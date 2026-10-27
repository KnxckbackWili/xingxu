import { useEffect, useRef, useState } from 'react'
import { Alert, Form, Input, InputNumber, Modal, Select, Space, Switch, Typography } from 'antd'
import { errMsg } from '../../../api/client'
import { projectDocumentsApi, type ProjectDocumentDefinition, type ProjectRequirementBody } from '../../../api/projectDocuments'
import { DOCUMENT_EVENTS, DOCUMENT_MILESTONES, DOCUMENT_RULE_EMPTY, DOCUMENT_STAGES, DOCUMENT_TIMINGS, DOCUMENT_TRIGGERS, DOCUMENT_WEEKDAYS } from '../../../constants/documentRules'

const fields = ['stage_key', 'code', 'name', 'template_no', 'required', 'scope', 'platform', 'timing_type', 'timing_event', 'timing_offset_hours', 'timing_weekday', 'trigger_type', 'sort_order', 'note', 'confidential_default', 'external_visible_default', 'external_never_visible', 'owner_id'] as const
export default function ProjectDocumentRequirementEditor({ projectId, editing, onClose, onSaved, onDirtyChange, canEdit = false, canSetConfidentiality = false, ownerOptions = [] }: {
  ownerOptions?: { id: string; name: string }[]
  canEdit?: boolean
  canSetConfidentiality?: boolean
  projectId: string; editing: ProjectDocumentDefinition | 'new' | null
  onClose: () => void; onSaved: () => void; onDirtyChange: (dirty: boolean) => void
}) {
  const [form] = Form.useForm()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const active = useRef(true)
  const lock = useRef(false)
  useEffect(() => { active.current = true; return () => { active.current = false } }, [])
  useEffect(() => {
    form.resetFields(); setError(''); onDirtyChange(false)
    if (editing) form.setFieldsValue(editing === 'new' ? {
      ...DOCUMENT_RULE_EMPTY, stage_key: '6', name: '', code: '', template_no: '', required: true,
      scope: 'project', platform: null, timing_type: 'on_demand', sort_order: 0, note: '',
      confidential_default: false, external_visible_default: false, external_never_visible: false, owner_id: null,
    } : editing)
  }, [editing, projectId, form, onDirtyChange])
  const kind = Form.useWatch('timing_type', form)
  const scope = Form.useWatch('scope', form)
  const confidential = Form.useWatch('confidential_default', form)
  const never = Form.useWatch('external_never_visible', form)
  const code = Form.useWatch('code', form)
  const forbiddenExternal = ['6.11.6', '6.11.6a', '6.11.6b', '6.11.6c'].includes(code)
  const previousCode = useRef('')
  useEffect(() => {
    if (editing === 'new' && forbiddenExternal && code !== previousCode.current) form.setFieldValue('confidential_default', true)
    previousCode.current = code
  }, [code, editing, forbiddenExternal, form])
  useEffect(() => { if (forbiddenExternal) form.setFieldsValue({ external_never_visible: true, external_visible_default: false }) }, [forbiddenExternal, form])
  const save = async () => {
    if (lock.current || !editing || !canEdit) return
    try { await form.validateFields() } catch { return }
    const values = form.getFieldsValue(true)
    const body = Object.fromEntries(fields.map(key => [key, values[key] ?? (['platform', 'timing_event', 'timing_offset_hours', 'timing_weekday', 'trigger_type', 'owner_id'].includes(key) ? null : values[key])])) as unknown as ProjectRequirementBody
    lock.current = true; setBusy(true); setError('')
    try {
      if (editing === 'new') await projectDocumentsApi.createRequirement(projectId, body)
      else await projectDocumentsApi.updateRequirement(projectId, editing.id, body)
      if (active.current) { onDirtyChange(false); onSaved(); onClose() }
    } catch (failure) { if (active.current) setError(errMsg(failure)) }
    finally { lock.current = false; if (active.current) setBusy(false) }
  }
  const eventOptions = Object.entries(DOCUMENT_EVENTS).filter(([value]) => kind === 'after_milestone'
    ? DOCUMENT_MILESTONES.includes(value) : value !== 'vehicle_arrival' || (scope === 'vehicle' && kind === 'after_event'))
  return <Modal title={editing === 'new' ? '新增项目资料要求' : '编辑项目资料要求'} open={editing !== null}
    okText="保存要求" cancelText="取消" onOk={() => void save()} confirmLoading={busy} okButtonProps={{ disabled: !canEdit }}
    onCancel={() => { if (!busy) { onDirtyChange(false); onClose() } }} maskClosable={false} width={680} destroyOnHidden>
    <Form form={form} layout="vertical" preserve disabled={busy || !canEdit} onValuesChange={() => onDirtyChange(true)}>
      {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} />}
      <Typography.Paragraph type="secondary">同一范围和周期中尚无提交历史的资料会更新要求；已有提交保留原规则。更改范围、平台或输出周期仅用于后续生成的资料。</Typography.Paragraph>
      {editing !== 'new' && editing?.source_metadata && <Typography.Paragraph type="secondary">原记录与审核信息保留；这里只修改本项目的资料要求。</Typography.Paragraph>}
      <Form.Item name="stage_key" label="阶段" rules={[{ required: true, message: '请选择第4–9阶段' }, { validator: (_, value) => value === 'legacy' ? Promise.reject(new Error('请将历史资料明确归类到第4–9阶段')) : Promise.resolve() }]}>
        <Select options={DOCUMENT_STAGES} placeholder="请选择资料所属阶段" />
      </Form.Item>
      <Space align="start" wrap>
        <Form.Item name="code" label="编号" rules={[{ required: true, whitespace: true, message: '请填写阶段内编号，如6.12' }]}><Input maxLength={40} placeholder="如6.12" /></Form.Item>
        <Form.Item name="name" label="资料名称" rules={[{ required: true, whitespace: true }]}><Input maxLength={300} style={{ width: 'min(330px, 70vw)' }} /></Form.Item>
      </Space>
      <Form.Item name="owner_id" label="默认资料负责人" help="留空时由活跃技术负责人接收提醒，其次为项目经理；既有提交可在资料行单独指派。"><Select allowClear showSearch optionFilterProp="label" placeholder="技术负责人 / 项目经理" options={ownerOptions.map(person => ({ value: person.id, label: person.name }))} /></Form.Item>
      <Form.Item name="template_no" label="模板编号或示例标识"><Input maxLength={100} /></Form.Item>
      <Space align="start" wrap>
        <Form.Item name="scope" label="范围" rules={[{ required: true }]}><Select style={{ width: 160 }} options={[{ value: 'project', label: '项目一份' }, { value: 'vehicle', label: '每台车一份' }]} onChange={value => { if (value !== 'vehicle' && form.getFieldValue('timing_event') === 'vehicle_arrival') form.setFieldValue('timing_event', null) }} /></Form.Item>
        <Form.Item name="platform" label="适用平台"><Select style={{ width: 160 }} allowClear placeholder="全部平台" options={[{ value: 'NDC', label: 'NDC' }, { value: 'GRACE', label: 'GRACE' }, { value: 'integrated', label: '集成' }]} /></Form.Item>
        <Form.Item name="required" label="必需资料" valuePropName="checked"><Switch /></Form.Item>
      </Space>
      <Form.Item name="timing_type" label="输出时机" rules={[{ required: true }]}><Select options={Object.entries(DOCUMENT_TIMINGS).map(([value, label]) => ({ value, label }))} onChange={value => form.setFieldsValue({ ...DOCUMENT_RULE_EMPTY, timing_type: value, ...(value === 'lifetime' ? { timing_event: 'internal_kickoff' } : ['before_event', 'after_event', 'after_milestone', 'on_trigger'].includes(value) ? { timing_offset_hours: 0 } : {}) })} /></Form.Item>
      {['before_event', 'after_event', 'after_milestone'].includes(kind) && <Form.Item name="timing_event" label="关键事件" rules={[{ required: true }]}><Select options={eventOptions.map(([value, label]) => ({ value, label }))} /></Form.Item>}
      {['before_event', 'after_event', 'after_milestone', 'on_trigger'].includes(kind) && <Form.Item name="timing_offset_hours" label="偏移小时" rules={[{ required: true }]}><InputNumber min={0} max={876000} precision={0} /></Form.Item>}
      {kind === 'weekly' && <Form.Item name="timing_weekday" label="每周截止星期" rules={[{ required: true, message: '每周规则必须选择星期' }]}><Select options={DOCUMENT_WEEKDAYS.map((label, index) => ({ label, value: index + 1 }))} /></Form.Item>}
      {kind === 'on_trigger' && <Form.Item name="trigger_type" label="触发类型" rules={[{ required: true }]}><Select options={Object.entries(DOCUMENT_TRIGGERS).map(([value, label]) => ({ value, label }))} /></Form.Item>}
      {kind === 'lifetime' && <Typography.Paragraph type="secondary">内部启动会建档，归档前提交；按需保留后续版本。</Typography.Paragraph>}
      <Form.Item name="confidential_default" label="默认保密" valuePropName="checked"><Switch disabled={!canSetConfidentiality || editing !== 'new'} onChange={value => value && form.setFieldValue('external_visible_default', false)} /></Form.Item>
      {editing && editing !== 'new' && <Typography.Paragraph type="secondary">现有资料要求的保密范围请从“保密范围”设置，按版本校验并作用于全部期次、历史版本和以后生成项。</Typography.Paragraph>}
      <Form.Item name="external_never_visible" label="禁止外部查看" valuePropName="checked"><Switch disabled={forbiddenExternal || editing !== 'new'} onChange={value => value && form.setFieldValue('external_visible_default', false)} /></Form.Item>
      <Form.Item name="external_visible_default" label="默认对外可见" valuePropName="checked"><Switch disabled={confidential || never || forbiddenExternal || editing !== 'new'} /></Form.Item>
      <Form.Item name="sort_order" label="排序" rules={[{ required: true }]}><InputNumber min={0} max={100000} precision={0} /></Form.Item>
      <Form.Item name="note" label="说明"><Input.TextArea rows={3} maxLength={5000} /></Form.Item>
    </Form>
  </Modal>
}
