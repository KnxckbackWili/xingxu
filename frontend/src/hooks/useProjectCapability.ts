import { createContext, useContext } from 'react'
import { isProjectWriteBlocked } from '../constants/status'

/** Server-returned project capabilities are authoritative; fallback supports older responses. */
export const ProjectArchivedContext = createContext(false)
export const ProjectStatusContext = createContext<string | undefined>(undefined)
export const ProjectCapabilitiesContext = createContext<string[] | undefined>(undefined)
export function hasProjectCapability(capabilities: string[] | undefined, capability: string, fallback = false) {
  return capabilities === undefined ? fallback : capabilities.includes(capability)
}
export function useProjectCapability(capability: string, fallback = false) {
  const writeBlocked = useProjectWriteBlocked()
  const capabilities = useContext(ProjectCapabilitiesContext)
  return (!writeBlocked || capability === 'project.export') && hasProjectCapability(capabilities, capability, fallback)
}
export function useProjectWriteBlocked(status?: string) {
  const archived = useContext(ProjectArchivedContext)
  const inheritedStatus = useContext(ProjectStatusContext)
  return archived || isProjectWriteBlocked(status ?? inheritedStatus)
}
