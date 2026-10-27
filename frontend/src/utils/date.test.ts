import { describe, expect, it } from 'vitest'
import dayjs from 'dayjs'
import { formatDateTime, parseDateTime } from './date'

describe('formatDateTime UTC audit timestamps', () => {
  it('renders legacy naive UTC exactly like an explicit UTC timestamp', () => {
    expect(formatDateTime('2026-10-04T19:05:30')).toBe(dayjs('2026-10-04T19:05:30Z').format('YYYY-MM-DD HH:mm'))
    expect(formatDateTime('2026-10-04 19:05:30.123456')).toBe(formatDateTime('2026-10-04T19:05:30.123456Z'))
  })

  it('respects explicit timezones without adding a second timezone', () => {
    expect(formatDateTime('2026-10-05T03:05:30+08:00')).toBe(formatDateTime('2026-10-04T19:05:30Z'))
  })

  it('preserves calendar dates and handles invalid values', () => {
    expect(formatDateTime('2026-10-05')).toBe('2026-10-05 00:00')
    expect(formatDateTime('invalid')).toBe('-')
    expect(formatDateTime(null)).toBe('-')
    expect(parseDateTime(null).isValid()).toBe(false)
    expect(parseDateTime(undefined).isValid()).toBe(false)
    expect(parseDateTime('2026-10-04T19:05:30').valueOf()).toBe(parseDateTime('2026-10-05T03:05:30+08:00').valueOf())
  })
})
