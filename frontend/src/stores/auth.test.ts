import { beforeEach, describe, expect, it, vi } from 'vitest'
import { authApi } from '../api'
import { useAuth } from './auth'
import { getOfflineAccount } from '../offline/queue'
vi.mock('../api', () => ({ authApi: { me: vi.fn(), login: vi.fn(), logout: vi.fn() } }))
vi.mock('../api/client', () => ({ tokenStore: { setTokens: vi.fn(), clear: vi.fn() } }))
const deferred = () => {
  let resolve!: (value: any) => void
  let reject!: (value: any) => void
  const promise = new Promise<any>((r, j) => { resolve = r; reject = j })
  return { promise, resolve, reject }
}
beforeEach(async () => {
  vi.clearAllMocks()
  vi.mocked(authApi.logout).mockResolvedValue(undefined as never)
  useAuth.getState().logout()
  await new Promise(resolve => setTimeout(resolve, 0))
  useAuth.setState({ user: null, loading: false, meError: false })
})
describe('session request ownership', () => {
  it('does not resume the old cookie session while explicit logout is pending', async () => {
    vi.mocked(authApi.login).mockResolvedValue({ user: { id: 'old', role: 'pm' } } as any)
    await useAuth.getState().login('old', 'password')
    const pending = deferred()
    vi.mocked(authApi.logout).mockReturnValue(pending.promise)
    vi.mocked(authApi.me).mockResolvedValue({ id: 'old', role: 'pm' } as any)
    useAuth.getState().logout()
    await useAuth.getState().fetchMe()
    const result = { user: useAuth.getState().user, owner: getOfflineAccount(), resumed: vi.mocked(authApi.me).mock.calls.length }
    pending.resolve(undefined)
    await pending.promise
    expect(result).toEqual({ user: null, owner: null, resumed: 0 })
  })
  it('does not restore a session from a late me response after logout', async () => {
    const pending = deferred()
    vi.mocked(authApi.me).mockReturnValue(pending.promise)
    const read = useAuth.getState().fetchMe()
    useAuth.getState().logout()
    pending.resolve({ id: 'old', role: 'worker' })
    await read
    expect(useAuth.getState().user).toBeNull()
    expect(getOfflineAccount()).toBeNull()
  })
  it('does not clear the new login when an older me request fails', async () => {
    const pending = deferred()
    vi.mocked(authApi.me).mockReturnValue(pending.promise)
    const read = useAuth.getState().fetchMe()
    vi.mocked(authApi.login).mockResolvedValue({ user: { id: 'new', role: 'worker' } } as any)
    await useAuth.getState().login('new', 'password')
    pending.reject(new Error('old request failed'))
    await read
    expect(useAuth.getState().user?.id).toBe('new')
    expect(useAuth.getState().meError).toBe(false)
    expect(getOfflineAccount()).toBe('new')
  })
  it('waits for a pending logout before sending the new login', async () => {
    const pending = deferred()
    vi.mocked(authApi.logout).mockReturnValue(pending.promise)
    useAuth.getState().logout()
    vi.mocked(authApi.login).mockResolvedValue({ user: { id: 'new', role: 'worker' } } as any)
    const login = useAuth.getState().login('new', 'password')
    expect(authApi.login).not.toHaveBeenCalled()
    pending.resolve(undefined)
    await login
    expect(authApi.login).toHaveBeenCalledTimes(1)
  })
  it('refreshes permissions silently and coalesces focus/403 requests without changing offline ownership', async () => {
    vi.mocked(authApi.login).mockResolvedValue({ user: { id: 'same', role: 'pm', system_permissions: ['system.people.view'] } } as any)
    await useAuth.getState().login('same', 'password')
    const pending = deferred()
    vi.mocked(authApi.me).mockReturnValue(pending.promise)
    const first = useAuth.getState().refreshPermissions()
    const second = useAuth.getState().refreshPermissions()
    expect(authApi.me).toHaveBeenCalledTimes(1)
    expect(useAuth.getState().loading).toBe(false)
    expect(useAuth.getState().user?.id).toBe('same')
    expect(getOfflineAccount()).toBe('same')
    pending.resolve({ id: 'same', role: 'pm', system_permissions: [], permission_version: 2 })
    await Promise.all([first, second])
    expect(useAuth.getState().user?.system_permissions).toEqual([])
    expect(useAuth.getState().user?.permission_version).toBe(2)
    expect(getOfflineAccount()).toBe('same')
  })
  it('does not erase the current account or permissions after a background network failure', async () => {
    vi.mocked(authApi.login).mockResolvedValue({ user: { id: 'same', role: 'worker', system_permissions: ['system.templates.view'] } } as any)
    await useAuth.getState().login('same', 'password')
    vi.mocked(authApi.me).mockRejectedValue(new Error('offline'))
    await useAuth.getState().refreshPermissions()
    expect(useAuth.getState().user?.system_permissions).toEqual(['system.templates.view'])
    expect(useAuth.getState().loading).toBe(false)
    expect(useAuth.getState().meError).toBe(false)
    expect(getOfflineAccount()).toBe('same')
  })
  it('ignores a previous account background permission response after login changes', async () => {
    vi.mocked(authApi.login).mockResolvedValue({ user: { id: 'old', role: 'pm' } } as any)
    await useAuth.getState().login('old', 'password')
    const pending = deferred()
    vi.mocked(authApi.me).mockReturnValue(pending.promise)
    const read = useAuth.getState().refreshPermissions()
    vi.mocked(authApi.login).mockResolvedValue({ user: { id: 'new', role: 'worker' } } as any)
    await useAuth.getState().login('new', 'password')
    pending.resolve({ id: 'old', role: 'admin', system_permissions: ['system.templates.manage'] })
    await read
    expect(useAuth.getState().user?.id).toBe('new')
    expect(getOfflineAccount()).toBe('new')
  })
})
