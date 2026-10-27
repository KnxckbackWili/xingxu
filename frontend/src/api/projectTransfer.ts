import { api } from './client'
import type { Project } from './index'
export type TransferPreview = { project_id: string; version: number; current_manager: { id: string; name: string }; candidates: { id: string; name: string }[]; removed: { user_id: string; name: string; documents: { code: string; name: string; required: boolean; restricted?: boolean }[] }[]; warning?: string; rule_warning?: string }
const path=(id:string)=>`/projects/${encodeURIComponent(id)}`
export const projectTransferApi={
  preview:async(id:string):Promise<TransferPreview>=>(await api.get(`${path(id)}/transfer-preview`)).data,
  transfer:async(id:string,preview:TransferPreview,target:string,reason:string,ack:string[]):Promise<Project&{viewer_retains_access:boolean}>=>(await api.post(`${path(id)}/transfer`,{target_manager_id:target,reason,version:preview.version,member_removal_confirmations:ack})).data,
}
