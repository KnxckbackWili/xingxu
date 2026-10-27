import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import InlineSelect from './InlineSelect'

const options = [{ value: 'on_site', label: '在现场' }, { value: 'in_transit', label: '运输中' }]

it('keeps the confirmed value and explains a failed quick save', async () => {
  const save = vi.fn().mockRejectedValue(new Error('网络断开，原值已保留'))
  render(<InlineSelect label="路由器状态" value="on_site" options={options} onSave={save} />)
  fireEvent.mouseDown(screen.getByRole('combobox', { name: '路由器状态' }))
  fireEvent.click(await screen.findByText('运输中'))
  await waitFor(() => expect(save).toHaveBeenCalledWith('in_transit'))
  expect(await screen.findByRole('alert')).toHaveAttribute('aria-label', expect.stringContaining('原值已保留'))
  expect(document.querySelector('.ant-select-selection-item')).toHaveTextContent('在现场')
})

it('disables a pending save and renders the server-confirmed value after success', async () => {
  let finish!: () => void
  const save = vi.fn(() => new Promise<void>((resolve) => { finish = resolve }))
  const view = render(<InlineSelect label="路由器状态" value="on_site" options={options} onSave={save} />)
  fireEvent.mouseDown(screen.getByRole('combobox', { name: '路由器状态' }))
  fireEvent.click(await screen.findByText('运输中'))
  await waitFor(() => expect(screen.getByRole('combobox', { name: '路由器状态' })).toBeDisabled())
  expect(save).toHaveBeenCalledTimes(1)
  finish()
  await waitFor(() => expect(screen.getByRole('combobox', { name: '路由器状态' })).not.toBeDisabled())
  view.rerender(<InlineSelect label="路由器状态" value="in_transit" options={options} onSave={save} />)
  expect(document.querySelector('.ant-select-selection-item')).toHaveTextContent('运输中')
})
