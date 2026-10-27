import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Card, DatePicker, Empty, Form, Input, Modal, Select, Space, Spin, Typography, message } from 'antd'
import dayjs from 'dayjs'
import { availabilityApi } from '../api'
import { errMsg } from '../api/client'

interface Period { id: string; start_date: string; end_date: string; reason: string; note: string }
interface Props { people: { id: string; name: string }[]; onClose: () => void; onChanged: () => void }

/** PM/admin only: mounted by PeoplePlanPage. The API remains the permission authority. */
export default function UnavailabilityManager({ people, onClose, onChanged }: Props) {
  const [personId, setPersonId] = useState<string>()
  const [periods, setPeriods] = useState<Period[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const [editing, setEditing] = useState<Period | null>(null)
  const [deleting, setDeleting] = useState<Period | null>(null)
  const [saving, setSaving] = useState(false)
  const busy = useRef(false)
  const [form] = Form.useForm()
  const personName = people.find(person => person.id === personId)?.name ?? ''

  useEffect(() => {
    let current = true
    setPeriods([])
    setError('')
    if (!personId) return
    setLoading(true)
    availabilityApi.listUnavailability(personId)
      .then(items => { if (current) setPeriods(items) })
      .catch(e => { if (current) setError(errMsg(e)) })
      .finally(() => { if (current) setLoading(false) })
    return () => { current = false }
  }, [personId, revision])

  const save = async (values: any) => {
    if (busy.current || !personId || !editing) return
    busy.current = true
    setSaving(true)
    try {
      const updated = await availabilityApi.updateUnavailability(personId, editing.id, {
        start_date: values.range[0].format('YYYY-MM-DD'), end_date: values.range[1].format('YYYY-MM-DD'),
        reason: values.reason, note: values.note ?? '',
      })
      setPeriods(items => items.map(item => item.id === editing.id ? updated : item).sort((a, b) => a.start_date.localeCompare(b.start_date)))
      setEditing(null)
      message.success('不可用时段已更新')
      onChanged()
    } catch (e) { message.error(errMsg(e)) }
    finally { busy.current = false; setSaving(false) }
  }
  const remove = async () => {
    if (busy.current || !personId || !deleting) return
    busy.current = true
    setSaving(true)
    try {
      await availabilityApi.deleteUnavailability(personId, deleting.id)
      setPeriods(items => items.filter(item => item.id !== deleting.id))
      setDeleting(null)
      message.success('不可用时段已取消')
      onChanged()
    } catch (e) { message.error(errMsg(e)) }
    finally { busy.current = false; setSaving(false) }
  }
  return <>
    <Modal open title="管理不可用时段" width={640} footer={null} onCancel={() => { if (!busy.current && !editing && !deleting) onClose() }} maskClosable={false}>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Typography.Text type="secondary">选择人员查看全部时段（含历史及未来安排）。日期包含起止当天；取消后该时段不再限制人员安排。</Typography.Text>
        <Select aria-label="管理人员" placeholder="选择人员" style={{ width: '100%' }} showSearch optionFilterProp="label" value={personId} disabled={!!editing || !!deleting || saving}
          options={people.map(person => ({ value: person.id, label: person.name }))} onChange={setPersonId} />
        {loading ? <Spin /> : error ? <Alert type="error" showIcon message={error} action={<Button onClick={() => setRevision(value => value + 1)}>重试</Button>} />
          : !personId ? <Empty description="请选择人员" /> : periods.length === 0 ? <Empty description="该人员暂无不可用时段" />
          : periods.map(period => <Card key={period.id} size="small">
            <Space direction="vertical" style={{ width: '100%', overflowWrap: 'anywhere' }}>
              <Typography.Text strong>{period.start_date} 至 {period.end_date}</Typography.Text>
              <Typography.Text>{period.reason}{period.note ? ` · ${period.note}` : ''}</Typography.Text>
              <Space wrap>
                <Button onClick={() => { form.setFieldsValue({ range: [dayjs(period.start_date), dayjs(period.end_date)], reason: period.reason, note: period.note }); setEditing(period) }}>编辑时段</Button>
                <Button danger onClick={() => setDeleting(period)}>取消时段</Button>
              </Space>
            </Space>
          </Card>)}
      </Space>
    </Modal>
    <Modal open={!!editing} title={`编辑不可用时段 · ${personName}`} width={480} okText="保存" cancelText="放弃修改" confirmLoading={saving} closable={!saving} maskClosable={false} keyboard={!saving} cancelButtonProps={{ disabled: saving }} onCancel={() => { if (!busy.current) setEditing(null) }} onOk={() => form.submit()}>
      <Form form={form} layout="vertical" onFinish={save} disabled={saving}>
        <Form.Item name="range" label="起止日期（含当天）" rules={[{ required: true, message: '请选择完整日期范围' }]}><DatePicker.RangePicker style={{ width: '100%' }} /></Form.Item>
        <Form.Item name="reason" label="原因" rules={[{ required: true, whitespace: true, message: '请填写原因' }]}><Input maxLength={100} /></Form.Item>
        <Form.Item name="note" label="备注"><Input.TextArea maxLength={500} showCount autoSize={{ minRows: 2, maxRows: 5 }} /></Form.Item>
      </Form>
    </Modal>
    <Modal open={!!deleting} title="确认取消不可用时段？" width={440} okText="确认取消时段" cancelText="保留时段" okButtonProps={{ danger: true }} confirmLoading={saving} closable={!saving} maskClosable={false} keyboard={!saving} cancelButtonProps={{ disabled: saving }} onCancel={() => { if (!busy.current) setDeleting(null) }} onOk={remove}>
      <p>{personName} · {deleting?.start_date} 至 {deleting?.end_date}</p>
      <p style={{ overflowWrap: 'anywhere' }}>{deleting?.reason}{deleting?.note ? ` · ${deleting.note}` : ''}</p>
      <p>此操作会删除该记录，恢复该时段的可用性（其他重叠时段仍然有效）。如需调整日期，请保留时段并使用编辑。</p>
    </Modal>
  </>
}
