import { useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Checkbox, Input, Modal, Typography } from 'antd'
import { Link } from 'react-router-dom'
import { api, errMsg } from '../api/client'
import type { WorkItem } from '../api/workItems'
import { ensureVerifiedAccount } from '../utils/verifiedAccount'
import { useAuth } from '../stores/auth'
import { hasSystemPermission } from '../constants/systemPermissions'

/** `blockedHint` replaces a disabled button with the reason when recording is not possible yet. */
export default function WorkCompletionAction({ projectId, item, canRecord, canOverride = false, blockedHint, onSaved }: { projectId: string; item: WorkItem; canRecord: boolean; canOverride?: boolean; blockedHint?: string; onSaved: () => void | Promise<void> }) {
  const { user } = useAuth()
  const allowed = canRecord && hasSystemPermission(user, 'worker.report')
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [error, setError] = useState('')
  const [receipt, setReceipt] = useState('')
  const [busy, setBusy] = useState(false)
  const identityKey = `${user?.id}:${projectId}:${item.id}`
  const identity = useMemo(() => Symbol(identityKey), [identityKey])
  const owner = useRef(identity); owner.current = identity
  const lock = useRef(false)
  useEffect(() => { owner.current = identity; setOpen(false); setReason(''); setError(''); setBusy(false); lock.current = false; return () => { owner.current = Symbol('closed') } }, [identity])
  const captured = useRef(item)
  const failed = (captured.current.check_items ?? []).filter(c => c.failed && c.is_applicable && !c.is_safety_critical)
  const save = async () => {
    if (lock.current || !allowed || !reason.trim()) return
    const identityAtStart = owner.current
    lock.current = true; setBusy(true); setError('')
    const work = captured.current
    try {
      ensureVerifiedAccount(user?.id)
      await api.put(`/projects/${projectId}/work-items/${work.id}/completion`, { version: work.version, is_completed: !work.is_completed, reason,
        override_failed: !work.is_completed && !!failed.length && canOverride && confirmed,
        failed_checks: !work.is_completed && confirmed ? failed.map(c => ({ id: c.id, version: c.version })) : [] })
      if (owner.current !== identityAtStart) return
      setOpen(false)
      try { await onSaved() } catch { if (owner.current === identityAtStart) setReceipt('工作状态已保存，但最新记录读取失败；请刷新核对，勿重复提交。') }
    } catch (e) { if (owner.current === identityAtStart) setError(errMsg(e)) }
    finally { if (owner.current === identityAtStart) { lock.current = false; setBusy(false) } }
  }
  if (item.kind === 'vehicle') return <Link to={`/pm/projects/${projectId}/vehicles`}>到车辆进度表登记</Link>
  if (!allowed && blockedHint) return <Typography.Text type="secondary" className="work-completion-hint">{blockedHint}</Typography.Text>
  return <>
    {receipt && <Alert type="warning" message={receipt} />}
    <Button disabled={!allowed} onClick={() => { captured.current = item; setReason(''); setConfirmed(false); setError(''); setOpen(true) }}>{item.is_completed ? '重新打开' : '标记完成'}</Button>
    <Modal title={`${captured.current.is_completed ? '重新打开' : '完成'}工作：${captured.current.name}`} open={open} okText="保存工作状态" cancelText="取消" confirmLoading={busy} okButtonProps={{ disabled: !allowed || !reason.trim() || (!captured.current.is_completed && !!failed.length && (!canOverride || !confirmed)) }} onOk={() => void save()} onCancel={() => { if (!lock.current) setOpen(false) }} destroyOnClose>
      {error && <Alert type="error" showIcon message="工作状态未确认" description={error} />}
      <Typography.Paragraph>保留原工作、检查与历史数量，记录本次状态和理由；车辆环节始终按真实车号登记。</Typography.Paragraph>
      {!!failed.length && !captured.current.is_completed && <Alert type="warning" message="存在普通失败检查" description={<>{failed.map(c => <p key={c.id}>{c.vehicle_label ? `${c.vehicle_label} · ` : ''}{c.name}：{c.failed_reason}</p>)}{canOverride && <Checkbox checked={confirmed} disabled={busy} onChange={e => setConfirmed(e.target.checked)}>确认对以上当前失败版本说明覆盖理由</Checkbox>}</>} />}
      <Input.TextArea aria-label="工作状态理由" value={reason} disabled={busy} onChange={e => setReason(e.target.value)} maxLength={4000} placeholder="完成依据或重新打开的原因（必填）" rows={4} />
    </Modal>
  </>
}
