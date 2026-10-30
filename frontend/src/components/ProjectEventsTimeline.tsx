import { useAuth } from '../stores/auth'
import { useEffect, useRef, useState } from 'react'
import { Alert, Button, DatePicker, Form, Input, Modal, Select, Typography } from 'antd'
import dayjs from 'dayjs'
import { api, errMsg } from '../api/client'
import { inProjectTime, type ProjectEvent } from '../constants/projectEvents'
import './ProjectEventsTimeline.css'
import { WorkSection } from './WorkPage'

export default function ProjectEventsTimeline({ projectId, canEdit, onChanged, initialData }: {
  projectId: string; canEdit: boolean; onChanged?: () => void; initialData?: any
}) {
  const { user } = useAuth()
  const scope = useRef(0)
  const [precision, setPrecision] = useState<'date' | 'datetime'>('datetime')
  const [data, setData] = useState<{ events: ProjectEvent[]; timezone?: string; version?: number; dispatch_platform?: string; arrival_summary?: any } | null>(null)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState<{ event: ProjectEvent; clear: boolean; projectId: string } | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [form] = Form.useForm()
  const busy = useRef(false)
  const mounted = useRef(true)
  const sequence = useRef(0)
  const load = async () => {
    const request = ++sequence.current
    try {
      const response = await api.get(`/projects/${projectId}/events`)
      if (mounted.current && request === sequence.current) { setData(response.data); setError('') }
    } catch (cause) { if (mounted.current && request === sequence.current) setError(errMsg(cause)) }
  }
  useEffect(() => { mounted.current = true; if (initialData !== undefined) { setData(initialData); setError('') } else load(); return () => { mounted.current = false; sequence.current++ } }, [projectId, initialData])
  useEffect(() => { scope.current++; setEditing(null); setSaveError(''); busy.current = false; setSaving(false); return () => { scope.current++ } }, [projectId, user?.id])
  const zone = data?.timezone || 'Asia/Shanghai'
  const open = (event: ProjectEvent, clear = false) => {
    setEditing({ event, clear, projectId }); setSaveError(''); setPrecision(event.actual_precision === 'date' ? 'date' : 'datetime')
    form.setFieldsValue({ actual_at: event.actual_date ? dayjs.tz(event.actual_date, zone) : event.actual_at ? inProjectTime(event.actual_at, zone) : inProjectTime(undefined, zone), reason: '', note: event.note || '' })
  }
  const save = async (values: any) => {
    if (!editing || editing.projectId !== projectId || !canEdit || busy.current) return
    const ticket = scope.current
    busy.current = true; setSaving(true); setSaveError('')
    try {
      await api.put(`/projects/${projectId}/events/${editing.event.event_key}`, {
        ...(editing.clear ? { actual_at: null } : precision === 'date' ? { actual_date: values.actual_at.format('YYYY-MM-DD') } : { actual_at: dayjs.tz(values.actual_at.format('YYYY-MM-DD HH:mm:ss'), zone).toISOString() }),
        note: values.note ?? '', reason: values.reason ?? '', version: data?.version,
      })
      if (mounted.current && ticket === scope.current) { setEditing(null); await load(); onChanged?.() }
    } catch (cause) { if (mounted.current && ticket === scope.current) setSaveError(errMsg(cause)) }
    finally { if (ticket === scope.current) { busy.current = false; if (mounted.current) setSaving(false) } }
  }
  const summary = data?.arrival_summary
  return <WorkSection title="关键事件" description={`调度平台：${data?.dispatch_platform === 'integrated' ? '集成' : data?.dispatch_platform || '未设置'} · 现场时区：${zone}`}>
    {error ? <Alert type="error" showIcon message="关键事件加载失败" description={error} action={<Button onClick={load}>重试关键事件</Button>} />
      : !data ? <Typography.Text type="secondary">正在读取关键事件…</Typography.Text>
      : <ol className="events-timeline" aria-label="关键事件">{(data.events ?? []).map(event => {
          const done = !!(event.actual_at || event.actual_date)
          const actual = event.derived ? event.actual_date || '未全部到场' : event.actual_date ? event.actual_date : event.actual_at ? inProjectTime(event.actual_at, zone).format('YYYY-MM-DD HH:mm') : '未登记'
          return <li key={event.event_key} className={done ? 'is-done' : ''}>
            <span className="events-dot" aria-hidden="true" />
            <div className="events-copy">
              <strong>{event.label}</strong>
              <span className="events-dates">计划 {event.planned_date || '未安排'} · 实际 {actual}</span>
              {event.derived && summary && <small>计划 {summary.expected} 台 · 已建档 {summary.registered} 台 · 到场 {summary.arrived} 台{summary.registry_complete ? '' : '（车辆档案未齐）'}</small>}
              {(event.actual_date || event.actual_source?.kind === 'legacy_status_transition') && <small>{event.source_description}</small>}
              {event.note && <small>{event.note}</small>}
            </div>
            {canEdit && !event.derived && <span className="events-actions">
              <Button size="small" type="link" aria-label={done ? `更正${event.label}时间` : `登记${event.label}已发生`} onClick={() => open(event)}>{done ? '更正' : '登记'}</Button>
              {done && <Button size="small" type="link" danger aria-label={`清除${event.label}实际时间`} onClick={() => open(event, true)}>清除</Button>}
            </span>}
          </li>
        })}</ol>}
    <Modal key={projectId} title={editing ? `${editing.clear ? '清除' : '登记'}${editing.event.label}实际时间` : ''} open={!!editing && editing.projectId === projectId}
      confirmLoading={saving} onCancel={() => { if (!busy.current) setEditing(null) }} onOk={() => form.submit()} okText="保存" okButtonProps={{ disabled: !canEdit }}>
      <Form form={form} layout="vertical" disabled={saving || !canEdit} onFinish={save}>
        {!editing?.clear && <Form.Item label="发生时间精度"><Select aria-label="发生时间精度" value={precision} onChange={setPrecision} options={[{value:'datetime',label:'实际时间'},{value:'date',label:'实际日期（仅精确到日）'}]} /></Form.Item>}
        {!editing?.clear && <Form.Item name="actual_at" label={`实际时间（${zone}）`} rules={[{ required: true, message: '请选择实际发生时间' }]}><DatePicker showTime={precision === 'datetime'} style={{ width: '100%' }} /></Form.Item>}
        {editing?.clear && <Alert type="warning" showIcon message="清除已发生时间必须填写理由，原时间和理由会保留在操作记录。" />}
        <Form.Item name="reason" label={editing?.clear ? '清除理由' : '更正说明'} rules={editing?.clear ? [{ required: true, whitespace: true, message: '请填写清除理由' }] : []}><Input.TextArea maxLength={1000} rows={2} /></Form.Item>
        <Form.Item name="note" label="备注"><Input.TextArea maxLength={2000} rows={2} /></Form.Item>
        {saveError && <Alert type="error" showIcon message={saveError} />}
      </Form>
    </Modal>
  </WorkSection>
}
