import { ensureVerifiedAccount } from '../../../utils/verifiedAccount'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Collapse, Drawer, Empty, Input, Modal, Select, Space, Table, Tag, Typography } from 'antd'
import { Link } from 'react-router-dom'
import { api, errMsg } from '../../../api/client'
import { workItemsApi, type WorkCatalog, type WorkItem, type WorkPhase } from '../../../api/workItems'
import { useAuth } from '../../../stores/auth'
import { hasSystemPermission } from '../../../constants/systemPermissions'
import WorkCompletionAction from '../../../components/WorkCompletionAction'
import WorkItemEditor from '../../../components/WorkItemEditor'
import WorkContextPanel, { WorkCheckAction } from '../../../components/WorkContextPanel'
import TemplateScope, { selectedWorkItems } from '../../../components/TemplateScope'
import { WorkPageHeader } from '../../../components/WorkPage'
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
  const [source, setSource] = useState<any>()
  const [append, setAppend] = useState(false)
  const [templates, setTemplates] = useState<{ id: string; name: string }[]>([])
  const [templateId, setTemplateId] = useState('default')
  const [scope, setScope] = useState<WorkPhase[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [excluded, setExcluded] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
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
    let active = true; setData(undefined); setDetailId(focusTaskId || undefined); setEditor(undefined); setSource(undefined); setAppend(false); void load()
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
  const history = async (item: WorkItem) => {
    const id = projectId; const owner = identity; const seq = generation.current
    try { const r = await api.get(`/projects/${id}/work-items/${item.id}/history`); if (current.current === owner && generation.current === seq) setSource(r.data) }
    catch (e) { if (current.current === owner) setError(errMsg(e)) }
  }
  const addPhase = async () => {
    if (lock.current || !canPlan || !phaseName?.trim()) return
    const owner = current.current; const seq = generation.current
    lock.current = true; setBusy(true)
    try { ensureVerifiedAccount(user?.id); await api.post(`/projects/${projectId}/work-phases`, { name: phaseName }); if (current.current !== owner || seq !== generation.current) return; setPhaseName(undefined); await changed() }
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
    <WorkPageHeader title="工作项" description="按阶段维护工作；车辆完成看真实进度表，非车辆工作记录完成状态。" tools={<Space wrap><Link to={`/pm/projects/${projectId}/schedule`}>周计划</Link><Button loading={loading} onClick={() => void load()}>刷新工作项</Button>{canPlan && <><Button onClick={() => setPhaseName('')}>添加阶段</Button><Button disabled={!data?.phases.length} onClick={() => setEditor({})}>添加工作项</Button><Button onClick={() => void openScope()}>从模板带入</Button></>}</Space>} />
    {error && <Alert type="error" showIcon message="工作项读取或操作未完成" description={error} action={<Button onClick={() => void load()}>刷新核对</Button>} />}
    {!!data?.legacy_work_items?.length && <Collapse items={[{ key: 'legacy', label: `历史准备工作来源（只读） ${data.legacy_work_items.length} 项`, children: data.legacy_work_items.map(item => <p key={item.id}>{item.name} {item.group_label && <Tag>{item.group_label}</Tag>}<Button onClick={() => void history(item)}>查看原记录</Button></p>) }]} />}
    {data && !data.phases.length && <Empty description="尚无工作阶段，添加阶段后即可维护工作项" />}
    {data && <Collapse defaultActiveKey={data.phases.map(p => p.id)} key={`${projectId}:${data.phases.map(p => p.id).join('|')}`} items={data.phases.map(phase => ({ key: phase.id, label: phase.name, extra: `${phase.work_items.length} 项工作`, children: <Table<WorkItem> rowKey="id" pagination={false} dataSource={phase.work_items} locale={{ emptyText: '本阶段尚无工作项' }} columns={[
      { title: '工作项', key: 'name', render: (_, item) => <><Button type="link" onClick={() => setDetailId(item.id)}>{item.name}</Button>{item.group_label && <Tag>{item.group_label}</Tag>}{item.description && <Typography.Paragraph ellipsis={{ rows: 2 }}>{item.description}</Typography.Paragraph>}</> },
      { title: '完成情况', key: 'state', render: (_, item) => item.kind === 'vehicle' ? <><Tag>车辆环节</Tag><div>{item.matrix?.name || '尚未关联环节'}</div><div>{item.matrix?.expected_count == null ? '数量待核对' : `${item.matrix.completed_count} / ${item.matrix.expected_count} 个车辆环节`}</div>{item.matrix?.warning && <Typography.Text type="warning">{item.matrix.warning}</Typography.Text>}</> : <><Tag color={item.is_completed ? 'green' : 'default'}>{item.is_completed ? '已完成' : '未完成'}</Tag>{item.quality_blocked && <Tag color="orange">检查待确认</Tag>}</> },
      { title: '操作', key: 'actions', render: (_, item) => <Space wrap><WorkCompletionAction projectId={projectId} item={item} canRecord={canRecord} canOverride={!!data.permissions.override} onSaved={changed} />{canPlan && <Button onClick={() => setEditor({ item })}>编辑</Button>}{item.has_legacy_quantity && <Button onClick={() => void history(item)}>历史来源</Button>}</Space> },
    ]} /> }))} />}
    <WorkItemEditor canEdit={canPlan} open={!!editor} projectId={projectId} item={editor?.item} phases={data?.phases || []} steps={steps} onClose={() => setEditor(undefined)} onSaved={changed} />
    <Modal title="添加工作阶段" open={phaseName !== undefined} onCancel={() => { if (!busy) setPhaseName(undefined) }} onOk={() => void addPhase()} okText="保存阶段" confirmLoading={busy} okButtonProps={{ disabled: !phaseName?.trim() || !canPlan }}><Input aria-label="工作阶段名称" value={phaseName} maxLength={100} onChange={e => setPhaseName(e.target.value)} /></Modal>
    <Modal title="从模板选择工作项" open={append} width={780} okText="带入所选工作" onCancel={() => { if (!busy) setAppend(false) }} onOk={() => void applyScope()} confirmLoading={busy} okButtonProps={{ disabled: !canPlan || !selectedWorkItems(scope, selected, excluded).length || busy }}><Select aria-label="工作来源模板" value={templateId} options={templates.map(t => ({ value: t.id, label: t.name }))} onChange={id => { setTemplateId(id); void readScope(id) }} /><TemplateScope phases={scope} selected={selected} onSelected={setSelected} excluded={excluded} onExcluded={setExcluded} disabled={busy} /></Modal>
    </>}
    <Drawer title={detail?.name || '工作项详情'} open={!!detailId} onClose={() => { setDetailId(undefined); onDetailClose?.() }} width={640}>
      {workspaceError && <Alert type="warning" message="工作执行上下文读取失败" description={workspaceError} action={<Button onClick={() => void load()}>刷新核对</Button>} />}
      {workspace && <WorkContextPanel data={workspace} onRefresh={changed} />}
      {detail ? <><Typography.Paragraph>{detail.description || '尚无补充说明'}</Typography.Paragraph><Space><Tag>{detail.phase_name}</Tag>{detail.group_label && <Tag>{detail.group_label}</Tag>}</Space>{detail.completion?.reason && <p>状态说明：{detail.completion.reason}</p>}<h3>检查要求</h3>{detail.check_items.map(check => <article key={check.id} style={{ marginBottom: 12 }}><strong>{check.name}</strong> <Tag>{check.vehicle_label || '工作检查'}</Tag>{check.is_safety_critical && <Tag color="red">安全关键</Tag>}<p>{check.failed ? `不通过：${check.failed_reason}` : !check.is_applicable ? `不适用：${check.not_applicable_reason}` : check.is_done ? '已通过' : '待检查'}</p>{canRecord && (!workspace || workspace.can_check) && <WorkCheckAction projectId={projectId} item={check} onSaved={changed} />}</article>)}<h3>参考文档</h3>{detail.reference_docs.map((ref, index) => <p key={index}><Button onClick={() => void downloadDocumentResource(`/projects/${projectId}/tasks/${detail.id}/reference-docs/${index}/download`, ref.filename)}>{ref.filename}</Button></p>)}<Link to={`/pm/projects/${projectId}/documents`}>项目资料清单</Link></> : <Empty description={loading ? '正在读取工作' : '该工作不在当前实施范围；可在历史来源中核对'} />}
    </Drawer>
    <Drawer title="原工作来源（只读）" open={source !== undefined} onClose={() => setSource(undefined)} width={760}><p>原名称、模块、描述、数量、日期和操作者保留用于追溯；当前工作按完成状态或真实车辆环节维护。</p><pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(source, null, 2)}</pre></Drawer>
  </div>
}
