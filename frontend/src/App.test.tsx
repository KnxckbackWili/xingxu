import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'

vi.mock('./api/client', () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
  tokenStore: { get: () => null, setTokens: vi.fn(), clear: vi.fn() },
  isAuthed: vi.fn(() => true),
  getCsrfToken: () => null,
  authHeaders: () => ({}),
  sessionExpiredTarget: () => null,
  errMsg: () => 'mock-error',
  showErr: vi.fn(),
}))

import { api, isAuthed } from './api/client'
import type { User } from './api'
import { useAuth } from './stores/auth'
import App from './App'

const NOTIFICATIONS = [
  { id: 'n1', title: '问题指派：车辆故障', content: '请尽快处理', ntype: 'issue_assigned', project_id: 'p1', is_read: false, created_at: '2026-08-30T10:00:00' },
]

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(isAuthed).mockReturnValue(true)
  useAuth.setState({ user: { id: 'u-pm', role: 'pm', username: 'pm', display_name: '项目经理', phone: '', email: '', is_active: true }, loading: false, meError: false })
  vi.mocked(api.get).mockImplementation(async (url: string) => {
    if (url === '/notifications') return { data: NOTIFICATIONS }
    if (url === '/notifications/unread-count') return { data: { count: 1 } }
    return { data: {} }
  })
})

function renderApp(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
      <LocationProbe />
    </MemoryRouter>,
  )
}

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="route-location">{location.pathname + location.search + location.hash}</output>
}

it('permits an explicitly granted field account to directly read system backups', async () => {
  useAuth.setState({ user: { id: 'member', role: 'worker', username: 'member', display_name: '成员', phone: '', email: '', is_active: true, system_permissions: ['system.backups.read'] } })
  vi.mocked(api.get).mockImplementation(async (url: string) => ({ data: url === '/system/backups' ? { items: [], restore_pending: false, database: 'postgresql', web_restore_supported: false } : url.includes('unread-count') ? { count: 0 } : [] }))
  renderApp('/pm/backups')
  await waitFor(() => expect(api.get).toHaveBeenCalledWith('/system/backups'), { timeout: 8000 })
  expect(screen.queryByText('403')).toBeNull()
  expect(screen.queryByRole('button', { name: /立即备份/ })).toBeNull()
}, 15000)

it('blocks a revoked module before reading it and reserves permission administration to real admins', async () => {
  useAuth.setState({ user: { id: 'member', role: 'worker', username: 'member', display_name: '成员', phone: '', email: '', is_active: true, system_permissions: ['permission.manage'], permission_overrides: { 'permission.manage': true } } })
  renderApp('/pm/permissions')
  expect(await screen.findByText('403')).toBeVisible()
  expect(api.get).not.toHaveBeenCalledWith('/permissions/catalog')
})

it('opens software updates for a real admin even without delegated module permissions', async () => {
  useAuth.setState({ user: { id: 'admin', role: 'admin', username: 'admin', display_name: '管理员', phone: '', email: '', is_active: true, system_permissions: [] } })
  vi.mocked(api.get).mockImplementation(async (url: string) => ({ data: url === '/system/updates' ? {
    current: { version: '2.3.8', commit: 'current-sha' },
    source: { repository_url: '', ref: 'main', has_token: false, allow_http: false, revision: 0 },
    runner: { online: false, last_seen: null, protocol: 1 }, check: null, job: null,
  } : url.includes('unread-count') ? { count: 0 } : [] }))
  renderApp('/pm/system-updates')
  expect(await screen.findByRole('heading', { name: '软件更新' }, { timeout: 5000 })).toBeInTheDocument()
  await waitFor(() => expect(api.get).toHaveBeenCalledWith('/system/updates'))
  expect(api.post).not.toHaveBeenCalled()
})

it.each([{ role: 'pm', is_active: true }, { role: 'admin', is_active: false }] as const)('blocks update URL access for an unauthorized account: %o', async account => {
  useAuth.setState({ user: { id: 'blocked', ...account, username: 'blocked', display_name: '成员', phone: '', email: '', system_permissions: ['system.updates.manage'], permission_overrides: { 'system.updates.manage': true } } })
  renderApp('/pm/system-updates')
  expect(await screen.findByText('403', {}, { timeout: 5000 })).toBeVisible()
  expect(api.get).not.toHaveBeenCalledWith('/system/updates')
})

it('does not use an administrator role to bypass an empty effective permission list', async () => {
  useAuth.setState({ user: { id: 'admin', role: 'admin', username: 'admin', display_name: '管理员', phone: '', email: '', is_active: true, system_permissions: [] } })
  renderApp('/pm/backups')
  expect(await screen.findByText('403')).toBeVisible()
  expect(api.get).not.toHaveBeenCalledWith('/system/backups')
})

it('preserves an unauthenticated deep link including query and fragment through login', async () => {
  const target = '/pm/messages?qa=original-target&status=unread#main-content'
  vi.mocked(isAuthed).mockReturnValue(false)
  const user: User = { id: 'u-pm', role: 'pm', username: 'pm', display_name: '项目经理', phone: '', email: '', is_active: true }
  useAuth.setState({ user: null, login: async () => {
    vi.mocked(isAuthed).mockReturnValue(true)
    useAuth.setState({ user })
    return user
  } })
  renderApp(target)
  await screen.findByText('登录工作台')
  const loginLocation = screen.getByTestId('route-location').textContent!
  expect(loginLocation.startsWith('/login?')).toBe(true)
  expect(new URLSearchParams(loginLocation.split('?')[1]).get('next')).toBe(target)
  fireEvent.change(screen.getByPlaceholderText('填写账号'), { target: { value: 'pm' } })
  fireEvent.change(screen.getByPlaceholderText('密码'), { target: { value: 'test-password' } })
  fireEvent.click(screen.getByRole('button', { name: /登\s*录/ }))
  await waitFor(() => expect(screen.getByTestId('route-location')).toHaveTextContent(target))
  expect(await screen.findByText('问题指派：车辆故障', {}, { timeout: 5000 })).toBeInTheDocument()
})

it('retains forbidden-route enforcement after returning to an authorized internal next path', async () => {
  vi.mocked(isAuthed).mockReturnValue(false)
  const user: User = { id: 'u-pm', role: 'pm', username: 'pm', display_name: '项目经理', phone: '', email: '', is_active: true }
  useAuth.setState({ user: null, login: async () => {
    vi.mocked(isAuthed).mockReturnValue(true)
    useAuth.setState({ user })
    return user
  } })
  renderApp('/pm/backups?qa=permission#main-content')
  await screen.findByText('登录工作台')
  fireEvent.change(screen.getByPlaceholderText('填写账号'), { target: { value: 'pm' } })
  fireEvent.change(screen.getByPlaceholderText('密码'), { target: { value: 'test-password' } })
  fireEvent.click(screen.getByRole('button', { name: /登\s*录/ }))
  expect(await screen.findByText('403')).toBeInTheDocument()
  expect(api.get).not.toHaveBeenCalledWith('/system/backups')
  expect(screen.getByTestId('route-location')).toHaveTextContent('/pm/backups?qa=permission#main-content')
})

/** 路由渲染 + 导航过滤回归（HYPE-58）：数据与权限入口/路由删除，消息通知入口接现有路由。 */
describe('App 路由', () => {
  it('/pm/messages 正常渲染消息通知页，壳内不出现「数据与权限」', async () => {
    const { container } = renderApp('/pm/messages')
    // lazy chunk 在全量并行跑时加载慢，放宽超时
    expect(await screen.findByText('问题指派：车辆故障', {}, { timeout: 5000 })).toBeInTheDocument()
    expect(container.textContent).not.toContain('数据与权限')
  })

  it('/pm/access 孤立路由已移除（404，不渲染数据与权限页）', async () => {
    renderApp('/pm/access')
    expect(await screen.findByText('页面不存在或已被移动', {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.queryByText('数据与权限')).toBeNull()
  })

  it('桌面常用导航直达消息，页面标题与入口一致', async () => {
    renderApp('/pm/messages')
    const main = await screen.findByRole('navigation', { name: '主导航' }, { timeout: 5000 })
    expect(within(main).getByRole('link', { name: '消息' })).toHaveAttribute('href', '/pm/messages')
    expect(await screen.findByRole('heading', { name: '消息' }, { timeout: 5000 })).toBeVisible()
  })
})

/**
 * HYPE-99：会话 Cookie 标记还在但 /auth/me 返回 403/5xx/网络错误时，受保护路由
 * 必须给出明确的重试/返回登录路径，而不是因为"会话标记仍在"永久停在 Spinner。
 */
describe('认证失败退出永久转圈（meError 兜底）', () => {
  it('meError=true 时渲染「无法验证登录状态」重试/返回登录，而非永久转圈', async () => {
    useAuth.setState({
      user: null,
      loading: false,
      meError: true,
      fetchMe: vi.fn(async () => {}),
      logout: vi.fn(),
    })
    renderApp('/pm/messages')

    // Result 兜底屏出现（而非 Spin）；antd 双汉字按钮名含插入空格（重 试）
    expect(await screen.findByText('无法验证登录状态', {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /重\s*试/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '返回登录' })).toBeInTheDocument()
    // 不再出现角色壳内容（说明没有越过认证层渲染业务页面）
    expect(screen.queryByText('消息通知')).toBeNull()
  })

  it('点击「重试」重新发起 fetchMe；点击「返回登录」走 logout 跳登录页', async () => {
    const fetchMe = vi.fn(async () => {})
    const logout = vi.fn(() => {})
    useAuth.setState({ user: null, loading: false, meError: true, fetchMe, logout })
    renderApp('/pm/messages')

    fireEvent.click(await screen.findByRole('button', { name: /重\s*试/ }, { timeout: 5000 }))
    // App 挂载时已自动 fetchMe 一次，点击「重试」再次发起
    expect(fetchMe).toHaveBeenCalledTimes(2)

    fireEvent.click(screen.getByRole('button', { name: '返回登录' }))
    await waitFor(() => expect(logout).toHaveBeenCalled())
  })
})

it('administrators can open backup management without invoking a backup action', async () => {
  useAuth.setState({ user: { id: 'admin', role: 'admin', username: 'admin', display_name: '管理员', phone: '', email: '', is_active: true }, loading: false, meError: false })
  vi.mocked(api.get).mockImplementation(async (url: string) => ({ data: url === '/system/backups' ? { items: [], restore_pending: false, database: 'sqlite', web_restore_supported: true } : { count: 0 } }))
  renderApp('/pm/backups')
  expect(await screen.findByRole('heading', { name: '备份与恢复' }, { timeout: 5000 })).toBeInTheDocument()
  await waitFor(() => expect(api.get).toHaveBeenCalledWith('/system/backups'), { timeout: 5000 })
  expect(api.post).not.toHaveBeenCalled()
})
it.each(['pm', 'worker', 'intern'] as const)('%s cannot directly open administrator backups', async role => {
  useAuth.setState({ user: { id: 'ordinary', role, username: 'ordinary', display_name: '普通用户', phone: '', email: '', is_active: true }, loading: false, meError: false })
  renderApp('/pm/backups')
  expect(await screen.findByText('403', {}, { timeout: 5000 })).toBeInTheDocument()
  expect(api.get).not.toHaveBeenCalledWith('/system/backups')
})

it.each(['worker', 'intern'] as const)('%s cannot use shared project routes to enter global staffing or inventory', async role => {
  useAuth.setState({ user: { id: 'member', role, username: 'member', display_name: '项目成员', phone: '', email: '', is_active: true }, loading: false, meError: false })
  renderApp('/pm/inventory')
  expect(await screen.findByText('403', {}, { timeout: 5000 })).toBeInTheDocument()
  expect(api.get).not.toHaveBeenCalledWith('/inventory/overview')
})
