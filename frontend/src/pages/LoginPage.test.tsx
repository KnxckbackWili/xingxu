import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

const mockNavigate = vi.fn()
const mockLocation = { search: '', pathname: '/login' }

vi.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
  useLocation: () => mockLocation,
}))

vi.mock('../../api/client', () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
  errMsg: () => 'mock-error',
}))

import { useAuth } from '../stores/auth'
import LoginPage from './LoginPage'

const internUser = { id: 'u-intern', role: 'intern', username: 'intern1', display_name: '实习1' } as any
const pmUser = { id: 'u-pm', role: 'pm', username: 'pm1', display_name: 'PM1' } as any
const workerUser = { id: 'u-w', role: 'worker', username: 'w1', display_name: '现场1' } as any

function loginAs(user: any) {
  useAuth.setState({ user, login: async () => user })
  render(<LoginPage />)
  fireEvent.change(screen.getByPlaceholderText('填写账号'), { target: { value: 'x' } })
  fireEvent.change(screen.getByPlaceholderText('密码'), { target: { value: 'x' } })
  // antd Button 自动给两字中文加空格（登 录）且 jsdom 下 accessible name 为空，用锚定正则定位点击（冒泡到 submit 按钮）
  fireEvent.click(screen.getByText(/^登\s*录$/))
}

beforeEach(() => {
  mockNavigate.mockClear()
  mockLocation.search = ''
})

describe('login next destination safety', () => {
  it('keeps an internal path, query and fragment intact', async () => {
    const target = '/pm/projects/project-a/reports?qa=original-target#main-content'
    mockLocation.search = `?${new URLSearchParams({ next: target })}`
    loginAs(pmUser)
    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith(target, { replace: true }))
  })
  it.each(['https://qa-redirect.invalid', '//qa-redirect.invalid', '/\\qa-redirect.invalid', '/login?next=/pm', '/\n/qa-redirect.invalid'])('rejects unsafe or looping next %j', async target => {
    mockLocation.search = `?${new URLSearchParams({ next: target })}`
    loginAs(pmUser)
    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/pm', { replace: true }))
  })
})

/**
 * 登录落地回归（二审必改 #1）：原逻辑按 `role === 'worker'` 硬编码，
 * 导致 intern 被导向无权访问的 /pm 直接进 403。
 * 现改为按 PM_ROLES 判权：无管理端权限的角色（worker/intern）→ /worker。
 */
describe('登录后按角色落地', () => {
  it('intern 登录后落 /worker（原 bug：被导向 /pm 403）', async () => {
    loginAs(internUser)
    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/worker/week', { replace: true }))
  })

  it('worker 登录后落 /worker', async () => {
    loginAs(workerUser)
    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/worker/week', { replace: true }))
  })

  it('pm 登录后落 /pm（管理端角色不受影响）', async () => {
    loginAs(pmUser)
    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/pm', { replace: true }))
  })
})
