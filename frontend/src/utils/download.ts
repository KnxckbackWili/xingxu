/** 解析 Content-Disposition 中的文件名：优先 RFC 5987 filename*（UTF-8），失败回退 filename。 */
export function parseDispositionFilename(disposition?: string): string {
  if (!disposition) return ''
  const star = disposition.match(/filename\*=UTF-8''([^;]+)/i)
  if (star?.[1]) {
    try { return decodeURIComponent(star[1]) } catch { /* fallthrough to plain filename */ }
  }
  const plain = disposition.match(/filename="?([^";]+)"?/i)
  return plain?.[1] ? plain[1].replace(/^"|"$/g, '') : ''
}

