import { afterEach, expect, it } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { installAccessibilityPatches } from './a11y'

const stop: Array<() => void> = []
afterEach(() => { stop.splice(0).forEach(dispose => dispose()) })
function install(markup: string) {
  render(<div dangerouslySetInnerHTML={{ __html: markup }} />)
  stop.push(installAccessibilityPatches())
  return screen.getByRole('combobox')
}

it('names form selects by their purpose before placeholders or changing selected values', async () => {
  const input = install('<div class="ant-form-item"><div class="ant-form-item-label"><label>安排什么工作</label></div><div class="ant-select"><input role="combobox" class="ant-select-selection-search-input"><span class="ant-select-selection-placeholder">选择工作</span><span class="ant-select-selection-item">现场新增工作</span></div></div>')
  expect(input).toHaveAccessibleName('安排什么工作')
  document.querySelector('.ant-select-selection-item')!.textContent = '已有项目任务'
  await waitFor(() => expect(input).toHaveAccessibleName('安排什么工作'))
})

it('uses a native associated label outside Form.Item', () => {
  const input = install('<label for="report">报告类型</label><div class="ant-select"><input id="report" role="combobox" class="ant-select-selection-search-input"><span class="ant-select-selection-item">周报</span></div>')
  expect(input).toHaveAccessibleName('报告类型')
})

it.each([
  ['aria-label="源码指定的名称"', '', '源码指定的名称'],
  ['aria-labelledby="existing-label"', '<span id="existing-label">关联名称</span>', '关联名称'],
])('preserves explicit accessible names %s', (attributes, label, name) => {
  const input = install(`${label}<div class="ant-form-item"><div class="ant-form-item-label"><label>表单兜底</label></div><div class="ant-select"><input role="combobox" class="ant-select-selection-search-input" ${attributes}><span class="ant-select-selection-item">动态值</span></div></div>`)
  expect(input).toHaveAccessibleName(name)
  if (attributes.startsWith('aria-labelledby')) expect(input).not.toHaveAttribute('aria-label')
})

it('uses the matching table column for an otherwise unnamed inline select', () => {
  const input = install('<table><thead><tr><th>采购项</th><th>到货状态</th></tr></thead><tbody><tr><td>线缆</td><td><div class="ant-select"><input role="combobox" class="ant-select-selection-search-input"><span class="ant-select-selection-item">已下单</span></div></td></tr></tbody></table>')
  expect(input).toHaveAccessibleName('到货状态')
})

it('keeps a stable generic fallback rather than naming unnamed controls by their values', () => {
  const input = install('<div class="ant-select"><input role="combobox" class="ant-select-selection-search-input" aria-labelledby="missing"><span class="ant-select-selection-item">周报</span></div>')
  expect(input).toHaveAccessibleName('选择选项')
  document.querySelector('.ant-select-selection-item')!.textContent = '月报'
  expect(input).toHaveAccessibleName('选择选项')
})

it('also preserves valid labelled-by names on checkboxes, progress and scroll areas', () => {
  render(<><span id="row-name">选择线缆记录</span><span id="progress-name">线缆敷设进度</span><span id="table-name">采购事项</span>
    <div className="ant-table-selection-column"><input type="checkbox" className="ant-checkbox-input" aria-labelledby="row-name" /></div>
    <div className="ant-progress" role="progressbar" aria-labelledby="progress-name"><span className="ant-progress-text">50%</span></div>
    <div className="ant-table-content" aria-labelledby="table-name" style={{ overflowX: 'auto' }}>清单</div></>)
  stop.push(installAccessibilityPatches())
  expect(screen.getByRole('checkbox')).toHaveAccessibleName('选择线缆记录')
  expect(screen.getByRole('progressbar')).toHaveAccessibleName('线缆敷设进度')
  expect(screen.getByRole('region')).toHaveAccessibleName('采购事项')
  for (const role of ['checkbox', 'progressbar', 'region']) expect(screen.getByRole(role)).not.toHaveAttribute('aria-label')
})
