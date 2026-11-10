import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { ProjectCapabilitiesContext } from '../../../hooks/useProjectCapability'
const { navigate, apiGet, apiPost } = vi.hoisted(() => ({ navigate: vi.fn(), apiGet: vi.fn(), apiPost: vi.fn() }))
vi.mock('react-router-dom', () => ({ useNavigate: () => navigate }))
vi.mock('../../../components/LazyChart', () => ({ default: () => <div data-testid="lazy-chart" /> }))
vi.mock('../../../api/client', () => ({ api: { get: apiGet, post: apiPost }, errMsg: () => '读取失败' }))
import OverviewPage from './OverviewPage'

const overview = { progress: { percent: 0, completed: 0, target: 10, phases: [] }, timeline: [], overdue: { items: [] }, issues: [], tree: [{ work_items: [{ id: 'w1' }] }], logs: [],
  weekly_plans: { state: 'available', total: 0, overdue_count: 0 }, document_progress: { pending: 0, submitted: 0, waived: 0, required_pending: 0, total: 0 } }
beforeEach(() => { vi.clearAllMocks(); apiGet.mockResolvedValue({ data: overview }); apiPost.mockResolvedValue({ data: {} }) })
const statusBar = async () => within(await screen.findByRole('region', { name: '项目状态' }))
const confirmIn = (name: string) => fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name }))

describe('项目概况', () => {
  it('loads everything with one request and pushes status forward after a single confirmation, without any checklist', async () => {
    render(<OverviewPage projectId="p1" projectStatus="preparing" canManageStatus />)
    const bar = await statusBar()
    expect(apiGet).toHaveBeenCalledTimes(1)
    expect(bar.getByText('下一步：现场实施')).toBeVisible()
    expect(screen.queryByText(/还差/)).not.toBeInTheDocument()
    expect(screen.queryByRole('list', { name: '准备清单' })).not.toBeInTheDocument()
    fireEvent.click(bar.getByRole('button', { name: '推进到「现场实施」' }))
    expect(apiPost).not.toHaveBeenCalled()
    fireEvent.change(within(screen.getByRole('dialog')).getByRole('textbox', { name: '状态变更说明' }), { target: { value: '人员已到场' } })
    confirmIn('确 认')
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith('/projects/p1/status', { status: 'executing', retrospective: '', reason: '人员已到场' }))
  })

  it('offers stepping back and suspension from the menu', async () => {
    render(<OverviewPage projectId="p1" projectStatus="acceptance" canManageStatus />)
    const bar = await statusBar()
    expect(bar.getByRole('button', { name: '推进到「已完成」' })).toBeVisible()
    fireEvent.click(bar.getByRole('button', { name: /调整项目状态/ }))
    fireEvent.click(await screen.findByRole('menuitem', { name: '退回「现场实施」' }))
    confirmIn('确 认')
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith('/projects/p1/status', expect.objectContaining({ status: 'executing' })))
  })

  it('suspension needs a reason and resuming returns to the stored status', async () => {
    const { unmount } = render(<OverviewPage projectId="p1" projectStatus="executing" canManageStatus />)
    fireEvent.click((await statusBar()).getByRole('button', { name: /调整项目状态/ }))
    fireEvent.click(await screen.findByRole('menuitem', { name: '突发停工' }))
    const dialog = within(screen.getByRole('dialog'))
    expect(dialog.getByRole('button', { name: '确认停工' })).toBeDisabled()
    fireEvent.change(dialog.getByRole('textbox'), { target: { value: '客户现场断电' } })
    fireEvent.click(dialog.getByRole('button', { name: '确认停工' }))
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith('/projects/p1/status', expect.objectContaining({ status: 'suspended', reason: '客户现场断电' })))
    unmount(); apiPost.mockClear()
    render(<OverviewPage projectId="p1" projectStatus="suspended" projectSuspension={{ status_before: 'executing', reason: '客户现场断电' }} canManageStatus />)
    fireEvent.click((await statusBar()).getByRole('button', { name: /恢复项目/ }))
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith('/projects/p1/status', expect.objectContaining({ status: 'executing' })))
  })

  it('archiving asks for a retrospective and keeps it when the server refuses', async () => {
    apiPost.mockRejectedValueOnce({ response: { data: { detail: '项目已被他人更新，请刷新' } } })
    render(<OverviewPage projectId="p1" projectStatus="completed" canManageStatus />)
    fireEvent.click((await statusBar()).getByRole('button', { name: '推进到「已归档」' }))
    const dialog = within(screen.getByRole('dialog'))
    expect(dialog.getByRole('button', { name: '确认归档' })).toBeDisabled()
    fireEvent.change(dialog.getByRole('textbox'), { target: { value: '点位表确认偏慢，下次提前对齐' } })
    fireEvent.click(dialog.getByRole('button', { name: '确认归档' }))
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith('/projects/p1/status', expect.objectContaining({ status: 'archived', retrospective: '点位表确认偏慢，下次提前对齐' })))
    expect(await dialog.findByText('项目已被他人更新，请刷新')).toBeInTheDocument()
    expect(dialog.getByRole('textbox')).toHaveValue('点位表确认偏慢，下次提前对齐')
  })

  it('without archive permission the project cannot be archived but can still step back', async () => {
    render(<OverviewPage projectId="p1" projectStatus="completed" canManageStatus canArchive={false} />)
    const bar = await statusBar()
    expect(bar.queryByRole('button', { name: '推进到「已归档」' })).not.toBeInTheDocument()
    fireEvent.click(bar.getByRole('button', { name: /调整项目状态/ }))
    expect(await screen.findByRole('menuitem', { name: '退回「验收中」' })).toBeInTheDocument()
  })

  it('people without status rights read the stage and acceptance but get no controls', async () => {
    apiGet.mockResolvedValue({ data: { ...overview, acceptance_summary: { latest: { id: 'a2', conclusion: 'rejected', accepted_at: '2026-10-02', accepted_by_name: '客户代表' }, eligible: false, reason: '最新验收不通过，需复检' } } })
    render(<ProjectCapabilitiesContext.Provider value={[]}><OverviewPage projectId="p1" projectStatus="acceptance" /></ProjectCapabilitiesContext.Provider>)
    const bar = await statusBar()
    expect(bar.getByText(/客户确认后推进到已完成/)).toBeVisible()
    expect(bar.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.getByText('最新验收结论：不通过')).toBeInTheDocument()
  })

  it('lists open issues plainly, without singling out severe ones', async () => {
    apiGet.mockResolvedValue({ data: { ...overview, issues: [{ id: 'i1', status: 'open', severity: 'critical' }, { id: 'i2', status: 'processing', severity: 'low' }, { id: 'i3', status: 'closed', severity: 'high' }],
      weekly_plans: { state: 'available', total: 12, overdue_count: 0 } } })
    render(<OverviewPage projectId="p1" projectStatus="executing" canManageStatus />)
    const issues = await screen.findByRole('link', { name: /现场问题/ })
    expect(issues).toHaveTextContent('2 个问题未关闭')
    expect(screen.queryByText(/严重问题|评估影响|优先处理/)).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: /周计划/ })).toHaveTextContent('已安排 12 格')
    fireEvent.click(issues)
    expect(navigate).toHaveBeenCalledWith('/pm/projects/p1/issues')
  })

  it('opens progress detail on demand and links groups to the plan', async () => {
    apiGet.mockResolvedValue({ data: { ...overview, progress: { ...overview.progress, percent: 100,
      quantities_by_unit: [{ unit: '台', completed: 1, target: 2 }, { unit: '米', completed: 2, target: 10 }],
      phases: [{ id: 'phase1', name: '进场准备', percent: 100 }] } } })
    render(<OverviewPage projectId="p1" projectStatus="executing" />)
    const toggle = await screen.findByRole('button', { name: '进度与记录' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(toggle)
    expect(within(screen.getByRole('list', { name: '各单位数量' })).getAllByRole('listitem')).toHaveLength(2)
    fireEvent.click(within(screen.getByRole('list', { name: '各分组进度' })).getByRole('button', { name: '进场准备' }))
    expect(navigate).toHaveBeenCalledWith('/pm/projects/p1/plan')
    expect(apiPost).not.toHaveBeenCalled()
  })
})
