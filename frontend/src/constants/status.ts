/** 项目状态唯一事实源（全系统共用，勿在页面内重复定义）。
 * 后端 project_lifecycle.py 定义同一生命周期与允许的相邻切换。
 */
export const STATUS_MAP: Record<string, { label: string; color: string }> = {
  preparing: { label: '筹备', color: 'gold' },
  ready: { label: '待进场', color: 'cyan' },
  executing: { label: '现场实施', color: 'green' },
  acceptance: { label: '验收中', color: 'magenta' },
  suspended: { label: '突发停工', color: 'red' },
  completed: { label: '已完成', color: 'success' },
  archived: { label: '已归档', color: 'purple' },
}

/** 运营中项目状态（人员池/待办口径，与后端 ACTIVE_PROJECT_STATUSES 一致）。
 * 页面不得用「!== archived」等页面级排除代替本常量。
 */
export const ACTIVE_PROJECT_STATUSES = [
  'preparing', 'ready', 'executing', 'acceptance',
]

export const STATUS_LABEL: Record<string, string> = Object.fromEntries(
  Object.entries(STATUS_MAP).map(([k, v]) => [k, v.label]),
)

export const STATUS_COLOR: Record<string, string> = Object.fromEntries(
  Object.entries(STATUS_MAP).map(([k, v]) => [k, v.color]),
)

export const isProjectStatus = (status: string) => Object.prototype.hasOwnProperty.call(STATUS_MAP, status)

/** 未知历史状态只读，保留原值以便按备份与审计记录核对。 */
export const isProjectWriteBlocked = (status?: string) => status !== undefined && (status === 'archived' || !isProjectStatus(status))

/** 派生状态：项目已延期时用红标覆盖，原始状态保留在 baseLabel/baseColor 中。 */
export function projectStatusMeta(status: string, overdue = false): { label: string; color: string; baseLabel: string; baseColor: string } {
  const known = isProjectStatus(status)
  const base = known ? STATUS_MAP[status] : { label: `未知历史状态（${status || '空值'}）`, color: 'warning' }
  if (!known) return { label: base.label, color: base.color, baseLabel: base.label, baseColor: base.color }
  if (overdue) return { label: '已延期', color: 'red', baseLabel: base.label, baseColor: base.color }
  return { label: base.label, color: base.color, baseLabel: base.label, baseColor: base.color }
}

/** 项目状态筛选选项（列表/总览页下拉用） */
export const STATUS_OPTIONS = Object.entries(STATUS_MAP).map(([k, v]) => ({ label: v.label, value: k }))

export const PROJECT_START_STATUS_OPTIONS = ['preparing'].map((value) => ({
  value,
  label: STATUS_MAP[value].label,
}))
