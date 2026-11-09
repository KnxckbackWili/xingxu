import { setOfflineAccount } from '../../offline/queue'
import { beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render as rtlRender, screen, waitFor, within } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import type { ReactElement } from 'react'
import TemplateEditorPage from './TemplateEditorPage'

const { get, put, post, del, auth } = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), post: vi.fn(), del: vi.fn(), auth: { user: { id: 'admin', role: 'admin' } as any } }))
vi.mock('../../api/client', () => ({ api: { get, put, post, delete: del }, errMsg: (e: any) => e?.message ?? '保存失败' }))
vi.mock('../../stores/auth', () => ({ useAuth: () => auth }))
vi.mock('../../hooks/useVehicleTypes', () => ({ useVehicleTypes: () => ({ options: [] }), toVehicleTypeSelectOptions: (_: unknown, extra: string[] = []) => extra.map(name => ({ label: name, value: name })) }))

const file = { id: 'f1', code: '6.1', name: '车辆到场点检表', template_no: '', required: true, scope: 'vehicle', platform: null, timing_type: 'on_demand', timing_event: null,
  timing_offset_hours: null, timing_weekday: null, trigger_type: null, confidential_default: false, external_visible_default: false, external_never_visible: false, note: '', blank_file: null }
const item = (id: string, name: string, extra: Record<string, unknown> = {}) => ({ id, section_id: 's1', kind: 'work', name, note: '', optional: false, per_vehicle: false, step_key: null,
  checks: [], files: [], quantity: null, unit: '', spec: '', reference_docs: [], version: 3, sort_order: 0, ...extra })
const content = () => ({ template_id: 'default', stages: [], sections: [
  { id: 's1', title: '到货与单车调试', stage_key: '6', stage_name: '实施', sort_order: 0, items: [
    item('w1', '到场点检', { per_vehicle: true, step_key: 'arrival', checks: [{ id: 'c1', name: '外观无损伤', required: true, safety: false }], files: [file] }),
    item('p1', 'AGV 本体', { kind: 'purchase', unit: '台', spec: '按合同' })] },
  { id: 's2', title: '培训与验收', stage_key: '7', stage_name: '验收', sort_order: 1, items: [item('w2', '最终验收', { section_id: 's2', optional: true })] }] })

const render = (ui: ReactElement) => rtlRender(ui, { wrapper: ({ children }) => <ConfigProvider theme={{ token: { motion: false } }}><MemoryRouter initialEntries={['/pm/templates/default']}><Routes><Route path="/pm/templates/:templateId" element={children} /></Routes></MemoryRouter></ConfigProvider> })

beforeEach(() => {
  setOfflineAccount('admin')
  auth.user = { id: 'admin', role: 'admin' }
  get.mockReset().mockImplementation(async (url: string) => ({ data: url === '/templates' ? [{ id: 'default', name: '通用模板', is_system: true }] : content() }))
  put.mockReset().mockImplementation(async () => ({ data: content() }))
  post.mockReset().mockImplementation(async () => ({ data: { ...content(), id: 'new' } }))
  del.mockReset()
})

it('shows titled sections with one row per thing and what each row hands in', async () => {
  render(<TemplateEditorPage />)
  const section = await screen.findByRole('region', { name: '段落：到货与单车调试' })
  const check = within(section).getByRole('button', { name: /到场点检/ })
  expect(check).toHaveTextContent('工作'); expect(check).toHaveTextContent('每台车'); expect(check).toHaveTextContent('1 项检查'); expect(check).toHaveTextContent('交 1 份')
  expect(within(section).getByRole('button', { name: /AGV 本体/ })).toHaveTextContent('采购')
  expect(screen.getByRole('button', { name: /最终验收/ })).toHaveTextContent('可选')
  expect(screen.getByText('2 项工作 · 0 组资料 · 1 项采购 · 共 1 份文件')).toBeInTheDocument()
  expect(screen.getAllByLabelText('段落「培训与验收」所属阶段').length).toBeGreaterThan(0)
})

it('a row edited in the panel saves itself with the version it was read at', async () => {
  render(<TemplateEditorPage />)
  fireEvent.click(await screen.findByRole('button', { name: /到场点检/ }))
  const side = await screen.findByRole('complementary', { name: '编辑：到场点检' })
  fireEvent.change(within(side).getByLabelText('名称'), { target: { value: '到场开箱点检' } })
  await waitFor(() => expect(put).toHaveBeenCalledTimes(1), { timeout: 2000 })
  const [url, body] = put.mock.calls[0]
  expect(url).toBe('/templates/default/items/w1')
  expect(body).toMatchObject({ name: '到场开箱点检', kind: 'work', per_vehicle: true, version: 3, section_id: 's1',
    checks: [{ id: 'c1', name: '外观无损伤', required: true, safety: false, description: '' }] })
  expect(body.files[0]).toMatchObject({ id: 'f1', code: '6.1', scope: 'vehicle' })
  expect(body.files[0]).not.toHaveProperty('blank_file')
  expect(await within(side).findByText('已保存')).toBeInTheDocument()
})

it('adds a purchase to a section by name', async () => {
  render(<TemplateEditorPage />)
  const section = await screen.findByRole('region', { name: '段落：培训与验收' })
  fireEvent.click(within(section).getByRole('button', { name: /加一件事/ }))
  fireEvent.click(await screen.findByText('加采购'))
  const input = await screen.findByLabelText('新采购名称')
  fireEvent.change(input, { target: { value: '验收礼品' } }); fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' })
  await waitFor(() => expect(post).toHaveBeenCalledWith('/templates/default/items', expect.objectContaining({ section_id: 's2', kind: 'purchase', name: '验收礼品', unit: '台' })))
})

it('renames a section in place', async () => {
  render(<TemplateEditorPage />)
  const title = (await screen.findAllByLabelText('段落标题'))[1]
  fireEvent.change(title, { target: { value: '客户培训' } }); fireEvent.blur(title)
  await waitFor(() => expect(put).toHaveBeenCalledWith('/templates/default/sections/s2', { title: '客户培训' }))
})

it('a failed load is shown and can be retried', async () => {
  get.mockRejectedValueOnce(new Error('模板读取失败'))
  render(<TemplateEditorPage />)
  expect(await screen.findByText('模板读取失败')).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: /刷新模板/ }))
  expect(await screen.findByRole('button', { name: /到场点检/ })).toBeVisible()
})

