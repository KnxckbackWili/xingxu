import { api } from '../api/client'
import type { UploadIntent, UploadLimits, UploadResult, UploadSession } from './types'

const path = (pid: string, sid?: string) => `/projects/${encodeURIComponent(pid)}/uploads${sid ? '/' + encodeURIComponent(sid) : ''}`
export const uploadTransport = {
  limits: async (signal?: AbortSignal): Promise<UploadLimits> => (await api.get('/storage/limits', { signal, timeout: 15_000 })).data,
  start: async (pid: string, intent: UploadIntent, signal: AbortSignal): Promise<UploadSession> =>
    (await api.post(path(pid), intent, { signal, timeout: 30_000 })).data,
  status: async (pid: string, sid: string, signal: AbortSignal): Promise<UploadSession> =>
    (await api.get(path(pid, sid), { signal, timeout: 30_000 })).data,
  chunk: async (pid: string, sid: string, index: number, data: Blob, sha: string, signal: AbortSignal) =>
    (await api.put(`${path(pid, sid)}/chunks/${index}`, data, { signal, timeout: 120_000,
      headers: { 'Content-Type': 'application/octet-stream', 'X-Chunk-SHA256': sha } })).data,
  finish: async (pid: string, sid: string, signal: AbortSignal): Promise<UploadResult> =>
    (await api.post(`${path(pid, sid)}/finish`, undefined, { signal, timeout: 600_000 })).data,
  cancel: async (pid: string, sid: string, signal: AbortSignal) => (await api.delete(path(pid, sid), { signal })).data,
}
