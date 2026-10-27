import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Drawer, Space, Table, Typography } from 'antd'
import { Link } from 'react-router-dom'
import { storageApi, type StorageOverview, type StorageProject } from '../../api/storage'
import { errMsg } from '../../api/client'
import { useAuth } from '../../stores/auth'
import ProjectStoragePanel, { storageSize } from '../../components/ProjectStoragePanel'
export default function StorageSettingsPage() {
  const { user } = useAuth()
  const epoch = useRef(0)
  const [data, setData] = useState<StorageOverview>()
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [project, setProject] = useState<StorageProject>()
  const load = async () => { const ticket = ++epoch.current; setLoading(true); setError(''); try { const next = await storageApi.overview(); if (ticket === epoch.current) setData(next) } catch (failure) { if (ticket === epoch.current) setError(errMsg(failure)) } finally { if (ticket === epoch.current) setLoading(false) } }
  useEffect(() => { setData(undefined); setProject(undefined); void load(); return () => { epoch.current++ } }, [user?.id, user?.permission_version])
  return <div style={{ padding: 24 }}>
    <Space><Typography.Title level={2}>存储管理</Typography.Title><Button onClick={() => void load()} loading={loading}>刷新占用</Button></Space>
    {error && <Alert type="error" message={error} />}
    {data && <><Typography.Paragraph>全局正式文件 {data.file_count} 个，占用 {storageSize(data.bytes)}；临时分片 {storageSize(data.temporary_bytes)}；已按策略清理 {storageSize(data.removed_bytes)}。当前上传上限 {storageSize(data.max_upload_size)}。</Typography.Paragraph><Typography.Paragraph type="secondary">下表列出你可查看的项目，文件清理仍按项目权限和保密范围核验。</Typography.Paragraph></>}
    <Table rowKey="project_id" loading={loading} dataSource={data?.projects ?? []} scroll={{ x: 650 }} columns={[
      { title: '项目', render: (_, row: StorageProject) => <Link to={`/pm/projects/${encodeURIComponent(row.project_id)}/documents`}>{row.project_name}</Link> },
      { title: '文件数', dataIndex: 'file_count' }, { title: '正式占用', render: (_, row) => storageSize(row.bytes) },
      { title: '临时分片', render: (_, row) => storageSize(row.temporary_bytes) },
      { title: '保留策略', render: (_, row) => <Button onClick={() => setProject(row)}>查看与清理</Button> },
    ]} />
    <Drawer title={project ? `${project.project_name} · 存储` : '项目存储'} open={!!project} onClose={() => setProject(undefined)} width={760} destroyOnHidden>{project && <ProjectStoragePanel key={project.project_id} projectId={project.project_id} canCleanup={!!project.can_cleanup} onChanged={() => void load()} />}</Drawer>
  </div>
}
