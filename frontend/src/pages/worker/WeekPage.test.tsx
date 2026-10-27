import { beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import WeekPage from './WeekPage'
import RecordsPage from './RecordsPage'
import { setOfflineAccount, getQueue } from '../../offline/queue'

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(), upload: vi.fn() }))
vi.mock('../../api/client', () => ({ api: { get: mocks.get, post: mocks.post, put: mocks.put, delete: mocks.del }, errMsg: () => '业务拒绝' }))
vi.mock('../../stores/auth', () => ({ useAuth: () => ({ user: { id: 'worker-1', role: 'worker', permission_overrides: { 'project.read': true, 'worker.report': true, 'worker.deliver': true, 'worker.issues': true, 'personal.records.read': true } } }) }))
vi.mock('../../offline/useOfflineSync', () => ({ useOfflineSync: () => ({ online: navigator.onLine, pendingCount: 0, rejected: [], syncVersion: 0, flush: vi.fn(), retry: vi.fn(), remove: vi.fn() }) }))
vi.mock('../../api/projectDocuments', () => ({ projectDocumentsApi: { upload: mocks.upload } }))
const plan = { id: 'cell-1', project_id: 'project-1', project_name: '项目甲', task_id: 'work-1', version: 4, week_start: '2026-10-26', mode: 'finish', scope: {}, assignee_ids: ['worker-1'], assignees: [{ id: 'worker-1', name: '本人' }], date_window: { earliest: '2026-10-19', latest: '2026-10-27', timezone: 'Asia/Shanghai' }, work_item: { id: 'work-1', name: '现场网络核对', kind: 'other', version: 2, is_completed: false, phase_name: '现场工作', check_items: [] } }
const base = { state: 'ready', plans: [plan], unassigned: [], assistable: [], vehicle_matrices: {}, this_week_documents: [], my_issues: [], windows: {}, warnings: [], permissions: { record: true, upload: true, issues: true } }
const draw = () => render(<MemoryRouter><WeekPage /></MemoryRouter>)
beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); setOfflineAccount('worker-1'); vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true); mocks.get.mockResolvedValue({ data: base }); mocks.post.mockResolvedValue({ data: {} }); mocks.upload.mockResolvedValue({}) })

it('读取周事实，不读取旧按日安排', async () => {
  draw(); expect(await screen.findByText('现场网络核对')).toBeInTheDocument()
  expect(mocks.get).toHaveBeenCalledWith('/worker/week', { params: {}, headers: { 'X-AGV-Expected-Account': 'worker-1' } })
  expect(mocks.get.mock.calls.every(([path]) => path !== '/worker/today')).toBe(true)
})

it('提交明确完成日期、理由和版本，不由客户端指定实际操作人', async () => {
  draw(); fireEvent.click(await screen.findByRole('button', { name: '登记实际完成' }))
  fireEvent.change(screen.getByLabelText('实际情况 / 修订理由'), { target: { value: '现场核实已完成' } })
  fireEvent.click(screen.getByRole('button', { name: '保存实际记录' }))
  await waitFor(() => expect(mocks.post).toHaveBeenCalledWith('/worker/operations', expect.objectContaining({ weekly_cell_id: 'cell-1', version: 2, completion_date: '2026-10-27', reason: '现场核实已完成', client_uuid: expect.any(String) }), { headers: { 'X-AGV-Expected-Account': 'worker-1' } }))
  expect(mocks.post.mock.calls[0][1]).not.toHaveProperty('actor_id')
})

it('离线勾选保留原UUID和payload，不发送完成请求', async () => {
  vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false); draw()
  fireEvent.click(await screen.findByRole('button', { name: '登记实际完成' }))
  fireEvent.change(screen.getByLabelText('实际情况 / 修订理由'), { target: { value: '离线核对后登记' } })
  fireEvent.click(screen.getByRole('button', { name: '保存实际记录' }))
  await waitFor(() => expect(getQueue()).toHaveLength(1))
  expect(getQueue()[0]).toMatchObject({ type: 'field', payload: { completion_date: '2026-10-27', version: 2, reason: '离线核对后登记' } })
  expect(mocks.post).not.toHaveBeenCalled()
})

it('读页面不静默认领，明确点击才写入', async () => {
  mocks.get.mockResolvedValue({ data: { ...base, plans: [], unassigned: [{ ...plan, assignee_ids: [], assignees: [] }] } }); draw()
  const button = await screen.findByRole('button', { name: /认\s*领/ }); expect(mocks.post).not.toHaveBeenCalled(); fireEvent.click(button)
  await waitFor(() => expect(mocks.post).toHaveBeenCalledWith('/projects/project-1/weekly-plans/cell-1/claim', { version: 4 }, { headers: { 'X-AGV-Expected-Account': 'worker-1' } }))
})

it('未知计划保持未知状态', async () => {
  mocks.get.mockResolvedValue({ data: { ...base, state: 'unavailable', plans: [], warnings: [{ project_id: 'project-1', message: '周计划尚未读取' }] } }); draw()
  expect(await screen.findByText('周计划尚未读取')).toBeInTheDocument(); expect(screen.queryByText('本周没有已发布给我的工作')).not.toBeInTheDocument()
})

it('资料上传携带精确期次ID到断点队列', async () => {
  mocks.get.mockResolvedValue({ data: { ...base, this_week_documents: [{ document_id: 'document-week-1', project_id: 'project-1', project_name: '项目甲', code: '6.2', name: '本周生命周期表', due_at: null, timezone: 'Asia/Shanghai' }] } }); draw()
  fireEvent.click(await screen.findByRole('button', { name: '上传当期资料' }))
  const file = new File(['record'], '周表.xlsx'); fireEvent.change(document.querySelector('input[type="file"]')!, { target: { files: [file] } })
  fireEvent.click(screen.getByRole('button', { name: '保存上传任务' }))
  await waitFor(() => expect(mocks.upload).toHaveBeenCalledWith('project-1', { file, documentIds: ['document-week-1'] }))
})

it('本人记录分别展示完成日期、登记时间和协助对象', async () => {
  mocks.get.mockResolvedValue({ data: { records: [{ id: 'r1', project_id: 'project-1', project_name: '项目甲', kind: 'work', target_id: 'work-1', target_name: '现场网络核对', step_key: '', completion_date: '2026-10-25', recorded_at: '2026-10-27T03:00:00Z', actor_name: '本人', assisted_user_name: '同事乙', is_done: true, note: '原始附注', action: 'record', version: 1, can_edit: true, can_retract: true, earliest: '2026-10-19', latest: '2026-10-27', timezone: 'Asia/Shanghai' }] } })
  render(<MemoryRouter><RecordsPage /></MemoryRouter>)
  expect(await screen.findByText('完成日期 2026-10-25')).toBeInTheDocument()
  expect(screen.getByText(/登记时间 2026-10-27T03:00:00Z/)).toHaveTextContent('协助 同事乙')
  expect(screen.getByRole('button', { name: /撤\s*回/ })).toBeInTheDocument()
})

it('按真实周计划范围显示逐车检查与统一完成事实', async () => {
  mocks.get.mockResolvedValue({ data: { ...base, plans: [{ ...plan, vehicle_step_key: 'arrival_inspection', scope: { vehicle_unit_ids: ['car-a'] }, completion: { state: 'planned', completed_count: 0, required_count: 1, quantity_unknown: false, is_complete: false }, work_item: { ...plan.work_item, kind: 'vehicle', vehicle_step_key: 'arrival_inspection', check_items: [{ id: 'check-a', name: '范围内检查', vehicle_unit_id: 'car-a', version: 0, is_done: false, is_applicable: true }, { id: 'check-b', name: '其它批次检查', vehicle_unit_id: 'car-b', version: 0, is_done: false, is_applicable: true }] } }], vehicle_matrices: { 'project-1': { steps: [{ key: 'arrival_inspection', name: '到场点检', source_task_id: 'work-1' }], units: [{ id: 'car-a', asset_code: 'AGV-A', cells: {} }, { id: 'car-b', asset_code: 'AGV-B', cells: {} }] } } } }); draw()
  expect(await screen.findByText('范围内检查')).toBeInTheDocument()
  expect(screen.queryByText('其它批次检查')).not.toBeInTheDocument()
  expect(screen.getByText('当前完成 0 / 累计计划 1')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /AGV-A/ })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /AGV-B/ })).not.toBeInTheDocument()
})
