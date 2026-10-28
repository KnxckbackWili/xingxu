import { useEffect, useState } from 'react'
import { Alert, Card, DatePicker, Empty, Select, Space, Table, Tag, Typography } from 'antd'
import { api, errMsg } from '../../../api/client'
import { useAuth } from '../../../stores/auth'
import { WorkPageHeader } from '../../../components/WorkPage'
import type { FieldRecord } from '../../../api/fieldWeek'
import './ReportPage.css'
import { PrinterOutlined } from '@ant-design/icons'
import { IconAction, RefreshAction } from '../../../components/IconAction'
type Report = { period_label: string; summary: { actual_records: number; completed_work: number; vehicle_completions: number; assisted_count: number; issues_opened: number; open_issues: number }; completed_items: FieldRecord[]; next_plan_state: string; next_plan: { id: string; week_start: string; task: string; mode: string; target_count: number | null }[] | null; document_summary: { submitted: number; versions: number; overdue: number }; document_submissions: { version_id: string; code: string; name: string; filename: string; uploaded_at: string }[]; vehicle_progress_changes: { event_id: string; date: string; title: string; asset_code?: string }[]; risks: { id: string; name: string; code: string }[] }
export default function ReportPage({ projectId, projectName }: { projectId: string; projectName: string }) {
  const {user}=useAuth()
  const [period, setPeriod] = useState('week'); const [refDate, setRefDate] = useState<string>(); const [data, setData] = useState<Report>(); const [error, setError] = useState(''); const [revision, setRevision] = useState(0)
  useEffect(() => { let live = true; setData(undefined); setError(''); api.get(`/projects/${projectId}/report`, { params: { period, ...(refDate ? { ref_date: refDate } : {}) }, headers: { 'X-AGV-Expected-Account': user?.id || '' } }).then(r => { if (live) setData(r.data) }).catch(e => { if (live) setError(errMsg(e)) }); return () => { live = false } }, [projectId, period, refDate, revision, user?.id])
  return <div className="project-report-page"><WorkPageHeader title={`${projectName} · 报告`} description="实际操作、资料提交和车辆进度变化；计划不作为实际完成凭证。" tools={<Space wrap><Select aria-label="报告周期" value={period} onChange={setPeriod} options={[{ value: 'week', label: '周报' }, { value: 'month', label: '月报' }]} /><DatePicker aria-label="报告参考日期" onChange={v => setRefDate(v?.format('YYYY-MM-DD'))} /><RefreshAction onClick={() => setRevision(n => n + 1)} /><IconAction bordered label="打印 / 保存 PDF" icon={<PrinterOutlined />} onClick={() => window.print()} /></Space>} />{error && <Alert type="error" message={error} />}
    {data && <><Typography.Paragraph>{data.period_label}</Typography.Paragraph><Card title="当期实际情况"><Space wrap><Tag>实际操作 {data.summary.actual_records}</Tag><Tag>工作完成登记 {data.summary.completed_work}</Tag><Tag>车辆环节完成登记 {data.summary.vehicle_completions}</Tag><Tag>协助记录 {data.summary.assisted_count}</Tag><Tag>未闭环问题 {data.summary.open_issues}</Tag></Space></Card>
      <Card title="实际记录"><Table<FieldRecord> rowKey="id" dataSource={data.completed_items} pagination={{ pageSize: 20 }} scroll={{ x: 760 }} columns={[{ title: '完成日期', dataIndex: 'completion_date' }, { title: '登记时间', dataIndex: 'recorded_at' }, { title: '工作 / 环节', dataIndex: 'target_name' }, { title: '实际操作人', dataIndex: 'actor_name' }, { title: '协助对象', dataIndex: 'assisted_user_name' }, { title: '操作', render: (_, r) => r.action === 'retract' ? r.restores_id ? '原事实已恢复' : '撤回' : r.action === 'edit' ? '修订' : r.is_done ? '完成' : '未完成' }]} /></Card>
      <Card title="资料提交"><p>提交 {data.document_summary.submitted} 项 · {data.document_summary.versions} 个版本 · 当前逾期 {data.document_summary.overdue} 项</p>{data.document_submissions.map(row => <p key={row.version_id}>{row.code} {row.name} · {row.filename} · {row.uploaded_at}</p>)}</Card>
      <Card title="车辆进度变化">{data.vehicle_progress_changes.length ? data.vehicle_progress_changes.map(row => <p key={row.event_id}>{row.date} · {row.asset_code || ''} {row.title}</p>) : <Empty description="当期没有车辆进度变化记录" />}</Card>
      <Card title="下一周期已发布周计划">{data.next_plan_state === 'unavailable' ? <Alert type="warning" message="周计划尚未读取" /> : data.next_plan?.length ? data.next_plan.map(row => <p key={row.id}>{row.week_start} · {row.task} · {row.mode === 'in_progress' ? '进行中' : row.target_count == null ? '计划完成工作' : `计划完成 ${row.target_count} 台`}</p>) : <Empty description="下一周期没有已发布计划" />}</Card>
      {!!data.risks.length && <Card title="逾期资料">{data.risks.map(row => <p key={row.id}>{row.code} {row.name}</p>)}</Card>}
    </>}
  </div>
}
