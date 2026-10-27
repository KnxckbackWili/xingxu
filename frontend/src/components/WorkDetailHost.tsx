import { lazy, Suspense, useEffect } from 'react'
import { Drawer, Spin } from 'antd'
import { useLocation } from 'react-router-dom'
import { closeWorkDetail, useWorkDetail } from '../stores/workDetail'
import { useAuth } from '../stores/auth'

const TaskDetails = lazy(() => import('../pages/pm/project/TaskPlanPage'))
export default function WorkDetailHost() {
  const { context } = useWorkDetail()
  const { user } = useAuth()
  const location = useLocation()
  useEffect(() => { useWorkDetail.setState({ context: null, changed: false }) }, [user?.id, location.pathname])
  if (!context || !user) return null
  return <Suspense fallback={<Drawer open title="工作详情" onClose={closeWorkDetail}><Spin /></Drawer>}>
    <TaskDetails key={`${context.projectId}:${context.taskId}`} projectId={context.projectId} focusTaskId={context.taskId} focusEntryId={context.entryId} focusTab={context.focusTab} detailsOnly
      onDetailClose={closeWorkDetail} onWorkChanged={() => useWorkDetail.setState({ changed: true })} />
  </Suspense>
}
