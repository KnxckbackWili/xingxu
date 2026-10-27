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
import './index.css'
import './styles/layout.css'
import './styles/workspace.css'

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

  useEffect(() => {
    applyThemeMode(mode)
  }, [mode])

  return (
    <ConfigProvider
      locale={zhCN}
      button={{ autoInsertSpace: false }}
      theme={{
        algorithm: mode === 'dark' ? theme.darkAlgorithm : theme.defaultAlgorithm,
        token: {
          colorPrimary: '#1764e8',
          colorInfo: '#2563eb',
          colorLink: mode === 'dark' ? '#9bbdff' : '#1764e8',
          colorLinkHover: mode === 'dark' ? '#b8c8ff' : '#294abc',
          colorSuccess: '#16835f',
          colorWarning: '#c77816',
          colorError: '#c63f3f',
          colorText: mode === 'dark' ? '#edf1f7' : '#202631',
          // T020：WCAG AA —— colorTextSecondary/colorTextDescription 需 ≥4.5:1。
          // 原 #65716e 在 Segmented 轨道 #d7e1d9 上约 4.23:1、AntD 默认 colorTextDescription
          // rgba(0,0,0,.45) 约 3.3:1，均不达标；统一加深。
          colorTextSecondary: mode === 'dark' ? '#b7c2d2' : '#606b7b',
          colorTextDescription: mode === 'dark' ? '#b7c2d2' : '#606b7b',
          colorTextPlaceholder: mode === 'dark' ? '#9babbe' : '#68758b',
          colorTextTertiary: mode === 'dark' ? '#9babbe' : '#66727d',
          colorBgLayout: mode === 'dark' ? '#11151c' : '#f5f6f8',
          colorBgContainer: mode === 'dark' ? '#1b222d' : '#ffffff',
          colorBorder: mode === 'dark' ? '#3d485a' : '#dce1e8',
          colorBorderSecondary: mode === 'dark' ? '#2d3848' : '#e9edf2',
          borderRadius: 9,
          fontSize: 14,
          controlHeight: 36,
        },
        components: {
          Card: {
            borderRadiusLG: 14,
            boxShadowTertiary: '0 1px 2px rgba(23, 32, 31, 0.04)',
          },
          Layout: {
            siderBg: mode === 'dark' ? '#11151c' : '#1b222d',
            headerBg: mode === 'dark' ? '#1b222d' : '#ffffff',
            headerHeight: 60,
          },
          Menu: {
            darkItemBg: 'transparent',
            darkItemColor: '#b7c2d2',
            darkItemSelectedBg: '#203656',
            darkItemSelectedColor: '#fff',
            darkItemHoverBg: '#242d3b',
            darkItemHoverColor: '#fff',
            itemBorderRadius: 9,
            itemHeight: 42,
          },
          Table: {
            headerBg: mode === 'dark' ? '#242d3b' : '#f8f9fb',
            headerColor: mode === 'dark' ? '#b7c2d2' : '#606b7b',
            rowHoverBg: mode === 'dark' ? '#253853' : '#edf4ff',
          },
          Button: {
            borderRadius: 9,
            primaryShadow: '0 2px 4px rgba(23, 107, 250, 0.16)',
          },
          Tabs: {
            inkBarColor: mode === 'dark' ? '#9bbdff' : '#1764e8',
            itemSelectedColor: mode === 'dark' ? '#9bbdff' : '#1764e8',
            itemHoverColor: mode === 'dark' ? '#b8c8ff' : '#1764e8',
          },
          Segmented: {
            trackBg: mode === 'dark' ? '#25334b' : '#eef1f7',
          },
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
