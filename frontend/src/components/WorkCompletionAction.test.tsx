import { setOfflineAccount } from '../offline/queue'
import { ConfigProvider } from 'antd'
import type { ReactNode } from 'react'
import { beforeEach, expect, it, vi } from 'vitest'
import { act, fireEvent, render as rtlRender, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import WorkCompletionAction from './WorkCompletionAction'
import { work } from '../test/workItems'
function render(ui: ReactNode) { return rtlRender(ui, { wrapper: ({ children }) => <ConfigProvider theme={{ token: { motion: false } }}>{children}</ConfigProvider> }) }

const { put, auth } = vi.hoisted(() => ({ put: vi.fn(), auth: { user: { id: 'u', role: 'pm' } as any } }))
vi.mock('../api/client', () => ({ api: { put }, errMsg: (e: any) => e.response?.data?.detail || '请求未确认' }))
vi.mock('../stores/auth', () => ({ useAuth: () => auth }))
beforeEach(() => { setOfflineAccount('u'); put.mockReset(); auth.user = { id: 'u', role: 'pm' } })
const props = () => ({ projectId: 'p', item: work(), canRecord: true, onSaved: vi.fn() })
function view(p = props()) { return render(<MemoryRouter><WorkCompletionAction {...p} /></MemoryRouter>) }
it('requires a reason, sends the loaded version once and preserves input on conflict', async () => {
  put.mockRejectedValue({ response: { status: 409, data: { detail: '版本变化，请核对' } } })
  const p = props(); view(p); fireEvent.click(screen.getByRole('button', { name: '标记完成' }))
  expect(screen.getByRole('button', { name: '保存工作状态' })).toBeDisabled()
  fireEvent.change(screen.getByLabelText('工作状态理由'), { target: { value: '复测完成' } })
  fireEvent.click(screen.getByRole('button', { name: '保存工作状态' }))
  await waitFor(() => expect(screen.getByText('版本变化，请核对')).toBeVisible())
  expect(screen.getByLabelText('工作状态理由')).toHaveValue('复测完成')
  expect(put).toHaveBeenCalledWith('/projects/p/work-items/w1/completion', { version: 7, is_completed: true, reason: '复测完成', override_failed: false, failed_checks: [] })
  expect(p.onSaved).not.toHaveBeenCalled()
})
it('locks duplicate clicks while saving and ignores a response after the actor changes', async () => {
  let done!: (v: any) => void; put.mockImplementation(() => new Promise(resolve => { done = resolve }))
  const p = props(); const v = view(p); fireEvent.click(screen.getByText('标记完成')); fireEvent.change(screen.getByLabelText('工作状态理由'), { target: { value: '依据' } })
  const save = screen.getByRole('button', { name: '保存工作状态' }); fireEvent.click(save); fireEvent.click(save)
  expect(put).toHaveBeenCalledOnce()
  auth.user = { id: 'another', role: 'pm' }; v.rerender(<MemoryRouter><WorkCompletionAction {...p} /></MemoryRouter>)
  await act(async () => done({ data: {} })); expect(p.onSaved).not.toHaveBeenCalled()
})
it('retains an open reason when the permission is revoked and sends nothing', () => {
  const p = props(); const v = view(p); fireEvent.click(screen.getByText('标记完成')); fireEvent.change(screen.getByLabelText('工作状态理由'), { target: { value: '原填写' } })
  auth.user = { id: 'u', role: 'pm', permission_overrides: { 'worker.report': false } }; v.rerender(<MemoryRouter><WorkCompletionAction {...p} /></MemoryRouter>)
  expect(screen.getByLabelText('工作状态理由')).toHaveValue('原填写'); expect(screen.getByRole('button', { name: '保存工作状态' })).toBeDisabled(); expect(put).not.toHaveBeenCalled()
})
it('only explicitly confirmed ordinary failure versions are sent for coverage', async () => {
  put.mockResolvedValue({ data: {} }); const p = { ...props(), canOverride: true, item: work({ check_items: [{ id: 'c', name: '复测', failed: true, failed_reason: '偏差', version: 4, is_applicable: true, is_required: true, is_done: false, is_safety_critical: false }] }) }
  view(p); fireEvent.click(screen.getByText('标记完成')); fireEvent.change(screen.getByLabelText('工作状态理由'), { target: { value: '已按当前偏差核对' } })
  expect(screen.getByRole('button', { name: '保存工作状态' })).toBeDisabled(); fireEvent.click(screen.getByRole('checkbox')); fireEvent.click(screen.getByRole('button', { name: '保存工作状态' }))
  await waitFor(() => expect(p.onSaved).toHaveBeenCalledOnce()); expect(put.mock.calls[0][1]).toMatchObject({ override_failed: true, failed_checks: [{ id: 'c', version: 4 }] })
})
it('links vehicle work to the matrix without a boolean completion button', () => {
  view({ ...props(), item: work({ kind: 'vehicle' }) }); expect(screen.getByRole('link', { name: '到车辆进度表登记' })).toHaveAttribute('href', '/pm/projects/p/vehicles'); expect(screen.queryByText('标记完成')).toBeNull()
})
it('preserves input without writing when a different tab changes the verified account', async () => {
  view(); fireEvent.click(screen.getByText('标记完成')); fireEvent.change(screen.getByLabelText('工作状态理由'), { target: { value: '原账号依据' } }); setOfflineAccount('other'); fireEvent.click(screen.getByRole('button', { name: '保存工作状态' })); await screen.findByText('请求未确认'); expect(put).not.toHaveBeenCalled(); expect(screen.getByLabelText('工作状态理由')).toHaveValue('原账号依据')
})
it('distinguishes a committed work state from failure to refresh it', async () => {
  put.mockResolvedValue({ data: {} }); const p = { ...props(), onSaved: vi.fn().mockRejectedValue(new Error('offline')) }; view(p); fireEvent.click(screen.getByText('标记完成')); fireEvent.change(screen.getByLabelText('工作状态理由'), { target: { value: '已验证' } }); fireEvent.click(screen.getByRole('button', { name: '保存工作状态' })); expect(await screen.findByText('工作状态已保存，但最新记录读取失败；请刷新核对，勿重复提交。')).toBeVisible(); expect(put).toHaveBeenCalledOnce()
})
it('does not close a new draft after switching A → B → A while an old response is pending', async () => {
  let done!: (value: any) => void; put.mockImplementation(() => new Promise(resolve => { done = resolve })); const p = props(); const v = view(p); fireEvent.click(screen.getByText('标记完成')); fireEvent.change(screen.getByLabelText('工作状态理由'), { target: { value: '旧请求' } }); fireEvent.click(screen.getByRole('button', { name: '保存工作状态' })); auth.user = { id: 'b', role: 'pm' }; v.rerender(<MemoryRouter><WorkCompletionAction {...p} /></MemoryRouter>); auth.user = { id: 'u', role: 'pm' }; v.rerender(<MemoryRouter><WorkCompletionAction {...p} /></MemoryRouter>); fireEvent.click(screen.getByText('标记完成')); fireEvent.change(screen.getByLabelText('工作状态理由'), { target: { value: '新的未提交依据' } }); await act(async () => done({ data: {} })); expect(screen.getByLabelText('工作状态理由')).toHaveValue('新的未提交依据'); expect(p.onSaved).not.toHaveBeenCalled()
})
it('lists required checks before completion and passes one from the dialog', async () => {
  put.mockResolvedValue({ data: {} })
  const check = { id: 'c1', name: '通道宽度确认', is_required: true, is_safety_critical: false, is_applicable: true, is_done: false, failed: false, version: 2 }
  const p = { ...props(), item: work({ check_items: [check] }) }
  const v = view(p); fireEvent.click(screen.getByRole('button', { name: '标记完成' }))
  fireEvent.change(screen.getByLabelText('工作状态理由'), { target: { value: '现场确认' } })
  expect(screen.getByRole('group', { name: '完成前必须通过的检查' })).toHaveTextContent('通道宽度确认')
  expect(screen.getByRole('button', { name: '保存工作状态' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: '确认通过' }))
  await waitFor(() => expect(put).toHaveBeenCalledWith('/projects/p/check-items/c1', { version: 2, is_done: true, failed: false, is_applicable: true }))
  expect(p.onSaved).toHaveBeenCalledOnce()
  v.rerender(<MemoryRouter><WorkCompletionAction {...p} item={work({ version: 8, check_items: [{ ...check, is_done: true, version: 3 }] })} /></MemoryRouter>)
  expect(screen.queryByRole('group', { name: '完成前必须通过的检查' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: '保存工作状态' })).toBeEnabled()
})
