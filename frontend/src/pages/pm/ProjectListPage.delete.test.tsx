import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { ConfigProvider } from 'antd'
import ProjectListPage from './ProjectListPage'
import { projectApi, type Project } from '../../api'
const { navigate } = vi.hoisted(() => ({ navigate: vi.fn() }))
vi.mock('react-router-dom', () => ({ useNavigate: () => navigate, useSearchParams: () => [new URLSearchParams(), vi.fn()] }))
vi.mock('../../stores/auth', () => ({ useAuth: () => ({ user: { id: 'pm1', role: 'pm' } }) }))
vi.mock('../../api', () => ({ projectApi: { list: vi.fn(), remove: vi.fn(), get: vi.fn() } }))
vi.mock('../../api/client', () => ({ api: { get: vi.fn(async () => ({ data: [] })), post: vi.fn() }, errMsg: () => '请求失败' }))
vi.mock('../../hooks/useVehicleTypes', () => ({ useVehicleTypes: () => ({ options: [], loading: false, error: null }), toVehicleTypeSelectOptions: () => [] }))
const project: Project = { id: 'p1', name: '归档项目', abbreviation: 'QA', manager: 'pm1', version: 3, can_delete: true, capabilities: ['project.delete'], client: '', location: '', start_date: '2026-10-01', end_date: '2026-10-07', status: 'archived', description: '', members: ['pm1'], created_at: '2026-10-01T00:00:00Z' }
beforeEach(() => { vi.clearAllMocks(); vi.mocked(projectApi.list).mockResolvedValue([project, { ...project, id: 'p2', name: '仅查看项目', can_delete: false, capabilities: [] }]); vi.mocked(projectApi.remove).mockResolvedValue({ message: '已删除', project_id: 'p1', deletion_id: 'd1', version: 4, backup: { available: true, sha256: 'fixture', bytes: 90 } }) })
it.each(['table', 'card'])('directly deletes an authorized archived project in the %s list and preserves the other row', async view => {
 localStorage.setItem('agvpm_proj_view', view); render(<ConfigProvider theme={{ token: { motion: false } }}><ProjectListPage /></ConfigProvider>)
 fireEvent.click(await screen.findByRole('button', { name: '删除项目：归档项目' }))
 expect(screen.queryByRole('button', { name: '删除项目：仅查看项目' })).not.toBeInTheDocument(); expect(navigate).not.toHaveBeenCalled()
 fireEvent.click(await screen.findByRole('button', { name: '备份并删除' }))
 await waitFor(() => expect(screen.queryByText('归档项目')).not.toBeInTheDocument()); expect(screen.getByText('仅查看项目')).toBeInTheDocument()
 expect(projectApi.remove).toHaveBeenCalledWith('p1', { version: 3 }); expect(navigate).not.toHaveBeenCalled()
 fireEvent.click(screen.getByRole('button', { name: '项目回收站' })); expect(navigate).toHaveBeenCalledWith('/pm/project-recycle-bin')
})
