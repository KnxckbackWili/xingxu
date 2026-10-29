import { setOfflineAccount } from '../../offline/queue'
import { beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import { work } from '../../test/workItems'
import TemplateEditorPage from './TemplateEditorPage'

const { get, put, post, del } = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), post: vi.fn(), del: vi.fn() }))
vi.mock('../../api/client', () => ({ api: { get, put, post, delete: del }, errMsg: () => '失败' }))
vi.mock('../../stores/auth', () => ({ useAuth: () => ({ user: { id: 'admin', role: 'admin' } }) }))
vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn() }))
vi.mock('../../hooks/useVehicleTypes', () => ({ useVehicleTypes: () => ({ options: [] }) }))
vi.mock('./TemplateDocumentsTab', () => ({ default: ({ stageKey }: { stageKey?: string }) => <div>资料列表：阶段{stageKey}</div> }))
vi.mock('./TemplateProcurementsTab', () => ({ default: () => <div>采购物料清单</div> }))
vi.mock('../../components/TemplateVehicleSteps', () => ({ default: () => null }))

const phases = [
  { id: 'prep', name: '进场准备', color: '#1677ff', stage_key: '5', work_items: [work({ id: 'w-survey', phase_id: 'prep', name: '场地勘测' })] },
  { id: 'single', name: '单车调试', color: '#1677ff', stage_key: '6', work_items: [work({ id: 'w-nav', phase_id: 'single', name: '导航调试', kind: 'vehicle', vehicle_step_key: 'debug' })] },
  { id: 'empty', name: '空分组', color: '#1677ff', stage_key: '6', work_items: [] },
]
beforeEach(() => {
  setOfflineAccount('admin'); vi.clearAllMocks()
  get.mockImplementation(async (url: string) => ({ data: url === '/templates' ? [{ id: 'default', name: '系统默认模板', is_system: true }]
    : url.endsWith('/work-items') ? { phases } : url.endsWith('/vehicle-steps') ? [{ key: 'arrive', name: '到场点检' }, { key: 'debug', name: '单车调试' }]
    : url.endsWith('/document-requirements') ? [{ stage_key: '4', is_group: false }, { stage_key: '6', is_group: false }, { stage_key: '6', is_group: true }] : [] }))
  put.mockResolvedValue({ data: {} }); post.mockResolvedValue({ data: {} }); del.mockResolvedValue({ data: {} })
})
const show = () => render(<ConfigProvider theme={{ token: { motion: false } }}><TemplateEditorPage /></ConfigProvider>)
const stageButton = (name: RegExp) => within(screen.getByRole('list', { name: '模板阶段' })).getByRole('button', { name })

it('opens on the first stage with work and shows that stage only', async () => {
  show()
  expect(await screen.findByText('场地勘测')).toBeInTheDocument()
  expect(screen.queryByText('导航调试')).not.toBeInTheDocument()
  expect(screen.getByText('采购物料清单')).toBeInTheDocument()
  expect(screen.getByText('资料列表：阶段5')).toBeInTheDocument()
  expect(stageButton(/实施/)).toHaveTextContent('1 工作 · 1 资料')
})

it('the implementation stage lists its groups, vehicle steps and no procurement', async () => {
  show(); await screen.findByText('场地勘测')
  fireEvent.click(stageButton(/实施/))
  expect(await screen.findByText('导航调试')).toBeInTheDocument()
  expect(screen.getByRole('region', { name: '工作分组：空分组' })).toHaveTextContent('还没有工作项')
  const steps = screen.getByText('车辆环节').closest('section')!
  expect(within(steps).getByText('单车调试')).toBeInTheDocument()
  expect(within(steps).getByText('1 项逐车工作')).toBeInTheDocument()
  expect(within(steps).getByText('暂无逐车工作')).toBeInTheDocument()
  expect(screen.queryByText('采购物料清单')).not.toBeInTheDocument()
  expect(screen.getByText('资料列表：阶段6')).toBeInTheDocument()
})

it('adds a work group to the current stage and moves a group to another stage', async () => {
  show(); await screen.findByText('场地勘测')
  fireEvent.click(screen.getByRole('button', { name: '添加工作分组' }))
  fireEvent.change(await screen.findByLabelText('工作分组名称'), { target: { value: '现场踏勘' } })
  fireEvent.click(screen.getByRole('button', { name: '保存分组' }))
  await waitFor(() => expect(post).toHaveBeenCalledWith('/templates/default/work-phases', { name: '现场踏勘', stage_key: '5' }))
  fireEvent.click(screen.getByRole('button', { name: '把分组「进场准备」移到其他阶段' }))
  fireEvent.click(await screen.findByText('移到 4 · 内部启动会'))
  await waitFor(() => expect(put).toHaveBeenCalledWith('/templates/default/work-phases/prep', { stage_key: '4' }))
})

it('only an empty group offers deletion', async () => {
  show(); await screen.findByText('场地勘测')
  expect(screen.queryByRole('button', { name: '删除分组「进场准备」' })).not.toBeInTheDocument()
  fireEvent.click(stageButton(/实施/))
  expect(await screen.findByRole('button', { name: '删除分组「空分组」' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '删除分组「单车调试」' })).not.toBeInTheDocument()
})
