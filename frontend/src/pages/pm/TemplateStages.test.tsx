import { setOfflineAccount } from '../../offline/queue'
import { beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { work } from '../../test/workItems'
import TemplateEditorPage from './TemplateEditorPage'

const { get, put, post, del } = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), post: vi.fn(), del: vi.fn() }))
vi.mock('../../api/client', () => ({ api: { get, put, post, delete: del }, errMsg: (e: any) => e?.message ?? '失败' }))
vi.mock('../../stores/auth', () => ({ useAuth: () => ({ user: { id: 'admin', role: 'admin' } }) }))
vi.mock('../../hooks/useVehicleTypes', () => ({ useVehicleTypes: () => ({ options: [] }) }))
vi.mock('./TemplateDocumentsTab', () => ({ default: () => <div>资料要求列表</div> }))
vi.mock('./TemplateProcurementsTab', () => ({ default: () => <div>采购物料清单</div> }))

const phases = () => [
  { id: 'prep', name: '进场准备', color: '#1677ff', stage_key: '5', work_items: [
    work({ id: 'w-survey', phase_id: 'prep', name: '场地勘测', group_label: '进场准备', check_definitions: [{ name: '勘测记录', is_required: true, is_safety_critical: false }] }),
    work({ id: 'w-net', phase_id: 'prep', name: '网络布线', group_label: '' })] },
  { id: 'single', name: '单车调试', color: '#1677ff', stage_key: '6', work_items: [work({ id: 'w-nav', phase_id: 'single', name: '导航调试', kind: 'vehicle', vehicle_step_key: 'debug', group_label: '' })] },
  { id: 'empty', name: '空分组', color: '#1677ff', stage_key: '6', work_items: [] },
]
const layoutOf = (call: any[]) => Object.fromEntries(call[1].groups.map((g: any) => [g.id, `${g.stage_key}:${g.item_ids.join(',')}`]))
beforeEach(() => {
  setOfflineAccount('admin'); vi.clearAllMocks()
  get.mockImplementation(async (url: string) => ({ data: url === '/templates' ? [{ id: 't1', name: '叉车模板', description: '重载', is_system: false, status: 'draft', version: 2, usage_count: 3 }]
    : url.endsWith('/work-items') ? { phases: phases() } : url.endsWith('/vehicle-steps') ? [{ key: 'arrive', name: '到场点检' }, { key: 'debug', name: '单车调试' }]
    : url.endsWith('/document-requirements') ? [{ stage_key: '4', is_group: false }, { stage_key: '6', is_group: false }, { stage_key: '6', is_group: true }] : [] }))
  put.mockImplementation(async (url: string, body: any) => ({ data: url.endsWith('/work-layout') ? { phases: phases() } : body }))
  post.mockImplementation(async (url: string, body: any) => ({ data: url.endsWith('/work-items') ? work({ id: `new-${body.name}`, phase_id: body.phase_id, name: body.name, group_label: '', check_definitions: [] })
    : url.endsWith('/work-phases') ? { id: 'g-new', name: body.name, stage_key: body.stage_key, color: '#1677ff', work_items: [] } : {} }))
  del.mockResolvedValue({ data: {} })
})
function Where() { const l = useLocation(); return <output aria-label="当前地址">{l.pathname}{l.search}</output> }
const show = (path = '/pm/templates/t1') => render(<ConfigProvider theme={{ token: { motion: false } }}><MemoryRouter initialEntries={[path]}><Routes>
  <Route path="/pm/templates/:templateId" element={<><TemplateEditorPage /><Where /></>} />
  <Route path="*" element={<Where />} />
</Routes></MemoryRouter></ConfigProvider>)
const region = (name: string) => screen.getByRole('region', { name })
const enter = (el: HTMLElement) => { fireEvent.keyDown(el, { key: 'Enter', code: 'Enter', keyCode: 13 }); fireEvent.keyUp(el, { key: 'Enter', code: 'Enter', keyCode: 13 }) }

it('lays work out by stage and group with counts on the tabs', async () => {
  show()
  expect(await screen.findByText('场地勘测')).toBeInTheDocument()
  expect(screen.getByLabelText('模板名称')).toHaveValue('叉车模板')
  expect(screen.getByText('已用于 3 个项目')).toBeInTheDocument()
  expect(screen.getByRole('tab', { name: /工作\s*3/ })).toHaveAttribute('aria-selected', 'true')
  expect(screen.getByRole('tab', { name: /资料\s*2/ })).toBeInTheDocument()
  expect(region('6 · 实施')).toHaveTextContent('导航调试')
  expect(region('4 · 内部启动会')).toHaveTextContent('暂无工作')
  expect(within(region('工作分组：进场准备')).getAllByText('进场准备')).toHaveLength(1)
  expect(region('工作分组：空分组')).toHaveTextContent('还没有工作项')
  expect(screen.getByRole('complementary', { name: '编辑说明' })).toHaveTextContent('改动会自动保存')
})

it('adds work items one after another with Enter, and groups in a chosen stage', async () => {
  show(); await screen.findByText('场地勘测')
  fireEvent.click(screen.getByRole('button', { name: '在「进场准备」添加工作项' }))
  const input = screen.getByLabelText('新工作项名称')
  fireEvent.change(input, { target: { value: '临时用电' } }); enter(input)
  await waitFor(() => expect(post).toHaveBeenCalledTimes(1))
  expect(post.mock.calls[0]).toEqual(['/templates/t1/work-items', { phase_id: 'prep', name: '临时用电', kind: 'other', description: '', group_label: '', vehicle_step_key: null, applicable_vehicle_types: [], scope_conditions: [], checks: [] }])
  expect(await within(region('工作分组：进场准备')).findByText('临时用电')).toBeInTheDocument()
  const again = screen.getByLabelText('新工作项名称')
  fireEvent.change(again, { target: { value: '消防通道' } }); enter(again)
  await waitFor(() => expect(post).toHaveBeenCalledTimes(2))
  fireEvent.keyDown(screen.getByLabelText('新工作项名称'), { key: 'Escape' })
  expect(screen.queryByLabelText('新工作项名称')).not.toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: '在「验收」添加工作分组' }))
  const group = screen.getByLabelText('新分组名称')
  fireEvent.change(group, { target: { value: '培训准备' } }); enter(group)
  await waitFor(() => expect(post).toHaveBeenCalledWith('/templates/t1/work-phases', { name: '培训准备', stage_key: '7' }))
  expect(await screen.findByRole('region', { name: '工作分组：培训准备' })).toBeInTheDocument()
  expect(screen.getByLabelText('新工作项名称')).toBeInTheDocument()
})

it('edits check requirements in the panel and deletes the item', async () => {
  show(); fireEvent.click(await screen.findByRole('button', { name: /场地勘测/ }))
  const side = await screen.findByRole('complementary', { name: '编辑工作项：场地勘测' })
  expect(side.querySelector('.tpl-panel-kicker')).toHaveTextContent('5 · 发车前 / 进场准备')
  fireEvent.click(within(side).getByRole('button', { name: /添加检查/ }))
  const check = within(side).getByLabelText('检查要求2')
  fireEvent.change(check, { target: { value: '地面平整度' } }); fireEvent.blur(check)
  await waitFor(() => expect(put).toHaveBeenCalledTimes(1))
  expect(put.mock.calls[0]).toEqual(['/templates/t1/work-items/w-survey', { checks: [
    { name: '勘测记录', description: '', is_required: true, is_safety_critical: false },
    { name: '地面平整度', description: '', is_required: true, is_safety_critical: false }], version: 7 }])
  fireEvent.click(within(side).getAllByRole('checkbox', { name: '安全关键' })[1])
  await waitFor(() => expect(put).toHaveBeenCalledTimes(2))
  expect(put.mock.calls[1][1].checks[1]).toMatchObject({ name: '地面平整度', is_safety_critical: true })

  fireEvent.click(within(side).getByRole('button', { name: /删除工作项/ }))
  fireEvent.click(await screen.findByRole('button', { name: /^删\s*除$/ }))
  await waitFor(() => expect(del).toHaveBeenCalledWith('/templates/t1/work-items/w-survey'))
  await waitFor(() => expect(screen.queryByText('场地勘测')).not.toBeInTheDocument())
})

it('moves an item with the arrows or by dragging, saving the whole order', async () => {
  show(); fireEvent.click(await screen.findByRole('button', { name: /场地勘测/ }))
  const side = await screen.findByRole('complementary', { name: '编辑工作项：场地勘测' })
  expect(within(side).getByRole('button', { name: '上移' })).toBeDisabled()
  fireEvent.click(within(side).getByRole('button', { name: '下移' }))
  await waitFor(() => expect(put).toHaveBeenCalledTimes(1))
  expect(put.mock.calls[0][0]).toBe('/templates/t1/work-layout')
  expect(layoutOf(put.mock.calls[0])).toEqual({ prep: '5:w-net,w-survey', single: '6:w-nav', empty: '6:' })

  // drag 导航调试 into the empty group
  const transfer = { setData: vi.fn(), effectAllowed: '', dropEffect: '' }
  const source = screen.getByText('导航调试').closest('li')!
  const target = within(region('工作分组：空分组')).getByRole('button', { name: /收起分组/ }).parentElement!
  fireEvent.dragStart(source, { dataTransfer: transfer })
  fireEvent.dragOver(target, { dataTransfer: transfer })
  fireEvent.drop(target, { dataTransfer: transfer })
  await waitFor(() => expect(put).toHaveBeenCalledTimes(2))
  expect(layoutOf(put.mock.calls[1])).toEqual({ prep: '5:w-survey,w-net', single: '6:', empty: '6:w-nav' })
})

it('a refused order is rolled back and the template reloaded', async () => {
  put.mockRejectedValueOnce(Object.assign(new Error('模板已被其他人修改，请刷新后再调整顺序'), { response: { status: 409 } }))
  show(); fireEvent.click(await screen.findByRole('button', { name: /场地勘测/ }))
  const loads = get.mock.calls.filter(([url]) => url.endsWith('/work-items')).length
  fireEvent.click(within(await screen.findByRole('complementary', { name: '编辑工作项：场地勘测' })).getByRole('button', { name: '下移' }))
  expect(await screen.findByText('模板已被其他人修改，请刷新后再调整顺序')).toBeInTheDocument()
  await waitFor(() => expect(get.mock.calls.filter(([url]) => url.endsWith('/work-items')).length).toBe(loads + 1))
  expect([...region('工作分组：进场准备').querySelectorAll('.tpl-node-name')].map(n => n.textContent)).toEqual(['场地勘测', '网络布线'])
})

it('groups are renamed, moved to another stage or deleted from one menu', async () => {
  show(); await screen.findByText('场地勘测')
  fireEvent.click(screen.getByRole('button', { name: '分组「进场准备」操作' }))
  fireEvent.click(await screen.findByText('重命名'))
  const name = screen.getByLabelText('分组名称')
  fireEvent.change(name, { target: { value: '进场勘测' } }); enter(name)
  await waitFor(() => expect(put).toHaveBeenCalledWith('/templates/t1/work-phases/prep', { name: '进场勘测' }))

  fireEvent.click(screen.getByRole('button', { name: '分组「进场勘测」操作' }))
  fireEvent.mouseEnter(await screen.findByText('移到其他阶段'))
  fireEvent.click(await screen.findByText('移到 4 · 内部启动会'))
  await waitFor(() => expect(put).toHaveBeenCalledWith('/templates/t1/work-phases/prep', { stage_key: '4' }))
  await waitFor(() => expect(region('4 · 内部启动会')).toHaveTextContent('进场勘测'))

  fireEvent.click(screen.getByRole('button', { name: '分组「空分组」操作' }))
  fireEvent.click(await screen.findByText('删除分组'))
  fireEvent.click(await screen.findByRole('button', { name: /^删\s*除$/ }))
  await waitFor(() => expect(del).toHaveBeenCalledWith('/templates/t1/work-phases/empty'))
})

it('the template name and description save when you leave them; the menu can delete the template', async () => {
  show(); await screen.findByText('场地勘测')
  const name = screen.getByLabelText('模板名称')
  fireEvent.change(name, { target: { value: '叉车重载模板' } }); fireEvent.blur(name)
  await waitFor(() => expect(put).toHaveBeenCalledWith('/templates/t1', { name: '叉车重载模板', description: '重载' }))
  fireEvent.click(screen.getByRole('button', { name: '更多模板操作' }))
  fireEvent.click(await screen.findByText('删除模板'))
  fireEvent.click(await screen.findByRole('button', { name: /删除模板/ }))
  await waitFor(() => expect(del).toHaveBeenCalledWith('/templates/t1'))
  await waitFor(() => expect(screen.getByLabelText('当前地址')).toHaveTextContent(/^\/pm\/templates$/))
})

it('vehicle steps are renamed and added in place; a step with work cannot be deleted', async () => {
  show(); await screen.findByText('场地勘测')
  fireEvent.click(screen.getByRole('tab', { name: /车辆环节/ }))
  expect(screen.getByLabelText('当前地址')).toHaveTextContent('/pm/templates/t1?tab=steps')
  expect(await screen.findByRole('button', { name: '车辆环节2仍有关联工作，不能删除' })).toBeDisabled()
  const first = screen.getByLabelText('车辆环节1名称')
  fireEvent.change(first, { target: { value: '到场检查' } }); fireEvent.blur(first)
  await waitFor(() => expect(put).toHaveBeenCalledWith('/templates/t1/vehicle-steps', { steps: [{ key: 'arrive', name: '到场检查' }, { key: 'debug', name: '单车调试' }] }))
  const add = screen.getByLabelText('新车辆环节名称')
  fireEvent.change(add, { target: { value: '防撞测试' } }); enter(add)
  await waitFor(() => expect(put).toHaveBeenCalledTimes(2))
  expect(put.mock.calls[1][1].steps.map((s: any) => s.name)).toEqual(['到场检查', '单车调试', '防撞测试'])
  fireEvent.click(screen.getByRole('tab', { name: /采购物料/ }))
  expect(await screen.findByText('采购物料清单')).toBeInTheDocument()
})

it('opens the tab named in the address and returns to the library', async () => {
  show('/pm/templates/t1?tab=documents')
  expect(await screen.findByText('资料要求列表')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '返回模板库' }))
  expect(screen.getByLabelText('当前地址')).toHaveTextContent(/^\/pm\/templates$/)
})
