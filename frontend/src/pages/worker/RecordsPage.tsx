import dayjs from 'dayjs'
import { useEffect, useRef, useState } from 'react'
import { Alert, Button, DatePicker, Empty, Skeleton, Tag, Typography } from 'antd'
import { fieldWeekApi, type FieldRecord } from '../../api/fieldWeek'
import { errMsg } from '../../api/client'
import FieldOperationModal, { type FieldTarget } from '../../components/FieldOperationModal'
import { useAuth } from '../../stores/auth'
import { hasSystemPermission } from '../../constants/systemPermissions'

const actionLabel = (record: FieldRecord) => record.action === 'retract' ? record.restores_id ? '修订已撤回，原事实已恢复' : '已撤回' : record.action === 'edit' ? '修订' : record.is_done ? '完成' : '未完成'

/** My actual records for one week: a summary line, then one row per record with edit/withdraw where still allowed. */
export default function RecordsPage() {
  const { user } = useAuth(); const [records, setRecords] = useState<FieldRecord[]>([]); const [week, setWeek] = useState<string>(); const [error, setError] = useState(''); const [loading, setLoading] = useState(false); const [revision, setRevision] = useState(0); const [target, setTarget] = useState<FieldTarget>(); const seq = useRef(0)
  useEffect(() => { const ticket = ++seq.current; setRecords([]); setTarget(undefined); setLoading(true); setError(''); fieldWeekApi.records(week ? { week_start: week } : undefined, user?.id).then(data => { if (ticket === seq.current) setRecords(data.records) }).catch(e => { if (ticket === seq.current) setError(errMsg(e)) }).finally(() => { if (ticket === seq.current) setLoading(false) }); return () => { seq.current++ } }, [user?.id, week, revision])
  const open = (record: FieldRecord, retract = false) => setTarget({ ...record, name: record.target_name, window: record, record_id: record.id, retract })
  const effective = records.filter(record => record.action !== 'retract')
  const canReport = hasSystemPermission(user, 'worker.report')
  return <section className="records-section" aria-label="按周查看实际记录">
    <div className="records-toolbar">
      <DatePicker picker="week" aria-label="记录周" value={week ? dayjs(week) : dayjs()} allowClear={false} onChange={value => setWeek(value?.subtract((value.day() + 6) % 7, 'day').format('YYYY-MM-DD'))} />
      {!loading && !error && <span className="records-summary">这周 {effective.length} 条记录 · 完成 {effective.filter(record => record.is_done).length} 条 · 协助 {effective.filter(record => record.assisted_user_name).length} 条</span>}
    </div>
    <Typography.Paragraph type="secondary" className="records-note">完成日期和登记时间分开保存。补记窗口内、后面没人改过的记录可以修改或撤回，原始版本一直保留。</Typography.Paragraph>
    {error && <Alert type="error" message={error} action={<Button onClick={() => setRevision(value => value + 1)}>重试</Button>} />}
    {loading ? <Skeleton active paragraph={{ rows: 3 }} /> : !error && !records.length ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="本周暂无实际记录" />
      : <ul className="records-list">{records.map(record => <li key={record.id}>
        <div className="records-main">
          <strong>{record.target_name}</strong><Tag>{actionLabel(record)}</Tag>
          <small className="records-meta"><span>{record.project_name}</span><span>完成日期 {record.completion_date}</span><span>登记时间 {record.recorded_at} · 操作人 {record.actor_name}{record.assisted_user_name ? ` · 协助 ${record.assisted_user_name}` : ''}</span></small>
          {record.note && <p>{record.note}</p>}{record.operation_reason && record.operation_reason !== record.note && <p>操作理由：{record.operation_reason}</p>}
        </div>
        {canReport && (record.can_edit || record.can_retract) && <span className="records-actions">{record.can_edit && <Button size="small" onClick={() => open(record)}>修改</Button>}{record.can_retract && <Button size="small" danger onClick={() => open(record, true)}>撤回</Button>}</span>}
      </li>)}</ul>}
    {target && <FieldOperationModal key={target.record_id} target={target} onClose={() => setTarget(undefined)} onSaved={() => setRevision(value => value + 1)} />}
  </section>
}
