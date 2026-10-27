import type { WorkItem, WorkCatalog } from '../api/workItems'
export function work(overrides: Partial<WorkItem> = {}): WorkItem {
  return { id: 'w1', phase_id: 'ph1', phase_name: '实施阶段', name: '现场验证', description: '原施工说明', group_label: '原模块标签', kind: 'other', applicable_vehicle_types: [], scope_conditions: [], is_completed: false, version: 7, sort_order: 1, has_legacy_quantity: true, reference_docs: [], check_items: [], completion: { reason: '', by_name: '', at: null }, ...overrides }
}
export function catalog(items = [work()]): WorkCatalog {
  return { phases: [{ id: 'ph1', name: '实施阶段', color: '#1677ff', work_items: items }], permissions: { plan: true, record: true, override: true }, project_status: 'executing' }
}
