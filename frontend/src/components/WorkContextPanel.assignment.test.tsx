import { expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import WorkContextPanel from './WorkContextPanel'
vi.mock('../stores/auth', () => ({ useAuth: () => ({ user: { id: 'u', role: 'worker' } }) }))
it('keeps historical assignee names visible and links to weekly planning without a daily quantity editor', () => {
  render(<MemoryRouter><WorkContextPanel data={{ project: { id: 'p', name: '项目' }, task: { id: 't' }, entries: [{ id: 'e', work_date: '2026-10-05', assignee_name: '原负责人', is_confirmed: true }] }} onRefresh={async () => {}} /></MemoryRouter>)
  expect(screen.getByText(/原负责人/)).toBeVisible(); expect(screen.getByRole('link', { name: '查看周计划' })).toHaveAttribute('href', '/pm/projects/p/schedule'); expect(screen.queryByRole('spinbutton')).toBeNull(); expect(screen.queryByRole('button', { name: '调整安排' })).toBeNull()
})
