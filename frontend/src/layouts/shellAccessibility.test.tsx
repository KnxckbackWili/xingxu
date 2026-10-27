import { beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import AppLayout from './AppLayout'

vi.mock('../components/NotificationBell', () => ({ default: () => <button>通知</button> }))
vi.mock('../components/UploadQueue', () => ({ default: () => null }))
vi.mock('../components/ChangePasswordModal', () => ({ default: () => null }))
vi.mock('../stores/auth', () => ({ useAuth: () => ({ user: { role: 'admin', display_name: '测试用户' }, logout: vi.fn() }) }))
beforeEach(() => vi.clearAllMocks())

it('names the brand, current main link, account and the find-a-function drawer, restoring focus on close', async () => {
  render(<ConfigProvider theme={{ token: { motion: false } }}><MemoryRouter initialEntries={['/pm/projects']}><AppLayout /></MemoryRouter></ConfigProvider>)
  expect(screen.getByRole('button', { name: '账户菜单：测试用户' })).toBeInTheDocument()
  expect(screen.getAllByRole('button', { name: '行序，返回工作台' }).length).toBeGreaterThan(0)
  const main = screen.getByRole('navigation', { name: '主导航' })
  expect(within(main).getByRole('link', { name: '项目' })).toHaveAttribute('aria-current', 'page')
  const trigger = screen.getByRole('button', { name: '查找功能' })
  fireEvent.click(trigger)
  const drawer = await screen.findByRole('dialog', { name: '查找功能' })
  expect(within(drawer).getByRole('textbox', { name: '查找功能' })).toBeInTheDocument()
  fireEvent.click(within(drawer).getByRole('button', { name: /close|关闭/i }))
  await waitFor(() => expect(screen.queryByRole('dialog', { name: '查找功能' })).not.toBeInTheDocument())
  await waitFor(() => expect(trigger).toHaveFocus())
})

it.each(['/worker/feedback', '/pm/feedback'])('marks no main destination as current on %s', (path) => {
  render(<MemoryRouter initialEntries={[path]}><AppLayout /></MemoryRouter>)
  expect(screen.getByRole('navigation', { name: '主导航' }).querySelector('[aria-current="page"]')).toBeNull()
})

it('keeps Projects current on a project detail page and on the old field project URL prefix', () => {
  const { unmount } = render(<MemoryRouter initialEntries={['/pm/projects/qa-project/overview']}><AppLayout /></MemoryRouter>)
  expect(within(screen.getByRole('navigation', { name: '主导航' })).getByRole('link', { name: '项目' })).toHaveAttribute('aria-current', 'page')
  unmount()
  render(<MemoryRouter initialEntries={['/worker/projects/qa-project']}><AppLayout /></MemoryRouter>)
  expect(within(screen.getByRole('navigation', { name: '主导航（手机）' })).getByRole('link', { name: '项目' })).toHaveAttribute('aria-current', 'page')
})
