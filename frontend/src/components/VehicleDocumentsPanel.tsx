import { useEffect, useRef, useState } from 'react'
import { message, Alert, Button, Empty, Input, Modal, Space, Spin, Tag, Typography, Upload } from 'antd'
import { DownloadOutlined, HistoryOutlined, UploadOutlined } from '@ant-design/icons'
import { errMsg } from '../api/client'
import { isUploadQueued } from '../uploads/types'
import { UPLOAD_COMPLETE_EVENT } from '../uploads/queue'
import { projectDocumentsApi, downloadDocumentResource, type ProjectDocument, type ProjectDocumentsResponse } from '../api/projectDocuments'
import { useAuth } from '../stores/auth'
import { hasSystemPermission } from '../constants/systemPermissions'
import { useProjectWriteBlocked } from '../hooks/useProjectCapability'
import { deadlineLabel, basisLabel } from '../utils/documentDeadlines'
import { formatDateTime } from '../utils/date'

const statusName = { pending: '待提交', submitted: '已提交', waived: '不适用' }

/** One vehicle view of the canonical instances; files and versions have one owner. */
export default function VehicleDocumentsPanel({ projectId, unitId, unitLabel, projectStatus, onChanged }: {
  projectId: string; unitId: string; unitLabel: string; projectStatus: string; onChanged?: () => void
}) {
  const { user } = useAuth()
  const writeBlocked = useProjectWriteBlocked(projectStatus)
  const [data, setData] = useState<ProjectDocumentsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [actionError, setActionError] = useState('')
  const [target, setTarget] = useState<ProjectDocument | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [history, setHistory] = useState<string | null>(null)
  const current = useRef({ projectId, unitId, userId: user?.id, generation: 0 })
  if (current.current.projectId !== projectId || current.current.unitId !== unitId || current.current.userId !== user?.id) {
    current.current = { projectId, unitId, userId: user?.id, generation: current.current.generation + 1 }
  }
  const requests = useRef(0)
  const busy = useRef(false)
  const load = async () => {
    const generation = current.current.generation
    const ticket = ++requests.current
    setLoading(true); setLoadError('')
    try {
      const response = await projectDocumentsApi.list(projectId, { vehicle_unit_id: unitId })
      if (!Array.isArray(response.documents) || !Array.isArray(response.definitions) || !response.permissions) throw new Error('资料响应不完整，请重试读取')
      if (generation !== current.current.generation || ticket !== requests.current) return
      setData(response)
    } catch (failure) {
      if (generation === current.current.generation && ticket === requests.current) setLoadError(errMsg(failure))
    } finally {
      if (generation === current.current.generation && ticket === requests.current) setLoading(false)
    }
  }
  useEffect(() => {
    setData(null); setTarget(null); setFile(null); setNote(''); setHistory(null); setActionError('')
    void load()
    return () => { current.current.generation++; requests.current++ }
  }, [projectId, unitId, user?.id])
  useEffect(() => { const refresh = () => { void load() }; window.addEventListener(UPLOAD_COMPLETE_EVENT, refresh); return () => window.removeEventListener(UPLOAD_COMPLETE_EVENT, refresh) }, [projectId, unitId, user?.id])
  const permissionVersion = useRef(user?.permission_version)
  useEffect(() => {
    if (permissionVersion.current !== user?.permission_version) {
      permissionVersion.current = user?.permission_version
      void load()
    }
  }, [user?.permission_version])
  const canSubmit = !!data?.permissions?.submit && hasSystemPermission(user, 'worker.deliver') && !writeBlocked && !loading && !loadError
  // Validate the returned owner again; a delayed response must never open another car's upload.
  const documents = (data?.documents ?? []).filter(row => row.scope === 'vehicle' && row.vehicle_unit_id === unitId)
  const waiting = (data?.definitions ?? []).filter(row => row.scope === 'vehicle' && row.instance_count === 0)
  const timezone = data?.timezone || 'Asia/Shanghai'
  const download = async (path: string, name: string) => {
    const generation = current.current.generation
    try { await downloadDocumentResource(path, name) }
    catch (failure) { if (generation === current.current.generation) setActionError(errMsg(failure)) }
  }
  const submit = async () => {
    if (busy.current || !target || !file || !canSubmit || !documents.some(row => row.id === target.id)) return
    const generation = current.current.generation
    const owner = { projectId, unitId, documentId: target.id, file, note }
    busy.current = true; setSaving(true); setActionError('')
    try {
      await projectDocumentsApi.upload(owner.projectId, { file: owner.file, documentIds: [owner.documentId], note: owner.note })
      if (generation !== current.current.generation) return
      setTarget(null); setFile(null); setNote(''); await load(); onChanged?.()
    } catch (failure) {
      if (generation === current.current.generation) {
        if (isUploadQueued(failure)) { setTarget(null); setFile(null); setNote(''); message.info(failure.message) }
        else setActionError(errMsg(failure))
      }
    } finally {
      busy.current = false
      setSaving(false)
    }
  }
  return <section aria-label={`${unitLabel}的资料`} style={{ marginTop: 20 }}>
    <Space wrap style={{ display: 'flex', justifyContent: 'space-between' }}>
      <Typography.Title level={4} style={{ margin: 0 }}>该车资料</Typography.Title>
      <Space wrap><Button onClick={() => void load()} loading={loading} disabled={saving}>刷新资料</Button><a href={`/pm/projects/${encodeURIComponent(projectId)}/documents?vehicle=${encodeURIComponent(unitId)}`}>在资料清单查看此车</a></Space>
    </Space>
    <Typography.Paragraph type="secondary">与项目资料清单共用同一份资料和版本；提交即可，审核不影响提交状态。</Typography.Paragraph>
    {loadError && <Alert type="error" showIcon message="该车资料读取失败" description={loadError} action={<Button onClick={() => void load()}>重试读取</Button>} />}
    {actionError && <Alert type="error" showIcon message="资料操作未完成" description={actionError} />}
    {loading && <Spin aria-label="正在读取该车资料" />}
    {!loading && !loadError && documents.length === 0 && <Empty description="该车暂无已生成资料" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
    {!loading && !loadError && documents.map(row => <article key={row.id} aria-label={`${row.code} ${row.name}`} style={{ border: '1px solid var(--ant-color-border, #d9d9d9)', borderRadius: 8, padding: 12, margin: '10px 0' }}>
      <Space wrap><Typography.Text strong>{row.code} {row.name}</Typography.Text><Tag color={row.status === 'submitted' ? 'green' : row.status === 'waived' ? 'default' : 'orange'}>{statusName[row.status]}</Tag>{row.period_key && <Tag>{row.period_key}</Tag>}<Tag>{row.required ? '必需' : '可选'}</Tag>{row.confidential && <Tag>保密</Tag>}{row.applicable === false && <Tag>当前项目不适用</Tag>}</Space>
      <p style={{ margin: '8px 0' }}>截止：{deadlineLabel(row.due_at, timezone)}{row.due_is_estimated ? '（预计）' : ''}{row.due_state === 'overdue' && <Tag color="red">已逾期</Tag>}</p>
      {basisLabel(row) && <Typography.Paragraph type="secondary">{basisLabel(row)}</Typography.Paragraph>}
      <Typography.Paragraph type="secondary">负责人：{row.effective_owner_name || '待指派'}{row.owner_warning ? `；${row.owner_warning}` : ''}</Typography.Paragraph>
      {row.status === 'waived' && <p>不适用理由：{row.waived_reason}</p>}
      {row.latest_version && <p>最新版本：{row.latest_version.filename} · {row.latest_version.uploaded_by_name || '原上传人未记录'} · {formatDateTime(row.latest_version.uploaded_at)}</p>}
      <Space wrap>
        {canSubmit && <Button icon={<UploadOutlined aria-hidden="true" />} disabled={saving || row.applicable === false} onClick={() => { if (!busy.current) { setTarget(row); setFile(null); setNote(''); setActionError('') } }}>上传{row.status === 'submitted' ? '新版本' : '资料'}</Button>}
        {row.blank_file_id && row.definition_id && <Button icon={<DownloadOutlined aria-hidden="true" />} onClick={() => void download(`/projects/${encodeURIComponent(projectId)}/documents/requirements/${encodeURIComponent(row.definition_id!)}/blank-file`, `${row.name}空白模板`)}>下载空白模板</Button>}
        {row.latest_version?.download_url && <Button icon={<DownloadOutlined aria-hidden="true" />} onClick={() => void download(row.latest_version!.download_url, row.latest_version!.filename)}>下载最新版本</Button>}
        {row.versions.length > 0 && <Button icon={<HistoryOutlined aria-hidden="true" />} onClick={() => setHistory(history === row.id ? null : row.id)}>版本历史（{row.versions.length}）</Button>}
      </Space>
      {history === row.id && <ul aria-label={`${row.name}版本历史`}>{[...row.versions].reverse().map(version => <li key={version.id}>{version.filename} · {version.uploaded_by_name || '原上传人未记录'} · {formatDateTime(version.uploaded_at)}{version.note && ` · ${version.note}`} {version.download_url && <Button type="link" onClick={() => void download(version.download_url, version.filename)}>下载此版本</Button>}</li>)}</ul>}
    </article>)}
    {!loading && !loadError && waiting.length > 0 && <details><summary>尚待生成的逐车资料要求（{waiting.length}）</summary>{waiting.map(row => <p key={row.id}>{row.code} {row.name}：{row.waiting_reason || '等待真实事件或周次生成资料'}</p>)}</details>}
    <Modal title={target ? `上传 ${target.code} ${target.name} · ${unitLabel}` : '上传该车资料'} open={!!target} onCancel={() => { if (!busy.current) { setTarget(null); setFile(null); setNote('') } }} onOk={() => void submit()} confirmLoading={saving} okText="提交资料" cancelText="取消" okButtonProps={{ disabled: !file || !canSubmit }} cancelButtonProps={{ disabled: saving }} maskClosable={!saving} closable={!saving} destroyOnClose>
      <Typography.Paragraph>文件将作为该车这项资料的新版本，原版本完整保留。</Typography.Paragraph>
      <Upload disabled={saving} maxCount={1} showUploadList={false} beforeUpload={selected => { if (!busy.current) setFile(selected); return false }} fileList={[]}><Button disabled={saving}>选择文件</Button></Upload>
      {file && <Space wrap style={{ marginTop: 8 }}><Typography.Text>已选择：{file.name}</Typography.Text><Button size="small" disabled={saving} onClick={() => { if (!busy.current) setFile(null) }}>移除文件</Button></Space>}

      <Input.TextArea aria-label="该车资料版本备注" value={note} onChange={event => setNote(event.target.value)} disabled={saving} maxLength={5000} placeholder="版本说明（可选）" style={{ marginTop: 12 }} />
      {actionError && <Alert type="error" message={actionError} />}
    </Modal>
  </section>
}
