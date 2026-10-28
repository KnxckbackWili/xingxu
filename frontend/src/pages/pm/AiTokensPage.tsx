import { hasSystemPermission } from '../../constants/systemPermissions'
import { WorkPageHeader, WorkSection } from '../../components/WorkPage'
import { NAV_LABEL, NAV_DESCRIPTION } from '../../constants/nav'
import './SettingsPages.css'
import { useEffect, useRef, useState } from 'react'
import {
  Alert, Button, Card, Checkbox, DatePicker, Empty, Form, Input, message, Modal, Popconfirm,
  Select, Space, Switch, Table, Tag, Typography,
} from 'antd'
import { CopyOutlined, PlusOutlined, ApiOutlined, KeyOutlined } from '@ant-design/icons'
import { formatDateTime } from '../../utils/date'
import { aiInternalApi, userApi } from '../../api'
import { errMsg } from '../../api/client'
import SwitchTouch from '../../components/SwitchTouch'
import { useMediaQuery } from '../../hooks/useMediaQuery'
import { MEDIA_QUERY } from '../../constants/breakpoints'
import { useSubmitLock } from '../../hooks/useSubmitLock'
import { useAuth } from '../../stores/auth'
import { InfoHint } from '../../components/IconAction'

interface BudgetStatus { enabled: boolean; blocked: boolean; reason: string; limits: { requests: number; tokens: number }; usage: { month: string; requests: number; tokens: number } }

interface TokenRow {
  id: string
  name: string
  token_prefix: string
  user_id: string
  user_name: string
  scopes: string[]
  expires_at: string | null
  is_active: boolean
  last_used_at: string | null
  created_at: string | null
}

export default function AiTokensPage() {
  const isMobile = useMediaQuery(MEDIA_QUERY.mobile)
  const [budget, setBudget] = useState<BudgetStatus | null>(null)
  const [rows, setRows] = useState<TokenRow[]>([])
  const [scopeOptions, setScopeOptions] = useState<Array<[string, string]>>([])
  const [users, setUsers] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [createdToken, setCreatedToken] = useState('')
  const [form] = Form.useForm()

  const user = useAuth((state) => state.user)
  const userId = user?.id
  const canManage = hasSystemPermission(user, 'system.agent_tokens.manage')
  const submitLock = useSubmitLock()
  const busy = useRef(false)
  const dialogOpen = useRef(false)
  const scope = useRef(0)
  const loadSequence = useRef(0)

  const load = async () => {
    const request = ++loadSequence.current
    setLoading(true)
    try {
      const [data, accounts] = await Promise.all([aiInternalApi.tokens(), user?.role === 'admin' && hasSystemPermission(user, 'system.users.read') ? userApi.list() : Promise.resolve(user ? [{ ...user }] : [])])
      if (request !== loadSequence.current) return
      setRows(user?.role === 'admin' ? data.items : data.items.filter((row: TokenRow) => row.user_id === userId))
      setScopeOptions(data.scopes.filter(([value]: [string, string]) => value.endsWith(':read')))
      setBudget(data.budget ?? null)
      setUsers(accounts.filter((account: any) => account.is_active))
    } catch (error) {
      if (request === loadSequence.current) message.error(errMsg(error))
    } finally { if (request === loadSequence.current) setLoading(false) }
  }

  useEffect(() => {
    setRows([])
    setBudget(null)
    setScopeOptions([])
    setUsers([])
    setOpen(false)
    setCreatedToken('')
    setSaving(false)
    void load()
    return () => {
      scope.current++
      loadSequence.current++
      dialogOpen.current = false
      busy.current = false
      submitLock.release()
    }
  }, [userId])

  // One synchronous lock covers all token writes, including competing enable/revoke actions.
  const mutate = async (action: () => Promise<void>) => {
    if (!canManage || !submitLock.tryAcquire()) return
    const generation = scope.current
    busy.current = true
    setSaving(true)
    loadSequence.current++
    setLoading(false)
    try { await action() }
    catch (error) { if (generation === scope.current) message.error(errMsg(error)) }
    finally {
      if (generation === scope.current) {
        submitLock.release()
        busy.current = false
        setSaving(false)
      }
    }
  }

  const create = async (values: any) => {
    if (!dialogOpen.current) return
    const generation = scope.current
    await mutate(async () => {
      const r = await aiInternalApi.createToken({
        name: values.name,
        user_id: values.user_id,
        scopes: values.scopes,
        expires_at: values.expires_at?.toISOString() ?? null,
      })
      if (generation !== scope.current) return
      setCreatedToken(r.token)
      form.resetFields()
      dialogOpen.current = false
      setOpen(false)
      message.success('访问令牌已创建')
      await load()
    })
  }

  const setActive = async (id: string, isActive: boolean, revoke = false) => {
    const generation = scope.current
    await mutate(async () => {
      if (revoke) await aiInternalApi.revokeToken(id)
      else await aiInternalApi.updateToken(id, { is_active: isActive })
      if (generation !== scope.current) return
      // Keep the confirmed security state even if the following refresh fails.
      setRows((current) => current.map((row) => row.id === id ? { ...row, is_active: isActive } : row))
      message.success(isActive ? '已启用' : '已停用')
      await load()
    })
  }

  const toggle = (row: TokenRow, isActive: boolean) => setActive(row.id, isActive)
  const revoke = (id: string) => setActive(id, false, true)
  const openCreate = () => {
    if (!canManage || busy.current) return
    form.resetFields()
    form.setFieldsValue({ user_id: user?.role === 'admin' ? undefined : userId, scopes: scopeOptions.map(([value]) => value).filter(value => value.endsWith(':read')) })
    dialogOpen.current = true
    setOpen(true)
  }
  const closeCreate = () => {
    if (busy.current) return
    dialogOpen.current = false
    setOpen(false)
  }

  const emptyNode = <Empty image={<KeyOutlined style={{ fontSize: 42, color: 'var(--agv-text-secondary)' }} />} description="还没有访问令牌，点击上方创建" />

  const renderScopes = (scopes: string[]) => <details className="token-scope-detail">
    <summary>{scopes.length} 项权限</summary>
    <Space size={[4, 4]} wrap>{scopes.map(value => <Tag key={value}>{scopeOptions.find(([key]) => key === value)?.[1] ?? value}</Tag>)}</Space>
  </details>

  const mcpUrl = `${window.location.origin}/api/ai/mcp/`

  const hermesConfig = `mcp_servers:
  agv:
    url: "${mcpUrl}"
    headers:
      Authorization: "Bearer \${AGV_AGENT_TOKEN}"`
  const restUrl = `${window.location.origin}/api/agent/tools`

  return (
    <div className="settings-work-page">
      <WorkPageHeader title={NAV_LABEL['/pm/ai-tokens']} description={NAV_DESCRIPTION['/pm/ai-tokens']}
        primary={canManage && <Button type="primary" icon={<PlusOutlined />} onClick={openCreate} disabled={!canManage || loading || saving}>创建令牌</Button>}
        meta={`${rows.filter(row => row.is_active).length} 个启用令牌 · ${rows.length} 个总计`} />


      <Alert type="info" showIcon message={<>只读接入，用于整理文字<InfoHint text="外部工具可读取获授权的资料清单、车辆进度表和本周待交资料；保密范围与当前账号一致。工具不修改状态、检查、资料、权限或分享，也不生成数量计划和按天排程。" /></>} style={{ marginBottom: 16 }} />
      <Card size="small" title="AI 用量预算" style={{ marginBottom: 16 }}>
        {budget ? <Space direction="vertical">
          <Typography.Text>{budget.usage.month} · 系统模型调用 {budget.usage.requests} 次 / {budget.limits.requests || '不限'} · 估算用量 {budget.usage.tokens} / {budget.limits.tokens || '不限'} tokens</Typography.Text>
          {budget.blocked && <Alert type="warning" showIcon message={budget.reason} />}
          <Typography.Paragraph type="secondary" style={{ margin: 0 }}>限额由部署配置维护，达到上限后停止系统模型调用。此处保留已有用量记录；外部 Agent 的模型费用由其提供方计量，读取项目数据不会触发系统模型调用。</Typography.Paragraph>
        </Space> : <Typography.Text type="secondary">预算信息尚未读取，请刷新后核对。</Typography.Text>}
      </Card>
      <WorkSection title="访问令牌" description="令牌绑定账号，只能访问该账号可见的项目；停用后立即失效。">
        {isMobile ? (
          rows.length === 0 ? emptyNode : (
            <div className="mobile-card-list">
              {rows.map((row) => (
                <Card key={row.id} size="small">
                  <Space direction="vertical" size={6} style={{ width: '100%' }}>
                    <div className="mobile-card-title">{row.name}</div>
                    <div className="mobile-card-row">
                      <span className="mobile-card-label">绑定账号</span>
                      <span className="mobile-card-value">{row.user_name}</span>
                    </div>
                    <div className="mobile-card-row">
                      <span className="mobile-card-label">令牌标识</span>
                      <span className="mobile-card-value"><Typography.Text code>{row.token_prefix}…</Typography.Text></span>
                    </div>
                    <div className="mobile-card-row">
                      <span className="mobile-card-label">权限</span>
                      <span className="mobile-card-value">{renderScopes(row.scopes)}</span>
                    </div>
                    <div className="mobile-card-row">
                      <span className="mobile-card-label">过期时间</span>
                      <span className="mobile-card-value">{row.expires_at ? formatDateTime(row.expires_at) : '长期'}</span>
                      <span className="mobile-card-label">最近使用</span>
                      <span className="mobile-card-value">{row.last_used_at ? formatDateTime(row.last_used_at) : '-'}</span>
                    </div>
                    <div className="mobile-card-actions">
                      <SwitchTouch id={`token-switch-${row.id}`} checked={row.is_active} disabled={saving || loading} onChange={(checked) => toggle(row, checked)} />
                      <Popconfirm title="停用这个 Token？停用后立即失效" onConfirm={() => revoke(row.id)}>
                        <Button className="touch-target" danger type="link" disabled={saving || loading || !row.is_active}>停用</Button>
                      </Popconfirm>
                    </div>
                  </Space>
                </Card>
              ))}
            </div>
          )
        ) : (
        <Table<TokenRow>
          scroll={{ x: 'max-content' }}
          rowKey="id"
          loading={loading}
          dataSource={rows}
          pagination={false}
          locale={{ emptyText: emptyNode }}
          columns={[
            { title: '名称', dataIndex: 'name', render: (v: string) => <Typography.Text strong>{v}</Typography.Text> },
            { title: '绑定账号', dataIndex: 'user_name', width: 120 },
            { title: '令牌标识', dataIndex: 'token_prefix', width: 130, render: (v: string) => <Typography.Text code>{v}…</Typography.Text> },
            {
              title: '权限', dataIndex: 'scopes',
              render: (scopes: string[]) => renderScopes(scopes),
            },
            { title: '过期时间', dataIndex: 'expires_at', width: 150, render: (v: string) => v ? formatDateTime(v) : '长期' },
            { title: '最近使用', dataIndex: 'last_used_at', width: 150, render: (v: string) => v ? formatDateTime(v) : '-' },
            {
              title: '启用', dataIndex: 'is_active', width: 80,
              render: (v: boolean, row) => <Switch size="small" checked={v} disabled={saving || loading} onChange={(checked) => toggle(row, checked)} />,
            },
            {
              title: '操作', width: 90,
              render: (_: any, row) => (
                <Popconfirm title="停用这个 Token？停用后立即失效" onConfirm={() => revoke(row.id)}>
                  <Button size="small" danger type="link" disabled={saving || loading || !row.is_active}>停用</Button>
                </Popconfirm>
              ),
            },
          ]}
        />
        )}
      </WorkSection>
      <details className="work-detail-summary settings-detail">
        <summary>连接外部助手与权限说明</summary>
      <div className="agent-connection-grid">
        <Card title={<><ApiOutlined /> 连接方式</>} size="small">
          <Typography.Paragraph>1. 创建 Token 并绑定账号。助手只能访问该账号可见的项目。</Typography.Paragraph>
          <Typography.Paragraph>2. 在助手中添加 Streamable HTTP MCP 服务：</Typography.Paragraph>
          <Typography.Paragraph copyable={{ text: mcpUrl }} code>{mcpUrl}</Typography.Paragraph>
          <Typography.Paragraph>3. 设置请求头 <Typography.Text code>Authorization: Bearer &lt;Token&gt;</Typography.Text>，重新连接后自动发现工具。</Typography.Paragraph>
          <Typography.Text type="secondary">支持在当前账号与令牌范围内读取项目工作、资料清单、车辆进度、人员、问题和物品等事实；实际工具以服务端目录为准。</Typography.Text>
        </Card>
        <Card title="Hermes 配置" size="small">
          <Typography.Paragraph>把以下配置加入 <Typography.Text code>~/.hermes/config.yaml</Typography.Text>，在 Hermes 环境中设置 <Typography.Text code>AGV_AGENT_TOKEN</Typography.Text>。</Typography.Paragraph>
          <pre className="agent-config">{hermesConfig}</pre>
          <Typography.Paragraph copyable={{ text: hermesConfig }}>复制配置</Typography.Paragraph>
          <Typography.Text type="secondary">通用 HTTP 客户端也可调用工具目录：</Typography.Text>
          <Typography.Paragraph copyable={{ text: restUrl }} code>{restUrl}</Typography.Paragraph>
        </Card>
      </div>
      <Alert type="info" showIcon style={{ marginBottom: 16 }} message={<>外部助手只读<InfoHint text="助手可读取获授权的事实并整理文字建议。业务修改由有权限的人在对应页面核对后操作；令牌不会取得写入能力，也不自动增加既有权限。" /></>} />
      </details>

      <Modal title="创建访问令牌" open={open} onCancel={closeCreate} cancelButtonProps={{ disabled: saving }} closable={!saving} maskClosable={!saving} keyboard={!saving} onOk={() => form.submit()} okText="创建" confirmLoading={saving} okButtonProps={{ disabled: !canManage }}>
        <Form form={form} disabled={!canManage || saving} layout="vertical" onFinish={create} initialValues={{ scopes: scopeOptions.map(([value]) => value).filter(value => value.endsWith(':read')) }}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="例如：项目助手（只读）" />
          </Form.Item>
          <Form.Item name="user_id" label="绑定系统账号" rules={[{ required: true, message: '请选择账号' }]}>
            <Select showSearch optionFilterProp="label" placeholder="AI 以该账号的可见范围执行"
              options={users.map((u) => ({ value: u.id, label: `${u.display_name}（${u.username}）` }))} />
          </Form.Item>
          <Form.Item name="scopes" label="权限范围" rules={[{ required: true, message: '请至少选择一个权限' }]}>
            <Checkbox.Group className="agent-scope-options" options={scopeOptions.map(([value, label]) => ({ value, label }))} />
          </Form.Item>
          <Form.Item name="expires_at" label="过期时间（可选）">
            <DatePicker showTime style={{ width: '100%' }} placeholder="留空则长期有效" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title="访问令牌已创建（只显示一次）" open={!!createdToken} footer={null} onCancel={() => setCreatedToken('')}>
        <Alert type="warning" showIcon message="请立即保存；关闭后无法再次查看完整 Token" style={{ marginBottom: 12 }} />
        <Typography.Paragraph copyable={{ text: createdToken }} code style={{ wordBreak: 'break-all' }}>{createdToken}</Typography.Paragraph>
        <Button icon={<CopyOutlined />} onClick={async () => { try { await navigator.clipboard.writeText(createdToken); message.success('已复制') } catch { message.error('复制失败，请手动复制 Token') } }}>复制令牌</Button>
      </Modal>
    </div>
  )
}
