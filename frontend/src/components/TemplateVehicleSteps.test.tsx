import { beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import TemplateVehicleSteps from './TemplateVehicleSteps'
const { get, put } = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }))
vi.mock('../api/client', () => ({ api: { get, put }, errMsg: () => '读取失败' }))
beforeEach(() => { vi.clearAllMocks(); get.mockResolvedValue({ data: [{ key: 'arrival', name: '到场点检' }, { key: 'run', name: '上线运行' }] }); put.mockResolvedValue({ data: [] }) })
it('preserves stable keys while editing and ordering names for future projects', async () => {
  render(<TemplateVehicleSteps templateId="default" canManage />)
  const input = await screen.findByLabelText('车辆环节1名称')
  fireEvent.change(input, { target: { value: '到场核对' } })
  fireEvent.click(screen.getAllByRole('button', { name: /上.*移/ })[1])
  fireEvent.click(screen.getByRole('button', { name: '保存车辆环节' }))
  await waitFor(() => expect(put).toHaveBeenCalledWith('/templates/default/vehicle-steps', { steps: [{ key: 'run', name: '上线运行' }, { key: 'arrival', name: '到场核对' }] }))
})
it('readers cannot edit definitions', async () => {
  render(<TemplateVehicleSteps templateId="custom" canManage={false} />)
  expect(await screen.findByLabelText('车辆环节1名称')).toBeDisabled()
  expect(screen.queryByRole('button', { name: '保存车辆环节' })).not.toBeInTheDocument()
})
it('keeps edited step names available for retry after a failed save', async () => {
  put.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ data: [] })
  render(<TemplateVehicleSteps templateId="default" canManage />)
  fireEvent.change(await screen.findByLabelText('车辆环节1名称'), { target: { value: '保留修改后的点检' } })
  fireEvent.click(screen.getByRole('button', { name: '保存车辆环节' }))
  await screen.findByText('读取失败')
  fireEvent.click(await screen.findByRole('button', { name: /保存车辆环节$/ }))
  await waitFor(() => expect(put).toHaveBeenCalledTimes(2))
  expect(put.mock.calls[1][1]).toEqual(put.mock.calls[0][1])
})
