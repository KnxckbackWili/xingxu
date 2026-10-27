import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import { beforeEach, expect, it, vi } from 'vitest'
const h = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../../../api/client', () => ({ api: { get: h.get }, errMsg: () => '网络不可用，请重试' }))
import CompletionReview from './CompletionReview'
const response = { project_version: 7, allowed: false, target: 'completed', blockers: [
  { type: 'documents', message: '缺少真实验收单', url: '/pm/projects/p1/documents' },
  { type: 'issues', message: '仍有已解决但未关闭的问题', url: '/pm/projects/p1/issues' },
  { type: 'vehicle_faults', message: 'AGV01故障尚未关闭', url: '/pm/projects/p1/vehicles' },
], ordinary_check_overrides: [{ task_id: 't1', task_name: '接口复核', reason: '受控隔离后独立复测', actor_name: '项目经理', recorded_at: null, url: '/pm/projects/p1/plan?task=t1', checks: [{ check_id: 'c1', name: '普通接口检查', failed_reason: '旧接口协议不同', still_current: false }] }] }
const show = (projectId = 'p1') => <ConfigProvider theme={{ token: { motion: false } }}><CompletionReview projectId={projectId} target="completed" open onClose={() => {}} /></ConfigProvider>
beforeEach(() => { vi.resetAllMocks(); h.get.mockResolvedValue({ data: response }) })
it('shows every blocker and separately records ordinary overrides without changing project status', async () => {
  render(show()); const modal = within(await screen.findByRole('dialog'))
  for (const row of response.blockers) expect(await modal.findByText(row.message)).toBeInTheDocument()
  expect(modal.getAllByRole('link', { name: '去核对相关记录' })).toHaveLength(3)
  expect(modal.getByText('覆盖理由：受控隔离后独立复测')).toBeInTheDocument(); expect(modal.getByText('检查事实已变化，需复核')).toBeInTheDocument()
  expect(h.get).toHaveBeenCalledExactlyOnceWith('/projects/p1/completion-review', expect.objectContaining({ params: { target: 'completed' } }))
  expect(modal.queryByRole('button', { name: '确认完成' })).toBeNull()
})
it('failed inspection stays unknown and retries explicitly', async () => {
  h.get.mockRejectedValueOnce(new Error('offline')); render(show())
  expect(await screen.findByText('核对清单加载失败')).toBeInTheDocument(); expect(screen.queryByText('当前证据已齐备')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '重新核对' })); expect(await screen.findByText('缺少真实验收单')).toBeInTheDocument()
})
it('ignores a previous project response and refuses off-project or external action links', async () => {
  let old: (value: unknown) => void = () => {}; h.get.mockImplementationOnce(() => new Promise(resolve => { old = resolve })).mockResolvedValueOnce({ data: { ...response, blockers: [{ type: 'documents', message: '新项目资料待处理', url: 'https://unexpected.invalid/' }], ordinary_check_overrides: [] } })
  const view = render(show()); view.rerender(show('p2')); expect(await screen.findByText('新项目资料待处理')).toBeInTheDocument()
  await act(async () => old({ data: response })); expect(screen.queryByText('缺少真实验收单')).toBeNull(); expect(screen.getByRole('link', { name: '去核对相关记录' })).toHaveAttribute('href', '/pm/projects/p2/overview')
})
