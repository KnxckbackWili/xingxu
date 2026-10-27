import { PM_ROLES, PM_WORKBENCH_ROLES, WORKER_ROLES } from './roles'
import { hasAnySystemPermission, type PermissionUser } from './systemPermissions'

export type NavigationUser = PermissionUser | string | null | undefined
export const navigationRole = (user: NavigationUser) => typeof user === 'string' ? user : user?.role

/** 管理端导航与路由守卫的单一事实源。
 *  菜单只渲染用户有权限的入口，路由守卫用同一份声明拦截 URL 直达。 */
export const NAV_ACCESS: Record<string, string[]> = {
  '/worker/week': WORKER_ROLES,
  '/worker/issues': WORKER_ROLES,
  '/worker/projects': WORKER_ROLES,
  '/worker/my': WORKER_ROLES,
  '/worker/messages': WORKER_ROLES,
  '/worker/feedback': WORKER_ROLES,
  '/pm/dashboard': PM_WORKBENCH_ROLES,
  '/pm/my-schedule': PM_WORKBENCH_ROLES,
  '/pm/team-schedule': PM_WORKBENCH_ROLES,
  '/pm/projects': PM_ROLES,
  '/pm/inventory': PM_WORKBENCH_ROLES,
  '/pm/people': PM_WORKBENCH_ROLES,
  '/pm/governance': ['admin', 'director', 'pm', 'lead'],
  '/pm/project-recycle-bin': PM_ROLES,
  '/pm/users': ['admin'],
  '/pm/permissions': ['admin'],
  '/pm/storage': ['admin'],
  '/pm/backups': ['admin'],
  '/pm/system-updates': ['admin'],
  '/pm/stats': PM_WORKBENCH_ROLES,
  '/pm/messages': PM_ROLES,
  '/pm/ai-tokens': ['admin'],
  '/pm/templates': ['admin'],
  '/pm/notification-channels': ['admin'],
  '/pm/holidays': [...PM_ROLES, ...WORKER_ROLES],
  '/pm/vehicle-types': ['admin'],
  '/pm/feedback': PM_ROLES,
}

export const NAV_LABEL: Record<string, string> = {
  '/pm/dashboard': '工作台',
  '/pm/my-schedule': '人员',
  '/pm/team-schedule': '人员',
  '/pm/projects': '项目',
  '/pm/inventory': '物品总览',
  '/pm/people': '人员',
  '/pm/governance': '项目移交',
  '/pm/project-recycle-bin': '项目回收站',
  '/pm/users': '账号',
  '/pm/permissions': '成员权限',
  '/pm/storage': '存储管理',
  '/pm/backups': '备份与恢复',
  '/pm/system-updates': '软件更新',
  '/pm/stats': '统计',
  '/pm/messages': '消息',
  '/pm/ai-tokens': '外部工具接入',
  '/pm/templates': '项目模板',
  '/pm/notification-channels': '通知设置',
  '/pm/holidays': '节假日设置',
  '/pm/vehicle-types': '车型库',
  '/pm/feedback': '使用反馈',
  '/worker/week': '本周',
  '/worker/issues': '问题',
  '/worker/projects': '项目',
  '/worker/my': '我的',
  '/worker/messages': '消息',
  '/worker/feedback': '使用反馈',
}

/** 用途和旧称供功能查找使用；展示名与路由权限分别保持单源。 */
export const NAV_DESCRIPTION: Record<string, string> = {
  '/pm/dashboard': '先处理待办，再看项目进展和风险',
  '/pm/projects': '打开、新建或导入你能查看的项目',
  '/pm/people': '按周核对人员与项目安排、不可用时段和冲突',
  '/pm/messages': '查看通知并回到对应工作',
  '/pm/my-schedule': '查看和调整自己的工作日期',
  '/pm/team-schedule': '按日期查看团队在做什么',
  '/pm/inventory': '跨项目查找物品、位置和库存',
  '/pm/stats': '比较可见项目的进度与人员产出',
  '/pm/governance': '申请或处理项目负责人移交，保留原项目资料',
  '/pm/project-recycle-bin': '查看删除前备份并还原你有权限管理的项目',
  '/pm/users': '维护账号、角色和组织归属',
  '/pm/permissions': '按成员管理全系统查看和操作权限',
  '/pm/templates': '维护新项目的工作项、检查和资料要求',
  '/pm/holidays': '核对年度放假、调休补班和数据缺失，维护发布来源',
  '/pm/vehicle-types': '维护创建项目时可选的车型',
  '/pm/notification-channels': '配置站外通知发送方式',
  '/pm/storage': '查看文件占用，预览并确认旧周资料保留策略',
  '/pm/backups': '保存系统备份或从完整备份恢复',
  '/pm/system-updates': '从自己的 Gitea 仓库检查和安装软件更新',
  '/pm/ai-tokens': '设置只读 Agent 接入、访问令牌和 AI 用量预算',
  '/pm/feedback': '反馈软件使用中遇到的问题',
  '/worker/week': '查看本人周计划，登记实际完成与提交资料',
  '/worker/issues': '上报现场问题，跟进处理结果',
  '/worker/projects': '查看自己参与的项目和现场资料',
  '/worker/my': '按周查看实际记录、协助与修订历史',
  '/worker/messages': '查看通知并回到对应工作',
  '/worker/feedback': '反馈软件使用中遇到的问题',
}

export const NAV_ALIASES: Record<string, string[]> = {}

export const NAV_PERMISSION_KEYS: Record<string, string[]> = {
  '/pm/dashboard': ['workspace.view', 'insights.view'],
  '/pm/people': ['workspace.view', 'personal.schedule.read'],
  '/pm/team-schedule': ['workspace.view'],
  '/pm/my-schedule': ['personal.schedule.read', 'personal.schedule.manage'],
  '/pm/stats': ['insights.view'],
  '/pm/inventory': ['system.inventory.view'],
  '/pm/users': ['system.users.read', 'system.users.manage'],
  '/pm/templates': ['system.templates.view', 'system.templates.manage', 'system.template_io.manage'],
  '/pm/holidays': ['system.holidays.read', 'system.holidays.manage'],
  '/pm/vehicle-types': ['system.vehicle_types.view', 'system.vehicle_types.manage'],
  '/pm/ai-tokens': ['system.agent_tokens.manage'],
  '/pm/notification-channels': ['system.notifications.configure'],
  '/pm/storage': ['system.backups.read'],
  '/pm/backups': ['system.backups.read', 'system.backups.create', 'system.backups.download', 'system.backups.delete', 'system.backups.restore'],
  '/pm/feedback': ['feedback.submit', 'system.feedback.manage'],
  '/worker/feedback': ['feedback.submit', 'system.feedback.manage'],
  '/pm/messages': ['personal.messages.use'],
  '/worker/messages': ['personal.messages.use'],
}

export function canAccessNav(key: string, subject?: NavigationUser): boolean {
  const role = navigationRole(subject)
  const user = typeof subject === 'string' ? { role: subject } : subject
  const allow = NAV_ACCESS[key]
  if (!allow) return true
  if (!user) return false
  if (key === '/pm/system-updates') return role === 'admin' && !('is_active' in user && user.is_active === false)
  if (key === '/pm/permissions') return role === 'admin'
  if (key === '/pm/project-recycle-bin') return !!role && allow.includes(role) && user.permission_overrides?.['project.delete'] !== false && user.permission_overrides?.['project.read'] !== false
  // These reads keep their existing project scope. Contextual capability
  // defaults must not be mistaken for global manager/data privileges.
  if (['/pm/projects', '/worker/projects', '/worker/week', '/worker/issues'].includes(key)) {
    if (user.permission_overrides?.['project.read'] === false || !role || !allow.includes(role)) return false
    return true
  }
  if (key === '/pm/inventory' && user.permission_overrides?.['system.inventory.read'] === true) return true
  // Owners retain access to follow their own applications; the review action
  // grants a reviewer an entry point but does not alter approval qualification.
  if (key === '/pm/governance') return false
  const keys = NAV_PERMISSION_KEYS[key]
  if (!keys) return !!role && allow.includes(role)
  if (!Array.isArray(user.system_permissions) && !keys.some(permission => typeof user.permission_overrides?.[permission] === 'boolean')) {
    return !!role && allow.includes(role)
  }
  return hasAnySystemPermission(user, keys)
}

export function systemHomeRoute(user: PermissionUser | null | undefined): string {
  if (canAccessNav('/pm/dashboard', user)) return '/pm/dashboard'
  if (['worker', 'intern'].includes(user?.role ?? '')) return canAccessNav('/worker/week', user) ? '/worker/week' : '/worker/my'
  if (canAccessNav('/pm/projects', user)) return '/pm/projects'
  return '/pm/messages'
}
