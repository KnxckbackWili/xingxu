import { Modal, Typography, Alert } from 'antd'
import { api } from './client'

interface RemovalPreview { removed:Array<{user_id:string;name:string;documents:Array<{code:string;name:string;required:boolean}>}>;warning:string;rule_warning?:string|null }

/** Read the real current difference, then obtain per-person acknowledgement. */
export async function confirmMemberRemoval(projectId:string,removed:string[]|null,signal?:AbortSignal,previewPath?:string):Promise<string[]|undefined> {
  if(removed && !removed.length)return []
  const query=new URLSearchParams();removed?.forEach(id=>query.append('removed_ids',id))
  const {data}=await api.get<RemovalPreview>(previewPath || `/projects/${projectId}/members/removal-preview?${query}`,{signal})
  if(signal?.aborted)return undefined
  if(!Array.isArray(data.removed) || (removed && data.removed.length!==removed.length))throw new Error('成员移出预览已变化，请刷新后重试')
  if(!data.removed.length)return []
  return new Promise(resolve=>{
    const finish=(value:string[]|undefined)=>{signal?.removeEventListener('abort',cancel);resolve(value)}
    const dialog=Modal.confirm({title:'移出前核对文档留存',okText:'已核对，确认移出',cancelText:'取消',maskClosable:false,
      content:<><Typography.Paragraph>{data.warning}</Typography.Paragraph>{data.rule_warning && <Alert type="warning" message={data.rule_warning} />}{data.removed.map(person=><Typography.Paragraph key={person.user_id}><b>{person.name}</b>：{person.documents.map(row=>`${row.code} ${row.name}${row.required?'（必需）':''}`).join('；') || '资料要求待配置'}</Typography.Paragraph>)}</>,
      onOk:()=>finish(data.removed.map(person=>person.user_id)),onCancel:()=>finish(undefined)})
    const cancel=()=>{dialog.destroy();finish(undefined)}
    signal?.addEventListener('abort',cancel,{once:true})
  })
}
