import { useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Checkbox, DatePicker, Empty, Input, InputNumber, Modal, Select, Space, Spin, Switch, Table, Tag, Typography } from 'antd'
import { Link, useLocation } from 'react-router-dom'
import dayjs from 'dayjs'
import type { Project } from '../../../api'
import { errMsg } from '../../../api/client'
import { weeklyPlansApi, planWarningText, type WeeklyPlanView, type PlanCell, type PlanInput, type PlanWork, type DraftRule, type DraftPreview, type DraftRequest, type DraftRules, type PlanWeek, type PlanSettings } from '../../../api/weeklyPlans'
import { useAuth } from '../../../stores/auth'
import { isProjectWriteBlocked } from '../../../constants/status'
import { ensureVerifiedAccount } from '../../../utils/verifiedAccount'
import { todayInTimezone } from '../../../utils/date'
import { parseDispositionFilename } from '../../../utils/download'
import HolidayCalendarNotice from '../../../components/HolidayCalendarNotice'
import { WorkPageHeader } from '../../../components/WorkPage'
import './WeeklyPlan.css'

const monday = (value: string) => { const d = dayjs(value); return d.subtract((d.day() + 6) % 7, 'day').format('YYYY-MM-DD') }
const stateText: Record<string,string> = { unknown:'完成情况待核对', completed:'已完成', overdue:'已逾期', in_progress:'计划进行中', planned:'计划完成' }
type Edit = { cell?: PlanCell; input: PlanInput; scopeMode: 'all'|'type'|'batch'; confirmIntent: boolean; intentReason: string }
const scopeText = (cell: PlanCell) => cell.scope.label || cell.scope.vehicle_type || (cell.scope.vehicle_unit_ids.length ? `指定 ${cell.scope.vehicle_unit_ids.length} 台` : cell.kind === 'vehicle' ? '全部适用车辆' : '本工作项')

const restDays = (week: PlanWeek, settings: PlanSettings) => Array.from({ length: 7 }, (_, offset) => dayjs(week.week_start).add(offset, 'day')).filter(date => {
  const value = date.format('YYYY-MM-DD')
  if (settings.rest_days.includes(value)) return true
  if (week.makeup_workdays.includes(value)) return false
  return settings.skip_holidays && week.holiday_days.includes(value) || settings.rest_mode === 'two' && date.day() === 6 || settings.rest_mode !== 'none' && date.day() === 0
}).map(date => date.format('MM-DD'))

export default function SchedulePage({projectId,project,onProjectChange}: {projectId:string;project?:Project;onProjectChange?:()=>void|Promise<void>;embedded?:boolean}) {
  const {user}=useAuth()
  const location=useLocation()
  const requestedWeek=new URLSearchParams(location.search).get('week')
  const [start,setStart]=useState(()=>monday(requestedWeek&&/^\d{4}-\d{2}-\d{2}$/.test(requestedWeek)?requestedWeek:todayInTimezone(project?.timezone)))
  const [count,setCount]=useState(6)
  useEffect(()=>{if(requestedWeek&&/^\d{4}-\d{2}-\d{2}$/.test(requestedWeek)&&dayjs(requestedWeek).isValid())setStart(monday(requestedWeek))},[requestedWeek])
  const [phaseId,setPhaseId]=useState<string>()
  const [includeCancelled,setIncludeCancelled]=useState(false)
  const scope=JSON.stringify([projectId,project?.status,project?.capabilities,user?.id,user?.role,user?.permission_version,user?.permission_overrides,user?.system_permissions,start,count,includeCancelled])
  const [snapshot,setSnapshot]=useState<{scope:string;data?:WeeklyPlanView;error?:string}>({scope:''})
  const data=snapshot.scope===scope?snapshot.data:undefined
  const error=snapshot.scope===scope?snapshot.error:undefined
  const [loading,setLoading]=useState(false)
  const [busy,setBusy]=useState(false)
  const [actionError,setActionError]=useState('')
  const [selection,setSelection]=useState<string[]>([])
  const [editor,setEditor]=useState<Edit>()
  const [editStale,setEditStale]=useState(false)
  const [publishOpen,setPublishOpen]=useState(false)
  const [cancelCell,setCancelCell]=useState<PlanCell>()
  const [cancelReason,setCancelReason]=useState('')
  const [draftOpen,setDraftOpen]=useState(false)
  const [rules,setRules]=useState<DraftRule[]>([])
  const [recommendations,setRecommendations]=useState<DraftRules>()
  const [firstWeek,setFirstWeek]=useState<string>()
  const [preview,setPreview]=useState<{body:DraftRequest;value:DraftPreview}>()
  const epoch=useRef(0),request=useRef(0),lock=useRef(false)
  const allowed=!!data?.permissions.edit&&!isProjectWriteBlocked(project?.status)&&user?.role!=='readonly'&&user?.permission_overrides?.['project.manage_schedule']!==false&&user?.permission_overrides?.['project.read']!==false
  const canExport=!!data?.permissions.export&&user?.permission_overrides?.['project.export']!==false
  const load=async()=>{
    const ticket=++request.current,current=epoch.current;setLoading(true)
    try {
      const next=await weeklyPlansApi.list(projectId,start,count,includeCancelled)
      if(current!==epoch.current||ticket!==request.current)return
      if(!Array.isArray(next.cells)||!Array.isArray(next.weeks)||!Array.isArray(next.work_items)||!next.permissions){setSnapshot({scope,error:'周计划响应不完整，请重新读取'});return}
      setSnapshot({scope,data:next});setSelection([])
    }catch(failure){if(current===epoch.current&&ticket===request.current)setSnapshot({scope,error:errMsg(failure)})}
    finally{if(current===epoch.current&&ticket===request.current)setLoading(false)}
  }
  useEffect(()=>{
    epoch.current++;lock.current=false;setBusy(false);setSnapshot({scope});setSelection([]);setEditor(undefined);setPreview(undefined);setDraftOpen(false);setRules([]);setFirstWeek(undefined);setRecommendations(undefined);setPublishOpen(false);setCancelCell(undefined);setActionError('');setPhaseId(undefined)
    void load();return()=>{epoch.current++;request.current++}
  },[scope])
  const write=async(operation:()=>Promise<unknown>,finish:()=>void)=>{
    if(!allowed||lock.current)return
    const current=epoch.current;lock.current=true;setBusy(true);setActionError('')
    try {ensureVerifiedAccount(user?.id);await operation();if(current!==epoch.current)return;finish();await load();await onProjectChange?.()}
    catch(failure){if(current===epoch.current){setActionError(errMsg(failure));setEditStale(true);setPreview(undefined)}}
    finally{if(current===epoch.current){lock.current=false;setBusy(false)}}
  }
  const works=useMemo(()=>data?.work_items.flatMap(phase=>phase.work_items.map(work=>({...work,phase_id:phase.id,phase_name:phase.name})))??[],[data])
  const visibleWorks=works.filter(work=>!phaseId||work.phase_id===phaseId)
  const visibleCells=data?.cells.filter(cell=>!phaseId||cell.phase_id===phaseId)??[]
  const chosen=visibleCells.filter(cell=>selection.includes(cell.id)&&!cell.published&&!cell.is_cancelled)
  const work=works.find(item=>item.id===editor?.input.task_id)
  const openNew=(item?:PlanWork,week=start)=>{setEditStale(false);setActionError('');setEditor({scopeMode:'all',confirmIntent:false,intentReason:'',input:{task_id:item?.id??'',scope:{vehicle_unit_ids:[]},week_start:week,mode:'finish',target_count:null,assignee_ids:[],notes:''}})}
  const openCell=(cell:PlanCell)=>{setEditStale(false);setActionError('');setEditor({cell,confirmIntent:false,intentReason:'',scopeMode:cell.scope.vehicle_type?'type':cell.scope.vehicle_unit_ids.length?'batch':'all',input:{task_id:cell.task_id,scope:{...cell.scope,vehicle_unit_ids:[...cell.scope.vehicle_unit_ids]},week_start:cell.week_start,mode:cell.mode,target_count:cell.target_count,assignee_ids:[...cell.assignee_ids],notes:cell.notes}})}
  const patch=(change:Partial<PlanInput>)=>setEditor(current=>current?{...current,input:{...current.input,...change}}:current)
  const valid=!!editor&&!!work&&!!editor.input.week_start&&(!editor.cell?.intent_review_required||editor.confirmIntent&&!!editor.intentReason.trim())&&(work.kind!=='vehicle'||editor.scopeMode==='all'||editor.scopeMode==='type'&&!!editor.input.scope.vehicle_type||editor.scopeMode==='batch'&&editor.input.scope.vehicle_unit_ids.length>0)&&(work.kind!=='vehicle'||editor.input.mode!=='finish'||Number.isInteger(editor.input.target_count)&&editor.input.target_count!>0)
  const save=()=>{
    if(!editor||!valid||editStale)return
    const input={...editor.input,target_count:work?.kind==='vehicle'&&editor.input.mode==='finish'?editor.input.target_count:null,scope:work?.kind==='vehicle'?editor.input.scope:{vehicle_unit_ids:[]}}
    const { task_id, ...changes } = input
    void write(()=>editor.cell?weeklyPlansApi.update(projectId,editor.cell.id,{...changes,version:editor.cell.version,...(editor.cell.intent_review_required?{confirm_intent:true,reason:editor.intentReason.trim()}:{})}):weeklyPlansApi.create(projectId,{...changes,task_id}),()=>setEditor(undefined))
  }
  const readRecommendations=async()=>{
    if(!allowed||lock.current)return
    const current=epoch.current;lock.current=true;setBusy(true);setActionError('');setPreview(undefined)
    try{
      ensureVerifiedAccount(user?.id)
      const result=await weeklyPlansApi.defaultRules(projectId)
      if(current!==epoch.current)return
      if(!Array.isArray(result.rules)||!Array.isArray(result.suggestions)||!Array.isArray(result.warnings)){setActionError('默认初稿建议响应不完整，可重试读取或手动选择关键事件');return}
      setRecommendations(result);setRules(result.rules)
    }catch(failure){if(current===epoch.current)setActionError(`默认初稿建议暂不可读取：${errMsg(failure)}。可重试或手动选择关键事件。`)}
    finally{if(current===epoch.current){lock.current=false;setBusy(false)}}
  }
  const openDraft=()=>{setPreview(undefined);setRules([]);setFirstWeek(undefined);setRecommendations(undefined);setDraftOpen(true);void readRecommendations()}
  const reloadRecommendations=()=>{
    if(rules.length)Modal.confirm({title:'重新读取初稿建议',content:'将用当前建议替换本次尚未保存的阶段规则，现有周计划保持原样。',okText:'读取并替换',cancelText:'保留填写',onOk:()=>void readRecommendations()})
    else void readRecommendations()
  }
  const draftBody:DraftRequest={phase_rules:rules,...(firstWeek?{first_week:firstWeek}:{})}
  const inspectDraft=async()=>{
    if(!allowed||lock.current||!rules.length)return
    const current=epoch.current;lock.current=true;setBusy(true);setActionError('');setPreview(undefined)
    try{ensureVerifiedAccount(user?.id);const result=await weeklyPlansApi.preview(projectId,draftBody);if(current!==epoch.current)return;if(!Array.isArray(result.proposals)||!Array.isArray(result.warnings)||!result.preview_token){setActionError('初稿响应不完整，请重新预览');return}setPreview({body:draftBody,value:result})}
    catch(failure){if(current===epoch.current)setActionError(errMsg(failure))}
    finally{if(current===epoch.current){lock.current=false;setBusy(false)}}
  }
  const excel=async()=>{
    if(!canExport||lock.current)return
    lock.current=true;setBusy(true);const current=epoch.current
    try{ensureVerifiedAccount(user?.id);const result=await weeklyPlansApi.excel(projectId,{week_start:start,weeks:count,phase_id:phaseId});if(current!==epoch.current)return;const url=URL.createObjectURL(result.data);const a=document.createElement('a');a.href=url;a.download=parseDispositionFilename(result.headers?.['content-disposition'])||'周计划.xlsx';a.click();URL.revokeObjectURL(url)}
    catch(failure){if(current===epoch.current)setActionError(errMsg(failure))}
    finally{if(current===epoch.current){lock.current=false;setBusy(false)}}
  }
  const print=()=>{document.documentElement.classList.add('printing-weekly-plans');window.addEventListener('afterprint',()=>document.documentElement.classList.remove('printing-weekly-plans'),{once:true});window.print()}
  const missing=[...new Set([...(project?.missing_holiday_years??[]),...(data?.weeks.flatMap(week=>week.missing_holiday_years)??[])])]
  return <section className="weekly-plan-page">
    <WorkPageHeader title="周计划" description="行是工作项，列是周；负责人和计划与实际完成分别记录。" tools={<Space wrap><Button loading={loading} disabled={busy} onClick={()=>void load()}>刷新周计划</Button>{allowed&&<><Button disabled={busy} onClick={()=>openNew()}>新增计划格</Button><Button disabled={busy} onClick={openDraft}>生成初稿</Button></>}<Link to={`/pm/projects/${projectId}/edit?section=schedule`}>排期设置</Link></Space>}/>
    <HolidayCalendarNotice years={missing}/>
    {error&&<Alert type="error" message="周计划暂不可读取" description={error} action={<Button onClick={()=>void load()}>重试读取</Button>}/>}
    {actionError&&!editor&&!draftOpen&&<Alert type="error" message="操作未完成" description={actionError}/>}
    <Space wrap className="weekly-plan-toolbar">
      <Button disabled={busy} onClick={()=>setStart(dayjs(start).subtract(count,'week').format('YYYY-MM-DD'))}>前{count}周</Button>
      <DatePicker aria-label="计划起始周" picker="week" value={dayjs(start)} allowClear={false} disabled={busy} onChange={date=>date&&setStart(monday(date.format('YYYY-MM-DD')))}/>
      <Button disabled={busy} onClick={()=>setStart(dayjs(start).add(count,'week').format('YYYY-MM-DD'))}>后{count}周</Button>
      <Select aria-label="显示周数" value={count} disabled={busy} onChange={setCount} options={[4,6,8,12].map(value=>({value,label:`${value}周`}))}/>
      <Select aria-label="按阶段筛选周计划" value={phaseId} disabled={busy} allowClear placeholder="全部阶段" onChange={value=>{setPhaseId(value);setSelection([])}} options={data?.work_items.map(phase=>({value:phase.id,label:phase.name}))}/>
      {allowed&&<label><Switch aria-label="显示已取消计划格" checked={includeCancelled} disabled={busy} onChange={setIncludeCancelled}/> 显示已取消</label>}
      {allowed&&data?.permissions.publish&&<><Button disabled={busy} onClick={()=>setSelection(visibleCells.filter(cell=>!cell.published&&!cell.is_cancelled).map(cell=>cell.id))}>选择当前范围草稿</Button><Button type="primary" disabled={!chosen.length||busy} onClick={()=>{setEditStale(false);setActionError('');setPublishOpen(true)}}>发布已选 {chosen.length} 格</Button></>}
      {canExport&&<><Button disabled={busy} onClick={()=>void excel()}>导出 Excel</Button><Button disabled={busy} onClick={print}>导出 PDF / 打印</Button></>}
    </Space>
    {loading&&!data&&<Spin aria-label="正在读取周计划"/>}
    {data&&<>
      {data.warnings.length>0&&<Alert type="warning" message="计划需要核对" description={<ul>{data.warnings.map((warning,index)=><li key={index}>{planWarningText(warning)}</li>)}</ul>}/>}
      <div className="weekly-plan-print">
        <header><h2>{project?.name||'项目'} · 周计划</h2><p>{start} 起 {count} 周 · 现场时区 {data.timezone} · 当前范围已发布 {visibleCells.filter(cell=>cell.published&&!cell.is_cancelled).length}{allowed?` / 草稿 ${visibleCells.filter(cell=>!cell.published&&!cell.is_cancelled).length}`:''}</p></header>
        {!visibleWorks.length?<Empty description="本范围尚无工作项，请先在计划的工作项页维护"/>:<div className="weekly-plan-scroll" role="region" aria-label="周计划表" tabIndex={0}><table className="weekly-plan-table"><thead><tr><th>阶段 / 工作项</th>{data.weeks.map(week=><th key={week.week_start}><strong>{week.week_start.slice(5)} — {week.week_end.slice(5)}</strong>{week.holiday_days.length>0&&<small>节假日：{week.holiday_days.map(day=>day.slice(5)).join('、')}</small>}{week.makeup_workdays.length>0&&<small>补班：{week.makeup_workdays.map(day=>day.slice(5)).join('、')}</small>}{restDays(week,data.settings).length>0&&<small>项目休息日：{restDays(week,data.settings).join('、')}</small>}{week.missing_holiday_years.length>0&&<small>年度安排待核对</small>}</th>)}</tr></thead><tbody>{visibleWorks.map(item=><tr key={item.id}><th><small>{item.phase_name}{item.group_label?` · ${item.group_label}`:''}</small><strong>{item.name}</strong><Tag>{item.kind==='vehicle'?'车辆环节':'非车辆工作'}</Tag></th>{data.weeks.map(week=>{
          const cells=visibleCells.filter(cell=>cell.task_id===item.id&&cell.week_start===week.week_start)
          return <td key={week.week_start}>{cells.map(cell=><article key={cell.id} className={cell.is_cancelled?'is-cancelled':''}>
            <Space wrap>{allowed&&!cell.published&&!cell.is_cancelled&&<Checkbox aria-label={`选择${cell.task_name} ${cell.week_start} ${scopeText(cell)}`} checked={selection.includes(cell.id)} onChange={event=>setSelection(current=>event.target.checked?[...current,cell.id]:current.filter(id=>id!==cell.id))}/>}<Tag color={cell.published?'blue':undefined}>{cell.is_cancelled?'已取消':cell.published?'已发布':'草稿'}</Tag></Space>
            <div>{scopeText(cell)}</div><strong>{cell.intent_review_required?'原计划意图待核对':cell.mode==='in_progress'?'进行中':cell.kind==='other'?'完成工作项':cell.target_count==null?'计划台数待核对':`完成 ${cell.target_count} 台`}</strong>
            <div>{cell.assignees.length?cell.assignees.map(person=>`${person.name}${person.active?'':'（已停用）'}`).join('、'):'未分配'}</div>
            <div><Tag color={cell.completion.overdue?'red':cell.completion.is_complete?'green':undefined}>{stateText[cell.completion.state]||'完成情况待核对'}</Tag>{cell.completion.required_count!=null&&cell.kind==='vehicle'&&<small>实际 {cell.completion.completed_count??'未知'} / 累计计划 {cell.completion.required_count}</small>}</div>
            {cell.completion.unidentified_completed!>0&&<small>含迁移车号待核对数量 {cell.completion.unidentified_completed}</small>}
            {cell.notes&&<p>{cell.notes}</p>}
            {cell.permissions.edit&&allowed&&<Button size="small" disabled={busy} aria-label={`编辑${cell.task_name} ${cell.week_start} ${scopeText(cell)}`} onClick={()=>openCell(cell)}>修改计划</Button>}
            {cell.source_metadata&&<details><summary>历史计划来源（只读）</summary><pre>{JSON.stringify(cell.source_metadata,null,2)}</pre></details>}
          </article>)}{allowed&&<Button type="dashed" disabled={busy} aria-label={`安排${item.name} ${week.week_start}`} onClick={()=>openNew(item,week.week_start)}>{cells.length?'另建范围':'安排'}</Button>}{!allowed&&!cells.length&&<span>未安排</span>}</td>
        })}</tr>)}</tbody></table></div>}
      </div>
    </>}
    <Modal title={editor?.cell?'修改周计划格':'新增周计划格'} open={!!editor&&!!data} onCancel={()=>{if(!busy)setEditor(undefined)}} onOk={save} okText="保存计划" confirmLoading={busy} okButtonProps={{disabled:!allowed||!valid||editStale}} cancelButtonProps={{disabled:busy}} maskClosable={!busy}>
      {editor&&<Space direction="vertical" style={{width:'100%'}}>
        {actionError&&<Alert type="error" message={actionError}/>}{editStale&&<Alert type="warning" message="请重新读取最新计划后再保存" action={<Button disabled={busy} onClick={()=>{setEditor(undefined);void load()}}>重新读取周计划</Button>}/>}
        {editor.cell?.intent_review_required&&<>
          <Alert type="warning" message="旧计划的完成意图待核对" description="原数量包含未知量或无法直接转换的计划。请核对原始来源，明确本次计划方式和车辆台数；原日程保留只读。核对前不会判完成或逾期。"/>
          <Checkbox checked={editor.confirmIntent} disabled={busy} onChange={event=>setEditor(current=>current?{...current,confirmIntent:event.target.checked}:current)}>已核对原始来源，按本次填写重新定义计划</Checkbox>
          <Input.TextArea aria-label="旧计划意图核对理由" value={editor.intentReason} disabled={busy} maxLength={1000} placeholder="说明已核对的来源和本次计划依据" onChange={event=>setEditor(current=>current?{...current,intentReason:event.target.value}:current)}/>
        </>}
        <label>工作项<Select aria-label="周计划工作项" value={editor.input.task_id||undefined} disabled={busy||!!editor.cell} style={{width:'100%'}} onChange={id=>patch({task_id:id,target_count:null,scope:{vehicle_unit_ids:[]}})} options={works.map(item=>({value:item.id,label:`${item.phase_name} · ${item.name}`}))}/></label>
        <label>计划周<DatePicker aria-label="计划完成周" picker="week" value={dayjs(editor.input.week_start)} allowClear={false} disabled={busy} onChange={value=>value&&patch({week_start:monday(value.format('YYYY-MM-DD'))})}/></label>
        <Select aria-label="计划方式" value={editor.input.mode} disabled={busy} onChange={mode=>patch({mode,target_count:null})} options={[{value:'finish',label:'本周完成'},{value:'in_progress',label:'本周进行中'}]}/>
        {work?.kind==='vehicle'&&<>
          <Select aria-label="车辆范围方式" value={editor.scopeMode} disabled={busy} onChange={scopeMode=>setEditor(current=>current?{...current,scopeMode,input:{...current.input,scope:{vehicle_unit_ids:[]}}}:current)} options={[{value:'all',label:'全部适用车辆'},{value:'type',label:'按车型'},{value:'batch',label:'指定车辆批次'}]}/>
          {editor.scopeMode==='type'&&<Select aria-label="计划车型" value={editor.input.scope.vehicle_type} disabled={busy} onChange={vehicle_type=>patch({scope:{vehicle_type,vehicle_unit_ids:[]}})} options={data?.vehicle_types.filter(type=>!work.applicable_vehicle_types.length||work.applicable_vehicle_types.includes(type)).map(type=>({value:type,label:type}))}/>}
          {editor.scopeMode==='batch'&&<Select aria-label="计划车辆批次" mode="multiple" value={editor.input.scope.vehicle_unit_ids} disabled={busy} onChange={vehicle_unit_ids=>patch({scope:{vehicle_unit_ids}})} options={data?.vehicles.map(unit=>({value:unit.id,label:unit.label}))}/>}
          {editor.input.mode==='finish'&&<InputNumber aria-label="计划完成车辆台数" min={1} precision={0} value={editor.input.target_count} disabled={busy} onChange={value=>patch({target_count:value})} placeholder="填写正整数台数"/>}
        </>}
        <Select aria-label="计划负责人" mode="multiple" allowClear value={editor.input.assignee_ids} disabled={busy} onChange={assignee_ids=>patch({assignee_ids})} options={data?.members.map(person=>({value:person.id,label:`${person.name}${person.active?'':'（已停用）'}`,disabled:!person.active&&!editor.input.assignee_ids.includes(person.id)}))}/>
        <Typography.Text type="secondary">可分配多人；留空不会自动认领。计划负责人不代表实际完成人。</Typography.Text>
        <Input.TextArea aria-label="周计划备注" value={editor.input.notes} disabled={busy} onChange={event=>patch({notes:event.target.value})} maxLength={2000}/>
        {editor.cell&&<Button danger={!editor.cell.is_cancelled} disabled={busy||editStale} onClick={()=>{setCancelCell(editor.cell);setCancelReason('')}}>{editor.cell.is_cancelled?'恢复此格':'取消此格'}</Button>}
      </Space>}
    </Modal>
    <Modal title={cancelCell?.is_cancelled?'恢复计划格':'取消计划格'} open={!!cancelCell&&!!data} onCancel={()=>{if(!busy)setCancelCell(undefined)}} okText="确认变更" confirmLoading={busy} okButtonProps={{disabled:!cancelReason.trim()||!allowed||editStale}} onOk={()=>cancelCell&&void write(()=>weeklyPlansApi.update(projectId,cancelCell.id,{version:cancelCell.version,is_cancelled:!cancelCell.is_cancelled,reason:cancelReason.trim()}),()=>{setCancelCell(undefined);setEditor(undefined)})}>
      {actionError&&<Alert type="error" message={actionError}/>}
      {editStale&&<Button disabled={busy} onClick={()=>{setCancelCell(undefined);setEditor(undefined);void load()}}>重新读取周计划</Button>}
      <Input.TextArea aria-label="计划取消或恢复理由" value={cancelReason} disabled={busy} onChange={event=>setCancelReason(event.target.value)} maxLength={1000}/>
    </Modal>
    <Modal title="发布选定周计划" open={publishOpen&&!!data} onCancel={()=>{if(!busy)setPublishOpen(false)}} okText="确认发布" confirmLoading={busy} okButtonProps={{disabled:!chosen.length||!allowed||editStale}} onOk={()=>void write(()=>weeklyPlansApi.publish(projectId,chosen.map(cell=>({id:cell.id,version:cell.version}))),()=>setPublishOpen(false))}>
      {actionError&&<Alert type="error" message={actionError}/>}
      {editStale&&<Button disabled={busy} onClick={()=>{setPublishOpen(false);void load()}}>重新读取周计划</Button>}
      <p>仅发布下面 {chosen.length} 格；实际完成保持独立记录。</p><ul>{chosen.map(cell=><li key={cell.id}>{cell.task_name} · {cell.week_start} · {scopeText(cell)} · {cell.assignees.map(person=>person.name).join('、')||'未分配'}</li>)}</ul>
    </Modal>
    <Modal title="生成周计划初稿" open={draftOpen&&!!data} width={780} onCancel={()=>{if(!busy)setDraftOpen(false)}} okText="保存为草稿" confirmLoading={busy} okButtonProps={{disabled:!allowed||!preview||JSON.stringify(preview.body)!==JSON.stringify(draftBody)||!preview.value.proposals.length}} onOk={()=>preview&&void write(()=>weeklyPlansApi.draft(projectId,{...preview.body,preview_token:preview.value.preview_token}),()=>setDraftOpen(false))}>
      <p>为需要安排的阶段选择关键事件。未选择的阶段不生成；缺少真实日期、明确台数或环节时保留警告。现有格不覆盖，负责人由你明确选择。</p>
      {actionError&&<Alert type="error" message={actionError}/>}
      <Space wrap><Button disabled={busy} onClick={reloadRecommendations}>重新读取初稿建议</Button>{busy&&<Spin aria-label="正在处理初稿"/>}</Space>
      {recommendations&&<div className="weekly-plan-suggestions">
        <p>{recommendations.rules.length?`已按可核对来源提出 ${recommendations.rules.length} 个阶段的默认规则；下方可继续修改，预览后才会保存。`:'没有可用的默认规则，请按实际工作阶段手动选择关键事件。'}</p>
        {recommendations.warnings.map((warning,index)=><Alert key={index} type="warning" message={planWarningText(warning)}/>)}
        {recommendations.suggestions.length>0&&<details><summary>查看初始建议的来源、窗口与理由</summary>{recommendations.suggestions.map(item=><div key={item.phase_id}><strong>{item.phase_name}</strong><div>{item.source_label}</div><div>参考窗口：{item.window_start&&item.window_end?`${item.window_start} — ${item.window_end}`:'待核对'} · 建议周：{item.week_start||'待核对'}</div><p>{item.reason}</p></div>)}</details>}
      </div>}
      <DatePicker aria-label="初稿起始周" picker="week" placeholder="起始周（可选）" value={firstWeek?dayjs(firstWeek):null} disabled={busy} onChange={value=>{setFirstWeek(value?monday(value.format('YYYY-MM-DD')):undefined);setPreview(undefined)}}/>
      {data?.work_items.map(phase=>{const rule=rules.find(item=>item.phase_id===phase.id);return <div key={phase.id} className="weekly-plan-rule"><strong>{phase.name}</strong><Select aria-label={`${phase.name}关键事件`} value={rule?.anchor} allowClear placeholder="本阶段不生成" disabled={busy} onChange={anchor=>{setRules(current=>anchor?[...current.filter(item=>item.phase_id!==phase.id),{phase_id:phase.id,anchor,offset_weeks:rule?.offset_weeks??0,mode:rule?.mode??'finish'}]:current.filter(item=>item.phase_id!==phase.id));setPreview(undefined)}} options={[{value:'before_ship',label:'发车前倒推'},{value:'after_arrival',label:'到场后安排'}]}/>{rule&&<><InputNumber aria-label={`${phase.name}偏移周数`} min={0} precision={0} value={rule.offset_weeks} disabled={busy} onChange={value=>{setRules(current=>current.map(item=>item.phase_id===phase.id?{...item,offset_weeks:value??0}:item));setPreview(undefined)}}/><Select aria-label={`${phase.name}初稿方式`} value={rule.mode} disabled={busy} onChange={mode=>{setRules(current=>current.map(item=>item.phase_id===phase.id?{...item,mode}:item));setPreview(undefined)}} options={[{value:'finish',label:'计划完成'},{value:'in_progress',label:'进行中'}]}/></>}</div>})}
      <Button disabled={!rules.length||busy} onClick={()=>void inspectDraft()}>预览初稿</Button>
      {preview&&<><ul>{preview.value.warnings.map((warning,index)=><li key={index}>{planWarningText(warning)}</li>)}</ul><Table rowKey={(_,index)=>String(index)} size="small" dataSource={preview.value.proposals} pagination={{pageSize:8}} columns={[{title:'阶段',dataIndex:'phase_name'},{title:'工作项',dataIndex:'task_name'},{title:'周',dataIndex:'week_start'},{title:'计划',render:(_,row)=>row.mode==='in_progress'?'进行中':row.kind==='other'?'完成工作项':`${row.target_count??'待核对'} 台`}]}/></>}
    </Modal>
  </section>
}
