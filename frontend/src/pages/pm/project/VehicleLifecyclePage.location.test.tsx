import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import { beforeEach, expect, it, vi } from 'vitest'
vi.mock('../../../components/VehicleProgressMatrix',()=>({default:()=>null}))
import VehicleLifecyclePage from './VehicleLifecyclePage'
import { api } from '../../../api/client'

vi.mock('react-router-dom', () => ({ useLocation: () => ({ search: '' }) }))
vi.mock('../../../stores/auth', () => ({ useAuth: () => ({ user: { id: 'pm', role: 'pm' } }) }))
vi.mock('../../../api/client', () => ({ api: { get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() }, errMsg: () => '位置保存失败' }))
const project = { id: 'p1', name: '车辆项目', manager: 'pm', technical_manager: null, members: ['pm'], status: 'executing', capabilities: ['project.manage_plan'] }
let saved: any
beforeEach(() => {
  vi.resetAllMocks()
  saved = { id: 'unit1', asset_code: 'AGV-001', location: '原仓库', current_status: 'fault', open_issue_count: 1 }
  vi.mocked(api.get).mockImplementation(async url => ({ data: url.endsWith('/vehicle-units') ? [saved] : [] }))
  vi.mocked(api.put).mockImplementation(async (_url, body: any) => ({ data: saved = { ...saved, ...body } }))
})
function page(overrides: any = {}) {
  return <ConfigProvider theme={{ token: { motion: false } }}><VehicleLifecyclePage project={{ ...project, ...overrides } as any} /></ConfigProvider>
}
async function editLocation() {
  fireEvent.click(await screen.findByRole('button', { name: '修改AGV-001当前位置' }))
  return screen.findByRole('textbox', { name: 'AGV-001新位置' })
}

it('changes location directly without inventing an issue or changing its existing fault state', async () => {
  render(page())
  const input = await editLocation()
  fireEvent.change(input, { target: { value: '2号库 A区' } })
  fireEvent.click(screen.getByRole('button', { name: '保存位置' }))
  await waitFor(() => expect(api.put).toHaveBeenCalledWith('/projects/p1/vehicle-units/unit1', { location: '2号库 A区' }))
  expect(await screen.findByRole('button', { name: '修改AGV-001当前位置' })).toHaveTextContent('2号库 A区')
  expect(saved.current_status).toBe('fault')
  expect(saved.open_issue_count).toBe(1)
  expect(api.post).not.toHaveBeenCalled()
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

it('Escape cancels the location draft without writing and returns focus to its trigger', async () => {
  render(page())
  const input = await editLocation()
  fireEvent.change(input, { target: { value: '未保存的位置' } })
  fireEvent.keyDown(input, { key: 'Escape' })
  await waitFor(() => expect(input).not.toBeVisible())
  const trigger = screen.getByRole('button', { name: '修改AGV-001当前位置' })
  expect(trigger).toHaveTextContent('原仓库')
  expect(trigger).toHaveFocus()
  expect(api.put).not.toHaveBeenCalled()
  fireEvent.click(trigger)
  expect(await screen.findByRole('textbox', { name: 'AGV-001新位置' })).toHaveValue('原仓库')
})

it('prevents duplicate location saves and keeps the failed input for retry', async () => {
  let reject: (value: any) => void = () => {}
  vi.mocked(api.put).mockReturnValueOnce(new Promise((_resolve, fail) => { reject = fail }))
  render(page())
  const input = await editLocation()
  fireEvent.change(input, { target: { value: '待保存位置' } })
  fireEvent.keyDown(input, { key: 'Enter' })
  fireEvent.keyDown(input, { key: 'Enter' })
  fireEvent.click(screen.getByRole('button', { name: '保存位置' }))
  await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1))
  expect(input).toBeDisabled()
  expect(screen.getByRole('button', { name: /取\s*消/ })).toBeDisabled()
  expect(screen.getByRole('button', { name: '修改AGV-001当前位置' })).toHaveTextContent('原仓库')
  await act(async () => reject(new Error('offline')))
  expect(await screen.findByRole('alert')).toHaveTextContent('位置保存失败')
  expect(input).toHaveValue('待保存位置')
  expect(input).not.toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: '保存位置' }))
  await waitFor(() => expect(api.put).toHaveBeenCalledTimes(2))
  expect(await screen.findByRole('button', { name: '修改AGV-001当前位置' })).toHaveTextContent('待保存位置')
})

it('explicitly clears the current location without touching fault or historical records', async () => {
  render(page())
  fireEvent.change(await editLocation(), { target: { value: '' } })
  fireEvent.click(screen.getByRole('button', { name: '保存位置' }))
  await waitFor(() => expect(api.put).toHaveBeenCalledWith('/projects/p1/vehicle-units/unit1', { location: '' }))
  expect(await screen.findByRole('button', { name: '修改AGV-001当前位置' })).toHaveTextContent('填写位置')
  expect(saved.current_status).toBe('fault')
  expect(api.post).not.toHaveBeenCalled()
})

it.each(['capabilities', 'archived', 'unknown'])('%s vehicles show location as read-only text', async mode => {
  render(page(mode === 'capabilities' ? { capabilities: [] } : { status: mode === 'unknown' ? 'legacy_unknown' : 'archived' }))
  expect(await screen.findByText('原仓库')).toBeVisible()
  expect(screen.queryByRole('button', { name: '修改AGV-001当前位置' })).not.toBeInTheDocument()
  expect(api.put).not.toHaveBeenCalled()
})

it('a previous-project save cannot overwrite the next project or show a stale success notice', async () => {
  let resolve: (value: any) => void = () => {}
  vi.mocked(api.put).mockReturnValueOnce(new Promise(done => { resolve = done }))
  vi.mocked(api.get).mockImplementation(async url => ({ data: url.endsWith('/vehicle-units')
    ? url.includes('/p2/') ? [{ ...saved, id: 'unit2', asset_code: 'AGV-002', location: '新项目仓库' }] : [saved] : [] }))
  const view = render(page())
  const input = await editLocation()
  fireEvent.change(input, { target: { value: '旧项目迟到位置' } })
  fireEvent.keyDown(input, { key: 'Enter' })
  await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1))
  view.rerender(page({ id: 'p2' }))
  await screen.findByText('AGV-002')
  await act(async () => resolve({ data: { ...saved, location: '旧项目迟到位置' } }))
  expect(screen.getByRole('button', { name: '修改AGV-002当前位置' })).toHaveTextContent('新项目仓库')
  expect(screen.queryByText('旧项目迟到位置')).not.toBeInTheDocument()
  expect(screen.queryByText('AGV-001当前位置已保存')).not.toBeInTheDocument()
})
