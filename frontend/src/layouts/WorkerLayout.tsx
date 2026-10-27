import { Layout, Avatar, Dropdown, Typography, Modal, Button, Drawer, Input, type InputRef } from 'antd'
import { CalendarOutlined, ProjectOutlined, WarningOutlined, UserOutlined, LogoutOutlined, SettingOutlined, BulbOutlined, CommentOutlined, MenuOutlined, SearchOutlined } from '@ant-design/icons'
import { useEffect, useRef, useState } from 'react'
import ChangePasswordModal from '../components/ChangePasswordModal'
import TwoFactorModal from '../components/TwoFactorModal'
import BrandMark from '../components/BrandMark'
import { getQueue } from '../offline/queue'
import { Link, Outlet, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../stores/auth'
import { useThemeStore } from '../stores/theme'
import NotificationBell from '../components/NotificationBell'
import { canAccessNav, NAV_LABEL, systemHomeRoute } from '../constants/nav'
import { MENU_GROUPS } from './pmMenu'
import { useDrawerReturnFocus } from '../hooks/useDrawerReturnFocus'
import './navigationShell.css'

const { Header, Content } = Layout

// 现场日常入口；消息保留在顶栏铃铛，管理能力进入设置。
const BASE_MENU = [
  { key: '/worker/week', icon: <CalendarOutlined />, label: NAV_LABEL['/worker/week'] },
  { key: '/worker/projects', icon: <ProjectOutlined />, label: NAV_LABEL['/worker/projects'] },
  { key: '/worker/issues', icon: <WarningOutlined />, label: NAV_LABEL['/worker/issues'] },
  { key: '/worker/my', icon: <UserOutlined />, label: NAV_LABEL['/worker/my'] },
]

export default function WorkerLayout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [pwdOpen, setPwdOpen] = useState(false)
  const [mfaOpen, setMfaOpen] = useState(false)
  const [accountMenuOpen, setAccountMenuOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [search, setSearch] = useState('')
  const menuTrigger = useRef<HTMLButtonElement>(null)
  const menuSearch = useRef<InputRef>(null)
  const restoreFocus = useRef(false)
  const accountTrigger = useRef<HTMLButtonElement>(null)
  const closeMenu = () => { restoreFocus.current = true; setMenuOpen(false) }
  const openMenu = () => { restoreFocus.current = false; setSearch(''); setMenuOpen(true) }
  useDrawerReturnFocus(menuOpen, restoreFocus, 'global-functions-drawer', () => menuTrigger.current)
  useEffect(() => { setMenuOpen(false) }, [location.pathname, location.search])
  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.altKey || !(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'k') return
      const target = event.target instanceof Element ? event.target : document.activeElement
      if (target?.closest('input, textarea, select, [contenteditable="true"], .ant-modal')) return
      event.preventDefault()
      openMenu()
    }
    window.addEventListener('keydown', shortcut)
    return () => window.removeEventListener('keydown', shortcut)
  }, [])
  const term = search.trim().toLocaleLowerCase()
  const groups = MENU_GROUPS(user).map(group => ({ ...group, children: group.children.filter(item =>
    !term || `${item.label} ${item.description} ${item.aliases.join(' ')}`.toLocaleLowerCase().includes(term)) })).filter(group => group.children.length)
  useEffect(() => {
    if (!accountMenuOpen) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      setAccountMenuOpen(false)
      accountTrigger.current?.focus()
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [accountMenuOpen])
  const themeMode = useThemeStore((state) => state.mode)
  const toggleTheme = useThemeStore((state) => state.toggle)
  const MENU = BASE_MENU.filter(item => canAccessNav(item.key, user))
  const selected = MENU.find((m) => location.pathname === m.key || location.pathname.startsWith(`${m.key}/`))?.key

  return (
    <Layout className="worker-shell">
      <a href="#main-content" className="skip-to-content">跳到主要内容</a>
      <Header className="worker-header">
        <button className="worker-brand" type="button" onClick={() => navigate(systemHomeRoute(user))} aria-label="行序，返回工作台">
          <BrandMark />
        </button>
        <div className="worker-header-actions">
          <Button ref={menuTrigger} type="text" icon={<MenuOutlined />} aria-label="设置" aria-haspopup="dialog" aria-expanded={menuOpen} onClick={openMenu} />
          <Button
            type="text"
            icon={<BulbOutlined />}
            aria-label={themeMode === 'dark' ? '切换到浅色模式' : '切换到深色模式'}
            title={themeMode === 'dark' ? '切换到浅色模式' : '切换到深色模式'}
            onClick={toggleTheme}
          />
          <NotificationBell />
        <Dropdown
          trigger={['click']}
          open={accountMenuOpen}
          onOpenChange={setAccountMenuOpen}
          menu={{
            items: [
              ...(canAccessNav('/worker/feedback', user) ? [{ key: 'feedback', icon: <CommentOutlined />, label: '使用反馈', onClick: () => { setAccountMenuOpen(false); navigate('/worker/feedback') } }] : []),
              ...(user?.role === 'admin' ? [{ key: 'permissions', icon: <SettingOutlined />, label: '成员权限', onClick: () => { setAccountMenuOpen(false); navigate('/pm/permissions') } }] : []),
              ...((['admin', 'pm'].includes(user?.role ?? '') || user?.two_factor_enabled) ? [{ key: 'mfa', icon: <SettingOutlined />, label: '二次验证', onClick: () => { setAccountMenuOpen(false); setMfaOpen(true) } }] : []),
              { key: 'pwd', icon: <SettingOutlined />, label: '修改密码', onClick: () => { setAccountMenuOpen(false); setPwdOpen(true) } },
              {
                key: 'logout',
                icon: <LogoutOutlined />,
                label: '退出登录',
                onClick: () => {
                  setAccountMenuOpen(false)
                  const pending = getQueue().length
                  if (pending > 0) {
                    Modal.confirm({
                      title: `还有 ${pending} 条离线记录未同步`,
                      content: '这些记录已绑定当前账号、仅保存在本机；只有当前账号下次登录才会自动同步，不会在其他账号下提交。建议先联网同步再退出。确定退出吗？',
                      okText: '仍然退出',
                      cancelText: '取消',
                      onOk: () => { logout(); navigate('/login') },
                    })
                  } else {
                    logout(); navigate('/login')
                  }
                },
              },
            ],
          }}
        >
          <button ref={accountTrigger} className="worker-user-trigger" type="button" aria-label={`账户菜单：${user?.display_name ?? "当前用户"}`} aria-haspopup="menu" aria-expanded={accountMenuOpen}>
            <Avatar size={30} icon={<UserOutlined />} />
            <Typography.Text>{user?.display_name}</Typography.Text>
          </button>
        </Dropdown>
        </div>
      </Header>
      <Content className="worker-content" id="main-content">
        <Outlet />
      </Content>
      <nav className="worker-bottom-nav" aria-label="现场工作导航">
        {MENU.map((m) => (
          <button
            key={m.key}
            onClick={() => navigate(m.key)}
            aria-current={selected === m.key ? 'page' : undefined}
            className={selected === m.key ? 'is-active' : ''}
            type="button"
          >
            <span className="worker-nav-icon">{m.icon}</span>
            <span>{m.label}</span>
          </button>
        ))}
      </nav>
      <Drawer title="设置" placement="left" width="min(460px, calc(100vw - 16px))" open={menuOpen} onClose={closeMenu} rootClassName="global-functions-drawer" destroyOnHidden
        afterOpenChange={open => { if (open) menuSearch.current?.focus() }}>
        <Input ref={menuSearch} aria-label="查找设置" placeholder="查找已授权设置" prefix={<SearchOutlined />} value={search} onChange={event => setSearch(event.target.value)} allowClear />
        {groups.map(group => <section className="global-function-group" key={group.key}><h3>{group.label}</h3><ul>{group.children.map(item => <li key={item.key}>
          <Link to={item.key} onClick={event => { if (location.pathname === item.key) { event.preventDefault(); closeMenu() } }} aria-label={item.label}>
            <span className="global-function-icon" aria-hidden="true">{item.icon}</span><span><strong>{item.label}</strong><small>{item.description}</small></span>
          </Link>
        </li>)}</ul></section>)}
        {!groups.length && <p className="function-search-empty">没有找到已授权的设置。</p>}
      </Drawer>
      <TwoFactorModal key={user?.id} open={mfaOpen} onClose={() => setMfaOpen(false)} afterClose={() => accountTrigger.current?.focus()} />
    <ChangePasswordModal open={pwdOpen} onClose={() => setPwdOpen(false)} afterClose={() => accountTrigger.current?.focus()} />
    </Layout>
  )
}
