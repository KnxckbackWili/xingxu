import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import ProjectJsonImport from './ProjectJsonImport'
import { api } from '../api/client'
const h = vi.hoisted(() => ({ navigate: vi.fn(), user: { id: 'pm', role: 'pm', permission_version: 0, permission_overrides: {} } as any }))
const { navigate } = h
vi.mock('react-router-dom', () => ({ useNavigate: () => navigate }))
vi.mock('../stores/auth', () => ({ useAuth: () => ({ user: h.user }) }))
vi.mock('../api/client', () => ({ api: { get: vi.fn(), post: vi.fn() }, errMsg: () => 'error' }))
describe('quick-import draft preflight', () => {
  const original = { type: 'agvpm-project', project: { name: '现场项目', status: 'executing' }, modules: [{ tasks: [{ name: '路线测绘', target_quantity: 30, unit: '米' }] }] }
  const invalid = { valid: false, summary: { project: '现场项目' }, errors: ['不能直接实施'] }
  const valid = { valid: true, summary: { project: '现场项目' }, warnings: ['交付证据需重新提交'] }
  beforeEach(() => {
    vi.clearAllMocks()
    h.user = { id: 'pm', role: 'pm', permission_version: 0, permission_overrides: {} }
    vi.mocked(api.post).mockReset()
    vi.mocked(api.get).mockResolvedValue({ data: [] })
  })
  const setup = () => render(<ConfigProvider theme={{ token: { motion: false } }}><ProjectJsonImport projectId="p1" /></ConfigProvider>)
  it('reports malformed JSON as a format error and never contacts the import API', async () => {
    const { container } = setup()
    const file = new File(['broken'], 'invalid-project.json', { type: 'application/json' })
    Object.defineProperty(file, 'text', { value: async () => '{"project": invalid}' })
    fireEvent.change(container.querySelector('input[type=file]')!, { target: { files: [file] } })
    expect(await screen.findByText('文件不是有效的 JSON，请检查备份格式；原预检内容已保留')).toBeVisible()
    expect(api.post).not.toHaveBeenCalled()
    expect(screen.queryByText('JSON 导入预检')).not.toBeInTheDocument()
  })
  async function choose(container: HTMLElement, payload: unknown = original) {
    const file = new File(['fixture'], 'project.json', { type: 'application/json' })
    Object.defineProperty(file, 'text', { value: async () => JSON.stringify(payload) })
    fireEvent.change(container.querySelector('input[type=file]')!, { target: { files: [file] } })
    await waitFor(() => expect(screen.getByText('JSON 导入预检')).toBeVisible())
  }
  it('explicitly revalidates a draft copy and prevents duplicate creation', async () => {
    let finishCreate: (value: unknown) => void = () => {}
    vi.mocked(api.post).mockResolvedValueOnce({ data: invalid }).mockResolvedValueOnce({ data: valid })
      .mockImplementationOnce(() => new Promise(resolve => { finishCreate = resolve }))
    const { container } = setup()
    await choose(container)
    expect(await screen.findByText('源项目状态：现场实施')).toBeVisible()
    const draftButton = screen.getByRole('button', { name: '按筹备重新预检' })
    fireEvent.click(draftButton); fireEvent.click(draftButton)
    await screen.findByText('新项目将从筹备开始')
    const draft = { ...original, project: { ...original.project, status: 'preparing' } }
    expect(api.post).toHaveBeenNthCalledWith(1, '/projects/import/preview', original)
    expect(api.post).toHaveBeenNthCalledWith(2, '/projects/import/preview', draft)
    expect(original.project.status).toBe('executing')
    const confirm = screen.getByRole('button', { name: '确认创建项目' })
    fireEvent.click(confirm); fireEvent.click(confirm)
    expect(api.post).toHaveBeenCalledTimes(3)
    expect(api.post).toHaveBeenLastCalledWith('/projects/import/json', draft)
    await act(async () => { finishCreate({ data: { id: 'copy', message: '创建成功' } }) })
    expect(navigate).toHaveBeenCalledOnce()
    expect(navigate).toHaveBeenCalledWith('/pm/projects/copy')
  })
  it('allows an unknown historical state to be copied as draft without guessing its original meaning', async () => {
    const historical = { ...original, project: { ...original.project, status: 'legacy-live' } }
    vi.mocked(api.post).mockResolvedValueOnce({ data: invalid }).mockResolvedValueOnce({ data: valid })
    const { container } = setup()
    await choose(container, historical)
    expect(await screen.findByText('源项目状态：未知历史状态（legacy-live）')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: '按筹备重新预检' }))
    await screen.findByText('新项目将从筹备开始')
    expect(api.post).toHaveBeenLastCalledWith('/projects/import/preview', { ...historical, project: { ...historical.project, status: 'preparing' } })
    expect(historical.project.status).toBe('legacy-live')
  })
  it('retains the original preflight after a failed request and permits retry', async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ data: invalid }).mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ data: valid })
    const { container } = setup()
    await choose(container)
    fireEvent.click(await screen.findByRole('button', { name: '按筹备重新预检' }))
    expect(await screen.findByText('筹备预检未通过，原预检内容已保留')).toBeVisible()
    expect(screen.getByText('不能直接实施')).toBeVisible()
    expect(screen.getByText('源项目状态：现场实施')).toBeVisible()
    expect(screen.getByRole('button', { name: '确认创建项目' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '按筹备重新预检' }))
    await screen.findByText('新项目将从筹备开始')
    expect(screen.getByRole('button', { name: '确认创建项目' })).toBeEnabled()
  })
  it('keeps backend validation errors blocking import even after requesting draft status', async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ data: invalid })
      .mockResolvedValueOnce({ data: { valid: false, errors: ['任务引用不存在'] } })
    const { container } = setup()
    await choose(container)
    fireEvent.click(await screen.findByRole('button', { name: '按筹备重新预检' }))
    expect(await screen.findByText('任务引用不存在')).toBeVisible()
    expect(screen.getByText('不能直接实施')).toBeVisible()
    expect(screen.queryByText('新项目将从筹备开始')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '确认创建项目' })).toBeDisabled()
    expect(api.post).toHaveBeenCalledTimes(2)
  })
  it('cancelling an in-flight conversion ignores its late response and does not reopen or create', async () => {
    let finish: (value: unknown) => void = () => {}
    vi.mocked(api.post).mockResolvedValueOnce({ data: invalid })
      .mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const { container } = setup()
    await choose(container)
    fireEvent.click(await screen.findByRole('button', { name: '按筹备重新预检' }))
    fireEvent.click(screen.getByRole('button', { name: /取.*消/ }))
    await act(async () => { finish({ data: valid }) })
    expect(screen.queryByText('新项目将从筹备开始')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '确认创建项目' })).not.toBeInTheDocument()
    expect(api.post).toHaveBeenCalledTimes(2)
    expect(navigate).not.toHaveBeenCalled()
  })
  it('ignores an old conversion after cancellation and choosing a newer file', async () => {
    let finishOld: (value: unknown) => void = () => {}
    vi.mocked(api.post).mockResolvedValueOnce({ data: invalid })
      .mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve }))
      .mockResolvedValueOnce({ data: { valid: true, summary: { project: '最新文件' } } })
    const { container } = setup()
    await choose(container)
    fireEvent.click(screen.getByRole('button', { name: '按筹备重新预检' }))
    fireEvent.click(screen.getByRole('button', { name: /取.*消/ }))
    await choose(container, { ...original, project: { name: '最新文件', status: 'preparing' } })
    expect(await screen.findByText('最新文件')).toBeVisible()
    await act(async () => { finishOld({ data: valid }) })
    expect(screen.getByText('最新文件')).toBeVisible()
    expect(screen.queryByText('现场项目')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '按筹备重新预检' })).not.toBeInTheDocument()
  })
  it('hides import when its system permission is explicitly denied', () => {
    h.user = { ...h.user, permission_overrides: { 'system.import.create': false } }
    setup()
    expect(screen.queryByRole('button', { name: '导入 JSON 新建项目' })).toBeNull()
    expect(api.post).not.toHaveBeenCalled()
  })
  it('discards a preview immediately after permission revocation', async () => {
    vi.mocked(api.post).mockResolvedValueOnce({data: valid})
    const page=setup();await choose(page.container)
    h.user={...h.user,permission_version:1,permission_overrides:{'system.import.create':false}}
    page.rerender(<ProjectJsonImport projectId="p1" />)
    expect(screen.queryByRole('button',{name:'确认创建项目'})).toBeNull()
    expect(screen.queryByText('现场项目')).toBeNull()
    expect(api.post).toHaveBeenCalledTimes(1)
  })
  it('ignores a late preflight response after switching project', async () => {
    let finish!:(value:any)=>void
    vi.mocked(api.post).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve}))
    const page=setup()
    const file=new File(['fixture'],'project.json');Object.defineProperty(file,'text',{value:async()=>JSON.stringify(original)})
    fireEvent.change(page.container.querySelector('input[type=file]')!,{target:{files:[file]}})
    await waitFor(()=>expect(api.post).toHaveBeenCalledOnce())
    page.rerender(<ProjectJsonImport projectId="p2" />)
    await act(async()=>finish({data:valid}))
    expect(screen.queryByRole('button',{name:'确认创建项目'})).toBeNull()
    expect(navigate).not.toHaveBeenCalled()
  })

})

