import { beforeEach, expect, it, vi } from 'vitest'
import { ConfigProvider } from 'antd'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import type { ProjectDocument } from '../api/projectDocuments'
import VehicleDocumentsPanel from './VehicleDocumentsPanel'
const h = vi.hoisted(() => ({ list: vi.fn(), upload: vi.fn(), download: vi.fn(), auth: { user: { id: 'worker1', role: 'worker', permission_overrides: {}, permission_version: 1 } as any } }))
vi.mock('../stores/auth', () => ({ useAuth: () => h.auth }))
vi.mock('../api/projectDocuments', () => ({ projectDocumentsApi: { list: h.list, upload: h.upload }, downloadDocumentResource: h.download }))
function row(change: Partial<ProjectDocument> = {}): ProjectDocument {
  return { id: 'doc-real-car-1', requirement_id: null, definition_id: 'definition-1', stage_key: '6', code: '6.1', name: '到场点检表', template_no: '', required: true, scope: 'vehicle', platform: null, timing_type: 'after_event', timing_event: 'vehicle_arrival', timing_offset_hours: 24, timing_weekday: null, trigger_type: null, blank_file_id: null, sort_order: 0, note: '', source_metadata: null, vehicle_unit_id: 'real-car-1', vehicle_label: 'AGV-001', period_key: null, trigger_ref: null, due_at: '2026-10-20T16:00:00Z', due_is_estimated: false, due_basis: { kind: 'actual_date_anchor', rule: 'after_event', timezone: 'Asia/Shanghai', actual_date: '2026-10-20', precision: 'date' }, due_state: 'overdue', effective_owner_name: '资料负责人', status: 'pending', waived_reason: '', confidential: false, external_visible: false, external_never_visible: false, submitted_at: null, submitted_by: null, version: 2, versions: [], latest_version: null, applicable: true, ...change }
}
function response(documents = [row()], submit = true) { return { documents, definitions: [], unclassified_files: [], permissions: { manage: true, submit }, timezone: 'Asia/Shanghai', version: 1 } }
function show(props = { projectId: 'p1', unitId: 'real-car-1', unitLabel: 'AGV-001', projectStatus: 'executing' }) {
  return render(<ConfigProvider theme={{ token: { motion: false } }}><VehicleDocumentsPanel {...props} /></ConfigProvider>)
}
beforeEach(() => { vi.clearAllMocks(); h.auth.user = { id: 'worker1', role: 'worker', permission_overrides: {}, permission_version: 1 }; h.list.mockResolvedValue(response()); h.upload.mockResolvedValue({ documents: [] }); h.download.mockResolvedValue(undefined) })
it('uses the real vehicle filter, canonical instance and project-local deadline basis', async () => {
  h.list.mockResolvedValue(response([row(), row({ id: 'other-doc', name: '另一台车的资料', vehicle_unit_id: 'real-car-2' })]))
  show()
  expect(await screen.findByText('6.1 到场点检表')).toBeVisible()
  expect(h.list).toHaveBeenCalledWith('p1', { vehicle_unit_id: 'real-car-1' })
  expect(screen.queryByText(/另一台车的资料/)).not.toBeInTheDocument()
  expect(screen.getByText(/2026-10-21 00:00/)).toBeVisible()
  expect(screen.getByText(/未记录实际时刻/)).toBeVisible()
  expect(screen.getByText(/资料负责人/)).toBeVisible()
  expect(screen.getByRole('link', { name: '在资料清单查看此车' })).toHaveAttribute('href', '/pm/projects/p1/documents?vehicle=real-car-1')
})
it('pre-entry uploads one version to the same document and blocks rapid duplicate clicks', async () => {
  let finish: (value: unknown) => void = () => undefined
  h.upload.mockImplementation(() => new Promise(resolve => { finish = resolve }))
  const version = { id: 'ver-1', attachment_id: 'file-1', filename: '真实点检.txt', uploaded_by_name: '现场人员', uploaded_at: '2026-10-20T16:01:00Z', download_url: '/projects/p1/documents/doc-real-car-1/versions/ver-1/download' }
  h.list.mockResolvedValueOnce(response()).mockResolvedValue(response([row({ status: 'submitted', latest_version: version as any, versions: [version as any] })]))
  show({ projectId: 'p1', unitId: 'real-car-1', unitLabel: 'AGV-001', projectStatus: 'preparing' })
  fireEvent.click(await screen.findByRole('button', { name: '上传资料' }))
  const dialog = within(screen.getByRole('dialog'))
  expect(dialog.getByRole('button', { name: '提交资料' })).toBeDisabled()
  const file = new File(['real inspection'], '真实点检.txt', { type: 'text/plain' })
  fireEvent.change(document.querySelector('input[type="file"]')!, { target: { files: [file] } })
  fireEvent.change(screen.getByLabelText('该车资料版本备注'), { target: { value: '逐车实测记录' } })
  await waitFor(() => expect(dialog.getByRole('button', { name: '提交资料' })).not.toBeDisabled())
  fireEvent.click(dialog.getByRole('button', { name: '提交资料' })); fireEvent.click(dialog.getByRole('button', { name: /提交资料/ }))
  await waitFor(() => expect(h.upload).toHaveBeenCalledExactlyOnceWith('p1', { file, documentIds: ['doc-real-car-1'], note: '逐车实测记录' }))
  await act(async () => { finish({ documents: [] }) })
  expect(await screen.findByText('已提交')).toBeVisible()
  expect(await screen.findByRole('button', { name: '下载最新版本' })).toBeVisible()
  expect(h.list).toHaveBeenCalledTimes(2)
})
it('keeps file and note after failure for explicit retry, without automatic replay', async () => {
  h.upload.mockRejectedValue({ isAxiosError: true, response: { data: { detail: '网络未确认' } } })
  show(); fireEvent.click(await screen.findByRole('button', { name: '上传资料' }))
  const file = new File(['original'], '原点检.txt', { type: 'text/plain' })
  fireEvent.change(document.querySelector('input[type="file"]')!, { target: { files: [file] } })
  fireEvent.change(screen.getByLabelText('该车资料版本备注'), { target: { value: '保留原说明' } })
  const dialog = within(screen.getByRole('dialog'))
  await waitFor(() => expect(dialog.getByRole('button', { name: '提交资料' })).not.toBeDisabled())
  fireEvent.click(dialog.getByRole('button', { name: '提交资料' }))
  await waitFor(() => expect(h.upload).toHaveBeenCalledTimes(1))
  await screen.findAllByText(/网络未确认/)
  await waitFor(() => expect(dialog.getByText('已选择：原点检.txt')).toBeVisible())
  expect(screen.getByLabelText('该车资料版本备注')).toHaveValue('保留原说明')
})
it('retains download and shared history while submission permission is revoked', async () => {
  h.auth.user.permission_overrides = { 'worker.deliver': false }
  const versions = [1, 2].map(i => ({ id: `version-${i}`, attachment_id: `file-${i}`, filename: `参数${i}.txt`, uploaded_by_name: '原上传人', uploaded_at: '2026-10-20T08:00:00Z', note: `版本${i}`, download_url: `/projects/p1/documents/doc-real-car-1/versions/version-${i}/download` }))
  h.list.mockResolvedValue(response([row({ status: 'submitted', versions: versions as any, latest_version: versions[1] as any })]))
  show()
  fireEvent.click(await screen.findByRole('button', { name: '下载最新版本' }))
  expect(h.download).toHaveBeenCalledWith(versions[1].download_url, '参数2.txt')
  expect(screen.queryByRole('button', { name: '上传新版本' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '版本历史（2）' }))
  const history = within(screen.getByRole('list', { name: '到场点检表版本历史' }))
  fireEvent.click(history.getAllByRole('button', { name: '下载此版本' })[1])
  expect(h.download).toHaveBeenLastCalledWith(versions[0].download_url, '参数1.txt')
})
it('shows a retryable read failure without claiming the vehicle has no documents', async () => {
  h.list.mockRejectedValueOnce(new Error('network')).mockResolvedValue(response())
  show()
  expect(await screen.findByText('该车资料读取失败')).toBeVisible()
  expect(screen.queryByText('该车暂无已生成资料')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '重试读取' }))
  expect(await screen.findByText('6.1 到场点检表')).toBeVisible()
})
it('ignores a previous vehicle response after switching the selected real car', async () => {
  let old: (value: unknown) => void = () => undefined
  h.list.mockImplementation((_pid, filter) => filter.vehicle_unit_id === 'real-car-1' ? new Promise(resolve => { old = resolve }) : Promise.resolve(response([row({ name: '第二台实车点检', vehicle_unit_id: 'real-car-2' })])))
  const ui = show()
  ui.rerender(<ConfigProvider theme={{ token: { motion: false } }}><VehicleDocumentsPanel projectId="p1" unitId="real-car-2" unitLabel="AGV-002" projectStatus="executing" /></ConfigProvider>)
  expect(await screen.findByText('6.1 第二台实车点检')).toBeVisible()
  await act(async () => { old(response()) })
  expect(screen.queryByText('6.1 到场点检表')).not.toBeInTheDocument()
  expect(h.upload).not.toHaveBeenCalled()
})
