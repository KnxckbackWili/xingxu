import { expect, it } from 'vitest'
import { deadlineLabel, basisLabel } from './documentDeadlines'
import type { ProjectDocument } from '../api/projectDocuments'

it('formats an absolute deadline in the saved project timezone across DST', () => {
  expect(deadlineLabel('2026-11-02T04:59:59.999999Z', 'America/New_York')).toBe('2026-11-01 23:59')
  expect(deadlineLabel('2026-03-09T03:59:59.999999Z', 'America/New_York')).toBe('2026-03-08 23:59')
})
it('explains a date-only actual anchor without claiming an exact event time', () => {
  const record = { timing_type: 'after_event', due_basis: { kind: 'actual_date_anchor', actual_date: '2026-11-01' } } as ProjectDocument
  expect(basisLabel(record)).toContain('日历锚点')
  expect(basisLabel(record)).toContain('未记录实际时刻')
})
