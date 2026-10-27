import { useEffect, useState } from 'react'
import { Alert } from 'antd'
import WorkItemEditor from './WorkItemEditor'
import { api, errMsg } from '../api/client'
import { workItemsApi, type WorkPhase } from '../api/workItems'
export default function CustomTaskModal({ projectId, open, onClose, onSaved }: { projectId: string; open: boolean; onClose: () => void; onSaved: () => void }) {
  const [phases,setPhases]=useState<WorkPhase[]>([])
  const [steps,setSteps]=useState<{key:string;name:string}[]>([])
  const [error,setError]=useState('')
  useEffect(()=>{if(!open)return;let active=true;setPhases([]);setError('');Promise.all([workItemsApi.list(projectId),api.get(`/projects/${projectId}/vehicle-progress`)]).then(([work,matrix])=>{if(active){setPhases(work.phases);setSteps(matrix.data.steps)}}).catch(e=>{if(active)setError(errMsg(e))});return()=>{active=false}},[projectId,open])
  return <>{error&&<Alert type="error" message={error}/>}<WorkItemEditor open={open} projectId={projectId} phases={phases} steps={steps} onClose={onClose} onSaved={onSaved}/></>
}
