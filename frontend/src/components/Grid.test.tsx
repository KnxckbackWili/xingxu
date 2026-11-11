import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
import Grid, { type Column } from './Grid'

interface Item { id: string; name: string; quantity: number | null; arrived: boolean; note: string }
const columns: Column<Item>[] = [
  { key: 'arrived', title: '到了', label: '到了', type: 'check', hint: () => '张伟 · 2026-05-23' },
  { key: 'name', title: '名称', label: '名称', primary: true, required: true },
  { key: 'quantity', title: '数量', label: '数量', type: 'number' },
  { key: 'note', title: '备注', label: '备注' },
]
const rows: Item[] = [{ id: 'a', name: '充电桩', quantity: 2, arrived: false, note: '' }, { id: 'b', name: '围栏', quantity: null, arrived: true, note: '分两批' }]
const setup = (props: Partial<Parameters<typeof Grid<Item>>[0]> = {}) => {
  const onSet = vi.fn()
  const view = render(<Grid label="物品" rows={rows} columns={columns} onSet={onSet} {...props} />)
  return { onSet, ...view, row: (index: number) => within(screen.getAllByRole('row')[index + 1]) }
}

describe('可编辑表格', () => {
  it('saves a cell when it is left, with the value the edit started from', () => {
    const { onSet, row } = setup()
    const input = row(0).getByLabelText('名称')
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: '  自动充电桩 ' } })
    expect(onSet).not.toHaveBeenCalled()
    fireEvent.blur(input)
    expect(onSet).toHaveBeenCalledWith(rows[0], 'name', '自动充电桩', '充电桩')
  })

  it('does not save an unchanged cell, and Escape gives the edit up', () => {
    const { onSet, row } = setup()
    const input = row(0).getByLabelText('备注')
    fireEvent.focus(input)
    fireEvent.blur(input)
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: '写错了' } })
    fireEvent.keyDown(input, { key: 'Escape' })
    fireEvent.blur(input)
    expect(onSet).not.toHaveBeenCalled()
    expect(input).toHaveValue('')
  })

  it('refuses to empty a required cell and to store text as a number', () => {
    const { onSet, row } = setup()
    const name = row(0).getByLabelText('名称')
    fireEvent.focus(name); fireEvent.change(name, { target: { value: ' ' } }); fireEvent.blur(name)
    expect(name).toHaveValue('充电桩')
    const quantity = row(0).getByLabelText('数量')
    fireEvent.focus(quantity); fireEvent.change(quantity, { target: { value: '很多' } }); fireEvent.blur(quantity)
    expect(quantity).toHaveValue('2')
    expect(onSet).not.toHaveBeenCalled()
    fireEvent.focus(quantity); fireEvent.change(quantity, { target: { value: '' } }); fireEvent.blur(quantity)
    expect(onSet).toHaveBeenCalledWith(rows[0], 'quantity', null, 2)
  })

  it('shows another person\'s change, but not over the cell being typed in', () => {
    const { rerender, row } = setup()
    const input = row(0).getByLabelText('备注')
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: '我正在写' } })
    const changed = [{ ...rows[0], note: '别人写的', name: '别人改的名字' }, rows[1]]
    rerender(<Grid label="物品" rows={changed} columns={columns} onSet={vi.fn()} />)
    expect(row(0).getByLabelText('备注')).toHaveValue('我正在写')
    expect(row(0).getByLabelText('名称')).toHaveValue('别人改的名字')
  })

  it('ticks with one click and says who ticked', () => {
    const { onSet, row } = setup()
    const tick = row(0).getByRole('checkbox', { name: '到了' })
    expect(tick).toHaveAttribute('aria-checked', 'false')
    expect(row(1).getByRole('checkbox', { name: '到了' })).toHaveAttribute('title', '张伟 · 2026-05-23')
    fireEvent.click(tick)
    expect(onSet).toHaveBeenCalledWith(rows[0], 'arrived', true)
  })

  it('adds a row from the last line with Enter and keeps the text when adding fails', async () => {
    const onAdd = vi.fn().mockResolvedValueOnce(undefined).mockRejectedValueOnce(new Error('offline'))
    setup({ onAdd, addPlaceholder: '输入名称后回车' })
    const input = screen.getByPlaceholderText('输入名称后回车')
    fireEvent.change(input, { target: { value: ' 叉齿 ' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onAdd).toHaveBeenCalledWith('叉齿')
    expect(input).toHaveValue('')
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onAdd).toHaveBeenCalledTimes(1)
    fireEvent.change(input, { target: { value: '托盘' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await vi.waitFor(() => expect(input).toHaveValue('托盘'))
  })

  it('labels every cell for the phone card and expands a row on demand', () => {
    setup({ expand: (row) => <p>{row.name} 的明细</p>, expandLabel: () => '记录 0' })
    expect(screen.getAllByRole('row')[1].querySelector('td.is-primary')).toHaveAttribute('data-label', '名称')
    expect(screen.queryByText('充电桩 的明细')).not.toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button', { name: '记录 0' })[0])
    expect(screen.getByText('充电桩 的明细')).toBeInTheDocument()
  })

  it('says so when there is nothing to show', () => {
    render(<Grid label="物品" rows={[]} columns={columns} onSet={vi.fn()} empty="物品都到齐了" />)
    expect(screen.getByText('物品都到齐了')).toBeInTheDocument()
  })
})
