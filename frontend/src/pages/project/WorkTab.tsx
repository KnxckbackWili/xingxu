import { useMemo, useState } from 'react'
import type { Snapshot, WorkItem } from '../../api/types'
import Grid, { AddLine, TextCell, type Column } from '../../components/Grid'
import { listOps } from '../../sync/rows'
import { stamp } from '../../utils/format'
import type { TabProps } from './context'

export default function WorkTab({ snap, live, base, me, todo }: TabProps) {
  const [extra, setExtra] = useState<string[]>([])
  const ops = listOps<Snapshot, WorkItem>(live, base, 'work', 'work', { stage: '阶段', name: '工作内容', note: '备注', done: '做完' }, { done: 'done' }, me.id)
  const stages = useMemo(() => {
    const map = new Map<string, WorkItem[]>()
    for (const row of snap.work) map.set(row.stage, [...(map.get(row.stage) ?? []), row])
    for (const name of extra) if (!map.has(name)) map.set(name, [])
    return [...map.entries()]
  }, [snap.work, extra])
  const columns: Column<WorkItem>[] = [
    { key: 'done', title: '做完', label: '做完', type: 'check', hint: (row) => stamp(snap.people, row.done_by, row.done_at) },
    { key: 'name', title: '工作内容', label: '工作内容', primary: true, required: true, multiline: true },
    { key: 'note', title: '备注', label: '备注', multiline: true, width: '32%' },
  ]
  const rename = async (from: string, rows: WorkItem[], to: string) => {
    setExtra((current) => current.map((name) => (name === from ? to : name)))
    await Promise.all(rows.map((row) => ops.set(row, 'stage', to)))
  }
  return <>
    {stages.length === 0 && <p className="tab-empty">还没有工作。先在下面写一个阶段名，再往里加工作。</p>}
    {stages.map(([stage, rows]) => {
      const shown = todo ? rows.filter((row) => !row.done) : rows
      if (todo && rows.length > 0 && shown.length === 0) return null
      return <section key={stage || '-'} className="stage" aria-label={stage || '未分阶段'}>
        <header className="stage-head">
          <TextCell value={stage} label="阶段名称" placeholder="未分阶段" strong onCommit={(next) => rename(stage, rows, next)} />
          <span className="stage-count">{rows.filter((row) => row.done).length} / {rows.length}</span>
        </header>
        <Grid label={`${stage || '未分阶段'}的工作`} rows={shown} columns={columns} rowClass={(row) => (row.done ? 'is-done' : '')}
          onSet={(row, key, value) => ops.set(row, key as keyof WorkItem & string, value)}
          onAdd={(text) => ops.add({ stage, name: text, note: '', done: false })} addPlaceholder="输入工作内容后回车，新增一项"
          onDelete={(row) => void ops.remove(row)} onMove={(row, offset) => void ops.move(rows, row, offset)} onReorder={todo ? undefined : (ids) => void ops.reorder(ids)} />
      </section>
    })}
    <div className="grid-wrap stage-new"><AddLine placeholder="输入新阶段的名称后回车" onAdd={(text) => setExtra((current) => (current.includes(text) ? current : [...current, text]))} /></div>
  </>
}
