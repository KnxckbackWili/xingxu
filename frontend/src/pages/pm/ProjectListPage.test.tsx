import { expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import ProjectListPage from './ProjectListPage'
import { api } from '../../api/client'
import { projectApi } from '../../api'
const { params, navigate, setSearchParams, auth } = vi.hoisted(() => {
  const params = new URLSearchParams('create=1')
  return { params, auth: { user: { role: 'pm' } as any }, navigate: vi.fn(), setSearchParams: vi.fn(() => {
    // The real router consumes ?create=1 once. A fresh setter on every render
    // would continually reopen/reset the wizard, unlike useSearchParams.
    for (const key of [...params.keys()]) params.delete(key)
  }) }
})
vi.mock('react-router-dom', () => ({ useNavigate: () => navigate, useSearchParams: () => [params, setSearchParams] }))
vi.mock('../../stores/auth', () => ({ useAuth: () => auth }))
vi.mock('../../api', () => ({ projectApi: { list: vi.fn().mockResolvedValue([]), create: vi.fn() } }))
vi.mock('../../api/client', () => ({ api: { get: vi.fn(), post: vi.fn() }, errMsg: () => 'error' }))
vi.mock('../../hooks/useVehicleTypes', () => ({ useVehicleTypes: () => ({ options: [], loading: false, error: null }), toVehicleTypeSelectOptions: () => [] }))

it('keeps other projects available when the dashboard lacks one progress value', async () => {
  params.delete('create')
  localStorage.setItem('agvpm_proj_view', 'table')
  const project = { id: 'live', name: '正常实施项目', abbreviation: '', manager: 'me',
    client: '客户', location: '上海', start_date: '2026-09-01', end_date: '2026-12-01',
    status: 'executing', description: '', members: ['me'], created_at: '2026-09-01T00:00:00Z' }
  vi.mocked(projectApi.list).mockResolvedValue([project, { ...project, id: 'unknown', name: '进度不可用项目'}])
  vi.mocked(api.get).mockImplementation(async url => {
    if (url === '/dashboard/overview') return { data: { projects: [{ id: 'live', percent: 65 }] } }
    return { data: [] }
  })
  render(<ConfigProvider theme={{ token: { motion: false } }}><ProjectListPage /></ConfigProvider>)
  expect(await screen.findByText('正常实施项目')).toBeVisible()
  expect(screen.getByText('65%')).toBeVisible()
  expect(screen.getByText('进度不可用项目')).toBeVisible()
  expect(screen.getByText('进度待核对')).toBeVisible()
  expect(screen.queryByText('项目进度与风险暂不可用')).not.toBeInTheDocument()
  expect(screen.queryByText('项目列表加载失败')).not.toBeInTheDocument()
})


