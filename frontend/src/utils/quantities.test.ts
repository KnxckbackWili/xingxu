import { describe, expect, it } from 'vitest'
import { groupQuantities, formatQuantities } from './quantities'

describe('project quantities', () => {
  it('keeps physical units separate and adds only matching units', () => {
    const groups = groupQuantities([
      { unit: '台', completed: 1, target_quantity: 2 },
      { unit: '米', completed: 2, target_quantity: 10 },
      { unit: '台', completed: 0.5, target_quantity: 3 },
      { unit: '项', completed: 0, target_quantity: null },
    ])
    expect(formatQuantities(groups)).toBe('1.5/5 台；2/10 米；0/0 项')
  })
  it('formats decimal aggregation without floating point artifacts', () => {
    expect(formatQuantities(groupQuantities([
      { unit: '米', completed: 0.1, target_quantity: 0.1 },
      { unit: '米', completed: 0.2, target_quantity: 0.2 },
    ]))).toBe('0.3/0.3 米')
  })
})
