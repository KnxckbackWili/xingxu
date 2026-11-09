import { type PermissionUser } from './systemPermissions'

export type NavigationUser = PermissionUser | string | null | undefined
export const navigationRole = (user: NavigationUser) => typeof user === 'string' ? user : user?.role

/** Entries only a system administrator sees; every other entry is open to every employee. */
export const ADMIN_NAV = new Set(['/pm/users', '/pm/storage', '/pm/backups', '/pm/system-updates', '/pm/notification-channels'])

export const NAV_LABEL: Record<string, string> = {
  '/pm/dashboard': '工作台',
  '/pm/projects': '项目',
  '/pm/inventory': '物品总览',
  '/pm/project-recycle-bin': '项目回收站',
  '/pm/users': '账号',
  '/pm/storage': '存储管理',
  '/pm/backups': '备份与恢复',
  '/pm/system-updates': '软件更新',
  '/pm/messages': '消息',
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
  '/pm/projects': '打开、新建或导入项目',
  '/pm/messages': '查看通知并回到对应工作',
  '/pm/inventory': '跨项目查找物品、位置和库存',
  '/pm/project-recycle-bin': '查看删除前备份并还原项目',
  '/pm/users': '新建账号、停用账号、重置密码',
  '/pm/templates': '维护新项目的工作项、检查和资料要求',
  '/pm/holidays': '核对年度放假、调休补班和数据缺失，维护发布来源',
  '/pm/vehicle-types': '维护创建项目时可选的车型',
  '/pm/notification-channels': '配置站外通知发送方式',
  '/pm/storage': '查看文件占用，清理过期的周资料原件',
  '/pm/backups': '保存系统备份或从完整备份恢复',
  '/pm/system-updates': '检查和安装软件更新',
  '/pm/feedback': '反馈软件使用中遇到的问题',
  '/worker/week': '查看本周工作，登记实际完成与提交资料',
  '/worker/issues': '上报现场问题，跟进处理结果',
  '/worker/projects': '查看项目和现场资料',
  '/worker/my': '按周查看自己的实际记录与修订历史',
  '/worker/messages': '查看通知并回到对应工作',
  '/worker/feedback': '反馈软件使用中遇到的问题',
}

export const NAV_ALIASES: Record<string, string[]> = {}

export function canAccessNav(key: string, subject?: NavigationUser): boolean {
  const user = typeof subject === 'string' ? { role: subject } : subject
  if (!user || user.is_active === false) return false
  return !ADMIN_NAV.has(key) || user.role === 'admin'
}

export function systemHomeRoute(user: PermissionUser | null | undefined): string {
  return user ? '/pm/dashboard' : '/login'
}
