import { setOfflineAccount } from '../../offline/queue'
import { beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import TemplateLibraryPage from './TemplateLibraryPage'

const { get, post, auth } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), auth: { user: { id: 'admin', role: 'admin' } as any } }))
vi.mock('../../api/client', () => ({ api: { get, post }, errMsg: () => '失败' }))
vi.mock('../../stores/auth', () => ({ useAuth: () => auth }))
vi.mock('../../hooks/useVehicleTypes', () => ({ useVehicleTypes: () => ({ options: [{ id: '1', name: '叉车式', is_enabled: true, sort_order: 1 }, { id: '2', name: '潜伏式', is_enabled: true, sort_order: 2 }] }),
  toVehicleTypeSelectOptions: (options: { name: string }[]) => options.map(o => ({ label: o.name, value: o.name })) }))

const templates = [
  { id: 'default', name: '系统默认模板', description: '标准 AGV 实施', is_system: true, version: 1, summary: { work: { '5': 4, '6': 41, '7': 4 }, documents: { '4': 5, '6': 32 }, vehicle_steps: 5 } },
  { id: 't2', name: '叉车模板', is_system: false, vehicle_type: '叉车式', status: 'draft', version: 2, usage_count: 3, summary: { work: { '6': 10 }, documents: {}, vehicle_steps: 3 } },
]
beforeEach(() => {
  setOfflineAccount('admin'); vi.clearAllMocks(); auth.user = { id: 'admin', role: 'admin' }
  get.mockResolvedValue({ data: templates }); post.mockResolvedValue({ data: { id: 'new-id' } })
})
function Where() { const l = useLocation(); return <output aria-label="当前地址">{l.pathname}{l.search}</output> }
const show = () => render(<ConfigProvider theme={{ token: { motion: false } }}><MemoryRouter initialEntries={['/pm/templates']}><Routes>
  <Route path="/pm/templates" element={<TemplateLibraryPage />} />
  <Route path="*" element={<Where />} />
</Routes></MemoryRouter></ConfigProvider>)

it('shows every template as a simple card with its totals, without versions or publish states', async () => {
  show()
  const card = (await screen.findByRole('button', { name: '打开模板「系统默认模板」' })).closest('li')!
  expect(card).toHaveTextContent('49 项工作')
  expect(card).toHaveTextContent('37 份资料')
  expect(card).toHaveTextContent('5 个车辆环节')
  expect(card).toHaveTextContent('通用')
  const other = screen.getByRole('button', { name: '打开模板「叉车模板」' }).closest('li')!
  expect(other).toHaveTextContent('叉车式')
  expect(other).not.toHaveTextContent('草稿')
  expect(other).not.toHaveTextContent('v2')
  expect(other).toHaveTextContent('已用于 3 个项目')
})

it('a card opens its template; the footer starts a project from it', async () => {
  show()
  fireEvent.click(await screen.findByRole('button', { name: '打开模板「叉车模板」' }))
  expect(screen.getByLabelText('当前地址')).toHaveTextContent('/pm/templates/t2')
})

it('starts a project from a template', async () => {
  show()
  const card = (await screen.findByRole('button', { name: '打开模板「叉车模板」' })).closest('li')!
  fireEvent.click(within(card).getByRole('button', { name: '用它新建项目' }))
  expect(screen.getByLabelText('当前地址')).toHaveTextContent('/pm/projects?create=1&template=t2')
})

it('creates a template for a vehicle type that has none yet and opens it', async () => {
  show()
  fireEvent.click(await screen.findByRole('button', { name: /新建模板/ }))
  expect(await screen.findByLabelText('模板名称')).toHaveValue('潜伏式模板')
  fireEvent.click(screen.getByRole('button', { name: '创建并打开' }))
  await waitFor(() => expect(post).toHaveBeenCalledWith('/templates', { name: '潜伏式模板', copy_from: 'default', vehicle_type: '潜伏式' }))
  expect(await screen.findByLabelText('当前地址')).toHaveTextContent('/pm/templates/new-id')
})

it('readers without template management do not see the create button', async () => {
  auth.user = { id: 'pm', role: 'pm', permission_overrides: { 'system.templates.manage': false } }
  show(); await screen.findByRole('button', { name: '打开模板「系统默认模板」' })
  expect(screen.queryByRole('button', { name: /新建模板/ })).not.toBeInTheDocument()
})

it('lists vehicle types without their own template, one click starts one', async () => {
  show()
  const hint = (await screen.findByText(/还没有专用模板的车型/)).closest('p')!
  expect(hint).not.toHaveTextContent('叉车式')
  fireEvent.click(within(hint).getByRole('button', { name: '潜伏式' }))
  expect(await screen.findByLabelText('模板名称')).toHaveValue('潜伏式模板')
  expect(screen.queryByText('全部并入标准模板')).not.toBeInTheDocument()
})
