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


/** 把接口返回的文件存到本地：链接挂进页面再点击，稍后再释放，浏览器才会用给定文件名。 */
export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url; link.download = filename; link.style.display = 'none'
  document.body.appendChild(link); link.click(); link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 30_000)
}
