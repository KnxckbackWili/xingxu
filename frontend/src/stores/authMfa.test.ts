import { beforeEach, expect, it, vi } from 'vitest'
import { authApi } from '../api'
import { twoFactorApi } from '../api/twoFactor'
import { tokenStore } from '../api/client'
import { getOfflineAccount } from '../offline/queue'
import { useAuth } from './auth'
vi.mock('../api', () => ({ authApi: { me: vi.fn(), login: vi.fn(), logout: vi.fn() } }))
vi.mock('../api/client', () => ({ tokenStore: { setTokens: vi.fn(), clear: vi.fn() } }))
vi.mock('../api/twoFactor', () => ({ twoFactorApi: { verify: vi.fn(), confirm: vi.fn(), cancel: vi.fn(), disable: vi.fn() } }))
const step = { two_factor_required: true as const, setup_required: false, challenge: 'memory-only-challenge', expires_in: 300 }
const session = { access_token: 'memory-access', refresh_token: 'memory-refresh', user: { id: 'mfa-user', role: 'pm' } } as any
const deferred = () => { let resolve!: (value: any) => void; const promise = new Promise<any>(done => { resolve = done }); return { promise, resolve } }
beforeEach(async () => {
  vi.clearAllMocks(); vi.mocked(authApi.logout).mockResolvedValue(undefined as never); vi.mocked(twoFactorApi.cancel).mockResolvedValue(undefined)
  useAuth.getState().logout(); await new Promise(resolve => setTimeout(resolve, 0)); vi.clearAllMocks()
})
it('password challenge has no user, offline ownership or token session', async () => {
  vi.mocked(authApi.login).mockResolvedValue(step)
  expect(await useAuth.getState().login('pm', 'password')).toEqual(step)
  expect(useAuth.getState().user).toBeNull(); expect(useAuth.getState().pendingMfa).toEqual(step)
  expect(getOfflineAccount()).toBeNull(); expect(tokenStore.setTokens).not.toHaveBeenCalled()
})
it('establishes session only after second factor and keeps recovery codes out of store', async () => {
  useAuth.getState().beginMfa(step)
  vi.mocked(twoFactorApi.confirm).mockResolvedValue({ ...session, recovery_codes: ['once-only'] })
  expect((await useAuth.getState().completeMfa(step.challenge, { otp: '123456' }, true)).recovery_codes).toEqual(['once-only'])
  expect(useAuth.getState().user?.id).toBe('mfa-user'); expect(getOfflineAccount()).toBe('mfa-user')
  useAuth.getState().finishMfa()
  expect(useAuth.getState().pendingMfa).toBeNull(); expect(JSON.stringify(useAuth.getState())).not.toContain('once-only')
})
it('cancels late verified response and queues cookie clearing behind it', async () => {
  const response = deferred(); useAuth.getState().beginMfa(step)
  vi.mocked(twoFactorApi.verify).mockReturnValue(response.promise)
  const result = useAuth.getState().completeMfa(step.challenge, { otp: '123456' }).catch(error => error)
  useAuth.getState().cancelMfa()
  expect(authApi.logout).not.toHaveBeenCalled(); expect(twoFactorApi.cancel).toHaveBeenCalledWith(step.challenge)
  response.resolve(session); expect(await result).toBeInstanceOf(Error)
  await new Promise(resolve => setTimeout(resolve, 0))
  expect(authApi.logout).toHaveBeenCalledTimes(1); expect(useAuth.getState().user).toBeNull()
})
it('queues next account login behind MFA so final cookie belongs to the new account', async () => {
  const response = deferred(); useAuth.getState().beginMfa(step)
  vi.mocked(twoFactorApi.verify).mockReturnValue(response.promise)
  const old = useAuth.getState().completeMfa(step.challenge, { recovery_code: 'unused-code' }).catch(error => error)
  vi.mocked(authApi.login).mockResolvedValue({ ...session, user: { id: 'new-account', role: 'worker' } })
  const next = useAuth.getState().login('new-account', 'password')
  expect(authApi.login).not.toHaveBeenCalled(); response.resolve(session)
  expect(await old).toBeInstanceOf(Error); await next; expect(useAuth.getState().user?.id).toBe('new-account')
})
it('failed OTP retains challenge and cannot establish a session', async () => {
  useAuth.getState().beginMfa(step); vi.mocked(twoFactorApi.verify).mockRejectedValue(new Error('wrong OTP'))
  await expect(useAuth.getState().completeMfa(step.challenge, { otp: '000000' })).rejects.toThrow('wrong OTP')
  expect(useAuth.getState().pendingMfa).toEqual(step); expect(useAuth.getState().user).toBeNull()
})

it('does not send queued old factor proof after another account owns the cookies', async () => {
  useAuth.getState().beginMfa(step)
  const response = deferred()
  vi.mocked(authApi.login).mockReturnValue(response.promise)
  const login = useAuth.getState().login('next', 'password')
  const proof = useAuth.getState().completeMfa(step.challenge, { otp: '123456' }).catch(error => error)
  response.resolve({ ...session, user: { id: 'next', role: 'worker' } })
  await login
  expect(await proof).toBeInstanceOf(Error)
  expect(twoFactorApi.verify).not.toHaveBeenCalled()
  expect(useAuth.getState().user?.id).toBe('next')
})
it('does not send queued old-account disable after another account signs in', async () => {
  useAuth.setState({ user: session.user })
  const response = deferred()
  vi.mocked(authApi.login).mockReturnValue(response.promise)
  const login = useAuth.getState().login('next', 'password')
  const disable = useAuth.getState().disableMfa('123456').catch(error => error)
  response.resolve({ ...session, user: { id: 'next', role: 'worker' } })
  await login
  expect(await disable).toBeInstanceOf(Error)
  expect(twoFactorApi.disable).not.toHaveBeenCalled()
})
