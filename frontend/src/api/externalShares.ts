import { api } from './client'

export type ShareScope = 'project_progress' | 'vehicle_progress' | 'signoffs' | 'delivery_documents' | 'selected_documents'
export const SHARE_SCOPES: { value: ShareScope; label: string }[] = [
  { value: 'project_progress', label: '项目进度' }, { value: 'vehicle_progress', label: '车辆进度表' },
  { value: 'signoffs', label: '四类签单' }, { value: 'delivery_documents', label: '验收与交付资料（第7–8阶段）' },
  { value: 'selected_documents', label: '指定资料' },
]
export interface ExternalShare {
  id: string; project_id: string; scopes: ShareScope[]; document_ids: string[]
  created_at: string; expires_at: string; revoked_at: string | null; expired: boolean; version: number
}
export interface ShareOption { id: string; code: string; name: string; vehicle_label: string; period_key: string | null }
export interface ExternalAccess { id: string; time: string; ip: string; action: string; resource_id: string | null; status_code: number }
const base = (id: string) => `/projects/${encodeURIComponent(id)}/external-shares`
export const externalSharesApi = {
  list: async (projectId: string): Promise<{ shares: ExternalShare[]; document_options: ShareOption[] }> => (await api.get(base(projectId))).data,
  create: async (projectId: string, body: { scopes: ShareScope[]; document_ids: string[]; expires_at: string }): Promise<ExternalShare & { token: string }> => (await api.post(base(projectId), body)).data,
  revoke: async (projectId: string, row: ExternalShare): Promise<ExternalShare> => (await api.post(`${base(projectId)}/${encodeURIComponent(row.id)}/revoke`, { version: row.version })).data,
  access: async (projectId: string, id: string): Promise<ExternalAccess[]> => (await api.get(`${base(projectId)}/${encodeURIComponent(id)}/access`)).data,
}
