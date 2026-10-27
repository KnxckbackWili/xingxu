import type { UploadJob } from './types'

const DATABASE = 'xingxu-resumable-uploads-v1'
const JOBS = 'jobs'
const FILES = 'files'
let pending: Promise<IDBDatabase> | undefined
const transientJobs = new Map<string, UploadJob>()
const transientFiles = new Map<string, Blob>()

function database(): Promise<IDBDatabase> {
  if (pending) return pending
  pending = new Promise<IDBDatabase>((resolve, reject) => {
    if (typeof indexedDB === 'undefined') { reject(new Error('此浏览器不支持离线文件存储')); return }
    const request = indexedDB.open(DATABASE, 1)
    request.onupgradeneeded = () => {
      const db = request.result
      const jobs = db.createObjectStore(JOBS, { keyPath: 'key' })
      jobs.createIndex('owner', 'owner_id')
      db.createObjectStore(FILES, { keyPath: 'key' })
    }
    request.onerror = () => reject(request.error ?? new Error('无法打开离线上传队列'))
    request.onblocked = () => reject(new Error('离线上传队列被另一窗口占用，请稍后重试'))
    request.onsuccess = () => {
      request.result.onversionchange = () => { request.result.close(); pending = undefined }
      resolve(request.result)
    }
  }).catch(error => { pending = undefined; throw error })
  return pending
}

function writable(db: IDBDatabase, names: string[]) {
  try { return db.transaction(names, 'readwrite', { durability: 'strict' }) }
  catch { return db.transaction(names, 'readwrite') }
}
function complete(tx: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve()
    tx.onabort = tx.onerror = () => reject(tx.error ?? new Error('离线存储未完成，原文件尚未保存'))
  })
}
function value<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error ?? new Error('读取离线上传队列失败'))
  })
}

function newer(a: UploadJob | undefined, b: UploadJob | undefined) {
  if (!a) return b
  if (!b) return a
  if (a.phase === 'completed') return a
  if (b.phase === 'completed') return b
  return a.updated_at > b.updated_at ? a : b
}

/** File bytes live in a separate store, so progress updates never rewrite GiB blobs. */
export const uploadStorage = {
  async insert(job: UploadJob, file: Blob): Promise<UploadJob> {
    transientFiles.set(job.key, file)
    try {
      const db = await database()
      const saved = { ...job, file: null, durable_file: true, metadata_durable: true }
      const tx = writable(db, [JOBS, FILES]); const done = complete(tx)
      tx.objectStore(JOBS).put(saved)
      tx.objectStore(FILES).put({ key: job.key, owner_id: job.owner_id, blob: file })
      await done
      transientJobs.delete(job.key)
      return saved
    } catch {
      const fallback = { ...job, file: null, durable_file: false, metadata_durable: false }
      // Retain small resume metadata where possible, without claiming the Blob
      // survived. The caller must keep the selected File on a failed offline save.
      try {
        const db = await database(); const tx = writable(db, [JOBS]); const done = complete(tx)
        const metadata = { ...fallback, metadata_durable: true }
        tx.objectStore(JOBS).put(metadata); await done
        return metadata
      } catch { transientJobs.set(job.key, fallback) }
      return fallback
    }
  },
  async get(owner: string, key: string): Promise<UploadJob | undefined> {
    let stored: UploadJob | undefined
    try {
      const db = await database()
      stored = await value(db.transaction(JOBS).objectStore(JOBS).get(key))
    } catch { /* A volatile job remains usable in its original tab. */ }
    const result = newer(stored, transientJobs.get(key))
    return result?.owner_id === owner ? result : undefined
  },
  async list(owner: string): Promise<UploadJob[]> {
    const rows = new Map<string, UploadJob>()
    try {
      const db = await database()
      const items: UploadJob[] = await value(db.transaction(JOBS).objectStore(JOBS).index('owner').getAll(owner))
      for (const item of items) if (item.owner_id === owner) rows.set(item.key, item)
    } catch { /* Do not read another account or the old localStorage op queue. */ }
    for (const item of transientJobs.values()) if (item.owner_id === owner) rows.set(item.key, newer(rows.get(item.key), item)!)
    return [...rows.values()].sort((a, b) => a.created_at - b.created_at)
  },
  async file(owner: string, key: string): Promise<Blob | undefined> {
    const record = await this.get(owner, key)
    if (!record) return undefined
    if (transientFiles.has(key)) return transientFiles.get(key)
    try {
      const db = await database()
      const stored = await value<{ owner_id: string; blob: Blob } | undefined>(db.transaction(FILES).objectStore(FILES).get(key))
      return stored?.owner_id === owner ? stored.blob : undefined
    } catch { return undefined }
  },
  async update(owner: string, key: string, change: (job: UploadJob) => UploadJob): Promise<UploadJob | undefined> {
    let callbackError: unknown
    try {
      const db = await database(); const tx = writable(db, [JOBS]); const done = complete(tx)
      let result: UploadJob | undefined
      const request = tx.objectStore(JOBS).get(key)
      request.onsuccess = () => {
        const current = newer(request.result, transientJobs.get(key))
        if (!current || current.owner_id !== owner) return
        try {
          result = { ...change(current), file: null, metadata_durable: true, updated_at: Date.now() }
          tx.objectStore(JOBS).put(result)
        } catch (error) { callbackError = error; tx.abort() }
      }
      await done
      transientJobs.delete(key)
      return result
    } catch (error) {
      if (callbackError) throw callbackError
      const current = await this.get(owner, key)
      if (!current) throw error
      const result = { ...change(current), file: null, metadata_durable: false, updated_at: Date.now() }
      transientJobs.set(key, result)
      return result
    }
  },
  async replaceFile(owner: string, key: string, file: Blob): Promise<UploadJob> {
    const current = await this.get(owner, key)
    if (!current) throw new Error('上传记录不存在或不属于当前账号')
    if (file.size !== current.intent.size) throw new Error('文件大小与原上传不同，请重新选择原文件')
    return this.insert({ ...current, error: '', phase: 'queued' }, file)
  },
  async releaseFile(owner: string, key: string) {
    if (!(await this.get(owner, key))) return
    transientFiles.delete(key)
    try { const db = await database(); const tx = writable(db, [FILES]); const done = complete(tx); tx.objectStore(FILES).delete(key); await done }
    catch { /* A later explicit removal retries freeing its persisted Blob. */ }
  },
  async remove(owner: string, key: string) {
    if (!(await this.get(owner, key))) return
    const db = await database(); const tx = writable(db, [JOBS, FILES]); const done = complete(tx)
    tx.objectStore(JOBS).delete(key); tx.objectStore(FILES).delete(key); await done
    transientJobs.delete(key); transientFiles.delete(key)
  },
}
