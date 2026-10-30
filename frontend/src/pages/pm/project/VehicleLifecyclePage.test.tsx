vi.mock('../../../components/VehicleDocumentsPanel', () => ({ default: ({ unitId }: { unitId: string }) => <div>资料面板 {unitId}</div> }))
vi.mock('../../../components/VehicleProgressMatrix', () => ({ default: () => <div>车辆进度表由专门测试覆盖</div> }))
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

vi.mock('react-router-dom', () => ({
  useLocation: () => ({ search: '' }),
}))

const apiGet = vi.fn()
const apiPost = vi.fn()
vi.mock('../../../api/client', () => ({
  api: {
    get: (...args: unknown[]) => apiGet(...args),
    post: (...args: unknown[]) => apiPost(...args),
    put: vi.fn(),
    delete: vi.fn(),
  },
  errMsg: () => 'mock-error',
}))

import { useAuth } from '../../../stores/auth'
import VehicleLifecyclePage from './VehicleLifecyclePage'

const PROJECT = {
  id: 'p1',
  name: '测试项目',
  manager: 'u-pm',
  technical_manager: 'u-pm',
  members: ['u-pm'],
  is_co_manager: false,
  status: 'executing',
}

/** 字典加载失败：历史车型「老式叉车」仍在项目车辆表中，字典接口 500。 */
function installDictFail() {
  apiGet.mockImplementation((url: string) => {
    if (url === '/vehicle-types') return Promise.reject({ response: { data: { detail: '字典服务不可用' } } })
    if (url === '/projects/p1/vehicle-units') return Promise.resolve({ data: [] })
    if (url === '/projects/p1/vehicles') {
      return Promise.resolve({ data: [{ id: 'v1', vehicle_type: '老式叉车', model_name: 'L1', quantity: 2, configuration: {} }] })
    }
    return Promise.resolve({ data: {} })
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  useAuth.setState({ user: { id: 'u-worker', role: 'worker', username: 'worker1', display_name: '现场1' } as any })
})

it('unknown legacy project allows historical vehicle reading and export while admin writes remain hidden', async () => {
  useAuth.setState({ user: { id: 'u-pm', role: 'admin', username: 'admin', display_name: '管理员' } as any })
  const unit = { id: 'unit-1', asset_code: 'AGV-001', current_status: 'attention', events: [
    { id: 'event-1', title: '历史故障原始记录', event_type: 'fault', event_date: '2026-09-30', operator_id: 'u-pm', is_closed: false },
  ] }
  apiGet.mockImplementation((url: string) => Promise.resolve({ data: url.endsWith('/vehicle-units/unit-1') ? unit : url.endsWith('/vehicle-units') ? [unit] : [] }))
  render(<VehicleLifecyclePage project={{ ...PROJECT, status: 'legacy_unknown', capabilities: ['project.update', 'project.manage_plan', 'project.manage_issues', 'project.manage_schedule', 'project.export'] } as any} />)
  fireEvent.click(await screen.findByRole('button', { name: /车辆记录/ }))
  expect(await screen.findByText('历史故障原始记录')).toBeInTheDocument()
  expect(screen.getByText('资料面板 unit-1')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '导入与导出' }))
  expect(await screen.findByRole('button', { name: /导出车辆表/ })).toBeInTheDocument()
  for (const name of ['添加车型', '添加现场车辆', '记录问题', '安排维修', '补充.*编辑']) expect(screen.queryByRole('button', { name: new RegExp(name) })).toBeNull()
})

/**
 * HYPE-65 现场信息页字典错误反馈回归：
 * VehicleLifecyclePage 必须消费 useVehicleTypes() 的 error/reload——
 * 字典加载失败时在「车型 / 数量配置」区显示错误提示与重试按钮，
 * 且历史车型保持显示，不得静默清空。
 */
describe('VehicleLifecyclePage 车型字典错误反馈', () => {
  it('字典加载失败：显示错误提示与重试按钮，历史车型仍显示', async () => {
    installDictFail()
    render(<VehicleLifecyclePage project={PROJECT as any} configurationOnly />)

    // 历史车型（字典外/已停用）仍显示在配置表中，不被静默清空
    expect(await screen.findByText('老式叉车')).toBeInTheDocument()
    expect(screen.getByText('L1')).toBeInTheDocument()
    expect(screen.getByText('2 台')).toBeInTheDocument()

    // 配置区出现清楚错误提示 + 重试按钮（AntD 会在两个汉字间自动插入空格）
    expect(screen.getByText('车型字典加载失败')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /重\s*试/ })).toBeInTheDocument()
  })

  it('点击重试重新加载字典并清除错误', async () => {
    let dictFails = true
    apiGet.mockImplementation((url: string) => {
      if (url === '/vehicle-types') {
        if (dictFails) {
          dictFails = false
          return Promise.reject({ response: { data: { detail: '字典服务不可用' } } })
        }
        return Promise.resolve({ data: [{ id: 't1', name: '潜伏式', is_enabled: true, sort_order: 1 }] })
      }
      if (url === '/projects/p1/vehicle-units') return Promise.resolve({ data: [] })
      if (url === '/projects/p1/vehicles') return Promise.resolve({ data: [] })
      return Promise.resolve({ data: {} })
    })

    render(<VehicleLifecyclePage project={PROJECT as any} configurationOnly />)
    expect(await screen.findByText('车型字典加载失败')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /重\s*试/ }))

    await waitFor(() => expect(screen.queryByText('车型字典加载失败')).not.toBeInTheDocument())
    // 重试成功后可正常请求字典
    expect(apiGet).toHaveBeenCalledWith('/vehicle-types')
  })
})


describe('VehicleLifecyclePage partial batch recovery', () => {
  it('shows confirmed vehicles and refreshes after partial failure without replaying the batch', async () => {
    useAuth.setState({ user: { id: 'u-pm', role: 'admin', username: 'admin', display_name: '管理员' } as any })
    const saved: any[] = []
    apiGet.mockImplementation((url: string) => Promise.resolve({ data:
      url.endsWith('/vehicle-units') ? [...saved] : [] }))
    apiPost.mockImplementation(async (_url: string, payload: any) => {
      if (payload.asset_code === 'AGV-002') throw new Error('conflict')
      const item = { id: 'unit-1', asset_code: payload.asset_code, current_status: 'normal', open_issue_count: 0 }
      saved.push(item)
      return { data: item }
    })
    render(<VehicleLifecyclePage project={PROJECT as any} />)
    fireEvent.click(await screen.findByRole('button', { name: /添加车辆/ }))
    fireEvent.change(screen.getByLabelText('起始编号'), { target: { value: 'AGV-001' } })
    fireEvent.change(screen.getByRole('spinbutton', { name: '数量' }), { target: { value: '3' } })
    fireEvent.click(screen.getByRole('button', { name: '建立档案' }))
    expect(await screen.findByText('车辆批量建档已停止，请核对台账后补录')).toBeInTheDocument()
    expect(screen.getByText('已确认建档 1 台：AGV-001')).toBeInTheDocument()
    expect(screen.getByText(/未确认建档：AGV-002.*后续 1 台未提交/)).toBeInTheDocument()
    expect(apiPost).toHaveBeenCalledTimes(2)
    expect(await screen.findByText('AGV-001')).toBeInTheDocument()
    expect(apiGet.mock.calls.filter(([url]) => url === '/projects/p1/vehicle-units').length).toBeGreaterThanOrEqual(2)
    fireEvent.click(screen.getByRole('button', { name: /添加车辆/ }))
    expect(screen.getByLabelText('起始编号')).toHaveValue('')
    expect(apiPost).toHaveBeenCalledTimes(2)
  })

  it('makes historical event location explicitly read-only', async () => {
    useAuth.setState({ user: { id: 'u-pm', role: 'admin', username: 'admin', display_name: '管理员' } as any })
    const unit = { id: 'unit-1', asset_code: 'AGV-001', current_status: 'attention', events: [
      { id: 'event-1', title: '故障记录', event_type: 'fault', event_date: '2026-09-30', location_after: '旧位置', is_closed: false },
    ] }
    apiGet.mockImplementation((url: string) => Promise.resolve({ data:
      url.endsWith('/vehicle-units/unit-1') ? unit : url.endsWith('/vehicle-units') ? [unit] : [] }))
    render(<VehicleLifecyclePage project={PROJECT as any} />)
    fireEvent.click(await screen.findByRole('button', { name: /车辆记录/ }))
    fireEvent.click(await screen.findByRole('button', { name: /补充.*编辑/ }))
    expect(screen.getByLabelText('车辆当前现场位置')).toBeDisabled()
    expect(screen.getByText('历史记录的位置不可修改；当前位置可在车辆清单中单独更新。')).toBeInTheDocument()
  })
})
it('prevents rapid duplicate vehicle-event creation and keeps the dialog open while saving', async () => {
  useAuth.setState({ user: { id: 'u-pm', role: 'admin', username: 'admin', display_name: '管理员' } as any })
  const unit = { id: 'unit-1', asset_code: 'AGV-001', current_status: 'normal', events: [] }
  apiGet.mockImplementation((url: string) => Promise.resolve({ data: url.endsWith('/vehicle-units/unit-1') ? unit : url.endsWith('/vehicle-units') ? [unit] : [] }))
  apiPost.mockReturnValue(new Promise(() => {}))
  render(<VehicleLifecyclePage project={PROJECT as any} />)
  fireEvent.click(await screen.findByRole('button', { name: /车辆记录/ }))
  fireEvent.click(await screen.findByRole('button', { name: /记录问题/ }))
  fireEvent.change(screen.getByLabelText('问题标题'), { target: { value: '避障传感器报警' } })
  const save = screen.getByRole('button', { name: '保存记录' })
  fireEvent.click(save); fireEvent.click(save)
  await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1))
  expect(apiPost).toHaveBeenCalledWith('/projects/p1/vehicle-units/unit-1/events', expect.objectContaining({ title: '避障传感器报警' }))
  expect(screen.getByLabelText('问题标题')).toBeInTheDocument()
})
