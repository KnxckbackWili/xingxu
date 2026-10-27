import { ConfigProvider } from 'antd'
import { beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import VehicleProgressMatrix from './VehicleProgressMatrix'
const { get, put } = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }))
vi.mock('../api/client', () => ({ api: { get, put }, errMsg: (e: any) => e.response?.data?.detail || e.message }))
const fixture = (extra = {}) => ({ steps: [{ key: 'arrival_inspection', name: '到场点检' }], units: [{ id: 'real-u1', asset_code: 'AGV-001', fleet_no: '现场01', vehicle_type: '潜伏式', model_name: 'Q1', cells: {} }], can_record: true, legacy: [], migration_warnings: [], summary: { completed: 0, target: 25, percent: 0, quantity_unknown: false, unregistered_quantity: 24 }, ...extra })
beforeEach(() => { vi.clearAllMocks(); get.mockResolvedValue({ data: fixture() }); put.mockResolvedValue({ data: fixture() }) })
it('shows incomplete responses as retryable without inventing an empty fleet', async () => {
  get.mockResolvedValueOnce({ data: [] })
  render(<VehicleProgressMatrix projectId="p1" status="executing" />)
  expect(await screen.findByText('车辆进度响应不完整，请重试读取')).toBeVisible()
  expect(screen.queryByText(/尚无真实车辆档案/)).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '刷新核对' }))
  expect(await screen.findByRole('button', { name: 'AGV-001 到场点检 勾选完成' })).toBeVisible()
})
it('sends the real vehicle id and expected cell version, protects rapid duplicates', async () => {
  let resolve: () => void = () => undefined
  put.mockImplementation(() => new Promise<void>(r => { resolve = r }))
  render(<VehicleProgressMatrix projectId="p1" status="executing" />)
  fireEvent.click(await screen.findByRole('button', { name: 'AGV-001 到场点检 勾选完成' }))
  const confirm = within(screen.getByRole('dialog')).getByRole('button', { name: /确.*认/ })
  fireEvent.click(confirm); fireEvent.click(confirm)
  await waitFor(() => expect(put).toHaveBeenCalledTimes(1))
  expect(put).toHaveBeenCalledWith('/projects/p1/vehicle-progress', expect.objectContaining({ is_done: true, cells: [{ vehicle_unit_id: 'real-u1', step_key: 'arrival_inspection', version: 0 }] }))
  resolve()
})
it('requires a reason before canceling an already completed cell', async () => {
  get.mockResolvedValue({ data: fixture({ units: [{ id: 'real-u1', asset_code: 'AGV-001', vehicle_type: '潜伏式', cells: { arrival_inspection: { is_done: true, done_on: '2026-10-20', version: 4 } } }] }) })
  render(<VehicleProgressMatrix projectId="p1" status="executing" />)
  fireEvent.click(await screen.findByRole('button', { name: 'AGV-001 到场点检 取消完成' }))
  const dialog = screen.getByRole('dialog'); const confirm = within(dialog).getByRole('button', { name: /确.*认/ })
  expect(confirm).toBeDisabled()
  fireEvent.change(screen.getByLabelText('取消完成理由'), { target: { value: '现场复测尚未通过' } })
  fireEvent.click(confirm)
  await waitFor(() => expect(put).toHaveBeenCalledWith('/projects/p1/vehicle-progress', expect.objectContaining({ is_done: false, reason: '现场复测尚未通过', cells: [{ vehicle_unit_id: 'real-u1', step_key: 'arrival_inspection', version: 4 }] })))
})
it('keeps migration identities unknown and displays source quantities without inventing rows', async () => {
  get.mockResolvedValue({ data: fixture({ units: [], legacy: [{ step_key: 'arrival_inspection', total_count: 3, unassigned_count: 3, source_metadata: { target_quantity: 5.2, completed_quantity: 2.7 } }], migration_warnings: ['已完成（迁移，车号未知）：尚未逐台核对'] }) })
  render(<VehicleProgressMatrix projectId="p1" status="executing" />)
  expect(await screen.findByText(/3 台待核对/)).toBeVisible()
  expect(screen.getByText(/尚无真实车辆档案/)).toBeVisible()
  expect(screen.queryByRole('button', { name: /AGV-.*勾选完成/ })).not.toBeInTheDocument()
})
it('pre-entry remains read-only even if an old response says recording is allowed', async () => {
  render(<VehicleProgressMatrix projectId="p1" status="ready" />)
  expect(await screen.findByRole('button', { name: 'AGV-001 到场点检 勾选完成' })).toBeDisabled()
  expect(screen.queryByRole('button', { name: '批量勾选' })).not.toBeInTheDocument()
})
it('does not let a late previous project response overwrite the current project', async () => {
  let old: (v: any) => void = () => undefined
  get.mockImplementation((url: string) => url.includes('p1') ? new Promise(r => { old = r }) : Promise.resolve({ data: fixture({ units: [] }) }))
  const { rerender } = render(<VehicleProgressMatrix projectId="p1" status="executing" />)
  rerender(<VehicleProgressMatrix projectId="p2" status="executing" />)
  await screen.findByText(/尚无真实车辆档案/)
  old({ data: fixture() })
  await waitFor(() => expect(screen.queryByText('现场01')).not.toBeInTheDocument())
})
it('clarifies an unknown historical target with the previous value and an audit reason', async () => {
  get.mockResolvedValue({ data: fixture({ can_manage: true, steps: [{ key: 'legacy_task', name: '历史环节：原单车检查', source_task_id: 'task', expected_quantity: null }], legacy: [{ step_key: 'legacy_task', total_count: 0, unassigned_count: 0, source_metadata: { target_quantity: null, completed_quantity: 0 } }], units: [] }) })
  render(<VehicleProgressMatrix projectId="p1" status="executing" />)
  const summary = await screen.findByText(/0 台待核对/)
  fireEvent.click(summary)
  fireEvent.click(screen.getByRole('button', { name: /核对应完成台数/ }))
  fireEvent.change(screen.getByRole('spinbutton', { name: '历史环节应完成台数' }), { target: { value: '25' } })
  fireEvent.change(screen.getByLabelText('核对台数理由'), { target: { value: '按原交付清单核对25台' } })
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /确.*认/ }))
  await waitFor(() => expect(put).toHaveBeenCalledWith('/projects/p1/vehicle-progress/steps/legacy_task', { expected_quantity: 25, previous_quantity: null, reason: '按原交付清单核对25台' }))
})
it('shows portable execution as an inspectable read-only source, without changing current progress', async () => {
  get.mockImplementation((url: string) => Promise.resolve({ data: url.endsWith('/source')
    ? { read_only: true, verified: false, source: { legacy_quantity_reports: [{ completed_quantity: 1000, client_uuid: '原项目真实登记', user_id: '原操作者' }] } }
    : fixture({ source_snapshot_available: true }) }))
  render(<ConfigProvider theme={{ token: { motion: false } }}><VehicleProgressMatrix projectId="p1" status="ready" /></ConfigProvider>)
  fireEvent.click(await screen.findByRole('button', { name: '查阅原始来源' }))
  await waitFor(() => expect(screen.getByText(/原项目真实登记/)).toBeVisible())
  expect(screen.getByText(/不计入本项目完成资格/)).toBeVisible()
  expect(put).not.toHaveBeenCalled()
})

it('shows the exact car and check blocker after an atomic batch refusal', async () => {
  put.mockRejectedValue({ response: { data: { detail: { message: '车辆检查未满足', blockers: [{ vehicle_unit_id: 'real-u1', vehicle_label: '现场01', name: '急停检查', reason: '安全关键检查须真实通过' }] } } } })
  render(<ConfigProvider theme={{ token: { motion: false } }}><VehicleProgressMatrix projectId="p1" status="executing" /></ConfigProvider>)
  fireEvent.click(await screen.findByRole('button', { name: 'AGV-001 到场点检 勾选完成' }))
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /确.*认/ }))
  expect(await screen.findByText(/现场01 · 急停检查：安全关键检查须真实通过/)).toBeVisible()
  await waitFor(() => expect(screen.getByRole('dialog')).toBeVisible())
})
