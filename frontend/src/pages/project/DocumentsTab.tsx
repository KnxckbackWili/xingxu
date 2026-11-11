import { useMemo } from 'react'
import { Tag } from 'antd'
import type { DocumentRow, Snapshot } from '../../api/types'
import Files from '../../components/Files'
import Grid, { type Column } from '../../components/Grid'
import { listOps } from '../../sync/rows'
import type { TabProps } from './context'

export default function DocumentsTab({ snap, live, base, me, todo }: TabProps) {
  const ops = listOps<Snapshot, DocumentRow>(live, base, 'documents', 'documents', { name: '资料名称', note: '备注' }, {}, me.id)
  const filesOf = useMemo(() => {
    const map = new Map<string, Snapshot['files']>()
    for (const file of snap.files) if (file.owner_kind === 'document' && file.owner_id) map.set(file.owner_id, [...(map.get(file.owner_id) ?? []), file])
    return map
  }, [snap.files])
  const columns: Column<DocumentRow>[] = [
    { key: 'name', title: '资料名称', label: '资料名称', primary: true, required: true, width: '28%' },
    { key: 'state', title: '状态', label: '状态', type: 'custom', width: 76, render: (row) => (filesOf.get(row.id)?.length ? <Tag color="green">已交</Tag> : <Tag color="orange">没交</Tag>) },
    { key: 'files', title: '文件', label: '文件', type: 'custom', render: (row) => <Files projectId={snap.project.id} ownerKind="document" ownerId={row.id}
      files={filesOf.get(row.id) ?? []} people={snap.people} track={live.track} /> },
    { key: 'note', title: '备注', label: '备注', multiline: true, width: '22%' },
  ]
  const rows = todo ? snap.documents.filter((row) => !filesOf.get(row.id)?.length) : snap.documents
  return <>
    <Grid label="要交的资料" rows={rows} columns={columns} empty={todo ? '要交的资料都交齐了' : '还没有要交的资料。在下面输入资料名称后回车。'}
      onSet={(row, key, value) => ops.set(row, key as keyof DocumentRow & string, value)}
      onAdd={(text) => ops.add({ name: text, note: '' })} addPlaceholder="输入资料名称后回车，新增一项要交的资料"
      onDelete={(row) => void ops.remove(row)} onMove={(row, offset) => void ops.move(snap.documents, row, offset)} onReorder={todo ? undefined : (ids) => void ops.reorder(ids)} />
    {!todo && <section className="other-files" aria-label="其他文件">
      <h3>其他文件</h3>
      <p>清单以外的文件放在这里，比如质量问题反馈单、现场照片。</p>
      <Files projectId={snap.project.id} ownerKind="other" ownerId={null} files={snap.files.filter((file) => file.owner_kind === 'other')} people={snap.people} track={live.track} label="上传文件" />
    </section>}
  </>
}
