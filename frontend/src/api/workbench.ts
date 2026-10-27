import { api } from './client'
import type { DocumentAction, DocumentAttention } from './projectDocuments'
export type VehicleSummary = { target: number; completed: number; identified_completed?: number; unidentified_completed?: number; quantity_unknown: boolean; fleet_quantity_unknown?: boolean; unregistered_quantity?: number; percent: number | null; progress_known?: boolean }
export type WorkbenchAction = DocumentAction & { project_id: string; project_name: string; timezone?: string }
export type WorkbenchProject = { id: string; name: string; status: string; percent?: number; vehicle_progress?: VehicleSummary; document_attention?: DocumentAttention; next_signoff?: WorkbenchAction | null }
export type WorkbenchOverview = { projects: WorkbenchProject[]; this_week_documents?: WorkbenchAction[]; weekly_plan?: WeeklyPlanAttention }
export type WeeklyPlanAttentionItem = { id: string; project_id: string; project_name: string; task_id: string; name: string; week_start: string; state: string; url: string }
// 后端只在读取成功时返回 state='available'；count 为已发布但逾期未完成的周计划格数。
export type WeeklyPlanAttention = { state: string; count: number | null; items: WeeklyPlanAttentionItem[] | null; unknown_count?: number; unknown_items?: WeeklyPlanAttentionItem[]; reason?: string }
export type WorkspaceStatisticsData = { projects: number; active_projects: number; completed_projects: number; status_distribution: { status: string; count: number }[]; vehicle_progress: VehicleSummary; documents: { this_week_count: number; overdue_count: number }; issues: { open: number; critical: number } }
export const workbenchApi = {
  overview: async (): Promise<WorkbenchOverview> => (await api.get('/dashboard/overview')).data,
  statistics: async (): Promise<WorkspaceStatisticsData> => (await api.get('/dashboard/statistics')).data,
}
export const documentActionUrl = (row: { project_id: string; id: string }) => `/pm/projects/${encodeURIComponent(row.project_id)}/documents?document=${encodeURIComponent(row.id)}`
