import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Empty, Form, Input, InputNumber, Popconfirm, Select, Skeleton, Space, Switch, Tag, Typography, Upload, message } from 'antd'
import { CloseOutlined, DeleteOutlined, DisconnectOutlined, DownloadOutlined, PaperClipOutlined, PlusOutlined, SearchOutlined, UploadOutlined } from '@ant-design/icons'
import { SaveBadge, type SaveState } from './TemplateWorkPanel'
import { api, errMsg } from '../../api/client'

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

/** Document requirements along the stage backbone, edited beside the list: changes to an existing requirement save themselves. */
export default function TemplateDocumentsTab({ templateId, editMode, refreshToken, onChanged }: { templateId: string; editMode: boolean; refreshToken?: unknown; onChanged?: () => unknown }) {
  const [rows, setRows] = useState<Requirement[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [selected, setSelected] = useState<string | 'new' | null>(null)
  const [save, setSave] = useState<SaveState>()
  const [busy, setBusy] = useState(false)
  const sequence = useRef(0)
  const owner = useRef(templateId); owner.current = templateId
  const timer = useRef<ReturnType<typeof setTimeout>>()
  const queue = useRef<Promise<unknown>>(Promise.resolve())
  const selectedRef = useRef<string | null>(null)
  const lastSaved = useRef('')
  const [form] = Form.useForm()
  const kind = Form.useWatch('timing_type', form)
  const group = Form.useWatch('is_group', form)
  const scope = Form.useWatch('scope', form)
  const stage = Form.useWatch('stage_key', form)
  const code = Form.useWatch('code', form)
  const confidential = Form.useWatch('confidential_default', form)
  const neverVisible = Form.useWatch('external_never_visible', form)
  const current = selected && selected !== 'new' ? rows.find(row => row.id === selected) : undefined

  const load = async () => {
    const ticket = ++sequence.current
    setLoading(true); setError(false)
    try {
      const response = await api.get(`/templates/${templateId}/document-requirements`)
      if (ticket === sequence.current && owner.current === templateId) setRows(response.data)
    } catch { if (ticket === sequence.current) { setError(true); setRows([]) } }
    finally { if (ticket === sequence.current) setLoading(false) }
  }
  useEffect(() => {
    selectedRef.current = null; setSelected(null); setSave(undefined); clearTimeout(timer.current); timer.current = undefined
    void load()
    return () => { sequence.current += 1; clearTimeout(timer.current) }
  }, [templateId, refreshToken])
  useEffect(() => { if (["6.11.6b", "6.11.6c"].includes(code)) form.setFieldsValue({ external_never_visible: true, external_visible_default: false }) }, [code])

  const bodyOf = () => {
    const values = form.getFieldsValue(true)
    return Object.fromEntries(FIELDS.map(key => [key, values[key] ?? (['parent_id', 'scope', 'platform', 'timing_type', 'timing_event', 'timing_offset_hours', 'timing_weekday', 'trigger_type'].includes(key) ? null : values[key])]))
  }
  const detail = (err: any) => { const text = err?.response?.data?.detail; return typeof text === 'string' ? text : errMsg(err) }
  const persist = async () => {
    const id = selectedRef.current; const templateAtStart = templateId
    if (!editMode || !id || id === 'new') return
    try { await form.validateFields() } catch { return }
    if (selectedRef.current !== id) return
    const body = bodyOf(); const text = JSON.stringify(body)
    if (text === lastSaved.current) return
    lastSaved.current = text
    queue.current = queue.current.then(async () => {
      setSave({ state: 'saving' })
      try {
        await api.put(`/templates/${templateId}/document-requirements/${id}`, body)
        if (owner.current !== templateAtStart) return
        if (selectedRef.current === id) setSave({ state: 'saved' })
        await load(); void onChanged?.()
      } catch (err) { if (selectedRef.current === id) { lastSaved.current = ''; setSave({ state: 'error', error: detail(err) }) } }
    })
    await queue.current
  }
  const schedule = () => { clearTimeout(timer.current); timer.current = setTimeout(() => { timer.current = undefined; void persist() }, 500) }
  const flush = async () => { if (timer.current) { clearTimeout(timer.current); timer.current = undefined; await persist() } }
  const open = async (row: Requirement | 'new') => {
    await flush()
    setSave(undefined); form.resetFields()
    const values = row === 'new' ? { ...RULE_EMPTY, stage_key: current && current.stage_key !== 'legacy' ? current.stage_key : '6', code: '', name: '', template_no: '', is_group: false, required: true, scope: 'project', platform: null, parent_id: null, timing_type: 'on_demand', confidential_default: false, external_visible_default: false, external_never_visible: false, sort_order: rows.length, note: '' } : row.stage_key === 'legacy' ? { ...row, stage_key: undefined, code: '', parent_id: null } : row
    form.setFieldsValue(values)
    lastSaved.current = row === 'new' ? '' : JSON.stringify(bodyOf())
    selectedRef.current = row === 'new' ? 'new' : row.id
    setSelected(selectedRef.current)
  }
  const close = async () => { await flush(); selectedRef.current = null; setSelected(null) }
  const run = async (operation: () => Promise<any>, success: string, after?: (result: any) => void) => {
    if (busy) return
    setBusy(true)
    try { const result = await operation(); message.success(success); await load(); void onChanged?.(); after?.(result) }
    catch (err) { message.error(detail(err)) } finally { setBusy(false) }
  }
  const create = async () => {
    try { await form.validateFields() } catch { return }
    await run(() => api.post(`/templates/${templateId}/document-requirements`, bodyOf()), '资料要求已添加', result => {
      const id = result?.data?.id
      if (id) { lastSaved.current = JSON.stringify(bodyOf()); selectedRef.current = id; setSelected(id) } else { selectedRef.current = null; setSelected(null) }
    })
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
  const sections = [...STAGES.map(s => ({ key: s.value, title: s.label.replace('全项目周期更新', '全项目周期') })), ...(rows.some(row => row.stage_key === 'legacy') ? [{ key: 'legacy', title: '历史待分类' }] : [])]

  const flags = (row: Requirement) => <>
    {row.stage_key === 'legacy' && <Tag color="orange">历史待分类</Tag>}
    {row.scope === 'vehicle' && <span className="tpl-row-tag">每台车</span>}
    {row.platform && <span className="tpl-row-tag">{row.platform === 'integrated' ? '集成' : row.platform}</span>}
    {!row.is_group && !row.required && <span className="tpl-row-tag">非必需</span>}
    {row.confidential_default && <span className="tpl-row-tag is-warn">保密</span>}
    {row.external_never_visible && <span className="tpl-row-tag">禁止外部查看</span>}
  </>
  const row = (item: Requirement) => <li key={item.id} className={`tpl-node${item.is_group ? ' is-subhead' : ''}${item.parent_id ? ' is-child' : ''}${selected === item.id ? ' is-selected' : ''}`}>
    <button type="button" className="tpl-node-row" aria-current={selected === item.id ? 'true' : undefined} onClick={() => void open(item)}>
      <span className="tpl-code">{item.code}</span>
      <span className="tpl-node-name">{item.name}</span>{flags(item)}
      <span className="tpl-row-meta">
        {!item.is_group && <span className="tpl-meta">{timingLabel(item)}</span>}
        {item.blank_file && <span className="tpl-meta" title={`空白模板：${item.blank_file.filename}`}><PaperClipOutlined aria-label="已有空白模板" /></span>}
      </span>
    </button>
    {item.source_metadata && <details className="tpl-source"><summary>历史来源（只读）</summary><pre>{JSON.stringify(item.source_metadata, null, 2)}</pre></details>}
  </li>

  const panel = selected && (selected === 'new' || current) ? <aside className="tpl-panel" aria-label={selected === 'new' ? '新增资料要求' : `编辑资料要求：${current?.code} ${current?.name}`}>
    <header className="tpl-panel-head">
      <span className="tpl-panel-kicker">{selected === 'new' ? '新增资料要求' : current?.is_group ? '资料分组' : '资料要求'}</span>
      <SaveBadge save={save} />
      <Button type="text" size="small" icon={<CloseOutlined />} aria-label="关闭编辑" onClick={() => void close()} />
    </header>
    <div className="tpl-panel-body">
      <Form form={form} layout="vertical" preserve disabled={!editMode} onValuesChange={() => { if (selected !== 'new') schedule() }}>
          {current?.stage_key === 'legacy' && <Alert type="info" showIcon message="请明确选择第4–9阶段并填写对应编号；历史来源只读保留，不会改写。" style={{ marginBottom: 12 }} />}
          <Form.Item name="stage_key" label="阶段" rules={[{ required: true }]}><Select options={STAGES} onChange={() => form.setFieldValue('parent_id', null)} /></Form.Item>
          <div className="tpl-form-pair"><Form.Item name="code" label="编号" rules={[{ required: true, message: '填写所属阶段的编号，如6.11.1a' }]}><Input maxLength={40} placeholder="如6.11.1a" /></Form.Item><Form.Item name="name" label="资料名称" rules={[{ required: true, whitespace: true }]}><Input maxLength={300} /></Form.Item></div>
          <Form.Item name="is_group" label="作为分组标题" valuePropName="checked"><Switch onChange={value => form.setFieldsValue(value ? { ...RULE_EMPTY, scope: null, required: false } : { scope: 'project', required: true, timing_type: 'on_demand' })} /></Form.Item>
          <Form.Item name="parent_id" label="父分组"><Select allowClear options={rows.filter(row => row.is_group && row.stage_key === stage && row.id !== current?.id).map(row => ({ value: row.id, label: `${row.code} ${row.name}` }))} /></Form.Item>
          {!group && <>
            <Form.Item name="template_no" label="模板编号或示例标识"><Input maxLength={100} placeholder="如模板16" /></Form.Item>
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
          <Form.Item name="note" label="说明"><Input.TextArea autoSize={{ minRows: 2, maxRows: 8 }} maxLength={5000} /></Form.Item>
        </Form>
      {current && !current.is_group && <div className="tpl-blank">
        <span className="tpl-blank-label">空白模板</span>
        {current.blank_file ? <Button type="link" size="small" icon={<DownloadOutlined />} onClick={() => void download(current)}>{current.blank_file.filename}</Button> : <span className="tpl-blank-none">尚未上传</span>}
        {editMode && <Upload showUploadList={false} disabled={busy} beforeUpload={file => { const data = new FormData(); data.append('file', file); void run(() => api.post(`/templates/${templateId}/document-requirements/${current.id}/blank-file`, data), '空白模板已上传'); return false }}>
          <Button size="small" icon={<UploadOutlined />} disabled={busy}>{current.blank_file ? `替换空白模板${current.code}` : `上传空白模板${current.code}`}</Button>
        </Upload>}
        {editMode && current.blank_file && <Popconfirm title="移除当前空白模板引用？历史版本保留。" okText="移除" cancelText="取消" onConfirm={() => run(() => api.delete(`/templates/${templateId}/document-requirements/${current.id}/blank-file`), '已移除引用')}>
          <Button size="small" type="text" danger icon={<DisconnectOutlined />} disabled={busy}>移除</Button>
        </Popconfirm>}
      </div>}
    </div>
    {editMode && <footer className="tpl-panel-foot">
      {selected === 'new' ? <Button type="primary" icon={<PlusOutlined />} loading={busy} onClick={() => void create()}>添加资料要求</Button>
        : <Popconfirm title={current?.is_group ? '删除此分组？' : '删除此资料要求？'} description="既有项目与历史文件保留。" okText="删除" okButtonProps={{ danger: true }} cancelText="取消"
          onConfirm={() => run(() => api.delete(`/templates/${templateId}/document-requirements/${current!.id}`), '资料要求已删除', () => { selectedRef.current = null; setSelected(null) })}>
          <Button danger type="text" icon={<DeleteOutlined />} disabled={busy}>{current?.is_group ? '删除分组' : '删除资料要求'}</Button>
        </Popconfirm>}
    </footer>}
  </aside> : <aside className="tpl-panel is-empty" aria-label="编辑说明">
    <p><strong>点左边任意一份资料开始编辑</strong></p>
    <ul><li>改动会自动保存，不需要点保存。</li><li>同一阶段按编号排列；分组下的资料自动缩进。</li>{editMode && <li>“新增资料要求”在右侧填写后点“添加”。</li>}</ul>
  </aside>

  return <div className={`tpl-split${selected ? ' has-panel' : ''}`}>
    <div className="tpl-split-main">
      <div className="tpl-toolbar">
        <Input allowClear prefix={<SearchOutlined />} aria-label="搜索资料要求" placeholder="搜编号、资料名称或模板编号" value={keyword} onChange={e => setKeyword(e.target.value)} />
        {editMode && <Button icon={<PlusOutlined />} onClick={() => void open('new')} disabled={busy}>新增资料要求</Button>}
      </div>
      {error ? <Alert type="error" message="资料要求加载失败" action={<Button onClick={() => void load()}>重试</Button>} />
        : loading && !rows.length ? <Skeleton active paragraph={{ rows: 6 }} />
        : !rows.length ? <Empty description="此模板尚未配置资料要求" />
        : term && !shown.length ? <Empty description="没有匹配的资料要求" />
        : <div className="tpl-outline-body">{sections.map(section => {
          const list = shown.filter(item => item.stage_key === section.key)
          if (term && !list.length) return null
          const count = list.filter(item => !item.is_group).length
          return <section key={section.key} className="tpl-stage-section" aria-label={section.title}>
            <header className="tpl-stage-head"><h3><span className="tpl-stage-key">{section.key === 'legacy' ? '?' : section.key}</span>{section.title.replace(/^\d · /, '')}</h3><span className="tpl-stage-meta">{count ? `${count} 份` : '暂无资料'}</span></header>
            {!!list.length && <ul className="tpl-nodes">{list.map(row)}</ul>}
          </section>
        })}</div>}
    </div>
    {panel}
  </div>
}
