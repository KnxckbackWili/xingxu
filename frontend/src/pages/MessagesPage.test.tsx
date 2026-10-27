import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { ConfigProvider } from 'antd'

const mockNavigate = vi.fn()

vi.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
}))

vi.mock('../api/client', () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
  errMsg: () => 'mock-error',
}))

import { api } from '../api/client'
import { useAuth } from '../stores/auth'
import MessagesPage from './MessagesPage'

const NOTIFICATIONS = [
  { id: 'n1', title: '问题指派：车辆故障', content: '请尽快处理 1 号车故障', ntype: 'issue_assigned', project_id: 'p1', is_read: false, created_at: '2026-08-30T10:00:00' },
  { id: 'n2', title: '报告已生成', content: '项目周报已生成', ntype: 'report', project_id: 'p1', is_read: true, created_at: '2026-08-29T09:00:00' },
]

beforeEach(() => {
  vi.clearAllMocks()
  mockNavigate.mockClear()
  useAuth.setState({ user: { id: 'u-pm', role: 'pm', username: 'pm', display_name: '项目经理', phone: '', email: '', is_active: true } })
  vi.mocked(api.get).mockResolvedValue({ data: NOTIFICATIONS })
  vi.mocked(api.post).mockResolvedValue({ data: { message: '已标记为已读' } })
})

describe('MessagesPage（消息通知）', () => {
  it('渲染通知列表并标记未读状态', async () => {
    render(<MessagesPage />)
    expect(await screen.findByRole('heading', { name: '消息', level: 1 })).toBeInTheDocument()
    expect(await screen.findByText('问题指派：车辆故障')).toBeInTheDocument()
    expect(screen.getByText('报告已生成')).toBeInTheDocument()
    // 默认展示「全部」并保留未读筛选能力
    expect(screen.getByText('全部')).toBeInTheDocument()
    expect(screen.getByText('未读')).toBeInTheDocument()
  })

  it('点击未读通知标记已读并在右侧展示详情', async () => {
    render(<MessagesPage />)
    fireEvent.click(await screen.findByText('问题指派：车辆故障'))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/notifications/n1/read'))
    // 列表摘要与右侧详情同文案 → 断言至少出现两处（详情面板已渲染）
    expect((await screen.findAllByText('请尽快处理 1 号车故障')).length).toBeGreaterThanOrEqual(2)
  })

  it('空通知时展示空态', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: [] })
    render(<MessagesPage />)
    expect(await screen.findByText('暂无通知')).toBeInTheDocument()
  })

  it('接口失败明确提示并可重试', async () => {
    vi.mocked(api.get).mockRejectedValue(new Error('network down'))
    render(<MessagesPage />)
    expect(await screen.findByText('通知加载失败')).toBeInTheDocument()
    expect(screen.queryByText('暂无通知')).toBeNull()
    vi.mocked(api.get).mockResolvedValue({ data: NOTIFICATIONS })
    fireEvent.click(screen.getByRole('button', { name: /重\s*试/ }))
    expect(await screen.findByText('报告已生成')).toBeInTheDocument()
  })
})


it('type filters request the server from offset zero and short pages end pagination', async () => {
  vi.mocked(api.get).mockResolvedValueOnce({ data: Array.from({ length: 20 }, (_, i) => ({ ...NOTIFICATIONS[0], id: `first-${i}`, title: `问题${i}` })) })
    .mockResolvedValueOnce({ data: [NOTIFICATIONS[1]] })
  render(<MessagesPage />)
  expect(await screen.findByText('问题19')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '加载更多' })).toBeInTheDocument()
  fireEvent.mouseDown(screen.getByRole('combobox', { name: '按类型筛选' }))
  fireEvent.click(await screen.findByText('报告', { selector: '.ant-select-item-option-content' }))
  expect(await screen.findByText('报告已生成')).toBeInTheDocument()
  expect(api.get).toHaveBeenLastCalledWith('/notifications', { params: { limit: 20, offset: 0, unread_only: false, ntype: 'report' } })
  expect(screen.queryByRole('button', { name: '加载更多' })).toBeNull()
})

it('a short appended page stops load-more and unread mutations reset the server offset', async () => {
  const full = Array.from({ length: 20 }, (_, i) => ({ ...NOTIFICATIONS[0], id: `n-${i}`, title: `待处理${i}` }))
  vi.mocked(api.get).mockResolvedValueOnce({ data: full }).mockResolvedValueOnce({ data: [NOTIFICATIONS[1]] })
  render(<MessagesPage />)
  fireEvent.click(await screen.findByRole('button', { name: '加载更多' }))
  await screen.findByText('报告已生成')
  expect(screen.queryByRole('button', { name: '加载更多' })).toBeNull()
  vi.mocked(api.get).mockResolvedValue({ data: full })
  fireEvent.click(screen.getByText('未读'))
  await waitFor(() => expect(api.get).toHaveBeenLastCalledWith('/notifications', { params: { limit: 20, offset: 0, unread_only: true } }))
  fireEvent.click(await screen.findByRole('button', { name: '待处理0' }))
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/notifications/n-0/read'))
  await waitFor(() => expect(api.get).toHaveBeenCalledTimes(4))
  expect(api.get).toHaveBeenLastCalledWith('/notifications', { params: { limit: 20, offset: 0, unread_only: true } })
})

it('a late response for the previous type cannot overwrite the new filtered list', async () => {
  let resolveOld!: (value: unknown) => void
  vi.mocked(api.get).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }) as any)
    .mockResolvedValueOnce({ data: [NOTIFICATIONS[1]] })
  render(<MessagesPage />)
  fireEvent.mouseDown(screen.getByRole('combobox', { name: '按类型筛选' }))
  fireEvent.click(await screen.findByText('报告', { selector: '.ant-select-item-option-content' }))
  await screen.findByText('报告已生成')
  resolveOld({ data: [NOTIFICATIONS[0]] })
  await waitFor(() => expect(screen.queryByText('问题指派：车辆故障')).toBeNull())
  expect(screen.getByText('报告已生成')).toBeInTheDocument()
})

it('a successful mark-all read survives an older inbox response', async () => {
  let resolveOld!: (value: { data: typeof NOTIFICATIONS }) => void
  vi.mocked(api.get).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    .mockResolvedValue({ data: [{ ...NOTIFICATIONS[0], is_read: true }] })
  render(<MessagesPage />)
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: '全部已读' }))
  })
  expect(api.post).toHaveBeenCalledWith('/notifications/read-all')
  await act(async () => { resolveOld({ data: [NOTIFICATIONS[0]] }) })
  expect(await screen.findByText('1 条已加载 · 0 条未读')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: NOTIFICATIONS[0].title }).closest('.message-list-item')).not.toHaveClass('is-unread')
})

it.each(['single', 'selected'])('a successful %s read survives a refresh started while the write was pending', async mode => {
  let resolveOld!: (value: { data: typeof NOTIFICATIONS }) => void
  let resolveRead!: (value: { data: { updated: number } }) => void
  vi.mocked(api.get).mockResolvedValueOnce({ data: [NOTIFICATIONS[0]] })
    .mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    .mockResolvedValue({ data: [{ ...NOTIFICATIONS[0], is_read: true }] })
  vi.mocked(api.post).mockImplementationOnce(() => new Promise(resolve => { resolveRead = resolve }))
  render(<MessagesPage />)
  const notification = await screen.findByRole('button', { name: NOTIFICATIONS[0].title })
  if (mode === 'single') {
    fireEvent.click(notification)
    expect(api.post).toHaveBeenCalledWith('/notifications/n1/read')
  } else {
    fireEvent.click(screen.getByRole('checkbox', { name: '选择该消息' }))
    fireEvent.click(screen.getByRole('button', { name: /标记已读（1）/ }))
    expect(api.post).toHaveBeenCalledWith('/notifications/read-batch', { ids: ['n1'] })
  }
  fireEvent.click(screen.getByRole('button', { name: /刷\s*新/ }))
  await act(async () => { resolveRead({ data: { updated: 1 } }) })
  await act(async () => { resolveOld({ data: [NOTIFICATIONS[0]] }) })
  expect(await screen.findByText('1 条已加载 · 0 条未读')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: NOTIFICATIONS[0].title }).closest('.message-list-item')).not.toHaveClass('is-unread')
})


it('external bell read events refresh the active unread filter once, while own read does not reload twice', async () => {
  const { NOTIFICATION_READ_EVENT } = await import('../utils/notificationEvents')
  render(<MessagesPage />)
  await screen.findByText('问题指派：车辆故障')
  fireEvent.click(screen.getByText('未读'))
  await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2))
  vi.mocked(api.get).mockResolvedValue({ data: [] })
  fireEvent(window, new CustomEvent(NOTIFICATION_READ_EVENT, { detail: { source: 'bell' } }))
  await screen.findByText('暂无通知')
  expect(api.get).toHaveBeenCalledTimes(3)
  expect(api.get).toHaveBeenLastCalledWith('/notifications', { params: { limit: 20, offset: 0, unread_only: true } })
})


it('opens phone message detail in a drawer and restores focus when closed', async () => {
  const media = vi.spyOn(window, 'matchMedia').mockImplementation(query => ({
    matches: query.includes('max-width'), media: query, onchange: null,
    addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: () => false,
  }))
  try {
    render(<ConfigProvider theme={{ token: { motion: false } }}><MessagesPage /></ConfigProvider>)
    const trigger = await screen.findByRole('button', { name: '问题指派：车辆故障' })
    fireEvent.click(trigger)
    const dialog = await screen.findByRole('dialog', { name: '消息详情' })
    expect(within(dialog).getByText('请尽快处理 1 号车故障')).toBeVisible()
    expect(within(dialog).getByRole('button', { name: /前往处理/ })).toBeEnabled()
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/notifications/n1/read'))
    fireEvent.click(within(dialog).getByRole('button', { name: /Close|关闭/ }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '消息详情' })).not.toBeInTheDocument())
    await waitFor(() => expect(screen.getByRole('button', { name: '问题指派：车辆故障' })).toHaveFocus())
  } finally { media.mockRestore() }
})
