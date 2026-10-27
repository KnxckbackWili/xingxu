import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const mockNavigate = vi.fn()

vi.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
}))

vi.mock('../api/client', () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
  errMsg: () => 'mock-error',
}))

import { api } from '../api/client'
import type { User } from '../api'
import { useAuth } from '../stores/auth'
import NotificationBell from './NotificationBell'
import { notifyReadStateChanged } from '../utils/notificationEvents'

function setUser(role: User['role']) {
  useAuth.setState({ user: { id: 'u1', role, username: 'u1', display_name: '用户', phone: '', email: '', is_active: true } })
}

beforeEach(() => {
  vi.clearAllMocks()
  mockNavigate.mockClear()
  vi.mocked(api.get).mockImplementation(async (url: string) => {
    if (url === '/notifications') return { data: [] }
    if (url === '/notifications/unread-count') return { data: { count: 0 } }
    return { data: {} }
  })
})

it('refreshes its unread badge immediately when the message center marks a notification read', async () => {
  setUser('pm')
  let unread = 1
  vi.mocked(api.get).mockImplementation(async (url: string) => ({ data: url === '/notifications/unread-count' ? { count: unread } : [] }))
  const { container } = render(<NotificationBell />)
  await waitFor(() => expect(container.querySelector('.ant-badge-count')).toHaveTextContent('1'))
  unread = 0
  act(() => { notifyReadStateChanged() })
  await waitFor(() => expect(container.querySelector('.ant-badge-count')).toHaveAttribute('data-show', 'false'))
})

/** 「消息通知」入口对所有已登录角色可见：PM 端走侧栏，worker/intern 走顶栏铃铛「查看全部通知」。 */
describe.each([
  ['pm', '/pm/messages'],
  ['worker', '/worker/messages'],
  ['intern', '/worker/messages'],
])('NotificationBell 通知入口（%s）', (role, target) => {
  it('铃铛可见，且「查看全部通知」进入当前角色的消息通知路由', async () => {
    setUser(role as User['role'])
    render(<NotificationBell />)
    expect(screen.getByLabelText('消息通知')).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('消息通知'))
    fireEvent.click(await screen.findByText('查看全部通知'))
    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith(target))
  })
})


it('failed mark-all does not strand an overlapping refresh spinner', async () => {
  setUser('pm')
  let resolveCount!: (value: any) => void
  let resolveItems!: (value: any) => void
  let calls = 0
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (++calls <= 2) return Promise.resolve({ data: url.includes('unread-count') ? { count: 1 } : [] })
    return new Promise(resolve => { if (url.includes('unread-count')) resolveCount = resolve; else resolveItems = resolve })
  })
  vi.mocked(api.post).mockRejectedValue(new Error('offline'))
  render(<NotificationBell />)
  await waitFor(() => expect(document.querySelector('.ant-badge-count')).toHaveTextContent('1'))
  fireEvent.click(screen.getByLabelText('消息通知'))
  const read = await screen.findByText('全部已读')
  await waitFor(() => expect(api.get).toHaveBeenCalledTimes(4))
  fireEvent.click(read)
  await waitFor(() => expect(api.post).toHaveBeenCalledOnce())
  await act(async () => { resolveCount({ data: { count: 1 } }); resolveItems({ data: [] }) })
  expect(await screen.findByText('暂无通知')).toBeInTheDocument()
  expect(document.querySelector('.ant-spin-spinning')).toBeNull()
})

it.each(['/notifications', '/notifications/unread-count'])('shows a retryable failure when %s cannot load instead of an empty inbox', async (failedUrl) => {
  setUser('pm')
  vi.mocked(api.get).mockImplementation(async (url: string) => {
    if (url === failedUrl) throw new Error('network lost')
    return { data: url.includes('unread-count') ? { count: 0 } : [] }
  })
  render(<NotificationBell />)
  fireEvent.click(screen.getByRole('button', { name: '消息通知' }))
  expect(await screen.findByText('通知暂时无法加载')).toBeInTheDocument()
  expect(screen.queryByText('暂无通知')).not.toBeInTheDocument()
  vi.mocked(api.get).mockImplementation(async (url: string) => ({ data: url.includes('unread-count') ? { count: 0 } : [] }))
  fireEvent.click(screen.getByRole('button', { name: '重新加载通知' }))
  expect(await screen.findByText('暂无通知')).toBeInTheDocument()
  expect(screen.queryByText('通知暂时无法加载')).not.toBeInTheDocument()
})

it('opens by keyboard, exposes actionable notification buttons, and restores focus after Escape', async () => {
  const keyboard = userEvent.setup()
  setUser('pm')
  const notification = { id: 'n1', title: '准备工作有更新', content: '请查看项目', ntype: 'system', project_id: null, is_read: true, created_at: null }
  vi.mocked(api.get).mockImplementation(async (url: string) => ({ data: url.includes('unread-count') ? { count: 0 } : [notification] }))
  render(<NotificationBell />)
  const bell = screen.getByRole('button', { name: '消息通知' })
  bell.focus()
  await keyboard.keyboard('{Enter}')
  const item = await screen.findByRole('button', { name: /准备工作有更新/ })
  await keyboard.tab()
  await keyboard.tab()
  expect(item.closest('.notification-preview-panel')).toContainElement(document.activeElement as HTMLElement)
  expect(bell).toHaveAttribute('aria-expanded', 'true')
  item.focus()
  await keyboard.keyboard('{Escape}')
  await waitFor(() => expect(bell).toHaveAttribute('aria-expanded', 'false'))
  expect(bell).toHaveFocus()
  await keyboard.keyboard(' ')
  await waitFor(() => expect(bell).toHaveAttribute('aria-expanded', 'true'))
})

it('keeps the last inbox visible with a stale-data warning after a refresh failure', async () => {
  setUser('pm')
  vi.mocked(api.get).mockImplementation(async (url: string) => ({ data: url.includes('unread-count') ? { count: 1 } : [
    { id: 'n1', title: '已加载的通知', content: '', ntype: 'system', project_id: null, is_read: false, created_at: null },
  ] }))
  render(<NotificationBell />)
  fireEvent.click(screen.getByRole('button', { name: '消息通知' }))
  expect(await screen.findByRole('button', { name: /已加载的通知/ })).toBeInTheDocument()
  vi.mocked(api.get).mockRejectedValue(new Error('network lost'))
  act(() => { notifyReadStateChanged() })
  expect(await screen.findByText('通知刷新失败，当前显示上次内容')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /已加载的通知/ })).toBeInTheDocument()
  expect(screen.queryByText('暂无通知')).not.toBeInTheDocument()
})

it('does not let an old account mark-read response alter the new account inbox', async () => {
  setUser('pm')
  let finish!: (value: unknown) => void
  vi.mocked(api.post).mockReturnValue(new Promise(resolve => { finish = resolve }))
  vi.mocked(api.get).mockImplementation(async (url: string) => ({ data: url.includes('unread-count') ? { count: 1 } : [
    { id: 'n1', title: '当前账号通知', content: '', ntype: 'system', project_id: null, is_read: false, created_at: null },
  ] }))
  const view = render(<NotificationBell />)
  fireEvent.click(screen.getByRole('button', { name: '消息通知' }))
  fireEvent.click(await screen.findByRole('button', { name: /全部已读/ }))
  await waitFor(() => expect(api.post).toHaveBeenCalledOnce())
  act(() => { useAuth.setState({ user: { ...useAuth.getState().user!, id: 'new-account' } }) })
  view.rerender(<NotificationBell />)
  fireEvent.click(screen.getByRole('button', { name: '消息通知' }))
  expect(await screen.findByRole('button', { name: /当前账号通知/ })).toBeInTheDocument()
  const readsBeforeOldResponse = vi.mocked(api.get).mock.calls.length
  await act(async () => { finish({ data: {} }) })
  expect(document.querySelector('.notification-preview-item')).toHaveClass('is-unread')
  expect(api.get).toHaveBeenCalledTimes(readsBeforeOldResponse)
})
