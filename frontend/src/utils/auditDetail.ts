import { ISSUE_STATUS_MAP } from '../constants/issues'

const SEVERITY_LABEL: Record<string, string> = { critical: '严重', high: '高', medium: '中', low: '低' }
const MOVEMENT_LABEL: Record<string, string> = {
  receive: '收货入场', issue: '领用出库', transfer: '位置转移', consume: '消耗',
  return_owner: '归还物主', return_site: '退回现场', adjust: '数量调整', inventory: '盘点',
}

/** Localize only the fixed enum suffixes of known system audit messages.
 * Audit storage, user-supplied titles, unknown formats and values stay unchanged.
 */
export function formatAuditDetail(detail: string): string {
  const status = /^更新问题：([\s\S]+) → 状态 (open|processing|resolved|closed|cancelled)$/.exec(detail)
  if (status && status[0] === detail) return `更新问题：${status[1]} → 状态 ${ISSUE_STATUS_MAP[status[2]].label}`
  const severity = /^上报问题：([\s\S]+)（(critical|high|medium|low)）$/.exec(detail)
  if (severity && severity[0] === detail) return `上报问题：${severity[1]}（${SEVERITY_LABEL[severity[2]]}）`
  const movement = /^物品「([\s\S]+)」新增流水：(receive|issue|transfer|consume|return_owner|return_site|adjust|inventory)$/.exec(detail)
  if (movement && movement[0] === detail) return `物品「${movement[1]}」新增流水：${MOVEMENT_LABEL[movement[2]]}`
  return detail
}
