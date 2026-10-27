import type { ReactNode } from 'react'
import {
  DashboardOutlined, ProjectOutlined, DatabaseOutlined, TeamOutlined, AuditOutlined, UserOutlined, MessageOutlined, ApiOutlined,
  SoundOutlined, CarOutlined, CommentOutlined, AppstoreOutlined, WarningOutlined, CloudDownloadOutlined, SettingOutlined,
  CalendarOutlined, FolderOpenOutlined, DeleteOutlined, SafetyOutlined,
} from '@ant-design/icons'
import { canAccessNav, NAV_ALIASES, NAV_DESCRIPTION, NAV_LABEL, type NavigationUser } from '../constants/nav'

export type MenuChild = { key: string; icon: ReactNode; label: string; description: string; aliases: string[] }
export type MenuGroup = { type: 'group'; key: string; label: string; children: MenuChild[] }
/** A main destination; `match` lists the route prefixes that belong to it. */
export type AppNavItem = MenuChild & { match: string[] }

const ICONS: Record<string, ReactNode> = {
  '/pm/dashboard': <DashboardOutlined />, '/pm/projects': <ProjectOutlined />, '/pm/people': <TeamOutlined />,
  '/pm/messages': <MessageOutlined />, '/worker/week': <DashboardOutlined />, '/worker/my': <UserOutlined />,
  '/pm/inventory': <AppstoreOutlined />, '/pm/project-recycle-bin': <DeleteOutlined />, '/pm/permissions': <SafetyOutlined />,
  '/pm/users': <UserOutlined />, '/pm/templates': <FolderOpenOutlined />, '/pm/vehicle-types': <CarOutlined />,
  '/pm/holidays': <CalendarOutlined />, '/pm/notification-channels': <SoundOutlined />, '/pm/backups': <DatabaseOutlined />,
  '/pm/storage': <DatabaseOutlined />, '/pm/ai-tokens': <ApiOutlined />, '/pm/feedback': <CommentOutlined />,
  '/pm/system-updates': <CloudDownloadOutlined />, '/worker/issues': <WarningOutlined />, '/worker/messages': <MessageOutlined />,
  '/worker/feedback': <CommentOutlined />, '/pm/settings': <SettingOutlined />, '/pm/governance': <AuditOutlined />,
}
const item = (key: string): MenuChild => ({ key, icon: ICONS[key], label: NAV_LABEL[key], description: NAV_DESCRIPTION[key], aliases: NAV_ALIASES[key] ?? [] })

/** Settings, grouped as one page instead of a flat drawer. Each entry keeps the route's own permission check. */
const SETTINGS: { key: string; label: string; keys: string[] }[] = [
  { key: 'team', label: '团队与权限', keys: ['/pm/users', '/pm/permissions'] },
  { key: 'project', label: '项目配置', keys: ['/pm/templates', '/pm/vehicle-types', '/pm/holidays'] },
  { key: 'data', label: '数据与安全', keys: ['/pm/backups', '/pm/storage', '/pm/project-recycle-bin'] },
  { key: 'system', label: '系统', keys: ['/pm/notification-channels', '/pm/ai-tokens', '/pm/system-updates'] },
]
export const MENU_GROUPS = (user?: NavigationUser): MenuGroup[] =>
  SETTINGS.map(group => ({ type: 'group' as const, key: group.key, label: group.label, children: group.keys.filter(key => canAccessNav(key, user)).map(item) }))
    .filter(group => group.children.length)
export const MENU_ITEMS = (user?: NavigationUser): MenuChild[] => MENU_GROUPS(user).flatMap(group => group.children)

/** One navigation for every role: managers and field staff share the same shell and pages; entries follow permissions. */
export function appNavItems(user?: NavigationUser): AppNavItem[] {
  const items: AppNavItem[] = []
  const workbench = canAccessNav('/pm/dashboard', user) ? '/pm/dashboard' : canAccessNav('/worker/week', user) ? '/worker/week' : ''
  if (workbench) items.push({ ...item(workbench), label: '工作台', description: NAV_DESCRIPTION['/pm/dashboard'], match: ['/pm/dashboard', '/worker/week'] })
  if (canAccessNav('/pm/projects', user)) items.push({ ...item('/pm/projects'), match: ['/pm/projects', '/pm/inventory', '/worker/projects'] })
  if (canAccessNav('/worker/issues', user)) items.push({ ...item('/worker/issues'), match: ['/worker/issues'] })
  if (canAccessNav('/pm/people', user)) items.push({ ...item('/pm/people'), match: ['/pm/people'] })
  const messages = canAccessNav('/pm/messages', user) ? '/pm/messages' : canAccessNav('/worker/messages', user) ? '/worker/messages' : ''
  if (messages) items.push({ ...item(messages), match: ['/pm/messages', '/worker/messages'] })
  if (MENU_ITEMS(user).length) items.push({ key: '/pm/settings', icon: ICONS['/pm/settings'], label: '设置', description: '账号、模板、备份与系统配置', aliases: [],
    match: ['/pm/settings', ...MENU_ITEMS(user).map(entry => entry.key)] })
  return items
}

/** Main destinations without settings (settings has its own page). */
export function primaryItems(user?: NavigationUser): MenuChild[] {
  return appNavItems(user).filter(entry => entry.key !== '/pm/settings')
}

export function activeNavKey(items: AppNavItem[], pathname: string): string | undefined {
  return items.find(entry => entry.match.some(prefix => pathname === prefix || pathname.startsWith(`${prefix}/`)))?.key
}
