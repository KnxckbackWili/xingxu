import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import IssuesPage from './IssuesPage'
import { api } from '../../../api/client'
import { ProjectStatusContext } from '../../../hooks/useProjectCapability'

const { useAuthMock, useMediaQueryMock } = vi.hoisted(() => ({
  useAuthMock: vi.fn(),
  useMediaQueryMock: vi.fn(),
}))

vi.mock('../../../stores/auth', () => ({
  useAuth: useAuthMock,
}))

vi.mock('react-router-dom', () => ({
  useLocation: () => ({ search: '' }),
}))

vi.mock('../../../hooks/useMediaQuery', () => ({
  useMediaQuery: useMediaQueryMock,
}))

const upload = vi.hoisted(() => vi.fn())
vi.mock('../../../uploads/queue', () => ({ uploadQueue: { upload }, UPLOAD_COMPLETE_EVENT: 'upload-complete-test' }))
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

const userListActive = vi.fn()
vi.mock('../../../api', () => ({
  userApi: { listActive: (...args: unknown[]) => userListActive(...args) },
}))

const PROJECT_ISSUES = [
  {
    id: 'i1',
    title: '线材拉一下就能连上编码器，正常行驶的时候会一侧突然断连',
    description: '现象描述',
    issue_type: 'hardware',
    extra: { device: 'AGV-01', affects_schedule: '影响' },
    severity: 'critical' as const,
    status: 'open' as const,
    reporter_id: 'u1',
    reporter_name: '孙晓',
    assignee_id: null,
    assignee_name: '',
    task_id: null,
    task_name: '',
    created_at: '2026-08-01T10:00:00',
    resolved_at: null,
    resolution: '',
  },
  {
    id: 'i2',
    title: '质量问题反馈单导入的问题',
    description: '导入的问题描述',
    issue_type: 'other',
    // 质量问题反馈单导入带入的原始字段（应被过滤，不泄漏到标题区）
    extra: {
      project_name: '天津环晟',
      reporter_name: '孙晓',
      vehicle_model: 'X1',
      vehicle_no: 'AGV-03',
      part: '传感器',
      feedback_date: '2026-08-12',
    },
    severity: 'low' as const,
    status: 'resolved' as const,
    reporter_id: 'u1',
    reporter_name: '孙晓',
    assignee_id: 'u2',
    assignee_name: '张三',
    task_id: null,
    task_name: '',
    created_at: '2026-08-02T10:00:00',
    resolved_at: null,
    resolution: '',
  },
]

const VEHICLE_ISSUES = [
  {
    id: 'v1',
    source: 'vehicle' as const,
    vehicle_unit_id: 'vu1',
    asset_code: 'AGV-03',
    vehicle_status: 'fault',
    title: '底盘异响',
    description: '行驶时底盘异响',
    fault_part: '驱动轮',
    cause: '',
    action_taken: '',
    replaced_parts: [],
    verification: '',
    handler: '',
    downtime_hours: null,
    status: 'open' as const,
    event_type: 'fault',
    event_date: '2026-08-03',
    reporter_name: '李四',
  },
]

afterEach(() => vi.unstubAllGlobals())

it('starts handling from the list without opening the issue drawer', async () => {
  useMediaQueryMock.mockReturnValue(false)
  vi.mocked(api.put).mockResolvedValueOnce({ data: {} })
  render(<IssuesPage projectId="p1" canManage />)
  fireEvent.click(await screen.findByRole('button', { name: '开始处理' }))
  await waitFor(() => expect(api.put).toHaveBeenCalledWith('/issues/i1', expect.objectContaining({ status: 'processing' })))
  expect(screen.queryByText('处理时间线')).not.toBeInTheDocument()
})

it('offers a named inline handler control while leaving read-only issues unchanged', async () => {
  useMediaQueryMock.mockReturnValue(false)
  const view = render(<IssuesPage projectId="p1" canManage />)
  expect(await screen.findByRole('combobox', { name: `${PROJECT_ISSUES[0].title}处理人` })).toBeInTheDocument()
  view.rerender(<IssuesPage projectId="p1" canManage={false} archived />)
  expect(screen.queryByRole('combobox', { name: `${PROJECT_ISSUES[0].title}处理人` })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '开始处理' })).not.toBeInTheDocument()
})

beforeEach(() => {
  vi.clearAllMocks()
  useAuthMock.mockReturnValue({ user: { id: 'u1', role: 'pm' } })
  apiGet.mockImplementation((url: string) => {
    if (url.includes('/issues')) return Promise.resolve({ data: PROJECT_ISSUES })
    if (url.includes('/vehicle-issues')) return Promise.resolve({ data: VEHICLE_ISSUES })
    if (url.includes('/documents/files')) return Promise.resolve({ data: [] })
    if (url.includes('/tree')) return Promise.resolve({ data: [] })
    return Promise.resolve({ data: [] })
  })
  userListActive.mockResolvedValue([])
})

describe('IssuesPage 移动端卡片布局', () => {
  it('移动端渲染卡片而非压缩表格，类型/严重程度/状态可读', async () => {
    useMediaQueryMock.mockReturnValue(true)
    render(<IssuesPage projectId="p1" />)
    await waitFor(() => {
      expect(screen.getByText('线材拉一下就能连上编码器，正常行驶的时候会一侧突然断连')).toBeInTheDocument()
    })
    // 车辆问题卡片也渲染
    expect(screen.getByText(/AGV-03 ·/)).toBeInTheDocument()
    expect(screen.getByText('底盘异响')).toBeInTheDocument()
    // 类型/严重程度/状态标签
    expect(screen.getByText('硬件')).toBeInTheDocument()
    expect(screen.getByText('严重')).toBeInTheDocument()
    expect(screen.getByText('待处理')).toBeInTheDocument()
    fireEvent.click(screen.getByText('全部', {selector:'.ant-segmented-item-label'}))
    expect(screen.getByText('已解决')).toBeInTheDocument()
  })

  it('标题区不泄漏 project_name/reporter_name 原始字段串', async () => {
    useMediaQueryMock.mockReturnValue(true)
    render(<IssuesPage projectId="p1" />)
    fireEvent.click(screen.getByText('全部', {selector:'.ant-segmented-item-label'}))
    await waitFor(() => {
      expect(screen.getByText('质量问题反馈单导入的问题')).toBeInTheDocument()
    })
    expect(screen.queryByText(/project_name/)).not.toBeInTheDocument()
    expect(screen.queryByText(/reporter_name/)).not.toBeInTheDocument()
    // 已知分类字段仍有可读摘要
    expect(screen.getByText('设备/部位：AGV-01 · 是否影响工期：影响')).toBeInTheDocument()
  })
})

describe('IssuesPage 桌面端表格', () => {
  it('桌面端渲染表格，标题列与操作列可点击', async () => {
    useMediaQueryMock.mockReturnValue(false)
    render(<IssuesPage projectId="p1" />)
    await waitFor(() => {
      expect(screen.getByText('线材拉一下就能连上编码器，正常行驶的时候会一侧突然断连')).toBeInTheDocument()
    })
    // 表格标题与操作（每个问题一行各有一个操作按钮）
    fireEvent.click(screen.getByRole('button', {name: PROJECT_ISSUES[0].title}))
    expect(screen.getByRole('button', {name:/导出单据/})).toBeInTheDocument()
    expect(screen.getByText('处理时间线')).toBeInTheDocument()
    // 表格模式下也不出现原始字段串
    expect(screen.queryByText(/project_name/)).not.toBeInTheDocument()
  })
})


describe('问题上报与权限流程', () => {
  it('HTTP 环境无 randomUUID 时仍按 extra 提交，重复点击只发送一次', async () => {
    useMediaQueryMock.mockReturnValue(true)
    vi.stubGlobal('crypto', {})
    vi.mocked(api.post).mockImplementation(() => new Promise(() => {}))
    render(<IssuesPage projectId="p1" canManage />)
    fireEvent.click(screen.getByRole('button', { name: /上报问题/ }))
    fireEvent.change(screen.getByLabelText('问题标题'), { target: { value: '充电失败' } })
    fireEvent.change(screen.getByLabelText('设备/部位'), { target: { value: 'AGV-01' } })
    const submit = screen.getByRole('button', { name: /确.*定/ })
    fireEvent.click(submit)
    fireEvent.click(submit)
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1))
    expect(vi.mocked(api.post).mock.calls[0][1]).toMatchObject({
      title: '充电失败', extra: { device: 'AGV-01' },
    })
  })

  it('没有项目管理能力的 PM 不显示指派操作', async () => {
    useMediaQueryMock.mockReturnValue(false)
    render(<IssuesPage projectId="p1" canManage={false} />)
    await screen.findByText(PROJECT_ISSUES[0].title)
    expect(screen.queryByRole('button', { name: /指派/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /改派/ })).not.toBeInTheDocument()
  })
})

it('附件失败后重试只上传剩余文件，不重复建问题', async () => {
  useMediaQueryMock.mockReturnValue(true)
  upload.mockReset().mockRejectedValueOnce(new Error('upload failed')).mockResolvedValueOnce({ file: { id: 'attachment' }, documents: [] })
  vi.mocked(api.post).mockImplementation(async (url) => {
    if (String(url).endsWith('/issues')) return { data: { id: 'saved-issue' } }
    throw new Error('unexpected issue write')
  })
  const { container } = render(<IssuesPage projectId="p1" canManage />)
  fireEvent.click(screen.getByRole('button', { name: /上报问题/ }))
  fireEvent.change(screen.getByLabelText('问题标题'), { target: { value: '附件重试' } })
  const input = document.querySelector('input[type="file"][multiple]')!
  fireEvent.change(input, { target: { files: [new File(['photo'], 'fault.png', { type: 'image/png' })] } })
  await screen.findByText('fault.png')
  fireEvent.click(screen.getByRole('button', { name: /确.*定/ }))
  const retry = await screen.findByRole('button', { name: '重试剩余附件' })
  await waitFor(() => expect(retry).not.toBeDisabled())
  fireEvent.click(retry)
  await waitFor(() => expect(upload).toHaveBeenCalledTimes(2))
  expect(upload).toHaveBeenLastCalledWith('p1', expect.any(File), expect.objectContaining({ entityType: 'issue', entityId: 'saved-issue' }))
  expect(vi.mocked(api.post).mock.calls.filter(([url]) => String(url).endsWith('/issues'))).toHaveLength(1)
  await waitFor(() => expect(screen.queryByRole('button', { name: '重试剩余附件' })).not.toBeInTheDocument())
  expect(container).toBeInTheDocument()
})

it('搜索同时过滤项目问题与车辆问题', async () => {
  useMediaQueryMock.mockReturnValue(true)
  render(<IssuesPage projectId="p1" />)
  await screen.findByText(PROJECT_ISSUES[0].title)
  fireEvent.change(screen.getByPlaceholderText('搜索问题、处理人或车辆'), { target: { value: 'AGV-03' } })
  expect(screen.getByText('底盘异响')).toBeInTheDocument()
  expect(screen.queryByText(PROJECT_ISSUES[0].title)).not.toBeInTheDocument()
})

it('解决提交失败保留方案，重试后才关闭', async () => {
  useMediaQueryMock.mockReturnValue(true)
  vi.mocked(api.put).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ data: {} })
  render(<IssuesPage projectId="p1" canManage />)
  fireEvent.click(await screen.findByText(PROJECT_ISSUES[0].title))
  fireEvent.click(screen.getByRole('button', { name: /解.*决/ }))
  fireEvent.change(screen.getByLabelText('解决方案'), { target: { value: '重新固定连接线并复测' } })
  fireEvent.click(screen.getByRole('button', { name: '提交解决方案' }))
  await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1))
  expect(screen.getByLabelText('解决方案')).toHaveValue('重新固定连接线并复测')
  await waitFor(() => expect(screen.getByRole('button', { name: '提交解决方案' })).not.toHaveClass('ant-btn-loading'))
  fireEvent.click(screen.getByRole('button', { name: '提交解决方案' }))
  await waitFor(() => expect(api.put).toHaveBeenCalledTimes(2))
  expect(vi.mocked(api.put).mock.calls[1][1]).toMatchObject({ status: 'resolved', resolution: '重新固定连接线并复测' })
})

it('候选处理人只来自当前项目端点，禁止回退全员', async () => {
  useMediaQueryMock.mockReturnValue(true)
  const original = apiGet.getMockImplementation()!
  apiGet.mockImplementation((url: string) => url.endsWith('/issue-assignees')
    ? Promise.resolve({ data: [{ id: 'member', display_name: '项目内处理人' }] }) : original(url))
  render(<IssuesPage projectId="p1" canManage />)
  await screen.findByText(PROJECT_ISSUES[0].title)
  expect(apiGet).toHaveBeenCalledWith('/projects/p1/issue-assignees')
  expect(userListActive).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', {name: PROJECT_ISSUES[0].title}))
  fireEvent.click(screen.getByRole('button', { name: /指派/ }))
  fireEvent.mouseDown(screen.getByRole('combobox', { name: '问题处理人' }))
  expect(await screen.findByText('项目内处理人')).toBeInTheDocument()
})

it('候选人读取失败禁用指派，保留重试入口', async () => {
  useMediaQueryMock.mockReturnValue(true)
  const original = apiGet.getMockImplementation()!
  apiGet.mockImplementation((url: string) => url.endsWith('/issue-assignees') ? Promise.reject(new Error('offline')) : original(url))
  render(<IssuesPage projectId="p1" canManage />)
  await screen.findByText(PROJECT_ISSUES[0].title)
  fireEvent.click(screen.getByRole('button', {name: PROJECT_ISSUES[0].title}))
  fireEvent.click(screen.getByRole('button', { name: /指派/ }))
  expect(await screen.findByText('可处理人员加载失败，请重试')).toBeInTheDocument()
  expect(screen.getByRole('combobox', { name: '问题处理人' })).toBeDisabled()
  expect(userListActive).not.toHaveBeenCalled()
})

it.each(['pm', 'lead', 'technician', 'worker', 'intern'])('已指派的 %s 可在共享工作区处理本人问题，不能改派', async role => {
  useMediaQueryMock.mockReturnValue(true)
  useAuthMock.mockReturnValue({ user: { id: 'handler', role } })
  const original = apiGet.getMockImplementation()!
  apiGet.mockImplementation((url: string) => url.endsWith('/issues')
    ? Promise.resolve({ data: [{ ...PROJECT_ISSUES[0], assignee_id: 'handler' }] }) : original(url))
  render(<IssuesPage projectId="p1" />)
  fireEvent.click(await screen.findByText(PROJECT_ISSUES[0].title))
  expect(screen.getByRole('button', { name: '开始处理' })).toBeVisible()
  expect(screen.getByRole('button', { name: /解.*决/ })).toBeVisible()
  expect(screen.queryByRole('button', { name: /指派/ })).toBeNull()
})

it('归档项目不显示任何问题写入口，但保留详情与导出', async () => {
  useMediaQueryMock.mockReturnValue(true)
  render(<IssuesPage projectId="p1" canManage archived />)
  fireEvent.click(await screen.findByText(PROJECT_ISSUES[0].title))
  for (const name of ['上报问题', '导入质量问题反馈单', '指派', '开始处理', '重新打开', '作废']) {
    expect(screen.queryByRole('button', { name: new RegExp(name) })).toBeNull()
  }
  expect(screen.getAllByRole('button', { name: /导出单据/ }).length).toBeGreaterThan(0)
})
it('unknown history hides issue writes, including reporter/assignee role fallbacks, without disabling export', async () => {
  useMediaQueryMock.mockReturnValue(true)
  render(<ProjectStatusContext.Provider value="legacy_unknown"><IssuesPage projectId="p1" canManage /></ProjectStatusContext.Provider>)
  fireEvent.click(await screen.findByText(PROJECT_ISSUES[0].title))
  for (const name of ['上报问题', '导入质量问题反馈单', '指派', '开始处理', '重新打开', '作废']) {
    expect(screen.queryByRole('button', { name: new RegExp(name) })).toBeNull()
  }
  expect(screen.getAllByRole('button', { name: /导出单据/ }).length).toBeGreaterThan(0)
})

it('指派请求在途时锁住选择及关闭，避免重复改派', async () => {
  useMediaQueryMock.mockReturnValue(true)
  const original = apiGet.getMockImplementation()!
  apiGet.mockImplementation((url: string) => url.endsWith('/issue-assignees')
    ? Promise.resolve({ data: [{ id: 'member', display_name: '项目内处理人' }] }) : original(url))
  vi.mocked(api.put).mockImplementation(() => new Promise(() => {}))
  render(<IssuesPage projectId="p1" canManage />)
  await screen.findByText(PROJECT_ISSUES[0].title)
  fireEvent.click(screen.getByRole('button', {name: PROJECT_ISSUES[0].title}))
  fireEvent.click(screen.getByRole('button', { name: /指派/ }))
  fireEvent.mouseDown(screen.getByRole('combobox', { name: '问题处理人' }))
  fireEvent.click(await screen.findByText('项目内处理人'))
  await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1))
  expect(screen.getByRole('combobox', { name: '问题处理人' })).toBeDisabled()
  expect(within(screen.getByRole('combobox', {name:'问题处理人'}).closest('[role="dialog"]') as HTMLElement).queryByRole('button', { name: 'Close' })).toBeNull()
})

it('keeps resolved vehicle events out of the project close queue and exposes history through All', async () => {
  useMediaQueryMock.mockReturnValue(false)
  const original=apiGet.getMockImplementation()!
  apiGet.mockImplementation((url:string)=>url.endsWith('/vehicle-issues')?Promise.resolve({data:[{...VEHICLE_ISSUES[0],status:'resolved'}]}):original(url))
  render(<IssuesPage projectId="p1" canManage />)
  await screen.findByText(PROJECT_ISSUES[0].title)
  expect(screen.queryByText(PROJECT_ISSUES[1].title)).toBeNull()
  fireEvent.click(screen.getByText('待关闭',{selector:'.ant-segmented-item-label'}))
  expect(screen.getByText(PROJECT_ISSUES[1].title)).toBeInTheDocument()
  expect(screen.queryByText(VEHICLE_ISSUES[0].title)).toBeNull()
  fireEvent.click(screen.getByText('全部',{selector:'.ant-segmented-item-label'}))
  expect(screen.getByText(VEHICLE_ISSUES[0].title)).toBeInTheDocument()
  expect(screen.getAllByRole('table')).toHaveLength(1)
})

it('reports accident nature independently from hardware type and preserves the true server SLA',async()=>{
  useMediaQueryMock.mockReturnValue(false)
  vi.mocked(api.post).mockResolvedValue({data:{id:'real-accident'}})
  render(<IssuesPage projectId="p1" canManage />)
  fireEvent.click(await screen.findByRole('button',{name:'上报问题'}))
  const modal=within(screen.getByRole('dialog'))
  fireEvent.change(modal.getByLabelText('问题标题'),{target:{value:'碰撞事故'}})
  fireEvent.mouseDown(modal.getByLabelText('问题性质'))
  fireEvent.click(screen.getByText('事故',{selector:'.ant-select-item-option-content'}))
  fireEvent.click(modal.getByRole('button',{name:/^确\s*定$/}))
  await waitFor(()=>expect(api.post).toHaveBeenCalledWith('/projects/p1/issues',expect.objectContaining({nature:'accident',issue_type:'hardware',title:'碰撞事故'})))
})
