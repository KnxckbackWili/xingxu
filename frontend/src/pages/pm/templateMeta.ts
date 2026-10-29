export type TemplateRow = {
  id: string; name: string; description?: string; version?: number; status?: string; usage_count?: number; is_system: boolean
  summary?: { work: Record<string, number>; documents: Record<string, number>; vehicle_steps: number }
}

export const templateStatus = (t?: TemplateRow) => t?.is_system ? '系统模板' : t?.status === 'published' ? '已发布' : '草稿'
