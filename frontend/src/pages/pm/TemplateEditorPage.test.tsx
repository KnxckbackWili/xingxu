import { setOfflineAccount } from '../../offline/queue'
import { beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render as rtlRender, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import type { ReactElement } from 'react'
import { catalog, work } from '../../test/workItems'
import TemplateEditorPage from './TemplateEditorPage'
const { get, put, auth } = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), auth: { user: { id: 'admin', role: 'admin' } as any } }))
vi.mock('../../api/client', () => ({ api: { get, put, post: vi.fn(), delete: vi.fn() }, errMsg: () => '保存失败' }))
vi.mock('../../stores/auth', () => ({ useAuth: () => auth }))
vi.mock('../../hooks/useVehicleTypes', () => ({ useVehicleTypes: () => ({ options: [] }) }))
vi.mock('./TemplateDocumentsTab', () => ({ default: () => <div>资料要求保留</div> }))
vi.mock('./TemplateProcurementsTab', () => ({ default: () => null }))
const render = (ui: ReactElement) => rtlRender(ui, { wrapper: ({ children }) => <MemoryRouter initialEntries={['/pm/templates/default']}><Routes><Route path="/pm/templates/:templateId" element={children} /></Routes></MemoryRouter> })
const panel = async () => { fireEvent.click(await screen.findByRole('button', { name: /现场验证/ })); return screen.findByRole('complementary', { name: /编辑工作项/ }) }
beforeEach(() => { setOfflineAccount('admin')
  auth.user = { id: 'admin', role: 'admin' }; get.mockReset(); put.mockReset().mockImplementation(async (_url: string, body: any) => ({ data: { ...work(), ...body, version: (body.version ?? 7) + 1 } }))
  get.mockImplementation(async (url: string) => ({ data: url === '/templates' ? [{ id: 'default', name: '系统模板', is_system: true }] : url.endsWith('/work-items') ? { phases: catalog().phases } : url.endsWith('/vehicle-steps') ? [] : [] }))
})
it('a field edited in the panel saves only that field, with the version it was read at', async () => {
  render(<TemplateEditorPage />); const side = await panel()
  const name = within(side).getByLabelText('工作项名称')
  fireEvent.change(name, { target: { value: '修订名称' } }); fireEvent.blur(name)
  await waitFor(() => expect(put).toHaveBeenCalledOnce())
  expect(put.mock.calls[0]).toEqual(['/templates/default/work-items/w1', { name: '修订名称', version: 7 }])
  expect(await within(side).findByText('已保存')).toBeInTheDocument()
  // nothing changed: leaving the field again sends nothing
  fireEvent.blur(within(side).getByLabelText('工作说明'))
  expect(put).toHaveBeenCalledOnce()
})
it('a failed load is shown and can be retried', async () => {
  get.mockRejectedValueOnce(new Error('down')); render(<TemplateEditorPage />)
  expect(await screen.findByText('模板读取失败，请重试。')).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: /刷新模板/ }))
  expect(await screen.findByText('现场验证')).toBeVisible()
})
it('shows the step and reference documents of vehicle work and keeps edits in order', async () => {
  get.mockImplementation(async (url: string) => ({ data: url === '/templates' ? [{ id: 'default', name: '系统模板' }] : url.endsWith('/work-items') ? { phases: catalog([work({ kind: 'vehicle', vehicle_step_key: 'arrival', reference_docs: [{ filename: '场地参考.txt', id: 'd' } as any] })]).phases } : [{ key: 'arrival', name: '到场点检' }] }))
  render(<TemplateEditorPage />); const side = await panel()
  expect(within(side).getByRole('button', { name: /场地参考\.txt$/ })).toBeVisible()
  expect(within(side).getByText('到场点检')).toBeInTheDocument()
  const description = within(side).getByLabelText('工作说明')
  fireEvent.change(description, { target: { value: '保留描述' } }); fireEvent.blur(description)
  const name = within(side).getByLabelText('工作项名称')
  fireEvent.change(name, { target: { value: '新名称' } }); fireEvent.blur(name)
  await waitFor(() => expect(put).toHaveBeenCalledTimes(2))
  expect(put.mock.calls[0][1]).toEqual({ description: '保留描述', version: 7 })
  expect(put.mock.calls[1][1]).toEqual({ name: '新名称', version: 8 })
})
it('readers see the template but cannot change it', async () => {
  auth.user = { id: 'reader', role: 'pm', permission_overrides: { 'system.templates.manage': false } }
  render(<TemplateEditorPage />); const side = await panel()
  expect(within(side).getByLabelText('工作项名称')).toBeDisabled()
  expect(within(side).queryByRole('button', { name: /删除工作项/ })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /添加工作项/ })).not.toBeInTheDocument()
  expect(document.querySelector('[draggable="true"]')).toBeNull()
})
