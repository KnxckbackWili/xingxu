import { beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { twoFactorApi } from '../api/twoFactor'
import { useAuth } from '../stores/auth'
import TwoFactorModal from './TwoFactorModal'
import MfaEnrollment from './MfaEnrollment'
vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn() }))
vi.mock('../api/twoFactor', () => ({ twoFactorApi: { status: vi.fn(), start: vi.fn(), codes: vi.fn(), setup: vi.fn(), recover: vi.fn(), cancel: vi.fn() } }))
const user = { id: 'isolated-pm', role: 'pm', username: 'pm', display_name: 'Test PM' } as any
beforeEach(() => { vi.clearAllMocks(); useAuth.setState({ user, pendingMfa: null }) })
it('requests nothing while closed; mandatory account cannot disable', async () => {
  vi.mocked(twoFactorApi.status).mockResolvedValue({ enabled: true, required: true, can_enroll: true, recovery_codes_remaining: 3 })
  const view = render(<TwoFactorModal open={false} onClose={vi.fn()} />)
  expect(twoFactorApi.status).not.toHaveBeenCalled(); view.rerender(<TwoFactorModal open onClose={vi.fn()} />)
  await screen.findByText('剩余恢复码：3 枚')
  fireEvent.change(screen.getByLabelText('当前六位验证码'), { target: { value: '123456' } })
  expect(screen.getByRole('button', { name: '关闭二次验证并退出登录' })).toBeDisabled()
})
it('shows recovery codes once without storage and clears them on completion', async () => {
  vi.mocked(twoFactorApi.status).mockResolvedValue({ enabled: true, required: false, can_enroll: true, recovery_codes_remaining: 1 })
  vi.mocked(twoFactorApi.codes).mockResolvedValue({ recovery_codes: ['once-only-private-code'] })
  const saved = vi.spyOn(Storage.prototype, 'setItem')
  const view = render(<TwoFactorModal open onClose={vi.fn()} />)
  await screen.findByText('剩余恢复码：1 枚')
  fireEvent.change(screen.getByLabelText('当前六位验证码'), { target: { value: '123456' } })
  fireEvent.click(screen.getByRole('button', { name: '重新生成恢复码' }))
  expect(await screen.findByDisplayValue('once-only-private-code')).toBeInTheDocument()
  expect(saved.mock.calls.flat().join(' ')).not.toContain('once-only-private-code')
  fireEvent.click(screen.getByRole('button', { name: '我已安全保存' }))
  expect(screen.queryByDisplayValue('once-only-private-code')).not.toBeInTheDocument()
  view.rerender(<TwoFactorModal open={false} onClose={vi.fn()} />)
  expect(screen.queryByDisplayValue('once-only-private-code')).not.toBeInTheDocument(); saved.mockRestore()
})
it('uses local SVG QR and keeps seed out of URL and storage', async () => {
  vi.mocked(twoFactorApi.start).mockResolvedValue({ secret: 'LOCAL-ONLY-SECRET', otpauth_uri: 'otpauth://totp/local?secret=LOCAL-ONLY-SECRET', expires_in: 300 })
  const saved = vi.spyOn(Storage.prototype, 'setItem'); const url = window.location.href
  const view = render(<MfaEnrollment challenge="purpose-limited" onComplete={vi.fn()} onCancel={vi.fn()} />)
  expect(await screen.findByLabelText('无法扫码时手动输入密钥')).toHaveValue('LOCAL-ONLY-SECRET')
  expect(view.container.querySelector('.ant-qrcode svg')).toBeInTheDocument(); expect(view.container.querySelector('img')).toBeNull()
  expect(window.location.href).toBe(url); expect(saved.mock.calls.flat().join(' ')).not.toContain('LOCAL-ONLY-SECRET')
  view.unmount(); expect(screen.queryByDisplayValue('LOCAL-ONLY-SECRET')).not.toBeInTheDocument(); saved.mockRestore()
})
it('ignores old account status after switching accounts', async () => {
  let resolve!: (value: any) => void
  vi.mocked(twoFactorApi.status).mockReturnValueOnce(new Promise(done => { resolve = done })).mockResolvedValueOnce({ enabled: false, required: false, can_enroll: false, recovery_codes_remaining: 0 })
  render(<TwoFactorModal open onClose={vi.fn()} />)
  useAuth.setState({ user: { ...user, id: 'other', role: 'worker' } })
  await screen.findByText('当前角色无需登记二次验证。')
  resolve({ enabled: true, required: true, can_enroll: true, recovery_codes_remaining: 99 })
  await waitFor(() => expect(screen.queryByText('剩余恢复码：99 枚')).not.toBeInTheDocument())
})
