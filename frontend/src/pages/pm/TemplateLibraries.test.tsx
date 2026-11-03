import { beforeEach, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import TemplateProcPanel from './TemplateProcPanel'
const { get, post, put, del } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() }))
vi.mock('../../api/client', () => ({ api: { get, post, put, delete: del }, errMsg: () => '保存失败' }))
beforeEach(() => { vi.clearAllMocks() })
const flushRef = { current: null as null | (() => Promise<void>) }

it('a new procurement item is added once even when the button is pressed twice, and a failure keeps the input', async () => {
  let reject: (reason: Error) => void = () => {}
  post.mockImplementation(() => new Promise((_resolve, fail) => { reject = fail }))
  const created = vi.fn()
  render(<TemplateProcPanel templateId="default" editMode flushRef={flushRef} onChanged={vi.fn()} onCreated={created} onClose={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('物料名称'), { target: { value: '充电桩' } })
  const add = screen.getByRole('button', { name: /添加采购物料/ })
  fireEvent.click(add); fireEvent.click(add)
  await waitFor(() => expect(post).toHaveBeenCalledTimes(1))
  expect(post.mock.calls[0]).toEqual(['/templates/default/procurements', { name: '充电桩', unit: '台', spec: '', risk: 'low', is_required: false }])
  await act(async () => reject(new Error('offline')))
  expect(screen.getByLabelText('物料名称')).toHaveValue('充电桩')
  expect(created).not.toHaveBeenCalled()
})

it('an existing item saves itself after typing stops, and switching rows saves first', async () => {
  put.mockResolvedValue({ data: {} })
  const changed = vi.fn()
  render(<TemplateProcPanel templateId="t1" editMode item={{ id: 'p1', name: '工控机', unit: '台', spec: '', risk: 'low', is_required: true }} flushRef={flushRef} onChanged={changed} onCreated={vi.fn()} onClose={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('规格 / 型号 / 说明'), { target: { value: '含 4G 模块' } })
  await act(async () => { await flushRef.current?.() })
  expect(put).toHaveBeenCalledWith('/templates/t1/procurements/p1', { name: '工控机', unit: '台', spec: '含 4G 模块', risk: 'low', is_required: true })
  expect(changed).toHaveBeenCalled()
  expect(await screen.findByText('已保存')).toBeInTheDocument()
})
