import { planWarningText, type WeeklyPlanSummary } from '../../../api/weeklyPlans'
import CompletionReview from './CompletionReview'
import ProjectEventsTimeline from '../../../components/ProjectEventsTimeline'
import { ProjectCapabilitiesContext, useProjectWriteBlocked } from '../../../hooks/useProjectCapability'
import { useContext, useEffect, useRef, useState } from 'react'
import {
  Card, Progress, Typography, Skeleton, Dropdown, message, Alert,
  Modal, Button, Input, Collapse, Space,
} from 'antd'
import {
  DownOutlined, PlayCircleOutlined, RightOutlined,
} from '@ant-design/icons'
import LazyChart from '../../../components/LazyChart'
import { api } from '../../../api/client'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../../stores/auth'
import { projectStageGuidance, projectWorkflow } from './projectWorkflow'
import { STATUS_LABEL, isProjectStatus, projectStatusMeta } from '../../../constants/status'
import { entryReady } from '../../../utils/projectPreparations'
import AcceptanceDecision, { type AcceptanceSummary } from '../../../components/AcceptanceDecision'
import type { DocumentAttention } from '../../../api/projectDocuments'
import { deadlineLabel } from '../../../utils/documentDeadlines'
import type { UnitQuantity } from '../../../utils/quantities'
import { formatDateTime } from '../../../utils/date'
import { formatAuditDetail } from '../../../utils/auditDetail'
import ContextTip from '../../../components/ContextTip'
import './OverviewPage.css'

const STATUS_FLOW: Record<string, string[]> = {
  preparing: ['executing'], executing: ['preparing', 'acceptance'],
  acceptance: ['executing', 'completed'], completed: ['acceptance', 'archived'], archived: ['completed'],
}
const SUSPENDABLE_STATUSES = ['preparing', 'executing', 'acceptance']

/** Project status remains a management decision; the work tree organizes its readable evidence. */
export default function OverviewPage({ projectId, projectStatus, projectSuspension = null, infoComplete, vehicleTotal = 0, memberCount = 0, canManageStatus = false, canArchive = true, onStatusChange }: {
  projectId: string; projectStatus: string; projectSuspension?: any; infoComplete?: boolean; vehicleTotal?: number; memberCount?: number; canManageStatus?: boolean; canArchive?: boolean; onStatusChange?: () => void
}) {
  const { user } = useAuth()
  const eventWriteBlocked = useProjectWriteBlocked(projectStatus)
  const eventCapabilities = useContext(ProjectCapabilitiesContext)
  const fieldStaff = useContext(ProjectCapabilitiesContext) === undefined && ['worker', 'intern'].includes(user?.role ?? '')
  const [data, setData] = useState<any>(null)
  const [dataOpen, setDataOpen] = useState(false)
  const [reviewOpen, setReviewOpen] = useState(false)
  const [eventState, setEventState] = useState<any>()
  const [timeline, setTimeline] = useState<any[]>([])
  const [overdue, setOverdue] = useState<any[]>([])
  const [issues, setIssues] = useState<any[]>([])
  const [documentActions, setDocumentActions] = useState<DocumentAttention | null>(null)
  const [documentProgress, setDocumentProgress] = useState<{ pending: number; submitted: number; waived: number; required_pending: number; total: number; phase4_ready?: boolean } | null>(null)
  const [recentLogs, setRecentLogs] = useState<any[]>([])
  // 项目准备摘要（准备 Tab 联动）
  const [prep, setPrep] = useState<any>(null)
  const [weeklyPlan, setWeeklyPlan] = useState<WeeklyPlanSummary | null>(null)
  const [taskCount, setTaskCount] = useState(0)
  const [unlinkedVehicleWorkCount, setUnlinkedVehicleWorkCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const [loadAttempt, setLoadAttempt] = useState(0)
  // C8-3：归档复盘弹窗
  const [archiveModal, setArchiveModal] = useState(false)
  const [retrospectiveText, setRetrospectiveText] = useState('')
  // HYPE-71：突发停工弹窗（原因必填）
  const [suspendOpen, setSuspendOpen] = useState(false)
  const [suspendReason, setSuspendReason] = useState('')
  const navigate = useNavigate()
  const statusLock = useRef(false)
  const [changingStatus, setChangingStatus] = useState(false)
  const [milestoneTarget, setMilestoneTarget] = useState<string | null>(null)
  const [statusReason, setStatusReason] = useState('')
  const [statusFailure, setStatusFailure] = useState<{ target: string; message: string } | null>(null)
  const [acceptanceSummary, setAcceptanceSummary] = useState<AcceptanceSummary | undefined>()

  useEffect(() => {
    const controller = new AbortController()
    const load = async () => {
      setLoading(true)
      setLoadError(false)
      try {
        const { data: overview } = await api.get(`/projects/${projectId}/overview`, { signal: controller.signal })
        if (controller.signal.aborted) return
        setData(overview.progress)
        setTimeline(overview.timeline)
        setEventState(overview.project_events ?? { events: [] })
        setOverdue(overview.overdue.items)
        setIssues(overview.issues)
        setDocumentProgress(overview.document_progress ?? null)
        setDocumentActions(overview.document_actions ?? null)
        setRecentLogs((overview.logs ?? []).slice(0, 5))
        setPrep(overview.preparations?.summary ?? null)
        setAcceptanceSummary(overview.acceptance_summary)
        setWeeklyPlan(overview.weekly_plans ?? null)
        const projectTasks = (overview.tree ?? []).filter((phase: any) => phase.name !== '项目准备').flatMap((phase: any) => phase.work_items ?? (phase.modules ?? []).flatMap((module: any) => module.tasks ?? []))
        setTaskCount(projectTasks.length)
        setUnlinkedVehicleWorkCount(projectTasks.filter((task: any) => (task.kind === 'vehicle' || task.quantity_type === 'per_vehicle') && !task.vehicle_step_key).length)
      } catch {
        if (!controller.signal.aborted) setLoadError(true)
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    load()
    return () => controller.abort()
  }, [projectId, projectStatus, loadAttempt])

  useEffect(() => { setReviewOpen(false); setDataOpen(false); setStatusFailure(null); setMilestoneTarget(null); setArchiveModal(false); setSuspendOpen(false) }, [projectId, projectStatus])

  if (loading) {
    return (
      <div>
        <Skeleton active paragraph={{ rows: 1 }} style={{ marginBottom: 16 }} />
        <Card style={{ marginBottom: 16 }}>
          <Skeleton active paragraph={{ rows: 3 }} />
        </Card>
        <Card>
          <Skeleton active paragraph={{ rows: 4 }} />
        </Card>
      </div>
    )
  }

  if (loadError) {
    return <Alert type="error" showIcon message="项目总览加载失败" description="请检查网络并重试。" action={<Button onClick={() => setLoadAttempt((n) => n + 1)}>重新加载</Button>} />
  }

  const changeStatus = async (s: string, retrospective?: string, reason?: string) => {
    if (statusLock.current || !canManageStatus || !isProjectStatus(projectStatus) || (s === 'archived' && !canArchive)) return
    // C8-3：归档必须填写项目复盘，未填则弹窗收集后再提交
    if (s === 'archived' && retrospective === undefined) {
      setRetrospectiveText('')
      setStatusFailure(null)
      setArchiveModal(true)
      return
    }
    statusLock.current = true
    setChangingStatus(true)
    setStatusFailure(null)
    try {
      const r = await api.post(`/projects/${projectId}/status`, {
        status: s,
        retrospective: retrospective ?? '',
        reason: reason ?? '',
      })
      const warnings: string[] = r.data?.warnings ?? []
      if (r.data?.requires_confirmation) {
        setStatusFailure({ target: s, message: [...warnings, '请到资料清单核对发车前资料；条件未满足时，必须明确批准风险进场并填写理由。'].join('；') })
      } else {
        setMilestoneTarget(null); setArchiveModal(false); setSuspendOpen(false)
        message.success(`状态已更新为「${STATUS_LABEL[s]}」`)
        onStatusChange?.()
      }
    } catch (e: any) {
      const detail = e.response?.data?.detail
      setStatusFailure({ target: s, message: typeof detail === 'string' ? detail : detail?.message ?? '状态切换失败，请检查网络后重试；当前项目阶段未确认改变。' })
    } finally {
      statusLock.current = false
      setChangingStatus(false)
    }
  }

  const phases: any[] = data?.phases ?? []
  const currentPhase = phases.find((p) => p.percent < 100)
  const openIssues = issues.filter((i) => !['closed', 'cancelled'].includes(i.status))
  const allowedNext = canManageStatus ? (STATUS_FLOW[projectStatus] ?? []).filter(status => status !== 'archived' || canArchive) : []
  const prepOverdue = prep?.overdue ?? 0
  const prepBlocked = prep?.blocked ?? 0
  const draftPlans = weeklyPlan?.draft_count ?? null
  const weeklyWarnings = (weeklyPlan?.warnings??[]).map(planWarningText)
  const severeIssueCount = openIssues.filter((i) => i.severity === 'critical' || i.severity === 'high').length
  const workflow = projectWorkflow({
    status: projectStatus, infoComplete, vehicles: vehicleTotal, tasks: taskCount,
    members: memberCount, plans: weeklyPlan?.total ?? null, drafts: draftPlans,
    unassigned: weeklyPlan?.unassigned_count ?? null, planWarnings: weeklyPlan?.warning_count,
    kickoffReady: documentProgress?.phase4_ready, prepReady: entryReady(prep), severeIssues: severeIssueCount, progress: data?.percent ?? 0,
  })
  const nextAction = fieldStaff && workflow.setup && workflow.action.path !== '/issues'
    ? { title: '查看执行安排', description: '项目处于准备阶段。查看已发布的周计划，有现场问题可随时上报。', path: '/plan?view=weeks', status: undefined }
    : workflow.action
  const actionDescription = nextAction.path.includes('step=schedule') && !nextAction.status
    ? '核对每周工作、车辆范围和负责人，再发布周计划。'
    : nextAction.description
  const stageGuidance = projectStageGuidance(projectStatus)

  const chartOption = {
    tooltip: { trigger: 'axis' },
    legend: { data: ['本周计划环节', '本周实际环节'] },
    grid: { left: 40, right: 20, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: timeline.map((t) => t.date.slice(5)) },
    yAxis: { type: 'value', name: '车辆环节数', minInterval: 1 },
    series: [
      {
        name: '本周计划环节',
        type: 'line',
        data: timeline.map((t) => t.plan_available === false ? null : t.planned),
        smooth: true,
        lineStyle: { color: '#999', type: 'dashed' },
        itemStyle: { color: '#999' },
      },
      {
        name: '本周实际环节',
        type: 'line',
        data: timeline.map((t) => t.actual),
        smooth: true,
        areaStyle: { opacity: 0.1 },
        lineStyle: { color: '#1677ff', width: 2 },
        itemStyle: { color: '#1677ff' },
      },
    ],
  }

  const go = (path: string) => navigate(`/pm/projects/${projectId}${({ '/archive': '/documents?acceptance=1', '/preparation': '/documents?review=1', '/files': '/documents', '/delivery': '/documents' } as Record<string, string>)[path] ?? path}`)
  const milestoneNext: Record<string, string> = { executing: 'acceptance' }
  // 每次人工推进都先确认；归档另有复盘弹窗。
  const requestStatus = (status: string) => {
    if (status === 'archived') { changeStatus(status); return }
    setStatusFailure(null); setStatusReason(''); setMilestoneTarget(status)
  }
  const failureLinks = statusFailure?.target === 'executing'
    ? [{ path: '/documents?stage=4', label: '查看准备资料' }, { path: '/documents?review=1', label: '查看发车前资料确认' }]
    : statusFailure?.target === 'acceptance' ? [{ path: '/documents?stage=6', label: '查看签单资料' }]
    : ['completed', 'archived'].includes(statusFailure?.target ?? '')
      ? [{ path: '/documents?acceptance=1', label: '核对验收与归档' }, { path: '/plan', label: '核对任务与质量' }, { path: '/documents', label: '核对必需资料' }, { path: '/issues', label: '处理未解决问题' }]
      : []
  const failureAlert = statusFailure && <Alert type="error" showIcon message="项目阶段尚未更新" description={statusFailure.message}
    action={<Space wrap>{failureLinks.length ? failureLinks.map(link => <Button key={link.path} onClick={() => { setMilestoneTarget(null); setArchiveModal(false); setSuspendOpen(false); go(link.path) }}>{link.label}</Button>)
      : <Button onClick={() => { setMilestoneTarget(null); setArchiveModal(false); setSuspendOpen(false); setStatusFailure(null); setLoadAttempt(value => value + 1) }}>重新查看项目</Button>}</Space>} />
  const statusItems = [
    ...allowedNext.map((status) => ({ key: status, label: `${status === milestoneNext[projectStatus] ? '确认进入' : '切换到'}「${STATUS_LABEL[status]}」`, onClick: () => requestStatus(status) })),
    ...(canManageStatus && SUSPENDABLE_STATUSES.includes(projectStatus) ? [{ key: 'suspend', label: '突发停工', danger: true, onClick: () => { setSuspendReason(''); setSuspendOpen(true) } }] : []),
  ]
  const link = (title: string, path: string, detail?: string, urgent = false) => <a
    className={`overview-tree-link${urgent ? ' is-urgent' : ''}`} href={`/pm/projects/${projectId}${path}`}
    onClick={event => { if (event.button !== 0 || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return; event.preventDefault(); go(path) }}>
    <span><strong>{title}</strong>{detail && <small>{detail}</small>}</span><RightOutlined aria-hidden="true" />
  </a>
  const count = (title: string, value: number | null, path: string, urgent = false) => <a className={`overview-side-count${urgent ? ' is-urgent' : ''}`} href={`/pm/projects/${projectId}${path}`}
    onClick={event => { if (event.button !== 0 || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return; event.preventDefault(); go(path) }}>
    <span>{title}</span><strong>{value ?? '未读取'}</strong>
  </a>
  const checklist = projectStatus === 'preparing' && !fieldStaff ? workflow.checklist : null
  const pendingSteps = checklist ? checklist.filter(item => !item.done).length : 0
  const groups: UnitQuantity[] = data?.quantities_by_unit ?? []
  const quantity = (value: number) => Number(value.toFixed(3))
  const scheduleDetail = !weeklyPlan ? '周计划尚未读取' : `${weeklyPlan.total} 格周计划，${weeklyPlan.published_count} 格已发布${draftPlans===null?'':`，${draftPlans} 格草稿`}`
  const overdueFirst = overdue[0]
  const overdueDetail = overdueFirst ? [overdueFirst.code, overdueFirst.name, deadlineLabel(overdueFirst.due_at, documentActions?.timezone || 'Asia/Shanghai'), overdueFirst.effective_owner_name].filter(Boolean).join(' · ') : ''
  const preparationDetail = entryReady(prep) ? '发车前资料已确认' : [
    prepBlocked ? `${prepBlocked} 项发车前资料待落实` : '核对第5阶段必需资料',
    prepOverdue ? `${prepOverdue} 项准备已逾期` : '',
  ].filter(Boolean).join(' · ')
  const deliveryDetail = documentProgress ? `${documentProgress.pending} 项资料待提交${documentProgress.required_pending ? `，其中 ${documentProgress.required_pending} 项必需` : ''}` : '资料状态待核对'

  return (
    <div className="project-overview-tree overview-work-page">
      <CompletionReview key={projectId} projectId={projectId} target={projectStatus === 'completed' ? 'archived' : 'completed'} open={reviewOpen} onClose={() => setReviewOpen(false)} />
      {statusFailure && !archiveModal && !milestoneTarget && !suspendOpen && failureAlert}
      {projectStatus === 'suspended' && <Alert type="warning" showIcon message="项目已停工" description={projectSuspension?.reason || '请联系项目负责人了解恢复安排。'} />}
      <section className="overview-tree-status" aria-label="当前行动">
        <div className="overview-current-context"><div className="overview-current-status"><span>当前项目状态</span><strong>{projectStatusMeta(projectStatus).label}</strong></div>
          <p>{projectStatus === 'suspended' && canManageStatus ? '处理停工原因后恢复原状态，现场实施仍需核对进场条件。' : actionDescription}</p>
          {stageGuidance && !fieldStaff && <span className="overview-next-state">{stageGuidance.next ? `下一项目状态：${STATUS_LABEL[stageGuidance.next]}` : '项目状态说明'}
            <ContextTip id="project-lifecycle" title="项目怎么推进"><p>{stageGuidance.description}</p><p>发车前资料确认的就绪状态单独跟踪；完成与归档仍会检查当前证据。</p>{!canManageStatus && <p>由有权限的负责人确认项目状态，你可以查阅相关资料。</p>}</ContextTip>
          </span>}
        </div>
        <div className="overview-status-actions">
        <Button type="primary" loading={changingStatus} disabled={projectStatus === 'suspended' && canManageStatus && !projectSuspension?.status_before}
          icon={projectStatus === 'suspended' && canManageStatus ? <PlayCircleOutlined aria-hidden="true" /> : undefined}
          onClick={() => projectStatus === 'suspended' && canManageStatus ? changeStatus(projectSuspension.status_before) : nextAction.status && canManageStatus ? requestStatus(nextAction.status) : go(nextAction.path)}>
          {projectStatus === 'suspended' && canManageStatus ? '恢复项目' : nextAction.status && !canManageStatus ? '查看准备情况' : nextAction.title}<RightOutlined aria-hidden="true" />
        </Button>
        {stageGuidance && !fieldStaff && canManageStatus && stageGuidance.next && (stageGuidance.next !== 'archived' || canArchive) && stageGuidance.next !== nextAction.status && <Button loading={changingStatus} onClick={() => requestStatus(stageGuidance.next!)}>推进至「{STATUS_LABEL[stageGuidance.next]}」</Button>}
        <Button onClick={() => setReviewOpen(true)}>{projectStatus === 'completed' ? '归档前核对' : '完成前核对'}</Button>
        {statusItems.length > 0 && <Dropdown trigger={['click']} menu={{ items: statusItems }}><Button loading={changingStatus}>调整项目状态 <DownOutlined /></Button></Dropdown>}
        </div>
      </section>

      <div className="overview-layout">
        <div className="overview-main">
          <section className="overview-next-work overview-card" aria-label="待处理工作">
            <h2>{checklist ? (pendingSteps ? `进入「现场实施」还差 ${pendingSteps} 项` : '准备清单已全部核对') : '现在要处理'}</h2>
            {checklist && <ol aria-label="准备清单" className="overview-checklist">{checklist.map(item => <li key={item.title} className={item.done ? 'is-done' : ''}>
              <span className="overview-check-mark" aria-hidden="true">{item.done ? '✓' : '!'}</span>
              <span className="overview-check-copy"><Button type="link" onClick={() => go(item.path)}>{item.title}</Button><small>{item.path === '/documents?review=1' && !entryReady(prep) ? preparationDetail : item.description}</small></span>
              <span className="overview-check-state">{item.done ? '已核对' : '待核对'}</span>
            </li>)}</ol>}
            <div className="overview-work-cards overview-work-list">
              {openIssues.length > 0 && link('现场问题', '/issues', `${openIssues.length} 个问题待处理${severeIssueCount ? `，其中 ${severeIssueCount} 个优先处理` : ''}`, severeIssueCount > 0)}
              {overdue.length > 0 && link(`${overdue.length} 项资料已逾期`, '/documents', overdueDetail, true)}
              {!fieldStaff && !checklist && workflow.setup && !entryReady(prep) && link('发车前资料确认', '/documents?review=1', preparationDetail, prepBlocked > 0)}
              {!fieldStaff && (!taskCount || unlinkedVehicleWorkCount > 0) && link('工作项范围待确认', '/plan', !taskCount ? '确认项目阶段与工作项范围' : `${unlinkedVehicleWorkCount} 项车辆工作尚未明确关联真实进度环节`)}
              {!checklist && (workflow.setup || (draftPlans??0)>0 || (weeklyPlan?.warning_count??0)>0) && link('周计划', '/plan?view=weeks', [scheduleDetail,...weeklyWarnings].join('；'))}
              {!!documentActions?.this_week_count && link('本周待交资料', '/documents?filter=week', `${documentActions.this_week_count} 项资料本周截止，按现场时区 ${documentActions.timezone}`)}
              {!checklist && (documentProgress === null || documentProgress.pending > 0) && link('项目资料', '/documents', deliveryDetail)}
              {!workflow.setup && !overdue.length && !openIssues.length && documentProgress !== null && !documentProgress.pending && link('查看周计划', '/plan?view=weeks', '查看已发布的工作和实际完成情况')}
            </div>
          </section>
          <ProjectEventsTimeline key={projectId} projectId={projectId} initialData={eventState} canEdit={!eventWriteBlocked && (eventCapabilities ? eventCapabilities.includes('project.update') : canManageStatus && user?.role !== 'director')} onChanged={onStatusChange} />
          {acceptanceSummary && ['acceptance', 'completed', 'archived'].includes(projectStatus) && <section className="overview-acceptance-summary overview-card" aria-label="当前验收情况">
            <h2>验收情况</h2><AcceptanceDecision summary={acceptanceSummary} />{link('查看验收与复盘', '/documents?acceptance=1')}
          </section>}
        </div>
        <aside className="overview-side" aria-label="项目概要">
          <section className="overview-card overview-side-progress">
            <h2>进度</h2>
            <div className="overview-side-metric"><span>总进度</span><strong>{data?.progress_known === false ? '未知（数量待补）' : `${data?.percent ?? 0}%`}</strong></div>
            <Progress percent={data?.percent ?? 0} showInfo={false} aria-label="项目概况进度" strokeColor="var(--agv-primary)" />
            {currentPhase && <p className="overview-side-note">待完成阶段：{currentPhase.name}</p>}
            <button type="button" className="overview-side-toggle" aria-expanded={dataOpen} aria-controls={`overview-evidence-${projectId}`} onClick={() => setDataOpen(value => !value)}>进度与记录 <RightOutlined aria-hidden="true" rotate={dataOpen ? 90 : 0} /></button>
          </section>
          <section className="overview-card overview-side-counts">
            <h2>待处理</h2>
            {count('未解决问题', openIssues.length, '/issues', severeIssueCount > 0)}
            {count('待提交资料', documentProgress?.pending ?? null, '/documents')}
            {count('逾期资料', overdue.length, '/documents', overdue.length > 0)}
            {!fieldStaff && count('项目成员', memberCount, '/team')}
          </section>
          {!fieldStaff && recentLogs.length > 0 && <section className="overview-card overview-side-logs">
            <h2>最近记录</h2>
            {recentLogs.slice(0, 3).map((log: any) => <div key={log.id}><span>{formatAuditDetail(log.detail)}</span><small>{log.operator_name || '系统'} · {log.created_at ? formatDateTime(log.created_at) : ''}</small></div>)}
            <Button type="link" onClick={() => go('/activity')}>全部记录</Button>
          </section>}
        </aside>
      </div>
      {dataOpen && <div id={`overview-evidence-${projectId}`} className="overview-evidence-panel" aria-label="进度明细与记录">
        <h2>进度明细</h2>
            <div className="overview-tree-data">
              <div className="overview-tree-progress">
                <span>项目总进度（含确认完成）</span><strong>{data?.percent ?? 0}<small>%</small></strong>
                <Progress percent={data?.percent ?? 0} showInfo={false} aria-label="项目总进度" strokeColor="var(--agv-primary)" />
                <div className="overview-tree-progress-foot"><span>{currentPhase ? `待完成任务阶段：${currentPhase.name}` : phases.length ? '各任务阶段数量进度已达标' : '尚未配置实施任务'}</span>
                  <ContextTip id="project-progress" title="进度与项目状态"><p>每台车的每个环节和每项非车辆工作等权计数。任务阶段是工作分组，项目状态由有权限的人确认；环节完成不会自动进入联调、试运行或验收。</p></ContextTip>
                </div>
              </div>
              <div className="overview-tree-quantity"><span>实际填报 / 目标</span>
                {groups.length ? <ul aria-label="各单位数量">{groups.map(group => <li key={group.unit}><span>{group.unit}</span><strong>{quantity(group.completed)} / {quantity(group.target)}</strong></li>)}</ul>
                  : <p>暂无分单位数量</p>}
              </div>
            </div>
            <Collapse className="overview-tree-details" expandIcon={({ isActive }) => <RightOutlined aria-hidden="true" rotate={isActive ? 90 : 0} />} items={[
              { key: 'more', label: fieldStaff ? '阶段与趋势' : '阶段进度与记录', children: <Collapse className="overview-tree-details-inner" expandIcon={({ isActive }) => <RightOutlined aria-hidden="true" rotate={isActive ? 90 : 0} />} items={[
                { key: 'phases', label: '任务阶段进度', children: phases.length ? <Collapse className="overview-tree-phases" expandIcon={({ isActive }) => <RightOutlined aria-hidden="true" rotate={isActive ? 90 : 0} />} items={phases.map((phase, index) => ({
                  key: phase.id || `${index}`, label: phase.name, extra: <span>{phase.percent}%</span>,
                  children: <div className="overview-tree-phase-content"><Progress percent={phase.percent} size="small" aria-label={`${phase.name}数量进度`} />
                    <Collapse className="overview-tree-modules" expandIcon={({ isActive }) => <RightOutlined aria-hidden="true" rotate={isActive ? 90 : 0} />} items={(phase.modules ?? []).map((module: any, moduleIndex: number) => ({
                      key: module.id || `${moduleIndex}`, label: module.name, extra: <span>{module.percent}%</span>,
                      children: <div><Progress percent={module.percent} size="small" aria-label={`${module.name}数量进度`} />
                        <ul className="overview-tree-tasks">{(module.tasks ?? []).map((task: any) => <li key={task.id || task.name}>
                          {fieldStaff ? <div className="overview-tree-task-text"><strong>{task.name}</strong><small>数量进度 {task.percent}%</small></div>
                            : link(task.name, `/plan?task=${encodeURIComponent(task.id)}`, `数量进度 ${task.percent}%`)}
                        </li>)}</ul>
                      </div>,
                    }))} />
                    {!fieldStaff && link('查看任务', '/plan')}
                  </div>,
                }))} /> : <Typography.Text type="secondary">尚未配置实施任务。</Typography.Text> },
                { key: 'trend', label: '进度趋势', children: <>{timeline.length > 0 && timeline.every(t => t.plan_available === false) && <Alert type="info" message="尚未配置车辆环节周计划，计划曲线暂显示未知" />}<LazyChart option={chartOption} style={{ height: 260 }} /></> },
                ...(!fieldStaff ? [{ key: 'activity', label: '最近动态', children: <div className="overview-tree-logs">
                  {recentLogs.length ? recentLogs.map((log: any) => <div key={log.id}><span>{formatAuditDetail(log.detail)}</span><small>{log.operator_name || '系统'} · {log.created_at ? formatDateTime(log.created_at) : ''}</small></div>) : <Typography.Text type="secondary">还没有项目动态。</Typography.Text>}
                  {link('查看操作记录', '/activity')}
                </div> }] : []),
              ]} /> },
            ]} />
      </div>}

      {/* C8-3：归档前填写项目复盘 */}
      <Modal title={milestoneTarget ? `确认进入「${STATUS_LABEL[milestoneTarget]}」` : '确认项目阶段'} open={!!milestoneTarget}
        onCancel={() => { if (!changingStatus) { setMilestoneTarget(null); setStatusFailure(null) } }}
        onOk={() => { if (milestoneTarget) changeStatus(milestoneTarget, undefined, statusReason.trim()) }} okText="确认推进阶段" cancelText="取消" confirmLoading={changingStatus}
        cancelButtonProps={{ disabled: changingStatus }} closable={!changingStatus} maskClosable={false}>
        <Typography.Paragraph>项目状态将从「{STATUS_LABEL[projectStatus] ?? projectStatus}」变为「{milestoneTarget ? STATUS_LABEL[milestoneTarget] : ''}」，变更会记入项目记录。</Typography.Paragraph>
        {milestoneTarget === milestoneNext[projectStatus] && <Typography.Paragraph>请核对现场实际情况后确认。当前进度 {data?.percent ?? 0}% 仅供参考，不会自动推进阶段；录入验收记录也不会自动标记项目完成。</Typography.Paragraph>}
        <Input.TextArea aria-label="状态变更说明" rows={2} maxLength={5000} value={statusReason} onChange={event => setStatusReason(event.target.value)} placeholder="说明（可选）：如资料已齐、客户确认进场等" disabled={changingStatus} />
        {failureAlert}
      </Modal>

      <Modal
        title="归档项目复盘"
        open={archiveModal}
        onCancel={() => { if (!changingStatus) setArchiveModal(false) }}
        okText="确认归档"
        confirmLoading={changingStatus}
        cancelButtonProps={{ disabled: changingStatus }}
        okButtonProps={{ disabled: !canArchive || !canManageStatus || retrospectiveText.trim().length < 5 }}
        onOk={() => {
          changeStatus('archived', retrospectiveText.trim())
        }}
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          归档后业务记录只读；需要纠正时可由有权限的人恢复项目。请简要填写复盘（成功经验、问题教训、改进建议，至少 5 字），
          内容将存入项目记录供后续参考。
        </Typography.Paragraph>
        {failureAlert}
        <Input.TextArea
          rows={4}
          maxLength={2000}
          value={retrospectiveText}
          onChange={(e) => setRetrospectiveText(e.target.value)}
          placeholder="例如：本次项目在点位表确认环节耗时偏长，下次建议提前两周与客户对齐……"
        />
      </Modal>

      {/* HYPE-71：突发停工（原因必填，服务端强制） */}
      <Modal
        title="突发停工"
        open={suspendOpen}
        onCancel={() => { if (!changingStatus) setSuspendOpen(false) }}
        okText="确认停工"
        confirmLoading={changingStatus}
        cancelButtonProps={{ disabled: changingStatus }}
        okButtonProps={{ danger: true, disabled: suspendReason.trim().length === 0 }}
        onOk={() => {
          changeStatus('suspended', undefined, suspendReason.trim())
        }}
      >
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="停工后暂停现场执行及进度填报，保留原项目阶段；由有权限的人确认恢复后继续。"
        />
        {failureAlert}
        <Input.TextArea
          rows={3}
          maxLength={500}
          value={suspendReason}
          onChange={(e) => setSuspendReason(e.target.value)}
          placeholder="请填写停工原因（必填）"
        />
      </Modal>

    </div>
  )
}
