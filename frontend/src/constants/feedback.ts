/** 系统问题反馈（HYPE-72）状态唯一事实源。
 *  值与后端 app/models 的 FEEDBACK_STATUSES 一致，页面不得另定义。 */
export const FEEDBACK_STATUS_MAP: Record<string, { label: string; color: string }> = {
  pending: { label: '待处理', color: 'gold' },
  processing: { label: '处理中', color: 'blue' },
  done: { label: '已处理', color: 'green' },
}

export const FEEDBACK_STATUS_OPTIONS = Object.entries(FEEDBACK_STATUS_MAP).map(([value, meta]) => ({
  value,
  label: meta.label,
}))

/** 可读取/管理反馈的角色（与后端 feedback.MANAGE_ROLES 一致）。
 *  普通用户只能提交，不得看到管理列表/详情入口。 */
export const FEEDBACK_MANAGE_ROLES = ['admin', 'director', 'pm']

export const canManageFeedback = (role?: string) => !!role && FEEDBACK_MANAGE_ROLES.includes(role)
