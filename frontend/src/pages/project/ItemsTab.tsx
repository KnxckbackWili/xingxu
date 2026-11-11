import type { Item, Snapshot } from '../../api/types'
import Grid, { type Column } from '../../components/Grid'
import { listOps } from '../../sync/rows'
import { stamp } from '../../utils/format'
import type { TabProps } from './context'

export default function ItemsTab({ snap, live, base, me, todo }: TabProps) {
  const ops = listOps<Snapshot, Item>(live, base, 'items', 'items', { name: '名称', spec: '规格', quantity: '数量', unit: '单位', note: '备注', arrived: '到了' }, { arrived: 'arrived' }, me.id)
  const columns: Column<Item>[] = [
    { key: 'arrived', title: '到了', label: '到了', type: 'check', hint: (row) => stamp(snap.people, row.arrived_by, row.arrived_at) },
    { key: 'name', title: '名称', label: '名称', primary: true, required: true, width: '26%' },
    { key: 'spec', title: '规格', label: '规格', multiline: true },
    { key: 'quantity', title: '数量', label: '数量', type: 'number' },
    { key: 'unit', title: '单位', label: '单位', width: 70 },
    { key: 'note', title: '备注', label: '备注', multiline: true, width: '24%' },
  ]
  const rows = todo ? snap.items.filter((row) => !row.arrived) : snap.items
  return <Grid label="物品" rows={rows} columns={columns} empty={todo ? '物品都到齐了' : '还没有物品。在下面输入名称后回车。'} rowClass={(row) => (row.arrived ? 'is-done' : '')}
    onSet={(row, key, value) => ops.set(row, key as keyof Item & string, value)}
    onAdd={(text) => ops.add({ name: text, spec: '', quantity: null, unit: '', note: '', arrived: false })} addPlaceholder="输入物品名称后回车，新增一样"
    onDelete={(row) => void ops.remove(row)} onMove={(row, offset) => void ops.move(snap.items, row, offset)} onReorder={todo ? undefined : (ids) => void ops.reorder(ids)} />
}
