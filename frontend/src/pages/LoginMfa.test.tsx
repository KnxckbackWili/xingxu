import { beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { authApi } from '../api'
import { twoFactorApi } from '../api/twoFactor'
import { useAuth } from '../stores/auth'
import LoginPage from './LoginPage'
const navigate = vi.fn()
vi.mock('react-router-dom', () => ({ useNavigate: () => navigate, useLocation: () => ({ search: '', pathname: '/login' }) }))
vi.mock('../api', () => ({ authApi: { login: vi.fn(), logout: vi.fn(), me: vi.fn() } }))
vi.mock('../api/client', () => ({ tokenStore: { clear: vi.fn(), setTokens: vi.fn() }, errMsg: () => '验证码错误' }))
vi.mock('../api/twoFactor', () => ({ twoFactorApi: { start: vi.fn(), verify: vi.fn(), confirm: vi.fn(), recoverLogin: vi.fn(), cancel: vi.fn() } }))
const step = { two_factor_required: true as const, setup_required: false, challenge: 'purpose-limited', expires_in: 300 }
const user = { id: 'isolated-pm', username: 'pm', role: 'pm', display_name: 'PM' } as any
const session = { access_token: 'a', refresh_token: 'r', user }
beforeEach(async () => {
  vi.clearAllMocks(); vi.mocked(authApi.logout).mockResolvedValue(undefined as never); vi.mocked(twoFactorApi.cancel).mockResolvedValue(undefined)
  useAuth.getState().logout(); await new Promise(resolve => setTimeout(resolve, 0)); vi.clearAllMocks()
})
async function password(expectMfa = true) {
  render(<LoginPage />)
  fireEvent.change(screen.getByPlaceholderText('填写账号'), { target: { value: 'pm' } })
  fireEvent.change(screen.getByPlaceholderText('密码'), { target: { value: 'password' } })
  fireEvent.click(screen.getByText(/^登\s*录$/))
  if (!expectMfa) return
  await waitFor(() => expect(useAuth.getState().pendingMfa).not.toBeNull())
  await waitFor(() => expect(screen.queryByPlaceholderText('密码')).not.toBeInTheDocument())
  if (!useAuth.getState().pendingMfa?.setup_required) await waitFor(() => expect(screen.getByLabelText('六位验证码')).not.toBeDisabled())
}
it('stays outside business after password, handles wrong OTP, then enters only after valid OTP', async () => {
  vi.mocked(authApi.login).mockResolvedValue(step)
  vi.mocked(twoFactorApi.verify).mockRejectedValueOnce(new Error('wrong')).mockResolvedValueOnce(session)
  await password(); const otp = await screen.findByLabelText('六位验证码')
  expect(navigate).not.toHaveBeenCalled(); expect(useAuth.getState().user).toBeNull()
  fireEvent.change(otp, { target: { value: '000000' } }); fireEvent.click(screen.getByRole('button', { name: /验证并登录/ }))
  await waitFor(() => expect(twoFactorApi.verify).toHaveBeenCalledTimes(1))
  await screen.findByText('验证码错误')
  expect(navigate).not.toHaveBeenCalled()
  await waitFor(() => expect(otp).not.toBeDisabled())
  fireEvent.change(otp, { target: { value: '123456' } }); fireEvent.click(screen.getByRole('button', { name: /验证并登录/ }))
  await waitFor(() => expect(navigate).toHaveBeenCalledWith('/pm', { replace: true }))
})
it('mandatory enrollment displays local key and requires saving one-time recovery codes before navigation', async () => {
  vi.mocked(authApi.login).mockResolvedValue({ ...step, setup_required: true })
  vi.mocked(twoFactorApi.start).mockResolvedValue({ secret: 'ISOLATED-KEY', otpauth_uri: 'otpauth://totp/local?secret=ISOLATED-KEY', expires_in: 300 })
  vi.mocked(twoFactorApi.confirm).mockResolvedValue({ ...session, recovery_codes: ['only-shown-once'] })
  await password(); await screen.findByDisplayValue('ISOLATED-KEY')
  fireEvent.change(screen.getByLabelText('六位验证码'), { target: { value: '123456' } }); fireEvent.click(screen.getByRole('button', { name: '确认启用' }))
  await screen.findByDisplayValue('only-shown-once'); expect(navigate).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '我已安全保存' }))
  expect(navigate).toHaveBeenCalledWith('/pm', { replace: true })
})
it('lost authenticator uses last recovery code to enter only replacement enrollment', async () => {
  vi.mocked(authApi.login).mockResolvedValue(step)
  vi.mocked(twoFactorApi.recoverLogin).mockResolvedValue({ ...step, setup_required: true, challenge: 'replacement-only' })
  vi.mocked(twoFactorApi.start).mockResolvedValue({ secret: 'NEW-KEY', otpauth_uri: 'otpauth://totp/local?secret=NEW-KEY', expires_in: 300 })
  await password(); await screen.findByLabelText('六位验证码')
  fireEvent.click(screen.getByRole('button', { name: '认证器丢失，使用恢复码重新绑定' }))
  fireEvent.change(screen.getByLabelText('一次性恢复码'), { target: { value: 'last-private-code' } })
  fireEvent.click(screen.getByRole('button', { name: /验证恢复码并重新绑定/ }))
  await screen.findByDisplayValue('NEW-KEY')
  expect(twoFactorApi.recoverLogin).toHaveBeenCalledWith(step.challenge, 'last-private-code')
  expect(useAuth.getState().user).toBeNull(); expect(navigate).not.toHaveBeenCalled()
})

it('ordinary login with explicit false policy fields still navigates immediately', async () => {
  vi.mocked(authApi.login).mockResolvedValue({ ...session, user: { ...user, two_factor_enabled: false, two_factor_required: false } })
  await password(false)
  await waitFor(() => expect(navigate).toHaveBeenCalledWith('/pm', { replace: true }))
  expect(useAuth.getState().pendingMfa).toBeNull()
})
