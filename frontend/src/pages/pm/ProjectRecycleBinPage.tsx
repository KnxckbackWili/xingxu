import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Empty, Input, Modal, Skeleton, Tag, Typography, message } from 'antd'
import { DownloadOutlined, ReloadOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { projectRecycleApi, type RecycledProject, type PermanentProjectBackup } from '../../api'
import { errMsg } from '../../api/client'
import { WorkPageHeader } from '../../components/WorkPage'
import { useAuth } from '../../stores/auth'
import { projectStatusMeta } from '../../constants/status'
import { formatDateTime } from '../../utils/date'
import PermanentProjectDeleteModal, { downloadPermanentProjectBackup } from '../../components/PermanentProjectDeleteModal'
import './ProjectRecycleBinPage.css'

export default function ProjectRecycleBinPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [rows, setRows] = useState<RecycledProject[]>([])
  const [permanent, setPermanent] = useState<RecycledProject | null>(null)
  const [permanentBackups, setPermanentBackups] = useState<PermanentProjectBackup[]>([])
  const [backupError, setBackupError] = useState('')
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<RecycledProject | null>(null)
  const [busy, setBusy] = useState(false)
  const [conflict, setConflict] = useState(false)
  const [actionError, setActionError] = useState('')
  const [downloading, setDownloading] = useState<string | null>(null)
  const sequence = useRef(0)
  const lock = useRef(false)
  const downloadLock = useRef(false)
  const alive = useRef(true)
  const actor = useRef(user?.id)
  actor.current = user?.id
  const allowed = !!user && user.permission_overrides?.['project.delete'] !== false && user.permission_overrides?.['project.read'] !== false
  const allowedRef = useRef(allowed)
  allowedRef.current = allowed
  const exportAllowed = !!user && user.permission_overrides?.['project.export'] !== false
  const exportAllowedRef = useRef(exportAllowed)
  exportAllowedRef.current = exportAllowed
  const signature = JSON.stringify([user?.id, user?.role, user?.permission_version, user?.permission_overrides])
  const policy = useRef(signature); policy.current = signature
  const purgeAllowed = user?.role === 'admin' && ['project.read', 'project.delete', 'project.export', 'system.projects.purge'].every(key => user.permission_overrides?.[key] !== false)
  const purgeAllowedRef = useRef(purgeAllowed); purgeAllowedRef.current = purgeAllowed
  const loadBackups = async () => {
    if (!purgeAllowedRef.current) return
    const identity = policy.current
    setBackupError('')
    try { const result = await projectRecycleApi.permanentBackups(); if (alive.current && policy.current === identity) setPermanentBackups(result) }
    catch (cause) { if (alive.current && policy.current === identity) setBackupError(errMsg(cause)) }
  }
  const load = async () => {
    const request = ++sequence.current, account = actor.current
    setLoading(true); setLoadError('')
    try {
      const result = await projectRecycleApi.list()
      if (alive.current && request === sequence.current && actor.current === account) setRows(result)
    } catch (cause) {
      if (alive.current && request === sequence.current && actor.current === account) setLoadError(errMsg(cause))
    } finally { if (alive.current && request === sequence.current && actor.current === account) setLoading(false) }
  }
  useEffect(() => {
    alive.current = true; setRows([]); setSelected(null); setPermanent(null); setPermanentBackups([])
    if (purgeAllowed) void loadBackups()
    void load()
    return () => { alive.current = false; sequence.current++ }
  }, [signature])
  const refreshSelected = async () => {
    if (!selected || lock.current || !allowedRef.current) return
    lock.current = true; setBusy(true)
    const account = actor.current
    try {
      const row = await projectRecycleApi.get(selected.id)
      if (!alive.current || actor.current !== account) return
      setSelected(row); setConflict(false); setActionError('')
      setRows(current => current.map(item => item.id === row.id ? row : item))
    } catch (cause) { if (alive.current && actor.current === account) setActionError(errMsg(cause)) }
    finally { lock.current = false; if (alive.current) setBusy(false) }
  }
  const restore = async () => {
    if (!selected?.can_restore || !allowedRef.current || conflict || lock.current) return
    const row = selected, account = actor.current
    lock.current = true; setBusy(true); setActionError('')
    try {
      await projectRecycleApi.restore(row.id, { version: row.version, deletion_id: row.deletion_id })
      if (!alive.current || actor.current !== account) return
      setSelected(null); setRows(current => current.filter(item => item.id !== row.id))
      message.success('原项目已还原，状态、成员与记录保持原样')
    } catch (cause: any) {
      if (!alive.current || actor.current !== account) return
      setActionError(errMsg(cause)); setConflict(cause.response?.status === 409)
    } finally { lock.current = false; if (alive.current) setBusy(false) }
  }
  const download = async (row: RecycledProject) => {
    if (!allowedRef.current || !exportAllowedRef.current || row.can_download_backup !== true || !row.delete_backup_available || downloadLock.current) return
    const account = actor.current, identity = policy.current
    downloadLock.current = true; setDownloading(row.id)
    try {
      const data = await projectRecycleApi.downloadBackup(row.id, row.deletion_id)
      if (!alive.current || actor.current !== account || policy.current !== identity || !allowedRef.current || !exportAllowedRef.current) return
      const url = URL.createObjectURL(data), link = document.createElement('a')
      link.href = url; link.download = `${row.name.replace(/[\\/:*?"<>|]/g, '_')}-删除前项目备份.zip.agvenc`; link.click(); URL.revokeObjectURL(url)
    } catch (cause) { if (alive.current && actor.current === account) message.error(errMsg(cause)) }
    finally { downloadLock.current = false; if (alive.current) setDownloading(null) }
  }
  const query = search.trim().toLocaleLowerCase()
  const visible = rows.filter(row => `${row.name} ${row.deleted_by_name}`.toLocaleLowerCase().includes(query))
  return <div className="project-recycle-page">
    <WorkPageHeader title="项目回收站" description="查看你有权限管理的已删除项目。还原会恢复原项目，保留删除前的状态、成员、资料和记录。"
      tools={<><Button disabled={busy} onClick={() => navigate('/pm/projects')}>返回项目</Button><Button aria-label="刷新回收站" disabled={busy} icon={<ReloadOutlined aria-hidden />} onClick={() => void load()}>刷新</Button></>} meta={loadError ? '列表暂不可用' : `${rows.length} 个已删除项目`} />
    <Alert type="info" showIcon message="回收站内项目不会自动清理" description="删除前备份并保留原项目。仅管理员可生成、下载加密备份后明确永久删除；历史归档只读保留，不再产生新的物理清理归档。备份仅包含对应项目的业务记录和文件，不提供整系统数据库或个人私有内容。" />
    <Input.Search aria-label="搜索回收站项目" placeholder="项目名称或删除人" allowClear value={search} onChange={event => setSearch(event.target.value)} className="project-recycle-search" />
    {loadError && <Alert type="error" showIcon message="回收站加载失败" description={loadError} action={<Button onClick={() => void load()}>重新加载</Button>} />}
    {loading && !rows.length ? <Skeleton active paragraph={{ rows: 5 }} /> : !loadError && !visible.length ? <Empty description={rows.length ? '没有匹配的已删除项目' : '回收站暂无项目'}><Button onClick={() => rows.length ? setSearch('') : navigate('/pm/projects')}>{rows.length ? '清除搜索' : '查看项目'}</Button></Empty> : <div className="project-recycle-list">
      {visible.map(row => <article className="project-recycle-card" key={row.id}>
        <div className="project-recycle-info"><h2>{row.name}</h2><div><Tag>删除前：{projectStatusMeta(row.status_before_delete).label}</Tag><Tag color={row.delete_backup_available ? 'green' : 'default'}>{row.delete_backup_available ? '已保留删除前备份' : '历史记录未附备份'}</Tag></div>
          <p>{row.deleted_by_name || '删除人未记录'} · {formatDateTime(row.deleted_at)}</p></div>
        <div className="project-recycle-actions"><Button aria-label={`还原项目：${row.name}`} type="primary" disabled={!allowed || !row.can_restore || busy} onClick={() => { setSelected(row); setConflict(false); setActionError('') }}>还原项目</Button>
          {row.delete_backup_available && row.can_download_backup === true && exportAllowed && <Button aria-label={`下载项目备份：${row.name}`} icon={<DownloadOutlined aria-hidden />} loading={downloading === row.id} disabled={!allowed || !!downloading} onClick={() => void download(row)}>下载项目备份</Button>}
          {user?.role === 'admin' && row.can_permanently_delete && <Button danger disabled={!allowed || busy} onClick={() => setPermanent(row)}>永久删除</Button>}</div>
      </article>)}
    </div>}
    {purgeAllowed && backupError && <Alert type="error" showIcon message="永久删除备份列表加载失败" description={backupError} action={<Button onClick={() => void loadBackups()}>重新读取备份列表</Button>} />}
    {purgeAllowed && permanentBackups.length > 0 && <section aria-label="永久删除备份"><h2>永久删除备份</h2>{permanentBackups.map(receipt => <div key={receipt.backup_id}><Typography.Text>{receipt.project_name} · {receipt.purged_at ? '已永久删除' : '已准备，尚未永久删除'}</Typography.Text><Button disabled={!!downloading || !exportAllowed} onClick={async () => {
      const account = actor.current, identity = policy.current
      setDownloading(receipt.backup_id)
      try { const publish = await downloadPermanentProjectBackup(receipt); if (alive.current && actor.current === account && policy.current === identity && purgeAllowedRef.current) publish() }
      catch (cause) { if (alive.current && actor.current === account) message.error(errMsg(cause)) }
      finally { if (alive.current && actor.current === account) setDownloading(null) }
    }}>下载加密备份</Button></div>)}</section>}
    <PermanentProjectDeleteModal key={user?.id} project={permanent} onClose={() => setPermanent(null)} onPurged={id => {
      setRows(current => current.filter(row => row.id !== id))
      void loadBackups()
    }} />
    <Modal className="project-recycle-modal" title="还原这个项目？" open={!!selected} onOk={restore} onCancel={() => { if (!lock.current) setSelected(null) }} okText="确认还原" cancelText="保留在回收站" confirmLoading={busy}
      okButtonProps={{ disabled: conflict || !allowed || !selected?.can_restore }} cancelButtonProps={{ disabled: busy }} closable={!busy} maskClosable={!busy}>
      {selected && <><Typography.Title level={5}>{selected.name}</Typography.Title><Typography.Paragraph>还原后项目回到项目列表，仍是删除前的「{projectStatusMeta(selected.status_before_delete).label}」。不会新建副本或重置历史数据。</Typography.Paragraph></>}
      {actionError && <Alert type="error" showIcon message={conflict ? '回收站记录已变化，请重新核对' : '未能确认还原结果，请核对后重试'} description={actionError}
        action={conflict ? <Button disabled={busy} onClick={() => void refreshSelected()}>读取最新记录</Button> : undefined} />}
    </Modal>
  </div>
}
