import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Checkbox, Form, Input, InputNumber, Space, Spin, Tag, Typography, Upload, message } from 'antd'
import { DownloadOutlined, UploadOutlined } from '@ant-design/icons'
import { holidayCalendarsApi, type AnnualCalendar, type CalendarWrite } from '../../api/holidayCalendars'
import { errMsg } from '../../api/client'
import { useAuth } from '../../stores/auth'
import { hasSystemPermission } from '../../constants/systemPermissions'
import { WorkPageHeader, WorkSection } from '../../components/WorkPage'
import HolidayCalendarNotice from '../../components/HolidayCalendarNotice'
import './SettingsPages.css'

type CalendarForm = { source_name: string; source_url: string; published_on: string; holidays: string; workdays: string; note: string; complete: boolean }
const splitDates = (value: string) => value.split(/[\s,，]+/).filter(Boolean)
const formValues = (row: AnnualCalendar): CalendarForm => ({ source_name: row.source_name, source_url: row.source_url,
  published_on: row.published_on ?? '', holidays: row.holidays.join('\n'), workdays: row.workdays.join('\n'), note: row.note, complete: false })

export default function HolidayCalendarsPage() {
  const { user } = useAuth()
  const canManage = hasSystemPermission(user, 'system.holidays.manage')
  const [year, setYear] = useState(new Date().getFullYear() + 1)
  const [calendar, setCalendar] = useState<AnnualCalendar | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [imported, setImported] = useState(false)
  const [form] = Form.useForm<CalendarForm>()
  const scope = useRef(0)
  const request = useRef(0)
  const saveLock = useRef(false)
  const importSequence = useRef(0)
  const canManageNow = useRef(canManage)
  canManageNow.current = canManage

  const load = async () => {
    const ticket = ++request.current
    importSequence.current++
    setLoading(true); setError(''); setCalendar(null); setImported(false); form.resetFields()
    try {
      const row = await holidayCalendarsApi.get(year)
      if (ticket !== request.current) return
      if (row.year !== year || !Array.isArray(row.holidays) || !Array.isArray(row.workdays)) throw new Error('年度数据格式不正确')
      setCalendar(row); form.setFieldsValue(formValues(row))
    } catch (e) { if (ticket === request.current) setError(errMsg(e) || '节假日数据加载失败') }
    finally { if (ticket === request.current) setLoading(false) }
  }
  useEffect(() => {
    scope.current++; void load()
    return () => { scope.current++; request.current++; importSequence.current++ }
  }, [year])

  const save = async (values: CalendarForm) => {
    if (!calendar || !canManageNow.current || saveLock.current) return
    saveLock.current = true; setSaving(true)
    const generation = scope.current
    const body: CalendarWrite = { year, holidays: splitDates(values.holidays), workdays: splitDates(values.workdays),
      source_name: values.source_name.trim(), source_url: values.source_url.trim(), published_on: values.published_on,
      note: values.note || '', complete: true, expected_version: calendar.version }
    try {
      const row = await holidayCalendarsApi.save(year, body)
      if (generation !== scope.current) return
      setCalendar(row); setImported(false); form.setFieldsValue(formValues(row))
      message.success('全年放假及补班安排已保存，已有计划不会自动改动')
    } catch (e) { if (generation === scope.current) message.error(errMsg(e)) }
    finally { saveLock.current = false; if (generation === scope.current) setSaving(false) }
  }
  const importFile = async (file: File) => {
    if (!canManageNow.current || saving || !calendar) return false
    const generation = scope.current
    const importTicket = ++importSequence.current
    try {
      if (file.size > 200_000) throw new Error('年度JSON文件不能超过200KB')
      const data = JSON.parse(await file.text())
      if (generation !== scope.current || importTicket !== importSequence.current || !canManageNow.current) return false
      if (data.year !== year || !Array.isArray(data.holidays) || !Array.isArray(data.workdays) ||
          ![...data.holidays, ...data.workdays].every(value => typeof value === 'string') ||
          typeof data.source_name !== 'string' || typeof data.source_url !== 'string' || typeof data.published_on !== 'string' ||
          (data.note !== undefined && typeof data.note !== 'string')) throw new Error('文件须为所选年度，含holidays、workdays、来源名称/链接和发布日期')
      form.setFieldsValue({ source_name: data.source_name, source_url: data.source_url, published_on: data.published_on,
        holidays: data.holidays.join('\n'), workdays: data.workdays.join('\n'), note: data.note || '', complete: false })
      setImported(true)
    } catch (e) { if (generation === scope.current && importTicket === importSequence.current) message.error(e instanceof Error ? e.message : '文件格式错误，当前输入保留') }
    return false
  }
  const exportFile = () => {
    if (!calendar) return
    const { source_name, source_url, published_on, holidays, workdays, note } = calendar
    const content = JSON.stringify({ year, source_name, source_url, published_on, holidays, workdays, note }, null, 2)
    const url = URL.createObjectURL(new Blob([content], { type: 'application/json' }))
    const a = document.createElement('a'); a.href = url; a.download = `holiday-calendar-${year}.json`; a.click(); URL.revokeObjectURL(url)
  }

  return <div className="settings-work-page">
    <WorkPageHeader title="节假日设置" description="按国务院年度通知核对放假与调休补班，保留来源与发布日期。" />
    <Space wrap style={{ marginBottom: 16 }}><Typography.Text>年度</Typography.Text><InputNumber aria-label="节假日年度" value={year} min={1900} max={2200} precision={0} disabled={saving} onChange={value => { if (value !== null && value >= 1900 && value <= 2200) setYear(value) }} /><Button disabled={saving || loading} onClick={() => void load()}>重新加载</Button></Space>
    {loading ? <Spin /> : error ? <Alert type="error" message="节假日数据加载失败" description={error} action={<Button onClick={() => void load()}>重试</Button>} /> : calendar && <WorkSection title={`${year} 年安排`}>
      <HolidayCalendarNotice years={calendar.available ? [] : [year]} settingsLink={false} />
      <Typography.Paragraph>{calendar.source_kind === 'bundled_official' ? <Tag color="green">内置官方已核对</Tag> : calendar.source_kind === 'maintained' ? <Tag color="blue">人工维护，请核对来源</Tag> : <Tag>尚无全年数据</Tag>}放假 {calendar.holidays.length} 天 · 调休补班 {calendar.workdays.length} 天</Typography.Paragraph>
      {calendar.available && <Typography.Paragraph>来源：<a href={calendar.source_url} target="_blank" rel="noreferrer">{calendar.source_name}</a> · 发布于 {calendar.published_on}</Typography.Paragraph>}
      <Space wrap style={{ marginBottom: 12 }}><Button icon={<DownloadOutlined />} onClick={exportFile}>{calendar.available ? '导出年度JSON' : '下载年度JSON格式'}</Button>{canManage && <Upload accept=".json,application/json" showUploadList={false} beforeUpload={importFile} disabled={saving}><Button icon={<UploadOutlined />} disabled={saving}>从JSON文件填入</Button></Upload>}</Space>
      {imported && <Alert type="info" showIcon message="文件已填入，尚未保存；请核对全年放假及补班日期，再确认保存。" style={{ marginBottom: 12 }} />}
      <Form form={form} layout="vertical" style={{ maxWidth: 760 }} onFinish={save} disabled={!canManage || saving}>
        <Form.Item name="source_name" label="来源名称" rules={[{ required: true, whitespace: true }]}><Input maxLength={300} /></Form.Item>
        <Form.Item name="source_url" label="来源链接（HTTPS）" rules={[{ required: true, type: 'url' }]}><Input maxLength={1000} /></Form.Item>
        <Form.Item name="published_on" label="来源发布日期" rules={[{ required: true, pattern: /^\d{4}-\d{2}-\d{2}$/, message: '填写YYYY-MM-DD日期' }]}><Input placeholder="YYYY-MM-DD" /></Form.Item>
        <Form.Item name="holidays" label="全年放假日期" rules={[{ required: true, whitespace: true, message: '按通知填入全年日期' }]} extra="YYYY-MM-DD，每行一个或用逗号分隔。不会自动推算农历或预测未来年度。"><Input.TextArea rows={6} /></Form.Item>
        <Form.Item name="workdays" label="调休补班日期" extra="包括周六/周日的补班；为空表示已核对全年无调休补班。"><Input.TextArea rows={3} /></Form.Item>
        <Form.Item name="note" label="说明"><Input.TextArea rows={2} maxLength={5000} /></Form.Item>
        {canManage ? <><Form.Item name="complete" valuePropName="checked" rules={[{ validator: (_, value) => value ? Promise.resolve() : Promise.reject(new Error('请先核对全年安排')) }]}><Checkbox>已核对全年放假和调休补班日期，并保留发布来源</Checkbox></Form.Item><Button type="primary" htmlType="submit" loading={saving}>保存全年安排</Button></> : <Typography.Paragraph type="secondary">当前账号仅可查看，请联系管理员维护年度安排。</Typography.Paragraph>}
      </Form>
      <Typography.Paragraph type="secondary" style={{ marginTop: 12 }}>开启项目“跳过法定节假日”时，补班日覆盖周末休息；项目手动休息日仍优先。保存不会自动修改已排或已发布的工作。</Typography.Paragraph>
    </WorkSection>}
  </div>
}
