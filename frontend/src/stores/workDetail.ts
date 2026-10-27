import { create } from 'zustand'

export interface WorkDetailContext {
  projectId: string
  taskId: string
  entryId?: string
  focusTab?: 'checks' | 'reference'
  onChanged?: () => void
}
export const useWorkDetail = create<{ context: WorkDetailContext | null; changed: boolean }>(() => ({ context: null, changed: false }))
export function openWorkDetail(context: WorkDetailContext) {
  useWorkDetail.setState({ context, changed: false })
}
export function closeWorkDetail() {
  const { context, changed } = useWorkDetail.getState()
  useWorkDetail.setState({ context: null, changed: false })
  if (changed) context?.onChanged?.()
}
