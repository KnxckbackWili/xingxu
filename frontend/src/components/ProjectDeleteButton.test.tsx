import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { ConfigProvider } from 'antd'
import type { ComponentProps } from 'react'
import type { PermissionUser } from '../constants/systemPermissions'
import ProjectDeleteButton from './ProjectDeleteButton'
import { projectApi } from '../api'
const auth: { user: PermissionUser | null } = vi.hoisted(() => ({ user: { id: 'pm1', role: 'pm' } }))
vi.mock('../stores/auth', () => ({ useAuth: () => auth }))
vi.mock('../api', () => ({ projectApi: { remove: vi.fn(), get: vi.fn() } }))
vi.mock('../api/client', () => ({ errMsg: (e: any) => e.response?.data?.detail ?? '暂时无法连接' }))
const project = { id: 'p1', name: '物流一期', manager: 'pm1', version: 3, capabilities: ['project.delete'], can_delete: true}
const receipt = { message: '已删除', project_id: 'p1', deletion_id: 'd1', version: 4, backup: { available: true, sha256: 'fixture', bytes: 90 } }
beforeEach(() => { vi.resetAllMocks(); auth.user = { id: 'pm1', role: 'pm' }; vi.mocked(projectApi.remove).mockResolvedValue(receipt) })
function show(p: ComponentProps<typeof ProjectDeleteButton>['project'] = project, onDeleted = vi.fn()) { render(<ConfigProvider theme={{ token: { motion: false } }}><ProjectDeleteButton project={p} onDeleted={onDeleted} /></ConfigProvider>); return onDeleted }
async function open() { fireEvent.click(screen.getByRole('button', { name: '删除项目：物流一期' })); await screen.findByRole('dialog', { name: '删除这个项目？' }) }
it('lets an authorized non-admin delete with one versioned confirmation and backup explanation', async () => {
 auth.user = { id: 'worker1', role: 'worker' }; const done = show(); await open()
 await waitFor(() => expect(screen.getByText(/备份失败时不会删除/)).toBeVisible()); expect(projectApi.remove).not.toHaveBeenCalled()
 fireEvent.click(screen.getByRole('button', { name: '备份并删除' }))
 await waitFor(() => expect(done).toHaveBeenCalledOnce()); expect(projectApi.remove).toHaveBeenCalledWith('p1', { version: 3 })
})
it('does not override a negative server metadata result with cached capabilities', () => { show({ ...project, can_delete: false }); expect(screen.queryByRole('button')).not.toBeInTheDocument() })
it.each(['project.delete', 'project.read'])('removes the entry after explicit %s denial', key => { auth.user = { id: 'admin', role: 'admin', permission_overrides: { [key]: false } }; show(); expect(screen.queryByRole('button')).not.toBeInTheDocument(); expect(projectApi.remove).not.toHaveBeenCalled() })
it('cancels without deleting or opening the surrounding card', async () => {
 const card = vi.fn(), done = vi.fn(); render(<ConfigProvider theme={{ token: { motion: false } }}><div onClick={card}><ProjectDeleteButton project={project} onDeleted={done} /></div></ConfigProvider>)
 await open(); fireEvent.click(screen.getByRole('button', { name: '保留项目' })); expect(projectApi.remove).not.toHaveBeenCalled(); expect(card).not.toHaveBeenCalled(); expect(done).not.toHaveBeenCalled()
})
it('retains backup-failure confirmation and serializes the retry', async () => {
 let resolve!: (value: typeof receipt) => void
 vi.mocked(projectApi.remove).mockRejectedValueOnce({ response: { status: 500, data: { detail: '删除前项目备份失败，项目未删除' } } }).mockImplementationOnce(() => new Promise(done => { resolve = done }))
 const done = show(); await open(); fireEvent.click(screen.getByRole('button', { name: '备份并删除' }))
 await screen.findByText('删除前项目备份失败，项目未删除'); expect(done).not.toHaveBeenCalled()
 const save = screen.getByRole('button', { name: '备份并删除' }); fireEvent.click(save); fireEvent.click(save)
 expect(projectApi.remove).toHaveBeenCalledTimes(2); expect(screen.getByRole('button', { name: '保留项目' })).toBeDisabled()
 await act(async () => resolve(receipt)); await waitFor(() => expect(done).toHaveBeenCalledOnce())
})
it('re-reads a conflicting version explicitly before another delete', async () => {
 vi.mocked(projectApi.remove).mockRejectedValueOnce({ response: { status: 409, data: { detail: '版本已变化' } } }).mockResolvedValueOnce(receipt); vi.mocked(projectApi.get).mockResolvedValue({ ...project, version: 7 })
 show(); await open(); fireEvent.click(screen.getByRole('button', { name: '备份并删除' })); await screen.findByText('项目已变化，请重新核对后确认')
 expect(screen.getByRole('button', { name: '备份并删除' })).toBeDisabled(); fireEvent.click(screen.getByRole('button', { name: '重新读取项目' }))
 await waitFor(() => expect(screen.getByRole('button', { name: '备份并删除' })).toBeEnabled()); fireEvent.click(screen.getByRole('button', { name: '备份并删除' }))
 await waitFor(() => expect(projectApi.remove).toHaveBeenLastCalledWith('p1', { version: 7 })); expect(projectApi.get).toHaveBeenCalledWith('p1', { signal: expect.any(AbortSignal) })
})
it('reads a real version rather than guessing when an old list omits it', async () => {
 vi.mocked(projectApi.get).mockResolvedValue({ ...project, version: 8 }); show({ ...project, version: undefined }); await open()
 await waitFor(() => expect(screen.getByRole('button', { name: '备份并删除' })).toBeEnabled()); expect(projectApi.remove).not.toHaveBeenCalled()
 fireEvent.click(screen.getByRole('button', { name: '备份并删除' })); await waitFor(() => expect(projectApi.remove).toHaveBeenCalledWith('p1', { version: 8 }))
})
it('ignores a late read after the parent revokes metadata or actor permissions change', async () => {
 let resolve!: (value: unknown) => void
 vi.mocked(projectApi.get).mockImplementation(() => new Promise(done => { resolve = done }))
 const done = vi.fn()
 const view = render(<ConfigProvider theme={{ token: { motion: false } }}><ProjectDeleteButton project={{ ...project, version: undefined }} onDeleted={done} /></ConfigProvider>)
 await open()
 auth.user = { id: 'pm1', role: 'pm', permission_version: 2 }
 view.rerender(<ConfigProvider theme={{ token: { motion: false } }}><ProjectDeleteButton project={{ ...project, version: 4, can_delete: false }} onDeleted={done} /></ConfigProvider>)
 await act(async () => resolve({ ...project, version: 9 }))
 expect(screen.queryByRole('button', { name: '删除项目：物流一期' })).not.toBeInTheDocument()
 expect(projectApi.remove).not.toHaveBeenCalled(); expect(done).not.toHaveBeenCalled()
})
it('never applies the previous project name or version to a newly rendered project', async () => {
 let resolve!: (value: unknown) => void
 vi.mocked(projectApi.get).mockImplementation(() => new Promise(done => { resolve = done }))
 const done = vi.fn(), next = { ...project, id: 'p2', name: '物流二期', version: 6 }
 const view = render(<ConfigProvider theme={{ token: { motion: false } }}><ProjectDeleteButton project={{ ...project, version: undefined }} onDeleted={done} /></ConfigProvider>)
 await open(); view.rerender(<ConfigProvider theme={{ token: { motion: false } }}><ProjectDeleteButton project={next} onDeleted={done} /></ConfigProvider>)
 await act(async () => resolve({ ...project, version: 9 }))
 fireEvent.click(screen.getByRole('button', { name: '删除项目：物流二期' }))
 const dialog = await screen.findByRole('dialog', { name: '删除这个项目？' })
 expect(within(dialog).getByRole('heading', { name: '物流二期' })).toBeInTheDocument()
 fireEvent.click(within(dialog).getByRole('button', { name: '备份并删除' }))
 await waitFor(() => expect(projectApi.remove).toHaveBeenCalledWith('p2', { version: 6 }))
})
it('does not invoke an old deletion callback after its confirmation is unmounted', async () => {
 let resolve!: (value: typeof receipt) => void
 vi.mocked(projectApi.remove).mockImplementation(() => new Promise(done => { resolve = done }))
 const done = vi.fn(), view = render(<ConfigProvider theme={{ token: { motion: false } }}><ProjectDeleteButton project={project} onDeleted={done} /></ConfigProvider>)
 await open(); fireEvent.click(screen.getByRole('button', { name: '备份并删除' })); view.unmount()
 await act(async () => resolve(receipt)); expect(done).not.toHaveBeenCalled()
})
