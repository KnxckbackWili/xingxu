import { ConfigProvider } from 'antd'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import VehicleChecksPanel from './VehicleChecksPanel'
const h = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), post: vi.fn(), auth: { user: { id: 'pm', role: 'pm', permission_overrides: {} as Record<string, boolean> } } }))
vi.mock('../stores/auth', () => ({ useAuth: () => h.auth }))
vi.mock('../api/client', () => ({ api: h, errMsg: (e: any) => e.response?.data?.detail || '请求未确认' }))
const row = (extra = {}) => ({ id: 'ci-real-1', task_id: 'task-1', task_name: '急停工作', task_version: 8, vehicle_unit_id: 'real-u1', vehicle_step_key: 'arrival_inspection', scope: 'vehicle', name: '急停检查', is_required: true, is_safety_critical: true, is_applicable: true, is_done: false, failed: false, version: 4, ...extra })
const props = { projectId: 'p1', unitId: 'real-u1', unitLabel: 'AGV-001', stepKey: 'arrival_inspection', steps: [{ key: 'arrival_inspection', name: '到场点检' }], canManage: true, onChanged: vi.fn() }
const show = (extra = {}) => render(<ConfigProvider theme={{ token: { motion: false } }}><VehicleChecksPanel {...props} {...extra} /></ConfigProvider>)
beforeEach(() => { vi.clearAllMocks(); h.auth.user.permission_overrides = {}; h.get.mockResolvedValue({ data: { items: [row()], can_record: true } }); h.put.mockResolvedValue({ data: {} }); h.post.mockResolvedValue({ data: { created: 1 } }) })
it('reads exact real vehicle/step and distinguishes original task-level facts', async () => {
  h.get.mockResolvedValue({ data: { items: [row(), row({ id: 'legacy', scope: 'legacy_task', vehicle_unit_id: null, is_done: true })], can_record: true } })
  show(); expect(await screen.findByText('本车检查')).toBeVisible()
  expect(screen.getByText('历史任务级（未逐车核验）')).toBeVisible()
  expect(h.get).toHaveBeenCalledExactlyOnceWith('/projects/p1/vehicle-units/real-u1/checks', { params: { step_key: 'arrival_inspection' } })
  expect(screen.queryByRole('button', { name: '不适用' })).not.toBeInTheDocument()
})
it('saves the same check version once despite rapid confirmation', async () => {
  let finish: () => void = () => undefined
  h.put.mockImplementation(() => new Promise<void>(resolve => { finish = resolve }))
  show(); fireEvent.click(await screen.findByRole('button', { name: '确认通过' }))
  const confirm = within(screen.getByRole('dialog')).getByRole('button', { name: '保存检查' })
  fireEvent.click(confirm); fireEvent.click(confirm)
  await waitFor(() => expect(h.put).toHaveBeenCalledExactlyOnceWith('/projects/p1/check-items/ci-real-1', { version: 4, is_done: true, failed: false, is_applicable: true }))
  await act(async () => { finish() })
})
it('keeps a failed reason after conflict and does not replay automatically', async () => {
  h.put.mockRejectedValue({ response: { status: 409, data: { detail: '版本已变化，请刷新核对' } } })
  show(); fireEvent.click(await screen.findByRole('button', { name: '不通过' }))
  const dialog = within(screen.getByRole('dialog')); expect(dialog.getByRole('button', { name: '保存检查' })).toBeDisabled()
  fireEvent.change(screen.getByLabelText('车辆检查原因'), { target: { value: '急停信号未释放' } })
  fireEvent.click(dialog.getByRole('button', { name: '保存检查' }))
  expect(await screen.findByText('版本已变化，请刷新核对')).toBeVisible()
  expect(screen.getByLabelText('车辆检查原因')).toHaveValue('急停信号未释放')
  expect(h.put).toHaveBeenCalledTimes(1)
  expect(h.get).toHaveBeenCalledTimes(1)
})
it('new review is explicit for this actual unit and preserves legacy facts', async () => {
  h.get.mockResolvedValue({ data: { items: [row({ scope: 'legacy_task', vehicle_unit_id: null, is_done: true })], can_record: true } })
  show(); fireEvent.click(await screen.findByRole('button', { name: '为本车生成复核：急停工作' }))
  fireEvent.change(screen.getByLabelText('车辆检查原因'), { target: { value: '车号逐台复核' } })
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '保存检查' }))
  await waitFor(() => expect(h.post).toHaveBeenCalledExactlyOnceWith('/projects/p1/tasks/task-1/vehicle-checks/generate', { vehicle_unit_ids: ['real-u1'], reason: '车号逐台复核' }))
  expect(h.put).not.toHaveBeenCalled()
})
it('read-only eligibility hides check actions and stale previous vehicle never replaces current', async () => {
  let old: (value: unknown) => void = () => undefined
  h.get.mockImplementationOnce(() => new Promise(resolve => { old = resolve })).mockResolvedValue({ data: { items: [row({ name: '第二台车检查' })], can_record: false } })
  const view = show({ canManage: false })
  view.rerender(<VehicleChecksPanel {...props} unitId="real-u2" unitLabel="AGV-002" canManage={false} />)
  expect(await screen.findByText('第二台车检查')).toBeVisible()
  await act(async () => { old({ data: { items: [row({ name: '迟到旧车检查' })], can_record: true } }) })
  expect(screen.queryByText('迟到旧车检查')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '确认通过' })).not.toBeInTheDocument()
})

it('revoked reporting permission closes write eligibility while preserving readable evidence', async () => {
  h.auth.user.permission_overrides = { 'worker.report': false }
  show({ canManage: false })
  expect(await screen.findByText('本车检查')).toBeVisible()
  expect(screen.queryByRole('button', { name: '确认通过' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '不通过' })).not.toBeInTheDocument()
})
