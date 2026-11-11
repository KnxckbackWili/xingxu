import React, { useEffect } from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { App as AntApp, ConfigProvider, theme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './App'
import ErrorBoundary from './components/ErrorBoundary'
import { applyThemeMode, useThemeStore } from './stores/theme'
import './styles/tokens.css'
import './styles/base.css'
import './styles/workspace.css'
import './styles/theme.css'

// Versions before 4 installed an offline cache. It would keep showing the old pages, so every
// visit makes sure it is gone: its service worker is unregistered and its caches are deleted.
if ('serviceWorker' in navigator) {
  void navigator.serviceWorker.getRegistrations().then((registrations) => registrations.forEach((registration) => { void registration.unregister() })).catch(() => undefined)
}
if ('caches' in window) {
  void caches.keys().then((keys) => keys.forEach((key) => { void caches.delete(key) })).catch(() => undefined)
}

function AppRoot() {
  const mode = useThemeStore((state) => state.mode)
  const dark = mode === 'dark'

  useEffect(() => {
    applyThemeMode(mode)
  }, [mode])

  return (
    <ConfigProvider
      locale={zhCN}
      button={{ autoInsertSpace: false }}
      theme={{
        algorithm: dark ? theme.darkAlgorithm : theme.defaultAlgorithm,
        token: {
          colorPrimary: dark ? '#8fb4ff' : '#2563eb',
          colorInfo: dark ? '#8fb4ff' : '#2563eb',
          colorLink: dark ? '#8fb4ff' : '#2563eb',
          colorLinkHover: dark ? '#a9c5ff' : '#1d4fd7',
          colorSuccess: dark ? '#6fd3a6' : '#12805c',
          colorWarning: dark ? '#eab765' : '#b4690e',
          colorError: dark ? '#ff9a92' : '#cf3a3d',
          colorText: dark ? '#edf1f7' : '#1b2333',
          // WCAG AA: secondary and placeholder text keep at least 4.5:1 on their surfaces.
          colorTextSecondary: dark ? '#aab5c6' : '#5c6779',
          colorTextDescription: dark ? '#aab5c6' : '#5c6779',
          colorTextPlaceholder: dark ? '#93a0b4' : '#6b778a',
          colorTextTertiary: dark ? '#93a0b4' : '#667284',
          colorBgLayout: dark ? '#0f131a' : '#f3f5f9',
          colorBgContainer: dark ? '#181e28' : '#ffffff',
          colorBgElevated: dark ? '#1d2430' : '#ffffff',
          colorBorder: dark ? '#364153' : '#dfe4ec',
          colorBorderSecondary: dark ? '#2a3342' : '#ebeef4',
          borderRadius: 10,
          borderRadiusLG: 14,
          fontSize: 14,
          controlHeight: 36,
          fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Helvetica, Arial, sans-serif",
        },
        components: {
          Card: { borderRadiusLG: 16 },
          Layout: { headerHeight: 60 },
          Table: { headerBg: 'transparent', headerColor: dark ? '#aab5c6' : '#5c6779', headerSplitColor: 'transparent', rowHoverBg: dark ? '#212936' : '#f6f8fb', borderColor: dark ? '#2a3342' : '#ebeef4' },
          Button: { borderRadius: 10, primaryShadow: 'none', defaultShadow: 'none', dangerShadow: 'none', fontWeight: 500 },
          Tabs: { inkBarColor: dark ? '#8fb4ff' : '#2563eb', itemSelectedColor: dark ? '#8fb4ff' : '#2563eb', itemHoverColor: dark ? '#a9c5ff' : '#2563eb' },
          Segmented: { trackBg: dark ? '#262f3d' : '#eef1f6' },
          Modal: { borderRadiusLG: 16 },
        },
      }}
    >
      <AntApp>
        <ErrorBoundary>
          <BrowserRouter><App /></BrowserRouter>
        </ErrorBoundary>
      </AntApp>
    </ConfigProvider>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AppRoot />
  </React.StrictMode>,
)
