import { ensureVerifiedAccount } from '../../utils/verifiedAccount'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, Button, Drawer, Dropdown, Empty, Input, Modal, Popconfirm, Tag, Tooltip, Typography, Upload, message } from 'antd'
import {
  CarOutlined, CheckSquareOutlined, CopyOutlined, DeleteOutlined, DownloadOutlined, EditOutlined, MoreOutlined, PaperClipOutlined, PlusOutlined,
  SafetyCertificateOutlined, SearchOutlined, StarFilled, SwapOutlined, UploadOutlined, FileTextOutlined, SettingOutlined,
} from '@ant-design/icons'
import { api, errMsg } from '../../api/client'
import { workItemsApi, type WorkItem, type WorkPhase } from '../../api/workItems'
import { useAuth } from '../../stores/auth'
import { hasSystemPermission } from '../../constants/systemPermissions'
import { STAGES, STAGE_NAME, stageLabel } from '../../constants/stages'
import { WorkPageHeader } from '../../components/WorkPage'
import TemplateDocumentsTab from './TemplateDocumentsTab'
import TemplateProcurementsTab from './TemplateProcurementsTab'
import TemplateVehicleSteps from '../../components/TemplateVehicleSteps'
import WorkItemEditor from '../../components/WorkItemEditor'
import { downloadDocumentResource } from '../../api/projectDocuments'
import { IconAction, RefreshAction } from '../../components/IconAction'
import './TemplateEditorPage.css'

type TemplateRow = { id: string; name: string; description?: string; version?: number; status?: string; usage_count?: number; is_system: boolean }
type GroupDialog = { mode: 'create' | 'rename'; phase?: WorkPhase; name: string }

/**
 * A template is one stage backbone (document stages 4–9). Each stage holds its work groups and work items,
 * its document requirements, and — where they belong — vehicle steps (实施) and procurement (发车前).
 */
export default function TemplateEditorPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const canManage = hasSystemPermission(user, 'system.templates.manage')
  const canImport = hasSystemPermission(user, 'system.template_io.manage')
  const canCreateProject = hasSystemPermission(user, 'projects.create')
  const [templates, setTemplates] = useState<TemplateRow[]>([])
  const [tid, setTid] = useState('default')
  const [phases, setPhases] = useState<WorkPhase[]>([])
  const [steps, setSteps] = useState<{ key: string; name: string }[]>([])
  const [docCounts, setDocCounts] = useState<Record<string, number>>({})
  const [stage, setStage] = useState<string>(STAGES[0].key)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [editor, setEditor] = useState<{ item?: WorkItem; phaseId?: string }>()
  const [group, setGroup] = useState<GroupDialog>()
  const [copyName, setCopyName] = useState<string>()
  const [docs, setDocs] = useState<WorkItem>()
  const [stepsOpen, setStepsOpen] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [busy, setBusy] = useState(false)
  const importInput = useRef<HTMLInputElement>(null)
  const lock = useRef(false)
  const generation = useRef(0)
  const stagePicked = useRef<symbol | null>(null)
  const identityKey = `${user?.id}:${tid}`
  const identity = useMemo(() => Symbol(identityKey), [identityKey])
  const current = useRef(identity)
  current.current = identity
  const load = async () => {
    const id = tid; const owner = identity; const seq = ++generation.current; setLoading(true)
    const results = await Promise.allSettled([api.get('/templates'), workItemsApi.template(id), api.get(`/templates/${id}/vehicle-steps`), api.get(`/templates/${id}/document-requirements`)])
    if (current.current !== owner || seq !== generation.current) return
    const [meta, work, vehicle, documents] = results
    if (meta.status === 'fulfilled' && work.status === 'fulfilled') {
      setTemplates(meta.value.data); setPhases(work.value.phases); setError('')
      // Open a template on its first stage that has work; later reloads keep the stage being edited.
      if (stagePicked.current !== owner) {
        stagePicked.current = owner
        const first = STAGES.find(s => work.value.phases.some(phase => (phase.stage_key ?? '6') === s.key && phase.work_items.length))
        setStage(first?.key ?? STAGES[0].key)
      }
    }
    else { setPhases([]); setError('模板读取失败，请重试。') }
    if (vehicle.status === 'fulfilled') setSteps(vehicle.value.data)
    else { setSteps([]); setError('车辆环节读取失败；已有工作保留，刷新后再选择关联。') }
    if (documents.status === 'fulfilled' && Array.isArray(documents.value.data)) {
      const counts: Record<string, number> = {}
      for (const row of documents.value.data) if (!row.is_group) counts[row.stage_key] = (counts[row.stage_key] ?? 0) + 1
      setDocCounts(counts)
    }
    setLoading(false)
  }
  useEffect(() => { current.current = identity; setPhases([]); setEditor(undefined); setDocs(undefined); setKeyword(''); void load(); return () => { generation.current++; current.current = Symbol('closed') } }, [identity])
  const mutate = async (run: () => Promise<unknown>, authority: 'manage' | 'import' = 'manage') => {
    if (lock.current || !(authority === 'import' ? canImport : canManage)) return
    const owner = identity; lock.current = true; setBusy(true); setError('')
    try { ensureVerifiedAccount(user?.id); await run(); if (current.current === owner) await load() }
    catch (e) { if (current.current === owner) setError(errMsg(e)) }
    finally { lock.current = false; if (current.current === owner) setBusy(false) }
  }
  const saveGroup = async () => {
    if (!group?.name.trim()) return
    const name = group.name.trim()
    await mutate(async () => {
      if (group.mode === 'create') await api.post(`/templates/${tid}/work-phases`, { name, stage_key: stage })
      else await api.put(`/templates/${tid}/work-phases/${group.phase!.id}`, { name })
      setGroup(undefined)
    })
  }
  const moveGroup = (phase: WorkPhase, target: string) => void mutate(async () => { await api.put(`/templates/${tid}/work-phases/${phase.id}`, { stage_key: target }); message.success(`已移到「${STAGE_NAME[target]}」`) })
  const deleteGroup = (phase: WorkPhase) => void mutate(() => api.delete(`/templates/${tid}/work-phases/${phase.id}`))
  const createStep = async (name: string) => {
    const key = `step_${globalThis.crypto?.randomUUID?.().replace(/-/g, '') ?? Date.now().toString(36)}`
    await api.put(`/templates/${tid}/vehicle-steps`, { steps: [...steps, { key, name }] })
    return key
  }
  const copy = async () => {
    if (!copyName?.trim() || lock.current || !canManage) return
    const owner = identity
    lock.current = true; setBusy(true)
    try { ensureVerifiedAccount(user?.id); const result = await api.post('/templates', { name: copyName, copy_from: tid }); if (current.current !== owner) return; setCopyName(undefined); setTid(result.data.id) }
    catch (e) { if (current.current === owner) setError(errMsg(e)) } finally { lock.current = false; if (current.current === owner) setBusy(false) }
  }
  const exportJson = async () => {
    try { const result = await api.get(`/templates/${tid}/export/json`); const url = URL.createObjectURL(new Blob([JSON.stringify(result.data, null, 2)], { type: 'application/json' })); const a = document.createElement('a'); a.href = url; a.download = `${templates.find(t => t.id === tid)?.name || '实施方案'}.json`; a.click(); URL.revokeObjectURL(url) }
    catch (e) { setError(errMsg(e)) }
  }
  const importJson = (file: File) => {
    void file.text().then(text => mutate(async () => { await api.post(`/templates/${tid}/import/json`, JSON.parse(text)); message.success('模板已导入') }, 'import')).catch(e => setError(errMsg(e)))
  }

  const selected = templates.find(t => t.id === tid)
  const workCount = phases.reduce((n, p) => n + p.work_items.length, 0)
  const stageOf = (phase: WorkPhase) => phase.stage_key ?? '6'
  const stagePhases = phases.filter(phase => stageOf(phase) === stage)
  const stageWork = (key: string) => phases.filter(phase => stageOf(phase) === key).reduce((n, p) => n + p.work_items.length, 0)
  const term = keyword.trim().toLowerCase()
  const visiblePhases = stagePhases.map(phase => ({ phase, items: term ? phase.work_items.filter(item => `${item.name} ${item.group_label ?? ''} ${item.description ?? ''}`.toLowerCase().includes(term)) : phase.work_items }))
    .filter(row => !term || row.items.length)
  const vehicleItems = phases.flatMap(phase => phase.work_items.filter(item => item.kind === 'vehicle'))
  const stageVehicleItems = stagePhases.flatMap(phase => phase.work_items.filter(item => item.kind === 'vehicle'))
  const stepName = (item: WorkItem) => steps.find(s => s.key === item.vehicle_step_key)?.name
  const moreItems = [
    ...(canManage ? [{ key: 'copy', icon: <CopyOutlined />, label: '复制为新模板' }] : []),
    { key: 'export', icon: <DownloadOutlined />, label: '导出模板 JSON' },
    ...(canImport ? [{ key: 'import', icon: <UploadOutlined />, label: '导入模板 JSON', disabled: busy }] : []),
  ]

  const workRow = (phase: WorkPhase) => (item: WorkItem) => <li key={item.id} className="template-work-row">
    <div className="template-work-main">
      <span className="template-work-name">{item.name}{item.group_label && item.group_label !== phase.name && <Tag className="template-work-group">{item.group_label}</Tag>}</span>
      {item.description && <Typography.Text type="secondary" ellipsis={{ tooltip: item.description }} className="template-work-desc">{item.description}</Typography.Text>}
    </div>
    <div className="template-work-meta">
      {item.kind === 'vehicle'
        ? <span className="template-chip is-vehicle"><CarOutlined aria-hidden />{stepName(item) ?? '历史工作待明确关联'}</span>
        : <span className="template-chip"><CheckSquareOutlined aria-hidden />完成 / 未完成</span>}
      <span className="template-chip"><SafetyCertificateOutlined aria-hidden />{item.check_definitions?.length || 0} 项检查</span>
    </div>
    <span className="row-icon-actions">
      <Tooltip title="参考文档"><Button type="text" className="icon-count-action" icon={<PaperClipOutlined />} aria-label={`参考文档 ${item.reference_docs.length}`} onClick={() => setDocs(item)}>{item.reference_docs.length}</Button></Tooltip>
      {canManage && <IconAction label="编辑工作项" icon={<EditOutlined />} onClick={() => setEditor({ item })} />}
    </span>
  </li>

  const groupBlock = ({ phase, items }: { phase: WorkPhase; items: WorkItem[] }) => <section key={phase.id} className="template-group" aria-label={`工作分组：${phase.name}`}>
    <header className="template-group-head">
      <strong>{phase.name}</strong><Typography.Text type="secondary">{items.length} 项</Typography.Text>
      {canManage && <span className="row-icon-actions">
        <IconAction label={`在「${phase.name}」添加工作项`} icon={<PlusOutlined />} onClick={() => setEditor({ phaseId: phase.id })} disabled={busy} />
        <IconAction label={`重命名分组「${phase.name}」`} icon={<EditOutlined />} onClick={() => setGroup({ mode: 'rename', phase, name: phase.name })} disabled={busy} />
        <Dropdown trigger={['click']} menu={{ items: STAGES.filter(s => s.key !== stageOf(phase)).map(s => ({ key: s.key, label: `移到 ${s.key} · ${s.name}` })), onClick: ({ key }) => moveGroup(phase, key) }}>
          <IconAction label={`把分组「${phase.name}」移到其他阶段`} icon={<SwapOutlined />} disabled={busy} />
        </Dropdown>
        {!phase.work_items.length && <Popconfirm title={`删除空分组「${phase.name}」？`} onConfirm={() => deleteGroup(phase)}><IconAction label={`删除分组「${phase.name}」`} icon={<DeleteOutlined />} danger disabled={busy} /></Popconfirm>}
      </span>}
    </header>
    {items.length ? <ul className="template-work-list">{items.map(workRow(phase))}</ul> : <p className="template-group-empty">还没有工作项</p>}
  </section>

  return <div className="template-studio-page">
    <WorkPageHeader title="项目模板" description="模板按第4–9阶段组织：每个阶段里放这一段的工作、要交的资料，发车前阶段还有采购物料，实施阶段还有逐车的车辆环节。修改模板不影响已创建的项目。" />
    {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />}
    <div className="template-studio">
      <nav className="template-list" aria-label="项目模板列表">
        <ul>{templates.map(t => <li key={t.id}><button type="button" aria-current={t.id === tid ? 'true' : undefined} onClick={() => setTid(t.id)}>
          <span className="template-list-icon" aria-hidden="true">{t.is_system ? <StarFilled /> : <FileTextOutlined />}</span>
          <span className="template-list-copy"><strong>{t.name}</strong><small>{t.is_system ? '系统模板' : t.status === 'published' ? '已发布' : '草稿'} · v{t.version || 1}{t.usage_count ? ` · ${t.usage_count} 个项目` : ''}</small></span>
        </button></li>)}</ul>
        {canManage && <Button block icon={<PlusOutlined />} onClick={() => setCopyName('')}>复制当前为新模板</Button>}
      </nav>
      <section className="template-detail" aria-label={selected?.name ?? '项目模板'}>
        <header className="template-detail-head">
          <div className="template-detail-title">
            <h2>{selected?.name ?? '项目模板'}</h2>
            <span>{selected?.is_system ? '系统模板' : selected?.status === 'published' ? '已发布' : '草稿'} · v{selected?.version || 1} · {workCount} 项工作 · {Object.values(docCounts).reduce((a, b) => a + b, 0)} 项资料 · {steps.length} 个车辆环节</span>
            {selected?.description && <Typography.Paragraph type="secondary" className="template-detail-desc">{selected.description}</Typography.Paragraph>}
          </div>
          <div className="template-detail-actions">
            {canCreateProject && <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate(`/pm/projects?create=1&template=${encodeURIComponent(tid)}`)}>用此模板新建项目</Button>}
            {canManage && tid !== 'default' && <Button disabled={busy} onClick={() => void mutate(() => api.post(`/templates/${tid}/publish`))}>发布版本</Button>}
            <RefreshAction label="刷新模板" loading={loading} onClick={load} />
            <Dropdown trigger={['click']} menu={{ items: moreItems, onClick: ({ key }) => {
              if (key === 'copy') setCopyName('')
              if (key === 'export') void exportJson()
              if (key === 'import') importInput.current?.click()
            } }}><IconAction bordered label="更多模板操作" icon={<MoreOutlined />} /></Dropdown>
            <input ref={importInput} type="file" accept=".json" hidden aria-hidden="true" onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) importJson(file) }} />
          </div>
        </header>

        <ol className="template-stage-rail" aria-label="模板阶段">{STAGES.map(s => <li key={s.key}>
          <button type="button" aria-current={stage === s.key ? 'step' : undefined} onClick={() => { setStage(s.key); setKeyword('') }}>
            <span className="template-stage-index">{s.key}</span>
            <span className="template-stage-copy"><strong>{s.name}</strong><small><span>{stageWork(s.key)} 工作</span> · <span>{docCounts[s.key] ?? 0} 资料</span></small></span>
          </button>
        </li>)}</ol>

        <div className="template-stage-panel" aria-label={`阶段：${stageLabel(stage)}`}>
          <section className="template-stage-section" aria-labelledby="template-stage-work">
            <div className="template-section-head">
              <h3 id="template-stage-work">工作</h3>
              <Input allowClear prefix={<SearchOutlined />} placeholder="在本阶段查找工作项" aria-label="查找工作项" value={keyword} onChange={e => setKeyword(e.target.value)} />
              {canManage && <><Button onClick={() => setGroup({ mode: 'create', name: '' })}>添加工作分组</Button>
                <Button type="primary" icon={<PlusOutlined />} disabled={!stagePhases.length || loading} onClick={() => setEditor({ phaseId: stagePhases[0]?.id })}>添加工作项</Button></>}
            </div>
            {!stagePhases.length && !loading && <Empty description={`「${STAGE_NAME[stage]}」阶段还没有工作分组`} />}
            {term && stagePhases.length > 0 && !visiblePhases.length && <Empty description="本阶段没有匹配的工作项" />}
            {visiblePhases.map(groupBlock)}
          </section>

          {(stage === '6' || stageVehicleItems.length > 0) && <section className="template-stage-section" aria-labelledby="template-stage-steps">
            <div className="template-section-head">
              <h3 id="template-stage-steps">车辆环节</h3>
              <Typography.Text type="secondary">每台车按这些环节逐车记录；逐车工作在添加工作项时选择或新建环节</Typography.Text>
              {canManage && <Button icon={<SettingOutlined />} onClick={() => setStepsOpen(true)}>调整环节顺序与名称</Button>}
            </div>
            <ol className="template-step-summary">{steps.map((s, index) => {
              const count = vehicleItems.filter(item => item.vehicle_step_key === s.key).length
              return <li key={s.key}><span className="template-step-index">{index + 1}</span><span>{s.name}</span><Typography.Text type="secondary">{count ? `${count} 项逐车工作` : '暂无逐车工作'}</Typography.Text></li>
            })}</ol>
          </section>}

          {stage === '5' && <section className="template-stage-section" aria-labelledby="template-stage-procurement">
            <div className="template-section-head"><h3 id="template-stage-procurement">采购物料</h3></div>
            <TemplateProcurementsTab templateId={tid} editMode={canManage} />
          </section>}

          <section className="template-stage-section" aria-labelledby="template-stage-docs">
            <div className="template-section-head"><h3 id="template-stage-docs">要交的资料</h3></div>
            <TemplateDocumentsTab templateId={tid} editMode={canManage} stageKey={stage} onChanged={load} />
          </section>
        </div>
      </section>
    </div>
    <WorkItemEditor canEdit={canManage} open={!!editor} templateId={tid} item={editor?.item} defaultPhaseId={editor?.phaseId} phases={phases} steps={steps}
      onCreateStep={canManage ? createStep : undefined} onClose={() => setEditor(undefined)} onSaved={load} />
    <Modal title={group?.mode === 'rename' ? '重命名工作分组' : `在「${STAGE_NAME[stage]}」添加工作分组`} open={!!group} onCancel={() => { if (!busy) setGroup(undefined) }} onOk={() => void saveGroup()} confirmLoading={busy} okText="保存分组" okButtonProps={{ disabled: !canManage || !group?.name.trim() }}>
      <Input aria-label="工作分组名称" value={group?.name} onChange={e => setGroup(old => old && { ...old, name: e.target.value })} maxLength={100} placeholder="例如：现场勘测、单车调试" />
    </Modal>
    <Modal title="复制为新模板" open={copyName !== undefined} onCancel={() => { if (!busy) setCopyName(undefined) }} onOk={() => void copy()} confirmLoading={busy} okText="创建模板" okButtonProps={{ disabled: !canManage || !copyName?.trim() }}>
      <Typography.Paragraph type="secondary">以「{selected?.name}」的全部内容为起点。</Typography.Paragraph>
      <Input aria-label="新模板名称" value={copyName} onChange={e => setCopyName(e.target.value)} maxLength={200} />
    </Modal>
    <Drawer title="车辆环节" open={stepsOpen} onClose={() => { setStepsOpen(false); void load() }} width={560} destroyOnHidden>
      <TemplateVehicleSteps templateId={tid} canManage={canManage} />
    </Drawer>
    <Drawer title={`${docs?.name || ''} · 参考文档`} open={!!docs} onClose={() => setDocs(undefined)} width={600}>{docs && <>
      {!docs.reference_docs.length && <Empty description="暂无参考文档" />}
      <ul className="template-ref-list">{docs.reference_docs.map((ref: any) => <li key={ref.id}>
        <Button type="link" icon={<PaperClipOutlined />} onClick={() => void downloadDocumentResource(`/templates/${tid}/tasks/${docs.id}/reference-docs/${ref.id}/download`, ref.filename)}>{ref.filename}</Button>
        {ref.note && <Typography.Text type="secondary">{ref.note}</Typography.Text>}
        {canManage && <Button danger type="text" disabled={busy} onClick={() => Modal.confirm({ title: `删除参考文档「${ref.filename}」？`, onOk: () => mutate(async () => { await api.delete(`/templates/${tid}/tasks/${docs.id}/reference-docs/${ref.id}`); setDocs(undefined) }) })}>删除参考文档</Button>}
      </li>)}</ul>
      {canManage && <Upload showUploadList={false} beforeUpload={file => { const target = docs; void mutate(async () => { const body = new FormData(); body.append('file', file); await api.post(`/templates/${tid}/tasks/${target.id}/reference-docs`, body); setDocs(undefined) }); return false }}><Button icon={<UploadOutlined />} disabled={busy}>上传参考文档</Button></Upload>}
    </>}</Drawer>
  </div>
}
