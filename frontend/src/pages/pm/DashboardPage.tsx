import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { Alert, Button, Card, Collapse, Empty, Spin, Table, Tag, Typography } from 'antd'
import { Link, useLocation } from 'react-router-dom'
import { useAuth } from '../../stores/auth'
import { hasSystemPermission } from '../../constants/systemPermissions'
import { projectStatusMeta } from '../../constants/status'
import VehicleProgressSummary from '../../components/VehicleProgressSummary'
import { WorkPageHeader } from '../../components/WorkPage'
import { workbenchApi, documentActionUrl, type WorkbenchOverview, type WorkbenchAction } from '../../api/workbench'
import { errMsg } from '../../api/client'
import { deadlineLabel } from '../../utils/documentDeadlines'
const WorkspaceStatistics=lazy(()=>import('../../components/WorkspaceStatistics'))

const actionLink=(row:WorkbenchAction)=><Link to={documentActionUrl(row)}>{row.code} {row.name}{row.vehicle_label?` · ${row.vehicle_label}`:''}</Link>

export default function DashboardPage() {
  const {user}=useAuth()
  const location=useLocation()
  const canWorkspace=hasSystemPermission(user,'workspace.view')
  const canStatistics=hasSystemPermission(user,'insights.view')
  const scope=JSON.stringify([user?.id,user?.role,user?.permission_version,user?.system_permissions,user?.permission_overrides])
  const [snapshot,setSnapshot]=useState<{scope:string;data?:WorkbenchOverview;error?:string}>({scope:''})
  const data=snapshot.scope===scope?snapshot.data:undefined
  const error=snapshot.scope===scope?snapshot.error:undefined
  const [loading,setLoading]=useState(false)
  const sequence=useRef(0)
  const load=async()=>{
    if(!canWorkspace)return
    const ticket=++sequence.current;setLoading(true);setSnapshot(current=>current.scope===scope?{...current,error:''}:{scope})
    try { const next=await workbenchApi.overview();if(!Array.isArray(next.projects))throw new Error('工作台响应不完整');if(ticket===sequence.current)setSnapshot({scope,data:next}) }
    catch(failure) { if(ticket===sequence.current)setSnapshot({scope,error:errMsg(failure)}) }
    finally { if(ticket===sequence.current)setLoading(false) }
  }
  useEffect(()=>{setSnapshot({scope});if(canWorkspace)void load();return()=>{sequence.current++}},[scope,canWorkspace])
  const projects=data?.projects??[]
  const week=data?.this_week_documents
  const plan=data?.weekly_plan
  const planRows=plan?.state==='available'?[...(plan.items??[]),...(plan.unknown_items??[]).map(row=>({...row,state:'unknown'}))]:[]
  const overdue=projects.flatMap(project=>(project.document_attention?.overdue??[]).map(row=>({...row,project_id:project.id,project_name:project.name,timezone:project.document_attention!.timezone})))
  const signoffs=projects.flatMap(project=>project.next_signoff?[{...project.next_signoff,project_id:project.id,project_name:project.name}]:[])
  return <div style={{padding:24}}>
    <WorkPageHeader title="工作台" description="按本周待办、资料和车辆进度推进项目。" tools={canWorkspace&&<Button loading={loading} onClick={()=>void load()}>刷新工作台</Button>}/>
    {error&&<Alert type="error" showIcon message="工作台暂不可读取" description={error} action={<Button onClick={()=>void load()}>重试读取</Button>}/>}
    {loading&&!data&&<Spin aria-label="正在读取工作台"/>}
    {canWorkspace&&data&&<>
      <Card title="本周待办" size="small" style={{marginBottom:16}} extra={<Link to="/pm/people">查看人员与本周安排</Link>}>
        {plan?.state!=='available'||!Array.isArray(plan.items)
          ? <Alert type="info" message="本周计划暂不可读取" description="可重试读取，或到项目计划中查看。"/>
          : !planRows.length ? <Empty description="已发布周计划暂无逾期或待核对的工作" image={Empty.PRESENTED_IMAGE_SIMPLE}/>
          : <Table rowKey={row=>row.id} size="small" pagination={{pageSize:8}} dataSource={planRows} columns={[
            {title:'项目',dataIndex:'project_name'},{title:'工作项',render:(_,row)=><Link to={row.url}>{row.name}</Link>},
            {title:'计划周',dataIndex:'week_start'},
            {title:'状态',render:(_,row)=>row.state==='unknown'?<Tag color="gold">完成情况待核对</Tag>:<Tag color="red">已逾期未完成</Tag>},
          ]}/>}
      </Card>
      <Card title="本周待交资料" size="small" style={{marginBottom:16}}>
        {week===undefined?<Alert type="warning" message="本周资料尚未读取"/>:!week.length?<Empty description="本周暂无待交资料" image={Empty.PRESENTED_IMAGE_SIMPLE}/>:<Table rowKey={row=>`${row.project_id}:${row.id}`} size="small" pagination={{pageSize:8}} dataSource={week} columns={[
          {title:'项目',dataIndex:'project_name'},{title:'资料',render:(_,row)=>actionLink(row)},
          {title:'截止',render:(_,row)=><>{deadlineLabel(row.due_at,row.timezone??'Asia/Shanghai')}{row.due_is_estimated?'（预计）':''}</>},
        ]}/>}
      </Card>
      <Card title="逾期资料" size="small" style={{marginBottom:16}}>
        {projects.some(project=>!project.document_attention)?<Alert type="warning" message="逾期资料尚未完整读取"/>:!overdue.length?<Empty description="暂无逾期资料" image={Empty.PRESENTED_IMAGE_SIMPLE}/>:<Table rowKey={row=>`${row.project_id}:${row.id}`} size="small" pagination={{pageSize:8}} dataSource={overdue} columns={[
          {title:'项目',dataIndex:'project_name'},{title:'资料',render:(_,row)=>actionLink(row)},
          {title:'逾期',render:(_,row)=><Tag color="red">{row.overdue_days} 天</Tag>},
        ]}/>}
      </Card>
      <Card title="项目与车辆进度" size="small" style={{marginBottom:16}}>
        <Table rowKey="id" size="small" scroll={{x:560}} dataSource={projects} pagination={{pageSize:10}} columns={[
          {title:'项目',render:(_,row)=><Link to={`/pm/projects/${encodeURIComponent(row.id)}/overview`}>{row.name}</Link>},
          {title:'状态',render:(_,row)=>{const status=projectStatusMeta(row.status);return <Tag color={status.color}>{status.label}</Tag>}},
          {title:'车辆进度',render:(_,row)=><VehicleProgressSummary value={row.vehicle_progress}/>},
          {title:'逾期资料',render:(_,row)=>row.document_attention?<Link to={`/pm/projects/${encodeURIComponent(row.id)}/documents?filter=overdue`}>{row.document_attention.overdue_count} 项</Link>:<Typography.Text type="secondary">未读取</Typography.Text>},
        ]}/>
      </Card>
      <Card title="下一张待交签单" size="small" style={{marginBottom:16}}>
        {projects.some(project=>project.next_signoff===undefined)?<Alert type="warning" message="签单状态尚未完整读取"/>:!signoffs.length?<Empty description="暂无待交签单" image={Empty.PRESENTED_IMAGE_SIMPLE}/>:<ul>{signoffs.map(row=><li key={`${row.project_id}:${row.id}`}><Typography.Text>{row.project_name} · </Typography.Text>{actionLink(row)}</li>)}</ul>}
      </Card>
    </>}
    {canStatistics&&<div id="statistics"><Collapse defaultActiveKey={!canWorkspace||location.hash==='#statistics'?['statistics']:[]} items={[{key:'statistics',label:'统计',children:<Suspense fallback={<Spin aria-label="正在加载统计"/>}><WorkspaceStatistics/></Suspense>}]} /></div>}
  </div>
}
