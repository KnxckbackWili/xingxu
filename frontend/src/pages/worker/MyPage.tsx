import { useEffect, useState } from 'react'
import { Alert, Button, Card, DatePicker, Empty, Space, Typography } from 'antd'
import { Link } from 'react-router-dom'
import { api, errMsg } from '../../api/client'
import { WorkPageHeader } from '../../components/WorkPage'
import { useAuth } from '../../stores/auth'
import { hasSystemPermission } from '../../constants/systemPermissions'
import RecordsPage from './RecordsPage'
import type { FieldRecord } from '../../api/fieldWeek'

function PersonalReport() {
  const { user } = useAuth(); const [week, setWeek] = useState<string>(); const [data, setData] = useState<{ records: FieldRecord[]; summary: { completed: number; assisted: number; actual_records: number } }>(); const [error, setError] = useState(''); const [revision, setRevision] = useState(0)
  useEffect(() => { let live = true; setData(undefined); setError(''); api.get('/worker/week-report', { params: week ? { week_start: week } : undefined, headers: { 'X-AGV-Expected-Account': user?.id || '' } }).then(r => { if (live) setData(r.data) }).catch(e => { if (live) setError(errMsg(e)) }); return () => { live = false } }, [user?.id, week, revision])
  return <Card title="我的周报" extra={<DatePicker picker="week" aria-label="周报周" onChange={value => setWeek(value?.subtract((value.day() + 6) % 7, 'day').format('YYYY-MM-DD'))} />}>
    {error ? <Alert type="error" message={error} action={<Button onClick={() => setRevision(n => n + 1)}>重试</Button>} /> : data ? <><Typography.Paragraph>当前有效实际记录 {data.summary.actual_records} 条 · 完成 {data.summary.completed} 条 · 协助 {data.summary.assisted} 条</Typography.Paragraph>{data.records.map(row => <p key={row.id}>{row.completion_date} · {row.project_name} · {row.target_name} · {row.action === 'retract' ? row.restores_id ? '原事实已恢复' : '撤回' : row.is_done ? '完成' : '未完成'}{row.assisted_user_name ? ` · 协助 ${row.assisted_user_name}` : ''}</p>)}{!data.records.length && <Empty description="当周没有实际记录" />}</> : <Typography.Text>正在读取周报…</Typography.Text>}
  </Card>
}
export default function MyPage() {
  const { user } = useAuth()
  return <div className="worker-work-page"><WorkPageHeader title="我的记录" description="按周查看实际完成、协助、修订与撤回记录。" primary={<Link to="/worker/week">返回本周</Link>} />{hasSystemPermission(user, 'personal.records.read') ? <Space direction="vertical" style={{ width: '100%' }}><RecordsPage /><PersonalReport /></Space> : <Alert type="info" message="本人记录查看权限已关闭" />}</div>
}
