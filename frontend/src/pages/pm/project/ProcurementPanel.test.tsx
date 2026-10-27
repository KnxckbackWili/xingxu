import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import { beforeEach, expect, it, vi } from 'vitest'
import { ProjectCapabilitiesContext, ProjectStatusContext } from '../../../hooks/useProjectCapability'
const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() }))
vi.mock('../../../api/client', () => ({ api: { get: h.get, post: h.post, put: h.put, delete: h.del }, errMsg: (e: any) => e?.response?.data?.detail ?? e.message ?? '失败' }))
import ProcurementPanel from './ProcurementPanel'
const item = { id: 'i1', name: '调度服务器', status: 'pending', owner_id: 'u1', owner_party: 'production', owner_name: '内部跟进人', required_date: '2026-09-01', committed_date: null, forecast_date: null, actual_date: null, is_required: false, risk: 'low', note: '', extra: { quantity: 3, unit: '台', spec: '原规格', order_status: '已到货', unknown_legacy: '保留历史字段' } }
function show(can = true) { return render(<ConfigProvider theme={{ token: { motion: false } }}><ProjectStatusContext.Provider value="executing"><ProjectCapabilitiesContext.Provider value={can ? ['project.manage_plan'] : []}><ProcurementPanel projectId="p1" /></ProjectCapabilitiesContext.Provider></ProjectStatusContext.Provider></ConfigProvider>) }
beforeEach(() => { vi.resetAllMocks(); h.get.mockImplementation(async (url: string) => ({ data: url.endsWith('/people') ? [{ id: 'u1', display_name: '内部跟进人' }] : url.startsWith('/templates/') ? [{ id: 'c1', name: '无线AP', spec: '防水', unit: '台' }] : { items: [item], summary: { total: 999 } } })); h.put.mockResolvedValue({}); h.post.mockResolvedValue({}) })
it('keeps arrived-but-pending procurement visible and patches only changed detail without discarding legacy metadata', async () => {
  show(); expect(await screen.findByText('调度服务器')).toBeVisible(); expect(screen.getByText('待确认')).toBeVisible(); expect(screen.getByText('已到货')).toBeVisible(); expect(screen.queryByText('999')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: /编\s*辑/ })); const modal = within(await screen.findByRole('dialog'))
  fireEvent.change(modal.getByLabelText('规格'), { target: { value: '新防水规格' } }); fireEvent.click(modal.getByRole('button', { name: '保存采购' }))
  await waitFor(() => expect(h.put).toHaveBeenCalledExactlyOnceWith('/projects/p1/procurements/i1', { extra: { spec: '新防水规格' } }))
})
it('keeps a failed edit open with its original draft and does not duplicate an in-flight save', async () => {
  let fail: (reason: unknown) => void = () => {}; h.put.mockImplementationOnce(() => new Promise((_resolve, reject) => { fail = reject }))
  show(); fireEvent.click(await screen.findByRole('button', { name: /编\s*辑/ })); const modal = within(await screen.findByRole('dialog'))
  fireEvent.change(modal.getByLabelText('规格'), { target: { value: '保留的填写' } }); const save = modal.getByRole('button', { name: '保存采购' }); fireEvent.click(save); fireEvent.click(save)
  await waitFor(() => expect(h.put).toHaveBeenCalledTimes(1)); await act(async () => fail(new Error('采购保存失败')))
  await waitFor(() => expect(modal.getByText('采购保存失败')).toBeVisible()); expect(modal.getByLabelText('规格')).toHaveValue('保留的填写')
})
it('imports selected catalog items with explicit quantities', async () => {
  show(); fireEvent.click(await screen.findByRole('button', { name: '从采购库带入' })); const modal = within(await screen.findByRole('dialog'))
  await modal.findByText('无线AP'); fireEvent.change(modal.getByLabelText('无线AP带入数量'), { target: { value: '12' } }); fireEvent.click(modal.getAllByRole('checkbox')[1]); fireEvent.click(modal.getByRole('button', { name: '带入所选采购' }))
  await waitFor(() => expect(h.post).toHaveBeenCalledWith('/projects/p1/procurements/import', { items: [{ item_id: 'c1', quantity: 12 }] }))
})
it('initial load failure remains visible and can recover without fake empty success', async () => {
  h.get.mockRejectedValueOnce(new Error('采购清单离线')); show(); expect(await screen.findByText('采购清单离线')).toBeVisible(); expect(screen.getByRole('button', { name: '新增采购项' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: '重新加载后重试' })); expect(await screen.findByText('调度服务器')).toBeVisible()
})
it('read-only members retain specification and internal follower but have no procurement writes', async () => {
  show(false); expect(await screen.findByText('原规格')).toBeVisible(); expect(screen.getByText('内部跟进人')).toBeVisible(); expect(screen.queryByRole('button', { name: /编\s*辑|删\s*除|新增采购项|从采购库带入/ })).toBeNull()
})
