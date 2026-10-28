import { useNavigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { Alert, Button, Space, Spin } from 'antd'
import { api, errMsg } from '../api/client'
import { openWorkDetail } from '../stores/workDetail'
import AcceptanceDecision, { acceptanceDecisionText } from './AcceptanceDecision'
import { RefreshAction } from './IconAction'

export default function HandoverSummary({ projectId, onUse }: { projectId: string; onUse?: (text: string) => void }) {
  const navigate = useNavigate()
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState(false)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setData(null); setError('')
    api.get(`/projects/${projectId}/handover-summary`, { signal:controller.signal }).then(r=>{if(!controller.signal.aborted){ if(!r.data?.counts) throw new Error('交接数据格式不正确'); setData(r.data) }})
      .catch(e=>{if(!controller.signal.aborted)setError(errMsg(e))})
    return ()=>controller.abort()
  },[projectId,attempt])
  if(error) return <Alert type="error" message="交接事项读取失败" description={error} action={<Button onClick={()=>setAttempt(x=>x+1)}>重试</Button>}/>
  if(!data) return <Spin/>
  const lines = [`${data.project_name} · 交接时待跟进：`, `未完工作 ${data.counts.tasks} 项；现场问题 ${data.counts.issues} 项；车辆故障 ${data.counts.faults} 项；待提交资料 ${data.counts.documents} 项。`,
    ...(data.acceptance_summary ? [acceptanceDecisionText(data.acceptance_summary)] : []),
    ...data.tasks.map((t:any)=>`工作：${t.name}`), ...data.faults.map((f:any)=>`故障：${f.asset_code} · ${f.title}`), ...data.issues.map((i:any)=>`问题：${i.title}`), ...data.documents.map((d:any)=>`资料：${d.code ? d.code + ' · ' : ''}${d.name}${d.vehicle_label ? ' / ' + d.vehicle_label : ''}`)]
  const note = '（仅列出部分事项，完整记录请到项目对应工作区查看。）'
  let summary = lines.slice(0,2).join('\n')
  let truncated = data.counts.tasks>data.tasks.length || data.counts.issues>data.issues.length || data.counts.faults>data.faults.length || data.counts.documents>data.documents.length
  for (const line of lines.slice(2)) {
    if (summary.length + line.length + note.length + 2 > 900) { truncated = true; break }
    summary += `\n${line}`
  }
  if (truncated) summary += `\n${note}`
  const visible = (items: any[]) => expanded ? items : items.slice(0, 3)
  return <section className="handover-summary">
    <div className="work-section-heading"><strong>接手后需要跟进</strong><Space><RefreshAction onClick={()=>setAttempt(x=>x+1)} />{onUse&&<Button size="small" onClick={()=>onUse(summary)}>带入交接说明</Button>}</Space></div>
    <p>根据项目现有记录整理，点击工作可继续处理。交接说明中再补充客户承诺和下一步重点。</p>
    <AcceptanceDecision summary={data.acceptance_summary} />
    <div className="handover-counts"><span>未完工作 <b>{data.counts.tasks}</b></span><span>现场问题 <b>{data.counts.issues}</b></span><span>车辆故障 <b>{data.counts.faults}</b></span><span>待提交资料 <b>{data.counts.documents}</b></span></div>
    <details open><summary>待办与遗留事项</summary>
      {visible(data.tasks).map((t:any)=><div key={t.id}><button className="task-name-link" onClick={()=>openWorkDetail({projectId,taskId:t.id,onChanged:()=>setAttempt(x=>x+1)})}>{t.name}</button></div>)}
      {visible(data.faults).map((f:any)=><p key={f.id}>故障 · {f.asset_code} · {f.title}</p>)}
      {visible(data.issues).map((i:any)=><p key={i.id}>问题 · {i.title}</p>)}
      {visible(data.documents).map((d:any)=><div key={d.id}><button className="task-name-link" onClick={()=>navigate(`/pm/projects/${encodeURIComponent(projectId)}/documents`)}>资料 · {d.code ? `${d.code} · ` : ''}{d.name}{d.vehicle_label ? ` / ${d.vehicle_label}` : ''}</button></div>)}
      {!Object.values(data.counts).some(Boolean)&&<p>当前工作清单中没有待跟进事项，请仍核对验收结论和现场口头约定。</p>}
    </details>
    {[data.tasks,data.issues,data.faults,data.documents].some(items=>items.length>3)&&<Button type="link" size="small" onClick={()=>setExpanded(value=>!value)}>{expanded?'收起部分事项':'展开更多待跟进事项'}</Button>}
    {(data.counts.tasks>15||data.counts.issues>10||data.counts.faults>10||data.counts.documents>15)&&<p>此处展示部分事项；完整记录请在对应工作区查看。</p>}
  </section>
}
