import { useAuth } from '../../stores/auth'
import { hasSystemPermission } from '../../constants/systemPermissions'
import { WorkPageHeader, WorkSection } from '../../components/WorkPage'
import { NAV_LABEL, NAV_DESCRIPTION } from '../../constants/nav'
import './SettingsPages.css'
import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Input, Modal, Space, Switch, Tag, Typography, message } from 'antd'
import { ReloadOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import { api } from '../../api/client'
import { errMsg } from '../../api/client'

interface DingtalkStatus {
  configured: boolean
  enabled: boolean
  source: 'env' | 'db' | null
  env_managed: boolean
  webhook_masked: string
  secret_set: boolean
  editable: boolean
  last_test: { at: string; success: boolean; detail: string } | null
}

interface ChannelsStatus {
  in_app: { enabled: boolean; label: string }
  dingtalk: DingtalkStatus
}

export default function NotificationChannelsPage() {
  const { user } = useAuth()
  const canConfigure = hasSystemPermission(user, 'system.notifications.configure')
  const [status, setStatus] = useState<ChannelsStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [enabled, setEnabled] = useState(false)
  const [webhook, setWebhook] = useState('')
  const [secret, setSecret] = useState('')
  const [configureOpen, setConfigureOpen] = useState(false)

  const applyStatus = (data: ChannelsStatus) => {
    setStatus(data)
    setEnabled(data.dingtalk.enabled)
  }

  const load = useCallback(async () => {
    setLoading(true)
    try {
      applyStatus((await api.get('/notification-channels')).data)
    } catch (error) { message.error(errMsg(error)) } finally { setLoading(false) }
  }, [])

  useEffect(() => { void load() }, [load])

  const save = async (nextEnabled: boolean) => {
    if (!canConfigure) return
    setSaving(true)
    try {
      await api.put('/notification-channels/dingtalk', {
        enabled: nextEnabled,
        webhook_url: webhook.trim(),
        // 输入框留空 = 保留已存 Secret；只在用户显式输入时覆盖
        secret: secret === '' ? null : secret,
      })
      message.success(nextEnabled ? '钉钉渠道已保存并启用' : '已保存（渠道保持停用）')
      setSecret('')
      await load()
    } catch (error) { message.error(errMsg(error)) } finally { setSaving(false) }
  }

  const disable = () => {
    if (!canConfigure) return
    Modal.confirm({
      title: '确认停用钉钉渠道？',
      content: '停用后外部投递立即停止（已保存的配置会保留，站内通知不受影响）。',
      okText: '停用', cancelText: '取消', okButtonProps: { danger: true },
      onOk: async () => {
        try { await api.delete('/notification-channels/dingtalk'); message.success('钉钉渠道已停用'); await load() }
        catch (error) { message.error(errMsg(error)); throw error }
      },
    })
  }

  const sendTest = () => {
    if (!canConfigure) return
    Modal.confirm({
      title: '向钉钉发送一条测试通知？',
      content: '将使用当前保存的配置直接外发一条测试消息（不产生业务通知，10 分钟内最多 5 次）。',
      okText: '发送测试', cancelText: '取消',
      onOk: async () => {
        try {
          const r = await api.post('/notification-channels/dingtalk/test')
          if (r.data.success) message.success('测试通知发送成功')
          else message.error(r.data.detail || '测试发送失败')
          await load()
        } catch (error) { message.error(errMsg(error)); throw error }
      },
    })
  }

  const ding = status?.dingtalk
  const envManaged = !!ding?.env_managed

  return <div className="settings-work-page notification-settings-page">
    <WorkPageHeader title={NAV_LABEL['/pm/notification-channels']} description={NAV_DESCRIPTION['/pm/notification-channels']}
      primary={canConfigure && <Button type="primary" disabled={!ding || envManaged} loading={saving} onClick={() => configureOpen ? save(enabled) : setConfigureOpen(true)}>{configureOpen ? '保存' : '配置钉钉'}</Button>}
      tools={<Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>刷新</Button>} />
    <WorkSection title="站内消息" description="项目待办与变更通过站内消息送达，无需额外配置。">
      <Space wrap>
        <Tag color="green" icon={<SafetyCertificateOutlined />}>{status?.in_app.label ?? '站内通知（始终开启）'}</Tag>
        <Typography.Text type="secondary">所有站内通知不受外部渠道启停影响。</Typography.Text>
      </Space>
    </WorkSection>

    <WorkSection
      title="钉钉机器人" description="按需将通知送到团队机器人；停用不会影响站内消息。"
      extra={ding?.source === 'env' ? <Tag color="blue">由部署环境托管</Tag>
        : ding?.source === 'db' ? <Tag color="purple">界面配置</Tag>
        : <Tag>未配置</Tag>}
    >
      {ding && (
        <>
          {!ding.editable && (
            <Alert type="info" showIcon style={{ marginBottom: 16 }}
              message="当前钉钉渠道由部署环境变量托管" description="界面配置不生效；如需改为界面管理，请在部署环境中移除 DINGTALK_WEBHOOK_URL 配置。" />
          )}
          <Space wrap className="notification-status">
              <Tag color={ding.enabled ? 'success' : 'default'}>{ding.enabled ? '已启用' : '已停用'}</Tag>
              {ding.configured && <Typography.Text type="secondary">当前 Webhook：{ding.webhook_masked}</Typography.Text>}
              {ding.secret_set && <Typography.Text type="secondary">已配置加签 Secret</Typography.Text>}
          </Space>
          {ding.last_test && <Alert type={ding.last_test.success ? 'success' : 'error'} showIcon message={`最近测试：${ding.last_test.success ? '成功' : '失败'}`} description={ding.last_test.detail} className="settings-notice" />}
          <details className="work-detail-summary settings-detail" open={configureOpen} onToggle={event => setConfigureOpen(event.currentTarget.open)}>
            <summary>钉钉配置与测试</summary>
          <Space direction="vertical" size={12} style={{ width: '100%', maxWidth: 640 }}>
            <Space wrap>
              <Switch aria-label="启用钉钉通知" checked={enabled} disabled={!canConfigure || envManaged || saving} onChange={setEnabled} />
              <Typography.Text>{enabled ? '已启用' : '已停用'}</Typography.Text>
            </Space>
            <label>
              <Typography.Text type="secondary">机器人 Webhook（HTTPS，仅限钉钉官方地址；含 access_token 属敏感凭据，保存后仅显示掩码）</Typography.Text>
              <Input
                aria-label="钉钉 Webhook 地址"
                value={webhook}
                disabled={!canConfigure || envManaged || saving}
                placeholder={ding.webhook_masked || 'https://oapi.dingtalk.com/robot/send?access_token=...'}
                onChange={(e) => setWebhook(e.target.value)}
              />
            </label>
            <label>
              <Typography.Text type="secondary">加签 Secret（可选；留空保持不变，需清除请用下方「清除 Secret」）</Typography.Text>
              <Input.Password
                aria-label="钉钉加签 Secret"
                value={secret}
                disabled={!canConfigure || envManaged || saving}
                placeholder={ding.secret_set ? '已设置（输入新值可覆盖）' : '未设置'}
                onChange={(e) => setSecret(e.target.value)}
              />
            </label>
            <Space wrap>
              <Button disabled={!canConfigure || saving} onClick={() => { setEnabled(ding.enabled); setWebhook(''); setSecret(''); setConfigureOpen(false) }}>取消修改</Button>
              <Button disabled={!canConfigure || envManaged || saving} onClick={disable}
                title={ding.enabled ? '停用外部投递（配置保留）' : '当前已停用'}>停用</Button>
              <Button disabled={!canConfigure || !ding.configured} onClick={sendTest}>发送测试通知</Button>
              {ding.secret_set && !envManaged && (
                <Button danger disabled={!canConfigure || saving} onClick={() => {
                  Modal.confirm({
                    title: '清除已保存的加签 Secret？',
                    content: '清除后下次投递将不再加签；若机器人开启了加签校验，外发会被钉钉拒绝。',
                    okText: '清除', cancelText: '取消', okButtonProps: { danger: true },
                    onOk: async () => {
                      try {
                        await api.put('/notification-channels/dingtalk', { enabled, webhook_url: webhook.trim(), clear_secret: true })
                        message.success('加签 Secret 已清除'); await load()
                      } catch (error) { message.error(errMsg(error)); throw error }
                    },
                  })
                }}>清除 Secret</Button>
              )}
            </Space>
          </Space>
          </details>
        </>
      )}
    </WorkSection>
  </div>
}
