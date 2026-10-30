import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Card, DatePicker, Empty, Form, Input, Modal, Select, Space, Table, Tag } from 'antd'
import dayjs from 'dayjs'
import { Link, useSearchParams } from 'react-router-dom'
import { api, errMsg } from '../../api/client'
import { ensureVerifiedAccount } from '../../utils/verifiedAccount'
import { WorkPageHeader } from '../../components/WorkPage'
import UnavailabilityManager from '../../components/UnavailabilityManager'
import { useAuth } from '../../stores/auth'
import { hasSystemPermission } from '../../constants/systemPermissions'
import { RefreshAction } from '../../components/IconAction'

type Cell = { id: string; project_id: string; project_name: string; week_start: string; mode: string; target_count: number | null; task_name?: string }
type Person = { id: string; name: string; cells: Cell[]; unavailable: { start_date: string; end_date: string; reason?: string; note?: string }[]; conflicts: { week_start: string; project_ids: string[] }[] }
type View = { state: string; people: Person[]; week_start: string; weeks: number; warnings: { message: string }[]; calendar: { missing_holiday_years: number[] }[]; permissions: { manage_unavailability: boolean } }
export default function PeoplePlanPage() {
  const [params] = useSearchParams(); const { user } = useAuth(); const teamAllowed = hasSystemPermission(user, 'workspace.view'); const [scope, setScope] = useState<'mine' | 'team'>(teamAllowed && params.get('view') !== 'mine' ? 'team' : 'mine'); const [week, setWeek] = useState<string>(); const [data, setData] = useState<View>(); const [error, setError] = useState(''); const [revision, setRevision] = useState(0); const [loading, setLoading] = useState(false); const generation = useRef(0)
  const [manage, setManage] = useState(false); const [create, setCreate] = useState(false); const [saving, setSaving] = useState(false); const [saveError, setSaveError] = useState(''); const savingLock = useRef(false); const [form] = Form.useForm()
  useEffect(() => { const seq = ++generation.current; setData(undefined); setError(''); setLoading(true); api.get('/people/weeks', { params: { scope, weeks: 4, ...(week ? { week_start: week } : {}) }, headers: { 'X-AGV-Expected-Account': user?.id || '' } }).then(r => { if (generation.current === seq) setData(r.data) }).catch(e => { if (generation.current === seq) setError(errMsg(e)) }).finally(() => { if (generation.current === seq) setLoading(false) }); return () => { generation.current++ } }, [user?.id, scope, week, revision])
  useEffect(() => { setScope(teamAllowed && params.get('view') !== 'mine' ? 'team' : 'mine') }, [teamAllowed, params])
  const canManage = hasSystemPermission(user, 'system.availability.manage') && !!data?.permissions.manage_unavailability
  const columns = [{ title: '人员', dataIndex: 'name', key: 'name', fixed: 'left' as const, width: 120 }, ...Array.from({ length: 4 }, (_, i) => {
    const start = dayjs(data?.week_start || week).add(i * 7, 'day').format('YYYY-MM-DD'); const end = dayjs(start).add(6, 'day').format('YYYY-MM-DD')
    return { title: `${start} 当周`, key: start, width: 240, render: (_: unknown, person: Person) => <Space direction="vertical">{person.cells.filter(c => c.week_start === start).map(c => <div key={c.id}><Link to={`/pm/projects/${c.project_id}/plan`}>{c.project_name}</Link> · {c.task_name || '工作项'}<div>{c.mode === 'in_progress' ? '进行中' : c.target_count == null ? '计划完成工作' : `计划完成 ${c.target_count} 台`}</div></div>)}{person.unavailable.filter(p => p.start_date <= end && p.end_date >= start).map((p, index) => <Tag key={index} color="orange">不可用 {p.start_date}–{p.end_date}{p.reason ? ` · ${p.reason}` : ''}</Tag>)}{person.conflicts.some(c => c.week_start === start) && <Tag color="red">同周多个项目安排，请核对</Tag>}</Space> }
  })]
  const save = async () => {
    if (savingLock.current || !canManage) return
    let values; try { values = await form.validateFields() } catch { return }
    savingLock.current = true; setSaving(true); setSaveError('')
    try { ensureVerifiedAccount(user?.id); await api.post(`/users/${values.user_id}/unavailability`, { start_date: values.range[0].format('YYYY-MM-DD'), end_date: values.range[1].format('YYYY-MM-DD'), reason: values.reason, note: values.note || '' }, { headers: { 'X-AGV-Expected-Account': user!.id } }); setCreate(false); setRevision(n => n + 1) } catch (e) { setSaveError(errMsg(e)) } finally { savingLock.current = false; setSaving(false) }
  }
  return <div><WorkPageHeader title="人员" description="按周核对人员在可见项目中的已发布安排和不可用时段；同一周多个项目会提示冲突。" tools={<Space wrap><Select aria-label="人员范围" value={scope} onChange={setScope} options={[...(teamAllowed ? [{ value: 'team', label: '团队周计划' }] : []), { value: 'mine', label: '本人周计划' }]} /><DatePicker picker="week" aria-label="人员计划起始周" value={week ? dayjs(week) : dayjs()} allowClear={false} onChange={value => setWeek(value?.subtract((value.day() + 6) % 7, 'day').format('YYYY-MM-DD'))} /><RefreshAction onClick={() => setRevision(n => n + 1)} loading={loading} /></Space>} />
    {error && <Alert type="error" message="人员周计划未能读取" description={error} />}{data?.warnings.map((w, i) => <Alert key={i} type="warning" message={w.message} />)}{[...new Set(data?.calendar.flatMap(row => row.missing_holiday_years) || [])].length > 0 && <Alert type="warning" message={`缺少年度节假日数据：${[...new Set(data?.calendar.flatMap(row => row.missing_holiday_years) || [])].join('、')}`} />}
    {canManage && <Space style={{ marginBottom: 12 }}><Button onClick={() => { setCreate(true); setSaveError(''); form.resetFields() }}>登记不可用时段</Button><Button onClick={() => setManage(true)}>管理不可用时段</Button></Space>}
    <Card>{data?.people.length ? <Table<Person> rowKey="id" columns={columns} dataSource={data.people} pagination={{ pageSize: 20 }} scroll={{ x: 1080 }} /> : <Empty description={data?.state === 'unavailable' || error ? '周计划状态未知' : '当前范围没有已发布安排'} />}</Card>
    {manage && data && <UnavailabilityManager people={data.people} onClose={() => setManage(false)} onChanged={() => setRevision(n => n + 1)} />}
    <Modal open={create} title="登记不可用时段" onCancel={() => !saving && setCreate(false)} onOk={() => void save()} confirmLoading={saving} okText="保存" cancelText="取消">{saveError && <Alert type="error" message={saveError} />}<Form form={form} layout="vertical"><Form.Item name="user_id" label="人员" rules={[{ required: true }]}><Select options={data?.people.map(p => ({ value: p.id, label: p.name }))} /></Form.Item><Form.Item name="range" label="不可用日期" rules={[{ required: true }]}><DatePicker.RangePicker /></Form.Item><Form.Item name="reason" label="原因" rules={[{ required: true }]}><Input maxLength={100} /></Form.Item><Form.Item name="note" label="说明"><Input.TextArea maxLength={500} /></Form.Item></Form></Modal>
  </div>
}
