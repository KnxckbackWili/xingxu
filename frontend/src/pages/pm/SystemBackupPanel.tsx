import { useAuth } from '../../stores/auth'
import { hasSystemPermission } from '../../constants/systemPermissions'
import { WorkPageHeader, WorkSection } from '../../components/WorkPage'
import { NAV_LABEL, NAV_DESCRIPTION } from '../../constants/nav'
import './SettingsPages.css'
import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Card, Input, Modal, Popconfirm, Space, Table, Tag, Typography, Upload, message } from 'antd'
import { CloudDownloadOutlined, DatabaseOutlined, DeleteOutlined, ReloadOutlined, UploadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { api, errMsg } from '../../api/client'
import { useSubmitLock } from '../../hooks/useSubmitLock'

type BackupData = { items: any[]; restore_pending: boolean; database?: string; web_restore_supported?: boolean; encryption?: { configured: boolean; source?: string } }

export default function SystemBackupPanel() {
  const { user } = useAuth()
  const canCreate = hasSystemPermission(user, 'system.backups.create')
  const canDownload = hasSystemPermission(user, 'system.backups.download')
  const canDelete = hasSystemPermission(user, 'system.backups.delete')
  const canRestore = hasSystemPermission(user, 'system.backups.restore')
  const canConfigure = user?.role === 'admin' && hasSystemPermission(user, 'system.backups.configure')
  const [data, setData] = useState<BackupData>({ items: [], restore_pending: false })
  const [loading, setLoading] = useState(false)
  const [metadataState, setMetadataState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [passwordOpen, setPasswordOpen] = useState(false)
  const [password, setPassword] = useState('')
  const [passwordAgain, setPasswordAgain] = useState('')
  const sequence = useRef(0)
  const scope = useRef(0)
  const restoreAllowed = useRef(false)
  const restoreSubmitting = useRef(false)
  const confirmDialog = useRef<ReturnType<typeof Modal.confirm> | null>(null)
  const mutationLock = useSubmitLock()

  const load = async () => {
    const request = ++sequence.current
    restoreAllowed.current = false
    setMetadataState('loading')
    try {
      const result = (await api.get('/system/backups')).data as BackupData
      if (request !== sequence.current) return
      setData(result)
      restoreAllowed.current = result.web_restore_supported === true && result.encryption?.configured === true
      setMetadataState('ready')
    } catch (error) {
      if (request !== sequence.current) return
      setMetadataState('error')
      message.error(errMsg(error))
    }
  }
  useEffect(() => {
    void load()
    return () => {
      scope.current++
      sequence.current++
      restoreAllowed.current = false
      confirmDialog.current?.destroy()
      confirmDialog.current = null
      setPassword(''); setPasswordAgain('')
    }
  }, [])

  const mutate = async (action: () => Promise<unknown>, success: string) => {
    if (!mutationLock.tryAcquire()) return false
    const generation = scope.current
    setLoading(true)
    try {
      await action()
      if (generation !== scope.current) return false
      message.success(success)
      await load()
      return true
    } catch (error) { if (generation === scope.current) message.error(errMsg(error)); return false }
    finally { mutationLock.release(); if (generation === scope.current) setLoading(false) }
  }
  const create = () => canCreate && mutate(() => api.post('/system/backups', { label: 'manual' }), '系统完整备份已生成')
  const remove = (filename: string) => canDelete && mutate(() => api.delete(`/system/backups/${filename}`), '备份已删除')
  const closePassword = () => { setPasswordOpen(false); setPassword(''); setPasswordAgain('') }
  const savePassword = async () => {
    if (!canConfigure) return
    if (password.length < 12 || password.length > 1024) { message.error('备份口令应为 12–1024 个字符'); return }
    if (password !== passwordAgain) { message.error('两次输入的备份口令不一致'); return }
    if (await mutate(() => api.put('/system/backup-encryption', { passphrase: password }), '备份口令已设置')) closePassword()
  }
  const download = async (filename: string) => {
    if (!canDownload) return
    const generation = scope.current
    try {
      const response = await api.get(`/system/backups/${filename}`, { responseType: 'blob' })
      if (generation !== scope.current) return
      const url = URL.createObjectURL(response.data); const link = document.createElement('a'); link.href = url; link.download = filename.endsWith('.agvenc') ? filename : filename + '.agvenc'; link.click(); URL.revokeObjectURL(url)
    } catch (error) { if (generation === scope.current) message.error(errMsg(error)) }
  }
  const restore = (file: File) => {
    // Missing or failed capability metadata must never imply SQLite/web-restore support.
    if (!canRestore || !restoreAllowed.current || !mutationLock.tryAcquire()) return false
    const generation = scope.current
    let restorePassword = ''
    setLoading(true)
    const release = () => {
      mutationLock.release()
      confirmDialog.current = null
      if (generation === scope.current) setLoading(false)
    }
    confirmDialog.current = Modal.confirm({
      title: '恢复整个 AGV 系统？',
      content: <Space direction="vertical" style={{ width: '100%' }}>
        <span>恢复会替换数据库、附件和系统密钥。系统会先生成加密的恢复前备份，上传后需要重启 Docker 容器。</span>
        <label htmlFor="restore-backup-password">这份备份的口令</label>
        <Input.Password id="restore-backup-password" autoComplete="off" onChange={event => { restorePassword = event.target.value }} />
      </Space>,
      okText: '校验并准备恢复', cancelText: '取消', okButtonProps: { danger: true },
      onCancel: (close) => { if (!restoreSubmitting.current) { release(); close() } },
      onOk: (close) => {
        if (restoreSubmitting.current) return
        if (generation !== scope.current || !canRestore || !restoreAllowed.current) { release(); close(); return }
        if (!restorePassword) { message.error('请输入这份备份的口令'); return }
        restoreSubmitting.current = true
        confirmDialog.current?.update({ okButtonProps: { danger: true, loading: true }, cancelButtonProps: { disabled: true }, keyboard: false })
        // Callback-style closing keeps failures retryable without an unhandled rejected promise.
        void (async () => {
          const body = new FormData(); body.append('file', file); body.append('confirm', 'RESTORE'); body.append('passphrase', restorePassword)
          try {
            const result = await api.post('/system/restore?confirm=RESTORE', body)
            if (generation !== scope.current) return
            message.success(result.data.message)
            await load()
            release()
            close()
          } catch (error) {
            if (generation === scope.current) message.error(errMsg(error))
          } finally {
            restoreSubmitting.current = false
            confirmDialog.current?.update({ okButtonProps: { danger: true, loading: false }, cancelButtonProps: { disabled: false }, keyboard: true })
          }
        })()
      },
    })
    return false
  }

  const configured = data.encryption?.configured === true
  const restoreDisabled = !canRestore || loading || metadataState !== 'ready' || data.web_restore_supported !== true || !configured
  const databaseLabel = data.database === 'postgresql' ? 'PostgreSQL 数据库' : data.database === 'sqlite' ? 'SQLite 数据库' : '数据库（类型尚未确认）'

  return <div className="settings-work-page system-backup-panel">
    <WorkPageHeader title={NAV_LABEL['/pm/backups']} description={NAV_DESCRIPTION['/pm/backups']}
      primary={canCreate && <Button type="primary" icon={<DatabaseOutlined />} loading={loading} disabled={metadataState !== 'ready' || !configured} onClick={create}>立即备份</Button>}
      tools={<Button icon={<ReloadOutlined />} onClick={load} disabled={loading} aria-label="刷新备份列表">刷新</Button>}
      meta={`${databaseLabel} · ${data.items.length} 个备份包`} />
    {metadataState === 'ready' && <Alert type={configured ? 'info' : 'warning'} showIcon style={{ marginBottom: 16 }}
      message={configured ? '系统备份已启用口令加密' : '请先设置备份口令'}
      description="下载的备份需要对应口令才能恢复。更换口令只影响新备份，请保留旧备份的口令。"
      action={canConfigure && <Button disabled={loading} onClick={() => setPasswordOpen(true)}>{configured ? '更换备份口令' : '设置备份口令'}</Button>} />}
    <Modal title="设置备份口令" open={passwordOpen} onOk={savePassword} onCancel={() => { if (!loading) closePassword() }} confirmLoading={loading}
      cancelButtonProps={{ disabled: loading }} keyboard={!loading} maskClosable={!loading} destroyOnClose>
      <Space direction="vertical" style={{ width: '100%' }}>
        <Typography.Text>请妥善保管口令；遗失后无法恢复对应备份。口令不会放入备份包。</Typography.Text>
        <label htmlFor="backup-password">新备份口令（至少 12 个字符）</label>
        <Input.Password id="backup-password" autoComplete="new-password" value={password} onChange={event => setPassword(event.target.value)} disabled={loading} />
        <label htmlFor="backup-password-again">再次输入备份口令</label>
        <Input.Password id="backup-password-again" autoComplete="new-password" value={passwordAgain} onChange={event => setPasswordAgain(event.target.value)} disabled={loading} />
      </Space>
    </Modal>
    {data.restore_pending && <Card size="small" style={{ marginBottom: 12, borderColor: '#d89614' }}><Tag color="warning">待恢复</Tag>备份已通过校验，请重启 Docker 容器应用恢复。</Card>}
    <WorkSection title="已保存的备份" description="生成后请下载到另一台设备；备份包含数据库、项目附件和系统密钥。">
      {metadataState === 'error' && <Alert type="error" showIcon message="备份信息加载失败，恢复功能已禁用" action={<Button size="small" onClick={load} disabled={loading}>重试</Button>} style={{ marginBottom: 12 }} />}
      <Table scroll={{ x: 620 }} rowKey="filename" size="small" loading={metadataState === 'loading'} dataSource={data.items} pagination={{ defaultPageSize: 10, pageSizeOptions: [10, 20, 50], showSizeChanger: true }} columns={[
        { title: '备份文件', dataIndex: 'filename', render: (value: string, row: any) => <><Typography.Text strong>{value}</Typography.Text>{row.encrypted === false && <Tag style={{ marginLeft: 8 }}>历史明文 · 下载时加密</Tag>}</> },
        { title: '创建时间', dataIndex: 'created_at', width: 170, render: (value: number) => dayjs.unix(value).format('YYYY-MM-DD HH:mm') },
        { title: '大小', dataIndex: 'size', width: 100, render: (value: number) => `${(value / 1024 / 1024).toFixed(1)} MB` },
        { title: '操作', width: 150, render: (_: any, row: any) => <Space size={0}><Button disabled={!canDownload} type="link" icon={<CloudDownloadOutlined />} onClick={() => download(row.filename)}>下载</Button><Popconfirm disabled={!canDelete} title="删除这个备份包？" onConfirm={() => remove(row.filename)}><Button type="link" danger disabled={!canDelete || loading} icon={<DeleteOutlined />}>删除</Button></Popconfirm></Space> },
      ]} />
    </WorkSection>
    <details className="work-detail-summary settings-detail">
      <summary>恢复系统备份</summary>
      <p className="work-helper">恢复会替换整个系统的数据和附件；正常备份只需点击上方“立即备份”。</p>
      {metadataState === 'ready' && data.web_restore_supported !== true && <Alert type="info" showIcon message={data.database === 'postgresql' ? '当前 PostgreSQL 部署不支持网页恢复' : '当前部署未确认支持网页恢复'} description="请由管理员使用 docker/scripts/restore.sh 恢复备份。网页仍支持生成及下载备份。" style={{ marginTop: 12 }} />}
      <div className="backup-restore-zone"><div><Typography.Text strong>灾难恢复</Typography.Text><div><Typography.Text type="secondary">上传 .agvenc 加密完整备份，并输入这份备份的口令</Typography.Text></div></div><Upload disabled={restoreDisabled} showUploadList={false} accept=".agvenc" beforeUpload={(file) => restore(file as File)}><Button disabled={restoreDisabled} danger icon={<UploadOutlined />}>上传恢复包</Button></Upload></div>
    </details>
  </div>
}
