import type { ReactNode } from 'react'
import { DashboardOutlined, CarryOutOutlined, CarOutlined, WarningOutlined, FileDoneOutlined, HistoryOutlined, PlusOutlined, SettingOutlined, DownloadOutlined } from '@ant-design/icons'

export interface ProjectNavChild { key: string; label: string; path: string; defaultChild?: boolean }
export interface ProjectNavItem { key: string; label: string; path: string; icon?: ReactNode; children?: ProjectNavChild[]; more?: boolean }
export interface ProjectNavGroup { key: string; label: string; items: ProjectNavItem[] }

/** The only maintained project navigation structure; other views derive from it. */
export const PROJECT_NAV_ITEMS: ProjectNavItem[] = [
  { key: 'overview', label: '概况', path: 'overview', icon: <DashboardOutlined /> },
  { key: 'plan', label: '计划', path: 'plan', icon: <CarryOutOutlined /> },
  { key: 'vehicles', label: '车辆', path: 'vehicles', icon: <CarOutlined /> },
  { key: 'delivery', label: '资料', path: 'documents', icon: <FileDoneOutlined /> },
  { key: 'issues', label: '问题', path: 'issues', icon: <WarningOutlined /> },
  { key: 'field', label: '现场', path: 'inventory', children: [
    { key: 'inventory', label: '物品', path: 'inventory', defaultChild: true },
    { key: 'handover', label: '联系人', path: 'handover' },
  ] },
  { key: 'activity', label: '报告与记录', path: 'reports', more: true, icon: <HistoryOutlined />, children: [
    { key: 'reports', label: '报告', path: 'reports', defaultChild: true },
    { key: 'history', label: '操作记录', path: 'history' },
  ] },
  { key: 'export', label: '导出', path: 'export', more: true, icon: <DownloadOutlined /> },
  { key: 'edit', label: '项目设置', path: 'edit', more: true, icon: <SettingOutlined /> },
]
const descriptions: Record<string, string> = {
  overview: '当前进展、待办和下一步', delivery: '按阶段查看资料清单、版本与输出时机',
  vehicles: '车辆进度表、逐车检查、资料与问题履历', plan: '维护工作项和周计划',
  issues: '上报问题并跟进闭环', field: '物品和联系人', inventory: '物品保管、台账与收发流水',
  handover: '客户联系人、入场说明和交接记录', reports: '查看项目周报和月报',
  history: '谁在何时修改了项目', export: '导出六张交付表、项目包或克隆新项目', edit: '维护项目范围、成员、负责人和外部查看',
}
export const PROJECT_PAGE_INFO = Object.fromEntries(PROJECT_NAV_ITEMS.flatMap(item =>
  [{ key: item.key, label: item.label }, ...(item.children ?? [])].map(entry => [entry.key, { label: entry.label, description: descriptions[entry.key] ?? '', aliases: [] as string[] }])) ) as Record<string, { label: string; title?: string; description: string; aliases: string[] }>
export const PROJECT_DISPLAY_LABEL = Object.fromEntries(Object.entries(PROJECT_PAGE_INFO).map(([key, info]) => [key, info.label])) as Record<string, string>
export const PROJECT_PAGE_TITLE: Record<string, string> = { ...PROJECT_DISPLAY_LABEL, handover: '联系人与入场' }
export const PROJECT_PRIMARY_SECTIONS = PROJECT_NAV_ITEMS.filter(item => !item.more).map(item => ({ key: item.key, label: item.label, defaultKey: item.children?.find(child => child.defaultChild)?.key ?? item.key, keys: item.children?.map(child => child.key) ?? [item.key] }))
export const PROJECT_MORE_KEYS = PROJECT_NAV_ITEMS.filter(item => item.more).flatMap(item => item.children?.map(child => child.key) ?? [item.key])
/** A derived compatibility view for older consumers; no separate group definitions. */
export const PROJECT_NAV_GROUPS: ProjectNavGroup[] = [{ key: 'project', label: '本项目', items: PROJECT_NAV_ITEMS }]
export const FIELD_STAFF_TOP_KEYS = PROJECT_NAV_ITEMS.filter(item => !item.more).map(item => item.key)
export function filterProjectNav(groups: ProjectNavGroup[], _role?: string, _capabilities?: string[]): ProjectNavGroup[] { return groups }
export const PROJECT_ITEM_BY_KEY = Object.fromEntries(PROJECT_NAV_ITEMS.map(item => [item.key, item])) as Record<string, ProjectNavItem>
export const PROJECT_CHILD_BY_SEGMENT = Object.fromEntries(PROJECT_NAV_ITEMS.flatMap(item => (item.children ?? []).map(child => [child.path, { parentKey: item.key, child }]))) as Record<string, { parentKey: string; child: ProjectNavChild }>
export function defaultChildKey(item: ProjectNavItem): string | null { return item.children?.find(child => child.defaultChild)?.key ?? null }
export interface ResolvedNav { parent: string; child: string | null }
export function resolveProjectNav(raw: string): ResolvedNav {
  const tab=raw.replace(/^\//, '')
  if (['documents','delivery','files','archive','preparation'].includes(tab)) return { parent: 'delivery', child: null }
  if (['plan','tasks','schedule'].includes(tab)) return { parent: 'plan', child: null }
  if (['edit','team','start'].includes(tab)) return { parent: 'overview', child: null }
  if (tab==='export') return { parent: 'delivery', child: null }
  if (tab==='site') return { parent: 'vehicles', child: null }
  if (tab==='activity') return { parent: 'activity', child: 'history' }
  const child=PROJECT_CHILD_BY_SEGMENT[tab]
  if (child) return { parent: child.parentKey, child: child.child.key }
  const item=PROJECT_ITEM_BY_KEY[tab]
  return item ? { parent: item.key, child: defaultChildKey(item) } : { parent: 'overview', child: null }
}
export function childSegment(parent: string, child: string): string { return PROJECT_ITEM_BY_KEY[parent]?.children?.find(item => item.key===child)?.path ?? PROJECT_ITEM_BY_KEY[parent]?.path ?? parent }
export interface ProjectActionItem { key: string; label: string; path: string; icon?: ReactNode; requiresEdit?: boolean; hideForFieldStaff?: boolean }
export const PROJECT_ACTIONS: ProjectActionItem[] = [
  { key: 'report', label: '上报问题', path: 'issues?report=1', icon: <PlusOutlined /> },
  ...PROJECT_NAV_ITEMS.filter(item => ['edit','export'].includes(item.key)),
]
export function filterProjectActions(actions: ProjectActionItem[], role?: string, canEditSettings=false, capabilities?: string[]): ProjectActionItem[] {
  return actions.filter(action => !(role==='readonly' && action.key==='report') && (!action.requiresEdit || canEditSettings)
    && (action.key!=='export' || (capabilities!==undefined ? capabilities.includes('project.export') : !['worker','intern','readonly'].includes(role ?? ''))))
}
