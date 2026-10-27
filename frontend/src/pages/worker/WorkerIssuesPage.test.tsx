import { beforeEach, expect, it, vi } from 'vitest'
import { act, fireEvent, render as renderDOM, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import type { ReactElement } from 'react'
import WorkerIssuesPage from './WorkerIssuesPage'
import { api } from '../../api/client'
import type { PermissionUser } from '../../constants/systemPermissions'

const render = (element: ReactElement, entry = '/worker/issues') => renderDOM(<MemoryRouter initialEntries={[entry]}>{element}</MemoryRouter>)

const authState: { user: PermissionUser } = vi.hoisted(() => ({ user: { id: 'worker', role: 'worker' } }))
vi.mock('../../stores/auth', () => ({ useAuth: () => authState }))
vi.mock('../../api/client', () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }))
beforeEach(() => {
  vi.resetAllMocks()
  authState.user = { id: 'worker', role: 'worker' }
  vi.mocked(api.get).mockImplementation(async (url) => ({ data: url === '/projects' ? [{ id: 'p1', name: '现场项目' }] : { items: [] } }) as any)
})

it('keeps assigned handling available when only issue reporting is denied', async () => {
  authState.user = { id: 'worker', role: 'worker', system_permissions: [], permission_overrides: { 'worker.issues': false } }
  vi.mocked(api.get).mockImplementation(async url => ({ data: url === '/projects' ? [{ id: 'p1', name: '现场项目', status: 'executing' }] : { items: [{ id: 'i1', title: '已指派的问题', assignee_id: 'worker', reporter_id: 'other', status: 'open', severity: 'medium', project_status: 'executing', version: 2 }] } }))
  vi.mocked(api.put).mockResolvedValue({ data: {} })
  render(<WorkerIssuesPage />, '/worker/issues?issue_id=i1')
  expect(await screen.findByRole('button', { name: '上报问题' })).toBeDisabled()
  const drawer = await screen.findByRole('dialog', { name: '已指派的问题' })
  fireEvent.click(within(drawer).getByRole('button', { name: '开始处理' }))
  await waitFor(() => expect(api.put).toHaveBeenCalledWith('/issues/i1', { status: 'processing', version: 2 }))
  expect(api.post).not.toHaveBeenCalled()
})

it.each(['open', 'resolved'])('keeps %s issues readable when contextual handling is explicitly denied', async status => {
  authState.user = { id: 'worker', role: 'worker', permission_overrides: { 'project.manage_issues': false } }
  vi.mocked(api.get).mockImplementation(async url => ({ data: url === '/projects' ? [] : { items: [{ id: 'i1', title: '仅查看问题', assignee_id: 'worker', reporter_id: 'worker', status, severity: 'medium', project_status: 'executing', resolution: '原处理结果' }] } }))
  render(<WorkerIssuesPage />, '/worker/issues?issue_id=i1')
  const drawer = await screen.findByRole('dialog', { name: '仅查看问题' })
  expect(within(drawer).queryByRole('button', { name: /开始处理|提交处理结果|重新打开/ })).not.toBeInTheDocument()
  expect(api.put).not.toHaveBeenCalled(); expect(api.post).not.toHaveBeenCalled()
})

it('cannot submit an open resolution after contextual permission is revoked', async () => {
  vi.mocked(api.get).mockImplementation(async url => ({ data: url === '/projects' ? [] : { items: [{ id: 'i1', title: '处理草稿', assignee_id: 'worker', reporter_id: 'worker', status: 'open', severity: 'medium', project_status: 'executing', version: 2 }] } }))
  const view = render(<WorkerIssuesPage />, '/worker/issues?issue_id=i1')
  const drawer = await screen.findByRole('dialog', { name: '处理草稿' })
  fireEvent.click(within(drawer).getByRole('button', { name: '提交处理结果' }))
  fireEvent.change(screen.getByLabelText('处理措施与验证结果'), { target: { value: '已填写，尚未提交' } })
  authState.user = { id: 'worker', role: 'worker', permission_overrides: { 'project.manage_issues': false } }
  view.rerender(<MemoryRouter initialEntries={['/worker/issues?issue_id=i1']}><WorkerIssuesPage /></MemoryRouter>)
  expect(screen.getByRole('button', { name: '提交复核' })).toBeDisabled()
  expect(screen.getByLabelText('处理措施与验证结果')).toHaveValue('已填写，尚未提交')
  await act(async () => { fireEvent.submit(screen.getByLabelText('处理措施与验证结果').closest('form')!) })
  expect(api.put).not.toHaveBeenCalled()
})

it('opens a permitted issue from a notification deep link', async () => {
  let resolveIssues!: (value: { data: { items: Record<string, unknown>[] } }) => void
  const pendingIssues = new Promise<{ data: { items: Record<string, unknown>[] } }>(resolve => { resolveIssues = resolve })
  vi.mocked(api.get).mockImplementation(async url => url === '/projects' ? { data: [] } : pendingIssues)
  vi.mocked(api.put).mockResolvedValue({ data: {} })
  render(<WorkerIssuesPage />, '/worker/issues?issue_id=i-link')
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(api.put).not.toHaveBeenCalled()
  await act(async () => resolveIssues({ data: { items: [{
    id: 'i-link', title: '深链复测问题', severity: 'medium', status: 'open', reporter_id: 'worker', assignee_id: 'worker',
    project_status: 'executing', project_name: '现场项目', created_at: '2026-10-04T19:20:00', source: 'project', version: 4,
  }] } }))
  expect(await screen.findByRole('button', { name: '深链复测问题' })).toBeVisible()
  const drawer = await screen.findByRole('dialog', { name: '深链复测问题' })
  const start = within(drawer).getByRole('button', { name: '开始处理' })
  expect(start).toBeVisible()
  expect(start).toBeEnabled()
  fireEvent.click(start)
  await waitFor(() => expect(api.put).toHaveBeenCalledWith('/issues/i-link', { status: 'processing', version: 4 }))
})

it('does not open another issue when the deep-link target is unavailable', async () => {
  render(<WorkerIssuesPage />, '/worker/issues?issue_id=private-issue')
  expect(await screen.findByText('问题不存在或无权访问')).toBeInTheDocument()
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(api.put).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '查看我的问题' }))
  await waitFor(() => expect(screen.queryByText('问题不存在或无权访问')).not.toBeInTheDocument())
})

it('distinguishes a failed load from an empty issue list and allows retry', async () => {
  vi.mocked(api.get).mockRejectedValueOnce(new Error('offline'))
  render(<WorkerIssuesPage />)
  expect(await screen.findByText('暂时无法加载问题和项目')).toBeInTheDocument()
  expect(screen.queryByText(/当前没有需要关注的问题/)).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '重新加载' }))
  expect(await screen.findByText(/当前没有需要关注的问题/)).toBeInTheDocument()
})

it('retains the report on failure and retries with the same idempotency key', async () => {
  vi.mocked(api.post).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ data: { id: 'i1' } })
  render(<WorkerIssuesPage />)
  fireEvent.click(await screen.findByRole('button', { name: /上报问题/ }))
  fireEvent.change(screen.getByLabelText('问题标题'), { target: { value: '3号车报警' } })
  fireEvent.click(screen.getByRole('button', { name: '提交上报' }))
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1))
  await waitFor(() => expect(screen.getByRole('button', { name: '提交上报' })).not.toHaveClass('ant-btn-loading'))
  expect(screen.getByLabelText('问题标题')).toHaveValue('3号车报警')
  fireEvent.click(screen.getByRole('button', { name: '提交上报' }))
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(2))
  const calls = vi.mocked(api.post).mock.calls
  expect(calls[0][0]).toBe('/projects/p1/issues')
  expect(calls[0][1]).toEqual(expect.objectContaining({ client_uuid: expect.any(String) }))
  expect(calls[1][1]).toEqual(calls[0][1])
})

it('keeps a successful submission successful when refreshing the list fails', async () => {
  vi.mocked(api.post).mockImplementation(async () => {
    vi.mocked(api.get).mockRejectedValue(new Error('refresh offline'))
    return { data: { id: 'i1' } }
  })
  render(<WorkerIssuesPage />)
  fireEvent.click(await screen.findByRole('button', { name: /上报问题/ }))
  fireEvent.change(screen.getByLabelText('问题标题'), { target: { value: '充电异常' } })
  fireEvent.click(screen.getByRole('button', { name: '提交上报' }))
  expect(await screen.findByText('暂时无法加载问题和项目')).toBeInTheDocument()
  expect(await screen.findByText('问题已上报')).toBeInTheDocument()
  expect(screen.queryByText(/未能确认上报结果/)).not.toBeInTheDocument()
  expect(api.post).toHaveBeenCalledTimes(1)
})

it('includes resolved issues and lets their reporter reopen them', async () => {
  vi.mocked(api.get).mockImplementation(async (url) => ({ data: url === '/projects' ? [] : { items: [{
    id: 'i-resolved', title: '复测未通过', severity: 'high', status: 'resolved', reporter_id: 'worker',
    project_status: 'acceptance', project_name: '现场项目', created_at: '2026-09-30', resolution: '已修复', source: 'project',
  }] } }) as any)
  vi.mocked(api.post).mockResolvedValue({ data: {} })
  render(<WorkerIssuesPage />)
  expect(await screen.findByText('0 项待处理')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button',{name:'查看全部问题'}))
  fireEvent.click(await screen.findByText('复测未通过'))
  fireEvent.click(await screen.findByRole('button', { name: '重新打开' }))
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/issues/i-resolved/reopen'))
  expect(api.get).toHaveBeenCalledWith('/dashboard/issues', { params: { include_closed: true } })
})

it('lets the assigned worker start and submit a result, keeping failed drafts', async () => {
  vi.mocked(api.get).mockImplementation(async (url) => ({ data: url === '/projects' ? [] : { items: [{
    id: 'i1', title: '修复避障', severity: 'high', status: 'open', reporter_id: 'other', assignee_id: 'worker',
    project_status: 'executing', project_name: '现场项目', created_at: '2026-09-30', version: 3,
  }] } }) as any)
  vi.mocked(api.put).mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ data: {} })
  render(<WorkerIssuesPage />)
  fireEvent.click(await screen.findByText('修复避障'))
  expect(screen.getByRole('button', { name: '开始处理' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '提交处理结果' }))
  fireEvent.change(screen.getByLabelText('处理措施与验证结果'), { target: { value: '更换传感器，复测通过' } })
  fireEvent.click(screen.getByRole('button', { name: '提交复核' }))
  await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1))
  expect(screen.getByLabelText('处理措施与验证结果')).toHaveValue('更换传感器，复测通过')
  await waitFor(() => expect(screen.getByRole('button', { name: '提交复核' })).not.toHaveClass('ant-btn-loading'))
  fireEvent.click(screen.getByRole('button', { name: '提交复核' }))
  await waitFor(() => expect(api.put).toHaveBeenLastCalledWith('/issues/i1', { status: 'resolved', resolution: '更换传感器，复测通过', version: 3 }))
})

it('explains PM restoration for a completed project without changing its state', async () => {
  vi.mocked(api.get).mockImplementation(async (url) => ({ data: url === '/projects' ? [] : { items: [{
    id: 'i1', title: '返工', severity: 'high', status: 'resolved', reporter_id: 'worker',
    project_status: 'completed', project_name: '现场项目', created_at: '2026-09-30',
  }] } }) as any)
  render(<WorkerIssuesPage />)
  fireEvent.click(await screen.findByRole('button',{name:'查看全部问题'}))
  fireEvent.click(await screen.findByText('返工'))
  expect(await screen.findByText(/先将项目恢复到验收中/)).toBeInTheDocument()
  expect(api.put).not.toHaveBeenCalled()
})

it.each(['open', 'resolved'])('keeps an unknown-state project issue readable without %s writes', async status => {
  vi.mocked(api.get).mockImplementation(async url => ({ data: url === '/projects'
    ? [{ id: 'p-unknown', name: '历史项目', status: 'legacy_unknown' }]
    : { items: [{ id: 'i-unknown', title: '历史问题', status, severity: 'medium', reporter_id: 'worker', assignee_id: 'worker', project_status: 'legacy_unknown', project_name: '历史项目', resolution: '历史处理说明' }] } }) as any)
  render(<WorkerIssuesPage />, '/worker/issues?issue_id=i-unknown')
  expect(await screen.findByText('项目存在未知历史状态，当前只读')).toBeInTheDocument()
  expect(screen.getByText(/原始状态：legacy_unknown/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /上报问题/ })).toBeDisabled()
  expect(screen.queryByRole('button', { name: '开始处理' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '提交处理结果' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '重新打开' })).not.toBeInTheDocument()
  expect(api.post).not.toHaveBeenCalled()
  expect(api.put).not.toHaveBeenCalled()
})

it('prefills the writable project rather than a read-only project when reporting', async () => {
  vi.mocked(api.get).mockImplementation(async url => ({ data: url === '/projects'
    ? [{ id: 'p-unknown', name: '历史项目', status: 'legacy_unknown' }, { id: 'p1', name: '现场项目', status: 'executing' }]
    : { items: [] } }) as any)
  vi.mocked(api.post).mockResolvedValue({ data: { id: 'new' } })
  render(<WorkerIssuesPage />)
  fireEvent.click(await screen.findByRole('button', { name: /上报问题/ }))
  fireEvent.change(screen.getByLabelText('问题标题'), { target: { value: '当前项目问题' } })
  fireEvent.click(screen.getByRole('button', { name: '提交上报' }))
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/projects/p1/issues', expect.objectContaining({ title: '当前项目问题' })))
})

it('explains why a read-only project cannot receive a new issue when its history is empty', async () => {
  vi.mocked(api.get).mockImplementation(async url => ({ data: url === '/projects'
    ? [{ id: 'p-unknown', name: '历史项目', status: 'legacy_unknown' }]
    : { items: [] } }) as any)
  render(<WorkerIssuesPage />)
  expect(await screen.findByText(/当前可见项目只读/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /上报问题/ })).toBeDisabled()
  expect(screen.queryByText(/可点击上报问题/)).not.toBeInTheDocument()
})

it('refreshes a conflicting issue without losing the resolution draft', async () => {
  const issue = { id: 'i1', title: '冲突问题', severity: 'high', status: 'processing', reporter_id: 'other', assignee_id: 'worker', project_status: 'executing', version: 1 }
  vi.mocked(api.get).mockImplementation(async (url) => ({ data: url === '/projects' ? [] : { items: [issue] } }) as any)
  vi.mocked(api.put).mockRejectedValueOnce({ response: { status: 409, data: { detail: '数据已更新' } } }).mockResolvedValue({ data: {} })
  render(<WorkerIssuesPage />)
  fireEvent.click(await screen.findByText('冲突问题'))
  fireEvent.click(screen.getByRole('button', { name: '提交处理结果' }))
  fireEvent.change(screen.getByLabelText('处理措施与验证结果'), { target: { value: '修复完成' } })
  fireEvent.click(screen.getByRole('button', { name: '提交复核' }))
  const refresh = await screen.findByRole('button', { name: '刷新并查看最新状态' })
  issue.version = 2
  fireEvent.click(refresh)
  await waitFor(() => expect(screen.getByRole('button', { name: '提交复核' })).not.toBeDisabled())
  expect(screen.getByLabelText('处理措施与验证结果')).toHaveValue('修复完成')
  fireEvent.click(screen.getByRole('button', { name: '提交复核' }))
  await waitFor(() => expect(api.put).toHaveBeenLastCalledWith('/issues/i1', { status: 'resolved', resolution: '修复完成', version: 2 }))
})

it('starts with unresolved issues and exposes reported history without changing scope permissions',async()=>{
 vi.mocked(api.get).mockImplementation(async url=>({data:url==='/projects'?[]:{items:[{id:'mine',title:'我报的已解决',reporter_id:'worker',status:'resolved',project_name:'现场',severity:'low'},{id:'assigned',title:'分给我处理',reporter_id:'other',assignee_id:'worker',status:'open',project_status:'executing',project_name:'现场',severity:'medium'}]}}) as any)
 render(<WorkerIssuesPage />)
 expect(await screen.findByRole('button',{name:'处理问题'})).toBeVisible()
 expect(screen.queryByText('我报的已解决')).toBeNull()
 fireEvent.click(screen.getByText('我上报的',{selector:'.ant-segmented-item-label'}))
 expect(screen.getByText('我报的已解决')).toBeInTheDocument()
 expect(screen.queryByText('分给我处理')).toBeNull()
 fireEvent.click(screen.getByText('全部',{selector:'.ant-segmented-item-label'}))
 expect(screen.getByText('分给我处理')).toBeInTheDocument()
})

it('sends the vehicle or device the field engineer names with the report', async () => {
  vi.mocked(api.get).mockImplementation(async (url) => ({ data: url === '/projects' ? [{ id: 'p1', name: '现场项目', status: 'executing' }]
    : url === '/projects/p1/vehicle-units' ? [{ id: 'u1', asset_code: 'AGV-003', fleet_no: '3号车' }] : { items: [] } }) as any)
  vi.mocked(api.post).mockResolvedValue({ data: { id: 'i1' } })
  render(<WorkerIssuesPage />)
  fireEvent.click(await screen.findByRole('button', { name: /上报问题/ }))
  fireEvent.change(screen.getByLabelText('问题标题'), { target: { value: '急停后无法复位' } })
  fireEvent.change(screen.getByLabelText('涉及车辆/设备（可选）'), { target: { value: '3号车 前防撞条' } })
  fireEvent.click(screen.getByRole('button', { name: '提交上报' }))
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/projects/p1/issues',
    expect.objectContaining({ title: '急停后无法复位', extra: expect.objectContaining({ device: '3号车 前防撞条' }) })))
})
