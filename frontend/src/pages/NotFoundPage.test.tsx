import { beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import type { PermissionUser } from '../constants/systemPermissions'
import NotFoundPage from './NotFoundPage'

const { navigate, current } = vi.hoisted(() => ({
  navigate: vi.fn(), current: { user: null as PermissionUser | null },
}))
vi.mock('react-router-dom', () => ({ useNavigate: () => navigate }))
vi.mock('../stores/auth', () => ({ useAuth: () => ({ user: current.user }) }))
beforeEach(() => { vi.clearAllMocks(); current.user = null })

it.each([
  [{ role: 'pm' }, '/pm/dashboard'],
  [{ role: 'worker' }, '/worker/today'],
  [{ role: 'pm', permission_overrides: { 'workspace.view': false } }, '/pm/projects'],
] as const)('returns an authenticated user to their authorized home', (user, target) => {
  current.user = user
  render(<NotFoundPage />)
  fireEvent.click(screen.getByRole('button', { name: '返回首页' }))
  expect(navigate).toHaveBeenCalledWith(target)
})

it('returns an unauthenticated user to login', () => {
  render(<NotFoundPage />)
  fireEvent.click(screen.getByRole('button', { name: '返回首页' }))
  expect(navigate).toHaveBeenCalledWith('/login')
})
