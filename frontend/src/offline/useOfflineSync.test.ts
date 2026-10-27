import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useOfflineSync } from './useOfflineSync'
import { enqueue, getQueue, getRejected, setOfflineAccount } from './queue'
import { api } from '../api/client'

vi.mock('../api/client', () => ({ api: { post: vi.fn() } }))
const deferred = () => {
  let resolve!: (value: any) => void
  const promise = new Promise<any>(r => { resolve = r })
  return { promise, resolve }
}
beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  setOfflineAccount(null)
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: true })
})

describe('offline sync session isolation', () => {
  it('updates this tab when work is queued and exposes completed automatic sync', async () => {
    setOfflineAccount('a')
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: false })
    vi.mocked(api.post).mockResolvedValue({ data: { accepted: ['offline-progress'], rejected: [] } })
    const { result } = renderHook(() => useOfflineSync())
    act(() => enqueue({ client_uuid: 'offline-progress', schedule_entry_id: 'entry-a' }, 'report'))
    expect(result.current.pendingCount).toBe(1)
    act(() => {
      Object.defineProperty(navigator, 'onLine', { configurable: true, value: true })
      window.dispatchEvent(new Event('online'))
    })
    await waitFor(() => expect(result.current.syncVersion).toBe(1))
    expect(result.current.pendingCount).toBe(0)
    expect(getQueue()).toEqual([])
  })

  it('ignores old-account sync responses after an account switch', async () => {
    setOfflineAccount('a')
    enqueue({ client_uuid: 'a-rejected', task_id: 'private-a' }, 'report')
    const pending = deferred()
    vi.mocked(api.post).mockReturnValue(pending.promise)
    const { result } = renderHook(() => useOfflineSync())
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1))
    act(() => {
      setOfflineAccount('b')
      enqueue({ client_uuid: 'b-pending' }, 'report')
    })
    await act(async () => {
      pending.resolve({ data: { accepted: [], rejected: ['a-rejected'] } })
      await pending.promise
    })
    expect(getQueue().map(op => op.client_uuid)).toEqual(['b-pending'])
    expect(getRejected()).toEqual([])
    expect(result.current.rejected).toEqual([])
    act(() => { setOfflineAccount('a') })
    expect(getQueue().map(op => op.client_uuid)).toEqual(['a-rejected'])
  })

  it('shares an in-flight request across repeated flushes', async () => {
    setOfflineAccount('a')
    enqueue({ client_uuid: 'same-op' })
    const pending = deferred()
    vi.mocked(api.post).mockReturnValue(pending.promise)
    const { result } = renderHook(() => useOfflineSync())
    const first = result.current.flush()
    const second = result.current.flush()
    expect(first).toBe(second)
    expect(api.post).toHaveBeenCalledTimes(1)
    await act(async () => {
      pending.resolve({ data: { accepted: ['same-op'] } })
      await first
    })
    expect(getQueue()).toEqual([])
    expect(result.current.pendingCount).toBe(0)
  })

  it('invalidates the bound account when another tab changes the session owner', async () => {
    setOfflineAccount('a')
    enqueue({ client_uuid: 'a-pending' })
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: false })
    const { result } = renderHook(() => useOfflineSync())
    act(() => {
      localStorage.setItem('agvpm_offline_owner', 'b')
      window.dispatchEvent(new StorageEvent('storage', { key: 'agvpm_offline_owner' }))
    })
    expect(result.current.pendingCount).toBe(0)
    expect(getQueue()).toEqual([])
    await result.current.flush()
    expect(api.post).not.toHaveBeenCalled()
  })
})
