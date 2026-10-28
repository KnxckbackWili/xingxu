import { useEffect, useRef, useState } from 'react'
import { Alert, Card, Col, Row, Spin, Statistic, Table, Tag } from 'antd'
import { useAuth } from '../stores/auth'
import { workbenchApi, type WorkspaceStatisticsData } from '../api/workbench'
import { errMsg } from '../api/client'
import { projectStatusMeta } from '../constants/status'
import { hasSystemPermission } from '../constants/systemPermissions'
import { RefreshAction } from './IconAction'
export default function WorkspaceStatistics() {
  const { user } = useAuth()
  const allowed = hasSystemPermission(user, 'insights.view')
  const scope=JSON.stringify([user?.id,user?.role,user?.permission_version,user?.system_permissions,user?.permission_overrides])
  const [snapshot,setSnapshot]=useState<{scope:string;data?:WorkspaceStatisticsData;error?:string}>({scope:''})
  const data=snapshot.scope===scope?snapshot.data:undefined
  const error=snapshot.scope===scope?snapshot.error:undefined
  const [loading, setLoading] = useState(false)
  const sequence = useRef(0)
  const load = async () => {
    const ticket=++sequence.current
    setLoading(true);setSnapshot(current=>current.scope===scope?{...current,error:''}:{scope})
    try { const next=await workbenchApi.statistics();if(ticket===sequence.current)setSnapshot({scope,data:next}) }
    catch(failure) { if(ticket===sequence.current)setSnapshot({scope,error:errMsg(failure)}) }
    finally { if(ticket===sequence.current)setLoading(false) }
  }
  useEffect(()=>{setSnapshot({scope});if(allowed)void load();return()=>{sequence.current++}},[scope,allowed])
  if(!allowed)return null
  return <section aria-label="统计">
    <RefreshAction label="刷新统计" onClick={load} loading={loading} />
    {error&&<Alert type="error" showIcon message="统计暂不可读取" description={error}/>}
    {loading&&!data&&<Spin aria-label="正在读取统计"/>}
    {data&&<>
      <Row gutter={[12,12]} style={{marginTop:12}}>{[
        ['可见项目',data.projects],['进行中项目',data.active_projects],['已完成项目',data.completed_projects],
        ['本周待交资料',data.documents.this_week_count],['逾期资料',data.documents.overdue_count],['未闭环问题',data.issues.open],
      ].map(([title,value])=><Col key={title} xs={12} md={8}><Card size="small"><Statistic title={title} value={value}/></Card></Col>)}</Row>
      <Card size="small" title="车辆进度" style={{marginTop:12}}>
        已完成 {data.vehicle_progress.completed} / {data.vehicle_progress.target} 个车辆环节
        {data.vehicle_progress.quantity_unknown||data.vehicle_progress.percent===null ? <Tag>车辆范围待核对</Tag> : <Tag>{data.vehicle_progress.percent}%</Tag>}
        {!!data.vehicle_progress.unidentified_completed&&<Tag>含迁移记录，待补车号</Tag>}
      </Card>
      <Table rowKey="status" size="small" pagination={false} dataSource={data.status_distribution} style={{marginTop:12}} columns={[
        {title:'项目状态',render:(_,row)=>projectStatusMeta(row.status).label},{title:'项目数',dataIndex:'count'},
      ]}/>
    </>}
  </section>
}
