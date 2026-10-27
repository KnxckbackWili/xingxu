import { api } from './client'

export type PlanScope = { vehicle_type?: string; vehicle_unit_ids: string[]; label?: string }
export type PlanWarning = string | { code?: string; message?: string; [key: string]: unknown }
export const planWarningText = (warning: PlanWarning) => typeof warning === 'string' ? warning : warning.message || '有计划信息需要核对'
export type PlanInput = { task_id: string; scope: PlanScope; week_start: string; mode: 'finish' | 'in_progress'; target_count: number | null; assignee_ids: string[]; notes: string }
export type PlanCell = PlanInput & {
  id: string; project_id: string; scope_key?: string; task_name: string; kind: 'vehicle' | 'other'; phase_id: string; phase_name: string; group_label: string;
  week_end: string; intent_review_required: boolean; published: boolean; is_cancelled: boolean; version: number; source_metadata?: Record<string, unknown> | null;
  assignees: { id: string; name: string; active: boolean }[]; permissions: { edit: boolean; claim: boolean };
  completion: { state: 'unknown' | 'completed' | 'overdue' | 'in_progress' | 'planned'; is_complete: boolean; overdue: boolean; completed_count: number | null; required_count: number | null; expected_count: number | null; quantity_unknown: boolean; target_review_required: boolean; warnings: string[]; unidentified_completed?: number; completion_date_unknown?: boolean }
}
export type PlanWork = { id: string; name: string; kind: 'vehicle' | 'other'; group_label: string; vehicle_step_key: string | null; applicable_vehicle_types: string[]; version: number }
export type PlanPhase = { id: string; name: string; work_items: PlanWork[] }
export type PlanWeek = { week_start: string; week_end: string; holiday_days: string[]; makeup_workdays: string[]; missing_holiday_years: number[] }
export type WeeklyPlanSummary = { state: 'available'; total: number; published_count: number; draft_count: number | null; overdue_count: number; unknown_count: number; warning_count: number; unassigned_count?: number; warnings?: PlanWarning[] }
export type PlanSettings = { rest_mode: 'none' | 'one' | 'two'; rest_days: string[]; skip_holidays: boolean }
export type SettingsResponse = { settings: PlanSettings; version: number; warnings?: PlanWarning[] }
export type WeeklyPlanView = {
  cells: PlanCell[]; work_items: PlanPhase[]; weeks: PlanWeek[]; warnings: PlanWarning[]; timezone: string;
  members: { id: string; name: string; active: boolean }[]; vehicles: { id: string; label: string; vehicle_id?: string }[]; vehicle_types: string[];
  settings: PlanSettings; permissions: { read: boolean; edit: boolean; publish: boolean; export: boolean; claim: boolean };
  summary: { state: 'available'; published_count: number; draft_count: number | null; overdue_count: number; in_progress_count: number }
}
export type DraftRule = { phase_id: string; anchor: 'before_ship' | 'after_arrival'; offset_weeks: number; mode: 'finish' | 'in_progress' }
export type DraftRules = {
  rules: DraftRule[]; warnings: PlanWarning[];
  suggestions: (DraftRule & { phase_name: string; source_phase_id: string | null; source_label: string; window_start: string | null; window_end: string | null; week_start: string | null; reason: string })[]
}
export type DraftRequest = { phase_rules: DraftRule[]; first_week?: string }
export type DraftPreview = { proposals: (PlanInput & { task_name: string; phase_name: string; kind: 'vehicle' | 'other' })[]; warnings: PlanWarning[]; preview_token: string }
const base = (pid: string) => `/projects/${encodeURIComponent(pid)}/weekly-plans`
export const weeklyPlansApi = {
  list: async (pid: string, week_start: string, weeks: number, include_cancelled = false) => (await api.get<WeeklyPlanView>(base(pid), { params: { week_start, weeks, include_cancelled } })).data,
  create: async (pid: string, input: PlanInput) => (await api.post<PlanCell>(base(pid), input)).data,
  update: async (pid: string, id: string, input: Partial<Omit<PlanInput, 'task_id'>> & { version: number; is_cancelled?: boolean; confirm_intent?: boolean; reason?: string }) => (await api.put<PlanCell>(`${base(pid)}/${encodeURIComponent(id)}`, input)).data,
  publish: async (pid: string, cells: { id: string; version: number }[]) => (await api.post(`${base(pid)}/publish`, { cells })).data,
  defaultRules: async (pid: string) => (await api.get<DraftRules>(`${base(pid)}/draft-rules`)).data,
  preview: async (pid: string, input: DraftRequest) => (await api.post<DraftPreview>(`${base(pid)}/draft/preview`, input)).data,
  draft: async (pid: string, input: DraftRequest & { preview_token: string }) => (await api.post(`${base(pid)}/draft`, input)).data,
  settings: async (pid: string) => (await api.get<SettingsResponse>(`${base(pid)}/settings`)).data,
  saveSettings: async (pid: string, input: PlanSettings & { version: number }) => (await api.put<SettingsResponse>(`${base(pid)}/settings`, input)).data,
  excel: (pid: string, params: { week_start: string; weeks: number; phase_id?: string }) => api.get<Blob>(`${base(pid)}/export/excel`, { params, responseType: 'blob', timeout: 600000 }),
}
