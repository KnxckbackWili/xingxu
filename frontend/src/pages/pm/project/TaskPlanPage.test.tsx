import { beforeEach, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import TaskPlanPage from './TaskPlanPage'
import { catalog, work } from '../../../test/workItems'
const { get, post, auth } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), auth: { user: { id: 'u', role: 'pm' } as any } }))
vi.mock('../../../api/client', () => ({ api: { get, post, put: vi.fn() }, errMsg: () => '读取失败' }))
vi.mock('../../../stores/auth', () => ({ useAuth: () => auth }))
vi.mock('../../../hooks/useVehicleTypes', () => ({ useVehicleTypes: () => ({ options: [] }) }))
const source = catalog([work(), work({ id: 'car', name: '真实车辆检查', kind: 'vehicle', matrix: { linked: true, name: '到场点检', completed_count: 2, expected_count: 3, percent: 66.7, warning: '已完成（迁移，车号未知），不代表逐台核验' } })])
beforeEach(() => {
  auth.user = { id: 'u', role: 'pm' }; get.mockReset(); post.mockReset()
  get.mockImplementation(async (url: string) => ({ data: url.endsWith('/work-items') ? source : url.endsWith('/vehicle-progress') ? { steps: [] } : url.endsWith('/history') ? { read_only: true, reports: [{ client_uuid: 'original-uuid', note: '原记录' }] } : url.endsWith('/workspace') ? { project: { id: 'p', name: '原项目' }, task: { id: 'w1', description: '原施工说明' }, work_item: work(), entries: [], can_complete: true, can_override: true } : [] }))
})
function show(props: any = {}) { return render(<MemoryRouter><TaskPlanPage projectId="p" {...props} /></MemoryRouter>) }
it('shows phase/work items, matrix identity warnings and history without editable quantities', async () => {
  show(); expect(await screen.findByText('现场验证')).toBeVisible(); expect(screen.getAllByText('原模块标签')[0]).toBeVisible(); expect(screen.getByText('2 / 3 个车辆环节')).toBeVisible(); expect(screen.getByText(/不代表逐台核验/)).toBeVisible()
  expect(screen.queryByRole('spinbutton')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '现场验证的更多操作' })); fireEvent.click(await screen.findByRole('menuitem', { name: '历史来源' }))
  expect(await screen.findByText(/original-uuid/)).toBeVisible()
})
it('keeps execution details in the global drawer and calls its close callback', async () => {
  const close = vi.fn(); show({ focusTaskId: 'w1', detailsOnly: true, onDetailClose: close })
  expect(await screen.findByText('原项目')).toBeVisible(); expect(screen.queryByRole('heading', { name: '工作项' })).toBeNull(); expect(screen.getByRole('button', { name: '标记完成' })).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: /Close/ })); expect(close).toHaveBeenCalledOnce()
})
it('uses authoritative project permission and keeps a failed load recoverable', async () => {
  get.mockRejectedValueOnce(new Error('network')); show(); expect(await screen.findByText('读取失败')).toBeVisible(); fireEvent.click(screen.getByRole('button', { name: '刷新核对' })); expect(await screen.findByText('现场验证')).toBeVisible()
})
it('ignores a late previous project response', async () => {
  let done!: (r: any) => void
  get.mockImplementation((url: string) => url === '/projects/p/work-items' ? new Promise(resolve => { done = resolve }) : Promise.resolve({ data: url.endsWith('/work-items') ? catalog([work({ id: 'new', name: '新项目工作' })]) : { steps: [] } }))
  const v = show(); v.rerender(<MemoryRouter><TaskPlanPage projectId="next" /></MemoryRouter>); await screen.findByText('新项目工作')
  await act(async () => done({ data: source })); expect(screen.queryByText('现场验证')).toBeNull()
})
it('displays retired preparation sources read-only and honors a project plan denial', async () => {
  get.mockImplementation(async (url: string) => ({ data: url.endsWith('/work-items') ? { ...source, legacy_work_items: [work({ id: 'legacy', name: '原准备工作' })], permissions: { plan: false, record: false, override: false } } : { steps: [] } }))
  show(); await screen.findByText('现场验证'); expect(screen.queryByRole('button', { name: '添加工作项' })).toBeNull(); expect(screen.getByRole('button', { name: '标记完成' })).toBeDisabled(); fireEvent.click(screen.getByText('历史准备工作来源（只读） 1 项')); await waitFor(() => expect(screen.getByText('原准备工作')).toBeVisible())
})

it('filters by state and search, opening every matching phase', async () => {
  show(); expect(await screen.findByText('现场验证')).toBeVisible()
  const filters = screen.getByRole('group', { name: '筛选工作项' })
  expect(screen.getByRole('button', { name: '全部 2' })).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(screen.getByRole('button', { name: '车辆工作 1' }))
  expect(filters).toBeInTheDocument(); expect(screen.queryByText('现场验证')).toBeNull(); expect(screen.getByText('真实车辆检查')).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: '全部 2' }))
  fireEvent.change(screen.getByRole('textbox', { name: '查找工作项' }), { target: { value: '不存在的工作' } })
  expect(screen.getByText('没有符合条件的工作项')).toBeVisible()
})
