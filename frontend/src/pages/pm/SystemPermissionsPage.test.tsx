import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { ConfigProvider } from 'antd'
import { createMemoryRouter, Link, RouterProvider } from 'react-router-dom'
import type { MemberPermissions, PermissionCatalog, PermissionMember, PermissionOverrides } from '../../api/permissions'
import SystemPermissionsPage from './SystemPermissionsPage'

const { calls, auth } = vi.hoisted(() => ({
  calls: { catalog: vi.fn(), users: vi.fn(), getUser: vi.fn(), updateUser: vi.fn() },
  auth: { user: { id: 'admin', role: 'admin' }, refreshPermissions: vi.fn() },
}))
vi.mock('../../api/permissions', () => ({ permissionsApi: calls }))
vi.mock('../../stores/auth', () => ({ useAuth: () => auth }))

const members: PermissionMember[] = [
  { id: 'admin', username: 'admin', display_name: '系统管理员', role: 'admin', is_active: true, permission_version: 7 },
  { id: 'worker', username: 'worker1', display_name: '现场工程师A', role: 'worker', is_active: true, permission_version: 4 },
  { id: 'worker-b', username: 'worker2', display_name: '现场工程师B', role: 'worker', is_active: false, permission_version: 2 },
]
const catalog: PermissionCatalog = { roles: [{ key: 'admin', name: '系统管理员' }, { key: 'worker', name: '实施工程师' }], groups: [
  { key: 'work', name: '工作工具', description: '用于查看和安排日常工作。', permissions: [
    { key: 'work.view', name: '查看安排', description: '查看可见工作安排。', scope: 'global', risk: 'low', default_roles: ['admin', 'worker'] },
    { key: 'work.manage', name: '管理安排', description: '调整工作日期和执行人。', scope: 'global', risk: 'high', default_roles: ['admin'] },
    { key: 'system.permissions', name: '管理系统权限', description: '权限管理仍仅对系统管理员开放。', scope: 'global', risk: 'critical', default_roles: ['admin'], admin_locked: true },
  ] },
  { key: 'projects', name: '项目内操作', description: '只作用于可见项目，不会扩大项目范围。', permissions: [
    { key: 'project.manage', name: '修改可见项目', description: '根据项目职责或单独设置调整项目。', scope: 'project', risk: 'high', default_roles: [], contextual_default: true },
  ] },
  { key: 'own', name: '本人资料', description: '只涉及本人内容。', permissions: [
    { key: 'own.read', name: '查看本人资料', description: '读取自己的资料。', scope: 'own', risk: 'low', default_roles: ['admin', 'worker'] },
  ] },
] }

function policy(id = 'worker', overrides: PermissionOverrides = {}, version?: number): MemberPermissions {
  const member = members.find(row => row.id === id)!
  const defaults = catalog.groups.flatMap(group => group.permissions.filter(row => row.default_roles.includes(member.role)).map(row => row.key))
  const effective = new Set(defaults)
  for (const [key, allowed] of Object.entries(overrides)) { if (allowed) effective.add(key); else effective.delete(key) }
  return { user: { ...member, permission_version: version ?? member.permission_version }, version: version ?? member.permission_version, defaults, effective: [...effective], overrides: { ...overrides } }
}
function failure(status: number, detail: string) { return { isAxiosError: true, response: { status, data: { detail } } } }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done }); return { promise, resolve } }
function mount() {
  const router = createMemoryRouter([
    { path: '/pm/permissions', element: <><Link to="/elsewhere">离开权限页</Link><SystemPermissionsPage /></> },
    { path: '/elsewhere', element: <h1>其他页面</h1> },
  ], { initialEntries: ['/pm/permissions'] })
  render(<ConfigProvider theme={{ token: { motion: false } }}><RouterProvider router={router} /></ConfigProvider>)
  return router
}
async function chooseMemberOnly(name = '现场工程师A') {
  fireEvent.click(await screen.findByRole('button', { name: `选择成员：${name}` }))
  await screen.findByRole('heading', { name, level: 2 })
  const advanced = screen.getByText('高级：逐项权限设置')
  if (!advanced.closest('details')?.open) fireEvent.click(advanced)
}
async function choose(name = '现场工程师A') {
  await chooseMemberOnly(name)
  return screen.findByRole('region', { name: '权限：查看安排' })
}
function setChoice(name: string, choice: string) {
  fireEvent.click(within(screen.getByRole('region', { name: `权限：${name}` })).getByRole('radio', { name: choice }))
}

beforeEach(() => {
  vi.resetAllMocks()
  auth.user = { id: 'admin', role: 'admin' }
  auth.refreshPermissions.mockResolvedValue(undefined)
  calls.catalog.mockResolvedValue(catalog)
  calls.users.mockResolvedValue(members)
  calls.getUser.mockImplementation(async id => policy(id))
  calls.updateUser.mockImplementation(async (id, body) => policy(id, body.overrides, body.version + 1))
})

it('keeps the management page administrator-only even if other roles have grants', async () => {
  auth.user = { id: 'worker', role: 'worker' }
  mount()
  expect(await screen.findByText('只有系统管理员可管理系统权限')).toBeInTheDocument()
  expect(calls.catalog).not.toHaveBeenCalled()
  expect(calls.users).not.toHaveBeenCalled()
  expect(calls.updateUser).not.toHaveBeenCalled()
})

it('loads dynamic modules and explains conditional project inheritance without claiming denial', async () => {
  mount(); await choose()
  fireEvent.click(screen.getByText('项目内操作'))
  const row = await screen.findByRole('region', { name: '权限：修改可见项目' })
  expect(row).toHaveTextContent('当前：按项目职责/授权')
  expect(row).toHaveTextContent('默认：按项目职责与已有授权')
  expect(row).not.toHaveTextContent('当前：禁止')
  expect(screen.getByText(/不会让他看到不相关项目/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('switch', { name: '仅看已允许' }))
  expect(screen.queryByRole('region', { name: '权限：修改可见项目' })).not.toBeInTheDocument()
  expect(screen.getByRole('region', { name: '权限：查看安排' })).toBeInTheDocument()
})

it('names the real catalog scopes and risks in Chinese and retains detailed descriptions', async () => {
  const realScopes = ['system', 'visible_projects', 'all_projects', 'archives', 'visible_people', 'own', 'project']
  const labels = ['全系统功能', '可见项目', '全部普通项目', '历史归档库', '人员范围', '本人范围', '可见项目']
  calls.catalog.mockResolvedValue({ ...catalog, groups: [{ key: 'all', name: '目录实际范围', description: '权限说明', permissions: realScopes.map((scope, index) => ({ key: `read.${scope}`, name: `范围${index}`, description: `详细说明${index}，权限仍受项目可见性和既有业务规则约束。`, default_roles: ['worker'], scope, risk: index === 2 ? 'high' : 'normal' })) }] })
  mount(); await chooseMemberOnly()
  for (let index = 0; index < realScopes.length; index++) {
    const row = screen.getByRole('region', { name: `权限：范围${index}` })
    expect(row).toHaveTextContent(labels[index]); expect(row).toHaveTextContent(`详细说明${index}`)
    expect(row).not.toHaveTextContent(realScopes[index])
  }
  expect(screen.getByRole('region', { name: '权限：范围2' })).toHaveTextContent('高风险')
})

it('does not claim that an allowed override is effective on an inactive account', async () => {
  calls.getUser.mockResolvedValue(policy('worker-b', { 'work.manage': true }))
  mount(); await choose('现场工程师B')
  expect(screen.getByRole('region', { name: '权限：管理安排' })).toHaveTextContent('当前：账号停用')
  expect(screen.getByRole('region', { name: '权限：管理安排' })).toHaveTextContent('启用账号后按规则生效')
  expect(within(screen.getByRole('region', { name: '权限：管理安排' })).getByRole('radio', { name: '允许' })).toBeChecked()
})

it('saves all three states with the source version, retaining untouched historical settings', async () => {
  calls.getUser.mockResolvedValue(policy('worker', { 'work.manage': true, 'retired.setting': false }))
  mount(); await choose()
  setChoice('查看安排', '禁止'); setChoice('管理安排', '继承')
  expect(screen.getByRole('region', { name: '权限：查看安排' })).toHaveTextContent('当前：允许')
  expect(screen.getByRole('region', { name: '权限：查看安排' })).toHaveTextContent('保存后：禁止')
  expect(screen.getByText('2 项未保存修改')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '保存权限' }))
  await waitFor(() => expect(calls.updateUser).toHaveBeenCalledWith('worker', { version: 4, overrides: { 'work.view': false, 'retired.setting': false } }))
  await waitFor(() => expect(screen.getByRole('button', { name: '保存权限' })).toBeDisabled())
})

it('protects the administrator management entry from single and module-wide changes', async () => {
  mount(); await choose('系统管理员')
  const row = screen.getByRole('region', { name: '权限：管理系统权限' })
  within(row).getAllByRole('radio').forEach(radio => expect(radio).toBeDisabled())
  expect(row).toHaveTextContent('保留管理员入口')
  fireEvent.click(screen.getByRole('button', { name: '本组禁止' }))
  fireEvent.click(screen.getByRole('button', { name: '保存权限' }))
  await waitFor(() => expect(calls.updateUser).toHaveBeenCalledWith('admin', { version: 7, overrides: { 'work.view': false, 'work.manage': false } }))
  await waitFor(() => expect(auth.refreshPermissions).toHaveBeenCalledTimes(1))
})

it('does not delegate permission management to a worker through a module batch', async () => {
  mount(); await choose()
  const row = screen.getByRole('region', { name: '权限：管理系统权限' })
  expect(row).toHaveTextContent('仅管理员身份')
  expect(row).toHaveTextContent('不能单独委派或关闭')
  within(row).getAllByRole('radio').forEach(radio => expect(radio).toBeDisabled())
  fireEvent.click(screen.getByRole('button', { name: '本组允许' }))
  fireEvent.click(screen.getByRole('button', { name: '保存权限' }))
  await waitFor(() => expect(calls.updateUser).toHaveBeenCalledWith('worker', { version: 4, overrides: { 'work.view': true, 'work.manage': true } }))
  expect(calls.updateUser.mock.calls[0][1].overrides).not.toHaveProperty('system.permissions')
})

it('limits a filtered module batch to visible editable rows and leaves other modules unchanged', async () => {
  mount(); await choose('系统管理员')
  fireEvent.change(screen.getByRole('searchbox', { name: '搜索权限' }), { target: { value: '查看安排' } })
  expect(screen.getByText('本组当前显示 1 项可调整')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '本组禁止' }))
  fireEvent.click(screen.getByRole('button', { name: '保存权限' }))
  await waitFor(() => expect(calls.updateUser).toHaveBeenCalledWith('admin', { version: 7, overrides: { 'work.view': false } }))
})

it('keeps a failed draft and retries the same explicit override rather than resetting it', async () => {
  calls.updateUser.mockRejectedValueOnce(failure(503, '保存服务暂不可用')).mockImplementationOnce(async (id, body) => policy(id, body.overrides, body.version + 1))
  mount(); await choose(); setChoice('管理安排', '允许')
  fireEvent.click(screen.getByRole('button', { name: '保存权限' }))
  expect(await screen.findByText('保存服务暂不可用')).toBeInTheDocument()
  expect(within(screen.getByRole('region', { name: '权限：管理安排' })).getByRole('radio', { name: '允许' })).toBeChecked()
  fireEvent.click(screen.getByRole('button', { name: '保存权限' }))
  await waitFor(() => expect(calls.updateUser).toHaveBeenCalledTimes(2))
  expect(calls.updateUser.mock.calls[1]).toEqual(calls.updateUser.mock.calls[0])
})

it('reads a conflict without replacing input and merges only local changes into the fresh version', async () => {
  const base = policy('worker', { 'work.view': true, 'retired.setting': false })
  const fresh = policy('worker', { 'work.view': false, 'own.read': false, 'retired.setting': false }, 9)
  calls.getUser.mockResolvedValueOnce(base).mockResolvedValueOnce(fresh)
  calls.updateUser.mockRejectedValueOnce(failure(409, '权限版本已过期')).mockImplementationOnce(async (id, body) => policy(id, body.overrides, body.version + 1))
  mount(); await choose(); setChoice('管理安排', '允许')
  fireEvent.click(screen.getByRole('button', { name: '保存权限' }))
  expect(await screen.findByText('权限已被他人更新，本次修改仍保留')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '保存权限' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: '读取最新权限' }))
  await screen.findByText('已读取最新版本，尚未替换你的输入')
  expect(within(screen.getByRole('region', { name: '权限：查看安排' })).getByRole('radio', { name: '允许' })).toBeChecked()
  expect(within(screen.getByRole('region', { name: '权限：管理安排' })).getByRole('radio', { name: '允许' })).toBeChecked()
  fireEvent.click(screen.getByRole('button', { name: '保留本次调整并重试' }))
  await waitFor(() => expect(calls.updateUser).toHaveBeenLastCalledWith('worker', { version: 9, overrides: { 'work.view': false, 'own.read': false, 'retired.setting': false, 'work.manage': true } }))
  await waitFor(() => expect(screen.getByRole('button', { name: '保存权限' })).toBeDisabled())
})

it('keeps conflict edits when reading the fresh version fails and permits explicit discard only', async () => {
  calls.getUser.mockResolvedValueOnce(policy()).mockRejectedValueOnce(failure(503, '读取最新失败')).mockResolvedValueOnce(policy('worker', { 'work.view': false }, 8))
  calls.updateUser.mockRejectedValue(failure(409, '版本冲突'))
  mount(); await choose(); setChoice('管理安排', '允许')
  fireEvent.click(screen.getByRole('button', { name: '保存权限' }))
  await screen.findByText('权限已被他人更新，本次修改仍保留')
  fireEvent.click(screen.getByRole('button', { name: '读取最新权限' }))
  expect(await screen.findByText('读取最新失败')).toBeInTheDocument()
  expect(within(screen.getByRole('region', { name: '权限：管理安排' })).getByRole('radio', { name: '允许' })).toBeChecked()
  fireEvent.click(screen.getByRole('button', { name: '读取最新权限' }))
  await screen.findByText('已读取最新版本，尚未替换你的输入')
  fireEvent.click(screen.getByRole('button', { name: '使用最新权限，放弃本次修改' }))
  await waitFor(() => expect(screen.getByRole('button', { name: '保存权限' })).toBeDisabled())
  expect(calls.updateUser).toHaveBeenCalledTimes(1)
})

it('does not call an obsolete snapshot current after cancelling a conflict draft', async () => {
  calls.updateUser.mockRejectedValue(failure(409, '权限版本已过期'))
  mount(); await choose(); setChoice('管理安排', '允许')
  fireEvent.click(screen.getByRole('button', { name: '保存权限' }))
  await screen.findByText('权限已被他人更新，本次修改仍保留')
  fireEvent.click(screen.getByRole('button', { name: '取消修改' }))
  expect(screen.getByText('本次修改已取消，需核对最新权限')).toBeInTheDocument()
  expect(screen.getByRole('region', { name: '权限：查看安排' })).toHaveTextContent('更新前：允许')
  expect(screen.getByRole('button', { name: '保存权限' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: '读取最新权限' }))
  await screen.findByText('已读取最新版本，尚未替换你的输入')
  fireEvent.click(screen.getByRole('button', { name: '使用最新权限，放弃本次修改' }))
  expect(screen.getByRole('region', { name: '权限：查看安排' })).toHaveTextContent('当前：允许')
  expect(calls.updateUser).toHaveBeenCalledTimes(1)
})

it('allows cancelling a member switch without losing edits', async () => {
  mount(); await choose(); setChoice('管理安排', '允许')
  fireEvent.click(screen.getByRole('button', { name: '选择成员：现场工程师B' }))
  const dialog = await screen.findByRole('dialog')
  expect(dialog).toHaveTextContent('当前成员的权限有未保存修改')
  fireEvent.click(within(dialog).getByRole('button', { name: '继续调整' }))
  expect(screen.getByRole('heading', { name: '现场工程师A', level: 2 })).toBeInTheDocument()
  expect(within(screen.getByRole('region', { name: '权限：管理安排' })).getByRole('radio', { name: '允许' })).toBeChecked()
  expect(calls.getUser).not.toHaveBeenCalledWith('worker-b')
})

it('switches members only after explicit discard and does not persist abandoned edits', async () => {
  mount(); await choose(); setChoice('管理安排', '允许')
  fireEvent.click(screen.getByRole('button', { name: '选择成员：现场工程师B' }))
  const dialog = await screen.findByRole('dialog')
  fireEvent.click(within(dialog).getByRole('button', { name: '放弃修改并切换' }))
  await screen.findByRole('heading', { name: '现场工程师B', level: 2 })
  expect(screen.getByRole('button', { name: '保存权限' })).toBeDisabled()
  expect(calls.updateUser).not.toHaveBeenCalled()
})

it('guards route navigation and browser reload while an override remains unsaved', async () => {
  const router = mount(); await choose(); setChoice('管理安排', '允许')
  const event = new Event('beforeunload', { cancelable: true })
  window.dispatchEvent(event); expect(event.defaultPrevented).toBe(true)
  fireEvent.click(screen.getByRole('link', { name: '离开权限页' }))
  const dialog = await screen.findByRole('dialog')
  fireEvent.click(within(dialog).getByRole('button', { name: '继续调整' }))
  expect(router.state.location.pathname).toBe('/pm/permissions')
  expect(within(screen.getByRole('region', { name: '权限：管理安排' })).getByRole('radio', { name: '允许' })).toBeChecked()
})

it('locks controls and navigation during an outstanding save and prevents duplicate submissions', async () => {
  const pending = deferred<MemberPermissions>()
  calls.updateUser.mockReturnValue(pending.promise)
  const router = mount(); await choose(); setChoice('管理安排', '允许')
  const saveButton = screen.getByRole('button', { name: '保存权限' })
  fireEvent.click(saveButton)
  fireEvent.click(saveButton)
  expect(calls.updateUser).toHaveBeenCalledTimes(1)
  expect(screen.getByRole('button', { name: '选择成员：现场工程师B' })).toBeDisabled()
  within(screen.getByRole('region', { name: '权限：管理安排' })).getAllByRole('radio').forEach(radio => expect(radio).toBeDisabled())
  fireEvent.click(screen.getByRole('link', { name: '离开权限页' }))
  expect(await screen.findByText('权限正在保存，请等待结果后再离开')).toBeInTheDocument()
  expect(router.state.location.pathname).toBe('/pm/permissions')
  await act(async () => pending.resolve(policy('worker', { 'work.manage': true }, 5)))
  fireEvent.click(screen.getByRole('link', { name: '离开权限页' }))
  await screen.findByRole('heading', { name: '其他页面' })
})

it('ignores a late response from the previous selected member', async () => {
  const pending = deferred<MemberPermissions>()
  calls.getUser.mockImplementation(id => id === 'worker' ? pending.promise : Promise.resolve(policy(id)))
  mount()
  fireEvent.click(await screen.findByRole('button', { name: '选择成员：现场工程师A' }))
  fireEvent.click(screen.getByRole('button', { name: '选择成员：现场工程师B' }))
  await screen.findByRole('heading', { name: '现场工程师B', level: 2 })
  await act(async () => pending.resolve(policy('worker', { 'work.manage': true }, 99)))
  expect(screen.getByRole('heading', { name: '现场工程师B', level: 2 })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '保存权限' })).toBeDisabled()
})

it('distinguishes unavailable directory data from an empty member list and retries', async () => {
  calls.catalog.mockRejectedValueOnce(failure(503, '目录服务暂不可用')).mockResolvedValueOnce(catalog)
  mount()
  expect(await screen.findByText('目录服务暂不可用')).toBeInTheDocument()
  expect(screen.queryByText('暂无成员')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '重新加载目录' }))
  expect(await screen.findByRole('button', { name: '选择成员：现场工程师A' })).toBeInTheDocument()
})


it('keeps item-by-item controls collapsed until advanced settings are opened', async () => {
  mount()
  fireEvent.click(await screen.findByRole('button', { name: '选择成员：现场工程师A' }))
  await screen.findByRole('heading', { name: '现场工程师A', level: 2 })
  expect(screen.getByText('高级：逐项权限设置').closest('details')).not.toHaveAttribute('open')
  fireEvent.click(screen.getByText('高级：逐项权限设置'))
  expect(screen.getByRole('region', { name: '权限：查看安排' })).toBeInTheDocument()
})
