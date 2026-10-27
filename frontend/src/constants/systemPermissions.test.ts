import { describe, expect, it } from 'vitest'
import { hasAnySystemPermission, hasSystemPermission } from './systemPermissions'

describe('system permission metadata', () => {
  it('uses effective permissions instead of the former role gate for explicit grants', () => {
    expect(hasSystemPermission({ role: 'worker', system_permissions: ['system.templates.manage'] }, 'system.templates.manage', ['admin'])).toBe(true)
    expect(hasSystemPermission({ role: 'pm', system_permissions: [] }, 'system.people.view', ['admin', 'pm'])).toBe(false)
  })
  it('keeps explicit false and an empty effective list from falling back to inherited roles', () => {
    expect(hasSystemPermission({ role: 'admin', system_permissions: ['system.templates.manage'], permission_overrides: { 'system.templates.manage': false } }, 'system.templates.manage', ['admin'])).toBe(false)
    expect(hasSystemPermission({ role: 'admin', system_permissions: [] }, 'system.templates.manage', ['admin'])).toBe(false)
  })
  it('supports old payloads and unknown keys without granting extra privileges', () => {
    expect(hasSystemPermission({ role: 'admin' }, 'system.templates.manage', ['admin'])).toBe(true)
    expect(hasSystemPermission({ role: 'worker' }, 'system.templates.manage', ['admin'])).toBe(false)
    expect(hasSystemPermission({ role: 'worker', permission_overrides: { 'system.templates.manage': true } }, 'system.templates.manage', ['admin'])).toBe(true)
    expect(hasSystemPermission(null, 'system.templates.manage', true)).toBe(false)
    expect(hasSystemPermission({ role: 'admin' }, 'unknown')).toBe(false)
    expect(hasSystemPermission({ role: 'admin', permission_overrides: { unknown: true } }, 'unknown')).toBe(false)
  })
  it('allows one of the required actions without overriding explicit denials', () => {
    expect(hasAnySystemPermission({ role: 'worker', system_permissions: ['system.templates.view'] }, ['system.templates.view', 'system.templates.manage'], ['admin'])).toBe(true)
    expect(hasAnySystemPermission({ role: 'admin', system_permissions: [] }, ['system.templates.view', 'system.templates.manage'], ['admin'])).toBe(false)
  })
})
