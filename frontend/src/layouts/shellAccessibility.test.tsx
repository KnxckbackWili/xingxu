import { beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import PmLayout from './PmLayout'
import WorkerLayout from './WorkerLayout'

vi.mock('../components/NotificationBell', () => ({ default: () => <button>通知</button> }))
vi.mock('../components/ChangePasswordModal', () => ({ default: () => null }))
vi.mock('../stores/auth', () => ({ useAuth: () => ({ user: { role: 'admin', display_name: '测试用户' }, logout: vi.fn() }) }))
beforeEach(() => vi.clearAllMocks())

it('PM shell names the brand, current common link, account and discoverable menu, restoring focus on close', async () => {
  render(<ConfigProvider theme={{ token: { motion: false } }}><MemoryRouter initialEntries={['/pm/projects']}><PmLayout /></MemoryRouter></ConfigProvider>)
  expect(screen.getByRole('button', { name: '账户菜单：测试用户' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '行序，返回工作台' })).toBeInTheDocument()
  const common = screen.getByRole('navigation', { name: '常用功能' })
  expect(within(common).getByRole('link', { name: '项目' })).toHaveAttribute('aria-current', 'page')
  expect(within(common).getAllByRole('link')).toHaveLength(4)
  const trigger = screen.getByRole('button', { name: '设置' })
  fireEvent.click(trigger)
  const drawer = await screen.findByRole('dialog', { name: '设置' })
  expect(within(drawer).getByRole('textbox', { name: '查找设置' })).toBeInTheDocument()
  fireEvent.click(within(drawer).getByRole('button', { name: /close|关闭/i }))
  await waitFor(() => expect(screen.queryByRole('dialog', { name: '设置' })).not.toBeInTheDocument())
  await waitFor(() => expect(trigger).toHaveFocus())
})

it('worker account remains named when responsive styles hide the username', () => {
  render(<MemoryRouter initialEntries={['/worker/week']}><WorkerLayout /></MemoryRouter>)
  expect(screen.getByRole('button', { name: '账户菜单：测试用户' })).toBeInTheDocument()
})

it.each(['/worker/messages', '/worker/feedback'])('does not mark Week as current on %s', (path) => {
  render(<MemoryRouter initialEntries={[path]}><WorkerLayout /></MemoryRouter>)
  const nav = screen.getByRole('navigation', { name: '现场工作导航' })
  expect(nav.querySelector('[aria-current="page"]')).toBeNull()
})

it('keeps Projects current when viewing a project detail', () => {
  render(<MemoryRouter initialEntries={['/worker/projects/qa-project']}><WorkerLayout /></MemoryRouter>)
  const nav = screen.getByRole('navigation', { name: '现场工作导航' })
  expect(within(nav).getByRole('button', { name: /项目/ })).toHaveAttribute('aria-current', 'page')
})
