import { ensureVerifiedAccount } from '../../utils/verifiedAccount'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Collapse, Drawer, Empty, Input, Modal, Select, Space, Table, Tag, Upload, message } from 'antd'
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

export default function TemplateEditorPage() {
  const { user } = useAuth()
  const canManage = hasSystemPermission(user, 'system.templates.manage')
  const canImport = hasSystemPermission(user, 'system.template_io.manage')
  const [templates, setTemplates] = useState<{ id: string; name: string; version?: number; is_system: boolean }[]>([])
  const [tid, setTid] = useState('default')
  const [phases, setPhases] = useState<WorkPhase[]>([])
  const [steps, setSteps] = useState<{ key: string; name: string }[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [editor, setEditor] = useState<{ item?: WorkItem }>()
  const [phaseName, setPhaseName] = useState<string>()
  const [copyName, setCopyName] = useState<string>()
  const [docs, setDocs] = useState<WorkItem>()
  const [busy, setBusy] = useState(false)
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
  useEffect(() => { current.current = identity; setPhases([]); setEditor(undefined); setDocs(undefined); void load(); return () => { generation.current++; current.current = Symbol('closed') } }, [identity])
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
  return <div>
    <WorkPageHeader title="实施模板" description="阶段下维护工作项；旧模块名保留为标签。已生成项目保留各自定义与检查事实。" tools={<Space wrap><Button loading={loading} onClick={() => void load()}>刷新模板</Button><Button onClick={() => void exportJson()}>导出模板 JSON</Button>{canManage && <><Button onClick={() => setCopyName('')}>复制为新模板</Button>{tid !== 'default' && <Button disabled={busy} onClick={() => void mutate(() => api.post(`/templates/${tid}/publish`))}>发布版本</Button>}</>}{canImport && <Upload accept=".json" showUploadList={false} beforeUpload={file => { void file.text().then(text => mutate(async () => { await api.post(`/templates/${tid}/import/json`, JSON.parse(text)); message.success('模板已导入') }, 'import')).catch(e => setError(errMsg(e))); return false }}><Button disabled={busy}>导入模板 JSON</Button></Upload>}</Space>} />
    {error && <Alert type="error" showIcon message={error} />}
    <Select aria-label="选择实施模板" value={tid} options={templates.map(t => ({ value: t.id, label: `${t.name} · v${t.version || 1}` }))} onChange={setTid} style={{ minWidth: 250 }} />
    <Tabs items={[
      { key: 'work', label: '工作项', children: <><Space style={{ margin: '12px 0' }}><Tag>{phases.length} 个阶段 · {phases.reduce((n, p) => n + p.work_items.length, 0)} 项工作</Tag>{canManage && <><Button onClick={() => setPhaseName('')}>添加阶段</Button><Button disabled={!phases.length || loading} onClick={() => setEditor({})}>添加工作项</Button></>}</Space>{!phases.length && !loading && <Empty description="暂无实施阶段" />}<Collapse defaultActiveKey={phases.map(p => p.id)} key={`${tid}:${phases.map(p => p.id).join('|')}`} items={phases.map(p => ({ key: p.id, label: p.name, children: <Table<WorkItem> rowKey="id" dataSource={p.work_items} pagination={false} columns={[
        { title: '工作项', render: (_, item) => <><strong>{item.name}</strong> {item.group_label && <Tag>{item.group_label}</Tag>}<p>{item.description}</p></> },
        { title: '实施方式', render: (_, item) => <><Tag>{item.kind === 'vehicle' ? '车辆环节' : '完成 / 未完成'}</Tag>{item.kind === 'vehicle' && <p>{steps.find(s => s.key === item.vehicle_step_key)?.name || '历史工作待明确关联'}</p>}<span>{item.check_definitions?.length || 0} 项检查</span></> },
        { title: '操作', render: (_, item) => <Space>{canManage && <Button onClick={() => setEditor({ item })}>编辑工作项</Button>}<Button onClick={() => setDocs(item)}>参考文档 {item.reference_docs.length}</Button></Space> },
      ]} /> }))} /></> },
      { key: 'documents', label: '资料要求', children: <TemplateDocumentsTab templateId={tid} editMode={canManage} /> },
      { key: 'procurements', label: '采购库', children: <TemplateProcurementsTab templateId={tid} editMode={canManage} /> },
      { key: 'vehicle_steps', label: '车辆环节', children: <TemplateVehicleSteps templateId={tid} canManage={canManage} /> },
    ]} />
    <WorkItemEditor canEdit={canManage} open={!!editor} templateId={tid} item={editor?.item} phases={phases} steps={steps} onClose={() => setEditor(undefined)} onSaved={load} />
    <Modal title="添加模板阶段" open={phaseName !== undefined} onCancel={() => { if (!busy) setPhaseName(undefined) }} onOk={() => void createPhase()} confirmLoading={busy} okText="保存阶段" okButtonProps={{ disabled: !canManage || !phaseName?.trim() }}><Input aria-label="模板阶段名称" value={phaseName} onChange={e => setPhaseName(e.target.value)} maxLength={100} /></Modal>
    <Modal title="复制模板" open={copyName !== undefined} onCancel={() => { if (!busy) setCopyName(undefined) }} onOk={() => void copy()} confirmLoading={busy} okText="创建模板" okButtonProps={{ disabled: !canManage || !copyName?.trim() }}><Input aria-label="新模板名称" value={copyName} onChange={e => setCopyName(e.target.value)} maxLength={200} /></Modal>
    <Drawer title={`${docs?.name || ''} · 参考文档`} open={!!docs} onClose={() => setDocs(undefined)} width={600}>{docs && <>{docs.reference_docs.map((ref: any) => <p key={ref.id}><Button onClick={() => void downloadDocumentResource(`/templates/${tid}/tasks/${docs.id}/reference-docs/${ref.id}/download`, ref.filename)}>{ref.filename}</Button>{ref.note}{canManage && <Button danger disabled={busy} onClick={() => Modal.confirm({ title: `删除参考文档「${ref.filename}」？`, onOk: () => mutate(async () => { await api.delete(`/templates/${tid}/tasks/${docs.id}/reference-docs/${ref.id}`); setDocs(undefined) }) })}>删除参考文档</Button>}</p>)}{canManage && <Upload showUploadList={false} beforeUpload={file => { const selected = docs; void mutate(async () => { const body = new FormData(); body.append('file', file); await api.post(`/templates/${tid}/tasks/${selected.id}/reference-docs`, body); setDocs(undefined) }); return false }}><Button disabled={busy}>上传参考文档</Button></Upload>}</>}</Drawer>
  </div>
}
