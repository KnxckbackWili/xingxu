import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'

const { currentRole, viewport } = vi.hoisted(() => ({ currentRole: { value: 'worker' as string }, viewport: { mobile: false } }))

vi.mock('../hooks/useMediaQuery', () => ({ useMediaQuery: () => viewport.mobile }))

vi.mock('../api/client', () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  errMsg: (e: unknown) => (e instanceof Error ? e.message : 'mock-error'),
}))
vi.mock('../stores/auth', () => ({
  useAuth: () => ({ user: { id: 'u1', role: currentRole.value, display_name: '现场工程师A' } }),
}))
vi.mock('../api', () => ({
  feedbackApi: {
    create: vi.fn(),
    list: vi.fn(),
    detail: vi.fn(),
    updateStatus: vi.fn(),
  },
}))

import { feedbackApi } from '../api'
import FeedbackPage from './FeedbackPage'

const ITEM = {
  id: 'fb-1', description: '登录页崩溃', steps: '', status: 'pending',
  user_id: 'u1', user_name: '张三',
  created_at: '2026-09-01T00:00:00', updated_at: '2026-09-01T00:00:00',
}

/**
 * 问题反馈页（HYPE-72）：
 * - 所有角色可见提交表单；普通角色不渲染管理列表、不发列表请求。
 * - 提交调用创建接口（描述必填、复现步骤可选）。
 * - 管理角色（pm）渲染反馈列表并加载数据。
 */
describe('问题反馈页', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    currentRole.value = 'worker'
    viewport.mobile = false
    vi.mocked(feedbackApi.list).mockReset().mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 })
  })

  it('worker 只看到提交表单，不渲染管理列表、不请求列表', () => {
    render(<FeedbackPage />)
    expect(screen.getByText('问题描述')).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/请描述你遇到的问题/)).toBeInTheDocument()
    expect(screen.queryByText('反馈列表')).not.toBeInTheDocument()
    expect(feedbackApi.list).not.toHaveBeenCalled()
  })

  it('提交反馈调用创建接口（描述必填、复现步骤可选）', async () => {
    vi.mocked(feedbackApi.create).mockResolvedValue({ id: 'fb-1', status: 'pending' })
    render(<FeedbackPage />)
    fireEvent.change(screen.getByPlaceholderText(/请描述你遇到的问题/), { target: { value: '页面加载慢' } })
    fireEvent.change(screen.getByPlaceholderText(/如何复现这个问题/), { target: { value: '1. 打开首页 2. 点击项目列表' } })
    fireEvent.click(screen.getByRole('button', { name: '提交反馈' }))
    await waitFor(() =>
      expect(feedbackApi.create).toHaveBeenCalledWith({ description: '页面加载慢', steps: '1. 打开首页 2. 点击项目列表' }),
    )
  })

  it('pm 管理角色看到反馈列表并加载数据', async () => {
    currentRole.value = 'pm'
    vi.mocked(feedbackApi.list).mockResolvedValue({ items: [ITEM], total: 1, page: 1, page_size: 20 })
    render(<FeedbackPage />)
    await screen.findByText('反馈列表')
    await screen.findByText('登录页崩溃')
    expect(screen.getByText('张三')).toBeInTheDocument()
    expect(feedbackApi.list).toHaveBeenCalled()
  })

  it('管理员提交后立即刷新列表，清除旧状态筛选并返回第一页', async () => {
    currentRole.value = 'admin'
    vi.mocked(feedbackApi.create).mockResolvedValue({ id: 'fb-new', status: 'pending' })
    vi.mocked(feedbackApi.list).mockResolvedValue({ items: [ITEM], total: 45, page: 1, page_size: 20 })
    render(<FeedbackPage />)
    await screen.findByText('登录页崩溃')
    fireEvent.click(screen.getByTitle('2'))
    await waitFor(() => expect(feedbackApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 })))
    vi.mocked(feedbackApi.list).mockResolvedValue({ items: [{ ...ITEM, description: '刚提交的问题' }], total: 46, page: 1, page_size: 20 })
    fireEvent.click(screen.getByRole('button', { name: '填写反馈' }))
    fireEvent.change(screen.getByPlaceholderText(/请描述你遇到的问题/), { target: { value: '刚提交的问题' } })
    fireEvent.click(screen.getByRole('button', { name: '提交反馈' }))
    await screen.findByText('刚提交的问题')
    expect(feedbackApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, status: undefined }))
  })

  it('changing the status filter resets pagination to the first page', async () => {
    currentRole.value = 'pm'
    vi.mocked(feedbackApi.list).mockResolvedValue({ items: [ITEM], total: 45, page: 1, page_size: 20 })
    render(<FeedbackPage />)
    await screen.findByText('登录页崩溃')
    fireEvent.click(screen.getByTitle('2'))
    await waitFor(() => expect(feedbackApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 })))
    fireEvent.mouseDown(screen.getAllByRole('combobox')[0])
    const options = screen.getAllByText('已处理')
    fireEvent.click(options[options.length - 1])
    await waitFor(() => expect(feedbackApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, status: 'done' })))
  })

  it('手机初次加载失败不显示暂无反馈，重试后恢复卡片和详情', async () => {
    currentRole.value = 'pm'
    viewport.mobile = true
    vi.mocked(feedbackApi.list).mockRejectedValueOnce(new Error('network down'))
      .mockResolvedValueOnce({ items: [ITEM], total: 1, page: 1, page_size: 20 })
    render(<FeedbackPage />)
    expect(screen.getByText('正在加载反馈…')).toBeInTheDocument()
    expect(screen.queryByText('暂无反馈')).not.toBeInTheDocument()
    expect(await screen.findByText('反馈列表加载失败')).toBeInTheDocument()
    expect(screen.queryByText('暂无反馈')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /重\s*试/ }))
    expect(await screen.findByRole('button', { name: ITEM.description })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '查看详情' }))
    expect(await screen.findByText('反馈详情')).toBeInTheDocument()
  })

  it('旧筛选的延迟失败不会清空新筛选成功返回的反馈', async () => {
    currentRole.value = 'pm'
    let rejectOld!: (error: Error) => void
    vi.mocked(feedbackApi.list).mockImplementationOnce(() => new Promise((_, reject) => { rejectOld = reject }))
      .mockResolvedValueOnce({ items: [{ ...ITEM, status: 'done' }], total: 1, page: 1, page_size: 20 })
    render(<FeedbackPage />)
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '按反馈状态筛选' }))
    fireEvent.click(screen.getByText('已处理', { selector: '.ant-select-item-option-content' }))
    expect(await screen.findByText(ITEM.description)).toBeInTheDocument()
    await act(async () => { rejectOld(new Error('old request failed')) })
    expect(screen.queryByText('反馈列表加载失败')).not.toBeInTheDocument()
    expect(screen.getByText(ITEM.description)).toBeInTheDocument()
  })

  it('新筛选加载失败时保持错误提示，旧请求成功不能回填旧记录', async () => {
    currentRole.value = 'pm'
    let resolveOld!: (result: { items: typeof ITEM[]; total: number; page: number; page_size: number }) => void
    vi.mocked(feedbackApi.list).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
      .mockRejectedValueOnce(new Error('current request failed'))
    render(<FeedbackPage />)
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '按反馈状态筛选' }))
    fireEvent.click(screen.getByText('已处理', { selector: '.ant-select-item-option-content' }))
    expect(await screen.findByText('反馈列表加载失败')).toBeInTheDocument()
    await act(async () => { resolveOld({ items: [ITEM], total: 1, page: 1, page_size: 20 }) })
    expect(screen.getByText('反馈列表加载失败')).toBeInTheDocument()
    expect(screen.queryByText(ITEM.description)).not.toBeInTheDocument()
    expect(screen.queryByText('暂无反馈')).not.toBeInTheDocument()
  })
})
