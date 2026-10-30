import dayjs from 'dayjs'
import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Card, Collapse, DatePicker, Empty, Modal, Space, Tag, Typography, Upload } from 'antd'
import { Link } from 'react-router-dom'
import { fieldWeekApi, type Plan, type Week } from '../../api/fieldWeek'
import { errMsg } from '../../api/client'
import { projectDocumentsApi } from '../../api/projectDocuments'
import { isUploadQueued } from '../../uploads/types'
import FieldOperationModal, { type FieldTarget } from '../../components/FieldOperationModal'
import { WorkPageHeader } from '../../components/WorkPage'
import { useOfflineSync } from '../../offline/useOfflineSync'
import { useAuth } from '../../stores/auth'
import { ensureVerifiedAccount } from '../../utils/verifiedAccount'
import { hasSystemPermission } from '../../constants/systemPermissions'
import { canAccessNav } from '../../constants/nav'
import { deadlineLabel } from '../../utils/documentDeadlines'
import { ISSUE_STATUS_MAP } from '../../constants/issues'
import './worker.css'
import { RefreshAction } from '../../components/IconAction'

export default function WeekPage({ projectId = '' }: { projectId?: string }) {
  const { user } = useAuth(); const identity = `${user?.id}:${projectId}`; const active = useRef(identity); active.current = identity
  const generation = useRef(0); const [data, setData] = useState<Week>(); const [error, setError] = useState(''); const [loading, setLoading] = useState(false)
  const [week, setWeek] = useState<string>(); const [revision, setRevision] = useState(0); const [target, setTarget] = useState<FieldTarget>(); const [showAssist, setShowAssist] = useState(false)
  const [claiming, setClaiming] = useState<string>(); const [uploading, setUploading] = useState<Week['this_week_documents'][number]>(); const [file, setFile] = useState<File>(); const [uploadError, setUploadError] = useState(''); const [uploadBusy, setUploadBusy] = useState(false); const [eventDate, setEventDate] = useState('')
  const lock = useRef(false); const uploadLock = useRef(false)
  const { online, pendingCount, rejected, syncVersion, flush, retry, remove } = useOfflineSync()
  const canRecord = !!data?.permissions.record && hasSystemPermission(user, 'worker.report')
  const load = () => setRevision(value => value + 1)
  useEffect(() => {
    const request = ++generation.current; const owner = identity; setLoading(true); setData(undefined); setError(''); setTarget(undefined); setUploading(undefined)
    fieldWeekApi.week({ ...(week ? { week_start: week } : {}), ...(projectId ? { project_id: projectId } : {}) }, user?.id).then(value => { if (active.current === owner && request === generation.current) setData(value) }).catch(e => { if (active.current === owner && request === generation.current) setError(errMsg(e)) }).finally(() => { if (active.current === owner && request === generation.current) setLoading(false) })
    return () => { generation.current++ }
  }, [identity, week, revision, syncVersion])
  const claim = async (plan: Plan) => {
    if (lock.current) return
    lock.current = true; setClaiming(plan.id); const owner = identity
    try { ensureVerifiedAccount(user?.id); await fieldWeekApi.claim(plan, user!.id); if (active.current === owner) load() } catch (e) { if (active.current === owner) setError(errMsg(e)) } finally { lock.current = false; if (active.current === owner) setClaiming(undefined) }
  }
  const open = (plan: Plan, kind: FieldTarget['kind'], id: string, version: number, isDone: boolean, name: string, step = '', assist = false) => setTarget({ project_id: plan.project_id, kind, target_id: id, version, is_done: isDone, name, step_key: step, weekly_cell_id: plan.id, window: plan.date_window, ...(assist ? { assisted: plan.assignees } : {}) })
  const blockedReason = (plan: Plan) => canRecord && plan.can_record !== false ? '' : !canRecord ? '当前账号没有登记实际完成的权限，可联系项目负责人。'
    : !['executing', 'acceptance'].includes(String((plan as { project_status?: string }).project_status ?? '')) ? '项目进入「现场实施」后才能登记完成和检查；进场前可以提交资料、上报问题。'
    : '这项计划当前不能登记（项目只读或计划已调整），请刷新或联系项目负责人。'
  const planCard = (plan: Plan, assist = false) => {
    const recordBlocked = blockedReason(plan)
    const recordAllowed = !recordBlocked
    const work = plan.work_item; const matrix = data?.vehicle_matrices[plan.project_id]
    const step = matrix?.steps.find(row => row.key === (plan.vehicle_step_key || work.vehicle_step_key) && (!work.vehicle_step_key || work.vehicle_step_key === row.key))
    const units = matrix?.units.filter(unit => (!plan.scope?.vehicle_unit_ids?.length || plan.scope.vehicle_unit_ids.includes(unit.id)) && (!plan.scope?.vehicle_type || unit.vehicle_type === plan.scope.vehicle_type)) || []
    const checks = work.check_items?.filter(check => !check.is_done && check.is_applicable && (!check.vehicle_unit_id || units.some(unit => unit.id === check.vehicle_unit_id))) ?? []
    const completion = plan.completion
    const completionTag = completion && (completion.quantity_unknown ? <Tag>完成范围待核对</Tag> : completion.is_complete ? <Tag color="green">已完成</Tag> : completion.overdue ? <Tag color="red">已逾期</Tag> : null)
    const hideRecord = !!recordBlocked && sharedBlocked.has(recordBlocked)
    return <Card key={plan.id} size="small" title={work.name} extra={<>{plan.mode === 'in_progress' && <Tag>进行中</Tag>}{completionTag}</>} className="week-plan-card">
      <p className="week-plan-meta">{plan.project_name} · {work.phase_name}{assist ? ` · 协助 ${plan.assignees.map(p => p.name).join('、')}` : ''}{plan.scope?.label ? ` · ${plan.scope.label}` : ''}{completion && work.kind === 'vehicle' ? ` · 已完成 ${completion.completed_count ?? '未知'} / ${completion.required_count ?? (plan.mode === 'in_progress' ? '进行中' : '待核对')}` : ''}</p>
      {recordBlocked && !sharedBlocked.has(recordBlocked) && <Alert type="info" showIcon message={recordBlocked} style={{ marginBottom: 8 }} />}
      {hideRecord ? null : work.kind === 'vehicle' ? step ? units.map(unit => { const cell = unit.cells[step.key]; return <p key={unit.id}><Button disabled={!recordAllowed || loading || !!cell?.is_done} onClick={() => open(plan, 'vehicle', unit.id, cell?.version || 0, true, `${unit.fleet_no || unit.asset_code} · ${step.name}`, step.key, assist)}>{cell?.is_done ? `已完成 ${cell.done_on || ''}` : '勾选完成'} · {unit.fleet_no || unit.asset_code}</Button></p> }) : <Alert type="warning" message="真实车辆环节尚未读取，不能按计划量填报" /> : <Button disabled={!recordAllowed || loading || work.is_completed} onClick={() => open(plan, 'work', work.id, work.version, true, work.name, '', assist)}>{work.is_completed ? '已完成' : '登记实际完成'}</Button>}
      {!!checks.length && <Collapse ghost size="small" className="week-plan-checks" items={[{ key: 'checks', label: `待完成检查 ${checks.length} 项${checks.some(check => check.failed) ? '（含不通过）' : ''}`,
        children: checks.map(check => <p key={check.id}><span>{check.vehicle_label ? `${check.vehicle_label} · ` : ''}{check.name} </span>{check.failed && <Tag color="red">不通过</Tag>}<Button size="small" disabled={!recordAllowed || loading} onClick={() => open(plan, 'check', check.id, check.version, true, check.name, '', assist)}>登记检查通过</Button></p>) }]} />}
      <Link to={`/pm/projects/${plan.project_id}/overview`}>查看项目</Link>
    </Card>
  }
  // Same notice for several cards → shown once above the list, naming the projects.
  const blockedGroups = new Map<string, Set<string>>()
  for (const plan of data?.plans ?? []) { const reason = blockedReason(plan); if (reason) blockedGroups.set(reason, (blockedGroups.get(reason) ?? new Set()).add(plan.project_name)) }
  const sharedBlocked = new Set([...blockedGroups].filter(([, projects]) => (data?.plans.length ?? 0) > 1 && projects.size > 0).map(([reason]) => reason))
  const warningGroups = new Map<string, number>()
  for (const warning of data?.warnings ?? []) warningGroups.set(warning.message, (warningGroups.get(warning.message) ?? 0) + 1)
  const submitFile = async () => {
    if (!file || !uploading || uploadLock.current) return
    uploadLock.current = true; setUploadBusy(true); setUploadError(''); const owner = identity
    try {
      ensureVerifiedAccount(user?.id)
      await projectDocumentsApi.upload(uploading.project_id, { file, documentIds: [uploading.document_id], ...(uploading.timing_event && eventDate ? { milestoneDates: { [uploading.timing_event]: eventDate } } : {}) })
      if (active.current === owner) { setUploading(undefined); setFile(undefined); load() }
    } catch (e) {
      if (active.current !== owner) return
      if (isUploadQueued(e)) { setUploading(undefined); setFile(undefined); load() }
      else setUploadError(errMsg(e))
    } finally { uploadLock.current = false; if (active.current === owner) setUploadBusy(false) }
  }
  return <div className="worker-work-page">
    <WorkPageHeader title={canAccessNav('/pm/dashboard', user) ? '我的本周' : '工作台'} description="本周分配给你的工作；登记实际完成日期，协助登记会同时保留操作人和被协助人。" tools={<Space wrap><DatePicker picker="week" aria-label="计划周" value={week ? dayjs(week) : dayjs()} allowClear={false} onChange={value => setWeek(value?.subtract((value.day() + 6) % 7, 'day').format('YYYY-MM-DD'))} /><RefreshAction onClick={load} loading={loading} /></Space>} />
    {error && <Alert type="error" message="本周信息未能读取" description={error} />}
    {warningGroups.size > 0 && <details className="week-notice week-notice-fold"><summary>{data!.warnings.length} 条计划提醒</summary>
      <ul className="week-notice-list">{[...warningGroups].map(([message, count]) => <li key={message}>{message}{count > 1 ? `（${count} 处）` : ''}</li>)}</ul></details>}
    {[...sharedBlocked].map(reason => <Alert key={reason} type="info" showIcon className="week-notice" message={`${[...blockedGroups.get(reason)!].join('、')}：${reason}`} />)}
    {!!pendingCount && <Alert type="info" message={`${pendingCount} 条操作仍在本机队列，未计作服务器完成`} action={<Button disabled={!online} onClick={() => void flush().then(load)}>同步原操作</Button>} />}
    {!!rejected.length && <Card size="small" title="需核对的离线操作">{rejected.map(row => <p key={row.client_uuid}>{row.reason} <Button onClick={() => retry(row.client_uuid)}>重试原操作</Button><Button onClick={() => remove(row.client_uuid)}>移除本机待核对项</Button></p>)}</Card>}
    <div className="week-layout"><div className="week-layout-main">
    <Card title="本周我负责的工作" loading={loading}>{data?.plans.length ? data.plans.map(plan => planCard(plan)) : !error && <Empty description={data?.permissions.plan_read === false ? '本人周计划查看权限已关闭' : data?.state === 'unavailable' ? '周计划尚未读取' : '本周没有已发布给我的工作'} />}</Card>
    {!!data?.unassigned.length && <Card title="待认领工作">{data.unassigned.map(plan => <p key={plan.id}>{plan.project_name} · {plan.work_item.name} <Button disabled={!canRecord || plan.permissions?.claim === false || !!claiming || !online} loading={claiming === plan.id} onClick={() => void claim(plan)}>认领</Button></p>)}</Card>}
    {!!data?.assistable.length && <Card title="协助同项目人员" extra={<Button onClick={() => setShowAssist(value => !value)}>{showAssist ? '收起' : '选择协助工作'}</Button>}>{showAssist ? data.assistable.map(plan => planCard(plan, true)) : <Typography.Text type="secondary">同项目有 {data.assistable.length} 项工作可协助登记。</Typography.Text>}</Card>}
    </div><div className="week-layout-side">
    <Card title="本周待交资料">{data?.this_week_documents.length ? data.this_week_documents.map(doc => <p key={doc.document_id}><Link to={`/pm/projects/${doc.project_id}/documents?document=${doc.document_id}`}>{doc.project_name} · {doc.code} {doc.name}</Link><br /><Typography.Text type="secondary">{deadlineLabel(doc.due_at, doc.timezone || 'Asia/Shanghai')} · {doc.effective_owner_name || '负责人待核对'}</Typography.Text> {data.permissions.upload && hasSystemPermission(user, 'worker.deliver') && <Button onClick={() => { setUploading(doc); setFile(undefined); setEventDate(''); setUploadError('') }}>上传当期资料</Button>}</p>) : <Empty description={error ? '资料状态未知' : '本周没有可见待交资料'} />}</Card>
    <Card title="我的问题" extra={data?.permissions.issues && <Link to="/worker/issues">上报与处理问题</Link>}>{data?.my_issues.length ? data.my_issues.map(issue => <p key={issue.id}><Link to={`/worker/issues?issue=${issue.id}`}>{issue.project_name} · {issue.title}</Link> <Tag color={ISSUE_STATUS_MAP[issue.status]?.color}>{ISSUE_STATUS_MAP[issue.status]?.label ?? issue.status}</Tag></p>) : <Empty description="暂无本人未闭环问题" />}</Card>
    </div></div>
    {target && <FieldOperationModal key={`${identity}:${target.kind}:${target.target_id}`} target={target} onClose={() => setTarget(undefined)} onSaved={load} />}
    <Modal open={!!uploading} title={`上传资料 · ${uploading?.name || ''}`} onCancel={() => !uploadBusy && setUploading(undefined)} onOk={() => void submitFile()} confirmLoading={uploadBusy} okButtonProps={{ disabled: !file || uploadBusy }} maskClosable={false} okText="保存上传任务">
      <Typography.Paragraph>使用原有断点上传队列。离线时文件及原期次保存在本机，联网后仍须通过当前权限和哈希核验。</Typography.Paragraph>{uploadError && <Alert type="error" message={uploadError} />}<Upload beforeUpload={value => { setFile(value); return false }} maxCount={1} fileList={file ? [{ uid: 'file', name: file.name, status: 'done' }] : []} onRemove={() => { setFile(undefined); return true }}><Button>选择文件</Button></Upload>
      {!!uploading?.timing_event && <><p>此资料用于登记实际事件日期，请核对原件：</p><DatePicker aria-label="实际事件日期" onChange={value => setEventDate(value?.format('YYYY-MM-DD') || '')} /></>}
    </Modal>
  </div>
}
