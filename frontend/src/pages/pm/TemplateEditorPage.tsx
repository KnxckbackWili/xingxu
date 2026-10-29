import { ensureVerifiedAccount } from '../../utils/verifiedAccount'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { Alert, Button, Drawer, Dropdown, Empty, Input, Modal, Tabs, Tag, message } from 'antd'
import { ArrowLeftOutlined, CarOutlined, CopyOutlined, DownloadOutlined, EditOutlined, MoreOutlined, PlusOutlined, UploadOutlined } from '@ant-design/icons'
import { api, errMsg } from '../../api/client'
import { workItemsApi, type WorkPhase } from '../../api/workItems'
import { useAuth } from '../../stores/auth'
import { hasSystemPermission } from '../../constants/systemPermissions'
import TemplateDocumentsTab from './TemplateDocumentsTab'
import TemplateProcurementsTab from './TemplateProcurementsTab'
import TemplateVehicleSteps from '../../components/TemplateVehicleSteps'
import TemplateWorkTab from './TemplateWorkTab'
import { IconAction, RefreshAction } from '../../components/IconAction'
import { templateStatus, type TemplateRow } from './templateMeta'
import './TemplateEditorPage.css'

const TABS = ['work', 'documents', 'steps', 'procurement'] as const
type Tab = typeof TABS[number]

/** One template, full width: its work, document requirements, vehicle steps and procurement each on their own tab. */
export default function TemplateEditorPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const tid = useParams().templateId ?? 'default'
  const [params, setParams] = useSearchParams()
  const tab: Tab = TABS.includes(params.get('tab') as Tab) ? params.get('tab') as Tab : 'work'
  const canManage = hasSystemPermission(user, 'system.templates.manage')
  const canImport = hasSystemPermission(user, 'system.template_io.manage')
  const canCreateProject = hasSystemPermission(user, 'projects.create')
  const [templates, setTemplates] = useState<TemplateRow[]>([])
  const [phases, setPhases] = useState<WorkPhase[]>([])
  const [steps, setSteps] = useState<{ key: string; name: string }[]>([])
  const [docCount, setDocCount] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [copyName, setCopyName] = useState<string>()
  const [stepsOpen, setStepsOpen] = useState(false)
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
    const results = await Promise.allSettled([api.get('/templates'), workItemsApi.template(id), api.get(`/templates/${id}/vehicle-steps`), api.get(`/templates/${id}/document-requirements`)])
    if (current.current !== owner || seq !== generation.current) return
    const [meta, work, vehicle, documents] = results
    if (meta.status === 'fulfilled' && work.status === 'fulfilled') { setTemplates(meta.value.data); setPhases(work.value.phases); setError('') }
    else { setPhases([]); setError('模板读取失败，请重试。') }
    if (vehicle.status === 'fulfilled') setSteps(vehicle.value.data)
    else { setSteps([]); setError('车辆环节读取失败；已有工作保留，刷新后再选择关联。') }
    if (documents.status === 'fulfilled' && Array.isArray(documents.value.data)) setDocCount(documents.value.data.filter((row: { is_group: boolean }) => !row.is_group).length)
    setLoading(false)
  }
  useEffect(() => { current.current = identity; setPhases([]); void load(); return () => { generation.current++; current.current = Symbol('closed') } }, [identity])
  const mutate = async (run: () => Promise<unknown>, authority: 'manage' | 'import' = 'manage') => {
    if (lock.current || !(authority === 'import' ? canImport : canManage)) return
    const owner = identity; lock.current = true; setBusy(true); setError('')
    try { ensureVerifiedAccount(user?.id); await run(); if (current.current === owner) await load() }
    catch (e) { if (current.current === owner) setError(errMsg(e)) }
    finally { lock.current = false; if (current.current === owner) setBusy(false) }
  }
  const createStep = async (name: string) => {
    const key = `step_${globalThis.crypto?.randomUUID?.().replace(/-/g, '') ?? Date.now().toString(36)}`
    await api.put(`/templates/${tid}/vehicle-steps`, { steps: [...steps, { key, name }] })
    return key
  }
  const copy = async () => {
    if (!copyName?.trim() || lock.current || !canManage) return
    const owner = identity
    lock.current = true; setBusy(true)
    try { ensureVerifiedAccount(user?.id); const result = await api.post('/templates', { name: copyName.trim(), copy_from: tid }); if (current.current !== owner) return; setCopyName(undefined); navigate(`/pm/templates/${result.data.id}`) }
    catch (e) { if (current.current === owner) setError(errMsg(e)) } finally { lock.current = false; if (current.current === owner) setBusy(false) }
  }
  const exportJson = async () => {
    try { const result = await api.get(`/templates/${tid}/export/json`); const url = URL.createObjectURL(new Blob([JSON.stringify(result.data, null, 2)], { type: 'application/json' })); const a = document.createElement('a'); a.href = url; a.download = `${selected?.name || '实施方案'}.json`; a.click(); URL.revokeObjectURL(url) }
    catch (e) { setError(errMsg(e)) }
  }
  const importJson = (file: File) => {
    void file.text().then(text => mutate(async () => { await api.post(`/templates/${tid}/import/json`, JSON.parse(text)); message.success('模板已导入') }, 'import')).catch(e => setError(errMsg(e)))
  }

  const selected = templates.find(t => t.id === tid)
  const workCount = phases.reduce((n, p) => n + p.work_items.length, 0)
  const vehicleItems = phases.flatMap(phase => phase.work_items.filter(item => item.kind === 'vehicle'))
  const moreItems = [
    ...(canManage ? [{ key: 'copy', icon: <CopyOutlined />, label: '复制为新模板' }] : []),
    { key: 'export', icon: <DownloadOutlined />, label: '导出 JSON' },
    ...(canImport ? [{ key: 'import', icon: <UploadOutlined />, label: '导入 JSON', disabled: busy }] : []),
  ]
  const setTab = (key: string) => setParams(old => { const next = new URLSearchParams(old); if (key === 'work') next.delete('tab'); else next.set('tab', key); return next }, { replace: true })

  const stepsTab = <div className="tpl-tab">
    <div className="tpl-toolbar">
      <span className="tpl-toolbar-note">每台车按这个顺序逐车记录；逐车工作在“工作”里关联到某个环节。</span>
      {canManage && <Button icon={<EditOutlined />} onClick={() => setStepsOpen(true)}>编辑环节</Button>}
    </div>
    {!steps.length && !loading ? <Empty description="还没有车辆环节" /> : <ol className="tpl-flow">{steps.map((s, index) => {
      const linked = vehicleItems.filter(item => item.vehicle_step_key === s.key)
      return <li key={s.key}>
        <div className="tpl-flow-head"><span className="tpl-stage-key">{index + 1}</span><strong>{s.name}</strong></div>
        {linked.length ? <ul>{linked.map(item => <li key={item.id}><CarOutlined aria-hidden />{item.name}</li>)}</ul> : <p className="tpl-empty">暂无逐车工作</p>}
      </li>
    })}</ol>}
  </div>

  return <div className="tpl-editor-page">
    <header className="tpl-editor-head">
      <IconAction label="返回模板库" icon={<ArrowLeftOutlined />} onClick={() => navigate('/pm/templates')} />
      <div className="tpl-editor-title">
        <h1>{selected?.name ?? (loading ? '' : '项目模板')}</h1>
        <div className="tpl-editor-meta"><Tag color={selected?.is_system ? 'blue' : selected?.status === 'published' ? 'green' : undefined}>{templateStatus(selected)}</Tag>
          <span>v{selected?.version || 1}</span>{!!selected?.usage_count && <span>已用于 {selected.usage_count} 个项目</span>}{selected?.description && <span className="tpl-editor-desc">{selected.description}</span>}</div>
      </div>
      <div className="tpl-editor-actions">
        {canCreateProject && <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate(`/pm/projects?create=1&template=${encodeURIComponent(tid)}`)}>用此模板新建项目</Button>}
        {canManage && tid !== 'default' && <Button disabled={busy} onClick={() => void mutate(async () => { await api.post(`/templates/${tid}/publish`); message.success('已发布新版本') })}>发布版本</Button>}
        <RefreshAction label="刷新模板" loading={loading} onClick={load} />
        <Dropdown trigger={['click']} menu={{ items: moreItems, onClick: ({ key }) => {
          if (key === 'copy') setCopyName(`${selected?.name ?? '模板'} 副本`)
          if (key === 'export') void exportJson()
          if (key === 'import') importInput.current?.click()
        } }}><IconAction bordered label="更多模板操作" icon={<MoreOutlined />} /></Dropdown>
        <input ref={importInput} type="file" accept=".json" hidden aria-hidden="true" onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) importJson(file) }} />
      </div>
    </header>
    {error && <Alert type="error" showIcon message={error} className="tpl-alert" />}
    <Tabs className="tpl-tabs" activeKey={tab} onChange={setTab} items={[
      { key: 'work', label: <span>工作<span className="tpl-tab-count">{workCount}</span></span>,
        children: <TemplateWorkTab templateId={tid} phases={phases} steps={steps} canManage={canManage} loading={loading} busy={busy} mutate={mutate} onReload={load} onCreateStep={createStep} /> },
      { key: 'documents', label: <span>资料<span className="tpl-tab-count">{docCount}</span></span>,
        children: <TemplateDocumentsTab templateId={tid} editMode={canManage} onChanged={load} /> },
      { key: 'steps', label: <span>车辆环节<span className="tpl-tab-count">{steps.length}</span></span>, children: stepsTab },
      { key: 'procurement', label: '采购物料', children: <div className="tpl-tab"><TemplateProcurementsTab templateId={tid} editMode={canManage} /></div> },
    ]} />
    <Modal title="复制为新模板" open={copyName !== undefined} onCancel={() => { if (!busy) setCopyName(undefined) }} onOk={() => void copy()} confirmLoading={busy} okText="创建模板" cancelText="取消" okButtonProps={{ disabled: !canManage || !copyName?.trim() }}>
      <p className="tpl-modal-note">以「{selected?.name}」的全部内容为起点。</p>
      <Input aria-label="新模板名称" value={copyName} onChange={e => setCopyName(e.target.value)} maxLength={200} />
    </Modal>
    <Drawer title="编辑车辆环节" open={stepsOpen} onClose={() => { setStepsOpen(false); void load() }} width={560} destroyOnHidden>
      <TemplateVehicleSteps templateId={tid} canManage={canManage} />
    </Drawer>
  </div>
}
