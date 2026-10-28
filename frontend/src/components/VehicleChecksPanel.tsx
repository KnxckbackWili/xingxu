import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Empty, Input, Modal, Select, Space, Tag, Typography } from 'antd'
import { api, errMsg } from '../api/client'
import { formatDateTime } from '../utils/date'
import { useAuth } from '../stores/auth'
import { hasSystemPermission } from '../constants/systemPermissions'
import { RefreshAction } from './IconAction'

export type VehicleCheck = { id: string; task_id: string; task_name: string; task_version: number; vehicle_unit_id: string | null; vehicle_step_key: string | null; scope: 'vehicle' | 'legacy_task'; name: string; is_required: boolean; is_safety_critical: boolean; is_applicable: boolean; is_done: boolean; failed: boolean; failed_reason: string; not_applicable_reason: string; done_by?: string; done_by_name?: string; done_at?: string; version: number; definition_version?: number; blocker?: string }
type Props = { projectId: string; unitId: string; unitLabel: string; stepKey: string; steps: { key: string; name: string }[]; canManage: boolean; onChanged: () => void }

export default function VehicleChecksPanel({ projectId, unitId, unitLabel, stepKey, steps, canManage, onChanged }: Props) {
  const { user } = useAuth()
  const canPlan = canManage && hasSystemPermission(user, 'project.manage_plan')
  const [data, setData] = useState<{ items: VehicleCheck[]; can_record: boolean }>()
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [action, setAction] = useState<{ item: VehicleCheck; kind: 'pass' | 'pending' | 'fail' | 'na' | 'review' }>()
  const [reason, setReason] = useState('')
  const [binding, setBinding] = useState<Record<string, string>>({})
  const lock = useRef(false)
  const generation = useRef(0)
  const current = useRef(`${projectId}:${unitId}:${stepKey}`)
  const identity = `${projectId}:${unitId}:${stepKey}`
  if (current.current !== identity) { current.current = identity; generation.current++ }
  const load = async () => {
    const seq = ++generation.current; setLoading(true)
    try { const r = await api.get(`/projects/${projectId}/vehicle-units/${unitId}/checks`, { params: { step_key: stepKey } }); if (seq === generation.current) { setData(r.data); setError('') } }
    catch (e) { if (seq === generation.current) { setData(undefined); setError(errMsg(e)) } }
    finally { if (seq === generation.current) setLoading(false) }
  }
  useEffect(() => { setData(undefined); setAction(undefined); setBinding({}); setError(''); void load(); return () => { generation.current++ } }, [identity])
  const canRecord = !!data?.can_record && hasSystemPermission(user, 'worker.report')
  const save = async () => {
    if (!action || lock.current || (!canPlan && action.kind === 'review') || (action.kind !== 'review' && !canRecord)) return
    const captured = identity; const seq = generation.current
    lock.current = true; setBusy(true); setError('')
    try {
      const item = action.item
      if (action.kind === 'review') await api.post(`/projects/${projectId}/tasks/${item.task_id}/vehicle-checks/generate`, { vehicle_unit_ids: [unitId], reason })
      else await api.put(`/projects/${projectId}/check-items/${item.id}`, { version: item.version,
        ...(action.kind === 'na' ? { is_applicable: false, not_applicable_reason: reason } : action.kind === 'fail' ? { failed: true, failed_reason: reason } : { is_done: action.kind === 'pass', failed: false, is_applicable: true }) })
      if (captured !== current.current || seq !== generation.current) return
      setAction(undefined); await load(); onChanged()
    } catch (e) { if (captured === current.current && seq === generation.current) setError(errMsg(e)) }
    finally { lock.current = false; setBusy(false) }
  }
  const bind = async (item: VehicleCheck) => {
    if (!canPlan || !binding[item.task_id] || lock.current) return
    const captured = identity; const seq = generation.current
    lock.current = true; setBusy(true); setError('')
    try {
      await api.put(`/projects/${projectId}/tasks/${item.task_id}`, { vehicle_step_key: binding[item.task_id], version: item.task_version })
      if (captured !== current.current || seq !== generation.current) return
      await load(); onChanged()
    } catch (e) { if (captured === current.current && seq === generation.current) setError(errMsg(e)) }
    finally { lock.current = false; setBusy(false) }
  }
  const choose = (item: VehicleCheck, kind: NonNullable<typeof action>['kind']) => { setReason(''); setAction({ item, kind }) }
  const unresolved = [...new Map((data?.items ?? []).filter(r => !r.vehicle_step_key).map(r => [r.task_id, r])).values()]
  const legacy = [...new Map((data?.items ?? []).filter(r => r.scope === 'legacy_task' && r.vehicle_step_key).map(r => [r.task_id, r])).values()]
  return <section aria-label={`${unitLabel} 环节检查`}>
    <Typography.Paragraph>{unitLabel} · {steps.find(s => s.key === stepKey)?.name}。必需项先完成，安全关键项必须真实通过。</Typography.Paragraph>
    <RefreshAction label="刷新检查" onClick={load} loading={loading} disabled={busy} />
    {error && <Alert showIcon type="error" message="检查操作未完成" description={error} />}
    {canPlan && unresolved.map(item => <div key={item.task_id}><Alert type="warning" message={`${item.task_name} 尚未明确关联环节`} /><Space wrap><Select aria-label={`${item.task_name} 关联车辆环节`} placeholder="负责人选择实际环节" value={binding[item.task_id]} disabled={busy} onChange={value => setBinding(old => ({ ...old, [item.task_id]: value }))} options={steps.map(s => ({ value: s.key, label: s.name }))} style={{ minWidth: 190 }} /><Button disabled={!binding[item.task_id] || busy} onClick={() => void bind(item)}>确认关联</Button></Space></div>)}
    {canPlan && legacy.map(item => <p key={item.task_id}><Button disabled={busy} onClick={() => choose(item, 'review')}>为本车生成复核：{item.task_name}</Button></p>)}
    {data?.items.length === 0 && <Empty description="此车本环节没有检查要求" />}
    {data?.items.map(item => <article key={item.id} style={{ padding: '12px 0', borderBottom: '1px solid var(--ant-color-border-secondary)' }}>
      <strong>{item.name}</strong> <Tag>{item.scope === 'vehicle' ? '本车检查' : '历史任务级（未逐车核验）'}</Tag>{item.is_safety_critical && <Tag color="red">安全关键</Tag>}{item.is_required && <Tag>必需</Tag>}
      <div>{item.task_name} · {!item.is_applicable ? `不适用：${item.not_applicable_reason}` : item.failed ? `不通过：${item.failed_reason}` : item.is_done ? '已通过' : '待检查'}</div>
      {item.done_at && <div>原检查时间：{formatDateTime(item.done_at)} · 操作人：{item.done_by_name || item.done_by || '未记录'}</div>}
      {item.blocker && <Typography.Paragraph type="warning">{item.blocker}</Typography.Paragraph>}
      {canRecord && <Space wrap><Button disabled={busy || !item.vehicle_step_key} onClick={() => choose(item, item.is_done ? 'pending' : 'pass')}>{item.is_done ? '撤销通过' : '确认通过'}</Button><Button disabled={busy || !item.vehicle_step_key} danger onClick={() => choose(item, 'fail')}>不通过</Button>{!item.is_safety_critical && <Button disabled={busy || !item.vehicle_step_key} onClick={() => choose(item, 'na')}>不适用</Button>}</Space>}
    </article>)}
    <Modal open={!!action} title={action?.kind === 'review' ? '为既有实车生成待复核项' : `登记检查：${action?.item.name ?? ''}`} okText="保存检查" cancelText="取消" confirmLoading={busy} okButtonProps={{ disabled: !!action && ['fail', 'na', 'review'].includes(action.kind) && !reason.trim() }} onCancel={() => { if (!lock.current) setAction(undefined) }} onOk={() => void save()}>
      {action?.kind === 'review' ? <p>原任务级结果完整保留；只为当前真实车辆添加尚未生成的待检项，不继承通过资格。</p> : <p>仅更新此条检查的当前版本。安全项不允许不适用；待检必需项不能被直接完成覆盖。</p>}
      {action && ['fail', 'na', 'review'].includes(action.kind) && <Input.TextArea aria-label="车辆检查原因" value={reason} disabled={busy} onChange={e => setReason(e.target.value)} maxLength={1000} placeholder="填写具体原因（必填）" />}
    </Modal>
  </section>
}
