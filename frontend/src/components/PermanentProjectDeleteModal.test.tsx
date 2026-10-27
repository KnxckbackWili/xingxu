import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { ConfigProvider } from 'antd'
import type { PermissionUser } from '../constants/systemPermissions'
import { projectRecycleApi, type RecycledProject, type PermanentProjectBackup } from '../api'
import PermanentProjectDeleteModal from './PermanentProjectDeleteModal'
const auth: { user: PermissionUser } = vi.hoisted(() => ({ user: { id: 'admin', role: 'admin' } }))
vi.mock('../stores/auth', () => ({ useAuth: () => auth }))
vi.mock('../api', () => ({ projectRecycleApi: { preparePermanent: vi.fn(), permanentlyDelete: vi.fn(), downloadPermanent: vi.fn() } }))
vi.mock('../api/client', () => ({ errMsg: () => '备份失败或记录变化' }))
const row: RecycledProject = { id: 'p1', name: '物流一期', version: 4, deletion_id: 'd1', deleted_at: '2026-10-01', deleted_by_name: 'PM', status_before_delete: 'executing', delete_backup_available: true, can_restore: true, can_permanently_delete: true }
const receipt: PermanentProjectBackup = { backup_id: 'receipt-1', project_id: 'p1', project_name: row.name, sha256: 'ciphertext-checksum', bytes: 1234, encrypted: true, purged_at: null }
const createUrl = vi.fn(() => 'blob:isolated-encrypted-backup')
beforeEach(() => {
  vi.clearAllMocks(); auth.user = { id: 'admin', role: 'admin' }
  vi.mocked(projectRecycleApi.preparePermanent).mockResolvedValue(receipt)
  vi.mocked(projectRecycleApi.downloadPermanent).mockResolvedValue(new Blob(['encrypted only']))
  vi.mocked(projectRecycleApi.permanentlyDelete).mockResolvedValue({ ...receipt, purged_at: '2026-10-27', message: '已永久删除' })
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createUrl })
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
})
afterEach(() => { vi.restoreAllMocks() })
const show = (onPurged = vi.fn()) => render(<ConfigProvider theme={{ token: { motion: false } }}><PermanentProjectDeleteModal project={row} onClose={vi.fn()} onPurged={onPurged} /></ConfigProvider>)
async function prepare() {
  fireEvent.click(screen.getByRole('button', { name: '生成加密项目备份' }))
  await screen.findByText('SHA-256：ciphertext-checksum')
  await waitFor(() => expect(screen.getByRole('button', { name: /下载加密项目备份/ })).not.toHaveClass('ant-btn-loading'))
}
it('requires verified ciphertext, successful download, saved confirmation and exact name before deleting', async () => {
  const purged = vi.fn(); show(purged); await prepare()
  expect(projectRecycleApi.preparePermanent).toHaveBeenCalledWith('p1', { version: 4, deletion_id: 'd1' })
  expect(screen.getByRole('button', { name: '确认永久删除' })).toBeDisabled(); expect(screen.getByRole('checkbox')).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: /下载加密项目备份/ })); await waitFor(() => expect(createUrl).toHaveBeenCalledTimes(1))
  fireEvent.click(screen.getByRole('checkbox')); fireEvent.change(screen.getByLabelText('输入完整项目名称确认永久删除'), { target: { value: '错误名称' } })
  expect(screen.getByRole('button', { name: '确认永久删除' })).toBeDisabled()
  fireEvent.change(screen.getByLabelText('输入完整项目名称确认永久删除'), { target: { value: row.name } }); fireEvent.click(screen.getByRole('button', { name: '确认永久删除' }))
  await waitFor(() => expect(purged).toHaveBeenCalledWith('p1'))
  expect(projectRecycleApi.permanentlyDelete).toHaveBeenCalledWith('p1', { version: 4, deletion_id: 'd1', backup_id: receipt.backup_id, confirm_name: row.name })
  expect(screen.getByText(/加密备份继续保留/)).toBeInTheDocument()
})
it('backup failure keeps the project and never submits permanent deletion', async () => {
  vi.mocked(projectRecycleApi.preparePermanent).mockRejectedValue(new Error('disk'))
  show(); fireEvent.click(screen.getByRole('button', { name: '生成加密项目备份' })); await screen.findByText('备份失败或记录变化')
  expect(projectRecycleApi.permanentlyDelete).not.toHaveBeenCalled(); expect(screen.queryByRole('button', { name: '确认永久删除' })).not.toBeInTheDocument()
})
it.each(['pm', 'readonly'])('never enables administrator deletion for %s with explicit grants', role => {
  auth.user = { id: 'other', role, permission_overrides: { 'system.projects.purge': true, 'project.delete': true } }
  show(); expect(screen.getByRole('button', { name: '生成加密项目备份' })).toBeDisabled()
})
it('does not publish a late download after permission revocation', async () => {
  let resolve!: (value: Blob) => void
  vi.mocked(projectRecycleApi.downloadPermanent).mockReturnValue(new Promise(done => { resolve = done }))
  const view = show(); await prepare(); fireEvent.click(screen.getByRole('button', { name: /下载加密项目备份/ }))
  auth.user = { id: 'admin', role: 'admin', permission_overrides: { 'system.projects.purge': false } }
  view.rerender(<ConfigProvider theme={{ token: { motion: false } }}><PermanentProjectDeleteModal project={row} onClose={vi.fn()} onPurged={vi.fn()} /></ConfigProvider>)
  await act(async () => resolve(new Blob(['old-private-ciphertext'])))
  expect(createUrl).not.toHaveBeenCalled(); expect(projectRecycleApi.permanentlyDelete).not.toHaveBeenCalled()
})
