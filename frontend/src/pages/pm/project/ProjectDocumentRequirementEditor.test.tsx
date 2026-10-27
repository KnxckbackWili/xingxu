import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import { beforeEach, expect, it, vi } from 'vitest'
import type { ProjectDocumentDefinition } from '../../../api/projectDocuments'
const h = vi.hoisted(() => ({ create: vi.fn(), update: vi.fn(), close: vi.fn(), saved: vi.fn(), dirty: vi.fn() }))
vi.mock('../../../api/projectDocuments', () => ({ projectDocumentsApi: { createRequirement: h.create, updateRequirement: h.update } }))
vi.mock('../../../api/client', () => ({ errMsg: (e: any) => e?.response?.data?.detail ?? e.message }))
import ProjectDocumentRequirementEditor from './ProjectDocumentRequirementEditor'
const definition = (extra = {}): ProjectDocumentDefinition => ({ id: 'r1', source_key: 'manual-r1', requirement_id: null, stage_key: '9', code: '9.1', name: '项目责任书', template_no: '模板25', required: true, scope: 'project', platform: null, timing_type: 'lifetime', timing_event: 'internal_kickoff', timing_offset_hours: null, timing_weekday: null, trigger_type: null, blank_file_id: null, sort_order: 1, note: '', source_metadata: null, confidential_default: false, external_visible_default: true, external_never_visible: false, waiting_reason: null, instance_count: 1, ...extra })
function show(value: ProjectDocumentDefinition | 'new' = definition()) { return render(<ConfigProvider theme={{ token: { motion: false } }}><ProjectDocumentRequirementEditor canEdit projectId="p1" editing={value} onClose={h.close} onSaved={h.saved} onDirtyChange={h.dirty} /></ConfigProvider>) }
beforeEach(() => { vi.resetAllMocks(); h.create.mockResolvedValue({}); h.update.mockResolvedValue({}) })
it('preserves lifetime timing and directs existing confidentiality changes to the versioned scope editor', async () => {
  show(); const modal = within(await screen.findByRole('dialog')); expect(modal.getByLabelText('默认保密')).toBeDisabled(); await waitFor(() => expect(modal.getByText(/保密范围.*版本校验/)).toBeVisible()); fireEvent.click(modal.getByRole('button', { name: '保存要求' }))
  await waitFor(() => expect(h.update).toHaveBeenCalledTimes(1)); expect(h.update.mock.calls[0][2]).toMatchObject({ timing_type: 'lifetime', timing_event: 'internal_kickoff', confidential_default: false, external_visible_default: true }); expect(h.update.mock.calls[0][2]).not.toHaveProperty('source_metadata')
})
it('requires explicit current-stage classification for a legacy source', async () => {
  show(definition({ stage_key: 'legacy', code: 'legacy-r1', source_metadata: { original: { private: '历史记录' } } })); const modal = within(await screen.findByRole('dialog')); fireEvent.click(modal.getByRole('button', { name: '保存要求' }))
  expect(await modal.findByText('请将历史资料明确归类到第4–9阶段')).toBeInTheDocument(); expect(h.update).not.toHaveBeenCalled()
  fireEvent.mouseDown(modal.getByLabelText('阶段')); fireEvent.click(await screen.findByText('4 · 内部启动会')); fireEvent.change(modal.getByLabelText('编号'), { target: { value: '4.8' } }); fireEvent.click(modal.getByRole('button', { name: '保存要求' }))
  await waitFor(() => expect(h.update).toHaveBeenCalledTimes(1)); expect(h.update.mock.calls[0][2]).toMatchObject({ stage_key: '4', code: '4.8' }); expect(h.update.mock.calls[0][2]).not.toHaveProperty('source_metadata')
})
it('requires a weekly weekday and keeps failed saves editable without duplicate requests', async () => {
  const view = show(definition({ timing_type: 'weekly', timing_event: null, timing_weekday: null })); let modal = within(await screen.findByRole('dialog')); fireEvent.click(modal.getByRole('button', { name: '保存要求' })); expect(await modal.findByText('每周规则必须选择星期')).toBeInTheDocument(); expect(h.update).not.toHaveBeenCalled(); view.unmount()
  let fail: (reason: unknown) => void = () => {}; h.update.mockImplementation(() => new Promise((_resolve, reject) => { fail = reject })); show(); modal = within(await screen.findByRole('dialog')); fireEvent.change(modal.getByLabelText('资料名称'), { target: { value: '修改后责任书' } }); const save = modal.getByRole('button', { name: '保存要求' }); fireEvent.click(save); fireEvent.click(save)
  await waitFor(() => expect(h.update).toHaveBeenCalledTimes(1)); await act(async () => fail(new Error('保存失败，请重试'))); await waitFor(() => expect(modal.getByText('保存失败，请重试')).toBeVisible()); expect(modal.getByLabelText('资料名称')).toHaveValue('修改后责任书'); expect(h.close).not.toHaveBeenCalled()
})
