import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Empty, Input, Modal, Radio, Space, Tag, Typography } from 'antd'
import { api, errMsg } from '../../../api/client'
import { useProjectCapability, useProjectWriteBlocked } from '../../../hooks/useProjectCapability'
import { formatDateTime } from '../../../utils/date'
import { useAuth } from '../../../stores/auth'

const label = (item: unknown) => typeof item === 'string' ? item : item && typeof item === 'object'
  ? String((item as Record<string, unknown>).name ?? (item as Record<string, unknown>).item_name ?? (item as Record<string, unknown>).reason ?? '待核对事项') : '待核对事项'
export default function EntryReviewPanel({ projectId, onConfirmed, onDirtyChange }: { projectId: string; onConfirmed?: (summary: any) => void; onDirtyChange?: (dirty: boolean) => void }) {
  const { user } = useAuth()
  const canReview = useProjectCapability('project.manage_plan') && !useProjectWriteBlocked()
  const [open, setOpen] = useState(false)
  const [review, setReview] = useState<any>(null)
  const [history, setHistory] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [historyError, setHistoryError] = useState('')
  const [conclusion, setConclusion] = useState('not_ready')
  const [notes, setNotes] = useState('')
  const historySequence = useRef(0)
  const sequence = useRef(0)
  const generation = useRef(0)
  const lock = useRef(false)
  const unmet = (review?.entry_unmet ?? review?.unmet ?? []) as unknown[]
  const blocked = !!(unmet.length || review?.missing?.length)
  const path = `/projects/${encodeURIComponent(projectId)}/documents/dispatch-review`
  const loadHistory = async () => {
    const ticket = generation.current; const request = ++historySequence.current
    setHistoryError('')
    try { const response = await api.get(`${path}/history`); if (ticket === generation.current && request === historySequence.current) setHistory(Array.isArray(response.data) ? response.data : []) }
    catch (failure) { if (ticket === generation.current && request === historySequence.current) setHistoryError(errMsg(failure)) }
  }
  useEffect(() => {
    lock.current = false; setSaving(false); setLoading(false); setHistory([]); setReview(null); setOpen(false); setNotes(''); setError(''); void loadHistory()
    return () => { sequence.current++; generation.current++ }
  }, [projectId, user?.id, user?.permission_version])
  const inspect = async (preserve = false) => {
    if (!canReview || lock.current) return
    const ticket = ++sequence.current
    setOpen(true); setReview(null); setError(''); setLoading(true)
    if (!preserve) { setNotes(''); onDirtyChange?.(false) }
    try {
      const response = await api.post(path, undefined, { timeout: 600000 })
      if (ticket !== sequence.current) return
      setReview(response.data)
      const unmet = response.data.entry_unmet ?? response.data.unmet ?? []
      if (!preserve) setConclusion(unmet.length || response.data.missing?.length ? 'not_ready' : 'ready')
    } catch (failure) { if (ticket === sequence.current) setError(errMsg(failure)) }
    finally { if (ticket === sequence.current) setLoading(false) }
  }
  const confirm = async () => {
    if (!canReview || !review || loading || lock.current) return
    if (conclusion === 'ready' && blocked) { setError('发车前资料尚未齐备，请补交或明确批准风险并填写理由'); return }
    if (conclusion === 'risky' && !notes.trim()) { setError('请填写风险批准理由'); return }
    const ticket = generation.current
    lock.current = true; setSaving(true); setError('')
    try {
      const response = await api.post(`${path}/confirm`, { conclusion, notes: notes.trim(), review_token: review.review_token }, { timeout: 600000 })
      if (ticket !== generation.current) return
      onConfirmed?.(response.data.summary); onDirtyChange?.(false); setOpen(false); setReview(null); await loadHistory()
    } catch (failure) {
      if (ticket === generation.current) { setError(errMsg(failure)); if ((failure as { response?: { status?: number } }).response?.status === 409) setReview(null) }
    } finally { if (ticket === generation.current) { lock.current = false; setSaving(false) } }
  }
  return <div>
    <Typography.Paragraph type="secondary">按第5阶段必需资料及真实原件核对。缺项时可填写理由批准风险进场；新增缺项或条件恶化后需重新确认。历史准备评审只作原始记录。</Typography.Paragraph>
    <Space style={{ marginBottom: 12 }}><Button onClick={() => void loadHistory()}>刷新评审记录</Button>{canReview && <Button type="primary" onClick={() => void inspect()}>核对发车前资料</Button>}</Space>
    {historyError && <Alert type="error" showIcon message={historyError} />}
    {!historyError && !history.length && <Empty description="尚无发车前资料确认记录" />}
    {history.map(record => <article className="field-record-card" key={record.id}>
      <Space wrap>{record.legacy && <Tag>原准备评审，仅供追溯</Tag>}<Tag>{({ ready: '确认具备', risky: '批准风险进场', not_ready: '暂不进场' } as Record<string, string>)[record.conclusion] ?? record.conclusion}</Tag><Typography.Text>{record.reviewer_name || '原评审人未记录'} · {formatDateTime(record.reviewed_at)}</Typography.Text></Space>
      {record.notes && <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>{record.notes}</Typography.Paragraph>}
    </article>)}
    <Modal title="发车前资料核对" open={open} onCancel={() => { if (!saving) { sequence.current++; setOpen(false); onDirtyChange?.(false) } }} onOk={() => void confirm()} okText="保存确认结论" cancelText="取消" confirmLoading={saving} okButtonProps={{ disabled: loading || !review || !canReview || (conclusion === 'risky' && !notes.trim()) }} maskClosable={false}>
      {error && <Alert type="error" showIcon message={error} action={!review && !loading && <Button onClick={() => void inspect(true)}>重新核对</Button>} />}
      {loading ? <Typography.Paragraph>正在读取最新条件…</Typography.Paragraph> : review && <>
        {blocked ? <Alert type="warning" showIcon message="仍有发车前资料待落实" description={<ul>{[...unmet, ...(review.missing ?? [])].map((item, index) => <li key={index}>{label(item)}</li>)}</ul>} /> : <Alert type="success" showIcon message="第5阶段必需资料及原件已齐备" />}
        {(review.unmet ?? []).length > 0 && <details><summary>全部待落实事项（{review.unmet.length}）</summary><ul>{review.unmet.map((item: unknown, index: number) => <li key={index}>{label(item)}</li>)}</ul></details>}
        {(review.risks ?? []).length > 0 && <Typography.Paragraph type="warning">当前风险：{review.risks.map(label).join('；')}</Typography.Paragraph>}
        <Radio.Group aria-label="发车前资料确认结论" value={conclusion} onChange={event => { setConclusion(event.target.value); onDirtyChange?.(true) }} style={{ margin: '14px 0' }} options={[{ value: 'not_ready', label: '暂不进场' }, { value: 'risky', label: '批准风险进场' }, { value: 'ready', label: '确认具备', disabled: blocked }]} />
      </>}
      <Input.TextArea aria-label="发车前资料确认理由" rows={4} value={notes} onChange={event => { setNotes(event.target.value); onDirtyChange?.(true) }} placeholder="说明风险、处理安排或评审备注" disabled={saving} maxLength={4000} />
    </Modal>
  </div>
}
