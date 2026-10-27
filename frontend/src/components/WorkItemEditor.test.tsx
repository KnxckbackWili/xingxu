import { setOfflineAccount } from '../offline/queue'
import { ConfigProvider } from 'antd'
import type { ReactNode } from 'react'
import { beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render as rtlRender, screen, waitFor } from '@testing-library/react'
import WorkItemEditor from './WorkItemEditor'
import { work, catalog } from '../test/workItems'
function render(ui: ReactNode) { return rtlRender(ui, { wrapper: ({ children }) => <ConfigProvider theme={{ token: { motion: false } }}>{children}</ConfigProvider> }) }

const { put, post } = vi.hoisted(() => ({ put: vi.fn(), post: vi.fn() }))
vi.mock('../api/client', () => ({ api: { put, post }, errMsg: () => '保存被拒绝' }))
vi.mock('../hooks/useVehicleTypes', () => ({ useVehicleTypes: () => ({ options: [] }) }))
vi.mock('../stores/auth', () => ({ useAuth: () => ({ user: { id: 'u', role: 'pm' } }) }))
beforeEach(() => { setOfflineAccount('u'); put.mockReset().mockResolvedValue({ data: {} }); post.mockReset().mockResolvedValue({ data: {} }) })
const props = () => ({ open: true, projectId: 'p', phases: catalog().phases, steps: [{ key: 'arrival', name: '到场检查' }], onClose: vi.fn(), onSaved: vi.fn() })
it('edits description and group without target/module writes and retains a real vehicle step', async () => {
  const p = props(); render(<WorkItemEditor {...p} item={work({ kind: 'vehicle', vehicle_step_key: 'arrival' })} />)
  fireEvent.change(screen.getByLabelText('工作说明'), { target: { value: '修订说明' } }); fireEvent.click(screen.getByRole('button', { name: '保存工作项' }))
  await waitFor(() => expect(p.onSaved).toHaveBeenCalledOnce())
  expect(put).toHaveBeenCalledWith('/projects/p/work-items/w1', { name: '现场验证', description: '修订说明', phase_id: 'ph1', group_label: '原模块标签', vehicle_step_key: 'arrival', version: 7 })
  expect(screen.queryByRole('spinbutton')).toBeNull()
})
it('keeps the draft on rejection and when edit authority is revoked', async () => {
  put.mockRejectedValue(new Error('blocked')); const p = props(); const v = render(<WorkItemEditor {...p} item={work()} />)
  fireEvent.change(screen.getByLabelText('工作项名称'), { target: { value: '保留的新名称' } }); fireEvent.click(screen.getByRole('button', { name: '保存工作项' }))
  await waitFor(() => expect(screen.getByText('保存被拒绝')).toBeVisible()); expect(screen.getByLabelText('工作项名称')).toHaveValue('保留的新名称')
  v.rerender(<WorkItemEditor {...p} canEdit={false} item={work()} />); expect(screen.getByRole('button', { name: '保存工作项' })).toBeDisabled(); expect(screen.getByLabelText('工作项名称')).toHaveValue('保留的新名称')
})
it('creates a non-vehicle work item without a module or quantity and with check definitions only', async () => {
  const p = props(); render(<WorkItemEditor {...p} />); fireEvent.change(screen.getByLabelText('工作项名称'), { target: { value: '现场清点' } }); fireEvent.click(screen.getByRole('button', { name: '保存工作项' }))
  await waitFor(() => expect(post).toHaveBeenCalledOnce()); expect(post.mock.calls[0][1]).toEqual({ phase_id: 'ph1', name: '现场清点', kind: 'other', description: '', group_label: '', vehicle_step_key: null, applicable_vehicle_types: [], scope_conditions: [], checks: [] })
})
