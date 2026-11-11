import { lazy, Suspense, useEffect, type ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { Button, Result, Spin } from 'antd'
import { isAuthed } from './api/client'
import AppLayout from './layouts/AppLayout'
import Home from './pages/Home'
import Login from './pages/Login'
import { useAuth } from './stores/auth'

const ProjectPage = lazy(() => import('./pages/project/ProjectPage'))
const Templates = lazy(() => import('./pages/Templates'))
const TemplateEditor = lazy(() => import('./pages/TemplateEditor'))
const History = lazy(() => import('./pages/History'))
const SettingsPage = lazy(() => import('./pages/settings/SettingsPage'))

function Waiting() {
  return <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 100 }}><Spin size="large" /></div>
}

/** Everything behind the sign-in: wait for "who am I", send strangers to the sign-in page. */
function SignedIn({ children }: { children: ReactNode }) {
  const { user, loading, failed, fetchMe } = useAuth()
  const location = useLocation()
  const authed = isAuthed()
  useEffect(() => { if (authed && !user && !loading && !failed) void fetchMe() }, [authed, user, loading, failed, fetchMe])
  if (!authed) return <Navigate to={`/login?${new URLSearchParams({ next: location.pathname + location.search })}`} replace />
  if (user) return <>{children}</>
  if (failed) {
    return <Result status="warning" title="无法确认登录状态" subTitle="服务器暂时没有回应，或登录已经失效。"
      extra={[<Button key="retry" type="primary" onClick={() => void fetchMe()}>重试</Button>,
        <Button key="login" onClick={() => { void useAuth.getState().logout().then(() => window.location.assign('/login')) }}>重新登录</Button>]} />
  }
  return <Waiting />
}

function AdminOnly({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  return user?.role === 'admin' ? <>{children}</> : <Result status="403" title="只有系统管理员能进设置" />
}

export default function App() {
  return <Suspense fallback={<Waiting />}>
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<SignedIn><AppLayout /></SignedIn>}>
        <Route index element={<Home />} />
        <Route path="projects/:id/:tab?" element={<ProjectPage />} />
        <Route path="templates" element={<Templates />} />
        <Route path="templates/:id" element={<TemplateEditor />} />
        <Route path="history" element={<History />} />
        <Route path="settings/:tab?" element={<AdminOnly><SettingsPage /></AdminOnly>} />
        <Route path="*" element={<Result status="404" title="没有这个页面" extra={<Button type="primary" href="/">回到项目</Button>} />} />
      </Route>
    </Routes>
  </Suspense>
}
