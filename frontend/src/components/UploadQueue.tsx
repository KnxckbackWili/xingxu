import { useEffect, useRef, useState } from 'react'
import { Alert, Badge, Button, Drawer, Empty, Input, Popconfirm, Progress, Space, Tag, Typography, message } from 'antd'
import { CloudUploadOutlined } from '@ant-design/icons'
import { errMsg } from '../api/client'
import { OFFLINE_ACCOUNT_EVENT } from '../offline/queue'
import { observeUploadQueue, uploadQueue, UPLOAD_QUEUE_EVENT } from '../uploads/queue'
import { isUploadQueued, type UploadJob } from '../uploads/types'

const labels: Record<UploadJob['phase'], string> = { queued: '等待上传', hashing: '校验原文件', uploading: '上传分片', finishing: '服务器核验与保存', paused: '已暂停', needs_file: '需重新选择原文件', error: '需要处理', completed: '正式文件已保存', cancelled: '已停止传输' }
const size = (bytes: number) => `${(bytes / 1048576).toFixed(1)} MB`

export default function UploadQueue({ ownerId }: { ownerId: string }) {
  const [rows, setRows] = useState<UploadJob[]>([])
  const [open, setOpen] = useState(false)
  const [error, setError] = useState('')
  const [working, setWorking] = useState<string>()
  const epoch = useRef(0)
  useEffect(() => observeUploadQueue(), [])
  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const refresh = async () => {
      const ticket = ++epoch.current
      const data = await uploadQueue.list()
      if (alive && ticket === epoch.current) setRows(data.filter(row => row.owner_id === ownerId))
    }
    const update = () => { if (!timer) timer = setTimeout(() => { timer = undefined; void refresh() }, 150) }
    const account = () => { epoch.current++; setRows([]); setOpen(false); setError(''); update() }
    window.addEventListener(UPLOAD_QUEUE_EVENT, update)
    window.addEventListener(OFFLINE_ACCOUNT_EVENT, account)
    void refresh()
    return () => { alive = false; epoch.current++; clearTimeout(timer); window.removeEventListener(UPLOAD_QUEUE_EVENT, update); window.removeEventListener(OFFLINE_ACCOUNT_EVENT, account) }
  }, [ownerId])
  const current = rows.filter(row => row.owner_id === ownerId)
  const pending = current.filter(row => !['completed', 'cancelled'].includes(row.phase))
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (current.some(row => !row.metadata_durable || !['completed', 'cancelled'].includes(row.phase) && !row.durable_file)) { event.preventDefault(); event.returnValue = '' }
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [current])
  const act = async (key: string, operation: () => Promise<unknown>) => {
    setWorking(key); setError('')
    try { await operation() }
    catch (failure) { if (isUploadQueued(failure)) message.info(failure.message); else setError(errMsg(failure)) }
    finally { setWorking(undefined) }
  }
  return <>
    {/* Only shown in the top bar while this account has upload records. */}
    {current.length > 0 && <Badge count={pending.length} size="small"><Button type="text" aria-label="打开上传队列" title="上传队列" icon={<CloudUploadOutlined />} onClick={() => setOpen(true)} /></Badge>}
    <Drawer title="上传队列" open={open} onClose={() => setOpen(false)} width={520}>
      <Typography.Paragraph type="secondary">分片上传可在断网后继续。仅服务器完成文件核验并保存后，资料才会更新为已提交。队列只显示当前账号的文件。</Typography.Paragraph>
      {error && <Alert type="error" showIcon message={error} closable onClose={() => setError('')} />}
      {!current.length && <Empty description="暂无上传记录" />}
      {current.map(row => <article key={row.key} style={{ borderBottom: '1px solid #eee', padding: '16px 0' }}>
        <Typography.Text strong>{row.intent.filename}</Typography.Text> <Tag color={row.phase === 'completed' ? 'green' : row.phase === 'error' ? 'red' : 'blue'}>{labels[row.phase]}</Tag>
        <p>{size(row.intent.size)}{row.cancel_requested ? ' · 等待服务器确认停止' : ''}</p>
        {row.phase === 'hashing' ? <Progress aria-label="文件校验进度" percent={Math.floor(row.hashed_bytes / row.intent.size * 100)} size="small" /> : <Progress aria-label="文件上传进度" percent={Math.floor(row.uploaded_bytes / row.intent.size * 100)} status={row.phase === 'completed' ? 'success' : row.phase === 'error' ? 'exception' : 'normal'} size="small" />}
        {!['completed', 'cancelled'].includes(row.phase) && !row.durable_file && <Alert type="warning" showIcon message="原文件未保存到离线存储" description="请保持此页面。关闭后需重新选择相同文件，已接收分片仍可继续。" />}
        {!row.metadata_durable && <Alert type="warning" message="队列记录尚未持久保存，请保持页面并重试。" />}
        {row.error && <Typography.Paragraph type="danger">{row.error}</Typography.Paragraph>}
        <Space wrap>
          {['queued', 'hashing', 'uploading'].includes(row.phase) && <Button size="small" onClick={() => void act(row.key, () => uploadQueue.pause(row.key))}>暂停</Button>}
          {['paused', 'error', 'needs_file'].includes(row.phase) && <Button size="small" loading={working === row.key} onClick={() => void act(row.key, () => uploadQueue.retry(row.key))}>继续</Button>}
          {!['completed', 'cancelled', 'finishing'].includes(row.phase) && <Popconfirm title="停止此项上传并清理服务器临时分片？正式文件不会删除。" onConfirm={() => act(row.key, () => uploadQueue.cancel(row.key))}><Button size="small" danger>停止传输</Button></Popconfirm>}
          {(row.phase === 'completed' || row.phase === 'cancelled' && !row.cancel_requested) && <Button size="small" onClick={() => void act(row.key, () => uploadQueue.removeCompleted(row.key))}>移除记录</Button>}
        </Space>
        {['needs_file', 'error', 'paused'].includes(row.phase) && <label style={{ display: 'block', marginTop: 8 }}>重新选择原文件<Input aria-label={`重新选择${row.intent.filename}`} type="file" disabled={working === row.key} onChange={event => { const file = event.target.files?.[0]; if (file) void act(row.key, () => uploadQueue.retry(row.key, file)); event.target.value = '' }} /></label>}
      </article>)}
    </Drawer>
  </>
}
