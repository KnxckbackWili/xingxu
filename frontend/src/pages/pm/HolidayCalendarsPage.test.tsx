import { beforeEach, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import HolidayCalendarsPage from './HolidayCalendarsPage'
import { holidayCalendarsApi, type AnnualCalendar } from '../../api/holidayCalendars'
const { actor } = vi.hoisted(() => ({ actor: { user: { role: 'admin', system_permissions: ['system.holidays.read', 'system.holidays.manage'] } } }))
vi.mock('../../stores/auth', () => ({ useAuth: () => actor }))
vi.mock('../../api/holidayCalendars', () => ({ holidayCalendarsApi: { get: vi.fn(), save: vi.fn() } }))
const year = new Date().getFullYear() + 1
const missing = (y = year): AnnualCalendar => ({ year: y, available: false, source_kind: 'missing', holidays: [], workdays: [], source_name: '', source_url: '', published_on: null, note: '', version: 0 })
const complete = (y = year): AnnualCalendar => ({ year: y, available: true, source_kind: 'maintained', holidays: [`${y}-01-01`], workdays: [`${y}-01-02`], source_name: '测试来源', source_url: 'https://example.com/calendar', published_on: '2026-10-01', note: '全年数据', version: 2 })
const mount = () => render(<ConfigProvider theme={{ token: { motion: false } }}><HolidayCalendarsPage /></ConfigProvider>)
const chooseFile = async (container: HTMLElement, data: unknown) => {
  const file = new File(['test'], 'calendar.json', { type: 'application/json' })
  Object.defineProperty(file, 'text', { value: async () => JSON.stringify(data) })
  fireEvent.change(container.querySelector('input[type=file]')!, { target: { files: [file] } })
}
beforeEach(() => {
  vi.clearAllMocks()
  actor.user.system_permissions = ['system.holidays.read', 'system.holidays.manage']
  vi.mocked(holidayCalendarsApi.get).mockResolvedValue(missing())
  vi.mocked(holidayCalendarsApi.save).mockResolvedValue(complete())
})

it('shows missing next-year coverage and keeps a read-only user out of maintenance', async () => {
  actor.user.system_permissions = ['system.holidays.read']
  mount()
  expect(await screen.findByText(`缺少 ${year} 年节假日与调休数据`)).toBeVisible()
  expect(screen.getByText(/不能视为没有节假日/)).toBeVisible()
  expect(screen.queryByRole('button', { name: /保存全年安排/ })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /从JSON文件填入/ })).not.toBeInTheDocument()
  expect(screen.getByLabelText('全年放假日期')).toBeDisabled()
})

it('reports unavailable data rather than empty success and supports retry', async () => {
  vi.mocked(holidayCalendarsApi.get).mockRejectedValueOnce(new Error('offline')).mockResolvedValue(complete())
  mount()
  expect(await screen.findByText('节假日数据加载失败')).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: /重.*试/ }))
  expect(await screen.findByText('人工维护，请核对来源')).toBeVisible()
  expect(screen.getByRole('link', { name: '测试来源' })).toHaveAttribute('href', 'https://example.com/calendar')
  expect(screen.getByText(/发布于 2026-10-01/)).toBeVisible()
})

it('previews file contents without writing, requires complete confirmation and prevents duplicate saves', async () => {
  const { container } = mount()
  await screen.findByText('尚无全年数据')
  await chooseFile(container, complete())
  expect(await screen.findByText(/文件已填入，尚未保存/)).toBeVisible()
  expect(screen.getByLabelText('调休补班日期')).toHaveValue(`${year}-01-02`)
  expect(holidayCalendarsApi.save).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: /保存全年安排/ }))
  expect(await screen.findByText('请先核对全年安排')).toBeVisible()
  let finish: (value: AnnualCalendar) => void = () => {}
  vi.mocked(holidayCalendarsApi.save).mockImplementation(() => new Promise(resolve => { finish = resolve }))
  fireEvent.click(screen.getByRole('checkbox', { name: '已核对全年放假和调休补班日期，并保留发布来源' }))
  const save = screen.getByRole('button', { name: /保存全年安排/ })
  fireEvent.click(save); fireEvent.click(save)
  await waitFor(() => expect(holidayCalendarsApi.save).toHaveBeenCalledTimes(1))
  expect(holidayCalendarsApi.save).toHaveBeenCalledWith(year, { year, holidays: [`${year}-01-01`], workdays: [`${year}-01-02`], source_name: '测试来源', source_url: 'https://example.com/calendar', published_on: '2026-10-01', note: '全年数据', complete: true, expected_version: 0 })
  await act(async () => finish(complete()))
  expect(await screen.findByText('人工维护，请核对来源')).toBeVisible()
})

it('preserves input when an imported file belongs to another year', async () => {
  vi.mocked(holidayCalendarsApi.get).mockResolvedValue(complete())
  const { container } = mount()
  await screen.findByText('人工维护，请核对来源')
  fireEvent.change(screen.getByLabelText('说明'), { target: { value: '当前草稿' } })
  await chooseFile(container, complete(year + 1))
  expect(await screen.findByText(/文件须为所选年度/)).toBeVisible()
  expect(screen.getByLabelText('说明')).toHaveValue('当前草稿')
  expect(holidayCalendarsApi.save).not.toHaveBeenCalled()
})

it('preserves annual edits after a version conflict for explicit reconciliation', async () => {
  vi.mocked(holidayCalendarsApi.get).mockResolvedValue(complete())
  vi.mocked(holidayCalendarsApi.save).mockRejectedValue({ isAxiosError: true, response: { data: { detail: '该年度已被其他人修改，请重新加载后核对' } } })
  mount()
  await screen.findByText('人工维护，请核对来源')
  fireEvent.change(screen.getByLabelText('说明'), { target: { value: '本次输入' } })
  fireEvent.click(screen.getByRole('checkbox'))
  fireEvent.click(screen.getByRole('button', { name: /保存全年安排/ }))
  expect(await screen.findByText('该年度已被其他人修改，请重新加载后核对')).toBeVisible()
  expect(screen.getByLabelText('说明')).toHaveValue('本次输入')
  expect(holidayCalendarsApi.get).toHaveBeenCalledTimes(1)
  expect(vi.mocked(holidayCalendarsApi.save).mock.calls[0][1].expected_version).toBe(2)
})

it('ignores a late old-year response and a late import after switching years', async () => {
  const { container } = mount()
  await screen.findByText('尚无全年数据')
  let finishImport: (value: string) => void = () => {}
  const file = new File(['test'], 'old.json', { type: 'application/json' })
  Object.defineProperty(file, 'text', { value: () => new Promise(resolve => { finishImport = resolve }) })
  fireEvent.change(container.querySelector('input[type=file]')!, { target: { files: [file] } })
  vi.mocked(holidayCalendarsApi.get).mockResolvedValue(complete(year + 1))
  fireEvent.change(screen.getByRole('spinbutton', { name: '节假日年度' }), { target: { value: String(year + 1) } })
  await screen.findByText('人工维护，请核对来源')
  await act(async () => finishImport(JSON.stringify(complete())))
  expect(screen.getByLabelText('全年放假日期')).toHaveValue(`${year + 1}-01-01`)
  expect(screen.queryByText(/文件已填入，尚未保存/)).not.toBeInTheDocument()
})
