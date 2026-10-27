import { api } from './client'
import axios from 'axios'
import { uploadQueue } from '../uploads/queue'
import { parseDispositionFilename } from '../utils/download'

export type DocumentTiming = 'before_event' | 'after_event' | 'weekly' | 'on_trigger' | 'after_milestone' | 'on_demand' | 'lifetime'
export type GeneratedFormKind = 'lifecycle' | 'contact' | 'inventory'
export type GeneratedFormOptions = { note?: string; confidential?: boolean; confidentialUserIds?: string[]; applicationId?: string }
export type GeneratedContactSource = { id: string; title: string; item_name: string; apply_date: string | null; status: string }
const generatedBody = (options: GeneratedFormOptions) => ({ note: options.note ?? '', confidential: options.confidential ?? false, confidential_user_ids: options.confidentialUserIds ?? [] })
export interface ProjectDocumentRule {
  id: string
  requirement_id: string | null
  stage_key: '4' | '5' | '6' | '7' | '8' | '9' | 'legacy'
  code: string
  name: string
  template_no: string
  required: boolean
  scope: 'project' | 'vehicle'
  platform: 'NDC' | 'GRACE' | 'integrated' | null
  timing_type: DocumentTiming
  timing_event: string | null
  timing_offset_hours: number | null
  timing_weekday: number | null
  trigger_type: string | null
  blank_file_id: string | null
  sort_order: number
  note: string
  source_metadata: Record<string, unknown> | null
}
export interface ProjectDocumentVersion {
  id: string
  attachment_id: string
  filename: string
  file_size: number
  sha256: string | null
  uploaded_by: string | null
  uploaded_by_name: string
  uploaded_at: string | null
  note: string
  review_metadata: Record<string, unknown> | null
  download_url: string
  storage_state?: 'available' | 'removed_by_policy'
  removal?: { receipt_id: string; removed_at: string; removed_by_name: string; reason: string } | null
  file?: ProjectFile
}
export interface DocumentDueBasis {
  kind: string; rule: string; timezone: string; precision?: string
  actual_date?: string; planned_date?: string; period_key?: string
}
export interface DocumentAction {
  id: string; document_id: string; code: string; name: string; due_at: string | null
  due_is_estimated: boolean; due_state: string; period_key: string | null; vehicle_label: string
  effective_owner_id?: string | null; effective_owner_name?: string; owner_warning?: string
  project_id?: string; project_name?: string; timezone?: string; overdue_days: number
}
export interface DocumentAttention {
  this_week: DocumentAction[]; this_week_count: number; overdue: DocumentAction[]; overdue_count: number
  estimated_past_due_count: number; on_demand: DocumentAction[]; owner_warnings: DocumentAction[]
  period_key: string; timezone: string; as_of: string
}
export interface ProjectDocument extends ProjectDocumentRule {
  trigger_event?: DocumentTriggerEvent | null
  definition_id: string | null
  vehicle_unit_id: string | null
  vehicle_label: string
  period_key: string | null
  trigger_ref: string | null
  due_at: string | null
  due_is_estimated: boolean
  due_basis?: DocumentDueBasis | null
  due_state?: string
  owner_id?: string | null
  owner_name?: string
  effective_owner_id?: string | null
  effective_owner_name?: string
  owner_warning?: string
  status: 'pending' | 'submitted' | 'waived'
  waived_reason: string
  confidential: boolean
  confidential_user_ids?: string[]
  external_visible: boolean
  external_never_visible: boolean
  submitted_at: string | null
  submitted_by: string | null
  version: number
  versions: ProjectDocumentVersion[]
  latest_version: ProjectDocumentVersion | null
  applicable: boolean
}
export interface DocumentTriggerEvent {
  id:string; trigger_type:string; source_type:string; source_id:string; occurred_at:string; recorded_at:string
  source_metadata:{basis?:string;title?:string;member_name?:string;note?:string;warning?:string}
}
export interface ProjectDocumentDefinition extends ProjectDocumentRule {
  source_key: string
  owner_id?: string | null
  effective_owner_name?: string
  owner_warning?: string
  confidential_default: boolean
  external_visible_default: boolean
  external_never_visible: boolean
  waiting_reason: string | null
  instance_count: number
  confidential_user_ids?: string[]
  access_version?: number
}
export interface ProjectFile {
  id: string
  filename: string
  file_size: number
  content_type: string
  sha256: string | null
  uploaded_by: string | null
  uploaded_by_name: string
  uploaded_at: string | null
  confidential: boolean
  confidential_explicit?: boolean
  confidential_user_ids?: string[]
  access_version?: number
  entity_type: string
  entity_id: string
  category: string
  download_url: string
  storage_state?: 'available' | 'removed_by_policy'
  removal?: { receipt_id: string; removed_at: string; removed_by_name: string; reason: string } | null
}
export interface ProjectDocumentsResponse {
  storage_warnings?: string[]
  trigger_events?:DocumentTriggerEvent[]
  documents: ProjectDocument[]
  definitions: ProjectDocumentDefinition[]
  unclassified_files: ProjectFile[]
  document_actions?: DocumentAttention
  owner_options?: { id: string; name: string }[]
  permissions: { manage: boolean; submit: boolean; manage_confidentiality?: boolean }
  timezone: string
  version: number
}
export type ProjectRequirementBody = Pick<ProjectDocumentRule,
  'stage_key' | 'code' | 'name' | 'template_no' | 'required' | 'scope' | 'platform' |
  'timing_type' | 'timing_event' | 'timing_offset_hours' | 'timing_weekday' |
  'trigger_type' | 'sort_order' | 'note'> & {
  owner_id?: string | null
  confidential_default: boolean; external_visible_default: boolean; external_never_visible: boolean
}
export interface DocumentUploadOptions {
  file: File
  documentIds?: string[]
  milestoneDates?: Record<string, string>
  note?: string
  entityType?: 'project' | 'task' | 'issue'
  entityId?: string
  category?: string
  confidential?: boolean
  confidentialUserIds?: string[]
}
const segment = encodeURIComponent
const base = (projectId: string) => `/projects/${segment(projectId)}/documents`
export const projectDocumentsApi = {
  confidentialityMembers: async (projectId: string): Promise<{ id: string; display_name: string; role: string }[]> =>
    (await api.get(`${base(projectId)}/confidentiality-members`)).data,
  setConfidentiality: async (projectId: string, kind: 'document' | 'definition' | 'file', id: string,
    body: { confidential: boolean; confidential_user_ids: string[]; version: number }): Promise<unknown> =>
    (await api.put(`${base(projectId)}/${kind === 'file' ? 'files/' : kind === 'definition' ? 'requirements/' : ''}${segment(id)}/confidentiality`, body)).data,
  list: async (projectId: string, filter?: { vehicle_unit_id: string }, expectedAccount?: string): Promise<ProjectDocumentsResponse> =>
    (await api.get(base(projectId), { params: filter, headers: expectedAccount ? { 'X-AGV-Expected-Account': expectedAccount } : {} })).data,
  assignOwner: async (projectId: string, id: string, ownerId: string | null, version?: number): Promise<ProjectDocument> =>
    (await api.put(`${base(projectId)}/${segment(id)}/owner`, { owner_id: ownerId, version })).data,
  files: async (projectId: string, params?: { entity_type?: string; entity_id?: string }): Promise<ProjectFile[]> =>
    (await api.get(`${base(projectId)}/files`, { params })).data,
  createRequirement: async (projectId: string, body: ProjectRequirementBody): Promise<ProjectDocumentDefinition> =>
    (await api.post(`${base(projectId)}/requirements`, body)).data,
  updateRequirement: async (projectId: string, id: string, body: ProjectRequirementBody): Promise<ProjectDocumentDefinition> =>
    (await api.put(`${base(projectId)}/requirements/${segment(id)}`, body)).data,
  upload: async (projectId: string, options: DocumentUploadOptions): Promise<{ file: ProjectFile; documents: ProjectDocument[] }> => {
    const { file, ...intent } = options
    return uploadQueue.upload(projectId, file, intent)
  },
  submit: async (projectId: string, documentIds: string[], attachmentId: string, note = '', milestoneDates: Record<string, string> = {}): Promise<{ documents: ProjectDocument[] }> =>
    (await api.post(`${base(projectId)}/submit`, { document_ids: documentIds, attachment_id: attachmentId, note, ...(Object.keys(milestoneDates).length ? { milestone_dates: milestoneDates } : {}) })).data,
  setStatus: async (projectId: string, row: ProjectDocument, status: 'pending' | 'waived', reason: string): Promise<ProjectDocument> =>
    (await api.put(`${base(projectId)}/${segment(row.id)}`, { status, reason, version: row.version })).data,
  review: async (projectId: string, documentId: string, versionId: string, decision: 'approved' | 'rejected', note = ''): Promise<ProjectDocumentVersion> =>
    (await api.post(`${base(projectId)}/${segment(documentId)}/versions/${segment(versionId)}/review`, { decision, note })).data,
  generateInventory: async (projectId: string, documentId: string, note = '', options: GeneratedFormOptions = {}): Promise<ProjectDocument> =>
    (await api.post(`${base(projectId)}/${segment(documentId)}/generate-inventory`, { ...generatedBody(options), note })).data,
  generateLifecycle: async (projectId: string, documentId: string, options: GeneratedFormOptions = {}): Promise<ProjectDocument> =>
    (await api.post(`${base(projectId)}/${segment(documentId)}/generate-lifecycle`, generatedBody(options))).data,
  generateContact: async (projectId: string, documentId: string, applicationId: string, options: GeneratedFormOptions = {}): Promise<ProjectDocument> =>
    (await api.post(`${base(projectId)}/${segment(documentId)}/generate-contact`, { ...generatedBody(options), application_id: applicationId })).data,
  generationSources: async (projectId: string, documentId: string, options: GeneratedFormOptions = {}): Promise<GeneratedContactSource[]> => {
    const params = new URLSearchParams({ confidential: String(options.confidential ?? false) })
    for (const id of options.confidentialUserIds ?? []) params.append('confidential_user_ids', id)
    return (await api.get(`${base(projectId)}/${segment(documentId)}/generation-sources?${params}`)).data
  },
  deleteFile: async (id: string) => (await api.delete(`/files/${segment(id)}`)).data,
}

export async function uploadProjectFile(projectId: string, file: File, entityType: 'project' | 'task' | 'issue' = 'project', entityId = '', category = ''): Promise<ProjectFile> {
  return (await projectDocumentsApi.upload(projectId, { file, entityType, entityId, category })).file
}

/** API response paths stay same-origin; do not send credentials to a file URL supplied by imported content. */
export async function downloadDocumentResource(path: string, filename: string) {
  const endpoint = path.startsWith('/api/') ? path.slice(4) : path
  if (!endpoint.startsWith('/files/') && !endpoint.startsWith('/projects/')) throw new Error('文件下载地址无效')
  const response = await api.get(endpoint, { responseType: 'blob', timeout: 600000 })
  const url = URL.createObjectURL(response.data)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = parseDispositionFilename(response.headers?.['content-disposition']) || filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}
export async function downloadProjectFile(id: string, filename: string) {
  return downloadDocumentResource(`/files/${segment(id)}/download`, filename)
}


export async function downloadSelectedDocuments(projectId: string, documentIds: string[]) {
  try {
    const response = await api.post(`${base(projectId)}/package`, { document_ids: documentIds }, { responseType: 'blob', timeout: 600000 })
    const url = URL.createObjectURL(response.data)
    const anchor = document.createElement('a')
    anchor.href = url; anchor.download = parseDispositionFilename(response.headers?.['content-disposition']) || '所选资料.zip'
    document.body.appendChild(anchor); anchor.click(); anchor.remove(); URL.revokeObjectURL(url)
  } catch (failure) {
    if (axios.isAxiosError(failure) && failure.response?.data instanceof Blob) {
      try { failure.response.data = JSON.parse(await failure.response.data.text()) } catch { /* Keep the original transport error. */ }
    }
    throw failure
  }
}
