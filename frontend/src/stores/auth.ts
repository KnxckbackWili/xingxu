import { create } from 'zustand'
import { authApi } from '../api'
import { tokenStore } from '../api/client'
import { setOfflineAccount } from '../offline/queue'
import type { User } from '../api'
import { twoFactorApi, type AuthSession, type MfaChallenge } from '../api/twoFactor'

interface AuthState {
  user: User | null
  loading: boolean
  meError: boolean
  pendingMfa: MfaChallenge | null
  login: (username: string, password: string, remember?: boolean) => Promise<User | MfaChallenge>
  beginMfa: (challenge: MfaChallenge) => void
  cancelMfa: () => void
  finishMfa: () => void
  completeMfa: (challenge: string, proof: { otp?: string; recovery_code?: string }, enroll?: boolean) => Promise<AuthSession>
  disableMfa: (otp: string) => Promise<void>
  logout: () => void
  fetchMe: () => Promise<void>
  refreshPermissions: () => Promise<void>
}

let pendingAuthentication: Promise<unknown> | null = null
function serializeAuthentication<T>(operation: () => Promise<T>): Promise<T> {
  const prior = pendingAuthentication
  const result = prior ? prior.catch(() => undefined).then(operation) : operation()
  pendingAuthentication = result
  void result.finally(() => { if (pendingAuthentication === result) pendingAuthentication = null }).catch(() => undefined)
  return result
}

let sessionRevision = 0
let pendingLogout: Promise<unknown> | null = null
let pendingPermissions: { id: string; revision: number; promise: Promise<void> } | null = null

export const useAuth = create<AuthState>((set, get) => ({
  user: null,
  loading: false,
  meError: false,
  pendingMfa: null,

  login: async (username, password, remember = true) => {
    const revision = ++sessionRevision
    // A slow logout response must not erase cookies from a newer login.
    if (pendingLogout) await pendingLogout
    if (revision !== sessionRevision) throw new Error('登录操作已取消，请重新登录')
    const data = await serializeAuthentication(() => {
      if (revision !== sessionRevision) throw new Error('登录操作已取消，请重新登录')
      return authApi.login(username, password)
    })
    if (revision !== sessionRevision) throw new Error('登录操作已取消，请重新登录')
    if (data.two_factor_required === true) {
      tokenStore.clear(); setOfflineAccount(null)
      set({ user: null, loading: false, meError: false, pendingMfa: data })
      return data as MfaChallenge
    }
    // HYPE-99：浏览器登录走 HttpOnly Cookie；setTokens 只清理历史 storage 令牌、不落盘。
    tokenStore.setTokens(data.access_token, data.refresh_token, remember)
    // HYPE-99：离线队列绑定到登录账号，切换账号互不可见。
    setOfflineAccount(data.user.id)
    set({ user: data.user, loading: false, meError: false, pendingMfa: null })
    return data.user
  },

  beginMfa: challenge => { set({ pendingMfa: challenge }) },

  finishMfa: () => set({ pendingMfa: null }),

  cancelMfa: () => {
    sessionRevision++
    const challenge = get().pendingMfa?.challenge
    if (challenge) void twoFactorApi.cancel(challenge).catch(() => undefined)
    set({ pendingMfa: null })
    if (!get().user) get().logout()
  },

  completeMfa: async (challenge, proof, enroll = false) => {
    if (get().pendingMfa?.challenge !== challenge) throw new Error('登录验证已取消，请重新登录')
    const revision = sessionRevision
    const data = await serializeAuthentication(() => {
      if (revision !== sessionRevision || get().pendingMfa?.challenge !== challenge) throw new Error('登录验证已取消，请重新登录')
      return enroll ? twoFactorApi.confirm(challenge, proof.otp || '') : twoFactorApi.verify(challenge, proof)
    })
    if (revision !== sessionRevision || get().pendingMfa?.challenge !== challenge) throw new Error('登录验证已取消，请重新登录')
    tokenStore.setTokens(data.access_token, data.refresh_token, true)
    setOfflineAccount(data.user.id)
    set({ user: data.user, pendingMfa: enroll ? get().pendingMfa : null, loading: false, meError: false })
    return data
  },

  disableMfa: async otp => {
    const revision = sessionRevision
    const userId = get().user?.id
    await serializeAuthentication(() => {
      if (revision !== sessionRevision || !userId || get().user?.id !== userId) throw new Error('账号已切换，请重新读取状态')
      return twoFactorApi.disable(otp)
    })
    if (revision !== sessionRevision) throw new Error('账号已切换，请重新读取状态')
    get().logout()
  },

  logout: () => {
    sessionRevision++
    // HYPE-99：先解绑离线队列归属（登出后队列不可读，杜绝换号自动提交），
    // 再通知后端清除 HttpOnly 会话 Cookie（失败不阻塞本地清理）。
    setOfflineAccount(null)
    pendingLogout ??= serializeAuthentication(() => authApi.logout()).catch(() => undefined).finally(() => { pendingLogout = null })
    tokenStore.clear()
    set({ user: null, loading: false, meError: false, pendingMfa: null })
  },

  fetchMe: async () => {
    // The old HttpOnly cookie can remain until logout's response arrives.
    // Automatic route recovery must never rebind that explicitly ended account.
    if (pendingLogout || get().loading) return
    const revision = ++sessionRevision
    set({ loading: true, meError: false })
    try {
      const user = await authApi.me()
      if (revision !== sessionRevision) return
      setOfflineAccount(user.id)
      set({ user, loading: false, meError: false })
    } catch {
      if (revision !== sessionRevision) return
      // HYPE-99：/auth/me 失败（403/5xx/网络）时若残留会话标记仍让 isAuthed()=true，
      // 路由守卫不能永久转圈——置 meError，由 ProtectedRoute 渲染错误 + 重试/回登录。
      setOfflineAccount(null)
      set({ user: null, loading: false, meError: true })
    }
  },

  refreshPermissions: () => {
    const current = get().user
    if (!current || get().loading) return Promise.resolve()
    const revision = sessionRevision
    if (pendingPermissions?.id === current.id && pendingPermissions.revision === revision) {
      return pendingPermissions.promise
    }
    const request = { id: current.id, revision, promise: Promise.resolve() }
    request.promise = (async () => {
      try {
        const user = await authApi.me()
        if (revision !== sessionRevision || get().user?.id !== current.id || user.id !== current.id) return
        // Silent refresh never flips the route's loading state, rebinds offline
        // ownership or clears form inputs when unrelated permissions change.
        set({ user })
      } catch {
        // Temporary network/403 failures are not logout instructions. The
        // business request still reports its server error and may be retried.
      } finally {
        if (pendingPermissions === request) pendingPermissions = null
      }
    })()
    pendingPermissions = request
    return request.promise
  },
}))
