import { expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import PmLayout from './PmLayout'
import WorkerLayout from './WorkerLayout'

const { put } = vi.hoisted(() => ({ put: vi.fn() }))
vi.mock('../api/client', () => ({ api: { put } }))
vi.mock('../stores/auth', () => ({ useAuth: () => ({ user: { role: 'pm', display_name: '焦点测试员' }, logout: vi.fn() }) }))
vi.mock('../stores/theme', () => ({ useThemeStore: (selector: (value: unknown) => unknown) => selector({ mode: 'light', toggle: vi.fn() }) }))
vi.mock('../components/NotificationBell', () => ({ default: () => null }))

it.each([
  { name: 'PM', Shell: PmLayout, closeAction: 'Escape' },
  { name: 'PM', Shell: PmLayout, closeAction: '取消' },
  { name: '现场', Shell: WorkerLayout, closeAction: 'Escape' },
  { name: '现场', Shell: WorkerLayout, closeAction: '取消' },
])('$name returns password-dialog focus to the account button after $closeAction closes it', async ({ Shell, closeAction }) => {
  put.mockClear()
  render(<MemoryRouter><Shell /></MemoryRouter>)
  const account = screen.getByRole('button', { name: '账户菜单：焦点测试员' })
  fireEvent.click(account)
  const password = await screen.findByRole('menuitem', { name: /修改密码/ })
  // A menu item may be detached or hidden once the dialog opens. Its former
  // focus must not become the modal's final return target.
  password.focus()
  fireEvent.click(password)
  const dialog = await screen.findByRole('dialog', { name: '修改密码' })
  const currentPassword = within(dialog).getByPlaceholderText('当前密码')
  currentPassword.focus()
  expect(currentPassword).toHaveFocus()
  expect(account).toHaveAttribute('aria-expanded', 'false')

  if (closeAction === 'Escape') fireEvent.keyDown(dialog, { key: 'Escape', keyCode: 27 })
  else fireEvent.click(within(dialog).getByRole('button', { name: /取\s*消/ }))

  // jsdom has no CSS engine to dispatch the closing animation's end event.
  await waitFor(() => expect(dialog).toHaveClass('ant-zoom-leave-active'))
  fireEvent.animationEnd(dialog)
  fireEvent.transitionEnd(dialog)
  await waitFor(() => expect(dialog).not.toBeVisible())
  await waitFor(() => expect(account).toHaveFocus())
  expect(put).not.toHaveBeenCalled()
})
