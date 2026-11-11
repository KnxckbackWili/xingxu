import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { Dropdown, Input, message } from 'antd'
import { ArrowDownOutlined, ArrowUpOutlined, CheckOutlined, DeleteOutlined, DownOutlined, HolderOutlined, MoreOutlined, RightOutlined } from '@ant-design/icons'
import './Grid.css'

type Row = { id: string }

export interface Column<R> {
  key: string
  title: ReactNode
  /** Plain name of the column: the label on a phone card and for screen readers. */
  label: string
  type?: 'text' | 'number' | 'check' | 'select' | 'date' | 'custom'
  width?: number | string
  /** Suggestions while typing; anything else may still be typed. */
  options?: string[]
  /** The only values a select may take. */
  choices?: { value: string; label: string }[]
  multiline?: boolean
  required?: boolean
  placeholder?: string
  render?: (row: R) => ReactNode
  /** The heading of a phone card. */
  primary?: boolean
  /** For ticks: who ticked and when. */
  hint?: (row: R) => string
  /** Value of a cell that is not a plain field of the row (a tick on the vehicle table). */
  value?: (row: R) => unknown
}

interface GridProps<R extends Row> {
  label: string
  rows: R[]
  columns: Column<R>[]
  onSet: (row: R, key: string, value: unknown) => Promise<unknown> | void
  onAdd?: (text: string) => Promise<unknown> | void
  addPlaceholder?: string
  onDelete?: (row: R) => void
  onMove?: (row: R, offset: number) => void
  onReorder?: (ids: string[]) => void
  expand?: (row: R) => ReactNode
  expandLabel?: (row: R) => string
  rowClass?: (row: R) => string
  empty?: string
}

function useDraft<T>(value: T) {
  const [draft, setDraft] = useState(value)
  const editing = useRef(false)
  // Someone else's change shows in the cell, unless this person is typing in it right now.
  useEffect(() => { if (!editing.current) setDraft(value) }, [value])
  return { draft, setDraft, editing }
}

function leave(event: KeyboardEvent<HTMLElement>, revert: () => void, multiline = false) {
  if (event.key === 'Escape') { revert(); (event.target as HTMLElement).blur() }
  if (event.key === 'Enter' && !event.nativeEvent.isComposing && (!multiline || event.ctrlKey || event.metaKey)) (event.target as HTMLElement).blur()
}

export function TextCell({ value, label, onCommit, options, multiline, required, placeholder, strong }: {
  value: string; label: string; onCommit: (value: string) => Promise<unknown> | void
  options?: string[]; multiline?: boolean; required?: boolean; placeholder?: string; strong?: boolean
}) {
  const { draft, setDraft, editing } = useDraft(value ?? '')
  const [state, setState] = useState<'' | 'saving' | 'saved'>('')
  const list = useId()
  const skip = useRef(false)
  const commit = () => {
    editing.current = false
    if (skip.current) { skip.current = false; return }
    const next = draft.trim()
    if (next === (value ?? '')) { setDraft(value ?? ''); return }
    if (required && !next) { setDraft(value ?? ''); message.warning(`${label}不能为空`); return }
    setDraft(next)
    const saving = onCommit(next)
    if (saving) {
      setState('saving')
      void saving.then(() => { setState('saved'); window.setTimeout(() => setState(''), 1200) }, () => setState(''))
    }
  }
  const revert = () => { skip.current = true; setDraft(value ?? '') }
  const shared = {
    'aria-label': label, value: draft, placeholder,
    className: `cell-input${strong ? ' is-strong' : ''}`,
    onFocus: () => { editing.current = true },
    onBlur: commit,
  }
  return <span className={`cell${state ? ` is-${state}` : ''}`}>
    {multiline
      ? <Input.TextArea {...shared} variant="borderless" autoSize={{ minRows: 1, maxRows: 8 }} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => leave(event, revert, true)} />
      : <input {...shared} list={options?.length ? list : undefined} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => leave(event, revert)} />}
    {options?.length ? <datalist id={list}>{options.map((option) => <option key={option} value={option} />)}</datalist> : null}
  </span>
}

function NumberCell({ value, label, onCommit }: { value: number | null; label: string; onCommit: (value: number | null) => void }) {
  const text = value === null || value === undefined ? '' : String(value)
  const { draft, setDraft, editing } = useDraft(text)
  const commit = () => {
    editing.current = false
    const next = draft.trim()
    if (next === text) return
    if (next === '') { onCommit(null); return }
    const number = Number(next)
    if (!Number.isFinite(number)) { setDraft(text); message.warning(`${label}应为数字`); return }
    setDraft(String(number))
    onCommit(number)
  }
  return <span className="cell"><input className="cell-input is-number" aria-label={label} inputMode="decimal" value={draft}
    onFocus={() => { editing.current = true }} onBlur={commit} onChange={(event) => setDraft(event.target.value)}
    onKeyDown={(event) => leave(event, () => setDraft(text))} /></span>
}

export function CheckCell({ checked, label, hint, onToggle, text }: { checked: boolean; label: string; hint?: string; onToggle: (next: boolean) => void; text?: string }) {
  return <button type="button" role="checkbox" aria-checked={checked} aria-label={label} title={hint || undefined}
    className={`cell-check${checked ? ' is-on' : ''}`} onClick={() => onToggle(!checked)}>
    <span className="cell-check-box">{checked && <CheckOutlined />}</span>{text && <span className="cell-check-text">{text}</span>}
  </button>
}

function renderCell<R extends Row>(column: Column<R>, row: R, onSet: GridProps<R>['onSet']) {
  const raw = column.value ? column.value(row) : (row as Record<string, unknown>)[column.key]
  const label = column.label
  switch (column.type ?? 'text') {
    case 'custom': return column.render?.(row)
    case 'check': return <CheckCell checked={!!raw} label={label} text={label} hint={column.hint?.(row)} onToggle={(next) => void onSet(row, column.key, next)} />
    case 'number': return <NumberCell value={(raw as number | null) ?? null} label={label} onCommit={(next) => void onSet(row, column.key, next)} />
    case 'date': return <span className="cell"><input type="date" className="cell-input is-date" aria-label={label} value={(raw as string | null) ?? ''}
      onChange={(event) => void onSet(row, column.key, event.target.value || null)} /></span>
    case 'select': return <span className="cell"><select className="cell-input" aria-label={label} value={(raw as string | null) ?? ''}
      onChange={(event) => void onSet(row, column.key, event.target.value || null)}>
      <option value="">—</option>{column.choices?.map((choice) => <option key={choice.value} value={choice.value}>{choice.label}</option>)}
    </select></span>
    default: return <TextCell value={(raw as string) ?? ''} label={label} options={column.options} multiline={column.multiline} required={column.required}
      placeholder={column.placeholder} strong={column.primary} onCommit={(next) => onSet(row, column.key, next)} />
  }
}

/** The line at the bottom of a list: type, press Enter, the row exists. */
export function AddLine({ placeholder, onAdd, label }: { placeholder: string; onAdd: (text: string) => Promise<unknown> | void; label?: string }) {
  const [text, setText] = useState('')
  const submit = () => {
    const value = text.trim()
    if (!value) return
    setText('')
    void Promise.resolve(onAdd(value)).catch(() => setText(value))
  }
  return <div className="grid-add">
    <input aria-label={label ?? placeholder} placeholder={placeholder} value={text} enterKeyHint="done" onChange={(event) => setText(event.target.value)}
      onKeyDown={(event) => { if (event.key === 'Enter' && !event.nativeEvent.isComposing) { event.preventDefault(); submit() } }} />
    {text.trim() && <button type="button" className="grid-add-go" onClick={submit}>添加</button>}
  </div>
}

/**
 * The one editable table of the app. A cell is edited where it stands and saves when left;
 * on a phone every row becomes a card.
 */
export default function Grid<R extends Row>({ label, rows, columns, onSet, onAdd, addPlaceholder, onDelete, onMove, onReorder, expand, expandLabel, rowClass, empty }: GridProps<R>) {
  const [open, setOpen] = useState<Set<string>>(new Set())
  const dragged = useRef('')
  const tools = !!(onDelete || onMove)
  const span = columns.length + (expand ? 1 : 0) + (onReorder ? 1 : 0) + (tools ? 1 : 0)
  const toggle = (id: string) => setOpen((current) => { const next = new Set(current); if (next.has(id)) next.delete(id); else next.add(id); return next })
  const drop = (target: string) => {
    const source = dragged.current
    dragged.current = ''
    if (!source || source === target || !onReorder) return
    const ids = rows.map((row) => row.id).filter((id) => id !== source)
    ids.splice(ids.indexOf(target), 0, source)
    onReorder(ids)
  }
  return <div className="grid-wrap">
    <table className="grid" aria-label={label}>
      <thead><tr>
        {onReorder && <th className="grid-handle" aria-hidden="true" />}
        {expand && <th className="grid-expand" aria-hidden="true" />}
        {columns.map((column) => <th key={column.key} style={{ width: column.width }} className={`is-${column.type ?? 'text'}`}>{column.title}</th>)}
        {tools && <th className="grid-tools"><span className="sr-only">操作</span></th>}
      </tr></thead>
      <tbody>
        {rows.length === 0 && empty && <tr className="grid-empty"><td colSpan={span}>{empty}</td></tr>}
        {rows.map((row, index) => [
          <tr key={row.id} className={rowClass?.(row)} onDragOver={onReorder ? (event) => event.preventDefault() : undefined} onDrop={onReorder ? () => drop(row.id) : undefined}>
            {onReorder && <td className="grid-handle" draggable onDragStart={() => { dragged.current = row.id }} title="拖动调整顺序"><HolderOutlined /></td>}
            {expand && <td className="grid-expand"><button type="button" className="grid-icon" aria-expanded={open.has(row.id)} aria-label={expandLabel?.(row) ?? '展开'} onClick={() => toggle(row.id)}>
              {open.has(row.id) ? <DownOutlined /> : <RightOutlined />}{expandLabel && <span className="grid-expand-text">{expandLabel(row)}</span>}</button></td>}
            {columns.map((column) => <td key={column.key} data-label={column.label} className={`is-${column.type ?? 'text'}${column.primary ? ' is-primary' : ''}${column.multiline ? ' is-wide' : ''}`}>{renderCell(column, row, onSet)}</td>)}
            {tools && <td className="grid-tools"><Dropdown trigger={['click']} placement="bottomRight" menu={{ items: [
              ...(onMove ? [{ key: 'up', icon: <ArrowUpOutlined />, label: '上移', disabled: index === 0, onClick: () => onMove(row, -1) },
                { key: 'down', icon: <ArrowDownOutlined />, label: '下移', disabled: index === rows.length - 1, onClick: () => onMove(row, 1) }] : []),
              ...(onDelete ? [{ key: 'delete', icon: <DeleteOutlined />, label: '删除', danger: true, onClick: () => onDelete(row) }] : []),
            ] }}><button type="button" className="grid-icon" aria-label="更多操作"><MoreOutlined /></button></Dropdown></td>}
          </tr>,
          expand && open.has(row.id) && <tr key={`${row.id}-more`} className="grid-more"><td colSpan={span}>{expand(row)}</td></tr>,
        ])}
      </tbody>
    </table>
    {onAdd && <AddLine placeholder={addPlaceholder ?? '在这里输入，回车添加'} onAdd={onAdd} />}
  </div>
}
