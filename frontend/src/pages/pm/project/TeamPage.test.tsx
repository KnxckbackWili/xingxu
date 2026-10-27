import { MemoryRouter } from 'react-router-dom'
import type { ReactNode } from 'react'
import { expect, it, vi } from 'vitest'
import { fireEvent, render as rawRender, screen, waitFor } from '@testing-library/react'
function render(ui: ReactNode) { return rawRender(<MemoryRouter>{ui}</MemoryRouter>) }
const { listActive, update } = vi.hoisted(() => ({ listActive: vi.fn(), update: vi.fn() }))
vi.mock('../../../api', () => ({ userApi: { listActive }, projectApi: { update } }))
vi.mock('../../../api/client', () => ({ api: { get: vi.fn() }, errMsg: () => '保存失败，请重试' }))
import TeamPage from './TeamPage'
it('unknown legacy project preserves team information without members, role-plan or delegation writes', async () => {
  vi.mocked(api.get).mockResolvedValue({ data: [{ id: 'worker-1', display_name: '历史成员', role: 'worker' }] })
  render(<TeamPage project={{ id: 'p2', status: 'legacy_unknown', members: ['worker-1'], capabilities: ['project.update', 'project.manage_members'], member_permissions: [], grantable_capabilities: ['project.manage_plan'] }} canEdit />)
  expect((await screen.findAllByText('历史成员')).length).toBeGreaterThan(0)
  for (const name of ['添加人员', '套用团队模板', '配置授权']) expect(screen.queryByRole('button', { name })).toBeNull()
})
it('将成员 ID 映射为姓名，失败保留成员选择并允许重试', async () => {
  listActive.mockResolvedValue([{ id: 'worker-1', display_name: '张工程师', role: 'worker' }])
  update.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({})
  const reload = vi.fn()
  render(<TeamPage project={{ id: 'p1', status: 'preparing', members: ['worker-1'], version: 7 }} canEdit onReload={reload} />)
  expect(await screen.findByText('张工程师')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '添加人员' }))
  fireEvent.click(screen.getByRole('button', { name: /保存成员/ }))
  await waitFor(() => expect(update).toHaveBeenCalledWith('p1', { members: ['worker-1'], version: 7 }))
  expect(reload).not.toHaveBeenCalled()
  await screen.findByText('保存失败，请重试')
  expect(screen.getByRole('link', { name: '去日程改派' })).toHaveAttribute('href', '/pm/projects/p1/schedule')
  fireEvent.click(screen.getByRole('button', { name: /保存成员/ }))
  await waitFor(() => expect(reload).toHaveBeenCalledOnce())
})

import { api } from '../../../api/client'
it.each([false, true])('loads only the project people endpoint; candidate expansion requires member authority (%s)', async canEdit => {
  listActive.mockClear()
  vi.mocked(api.get).mockResolvedValue({ data: [{ id: 'worker-1', display_name: '项目内成员', role: 'worker', inherited_capabilities: [] }] })
  render(<TeamPage project={{ id: 'p2', status: 'preparing', members: ['worker-1'], capabilities: canEdit ? ['project.manage_members'] : [], member_permissions: [], grantable_capabilities: [] }} canEdit={canEdit} />)
  expect((await screen.findAllByText('项目内成员')).length).toBeGreaterThan(0)
  expect(api.get).toHaveBeenCalledWith('/projects/p2/people', { params: canEdit ? { include_candidates: true } : undefined })
  expect(listActive).not.toHaveBeenCalled()
  expect(screen.queryByRole('button', { name: '配置授权' })).toBeNull()
})
