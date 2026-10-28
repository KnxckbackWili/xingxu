import { useEffect, useRef, useState } from 'react'
import { Alert, Drawer, Space, Table } from 'antd'
import { Link } from 'react-router-dom'
import { storageApi, type StorageOverview, type StorageProject } from '../../api/storage'
import { errMsg } from '../../api/client'
import { useAuth } from '../../stores/auth'
import ProjectStoragePanel, { storageSize } from '../../components/ProjectStoragePanel'
import { IconAction, RefreshAction } from '../../components/IconAction'
import { WorkPageHeader } from '../../components/WorkPage'
import { FolderOpenOutlined } from '@ant-design/icons'
export default function StorageSettingsPage() {
  const { user } = useAuth()
  const epoch = useRef(0)
  const [data, setData] = useState<StorageOverview>()
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [project, setProject] = useState<StorageProject>()
  const load = async () => { const ticket = ++epoch.current; setLoading(true); setError(''); try { const next = await storageApi.overview(); if (ticket === epoch.current) setData(next) } catch (failure) { if (ticket === epoch.current) setError(errMsg(failure)) } finally { if (ticket === epoch.current) setLoading(false) } }
  useEffect(() => { setData(undefined); setProject(undefined); void load(); return () => { epoch.current++ } }, [user?.id, user?.permission_version])
  return <div>
    <WorkPageHeader title="存储管理" description="下表列出你可查看的项目，文件清理仍按项目权限和保密范围核验。" tools={<RefreshAction label="刷新占用" onClick={load} loading={loading} />}
      meta={data && <Space wrap size={[16, 4]}><span>正式文件 {data.file_count} 个 · {storageSize(data.bytes)}</span><span>临时分片 {storageSize(data.temporary_bytes)}</span><span>已清理 {storageSize(data.removed_bytes)}</span><span>上传上限 {storageSize(data.max_upload_size)}</span></Space>} />
    {error && <Alert type="error" message={error} />}
    <Table rowKey="project_id" loading={loading} dataSource={data?.projects ?? []} scroll={{ x: 650 }} columns={[
      { title: '项目', render: (_, row: StorageProject) => <Link to={`/pm/projects/${encodeURIComponent(row.project_id)}/documents`}>{row.project_name}</Link> },
      { title: '文件数', dataIndex: 'file_count' }, { title: '正式占用', render: (_, row) => storageSize(row.bytes) },
      { title: '临时分片', render: (_, row) => storageSize(row.temporary_bytes) },
      { title: '保留策略', render: (_, row) => <IconAction label="查看与清理" icon={<FolderOpenOutlined />} onClick={() => setProject(row)} /> },
    ]} />
    <Drawer title={project ? `${project.project_name} · 存储` : '项目存储'} open={!!project} onClose={() => setProject(undefined)} width={760} destroyOnHidden>{project && <ProjectStoragePanel key={project.project_id} projectId={project.project_id} canCleanup={!!project.can_cleanup} onChanged={() => void load()} />}</Drawer>
  </div>
}
