export interface User { id: string; username: string; display_name: string; role: 'admin' | 'employee'; is_active: boolean; created_at?: string }

export interface Base { id: string; created_at: string; created_by: string | null; updated_at: string; sort_order?: number }
export interface Step extends Base { name: string }
export interface Vehicle extends Base { vehicle_no: string; fleet_no: string; model: string; config_no: string; note: string }
export interface VehicleRecord extends Base { vehicle_id: string; happened_on: string | null; category: string; content: string; recorded_by_name: string; recorded_on: string | null }
export interface WorkItem extends Base { stage: string; name: string; note: string; done: boolean; done_by: string | null; done_at: string | null }
export interface Issue extends Base { description: string; vehicle_id: string | null; resolution: string; is_closed: boolean; closed_by: string | null; closed_at: string | null }
export interface DocumentRow extends Base { name: string; note: string }
export interface Item extends Base { name: string; spec: string; quantity: number | null; unit: string; arrived: boolean; arrived_by: string | null; arrived_at: string | null; note: string }
export interface Mark { vehicle_id: string; step_id: string; done_by: string | null; done_at: string }
export interface FileRow { id: string; owner_kind: 'document' | 'issue' | 'other'; owner_id: string | null; filename: string; size: number; mime: string; created_by: string | null; created_at: string }
export interface Project { id: string; name: string; contract_no: string; customer: string; note: string; is_closed: boolean; rev: number; created_at: string; updated_at: string; deleted_at: string | null; deleted_by_name?: string }

export interface Snapshot {
  project: Project
  steps: Step[]; vehicles: Vehicle[]; vehicle_records: VehicleRecord[]; work: WorkItem[]; issues: Issue[]
  documents: DocumentRow[]; items: Item[]; marks: Mark[]; files: FileRow[]
  people: Record<string, string>; vehicle_types: string[]
}
export type ListKey = 'steps' | 'vehicles' | 'vehicle_records' | 'work' | 'issues' | 'documents' | 'items'

export interface Gaps {
  vehicles: { total: number; missing: { id: string; name: string; fleet_no: string; missing: string[] }[] }
  work: { id: string; stage: string; name: string }[]
  issues: { id: string; name: string }[]
  documents: { id: string; name: string }[]
  items: { id: string; name: string }[]
}
export interface OverviewProject extends Project { gaps: Gaps | null }

export interface Template { id: string; name: string; note: string; rev: number; updated_at: string; counts?: Record<TemplateKind, number> }
export type TemplateKind = 'work' | 'document' | 'step' | 'item'
export interface TemplateRow extends Base { kind: TemplateKind; stage: string; name: string; spec: string; quantity: number | null; unit: string }
export interface TemplateSnapshot { template: Template; rows: TemplateRow[]; people: Record<string, string> }
export interface VehicleType { id: string; name: string; note: string; is_enabled: boolean; sort_order: number }

export interface HistoryItem {
  seq: number; created_at: string; user_id: string | null; user_name: string; project_id: string | null; project_name: string
  kind: string; kind_label: string; action: string; action_label: string; row_id: string; row_label: string; detail: string
  field_label: string; old_text: string; new_text: string; scope_id: string | null; can_restore: boolean
}
export interface ImportResult { counts: { label: string; count: number }[]; problems: string[]; problem_count: number; unknown_models: string[]; preview: boolean }
export interface Conflict { current: unknown; by: string }
