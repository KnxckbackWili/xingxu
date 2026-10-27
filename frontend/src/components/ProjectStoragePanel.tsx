import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Collapse, Input, InputNumber, Space, Table, Typography, message } from 'antd'
import { storageApi, type CleanupPreview, type StorageProject } from '../api/storage'
import { errMsg } from '../api/client'
import { useAuth } from '../stores/auth'
import { PROJECT_EVENT_LABELS } from '../constants/projectEvents'
export const storageSize = (bytes: number) => bytes >= 1073741824 ? `${(bytes / 1073741824).toFixed(2)} GB` : `${(bytes / 1048576).toFixed(1)} MB`

export default function ProjectStoragePanel({ projectId, canCleanup = false, onChanged }: { projectId: string; canCleanup?: boolean; onChanged?: () => void }) {
  const { user } = useAuth()
  const [info, setInfo] = useState<StorageProject>()
  const [keep, setKeep] = useState(8)
  const [preview, setPreview] = useState<CleanupPreview>()
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [stale, setStale] = useState(false)
  const epoch = useRef(0)
  const lock = useRef(false)
  useEffect(() => {
    const ticket = ++epoch.current
    setInfo(undefined); setPreview(undefined); setError(''); setReason(''); setKeep(8); setBusy(false); lock.current = false
    void storageApi.project(projectId).then(data => { if (ticket === epoch.current) setInfo(data) }).catch(failure => { if (ticket === epoch.current) setError(errMsg(failure)) })
    return () => { epoch.current++ }
  }, [projectId, user?.id, user?.permission_version])
  const act = async (confirm: boolean) => {
    if (lock.current || !canCleanup) return
    if (confirm && (!preview || stale || !reason.trim() || !preview.candidates.length)) return
    const ticket = epoch.current; lock.current = true; setBusy(true); setError('')
    try {
      if (!confirm) {
        const next = await storageApi.preview(projectId, keep)
        if (ticket === epoch.current) { setPreview(next); setStale(false) }
      } else {
        const result = await storageApi.confirm(projectId, preview!, reason.trim())
        if (ticket !== epoch.current) return
        message.success(`已登记清理 ${result.removed_files} 个文件，${storageSize(result.removed_bytes)}`)
        setPreview(undefined); setReason(''); if (result.warning) setError(result.warning)
        const next = await storageApi.project(projectId)
        if (ticket === epoch.current) { setInfo(next); onChanged?.() }
      }
    } catch (failure) {
      if (ticket === epoch.current) { setError(errMsg(failure)); if (confirm) setStale(true) }
    } finally { if (ticket === epoch.current) { lock.current = false; setBusy(false) } }
  }
  return <section aria-label="项目存储与保留策略">
    {error && <Alert type="error" showIcon message={error} />}
    {info && <Typography.Paragraph>正式文件 {info.file_count} 个，占用 {storageSize(info.bytes)}；临时分片 {storageSize(info.temporary_bytes)}；已按策略清理 {storageSize(info.removed_bytes)}。</Typography.Paragraph>}
    {info?.storage_warnings?.map((warning, i) => <Alert key={i} type="warning" showIcon message={warning} />)}
    {!!info?.missing_file_count && <Alert type="error" message={`有 ${info.missing_file_count} 个原文件缺失，请先核对备份。`} />}
    {canCleanup && <>
      <Typography.Paragraph>仅清理旧周期资料文件；最新一期、最近 N 期及里程碑保护版本保留。版本元数据和清理凭据继续保留。确认后原文件字节无法从本系统恢复。</Typography.Paragraph>
      <Space wrap><label>保留最近 <InputNumber aria-label="保留周数" min={1} max={520} precision={0} value={keep} disabled={busy} onChange={value => { setKeep(value ?? 8); setStale(true) }} /> 期</label><Button loading={busy} onClick={() => void act(false)}>预览清理文件</Button></Space>
      {preview && <div style={{ marginTop: 16 }}>
        <Typography.Text strong>将清理 {preview.candidates.length} 个文件，{storageSize(preview.candidate_bytes)}</Typography.Text>
        <Table rowKey="attachment_id" size="small" pagination={{ pageSize: 8 }} dataSource={preview.candidates} columns={[
          { title: '文件', dataIndex: 'filename' }, { title: '大小', render: (_, row) => storageSize(row.file_size) },
          { title: '资料 / 周次', render: (_, row) => row.documents.map(doc => `${doc.code} ${doc.name} ${doc.period_key ?? ''}`).join('；') },
        ]} />
        <Collapse items={[{ key: 'protected', label: `保留原因（${preview.protected.length} 个文件）`, children: preview.protected.map(row => <p key={row.attachment_id}>{row.filename}：{row.reason}</p>) }, { key: 'milestones', label: '里程碑保护依据', children: preview.milestone_protection.map((row, i) => <p key={i}>{PROJECT_EVENT_LABELS[row.event_key] ?? row.event_key}：{row.basis}（{row.precision}）</p>) }]} />
        <Input.TextArea aria-label="存储清理理由" placeholder="填写清理理由，确认后保留审计记录" rows={3} value={reason} disabled={busy} onChange={event => setReason(event.target.value)} maxLength={1000} style={{ margin: '12px 0' }} />
        {stale && <Alert type="warning" message="请重新预览当前文件及保护范围，再确认清理。" />}
        <Button danger disabled={busy || stale || !reason.trim() || !preview.candidates.length} loading={busy} onClick={() => void act(true)}>确认清理上列文件</Button>
      </div>}
    </>}
  </section>
}
