import { describe, expect, it } from 'vitest'
import { Blob } from 'node:buffer'
import { createHash } from 'node:crypto'
import { hashBlob } from './hashCore'
import { DEFAULT_CHUNK_SIZE } from './types'

describe('incremental upload checksums', () => {
  it('matches SHA-256 known vector and preserves slice order', async () => {
    const progress: number[] = []
    const result = await hashBlob(new Blob(['abc']) as unknown as globalThis.Blob, 2, bytes => progress.push(bytes))
    expect(result.sha256).toBe('ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')
    expect(result.chunk_hashes).toEqual(['ab', 'c'].map(text => createHash('sha256').update(text).digest('hex')))
    expect(progress).toEqual([2, 3])
  })
  it('never reads the whole file and bounds memory to one 8 MiB slice', async () => {
    const input = new Uint8Array(DEFAULT_CHUNK_SIZE + 17).fill(37)
    const blob = new Blob([input])
    const sizes: number[] = []
    const file = { size: blob.size, arrayBuffer: () => { throw new Error('whole file read forbidden') }, slice: (start: number, end: number) => { sizes.push(end - start); return blob.slice(start, end) } }
    const result = await hashBlob(file as unknown as globalThis.Blob)
    expect(result.sha256).toBe(createHash('sha256').update(input).digest('hex'))
    expect(sizes).toEqual([DEFAULT_CHUNK_SIZE, 17])
    expect(result.chunk_hashes).toHaveLength(2)
  })
  it('stops between slices and rejects empty files', async () => {
    const controller = new AbortController()
    await expect(hashBlob(new Blob(['abcd']) as unknown as globalThis.Blob, 2, () => controller.abort(), controller.signal)).rejects.toMatchObject({ name: 'AbortError' })
    await expect(hashBlob(new Blob([]) as unknown as globalThis.Blob)).rejects.toThrow('文件为空')
  })
})
