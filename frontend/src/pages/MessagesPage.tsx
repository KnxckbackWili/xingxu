import { useDrawerReturnFocus } from '../hooks/useDrawerReturnFocus'
import { WorkPageHeader, WorkSection } from '../components/WorkPage'
import { NAV_LABEL, NAV_DESCRIPTION } from '../constants/nav'
import { useMediaQuery } from '../hooks/useMediaQuery'
import { MEDIA_QUERY } from '../constants/breakpoints'
import './pm/SettingsPages.css'
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Alert, Card, Drawer, List, Segmented, Select, Checkbox, Button, Spin, Space, Row, Col,
  Typography, Tag, message,
} from 'antd'
import { CheckOutlined, ReloadOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../stores/auth'
import { TYPE_TAG, openNotification, formatNotificationContent } from '../utils/notifyNav'
import { NOTIFICATION_READ_EVENT, notifyReadStateChanged } from '../utils/notificationEvents'
import { formatDateTime } from '../utils/date'
import { FONT } from '../constants/theme'
import EmptyState from '../components/EmptyState'

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

const PAGE_SIZE = 20

export default function MessagesPage() {
  const isMobile = useMediaQuery(MEDIA_QUERY.mobile)
  const detailTrigger = useRef<HTMLElement | null>(null)
  const detailTriggerId = useRef<string | null>(null)
  const restoreDetailFocus = useRef(false)
  const [items, setItems] = useState<NotificationT[]>([])
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState(false)
  const [hasMore, setHasMore] = useState(false)
  const loadSeq = useRef(0)
  const appendPending = useRef(false)
  const loadPending = useRef(false)
  const [unreadOnly, setUnreadOnly] = useState(false)
  const [typeFilter, setTypeFilter] = useState<string>('all')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  // 左右分栏：右侧详情
  const [detail, setDetail] = useState<any | null>(null)
  const navigate = useNavigate()
  const { user } = useAuth()

  useDrawerReturnFocus(!!detail, restoreDetailFocus, 'message-detail-mobile-drawer', () => {
    const currentMessage = [...document.querySelectorAll<HTMLButtonElement>('.message-title-button')].find(button => button.dataset.notificationId === detailTriggerId.current)
    return (detailTrigger.current?.isConnected ? detailTrigger.current : currentMessage)
      ?? document.querySelector<HTMLInputElement>('.messages-work-page .ant-segmented-item-selected input')
  })

  // 已加载条数用 ref 跟踪（不放进 useCallback 依赖，避免 items 变化触发 useEffect 重跑重置分页）
  const itemsRef = useRef(0)
  const load = useCallback(async (append: boolean) => {
    if (append && appendPending.current) return
    const seq = ++loadSeq.current
    appendPending.current = append
    loadPending.current = true
    setLoading(true)
    setLoadError(false)
    if (!append) { itemsRef.current = 0; setItems([]); setHasMore(false); setSelected(new Set()) }
    try {
      const offset = append ? itemsRef.current : 0
      const r = await api.get('/notifications', { params: { limit: PAGE_SIZE, offset, unread_only: unreadOnly, ...(typeFilter !== 'all' ? { ntype: typeFilter } : {}) } })
      if (seq !== loadSeq.current) return
      itemsRef.current = offset + r.data.length
      setItems(prev => append ? [...prev, ...r.data] : r.data)
      setHasMore(r.data.length === PAGE_SIZE)
    } catch {
      if (seq === loadSeq.current) setLoadError(true)
    } finally {
      if (seq === loadSeq.current) { setLoading(false); appendPending.current = false; loadPending.current = false }
    }
  }, [unreadOnly, typeFilter])

  // Mutations use the latest filter, even if it changed while the write was in flight.
  const latestLoad = useRef(load)
  latestLoad.current = load
  const latestUnreadOnly = useRef(unreadOnly)
  latestUnreadOnly.current = unreadOnly
  useEffect(() => {
    const refresh = (event: Event) => {
      if ((event as CustomEvent<{ source?: string }>).detail?.source !== 'messages') void latestLoad.current(false)
    }
    window.addEventListener(NOTIFICATION_READ_EVENT, refresh)
    return () => window.removeEventListener(NOTIFICATION_READ_EVENT, refresh)
  }, [])
  useEffect(() => {
    setDetail(null)
    void load(false)
    return () => { loadSeq.current++ }
  }, [load])

  const visible = items

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const markSelectedRead = async () => {
    if (selected.size === 0) return
    try {
      const r = await api.post('/notifications/read-batch', { ids: Array.from(selected) })
      notifyReadStateChanged('messages')
      setItems((prev) => prev.map((n) => (selected.has(n.id) ? { ...n, is_read: true } : n)))
      message.success(`已将 ${r.data.updated} 条通知标记为已读`)
      setSelected(new Set())
      if (latestUnreadOnly.current || loadPending.current) await latestLoad.current(false)
    } catch (e: any) {
      message.error(e.response?.data?.detail ?? '标记失败')
    }
  }

  const markAllRead = async () => {
    try {
      await api.post('/notifications/read-all')
      notifyReadStateChanged('messages')
      setItems((prev) => prev.map((n) => ({ ...n, is_read: true })))
      message.success('全部已读')
      setSelected(new Set())
      // A read started before this write may still carry unread rows; replace it with a fresh request.
      if (latestUnreadOnly.current || loadPending.current) await latestLoad.current(false)
    } catch (e: any) {
      message.error(e.response?.data?.detail ?? '操作失败')
    }
  }

  const openOne = async (n: NotificationT) => {
    // 左右分栏：点击 → 右侧显示详情并标记已读（不立即跳转）
    detailTriggerId.current = n.id
    setDetail(n)
    if (!n.is_read) {
      try {
        await api.post(`/notifications/${n.id}/read`)
        notifyReadStateChanged('messages')
        setItems((prev) => prev.map((x) => (x.id === n.id ? { ...x, is_read: true } : x)))
        if (latestUnreadOnly.current || loadPending.current) await latestLoad.current(false)
      } catch {
        // ignore
      }
    }
  }

  const detailContent = detail && <>
    <h2 className="message-detail-title">{detail.title}</h2>
    <Space size={8} wrap style={{ marginBottom: 12 }}>
      <Tag>{TYPE_TAG[detail.ntype] ?? '系统'}</Tag>
      <Typography.Text type="secondary">{detail.created_at ? formatDateTime(detail.created_at) : ''}</Typography.Text>
      {detail.project_name && <Typography.Text type="secondary">项目：{detail.project_name}</Typography.Text>}
    </Space>
    <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>{formatNotificationContent(detail.content, detail.ntype)}</Typography.Paragraph>
    <Button type="primary" onClick={() => openNotification(detail, user, navigate)}>前往处理 →</Button>
  </>

  return (
    <div className="settings-work-page messages-work-page">
      <WorkPageHeader title={NAV_LABEL['/pm/messages']} description={NAV_DESCRIPTION['/pm/messages']}
        primary={!detail && !selected.size ? <Button type="primary" disabled={loading || !items.length} onClick={() => {
          detailTrigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
          void openOne(items.find(item => !item.is_read) ?? items[0])
        }}>{items.some(item => !item.is_read) ? '查看未读' : '查看消息'}</Button> : undefined}
        tools={<Space><Button icon={<ReloadOutlined />} onClick={() => load(false)}>刷新</Button><Button onClick={markAllRead}>全部已读</Button></Space>} />
      <WorkSection title="收件箱" description={loading ? '正在加载消息' : `${items.length} 条已加载 · ${items.filter(item => !item.is_read).length} 条未读`} filters={
      <Space style={{ marginBottom: 16 }} wrap>
        <Segmented
          value={unreadOnly ? 'unread' : 'all'}
          onChange={(v) => setUnreadOnly(v === 'unread')}
          options={[
            { label: '全部', value: 'all' },
            { label: '未读', value: 'unread' },
          ]}
        />
        <Select
          virtual={false}
          style={{ width: 160 }}
          aria-label="按类型筛选"
          value={typeFilter}
          onChange={setTypeFilter}
          options={[
            { label: '全部类型', value: 'all' },
            ...Object.entries(TYPE_TAG).map(([value, label]) => ({ value, label })),
          ]}
        />
        {selected.size > 0 && (
          <Button type="primary" icon={<CheckOutlined />} onClick={markSelectedRead}>
            标记已读（{selected.size}）
          </Button>
        )}
      </Space>}>

      {loadError && <Alert type="error" showIcon message="通知加载失败" description="请重试，未加载成功不代表没有通知。" action={<Button onClick={() => load(items.length > 0)}>重试</Button>} style={{ marginBottom: 16 }} />}
      <Row gutter={16}>
        {/* 左：消息列表（精简项：圆点/标题/摘要/时间） */}
        <Col xs={24} lg={isMobile ? 24 : 10}>
          {loading && items.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 40 }}>
              <Spin />
            </div>
          ) : loadError && items.length === 0 ? null : visible.length === 0 ? (
            <EmptyState title="暂无通知" description={typeFilter !== "all" ? "当前类型没有通知，可选择其他类型查看。" : "项目进展和需要处理的事项会在这里通知你。"} />
          ) : (
            <>
              <List
                dataSource={visible}
                renderItem={(n) => (
                  <List.Item
                    className={`message-list-item${detail?.id === n.id ? ' is-selected' : ''}${!n.is_read ? ' is-unread' : ''}`}
                    onClick={(event) => { detailTrigger.current = event.currentTarget.querySelector<HTMLElement>('.message-title-button') ?? event.currentTarget; void openOne(n) }}
                  >
                    <Space align="start" size={4} className="message-select-area">
                      {!n.is_read && <span className="message-unread-dot" aria-label="未读" />}
                      <Checkbox
                        aria-label="选择该消息"
                        checked={selected.has(n.id)}
                        onChange={(e) => {
                          e.stopPropagation()
                          toggleSelect(n.id)
                        }}
                        onClick={(e) => e.stopPropagation()}
                      />
                    </Space>
                    <List.Item.Meta
                      style={{ flex: 1, minWidth: 0, paddingLeft: 4 }}
                      title={
                        <button type="button" className="message-title-button" data-notification-id={n.id} onClick={(event) => { event.stopPropagation(); detailTrigger.current = event.currentTarget; void openOne(n) }} style={{ fontWeight: n.is_read ? 400 : 600, fontSize: FONT.body }}>{n.title}</button>
                      }
                      description={
                        <div>
                          <Typography.Text type="secondary" className="message-content-clamp" style={{ fontSize: FONT.small }}>
                            {formatNotificationContent(n.content, n.ntype)}
                          </Typography.Text>
                          <div style={{ marginTop: 2 }}>
                            <Typography.Text type="secondary" style={{ fontSize: FONT.caption }}>
                              {TYPE_TAG[n.ntype] ?? '系统'} · {n.created_at ? formatDateTime(n.created_at) : ''}
                            </Typography.Text>
                          </div>
                        </div>
                      }
                    />
                  </List.Item>
                )}
              />
              {hasMore && (
                <div style={{ textAlign: 'center', marginTop: 16 }}>
                  <Button loading={loading} onClick={() => load(true)}>
                    加载更多
                  </Button>
                </div>
              )}
            </>
          )}
        </Col>
        {!isMobile && <Col xs={24} lg={14} className={detail ? 'message-detail-panel' : 'message-detail-panel message-detail-panel--empty'}>
          {detail ? <Card size="small" style={{ minHeight: 280 }}>{detailContent}</Card>
            : <EmptyState compact title="未选择消息" description="点击左侧消息查看完整内容和处理入口。" />}
        </Col>}
      </Row>
      </WorkSection>
      {isMobile && <Drawer title="消息详情" rootClassName="message-detail-mobile-drawer" open={!!detail}
        onClose={() => { restoreDetailFocus.current = true; setDetail(null) }} width="min(480px, calc(100vw - 16px))" destroyOnHidden>
        {detailContent}
      </Drawer>}
    </div>
  )
}
