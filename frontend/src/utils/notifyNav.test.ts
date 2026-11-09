import { beforeEach, describe, expect, it, vi } from 'vitest'
import { openNotification, formatNotificationContent } from './notifyNav'

const nav = vi.fn()

beforeEach(() => {
  nav.mockClear()
})

describe('openNotification 打开通知对应的工作', () => {
  it.each([
    ['document_submitted', '/documents'],
    ['report', '/reports'],
    ['schedule_confirmed', '/plan?view=weeks'],
  ])('%s 通知进入对应项目业务页', (ntype, path) => {
    openNotification({ ntype, project_id: 'p1' }, { role: 'employee' }, nav)
    expect(nav).toHaveBeenCalledWith(`/pm/projects/p1${path}`)
  })

  it('没有具体问题的问题通知进入项目问题页', () => {
    openNotification({ ntype: 'issue_assigned', project_id: 'p1' }, { role: 'employee' }, nav)
    expect(nav).toHaveBeenCalledWith('/pm/projects/p1/issues')
  })

  it('无 project_id → 工作台', () => {
    openNotification({ ntype: 'system', project_id: null }, { role: 'employee' }, nav)
    expect(nav).toHaveBeenCalledWith('/pm/dashboard')
  })
})

it('localizes only legacy system issue severity fields and preserves user text', () => {
  expect(formatNotificationContent('严重程度：medium · 上报人：张三', 'issue_assigned')).toBe('严重程度：中 · 上报人：张三')
  expect(formatNotificationContent('严重程度：critical · 上报人：张三', 'issue_reported')).toBe('严重程度：严重 · 上报人：张三')
  expect(formatNotificationContent('用户写下 medium 和 critical', 'issue_assigned')).toBe('用户写下 medium 和 critical')
  expect(formatNotificationContent('严重程度：medium · 上报人：张三', 'system')).toBe('严重程度：medium · 上报人：张三')
})

it.each(['issue_reported', 'issue_assigned', 'issue_resolved', 'issue_reopened', 'issue_cancelled'])('opens the exact field issue for %s', (ntype) => {
  openNotification({ ntype, project_id: 'p1', entity_id: 'issue-1' }, { role: 'employee' }, nav)
  expect(nav).toHaveBeenCalledWith('/worker/issues?issue_id=issue-1')
})

it('opens the issue list when an issue notification has neither project nor entity', () => {
  openNotification({ ntype: 'issue_assigned', project_id: null }, { role: 'employee' }, nav)
  expect(nav).toHaveBeenCalledWith('/worker/issues')
})

it.each(['employee', 'admin'])('new document notifications use the same document list for %s', role => {
  openNotification({ ntype: 'document_submitted', project_id: 'p1', entity_id: 'document-1' }, { role }, nav)
  expect(nav).toHaveBeenCalledWith('/pm/projects/p1/documents')
})

it('opens the exact document for a deadline reminder without treating it as a task', () => {
  openNotification({ ntype: 'document_deadline', project_id: 'p1', entity_id: 'document-1' }, { role: 'employee' }, nav)
  expect(nav).toHaveBeenCalledWith('/pm/projects/p1/documents?document=document-1')
})
