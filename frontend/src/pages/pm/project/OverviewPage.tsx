import { PersonAvatar } from '../../../components/Person'
import { type WeeklyPlanSummary } from '../../../api/weeklyPlans'
import ProjectEventsTimeline from '../../../components/ProjectEventsTimeline'
import { ProjectCapabilitiesContext, useProjectWriteBlocked } from '../../../hooks/useProjectCapability'
import { useContext, useEffect, useRef, useState } from 'react'
import {
  Card, Progress, Typography, Skeleton, Dropdown, message, Alert,
  Modal, Button, Input, Space,
} from 'antd'
import {
  DownOutlined, PlayCircleOutlined, RightOutlined,
} from '@ant-design/icons'
import LazyChart from '../../../components/LazyChart'
import { api } from '../../../api/client'
import { useNavigate } from 'react-router-dom'
import { projectStageGuidance } from './projectWorkflow'
import { STATUS_LABEL, isProjectStatus, projectStatusMeta } from '../../../constants/status'
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
export default function OverviewPage({ projectId, projectStatus, projectSuspension = null, canManageStatus = false, canArchive = true, onStatusChange }: {
  projectId: string; projectStatus: string; projectSuspension?: any; canManageStatus?: boolean; canArchive?: boolean; onStatusChange?: () => void
}) {
  const eventWriteBlocked = useProjectWriteBlocked(projectStatus)
  const eventCapabilities = useContext(ProjectCapabilitiesContext)
  const [data, setData] = useState<any>(null)
  const [dataOpen, setDataOpen] = useState(false)
  const [eventState, setEventState] = useState<any>()
  const [timeline, setTimeline] = useState<any[]>([])
  const [overdue, setOverdue] = useState<any[]>([])
  const [issues, setIssues] = useState<any[]>([])
  const [documentActions, setDocumentActions] = useState<DocumentAttention | null>(null)
  const [documentProgress, setDocumentProgress] = useState<{ pending: number; submitted: number; waived: number; required_pending: number; total: number } | null>(null)
  const [recentLogs, setRecentLogs] = useState<any[]>([])
  const [weeklyPlan, setWeeklyPlan] = useState<WeeklyPlanSummary | null>(null)
  const [taskCount, setTaskCount] = useState(0)
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
        setAcceptanceSummary(overview.acceptance_summary)
        setWeeklyPlan(overview.weekly_plans ?? null)
        const projectTasks = (overview.tree ?? []).flatMap((phase: any) => phase.work_items ?? [])
        setTaskCount(projectTasks.length)
      } catch {
        if (!controller.signal.aborted) setLoadError(true)
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    load()
    return () => controller.abort()
  }, [projectId, projectStatus, loadAttempt])

  useEffect(() => { setDataOpen(false); setStatusFailure(null); setMilestoneTarget(null); setArchiveModal(false); setSuspendOpen(false) }, [projectId, projectStatus])

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
      await api.post(`/projects/${projectId}/status`, {
        status: s,
        retrospective: retrospective ?? '',
        reason: reason ?? '',
      })
      setMilestoneTarget(null); setArchiveModal(false); setSuspendOpen(false)
      message.success(`状态已更新为「${STATUS_LABEL[s]}」`)
      onStatusChange?.()
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

  const go = (path: string) => navigate(`/pm/projects/${projectId}${path}`)
  // 每次人工推进都先确认；归档另有复盘弹窗。
  const requestStatus = (status: string) => {
    if (status === 'archived') { changeStatus(status); return }
    setStatusFailure(null); setStatusReason(''); setMilestoneTarget(status)
  }
  const failureAlert = statusFailure && <Alert type="error" showIcon message="项目状态尚未更新" className="overview-failure"
    description={<><div>{statusFailure.message}</div><Space wrap className="overview-failure-actions">
      <Button onClick={() => { setMilestoneTarget(null); setArchiveModal(false); setSuspendOpen(false); setStatusFailure(null); setLoadAttempt(value => value + 1) }}>重新查看项目</Button></Space></>} />
  const pushTarget = stageGuidance && canManageStatus && stageGuidance.next && (stageGuidance.next !== 'archived' || canArchive) ? stageGuidance.next : null
  const statusItems = [
    ...allowedNext.filter(status => status !== pushTarget).map((status) => ({ key: status, label: `退回「${STATUS_LABEL[status]}」`, onClick: () => requestStatus(status) })),
    ...(canManageStatus && SUSPENDABLE_STATUSES.includes(projectStatus) ? [{ type: 'divider' as const }, { key: 'suspend', label: '突发停工', danger: true, onClick: () => { setSuspendReason(''); setSuspendOpen(true) } }] : []),
  ]
  const menuOf = (items: typeof statusItems) => items.some(item => 'label' in item) && <Dropdown trigger={['click']} menu={{ items }}><Button loading={changingStatus}>调整项目状态 <DownOutlined /></Button></Dropdown>
  const statusMenu = menuOf(statusItems)
  const link = (title: string, path: string, detail?: string, urgent = false) => <a
    className={`overview-tree-link${urgent ? ' is-urgent' : ''}`} href={`/pm/projects/${projectId}${path}`}
    onClick={event => { if (event.button !== 0 || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return; event.preventDefault(); go(path) }}>
    <span><strong>{title}</strong>{detail && <small>{detail}</small>}</span><RightOutlined aria-hidden="true" />
  </a>
  const groups: UnitQuantity[] = data?.quantities_by_unit ?? []
  const quantity = (value: number) => Number(value.toFixed(3))
  // Say what needs doing, not the bookkeeping.
  const scheduleDetail = !weeklyPlan ? '周计划尚未读取' : weeklyPlan.total ? `已安排 ${weeklyPlan.total} 格` : '还没有安排，可以按模板生成'
  const overdueFirst = overdue[0]
  const overdueDetail = overdueFirst ? [overdueFirst.code, overdueFirst.name, deadlineLabel(overdueFirst.due_at, documentActions?.timezone || 'Asia/Shanghai'), overdueFirst.effective_owner_name].filter(Boolean).join(' · ') : ''
  const deliveryDetail = documentProgress ? `${documentProgress.pending} 项资料待提交${documentProgress.required_pending ? `，其中 ${documentProgress.required_pending} 项必需` : ''}` : '资料状态待核对'

  return (
    <div className="project-overview-tree overview-work-page">
      {statusFailure && !archiveModal && !milestoneTarget && !suspendOpen && failureAlert}
      {projectStatus === 'suspended' && <Alert type="warning" showIcon message="项目已停工" description={projectSuspension?.reason || '请联系项目负责人了解恢复安排。'} />}
      <section className="overview-next" aria-label="项目状态">
        <div className="overview-next-copy">
          <span className="overview-next-kicker"><strong>{projectStatusMeta(projectStatus).label}</strong>{stageGuidance?.next && <span>下一步：{STATUS_LABEL[stageGuidance.next]}</span>}</span>
          <p>{stageGuidance?.description}</p>
        </div>
        {canManageStatus && <div className="overview-status-actions">
          {projectStatus === 'suspended'
            ? <Button type="primary" loading={changingStatus} disabled={!projectSuspension?.status_before} icon={<PlayCircleOutlined aria-hidden="true" />} onClick={() => changeStatus(projectSuspension.status_before)}>恢复项目</Button>
            : pushTarget && <Button type="primary" loading={changingStatus} onClick={() => requestStatus(pushTarget)}>推进到「{STATUS_LABEL[pushTarget]}」</Button>}
          {statusMenu}
        </div>}
      </section>

      <div className="overview-layout">
        <div className="overview-main">
          <section className="overview-next-work overview-card" aria-label="待处理工作">
            <div className="overview-card-head"><h2>现在要处理</h2></div>
            <div className="overview-work-cards overview-work-list">
              {openIssues.length > 0 && link('现场问题', '/issues', `${openIssues.length} 个问题未关闭`)}
              {overdue.length > 0 && link(`${overdue.length} 项资料已逾期`, '/documents', overdueDetail, true)}
              {!taskCount && link('还没有工作项', '/plan', '从模板带入或手动添加要做的工作')}
              {link('周计划', '/plan?view=weeks', scheduleDetail)}
              {!!documentActions?.this_week_count && link('本周待交资料', '/documents?filter=week', `${documentActions.this_week_count} 项资料本周截止，按现场时区 ${documentActions.timezone}`)}
              {(documentProgress === null || documentProgress.pending > 0) && link('项目资料', '/documents', deliveryDetail)}
            </div>
          </section>
          <ProjectEventsTimeline key={projectId} projectId={projectId} initialData={eventState} canEdit={!eventWriteBlocked && (eventCapabilities ? eventCapabilities.includes('project.update') : canManageStatus)} onChanged={onStatusChange} />
          {acceptanceSummary && ['acceptance', 'completed', 'archived'].includes(projectStatus) && <section className="overview-acceptance-summary overview-card" aria-label="当前验收情况">
            <h2>验收情况</h2><AcceptanceDecision summary={acceptanceSummary} />{link('查看验收与复盘', '/documents?acceptance=1')}
          </section>}
        </div>
        <aside className="overview-side" aria-label="项目概要">
          <section className="overview-card overview-side-progress">
            <h2>进度</h2>
            <div className="overview-side-metric"><span>总进度</span><strong>{data?.progress_known === false ? '—' : `${data?.percent ?? 0}%`}</strong></div>
            {data?.progress_known === false ? <p className="overview-side-note">车辆台数待补，进度暂不计算</p>
              : <Progress percent={data?.percent ?? 0} showInfo={false} aria-label="项目概况进度" strokeColor="var(--agv-primary)" />}
            {currentPhase && <p className="overview-side-note">下一个未完成分组：{currentPhase.name}</p>}
            <button type="button" className="overview-side-toggle" aria-expanded={dataOpen} aria-controls={`overview-evidence-${projectId}`} onClick={() => setDataOpen(value => !value)}>进度与记录 <RightOutlined aria-hidden="true" rotate={dataOpen ? 90 : 0} /></button>
          </section>
          {recentLogs.length > 0 && <section className="overview-card overview-side-logs">
            <h2>最近记录</h2>
            {recentLogs.slice(0, 3).map((log: any) => <div key={log.id} className="overview-log"><PersonAvatar name={log.operator_name || '系统'} /><span className="overview-log-copy"><span>{formatAuditDetail(log.detail)}</span><small>{log.operator_name || '系统'} · {log.created_at ? formatDateTime(log.created_at) : ''}</small></span></div>)}
            <Button type="link" onClick={() => go('/history')}>全部记录</Button>
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
            {/* Flat, no nested folding: group progress, trend, then recent activity. */}
            <h3 className="overview-evidence-title">各分组进度</h3>
            {phases.length ? <ul className="overview-phase-list" aria-label="各分组进度">{phases.map((phase, index) => <li key={phase.id || index}>
              <button type="button" className="task-name-link" onClick={() => go('/plan')}>{phase.name}</button>
              <Progress percent={phase.percent} size="small" showInfo={false} aria-label={`${phase.name}数量进度`} /><span className="overview-phase-percent">{phase.percent}%</span>
            </li>)}</ul> : <Typography.Text type="secondary">尚未配置实施任务。</Typography.Text>}
            <h3 className="overview-evidence-title">进度趋势</h3>
            {timeline.length > 0 && timeline.every(t => t.plan_available === false) && <Alert type="info" message="尚未配置车辆环节周计划，计划曲线暂显示未知" />}
            <LazyChart option={chartOption} style={{ height: 240 }} />
            {<><h3 className="overview-evidence-title">最近动态</h3><div className="overview-tree-logs">
              {recentLogs.length ? recentLogs.map((log: any) => <div key={log.id} className="overview-log"><PersonAvatar name={log.operator_name || '系统'} /><span className="overview-log-copy"><span>{formatAuditDetail(log.detail)}</span><small>{log.operator_name || '系统'} · {log.created_at ? formatDateTime(log.created_at) : ''}</small></span></div>) : <Typography.Text type="secondary">还没有项目动态。</Typography.Text>}
              {link('查看操作记录', '/history')}
            </div></>}
      </div>}

      {/* C8-3：归档前填写项目复盘 */}
      <Modal title={milestoneTarget ? `确认进入「${STATUS_LABEL[milestoneTarget]}」` : '确认项目阶段'} open={!!milestoneTarget}
        onCancel={() => { if (!changingStatus) { setMilestoneTarget(null); setStatusFailure(null) } }}
        onOk={() => { if (milestoneTarget) changeStatus(milestoneTarget, undefined, statusReason.trim()) }} okText="确认" cancelText="取消" confirmLoading={changingStatus}
        cancelButtonProps={{ disabled: changingStatus }} closable={!changingStatus} maskClosable={false}>
        <Typography.Paragraph>项目状态将从「{STATUS_LABEL[projectStatus] ?? projectStatus}」变为「{milestoneTarget ? STATUS_LABEL[milestoneTarget] : ''}」，变更会记入项目记录。</Typography.Paragraph>
        <Input.TextArea aria-label="状态变更说明" rows={2} maxLength={5000} value={statusReason} onChange={event => setStatusReason(event.target.value)} placeholder="说明（可选）" disabled={changingStatus} />
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
