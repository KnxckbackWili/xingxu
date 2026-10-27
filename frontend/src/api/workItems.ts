import { api } from './client'
export type WorkCheck = { id: string; name: string; description?: string; is_required: boolean; is_safety_critical: boolean; is_applicable: boolean; is_done: boolean; failed: boolean; failed_reason?: string; not_applicable_reason?: string; vehicle_unit_id?: string; vehicle_label?: string; version: number }
export type WorkItem = { id: string; phase_id: string; phase_name: string; name: string; description: string; group_label: string; kind: 'vehicle' | 'other'; vehicle_step_key?: string | null; applicable_vehicle_types: string[]; scope_conditions: string[]; is_completed: boolean; quality_blocked?: boolean; version: number; sort_order: number; has_legacy_quantity: boolean; reference_docs: { filename: string; note?: string }[]; check_items: WorkCheck[]; check_definitions?: { name: string; description?: string; is_required: boolean; is_safety_critical: boolean }[]; completion: { reason: string; by_name: string; at: string | null }; matrix?: { linked: boolean; name?: string; completed_count?: number; expected_count?: number | null; unidentified_completed?: number; percent: number | null; warning?: string } }
export type WorkPhase = { id: string; name: string; color: string; work_items: WorkItem[] }
export type WorkCatalog = { legacy_work_items?: WorkItem[]; phases: WorkPhase[]; permissions: { plan: boolean; record: boolean; override: boolean }; project_status: string }
export const workItemsApi = {
  list: async (pid: string) => (await api.get<WorkCatalog>(`/projects/${pid}/work-items`)).data,
  template: async (tid: string) => (await api.get<{ phases: WorkPhase[] }>(`/templates/${tid}/work-items`)).data,
}
