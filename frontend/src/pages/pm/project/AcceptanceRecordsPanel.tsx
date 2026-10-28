import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Empty, Form, Input, Modal, Select, Space, Tag, Typography } from 'antd'
import { api, errMsg } from '../../../api/client'
import { projectDocumentsApi, downloadProjectFile, type ProjectFile } from '../../../api/projectDocuments'
import AcceptanceDecision, { acceptanceLabels, type AcceptanceRecord } from '../../../components/AcceptanceDecision'
import { formatDateTime } from '../../../utils/date'
import { RefreshAction } from '../../../components/IconAction'

export default function AcceptanceRecordsPanel({ projectId, refreshToken, onChanged, onUpload, onDirtyChange }: {
  projectId: string; refreshToken?: unknown; onChanged?: () => void; onUpload?: () => void
  onDirtyChange?: (dirty: boolean) => void
}) {
  const [records, setRecords] = useState<AcceptanceRecord[]>([])
  const [project, setProject] = useState<any>(null)
  const [files, setFiles] = useState<ProjectFile[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [form] = Form.useForm()
  const sequence = useRef(0)
  const generation = useRef(0)
  const lock = useRef(false)
  const activeProject = useRef(projectId); activeProject.current = projectId
  const load = async () => {
    const ticket = ++sequence.current
    setLoading(true); setLoadError('')
    try {
      const [result, detail, attachments] = await Promise.all([
        api.get(`/projects/${encodeURIComponent(projectId)}/acceptance`),
        api.get(`/projects/${encodeURIComponent(projectId)}`),
        projectDocumentsApi.files(projectId),
      ])
      if (ticket !== sequence.current || activeProject.current !== projectId) return
      setRecords(Array.isArray(result.data) ? result.data : []); setProject(detail.data); setFiles(attachments)
    } catch (failure) { if (ticket === sequence.current) setLoadError(errMsg(failure)) }
    finally { if (ticket === sequence.current) setLoading(false) }
  }
  useEffect(() => {
    setProject(null); setRecords([]); setOpen(false); setSaveError(''); setSaving(false); form.resetFields()
    return () => { sequence.current++; generation.current++ }
  }, [projectId, form])
  useEffect(() => { void load() }, [projectId, refreshToken])
  const stage = project?.status === 'suspended' ? project?.suspension?.status_before : project?.status
  const canRecord = !!project?.capabilities?.includes('project.update') && ['executing', 'commissioning', 'pilot', 'acceptance', 'completed'].includes(stage)
  const today = project?.acceptance_summary?.as_of_date ?? ''
  const save = async (values: Record<string, unknown>) => {
    if (lock.current || !canRecord || loadError) return
    const ticket = generation.current
    lock.current = true; setSaving(true); setSaveError('')
    try {
      await api.post(`/projects/${encodeURIComponent(projectId)}/acceptance`, {
        ...values, accepted_by_name: String(values.accepted_by_name ?? '').trim(),
      })
      if (ticket === generation.current) { setOpen(false); onDirtyChange?.(false); await load(); onChanged?.() }
    } catch (failure) { if (ticket === generation.current) setSaveError(errMsg(failure)) }
    finally { if (ticket === generation.current) { lock.current = false; setSaving(false) } }
  }
  const current = records.find(record => record.id === project?.acceptance_summary?.latest?.id) || records.find(record => record.is_effective) || records[0]
  const renderRecord = (record: AcceptanceRecord) => <article key={record.id} className="field-record-card">
    <Space wrap><Typography.Text strong>{record.accepted_by_name}</Typography.Text><Tag color={record.conclusion === 'accepted' ? 'green' : 'orange'}>{acceptanceLabels[record.conclusion]}</Tag>
      {record.is_effective && <Tag color="blue">最新有效结果</Tag>}{record.scope_current === false && <Tag color="orange">范围已变更</Tag>}{record.scope_verified === false && <Tag>范围未核验</Tag>}
      {record.effective_date_reached === false && <Tag>尚未到验收日期</Tag>}
    </Space>
    <p>验收日期 {record.accepted_at} · 录入 {formatDateTime(record.created_at)}</p>
    {record.invalid_reason && <Typography.Paragraph type="warning">{record.invalid_reason}</Typography.Paragraph>}
    {record.notes && <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>{record.notes}</Typography.Paragraph>}
    {record.attachment_id && <Button size="small" onClick={() => void downloadProjectFile(record.attachment_id!, files.find(file => file.id === record.attachment_id)?.filename || '验收签字附件').catch(() => setSaveError('验收附件下载失败，请重试'))}>下载签字附件</Button>}
  </article>
  const retrospective = typeof project?.retrospective === 'string' ? { content: project.retrospective } : project?.retrospective ?? {}
  return <div aria-busy={loading}>
    <Typography.Paragraph type="secondary">验收以最新有效结论和当前车辆范围为准；选择的签字附件会同时关联本项目资料7.1；未选附件时仍需在资料清单补交项目验收单。</Typography.Paragraph>
    <Space wrap style={{ marginBottom: 12 }}><RefreshAction label="刷新验收记录" loading={loading} onClick={load} />
      {canRecord && <Button type="primary" disabled={loading || !!loadError || saving} onClick={() => { form.resetFields(); setSaveError(''); onDirtyChange?.(false); setOpen(true) }}>录入验收记录</Button>}
      {onUpload && <Button onClick={onUpload}>上传项目验收单</Button>}
    </Space>
    {loadError && <Alert type="error" showIcon message={loadError} action={<Button onClick={() => void load()}>重试</Button>} />}
    {saveError && !open && <Alert type="error" showIcon message={saveError} />}
    {project?.acceptance_summary?.latest && <AcceptanceDecision summary={project.acceptance_summary} />}
    {!loading && !loadError && !current && <Empty description={canRecord ? '尚未录入客户验收结果' : '尚无验收记录；由有项目资料维护权限的负责人录入'} />}
    {current && renderRecord(current)}
    {records.length > 1 && <details className="field-details"><summary>历史验收记录（{records.length - 1}）</summary>{records.filter(record => record.id !== current?.id).map(renderRecord)}</details>}
    <details className="field-details"><summary>项目复盘</summary>
      {['content', 'success', 'problems', 'improvements'].some(key => typeof retrospective[key] === 'string' && retrospective[key].trim()) ? <>
        <p>作者：{retrospective.author_name || '未记录'} · {formatDateTime(retrospective.written_at)}</p>
        {([['content', ''], ['success', '成功经验'], ['problems', '问题教训'], ['improvements', '改进建议']] as const).map(([key, label]) => retrospective[key] && <div key={key}>{label && <Typography.Text strong>{label}</Typography.Text>}<Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>{retrospective[key]}</Typography.Paragraph></div>)}
      </> : <Typography.Paragraph type="secondary">尚未填写复盘，归档时由负责人记录。</Typography.Paragraph>}
    </details>
    {project?.status === 'completed' && <Typography.Paragraph type="secondary">如需补报工作或调整计划，请由负责人先重新打开项目。</Typography.Paragraph>}
    <Modal title="录入验收记录" open={open} onCancel={() => { if (!saving) { setOpen(false); onDirtyChange?.(false) } }} onOk={() => form.submit()} confirmLoading={saving} okText="保存验收记录" cancelText="取消" maskClosable={false}>
      <Form form={form} layout="vertical" initialValues={{ conclusion: 'accepted' }} onFinish={save} disabled={saving} onValuesChange={() => onDirtyChange?.(true)}>
        {saveError && <Alert type="error" showIcon message={saveError} />}
        <Form.Item name="accepted_by_name" label="客户验收人" rules={[{ required: true, whitespace: true }]}><Input maxLength={100} /></Form.Item>
        <Form.Item name="accepted_at" label="验收日期" rules={[{ required: true }, { validator: (_, value) => today && value > today ? Promise.reject(new Error(`验收日期不能晚于项目当地今天（${today}）`)) : Promise.resolve() }]} extra={today ? `项目当地今天：${today}；补录旧日期不会替代较新的结论。` : '补录旧日期不会替代较新的结论。'}><Input type="date" max={today || undefined} /></Form.Item>
        <Form.Item name="conclusion" label="验收结论" rules={[{ required: true }]}><Select options={Object.entries(acceptanceLabels).map(([value, label]) => ({ value, label }))} /></Form.Item>
        <Form.Item name="attachment_id" label="签字附件"><Select allowClear showSearch optionFilterProp="label" options={files.map(file => ({ value: file.id, label: file.filename }))} /></Form.Item>
        <Form.Item name="notes" label="结论说明 / 遗留问题"><Input.TextArea rows={3} /></Form.Item>
      </Form>
    </Modal>
  </div>
}
