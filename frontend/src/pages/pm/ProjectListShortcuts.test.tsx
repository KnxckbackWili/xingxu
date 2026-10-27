import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ProjectListPage from './ProjectListPage'
import { projectApi, type Project, type User } from '../../api'
import { api } from '../../api/client'

const { auth, navigate, params, setParams } = vi.hoisted(() => {
  const auth: { user: User | null } = { user: null }
  return { auth, navigate: vi.fn(), params: new URLSearchParams(), setParams: vi.fn() }
})
vi.mock('../../stores/auth', () => ({ useAuth: () => auth }))
vi.mock('react-router-dom', () => ({ useNavigate: () => navigate, useSearchParams: () => [params, setParams] }))
vi.mock('../../api', () => ({ projectApi: { list: vi.fn(), create: vi.fn(), get: vi.fn() } }))
vi.mock('../../api/client', () => ({ api: { get: vi.fn(), post: vi.fn() }, errMsg: () => '加载失败' }))
vi.mock('../../hooks/useVehicleTypes', () => ({
  useVehicleTypes: () => ({ options: [], loading: false, error: null }), toVehicleTypeSelectOptions: () => [],
}))

let accountSequence = 0
const account = (id: string): User => ({
  id, role: 'pm', username: id, display_name: '隔离测试经理', phone: '', email: '', is_active: true,
})
const project = (id: string, name: string): Project => ({
  id, name, abbreviation: '', manager: 'manager', client: 'QA客户', location: 'QA地点',
  start_date: '2026-10-01', end_date: '2026-12-31', status: 'preparing', description: '',
  members: [], capabilities: [], can_delete: false, created_at: '2026-10-01T00:00:00Z',
})
function seedShortcuts(id: string, favorites: string[], recent: Array<{ id: string; section: string }> = []) {
  localStorage.setItem(`agvpm.project-shortcuts.v1:${id}`, JSON.stringify({ favorites, recent }))
}
const setup = () => render(<ConfigProvider theme={{ token: { motion: false } }}><ProjectListPage /></ConfigProvider>)
const table = () => within(screen.getByRole('table'))
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  localStorage.setItem('agvpm_proj_view', 'table')
  auth.user = account(`shortcut-page-${++accountSequence}`)
  vi.mocked(projectApi.list).mockReset().mockResolvedValue([])
  vi.mocked(api.get).mockReset().mockResolvedValue({ data: { projects: [] } })
})

describe('account-scoped project shortcuts in the real project list', () => {
  it.each([
    ['card', '查看工作项', 'plan'], ['card', '查看周计划', 'plan?view=weeks'],
    ['table', '查看工作项', 'plan'], ['table', '查看周计划', 'plan?view=weeks'],
  ])('opens the %s project %s directly without the parent row opening overview', async (view, label, section) => {
    localStorage.setItem('agvpm_proj_view', view)
    vi.mocked(projectApi.list).mockResolvedValue([project('alpha', 'Alpha项目')])
    setup()
    fireEvent.click(await screen.findByRole('button', { name: `${label}：Alpha项目` }))
    expect(navigate).toHaveBeenCalledTimes(1)
    expect(navigate).toHaveBeenCalledWith(`/pm/projects/alpha/${section}`)
    expect(projectApi.create).not.toHaveBeenCalled()
  })

  it('favorites a project without navigating and filters to favorites using the live list', async () => {
    vi.mocked(projectApi.list).mockResolvedValue([project('alpha', 'Alpha项目'), project('beta', 'Beta项目')])
    setup()
    const favorite = await screen.findByRole('button', { name: '收藏项目：Alpha项目' })
    fireEvent.click(favorite)
    expect(navigate).not.toHaveBeenCalled()
    expect(await screen.findByRole('button', { name: '取消收藏：Alpha项目' })).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(screen.getByRole('button', { name: /我的收藏/ }))
    expect(table().getByText('Alpha项目')).toBeVisible()
    expect(table().queryByText('Beta项目')).not.toBeInTheDocument()
    expect(JSON.parse(localStorage.getItem(`agvpm.project-shortcuts.v1:${auth.user!.id}`)!)).toEqual({ favorites: ['alpha'], recent: [] })
  })

  it('clears recent visits without clearing favorites and navigates to a safe remembered page', async () => {
    seedShortcuts(auth.user!.id, ['alpha'], [{ id: 'alpha', section: 'documents' }])
    vi.mocked(projectApi.list).mockResolvedValue([project('alpha', 'Alpha项目')])
    setup()
    const recent = await screen.findByRole('region', { name: '最近浏览的项目' })
    fireEvent.click(within(recent).getByRole('button', { name: /Alpha项目.*继续查看资料/ }))
    expect(navigate).toHaveBeenCalledWith('/pm/projects/alpha/documents')
    fireEvent.click(within(recent).getByRole('button', { name: '清空记录' }))
    expect(screen.queryByRole('region', { name: '最近浏览的项目' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '取消收藏：Alpha项目' })).toHaveAttribute('aria-pressed', 'true')
    expect(JSON.parse(localStorage.getItem(`agvpm.project-shortcuts.v1:${auth.user!.id}`)!)).toEqual({ favorites: ['alpha'], recent: [] })
  })

  it('keeps keyword, status and favorites filters when refreshing the server list', async () => {
    seedShortcuts(auth.user!.id, ['alpha'])
    vi.mocked(projectApi.list).mockResolvedValue([project('alpha', 'Alpha项目'), project('beta', 'Beta项目')])
    setup()
    await screen.findByRole('button', { name: '取消收藏：Alpha项目' })
    const keyword = screen.getByPlaceholderText('搜索项目、客户或地点')
    fireEvent.change(keyword, { target: { value: 'Alpha' } })
    fireEvent.click(screen.getByRole('button', { name: /我的收藏/ }))
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '按状态筛选' }))
    fireEvent.click(await screen.findByText('筹备', { selector: '.ant-select-item-option-content' }))
    fireEvent.click(screen.getByRole('button', { name: '刷新项目列表' }))
    await waitFor(() => expect(projectApi.list).toHaveBeenCalledTimes(2))
    await screen.findByRole('button', { name: '取消收藏：Alpha项目' })
    expect(keyword).toHaveValue('Alpha')
    expect(screen.getByRole('button', { name: /我的收藏/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('combobox', { name: '按状态筛选' }).closest('.ant-select')).toHaveTextContent('筹备')
    expect(table().queryByText('Beta项目')).not.toBeInTheDocument()
  })

  it('excludes an unavailable project from recent visits and favorites without exposing stored IDs', async () => {
    seedShortcuts(auth.user!.id, ['revoked', 'alpha'], [
      { id: 'revoked', section: 'edit' }, { id: 'alpha', section: 'overview' },
    ])
    vi.mocked(projectApi.list).mockResolvedValue([project('alpha', 'Alpha项目')])
    setup()
    const recent = await screen.findByRole('region', { name: '最近浏览的项目' })
    expect(within(recent).getAllByRole('button')).toHaveLength(2) // Clear + the one currently visible project.
    expect(recent).toHaveTextContent('Alpha项目')
    expect(recent).not.toHaveTextContent('revoked')
    expect(recent).not.toHaveTextContent('项目设置')
    fireEvent.click(screen.getByRole('button', { name: /我的收藏/ }))
    expect(table().getByText('Alpha项目')).toBeVisible()
    expect(table().queryByText('revoked')).not.toBeInTheDocument()
  })

  it('falls back to overview for an old activity shortcut when audit reading is explicitly denied', async () => {
    auth.user = { ...auth.user!, permission_overrides: { 'system.audit.read': false }, permission_version: 1 }
    seedShortcuts(auth.user.id, ['alpha'], [{ id: 'alpha', section: 'activity' }])
    vi.mocked(projectApi.list).mockResolvedValue([project('alpha', 'Alpha项目')])
    setup()
    const recent = await screen.findByRole('region', { name: '最近浏览的项目' })
    expect(recent).toHaveTextContent('继续查看概况')
    expect(recent).not.toHaveTextContent('操作记录')
    fireEvent.click(within(recent).getByRole('button', { name: /Alpha项目.*继续查看概况/ }))
    expect(navigate).toHaveBeenCalledWith('/pm/projects/alpha/overview')
    expect(screen.getByRole('button', { name: '取消收藏：Alpha项目' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('does not let the previous account pending list overwrite the current account or its favorites', async () => {
    const first = auth.user!.id, second = `${first}-other`
    seedShortcuts(first, ['alpha'], [{ id: 'alpha', section: 'schedule' }])
    seedShortcuts(second, ['beta'], [{ id: 'beta', section: 'overview' }])
    const old = deferred<Project[]>()
    vi.mocked(projectApi.list).mockReturnValueOnce(old.promise).mockResolvedValueOnce([project('beta', 'Beta项目')])
    const view = setup()
    await waitFor(() => expect(projectApi.list).toHaveBeenCalledTimes(1))
    auth.user = account(second)
    view.rerender(<ConfigProvider theme={{ token: { motion: false } }}><ProjectListPage /></ConfigProvider>)
    expect(await screen.findByRole('button', { name: '取消收藏：Beta项目' })).toBeVisible()
    await act(async () => { old.resolve([project('alpha', 'Alpha项目')]); await old.promise })
    expect(screen.queryByRole('button', { name: '取消收藏：Alpha项目' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '取消收藏：Beta项目' })).toBeVisible()
    const recent = screen.getByRole('region', { name: '最近浏览的项目' })
    expect(recent).toHaveTextContent('Beta项目')
    expect(recent).not.toHaveTextContent('Alpha项目')
    expect(navigate).not.toHaveBeenCalled()
  })

  it('does not restore a removed project when an older permission-scope request completes late', async () => {
    seedShortcuts(auth.user!.id, [], [{ id: 'revoked', section: 'schedule' }])
    const old = deferred<Project[]>()
    vi.mocked(projectApi.list).mockReturnValueOnce(old.promise).mockResolvedValueOnce([project('alpha', 'Alpha项目')])
    const view = setup()
    await waitFor(() => expect(projectApi.list).toHaveBeenCalledTimes(1))
    auth.user = { ...auth.user!, permission_version: 1, permission_overrides: { 'projects.view_all': false } }
    view.rerender(<ConfigProvider theme={{ token: { motion: false } }}><ProjectListPage /></ConfigProvider>)
    expect(await screen.findByRole('button', { name: '收藏项目：Alpha项目' })).toBeVisible()
    await act(async () => { old.resolve([project('revoked', '已经失权的项目')]); await old.promise })
    expect(screen.queryByText('已经失权的项目')).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: '最近浏览的项目' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '收藏项目：Alpha项目' })).toBeVisible()
  })
})
