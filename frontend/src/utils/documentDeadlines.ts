import type { ProjectDocument } from '../api/projectDocuments'
import { formatDateTime, parseDateTime } from './date'
export function deadlineLabel(value: string | null, timezone: string) {
  if (!value) return '无截止时间'
  const parsed = parseDateTime(value)
  if (!parsed.isValid()) return '截止时间待核对'
  try {
    const parts = new Intl.DateTimeFormat('zh-CN', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(parsed.toDate())
    const part = (type: string) => parts.find(item => item.type === type)?.value ?? ''
    return `${part('year')}-${part('month')}-${part('day')} ${part('hour')}:${part('minute')}`
  } catch { return formatDateTime(value) }
}
export function basisLabel(row: ProjectDocument) {
  const basis = row.due_basis
  if (basis?.kind === 'actual_date_anchor') return `按实际到场日 ${basis.actual_date} 的日历锚点计算；原事件仅有日期，未记录实际时刻。`
  if (basis?.kind === 'planned_date_anchor') return `按计划日期 ${basis.planned_date} 预计，实际发生后重新核对。`
  if (row.timing_type === 'on_demand') return '按需抽查，无固定截止时间。'
  if (row.timing_type === 'lifetime') return '内部启动会实际登记后建档，归档前提交。'
  if (!row.due_at) return '等待真实事件或计划日期后计算截止。'
  return ''
}
