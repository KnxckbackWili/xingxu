import { forwardRef, useId, type ReactNode } from 'react'
import { Button, Tooltip, type ButtonProps } from 'antd'
import { InfoCircleOutlined, ReloadOutlined } from '@ant-design/icons'

type IconActionProps = Omit<ButtonProps, 'icon' | 'type' | 'children'> & { label: string; icon: ReactNode; bordered?: boolean }

/** An icon-only button; the label is the tooltip and the accessible name. Extra props reach the button, so it can sit inside Popconfirm/Dropdown. */
export const IconAction = forwardRef<HTMLButtonElement | HTMLAnchorElement, IconActionProps>(function IconAction({ label, icon, bordered = false, className = '', ...rest }, ref) {
  return <Tooltip title={label}>
    <Button ref={ref} aria-label={label} {...rest} className={`icon-action ${className}`} type={bordered ? 'default' : 'text'} icon={icon} />
  </Tooltip>
})

export function RefreshAction({ label = '刷新', onClick, loading, disabled }: { label?: string; onClick: () => unknown; loading?: boolean; disabled?: boolean }) {
  return <IconAction bordered label={label} icon={<ReloadOutlined />} onClick={() => void onClick()} loading={loading} disabled={disabled} />
}

/** Explanatory text kept out of the way: an ⓘ beside a heading, still read by screen readers. */
export function InfoHint({ text }: { text: ReactNode }) {
  const id = useId()
  return <>
    <Tooltip title={text} trigger={['hover', 'focus', 'click']} placement="bottomLeft">
      <span className="info-hint" tabIndex={0} role="img" aria-label="查看说明" aria-describedby={id}><InfoCircleOutlined /></span>
    </Tooltip>
    <span id={id} className="sr-only">{text}</span>
  </>
}
