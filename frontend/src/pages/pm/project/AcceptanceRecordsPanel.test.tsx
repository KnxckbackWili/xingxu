import { beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import AcceptanceRecordsPanel from './AcceptanceRecordsPanel'
import { api } from '../../../api/client'
vi.mock('../../../api/client', () => ({ api: { get: vi.fn(), post: vi.fn() }, errMsg: (e: any) => e?.response?.data?.detail ?? e?.message ?? '请求失败' }))
vi.mock('../../../stores/auth', () => ({ useAuth: () => ({ user: { role: 'pm' } }) }))
beforeEach(() => vi.clearAllMocks())

function mockEmptyAcceptance(status: string, capabilities: string[]) {
  vi.mocked(api.get).mockImplementation(async url => ({ data:
    String(url).endsWith('/acceptance') || String(url).endsWith('/documents/files') ? []
      : String(url).endsWith('/archive-checklist') ? { items: [], progress: { done: 0, total: 0 } }
        : { status, capabilities, acceptance_summary: { latest: null, eligible: false,
          reason: '缺少验收签字记录，请先在验收页录入验收结论', as_of_date: '2026-10-12' } },
  }) as any)
}

it('offers an adjacent empty-state entry using the same acceptance form without writing on cancellation', async () => {
  mockEmptyAcceptance('ready', ['project.update'])
  render(<ConfigProvider theme={{ token: { motion: false } }}><AcceptanceRecordsPanel projectId="p1" /></ConfigProvider>)
  expect(await screen.findByText('尚未录入客户验收结果')).toBeInTheDocument()
  expect(screen.queryByText(/请先在验收页/)).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: '录入验收记录' })).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: '录入验收记录' }))
  const dialog = await screen.findByRole('dialog', { name: '录入验收记录' })
  const recorder = within(dialog).getByLabelText('客户验收人')
  await waitFor(() => expect(recorder).toBeVisible())
  expect(recorder).toHaveValue('')
  fireEvent.change(recorder, { target: { value: '取消前填写的客户代表' } })
  expect(recorder).toHaveValue('取消前填写的客户代表')
  fireEvent.click(within(dialog).getByRole('button', { name: /取\s*消/ }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(api.post).not.toHaveBeenCalled()
})

it('explains the acceptance stage without opening a premature entry', async () => {
  mockEmptyAcceptance('planning', ['project.update'])
  render(<AcceptanceRecordsPanel projectId="p1" />)
  expect(await screen.findByText('尚无验收记录；由有项目资料维护权限的负责人录入')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /录入验收记录/ })).not.toBeInTheDocument()
  expect(api.post).not.toHaveBeenCalled()
})

it('points a read-only eligible project to the authorized recorder instead of a self-referencing page', async () => {
  mockEmptyAcceptance('ready', [])
  render(<AcceptanceRecordsPanel projectId="p1" />)
  expect(await screen.findByText('尚无验收记录；由有项目资料维护权限的负责人录入')).toBeInTheDocument()
  expect(screen.queryByText(/请先在验收页/)).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /录入验收记录/ })).not.toBeInTheDocument()
  expect(api.post).not.toHaveBeenCalled()
})

function mockRetrospective(retrospective: unknown) {
  vi.mocked(api.get).mockImplementation(async url => ({ data:
    String(url).endsWith('/acceptance') || String(url).endsWith('/documents/files') ? []
      : String(url).endsWith('/archive-checklist') ? { items: [], progress: { done: 0, total: 0 } }
        : { status: 'archived', capabilities: [], retrospective },
  }) as any)
}

it('reads the archived retrospective with its author and local technical time without edit controls', async () => {
  const content = '成功经验\n' + '长文原文需要完整保留。'.repeat(80)
  mockRetrospective({ content, author: 'internal-author-id', author_name: '复盘人员', written_at: '2026-10-04T23:05:10' })
  render(<AcceptanceRecordsPanel projectId="p1" />)
  const paragraph = await screen.findByText(content, { normalizer: value => value })
  expect(paragraph).toHaveStyle({ whiteSpace: 'pre-wrap' })
  // The API's naive technical timestamp means UTC; display follows this browser.
  const local = new Date('2026-10-04T23:05:10Z')
  const pad = (value: number) => String(value).padStart(2, '0')
  const localTime = `${local.getFullYear()}-${pad(local.getMonth() + 1)}-${pad(local.getDate())} ${pad(local.getHours())}:${pad(local.getMinutes())}`
  expect(screen.getByText(`作者：复盘人员 · ${localTime}`)).toBeInTheDocument()
  expect(screen.queryByText(/internal-author-id/)).toBeNull()
  expect(screen.queryByRole('textbox')).toBeNull()
  expect(screen.queryByRole('button', { name: /保存|编辑复盘/ })).toBeNull()
  expect(api.post).not.toHaveBeenCalled()
})

it('shows legacy success/problem/improvement sections and a missing author without exposing its ID', async () => {
  mockRetrospective({ success: '客户验收通过', problems: '接口复测延迟', improvements: '提前确认协议', author: 'deleted-author-id' })
  render(<AcceptanceRecordsPanel projectId="p1" />)
  expect(await screen.findByText('客户验收通过')).toBeInTheDocument()
  expect(screen.getByText('成功经验')).toBeInTheDocument()
  expect(screen.getByText('问题教训')).toBeInTheDocument()
  expect(screen.getByText('接口复测延迟')).toBeInTheDocument()
  expect(screen.getByText('改进建议')).toBeInTheDocument()
  expect(screen.getByText('提前确认协议')).toBeInTheDocument()
  expect(screen.getByText('作者：未记录 · -')).toBeInTheDocument()
  expect(screen.queryByText(/deleted-author-id/)).toBeNull()
})

it('gives an explicit empty retrospective instead of hiding the section', async () => {
  mockRetrospective({ author_name: '' })
  render(<AcceptanceRecordsPanel projectId="p1" />)
  expect(await screen.findByText('项目复盘')).toBeInTheDocument()
  expect(screen.getByText('尚未填写复盘，归档时由负责人记录。')).toBeInTheDocument()
})

it('验收加载失败可重试且不请求旧归档清单', async () => {
  vi.mocked(api.get).mockRejectedValue(new Error('offline'))
  render(<AcceptanceRecordsPanel projectId="p1" />)
  expect(await screen.findByText('offline')).toBeInTheDocument()
  mockEmptyAcceptance('ready', [])
  fireEvent.click(screen.getByRole('button', { name: /重\s*试/ }))
  expect(await screen.findByText('尚无验收记录；由有项目资料维护权限的负责人录入')).toBeInTheDocument()
  expect(vi.mocked(api.get).mock.calls.some(([url]) => String(url).includes('archive-checklist'))).toBe(false)
})

it('records acceptance separately and preserves failed submissions', async () => {
  vi.mocked(api.get).mockImplementation(async (url) => ({ data:
    String(url).endsWith('/acceptance') || String(url).endsWith('/documents/files') ? []
      : String(url).endsWith('/archive-checklist') ? { items: [], progress: { done: 0, total: 0 } }
        : { status: 'acceptance', capabilities: ['project.update'], acceptance_summary: { as_of_date: '2026-10-02' } },
  }) as any)
  vi.mocked(api.post).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ data: {} })
  render(<AcceptanceRecordsPanel projectId="p1" />)
  fireEvent.click(await screen.findByRole('button', { name: '录入验收记录' }))
  fireEvent.change(screen.getByLabelText('客户验收人'), { target: { value: '客户代表' } })
  fireEvent.change(screen.getByLabelText('验收日期'), { target: { value: '2026-09-30' } })
  fireEvent.click(screen.getByRole('button', { name: '保存验收记录' }))
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1))
  await waitFor(() => expect(screen.getByRole('button', { name: '保存验收记录' })).not.toHaveClass('ant-btn-loading'))
  expect(screen.getByLabelText('客户验收人')).toHaveValue('客户代表')
  fireEvent.click(screen.getByRole('button', { name: '保存验收记录' }))
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(2))
  expect(vi.mocked(api.post).mock.calls[1]).toEqual(['/projects/p1/acceptance', expect.objectContaining({
    accepted_by_name: '客户代表', accepted_at: '2026-09-30', conclusion: 'accepted',
  })])
})

it('shows acceptance records read-only for an archived project', async () => {
  vi.mocked(api.get).mockImplementation(async (url) => ({ data:
    String(url).endsWith('/acceptance') ? [{ id: 'a1', accepted_by_name: '客户', accepted_at: '2026-09-30', conclusion: 'accepted' }]
      : String(url).endsWith('/documents/files') ? []
      : String(url).endsWith('/archive-checklist') ? { items: [], progress: { done: 0, total: 0 } }
        : { status: 'archived', capabilities: ['project.update'] },
  }) as any)
  render(<AcceptanceRecordsPanel projectId="p1" />)
  expect(await screen.findByText('客户')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '录入验收记录' })).not.toBeInTheDocument()
})

it.each(['rejected', 'conditionally_accepted'])('shows the latest %s decision instead of treating an old pass as current', async (conclusion) => {
  const latest = { id: 'a2', accepted_by_name: '复检客户', accepted_at: '2026-10-02', created_at: '2026-10-02T09:00:00Z', conclusion, is_effective: true, scope_current: true, scope_verified: true }
  const historical = { id: 'a1', accepted_by_name: '首检客户', accepted_at: '2026-10-01', conclusion: 'accepted', is_effective: false }
  vi.mocked(api.get).mockImplementation(async url => ({ data:
    String(url).endsWith('/acceptance') ? [latest, historical]
      : String(url).endsWith('/documents/files') ? []
      : String(url).endsWith('/archive-checklist') ? { items: [], progress: { done: 0, total: 0 } }
      : { status: 'acceptance', capabilities: ['project.update'], acceptance_summary: { as_of_date: '2026-10-02', latest, eligible: false, reason: '最新验收结论尚未通过，请处理后重新验收' } },
  }) as any)
  render(<AcceptanceRecordsPanel projectId="p1" />)
  expect(await screen.findByText(`最新验收结论：${conclusion === 'rejected' ? '不通过' : '有条件通过'}`)).toBeInTheDocument()
  expect(screen.getByText('最新有效结果').closest('.ant-space')).toHaveTextContent('复检客户')
  fireEvent.click(screen.getByText('历史验收记录（1）'))
  expect(screen.getByText('首检客户').closest('.ant-space')).toHaveTextContent('首检客户')
  expect(screen.getByText('最新验收结论尚未通过，请处理后重新验收')).toBeInTheDocument()
  expect(api.post).not.toHaveBeenCalled()
})

it('shows scope-invalid or unverified decisions without calling them complete', async () => {
  const latest = { id: 'a1', accepted_by_name: '客户', accepted_at: '2026-10-01', conclusion: 'accepted', is_effective: true, scope_current: false, scope_verified: false }
  vi.mocked(api.get).mockImplementation(async url => ({ data:
    String(url).endsWith('/acceptance') ? [latest]
      : String(url).endsWith('/documents/files') ? []
      : String(url).endsWith('/archive-checklist') ? { items: [], progress: { done: 0, total: 0 } }
      : { status: 'completed', capabilities: ['project.update'], acceptance_summary: { as_of_date: '2026-10-02', latest, eligible: false, reason: '历史验收记录缺少范围快照，请复核当前范围后重新录入验收结论' } },
  }) as any)
  render(<AcceptanceRecordsPanel projectId="p1" />)
  expect(await screen.findByText('范围未核验')).toBeInTheDocument()
  expect(screen.getByText('历史验收记录缺少范围快照，请复核当前范围后重新录入验收结论')).toBeInTheDocument()
  expect(screen.getByText(/如需补报工作或调整计划/)).toBeInTheDocument()
})

it('successful reinspection refreshes the server decision and does not change the lifecycle itself', async () => {
  let saved = false
  const old = { id: 'a1', accepted_by_name: '首检客户', accepted_at: '2026-10-01', conclusion: 'rejected', is_effective: true }
  const next = { id: 'a2', accepted_by_name: '复检客户', accepted_at: '2026-10-02', conclusion: 'accepted', is_effective: true }
  vi.mocked(api.get).mockImplementation(async url => ({ data:
    String(url).endsWith('/acceptance') ? saved ? [next, { ...old, is_effective: false }] : [old]
      : String(url).endsWith('/documents/files') ? []
      : String(url).endsWith('/archive-checklist') ? { items: [], progress: { done: 0, total: 0 } }
      : { status: 'acceptance', capabilities: ['project.update'], acceptance_summary: { as_of_date: '2026-10-02', latest: saved ? next : old, eligible: saved, reason: saved ? '最新验收通过' : '最新验收不通过' } },
  }) as any)
  vi.mocked(api.post).mockImplementation(async () => { saved = true; return { data: next } })
  render(<AcceptanceRecordsPanel projectId="p1" />)
  expect(await screen.findByText('最新验收结论：不通过')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '录入验收记录' }))
  const dialog = screen.getByRole('dialog')
  fireEvent.change(within(dialog).getByLabelText('客户验收人'), { target: { value: '复检客户' } })
  fireEvent.change(within(dialog).getByLabelText('验收日期'), { target: { value: '2026-10-02' } })
  fireEvent.click(within(dialog).getByRole('button', { name: '保存验收记录' }))
  expect(await screen.findByText('最新验收结论：通过')).toBeInTheDocument()
  expect(api.post).toHaveBeenCalledTimes(1)
  expect(api.post).toHaveBeenCalledWith('/projects/p1/acceptance', expect.anything())
})

it.each(['preparing', 'planning'])('suspension from %s does not unlock premature acceptance recording', async status => {
  vi.mocked(api.get).mockImplementation(async url => ({ data:
    String(url).endsWith('/acceptance') || String(url).endsWith('/documents/files') ? []
      : String(url).endsWith('/archive-checklist') ? { items: [], progress: { done: 0, total: 0 } }
      : { status: 'suspended', suspension: { status_before: status }, capabilities: ['project.update'] },
  }) as any)
  render(<AcceptanceRecordsPanel projectId="p1" />)
  await screen.findByText('尚无验收记录；由有项目资料维护权限的负责人录入')
  expect(screen.queryByRole('button', { name: '录入验收记录' })).not.toBeInTheDocument()
})

it('a member without project.update can read the latest result but cannot record acceptance', async () => {
  vi.mocked(api.get).mockImplementation(async url => ({ data:
    String(url).endsWith('/acceptance') || String(url).endsWith('/documents/files') ? []
      : String(url).endsWith('/archive-checklist') ? { items: [], progress: { done: 0, total: 0 } }
      : { status: 'acceptance', capabilities: [] },
  }) as any)
  render(<AcceptanceRecordsPanel projectId="p1" />)
  await screen.findByText('尚无验收记录；由有项目资料维护权限的负责人录入')
  expect(screen.queryByRole('button', { name: '录入验收记录' })).not.toBeInTheDocument()
})

it('uses the server site date as the acceptance maximum and blocks a future date locally', async () => {
  vi.mocked(api.get).mockImplementation(async url => ({ data:
    String(url).endsWith('/acceptance') || String(url).endsWith('/documents/files') ? []
      : String(url).endsWith('/archive-checklist') ? { items: [], progress: { done: 0, total: 0 } }
      : { status: 'acceptance', timezone: 'Pacific/Honolulu', capabilities: ['project.update'], acceptance_summary: { latest: null, eligible: false, reason: '缺少验收记录', as_of_date: '2026-10-01' } },
  }) as any)
  render(<AcceptanceRecordsPanel projectId="p1" />)
  fireEvent.click(await screen.findByRole('button', { name: '录入验收记录' }))
  const dialog = screen.getByRole('dialog')
  const date = within(dialog).getByLabelText('验收日期')
  expect(date).toHaveAttribute('max', '2026-10-01')
  fireEvent.change(within(dialog).getByLabelText('客户验收人'), { target: { value: '客户代表' } })
  fireEvent.change(date, { target: { value: '2026-10-02' } })
  fireEvent.click(within(dialog).getByRole('button', { name: '保存验收记录' }))
  expect(await within(dialog).findByText('验收日期不能晚于项目当地今天（2026-10-01）')).toBeInTheDocument()
  expect(api.post).not.toHaveBeenCalled()
})

it('server date rejection remains visible and preserves inputs for correction', async () => {
  vi.mocked(api.get).mockImplementation(async url => ({ data:
    String(url).endsWith('/acceptance') || String(url).endsWith('/documents/files') ? []
      : String(url).endsWith('/archive-checklist') ? { items: [], progress: { done: 0, total: 0 } }
      : { status: 'acceptance', capabilities: ['project.update'], acceptance_summary: { latest: null, eligible: false, reason: '缺少验收记录', as_of_date: '2026-10-02' } },
  }) as any)
  vi.mocked(api.post).mockRejectedValue({ response: { status: 400, data: { detail: '验收日期不能晚于项目当地今天（2026-10-01）' } } })
  render(<AcceptanceRecordsPanel projectId="p1" />)
  fireEvent.click(await screen.findByRole('button', { name: '录入验收记录' }))
  const dialog = screen.getByRole('dialog')
  fireEvent.change(within(dialog).getByLabelText('客户验收人'), { target: { value: '客户代表' } })
  fireEvent.change(within(dialog).getByLabelText('验收日期'), { target: { value: '2026-10-02' } })
  fireEvent.click(within(dialog).getByRole('button', { name: '保存验收记录' }))
  expect(await within(dialog).findByText('验收日期不能晚于项目当地今天（2026-10-01）')).toBeInTheDocument()
  expect(within(dialog).getByLabelText('客户验收人')).toHaveValue('客户代表')
  expect(within(dialog).getByLabelText('验收日期')).toHaveValue('2026-10-02')
})

it('a historical future-dated row cannot displace the explicitly effective rejection', async () => {
  const future = { id: 'future', accepted_by_name: '未来日期客户', accepted_at: '2099-01-01', conclusion: 'accepted', is_effective: false, effective_date_reached: false, invalid_reason: '验收日期晚于项目当地今天，暂不生效' }
  const latest = { id: 'current', accepted_by_name: '当前客户', accepted_at: '2026-10-01', conclusion: 'rejected', is_effective: true, effective_date_reached: true }
  vi.mocked(api.get).mockImplementation(async url => ({ data:
    String(url).endsWith('/acceptance') ? [future, latest]
      : String(url).endsWith('/documents/files') ? []
      : String(url).endsWith('/archive-checklist') ? { items: [], progress: { done: 0, total: 0 } }
      : { status: 'acceptance', capabilities: ['project.update'], acceptance_summary: { latest, eligible: false, reason: '最新验收不通过', warning: '有 1 条未来日期历史记录暂不生效', pending_future_count: 1, as_of_date: '2026-10-02' } },
  }) as any)
  render(<AcceptanceRecordsPanel projectId="p1" />)
  expect(await screen.findByText('最新验收结论：不通过')).toBeInTheDocument()
  expect(screen.getByText('最新有效结果').closest('.ant-space')).toHaveTextContent('当前客户')
  fireEvent.click(screen.getByText('历史验收记录（1）'))
  expect(screen.getByText('尚未到验收日期').closest('.ant-space')).toHaveTextContent('未来日期客户')
  expect(screen.getByText('有 1 条未来日期历史记录暂不生效')).toBeInTheDocument()
})
