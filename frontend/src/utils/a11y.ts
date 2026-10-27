/**
 * 全站可访问性兜底（T019/T020）。
 *
 * Ant Design 部分组件不自动产生 axe 要求可访问语义：
 *   - Select 的 combobox 搜索框没有可访问名称（placeholder 不算 name）
 *   - Table 行选择的 Checkbox 没有 aria-label
 *   - 横向滚动的 `.ant-table-content` 不可键盘聚焦（scrollable-region-focusable）
 *   - `<Progress>` 没有可访问名称（aria-progressbar-name）
 *   - 内联编辑的 Input / InputNumber 没有可访问名称
 *
 * 源码层已为常见控件补 aria-label（见各页面），这里在 DOM 层做幂等兜底：
 * 只对没有可访问名称的节点补，不覆盖源码显式指定；随 DOM 变化自动修补，
 * 适配异步加载/表格重绘后再渲染的节点。
 */

function selectName(input: HTMLInputElement): string | null {
  const select = input.closest('.ant-select')
  if (!select) return null
  // A control's name describes its purpose, rather than its changing value.
  const label = select.closest('.ant-form-item')?.querySelector('.ant-form-item-label label')
  const formName = label?.textContent?.trim()
  if (formName) return formName
  const nativeName = [...(input.labels ?? [])].map(item => item.textContent?.trim()).find(Boolean)
  if (nativeName) return nativeName
  const ph = select.querySelector('.ant-select-selection-placeholder')
  const text = ph && ph.textContent ? ph.textContent.trim() : ''
  if (text) return text
  const cell = select.closest('td')
  const headers = cell?.closest('table')?.tHead?.rows
  if (cell && headers?.length) {
    const heading = headers[headers.length - 1].cells[cell.cellIndex]?.textContent?.trim()
    if (heading) return heading
  }
  return '选择选项'
}

function hasAccessibleName(input: HTMLElement): boolean {
  if (input.getAttribute('aria-label')?.trim()) return true
  const labelledBy = input.getAttribute('aria-labelledby')?.trim().split(/\s+/) ?? []
  return labelledBy.some(id => {
    const label = document.getElementById(id)
    return !!(label?.textContent?.trim() || label?.getAttribute('aria-label')?.trim())
  })
}

function patchSelect(input: HTMLInputElement) {
  if (hasAccessibleName(input)) return
  const name = selectName(input)
  if (name) input.setAttribute('aria-label', name)
}

function patchCheckbox(input: HTMLInputElement) {
  if (hasAccessibleName(input)) return
  if (input.closest('.ant-table-selection-column')) {
    input.setAttribute('aria-label', '选择该行')
  } else if (input.closest('.ant-list-item, li')) {
    input.setAttribute('aria-label', '选择该条')
  }
}

function patchScrollable(el: HTMLElement) {
  if (el.getAttribute('tabindex') !== null) return
  const style = getComputedStyle(el)
  const scrollX = style.overflowX === 'auto' || style.overflowX === 'scroll'
  const scrollY = style.overflowY === 'auto' || style.overflowY === 'scroll'
  if (!scrollX && !scrollY) return
  el.setAttribute('tabindex', '0')
  el.setAttribute('role', 'region')
  if (!hasAccessibleName(el)) {
    el.setAttribute('aria-label', '表格横向滚动区域')
  }
}

function patchProgress(el: HTMLElement) {
  if (hasAccessibleName(el)) return
  // The value is already exposed by aria-valuenow. A captured percentage in
  // the name becomes stale when the same component finishes or is reused.
  el.setAttribute('aria-label', '进度')
}

function scan() {
  document.querySelectorAll<HTMLInputElement>('input.ant-select-selection-search-input').forEach(patchSelect)
  document.querySelectorAll<HTMLInputElement>('input.ant-checkbox-input').forEach(patchCheckbox)
  document.querySelectorAll<HTMLElement>('.ant-table-content').forEach(patchScrollable)
  document.querySelectorAll<HTMLElement>('.ant-progress').forEach(patchProgress)
}

/** 安装全局可访问性修补，返回卸载函数（组件卸载时调用）。 */
export function installAccessibilityPatches(): () => void {
  scan()
  const mo = new MutationObserver(() => scan())
  mo.observe(document.documentElement, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ['class'],
  })
  return () => mo.disconnect()
}
