import LegacyLifecycleRepair from './LegacyLifecycleRepair'
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { Typography, Button, Tag, Space, message, Spin, Result, Descriptions, Drawer, Alert } from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { projectApi, type Project } from '../../../api'
import { errMsg } from '../../../api/client'
import { useAuth } from '../../../stores/auth'
import { hasSystemPermission } from '../../../constants/systemPermissions'
import { isProjectStatus, projectStatusMeta } from '../../../constants/status'
import Tabs from '../../../components/VisibleTabs'
import { childSegment, resolveProjectNav } from '../../../constants/projectNav'
import { ProjectMenuContent } from './ProjectMenu'
import { hasProjectCapability, ProjectCapabilitiesContext, ProjectArchivedContext, ProjectStatusContext } from '../../../hooks/useProjectCapability'
import { useProjectShortcuts } from '../../../hooks/useProjectShortcuts'
import ForbiddenPage from '../../ForbiddenPage'
const OverviewPage = lazy(() => import('./OverviewPage'))
const TaskPlanPage = lazy(() => import('./TaskPlanPage'))
const SchedulePage = lazy(() => import('./SchedulePage'))
const IssuesPage = lazy(() => import('./IssuesPage'))
const DocumentsPage = lazy(() => import('./DocumentsPage'))
const SiteInformationPage = lazy(() => import('./SiteInformationPage'))
const ActivityPage = lazy(() => import('./ActivityPage'))
const EditPage = lazy(() => import('./EditPage'))
const ExportPage = lazy(() => import('./ExportPage'))

// HYPE-58 性能：菜单悬停/聚焦预取对应页面 chunk。与上面 lazy() 用同一 import 说明符，
// Vite 按模块去重，预取即预热 React.lazy 待加载的 chunk，切页时秒开。
const PAGE_PREFETCH: Record<string, () => void> = {
  start: () => void import('./StartupPage'),
  overview: () => void import('./OverviewPage'),
    plan: () => void import('./TaskPlanPage'),
  schedule: () => void import('./SchedulePage'),
  site: () => void import('./SiteInformationPage'),
  issues: () => void import('./IssuesPage'),
  delivery: () => void import('./DocumentsPage'),
  documents: () => void import('./DocumentsPage'),
  field: () => void import('./SiteInformationPage'),
  vehicles: () => void import('./SiteInformationPage'),
  activity: () => void import('./ActivityPage'),
  report: () => void import('./IssuesPage'),
  edit: () => void import('./EditPage'),
  export: () => void import('./ExportPage'),
}

export default function ProjectLayout() {
  const { user } = useAuth()
  const { visit } = useProjectShortcuts(user?.id)
  const { projectId } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const projectListPath = ['worker', 'intern'].includes(user?.role ?? '') ? '/worker/projects' : '/pm/projects'
  const [project, setProject] = useState<Project | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<'unavailable' | 'forbidden' | 'network' | null>(null)
  const [denialReason, setDenialReason] = useState('')
  const [infoOpen, setInfoOpen] = useState(false)
  const loadedProject = useRef<Project | null>(null)
  const permissionSignature = JSON.stringify([user?.id, user?.role, user?.permission_version, user?.permission_overrides ?? {}])
  const previousUserId = useRef(user?.id)
  const previousLocation = useRef(`${projectId}:${location.pathname}`)
  const effectiveCapabilities = useMemo(() => project?.capabilities?.filter(key => user?.permission_overrides?.[key] !== false), [project?.capabilities, user?.permission_overrides])
  const workspaceRef = useRef<HTMLDivElement>(null)
  const headerRef = useRef<HTMLDivElement>(null)
  const bodyRef = useRef<HTMLDivElement>(null)
  // StartupPage guards all router navigation, including global links and history.
  const navigateSafely = (path: string) => navigate(path)
  // 过期请求取消（HYPE-58）：快速切换项目/Tab 时 abort 上一次未完成请求，避免旧响应覆盖新数据
  const currentProjectId = useRef(projectId)
  currentProjectId.current = projectId
  const abortRef = useRef<AbortController | null>(null)

  const load = async () => {
    if (!projectId || currentProjectId.current !== projectId) return
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    const { signal } = controller
    // Keep the directory and current project shell during same-project refresh.
    // A different project never renders cached data from the previous one.
    if (loadedProject.current?.id !== projectId) {
      setLoading(true)
      setProject(null)
      loadedProject.current = null
    }
    setLoadError(null)
    setDenialReason('')
    try {
      const p = await projectApi.get(projectId, { signal })
      if (signal.aborted || currentProjectId.current !== projectId) return
      loadedProject.current = p
      setProject(p)
      const section = location.pathname.split(`/projects/${projectId}/`)[1]?.split('/')[0] || 'overview'
      const { parent, child } = resolveProjectNav(section)
      if (!(parent === 'activity' && (child ?? 'history') === 'history' && !hasSystemPermission(user, 'system.audit.read'))) visit(p.id, section)
    } catch (e) {
      if (!signal.aborted && currentProjectId.current === projectId) {
        const status = (e as { response?: { status?: number } }).response?.status
        const unavailable = status === 404
        const detail = (e as { response?: { data?: { detail?: string | { message?: string } } } }).response?.data?.detail
        const reason = typeof detail === 'string' ? detail : detail?.message || errMsg(e)
        setLoadError(status === 403 ? 'forbidden' : unavailable ? 'unavailable' : 'network')
        if (status === 403) setDenialReason(reason)
        message.error({ content: unavailable ? '项目不存在或无权访问' : reason, key: 'project-load' })
      }
    } finally {
      if (!signal.aborted && currentProjectId.current === projectId) setLoading(false)
    }
  }

  useEffect(() => {
    const locationKey = `${projectId}:${location.pathname}`
    if (previousLocation.current !== locationKey) setInfoOpen(false)
    previousLocation.current = locationKey
    if (previousUserId.current !== user?.id) loadedProject.current = null
    previousUserId.current = user?.id
    // The existing loader keeps the frame and local forms for same-project
    // permission updates, and aborts responses belonging to the prior request.
    void load()
    // 卸载时中止仍在途的请求
    return () => abortRef.current?.abort()
  }, [projectId, location.pathname, permissionSignature])

  // Only committed route changes reset the page. A rejected unsaved-form
  // navigation never changes pathname, and the directory's own scroll stays.
  useEffect(() => { window.scrollTo({ top: 0, left: 0 }) }, [location.pathname])


  // URL → 菜单选中态：一级 + 二级 都由单一配置源解析（含 tasks/vehicles/files 等兼容路由）
  const pathPart = location.pathname.split(`/projects/${projectId}`)[1] ?? ''
  const rawTab = pathPart.split('/')[1] || 'overview'
  const specialView = ['edit', 'export'].includes(rawTab) ? rawTab : ''
  const { parent: activeParent, child: activeChild } = resolveProjectNav(rawTab)
  const activeTab = specialView === 'edit' ? 'overview' : specialView === 'export' ? 'delivery' : activeParent

  useEffect(() => {
    const redirected: Record<string,string> = { schedule: 'plan?view=weeks', team: 'edit?section=members', start: 'overview', site: 'vehicles', activity: 'history' }
    if (redirected[rawTab]) { navigate(`/pm/projects/${projectId}/${redirected[rawTab]}`, { replace: true }); return }
    const oldDocumentTab = ['delivery', 'files', 'archive', 'preparation'].includes(rawTab)
    const oldTaskDocument = ['plan', 'tasks'].includes(rawTab) && new URLSearchParams(location.search).get('tab') === 'deliverables'
    if (oldDocumentTab || oldTaskDocument) {
      const query = rawTab === 'archive' ? '?acceptance=1' : rawTab === 'preparation' ? '?review=1' : ''
      navigate(`/pm/projects/${projectId}/documents${query}`, { replace: true })
    }
  }, [rawTab, projectId, location.search, navigate])

  /** 二级页内 Tab 切换 → 更新地址栏（走配置源里该二级项的 path 段） */
  const subNav = (parentKey: string) => (childKey: string) => {
    navigate(`/pm/projects/${projectId}/${childSegment(parentKey, childKey)}`)
  }

  if (loading || (project !== null && project.id !== projectId)) {
    return (
      <div className="project-workspace-loading">
        <Spin size="large" />
        <Typography.Text type="secondary">正在加载项目...</Typography.Text>
      </div>
    )
  }

  if (loadError || !project) {
    const unavailable = loadError === 'unavailable' || (!loadError && !project)
    const forbidden = loadError === 'forbidden'
    return (
      <Result
        status={forbidden ? '403' : unavailable ? '404' : 'error'}
        title={forbidden ? '没有权限查看项目' : unavailable ? '项目不存在或无权访问' : '项目加载失败'}
        subTitle={forbidden ? denialReason : unavailable ? '当前链接无法查看此项目，请返回项目列表查找可访问的项目' : '请稍后重试，或返回项目列表'}
        extra={
          <Space>
            {!unavailable && !forbidden && <Button onClick={load}>重新加载</Button>}
            <Button type="primary" onClick={() => navigateSafely(projectListPath)}>返回项目列表</Button>
          </Space>
        }
      />
    )
  }

  const st = projectStatusMeta(project.status)
  const unknownStatus = !isProjectStatus(project.status) || !!project.legacy_lifecycle?.requires_repair
  const daysLeft = dayjs(project.end_date).diff(dayjs(), 'day')
  const legacyEditSettings = user?.role === 'admin' || (['pm', 'lead'].includes(user?.role ?? '') && project.manager === user?.id) || !!project.is_co_manager
  const legacyManageInventory = legacyEditSettings || (project.technical_manager === user?.id && ['lead', 'technician'].includes(user?.role ?? ''))
  const legacyManageIssues = ['admin', 'director'].includes(user?.role ?? '') || !!project.is_co_manager
    || (project.manager === user?.id && ['pm', 'lead'].includes(user?.role ?? ''))
    || (project.technical_manager === user?.id && ['lead', 'technician', 'pm', 'worker'].includes(user?.role ?? ''))
  const can = (capability: string, fallback = false) => user?.permission_overrides?.[capability] !== false && hasProjectCapability(effectiveCapabilities, capability, fallback)
  const canEditSettings = !unknownStatus && can('project.update', legacyEditSettings)
  const canManageInventory = !unknownStatus && project.status !== 'archived' && can('project.manage_inventory', legacyManageInventory)
  const canManageIssues = !unknownStatus && can('project.manage_issues', legacyManageIssues)
  const canReadAudit = hasSystemPermission(user, 'system.audit.read')
  const canManageStatus = !unknownStatus && ((user?.role === 'director' && can('project.archive', true)) || can('project.update', legacyEditSettings))
  if (activeTab === 'activity' && (activeChild ?? 'history') === 'history' && !canReadAudit) return <ForbiddenPage />
  if (specialView === 'export' && !can('project.export', !['worker', 'intern'].includes(user?.role ?? ''))) return <ForbiddenPage />

  const menuProps = {
    projectId: project.id,
    activeParent,
    activeChild,
    onNavigate: navigateSafely,
    canEditSettings,
    capabilities: effectiveCapabilities,
    activeSpecial: specialView,
    navigationKey: location.pathname + location.search,
    onPrefetch: (key: string) => PAGE_PREFETCH[key]?.(),
  }

  return (
    <ProjectArchivedContext.Provider value={unknownStatus || project.status === 'archived'}>
    <ProjectStatusContext.Provider value={project.status}>
    <ProjectCapabilitiesContext.Provider value={effectiveCapabilities}>
    <div className="project-workspace project-tree-workspace" ref={workspaceRef}>
      <div className="project-workspace-header" ref={headerRef}>
        <div className="project-title-row">
          <Button aria-label="返回项目列表" icon={<ArrowLeftOutlined />} type="text" onClick={() => navigateSafely(projectListPath)} />
          <Typography.Title level={4} title={project.name} style={{ margin: 0 }}>{project.name}</Typography.Title>
        </div>
        <div className="project-context-row">
          <Tag color={st.color}>{st.label}</Tag>

          <span className="project-context-summary" title={[project.client, project.location].filter(Boolean).join(' · ') || project.manager_name}>{[project.client, project.location].filter(Boolean).join(' · ') || (project.manager_name ? `负责人 ${project.manager_name}` : '客户与地点待补充')}</span>
          <Button className="project-info-trigger" type="text" onClick={() => setInfoOpen(true)}>项目信息</Button>
        </div>
      </div>
      {project.legacy_lifecycle?.requires_repair && (activeTab === 'overview'
        ? <LegacyLifecycleRepair project={project} onChanged={load} />
        : <Alert type="warning" showIcon message="历史状态需明确核对，当前只读" action={<Button onClick={() => navigateSafely(`/pm/projects/${project.id}/overview`)}>前往概况核对历史状态</Button>} />)}
      {unknownStatus && !project.legacy_lifecycle?.requires_repair && <Alert type="warning" showIcon style={{ marginBottom: 12 }} message="项目存在未知历史状态，当前只读"
        description={`原始状态：${project.status || '空值'}。查阅与导出仍可使用；请管理员根据备份或审计记录核对后修复。`}
        action={canReadAudit ? <Button onClick={() => navigateSafely(`/pm/projects/${project.id}/history`)}>查看操作记录</Button> : undefined} />}
      <Drawer title="项目信息" open={infoOpen} onClose={() => setInfoOpen(false)} width="min(400px, calc(100vw - 16px))">
        <Descriptions column={1} items={[
          { key: 'name', label: '项目名称', children: project.name },
          { key: 'client', label: '客户', children: project.client || '未填写' },
          { key: 'location', label: '地点', children: project.location || '未填写' },
          { key: 'manager', label: '负责人', children: project.manager_name || '未分配' },
          { key: 'end', label: '计划结束', children: `${project.end_date}（${daysLeft >= 0 ? `剩 ${daysLeft} 天` : `已过 ${Math.abs(daysLeft)} 天`}）` },
          { key: 'schedule', label: '周计划', children: <Button type="link" onClick={() => navigateSafely(`/pm/projects/${project.id}/plan?view=weeks`)}>查看计划与发布情况</Button> },
          { key: 'source', label: '来源模板', children: project.source_template?.name || '未关联模板' },
        ]} />
        <Typography.Paragraph type="secondary" style={{ marginTop: 16 }}>项目成员可查看完整项目；编辑、人员安排等操作按本项目授权开放。</Typography.Paragraph>

        {canEditSettings && <Button onClick={() => navigateSafely(`/pm/projects/${project.id}/edit`)}>打开项目设置</Button>}

      </Drawer>
      <div className="project-workspace-body" ref={bodyRef}>
        <ProjectMenuContent {...menuProps} />
        <div className="project-workspace-main" id="project-current-work">
          <Suspense key={project.id} fallback={<div style={{ textAlign: 'center', padding: 64 }}><Spin /></div>}>
            {rawTab === 'edit' && <EditPage project={project} onReload={load} />}
            {rawTab === 'export' && <ExportPage projectId={project.id} projectName={project.name} />}
            {!specialView && activeTab === 'overview' && <OverviewPage projectId={project.id} projectStatus={project.status} projectSuspension={project.suspension ?? null} vehicleTotal={project.vehicle_total ?? 0} memberCount={project.members?.length ?? 0} canManageStatus={canManageStatus} canArchive={user?.permission_overrides?.['project.archive'] !== false} onStatusChange={load} />}
            {!specialView && activeTab === 'plan' && <Tabs activeKey={rawTab==='schedule'||new URLSearchParams(location.search).get('view')==='weeks'?'weeks':'work'} onChange={view=>navigateSafely(`/pm/projects/${project.id}/plan?view=${view}`)} items={[
              { key:'work',label:'工作项',children:(rawTab!=='schedule'&&new URLSearchParams(location.search).get('view')!=='weeks') ? <TaskPlanPage focusTaskId={new URLSearchParams(location.search).get('task') ?? ''} focusTab={new URLSearchParams(location.search).get('tab') === 'reference' ? 'reference' : 'checks'} sourceTemplate={project.source_template} vehicles={project.vehicles ?? []} projectId={project.id} canManage={!!project.is_co_manager} projectStatus={project.status} focusTargets={new URLSearchParams(location.search).get('focus') === 'targets'} /> : null },
              { key:'weeks',label:'周计划',children:(rawTab==='schedule'||new URLSearchParams(location.search).get('view')==='weeks') ? <SchedulePage projectId={project.id} project={project} onProjectChange={load} /> : null },
            ]} />}
            {!specialView && (activeTab==='vehicles'||activeTab==='field') && <SiteInformationPage standalone project={project} canManageInventory={canManageInventory} sub={activeTab==='vehicles'?'vehicles':(activeChild??'inventory') as 'inventory'|'handover'} onSubChange={subNav('field')} onReload={load} />}
            {!specialView && activeTab === 'issues' && <IssuesPage key={project.id} projectId={project.id} canManage={canManageIssues} archived={project.status === 'archived'} />}
            {!specialView && activeTab === 'delivery' && <DocumentsPage projectId={project.id} templateId={project.source_template?.id ?? undefined} onProjectChange={load} />}
            {!specialView && activeTab === 'activity' && <ActivityPage standalone projectId={project.id} projectName={project.name} sub={(activeChild ?? 'history') as 'history' | 'reports'} onSubChange={subNav('activity')} />}
          </Suspense>
        </div>
      </div>
    </div>
    </ProjectCapabilitiesContext.Provider>
    </ProjectStatusContext.Provider>
    </ProjectArchivedContext.Provider>
  )
}
