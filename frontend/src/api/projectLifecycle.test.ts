import { beforeEach, expect, it, vi } from 'vitest'
import { projectApi, projectRecycleApi } from './index'
import { api } from './client'
vi.mock('./client', () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() } }))
const id = 'cache-lifecycle-fixture'
beforeEach(() => { vi.resetAllMocks(); projectApi.invalidate(id) })
it('fresh reads preserve server versions after a failed update and observe the successful update', async () => {
 vi.mocked(api.get).mockResolvedValueOnce({ data: { id, version: 3 } }).mockResolvedValueOnce({ data: { id, version: 3 } }).mockResolvedValueOnce({ data: { id, version: 4 } })
 vi.mocked(api.put).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ data: { id, version: 4 } })
 await projectApi.get(id); await expect(projectApi.update(id, { version: 3 })).rejects.toThrow('offline')
 expect(await projectApi.get(id)).toEqual({ id, version: 3 }); expect(api.get).toHaveBeenCalledTimes(2)
 await projectApi.update(id, { version: 3 }); expect(await projectApi.get(id)).toEqual({ id, version: 4 }); expect(api.get).toHaveBeenCalledTimes(3)
})
it('does not retain an active-project cache after deletion or restoration of its exact generation', async () => {
 vi.mocked(api.get).mockResolvedValueOnce({ data: { id, version: 3 } }).mockRejectedValueOnce(new Error('deleted')).mockResolvedValueOnce({ data: { id, version: 6 } })
 vi.mocked(api.delete).mockResolvedValue({ data: { deletion_id: 'd1', version: 4, backup: { available: true } } }); vi.mocked(api.post).mockResolvedValue({ data: { project_id: id, version: 6 } })
 await projectApi.get(id); await projectApi.remove(id, { version: 3 })
 expect(api.delete).toHaveBeenCalledWith(`/projects/${id}`, expect.objectContaining({ params: { version: 3 } })); await expect(projectApi.get(id)).rejects.toThrow('deleted')
 await projectRecycleApi.restore(id, { version: 4, deletion_id: 'd1' }); expect(api.post).toHaveBeenCalledWith(`/project-recycle-bin/projects/${id}/restore`, { version: 4, deletion_id: 'd1' }, expect.objectContaining({ timeout: expect.any(Number) }))
 expect(await projectApi.get(id)).toEqual({ id, version: 6 })
})
it('downloads a scoped project deletion backup rather than the full system backup', async () => {
 const blob = new Blob(['QA project backup']); vi.mocked(api.get).mockResolvedValue({ data: blob })
 expect(await projectRecycleApi.downloadBackup(id, 'd1')).toBe(blob)
 expect(api.get).toHaveBeenCalledWith(`/project-recycle-bin/projects/${id}/backup`, expect.objectContaining({ params: { deletion_id: 'd1' }, responseType: 'blob' }))
 expect(vi.mocked(api.get).mock.calls.some(([url]) => url.includes('/system/'))).toBe(false)
})
