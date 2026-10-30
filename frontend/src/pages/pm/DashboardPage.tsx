import { lazy, Suspense, useEffect, useRef, useState, type ReactNode } from 'react'
import { Alert, Button, Collapse, Empty, Spin, Table, Tag, Typography } from 'antd'
import { Link, useLocation } from 'react-router-dom'
import dayjs from 'dayjs'
import { useAuth } from '../../stores/auth'
import { hasSystemPermission } from '../../constants/systemPermissions'
import { canAccessNav } from '../../constants/nav'
import { projectStatusMeta } from '../../constants/status'
import VehicleProgressSummary from '../../components/VehicleProgressSummary'
import { WorkPageHeader } from '../../components/WorkPage'
import { workbenchApi, documentActionUrl, type WorkbenchOverview, type WorkbenchAction } from '../../api/workbench'
import { fieldWeekApi, type Week } from '../../api/fieldWeek'
import { api, errMsg } from '../../api/client'
import { deadlineLabel } from '../../utils/documentDeadlines'
import './DashboardPage.css'
import { RefreshAction } from '../../components/IconAction'
const WorkspaceStatistics = lazy(() => import('../../components/WorkspaceStatistics'))

type Kind = '资料' | '周计划' | '问题' | '签单'
type TodoRow = { key: string; kind: Kind; title: ReactNode; meta: string; due: string; urgent?: boolean }
type IssueRow = { id: string; title: string; project_id: string; project_name: string; status: string; severity: string; assignee_id: string | null; assignee_name: string; sla_due_at?: string | null }
const KINDS: Kind[] = ['资料', '周计划', '问题', '签单']
const PAGE = 8

const docLink = (row: WorkbenchAction) => <Link to={documentActionUrl(row)}>{row.code} {row.name}{row.vehicle_label ? ` · ${row.vehicle_label}` : ''}</Link>

/** 我的本周：分配给当前账号的已发布周计划，登记在本周页完成。 */
function MyWeek({ account }: { account: string }) {
  const [week, setWeek] = useState<Week>()
  const [error, setError] = useState('')
  useEffect(() => {
    let live = true; setWeek(undefined); setError('')
    fieldWeekApi.week(undefined, account).then(data => { if (live) setWeek(data) }).catch(failure => { if (live) setError(errMsg(failure)) })
    return () => { live = false }
  }, [account])
  const plans = week?.plans ?? []
  const blocked = week ? new Set(week.warnings.map(row => row.project_id)).size : 0
  return <section className="workbench-card workbench-mine" aria-labelledby="workbench-mine-title">
    <div className="workbench-card-head"><h2 id="workbench-mine-title">我的本周</h2><Link to="/worker/week">去登记</Link></div>
    {error ? <Alert type="warning" showIcon message="我的本周暂不可读取" description={error} />
      : !week ? <Spin aria-label="正在读取我的本周" />
      : !plans.length ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="本周没有分配给你的工作" />
      : <ul className="workbench-mine-list">{plans.slice(0, 6).map(plan => <li key={plan.id}>
        <span className="workbench-mine-name">{plan.work_item.name}</span>
        <Tag>{plan.mode === 'finish' ? '计划完成' : '推进中'}</Tag>
        <small>{plan.project_name} · {plan.work_item.phase_name}{plan.work_item.check_items.length ? ` · ${plan.work_item.check_items.length} 项检查` : ''}</small>
      </li>)}{plans.length > 6 && <li className="workbench-more"><Link to="/worker/week">还有 {plans.length - 6} 项</Link></li>}</ul>}
    {blocked > 0 && <p className="workbench-mine-note">{blocked} 个项目有需要核对的提醒，详见本周页。</p>}
  </section>
}

export default function DashboardPage() {
  const { user } = useAuth()
  const location = useLocation()
  const canWorkspace = hasSystemPermission(user, 'workspace.view')
  const canStatistics = hasSystemPermission(user, 'insights.view')
  const canWeek = canAccessNav('/worker/week', user)
  const scope = JSON.stringify([user?.id, user?.role, user?.permission_version, user?.system_permissions, user?.permission_overrides])
  const [snapshot, setSnapshot] = useState<{ scope: string; data?: WorkbenchOverview; error?: string; issues?: IssueRow[]; issuesError?: string }>({ scope: '' })
  const current = snapshot.scope === scope ? snapshot : undefined
  const data = current?.data
  const [loading, setLoading] = useState(false)
  const [kind, setKind] = useState<Kind | '全部'>('全部')
  const [showAll, setShowAll] = useState(false)
  const sequence = useRef(0)
  const load = async () => {
    if (!canWorkspace) return
    const ticket = ++sequence.current; setLoading(true); setSnapshot(prev => prev.scope === scope ? { ...prev, error: '' } : { scope })
    const issues = api.get('/dashboard/issues').then(r => ({ issues: (r.data?.items ?? []) as IssueRow[] }), failure => ({ issuesError: errMsg(failure) }))
    try {
      const next = await workbenchApi.overview(); if (!Array.isArray(next.projects)) throw new Error('工作台响应不完整')
      const issueState = await issues
      if (ticket === sequence.current) setSnapshot({ scope, data: next, ...issueState })
    } catch (failure) { if (ticket === sequence.current) setSnapshot({ scope, error: errMsg(failure) }) }
    finally { if (ticket === sequence.current) setLoading(false) }
  }
  useEffect(() => { setSnapshot({ scope }); if (canWorkspace) void load(); return () => { sequence.current++ } }, [scope, canWorkspace])

  const projects = data?.projects ?? []
  const plan = data?.weekly_plan
  const planReadable = plan?.state === 'available' && Array.isArray(plan.items)
  const overdueReadable = !projects.some(project => !project.document_attention)
  const signoffReadable = !projects.some(project => project.next_signoff === undefined)
  const todos: TodoRow[] = []
  const seen = new Set<string>()
  for (const project of projects) for (const row of project.document_attention?.overdue ?? []) {
    const action = { ...row, project_id: project.id, project_name: project.name, timezone: project.document_attention!.timezone }
    seen.add(`${project.id}:${row.id}`)
    todos.push({ key: `overdue:${project.id}:${row.id}`, kind: '资料', title: docLink(action), meta: project.name, due: `逾期 ${row.overdue_days} 天`, urgent: true })
  }
  if (planReadable) {
    for (const row of plan!.items ?? []) todos.push({ key: `plan:${row.id}`, kind: '周计划', title: <Link to={row.url}>{row.name}</Link>, meta: `${row.project_name} · 计划周 ${row.week_start}`, due: '已逾期未完成', urgent: true })
  }
  for (const row of current?.issues ?? []) if (!row.assignee_id || row.assignee_id === user?.id) {
    todos.push({ key: `issue:${row.id}`, kind: '问题', title: <Link to={`/pm/projects/${encodeURIComponent(row.project_id)}/issues`}>{row.title}</Link>,
      meta: `${row.project_name} · ${row.assignee_id ? '指派给我' : '未指派'}`, due: row.sla_due_at ? `截止 ${dayjs(row.sla_due_at).format('MM-DD HH:mm')}` : '待处理', urgent: !!row.sla_due_at && dayjs(row.sla_due_at).isBefore(dayjs()) })
  }
  for (const row of data?.this_week_documents ?? []) if (!seen.has(`${row.project_id}:${row.id}`)) {
    todos.push({ key: `week:${row.project_id}:${row.id}`, kind: '资料', title: docLink(row), meta: `${row.project_name} · 本周待交`,
      due: `${deadlineLabel(row.due_at, row.timezone ?? 'Asia/Shanghai')}${row.due_is_estimated ? '（预计）' : ''}` })
  }
  if (planReadable) for (const row of plan!.unknown_items ?? []) todos.push({ key: `unknown:${row.id}`, kind: '周计划', title: <Link to={row.url}>{row.name}</Link>, meta: `${row.project_name} · 计划周 ${row.week_start}`, due: '完成情况待核对' })
  for (const project of projects) if (project.next_signoff) {
    const row = { ...project.next_signoff, project_id: project.id, project_name: project.name }
    todos.push({ key: `sign:${project.id}:${row.id}`, kind: '签单', title: docLink(row), meta: `${project.name} · 下一张待交签单`, due: '待提交' })
  }
  const counts = Object.fromEntries(KINDS.map(entry => [entry, todos.filter(row => row.kind === entry).length])) as Record<Kind, number>
  const filtered = kind === '全部' ? todos : todos.filter(row => row.kind === kind)
  const visible = showAll ? filtered : filtered.slice(0, PAGE)
  const unread = [
    !planReadable && '本周计划暂不可读取，可重试或到项目计划中查看。',
    !overdueReadable && '逾期资料尚未完整读取。',
    !signoffReadable && '签单状态尚未完整读取。',
    current?.issuesError && '问题尚未读取。',
  ].filter(Boolean) as string[]
  const allRead = !unread.length

  const today = dayjs()
  const monday = today.subtract((today.day() + 6) % 7, 'day')
  return <div className="workbench">
    <WorkPageHeader title="工作台" description={`${today.format('M 月 D 日')} · 本周 ${monday.format('M/D')} – ${monday.add(6, 'day').format('M/D')}`}
      tools={canWorkspace && <RefreshAction loading={loading} onClick={load} />} />
    {current?.error && <Alert type="error" showIcon message="工作台暂不可读取" description={current.error} action={<Button onClick={() => void load()}>重试读取</Button>} style={{ marginBottom: 16 }} />}
    {loading && !data && canWorkspace && <Spin aria-label="正在读取工作台" />}
    <div className="workbench-grid">
      {canWorkspace && data && <section className="workbench-card workbench-todo" aria-labelledby="workbench-todo-title">
        <div className="workbench-card-head">
          <h2 id="workbench-todo-title">需要处理 <span className="workbench-count">{todos.length}</span></h2>
          <div className="workbench-chips" role="group" aria-label="按类型筛选">
            {(['全部', ...KINDS] as const).map(entry => <button key={entry} type="button" aria-pressed={kind === entry} onClick={() => { setKind(entry); setShowAll(false) }}>
              {entry} {entry === '全部' ? todos.length : counts[entry]}
            </button>)}
          </div>
        </div>
        {unread.map(text => <Alert key={text} type="info" showIcon message={text} className="workbench-unread" />)}
        {visible.length ? <ul className="workbench-todo-list">{visible.map(row => <li key={row.key} className={row.urgent ? 'is-urgent' : ''}>
          <span className={`workbench-kind workbench-kind--${KINDS.indexOf(row.kind)}`}>{row.kind}</span>
          <span className="workbench-todo-main">{row.title}<small>{row.meta}</small></span>
          <span className="workbench-todo-due">{row.due}</span>
        </li>)}</ul>
          : allRead ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={kind === '全部' ? '暂无需要处理的事项' : `暂无${kind}待处理`} /> : null}
        {filtered.length > PAGE && <div className="workbench-todo-foot"><Button type="link" onClick={() => setShowAll(value => !value)}>{showAll ? '收起' : `显示全部 ${filtered.length} 项`}</Button></div>}
      </section>}
      {canWeek && user?.id && <MyWeek account={user.id} />}
      {canWorkspace && data && <section className="workbench-card workbench-projects" aria-labelledby="workbench-projects-title">
        <div className="workbench-card-head"><h2 id="workbench-projects-title">我的项目</h2><Link to="/pm/projects">全部项目</Link></div>
        <Table rowKey="id" size="small" scroll={{ x: 560 }} dataSource={projects} pagination={projects.length > 10 ? { pageSize: 10 } : false} columns={[
          { title: '项目', render: (_, row) => <Link to={`/pm/projects/${encodeURIComponent(row.id)}/overview`}>{row.name}</Link> },
          { title: '状态', render: (_, row) => { const status = projectStatusMeta(row.status); return <Tag color={status.color}>{status.label}</Tag> } },
          { title: '车辆进度', render: (_, row) => <VehicleProgressSummary value={row.vehicle_progress} /> },
          { title: '逾期资料', render: (_, row) => !row.document_attention ? <Typography.Text type="secondary">未读取</Typography.Text> : row.document_attention.overdue_count ? <Link className="dashboard-overdue-link" to={`/pm/projects/${encodeURIComponent(row.id)}/documents?filter=overdue`}>{row.document_attention.overdue_count} 项</Link> : <Typography.Text type="secondary">—</Typography.Text> },
        ]} />
      </section>}
    </div>
    {canStatistics && <div id="statistics" className="workbench-statistics"><Collapse defaultActiveKey={!canWorkspace || location.hash === '#statistics' ? ['statistics'] : []} items={[{ key: 'statistics', label: '统计', children: <Suspense fallback={<Spin aria-label="正在加载统计" />}><WorkspaceStatistics /></Suspense> }]} /></div>}
  </div>
}
