import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import dayjs from 'dayjs'
import TeamSchedulePage from './TeamSchedulePage'

const apiGet = vi.fn()
const openWorkDetail = vi.fn()
vi.mock('../../stores/workDetail', () => ({ openWorkDetail: (...args: unknown[]) => openWorkDetail(...args) }))

vi.mock('../../api/client', () => ({
  api: { get: (...args: unknown[]) => apiGet(...args) },
}))
vi.mock('../../stores/auth', () => ({
  useAuth: () => ({ user: { id: 'user-me', role: 'pm', display_name: '项目经理甲' } }),
}))

const people = [
  { id: 'w1', name: '张三' },
  { id: 'w2', name: '李四' },
]

/** 与 TeamSchedulePage 一致的月历网格起始：当月首日所在周之周一 */
const gridStartFor = (month: dayjs.Dayjs) => {
  const first = month.startOf('month')
  const offset = first.day() === 0 ? 6 : first.day() - 1
  return first.subtract(offset, 'day')
}
const allEntries = [
  { entry_id: 'e1', work_date: dayjs().format('YYYY-MM-DD'), assignee_id: 'w1', assignee_name: '张三',
    project_id: 'p1', project_name: '项目A', task_id: 't1', task_name: '任务一',
    planned_quantity: 2, completed_quantity: 1,
    status: 'planned', is_confirmed: true, is_locked: false, notes: '正常条目' },
  { entry_id: 'e2', work_date: dayjs().add(1, 'day').format('YYYY-MM-DD'), assignee_id: 'w2', assignee_name: '李四',
    project_id: 'p1', project_name: '项目A', task_id: 't1', task_name: '任务一',
    planned_quantity: 3, completed_quantity: 0,
    status: 'planned', is_confirmed: false, is_locked: true, notes: '' },
]

const renderPage = () => render(
  <ConfigProvider locale={zhCN}>
    <TeamSchedulePage />
  </ConfigProvider>,
)

beforeEach(() => {
  vi.clearAllMocks()
  apiGet.mockImplementation((_url: string, config?: { params?: { user_id?: string } }) =>
    Promise.resolve({
      data: {
        people,
        entries: config?.params?.user_id
          ? allEntries.filter((e) => e.assignee_id === config.params!.user_id)
          : allEntries,
      },
    }),
  )
})

describe('团队日程（HYPE-88，只读）', () => {
  it('固定月历视图（HYPE-90）：无 列表/日历 切换，默认即月历；条目显示 人/任务/计划量；只读无编辑入口', async () => {
    const { container } = renderPage()
    // 默认即月历：网格与周一表头直接渲染
    const today = dayjs().format('YYYY-MM-DD')
    await waitFor(() => expect(container.querySelector(`[data-date="${today}"]`)).toBeTruthy())
    expect(screen.getByText('一')).toBeInTheDocument()
    // 无 列表/日历 切换控件
    expect(screen.queryByText('列表')).not.toBeInTheDocument()
    expect(screen.queryByText('日历')).not.toBeInTheDocument()
    // 月历格条目显示 人 + 任务 + 计划量
    expect(await screen.findByText(/张三 · 任务一 · 计划 2/)).toBeInTheDocument()
    expect(screen.getByText(/李四 · 任务一 · 计划 3/)).toBeInTheDocument()
    // 只读：无任何编辑入口
    expect(screen.queryByRole('button', { name: /编\s*辑/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /删\s*除/ })).not.toBeInTheDocument()
    // 人员过滤下拉保留
    expect(screen.getByText('按人员过滤')).toBeInTheDocument()
  })

  it('人员过滤：选择某人后仅请求该人的条目', async () => {
    renderPage()
    await screen.findByText(/张三 · 任务一/)
    fireEvent.mouseDown(document.querySelector('.ant-select-selector') as HTMLElement)
    fireEvent.click(await screen.findByText('李四'))
    await waitFor(() => {
      const last = apiGet.mock.calls[apiGet.mock.calls.length - 1] as [string, { params: { user_id?: string } }]
      expect(last[1].params.user_id).toBe('w2')
    })
    await waitFor(() => expect(screen.queryByText(/张三 · 任务一/)).not.toBeInTheDocument())
    expect(screen.getByText(/李四 · 任务一 · 计划 3/)).toBeInTheDocument()
  })

  it('数据请求窗口按月历 42 格取数；切月更新窗口', async () => {
    const { container } = renderPage()
    const today = dayjs().format('YYYY-MM-DD')
    await waitFor(() => expect(container.querySelector(`[data-date="${today}"]`)).toBeTruthy())
    const last = apiGet.mock.calls[apiGet.mock.calls.length - 1] as [string, { params: { from_date: string; to_date: string } }]
    expect(dayjs(last[1].params.to_date).diff(dayjs(last[1].params.from_date), 'day')).toBe(41)
    // 切月后窗口更新到下一月所在网格
    fireEvent.click(screen.getByRole('button', { name: '下一月' }))
    await waitFor(() => {
      const now = apiGet.mock.calls[apiGet.mock.calls.length - 1] as [string, { params: { from_date: string; to_date: string } }]
      expect(now[1].params.from_date).toBe(gridStartFor(dayjs().add(1, 'month')).format('YYYY-MM-DD'))
    })
  })

  describe('当天明细 Drawer（HYPE-91，只读）', () => {
    const today = () => dayjs().format('YYYY-MM-DD')

    const openTodayDrawer = async () => {
      const { container } = renderPage()
      await waitFor(() => expect(container.querySelector(`[data-date="${today()}"]`)).toBeTruthy())
      fireEvent.click(container.querySelector(`[data-date="${today()}"]`) as Element)
      await waitFor(() => expect(screen.getByText(`${today()} 日程（1 条）`)).toBeInTheDocument())
      return document.querySelector('.ant-drawer-body') as HTMLElement
    }

    it('点日格打开当天明细：字段渲染完整（人/项目/任务/计划完成/状态/下达/备注）', async () => {
      const body = await openTodayDrawer()
      expect(within(body).getByText('张三')).toBeInTheDocument()
      expect(within(body).getByText('项目A · 任务一')).toBeInTheDocument()
      expect(within(body).getByText(/计划 2 \/ 完成 1/)).toBeInTheDocument()
      // 状态口径：数量未达标 → 待执行；已下达
      expect(within(body).getByText('待执行', { selector: '.ant-tag' })).toBeInTheDocument()
      expect(within(body).getByText('已下达', { selector: '.ant-tag' })).toBeInTheDocument()
      expect(within(body).getByText('备注：正常条目')).toBeInTheDocument()
      // 只读：无任何编辑/删除入口
      expect(within(body).queryByRole('button', { name: /编\s*辑/ })).not.toBeInTheDocument()
      expect(within(body).queryByRole('button', { name: /删\s*除/ })).not.toBeInTheDocument()
    })

    it('状态与锁定 Tag：已锁定条目显示「已锁定」；数量达标显示「已完成」', async () => {
      const tomorrow = dayjs().add(1, 'day').format('YYYY-MM-DD')
      const { container } = renderPage()
      await waitFor(() => expect(container.querySelector(`[data-date="${tomorrow}"]`)).toBeTruthy())
      fireEvent.click(container.querySelector(`[data-date="${tomorrow}"]`) as Element)
      await waitFor(() => expect(screen.getByText(`${tomorrow} 日程（1 条）`)).toBeInTheDocument())
      const body = document.querySelector('.ant-drawer-body') as HTMLElement
      expect(within(body).getByText('已锁定', { selector: '.ant-tag' })).toBeInTheDocument()
      expect(within(body).getByText('未下达', { selector: '.ant-tag' })).toBeInTheDocument()
      expect(within(body).queryByRole('button', { name: /编\s*辑/ })).not.toBeInTheDocument()
    })

    it('人员过滤生效时，当天明细同步过滤（仅显示过滤后的人）', async () => {
      const { container } = renderPage()
      await screen.findByText(/张三 · 任务一/)
      fireEvent.mouseDown(document.querySelector('.ant-select-selector') as HTMLElement)
      fireEvent.click(await screen.findByText('李四'))
      await waitFor(() => expect(screen.queryByText(/张三 · 任务一/)).not.toBeInTheDocument())
      const tomorrow = dayjs().add(1, 'day').format('YYYY-MM-DD')
      fireEvent.click(container.querySelector(`[data-date="${tomorrow}"]`) as Element)
      await waitFor(() => expect(screen.getByText(`${tomorrow} 日程（1 条）`)).toBeInTheDocument())
      const body = document.querySelector('.ant-drawer-body') as HTMLElement
      // 明细只包含过滤后的人（李四），不出现张三
      expect(within(body).getByText('李四')).toBeInTheDocument()
      expect(within(body).queryByText('张三')).not.toBeInTheDocument()
    })
  })
})

it('shows a retryable failure instead of an empty schedule', async () => {
  apiGet.mockRejectedValueOnce(new Error('offline'))
  renderPage()
  expect(await screen.findByText('团队日程加载失败')).toBeInTheDocument()
  expect(screen.queryByText('暂无团队日程')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '重新加载' }))
  expect(await screen.findByText(/张三 · 任务一/)).toBeInTheDocument()
})

it('ignores an earlier month response and keeps the latest month data', async () => {
  let resolveOld!: (value: unknown) => void
  apiGet.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    .mockResolvedValueOnce({ data: { people, entries: allEntries.map(entry => ({ ...entry, work_date: dayjs().add(1, 'month').startOf('month').add(4, 'day').format('YYYY-MM-DD') })) } })
  renderPage()
  fireEvent.click(screen.getByRole('button', { name: '下一月' }))
  await screen.findByText(/张三 · 任务一/)
  resolveOld({ data: { entries: [], people: [] } })
  await waitFor(() => expect(screen.queryByText('暂无团队日程')).toBeNull())
  expect(screen.getByText(/张三 · 任务一/)).toBeInTheDocument()
})

it('calendar dates are named keyboard-operable buttons', async () => {
  const user = (await import('@testing-library/user-event')).default.setup()
  renderPage()
  const button = await screen.findByRole('button', { name: `${dayjs().format('YYYY-MM-DD')}，1 项安排` })
  button.focus()
  await user.keyboard('{Enter}')
  expect(await screen.findByRole('dialog')).toBeInTheDocument()
  expect(button).toHaveAttribute('aria-current', 'date')
})

it('opens the exact selected work and entry directly from the day card', async () => {
  renderPage()
  fireEvent.click(await screen.findByRole('button', { name: `${dayjs().format('YYYY-MM-DD')}，1 项安排` }))
  const drawer = await screen.findByRole('dialog')
  fireEvent.click(within(drawer).getByRole('button', { name: '查看工作' }))
  expect(openWorkDetail).toHaveBeenCalledWith({ projectId: 'p1', taskId: 't1', entryId: 'e1', onChanged: expect.any(Function) })
  const previous = apiGet.mock.calls.length
  await openWorkDetail.mock.calls[0][0].onChanged()
  expect(apiGet.mock.calls.length).toBe(previous + 1)
  expect(apiGet.mock.calls[apiGet.mock.calls.length - 1]?.[0]).toBe('/dashboard/team-schedule')
})
