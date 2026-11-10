import { describe, expect, it } from 'vitest'
import { projectStageGuidance } from './projectWorkflow'

describe('projectStageGuidance', () => {
  it('names the next status in order and stops at archived', () => {
    expect(['preparing', 'executing', 'acceptance', 'completed'].map(status => projectStageGuidance(status)?.next))
      .toEqual(['executing', 'acceptance', 'completed', 'archived'])
    expect(projectStageGuidance('archived')?.next).toBeUndefined()
    expect(projectStageGuidance('suspended')?.next).toBeUndefined()
    expect(projectStageGuidance('unknown')).toBeNull()
  })
  it('describes each stage without asking for evidence checks', () => {
    for (const status of ['preparing', 'executing', 'acceptance', 'completed', 'archived', 'suspended'])
      expect(projectStageGuidance(status)?.description).not.toMatch(/核对|门禁|齐备/)
  })
})
