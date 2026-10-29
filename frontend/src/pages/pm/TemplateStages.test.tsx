import { setOfflineAccount } from '../../offline/queue'
import { beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { work } from '../../test/workItems'
import TemplateEditorPage from './TemplateEditorPage'

const { get, put, post, del } = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), post: vi.fn(), del: vi.fn() }))
vi.mock('../../api/client', () => ({ api: { get, put, post, delete: del }, errMsg: () => '失败' }))
vi.mock('../../stores/auth', () => ({ useAuth: () => ({ user: { id: 'admin', role: 'admin' } }) }))
vi.mock('../../hooks/useVehicleTypes', () => ({ useVehicleTypes: () => ({ options: [] }) }))
vi.mock('./TemplateDocumentsTab', () => ({ default: () => <div>资料要求列表</div> }))
vi.mock('./TemplateProcurementsTab', () => ({ default: () => <div>采购物料清单</div> }))
vi.mock('../../components/TemplateVehicleSteps', () => ({ default: () => null }))

const phases = [
  { id: 'prep', name: '进场准备', color: '#1677ff', stage_key: '5', work_items: [work({ id: 'w-survey', phase_id: 'prep', name: '场地勘测', group_label: '进场准备', check_definitions: [{ name: '勘测记录', is_required: true, is_safety_critical: false }] })] },
  { id: 'single', name: '单车调试', color: '#1677ff', stage_key: '6', work_items: [work({ id: 'w-nav', phase_id: 'single', name: '导航调试', kind: 'vehicle', vehicle_step_key: 'debug', group_label: '' })] },
  { id: 'empty', name: '空分组', color: '#1677ff', stage_key: '6', work_items: [] },
]
beforeEach(() => {
  setOfflineAccount('admin'); vi.clearAllMocks()
  get.mockImplementation(async (url: string) => ({ data: url === '/templates' ? [{ id: 'default', name: '系统默认模板', is_system: true, usage_count: 3 }]
    : url.endsWith('/work-items') ? { phases } : url.endsWith('/vehicle-steps') ? [{ key: 'arrive', name: '到场点检' }, { key: 'debug', name: '单车调试' }]
    : url.endsWith('/document-requirements') ? [{ stage_key: '4', is_group: false }, { stage_key: '6', is_group: false }, { stage_key: '6', is_group: true }] : [] }))
  put.mockResolvedValue({ data: {} }); post.mockResolvedValue({ data: {} }); del.mockResolvedValue({ data: {} })
})
function Where() { const l = useLocation(); return <output aria-label="当前地址">{l.pathname}{l.search}</output> }
const show = (path = '/pm/templates/default') => render(<ConfigProvider theme={{ token: { motion: false } }}><MemoryRouter initialEntries={[path]}><Routes>
  <Route path="/pm/templates/:templateId" element={<><TemplateEditorPage /><Where /></>} />
  <Route path="*" element={<Where />} />
</Routes></MemoryRouter></ConfigProvider>)

it('lays work out by stage with counts on the tabs and the stage index', async () => {
  show()
  expect(await screen.findByRole('heading', { name: '系统默认模板' })).toBeInTheDocument()
  expect(await screen.findByText('场地勘测')).toBeInTheDocument()
  expect(screen.getByText('已用于 3 个项目')).toBeInTheDocument()
  expect(screen.getByRole('tab', { name: /工作\s*2/ })).toHaveAttribute('aria-selected', 'true')
  expect(screen.getByRole('tab', { name: /资料\s*2/ })).toBeInTheDocument()
  const index = screen.getByRole('navigation', { name: '工作阶段目录' })
  expect(within(index).getByRole('button', { name: '跳到实施，1 项工作' })).toBeInTheDocument()
  expect(within(index).getByRole('button', { name: '跳到内部启动会，0 项工作' })).toBeInTheDocument()
  expect(screen.getByRole('region', { name: '6 · 实施' })).toHaveTextContent('导航调试')
  expect(screen.getByRole('region', { name: '4 · 内部启动会' })).toHaveTextContent('暂无工作')
  // a group label equal to its group is not repeated; the vehicle step is shown on the row
  expect(within(screen.getByRole('region', { name: '工作分组：进场准备' })).getAllByText('进场准备')).toHaveLength(1)
  expect(within(screen.getByRole('region', { name: '工作分组：单车调试' })).getAllByText('单车调试')).toHaveLength(2)
  expect(screen.getByRole('region', { name: '工作分组：空分组' })).toHaveTextContent('还没有工作项')
})

it('a row opens the details drawer and the editor is one step away', async () => {
  show(); fireEvent.click(await screen.findByRole('button', { name: /场地勘测/ }))
  const drawer = await screen.findByRole('dialog')
  expect(within(drawer).getByText('5 · 发车前 / 进场准备')).toBeInTheDocument()
  expect(within(drawer).getByText('勘测记录')).toBeInTheDocument()
  fireEvent.click(within(drawer).getByRole('button', { name: /编辑工作项/ }))
  expect(await screen.findByLabelText('工作项名称')).toHaveValue('场地勘测')
})

it('adds a group to a chosen stage and moves or deletes groups from one menu', async () => {
  show(); await screen.findByText('场地勘测')
  fireEvent.click(screen.getByRole('button', { name: '在「验收」添加工作分组' }))
  fireEvent.change(await screen.findByLabelText('工作分组名称'), { target: { value: '培训准备' } })
  fireEvent.click(screen.getByRole('button', { name: '保存分组' }))
  await waitFor(() => expect(post).toHaveBeenCalledWith('/templates/default/work-phases', { name: '培训准备', stage_key: '7' }))

  fireEvent.click(screen.getByRole('button', { name: '分组「进场准备」操作' }))
  fireEvent.mouseEnter(await screen.findByText('移到其他阶段'))
  fireEvent.click(await screen.findByText('移到 4 · 内部启动会'))
  await waitFor(() => expect(put).toHaveBeenCalledWith('/templates/default/work-phases/prep', { stage_key: '4' }))

  fireEvent.click(screen.getByRole('button', { name: '分组「空分组」操作' }))
  fireEvent.click(await screen.findByText('删除分组'))
  fireEvent.click(await screen.findByRole('button', { name: /删\s*除/ }))
  await waitFor(() => expect(del).toHaveBeenCalledWith('/templates/default/work-phases/empty'))
})

it('a group with work cannot be deleted', async () => {
  show(); await screen.findByText('场地勘测')
  fireEvent.click(screen.getByRole('button', { name: '分组「进场准备」操作' }))
  expect((await screen.findByText('删除分组（先移走工作项）')).closest('li')).toHaveAttribute('aria-disabled', 'true')
})

it('vehicle steps and procurement each have their own tab, kept in the address', async () => {
  show(); await screen.findByText('场地勘测')
  fireEvent.click(screen.getByRole('tab', { name: /车辆环节/ }))
  expect(await screen.findByText('暂无逐车工作')).toBeInTheDocument()
  expect(screen.getByLabelText('当前地址')).toHaveTextContent('/pm/templates/default?tab=steps')
  const debug = screen.getAllByRole('listitem').find(li => li.textContent?.startsWith('2单车调试'))!
  expect(debug).toHaveTextContent('导航调试')
  fireEvent.click(screen.getByRole('tab', { name: /采购物料/ }))
  expect(await screen.findByText('采购物料清单')).toBeInTheDocument()
})

it('opens the tab named in the address and returns to the library', async () => {
  show('/pm/templates/default?tab=documents')
  expect(await screen.findByText('资料要求列表')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '返回模板库' }))
  expect(screen.getByLabelText('当前地址')).toHaveTextContent(/^\/pm\/templates$/)
})
