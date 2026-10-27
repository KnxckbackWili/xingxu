import { hasSystemPermission } from '../constants/systemPermissions'
import Tabs from '../components/VisibleTabs'
import { WorkPageHeader, WorkSection } from '../components/WorkPage'
import { NAV_LABEL, NAV_DESCRIPTION } from '../constants/nav'
import './pm/SettingsPages.css'
import { useEffect, useRef, useState } from 'react'
import {
  Alert, Button, Drawer, Empty, Form, Input, Pagination, Select, Space, Spin, Table, Tag, Typography, message,
} from 'antd'
import { useAuth } from '../stores/auth'
import { errMsg } from '../api/client'
import { feedbackApi } from '../api'
import { FEEDBACK_STATUS_MAP, FEEDBACK_STATUS_OPTIONS } from '../constants/feedback'
import { formatDateTime } from '../utils/date'
import { useMediaQuery } from '../hooks/useMediaQuery'
import { MEDIA_QUERY } from '../constants/breakpoints'

interface FeedbackItem {
  id: string
  description: string
  steps: string
  status: string
  user_id: string
  user_name: string
  created_at: string
  updated_at: string
}

/**
 * 系统问题反馈（HYPE-72）。
 * - 全局入口（/pm/feedback、/worker/feedback 共用本页）：所有角色可提交。
 * - 管理角色（admin/director/pm）额外看到反馈列表、详情与处理状态更新；
 *   普通用户不渲染管理区块，后端读取接口亦按角色 403。
 */
export default function FeedbackPage() {
  const isMobile = useMediaQuery(MEDIA_QUERY.mobile)
  const { user } = useAuth()
  const manage = hasSystemPermission(user, 'system.feedback.manage')
  const canSubmit = hasSystemPermission(user, 'feedback.submit')
  const [view, setView] = useState('list')

  const submitLock = useRef(false)
  const loadSequence = useRef(0)
  const [form] = Form.useForm()
  const [submitting, setSubmitting] = useState(false)

  const [items, setItems] = useState<FeedbackItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [refresh, setRefresh] = useState(0)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState(false)

  const [detail, setDetail] = useState<FeedbackItem | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const [statusUpdating, setStatusUpdating] = useState(false)

  const load = async () => {
    if (!manage) return
    const request = ++loadSequence.current
    setLoading(true)
    setLoadError(false)
    try {
      const r = await feedbackApi.list({ status: statusFilter, page, page_size: pageSize })
      if (request !== loadSequence.current) return
      setItems(r.items)
      setTotal(r.total)
    } catch (e) {
      if (request !== loadSequence.current) return
      setLoadError(true)
      setItems([])
      setTotal(0)
      message.error(errMsg(e))
    } finally {
      if (request === loadSequence.current) setLoading(false)
    }
  }

  useEffect(() => {
    if (manage) void load()
    return () => { loadSequence.current++ }
  }, [manage, page, pageSize, statusFilter, refresh]) // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async (values: { description: string; steps?: string }) => {
    if (!canSubmit || submitLock.current) return
    submitLock.current = true
    setSubmitting(true)
    try {
      await feedbackApi.create({ description: values.description.trim(), steps: values.steps?.trim() ?? '' })
      message.success('反馈已提交，感谢你的反馈')
      form.resetFields()
      if (manage) {
        setView('list')
        setPage(1)
        setStatusFilter(undefined)
        setRefresh(value => value + 1)
      }
    } catch (e) {
      message.error(errMsg(e))
    } finally {
      submitLock.current = false
      setSubmitting(false)
    }
  }

  const openDetail = (row: FeedbackItem) => {
    setDetail(row)
    setDetailOpen(true)
  }

  const updateStatus = async (status: string) => {
    if (!detail) return
    setStatusUpdating(true)
    try {
      const updated = await feedbackApi.updateStatus(detail.id, status)
      setDetail(updated)
      message.success('处理状态已更新')
      void load()
    } catch (e) {
      message.error(errMsg(e))
    } finally {
      setStatusUpdating(false)
    }
  }

  const columns = [
    { title: '问题描述', dataIndex: 'description', ellipsis: true, render: (v: string, row: FeedbackItem) => <Typography.Link onClick={() => openDetail(row)}>{v}</Typography.Link> },
    { title: '提交人', dataIndex: 'user_name', width: 120, render: (v: string) => v || '—' },
    { title: '状态', dataIndex: 'status', width: 100, render: (v: string) => { const m = FEEDBACK_STATUS_MAP[v]; return <Tag color={m?.color}>{m?.label ?? v}</Tag> } },
    { title: '提交时间', dataIndex: 'created_at', width: 170, render: (v: string) => formatDateTime(v) },
    { title: '操作', key: 'actions', width: 80, render: (_: unknown, row: FeedbackItem) => <Button size="small" type="link" onClick={() => openDetail(row)}>查看</Button> },
  ]

  const submission = <WorkSection title="描述遇到的问题" description="这是软件使用反馈；项目现场故障请到项目“问题”上报。">
        <Form form={form} layout="vertical" disabled={!canSubmit} onFinish={submit}>
          <Form.Item
            name="description"
            label="问题描述"
            rules={[
              { required: true, whitespace: true, message: '请填写问题描述' },
              { max: 2000, message: '问题描述不能超过 2000 字' },
            ]}
          >
            <Input.TextArea rows={4} maxLength={2000} showCount placeholder="请描述你遇到的问题（必填）" />
          </Form.Item>
          <Form.Item
            name="steps"
            label="复现步骤（可选）"
            rules={[{ max: 5000, message: '复现步骤不能超过 5000 字' }]}
          >
            <Input.TextArea rows={3} maxLength={5000} showCount placeholder="如何复现这个问题？请分步骤描述（选填）" />
          </Form.Item>

        </Form>  </WorkSection>
  const feedbackList = <WorkSection title="反馈列表" description="点击一条反馈查看复现步骤并更新处理状态。" filters={
            <Select
              aria-label="按反馈状态筛选"
              allowClear
              placeholder="按状态筛选"
              style={{ width: 140 }}
              value={statusFilter}
              onChange={(value) => { setPage(1); setStatusFilter(value) }}
              options={FEEDBACK_STATUS_OPTIONS}
            />  }>
          {loadError ? <Alert type="error" showIcon message="反馈列表加载失败" description="请重新加载后查看；加载失败不代表没有反馈。"
            action={<Button onClick={() => void load()}>重试</Button>} /> : isMobile ? <Spin spinning={loading}>
            {items.length ? <div className="feedback-mobile-list">
              {items.map(item => <article key={item.id} className="settings-object-card feedback-item">
                <div className="feedback-item-meta">
                  <Tag color={FEEDBACK_STATUS_MAP[item.status]?.color}>{FEEDBACK_STATUS_MAP[item.status]?.label ?? item.status}</Tag>
                  <Typography.Text type="secondary">{formatDateTime(item.created_at)}</Typography.Text>
                </div>
                <button type="button" className="feedback-item-title" onClick={() => openDetail(item)}>{item.description}</button>
                <div className="feedback-item-footer">
                  <Typography.Text type="secondary">提交人：{item.user_name || '—'}</Typography.Text>
                  <Button onClick={() => openDetail(item)}>查看详情</Button>
                </div>
              </article>)}
            </div> : loading ? <div className="work-empty" role="status">正在加载反馈…</div>
              : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={statusFilter ? '当前状态下暂无反馈' : '暂无反馈'} />}
            {total > 0 && <Pagination className="feedback-pagination" simple current={page} pageSize={pageSize} total={total}
              showSizeChanger={false} onChange={setPage} showTotal={count => `共 ${count} 条反馈`} />}
          </Spin> : <Table<FeedbackItem>
            rowKey="id"
            columns={columns}
            dataSource={items}
            loading={loading}
            scroll={{ x: 720 }}
            pagination={{
              current: page,
              pageSize,
              total,
              showSizeChanger: true,
              showTotal: (t) => `共 ${t} 条反馈`,
              onChange: (p, ps) => { setPage(p); setPageSize(ps) },
            }}
            locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无反馈" /> }}
          />}  </WorkSection>

  return (
    <div className="settings-work-page feedback-page">
      <WorkPageHeader title={NAV_LABEL['/pm/feedback']} description={NAV_DESCRIPTION['/pm/feedback']}
        primary={canSubmit ? manage && view !== 'create' ? <Button type="primary" onClick={() => setView('create')}>填写反馈</Button>
          : <Button type="primary" loading={submitting} onClick={() => form.submit()}>提交反馈</Button> : undefined} />
      {manage ? <Tabs activeKey={view} onChange={setView} items={[
        { key: 'list', label: '处理反馈', children: feedbackList },
        { key: 'create', label: '填写反馈', children: submission },
      ]} /> : submission}

      <Drawer title="反馈详情" rootClassName="feedback-detail-drawer" width="min(480px, 100vw)" open={detailOpen} onClose={() => setDetailOpen(false)}>
        {detail && (
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <div>
              <Typography.Text type="secondary">提交人</Typography.Text>
              <div>{detail.user_name || '—'}</div>
            </div>
            <div>
              <Typography.Text type="secondary">提交时间</Typography.Text>
              <div>{formatDateTime(detail.created_at)}</div>
            </div>
            <div>
              <Typography.Text type="secondary">更新时间</Typography.Text>
              <div>{formatDateTime(detail.updated_at)}</div>
            </div>
            <div>
              <Typography.Text type="secondary">处理状态</Typography.Text>
              <div style={{ marginTop: 4 }}>
                <Space>
                  <Tag color={FEEDBACK_STATUS_MAP[detail.status]?.color}>
                    {FEEDBACK_STATUS_MAP[detail.status]?.label ?? detail.status}
                  </Tag>
                  {manage && (
                    <Select
                      aria-label="反馈处理状态"
                      value={detail.status}
                      style={{ width: 120 }}
                      loading={statusUpdating}
                      disabled={statusUpdating}
                      onChange={updateStatus}
                      options={FEEDBACK_STATUS_OPTIONS}
                    />
                  )}
                </Space>
              </div>
            </div>
            <div>
              <Typography.Text type="secondary">问题描述</Typography.Text>
              <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginTop: 4 }}>{detail.description}</Typography.Paragraph>
            </div>
            <div>
              <Typography.Text type="secondary">复现步骤</Typography.Text>
              <Typography.Paragraph type="secondary" style={{ whiteSpace: 'pre-wrap', marginTop: 4 }}>
                {detail.steps || '（未填写）'}
              </Typography.Paragraph>
            </div>
          </Space>
        )}
      </Drawer>
    </div>
  )
}
