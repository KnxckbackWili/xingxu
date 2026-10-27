import { api } from './client'
export type StorageProject = { project_id: string; project_name: string; state?: string; can_cleanup?: boolean; bytes: number; file_count: number; removed_bytes: number; removed_file_count: number; temporary_bytes: number; missing_file_count?: number; storage_warnings?: string[] }
export type StorageOverview = { max_upload_size: number; bytes: number; file_count: number; removed_bytes: number; temporary_bytes: number; projects: StorageProject[] }
export type CleanupPreview = { project_id: string; keep_periods: number; fingerprint: string; candidates: { attachment_id: string; filename: string; file_size: number; sha256: string; documents: { id: string; code: string; name: string; period_key: string | null }[]; versions: { id: string; uploaded_at: string | null; uploaded_by_name: string }[] }[]; candidate_bytes: number; protected: { attachment_id: string; filename: string; reason: string }[]; milestone_protection: { event_key: string; precision: string; basis: string }[] }
const base = (id: string) => `/projects/${encodeURIComponent(id)}/storage`
export const storageApi = {
  overview: async (): Promise<StorageOverview> => (await api.get('/system/storage')).data,
  project: async (id: string): Promise<StorageProject> => (await api.get(base(id))).data,
  preview: async (id: string, keep: number): Promise<CleanupPreview> => (await api.post(`${base(id)}/cleanup-preview`, { keep_periods: keep })).data,
  confirm: async (id: string, preview: CleanupPreview, reason: string): Promise<{ receipt_id: string; removed_files: number; removed_bytes: number; released_bytes?: number; pending_reclaim_bytes?: number; warning?: string }> => (await api.post(`${base(id)}/cleanup-confirm`, { keep_periods: preview.keep_periods, fingerprint: preview.fingerprint, reason })).data,
}
