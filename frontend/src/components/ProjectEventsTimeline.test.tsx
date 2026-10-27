import { beforeEach, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'

const { get, put } = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }))
vi.mock('../api/client', () => ({ api: { get, put }, errMsg: () => '保存失败，请重试' }))
import ProjectEventsTimeline from './ProjectEventsTimeline'

const data = { timezone: 'Asia/Shanghai', version: 3, dispatch_platform: 'integrated', arrival_summary: { expected: 2, registered: 1, arrived: 1, registry_complete: false }, events: [
  { event_key: 'ship', label: '发车', actual_at: '2026-10-20T06:30:00+00:00', planned_date: '2026-10-19', derived: false, actual_precision: 'datetime' },
  { event_key: 'arrival_all', label: '全部到场', actual_at: null, actual_date: null, derived: true, actual_precision: 'date' },
] }
beforeEach(() => { vi.clearAllMocks(); get.mockResolvedValue({ data }); put.mockResolvedValue({ data: {} }) })

it('shows actual instants in project time and date-only aggregate evidence, with no manual aggregate control', async () => {
  render(<ProjectEventsTimeline projectId="p1" canEdit />)
  expect(await screen.findByText(/2026-10-20 14:30/)).toBeVisible()
  expect(screen.getByText(/按逐台到场日期汇总；计划 2 台，已建档 1 台，到场 1 台/)).toBeVisible()
  expect(screen.queryByRole('button', { name: /登记全部到场|清除全部到场/ })).not.toBeInTheDocument()
})

it('requires a clear reason and sends one atomic request while save is pending', async () => {
  let resolve!: (value: any) => void
  put.mockImplementation(() => new Promise(done => { resolve = done }))
  const changed = vi.fn()
  render(<ProjectEventsTimeline projectId="p1" canEdit onChanged={changed} />)
  fireEvent.click(await screen.findByRole('button', { name: '清除发车实际时间' }))
  const save = screen.getByRole('button', { name: /^保 存$|^保存$/ })
  fireEvent.click(save)
  expect(await screen.findByText('请填写清除理由')).toBeInTheDocument()
  expect(put).not.toHaveBeenCalled()
  fireEvent.change(screen.getByLabelText('清除理由'), { target: { value: '误登记发车' } })
  fireEvent.click(save); fireEvent.click(save)
  await waitFor(() => expect(put).toHaveBeenCalledTimes(1))
  expect(put).toHaveBeenCalledWith('/projects/p1/events/ship', expect.objectContaining({ actual_at: null, reason: '误登记发车', version: 3 }))
  await act(async () => { resolve({ data: {} }) })
  await waitFor(() => expect(changed).toHaveBeenCalledTimes(1))
})

it('keeps event data read-only without update authority', async () => {
  render(<ProjectEventsTimeline projectId="p1" canEdit={false} />)
  await screen.findByText('发车')
  expect(screen.queryByRole('button', { name: /更正|清除|登记/ })).not.toBeInTheDocument()
})

it('shows signed dates without inventing midnight and preserves date precision when saving', async () => {
  const dateOnly={...data,events:[{event_key:'commissioning_done',label:'调试完工',actual_at:null,actual_date:'2026-01-02',actual_precision:'date',derived:false,source_description:'签单明确记录的实际日期，仅精确到日'}]}
  get.mockResolvedValue({data:dateOnly})
  render(<ProjectEventsTimeline projectId="p1" canEdit />)
  expect(await screen.findByRole('cell', { name: '2026-01-02' })).toBeVisible()
  expect(screen.queryByText(/2026-01-02 00:00/)).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button',{name:'更正调试完工时间'}))
  fireEvent.click(screen.getByRole('button',{name:/^保 存$|^保存$/}))
  await waitFor(()=>expect(put).toHaveBeenCalledWith('/projects/p1/events/commissioning_done',expect.objectContaining({actual_date:'2026-01-02'})))
  expect(put.mock.calls[0][1]).not.toHaveProperty('actual_at')
})

it('ignores a completed save from the previous project after navigation', async () => {
  let finish!: (value: unknown)=>void
  put.mockImplementation(()=>new Promise(resolve=>{finish=resolve}))
  const changed=vi.fn()
  const view=render(<ProjectEventsTimeline projectId="p1" canEdit onChanged={changed} />)
  fireEvent.click(await screen.findByRole('button',{name:'清除发车实际时间'}))
  fireEvent.change(screen.getByLabelText('清除理由'),{target:{value:'原项目误登记'}})
  fireEvent.click(screen.getByRole('button',{name:/^保 存$|^保存$/}))
  await waitFor(()=>expect(put).toHaveBeenCalledTimes(1))
  view.rerender(<ProjectEventsTimeline projectId="p2" canEdit onChanged={changed} />)
  await act(async()=>finish({data:{}}))
  expect(changed).not.toHaveBeenCalled()
  await waitFor(()=>expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
})
