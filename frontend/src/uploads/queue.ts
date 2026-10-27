import { getOfflineAccount, getOfflineAccountRevision, OFFLINE_ACCOUNT_EVENT } from '../offline/queue'
import { errMsg } from '../api/client'
import axios from 'axios'
import { hashFile } from './hashFile'
import { uploadStorage } from './storage'
import { uploadTransport } from './transport'
import { DEFAULT_CHUNK_SIZE, DEFAULT_UPLOAD_LIMIT, UploadQueuedError, uploadJobKey } from './types'
import type { UploadJob, UploadOptions, UploadResult, UploadSession } from './types'

export const UPLOAD_QUEUE_EVENT = 'xingxu-upload-queue'
export const UPLOAD_COMPLETE_EVENT = 'xingxu-upload-completed'
const changed = () => window.dispatchEvent(new Event(UPLOAD_QUEUE_EVENT))
const online = () => navigator.onLine !== false
const uuid = () => {
  if (crypto.randomUUID) return crypto.randomUUID()
  const bytes = crypto.getRandomValues(new Uint8Array(16)); bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128
  return Array.from(bytes, (byte, i) => `${[4, 6, 8, 10].includes(i) ? '-' : ''}${byte.toString(16).padStart(2, '0')}`).join('')
}
class LeaseBusy extends Error {}
class ScopeChanged extends Error {}
class Interrupted extends Error {}
class JobStopped extends Error {}
type Running = { controller: AbortController; owner: string; revision: number }
const active = new Map<string, Running>()
const operations = new Map<string, Promise<UploadResult>>()
const intents = new WeakMap<Blob, Map<string, string>>()
let tail: Promise<unknown> = Promise.resolve()
let synchronizing: Promise<void> | null = null
let cachedLimit = DEFAULT_UPLOAD_LIMIT

function scope(owner: string, revision: number, signal: AbortSignal, requireOnline = true) {
  signal.throwIfAborted()
  if (owner !== getOfflineAccount() || revision !== getOfflineAccountRevision()) throw new ScopeChanged('账号已变化，原上传仍绑定原账号')
  if (requireOnline && !online()) throw new Interrupted('网络已断开，上传将在联网后继续')
}
function safeSession(session: UploadSession, job: UploadJob) {
  if (session.project_id !== job.project_id || session.client_uuid !== job.intent.client_uuid || session.size !== job.intent.size
      || session.sha256 !== job.intent.sha256 || session.chunk_size !== DEFAULT_CHUNK_SIZE
      || session.total_chunks !== Math.ceil(job.intent.size / DEFAULT_CHUNK_SIZE)) throw new Error('服务器上传会话与原文件不一致，已停止')
}
async function patch(job: UploadJob, lease: string, changes: Partial<UploadJob>) {
  const result = await uploadStorage.update(job.owner_id, job.key, current => {
    if (current.lease_id !== lease) throw new LeaseBusy('另一窗口正在处理此文件')
    if (['completed', 'cancelled'].includes(current.phase) && changes.phase !== current.phase) throw new JobStopped('上传已结束')
    if (current.phase === 'paused' && current.pause_reason === 'user' && changes.phase && changes.phase !== 'paused') throw new JobStopped('上传已暂停')
    return { ...current, ...changes }
  })
  if (!result) throw new Error('本地上传记录已不存在')
  changed(); return result
}

async function processJob(owner: string, key: string): Promise<UploadResult> {
  const running = { owner, revision: getOfflineAccountRevision(), controller: new AbortController() }
  const { signal } = running.controller
  const lease = uuid()
  active.set(key, running)
  let job = await uploadStorage.get(owner, key)
  let heartbeat: ReturnType<typeof setInterval> | undefined
  try {
    if (!job) throw new Error('上传记录不存在')
    scope(owner, running.revision, signal)
    if (job.phase === 'completed' && job.result) return job.result
    if (job.phase === 'cancelled') throw new Error('上传已停止；已生成的正式文件不受此操作影响')
    if (job.phase === 'paused' && ['user', 'permission'].includes(job.pause_reason ?? '')) {
      throw new UploadQueuedError(job.intent.client_uuid, '原文件已保留，请在上传队列中手动继续。')
    }
    job = await uploadStorage.update(owner, key, current => {
      if (current.lease_id && current.lease_until! > Date.now()) throw new LeaseBusy('另一窗口正在处理此文件')
      return { ...current, lease_id: lease, lease_until: Date.now() + 60_000 }
    })
    if (!job) throw new Error('上传记录不存在')
    heartbeat = setInterval(() => {
      void uploadStorage.update(owner, key, current => {
        if (current.lease_id !== lease) throw new LeaseBusy('上传已由另一窗口接续')
        return { ...current, lease_until: Date.now() + 60_000 }
      }).catch(() => running.controller.abort(new LeaseBusy('上传已由另一窗口接续')))
    }, 20_000)
    const file = await uploadStorage.file(owner, key)
    scope(owner, running.revision, signal)
    if (!file || file.size !== job.intent.size) {
      await patch(job, lease, { phase: 'needs_file', error: '本地文件未保留，请重新选择原文件；服务器分片仍可续传。' })
      throw new Error('请重新选择原文件后继续')
    }
    if (!job.intent.sha256 || !job.chunk_hashes.length) {
      job = await patch(job, lease, { phase: 'hashing', error: '', pause_reason: undefined })
      let last = 0
      const hashes = await hashFile(file, signal, bytes => {
        if (Date.now() - last < 250 && bytes !== file.size) return
        last = Date.now()
        void patch(job!, lease, { hashed_bytes: bytes }).catch(() => undefined)
      })
      scope(owner, running.revision, signal)
      if (job.intent.sha256 && job.intent.sha256 !== hashes.sha256) throw new Error('所选文件与原文件的SHA-256不同，请重新选择原文件')
      job = await patch(job, lease, { intent: { ...job.intent, sha256: hashes.sha256 }, chunk_hashes: hashes.chunk_hashes,
        hashed_bytes: file.size, phase: 'uploading' })
    }
    scope(owner, running.revision, signal)
    let session = job.session_id ? await uploadTransport.status(job.project_id, job.session_id, signal)
      : await uploadTransport.start(job.project_id, job.intent, signal)
    safeSession(session, job)
    if (session.state === 'expired') {
      scope(owner, running.revision, signal)
      session = await uploadTransport.start(job.project_id, job.intent, signal)
      scope(owner, running.revision, signal); safeSession(session, job)
    }
    job = await patch(job, lease, { session_id: session.id })
    if (session.state !== 'open' && session.state !== 'finished') throw new Error('服务器会话已失效或停止，请保留原文件并重新开始此项上传')
    const received = new Map(session.received.map(part => [part.index, part]))
    if (received.size !== session.received.length) throw new Error('服务器分片清单重复，已停止')
    let confirmed = 0
    for (const part of session.received) {
      const expected = Math.min(DEFAULT_CHUNK_SIZE, file.size - part.index * DEFAULT_CHUNK_SIZE)
      if (!Number.isInteger(part.index) || part.index < 0 || part.index >= session.total_chunks || part.size !== expected || job.chunk_hashes[part.index] !== part.sha256) throw new Error('已存分片与原文件不一致，已停止')
      confirmed += part.size
    }
    job = await patch(job, lease, { phase: 'uploading', uploaded_bytes: confirmed, error: '', pause_reason: undefined })
    for (let index = 0; session.state === 'open' && index < session.total_chunks; index++) {
      scope(owner, running.revision, signal)
      if (received.has(index)) continue
      const start = index * DEFAULT_CHUNK_SIZE
      const part = file.slice(start, Math.min(file.size, start + DEFAULT_CHUNK_SIZE))
      const ack = await uploadTransport.chunk(job.project_id, session.id, index, part, job.chunk_hashes[index], signal)
      if (ack.index !== index || ack.size !== part.size || ack.sha256 !== job.chunk_hashes[index]) throw new Error('分片回执与原文件不一致，已停止')
      scope(owner, running.revision, signal)
      confirmed += part.size
      job = await patch(job, lease, { uploaded_bytes: confirmed })
    }
    scope(owner, running.revision, signal)
    job = await patch(job, lease, { phase: 'finishing', error: '' })
    const result = session.state === 'finished' && session.result ? session.result : await uploadTransport.finish(job.project_id, session.id, signal)
    scope(owner, running.revision, signal)
    job = await patch(job, lease, { phase: 'completed', uploaded_bytes: file.size, result, error: '' })
    await uploadStorage.releaseFile(owner, key)
    changed(); window.dispatchEvent(new Event(UPLOAD_COMPLETE_EVENT)); return result
  } catch (error: unknown) {
    if (error instanceof LeaseBusy) {
      if (job?.durable_file && job.metadata_durable) throw new UploadQueuedError(job.intent.client_uuid, '另一窗口正在继续此文件，当前队列会在完成后更新。')
      throw new Error('另一窗口正在处理此文件；本地文件尚未持久保存，请保持页面并稍后重试。')
    }
    const current = await uploadStorage.get(owner, key)
    if (current?.phase === 'completed' && current.result) { scope(owner, running.revision, signal); return current.result }
    if (current && !['completed', 'cancelled', 'needs_file'].includes(current.phase) && current.lease_id === lease) {
      const status = (error as { response?: { status?: number } })?.response?.status
      const account = error instanceof ScopeChanged || owner !== getOfflineAccount() || running.revision !== getOfflineAccountRevision()
      const interrupted = signal.aborted || !online() || error instanceof Interrupted || error instanceof ScopeChanged || (axios.isAxiosError(error) && !error.response)
      const permission = status === 401 || status === 403 || status === 404
      const pausedByUser = current.pause_reason === 'user'
      job = await patch(current, lease, { phase: permission || interrupted || pausedByUser ? 'paused' : 'error',
        pause_reason: pausedByUser ? 'user' : account ? 'account' : permission ? 'permission' : interrupted ? 'offline' : undefined,
        error: account ? '账号已变化，请登录原账号后继续' : errMsg(error) })
      if ((interrupted || pausedByUser) && job.durable_file && job.metadata_durable) throw new UploadQueuedError(job.intent.client_uuid,
        pausedByUser ? '文件已保存并暂停，可在上传队列手动继续。' : account ? '原账号的上传已保留，重新登录原账号后可继续。' : undefined)
    }
    throw error
  } finally {
    if (heartbeat) clearInterval(heartbeat)
    if (active.get(key) === running) active.delete(key)
    await uploadStorage.update(owner, key, current => current.lease_id === lease ? { ...current, lease_id: undefined, lease_until: undefined } : current).catch(() => undefined)
    changed()
  }
}

function run(owner: string, key: string): Promise<UploadResult> {
  const existing = operations.get(key)
  if (existing) return existing
  const result = tail.then(() => processJob(owner, key))
  tail = result.catch(() => undefined)
  operations.set(key, result)
  void result.finally(() => { if (operations.get(key) === result) operations.delete(key) }).catch(() => undefined)
  return result
}

async function cancelRemote(job: UploadJob) {
  const revision = getOfflineAccountRevision(); const signal = new AbortController().signal
  scope(job.owner_id, revision, signal)
  const session = job.session_id ? await uploadTransport.status(job.project_id, job.session_id, signal) : await uploadTransport.start(job.project_id, job.intent, signal)
  scope(job.owner_id, revision, signal); safeSession(session, job)
  await uploadTransport.cancel(job.project_id, session.id, signal)
  scope(job.owner_id, revision, signal)
}

export const uploadQueue = {
  async list(): Promise<UploadJob[]> {
    const owner = getOfflineAccount(); const revision = getOfflineAccountRevision()
    if (!owner) return []
    const rows = await uploadStorage.list(owner)
    return owner === getOfflineAccount() && revision === getOfflineAccountRevision() ? rows : []
  },
  async upload(projectId: string, file: File, options: UploadOptions = {}): Promise<UploadResult> {
    const owner = getOfflineAccount(); const revision = getOfflineAccountRevision()
    if (!owner) throw new Error('请先登录后上传文件')
    if (!file.size) throw new Error('文件为空，不能提交资料')
    if (online()) {
      try { const limit = (await uploadTransport.limits()).max_upload_size; if (Number.isSafeInteger(limit) && limit > 0) cachedLimit = limit } catch { /* The server rechecks its current limit. */ }
    }
    if (owner !== getOfflineAccount() || revision !== getOfflineAccountRevision()) throw new Error('账号已切换，请重新选择上传')
    if (!Number.isSafeInteger(file.size) || file.size > cachedLimit) throw new Error(`文件超过当前上限 ${Math.floor(cachedLimit / 1024 / 1024)} MB`)
    const frozen = { document_ids: [...(options.documentIds ?? [])], note: options.note ?? '', entity_type: options.entityType ?? 'project' as const,
      entity_id: options.entityId ?? '', category: options.category ?? '', confidential: options.confidential,
      confidential_user_ids: options.confidentialUserIds ? [...options.confidentialUserIds] : undefined,
      milestone_dates: options.milestoneDates ? { ...options.milestoneDates } : undefined }
    const signature = JSON.stringify([owner, projectId, frozen])
    let map = intents.get(file)
    if (!map) { map = new Map(); intents.set(file, map) }
    let id = map.get(signature) ?? uuid()
    let key = uploadJobKey(owner, id)
    let job = await uploadStorage.get(owner, key)
    if (job?.phase === 'cancelled') { id = uuid(); key = uploadJobKey(owner, id); job = undefined }
    map.set(signature, id)
    if (!job) job = await uploadStorage.insert({ key, owner_id: owner, project_id: projectId, created_at: Date.now(), updated_at: Date.now(),
      intent: { ...frozen, client_uuid: id, filename: file.name, size: file.size, sha256: '', content_type: file.type || 'application/octet-stream' },
      file: null, durable_file: false, metadata_durable: false, last_modified: file.lastModified,
      session_id: null, chunk_hashes: [], phase: 'queued', hashed_bytes: 0, uploaded_bytes: 0, error: '' }, file)
    if (owner !== getOfflineAccount() || revision !== getOfflineAccountRevision()) throw new Error('账号已切换，原上传意图仍绑定原账号')
    changed()
    if (!online()) {
      if (!job.durable_file || !job.metadata_durable) throw new Error('未保存到离线队列，请保留当前选中文件，联网后重试或重新选择原文件。')
      throw new UploadQueuedError(id)
    }
    if (job.phase === 'error' || job.phase === 'needs_file' || job.phase === 'paused') {
      await uploadStorage.replaceFile(owner, key, file)
      await uploadStorage.update(owner, key, current => ({ ...current, phase: 'queued', pause_reason: undefined, error: '' }))
    }
    return run(owner, key)
  },
  async retry(key: string, file?: File) {
    const owner = getOfflineAccount(); const revision = getOfflineAccountRevision()
    if (!owner) throw new Error('请先登录')
    const job = await uploadStorage.get(owner, key)
    if (!job) throw new Error('上传记录不存在')
    if (job.phase === 'completed' && job.result) return job.result
    if (job.phase === 'cancelled') throw new Error('此项上传已停止，请从原页面创建新的上传')
    if (file) {
      if (file.size !== job.intent.size) throw new Error('大小不同，请重新选择原文件')
      // Always hash a replacement and compare the original immutable intent.
      const hashes = await hashFile(file, new AbortController().signal)
      if (job.intent.sha256 && hashes.sha256 !== job.intent.sha256) throw new Error('SHA-256不同，请重新选择原文件')
      if (owner !== getOfflineAccount() || revision !== getOfflineAccountRevision()) throw new Error('账号已切换')
      await uploadStorage.replaceFile(owner, key, file)
      await uploadStorage.update(owner, key, current => ({ ...current, intent: { ...current.intent, sha256: hashes.sha256 }, chunk_hashes: hashes.chunk_hashes }))
    }
    await uploadStorage.update(owner, key, current => ({ ...current, phase: 'queued', pause_reason: undefined, error: '' }))
    changed(); return run(owner, key)
  },
  async pause(key: string) {
    const owner = getOfflineAccount(); if (!owner) return
    const job = await uploadStorage.get(owner, key)
    if (!job || ['completed', 'cancelled', 'finishing'].includes(job.phase)) return
    await uploadStorage.update(owner, key, current => ({ ...current, phase: 'paused', pause_reason: 'user' }))
    active.get(key)?.controller.abort(new Error('已暂停上传'))
    changed()
  },
  async cancel(key: string) {
    const owner = getOfflineAccount(); if (!owner) throw new Error('请先登录')
    const job = await uploadStorage.get(owner, key)
    if (!job) return
    if (['completed', 'finishing'].includes(job.phase)) throw new Error('文件正在保存或已完成，停止传输不会删除正式文件')
    active.get(key)?.controller.abort(new Error('已停止上传'))
    const stopped = await uploadStorage.update(owner, key, current => ({ ...current, phase: 'cancelled', cancel_requested: !!current.intent.sha256 }))
    if (!stopped?.metadata_durable) throw new Error('停止状态尚未保存，请保持页面并稍后重试')
    await uploadStorage.releaseFile(owner, key)
    if (online() && stopped.cancel_requested) {
      await cancelRemote(stopped)
      await uploadStorage.update(owner, key, current => ({ ...current, cancel_requested: false }))
    }
    changed()
  },
  async removeCompleted(key: string) {
    const owner = getOfflineAccount(); if (!owner) return
    const job = await uploadStorage.get(owner, key)
    if (job && (job.phase === 'completed' || job.phase === 'cancelled' && !job.cancel_requested)) await uploadStorage.remove(owner, key)
    changed()
  },
  sync(): Promise<void> {
    if (synchronizing) return synchronizing
    synchronizing = (async () => {
      if (!online()) return
      const owner = getOfflineAccount(); if (!owner) return
      for (const job of await this.list()) {
        if (getOfflineAccount() !== owner) return
        if (job.cancel_requested) {
          try { await cancelRemote(job); await uploadStorage.update(owner, job.key, current => ({ ...current, cancel_requested: false })) } catch { /* Preserve the pending cancellation. */ }
        } else if (['queued', 'hashing', 'uploading', 'finishing'].includes(job.phase) || job.phase === 'paused' && ['offline', 'account'].includes(job.pause_reason ?? '')) {
          try { await run(owner, job.key) } catch { /* Each record keeps its own truthful state and error. */ }
        }
      }
    })().finally(() => { synchronizing = null; changed() })
    return synchronizing
  },
}

/** Called once by the app; account changes stop all work before a new account can send it. */
export function observeUploadQueue() {
  const stop = () => { for (const value of active.values()) value.controller.abort(new ScopeChanged('账号或网络已变化')); changed() }
  const resume = () => { void uploadQueue.sync() }
  const account = () => { stop(); resume() }
  const storage = () => { for (const value of active.values()) if (value.owner !== getOfflineAccount()) { stop(); break } }
  window.addEventListener(OFFLINE_ACCOUNT_EVENT, account)
  window.addEventListener('offline', stop); window.addEventListener('online', resume); window.addEventListener('storage', storage)
  const timer = setInterval(resume, 30_000)
  resume()
  return () => {
    clearInterval(timer); stop(); window.removeEventListener(OFFLINE_ACCOUNT_EVENT, account)
    window.removeEventListener('offline', stop); window.removeEventListener('online', resume); window.removeEventListener('storage', storage)
  }
}
