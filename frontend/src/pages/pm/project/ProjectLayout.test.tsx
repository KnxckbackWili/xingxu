import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import ProjectLayout from './ProjectLayout'

const { useAuthMock, navigateMock, route } = vi.hoisted(() => ({ useAuthMock: vi.fn(), navigateMock: vi.fn(), route: { pathname: '/pm/projects/p1/overview', projectId: 'p1' } }))
vi.mock('../../../stores/auth', () => ({
  useAuth: useAuthMock,
}))

vi.mock('react-router-dom', () => ({
  useParams: () => ({ projectId: route.projectId }),
  useNavigate: () => navigateMock,
  useLocation: () => route,
}))

vi.mock('../../../hooks/useMediaQuery', () => ({
  useMediaQuery: () => false,
}))

const apiGet = vi.fn()
vi.mock('../../../api/client', () => ({
  api: {
    get: (...args: unknown[]) => apiGet(...args),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
  errMsg: () => 'mock-error',
  tokenStore: { access: 'test-token' },
}))

// 内页懒加载 chunk 用占位组件：本测试只关心项目壳头部请求集，不渲染真实总览页
vi.mock('./OverviewPage', () => ({
  default: ({ onStatusChange, canManageStatus, canArchive }: { onStatusChange: () => Promise<void>; canManageStatus?: boolean; canArchive?: boolean }) => <div data-testid="mock-overview" data-manage-status={String(canManageStatus)} data-can-archive={String(canArchive)}>概览占位<input aria-label="测试本页未保存输入" /><button onClick={() => void onStatusChange()}>刷新项目壳</button></div>,
}))

const PROJECT = {
  id: 'p1',
  name: '性能验收项目',
  abbreviation: 'PERF',
  manager: 'u-pm',
  manager_name: '张经理',
  client: '客户A',
  location: '苏州',
  start_date: '2026-08-10',
  end_date: '2026-10-31',
  status: 'preparing' as const,
  description: '',
  members: ['u-pm'],
  schedule_version: 2,
  schedule_summary: { total: 5, confirmed: 3 },
  vehicle_total: 4,
  created_at: '2026-08-01T00:00:00Z',
}

/**
 * HYPE-58 性能验收（一审 REJECT 项2 的可复现证据）：
 * 项目壳进入详情只拉「项目详情（含 schedule_summary）+ 进度聚合」两条请求，
 * 头部「已下达数量」来自轻量 summary，绝不再拉完整 /schedule 列表；
 * 卸载（切 Tab/切项目）时对在途请求执行 abort。
 */
describe('ProjectLayout 项目壳请求集（HYPE-58）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    route.projectId = 'p1'
    route.pathname = '/pm/projects/p1/overview'
    useAuthMock.mockReturnValue({ user: { role: 'pm' } })
    apiGet.mockImplementation(async (url: string) => {
      if (url === '/projects/p1/progress') return { data: { phases: [] } }
      if (url === '/projects/p1') return { data: PROJECT }
      return { data: {} }
    })
  })

  it('项目头部只请求详情，排程摘要按需查看', async () => {
    const { unmount } = render(<ProjectLayout />)
    await screen.findByTestId('mock-overview')

    expect(screen.queryByRole('button', { name: '查看计划与发布情况' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '项目信息' }))
    expect(await screen.findByRole('button', { name: '查看计划与发布情况' })).toBeInTheDocument()
    expect(apiGet.mock.calls.map((call) => call[0])).toEqual(['/projects/p1'])
    unmount()
  })

  it('卸载（切 Tab/切项目）时中止在途请求', async () => {
    let capturedSignal: AbortSignal | undefined
    apiGet.mockImplementation((url: string, options?: { signal?: AbortSignal }) => {
      if (url === '/projects/p1') capturedSignal = options?.signal
      if (url === '/projects/p1') return Promise.resolve({ data: PROJECT })
      if (url === '/projects/p1/progress') return Promise.resolve({ data: { phases: [] } })
      return Promise.resolve({ data: {} })
    })

    const { unmount } = render(<ProjectLayout />)
    await screen.findByTestId('mock-overview')
    expect(capturedSignal?.aborted).toBe(false)

    unmount() // 模拟切 Tab / 切项目：卸载清理应 abort 在途请求
    await waitFor(() => expect(capturedSignal?.aborted).toBe(true))
  })
})

vi.mock('./EditPage', () => ({ default: () => <div>编辑项目占位</div> }))
vi.mock('./ExportPage', () => ({ default: () => <div>导出项目占位</div> }))

describe('project direct URL capability boundary', () => {
  beforeEach(() => { vi.clearAllMocks(); route.projectId = 'p1'; useAuthMock.mockReturnValue({ user: { role: 'intern', id: 'member' } }) })
  it.each(['export'])('blocks unauthorized direct %s URLs even for a visible project', async tab => {
    route.pathname = `/pm/projects/p1/${tab}`
    apiGet.mockResolvedValue({ data: { ...PROJECT, capabilities: [] } })
    render(<ProjectLayout />)
    expect(await screen.findByText('403')).toBeInTheDocument()
    expect(screen.queryByText('编辑项目占位')).toBeNull()
    expect(screen.queryByText('导出项目占位')).toBeNull()
  })
  it.each([['edit', 'project.update', '编辑项目占位'], ['export', 'project.export', '导出项目占位']])('allows authorized intern direct %s route', async (tab, capability, title) => {
    route.pathname = `/pm/projects/p1/${tab}`
    apiGet.mockResolvedValue({ data: { ...PROJECT, capabilities: [capability] } })
    render(<ProjectLayout />)
    expect(await screen.findByText(title)).toBeInTheDocument()
  })
  it.each([['worker', ['project.manage_members']], ['readonly', ['project.export']]])('opens readable settings for %s without core-write authority', async (role, capabilities) => {
    route.pathname = '/pm/projects/p1/edit'
    useAuthMock.mockReturnValue({ user: { role, id: 'member' } })
    apiGet.mockResolvedValue({ data: { ...PROJECT, capabilities } })
    render(<ProjectLayout />)
    expect(await screen.findByText('编辑项目占位')).toBeInTheDocument()
    expect(screen.queryByText('403')).toBeNull()
  })
  it('keeps network failures retryable without rendering a project', async () => {
    route.pathname = '/pm/projects/p1/overview'
    apiGet.mockRejectedValue(new Error('not found'))
    render(<ProjectLayout />)
    expect(await screen.findByText('项目加载失败')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重新加载' })).toBeInTheDocument()
    expect(screen.queryByTestId('mock-overview')).toBeNull()
  })
  it('retains a public system-denial reason on a forbidden project without showing project data', async () => {
    route.pathname = '/pm/projects/p1/overview'
    apiGet.mockRejectedValue({ response: { status: 403, data: { detail: '系统禁止：查看项目（project.read）' } } })
    render(<ProjectLayout />)
    expect(await screen.findByText('没有权限查看项目', { selector: '.ant-result-title' })).toBeInTheDocument()
    expect(screen.getByText('系统禁止：查看项目（project.read）', { selector: '.ant-result-subtitle' })).toBeVisible()
    expect(screen.queryByTestId('mock-overview')).toBeNull()
  })
  it.each([404])('shows an unavailable project state for HTTP %s and returns to the list', async status => {
    route.pathname = '/pm/projects/p1/overview'
    apiGet.mockRejectedValue({ response: { status, data: { detail: '项目已删除' } } })
    render(<ProjectLayout />)
    expect(await screen.findByText('项目不存在或无权访问', { selector: '.ant-result-title' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '重新加载' })).not.toBeInTheDocument()
    expect(screen.queryByTestId('mock-overview')).not.toBeInTheDocument()
    expect(screen.queryByText('项目已删除')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '返回项目列表' }))
    expect(navigateMock).toHaveBeenCalledWith('/pm/projects') // 两端已合并，现场人员同样回到项目列表
  })
  it('retries a server failure and restores the project once the request succeeds', async () => {
    route.pathname = '/pm/projects/p1/overview'
    apiGet.mockRejectedValueOnce({ response: { status: 500 } }).mockResolvedValueOnce({ data: PROJECT })
    render(<ProjectLayout />)
    await screen.findByText('项目加载失败')
    fireEvent.click(screen.getByRole('button', { name: '重新加载' }))
    expect(await screen.findByTestId('mock-overview')).toBeInTheDocument()
    expect(screen.queryByText('项目加载失败')).not.toBeInTheDocument()
    expect(apiGet).toHaveBeenCalledTimes(2)
  })
  it('does not let a stale unavailable response replace a newly loaded view', async () => {
    route.pathname = '/pm/projects/p1/overview'
    let rejectOld: (error: unknown) => void = () => {}
    let oldSignal: AbortSignal | undefined
    apiGet.mockImplementationOnce((_url: string, options: { signal?: AbortSignal }) => {
      oldSignal = options.signal
      return new Promise((_resolve, reject) => { rejectOld = reject })
    }).mockResolvedValueOnce({ data: PROJECT })
    const { rerender } = render(<ProjectLayout />)
    route.pathname = '/pm/projects/p1/export'
    useAuthMock.mockReturnValue({ user: { role: 'admin', id: 'admin' } })
    rerender(<ProjectLayout />)
    expect(await screen.findByText('导出项目占位')).toBeInTheDocument()
    expect(oldSignal?.aborted).toBe(true)
    rejectOld({ response: { status: 404 } })
    await waitFor(() => expect(apiGet).toHaveBeenCalledTimes(2))
    expect(screen.getByText('导出项目占位')).toBeInTheDocument()
    expect(screen.queryByText('项目不存在或无权访问', { selector: '.ant-result-title' })).not.toBeInTheDocument()
  })
  it.each(['overview', 'export'])('keeps unknown history readable at %s without disguising its state', async tab => {
    route.pathname = `/pm/projects/p1/${tab}`
    useAuthMock.mockReturnValue({ user: { role: 'admin', id: 'admin' } })
    apiGet.mockResolvedValue({ data: { ...PROJECT, status: 'legacy_unknown', capabilities: ['project.update', 'project.export'] } })
    render(<ProjectLayout />)
    expect(await screen.findByText('项目存在未知历史状态，当前只读')).toBeInTheDocument()
    expect(screen.getByText('未知历史状态（legacy_unknown）')).toBeInTheDocument()
    expect(screen.getByText(/原始状态：legacy_unknown/)).toBeInTheDocument()
    expect(screen.queryByText('草稿')).not.toBeInTheDocument()
    expect(await screen.findByText(tab === 'export' ? '导出项目占位' : '概览占位')).toBeInTheDocument()
  })
})

vi.mock('./StartupPage', () => ({ default: () => <div>开工占位</div> }))
vi.mock('./TaskPlanPage', () => ({ default: () => <div>任务占位</div> }))
vi.mock('./SchedulePage', () => ({ default: () => <div>日程占位</div> }))
vi.mock('./SiteInformationPage', () => ({ default: ({ sub }: { sub: string }) => <div>现场占位 {sub}</div> }))
vi.mock('./DocumentsPage', () => ({ default: () => <div>资料占位</div> }))
vi.mock('./ActivityPage', () => ({ default: ({ sub }: { sub: string }) => <div>动态占位 {sub}</div> }))
vi.mock('./TeamPage', () => ({ default: () => <div>团队占位</div> }))

describe('persistent project directory during route refresh', () => {
  beforeEach(() => {
    vi.clearAllMocks();route.projectId='p1';route.pathname='/pm/projects/p1/overview'
    useAuthMock.mockReturnValue({user:{role:'admin',id:'admin'}})
  })
  it('retains header and directory while a same-project page refresh is pending, then updates metadata', async () => {
    let resolveRefresh: (value: unknown) => void=()=>{}
    apiGet.mockResolvedValueOnce({data:PROJECT}).mockImplementationOnce(()=>new Promise(resolve=>{resolveRefresh=resolve}))
    const {rerender}=render(<ProjectLayout />)
    await screen.findByTestId('mock-overview')
    const directory=screen.getByRole('navigation',{name:'项目常用功能'})
    expect(screen.queryByText('项目成员可查看完整项目；编辑、人员安排等操作按本项目授权开放。')).toBeNull()
    route.pathname='/pm/projects/p1/export';rerender(<ProjectLayout />)
    expect(await screen.findByText('导出项目占位')).toBeVisible()
    expect(screen.getByRole('navigation',{name:'项目常用功能'})).toBe(directory)
    expect(screen.getByText(PROJECT.name)).toBeVisible()
    expect(screen.queryByText('正在加载项目...')).toBeNull()
    resolveRefresh({data:{...PROJECT,name:'已更新项目名称',status:'ready'}})
    await screen.findByText('已更新项目名称')
    expect(screen.getByRole('navigation',{name:'项目常用功能'})).toBe(directory)
    expect(screen.getByText('待进场', { selector: '.ant-tag' })).toBeVisible()
    expect(screen.getByRole('list', { name: '项目阶段：待进场' })).toBeVisible()
  })
  it('never displays cached project data after changing project and ignores the aborted prior-page response', async () => {
    let oldSignal: AbortSignal|undefined
    let rejectOld:(reason:unknown)=>void=()=>{}
    let resolveNew:(value:unknown)=>void=()=>{}
    apiGet.mockResolvedValueOnce({data:PROJECT})
      .mockImplementationOnce((_url,options:{signal:AbortSignal})=>{oldSignal=options.signal;return new Promise((_resolve,reject)=>{rejectOld=reject})})
      .mockImplementationOnce(()=>new Promise(resolve=>{resolveNew=resolve}))
    const {rerender}=render(<ProjectLayout />)
    await screen.findByTestId('mock-overview')
    route.pathname='/pm/projects/p1/export';rerender(<ProjectLayout />)
    await screen.findByText('导出项目占位')
    route.projectId='p2';route.pathname='/pm/projects/p2/overview';rerender(<ProjectLayout />)
    expect(screen.getByText('正在加载项目...')).toBeVisible()
    expect(screen.queryByText(PROJECT.name)).toBeNull()
    expect(oldSignal?.aborted).toBe(true)
    rejectOld({response:{status:404}})
    resolveNew({data:{...PROJECT,id:'p2',name:'第二个项目'}})
    await screen.findByText('第二个项目')
    expect(screen.queryByText(PROJECT.name)).toBeNull()
    expect(screen.queryByText('项目不存在或无权访问',{selector:'.ant-result-title'})).toBeNull()
  })
  it.each([
    ['tasks','计划','任务占位'], ['history','操作记录','动态占位 history'], ['activity','操作记录','动态占位 history'],
    ['site','车辆','现场占位 vehicles'], ['delivery','资料','资料占位'], ['files','资料','资料占位'], ['documents','资料','资料占位'],
  ])('keeps legacy %s route reachable and highlighted', async (path,label,content) => {
    route.pathname=`/pm/projects/p1/${path}`;apiGet.mockResolvedValue({data:PROJECT})
    render(<ProjectLayout />)
    await screen.findByText(content)
    if (path === 'history' || path === 'activity') {
      fireEvent.click(screen.getByRole('button', { name: /更多/ })); await screen.findByRole('dialog')
    }
    expect(screen.getByRole('button',{name:label})).toHaveAttribute('aria-current','page')
  })
})

it('resets window scroll only after committed pathname changes while preserving the navigation', async () => {
  vi.clearAllMocks();route.projectId='p1';route.pathname='/pm/projects/p1/overview'
  useAuthMock.mockReturnValue({user:{role:'admin'}});apiGet.mockResolvedValue({data:PROJECT})
  const scroll=vi.spyOn(window,'scrollTo')
  const {rerender}=render(<ProjectLayout />);await screen.findByTestId('mock-overview')
  const directory=screen.getByRole('navigation',{name:'项目常用功能'})
  scroll.mockClear()
  rerender(<ProjectLayout />)
  expect(scroll).not.toHaveBeenCalled()
  route.pathname='/pm/projects/p1/export';rerender(<ProjectLayout />)
  await screen.findByText('导出项目占位')
  expect(scroll).toHaveBeenCalledExactlyOnceWith({top:0,left:0})
  expect(screen.getByRole('navigation',{name:'项目常用功能'})).toBe(directory)
  expect(directory.closest('aside')).toBeNull()
  scroll.mockRestore()
})

it('refreshes header after a phase action without removing the current page or directory', async () => {
  vi.clearAllMocks();route.projectId='p1';route.pathname='/pm/projects/p1/overview'
  useAuthMock.mockReturnValue({user:{role:'admin'}})
  let resolveRefresh:(value:unknown)=>void=()=>{}
  apiGet.mockResolvedValueOnce({data:PROJECT}).mockImplementationOnce(()=>new Promise(resolve=>{resolveRefresh=resolve}))
  render(<ProjectLayout />);const page=await screen.findByTestId('mock-overview')
  const directory=screen.getByRole('navigation',{name:'项目常用功能'})
  fireEvent.click(screen.getByRole('button',{name:'刷新项目壳'}))
  expect(screen.getByTestId('mock-overview')).toBe(page)
  expect(screen.getByRole('navigation',{name:'项目常用功能'})).toBe(directory)
  expect(screen.queryByText('正在加载项目...')).toBeNull()
  resolveRefresh({data:{...PROJECT,status:'ready'}})
  await screen.findByText('待进场')
  expect(screen.getByTestId('mock-overview')).toBe(page)
  expect(apiGet).toHaveBeenCalledTimes(2)
})

it('refreshes project capabilities after permission changes without resetting the current page input or directory', async () => {
  route.projectId = 'p1'; route.pathname = '/pm/projects/p1/overview'
  useAuthMock.mockReturnValue({ user: { id: 'pm', role: 'pm', permission_version: 0 } })
  let resolveRefresh!: (value: any) => void
  apiGet.mockResolvedValueOnce({ data: { ...PROJECT, capabilities: ['project.manage_plan'] } }).mockImplementationOnce(() => new Promise(resolve => { resolveRefresh = resolve }))
  const page = render(<ProjectLayout />)
  const input = await screen.findByRole('textbox', { name: '测试本页未保存输入' })
  const directory = screen.getByRole('navigation', { name: '项目常用功能' })
  fireEvent.change(input, { target: { value: '保留本页草稿' } })
  useAuthMock.mockReturnValue({ user: { id: 'pm', role: 'pm', permission_version: 1, permission_overrides: { 'project.manage_plan': false } } })
  page.rerender(<ProjectLayout />)
  expect(input).toHaveValue('保留本页草稿')
  expect(screen.queryByText('正在加载项目...')).toBeNull()
  expect(screen.getByRole('navigation', { name: '项目常用功能' })).toBe(directory)
  await act(async () => resolveRefresh({ data: { ...PROJECT, capabilities: [] } }))
  expect(screen.getByRole('textbox', { name: '测试本页未保存输入' })).toBe(input)
  expect(input).toHaveValue('保留本页草稿')
})

describe('explicit archive and audit permission denials', () => {
  beforeEach(() => {
    vi.clearAllMocks(); route.projectId = 'p1'; route.pathname = '/pm/projects/p1/overview'
  })
  it.each([
    ['director', ['project.archive'], undefined, true, true],
    ['director', ['project.archive'], false, false, false],
    ['pm', ['project.update'], false, true, false],
    ['pm', ['project.update'], undefined, true, true],
    ['worker', ['project.archive'], true, false, true],
  ])('keeps %s status qualification separate from archive override %s', async (role, capabilities, archive, statusAllowed, archiveAllowed) => {
    useAuthMock.mockReturnValue({ user: { id: role, role, permission_overrides: archive === undefined ? {} : { 'project.archive': archive } } })
    apiGet.mockResolvedValue({ data: { ...PROJECT, capabilities } })
    render(<ProjectLayout />)
    const overview = await screen.findByTestId('mock-overview')
    expect(overview).toHaveAttribute('data-manage-status', String(statusAllowed))
    expect(overview).toHaveAttribute('data-can-archive', String(archiveAllowed))
  })
  it.each(['history', 'activity'])('blocks the %s audit route while project reads remain allowed', async path => {
    useAuthMock.mockReturnValue({ user: { id: 'pm', role: 'pm', permission_overrides: { 'system.audit.read': false } } })
    route.pathname = `/pm/projects/p1/${path}`
    apiGet.mockResolvedValue({ data: { ...PROJECT, capabilities: ['project.read'] } })
    render(<ProjectLayout />)
    expect(await screen.findByText('403', { selector: '.ant-result-title' })).toBeVisible()
    expect(screen.queryByText('动态占位 history')).not.toBeInTheDocument()
    expect(apiGet.mock.calls.map(([url]) => url)).toEqual(['/projects/p1'])
  })
})
