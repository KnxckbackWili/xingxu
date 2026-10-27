import { useEffect, useRef, useState } from 'react'
import { Avatar, Drawer, Dropdown, Input, Modal, type InputRef, type MenuProps } from 'antd'
import { LogoutOutlined, UserOutlined, SettingOutlined, BulbOutlined, SearchOutlined, CommentOutlined, LockOutlined, SafetyOutlined, HistoryOutlined } from '@ant-design/icons'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../stores/auth'
import { useThemeStore } from '../stores/theme'
import { getQueue } from '../offline/queue'
import NotificationBell from '../components/NotificationBell'
import UploadQueue from '../components/UploadQueue'
import ChangePasswordModal from '../components/ChangePasswordModal'
import TwoFactorModal from '../components/TwoFactorModal'
import BrandMark from '../components/BrandMark'
import { useDrawerReturnFocus } from '../hooks/useDrawerReturnFocus'
import { canAccessNav, systemHomeRoute } from '../constants/nav'
import { ROLE_NAME } from '../constants/roles'
import { activeNavKey, appNavItems, MENU_GROUPS } from './pmMenu'
import './appShell.css'

/** The one shell for every role: sidebar on desktop, top bar + bottom tabs on phones. */
export default function AppLayout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const themeMode = useThemeStore(state => state.mode)
  const toggleTheme = useThemeStore(state => state.toggle)
  const [pwdOpen, setPwdOpen] = useState(false)
  const [mfaOpen, setMfaOpen] = useState(false)
  const [accountOpen, setAccountOpen] = useState(false)
  const [sheetOpen, setSheetOpen] = useState(false)
  const [findOpen, setFindOpen] = useState(false)
  const [search, setSearch] = useState('')
  const accountTrigger = useRef<HTMLButtonElement>(null)
  const findTrigger = useRef<HTMLButtonElement>(null)
  const findInput = useRef<InputRef>(null)
  const restoreFocus = useRef(false)
  const nav = appNavItems(user)
  const current = activeNavKey(nav, location.pathname)
  const inProject = /^\/pm\/projects\/[^/]+/.test(location.pathname)
  const bottom = [...nav.filter(entry => ['/pm/dashboard', '/worker/week', '/pm/projects', '/worker/issues', '/pm/messages', '/worker/messages'].includes(entry.key)).slice(0, 4)]

  useDrawerReturnFocus(findOpen, restoreFocus, 'app-find-drawer', () => findTrigger.current)
  const closeFind = () => { restoreFocus.current = true; setFindOpen(false) }
  const openFind = () => { restoreFocus.current = false; setSearch(''); setFindOpen(true) }
  // Close only after the router accepts navigation; dirty-form guards keep the drawer intact.
  useEffect(() => { setFindOpen(false); setAccountOpen(false); setSheetOpen(false) }, [location.pathname, location.search])
  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return // Current-project search owns Ctrl/⌘ K when available.
      const target = event.target instanceof Element ? event.target : document.activeElement
      if (target?.closest('.ant-modal')) return
      if (event.key === 'Escape' && findOpen) { event.preventDefault(); closeFind(); return }
      if (event.key === 'Escape' && accountOpen) { setAccountOpen(false); accountTrigger.current?.focus(); return }
      if (!(event.ctrlKey || event.metaKey) || event.altKey || event.key.toLowerCase() !== 'k') return
      if (target?.closest('input, textarea, select, [contenteditable="true"]')) return
      event.preventDefault(); openFind()
    }
    window.addEventListener('keydown', shortcut)
    return () => window.removeEventListener('keydown', shortcut)
  }, [accountOpen, findOpen])

  const signOut = () => {
    const pending = getQueue().length
    const leave = () => { logout(); navigate('/login') }
    if (!pending) { leave(); return }
    Modal.confirm({
      title: `还有 ${pending} 条离线记录未同步`,
      content: '这些记录已绑定当前账号、仅保存在本机；只有当前账号下次登录才会自动同步，不会在其他账号下提交。建议先联网同步再退出。确定退出吗？',
      okText: '仍然退出', cancelText: '取消', onOk: leave,
    })
  }
  const feedback = canAccessNav('/pm/feedback', user) ? '/pm/feedback' : canAccessNav('/worker/feedback', user) ? '/worker/feedback' : ''
  const close = (action: () => void) => () => { setAccountOpen(false); setSheetOpen(false); action() }
  const accountItems: MenuProps['items'] = [
    ...(canAccessNav('/worker/my', user) ? [{ key: 'records', icon: <HistoryOutlined />, label: '我的记录', onClick: close(() => navigate('/worker/my')) }] : []),
    ...(MENU_GROUPS(user).length ? [{ key: 'settings', icon: <SettingOutlined />, label: '设置', onClick: close(() => navigate('/pm/settings')) }] : []),
    ...((['admin', 'pm'].includes(user?.role ?? '') || user?.two_factor_enabled) ? [{ key: 'mfa', icon: <SafetyOutlined />, label: '二次验证', onClick: close(() => setMfaOpen(true)) }] : []),
    { key: 'pwd', icon: <LockOutlined />, label: '修改密码', onClick: close(() => setPwdOpen(true)) },
    { key: 'theme', icon: <BulbOutlined />, label: themeMode === 'dark' ? '切换到浅色模式' : '切换到深色模式', onClick: close(toggleTheme) },
    ...(feedback ? [{ key: 'feedback', icon: <CommentOutlined />, label: '使用反馈', onClick: close(() => navigate(feedback)) }] : []),
    { type: 'divider' as const },
    { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', onClick: close(signOut) },
  ]
  const roleName = ROLE_NAME[user?.role ?? ''] ?? '项目成员'
  const account = <Dropdown trigger={['click']} open={accountOpen} onOpenChange={setAccountOpen} placement="topLeft" menu={{ items: accountItems }}>
    <button ref={accountTrigger} className="app-account" type="button"
      aria-label={`账户菜单：${user?.display_name ?? '当前用户'}`} aria-haspopup="menu" aria-expanded={accountOpen}>
      <Avatar size={32} icon={<UserOutlined />} />
      <span className="app-account-copy"><strong>{user?.display_name}</strong>{user?.display_name !== roleName && <small>{roleName}</small>}</span>
    </button>
  </Dropdown>

  const term = search.trim().toLocaleLowerCase()
  const findGroups = [{ key: 'main', label: '常用', children: nav.filter(entry => entry.key !== '/pm/settings') }, ...MENU_GROUPS(user)]
    .map(group => ({ ...group, children: group.children.filter(entry => !term || `${entry.label} ${entry.description} ${entry.aliases.join(' ')}`.toLocaleLowerCase().includes(term)) }))
    .filter(group => group.children.length)

  return <div className={`app-shell pm-shell${inProject ? ' is-project-workspace' : ''}`}>
    <a href="#main-content" className="skip-to-content">跳到主要内容</a>
    <aside className="app-sidebar">
      <button className="app-brand" type="button" onClick={() => navigate(systemHomeRoute(user))} aria-label="行序，返回工作台"><BrandMark /></button>
      <nav className="app-sidebar-nav" aria-label="主导航">
        {nav.map(entry => <Link key={entry.key} to={entry.key} aria-current={current === entry.key ? 'page' : undefined}>
          <span className="app-nav-icon" aria-hidden="true">{entry.icon}</span><span>{entry.label}</span>
        </Link>)}
      </nav>
      <div className="app-sidebar-footer">{account}</div>
    </aside>
    <div className="app-main">
      <header className="app-topbar">
        <button className="app-brand app-brand--mobile" type="button" onClick={() => navigate(systemHomeRoute(user))} aria-label="行序，返回工作台"><BrandMark /></button>
        <button ref={findTrigger} className="app-find" type="button" onClick={openFind} aria-haspopup="dialog" aria-expanded={findOpen} aria-keyshortcuts="Control+K Meta+K" aria-label="查找功能">
          <SearchOutlined aria-hidden="true" /><span className="app-find-label">查找功能</span><kbd>Ctrl K</kbd>
        </button>
        <div className="app-topbar-actions">
          {user && <UploadQueue key={user.id} ownerId={user.id} />}
          <NotificationBell />
        </div>
      </header>
      <main className="app-content" id="main-content"><div className="content-canvas"><Outlet /></div></main>
    </div>
    <nav className="app-bottom-nav" aria-label="主导航（手机）">
      {bottom.map(entry => <Link key={entry.key} to={entry.key} aria-current={current === entry.key ? 'page' : undefined}>
        <span className="app-nav-icon" aria-hidden="true">{entry.icon}</span><span>{entry.label}</span>
      </Link>)}
      <button type="button" onClick={() => setSheetOpen(true)} aria-haspopup="dialog" aria-expanded={sheetOpen} aria-label="我的：记录、设置与账户">
        <span className="app-nav-icon" aria-hidden="true"><UserOutlined /></span><span>我的</span>
      </button>
    </nav>
    <Drawer title="查找功能" placement="left" width="min(460px, calc(100vw - 16px))" open={findOpen} onClose={closeFind} rootClassName="app-find-drawer global-functions-drawer" destroyOnHidden
      afterOpenChange={open => { if (open) findInput.current?.focus() }}>
      <Input ref={findInput} aria-label="查找功能" placeholder="按名称或用途查找" prefix={<SearchOutlined />} value={search} onChange={event => setSearch(event.target.value)} allowClear />
      {findGroups.map(group => <section className="global-function-group" key={group.key} aria-labelledby={`find-${group.key}`}>
        <h3 id={`find-${group.key}`}>{group.label}</h3><ul>{group.children.map(entry => <li key={entry.key}>
          <Link to={entry.key} aria-label={entry.label} aria-current={location.pathname === entry.key ? 'page' : undefined}
            onClick={event => { if (location.pathname === entry.key && !location.search) { event.preventDefault(); closeFind() } }}>
            <span className="global-function-icon" aria-hidden="true">{entry.icon}</span><span><strong>{entry.label}</strong><small>{entry.description}</small></span>
          </Link>
        </li>)}</ul>
      </section>)}
      {!findGroups.length && <p className="function-search-empty">没有找到功能，试试名称或用途。</p>}
    </Drawer>
    <Drawer title={user?.display_name ?? '我的'} placement="bottom" height="auto" open={sheetOpen} onClose={() => setSheetOpen(false)} rootClassName="app-account-sheet">
      <p className="app-account-sheet-role">{roleName}</p>
      <ul>{accountItems.map((entry, index) => entry && 'key' in entry && 'onClick' in entry
        ? <li key={String(entry.key)}><button type="button" onClick={entry.onClick as () => void}><span aria-hidden="true">{'icon' in entry ? entry.icon : null}</span>{'label' in entry ? entry.label : null}</button></li>
        : <li key={`divider-${index}`} className="app-account-sheet-divider" role="separator" />)}</ul>
    </Drawer>
    <TwoFactorModal key={user?.id} open={mfaOpen} onClose={() => setMfaOpen(false)} afterClose={() => accountTrigger.current?.focus()} />
    <ChangePasswordModal open={pwdOpen} onClose={() => setPwdOpen(false)} afterClose={() => accountTrigger.current?.focus()} />
  </div>
}
