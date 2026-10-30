import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Modal } from 'antd'
import { Link, createMemoryRouter, RouterProvider } from 'react-router-dom'
import { useState } from 'react'
const { get, update, listActive } = vi.hoisted(() => ({ get: vi.fn(), update: vi.fn(), listActive: vi.fn() }))
vi.mock('../../../api', () => ({ projectApi: { update }, userApi: { listActive }, ROLE_MAP: {} }))
vi.mock('../../../api/client', () => ({ api: { get }, errMsg: () => '加载失败' }))
vi.mock('../../../stores/auth', () => ({ useAuth: () => ({ user: { id: 'pm', role: 'pm' } }) }))
vi.mock('../GovernancePage', () => ({ default: () => null }))
import EditPage from './EditPage'
beforeEach(() => {
  vi.clearAllMocks(); listActive.mockResolvedValue([]); update.mockResolvedValue({}); get.mockResolvedValue({ data: { items: [] } })
})
afterEach(() => { vi.restoreAllMocks() })
const editableProject = { id: 'p1', name: '项目', status: 'preparing', manager: 'pm', members: [], start_date: '2026-09-01', end_date: '2026-10-31', description: '原说明', version: 3 } as any
function show(project = editableProject, onReload = vi.fn()) {
  const router = createMemoryRouter([
    { path: '/edit', element: <><Link to="/overview">项目首页</Link><EditPage project={project} onReload={onReload} /></> },
    { path: '*', element: <div>其他页面</div> },
  ], { initialEntries: ['/edit'] })
  render(<RouterProvider router={router} />)
  return router
}
function watchConfirm() {
  return vi.spyOn(Modal, 'confirm').mockImplementation(() => ({ destroy: vi.fn(), update: vi.fn() }))
}

it('keeps the original form version when another update arrives during an unsaved edit', async () => {
  let refresh!: () => void
  function Page() {
    const [project, setProject] = useState(editableProject)
    refresh = () => setProject({ ...editableProject, description: '他人刚保存的说明', version: 4 })
    return <EditPage project={project} onReload={vi.fn()} />
  }
  const router = createMemoryRouter([{ path: '/edit', element: <Page /> }], { initialEntries: ['/edit'] })
  render(<RouterProvider router={router} />)
  fireEvent.change(await screen.findByLabelText('说明'), { target: { value: '本人的未保存编辑' } })
  act(refresh)
  expect(screen.getByLabelText('说明')).toHaveValue('本人的未保存编辑')
  fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))
  await waitFor(() => expect(update).toHaveBeenCalledOnce())
  expect(update).toHaveBeenCalledWith('p1', expect.objectContaining({ version: 3, description: '本人的未保存编辑' }))
})

it.each(['legacy_unknown', 'archived'])('%s renders original project fields read-only for its owner', async (status) => {
  listActive.mockResolvedValue([])
  const confirm = watchConfirm()
  const router = show({ id: 'p1', name: '历史项目', status, manager: 'pm', members: [], start_date: '2026-09-01', end_date: '2026-10-31' } as any)
  expect(await screen.findByLabelText('项目名称')).toBeDisabled()
  expect(screen.getByLabelText('项目名称')).toHaveValue('历史项目')
  expect(screen.getByRole('combobox', { name: '技术负责人' })).toBeDisabled()
  expect(screen.queryByRole('button', { name: /保 存|保存/ })).toBeNull()
  fireEvent.click(screen.getByText('项目首页'))
  await waitFor(() => expect(router.state.location.pathname).toBe('/overview'))
  expect(confirm).not.toHaveBeenCalled()
})

it('previews preparation dates before clearing the planned entry date without shifting them', async () => {
  listActive.mockResolvedValue([])
  update.mockResolvedValue({})
  get.mockResolvedValue({ data: { documents: [{ id: 'doc', name: '发车资料', due_at: '2026-09-15T09:00:00Z', status: 'pending', applicable: true, due_is_estimated: true }] } })
  const confirm = vi.spyOn(Modal, 'confirm').mockImplementation(() => ({ destroy: vi.fn(), update: vi.fn() }))
  const project = { id: 'p1', name: '项目', manager: 'pm', members: [], start_date: '2026-09-01', end_date: '2026-10-31', events: [{ event_key: 'ship', planned_date: '2026-09-15' }], version: 3 } as any
  show(project)
  const input = await screen.findByLabelText('发车计划日期')
  expect(input).toHaveValue('2026-09-15')
  const clear = input.closest('.ant-picker')!.querySelector('.ant-picker-clear')!
  fireEvent.mouseDown(clear)
  fireEvent.mouseUp(clear)
  fireEvent.click(clear)
  fireEvent.click(screen.getByRole('button', { name: /保 存|保存/ }))
  await waitFor(() => expect(confirm).toHaveBeenCalledOnce())
  expect(update).not.toHaveBeenCalled()
  const preview = confirm.mock.calls[0][0]
  render(<>{preview.content}</>)
  expect(screen.getByText('发车资料：2026-09-15T09:00:00Z（预计）')).toBeInTheDocument()
  await act(async () => { await preview.onOk?.() })
  expect(update).toHaveBeenCalledWith('p1', expect.objectContaining({ event_plans: expect.objectContaining({ ship: null }), version: 3 }))
  confirm.mockRestore()
})

it('leaves clean settings normally and preserves a dirty draft until discard is explicitly confirmed', async () => {
  const confirm = watchConfirm()
  const router = show()
  fireEvent.click(screen.getByText('项目首页'))
  await waitFor(() => expect(router.state.location.pathname).toBe('/overview'))
  expect(confirm).not.toHaveBeenCalled()
  await act(() => router.navigate('/edit'))
  fireEvent.change(await screen.findByLabelText('说明'), { target: { value: '尚未保存的说明' } })
  fireEvent.click(screen.getByText('项目首页'))
  await waitFor(() => expect(confirm).toHaveBeenCalledOnce())
  expect(confirm.mock.calls[0][0].title).toBe('项目设置有未保存的修改')
  expect(router.state.location.pathname).toBe('/edit')
  act(() => confirm.mock.calls[0][0].onCancel?.())
  expect(screen.getByLabelText('说明')).toHaveValue('尚未保存的说明')
  fireEvent.click(screen.getByText('项目首页'))
  await waitFor(() => expect(confirm).toHaveBeenCalledTimes(2))
  act(() => confirm.mock.calls[1][0].onOk?.())
  await waitFor(() => expect(router.state.location.pathname).toBe('/overview'))
  expect(update).not.toHaveBeenCalled()
})

it('successful persistence clears dirty state and allows normal navigation', async () => {
  const confirm = watchConfirm()
  const onReload = vi.fn()
  const router = show(editableProject, onReload)
  fireEvent.change(await screen.findByLabelText('说明'), { target: { value: '已保存的新说明' } })
  fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))
  await waitFor(() => expect(onReload).toHaveBeenCalledOnce())
  expect(update).toHaveBeenCalledWith('p1', expect.objectContaining({ version: 3, description: '已保存的新说明' }))
  fireEvent.click(screen.getByRole('tab', { name: '项目协管' }))
  expect(screen.getByRole('tab', { name: '项目协管' })).toHaveAttribute('aria-selected', 'true')
  expect(confirm).not.toHaveBeenCalled()
  fireEvent.click(screen.getByText('项目首页'))
  await waitFor(() => expect(router.state.location.pathname).toBe('/overview'))
  expect(confirm).not.toHaveBeenCalled()
})

it('persists the technical manager clear as null and keeps it clear after reloading saved information', async () => {
  listActive.mockResolvedValue([{ id: 'tech', display_name: '原技术负责人', role: 'worker' }])
  const confirm = watchConfirm()
  const onReload = vi.fn()
  function ReloadingPage() {
    const [project, setProject] = useState({ ...editableProject, technical_manager: 'tech' })
    return <><Link to="/overview">项目首页</Link><EditPage project={project} onReload={() => {
      onReload()
      setProject({ ...editableProject, technical_manager: null, version: 4 })
    }} /></>
  }
  const router = createMemoryRouter([{ path: '/edit', element: <ReloadingPage /> }, { path: '*', element: <div>其他页面</div> }], { initialEntries: ['/edit'] })
  render(<RouterProvider router={router} />)
  const select = (await screen.findByRole('combobox', { name: '技术负责人' })).closest('.ant-select')!
  await waitFor(() => expect(select).toHaveTextContent('原技术负责人（实施工程师）'))
  fireEvent.mouseDown(select.querySelector('.ant-select-clear')!)
  fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))
  await waitFor(() => expect(onReload).toHaveBeenCalledOnce())
  expect(update).toHaveBeenCalledWith('p1', expect.objectContaining({ technical_manager_id: null, version: 3 }))
  expect(select.querySelector('.ant-select-selection-item')).toBeNull()
  fireEvent.click(screen.getByText('其他资料：简称、时区与人员备注'))
  expect(screen.getByRole('combobox', { name: '现场时区' })).toHaveAttribute('aria-label', '现场时区')
  fireEvent.click(screen.getByText('项目首页'))
  await waitFor(() => expect(router.state.location.pathname).toBe('/overview'))
  expect(confirm).not.toHaveBeenCalled()
})

it('omits technical manager changes when a co-manager saves other project information', async () => {
  listActive.mockResolvedValue([{ id: 'tech', display_name: '正式技术负责人', role: 'worker' }])
  const onReload = vi.fn()
  show({ ...editableProject, manager: 'another-owner', is_co_manager: true, technical_manager: 'tech' }, onReload)
  expect(await screen.findByRole('combobox', { name: '技术负责人' })).toBeDisabled()
  fireEvent.change(screen.getByLabelText('说明'), { target: { value: '协管更新说明' } })
  fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))
  await waitFor(() => expect(onReload).toHaveBeenCalledOnce())
  expect(update).toHaveBeenCalledWith('p1', expect.objectContaining({ description: '协管更新说明' }))
  expect(update.mock.calls[0][1]).not.toHaveProperty('technical_manager_id')
})

it('keeps dirty information on a cancelled tab switch and restores saved values on explicit discard', async () => {
  const confirm = watchConfirm()
  show()
  fireEvent.change(await screen.findByLabelText('说明'), { target: { value: '未保存的同页探针' } })
  fireEvent.click(screen.getByRole('tab', { name: '项目协管' }))
  await waitFor(() => expect(confirm).toHaveBeenCalledOnce())
  expect(screen.getByRole('tab', { name: '基本信息' })).toHaveAttribute('aria-selected', 'true')
  act(() => confirm.mock.calls[0][0].onCancel?.())
  expect(screen.getByLabelText('说明')).toHaveValue('未保存的同页探针')
  fireEvent.click(screen.getByRole('tab', { name: '项目协管' }))
  await waitFor(() => expect(confirm).toHaveBeenCalledTimes(2))
  expect(confirm.mock.calls[1][0].okText).toBe('放弃修改并切换')
  act(() => confirm.mock.calls[1][0].onOk?.())
  expect(screen.getByRole('tab', { name: '项目协管' })).toHaveAttribute('aria-selected', 'true')
  fireEvent.click(screen.getByRole('tab', { name: '基本信息' }))
  expect(screen.getByLabelText('说明')).toHaveValue('原说明')
  fireEvent.click(screen.getByRole('tab', { name: '移交负责人' }))
  expect(screen.getByRole('tab', { name: '移交负责人' })).toHaveAttribute('aria-selected', 'true')
  expect(confirm).toHaveBeenCalledTimes(2)
  expect(update).not.toHaveBeenCalled()
})

it('router navigation supersedes a tab decision without letting its stale callback switch tabs', async () => {
  const confirm = watchConfirm()
  const router = show()
  fireEvent.change(await screen.findByLabelText('说明'), { target: { value: '仍在编辑' } })
  fireEvent.click(screen.getByRole('tab', { name: '项目协管' }))
  await waitFor(() => expect(confirm).toHaveBeenCalledOnce())
  const tabDecision = confirm.mock.calls[0][0]
  const tabDialog = confirm.mock.results[0].value
  await act(() => router.navigate('/overview'))
  await waitFor(() => expect(confirm).toHaveBeenCalledTimes(2))
  expect(tabDialog.destroy).toHaveBeenCalledOnce()
  expect(confirm.mock.calls[1][0].okText).toBe('放弃修改并离开')
  act(() => tabDecision.onOk?.())
  expect(screen.getByRole('tab', { name: '基本信息' })).toHaveAttribute('aria-selected', 'true')
  expect(screen.getByLabelText('说明')).toHaveValue('仍在编辑')
  act(() => confirm.mock.calls[1][0].onCancel?.())
  expect(router.state.location.pathname).toBe('/edit')
  expect(screen.getByLabelText('说明')).toHaveValue('仍在编辑')
})

it('failed persistence preserves the draft and its leave warning', async () => {
  update.mockRejectedValue(new Error('offline'))
  const confirm = watchConfirm()
  const onReload = vi.fn()
  const router = show(editableProject, onReload)
  fireEvent.change(await screen.findByLabelText('说明'), { target: { value: '保存失败仍保留' } })
  fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))
  expect(await screen.findByText('加载失败')).toBeInTheDocument()
  expect(screen.getByLabelText('说明')).toHaveValue('保存失败仍保留')
  expect(onReload).not.toHaveBeenCalled()
  fireEvent.click(screen.getByText('项目首页'))
  await waitFor(() => expect(confirm).toHaveBeenCalledOnce())
  expect(router.state.location.pathname).toBe('/edit')
})

it('reverting changes removes the unload warning and avoids a false leave prompt', async () => {
  const confirm = watchConfirm()
  const router = show()
  const description = await screen.findByLabelText('说明')
  fireEvent.change(description, { target: { value: '暂时修改' } })
  const dirtyUnload = new Event('beforeunload', { cancelable: true })
  window.dispatchEvent(dirtyUnload)
  expect(dirtyUnload.defaultPrevented).toBe(true)
  fireEvent.change(description, { target: { value: '原说明' } })
  const cleanUnload = new Event('beforeunload', { cancelable: true })
  window.dispatchEvent(cleanUnload)
  expect(cleanUnload.defaultPrevented).toBe(false)
  fireEvent.click(screen.getByText('项目首页'))
  await waitFor(() => expect(router.state.location.pathname).toBe('/overview'))
  expect(confirm).not.toHaveBeenCalled()
})

it('disables editing and duplicate submits until persistence completes and reloads saved data', async () => {
  let finish!: (value: unknown) => void
  update.mockReturnValue(new Promise(resolve => { finish = resolve }))
  const confirm = watchConfirm()
  function ReloadingPage() {
    const [project, setProject] = useState(editableProject)
    return <><Link to="/overview">项目首页</Link><EditPage project={project} onReload={() => setProject({ ...editableProject, version: 4, description: '第一次保存' })} /></>
  }
  const router = createMemoryRouter([{ path: '/edit', element: <ReloadingPage /> }, { path: '*', element: <div>其他页面</div> }], { initialEntries: ['/edit'] })
  render(<RouterProvider router={router} />)
  const description = await screen.findByLabelText('说明')
  fireEvent.change(description, { target: { value: '第一次保存' } })
  fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))
  await waitFor(() => expect(update).toHaveBeenCalledOnce())
  expect(description).toBeDisabled()
  expect(screen.getByLabelText('项目名称')).toBeDisabled()
  expect(screen.getByRole('combobox', { name: '技术负责人' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))
  expect(update).toHaveBeenCalledOnce()
  await act(async () => { finish({}) })
  expect(screen.getByLabelText('说明')).toHaveValue('第一次保存')
  expect(screen.getByLabelText('说明')).not.toBeDisabled()
  fireEvent.click(screen.getByText('项目首页'))
  await waitFor(() => expect(router.state.location.pathname).toBe('/overview'))
  expect(confirm).not.toHaveBeenCalled()
})

it('labels historical technical roles consistently and guards an unsubmitted co-manager selection', async () => {
  listActive.mockResolvedValue([{ id: 'tech', display_name: '历史技术员', role: 'technician' }])
  const confirm = watchConfirm()
  const router = show({ ...editableProject, co_managers: [{ user_id: 'old', display_name: '旧协管', role: 'legacy_role', expires_at: '2026-10-31', is_active: true }] })
  const manager = await screen.findByRole('combobox', { name: '技术负责人' })
  fireEvent.mouseDown(manager.closest('.ant-select')!.querySelector('.ant-select-selector')!)
  expect(await screen.findByText('历史技术员（技术工程师（旧））')).toBeInTheDocument()
  fireEvent.keyDown(manager, { key: 'Escape', keyCode: 27 })
  fireEvent.click(screen.getByRole('tab', { name: '项目协管' }))
  expect(await screen.findByText('legacy_role')).toBeInTheDocument()
  const coSelect = screen.getByText('选择实施/技术人员').closest('.ant-select')!
  fireEvent.mouseDown(coSelect.querySelector('.ant-select-selector')!)
  const options = await screen.findAllByText('历史技术员（技术工程师（旧））')
  fireEvent.click(options[options.length - 1])
  fireEvent.click(screen.getByText('项目首页'))
  await waitFor(() => expect(confirm).toHaveBeenCalledOnce())
  expect(router.state.location.pathname).toBe('/edit')
  expect(update).not.toHaveBeenCalled()
})

it('cancels a dirty co-manager tab switch or explicitly discards its unsubmitted selection', async () => {
  listActive.mockResolvedValue([{ id: 'tech', display_name: '现场协管', role: 'worker' }])
  const confirm = watchConfirm()
  show()
  fireEvent.click(screen.getByRole('tab', { name: '项目协管' }))
  const coSelect = (await screen.findByText('选择实施/技术人员')).closest('.ant-select')!
  fireEvent.mouseDown(coSelect.querySelector('.ant-select-selector')!)
  fireEvent.click(await screen.findByText('现场协管（实施工程师）'))
  fireEvent.click(screen.getByRole('tab', { name: '基本信息' }))
  await waitFor(() => expect(confirm).toHaveBeenCalledOnce())
  act(() => confirm.mock.calls[0][0].onCancel?.())
  expect(screen.getByRole('tab', { name: '项目协管' })).toHaveAttribute('aria-selected', 'true')
  expect(coSelect).toHaveTextContent('现场协管（实施工程师）')
  fireEvent.click(screen.getByRole('tab', { name: '基本信息' }))
  await waitFor(() => expect(confirm).toHaveBeenCalledTimes(2))
  act(() => confirm.mock.calls[1][0].onOk?.())
  expect(screen.getByRole('tab', { name: '基本信息' })).toHaveAttribute('aria-selected', 'true')
  fireEvent.click(screen.getByRole('tab', { name: '项目协管' }))
  expect(await screen.findByText('选择实施/技术人员')).toBeInTheDocument()
  expect(confirm).toHaveBeenCalledTimes(2)
  expect(update).not.toHaveBeenCalled()
})
