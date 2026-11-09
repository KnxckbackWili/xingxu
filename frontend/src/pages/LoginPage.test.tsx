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

const pmUser = { id: 'u-pm', role: 'admin', username: 'pm1', display_name: 'PM1' } as any
const workerUser = { id: 'u-w', role: 'employee', username: 'w1', display_name: '现场1' } as any

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
    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/pm/dashboard', { replace: true }))
  })
})

describe('登录后进入工作台', () => {
  it.each([['员工', workerUser], ['系统管理员', pmUser]])('%s 登录后进入工作台', async (_, user) => {
    loginAs(user)
    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/pm/dashboard', { replace: true }))
  })
})
