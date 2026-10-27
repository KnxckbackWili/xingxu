import { beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ConfigProvider } from 'antd'

const { listActive, listProjects, get, put, viewport } = vi.hoisted(() => ({
  listActive: vi.fn(), listProjects: vi.fn(), get: vi.fn(), put: vi.fn(), viewport: { mobile: false },
}))
vi.mock('../../api', () => ({ userApi: { listActive }, projectApi: { list: listProjects } }))
vi.mock('../../api/client', () => ({ api: { get, put } }))
vi.mock('../../stores/auth', () => ({ useAuth: () => ({ user: { role: 'admin' } }) }))
vi.mock('../../hooks/useMediaQuery', () => ({ useMediaQuery: () => viewport.mobile }))
import AssignPage from './AssignPage'

const project = { id: 'p1', name: '测试项目', status: 'preparing', members: ['u1'], version: 7,
  capabilities: ['project.manage_members'] }
beforeEach(() => {
  vi.clearAllMocks()
  listActive.mockResolvedValue([{ id: 'u1', display_name: '已安排人员', role: 'worker' },
    { id: 'u2', display_name: '待安排人员', role: 'worker' }])
  listProjects.mockResolvedValue([project])
  get.mockImplementation((path: string) => Promise.resolve({ data: path === '/dashboard/assignment-pool'
    ? { items: [{ id: 'u1', load_percent: 20, project_count: 1 }, { id: 'u2', load_percent: 0, project_count: 0 }] }
    : [] }))
  put.mockResolvedValue({ data: { ...project, members: ['u1', 'u2'], version: 8 } })
})

it.each([false, true])('saves actual members without organization or staffing templates (mobile=%s)', async mobile => {
  viewport.mobile = mobile
  render(<ConfigProvider theme={{ token: { motion: false } }}><AssignPage mode="projects" /></ConfigProvider>)
  expect(await screen.findByText('待安排人员')).toBeInTheDocument()
  expect(screen.queryByText('岗位缺口')).toBeNull()
  expect(screen.queryByPlaceholderText('小组')).toBeNull()
  fireEvent.click(screen.getByRole('checkbox', { name: mobile ? '选择该候选人' : '选择该行' }))
  fireEvent.click(screen.getByRole('button', { name: /加入项目/ }))
  await waitFor(() => expect(put).toHaveBeenCalledWith('/projects/p1', { members: ['u1', 'u2'], version: 7 }))
  expect(get.mock.calls.map(call => call[0])).toEqual(['/dashboard/people-overview', '/dashboard/assignment-pool'])
})
