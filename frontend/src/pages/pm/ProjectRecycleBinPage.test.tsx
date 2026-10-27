import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { ConfigProvider } from 'antd'
import type { PermissionUser } from '../../constants/systemPermissions'
import ProjectRecycleBinPage from './ProjectRecycleBinPage'
import { projectRecycleApi, type RecycledProject } from '../../api'
const navigate = vi.hoisted(() => vi.fn())
const auth: { user: PermissionUser | null } = vi.hoisted(() => ({ user: { id: 'pm1', role: 'pm' } }))
vi.mock('react-router-dom', () => ({ useNavigate: () => navigate }))
vi.mock('../../stores/auth', () => ({ useAuth: () => auth }))
vi.mock('../../api', () => ({ projectRecycleApi: { list: vi.fn(), get: vi.fn(), restore: vi.fn(), downloadBackup: vi.fn(), permanentBackups: vi.fn(), preparePermanent: vi.fn(), permanentlyDelete: vi.fn(), downloadPermanent: vi.fn() } }))
vi.mock('../../api/client', () => ({ errMsg: (e: any) => e.response?.data?.detail ?? '暂时无法连接' }))
const row: RecycledProject = { id: 'p1', name: '物流一期', status_before_delete: 'executing', deleted_at: '2026-10-08T01:00:00Z', deleted_by_name: '李经理', deletion_id: 'd1', version: 5, can_restore: true, delete_backup_available: true, can_download_backup: true }
beforeEach(() => { vi.resetAllMocks(); auth.user = { id: 'pm1', role: 'pm' }; vi.mocked(projectRecycleApi.list).mockResolvedValue([row]); vi.mocked(projectRecycleApi.restore).mockResolvedValue({ message: '已还原', project_id: 'p1', version: 6 }) })
function show() { return render(<ConfigProvider theme={{ token: { motion: false } }}><ProjectRecycleBinPage /></ConfigProvider>) }
async function open() { fireEvent.click(await screen.findByRole('button', { name: '还原项目：物流一期' })); return screen.findByRole('dialog', { name: '还原这个项目？' }) }
it('explains project-only backup and cancels without a restoration write', async () => {
 show(); const dialog = await open(); await waitFor(() => expect(within(dialog).getByText(/不会新建副本或重置历史数据/)).toBeVisible()); expect(screen.getByText(/不提供整系统数据库/)).toBeVisible()
 fireEvent.click(within(dialog).getByRole('button', { name: '保留在回收站' })); expect(projectRecycleApi.restore).not.toHaveBeenCalled(); expect(screen.getByRole('heading', { name: '物流一期' })).toBeInTheDocument()
})
it('restores only the exact deletion generation and removes only the successful row', async () => {
 vi.mocked(projectRecycleApi.list).mockResolvedValue([row, { ...row, id: 'p2', name: '物流二期', deletion_id: 'd2' }]); show(); const dialog = await open()
 fireEvent.click(within(dialog).getByRole('button', { name: '确认还原' })); await waitFor(() => expect(projectRecycleApi.restore).toHaveBeenCalledWith('p1', { version: 5, deletion_id: 'd1' }))
 await waitFor(() => expect(screen.queryByRole('heading', { name: '物流一期' })).not.toBeInTheDocument()); expect(screen.getByRole('heading', { name: '物流二期' })).toBeInTheDocument()
})
it('retains failed restoration and retries the same version and deletion identity', async () => {
 vi.mocked(projectRecycleApi.restore).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ message: '成功', project_id: 'p1', version: 6 }); show(); const dialog = await open()
 fireEvent.click(within(dialog).getByRole('button', { name: '确认还原' })); await screen.findByText('未能确认还原结果，请核对后重试'); fireEvent.click(screen.getByRole('button', { name: '确认还原' }))
 await waitFor(() => expect(projectRecycleApi.restore).toHaveBeenCalledTimes(2)); expect(vi.mocked(projectRecycleApi.restore).mock.calls[0]).toEqual(vi.mocked(projectRecycleApi.restore).mock.calls[1])
})
it('cannot restore with an old deletion id after a concurrent restoration and re-delete', async () => {
 vi.mocked(projectRecycleApi.restore).mockRejectedValueOnce({ response: { status: 409, data: { detail: '记录已变化' } } }).mockResolvedValueOnce({ message: '成功', project_id: 'p1', version: 10 }); vi.mocked(projectRecycleApi.get).mockResolvedValue({ ...row, deletion_id: 'd-new', version: 9 })
 show(); const dialog = await open(); fireEvent.click(within(dialog).getByRole('button', { name: '确认还原' })); await screen.findByText('回收站记录已变化，请重新核对'); expect(screen.getByRole('button', { name: '确认还原' })).toBeDisabled()
 fireEvent.click(screen.getByRole('button', { name: '读取最新记录' })); await waitFor(() => expect(screen.getByRole('button', { name: '确认还原' })).toBeEnabled()); fireEvent.click(screen.getByRole('button', { name: '确认还原' }))
 await waitFor(() => expect(projectRecycleApi.restore).toHaveBeenLastCalledWith('p1', { version: 9, deletion_id: 'd-new' }))
})
it('serializes repeated restoration clicks and locks cancellation during its response', async () => {
 let resolve!: (value: { message: string; project_id: string; version: number }) => void; vi.mocked(projectRecycleApi.restore).mockImplementation(() => new Promise(done => { resolve = done }))
 show(); const dialog = await open(); const save = within(dialog).getByRole('button', { name: '确认还原' }); fireEvent.click(save); fireEvent.click(save)
 expect(projectRecycleApi.restore).toHaveBeenCalledTimes(1); expect(screen.getByRole('button', { name: '保留在回收站' })).toBeDisabled()
 await act(async () => resolve({ message: '成功', project_id: 'p1', version: 6 })); await screen.findByText('回收站暂无项目')
})
it.each(['project.delete', 'project.read'])('denies restore and backup download after explicit %s denial', async key => {
 auth.user = { id: 'pm1', role: 'pm', permission_overrides: { [key]: false } }; show(); const restore = await screen.findByRole('button', { name: '还原项目：物流一期' })
 expect(restore).toBeDisabled(); fireEvent.click(restore); expect(screen.getByRole('button', { name: '下载项目备份：物流一期' })).toBeDisabled(); expect(projectRecycleApi.restore).not.toHaveBeenCalled(); expect(projectRecycleApi.downloadBackup).not.toHaveBeenCalled()
})
it('keeps authorized restoration while hiding backup download after explicit export denial, even with stale allowed metadata', async () => {
 auth.user = { id: 'pm1', role: 'pm', permission_overrides: { 'project.delete': true, 'project.export': false } }
 show(); const restore = await screen.findByRole('button', { name: '还原项目：物流一期' })
 expect(restore).toBeEnabled(); expect(screen.queryByRole('button', { name: '下载项目备份：物流一期' })).not.toBeInTheDocument()
 expect(projectRecycleApi.downloadBackup).not.toHaveBeenCalled()
 const dialog = await open(); fireEvent.click(within(dialog).getByRole('button', { name: '确认还原' }))
 await waitFor(() => expect(projectRecycleApi.restore).toHaveBeenCalledWith('p1', { version: 5, deletion_id: 'd1' }))
 await screen.findByText('回收站暂无项目'); expect(projectRecycleApi.downloadBackup).not.toHaveBeenCalled()
})
it.each([false, undefined])('requires an explicit server download grant (%s) without disabling restore', async canDownload => {
 vi.mocked(projectRecycleApi.list).mockResolvedValue([{ ...row, can_download_backup: canDownload }]); show()
 expect(await screen.findByRole('button', { name: '还原项目：物流一期' })).toBeEnabled()
 expect(screen.queryByRole('button', { name: /下载项目备份/ })).not.toBeInTheDocument(); expect(projectRecycleApi.downloadBackup).not.toHaveBeenCalled()
})
it('does not offer a nonexistent historical backup or hide an authorized restore', async () => {
 vi.mocked(projectRecycleApi.list).mockResolvedValue([{ ...row, delete_backup_available: false }]); show(); await screen.findByText('历史记录未附备份')
 expect(screen.getByRole('button', { name: '还原项目：物流一期' })).toBeEnabled(); expect(screen.queryByRole('button', { name: /下载项目备份/ })).not.toBeInTheDocument()
})
it('distinguishes failed loading from an empty bin and permits reload', async () => {
 vi.mocked(projectRecycleApi.list).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce([row]); show(); await screen.findByText('回收站加载失败'); expect(screen.queryByText('回收站暂无项目')).not.toBeInTheDocument()
 fireEvent.click(screen.getByRole('button', { name: '重新加载' })); await screen.findByRole('heading', { name: '物流一期' })
})
