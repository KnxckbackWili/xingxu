import { useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Form, Input, Modal, Select, Space, Tag, Typography, message } from 'antd'
import { Link } from 'react-router-dom'
import { api, errMsg } from '../api/client'
import { ensureVerifiedAccount } from '../utils/verifiedAccount'
import { useAuth } from '../stores/auth'
import { hasSystemPermission } from '../constants/systemPermissions'
import WorkCompletionAction from './WorkCompletionAction'
import type { WorkItem } from '../api/workItems'

function readDraft(key: string) { try { return JSON.parse(sessionStorage.getItem(key) || '{}') } catch { return {} } }
export default function WorkContextPanel({ data, onRefresh }: { data: any; entryId?: string; onRefresh: () => Promise<void> }) {
  const { user } = useAuth()
  const key = `agv:work-draft:${user?.id}:${data.project.id}:${data.task.id}`
  const [owner, setOwner] = useState(key)
  const [draft, setDraft] = useState<any>(() => readDraft(key))
  const [repairing, setRepairing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [receipt, setReceipt] = useState('')
  const [form] = Form.useForm()
  const lock = useRef(false)
  const token = useMemo(() => Symbol(key), [key])
  const current = useRef(token)
  current.current = token
  const canRepair = !!data.can_update_repair && hasSystemPermission(user, 'worker.issues')
  const canRecord = !!data.can_complete && hasSystemPermission(user, 'worker.report')
  useEffect(() => { current.current = token; return () => { current.current = Symbol('closed') } }, [key])
  useEffect(() => { setOwner(key); setDraft(readDraft(key)); setRepairing(false); setError(''); setReceipt('') }, [key])
  useEffect(() => { if (owner !== key) return; try { sessionStorage.setItem(key, JSON.stringify(draft)) } catch { /* Keep current form even when storage is unavailable. */ } }, [owner, key, draft])
  const saveRepair = async (values: any) => {
    if (!canRepair || lock.current) return
    const identity = current.current; lock.current = true; setBusy(true); setError('')
    try {
      ensureVerifiedAccount(user?.id)
      await api.put(`/projects/${data.project.id}/vehicle-units/${data.repair.unit_id}/events/${data.repair.id}`, { action_taken: values.action_taken, verification: values.verification, is_closed: values.is_closed, ...(values.status_after ? { status_after: values.status_after } : {}) })
      if (current.current !== identity) return
      setDraft((d: any) => ({ ...d, repair: undefined })); setRepairing(false)
      setReceipt(values.is_closed ? '维修记录已关闭，原处理和验证保留。' : '维修进展已保存。')
      try { await onRefresh() } catch { if (current.current === identity) setError('已保存，但最新记录读取失败，请刷新核对，勿重复提交。') }
    } catch (e) { if (current.current === identity) setError(errMsg(e)) }
    finally { lock.current = false; if (current.current === identity) setBusy(false) }
  }
  const work = data.work_item as WorkItem | undefined
  if (owner !== key) return <Typography.Text>正在读取当前工作草稿</Typography.Text>
  return <section className="work-context">
    <Typography.Text strong>{data.project.name}</Typography.Text>
    {data.task.description && <p>{data.task.description}</p>}
    {draft.pending && <Alert type="warning" message="有历史数量操作待核对，原 UUID 和填写内容已保留" description="当前工作记录完成状态；历史数量不会自动改写或重报。" />}
    {receipt && <Alert type="success" message={receipt} />}
    {error && <Alert type="error" message={error} action={<Button onClick={() => void onRefresh().then(() => setError('')).catch(() => {})}>刷新核对</Button>} />}
    <Space wrap>{work && <WorkCompletionAction projectId={data.project.id} item={work} canRecord={canRecord} canOverride={!!data.can_override} onSaved={onRefresh} />}<Link to={`/pm/projects/${data.project.id}/schedule`}>查看周计划</Link><Link to={`/pm/projects/${data.project.id}/documents`}>项目资料清单</Link></Space>
    <h3>人员与安排</h3>
    {(data.entries || []).filter((entry: any) => entry.status !== 'skipped').map((entry: any) => <p key={entry.id}>{entry.work_date} · {entry.assignee_name}<Tag>{entry.is_confirmed ? '已发布' : '未发布'}</Tag>{entry.notes}</p>)}
    {data.repair && <><h3>维修与验证</h3><p>{data.repair.asset_code} · {data.repair.title} · {data.repair.is_closed ? '已关闭' : '待处理'}</p><p>{data.repair.action_taken}</p><p>{data.repair.verification}</p>{canRepair && <Button onClick={() => { form.setFieldsValue(draft.repair || { ...data.repair, status_after: undefined }); setRepairing(true) }}>记录维修与验证</Button>}</>}
    {repairing && <Form form={form} layout="vertical" disabled={busy || !canRepair} onFinish={saveRepair} onValuesChange={(_, value) => setDraft((d: any) => ({ ...d, repair: value }))}>
      <Form.Item name="action_taken" label="处理过程"><Input.TextArea rows={3} /></Form.Item><Form.Item name="verification" label="验证结果"><Input.TextArea rows={3} /></Form.Item>
      <Form.Item name="status_after" label="车辆当前状态"><Select allowClear options={[{ value: 'normal', label: '正常' }, { value: 'attention', label: '待关注' }, { value: 'fault', label: '故障' }, { value: 'stopped', label: '停用' }]} /></Form.Item>
      <Form.Item name="is_closed" label="本问题是否关闭"><Select options={[{ value: false, label: '继续处理' }, { value: true, label: '已验证，关闭问题' }]} /></Form.Item>
      <Space><Button type="primary" loading={busy} htmlType="submit">保存维修记录</Button><Button disabled={busy} onClick={() => setRepairing(false)}>收起，保留填写</Button></Space>
    </Form>}
  </section>
}

export function WorkCheckAction({ projectId, item, onSaved }: { projectId: string; item: any; onSaved: () => Promise<void> }) {
  const { user } = useAuth()
  const allowed = hasSystemPermission(user, 'worker.report')
  const [action, setAction] = useState<'fail' | 'na'>()
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const lock = useRef(false)
  const captured = useRef(item)
  const save = async (kind: 'pass' | 'fail' | 'na' = 'pass') => {
    if (!allowed || lock.current || (kind !== 'pass' && !reason.trim())) return
    lock.current = true; setBusy(true)
    const check = kind === 'pass' ? item : captured.current
    try {
      ensureVerifiedAccount(user?.id)
      await api.put(`/projects/${projectId}/check-items/${check.id}`, { version: check.version,
        ...(kind === 'fail' ? { failed: true, failed_reason: reason } : kind === 'na' ? { is_applicable: false, not_applicable_reason: reason } : { is_done: !check.is_done, failed: false, is_applicable: true }) })
      setAction(undefined); await onSaved()
    } catch (e) { message.error(errMsg(e)) }
    finally { lock.current = false; setBusy(false) }
  }
  return <><Space wrap><Button size="small" disabled={!allowed || busy} onClick={() => void save()}>{item.is_done ? '撤销通过' : '确认通过'}</Button><Button size="small" danger disabled={!allowed || busy} onClick={() => { captured.current = item; setReason(''); setAction('fail') }}>不通过</Button>{!item.is_safety_critical && <Button size="small" disabled={!allowed || busy} onClick={() => { captured.current = item; setReason(''); setAction('na') }}>不适用</Button>}</Space><Modal open={!!action} title={`检查${action === 'na' ? '不适用' : '不通过'}：${captured.current.name}`} okText="保存检查" cancelText="取消" onOk={() => void save(action)} confirmLoading={busy} okButtonProps={{ disabled: !allowed || !reason.trim() }} onCancel={() => { if (!lock.current) setAction(undefined) }}><Input.TextArea aria-label="检查状态理由" value={reason} onChange={e => setReason(e.target.value)} disabled={busy} /></Modal></>
}
