import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { Button, Popover } from 'antd'
import { CloseOutlined, QuestionCircleOutlined } from '@ant-design/icons'
import './quickControls.css'

interface Props { id: string; title: string; children: ReactNode }
/** Help is available on request, without interrupting work on the page. */
export default function ContextTip({ id, title, children }: Props) {
  const [open, setOpen] = useState(false)
  const trigger = useRef<HTMLSpanElement>(null)

  const close = () => {
    setOpen(false)
    trigger.current?.querySelector('button')?.focus()
  }
  const onKeyDown = (event: KeyboardEvent) => {
    if (open && event.key === 'Escape') {
      event.stopPropagation()
      close()
    }
  }
  useEffect(() => { setOpen(false) }, [id, title])

  return <span ref={trigger} className="context-tip-anchor" onKeyDown={onKeyDown}><Popover open={open} trigger="click" placement="top" destroyOnHidden
    onOpenChange={setOpen}
    title={<div className="context-tip-heading"><span>{title}</span><Button type="text" size="small" icon={<CloseOutlined />} aria-label={`关闭提示：${title}`} onClick={close} /></div>}
    content={<div className="context-tip-copy">{children}</div>}>
    <Button className="context-tip-trigger" type="text" size="small" icon={<QuestionCircleOutlined />}
      aria-label={`操作提示：${title}`} aria-expanded={open} title={title} />
  </Popover></span>
}
