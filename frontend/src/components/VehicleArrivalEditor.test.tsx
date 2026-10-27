import { beforeEach, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
const { put } = vi.hoisted(() => ({ put: vi.fn() }))
vi.mock('../api/client', () => ({ api: { put }, errMsg: () => '登记失败' }))
import VehicleArrivalEditor from './VehicleArrivalEditor'

const project = { id: 'p1', timezone: 'Asia/Shanghai' } as any
const units = [{ id: 'u1', asset_code: 'AGV-001', arrived_at: '2026-10-01' }, { id: 'u2', asset_code: 'AGV-002' }]
beforeEach(() => { vi.clearAllMocks(); put.mockResolvedValue({ data: {} }) })

it('registers the selected fleet together using a calendar date', async () => {
  const saved = vi.fn()
  render(<VehicleArrivalEditor project={project} units={units} onSaved={saved} />)
  fireEvent.click(screen.getByRole('button', { name: '批量登记到场' }))
  fireEvent.click(screen.getByRole('button', { name: '选择全部已建档车辆' }))
  fireEvent.click(screen.getByRole('button', { name: '保存到场日期' }))
  await waitFor(() => expect(put).toHaveBeenCalledOnce())
  expect(put).toHaveBeenCalledWith('/projects/p1/vehicle-arrivals', expect.objectContaining({ unit_ids: ['u1', 'u2'], arrived_at: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/) }))
  await waitFor(() => expect(saved).toHaveBeenCalledOnce())
})

it('requires a reason before clearing dates and prevents duplicate submissions', async () => {
  let resolve!: (value: any) => void
  put.mockImplementation(() => new Promise(done => { resolve = done }))
  render(<VehicleArrivalEditor project={project} units={units} onSaved={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: '批量登记到场' }))
  fireEvent.click(screen.getByLabelText('清除误登记'))
  fireEvent.click(screen.getByRole('button', { name: '选择全部已建档车辆' }))
  const save = screen.getByRole('button', { name: '保存到场日期' })
  fireEvent.click(save)
  expect(await screen.findByText('请填写清除理由')).toBeInTheDocument()
  expect(put).not.toHaveBeenCalled()
  fireEvent.change(screen.getByLabelText('清除理由'), { target: { value: '到场误登记' } })
  fireEvent.click(save); fireEvent.click(save)
  await waitFor(() => expect(put).toHaveBeenCalledOnce())
  expect(put).toHaveBeenCalledWith('/projects/p1/vehicle-arrivals', { unit_ids: ['u1', 'u2'], arrived_at: null, reason: '到场误登记' })
  await act(async () => { resolve({ data: {} }) })
})
