/** Refresh notification readers immediately after a successful read mutation. */
export const NOTIFICATION_READ_EVENT = 'agv:notification-read'

export function notifyReadStateChanged(source?: 'messages' | 'bell') {
  window.dispatchEvent(new CustomEvent(NOTIFICATION_READ_EVENT, { detail: { source } }))
}
