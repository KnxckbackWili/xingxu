import { useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Checkbox, Form, Input, Modal, Select, Space } from 'antd'
import { api, errMsg } from '../api/client'
import type { WorkItem, WorkPhase } from '../api/workItems'
import { ensureVerifiedAccount } from '../utils/verifiedAccount'
import { useAuth } from '../stores/auth'
import { useVehicleTypes } from '../hooks/useVehicleTypes'

type Props = { canEdit?: boolean; open: boolean; projectId?: string; templateId?: string; item?: WorkItem; phases: WorkPhase[]; steps: { key: string; name: string }[]; onClose: () => void; onSaved: () => void | Promise<void> }
export default function WorkItemEditor({ canEdit = true, open, projectId, templateId, item, phases, steps, onClose, onSaved }: Props) {
  const { user } = useAuth()
  const identityKey = `${user?.id}:${projectId ?? ''}:${templateId ?? ''}:${item?.id ?? 'new'}`
  const identity = useMemo(() => Symbol(identityKey), [identityKey])
  const owner = useRef(identity); owner.current = identity
  useEffect(() => { owner.current = identity; return () => { owner.current = Symbol('closed') } }, [identity])
  const [form] = Form.useForm()
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const authority = useRef(canEdit); authority.current = canEdit
  const [busy, setBusy] = useState(false)
  const lock = useRef(false)
  const captured = useRef(item)
  const kind = Form.useWatch('kind', form)
  const { options } = useVehicleTypes()
  useEffect(() => {
    if (!open) return
    captured.current = item; setError(''); setSaved(false); form.resetFields()
    form.setFieldsValue(item ? { ...item, checks: item.check_definitions ?? [], vehicle_step_key: item.vehicle_step_key ?? null } : { kind: 'other', phase_id: phases[0]?.id, group_label: '', applicable_vehicle_types: [], scope_conditions: [], checks: [] })
  }, [open, identity])
  const save = async () => {
    if (lock.current || !authority.current || saved) return
    const requestOwner = owner.current
    lock.current = true; setBusy(true); setError('')
    try {
      const value = await form.validateFields()
      if (owner.current !== requestOwner || !authority.current) return
      ensureVerifiedAccount(user?.id)
      const previous = captured.current
      const base = templateId ? `/templates/${templateId}/work-items` : `/projects/${projectId}/work-items`
      const fields = previous && !templateId ? { name: value.name, description: value.description ?? '', phase_id: value.phase_id, group_label: value.group_label ?? '', ...(previous.kind === 'vehicle' ? { vehicle_step_key: value.vehicle_step_key ?? null } : {}) }
        : { phase_id: value.phase_id, name: value.name, kind: value.kind, description: value.description ?? '', group_label: value.group_label ?? '',
          vehicle_step_key: value.kind === 'vehicle' ? value.vehicle_step_key ?? null : null, applicable_vehicle_types: value.applicable_vehicle_types ?? [], scope_conditions: value.scope_conditions ?? [],
          checks: (value.checks ?? []).map((c: any) => ({ name: c.name, description: c.description ?? '', is_required: c.is_required !== false, is_safety_critical: !!c.is_safety_critical })) }
      if (previous) await api.put(`${base}/${previous.id}`, { ...fields, version: previous.version })
      else await api.post(base, fields)
      if (owner.current !== requestOwner) return
      setSaved(true)
      try { await onSaved(); if (owner.current === requestOwner) onClose() } catch { if (owner.current === requestOwner) setError('工作项已保存，但最新记录读取失败；请关闭后刷新核对。') }
    } catch (e) { if (owner.current === requestOwner) setError(errMsg(e)) }
    finally { if (owner.current === requestOwner) { lock.current = false; setBusy(false) } }
  }
  return <Modal title={item ? '编辑工作项' : '添加工作项'} open={open} onCancel={() => { if (!lock.current) onClose() }} onOk={() => void save()} okText="保存工作项" cancelText="取消" confirmLoading={busy} okButtonProps={{ disabled: !canEdit || saved }} destroyOnClose>
    {error && <Alert type="error" message={saved ? '工作项已保存' : '工作项未保存'} description={error} />}
    <Form form={form} layout="vertical" disabled={busy || !canEdit} preserve>
      <Form.Item name="phase_id" label="阶段" rules={[{ required: true }]}><Select options={phases.map(p => ({ label: p.name, value: p.id }))} /></Form.Item>
      <Form.Item name="name" label="工作项名称" rules={[{ required: true, whitespace: true }]}><Input maxLength={200} /></Form.Item>
      <Form.Item name="description" label="工作说明"><Input.TextArea rows={3} maxLength={20000} /></Form.Item>
      <Form.Item name="group_label" label="分组标签" tooltip="用于保留旧模块名称或标记工作范围，不增加层级"><Input maxLength={200} /></Form.Item>
      <Form.Item name="kind" label="工作类型" rules={[{ required: true }]}><Select disabled={busy || (!!item && !templateId)} options={[{ label: '非车辆工作（完成 / 未完成）', value: 'other' }, { label: '车辆工作（关联真实车辆环节）', value: 'vehicle' }]} /></Form.Item>
      {kind === 'vehicle' && <><Form.Item name="vehicle_step_key" label="车辆环节" rules={[{ required: !item || item.kind !== 'vehicle' }]}><Select allowClear options={steps.map(s => ({ label: s.name, value: s.key }))} placeholder="明确选择，不按名称猜测" /></Form.Item>{(!item || templateId) && <Form.Item name="applicable_vehicle_types" label="适用车型"><Select mode="multiple" options={options} placeholder="留空表示全部车型" /></Form.Item>}</>}
      {(!item || templateId) && <><Form.Item name="scope_conditions" label="业务范围条件"><Select mode="multiple" options={[{ value: 'need_wms', label: 'WMS 对接' }, { value: 'need_charging', label: '自动充电' }]} /></Form.Item>
        <Form.List name="checks">{(fields, { add, remove }) => <><strong>检查要求</strong>{fields.map(field => <div key={field.key} style={{ padding: '8px 0' }}><Form.Item name={[field.name, 'name']} rules={[{ required: true, whitespace: true }]}><Input aria-label={`检查要求${field.name + 1}名称`} placeholder="检查名称" /></Form.Item><Form.Item name={[field.name, 'description']}><Input.TextArea placeholder="检查说明" /></Form.Item><Space><Form.Item name={[field.name, 'is_required']} valuePropName="checked" noStyle><Checkbox>必需</Checkbox></Form.Item><Form.Item name={[field.name, 'is_safety_critical']} valuePropName="checked" noStyle><Checkbox>安全关键</Checkbox></Form.Item><Button danger onClick={() => remove(field.name)}>移除定义</Button></Space></div>)}<Button onClick={() => add({ name: '', description: '', is_required: true, is_safety_critical: false })}>添加检查定义</Button></>}</Form.List></>}
    </Form>
  </Modal>
}
