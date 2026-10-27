import type { ReactNode } from 'react'
import {
  DashboardOutlined, ProjectOutlined, BarChartOutlined, DatabaseOutlined, TeamOutlined,
  AuditOutlined, UserOutlined, MessageOutlined, ApiOutlined, ScheduleOutlined,
  SoundOutlined, CarOutlined, CommentOutlined, AppstoreOutlined, WarningOutlined, CloudDownloadOutlined,
} from '@ant-design/icons'
import { canAccessNav, NAV_ALIASES, NAV_DESCRIPTION, NAV_LABEL, navigationRole, type NavigationUser } from '../constants/nav'
import { hasAnySystemPermission } from '../constants/systemPermissions'

export type MenuChild = { key: string; icon: ReactNode; label: string; description: string; aliases: string[] }
export type MenuGroup = { type: 'group'; key: string; label: string; children: MenuChild[] }
const ICONS: Record<string, ReactNode> = {
  '/pm/dashboard': <DashboardOutlined />, '/pm/projects': <ProjectOutlined />, '/pm/people': <TeamOutlined />,
  '/pm/messages': <MessageOutlined />, '/worker/week': <ScheduleOutlined />,
  '/pm/my-schedule': <ScheduleOutlined />, '/pm/team-schedule': <TeamOutlined />, '/worker/my': <UserOutlined />,
  '/pm/inventory': <AppstoreOutlined />, '/pm/stats': <BarChartOutlined />,
  '/pm/governance': <AuditOutlined />, '/pm/project-recycle-bin': <DatabaseOutlined />, '/pm/permissions': <AuditOutlined />, '/pm/users': <UserOutlined />, '/pm/templates': <DatabaseOutlined />,
  '/pm/vehicle-types': <CarOutlined />, '/pm/notification-channels': <SoundOutlined />, '/pm/backups': <DatabaseOutlined />,
  '/pm/ai-tokens': <ApiOutlined />, '/pm/feedback': <CommentOutlined />,
  '/pm/system-updates': <CloudDownloadOutlined />,
  '/worker/issues': <WarningOutlined />, '/worker/projects': <ProjectOutlined />, '/worker/messages': <MessageOutlined />, '/worker/feedback': <CommentOutlined />,
}
export const PRIMARY_NAV_KEYS = ['/pm/dashboard', '/pm/projects', '/pm/people', '/pm/messages']
const item = (key: string): MenuChild => ({ key, icon: ICONS[key], label: NAV_LABEL[key], description: NAV_DESCRIPTION[key], aliases: NAV_ALIASES[key] ?? [] })

/** 常用四项直接可见。全部功能分组完整，始终使用与路由相同的权限声明。 */
export function primaryItems(user?: NavigationUser): MenuChild[] {
  const field = ['worker', 'intern'].includes(navigationRole(user) ?? '')
  const subject = typeof user === 'string' ? { role: user } : user
  const manageProjects = hasAnySystemPermission(subject, ['projects.create', 'system.import.create'])
  const keys = PRIMARY_NAV_KEYS.map(key => field && !manageProjects && key === '/pm/projects' ? '/worker/projects' : field && key === '/pm/messages' ? '/worker/messages' : key)
  return keys.filter(key => canAccessNav(key, user)).map(item)
}
export const MENU_GROUPS = (user?: NavigationUser): MenuGroup[] => {
  const keys=['/pm/templates','/pm/users','/pm/permissions','/pm/vehicle-types','/pm/holidays','/pm/notification-channels','/pm/backups','/pm/storage','/pm/system-updates','/pm/ai-tokens','/pm/project-recycle-bin','/pm/inventory']
  const children=keys.filter(key=>canAccessNav(key,user)).map(item)
  return children.length ? [{type:'group',key:'settings',label:'设置',children}] : []
}
export const MENU_ITEMS = (user?: NavigationUser): MenuChild[] => MENU_GROUPS(user).flatMap(group => group.children)

/** 兼容既有消费者；不再把分组默认落点当成侧栏导航或重复页内导航。 */
export function workAreas(user?: NavigationUser) {
  return MENU_GROUPS(user).map(group => ({ label: group.label, items: group.children }))
}
export function primaryMenu(user?: NavigationUser): MenuGroup[] {
  return [{ type: 'group', key: 'common', label: '常用', children: primaryItems(user) }]
}
