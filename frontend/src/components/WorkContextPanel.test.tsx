import { setOfflineAccount } from '../offline/queue'
import { beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import WorkContextPanel, { WorkCheckAction } from './WorkContextPanel'
const { put, auth } = vi.hoisted(() => ({ put: vi.fn(), auth: { user: { id: 'u', role: 'worker' } as any } }))
vi.mock('../api/client', () => ({ api: { put }, errMsg: () => '请求失败' }))
vi.mock('../stores/auth', () => ({ useAuth: () => auth }))
const data = { project: { id: 'p', name: '现场' }, task: { id: 'w', description: '原工作' }, entries: [], repair: { id: 'r', unit_id: 'v', title: '原故障', action_taken: '', verification: '', is_closed: false }, can_update_repair: true }
beforeEach(() => { setOfflineAccount('u'); put.mockReset(); sessionStorage.clear(); auth.user = { id: 'u', role: 'worker' } })
function show(d = data, refresh = vi.fn()) { return render(<MemoryRouter><WorkContextPanel data={d} onRefresh={refresh} /></MemoryRouter>) }
it('preserves an old pending UUID without creating a new quantity submission', () => {
  const original = { pending: { task_id: 'w', client_uuid: 'old-uuid', completed_quantity: 2, note: '原文' } }; sessionStorage.setItem('agv:work-draft:u:p:w', JSON.stringify(original)); show()
  expect(screen.getByText(/原 UUID 和填写内容已保留/)).toBeVisible(); expect(JSON.parse(sessionStorage.getItem('agv:work-draft:u:p:w')!)).toEqual(original); expect(screen.queryByRole('spinbutton')).toBeNull(); expect(put).not.toHaveBeenCalled()
})
it('restores a repair draft and distinguishes a successful save from failed refreshing', async () => {
  const refresh = vi.fn().mockRejectedValue(new Error('offline')); let v = show(data, refresh); fireEvent.click(screen.getByText('记录维修与验证')); fireEvent.change(screen.getByLabelText('处理过程'), { target: { value: '更换驱动轮' } }); v.unmount(); v = show(data, refresh); fireEvent.click(screen.getByText('记录维修与验证')); expect(screen.getByLabelText('处理过程')).toHaveValue('更换驱动轮'); put.mockResolvedValue({ data: {} }); fireEvent.click(screen.getByRole('button', { name: '保存维修记录' })); expect(await screen.findByText('已保存，但最新记录读取失败，请刷新核对，勿重复提交。')).toBeVisible(); expect(put).toHaveBeenCalledOnce()
})
it('does not transfer one actor’s repair draft to another actor', async () => {
  const v = show(); fireEvent.click(screen.getByText('记录维修与验证')); fireEvent.change(screen.getByLabelText('处理过程'), { target: { value: '甲的私有草稿' } }); auth.user = { id: 'other', role: 'worker' }; v.rerender(<MemoryRouter><WorkContextPanel data={data} onRefresh={async () => {}} /></MemoryRouter>); fireEvent.click(await screen.findByText('记录维修与验证')); expect(screen.getByLabelText('处理过程')).not.toHaveValue('甲的私有草稿'); expect(JSON.parse(sessionStorage.getItem('agv:work-draft:u:p:w')!).repair.action_taken).toBe('甲的私有草稿')
})
it('sends the loaded check version and prevents safety NA and revoked writes', async () => {
  put.mockResolvedValue({ data: {} }); const item = { id: 'c', name: '急停', version: 9, is_done: false, is_safety_critical: true }; const v = render(<WorkCheckAction projectId="p" item={item} onSaved={async () => {}} />); expect(screen.queryByText('不适用')).toBeNull(); fireEvent.click(screen.getByText('确认通过')); await waitFor(() => expect(put).toHaveBeenCalledWith('/projects/p/check-items/c', { version: 9, is_done: true, failed: false, is_applicable: true })); auth.user = { id: 'u', role: 'worker', permission_overrides: { 'worker.report': false } }; v.rerender(<WorkCheckAction projectId="p" item={item} onSaved={async () => {}} />); expect(screen.getByText('确认通过').closest('button')).toBeDisabled()
})
