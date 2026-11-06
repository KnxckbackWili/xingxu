import { ensureVerifiedAccount } from '../../../utils/verifiedAccount'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Drawer, Dropdown, Empty, Input, Modal, Select, Space, Tag, Typography } from 'antd'
import { STAGES, stageIndex, stageLabel } from '../../../constants/stages'
import { CarOutlined, CheckCircleFilled, DownOutlined, EllipsisOutlined, PlusOutlined, RightOutlined, SearchOutlined } from '@ant-design/icons'
import './TaskPlanPage.css'
import { Link } from 'react-router-dom'
import { api, errMsg } from '../../../api/client'
import { workItemsApi, type WorkCatalog, type WorkItem, type WorkPhase } from '../../../api/workItems'
import { useAuth } from '../../../stores/auth'
import { hasSystemPermission } from '../../../constants/systemPermissions'
import WorkCompletionAction from '../../../components/WorkCompletionAction'
import WorkItemEditor from '../../../components/WorkItemEditor'
import WorkContextPanel, { WorkCheckAction } from '../../../components/WorkContextPanel'
import TemplateScope, { selectedWorkItems } from '../../../components/TemplateScope'
import { downloadDocumentResource } from '../../../api/projectDocuments'

type Props = { projectId: string; projectStatus?: string; focusTaskId?: string; onWorkChanged?: () => void; detailsOnly?: boolean; onDetailClose?: () => void; [key: string]: unknown }
export default function TaskPlanPage({ projectId, focusTaskId, onWorkChanged, detailsOnly = false, onDetailClose }: Props) {
  const { user } = useAuth()
  const identityKey = `${user?.id}:${projectId}`
  const identity = useMemo(() => Symbol(identityKey), [identityKey])
  const [workspace, setWorkspace] = useState<any>()
  const [workspaceError, setWorkspaceError] = useState('')
  const workspaceSequence = useRef(0)
  const [rawData, setData] = useState<WorkCatalog>()
  const dataOwner = useRef<symbol>()
  const data = dataOwner.current === identity ? rawData : undefined
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [steps, setSteps] = useState<{ key: string; name: string }[]>([])
  const [detailId, setDetailId] = useState<string>()
  const [editor, setEditor] = useState<{ item?: WorkItem }>()
  const [phaseName, setPhaseName] = useState<string>()
  const [phaseStage, setPhaseStage] = useState<string>('6')
  const [append, setAppend] = useState(false)
  const [templates, setTemplates] = useState<{ id: string; name: string }[]>([])
  const [templateId, setTemplateId] = useState('default')
  const [scope, setScope] = useState<WorkPhase[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [excluded, setExcluded] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [filter, setFilter] = useState<'all' | 'open' | 'vehicle'>('all')
  const [folded, setFolded] = useState<Record<string, boolean>>({})
  const [query, setQuery] = useState('')
  const lock = useRef(false)
  const scopeSequence = useRef(0)
  const generation = useRef(0)
  const current = useRef(identity)
  if (current.current !== identity) { current.current = identity; generation.current++ }
  const load = async () => {
    const id = projectId; const owner = identity; const seq = ++generation.current; setLoading(true)
    try {
      const result = await workItemsApi.list(id)
      if (seq !== generation.current || current.current !== owner) return
      dataOwner.current = owner; setData(result); setError('')
    } catch (e) { if (seq === generation.current && current.current === owner) { setData(undefined); setError(errMsg(e)) } }
    finally { if (seq === generation.current) setLoading(false) }
  }
  useEffect(() => {
    current.current = identity
    let active = true; setData(undefined); setDetailId(focusTaskId || undefined); setEditor(undefined); setAppend(false); void load()
    api.get(`/projects/${projectId}/vehicle-progress`).then(r => { if (active) setSteps(r.data.steps || []) }).catch(() => { if (active) setSteps([]) })
    return () => { active = false; generation.current++; scopeSequence.current++; workspaceSequence.current++; current.current = Symbol('closed') }
  }, [identity])
  useEffect(() => { if (focusTaskId) setDetailId(focusTaskId) }, [focusTaskId])
  const canPlan = !!data?.permissions.plan && user?.role !== 'readonly' && user?.permission_overrides?.['project.manage_plan'] !== false
  const canRecord = !!data?.permissions.record && hasSystemPermission(user, 'worker.report')
  const work = data?.phases.flatMap(p => p.work_items) || []
  const detail = work.find(w => w.id === detailId)
  const changed = async () => { const owner = identity; await load(); if (current.current === owner) onWorkChanged?.() }
  useEffect(() => {
    const owner = identity; const seq = ++workspaceSequence.current; setWorkspace(undefined); setWorkspaceError('')
    if (!detailId) return
    api.get(`/projects/${projectId}/tasks/${detailId}/workspace`).then(r => { if (owner === current.current && seq === workspaceSequence.current) setWorkspace(r.data) }).catch(e => { if (owner === current.current && seq === workspaceSequence.current) setWorkspaceError(errMsg(e)) })
    return () => { workspaceSequence.current++ }
  }, [identity, detailId, data])
  const addPhase = async () => {
    if (lock.current || !canPlan || !phaseName?.trim()) return
    const owner = current.current; const seq = generation.current
    lock.current = true; setBusy(true)
    try { ensureVerifiedAccount(user?.id); await api.post(`/projects/${projectId}/work-phases`, { name: phaseName, stage_key: phaseStage }); if (current.current !== owner || seq !== generation.current) return; setPhaseName(undefined); await changed() }
    catch (e) { if (current.current === owner) setError(errMsg(e)) } finally { lock.current = false; if (current.current === owner) setBusy(false) }
  }
  const readScope = async (id: string) => {
    const owner = identity; const seq = ++scopeSequence.current; setBusy(true); setScope([]); setSelected([])
    try { const result = await workItemsApi.template(id); if (current.current !== owner || seq !== scopeSequence.current) return; setScope(result.phases); setSelected(result.phases.flatMap(p => p.work_items.map(w => w.id))); setExcluded([]) }
    catch (e) { if (current.current === owner && seq === scopeSequence.current) setError(errMsg(e)) }
    finally { if (seq === scopeSequence.current) setBusy(false) }
  }
  const openScope = async () => {
    setAppend(true)
    try { const result = await api.get('/templates'); setTemplates(result.data); await readScope(templateId) }
    catch (e) { setError(errMsg(e)) }
  }
  const applyScope = async () => {
    if (!canPlan || lock.current) return
    const owner = current.current; const seq = generation.current
    lock.current = true; setBusy(true)
    try { ensureVerifiedAccount(user?.id); await api.post(`/projects/${projectId}/tasks/generate`, { template_id: templateId, work_item_ids: selectedWorkItems(scope, selected, excluded) }); if (current.current !== owner || seq !== generation.current) return; setAppend(false); await changed() }
    catch (e) { if (current.current === owner) setError(errMsg(e)) } finally { lock.current = false; if (current.current === owner) setBusy(false) }
  }
  return <div>
    {!detailsOnly && <>
    {error && <Alert type="error" showIcon message="工作项读取或操作未完成" description={error} action={<Button onClick={() => void load()}>刷新核对</Button>} />}
    {data && <div className="plan-toolbar">
      <Input allowClear prefix={<SearchOutlined />} aria-label="查找工作项" placeholder="查找工作项" value={query} onChange={event => setQuery(event.target.value)} className="plan-search" />
      <div className="plan-filters" role="group" aria-label="筛选工作项">
        {([['all', '全部', work.length], ['open', '未完成', work.filter(item => !item.is_completed).length], ['vehicle', '车辆工作', work.filter(item => item.kind === 'vehicle').length]] as const).map(([key, label, total]) =>
          <button key={key} type="button" aria-pressed={filter === key} onClick={() => setFilter(key)}>{label} {total}</button>)}
      </div>
      <span className="plan-toolbar-actions">
        {canPlan && <Button type="primary" icon={<PlusOutlined />} disabled={!data.phases.length} onClick={() => setEditor({})}>添加工作项</Button>}
        <Dropdown trigger={['click']} menu={{ items: [
          ...(canPlan ? [{ key: 'phase', label: '添加工作分组', onClick: () => setPhaseName('') }, { key: 'template', label: '从模板带入', onClick: () => void openScope() }] : []),
          { key: 'refresh', label: '刷新工作项', onClick: () => void load() },
        ] }}><Button loading={loading}>更多 <DownOutlined /></Button></Dropdown>
      </span>
    </div>}
    {data && !data.phases.length && <Empty description="尚无工作分组，添加分组后即可维护工作项" />}
    {data && !!data.phases.length && (() => {
      const term = query.trim().toLocaleLowerCase()
      const match = (item: WorkItem) => (filter === 'all' || (filter === 'open' && !item.is_completed) || (filter === 'vehicle' && item.kind === 'vehicle'))
        && (!term || `${item.name} ${item.group_label ?? ''} ${item.description ?? ''}`.toLocaleLowerCase().includes(term))
      const narrowed = filter !== 'all' || !!term
      const phases = data.phases.map(phase => ({ phase, items: phase.work_items.filter(match) })).filter(row => !narrowed || row.items.length)
      if (!phases.length) return <Empty description="没有符合条件的工作项" />
      // Finished groups fold away unless searched or opened by hand; groups with open work stay open.
      const isOpen = (phase: WorkPhase) => narrowed || (folded[phase.id] ?? phase.work_items.every(item => item.is_completed)) === false
      const toggle = (phase: WorkPhase) => setFolded(old => ({ ...old, [phase.id]: isOpen(phase) }))
      const blockedHint = ['preparing', 'suspended'].includes(data.project_status ?? '') ? '进入现场实施后可登记' : undefined
      const row = (item: WorkItem) => <li key={item.id} className={`plan-row${item.is_completed ? ' is-done' : ''}`}>
        <span className="plan-row-state" aria-hidden>{item.is_completed ? <CheckCircleFilled /> : item.kind === 'vehicle' ? <CarOutlined /> : <span className="plan-dot" />}</span>
        <button type="button" className="plan-row-name" onClick={() => setDetailId(item.id)}>{item.name}</button>
        {item.group_label && item.group_label !== item.phase_name && <Tag className="plan-row-tag">{item.group_label}</Tag>}
        <span className="plan-row-meta">
          {item.kind === 'vehicle' && <span className="plan-row-vehicle" title={item.matrix?.expected_count == null ? undefined : `${item.matrix.completed_count} / ${item.matrix.expected_count} 个车辆环节`}>{item.matrix?.name || '尚未关联环节'} {item.matrix?.expected_count == null ? '数量待核对' : `${item.matrix.completed_count}/${item.matrix.expected_count}`}</span>}
          {item.kind === 'vehicle' && item.matrix?.warning && <Typography.Text type="warning" className="plan-row-warning">{item.matrix.warning}</Typography.Text>}
          {item.kind !== 'vehicle' && <span className="plan-row-complete"><WorkCompletionAction compact projectId={projectId} item={item} canRecord={canRecord} canOverride={!!data.permissions.override} blockedHint={blockedHint} onSaved={changed} /></span>}
          <Dropdown trigger={['click']} menu={{ items: [
            { key: 'detail', label: '查看详情与检查', onClick: () => setDetailId(item.id) },
            ...(canPlan ? [{ key: 'edit', label: '编辑', onClick: () => setEditor({ item }) }] : []),
          ] }}><Button type="text" size="small" aria-label={`${item.name}的更多操作`} icon={<EllipsisOutlined />} /></Dropdown>
        </span>
      </li>
      // One section per backbone stage (4–9); work groups keep their order inside it.
      const stages = [...new Set(phases.map(row => row.phase.stage_key ?? '6'))].sort((a, b) => stageIndex(a) - stageIndex(b))
      return stages.map(stage => { const rows = phases.filter(row => (row.phase.stage_key ?? '6') === stage); return <section key={stage} className="plan-stage" aria-label={`阶段：${stageLabel(stage)}`}>
        <h3 className="plan-stage-title">{stageLabel(stage)}<span className="plan-phase-count">{rows.reduce((n, row) => n + row.phase.work_items.filter(item => item.is_completed).length, 0)} / {rows.reduce((n, row) => n + row.phase.work_items.length, 0)} 完成</span></h3>
        {rows.map(({ phase, items }) => {
          const done = phase.work_items.filter(item => item.is_completed).length
          const open = isOpen(phase)
          return <div key={phase.id} className="plan-group" role="region" aria-label={`工作分组：${phase.name}`}>
            <button type="button" className="plan-group-head" aria-expanded={open} onClick={() => toggle(phase)}>
              {open ? <DownOutlined /> : <RightOutlined />}<strong>{phase.name}</strong>
              <span className="plan-group-bar" aria-hidden><span style={{ width: `${phase.work_items.length ? done / phase.work_items.length * 100 : 0}%` }} /></span>
              <span className="plan-phase-count">{done}/{phase.work_items.length}</span>
            </button>
            {open && <ul className="plan-rows">{items.map(row)}{!items.length && <li className="plan-row-empty">本分组尚无工作项</li>}</ul>}
          </div>
        })}
      </section> })
    })()}
    <WorkItemEditor canEdit={canPlan} open={!!editor} projectId={projectId} item={editor?.item} phases={data?.phases || []} steps={steps} onClose={() => setEditor(undefined)} onSaved={changed} />
    <Modal title="添加工作分组" open={phaseName !== undefined} onCancel={() => { if (!busy) setPhaseName(undefined) }} onOk={() => void addPhase()} okText="保存分组" confirmLoading={busy} okButtonProps={{ disabled: !phaseName?.trim() || !canPlan }}>
      <Space direction="vertical" style={{ width: '100%' }}>
        <Select aria-label="所属阶段" value={phaseStage} onChange={setPhaseStage} options={STAGES.map(stage => ({ value: stage.key, label: stage.name }))} style={{ width: '100%' }} />
        <Input aria-label="工作分组名称" value={phaseName} maxLength={100} onChange={e => setPhaseName(e.target.value)} placeholder="例如：现场补充工作" />
      </Space>
    </Modal>
    <Modal title="从模板选择工作项" open={append} width={780} okText="带入所选工作" onCancel={() => { if (!busy) setAppend(false) }} onOk={() => void applyScope()} confirmLoading={busy} okButtonProps={{ disabled: !canPlan || !selectedWorkItems(scope, selected, excluded).length || busy }}><Select aria-label="工作来源模板" value={templateId} options={templates.map(t => ({ value: t.id, label: t.name }))} onChange={id => { setTemplateId(id); void readScope(id) }} /><TemplateScope phases={scope} selected={selected} onSelected={setSelected} excluded={excluded} onExcluded={setExcluded} disabled={busy} /></Modal>
    </>}
    <Drawer title={detail?.name || '工作项详情'} open={!!detailId} onClose={() => { setDetailId(undefined); onDetailClose?.() }} width={640}>
      {workspaceError && <Alert type="warning" message="工作执行上下文读取失败" description={workspaceError} action={<Button onClick={() => void load()}>刷新核对</Button>} />}
      {workspace && <WorkContextPanel data={workspace} onRefresh={changed} />}
      {detail ? <><Typography.Paragraph>{detail.description || '尚无补充说明'}</Typography.Paragraph><Space><Tag>{detail.phase_name}</Tag>{detail.group_label && <Tag>{detail.group_label}</Tag>}</Space>{detail.completion?.reason && <p>状态说明：{detail.completion.reason}</p>}<h3>检查要求</h3>{detail.check_items.map(check => <article key={check.id} style={{ marginBottom: 12 }}><strong>{check.name}</strong> <Tag>{check.vehicle_label || '工作检查'}</Tag>{check.is_safety_critical && <Tag color="red">安全关键</Tag>}<p>{check.failed ? `不通过：${check.failed_reason}` : !check.is_applicable ? `不适用：${check.not_applicable_reason}` : check.is_done ? '已通过' : '待检查'}</p>{canRecord && (!workspace || workspace.can_check) && <WorkCheckAction projectId={projectId} item={check} onSaved={changed} />}</article>)}<h3>参考文档</h3>{detail.reference_docs.map((ref, index) => <p key={index}><Button onClick={() => void downloadDocumentResource(`/projects/${projectId}/tasks/${detail.id}/reference-docs/${index}/download`, ref.filename)}>{ref.filename}</Button></p>)}<Link to={`/pm/projects/${projectId}/documents`}>项目资料清单</Link></> : <Empty description={loading ? '正在读取工作' : '该工作不在当前实施范围；可在历史来源中核对'} />}
    </Drawer>
  </div>
}
