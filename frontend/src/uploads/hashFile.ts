import type { FileHashes } from './hashCore'
import { DEFAULT_CHUNK_SIZE } from './types'

export async function hashFile(file: Blob, signal: AbortSignal, progress?: (bytes: number) => void): Promise<FileHashes> {
  signal.throwIfAborted()
  let worker: Worker
  try {
    if (typeof Worker === 'undefined') throw new Error('No worker')
    worker = new Worker(new URL('./hashWorker.ts', import.meta.url), { type: 'module' })
  } catch {
    const { hashBlob } = await import('./hashCore')
    return hashBlob(file, DEFAULT_CHUNK_SIZE, progress, signal)
  }
  return new Promise((resolve, reject) => {
    const finish = (result?: FileHashes, error?: unknown) => {
      signal.removeEventListener('abort', abort); worker.terminate()
      if (error) reject(error); else resolve(result!)
    }
    const abort = () => finish(undefined, signal.reason ?? new DOMException('Cancelled', 'AbortError'))
    signal.addEventListener('abort', abort, { once: true })
    worker.onmessage = event => {
      if (event.data.type === 'progress') progress?.(event.data.bytes)
      if (event.data.type === 'done') finish(event.data.result)
      if (event.data.type === 'error') finish(undefined, new Error(event.data.message))
    }
    worker.onerror = () => finish(undefined, new Error('文件校验失败，请保留原文件后重试'))
    worker.postMessage({ file, chunkSize: DEFAULT_CHUNK_SIZE })
  })
}
