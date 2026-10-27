import { afterEach, expect, it } from 'vitest'
import { installAccessibilityPatches } from './a11y'

let uninstall: (() => void) | undefined
afterEach(() => { uninstall?.(); document.body.innerHTML = '' })

it('keeps a progress purpose separate from its changing percentage', () => {
  document.body.innerHTML = '<div class="ant-progress" role="progressbar" aria-valuenow="0"><span class="ant-progress-text">0%</span></div>'
  uninstall = installAccessibilityPatches()
  const progress = document.querySelector('[role=progressbar]')!
  expect(progress.getAttribute('aria-label')).toBe('进度')
  progress.setAttribute('aria-valuenow', '100')
  progress.querySelector('span')!.textContent = '✓'
  expect(progress.getAttribute('aria-label')).toBe('进度')
  expect(progress.getAttribute('aria-valuenow')).toBe('100')
})

it('preserves an explicit progress name', () => {
  document.body.innerHTML = '<div class="ant-progress" role="progressbar" aria-label="文件上传进度"><span class="ant-progress-text">0%</span></div>'
  uninstall = installAccessibilityPatches()
  expect(document.querySelector('[role=progressbar]')!.getAttribute('aria-label')).toBe('文件上传进度')
})
