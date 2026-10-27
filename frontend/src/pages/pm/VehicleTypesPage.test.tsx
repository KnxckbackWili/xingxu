const { permissionActor } = vi.hoisted(() => ({ permissionActor: { user: { id: 'admin', role: 'admin', system_permissions: undefined as string[] | undefined } } }))
vi.mock('../../stores/auth', () => ({ useAuth: () => ({ user: permissionActor.user }) }))
import { StrictMode } from 'react'
import { beforeEach, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import VehicleTypesPage from './VehicleTypesPage'
import { vehicleTypeApi } from '../../api'
vi.mock('../../api', () => ({ vehicleTypeApi: { listAll: vi.fn(), create: vi.fn(), update: vi.fn(), reorder: vi.fn() } }))
vi.mock('../../api/client', () => ({ errMsg: () => '请求失败' }))
const ROWS = [
  { id: 'v1', name: '双向车', is_enabled: true, sort_order: 0 },
  { id: 'v2', name: '背负式', is_enabled: true, sort_order: 1 },
]
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
function mount(strict = false) {
  const page = <ConfigProvider theme={{ token: { motion: false } }}><VehicleTypesPage /></ConfigProvider>
  return render(strict ? <StrictMode>{page}</StrictMode> : page)
}
it('allows a granted field account to manage the dictionary but keeps a view-only account read-only', async () => {
  permissionActor.user = { id: 'member', role: 'worker', system_permissions: ['system.vehicle_types.view', 'system.vehicle_types.manage'] }
  const view = mount()
  await screen.findByText('双向车')
  expect(screen.getByRole('button', { name: /添加车型/ })).toBeEnabled()
  permissionActor.user = { id: 'member', role: 'worker', system_permissions: ['system.vehicle_types.view'] }
  view.rerender(<ConfigProvider theme={{ token: { motion: false } }}><VehicleTypesPage /></ConfigProvider>)
  expect(screen.queryByRole('button', { name: /添加车型/ })).toBeNull()
  for (const button of screen.getAllByRole('button', { name: /重命名|上移|下移/ })) expect(button).toBeDisabled()
  expect(vehicleTypeApi.update).not.toHaveBeenCalled()
})
beforeEach(() => {
  permissionActor.user = { id: 'admin', role: 'admin', system_permissions: undefined }
  vi.clearAllMocks()
  vi.mocked(vehicleTypeApi.listAll).mockResolvedValue(ROWS)
  vi.mocked(vehicleTypeApi.create).mockResolvedValue({})
  vi.mocked(vehicleTypeApi.update).mockResolvedValue({})
  vi.mocked(vehicleTypeApi.reorder).mockResolvedValue({})
})

it('serializes create and blocks cancellation during save, then releases on failure', async () => {
  const pending = deferred<any>()
  vi.mocked(vehicleTypeApi.create).mockReturnValueOnce(pending.promise)
  mount()
  await screen.findByText('双向车')
  fireEvent.click(screen.getByRole('button', { name: /添加车型/ }))
  const dialog = screen.getByRole('dialog')
  fireEvent.change(within(dialog).getByRole('textbox'), { target: { value: '叉车' } })
  const form = dialog.querySelector('form')!
  await act(async () => { fireEvent.submit(form); fireEvent.submit(form) })
  expect(vehicleTypeApi.create).toHaveBeenCalledTimes(1)
  expect(vehicleTypeApi.create).toHaveBeenCalledWith({ name: '叉车' })
  expect(within(dialog).getByRole('button', { name: /Cancel|取\s*消/ })).toBeDisabled()
  fireEvent.keyDown(dialog, { key: 'Escape', code: 'Escape' })
  expect(dialog).toBeInTheDocument()
  await act(async () => pending.reject(new Error('offline')))
  await act(async () => fireEvent.submit(form))
  expect(vehicleTypeApi.create).toHaveBeenCalledTimes(2)
})

it('canceled creation cannot submit after asynchronous form validation', async () => {
  mount()
  await screen.findByText('双向车')
  fireEvent.click(screen.getByRole('button', { name: /添加车型/ }))
  const dialog = screen.getByRole('dialog')
  fireEvent.change(within(dialog).getByRole('textbox'), { target: { value: '叉车' } })
  act(() => {
    fireEvent.submit(dialog.querySelector('form')!)
    fireEvent.click(within(dialog).getByRole('button', { name: /Cancel|取\s*消/ }))
  })
  await act(async () => {})
  expect(vehicleTypeApi.create).not.toHaveBeenCalled()
})

it('serializes rename and keeps the confirmed name when refresh fails', async () => {
  const pending = deferred<any>()
  vi.mocked(vehicleTypeApi.update).mockReturnValueOnce(pending.promise)
  mount()
  await screen.findByText('双向车')
  fireEvent.click(screen.getAllByRole('button', { name: /重命名/ })[0])
  const dialog = screen.getByRole('dialog')
  fireEvent.change(within(dialog).getByRole('textbox'), { target: { value: '双向 AGV' } })
  await act(async () => { fireEvent.submit(dialog.querySelector('form')!); fireEvent.submit(dialog.querySelector('form')!) })
  expect(vehicleTypeApi.update).toHaveBeenCalledTimes(1)
  expect(vehicleTypeApi.update).toHaveBeenCalledWith('v1', { name: '双向 AGV' })
  expect(screen.getAllByRole('switch')[0]).toBeDisabled()
  vi.mocked(vehicleTypeApi.listAll).mockRejectedValueOnce(new Error('offline'))
  await act(async () => pending.resolve({}))
  expect(await screen.findByText('双向 AGV')).toBeVisible()
})

it('locks reorder against repeated clicks and competing status updates', async () => {
  const pending = deferred<any>()
  vi.mocked(vehicleTypeApi.reorder).mockReturnValueOnce(pending.promise)
  mount()
  await screen.findByText('双向车')
  const down = screen.getAllByRole('button', { name: '下移' })[0]
  const toggle = screen.getAllByRole('switch')[0]
  act(() => { fireEvent.click(down); fireEvent.click(down); fireEvent.click(toggle) })
  expect(vehicleTypeApi.reorder).toHaveBeenCalledExactlyOnceWith(['v2', 'v1'])
  expect(vehicleTypeApi.update).not.toHaveBeenCalled()
  vi.mocked(vehicleTypeApi.listAll).mockRejectedValueOnce(new Error('offline'))
  await act(async () => pending.resolve({}))
  expect(screen.getAllByRole('row')[1]).toHaveTextContent('背负式')
})

it('ignores stale initial responses and retains confirmed disabled status on refresh failure', async () => {
  const old = deferred<any>()
  vi.mocked(vehicleTypeApi.listAll).mockReturnValueOnce(old.promise)
  mount(true)
  await screen.findByText('双向车')
  vi.mocked(vehicleTypeApi.listAll).mockRejectedValueOnce(new Error('offline'))
  act(() => { fireEvent.click(screen.getAllByRole('switch')[0]); fireEvent.click(screen.getAllByRole('switch')[0]) })
  await waitFor(() => expect(vehicleTypeApi.update).toHaveBeenCalledExactlyOnceWith('v1', { is_enabled: false }))
  await waitFor(() => expect(screen.getAllByRole('switch')[0]).not.toBeChecked())
  await act(async () => old.resolve(ROWS))
  expect(screen.getAllByRole('switch')[0]).not.toBeChecked()
})

it('does not start a refresh when a mutation completes after navigation', async () => {
  const pending = deferred<any>()
  vi.mocked(vehicleTypeApi.update).mockReturnValueOnce(pending.promise)
  const { unmount } = mount()
  await screen.findByText('双向车')
  fireEvent.click(screen.getAllByRole('switch')[0])
  unmount()
  await act(async () => pending.resolve({}))
  expect(vehicleTypeApi.listAll).toHaveBeenCalledTimes(1)
})

it('reorders a search result against the whole dictionary rather than the filtered row index', async () => {
  mount()
  await screen.findByText('双向车')
  fireEvent.change(screen.getByRole('searchbox', { name: '搜索车型' }), { target: { value: '背负' } })
  expect(screen.queryByText('双向车')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: '上移' })).toBeEnabled()
  fireEvent.click(screen.getByRole('button', { name: '上移' }))
  await waitFor(() => expect(vehicleTypeApi.reorder).toHaveBeenCalledExactlyOnceWith(['v2', 'v1']))
})
