import { ensureVerifiedAccount } from '../../utils/verifiedAccount'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { Alert, Button, Dropdown, Input, Modal, Tabs, Tag, message } from 'antd'
import { ArrowLeftOutlined, CopyOutlined, DeleteOutlined, DownloadOutlined, MoreOutlined, PlusOutlined, SaveOutlined, UploadOutlined } from '@ant-design/icons'
import { api, errMsg } from '../../api/client'
import { workItemsApi, type WorkPhase } from '../../api/workItems'
import { useAuth } from '../../stores/auth'
import { hasSystemPermission } from '../../constants/systemPermissions'
import TemplateDocumentsTab from './TemplateDocumentsTab'
import TemplateProcurementsTab from './TemplateProcurementsTab'
import TemplateStepsTab from './TemplateStepsTab'
import TemplateWorkTab from './TemplateWorkTab'
import { IconAction, RefreshAction } from '../../components/IconAction'
import { templateStatus, type TemplateRow } from './templateMeta'
import './TemplateEditorPage.css'

const TABS = ['work', 'documents', 'steps', 'procurement'] as const
type Tab = typeof TABS[number]

/** One template, full width and edited in place: work, document requirements, vehicle steps and procurement each on their own tab. Changes save themselves. */
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
  const [title, setTitle] = useState<{ name: string; description: string }>()
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
    ensureVerifiedAccount(user?.id)
    const next = [...steps, { key, name }]
    await api.put(`/templates/${tid}/vehicle-steps`, { steps: next })
    setSteps(next)
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
  const moreItems = [
    ...(canManage && tid !== 'default' ? [{ key: 'publish', icon: <SaveOutlined />, label: `存为新版本 v${(selected?.version || 1) + 1}`, disabled: busy }] : []),
    ...(canManage ? [{ key: 'copy', icon: <CopyOutlined />, label: '复制为新模板' }] : []),
    { key: 'export', icon: <DownloadOutlined />, label: '导出 JSON' },
    ...(canImport ? [{ key: 'import', icon: <UploadOutlined />, label: '导入 JSON（覆盖当前内容）', disabled: busy }] : []),
    ...(canManage && tid !== 'default' ? [{ type: 'divider' as const }, { key: 'delete', icon: <DeleteOutlined />, label: '删除模板', danger: true, disabled: busy }] : []),
  ]
  const setTab = (key: string) => setParams(old => { const next = new URLSearchParams(old); if (key === 'work') next.delete('tab'); else next.set('tab', key); return next }, { replace: true })

  useEffect(() => { if (selected) setTitle({ name: selected.name, description: selected.description ?? '' }) }, [selected?.id, selected?.name, selected?.description])
  const editableMeta = canManage && tid !== 'default'
  const saveTitle = () => {
    if (!title || !selected) return
    const name = title.name.trim(); const description = title.description.trim()
    if (!name) { setTitle({ name: selected.name, description }); return }
    if (name === selected.name && description === (selected.description ?? '')) return
    void mutate(() => api.put(`/templates/${tid}`, { name, description }))
  }
  const removeTemplate = () => Modal.confirm({
    title: `删除模板「${selected?.name}」？`, content: '已创建的项目不受影响；模板本身无法恢复。', okText: '删除模板', okButtonProps: { danger: true }, cancelText: '取消',
    onOk: async () => { try { ensureVerifiedAccount(user?.id); await api.delete(`/templates/${tid}`); message.success('模板已删除'); navigate('/pm/templates') } catch (e) { setError(errMsg(e)) } },
  })

  return <div className="tpl-editor-page">
    <header className="tpl-editor-head">
      <IconAction label="返回模板库" icon={<ArrowLeftOutlined />} onClick={() => navigate('/pm/templates')} />
      <div className="tpl-editor-title">
        {editableMeta && title ? <>
          <Input className="tpl-editor-name" aria-label="模板名称" variant="borderless" value={title.name} maxLength={200} onChange={e => setTitle({ ...title, name: e.target.value })} onBlur={saveTitle} onPressEnter={e => (e.target as HTMLInputElement).blur()} />
          <Input className="tpl-editor-desc-input" aria-label="模板说明" variant="borderless" placeholder="添加说明：适合什么样的项目" value={title.description} maxLength={2000} onChange={e => setTitle({ ...title, description: e.target.value })} onBlur={saveTitle} onPressEnter={e => (e.target as HTMLInputElement).blur()} />
        </> : <><h1>{selected?.name ?? (loading ? '' : '项目模板')}</h1>{selected?.description && <p className="tpl-editor-desc">{selected.description}</p>}</>}
        <div className="tpl-editor-meta"><Tag color={selected?.is_system ? 'blue' : selected?.status === 'published' ? 'green' : undefined}>{templateStatus(selected)}</Tag>
          <span>v{selected?.version || 1}</span>{!!selected?.usage_count && <span>已用于 {selected.usage_count} 个项目</span>}<span>修改自动保存，之后新建的项目按最新内容生成</span></div>
      </div>
      <div className="tpl-editor-actions">
        {canCreateProject && <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate(`/pm/projects?create=1&template=${encodeURIComponent(tid)}`)}>用此模板新建项目</Button>}
        <RefreshAction label="刷新模板" loading={loading} onClick={load} />
        <Dropdown trigger={['click']} menu={{ items: moreItems, onClick: ({ key }) => {
          if (key === 'copy') setCopyName(`${selected?.name ?? '模板'} 副本`)
          if (key === 'export') void exportJson()
          if (key === 'import') importInput.current?.click()
          if (key === 'publish') void mutate(async () => { await api.post(`/templates/${tid}/publish`); message.success('已存为新版本') })
          if (key === 'delete') removeTemplate()
        } }}><IconAction bordered label="更多模板操作" icon={<MoreOutlined />} /></Dropdown>
        <input ref={importInput} type="file" accept=".json" hidden aria-hidden="true" onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) importJson(file) }} />
      </div>
    </header>
    {error && <Alert type="error" showIcon message={error} className="tpl-alert" />}
    <Tabs className="tpl-tabs" activeKey={tab} onChange={setTab} items={[
      { key: 'work', label: <span>工作<span className="tpl-tab-count">{workCount}</span></span>,
        children: <TemplateWorkTab templateId={tid} phases={phases} setPhases={setPhases} steps={steps} canManage={canManage} loading={loading} onReload={load} onCreateStep={createStep} /> },
      { key: 'documents', label: <span>资料<span className="tpl-tab-count">{docCount}</span></span>,
        children: <TemplateDocumentsTab templateId={tid} editMode={canManage} onChanged={load} /> },
      { key: 'steps', label: <span>车辆环节<span className="tpl-tab-count">{steps.length}</span></span>, children: <TemplateStepsTab templateId={tid} steps={steps} setSteps={setSteps} phases={phases} canManage={canManage} /> },
      { key: 'procurement', label: '采购物料', children: <div className="tpl-tab"><TemplateProcurementsTab templateId={tid} editMode={canManage} /></div> },
    ]} />
    <Modal title="复制为新模板" open={copyName !== undefined} onCancel={() => { if (!busy) setCopyName(undefined) }} onOk={() => void copy()} confirmLoading={busy} okText="创建模板" cancelText="取消" okButtonProps={{ disabled: !canManage || !copyName?.trim() }}>
      <p className="tpl-modal-note">以「{selected?.name}」的全部内容为起点。</p>
      <Input aria-label="新模板名称" value={copyName} onChange={e => setCopyName(e.target.value)} maxLength={200} />
    </Modal>
  </div>
}
