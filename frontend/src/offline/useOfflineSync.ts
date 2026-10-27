import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import {
  getQueue, removeFromQueue, getRejected, addRejected, removeRejected, retryRejected,
  getOfflineAccount, getOfflineAccountRevision, OFFLINE_ACCOUNT_EVENT, OFFLINE_QUEUE_EVENT,
} from './queue'

/**
 * Tracks online state and provides a flush() that syncs queued worker ops.
 * Call after submitting when online; hook wires the 'online' event.
 *
 * C5-5/C5-6: flush sends typed ops to /worker/sync; rejected ones are moved to
 * the rejected store (with server reason) and exposed via `rejected` for
 * inspect / retry / delete. `pendingCount` only counts items still waiting to
 * sync (rejected items are no longer counted as pending).
 */
export function useOfflineSync() {
  const inFlight = useRef<Promise<number> | null>(null)
  const [online, setOnline] = useState(navigator.onLine)
  const [pendingCount, setPendingCount] = useState(getQueue().length)
  const [rejected, setRejected] = useState(getRejected())
  const [syncVersion, setSyncVersion] = useState(0)

  const refreshCount = useCallback(() => {
    setPendingCount(getQueue().length)
    setRejected(getRejected())
  }, [])

  const flush = useCallback((): Promise<number> => {
    // Repeated online events / save callbacks share one request. Server UUIDs
    // still provide crash-retry idempotency, but do not protect client state.
    if (inFlight.current) return inFlight.current
    const owner = getOfflineAccount()
    const revision = getOfflineAccountRevision()
    const queue = getQueue()
    if (!owner || queue.length === 0 || !navigator.onLine) return Promise.resolve(0)
    const request = (async () => {
      try {
        const r = await api.post('/worker/sync', {
          ops: queue.map((i) => ({ type: i.type, client_uuid: i.client_uuid, payload: i.payload })),
        })
        // Never apply a previous session's result to the currently bound account.
        // Leave the old queue intact: its UUIDs make a later owner retry safe.
        if (owner !== getOfflineAccount() || revision !== getOfflineAccountRevision()) return 0
        const accepted: string[] = r.data.accepted ?? []
        const rejectedUuids: string[] = r.data.rejected ?? []
        const rejectedDetail: Record<string, string> = r.data.rejected_detail ?? {}
        removeFromQueue(accepted)
        for (const u of rejectedUuids) {
          const item = queue.find((i) => i.client_uuid === u)
          if (item) addRejected(item, rejectedDetail[u] ?? '服务端拒绝')
          removeFromQueue([u])
        }
        refreshCount()
        if (accepted.length || rejectedUuids.length) setSyncVersion(value => value + 1)
        return accepted.length
      } catch {
        return 0
      } finally {
        inFlight.current = null
      }
    })()
    inFlight.current = request
    return request
  }, [refreshCount])

  const retry = useCallback((uuid: string) => {
    retryRejected(uuid)
    refreshCount()
  }, [refreshCount])

  const remove = useCallback((uuid: string) => {
    removeRejected([uuid])
    refreshCount()
  }, [refreshCount])

  useEffect(() => {
    const onOnline = () => setOnline(true)
    const onOffline = () => setOnline(false)
    window.addEventListener('online', onOnline)
    window.addEventListener('offline', onOffline)
    window.addEventListener('storage', refreshCount)
    window.addEventListener(OFFLINE_ACCOUNT_EVENT, refreshCount)
    window.addEventListener(OFFLINE_QUEUE_EVENT, refreshCount)
    return () => {
      window.removeEventListener('online', onOnline)
      window.removeEventListener('offline', onOffline)
      window.removeEventListener('storage', refreshCount)
      window.removeEventListener(OFFLINE_ACCOUNT_EVENT, refreshCount)
      window.removeEventListener(OFFLINE_QUEUE_EVENT, refreshCount)
    }
  }, [refreshCount])

  // Auto-flush when coming back online
  useEffect(() => {
    if (online) {
      flush()
    }
  }, [online, flush])

  return { online, pendingCount, rejected, syncVersion, flush, retry, remove, refreshCount }
}
