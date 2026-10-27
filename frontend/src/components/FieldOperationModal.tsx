import { useEffect, useRef, useState } from 'react'
import { Alert, DatePicker, Form, Input, Modal, Select, Typography } from 'antd'
import dayjs from 'dayjs'
import { fieldWeekApi, type Window } from '../api/fieldWeek'
import { api, errMsg } from '../api/client'
import { useAuth } from '../stores/auth'
import { enqueue, getQueue, getOfflineAccount } from '../offline/queue'
import { ensureVerifiedAccount } from '../utils/verifiedAccount'

export type FieldTarget = { project_id: string; kind: 'work' | 'vehicle' | 'check'; target_id: string; step_key?: string; version: number; is_done: boolean; weekly_cell_id?: string; name: string; window: Window; assisted?: { id: string; name: string }[]; record_id?: string; retract?: boolean; note?: string; completion_date?: string }
export default function FieldOperationModal({ target, onClose, onSaved }: { target: FieldTarget; onClose: () => void; onSaved: () => void }) {
  const { user } = useAuth(); const owner = useRef(user?.id); const current = useRef(user?.id); current.current = user?.id
  const [form] = Form.useForm(); const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [uncertain, setUncertain] = useState(false)
  const alive = useRef(true); useEffect(() => () => { alive.current = false }, [])
  const lock = useRef(false); const uuid = useRef(crypto.randomUUID()); const exact = useRef<Record<string, unknown>>()
  useEffect(() => { form.setFieldsValue({ completion_date: dayjs(target.completion_date || target.window.latest), reason: '', note: target.record_id ? target.note || '' : '' }) }, [target, form])
  const save = async () => {
    if (lock.current || owner.current !== current.current) return
    let values
    try { values = await form.validateFields() } catch { return }
    try { ensureVerifiedAccount(owner.current) } catch (e) { setError(errMsg(e)); return }
    const payload = exact.current || { project_id: target.project_id, kind: target.kind, target_id: target.target_id, step_key: target.step_key || '', weekly_cell_id: target.weekly_cell_id, is_done: target.is_done, version: target.version, client_uuid: uuid.current, reason: values.reason, note: values.note || '', completion_date: values.completion_date.format('YYYY-MM-DD'), ...(values.assisted_user_id ? { assisted_user_id: values.assisted_user_id } : {}) }
    exact.current = payload; lock.current = true; setBusy(true); setError('')
    try {
      ensureVerifiedAccount(owner.current)
      if (!navigator.onLine && !target.record_id) {
        if (getOfflineAccount() !== owner.current) throw new Error('账号已变化，未保存离线操作')
        if (!getQueue().some(row => row.client_uuid === payload.client_uuid)) enqueue(payload, 'field')
        if (!getQueue().some(row => row.client_uuid === payload.client_uuid)) throw new Error('无法确认本机保存，原填写仍保留')
      } else if (target.record_id) {
        const body = { version: payload.version, completion_date: payload.completion_date, reason: payload.reason, note: payload.note, client_uuid: payload.client_uuid }
        const headers = { 'X-AGV-Expected-Account': owner.current! }
        if (target.retract) await api.delete(`/worker/records/${target.record_id}`, { data: body, headers })
        else await api.put(`/worker/records/${target.record_id}`, body, { headers })
      } else await fieldWeekApi.save(payload, owner.current!)
      if (alive.current && owner.current === current.current && getOfflineAccount() === owner.current) { onSaved(); onClose() }
    } catch (e) {
      if (!alive.current || owner.current !== current.current) return
      const status = (e as { response?: { status: number } }).response?.status
      if (!status || status >= 500) { setUncertain(true); setError('结果尚未确认，原操作编号和内容已保留。重试会核对同一次操作。') }
      else { exact.current = undefined; setError(errMsg(e)); setUncertain(false) }
    } finally { lock.current = false; if (alive.current && owner.current === current.current && getOfflineAccount() === owner.current) setBusy(false) }
  }
  return <Modal open title={`${target.retract ? '撤回' : target.record_id ? '修改' : target.is_done ? '登记完成' : '登记未完成'} · ${target.name}`} onCancel={() => !busy && onClose()} onOk={() => void save()} confirmLoading={busy} maskClosable={false} okText={uncertain ? '核对原操作并重试' : '保存实际记录'} cancelText="取消">
    <Typography.Paragraph>完成日期按项目时区 {target.window.timezone} 核验。登记时间由服务器记录，修订与撤回均保留原始记录。</Typography.Paragraph>
    {error && <Alert type="error" message={error} />}
    <Form form={form} layout="vertical" disabled={busy || uncertain}>
      <Form.Item name="completion_date" label="实际完成日期" rules={[{ required: true }]}><DatePicker disabledDate={day => day.format('YYYY-MM-DD') < target.window.earliest || day.format('YYYY-MM-DD') > target.window.latest} /></Form.Item>
      {!!target.assisted?.length && <Form.Item name="assisted_user_id" label="协助登记（必须明确被协助人）" rules={[{ required: true, message: '请选择被协助人' }]}><Select options={target.assisted.map(p => ({ value: p.id, label: p.name }))} /></Form.Item>}
      <Form.Item name="reason" label="实际情况 / 修订理由" rules={[{ required: true, whitespace: true }]}><Input.TextArea maxLength={4000} autoSize={{ minRows: 2, maxRows: 6 }} /></Form.Item>
      <Form.Item name="note" label="附注"><Input.TextArea maxLength={4000} disabled={target.retract} /></Form.Item>
    </Form>
  </Modal>
}
