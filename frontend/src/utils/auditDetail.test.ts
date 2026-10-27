import { expect, it } from 'vitest'
import { formatAuditDetail } from './auditDetail'

it.each([
  ['open', '待处理'], ['processing', '处理中'], ['resolved', '已解决'],
  ['closed', '已关闭'], ['cancelled', '已作废'],
])('localizes the fixed issue-status suffix %s while preserving the issue title', (value, label) => {
  expect(formatAuditDetail(`更新问题：PLC processing/closed 状态复核 → 状态 ${value}`))
    .toBe(`更新问题：PLC processing/closed 状态复核 → 状态 ${label}`)
})

it.each([['critical', '严重'], ['high', '高'], ['medium', '中'], ['low', '低']])('localizes the fixed issue-severity suffix %s', (value, label) => {
  expect(formatAuditDetail(`上报问题：low（high）信号问题（${value}）`))
    .toBe(`上报问题：low（high）信号问题（${label}）`)
})

it.each([
  ['receive', '收货入场'], ['issue', '领用出库'], ['transfer', '位置转移'], ['consume', '消耗'],
  ['return_owner', '归还物主'], ['return_site', '退回现场'], ['adjust', '数量调整'], ['inventory', '盘点'],
])('localizes the fixed inventory-movement suffix %s', (value, label) => {
  expect(formatAuditDetail(`物品「transfer型「receive」测距仪」新增流水：${value}`))
    .toBe(`物品「transfer型「receive」测距仪」新增流水：${label}`)
})

it.each([
  '客户记录：closed/low/transfer 尚需复核',
  '更新问题：待复核 → 状态 future_status',
  '上报问题：待复核（urgent）',
  '物品「测距仪」新增流水：future_action',
  '备注：更新问题：待复核 → 状态 closed',
  '更新问题：待复核 → 状态 closed；用户补充',
  '上报问题：待复核（low）\n备注：保留原文',
  '物品「测距仪」新增流水：receive extra',
  '更新问题：待复核 → 状态 closed\n',
  '上报问题：待复核（low）\n',
  '物品「测距仪」新增流水：receive\n',
  '更新问题：待复核 → 状态 已关闭',
  '',
])('preserves free text, unknown values and unmatched formats: %s', (detail) => {
  expect(formatAuditDetail(detail)).toBe(detail)
})
