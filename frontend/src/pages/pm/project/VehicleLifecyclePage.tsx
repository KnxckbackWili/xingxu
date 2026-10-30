import VehicleDocumentsPanel from '../../../components/VehicleDocumentsPanel'
import VehicleProgressMatrix from '../../../components/VehicleProgressMatrix'
import VehicleArrivalEditor from '../../../components/VehicleArrivalEditor'
import { hasProjectCapability, useProjectWriteBlocked } from '../../../hooks/useProjectCapability'
import { openWorkDetail } from '../../../stores/workDetail'
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert, Button, Checkbox, DatePicker, Drawer, Empty, Form, Input, InputNumber, Modal, Select,
  Space, Table, Tag, Typography, message, Popconfirm, Popover, Upload, Segmented,
} from 'antd'
import { CarOutlined, CheckCircleOutlined, DeleteOutlined, DownloadOutlined, EditOutlined, PlusOutlined, SwapOutlined, UploadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { useSubmitLock } from '../../../hooks/useSubmitLock'
import { api, errMsg } from '../../../api/client'
import { projectApi, type Project } from '../../../api'
import WorkAssignmentModal from '../../../components/WorkAssignmentModal'
import { useAuth } from '../../../stores/auth'
import { useLocation } from 'react-router-dom'
import { useVehicleTypes, toVehicleTypeSelectOptions } from '../../../hooks/useVehicleTypes'
import './VehicleLifecyclePage.css'
import { WorkPageHeader, WorkSection } from '../../../components/WorkPage'
import { useMediaQuery } from '../../../hooks/useMediaQuery'
import './FieldWorkPages.css'
import { IconAction, RefreshAction } from '../../../components/IconAction'

/** 根据起始编号生成连续编号：AGV-001 -> AGV-001, AGV-002... */
function nextAssetCode(startCode: string, index: number) {
  const match = startCode.match(/^(.*?)(\d+)$/)
  if (!match) return index === 0 ? startCode : `${startCode}-${index + 1}`
  const prefix = match[1]
  const num = parseInt(match[2], 10)
  const pad = match[2].length
  return `${prefix}${String(num + index).padStart(pad, '0')}`
}

const STATUS: Record<string, { label: string; color: string }> = {
  normal: { label: '正常', color: 'success' }, attention: { label: '需关注', color: 'warning' },
  fault: { label: '故障', color: 'error' }, stopped: { label: '停机', color: 'default' }, retired: { label: '退役', color: 'default' },
}
const EVENTS: Record<string, string> = {
  fault: '故障', repair: '维修', maintenance: '保养', inspection: '巡检',
  production: '生产', test: '测试', shipment: '发运', arrival: '到场', commission: '调试',
  handover: '移交', retire: '退役', other: '其他', created: '建档',
}

function VehicleLocationEditor({ code, location, onSave }: { code: string; location: string; onSave: (value: string) => Promise<void> }) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState(location)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const lock = useSubmitLock()
  const busy = useRef(false)
  const mounted = useRef(true)
  const trigger = useRef<HTMLButtonElement>(null)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const close = () => {
    if (busy.current) return
    setOpen(false); setDraft(location); setError('')
    trigger.current?.focus()
  }
  const save = async () => {
    const value = draft.trim()
    if (value === location) { close(); return }
    if (!lock.tryAcquire()) return
    busy.current = true; setSaving(true); setError('')
    try {
      await onSave(value)
      if (!mounted.current) return
      setOpen(false)
      message.success(`${code}当前位置已保存`)
      trigger.current?.focus()
    } catch (cause) {
      if (mounted.current) setError(errMsg(cause))
    } finally {
      lock.release(); busy.current = false
      if (mounted.current) setSaving(false)
    }
  }
  return <Popover title={`${code}当前位置`} trigger="click" placement="bottomLeft" open={open}
    onOpenChange={next => {
      if (busy.current) return
      setOpen(next); setError('')
      if (next) setDraft(location)
    }} content={<div className="vehicle-location-editor" onKeyDown={event => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close() }
    }}>
      <Input autoFocus aria-label={`${code}新位置`} maxLength={200} value={draft} disabled={saving}
        onChange={event => setDraft(event.target.value)} onPressEnter={save} placeholder="如：2号库 A区；留空清除" />
      <Typography.Text type="secondary">只更新当前位置，历史问题的位置保持原记录。</Typography.Text>
      {error && <Typography.Text type="danger" role="alert">{error}</Typography.Text>}
      <Space><Button aria-label="取消修改位置" disabled={saving} onClick={close}>取消</Button><Button aria-label="保存位置" type="primary" loading={saving} disabled={draft.trim() === location} onClick={save}>保存位置</Button></Space>
    </div>}>
    <Button ref={trigger} type="link" className="vehicle-location-trigger touch-target" aria-label={`修改${code}当前位置`} icon={<EditOutlined />}>
      {location || '填写位置'}
    </Button>
  </Popover>
}

export default function VehicleLifecyclePage({ project, onReload, configurationOnly = false, onDirtyChange }: { project: Project; onReload?: () => void | Promise<void>; configurationOnly?: boolean; onDirtyChange?: (dirty:boolean)=>void }) {
  const projectId = project.id
  const { user } = useAuth()
  const location = useLocation()
  const openedFromQuery = useRef('')
  const [units, setUnits] = useState<any[]>([])
  const [loaded, setLoaded] = useState(false)
  const [vehicles, setVehicles] = useState<any[]>([])
  const [selected, setSelected] = useState<any | null>(null)
  const [unitOpen, setUnitOpen] = useState(false)
  const [unitSaving, setUnitSaving] = useState(false)
  const unitLock = useSubmitLock()
  const [batchFailure, setBatchFailure] = useState<{ created: string[]; failed: string; remaining: number; reason: string } | null>(null)
  const eventLock = useSubmitLock()
  const [eventSaving, setEventSaving] = useState(false)
  const [eventOpen, setEventOpen] = useState(false)
  const [editingEvent, setEditingEvent] = useState<any | null>(null)
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const isMobile = useMediaQuery('(max-width: 767px)')
  const [unitForm] = Form.useForm()
  const [eventForm] = Form.useForm()
  const [typeConfig, setTypeConfig] = useState<any | null>(null)
  const [assignment, setAssignment] = useState<any>(null)
  const [typeForm] = Form.useForm()
  const [typeConfigOpen, setTypeConfigOpen] = useState(false)
  const writeBlocked = useProjectWriteBlocked(project.status)
  const hasManagePermission = hasProjectCapability(project.capabilities, 'project.manage_plan', user?.role === 'admin'
    || (user?.role === 'pm' && project.manager === user.id)
    || (['lead', 'technician'].includes(user?.role ?? '') && project.technical_manager === user?.id)
    || !!project.is_co_manager)
  const canManage = !writeBlocked && hasManagePermission
  const canExport = hasProjectCapability(project.capabilities, 'project.export', hasManagePermission)
  const canSchedule = !writeBlocked && hasProjectCapability(project.capabilities, 'project.manage_schedule', hasManagePermission)
  const canManageEvents = !writeBlocked && (hasProjectCapability(project.capabilities, 'project.manage_issues', false) || user?.role === 'admin' || user?.role === 'director' || project.manager === user?.id || project.technical_manager === user?.id || !!project.is_co_manager)
  const canConfigure = !writeBlocked && hasProjectCapability(project.capabilities, 'project.update', hasManagePermission)
  const canRecord = !writeBlocked && (user?.role === 'admin' || user?.role === 'director'
    || project.manager === user?.id || project.technical_manager === user?.id
    || (project.members ?? []).includes(user?.id ?? ''))
  // 车型字典（HYPE-63）：可选车型来自后端字典；已停用/字典外的历史值以「（历史）」保留显示。
  // 字典加载失败时暴露 error/reload：配置区显示错误提示 + 重试按钮，历史车型不受影响。
  const { options: dictOptions, loading: dictLoading, error: dictError, reload: reloadDict } = useVehicleTypes()
  const currentProject = useRef({ id: projectId, generation: 0 })
  if (currentProject.current.id !== projectId) currentProject.current = { id: projectId, generation: currentProject.current.generation + 1 }
  const loadSequence = useRef(0)

  const load = async () => {
    const generation = currentProject.current.generation
    const request = ++loadSequence.current
    try {
      const [list, types] = await Promise.all([
        api.get(`/projects/${projectId}/vehicle-units`).then((response) => response.data),
        projectApi.vehicles(projectId),
      ])
      if (request !== loadSequence.current || generation !== currentProject.current.generation) return
      setUnits(list)
      setVehicles(types)
      setLoaded(true)
    } catch (error) { if (request === loadSequence.current && generation === currentProject.current.generation) message.error(errMsg(error)) }
  }
  useEffect(() => {
    setUnits([]); setVehicles([]); setSelected(null); setLoaded(false); load()
    return () => { loadSequence.current++; currentProject.current.generation++ }
  }, [projectId])

  const saveLocation = async (unit: any, value: string) => {
    if (!canManage) return
    const generation = currentProject.current.generation
    loadSequence.current++
    const { data } = await api.put(`/projects/${projectId}/vehicle-units/${unit.id}`, { location: value })
    if (generation !== currentProject.current.generation) return
    loadSequence.current++
    setUnits(old => old.map(row => row.id === unit.id ? { ...row, ...data } : row))
    setSelected((old: any) => old?.id === unit.id ? { ...old, location: data.location } : old)
  }

  const downloadLifecycle = async () => {
    try {
      const r = await api.get(`/projects/${projectId}/export/lifecycle`, { responseType: 'blob' })
      const url = URL.createObjectURL(r.data)
      const a = document.createElement('a'); a.href = url; a.download = 'AGV生命周期表.xlsx'; a.click()
      URL.revokeObjectURL(url)
    } catch (error) { message.error(errMsg(error)) }
  }

  const importLifecycle = async (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    try {
      const r = await api.post(`/projects/${projectId}/import/lifecycle`, fd, { timeout: 120000 })
      message.success(r.data?.message ?? '生命周期表导入成功')
      await load()
    } catch (error) { message.error(errMsg(error)) }
    return false
  }

  const addVehicleType = async () => {
    try {
      await projectApi.addVehicle(projectId, { vehicle_type: dictOptions[0]?.name ?? '其他/定制', model_name: '新车型', quantity: 1 })
      await load()
      await onReload?.()
    } catch (error) { message.error(errMsg(error)) }
  }
  const updateVehicleType = async (v: any, field: string, value: any) => {
    try { await projectApi.updateVehicle(projectId, v.id, { [field]: value }); await load(); await onReload?.() } catch (error) { message.error(errMsg(error)) }
  }
  const removeVehicleType = async (vid: string) => {
    try { await projectApi.removeVehicle(projectId, vid); await load(); await onReload?.() } catch (error) { message.error(errMsg(error)) }
  }
  const openTypeConfig = (v: any) => {
    setTypeConfig(v)
    typeForm.setFieldsValue({ configuration: JSON.stringify(v.configuration ?? {}, null, 2), notes: v.notes ?? '' })
    setTypeConfigOpen(true)
  }
  const saveTypeConfig = async (values: any) => {
    if (!typeConfig) return
    try {
      const configuration = JSON.parse(values.configuration || '{}')
      if (!configuration || Array.isArray(configuration) || typeof configuration !== 'object') throw new SyntaxError()
      await projectApi.updateVehicle(projectId, typeConfig.id, { configuration, notes: values.notes ?? '' })
      message.success('车型配置已保存'); onDirtyChange?.(false); setTypeConfigOpen(false); setTypeConfig(null); await load(); await onReload?.()
    } catch (error) { message.error(error instanceof SyntaxError ? '配置必须是 JSON 对象' : errMsg(error)) }
  }

  const filtered = useMemo(() => units.filter((unit) => {
    const query = search.trim().toLowerCase()
    if (status === 'attention_all' && !(unit.open_issue_count || ['fault', 'stopped', 'attention'].includes(unit.current_status))) return false
    if (status === 'open' && !unit.open_issue_count) return false
    if (status && !['open', 'attention_all'].includes(status) && unit.current_status !== status) return false
    return !query || [unit.asset_code, unit.serial_number, unit.model_name, unit.location]
      .some((value) => (value ?? '').toLowerCase().includes(query))
  }), [units, search, status])

  const openHistory = async (unit: any) => {
    try { setSelected((await api.get(`/projects/${projectId}/vehicle-units/${unit.id}`)).data) }
    catch (error) { message.error(errMsg(error)) }
  }

  useEffect(() => {
    const unitId = new URLSearchParams(location.search).get('unit') ?? ''
    const unit = units.find((item) => item.id === unitId)
    if (!unit || openedFromQuery.current === unitId) return
    openedFromQuery.current = unitId
    openHistory(unit)
  }, [location.search, units])

  const createUnit = async (values: any) => {
    if (!unitLock.tryAcquire()) return
    setUnitSaving(true)
    setBatchFailure(null)
    const count = Math.max(1, Number(values.batch_count) || 1)
    const created: string[] = []
    let currentCode = values.asset_code
    try {
      for (let i = 0; i < count; i++) {
        currentCode = nextAssetCode(values.asset_code, i)
        await api.post(`/projects/${projectId}/vehicle-units`, {
          ...values, asset_code: currentCode, current_stage: 'planned',
        })
        created.push(currentCode)
      }
      message.success(count > 1 ? `已批量建档 ${count} 台现场车辆` : '现场车辆已建档')
    } catch (error) {
      setBatchFailure({ created, failed: currentCode, remaining: count - created.length - 1, reason: errMsg(error) })
    } finally {
      // Each POST commits separately. Refresh even on partial failure and never replay the batch.
      setUnitOpen(false); unitForm.resetFields(); await load()
      setUnitSaving(false); unitLock.release()
    }
  }

  const saveEvent = async (values: any) => {
    if (!selected || !eventLock.tryAcquire()) return
    setEventSaving(true)
    try {
      const payload = {
        ...values,
        event_date: values.event_date.format('YYYY-MM-DD'),
        replaced_parts: values.replaced_parts ?? [],
        status_after: values.is_closed ? 'normal' : values.status_after,
      }
      if (editingEvent) {
        const { event_date: _eventDate, event_type: _eventType, location_after: _location, ...updates } = payload
        await api.put(`/projects/${projectId}/vehicle-units/${selected.id}/events/${editingEvent.id}`, updates)
        message.success('现场问题记录已更新')
      } else {
        await api.post(`/projects/${projectId}/vehicle-units/${selected.id}/events`, payload)
        message.success('现场问题已记录')
      }
      setEventOpen(false); setEditingEvent(null); eventForm.resetFields(); await openHistory(selected); await load()
    } catch (error) { message.error(errMsg(error)) }
    finally { eventLock.release(); setEventSaving(false) }
  }

  const editEvent = (event: any) => {
    setEditingEvent(event)
    eventForm.setFieldsValue({
      ...event,
      event_date: dayjs(event.event_date),
      status_after: event.status_after || selected?.current_status || 'attention',
      replaced_parts: event.replaced_parts ?? [],
    })
    setEventOpen(true)
  }

  const closeEvent = async (event: any) => {
    if (!selected) return
    try {
      await api.put(`/projects/${projectId}/vehicle-units/${selected.id}/events/${event.id}`, {
        is_closed: true,
        status_after: 'normal',
      })
      message.success('问题已关闭，车辆状态已按剩余问题更新')
      await openHistory(selected); await load()
    } catch (error) { message.error(errMsg(error)) }
  }

  const configuration = <WorkSection title={`计划车型与数量（${vehicles.reduce((s: number, v: any) => s + (v.quantity || 0), 0)} 台）`}
      extra={canConfigure && <Button size="small" type="primary" icon={<PlusOutlined />} onClick={addVehicleType}>添加车型</Button>}
      description="实车登记在「车辆」页；计划车型数量变化后，请核对周计划。">
      {dictError && <Alert type="error" showIcon style={{ marginBottom: 12 }} message="车型字典加载失败"
        description={<>无法获取可选车型列表：{dictError}。历史车型仍可正常显示与编辑，请点击重试。</>}
        action={<Button size="small" onClick={reloadDict}>重试</Button>} />}
      <Table rowKey="id" dataSource={vehicles} scroll={{ x: 640 }} pagination={false} size="small" columns={[
        { title: '车型', dataIndex: 'vehicle_type', width: 150, render: (val: string, rec: any) => canConfigure
          ? <Select size="small" value={val} style={{ width: 140 }} aria-label="车型" loading={dictLoading} onChange={(v) => updateVehicleType(rec, 'vehicle_type', v)} options={toVehicleTypeSelectOptions(dictOptions, [val])} />
          : <Tag>{val}</Tag> },
        { title: '型号', dataIndex: 'model_name', render: (val: string, rec: any) => canConfigure
          ? <Input size="small" defaultValue={val} style={{ width: 160 }} aria-label="型号" onBlur={(e) => e.target.value !== val && updateVehicleType(rec, 'model_name', e.target.value)} />
          : val },
        { title: '数量', dataIndex: 'quantity', width: 120, render: (val: number, rec: any) => canConfigure
          ? <InputNumber size="small" min={1} defaultValue={val} aria-label="数量" onBlur={(e) => Number(e.target.value) !== val && updateVehicleType(rec, 'quantity', Number(e.target.value))} />
          : `${val} 台` },
        { title: '配置', width: 100, render: (_: any, rec: any) => <Button size="small" type="link" onClick={() => openTypeConfig(rec)}>{Object.keys(rec.configuration ?? {}).length ? `${Object.keys(rec.configuration).length} 项` : canConfigure ? '填写' : '查看'}</Button> },
        ...(canConfigure ? [{ title: '', width: 50, render: (_: any, rec: any) => <Popconfirm title="删除该车型配置？" onConfirm={() => removeVehicleType(rec.id)}><Button size="small" type="text" danger icon={<DeleteOutlined />} aria-label="删除车型配置" /></Popconfirm> }] : []),
      ]} />
    </WorkSection>
  const configurationModal = <Modal className="field-work-modal" title={`${typeConfig?.vehicle_type ?? ''} ${typeConfig?.model_name ?? ''} · 车型配置`} open={typeConfigOpen}
      onCancel={() => { onDirtyChange?.(false); setTypeConfigOpen(false); setTypeConfig(null) }} onOk={() => typeForm.submit()} okText="保存" okButtonProps={{ disabled: !canConfigure }} width={640}>
      <Form form={typeForm} layout="vertical" onFinish={saveTypeConfig} onValuesChange={()=>onDirtyChange?.(true)}>
        <Form.Item name="configuration" label="扩展配置 JSON" extra="记录导航方式、载重、电池、尺寸、安全扫描仪、通信方式等。">
          <Input.TextArea rows={9} disabled={!canConfigure} spellCheck={false} style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' }} />
        </Form.Item>
        <Form.Item name="notes" label="车型备注"><Input.TextArea rows={3} disabled={!canConfigure} /></Form.Item>
      </Form>
    </Modal>
  if (configurationOnly) return <div>{configuration}{configurationModal}</div>
  const openIssues = units.reduce((sum, unit) => sum + (unit.open_issue_count ?? 0), 0)
  return <div className="field-work-page">
    <WorkPageHeader title="车辆" description="按车号登记环节，查看车辆位置与问题履历。"
      primary={canManage && <Button type="primary" icon={<PlusOutlined />} onClick={() => setUnitOpen(true)}>添加车辆</Button>}
      tools={<Space wrap>{canManage && units.length > 0 && <VehicleArrivalEditor key={projectId} project={project} units={units} onSaved={async () => { await load(); await onReload?.() }} />}<RefreshAction onClick={load} />{(canManage || canExport) && <Popover trigger="click" placement="bottomRight" content={<div className="field-secondary-actions">
        {canManage && <Upload showUploadList={false} accept=".xlsx" beforeUpload={(f) => importLifecycle(f as File)}><Button icon={<UploadOutlined />}>导入车辆表</Button></Upload>}
        {canExport && <Button icon={<DownloadOutlined />} onClick={downloadLifecycle}>导出车辆表</Button>}
        <Typography.Text type="secondary">Excel 按车辆编号匹配，重复导入不重复建档；保留原生命周期表格式。</Typography.Text>
      </div>}><IconAction bordered label="导入与导出" icon={<SwapOutlined />} /></Popover>}</Space>}
      meta={<Space wrap><span>{units.length} 台车辆</span><span>{openIssues} 个未关闭问题</span></Space>} />
    {loaded && !units.length ? <Empty className="vehicles-empty" image={Empty.PRESENTED_IMAGE_SIMPLE} description={<><strong>还没有车辆档案</strong><span>按车号建档后，就能逐车登记到场、调试等环节，并跟踪每台车的问题。{(project.vehicle_total ?? 0) > 0 ? `计划共 ${project.vehicle_total} 台。` : ''}</span></>}>
      {canManage && <Button type="primary" icon={<PlusOutlined />} onClick={() => setUnitOpen(true)}>添加车辆</Button>}
    </Empty> : <>
    <VehicleProgressMatrix projectId={projectId} status={project.status} onChanged={() => { void load(); void onReload?.() }} />
    <Typography.Title level={4}>车辆档案与问题履历</Typography.Title>
    {batchFailure && <Alert type="warning" showIcon closable onClose={() => setBatchFailure(null)}
      message="车辆批量建档已停止，请核对台账后补录"
      description={<div><div>已确认建档 {batchFailure.created.length} 台：{batchFailure.created.join('、') || '无'}</div>
        <div>未确认建档：{batchFailure.failed}（{batchFailure.reason}）；后续 {batchFailure.remaining} 台未提交</div>
        <div>列表已重新加载。请先核对未确认编号是否存在，再用「添加车辆」补录缺少的编号。</div></div>} />}
    <WorkSection filters={<>
      <Segmented aria-label="车辆查看范围" value={status === 'attention_all' ? 'attention_all' : ''} options={[{value:'',label:'全部车辆'},{value:'attention_all',label:'需关注'}]} onChange={value => setStatus(String(value))} />
      <Input allowClear aria-label="搜索现场车辆" placeholder="搜索编号、型号或位置" value={search} onChange={event => setSearch(event.target.value)} />
      <Select allowClear aria-label="筛选车辆状态" placeholder="所有状态" value={['', 'attention_all'].includes(status) ? undefined : status} onChange={value => setStatus(value ?? '')} options={[{value:'open',label:'有未关闭问题'},...Object.entries(STATUS).map(([value,item]) => ({value,label:item.label}))]} />
      <span className="field-result-count">{filtered.length} 台</span>
    </>}>
      {isMobile ? <div className="field-card-list">{filtered.map(unit => <article className="field-record-card" key={unit.id}>
        <h3><CarOutlined /> {unit.asset_code}</h3><div className="field-record-meta"><Tag color={STATUS[unit.current_status]?.color}>{STATUS[unit.current_status]?.label ?? unit.current_status}</Tag>{unit.open_issue_count ? <Tag color="red">{unit.open_issue_count} 个未关闭问题</Tag> : <span>无遗留问题</span>}</div>
        <p>{unit.vehicle_type || '-'} / {unit.model_name || '-'}</p>
        <div>到场日期：{unit.arrived_at || '未登记'}</div>
        <div>位置：{canManage ? <VehicleLocationEditor key={`${projectId}:${unit.id}`} code={unit.asset_code} location={unit.location || ''} onSave={next => saveLocation(unit,next)} /> : unit.location || '-'}</div>
        <div className="field-record-actions"><Button onClick={() => openHistory(unit)}>车辆记录</Button></div>
      </article>)}{!filtered.length && <Empty description="没有符合条件的车辆" />}</div>
      : <Table rowKey="id" size="small" dataSource={filtered} scroll={{ x: 780 }} pagination={{defaultPageSize:20,pageSizeOptions:[20,50,100],showSizeChanger:true,showTotal:total=>`共 ${total} 台`}} columns={[
        {title:'车辆',render:(_:any,unit:any)=><div><Typography.Text strong>{unit.asset_code}</Typography.Text><span className="field-subline">{unit.vehicle_type || '-'} / {unit.model_name || '-'}</span></div>},
        {title:'当前位置',dataIndex:'location',render:(value:string,unit:any)=>canManage ? <VehicleLocationEditor key={`${projectId}:${unit.id}`} code={unit.asset_code} location={value || ''} onSave={next=>saveLocation(unit,next)} /> : value || '-'},
        {title:'到场日期',dataIndex:'arrived_at',render:(value:string)=>value || '未登记'},
        {title:'状态',dataIndex:'current_status',render:(value:string)=><Tag color={STATUS[value]?.color}>{STATUS[value]?.label ?? value}</Tag>},
        {title:'未关闭问题',render:(_:any,unit:any)=>unit.open_issue_count ? <Tag color="red">{unit.open_issue_count} 个</Tag> : '无'},
        {title:'最近问题',dataIndex:'last_issue_date',render:(value:string)=>value || '-'},
        {title:'操作',render:(_:any,unit:any)=><Button onClick={()=>openHistory(unit)}>车辆记录</Button>},
      ]} />}
    </WorkSection>
    </>}


    <Modal className="field-work-modal" title="添加现场车辆" open={unitOpen} onCancel={() => { if (!unitSaving) { setUnitOpen(false); unitForm.resetFields() } }} onOk={() => unitForm.submit()} confirmLoading={unitSaving} cancelButtonProps={{ disabled: unitSaving }} okText="建立档案" width={520}>
      <Form form={unitForm} layout="vertical" onFinish={createUnit}>
        <Space.Compact style={{ width: '100%' }}>
          <Form.Item name="asset_code" label="起始编号" rules={[{ required: true, message: '请填写起始车辆编号' }]} style={{ flex: 1, marginBottom: 12 }}>
            <Input placeholder="如 AGV-001" />
          </Form.Item>
          <Form.Item name="batch_count" label="数量" initialValue={1} style={{ width: 110, marginLeft: 8, marginBottom: 12 }}>
            <InputNumber min={1} max={500} style={{ width: '100%' }} />
          </Form.Item>
        </Space.Compact>
        <Form.Item name="vehicle_id" label="车型"><Select allowClear placeholder="选择项目中已配置的车型" options={vehicles.map((vehicle) => ({ value: vehicle.id, label: `${vehicle.vehicle_type} / ${vehicle.model_name}` }))} /></Form.Item>
        <Form.Item name="location" label="当前位置"><Input placeholder="如 2 号库 A 区" /></Form.Item>
        <Typography.Text type="secondary">填起始编号和数量后，会按连续编号批量建档，如 AGV-001 ~ AGV-005。</Typography.Text>
      </Form>
    </Modal>

    <Drawer className="field-work-modal" title={selected ? `${selected.asset_code} · 车辆记录` : ''} open={!!selected} onClose={() => setSelected(null)} width={isMobile ? '100%' : 720} extra={canRecord ?
      <Button type="primary" icon={<PlusOutlined />} onClick={() => {
        setEditingEvent(null)
        eventForm.resetFields()
        eventForm.setFieldsValue({ event_date: dayjs(), event_type: 'fault', status_after: 'attention', is_closed: false, replaced_parts: [] })
        setEventOpen(true)
      }}>记录问题</Button> : null
    }>
      {selected && <>
        <div className="vehicle-state-strip">
          <span><b>{STATUS[selected.current_status]?.label ?? selected.current_status}</b>当前状态</span>
          <span><b>{selected.open_issue_count ?? 0}</b>未关闭问题</span>
          <span><b>{selected.arrived_at || '未登记'}</b>到场日期</span>
          <span><b>{selected.location || '-'}</b>现场位置</span>
        </div>
        <VehicleDocumentsPanel key={`${projectId}:${selected.id}`} projectId={projectId} unitId={selected.id} unitLabel={selected.fleet_no || selected.asset_code} projectStatus={project.status} onChanged={() => { void onReload?.() }} />
        {selected.events?.length ? <div style={{ marginTop: 16 }}>
          {selected.events.map((event: any) => <div key={event.id} className="vehicle-history-entry">
            <Space wrap>
              <Typography.Text strong>{event.title}</Typography.Text>
              <Tag>{EVENTS[event.event_type] ?? event.event_type}</Tag>
              {['fault', 'repair', 'maintenance', 'inspection'].includes(event.event_type) && <Tag color={event.is_closed ? 'green' : 'red'}>{event.is_closed ? '已关闭' : '待处理'}</Tag>}
            </Space>
            <Typography.Text type="secondary" style={{ display: 'block', marginTop: 3 }}>{event.event_date} · 记录人 {event.operator_name || '系统'}{event.handler ? ` · 处理人 ${event.handler}` : ''}</Typography.Text>
            {event.description && <Typography.Paragraph style={{ margin: '8px 0 0' }}><b>现象：</b>{event.description}</Typography.Paragraph>}
            {event.fault_part && <div><b>部位：</b>{event.fault_part}</div>}
            {event.cause && <div><b>原因：</b>{event.cause}</div>}
            {event.action_taken && <div><b>处理：</b>{event.action_taken}</div>}
            {!!event.replaced_parts?.length && <div><b>更换配件：</b>{event.replaced_parts.map((part: any) => `${part.name || '配件'}${part.model ? `(${part.model})` : ''} x${part.quantity || 1}`).join('；')}</div>}
            {event.downtime_hours != null && <div><b>停机：</b>{event.downtime_hours} 小时</div>}
            {event.verification && <div><b>验证：</b>{event.verification}</div>}
            {!!event.assignments?.length && <div className="vehicle-repair-assignments"><strong>历史按日安排</strong>{event.assignments.map((entry: any) => <div key={entry.id}><button className="task-name-link" onClick={() => openWorkDetail({projectId,taskId:entry.task_id,entryId:entry.entry_id || entry.id,onChanged:()=>{load();if(selected)openHistory(selected)}})}>{entry.work_date} · {entry.assignee_name} · 查看工作与结果</button> <Tag color="blue">历史计划来源</Tag></div>)}</div>}
            {!!event.weekly_assignments?.length && <div className="vehicle-repair-assignments"><strong>维修周计划</strong>{event.weekly_assignments.map((cell:any)=><div key={cell.id}><a href={`/pm/projects/${projectId}/plan?view=weeks&week=${cell.week_start}&cell=${cell.id}`}>{cell.week_start} · {cell.assignees?.map((person:any)=>person.name).join('、')||'未分配'}</a> <Tag>{cell.is_cancelled?'已取消':cell.published?'已发布':'草稿'}</Tag></div>)}</div>}
            {canSchedule && !event.is_closed && <Button size="small" style={{ marginTop: 8 }} onClick={() => setAssignment({ projectId, repair: { unitId: selected.id, eventId: event.id, title: event.title } })}>{event.assignments?.length ? '追加维修安排' : '安排维修'}</Button>}
            {!writeBlocked && (canManageEvents || event.operator_id === user?.id) && <Space size={0} wrap>
              <Button size="small" type="link" icon={<EditOutlined />} onClick={() => editEvent(event)}>补充 / 编辑</Button>
              {!event.is_closed && <Button size="small" type="link" icon={<CheckCircleOutlined />} onClick={() => closeEvent(event)}>标记已解决</Button>}
            </Space>}
          </div>)}
        </div> : <Empty description="暂无现场问题记录" style={{ marginTop: 32 }} />}
      </>}
    </Drawer>

    <WorkAssignmentModal context={assignment} onClose={() => setAssignment(null)} onSaved={() => { load(); if (selected) openHistory(selected) }} />

    <Modal className="field-work-modal" title={`${editingEvent ? '编辑' : '记录'}现场车辆问题：${selected?.asset_code ?? ''}`} open={eventOpen} confirmLoading={eventSaving} onCancel={() => { if (!eventSaving) { setEventOpen(false); setEditingEvent(null); eventForm.resetFields() } }} onOk={() => eventForm.submit()} okText="保存记录" width={700}>
      <Form form={eventForm} layout="vertical" onFinish={saveEvent}>
        <div className="vehicle-event-fields">
          <Form.Item name="event_type" label="记录类型" rules={[{ required: true }]} style={{ flex: 1 }}><Select disabled={!!editingEvent} options={['fault', 'repair', 'maintenance', 'inspection', 'other'].map((value) => ({ value, label: EVENTS[value] }))} /></Form.Item>
          <Form.Item name="event_date" label="发生日期" rules={[{ required: true }]} style={{ flex: 1 }}><DatePicker disabled={!!editingEvent} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="status_after" label="车辆状态" style={{ flex: 1 }}><Select options={Object.entries(STATUS).map(([value, item]) => ({ value, label: item.label }))} /></Form.Item>
        </div>
        <Form.Item name="title" label="问题标题" rules={[{ required: true }]}><Input placeholder="如：左前避障传感器间歇报警" /></Form.Item>
        <div className="vehicle-event-fields">
          <Form.Item name="fault_part" label="故障部位" style={{ flex: 1 }}><Input placeholder="传感器、电机、PLC、轮组等" /></Form.Item>
          <Form.Item name="handler" label="现场处理人" style={{ flex: 1 }}><Input /></Form.Item>
          <Form.Item name="downtime_hours" label="停机小时" style={{ flex: 1 }}><InputNumber min={0} precision={1} style={{ width: '100%' }} /></Form.Item>
        </div>
        <Form.Item name="description" label="故障现象"><Input.TextArea rows={2} placeholder="什么时候出现、如何复现、报警码和现场影响" /></Form.Item>
        <Form.Item name="cause" label="原因判断"><Input.TextArea rows={2} placeholder="已确认原因或当前排查结论" /></Form.Item>
        <Form.Item name="action_taken" label="处理过程"><Input.TextArea rows={3} placeholder="做了哪些检查、调整、维修或软件修改" /></Form.Item>
        <Form.List name="replaced_parts">
          {(fields, { add, remove }) => <div>
            <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 8 }}><Typography.Text strong>更换配件</Typography.Text><Button size="small" type="dashed" icon={<PlusOutlined />} onClick={() => add({ quantity: 1 })}>添加配件</Button></Space>
            {fields.map(({ key, name }) => <div key={key} className="vehicle-part-fields">
              <Form.Item name={[name, 'name']} rules={[{ required: true, message: '填写配件名称' }]}><Input aria-label="配件名称" placeholder="配件名称" /></Form.Item>
              <Form.Item name={[name, 'model']}><Input aria-label="配件型号或料号" placeholder="型号/料号" /></Form.Item>
              <Form.Item name={[name, 'quantity']}><InputNumber min={1} aria-label="配件数量" placeholder="数量" /></Form.Item>
              <Button type="text" danger aria-label={`删除第 ${name + 1} 项配件`} onClick={() => remove(name)}>删除</Button>
            </div>)}
          </div>}
        </Form.List>
        <Form.Item name="verification" label="处理后验证"><Input.TextArea rows={2} placeholder="试运行结果、观察周期及仍需关注事项" /></Form.Item>
        <Form.Item name="location_after" label="车辆当前现场位置" extra={editingEvent ? '历史记录的位置不可修改；当前位置可在车辆清单中单独更新。' : undefined}><Input disabled={!!editingEvent} /></Form.Item>
        <Form.Item name="is_closed" valuePropName="checked"><Checkbox>本次记录已处理完成，无遗留问题</Checkbox></Form.Item>
      </Form>
    </Modal>


  </div>
}
