import { act, fireEvent, render, screen, cleanup } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import ContextTip from './ContextTip'

// Check the help state and keyboard behavior without depending on portal animation.
vi.mock('antd', () => ({
  Button: ({ children, icon, type: _type, size: _size, ...props }: any) => <button {...props}>{icon}{children}</button>,
  Popover: ({ open, title, content, children, onOpenChange }: any) => <>
    <span onClick={() => onOpenChange(!open)}>{children}</span>
    {open && <aside>{title}{content}</aside>}
  </>,
}))
vi.mock('../stores/auth', () => ({ useAuth: () => ({ user: { id: 'alice' } }) }))

beforeEach(() => {
  localStorage.clear(); sessionStorage.clear()
  vi.useFakeTimers()
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue(new DOMRect(100, 100, 24, 24))
})
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks() })

it('never opens automatically while the user is working or focusing the help button', () => {
  render(<ContextTip id="prep" title="快捷调整">直接选择状态即可保存</ContextTip>)
  act(() => { vi.advanceTimersByTime(2100) })
  expect(screen.queryByText('直接选择状态即可保存')).not.toBeInTheDocument()
  fireEvent.focus(screen.getByRole('button', { name: '操作提示：快捷调整' }))
  act(() => { vi.advanceTimersByTime(8 * 24 * 60 * 60 * 1000) })
  expect(screen.queryByText('直接选择状态即可保存')).not.toBeInTheDocument()
})

it('opens on request and returns focus after Escape or explicit dismissal', () => {
  render(<ContextTip id="prep" title="快捷调整">直接选择状态即可保存</ContextTip>)
  const trigger = screen.getByRole('button', { name: '操作提示：快捷调整' })
  fireEvent.click(trigger)
  expect(screen.getByText('直接选择状态即可保存')).toBeVisible()
  expect(trigger).toHaveAttribute('aria-expanded', 'true')
  const close = screen.getByRole('button', { name: '关闭提示：快捷调整' })
  close.focus()
  fireEvent.keyDown(close, { key: 'Escape' })
  expect(screen.queryByText('直接选择状态即可保存')).not.toBeInTheDocument()
  expect(trigger).toHaveFocus()
  expect(trigger).toHaveAttribute('aria-expanded', 'false')
  fireEvent.click(trigger)
  fireEvent.click(screen.getByRole('button', { name: '关闭提示：快捷调整' }))
  expect(screen.queryByText('直接选择状态即可保存')).not.toBeInTheDocument()
  expect(trigger).toHaveFocus()
})

it('closes a previous topic when the page changes', () => {
  const view = render(<ContextTip id="prep" title="准备">准备帮助</ContextTip>)
  fireEvent.click(screen.getByRole('button', { name: '操作提示：准备' }))
  expect(screen.getByText('准备帮助')).toBeVisible()
  view.rerender(<ContextTip id="gantt" title="工期">工期帮助</ContextTip>)
  expect(screen.queryByText('工期帮助')).not.toBeInTheDocument()
})
