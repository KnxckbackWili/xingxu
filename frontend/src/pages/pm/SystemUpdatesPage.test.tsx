import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ConfigProvider } from 'antd'
import { StrictMode } from 'react'
import type { SystemUpdates } from '../../api/systemUpdates'

const auth = vi.hoisted(() => ({ user: { id: 'admin-a', role: 'admin', is_active: true } }))
vi.mock('../../stores/auth', () => ({ useAuth: () => auth }))
vi.mock('../../api/client', () => ({
  api: { get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() },
  errMsg: (error: any) => error?.response?.data?.detail || '网络暂时不可用',
}))
vi.mock('../../offline/queue', () => ({ getOfflineAccount: vi.fn(() => 'admin-a') }))
import { api } from '../../api/client'
import { getOfflineAccount } from '../../offline/queue'
import { APP_VERSION } from '../../version'
import SystemUpdatesPage from './SystemUpdatesPage'

const defaultSource = { id: 'default-gitea', name: '我的 Gitea', is_default: true, repository_url: 'https://git.example.com/team/workflow', ref: 'main', has_token: false, allow_http: false, revision: 1 }
const initial: SystemUpdates = {
  current: { version: '2.3.8', commit: 'a'.repeat(40) },
  source: defaultSource, sources: [defaultSource], active_source_id: 'default-gitea',
  runner: { online: false, last_seen: null, protocol: 1, trust: { configured: true, protocol: 1 } }, check: null, job: null,
}
const checked: SystemUpdates = { ...initial, check: { id: 'check-1', source_revision: 1, version: '2.4.0', commit: 'b'.repeat(40), checked_at: '2026-10-19T10:00:00Z', update_available: true, trust: { status: 'trusted', method: 'commit', message: '此仓库提交已由宿主登记。' } } }
const renderPage = () => render(<ConfigProvider theme={{ token: { motion: false } }}><SystemUpdatesPage /></ConfigProvider>)
const findCurrentVersion = () => screen.findByText('2.3.8', { selector: 'strong' })
function openSourceSettings() {
  const summary = screen.getByLabelText('更新来源')
  if (!summary.closest('details')?.open) fireEvent.click(summary)
}
function openAdvancedSources() {
  openSourceSettings()
  const summary = screen.getByLabelText('高级来源管理')
  if (!summary.closest('details')?.open) fireEvent.click(summary)
}
const online = { ...checked, runner: { ...checked.runner, online: true } }
const running = { ...online, job: { id: 'job-1', status: 'installing', phase: 'installing', message: '正在安装新版本', target_version: '2.4.0', target_commit: 'b'.repeat(40), created_at: '2026-10-19T10:00:00Z', updated_at: '2026-10-19T10:01:00Z' } }
async function poll() {
  const callback = vi.mocked(window.setInterval).mock.calls.find(([, delay]) => delay === 6000)?.[0]
  if (typeof callback !== 'function') throw new Error('Missing update polling interval')
  await act(async () => { callback() })
}
beforeEach(() => {
  vi.resetAllMocks()
  auth.user = { id: 'admin-a', role: 'admin', is_active: true }
  vi.mocked(getOfflineAccount).mockReturnValue('admin-a')
  vi.mocked(api.get).mockResolvedValue({ data: initial })
  vi.spyOn(window, 'setInterval')
})
afterEach(() => vi.restoreAllMocks())

it('starts with focused update actions and lets administrators reveal source and build details', async () => {
  renderPage(); await findCurrentVersion()
  expect(screen.getByRole('heading', { name: '让行序保持最新' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '检查更新' })).toBeEnabled()
  expect(screen.queryByRole('button', { name: '安装更新' })).not.toBeInTheDocument()
  expect(screen.getByLabelText('更新来源').closest('details')).not.toHaveAttribute('open')
  expect(screen.getByLabelText('Gitea 仓库完整地址')).not.toBeVisible()
  expect(screen.getByLabelText('版本详情').closest('details')).not.toHaveAttribute('open')
  expect(screen.getByText(initial.current.commit)).not.toBeVisible()
  fireEvent.click(screen.getByLabelText('版本详情'))
  expect(screen.getByText(initial.current.commit)).toBeVisible()
  openSourceSettings()
  expect(screen.getByLabelText('Gitea 仓库完整地址')).toBeVisible()
  expect(screen.getByLabelText('高级来源管理').closest('details')).not.toHaveAttribute('open')
  expect(screen.getByLabelText('当前更新来源')).not.toBeVisible()
  expect(screen.getByRole('button', { name: '添加来源' })).not.toBeVisible()
  expect(api.put).not.toHaveBeenCalled()
  expect(api.post).not.toHaveBeenCalled()
})

it('shows the latest-version result without offering an installation that cannot run', async () => {
  vi.mocked(api.get).mockResolvedValue({ data: { ...online, check: { ...online.check!, version: initial.current.version, commit: initial.current.commit, update_available: false } } })
  renderPage(); await findCurrentVersion()
  expect(screen.getByRole('heading', { name: '你的行序已是最新版本' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '检查更新' })).toBeEnabled()
  expect(screen.queryByRole('button', { name: '安装更新' })).not.toBeInTheDocument()
  expect(screen.getByLabelText('更新来源').closest('details')).not.toHaveAttribute('open')
})

it('describes an older source as having no available update without claiming its build is current', async () => {
  vi.mocked(api.get).mockResolvedValue({ data: { ...online, check: { ...online.check!, version: '2.3.7', commit: 'c'.repeat(40), update_available: false } } })
  renderPage(); await findCurrentVersion()
  expect(screen.getByRole('heading', { name: '暂无可用更新' })).toBeInTheDocument()
  expect(screen.getByText('所选来源没有比当前版本更新的版本。')).toBeVisible()
  expect(screen.queryByText('你的行序已是最新版本')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: '检查更新' })).toBeEnabled()
  expect(screen.queryByRole('button', { name: '安装更新' })).not.toBeInTheDocument()
})

it.each([
  { status: 'failed', title: '更新未完成' },
  { status: 'rolled_back', title: '已恢复更新前版本' },
])('retains the $status outcome until a fresh check permits another installation', async ({ status, title }) => {
  const completed = { ...running, job: { ...running.job, status, message: '上次更新已停止。' } }
  vi.mocked(api.get).mockResolvedValue({ data: completed })
  vi.mocked(api.post).mockResolvedValue({ data: { ...completed, check: { ...checked.check!, id: 'fresh-check', checked_at: '2026-10-19T10:05:00Z' } } })
  renderPage(); await findCurrentVersion()
  expect(screen.getByRole('heading', { name: title })).toBeInTheDocument()
  expect(screen.getByText('请重新检查版本，再尝试安装。')).toBeVisible()
  expect(screen.queryByRole('heading', { name: '有新版本可用' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: '检查更新' })).toBeEnabled()
  expect(screen.getByRole('button', { name: '安装更新' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: '检查更新' }))
  await screen.findByRole('heading', { name: '有新版本可用' })
  expect(screen.getByRole('button', { name: '安装更新' })).toBeEnabled()
  expect(api.post).toHaveBeenCalledWith('/system/updates/check', { source_revision: 1 })
})

it('preserves an unsaved source while its settings are collapsed and refreshed', async () => {
  vi.mocked(api.get).mockResolvedValue({ data: online })
  renderPage(); await findCurrentVersion(); openSourceSettings()
  fireEvent.change(screen.getByLabelText('分支或标签'), { target: { value: 'draft-release' } })
  fireEvent.change(screen.getByLabelText('私有访问令牌'), { target: { value: 'collapsed-source-token' } })
  fireEvent.click(screen.getByLabelText('更新来源'))
  expect(screen.getByText('有未保存的修改')).toBeVisible()
  expect(screen.getByLabelText('分支或标签')).not.toBeVisible()
  expect(screen.getByRole('button', { name: '检查更新' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '安装更新' })).toBeDisabled()
  await poll()
  expect(screen.getByLabelText('更新来源').closest('details')).not.toHaveAttribute('open')
  openSourceSettings()
  expect(screen.getByLabelText('分支或标签')).toHaveValue('draft-release')
  expect(screen.getByLabelText('私有访问令牌')).toHaveValue('collapsed-source-token')
  expect(api.put).not.toHaveBeenCalled()
  expect(api.post).not.toHaveBeenCalled()
})

it.each([true, false])('makes manual recovery visible and keeps changes locked when runner online is %s', async runnerOnline => {
  vi.mocked(api.get).mockResolvedValue({ data: { ...selected(), runner: { ...online.runner, online: runnerOnline }, job: { ...running.job, status: 'needs_attention', phase: 'needs_attention', message: '回滚校验未通过，请先恢复服务。' } } })
  renderPage(); await findCurrentVersion()
  expect(screen.getByRole('heading', { name: '更新需要处理' })).toBeInTheDocument()
  expect(screen.getByText('更新需要人工处理')).toBeVisible()
  expect(screen.getByText('回滚校验未通过，请先恢复服务。')).toBeVisible()
  if (!runnerOnline) {
    expect(screen.getByText('恢复处理尚未完成')).toBeVisible()
    expect(screen.getByText('需要部署管理员检查备份和日志，完成恢复后再继续。')).toBeVisible()
    expect(screen.queryByText('更新中，等待服务恢复')).not.toBeInTheDocument()
  }
  expect(screen.getByRole('button', { name: '检查更新' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '安装更新' })).toBeDisabled()
  openSourceSettings()
  expect(screen.getByRole('combobox', { name: '当前更新来源' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '添加来源' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '删除来源' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '保存并检查更新' })).toBeDisabled()
  expect(api.post).not.toHaveBeenCalled()
})

it('preserves dirty source and token during polling and requires checking the saved configuration', async () => {
  vi.mocked(api.get).mockResolvedValueOnce({ data: online }).mockResolvedValue({ data: { ...online, source: { ...initial.source, ref: 'other-admin', revision: 3 } } })
  renderPage()
  await findCurrentVersion(); openSourceSettings()
  fireEvent.change(screen.getByLabelText('分支或标签'), { target: { value: 'my-release' } })
  fireEvent.change(screen.getByLabelText('私有访问令牌'), { target: { value: 'unsaved-secret' } })
  await poll()
  expect(screen.getByLabelText('分支或标签')).toHaveValue('my-release')
  expect(screen.getByLabelText('私有访问令牌')).toHaveValue('unsaved-secret')
  expect(screen.getByRole('button', { name: '检查更新' })).toBeDisabled()
  expect(screen.queryByRole('button', { name: '安装更新' })).not.toBeInTheDocument()
  expect(screen.getByText('来源已被其他管理员修改')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '放弃修改并载入最新配置' }))
  expect(screen.getByLabelText('分支或标签')).toHaveValue('other-admin')
  expect(screen.getByLabelText('私有访问令牌')).toHaveValue('')
  expect(screen.queryByRole('button', { name: '安装更新' })).not.toBeInTheDocument()
  expect(api.put).not.toHaveBeenCalled()
})

it('clears a saved token explicitly, defaults an empty ref to main and locks duplicate saves', async () => {
  vi.mocked(api.get).mockResolvedValue({ data: { ...initial, source: { ...initial.source, has_token: true } } })
  let resolveSave!: (value: unknown) => void
  vi.mocked(api.put).mockImplementation(() => new Promise(resolve => { resolveSave = resolve }))
  vi.mocked(api.post).mockResolvedValue({ data: { ...initial, source: { ...initial.source, revision: 2 } } })
  renderPage()
  await findCurrentVersion(); openSourceSettings()
  expect(screen.getByText('已保存访问令牌')).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('分支或标签'), { target: { value: '' } })
  fireEvent.click(screen.getByRole('checkbox', { name: '清除已保存的令牌' }))
  const save = screen.getByRole('button', { name: '保存并检查更新' })
  fireEvent.click(save); fireEvent.click(save)
  expect(api.put).toHaveBeenCalledTimes(1)
  expect(api.put).toHaveBeenCalledWith('/system/updates/source', { name: '我的 Gitea', repository_url: initial.source.repository_url, ref: 'main', allow_http: false, revision: 1, clear_token: true })
  expect(screen.getByLabelText('Gitea 仓库完整地址')).toBeDisabled()
  await act(async () => resolveSave({ data: { ...initial, source: { ...initial.source, revision: 2 } } }))
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1))
  expect(screen.getByLabelText('私有访问令牌')).toHaveValue('')
})

it('requires explicit HTTP permission before saving a LAN source', async () => {
  renderPage()
  await findCurrentVersion(); openSourceSettings()
  fireEvent.change(screen.getByLabelText('Gitea 仓库完整地址'), { target: { value: 'http://nas.local/team/workflow' } })
  fireEvent.click(screen.getByRole('button', { name: '保存并检查更新' }))
  expect(screen.getByText('使用局域网 HTTP 地址前，请勾选明确允许。')).toBeInTheDocument()
  expect(api.put).not.toHaveBeenCalled()
})

it('does not let an earlier polling response overwrite a successful source save and check', async () => {
  let resolvePoll!: (value: unknown) => void
  vi.mocked(api.get).mockResolvedValueOnce({ data: initial }).mockImplementationOnce(() => new Promise(resolve => { resolvePoll = resolve }))
  const saved = { ...online, source: { ...online.source, ref: 'release', revision: 2 }, check: { ...online.check!, source_revision: 2 } }
  vi.mocked(api.put).mockResolvedValue({ data: saved })
  vi.mocked(api.post).mockResolvedValue({ data: saved })
  renderPage(); await findCurrentVersion(); openSourceSettings()
  await poll()
  fireEvent.change(screen.getByLabelText('分支或标签'), { target: { value: 'release' } })
  fireEvent.click(screen.getByRole('button', { name: '保存并检查更新' }))
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/system/updates/check', { source_revision: 2 }))
  await act(async () => resolvePoll({ data: initial }))
  expect(screen.getByLabelText('分支或标签')).toHaveValue('release')
  expect(screen.getByRole('button', { name: '安装更新' })).toBeEnabled()
})

it('confirms backup and downtime before installing once, then waits through disconnection without a false failure', async () => {
  vi.mocked(api.get).mockResolvedValue({ data: online })
  let resolveInstall!: (value: unknown) => void
  vi.mocked(api.post).mockImplementation(() => new Promise(resolve => { resolveInstall = resolve }))
  renderPage(); await findCurrentVersion(); openSourceSettings()
  fireEvent.click(screen.getByRole('button', { name: '安装更新' }))
  const dialog = within(screen.getByRole('dialog'))
  expect(dialog.getByText(/系统会先自动备份，安装期间网页会短暂不可用/)).toBeInTheDocument()
  const confirm = dialog.getByRole('button', { name: '自动备份并安装' })
  fireEvent.click(confirm); fireEvent.click(confirm)
  expect(api.post).toHaveBeenCalledTimes(1)
  expect(api.post).toHaveBeenCalledWith('/system/updates/install', { check_id: 'check-1', confirm: true })
  await act(async () => resolveInstall({ data: running }))
  expect(screen.getByLabelText('分支或标签')).toBeDisabled()
  vi.mocked(api.get).mockRejectedValueOnce(new Error('restarting'))
  await poll()
  expect(screen.getByText('更新中，等待服务恢复')).toBeInTheDocument()
  expect(screen.getByText('正在安装新版本')).toBeInTheDocument()
  expect(screen.queryByText('更新未完成')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: '安装更新' })).toBeDisabled()
  vi.mocked(api.get).mockResolvedValue({ data: { ...running, current: { ...running.current, version: '2.4.0' }, job: { ...running.job, status: 'succeeded', message: '更新验证通过' } } })
  await poll()
  expect(screen.getByRole('button', { name: '刷新页面使用新版本' })).toBeEnabled()
})

it('does not ask an already-current frontend to reload for a historical successful update', async () => {
  const version = APP_VERSION.replace(/^v/, '')
  vi.mocked(api.get).mockResolvedValue({ data: { ...running, current: { version, commit: running.job.target_commit }, job: { ...running.job, status: 'succeeded', message: '更新验证通过' } } })
  renderPage()
  await screen.findByRole('heading', { name: '更新已完成' })
  expect(screen.queryByText('新版本已安装，刷新页面后即可使用。')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '刷新页面使用新版本' })).not.toBeInTheDocument()
  await poll()
  expect(screen.queryByRole('button', { name: '刷新页面使用新版本' })).not.toBeInTheDocument()
})

it('offers a reload after observing a running job finish even when the version number stays the same', async () => {
  const version = APP_VERSION.replace(/^v/, '')
  const active = { ...running, current: { ...running.current, version }, job: { ...running.job, target_version: version } }
  vi.mocked(api.get).mockResolvedValue({ data: active })
  renderPage()
  await screen.findByText('正在安装新版本')
  expect(screen.queryByRole('button', { name: '刷新页面使用新版本' })).not.toBeInTheDocument()
  vi.mocked(api.get).mockResolvedValue({ data: { ...active, current: { version, commit: active.job.target_commit }, job: { ...active.job, status: 'succeeded', message: '更新验证通过' } } })
  await poll()
  expect(screen.getByRole('button', { name: '刷新页面使用新版本' })).toBeEnabled()
})

it('offers a reload for an already-completed update when the frontend version differs from the server', async () => {
  vi.mocked(api.get).mockResolvedValue({ data: { ...running, current: { version: '9.9.9', commit: running.job.target_commit }, job: { ...running.job, target_version: '9.9.9', status: 'succeeded', message: '更新验证通过' } } })
  renderPage()
  await screen.findByRole('heading', { name: '更新已完成' })
  expect(screen.getByRole('button', { name: '刷新页面使用新版本' })).toBeEnabled()
})

it('keeps an uncertain install locked while polling until its new job is observed', async () => {
  vi.mocked(api.get).mockResolvedValue({ data: online })
  vi.mocked(api.post).mockRejectedValue(new Error('lost install response'))
  renderPage(); await findCurrentVersion(); openSourceSettings()
  fireEvent.click(screen.getByRole('button', { name: '安装更新' }))
  fireEvent.click(screen.getByRole('button', { name: '自动备份并安装' }))
  await screen.findByText('更新中，等待服务恢复')
  await poll()
  expect(screen.getByRole('button', { name: '安装更新' })).toBeDisabled()
  expect(screen.getByLabelText('Gitea 仓库完整地址')).toBeDisabled()
  vi.mocked(api.get).mockResolvedValue({ data: running })
  await poll()
  expect(screen.getByText('正在安装新版本')).toBeInTheDocument()
  expect(api.post).toHaveBeenCalledTimes(1)
})

it('invalidates an open confirmation when polling replaces the checked target', async () => {
  vi.mocked(api.get).mockResolvedValueOnce({ data: online }).mockResolvedValue({ data: { ...online, check: { ...online.check!, id: 'check-new', commit: 'c'.repeat(40) } } })
  renderPage(); await findCurrentVersion(); openSourceSettings()
  fireEvent.click(screen.getByRole('button', { name: '安装更新' }))
  await poll()
  expect(screen.getByRole('button', { name: '自动备份并安装' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: '自动备份并安装' }))
  expect(api.post).not.toHaveBeenCalled()
})

it('discards a previous account callback without issuing its follow-up check or exposing its token', async () => {
  let resolveSave!: (value: unknown) => void
  vi.mocked(api.put).mockImplementation(() => new Promise(resolve => { resolveSave = resolve }))
  const view = renderPage(); await findCurrentVersion(); openSourceSettings()
  fireEvent.change(screen.getByLabelText('私有访问令牌'), { target: { value: 'account-a-secret' } })
  fireEvent.click(screen.getByRole('button', { name: '保存并检查更新' }))
  auth.user = { id: 'admin-b', role: 'admin', is_active: true }
  vi.mocked(getOfflineAccount).mockReturnValue('admin-b')
  vi.mocked(api.get).mockResolvedValue({ data: { ...initial, source: { ...initial.source, ref: 'account-b' } } })
  view.rerender(<ConfigProvider><SystemUpdatesPage /></ConfigProvider>)
  await waitFor(() => expect(screen.getByLabelText('分支或标签')).toHaveValue('account-b'))
  openSourceSettings()
  await act(async () => resolveSave({ data: { ...initial, source: { ...initial.source, has_token: true, revision: 2 } } }))
  expect(screen.getByLabelText('私有访问令牌')).toHaveValue('')
  expect(screen.getByLabelText('分支或标签')).toHaveValue('account-b')
  expect(api.post).not.toHaveBeenCalled()
})

it('blocks a stale cross-tab login before any source write or installation', async () => {
  vi.mocked(api.get).mockResolvedValue({ data: online })
  renderPage(); await findCurrentVersion(); openSourceSettings()
  vi.mocked(getOfflineAccount).mockReturnValue(null)
  fireEvent.click(screen.getByRole('button', { name: '保存并检查更新' }))
  expect(api.put).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '安装更新' }))
  fireEvent.click(screen.getByRole('button', { name: '自动备份并安装' }))
  expect(api.post).not.toHaveBeenCalled()
  expect(screen.getByText('当前登录状态已变化，请重新验证登录后操作。')).toBeInTheDocument()
})

it.each([{ role: 'pm', is_active: true }, { role: 'admin', is_active: false }])('rejects a non-admin or disabled account before fetching update information: %o', async user => {
  auth.user = { id: 'blocked', ...user }
  renderPage()
  expect(screen.getByText('仅系统管理员可以管理软件更新')).toBeInTheDocument()
  expect(api.get).not.toHaveBeenCalled()
})

it('shows a recoverable initial read error and keeps a failed source draft intact', async () => {
  vi.mocked(api.get).mockRejectedValueOnce({ response: { data: { detail: '更新信息读取失败' } } }).mockResolvedValue({ data: initial })
  vi.mocked(api.put).mockRejectedValue({ response: { data: { detail: '配置已变化，请刷新后重试' } } })
  renderPage()
  await screen.findByText('更新信息暂时无法读取')
  fireEvent.click(screen.getByRole('button', { name: /重\s*试/ }))
  await findCurrentVersion(); openSourceSettings()
  fireEvent.change(screen.getByLabelText('分支或标签'), { target: { value: 'keep-my-draft' } })
  fireEvent.click(screen.getByRole('button', { name: '保存并检查更新' }))
  await screen.findByText('配置已变化，请刷新后重试')
  expect(screen.getByLabelText('分支或标签')).toHaveValue('keep-my-draft')
  expect(api.post).not.toHaveBeenCalled()
})

it('disables installation of an old result after a failed fresh update check', async () => {
  vi.mocked(api.get).mockResolvedValue({ data: online })
  vi.mocked(api.post).mockRejectedValue({ response: { data: { detail: '仓库暂时无法连接' } } })
  renderPage(); await findCurrentVersion(); openSourceSettings()
  fireEvent.click(screen.getByRole('button', { name: '检查更新' }))
  await screen.findByText('仓库暂时无法连接')
  expect(screen.getByRole('button', { name: '安装更新' })).toBeDisabled()
})

it('shows waiting for recovery when the runner disconnects during an active job', async () => {
  vi.mocked(api.get).mockResolvedValue({ data: { ...running, runner: { ...running.runner, online: false } } })
  renderPage()
  expect(await screen.findByText('更新中，等待服务恢复')).toBeInTheDocument()
  openSourceSettings()
  expect(screen.getByRole('button', { name: '安装更新' })).toBeDisabled()
  expect(screen.getByLabelText('分支或标签')).toBeDisabled()
})

it('requires a new check after a completed attempt instead of resubmitting its old check id', async () => {
  const failed = { ...running, job: { ...running.job, status: 'failed', message: '下载未完成' } }
  vi.mocked(api.get).mockResolvedValue({ data: failed })
  vi.mocked(api.post).mockResolvedValue({ data: { ...failed, check: { ...checked.check!, id: 'fresh-check', checked_at: '2026-10-19T10:05:00Z' } } })
  renderPage(); await findCurrentVersion(); openSourceSettings()
  expect(screen.getByRole('button', { name: '安装更新' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: '检查更新' }))
  await waitFor(() => expect(screen.getByRole('button', { name: '安装更新' })).toBeEnabled())
})

it('loads normally when React replays effect setup while the first read is still pending', async () => {
  vi.mocked(api.get).mockImplementationOnce(() => new Promise(() => {})).mockResolvedValue({ data: initial })
  render(<StrictMode><SystemUpdatesPage /></StrictMode>)
  expect(await findCurrentVersion()).toBeInTheDocument(); openSourceSettings()
})

it('saves a Gitea source and checks its saved revision while an unconnected runner keeps installation disabled', async () => {
  const saved = { ...initial, source: { ...initial.source, repository_url: 'http://nas.local/team/workflow', revision: 2, has_token: true, allow_http: true } }
  vi.mocked(api.put).mockResolvedValue({ data: saved })
  vi.mocked(api.post).mockResolvedValue({ data: { ...saved, check: { ...checked.check!, source_revision: 2 } } })
  renderPage()
  expect(await findCurrentVersion()).toBeInTheDocument(); openSourceSettings()
  expect(screen.getByText('更新服务未连接')).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Gitea 仓库完整地址'), { target: { value: 'http://nas.local/team/workflow' } })
  fireEvent.change(screen.getByLabelText('私有访问令牌'), { target: { value: 'private-token-for-test' } })
  fireEvent.click(screen.getByRole('checkbox', { name: '允许局域网 HTTP 地址' }))
  fireEvent.click(screen.getByRole('button', { name: '保存并检查更新' }))
  await waitFor(() => expect(api.put).toHaveBeenCalledWith('/system/updates/source', {
    name: '我的 Gitea', repository_url: 'http://nas.local/team/workflow', ref: 'main', revision: 1, allow_http: true, token: 'private-token-for-test',
  }))
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/system/updates/check', { source_revision: 2 }))
  expect(screen.getByLabelText('私有访问令牌')).toHaveValue('')
  expect(screen.getByText('已保存访问令牌')).toBeInTheDocument()
  expect(await screen.findByText('行序 2.4.0 已准备好，安装前会自动备份。')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '安装更新' })).toBeDisabled()
})

const secondarySource = { ...defaultSource, id: 'secondary-gitea', name: '备用 Gitea', is_default: false, repository_url: 'https://backup.example.com/team/workflow', has_token: true }
const multiple = { ...initial, sources: [defaultSource, secondarySource] }
const selected = (id = secondarySource.id, revision = 2): SystemUpdates => {
  const sources = multiple.sources.map(source => ({ ...source, revision }))
  return { ...multiple, sources, source: sources.find(source => source.id === id)!, active_source_id: id, check: null }
}
function fillNewSource() {
  fireEvent.change(screen.getByLabelText('新来源名称'), { target: { value: '备用 Gitea' } })
  fireEvent.change(screen.getByLabelText('新来源仓库地址'), { target: { value: secondarySource.repository_url } })
  fireEvent.change(screen.getByLabelText('新来源访问令牌'), { target: { value: 'new-source-only-token' } })
}

it('preselects the supplied default Gitea without making a check or offering to delete it', async () => {
  renderPage(); await findCurrentVersion(); openAdvancedSources()
  expect(screen.getByRole('combobox', { name: '当前更新来源' })).toHaveValue('default-gitea')
  expect(screen.getByRole('option', { name: '我的 Gitea（默认）' })).toBeInTheDocument()
  expect(screen.getByLabelText('Gitea 仓库完整地址')).toHaveValue(defaultSource.repository_url)
  expect(screen.queryByRole('button', { name: '删除来源' })).not.toBeInTheDocument()
  expect(api.post).not.toHaveBeenCalled()
})

it('adds and activates a separate source, retains the default and clears its draft token', async () => {
  let resolveAdd!: (value: unknown) => void
  vi.mocked(api.post).mockImplementationOnce(() => new Promise(resolve => { resolveAdd = resolve }))
  renderPage(); await findCurrentVersion(); openAdvancedSources()
  fireEvent.click(screen.getByRole('button', { name: '添加来源' }))
  fillNewSource()
  const submit = screen.getByRole('button', { name: '添加并使用' })
  fireEvent.click(submit); fireEvent.click(submit)
  expect(api.post).toHaveBeenCalledTimes(1)
  expect(api.post).toHaveBeenCalledWith('/system/updates/sources', { name: '备用 Gitea', repository_url: secondarySource.repository_url, ref: 'main', allow_http: false, revision: 1, token: 'new-source-only-token' })
  expect(screen.getByRole('combobox', { name: '当前更新来源' })).toBeDisabled()
  expect(screen.getByLabelText('新来源访问令牌')).toBeDisabled()
  await act(async () => resolveAdd({ data: selected() }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(screen.getByRole('combobox', { name: '当前更新来源' })).toHaveValue('secondary-gitea')
  expect(screen.getByRole('option', { name: '我的 Gitea（默认）' })).toBeInTheDocument()
  expect(screen.getByLabelText('私有访问令牌')).toHaveValue('')
  expect(screen.getByText('已添加并切换至「备用 Gitea」，请检查版本。')).toBeInTheDocument()
  expect(api.post).toHaveBeenCalledTimes(1)
})

it('requires explicit discard before switching sources and never transfers an unsaved token', async () => {
  vi.mocked(api.get).mockResolvedValue({ data: multiple })
  vi.mocked(api.post).mockResolvedValue({ data: selected() })
  renderPage(); await findCurrentVersion(); openAdvancedSources()
  fireEvent.change(screen.getByLabelText('私有访问令牌'), { target: { value: 'default-source-only-token' } })
  fireEvent.change(screen.getByRole('combobox', { name: '当前更新来源' }), { target: { value: secondarySource.id } })
  expect(screen.getByRole('dialog')).toHaveTextContent('放弃未保存的修改？')
  fireEvent.click(screen.getByRole('button', { name: '保留并返回' }))
  expect(screen.getByLabelText('私有访问令牌')).toHaveValue('default-source-only-token')
  expect(screen.getByRole('combobox', { name: '当前更新来源' })).toHaveValue(defaultSource.id)
  expect(api.post).not.toHaveBeenCalled()
  fireEvent.change(screen.getByRole('combobox', { name: '当前更新来源' }), { target: { value: secondarySource.id } })
  fireEvent.click(screen.getByRole('button', { name: '放弃修改并切换' }))
  await waitFor(() => expect(screen.getByRole('combobox', { name: '当前更新来源' })).toHaveValue(secondarySource.id))
  expect(api.post).toHaveBeenCalledWith('/system/updates/sources/secondary-gitea/select', { revision: 1 })
  expect(screen.getByLabelText('私有访问令牌')).toHaveValue('')
  expect(screen.getByText('已切换至「备用 Gitea」，请重新检查版本。')).toBeInTheDocument()
})

it('confirms deletion of a custom source and returns to the retained default', async () => {
  vi.mocked(api.get).mockResolvedValue({ data: selected() })
  vi.mocked(api.delete).mockResolvedValue({ data: { ...selected(defaultSource.id, 3), sources: [{ ...defaultSource, revision: 3 }] } })
  renderPage(); await findCurrentVersion(); openAdvancedSources()
  fireEvent.click(screen.getByRole('button', { name: '删除来源' }))
  expect(screen.getByRole('dialog')).toHaveTextContent('及其已保存的访问令牌')
  fireEvent.click(screen.getByRole('button', { name: '保留并返回' }))
  expect(api.delete).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '删除来源' }))
  fireEvent.click(screen.getByRole('button', { name: '删除并返回默认来源' }))
  await waitFor(() => expect(screen.getByRole('combobox', { name: '当前更新来源' })).toHaveValue(defaultSource.id))
  expect(api.delete).toHaveBeenCalledWith('/system/updates/sources/secondary-gitea', { params: { revision: 2 } })
  expect(screen.queryByRole('option', { name: secondarySource.name })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '删除来源' })).not.toBeInTheDocument()
})

it('ignores a polling response that arrives after a source switch', async () => {
  let resolvePoll!: (value: unknown) => void
  vi.mocked(api.get).mockResolvedValueOnce({ data: multiple }).mockImplementationOnce(() => new Promise(resolve => { resolvePoll = resolve }))
  vi.mocked(api.post).mockResolvedValue({ data: selected() })
  renderPage(); await findCurrentVersion(); openAdvancedSources(); await poll()
  fireEvent.change(screen.getByRole('combobox', { name: '当前更新来源' }), { target: { value: secondarySource.id } })
  await screen.findByText('已切换至「备用 Gitea」，请重新检查版本。')
  await act(async () => resolvePoll({ data: multiple }))
  expect(screen.getByRole('combobox', { name: '当前更新来源' })).toHaveValue(secondarySource.id)
  expect(screen.getByLabelText('Gitea 仓库完整地址')).toHaveValue(secondarySource.repository_url)
})

it('preserves the new-source draft during concurrent refresh and requires acknowledging its latest revision', async () => {
  vi.mocked(api.get).mockResolvedValueOnce({ data: initial }).mockResolvedValue({ data: selected() })
  vi.mocked(api.post).mockResolvedValue({ data: selected(secondarySource.id, 3) })
  renderPage(); await findCurrentVersion(); openAdvancedSources()
  fireEvent.click(screen.getByRole('button', { name: '添加来源' })); fillNewSource()
  await poll()
  expect(screen.getByLabelText('新来源访问令牌')).toHaveValue('new-source-only-token')
  expect(screen.getByLabelText('新来源仓库地址')).toHaveValue(secondarySource.repository_url)
  expect(screen.getByRole('button', { name: '添加并使用' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: '保留填写并采用最新列表' }))
  fireEvent.click(screen.getByRole('button', { name: '添加并使用' }))
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/system/updates/sources', expect.objectContaining({ revision: 2, token: 'new-source-only-token' })))
})

it('keeps an old source draft separate after another administrator changes the active source', async () => {
  vi.mocked(api.get).mockResolvedValueOnce({ data: multiple }).mockResolvedValue({ data: selected() })
  renderPage(); await findCurrentVersion(); openAdvancedSources()
  fireEvent.change(screen.getByLabelText('私有访问令牌'), { target: { value: 'old-source-token' } })
  await poll()
  expect(screen.getByRole('combobox', { name: '当前更新来源' })).toHaveValue(secondarySource.id)
  expect(screen.getByLabelText('Gitea 仓库完整地址')).toHaveValue(defaultSource.repository_url)
  expect(screen.getByLabelText('私有访问令牌')).toHaveValue('old-source-token')
  expect(screen.getByRole('button', { name: '保存并检查更新' })).toBeDisabled()
  expect(screen.getByText(/你的填写仍属于「我的 Gitea」/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '放弃修改并载入最新配置' }))
  expect(screen.getByLabelText('私有访问令牌')).toHaveValue('')
  expect(screen.getByLabelText('Gitea 仓库完整地址')).toHaveValue(secondarySource.repository_url)
  expect(api.put).not.toHaveBeenCalled()
})

it.each(['installing', 'maintenance'])('locks selection, creation and deletion during %s', async mode => {
  vi.mocked(api.get).mockResolvedValue({ data: { ...selected(), ...(mode === 'maintenance' ? { maintenance: true } : { job: running.job }) } })
  renderPage(); await findCurrentVersion(); openAdvancedSources()
  expect(screen.getByRole('combobox', { name: '当前更新来源' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '添加来源' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '删除来源' })).toBeDisabled()
  expect(screen.getByLabelText('私有访问令牌')).toBeDisabled()
  expect(api.post).not.toHaveBeenCalled()
})

it('drops a pending add response and its token when the signed-in administrator changes', async () => {
  let resolveAdd!: (value: unknown) => void
  vi.mocked(api.post).mockImplementationOnce(() => new Promise(resolve => { resolveAdd = resolve }))
  const view = renderPage(); await findCurrentVersion(); openAdvancedSources()
  fireEvent.click(screen.getByRole('button', { name: '添加来源' })); fillNewSource()
  fireEvent.click(screen.getByRole('button', { name: '添加并使用' }))
  auth.user = { id: 'admin-b', role: 'admin', is_active: true }
  vi.mocked(getOfflineAccount).mockReturnValue('admin-b')
  view.rerender(<ConfigProvider><SystemUpdatesPage /></ConfigProvider>)
  await findCurrentVersion(); openAdvancedSources()
  await act(async () => resolveAdd({ data: selected() }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(screen.getByRole('combobox', { name: '当前更新来源' })).toHaveValue(defaultSource.id)
  expect(screen.getByLabelText('私有访问令牌')).toHaveValue('')
  expect(screen.queryByText('已添加并切换至「备用 Gitea」，请检查版本。')).not.toBeInTheDocument()
})

it('requires discard before opening an add draft and clears an abandoned new token', async () => {
  renderPage(); await findCurrentVersion(); openAdvancedSources()
  fireEvent.change(screen.getByLabelText('私有访问令牌'), { target: { value: 'unsaved-original-token' } })
  fireEvent.click(screen.getByRole('button', { name: '添加来源' }))
  fireEvent.click(screen.getByRole('button', { name: '保留并返回' }))
  expect(screen.getByLabelText('私有访问令牌')).toHaveValue('unsaved-original-token')
  fireEvent.click(screen.getByRole('button', { name: '添加来源' }))
  fireEvent.click(screen.getByRole('button', { name: '放弃修改并添加' }))
  fillNewSource()
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '取 消' }))
  fireEvent.click(screen.getByRole('button', { name: '添加来源' }))
  expect(screen.getByLabelText('新来源访问令牌')).toHaveValue('')
  expect(screen.getByLabelText('新来源名称')).toHaveValue('')
  expect(api.post).not.toHaveBeenCalled()
})


it('keeps the active source draft and token when advanced source management is collapsed', async () => {
  renderPage(); await findCurrentVersion(); openSourceSettings()
  fireEvent.change(screen.getByLabelText('私有访问令牌'), { target: { value: 'retained-draft-token' } })
  openAdvancedSources()
  expect(screen.getByLabelText('当前更新来源')).toBeVisible()
  fireEvent.click(screen.getByLabelText('高级来源管理'))
  expect(screen.getByLabelText('当前更新来源')).not.toBeVisible()
  expect(screen.getByLabelText('私有访问令牌')).toHaveValue('retained-draft-token')
  await poll()
  expect(screen.getByLabelText('私有访问令牌')).toHaveValue('retained-draft-token')
  expect(api.put).not.toHaveBeenCalled()
  expect(api.post).not.toHaveBeenCalled()
})

it.each([
  { name: 'legacy check', state: { ...online, check: { ...online.check!, trust: undefined } } },
  { name: 'legacy runner', state: { ...online, runner: { ...online.runner, trust: undefined } } },
  { name: 'unconfigured host', state: { ...online, runner: { ...online.runner, trust: { configured: false, protocol: 1 } } } },
  { name: 'unsupported host trust protocol', state: { ...online, runner: { ...online.runner, trust: { configured: true, protocol: 2 } } } },
])('fails closed for $name without starting installation', async ({ state }) => {
  vi.mocked(api.get).mockResolvedValue({ data: state })
  renderPage(); await findCurrentVersion()
  expect(screen.getByRole('heading', { name: '版本尚未通过宿主验证' })).toBeVisible()
  expect(screen.getAllByText('宿主尚未验证此版本，请重新检查或联系部署管理员').length).toBeGreaterThan(0)
  const install = screen.getByRole('button', { name: '安装更新' })
  expect(install).toBeDisabled()
  fireEvent.click(install)
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(api.post).not.toHaveBeenCalled()
})

it('shows the host rejection reason and offers no way to change trust from the page', async () => {
  vi.mocked(api.get).mockResolvedValue({ data: { ...online, check: { ...online.check!, trust: { status: 'rejected', message: '目标标签未签名或签名不属于受信任发布者。' } } } })
  renderPage(); await findCurrentVersion(); openAdvancedSources()
  expect(screen.getByText('此版本未通过信任验证')).toBeVisible()
  expect(screen.getAllByText('目标标签未签名或签名不属于受信任发布者。').length).toBeGreaterThan(0)
  expect(screen.getByRole('button', { name: '安装更新' })).toBeDisabled()
  expect(screen.queryByRole('button', { name: /信任|公钥|允许提交/ })).toBeNull()
  expect(screen.queryByLabelText(/公钥|信任配置|允许提交/)).toBeNull()
})

it('polls pending host verification without a job and enables a verified signed tag', async () => {
  const waiting = { ...online, check: { ...online.check!, trust: { status: 'pending', message: '等待宿主核对版本签名。' } } }
  vi.mocked(api.get).mockResolvedValueOnce({ data: waiting }).mockResolvedValue({ data: { ...online, check: { ...online.check!, trust: { status: 'trusted', method: 'signed_tag', message: '发布标签签名验证通过。' } } } })
  renderPage(); await findCurrentVersion()
  expect(screen.getByRole('heading', { name: '等待宿主验证版本' })).toBeVisible()
  expect(screen.getByRole('button', { name: '安装更新' })).toBeDisabled()
  expect(screen.queryByLabelText('更新进度')).toBeNull()
  await poll()
  expect(await screen.findByText('标签签名已验证')).toBeVisible()
  expect(screen.getByRole('button', { name: '安装更新' })).toBeEnabled()
  expect(api.get).toHaveBeenCalledTimes(2)
  expect(api.post).not.toHaveBeenCalled()
})

it('blocks an open confirmation if the same check loses host trust during polling', async () => {
  vi.mocked(api.get).mockResolvedValueOnce({ data: online }).mockResolvedValue({ data: { ...online, check: { ...online.check!, trust: { status: 'rejected', message: '宿主的发布信任已撤销。' } } } })
  renderPage(); await findCurrentVersion()
  fireEvent.click(screen.getByRole('button', { name: '安装更新' }))
  expect(screen.getByRole('button', { name: '自动备份并安装' })).toBeEnabled()
  await poll()
  await waitFor(() => expect(screen.getByText('宿主信任状态已变化，请关闭后重新检查版本。')).toBeVisible())
  fireEvent.click(screen.getByRole('button', { name: '自动备份并安装' }))
  expect(screen.getByRole('button', { name: '自动备份并安装' })).toBeDisabled()
  expect(api.post).not.toHaveBeenCalled()
})

it('blocks an open confirmation if the runner loses its configured trust capability', async () => {
  vi.mocked(api.get).mockResolvedValueOnce({ data: online }).mockResolvedValue({ data: { ...online, runner: { ...online.runner, trust: undefined } } })
  renderPage(); await findCurrentVersion()
  fireEvent.click(screen.getByRole('button', { name: '安装更新' }))
  await poll()
  await waitFor(() => expect(screen.getByText('宿主信任状态已变化，请关闭后重新检查版本。')).toBeVisible())
  expect(screen.getByRole('button', { name: '自动备份并安装' })).toBeDisabled()
  expect(api.post).not.toHaveBeenCalled()
})
