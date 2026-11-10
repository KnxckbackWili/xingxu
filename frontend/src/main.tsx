import React from 'react'
import ReactDOM from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import { ConfigProvider, App as AntApp, theme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import dayjs from 'dayjs'
import 'dayjs/locale/zh-cn'
import utc from 'dayjs/plugin/utc'
import timezone from 'dayjs/plugin/timezone'
dayjs.extend(utc)
dayjs.extend(timezone)
import App from './App'
import ErrorBoundary from './components/ErrorBoundary'
import { useThemeStore, applyThemeMode } from './stores/theme'
import { useEffect } from 'react'
import './styles/tokens.css'
import './index.css'
import './styles/layout.css'
import './styles/workspace.css'
import './styles/theme.css'

// 版本标记：直接取 package.json version（构建时注入），缓存旧版本时强制刷新
// 前端版本与 package.json 单一事实源，不再手工维护
import { APP_VERSION } from './version'
const VERSION_KEY = 'agvpm_app_version'
try {
  const stored = localStorage.getItem(VERSION_KEY)
  if (stored && stored !== APP_VERSION) {
    localStorage.setItem(VERSION_KEY, APP_VERSION)
    // 清掉旧 Service Worker 缓存，强制拿新版本
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.getRegistrations().then((regs) => regs.forEach((r) => r.unregister()))
    }
    caches?.keys?.().then((keys) => keys.forEach((k) => caches.delete(k)))
    window.location.reload()
  } else {
    localStorage.setItem(VERSION_KEY, APP_VERSION)
  }
} catch {
  // ignore storage errors
}

dayjs.locale('zh-cn')

const router = createBrowserRouter([{ path: '*', element: <App /> }])

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
          <RouterProvider router={router} />
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
