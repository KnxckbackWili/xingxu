import { useEffect, useRef, useState, type MutableRefObject } from 'react'
import { Button, Form, Input, Popconfirm, Select, Switch, message } from 'antd'
import { CloseOutlined, DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { api, errMsg } from '../../api/client'
import { SaveBadge, type SaveState } from './TemplateWorkPanel'

export const RISK_LABEL: Record<string, string> = { low: '低', medium: '中', high: '高' }
export type ProcItem = { id: string; name: string; unit?: string; spec?: string; risk?: string; is_required?: boolean }
const FIELDS = ['name', 'unit', 'spec', 'risk', 'is_required'] as const

/**
 * One common procurement item edited beside the template outline. Projects pick from these in their preparation
 * checklist; quantities and arrival are kept in the project. Existing items save themselves; new ones use the button.
 */
export default function TemplateProcPanel({ templateId, editMode, item, flushRef, onChanged, onCreated, onClose }: {
  templateId: string; editMode: boolean; item?: ProcItem; flushRef: MutableRefObject<(() => Promise<void>) | null>
  onChanged: () => Promise<unknown> | unknown; onCreated: (id?: string) => void; onClose: () => void
}) {
  const [form] = Form.useForm()
  const [save, setSave] = useState<SaveState>()
  const [busy, setBusy] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout>>()
  const queue = useRef<Promise<unknown>>(Promise.resolve())
  const lastSaved = useRef('')
  const bodyOf = () => { const values = form.getFieldsValue(true); return Object.fromEntries(FIELDS.map(key => [key, values[key]])) }
  useEffect(() => {
    form.setFieldsValue(item ? { ...item, unit: item.unit || '件', risk: item.risk || 'low', is_required: !!item.is_required } : { name: '', unit: '台', spec: '', risk: 'low', is_required: false })
    lastSaved.current = item ? JSON.stringify(bodyOf()) : ''
  }, [])
  const persist = async () => {
    if (!editMode || !item) return
    try { await form.validateFields() } catch { return }
    const body = bodyOf(); const text = JSON.stringify(body)
    if (text === lastSaved.current) return
    lastSaved.current = text
    queue.current = queue.current.then(async () => {
      setSave({ state: 'saving' })
      try { await api.put(`/templates/${templateId}/procurements/${item.id}`, body); setSave({ state: 'saved' }); await onChanged() }
      catch (e) { lastSaved.current = ''; setSave({ state: 'error', error: errMsg(e) }) }
    })
    await queue.current
  }
  const schedule = () => { clearTimeout(timer.current); timer.current = setTimeout(() => { timer.current = undefined; void persist() }, 500) }
  const flush = async () => { if (timer.current) { clearTimeout(timer.current); timer.current = undefined; await persist() } }
  useEffect(() => { flushRef.current = flush; return () => { if (flushRef.current === flush) flushRef.current = null } })
  const create = async () => {
    try { await form.validateFields() } catch { return }
    if (busy) return
    setBusy(true)
    try { const result = await api.post(`/templates/${templateId}/procurements`, bodyOf()); message.success('采购物料已添加'); await onChanged(); onCreated(result?.data?.id) }
    catch (e) { message.error(errMsg(e)) } finally { setBusy(false) }
  }
  const remove = async () => {
    if (!item || busy) return
    setBusy(true)
    try { await api.delete(`/templates/${templateId}/procurements/${item.id}`); message.success('已删除'); await onChanged(); onClose() }
    catch (e) { message.error(errMsg(e)) } finally { setBusy(false) }
  }

  return <aside className="tpl-panel" aria-label={item ? `编辑采购物料：${item.name}` : '新增采购物料'}>
    <header className="tpl-panel-head">
      <span className="tpl-panel-kicker">{item ? '采购物料' : '新增采购物料'}</span>
      <SaveBadge save={save} />
      <Button type="text" size="small" icon={<CloseOutlined />} aria-label="关闭编辑" onClick={() => void flush().then(onClose)} />
    </header>
    <div className="tpl-panel-body">
      <Form form={form} layout="vertical" preserve disabled={!editMode || busy} onValuesChange={() => { if (item) schedule() }}>
        <Form.Item name="name" label="物料名称" rules={[{ required: true, whitespace: true, message: '填写物料名称' }]}><Input maxLength={200} placeholder="如：车载工控机 / 自动充电桩 / 安全围栏" /></Form.Item>
        <div className="tpl-form-pair">
          <Form.Item name="unit" label="单位"><Select options={['台', '套', '米', '箱', '卷', '个', '件'].map(u => ({ label: u, value: u }))} /></Form.Item>
          <Form.Item name="risk" label="缺货风险"><Select options={Object.entries(RISK_LABEL).map(([value, label]) => ({ label, value }))} /></Form.Item>
        </div>
        <Form.Item name="spec" label="规格 / 型号 / 说明"><Input maxLength={300} placeholder="如：含 4G 模块与硬盘（每车 1 台）" /></Form.Item>
        <Form.Item name="is_required" label="通常必需" valuePropName="checked"><Switch /></Form.Item>
      </Form>
      <p className="tpl-field-hint">项目在准备清单里勾选要买的物料；数量和到货情况在项目里填。</p>
    </div>
    {editMode && <footer className="tpl-panel-foot">
      {!item ? <Button type="primary" icon={<PlusOutlined />} loading={busy} onClick={() => void create()}>添加采购物料</Button>
        : <Popconfirm title="删除这个采购物料？" description="已建项目里的采购记录不受影响。" okText="删除" okButtonProps={{ danger: true }} cancelText="取消" onConfirm={() => void remove()}>
          <Button danger type="text" icon={<DeleteOutlined />} disabled={busy}>删除采购物料</Button>
        </Popconfirm>}
    </footer>}
  </aside>
}
