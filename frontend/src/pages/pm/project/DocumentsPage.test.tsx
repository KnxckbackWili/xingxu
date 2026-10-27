import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import { UploadQueuedError } from '../../../uploads/types'
import { beforeEach, expect, it, vi } from 'vitest'
import { createMemoryRouter, RouterProvider, useParams } from 'react-router-dom'
import { ProjectCapabilitiesContext, ProjectStatusContext } from '../../../hooks/useProjectCapability'
import type { ProjectDocument, ProjectDocumentsResponse } from '../../../api/projectDocuments'
const h = vi.hoisted(() => ({ list: vi.fn(), upload: vi.fn(), submit: vi.fn(), status: vi.fn(), review: vi.fn(), download: vi.fn(), files: vi.fn(), remove: vi.fn(), package: vi.fn(), members: vi.fn(), policy: vi.fn(), owner: vi.fn(), generateLifecycle: vi.fn(), generateContact: vi.fn(), generateInventory: vi.fn(), auth: { user: { id: 'me', role: 'admin', permission_version: 1 } }, state: { status: 'executing' } }))
vi.mock('../../../stores/auth', () => ({ useAuth: () => h.auth }))
vi.mock('../../../api/projectDocuments', () => ({ projectDocumentsApi: { list: h.list, upload: h.upload, submit: h.submit, setStatus: h.status, review: h.review, assignOwner: h.owner, files: h.files, deleteFile: h.remove, confidentialityMembers: h.members, setConfidentiality: h.policy, generateLifecycle: h.generateLifecycle, generateContact: h.generateContact, generateInventory: h.generateInventory }, downloadDocumentResource: h.download, downloadSelectedDocuments: h.package }))
vi.mock('./ProjectDocumentRequirementEditor', () => ({ default: () => null }))
vi.mock('./ProcurementPanel', () => ({ default: () => <div>采购明细面板</div> }))
vi.mock('./AcceptanceRecordsPanel', () => ({ default: () => <div>验收记录面板</div> }))
vi.mock('./EntryReviewPanel', () => ({ default: () => <div>评审记录面板</div> }))
import DocumentsPage from './DocumentsPage'
function row(id = 'd1', patch: Partial<ProjectDocument> = {}): ProjectDocument {
  return { id, requirement_id: null, definition_id: 'r1', stage_key: '4', code: id === 'd1' ? '4.1' : '4.2', name: `项目资料${id}`, template_no: '', required: true, scope: 'project', platform: null, timing_type: 'on_demand', timing_event: null, timing_offset_hours: null, timing_weekday: null, trigger_type: null, blank_file_id: null, sort_order: 0, note: '', source_metadata: null, vehicle_unit_id: null, vehicle_label: '', period_key: null, trigger_ref: null, due_at: null, due_is_estimated: false, status: 'pending', waived_reason: '', confidential: false, external_visible: false, external_never_visible: false, submitted_at: null, submitted_by: null, version: 7, versions: [], latest_version: null, applicable: true, ...patch }
}
const response = (documents = [row()]): ProjectDocumentsResponse => ({ documents, definitions: [], unclassified_files: [], permissions: { manage: true, submit: true }, timezone: 'Asia/Shanghai', version: 1 })
function show(capabilities = ['project.manage_plan', 'project.update'], initialPath = '/p1') {
  const Page = () => <ProjectStatusContext.Provider value={h.state.status}><ProjectCapabilitiesContext.Provider value={capabilities}><DocumentsPage projectId={useParams().id!} /></ProjectCapabilitiesContext.Provider></ProjectStatusContext.Provider>
  const router = createMemoryRouter([{ path: '/:id', element: <Page /> }], { initialEntries: [initialPath] })
  render(<ConfigProvider theme={{ token: { motion: false } }}><RouterProvider router={router} /></ConfigProvider>)
  return router
}
beforeEach(() => { vi.resetAllMocks(); h.auth.user = { id: 'me', role: 'admin', permission_version: 1 }; h.state.status = 'executing'; h.list.mockResolvedValue(response()); h.files.mockResolvedValue([]); h.upload.mockResolvedValue({}); h.status.mockResolvedValue({}); h.review.mockResolvedValue({}); h.owner.mockResolvedValue({}); h.download.mockResolvedValue(undefined); h.package.mockResolvedValue(undefined); h.members.mockResolvedValue([{ id: 'person-1', display_name: '指定工程师' }]); h.policy.mockResolvedValue({}) })
it('shows date precision and exposes real owner assignment with the current version', async () => {
  h.list.mockResolvedValue({ ...response([row('d1', { name: '到场点检', timing_type: 'after_event', due_at: '2026-11-02T04:00:00Z',
    due_basis: { kind: 'actual_date_anchor', rule: 'after_event', timezone: 'America/New_York', precision: 'date', actual_date: '2026-11-01' },
    effective_owner_name: '原负责人', owner_warning: '原负责人已停用' })]), owner_options: [{ id: 'u1', name: '张工' }] })
  show()
  expect(await screen.findByText(/按实际到场日 2026-11-01/)).toHaveTextContent('未记录实际时刻')
  fireEvent.click(screen.getByRole('button', { name: '指派负责人' }))
  const modal = within(screen.getByRole('dialog'))
  fireEvent.mouseDown(modal.getByRole('combobox', { name: '资料负责人' }))
  fireEvent.click(screen.getByText('张工', { selector: '.ant-select-item-option-content' }))
  fireEvent.click(modal.getByRole('button', { name: '保存负责人' }))
  await waitFor(() => expect(h.owner).toHaveBeenCalledExactlyOnceWith('p1', 'd1', 'u1', 7))
})
it('filters server-defined current-week work separately from on-demand inspections', async () => {
  const weekly = row('weekly', { code: '6.2', name: '本周生命周期', timing_type: 'weekly', period_key: '2026-W44', due_at: '2026-11-01T15:59:59Z' })
  h.list.mockResolvedValue({ ...response([weekly, row('random', { name: '抽查变更单' })]), document_actions: {
    this_week_count: 1, this_week: [{ id: 'weekly', document_id: 'weekly', code: '6.2', name: weekly.name, due_at: weekly.due_at, due_is_estimated: false, due_state: 'upcoming', period_key: weekly.period_key, vehicle_label: '', overdue_days: 0 }],
    overdue_count: 0, overdue: [], estimated_past_due_count: 0, on_demand: [], owner_warnings: [], period_key: '2026-W44', timezone: 'Asia/Shanghai', as_of: '2026-10-27T10:00:00Z',
  } })
  show(); await screen.findByText(/6.2 本周生命周期/)
  fireEvent.click(screen.getByText('本周待交', { selector: '.ant-segmented-item-label' }))
  expect(screen.queryByText(/抽查变更单/)).toBeNull()
  fireEvent.click(screen.getByText('抽查', { selector: '.ant-segmented-item-label' }))
  expect(screen.getByText(/抽查变更单/)).toBeVisible()
  expect(screen.queryByText(/6.2 本周生命周期/)).toBeNull()
})
it('requires a real file and submits one actual upload to all selected requirements', async () => {
  h.list.mockResolvedValue(response([row(), row('d2')]))
  show(); await screen.findByText(/4.1 项目资料d1/)
  const checks = screen.getAllByRole('checkbox'); fireEvent.click(checks[1]); fireEvent.click(checks[2])
  fireEvent.click(screen.getByRole('button', { name: '同一文件提交所选资料' }))
  const modal = within(screen.getByRole('dialog'))
  expect(modal.getByRole('button', { name: '确认提交' })).toBeDisabled()
  const file = new File(['real evidence'], '项目清单.pdf', { type: 'application/pdf' })
  fireEvent.change(modal.getByLabelText('选择资料文件'), { target: { files: [file] } })
  const save = modal.getByRole('button', { name: '确认提交' }); fireEvent.click(save); fireEvent.click(save)
  await waitFor(() => expect(h.upload).toHaveBeenCalledExactlyOnceWith('p1', { file, documentIds: ['d1', 'd2'], note: '' }))
  expect(h.submit).not.toHaveBeenCalled()
})
it('preserves file, notes and selected requirement when upload fails', async () => {
  h.upload.mockRejectedValue({ isAxiosError: true, response: { data: { detail: '存储空间不足' } } })
  show(); fireEvent.click(await screen.findByRole('button', { name: '提交文件' }))
  const modal = within(screen.getByRole('dialog')); const file = new File(['proof'], '证据.txt')
  fireEvent.change(modal.getByLabelText('选择资料文件'), { target: { files: [file] } }); fireEvent.change(modal.getByLabelText('本次提交说明'), { target: { value: '保留草稿说明' } })
  fireEvent.click(modal.getByRole('button', { name: '确认提交' }))
  await waitFor(() => expect(modal.getByText('存储空间不足')).toBeVisible())
  expect(modal.getByLabelText('本次提交说明')).toHaveValue('保留草稿说明')
  expect(modal.getByRole('button', { name: '确认提交' })).toBeEnabled()
  fireEvent.click(modal.getByRole('button', { name: '确认提交' }))
  await waitFor(() => expect(h.upload).toHaveBeenCalledTimes(2))
  expect(h.upload.mock.calls[1][1]).toEqual({ file, documentIds: ['d1'], note: '保留草稿说明' })
})
it('retains unknown counts on failed load and offers a real retry', async () => {
  h.list.mockRejectedValueOnce(new Error('offline'))
  show(); expect(await screen.findByText('资料清单加载失败')).toBeVisible()
  expect(screen.queryByText('当前筛选没有资料')).toBeNull(); expect(screen.queryByRole('button', { name: '上传资料或文件' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: /重\s*试/ })); expect(await screen.findByText(/4.1 项目资料d1/)).toBeVisible()
})
it('ignores an older project response after navigation', async () => {
  let old: (value: ProjectDocumentsResponse) => void = () => {}
  h.list.mockImplementationOnce(() => new Promise(resolve => { old = resolve })).mockResolvedValueOnce(response([row('new', { name: '新项目资料' })]))
  const router = show(); await act(async () => { await router.navigate('/p2') })
  expect(await screen.findByText(/新项目资料/)).toBeVisible()
  await act(async () => old(response([row('old', { name: '旧项目资料' })])))
  expect(screen.queryByText(/旧项目资料/)).toBeNull()
})
it.each(['archived', 'legacy_unknown'])('%s keeps files readable and hides all write controls', async status => {
  h.state.status = status; h.list.mockResolvedValue({ ...response(), unclassified_files: [{ id: 'f1', filename: '历史文件.pdf', file_size: 2, content_type: 'application/pdf', sha256: null, uploaded_by: null, uploaded_by_name: '', uploaded_at: null, confidential: false, entity_type: 'project', entity_id: 'p1', category: '', download_url: '/files/f1/download' }] })
  show(); fireEvent.click(await screen.findByRole('button', { name: /历史文件.pdf/ }))
  await waitFor(() => expect(h.download).toHaveBeenCalledWith('/files/f1/download', '历史文件.pdf'))
  expect(screen.queryByRole('button', { name: '上传资料或文件' })).toBeNull(); expect(screen.queryByRole('button', { name: /删\s*除/ })).toBeNull(); expect(screen.queryByRole('button', { name: '提交文件' })).toBeNull()
})
it('requires an explanation and current row version for waiver', async () => {
  show(); fireEvent.click(await screen.findByRole('button', { name: '不适用' }))
  const modal = within(screen.getByRole('dialog')); expect(modal.getByRole('button', { name: '保存理由' })).toBeDisabled()
  fireEvent.change(modal.getByLabelText('资料状态修改理由'), { target: { value: '客户合同明确不要求' } }); fireEvent.click(modal.getByRole('button', { name: '保存理由' }))
  await waitFor(() => expect(h.status).toHaveBeenCalledWith('p1', expect.objectContaining({ id: 'd1', version: 7 }), 'waived', '客户合同明确不要求'))
})
it('shows all versions and historical optional review while preventing self review', async () => {
  const v = { id: 'v1', attachment_id: 'a1', filename: '已交证据.pdf', file_size: 12, sha256: null, uploaded_by: 'me', uploaded_by_name: '本人', uploaded_at: '2026-10-01T00:00:00Z', note: '第一版', review_metadata: { latest_review: { decision: 'rejected', note: '补充说明', by_name: '复核人员', at: '2026-10-02T00:00:00Z' }, review_history: [] }, download_url: '/projects/p1/documents/d1/versions/v1/download' }
  h.list.mockResolvedValue(response([row('d1', { status: 'submitted', versions: [v], latest_version: v })]))
  show(); fireEvent.click(await screen.findByRole('button', { name: /版本记录 1/ }))
  const drawer = within(await screen.findByRole('dialog')); await waitFor(() => expect(drawer.getByText('已退回')).toBeVisible()); expect(drawer.queryByRole('button', { name: '审核通过' })).toBeNull()
  fireEvent.click(drawer.getByRole('button', { name: /下载此版本/ })); expect(h.download).toHaveBeenCalledWith(v.download_url, v.filename)
  expect(screen.getByText(/已提交 1/)).toBeVisible()
})
it('retains platform history without making it selectable or pending for the current platform', async () => {
  h.list.mockResolvedValue(response([row('d1', { applicable: false, platform: 'NDC' })])); show()
  expect(await screen.findByText('原平台资料，保留历史')).toBeVisible(); expect(screen.queryByRole('button', { name: '提交文件' })).toBeNull()
  expect(screen.getByText(/0 项资料 · 待交 0/)).toBeVisible()
  const checks = screen.getAllByRole('checkbox'); expect(checks[checks.length - 1]).toBeDisabled()
})

it('submits the date explicitly written on a signoff and retains it after an upload error', async () => {
  h.list.mockResolvedValue(response([row('d1', {code:'6.10.2',timing_type:'after_milestone',timing_event:'commissioning_done'})]))
  h.upload.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({})
  show();fireEvent.click(await screen.findByRole('button',{name:'提交文件'}))
  const modal=within(screen.getByRole('dialog'))
  await waitFor(()=>expect(modal.getByText(/上传时间不会作为实际发生时间/)).toBeVisible())
  const file=new File(['signed evidence'],'signed.txt',{type:'text/plain'})
  fireEvent.change(modal.getByLabelText('选择资料文件'),{target:{files:[file]}})
  fireEvent.change(modal.getByLabelText('调试完工签单实际日期'),{target:{value:'2026-01-02'}})
  fireEvent.click(modal.getByRole('button',{name:'确认提交'}))
  await waitFor(()=>expect(h.upload).toHaveBeenCalledTimes(1))
  expect(modal.getByLabelText('调试完工签单实际日期')).toHaveValue('2026-01-02')
  await waitFor(()=>expect(modal.getByRole('button',{name:'确认提交'})).toBeEnabled())
  fireEvent.click(modal.getByRole('button',{name:'确认提交'}))
  await waitFor(()=>expect(h.upload).toHaveBeenCalledTimes(2))
  expect(h.upload.mock.calls[1]).toEqual(['p1',{file,documentIds:['d1'],note:'',milestoneDates:{commissioning_done:'2026-01-02'}}])
})

it('read-only export users can package selected evidence without gaining upload or requirement controls', async () => {
  h.auth.user.role = 'readonly'; h.list.mockResolvedValue({ ...response(), permissions: { manage: false, submit: false } })
  show(['project.export']); await screen.findByText(/4.1 项目资料d1/)
  fireEvent.click(screen.getAllByRole('checkbox')[1]); fireEvent.click(screen.getByRole('button', { name: '打包所选资料（最新版本）' }))
  await waitFor(() => expect(h.package).toHaveBeenCalledExactlyOnceWith('p1', ['d1']))
  expect(screen.queryByRole('button', { name: /上传资料或文件/ })).toBeNull(); expect(h.upload).not.toHaveBeenCalled()
})

it('does not infer confidential management from the global administrator role', async () => {
  show(); await screen.findByText(/4.1 项目资料d1/)
  expect(screen.getByText(/账号密码类信息建议使用密码管理工具/)).toBeVisible()
  expect(screen.queryByRole('button', { name: '保密范围' })).toBeNull()
})

it('applies an owner-selected independent confidential scope in the first upload request', async () => {
  h.list.mockResolvedValue({ ...response(), permissions: { manage: true, submit: true, manage_confidentiality: true } })
  show(); await screen.findByText(/4.1 项目资料d1/)
  fireEvent.click(screen.getByRole('button', { name: /上传资料或文件/ }))
  const modal = within(await screen.findByRole('dialog'))
  fireEvent.click(modal.getByRole('switch', { name: '上传附件额外保密' }))
  await waitFor(() => expect(modal.getByRole('combobox', { name: '上传附件指定可见人员' })).toBeEnabled())
  fireEvent.mouseDown(modal.getByRole('combobox', { name: '上传附件指定可见人员' }))
  fireEvent.click(await screen.findByText('指定工程师'))
  const file = new File(['private from birth'], 'private.txt', { type: 'text/plain' })
  fireEvent.change(modal.getByLabelText('选择资料文件'), { target: { files: [file] } })
  fireEvent.click(modal.getByRole('button', { name: '确认提交' }))
  await waitFor(() => expect(h.upload).toHaveBeenCalledExactlyOnceWith('p1', {
    file, documentIds: [], note: '', confidential: true, confidentialUserIds: ['person-1'],
  }))
})

it('opens the precise document stage from overview guidance without changing submission facts', async () => {
  h.list.mockResolvedValue(response([row('d1'),row('d2',{stage_key:'6',code:'6.10.2',name:'调试签单'})]))
  const router=show()
  await screen.findByText(/4.1 项目资料d1/)
  await act(async()=>router.navigate('/p1?stage=6'))
  expect(await screen.findByText(/6.10.2 调试签单/)).toBeVisible()
  expect(screen.queryByText(/4.1 项目资料d1/)).not.toBeInTheDocument()
  expect(h.upload).not.toHaveBeenCalled()
})

it('uses the real vehicle deep link to filter the shared canonical instances', async () => {
  h.list.mockResolvedValue(response([
    row('car1', { scope: 'vehicle', vehicle_unit_id: 'real-car-1', vehicle_label: 'AGV-001', name: '第一台点检', code: '6.1' }),
    row('car2', { scope: 'vehicle', vehicle_unit_id: 'real-car-2', vehicle_label: 'AGV-002', name: '第二台点检', code: '6.1' }),
    row('project', { name: '项目资料应隐藏' }),
  ]))
  const router = show(undefined, '/p1?vehicle=real-car-1')
  expect(await screen.findByText(/6.1 第一台点检/)).toBeVisible()
  expect(screen.queryByText(/6.1 第二台点检/)).not.toBeInTheDocument()
  expect(screen.queryByText(/项目资料应隐藏/)).not.toBeInTheDocument()
  await act(async () => { await router.navigate('/p1?vehicle=real-car-2') })
  expect(await screen.findByText(/6.1 第二台点检/)).toBeVisible()
  expect(screen.queryByText(/6.1 第一台点检/)).not.toBeInTheDocument()
  expect(h.upload).not.toHaveBeenCalled()
})

it('hands off only a durable queued upload and does not display it as a submitted version', async () => {
  h.upload.mockRejectedValueOnce(new UploadQueuedError('stable-uuid'))
  show(); fireEvent.click(await screen.findByRole('button', { name: '提交文件' }))
  const modal = within(screen.getByRole('dialog'))
  fireEvent.change(modal.getByLabelText('选择资料文件'), { target: { files: [new File(['proof'], 'queued.txt')] } })
  fireEvent.click(modal.getByRole('button', { name: '确认提交' }))
  expect(await screen.findByText(/文件已保存到上传队列/)).toBeVisible()
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(screen.getByText(/已提交 0/)).toBeVisible()
  expect(screen.queryByText('资料已提交，新版本已保存')).toBeNull()
})

it('only offers the lifecycle generator for the server local current week and submits it once', async () => {
  const current = row('current', { stage_key: '6', code: '6.2', name: '本周系统表', timing_type: 'weekly', period_key: '2026-W44' })
  const old = row('old', { stage_key: '6', code: '6.2', name: '历史周次表', timing_type: 'weekly', period_key: '2026-W43' })
  h.list.mockResolvedValue({ ...response([current, old]), document_actions: { this_week_count: 0, this_week: [], overdue_count: 0, overdue: [], estimated_past_due_count: 0, on_demand: [], owner_warnings: [], period_key: '2026-W44', timezone: 'Pacific/Auckland', as_of: '2026-10-25T11:30:00Z' } })
  h.generateLifecycle.mockResolvedValue(current)
  show(); const button = await screen.findByRole('button', { name: '由系统生成本周生命周期表' })
  expect(screen.getAllByRole('button', { name: '由系统生成本周生命周期表' })).toHaveLength(1)
  fireEvent.click(button); fireEvent.click(button)
  await waitFor(() => expect(h.generateLifecycle).toHaveBeenCalledExactlyOnceWith('p1', 'current', {}))
})
