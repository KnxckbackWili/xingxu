import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConfigProvider, message } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import InventoryPage from './InventoryPage'
import { api } from '../../../api/client'

const apiGet = vi.fn()
const apiPost = vi.fn()
let mobile = false
vi.mock('../../../hooks/useMediaQuery', () => ({ useMediaQuery: () => mobile }))
vi.mock('../../../api/client', () => ({
  api: {
    get: (...args: unknown[]) => apiGet(...args),
    post: (...args: unknown[]) => apiPost(...args),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
  errMsg: () => '服务器内部错误，请稍后重试',
  tokenStore: { access: 'test-token' },
}))

const renderPage = () => render(
  <ConfigProvider locale={zhCN}>
    <InventoryPage projectId="p1" canManage />
  </ConfigProvider>,
)

let errorSpy: ReturnType<typeof vi.spyOn>
let successSpy: ReturnType<typeof vi.spyOn>
beforeEach(() => {
  vi.clearAllMocks()
  mobile = false
  apiGet.mockImplementation((url: string) => {
    if (url.includes('/item-applications')) return Promise.resolve({ data: [] })
    if (url.includes('/inventory')) return Promise.resolve({ data: { items: [], summary: {}, total: 0 } })
    return Promise.resolve({ data: [] })
  })
  errorSpy = vi.spyOn(message, 'error').mockReturnValue({} as any)
  successSpy = vi.spyOn(message, 'success').mockReturnValue({} as any)
})

afterEach(() => {
  errorSpy?.mockRestore()
  successSpy?.mockRestore()
})

it('hides the mobile empty-list pager and keeps navigation available when items load', async () => {
  mobile = true
  renderPage()
  await screen.findByText('没有符合条件的物品')
  expect(screen.queryByTitle('上一页')).not.toBeInTheDocument()
  expect(screen.queryByTitle('下一页')).not.toBeInTheDocument()

  apiGet.mockImplementation(async (url: string) => ({ data: url.endsWith('/item-applications') ? [] : {
    items: [{ id: 'item1', name: '现场网线', quantity: 1, unit: '根' }], summary: {}, total: 51,
  } }))
  fireEvent.click(screen.getByRole('button', { name: /刷\s*新/ }))
  await screen.findByText('现场网线')
  const next = screen.getByTitle('下一页')
  fireEvent.click(next)
  await waitFor(() => expect(apiGet).toHaveBeenCalledWith('/projects/p1/inventory', expect.objectContaining({
    params: expect.objectContaining({ page: 2, page_size: 50 }),
  })))
})

describe('InventoryPage 物品申请表单确认', () => {
  it('快速双击「确定」只提交一次，提交失败也只弹一次 500 提示', async () => {
    // 后端返回 500（复现截图中的服务端错误场景）
    apiPost.mockRejectedValue({
      response: { status: 500, data: { detail: 'boom' } },
      config: { url: '/projects/p1/item-applications' },
    })

    renderPage()
    fireEvent.click(screen.getByRole('tab', { name: /^申请/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: /新建申请/ })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /新建申请/ }))

    const title = await screen.findByLabelText('申请事项')
    await userEvent.type(title, '更换三支点螺栓需要吊车')

    const ok = screen.getByRole('button', { name: /确\s*定/ })
    // 第一次点击后立刻第二次点击：若缺少重入保护，会发出两个并发 POST
    fireEvent.click(ok)
    fireEvent.click(ok)

    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(errorSpy).toHaveBeenCalledTimes(1))
    expect(errorSpy).toHaveBeenCalledWith('服务器内部错误，请稍后重试')
  })

  it('提交成功后只发一次请求并提示成功', async () => {
    apiPost.mockResolvedValue({ data: { id: 'app1' } })

    renderPage()
    fireEvent.click(screen.getByRole('tab', { name: /^申请/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: /新建申请/ })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /新建申请/ }))

    const title = await screen.findByLabelText('申请事项')
    await userEvent.type(title, '更换三支点螺栓需要吊车')

    const ok = screen.getByRole('button', { name: /确\s*定/ })
    fireEvent.click(ok)
    fireEvent.click(ok)

    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(successSpy).toHaveBeenCalledTimes(1))
  })
})

it('changes only the item status from the list and retains balance/detail fields', async () => {
  const item = { id: 'quick', name: '快捷网线', quantity: 25, unit: '米', status: 'on_site', location: '控制柜', note: '保留备注' }
  apiGet.mockImplementation(async (url: string) => ({ data: url.endsWith('/item-applications') ? [] : { items: [item], summary: {}, total: 1 } }))
  vi.mocked(api.patch).mockResolvedValueOnce({ data: { ...item, status: 'in_use' } })
  renderPage()
  fireEvent.mouseDown(await screen.findByRole('combobox', { name: '快捷网线物品状态' }))
  fireEvent.click(await screen.findByText('使用中'))
  await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/projects/p1/inventory/quick/status', { status: 'in_use', expected_status: 'on_site' }))
  expect(screen.queryByText('编辑物品')).not.toBeInTheDocument()
  expect(api.put).not.toHaveBeenCalled()
})
it('does not replace the current project inventory with a late previous-project list', async () => {
  let resolveOld!: (value: any) => void
  apiGet.mockImplementation((url: string) => url.endsWith('/item-applications') ? Promise.resolve({ data: [] })
    : url === '/projects/a/inventory' ? new Promise(resolve => { resolveOld = resolve })
    : Promise.resolve({ data: { items: [{ id: 'b1', name: 'B项目工具', quantity: 1 }], summary: {}, total: 1 } }))
  const view = render(<InventoryPage projectId="a" canManage={false} />)
  view.rerender(<InventoryPage projectId="b" canManage={false} />)
  expect(await screen.findByText('B项目工具')).toBeInTheDocument()
  await act(async () => { resolveOld({ data: { items: [{ id: 'a1', name: 'A项目工具' }], summary: {}, total: 1 } }) })
  expect(screen.queryByText('A项目工具')).not.toBeInTheDocument()
  expect(screen.getByText('B项目工具')).toBeInTheDocument()
})

it('流水丢失响应后冻结原内容并用同一UUID重试，不把重复回执当新扣减', async () => {
  const item = { id: 'item1', name: '螺栓', quantity: 20, unit: '个', location: '库房', custodian: '张三' }
  apiGet.mockImplementation(async (url: string) => ({ data: url.endsWith('/movements') || url.endsWith('/item-applications') ? [] : { items: [item], summary: {}, total: 1 } }))
  apiPost.mockRejectedValueOnce(new Error('timeout')).mockResolvedValueOnce({ data: { accepted: false, item: { ...item, quantity: 18 } } })
  renderPage()
  fireEvent.click(await screen.findByTitle('查看流水'))
  await screen.findByLabelText('本次数量')
  expect(screen.getByLabelText('本次数量')).toHaveValue('20')
  expect(screen.getByLabelText('本次数量')).toHaveAttribute('readonly')
  expect(screen.getByText('位置转移按整条台账数量移动')).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('说明'), { target: { value: '安装使用' } })
  fireEvent.click(screen.getByRole('button', { name: /保存记录/ }))
  await screen.findByText('这笔记录的结果尚未确认')
  expect(screen.getByLabelText('本次数量')).toBeDisabled()
  expect(screen.getByLabelText('说明')).toBeDisabled()
  const first = apiPost.mock.calls[0][1]
  expect(first).toMatchObject({ quantity: 20, note: '安装使用', client_uuid: expect.any(String) })
  expect(first.occurred_at).toMatch(/Z$/)
  const retry = screen.getByRole('button', { name: /重试本次记录/ })
  fireEvent.click(retry); fireEvent.click(retry)
  await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(2))
  expect(apiPost.mock.calls[1][1]).toEqual(first)
  await waitFor(() => expect(screen.getByLabelText('本次数量')).not.toBeDisabled())
  expect(successSpy).toHaveBeenCalledTimes(1)
})

it('流水已保存后刷新失败不误报写入失败，也不保留待重试操作', async () => {
  const item = { id: 'item1', name: '螺栓', quantity: 20, unit: '个', location: '库房' }
  let reads = 0
  apiGet.mockImplementation(async (url: string) => {
    if (url.endsWith('/movements')) { if (++reads > 1) throw new Error('refresh failed'); return { data: [] } }
    return { data: url.endsWith('/item-applications') ? [] : { items: [item], summary: {}, total: 1 } }
  })
  apiPost.mockResolvedValueOnce({ data: { accepted: true, item } })
  const warn = vi.spyOn(message, 'warning')
  renderPage()
  fireEvent.click(await screen.findByTitle('查看流水'))
  fireEvent.click(await screen.findByRole('button', { name: /保存记录/ }))
  await waitFor(() => expect(successSpy).toHaveBeenCalledOnce())
  await waitFor(() => expect(warn).toHaveBeenCalledWith('流水已保存，但最新记录读取失败，请刷新查看，无需重复提交'))
  expect(errorSpy).not.toHaveBeenCalled()
  expect(screen.queryByText('这笔记录的结果尚未确认')).toBeNull()
  warn.mockRestore()
})
it('从整批转移切到收发动作时默认单次1件，不继承整批库存数量', async () => {
  const item = { id: 'item1', name: '螺栓', quantity: 20, unit: '个' }
  apiGet.mockImplementation(async (url: string) => ({ data: url.endsWith('/movements') || url.endsWith('/item-applications') ? [] : { items: [item], summary: {}, total: 1 } }))
  renderPage()
  fireEvent.click(await screen.findByTitle('查看流水'))
  expect(screen.getByLabelText('本次数量')).toHaveValue('20')
  fireEvent.mouseDown(screen.getByLabelText('本次操作'))
  fireEvent.click(await screen.findByText('消耗', { selector: '.ant-select-item-option-content' }))
  expect(screen.getByLabelText('本次数量')).toHaveValue('1')
  expect(screen.getByLabelText('本次数量')).not.toHaveAttribute('readonly')
  expect(apiPost).not.toHaveBeenCalled()
})


it('旧手工墙钟与新UTC流水按显示时间排序并明确来源，初始盘点按UTC显示', async () => {
  const item = { id: 'item1', name: '历史工具', quantity: 2, unit: '台' }
  // Fix the intended local display order, then encode server timestamps as UTC.
  // This exercises UTC-naive normalization without assuming the runner is in Shanghai.
  const utcNaive = (hour: number, minute: number) => new Date(2026, 9, 5, hour, minute).toISOString().replace(/Z$/, '')
  const history = [
    { id: 'old', movement_type: 'transfer', occurred_at: '2026-10-05T03:10:00', time_basis: 'legacy_local', balance_after: 2, note: '旧手工墙钟' },
    { id: 'new', movement_type: 'transfer', occurred_at: utcNaive(4, 24), time_basis: 'utc', balance_after: 2, note: '新UTC记录' },
    { id: 'initial', movement_type: 'inventory', occurred_at: utcNaive(3, 0), time_basis: 'utc', balance_after: 2, note: '初始盘点' },
  ]
  apiGet.mockImplementation(async (url: string) => ({ data: url.endsWith('/movements') ? history : url.endsWith('/item-applications') ? [] : { items: [item], summary: {}, total: 1 } }))
  renderPage()
  fireEvent.click(await screen.findByTitle('查看流水'))
  await screen.findByText('旧手工墙钟')
  expect(screen.getByText(/旧记录未注明时区/)).toHaveTextContent('2026-10-05 03:10')
  expect(screen.getByText(/2026-10-05 04:24/)).not.toHaveTextContent('旧记录未注明时区')
  expect(screen.getByText(/2026-10-05 03:00/)).not.toHaveTextContent('旧记录未注明时区')
  const notes = [...document.querySelectorAll('.inventory-movement p')].map(element => element.textContent)
  expect(notes).toEqual(['新UTC记录', '旧手工墙钟', '初始盘点'])
})

it('shows full application information to a reader without a save or status mutation control', async () => {
  apiGet.mockImplementation(async (url:string)=>({data:url.endsWith('/item-applications')?[{id:'app-read',title:'现场吊车申请',item_name:'吊车',requirement:'停机窗口吊装',reason:'更换重件',status:'pending'}]:{items:[],summary:{},total:0}}))
  render(<InventoryPage projectId="p1" canManage={false} />)
  fireEvent.click(await screen.findByRole('tab',{name:/^申请/}))
  fireEvent.click(await screen.findByRole('button',{name:'查看申请'}))
  expect(screen.getByLabelText('原因')).toHaveValue('更换重件')
  expect(screen.getByLabelText('原因')).toBeDisabled()
  expect(screen.queryByRole('button',{name:/确\s*定/})).toBeNull()
  expect(api.put).not.toHaveBeenCalled()
  expect(apiPost).not.toHaveBeenCalled()
})
