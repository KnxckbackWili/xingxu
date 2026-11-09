import { useAuth } from '../../stores/auth'
import { hasSystemPermission } from '../../constants/systemPermissions'
import { WorkPageHeader } from '../../components/WorkPage'
import { NAV_LABEL, NAV_DESCRIPTION } from '../../constants/nav'
import './SettingsPages.css'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Tag, Button, Modal, Form, Input, Select, message, Popconfirm, Empty, Pagination } from 'antd'
import {
  PlusOutlined, EditOutlined, StopOutlined, PlayCircleOutlined, UserOutlined, SearchOutlined,
} from '@ant-design/icons'
import { userApi } from '../../api'
import { errMsg } from '../../api/client'
import { useSubmitLock } from '../../hooks/useSubmitLock'
import { ROLE_NAME } from '../../constants/roles'
import { IconAction } from '../../components/IconAction'

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

const ROLE_COLOR: Record<string, string> = { admin: 'red', employee: 'blue' }

export default function UsersPage() {
  const { user: currentUser } = useAuth()
  const isAdmin = currentUser?.role === 'admin'
  const canManage = hasSystemPermission(currentUser, 'system.users.manage')
  const canEditAccount = (target: UserRow) => canManage && (isAdmin || target.role !== 'admin')
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
    }).sort((a, b) => Number(b.is_active) - Number(a.is_active))
  }, [users, keyword, roleFilter, activeFilter])

  useEffect(() => { setUserPage(1) }, [keyword, roleFilter, activeFilter])

  const USER_PAGE_SIZE = 30
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
        primary={canManage && <Button disabled={saving || !!loadError} type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); form.resetFields(); setModalOpen(true) }}>新建用户</Button>} />

      {loadError && <Alert type="error" showIcon message="账号加载失败" description={loadError} action={<Button onClick={() => void load()}>重试</Button>} style={{ marginBottom: 12 }} />}
      {/* One list for desktop and phone: who, role, login name; edit and enable/disable on the right. Disabled accounts sink to the bottom. */}
      <div className="user-toolbar">
        <Input allowClear prefix={<SearchOutlined />} aria-label="搜索账号" placeholder="姓名、账号、电话或邮箱" value={keyword} onChange={(e) => setKeyword(e.target.value)} className="user-search" />
        <Select allowClear placeholder="全部角色" aria-label="按角色筛选" value={roleFilter || undefined} onChange={(v) => setRoleFilter(v ?? '')}
          style={{ minWidth: 120 }} options={Object.entries(ROLE_NAME).map(([v, label]) => ({ value: v, label }))} />
        <span className="user-count">{filteredUsers.length} 人</span>
      </div>
      {loading && !users.length ? <Empty description="正在读取账号…" /> : filteredUsers.length === 0
        ? <Empty image={hasUserFilters ? Empty.PRESENTED_IMAGE_SIMPLE : <UserOutlined style={{ fontSize: 42, color: '#b6c2be' }} />} description={hasUserFilters ? '当前筛选范围没有账号' : '还没有用户账号'}>
            {hasUserFilters && <Button onClick={clearUserFilters}>清空筛选</Button>}
          </Empty>
        : <>
          <ul className="user-list" aria-label="账号名单">{shownUsers.map(u => <li key={u.id} className={u.is_active ? '' : 'is-inactive'}>
            <span className="user-avatar" aria-hidden>{(u.display_name || u.username).slice(0, 1)}</span>
            <span className="user-main"><strong>{u.display_name}</strong>{!u.is_active && <Tag>停用</Tag>}<small>{[u.username, u.phone].filter(Boolean).join(' · ')}</small></span>
            <Tag color={ROLE_COLOR[u.role]} className="user-role">{ROLE_NAME[u.role] ?? u.role}</Tag>
            <span className="row-icon-actions">
              <IconAction label="编辑" icon={<EditOutlined />} disabled={!canEditAccount(u)} onClick={() => openEdit(u)} />
              <Popconfirm title={u.is_active ? `停用「${u.display_name}」？` : `启用「${u.display_name}」？`} onConfirm={() => toggleActive(u)} disabled={!canEditAccount(u) || saving || !!loadError || u.username === 'admin'}>
                <IconAction label={u.is_active ? '停用' : '启用'} danger={u.is_active} icon={u.is_active ? <StopOutlined /> : <PlayCircleOutlined />} disabled={!canEditAccount(u) || saving || !!loadError || u.username === 'admin'} />
              </Popconfirm>
            </span>
          </li>)}</ul>
          {USER_PAGE_SIZE < filteredUsers.length && <Pagination simple size="small" current={userPage} pageSize={USER_PAGE_SIZE} total={filteredUsers.length} onChange={setUserPage} style={{ marginTop: 12, textAlign: 'right' }} />}
        </>}

      {/* 用户表单 */}
      <Modal title={editing ? `编辑用户：${editing.display_name}` : '新建用户'} open={modalOpen} onCancel={() => { if (!saving) setModalOpen(false) }} confirmLoading={saving} okButtonProps={{ disabled: !canManage || !!loadError || (!!editing && !canEditAccount(editing)) }} onOk={() => form.submit()} okText="保存" width={520}>
        <Form form={form} layout="vertical" disabled={!canManage || saving} onFinish={submit}>
          {!editing && (
            <>
              <Form.Item name="username" label="登录用户名" tooltip="留空则用姓名作为登录用户名">
                <Input placeholder="留空 = 用姓名登录" autoComplete="off" />
              </Form.Item>
              <Form.Item name="password" label="初始密码" rules={[{ required: true, min: 6, message: '至少 6 位' }]}>
                <Input.Password placeholder="至少 6 位" autoComplete="new-password" />
              </Form.Item>
            </>
          )}
          <Form.Item name="display_name" label="姓名" rules={[{ required: true, message: '请输入姓名' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="role" label="账号类型" initialValue="employee" rules={[{ required: true }]}
            extra="员工可以做全部项目工作；系统管理员另外管理账号、模板、车型、备份和系统设置。">
            <Select aria-label="账号类型" disabled={!canManage || saving}
              options={[{ value: 'employee', label: '员工' }, { value: 'admin', label: '系统管理员' }]} />
          </Form.Item>
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
