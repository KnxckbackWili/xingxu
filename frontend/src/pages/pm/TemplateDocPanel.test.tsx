import { fireEvent, render as rtlRender, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { ConfigProvider } from 'antd'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { setOfflineAccount } from '../../offline/queue'
import TemplateEditorPage from './TemplateEditorPage'
// Document requirements are edited on the one-page template editor: rows in their stage, the panel beside them.
const { get, post, put, del, auth, data } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(), auth: { user: { id: 'admin', role: 'admin' } as any }, data: { docs: [] as any[], fail: false } }))
vi.mock('../../api/client', () => ({ api: { get, post, put, delete: del }, errMsg: () => '操作失败' }))
vi.mock('../../stores/auth', () => ({ useAuth: () => auth }))
vi.mock('../../hooks/useVehicleTypes', () => ({ useVehicleTypes: () => ({ options: [] }), toVehicleTypeSelectOptions: () => [] }))
const Editor = ({ editMode = true }: { editMode?: boolean; templateId?: string }) => { auth.user = editMode ? { id: 'admin', role: 'admin' } : { id: 'reader', role: 'pm', permission_overrides: { 'system.templates.manage': false } }; return <TemplateEditorPage /> }
const TemplateDocumentsTab = Editor
const render = (ui: React.ReactElement) => rtlRender(ui, { wrapper: ({ children }) => <ConfigProvider theme={{ token: { motion: false } }}><MemoryRouter initialEntries={['/pm/templates/default']}><Routes><Route path="/pm/templates/:templateId" element={children} /></Routes></MemoryRouter></ConfigProvider> })
const docs = (rows: any[]) => { data.docs = rows }
const row = (extra = {}) => ({ id: 'r1', stage_key: '6', code: '6.2', name: '生命周期表', template_no: '模板9', is_group: false, parent_id: null, required: true, scope: 'project', platform: null, timing_type: 'weekly', timing_event: null, timing_offset_hours: null, timing_weekday: 7, trigger_type: null, confidential_default: false, external_visible_default: false, external_never_visible: false, sort_order: 1, note: '', blank_file: null, ...extra })
const panel = () => screen.findByRole('complementary', { name: /资料要求/ })
const type = (field: HTMLElement, value: string) => fireEvent.change(field, { target: { value } })
beforeEach(() => { setOfflineAccount('admin'); vi.clearAllMocks(); data.docs = [row()]; data.fail = false
  get.mockImplementation(async (url: string) => {
    if (url === '/templates') return { data: [{ id: 'default', name: '系统模板', is_system: true }] }
    if (url.endsWith('/work-items')) return { data: { phases: [] } }
    if (url.endsWith('/document-requirements')) { if (data.fail) throw new Error('offline'); return { data: data.docs } }
    return { data: [] }
  }); post.mockResolvedValue({ data: { id: 'created' } }); put.mockResolvedValue({ data: {} }); del.mockResolvedValue({ data: {} }) })

it('只读显示资料规则和阶段分节，面板不可改', async () => {
  render(<TemplateDocumentsTab templateId="default" editMode={false} />)
  expect(await screen.findByText('生命周期表')).toBeVisible()
  expect(screen.getByText('每周日')).toBeVisible()
  expect(screen.getByRole('region', { name: '实施' })).toHaveTextContent('生命周期表')
  expect(screen.getByRole('region', { name: '交付' })).toHaveTextContent('这个阶段没有要交的资料')
  expect(screen.queryByRole('button', { name: /添加资料/ })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /6\.2.*生命周期表/ }))
  const side = await panel()
  expect(within(side).getByLabelText('资料名称')).toBeDisabled()
  expect(within(side).queryByRole('button', { name: /上传空白模板/ })).not.toBeInTheDocument()
  expect(within(side).queryByRole('button', { name: /删除/ })).not.toBeInTheDocument()
})
it('资料读取失败时提示，刷新后恢复', async () => {
  data.fail = true
  render(<TemplateDocumentsTab templateId="default" editMode />)
  expect(await screen.findAllByText('资料读取失败，请刷新')).not.toHaveLength(0)
  data.fail = false
  fireEvent.click(screen.getByRole('button', { name: /刷新模板/ }))
  expect(await screen.findByText('生命周期表')).toBeVisible()
})
it('改动自动保存完整规则字段；保存失败保留输入并提示', async () => {
  put.mockRejectedValueOnce({ response: { data: { detail: '保存测试失败' } } })
  render(<TemplateDocumentsTab templateId="default" editMode />)
  fireEvent.click(await screen.findByRole('button', { name: /6\.2.*生命周期表/ }))
  const side = await panel()
  type(within(side).getByLabelText('资料名称'), '生命周期表修订')
  expect(await within(side).findByText('保存测试失败')).toBeVisible()
  expect(within(side).getByLabelText('资料名称')).toHaveValue('生命周期表修订')
  expect(put.mock.calls[0][0]).toBe('/templates/default/document-requirements/r1')
  expect(put.mock.calls[0][1]).toMatchObject({ name: '生命周期表修订', timing_type: 'weekly', timing_weekday: 7, timing_event: null, timing_offset_hours: null, parent_id: null })
  type(within(side).getByLabelText('资料名称'), '生命周期表二修')
  expect(await within(side).findByText('已保存')).toBeVisible()
  expect(put).toHaveBeenCalledTimes(2)
})
it('保密开关清除并禁用默认对外可见；全周期的隐藏启动事件不会丢失', async () => {
  docs([row({ timing_type: 'lifetime', timing_event: 'internal_kickoff', timing_weekday: null, external_visible_default: true })])
  render(<TemplateDocumentsTab templateId="default" editMode />)
  fireEvent.click(await screen.findByRole('button', { name: /6\.2.*生命周期表/ }))
  const side = await panel()
  fireEvent.click(within(side).getByLabelText('默认保密'))
  expect(within(side).getByLabelText('默认对外可见')).toBeDisabled()
  await waitFor(() => expect(put).toHaveBeenCalledTimes(1))
  expect(put.mock.calls[0][1]).toMatchObject({ confidential_default: true, external_visible_default: false, timing_type: 'lifetime', timing_event: 'internal_kickoff', timing_weekday: null })
})
it('每周规则缺少星期时不保存；连续输入只发送一次请求', async () => {
  docs([row({ timing_weekday: null })])
  const view = render(<TemplateDocumentsTab templateId="default" editMode />)
  fireEvent.click(await screen.findByRole('button', { name: /6\.2.*生命周期表/ }))
  type(within(await panel()).getByLabelText('资料名称'), '改名')
  expect(await screen.findByText('每周规则必须选择星期')).toBeVisible()
  expect(put).not.toHaveBeenCalled()
  view.unmount()
  docs([row()])
  render(<TemplateDocumentsTab templateId="default" editMode />)
  fireEvent.click(await screen.findByRole('button', { name: /6\.2.*生命周期表/ }))
  const name = within(await panel()).getByLabelText('资料名称')
  type(name, '生'); type(name, '生命'); type(name, '生命周期')
  await waitFor(() => expect(put).toHaveBeenCalledTimes(1))
  expect(put.mock.calls[0][1]).toMatchObject({ name: '生命周期' })
})
it('切换到别的资料前，先保存还没发出的改动', async () => {
  docs([row(), row({ id: 'r2', code: '6.3', name: '问题清单' })])
  render(<TemplateDocumentsTab templateId="default" editMode />)
  fireEvent.click(await screen.findByRole('button', { name: /6\.2.*生命周期表/ }))
  type(within(await panel()).getByLabelText('资料名称'), '生命周期表A')
  fireEvent.click(screen.getByRole('button', { name: /6\.3.*问题清单/ }))
  await waitFor(() => expect(put).toHaveBeenCalledTimes(1))
  expect(put.mock.calls[0]).toEqual(['/templates/default/document-requirements/r1', expect.objectContaining({ name: '生命周期表A' })])
  expect(within(await screen.findByRole('complementary', { name: /6\.3 问题清单/ })).getByLabelText('资料名称')).toHaveValue('问题清单')
})
it('legacy sources stay read-only and classification explicitly chooses a current stage without rewriting the source', async () => {
  const source = { source_type: 'template_task', original_stage: '公司评审', original: { name: '旧启动资料' } }
  docs([row({ stage_key: 'legacy', code: 'legacy-old', name: '旧启动资料', source_metadata: source })])
  render(<TemplateDocumentsTab templateId="default" editMode />)
  expect(await screen.findByText('历史来源（只读）')).toBeInTheDocument()
  expect(screen.getByText(/"original_stage": "公司评审"/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /legacy-old.*旧启动资料/ }))
  const side = await panel()
  type(within(side).getByLabelText('资料名称'), '旧启动资料')
  await new Promise(resolve => setTimeout(resolve, 700))
  expect(put).not.toHaveBeenCalled()
  fireEvent.mouseDown(within(side).getByLabelText('阶段'))
  fireEvent.click(await screen.findByText('内部启动会', { selector: '.ant-select-item-option-content' }))
  type(within(side).getByLabelText('编号'), '4.1')
  await waitFor(() => expect(put).toHaveBeenCalledTimes(1))
  expect(put.mock.calls[0][1]).toMatchObject({ stage_key: '4', code: '4.1', name: '旧启动资料' })
  expect(put.mock.calls[0][1]).not.toHaveProperty('source_metadata')
})
it('新增资料要求需点“添加”；删除和空白模板在面板里', async () => {
  docs([row({ blank_file: { id: 'f', filename: '周期表.xlsx', file_size: 1, sha256: 'x' } })])
  render(<TemplateDocumentsTab templateId="default" editMode />)
  fireEvent.click(within(await screen.findByRole('region', { name: '资料：6' })).getByRole('button', { name: '在此阶段添加资料' }))
  const fresh = await screen.findByRole('complementary', { name: '新增资料要求' })
  type(within(fresh).getByLabelText('编号'), '6.9'); type(within(fresh).getByLabelText('资料名称'), '巡检记录')
  await new Promise(resolve => setTimeout(resolve, 700))
  expect(post).not.toHaveBeenCalled()
  fireEvent.click(within(fresh).getByRole('button', { name: /添加资料要求/ }))
  await waitFor(() => expect(post).toHaveBeenCalledTimes(1))
  expect(post.mock.calls[0][1]).toMatchObject({ stage_key: '6', code: '6.9', name: '巡检记录', timing_type: 'on_demand' })

  fireEvent.click(screen.getByRole('button', { name: /6\.2.*生命周期表/ }))
  const side = await screen.findByRole('complementary', { name: /6\.2 生命周期表/ })
  expect(within(side).getByRole('button', { name: /周期表\.xlsx/ })).toBeInTheDocument()
  expect(within(side).getByRole('button', { name: /替换空白模板6\.2/ })).toBeInTheDocument()
  fireEvent.click(within(side).getByRole('button', { name: /删除资料要求/ }))
  fireEvent.click(await screen.findByRole('button', { name: /^删\s*除$/ }))
  await waitFor(() => expect(del).toHaveBeenCalledWith('/templates/default/document-requirements/r1'))
})
it('搜索只留下匹配的阶段', async () => {
  docs([row(), row({ id: 'r2', stage_key: '4', code: '4.1', name: '启动会纪要', required: false })])
  render(<TemplateDocumentsTab templateId="default" editMode />)
  expect(await screen.findByRole('region', { name: '内部启动会' })).toHaveTextContent('非必需')
  fireEvent.change(screen.getByLabelText('查找模板内容'), { target: { value: '生命' } })
  expect(screen.queryByRole('region', { name: '内部启动会' })).not.toBeInTheDocument()
  expect(screen.getByRole('region', { name: '实施' })).toHaveTextContent('生命周期表')
})
it('deadlines are shown and edited in days while the hours stay exact', async () => {
  docs([row({ timing_type: 'before_event', timing_event: 'ship', timing_offset_hours: 168, timing_weekday: null })])
  render(<TemplateDocumentsTab templateId="default" editMode />)
  expect(await screen.findByText('发车前 7 天')).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: /6\.2.*生命周期表/ }))
  const days = within(await panel()).getByLabelText('相隔天数')
  expect(days).toHaveValue('7')
  type(days, '3')
  await waitFor(() => expect(put).toHaveBeenCalledTimes(1))
  expect(put.mock.calls[0][1]).toMatchObject({ timing_offset_hours: 72, timing_type: 'before_event', timing_event: 'ship' })
})
