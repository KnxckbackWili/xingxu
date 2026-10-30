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
  // Same rule as the server: safety checks must pass, other required checks must be done (or failed with an override).
  const blockers = (captured.current.check_items ?? []).filter(c => c.is_safety_critical ? (!c.is_done || c.failed || !c.is_applicable) : c.is_required && c.is_applicable && !c.is_done && !c.failed)
  const pendingChecks = (captured.current.check_items ?? []).filter(c => c.is_applicable && !c.is_done && !c.failed).length - blockers.filter(c => c.is_applicable && !c.is_done && !c.failed).length
  const [passing, setPassing] = useState('')
  const [, refresh] = useState(0)
  // A check passed from this dialog reloads the work item; keep the dialog on the fresh copy.
  useEffect(() => { if (open && item.id === captured.current.id) { captured.current = item; refresh(n => n + 1) } }, [item, open])
  const pass = async (check: WorkItem['check_items'][number]) => {
    if (passing) return
    setPassing(check.id); setError('')
    try {
      ensureVerifiedAccount(user?.id)
      await api.put(`/projects/${projectId}/check-items/${check.id}`, { version: check.version, is_done: true, failed: false, is_applicable: true })
      await onSaved()
    } catch (e) { setError(errMsg(e)) }
    finally { setPassing('') }
  }
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
    <Modal title={`${captured.current.is_completed ? '重新打开' : '完成'}工作：${captured.current.name}`} open={open} okText="保存工作状态" cancelText="取消" confirmLoading={busy} okButtonProps={{ disabled: !allowed || !reason.trim() || (!captured.current.is_completed && (blockers.length > 0 || (!!failed.length && (!canOverride || !confirmed)))) }} onOk={() => void save()} onCancel={() => { if (!lock.current) setOpen(false) }} destroyOnClose>
      {error && <Alert type="error" showIcon message="工作状态未确认" description={error} />}
      <Typography.Paragraph>{captured.current.is_completed ? '写明重新打开的原因，原完成记录会保留。' : `写明完成依据，如确认人或照片位置，便于以后核对。${pendingChecks ? `还有 ${pendingChecks} 项检查未确认，标记完成不会替它们打勾。` : ''}`}</Typography.Paragraph>
      {!captured.current.is_completed && blockers.length > 0 && <div className="work-completion-blockers" role="group" aria-label="完成前必须通过的检查">
        <Typography.Text strong>先确认这些检查</Typography.Text>
        {blockers.map(check => <div key={check.id} className="work-completion-blocker"><span>{check.vehicle_label ? `${check.vehicle_label} · ` : ''}{check.name}{check.is_safety_critical && <Typography.Text type="danger"> · 安全</Typography.Text>}{check.failed && <Typography.Text type="danger"> · 不通过</Typography.Text>}</span>
          <Button size="small" loading={passing === check.id} disabled={!!passing || busy} onClick={() => void pass(check)}>确认通过</Button></div>)}
      </div>}
      {!!failed.length && !captured.current.is_completed && <Alert type="warning" message="存在普通失败检查" description={<>{failed.map(c => <p key={c.id}>{c.vehicle_label ? `${c.vehicle_label} · ` : ''}{c.name}：{c.failed_reason}</p>)}{canOverride && <Checkbox checked={confirmed} disabled={busy} onChange={e => setConfirmed(e.target.checked)}>确认对以上当前失败版本说明覆盖理由</Checkbox>}</>} />}
      <Input.TextArea aria-label="工作状态理由" value={reason} disabled={busy} onChange={e => setReason(e.target.value)} maxLength={4000} placeholder={captured.current.is_completed ? '重新打开原因（必填）' : '完成依据（必填）'} rows={4} />
    </Modal>
  </>
}
