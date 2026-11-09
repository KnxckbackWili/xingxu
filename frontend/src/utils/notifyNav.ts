import type { NavigateFunction } from 'react-router-dom'
import { systemHomeRoute } from '../constants/nav'
import type { PermissionUser } from '../constants/systemPermissions'

/** Notification type label mapping (shared by bell dropdown and message center). */
export const TYPE_TAG: Record<string, string> = {
  issue_assigned: '问题指派',
  issue_reported: '问题上报',
  issue_resolved: '问题解决',
  issue_reopened: '问题重开',
  issue_cancelled: '问题取消',
  document_submitted: '资料提交',
  document_deadline: '资料截止提醒',
  schedule_confirmed: '计划通知',
  issue_sla: '问题时限',
  project_membership: '项目负责人',
  report: '报告',
  system: '系统',
}

/** Show issue severity codes in Chinese; user text is kept as written. */
export function formatNotificationContent(content: string, ntype: string): string {
  if (!['issue_reported', 'issue_assigned'].includes(ntype)) return content
  const labels: Record<string, string> = { critical: '严重', high: '高', medium: '中', low: '低' }
  return content.replace(/^严重程度：(critical|high|medium|low)(?= · 上报人：)/, (_, severity: string) => `严重程度：${labels[severity]}`)
}

interface NotifyTarget {
  ntype: string
  project_id: string | null
  entity_id?: string | null
}

/** Navigate to the context of a notification. */
export function openNotification(
  n: NotifyTarget,
  user: PermissionUser | null,
  navigate: NavigateFunction,
) {
  if (n.project_id && ['document_submitted', 'document_deadline'].includes(n.ntype)) {
    navigate(`/pm/projects/${encodeURIComponent(n.project_id)}/documents${n.ntype === 'document_deadline' && n.entity_id ? `?document=${encodeURIComponent(n.entity_id)}` : ''}`)
    return
  }
  if (n.project_id && n.ntype === 'schedule_confirmed') {
    navigate(`/pm/projects/${encodeURIComponent(n.project_id)}/plan?view=weeks`)
    return
  }
  if (n.ntype.startsWith('issue_') && n.entity_id) {
    navigate(`/worker/issues?issue_id=${encodeURIComponent(n.entity_id)}`)
  } else if (n.project_id) {
    const tab =
      n.ntype.startsWith('issue') ? '/issues'
      : n.ntype === 'report' ? '/reports'
      : ''
    navigate(`/pm/projects/${n.project_id}${tab}`)
  } else if (n.ntype.startsWith('issue_')) {
    navigate('/worker/issues')
  } else {
    navigate(systemHomeRoute(user))
  }
}
