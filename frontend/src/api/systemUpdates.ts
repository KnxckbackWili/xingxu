import { api } from './client'

export interface UpdateSource {
  id: string
  name: string
  is_default: boolean
  repository_url: string
  ref: string
  has_token: boolean
  allow_http: boolean
  revision: number
}
export interface UpdateTrust {
  status: 'pending' | 'trusted' | 'rejected'
  method?: 'commit' | 'signed_tag'
  message: string
}
export interface UpdateCheck {
  id: string
  source_revision: number
  commit: string
  version: string
  checked_at: string
  update_available: boolean
  trust?: UpdateTrust
}
export interface UpdateJob {
  id: string
  status: string
  phase: string
  message: string
  target_version: string
  target_commit: string
  created_at: string
  updated_at: string
}
export interface SystemUpdates {
  current: { version: string; commit: string }
  source: UpdateSource
  sources: UpdateSource[]
  active_source_id: string
  maintenance?: boolean
  runner: { online: boolean; last_seen: string | null; protocol: number; trust?: { configured: boolean; protocol: 1 } }
  check: UpdateCheck | null
  job: UpdateJob | null
}
export interface UpdateSourceInput {
  name?: string
  repository_url: string
  ref: string
  allow_http: boolean
  revision: number
  token?: string
  clear_token?: boolean
}
export const systemUpdatesApi = {
  get: async (): Promise<SystemUpdates> => (await api.get('/system/updates')).data,
  saveSource: async (body: UpdateSourceInput): Promise<SystemUpdates> => (await api.put('/system/updates/source', body)).data,
  addSource: async (body: UpdateSourceInput & { name: string }): Promise<SystemUpdates> => (await api.post('/system/updates/sources', body)).data,
  selectSource: async (sourceId: string, revision: number): Promise<SystemUpdates> => (await api.post(`/system/updates/sources/${encodeURIComponent(sourceId)}/select`, { revision })).data,
  deleteSource: async (sourceId: string, revision: number): Promise<SystemUpdates> => (await api.delete(`/system/updates/sources/${encodeURIComponent(sourceId)}`, { params: { revision } })).data,
  check: async (sourceRevision: number): Promise<SystemUpdates> => (await api.post('/system/updates/check', { source_revision: sourceRevision })).data,
  install: async (checkId: string): Promise<SystemUpdates> => (await api.post('/system/updates/install', { check_id: checkId, confirm: true })).data,
}
