import { describe, expect, it } from 'vitest'
import { MENU_GROUPS, MENU_ITEMS, activeNavKey, appNavItems, primaryItems } from './pmMenu'
import { ADMIN_NAV, NAV_LABEL, NAV_DESCRIPTION, canAccessNav } from '../constants/nav'

describe('主导航与设置目录', () => {
  it('gives every account the same four daily destinations', () => {
    for (const role of ['admin', 'employee']) expect(primaryItems(role).map(item => [item.key, item.label])).toEqual([
      ['/pm/dashboard', '工作台'], ['/pm/projects', '项目'], ['/worker/issues', '问题'], ['/pm/messages', '消息'],
    ])
    expect(appNavItems('admin').map(item => item.label)).toEqual(['工作台', '项目', '问题', '消息', '设置'])
    expect(appNavItems({ role: 'employee', is_active: false })).toEqual([])
  })
  it('groups administrator settings without duplicate daily links', () => {
    expect(MENU_GROUPS('admin').map(group => group.label)).toEqual(['项目', '人员与数据', '系统', '高级'])
    const items = MENU_ITEMS('admin'); const paths = items.map(item => item.key)
    for (const path of ['/pm/templates', '/pm/users', '/pm/vehicle-types', '/pm/holidays', '/pm/notification-channels', '/pm/backups', '/pm/storage', '/pm/system-updates', '/pm/project-recycle-bin']) expect(paths).toContain(path)
    for (const path of ['/pm/dashboard', '/pm/projects', '/pm/messages', '/pm/feedback', '/pm/inventory']) expect(paths).not.toContain(path)
    expect(new Set(paths).size).toBe(paths.length)
    for (const item of items) { expect(item.label).toBe(NAV_LABEL[item.key]); expect(item.description).toBe(NAV_DESCRIPTION[item.key]); expect(item.aliases).toEqual([]) }
  })
  it('keeps administrator settings away from employees but leaves them the project recycle bin and holidays', () => {
    const paths = MENU_ITEMS('employee').map(item => item.key)
    for (const path of ADMIN_NAV) { expect(paths).not.toContain(path); expect(canAccessNav(path, 'employee')).toBe(false) }
    expect(paths).toEqual(expect.arrayContaining(['/pm/project-recycle-bin', '/pm/holidays']))
    expect(canAccessNav('/pm/system-updates', { role: 'admin', is_active: false })).toBe(false)
  })
  it('matches field URLs to the merged destinations', () => {
    const nav = appNavItems('employee')
    expect(activeNavKey(nav, '/worker/week')).toBe('/pm/dashboard')
    expect(activeNavKey(nav, '/worker/projects/p1')).toBe('/pm/projects')
    expect(activeNavKey(nav, '/pm/projects/p1/overview')).toBe('/pm/projects')
    expect(activeNavKey(nav, '/worker/messages')).toBe('/pm/messages')
    expect(activeNavKey(nav, '/worker/feedback')).toBeUndefined()
  })
})
