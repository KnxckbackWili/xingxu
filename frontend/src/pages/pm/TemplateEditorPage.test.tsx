import { setOfflineAccount } from '../../offline/queue'
import { beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { catalog, work } from '../../test/workItems'
import TemplateEditorPage from './TemplateEditorPage'
const { get, put, auth } = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), auth: { user: { id: 'admin', role: 'admin' } as any } }))
vi.mock('../../api/client', () => ({ api: { get, put, post: vi.fn(), delete: vi.fn() }, errMsg: () => '保存失败' }))
vi.mock('../../stores/auth', () => ({ useAuth: () => auth }))
vi.mock('../../hooks/useVehicleTypes', () => ({ useVehicleTypes: () => ({ options: [] }) }))
vi.mock('./TemplateDocumentsTab', () => ({ default: () => <div>资料要求保留</div> }))
vi.mock('./TemplateProcurementsTab', () => ({ default: () => null }))
vi.mock('../../components/TemplateVehicleSteps', () => ({ default: () => null }))
beforeEach(() => { setOfflineAccount('admin');
  auth.user = { id: 'admin', role: 'admin' }; get.mockReset(); put.mockReset().mockResolvedValue({ data: {} })
  get.mockImplementation(async (url: string) => ({ data: url === '/templates' ? [{ id: 'default', name: '系统模板', is_system: true }] : url.endsWith('/work-items') ? catalog().phases && { phases: catalog().phases } : url.endsWith('/vehicle-steps') ? [] : [] }))
})
it('edits one work item without replacing unrelated work or quantities', async () => {
  render(<TemplateEditorPage />); await screen.findByText('现场验证'); fireEvent.click(screen.getByRole('button', { name: '编辑工作项' })); fireEvent.change(screen.getByLabelText('工作项名称'), { target: { value: '修订名称' } }); fireEvent.click(screen.getByRole('button', { name: '保存工作项' }))
  await waitFor(() => expect(put).toHaveBeenCalledOnce()); expect(put.mock.calls[0][0]).toBe('/templates/default/work-items/w1'); expect(put.mock.calls[0][1]).toMatchObject({ name: '修订名称', version: 7 }); expect(put.mock.calls[0][1]).not.toHaveProperty('target_quantity'); expect(put.mock.calls[0][1]).not.toHaveProperty('modules')
})
it('blocks editing after a failed load and supports retry', async () => {
  get.mockRejectedValueOnce(new Error('down')); render(<TemplateEditorPage />); expect(await screen.findByText('模板读取失败，请重试。')).toBeVisible(); expect(screen.getByRole('button', { name: '添加工作项' })).toBeDisabled(); fireEvent.click(screen.getByRole('button', { name: /刷新模板/ })); expect(await screen.findByText('现场验证')).toBeVisible()
})
it('reads reference names from the current item and preserves description when editing vehicle work', async () => {
  get.mockImplementation(async (url: string) => ({ data: url === '/templates' ? [{ id: 'default', name: '系统模板' }] : url.endsWith('/work-items') ? { phases: catalog([work({ kind: 'vehicle', vehicle_step_key: 'arrival', reference_docs: [{ filename: '场地参考.txt', id: 'd' } as any] })]).phases } : [{ key: 'arrival', name: '到场点检' }] }))
  render(<TemplateEditorPage />); await screen.findByText('现场验证'); fireEvent.click(screen.getByRole('button', { name: '参考文档 1' })); expect(await screen.findByRole('button', { name: '场地参考.txt' })).toBeVisible(); fireEvent.click(screen.getByRole('button', { name: /Close/ })); fireEvent.click(screen.getByRole('button', { name: '编辑工作项' })); fireEvent.change(screen.getByLabelText('工作说明'), { target: { value: '保留描述' } }); fireEvent.click(screen.getByRole('button', { name: '保存工作项' })); await waitFor(() => expect(put).toHaveBeenCalledOnce()); expect(put.mock.calls[0][1]).toMatchObject({ vehicle_step_key: 'arrival', description: '保留描述' })
})
it('retains the open work draft but disables saving when management is revoked', async () => {
  const v = render(<TemplateEditorPage />); await screen.findByText('现场验证'); fireEvent.click(screen.getByRole('button', { name: '编辑工作项' })); fireEvent.change(screen.getByLabelText('工作项名称'), { target: { value: '填写保留' } }); auth.user = { id: 'admin', role: 'admin', permission_overrides: { 'system.templates.manage': false } }; v.rerender(<TemplateEditorPage />); expect(screen.getByLabelText('工作项名称')).toHaveValue('填写保留'); expect(screen.getByRole('button', { name: '保存工作项' })).toBeDisabled(); expect(put).not.toHaveBeenCalled()
})
