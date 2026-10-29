import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Dropdown, Empty, Form, Input, InputNumber, Modal, Select, Skeleton, Space, Switch, Tag, Typography, message } from 'antd'
import { DeleteOutlined, DisconnectOutlined, DownloadOutlined, EditOutlined, MoreOutlined, PaperClipOutlined, PlusOutlined, SearchOutlined, UploadOutlined } from '@ant-design/icons'
import { stageLabel } from '../../constants/stages'
import { StageOutline, StageSection, outlineStages } from './TemplateOutline'
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

/** Document requirements along the stage backbone; a row opens its rule, file and delete actions sit in one menu. */
export default function TemplateDocumentsTab({ templateId, editMode, refreshToken, onChanged }: { templateId: string; editMode: boolean; refreshToken?: unknown; onChanged?: () => unknown }) {
  const [rows, setRows] = useState<Requirement[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(false)
  const [keyword, setKeyword] = useState('')
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
    form.setFieldsValue(row === 'new' ? { ...RULE_EMPTY, stage_key: '6', code: '', name: '', template_no: '', is_group: false, required: true, scope: 'project', platform: null, parent_id: null, timing_type: 'on_demand', confidential_default: false, external_visible_default: false, external_never_visible: false, sort_order: rows.length, note: '' } : row.stage_key === 'legacy' ? { ...row, stage_key: undefined, code: '', parent_id: null } : row)
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
  const eventOptions = Object.entries(EVENTS).filter(([key]) => kind === 'after_milestone' ? MILESTONES.includes(key) : key !== 'vehicle_arrival' || (kind === 'after_event' && scope === 'vehicle')).map(([value, label]) => ({ value, label }))
  const term = keyword.trim().toLowerCase()
  const hit = (row: Requirement) => !term || `${row.code} ${row.name} ${row.template_no}`.toLowerCase().includes(term)
  const parentsOfHits = new Set(rows.filter(row => !row.is_group && hit(row)).map(row => row.parent_id))
  const shown = rows.filter(row => row.is_group ? hit(row) || parentsOfHits.has(row.id) : hit(row))
  const counts: Record<string, number> = {}
  for (const row of shown) if (!row.is_group) counts[row.stage_key] = (counts[row.stage_key] ?? 0) + 1
  const hasLegacy = rows.some(row => row.stage_key === 'legacy')
  const stages = outlineStages(counts, hasLegacy ? [{ key: 'legacy', name: '历史待分类', count: counts.legacy ?? 0 }] : [])
  const uploadInput = useRef<HTMLInputElement>(null)
  const uploadFor = useRef<Requirement>()
  const remove = (row: Requirement) => Modal.confirm({ title: row.is_group ? `删除分组「${row.name}」？` : `删除资料要求「${row.code} ${row.name}」？`, content: '既有项目与历史文件保留。', okText: '删除', okButtonProps: { danger: true }, cancelText: '取消',
    onOk: () => act(() => api.delete(`/templates/${templateId}/document-requirements/${row.id}`), '资料要求已删除') })
  const rowMenu = (row: Requirement) => {
    const items = [
      ...(row.blank_file ? [{ key: 'download', icon: <DownloadOutlined />, label: `下载空白模板（${row.blank_file.filename}）` }] : []),
      ...(editMode && !row.is_group ? [{ key: 'upload', icon: <UploadOutlined />, label: row.blank_file ? '替换空白模板' : '上传空白模板' }] : []),
      ...(editMode && row.blank_file ? [{ key: 'unlink', icon: <DisconnectOutlined />, label: '移除空白模板引用', danger: true }] : []),
      ...(editMode ? [{ key: 'edit', icon: <EditOutlined />, label: row.is_group ? '编辑分组' : '编辑' }, { type: 'divider' as const }, { key: 'delete', icon: <DeleteOutlined />, label: row.is_group ? '删除分组' : '删除资料要求', danger: true }] : []),
    ]
    if (!items.length) return null
    return <Dropdown trigger={['click']} disabled={busy} menu={{ items, onClick: ({ key }) => {
      if (key === 'download') void download(row)
      if (key === 'upload') { uploadFor.current = row; uploadInput.current?.click() }
      if (key === 'unlink') Modal.confirm({ title: '移除当前空白模板引用？', content: '历史版本保留。', okText: '移除', cancelText: '取消', onOk: () => act(() => api.delete(`/templates/${templateId}/document-requirements/${row.id}/blank-file`), '已移除引用') })
      if (key === 'edit') open(row)
      if (key === 'delete') remove(row)
    } }}><IconAction label={`资料${row.code}操作`} icon={<MoreOutlined />} /></Dropdown>
  }
  const flags = (row: Requirement) => <>
    {row.stage_key === 'legacy' && <Tag color="orange">历史待分类</Tag>}
    {row.scope === 'vehicle' && <span className="tpl-row-tag">每台车</span>}
    {row.platform && <span className="tpl-row-tag">{row.platform === 'integrated' ? '集成' : row.platform}</span>}
    {!row.required && <span className="tpl-row-tag">非必需</span>}
    {row.confidential_default && <span className="tpl-row-tag is-warn">保密</span>}
    {row.external_never_visible && <span className="tpl-row-tag">禁止外部查看</span>}
    {row.external_visible_default && <span className="tpl-row-tag">对外可见</span>}
  </>
  const requirementRow = (row: Requirement) => {
    if (row.is_group) return <li key={row.id} className="tpl-subhead">
      <span className="tpl-code">{row.code}</span><strong>{row.name}</strong><span className="tpl-group-count">{shown.filter(child => child.parent_id === row.id).length}</span>{rowMenu(row)}
    </li>
    const body = <>
      <span className="tpl-row-title"><span className="tpl-code">{row.code}</span><span className="tpl-row-name">{row.name}</span>{flags(row)}</span>
      <span className="tpl-row-meta">
        {row.template_no && <span className="tpl-meta">{row.template_no}</span>}
        <span className="tpl-meta">{timingLabel(row)}</span>
        {row.blank_file && <span className="tpl-meta" title={`空白模板：${row.blank_file.filename}`}><PaperClipOutlined aria-label="已有空白模板" /></span>}
      </span>
      {row.note && <span className="tpl-row-note">{row.note}</span>}
    </>
    return <li key={row.id} className={row.parent_id ? 'is-child' : undefined}>
      <div className="tpl-row-line">
        {editMode ? <button type="button" className="tpl-row" disabled={busy} onClick={() => open(row)}>{body}</button> : <div className="tpl-row is-static">{body}</div>}
        {rowMenu(row)}
      </div>
      {row.source_metadata && <details className="tpl-source"><summary>历史来源（只读）</summary><pre>{JSON.stringify(row.source_metadata, null, 2)}</pre></details>}
    </li>
  }

  return <div className="tpl-tab">
    <div className="tpl-toolbar">
      <Input allowClear prefix={<SearchOutlined />} aria-label="搜索资料要求" placeholder="搜编号、资料名称或模板编号" value={keyword} onChange={e => setKeyword(e.target.value)} />
      {editMode && <Button type="primary" icon={<PlusOutlined />} onClick={() => open('new')} disabled={busy}>新增资料要求</Button>}
    </div>
    <input ref={uploadInput} type="file" hidden aria-hidden="true" onChange={event => {
      const file = event.target.files?.[0]; const row = uploadFor.current; event.target.value = ''
      if (!file || !row) return
      const data = new FormData(); data.append('file', file)
      void act(() => api.post(`/templates/${templateId}/document-requirements/${row.id}/blank-file`, data), '空白模板已上传')
    }} />
    {error ? <Alert type="error" message="资料要求加载失败" action={<Button onClick={() => void load()}>重试</Button>} />
      : loading && !rows.length ? <Skeleton active paragraph={{ rows: 6 }} />
      : !rows.length ? <Empty description="此模板尚未配置资料要求" />
      : term && !shown.length ? <Empty description="没有匹配的资料要求" />
      : <StageOutline id="tpl-docs" label="资料" unit="份资料" stages={stages}>
        {stages.map(stage => {
          const list = shown.filter(row => row.stage_key === stage.key)
          if (term && !list.length) return null
          return <StageSection key={stage.key} outlineId="tpl-docs" stage={stage.key} title={stage.key === 'legacy' ? '历史待分类' : stageLabel(stage.key)} meta={stage.count ? `${stage.count} 份` : '暂无资料'}>
            {!!list.length && <ul className="tpl-list tpl-doc-list">{list.map(requirementRow)}</ul>}
          </StageSection>
        })}
      </StageOutline>}
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
