import { useMemo, useState } from 'react'
import { Button, Dropdown, Modal, message } from 'antd'
import { DownOutlined, DownloadOutlined, PlusOutlined, UploadOutlined } from '@ant-design/icons'
import { api, errMsg } from '../../api/client'
import type { Snapshot, Step, Vehicle, VehicleRecord } from '../../api/types'
import Grid, { type Column } from '../../components/Grid'
import ImportModal from '../../components/ImportModal'
import { promptText } from '../../components/prompt'
import { listOps } from '../../sync/rows'
import { download, stamp, today } from '../../utils/format'
import type { TabProps } from './context'

const CATEGORIES = ['故障', '维修', '保养', '检查', '软件', '硬件', '其他']

export default function VehiclesTab({ snap, live, base, me, todo }: TabProps) {
  const [importing, setImporting] = useState<'' | 'vehicles' | 'lifecycle'>('')
  const vehicles = listOps<Snapshot, Vehicle>(live, base, 'vehicles', 'vehicles', { vehicle_no: '车辆编号', fleet_no: '车号', model: '型号', config_no: '配置号', note: '备注' }, {}, me.id)
  const steps = listOps<Snapshot, Step>(live, base, 'steps', 'steps', { name: '环节' }, {}, me.id)
  const records = listOps<Snapshot, VehicleRecord>(live, base, 'vehicle-records', 'vehicle_records',
    { category: '分类', content: '变更内容', recorded_by_name: '记录人', happened_on: '调车时间记录', recorded_on: '记录时间' }, {}, me.id)
  const marks = useMemo(() => new Map(snap.marks.map((mark) => [`${mark.vehicle_id}:${mark.step_id}`, mark])), [snap.marks])
  const byVehicle = useMemo(() => {
    const map = new Map<string, VehicleRecord[]>()
    for (const record of snap.vehicle_records) map.set(record.vehicle_id, [...(map.get(record.vehicle_id) ?? []), record])
    return map
  }, [snap.vehicle_records])
  const categories = useMemo(() => [...new Set([...CATEGORIES, ...snap.vehicle_records.map((record) => record.category).filter(Boolean)])], [snap.vehicle_records])

  const setMark = (vehicleId: string, stepId: string, done: boolean) => {
    live.mutate((data) => ({ ...data, marks: done
      ? [...data.marks.filter((mark) => !(mark.vehicle_id === vehicleId && mark.step_id === stepId)), { vehicle_id: vehicleId, step_id: stepId, done_by: me.id, done_at: new Date().toISOString() }]
      : data.marks.filter((mark) => !(mark.vehicle_id === vehicleId && mark.step_id === stepId)) }))
    void live.track(api.put(`${base}/vehicles/${vehicleId}/steps/${stepId}`, { done })).catch((failure) => message.error(errMsg(failure)))
  }
  const setColumn = (step: Step, done: boolean) => {
    const affected = snap.vehicles.filter((vehicle) => marks.has(`${vehicle.id}:${step.id}`) !== done).length
    if (!affected) { message.info(done ? '这一列已经全部打勾' : '这一列没有勾'); return }
    Modal.confirm({
      title: done ? `把 ${affected} 台车的“${step.name}”都标为完成？` : `取消 ${affected} 台车的“${step.name}”？`,
      okText: '确定', cancelText: '取消',
      onOk: () => live.track(api.put(`${base}/steps/${step.id}/all`, { done })).catch((failure) => message.error(errMsg(failure))),
    })
  }
  const removeStep = (step: Step) => {
    const ticks = snap.marks.filter((mark) => mark.step_id === step.id).length
    Modal.confirm({ title: `删除环节“${step.name}”？`, content: ticks ? `这一列已有 ${ticks} 个勾。删除后 30 天内可以在操作记录里恢复。` : '删除后 30 天内可以在操作记录里恢复。',
      okText: '删除', okButtonProps: { danger: true }, cancelText: '取消', onOk: () => steps.remove(step) })
  }
  const addStep = async () => {
    const name = await promptText('新增环节', '', '例如：到货、调试、交付')
    if (name) await steps.add({ name }).catch(() => undefined)
  }

  const columns: Column<Vehicle>[] = [
    { key: 'vehicle_no', title: '车辆编号', label: '车辆编号', primary: true, required: true, width: 170 },
    { key: 'fleet_no', title: '车号', label: '车号', width: 80 },
    { key: 'model', title: '型号', label: '型号', options: snap.vehicle_types, width: 130 },
    { key: 'config_no', title: '配置号', label: '配置号', width: 110 },
    ...snap.steps.map((step, index): Column<Vehicle> => ({
      key: `step:${step.id}`, label: step.name, type: 'check',
      value: (row) => marks.has(`${row.id}:${step.id}`),
      hint: (row) => { const mark = marks.get(`${row.id}:${step.id}`); return mark ? stamp(snap.people, mark.done_by, mark.done_at) : '' },
      title: <Dropdown trigger={['click']} menu={{ items: [
        { key: 'all', label: '整列打勾', onClick: () => setColumn(step, true) },
        { key: 'none', label: '整列取消', onClick: () => setColumn(step, false) },
        { type: 'divider' },
        { key: 'rename', label: '改名', onClick: () => void promptText('环节名称', step.name).then((name) => { if (name) void steps.set(step, 'name', name) }) },
        { key: 'left', label: '左移', disabled: index === 0, onClick: () => void steps.move(snap.steps, step, -1) },
        { key: 'right', label: '右移', disabled: index === snap.steps.length - 1, onClick: () => void steps.move(snap.steps, step, 1) },
        { key: 'delete', label: '删除环节', danger: true, onClick: () => removeStep(step) },
      ] }}><button type="button" className="step-head" aria-label={`环节 ${step.name}`}>{step.name}<DownOutlined /></button></Dropdown>,
    })),
    { key: 'note', title: '备注', label: '备注', multiline: true },
  ]
  const recordColumns: Column<VehicleRecord>[] = [
    { key: 'happened_on', title: '调车时间记录', label: '调车时间记录', type: 'date', width: 150 },
    { key: 'category', title: '分类', label: '分类', options: categories, width: 110 },
    { key: 'content', title: '变更内容', label: '变更内容', primary: true, required: true, multiline: true },
    { key: 'recorded_by_name', title: '记录人', label: '记录人', width: 110 },
    { key: 'recorded_on', title: '记录时间', label: '记录时间', type: 'date', width: 150 },
  ]
  const shown = todo ? snap.vehicles.filter((vehicle) => snap.steps.some((step) => !marks.has(`${vehicle.id}:${step.id}`))) : snap.vehicles

  return <>
    <div className="tab-tools">
      <Button icon={<PlusOutlined />} onClick={() => void addStep()}>加环节</Button>
      <Dropdown menu={{ items: [
        { key: 'lifecycle', label: '导入生命周期表', onClick: () => setImporting('lifecycle') },
        { key: 'vehicles', label: '导入车辆表', onClick: () => setImporting('vehicles') },
      ] }}><Button icon={<UploadOutlined />}>导入</Button></Dropdown>
      <Button icon={<DownloadOutlined />} onClick={() => download(`${base}/lifecycle.xlsx`)}>导出生命周期表</Button>
    </div>
    <Grid label="车辆" rows={shown} columns={columns} empty={todo ? '所有车辆的环节都做完了' : '还没有车辆。在下面输入车辆编号后回车。'}
      onSet={(row, key, value, seen) => key.startsWith('step:') ? setMark(row.id, key.slice(5), !!value) : vehicles.set(row, key as keyof Vehicle & string, value, seen)}
      onAdd={(text) => vehicles.add({ vehicle_no: text, fleet_no: '', model: '', config_no: '', note: '' })} addPlaceholder="输入车辆编号后回车，新增一台车"
      onDelete={(row) => void vehicles.remove(row)} onMove={(row, offset) => void vehicles.move(snap.vehicles, row, offset)} onReorder={todo ? undefined : (ids) => void vehicles.reorder(ids)}
      expandLabel={(row) => `记录 ${byVehicle.get(row.id)?.length ?? 0}`}
      expand={(row) => <Grid label={`${row.vehicle_no} 的车辆记录`} rows={byVehicle.get(row.id) ?? []} columns={recordColumns} empty="这台车还没有记录"
        onSet={(record, key, value, seen) => records.set(record, key as keyof VehicleRecord & string, value, seen)} onDelete={(record) => void records.remove(record)}
        onAdd={(text) => records.add({ vehicle_id: row.id, content: text, category: '', happened_on: null, recorded_by_name: me.name, recorded_on: today() })}
        addPlaceholder="写下这台车的变更、故障或维修，回车添加" />} />
    <ImportModal open={!!importing} title={importing === 'lifecycle' ? '导入生命周期表' : '导入车辆表'} url={`${base}/import/${importing || 'vehicles'}`}
      hint={importing === 'lifecycle' ? '支持公司的 AGV 生命周期表和本系统导出的生命周期表。按“车辆编号”对应车辆，没有的车会新建。' : '表头需要有“车辆编号”，可以带车号、型号、配置号、备注和各环节。'}
      onClose={() => setImporting('')} onDone={live.refresh} />
  </>
}
