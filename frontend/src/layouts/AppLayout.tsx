import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { Dropdown, Form, Input, Modal, message } from 'antd'
import { AppstoreOutlined, HistoryOutlined, HomeOutlined, KeyOutlined, LogoutOutlined, MoonOutlined, SettingOutlined, SunOutlined } from '@ant-design/icons'
import { api, errMsg } from '../api/client'
import BrandMark from '../components/BrandMark'
import { PersonAvatar } from '../components/Person'
import { useAuth } from '../stores/auth'
import { useThemeStore } from '../stores/theme'
import { APP_VERSION } from '../version'
import './AppLayout.css'

function PasswordModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [form] = Form.useForm()
  const [busy, setBusy] = useState(false)
  const submit = async () => {
    const values = await form.validateFields()
    setBusy(true)
    try {
      await api.put('/auth/password', { old_password: values.old_password, new_password: values.new_password })
      message.success('密码已修改，其他设备需要重新登录')
      form.resetFields()
      onClose()
    } catch (failure) {
      message.error(errMsg(failure))
    } finally {
      setBusy(false)
    }
  }
  return <Modal open={open} title="修改密码" okText="保存" cancelText="取消" confirmLoading={busy} onOk={() => void submit()} onCancel={onClose} destroyOnClose>
    <Form form={form} layout="vertical" preserve={false}>
      <Form.Item name="old_password" label="现在的密码" rules={[{ required: true, message: '请输入现在的密码' }]}><Input.Password autoComplete="current-password" /></Form.Item>
      <Form.Item name="new_password" label="新密码" extra="至少 8 位" rules={[{ required: true, min: 8, message: '新密码至少 8 位' }]}><Input.Password autoComplete="new-password" /></Form.Item>
    </Form>
  </Modal>
}

export default function AppLayout() {
  const { user, logout } = useAuth()
  const { mode, toggle } = useThemeStore()
  const navigate = useNavigate()
  const [password, setPassword] = useState(false)
  const links = [
    { to: '/', label: '项目', icon: <HomeOutlined />, end: true },
    { to: '/templates', label: '模板', icon: <AppstoreOutlined /> },
    { to: '/history', label: '操作记录', icon: <HistoryOutlined /> },
    ...(user?.role === 'admin' ? [{ to: '/settings', label: '设置', icon: <SettingOutlined /> }] : []),
  ]
  const signOut = async () => { await logout(); navigate('/login', { replace: true }) }
  return <div className="shell">
    <header className="shell-bar">
      <NavLink to="/" className="shell-brand" aria-label="行序，回到项目"><BrandMark /></NavLink>
      <nav className="shell-nav" aria-label="主导航">
        {links.map((link) => <NavLink key={link.to} to={link.to} end={link.end} className={({ isActive }) => (isActive || (link.to === '/' && location.pathname.startsWith('/projects')) ? 'is-active' : '')}>{link.icon}<span>{link.label}</span></NavLink>)}
      </nav>
      <div className="shell-right">
        <button type="button" className="shell-icon" aria-label={mode === 'dark' ? '切换到浅色' : '切换到深色'} onClick={toggle}>{mode === 'dark' ? <SunOutlined /> : <MoonOutlined />}</button>
        <Dropdown trigger={['click']} placement="bottomRight" menu={{ items: [
          { key: 'who', disabled: true, label: <span>{user?.display_name}（{user?.role === 'admin' ? '系统管理员' : '员工'}）<br /><small>{user?.username} · 行序 {APP_VERSION}</small></span> },
          { type: 'divider' },
          { key: 'password', icon: <KeyOutlined />, label: '修改密码', onClick: () => setPassword(true) },
          { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', onClick: () => void signOut() },
        ] }}><button type="button" className="shell-user" aria-label={`账号 ${user?.display_name ?? ''}`}><PersonAvatar name={user?.display_name} large /></button></Dropdown>
      </div>
    </header>
    <main className="shell-main"><Outlet /></main>
    <PasswordModal open={password} onClose={() => setPassword(false)} />
  </div>
}
