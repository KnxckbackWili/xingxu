import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import {
  Table, Tag, Button, Modal, Form, Input, Select, Upload, message, Space, Typography, Alert, Drawer, Divider, Empty, Segmented, Popover,
} from 'antd'
import {
  CheckCircleOutlined, DeleteOutlined, DownloadOutlined, FileExcelOutlined, FileTextOutlined, PaperClipOutlined,
  EyeOutlined, ImportOutlined, PlayCircleOutlined, PlusOutlined, StopOutlined, UploadOutlined, UserSwitchOutlined,
} from '@ant-design/icons'
import { parseDateTime,formatDateTime } from '../../../utils/date'
import { api, errMsg } from '../../../api/client'
import { projectDocumentsApi, uploadProjectFile, downloadProjectFile } from '../../../api/projectDocuments'
import { isUploadQueued } from '../../../uploads/types'
import { useAuth } from '../../../stores/auth'
import { useSubmitLock } from '../../../hooks/useSubmitLock'
import { useMediaQuery } from '../../../hooks/useMediaQuery'
import { useProjectWriteBlocked } from '../../../hooks/useProjectCapability'
import { MEDIA_QUERY } from '../../../constants/breakpoints'
import { ISSUE_TYPES, ISSUE_TYPE_HINTS, ISSUE_TYPE_FIELDS, ISSUE_STATUS_MAP, ISSUE_NATURES, extraSummary } from '../../../constants/issues'
import InlineSelect from '../../../components/InlineSelect'
import ContextTip from '../../../components/ContextTip'
import { WorkPageHeader, WorkSection } from '../../../components/WorkPage'
import './FieldWorkPages.css'
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
  assignee_id: string | null
  assignee_name: string
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
  const [sourceFilter, setSourceFilter] = useState<'all' | 'project' | 'vehicle'>('all')
  const [vehicleDetail, setVehicleDetail] = useState<VehicleIssue | null>(null)
  const [users, setUsers] = useState<any[]>([])
  const [usersLoading, setUsersLoading] = useState(false)
  const [usersError, setUsersError] = useState(false)
  const peopleRequest = useRef(0)
  const loadRequest = useRef(0)
  const currentProject = useRef(projectId)
  currentProject.current = projectId
  const [assigning, setAssigning] = useState<Issue | null>(null)
  const [tasks, setTasks] = useState<{ id: string; label: string; phase: string }[]>([])
  const [issueAtts, setIssueAtts] = useState<Record<string, any[]>>({})
  const [fileList, setFileList] = useState<any[]>([])
  const [typeFilter, setTypeFilter] = useState<string>('')
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
  const { user } = useAuth()
  const contextWriteBlocked = useProjectWriteBlocked()
  const writeBlocked = archived || contextWriteBlocked
  const canEdit = canManage && !writeBlocked
  const canClose = (issue: Issue) => !writeBlocked && user?.role !== 'readonly' && user?.permission_overrides?.['project.manage_issues'] !== false && issue.can_close === true
  const canHandle = (issue: Issue) => !writeBlocked && (canEdit || issue.assignee_id === user?.id)
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

  const loadUsers = async () => {
    const request = ++peopleRequest.current
    setUsersLoading(true); setUsersError(false)
    try {
      const { data } = await api.get(`/projects/${projectId}/issue-assignees`)
      if (request === peopleRequest.current && currentProject.current === projectId) setUsers(data)
    } catch {
      if (request === peopleRequest.current && currentProject.current === projectId) { setUsers([]); setUsersError(true) }
    } finally { if (request === peopleRequest.current && currentProject.current === projectId) setUsersLoading(false) }
  }

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

  const doAssign = async (uid: string | undefined) => {
    if (!assigning || !canEdit || usersLoading || usersError || !statusLock.tryAcquire()) return
    setStatusSaving(true)
    try {
      await api.put(`/issues/${assigning.id}`, { assignee_id: uid || null, version: assigning.version })
      if (currentProject.current !== projectId) return
      message.success(uid ? '已指派处理人' : '已取消指派')
      setAssigning(null); setDetailIssue(null)
      await load()
    } catch (e: any) {
      if (currentProject.current !== projectId) return
      message.error(e.response?.data?.detail ?? '指派失败')
      if (e.response?.status === 409) {
        const fresh = await load()
        setAssigning(fresh?.find(issue => issue.id === assigning.id) ?? null)
      }
    } finally { statusLock.release(); setStatusSaving(false) }
  }

  const download = async (id: string, name: string) => {
    try { await downloadProjectFile(id, name) } catch (failure) { message.error(errMsg(failure)) }
  }

  const downloadQualityForm = async (issue: Issue) => {
    try {
      const r = await api.get(`/projects/${projectId}/issues/${issue.id}/export/quality-form`, { responseType: 'blob' })
      const url = URL.createObjectURL(r.data)
      const a = document.createElement('a'); a.href = url; a.download = `质量问题反馈单-${issue.title.slice(0, 20)}.xlsx`; a.click()
      URL.revokeObjectURL(url)
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
    void loadUsers()
    let active = true
    // 任务列表（上报表单的「关联任务」选择）
    api.get(`/projects/${projectId}/tree`).then((r) => {
      if (!active) return
      const flat: { id: string; label: string; phase: string }[] = []
      for (const ph of r.data ?? []) {
        for (const m of ph.modules ?? []) {
          for (const t of m.tasks ?? []) flat.push({ id: t.id, label: t.name, phase: ph.name })
        }
      }
      setTasks(flat)
    }).catch(() => {})
    return () => { active = false; peopleRequest.current++; loadRequest.current++ }
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
  const filtered = issues.filter((i) => (!typeFilter || i.issue_type === typeFilter)
    && matches(i.title, i.description, i.status, i.assignee_name))
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

  const quickAssign = async (issue: Issue, assigneeId: string | undefined) => {
    if (!canEdit || usersLoading || usersError || !statusLock.tryAcquire()) throw new Error('当前暂不能保存，请稍后重试')
    setStatusSaving(true)
    try {
      const response = await api.put(`/issues/${issue.id}`, { assignee_id: assigneeId || null, version: issue.version })
      if (currentProject.current !== projectId) return
      const selected = users.find((person) => person.id === assigneeId)
      setIssues((current) => current.map((item) => item.id === issue.id ? { ...item, assignee_id: assigneeId || null,
        assignee_name: selected?.display_name || '', ...response.data } : item))
      message.success(assigneeId ? '已指派处理人' : '已取消指派')
      await load()
    } catch (error: any) {
      if (currentProject.current === projectId && error.response?.status === 409) await load()
      throw error
    } finally { statusLock.release(); setStatusSaving(false) }
  }

  const openResolution = (issue: Issue) => {
    setResolutionAction('resolved'); setEditing(issue)
    resolveForm.setFieldsValue({ resolution: issue.resolution }); setDetailIssue(null)
  }
  const quickActions = (issue: Issue) => {
    if (detailIssue || assigning || editing) return null
    return <span className="row-icon-actions" onClick={(event) => event.stopPropagation()}>
    {canHandle(issue) && issue.status === 'open' && <IconAction label="开始处理" icon={<PlayCircleOutlined />} loading={statusSaving}
      onClick={() => updateStatus(issue, 'processing')} />}
    {canHandle(issue) && ['open', 'processing'].includes(issue.status) && <IconAction label="解决" icon={<CheckCircleOutlined />} disabled={statusSaving}
      onClick={() => openResolution(issue)} />}
    {canClose(issue) && issue.status === 'resolved' && <IconAction label="关闭" icon={<StopOutlined />} loading={statusSaving}
      onClick={() => updateStatus(issue, 'closed')} />}
    </span>
  }

  const queue: Array<{id:string;source:'project';item:Issue} | {id:string;source:'vehicle';item:VehicleIssue}> = [
    ...(sourceFilter==='vehicle' ? [] : filtered.map(item=>({id:`project:${item.id}`,source:'project' as const,item}))),
    ...(sourceFilter==='project' ? [] : filteredVehicles.map(item=>({id:`vehicle:${item.id}`,source:'vehicle' as const,item}))),
  ]
  const issueTags = (row: typeof queue[number]) => {
    if(row.source==='vehicle') return <Space wrap><Tag>车辆</Tag><Tag color={row.item.status==='resolved'?'green':'red'}>{row.item.status==='resolved'?'已关闭':'未解决'}</Tag></Space>
    const issue=row.item
    const overdue=issue.sla_due_at && !['closed','cancelled'].includes(issue.status) && parseDateTime(issue.sla_due_at).isBefore(new Date())
    return <Space wrap>{TYPE_LABEL[issue.issue_type] && issue.issue_type !== 'other' && <Tag>{TYPE_LABEL[issue.issue_type]}</Tag>}{issue.nature && issue.nature !== 'normal' && <Tag color={issue.nature==='accident'?'red':issue.nature==='quality'?'orange':undefined}>{ISSUE_NATURES.find(item=>item.value===issue.nature)?.label}</Tag>}<Tag color={SEVERITY_MAP[issue.severity]?.color}>{SEVERITY_MAP[issue.severity]?.label}</Tag><Tag color={ISSUE_STATUS_MAP[issue.status]?.color}>{ISSUE_STATUS_MAP[issue.status]?.label}</Tag>{overdue && <Tag color="red">超过 {issue.sla_hours} 小时处理时限</Tag>}</Space>
  }

  const issueOwner = (row:typeof queue[number]) => row.source==='vehicle' ? row.item.handler || row.item.reporter_name || '未填写'
    : canEdit ? <InlineSelect label={`${row.item.title}处理人`} value={row.item.assignee_id} placeholder="未指派"
        options={users.map(person=>({value:person.id,label:person.display_name || person.username}))}
        disabled={statusSaving || usersLoading || usersError} allowClear onSave={value=>quickAssign(row.item,value)} /> : row.item.assignee_name || '未指派'
  const issueActions = (row:typeof queue[number]) => row.source==='vehicle'
    ? <IconAction label="查看车辆问题" icon={<EyeOutlined />} onClick={()=>setVehicleDetail(row.item)} />
    : <span className="row-icon-actions">{quickActions(row.item)}<IconAction label="详情" icon={<EyeOutlined />} onClick={()=>setDetailIssue(row.item)} /></span>
  const issueDescription = (row:typeof queue[number]) => row.source==='vehicle'
    ? `${row.item.asset_code} · ${row.item.fault_part || row.item.description || '未填写故障部位'}`
    : extraSummary(row.item.extra) || row.item.task_name || row.item.description
  return (
    <div className="field-work-page">
      <WorkPageHeader title="现场问题" description="先处理未解决的问题，填写结果后再确认关闭。车辆问题在车辆记录中处理。"
        primary={!writeBlocked && <Button type="primary" aria-label="上报问题" icon={<PlusOutlined />} onClick={()=>setModalOpen(true)}>上报问题</Button>}
        tools={<Space wrap><RefreshAction onClick={load} loading={loading} /><ContextTip id="issue-quick-actions" title="问题快捷处理">有处理权限时，可直接指派和开始处理；解决时填写方案，再由项目经理或报告人确认关闭。</ContextTip>{!writeBlocked && <Popover trigger="click" content={<Upload disabled={importing} showUploadList={false} accept=".xlsx" beforeUpload={file=>importQualityForm(file as File)}><Button loading={importing} icon={<UploadOutlined />}>导入质量问题反馈单</Button></Upload>}><IconAction bordered label="导入问题" icon={<ImportOutlined />} /></Popover>}</Space>}
        meta={`${openProjectCount + openVehicleCount} 项未解决 · ${issues.filter(i=>i.status==='resolved').length} 项待关闭`} />
      {loadError && <Alert type="error" showIcon message="问题数据未能完整加载，请重试。" action={<Button onClick={load} loading={loading}>重新加载</Button>} />}
      <WorkSection filters={<>
        <Segmented aria-label="问题查看范围" value={statusFilter} onChange={value=>setStatusFilter(String(value))} options={[{value:'active',label:'待解决'},{value:'resolved',label:'待关闭'},{value:'all',label:'全部'}]} />
        <Input.Search aria-label="搜索问题" placeholder="搜索问题、处理人或车辆" allowClear value={search} onChange={event=>setSearch(event.target.value)} />
        <Popover trigger="click" placement="bottomRight" content={<div className="field-secondary-actions">
          <Select aria-label="筛选问题来源" value={sourceFilter} onChange={setSourceFilter} options={[{value:'all',label:'所有来源'},{value:'project',label:'项目问题'},{value:'vehicle',label:'车辆问题'}]} />
          <Select aria-label="筛选问题类型" value={typeFilter || undefined} allowClear placeholder="所有类型" disabled={sourceFilter==='vehicle'} onChange={value=>setTypeFilter(value || '')} options={ISSUE_TYPES} />
          <Select aria-label="筛选问题状态" value={statusFilter} onChange={setStatusFilter} options={[{value:'all',label:'全部状态'},{value:'active',label:'待解决'},...Object.entries(ISSUE_STATUS_MAP).map(([value,entry])=>({value,label:entry.label}))]} />
          <Button onClick={()=>{setSourceFilter('all');setTypeFilter('');setStatusFilter('active');setSearch('')}}>重置筛选</Button>
        </div>}><Button>更多筛选{sourceFilter!=='all' || typeFilter ? '（已设置）' : ''}</Button></Popover>
        <span className="field-result-count">{queue.length} 项</span>
      </>}>
        {isMobile ? <div className="field-card-list">{queue.map(row=><article className="field-record-card" key={row.id}>
          <h3><button className="task-name-link" onClick={()=>row.source==='vehicle'?setVehicleDetail(row.item):setDetailIssue(row.item)}>{row.item.title}</button></h3>
          {issueTags(row)}<p className="field-wrap">{issueDescription(row)}</p>
          <div className="field-record-meta"><span>处理人：</span>{issueOwner(row)}</div><div className="field-record-actions">{issueActions(row)}</div>
        </article>)}</div> : <Table rowKey="id" size="small" dataSource={queue} scroll={{ x: 780 }} loading={loading} pagination={{pageSize:20}} columns={[
          {title:'问题',render:(_:any,row:typeof queue[number])=><div><button className="task-name-link" onClick={()=>row.source==='vehicle'?setVehicleDetail(row.item):setDetailIssue(row.item)}>{row.item.title}</button><span className="field-subline field-wrap">{issueDescription(row)}</span></div>},
          {title:'状态与类型',render:(_:any,row:typeof queue[number])=>issueTags(row)},
          {title:'处理人',render:(_:any,row:typeof queue[number])=>issueOwner(row)},
          {title:'操作',render:(_:any,row:typeof queue[number])=>issueActions(row)},
        ]} locale={{emptyText:'没有符合条件的问题'}} />}
        {!queue.length && isMobile && <Empty description="没有符合条件的问题" />}
        {!queue.length && statusFilter!=='all' && <Button onClick={()=>setStatusFilter('all')}>查看全部问题</Button>}
      </WorkSection>

      <Modal className="field-work-modal" title="上报问题" open={modalOpen} confirmLoading={submitting}
        okText={createdIssueId ? '重试剩余附件' : '确定'}
        closable={!submitting} maskClosable={!submitting} cancelButtonProps={{ disabled: submitting }}
        onCancel={() => setModalOpen(false)} onOk={() => form.submit()}>
        {createdIssueId && <Alert type="warning" showIcon style={{ marginBottom: 12 }} message="问题已保存，请重试上传剩余附件。" />}
        <fieldset disabled={!!createdIssueId || submitting} style={{ border: 0, padding: 0, margin: 0 }}>
        <Form form={form} layout="vertical" onFinish={create} disabled={!!createdIssueId || submitting}>
          <Form.Item name="title" label="问题标题" rules={[{ required: true, whitespace: true, message: '请输入问题标题' }, { max: 300, message: '标题最多 300 字' }]}>
            <Input placeholder="简述问题" />
          </Form.Item>
          <Form.Item name="description" label="问题描述">
            <Input.TextArea rows={3} placeholder="详细描述现象、影响等" />
          </Form.Item>
          <Form.Item name="issue_type" label="问题类型" initialValue="hardware" rules={[{ required: true }]}>
            <Select options={ISSUE_TYPES} />
          </Form.Item>
          <Form.Item name="nature" label="问题性质" initialValue="normal" rules={[{required:true}]} extra="事故自动建立事故报告；质量问题建立反馈单和可选返厂申请。标准资料要求24小时内提交，问题处理时限按服务端配置。">
            <Select options={ISSUE_NATURES} />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(prev, cur) => prev.issue_type !== cur.issue_type}>
            {({ getFieldValue }) => {
              const t = getFieldValue('issue_type') || 'hardware'
              const fields = ISSUE_TYPE_FIELDS[t] ?? []
              return (
                <>
                  <Alert
                    type="info"
                    showIcon
                    style={{ marginBottom: 12 }}
                    message={ISSUE_TYPE_HINTS[t] ?? ISSUE_TYPE_HINTS.other}
                  />
                  {fields.map((f) => (
                    <Form.Item key={f.key} name={['extra', f.key]} preserve={false} label={f.label} style={{ marginBottom: 12 }}>
                      {f.type === 'select'
                        ? <Select options={f.options} placeholder={f.placeholder} allowClear />
                        : <Input placeholder={f.placeholder} />}
                    </Form.Item>
                  ))}
                </>
              )
            }}
          </Form.Item>
          <Form.Item name="task_id" label="关联任务（可选）">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder="选择任务，便于定位问题上下文"
              options={tasks.map((t) => ({ label: `${t.phase} / ${t.label}`, value: t.id }))}
            />
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
        </Form>
        </fieldset>
      </Modal>

      {/* 指派处理人 */}
      <Modal className="field-work-modal"
        title={`指派处理人：${assigning?.title ?? ''}`}
        open={!!assigning}
        onCancel={() => { if (!statusSaving) setAssigning(null) }}
        closable={!statusSaving}
        maskClosable={!statusSaving}
        footer={null}
        width={420}
      >
        {usersError && <Alert type="error" showIcon message="可处理人员加载失败，请重试" action={<Button onClick={loadUsers}>重试</Button>} />}
        <Select
          aria-label="问题处理人"
          loading={usersLoading || statusSaving}
          disabled={usersLoading || usersError || statusSaving}
          style={{ width: '100%' }}
          placeholder="选择处理人（清空则取消指派）"
          allowClear
          value={assigning?.assignee_id ?? undefined}
          onChange={(v) => doAssign(v)}
          options={users.map((u) => ({ label: u.display_name, value: u.id }))}
        />
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
          <Button type="primary" onClick={() => window.location.assign(`/pm/projects/${projectId}/vehicles?unit=${vehicleDetail.vehicle_unit_id}`)}>进入单车履历处理</Button>
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
                { icon: <UserSwitchOutlined />, label: '指派处理', desc: detailIssue.assignee_name ? `${detailIssue.assignee_name} 接手` : '未指派', done: !!detailIssue.assignee_name },
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
              && (canEdit || detailIssue.reporter_id === user?.id || detailIssue.assignee_id === user?.id) && (
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
            {canEdit && (
              <Button size="small" icon={<UserSwitchOutlined />} onClick={() => setAssigning(detailIssue)}>指派</Button>
            )}
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
