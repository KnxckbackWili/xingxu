import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import SwitchTouch from './SwitchTouch'

describe('SwitchTouch 44px 触控热区', () => {
  it('id 落到 Switch 按钮，label htmlFor 匹配，控件仍是原生按钮（键盘焦点保留）', () => {
    render(<SwitchTouch id="tk-1" checked={false} onChange={vi.fn()} />)
    const sw = screen.getByRole('switch')
    const label = sw.closest('label')!
    expect(sw.tagName).toBe('BUTTON')
    expect(sw).toHaveAttribute('id', 'tk-1')
    expect(sw).toHaveAttribute('aria-checked', 'false')
    expect(label).toHaveAttribute('for', 'tk-1')
    expect(label).toHaveClass('switch-touch')
  })

  it('点击 label 上下 padding 区域只切换一次', () => {
    const onChange = vi.fn()
    render(<SwitchTouch id="tk-1" checked={false} onChange={onChange} />)
    const label = screen.getByRole('switch').closest('label')!
    fireEvent.click(label)
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange.mock.calls[0][0]).toBe(true)
  })

  it('点击 Switch 本体不重复切换', () => {
    const onChange = vi.fn()
    render(<SwitchTouch id="tk-1" checked={false} onChange={onChange} />)
    fireEvent.click(screen.getByRole('switch'))
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange.mock.calls[0][0]).toBe(true)
  })

  it('禁用态不切换：label 热区与 Switch 本体都不触发 onChange', () => {
    const onChange = vi.fn()
    render(<SwitchTouch id="tk-1" checked={false} onChange={onChange} disabled />)
    const sw = screen.getByRole('switch')
    expect(sw).toBeDisabled()
    const label = sw.closest('label')!
    fireEvent.click(label)
    fireEvent.click(sw)
    expect(onChange).not.toHaveBeenCalled()
    expect(sw).toHaveAttribute('aria-checked', 'false')
  })

  it('loading 态等价禁用，不触发切换', () => {
    const onChange = vi.fn()
    render(<SwitchTouch id="tk-1" checked={false} onChange={onChange} loading />)
    const sw = screen.getByRole('switch')
    expect(sw).toBeDisabled()
    fireEvent.click(sw)
    expect(onChange).not.toHaveBeenCalled()
  })
})
