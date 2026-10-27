import { useEffect, useState } from 'react'
import { Alert, Button, Card, Empty, Space, Table, Tag, Typography } from 'antd'
import { Link, useParams } from 'react-router-dom'
import { projectApi } from '../../api'
import { api, errMsg } from '../../api/client'
import { projectDocumentsApi, downloadDocumentResource, type ProjectDocumentsResponse } from '../../api/projectDocuments'
import type { Matrix } from '../../api/fieldWeek'
import { useAuth } from '../../stores/auth'
import { WorkPageHeader } from '../../components/WorkPage'

export default function WorkerProjectDetailPage() {
  const { user } = useAuth(); const { projectId } = useParams(); const [project, setProject] = useState<{ name: string; status: string }>(); const [documents, setDocuments] = useState<ProjectDocumentsResponse>(); const [matrix, setMatrix] = useState<Matrix>(); const [error, setError] = useState(''); const [revision, setRevision] = useState(0)
  useEffect(() => { let live = true; setProject(undefined); setDocuments(undefined); setMatrix(undefined); setError(''); if (!projectId) return
    Promise.all([projectApi.get(projectId,{expectedAccount:user?.id}), projectDocumentsApi.list(projectId,undefined,user?.id), api.get(`/projects/${projectId}/vehicle-progress`, {headers:{'X-AGV-Expected-Account':user?.id || ''}})]).then(([p, d, m]) => { if (live) { setProject(p); setDocuments(d); setMatrix(m.data) } }).catch(e => { if (live) setError(errMsg(e)) }); return () => { live = false }
  }, [projectId, revision, user?.id])
  const download = async (path: string, name: string) => { try { await downloadDocumentResource(path, name) } catch (e) { setError(errMsg(e)) } }
  return <div className="worker-work-page"><WorkPageHeader title={project?.name || '项目'} description="只读查看项目、车辆进度与可见资料；实际操作在本周登记。" primary={<Link to={`/worker/week?project_id=${projectId || ''}`}>进入本周</Link>} tools={<Button onClick={() => setRevision(n => n + 1)}>刷新</Button>} />{error && <Alert type="error" message="项目信息未能完整读取" description={error} />}
    <Card title="车辆进度（只读）">{matrix ? <Table rowKey="id" dataSource={matrix.units} scroll={{ x: 650 }} columns={[{ title: '实际车号', key: 'vehicle', render: (_, unit) => unit.fleet_no || unit.asset_code }, ...matrix.steps.map(step => ({ title: step.name, key: step.key, render: (_: unknown, unit: Matrix['units'][number]) => <Tag color={unit.cells[step.key]?.is_done ? 'green' : 'default'}>{unit.cells[step.key]?.is_done ? unit.cells[step.key]?.done_on || '历史完成' : '未完成'}</Tag> }))]} /> : <Typography.Text>车辆状态尚未读取</Typography.Text>}</Card>
    <Card title="空白模板">{documents?.definitions.filter(rule => rule.blank_file_id).map(rule => <p key={rule.id}>{rule.code} {rule.name} <Button onClick={() => void download(`/projects/${projectId}/documents/requirements/${rule.id}/blank-file`, `${rule.code}-空白模板`)}>下载空白模板</Button></p>)}{documents && !documents.definitions.some(rule => rule.blank_file_id) && <Empty description="没有当前可见的空白模板" />}</Card>
    <Card title="当前资料">{documents?.documents.filter(row => row.applicable).map(row => <p key={row.id}><Space><span>{row.code} {row.name}</span><Tag>{row.status === 'submitted' ? '已提交' : row.status === 'waived' ? '不适用' : '待提交'}</Tag>{row.latest_version && <Button onClick={() => void download(row.latest_version!.download_url, row.latest_version!.filename)}>下载当前版本</Button>}</Space></p>)}</Card>
  </div>
}
