import { beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { ProjectCapabilitiesContext } from '../../../hooks/useProjectCapability'

const { auth, historyGet } = vi.hoisted(() => ({
  auth: { user: { id: 'pm', role: 'pm', permission_overrides: {} as Record<string, boolean> } }, historyGet: vi.fn(),
}))
vi.mock('../../../stores/auth', () => ({ useAuth: () => auth }))
vi.mock('../../../api', () => ({ projectApi: { update: vi.fn() }, userApi: { listActive: vi.fn().mockResolvedValue([]) } }))
vi.mock('../../../api/client', () => ({ api: { get: vi.fn().mockResolvedValue({ data: [] }) }, errMsg: () => '权限已变化' }))
vi.mock('../../../api/projectEditHistory', () => ({ projectEditHistoryApi: { get: historyGet, apply: vi.fn() } }))
vi.mock('../GovernancePage', () => ({ default: () => null }))
import EditPage from './EditPage'
beforeEach(() => { vi.clearAllMocks(); auth.user.permission_overrides = {} })

it.each(['project.update', 'project.read'])('honors fresh %s denial while project capabilities are still cached', async (key) => {
  auth.user.permission_overrides = { [key]: false }
  const project = { id: 'p-one', name: '原项目资料', manager: 'pm', status: 'draft', version: 3,
    start_date: '2026-10-09', end_date: '2026-10-30', capabilities: ['project.update'] } as any
  const router = createMemoryRouter([{ path: '/', element:
    <ProjectCapabilitiesContext.Provider value={project.capabilities}><EditPage project={project} onReload={vi.fn()} /></ProjectCapabilitiesContext.Provider>,
  }])
  render(<RouterProvider router={router} />)
  expect(await screen.findByLabelText('项目名称')).toBeDisabled()
  expect(screen.queryByRole('button', { name: /保\s*存/ })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '撤回修改' })).not.toBeInTheDocument()
  expect(historyGet).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('tab', { name: '项目协管' }))
  expect(screen.queryByRole('button', { name: /授权协管/ })).not.toBeInTheDocument()
})
