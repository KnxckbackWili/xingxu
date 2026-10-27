import dayjs from 'dayjs'

/** 全站统一日期渲染：
 *  - 显示给用户看的日期带年份：YYYY-MM-DD
 *  - 时间：YYYY-MM-DD HH:mm
 *  - API 入参与 Map key 保持 YYYY-MM-DD，不经过这些函数
 */
export function formatDate(value?: string | number | Date | dayjs.Dayjs | null, fallback = '-'): string {
  if (!value) return fallback
  const d = dayjs(value)
  return d.isValid() ? d.format('YYYY-MM-DD') : fallback
}

export function parseDateTime(value?: string | number | Date | dayjs.Dayjs | null): dayjs.Dayjs {
  // API 的审计时间来自 utcnow()；旧接口省略了 UTC 后缀，不能按浏览器本地时间解析。
  // 只有日期时间字符串补时区，纯日期（实施日、排程日）仍保持日历日期语义。
  const normalized = typeof value === 'string' && /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/.test(value)
    ? `${value.replace(' ', 'T')}Z`
    : value
  return dayjs(normalized ?? null)
}

export function formatDateTime(value?: string | number | Date | dayjs.Dayjs | null, fallback = '-'): string {
  if (!value) return fallback
  const d = parseDateTime(value)
  return d.isValid() ? d.format('YYYY-MM-DD HH:mm') : fallback
}

export function formatMonthDay(value?: string | number | Date | dayjs.Dayjs | null, fallback = '-'): string {
  if (!value) return fallback
  const d = dayjs(value)
  return d.isValid() ? d.format('MM-DD') : fallback
}

export function formatMonthDayRange(start?: string | number | Date | dayjs.Dayjs | null, end?: string | number | Date | dayjs.Dayjs | null, fallback = '-'): string {
  if (!start || !end) return fallback
  const s = dayjs(start)
  const e = dayjs(end)
  if (!s.isValid() || !e.isValid()) return fallback
  return `${s.format('YYYY-MM-DD')} ~ ${e.format('YYYY-MM-DD')}`
}

/** 把「今天」夹到项目周期内：日程默认停在项目起始月而非当月。 */
export function focusDateInRange(today: dayjs.Dayjs, start?: string | Date | null, end?: string | Date | null): dayjs.Dayjs {
  const s = start ? dayjs(start) : null
  const e = end ? dayjs(end) : null
  if (s?.isValid() && today.isBefore(s, 'day')) return s
  if (e?.isValid() && today.isAfter(e, 'day')) return e
  return today
}

/** 项目现场时区的"当地今天"（P2-体验：俄/越现场与国内可能相差一天）。 */
export function todayInTimezone(tz?: string | null): string {
  if (tz) {
    try {
      return dayjs().tz(tz).format('YYYY-MM-DD')
    } catch { /* 非法时区回退本地日期 */ }
  }
  return dayjs().format('YYYY-MM-DD')
}
