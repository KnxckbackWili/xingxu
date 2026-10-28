import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import { beforeEach, expect, it, vi } from 'vitest'
import { ProjectCapabilitiesContext, ProjectStatusContext } from '../../../hooks/useProjectCapability'
const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../../api/client', () => ({ api: { get: h.get, post: h.post }, errMsg: (e: any) => e?.response?.data?.detail ?? e?.message ?? '失败' }))
vi.mock('../../../stores/auth', () => ({ useAuth: () => ({ user: { id: 'pm', permission_version: 1 } }) }))
import EntryReviewPanel from './EntryReviewPanel'
const manifest = { met: [], unmet: [{ name: '安全条件', is_required: true }], entry_unmet: [{ name: '安全条件' }], risks: [], missing: [], review_token: 'token1' }
function show(can = true) { return render(<ConfigProvider theme={{ token: { motion: false } }}><ProjectStatusContext.Provider value="preparing"><ProjectCapabilitiesContext.Provider value={can ? ['project.manage_plan'] : []}><EntryReviewPanel projectId="p1" /></ProjectCapabilitiesContext.Provider></ProjectStatusContext.Provider></ConfigProvider>) }
beforeEach(() => { vi.resetAllMocks(); h.get.mockResolvedValue({ data: [] }); h.post.mockResolvedValue({ data: manifest }) })
it('opens loading immediately and requires a reason to approve real risk', async () => {
  let finish: (value: unknown) => void = () => {}; h.post.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  show(); fireEvent.click(screen.getByRole('button', { name: '核对发车前资料' })); expect(screen.getByText('正在读取最新条件…')).toBeInTheDocument()
  await act(async () => finish({ data: manifest }))
  expect(screen.getByRole('radio', { name: '确认具备' })).toBeDisabled()
  fireEvent.click(screen.getByRole('radio', { name: '批准风险进场' })); expect(screen.getByRole('button', { name: '保存确认结论' })).toBeDisabled()
  fireEvent.change(screen.getByLabelText('发车前资料确认理由'), { target: { value: '现场受控隔离，次日补齐' } }); fireEvent.click(screen.getByRole('button', { name: '保存确认结论' }))
  await waitFor(() => expect(h.post).toHaveBeenCalledWith('/projects/p1/documents/dispatch-review/confirm', { conclusion: 'risky', notes: '现场受控隔离，次日补齐', review_token: 'token1' }, { timeout: 600000 }))
})
it('retains notes on stale review and requires an explicit fresh inspection before resubmission', async () => {
  h.post.mockResolvedValueOnce({ data: manifest }).mockRejectedValueOnce({ response: { status: 409, data: { detail: '清单已变化' } } }).mockResolvedValue({ data: { ...manifest, review_token: 'token2' } })
  show(); fireEvent.click(screen.getByRole('button', { name: '核对发车前资料' })); await screen.findAllByText('安全条件')
  fireEvent.click(screen.getByRole('radio', { name: '批准风险进场' })); fireEvent.change(screen.getByLabelText('发车前资料确认理由'), { target: { value: '保留评审理由' } }); fireEvent.click(screen.getByRole('button', { name: '保存确认结论' }))
  await waitFor(() => expect(screen.getByText('清单已变化')).toBeVisible()); expect(screen.getByLabelText('发车前资料确认理由')).toHaveValue('保留评审理由'); expect(screen.getByRole('button', { name: '保存确认结论' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: '重新核对' })); await screen.findAllByText('安全条件'); fireEvent.click(screen.getByRole('button', { name: '保存确认结论' }))
  await waitFor(() => expect(h.post).toHaveBeenLastCalledWith('/projects/p1/documents/dispatch-review/confirm', expect.objectContaining({ review_token: 'token2', notes: '保留评审理由' }), { timeout: 600000 }))
})
it('optional unfinished items do not prevent an ordinary readiness conclusion', async () => {
  h.post.mockResolvedValue({ data: { ...manifest, entry_unmet: [], unmet: [{ name: '可选采购项', is_required: false }] } }); show(); fireEvent.click(screen.getByRole('button', { name: '核对发车前资料' }))
  await waitFor(() => expect(screen.getByText('第5阶段必需资料及原件已齐备')).toBeVisible()); expect(screen.getByRole('radio', { name: '确认具备' })).toBeEnabled()
})
it('shared read-only members see history without inspection or approval controls', async () => {
  h.get.mockResolvedValue({ data: [{ id: 'r1', conclusion: 'risky', reviewer_name: '历史评审人', reviewed_at: null, notes: '原风险理由' }] }); show(false)
  expect(await screen.findByText('历史评审人 · -')).toBeVisible(); expect(screen.getByText('原风险理由')).toBeVisible(); expect(screen.queryByRole('button', { name: '核对发车前资料' })).toBeNull(); expect(h.post).not.toHaveBeenCalled()
})

it('does not keep the previous project submission lock or apply its delayed result', async () => {
  let finish!: (value: unknown) => void
  h.post.mockResolvedValueOnce({ data: manifest }).mockImplementationOnce(() => new Promise(resolve => { finish = resolve })).mockResolvedValue({ data: manifest })
  const changed=vi.fn()
  const tree=(id: string) => <ConfigProvider theme={{ token: { motion: false } }}><ProjectStatusContext.Provider value="preparing"><ProjectCapabilitiesContext.Provider value={['project.manage_plan']}><EntryReviewPanel projectId={id} onConfirmed={changed} /></ProjectCapabilitiesContext.Provider></ProjectStatusContext.Provider></ConfigProvider>
  const view=render(tree('p1'))
  fireEvent.click(screen.getByRole('button', { name: '核对发车前资料' }))
  await screen.findAllByText('安全条件')
  fireEvent.click(screen.getByRole('radio', { name: '批准风险进场' }))
  fireEvent.change(screen.getByLabelText('发车前资料确认理由'), { target: { value: '旧项目风险理由' } })
  fireEvent.click(screen.getByRole('button', { name: '保存确认结论' }))
  await waitFor(() => expect(h.post).toHaveBeenCalledTimes(2))
  view.rerender(tree('p2'))
  fireEvent.click(screen.getByRole('button', { name: '核对发车前资料' }))
  await waitFor(() => expect(h.post).toHaveBeenLastCalledWith('/projects/p2/documents/dispatch-review', undefined, { timeout: 600000 }))
  await act(async () => finish({ data: { summary: {} } }))
  await waitFor(() => expect(screen.getByRole('dialog')).toBeVisible())
  expect(screen.getByLabelText('发车前资料确认理由')).toHaveValue('')
  expect(changed).not.toHaveBeenCalled()
})
