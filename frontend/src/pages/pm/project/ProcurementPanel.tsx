import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Empty, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Switch, Table, Tag, Typography, Checkbox } from 'antd'
import { api, errMsg } from '../../../api/client'
import { useAuth } from '../../../stores/auth'
import { useProjectCapability, useProjectWriteBlocked } from '../../../hooks/useProjectCapability'

interface Procurement {
  id: string; name: string; status: string; owner_id: string | null; owner_party: string; owner_name: string
  required_date: string | null; committed_date: string | null; forecast_date: string | null; actual_date: string | null
  is_required: boolean; risk: string; note: string; extra: Record<string, unknown>
}
const statuses = [{ value: 'not_started', label: '未开始' }, { value: 'in_progress', label: '进行中' }, { value: 'pending', label: '待确认' }, { value: 'passed', label: '已通过' }, { value: 'failed', label: '不通过' }, { value: 'na', label: '不适用' }]
const parties = [{ value: 'project', label: '项目团队' }, { value: 'client', label: '客户' }, { value: 'procurement', label: '采购部门' }, { value: 'production', label: '生产部门' }, { value: 'software', label: '软件团队' }]
const orders = ['未申请', '已下单', '采购中', '已到货']
export default function ProcurementPanel({ projectId, templateId, onDirtyChange }: { projectId: string; templateId?: string; onDirtyChange?: (dirty: boolean) => void }) {
  const { user } = useAuth()
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>()
  const [mine, setMine] = useState(false)
  const [today, setToday] = useState('')
  const [items, setItems] = useState<Procurement[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [actionError, setActionError] = useState('')
  const [busy, setBusy] = useState(false)
  const [editing, setEditing] = useState<Procurement | 'new' | null>(null)
  const [form] = Form.useForm()
  const [owners, setOwners] = useState<Array<{ id: string; display_name: string }>>([])
  const [catalog, setCatalog] = useState<Array<{ id: string; name: string; unit: string; spec: string }>>([])
  const [catalogOpen, setCatalogOpen] = useState(false)
  const [catalogError, setCatalogError] = useState('')
  const [catalogBusy, setCatalogBusy] = useState(false)
  const [catalogSelection, setCatalogSelection] = useState<string[]>([])
  const [catalogQuantities, setCatalogQuantities] = useState<Record<string, number>>({})
  const lock = useRef(false)
  const sequence = useRef(0)
  const generation = useRef(0)
  const owner = useRef(projectId); owner.current = projectId
  const writable = useProjectCapability('project.manage_plan') && !useProjectWriteBlocked()
  const path = `/projects/${encodeURIComponent(projectId)}/procurements`
  const load = async () => {
    const ticket = ++sequence.current
    setLoading(true); setError('')
    try {
      const result = await api.get(path)
      if (ticket === sequence.current && owner.current === projectId) { setItems(result.data.items ?? []); setToday(result.data.summary?.today ?? '') }
    } catch (failure) { if (ticket === sequence.current) setError(errMsg(failure)) }
    finally { if (ticket === sequence.current) setLoading(false) }
  }
  useEffect(() => {
    setItems([]); setSearch(''); setStatusFilter(undefined); setMine(false); setToday(''); setEditing(null); setCatalogOpen(false); setOwners([]); lock.current = false; setBusy(false); setActionError('')
    void load()
    const current = generation.current
    api.get(`/projects/${encodeURIComponent(projectId)}/people`).then(response => {
      if (current === generation.current && owner.current === projectId) setOwners(Array.isArray(response.data) ? response.data : [])
    }).catch(() => {})
    return () => { sequence.current++; generation.current++ }
  }, [projectId])
  const act = async (operation: () => Promise<unknown>, after?: () => void) => {
    if (lock.current || !writable || error) return
    const ticket = generation.current
    lock.current = true; setBusy(true); setActionError('')
    try {
      await operation()
      if (ticket === generation.current) { after?.(); await load() }
    } catch (failure) { if (ticket === generation.current) setActionError(errMsg(failure)) }
    finally { if (ticket === generation.current) { lock.current = false; setBusy(false) } }
  }
  const open = (row: Procurement | 'new') => {
    form.resetFields(); setActionError(''); setEditing(row); onDirtyChange?.(false)
    form.setFieldsValue(row === 'new' ? { name: '', status: 'not_started', owner_party: 'project', is_required: false, risk: 'low', quantity: 1, unit: '件', spec: '', order_status: '未申请' }
      : { ...row, quantity: row.extra.quantity ?? 1, unit: row.extra.unit ?? '件', spec: row.extra.spec ?? '', order_status: row.extra.order_status ?? '未申请' })
  }
  const save = async () => {
    try { await form.validateFields() } catch { return }
    if (!editing) return
    const values = form.getFieldsValue(true)
    const body: Record<string, unknown> = {}
    const old = editing === 'new' ? null : editing
    for (const key of ['name', 'status', 'owner_id', 'owner_party', 'is_required', 'required_date', 'committed_date', 'forecast_date', 'actual_date', 'risk', 'note']) {
      const value = values[key] ?? (key === 'is_required' ? false : key.endsWith('_date') || key === 'owner_id' ? null : '')
      if (!old || value !== old[key as keyof Procurement]) body[key] = value
    }
    const extraDefaults: Record<string, unknown> = { quantity: 1, unit: '件', spec: '', order_status: '未申请' }
    const extra = Object.fromEntries(['quantity', 'unit', 'spec', 'order_status'].filter(key => !old || values[key] !== (old.extra?.[key] ?? extraDefaults[key])).map(key => [key, values[key]]))
    if (Object.keys(extra).length) body.extra = extra
    if (!old) { body.category = 'procurement'; body.blocks_entry = false }
    await act(() => old ? api.put(`${path}/${encodeURIComponent(old.id)}`, body) : api.post(path, body), () => { setEditing(null); onDirtyChange?.(false) })
  }
  const openCatalog = async () => {
    setActionError(''); setCatalogOpen(true); setCatalogSelection([]); setCatalogQuantities({}); setCatalogError(''); setCatalogBusy(true)
    const ticket = generation.current
    try {
      const result = await api.get(`/templates/${encodeURIComponent(templateId ?? 'default')}/procurements`)
      if (ticket === generation.current) setCatalog(result.data)
    } catch (failure) { if (ticket === generation.current) setCatalogError(errMsg(failure)) }
    finally { if (ticket === generation.current) setCatalogBusy(false) }
  }
  const filtered = items.filter(row => (!mine || row.owner_id === user?.id) && (!statusFilter || row.status === statusFilter) && `${row.name} ${row.extra?.spec ?? ''} ${row.note}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()))
  return <div>
    <Typography.Paragraph type="secondary">采购明细支持资料4.4。数量和到货状态在这里维护，资料本身仍需上传文件提交。</Typography.Paragraph>
    <Space wrap style={{ marginBottom: 12 }}>
      {writable && <><Button disabled={busy || !!error} onClick={() => open('new')}>新增采购项</Button><Button disabled={busy || !!error} onClick={() => void openCatalog()}>从采购库带入</Button></>}
      <Button loading={loading} onClick={() => void load()}>刷新采购</Button>
    </Space>
    {error && <Alert type="error" showIcon message={error} action={<Button onClick={() => void load()}>重新加载后重试</Button>} />}
    {actionError && !editing && !catalogOpen && <Alert type="error" showIcon message={actionError} />}
    <Space wrap style={{ marginBottom: 12 }}><Input.Search aria-label="搜索采购明细" placeholder="名称、规格或备注" value={search} onChange={event => setSearch(event.target.value)} allowClear /><Select aria-label="采购状态" placeholder="全部状态" value={statusFilter} onChange={setStatusFilter} allowClear options={statuses} style={{ minWidth: 130 }} /><Checkbox checked={mine} onChange={event => setMine(event.target.checked)}>我跟进的采购</Checkbox><Typography.Text type="secondary">显示 {filtered.length} / 共 {items.length} 项</Typography.Text></Space>
    <Table<Procurement> rowKey="id" size="small" loading={loading} dataSource={filtered} pagination={{ pageSize: 10 }} scroll={{ x: 660 }} locale={{ emptyText: <Empty description={error ? "采购清单尚未读取" : items.length ? "当前筛选没有采购项" : "尚未添加采购明细"} /> }} columns={[
      { title: '采购项', render: (_, row) => <><Typography.Text strong>{row.name}</Typography.Text><div>{String(row.extra?.spec ?? '')}</div>{row.note && <Typography.Text type="secondary">{row.note}</Typography.Text>}</> },
      { title: '数量', width: 95, render: (_, row) => `${row.extra?.quantity ?? 1} ${row.extra?.unit ?? '件'}` },
      { title: '进展', render: (_, row) => <><Tag>{String(row.extra?.order_status ?? '未申请')}</Tag><div>{statuses.find(item => item.value === row.status)?.label ?? row.status}</div></> },
      { title: '负责人 / 日期', render: (_, row) => <>{row.owner_name || owners.find(person => person.id === row.owner_id)?.display_name || parties.find(party => party.value === row.owner_party)?.label || '未指定'}<div>{row.actual_date ? `到货 ${row.actual_date}` : row.forecast_date ? `预计 ${row.forecast_date}` : row.required_date ? `要求 ${row.required_date}` : ''}</div></> },
      ...(writable ? [{ title: '操作', width: 120, render: (_: unknown, row: Procurement) => <Space><Button size="small" disabled={busy || !!error} onClick={() => open(row)}>编辑</Button><Popconfirm title="删除此采购明细？" onConfirm={() => act(() => api.delete(`${path}/${encodeURIComponent(row.id)}`))}><Button size="small" danger disabled={busy || !!error}>删除</Button></Popconfirm></Space> }] : []),
    ]} />
    <Modal title={editing === 'new' ? '新增采购明细' : '编辑采购明细'} open={editing !== null} onCancel={() => { if (!busy) { setEditing(null); onDirtyChange?.(false) } }} onOk={() => void save()} okText="保存采购" cancelText="取消" confirmLoading={busy} maskClosable={false}>
      <Form form={form} layout="vertical" disabled={busy} onValuesChange={() => onDirtyChange?.(true)}>
        {actionError && <Alert type="error" showIcon message={actionError} />}
        <Form.Item name="name" label="采购名称" rules={[{ required: true, whitespace: true }]}><Input /></Form.Item>
        <Space wrap><Form.Item name="quantity" label="数量" rules={[{ required: true }]}><InputNumber min={0.1} /></Form.Item><Form.Item name="unit" label="单位" rules={[{ required: true }]}><Input /></Form.Item></Space>
        <Form.Item name="spec" label="规格"><Input /></Form.Item>
        <Form.Item name="order_status" label="采购进度"><Select options={orders.map(value => ({ value, label: value }))} /></Form.Item>
        <Form.Item name="status" label="状态"><Select options={statuses} /></Form.Item>
        <Form.Item name="owner_party" label="负责方"><Select options={editing !== 'new' && editing?.owner_party === 'company' ? [...parties, { value: 'company', label: '项目团队（历史）' }] : parties} /></Form.Item>
        <Form.Item name="owner_id" label="内部跟进人"><Select allowClear options={owners.map(person => ({ value: person.id, label: person.display_name }))} /></Form.Item>
        <Space wrap><Form.Item name="required_date" label="要求日期"><Input type="date" /></Form.Item><Form.Item name="committed_date" label="承诺日期"><Input type="date" /></Form.Item></Space>
        <Space wrap><Form.Item name="forecast_date" label="预计到货"><Input type="date" /></Form.Item><Form.Item name="actual_date" label="实际到货" rules={[{ validator: (_, value) => today && value > today ? Promise.reject(new Error(`实际到货不能晚于项目当地今天（${today}）`)) : Promise.resolve() }]}><Input type="date" max={today || undefined} /></Form.Item></Space>
        <Form.Item name="risk" label="风险等级"><Select options={[{ value: 'low', label: '低' }, { value: 'medium', label: '中' }, { value: 'high', label: '高' }]} /></Form.Item>
        <Form.Item name="is_required" label="必需采购项" valuePropName="checked"><Switch /></Form.Item>
        <Form.Item name="note" label="备注"><Input.TextArea rows={2} /></Form.Item>
      </Form>
    </Modal>
    <Modal title="从模板采购库带入" open={catalogOpen} onCancel={() => !busy && setCatalogOpen(false)} okText="带入所选采购" cancelText="取消" confirmLoading={busy} okButtonProps={{ disabled: catalogBusy || !!catalogError || !catalogSelection.length }} onOk={() => act(() => api.post(`${path}/import`, { items: catalogSelection.map(id => ({ item_id: id, quantity: catalogQuantities[id] ?? 1 })) }), () => setCatalogOpen(false))}>
      {actionError && <Alert type="error" showIcon message={actionError} />}
      {catalogError && <Alert type="error" message={catalogError} action={<Button onClick={() => void openCatalog()}>重试采购库</Button>} />}
      <Table rowKey="id" size="small" loading={catalogBusy} dataSource={catalog} pagination={{ pageSize: 8 }} rowSelection={{ selectedRowKeys: catalogSelection, onChange: keys => setCatalogSelection(keys.map(String)), getCheckboxProps: row => ({ disabled: items.some(item => item.name === row.name) }) }} columns={[
        { title: '采购项', dataIndex: 'name' }, { title: '规格', dataIndex: 'spec' },
        { title: '数量', render: (_, row) => <InputNumber aria-label={`${row.name}带入数量`} min={0.1} value={catalogQuantities[row.id] ?? 1} onChange={value => setCatalogQuantities(previous => ({ ...previous, [row.id]: value ?? 1 }))} /> },
      ]} />
    </Modal>
  </div>
}
