import { expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import HistoryPage from './HistoryPage'
import { api } from '../../../api/client'
vi.mock('../../../api/client', () => ({ api: { get: vi.fn() } }))

it('allows all fetched history to be inspected and collapsed', async () => {
  vi.mocked(api.get).mockResolvedValue({ data: Array.from({ length: 12 }, (_, index) => ({
    id: `log-${index}`, operator_name: '负责人', detail: `操作编号${index}`, created_at: '',
  })) })
  render(<HistoryPage projectId="p1" />)
  await screen.findByRole('button', { name: '展开其余 2 条记录' })
  expect(screen.queryByText('操作编号11')).not.toBeInTheDocument()
  fireEvent.change(screen.getByRole('searchbox', { name: '搜索已加载记录' }), { target: { value: '操作编号11' } })
  expect(screen.getByText('操作编号11')).toBeVisible()
  expect(screen.queryByText('操作编号0')).not.toBeInTheDocument()
  fireEvent.change(screen.getByRole('searchbox', { name: '搜索已加载记录' }), { target: { value: '' } })
  fireEvent.click(screen.getByRole('button', { name: '展开其余 2 条记录' }))
  expect(screen.getByText('操作编号11')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '收起记录' }))
  expect(screen.queryByText('操作编号11')).not.toBeInTheDocument()
})
it('keeps a failed audit-log request distinct from an empty history', async () => {
  vi.mocked(api.get).mockRejectedValue(new Error('offline'))
  render(<HistoryPage projectId="p1" />)
  expect(await screen.findByText('变更记录加载失败')).toBeInTheDocument()
  expect(screen.queryByText('暂无变更记录')).not.toBeInTheDocument()
})

it('shows localized fixed audit fields without modifying the fetched records or user text', async () => {
  const details = ['更新问题：low 信号复核 → 状态 resolved', '上报问题：processing 信号（low）', '物品「receive 型工具」新增流水：transfer', '备注：low/receive/resolved 原文']
  const logs = details.map((detail, index) => ({ id: `fixed-${index}`, operator_name: '负责人', detail, created_at: '' }))
  vi.mocked(api.get).mockResolvedValue({ data: logs })
  render(<HistoryPage projectId="p1" />)
  expect(await screen.findByText('更新问题：low 信号复核 → 状态 已解决')).toBeInTheDocument()
  expect(screen.getByText('上报问题：processing 信号（低）')).toBeInTheDocument()
  expect(screen.getByText('物品「receive 型工具」新增流水：位置转移')).toBeInTheDocument()
  expect(screen.getByText(details[3])).toBeInTheDocument()
  expect(logs.map(log => log.detail)).toEqual(details)
})
