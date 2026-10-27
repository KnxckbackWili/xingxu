import { beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import AppLayout from './AppLayout'
import { ProjectMenuContent } from '../pages/pm/project/ProjectMenu'

const { logout, auth, queue } = vi.hoisted(() => ({ logout: vi.fn(), auth: { role: 'pm' }, queue: { pending: 0 } }))
vi.mock('../stores/auth', () => ({ useAuth: () => ({ user: { role: auth.role, display_name: '项目测试经理' }, logout }) }))
vi.mock('../stores/theme', () => ({ useThemeStore: (selector: (value: unknown) => unknown) => selector({ mode: 'light', toggle: vi.fn() }) }))
vi.mock('../components/NotificationBell', () => ({ default: () => null }))
vi.mock('../components/UploadQueue', () => ({ default: () => null }))
vi.mock('../offline/queue', () => ({ getQueue: () => Array.from({ length: queue.pending }) }))
vi.mock('../components/ChangePasswordModal', () => ({ default: ({ open }: { open: boolean }) => open ? <div role="dialog">修改密码表单</div> : null }))
function LocationProbe() { return <output data-testid="route">{useLocation().pathname}</output> }
beforeEach(() => { auth.role = 'pm'; queue.pending = 0; logout.mockClear() })

const mainLinks = () => within(screen.getByRole('navigation', { name: '主导航' })).getAllByRole('link').map(link => link.textContent)

it('gives managers and field staff the same shell, with entries following permissions', () => {
  const { unmount } = render(<MemoryRouter initialEntries={['/pm/dashboard']}><AppLayout /></MemoryRouter>)
  // 项目回收站随设置页进入，项目经理也有入口
  expect(mainLinks()).toEqual(['工作台', '项目', '问题', '人员', '消息', '设置'])
  unmount()
  auth.role = 'admin'
  const admin = render(<MemoryRouter initialEntries={['/pm/dashboard']}><AppLayout /></MemoryRouter>)
  expect(mainLinks()).toEqual(['工作台', '项目', '问题', '人员', '消息', '设置'])
  admin.unmount()
  auth.role = 'worker'
  render(<MemoryRouter initialEntries={['/worker/week']}><AppLayout /></MemoryRouter>)
  expect(mainLinks()).toEqual(['工作台', '项目', '问题', '消息', '设置'])
  const workbench = within(screen.getByRole('navigation', { name: '主导航' })).getByRole('link', { name: '工作台' })
  expect(workbench).toHaveAttribute('href', '/worker/week')
  expect(workbench).toHaveAttribute('aria-current', 'page')
})

it('keeps the account click, Escape focus and password workflow', async () => {
  render(<MemoryRouter><AppLayout /></MemoryRouter>)
  const account = screen.getByRole('button', { name: '账户菜单：项目测试经理' }); fireEvent.click(account)
  await screen.findByText('修改密码'); expect(account).toHaveAttribute('aria-expanded', 'true')
  fireEvent.keyDown(window, { key: 'Escape' }); expect(account).toHaveFocus(); expect(account).toHaveAttribute('aria-expanded', 'false')
  fireEvent.click(account); fireEvent.click(await screen.findByText('修改密码'))
  expect(await screen.findByRole('dialog')).toHaveTextContent('修改密码表单'); expect(logout).not.toHaveBeenCalled()
})

it('logs out to the login page, confirming first when offline records are unsynced', async () => {
  render(<MemoryRouter initialEntries={['/pm/dashboard']}><AppLayout /><LocationProbe /></MemoryRouter>)
  fireEvent.click(screen.getByRole('button', { name: '账户菜单：项目测试经理' })); fireEvent.click(await screen.findByText('退出登录'))
  expect(logout).toHaveBeenCalledOnce(); expect(screen.getByTestId('route')).toHaveTextContent('/login')
})

it('phone "我的" sheet offers records, password and logout', async () => {
  auth.role = 'worker'
  render(<MemoryRouter initialEntries={['/worker/week']}><AppLayout /><LocationProbe /></MemoryRouter>)
  fireEvent.click(screen.getByRole('button', { name: '我的：记录、设置与账户' }))
  const sheet = within(await screen.findByRole('dialog', { name: '项目测试经理' }))
  expect(sheet.getByRole('button', { name: /修改密码/ })).toBeInTheDocument()
  fireEvent.click(sheet.getByRole('button', { name: /我的记录/ }))
  expect(screen.getByTestId('route')).toHaveTextContent('/worker/my')
})

it('finds a function by purpose without exposing admin settings to a project manager', async () => {
  render(<MemoryRouter initialEntries={['/pm/projects/project-a/overview']}><AppLayout /><LocationProbe /></MemoryRouter>)
  fireEvent.click(screen.getByRole('button', { name: '查找功能' })); const dialog = within(await screen.findByRole('dialog'))
  expect(dialog.queryByRole('link', { name: '账号' })).toBeNull(); expect(dialog.queryByRole('link', { name: '项目模板' })).toBeNull()
  fireEvent.change(dialog.getByRole('textbox', { name: '查找功能' }), { target: { value: '周' } })
  fireEvent.click(dialog.getByRole('link', { name: '人员' }))
  expect(screen.getByTestId('route')).toHaveTextContent('/pm/people'); await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
})

it('opens find outside projects, respects editing, and restores Escape focus', async () => {
  render(<MemoryRouter><input aria-label="备注" /><AppLayout /></MemoryRouter>)
  const input = screen.getByRole('textbox', { name: '备注' }); input.focus(); fireEvent.keyDown(input, { key: 'k', ctrlKey: true })
  expect(screen.queryByRole('dialog')).toBeNull()
  input.blur(); fireEvent.keyDown(window, { key: 'k', ctrlKey: true }); await screen.findByRole('textbox', { name: '查找功能' })
  fireEvent.keyDown(window, { key: 'Escape' })
  await waitFor(() => expect(screen.getByRole('button', { name: '查找功能' })).toHaveFocus())
})

it('project shortcut takes precedence over shell search without opening two drawers', async () => {
  render(<MemoryRouter initialEntries={['/pm/projects/p1/overview']}><AppLayout /><ProjectMenuContent projectId="p1" activeParent="overview" activeChild={null} onNavigate={() => {}} /></MemoryRouter>)
  fireEvent.keyDown(window, { key: 'k', ctrlKey: true })
  expect(await screen.findByRole('textbox', { name: '查找项目功能' })).toBeInTheDocument()
  expect(screen.queryByRole('textbox', { name: '查找功能' })).toBeNull(); expect(screen.getAllByRole('dialog')).toHaveLength(1)
})
