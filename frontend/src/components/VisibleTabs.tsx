import { useId } from 'react'
import { Tabs, type TabsProps } from 'antd'

/** Wrapping tab labels: no horizontal clipping or overflow-only destinations. */
export default function VisibleTabs({ items = [], id, hideBar = false, ...props }: TabsProps & { hideBar?: boolean }) {
  const generatedId = useId()
  if (hideBar) return <>{items.find(item => item.key === (props.activeKey ?? props.defaultActiveKey ?? items[0]?.key))?.children}</>
  return <Tabs {...props} id={id ?? `visible-tabs-${generatedId}`} items={items}
    renderTabBar={(bar) => <div className="visible-tabs-bar" style={bar.style}>
      <div className="visible-tabs-list" role="tablist" aria-label="页面功能" aria-orientation="horizontal">
        {items.map((item) => <button
          key={item.key} type="button" role="tab"
          id={`${bar.id}-tab-${item.key}`} aria-controls={`${bar.id}-panel-${item.key}`}
          aria-selected={bar.activeKey === item.key} disabled={item.disabled}
          tabIndex={bar.activeKey === item.key ? 0 : -1}
          className={`visible-tab${bar.activeKey === item.key ? ' is-active' : ''}`}
          onClick={(event) => bar.onTabClick(item.key, event)}
          onKeyDown={(event) => {
            if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
            event.preventDefault()
            const enabled = items.filter((tab) => !tab.disabled)
            const index = enabled.findIndex((tab) => tab.key === item.key)
            const delta = (event.key === 'ArrowRight' ? 1 : -1) * (bar.rtl ? -1 : 1)
            const next = event.key === 'Home' ? 0 : event.key === 'End' ? enabled.length - 1 : (index + delta + enabled.length) % enabled.length
            const target = enabled[next]
            if (!target) return
            const buttons = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('button[role="tab"]:not(:disabled)')
            buttons?.[next]?.focus()
            bar.onTabClick(target.key, event)
          }}
        >{item.icon}{item.label}</button>)}
      </div>
    </div>}
  />
}
