import { beforeEach, describe, expect, it, vi } from 'vitest'
import { StrictMode } from 'react'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import AiTokensPage from './AiTokensPage'

const { session } = vi.hoisted(() => ({ session: { id: 'u1' } }))
vi.mock('../../stores/auth', () => ({ useAuth: (select: any) => select({ user: { id: session.id, role: 'admin' } }) }))

vi.mock('../../api/client', () => ({
  errMsg: () => 'mock-error',
}))

vi.mock('../../api', () => ({
  aiInternalApi: { tokens: vi.fn(), createToken: vi.fn(), updateToken: vi.fn(), revokeToken: vi.fn() },
  userApi: { list: vi.fn() },
}))

import { aiInternalApi, userApi } from '../../api'

const TOKEN = {
  id: 'tk-1',
  name: 'Claude Desktop 接入',
  token_prefix: 'agv_abc',
  user_id: 'u1',
  user_name: '管理员',
  scopes: ['projects:read'],
  expires_at: null,
  is_active: false,
  last_used_at: null,
  created_at: '2026-08-01T10:00:00',
}

/** 移动端：命中 (max-width: 640px)，渲染 mobile-card-list 分支 */
function useMobileMedia() {
  window.matchMedia = ((query: string) => ({
    matches: true,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
}

beforeEach(() => {
  vi.clearAllMocks()
  session.id = 'u1'
  vi.mocked(aiInternalApi.tokens).mockResolvedValue({ items: [TOKEN], scopes: [['projects:read', '项目读取']] } as any)
  vi.mocked(userApi.list).mockResolvedValue([])
  vi.mocked(aiInternalApi.updateToken).mockResolvedValue({} as any)
})

describe('AiTokensPage 移动端卡片 Switch 热区', () => {
  it('每行 Switch 有稳定唯一 id，label htmlFor 匹配；点击 padding 热区只切换一次', async () => {
    useMobileMedia()
    render(<AiTokensPage />)
    await waitFor(() => expect(screen.getByRole('switch')).toBeInTheDocument())

    const sw = screen.getByRole('switch')
    const label = sw.closest('label')!
    expect(sw).toHaveAttribute('id', 'token-switch-tk-1')
    expect(label).toHaveAttribute('for', 'token-switch-tk-1')

    fireEvent.click(label)
    await waitFor(() => {
      expect(aiInternalApi.updateToken).toHaveBeenCalledTimes(1)
      expect(aiInternalApi.updateToken).toHaveBeenCalledWith('tk-1', { is_active: true })
    })
  })

  it('点击 Switch 本体不重复切换（updateToken 只调用一次）', async () => {
    useMobileMedia()
    render(<AiTokensPage />)
    await waitFor(() => expect(screen.getByRole('switch')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('switch'))
    await waitFor(() => {
      expect(aiInternalApi.updateToken).toHaveBeenCalledTimes(1)
      expect(aiInternalApi.updateToken).toHaveBeenCalledWith('tk-1', { is_active: true })
    })
  })
})

it('新令牌默认选择只读范围', async () => {
  vi.mocked(aiInternalApi.tokens).mockResolvedValue({ items: [TOKEN], scopes: [
    ['projects:read', '项目读取'], ['templates:read', '实施模板'],
  ] } as any)
  render(<AiTokensPage />)
  await screen.findByText(TOKEN.name)
  fireEvent.click(screen.getByRole('button', { name: /创建令牌/ }))
  expect(screen.getByRole('checkbox', { name: '项目读取' })).toBeChecked()
  expect(screen.getByRole('checkbox', { name: '实施模板' })).toBeChecked()
  expect(screen.getByText(/Bearer \$\{AGV_AGENT_TOKEN\}/)).toBeInTheDocument()
})

it('explains current read-only tools without promising drafts or business writes', async () => {
  render(<AiTokensPage />)
  await screen.findByText(TOKEN.name)
  fireEvent.click(screen.getByText('连接外部助手与权限说明'))
  expect(screen.getByText('外部助手只读')).toBeInTheDocument()
  expect(screen.getByText(/业务修改由有权限的人在对应页面核对后操作/)).toBeInTheDocument()
  expect(screen.getByText(/实际工具以服务端目录为准/)).toBeInTheDocument()
  expect(screen.queryByText(/提出变更只会生成草稿|合并与回退会立即修改项目|写入单独授权/)).toBeNull()
  expect(aiInternalApi.createToken).not.toHaveBeenCalled()
})

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

it('serializes repeated toggles and blocks revoke while an update is pending', async () => {
  const pending = deferred<any>()
  vi.mocked(aiInternalApi.tokens).mockResolvedValue({ items: [{ ...TOKEN, is_active: true }], scopes: [] })
  vi.mocked(aiInternalApi.updateToken).mockReturnValueOnce(pending.promise)
  render(<AiTokensPage />)
  await screen.findByText(TOKEN.name)
  const sw = screen.getByRole('switch')
  act(() => { fireEvent.click(sw); fireEvent.click(sw) })
  expect(aiInternalApi.updateToken).toHaveBeenCalledExactlyOnceWith(TOKEN.id, { is_active: false })
  expect(sw).toBeDisabled()
  expect(screen.getByRole('button', { name: /停\s*用/ })).toBeDisabled()
  vi.mocked(aiInternalApi.tokens).mockRejectedValueOnce(new Error('offline'))
  await act(async () => pending.resolve({}))
  expect(sw).not.toBeChecked()
  expect(aiInternalApi.revokeToken).not.toHaveBeenCalled()
})

it('keeps confirmed revocation on refresh failure and ignores a stale earlier response', async () => {
  const old = deferred<any>()
  vi.mocked(aiInternalApi.tokens).mockReturnValueOnce(old.promise).mockResolvedValue({ items: [{ ...TOKEN, is_active: true }], scopes: [] })
  vi.mocked(aiInternalApi.revokeToken).mockResolvedValue({})
  render(<StrictMode><AiTokensPage /></StrictMode>)
  await screen.findByText(TOKEN.name)
  vi.mocked(aiInternalApi.tokens).mockRejectedValueOnce(new Error('offline'))
  fireEvent.click(screen.getByRole('button', { name: /停\s*用/ }))
  fireEvent.click(await screen.findByRole('button', { name: 'OK' }))
  await waitFor(() => expect(aiInternalApi.revokeToken).toHaveBeenCalledExactlyOnceWith(TOKEN.id))
  await waitFor(() => expect(screen.getByRole('switch')).not.toBeChecked())
  await act(async () => old.resolve({ items: [{ ...TOKEN, is_active: true }], scopes: [] }))
  expect(screen.getByRole('switch')).not.toBeChecked()
})

it('locks token creation, retains the form on failure, and displays one created token', async () => {
  const pending = deferred<any>()
  vi.mocked(aiInternalApi.createToken).mockReturnValueOnce(pending.promise).mockResolvedValue({ token: 'mock-token-created' })
  vi.mocked(userApi.list).mockResolvedValue([
    { id: 'u1', display_name: '测试账号', username: 'test', is_active: true },
    { id: 'disabled', display_name: '停用账号', username: 'disabled', is_active: false },
  ] as any)
  render(<AiTokensPage />)
  await screen.findByText(TOKEN.name)
  fireEvent.click(screen.getByRole('button', { name: /创建令牌/ }))
  const dialog = screen.getByRole('dialog')
  fireEvent.change(within(dialog).getByRole('textbox', { name: '名称' }), { target: { value: 'mock-agent' } })
  fireEvent.mouseDown(within(dialog).getAllByRole('combobox')[0])
  expect(screen.queryByText('停用账号（disabled）')).not.toBeInTheDocument()
  fireEvent.click(await screen.findByText('测试账号（test）'))
  const form = dialog.querySelector('form')!
  await act(async () => { fireEvent.submit(form); fireEvent.submit(form) })
  expect(aiInternalApi.createToken).toHaveBeenCalledTimes(1)
  expect(within(dialog).getByRole('button', { name: /Cancel|取\s*消/ })).toBeDisabled()
  await act(async () => pending.reject(new Error('offline')))
  await act(async () => fireEvent.submit(form))
  expect(aiInternalApi.createToken).toHaveBeenCalledTimes(2)
  expect(await screen.findByText('mock-token-created')).toBeInTheDocument()
})

it('ignores creation validated after the dialog has been canceled', async () => {
  vi.mocked(userApi.list).mockResolvedValue([{ id: 'u1', display_name: '测试账号', username: 'test', is_active: true }] as any)
  render(<AiTokensPage />)
  await screen.findByText(TOKEN.name)
  fireEvent.click(screen.getByRole('button', { name: /创建令牌/ }))
  const dialog = screen.getByRole('dialog')
  fireEvent.change(within(dialog).getByRole('textbox', { name: '名称' }), { target: { value: 'mock-agent' } })
  fireEvent.mouseDown(within(dialog).getAllByRole('combobox')[0])
  fireEvent.click(await screen.findByText('测试账号（test）'))
  act(() => { fireEvent.submit(dialog.querySelector('form')!); fireEvent.click(within(dialog).getByRole('button', { name: /Cancel|取\s*消/ })) })
  await act(async () => {})
  expect(aiInternalApi.createToken).not.toHaveBeenCalled()
})

it('does not refresh after a late token-status update following navigation', async () => {
  const pending = deferred<any>()
  vi.mocked(aiInternalApi.updateToken).mockReturnValueOnce(pending.promise)
  const { unmount } = render(<AiTokensPage />)
  await screen.findByText(TOKEN.name)
  fireEvent.click(screen.getByRole('switch'))
  unmount()
  await act(async () => pending.resolve({}))
  expect(aiInternalApi.tokens).toHaveBeenCalledTimes(1)
})


it('never reveals a late-created token to a different account', async () => {
  const pending = deferred<any>()
  vi.mocked(aiInternalApi.createToken).mockReturnValueOnce(pending.promise)
  vi.mocked(userApi.list).mockResolvedValue([{ id: 'u1', display_name: '测试账号', username: 'test', is_active: true }] as any)
  const { rerender } = render(<AiTokensPage />)
  await screen.findByText(TOKEN.name)
  fireEvent.click(screen.getByRole('button', { name: /创建令牌/ }))
  const dialog = screen.getByRole('dialog')
  fireEvent.change(within(dialog).getByRole('textbox', { name: '名称' }), { target: { value: 'mock-agent' } })
  fireEvent.mouseDown(within(dialog).getAllByRole('combobox')[0])
  fireEvent.click(await screen.findByText('测试账号（test）'))
  await act(async () => fireEvent.submit(dialog.querySelector('form')!))
  expect(aiInternalApi.createToken).toHaveBeenCalledTimes(1)
  session.id = 'u2'
  vi.mocked(aiInternalApi.tokens).mockResolvedValue({ items: [], scopes: [] })
  await act(async () => rerender(<AiTokensPage />))
  await act(async () => pending.resolve({ token: 'previous-account-token' }))
  expect(screen.queryByText('previous-account-token')).not.toBeInTheDocument()
  expect(aiInternalApi.tokens).toHaveBeenCalledTimes(2)
})

it('puts active connections before collapsed technical setup and exposes a single create action', async () => {
  vi.mocked(aiInternalApi.tokens).mockResolvedValue({ items: [], scopes: [] })
  render(<AiTokensPage />)
  await screen.findByText('还没有访问令牌，点击上方创建')
  expect(screen.getAllByRole('button', { name: /创建令牌/ })).toHaveLength(1)
  const setup = screen.getByText('连接外部助手与权限说明').closest('details')
  expect(setup).not.toHaveAttribute('open')
  expect(aiInternalApi.createToken).not.toHaveBeenCalled()
})

it('keeps Agent and existing budget together in settings and exposes current read-only scopes only', async () => {
  vi.mocked(aiInternalApi.tokens).mockResolvedValue({ items: [], scopes: [
    ['projects:read', '项目读取'], ['files:read', '资料清单与本周待交'], ['vehicles:read', '车辆进度表'], ['schedule:preview', '旧排程预览'],
  ], budget: { enabled: true, blocked: true, reason: '月度请求次数已达上限', limits: { requests: 20, tokens: 20000 }, usage: { month: '2026-10', requests: 20, tokens: 3000 } } } as any)
  render(<AiTokensPage />)
  expect(await screen.findByText('AI 用量预算')).toBeVisible()
  expect(await screen.findByText('月度请求次数已达上限')).toBeVisible()
  expect(screen.getByText(/系统模型调用 20 次/)).toHaveTextContent('3000 / 20000 tokens')
  expect(screen.getByText(/只读接入，用于整理文字/)).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: /创建令牌/ }))
  expect(await screen.findByRole('checkbox', { name: '资料清单与本周待交' })).toBeChecked()
  expect(screen.getByRole('checkbox', { name: '车辆进度表' })).toBeChecked()
  expect(screen.queryByRole('checkbox', { name: '旧排程预览' })).toBeNull()
})
