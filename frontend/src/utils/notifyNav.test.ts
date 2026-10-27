import { beforeEach, describe, expect, it, vi } from 'vitest'
import { openNotification, formatNotificationContent, TYPE_TAG } from './notifyNav'

const nav = vi.fn()

beforeEach(() => {
  nav.mockClear()
})

it('uses current fixed categories while preserving historical notification facts', () => {
  expect(TYPE_TAG.schedule).toBe('计划通知')
  expect(TYPE_TAG.schedule_confirmed).toBe('计划通知')
  expect(TYPE_TAG.governance).toBe('负责人更换（历史）')
  const historical = '「原项目」日程已下达（v2），共 3 条日程'
  expect(formatNotificationContent(historical, 'schedule_confirmed')).toBe(historical)
})

describe('openNotification 通知跳转按 PM 工作台权限判权', () => {
  it.each([
    ['deliverable_submitted', '/documents'],
    ['deliverable_reviewed', '/documents'],
    ['report', '/reports'],
    ['schedule', '/plan?view=weeks'],
    ['schedule_confirmed', '/plan?view=weeks'],
  ])('PM %s 通知进入对应项目业务页', (ntype, path) => {
    openNotification({ ntype, project_id: 'p1' }, { role: 'pm' }, nav)
    expect(nav).toHaveBeenCalledWith(`/pm/projects/p1${path}`)
  })

  it('PM 工作台角色（technician）→ 项目问题上下文', () => {
    openNotification({ ntype: 'issue_assigned', project_id: 'p1' }, { role: 'technician' }, nav)
    expect(nav).toHaveBeenCalledWith('/pm/projects/p1/issues')
  })

  it('worker → 现场工作台（不进项目页）', () => {
    openNotification({ ntype: 'schedule', project_id: 'p1' }, { role: 'worker' }, nav)
    expect(nav).toHaveBeenCalledWith('/worker/week?project_id=p1')
  })

  it('intern → 现场工作台（回归：原 `role !== worker` 会把 intern 导向 /pm/projects → 403）', () => {
    openNotification({ ntype: 'schedule', project_id: 'p1' }, { role: 'intern' }, nav)
    expect(nav).toHaveBeenCalledWith('/worker/week?project_id=p1')
  })

  it('无 project_id → 当前账号可进入的工作台', () => {
    openNotification({ ntype: 'system', project_id: null }, { role: 'pm' }, nav)
    expect(nav).toHaveBeenCalledWith('/pm/dashboard')
  })
})

it('retired approval notifications remain in personal messages after project access changes',()=>{
 const navigate=vi.fn()
 openNotification({ntype:'governance',project_id:'old-project'},{role:'pm'},navigate)
 expect(navigate).toHaveBeenCalledWith('/pm/messages')
})

it('localizes only legacy system issue severity fields and preserves user text', () => {
  expect(formatNotificationContent('严重程度：medium · 上报人：张三', 'issue_assigned')).toBe('严重程度：中 · 上报人：张三')
  expect(formatNotificationContent('严重程度：critical · 上报人：张三', 'issue_reported')).toBe('严重程度：严重 · 上报人：张三')
  expect(formatNotificationContent('用户写下 medium 和 critical', 'issue_assigned')).toBe('用户写下 medium 和 critical')
  expect(formatNotificationContent('严重程度：medium · 上报人：张三', 'system')).toBe('严重程度：medium · 上报人：张三')
})

it.each(['issue_reported', 'issue_assigned', 'issue_resolved', 'issue_reopened', 'issue_cancelled'])('opens the exact field issue for %s', (ntype) => {
  openNotification({ ntype, project_id: 'p1', entity_id: 'issue-1' }, { role: 'worker' }, nav)
  expect(nav).toHaveBeenCalledWith('/worker/issues?issue_id=issue-1')
})

it('opens the field issue list when a legacy issue notification has no entity', () => {
  openNotification({ ntype: 'issue_assigned', project_id: 'p1' }, { role: 'intern' }, nav)
  expect(nav).toHaveBeenCalledWith('/worker/issues')
})

it('opens the document list for a historical field delivery review', () => {
  openNotification({ ntype: 'deliverable_reviewed', project_id: 'p1', entity_id: 'task-1' }, { role: 'worker' }, nav)
  expect(nav).toHaveBeenCalledWith('/pm/projects/p1/documents')
})

it.each(['worker', 'intern', 'pm'])('new document notifications use the same document list for %s', role => {
  openNotification({ ntype: 'document_submitted', project_id: 'p1', entity_id: 'document-1' }, { role }, nav)
  expect(nav).toHaveBeenCalledWith('/pm/projects/p1/documents')
})

it('opens the exact document for a deadline reminder without treating it as a task', () => {
  openNotification({ ntype: 'document_deadline', project_id: 'p1', entity_id: 'document-1' }, { role: 'worker' }, nav)
  expect(nav).toHaveBeenCalledWith('/pm/projects/p1/documents?document=document-1')
})
