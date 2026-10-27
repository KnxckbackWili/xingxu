import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Input, Modal, Radio, Space, Spin, Switch } from 'antd'
import dayjs from 'dayjs'
import type { Project } from '../../../api'
import { errMsg } from '../../../api/client'
import { weeklyPlansApi, planWarningText, type PlanSettings, type SettingsResponse } from '../../../api/weeklyPlans'
import { useAuth } from '../../../stores/auth'
import { useProjectCapability, useProjectWriteBlocked } from '../../../hooks/useProjectCapability'
import { ensureVerifiedAccount } from '../../../utils/verifiedAccount'
import HolidayCalendarNotice from '../../../components/HolidayCalendarNotice'

export default function WeeklyPlanSettings({project,onReload,onDirtyChange}:{project:Project;onReload:()=>void;onDirtyChange?:(dirty:boolean)=>void}) {
  const {user}=useAuth()
  const canSchedule=useProjectCapability('project.manage_schedule',project.capabilities?.includes('project.manage_schedule')??user?.role==='pm')
  const blocked=useProjectWriteBlocked(project.status)
  const allowed=canSchedule&&!blocked&&user?.role!=='readonly'&&user?.permission_overrides?.['project.manage_schedule']!==false&&user?.permission_overrides?.['project.read']!==false
  const scope=JSON.stringify([project.id,user?.id,user?.permission_version,user?.permission_overrides])
  const [snapshot,setSnapshot]=useState<{scope:string;value?:SettingsResponse}>({scope:''})
  const [draft,setDraft]=useState<PlanSettings>({rest_mode:'none',rest_days:[],skip_holidays:false})
  const [dates,setDates]=useState('')
  const [error,setError]=useState('')
  const [loading,setLoading]=useState(false)
  const [busy,setBusy]=useState(false)
  const [stale,setStale]=useState(false)
  const epoch=useRef(0),lock=useRef(false)
  const data=snapshot.scope===scope?snapshot.value:undefined
  const read=async()=>{
    if(!allowed)return
    const current=epoch.current;setLoading(true);setError('')
    try{ensureVerifiedAccount(user?.id);const value=await weeklyPlansApi.settings(project.id);if(current!==epoch.current)return;if(!value.settings||!Number.isInteger(value.version)){setError('排期设置响应不完整，请重试');return}setSnapshot({scope,value});setDraft(value.settings);setDates(value.settings.rest_days.join('\n'));setStale(false);onDirtyChange?.(false)}
    catch(failure){if(current===epoch.current)setError(errMsg(failure))}
    finally{if(current===epoch.current)setLoading(false)}
  }
  useEffect(()=>{epoch.current++;lock.current=false;setSnapshot({scope});setBusy(false);setError('');setStale(false);onDirtyChange?.(false);void read();return()=>{epoch.current++}},[scope,allowed])
  useEffect(()=>{if(data)onDirtyChange?.(JSON.stringify(draft)!==JSON.stringify(data.settings)||dates!==data.settings.rest_days.join('\n'))},[draft,dates,data,onDirtyChange])
  const save=async()=>{
    if(!allowed||!data||stale||lock.current)return
    const rest_days=[...new Set(dates.split(/[\n,，]/).map(day=>day.trim()).filter(Boolean))].sort()
    if(rest_days.some(day=>!/^\d{4}-\d{2}-\d{2}$/.test(day)||dayjs(day).format('YYYY-MM-DD')!==day)){setError('请按每行 YYYY-MM-DD 填写有效的休息日期');return}
    const current=epoch.current;lock.current=true;setBusy(true);setError('')
    try{ensureVerifiedAccount(user?.id);const value=await weeklyPlansApi.saveSettings(project.id,{...draft,rest_days,version:data.version});if(current!==epoch.current)return;setSnapshot({scope,value});setDraft(value.settings);setDates(value.settings.rest_days.join('\n'));onDirtyChange?.(false);onReload()}
    catch(failure){if(current===epoch.current){setError(errMsg(failure));setStale(true)}}
    finally{if(current===epoch.current){lock.current=false;setBusy(false)}}
  }
  const reload=()=>Modal.confirm({title:'重新读取排期设置',content:'重新读取将替换本次尚未保存的设置。',okText:'重新读取',cancelText:'保留填写',onOk:()=>void read()})
  return <section aria-label="排期设置">
    <HolidayCalendarNotice years={project.missing_holiday_years}/>
    {!allowed?<Alert type="info" message="本账号当前没有周计划维护权限"/>:<>
      <p>在周计划上标注休息与节假日，安排时核对现场可用日期。</p>
      {error&&<Alert type="error" message={error} action={<Button onClick={reload} disabled={busy}>重新读取设置</Button>}/>}
      {stale&&<Alert type="warning" message="设置预览已失效，请重新读取后保存"/>}
      {loading&&<Spin aria-label="正在读取排期设置"/>}
      {data&&<Space direction="vertical" style={{width:'100%'}}>
        <Radio.Group aria-label="每周休息安排" value={draft.rest_mode} disabled={busy} onChange={event=>setDraft(value=>({...value,rest_mode:event.target.value}))}><Radio value="none">不固定周休息日</Radio><Radio value="one">周日休息</Radio><Radio value="two">周六、周日休息</Radio></Radio.Group>
        <label><Switch aria-label="法定节假日作为项目休息日" checked={draft.skip_holidays} disabled={busy} onChange={skip_holidays=>setDraft(value=>({...value,skip_holidays}))}/> 法定节假日作为项目休息日</label>
        <label>手动补充休息日，每行一个日期（YYYY-MM-DD）<Input.TextArea aria-label="手动休息日" value={dates} rows={4} disabled={busy} onChange={event=>setDates(event.target.value)}/></label>
        {data.warnings?.map((warning,index)=><Alert key={index} type="warning" message={planWarningText(warning)}/>)}
        <Button type="primary" loading={busy} disabled={stale} onClick={()=>void save()}>保存排期设置</Button>
      </Space>}
    </>}
  </section>
}
