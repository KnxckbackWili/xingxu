import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import {
  Tag, Button, Modal, Form, Input, Select, Upload, message, Space, Typography, Alert, Drawer, Divider, Empty, Segmented, Popover,
} from 'antd'
import {
  CheckCircleOutlined, DeleteOutlined, DownloadOutlined, FileExcelOutlined, FileTextOutlined, PaperClipOutlined,
  ImportOutlined, PlusOutlined, StopOutlined, UploadOutlined, UserSwitchOutlined,
} from '@ant-design/icons'
import { parseDateTime,formatDateTime } from '../../../utils/date'
import { saveBlob } from '../../../utils/download'
import { api, errMsg } from '../../../api/client'
import { projectDocumentsApi, uploadProjectFile, downloadProjectFile } from '../../../api/projectDocuments'
import { isUploadQueued } from '../../../uploads/types'
import { useSubmitLock } from '../../../hooks/useSubmitLock'
import { useMediaQuery } from '../../../hooks/useMediaQuery'
import { useProjectWriteBlocked } from '../../../hooks/useProjectCapability'
import { MEDIA_QUERY } from '../../../constants/breakpoints'
import { ISSUE_TYPES, ISSUE_TYPE_HINTS, ISSUE_TYPE_FIELDS, ISSUE_STATUS_MAP, ISSUE_NATURES, extraSummary } from '../../../constants/issues'
import InlineSelect from '../../../components/InlineSelect'
import { WorkPageHeader } from '../../../components/WorkPage'
import './FieldWorkPages.css'
import '../../../components/IssueList.css'
import { IconAction, RefreshAction } from '../../../components/IconAction'

interface Issue {
  can_close?: boolean
  reporter_id?: string
  id: string
  title: string
  description: string
  issue_type: string
  nature?:string
  sla_hours?:number
  sla_due_at?:string|null
  sla_basis?:string
  trigger_event_id?:string|null
  sla_warning?:string|null
  extra: Record<string, unknown> | null
  severity: 'critical' | 'high' | 'medium' | 'low'
  status: 'open' | 'processing' | 'resolved' | 'closed' | 'cancelled'
  reporter_name: string
  task_name: string
  created_at: string
  resolved_at: string | null
  resolution: string
  version: number
}

interface VehicleIssue {
  id: string
  source: 'vehicle'
  vehicle_unit_id: string
  asset_code: string
  vehicle_status: string
  title: string
  description: string
  fault_part: string
  cause: string
  action_taken: string
  replaced_parts: Array<{ name?: string; model?: string; quantity?: number }>
  verification: string
  handler: string
  downtime_hours: number | null
  status: 'open' | 'resolved'
  event_type: string
  event_date: string
  reporter_name: string
}

const SEVERITY_MAP: Record<string, { label: string; color: string }> = {
  critical: { label: '严重', color: 'red' },
  high: { label: '高', color: 'orange' },
  medium: { label: '中', color: 'gold' },
  low: { label: '低', color: 'blue' },
}

const TYPE_LABEL: Record<string, string> = {
  hardware: '硬件', software: '软件', environment: '环境', process: '流程', safety: '安全', other: '其他',
}

export default function IssuesPage({ projectId, canManage = false, archived = false }: { projectId: string; canManage?: boolean; archived?: boolean }) {
  const [issues, setIssues] = useState<Issue[]>([])
  const [vehicleIssues, setVehicleIssues] = useState<VehicleIssue[]>([])
  const [vehicleDetail, setVehicleDetail] = useState<VehicleIssue | null>(null)
  const loadRequest = useRef(0)
  const currentProject = useRef(projectId)
  currentProject.current = projectId
  const [tasks, setTasks] = useState<{ id: string; label: string; phase: string }[]>([])
  const [issueAtts, setIssueAtts] = useState<Record<string, any[]>>({})
  const [fileList, setFileList] = useState<any[]>([])
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState(archived ? 'all' : 'active')
  const [loadError, setLoadError] = useState(false)
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<Issue | null>(null)
  // 问题详情 Drawer（列表不再堆叠全字段）
  const [detailIssue, setDetailIssue] = useState<Issue | null>(null)
  const [form] = Form.useForm()
  const location = useLocation()
  const contextWriteBlocked = useProjectWriteBlocked()
  const writeBlocked = archived || contextWriteBlocked
  const canEdit = canManage && !writeBlocked
  const canClose = (issue: Issue) => !writeBlocked && issue.can_close === true
  // No assignment: anyone on the project (everyone) may start and resolve; the first to start becomes the handler.
  const canHandle = (_issue: Issue) => !writeBlocked
  const importLock = useSubmitLock()
  const [importing, setImporting] = useState(false)
  const submitLock = useSubmitLock()
  const [submitting, setSubmitting] = useState(false)
  const [createdIssueId, setCreatedIssueId] = useState<string | null>(null)
  const reportKey = useRef<string | null>(null)
  const [resolutionAction, setResolutionAction] = useState<'resolved' | 'cancelled'>('resolved')
  const [statusSaving, setStatusSaving] = useState(false)
  const statusLock = useSubmitLock()
  const [resolveForm] = Form.useForm()
  // 移动端（≤640px）：不再压缩桌面表格，改用卡片/分层行布局（见下方 isMobile 分支）
  const isMobile = useMediaQuery(MEDIA_QUERY.mobile)

  const load = async () => {
    const request = ++loadRequest.current
    setLoading(true); setLoadError(false)
    try {
      const [r, vehicles, ar] = await Promise.all([
        api.get(`/projects/${projectId}/issues`),
        api.get(`/projects/${projectId}/vehicle-issues`),
        projectDocumentsApi.files(projectId, { entity_type: 'issue' }),
      ])
      if (request !== loadRequest.current || currentProject.current !== projectId) return
      setIssues(r.data); setVehicleIssues(vehicles.data)
      const grouped: Record<string, any[]> = {}
      for (const a of ar) (grouped[a.entity_id] = grouped[a.entity_id] || []).push(a)
      setIssueAtts(grouped)
      return r.data as Issue[]
    } catch {
      if (request === loadRequest.current && currentProject.current === projectId) {
        setLoadError(true); message.error('问题列表加载失败')
      }
    } finally { if (request === loadRequest.current && currentProject.current === projectId) setLoading(false) }
  }

  const download = async (id: string, name: string) => {
    try { await downloadProjectFile(id, name) } catch (failure) { message.error(errMsg(failure)) }
  }

  /** 质量问题反馈单 (company form A02) for a project issue or a vehicle problem. */
  const downloadQualityForm = async (issue: { id: string; title: string; source?: string }) => {
    const path = issue.source === 'vehicle' ? 'vehicle-events' : 'issues'
    try {
      const r = await api.get(`/projects/${projectId}/${path}/${issue.id}/export/quality-form`, { responseType: 'blob' })
      saveBlob(r.data, `质量问题反馈单-${issue.title.slice(0, 20)}.xlsx`)
    } catch (e: any) { message.error(e.response?.data?.detail ?? '导出失败') }
  }

  const importQualityForm = async (file: File) => {
    if (writeBlocked || !importLock.tryAcquire()) return false
    setImporting(true)
    const fd = new FormData()
    fd.append('file', file)
    try {
      const r = await api.post(`/projects/${projectId}/import/quality-form`, fd, { timeout: 120000 })
      message.success(r.data?.message ?? '质量问题反馈单已导入')
      await load()
    } catch (e: any) { message.error(e.response?.data?.detail ?? '导入失败') }
    finally { importLock.release(); setImporting(false) }
    return false
  }

  useEffect(() => {
    load()
    let active = true
    // 任务列表（上报表单的「关联任务」选择）
    api.get(`/projects/${projectId}/tree`).then((r) => {
      if (!active) return
      const flat: { id: string; label: string; phase: string }[] = []
      for (const ph of r.data ?? []) {
        for (const t of ph.work_items ?? []) flat.push({ id: t.id, label: t.name, phase: ph.name })
      }
      setTasks(flat)
    }).catch(() => {})
    return () => { active = false; loadRequest.current++ }
  }, [projectId])

  // 支持从项目头部“上报问题”带 report=1 直达弹窗
  useEffect(() => {
    if (!writeBlocked && new URLSearchParams(location.search).get('report') === '1') {
      setModalOpen(true)
    }
  }, [location.search, writeBlocked])

  const matches = (title: string, description: string, status: string, context = '') => {
    const term = search.trim().toLocaleLowerCase()
    return (!term || `${title} ${description} ${context}`.toLocaleLowerCase().includes(term))
      && (statusFilter === 'all' || (statusFilter === 'active' ? ['open', 'processing'].includes(status) : status === statusFilter))
  }
  const filtered = issues.filter((i) => matches(i.title, i.description, i.status, i.reporter_name))
  const filteredVehicles = vehicleIssues.filter((i) => (statusFilter !== 'resolved') && matches(i.title, i.description, i.status, i.asset_code))
  const openProjectCount = issues.filter((i) => i.status === 'open' || i.status === 'processing').length
  const openVehicleCount = vehicleIssues.filter((i) => i.status === 'open').length

  const create = async (values: any) => {
    if (writeBlocked || !submitLock.tryAcquire()) return
    setSubmitting(true)
    let iid = createdIssueId
    try {
      if (!iid) {
        // NAS 的普通 HTTP 页面可能没有 randomUUID；兼容现有离线填报的本地键格式。
        reportKey.current ??= globalThis.crypto?.randomUUID?.() ?? `local-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
        const r = await api.post(`/projects/${projectId}/issues`, { ...values, client_uuid: reportKey.current })
        iid = r.data.id
        setCreatedIssueId(iid)
      }
      // 创建成功后只重试尚未上传的文件，避免再次创建问题或重传已成功的附件。
      let queued = 0
      for (const f of fileList) {
        try { await uploadProjectFile(projectId, f as File, 'issue', iid!) }
        catch (failure) { if (!isUploadQueued(failure)) throw failure; queued++ }
        setFileList((pending) => pending.filter((item) => item !== f))
      }
      if (queued) message.info(`问题已上报，${queued} 个附件已保存到上传队列，核验完成后才会关联。`)
      else message.success(fileList.length ? '问题已上报，附件已保存' : '问题已上报')
      setCreatedIssueId(null)
      reportKey.current = null
      setModalOpen(false)
      form.resetFields()
      await load()
    } catch (e: any) {
      message.error(iid ? '问题已保存，部分附件上传失败。请重试剩余附件。' : e.response?.data?.detail ?? '提交失败')
      if (iid) await load()
    } finally {
      setSubmitting(false)
      submitLock.release()
    }
  }

  const updateStatus = async (issue: Issue, status: string, resolution?: string) => {
    if (writeBlocked || !statusLock.tryAcquire()) return false
    setStatusSaving(true)
    try {
      await api.put(`/issues/${issue.id}`, { status, resolution, version: issue.version })
      if (currentProject.current !== projectId) return false
      message.success('状态已更新')
      await load()
      return true
    } catch (e: any) {
      message.error(e.response?.data?.detail ?? '更新失败，已保留填写内容')
      return false
    } finally {
      setStatusSaving(false)
      statusLock.release()
    }
  }

  const openResolution = (issue: Issue) => {
    setResolutionAction('resolved'); setEditing(issue)
    resolveForm.setFieldsValue({ resolution: issue.resolution }); setDetailIssue(null)
  }
  // One next step per row: start → resolve → confirm close. Everything else is in the detail drawer.
  const nextAction = (issue: Issue) => {
    if (detailIssue || editing) return null
    if (canHandle(issue) && issue.status === 'open') return <Button size="small" loading={statusSaving} onClick={() => updateStatus(issue, 'processing')}>开始处理</Button>
    if (canHandle(issue) && issue.status === 'processing') return <Button size="small" type="primary" disabled={statusSaving} onClick={() => openResolution(issue)}>解决</Button>
    if (canClose(issue) && issue.status === 'resolved') return <Button size="small" type="primary" loading={statusSaving} onClick={() => updateStatus(issue, 'closed')}>确认关闭</Button>
    return null
  }

  const queue: Array<{id:string;source:'project';item:Issue} | {id:string;source:'vehicle';item:VehicleIssue}> = [
    ...filtered.map(item=>({id:`project:${item.id}`,source:'project' as const,item})),
    ...filteredVehicles.map(item=>({id:`vehicle:${item.id}`,source:'vehicle' as const,item})),
  ]
  const overdue = (issue: Issue) => !!issue.sla_due_at && !['closed', 'cancelled', 'resolved'].includes(issue.status) && parseDateTime(issue.sla_due_at).isBefore(new Date())
  const shortTime = (value?: string | null) => value ? parseDateTime(value).format('MM-DD HH:mm') : ''
  const issueRow = (row: typeof queue[number]) => {
    if (row.source === 'vehicle') {
      const item = row.item
      return <li key={row.id} className={`issue-row${item.status === 'resolved' ? ' is-closed' : ''}`}>
        <span className="issue-row-severity is-vehicle" aria-hidden />
        <div className="issue-row-main">
          <button type="button" className="issue-row-title" onClick={() => setVehicleDetail(item)}>{item.title}</button>
          <span className="issue-row-meta"><span>{item.asset_code} · {item.fault_part || item.description || '未填写故障部位'}</span><span>{item.event_date}{item.handler ? ` · 处理人 ${item.handler}` : ''}</span></span>
        </div>
        <span className="issue-row-tags"><Tag>车辆</Tag><Tag color={item.status === 'resolved' ? 'green' : 'red'}>{item.status === 'resolved' ? '已关闭' : '未解决'}</Tag></span>
        <span className="issue-row-action"><Button size="small" onClick={() => setVehicleDetail(item)}>查看</Button></span>
      </li>
    }
    const issue = row.item
    const type = TYPE_LABEL[issue.issue_type] && issue.issue_type !== 'other' ? TYPE_LABEL[issue.issue_type] : ''
    const summary = extraSummary(issue.extra) || issue.task_name || issue.description
    return <li key={row.id} className={`issue-row sev-${issue.severity}${['closed', 'cancelled'].includes(issue.status) ? ' is-closed' : ''}`}>
      <span className="issue-row-severity" title={`严重程度：${SEVERITY_MAP[issue.severity]?.label}`} aria-hidden />
      <div className="issue-row-main">
        <button type="button" className="issue-row-title" onClick={() => setDetailIssue(issue)}>{issue.title}</button>
        <span className="issue-row-meta">{type && <span>{type}</span>}{summary && <span className="issue-row-summary">{summary}</span>}<span>{issue.reporter_name} 上报 {shortTime(issue.created_at)}</span></span>
      </div>
      <span className="issue-row-tags">
        {issue.nature && issue.nature !== 'normal' && <Tag color={issue.nature === 'accident' ? 'red' : issue.nature === 'quality' ? 'orange' : undefined}>{ISSUE_NATURES.find(item => item.value === issue.nature)?.label}</Tag>}
        {['critical', 'high'].includes(issue.severity) && <Tag color={SEVERITY_MAP[issue.severity]?.color}>{SEVERITY_MAP[issue.severity]?.label}</Tag>}
        <Tag color={ISSUE_STATUS_MAP[issue.status]?.color}>{ISSUE_STATUS_MAP[issue.status]?.label}</Tag>
        {overdue(issue) && <Tag color="red">超过 {issue.sla_hours} 小时</Tag>}
      </span>
      <span className="issue-row-action">{nextAction(issue)}</span>
    </li>
  }
  const activeCount = openProjectCount + openVehicleCount
  const closingCount = issues.filter(i => i.status === 'resolved').length
  return (
    <div className="field-work-page">
      <WorkPageHeader title="现场问题" description="上报 → 开始处理 → 解决 → 确认关闭。不用指派，谁处理谁点“开始处理”。每行右侧是下一步；点标题看详情、导出或作废。车辆问题在车辆记录里处理。"
        primary={!writeBlocked && <Button type="primary" aria-label="上报问题" icon={<PlusOutlined />} onClick={()=>setModalOpen(true)}>上报问题</Button>}
        meta={`${activeCount} 项待解决 · ${closingCount} 项待关闭`}
        tools={<Space wrap><RefreshAction onClick={load} loading={loading} />{!writeBlocked && <Popover trigger="click" content={<Upload disabled={importing} showUploadList={false} accept=".xlsx" beforeUpload={file=>importQualityForm(file as File)}><Button loading={importing} icon={<UploadOutlined />}>导入质量问题反馈单</Button></Upload>}><IconAction bordered label="导入问题" icon={<ImportOutlined />} /></Popover>}</Space>} />
      {loadError && <Alert type="error" showIcon message="问题数据未能完整加载，请重试。" action={<Button onClick={load} loading={loading}>重新加载</Button>} />}
      <div className="issue-toolbar">
        <Segmented aria-label="问题查看范围" value={statusFilter} onChange={value=>setStatusFilter(String(value))} options={[{value:'active',label:'待解决'},{value:'resolved',label:'待关闭'},{value:'all',label:'全部'}]} />
        <Input.Search aria-label="搜索问题" placeholder="搜索问题、处理人或车辆" allowClear value={search} onChange={event=>setSearch(event.target.value)} className="issue-search" />
      </div>
      {loading && !queue.length ? <Empty description="正在读取问题…" /> : queue.length ? <ul className="issue-list" aria-label="问题列表">{queue.map(issueRow)}</ul>
        : <Empty description={statusFilter === 'active' ? '没有待解决的问题' : '没有符合条件的问题'}>{statusFilter!=='all' && <Button onClick={()=>setStatusFilter('all')}>查看全部问题</Button>}</Empty>}

      <Modal className="field-work-modal" title="上报问题" open={modalOpen} confirmLoading={submitting}
        okText={createdIssueId ? '重试剩余附件' : '提交问题'}
        closable={!submitting} maskClosable={!submitting} cancelButtonProps={{ disabled: submitting }}
        onCancel={() => setModalOpen(false)} onOk={() => form.submit()}>
        {createdIssueId && <Alert type="warning" showIcon style={{ marginBottom: 12 }} message="问题已保存，请重试上传剩余附件。" />}
        <fieldset disabled={!!createdIssueId || submitting} style={{ border: 0, padding: 0, margin: 0 }}>
        <Form form={form} layout="vertical" onFinish={create} disabled={!!createdIssueId || submitting}>
          <Form.Item name="title" label="问题标题" rules={[{ required: true, whitespace: true, message: '请输入问题标题' }, { max: 300, message: '标题最多 300 字' }]}>
            <Input placeholder="简述问题" />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(prev, cur) => prev.issue_type !== cur.issue_type}>
            {({ getFieldValue }) => <Form.Item name="description" label="问题描述">
              <Input.TextArea rows={3} placeholder={ISSUE_TYPE_HINTS[getFieldValue('issue_type') || 'hardware'] ?? '现象、影响、发生时间'} />
            </Form.Item>}
          </Form.Item>
          <div className="issue-form-pair">
            <Form.Item name="issue_type" label="问题类型" initialValue="hardware" rules={[{ required: true }]}>
              <Select options={ISSUE_TYPES} />
            </Form.Item>
            <Form.Item name="severity" label="严重程度" initialValue="medium">
              <Select
                options={[
                  { label: '严重（影响整体交付）', value: 'critical' },
                  { label: '高（影响主要功能）', value: 'high' },
                  { label: '中（影响局部功能）', value: 'medium' },
                  { label: '低（不影响使用）', value: 'low' },
                ]}
              />
            </Form.Item>
          </div>
          <Form.Item label="附件（照片/截图/文件，支持续传）">
            <Upload
              multiple
              fileList={fileList}
              beforeUpload={(f: any) => { setFileList((prev) => [...prev, f]); return false }}
              onRemove={(f: any) => setFileList((prev) => prev.filter((x) => x !== f))}
            >
              <Button icon={<PaperClipOutlined />}>选择文件</Button>
            </Upload>
          </Form.Item>
          <details className="issue-form-more">
            <summary>更多信息（可选）</summary>
            <Form.Item name="nature" label="问题性质" initialValue="normal" rules={[{required:true}]} extra="选“事故”或“质量问题”会自动建立需要提交的报告。">
              <Select options={ISSUE_NATURES} />
            </Form.Item>
            <Form.Item noStyle shouldUpdate={(prev, cur) => prev.issue_type !== cur.issue_type}>
              {({ getFieldValue }) => (ISSUE_TYPE_FIELDS[getFieldValue('issue_type') || 'hardware'] ?? []).map((f) => (
                <Form.Item key={f.key} name={['extra', f.key]} preserve={false} label={f.label} style={{ marginBottom: 12 }}>
                  {f.type === 'select'
                    ? <Select options={f.options} placeholder={f.placeholder} allowClear />
                    : <Input placeholder={f.placeholder} />}
                </Form.Item>
              ))}
            </Form.Item>
            <Form.Item name="task_id" label="关联任务">
              <Select
                allowClear
                showSearch
                optionFilterProp="label"
                placeholder="选择任务，便于定位问题上下文"
                options={tasks.map((t) => ({ label: `${t.phase} / ${t.label}`, value: t.id }))}
              />
            </Form.Item>
          </details>
        </Form>
        </fieldset>
      </Modal>

      <Drawer className="field-work-modal" title={vehicleDetail ? `${vehicleDetail.asset_code} · ${vehicleDetail.title}` : ''} open={!!vehicleDetail} onClose={() => setVehicleDetail(null)} width={isMobile ? '100%' : 520}>
        {vehicleDetail && <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Space wrap><Tag color="blue">车辆问题</Tag><Tag color={vehicleDetail.status === 'resolved' ? 'green' : 'red'}>{vehicleDetail.status === 'resolved' ? '已解决' : '未解决'}</Tag><Typography.Text type="secondary">{vehicleDetail.event_date}</Typography.Text></Space>
          {vehicleDetail.description && <Typography.Paragraph><b>故障现象：</b>{vehicleDetail.description}</Typography.Paragraph>}
          {vehicleDetail.fault_part && <div><b>故障部位：</b>{vehicleDetail.fault_part}</div>}
          {vehicleDetail.cause && <div><b>原因判断：</b>{vehicleDetail.cause}</div>}
          {vehicleDetail.action_taken && <div><b>处理过程：</b>{vehicleDetail.action_taken}</div>}
          {!!vehicleDetail.replaced_parts?.length && <div><b>更换配件：</b>{vehicleDetail.replaced_parts.map((part) => `${part.name || '配件'}${part.model ? `(${part.model})` : ''} x${part.quantity || 1}`).join('；')}</div>}
          {vehicleDetail.verification && <div><b>处理验证：</b>{vehicleDetail.verification}</div>}
          <Space wrap>
            <Button type="primary" onClick={() => window.location.assign(`/pm/projects/${projectId}/vehicles?unit=${vehicleDetail.vehicle_unit_id}`)}>进入单车履历处理</Button>
            <Button icon={<FileExcelOutlined />} onClick={() => void downloadQualityForm(vehicleDetail)}>导出质量问题反馈单</Button>
          </Space>
        </Space>}
      </Drawer>

      {/* 问题详情 Drawer：全字段 + 附件 + 信息 + 底部操作（列表只留摘要） */}
      <Drawer className="field-work-modal"
        title={detailIssue ? (
          <Space size={8} wrap>
            <span style={{ wordBreak: 'break-word' }}>{detailIssue.title}</span>
            <Tag color={SEVERITY_MAP[detailIssue.severity]?.color} style={{ fontSize: 11 }}>
              {SEVERITY_MAP[detailIssue.severity]?.label}
            </Tag>
            <Tag color={ISSUE_STATUS_MAP[detailIssue.status]?.color} style={{ fontSize: 11 }}>
              {ISSUE_STATUS_MAP[detailIssue.status]?.label}
            </Tag>
          </Space>
        ) : ''}
        open={!!detailIssue}
        onClose={() => setDetailIssue(null)}
        width={isMobile ? '100%' : 480}
      >
        {detailIssue && (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Space wrap><Typography.Text>问题性质：</Typography.Text>{canEdit ? <InlineSelect label="问题性质" value={detailIssue.nature || 'normal'} options={ISSUE_NATURES} disabled={statusSaving} onSave={async value=>{
              if(!value || !statusLock.tryAcquire())return
              setStatusSaving(true)
              try {const result=await api.put(`/issues/${detailIssue.id}`,{nature:value,version:detailIssue.version});if(currentProject.current!==projectId)return;setDetailIssue(result.data);await load()}
              catch(error){message.error(errMsg(error))}finally{statusLock.release();setStatusSaving(false)}
            }} /> : <Typography.Text>{ISSUE_NATURES.find(item=>item.value===detailIssue.nature)?.label || '普通'}</Typography.Text>}</Space>
            {detailIssue.sla_due_at && <Typography.Text type="secondary">处理时限 {detailIssue.sla_hours} 小时 · 截止 {formatDateTime(detailIssue.sla_due_at)}{detailIssue.sla_basis==='nature_changed'?'（从本次性质变更登记时刻起）':'（从上报时刻起）'}；仅关闭或作废算闭环。</Typography.Text>}
            {detailIssue.sla_warning && <Alert type="info" message={detailIssue.sla_warning} />}
            {detailIssue.trigger_event_id && <Button href={`/pm/projects/${projectId}/documents?trigger=${detailIssue.trigger_event_id}`}>查看本事件资料</Button>}
            {detailIssue.nature==='quality' && <Typography.Paragraph type="secondary">导出的质量问题反馈单可在本事件资料中作为6.8.1附件上传。</Typography.Paragraph>}
            <Space direction="vertical" size={2} style={{ width: '100%' }}>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {({ hardware: '硬件', software: '软件', environment: '环境', process: '流程', safety: '安全', other: '其他' } as Record<string, string>)[detailIssue.issue_type] ?? '其他'}
                {detailIssue.task_name ? ` · 关联任务：${detailIssue.task_name}` : ''}
              </Typography.Text>
              {extraSummary(detailIssue.extra) && (
                <Typography.Text style={{ fontSize: 12, color: 'var(--agv-text-secondary)' }}>{extraSummary(detailIssue.extra)}</Typography.Text>
              )}
              {detailIssue.description && (
                <Typography.Paragraph type="secondary" style={{ fontSize: 13, margin: '4px 0 0' }}>
                  {detailIssue.description}
                </Typography.Paragraph>
              )}
            </Space>

            {(issueAtts[detailIssue.id] ?? []).length > 0 && (
              <>
                <Divider style={{ margin: '4px 0' }} />
                <Typography.Text strong style={{ fontSize: 13 }}>附件</Typography.Text>
                <Space direction="vertical" size={4} style={{ width: '100%' }}>
                  {(issueAtts[detailIssue.id] ?? []).map((a) => (
                    <Button key={a.id} type="link" size="small" style={{ padding: 0, justifyContent: 'flex-start', fontSize: 12 }}
                      icon={<DownloadOutlined />} onClick={() => download(a.id, a.filename)}>
                      {a.filename}
                    </Button>
                  ))}
                </Space>
              </>
            )}

            <Divider style={{ margin: '4px 0' }} />
            <Typography.Text strong style={{ fontSize: 13 }}>处理时间线</Typography.Text>
            <Space direction="vertical" size={10} style={{ width: '100%', marginTop: 8 }}>
              {[
                { icon: <FileTextOutlined />, label: '上报', desc: `${detailIssue.reporter_name} · ${detailIssue.created_at ? parseDateTime(detailIssue.created_at).format('MM-DD HH:mm') : ''}`, done: true },
                { icon: <UserSwitchOutlined />, label: '开始处理', desc: detailIssue.status === 'open' ? '还没人开始' : '已开始处理', done: detailIssue.status !== 'open' },
                { icon: <CheckCircleOutlined />, label: '解决', desc: detailIssue.resolved_at ? parseDateTime(detailIssue.resolved_at).format('MM-DD HH:mm') : '待解决', done: !!detailIssue.resolved_at },
                { icon: <StopOutlined />, label: '关闭/作废', desc: detailIssue.status === 'cancelled' ? '已作废' : detailIssue.status === 'closed' ? '已关闭' : '待关闭', done: detailIssue.status === 'cancelled' || detailIssue.status === 'closed' },
              ].map((s) => (
                <div key={s.label} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, fontSize: 12 }}>
                  <span style={{ fontSize: 14, opacity: s.done ? 1 : 0.35 }}>{s.icon}</span>
                  <div>
                    <Typography.Text strong style={{ fontSize: 12, opacity: s.done ? 1 : 0.5 }}>{s.label}</Typography.Text>
                    <Typography.Text type="secondary" style={{ fontSize: 11, marginLeft: 8 }}>{s.desc}</Typography.Text>
                  </div>
                </div>
              ))}
            </Space>
            {detailIssue.resolution && (
              <Typography.Paragraph type="secondary" style={{ fontSize: 12, margin: '4px 0 0' }}>
                解决方案/说明：{detailIssue.resolution}
              </Typography.Paragraph>
            )}
          </Space>
        )}
        {detailIssue && (
          <div style={{ position: 'sticky', bottom: -24, marginTop: 24, padding: '12px 0', borderTop: '1px solid var(--agv-border-soft)', background: 'var(--agv-bg-container)', display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {canHandle(detailIssue) && detailIssue.status === 'open' && (
              <Button size="small" loading={statusSaving} onClick={async () => { if (await updateStatus(detailIssue, 'processing')) setDetailIssue(null) }}>开始处理</Button>
            )}
            {canHandle(detailIssue) && (detailIssue.status === 'open' || detailIssue.status === 'processing') && (
              <Button
                size="small"
                type="primary"
                onClick={() => {
                  setResolutionAction('resolved')
                  setEditing(detailIssue)
                  resolveForm.setFieldsValue({ resolution: detailIssue.resolution })
                  setDetailIssue(null)
                }}
              >
                解决
              </Button>
            )}
            {!writeBlocked && ['resolved', 'closed', 'cancelled'].includes(detailIssue.status)
              && (
              <Button size="small" loading={statusSaving} onClick={async () => {
                if (!statusLock.tryAcquire()) return
                setStatusSaving(true)
                try {
                  await api.post(`/issues/${detailIssue.id}/reopen`)
                  message.success('问题已重新打开'); setDetailIssue(null); await load()
                } catch (error: any) { message.error(error.response?.data?.detail ?? '重新打开失败') }
                finally { setStatusSaving(false); statusLock.release() }
              }}>重新打开</Button>
            )}
            {canClose(detailIssue) && detailIssue.status === 'resolved' && (
              <Button size="small" type="primary" loading={statusSaving} onClick={async () => { if (await updateStatus(detailIssue, 'closed')) setDetailIssue(null) }}>关闭</Button>
            )}
            <Button size="small" icon={<FileExcelOutlined />} onClick={()=>downloadQualityForm(detailIssue)}>导出单据</Button>
            {canClose(detailIssue) && ['open', 'processing'].includes(detailIssue.status) && (
              <Button size="small" danger icon={<DeleteOutlined />} onClick={() => {
                setResolutionAction('cancelled')
                setEditing(detailIssue)
                resolveForm.resetFields()
                setDetailIssue(null)
              }}>作废</Button>
            )}
          </div>
        )}
      </Drawer>

      <Modal className="field-work-modal"
        title={`${resolutionAction === 'resolved' ? '解决' : '作废'}问题：${editing?.title ?? ''}`}
        open={!!editing}
        okText={resolutionAction === 'resolved' ? '提交解决方案' : '确认作废'}
        cancelText="返回"
        onCancel={() => { if (!statusSaving) setEditing(null) }}
        confirmLoading={statusSaving}
        closable={!statusSaving}
        maskClosable={false}
        cancelButtonProps={{ disabled: statusSaving }}
        onOk={() => {
          resolveForm.validateFields().then(async (v) => {
            if (editing && await updateStatus(editing, resolutionAction, v.resolution.trim())) setEditing(null)
          }).catch(() => {})
        }}
      >
        <Form form={resolveForm} layout="vertical" disabled={statusSaving}>
          <Form.Item name="resolution" label={resolutionAction === 'resolved' ? '解决方案' : '作废原因'} rules={[{ required: true, whitespace: true, message: '请填写具体说明' }]}>
            <Input.TextArea rows={3} placeholder={resolutionAction === 'resolved' ? '记录根因与处理措施' : '说明为何作废，例如重复上报时注明原问题，便于后续追溯'} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
