import { api } from './client'

export type ItemKind = 'work' | 'file' | 'purchase'
export interface TemplateCheck { id?: string; name: string; description?: string; required: boolean; safety: boolean }
export interface TemplateFile {
  id?: string; code: string; name: string; template_no: string; required: boolean; scope: 'project' | 'vehicle'
  platform: 'NDC' | 'GRACE' | 'integrated' | null; timing_type: string; timing_event: string | null; timing_offset_hours: number | null
  timing_weekday: number | null; trigger_type: string | null; confidential_default: boolean; external_visible_default: boolean
  external_never_visible: boolean; note: string; blank_file?: { id: string; filename: string; file_size: number } | null
}
export interface TemplateItem {
  id: string; section_id: string; kind: ItemKind; name: string; note: string; optional: boolean; per_vehicle: boolean; step_key: string | null
  checks: TemplateCheck[]; files: TemplateFile[]; quantity: number | null; unit: string; spec: string; fields: Record<string, string | number>
  reference_docs: { id: string; filename: string; note: string }[]; version: number; sort_order: number
}
export interface TemplateSection { id: string; title: string; stage_key: string; stage_name: string; sort_order: number; items: TemplateItem[] }
export interface TemplateFieldDef { id: string; name: string; field_type: 'text' | 'number' | 'date' | 'select'; options: string[] }
export interface TemplateTree { template_id: string; sections: TemplateSection[]; fields: TemplateFieldDef[]; stages: { key: string; name: string }[] }

export const KIND_NAMES: Record<ItemKind, string> = { work: '工作', file: '资料', purchase: '采购' }
export const STAGES = [
  { key: '4', name: '内部启动会' }, { key: '5', name: '发车前' }, { key: '6', name: '实施' },
  { key: '7', name: '验收' }, { key: '8', name: '交付' }, { key: '9', name: '全项目周期' },
]
/** What a section's stage means for the project: when its required files must be in. */
export const STAGE_GATES: Record<string, string> = {
  '4': '开始实施前交齐', '5': '发车进场前核对', '6': '项目完成前交齐', '7': '项目完成前交齐', '8': '归档前交齐', '9': '归档前交齐', legacy: '不参与核对',
}

/** The body the API accepts for a row: the row minus the read-only parts. */
export const itemBody = (item: Omit<TemplateItem, 'id' | 'reference_docs' | 'sort_order' | 'step_key' | 'version'> & { version?: number }) => ({
  section_id: item.section_id, kind: item.kind, name: item.name, note: item.note, optional: item.optional,
  per_vehicle: item.kind === 'work' && item.per_vehicle,
  checks: item.kind === 'work' ? item.checks.map(({ id, name, description, required, safety }) => ({ id, name, description: description ?? '', required, safety })) : [],
  files: item.files.map(({ blank_file: _blank, ...file }) => file),
  quantity: item.kind === 'purchase' ? item.quantity : null, unit: item.kind === 'purchase' ? item.unit : '', spec: item.kind === 'purchase' ? item.spec : '',
  fields: item.fields, version: item.version,
})

export const newFile = (name = ''): TemplateFile => ({
  code: '', name, template_no: '', required: true, scope: 'project', platform: null, timing_type: 'on_demand', timing_event: null,
  timing_offset_hours: null, timing_weekday: null, trigger_type: null, confidential_default: false, external_visible_default: false,
  external_never_visible: false, note: '',
})

const base = (tid: string) => `/templates/${encodeURIComponent(tid)}`
export const templateItemsApi = {
  read: async (tid: string) => (await api.get<TemplateTree>(`${base(tid)}/items`)).data,
  addSection: async (tid: string, body: { title: string; stage_key: string; after_id?: string }) => (await api.post<TemplateTree & { id: string }>(`${base(tid)}/sections`, body)).data,
  updateSection: async (tid: string, id: string, body: { title?: string; stage_key?: string }) => (await api.put<TemplateTree>(`${base(tid)}/sections/${id}`, body)).data,
  removeSection: async (tid: string, id: string) => (await api.delete<TemplateTree>(`${base(tid)}/sections/${id}`)).data,
  layout: async (tid: string, sections: { id: string; item_ids: string[] }[]) => (await api.put<TemplateTree>(`${base(tid)}/layout`, { sections })).data,
  addItem: async (tid: string, body: ReturnType<typeof itemBody>) => (await api.post<TemplateTree & { id: string }>(`${base(tid)}/items`, body)).data,
  updateItem: async (tid: string, id: string, body: ReturnType<typeof itemBody>) => (await api.put<TemplateTree>(`${base(tid)}/items/${id}`, body)).data,
  removeItem: async (tid: string, id: string) => (await api.delete<TemplateTree>(`${base(tid)}/items/${id}`)).data,
  copy: async (tid: string, body: { source_template_id: string; item_ids: string[]; section_id?: string }) => (await api.post<TemplateTree & { copied: string[] }>(`${base(tid)}/items/copy`, body)).data,
  fields: async (tid: string, fields: (Omit<TemplateFieldDef, 'id'> & { id?: string })[]) => (await api.put<TemplateTree>(`${base(tid)}/fields`, { fields })).data,
  uploadBlank: async (tid: string, itemId: string, fileId: string, file: File) => {
    const data = new FormData(); data.append('file', file)
    return (await api.post<TemplateTree>(`${base(tid)}/items/${itemId}/files/${fileId}/blank`, data)).data
  },
  removeBlank: async (tid: string, itemId: string, fileId: string) => (await api.delete<TemplateTree>(`${base(tid)}/items/${itemId}/files/${fileId}/blank`)).data,
  downloadBlank: async (tid: string, itemId: string, fileId: string) => (await api.get<Blob>(`${base(tid)}/items/${itemId}/files/${fileId}/blank`, { responseType: 'blob' })).data,
  exportExcel: async (tid: string) => (await api.get<Blob>(`${base(tid)}/excel`, { responseType: 'blob' })).data,
  importExcel: async (tid: string, file: File) => {
    const data = new FormData(); data.append('file', file)
    return (await api.post<TemplateTree & { imported: { sections: number; items: number; fields: number } }>(`${base(tid)}/excel`, data)).data
  },
}
