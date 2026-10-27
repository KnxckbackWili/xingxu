import { api } from './client'
import type { User } from './index'

export type MfaChallenge = { two_factor_required: true; setup_required: boolean; challenge: string; expires_in: number }
export type AuthSession = { access_token: string; refresh_token: string; user: User; recovery_codes?: string[] }
export type MfaStatus = { enabled: boolean; required: boolean; can_enroll: boolean; recovery_codes_remaining: number }
export const twoFactorApi = {
  status: () => api.get<MfaStatus>('/auth/2fa').then(r => r.data),
  start: (challenge: string) => api.post<{ secret: string; otpauth_uri: string; expires_in: number }>('/auth/2fa/enroll/start', { challenge }).then(r => r.data),
  verify: (challenge: string, proof: { otp?: string; recovery_code?: string }) => api.post<AuthSession>('/auth/2fa/verify', { challenge, ...proof }).then(r => r.data),
  confirm: (challenge: string, otp: string) => api.post<AuthSession>('/auth/2fa/enroll/confirm', { challenge, otp }).then(r => r.data),
  setup: (password: string) => api.post<MfaChallenge>('/auth/2fa/setup', { password }).then(r => r.data),
  disable: (otp: string) => api.post('/auth/2fa/disable', { otp }).then(r => r.data),
  codes: (otp: string) => api.post<{ recovery_codes: string[] }>('/auth/2fa/recovery-codes', { otp }).then(r => r.data),
  cancel: (challenge: string) => api.post('/auth/2fa/cancel', { challenge }).then(r => r.data),
  recoverLogin: (challenge: string, recovery_code: string) => api.post<MfaChallenge>('/auth/2fa/recover/start', { challenge, recovery_code }).then(r => r.data),
  recover: (password: string, recovery_code: string) => api.post<MfaChallenge>('/auth/2fa/recover', { password, recovery_code }).then(r => r.data),
}
