import { useEffect, useRef, useState } from 'react'
import { Button, Typography, Tag, Space, Empty, Skeleton, Drawer, Divider, Modal, Form, Input, Select, Alert, message, Segmented, Upload, AutoComplete } from 'antd'
import type { UploadFile } from 'antd'
import { PlusOutlined, UploadOutlined } from '@ant-design/icons'
import { useSearchParams } from 'react-router-dom'
import { formatDate, formatDateTime } from '../../utils/date'
import { api } from '../../api/client'
import { useSubmitLock } from '../../hooks/useSubmitLock'
import { useAuth } from '../../stores/auth'
import { hasSystemPermission } from '../../constants/systemPermissions'
import { ISSUE_STATUS_MAP, ISSUE_TYPES, ISSUE_TYPE_SHORT, ISSUE_NATURES, ISSUE_TYPE_FIELDS, extraSummary } from '../../constants/issues'
import { uploadProjectFile } from '../../api/projectDocuments'
import { isUploadQueued } from '../../uploads/types'
import { WorkPageHeader, WorkSection } from '../../components/WorkPage'
import './WorkerWorkPages.css'
import '../../components/IssueList.css'
import { isProjectWriteBlocked } from '../../constants/status'
import { RefreshAction } from '../../components/IconAction'

interface MyIssue {
  id: string
  title: string
  description: string
  severity: string
  status: string
  reporter_id: string
  version?: number
  project_status?: string
  project_name: string
  created_at: string
  resolution: string
  source?: 'project' | 'vehicle'
  extra?: Record<string, unknown> | null
  asset_code?: string
  nature?:string
  sla_hours?:number
  sla_due_at?:string|null
  sla_warning?:string|null
}

const SEV: Record<string, { label: string; color: string }> = {
  critical: { label: '严重', color: 'red' },
  high: { label: '高', color: 'orange' },
  medium: { label: '中', color: 'gold' },
  low: { label: '低', color: 'blue' },
}

/**
 * 问题：所有账号看到所有项目的问题，不用指派，谁处理谁开始。
 */
export default function WorkerIssuesPage() {
  const [scope,setScope] = useState('active')
  const [search,setSearch] = useState('')
  const [searchParams, setSearchParams] = useSearchParams()
  const focusIssueId = searchParams.get('issue_id') || ''
  const [conflict, setConflict] = useState(false)
  const [handling, setHandling] = useState(false)
  const [resolutionOpen, setResolutionOpen] = useState(false)
  const [resolutionForm] = Form.useForm()
  const handlingLock = useSubmitLock()
  const [reopening, setReopening] = useState(false)
  const reopenLock = useSubmitLock()
  const [issues, setIssues] = useState<MyIssue[]>([])
  const [loading, setLoading] = useState(true)
  const [detail, setDetail] = useState<MyIssue | null>(null)
  const [projects, setProjects] = useState<any[]>([])
  const [reportOpen, setReportOpen] = useState(false)
  const [reportForm] = Form.useForm()
  const { user } = useAuth()
  const canRaiseIssue = hasSystemPermission(user, 'worker.issues')
  // Anyone with issue handling allowed may start or resolve an issue.
  const canHandleIssue = !!user
  const permissions = useRef({ raise: canRaiseIssue, handle: canHandleIssue })
  permissions.current = { raise: canRaiseIssue, handle: canHandleIssue }
  const [loadError, setLoadError] = useState(false)
  const [retry, setRetry] = useState(0)
  const [submitting, setSubmitting] = useState(false)
  const submitLock = useSubmitLock()
  const reportKey = useRef<string | null>(null)
  // 问题建好后只重试剩余附件，不重复建问题（与项目问题页一致）。
  const [createdIssue, setCreatedIssue] = useState<{ id: string; projectId: string } | null>(null)
  const [fileList, setFileList] = useState<UploadFile[]>([])
  const [vehicleOptions, setVehicleOptions] = useState<{ value: string }[]>([])
  const reportProjectId = Form.useWatch('project_id', reportForm)
  useEffect(() => {
    let active = true
    setVehicleOptions([])
    if (!reportOpen || !reportProjectId) return
    api.get(`/projects/${reportProjectId}/vehicle-units`).then(({ data }) => {
      if (!active || !Array.isArray(data)) return
      setVehicleOptions(data.map((unit: any) => ({ value: [unit.fleet_no, unit.asset_code].filter(Boolean).join(' · ') })).filter((option: { value: string }) => option.value))
    }).catch(() => { /* 车辆列表仅作输入建议，读取失败仍可手动填写 */ })
    return () => { active = false }
  }, [reportOpen, reportProjectId])
  const writableProjects = projects.filter(project => !isProjectWriteBlocked(project.status))

  useEffect(() => {
    if (loading || loadError || !focusIssueId) return
    setDetail(issues.find(issue => issue.id === focusIssueId) ?? null)
    setConflict(false)
  }, [issues, loading, loadError, focusIssueId])

  const closeDetail = () => {
    setDetail(null)
    if (focusIssueId) {
      const next = new URLSearchParams(searchParams)
      next.delete('issue_id')
      setSearchParams(next, { replace: true })
    }
  }

  useEffect(() => {
    let active = true
    const load = async () => {
      setLoading(true)
      setLoadError(false)
      try {
        const [r, p] = await Promise.all([
          api.get('/dashboard/issues', { params: { include_closed: true } }),
          api.get('/projects'),
        ])
        if (!active) return
        setIssues(r.data.items ?? [])
        setProjects(p.data ?? [])
      } catch {
        if (active) setLoadError(true)
      } finally {
        if (active) setLoading(false)
      }
    }
    load()
    return () => { active = false }
  }, [user?.id, retry])

  // No assignment: anyone may start or resolve an open issue; whoever starts it becomes its handler.
  const canWork = (issue: MyIssue) => canHandleIssue && issue.source !== 'vehicle' && ['open', 'processing'].includes(issue.status) && !isProjectWriteBlocked(issue.project_status)
  const handleIssue = async (status: 'processing' | 'resolved', resolution?: string, target: MyIssue | null = detail) => {
    if (!permissions.current.handle || !target || conflict || !canWork(target) || !handlingLock.tryAcquire()) return
    setHandling(true)
    try {
      await api.put(`/issues/${target.id}`, { status, ...(resolution ? { resolution } : {}), version: target.version })
      message.success(status === 'resolved' ? '处理结果已提交，请报告人复核' : '已开始处理')
      setResolutionOpen(false); setDetail(null); setRetry(value => value + 1)
    } catch (error: any) { if (error.response?.status === 409) setConflict(true); message.error(error.response?.data?.detail ?? '保存失败，填写内容已保留，请重试') }
    finally { setHandling(false); handlingLock.release() }
  }

  const submitReport = async (values: any) => {
    if (!permissions.current.raise) return
    if (isProjectWriteBlocked(projects.find(project => project.id === values.project_id)?.status)) {
      message.warning('此项目当前只读，不能上报问题')
      return
    }
    if (!submitLock.tryAcquire()) return
    setSubmitting(true)
    reportKey.current ??= globalThis.crypto?.randomUUID?.() ?? `local-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
    let issue = createdIssue?.projectId === values.project_id ? createdIssue : null
    try {
      if (!issue) {
        const extra = Object.fromEntries(Object.entries(values.extra ?? {}).filter(([, value]) => typeof value === 'string' ? value.trim() : value != null))
        const { data } = await api.post(`/projects/${values.project_id}/issues`, {
          client_uuid: reportKey.current,
          title: values.title.trim(),
          description: values.description || '',
          issue_type: values.issue_type,
          nature:values.nature || 'normal',
          severity: values.severity,
          ...(Object.keys(extra).length ? { extra } : {}),
        })
        issue = { id: data.id, projectId: values.project_id }
        setCreatedIssue(issue)
      }
      let queued = 0
      for (const file of fileList) {
        try { await uploadProjectFile(issue.projectId, file as unknown as File, 'issue', issue.id) }
        catch (failure) { if (!isUploadQueued(failure)) throw failure; queued++ }
        setFileList((pending) => pending.filter((item) => item !== file))
      }
      if (queued) message.info(`问题已上报，${queued} 个附件已保存到上传队列，核验完成后才会关联。`)
      else message.success(fileList.length ? '问题已上报，附件已保存' : '问题已上报')
      setReportOpen(false)
      reportForm.resetFields()
      setFileList([])
      setCreatedIssue(null)
      reportKey.current = null
      setRetry((value) => value + 1)
    } catch (e: any) {
      if (issue) { message.error('问题已保存，部分附件上传失败。请重试剩余附件。'); setRetry((value) => value + 1) }
      else message.error(e.response?.data?.detail ?? '未能确认上报结果，已保留填写内容，请重试')
    } finally {
      setSubmitting(false)
      submitLock.release()
    }
  }

  if (loading) {
    return <Space direction="vertical" style={{ width: '100%' }} size={12}>{[1, 2].map((i) => <Skeleton key={i} active paragraph={{ rows: 1 }} />)}</Space>
  }

  const visible=issues.filter(issue=>(scope==='all' || scope==='reported' ? scope!=='reported' || issue.reporter_id===user?.id : ['open','processing'].includes(issue.status)) && `${issue.title} ${issue.project_name}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()))
  const openIssue=(issue:MyIssue)=>{setDetail(issue);setConflict(false);setSearchParams({issue_id:issue.id},{replace:true})}
  return (
    <div className="worker-work-page">
      <WorkPageHeader title="问题" description="所有项目的问题都在这里，不用指派：谁处理谁点“开始处理”，处理完提交结果。"
        primary={<Button type="primary" aria-label="上报问题" icon={<PlusOutlined />} disabled={!canRaiseIssue || loadError || writableProjects.length===0} onClick={()=>{if(!permissions.current.raise)return;if(writableProjects.length===1)reportForm.setFieldValue('project_id',writableProjects[0].id);setReportOpen(true)}}>上报问题</Button>}
        tools={<RefreshAction onClick={()=>setRetry(value=>value+1)} />} meta={loadError?'数据暂不可用':`${issues.filter(issue=>['open','processing'].includes(issue.status)).length} 项待处理`} />
      <WorkSection filters={<><Segmented aria-label="问题查看范围" value={scope} onChange={value=>setScope(String(value))} options={[{value:'active',label:'待处理'},{value:'reported',label:'我上报的'},{value:'all',label:'全部'}]} /><Input.Search aria-label="搜索我的问题" placeholder="搜索问题或项目" allowClear value={search} onChange={event=>setSearch(event.target.value)} /></>}>

      {!loadError && focusIssueId && !issues.some(issue => issue.id === focusIssueId) && <Alert type="warning" showIcon style={{ marginBottom: 12 }}
        message="问题不存在或无权访问" description="此链接的问题不在你的可见范围内（可能已删除）。下方是其余的问题。"
        action={<Button onClick={closeDetail}>查看我的问题</Button>} />}
      {loadError ? (
        <Alert type="warning" showIcon message="暂时无法加载问题和项目" description="这不代表没有待处理问题。请检查网络后重试；已填写的上报内容仍保留在本页。" action={<Button onClick={() => setRetry((value) => value + 1)}>重新加载</Button>} />
      ) : issues.length === 0 ? (
        <Empty description={projects.length === 0 ? "系统里还没有项目。" : writableProjects.length === 0 ? "当前可见项目只读，可查阅问题历史；需要上报时请联系项目负责人确认项目状态。" : "当前没有需要关注的问题；遇到现场异常时，可点击上报问题。"} image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ padding: 60 }} />
      ) : (
        <ul className="issue-list" aria-label="我的问题列表">{visible.map(i => <li key={i.id} className={`issue-row sev-${i.severity}${['closed', 'cancelled'].includes(i.status) ? ' is-closed' : ''}`}>
          <span className={`issue-row-severity${i.source === 'vehicle' ? ' is-vehicle' : ''}`} title={`严重程度：${SEV[i.severity]?.label ?? ''}`} aria-hidden />
          <div className="issue-row-main">
            <button type="button" className="issue-row-title" onClick={() => openIssue(i)}>{i.title}</button>
            <span className="issue-row-meta"><span>{i.project_name}</span><span>{i.source === 'vehicle' ? `${i.asset_code || '车辆'}故障` : `${formatDateTime(i.created_at).split(' ')[0]} 上报`}</span></span>
          </div>
          <span className="issue-row-tags">{['critical', 'high'].includes(i.severity) && <Tag color={SEV[i.severity]?.color}>{SEV[i.severity]?.label}</Tag>}<Tag color={ISSUE_STATUS_MAP[i.status]?.color}>{ISSUE_STATUS_MAP[i.status]?.label}</Tag></span>
          <span className="issue-row-action">{!detail && canWork(i) && i.status === 'open' && <Button size="small" loading={handling} onClick={() => void handleIssue('processing', undefined, i)}>开始处理</Button>}</span>
        </li>)}</ul>
      )}

      {!loadError && issues.length>0 && visible.length===0 && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="这个范围没有问题"><Button onClick={()=>{setScope('all');setSearch('')}}>查看全部问题</Button></Empty>}
      </WorkSection>
      <Modal className="worker-work-modal" title="上报问题" open={reportOpen} onCancel={() => { if (!submitting) setReportOpen(false) }} onOk={() => reportForm.submit()} okButtonProps={{ disabled: !canRaiseIssue }} confirmLoading={submitting} cancelText="暂时收起" cancelButtonProps={{ disabled: submitting }} closable={!submitting} maskClosable={false} okText="提交上报" width={520}>
        <Form form={reportForm} layout="vertical" onFinish={submitReport} disabled={!canRaiseIssue || submitting} scrollToFirstError>
          <Form.Item name="project_id" label="所属项目" rules={[{ required: true, message: '请选择项目' }]}>
            <Select placeholder="选择项目" options={projects.map((p) => ({ value: p.id, label: p.name, disabled: isProjectWriteBlocked(p.status) }))} />
          </Form.Item>
          <Form.Item name="title" label="问题标题" rules={[{ required: true, whitespace: true, message: '请填写问题标题' }]}>
            <Input placeholder="如：3号车避障传感器报警" />
          </Form.Item>
          <Form.Item name="description" label="问题描述">
            <Input.TextArea rows={3} placeholder="发生时间、现象、影响范围等" />
          </Form.Item>
          <Form.Item name={['extra', 'device']} label="涉及车辆/设备（可选）">
            <AutoComplete options={vehicleOptions} placeholder="如：3号车 · AGV-003 / 充电桩" allowClear filterOption={(input, option) => String(option?.value ?? '').toLowerCase().includes(input.toLowerCase())} />
          </Form.Item>
          <Form.Item label="照片或附件（可选）" extra={createdIssue ? '问题已保存，提交时只重试下面剩余的附件。' : undefined}>
            <Upload multiple fileList={fileList} beforeUpload={file => { setFileList(list => [...list, file]); return false }} onRemove={file => setFileList(list => list.filter(item => item.uid !== file.uid))} accept="image/*,video/*,.pdf,.doc,.docx,.xls,.xlsx,.zip,.txt">
              <Button icon={<UploadOutlined />}>拍照或选择文件</Button>
            </Upload>
          </Form.Item>
          <div className="issue-form-pair">
            <Form.Item name="issue_type" label="问题类型" initialValue="other" rules={[{ required: true }]}>
              <Select options={ISSUE_TYPES.map((t) => ({ value: t.value, label: ISSUE_TYPE_SHORT[t.value] ?? t.value }))} />
            </Form.Item>
            <Form.Item name="severity" label="严重程度" initialValue="medium" rules={[{ required: true }]}>
              <Select options={[
                { value: 'critical', label: '严重 · 安全风险或停工' },
                { value: 'high', label: '高 · 关键工作受阻' },
                { value: 'medium', label: '中 · 可暂时继续' },
                { value: 'low', label: '低 · 不影响工作' },
              ]} />
            </Form.Item>
          </div>
          <details className="issue-form-more">
            <summary>更多信息（可选）</summary>
            <Form.Item name="nature" label="问题性质" initialValue="normal" extra="选“事故”或“质量问题”会自动建立需要提交的报告。" rules={[{required:true}]}><Select options={ISSUE_NATURES} /></Form.Item>
            <Form.Item noStyle shouldUpdate={(prev, cur) => prev.issue_type !== cur.issue_type}>
              {({ getFieldValue }) => (ISSUE_TYPE_FIELDS[getFieldValue('issue_type')] ?? []).filter(field => field.key !== 'device').map(field => (
                <Form.Item key={field.key} name={['extra', field.key]} preserve={false} label={field.label}>
                  {field.type === 'select' ? <Select options={field.options} placeholder={field.placeholder} allowClear /> : <Input placeholder={field.placeholder} />}
                </Form.Item>
              ))}
            </Form.Item>
          </details>
        </Form>
      </Modal>

      <Drawer className="worker-work-modal"
        title={detail?.title ?? ''}
        open={!!detail}
        onClose={closeDetail}
        width="min(420px, 100vw)"
      >
        {detail && (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Space size={6}>
              {detail.nature && <Tag>{ISSUE_NATURES.find(item=>item.value===detail.nature)?.label || '普通'}</Tag>}
              <Tag color={SEV[detail.severity]?.color}>{SEV[detail.severity]?.label}</Tag>
              <Tag color={ISSUE_STATUS_MAP[detail.status]?.color}>{ISSUE_STATUS_MAP[detail.status]?.label}</Tag>
              {detail.source === 'vehicle' && <Tag color="blue">车辆 {detail.asset_code}</Tag>}
            </Space>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {detail.project_name} · 上报 {detail.source === 'vehicle' ? formatDate(detail.created_at) : formatDateTime(detail.created_at)}
            </Typography.Text>
            {extraSummary(detail.extra) && <Typography.Text type="secondary" style={{ fontSize: 12 }}>{extraSummary(detail.extra)}</Typography.Text>}
            {detail.sla_due_at && <Typography.Paragraph type="secondary">处理时限 {detail.sla_hours} 小时 · 截止 {formatDateTime(detail.sla_due_at)}；仅关闭或作废算闭环。</Typography.Paragraph>}
            {detail.sla_warning && <Alert type="info" message={detail.sla_warning} />}
            {detail.description && (
              <Typography.Paragraph type="secondary">{detail.description}</Typography.Paragraph>
            )}
            <Divider style={{ margin: '4px 0' }} />
            <Typography.Text strong style={{ fontSize: 13 }}>处理进展</Typography.Text>
            {conflict && !resolutionOpen && <Button onClick={() => { setResolutionOpen(true) }}>查看更新并继续处理</Button>}
            <Typography.Paragraph type="secondary" style={{ fontSize: 13 }}>
              {detail.status === 'open' && '问题待处理，处理人接手后会开始处理。'}
              {detail.status === 'processing' && '正在处理中，可在消息通知页查看进度。'}
              {detail.status === 'resolved' && `已解决：${detail.resolution || '处理人已提交解决方案'}`}
              {(detail.status === 'closed' || detail.status === 'cancelled') && (detail.status === 'cancelled' ? '问题已作废。' : '问题已关闭。')}
            </Typography.Paragraph>
            {detail.project_status === 'completed' && <Alert type="warning" showIcon message="项目已完成" description="重开问题后，请项目负责人确认返工；需要安排或报工时，先将项目恢复到验收中。" />}
            {canWork(detail) && <Space>
              {detail.status === 'open' && <Button loading={handling} onClick={() => handleIssue('processing')}>开始处理</Button>}
              <Button loading={handling} onClick={() => { resolutionForm.setFieldsValue({ resolution: detail.resolution || '' }); setResolutionOpen(true) }}>提交处理结果</Button>
            </Space>}
            {canHandleIssue && detail.source !== 'vehicle' && !isProjectWriteBlocked(detail.project_status)
              && ['resolved', 'closed', 'cancelled'].includes(detail.status) && (
              <Button loading={reopening} onClick={async () => {
                if (!permissions.current.handle || isProjectWriteBlocked(detail.project_status) || !reopenLock.tryAcquire()) return
                setReopening(true)
                try {
                  await api.post(`/issues/${detail.id}/reopen`)
                  message.success(detail.project_status === 'completed' ? '问题已重新打开；需项目负责人确认是否恢复返工' : '问题已重新打开'); setDetail(null); setRetry((value) => value + 1)
                } catch (error: any) { message.error(error.response?.data?.detail ?? '重新打开失败') }
                finally { setReopening(false); reopenLock.release() }
              }}>重新打开</Button>
            )}
          </Space>
        )}
      </Drawer>
      <Modal className="worker-work-modal" title="提交处理结果" open={resolutionOpen} confirmLoading={handling} okButtonProps={{ disabled: !detail || !canWork(detail) || conflict }} onOk={() => resolutionForm.submit()} onCancel={() => { if (!handling) setResolutionOpen(false) }} okText="提交复核" cancelButtonProps={{ disabled: handling }}>
        {conflict && <Alert type="warning" message="问题已被他人修改，填写内容仍保留" action={<Button onClick={async () => {
          try {
            const result = await api.get('/dashboard/issues', { params: { include_closed: true } })
            const latest = (result.data.items ?? []).find((item: MyIssue) => item.id === detail?.id)
            if (!latest) { message.warning('该问题已不可见，请关闭后刷新列表'); return }
            setDetail(latest); setIssues(result.data.items ?? []); setConflict(false)
            message.info(`最新状态：${ISSUE_STATUS_MAP[latest.status]?.label || latest.status}。请确认后再提交`)
          } catch { message.error('刷新失败，请稍后重试；填写内容仍保留') }
        }}>刷新并查看最新状态</Button>} />}
        <Form form={resolutionForm} layout="vertical" onFinish={values => handleIssue('resolved', values.resolution.trim())}>
          <Form.Item name="resolution" label="处理措施与验证结果" rules={[{ required: true, whitespace: true, message: '请填写处理措施与验证结果' }]}><Input.TextArea rows={4} disabled={!canHandleIssue || handling || isProjectWriteBlocked(detail?.project_status)} /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
