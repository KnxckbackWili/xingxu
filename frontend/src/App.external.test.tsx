import { beforeEach, expect, it, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
const h = vi.hoisted(() => ({ fetchMe: vi.fn(), refreshPermissions: vi.fn(), user: null as { id: string; role: string } | null }))
vi.mock('./stores/auth', () => ({ useAuth: () => ({ user: h.user, loading: false, fetchMe: h.fetchMe, refreshPermissions: h.refreshPermissions }) }))
vi.mock('./api/client', async original => ({ ...await original<object>(), isAuthed: () => true }))
vi.mock('./pages/ExternalViewPage', () => ({ default: () => <div>专用外部只读页面</div> }))
vi.mock('./components/WorkDetailHost', () => ({ default: () => <div>内部工作抽屉</div> }))
import App from './App'
beforeEach(() => { vi.clearAllMocks(); h.user = null })
it.each([false, true])('external route ignores ambient business sessions (loaded=%s)', async loaded => {
  if (loaded) h.user = { id: 'internal-admin', role: 'admin' }
  render(<MemoryRouter initialEntries={['/external#token=not-a-business-session']}><App /></MemoryRouter>)
  expect(await screen.findByText('专用外部只读页面')).toBeVisible()
  expect(screen.queryByText('内部工作抽屉')).toBeNull()
  fireEvent.focus(window)
  expect(h.fetchMe).not.toHaveBeenCalled(); expect(h.refreshPermissions).not.toHaveBeenCalled()
})
