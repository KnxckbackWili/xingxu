import { expect, it } from 'vitest'
import { canAccessNav, systemHomeRoute } from './nav'
import { hasSystemPermission } from './systemPermissions'

it('lands a readonly account on its project list with project and message navigation', () => {
  const reader = { role: 'readonly', system_permissions: ['project.read', 'personal.messages.use'] }
  expect(systemHomeRoute(reader)).toBe('/pm/projects')
  expect(canAccessNav('/pm/projects', reader)).toBe(true)
  expect(canAccessNav('/pm/messages', reader)).toBe(true)
  expect(canAccessNav('/pm/permissions', reader)).toBe(false)
})

it('does not show readonly write actions even for stale or forged effective grants', () => {
  const reader = { role: 'readonly', permission_overrides: { 'worker.report': true }, system_permissions: ['worker.report'] }
  expect(hasSystemPermission(reader, 'worker.report', true)).toBe(false)
  expect(hasSystemPermission(reader, 'projects.create', true)).toBe(false)
})

it('keeps legacy readonly project lookup available while denying unknown future actions', () => {
  expect(hasSystemPermission({ role: 'readonly' }, 'project.read')).toBe(true)
  expect(hasSystemPermission({ role: 'readonly' }, 'future.write', true)).toBe(false)
})
