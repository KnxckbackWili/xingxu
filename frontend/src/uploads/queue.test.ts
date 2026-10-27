import { beforeEach, describe, expect, it, vi } from 'vitest'
import { IDBFactory } from 'fake-indexeddb'
import { Blob } from 'node:buffer'
import type { UploadIntent, UploadSession } from './types'
const h = vi.hoisted(() => ({ owner: 'a' as string | null, revision: 1, limits: vi.fn(), start: vi.fn(), status: vi.fn(), chunk: vi.fn(), finish: vi.fn(), cancel: vi.fn(), hash: vi.fn() }))
vi.mock('../offline/queue', () => ({ getOfflineAccount: () => h.owner, getOfflineAccountRevision: () => h.revision, OFFLINE_ACCOUNT_EVENT: 'account-test' }))
vi.mock('../api/client', () => ({ errMsg: (error: Error) => error.message }))
vi.mock('./hashFile', () => ({ hashFile: h.hash }))
vi.mock('./transport', () => ({ uploadTransport: h }))
const sha = 'a'.repeat(64)
const partSha = 'b'.repeat(64)
const file = (size = 3) => Object.assign(new Blob([new Uint8Array(size)]), { name: '证据.bin', lastModified: 123 }) as unknown as File
const network = () => Object.assign(new Error('interrupted'), { isAxiosError: true })
const result = { file: { id: 'real-file' }, documents: [{ id: 'real-doc', status: 'submitted' }] }
const online = (value: boolean) => Object.defineProperty(navigator, 'onLine', { value, configurable: true })
let intent: UploadIntent
const session = (patch: Partial<UploadSession> = {}): UploadSession => ({ id: 'session1', project_id: 'p', client_uuid: intent.client_uuid, filename: intent.filename, size: intent.size, sha256: intent.sha256, state: 'open', chunk_size: 8388608, total_chunks: Math.ceil(intent.size / 8388608), received: [], expires_at: '2026-12-01', ...patch })
beforeEach(() => {
  vi.resetModules(); vi.clearAllMocks(); vi.stubGlobal('indexedDB', new IDBFactory()); online(true); h.owner = 'a'; h.revision++
  h.limits.mockResolvedValue({ max_upload_size: 2147483648 })
  h.hash.mockImplementation(async (blob: Blob) => ({ sha256: sha, chunk_hashes: Array(Math.ceil(blob.size / 8388608)).fill(partSha) }))
  h.start.mockImplementation(async (_: string, body: UploadIntent) => { intent = body; return session() })
  h.status.mockImplementation(async () => session())
  h.chunk.mockImplementation(async (_p: string, _s: string, index: number, blob: Blob) => ({ index, size: blob.size, sha256: partSha }))
  h.finish.mockResolvedValue(result); h.cancel.mockResolvedValue({ state: 'cancelled' })
})
describe('resumable upload queue', () => {
  it('resumes only missing verified slices with the original session and never repeats formal versions', async () => {
    const { uploadQueue } = await import('./queue')
    h.chunk.mockImplementationOnce(async (_p: string, _s: string, index: number, blob: Blob) => ({ index, size: blob.size, sha256: partSha })).mockRejectedValueOnce(network())
    await expect(uploadQueue.upload('p', file(8388611), { documentIds: ['d'], milestoneDates: { handover: '2026-10-27' } })).rejects.toMatchObject({ name: 'UploadQueuedError' })
    const [job] = await uploadQueue.list()
    expect(job).toMatchObject({ phase: 'paused', session_id: 'session1', uploaded_bytes: 8388608, durable_file: true })
    h.status.mockResolvedValue(session({ received: [{ index: 0, size: 8388608, sha256: partSha }] }))
    expect(await uploadQueue.retry(job.key)).toEqual(result)
    expect(h.chunk.mock.calls.map(call => call[2])).toEqual([0, 1, 1])
    expect(h.start).toHaveBeenCalledTimes(1)
    expect(intent.milestone_dates).toEqual({ handover: '2026-10-27' })
    expect(await uploadQueue.retry(job.key)).toEqual(result)
    expect(h.finish).toHaveBeenCalledTimes(1)
  })
  it('retries a timed-out start using the same immutable UUID', async () => {
    const { uploadQueue } = await import('./queue')
    h.start.mockRejectedValueOnce(network())
    const original = file()
    await expect(uploadQueue.upload('p', original, { documentIds: ['d'] })).rejects.toMatchObject({ name: 'UploadQueuedError' })
    await uploadQueue.upload('p', original, { documentIds: ['d'] })
    expect(h.start.mock.calls[0][1]).toEqual(h.start.mock.calls[1][1])
    expect(h.finish).toHaveBeenCalledTimes(1)
  })
  it('halts when the account changes during a request and hides the original queue from the new account', async () => {
    const { uploadQueue } = await import('./queue')
    h.chunk.mockImplementationOnce(async (_p: string, _s: string, index: number, blob: Blob) => { h.owner = 'b'; h.revision++; return { index, size: blob.size, sha256: partSha } })
    await expect(uploadQueue.upload('p', file())).rejects.toMatchObject({ name: 'UploadQueuedError' })
    expect(h.finish).not.toHaveBeenCalled()
    expect(await uploadQueue.list()).toEqual([])
    h.owner = 'a'; h.revision++
    expect((await uploadQueue.list())[0]).toMatchObject({ phase: 'paused', pause_reason: 'account' })
  })
  it('pauses permission failures without automatic resend and preserves the original file', async () => {
    const { uploadQueue } = await import('./queue')
    h.chunk.mockRejectedValueOnce(Object.assign(new Error('forbidden'), { response: { status: 403 } }))
    await expect(uploadQueue.upload('p', file())).rejects.toThrow('forbidden')
    const [job] = await uploadQueue.list()
    expect(job).toMatchObject({ phase: 'paused', pause_reason: 'permission', durable_file: true })
    await uploadQueue.sync()
    expect(h.chunk).toHaveBeenCalledTimes(1)
  })
  it('does not auto-retry corrupt session metadata or a mismatched replacement', async () => {
    const { uploadQueue } = await import('./queue')
    h.start.mockImplementationOnce(async (_: string, body: UploadIntent) => { intent = body; return session({ sha256: 'wrong' }) })
    await expect(uploadQueue.upload('p', file())).rejects.toThrow('会话与原文件不一致')
    const [job] = await uploadQueue.list()
    expect(job.phase).toBe('error')
    await uploadQueue.sync(); expect(h.start).toHaveBeenCalledTimes(1)
    h.hash.mockResolvedValueOnce({ sha256: 'c'.repeat(64), chunk_hashes: [partSha] })
    await expect(uploadQueue.retry(job.key, file())).rejects.toThrow('SHA-256不同')
    expect(h.start).toHaveBeenCalledTimes(1)
  })
  it('claims offline success only after both Blob and metadata persist', async () => {
    const { uploadQueue } = await import('./queue')
    online(false)
    await expect(uploadQueue.upload('p', file())).rejects.toMatchObject({ name: 'UploadQueuedError' })
    expect(h.start).not.toHaveBeenCalled()
    expect((await uploadQueue.list())[0]).toMatchObject({ durable_file: true, metadata_durable: true, phase: 'queued' })
    vi.stubGlobal('indexedDB', { open() { throw new Error('no storage') } }); vi.resetModules()
    const other = (await import('./queue')).uploadQueue
    await expect(other.upload('p', file())).rejects.toThrow('未保存到离线队列')
    expect(h.start).not.toHaveBeenCalled()
  })
  it('keeps a finished server result after a finish timeout and refuses to revive a cancelled job', async () => {
    const { uploadQueue } = await import('./queue')
    h.finish.mockRejectedValueOnce(network())
    await expect(uploadQueue.upload('p', file())).rejects.toMatchObject({ name: 'UploadQueuedError' })
    const [job] = await uploadQueue.list()
    h.status.mockResolvedValue(session({ state: 'finished', received: [{ index: 0, size: 3, sha256: partSha }], result: result as UploadSession['result'] }))
    expect(await uploadQueue.retry(job.key)).toEqual(result)
    expect(h.finish).toHaveBeenCalledTimes(1)
    online(false); await expect(uploadQueue.upload('p', file())).rejects.toMatchObject({ name: 'UploadQueuedError' })
    const stopped = (await uploadQueue.list()).find(row => row.phase === 'queued')!
    await uploadQueue.cancel(stopped.key)
    await expect(uploadQueue.retry(stopped.key)).rejects.toThrow('已停止')
  })
})
