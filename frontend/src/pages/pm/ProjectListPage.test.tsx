import { expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import ProjectListPage from './ProjectListPage'
import { api } from '../../api/client'
import { projectApi } from '../../api'
const { params, navigate, setSearchParams, auth } = vi.hoisted(() => {
  const params = new URLSearchParams('create=1')
  return { params, auth: { user: { role: 'pm' } as any }, navigate: vi.fn(), setSearchParams: vi.fn(() => {
    // The real router consumes ?create=1 once. A fresh setter on every render
    // would continually reopen/reset the wizard, unlike useSearchParams.
    for (const key of [...params.keys()]) params.delete(key)
  }) }
})
vi.mock('react-router-dom', () => ({ useNavigate: () => navigate, useSearchParams: () => [params, setSearchParams] }))
vi.mock('../../stores/auth', () => ({ useAuth: () => auth }))
vi.mock('../../api', () => ({ projectApi: { list: vi.fn().mockResolvedValue([]), create: vi.fn() } }))
vi.mock('../../api/client', () => ({ api: { get: vi.fn(), post: vi.fn() }, errMsg: () => 'error' }))
vi.mock('../../hooks/useVehicleTypes', () => ({ useVehicleTypes: () => ({ options: [], loading: false, error: null }), toVehicleTypeSelectOptions: () => [] }))

async function fillProjectDetails() {
  fireEvent.change(screen.getByLabelText('项目名称'), { target: { value: '首次创建项目' } })
  fireEvent.change(screen.getByLabelText('客户'), { target: { value: '客户公司' } })
  fireEvent.change(screen.getByLabelText('地点'), { target: { value: '上海' } })
  fireEvent.change(screen.getByLabelText('型号'), { target: { value: 'T6' } })
  const dates = document.querySelectorAll<HTMLInputElement>('.ant-picker-range input')
  for (const [index, date] of [...dates].entries()) {
    fireEvent.focus(date)
    fireEvent.change(date, { target: { value: index === 0 ? '2026-10-07' : '2026-11-07' } })
    fireEvent.keyDown(date, { key: 'Enter', code: 'Enter', keyCode: 13 })
    fireEvent.blur(date)
  }
}

it('starts with project details, validates them before content, and explains draft without choosing a running stage', async () => {
  params.set('create', '1')
  vi.mocked(projectApi.list).mockResolvedValue([])
  vi.mocked(api.get).mockResolvedValue({ data: [] })
  render(<ConfigProvider theme={{ token: { motion: false } }}><ProjectListPage /></ConfigProvider>)
  await waitFor(() => expect(screen.getByText('新项目从筹备开始')).toBeVisible())
  expect(screen.getByLabelText('项目名称')).toBeVisible()
  expect(screen.queryByRole('button', { name: /系统模板/ })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '选择工作内容' }))
  expect(await screen.findByText('请输入项目名称')).toBeVisible()
  expect(screen.getByRole('button', { name: '选择工作内容' })).toBeVisible()
  expect(screen.queryByRole('combobox', { name: '项目初始阶段' })).not.toBeInTheDocument()
  expect(projectApi.create).not.toHaveBeenCalled()
})

it('permits entering details during template loading, blocks confirmation, and ignores an old response', async () => {
  vi.clearAllMocks()
  params.set('create', '1')
  let finishOld: (value: unknown) => void = () => {}
  vi.mocked(api.get).mockImplementation(async (url) => {
    if (url === '/templates') return { data: [{ id: 'default', name: '系统模板', is_system: true }, { id: 'new', name: '另一模板', is_system: true }] }
    if (url === '/templates/default/work-items') return new Promise((resolve) => { finishOld = resolve })
    if (url === '/templates/new/work-items') return { data: { phases: [{ id: 'new-phase', name: '新模板阶段', work_items: [{ id: 'new-work', name: '新模板工作', check_items: [] }] }] } }
    return { data: [] }
  })
  render(<ConfigProvider theme={{ token: { motion: false } }}><ProjectListPage /></ConfigProvider>)
  expect(await screen.findByText('正在加载模板，请稍候…')).toBeInTheDocument()
  await waitFor(() => expect(api.get).toHaveBeenCalledWith('/templates/default/work-items'))
  expect(screen.getByRole('button', { name: '选择工作内容' })).not.toBeDisabled()
  await fillProjectDetails()
  fireEvent.click(screen.getByRole('button', { name: '选择工作内容' }))
  expect(await screen.findByRole('button', { name: '检查并创建' })).toBeDisabled()
  fireEvent.click(await screen.findByRole('button', { name: /另一模板/ }))
  expect(await screen.findByText('新模板阶段')).toBeVisible()
  await act(async () => { finishOld({ data: { phases: [{ id: 'old-phase', name: '过期阶段', work_items: [{ id: 'old-work', name: '过期工作', check_items: [] }] }] } }) })
  expect(screen.queryByText('过期模块')).not.toBeInTheDocument()
  expect(screen.getByText('新模板阶段')).toBeVisible()
  await waitFor(() => expect(screen.getByRole('button', { name: '检查并创建' })).not.toBeDisabled())
}, 15_000)

it.each(['table', 'card'])('keeps unavailable progress distinct from a real zero and recovers its filters (%s)', async view => {
  params.delete('create')
  localStorage.setItem('agvpm_proj_view', view)
  const project = { id: 'live', name: '实施项目', abbreviation: '', manager: 'me',
    client: '客户', location: '上海', start_date: '2026-09-01', end_date: '2026-12-01',
    status: 'executing', description: '', members: ['me'], created_at: '2026-09-01T00:00:00Z' }
  vi.mocked(projectApi.list).mockResolvedValue([project, { ...project, id: 'zero', name: '零进度项目'}])
  let overviewAvailable = false
  vi.mocked(api.get).mockImplementation(async url => {
    if (url === '/dashboard/overview') {
      return { data: { projects: overviewAvailable
        ? [{ id: 'live', percent: 65, overdue: true, critical_issues: 1 }, { id: 'zero', percent: 0 }]
        : [{ id: 'zero', percent: 0 }] } }
    }
    return { data: [] }
  })
  render(<ConfigProvider theme={{ token: { motion: false } }}><ProjectListPage /></ConfigProvider>)
  expect(await screen.findByText('进度暂不可用')).toBeVisible()
  expect(screen.getAllByText('0%')).toHaveLength(1)
  fireEvent.mouseDown(screen.getByRole('combobox', { name: '按进度筛选' }))
  fireEvent.click(screen.getByText('未启动', { selector: '.ant-select-item-option-content' }))
  expect(screen.queryByText('实施项目')).not.toBeInTheDocument()
  expect(screen.getByText('零进度项目')).toBeVisible()
  expect(screen.getByText('1 个项目')).toBeInTheDocument()
  overviewAvailable = true
  fireEvent.click(screen.getByRole('button', { name: '重试进度' }))
  await waitFor(() => expect(screen.queryByText('部分项目进度与风险暂不可用')).not.toBeInTheDocument())
  fireEvent.click(screen.getByRole('button', { name: '清除筛选' }))
  expect(await screen.findByText('65%')).toBeVisible()
  expect(screen.getByText('实施项目')).toBeVisible()
})

it('keeps other projects available when the dashboard lacks one progress value', async () => {
  params.delete('create')
  localStorage.setItem('agvpm_proj_view', 'table')
  const project = { id: 'live', name: '正常实施项目', abbreviation: '', manager: 'me',
    client: '客户', location: '上海', start_date: '2026-09-01', end_date: '2026-12-01',
    status: 'executing', description: '', members: ['me'], created_at: '2026-09-01T00:00:00Z' }
  vi.mocked(projectApi.list).mockResolvedValue([project, { ...project, id: 'unknown', name: '进度不可用项目'}])
  vi.mocked(api.get).mockImplementation(async url => {
    if (url === '/dashboard/overview') return { data: { projects: [{ id: 'live', percent: 65 }] } }
    return { data: [] }
  })
  render(<ConfigProvider theme={{ token: { motion: false } }}><ProjectListPage /></ConfigProvider>)
  expect(await screen.findByText('正常实施项目')).toBeVisible()
  expect(screen.getByText('65%')).toBeVisible()
  expect(screen.getByText('进度不可用项目')).toBeVisible()
  expect(screen.getByText('进度暂不可用')).toBeVisible()
  expect(screen.queryByText('项目列表加载失败')).not.toBeInTheDocument()
})


it('previews current-platform material definitions while separating vehicle rules, legacy sources and optional procurement', async () => {
  params.set('create', '1')
  vi.mocked(projectApi.list).mockResolvedValue([])
  vi.mocked(api.get).mockImplementation(async url => {
    if (url === '/templates') return { data: [{ id: 'default', name: '系统模板', is_system: true }] }
    if (url === '/templates/default/work-items') return { data: { phases: [{ id: 'phase', name: '实施', work_items: [{ id: 'task1', name: '现场点检', kind: 'other', check_items: [] }] }] } }
    if (url === '/templates/default/document-requirements') return { data: [
      { id: 'generic', code: '4.1', stage_key: '4', name: '客户启动资料', scope: 'project', required: true, platform: null },
      { id: 'ndc', code: '6.11.1a', stage_key: '6', name: 'NDC说明', scope: 'vehicle', required: true, platform: 'NDC' },
      { id: 'grace', code: '6.11.2', stage_key: '6', name: 'GRACE说明', scope: 'project', required: true, platform: 'GRACE' },
      { id: 'group', code: '6.11', stage_key: '6', name: '平台分组', is_group: true },
      { id: 'old', code: 'legacy-old', stage_key: 'legacy', name: '旧任务资料', required: true },
    ] }
    if (url === '/templates/default/procurements') return { data: [{ id: 'buy1', name: '设备A' }, { id: 'buy2', name: '设备B' }] }
    return { data: [] }
  })
  render(<ConfigProvider theme={{ token: { motion: false } }}><ProjectListPage /></ConfigProvider>)
  await screen.findByText('新项目从筹备开始')
  await waitFor(() => expect(api.get).toHaveBeenCalledWith('/templates/default/document-requirements'))
  await waitFor(() => expect(screen.queryByText('正在加载模板，请稍候…')).not.toBeInTheDocument())
  await fillProjectDetails()
  fireEvent.click(screen.getByText('其他资料：关键事件、调度平台、服务器、地区与时区'))
  fireEvent.mouseDown(screen.getByRole('combobox', { name: '调度平台' }))
  fireEvent.click(await screen.findByText('NDC', { selector: '.ant-select-item-option-content' }))
  fireEvent.click(screen.getByRole('button', { name: '选择工作内容' }))
  await waitFor(() => expect(screen.getByRole('button', { name: '检查并创建' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: '检查并创建' }))
  fireEvent.click(await screen.findByText('查看资料要求（2 项）'))
  expect(await screen.findByText(/4.1 客户启动资料/)).toBeVisible()
  expect(screen.getByText(/6.11.1a NDC说明/)).toBeVisible()
  expect(screen.queryByText(/GRACE说明/)).not.toBeInTheDocument()
  expect(screen.getByText('历史待分类 1 项')).toBeInTheDocument()
  expect(screen.getByText(/常用采购库 2 项可选，不会自动带入项目/)).toBeInTheDocument()
  expect(vi.mocked(api.get).mock.calls.some(([url]) => String(url).includes('/preparations'))).toBe(false)
}, 15_000)

it('filters overdue documents from the project DTO without workspace permission', async () => {
  params.delete('create');localStorage.setItem('agvpm_proj_view','table')
  auth.user={role:'pm',id:'scoped',permission_overrides:{'workspace.view':false}}
  const base={id:'due',name:'资料逾期项目',status:'executing',members:[],document_attention:{overdue_count:2}} as any
  vi.mocked(projectApi.list).mockResolvedValue([base,{...base,id:'clear',name:'资料齐备项目',document_attention:{overdue_count:0}}])
  vi.mocked(api.get).mockReset();vi.mocked(api.get).mockResolvedValue({data:[]})
  try {
    render(<ConfigProvider theme={{token:{motion:false}}}><ProjectListPage/></ConfigProvider>)
    await screen.findByText('资料齐备项目')
    fireEvent.mouseDown(screen.getByRole('combobox',{name:'按进度筛选'}))
    fireEvent.click(await screen.findByText('已逾期'))
    expect(screen.getByText('资料逾期项目')).toBeVisible()
    expect(screen.queryByText('资料齐备项目')).toBeNull()
    expect(vi.mocked(api.get).mock.calls.some(([url])=>url==='/dashboard/overview')).toBe(false)
    expect(screen.queryByRole('button',{name:'更多操作'})).toBeNull()
  } finally {auth.user={role:'pm'}}
})
