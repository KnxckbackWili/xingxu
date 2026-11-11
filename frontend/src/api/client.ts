import axios from 'axios'
import { message } from 'antd'

function cookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`))
  return match ? decodeURIComponent(match[1]) : null
}

/** Signed in: the readable marker cookie that accompanies the HttpOnly session cookies. */
export function isAuthed(): boolean {
  return !!cookie('agvpm_session')
}

/** Headers for requests that do not go through axios (file uploads use it too). */
export function csrfHeaders(): Record<string, string> {
  const token = cookie('agvpm_csrf')
  return token ? { 'X-CSRF-Token': token } : {}
}

/** Where an expired session goes. The sign-in page never names itself as the way back. */
export function sessionExpiredTarget(path: string): string | null {
  if (!path || path === '/' || path.startsWith('/login')) return null
  return `/login?expired=1&next=${encodeURIComponent(path)}`
}

export const api = axios.create({ baseURL: '/api', timeout: 20000, withCredentials: true })

api.interceptors.request.use((config) => {
  if (!['GET', 'HEAD', 'OPTIONS'].includes((config.method ?? 'get').toUpperCase())) Object.assign(config.headers, csrfHeaders())
  return config
})

api.interceptors.response.use(undefined, async (error) => {
  const original = error.config
  const url: string = original?.url ?? ''
  // A wrong password is an answer, not an expired session.
  if (url.endsWith('/auth/login') || url.endsWith('/auth/refresh')) return Promise.reject(error)
  if (error.response?.status === 401 && !original._retry && isAuthed()) {
    original._retry = true
    try {
      await axios.post('/api/auth/refresh', {}, { withCredentials: true })
      return api(original)
    } catch {
      const target = sessionExpiredTarget(window.location.pathname + window.location.search)
      if (target) window.location.href = target
    }
  }
  return Promise.reject(error)
})

export function errMsg(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) return detail.map((item: { msg?: string }) => item.msg).join('；')
    const status = error.response?.status
    if (status === 503) return '系统正在更新，请稍后再试'
    if (status && status >= 500) return '服务器出错了，请稍后再试'
    if (status === 413) return '文件太大'
    if (status === 404) return '内容不存在或已被删除'
    if (status === 403) return '没有权限'
    if (status === 401) return '登录已过期，请重新登录'
    if (error.code === 'ECONNABORTED') return '请求超时，请检查网络后重试'
  }
  if (typeof navigator !== 'undefined' && !navigator.onLine) return '没有网络，暂时不能保存'
  return error instanceof Error && !axios.isAxiosError(error) ? error.message : '网络异常，请稍后重试'
}

export function showErr(error: unknown) {
  message.error(errMsg(error))
}

export function newId(): string {
  return crypto.randomUUID()
}
