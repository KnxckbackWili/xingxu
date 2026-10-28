import { ensureVerifiedAccount } from '../../utils/verifiedAccount'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, Button, Collapse, Drawer, Dropdown, Empty, Input, Modal, Tag, Tooltip, Typography, Upload, message } from 'antd'
import {
  CarOutlined, CheckSquareOutlined, CopyOutlined, DownloadOutlined, EditOutlined, MoreOutlined, PaperClipOutlined, PlusOutlined,
  SafetyCertificateOutlined, SearchOutlined, StarFilled, UploadOutlined, FileTextOutlined,
} from '@ant-design/icons'
import { api, errMsg } from '../../api/client'
import { workItemsApi, type WorkItem, type WorkPhase } from '../../api/workItems'
import { useAuth } from '../../stores/auth'
import { hasSystemPermission } from '../../constants/systemPermissions'
import { WorkPageHeader } from '../../components/WorkPage'
import Tabs from '../../components/VisibleTabs'
import TemplateDocumentsTab from './TemplateDocumentsTab'
import TemplateProcurementsTab from './TemplateProcurementsTab'
import TemplateVehicleSteps from '../../components/TemplateVehicleSteps'
import WorkItemEditor from '../../components/WorkItemEditor'
import { downloadDocumentResource } from '../../api/projectDocuments'
import { IconAction, RefreshAction } from '../../components/IconAction'
import './TemplateEditorPage.css'

type TemplateRow = { id: string; name: string; description?: string; version?: number; status?: string; usage_count?: number; is_system: boolean }

/** Templates as a list on the left and the chosen template's content on the right; actions act on the chosen template. */
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
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [editor, setEditor] = useState<{ item?: WorkItem }>()
  const [phaseName, setPhaseName] = useState<string>()
  const [copyName, setCopyName] = useState<string>()
  const [docs, setDocs] = useState<WorkItem>()
  const [keyword, setKeyword] = useState('')
  const [busy, setBusy] = useState(false)
  const importInput = useRef<HTMLInputElement>(null)
  const lock = useRef(false)
  const generation = useRef(0)
  const identityKey = `${user?.id}:${tid}`
  const identity = useMemo(() => Symbol(identityKey), [identityKey])
  const current = useRef(identity)
  current.current = identity
  const load = async () => {
    const id = tid; const owner = identity; const seq = ++generation.current; setLoading(true)
    const results = await Promise.allSettled([api.get('/templates'), workItemsApi.template(id), api.get(`/templates/${id}/vehicle-steps`)])
    if (current.current !== owner || seq !== generation.current) return
    const [meta, work, vehicle] = results
    if (meta.status === 'fulfilled' && work.status === 'fulfilled') { setTemplates(meta.value.data); setPhases(work.value.phases); setError('') }
    else { setPhases([]); setError('模板读取失败，请重试。') }
    if (vehicle.status === 'fulfilled') setSteps(vehicle.value.data)
    else { setSteps([]); setError('车辆环节读取失败；已有工作保留，刷新后再选择关联。') }
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
  const createPhase = async () => {
    if (!phaseName?.trim()) return
    await mutate(async () => { await api.post(`/templates/${tid}/work-phases`, { name: phaseName }); setPhaseName(undefined) })
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
  const term = keyword.trim().toLowerCase()
  const visiblePhases = phases.map(phase => ({ phase, items: term ? phase.work_items.filter(item => `${item.name} ${item.group_label ?? ''} ${item.description ?? ''}`.toLowerCase().includes(term)) : phase.work_items }))
    .filter(row => !term || row.items.length)
  const stepName = (item: WorkItem) => steps.find(s => s.key === item.vehicle_step_key)?.name
  const moreItems = [
    ...(canManage ? [{ key: 'copy', icon: <CopyOutlined />, label: '复制为新模板' }] : []),
    { key: 'export', icon: <DownloadOutlined />, label: '导出模板 JSON' },
    ...(canImport ? [{ key: 'import', icon: <UploadOutlined />, label: '导入模板 JSON', disabled: busy }] : []),
  ]

  const workRow = (item: WorkItem) => <li key={item.id} className="template-work-row">
    <div className="template-work-main">
      <span className="template-work-name">{item.name}{item.group_label && <Tag className="template-work-group">{item.group_label}</Tag>}</span>
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

  return <div className="template-studio-page">
    <WorkPageHeader title="项目模板" description="新项目从模板带入工作项、资料要求、采购项和车辆环节；修改模板不影响已创建的项目。" />
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
            <span>{selected?.is_system ? '系统模板' : selected?.status === 'published' ? '已发布' : '草稿'} · v{selected?.version || 1} · {workCount} 项工作 · {steps.length} 个车辆环节</span>
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
        <Tabs items={[
          { key: 'work', label: `工作项 ${workCount}`, children: <>
            <div className="template-work-toolbar">
              <Input allowClear prefix={<SearchOutlined />} placeholder="查找工作项" aria-label="查找工作项" value={keyword} onChange={e => setKeyword(e.target.value)} />
              {canManage && <><Button onClick={() => setPhaseName('')}>添加阶段</Button><Button type="primary" icon={<PlusOutlined />} disabled={!phases.length || loading} onClick={() => setEditor({})}>添加工作项</Button></>}
            </div>
            {!phases.length && !loading && <Empty description="暂无实施阶段" />}
            {term && !visiblePhases.length && <Empty description="没有匹配的工作项" />}
            <Collapse className="template-phases" key={`${tid}:${phases.map(p => p.id).join('|')}:${term ? 'search' : ''}`}
              defaultActiveKey={term ? visiblePhases.map(row => row.phase.id) : phases.slice(0, 1).map(p => p.id)}
              items={visiblePhases.map(({ phase, items }) => ({ key: phase.id,
                label: <span className="template-phase-label">{phase.name}<Typography.Text type="secondary">{items.length} 项</Typography.Text></span>,
                children: <ul className="template-work-list">{items.map(workRow)}</ul> }))} />
          </> },
          { key: 'documents', label: '资料要求', children: <TemplateDocumentsTab templateId={tid} editMode={canManage} /> },
          { key: 'procurements', label: '采购库', children: <TemplateProcurementsTab templateId={tid} editMode={canManage} /> },
          { key: 'vehicle_steps', label: `车辆环节 ${steps.length}`, children: <TemplateVehicleSteps templateId={tid} canManage={canManage} /> },
        ]} />
      </section>
    </div>
    <WorkItemEditor canEdit={canManage} open={!!editor} templateId={tid} item={editor?.item} phases={phases} steps={steps} onClose={() => setEditor(undefined)} onSaved={load} />
    <Modal title="添加模板阶段" open={phaseName !== undefined} onCancel={() => { if (!busy) setPhaseName(undefined) }} onOk={() => void createPhase()} confirmLoading={busy} okText="保存阶段" okButtonProps={{ disabled: !canManage || !phaseName?.trim() }}><Input aria-label="模板阶段名称" value={phaseName} onChange={e => setPhaseName(e.target.value)} maxLength={100} /></Modal>
    <Modal title="复制为新模板" open={copyName !== undefined} onCancel={() => { if (!busy) setCopyName(undefined) }} onOk={() => void copy()} confirmLoading={busy} okText="创建模板" okButtonProps={{ disabled: !canManage || !copyName?.trim() }}>
      <Typography.Paragraph type="secondary">以「{selected?.name}」的全部内容为起点。</Typography.Paragraph>
      <Input aria-label="新模板名称" value={copyName} onChange={e => setCopyName(e.target.value)} maxLength={200} />
    </Modal>
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
