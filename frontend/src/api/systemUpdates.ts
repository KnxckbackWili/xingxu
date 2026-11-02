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
  /** github_release: install the CI image of the newest vX.Y.Z tag; gitea: build the source on the host. */
  kind?: 'github_release' | 'gitea'
  image?: string
}
export interface ReleaseNote { version: string; body: string }
export interface UpdateTrust {
  status: 'pending' | 'trusted' | 'rejected'
  method?: 'commit' | 'signed_tag' | 'release_image'
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
  kind?: 'github_release'
  tag?: string
  image?: string
  notes?: ReleaseNote[]
  release_url?: string
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
  runner: { online: boolean; last_seen: string | null; protocol: number; release_images?: boolean; trust?: { configured: boolean; protocol: 1 } }
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
