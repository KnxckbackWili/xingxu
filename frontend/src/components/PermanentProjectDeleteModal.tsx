import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Checkbox, Input, Modal, Space, Typography } from 'antd'
import { projectRecycleApi, type RecycledProject, type PermanentProjectBackup } from '../api'
import { useAuth } from '../stores/auth'
import { errMsg } from '../api/client'
import { useSubmitLock } from '../hooks/useSubmitLock'

export async function downloadPermanentProjectBackup(receipt: PermanentProjectBackup) {
  const data = await projectRecycleApi.downloadPermanent(receipt.backup_id)
  return () => {
    const url = URL.createObjectURL(data), link = document.createElement('a')
    link.href = url; link.download = `${receipt.project_name.replace(/[\\/:*?"<>|]/g, '_')}-永久删除备份.zip.agvenc`
    link.click(); URL.revokeObjectURL(url)
  }
}

export default function PermanentProjectDeleteModal({ project, onClose, onPurged }: { project: RecycledProject | null; onClose: () => void; onPurged: (id: string) => void }) {
  const { user } = useAuth()
  const [receipt, setReceipt] = useState<PermanentProjectBackup | null>(null)
  const [saved, setSaved] = useState(false)
  const [downloaded, setDownloaded] = useState(false)
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(false)
  const generation = useRef(0)
  const lock = useSubmitLock()
  const allowed = user?.role === 'admin' && project?.can_permanently_delete === true && ['project.read', 'project.delete', 'project.export', 'system.projects.purge'].every(key => user.permission_overrides?.[key] !== false)
  const signature = JSON.stringify([user?.id, user?.role, user?.permission_version, user?.permission_overrides, project?.id, project?.deletion_id, project?.version])
  const currentSignature = useRef(signature); currentSignature.current = signature
  useEffect(() => {
    generation.current++; setReceipt(null); setSaved(false); setDownloaded(false); setName(''); setError(''); setBusy(false); setDone(false)
    return () => { generation.current++ }
  }, [signature])
  const run = async (operation: (valid: () => boolean) => Promise<void>) => {
    if (!allowed || !project || !lock.tryAcquire()) return
    const current = generation.current, identity = currentSignature.current
    const valid = () => generation.current === current && currentSignature.current === identity
    setBusy(true); setError('')
    try { await operation(valid) }
    catch (cause) { if (valid()) setError(errMsg(cause)) }
    finally { lock.release(); if (valid()) setBusy(false) }
  }
  const prepare = () => run(async valid => {
    const result = await projectRecycleApi.preparePermanent(project!.id, { version: project!.version, deletion_id: project!.deletion_id })
    if (valid()) { setReceipt(result); setSaved(false); setDownloaded(false) }
  })
  const download = () => run(async valid => {
    if (!receipt) return
    const publish = await downloadPermanentProjectBackup(receipt)
    if (valid()) { publish(); setDownloaded(true) }
  })
  const remove = () => run(async valid => {
    if (!receipt || !saved || !downloaded || name !== project!.name || done) return
    const result = await projectRecycleApi.permanentlyDelete(project!.id, { version: project!.version, deletion_id: project!.deletion_id, backup_id: receipt.backup_id, confirm_name: name })
    if (valid()) { setDone(true); setReceipt(result); setName(''); onPurged(project!.id) }
  })
  return <Modal title={done ? '项目已永久删除' : '永久删除这个项目？'} open={!!project} footer={null} onCancel={() => { if (!busy) onClose() }} closable={!busy} maskClosable={!busy} keyboard={!busy} destroyOnHidden>
    <Space direction="vertical" style={{ width: '100%' }}>
      <Typography.Text strong>{project?.name}</Typography.Text>
      <Alert type={done ? 'success' : 'warning'} showIcon message={done ? '加密备份继续保留，可在回收站的永久删除备份中下载' : '永久删除不能从回收站还原'} description={done ? undefined : '先生成并下载当前项目的加密备份。备份失败、记录变化或文件不完整时，项目会保留在回收站。'} />
      {error && <Alert type="error" showIcon message="未能确认结果，请核对后重试" description={error} />}
      {!done && <Button loading={busy} disabled={!allowed} onClick={() => void prepare()}>{receipt ? '重新生成当前证据备份' : '生成加密项目备份'}</Button>}
      {receipt && <>
        <Typography.Text type="secondary">加密备份 · {receipt.bytes} 字节</Typography.Text><Typography.Text style={{ wordBreak: 'break-all' }}>SHA-256：{receipt.sha256}</Typography.Text>
        <Button loading={busy} disabled={!allowed} onClick={() => void download()}>下载加密项目备份</Button>
        {!done && <>
          <Checkbox checked={saved} disabled={!downloaded || busy} onChange={event => setSaved(event.target.checked)}>我已下载并安全保存这份加密备份</Checkbox>
          <label htmlFor="permanent-project-name">输入完整项目名称确认永久删除</label><Input id="permanent-project-name" value={name} onChange={event => setName(event.target.value)} autoComplete="off" disabled={busy} />
          <Button danger type="primary" loading={busy} disabled={!allowed || !saved || !downloaded || name !== project?.name} onClick={() => void remove()}>确认永久删除</Button>
        </>}
      </>}
      <Button disabled={busy} onClick={onClose}>{done ? '关闭' : '保留在回收站'}</Button>
    </Space>
  </Modal>
}
