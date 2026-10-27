import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import { Alert, Badge, Dropdown, List, Typography, Button, Empty, Spin, Space } from 'antd'
import { BellOutlined, CheckOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../stores/auth'
import { isPMWorkbench } from '../constants/roles'
import { TYPE_TAG, openNotification, formatNotificationContent } from '../utils/notifyNav'
import { NOTIFICATION_READ_EVENT, notifyReadStateChanged } from '../utils/notificationEvents'
import { formatDateTime } from '../utils/date'
import { hasSystemPermission } from '../constants/systemPermissions'
import './notificationBell.css'

interface NotificationT {
  id: string
  title: string
  content: string
  ntype: string
  project_id: string | null
  entity_id?: string | null
  is_read: boolean
  created_at: string | null
}

export default function NotificationBell() {
  const [count, setCount] = useState(0)
  const [items, setItems] = useState<NotificationT[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [loadError, setLoadError] = useState(false)
  const [actionError, setActionError] = useState(false)
  const [marking, setMarking] = useState(false)
  const trigger = useRef<HTMLSpanElement>(null)
  const panelId = useId()
  const refreshSequence = useRef(0)
  const accountSession = useRef(0)
  const markLock = useRef(false)
  const navigate = useNavigate()
  const { user } = useAuth()
  const canMessages = hasSystemPermission(user, 'personal.messages.use')

  const refresh = async () => {
    if (!canMessages) return
    const request = ++refreshSequence.current
    setLoading(true)
    try {
      const [c, n] = await Promise.all([
        api.get('/notifications/unread-count'),
        api.get('/notifications', { params: { limit: 20 } }),
      ])
      if (request !== refreshSequence.current) return
      setCount(c.data.count)
      setItems(n.data)
      setLoadError(false)
    } catch {
      if (request === refreshSequence.current) setLoadError(true)
    } finally {
      if (request === refreshSequence.current) setLoading(false)
    }
  }

  useEffect(() => {
    accountSession.current++
    markLock.current = false; setMarking(false)
    setOpen(false); setCount(0); setItems([]); setLoadError(false); setActionError(false)
    if (!canMessages) { refreshSequence.current++; setLoading(false); return }
    refresh()
    // Poll every 60s for new notifications
    const timer = setInterval(refresh, 60000)
    window.addEventListener(NOTIFICATION_READ_EVENT, refresh)
    return () => {
      accountSession.current++
      clearInterval(timer)
      refreshSequence.current++
      window.removeEventListener(NOTIFICATION_READ_EVENT, refresh)
    }
  }, [user?.id, canMessages])

  const markAllRead = async () => {
    if (!canMessages || markLock.current) return
    const session = accountSession.current
    markLock.current = true
    setMarking(true)
    setActionError(false)
    try {
      await api.post('/notifications/read-all')
      if (session !== accountSession.current) return
      refreshSequence.current++
      setCount(0)
      setItems((prev) => prev.map((n) => ({ ...n, is_read: true })))
      notifyReadStateChanged('bell')
    } catch {
      if (session === accountSession.current) setActionError(true)
    } finally {
      if (session === accountSession.current) { markLock.current = false; setMarking(false) }
    }
  }

  const openOne = async (n: NotificationT) => {
    if (!canMessages) return
    const session = accountSession.current
    if (!n.is_read) {
      try {
        await api.post(`/notifications/${n.id}/read`)
        if (session !== accountSession.current) return
        refreshSequence.current++
        setCount((c) => Math.max(0, c - 1))
        notifyReadStateChanged('bell')
      } catch {
        // ignore
      }
    }
    if (session !== accountSession.current) return
    setOpen(false)
    openNotification(n, user, navigate)
  }

  const goMessages = () => {
    setOpen(false)
    // 用 isPMWorkbench 而非 `role === 'worker'`：intern 非 worker，但同样无 /pm 权限，应去 /worker/messages
    navigate(isPMWorkbench(user?.role) ? '/pm/messages' : '/worker/messages')
  }

  const dismissWithKeyboard = (event: KeyboardEvent) => {
    if (open && event.key === 'Escape') {
      event.stopPropagation()
      setOpen(false)
      trigger.current?.querySelector('button')?.focus()
    }
  }

  const menuContent = (
    <div id={panelId} className="notification-preview-panel" onKeyDown={event => {
      // rc-dropdown otherwise closes on the second Tab, before a notification can be reached.
      if (event.key === 'Tab') event.stopPropagation()
      dismissWithKeyboard(event)
    }} onBlur={event => {
      if (event.relatedTarget && !event.currentTarget.contains(event.relatedTarget)) setOpen(false)
    }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '8px 12px',
          borderBottom: '1px solid var(--agv-border)',
        }}
      >
        <Typography.Text strong>通知</Typography.Text>
        {count > 0 && (
          <Button type="link" size="small" icon={<CheckOutlined />} loading={marking} onClick={markAllRead}>
            全部已读
          </Button>
        )}
      </div>
      {loadError && <Alert type="warning" showIcon message={items.length ? '通知刷新失败，当前显示上次内容' : '通知暂时无法加载'}
        action={<Button size="small" aria-label="重新加载通知" onClick={refresh} loading={loading}>重试</Button>} />}
      {actionError && <Alert type="error" showIcon message="标记已读失败，请重试" />}
      {loading && items.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 30 }}>
          <Spin size="small" />
        </div>
      ) : items.length === 0 && !loadError ? (
        <Empty description="暂无通知" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ padding: 30 }} />
      ) : items.length > 0 ? (
        <List
          dataSource={items}
          renderItem={(n) => (
            <List.Item style={{ padding: 0 }}>
              <button type="button" className={`notification-preview-item${n.is_read ? '' : ' is-unread'}`} onClick={() => openOne(n)}>
                  <Space size={6}>
                    {!n.is_read && <Badge status="processing" />}
                    <Typography.Text strong={!n.is_read}>{n.title}</Typography.Text>
                  </Space>
                  <span className="notification-preview-description">
                    <Typography.Text style={{ fontSize: 12 }}>{formatNotificationContent(n.content, n.ntype)}</Typography.Text>
                    <span className="notification-preview-date">
                      <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                        {TYPE_TAG[n.ntype] ?? '系统'} ·{' '}
                        {n.created_at ? formatDateTime(n.created_at) : ''}
                      </Typography.Text>
                    </span>
                  </span>
              </button>
            </List.Item>
          )}
        />
      ) : null}
      <div style={{ borderTop: '1px solid var(--agv-border)' }}>
        <Button type="text" block onClick={goMessages}>
          查看全部通知
        </Button>
      </div>
    </div>
  )

  if (!canMessages) return null
  return (
    <span ref={trigger} onKeyDown={dismissWithKeyboard}>
    <Dropdown
      trigger={['click']}
      open={open}
      onOpenChange={(o) => {
        setOpen(o)
        if (o) refresh()
      }}
      popupRender={() => menuContent}
      placement="bottomRight"
      align={{ overflow: { shiftX: true, adjustX: true, adjustY: true } }}
    >
      <Badge count={count} size="small" offset={[-4, 4]}>
        <Button type="text" aria-label="消息通知" aria-expanded={open} aria-controls={open ? panelId : undefined}
          title={loadError ? '通知加载失败，点击重试' : '消息通知'} icon={<BellOutlined style={{ fontSize: 16 }} />} />
      </Badge>
    </Dropdown>
    </span>
  )
}
