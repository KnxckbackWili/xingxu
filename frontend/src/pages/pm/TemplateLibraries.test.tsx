import { beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import TemplateProcurementsTab from './TemplateProcurementsTab'
const { get, post, put, del } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() }))
vi.mock('../../api/client', () => ({ api: { get, post, put, delete: del } }))
beforeEach(() => { vi.clearAllMocks(); get.mockResolvedValue({ data: [] }) })
for (const [label, Component] of [['采购', TemplateProcurementsTab]] as const) {
  it(`${label}加载失败可重试`, async () => {
    get.mockRejectedValueOnce(new Error('offline'))
    render(<Component templateId="default" editMode />)
    expect(await screen.findByText('清单加载失败')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: /重.*试/ }))
    await waitFor(() => expect(screen.queryByText('清单加载失败')).not.toBeInTheDocument())
    expect(get).toHaveBeenCalledTimes(2)
  })
  it(`${label}保存失败保留输入，重复提交只发一次`, async () => {
    render(<Component templateId="default" editMode />)
    await waitFor(() => expect(get).toHaveBeenCalled())
    fireEvent.click(screen.getByRole('button', { name: /添加常用项/ }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText('物料名称'), { target: { value: '测试名称' } })
    let rejectSave: (reason: Error) => void = () => {}
    post.mockImplementation(() => new Promise((_resolve, reject) => { rejectSave = reject }))
    const save = within(dialog).getByRole('button', { name: /保.*存/ })
    fireEvent.click(save); fireEvent.click(save)
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1))
    rejectSave(new Error('offline'))
    expect(await screen.findByText('保存失败')).toBeVisible()
    expect(within(dialog).getByLabelText('物料名称')).toHaveValue('测试名称')
  })
}
for (const [label, Component] of [['采购', TemplateProcurementsTab]] as const) {
  it(`${label}旧模板保存完成不能刷新覆盖新模板`, async () => {
    get.mockImplementation(async (url: string) => ({ data: url.includes('/new/') ? [{ id: 'new-item', name: '新模板内容', category: 'scope' }] : [] }))
    let resolveSave: (value: any) => void = () => {}
    post.mockImplementation(() => new Promise(resolve => { resolveSave = resolve }))
    const view = render(<Component templateId="old" editMode />)
    fireEvent.click(screen.getByRole('button', { name: /添加常用项/ }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText('物料名称'), { target: { value: '旧模板新增' } })
    fireEvent.click(within(dialog).getByRole('button', { name: /保.*存/ }))
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1))
    view.rerender(<Component templateId="new" editMode />)
    expect(await screen.findByText('新模板内容')).toBeVisible()
    resolveSave({ data: {} })
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2))
    expect(screen.getByText('新模板内容')).toBeVisible()
  })
}
