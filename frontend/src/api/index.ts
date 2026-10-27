import type { ProjectEvent } from '../constants/projectEvents'
import { api } from './client'

// ===== Auth =====
export const authApi = {
  login: (username: string, password: string) =>
    api.post('/auth/login', { username, password }).then((r) => r.data),
  me: () => api.get('/auth/me').then((r) => r.data),
  // 登出：后端清除 HttpOnly 会话 Cookie（写请求，前端自动带 X-CSRF-Token）
  logout: () => api.post('/auth/logout').then((r) => r.data),
}

// ===== Users (admin) =====
export const userApi = {
  list: () => api.get('/users').then((r) => r.data),
  create: (data: any) => api.post('/users', data).then((r) => r.data),
  update: (id: string, data: any) => api.put(`/users/${id}`, data).then((r) => r.data),
  listActive: () => api.get('/users/all-active').then((r) => r.data),
}

// ===== 人员不可用时段=====
export const availabilityApi = {
  listUnavailability: (userId: string) => api.get(`/users/${userId}/unavailability`).then((r) => r.data),
  createUnavailability: (userId: string, data: any) => api.post(`/users/${userId}/unavailability`, data).then((r) => r.data),
  updateUnavailability: (userId: string, id: string, data: any) => api.put(`/users/${userId}/unavailability/${id}`, data).then((r) => r.data),
  deleteUnavailability: (userId: string, id: string) => api.delete(`/users/${userId}/unavailability/${id}`).then((r) => r.data),
  assignmentCheck: (params: { user_id: string; work_date: string; exclude_project_id?: string }) =>
    api.get('/schedule/assignment-check', { params }).then((r) => r.data),
}

// ===== Projects =====
// Private project reads always recheck the current server scope and actor.
export const projectApi = {
  list: (expectedAccount?: string) => api.get('/projects', { headers: expectedAccount ? { 'X-AGV-Expected-Account': expectedAccount } : {} }).then((r) => r.data),
  get: (id: string, options?: { signal?: AbortSignal; expectedAccount?: string }) =>
    api.get(`/projects/${id}`, { signal: options?.signal, headers: options?.expectedAccount ? { 'X-AGV-Expected-Account': options.expectedAccount } : {} }).then((r) => r.data),
  create: (data: any) => api.post('/projects', data).then((r) => r.data),
  invalidate: (_id: string) => undefined,
  update: (id: string, data: any) => api.put(`/projects/${id}`, data).then((r) => { return r.data }),
  remove: async (id: string, data: { version: number; reason?: string }): Promise<ProjectDeletionReceipt> => {
    const response = await api.delete(`/projects/${encodeURIComponent(id)}`, { params: data, timeout: 600000 })
    return response.data
  },
  governanceRequests: (status?: string) => api.get('/projects/governance/requests', { params: { status } }).then((r) => r.data),
  requestGovernance: (id: string, data: any) => api.post(`/projects/${id}/governance-requests`, data).then((r) => r.data),
  reviewGovernance: (id: string, data: any) => api.post(`/projects/governance/requests/${id}/review`, data).then((r) => r.data),

  // Vehicles
  vehicles: (id: string) => api.get(`/projects/${id}/vehicles`).then((r) => r.data),
  addVehicle: (id: string, data: any) =>
    api.post(`/projects/${id}/vehicles`, data).then((r) => r.data),
  updateVehicle: (id: string, vid: string, data: any) =>
    api.put(`/projects/${id}/vehicles/${vid}`, data).then((r) => r.data),
  removeVehicle: (id: string, vid: string) =>
    api.delete(`/projects/${id}/vehicles/${vid}`).then((r) => r.data),
}

/** Project-only recovery never uses the full-system backup endpoint. */
export interface ProjectDeletionReceipt {
  message: string
  deletion_id: string
  project_id: string
  version: number
  backup: { available: boolean; sha256: string; bytes: number }
}
export interface RecycledProject {
  id: string
  name: string
  status_before_delete: string
  deleted_at: string
  deleted_by_name: string
  deletion_id: string
  version: number
  delete_backup_available: boolean
  /** Absent permission metadata never enables an exported project backup. */
  can_download_backup?: boolean
  can_restore: boolean
  can_permanently_delete?: boolean
  backup?: { available: boolean; sha256: string; bytes: number }
}
export interface PermanentProjectBackup {
  backup_id: string; project_id: string; project_name: string; sha256: string; bytes: number; encrypted: true; purged_at: string | null
}
export const projectRecycleApi = {
  permanentBackups: (): Promise<PermanentProjectBackup[]> => api.get('/project-recycle-bin/permanent-backups').then(r => r.data),
  preparePermanent: (id: string, data: { version: number; deletion_id: string }): Promise<PermanentProjectBackup> => api.post(`/project-recycle-bin/projects/${encodeURIComponent(id)}/permanent-backup`, data, { timeout: 600000 }).then(r => r.data),
  permanentlyDelete: (id: string, data: { version: number; deletion_id: string; backup_id: string; confirm_name: string }): Promise<PermanentProjectBackup & { message: string }> => api.delete(`/project-recycle-bin/projects/${encodeURIComponent(id)}/permanent`, { data, timeout: 600000 }).then(r => r.data),
  downloadPermanent: (backupId: string): Promise<Blob> => api.get(`/project-recycle-bin/backups/${encodeURIComponent(backupId)}`, { responseType: 'blob', timeout: 600000 }).then(r => r.data),
  list: (): Promise<RecycledProject[]> => api.get('/project-recycle-bin/projects').then(r => r.data),
  get: (id: string): Promise<RecycledProject> => api.get(`/project-recycle-bin/projects/${encodeURIComponent(id)}`).then(r => r.data),
  restore: (id: string, data: { version: number; deletion_id: string }): Promise<{ message: string; project_id: string; version: number }> =>
    api.post(`/project-recycle-bin/projects/${encodeURIComponent(id)}/restore`, data, { timeout: 600000 }).then(r => { return r.data }),
  downloadBackup: (id: string, deletionId: string): Promise<Blob> => api.get(`/project-recycle-bin/projects/${encodeURIComponent(id)}/backup`, { params: { deletion_id: deletionId }, responseType: 'blob', timeout: 600000 }).then(r => r.data),
}

// ===== 车型字典（HYPE-63）=====
export const vehicleTypeApi = {
  /** 普通用户可读的启用车型（业务页面选择项） */
  list: () => api.get('/vehicle-types').then((r) => r.data),
  /** 管理员读取全部（含已停用） */
  listAll: () => api.get('/vehicle-types/all').then((r) => r.data),
  create: (data: { name: string; sort_order?: number }) =>
    api.post('/vehicle-types', data).then((r) => r.data),
  update: (id: string, data: { name?: string; is_enabled?: boolean; sort_order?: number }) =>
    api.put(`/vehicle-types/${id}`, data).then((r) => r.data),
  reorder: (ids: string[]) =>
    api.put('/vehicle-types/reorder', { ids }).then((r) => r.data),
}

// ===== Types =====
export interface User {
  id: string
  username: string
  display_name: string
  role: 'admin' | 'pm' | 'worker' | 'director' | 'lead' | 'technician' | 'intern' | 'readonly'
  phone: string
  email: string
  is_active: boolean
  two_factor_enabled?: boolean
  two_factor_required?: boolean
  has_co_manager_projects?: boolean
  system_permissions?: string[]
  permission_overrides?: Record<string, boolean>
  permission_version?: number
}

export interface Project {
  vehicle_progress?: import('./workbench').VehicleSummary
  document_attention?: import('./projectDocuments').DocumentAttention
  next_signoff?: import('./workbench').WorkbenchAction | null
  can_delete?: boolean
  member_permissions?: Array<{ user_id: string; capabilities: string[] }>
  grantable_capabilities?: string[]
  member_details?: Array<{ id: string; display_name: string; role: string }>
  capabilities?: string[]
  id: string
  name: string
  abbreviation: string
  manager: string
  manager_name?: string
  technical_manager?: string
  technical_manager_name?: string
  co_managers?: Array<{ user_id: string; expires_at?: string; display_name?: string; role?: string; is_active?: boolean }>
  is_co_manager?: boolean
  client: string
  location: string
  timezone?: string
  planned_entry_date?: string | null // historical, read only for one version
  dispatch_platform?: 'NDC' | 'GRACE' | 'integrated' | null
  events?: ProjectEvent[]
  start_date: string
  end_date: string
  status: string
  legacy_lifecycle?: { original_status?: string | null; requires_repair?: boolean; repair_reason?: string }
  suspension?: Record<string, any>
  retrospective?: { content?: string; success?: string; problems?: string; improvements?: string; written_at?: string; author?: string; author_name?: string }
  description: string
  staffing_notes?: string
  source_template?: { id: string | null; name: string; version: number | null; available: boolean }
  vehicles?: Array<{ vehicle_type: string; quantity: number }>
  members: string[]
  version?: number
  rest_mode?: 'none' | 'one' | 'two'
  rest_days?: string[]
  skip_holidays?: boolean
  schedule_version?: number
  holiday_dates?: string[]
  adjusted_work_dates?: string[]
  missing_holiday_years?: number[]
  holiday_sources?: Array<{ year: number; source_kind: string; source_name: string; source_url: string; published_on: string; version: number }>
  vehicle_total?: number
  client_contacts?: Array<Record<string, any>>
  entry_plan?: Record<string, any>
  weekly_plan_summary?: import('./weeklyPlans').WeeklyPlanSummary
  created_at: string
}

export const ROLE_MAP: Record<string, string> = {
  admin: '系统管理员',
  pm: '项目经理',
  worker: '实施工程师',
  readonly: '只读',
}

// ===== AI 内部开放接口 =====
export const aiInternalApi = {
  tokens: () => api.get('/ai/internal/tokens').then((r) => r.data),
  createToken: (data: any) => api.post('/ai/internal/tokens', data).then((r) => r.data),
  updateToken: (id: string, data: any) => api.put(`/ai/internal/tokens/${id}`, data).then((r) => r.data),
  revokeToken: (id: string) => api.delete(`/ai/internal/tokens/${id}`).then((r) => r.data),
}

// ===== AI 开放接口 =====
export const aiApi = {
  capabilities: (projectId?: string) =>
    api.get('/ai-projects/capabilities', { params: projectId ? { project_id: projectId } : {} }).then((r) => r.data),

}

// ===== 系统问题反馈（HYPE-72）=====
// 提交：所有登录角色可用；列表/详情/状态更新：仅管理角色（后端再按角色拦截）。
export const feedbackApi = {
  create: (data: { description: string; steps?: string }) => api.post('/feedback', data).then((r) => r.data),
  list: (params?: { status?: string; page?: number; page_size?: number }) =>
    api.get('/feedback', { params }).then((r) => r.data),
  detail: (id: string) => api.get(`/feedback/${id}`).then((r) => r.data),
  updateStatus: (id: string, status: string) => api.patch(`/feedback/${id}/status`, { status }).then((r) => r.data),
}
