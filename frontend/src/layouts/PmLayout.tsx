import { useDrawerReturnFocus } from '../hooks/useDrawerReturnFocus'
import { Layout, Dropdown, Avatar, Typography, Button, Drawer, Input, type InputRef } from 'antd'
import { LogoutOutlined, UserOutlined, SettingOutlined, MenuOutlined, BulbOutlined, DownOutlined, SearchOutlined } from '@ant-design/icons'
import { Link, Outlet, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../stores/auth'
import { useThemeStore } from '../stores/theme'
import NotificationBell from '../components/NotificationBell'
import ChangePasswordModal from '../components/ChangePasswordModal'
import TwoFactorModal from '../components/TwoFactorModal'
import BrandMark from '../components/BrandMark'
import { useEffect, useRef, useState } from 'react'
import { MENU_GROUPS, primaryItems } from './pmMenu'
import { canAccessNav, systemHomeRoute } from '../constants/nav'
import { ROLE_NAME } from '../constants/roles'
import './navigationShell.css'

const { Header, Content } = Layout
export default function PmLayout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [pwdOpen, setPwdOpen] = useState(false)
  const [mfaOpen, setMfaOpen] = useState(false)
  const [accountMenuOpen, setAccountMenuOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [search, setSearch] = useState('')
  const accountTrigger = useRef<HTMLButtonElement>(null)
  const menuTrigger = useRef<HTMLButtonElement>(null)
  const menuSearch = useRef<InputRef>(null)
  const restoreFocus = useRef(false)
  const themeMode = useThemeStore(state => state.mode)
  const toggleTheme = useThemeStore(state => state.toggle)
  const inProject = /^\/pm\/projects\/[^/]+/.test(location.pathname)
  const fieldUser = ['worker', 'intern'].includes(user?.role ?? '')
  const homeRoute = systemHomeRoute(user)
  const primary = primaryItems(user)
  const groups = MENU_GROUPS(user)
  const currentPrimary = primary.find(item => location.pathname === item.key || location.pathname.startsWith(`${item.key}/`))?.key
    ?? (inProject ? primary.find(item => item.key.endsWith('/projects'))?.key : undefined)
  const term = search.trim().toLocaleLowerCase()
  const filtered = groups.map(group => ({ ...group, children: group.children.filter(item => !term ||
    `${item.label} ${item.description} ${item.aliases.join(' ')}`.toLocaleLowerCase().includes(term)) })).filter(group => group.children.length)
  useDrawerReturnFocus(menuOpen, restoreFocus, 'global-functions-drawer', () => menuTrigger.current)
  const closeMenu = () => { restoreFocus.current = true; setMenuOpen(false) }
  const openMenu = () => { menuTrigger.current?.focus(); restoreFocus.current = false; setSearch(''); setMenuOpen(true) }

  useEffect(() => {
    if (!accountMenuOpen) return
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setAccountMenuOpen(false); accountTrigger.current?.focus() }
    }
    window.addEventListener('keydown', escape)
    return () => window.removeEventListener('keydown', escape)
  }, [accountMenuOpen])
  // Close only after the router accepts navigation; dirty-form guards keep the menu intact.
  useEffect(() => { setMenuOpen(false) }, [location.pathname, location.search])
  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return // Current-project search owns Ctrl/⌘ K when available.
      const target = event.target instanceof Element ? event.target : document.activeElement
      if (target?.closest('.ant-modal')) return
      if (event.key === 'Escape' && menuOpen) { event.preventDefault(); closeMenu(); return }
      if (!(event.ctrlKey || event.metaKey) || event.altKey || event.key.toLowerCase() !== 'k') return
      if (target?.closest('input, textarea, select, [contenteditable="true"]')) return
      event.preventDefault(); openMenu()
    }
    window.addEventListener('keydown', shortcut)
    return () => window.removeEventListener('keydown', shortcut)
  }, [menuOpen])

  return <Layout className={`pm-shell unified-navigation-shell${inProject ? ' is-project-workspace' : ''}`}>
    <a href="#main-content" className="skip-to-content">跳到主要内容</a>
    <Layout className="pm-main">
      <Header className="pm-header unified-topbar">
        <div className="global-navigation">
          <button className="global-brand" type="button" onClick={() => navigate(homeRoute)} aria-label={fieldUser ? '行序，返回本周' : '行序，返回工作台'}>
            <BrandMark />
          </button>
          <nav className="global-primary-navigation" aria-label="常用功能">
            {primary.map(item => <Link key={item.key} to={item.key} aria-current={currentPrimary === item.key ? 'page' : undefined}>{item.label}</Link>)}
          </nav>
          <button className="global-functions-trigger" ref={menuTrigger} type="button" aria-label="设置" aria-haspopup="dialog" aria-expanded={menuOpen}
            aria-keyshortcuts="Control+K Meta+K" onClick={openMenu}><MenuOutlined /><span className="global-functions-desktop-label">设置</span><span className="global-functions-mobile-label">设置</span></button>
        </div>
        <div className="pm-header-actions">
          <Button type="text" icon={<BulbOutlined />} aria-label={themeMode === 'dark' ? '切换到浅色模式' : '切换到深色模式'} title={themeMode === 'dark' ? '切换到浅色模式' : '切换到深色模式'} onClick={toggleTheme} />
          <NotificationBell />
          <Dropdown trigger={['click']} open={accountMenuOpen} onOpenChange={setAccountMenuOpen} menu={{ items: [
            ...(user?.role === 'admin' ? [{ key: 'permissions', icon: <SettingOutlined />, label: '成员权限', onClick: () => { setAccountMenuOpen(false); navigate('/pm/permissions') } }] : []),
            ...((['admin', 'pm'].includes(user?.role ?? '') || user?.two_factor_enabled) ? [{ key: 'mfa', icon: <SettingOutlined />, label: '二次验证', onClick: () => { setAccountMenuOpen(false); setMfaOpen(true) } }] : []),
              { key: 'pwd', icon: <SettingOutlined />, label: '修改密码', onClick: () => { setAccountMenuOpen(false); setPwdOpen(true) } },
            ...(canAccessNav('/pm/feedback',user) ? [{key:'feedback',label:'使用反馈',onClick:()=>{setAccountMenuOpen(false);navigate('/pm/feedback')}}] : []),
            { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', onClick: () => { setAccountMenuOpen(false); logout(); navigate('/login') } },
          ] }}>
            <button ref={accountTrigger} className="user-trigger" type="button" aria-label={`账户菜单：${user?.display_name ?? '当前用户'}`} aria-haspopup="menu" aria-expanded={accountMenuOpen}>
              <Avatar size={30} icon={<UserOutlined />} /><span className="user-trigger-copy"><Typography.Text>{user?.display_name}</Typography.Text>{user?.display_name !== (ROLE_NAME[user?.role ?? ''] ?? '项目成员') && <Typography.Text type="secondary">{ROLE_NAME[user?.role ?? ''] ?? '项目成员'}</Typography.Text>}</span><DownOutlined style={{ fontSize: 10, color: 'var(--agv-text-secondary)' }} />
            </button>
          </Dropdown>
        </div>
      </Header>
      <Content className="pm-content" id="main-content"><div className="content-canvas"><Outlet /></div></Content>
    </Layout>
    <Drawer title="设置" placement="left" width="min(460px, calc(100vw - 16px))" open={menuOpen} onClose={closeMenu} rootClassName="global-functions-drawer" destroyOnHidden
      afterOpenChange={open => {
        if (open && !document.activeElement?.closest('.global-functions-drawer a, .global-functions-drawer button')) menuSearch.current?.focus()
      }}>
      <Input ref={menuSearch} aria-label="查找设置" placeholder="按名称或用途查找设置" prefix={<SearchOutlined />} value={search} onChange={event => setSearch(event.target.value)} allowClear />
      {filtered.map(group => <section className="global-function-group" key={group.key} aria-labelledby={`global-functions-${group.key}`}>
        <h3 id={`global-functions-${group.key}`}>{group.label}</h3><ul>{group.children.map(item => <li key={item.key}>
          <Link to={item.key} aria-label={item.label} aria-describedby={`global-function-${item.key.replace(/\W/g, '-')}`} aria-current={location.pathname === item.key ? 'page' : undefined}
            onClick={event => { if (location.pathname === item.key && !location.search) { event.preventDefault(); closeMenu() } }}>
            <span className="global-function-icon" aria-hidden="true">{item.icon}</span><span><strong>{item.label}</strong><small id={`global-function-${item.key.replace(/\W/g, '-')}`}>{item.description}</small></span>
          </Link>
        </li>)}</ul>
      </section>)}
      {!filtered.length && <p className="function-search-empty">没有找到功能，试试名称或用途。</p>}
    </Drawer>
    <TwoFactorModal key={user?.id} open={mfaOpen} onClose={() => setMfaOpen(false)} afterClose={() => accountTrigger.current?.focus()} />
    <ChangePasswordModal open={pwdOpen} onClose={() => setPwdOpen(false)} afterClose={() => accountTrigger.current?.focus()} />
  </Layout>
}
