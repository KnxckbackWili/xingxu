import VehicleChecksPanel from './VehicleChecksPanel'
import { useEffect, useRef, useState } from 'react'
import { Alert, Button, DatePicker, Empty, Input, InputNumber, Modal, Select, Space, Table, Tag, Typography } from 'antd'
import dayjs from 'dayjs'
import { api, errMsg } from '../api/client'
import { RefreshAction } from './IconAction'

type Cell = { version: number; is_done: boolean; done_on: string | null; migrated: boolean; recorded_at: string; done_by: string; note: string }
type Unit = { id: string; asset_code: string; fleet_no: string; vehicle_type: string; model_name: string; cells: Record<string, Cell> }
type Matrix = { source_snapshot_available?: boolean; today?: string; steps: { key: string; name: string; source_task_id: string | null; expected_quantity: number | null }[]; units: Unit[]; can_record?: boolean; can_manage?: boolean; legacy: { step_key: string; unassigned_count: number; source_metadata: Record<string, unknown> }[]; summary: { completed: number; target: number; percent: number | null; quantity_unknown: boolean; unregistered_quantity: number }; migration_warnings: string[] }

function matrixError(error: unknown) {
  const detail = (error as { response?: { data?: { detail?: { message?: string; blockers?: { name: string; reason: string; vehicle_unit_id: string; vehicle_label?: string }[] } } } }).response?.data?.detail
  return detail && Array.isArray(detail.blockers) ? `${detail.message}；${detail.blockers.map(b => `${b.vehicle_label || b.vehicle_unit_id} · ${b.name}：${b.reason}`).join('；')}` : errMsg(error)
}

export default function VehicleProgressMatrix({ projectId, status, onChanged }: { projectId: string; status: string; onChanged?: () => void }) {
  const [checking, setChecking] = useState<{ unit: Unit; key: string } | null>(null)
  const [data, setData] = useState<Matrix | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [source, setSource] = useState<unknown>(undefined)
  const [readingSource, setReadingSource] = useState(false)
  const [vehicleType, setVehicleType] = useState<string>()
  const [selected, setSelected] = useState<React.Key[]>([])
  const [step, setStep] = useState<string>()
  const [editing, setEditing] = useState<{ cells: { vehicle_unit_id: string; step_key: string; version: number }[]; is_done: boolean; claim_migrated: boolean } | null>(null)
  const [targetEdit, setTargetEdit] = useState<{ key: string; previous: number | null; quantity: number | null } | null>(null)
  const [date, setDate] = useState(dayjs())
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState(false)
  const lock = useRef(false)
  const generation = useRef(0)
  const active = useRef(projectId)
  if (active.current !== projectId) { active.current = projectId; generation.current++ }
  const load = async () => {
    const id = ++generation.current
    setLoading(true); setError('')
    try {
      const response = await api.get(`/projects/${projectId}/vehicle-progress`)
      if (!Array.isArray(response.data?.steps) || !Array.isArray(response.data?.units) || !response.data?.summary || typeof response.data.summary.completed !== 'number') throw new Error('车辆进度响应不完整，请重试读取')
      if (generation.current === id) setData(response.data)
    } catch (e) { if (generation.current === id) { setError(matrixError(e)); setData(null) } }
    finally { if (generation.current === id) setLoading(false) }
  }
  useEffect(() => { setData(null); setChecking(null); setSelected([]); setVehicleType(undefined); setEditing(null); setTargetEdit(null); setSource(undefined); setReadingSource(false); void load(); return () => { generation.current++ } }, [projectId])
  const readSource = async () => {
    const id = projectId; const gen = generation.current
    setReadingSource(true)
    try { const response = await api.get(`/projects/${id}/vehicle-progress/source`); if (active.current === id && generation.current === gen) setSource(response.data.source) }
    catch (e) { if (active.current === id && generation.current === gen) setError(matrixError(e)) }
    finally { if (active.current === id && generation.current === gen) setReadingSource(false) }
  }
  const canRecord = !!data?.can_record && ['executing', 'acceptance'].includes(status)
  const rows = (data?.units ?? []).filter(u => !vehicleType || u.vehicle_type === vehicleType)
  const open = (units: Unit[], key: string, isDone: boolean, claim = false) => {
    if (!canRecord || lock.current) return
    setReason(''); setDate(dayjs(data?.today)); setError('')
    setEditing({ cells: units.map(u => ({ vehicle_unit_id: u.id, step_key: key, version: u.cells[key]?.version ?? 0 })), is_done: isDone, claim_migrated: claim })
  }
  const saveTarget = async () => {
    if (!targetEdit || targetEdit.quantity == null || !reason.trim() || lock.current) return
    const id = projectId; const gen = generation.current
    lock.current = true; setSaving(true)
    try {
      await api.put(`/projects/${id}/vehicle-progress/steps/${encodeURIComponent(targetEdit.key)}`, { expected_quantity: targetEdit.quantity, previous_quantity: targetEdit.previous, reason })
      if (active.current !== id || generation.current !== gen) return
      setTargetEdit(null); await load(); onChanged?.()
    } catch (e) { if (active.current === id && generation.current === gen) setError(matrixError(e)) }
    finally { lock.current = false; setSaving(false) }
  }
  const save = async () => {
    if (!editing || lock.current || (!editing.is_done && !reason.trim())) return
    const id = projectId; const gen = generation.current
    lock.current = true; setSaving(true)
    try {
      await api.put(`/projects/${id}/vehicle-progress`, { ...editing, done_on: editing.claim_migrated || !editing.is_done ? null : date.format('YYYY-MM-DD'), reason })
      if (active.current !== id || generation.current !== gen) return
      setEditing(null); setSelected([]); await load(); onChanged?.()
    } catch (e) { if (active.current === id && generation.current === gen) setError(matrixError(e)) }
    finally { lock.current = false; setSaving(false) }
  }
  return <section aria-label="车辆进度表">
    <Typography.Title level={4}>车辆进度表</Typography.Title>
    <Typography.Paragraph type="secondary">每个环节记录实际完成日期；生命周期问题履历保留在下方车辆记录中。</Typography.Paragraph>
    {error && <Alert type="error" showIcon message="车辆进度操作未完成" description={error} action={<Button onClick={() => void load()}>刷新核对</Button>} />}
    {!data && !loading && !error && <Empty description="车辆进度未知" />}
    {data && <>
      <Space wrap style={{ marginBottom: 12 }}><span>已完成 {data.summary.completed} / {data.summary.target} 个环节 · {data.summary.percent == null ? '进度未知（数量待补）' : `${data.summary.percent}%`}</span><RefreshAction label="刷新进度表" onClick={load} loading={loading} />
        <Select aria-label="按车型筛选进度" allowClear placeholder="全部车型" value={vehicleType} onChange={v => { setVehicleType(v); setSelected([]) }} options={[...new Set(data.units.map(u => u.vehicle_type).filter(Boolean))].map(v => ({ label: v, value: v }))} style={{ minWidth: 160 }} />
      </Space>
      {data.source_snapshot_available && <Alert type="info" message="便携导入来源仅供核对，不计入本项目完成资格" action={<Button loading={readingSource} onClick={() => void readSource()}>查阅原始来源</Button>} />}
      {(data.migration_warnings ?? []).length > 0 && <Alert type="warning" showIcon message={data.migration_warnings.join('；')} description="未知数量与未知车号分别保留；历史完成凭证计入数量，但不代表已逐台核验。" />}
      {data.legacy.filter(c => c.unassigned_count > 0 || data.steps.find(s => s.key === c.step_key)?.expected_quantity == null).map(c => <details key={c.step_key} style={{ margin: '8px 0' }}><summary><Tag color="orange">已完成（迁移，车号未知）</Tag>{data.steps.find(s => s.key === c.step_key)?.name} · {c.unassigned_count} 台待核对</summary><p>原目标：{String(c.source_metadata.target_quantity ?? '未知')} 台；原累计：{String(c.source_metadata.completed_quantity ?? '未知')} 台。迁移凭证：{c.unassigned_count} 台未核对；实际完成日期未知。</p>{data.can_manage && ['executing', 'acceptance'].includes(status) && <Button onClick={() => { const old = data.steps.find(s => s.key === c.step_key)?.expected_quantity ?? null; setReason(''); setTargetEdit({ key: c.step_key, previous: old, quantity: old }) }}>核对应完成台数</Button>}</details>)}
      {canRecord && <Space wrap style={{ margin: '12px 0' }}><span>已选 {selected.length} 台</span><Select aria-label="批量车辆环节" placeholder="选择环节" value={step} onChange={setStep} options={data.steps.map(s => ({ value: s.key, label: s.name }))} style={{ minWidth: 170 }} />
        <Button disabled={!selected.length || !step || saving} onClick={() => open(rows.filter(u => selected.includes(u.id)), step!, true)}>批量勾选</Button>
        <Button disabled={!selected.length || !step || saving} onClick={() => open(rows.filter(u => selected.includes(u.id)), step!, false)}>批量取消</Button>
        <Button disabled={!selected.length || !step || saving || !data.legacy.some(c => c.step_key === step && c.unassigned_count > 0)} onClick={() => open(rows.filter(u => selected.includes(u.id)), step!, true, true)}>补录迁移车号</Button>
      </Space>}
      <Table<Unit> rowKey="id" dataSource={rows} loading={loading} pagination={{ pageSize: 25, showSizeChanger: true }} scroll={{ x: Math.max(750, data.steps.length * 155 + 180) }} rowSelection={canRecord ? { selectedRowKeys: selected, onChange: setSelected } : undefined}
        columns={[{ title: '车号 / 车辆编号', key: 'vehicle', fixed: 'left', width: 180, render: (_, u) => <><strong>{u.fleet_no || u.asset_code}</strong><div>{u.model_name}</div></> }, ...data.steps.map(s => ({ title: s.name, key: s.key, width: 155, render: (_: unknown, u: Unit) => { const c = u.cells[s.key]; return <Space direction="vertical"><Button style={{ minHeight: 44 }} disabled={!canRecord || saving} type={c?.is_done ? 'primary' : 'default'} aria-label={`${u.asset_code} ${s.name} ${c?.is_done ? '取消完成' : '勾选完成'}`} onClick={() => open([u], s.key, !c?.is_done)}>{c?.is_done ? c.done_on || '已完成（迁移）' : '未完成'}</Button><Button size="small" aria-label={`${u.asset_code} ${s.name} 检查要求`} onClick={() => setChecking({ unit: u, key: s.key })}>检查要求</Button></Space> } }))]} locale={{ emptyText: '尚无真实车辆档案，请先在下方添加车辆并填写实际编号' }} />
    </>}
    <Modal open={!!checking} title="车辆环节检查" footer={null} width={760} onCancel={() => setChecking(null)} destroyOnClose>
      {checking && data && <VehicleChecksPanel key={`${projectId}:${checking.unit.id}:${checking.key}`} projectId={projectId} unitId={checking.unit.id} unitLabel={checking.unit.fleet_no || checking.unit.asset_code} stepKey={checking.key} steps={data.steps} canManage={!!data.can_manage} onChanged={() => { void load(); onChanged?.() }} />}
    </Modal>
    <Modal title="原始来源记录（只读，未核验）" open={source !== undefined} onCancel={() => setSource(undefined)} footer={<Button onClick={() => setSource(undefined)}>关闭</Button>} width={800}>
      <p>原字段、日期、车号和操作者保留用于核对；本项目完成、检查和验收须重新登记。</p><pre style={{ whiteSpace: 'pre-wrap', maxHeight: '60vh', overflow: 'auto' }}>{JSON.stringify(source, null, 2)}</pre>
    </Modal>
    <Modal title="核对历史环节应完成台数" open={!!targetEdit} okText="确认" cancelText="取消" confirmLoading={saving} okButtonProps={{ disabled: targetEdit?.quantity == null || !reason.trim() }} onCancel={() => { if (!lock.current) setTargetEdit(null) }} onOk={() => void saveTarget()}>
      <p>保留原始目标和完成数量，仅补充本项目矩阵的应完成台数。不能少于已有完成凭证。</p>
      <InputNumber aria-label="历史环节应完成台数" min={0} max={100000} precision={0} value={targetEdit?.quantity} disabled={saving} onChange={v => setTargetEdit(old => old ? { ...old, quantity: v } : old)} />
      <Input.TextArea aria-label="核对台数理由" value={reason} disabled={saving} onChange={e => setReason(e.target.value)} placeholder="核对依据与理由（必填）" maxLength={1000} />
    </Modal>
    <Modal title={editing?.claim_migrated ? '核对迁移凭证并补录车号' : editing?.is_done ? '登记车辆环节完成' : '取消车辆环节完成'} open={!!editing} okText="确认" cancelText="取消" confirmLoading={saving} okButtonProps={{ disabled: !editing?.is_done && !reason.trim() }} cancelButtonProps={{ disabled: saving }} onCancel={() => { if (!lock.current) setEditing(null) }} onOk={() => void save()} destroyOnClose>
      <p>{editing?.cells.length} 个单元格；所有改动同时成功或同时保留原状。</p>
      {editing?.is_done && !editing.claim_migrated && <DatePicker aria-label="实际完成日期" disabledDate={value => value.format('YYYY-MM-DD') > (data?.today ?? dayjs().format('YYYY-MM-DD'))} value={date} allowClear={false} onChange={v => { if (v) setDate(v) }} />}
      {editing?.claim_migrated && <Alert type="info" message="仅转移已有完成凭证，完成总数不增加；历史实际日期未知，保留未知。" />}
      {!editing?.is_done && <Input.TextArea aria-label="取消完成理由" placeholder="取消理由（必填，保留审计）" value={reason} onChange={e => setReason(e.target.value)} maxLength={1000} />}
    </Modal>
  </section>
}
