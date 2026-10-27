import { useEffect, useRef, useState } from 'react'
import { Alert, Button, DatePicker, Input, Modal, Select, Space, Spin, message } from 'antd'
import dayjs from 'dayjs'
import { api, errMsg } from '../api/client'
import { weeklyPlansApi, type WeeklyPlanView } from '../api/weeklyPlans'
import { useAuth } from '../stores/auth'
import { ensureVerifiedAccount } from '../utils/verifiedAccount'
import { todayInTimezone } from '../utils/date'

type Context={projectId?:string;personId?:string;date?:string;entry?:any;task?:{id:string;name:string};repair?:{unitId:string;eventId:string;title:string}}
const monday=(date:string)=>{const value=dayjs(date);return value.subtract((value.day()+6)%7,'day').format('YYYY-MM-DD')}
export default function WorkAssignmentModal({context,onClose,onSaved}:{context:Context|null;onClose:()=>void;onSaved:()=>void}) {
  const {user}=useAuth()
  const pid=context?.projectId||context?.entry?.project_id
  const scope=JSON.stringify([pid,context?.repair?.unitId,context?.repair?.eventId,!!context,user?.id,user?.role,user?.permission_version,user?.permission_overrides])
  const [snapshot,setSnapshot]=useState<{scope:string;data?:WeeklyPlanView}>({scope:''})
  const data=snapshot.scope===scope?snapshot.data:undefined
  const [week,setWeek]=useState(()=>monday(todayInTimezone()))
  const [people,setPeople]=useState<string[]>([])
  const [mode,setMode]=useState<'finish'|'in_progress'>('finish')
  const [notes,setNotes]=useState('')
  const [error,setError]=useState('')
  const [exists,setExists]=useState(false)
  const [loading,setLoading]=useState(false)
  const [saving,setSaving]=useState(false)
  const epoch=useRef(0),lock=useRef(false),weekEdited=useRef(false)
  const allowed=!!data?.permissions.edit&&user?.role!=='readonly'&&user?.permission_overrides?.['project.manage_schedule']!==false&&user?.permission_overrides?.['project.read']!==false
  const load=async()=>{
    if(!pid||!context?.repair)return
    const current=epoch.current;setLoading(true);setError('')
    try{ensureVerifiedAccount(user?.id);const result=await weeklyPlansApi.list(pid,week,1);if(current!==epoch.current)return;setSnapshot({scope,data:result});if(!weekEdited.current)setWeek(monday(context.date||todayInTimezone(result.timezone)))}
    catch(failure){if(current===epoch.current)setError(errMsg(failure))}
    finally{if(current===epoch.current)setLoading(false)}
  }
  useEffect(()=>{epoch.current++;lock.current=false;weekEdited.current=false;setSnapshot({scope});setWeek(monday(context?.date||todayInTimezone()));setPeople(context?.personId?[context.personId]:[]);setMode('finish');setNotes('');setError('');setExists(false);setSaving(false);void load();return()=>{epoch.current++}},[scope])
  const save=async()=>{
    if(!allowed||!context?.repair||!pid||exists||lock.current)return
    const current=epoch.current;lock.current=true;setSaving(true);setError('')
    try{
      ensureVerifiedAccount(user?.id)
      const result=await api.post(`/projects/${pid}/vehicle-units/${context.repair.unitId}/events/${context.repair.eventId}/weekly-plans`,{week_start:week,assignee_ids:people,mode,notes})
      if(current!==epoch.current)return
      if(result.data?.created===false){setExists(true);return}
      message.success('维修周计划草稿已保存，请到周计划核对并发布');onClose();onSaved()
    }catch(failure){if(current===epoch.current)setError(errMsg(failure))}
    finally{if(current===epoch.current){lock.current=false;setSaving(false)}}
  }
  return <Modal title={context?.repair?`安排维修周计划 · ${context.repair.title}`:'工作安排已合并到周计划'} open={!!context} onCancel={()=>{if(!saving)onClose()}} onOk={()=>void save()} okText="保存为周计划草稿" confirmLoading={saving} okButtonProps={{disabled:!allowed||exists||loading||!context?.repair}} cancelButtonProps={{disabled:saving}} maskClosable={false}>
    {!context?.repair?<p>在项目周计划中选择工作项、周和负责人。<a href={pid?`/pm/projects/${encodeURIComponent(pid)}/plan?view=weeks`:'/pm/projects'}>打开项目周计划</a></p>:<Space direction="vertical" style={{width:'100%'}}>
      <p>维修记录保留原始事实；本次安排保存为草稿，发布后才通知计划负责人。</p>
      {loading&&<Spin aria-label="正在读取维修计划人员"/>}
      {error&&<Alert type="error" message={error} action={<Button disabled={saving} onClick={()=>void load()}>重新读取</Button>}/>}
      {data&&!allowed&&<Alert type="info" message="本账号当前没有此项目的周计划维护权限"/>}
      {exists&&<Alert type="warning" message="本周已存在此维修计划格，本次填写尚未修改原安排" description={<a href={`/pm/projects/${pid}/plan?view=weeks&week=${week}`}>前往周计划核对并修改</a>}/>}
      <DatePicker aria-label="维修计划周" picker="week" value={dayjs(week)} allowClear={false} disabled={saving} onChange={value=>{if(value){weekEdited.current=true;setWeek(monday(value.format('YYYY-MM-DD')));setExists(false)}}}/>
      <Select aria-label="维修计划负责人" mode="multiple" allowClear value={people} disabled={saving||!allowed} onChange={setPeople} placeholder="可多人，也可留空待明确认领" options={data?.members.filter(person=>person.active).map(person=>({value:person.id,label:person.name}))}/>
      <Select aria-label="维修计划方式" value={mode} disabled={saving} onChange={setMode} options={[{value:'finish',label:'本周完成'},{value:'in_progress',label:'本周进行中'}]}/>
      <Input.TextArea aria-label="维修安排说明" value={notes} disabled={saving} maxLength={2000} rows={3} onChange={event=>setNotes(event.target.value)}/>
    </Space>}
  </Modal>
}
