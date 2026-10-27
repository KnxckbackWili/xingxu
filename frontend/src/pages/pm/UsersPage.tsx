import { Link } from 'react-router-dom'
import { useAuth } from '../../stores/auth'
import { hasSystemPermission } from '../../constants/systemPermissions'
import { WorkPageHeader, WorkSection } from '../../components/WorkPage'
import { NAV_LABEL, NAV_DESCRIPTION } from '../../constants/nav'
import './SettingsPages.css'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Card, Table, Tag, Button, Modal, Form, Input, Select, message, Space, Typography, Popconfirm, Empty, Pagination } from 'antd'
import {
  PlusOutlined, EditOutlined, StopOutlined, PlayCircleOutlined, UserOutlined,
} from '@ant-design/icons'
import { userApi, ROLE_MAP } from '../../api'
import { errMsg } from '../../api/client'
import { useMediaQuery } from '../../hooks/useMediaQuery'
import { useSubmitLock } from '../../hooks/useSubmitLock'
import { MEDIA_QUERY } from '../../constants/breakpoints'
import { ROLE_NAME } from '../../constants/roles'

interface UserRow {
  id: string
  username: string
  display_name: string
  role: string
  phone: string
  email: string
  is_active: boolean
  created_at: string | null
}

const ROLE_COLOR: Record<string, string> = {
  admin: 'red', director: 'magenta', lead: 'purple', pm: 'blue',
  technician: 'cyan', worker: 'green', intern: 'default', readonly: 'default',
}

export default function UsersPage() {
  const { user: currentUser } = useAuth()
  const isAdmin = currentUser?.role === 'admin'
  const canManage = hasSystemPermission(currentUser, 'system.users.manage')
  const canEditAccount = (target: UserRow) => canManage && (isAdmin || target.role !== 'admin')
  const isMobile = useMediaQuery(MEDIA_QUERY.mobile)
  const [users, setUsers] = useState<UserRow[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [loadError, setLoadError] = useState('')
  const loadSequence = useRef(0)
  const lock = useSubmitLock()
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<UserRow | null>(null)
  const [form] = Form.useForm()
  const [keyword, setKeyword] = useState('')
  const [userPage, setUserPage] = useState(1)
  const [roleFilter, setRoleFilter] = useState<string>('')
  const [activeFilter, setActiveFilter] = useState<string>('')

  const load = async () => {
    const sequence = ++loadSequence.current
    setLoading(true)
    try {
      const u = await userApi.list()
      if (sequence !== loadSequence.current) return
      setUsers(u)
      setLoadError('')
    } catch (e) {
      if (sequence === loadSequence.current) setLoadError(errMsg(e))
    } finally {
      if (sequence === loadSequence.current) setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    return () => { loadSequence.current += 1 }
  }, [])

  const filteredUsers = useMemo(() => {
    const q = keyword.trim().toLowerCase()
    return users.filter((u) => {
      if (q && ![u.display_name, u.username, u.phone, u.email].some((v) => (v ?? '').toLowerCase().includes(q))) return false
      if (roleFilter && u.role !== roleFilter) return false
      if (activeFilter && String(u.is_active) !== activeFilter) return false
      return true
    })
  }, [users, keyword, roleFilter, activeFilter])

  useEffect(() => { setUserPage(1) }, [keyword, roleFilter, activeFilter])

  const USER_PAGE_SIZE = 12
  const shownUsers = filteredUsers.slice((userPage - 1) * USER_PAGE_SIZE, userPage * USER_PAGE_SIZE)
  const hasUserFilters = Boolean(keyword || roleFilter || activeFilter)
  const clearUserFilters = () => { setKeyword(''); setRoleFilter(''); setActiveFilter('') }

  const openEdit = (user: UserRow) => {
    if (saving || !canEditAccount(user)) return
    form.resetFields()
    form.setFieldsValue({
      display_name: user.display_name, role: user.role,
      phone: user.phone, email: user.email, password: undefined,
    })
    setEditing(user)
    setModalOpen(true)
  }

  const submit = async (values: any) => {
    if (!canManage || (editing && !canEditAccount(editing))) return
    if (loadError || !lock.tryAcquire()) return
    setSaving(true)
    try {
      const rest = { ...values }
      if (!isAdmin) { if (editing) delete rest.role; else rest.role = 'worker' }
      if (editing && !rest.password) delete rest.password
      if (!editing && !rest.username?.trim()) {
        rest.username = rest.display_name?.trim()  // 登录用户名留空 = 用姓名
      }
      if (editing) {
        await userApi.update(editing.id, rest)
        message.success('用户已更新')
      } else {
        await userApi.create(rest)
        message.success('用户已创建')
      }
      setModalOpen(false)
      await load()
    } catch (e) {
      message.error(errMsg(e))
    } finally { setSaving(false); lock.release() }
  }

  const toggleActive = async (u: UserRow) => {
    if (!canEditAccount(u)) return
    if (loadError || !lock.tryAcquire()) return
    setSaving(true)
    try {
      await userApi.update(u.id, { is_active: !u.is_active })
      message.success(u.is_active ? '账号已停用' : '账号已启用')
      await load()
    } catch (e) {
      message.error(errMsg(e))
    } finally { setSaving(false); lock.release() }
  }


  return (
    <div className="settings-work-page">
      <WorkPageHeader title={NAV_LABEL['/pm/users']} description={NAV_DESCRIPTION['/pm/users']}
        meta={`${users.filter((u) => u.is_active).length} 个启用账号 · 共 ${users.length} 个账号`}
        primary={canManage && <Button disabled={saving || !!loadError} type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); form.resetFields(); setModalOpen(true) }}>新建用户</Button>} tools={isAdmin && <Link to="/pm/permissions"><Button>管理成员权限</Button></Link>} />

      {loadError && <Alert type="error" showIcon message="账号加载失败" description={loadError} action={<Button onClick={() => void load()}>重试</Button>} style={{ marginBottom: 12 }} />}
      <WorkSection title="账号名单" description="账号决定登录与角色；项目成员在各项目的“人员”中管理。" filters={
              <Space wrap className="user-filter-bar">
                <Input.Search allowClear placeholder="搜索姓名/账号/电话/邮箱" value={keyword}
                  onChange={(e) => setKeyword(e.target.value)} style={{ width: 240 }} />
                <Select allowClear placeholder="角色" aria-label="按角色筛选" value={roleFilter || undefined} onChange={(v) => setRoleFilter(v ?? '')}
                  style={{ width: 120 }} options={Object.entries(ROLE_NAME).map(([v, label]) => ({ value: v, label }))} />
                <Select allowClear placeholder="账号状态" aria-label="按账号状态筛选" value={activeFilter || undefined} onChange={(v) => setActiveFilter(v ?? '')}
                  style={{ width: 110 }} options={[{ label: '已启用', value: 'true' }, { label: '已停用', value: 'false' }]} />
              </Space>
            } extra={<Typography.Text type="secondary">{filteredUsers.length} 人</Typography.Text>}>
          {isMobile ? (
            filteredUsers.length === 0
              ? (
                <Empty
                  image={hasUserFilters ? Empty.PRESENTED_IMAGE_SIMPLE : <UserOutlined style={{ fontSize: 42, color: '#b6c2be' }} />}
                  description={hasUserFilters ? '当前筛选范围没有账号' : '还没有用户账号'}
                >
                  {hasUserFilters && <Button className="touch-target" onClick={clearUserFilters}>清空筛选</Button>}
                </Empty>
              )
              : (
                <>
                  <div className="mobile-card-list">
                    {shownUsers.map((u) => {
                      return (
                        <Card key={u.id} size="small">
                          <Space direction="vertical" size={6} style={{ width: '100%' }}>
                            <div className="mobile-card-row">
                              <span className="mobile-card-title-sm">{u.display_name}</span>
                              {!u.is_active && <Tag color="default">停用</Tag>}
                            </div>
                            <div className="mobile-card-row">
                              <span className="mobile-card-label">角色</span>
                              <span className="mobile-card-value"><Tag color={ROLE_COLOR[u.role]}>{ROLE_NAME[u.role] ?? u.role}</Tag></span>
                            </div>
                            <div className="mobile-card-row">
                              <span className="mobile-card-label">用户名</span>
                              <span className="mobile-card-value">{u.username}</span>
                              <span className="mobile-card-label">电话</span>
                              <span className="mobile-card-value">{u.phone || '-'}</span>
                            </div>
                            <div className="mobile-card-actions">
                              <Button className="touch-target" type="link" icon={<EditOutlined />} disabled={!canEditAccount(u)} onClick={() => openEdit(u)}>编辑</Button>
                              <Popconfirm title={u.is_active ? `停用「${u.display_name}」？` : `启用「${u.display_name}」？`} onConfirm={() => toggleActive(u)} disabled={!canEditAccount(u) || saving || !!loadError || u.username === 'admin'}>
                                <Button className="touch-target" type="link" icon={u.is_active ? <StopOutlined /> : <PlayCircleOutlined />} style={{ color: u.is_active ? 'var(--agv-danger)' : 'var(--agv-success)' }} disabled={!canEditAccount(u) || saving || !!loadError || u.username === 'admin'}>
                                  {u.is_active ? '停用' : '启用'}
                                </Button>
                              </Popconfirm>
                            </div>
                          </Space>
                        </Card>
                      )
                    })}
                  </div>
                  {USER_PAGE_SIZE < filteredUsers.length && (
                    <Pagination simple size="small" current={userPage} pageSize={USER_PAGE_SIZE} total={filteredUsers.length} onChange={setUserPage} style={{ marginTop: 12, textAlign: 'right' }} />
                  )}
                </>
              )
          ) : (
          <Table<UserRow>
            loading={loading}
            rowKey="id"
            dataSource={filteredUsers}
            scroll={{ x: 'max-content' }}
            pagination={{
              defaultPageSize: 12,
              pageSizeOptions: [12, 24, 48],
              showSizeChanger: true,
              showQuickJumper: filteredUsers.length > 48,
              showTotal: (total, range) => `${range[0]}-${range[1]} / 共 ${total} 人`,
            }}
            size="small"
            columns={[
              {
                title: '姓名',
                dataIndex: 'display_name',
                render: (v: string, u) => (
                  <Space size={6}>
                    <Typography.Text strong>{v}</Typography.Text>
                    {!u.is_active && <Tag color="default">停用</Tag>}
                  </Space>
                ),
              },
              {
                title: '角色',
                dataIndex: 'role',
                width: 130,
                render: (r: string) => <Tag color={ROLE_COLOR[r]}>{ROLE_NAME[r] ?? r}</Tag>,
              },
              { title: '用户名', dataIndex: 'username', width: 100, responsive: ['md'], render: (v: string) => <Typography.Text type="secondary">{v}</Typography.Text> },
              { title: '电话', dataIndex: 'phone', width: 120, responsive: ['lg'], render: (v: string) => v || '-' },
              {
                title: '操作',
                width: 150,
                render: (_: any, u: UserRow) => (
                  <Space size={0}>
                    <Button type="link" size="small" icon={<EditOutlined />} disabled={!canEditAccount(u)} onClick={() => openEdit(u)}>
                      编辑
                    </Button>
                    <Popconfirm title={u.is_active ? `停用「${u.display_name}」？` : `启用「${u.display_name}」？`} onConfirm={() => toggleActive(u)} disabled={!canEditAccount(u) || saving || !!loadError || u.username === 'admin'}>
                      <Button type="link" size="small" icon={u.is_active ? <StopOutlined /> : <PlayCircleOutlined />} style={{ color: u.is_active ? '#ad2102' : '#237804' }} disabled={!canEditAccount(u) || saving || !!loadError || u.username === 'admin'}>
                        {u.is_active ? '停用' : '启用'}
                      </Button>
                    </Popconfirm>
                  </Space>
                ),
              },
            ]}
          />
          )}
      </WorkSection>

      {/* 用户表单 */}
      <Modal title={editing ? `编辑用户：${editing.display_name}` : '新建用户'} open={modalOpen} onCancel={() => { if (!saving) setModalOpen(false) }} confirmLoading={saving} okButtonProps={{ disabled: !canManage || !!loadError || (!!editing && !canEditAccount(editing)) }} onOk={() => form.submit()} okText="保存" width={520}>
        <Form form={form} layout="vertical" disabled={!canManage || saving} onFinish={submit}>
          {!editing && (
            <>
              <Form.Item name="username" label="登录用户名" tooltip="留空则用姓名作为登录用户名">
                <Input placeholder="留空 = 用姓名登录" autoComplete="off" />
              </Form.Item>
              <Form.Item name="permission_preset" label="预设角色" initialValue="worker">
                <Select aria-label="预设角色" onChange={value => form.setFieldValue('role', value)} options={[
                  ...(isAdmin ? [{ value: 'pm', label: '项目经理' }] : []),
                  { value: 'worker', label: '实施工程师' }, { value: 'readonly', label: '只读' },
                ]} />
              </Form.Item>
              <Form.Item name="password" label="初始密码" rules={[{ required: true, min: 6, message: '至少 6 位' }]}>
                <Input.Password placeholder="至少 6 位" autoComplete="new-password" />
              </Form.Item>
            </>
          )}
          <Form.Item name="display_name" label="姓名" rules={[{ required: true, message: '请输入姓名' }]}>
            <Input />
          </Form.Item>
          <details className="work-detail-summary"><summary>高级：账号角色与逐项权限</summary>
          <Typography.Paragraph type="secondary">通常使用预设角色即可。只读账号不能通过单项授权改为可写，需要先调整账号角色。</Typography.Paragraph>
          <Form.Item name="role" label="角色（职级）" extra={!isAdmin ? "角色和管理员账号仅由系统管理员维护；受托账号只能创建实施工程师。" : undefined} initialValue="worker" rules={[{ required: true }]}>
            <Select aria-label="高级账号角色" disabled={!isAdmin || !canManage || saving} onChange={() => form.setFieldValue('permission_preset', undefined)}
              options={Object.entries({ ...ROLE_MAP, ...(editing && !ROLE_MAP[editing.role] ? { [editing.role]: ROLE_NAME[editing.role] ?? editing.role } : {}) }).map(([v, l]) => ({ label: ROLE_NAME[v] ?? l, value: v }))}
            />
          </Form.Item>
          {isAdmin && <Link to="/pm/permissions">高级：逐项权限设置</Link>}
          </details>
          {editing && (
            <Form.Item name="password" label="重置密码（留空不修改）">
              <Input.Password placeholder="留空则不修改" autoComplete="new-password" />
            </Form.Item>
          )}
          <Form.Item name="phone" label="电话"><Input /></Form.Item>
          <Form.Item name="email" label="邮箱"><Input /></Form.Item>
        </Form>
      </Modal>

    </div>
  )
}
