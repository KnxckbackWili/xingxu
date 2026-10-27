import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { Link, createMemoryRouter, RouterProvider, Routes, Route, useLocation, useNavigate } from 'react-router-dom'
import { Modal } from 'antd'
import { useUnsavedNavigation } from './useUnsavedNavigation'
let confirmation: any
let confirm: ReturnType<typeof vi.spyOn>
function Work() {
  const [dirty, setDirty] = useUnsavedNavigation()
  const navigate = useNavigate()
  const location = useLocation()
  return <><div>{location.pathname}{location.search}</div><input aria-label="工作量" onChange={() => setDirty(true)} />
    <span>{dirty ? '待保存' : '已保存'}</span>
    <Link to="/start?step=people">下一步</Link>
    <button onClick={() => { setDirty(false); navigate('/other') }}>保存并继续</button>
    <button onClick={() => setDirty(false)}>只保存</button></>
}
function setup(entries = ['/start'], initialIndex?: number) {
  // Production also uses a wildcard data-router root around descendant Routes.
  const router = createMemoryRouter([{ path: '*', element: <><nav><Link to="/other">全局菜单</Link></nav><Routes><Route path="/start" element={<Work />} /><Route path="*" element={<div>其他页面</div>} /></Routes></> }], { initialEntries: entries, initialIndex })
  render(<RouterProvider router={router} />)
  return router
}
beforeEach(() => { confirmation = undefined; confirm = vi.spyOn(Modal, 'confirm').mockImplementation((options: any) => { confirmation = options; return { destroy: vi.fn(), update: vi.fn() } }) })
afterEach(() => { vi.restoreAllMocks() })
it('unmodified pages and save-and-continue navigate without warnings', async () => {
  const router = setup()
  fireEvent.click(screen.getByText('全局菜单'))
  await waitFor(() => expect(router.state.location.pathname).toBe('/other'))
  expect(confirm).not.toHaveBeenCalled()
  await act(() => router.navigate('/start'))
  fireEvent.change(screen.getByLabelText('工作量'), { target: { value: '12' } })
  fireEvent.click(screen.getByText('保存并继续'))
  await waitFor(() => expect(router.state.location.pathname).toBe('/other'))
  expect(confirm).not.toHaveBeenCalled()
})
it('global navigation cancel preserves input, and repeated clicks show one decision', async () => {
  const router = setup()
  fireEvent.change(screen.getByLabelText('工作量'), { target: { value: '12' } })
  fireEvent.click(screen.getByText('全局菜单'))
  fireEvent.click(screen.getByText('全局菜单'))
  await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1))
  expect(confirmation.title).toBe('开工安排有未保存的修改')
  expect(router.state.location.pathname).toBe('/start')
  act(() => confirmation.onCancel())
  expect(screen.getByLabelText('工作量')).toHaveValue('12')
  expect(screen.getByText('待保存')).toBeVisible()
  fireEvent.click(screen.getByText('全局菜单'))
  await waitFor(() => expect(confirm).toHaveBeenCalledTimes(2))
  act(() => confirmation.onOk())
  await waitFor(() => expect(router.state.location.pathname).toBe('/other'))
})
it.each([['Back', ['/other', '/start'], 1, -1], ['Forward', ['/start', '/other'], 0, 1]] as const)('%s is blocked until discard is confirmed', async (_, entries, index, delta) => {
  const router = setup([...entries], index)
  fireEvent.change(screen.getByLabelText('工作量'), { target: { value: '8' } })
  await act(() => router.navigate(delta))
  await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1))
  expect(router.state.location.pathname).toBe('/start')
  act(() => confirmation.onCancel())
  expect(screen.getByLabelText('工作量')).toHaveValue('8')
  await act(() => router.navigate(delta))
  act(() => confirmation.onOk())
  await waitFor(() => expect(router.state.location.pathname).toBe('/other'))
})
it('query-only step change is guarded; successful save clears a pending warning', async () => {
  const router = setup()
  fireEvent.change(screen.getByLabelText('工作量'), { target: { value: '8' } })
  fireEvent.click(screen.getByText('下一步'))
  await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1))
  expect(router.state.location.search).toBe('')
  fireEvent.click(screen.getByText('只保存'))
  await waitFor(() => expect(router.state.location.search).toBe('?step=people'))
  expect(screen.getByText('已保存')).toBeVisible()
})
it('refresh is guarded only while dirty and listener is removed after save', () => {
  setup()
  fireEvent.change(screen.getByLabelText('工作量'), { target: { value: '8' } })
  const dirtyUnload = new Event('beforeunload', { cancelable: true })
  window.dispatchEvent(dirtyUnload)
  expect(dirtyUnload.defaultPrevented).toBe(true)
  fireEvent.click(screen.getByText('只保存'))
  const cleanUnload = new Event('beforeunload', { cancelable: true })
  window.dispatchEvent(cleanUnload)
  expect(cleanUnload.defaultPrevented).toBe(false)
})
