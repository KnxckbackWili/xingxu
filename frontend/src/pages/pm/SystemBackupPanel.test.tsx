const { permissionActor } = vi.hoisted(() => ({ permissionActor: { user: { id: 'admin', role: 'admin', system_permissions: undefined as string[] | undefined } } }))
vi.mock('../../stores/auth', () => ({ useAuth: () => ({ user: permissionActor.user }) }))
import { beforeEach, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
const { get, post, put, remove } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), remove: vi.fn() }))
vi.mock('../../api/client', () => ({ api: { get, post, put, delete: remove }, errMsg: () => '请求失败' }))
import SystemBackupPanel from './SystemBackupPanel'

const supported = { items: [], restore_pending: false, database: 'sqlite', web_restore_supported: true, encryption: { configured: true } }
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
function mount() { const view = render(<ConfigProvider locale={zhCN} theme={{ token: { motion: false } }}><SystemBackupPanel /></ConfigProvider>); fireEvent.click(screen.getByText('恢复系统备份')); return view }
beforeEach(() => {
  permissionActor.user = { id: 'admin', role: 'admin', system_permissions: undefined }
  vi.clearAllMocks(); get.mockResolvedValue({ data: supported }); post.mockResolvedValue({ data: { message: '恢复已准备' } })
})

it('does not let backup reading authorize restore or creation even when web restore is supported', async () => {
  permissionActor.user = { id: 'member', role: 'worker', system_permissions: ['system.backups.read'] }
  mount()
  await waitFor(() => expect(get).toHaveBeenCalledWith('/system/backups'))
  expect(screen.queryByRole('button', { name: /立即备份/ })).toBeNull()
  expect(screen.getByRole('button', { name: /上传恢复包/ })).toBeDisabled()
  expect(post).not.toHaveBeenCalled()
})

it('explains unsupported PostgreSQL web restore before upload', async () => {
  get.mockResolvedValue({ data: { ...supported, database: 'postgresql', web_restore_supported: false } })
  mount()
  expect(await screen.findByText('当前 PostgreSQL 部署不支持网页恢复')).toBeVisible()
  expect(screen.getByRole('button', { name: /上传恢复包/ })).toBeDisabled()
  expect(screen.getByText(/PostgreSQL 数据库/)).toBeVisible()
})

it('fails closed during metadata loading and on failure, then allows retry', async () => {
  const initial = deferred<any>()
  get.mockReturnValueOnce(initial.promise)
  mount()
  expect(screen.getByRole('button', { name: /上传恢复包/ })).toBeDisabled()
  expect(screen.queryByText(/SQLite/)).not.toBeInTheDocument()
  await act(async () => initial.reject(new Error('offline')))
  expect(await screen.findByText('备份信息加载失败，恢复功能已禁用')).toBeVisible()
  expect(screen.getByRole('button', { name: /上传恢复包/ })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: /重\s*试/ }))
  await waitFor(() => expect(screen.getByRole('button', { name: /上传恢复包/ })).not.toBeDisabled())
  expect(screen.getByText(/SQLite 数据库/)).toBeVisible()
})

it('does not assume restore support from missing capability metadata', async () => {
  get.mockResolvedValue({ data: { items: [], restore_pending: false } })
  mount()
  expect(await screen.findByText('当前部署未确认支持网页恢复')).toBeVisible()
  expect(screen.getByRole('button', { name: /上传恢复包/ })).toBeDisabled()
  expect(screen.queryByText(/SQLite/)).not.toBeInTheDocument()
})

it('ignores an older supported response after newer unsupported metadata', async () => {
  const old = deferred<any>()
  get.mockReturnValueOnce(old.promise).mockResolvedValueOnce({ data: { ...supported, web_restore_supported: false } })
  mount()
  fireEvent.click(screen.getByRole('button', { name: '刷新备份列表' }))
  await screen.findByText('当前部署未确认支持网页恢复')
  await act(async () => old.resolve({ data: supported }))
  expect(screen.getByRole('button', { name: /上传恢复包/ })).toBeDisabled()
})

it('revokes previously loaded restore capability if metadata refresh fails', async () => {
  mount()
  await waitFor(() => expect(screen.getByRole('button', { name: /上传恢复包/ })).not.toBeDisabled())
  get.mockRejectedValueOnce(new Error('offline'))
  fireEvent.click(screen.getByRole('button', { name: '刷新备份列表' }))
  await screen.findByText('备份信息加载失败，恢复功能已禁用')
  expect(screen.getByRole('button', { name: /上传恢复包/ })).toBeDisabled()
})

it('serializes backup creation and releases the lock after failure', async () => {
  const first = deferred<any>()
  post.mockReturnValueOnce(first.promise)
  mount()
  await waitFor(() => expect(screen.getByRole('button', { name: /上传恢复包/ })).not.toBeDisabled())
  const create = screen.getByRole('button', { name: /立即备份/ })
  act(() => { fireEvent.click(create); fireEvent.click(create) })
  expect(post).toHaveBeenCalledTimes(1)
  await act(async () => first.reject(new Error('offline')))
  fireEvent.click(create)
  await waitFor(() => expect(post).toHaveBeenCalledTimes(2))
})

it('requires restore confirmation, blocks duplicate upload, and permits cancellation', async () => {
  const { container } = mount()
  await waitFor(() => expect(screen.getByRole('button', { name: /上传恢复包/ })).not.toBeDisabled())
  const input = container.querySelector('input[type="file"]')!
  fireEvent.change(input, { target: { files: [new File(['mock'], 'backup.agvenc')] } })
  await screen.findAllByText('恢复整个 AGV 系统？')
  expect(post).not.toHaveBeenCalled()
  expect(screen.getByRole('button', { name: /上传恢复包/ })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: /取\s*消/ }))
  await waitFor(() => expect(screen.getByRole('button', { name: /上传恢复包/ })).not.toBeDisabled())
  expect(post).not.toHaveBeenCalled()
})

it('keeps restore confirmation open on failure and retries once without duplicate posts', async () => {
  const pending = deferred<any>()
  post.mockReturnValueOnce(pending.promise)
  const { container } = mount()
  await waitFor(() => expect(screen.getByRole('button', { name: /上传恢复包/ })).not.toBeDisabled())
  fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [new File(['mock'], 'backup.agvenc')] } })
  const confirm = await screen.findByRole('button', { name: '校验并准备恢复' })
  fireEvent.change(screen.getByLabelText('这份备份的口令'), { target: { value: 'test-only-backup-password' } })
  act(() => { fireEvent.click(confirm); fireEvent.click(confirm) })
  expect(post).toHaveBeenCalledTimes(1)
  expect(post).toHaveBeenCalledWith('/system/restore?confirm=RESTORE', expect.any(FormData))
  const submitted = post.mock.calls[0][1] as FormData
  expect(submitted.get('passphrase')).toBe('test-only-backup-password')
  expect((submitted.get('file') as File).name).toBe('backup.agvenc')
  await waitFor(() => expect(screen.getByRole('button', { name: /取\s*消/ })).toBeDisabled())
  await act(async () => pending.reject(new Error('invalid backup')))
  await waitFor(() => expect(confirm).not.toHaveClass('ant-btn-loading'))
  fireEvent.click(confirm)
  await waitFor(() => expect(post).toHaveBeenCalledTimes(2))
  await waitFor(() => expect(screen.getByRole('button', { name: /上传恢复包/ })).not.toBeDisabled())
})

it('keeps generating and downloading primary, while recovery needs explicit expansion', async () => {
  render(<ConfigProvider locale={zhCN} theme={{ token: { motion: false } }}><SystemBackupPanel /></ConfigProvider>)
  await screen.findByText(/SQLite 数据库/)
  expect(screen.getByText('恢复系统备份').closest('details')).not.toHaveAttribute('open')
  expect(screen.getByRole('button', { name: /立即备份/ })).toBeEnabled()
  expect(post).not.toHaveBeenCalled()
})


it('requires administrator password setup before creating or restoring backups', async () => {
  get.mockResolvedValue({ data: { ...supported, encryption: { configured: false } } })
  put.mockResolvedValue({ data: { configured: true } })
  mount()
  expect(await screen.findByText('请先设置备份口令')).toBeVisible()
  expect(screen.getByRole('button', { name: /立即备份/ })).toBeDisabled()
  expect(screen.getByRole('button', { name: /上传恢复包/ })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: '设置备份口令' }))
  fireEvent.change(screen.getByLabelText('新备份口令（至少 12 个字符）'), { target: { value: 'test-only-backup-password' } })
  fireEvent.change(screen.getByLabelText('再次输入备份口令'), { target: { value: 'different-backup-password' } })
  fireEvent.click(screen.getByRole('button', { name: /确\s*定/ }))
  expect(put).not.toHaveBeenCalled()
  fireEvent.change(screen.getByLabelText('再次输入备份口令'), { target: { value: 'test-only-backup-password' } })
  get.mockResolvedValue({ data: supported })
  fireEvent.click(screen.getByRole('button', { name: /确\s*定/ }))
  await waitFor(() => expect(put).toHaveBeenCalledTimes(1))
  expect(put).toHaveBeenCalledWith('/system/backup-encryption', { passphrase: 'test-only-backup-password' })
  await waitFor(() => expect(screen.queryByLabelText('再次输入备份口令')).toBeNull())
  expect(screen.getByRole('button', { name: /立即备份/ })).toBeEnabled()
})

it('does not show passphrase configuration to delegated non-administrators', async () => {
  permissionActor.user = { id: 'worker', role: 'worker', system_permissions: ['system.backups.read', 'system.backups.configure'] }
  get.mockResolvedValue({ data: { ...supported, encryption: { configured: false } } })
  mount()
  await screen.findByText('请先设置备份口令')
  expect(screen.queryByRole('button', { name: '设置备份口令' })).toBeNull()
})

it('requires a backup password before posting a restore', async () => {
  const { container } = mount()
  await waitFor(() => expect(screen.getByRole('button', { name: /上传恢复包/ })).toBeEnabled())
  fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [new File(['mock'], 'backup.agvenc')] } })
  fireEvent.click(await screen.findByRole('button', { name: '校验并准备恢复' }))
  expect(post).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: /取\s*消/ }))
})


it('requires the configure grant even for an administrator', async () => {
  permissionActor.user = { id: 'admin', role: 'admin', system_permissions: ['system.backups.read'] }
  mount()
  await screen.findByText('系统备份已启用口令加密')
  expect(screen.queryByRole('button', { name: '更换备份口令' })).toBeNull()
})

it('clears canceled password entries and refuses short passwords', async () => {
  mount()
  fireEvent.click(await screen.findByRole('button', { name: '更换备份口令' }))
  fireEvent.change(screen.getByLabelText('新备份口令（至少 12 个字符）'), { target: { value: 'short' } })
  fireEvent.change(screen.getByLabelText('再次输入备份口令'), { target: { value: 'short' } })
  fireEvent.click(screen.getByRole('button', { name: /确\s*定/ }))
  expect(put).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: /取\s*消/ }))
  await waitFor(() => expect(screen.queryByLabelText('再次输入备份口令')).toBeNull())
  fireEvent.click(screen.getByRole('button', { name: '更换备份口令' }))
  expect(screen.getByLabelText('新备份口令（至少 12 个字符）')).toHaveValue('')
  expect(screen.getByLabelText('再次输入备份口令')).toHaveValue('')
})

it('serializes password changes, keeps a failed attempt retryable, and clears successful values', async () => {
  const saving = deferred<any>()
  put.mockReturnValueOnce(saving.promise).mockResolvedValueOnce({ data: { configured: true } })
  mount()
  fireEvent.click(await screen.findByRole('button', { name: '更换备份口令' }))
  fireEvent.change(screen.getByLabelText('新备份口令（至少 12 个字符）'), { target: { value: 'test-only-backup-password' } })
  fireEvent.change(screen.getByLabelText('再次输入备份口令'), { target: { value: 'test-only-backup-password' } })
  const confirm = screen.getByRole('button', { name: /确\s*定/ })
  act(() => { fireEvent.click(confirm); fireEvent.click(confirm) })
  expect(put).toHaveBeenCalledTimes(1)
  expect(screen.getByRole('button', { name: /取\s*消/ })).toBeDisabled()
  expect(screen.getByLabelText('新备份口令（至少 12 个字符）')).toBeDisabled()
  await act(async () => saving.reject(new Error('offline')))
  expect(screen.getByLabelText('新备份口令（至少 12 个字符）')).toHaveValue('test-only-backup-password')
  fireEvent.click(confirm)
  await waitFor(() => expect(put).toHaveBeenCalledTimes(2))
  await waitFor(() => expect(screen.queryByLabelText('再次输入备份口令')).toBeNull())
  fireEvent.click(screen.getByRole('button', { name: '更换备份口令' }))
  expect(screen.getByLabelText('新备份口令（至少 12 个字符）')).toHaveValue('')
  expect(screen.getByLabelText('再次输入备份口令')).toHaveValue('')
})
