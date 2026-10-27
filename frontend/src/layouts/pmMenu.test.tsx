import { describe, expect, it } from 'vitest'
import { MENU_GROUPS, MENU_ITEMS, activeNavKey, appNavItems, primaryItems } from './pmMenu'
import { NAV_ACCESS, NAV_LABEL, NAV_DESCRIPTION, canAccessNav } from '../constants/nav'
import { PM_ROLES, WORKER_ROLES } from '../constants/roles'

describe('主导航与设置目录', () => {
  it('reserves software updates in the system settings group for real active administrators, never delegated permissions', () => {
    const admin = { role: 'admin', is_active: true, system_permissions: [] }
    expect(canAccessNav('/pm/system-updates', admin)).toBe(true)
    expect(MENU_GROUPS(admin).find(group => group.key === 'system')?.children).toContainEqual(expect.objectContaining({ key: '/pm/system-updates', label: '软件更新' }))
    for (const role of ['pm', 'director', 'worker']) {
      const delegated = { role, system_permissions: ['system.updates.manage'], permission_overrides: { 'system.updates.manage': true } }
      expect(canAccessNav('/pm/system-updates', delegated)).toBe(false)
      expect(MENU_ITEMS(delegated).some(item => item.key === '/pm/system-updates')).toBe(false)
    }
    const inactiveAdmin = { ...admin, is_active: false }
    expect(canAccessNav('/pm/system-updates', inactiveAdmin)).toBe(false)
  })
  it('gives every role one main navigation; field staff land on their week as the workbench', () => {
    expect(primaryItems('pm').map(item => [item.key, item.label])).toEqual([
      ['/pm/dashboard', '工作台'], ['/pm/projects', '项目'], ['/worker/issues', '问题'], ['/pm/people', '人员'], ['/pm/messages', '消息'],
    ])
    for (const role of ['worker', 'intern']) expect(primaryItems(role).map(item => [item.key, item.label])).toEqual([
      ['/worker/week', '工作台'], ['/pm/projects', '项目'], ['/worker/issues', '问题'], ['/pm/messages', '消息'],
    ])
    expect(appNavItems('admin').map(item => item.label)).toEqual(['工作台', '项目', '问题', '人员', '消息', '设置'])
    expect(appNavItems('readonly').map(item => item.label)).not.toContain('问题')
  })
  it('groups low-frequency tools into four settings groups without duplicate daily links', () => {
    expect(MENU_GROUPS('admin').map(group => group.label)).toEqual(['团队与权限', '项目配置', '数据与安全', '系统'])
    const items = MENU_ITEMS('admin'); const paths = items.map(item => item.key)
    for (const path of ['/pm/templates', '/pm/users', '/pm/permissions', '/pm/vehicle-types', '/pm/holidays', '/pm/notification-channels', '/pm/backups', '/pm/storage', '/pm/system-updates', '/pm/ai-tokens', '/pm/project-recycle-bin']) expect(paths).toContain(path)
    for (const path of ['/pm/dashboard', '/pm/projects', '/pm/people', '/pm/messages', '/pm/stats', '/pm/governance', '/pm/my-schedule', '/pm/team-schedule', '/pm/feedback', '/pm/inventory']) expect(paths).not.toContain(path)
    expect(new Set(paths).size).toBe(paths.length)
    for (const item of items) { expect(item.label).toBe(NAV_LABEL[item.key]); expect(item.description).toBe(NAV_DESCRIPTION[item.key]); expect(item.aliases).toEqual([]) }
  })
  it('keeps field daily routes out of the settings directory', () => {
    for (const role of ['worker', 'intern']) for (const item of MENU_ITEMS(role)) expect(item.key).not.toMatch(/today|schedule|issues|worker\/my|feedback/)
  })
  it('matches old field URLs to the merged destinations', () => {
    const nav = appNavItems('worker')
    expect(activeNavKey(nav, '/worker/projects/p1')).toBe('/pm/projects')
    expect(activeNavKey(nav, '/pm/projects/p1/overview')).toBe('/pm/projects')
    expect(activeNavKey(nav, '/worker/messages')).toBe('/pm/messages')
    expect(activeNavKey(nav, '/worker/feedback')).toBeUndefined()
  })
  it('does not expose admin settings to any other role', () => {
    for (const role of PM_ROLES.filter(role => role !== 'admin')) {
      const paths = MENU_ITEMS(role).map(item => item.key)
      for (const path of ['/pm/users','/pm/backups','/pm/templates','/pm/vehicle-types','/pm/notification-channels','/pm/ai-tokens']) expect(paths).not.toContain(path)
    }
  })
  it('keeps old daily URLs out of settings and removes old search aliases',()=>{
    for(const role of PM_ROLES)expect(MENU_ITEMS(role).some(item=>['/pm/ai','/pm/calendar','/pm/my-schedule','/pm/team-schedule'].includes(item.key))).toBe(false)
    for(const path of ['/worker/week','/worker/issues','/worker/projects','/worker/my','/worker/messages','/worker/feedback'])expect(NAV_ACCESS[path]).toEqual(WORKER_ROLES)
    expect(MENU_ITEMS('admin').find(item=>item.key==='/pm/ai-tokens')?.aliases).toEqual([])
  })
  it('reveals granted global modules to a field role without granting project management', () => {
    const member = { role: 'worker', system_permissions: ['system.templates.view', 'system.backups.read', 'personal.schedule.read'], permission_overrides: { 'system.templates.view': true } }
    expect(MENU_ITEMS(member).map(item => item.key)).toContain('/pm/templates')
    expect(MENU_ITEMS(member).map(item => item.key)).toContain('/pm/backups')
    expect(canAccessNav('/pm/templates', member)).toBe(true)
    expect(canAccessNav('/pm/permissions', member)).toBe(false)
    expect(canAccessNav('/pm/people', member)).toBe(true) // 本人周计划；团队范围仍单独鉴权
  })
  it('does not expose inventory merely because shared inventory reading is a role default', () => {
    const member = { role: 'worker', system_permissions: ['system.inventory.read'] }
    expect(canAccessNav('/pm/inventory', member)).toBe(false)
    expect(canAccessNav('/pm/inventory', { ...member, permission_overrides: { 'system.inventory.read': true } })).toBe(true)
  })
  it('honors revocation and keeps personal messages/account available', () => {
    const member = { role: 'pm', system_permissions: ['workspace.view', 'personal.messages.use'], permission_overrides: { 'workspace.view': false, 'project.read': false } }
    expect(canAccessNav('/pm/dashboard', member)).toBe(false)
    expect(canAccessNav('/pm/projects', member)).toBe(false)
    expect(canAccessNav('/pm/messages', member)).toBe(true)
    expect(canAccessNav('/worker/my', member)).toBe(true)
    expect(canAccessNav('/pm/permissions', { role: 'admin', system_permissions: [], permission_overrides: { 'permission.manage': false } })).toBe(true)
  })
  it('does not expose the retired governance workflow to any role',()=>{
    for(const role of PM_ROLES)expect(MENU_ITEMS(role).some(item=>item.key==='/pm/governance')).toBe(false)
  })
  it('keeps project recovery distinct from system backups and denies explicitly prohibited access',()=>{
    expect(NAV_LABEL['/pm/governance']).toBe('项目移交')
    expect(NAV_DESCRIPTION['/pm/governance']).not.toContain('项目删除')
    expect(canAccessNav('/pm/project-recycle-bin',{role:'worker',system_permissions:[]})).toBe(true)
    expect(MENU_ITEMS('worker').map(item=>item.key)).toContain('/pm/project-recycle-bin')
    expect(canAccessNav('/pm/backups','worker')).toBe(false)
    for(const key of ['project.read','project.delete'])expect(canAccessNav('/pm/project-recycle-bin',{role:'admin',permission_overrides:{[key]:false}})).toBe(false)
  })
})
