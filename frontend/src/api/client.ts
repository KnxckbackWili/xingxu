import axios from 'axios'
import { getOfflineAccount } from '../offline/queue'
import { OFFLINE_ACCOUNT_HEADER } from '../offline/cacheKey'
import { message } from 'antd'
import { SYSTEM_PERMISSION_REFRESH_EVENT } from '../constants/systemPermissions'

const TOKEN_KEY = 'agvpm_token'
const REFRESH_KEY = 'agvpm_refresh'
const SESSION_TOKEN_KEY = 'agvpm_token_session'
const SESSION_REFRESH_KEY = 'agvpm_refresh_session'
// P2-安全：HttpOnly Cookie 会话标记 / CSRF 双提交 cookie（后端 set_auth_cookies 写入）
const SESSION_MARKER_COOKIE = 'agvpm_session'
const CSRF_COOKIE = 'agvpm_csrf'

function getCookie(name: string): string | null {
  if (typeof document === 'undefined') return null
  const m = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`))
  return m ? decodeURIComponent(m[1]) : null
}

/** 是否已登录：HttpOnly Cookie 会话标记（浏览器 JWT 已不落 storage，tokenStore.access 恒为 null）。 */
export function isAuthed(): boolean {
  return !!tokenStore.access || !!getCookie(SESSION_MARKER_COOKIE)
}

/** CSRF 双提交 token（读自非 HttpOnly 的 agvpm_csrf cookie）。 */
export function getCsrfToken(): string | null {
  return getCookie(CSRF_COOKIE)
}

/** 非 axios 请求（SSE/流式 fetch）的认证头：cookie 会话发 CSRF 头（storage 令牌已废弃）。 */
export function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = {}
  const token = tokenStore.access
  if (token) {
    headers.Authorization = `Bearer ${token}`
  } else {
    const csrf = getCsrfToken()
    if (csrf) headers['X-CSRF-Token'] = csrf
  }
  return headers
}

function clearOfflineApiCache() {
  if ('caches' in window) {
    void window.caches.delete('agvpm-api')
  }
}

const STORAGE_TOKEN_KEYS = [TOKEN_KEY, REFRESH_KEY, SESSION_TOKEN_KEY, SESSION_REFRESH_KEY]

/**
 * HYPE-99 浏览器认证安全契约：清掉历史 localStorage/sessionStorage 令牌。
 * 残留 access token 会以 Bearer 头走「免 CSRF」通道，绕过 HttpOnly Cookie/CSRF
 * 防线——因此模块加载、登录、登出、续期成功时都主动清除，浏览器内永不落盘。
 */
function purgeStorageTokens() {
  for (const key of STORAGE_TOKEN_KEYS) {
    try { localStorage.removeItem(key) } catch { /* 隐私模式等不可用场景忽略 */ }
    try { sessionStorage.removeItem(key) } catch { /* ignore */ }
  }
  clearOfflineApiCache()
}

// 模块加载即清理一次：升级前版本曾把令牌写进 storage，不能让残留会话继续生效。
purgeStorageTokens()

export const tokenStore = {
  // HYPE-99：浏览器登录一律走 HttpOnly Cookie（agvpm_access / agvpm_refresh）。
  // access/refresh 恒为 null，JWT 不写进 localStorage/sessionStorage。
  // 非浏览器 API 客户端（脚本/curl/集成）直接用后端登录响应里的 access_token 走
  // Bearer，那是独立通道（后端 deps.get_current_user 仍支持），与本前端无关。
  get access(): string | null {
    return null
  },
  set access(_v: string | null) {
    // 静默丢弃：任何残余写路径都不允许把令牌写回 storage
  },
  get refresh(): string | null {
    return null
  },
  set refresh(_v: string | null) {
    // 静默丢弃
  },
  /** 兼容历史调用点（登录）：只做清理，绝不落盘。 */
  setTokens(_access: string | null, _refresh: string | null, _remember: boolean) {
    purgeStorageTokens()
  },
  clear() {
    purgeStorageTokens()
  },
}

/**
 * 会话过期后的跳转目标。登录页自身绝不能被写进 next（HYPE-56 二审）：
 * 旧 token/cookie 残留时，登录页会反复触发 fetchMe→401→refresh→失败，
 * 若把登录页 URL（含已嵌套的 next）写进 next 重定向，会一层层递归增长
 * 成 `/login?expired=1&next=/login?expired=1&next=...` 的路由级死循环。
 * - 已在登录页/根路径：返回 null，不再跳转（登录页是公开页，停留即可）；
 * - 其他路径：返回带原地址 next 的登录 URL，登录成功后跳回保留操作上下文。
 */
export function sessionExpiredTarget(currentPath: string): string | null {
  if (!currentPath || currentPath === '/' || currentPath.startsWith('/login')) {
    return null
  }
  return `/login?expired=1&next=${encodeURIComponent(currentPath)}`
}

export const api = axios.create({
  baseURL: '/api',
  timeout: 15000,
  withCredentials: true, // 携带 HttpOnly 会话 Cookie（同源必发；dev 跨源也带上）
})

api.interceptors.request.use((config) => {
  const owner = getOfflineAccount()
  // A view may supply its captured account; never overwrite it with a newer
  // global binding after another tab changed the cookie session.
  if (owner && !config.headers['X-AGV-Expected-Account']) config.headers['X-AGV-Expected-Account'] = owner
  if (owner && /^\/worker\/(today|records|schedule)(?:\?|$)/.test(config.url ?? '')) {
    config.headers[OFFLINE_ACCOUNT_HEADER] = owner
  }
  const token = tokenStore.access
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  // cookie 会话的写请求需回传 X-CSRF-Token（与 agvpm_csrf cookie 双提交）
  const method = (config.method ?? 'get').toUpperCase()
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    const csrf = getCsrfToken()
    if (csrf) config.headers['X-CSRF-Token'] = csrf
  }
  return config
}, undefined, { synchronous: true })

api.interceptors.response.use(
  (resp) => resp,
  async (error) => {
    const original = error.config
    // 登录/刷新接口自身的 401 是业务错误（密码错误/无效令牌），不是会话过期：
    // 不能走 refresh 重试或跳转登录页，否则密码错误时页面会被整页刷新（/login?expired=1）
    // 且输入丢失，造成"一直刷新界面"的观感。登录 401 必须原样透传给表单提示。
    const url: string = original?.url ?? ''
    if (url.endsWith('/auth/login') || url.endsWith('/auth/refresh') || url.includes('/auth/2fa/')) {
      return Promise.reject(error)
    }
    if (error.response?.status === 403 && !url.endsWith('/auth/me') && isAuthed()) {
      window.dispatchEvent(new Event(SYSTEM_PERMISSION_REFRESH_EVENT))
    }
    // 401：靠 HttpOnly refresh Cookie 续期一次（SPA 不落盘 refresh_token）。
    // cookie 会话的 marker（agvpm_session）还在即视为可续期会话。
    if (error.response?.status === 401 && !original._retry && isAuthed()) {
      original._retry = true
      try {
        // HYPE-99：浏览器一律走 Cookie 续期（后端 Refresh 端点同时接受 body / Cookie，
        // 浏览器只走 Cookie 通道，避免把 refresh_token 读进 JS）。
        await axios.post('/api/auth/refresh', {}, { withCredentials: true })
        // 续期成功：Set-Cookie 已自动更新；清掉任何历史 storage 令牌，重试走 cookie 认证
        purgeStorageTokens()
        delete original.headers.Authorization
        return api(original)
      } catch {
        tokenStore.clear()
        // HYPE-56：会话过期跳转绝不能把登录页自身写进 next，否则每次 refresh 失败都会把
        // 当前 URL（含已嵌套的 next）再编码一层，形成路由级递归死循环；已在登录页时直接停留。
        const target = sessionExpiredTarget(window.location.pathname + window.location.search)
        if (target) {
          window.location.href = target
        }
      }
    }
    return Promise.reject(error)
  },
)

/** Extract Chinese error message from API error. */
export function errMsg(e: unknown): string {
  if (axios.isAxiosError(e)) {
    const detail = (e.response?.data as any)?.detail
    if (typeof detail === 'string') return detail
    if (detail && typeof detail.message === 'string') return detail.message
    if (Array.isArray(detail)) return detail.map((d: any) => d.msg).join('; ')
    const status = e.response?.status
    if (status && status >= 500) return '服务器内部错误，请稍后重试'
    if (status === 409) return '数据已被他人修改，请刷新后重试'
    if (status === 404) return '请求的资源不存在'
    if (status === 403) return '没有权限执行此操作'
    if (status === 401) return '登录已过期，请重新登录'
    if (e.code === 'ECONNABORTED') return '请求超时，请检查网络后重试'
  }
  if (!navigator.onLine) return '当前离线，请连接网络后重试'
  return '网络异常，请检查网络连接后重试'
}

/** Show error toast. */
export function showErr(e: unknown) {
  message.error(errMsg(e))
}
