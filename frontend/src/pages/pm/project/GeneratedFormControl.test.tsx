import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { ConfigProvider } from 'antd'
import type { GeneratedFormKind } from '../../../api/projectDocuments'
const h = vi.hoisted(() => ({ sources: vi.fn(), members: vi.fn(), generate: vi.fn() }))
vi.mock('../../../api/projectDocuments', () => ({ projectDocumentsApi: { generationSources: h.sources, confidentialityMembers: h.members } }))
import GeneratedFormControl from './GeneratedFormControl'
const source = { id: 'real-application', title: '原吊车申请', item_name: '吊车', apply_date: '2026-01-02', status: 'pending' }
beforeEach(() => { vi.resetAllMocks(); h.sources.mockResolvedValue([source]); h.members.mockResolvedValue([{ id: 'chosen', display_name: '已授权成员', role: 'worker' }]); h.generate.mockResolvedValue(true) })
function component(kind: GeneratedFormKind, projectId = 'p1', manage = false) {
  return <ConfigProvider theme={{ token: { motion: false } }}><GeneratedFormControl projectId={projectId} documentId="d1" kind={kind} busy={false} canManageConfidentiality={manage} onGenerate={h.generate} /></ConfigProvider>
}
it.each([['lifecycle', '由系统生成本周生命周期表'], ['inventory', '由物品流水生成']] as const)('%s defaults to one click with conservative source filtering', async (kind, label) => {
  render(component(kind)); fireEvent.click(screen.getByRole('button', { name: label }))
  await waitFor(() => expect(h.generate).toHaveBeenCalledExactlyOnceWith({}))
  expect(h.sources).not.toHaveBeenCalled()
})
it('contact requires selecting an actual server source before creating a version', async () => {
  render(component('contact')); fireEvent.click(screen.getByRole('button', { name: '由内部联系单生成' }))
  expect(screen.getByRole('button', { name: '生成并提交当前版本' })).toBeDisabled()
  await waitFor(() => expect(h.sources).toHaveBeenCalledWith('p1', 'd1', { confidential: false, confidentialUserIds: [] }))
  fireEvent.mouseDown(screen.getByRole('combobox', { name: '选择原物品申请' })); fireEvent.click(await screen.findByText('原吊车申请 · 2026-01-02'))
  fireEvent.click(screen.getByRole('button', { name: '生成并提交当前版本' }))
  await waitFor(() => expect(h.generate).toHaveBeenCalledWith({ confidential: false, confidentialUserIds: [], applicationId: 'real-application' }))
})
it('rechecks sources for an explicit private recipient set', async () => {
  render(component('contact', 'p1', true)); fireEvent.click(screen.getByRole('button', { name: '由内部联系单生成' }))
  fireEvent.click(screen.getByRole('switch', { name: '生成保密附件' }))
  await waitFor(() => expect(h.members).toHaveBeenCalledWith('p1'))
  const select = screen.getByRole('combobox', { name: '生成附件指定人员' })
  await waitFor(() => expect(select).not.toBeDisabled()); fireEvent.mouseDown(select); fireEvent.click(await screen.findByText('已授权成员'))
  await waitFor(() => expect(h.sources).toHaveBeenLastCalledWith('p1', 'd1', { confidential: true, confidentialUserIds: ['chosen'] }))
  fireEvent.mouseDown(screen.getByRole('combobox', { name: '选择原物品申请' })); fireEvent.click(await screen.findByText('原吊车申请 · 2026-01-02'))
  fireEvent.click(screen.getByRole('button', { name: '生成并提交当前版本' }))
  await waitFor(() => expect(h.generate).toHaveBeenCalledWith({ confidential: true, confidentialUserIds: ['chosen'], applicationId: 'real-application' }))
})
it('empty or failed source reads cannot submit an invented contact', async () => {
  h.sources.mockRejectedValueOnce({ isAxiosError: true, response: { status: 503, data: { detail: '来源暂不可用' } } }).mockResolvedValue([])
  render(component('contact')); fireEvent.click(screen.getByRole('button', { name: '由内部联系单生成' }))
  await waitFor(() => expect(screen.getByText('来源暂不可用')).toBeVisible()); expect(screen.getByRole('button', { name: '生成并提交当前版本' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: '重新读取' }))
  await waitFor(() => expect(screen.getByText(/当前输出范围没有可用的申请记录/)).toBeVisible())
  expect(screen.getByRole('button', { name: '生成并提交当前版本' })).toBeDisabled(); expect(h.generate).not.toHaveBeenCalled()
})
it('ignores a late source response after changing projects', async () => {
  let resolve: (rows: typeof source[]) => void = () => {}
  h.sources.mockImplementationOnce(() => new Promise(done => { resolve = done })).mockResolvedValue([{ ...source, title: '本项目申请' }])
  const ui = render(component('contact')); fireEvent.click(screen.getByRole('button', { name: '由内部联系单生成' }))
  await waitFor(() => expect(h.sources).toHaveBeenCalledTimes(1)); ui.rerender(component('contact', 'p2'))
  await act(async () => resolve([{ ...source, title: '过期旧项目申请' }]))
  fireEvent.click(screen.getByRole('button', { name: '由内部联系单生成' }))
  await waitFor(() => expect(h.sources).toHaveBeenCalledWith('p2', 'd1', { confidential: false, confidentialUserIds: [] }))
  fireEvent.mouseDown(screen.getByRole('combobox', { name: '选择原物品申请' }))
  await waitFor(() => expect(screen.getByText('本项目申请 · 2026-01-02')).toBeVisible()); expect(screen.queryByText(/过期旧项目申请/)).toBeNull()
})
it('keeps the chosen source and a visible error when server generation fails', async () => {
  h.generate.mockResolvedValue(false)
  render(component('contact')); fireEvent.click(screen.getByRole('button', { name: '由内部联系单生成' }))
  await waitFor(() => expect(h.sources).toHaveBeenCalledTimes(1))
  fireEvent.mouseDown(screen.getByRole('combobox', { name: '选择原物品申请' })); fireEvent.click(await screen.findByText('原吊车申请 · 2026-01-02'))
  fireEvent.click(screen.getByRole('button', { name: '生成并提交当前版本' }))
  await waitFor(() => expect(screen.getByText('文件未生成，请核对当前权限与来源后重试')).toBeVisible())
  expect(screen.getByRole('dialog')).toBeVisible(); expect(screen.getByRole('button', { name: '生成并提交当前版本' })).toBeEnabled()
})
