import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

const mockNavigate = vi.fn()

vi.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
}))

vi.mock('../../api/client', () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
  errMsg: () => 'mock-error',
}))

import { api } from '../../api/client'
import { useAuth } from '../../stores/auth'
import NotificationChannelsPage from './NotificationChannelsPage'

const DB_STATUS = {
  in_app: { enabled: true, label: '站内通知（始终开启）' },
  dingtalk: {
    configured: true, enabled: true, source: 'db', env_managed: false,
    webhook_masked: 'https://oapi.dingtalk.com/robot/send?access_token=****',
    secret_set: true, editable: true, last_test: null,
  },
}

const ENV_STATUS = {
  ...DB_STATUS,
  dingtalk: { ...DB_STATUS.dingtalk, source: 'env', env_managed: true, editable: false },
}

beforeEach(() => {
  vi.clearAllMocks()
  mockNavigate.mockClear()
  useAuth.setState({ user: { id: 'u-admin', role: 'admin', username: 'admin', display_name: '管理员', phone: '', email: '', is_active: true } })
  vi.mocked(api.get).mockResolvedValue({ data: DB_STATUS })
  vi.mocked(api.put).mockResolvedValue({ data: { enabled: true, secret_set: true } })
  vi.mocked(api.post).mockResolvedValue({ data: { success: true, detail: '发送成功' } })
  vi.mocked(api.delete).mockResolvedValue({ data: { message: 'ok' } })
})

describe('通知渠道页（管理员）', () => {
  it('渲染站内通知与钉钉渠道状态（掩码 Webhook）', async () => {
    render(<NotificationChannelsPage />)
    expect(await screen.findByText('站内通知（始终开启）')).toBeInTheDocument()
    const webhookText = await screen.findByText(/当前 Webhook：/)
    expect(webhookText.textContent).toContain('access_token=****')
    expect(screen.getByText('钉钉配置与测试').closest('details')).not.toHaveAttribute('open')
    expect(api.put).not.toHaveBeenCalled()
    fireEvent.click(screen.getByText('钉钉配置与测试'))
    expect(screen.getByRole('switch')).toBeChecked()
  })

  it('env 托管时展示只读提示并禁用表单', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: ENV_STATUS })
    render(<NotificationChannelsPage />)
    expect(await screen.findByText('当前钉钉渠道由部署环境变量托管')).toBeInTheDocument()
    fireEvent.click(screen.getByText('钉钉配置与测试'))
    await screen.findByRole('button', { name: /保\s*存/ })
    expect(screen.getByRole('switch')).toBeDisabled()
    expect(screen.getByRole('button', { name: /保\s*存/ })).toBeDisabled()
  })

  it('保存调用 PUT，Secret 输入留空时传 null（保留既有 Secret）', async () => {
    render(<NotificationChannelsPage />)
    await screen.findByText('站内通知（始终开启）')
    fireEvent.click(await screen.findByRole('button', { name: '配置钉钉' }))
    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))
    await waitFor(() => expect(api.put).toHaveBeenCalledWith('/notification-channels/dingtalk',
      { enabled: true, webhook_url: '', secret: null }))
  })

  it('发送测试通知需二次确认并展示结果', async () => {
    render(<NotificationChannelsPage />)
    await screen.findByText('站内通知（始终开启）')
    fireEvent.click(await screen.findByRole('button', { name: '配置钉钉' }))
    fireEvent.click(screen.getByRole('button', { name: '发送测试通知' }))
    const testOks = await screen.findAllByRole('button', { name: '发送测试' })
    fireEvent.click(testOks[testOks.length - 1])
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/notification-channels/dingtalk/test'))
    expect(await screen.findByText(/测试通知发送成功/)).toBeInTheDocument()
  })

  it('停用需二次确认并调用 DELETE', async () => {
    render(<NotificationChannelsPage />)
    await screen.findByText('站内通知（始终开启）')
    fireEvent.click(await screen.findByRole('button', { name: '配置钉钉' }))
    fireEvent.click(screen.getByRole('button', { name: /停\s*用/ }))
    await screen.findAllByText('确认停用钉钉渠道？') // 等 confirm 弹窗挂载（rc-motion 异步）
    const stopBtns = await screen.findAllByRole('button', { name: /停\s*用/ })
    fireEvent.click(stopBtns[stopBtns.length - 1])
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/notification-channels/dingtalk'))
  })
})
