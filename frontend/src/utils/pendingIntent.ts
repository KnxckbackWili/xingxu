/** Retry receipts contain only the submitted business payload, never auth data.
 * Account/project/entity keys prevent another user's form from reusing them. */
export function pendingIntentKey(kind: string, userId: string | undefined, projectId: string, entityId: string) {
  return userId ? `agv:pending:${kind}:${userId}:${projectId}:${entityId}` : null
}
export function readPendingIntent<T>(key: string | null): T | undefined {
  if (!key) return undefined
  try { return JSON.parse(sessionStorage.getItem(key) || 'null') ?? undefined } catch { return undefined }
}
export function writePendingIntent(key: string | null, value: unknown) {
  if (!key) return
  try { sessionStorage.setItem(key, JSON.stringify(value)) } catch { /* In-memory intent still protects retries in this view. */ }
}
export function clearPendingIntent(key: string | null) {
  if (!key) return
  try { sessionStorage.removeItem(key) } catch { /* Current view has already cleared its receipt. */ }
}
