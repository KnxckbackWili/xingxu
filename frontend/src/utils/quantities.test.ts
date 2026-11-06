import { describe, expect, it } from 'vitest'
import { formatQuantities } from './quantities'

describe('project quantities', () => {
  it('keeps each unit on its own line of the summary', () => {
    expect(formatQuantities([{ unit: '车辆环节', completed: 1.5, target: 5 }, { unit: '工作项', completed: 0, target: 0 }])).toBe('1.5/5 车辆环节；0/0 工作项')
  })
  it('formats decimal aggregation without floating point artifacts', () => {
    expect(formatQuantities([{ unit: '米', completed: 0.1 + 0.2, target: 0.3 }])).toBe('0.3/0.3 米')
  })
})
