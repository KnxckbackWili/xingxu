import { expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import HandoverSummary from './HandoverSummary'
import { api } from '../api/client'
const navigate = vi.hoisted(() => vi.fn())
vi.mock('react-router-dom', () => ({ useNavigate: () => navigate }))
vi.mock('../api/client',()=>({api:{get:vi.fn()},errMsg:()=> '网络不可用'}))
it('keeps the full totals and explicitly labels a shortened handover, applying it only on request',async()=>{
 const use=vi.fn()
 vi.mocked(api.get).mockResolvedValue({data:{project_name:'现场甲',counts:{tasks:40,issues:0,faults:0,documents:0},tasks:Array.from({length:15},(_,i)=>({id:String(i),name:`工作${i}：${'需要继续核对'.repeat(25)}`})),issues:[],faults:[],documents:[]}})
 render(<HandoverSummary projectId="p1" onUse={use}/>);const button=await screen.findByRole('button',{name:'带入交接说明'})
 expect(use).not.toHaveBeenCalled();fireEvent.click(button)
 const text=use.mock.calls[0][0];expect(text).toContain('未完工作 40 项');expect(text).toContain('仅列出部分事项');expect(text.length).toBeLessThanOrEqual(900)
})
it('shows a failed read as an error with retry instead of suggesting there are no pending items',async()=>{
 vi.mocked(api.get).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({data:{project_name:'现场甲',counts:{tasks:0,issues:0,faults:0,documents:0},tasks:[],issues:[],faults:[],documents:[]}})
 render(<HandoverSummary projectId="p1"/>);expect(await screen.findByText('交接事项读取失败')).toBeVisible();expect(screen.queryByText(/当前工作清单中没有待跟进事项/)).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:/重\s*试/}));expect(await screen.findByText(/当前工作清单中没有待跟进事项/)).toBeVisible()
})

it('carries the controlling rejection into a shortened handover before task details', async () => {
  const use = vi.fn()
  vi.mocked(api.get).mockResolvedValue({ data: { project_name: '现场甲', counts: { tasks: 30, issues: 0, faults: 0, documents: 0 }, tasks: Array.from({ length: 15 }, (_, i) => ({ id: String(i), name: `工作${i}${'很长的内容'.repeat(25)}` })), issues: [], faults: [], documents: [], acceptance_summary: { latest: { id: 'a2', accepted_at: '2026-10-02', accepted_by_name: '客户代表', conclusion: 'rejected' }, eligible: false, reason: '最新验收不通过，旧通过不能用于完成项目' } } })
  render(<HandoverSummary projectId="p1" onUse={use} />)
  expect(await screen.findByText('最新验收结论：不通过')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '带入交接说明' }))
  const text = use.mock.calls[0][0]
  expect(text).toContain('最新验收：不通过 · 2026-10-02 · 客户代表')
  expect(text).toContain('旧通过不能用于完成项目')
  expect(text.indexOf('最新验收')).toBeLessThan(text.indexOf('工作：'))
  expect(text.length).toBeLessThanOrEqual(900)
})

it('links a pending document instance to the document list without treating its id as a task', async () => {
  vi.mocked(api.get).mockResolvedValue({ data: { project_name: '现场甲', counts: { tasks: 0, issues: 0, faults: 0, documents: 1 }, tasks: [], issues: [], faults: [], documents: [{ id: 'document-1', code: '6.2', name: '项目周报', status: 'pending' }] } })
  render(<HandoverSummary projectId="p1" />)
  fireEvent.click(await screen.findByRole('button', { name: /资料 · 6.2 · 项目周报/ }))
  expect(navigate).toHaveBeenCalledWith('/pm/projects/p1/documents')
})
