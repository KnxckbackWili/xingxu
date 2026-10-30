import dayjs from 'dayjs'
import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Card, DatePicker, Empty, Space, Tag, Typography } from 'antd'
import { fieldWeekApi, type FieldRecord } from '../../api/fieldWeek'
import { errMsg } from '../../api/client'
import FieldOperationModal, { type FieldTarget } from '../../components/FieldOperationModal'
import { useAuth } from '../../stores/auth'
import { hasSystemPermission } from '../../constants/systemPermissions'

export default function RecordsPage() {
  const { user } = useAuth(); const [records, setRecords] = useState<FieldRecord[]>([]); const [week, setWeek] = useState<string>(); const [error, setError] = useState(''); const [loading, setLoading] = useState(false); const [revision, setRevision] = useState(0); const [target, setTarget] = useState<FieldTarget>(); const seq = useRef(0)
  useEffect(() => { const ticket = ++seq.current; setRecords([]); setTarget(undefined); setLoading(true); setError(''); fieldWeekApi.records(week ? { week_start: week } : undefined, user?.id).then(data => { if (ticket === seq.current) setRecords(data.records) }).catch(e => { if (ticket === seq.current) setError(errMsg(e)) }).finally(() => { if (ticket === seq.current) setLoading(false) }); return () => { seq.current++ } }, [user?.id, week, revision])
  const open = (record: FieldRecord, retract = false) => setTarget({ ...record, name: record.target_name, window: record, record_id: record.id, retract })
  return <Card loading={loading} title="按周查看实际记录" extra={<DatePicker picker="week" aria-label="记录周" value={week ? dayjs(week) : dayjs()} allowClear={false} onChange={value => setWeek(value?.subtract((value.day() + 6) % 7, 'day').format('YYYY-MM-DD'))} />}>
    <Typography.Paragraph>完成日期与登记时间分别保留。本人补记窗口内、且未被后续操作改变的记录可修改或撤回；原始版本一直保留。</Typography.Paragraph>
    {error && <Alert type="error" message={error} action={<Button onClick={() => setRevision(value => value + 1)}>重试</Button>} />}
    {!error && !records.length && <Empty description="本周暂无实际记录" />}
    {records.map(record => <Card size="small" key={record.id} style={{ marginBottom: 10 }} title={`${record.project_name} · ${record.target_name}`}>
      <Space wrap><Tag>{record.action === 'retract' ? record.restores_id ? '修订已撤回，原事实已恢复' : '已撤回' : record.action === 'edit' ? '修订' : record.is_done ? '完成' : '未完成'}</Tag><span>完成日期 {record.completion_date}</span></Space><p>登记时间 {record.recorded_at} · 操作人 {record.actor_name}{record.assisted_user_name ? ` · 协助 ${record.assisted_user_name}` : ''}</p><p style={{ whiteSpace: 'pre-wrap' }}>{record.note}</p>{record.operation_reason && record.operation_reason !== record.note && <p>操作理由：{record.operation_reason}</p>}
      {hasSystemPermission(user, 'worker.report') && <Space>{record.can_edit && <Button onClick={() => open(record)}>修改</Button>}{record.can_retract && <Button danger onClick={() => open(record, true)}>撤回</Button>}</Space>}
    </Card>)}
    {target && <FieldOperationModal key={target.record_id} target={target} onClose={() => setTarget(undefined)} onSaved={() => setRevision(value => value + 1)} />}
  </Card>
}
