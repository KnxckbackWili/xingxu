import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// client.ts 在模块加载时即创建 axios 实例并注册拦截器，
// 因此在 import 之前 mock 'axios'，捕获实例上注册的拦截器回调，
// 直接对响应拦截器（onRejected）做行为回归。
const { axiosMock, apiMock, responseErrHandlers, requestHandlers } = vi.hoisted(() => {
  const responseErrHandlers: Array<(err: unknown) => unknown> = []
  const requestHandlers: Array<(config: any) => unknown> = []
  // apiMock 必须是可调用函数：拦截器 refresh 成功后 `return api(original)` 会调用它。
  const apiMock = vi.fn(async (config: any) => ({ data: 'retried', config }))
  Object.assign(apiMock, {
    interceptors: {
      request: { use: (fn: any) => { requestHandlers.push(fn) } },
      response: { use: (_ok: any, err: any) => { responseErrHandlers.push(err) } },
    },
    defaults: { headers: { common: {} } },
    post: vi.fn(),
    get: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  })
  const axiosMock = {
    create: vi.fn(() => apiMock),
    post: vi.fn(),
    isAxiosError: (e: any) => e?.isAxiosError === true,
  }
  return { axiosMock, apiMock, responseErrHandlers, requestHandlers }
})

vi.mock('axios', () => ({ default: axiosMock }))

import { errMsg, tokenStore, sessionExpiredTarget } from './client'
import { SYSTEM_PERMISSION_REFRESH_EVENT } from '../constants/systemPermissions'
import { setOfflineAccount } from '../offline/queue'

it('preserves a view-captured account header after another tab changes the global binding', () => {
  setOfflineAccount('account-b')
  const config: any = { url: '/worker/operations', method: 'post', headers: { 'X-AGV-Expected-Account': 'account-a' } }
  requestHandlers[0](config)
  expect(config.headers['X-AGV-Expected-Account']).toBe('account-a')
  const current: any = { url: '/worker/operations', method: 'post', headers: {} }
  requestHandlers[0](current)
  expect(current.headers['X-AGV-Expected-Account']).toBe('account-b')
})

const onRejected = responseErrHandlers[0]

const TOKEN_KEY = 'agvpm_token'
const SESSION_TOKEN_KEY = 'agvpm_token_session'

function make401(config: { url: string; method: string }) {
  return {
    isAxiosError: true,
    response: { status: 401, data: { detail: '未认证' } },
    config: { ...config, headers: {} },
  }
}

function setCookieSession() {
  document.cookie = 'agvpm_session=1; path=/'
}
function clearCookieSession() {
  document.cookie = 'agvpm_session=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT'
}

beforeEach(() => {
  axiosMock.post.mockReset()
  apiMock.mockClear()
  localStorage.clear()
  sessionStorage.clear()
  clearCookieSession()
  tokenStore.clear()
})

/**
 * HYPE-56 回归：密码错误登录（/auth/login 401）此前被响应拦截器误判为"会话过期"，
 * 走 refresh 流程——refresh 成功则徒劳重发一次注定失败的登录并轮换令牌；
 * refresh 失败则 `window.location.href = /login?expired=1` 整页刷新、输入丢失，
 * 表现为"密码登录错误后界面持续刷新"。
 * 修复：登录/刷新接口的 401 直接透传，不触发 refresh、不跳转。
 * HYPE-99：浏览器不再把令牌写进 storage，残留的历史 token 也不影响透传判断。
 */
describe('登录接口 401 不透传 refresh 逻辑（HYPE-56/HYPE-99）', () => {
  it('密码错误登录：原样拒绝，不调 /auth/refresh，不跳转登录页', async () => {
    // 即使浏览器残留旧版本的 storage token（模块加载已清理，access 恒为 null），仍原样拒绝
    localStorage.setItem(TOKEN_KEY, 'stale-access')
    const loginErr = make401({ url: '/auth/login', method: 'post' })

    await expect(onRejected(loginErr)).rejects.toBe(loginErr)

    expect(axiosMock.post).not.toHaveBeenCalled()
    expect(window.location.href).not.toContain('expired=1')
  })

  it('错误密码提示稳定：errMsg 返回服务端 detail「用户名或密码错误」', () => {
    const e = { isAxiosError: true, response: { status: 401, data: { detail: '用户名或密码错误' } } }
    expect(errMsg(e)).toBe('用户名或密码错误')
  })

  it('无任何会话标记时登录 401 同样原样透传', async () => {
    const loginErr = make401({ url: '/auth/login', method: 'post' })
    await expect(onRejected(loginErr)).rejects.toBe(loginErr)
    expect(axiosMock.post).not.toHaveBeenCalled()
  })
})

describe('业务接口 401 → HttpOnly Cookie 续期（HYPE-99）', () => {
  it('有 cookie 会话标记：调 /auth/refresh（空 body + credentials）成功后重试原请求，且不落盘令牌', async () => {
    axiosMock.post.mockResolvedValueOnce({ data: { access_token: 'new-access', refresh_token: 'new-refresh' } })
    setCookieSession()
    const err = make401({ url: '/api/projects', method: 'get' })

    const result = await onRejected(err)

    // 只走 Cookie 通道：请求体不带 refresh_token
    expect(axiosMock.post).toHaveBeenCalledWith(
      '/api/auth/refresh',
      {},
      { withCredentials: true },
    )
    expect(result).toEqual({ data: 'retried', config: expect.objectContaining({ _retry: true }) })
    // 服务端即便回传新令牌，前端也绝不写进 localStorage/sessionStorage
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull()
    expect(sessionStorage.getItem(SESSION_TOKEN_KEY)).toBeNull()
  })

  it('无 cookie 会话标记：401 不触发 refresh，原样拒绝', async () => {
    const err = make401({ url: '/api/projects', method: 'get' })
    await expect(onRejected(err)).rejects.toBe(err)
    expect(axiosMock.post).not.toHaveBeenCalled()
  })
})

describe('请求拦截器（HYPE-99 浏览器不再走 Bearer）', () => {
  it('即使 storage 残留历史 token，也不附加 Authorization: Bearer', () => {
    localStorage.setItem(TOKEN_KEY, 'legacy-access-tok')
    const config: any = { headers: {} }
    requestHandlers[0](config)
    expect(config.headers.Authorization).toBeUndefined()
  })

  it('cookie 会话写请求回传 X-CSRF-Token（双提交），GET 不带', () => {
    document.cookie = 'agvpm_csrf=csrf-token-abc; path=/'
    const write: any = { method: 'post', headers: {} }
    requestHandlers[0](write)
    expect(write.headers['X-CSRF-Token']).toBe('csrf-token-abc')

    const read: any = { method: 'get', headers: {} }
    requestHandlers[0](read)
    expect(read.headers['X-CSRF-Token']).toBeUndefined()
  })
})

describe('permission changes are refreshed without logging out', () => {
  it('signals a business 403 but preserves the original error and session', async () => {
    setCookieSession()
    const listener = vi.fn()
    window.addEventListener(SYSTEM_PERMISSION_REFRESH_EVENT, listener)
    const error = { ...make401({ url: '/templates', method: 'put' }), response: { status: 403 } }
    try {
      await expect(onRejected(error)).rejects.toBe(error)
      expect(listener).toHaveBeenCalledTimes(1)
      expect(axiosMock.post).not.toHaveBeenCalled()
      expect(document.cookie).toContain('agvpm_session=1')
      await expect(onRejected({ ...error, config: { url: '/auth/me' } })).rejects.toBeDefined()
      expect(listener).toHaveBeenCalledTimes(1)
    } finally { window.removeEventListener(SYSTEM_PERMISSION_REFRESH_EVENT, listener) }
  })
})

describe('tokenStore：浏览器永不落盘，历史令牌安全清理（HYPE-99）', () => {
  it('setTokens/clear 只清理历史 storage 令牌，不写入任何新令牌', () => {
    localStorage.setItem(TOKEN_KEY, 'old-access')
    sessionStorage.setItem(SESSION_TOKEN_KEY, 'old-session')
    tokenStore.setTokens('new-access', 'new-refresh', true)
    expect(tokenStore.access).toBeNull()
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull()
    expect(sessionStorage.getItem(SESSION_TOKEN_KEY)).toBeNull()
  })

  it('模块加载已清理历史令牌：import 后残留键不存在', () => {
    // client.ts 在 import 时调用 purgeStorageTokens()；此处由 beforeEach 写入后再次 clear 验证
    localStorage.setItem(TOKEN_KEY, 'x')
    tokenStore.clear()
    expect(tokenStore.access).toBeNull()
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull()
  })
})

/**
 * HYPE-56 二审回归：上一轮只堵住了登录 API 401 的 refresh 重试，遗漏了「会话过期跳转
 * 把登录页自身写进 next」的路由级递归——旧 token/cookie 残留时，登录页反复
 * fetchMe→401→refresh→失败→重定向，next 一层层嵌套，用户外网 URL 出现指数级增长
 * 的 `/login?expired=1&next=/login?expired=1&next=...`。
 * 修复：登录页/根路径不再跳转；业务页才带原地址 next。
 */
describe('sessionExpiredTarget：登录页绝不写入 next', () => {
  it('已在登录页（含带 next 的）→ 不再跳转', () => {
    expect(sessionExpiredTarget('/login')).toBeNull()
    expect(sessionExpiredTarget('/login?expired=1&next=%2Fpm')).toBeNull()
  })

  it('根路径 → 不再跳转', () => {
    expect(sessionExpiredTarget('/')).toBeNull()
  })

  it('业务页面 → 只带原地址 next 跳登录，next 不含登录页自身', () => {
    expect(sessionExpiredTarget('/pm/dashboard')).toBe('/login?expired=1&next=%2Fpm%2Fdashboard')
    expect(sessionExpiredTarget('/worker/today')).toBe('/login?expired=1&next=%2Fworker%2Ftoday')
  })
})

describe('refresh 失败后的会话过期跳转（HYPE-56 二审 / HYPE-99 Cookie 会话）', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('已在登录页：refresh 失败后不跳转、不把登录页写进 next', async () => {
    vi.stubGlobal('location', {
      pathname: '/login',
      search: '?expired=1&next=%2Fpm',
      href: 'http://localhost:3000/login?expired=1&next=%2Fpm',
    })
    axiosMock.post.mockRejectedValueOnce(make401({ url: '/auth/refresh', method: 'post' }))
    setCookieSession()
    const err = make401({ url: '/api/projects', method: 'get' })

    await expect(onRejected(err)).rejects.toBe(err)
    expect(tokenStore.access).toBeNull()
    // 未发生跳转：href 保持原值，登录页 URL 不再被包进 next
    expect(globalThis.location.href).toBe('http://localhost:3000/login?expired=1&next=%2Fpm')
  })

  it('业务页：refresh 失败后带原地址 next 跳登录页', async () => {
    vi.stubGlobal('location', {
      pathname: '/pm/dashboard',
      search: '',
      href: 'http://localhost:3000/pm/dashboard',
    })
    axiosMock.post.mockRejectedValueOnce(make401({ url: '/auth/refresh', method: 'post' }))
    setCookieSession()
    const err = make401({ url: '/api/projects', method: 'get' })

    await expect(onRejected(err)).rejects.toBe(err)
    expect(globalThis.location.href).toBe('/login?expired=1&next=%2Fpm%2Fdashboard')
  })
})

it('formats all lifecycle blockers as the server summary', () => {
  expect(errMsg({ isAxiosError: true, response: { status: 400, data: { detail: {
    message: '资料未提交；问题未关闭', blockers: [{ type: 'documents' }, { type: 'issues' }],
  } } } })).toBe('资料未提交；问题未关闭')
})


it.each(['/auth/2fa/verify', '/auth/2fa/enroll/confirm', '/auth/2fa/recovery-codes', '/auth/2fa/disable', '/auth/2fa/recover/start'])('does not auto-retry factor proof or refresh cookies for %s', async url => {
  setCookieSession()
  const error = make401({ url, method: 'post' })
  await expect(onRejected(error)).rejects.toBe(error)
  expect(axiosMock.post).not.toHaveBeenCalled()
  expect(apiMock).not.toHaveBeenCalled()
})
