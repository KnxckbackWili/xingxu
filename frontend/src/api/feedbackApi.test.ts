import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const apiGet = vi.fn()
const apiPost = vi.fn()
const apiPatch = vi.fn()

vi.mock('./client', () => ({
  api: {
    get: (...args: unknown[]) => apiGet(...args),
    post: (...args: unknown[]) => apiPost(...args),
    patch: (...args: unknown[]) => apiPatch(...args),
    put: vi.fn(),
    delete: vi.fn(),
  },
  errMsg: () => 'mock-error',
  tokenStore: { access: 'test-token' },
}))

import { feedbackApi } from './index'

/** feedbackApi（HYPE-72）：提交 / 列表参数 / 状态更新请求形状回归。 */
describe('feedbackApi（HYPE-72）', () => {
  beforeEach(() => vi.clearAllMocks())
  afterEach(() => vi.resetAllMocks())

  it('create 提交到 POST /feedback（描述 + 可选复现步骤）', async () => {
    apiPost.mockResolvedValue({ data: { id: 'fb-1', status: 'pending' } })
    const r = await feedbackApi.create({ description: '页面加载慢', steps: '反复刷新' })
    expect(apiPost).toHaveBeenCalledWith('/feedback', { description: '页面加载慢', steps: '反复刷新' })
    expect(r.id).toBe('fb-1')
  })

  it('list 携带分页与状态筛选参数', async () => {
    apiGet.mockResolvedValue({ data: { items: [], total: 0, page: 1, page_size: 20 } })
    await feedbackApi.list({ status: 'done', page: 2, page_size: 10 })
    expect(apiGet).toHaveBeenCalledWith('/feedback', { params: { status: 'done', page: 2, page_size: 10 } })
  })

  it('updateStatus 走 PATCH /feedback/{id}/status', async () => {
    apiPatch.mockResolvedValue({ data: { id: 'fb-1', status: 'processing' } })
    const r = await feedbackApi.updateStatus('fb-1', 'processing')
    expect(apiPatch).toHaveBeenCalledWith('/feedback/fb-1/status', { status: 'processing' })
    expect(r.status).toBe('processing')
  })
})
