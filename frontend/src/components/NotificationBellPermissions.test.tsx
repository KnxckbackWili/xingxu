import { act, fireEvent, render, screen } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import NotificationBell from './NotificationBell'
import { api } from '../api/client'
import { NOTIFICATION_READ_EVENT } from '../utils/notificationEvents'
const { actor } = vi.hoisted(() => ({ actor: { user: { id: 'u1', role: 'worker', system_permissions: ['personal.messages.use'] } } }))
vi.mock('../stores/auth', () => ({ useAuth: () => ({ user: actor.user }) }))
vi.mock('../api/client', () => ({ api: { get: vi.fn(), post: vi.fn() } }))
beforeEach(() => {
  actor.user = { id: 'u1', role: 'worker', system_permissions: ['personal.messages.use'] }
  vi.clearAllMocks()
  vi.mocked(api.get).mockImplementation(async path => ({ data: path.includes('unread-count') ? { count: 0 } : [] }))
})
afterEach(() => vi.useRealTimers())
const view = () => <ConfigProvider theme={{ token: { motion: false } }}><MemoryRouter><NotificationBell /></MemoryRouter></ConfigProvider>
it('does not mount the bell, poll or refresh a closed personal message feature', async () => {
  actor.user.system_permissions = []
  vi.useFakeTimers()
  render(view())
  expect(screen.queryByRole('button', { name: '消息通知' })).toBeNull()
  await act(async () => { window.dispatchEvent(new Event(NOTIFICATION_READ_EVENT)); await vi.advanceTimersByTimeAsync(120_000) })
  expect(api.get).not.toHaveBeenCalled()
})
it('stops polling and prevents a late old response from restoring a revoked bell', async () => {
  let resolveCount!: (data: any) => void
  let resolveItems!: (data: any) => void
  vi.mocked(api.get).mockImplementation(path => new Promise(resolve => {
    if (path.includes('unread-count')) resolveCount = resolve
    else resolveItems = resolve
  }))
  const page = render(view())
  expect(screen.getByRole('button', { name: '消息通知' })).toBeInTheDocument()
  actor.user.system_permissions = []
  page.rerender(view())
  await act(async () => { resolveCount({ data: { count: 20 } }); resolveItems({ data: [{ id: 'old', title: 'old account message' }] }) })
  expect(screen.queryByRole('button', { name: '消息通知' })).toBeNull()
  fireEvent(window, new Event(NOTIFICATION_READ_EVENT))
  expect(api.get).toHaveBeenCalledTimes(2)
})
