/** 2026-05-23 from a server timestamp, in the reader's own time zone. */
export function day(value: string | null | undefined): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

export function dayTime(value: string | null | undefined): string {
  if (!value) return ''
  const date = new Date(value)
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${day(value)} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function today(): string {
  return day(new Date().toISOString())
}

export function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/** Who ticked a box and when, for its tooltip. */
export function stamp(people: Record<string, string>, by: string | null | undefined, at: string | null | undefined): string {
  if (!at) return ''
  return `${(by && people[by]) || '有人'} · ${day(at)}`
}

/** Save a file the server offers; its name comes from the server's Content-Disposition. */
export function download(path: string) {
  const link = document.createElement('a')
  link.href = `/api${path}`
  link.download = ''
  document.body.appendChild(link)
  link.click()
  link.remove()
}
