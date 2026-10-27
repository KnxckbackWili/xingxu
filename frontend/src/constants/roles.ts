/** 可进管理端 /pm 的角色（App.tsx 路由守卫共用单一事实源） */
export const PM_ROLES = ['admin', 'director', 'lead', 'pm', 'technician', 'worker', 'intern', 'readonly']
/** 可进现场端 /worker 的角色 */
export const WORKER_ROLES = ['worker', 'intern', 'technician', 'pm', 'lead', 'admin']

/** 管理端核心工作台角色（/pm/dashboard、/pm/people、/pm/stats 守卫）。
 *  登录落地也据此区分：该集合内 → /pm，否则（worker/intern）→ /worker。
 *  worker 虽可进 /pm 项目区，但默认落地是现场工作台，不能按 PM_ROLES 判断。 */
export const PM_WORKBENCH_ROLES = ['admin', 'director', 'lead', 'pm', 'technician']

/** 是否可进 PM 工作台（登录落地 / 通知跳转等「非菜单」判权共用，避免 `role === 'worker'` 三元把 intern 也放行到 /pm） */
export const isPMWorkbench = (role?: string) => (role ? PM_WORKBENCH_ROLES.includes(role) : false)

/** 管理端可操作角色的粗粒度判断。
 * 后端按「能力 + 项目关系」细分拦截，技术负责人不能修改核心资料或成员，
 * 前端只做粗粒度显示控制，被后端拒绝的操作会提示 403 错误。
 */
export const MANAGER_ROLES = ['admin', 'pm']

export const isManager = (role?: string) => (role ? MANAGER_ROLES.includes(role) : false)

/** 角色全名（人员管理/总览等用）。系统已收敛为 admin/pm/worker 三级；旧角色保留映射用于历史数据显示。 */
export const ROLE_NAME: Record<string, string> = {
  admin: '系统管理员', pm: '项目经理', worker: '实施工程师', readonly: '只读',
  director: '总监（旧）', lead: '技术经理（旧）', technician: '技术工程师（旧）', intern: '实习工程师（旧）',
}

/** 角色短名（表格 Tag/下拉用） */
export const ROLE_LABEL: Record<string, string> = {
  admin: '管理员', pm: 'PM', worker: '实施', readonly: '只读',
  director: '总监（旧）', lead: '技术经理（旧）', technician: '技术（旧）', intern: '实习（旧）',
}

/** 角色 Tag 颜色（部分角色有专属色） */
export const ROLE_TAG: Record<string, { label: string; color: string }> = {
  admin: { label: '管理员', color: 'red' },
  pm: { label: 'PM', color: 'blue' },
  worker: { label: '实施', color: 'green' },
  readonly: { label: '只读', color: 'default' },
  lead: { label: '技术经理', color: 'purple' },
  technician: { label: '技术', color: 'cyan' },
  intern: { label: '实习', color: 'default' },
}
