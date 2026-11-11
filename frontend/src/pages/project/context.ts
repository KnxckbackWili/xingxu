import type { Snapshot } from '../../api/types'
import type { Live } from '../../sync/useLive'

/** What every tab of the project page works with. */
export interface TabProps {
  snap: Snapshot
  live: Live<Snapshot>
  /** `/projects/<id>` */
  base: string
  /** The signed-in person's id and name. */
  me: { id: string; name: string }
  /** Show only what is still to do. */
  todo: boolean
}

/** The five rules of "still missing", as the page counts them from its own copy. */
export function gapCounts(snap: Snapshot) {
  const marks = new Set(snap.marks.map((mark) => `${mark.vehicle_id}:${mark.step_id}`))
  const withFiles = new Set(snap.files.filter((file) => file.owner_kind === 'document').map((file) => file.owner_id))
  return {
    vehicles: snap.vehicles.filter((vehicle) => snap.steps.some((step) => !marks.has(`${vehicle.id}:${step.id}`))).length,
    work: snap.work.filter((row) => !row.done).length,
    issues: snap.issues.filter((row) => !row.is_closed).length,
    documents: snap.documents.filter((row) => !withFiles.has(row.id)).length,
    items: snap.items.filter((row) => !row.arrived).length,
  }
}
