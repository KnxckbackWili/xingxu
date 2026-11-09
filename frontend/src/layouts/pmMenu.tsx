import type { ReactNode } from 'react'
import {
  DashboardOutlined, ProjectOutlined, DatabaseOutlined, UserOutlined, MessageOutlined,
  SoundOutlined, CarOutlined, CommentOutlined, AppstoreOutlined, WarningOutlined, CloudDownloadOutlined, SettingOutlined,
  CalendarOutlined, FolderOpenOutlined, DeleteOutlined,
} from '@ant-design/icons'
import { canAccessNav, NAV_ALIASES, NAV_DESCRIPTION, NAV_LABEL, type NavigationUser } from '../constants/nav'

export type MenuChild = { key: string; icon: ReactNode; label: string; description: string; aliases: string[] }
export type MenuGroup = { type: 'group'; key: string; label: string; children: MenuChild[] }
/** A main destination; `match` lists the route prefixes that belong to it. */
export type AppNavItem = MenuChild & { match: string[] }

const ICONS: Record<string, ReactNode> = {
  '/pm/dashboard': <DashboardOutlined />, '/pm/projects': <ProjectOutlined />,
  '/pm/messages': <MessageOutlined />, '/worker/week': <DashboardOutlined />, '/worker/my': <UserOutlined />,
  '/pm/inventory': <AppstoreOutlined />, '/pm/project-recycle-bin': <DeleteOutlined />,
  '/pm/users': <UserOutlined />, '/pm/templates': <FolderOpenOutlined />, '/pm/vehicle-types': <CarOutlined />,
  '/pm/holidays': <CalendarOutlined />, '/pm/notification-channels': <SoundOutlined />, '/pm/backups': <DatabaseOutlined />,
  '/pm/storage': <DatabaseOutlined />, '/pm/feedback': <CommentOutlined />,
  '/pm/system-updates': <CloudDownloadOutlined />, '/worker/issues': <WarningOutlined />, '/worker/messages': <MessageOutlined />,
  '/worker/feedback': <CommentOutlined />, '/pm/settings': <SettingOutlined />,
}
const item = (key: string): MenuChild => ({ key, icon: ICONS[key], label: NAV_LABEL[key], description: NAV_DESCRIPTION[key], aliases: NAV_ALIASES[key] ?? [] })

/** Settings, grouped as one page instead of a flat drawer. Each entry keeps the route's own permission check. */
const SETTINGS: { key: string; label: string; keys: string[] }[] = [
  // Everyday first; rarely touched settings sit together under 高级.
  { key: 'project', label: '项目', keys: ['/pm/templates', '/pm/vehicle-types', '/pm/holidays'] },
  { key: 'team', label: '人员与数据', keys: ['/pm/users', '/pm/backups', '/pm/project-recycle-bin'] },
  { key: 'system', label: '系统', keys: ['/pm/notification-channels', '/pm/system-updates'] },
  { key: 'advanced', label: '高级', keys: ['/pm/storage'] },
]
export const MENU_GROUPS = (user?: NavigationUser): MenuGroup[] =>
  SETTINGS.map(group => ({ type: 'group' as const, key: group.key, label: group.label, children: group.keys.filter(key => canAccessNav(key, user)).map(item) }))
    .filter(group => group.children.length)
export const MENU_ITEMS = (user?: NavigationUser): MenuChild[] => MENU_GROUPS(user).flatMap(group => group.children)

/** One navigation for every account; administrators also get the settings entries. */
export function appNavItems(user?: NavigationUser): AppNavItem[] {
  if (!canAccessNav('/pm/dashboard', user)) return []
  const items: AppNavItem[] = [
    { ...item('/pm/dashboard'), match: ['/pm/dashboard', '/worker/week'] },
    { ...item('/pm/projects'), match: ['/pm/projects', '/pm/inventory', '/worker/projects'] },
    { ...item('/worker/issues'), match: ['/worker/issues'] },
    { ...item('/pm/messages'), match: ['/pm/messages', '/worker/messages'] },
  ]
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
