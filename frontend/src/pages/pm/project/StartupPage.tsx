import { Navigate } from 'react-router-dom'
import type { Project } from '../../../api'

/** Old bookmarks resolve to the ordered setup on the project overview. */
export default function StartupPage({ project }: { project: Project; canEdit: boolean; onReload: () => Promise<void> | void; onDirtyChange?: (dirty: boolean) => void }) {
  return <Navigate to={`/pm/projects/${project.id}/overview`} replace />
}
