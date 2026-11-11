import { useMemo } from 'react'
import type { Issue, Snapshot } from '../../api/types'
import Files from '../../components/Files'
import Grid, { AddLine, type Column } from '../../components/Grid'
import Person from '../../components/Person'
import { listOps } from '../../sync/rows'
import { day, stamp } from '../../utils/format'
import type { TabProps } from './context'

export default function IssuesTab({ snap, live, base, me, todo }: TabProps) {
  const ops = listOps<Snapshot, Issue>(live, base, 'issues', 'issues', { description: '问题描述', vehicle_id: '关联车辆', resolution: '处理结果', is_closed: '状态' }, { is_closed: 'closed' }, me.id)
  const rows = useMemo(() => [...snap.issues].filter((row) => !todo || !row.is_closed)
    .sort((a, b) => Number(a.is_closed) - Number(b.is_closed) || b.created_at.localeCompare(a.created_at)), [snap.issues, todo])
  const columns: Column<Issue>[] = [
    { key: 'is_closed', title: '状态', label: '状态', type: 'custom', width: 84, render: (row) => <button type="button" className={`issue-state${row.is_closed ? ' is-closed' : ''}`}
      aria-pressed={row.is_closed} aria-label={row.is_closed ? '已关，点一下重新打开' : '没关，点一下关闭'} title={row.is_closed ? stamp(snap.people, row.closed_by, row.closed_at) : '点一下关闭'}
      onClick={() => void ops.set(row, 'is_closed', !row.is_closed)}>{row.is_closed ? '已关' : '没关'}</button> },
    { key: 'description', title: '问题描述', label: '问题描述', primary: true, required: true, multiline: true },
    { key: 'vehicle_id', title: '关联车辆', label: '关联车辆', type: 'select', width: 180, choices: snap.vehicles.map((vehicle) => ({ value: vehicle.id, label: vehicle.vehicle_no })) },
    { key: 'resolution', title: '处理结果', label: '处理结果', multiline: true, placeholder: '怎么处理的', width: '24%' },
    { key: 'files', title: '照片和文件', label: '照片和文件', type: 'custom', render: (row) => <Files projectId={snap.project.id} ownerKind="issue" ownerId={row.id}
      files={snap.files.filter((file) => file.owner_kind === 'issue' && file.owner_id === row.id)} people={snap.people} track={live.track} label="拍照 / 上传" /> },
    { key: 'meta', title: '上报', label: '上报', type: 'custom', width: 130, render: (row) => <span className="issue-meta"><Person name={row.created_by ? snap.people[row.created_by] : ''} /><small>{day(row.created_at)}</small></span> },
  ]
  return <>
    <div className="grid-wrap issue-new"><AddLine placeholder="写一句话说明问题，回车上报" onAdd={(text) => ops.add({ description: text, vehicle_id: null, resolution: '', is_closed: false })} /></div>
    <Grid label="问题" rows={rows} columns={columns} empty={todo ? '没有未关闭的问题' : '还没有问题'} rowClass={(row) => (row.is_closed ? 'is-done' : '')}
      onSet={(row, key, value) => ops.set(row, key as keyof Issue & string, value)} onDelete={(row) => void ops.remove(row)} />
  </>
}
