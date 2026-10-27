import { expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import WorkerLayout from './WorkerLayout'

vi.mock('../stores/auth', () => ({ useAuth: () => ({ user: { display_name: '现场测试员' }, logout: vi.fn() }) }))
vi.mock('../stores/theme', () => ({ useThemeStore: (selector: (value: unknown) => unknown) => selector({ mode: 'light', toggle: vi.fn() }) }))
vi.mock('../components/NotificationBell', () => ({ default: () => null }))
vi.mock('../components/ChangePasswordModal', () => ({ default: ({ open }: { open: boolean }) => open ? <div role="dialog">修改密码表单</div> : null }))

it('opens the account menu by a button click and exposes the password action without requiring hover', async () => {
  render(<MemoryRouter><WorkerLayout /></MemoryRouter>)
  fireEvent.click(screen.getByRole('button', { name: '账户菜单：现场测试员' }))
  const password = await screen.findByText('修改密码')
  expect(screen.getByText('退出登录')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '账户菜单：现场测试员' })).toHaveAttribute('aria-expanded', 'true')
  fireEvent.keyDown(window, { key: 'Escape' })
  expect(screen.getByRole('button', { name: '账户菜单：现场测试员' })).toHaveAttribute('aria-expanded', 'false')
  expect(screen.getByRole('button', { name: '账户菜单：现场测试员' })).toHaveFocus()
  fireEvent.click(screen.getByRole('button', { name: '账户菜单：现场测试员' }))
  fireEvent.click(password)
  expect(await screen.findByRole('dialog')).toHaveTextContent('修改密码表单')
})
