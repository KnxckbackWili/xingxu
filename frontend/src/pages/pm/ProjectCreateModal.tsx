import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, Button, DatePicker, Form, Input, Modal, Select, Typography, message } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import { flatWorkItems, selectedWorkItems } from '../../components/TemplateScope'
import { projectApi } from '../../api'
import { api, errMsg } from '../../api/client'
import { DEFAULT_TIMEZONE } from '../../constants/timezones'
import { useSubmitLock } from '../../hooks/useSubmitLock'

type TemplateRow = { id: string; name: string; is_system?: boolean }
type Values = { name: string; range: [Dayjs, Dayjs]; template: string }

/** One screen: name, period and template. Customer, vehicles, people and documents are filled in the project's preparation checklist. */
export default function ProjectCreateModal({ open, initialTemplate, onClose }: { open: boolean; initialTemplate?: string | null; onClose: () => void }) {
  const [form] = Form.useForm<Values>()
  const navigate = useNavigate()
  const lock = useSubmitLock()
  const creationKey = useRef<string | null>(null)
  const request = useRef(0)
  const [templates, setTemplates] = useState<TemplateRow[]>([])
  const [workIds, setWorkIds] = useState<string[] | null>(null)
  const [loadError, setLoadError] = useState('')
  const [saving, setSaving] = useState(false)
  const template = Form.useWatch('template', form)

  const loadWork = async (tid: string) => {
    const ticket = ++request.current
    setWorkIds(null); setLoadError('')
    try {
      const response = await api.get(`/templates/${tid}/work-items`)
      if (!Array.isArray(response.data?.phases)) throw new Error('模板工作内容返回格式无效')
      const phases = response.data.phases
      if (ticket === request.current) setWorkIds(selectedWorkItems(phases, flatWorkItems(phases).map((task: { id: string }) => task.id), []))
    } catch (error) {
      if (ticket === request.current) setLoadError(errMsg(error))
    }
  }

  useEffect(() => {
    if (!open) return
    form.setFieldsValue({ name: '', range: [dayjs(), dayjs().add(3, 'month').subtract(1, 'day')], template: initialTemplate || 'default' })
    creationKey.current = null
    void (async () => {
      try {
        const response = await api.get('/templates')
        const rows: TemplateRow[] = Array.isArray(response.data) ? response.data : []
        setTemplates([...rows].sort((a, b) => Number(!!b.is_system) - Number(!!a.is_system)))
        const wanted = initialTemplate && rows.some(row => row.id === initialTemplate) ? initialTemplate : (rows.find(row => row.is_system)?.id ?? rows[0]?.id ?? 'default')
        form.setFieldValue('template', wanted)
      } catch (error) {
        setLoadError(errMsg(error))
      }
    })()
  }, [open])

  useEffect(() => { if (open && template) void loadWork(template) }, [open, template])

  const submit = async (values: Values) => {
    if (!workIds || !lock.tryAcquire()) return
    setSaving(true)
    creationKey.current ??= globalThis.crypto?.randomUUID?.() ?? `local-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
    try {
      const project = await projectApi.create({
        name: values.name.trim(), status: 'preparing', timezone: DEFAULT_TIMEZONE,
        start_date: values.range[0].format('YYYY-MM-DD'), end_date: values.range[1].format('YYYY-MM-DD'),
        template_id: values.template, work_item_ids: workIds, client_uuid: creationKey.current,
      })
      const tasks = project.initial_generation?.tasks ?? 0
      message.success(tasks ? `项目已创建，带入 ${tasks} 项工作；按准备清单补全车型、人员和资料` : '项目已创建；可在计划页从模板带入工作')
      creationKey.current = null
      onClose()
      navigate(`/pm/projects/${project.id}/overview`)
    } catch (error) {
      message.error(errMsg(error))
    } finally {
      setSaving(false)
      lock.release()
    }
  }

  return <Modal title="新建项目" open={open} width={480} destroyOnHidden maskClosable={!saving} closable={!saving}
    onCancel={() => { if (!saving) onClose() }}
    footer={<>
      <Button disabled={saving} onClick={onClose}>取消</Button>
      <Button type="primary" loading={saving} disabled={!workIds} onClick={() => form.submit()}>创建并进入项目</Button>
    </>}>
    <Form form={form} layout="vertical" onFinish={submit} disabled={saving} className="project-quick-create" requiredMark={false}>
      <Form.Item name="name" label="项目名称" rules={[{ required: true, whitespace: true, message: '请输入项目名称' }]}>
        <Input autoFocus placeholder="例如：华东物流中心 AGV 项目" maxLength={200} />
      </Form.Item>
      <Form.Item name="range" label="实施周期" rules={[{ required: true, message: '请选择实施周期' },
        { validator: async (_, value?: [Dayjs, Dayjs]) => { if (value && value[1].isBefore(value[0], 'day')) throw new Error('结束日期不能早于开始日期') } }]}>
        <DatePicker.RangePicker style={{ width: '100%' }} allowClear={false} />
      </Form.Item>
      <Form.Item name="template" label="工作模板" extra={workIds ? `将带入 ${workIds.length} 项工作，进项目后可增删` : loadError ? undefined : '正在读取模板…'}>
        <Select aria-label="工作模板" loading={!templates.length && !loadError} options={templates.map(row => ({ value: row.id, label: row.name }))} />
      </Form.Item>
      {loadError && <Alert type="error" showIcon message="模板读取失败，暂不能创建" description={loadError}
        action={<Button size="small" onClick={() => void loadWork(form.getFieldValue('template'))}>重试</Button>} />}
      <Typography.Paragraph type="secondary" className="project-quick-create-note">
        客户、地点、车型、人员和资料在项目的“准备清单”里补全。
      </Typography.Paragraph>
    </Form>
  </Modal>
}
