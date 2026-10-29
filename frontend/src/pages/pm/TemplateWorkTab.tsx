import { useRef, useState, type DragEvent, type Dispatch, type SetStateAction } from 'react'
import type { InputRef } from 'antd'
import { Dropdown, Empty, Input, Modal, message } from 'antd'
import { CarOutlined, CheckCircleOutlined, DeleteOutlined, DownOutlined, EditOutlined, HolderOutlined, MoreOutlined, PaperClipOutlined, PlusOutlined, RightOutlined, SearchOutlined } from '@ant-design/icons'
import { api, errMsg } from '../../api/client'
import type { WorkItem, WorkPhase } from '../../api/workItems'
import { STAGES, STAGE_NAME, stageIndex, stageLabel } from '../../constants/stages'
import { ensureVerifiedAccount } from '../../utils/verifiedAccount'
import { useAuth } from '../../stores/auth'
import { IconAction } from '../../components/IconAction'
import TemplateWorkPanel, { type SaveState } from './TemplateWorkPanel'

type Step = { key: string; name: string }
type Props = {
  templateId: string; phases: WorkPhase[]; setPhases: Dispatch<SetStateAction<WorkPhase[]>>; steps: Step[]; canManage: boolean; loading: boolean
  onReload: () => Promise<void> | void; onCreateStep: (name: string) => Promise<string>
}
type Drag = { type: 'item' | 'group'; id: string }
type Drop = { id: string; pos: 'before' | 'after' | 'end' }

export const stageOf = (phase: WorkPhase) => phase.stage_key ?? '6'
const sortByStage = (groups: WorkPhase[]) => groups.map((g, i) => ({ g, i })).sort((a, b) => stageIndex(stageOf(a.g)) - stageIndex(stageOf(b.g)) || a.i - b.i).map(row => row.g)
const blank = (phase_id: string, name: string) => ({ phase_id, name, kind: 'other', description: '', group_label: '', vehicle_step_key: null, applicable_vehicle_types: [], scope_conditions: [], checks: [] })

/**
 * Template work as an editable outline: stage → group → item. Names are typed in place, Enter keeps adding,
 * rows and groups are dragged to reorder or move, and the selected item is edited in the side panel. Everything saves itself.
 */
export default function TemplateWorkTab({ templateId, phases, setPhases, steps, canManage, loading, onReload, onCreateStep }: Props) {
  const { user } = useAuth()
  const [keyword, setKeyword] = useState('')
  const [selectedId, setSelectedId] = useState<string>()
  const [adding, setAdding] = useState<string>()
  const [addingGroup, setAddingGroup] = useState<string>()
  const [renaming, setRenaming] = useState<string>()
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [saves, setSaves] = useState<Record<string, SaveState>>({})
  const [drop, setDrop] = useState<Drop | null>(null)
  const drag = useRef<Drag | null>(null)
  const latest = useRef(phases); latest.current = phases
  const queues = useRef(new Map<string, Promise<unknown>>())
  const term = keyword.trim().toLowerCase()
  const matches = (item: WorkItem) => !term || `${item.name} ${item.group_label ?? ''} ${item.description ?? ''}`.toLowerCase().includes(term)
  const located = phases.flatMap(phase => phase.work_items.map((item, index) => ({ item, phase, index })))
  const selected = located.find(row => row.item.id === selectedId)
  const editable = canManage && !term

  const fail = (e: unknown) => message.error(errMsg(e))
  const guard = () => { if (!canManage) throw new Error('没有模板维护权限'); ensureVerifiedAccount(user?.id) }
  const placeItem = (saved: WorkItem) => setPhases(old => {
    const from = old.find(p => p.work_items.some(w => w.id === saved.id))
    if (!from || from.id === saved.phase_id) return old.map(p => p.id === from?.id ? { ...p, work_items: p.work_items.map(w => w.id === saved.id ? saved : w) } : p)
    return old.map(p => p.id === from.id ? { ...p, work_items: p.work_items.filter(w => w.id !== saved.id) } : p.id === saved.phase_id ? { ...p, work_items: [...p.work_items, saved] } : p)
  })

  const patchItem = (id: string, patch: Record<string, unknown>) => {
    const run = (queues.current.get(id) ?? Promise.resolve()).then(async () => {
      const current = latest.current.flatMap(p => p.work_items).find(w => w.id === id)
      if (!current) return
      setSaves(old => ({ ...old, [id]: { state: 'saving' } }))
      try {
        guard()
        const result = await api.put(`/templates/${templateId}/work-items/${id}`, { ...patch, version: current.version })
        placeItem(result.data); setSaves(old => ({ ...old, [id]: { state: 'saved' } }))
      } catch (e) { setSaves(old => ({ ...old, [id]: { state: 'error', error: errMsg(e) } })) }
    })
    queues.current.set(id, run)
    return run
  }
  const createItem = async (phaseId: string, name: string) => {
    try { guard(); const result = await api.post(`/templates/${templateId}/work-items`, blank(phaseId, name)); setPhases(old => old.map(p => p.id === phaseId ? { ...p, work_items: [...p.work_items, result.data] } : p)) }
    catch (e) { fail(e) }
  }
  const deleteItem = async (id: string) => {
    try { guard(); await api.delete(`/templates/${templateId}/work-items/${id}`); setSelectedId(undefined); setPhases(old => old.map(p => ({ ...p, work_items: p.work_items.filter(w => w.id !== id) }))) }
    catch (e) { fail(e) }
  }
  const createGroup = async (stage: string, name: string) => {
    try {
      guard(); const result = await api.post(`/templates/${templateId}/work-phases`, { name, stage_key: stage })
      setPhases(old => sortByStage([...old, { ...result.data, work_items: [] }])); setAdding(result.data.id)
    } catch (e) { fail(e) }
  }
  const updateGroup = async (phase: WorkPhase, change: { name?: string; stage_key?: string }) => {
    try { guard(); await api.put(`/templates/${templateId}/work-phases/${phase.id}`, change); setPhases(old => sortByStage(old.map(p => p.id === phase.id ? { ...p, ...change } : p))) }
    catch (e) { fail(e) }
  }
  const deleteGroup = (phase: WorkPhase) => Modal.confirm({ title: `删除空分组「${phase.name}」？`, okText: '删除', okButtonProps: { danger: true }, cancelText: '取消', onOk: async () => {
    try { guard(); await api.delete(`/templates/${templateId}/work-phases/${phase.id}`); setPhases(old => old.filter(p => p.id !== phase.id)) } catch (e) { fail(e) }
  } })
  const saveLayout = async (next: WorkPhase[]) => {
    const previous = latest.current
    setPhases(next)
    try {
      guard()
      const result = await api.put(`/templates/${templateId}/work-layout`, { groups: next.map(p => ({ id: p.id, stage_key: stageOf(p), item_ids: p.work_items.map(w => w.id) })) })
      setPhases(result.data.phases)
    } catch (e) { setPhases(previous); fail(e); if ((e as any)?.response?.status === 409) void onReload() }
  }
  const moveItem = (id: string, target: Drop) => {
    const item = latest.current.flatMap(p => p.work_items).find(w => w.id === id)
    if (!item || target.id === id) return
    const without = latest.current.map(p => ({ ...p, work_items: p.work_items.filter(w => w.id !== id) }))
    const next = without.map(p => {
      if (target.pos === 'end') return p.id === target.id ? { ...p, work_items: [...p.work_items, item] } : p
      const index = p.work_items.findIndex(w => w.id === target.id)
      if (index < 0) return p
      const at = target.pos === 'before' ? index : index + 1
      return { ...p, work_items: [...p.work_items.slice(0, at), item, ...p.work_items.slice(at)] }
    })
    void saveLayout(next)
  }
  const moveGroup = (id: string, target: { groupId?: string; pos?: 'before' | 'after'; stage?: string }) => {
    const group = latest.current.find(p => p.id === id)
    if (!group || target.groupId === id) return
    const rest = latest.current.filter(p => p.id !== id)
    if (target.stage) return void saveLayout(sortByStage([...rest, { ...group, stage_key: target.stage }]))
    const index = rest.findIndex(p => p.id === target.groupId)
    if (index < 0) return
    const anchor = rest[index]; const at = target.pos === 'before' ? index : index + 1
    void saveLayout(sortByStage([...rest.slice(0, at), { ...group, stage_key: stageOf(anchor) }, ...rest.slice(at)]))
  }
  const nudge = (id: string, delta: -1 | 1) => {
    const row = located.find(r => r.item.id === id); if (!row) return
    const neighbour = row.phase.work_items[row.index + delta]; if (!neighbour) return
    moveItem(id, { id: neighbour.id, pos: delta < 0 ? 'before' : 'after' })
  }

  const dragProps = (kind: Drag['type'], id: string) => editable ? {
    draggable: true,
    onDragStart: (e: DragEvent) => { drag.current = { type: kind, id }; e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', id); e.stopPropagation() },
    onDragEnd: () => { drag.current = null; setDrop(null) },
  } : {}
  const half = (e: DragEvent) => { const box = (e.currentTarget as HTMLElement).getBoundingClientRect(); return e.clientY - box.top < box.height / 2 ? 'before' as const : 'after' as const }
  const over = (accept: Drag['type'], target: Drop | ((e: DragEvent) => Drop)) => (e: DragEvent) => {
    if (drag.current?.type !== accept) return
    e.preventDefault(); e.stopPropagation(); e.dataTransfer.dropEffect = 'move'
    const next = typeof target === 'function' ? target(e) : target
    setDrop(old => old && old.id === next.id && old.pos === next.pos ? old : next)
  }
  const land = (action: () => void) => (e: DragEvent) => { if (!drag.current) return; e.preventDefault(); e.stopPropagation(); action(); drag.current = null; setDrop(null) }
  const marker = (id: string) => drop?.id === id ? ` is-drop-${drop.pos}` : ''

  const inlineInput = (label: string, placeholder: string, onSubmit: (value: string) => Promise<void> | void, onDone: () => void, keepOpen = false, initial = '') =>
    <InlineInput label={label} placeholder={placeholder} onSubmit={onSubmit} onDone={onDone} keepOpen={keepOpen} initial={initial} />

  const itemRow = (phase: WorkPhase) => (item: WorkItem) => <li key={item.id} className={`tpl-node${selectedId === item.id ? ' is-selected' : ''}${marker(item.id)}`} {...dragProps('item', item.id)}
    onDragOver={over('item', e => ({ id: item.id, pos: half(e) }))} onDrop={land(() => drop && moveItem(drag.current!.id, drop))}>
    <button type="button" className="tpl-node-row" aria-current={selectedId === item.id ? 'true' : undefined} onClick={() => setSelectedId(item.id)}>
      {editable && <HolderOutlined className="tpl-handle" aria-hidden />}
      <span className="tpl-node-name">{item.name}</span>
      {item.group_label && item.group_label !== phase.name && <span className="tpl-row-tag">{item.group_label}</span>}
      <span className="tpl-row-meta">
        {item.kind === 'vehicle' && <span className="tpl-meta is-vehicle"><CarOutlined aria-hidden />{steps.find(s => s.key === item.vehicle_step_key)?.name ?? '未关联环节'}</span>}
        {!!item.check_definitions?.length && <span className="tpl-meta" title="检查要求"><CheckCircleOutlined aria-hidden />{item.check_definitions.length}</span>}
        {!!item.reference_docs.length && <span className="tpl-meta" title="参考文档"><PaperClipOutlined aria-hidden />{item.reference_docs.length}</span>}
      </span>
    </button>
  </li>

  const groupMenu = (phase: WorkPhase, index: number, siblings: WorkPhase[]) => ({
    items: [
      { key: 'rename', icon: <EditOutlined />, label: '重命名' },
      { key: 'up', label: '上移分组', disabled: index === 0 },
      { key: 'down', label: '下移分组', disabled: index === siblings.length - 1 },
      { key: 'move', label: '移到其他阶段', children: STAGES.filter(s => s.key !== stageOf(phase)).map(s => ({ key: `move:${s.key}`, label: `移到 ${s.key} · ${s.name}` })) },
      { type: 'divider' as const },
      { key: 'delete', icon: <DeleteOutlined />, danger: true, disabled: phase.work_items.length > 0, label: phase.work_items.length ? '删除分组（先移走工作项）' : '删除分组' },
    ],
    onClick: ({ key }: { key: string }) => {
      if (key === 'rename') setRenaming(phase.id)
      if (key === 'up') moveGroup(phase.id, { groupId: siblings[index - 1].id, pos: 'before' })
      if (key === 'down') moveGroup(phase.id, { groupId: siblings[index + 1].id, pos: 'after' })
      if (key.startsWith('move:')) void updateGroup(phase, { stage_key: key.slice(5) }).then(() => message.success(`已移到「${STAGE_NAME[key.slice(5)]}」`))
      if (key === 'delete') deleteGroup(phase)
    },
  })

  const groupBlock = (phase: WorkPhase, index: number, siblings: WorkPhase[]) => {
    const items = phase.work_items.filter(matches)
    if (term && !items.length) return null
    const open = !!term || !collapsed.has(phase.id)
    return <div key={phase.id} className={`tpl-group${marker(phase.id)}`} role="region" aria-label={`工作分组：${phase.name}`}
      onDragOver={over('group', e => ({ id: phase.id, pos: half(e) }))} onDrop={land(() => drop && drop.pos !== 'end' && moveGroup(drag.current!.id, { groupId: phase.id, pos: drop.pos }))}>
      <div className={`tpl-group-head${marker(`end:${phase.id}`)}`} {...dragProps('group', phase.id)}
        onDragOver={over('item', { id: `end:${phase.id}`, pos: 'end' })} onDrop={land(() => drag.current?.type === 'item' && moveItem(drag.current.id, { id: phase.id, pos: 'end' }))}>
        <button type="button" className="tpl-collapse" aria-expanded={open} aria-label={`${open ? '收起' : '展开'}分组「${phase.name}」`}
          onClick={() => setCollapsed(old => { const next = new Set(old); if (next.has(phase.id)) next.delete(phase.id); else next.add(phase.id); return next })}>{open ? <DownOutlined /> : <RightOutlined />}</button>
        {renaming === phase.id ? inlineInput('分组名称', '分组名称', name => updateGroup(phase, { name }), () => setRenaming(undefined), false, phase.name)
          : <strong onDoubleClick={() => editable && setRenaming(phase.id)} title={editable ? '双击改名' : undefined}>{phase.name}</strong>}
        <span className="tpl-group-count">{items.length}</span>
        {canManage && <span className="tpl-group-actions">
          <IconAction label={`在「${phase.name}」添加工作项`} icon={<PlusOutlined />} onClick={() => { setCollapsed(old => { const next = new Set(old); next.delete(phase.id); return next }); setAdding(phase.id) }} />
          <Dropdown trigger={['click']} menu={groupMenu(phase, index, siblings)}><IconAction label={`分组「${phase.name}」操作`} icon={<MoreOutlined />} /></Dropdown>
        </span>}
      </div>
      {open && <ul className="tpl-nodes">
        {items.map(itemRow(phase))}
        {adding === phase.id && <li className="tpl-node is-adding">{inlineInput('新工作项名称', '输入工作项名称，回车继续添加，Esc 结束', name => createItem(phase.id, name), () => setAdding(undefined), true)}</li>}
        {!items.length && adding !== phase.id && <li className="tpl-node-empty">还没有工作项{editable && '，可把工作拖到这里'}</li>}
      </ul>}
    </div>
  }

  const panelRow = selected
  return <div className={`tpl-split${selected ? ' has-panel' : ''}`}>
    <div className="tpl-split-main">
      <div className="tpl-toolbar">
        <Input allowClear prefix={<SearchOutlined />} placeholder="查找工作项" aria-label="查找工作项" value={keyword} onChange={e => setKeyword(e.target.value)} />
        {editable && <span className="tpl-toolbar-note">拖动 <HolderOutlined /> 调整顺序，或拖到别的分组、阶段</span>}
      </div>
      {term && !located.some(row => matches(row.item)) ? <Empty description="没有匹配的工作项" />
        : <div className="tpl-outline-body">{STAGES.map(stage => {
          const groups = phases.filter(p => stageOf(p) === stage.key)
          const count = groups.reduce((n, p) => n + p.work_items.filter(matches).length, 0)
          if (term && !count) return null
          return <section key={stage.key} className={`tpl-stage-section${marker(`stage:${stage.key}`)}`} aria-label={stageLabel(stage.key)}
            onDragOver={over('group', { id: `stage:${stage.key}`, pos: 'end' })} onDrop={land(() => drag.current?.type === 'group' && moveGroup(drag.current.id, { stage: stage.key }))}>
            <header className="tpl-stage-head">
              <h3><span className="tpl-stage-key">{stage.key}</span>{stage.name}</h3>
              <span className="tpl-stage-meta">{count ? `${count} 项` : '暂无工作'}</span>
              {canManage && <span className="tpl-stage-actions"><IconAction label={`在「${stage.name}」添加工作分组`} icon={<PlusOutlined />} disabled={loading} onClick={() => setAddingGroup(stage.key)} /></span>}
            </header>
            {groups.map((phase, index) => groupBlock(phase, index, groups))}
            {addingGroup === stage.key && <div className="tpl-group is-adding">{inlineInput('新分组名称', '输入分组名称后回车', name => createGroup(stage.key, name), () => setAddingGroup(undefined))}</div>}
          </section>
        })}</div>}
    </div>
    {panelRow ? <TemplateWorkPanel key={panelRow.item.id} item={panelRow.item} phases={phases} steps={steps} templateId={templateId} canManage={canManage} save={saves[panelRow.item.id]}
      canMove={{ up: panelRow.index > 0 && !term, down: panelRow.index < panelRow.phase.work_items.length - 1 && !term }}
      onPatch={patch => patchItem(panelRow.item.id, patch)} onDelete={() => void deleteItem(panelRow.item.id)} onMove={delta => nudge(panelRow.item.id, delta)}
      onCreateStep={onCreateStep} onClose={() => setSelectedId(undefined)}
      onUpload={file => { const body = new FormData(); body.append('file', file); void (async () => { try { guard(); await api.post(`/templates/${templateId}/tasks/${panelRow.item.id}/reference-docs`, body); await onReload() } catch (e) { fail(e) } })() }}
      onRemoveRef={(id) => void (async () => { try { guard(); await api.delete(`/templates/${templateId}/tasks/${panelRow.item.id}/reference-docs/${id}`); await onReload() } catch (e) { fail(e) } })()} />
      : <aside className="tpl-panel is-empty" aria-label="编辑说明">
        <p><strong>点左边任意一项开始编辑</strong></p>
        <ul>
          <li>改动会自动保存，不需要点保存。</li>
          {canManage && <li>分组右侧 <PlusOutlined /> 添加工作项，回车可连续添加。</li>}
          {canManage && <li>拖动 <HolderOutlined /> 调整顺序，或拖到别的分组、阶段。</li>}
          {canManage && <li>双击分组名改名；阶段标题右侧 <PlusOutlined /> 添加分组。</li>}
        </ul>
      </aside>}
  </div>
}

/** A name typed in place. Enter submits (and with keepOpen clears for the next one); leaving the field submits once; Esc cancels. */
function InlineInput({ label, placeholder, onSubmit, onDone, keepOpen, initial }: { label: string; placeholder: string; onSubmit: (value: string) => Promise<void> | void; onDone: () => void; keepOpen: boolean; initial: string }) {
  const input = useRef<InputRef>(null)
  const busy = useRef(false)
  const closed = useRef(false)
  const finish = () => { if (!closed.current) { closed.current = true; onDone() } }
  const submit = async (value: string, close: boolean) => {
    if (busy.current || closed.current) return
    if (!value || value === initial) return finish()
    busy.current = true
    try { await onSubmit(value) } finally { busy.current = false }
    if (close) finish(); else if (input.current?.input) { input.current.input.value = ''; input.current.focus() }
  }
  return <Input ref={input} autoFocus size="small" aria-label={label} placeholder={placeholder} defaultValue={initial} maxLength={200} className="tpl-inline-input"
    onPressEnter={e => void submit(e.currentTarget.value.trim(), !keepOpen)}
    onKeyDown={e => { if (e.key === 'Escape') finish() }}
    onBlur={e => { if (!busy.current) void submit(e.currentTarget.value.trim(), true) }} />
}
