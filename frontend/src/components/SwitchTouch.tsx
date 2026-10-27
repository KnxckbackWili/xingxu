import { Switch } from 'antd'

interface SwitchTouchProps {
  /** 稳定唯一的 id：同时落到 Switch 按钮与 label 的 htmlFor，保证一行一个热区 */
  id: string
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
  loading?: boolean
}

/**
 * 移动端 Switch 触控热区：用带匹配 htmlFor 的 <label> 包裹 Switch，
 * 使整个 44px 热区（含上下 padding）点击都只触发一次切换。
 * Switch 自身保留：onChange、键盘焦点（role=switch 按钮仍可 Tab 聚焦）、disabled/loading 语义。
 */
export default function SwitchTouch({ id, checked, onChange, disabled, loading }: SwitchTouchProps) {
  return (
    <label className="switch-touch" htmlFor={id}>
      <Switch id={id} checked={checked} onChange={onChange} disabled={disabled} loading={loading} />
    </label>
  )
}
