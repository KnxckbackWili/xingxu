import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Checkbox, Input, Modal, Select, Space, Typography, message } from 'antd'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../../stores/auth'
import { useProjectCapability, useProjectWriteBlocked } from '../../../hooks/useProjectCapability'
import type { Project } from '../../../api'
import { projectTransferApi, type TransferPreview } from '../../../api/projectTransfer'
import { errMsg } from '../../../api/client'

export default function ProjectOwnerPanel({project,onReload,onDirtyChange}:{project:Project;onReload:()=>void;onDirtyChange?:(value:boolean)=>void}){
  const {user}=useAuth();const navigate=useNavigate()
  const canUpdate=useProjectCapability('project.update')
  const canMembers=useProjectCapability('project.manage_members')
  const blocked=useProjectWriteBlocked()
  const isOwner=user?.id===project.manager||user?.role==='admin'
  const allowed=isOwner&&canUpdate&&canMembers&&!blocked
  const [preview,setPreview]=useState<TransferPreview>()
  const [open,setOpen]=useState(false)
  const [target,setTarget]=useState<string>()
  const [reason,setReason]=useState('')
  const [ack,setAck]=useState<string[]>([])
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(false)
  const [stale,setStale]=useState(false)
  const epoch=useRef(0);const lock=useRef(false)
  useEffect(()=>{epoch.current++;lock.current=false;setOpen(false);setPreview(undefined);setTarget(undefined);setReason('');setAck([]);setError('');setBusy(false);setStale(false);onDirtyChange?.(false);return()=>{epoch.current++}},[project.id,project.manager,user?.id,user?.permission_version])
  useEffect(()=>{onDirtyChange?.(!!target||!!reason.trim()||!!ack.length)},[target,reason,ack,onDirtyChange])
  const inspect=async()=>{
    if(!allowed||lock.current)return
    const ticket=epoch.current;lock.current=true;setOpen(true);setBusy(true);setError('');setStale(true)
    try{const next=await projectTransferApi.preview(project.id);if(ticket!==epoch.current)return;if(next.project_id!==project.id){setError('负责人预览不属于当前项目，请重新读取');return}setPreview(next);setStale(false);setAck([]);setTarget(current=>next.candidates.some(person=>person.id===current)?current:undefined)}
    catch(failure){if(ticket===epoch.current){setStale(true);setError(errMsg(failure))}}
    finally{if(ticket===epoch.current){lock.current=false;setBusy(false)}}
  }
  const save=async()=>{
    if(!allowed||lock.current||stale||!preview||!target||reason.trim().length<5||preview.removed.some(person=>!ack.includes(person.user_id)))return
    const ticket=epoch.current;lock.current=true;setBusy(true);setError('')
    try{
      const result=await projectTransferApi.transfer(project.id,preview,target,reason.trim(),ack)
      if(ticket!==epoch.current)return
      setOpen(false);setReason('');setTarget(undefined);setAck([]);onDirtyChange?.(false);message.success('项目负责人已更换')
      if(result.viewer_retains_access===false)navigate('/pm/projects',{replace:true});else onReload()
    }catch(failure){if(ticket===epoch.current){setError(errMsg(failure));setStale(true)}}
    finally{if(ticket===epoch.current){lock.current=false;setBusy(false)}}
  }
  return <section aria-label="项目负责人">
    <Typography.Paragraph>当前负责人：{project.manager_name||'未分配'}</Typography.Paragraph>
    {allowed?<Button onClick={()=>void inspect()}>更换负责人</Button>:<Alert type="info" message={!isOwner?'仅当前负责人或管理员可更换负责人':!canUpdate?'当前账号缺少项目编辑权限':!canMembers?'当前账号缺少成员维护权限':'项目当前状态不可修改'}/>}
    <Modal title="更换项目负责人" open={open} maskClosable={false} confirmLoading={busy} okText="保存负责人" cancelText="取消" onCancel={()=>{if(!busy){setOpen(false);setTarget(undefined);setReason('');setAck([])}}} onOk={()=>void save()} okButtonProps={{disabled:!allowed||stale||!preview||!target||reason.trim().length<5||preview.removed.some(person=>!ack.includes(person.user_id))}}>
      {error&&<Alert type="error" showIcon message={error} action={<Space><Button disabled={busy} onClick={()=>void inspect()}>重新核对</Button><Button disabled={busy} onClick={onReload}>刷新项目信息</Button></Space>}/>}
      {stale&&preview&&<Alert type="warning" message="当前预览已失效，请重新核对后保存"/>}
      {preview?.warning&&<Alert type="warning" showIcon message={preview.warning}/>}
      {preview?.rule_warning&&<Alert type="warning" message={preview.rule_warning}/>}
      <p>选择新的负责人并填写理由；保存时重新核对当前权限、项目版本及离场资料。</p>
      <Select aria-label="新项目负责人" style={{width:'100%'}} showSearch optionFilterProp="label" value={target} disabled={busy||!preview} onChange={setTarget} options={preview?.candidates.map(person=>({value:person.id,label:person.name}))}/>
      <Input.TextArea aria-label="更换负责人理由" value={reason} onChange={event=>setReason(event.target.value)} placeholder="请说明更换原因（至少5字）" rows={3} maxLength={1000} disabled={busy} style={{margin:'12px 0'}}/>
      {preview?.removed.map(person=><div key={person.user_id}><Typography.Text strong>{person.name} 将离开当前项目职责范围</Typography.Text><ul>{person.documents.map((doc,index)=><li key={index}>{doc.code} {doc.name}{doc.required?'（必需）':''}</li>)}</ul><Checkbox disabled={busy} checked={ack.includes(person.user_id)} onChange={event=>setAck(current=>event.target.checked?[...current,person.user_id]:current.filter(id=>id!==person.user_id))}>已核对{person.name}的离场资料安排</Checkbox></div>)}
    </Modal>
  </section>
}
