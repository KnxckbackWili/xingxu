import { ensureVerifiedAccount } from '../../utils/verifiedAccount'
import { useEffect, useMemo, useRef, useState, type DragEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Alert, Button, Checkbox, Drawer, Dropdown, Empty, Grid, Input, Modal, Select, Skeleton, Tag, Tooltip, message } from 'antd'
import {
  ArrowLeftOutlined, CarOutlined, CopyOutlined, DeleteOutlined, DownloadOutlined, FileTextOutlined, HolderOutlined,
  ImportOutlined, MoreOutlined, PlusOutlined, SearchOutlined, ShoppingCartOutlined, ToolOutlined, UploadOutlined,
} from '@ant-design/icons'
import { api, errMsg } from '../../api/client'
import { itemBody, KIND_NAMES, newFile, STAGE_GATES, STAGES, templateItemsApi, type ItemKind, type TemplateItem, type TemplateTree } from '../../api/templateItems'
import { useAuth } from '../../stores/auth'
import { hasSystemPermission } from '../../constants/systemPermissions'
import TemplateItemPanel from './TemplateItemPanel'
import { IconAction, RefreshAction } from '../../components/IconAction'
import { toVehicleTypeSelectOptions, useVehicleTypes } from '../../hooks/useVehicleTypes'
import type { TemplateRow } from './templateMeta'
import './TemplateEditorPage.css'

const KIND_ICONS: Record<ItemKind, JSX.Element> = { work: <ToolOutlined />, file: <FileTextOutlined />, purchase: <ShoppingCartOutlined /> }
type Drag = { type: 'item' | 'section'; id: string }
type Drop = { id: string; pos: 'before' | 'after' | 'end' }

/** The small facts shown on a row: per vehicle, checks, files, quantity, optional. */
function rowFacts(item: TemplateItem) {
  return [
    item.per_vehicle ? '每台车' : '',
    item.kind === 'work' && item.checks.length ? `${item.checks.length} 项检查` : '',
    item.kind === 'purchase' ? (item.quantity != null ? `${item.quantity} ${item.unit}`.trim() : '数量项目里定') : '',
    item.kind === 'purchase' && item.spec ? item.spec : '',
    item.files.length ? (item.kind === 'file' ? `${item.files.length} 份文件` : `交 ${item.files.length} 份`) : '',
  ].filter(Boolean)
}

/**
 * One template on one page: titled sections, one row per thing (work, files, purchase), edited beside the list.
 * Sections and rows are added, renamed, dragged and removed in place; everything saves itself.
 */
export default function TemplateEditorPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const screens = Grid.useBreakpoint()
  const tid = useParams().templateId ?? 'default'
  const canManage = hasSystemPermission(user, 'system.templates.manage')
  const canImport = canManage && hasSystemPermission(user, 'system.template_io.manage')
  const canCreateProject = hasSystemPermission(user, 'projects.create')
  const { options: vehicleDictionary } = useVehicleTypes()
  const [templates, setTemplates] = useState<TemplateRow[]>([])
  const [tree, setTree] = useState<TemplateTree>()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selectedId, setSelectedId] = useState<string>()
  const [keyword, setKeyword] = useState('')
  const [title, setTitle] = useState<{ name: string; description: string }>()
  const [adding, setAdding] = useState<{ sectionId: string; kind: ItemKind; name: string }>()
  const [sectionTitles, setSectionTitles] = useState<Record<string, string>>({})
  const [copyName, setCopyName] = useState<string>()
  const [copyFrom, setCopyFrom] = useState<{ source?: string; tree?: TemplateTree; chosen: string[]; target?: string }>()
  const [busy, setBusy] = useState(false)
  const [drop, setDrop] = useState<Drop | null>(null)
  const drag = useRef<Drag | null>(null)
  const flushRef = useRef<(() => Promise<void>) | null>(null)
  const importInput = useRef<HTMLInputElement>(null)
  const generation = useRef(0)
  const identity = useMemo(() => Symbol(`${user?.id}:${tid}`), [user?.id, tid])
  const current = useRef(identity)
  current.current = identity

  const load = async () => {
    const owner = identity; const seq = ++generation.current; setLoading(true)
    try {
      const [meta, content] = await Promise.all([api.get('/templates'), templateItemsApi.read(tid)])
      if (current.current !== owner || seq !== generation.current) return
      setTemplates(meta.data); setTree(content); setError('')
    } catch (e) { if (current.current === owner) setError(errMsg(e)) }
    finally { if (current.current === owner && seq === generation.current) setLoading(false) }
  }
  useEffect(() => { setTree(undefined); setSelectedId(undefined); flushRef.current = null; void load(); return () => { generation.current++ } }, [identity])
  const selected = templates.find(t => t.id === tid)
  useEffect(() => { if (selected) setTitle({ name: selected.name, description: selected.description ?? '' }) }, [selected?.id, selected?.name, selected?.description])
  useEffect(() => { setSectionTitles(Object.fromEntries((tree?.sections ?? []).map(section => [section.id, section.title]))) }, [tree])

  const select = async (id?: string) => { await flushRef.current?.(); setSelectedId(id) }
  /** Run a change that answers with the whole template; the newest answer is shown. */
  const mutate = async (run: () => Promise<TemplateTree | void>, success?: string) => {
    if (!canManage) return
    const owner = identity; setBusy(true); setError('')
    try { ensureVerifiedAccount(user?.id); await flushRef.current?.(); const next = await run(); if (current.current !== owner) return; if (next) setTree(next); if (success) message.success(success) }
    catch (e) { if (current.current === owner) { setError(errMsg(e)); void load() } }
    finally { if (current.current === owner) setBusy(false) }
  }

  const sections = tree?.sections ?? []
  const allItems = sections.flatMap(section => section.items)
  const term = keyword.trim().toLowerCase()
  const hit = (item: TemplateItem) => !term || [item.name, item.note, item.spec, ...item.checks.map(check => check.name), ...item.files.flatMap(file => [file.code, file.name])].join(' ').toLowerCase().includes(term)
  const selectedItem = allItems.find(item => item.id === selectedId)
  const counts = { work: allItems.filter(i => i.kind === 'work').length, file: allItems.filter(i => i.kind === 'file').length, purchase: allItems.filter(i => i.kind === 'purchase').length, files: allItems.reduce((n, i) => n + i.files.length, 0) }

  // ----- sections -----
  const addSection = (afterId?: string) => mutate(async () => {
    const after = sections.find(section => section.id === afterId) ?? sections[sections.length - 1]
    const result = await templateItemsApi.addSection(tid, { title: '新段落', stage_key: after?.stage_key ?? '6', after_id: after?.id })
    setTimeout(() => document.querySelector<HTMLInputElement>(`[data-section-title="${result.id}"]`)?.select(), 50)
    return result
  })
  const renameSection = (id: string) => {
    const section = sections.find(row => row.id === id); const value = (sectionTitles[id] ?? '').trim()
    if (!section) return
    if (!value) { setSectionTitles(old => ({ ...old, [id]: section.title })); return }
    if (value !== section.title) void mutate(() => templateItemsApi.updateSection(tid, id, { title: value }))
  }
  const removeSection = (id: string) => {
    const section = sections.find(row => row.id === id)
    if (!section) return
    Modal.confirm({ title: `删除段落「${section.title}」？`, content: section.items.length ? `里面的 ${section.items.length} 件事会一起删除。已建的项目不受影响。` : '已建的项目不受影响。',
      okText: '删除段落', okButtonProps: { danger: true }, cancelText: '取消',
      onOk: () => mutate(async () => { if (section.items.some(item => item.id === selectedId)) setSelectedId(undefined); return templateItemsApi.removeSection(tid, id) }, '段落已删除') })
  }
  const layoutOf = (list = sections) => list.map(section => ({ id: section.id, item_ids: section.items.map(item => item.id) }))
  const saveLayout = (next: typeof sections) => {
    setTree(old => old && { ...old, sections: next })
    void mutate(() => templateItemsApi.layout(tid, layoutOf(next)))
  }
  const moveSection = (id: string, target: Drop) => {
    const list = [...sections]; const from = list.findIndex(s => s.id === id); if (from < 0) return
    const [row] = list.splice(from, 1)
    let to = list.findIndex(s => s.id === target.id); if (to < 0) return
    if (target.pos === 'after') to += 1
    list.splice(to, 0, row)
    if (list.map(s => s.id).join() !== sections.map(s => s.id).join()) saveLayout(list)
  }
  const moveItem = (id: string, target: Drop) => {
    const list = sections.map(section => ({ ...section, items: section.items.filter(item => item.id !== id) }))
    const item = allItems.find(row => row.id === id); if (!item) return
    if (target.pos === 'end') { const section = list.find(s => s.id === target.id); if (!section) return; section.items.push({ ...item, section_id: section.id }) }
    else {
      const section = list.find(s => s.items.some(row => row.id === target.id)); if (!section) return
      const index = section.items.findIndex(row => row.id === target.id) + (target.pos === 'after' ? 1 : 0)
      section.items.splice(index, 0, { ...item, section_id: section.id })
    }
    if (JSON.stringify(layoutOf(list)) !== JSON.stringify(layoutOf())) saveLayout(list)
  }
  const shiftSection = (id: string, by: number) => {
    const index = sections.findIndex(s => s.id === id); const to = index + by
    if (index < 0 || to < 0 || to >= sections.length) return
    const list = [...sections]; const [row] = list.splice(index, 1); list.splice(to, 0, row); saveLayout(list)
  }

  // ----- rows -----
  const addingOpen = useRef(false)
  const startAdding = (sectionId: string, kind: ItemKind) => { addingOpen.current = true; setAdding({ sectionId, kind, name: '' }) }
  const stopAdding = () => { addingOpen.current = false; setAdding(undefined) }
  const addItem = () => {
    // Enter and the blur that follows must not add the row twice.
    if (!adding || !addingOpen.current) return
    addingOpen.current = false
    if (!adding.name.trim()) { setAdding(undefined); return }
    const { sectionId, kind, name } = adding
    setAdding(undefined)
    void mutate(async () => {
      const result = await templateItemsApi.addItem(tid, itemBody({ section_id: sectionId, kind, name: name.trim(), note: '', optional: false, per_vehicle: false, checks: [], files: kind === 'file' ? [newFile(name.trim())] : [], quantity: null, unit: kind === 'purchase' ? '台' : '', spec: '' }))
      setSelectedId(result.id)
      return result
    })
  }

  // ----- drag and drop -----
  const dragProps = (type: Drag['type'], id: string) => canManage && !term ? {
    draggable: true,
    onDragStart: (e: DragEvent) => { drag.current = { type, id }; e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', id); e.stopPropagation() },
    onDragEnd: () => { drag.current = null; setDrop(null) },
  } : {}
  const half = (e: DragEvent) => { const box = (e.currentTarget as HTMLElement).getBoundingClientRect(); return e.clientY - box.top < box.height / 2 ? 'before' as const : 'after' as const }
  const over = (accept: Drag['type'], target: (e: DragEvent) => Drop) => (e: DragEvent) => {
    if (drag.current?.type !== accept) return
    e.preventDefault(); e.stopPropagation(); const next = target(e)
    if (next.id !== drop?.id || next.pos !== drop?.pos) setDrop(next)
  }
  const land = (e: DragEvent) => {
    if (!drag.current || !drop) return
    e.preventDefault(); e.stopPropagation()
    const { type, id } = drag.current
    if (type === 'item') moveItem(id, drop); else if (drop.pos !== 'end') moveSection(id, drop)
    drag.current = null; setDrop(null)
  }
  const marker = (id: string) => drop?.id === id ? ` is-drop-${drop.pos}` : ''

  // ----- template -----
  const editableMeta = canManage && tid !== 'default'
  const saveTitle = () => {
    if (!title || !selected) return
    const name = title.name.trim(); const description = title.description.trim()
    if (!name) { setTitle({ name: selected.name, description }); return }
    if (name === selected.name && description === (selected.description ?? '')) return
    void mutate(async () => { await api.put(`/templates/${tid}`, { name, description }); await load() })
  }
  const saveVehicleType = (vehicle_type?: string) => selected && void mutate(async () => { await api.put(`/templates/${tid}`, { name: selected.name, vehicle_type: vehicle_type ?? '' }); await load() }, vehicle_type ? `已设为「${vehicle_type}」专用模板` : '已改为通用模板')
  const copyTemplate = async () => {
    if (!copyName?.trim() || !canManage) return
    setBusy(true)
    try { ensureVerifiedAccount(user?.id); const result = await api.post('/templates', { name: copyName.trim(), copy_from: tid }); setCopyName(undefined); navigate(`/pm/templates/${result.data.id}`) }
    catch (e) { setError(errMsg(e)) } finally { setBusy(false) }
  }
  const exportExcel = async () => {
    try { const blob = await templateItemsApi.exportExcel(tid); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = `${selected?.name ?? '模板'}.xlsx`; a.click(); URL.revokeObjectURL(url) }
    catch (e) { setError(errMsg(e)) }
  }
  const importExcel = (file: File) => Modal.confirm({
    title: '用表格替换这个模板？', okText: '导入并替换', cancelText: '取消',
    content: '表格里的段落和事项会整体替换当前内容。名称相同的事项、编号相同的文件会保留原来的空白模板和参考文件。已建的项目不受影响。',
    onOk: () => mutate(async () => { const result = await templateItemsApi.importExcel(tid, file); setSelectedId(undefined); message.success(`已导入 ${result.imported.sections} 个段落、${result.imported.items} 件事`); return result }),
  })
  const removeTemplate = () => Modal.confirm({
    title: `删除模板「${selected?.name}」？`, content: '已创建的项目不受影响；模板本身无法恢复。', okText: '删除模板', okButtonProps: { danger: true }, cancelText: '取消',
    onOk: async () => { try { ensureVerifiedAccount(user?.id); await api.delete(`/templates/${tid}`); message.success('模板已删除'); navigate('/pm/templates') } catch (e) { setError(errMsg(e)) } },
  })
  const openCopy = () => setCopyFrom({ chosen: [], source: templates.find(t => t.id !== tid)?.id })
  useEffect(() => {
    if (!copyFrom?.source || copyFrom.tree?.template_id === copyFrom.source) return
    const source = copyFrom.source
    void templateItemsApi.read(source).then(result => setCopyFrom(old => old && old.source === source ? { ...old, tree: result, chosen: [] } : old)).catch(e => setError(errMsg(e)))
  }, [copyFrom?.source])
  const doCopy = () => copyFrom?.source && copyFrom.chosen.length && void mutate(async () => {
    const result = await templateItemsApi.copy(tid, { source_template_id: copyFrom.source!, item_ids: copyFrom.chosen, section_id: copyFrom.target })
    setCopyFrom(undefined); message.success(`已复制 ${result.copied.length} 件事`); return result
  })

  const typeOptions = toVehicleTypeSelectOptions(vehicleDictionary, selected?.vehicle_type ? [selected.vehicle_type] : [])
  const takenTypes = new Map(templates.filter(t => t.vehicle_type && t.id !== tid).map(t => [t.vehicle_type!, t.name]))
  const moreItems = [
    { key: 'export', icon: <DownloadOutlined />, label: '导出 Excel' },
    ...(canImport ? [{ key: 'import', icon: <UploadOutlined />, label: '从 Excel 导入（替换）', disabled: busy }] : []),
    ...(canManage ? [{ key: 'copy', icon: <CopyOutlined />, label: '复制为新模板' }] : []),
    ...(canManage && tid !== 'default' ? [{ type: 'divider' as const }, { key: 'delete', icon: <DeleteOutlined />, label: '删除模板', danger: true, disabled: busy }] : []),
  ]
  const addMenu = (sectionId: string) => ({ items: (['work', 'file', 'purchase'] as ItemKind[]).map(kind => ({ key: kind, icon: KIND_ICONS[kind], label: `加${KIND_NAMES[kind]}` })), onClick: ({ key }: { key: string }) => startAdding(sectionId, key as ItemKind) })

  const itemRow = (item: TemplateItem) => <li key={item.id} className={`tpl-row${selectedId === item.id ? ' is-selected' : ''}${marker(item.id)}`} {...dragProps('item', item.id)}
    onDragOver={over('item', e => ({ id: item.id, pos: half(e) }))} onDrop={land}>
    <button type="button" className="tpl-row-main" aria-current={selectedId === item.id ? 'true' : undefined} onClick={() => void select(selectedId === item.id ? undefined : item.id)}>
      {canManage && !term && <span className="tpl-handle" aria-hidden><HolderOutlined /></span>}
      <span className={`tpl-kind is-${item.kind}`} title={KIND_NAMES[item.kind]}>{KIND_ICONS[item.kind]}<span>{KIND_NAMES[item.kind]}</span></span>
      <span className="tpl-row-name">{item.name}</span>
      {item.optional && <Tag className="tpl-row-optional">可选</Tag>}
      <span className="tpl-row-facts">{rowFacts(item).map(fact => <span key={fact}>{fact}</span>)}</span>
    </button>
  </li>

  const sectionBlock = (section: TemplateTree['sections'][number], index: number) => {
    const rows = section.items.filter(hit)
    if (term && !rows.length) return null
    const files = section.items.reduce((n, item) => n + item.files.length, 0)
    return <section key={section.id} className={`tpl-section${marker(section.id)}`} aria-label={`段落：${section.title}`}
      onDragOver={over('section', e => ({ id: section.id, pos: half(e) }))} onDrop={land}>
      <header className="tpl-section-head" {...dragProps('section', section.id)}>
        {canManage && !term && <span className="tpl-handle" aria-hidden><HolderOutlined /></span>}
        {canManage ? <Input className="tpl-section-title" variant="borderless" aria-label="段落标题" data-section-title={section.id} value={sectionTitles[section.id] ?? section.title} maxLength={200}
          onChange={e => setSectionTitles(old => ({ ...old, [section.id]: e.target.value }))} onBlur={() => renameSection(section.id)} onPressEnter={e => (e.target as HTMLInputElement).blur()} />
          : <h3 className="tpl-section-title">{section.title}</h3>}
        <Tooltip title={`这一段要交的文件：${STAGE_GATES[section.stage_key] ?? ''}`}>
          <Select className="tpl-section-stage" size="small" variant="borderless" aria-label={`段落「${section.title}」所属阶段`} value={section.stage_key} disabled={!canManage || busy} popupMatchSelectWidth={false}
            onChange={stage_key => void mutate(() => templateItemsApi.updateSection(tid, section.id, { stage_key }))}
            options={[...STAGES.map(stage => ({ value: stage.key, label: `阶段：${stage.name}` })), ...(section.stage_key === 'legacy' ? [{ value: 'legacy', label: '历史待分类' }] : [])]} />
        </Tooltip>
        <span className="tpl-section-count">{section.items.length} 件事{files ? ` · ${files} 份文件` : ''}</span>
        {canManage && <Dropdown trigger={['click']} menu={{ items: [
          { key: 'up', label: '上移', disabled: index === 0 }, { key: 'down', label: '下移', disabled: index === sections.length - 1 },
          { key: 'add', label: '在下面加段落' }, { type: 'divider' }, { key: 'delete', label: '删除段落', danger: true }],
          onClick: ({ key }) => { if (key === 'up') shiftSection(section.id, -1); if (key === 'down') shiftSection(section.id, 1); if (key === 'add') void addSection(section.id); if (key === 'delete') removeSection(section.id) } }}>
          <IconAction label={`段落「${section.title}」操作`} icon={<MoreOutlined />} />
        </Dropdown>}
      </header>
      <ul className="tpl-rows">
        {rows.map(itemRow)}
        {!section.items.length && <li className={`tpl-row-empty${marker(`end:${section.id}`)}`} onDragOver={over('item', () => ({ id: section.id, pos: 'end' }))} onDrop={land}>这个段落还没有事项</li>}
      </ul>
      {canManage && !term && (adding?.sectionId === section.id
        ? <div className="tpl-adding">
            <span className={`tpl-kind is-${adding.kind}`}>{KIND_ICONS[adding.kind]}<span>{KIND_NAMES[adding.kind]}</span></span>
            <Input autoFocus aria-label={`新${KIND_NAMES[adding.kind]}名称`} placeholder={adding.kind === 'purchase' ? '要买什么，如 充电桩' : adding.kind === 'file' ? '资料名称，如 验收资料' : '要做什么，如 场地勘测'} value={adding.name} maxLength={200}
              onChange={e => setAdding({ ...adding, name: e.target.value })} onPressEnter={addItem} onBlur={addItem} onKeyDown={e => { if (e.key === 'Escape') stopAdding() }} />
          </div>
        : <div className="tpl-section-foot" onDragOver={over('item', () => ({ id: section.id, pos: 'end' }))} onDrop={land}>
            <Dropdown trigger={['click']} menu={addMenu(section.id)}><Button type="text" size="small" icon={<PlusOutlined />}>加一件事</Button></Dropdown>
          </div>)}
    </section>
  }

  const panel = selectedItem && tree ? <TemplateItemPanel key={selectedItem.id} templateId={tid} item={selectedItem} sections={sections} editable={canManage}
    flushRef={flushRef} onTree={setTree} onClose={() => setSelectedId(undefined)} onReload={load} /> : null
  const wide = screens.lg !== false

  return <div className="tpl-editor-page">
    <header className="tpl-editor-head">
      <IconAction label="返回模板库" icon={<ArrowLeftOutlined />} onClick={() => navigate('/pm/templates')} />
      <div className="tpl-editor-title">
        {editableMeta && title ? <>
          <Input className="tpl-editor-name" aria-label="模板名称" variant="borderless" value={title.name} maxLength={200} onChange={e => setTitle({ ...title, name: e.target.value })} onBlur={saveTitle} onPressEnter={e => (e.target as HTMLInputElement).blur()} />
          <Input className="tpl-editor-desc-input" aria-label="模板说明" variant="borderless" placeholder="添加说明：适合什么样的项目" value={title.description} maxLength={2000} onChange={e => setTitle({ ...title, description: e.target.value })} onBlur={saveTitle} onPressEnter={e => (e.target as HTMLInputElement).blur()} />
        </> : <><h1>{selected?.name ?? (loading ? '' : '项目模板')}</h1>{selected?.description && <p className="tpl-editor-desc">{selected.description}</p>}</>}
        <div className="tpl-editor-meta">
          {selected?.is_system ? <Tag color="blue">通用</Tag> : selected && <label className="tpl-editor-type"><CarOutlined />
            <Select aria-label="模板车型" size="small" variant="borderless" allowClear placeholder="通用（所有车型）" disabled={!canManage || busy} value={selected.vehicle_type ?? undefined} style={{ minWidth: 150 }}
              options={typeOptions.map(option => ({ ...option, disabled: takenTypes.has(String(option.value)), title: takenTypes.has(String(option.value)) ? `已有模板「${takenTypes.get(String(option.value))}」` : undefined }))}
              onChange={value => saveVehicleType(value as string | undefined)} /></label>}
          {!!selected?.usage_count && <span>已用于 {selected.usage_count} 个项目</span>}
          <span>改动自动保存，之后新建的项目按最新内容带入</span>
        </div>
      </div>
      <div className="tpl-editor-actions">
        {canCreateProject && <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate(`/pm/projects?create=1&template=${encodeURIComponent(tid)}`)}>用此模板新建项目</Button>}
        <RefreshAction label="刷新模板" loading={loading} onClick={load} />
        <Dropdown trigger={['click']} menu={{ items: moreItems, onClick: ({ key }) => {
          if (key === 'copy') setCopyName(`${selected?.name ?? '模板'} 副本`)
          if (key === 'export') void exportExcel()
          if (key === 'import') importInput.current?.click()
          if (key === 'delete') removeTemplate()
        } }}><IconAction bordered label="更多模板操作" icon={<MoreOutlined />} /></Dropdown>
        <input ref={importInput} type="file" accept=".xlsx" hidden aria-hidden="true" onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) importExcel(file) }} />
      </div>
    </header>
    {error && <Alert type="error" showIcon message={error} className="tpl-alert" closable onClose={() => setError('')} />}
    <div className="tpl-toolbar">
      <Input allowClear prefix={<SearchOutlined />} placeholder="查找事项、检查要点或文件" aria-label="查找模板内容" value={keyword} onChange={e => setKeyword(e.target.value)} />
      <span className="tpl-toolbar-note">{counts.work} 项工作 · {counts.file} 组资料 · {counts.purchase} 项采购 · 共 {counts.files} 份文件</span>
      {canManage && <span className="tpl-toolbar-actions">
        <Button icon={<PlusOutlined />} disabled={busy} onClick={() => void addSection()}>加段落</Button>
        {templates.length > 1 && <Button icon={<ImportOutlined />} onClick={openCopy}>从其他模板复制</Button>}
      </span>}
    </div>
    <div className={`tpl-split${panel && wide ? ' has-panel' : ''}`}>
      <div className="tpl-split-main">
        {!tree && loading ? <Skeleton active paragraph={{ rows: 8 }} />
          : !sections.length ? <Empty description="这个模板还没有内容">{canManage && <Button type="primary" icon={<PlusOutlined />} onClick={() => void addSection()}>加第一个段落</Button>}</Empty>
          : <div className="tpl-sections">{sections.map(sectionBlock)}</div>}
        {term && tree && !allItems.some(hit) && <Empty description={`没有找到「${keyword.trim()}」`} />}
      </div>
      {wide && panel}
    </div>
    {!wide && <Drawer open={!!panel} placement="bottom" height="88%" closable={false} onClose={() => void select(undefined)} styles={{ body: { padding: 0 } }} destroyOnHidden>{panel}</Drawer>}

    <Modal destroyOnHidden title="复制为新模板" open={copyName !== undefined} onCancel={() => { if (!busy) setCopyName(undefined) }} onOk={() => void copyTemplate()} confirmLoading={busy} okText="创建模板" cancelText="取消" okButtonProps={{ disabled: !copyName?.trim() }}>
      <p className="tpl-modal-note">以「{selected?.name}」的全部内容为起点。</p>
      <Input aria-label="新模板名称" value={copyName} onChange={e => setCopyName(e.target.value)} maxLength={200} />
    </Modal>


    <Modal destroyOnHidden title="从其他模板复制事项" open={!!copyFrom} width={680} onCancel={() => { if (!busy) setCopyFrom(undefined) }} onOk={() => void doCopy()} confirmLoading={busy}
      okText={copyFrom?.chosen.length ? `复制 ${copyFrom.chosen.length} 件事` : '复制'} cancelText="取消" okButtonProps={{ disabled: !copyFrom?.chosen.length }}>
      <div className="tpl-form-pair">
        <label className="tpl-field"><span>来源模板</span><Select aria-label="来源模板" value={copyFrom?.source} onChange={source => setCopyFrom(old => old && { ...old, source, tree: undefined, chosen: [] })}
          options={templates.filter(t => t.id !== tid).map(t => ({ value: t.id, label: t.name }))} /></label>
        <label className="tpl-field"><span>放到哪个段落</span><Select aria-label="放到哪个段落" allowClear placeholder="同名段落（没有就放最后一段）" value={copyFrom?.target}
          onChange={target => setCopyFrom(old => old && { ...old, target })} options={sections.map(section => ({ value: section.id, label: section.title }))} /></label>
      </div>
      {!copyFrom?.tree ? <Skeleton active paragraph={{ rows: 4 }} /> : <div className="tpl-copy-list">
        {copyFrom.tree.sections.map(section => {
          const ids = section.items.map(item => item.id); const chosen = ids.filter(id => copyFrom.chosen.includes(id))
          return <fieldset key={section.id}>
            <legend><Checkbox checked={!!ids.length && chosen.length === ids.length} indeterminate={!!chosen.length && chosen.length < ids.length} disabled={!ids.length}
              onChange={e => setCopyFrom(old => old && { ...old, chosen: e.target.checked ? [...new Set([...old.chosen, ...ids])] : old.chosen.filter(id => !ids.includes(id)) })}>{section.title}</Checkbox></legend>
            {section.items.map(item => <Checkbox key={item.id} checked={copyFrom.chosen.includes(item.id)}
              onChange={e => setCopyFrom(old => old && { ...old, chosen: e.target.checked ? [...old.chosen, item.id] : old.chosen.filter(id => id !== item.id) })}>
              <span className={`tpl-kind is-${item.kind}`}>{KIND_ICONS[item.kind]}<span>{KIND_NAMES[item.kind]}</span></span> {item.name}
              <span className="tpl-copy-facts">{rowFacts(item).join(' · ')}</span>
            </Checkbox>)}
          </fieldset>
        })}
      </div>}
    </Modal>
    {busy && <span className="sr-only" role="status">正在保存</span>}
  </div>
}
