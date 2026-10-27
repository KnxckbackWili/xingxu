import { PROJECT_START_STATUS_OPTIONS } from '../constants/status'

const startStatuses = new Set(PROJECT_START_STATUS_OPTIONS.map(({ value }) => value))

function projectFields(payload: unknown): Record<string, unknown> | undefined {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return undefined
  const project = (payload as Record<string, unknown>).project
  return project && typeof project === 'object' && !Array.isArray(project)
    ? project as Record<string, unknown> : undefined
}

export function projectImportSourceStatus(payload: unknown): string | undefined {
  const status = projectFields(payload)?.status
  return typeof status === 'string' ? status : undefined
}

/** Create a draft copy only; the backend must validate it again before import. */
export function draftProjectImport(payload: unknown): { payload: Record<string, unknown>; sourceStatus: string } | null {
  const sourceStatus = projectImportSourceStatus(payload)
  if (sourceStatus === undefined || startStatuses.has(sourceStatus)) return null
  return {
    payload: { ...payload as Record<string, unknown>, project: { ...projectFields(payload), status: 'preparing' } },
    sourceStatus,
  }
}
