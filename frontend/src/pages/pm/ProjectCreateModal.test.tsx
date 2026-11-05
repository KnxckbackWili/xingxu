import { beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import dayjs from 'dayjs'
import ProjectCreateModal from './ProjectCreateModal'
import { api } from '../../api/client'
import { projectApi } from '../../api'

const navigate = vi.hoisted(() => vi.fn())
vi.mock('react-router-dom', () => ({ useNavigate: () => navigate }))
vi.mock('../../api', () => ({ projectApi: { create: vi.fn() } }))
vi.mock('../../api/client', () => ({ api: { get: vi.fn() }, errMsg: (error: any) => error?.message ?? 'error' }))

const templates = [{ id: 'preset', name: '叉车模板', is_system: false }, { id: 'default', name: '系统默认模板', is_system: true }]
const row = (id: string, name: string, extra: Record<string, unknown> = {}) => ({ id, name, kind: 'work', optional: false, files: [], checks: [], ...extra })
const content = (items: ReturnType<typeof row>[]) => ({ data: { sections: [{ id: 's', title: '实施', stage_key: '6', items }] } })
const work = (prefix: string, count: number) => content(Array.from({ length: count }, (_, i) => row(`${prefix}-${i}`, `工作${i}`)))
const ready = (count: number) => `将带入 ${count} 项工作 · 0 份文件 · 0 项采购，进项目后可增删`

function show(initialTemplate?: string) {
  const onClose = vi.fn()
  render(<ConfigProvider theme={{ token: { motion: false } }}><ProjectCreateModal open initialTemplate={initialTemplate} onClose={onClose} /></ConfigProvider>)
  return onClose
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.get).mockImplementation(async (url: string) => url === '/templates' ? { data: templates } : url === '/templates/preset/items' ? work('p', 2) : work('d', 3))
  vi.mocked(projectApi.create).mockResolvedValue({ id: 'new-project', initial_generation: { tasks: 3 } } as any)
})

it('creates from one screen with a default period and every work item of the system template', async () => {
  const onClose = show()
  expect(await screen.findByText(ready(3))).toBeInTheDocument()
  expect(screen.queryByLabelText('客户')).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('项目名称'), { target: { value: '  快速项目  ' } })
  fireEvent.click(screen.getByRole('button', { name: '创建并进入项目' }))
  await waitFor(() => expect(projectApi.create).toHaveBeenCalledTimes(1))
  const body = vi.mocked(projectApi.create).mock.calls[0][0] as any
  expect(body).toMatchObject({ name: '快速项目', status: 'preparing', template_id: 'default', optional_item_ids: [],
    start_date: dayjs().format('YYYY-MM-DD'), end_date: dayjs().add(3, 'month').subtract(1, 'day').format('YYYY-MM-DD') })
  expect(body.client_uuid).toEqual(expect.any(String))
  await waitFor(() => expect(navigate).toHaveBeenCalledWith('/pm/projects/new-project/overview'))
  expect(onClose).toHaveBeenCalled()
})

it('requires a name and sends nothing until it is given', async () => {
  show()
  await screen.findByText(ready(3))
  fireEvent.click(screen.getByRole('button', { name: '创建并进入项目' }))
  expect(await screen.findByText('请输入项目名称')).toBeVisible()
  expect(projectApi.create).not.toHaveBeenCalled()
})

it('honours a template chosen from the template page', async () => {
  show('preset')
  expect(await screen.findByText(ready(2))).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('项目名称'), { target: { value: '模板项目' } })
  fireEvent.click(screen.getByRole('button', { name: '创建并进入项目' }))
  await waitFor(() => expect(projectApi.create).toHaveBeenCalledWith(expect.objectContaining({ template_id: 'preset', optional_item_ids: [] })))
})

it('blocks creation when the template cannot be read and retries on request', async () => {
  let fail = true
  vi.mocked(api.get).mockImplementation(async (url: string) => {
    if (url === '/templates') return { data: templates }
    if (fail) throw new Error('模板服务暂不可用')
    return work('d', 3)
  })
  show()
  expect(await screen.findByText('模板读取失败，暂不能创建')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '创建并进入项目' })).toBeDisabled()
  fail = false
  fireEvent.click(screen.getByRole('button', { name: '重 试' }))
  expect(await screen.findByText(ready(3))).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '创建并进入项目' })).toBeEnabled()
})

it('a double click creates one project with one idempotency key', async () => {
  let finish: (value: any) => void = () => {}
  vi.mocked(projectApi.create).mockImplementation(() => new Promise(resolve => { finish = resolve }))
  show()
  await screen.findByText(ready(3))
  fireEvent.change(screen.getByLabelText('项目名称'), { target: { value: '只建一次' } })
  const button = screen.getByRole('button', { name: '创建并进入项目' })
  fireEvent.click(button); fireEvent.click(button)
  await waitFor(() => expect(projectApi.create).toHaveBeenCalledTimes(1))
  finish({ id: 'once', initial_generation: { tasks: 3 } })
  await waitFor(() => expect(navigate).toHaveBeenCalledWith('/pm/projects/once/overview'))
})

it('lists optional rows unticked; only the ones ticked come in', async () => {
  vi.mocked(api.get).mockImplementation(async (url: string) => url === '/templates' ? { data: [templates[1]] } : content([
    row('core', '系统联调'), row('lift', '电梯对接', { optional: true, files: [{ id: 'f', code: '6.20', name: '电梯协议' }] }),
    row('spare', '备件', { kind: 'purchase', optional: true })]))
  show()
  expect(await screen.findByText(ready(1))).toBeInTheDocument()
  expect(document.querySelector('[aria-label="工作模板"]')?.closest('.ant-form-item')).toHaveClass('ant-form-item-hidden')
  expect(screen.queryByRole('checkbox', { name: '系统联调' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('checkbox', { name: '电梯对接' }))
  fireEvent.click(screen.getByRole('checkbox', { name: '备件' }))
  expect(screen.getByText('将带入 2 项工作 · 1 份文件 · 1 项采购，进项目后可增删')).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('项目名称'), { target: { value: '有电梯项目' } })
  fireEvent.click(screen.getByRole('button', { name: '创建并进入项目' }))
  await waitFor(() => expect(projectApi.create).toHaveBeenCalledTimes(1))
  expect((vi.mocked(projectApi.create).mock.calls[0][0] as any).optional_item_ids).toEqual(['lift', 'spare'])
}, 15000)

it('choosing a vehicle type switches to that type\'s own template', async () => {
  vi.mocked(api.get).mockImplementation(async (url: string) => url === '/templates' ? { data: [{ ...templates[0], vehicle_type: '叉车式' }, templates[1]] } : url === '/templates/preset/items' ? work('p', 2) : work('d', 3))
  show()
  expect(await screen.findByText(ready(3))).toBeInTheDocument()
  fireEvent.mouseDown(screen.getByRole('combobox', { name: '车型' }))
  fireEvent.click(await screen.findByText(/^叉车式/, { selector: '.ant-select-item-option-content' }))
  expect(await screen.findByText(ready(2))).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('项目名称'), { target: { value: '叉车项目' } })
  fireEvent.click(screen.getByRole('button', { name: '创建并进入项目' }))
  await waitFor(() => expect(projectApi.create).toHaveBeenCalledWith(expect.objectContaining({ template_id: 'preset', optional_item_ids: [] })))
})
