import { sha256 } from '@noble/hashes/sha2.js'
import { DEFAULT_CHUNK_SIZE } from './types'

const hex = (bytes: Uint8Array) => Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')
export type FileHashes = { sha256: string; chunk_hashes: string[] }

/** Both digests use the same bounded slices; no whole-file ArrayBuffer exists. */
export async function hashBlob(file: Blob, chunkSize = DEFAULT_CHUNK_SIZE,
  progress?: (bytes: number) => void, signal?: AbortSignal): Promise<FileHashes> {
  if (!Number.isInteger(chunkSize) || chunkSize < 1 || chunkSize > DEFAULT_CHUNK_SIZE) throw new Error('分片大小无效')
  if (!Number.isSafeInteger(file.size) || file.size < 1) throw new Error('文件为空或大小无效')
  const whole = sha256.create()
  const parts: string[] = []
  for (let offset = 0; offset < file.size; offset += chunkSize) {
    signal?.throwIfAborted()
    const bytes = new Uint8Array(await file.slice(offset, Math.min(file.size, offset + chunkSize)).arrayBuffer())
    signal?.throwIfAborted()
    whole.update(bytes); parts.push(hex(sha256(bytes)))
    progress?.(Math.min(file.size, offset + bytes.length))
    // Also keep the fallback on the main thread responsive to cancellation.
    await new Promise<void>(resolve => setTimeout(resolve, 0))
  }
  return { sha256: hex(whole.digest()), chunk_hashes: parts }
}
