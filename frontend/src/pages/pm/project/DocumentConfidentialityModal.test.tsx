import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import { beforeEach, expect, it, vi } from 'vitest'
import type { ProjectDocument } from '../../../api/projectDocuments'

const h = vi.hoisted(() => ({ members: vi.fn(), policy: vi.fn(), close: vi.fn(), saved: vi.fn(), dirty: vi.fn() }))
vi.mock('../../../api/projectDocuments', () => ({ projectDocumentsApi: { confidentialityMembers: h.members, setConfidentiality: h.policy } }))
import DocumentConfidentialityModal from './DocumentConfidentialityModal'

const document: ProjectDocument = { id: 'd1', requirement_id: null, definition_id: 'r1', stage_key: '6', code: '6.11.6b', name: '服务器位置说明', template_no: '', required: true, scope: 'project', platform: null, timing_type: 'weekly', timing_event: null, timing_offset_hours: null, timing_weekday: 5, trigger_type: null, blank_file_id: null, sort_order: 0, note: '', source_metadata: null, vehicle_unit_id: null, vehicle_label: '', period_key: '2026-W44', trigger_ref: null, due_at: null, due_is_estimated: false, status: 'pending', waived_reason: '', confidential: false, confidential_user_ids: [], external_visible: false, external_never_visible: true, submitted_at: null, submitted_by: null, version: 7, versions: [], latest_version: null, applicable: true }
const target = { kind: 'document' as const, row: document }
const show = (projectId = 'p1', disabled = false) => render(<ConfigProvider theme={{ token: { motion: false } }}><DocumentConfidentialityModal projectId={projectId} target={target} disabled={disabled} onClose={h.close} onSaved={h.saved} onDirtyChange={h.dirty} /></ConfigProvider>)

beforeEach(() => { vi.resetAllMocks(); h.members.mockResolvedValue([{ id: 'person-1', display_name: '指定工程师' }]); h.policy.mockResolvedValue({}); h.saved.mockResolvedValue(undefined) })

it('explains all periods and history, and submits the exact scope and CAS version once', async () => {
  let finish: (value: unknown) => void = () => {}
  h.policy.mockImplementation(() => new Promise(resolve => { finish = resolve }))
  show(); const modal = within(await screen.findByRole('dialog'))
  await waitFor(() => expect(modal.getByText(/全部期次、历史版本和以后生成项/)).toBeVisible())
  await waitFor(() => expect(modal.getByRole('switch', { name: '保密' })).toBeEnabled())
  fireEvent.click(modal.getByRole('switch', { name: '保密' }))
  fireEvent.mouseDown(modal.getByRole('combobox', { name: '指定可见人员' }))
  fireEvent.click(await screen.findByText('指定工程师'))
  const save = modal.getByRole('button', { name: '保存保密范围' }); fireEvent.click(save); fireEvent.click(save)
  await waitFor(() => expect(h.policy).toHaveBeenCalledExactlyOnceWith('p1', 'document', 'd1', { confidential: true, confidential_user_ids: ['person-1'], version: 7 }))
  await act(async () => finish({}))
  await waitFor(() => expect(h.saved).toHaveBeenCalledTimes(1)); expect(h.close).toHaveBeenCalledTimes(1)
})

it('keeps stale-version failures visible and does not silently retry or close', async () => {
  h.policy.mockRejectedValue({ isAxiosError: true, response: { status: 409, data: { detail: '保密范围版本已变化' } } })
  show(); const modal = within(await screen.findByRole('dialog'))
  await waitFor(() => expect(modal.getByRole('button', { name: '保存保密范围' })).toBeEnabled())
  fireEvent.click(modal.getByRole('button', { name: '保存保密范围' }))
  await waitFor(() => expect(modal.getByText('保密范围版本已变化')).toBeVisible())
  expect(modal.getByRole('button', { name: '保存保密范围' })).toBeDisabled()
  expect(h.policy).toHaveBeenCalledTimes(1); expect(h.close).not.toHaveBeenCalled(); expect(h.saved).not.toHaveBeenCalled()
})

it('does not let a disabled or lost-owner session save a grant', async () => {
  show('p1', true); const modal = within(await screen.findByRole('dialog'))
  expect(modal.getByRole('switch', { name: '保密' })).toBeDisabled()
  fireEvent.click(modal.getByRole('button', { name: '保存保密范围' }))
  expect(h.policy).not.toHaveBeenCalled()
})
