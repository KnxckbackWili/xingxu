import { useEffect, useRef, useState } from 'react'
import { Alert, Button, DatePicker, Form, Input, Modal, Radio, Select } from 'antd'
import dayjs from 'dayjs'
import { api, errMsg } from '../api/client'
import { type Project } from '../api'
import { inProjectTime } from '../constants/projectEvents'

export default function VehicleArrivalEditor({ project, units, onSaved }: {
  project: Project; units: Array<{ id: string; asset_code: string; arrived_at?: string | null }>; onSaved: () => void | Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [form] = Form.useForm()
  const mode = Form.useWatch('mode', form)
  const busy = useRef(false)
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const begin = () => {
    form.setFieldsValue({ mode: 'register', unit_ids: [], arrived_at: dayjs(inProjectTime(undefined, project.timezone || 'Asia/Shanghai').format('YYYY-MM-DD')), reason: '' })
    setError(''); setOpen(true)
  }
  const save = async (values: any) => {
    if (busy.current) return
    busy.current = true; setSaving(true); setError('')
    try {
      await api.put(`/projects/${project.id}/vehicle-arrivals`, {
        unit_ids: values.unit_ids, arrived_at: values.mode === 'clear' ? null : values.arrived_at.format('YYYY-MM-DD'), reason: values.reason ?? '',
      })
      if (mounted.current) { setOpen(false); await onSaved() }
    } catch (cause) { if (mounted.current) setError(errMsg(cause)) }
    finally { busy.current = false; if (mounted.current) setSaving(false) }
  }
  return <>
    <Button disabled={!units.length} onClick={begin}>批量登记到场</Button>
    <Modal className="field-work-modal" title="车辆到场日期" open={open} onCancel={() => { if (!busy.current) setOpen(false) }}
      onOk={() => form.submit()} confirmLoading={saving} okText="保存到场日期">
      <Form form={form} layout="vertical" disabled={saving} onFinish={save}>
        <Form.Item name="mode" label="操作"><Radio.Group options={[{ value: 'register', label: '登记到场' }, { value: 'clear', label: '清除误登记' }]} /></Form.Item>
        <Form.Item name="unit_ids" label="选择车辆" rules={[{ required: true, message: '请选择至少一台车辆' }]}>
          <Select mode="multiple" aria-label="选择到场车辆" optionFilterProp="label" maxTagCount="responsive"
            options={units.map(unit => ({ value: unit.id, label: `${unit.asset_code}${unit.arrived_at ? ` · ${unit.arrived_at}已到场` : ''}` }))} />
        </Form.Item>
        <Button size="small" disabled={saving} onClick={() => form.setFieldValue('unit_ids', units.map(unit => unit.id))}>选择全部已建档车辆</Button>
        {mode !== 'clear' && <Form.Item name="arrived_at" label="到场日期" rules={[{ required: true, message: '请选择到场日期' }]}><DatePicker /></Form.Item>}
        {mode === 'clear' && <Alert type="warning" showIcon message="清除已有到场日期须填写理由，并保留操作记录。全部到场日期会重新汇总。" />}
        <Form.Item name="reason" label={mode === 'clear' ? '清除理由' : '登记说明'} rules={mode === 'clear' ? [{ required: true, whitespace: true, message: '请填写清除理由' }] : []}>
          <Input.TextArea rows={2} maxLength={1000} />
        </Form.Item>
        <Alert type="info" message="车辆按计划车型数量完整建档且每台都已到场后，自动以最后一台的到场日期登记「全部到场」。" />
        {error && <Alert type="error" showIcon message={error} />}
      </Form>
    </Modal>
  </>
}
