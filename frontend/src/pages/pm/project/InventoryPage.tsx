import { useEffect, useRef, useState } from 'react'
import {
  Alert, Button, Col, DatePicker, Descriptions, Drawer, Empty, Form, Input, InputNumber, Modal,
  Popconfirm, Row, Select, Space, Table, Tag, Timeline, Typography, message, Upload, Tabs, Segmented, Pagination, Popover,
} from 'antd'
import {
  FileWordOutlined, InboxOutlined, PlusOutlined, UploadOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { api, errMsg } from '../../../api/client'
import { useAuth } from '../../../stores/auth'
import { clearPendingIntent, pendingIntentKey, readPendingIntent, writePendingIntent } from '../../../utils/pendingIntent'
import { useSubmitLock } from '../../../hooks/useSubmitLock'
import { formatDateTime } from '../../../utils/date'
import { useProjectWriteBlocked } from '../../../hooks/useProjectCapability'
import InlineSelect from '../../../components/InlineSelect'
import ContextTip from '../../../components/ContextTip'
import { WorkPageHeader, WorkSection } from '../../../components/WorkPage'
import { useMediaQuery } from '../../../hooks/useMediaQuery'
import './FieldWorkPages.css'

const OWNERSHIP: Record<string, { label: string; color: string }> = {
  company: { label: '我方', color: 'blue' },
  client: { label: '甲方', color: 'gold' },
  third_party: { label: '第三方', color: 'default' },
}
const CATEGORY: Record<string, string> = {
  equipment: '设备', tool: '工具', spare_part: '备件', material: '材料',
  consumable: '耗材', document: '资料', other: '其他',
}
const STATUS: Record<string, { label: string; color: string }> = {
  expected: { label: '待到场', color: 'default' }, in_transit: { label: '运输中', color: 'processing' },
  on_site: { label: '在现场', color: 'success' }, in_use: { label: '使用中', color: 'blue' },
  loaned: { label: '借出', color: 'purple' }, consumed: { label: '已耗尽', color: 'default' },
  returned: { label: '已归还', color: 'cyan' }, lost: { label: '遗失', color: 'error' },
  damaged: { label: '损坏', color: 'error' }, scrapped: { label: '报废', color: 'default' },
}
const MOVEMENT: Record<string, string> = {
  receive: '收货入场', issue: '领用出库', transfer: '位置转移', consume: '消耗',
  return_owner: '归还物主', return_site: '退回现场', adjust: '数量调整', inventory: '盘点',
}
const APP_STATUS: Record<string, { label: string; color: string }> = {
  pending: { label: '待审批', color: 'processing' },
  approved: { label: '已批准', color: 'success' },
  rejected: { label: '已驳回', color: 'error' },
}

const movementDisplayTime = (movement: any) => movement.time_basis === 'legacy_local'
  ? dayjs(movement.occurred_at).format('YYYY-MM-DD HH:mm') : formatDateTime(movement.occurred_at)

interface Props { projectId: string; canManage: boolean }

export default function InventoryPage({ projectId, canManage: managePermission }: Props) {
  const { user } = useAuth()
  const writeBlocked = useProjectWriteBlocked()
  const canManage = managePermission && !writeBlocked
  const canQuickEdit = canManage
  const isMobile = useMediaQuery('(max-width: 767px)')
  const [activeTab, setActiveTab] = useState('items')
  const [appStatusFilter, setAppStatusFilter] = useState('pending')
  const currentProject = useRef(projectId)
  currentProject.current = projectId
  const pendingMovements = useRef(new Map<string, any>())
  const [movementPending, setMovementPending] = useState<any>(null)
  const movementKey = (id: string) => pendingIntentKey('inventory', user?.id, projectId, id)
  const listSequence = useRef(0)
  const appSequence = useRef(0)
  const movementSequence = useRef(0)
  const [loadError, setLoadError] = useState(false)
  const [rows, setRows] = useState<any[]>([])
  const [summary, setSummary] = useState<any>({})
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [filters, setFilters] = useState({ search: '', ownership: '', status: '', category: '' })
  const [editing, setEditing] = useState<any | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [movementItem, setMovementItem] = useState<any | null>(null)
  const [movements, setMovements] = useState<any[]>([])
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()
  const [movementForm] = Form.useForm()
  useEffect(() => { pendingMovements.current.clear(); setMovementPending(null); setMovementItem(null) }, [projectId, user?.id])
  const movementType = Form.useWatch('movement_type', movementForm)
  // 内部联系单（物品申请）
  const [apps, setApps] = useState<any[]>([])
  const [appsLoading, setAppsLoading] = useState(false)
  const [editingApp, setEditingApp] = useState<any | null>(null)
  const [appModalOpen, setAppModalOpen] = useState(false)
  const [appSaving, setAppSaving] = useState(false)
  const [appForm] = Form.useForm()
  // 提交重入锁：防止快速双击「确定」等造成并发请求（重复错误提示）
  const appLock = useSubmitLock()
  const itemLock = useSubmitLock()
  const movementLock = useSubmitLock()

  const load = async (nextPage = page) => {
    const request = ++listSequence.current
    setLoading(true); setLoadError(false)
    try {
      const response = await api.get(`/projects/${projectId}/inventory`, { params: { ...filters, page: nextPage, page_size: 50 } })
      if (request !== listSequence.current) return
      setRows(response.data.items)
      setSummary(response.data.summary)
      setTotal(response.data.total)
    } catch { if (request === listSequence.current) setLoadError(true) } finally { if (request === listSequence.current) setLoading(false) }
  }

  useEffect(() => { void load(1); setPage(1); return () => { listSequence.current++ } }, [projectId, filters])

  // ===== 内部联系单（物品申请） =====
  const loadApplications = async () => {
    const request = ++appSequence.current
    setAppsLoading(true)
    try {
      const result = await api.get(`/projects/${projectId}/item-applications`)
      if (request === appSequence.current) setApps(result.data)
    } catch (error) { message.error(errMsg(error)) } finally { if (request === appSequence.current) setAppsLoading(false) }
  }
  useEffect(() => { void loadApplications(); return () => { appSequence.current++; movementSequence.current++ } }, [projectId])

  const openApplication = (app?: any) => {
    setEditingApp(app ?? null)
    appForm.resetFields()
    appForm.setFieldsValue(app ? {
      ...app,
      apply_date: app.apply_date ? dayjs(app.apply_date) : null,
    } : { status: 'pending', apply_date: dayjs() })
    setAppModalOpen(true)
  }

  const saveApplication = async () => {
    if (!canManage || !appLock.tryAcquire()) return
    let values: any
    try {
      values = await appForm.validateFields()
    } catch {
      // 表单校验失败：内联提示即可，解锁提交按钮
      appLock.release()
      return
    }
    const payload = { ...values, apply_date: values.apply_date ? values.apply_date.format('YYYY-MM-DD') : null }
    setAppSaving(true)
    try {
      if (editingApp) await api.put(`/projects/${projectId}/item-applications/${editingApp.id}`, payload)
      else await api.post(`/projects/${projectId}/item-applications`, payload)
      message.success(editingApp ? '物品申请已更新' : '物品申请已创建')
      setAppModalOpen(false)
      await loadApplications()
    } catch (error) { message.error(errMsg(error)) } finally { appLock.release(); setAppSaving(false) }
  }

  const downloadApplication = async (app: any) => {
    try {
      const r = await api.get(`/projects/${projectId}/item-applications/${app.id}/export`, { responseType: 'blob' })
      const url = URL.createObjectURL(r.data)
      const a = document.createElement('a'); a.href = url; a.download = `内部联系单-${(app.item_name || app.title || '物品').slice(0, 12)}.docx`; a.click()
      URL.revokeObjectURL(url)
    } catch (error) { message.error(errMsg(error)) }
  }

  const importApplication = async (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    try {
      const r = await api.post(`/projects/${projectId}/import/item-application`, fd, { timeout: 120000 })
      message.success(r.data?.message ?? '内部联系单已导入')
      await loadApplications()
    } catch (error) { message.error(errMsg(error)) }
    return false
  }

  const openItem = (item?: any) => {
    setEditing(item ?? null)
    form.resetFields()
    form.setFieldsValue(item ? {
      ...item,
      received_date: item.received_date ? dayjs(item.received_date) : null,
      expected_return_date: item.expected_return_date ? dayjs(item.expected_return_date) : null,
    } : { ownership: 'company', category: 'other', quantity: 1, unit: '件', status: 'on_site', tracking_mode: 'quantity' })
    setModalOpen(true)
  }

  const saveItem = async () => {
    if (!itemLock.tryAcquire()) return
    let values: any
    try {
      values = await form.validateFields()
    } catch {
      itemLock.release()
      return
    }
    const payload = {
      item_code: editing?.item_code ?? '',
      category: editing?.category ?? 'other',
      tracking_mode: editing?.tracking_mode ?? 'quantity',
      specification: editing?.specification ?? '',
      serial_number: editing?.serial_number ?? '',
      minimum_quantity: editing?.minimum_quantity ?? null,
      supplier: editing?.supplier ?? '',
      extra: editing?.extra ?? {},
      ...values,
      received_date: values.received_date ? values.received_date.format('YYYY-MM-DD') : null,
      expected_return_date: values.expected_return_date ? values.expected_return_date.format('YYYY-MM-DD') : null,
    }
    setSaving(true)
    try {
      if (editing) await api.put(`/projects/${projectId}/inventory/${editing.id}`, payload)
      else await api.post(`/projects/${projectId}/inventory`, payload)
      message.success(editing ? '物品已更新' : '物品已录入')
      setModalOpen(false)
      await load()
    } catch (error) { message.error(errMsg(error)) } finally { itemLock.release(); setSaving(false) }
  }

  const quickItemStatus = async (item: any, status: string | undefined) => {
    if (!status || !canQuickEdit || !itemLock.tryAcquire()) throw new Error('当前暂不能保存，请稍后重试')
    setSaving(true)
    try {
      const response = await api.patch(`/projects/${projectId}/inventory/${item.id}/status`, { status, expected_status: item.status })
      if (currentProject.current !== projectId) return
      setRows((current) => current.map((row) => row.id === item.id ? { ...row, status, ...response.data } : row))
      await load()
    } catch (error: any) {
      if (currentProject.current === projectId && error.response?.status === 409) await load()
      throw error
    } finally { itemLock.release(); setSaving(false) }
  }
  const quickApplicationStatus = async (app: any, status: string | undefined) => {
    if (!status || !canQuickEdit || !appLock.tryAcquire()) throw new Error('当前暂不能保存，请稍后重试')
    setAppSaving(true)
    try {
      const response = await api.patch(`/projects/${projectId}/item-applications/${app.id}/status`, { status, expected_status: app.status })
      if (currentProject.current !== projectId) return
      setApps((current) => current.map((row) => row.id === app.id ? { ...row, status, ...response.data } : row))
      await loadApplications()
    } catch (error: any) {
      if (currentProject.current === projectId && error.response?.status === 409) await loadApplications()
      throw error
    } finally { appLock.release(); setAppSaving(false) }
  }

  const openMovements = async (item: any) => {
    if (saving) return
    const pending = pendingMovements.current.get(item.id) ?? readPendingIntent<any>(movementKey(item.id))
    if (pending) pendingMovements.current.set(item.id, pending)
    setMovementPending(pending ?? null)
    const request = ++movementSequence.current
    setMovements([])
    setMovementItem(item)
    movementForm.resetFields()
    movementForm.setFieldsValue(pending ? { ...pending, occurred_at: dayjs(pending.occurred_at) } : { movement_type: 'transfer', quantity: item.quantity, occurred_at: dayjs(), from_location: item.location, handler: item.custodian })
    try {
      const result = await api.get(`/projects/${projectId}/inventory/${item.id}/movements`)
      if (request === movementSequence.current) setMovements(result.data)
    } catch (error) { message.error(errMsg(error)) }
  }

  const saveMovement = async () => {
    if (!canManage || !movementItem || !movementLock.tryAcquire()) return
    let payload = pendingMovements.current.get(movementItem.id)
    if (!payload) {
      try {
        const values = await movementForm.validateFields()
        payload = { ...values, occurred_at: values.occurred_at.toISOString(),
          client_uuid: globalThis.crypto?.randomUUID?.() ?? `local-${Date.now()}-${Math.random().toString(36).slice(2, 10)}` }
      } catch { movementLock.release(); return }
    }
    const id = movementItem.id
    pendingMovements.current.set(id, payload)
    writePendingIntent(movementKey(id), payload)
    setMovementPending(payload); setSaving(true)
    try {
      const response = await api.post(`/projects/${projectId}/inventory/${id}/movements`, payload)
      // Both a new write and an idempotent receipt confirm this operation.
      pendingMovements.current.delete(id); clearPendingIntent(movementKey(id)); setMovementPending(null)
      setMovementItem(response.data.item)
      movementForm.resetFields()
      movementForm.setFieldsValue({ movement_type: 'transfer', quantity: response.data.item.quantity, occurred_at: dayjs(), from_location: response.data.item.location, handler: response.data.item.custodian })
      message.success('收发记录已保存')
      try {
        setMovements((await api.get(`/projects/${projectId}/inventory/${id}/movements`)).data)
        await load()
      } catch { message.warning('流水已保存，但最新记录读取失败，请刷新查看，无需重复提交') }
    } catch (error: any) {
      if (error.response?.status >= 400 && error.response?.status < 500) {
        pendingMovements.current.delete(id); clearPendingIntent(movementKey(id)); setMovementPending(null)
      }
      message.error(errMsg(error))
    } finally { movementLock.release(); setSaving(false) }
  }

  const statItems = [
    ['全部物品', summary.total_records ?? 0], ['我方物品', summary.company_records ?? 0],
    ['甲方物品', summary.client_records ?? 0], ['需要关注', summary.attention_records ?? 0],
  ]
  const hasFilters = Object.values(filters).some(Boolean)
  const clearFilters = () => setFilters({ search: '', ownership: '', status: '', category: '' })
  const itemActions = (item: any) => <Space wrap>
    <Button title="查看流水" onClick={() => openMovements(item)}>收发记录</Button>
    {canManage && <Popover trigger="click" content={<Space direction="vertical">
      <Button aria-label={`编辑物品${item.name}`} onClick={() => openItem(item)}>编辑信息</Button>
      <Popconfirm title="删除物品及全部流水？" onConfirm={async () => {await api.delete(`/projects/${projectId}/inventory/${item.id}`);message.success('物品已删除');await load()}}><Button danger>删除物品</Button></Popconfirm>
    </Space>}><Button aria-label={`${item.name}更多操作`}>更多</Button></Popover>}
  </Space>
  const itemStatus = (item:any) => canQuickEdit ? <InlineSelect label={`${item.name}物品状态`} value={item.status} options={Object.entries(STATUS).map(([value,entry])=>({value,label:entry.label}))} disabled={saving} onSave={status=>quickItemStatus(item,status)} /> : <Tag color={STATUS[item.status]?.color}>{STATUS[item.status]?.label ?? item.status}</Tag>
  const appStatus = (app:any) => canQuickEdit ? <InlineSelect label={`${app.title || app.item_name}申请状态`} value={app.status} options={Object.entries(APP_STATUS).map(([value,entry])=>({value,label:entry.label}))} disabled={appSaving} onSave={status=>quickApplicationStatus(app,status)} /> : <Tag color={APP_STATUS[app.status]?.color}>{APP_STATUS[app.status]?.label ?? app.status}</Tag>
  const appActions = (app:any) => <Space wrap>
    <Button onClick={()=>openApplication(app)}>{canManage ? '查看与编辑' : '查看申请'}</Button>
    <Popover trigger="click" content={<Space direction="vertical"><Button icon={<FileWordOutlined />} onClick={()=>downloadApplication(app)}>导出 Word</Button>{canManage && <Popconfirm title="删除该申请记录？" onConfirm={async()=>{await api.delete(`/projects/${projectId}/item-applications/${app.id}`);message.success('已删除');await loadApplications()}}><Button danger>删除申请</Button></Popconfirm>}</Space>}><Button aria-label={`${app.title || app.item_name}申请更多操作`}>更多</Button></Popover>
  </Space>
  const filteredApps = apps.filter(app => appStatusFilter==='all' || app.status===appStatusFilter)
  const itemsContent = <WorkSection filters={<>
    <Input.Search allowClear aria-label="搜索现场物品" placeholder="搜索名称、编号或位置" value={filters.search} onChange={event=>setFilters(old=>({...old,search:event.target.value}))} onSearch={search=>setFilters(old=>({...old,search}))} />
    <Select aria-label="筛选物品归属" allowClear value={filters.ownership || undefined} placeholder="所有归属" onChange={(ownership='')=>setFilters(old=>({...old,ownership}))} options={Object.entries(OWNERSHIP).map(([value,meta])=>({value,label:meta.label}))} />
    <Select aria-label="筛选物品状态" allowClear value={filters.status || undefined} placeholder="所有状态" onChange={(status='')=>setFilters(old=>({...old,status}))} options={Object.entries(STATUS).map(([value,meta])=>({value,label:meta.label}))} />
    <Popover trigger="click" content={<Select style={{width:200}} aria-label="筛选物品分类" allowClear value={filters.category || undefined} placeholder="所有分类" onChange={(category='')=>setFilters(old=>({...old,category}))} options={Object.entries(CATEGORY).map(([value,label])=>({value,label}))} />}><Button>分类筛选</Button></Popover>
    {hasFilters && <Button onClick={clearFilters}>清空筛选</Button>}
    <span className="field-result-count">{total} 条物品记录</span>
  </>}>
    {isMobile ? <><div className="field-card-list">{rows.map(item=><article className="field-record-card" key={item.id}>
      <h3>{item.name}</h3><div className="field-record-meta"><Tag color={OWNERSHIP[item.ownership]?.color}>{OWNERSHIP[item.ownership]?.label ?? item.ownership}</Tag><strong className={item.low_stock?'inventory-low':''}>{item.quantity} {item.unit}</strong>{itemStatus(item)}</div>
      <span className="field-subline">{[item.item_code,item.specification,item.serial_number].filter(Boolean).join(' · ')}</span>
      <p>{item.location || '未填写位置'} · {item.custodian || '未指定保管人'}</p><div className="field-record-actions">{itemActions(item)}</div>
    </article>)}</div>{total > 0 && <Pagination simple current={page} pageSize={50} total={total} onChange={next=>{setPage(next);void load(next)}} />}</> : <Table rowKey="id" loading={loading} dataSource={rows} scroll={{ x: 900 }} pagination={{current:page,pageSize:50,total,showSizeChanger:false,onChange:next=>{setPage(next);void load(next)}}} columns={[
      {title:'物品',render:(_:any,item:any)=><div><strong>{item.name}</strong><span className="field-subline">{[item.item_code,item.specification,item.serial_number].filter(Boolean).join(' · ') || '未填写编号和规格'}</span></div>},
      {title:'归属',dataIndex:'ownership',render:(value:string)=><Tag color={OWNERSHIP[value]?.color}>{OWNERSHIP[value]?.label ?? value}</Tag>},
      {title:'数量',render:(_:any,item:any)=><span className={item.low_stock?'inventory-low':''}>{item.quantity} {item.unit}</span>},
      {title:'状态',render:(_:any,item:any)=>itemStatus(item)},
      {title:'位置与保管人',render:(_:any,item:any)=><div>{item.location || '-'}<span className="field-subline">{item.custodian || '未指定保管人'}</span></div>},
      {title:'操作',render:(_:any,item:any)=>itemActions(item)},
    ]} locale={{emptyText:hasFilters?'当前筛选范围没有物品':'还没有现场物品，点击录入物品添加第一条记录。'}} />}
    {isMobile && !rows.length && <Empty description={loading?'正在加载物品':'没有符合条件的物品'} />}
  </WorkSection>
  const applicationsContent = <WorkSection description="申请物品或服务，在列表查看审批状态。Word 联系单可导入或导出。"
    filters={<Segmented aria-label="物品申请查看范围" value={appStatusFilter} onChange={value=>setAppStatusFilter(String(value))} options={[{value:'pending',label:'待审批'},{value:'approved',label:'已批准'},{value:'rejected',label:'已驳回'},{value:'all',label:'全部'}]} />}
    extra={canManage && <Upload showUploadList={false} accept=".docx" beforeUpload={file=>importApplication(file as File)}><Button icon={<UploadOutlined />}>导入联系单</Button></Upload>}>
    {isMobile ? <div className="field-card-list">{filteredApps.map(app=><article className="field-record-card" key={app.id}><h3>{app.title || app.item_name}</h3><div className="field-record-meta">{appStatus(app)}<span>{app.amount || '未填写金额'}</span></div><span className="field-subline">{app.item_name}</span><p className="field-wrap">{app.requirement || '未填写需求'}</p><span className="field-subline">{[app.applicant,app.department,app.apply_date].filter(Boolean).join(' · ')}</span><div className="field-record-actions">{appActions(app)}</div></article>)}{!filteredApps.length && <Empty description="没有符合条件的申请" />}</div> : <Table rowKey="id" size="small" loading={appsLoading} dataSource={filteredApps} scroll={{ x: 820 }} pagination={false} locale={{emptyText:'没有符合条件的申请'}} columns={[
      {title:'申请事项',render:(_:any,app:any)=><div><strong>{app.title || app.item_name || '-'}</strong>{app.item_name && <span className="field-subline">{app.item_name}</span>}<span className="field-subline field-wrap">{app.requirement || '-'}</span></div>},
      {title:'申请人',render:(_:any,app:any)=><div>{app.applicant || '-'}<span className="field-subline">{app.department}</span></div>},
      {title:'金额',dataIndex:'amount',render:(value:string)=>value || '-'},
      {title:'状态',render:(_:any,app:any)=>appStatus(app)},
      {title:'日期',dataIndex:'apply_date'},
      {title:'操作',render:(_:any,app:any)=>appActions(app)},
    ]} />}
  </WorkSection>
  return <div className="inventory-page field-work-page">
    <WorkPageHeader title="现场物品" description="记录物品放在哪里、由谁保管，以及每次收货、领用和归还。"
      primary={canManage && <Button type="primary" icon={<PlusOutlined />} onClick={()=>activeTab==='items'?openItem():openApplication()}>{activeTab==='items'?'录入物品':'新建申请'}</Button>}
      tools={<Space wrap><Button onClick={()=>activeTab==='items'?load():loadApplications()}>刷新</Button><ContextTip id="inventory-quick-status" title="物品快捷调整">有管理权限时，可直接改状态；收货、领用和数量变动请记录在收发记录中。</ContextTip></Space>}
      meta={<Space wrap>{statItems.filter(([label])=>['全部物品','需要关注'].includes(String(label))).map(([label,value])=><span key={label}>{label} {value}</span>)}</Space>} />
    {loadError && <Alert type="error" showIcon message="物品列表加载失败" action={<Button onClick={()=>load()}>重试</Button>} />}
    <Tabs activeKey={activeTab} onChange={setActiveTab} items={[{key:'items',label:'物品',children:itemsContent},{key:'applications',label:`申请${apps.filter(app=>app.status==='pending').length ? ` (${apps.filter(app=>app.status==='pending').length})` : ''}`,children:applicationsContent}]} />

    <Modal className="field-work-modal" title={editingApp ? canManage ? '编辑物品申请' : '查看物品申请' : '新建物品申请'} open={appModalOpen} onCancel={() => { if (!appSaving) setAppModalOpen(false) }} onOk={saveApplication} footer={canManage ? undefined : null} confirmLoading={appSaving} width={640} destroyOnClose>
      <Form form={appForm} layout="vertical" requiredMark={false} disabled={!canManage}>
        <Form.Item name="title" label="申请事项" rules={[{ required: true, message: '请填写申请事项' }]}><Input placeholder="如：更换三支点螺栓需要吊车" /></Form.Item>
        <Row gutter={12}><Col xs={24} sm={12}><Form.Item name="item_name" label="物品/服务"><Input placeholder="如：吊车" /></Form.Item></Col>
          <Col xs={24} sm={12}><Form.Item name="amount" label="金额"><Input placeholder="如：3000元" /></Form.Item></Col></Row>
        <Form.Item name="requirement" label="需求"><Input.TextArea rows={2} placeholder="具体需求说明，如：更换三支点螺栓需要使用吊车，共计3000元" /></Form.Item>
        <Form.Item name="reason" label="原因"><Input.TextArea rows={2} /></Form.Item>
        <Row gutter={12}><Col xs={24} sm={12}><Form.Item name="drawing_no" label="图号"><Input /></Form.Item></Col>
          <Col xs={24} sm={12}><Form.Item name="contract_no" label="合同号"><Input /></Form.Item></Col></Row>
        <Row gutter={12}><Col xs={24} sm={8}><Form.Item name="applicant" label="申请人"><Input /></Form.Item></Col>
          <Col xs={24} sm={8}><Form.Item name="approver" label="审批人"><Input /></Form.Item></Col>
          <Col xs={24} sm={8}><Form.Item name="department" label="申请部门"><Input placeholder="如：项目技术部" /></Form.Item></Col></Row>
        <Row gutter={12}><Col xs={24} sm={12}><Form.Item name="apply_date" label="申请日期"><DatePicker style={{ width: '100%' }} /></Form.Item></Col>
          <Col xs={24} sm={12}><Form.Item name="status" label="状态"><Select options={Object.entries(APP_STATUS).map(([value, meta]) => ({ value, label: meta.label }))} /></Form.Item></Col></Row>
        <Form.Item name="note" label="备注"><Input.TextArea rows={2} /></Form.Item>
      </Form>
    </Modal>

    <Modal className="field-work-modal" title={editing ? '编辑物品' : '录入现场物品'} open={modalOpen} onCancel={() => { if (!saving) setModalOpen(false) }} onOk={saveItem} confirmLoading={saving} width={620} destroyOnClose>
      <Form form={form} layout="vertical" requiredMark={false}>
        <Form.Item name="name" label="物品名称" rules={[{ required: true, message: '请填写物品名称' }]}><Input placeholder="如：激光测距仪" /></Form.Item>
        <Row gutter={12}><Col xs={24} sm={8}><Form.Item name="quantity" label="数量" rules={[{ required: true }]}><InputNumber min={0} precision={2} style={{ width: '100%' }} /></Form.Item></Col><Col xs={24} sm={8}><Form.Item name="unit" label="单位" rules={[{ required: true }]}><Input /></Form.Item></Col><Col xs={24} sm={8}><Form.Item name="status" label="物品状态" rules={[{ required: true }]}><Select options={Object.entries(STATUS).map(([value, meta]) => ({ value, label: meta.label }))} /></Form.Item></Col></Row>
        <Row gutter={12}><Col xs={24} sm={12}><Form.Item name="ownership" label="物品归属" rules={[{ required: true }]}><Select options={Object.entries(OWNERSHIP).map(([value, meta]) => ({ value, label: meta.label }))} /></Form.Item></Col><Col xs={24} sm={12}><Form.Item name="location" label="去向 / 现场位置"><Input placeholder="放在哪里，或已归还给谁" /></Form.Item></Col></Row>
        <Form.Item name="custodian" label="保管人 / 使用人"><Input placeholder="当前由谁保管或使用" /></Form.Item>
        <details className="inventory-additional-fields">
          <summary>分类、编号与归还信息（选填）</summary>
          <Row gutter={12}>
            <Col xs={24} sm={12}><Form.Item name="category" label="物品分类"><Select options={Object.entries(CATEGORY).map(([value, label]) => ({ value, label }))} /></Form.Item></Col>
            <Col xs={24} sm={12}><Form.Item name="item_code" label="物品编号"><Input maxLength={100} placeholder="现场台账或资产编号" /></Form.Item></Col>
          </Row>
          <Form.Item name="specification" label="规格 / 型号"><Input maxLength={300} /></Form.Item>
          <Row gutter={12}>
            <Col xs={24} sm={12}><Form.Item name="serial_number" label="序列号"><Input maxLength={200} /></Form.Item></Col>
            <Col xs={24} sm={12}><Form.Item name="tracking_mode" label="管理方式"><Select options={[{ value: 'quantity', label: '按数量管理' }, { value: 'serial', label: '按序列号管理（数量 0 或 1）' }]} /></Form.Item></Col>
          </Row>
          <Form.Item name="supplier" label="供应商 / 来源"><Input maxLength={200} /></Form.Item>
          <Row gutter={12}>
            <Col xs={24} sm={12}><Form.Item name="received_date" label="到场日期"><DatePicker style={{ width: '100%' }} /></Form.Item></Col>
            <Col xs={24} sm={12}><Form.Item name="expected_return_date" label="预计归还日期"><DatePicker style={{ width: '100%' }} /></Form.Item></Col>
          </Row>
          <Form.Item name="minimum_quantity" label="库存关注数量" extra="库存小于或等于此数量时，列入“需要关注”。"><InputNumber min={0} precision={2} style={{ width: '100%' }} /></Form.Item>
        </details>
        <Form.Item name="note" label="补充说明"><Input.TextArea rows={2} /></Form.Item>
      </Form>
    </Modal>

    <Drawer className="field-work-modal" title={movementItem ? `${movementItem.name} · 收发记录` : '收发记录'} open={!!movementItem} onClose={() => { if (!saving) { movementSequence.current++; setMovementItem(null) } }} width={isMobile ? '100%' : 620}>
      {movementItem && <Descriptions size="small" column={2} items={[
        { key: 'owner', label: '归属', children: OWNERSHIP[movementItem.ownership]?.label },
        { key: 'balance', label: '当前数量', children: `${movementItem.quantity} ${movementItem.unit}` },
        { key: 'location', label: '位置', children: movementItem.location || '-' },
        { key: 'holder', label: '保管人', children: movementItem.custodian || '-' },
      ]} />}
      {canManage && <Form form={movementForm} layout="vertical" className="inventory-movement-form" disabled={saving || !!movementPending}>
        {movementPending && !saving && <Alert type="warning" showIcon message="这笔记录的结果尚未确认" description="已保留原操作、数量与操作编号；重试只确认同一笔记录，不会再次扣减库存。" />}
        <Row gutter={12}><Col xs={24} sm={12}><Form.Item name="movement_type" label="本次操作" rules={[{ required: true }]}><Select onChange={value => movementForm.setFieldValue('quantity', value === 'transfer' ? movementItem?.quantity : 1)} options={Object.entries(MOVEMENT).map(([value, label]) => ({ value, label }))} /></Form.Item></Col><Col xs={24} sm={12}>{['adjust', 'inventory'].includes(movementType) ? <Form.Item name="quantity_after" label="调整后数量" rules={[{ required: true }]}><InputNumber min={0} style={{ width: '100%' }} /></Form.Item> : <Form.Item name="quantity" label="本次数量" rules={[{ required: movementType !== 'transfer' }]}><InputNumber readOnly={movementType === 'transfer'} min={0} style={{ width: '100%' }} /></Form.Item>}</Col></Row>
        {movementType === 'transfer' && <Alert type="info" showIcon message="位置转移按整条台账数量移动" description="部分物品转移请先拆分台账，再对该条记录整批移动；此处不会自动拆分。" />}
        {['issue', 'consume', 'return_owner'].includes(movementType) && <Typography.Paragraph type="secondary">本次经手人和去向只记录在流水中，剩余库存的位置与保管人保持不变。</Typography.Paragraph>}
        <Row gutter={12}><Col xs={24} sm={12}><Form.Item name="from_location" label="原位置"><Input /></Form.Item></Col><Col xs={24} sm={12}><Form.Item name="to_location" label="新位置"><Input /></Form.Item></Col></Row>
        <Row gutter={12}><Col xs={24} sm={12}><Form.Item name="handler" label="经手人"><Input /></Form.Item></Col><Col xs={24} sm={12}><Form.Item name="occurred_at" label="发生时间" rules={[{ required: true }]}><DatePicker showTime style={{ width: '100%' }} /></Form.Item></Col></Row>
        <Form.Item name="note" label="说明"><Input.TextArea rows={2} /></Form.Item>
        <Button type="primary" disabled={false} icon={<InboxOutlined />} loading={saving} onClick={saveMovement}>{movementPending ? '重试本次记录' : '保存记录'}</Button>
      </Form>}
      <Typography.Title level={5}>历史记录</Typography.Title>
      <Timeline items={[...movements].sort((a, b) => movementDisplayTime(b).localeCompare(movementDisplayTime(a))).map((movement) => ({
        color: ['consume', 'return_owner'].includes(movement.movement_type) ? 'orange' : 'blue',
        children: <div className="inventory-movement"><strong>{MOVEMENT[movement.movement_type] ?? movement.movement_type}</strong><span>{movementDisplayTime(movement)}{movement.time_basis === 'legacy_local' && '（旧记录未注明时区）'} · 结余 {movement.balance_after} {movementItem?.unit}</span><p>{[movement.from_location && `从 ${movement.from_location}`, movement.to_location && `到 ${movement.to_location}`, movement.handler, movement.note].filter(Boolean).join(' · ')}</p></div>,
      }))} pending={false} />
    </Drawer>
  </div>
}
