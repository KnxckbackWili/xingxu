/** Dedicated network seam: no internal auth interceptor, cookies, cache or storage. */
export interface ExternalDocument {
  id: string; code: string; name: string; vehicle_label: string; period_key: string | null; status: string
  file: { version_id: string; filename: string; size: number; uploaded_at: string | null } | null
}
export interface ExternalView {
  share_id: string; project_name: string; scopes: string[]; expires_at: string
  project_progress?: { status: string; start_date: string; end_date: string; percent: number | null; completed: number; target: number; quantity_unknown: boolean }
  vehicle_progress?: { steps: { key: string; name: string }[]; units: { asset_code: string; fleet_no: string; vehicle_type: string; model_name: string; cells: Record<string, { is_done: boolean; done_on: string | null }> }[]; warnings: string[] }
  documents?: ExternalDocument[]
}
const options: RequestInit = { credentials: 'omit', cache: 'no-store', referrerPolicy: 'no-referrer', redirect: 'error' }
async function checked(url: string, init: RequestInit) {
  const response = await fetch(url, { ...options, ...init })
  if (!response.ok) throw new Error(response.status === 401 ? '分享已到期、被撤销或会话已失效，请重新打开原始链接；仍无法访问时联系项目负责人。' : response.status === 404 ? '此资料未对当前分享开放。' : '暂时无法读取分享，请稍后重试。')
  return response
}
export const externalViewApi = {
  bootstrap: async (token: string, signal?: AbortSignal): Promise<{ session_token: string; session_expires_at: string; view: ExternalView }> =>
    (await checked('/api/external/bootstrap', { method: 'POST', signal, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token }) })).json(),
  view: async (session: string, signal?: AbortSignal): Promise<ExternalView> =>
    (await checked('/api/external/view', { signal, headers: { Authorization: `Bearer ${session}` } })).json(),
  download: async (session: string, row: ExternalDocument): Promise<Blob> => {
    if (!row.file) throw new Error('此资料尚无可下载文件。')
    return (await checked(`/api/external/documents/${encodeURIComponent(row.id)}/versions/${encodeURIComponent(row.file.version_id)}/download`, { headers: { Authorization: `Bearer ${session}` } })).blob()
  },
}
