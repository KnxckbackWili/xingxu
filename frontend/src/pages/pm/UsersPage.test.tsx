import { MemoryRouter } from 'react-router-dom'
const { permissionActor } = vi.hoisted(() => ({ permissionActor: { user: { id: 'admin', role: 'admin', system_permissions: undefined as string[] | undefined } } }))
vi.mock('../../stores/auth', () => ({ useAuth: () => ({ user: permissionActor.user }) }))
import { beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import UsersPage from './UsersPage'
import { userApi } from '../../api'
const { viewport } = vi.hoisted(() => ({ viewport: { mobile: true } }))
vi.mock('../../hooks/useMediaQuery', () => ({ useMediaQuery: () => viewport.mobile }))
vi.mock('../../api/client', () => ({ errMsg: () => 'error' }))
vi.mock('../../api', () => ({
  ROLE_MAP: { worker: '实施工程师' },
  userApi: { list: vi.fn(), update: vi.fn(), create: vi.fn() },
}))
const people = [
  { id: 'u1', username: 'one', display_name: '甲', role: 'worker', phone: '', email: '', is_active: true },
  { id: 'u2', username: 'two', display_name: '乙', role: 'worker', phone: '', email: '', is_active: true },
]
beforeEach(() => {
  permissionActor.user = { id: 'admin', role: 'admin', system_permissions: undefined }
  vi.clearAllMocks()
  vi.mocked(userApi.list).mockResolvedValue(people as any)
  vi.mocked(userApi.update).mockResolvedValue({} as any)
})
it.each([true, false])('discards another user password draft without retired profile fields (mobile=%s)', async mobile => {
  viewport.mobile = mobile
  render(<ConfigProvider theme={{ token: { motion: false } }}><MemoryRouter><UsersPage /></MemoryRouter></ConfigProvider>)
  const edits = await screen.findAllByRole('button', { name: /编辑/ })
  fireEvent.click(edits[0])
  let dialog = await screen.findByRole('dialog')
  fireEvent.change(within(dialog).getByPlaceholderText('留空则不修改'), { target: { value: 'not-a-real-password' } })
  fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
  fireEvent.click(screen.getAllByRole('button', { name: /编辑/ })[1])
  dialog = await screen.findByRole('dialog')
  expect(within(dialog).getByPlaceholderText('留空则不修改')).toHaveValue('')
  fireEvent.click(within(dialog).getByRole('button', { name: /保\s*存/ }))
  await waitFor(() => expect(userApi.update).toHaveBeenCalledWith('u2', expect.objectContaining({ display_name: '乙' })))
  expect(vi.mocked(userApi.update).mock.calls[0][1]).not.toHaveProperty('skills')
  expect(vi.mocked(userApi.update).mock.calls[0][1]).not.toHaveProperty('group_id')
  expect(userApi.update).toHaveBeenCalledWith('u2', expect.not.objectContaining({ password: expect.anything() }))
})

it('saves account once and keeps the dialog open while saving', async () => {
  viewport.mobile = true
  let finish!: (value: any) => void
  vi.mocked(userApi.update).mockReturnValue(new Promise(resolve => { finish = resolve }))
  render(<ConfigProvider theme={{ token: { motion: false } }}><MemoryRouter><UsersPage /></MemoryRouter></ConfigProvider>)
  fireEvent.click((await screen.findAllByRole('button', { name: /编辑/ }))[0])
  const dialog = await screen.findByRole('dialog')
  const save = within(dialog).getByRole('button', { name: /保\s*存/ })
  fireEvent.click(save)
  fireEvent.click(save)
  await waitFor(() => expect(userApi.update).toHaveBeenCalledTimes(1))
  expect(userApi.update).toHaveBeenCalledWith('u1', expect.objectContaining({ display_name: '甲' }))
  fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
  expect(dialog.closest('.ant-modal-wrap')).not.toHaveStyle({ display: 'none' })
  finish({})
  await waitFor(() => expect(dialog.closest('.ant-modal-wrap')).toHaveStyle({ display: 'none' }))
  expect(vi.mocked(userApi.update).mock.calls[0][1]).not.toHaveProperty('skills')
  expect(vi.mocked(userApi.update).mock.calls[0][1]).not.toHaveProperty('group_id')
})
it('shows load failure and blocks writes until a successful retry', async () => {
  vi.mocked(userApi.list).mockRejectedValueOnce(new Error('offline'))
  render(<ConfigProvider theme={{ token: { motion: false } }}><MemoryRouter><UsersPage /></MemoryRouter></ConfigProvider>)
  expect(await screen.findByText('账号加载失败')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /新建用户/ })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: /重\s*试/ }))
  await waitFor(() => expect(screen.queryByText('账号加载失败')).not.toBeInTheDocument())
  expect(screen.getByRole('button', { name: /新建用户/ })).toBeEnabled()
})

it('preserves a migrated role when editing only contact details', async () => {
  viewport.mobile = true
  vi.mocked(userApi.list).mockResolvedValue([{ ...people[0], role: 'director' }] as any)
  render(<ConfigProvider theme={{ token: { motion: false } }}><MemoryRouter><UsersPage /></MemoryRouter></ConfigProvider>)
  expect(await screen.findByText('总监（旧）')).toBeInTheDocument()
  fireEvent.click((await screen.findAllByRole('button', { name: /编辑/ }))[0])
  const dialog = await screen.findByRole('dialog')
  expect(within(dialog).getByText('总监（旧）')).toBeInTheDocument()
  fireEvent.change(within(dialog).getByLabelText('电话'), { target: { value: '13900000000' } })
  fireEvent.click(within(dialog).getByRole('button', { name: /保\s*存/ }))
  await waitFor(() => expect(userApi.update).toHaveBeenCalledWith('u1', expect.objectContaining({ role: 'director', phone: '13900000000' })))
})

it('delegates ordinary account editing without transmitting roles or enabling administrator edits', async () => {
  permissionActor.user = { id: 'member', role: 'worker', system_permissions: ['system.users.manage'] }
  vi.mocked(userApi.list).mockResolvedValue([...people, { ...people[0], id: 'admin', username: 'admin', role: 'admin', display_name: '系统管理员' }] as any)
  render(<ConfigProvider theme={{ token: { motion: false } }}><MemoryRouter><UsersPage /></MemoryRouter></ConfigProvider>)
  const edits = await screen.findAllByRole('button', { name: /编辑/ })
  expect(edits[2]).toBeDisabled()
  expect(screen.queryByRole('button', { name: '管理成员权限' })).toBeNull()
  fireEvent.click(edits[0])
  const dialog = await screen.findByRole('dialog')
  expect(within(dialog).getByLabelText('角色（职级）')).toBeDisabled()
  fireEvent.click(within(dialog).getByRole('button', { name: /保\s*存/ }))
  await waitFor(() => expect(userApi.update).toHaveBeenCalledWith('u1', expect.objectContaining({ display_name: '甲' })))
  expect(vi.mocked(userApi.update).mock.calls[0][1]).not.toHaveProperty('role')
})


it('creates an account from a preset while keeping individual role controls in advanced settings', async () => {
  vi.mocked(userApi.create).mockResolvedValue({} as any)
  render(<MemoryRouter><UsersPage /></MemoryRouter>)
  fireEvent.click(await screen.findByRole('button', { name: /新建用户/ }))
  const dialog = await screen.findByRole('dialog')
  expect(within(dialog).getByRole('combobox', { name: '预设角色' })).toBeInTheDocument()
  expect(within(dialog).getByText('高级：账号角色与逐项权限').closest('details')).not.toHaveAttribute('open')
  fireEvent.change(within(dialog).getByLabelText('姓名'), { target: { value: '新工程师' } })
  fireEvent.change(within(dialog).getByPlaceholderText('至少 6 位'), { target: { value: 'example-test-password' } })
  fireEvent.click(within(dialog).getByRole('button', { name: /保\s*存/ }))
  await waitFor(() => expect(userApi.create).toHaveBeenCalledWith(expect.objectContaining({
    username: '新工程师', permission_preset: 'worker', role: 'worker',
  })))
})
