import { hasSystemPermission } from '../../constants/systemPermissions'
import { canAccessNav } from '../../constants/nav'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  Alert, Card, Col, Row, Button, Tag, Typography, Space, Empty, Skeleton, Input,
  Select, message, Progress, Segmented, Table, Pagination,
} from 'antd'
import {
  AppstoreOutlined, DeleteOutlined, PlusOutlined, StarOutlined, StarFilled, HistoryOutlined, UnorderedListOutlined, RightOutlined,
} from '@ant-design/icons'
import ProjectDeleteButton from '../../components/ProjectDeleteButton'
import { projectApi, type Project } from '../../api'
import { api } from '../../api/client'
import { useAuth } from '../../stores/auth'
import VehicleProgressSummary from '../../components/VehicleProgressSummary'
import { STATUS_MAP, projectStatusMeta } from '../../constants/status'
import { formatMonthDayRange } from '../../utils/date'
import { PROJECT_SHORTCUT_LIMIT, shortcutSectionLabel, useProjectShortcuts } from '../../hooks/useProjectShortcuts'

import { WorkPageHeader } from '../../components/WorkPage'
import ProjectCreateModal from './ProjectCreateModal'
import './ProjectListPage.css'
import { RefreshAction } from '../../components/IconAction'

/** 项目列表；新建项目为一屏快速创建，其余资料进项目后按准备清单补全。 */
export default function ProjectListPage() {
  const [projectData, setProjectData] = useState<{ actor: string; projects: Project[] }>({ actor: '', projects: [] })
  const loadSequence = useRef(0)
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [createTemplate, setCreateTemplate] = useState<string | null>(null)
  const [loadError, setLoadError] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [progressFilter, setProgressFilter] = useState<string>('')
  const [favoritesOnly, setFavoritesOnly] = useState(false)
  const [cardPage, setCardPage] = useState(1)
  const [cardPageSize, setCardPageSize] = useState(12)
  // 卡片/表格视图切换（记住上次选择）
  const [viewMode, setViewMode] = useState<'card' | 'table'>(() => {
    try {
      const stored = localStorage.getItem('agvpm_proj_view')
      if (stored === 'card' || stored === 'table') return stored
    } catch { /* Browser storage may be unavailable. */ }
    return window.matchMedia('(max-width: 767px)').matches ? 'card' : 'table'
  })
  const switchView = (v: any) => { setViewMode(v); try { localStorage.setItem('agvpm_proj_view', v) } catch { /* The current view still works. */ } }
  const [progressMap, setProgressMap] = useState<Record<string, { percent: number; overdue: boolean; critical: number }>>({})
  const [progressFailed, setProgressFailed] = useState(false)
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { user } = useAuth()
  const actor = JSON.stringify([user?.id, user?.role, user?.permission_version, user?.permission_overrides, user?.system_permissions])
  const currentActor = useRef(actor)
  currentActor.current = actor
  const projects = projectData.actor === actor ? projectData.projects : []
  const removeProject = (id: string) => setProjectData(current => ({ ...current, projects: current.projects.filter(item => item.id !== id) }))
  const shortcuts = useProjectShortcuts(user?.id)
  const recentProjects = shortcuts.recent.flatMap(item => {
    const project = projects.find(project => project.id === item.id)
    const section = ['activity','history'].includes(item.section) && !hasSystemPermission(user, 'system.audit.read') ? 'overview' : item.section
    return project ? [{ ...item, section, project }] : []
  }).slice(0, 3)
  const favoriteButton = (project: Project) => {
    const saved = shortcuts.favorites.includes(project.id)
    return <Button className={saved ? 'project-favorite is-active' : 'project-favorite'} type="text"
      aria-label={`${saved ? '取消收藏' : '收藏项目'}：${project.name}`} aria-pressed={saved}
      title={saved ? '取消收藏' : '收藏项目'} icon={saved ? <StarFilled /> : <StarOutlined />}
      onClick={event => { event.stopPropagation(); if (!shortcuts.toggleFavorite(project.id)) message.info(`最多收藏 ${PROJECT_SHORTCUT_LIMIT} 个项目，请先取消部分收藏`) }} />
  }
  const quickLinks = (project: Project) => <>
    <Button type="link" size="small" aria-label={`查看工作项：${project.name}`} onClick={event => { event.stopPropagation(); navigate(`/pm/projects/${project.id}/plan`) }}>工作项</Button>
    <Button type="link" size="small" aria-label={`查看周计划：${project.name}`} onClick={event => { event.stopPropagation(); navigate(`/pm/projects/${project.id}/plan?view=weeks`) }}>周计划</Button>
  </>
  const overdueDocs = (project: Project) => !!project.document_attention?.overdue_count && <Tag color="red" className="project-overdue-docs" onClick={event => { event.stopPropagation(); navigate(`/pm/projects/${project.id}/documents?filter=overdue`) }}>逾期资料 {project.document_attention.overdue_count}</Tag>
  const canCreate = hasSystemPermission(user, 'projects.create')



  const load = async () => {
    const request = ++loadSequence.current
    const isCurrent = () => request === loadSequence.current && currentActor.current === actor
    setLoading(true)
    setLoadError(false)
    try {
      const wantsProgress = hasSystemPermission(user, 'workspace.view')
      const [list, ov] = await Promise.all([
        projectApi.list(),
        wantsProgress ? api.get('/dashboard/overview').catch(() => null) : Promise.resolve(null),
      ])
      const m: Record<string, { percent: number; overdue: boolean; critical: number }> = {}
      if (ov?.data?.projects) {
        ov.data.projects.forEach((p: any) => {
          if (typeof p.percent === 'number' && Number.isFinite(p.percent)) m[p.id] = { percent: p.percent, overdue: !!p.overdue, critical: p.critical_issues ?? 0 }
        })
      }
      if (isCurrent()) { setProjectData({ actor, projects: list }); setProgressMap(m); setProgressFailed(wantsProgress && !ov) }
    } catch (e) {
      if (isCurrent()) setLoadError(true)
    } finally {
      if (isCurrent()) setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    return () => { loadSequence.current++ }
  }, [actor])

  useEffect(() => {
    if (searchParams.get('create') === '1') {
      setCreateTemplate(searchParams.get('template'))
      setModalOpen(true)
      setSearchParams({}, { replace: true })
    }
  }, [searchParams, setSearchParams])

  const filtered = useMemo(() => {
    let list = [...projects]
    if (favoritesOnly) list = list.filter(project => shortcuts.favorites.includes(project.id))
    if (keyword.trim()) {
      const k = keyword.trim().toLowerCase()
      list = list.filter(
        (p) =>
          p.name.toLowerCase().includes(k) ||
          (p.client ?? '').toLowerCase().includes(k) ||
          (p.abbreviation ?? '').toLowerCase().includes(k) ||
          (p.location ?? '').toLowerCase().includes(k),
      )
    }
    if (statusFilter) list = list.filter((p) => p.status === statusFilter)
    if (progressFilter) {
      list = list.filter((p) => {
        const prog = progressMap[p.id]
        if (progressFilter === 'overdue') return p.document_attention ? p.document_attention.overdue_count > 0 : !!prog?.overdue
        if (!prog) return false
        const pct = prog.percent
        if (progressFilter === 'not_started') return pct <= 0
        if (progressFilter === 'running') return pct > 0 && pct < 100
        if (progressFilter === 'completed') return pct >= 100
        return true
      })
    }
    return list
  }, [projects, keyword, statusFilter, progressFilter, progressMap, favoritesOnly, shortcuts.favorites])

  useEffect(() => {
    setCardPage(1)
  }, [keyword, statusFilter, progressFilter, favoritesOnly])

  const cardPageCount = Math.max(1, Math.ceil(filtered.length / cardPageSize))
  const currentCardPage = Math.min(cardPage, cardPageCount)
  const shownCards = filtered.slice((currentCardPage - 1) * cardPageSize, currentCardPage * cardPageSize)


  return (
    <div className="project-library-page">
      {loadError && <Alert type="warning" showIcon message="项目列表加载失败" description="列表可能不是最新的，请重新加载。" action={<Button onClick={load}>重新加载</Button>} style={{ marginBottom: 16 }} />}
      {/* A project without a known vehicle count says so in its own row; the banner is for a failed progress request. */}
      {!loading && !loadError && progressFailed && <Alert type="warning" showIcon message="项目进度与风险暂不可用"
        description="进度数据读取失败，进度筛选暂不准确；项目本身仍可打开。"
        action={<Button onClick={() => void load()}>重试进度</Button>} style={{ marginBottom: 16 }} />}
      <WorkPageHeader title="项目" description="打开项目，查看工作项、维护周计划或处理现场问题。"
        meta={loadError ? '列表暂不可用' : `${filtered.length} 个项目`}
        primary={canCreate ? <Button type="primary" icon={<PlusOutlined />} onClick={() => { setCreateTemplate(null); setModalOpen(true) }}>新建项目</Button> : undefined}
        tools={<><RefreshAction label="刷新项目列表" loading={loading} onClick={load} />{canAccessNav('/pm/inventory', user) && <Button icon={<AppstoreOutlined />} aria-label="物品总览" onClick={() => navigate('/pm/inventory')}>物品总览</Button>}{canAccessNav('/pm/project-recycle-bin', user) && <Button icon={<DeleteOutlined />} aria-label="项目回收站" onClick={() => navigate('/pm/project-recycle-bin')}>回收站</Button>}</>} />

      {shortcuts.temporary && <Alert className="project-shortcuts-notice" type="info" showIcon message="浏览器暂时无法保存，收藏与最近浏览仅在本次使用中保留。" />}
      {!loading && !loadError && recentProjects.length > 0 && <section className="project-recent" aria-label="最近浏览的项目">
        <div className="project-recent-heading"><span><HistoryOutlined /> 最近浏览</span><Button type="text" size="small" onClick={shortcuts.clearRecent}>清空记录</Button></div>
        <div className="project-recent-grid">{recentProjects.map(({ id, section, project }) =>
          <button key={id} className="project-recent-link" onClick={() => navigate(`/pm/projects/${id}/${section}`)}>
            <span className="project-recent-name">{project.name}</span>
            <span className="project-recent-section">继续查看{shortcutSectionLabel(section)} <RightOutlined /></span>
          </button>)}</div>
      </section>}
      <div className="project-library-toolbar">
        <div className="project-library-filters" aria-label="项目筛选">
          <Input.Search
            placeholder="搜索项目、客户或地点"
            allowClear
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            style={{ width: 260 }}
          />
          <Select
            placeholder="状态筛选"
            aria-label="按状态筛选"
            allowClear
            value={statusFilter || undefined}
            onChange={(v) => setStatusFilter(v ?? '')}
            style={{ width: 120 }}
            options={Object.entries(STATUS_MAP).map(([k, v]) => ({ label: v.label, value: k }))}
          />
          <Select
            placeholder="进度筛选"
            aria-label="按进度筛选"
            allowClear
            value={progressFilter || undefined}
            onChange={(v) => setProgressFilter(v ?? '')}
            style={{ width: 120 }}
            options={[
              { label: '未启动', value: 'not_started' },
              { label: '进行中', value: 'running' },
              { label: '已完成', value: 'completed' },
              { label: '已逾期', value: 'overdue' },
            ]}
          />
          <Button className="project-favorites-filter" aria-label="我的收藏" icon={favoritesOnly ? <StarFilled /> : <StarOutlined />} type={favoritesOnly ? 'primary' : 'default'} aria-pressed={favoritesOnly} onClick={() => setFavoritesOnly(value => !value)}>我的收藏</Button>
          {(keyword || statusFilter || progressFilter || favoritesOnly) && <Button className="project-clear-filters" type="link" onClick={() => { setKeyword(''); setStatusFilter(''); setProgressFilter(''); setFavoritesOnly(false) }}>清除筛选</Button>}
        </div>
        <div className="project-library-view-tools">
          <Segmented
            aria-label="项目展示方式"
            value={viewMode}
            onChange={switchView}
            options={[
              { label: <span title="卡片视图"><AppstoreOutlined /> 卡片</span>, value: 'card' },
              { label: <span title="表格视图"><UnorderedListOutlined /> 表格</span>, value: 'table' },
            ]}
          />
        </div>
      </div>

      {loading ? (
        <Row gutter={[16, 16]}>
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <Col xs={24} sm={12} lg={8} key={i}>
              <Card><Skeleton active paragraph={{ rows: 3 }} /></Card>
            </Col>
          ))}
        </Row>
      ) : loadError && projects.length === 0 ? null : filtered.length === 0 ? (
        <Empty className="project-library-empty" description={projects.length === 0 ? '还没有项目，创建第一个项目开始' : '没有匹配的项目'}>
          {projects.length === 0 && canCreate && (
            <Button type="primary" icon={<PlusOutlined />} onClick={() => { setCreateTemplate(null); setModalOpen(true) }}>
              新建项目
            </Button>
          )}
          {projects.length > 0 && (
            <Button size="small" onClick={() => { setKeyword(''); setStatusFilter(''); setProgressFilter(''); setFavoritesOnly(false) }}>清空筛选</Button>
          )}
        </Empty>
      ) : viewMode === 'table' ? (
        /* 表格视图：项目多时更高效 */
        <Table
          className="project-library-table"
          rowKey="id"
          dataSource={filtered}
          size="small"
          scroll={{ x: 1120 }}
          pagination={{
            defaultPageSize: 15,
            pageSizeOptions: [15, 30, 50],
            showSizeChanger: true,
            showQuickJumper: filtered.length > 50,
            showTotal: (total, range) => `${range[0]}-${range[1]} / 共 ${total} 个`,
            hideOnSinglePage: true,
          }}
          onRow={(p) => ({ onClick: () => navigate(`/pm/projects/${p.id}`), style: { cursor: 'pointer' } })}
          columns={[
            { title: <StarOutlined aria-label="收藏" />, key: 'favorite', width: 52, render: (_, p) => favoriteButton(p) },
            {
              title: '项目', dataIndex: 'name', width: 240,
              render: (v: string, p) => (
                <div className="project-table-name">
                  <Space size={6} wrap>
                    <span style={{ fontWeight: 600 }}>{v}</span>
                    {progressMap[p.id]?.overdue && <Tag color="red" style={{ fontSize: 10 }}>逾期</Tag>}
                    {!!progressMap[p.id]?.critical && <Tag color="volcano" style={{ fontSize: 10 }}>严重问题 {progressMap[p.id].critical}</Tag>}
                    {overdueDocs(p)}
                  </Space>
                  {p.client && <Typography.Text type="secondary" className="project-table-client">{p.client}</Typography.Text>}
                </div>
              ),
            },
            { title: '状态', width: 110, render: (_, p) => {
              const st = projectStatusMeta(p.status)
              return (
                <Space size={2}>
                  <Tag color={st.color}>{st.label}</Tag>
                  {st.label === '已延期' && <Typography.Text type="secondary" style={{ fontSize: 10 }}>{st.baseLabel}</Typography.Text>}
                </Space>
              )
            } },
            {
              title: '进度', width: 200,
              render: (_, p) => <div className="project-progress-cell">
                {progressMap[p.id] ? <div className="project-progress-row">
                  <Progress percent={progressMap[p.id].percent} size="small" showInfo={false} style={{ flex: 1 }} aria-label={`${p.name} 进度`} />
                  <Typography.Text style={{ fontSize: 12 }}>{progressMap[p.id].percent}%</Typography.Text>
                </div> : <Typography.Text type="secondary">{progressFailed ? '进度暂不可用' : '进度待核对'}</Typography.Text>}
                <VehicleProgressSummary compact value={p.vehicle_progress} />
              </div>,
            },
            {
              title: '周期', width: 200,
              render: (_, p) => {
                const overdue = progressMap[p.id]?.overdue
                return (
                  <Space size={4} className="project-period-cell">
                    <Typography.Text type={overdue ? 'danger' : 'secondary'} style={{ fontSize: 12, whiteSpace: 'nowrap' }}>
                      {formatMonthDayRange(p.start_date, p.end_date)}
                    </Typography.Text>
                    {overdue && <Tag color="red" style={{ fontSize: 10 }}>已延期</Tag>}
                  </Space>
                )
              },
            },
            {
              title: '负责人', width: 120,
              render: (_, p) => <span style={{ whiteSpace: 'nowrap' }}>{p.manager_name || '未分配'}</span>,
            },
            {
              title: '操作', key: 'action', width: 170,
              render: (_, p) => (
                <span className="row-icon-actions">
                {quickLinks(p)}
                <ProjectDeleteButton project={p} onDeleted={() => removeProject(p.id)} />
                </span>
              ),
            },
          ]}
        />
      ) : (
        /* 卡片视图：精简——名称/状态/风险 + 进度条 + 一行小字 */
        <>
        <Row gutter={[16, 16]}>
          {shownCards.map((p) => {
            const st = projectStatusMeta(p.status)
            const prog = progressMap[p.id]
            return (
              <Col xs={24} md={12} key={p.id}>
                <Card
                  className="project-library-card"
                  hoverable
                  onClick={() => navigate(`/pm/projects/${p.id}`)}
                  style={{ overflow: 'hidden' }}
                  title={
                    <div className="project-library-card-heading">
                      <div className="project-library-identity">
                        <span title={p.name} className="project-library-name">{p.name}</span>
                        <div className="project-library-tags">

                          <Tag color={st.color}>{st.label}</Tag>
                          {st.label === '已延期' && <Typography.Text type="secondary" style={{ fontSize: 11 }}>{st.baseLabel}</Typography.Text>}
                        </div>
                      </div>
                      {favoriteButton(p)}
                    </div>
                  }
                >
                  <Space direction="vertical" size={6} style={{ width: '100%' }}>
                    {prog ? <div className="project-progress-row project-card-progress">
                      <Progress
                        percent={prog.percent}
                        size="small"
                        showInfo={false}
                        aria-label={`${p.name} 进度`}
                        strokeColor={prog?.percent >= 100 ? 'var(--agv-success)' : prog?.overdue ? 'var(--agv-danger)' : 'var(--agv-primary)'}
                        style={{ flex: 1 }}
                      />
                      <Typography.Text className="project-card-percent">
                        {prog.percent}%
                      </Typography.Text>
                    </div> : <Typography.Text type="secondary">{progressFailed ? '进度暂不可用' : '进度待核对'}</Typography.Text>}
                    <div className="project-card-facts" aria-label={`${p.name}车辆进度`}><VehicleProgressSummary compact value={p.vehicle_progress}/>{overdueDocs(p)}</div>
                    <Typography.Text type="secondary" className="project-card-context">
                      {[p.client, p.location].filter(Boolean).join(' · ') || '客户与地点待补充'}
                    </Typography.Text>
                    <div className="project-card-meta">
                      <Typography.Text type="secondary">{formatMonthDayRange(p.start_date, p.end_date)}</Typography.Text>
                      <Typography.Text type="secondary">负责人：{p.manager_name || '未分配'}</Typography.Text>
                    </div>
                    {!!prog?.critical && (
                      <Typography.Text className="project-card-risk">
                        未解决严重问题 {prog.critical} 个
                      </Typography.Text>
                    )}
                    <div className="project-card-actions">
                    <Button type="link" size="small" aria-label={`进入项目：${p.name}`}
                      style={{ paddingInline: 0, fontSize: 14, color: 'var(--agv-primary)' }}
                      onClick={(event) => { event.stopPropagation(); navigate(`/pm/projects/${p.id}`) }}>
                      进入项目 <RightOutlined style={{ fontSize: 10 }} />
                    </Button>
                    {quickLinks(p)}

                    <ProjectDeleteButton project={p} onDeleted={() => removeProject(p.id)} />
                    </div>
                  </Space>
                </Card>
              </Col>
            )
          })}
        </Row>
        {filtered.length > cardPageSize && (
          <div className="project-card-pagination">
            <Pagination
              current={currentCardPage}
              pageSize={cardPageSize}
              total={filtered.length}
              showSizeChanger
              showQuickJumper={filtered.length > 50}
              pageSizeOptions={[12, 24, 48]}
              showTotal={(total, range) => `${range[0]}-${range[1]} / 共 ${total} 个`}
              onChange={(page, size) => { setCardPage(page); setCardPageSize(size) }}
            />
          </div>
        )}
        </>
      )}

      <ProjectCreateModal open={modalOpen} initialTemplate={createTemplate} onClose={() => setModalOpen(false)} />
    </div>
  )
}
