import { useEffect, useRef, useState, type MutableRefObject } from 'react'
import { Alert, Button, Form, Input, InputNumber, Popconfirm, Select, Space, Switch, Tag, Upload, message } from 'antd'
import { CloseOutlined, DeleteOutlined, DisconnectOutlined, DownloadOutlined, PlusOutlined, UploadOutlined } from '@ant-design/icons'
import { SaveBadge, type SaveState } from './TemplateWorkPanel'
import { api, errMsg } from '../../api/client'

export const DOC_STAGES = [{ value: '4', label: '内部启动会' }, { value: '5', label: '发车前' }, { value: '6', label: '实施' }, { value: '7', label: '验收' }, { value: '8', label: '交付' }, { value: '9', label: '全项目周期' }]
const TIMINGS: Record<string, string> = { on_demand: '需要时交（无固定截止）', weekly: '每周交', before_event: '某个事件之前', after_event: '某个事件之后', after_milestone: '某个节点完成后', on_trigger: '发生某种情况后', lifetime: '整个项目期间更新，归档前交' }
// Offsets are stored in hours; people think in days.
const days = (hours: number | null | undefined) => hours == null ? null : Math.round(hours / 24 * 100) / 100
const offsetText = (hours: number | null | undefined) => !hours ? '' : hours % 24 === 0 ? ` ${hours / 24} 天` : ` ${hours} 小时`
const EVENTS: Record<string, string> = { internal_kickoff: '内部启动会', ship: '发车', arrival_all: '全部到场', vehicle_arrival: '该车到场', delivery_signed: '到货签收', commissioning_done: '调试完工', go_live: '上线运行', training_done: '培训完成', acceptance: '项目验收', handover: '交付售后' }
const MILESTONES = ['delivery_signed', 'commissioning_done', 'go_live', 'training_done', 'acceptance', 'handover']
const TRIGGERS: Record<string, string> = { accident: '事故', quality: '质量问题', member_leave: '人员离开项目' }
const WEEKDAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
const RULE_EMPTY = { timing_type: null, timing_event: null, timing_offset_hours: null, timing_weekday: null, trigger_type: null }
const FIELDS = ['stage_key', 'code', 'name', 'template_no', 'is_group', 'parent_id', 'required', 'scope', 'platform', 'timing_type', 'timing_event', 'timing_offset_hours', 'timing_weekday', 'trigger_type', 'confidential_default', 'external_visible_default', 'external_never_visible', 'sort_order', 'note']

interface BlankFile { id: string; filename: string; file_size: number; sha256: string }
export interface Requirement { id: string; stage_key: string; code: string; name: string; template_no: string; is_group: boolean; parent_id: string | null; parent_code: string | null; required: boolean; scope: string | null; platform: string | null; timing_type: string | null; timing_event: string | null; timing_offset_hours: number | null; timing_weekday: number | null; trigger_type: string | null; confidential_default: boolean; external_visible_default: boolean; external_never_visible: boolean; sort_order: number; note: string; blank_file: BlankFile | null; source_metadata?: Record<string, unknown> | null }

export function timingLabel(row: Requirement) {
  if (row.stage_key === 'legacy') return '历史待分类，输出规则待确认'
  if (row.is_group) return '分组'
  if (row.timing_type === 'weekly') return `每周${WEEKDAYS[(row.timing_weekday ?? 1) - 1].slice(1)}`
  if (row.timing_type === 'on_demand') return '需要时交'
  if (row.timing_type === 'lifetime') return '项目期间更新，归档前交'
  const event = row.timing_type === 'on_trigger' ? TRIGGERS[row.trigger_type ?? ''] ?? '' : EVENTS[row.timing_event ?? ''] ?? ''
  if (!row.timing_offset_hours) return `${event}时`
  return `${event}${row.timing_type === 'before_event' ? '前' : '后'}${offsetText(row.timing_offset_hours)}`
}

/** Small tags shown on a document row in the outline. */
export const docFlags = (row: Requirement) => <>
  {row.stage_key === 'legacy' && <Tag color="orange">历史待分类</Tag>}
  {row.scope === 'vehicle' && <span className="tpl-row-tag">每台车</span>}
  {row.platform && <span className="tpl-row-tag">{row.platform === 'integrated' ? '集成' : row.platform}</span>}
  {!row.is_group && !row.required && <span className="tpl-row-tag">非必需</span>}
  {row.confidential_default && <span className="tpl-row-tag is-warn">保密</span>}
  {row.external_never_visible && <span className="tpl-row-tag">禁止外部查看</span>}
</>

type Target = Requirement | { stage: string }

/**
 * One document requirement edited beside the template outline. Changes to an existing requirement save themselves
 * half a second after typing stops; a new one is added with the button. The parent awaits `flushRef` before switching.
 */
export default function TemplateDocPanel({ templateId, editMode, rows, target, flushRef, onChanged, onCreated, onClose }: {
  templateId: string; editMode: boolean; rows: Requirement[]; target: Target; flushRef: MutableRefObject<(() => Promise<void>) | null>
  onChanged: () => Promise<unknown> | unknown; onCreated: (id?: string) => void; onClose: () => void
}) {
  const current = 'id' in target ? target : undefined
  const [save, setSave] = useState<SaveState>()
  const [busy, setBusy] = useState(false)
  const owner = useRef(templateId); owner.current = templateId
  const timer = useRef<ReturnType<typeof setTimeout>>()
  const queue = useRef<Promise<unknown>>(Promise.resolve())
  const lastSaved = useRef('')
  const [form] = Form.useForm()
  const kind = Form.useWatch('timing_type', form)
  const group = Form.useWatch('is_group', form)
  const scope = Form.useWatch('scope', form)
  const stage = Form.useWatch('stage_key', form)
  const code = Form.useWatch('code', form)
  const confidential = Form.useWatch('confidential_default', form)
  const neverVisible = Form.useWatch('external_never_visible', form)

  const bodyOf = () => {
    const values = form.getFieldsValue(true)
    return Object.fromEntries(FIELDS.map(key => [key, values[key] ?? (['parent_id', 'scope', 'platform', 'timing_type', 'timing_event', 'timing_offset_hours', 'timing_weekday', 'trigger_type'].includes(key) ? null : values[key])]))
  }
  useEffect(() => {
    const values = current ? (current.stage_key === 'legacy' ? { ...current, stage_key: undefined, code: '', parent_id: null } : current)
      : { ...RULE_EMPTY, stage_key: (target as { stage: string }).stage, code: '', name: '', template_no: '', is_group: false, required: true, scope: 'project', platform: null, parent_id: null, timing_type: 'on_demand', confidential_default: false, external_visible_default: false, external_never_visible: false, sort_order: rows.length, note: '' }
    form.setFieldsValue(values)
    lastSaved.current = current ? JSON.stringify(bodyOf()) : ''
  }, [])
  useEffect(() => { if (["6.11.6b", "6.11.6c"].includes(code)) form.setFieldsValue({ external_never_visible: true, external_visible_default: false }) }, [code])

  const detail = (err: any) => { const text = err?.response?.data?.detail; return typeof text === 'string' ? text : errMsg(err) }
  const persist = async () => {
    const templateAtStart = templateId
    if (!editMode || !current) return
    try { await form.validateFields() } catch { return }
    const body = bodyOf(); const text = JSON.stringify(body)
    if (text === lastSaved.current) return
    lastSaved.current = text
    queue.current = queue.current.then(async () => {
      setSave({ state: 'saving' })
      try {
        await api.put(`/templates/${templateId}/document-requirements/${current.id}`, body)
        if (owner.current !== templateAtStart) return
        setSave({ state: 'saved' }); await onChanged()
      } catch (err) { lastSaved.current = ''; setSave({ state: 'error', error: detail(err) }) }
    })
    await queue.current
  }
  const schedule = () => { clearTimeout(timer.current); timer.current = setTimeout(() => { timer.current = undefined; void persist() }, 500) }
  const flush = async () => { if (timer.current) { clearTimeout(timer.current); timer.current = undefined; await persist() } }
  useEffect(() => { flushRef.current = flush; return () => { if (flushRef.current === flush) flushRef.current = null } })
  const run = async (operation: () => Promise<any>, success: string, after?: (result: any) => void) => {
    if (busy) return
    setBusy(true)
    try { const result = await operation(); message.success(success); await onChanged(); after?.(result) }
    catch (err) { message.error(detail(err)) } finally { setBusy(false) }
  }
  const create = async () => {
    try { await form.validateFields() } catch { return }
    await run(() => api.post(`/templates/${templateId}/document-requirements`, bodyOf()), '资料要求已添加', result => onCreated(result?.data?.id))
  }
  const download = async (row: Requirement) => {
    try {
      const result = await api.get(`/templates/${templateId}/document-requirements/${row.id}/blank-file`, { responseType: 'blob' })
      const url = URL.createObjectURL(result.data)
      const link = document.createElement('a'); link.href = url; link.download = row.blank_file?.filename ?? '空白模板'; link.click(); URL.revokeObjectURL(url)
    } catch { message.error('空白模板下载失败，请重试或联系管理员核对文件') }
  }
  const eventOptions = Object.entries(EVENTS).filter(([key]) => kind === 'after_milestone' ? MILESTONES.includes(key) : key !== 'vehicle_arrival' || (kind === 'after_event' && scope === 'vehicle')).map(([value, label]) => ({ value, label }))

  return <aside className="tpl-panel" aria-label={current ? `编辑资料要求：${current.code} ${current.name}` : '新增资料要求'}>
    <header className="tpl-panel-head">
      <span className="tpl-panel-kicker">{!current ? '新增资料要求' : current.is_group ? '资料分组' : '资料要求'}</span>
      <SaveBadge save={save} />
      <Button type="text" size="small" icon={<CloseOutlined />} aria-label="关闭编辑" onClick={() => void flush().then(onClose)} />
    </header>
    <div className="tpl-panel-body">
      <Form form={form} layout="vertical" preserve disabled={!editMode} onValuesChange={() => { if (current) schedule() }}>
          {current?.stage_key === 'legacy' && <Alert type="info" showIcon message="请选择阶段并填写对应编号；历史来源只读保留，不会改写。" style={{ marginBottom: 12 }} />}
          <Form.Item name="name" label="资料名称" rules={[{ required: true, whitespace: true }]}><Input maxLength={300} /></Form.Item>
          <div className="tpl-form-pair">
            <Form.Item name="code" label="编号" rules={[{ required: true, message: '填写编号，如6.11.1a' }]}><Input maxLength={40} placeholder="如6.11.1a" /></Form.Item>
            <Form.Item name="stage_key" label="阶段" rules={[{ required: true }]}><Select options={DOC_STAGES} onChange={() => form.setFieldValue('parent_id', null)} /></Form.Item>
          </div>
          {!group && <>
            <Space wrap size={24} className="tpl-form-switches">
              <Form.Item name="required" label="必须提交" valuePropName="checked"><Switch /></Form.Item>
              <Form.Item name="scope" label="每台车一份" getValueProps={value => ({ checked: value === 'vehicle' })} getValueFromEvent={checked => checked ? 'vehicle' : 'project'}>
                <Switch onChange={checked => { if (!checked && form.getFieldValue('timing_event') === 'vehicle_arrival') form.setFieldValue('timing_event', null) }} />
              </Form.Item>
            </Space>
            <Form.Item name="timing_type" label="什么时候交" rules={[{ required: true }]}><Select options={Object.entries(TIMINGS).map(([value, label]) => ({ value, label }))} onChange={value => form.setFieldsValue({ ...RULE_EMPTY, timing_type: value, ...(value === 'lifetime' ? { timing_event: 'internal_kickoff' } : ['before_event', 'after_event', 'after_milestone', 'on_trigger'].includes(value) ? { timing_offset_hours: 0 } : {}) })} /></Form.Item>
            {['before_event', 'after_event', 'after_milestone', 'on_trigger'].includes(kind) && <div className="tpl-form-pair">
              {kind === 'on_trigger'
                ? <Form.Item name="trigger_type" label="发生什么" rules={[{ required: true }]}><Select options={Object.entries(TRIGGERS).map(([value, label]) => ({ value, label }))} /></Form.Item>
                : <Form.Item name="timing_event" label={kind === 'after_milestone' ? '哪个节点' : '哪个事件'} rules={[{ required: true }]}><Select options={eventOptions} /></Form.Item>}
              <Form.Item name="timing_offset_hours" label={kind === 'before_event' ? '提前' : '之后'} rules={[{ required: true }]}
                getValueProps={value => ({ value: days(value) })} getValueFromEvent={value => value == null ? null : Math.round(Number(value) * 24)}>
                <InputNumber min={0} max={36500} step={1} addonAfter="天" aria-label="相隔天数" />
              </Form.Item>
            </div>}
            {kind === 'weekly' && <Form.Item name="timing_weekday" label="每周几截止" rules={[{ required: true, message: '每周规则必须选择星期' }]}><Select options={WEEKDAYS.map((label, index) => ({ value: index + 1, label }))} /></Form.Item>}
          </>}
          <Form.Item name="note" label="说明"><Input.TextArea autoSize={{ minRows: 2, maxRows: 8 }} maxLength={5000} placeholder="可选：写给提交人的说明" /></Form.Item>
          <details className="tpl-more" open={!!current?.is_group}>
            <summary>更多设置</summary>
            <Form.Item name="is_group" label="作为分组标题" valuePropName="checked"><Switch onChange={value => form.setFieldsValue(value ? { ...RULE_EMPTY, scope: null, required: false } : { scope: 'project', required: true, timing_type: 'on_demand' })} /></Form.Item>
            <Form.Item name="parent_id" label="放在哪个分组下"><Select allowClear placeholder="不放在分组下" options={rows.filter(row => row.is_group && row.stage_key === stage && row.id !== current?.id).map(row => ({ value: row.id, label: `${row.code} ${row.name}` }))} /></Form.Item>
            {!group && <>
              <Form.Item name="template_no" label="模板编号"><Input maxLength={100} placeholder="可选，如模板16" /></Form.Item>
              <Form.Item name="platform" label="只用于某个调度平台"><Select allowClear placeholder="所有平台都用" options={[{ value: 'NDC', label: 'NDC' }, { value: 'GRACE', label: 'GRACE' }, { value: 'integrated', label: '集成' }]} /></Form.Item>
              <Space wrap size={24} className="tpl-form-switches">
                <Form.Item name="confidential_default" label="默认保密" valuePropName="checked"><Switch onChange={value => value && form.setFieldValue('external_visible_default', false)} /></Form.Item>
                <Form.Item name="external_never_visible" label="禁止外部查看" valuePropName="checked"><Switch onChange={value => value && form.setFieldValue('external_visible_default', false)} disabled={['6.11.6b', '6.11.6c'].includes(code)} /></Form.Item>
                <Form.Item name="external_visible_default" label="默认对外可见" valuePropName="checked"><Switch disabled={confidential || neverVisible} /></Form.Item>
              </Space>
            </>}
            <Form.Item name="sort_order" label="排序" rules={[{ required: true }]}><InputNumber min={0} max={100000} precision={0} /></Form.Item>
          </details>
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
      {!current ? <Button type="primary" icon={<PlusOutlined />} loading={busy} onClick={() => void create()}>添加资料要求</Button>
        : <Popconfirm title={current?.is_group ? '删除此分组？' : '删除此资料要求？'} description="既有项目与历史文件保留。" okText="删除" okButtonProps={{ danger: true }} cancelText="取消"
          onConfirm={() => run(() => api.delete(`/templates/${templateId}/document-requirements/${current!.id}`), '资料要求已删除', onClose)}>
          <Button danger type="text" icon={<DeleteOutlined />} disabled={busy}>{current?.is_group ? '删除分组' : '删除资料要求'}</Button>
        </Popconfirm>}
    </footer>}
  </aside>
}
