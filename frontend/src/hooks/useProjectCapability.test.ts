import { describe, expect, it } from 'vitest'
import { hasProjectCapability } from './useProjectCapability'
describe('project capability authority', () => {
  it.each(['admin', 'director', 'pm', 'lead', 'technician', 'worker', 'intern'])('%s uses the project grant rather than a global role', () => {
    expect(hasProjectCapability([], 'project.manage_plan', true)).toBe(false)
    expect(hasProjectCapability(['project.manage_plan'], 'project.manage_plan', false)).toBe(true)
    expect(hasProjectCapability(['project.manage_plan'], 'project.manage_members', true)).toBe(false)
  })
  it('only falls back for older responses without capability metadata', () => {
    expect(hasProjectCapability(undefined, 'project.update', true)).toBe(true)
    expect(hasProjectCapability(undefined, 'project.update')).toBe(false)
  })
})
