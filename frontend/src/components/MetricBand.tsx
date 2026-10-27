import { Space, Typography } from 'antd'
import type { ReactNode } from 'react'

export interface MetricBandItem {
  label: string
  value: ReactNode
  /** 强调色；不传使用品牌主色 */
  tone?: 'brand' | 'success' | 'warning' | 'danger' | 'neutral'
  hint?: ReactNode
}

const TONE_CLASS: Record<NonNullable<MetricBandItem['tone']>, string> = {
  brand: 'metric-tone-brand',
  success: 'metric-tone-success',
  warning: 'metric-tone-warning',
  danger: 'metric-tone-danger',
  neutral: 'metric-tone-neutral',
}

/** 统一指标条：替换散落各页的指标画法，保证同一条带、同一字号、同一间距。 */
export default function MetricBand({ items, columns }: { items: MetricBandItem[]; columns?: number }) {
  return (
    <div
      className={`metric-band${columns ? ` metric-band-cols-${columns}` : ''}`}
      style={columns ? { gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` } : undefined}
    >
      {items.map((item, index) => (
        <div className="metric-cell" key={`${item.label}-${index}`}>
          <Space direction="vertical" size={2} className="metric-cell-inner">
            <Typography.Text type="secondary" className="metric-label">{item.label}</Typography.Text>
            <span className={`metric-value ${TONE_CLASS[item.tone ?? 'brand']}`}>{item.value}</span>
            {item.hint && <Typography.Text type="secondary" className="metric-hint">{item.hint}</Typography.Text>}
          </Space>
        </div>
      ))}
    </div>
  )
}
