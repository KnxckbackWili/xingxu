import { describe, expect, it } from 'vitest'
import { canAccessNav, systemHomeRoute } from './nav'
import { hasAnySystemPermission, hasSystemPermission } from './systemPermissions'

describe('two kinds of account', () => {
  it('follows the server list when the session carries one', () => {
    expect(hasSystemPermission({ role: 'employee', system_permissions: ['project.read'] }, 'project.read')).toBe(true)
    expect(hasSystemPermission({ role: 'admin', system_permissions: [] }, 'system.users.manage')).toBe(false)
  })
  it('lets an administrator do everything and an employee all project work', () => {
    expect(hasSystemPermission({ role: 'admin' }, 'system.users.manage')).toBe(true)
    expect(hasSystemPermission({ role: 'employee' }, 'system.users.manage')).toBe(false)
    expect(hasSystemPermission({ role: 'employee' }, 'worker.report')).toBe(true)
    expect(hasAnySystemPermission({ role: 'employee' }, ['system.backups.read', 'project.update'])).toBe(true)
  })
  it('gives nothing to a missing or disabled account', () => {
    expect(hasSystemPermission(null, 'project.read')).toBe(false)
    expect(hasSystemPermission({ role: 'admin', is_active: false }, 'project.read')).toBe(false)
  })
  it('shows administrator pages only to administrators', () => {
    expect(canAccessNav('/pm/users', { role: 'employee' })).toBe(false)
    expect(canAccessNav('/pm/users', { role: 'admin' })).toBe(true)
    expect(canAccessNav('/pm/projects', { role: 'employee' })).toBe(true)
    expect(systemHomeRoute({ role: 'employee' })).toBe('/pm/dashboard')
    expect(systemHomeRoute(null)).toBe('/login')
  })
})
