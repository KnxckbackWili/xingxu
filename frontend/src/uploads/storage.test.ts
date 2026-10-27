import { beforeEach, describe, expect, it, vi } from 'vitest'
import { IDBFactory } from 'fake-indexeddb'
import { Blob } from 'node:buffer'
import type { UploadJob } from './types'
const row = (owner: string, id: string): UploadJob => ({ key: `${owner}:${id}`, owner_id: owner, project_id: 'p', created_at: 1, updated_at: 1, intent: { client_uuid: id, filename: 'a.txt', size: 3, sha256: '', content_type: 'text/plain', document_ids: [], note: '', entity_type: 'project', entity_id: '', category: '' }, file: null, durable_file: false, metadata_durable: false, last_modified: 1, session_id: null, chunk_hashes: [], phase: 'queued', hashed_bytes: 0, uploaded_bytes: 0, error: '' })
beforeEach(() => { vi.resetModules(); vi.stubGlobal('indexedDB', new IDBFactory()) })
describe('durable upload storage', () => {
  it('persists bytes independently of metadata and isolates accounts across reload', async () => {
    let { uploadStorage } = await import('./storage')
    const saved = await uploadStorage.insert(row('a', 'one'), new Blob(['abc']) as unknown as globalThis.Blob)
    expect(saved).toMatchObject({ durable_file: true, metadata_durable: true })
    await uploadStorage.update('a', saved.key, current => ({ ...current, uploaded_bytes: 2 }))
    vi.resetModules(); ({ uploadStorage } = await import('./storage'))
    expect(await (await uploadStorage.file('a', saved.key))!.text()).toBe('abc')
    expect((await uploadStorage.get('a', saved.key))?.uploaded_bytes).toBe(2)
    expect(await uploadStorage.get('b', saved.key)).toBeUndefined()
    expect(await uploadStorage.file('b', saved.key)).toBeUndefined()
    expect(await uploadStorage.list('b')).toEqual([])
  })
  it('retains a file in its original tab without claiming offline durability when storage fails', async () => {
    vi.stubGlobal('indexedDB', { open() { throw new DOMException('full', 'QuotaExceededError') } })
    const { uploadStorage } = await import('./storage')
    const file = new Blob(['abc']) as unknown as globalThis.Blob
    const saved = await uploadStorage.insert(row('a', 'one'), file)
    expect(saved).toMatchObject({ durable_file: false, metadata_durable: false })
    expect(await uploadStorage.file('a', saved.key)).toBe(file)
    expect(await uploadStorage.file('b', saved.key)).toBeUndefined()
  })
  it('keeps a lease refusal atomic and does not replace the other tab owner', async () => {
    const { uploadStorage } = await import('./storage')
    await uploadStorage.insert({ ...row('a', 'one'), lease_id: 'tab1' }, new Blob(['abc']) as unknown as globalThis.Blob)
    await expect(uploadStorage.update('a', 'a:one', () => { throw new Error('busy') })).rejects.toThrow('busy')
    expect((await uploadStorage.get('a', 'a:one'))?.lease_id).toBe('tab1')
  })
})
