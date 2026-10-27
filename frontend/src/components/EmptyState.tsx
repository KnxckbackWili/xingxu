import { Button, Empty, Typography } from 'antd'
import type { ReactNode } from 'react'

/** 统一空状态：空数据与空筛选分流，后者给「清空筛选」。 */
export default function EmptyState({
  type = 'data',
  title,
  description,
  action,
  onClear,
  compact = false,
}: {
  type?: 'data' | 'filter'
  title?: string
  description?: ReactNode
  action?: ReactNode
  onClear?: () => void
  compact?: boolean
}) {
  const defaultTitle = type === 'filter' ? '没有匹配的结果' : '暂无数据'
  const defaultDesc =
    type === 'filter'
      ? '换一个筛选条件试试，或者清空筛选查看全部内容'
      : '这里还没有内容，后续会随着业务进展逐步沉淀'

  return (
    <div className={`empty-state${compact ? ' empty-state-compact' : ''}`}>
      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={null} />
      <Typography.Title level={5} style={{ margin: 0 }}>{title ?? defaultTitle}</Typography.Title>
      <Typography.Text type="secondary" style={{ maxWidth: 420, textAlign: 'center', fontSize: 12 }}>
        {description ?? defaultDesc}
      </Typography.Text>
      {type === 'filter' && onClear && (
        <Button size="small" onClick={onClear} style={{ marginTop: 12 }}>
          清空筛选
        </Button>
      )}
      {action && <div style={{ marginTop: 12 }}>{action}</div>}
    </div>
  )
}
