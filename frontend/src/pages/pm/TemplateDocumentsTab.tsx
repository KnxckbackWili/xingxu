import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Empty, Form, Input, InputNumber, Modal, Popconfirm, Select, Skeleton, Space, Switch, Tag, Typography, Upload, message } from 'antd'
import { DeleteOutlined, DisconnectOutlined, DownloadOutlined, EditOutlined, PlusOutlined, UploadOutlined } from '@ant-design/icons'
import { IconAction } from '../../components/IconAction'
import { api } from '../../api/client'

const STAGES = [{ value: '4', label: '4 · 内部启动会' }, { value: '5', label: '5 · 发车前' }, { value: '6', label: '6 · 实施' }, { value: '7', label: '7 · 验收' }, { value: '8', label: '8 · 交付' }, { value: '9', label: '9 · 全项目周期更新' }]
const TIMINGS: Record<string, string> = { before_event: '事件发生前', after_event: '事件发生后', weekly: '每周', on_trigger: '事件触发', after_milestone: '里程碑完成后', on_demand: '按需抽查', lifetime: '全项目周期更新' }
const EVENTS: Record<string, string> = { internal_kickoff: '内部启动会', ship: '发车', arrival_all: '全部到场', vehicle_arrival: '该车到场', delivery_signed: '到货签收', commissioning_done: '调试完工', go_live: '上线运行', training_done: '培训完成', acceptance: '项目验收', handover: '交付售后' }
const MILESTONES = ['delivery_signed', 'commissioning_done', 'go_live', 'training_done', 'acceptance', 'handover']
const TRIGGERS: Record<string, string> = { accident: '事故', quality: '质量问题', member_leave: '人员离开项目' }
const WEEKDAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
const RULE_EMPTY = { timing_type: null, timing_event: null, timing_offset_hours: null, timing_weekday: null, trigger_type: null }
const FIELDS = ['stage_key', 'code', 'name', 'template_no', 'is_group', 'parent_id', 'required', 'scope', 'platform', 'timing_type', 'timing_event', 'timing_offset_hours', 'timing_weekday', 'trigger_type', 'confidential_default', 'external_visible_default', 'external_never_visible', 'sort_order', 'note']

interface BlankFile { id: string; filename: string; file_size: number; sha256: string }
interface Requirement { id: string; stage_key: string; code: string; name: string; template_no: string; is_group: boolean; parent_id: string | null; parent_code: string | null; required: boolean; scope: string | null; platform: string | null; timing_type: string | null; timing_event: string | null; timing_offset_hours: number | null; timing_weekday: number | null; trigger_type: string | null; confidential_default: boolean; external_visible_default: boolean; external_never_visible: boolean; sort_order: number; note: string; blank_file: BlankFile | null; source_metadata?: Record<string, unknown> | null }

export function timingLabel(row: Requirement) {
  if (row.stage_key === 'legacy') return '历史待分类，输出规则待确认'
  if (row.is_group) return '分组'
  if (row.timing_type === 'weekly') return `每周${WEEKDAYS[(row.timing_weekday ?? 1) - 1].slice(1)}`
  if (row.timing_type === 'on_demand') return '按需抽查'
  if (row.timing_type === 'lifetime') return '内部启动会建档，归档前提交'
  if (row.timing_type === 'on_trigger') return `${TRIGGERS[row.trigger_type ?? '']}后 ${row.timing_offset_hours} 小时`
  return `${EVENTS[row.timing_event ?? ''] ?? ''}${row.timing_type === 'before_event' ? '前' : '后'} ${row.timing_offset_hours} 小时`
}

/** With stageKey the list is pinned to one stage of the template backbone (historical unclassified rows stay visible below). */
export default function TemplateDocumentsTab({ templateId, editMode, refreshToken, stageKey, onChanged }: { templateId: string; editMode: boolean; refreshToken?: unknown; stageKey?: string; onChanged?: () => unknown }) {
  const [rows, setRows] = useState<Requirement[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [stageFilter, setStageFilter] = useState<string>()
  const [editing, setEditing] = useState<Requirement | 'new' | null>(null)
  const [busy, setBusy] = useState(false)
  const sequence = useRef(0)
  const mutation = useRef(0)
  const busyRef = useRef(false)
  const current = useRef(templateId)
  current.current = templateId
  const [form] = Form.useForm()
  const kind = Form.useWatch('timing_type', form)
  const group = Form.useWatch('is_group', form)
  const scope = Form.useWatch('scope', form)
  const stage = Form.useWatch('stage_key', form)
  const code = Form.useWatch('code', form)
  const confidential = Form.useWatch('confidential_default', form)
  const neverVisible = Form.useWatch('external_never_visible', form)

  const load = async () => {
    const ticket = ++sequence.current
    setLoading(true); setError(false)
    try {
      const response = await api.get(`/templates/${templateId}/document-requirements`)
      if (ticket === sequence.current && current.current === templateId) setRows(response.data)
    } catch { if (ticket === sequence.current) { setError(true); setRows([]) } }
    finally { if (ticket === sequence.current) setLoading(false) }
  }
  useEffect(() => {
    setEditing(null); setBusy(false); busyRef.current = false; mutation.current += 1
    void load()
    return () => { sequence.current += 1; mutation.current += 1 }
  }, [templateId, refreshToken])
  useEffect(() => { if (!editMode) setEditing(null) }, [editMode])
  useEffect(() => { if (["6.11.6b", "6.11.6c"].includes(code)) form.setFieldsValue({ external_never_visible: true, external_visible_default: false }) }, [code])

  const act = async (operation: () => Promise<unknown>, success: string) => {
    if (busyRef.current) return
    busyRef.current = true
    const ticket = ++mutation.current
    const owner = templateId
    setBusy(true)
    try {
      await operation()
      if (ticket === mutation.current && owner === current.current) { message.success(success); setEditing(null); await load(); void onChanged?.() }
    } catch (err: any) {
      if (ticket === mutation.current) { const detail = err.response?.data?.detail; message.error(typeof detail === 'string' ? detail : '操作未完成，请检查输入后重试') }
    } finally { if (ticket === mutation.current) { busyRef.current = false; setBusy(false) } }
  }
  const open = (row: Requirement | 'new') => {
    form.resetFields()
    form.setFieldsValue(row === 'new' ? { ...RULE_EMPTY, stage_key: stageKey ?? (STAGES.some(stage => stage.value === stageFilter) ? stageFilter : '6'), code: '', name: '', template_no: '', is_group: false, required: true, scope: 'project', platform: null, parent_id: null, timing_type: 'on_demand', confidential_default: false, external_visible_default: false, external_never_visible: false, sort_order: rows.length, note: '' } : row.stage_key === 'legacy' ? { ...row, stage_key: undefined, code: '', parent_id: null } : row)
    setEditing(row)
  }
  const save = async () => {
    try { await form.validateFields() } catch { return }
    const values = form.getFieldsValue(true)
    const body = Object.fromEntries(FIELDS.map(key => [key, values[key] ?? (['parent_id', 'scope', 'platform', 'timing_type', 'timing_event', 'timing_offset_hours', 'timing_weekday', 'trigger_type'].includes(key) ? null : values[key])]))
    const path = `/templates/${templateId}/document-requirements`
    await act(() => editing === 'new' ? api.post(path, body) : api.put(`${path}/${(editing as Requirement).id}`, body), '资料要求已保存')
  }
  const download = async (row: Requirement) => {
    try {
      const result = await api.get(`/templates/${templateId}/document-requirements/${row.id}/blank-file`, { responseType: 'blob' })
      const url = URL.createObjectURL(result.data)
      const link = document.createElement('a'); link.href = url; link.download = row.blank_file?.filename ?? '空白模板'; link.click(); URL.revokeObjectURL(url)
    } catch { message.error('空白模板下载失败，请重试或联系管理员核对文件') }
  }
  const activeStage = stageKey ?? stageFilter
  const filtered = rows.filter(row => (!activeStage || row.stage_key === activeStage || (!!stageKey && row.stage_key === 'legacy')) && `${row.code} ${row.name} ${row.template_no}`.toLowerCase().includes(keyword.toLowerCase()))
  const eventOptions = Object.entries(EVENTS).filter(([key]) => kind === 'after_milestone' ? MILESTONES.includes(key) : key !== 'vehicle_arrival' || (kind === 'after_event' && scope === 'vehicle')).map(([value, label]) => ({ value, label }))

  const stageLabel = (key: string) => key === 'legacy' ? '历史待分类' : STAGES.find(stage => stage.value === key)?.label ?? `第${key}阶段`
  const stageKeys = [...STAGES.map(stage => stage.value), 'legacy'].filter(key => rows.some(row => row.stage_key === key))
  const count = (key: string) => rows.filter(row => row.stage_key === key && !row.is_group).length
  const blankActions = (row: Requirement) => editMode && !row.is_group && <>
    <Upload showUploadList={false} disabled={busy} beforeUpload={file => { const data = new FormData(); data.append('file', file); void act(() => api.post(`/templates/${templateId}/document-requirements/${row.id}/blank-file`, data), '空白模板已上传'); return false }}>
      <IconAction label={row.blank_file ? `替换空白模板${row.code}` : `上传空白模板${row.code}`} icon={<UploadOutlined />} disabled={busy} />
    </Upload>
    {row.blank_file && <Popconfirm title="移除当前空白模板引用？历史版本保留。" onConfirm={() => act(() => api.delete(`/templates/${templateId}/document-requirements/${row.id}/blank-file`), '已移除引用')}>
      <IconAction label={`移除空白模板${row.code}`} icon={<DisconnectOutlined />} danger disabled={busy} />
    </Popconfirm>}
  </>
  const requirementRow = (row: Requirement) => row.is_group
    ? <li key={row.id} className="template-doc-group"><span className="template-doc-code">{row.code}</span><strong>{row.name}</strong>
      {editMode && <span className="row-icon-actions"><IconAction label={`编辑资料${row.code}`} icon={<EditOutlined />} onClick={() => open(row)} disabled={busy} />
        <Popconfirm title="删除此分组？既有项目与历史文件保留。" onConfirm={() => act(() => api.delete(`/templates/${templateId}/document-requirements/${row.id}`), '资料要求已删除')}><IconAction label={`删除资料${row.code}`} icon={<DeleteOutlined />} danger disabled={busy} /></Popconfirm></span>}</li>
    : <li key={row.id} className={`template-doc-row${row.parent_code ? ' is-child' : ''}`}>
      <div className="template-doc-main">
        <span className="template-doc-title"><span className="template-doc-code">{row.code}</span>{row.name}{row.stage_key === 'legacy' && <Tag color="orange">历史待分类</Tag>}</span>
        <span className="template-doc-meta">
          <span>{timingLabel(row)}</span>
          {row.scope === 'vehicle' && <span>每台车</span>}
          {row.platform && <span>{row.platform === 'integrated' ? '集成' : row.platform}</span>}
          {row.template_no && <span>{row.template_no}</span>}
          {row.required ? <Tag color="blue">必需</Tag> : <Tag>非必需</Tag>}
          {row.confidential_default && <Tag color="orange">默认保密</Tag>}
          {row.external_never_visible && <Tag>禁止外部查看</Tag>}
          {row.external_visible_default && <Tag>默认对外可见</Tag>}
        </span>
        {row.note && <Typography.Text type="secondary" className="template-doc-note">{row.note}</Typography.Text>}
        {row.source_metadata && <details><summary>历史来源（只读）</summary><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxHeight: 180, overflow: 'auto' }}>{JSON.stringify(row.source_metadata, null, 2)}</pre></details>}
      </div>
      {row.blank_file && <Button type="link" size="small" className="template-doc-blank" icon={<DownloadOutlined />} onClick={() => void download(row)}>{row.blank_file.filename}</Button>}
      <span className="row-icon-actions">
        {blankActions(row)}
        {editMode && <IconAction label={`${row.stage_key === 'legacy' ? '分类历史资料' : '编辑资料'}${row.code}`} icon={<EditOutlined />} onClick={() => open(row)} disabled={busy} />}
        {editMode && <Popconfirm title="删除此资料要求？既有项目与历史文件保留。" onConfirm={() => act(() => api.delete(`/templates/${templateId}/document-requirements/${row.id}`), '资料要求已删除')}><IconAction label={`删除资料${row.code}`} icon={<DeleteOutlined />} danger disabled={busy} /></Popconfirm>}
      </span>
    </li>

  return <div className="template-docs">
    <div className="template-work-toolbar">
      <Input.Search aria-label="搜索资料要求" allowClear placeholder="搜编号、资料或模板编号" value={keyword} onChange={e => setKeyword(e.target.value)} />
      {editMode && <Button type="primary" icon={<PlusOutlined />} onClick={() => open('new')} disabled={busy}>新增资料要求</Button>}
    </div>
    {!stageKey && <div className="template-stage-chips" role="group" aria-label="筛选资料阶段">
      <button type="button" aria-pressed={!stageFilter} onClick={() => setStageFilter(undefined)}>全部 {rows.filter(row => !row.is_group).length}</button>
      {stageKeys.map(key => <button key={key} type="button" aria-pressed={stageFilter === key} onClick={() => setStageFilter(key)}>{stageLabel(key)} {count(key)}</button>)}
    </div>}
    {error ? <Alert type="error" message="资料要求加载失败" action={<Button onClick={() => void load()}>重试</Button>} />
      : loading && !rows.length ? <Skeleton active paragraph={{ rows: 6 }} />
      : !filtered.length ? <Empty description={stageKey ? (keyword ? '本阶段没有匹配的资料要求' : '本阶段还没有资料要求') : rows.length ? '没有匹配的资料要求' : '此模板尚未配置资料要求'} />
      : <div className="template-doc-stages">{stageKeys.filter(key => filtered.some(row => row.stage_key === key)).map(key => <section key={key} aria-label={stageLabel(key)}>
        {(!stageKey || key === 'legacy') && <h3>{stageLabel(key)}<Typography.Text type="secondary">{filtered.filter(row => row.stage_key === key && !row.is_group).length} 项</Typography.Text></h3>}
        <ul>{filtered.filter(row => row.stage_key === key).map(requirementRow)}</ul>
      </section>)}</div>}
    <Modal title={editing === 'new' ? '新增资料要求' : '编辑资料要求'} open={editing !== null} onCancel={() => !busy && setEditing(null)} onOk={() => void save()} confirmLoading={busy} okText="保存" cancelText="取消" width={700} destroyOnHidden>
      <Form form={form} layout="vertical" preserve>
        {editing && editing !== 'new' && editing.stage_key === 'legacy' && <Alert type="info" showIcon message="请明确选择第4–9阶段并填写对应编号；历史来源只读保留，不会改写。" style={{ marginBottom: 12 }} />}
        <Form.Item name="stage_key" label="阶段" rules={[{ required: true }]}><Select options={STAGES} onChange={() => form.setFieldValue('parent_id', null)} /></Form.Item>
        <Space wrap align="start" style={{ display: 'flex' }}><Form.Item name="code" label="编号" rules={[{ required: true, message: '填写所属阶段的编号，如6.11.1a' }]}><Input maxLength={40} placeholder="如6.11.1a" /></Form.Item><Form.Item name="name" label="资料名称" rules={[{ required: true, whitespace: true }]}><Input maxLength={300} style={{ width: 'min(350px, 75vw)' }} /></Form.Item></Space>
        <Form.Item name="is_group" label="作为分组标题" valuePropName="checked"><Switch onChange={value => form.setFieldsValue(value ? { ...RULE_EMPTY, scope: null, required: false } : { scope: 'project', required: true, timing_type: 'on_demand' })} /></Form.Item>
        <Form.Item name="parent_id" label="父分组"><Select allowClear options={rows.filter(row => row.is_group && row.stage_key === stage && row.id !== (editing === 'new' ? '' : editing?.id)).map(row => ({ value: row.id, label: `${row.code} ${row.name}` }))} /></Form.Item>
        {!group && <>
          <Form.Item name="template_no" label="模板编号或示例标识"><Input maxLength={100} placeholder="如模板16；空白文件可在列表上传" /></Form.Item>
          <Space wrap align="start"><Form.Item name="scope" label="资料范围" rules={[{ required: true }]}><Select style={{ width: 180 }} options={[{ value: 'project', label: '项目一份' }, { value: 'vehicle', label: '每台车一份' }]} onChange={value => { if (value !== 'vehicle' && form.getFieldValue('timing_event') === 'vehicle_arrival') form.setFieldValue('timing_event', null) }} /></Form.Item><Form.Item name="platform" label="适用平台"><Select allowClear placeholder="全部平台" style={{ width: 180 }} options={[{ value: 'NDC', label: 'NDC' }, { value: 'GRACE', label: 'GRACE' }, { value: 'integrated', label: '集成' }]} /></Form.Item><Form.Item name="required" label="必须提交" valuePropName="checked"><Switch /></Form.Item></Space>
          <Form.Item name="timing_type" label="输出时机" rules={[{ required: true }]}><Select options={Object.entries(TIMINGS).map(([value, label]) => ({ value, label }))} onChange={value => form.setFieldsValue({ ...RULE_EMPTY, timing_type: value, ...(value === 'lifetime' ? { timing_event: 'internal_kickoff' } : ['before_event', 'after_event', 'after_milestone', 'on_trigger'].includes(value) ? { timing_offset_hours: 0 } : {}) })} /></Form.Item>
          {['before_event', 'after_event', 'after_milestone'].includes(kind) && <Form.Item name="timing_event" label="关键事件" rules={[{ required: true }]}><Select options={eventOptions} /></Form.Item>}
          {['before_event', 'after_event', 'after_milestone', 'on_trigger'].includes(kind) && <Form.Item name="timing_offset_hours" label="偏移小时" rules={[{ required: true }]}><InputNumber min={0} max={876000} precision={0} /></Form.Item>}
          {kind === 'weekly' && <Form.Item name="timing_weekday" label="每周截止星期" rules={[{ required: true, message: '每周规则必须选择星期' }]}><Select options={WEEKDAYS.map((label, index) => ({ value: index + 1, label }))} /></Form.Item>}
          {kind === 'on_trigger' && <Form.Item name="trigger_type" label="触发类型" rules={[{ required: true }]}><Select options={Object.entries(TRIGGERS).map(([value, label]) => ({ value, label }))} /></Form.Item>}
          {kind === 'lifetime' && <Typography.Paragraph type="secondary">内部启动会建档，之后按需更新；归档前必须提交。</Typography.Paragraph>}
          <Form.Item name="confidential_default" label="默认保密" valuePropName="checked"><Switch onChange={value => value && form.setFieldValue('external_visible_default', false)} /></Form.Item>
          <Form.Item name="external_never_visible" label="禁止外部查看" valuePropName="checked"><Switch onChange={value => value && form.setFieldValue('external_visible_default', false)} disabled={['6.11.6b', '6.11.6c'].includes(code)} /></Form.Item>
          <Form.Item name="external_visible_default" label="默认对外可见" valuePropName="checked"><Switch disabled={confidential || neverVisible} /></Form.Item>
        </>}
        <Form.Item name="sort_order" label="排序" rules={[{ required: true }]}><InputNumber min={0} max={100000} precision={0} /></Form.Item>
        <Form.Item name="note" label="说明"><Input.TextArea rows={3} maxLength={5000} /></Form.Item>
      </Form>
    </Modal>
  </div>
}
