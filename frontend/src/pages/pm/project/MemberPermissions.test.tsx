import { beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import MemberPermissions from './MemberPermissions'
import { permissionsApi } from '../../../api/permissions'
const { update } = vi.hoisted(() => ({ update: vi.fn() }))
vi.mock('../../../api', () => ({ projectApi: { update } }))
vi.mock('../../../api/permissions', () => ({ permissionsApi: { projectReasons: vi.fn() } }))
vi.mock('../../../api/client', () => ({ errMsg: () => '授权保存失败' }))
const project: any = { id: 'p1', version: 4, members: ['worker', 'intern'], capabilities: ['project.manage_members'], grantable_capabilities: ['project.manage_plan', 'project.manage_schedule'], member_permissions: [{ user_id: 'intern', capabilities: ['project.manage_schedule'] }] }
const members = [{ id: 'worker', display_name: '实施成员' }, { id: 'intern', display_name: '实习成员' }]
beforeEach(() => { vi.clearAllMocks(); update.mockResolvedValue({}) })
it('unknown legacy state preserves readable grants without delegation controls', () => {
  render(<MemberPermissions project={{ ...project, status: 'legacy_unknown' }} members={members} />)
  expect(screen.getByText('实习成员')).toBeInTheDocument()
  expect(screen.getByText('编辑并发布周计划')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '配置授权' })).toBeNull()
})
it('describes archive grants without promising document editing or acceptance authority', () => {
  render(<MemberPermissions project={{ ...project, member_permissions: [{ user_id: 'worker', capabilities: ['project.archive'] }] }} members={members} />)
  expect(screen.getByText('归档与复盘操作')).toBeInTheDocument()
  expect(screen.queryByText('维护验收与资料清单')).toBeNull()
})
it('grants only project capabilities without changing role, preserving other member grants', async () => {
  const reload = vi.fn()
  render(<MemberPermissions project={project} members={members} onReload={reload} />)
  fireEvent.click(screen.getAllByRole('button', { name: '配置授权' })[0])
  fireEvent.click(screen.getByRole('checkbox', { name: '编辑工作项、资料要求与车辆台账' }))
  fireEvent.click(screen.getByRole('button', { name: /保存授权/ }))
  await waitFor(() => expect(update).toHaveBeenCalledWith('p1', { version: 4, member_permissions: [{ user_id: 'intern', capabilities: ['project.manage_schedule'] }, { user_id: 'worker', capabilities: ['project.manage_plan'] }] }))
  expect(reload).toHaveBeenCalledOnce()
})
it('clearing all checkboxes revokes the explicit member grant', async () => {
  render(<MemberPermissions project={project} members={members} />)
  fireEvent.click(screen.getAllByRole('button', { name: '配置授权' })[1])
  fireEvent.click(screen.getByRole('checkbox', { name: '编辑并发布周计划' }))
  fireEvent.click(screen.getByRole('button', { name: /保存授权/ }))
  await waitFor(() => expect(update).toHaveBeenCalledWith('p1', { version: 4, member_permissions: [] }))
})
it('delegated member managers cannot redelegate without server grant authority', () => {
  render(<MemberPermissions project={{ ...project, grantable_capabilities: [] }} members={members} />)
  expect(screen.queryByRole('button', { name: '配置授权' })).toBeNull()
})
it('preserves selection after a rejected save and can retry', async () => {
  update.mockRejectedValueOnce(new Error('conflict'))
  render(<MemberPermissions project={project} members={members} />)
  fireEvent.click(screen.getAllByRole('button', { name: '配置授权' })[0])
  fireEvent.click(screen.getByRole('checkbox', { name: '编辑工作项、资料要求与车辆台账' }))
  fireEvent.click(screen.getByRole('button', { name: /保存授权/ }))
  expect(await screen.findByText('授权保存失败')).toBeInTheDocument()
  expect(screen.getByRole('checkbox', { name: '编辑工作项、资料要求与车辆台账' })).toBeChecked()
  fireEvent.click(await screen.findByRole('button', { name: /保存授权/ }))
  await waitFor(() => expect(update).toHaveBeenCalledTimes(2))
})
it('labels inherited authority separately from revocable additional grants', () => {
  render(<MemberPermissions project={project} members={[{ id: 'worker', display_name: '协管成员', inherited_capabilities: ['project.manage_plan'] }]} />)
  expect(screen.getByText('职责自带（不可在此撤销）：编辑工作项、资料要求与车辆台账')).toBeInTheDocument()
})
it('does not allow changing grants on an archived project', () => {
  render(<MemberPermissions project={{ ...project, status: 'archived' }} members={members} />)
  expect(screen.queryByRole('button', { name: '配置授权' })).toBeNull()
})
it('uses the opening version when project data changes behind an open grant editor', async () => {
  const view = render(<MemberPermissions project={project} members={members} />)
  fireEvent.click(screen.getAllByRole('button', { name: '配置授权' })[0])
  fireEvent.click(screen.getByRole('checkbox', { name: '编辑工作项、资料要求与车辆台账' }))
  view.rerender(<MemberPermissions project={{ ...project, version: 5, member_permissions: [] }} members={members} />)
  fireEvent.click(screen.getByRole('button', { name: /保存授权/ }))
  await waitFor(() => expect(update).toHaveBeenCalledWith('p1', expect.objectContaining({ version: 4, member_permissions: expect.arrayContaining([{ user_id: 'intern', capabilities: ['project.manage_schedule'] }]) })))
})


it('shows the server reason for each project permission without changing grants', async () => {
  vi.mocked(permissionsApi.projectReasons).mockResolvedValue({ items: [
    { key: 'project.update', name: '修改项目资料', allowed: false, layer: 'system', reason: '系统管理员已禁止此操作或项目查看' },
  ] })
  render(<MemberPermissions project={project} members={members} />)
  fireEvent.click(screen.getAllByRole('button', { name: '查看无权限原因' })[0])
  expect(await screen.findByText('系统管理员已禁止此操作或项目查看')).toBeInTheDocument()
  expect(permissionsApi.projectReasons).toHaveBeenCalledWith('p1', 'worker')
  expect(update).not.toHaveBeenCalled()
})

it('does not display another project late explanation after the project changes', async () => {
  let complete!: (data: { items: any[] }) => void
  vi.mocked(permissionsApi.projectReasons).mockReturnValue(new Promise(resolve => { complete = resolve }))
  const page = render(<MemberPermissions project={project} members={members} />)
  fireEvent.click(screen.getAllByRole('button', { name: '查看无权限原因' })[0])
  page.rerender(<MemberPermissions project={{ ...project, id: 'p2' }} members={members} />)
  complete({ items: [{ key: 'project.update', name: '旧项目', allowed: false, layer: 'system', reason: '旧项目返回' }] })
  await waitFor(() => expect(screen.queryByRole('dialog', { name: /查看权限原因/ })).toBeNull())
  expect(screen.queryByText('旧项目返回')).toBeNull()
})
