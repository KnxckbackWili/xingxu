import { beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import ForbiddenPage from './ForbiddenPage'
const { navigate, current } = vi.hoisted(() => ({ navigate: vi.fn(), current: { role: 'employee' } }))
vi.mock('react-router-dom', () => ({ useNavigate: () => navigate }))
vi.mock('../stores/auth', () => ({ useAuth: () => ({ user: { role: current.role } }) }))
beforeEach(() => vi.clearAllMocks())
it.each(['employee', 'admin'])('returns %s to the workbench', role => {
  current.role = role
  render(<ForbiddenPage />)
  fireEvent.click(screen.getByRole('button', { name: '回到工作台' }))
  expect(navigate).toHaveBeenCalledWith('/pm/dashboard')
})
