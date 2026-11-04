import VehicleChecksPanel from './VehicleChecksPanel'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Alert, Button, Checkbox, DatePicker, Empty, Input, InputNumber, Modal, Segmented, Select, Space, Table, Tag } from 'antd'
import { CheckOutlined, FileSearchOutlined, SearchOutlined } from '@ant-design/icons'
import { useMediaQuery } from '../hooks/useMediaQuery'
import { IconAction } from './IconAction'
import './VehicleProgressMatrix.css'
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

/** Register details of a vehicle shown on its row (from the vehicle register). */
export type VehicleRowInfo = { id: string; location?: string; current_status?: string; open_issue_count?: number; arrived_at?: string | null; serial_number?: string }
const STATUS: Record<string, { label: string; color: string }> = { attention: { label: '需关注', color: 'warning' }, fault: { label: '故障', color: 'error' }, stopped: { label: '停机', color: 'default' }, retired: { label: '退役', color: 'default' } }
const short = (date: string | null | undefined) => date ? date.slice(5) : ''

/**
 * The project's vehicles in one list: each row is a vehicle with its location, status and every vehicle step.
 * A step is one button — tap to record it done (or to take it back with a reason); its checks open from the dialog.
 */
export default function VehicleProgressMatrix({ projectId, status, onChanged, info = [], renderLocation, onOpenRecord, emptyHint }: {
  projectId: string; status: string; onChanged?: () => void
  info?: VehicleRowInfo[]; renderLocation?: (unitId: string) => ReactNode; onOpenRecord?: (unitId: string) => void; emptyHint?: ReactNode
}) {
  const isMobile = useMediaQuery('(max-width: 767px)')
  const [search, setSearch] = useState('')
  const [attention, setAttention] = useState(false)
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
  const infoOf = (id: string) => info.find(row => row.id === id)
  const needsAttention = (id: string) => { const row = infoOf(id); return !!row && (!!row.open_issue_count || ['fault', 'stopped', 'attention'].includes(row.current_status ?? '')) }
  const term = search.trim().toLowerCase()
  const rows = (data?.units ?? []).filter(u => (!vehicleType || u.vehicle_type === vehicleType) && (!attention || needsAttention(u.id))
    && (!term || [u.asset_code, u.fleet_no, u.model_name, infoOf(u.id)?.location, infoOf(u.id)?.serial_number].some(value => (value ?? '').toLowerCase().includes(term))))
  const stepDone = (key: string) => (data?.units ?? []).filter(u => u.cells[key]?.is_done).length
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
  const stepButton = (u: Unit, s: Matrix['steps'][number]) => {
    const c = u.cells[s.key]; const label = u.fleet_no || u.asset_code
    if (!canRecord) return <button type="button" className={`vstep${c?.is_done ? ' is-done' : ''}`} aria-label={`${u.asset_code} ${s.name} 检查要求`} title={`${label} · ${s.name}：查看检查要求`} onClick={() => setChecking({ unit: u, key: s.key })}>
      {c?.is_done ? <><CheckOutlined aria-hidden />{short(c.done_on) || '已完成'}</> : <span className="vstep-dot" aria-hidden />}{isMobile && <span className="vstep-name">{s.name}</span>}</button>
    return <button type="button" className={`vstep${c?.is_done ? ' is-done' : ''}`} disabled={saving} aria-label={`${u.asset_code} ${s.name} ${c?.is_done ? '取消完成' : '勾选完成'}`} title={`${label} · ${s.name}`}
      onClick={() => open([u], s.key, !c?.is_done)}>
      {c?.is_done ? <><CheckOutlined aria-hidden />{short(c.done_on) || '已完成'}</> : <span className="vstep-dot" aria-hidden />}{isMobile && <span className="vstep-name">{s.name}</span>}</button>
  }
  const vehicleCell = (u: Unit) => { const row = infoOf(u.id); const state = STATUS[row?.current_status ?? '']; return <div className="vrow-name">
    <strong>{u.fleet_no || u.asset_code}</strong>{u.fleet_no && u.fleet_no !== u.asset_code && <small>{u.asset_code}</small>}
    <span className="vrow-sub">{[u.vehicle_type, u.model_name].filter(Boolean).join(' / ')}</span>
    {(state || !!row?.open_issue_count) && <span className="vrow-flags">{state && <Tag color={state.color}>{state.label}</Tag>}{!!row?.open_issue_count && <Tag color="red">{row.open_issue_count} 个问题</Tag>}</span>}
  </div> }
  const recordButton = (u: Unit) => onOpenRecord && <IconAction label={`${u.asset_code} 车辆记录`} icon={<FileSearchOutlined />} onClick={() => onOpenRecord(u.id)} />
  const types = [...new Set((data?.units ?? []).map(u => u.vehicle_type).filter(Boolean))]
  return <section aria-label="车辆清单" className="vboard">
    {error && <Alert type="error" showIcon message="车辆进度操作未完成" description={error} action={<Button onClick={() => void load()}>刷新核对</Button>} />}
    {!data && !loading && !error && <Empty description="车辆进度未知" />}
    {data && <>
      <div className="vboard-toolbar">
        <Input allowClear prefix={<SearchOutlined />} aria-label="搜索现场车辆" placeholder="车号、型号或位置" value={search} onChange={e => setSearch(e.target.value)} className="vboard-search" />
        <Segmented aria-label="车辆查看范围" value={attention ? 'attention' : 'all'} onChange={value => setAttention(value === 'attention')} options={[{ value: 'all', label: '全部' }, { value: 'attention', label: '需关注' }]} />
        {types.length > 1 && <Select aria-label="按车型筛选进度" allowClear placeholder="全部车型" value={vehicleType} onChange={v => { setVehicleType(v); setSelected([]) }} options={types.map(v => ({ label: v, value: v }))} style={{ minWidth: 140 }} />}
        <span className="vboard-summary">已完成 {data.summary.completed} / {data.summary.target} 个环节{data.summary.percent == null ? ' · 进度未知（数量待补）' : ` · ${data.summary.percent}%`}</span>
        <RefreshAction label="刷新车辆" onClick={() => { void load(); onChanged?.() }} loading={loading} />
      </div>
      {data.source_snapshot_available && <Alert type="info" message="便携导入来源仅供核对，不计入本项目完成资格" action={<Button loading={readingSource} onClick={() => void readSource()}>查阅原始来源</Button>} />}
      {(data.migration_warnings ?? []).length > 0 && <Alert type="warning" showIcon message={data.migration_warnings.join('；')} description="未知数量与未知车号分别保留；历史完成凭证计入数量，但不代表已逐台核验。" />}
      {data.legacy.filter(c => c.unassigned_count > 0 || data.steps.find(s => s.key === c.step_key)?.expected_quantity == null).map(c => <details key={c.step_key} style={{ margin: '8px 0' }}><summary><Tag color="orange">已完成（迁移，车号未知）</Tag>{data.steps.find(s => s.key === c.step_key)?.name} · {c.unassigned_count} 台待核对</summary><p>原目标：{String(c.source_metadata.target_quantity ?? '未知')} 台；原累计：{String(c.source_metadata.completed_quantity ?? '未知')} 台。迁移凭证：{c.unassigned_count} 台未核对；实际完成日期未知。</p>{data.can_manage && ['executing', 'acceptance'].includes(status) && <Button onClick={() => { const old = data.steps.find(s => s.key === c.step_key)?.expected_quantity ?? null; setReason(''); setTargetEdit({ key: c.step_key, previous: old, quantity: old }) }}>核对应完成台数</Button>}</details>)}
      {/* Batch tools appear once vehicles are ticked; tapping a step is enough for one-by-one work. */}
      {canRecord && selected.length > 0 && <Space wrap className="vboard-batch"><span>已选 {selected.length} 台</span><Select aria-label="批量车辆环节" placeholder="选择环节" value={step} onChange={setStep} options={data.steps.map(s => ({ value: s.key, label: s.name }))} style={{ minWidth: 170 }} />
        <Button disabled={!selected.length || !step || saving} onClick={() => open(rows.filter(u => selected.includes(u.id)), step!, true)}>批量勾选</Button>
        <Button disabled={!selected.length || !step || saving} onClick={() => open(rows.filter(u => selected.includes(u.id)), step!, false)}>批量取消</Button>
        {data.legacy.some(c => c.unassigned_count > 0) && <Button disabled={!selected.length || !step || saving || !data.legacy.some(c => c.step_key === step && c.unassigned_count > 0)} onClick={() => open(rows.filter(u => selected.includes(u.id)), step!, true, true)}>补录迁移车号</Button>}
        <Button type="link" onClick={() => setSelected([])}>取消选择</Button>
      </Space>}
      {!data.units.length ? <Empty description={emptyHint ?? '尚无真实车辆档案，请先添加车辆并填写实际编号'} />
        : !rows.length ? <Empty description="没有符合条件的车辆" />
        : isMobile ? <ul className="vboard-cards">{rows.map(u => <li key={u.id} className="vboard-card">
          <header>{canRecord && <Checkbox aria-label={`选择${u.asset_code}`} checked={selected.includes(u.id)} onChange={e => setSelected(old => e.target.checked ? [...old, u.id] : old.filter(id => id !== u.id))} />}{vehicleCell(u)}{recordButton(u)}</header>
          {renderLocation && <div className="vboard-card-location">位置 {renderLocation(u.id)}</div>}
          <div className="vboard-card-steps">{data.steps.map(s => <span key={s.key}>{stepButton(u, s)}</span>)}</div>
        </li>)}</ul>
        : <Table<Unit> rowKey="id" className="vboard-table" dataSource={rows} loading={loading} size="small" pagination={rows.length > 50 ? { pageSize: 50, showSizeChanger: true } : false} scroll={{ x: Math.max(720, data.steps.length * 96 + 380) }}
          rowSelection={canRecord ? { selectedRowKeys: selected, onChange: setSelected, columnWidth: 36 } : undefined}
          columns={[
            { title: '车辆', key: 'vehicle', fixed: 'left', width: 170, render: (_, u) => vehicleCell(u) },
            ...(renderLocation ? [{ title: '位置', key: 'location', width: 130, render: (_: unknown, u: Unit) => renderLocation(u.id) }] : []),
            ...data.steps.map(s => ({ title: <span className="vstep-head">{s.name}<small>{stepDone(s.key)}/{data.units.length}</small></span>, key: s.key, width: 96, align: 'center' as const, render: (_: unknown, u: Unit) => stepButton(u, s) })),
            ...(onOpenRecord ? [{ title: '', key: 'record', width: 52, render: (_: unknown, u: Unit) => recordButton(u) }] : []),
          ]} />}
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
    <Modal title={editing?.claim_migrated ? '核对迁移凭证并补录车号' : editing?.is_done ? '登记完成' : '取消完成'} open={!!editing} okText="确认" cancelText="取消" confirmLoading={saving} okButtonProps={{ disabled: !editing?.is_done && !reason.trim() }} cancelButtonProps={{ disabled: saving }} onCancel={() => { if (!lock.current) setEditing(null) }} onOk={() => void save()} destroyOnClose>
      <p>{editing && editing.cells.length > 1 ? `${editing.cells.length} 台车一起登记；全部成功或全部保持原状。` : editing ? `${data?.units.find(u => u.id === editing.cells[0].vehicle_unit_id)?.asset_code ?? ''} · ${data?.steps.find(s => s.key === editing.cells[0].step_key)?.name ?? ''}` : ''}</p>
      {editing?.cells.length === 1 && <Button type="link" size="small" style={{ paddingInline: 0 }} onClick={() => { const cell = editing.cells[0]; const unit = data?.units.find(u => u.id === cell.vehicle_unit_id); if (unit) { setEditing(null); setChecking({ unit, key: cell.step_key }) } }}>查看这一步的检查要求</Button>}
      {editing?.is_done && !editing.claim_migrated && <DatePicker aria-label="实际完成日期" disabledDate={value => value.format('YYYY-MM-DD') > (data?.today ?? dayjs().format('YYYY-MM-DD'))} value={date} allowClear={false} onChange={v => { if (v) setDate(v) }} />}
      {editing?.claim_migrated && <Alert type="info" message="仅转移已有完成凭证，完成总数不增加；历史实际日期未知，保留未知。" />}
      {!editing?.is_done && <Input.TextArea aria-label="取消完成理由" placeholder="取消理由（必填，保留审计）" value={reason} onChange={e => setReason(e.target.value)} maxLength={1000} />}
    </Modal>
  </section>
}
