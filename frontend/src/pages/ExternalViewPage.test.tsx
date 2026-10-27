import { beforeEach, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { StrictMode } from 'react'
const h = vi.hoisted(() => ({ bootstrap: vi.fn(), download: vi.fn() }))
vi.mock('../api/externalView', () => ({ externalViewApi: h }))
import ExternalViewPage from './ExternalViewPage'
const view = { share_id: 's', project_name: '仅外部项目', scopes: ['project_progress'], expires_at: '2099-01-01T00:00:00Z', project_progress: { status: 'executing', percent: 40, start_date: '2026-01-01', end_date: '2026-12-31' } }
beforeEach(() => {
  vi.resetAllMocks(); window.history.replaceState({}, '', '/external#token=one-time-secret')
  h.bootstrap.mockResolvedValue({ session_token: 'memory-only-session', session_expires_at: new Date(Date.now() + 60000).toISOString(), view })
})
it('strips fragments immediately, survives StrictMode and shows only granted content', async () => {
  const local = vi.spyOn(Storage.prototype, 'setItem')
  render(<StrictMode><ExternalViewPage /></StrictMode>)
  expect(await screen.findByText('仅外部项目')).toBeVisible()
  expect(window.location.hash).toBe('')
  expect(h.bootstrap).toHaveBeenCalledWith('one-time-secret', expect.any(AbortSignal))
  expect(screen.queryByText('已授权资料')).toBeNull()
  expect(screen.queryByText('车辆进度表')).toBeNull()
  expect(screen.queryByRole('button', { name: '编辑' })).toBeNull()
  expect(local).not.toHaveBeenCalled(); local.mockRestore()
})
it('discards previously displayed content after a revoked-link refresh', async () => {
  render(<ExternalViewPage />); await screen.findByText('仅外部项目')
  h.bootstrap.mockRejectedValueOnce(new Error('分享已被撤销'))
  fireEvent.click(screen.getByRole('button', { name: '刷新分享' }))
  expect(await screen.findByText('分享已被撤销')).toBeVisible()
  expect(screen.queryByText('仅外部项目')).toBeNull()
})
it('only renders a supplied latest file and discards the view if its ACL changes', async () => {
  h.bootstrap.mockResolvedValueOnce({ session_token: 'session', session_expires_at: new Date(Date.now() + 60000).toISOString(), view: { ...view, project_progress: undefined,
    documents: [{ id: 'd', code: '7.1', name: '交付原件', status: 'submitted', file: { version_id: 'v', filename: 'final.txt' } }] } })
  h.download.mockRejectedValueOnce(new Error('此资料未对当前分享开放'))
  render(<ExternalViewPage />)
  fireEvent.click(await screen.findByRole('button', { name: 'final.txt' }))
  await waitFor(() => expect(h.download).toHaveBeenCalledWith('session', expect.objectContaining({ id: 'd', file: expect.objectContaining({ version_id: 'v' }) })))
  expect(await screen.findByText('此资料未对当前分享开放')).toBeVisible()
  expect(screen.queryByText('交付原件')).toBeNull()
})
it('removes data when the short session expires', async () => {
  let resolve!: (value: unknown) => void
  h.bootstrap.mockReturnValueOnce(new Promise(r => { resolve = r }))
  render(<ExternalViewPage />)
  await act(async () => resolve({ session_token: 'session', session_expires_at: new Date(Date.now() + 100).toISOString(), view }))
  expect(screen.getByText('仅外部项目')).toBeVisible()
  expect(await screen.findByText('当前只读会话已到期，请刷新核对分享是否仍有效。')).toBeVisible()
  expect(screen.queryByText('仅外部项目')).toBeNull()
})
