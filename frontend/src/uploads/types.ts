import type { ProjectDocument, ProjectFile } from '../api/projectDocuments'

export type UploadIntent = {
  client_uuid: string
  filename: string
  size: number
  sha256: string
  content_type: string
  document_ids: string[]
  note: string
  entity_type: 'project' | 'task' | 'issue'
  entity_id: string
  category: string
  confidential?: boolean
  confidential_user_ids?: string[]
  milestone_dates?: Record<string, string>
}
export type UploadResult = { file: ProjectFile; documents: ProjectDocument[] }
export type UploadSession = {
  id: string; project_id: string; client_uuid: string; filename: string
  size: number; sha256: string; state: 'open' | 'finished' | 'cancelled' | 'expired'
  chunk_size: number; total_chunks: number
  received: Array<{ index: number; size: number; sha256: string }>
  expires_at: string; result?: UploadResult
}
export type UploadLimits = { max_upload_size: number; chunk_size: number; session_ttl_days: number; buffered_upload_limit: number }
export type UploadOptions = {
  documentIds?: string[]; note?: string
  entityType?: 'project' | 'task' | 'issue'; entityId?: string; category?: string
  confidential?: boolean; confidentialUserIds?: string[]
  milestoneDates?: Record<string, string>
}
export type UploadPhase = 'queued' | 'hashing' | 'uploading' | 'finishing' | 'paused' | 'needs_file' | 'error' | 'completed' | 'cancelled'
export type UploadJob = {
  key: string; owner_id: string; project_id: string; created_at: number; updated_at: number
  intent: UploadIntent; file: Blob | null; durable_file: boolean; metadata_durable: boolean; last_modified: number
  session_id: string | null; chunk_hashes: string[]
  phase: UploadPhase; pause_reason?: 'user' | 'offline' | 'account' | 'permission'
  hashed_bytes: number; uploaded_bytes: number; error: string
  result?: UploadResult
  cancel_requested?: boolean
  lease_id?: string; lease_until?: number
}

export class UploadQueuedError extends Error {
  constructor(public readonly uploadId: string, message = '文件已保存到上传队列，联网后会继续；资料将在服务器核验完成后更新。') {
    super(message)
    this.name = 'UploadQueuedError'
  }
}
export const isUploadQueued = (error: unknown): error is UploadQueuedError => error instanceof UploadQueuedError
export const uploadJobKey = (owner: string, id: string) => `${owner}:${id}`
export const DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024
export const DEFAULT_UPLOAD_LIMIT = 2048 * 1024 * 1024
