import { beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import PmLayout from './PmLayout'
import { ProjectMenuContent } from '../pages/pm/project/ProjectMenu'
const { logout, auth } = vi.hoisted(() => ({ logout: vi.fn(), auth: { role: 'pm' } }))
vi.mock('../stores/auth', () => ({ useAuth: () => ({ user: { role: auth.role, display_name: '项目测试经理' }, logout }) }))
vi.mock('../stores/theme', () => ({ useThemeStore: (selector: (value: unknown) => unknown) => selector({ mode: 'light', toggle: vi.fn() }) }))
vi.mock('../components/NotificationBell', () => ({ default: () => null }))
vi.mock('../components/ChangePasswordModal', () => ({ default: ({ open }: { open: boolean }) => open ? <div role="dialog">修改密码表单</div> : null }))
function LocationProbe() { return <output data-testid="pm-route">{useLocation().pathname}</output> }
beforeEach(() => { auth.role = 'pm'; logout.mockClear() })
it('keeps the account click, Escape focus and password workflow', async () => {
  render(<MemoryRouter><PmLayout /></MemoryRouter>)
  const account = screen.getByRole('button', { name: '账户菜单：项目测试经理' }); fireEvent.click(account)
  await screen.findByText('修改密码'); expect(account).toHaveAttribute('aria-expanded', 'true')
  fireEvent.keyDown(window, { key: 'Escape' }); expect(account).toHaveFocus(); expect(account).toHaveAttribute('aria-expanded', 'false')
  fireEvent.click(account); fireEvent.click(await screen.findByText('修改密码'))
  expect(await screen.findByRole('dialog')).toHaveTextContent('修改密码表单'); expect(logout).not.toHaveBeenCalled()
})
it('preserves logout and login destination', async () => {
  render(<MemoryRouter initialEntries={['/pm/dashboard']}><PmLayout /><LocationProbe /></MemoryRouter>)
  fireEvent.click(screen.getByRole('button', { name: '账户菜单：项目测试经理' })); fireEvent.click(await screen.findByText('退出登录'))
  expect(logout).toHaveBeenCalledOnce(); expect(screen.getByTestId('pm-route')).toHaveTextContent('/login')
})
it.each(['/pm/dashboard', '/pm/stats', '/pm/projects/project-a/tasks'])('uses one top navigation and no duplicate sidebar or local row on %s', path => {
  const { container } = render(<MemoryRouter initialEntries={[path]}><PmLayout /></MemoryRouter>)
  expect(container.querySelector('.pm-sider')).toBeNull(); expect(container.querySelector('.area-pages')).toBeNull()
  const top = within(screen.getByRole('navigation', { name: '常用功能' }))
  expect(top.getAllByRole('link').map(link => link.textContent)).toEqual(['工作台', '项目', '人员', '消息'])
  if (path.includes('/projects/')) expect(top.getByRole('link', { name: '项目' })).toHaveAttribute('aria-current', 'page')
})
it('makes settings discoverable by purpose without exposing retired names or extra admin access', async () => {
  render(<MemoryRouter initialEntries={['/pm/projects/project-a/overview']}><PmLayout /><LocationProbe /></MemoryRouter>)
  fireEvent.click(screen.getByRole('button', { name: '设置' })); const dialog = within(await screen.findByRole('dialog'))
  expect(dialog.queryByRole('link', { name: '待整理文件' })).toBeNull()
  expect(dialog.queryByRole('link', { name: '账号' })).toBeNull(); expect(dialog.queryByRole('link', { name: '项目模板' })).toBeNull()
  fireEvent.change(dialog.getByRole('textbox', { name: '查找全站功能' }), { target: { value: '物品' } })
  fireEvent.click(dialog.getByRole('link', { name: '物品总览' }))
  expect(screen.getByTestId('pm-route')).toHaveTextContent('/pm/inventory'); await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
})
it('filters the common and complete catalog for a field worker', async () => {
  auth.role = 'worker'; render(<MemoryRouter initialEntries={['/pm/projects/p1/overview']}><PmLayout /></MemoryRouter>)
  const top = within(screen.getByRole('navigation', { name: '常用功能' }))
  expect(top.queryByRole('link', { name: '工作台' })).toBeNull(); expect(top.queryByRole('link', { name: '人员' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '设置' })); const dialog = within(await screen.findByRole('dialog'))
  for (const label of ['账号', '统计', '待整理文件', '项目模板']) expect(dialog.queryByRole('link', { name: label })).toBeNull()
  expect(dialog.queryByRole('link', { name: '今天' })).toBeNull()
  expect(dialog.queryByRole('link', { name: '日程' })).toBeNull()
})
it('opens global search outside projects, respects editing, and restores Escape focus', async () => {
  render(<MemoryRouter><input aria-label="备注" /><PmLayout /></MemoryRouter>)
  const input = screen.getByRole('textbox', { name: '备注' }); input.focus(); fireEvent.keyDown(input, { key: 'k', ctrlKey: true })
  expect(screen.queryByRole('dialog')).toBeNull()
  input.blur(); fireEvent.keyDown(window, { key: 'k', ctrlKey: true }); await screen.findByRole('textbox', { name: '查找全站功能' })
  fireEvent.keyDown(window, { key: 'Escape' }); await waitFor(() => expect(screen.getByRole('button', { name: '设置' })).toHaveFocus())
})
it('project shortcut takes precedence over shell search without opening two drawers', async () => {
  render(<MemoryRouter initialEntries={['/pm/projects/p1/overview']}><PmLayout /><ProjectMenuContent projectId="p1" activeParent="overview" activeChild={null} onNavigate={() => {}} /></MemoryRouter>)
  fireEvent.keyDown(window, { key: 'k', ctrlKey: true })
  expect(await screen.findByRole('textbox', { name: '查找项目功能' })).toBeInTheDocument()
  expect(screen.queryByRole('textbox', { name: '查找全站功能' })).toBeNull(); expect(screen.getAllByRole('dialog')).toHaveLength(1)
})
