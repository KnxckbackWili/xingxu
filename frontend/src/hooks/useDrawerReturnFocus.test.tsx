import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { useRef, useState } from 'react'
import { useDrawerReturnFocus } from './useDrawerReturnFocus'

let nextId = 0
let frames: Map<number, FrameRequestCallback>
let restoreSpies: () => void
function frame() {
  act(() => { const pending = [...frames.values()]; frames.clear(); pending.forEach(callback => callback(performance.now())) })
}
function Harness() {
  const [open, setOpen] = useState(true)
  const requested = useRef(false)
  const trigger = useRef<HTMLButtonElement>(null)
  useDrawerReturnFocus(open, requested, 'qa-drawer', () => trigger.current)
  return <><button ref={trigger}>菜单入口</button><button onClick={() => { requested.current = true; setOpen(false) }}>关闭</button><button onClick={() => setOpen(true)}>重新打开</button><input aria-label="其他输入" /></>
}
function portal() {
  const wrapper = document.createElement('div'); wrapper.className = 'qa-drawer'
  const body = document.createElement('div'); body.className = 'ant-drawer-body'
  const input = document.createElement('input'); body.append(input); wrapper.append(body); document.body.append(wrapper); input.focus()
  return { wrapper, body }
}
beforeEach(() => {
  frames = new Map(); nextId = 0
  const raf = vi.spyOn(globalThis, 'requestAnimationFrame').mockImplementation(callback => { frames.set(++nextId, callback); return nextId })
  const cancel = vi.spyOn(globalThis, 'cancelAnimationFrame').mockImplementation(id => { frames.delete(id) })
  restoreSpies = () => { raf.mockRestore(); cancel.mockRestore() }
})
afterEach(() => { document.querySelectorAll('.qa-drawer').forEach(node => node.remove()); restoreSpies() })

it('waits for its body portal to disappear and restores focus even if the shell remains', () => {
  render(<Harness />); const { body, wrapper } = portal()
  fireEvent.click(screen.getByText('关闭')); frame()
  expect(screen.getByText('菜单入口')).not.toHaveFocus()
  body.remove(); frame()
  expect(wrapper).toBeInTheDocument()
  expect(screen.getByText('菜单入口')).toHaveFocus()
  expect(frames.size).toBe(0)
})
it('respects a different input the user focused while the drawer was closing', () => {
  render(<Harness />); const { body } = portal()
  fireEvent.click(screen.getByText('关闭')); frame()
  screen.getByRole('textbox', { name: '其他输入' }).focus(); body.remove(); frame()
  expect(screen.getByRole('textbox', { name: '其他输入' })).toHaveFocus()
})
it('cancels a pending return when reopened or unmounted', () => {
  const view = render(<Harness />); portal()
  fireEvent.click(screen.getByText('关闭')); expect(frames.size).toBe(1)
  fireEvent.click(screen.getByText('重新打开')); expect(frames.size).toBe(0)
  fireEvent.click(screen.getByText('关闭')); expect(frames.size).toBe(1)
  view.unmount(); expect(frames.size).toBe(0)
})
