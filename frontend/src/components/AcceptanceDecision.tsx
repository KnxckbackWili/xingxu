import { Alert, Space, Typography } from 'antd'
import { formatDateTime } from '../utils/date'

export interface AcceptanceRecord {
  id: string
  accepted_by_name: string
  accepted_at: string
  created_at?: string
  conclusion: 'accepted' | 'conditionally_accepted' | 'rejected'
  attachment_id?: string | null
  notes?: string
  is_effective?: boolean
  scope_current?: boolean
  scope_verified?: boolean
  effective_date_reached?: boolean
  invalid_reason?: string
}

export interface AcceptanceSummary {
  latest: AcceptanceRecord | null
  eligible: boolean
  reason: string
  warning?: string
  pending_future_count?: number
  as_of_date?: string
}

export const acceptanceLabels = { accepted: '通过', conditionally_accepted: '有条件通过', rejected: '不通过' }

/** The server selects the controlling decision and supplies its completion eligibility. */
export function acceptanceDecisionText(summary: AcceptanceSummary): string {
  const latest = summary.latest
  const decision = latest
    ? `最新验收：${acceptanceLabels[latest.conclusion]} · ${latest.accepted_at} · ${latest.accepted_by_name}。${summary.reason}`
    : `最新验收：暂无记录。${summary.reason}`
  return `${decision}${summary.warning ? ` 提醒：${summary.warning}` : ''}`
}

export default function AcceptanceDecision({ summary }: { summary?: AcceptanceSummary }) {
  if (!summary) return null
  const latest = summary.latest
  return <Alert showIcon type={summary.eligible && !summary.warning ? 'success' : 'warning'}
    message={latest ? `最新验收结论：${acceptanceLabels[latest.conclusion]}` : '尚无验收结论'}
    description={<Space direction="vertical" size={4}>
      {latest && <Typography.Text>验收日期 {latest.accepted_at} · 验收人 {latest.accepted_by_name}{latest.created_at ? ` · 录入时间 ${formatDateTime(latest.created_at)}` : ''}</Typography.Text>}
      <Typography.Text>{summary.reason || (summary.eligible ? '最新验收已通过；完成及归档仍需核对其他条件。' : '请在资料清单中核对最新验收结论。')}</Typography.Text>
      {summary.warning && <Typography.Text type="warning">{summary.warning}</Typography.Text>}
    </Space>} />
}
