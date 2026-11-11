import { useCallback, useEffect, useRef, useState } from 'react'
import { api, errMsg } from '../api/client'

const INTERVAL = 4000

export interface Live<T> {
  data: T | null
  error: string
  /** Fetch now (after a write, or when the page wants to be sure). */
  refresh: () => void
  /** Show a change at once, before the server has answered. */
  mutate: (change: (data: T) => T) => void
  /** Wrap a write: fresh server copies are held back until it has settled, then fetched. */
  track: <R>(write: Promise<R>) => Promise<R>
}

/**
 * A server resource that stays current: asked again every four seconds with the version in hand,
 * answered 304 while nothing changed. Polling pauses while the page is hidden.
 */
export function useLive<T>(url: string | null): Live<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState('')
  const state = useRef({ etag: '', writes: 0, epoch: 0, url: '', busy: false, again: false })

  const load = useCallback(async () => {
    const current = state.current
    if (!url || current.url !== url) return
    if (current.busy) { current.again = true; return }
    if (current.writes > 0) return
    current.busy = true
    const epoch = current.epoch
    try {
      const response = await api.get(url, {
        headers: current.etag ? { 'If-None-Match': current.etag } : {},
        validateStatus: (status) => status === 200 || status === 304,
      })
      if (state.current.url !== url) return
      // A copy fetched while a write was under way may predate it: drop it and ask again.
      if (state.current.epoch !== epoch || state.current.writes > 0) { state.current.again = true; return }
      if (response.status === 200) {
        state.current.etag = response.headers.etag ?? ''
        setData(response.data as T)
      }
      setError('')
    } catch (failure) {
      if (state.current.url === url) setError(errMsg(failure))
    } finally {
      state.current.busy = false
      if (state.current.again) { state.current.again = false; void load() }
    }
  }, [url])

  useEffect(() => {
    state.current = { etag: '', writes: 0, epoch: 0, url: url ?? '', busy: false, again: false }
    setData(null)
    setError('')
    if (!url) return
    void load()
    const timer = window.setInterval(() => { if (!document.hidden) void load() }, INTERVAL)
    const wake = () => { if (!document.hidden) void load() }
    document.addEventListener('visibilitychange', wake)
    window.addEventListener('online', wake)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', wake)
      window.removeEventListener('online', wake)
    }
  }, [url, load])

  const mutate = useCallback((change: (data: T) => T) => setData((current) => (current === null ? current : change(current))), [])

  const track = useCallback(<R,>(write: Promise<R>): Promise<R> => {
    state.current.writes += 1
    state.current.epoch += 1
    const settle = () => {
      state.current.writes -= 1
      state.current.epoch += 1
      if (state.current.writes === 0) void load()
    }
    write.then(settle, settle)
    return write
  }, [load])

  return { data, error, refresh: load, mutate, track }
}
