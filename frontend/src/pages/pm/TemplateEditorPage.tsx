import { ensureVerifiedAccount } from '../../utils/verifiedAccount'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Alert, Button, Dropdown, Input, Modal, Select, Tag, message } from 'antd'
import { ArrowLeftOutlined, CopyOutlined, DeleteOutlined, DownloadOutlined, FileTextOutlined, HolderOutlined, MoreOutlined, PaperClipOutlined, PlusOutlined, SearchOutlined, ShoppingCartOutlined, UploadOutlined } from '@ant-design/icons'
import { api, errMsg } from '../../api/client'
import { workItemsApi, type WorkPhase } from '../../api/workItems'
import { useAuth } from '../../stores/auth'
import { hasSystemPermission } from '../../constants/systemPermissions'
import TemplateDocPanel, { docFlags, timingLabel, type Requirement } from './TemplateDocPanel'
import TemplateProcPanel, { type ProcItem } from './TemplateProcPanel'
import TemplateStepsBlock from './TemplateStepsBlock'
import TemplateOutline from './TemplateOutline'
import { IconAction, RefreshAction } from '../../components/IconAction'
import { toVehicleTypeSelectOptions, useVehicleTypes } from '../../hooks/useVehicleTypes'
import type { TemplateRow } from './templateMeta'
import './TemplateEditorPage.css'

type Selection = { kind: 'work'; id: string } | { kind: 'doc'; id: string } | { kind: 'doc-new'; stage: string } | { kind: 'proc'; id: string } | { kind: 'proc-new' } | null
/** Procurement is prepared before the vehicles ship; vehicle steps are recorded during implementation. */
const PROCUREMENT_STAGE = '5'
const STEPS_STAGE = '6'

/**
 * One template on one page: work, documents, vehicle steps and procurement laid out along stages 4–9 and edited in
 * place, with a single side panel for whatever row is selected. One template per vehicle type. Changes save themselves.
 */
export default function TemplateEditorPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const tid = useParams().templateId ?? 'default'
  const canManage = hasSystemPermission(user, 'system.templates.manage')
  const canImport = hasSystemPermission(user, 'system.template_io.manage')
  const canCreateProject = hasSystemPermission(user, 'projects.create')
  const [templates, setTemplates] = useState<TemplateRow[]>([])
  const [phases, setPhases] = useState<WorkPhase[]>([])
  const [steps, setSteps] = useState<{ key: string; name: string }[]>([])
  const [docs, setDocs] = useState<Requirement[]>([])
  const [docsError, setDocsError] = useState(false)
  const [procs, setProcs] = useState<ProcItem[]>([])
  const [selection, setSelection] = useState<Selection>(null)
  const [keyword, setKeyword] = useState('')
  const flushRef = useRef<(() => Promise<void>) | null>(null)
  const { options: vehicleDictionary } = useVehicleTypes()
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
    const results = await Promise.allSettled([api.get('/templates'), workItemsApi.template(id), api.get(`/templates/${id}/vehicle-steps`), api.get(`/templates/${id}/document-requirements`), api.get(`/templates/${id}/procurements`)])
    if (current.current !== owner || seq !== generation.current) return
    const [meta, work, vehicle, documents, procurement] = results
    if (meta.status === 'fulfilled' && work.status === 'fulfilled') { setTemplates(meta.value.data); setPhases(work.value.phases); setError('') }
    else { setPhases([]); setError('模板读取失败，请重试。') }
    if (vehicle.status === 'fulfilled') setSteps(vehicle.value.data)
    else { setSteps([]); setError('车辆环节读取失败；已有工作保留，刷新后再选择关联。') }
    if (documents.status === 'fulfilled' && Array.isArray(documents.value.data)) { setDocs(documents.value.data); setDocsError(false) } else { setDocs([]); setDocsError(true) }
    if (procurement.status === 'fulfilled' && Array.isArray(procurement.value.data)) setProcs(procurement.value.data)
    setLoading(false)
  }
  const loadDocs = async () => { const owner = identity; try { const result = await api.get(`/templates/${tid}/document-requirements`); if (current.current === owner) { setDocs(result.data); setDocsError(false) } } catch { if (current.current === owner) setDocsError(true) } }
  const loadProcs = async () => { const owner = identity; try { const result = await api.get(`/templates/${tid}/procurements`); if (current.current === owner) setProcs(result.data) } catch (e) { if (current.current === owner) setError(errMsg(e)) } }
  useEffect(() => { current.current = identity; setPhases([]); setDocs([]); setProcs([]); setSelection(null); flushRef.current = null; void load(); return () => { generation.current++; current.current = Symbol('closed') } }, [identity])
  // Switching rows first saves what the open panel has not sent yet.
  const select = async (next: Selection) => { await flushRef.current?.(); setSelection(next) }
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
    ...(canManage ? [{ key: 'copy', icon: <CopyOutlined />, label: '复制为新模板' }] : []),
    { key: 'export', icon: <DownloadOutlined />, label: '导出 JSON' },
    ...(canImport ? [{ key: 'import', icon: <UploadOutlined />, label: '导入 JSON（覆盖当前内容）', disabled: busy }] : []),
    ...(canManage && tid !== 'default' ? [{ type: 'divider' as const }, { key: 'delete', icon: <DeleteOutlined />, label: '删除模板', danger: true, disabled: busy }] : []),
  ]

  useEffect(() => { if (selected) setTitle({ name: selected.name, description: selected.description ?? '' }) }, [selected?.id, selected?.name, selected?.description])
  const editableMeta = canManage && tid !== 'default'
  const saveTitle = () => {
    if (!title || !selected) return
    const name = title.name.trim(); const description = title.description.trim()
    if (!name) { setTitle({ name: selected.name, description }); return }
    if (name === selected.name && description === (selected.description ?? '')) return
    void mutate(() => api.put(`/templates/${tid}`, { name, description }))
  }
  const saveVehicleType = (vehicle_type: string | undefined) => {
    if (!selected) return
    void mutate(async () => { await api.put(`/templates/${tid}`, { name: selected.name, vehicle_type: vehicle_type ?? '' }); message.success(vehicle_type ? `已设为「${vehicle_type}」专用模板` : '已改为通用模板') })
  }

  // Search covers every kind of row on the page.
  const term = keyword.trim().toLowerCase()
  const docHit = (row: Requirement) => !term || `${row.code} ${row.name} ${row.template_no}`.toLowerCase().includes(term)
  const docParents = new Set(docs.filter(row => !row.is_group && docHit(row)).map(row => row.parent_id))
  const shownDocs = docs.filter(row => row.is_group ? docHit(row) || docParents.has(row.id) : docHit(row))
  const procHit = (row: ProcItem) => !term || `${row.name} ${row.spec ?? ''}`.toLowerCase().includes(term)
  const shownProcs = procs.filter(procHit)
  const stepHit = !term || steps.some(step => step.name.toLowerCase().includes(term))
  const docsIn = (stage: string) => shownDocs.filter(row => row.stage_key === stage)
  const realDocs = (rows: Requirement[]) => rows.filter(row => !row.is_group).length
  const stageExtraCount = (stage: string) => docsIn(stage).length + (stage === PROCUREMENT_STAGE ? shownProcs.length : 0) + (stage === STEPS_STAGE && term && stepHit ? 1 : 0)
  const stageExtraLabel = (stage: string) => [realDocs(docsIn(stage)) ? `${realDocs(docsIn(stage))} 份资料` : '', stage === PROCUREMENT_STAGE && shownProcs.length ? `${shownProcs.length} 个采购物料` : '', stage === STEPS_STAGE && steps.length ? `${steps.length} 个车辆环节` : ''].filter(Boolean).join(' · ')
  const isSelected = (kind: 'doc' | 'proc', id: string) => selection?.kind === kind && selection.id === id

  const docRow = (item: Requirement) => <li key={item.id} className={`tpl-node${item.is_group ? ' is-subhead' : ''}${item.parent_id ? ' is-child' : ''}${isSelected('doc', item.id) ? ' is-selected' : ''}`}>
    <button type="button" className="tpl-node-row" aria-current={isSelected('doc', item.id) ? 'true' : undefined} onClick={() => void select({ kind: 'doc', id: item.id })}>
      <span className="tpl-code">{item.code}</span>
      <span className="tpl-node-name">{item.name}</span>{docFlags(item)}
      <span className="tpl-row-meta">
        {!item.is_group && <span className="tpl-meta">{timingLabel(item)}</span>}
        {item.blank_file && <span className="tpl-meta" title={`空白模板：${item.blank_file.filename}`}><PaperClipOutlined aria-label="已有空白模板" /></span>}
      </span>
    </button>
    {item.source_metadata && <details className="tpl-source"><summary>历史来源（只读）</summary><pre>{JSON.stringify(item.source_metadata, null, 2)}</pre></details>}
  </li>
  const docBlock = (stage: string, title = '资料') => {
    const rows = docsIn(stage)
    if (term && !rows.length) return null
    return <div className="tpl-group tpl-docs" role="region" aria-label={`${title}：${stage}`}>
      <div className="tpl-group-head">
        <span className="tpl-block-icon" aria-hidden><FileTextOutlined /></span>
        <strong>{title}</strong>
        <span className="tpl-group-count">{realDocs(rows)}</span>
        {canManage && stage !== 'legacy' && <span className="tpl-group-actions"><IconAction label={`在此阶段添加资料`} icon={<PlusOutlined />} onClick={() => void select({ kind: 'doc-new', stage })} /></span>}
      </div>
      <ul className="tpl-nodes">
        {rows.map(docRow)}
        {!rows.length && <li className="tpl-node-empty">{docsError ? '资料读取失败，请刷新' : '这个阶段没有要交的资料'}</li>}
      </ul>
    </div>
  }
  const procBlock = () => {
    if (term && !shownProcs.length) return null
    return <div className="tpl-group tpl-procs" role="region" aria-label="采购物料">
      <div className="tpl-group-head">
        <span className="tpl-block-icon" aria-hidden><ShoppingCartOutlined /></span>
        <strong>采购物料</strong>
        <span className="tpl-group-count">{shownProcs.length}</span>
        <span className="tpl-block-note">项目准备时勾选要买的，数量和到货在项目里填</span>
        {canManage && <span className="tpl-group-actions"><IconAction label="添加采购物料" icon={<PlusOutlined />} onClick={() => void select({ kind: 'proc-new' })} /></span>}
      </div>
      <ul className="tpl-nodes">
        {shownProcs.map(item => <li key={item.id} className={`tpl-node${isSelected('proc', item.id) ? ' is-selected' : ''}`}>
          <button type="button" className="tpl-node-row" aria-current={isSelected('proc', item.id) ? 'true' : undefined} onClick={() => void select({ kind: 'proc', id: item.id })}>
            <span className="tpl-node-name">{item.name}</span>
            {item.is_required && <span className="tpl-row-tag is-warn">通常必需</span>}
            <span className="tpl-row-meta"><span className="tpl-meta">{[item.spec, item.unit].filter(Boolean).join(' · ')}</span></span>
          </button>
        </li>)}
        {!shownProcs.length && <li className="tpl-node-empty">还没有常用采购物料</li>}
      </ul>
    </div>
  }
  const selectedDoc = selection?.kind === 'doc' ? docs.find(row => row.id === selection.id) : undefined
  const selectedProc = selection?.kind === 'proc' ? procs.find(row => row.id === selection.id) : undefined
  const closePanel = () => setSelection(null)
  const panel = selection?.kind === 'doc-new' || selectedDoc
    ? <TemplateDocPanel key={selectedDoc?.id ?? `new-${selection?.kind === 'doc-new' ? selection.stage : ''}`} templateId={tid} editMode={canManage} rows={docs}
      target={selectedDoc ?? { stage: selection?.kind === 'doc-new' ? selection.stage : '6' }} flushRef={flushRef}
      onChanged={loadDocs} onCreated={id => setSelection(id ? { kind: 'doc', id } : null)} onClose={closePanel} />
    : selection?.kind === 'proc-new' || selectedProc
    ? <TemplateProcPanel key={selectedProc?.id ?? 'new-proc'} templateId={tid} editMode={canManage} item={selectedProc} flushRef={flushRef}
      onChanged={loadProcs} onCreated={id => setSelection(id ? { kind: 'proc', id } : null)} onClose={closePanel} />
    : undefined
  const legacy = docs.some(row => row.stage_key === 'legacy')
  const typeOptions = toVehicleTypeSelectOptions(vehicleDictionary, selected?.vehicle_type ? [selected.vehicle_type] : [])
  const takenTypes = new Map(templates.filter(t => t.vehicle_type && t.id !== tid).map(t => [t.vehicle_type!, t.name]))
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
        <div className="tpl-editor-meta">
          {selected?.is_system ? <Tag color="blue">通用</Tag> : selected && <label className="tpl-editor-type">车型
            <Select aria-label="模板车型" size="small" variant="borderless" allowClear placeholder="通用（所有车型）" disabled={!canManage || busy} value={selected.vehicle_type ?? undefined} style={{ minWidth: 150 }}
              options={typeOptions.map(option => ({ ...option, disabled: takenTypes.has(String(option.value)), title: takenTypes.has(String(option.value)) ? `已有模板「${takenTypes.get(String(option.value))}」` : undefined }))}
              onChange={value => saveVehicleType(value as string | undefined)} /></label>}
          {!!selected?.usage_count && <span>已用于 {selected.usage_count} 个项目</span>}<span>改动自动保存，之后新建的项目按最新内容带入</span></div>
      </div>
      <div className="tpl-editor-actions">
        {canCreateProject && <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate(`/pm/projects?create=1&template=${encodeURIComponent(tid)}`)}>用此模板新建项目</Button>}
        <RefreshAction label="刷新模板" loading={loading} onClick={load} />
        <Dropdown trigger={['click']} menu={{ items: moreItems, onClick: ({ key }) => {
          if (key === 'copy') setCopyName(`${selected?.name ?? '模板'} 副本`)
          if (key === 'export') void exportJson()
          if (key === 'import') importInput.current?.click()
          if (key === 'delete') removeTemplate()
        } }}><IconAction bordered label="更多模板操作" icon={<MoreOutlined />} /></Dropdown>
        <input ref={importInput} type="file" accept=".json" hidden aria-hidden="true" onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) importJson(file) }} />
      </div>
    </header>
    {error && <Alert type="error" showIcon message={error} className="tpl-alert" />}
    <TemplateOutline templateId={tid} phases={phases} setPhases={setPhases} steps={steps} canManage={canManage} loading={loading} onReload={load} onCreateStep={createStep}
      term={term} selectedId={selection?.kind === 'work' ? selection.id : undefined} onSelect={id => void select(id ? { kind: 'work', id } : null)} panel={panel}
      toolbar={<div className="tpl-toolbar">
        <Input allowClear prefix={<SearchOutlined />} placeholder="查找工作、资料或采购物料" aria-label="查找模板内容" value={keyword} onChange={e => setKeyword(e.target.value)} />
        <span className="tpl-toolbar-note">{workCount} 项工作 · {realDocs(docs)} 份资料 · {steps.length} 个车辆环节 · {procs.length} 个采购物料{canManage && !term && <> · 拖动 <HolderOutlined /> 调整工作顺序</>}</span>
      </div>}
      stageTop={stage => stage === STEPS_STAGE && stepHit ? <TemplateStepsBlock templateId={tid} steps={steps} setSteps={setSteps} phases={phases} canManage={canManage} /> : null}
      stageBottom={stage => <>{docBlock(stage)}{stage === PROCUREMENT_STAGE && procBlock()}</>}
      stageExtraCount={stageExtraCount} stageExtraLabel={stageExtraLabel}
      stageAddMenu={stage => canManage ? [{ key: 'doc', label: '添加资料', onClick: () => void select({ kind: 'doc-new', stage }) }, ...(stage === PROCUREMENT_STAGE ? [{ key: 'proc', label: '添加采购物料', onClick: () => void select({ kind: 'proc-new' }) }] : [])] : []}
      afterStages={legacy ? <section className="tpl-stage-section" aria-label="历史待分类"><header className="tpl-stage-head"><h3><span className="tpl-stage-key">?</span>历史待分类</h3></header>{docBlock('legacy', '待分类资料')}</section> : null} />
    <Modal title="复制为新模板" open={copyName !== undefined} onCancel={() => { if (!busy) setCopyName(undefined) }} onOk={() => void copy()} confirmLoading={busy} okText="创建模板" cancelText="取消" okButtonProps={{ disabled: !canManage || !copyName?.trim() }}>
      <p className="tpl-modal-note">以「{selected?.name}」的全部内容为起点。</p>
      <Input aria-label="新模板名称" value={copyName} onChange={e => setCopyName(e.target.value)} maxLength={200} />
    </Modal>
  </div>
}
