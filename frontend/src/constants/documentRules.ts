export const DOCUMENT_STAGES = [
  { value: '4', label: '4 · 内部启动会' }, { value: '5', label: '5 · 发车前' },
  { value: '6', label: '6 · 实施' }, { value: '7', label: '7 · 验收' },
  { value: '8', label: '8 · 交付' }, { value: '9', label: '9 · 全项目周期更新' },
]
export const DOCUMENT_TIMINGS: Record<string, string> = {
  before_event: '事件发生前', after_event: '事件发生后', weekly: '每周',
  on_trigger: '事件触发', after_milestone: '里程碑完成后', on_demand: '按需抽查', lifetime: '全项目周期更新',
}
export const DOCUMENT_EVENTS: Record<string, string> = {
  internal_kickoff: '内部启动会', ship: '发车', arrival_all: '全部到场', vehicle_arrival: '该车到场',
  delivery_signed: '到货签收', commissioning_done: '调试完工', go_live: '上线运行',
  training_done: '培训完成', acceptance: '项目验收', handover: '交付售后',
}
export const DOCUMENT_MILESTONES = ['delivery_signed', 'commissioning_done', 'go_live', 'training_done', 'acceptance', 'handover']
export const DOCUMENT_TRIGGERS: Record<string, string> = { accident: '事故', quality: '质量问题', member_leave: '人员离开项目' }
export const DOCUMENT_WEEKDAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
export const DOCUMENT_RULE_EMPTY = { timing_type: null, timing_event: null, timing_offset_hours: null, timing_weekday: null, trigger_type: null }
export function documentRuleLabel(rule: { timing_type: string; timing_event: string | null; timing_weekday: number | null; timing_offset_hours: number | null; trigger_type: string | null }) {
  if (rule.timing_type === 'weekly') return `每周${DOCUMENT_WEEKDAYS[(rule.timing_weekday ?? 1) - 1]?.slice(1) ?? ''}`
  if (rule.timing_type === 'on_demand') return '按需抽查'
  if (rule.timing_type === 'lifetime') return '内部启动会建档，归档前提交'
  if (rule.timing_type === 'on_trigger') return `${DOCUMENT_TRIGGERS[rule.trigger_type ?? ''] ?? '相关事件'}后 ${rule.timing_offset_hours ?? 0} 小时`
  return `${DOCUMENT_EVENTS[rule.timing_event ?? ''] ?? '相关事件'}${rule.timing_type === 'before_event' ? '前' : '后'} ${rule.timing_offset_hours ?? 0} 小时`
}
