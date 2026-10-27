import { lazy, Suspense, useEffect, type ReactNode } from 'react'
import { Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { Spin, Button, Result } from 'antd'
import { useAuth } from './stores/auth'
import { isAuthed } from './api/client'
import { PM_ROLES, WORKER_ROLES } from './constants/roles'
import { canAccessNav } from './constants/nav'
import { SYSTEM_PERMISSION_REFRESH_EVENT } from './constants/systemPermissions'
import { installAccessibilityPatches } from './utils/a11y'
import WorkDetailHost from './components/WorkDetailHost'
import LoginPage from './pages/LoginPage'
import ForbiddenPage from './pages/ForbiddenPage'
import NotFoundPage from './pages/NotFoundPage'

const ExternalViewPage = lazy(() => import('./pages/ExternalViewPage'))
const AppLayout = lazy(() => import('./layouts/AppLayout'))
const SettingsPage = lazy(() => import('./pages/pm/SettingsPage'))
const ProjectListPage = lazy(() => import('./pages/pm/ProjectListPage'))
const ProjectLayout = lazy(() => import('./pages/pm/project/ProjectLayout'))
const InventoryOverviewPage = lazy(() => import('./pages/pm/InventoryOverviewPage'))
const TemplateEditorPage = lazy(() => import('./pages/pm/TemplateEditorPage'))
const DashboardPage = lazy(() => import('./pages/pm/DashboardPage'))
const PeoplePlanPage = lazy(() => import('./pages/pm/PeoplePlanPage'))
const UsersPage = lazy(() => import('./pages/pm/UsersPage'))
const SystemPermissionsPage = lazy(() => import('./pages/pm/SystemPermissionsPage'))
const SystemBackupPanel = lazy(() => import('./pages/pm/SystemBackupPanel'))
const StorageSettingsPage = lazy(() => import('./pages/pm/StorageSettingsPage'))
const SystemUpdatesPage = lazy(() => import('./pages/pm/SystemUpdatesPage'))
const ProjectRecycleBinPage = lazy(() => import('./pages/pm/ProjectRecycleBinPage'))
const MessagesPage = lazy(() => import('./pages/MessagesPage'))
const AiTokensPage = lazy(() => import('./pages/pm/AiTokensPage'))
const NotificationChannelsPage = lazy(() => import('./pages/pm/NotificationChannelsPage'))
const VehicleTypesPage = lazy(() => import('./pages/pm/VehicleTypesPage'))
const HolidayCalendarsPage = lazy(() => import('./pages/pm/HolidayCalendarsPage'))
const WeekPage = lazy(() => import('./pages/worker/WeekPage'))
function WeekRoute() {
  const location = useLocation()
  return <WeekPage projectId={new URLSearchParams(location.search).get('project_id') || ''} />
}

function LegacyWeekRedirect() {
  const location = useLocation()
  const projectId = new URLSearchParams(location.search).get('project_id')
  return <Navigate to={projectId ? `/worker/week?project_id=${encodeURIComponent(projectId)}` : '/worker/week'} replace />
}

const WorkerIssuesPage = lazy(() => import('./pages/worker/WorkerIssuesPage'))
const MyPage = lazy(() => import('./pages/worker/MyPage'))
function WorkerProjectRedirect() {
  const location = useLocation()
  return <Navigate to={location.pathname.replace(/^\/worker\/projects/, '/pm/projects')} replace />
}
const FeedbackPage = lazy(() => import('./pages/FeedbackPage'))


/** 角色路由边界：PM_ROLES / WORKER_ROLES 定义见 constants/roles.ts（与登录落地共用单一事实源） */

function PageLoader() {
  return (
    <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 100 }}>
      <Spin size="large" />
    </div>
  )
}

function load(element: ReactNode) {
  return <Suspense fallback={<PageLoader />}>{element}</Suspense>
}

function Spinner() {
  return (
    <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 100 }}>
      <Spin size="large" />
    </div>
  )
}

function ProtectedRoute({ children, allow, navKey }: { children: React.ReactNode; allow?: string[]; navKey?: string }) {
  const { user, loading, meError, fetchMe, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const loginTarget = `/login?${new URLSearchParams({ next: location.pathname + location.search + location.hash })}`
  const authed = isAuthed()
  // 有会话（HttpOnly Cookie 标记）但用户信息还没加载完 → 等 fetchMe 完成
  if (loading || (authed && !user && !meError)) {
    return <Spinner />
  }
  // HYPE-99：会话标记还在但 /auth/me 返回 403/5xx/网络错误时，禁止永久转圈——
  // 给明确的重试 / 返回登录路径。
  if (authed && !user && meError) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 80 }}>
        <Result
          status="warning"
          title="无法验证登录状态"
          subTitle="服务器校验会话失败或网络异常。请重试；若持续失败，请重新登录。"
          extra={[
            <Button key="retry" type="primary" onClick={() => { void fetchMe() }}>
              重试
            </Button>,
            <Button
              key="login"
              onClick={() => {
                logout()
                navigate(loginTarget, { replace: true })
              }}
            >
              返回登录
            </Button>,
          ]}
        />
      </div>
    )
  }
  if (!authed || !user) {
    return <Navigate to={loginTarget} replace />
  }
  // 角色守卫：菜单隐藏不是边界，URL 直达也要拦——渲染 403 页而非静默重定向
  if ((allow && !allow.includes(user.role)) || (navKey && !canAccessNav(navKey, user))) {
    return <ForbiddenPage />
  }
  return <>{children}</>
}

export default function App() {
  const { user, fetchMe, refreshPermissions } = useAuth()
  const location = useLocation()

  useEffect(() => {
    // HYPE-56：登录页不做会话校验。旧 token/cookie 残留时，登录页触发 fetchMe 必然 401，
    // 进而 refresh→失败→重定向，把登录页自身写进 next 造成路由级死循环。
    // 登录页是公开页，无需 fetchMe，由用户登录动作换取新会话。
    if (isAuthed() && !user && location.pathname !== '/login' && !location.pathname.startsWith('/external')) {
      fetchMe()
    }
  }, [user, fetchMe, location.pathname])

  useEffect(() => {
    if (!user || location.pathname.startsWith('/external') || typeof refreshPermissions !== 'function') return
    const refresh = () => { if (document.visibilityState !== 'hidden') void refreshPermissions() }
    window.addEventListener('focus', refresh)
    window.addEventListener(SYSTEM_PERMISSION_REFRESH_EVENT, refresh)
    document.addEventListener('visibilitychange', refresh)
    const timer = window.setInterval(refresh, 60_000)
    return () => {
      window.removeEventListener('focus', refresh)
      window.removeEventListener(SYSTEM_PERMISSION_REFRESH_EVENT, refresh)
      document.removeEventListener('visibilitychange', refresh)
      window.clearInterval(timer)
    }
  }, [user?.id, refreshPermissions, location.pathname])

  // 全站可访问性兜底（T019）：Select/Checkbox/滚动容器/Progress 的可访问名称与焦点语义
  useEffect(() => installAccessibilityPatches(), [])

  return (
    <div className="page-fade">
      <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/external" element={load(<ExternalViewPage />)} />
      <Route
        path="/pm"
        element={
          <ProtectedRoute allow={PM_ROLES}>
            {load(<AppLayout />)}
          </ProtectedRoute>
        }
      >
        <Route index element={<Navigate to={canAccessNav('/pm/dashboard', user) ? '/pm/dashboard' : canAccessNav('/pm/projects', user) ? '/pm/projects' : '/pm/messages'} replace />} />
        <Route path="projects" element={<ProtectedRoute navKey="/pm/projects">{load(<ProjectListPage />)}</ProtectedRoute>} />
        <Route path="inventory" element={<ProtectedRoute navKey="/pm/inventory">{load(<InventoryOverviewPage />)}</ProtectedRoute>} />
        <Route path="ai" element={<Navigate to="/pm/projects" replace />} />
        <Route path="dashboard" element={<ProtectedRoute navKey="/pm/dashboard">{load(<DashboardPage />)}</ProtectedRoute>} />
        <Route path="my-schedule" element={<Navigate to="/pm/people?view=mine" replace />} />
        <Route path="team-schedule" element={<Navigate to="/pm/people?view=team" replace />} />
        <Route path="people" element={<ProtectedRoute navKey="/pm/people">{load(<PeoplePlanPage />)}</ProtectedRoute>} />
        <Route path="projects/:projectId" element={<ProtectedRoute navKey="/pm/projects">{load(<ProjectLayout />)}</ProtectedRoute>} />
        <Route path="projects/:projectId/:tab" element={<ProtectedRoute navKey="/pm/projects">{load(<ProjectLayout />)}</ProtectedRoute>} />
        <Route path="templates" element={<ProtectedRoute navKey="/pm/templates">{load(<TemplateEditorPage />)}</ProtectedRoute>} />
        <Route path="ai-assistant" element={<Navigate to="/pm/projects" replace />} />
        <Route path="progress" element={<Navigate to="/pm/dashboard" replace />} />
        <Route path="stats" element={<Navigate to="/pm/dashboard#statistics" replace />} />
        <Route path="messages" element={<ProtectedRoute navKey="/pm/messages">{load(<MessagesPage />)}</ProtectedRoute>} />
        <Route path="governance" element={<Navigate to="/pm/projects" replace />} />
        <Route path="project-recycle-bin" element={<ProtectedRoute navKey="/pm/project-recycle-bin">{load(<ProjectRecycleBinPage />)}</ProtectedRoute>} />
        <Route path="storage" element={<ProtectedRoute navKey="/pm/storage">{load(<StorageSettingsPage />)}</ProtectedRoute>} />
        <Route path="backups" element={<ProtectedRoute navKey="/pm/backups">{load(<SystemBackupPanel />)}</ProtectedRoute>} />
        <Route path="system-updates" element={<ProtectedRoute allow={['admin']} navKey="/pm/system-updates">{load(<SystemUpdatesPage />)}</ProtectedRoute>} />
        <Route path="users" element={<ProtectedRoute navKey="/pm/users">{load(<UsersPage />)}</ProtectedRoute>} />
        <Route path="permissions" element={<ProtectedRoute allow={['admin']} navKey="/pm/permissions">{load(<SystemPermissionsPage />)}</ProtectedRoute>} />
        <Route path="ai-tokens" element={<ProtectedRoute navKey="/pm/ai-tokens">{load(<AiTokensPage />)}</ProtectedRoute>} />
        <Route path="notification-channels" element={<ProtectedRoute navKey="/pm/notification-channels">{load(<NotificationChannelsPage />)}</ProtectedRoute>} />
        <Route path="holidays" element={<ProtectedRoute navKey="/pm/holidays">{load(<HolidayCalendarsPage />)}</ProtectedRoute>} />
        <Route path="vehicle-types" element={<ProtectedRoute navKey="/pm/vehicle-types">{load(<VehicleTypesPage />)}</ProtectedRoute>} />
        <Route path="feedback" element={<ProtectedRoute navKey="/pm/feedback">{load(<FeedbackPage />)}</ProtectedRoute>} />
        <Route path="settings" element={load(<SettingsPage />)} />
      </Route>
      <Route
        path="/worker"
        element={
          <ProtectedRoute allow={WORKER_ROLES}>
            {load(<AppLayout />)}
          </ProtectedRoute>
        }
      >
        <Route index element={<Navigate to="/worker/week" replace />} />
        <Route path="week" element={<ProtectedRoute navKey="/worker/week">{load(<WeekRoute />)}</ProtectedRoute>} />
        <Route path="today" element={<LegacyWeekRedirect />} />
        <Route path="schedule" element={<LegacyWeekRedirect />} />
        <Route path="issues" element={<ProtectedRoute navKey="/worker/issues">{load(<WorkerIssuesPage />)}</ProtectedRoute>} />
        {/* 两端已合并：项目统一在项目页查看 */}
        <Route path="projects" element={<WorkerProjectRedirect />} />
        <Route path="projects/:projectId" element={<WorkerProjectRedirect />} />
        <Route path="my" element={load(<MyPage />)} />
        {/* 旧路由兼容 */}
        <Route path="records" element={<Navigate to="/worker/my" replace />} />
        <Route path="stats" element={<Navigate to="/worker/my" replace />} />
        <Route path="messages" element={<ProtectedRoute navKey="/worker/messages">{load(<MessagesPage />)}</ProtectedRoute>} />
        <Route path="feedback" element={<ProtectedRoute navKey="/worker/feedback">{load(<FeedbackPage />)}</ProtectedRoute>} />
      </Route>
      <Route path="/" element={<Navigate to="/login" replace />} />
      <Route path="*" element={<NotFoundPage />} />
      </Routes>
      {!location.pathname.startsWith('/external') && <>
        <WorkDetailHost />
      </>}
    </div>
  )
}
