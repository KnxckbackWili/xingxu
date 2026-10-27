import { DISPATCH_PLATFORMS, PLAN_EVENTS, PROJECT_EVENT_LABELS, planPayload } from '../../constants/projectEvents'
import { hasSystemPermission } from '../../constants/systemPermissions'
import { canAccessNav } from '../../constants/nav'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  Alert, Avatar, Card, Col, Row, Button, Tag, Typography, Space, Empty, Skeleton, Modal, Form, Input, InputNumber,
  Select, DatePicker, message, Progress, Segmented, Table, Radio, Pagination, Descriptions, Collapse, Steps,
} from 'antd'
import {
  AppstoreOutlined, CheckCircleFilled, FileTextOutlined, PlusOutlined, ReloadOutlined, StarOutlined, StarFilled, HistoryOutlined, UnorderedListOutlined, RightOutlined,
} from '@ant-design/icons'
import TemplateScope, { flatWorkItems, selectedWorkItems } from '../../components/TemplateScope'
import ProjectDeleteButton from '../../components/ProjectDeleteButton'
import { projectApi, type Project } from '../../api'
import { api, errMsg } from '../../api/client'
import { useAuth } from '../../stores/auth'
import VehicleProgressSummary from '../../components/VehicleProgressSummary'
import { STATUS_MAP, projectStatusMeta } from '../../constants/status'
import { DEFAULT_VEHICLE_DRAFT } from '../../constants/vehicles'
import { TIMEZONE_OPTIONS, DEFAULT_TIMEZONE } from '../../constants/timezones'
import { formatMonthDayRange } from '../../utils/date'
import { PROJECT_SHORTCUT_LIMIT, shortcutSectionLabel, useProjectShortcuts } from '../../hooks/useProjectShortcuts'
import { useSubmitLock } from '../../hooks/useSubmitLock'
import { useVehicleTypes, toVehicleTypeSelectOptions } from '../../hooks/useVehicleTypes'

import { WorkPageHeader } from '../../components/WorkPage'
import './ProjectListPage.css'

/** 项目列表 + 创建向导（项目资料 → 工作内容 → 确认创建）。 */
export default function ProjectListPage() {
  const [projectData, setProjectData] = useState<{ actor: string; projects: Project[] }>({ actor: '', projects: [] })
  const loadSequence = useRef(0)
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const createLock = useSubmitLock()
  const creationKey = useRef<string | null>(null)
  const templateRequest = useRef(0)
  const [templateLoading, setTemplateLoading] = useState(true)
  const [templateError, setTemplateError] = useState(false)
  const [loadError, setLoadError] = useState(false)
  const [form] = Form.useForm()
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
    <Button size="small" aria-label={`查看工作项：${project.name}`} onClick={event => { event.stopPropagation(); navigate(`/pm/projects/${project.id}/plan`) }}>工作项</Button>
    <Button size="small" aria-label={`查看周计划：${project.name}`} onClick={event => { event.stopPropagation(); navigate(`/pm/projects/${project.id}/plan?view=weeks`) }}>周计划</Button>
  </>
  const canCreate = hasSystemPermission(user, 'projects.create')
  // 车型字典（HYPE-63）：创建向导的车型选择统一来自后端字典，不再硬编码
  const { options: dictOptions, loading: dictLoading, error: dictError, reload: reloadDict } = useVehicleTypes()

  // 创建向导状态；选择内容按原工作项 ID 保存。
  const [templates, setTemplates] = useState<any[]>([])
  const [createStep, setCreateStep] = useState(0)
  const createStepTop = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => {
    if (!modalOpen) return
    const body = createStepTop.current?.closest('.ant-modal-body')
    if (body) body.scrollTop = 0
  }, [modalOpen, createStep])
  const [excludedTasks, setExcludedTasks] = useState<string[]>([])
  const [documentRequirements, setDocumentRequirements] = useState<any[]>([])
  const [procurementOptions, setProcurementOptions] = useState<any[]>([])
  const dispatchPlatform = Form.useWatch('dispatch_platform', form) ?? null
  const createVehicles = Form.useWatch('vehicles', form) ?? []
  const [tplId, setTplId] = useState(() => searchParams.get('template') || 'default')
  const [tplPhases, setTplPhases] = useState<any[]>([])
  const [selectedWorkIds, setSelectedWorkIds] = useState<Set<string>>(new Set())
  const previewDocuments = documentRequirements.filter(row => !row.is_group && row.stage_key !== 'legacy' && (!row.platform || row.platform === dispatchPlatform))
  const vehicleDocumentCount = previewDocuments.filter(row => row.scope === 'vehicle').length
  // 资料要求与已生成的待交资料不是同一个数：每车、每周与事件触发的要求在条件出现时才生成。
  const weeklyDocumentCount = previewDocuments.filter(row => row.scope !== 'vehicle' && row.timing_type === 'weekly').length
  const laterDocumentCount = previewDocuments.filter(row => row.scope !== 'vehicle' && ['on_trigger', 'on_demand'].includes(row.timing_type)).length
  const documentBreakdown = [vehicleDocumentCount && `每车 ${vehicleDocumentCount} 项在车辆建档后生成`, weeklyDocumentCount && `每周 ${weeklyDocumentCount} 项在现场实施后逐周生成`, laterDocumentCount && `事件触发或抽查 ${laterDocumentCount} 项在发生时生成`].filter(Boolean).join('；')
  const legacyDocumentCount = documentRequirements.filter(row => row.stage_key === 'legacy').length
  const documentStages = [...new Set(previewDocuments.map(row => row.stage_key))]
  const createTasks = flatWorkItems(tplPhases).filter(task => selectedWorkItems(tplPhases,[...selectedWorkIds],excludedTasks).includes(task.id))


  const load = async () => {
    const request = ++loadSequence.current
    const isCurrent = () => request === loadSequence.current && currentActor.current === actor
    setLoading(true)
    setLoadError(false)
    try {
      const [list, ov] = await Promise.all([
        projectApi.list(),
        hasSystemPermission(user, 'workspace.view') ? api.get('/dashboard/overview').catch(() => null) : Promise.resolve(null),
      ])
      const m: Record<string, { percent: number; overdue: boolean; critical: number }> = {}
      if (ov?.data?.projects) {
        ov.data.projects.forEach((p: any) => {
          if (typeof p.percent === 'number' && Number.isFinite(p.percent)) m[p.id] = { percent: p.percent, overdue: !!p.overdue, critical: p.critical_issues ?? 0 }
        })
      }
      if (isCurrent()) { setProjectData({ actor, projects: list }); setProgressMap(m) }
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
      setCreateStep(0)
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
  const unavailableProgressCount = projects.filter(project => !progressMap[project.id]).length

  // ===== 向导 =====
  const loadTemplates = async (tid?: string) => {
    setTemplateLoading(true)
    setTemplateError(false)
    try {
      const tl = await api.get('/templates')
      setTemplates(tl.data)
      await switchTemplate(tid ?? tplId)
    } catch {
      setTemplateLoading(false)
      setTemplateError(true)
    }
  }

  const switchTemplate = async (tid: string) => {
    const request = ++templateRequest.current
    setTplId(tid)
    setTemplateLoading(true)
    setTemplateError(false)
    setTplPhases([])
    setDocumentRequirements([])
    setProcurementOptions([])
    setSelectedWorkIds(new Set())
    setExcludedTasks([])
    try {
      const [tr, documents, procurements] = await Promise.all([api.get(`/templates/${tid}/work-items`), api.get(`/templates/${tid}/document-requirements`), api.get(`/templates/${tid}/procurements`)])
      if (request !== templateRequest.current) return
      const workPhases = tr.data.phases
      if (![workPhases, documents.data, procurements.data].every(Array.isArray)) throw new Error('模板资料返回格式无效')
      setTplPhases(workPhases)
      setDocumentRequirements(documents.data)
      setProcurementOptions(procurements.data)
      setSelectedWorkIds(new Set(flatWorkItems(workPhases).map(task => task.id)))
    } catch {
      if (request === templateRequest.current) setTemplateError(true)
    } finally {
      if (request === templateRequest.current) setTemplateLoading(false)
    }
  }

  // 模板选择默认只突出系统模板，预置场景模板收进“模板库”，减少首次创建时的选择负担。
  const quickTemplates = useMemo(() => templates.filter((t) => t.is_system), [templates])
  const libraryTemplates = useMemo(() => templates.filter((t) => !t.is_system), [templates])
  const renderTemplateOption = (t: any) => (
    <button
      type="button"
      key={t.id}
      onClick={() => switchTemplate(t.id)}
      disabled={saving}
      aria-pressed={tplId === t.id}
      className={`template-option${tplId === t.id ? ' is-selected' : ''}`}
    >
      <span className="template-option-icon">{t.is_system ? <StarFilled /> : <FileTextOutlined />}</span>
      <span className="template-option-copy">
        <strong>{t.name}</strong>
        <small>{t.description}</small>
      </span>
      {tplId === t.id && <CheckCircleFilled className="template-option-check" />}
    </button>
  )

  const create = async (values: any) => {
    if (templateLoading || templateError || !createLock.tryAcquire()) return
    setSaving(true)
    creationKey.current ??= globalThis.crypto?.randomUUID?.() ?? `local-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
    try {
      const data = {
        name: values.name,
        abbreviation: values.abbreviation,
        client: values.client,
        location: values.location,
        timezone: values.timezone || DEFAULT_TIMEZONE,
        start_date: values.range[0].format('YYYY-MM-DD'),
        end_date: values.range[1].format('YYYY-MM-DD'),
        description: values.description,
        status: 'preparing',
        dispatch_platform: values.dispatch_platform ?? null,
        event_plans: planPayload(values.event_plans),
        client_server: values.client_server ?? false,
        new_vehicles: values.new_vehicles ?? true,
        overseas: values.overseas ?? false,
      }
      const p = await projectApi.create({
        ...data,
        vehicles: (values.vehicles ?? []).map((v: any) => ({
          vehicle_type: v.vehicle_type, model_name: v.model_name,
          quantity: Number(v.quantity), notes: v.notes || '',
        })),
        work_item_ids: selectedWorkItems(tplPhases,[...selectedWorkIds],excludedTasks), template_id: tplId, client_uuid: creationKey.current,
      })
      const generated = p.initial_generation ?? { tasks: 0, check_items: 0, zero_target_tasks: 0 }

      if (selectedWorkIds.size === 0) {
        message.warning('项目已创建，尚未选择工作项；可在计划页从模板带入。')
      } else if (generated.tasks === 0) {
        // C1-1：选了模块但生成的实施任务为 0（所选模块均为「仅准备项」）→ 不再误报成功
        message.warning('项目资料已建立，尚未加入执行工作；可在项目计划中从方案补充工作。')
      } else {
        const definitions = generated.check_definitions ?? generated.check_items
        const vehicleDefinitions = generated.vehicle_check_definitions ?? 0
        message.success(`项目已创建，生成 ${generated.tasks} 项工作、${definitions} 项检查要求${vehicleDefinitions ? `（其中 ${vehicleDefinitions} 项按车辆，车辆建档后逐车生成）` : ''}`)
      }
      setModalOpen(false)
      form.resetFields()
      creationKey.current = null
      navigate(`/pm/projects/${p.id}/overview`)
    } catch (e) {
      message.error(errMsg(e))
    } finally {
      setSaving(false)
      createLock.release()
    }
  }

  return (
    <div className="project-library-page">
      {loadError && <Alert type="warning" showIcon message="项目列表加载失败" description="列表可能不是最新的，请重新加载。" action={<Button onClick={load}>重新加载</Button>} style={{ marginBottom: 16 }} />}
      {!loading && !loadError && unavailableProgressCount > 0 && <Alert type="warning" showIcon message="部分项目进度与风险暂不可用"
        description={`${unavailableProgressCount} 个项目尚未取得进度与风险数据；这些项目不会计入进度筛选，项目本身仍可打开。`}
        action={<Button onClick={() => void load()}>重试进度</Button>} style={{ marginBottom: 16 }} />}
      <WorkPageHeader title="项目" description="打开项目，查看工作项、维护周计划或处理现场问题。"
        meta={loadError ? '列表暂不可用' : `${filtered.length} 个项目`}
        primary={canCreate ? <Button type="primary" icon={<PlusOutlined />} onClick={() => { setCreateStep(0); setModalOpen(true) }}>新建项目</Button> : undefined}
        tools={<><Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()} aria-label="刷新项目列表">刷新</Button>{canAccessNav('/pm/inventory', user) && <Button onClick={() => navigate('/pm/inventory')}>物品总览</Button>}{canAccessNav('/pm/project-recycle-bin', user) && <Button aria-label="项目回收站" onClick={() => navigate('/pm/project-recycle-bin')}>回收站</Button>}</>} />

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
            <Button type="primary" icon={<PlusOutlined />} onClick={() => { setCreateStep(0); setModalOpen(true) }}>
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
            { title: '收藏', key: 'favorite', width: 60, render: (_, p) => favoriteButton(p) },
            {
              title: '项目', dataIndex: 'name',
              render: (v: string, p) => (
                <Space size={6} wrap className="project-table-name">
                  <span style={{ fontWeight: 600 }}>{v}</span>

                  {progressMap[p.id]?.overdue && <Tag color="red" style={{ fontSize: 10 }}>逾期</Tag>}
                  {!!progressMap[p.id]?.critical && <Tag color="volcano" style={{ fontSize: 10 }}>严重问题 {progressMap[p.id].critical}</Tag>}
                </Space>
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
              title: '项目进度', width: 160,
              render: (_, p) => (
                progressMap[p.id] ?
                <div className="project-progress-row">
                  <Progress percent={progressMap[p.id].percent} size="small" showInfo={false} style={{ flex: 1 }} aria-label={`${p.name} 进度`} />
                  <Typography.Text style={{ fontSize: 11 }}>{progressMap[p.id].percent}%</Typography.Text>
                </div> : <Typography.Text type="secondary">进度暂不可用</Typography.Text>
              ),
            },
            { title:'车辆进度',width:180,render:(_,p)=><VehicleProgressSummary value={p.vehicle_progress}/> },
            { title:'逾期资料',width:110,render:(_,p)=>p.document_attention?<Button type="link" size="small" onClick={event=>{event.stopPropagation();navigate(`/pm/projects/${p.id}/documents?filter=overdue`)}}>{p.document_attention.overdue_count} 项</Button>:<Typography.Text type="secondary">未读取</Typography.Text> },
            {
              title: '周期', width: 140,
              render: (_, p) => {
                const overdue = progressMap[p.id]?.overdue
                return (
                  <Space size={4}>
                    <Typography.Text type={overdue ? 'danger' : 'secondary'} style={{ fontSize: 12 }}>
                      {formatMonthDayRange(p.start_date, p.end_date)}
                    </Typography.Text>
                    {overdue && <Tag color="red" style={{ fontSize: 10 }}>已延期</Tag>}
                  </Space>
                )
              },
            },
            { title: '客户', dataIndex: 'client', ellipsis: true, render: (v: string) => v ? <Typography.Text strong style={{ fontSize: 12 }}>{v}</Typography.Text> : '-' },
            {
              title: '负责人', width: 130,
              render: (_, p) => (
                <Space size={6}>
                  <Avatar size={24} style={{ background: 'var(--agv-primary-soft)', color: 'var(--agv-primary)', fontSize: 11, flexShrink: 0 }}>
                    {p.manager_name?.[0] || '未'}
                  </Avatar>
                  <span style={{ fontSize: 12 }}>{p.manager_name || '未分配'}</span>
                </Space>
              ),
            },
            {
              title: '操作', key: 'action', width: 250,
              render: (_, p) => (
                <Space wrap>
                <Button
                  type="link"
                  size="small"
                  style={{ padding: 0 }}
                  onClick={(e) => { e.stopPropagation(); navigate(`/pm/projects/${p.id}`) }}
                >
                  查看
                </Button>
                {quickLinks(p)}

                <ProjectDeleteButton project={p} onDeleted={() => removeProject(p.id)} />
                </Space>
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
                    </div> : <Typography.Text type="secondary">进度暂不可用</Typography.Text>}
                    <div aria-label={`${p.name}车辆进度`}><VehicleProgressSummary value={p.vehicle_progress}/></div>
                    <Typography.Text type="secondary">逾期资料：{p.document_attention ? `${p.document_attention.overdue_count} 项` : '未读取'}</Typography.Text>
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

      {/* ===== 创建项目 ===== */}
      <Modal
        className="project-create-modal"
        title="新建项目"
        open={modalOpen}
        onCancel={() => { if (!saving) setModalOpen(false) }}
        maskClosable={false}
        closable={!saving}
        cancelButtonProps={{ disabled: saving }}
        okButtonProps={{ disabled: templateLoading || templateError || dictLoading || !!dictError }}
        onOk={() => form.submit()}
        confirmLoading={saving}
        okText="创建项目"
        cancelText="取消"
        width={900}
        footer={<Space wrap>
          <Button disabled={saving} onClick={() => setModalOpen(false)}>取消</Button>
          {createStep > 0 && <Button disabled={saving} onClick={() => setCreateStep((step) => step - 1)}>上一步</Button>}
          <Button type="primary" loading={saving} disabled={dictLoading || !!dictError || (createStep > 0 && (templateLoading || templateError))} onClick={async () => {
            if (createStep === 0) { try { await form.validateFields(); setCreateStep(1) } catch { /* 表单显示具体缺项 */ } }
            else if (createStep === 1) setCreateStep(2)
            else form.submit()
          }}>{createStep === 0 ? '选择工作内容' : createStep === 1 ? '检查并创建' : '创建筹备项目'}</Button>
        </Space>}
        styles={{ body: { maxHeight: 'min(70vh, calc(100dvh - 180px))', overflowY: 'auto' } }}
        afterOpenChange={(open) => { if (open) { setCreateStep(0); loadTemplates() } }}
      >
        {templateError && <Alert type="error" showIcon message="模板加载失败，暂不能创建项目" action={<Button onClick={() => loadTemplates()}>重新加载模板</Button>} style={{ marginBottom: 12 }} />}
        {templateLoading && <Typography.Paragraph type="secondary" role="status">正在加载模板，请稍候…</Typography.Paragraph>}
        <div ref={createStepTop}>
          <Steps className="project-create-steps" responsive={false} labelPlacement="vertical" size="small" current={createStep} items={[{ title: '项目资料' }, { title: '工作内容' }, { title: '确认创建' }]} style={{ marginBottom: 20 }} />
        </div>
        <div style={{ display: createStep === 1 ? 'block' : 'none' }}>
        <Typography.Text strong className="create-section-title">这次项目要做哪些工作</Typography.Text>
        <Typography.Paragraph type="secondary" className="create-section-help">
          已选标准工作内容，可直接继续；需要调整时，取消不做的工作或展开任务修改数量。
        </Typography.Paragraph>
                  <div className="template-picker">
            {quickTemplates.map(renderTemplateOption)}
          </div>
          {libraryTemplates.length > 0 && (
            <Collapse
              size="small"
              ghost
              defaultActiveKey={[]}
              style={{ marginTop: 4 }}
              items={[{
                key: 'library',
                label: `换一个项目模板（${libraryTemplates.length}）`,
                children: <div className="template-picker">{libraryTemplates.map(renderTemplateOption)}</div>,
              }]}
            />
          )}

        <div className="create-content-scope">
          <TemplateScope phases={tplPhases} selected={[...selectedWorkIds]} onSelected={(ids) => setSelectedWorkIds(new Set(ids))} excluded={excludedTasks} onExcluded={setExcludedTasks} review showAll compact disabled={saving} />
        </div>
        </div>
        <div style={{ display: createStep === 0 ? 'block' : 'none' }}>
        <Typography.Text strong className="create-section-title">项目信息</Typography.Text>
                  <Form form={form} layout="vertical" onFinish={(values) => { if (createStep === 2) void create(values); else if (createStep === 0) setCreateStep(1) }} disabled={saving} scrollToFirstError={{ block: 'center' }} className="project-create-form">
            <Form.Item name="name" label="项目名称" rules={[{ required: true, whitespace: true, message: '请输入项目名称' }]}>
              <Input placeholder="例如：华东物流中心 AGV 实施项目" />
            </Form.Item>
            <Row gutter={12}>
              <Col xs={24} md={12}>
                <Form.Item name="range" label="实施周期" rules={[{ required: true, message: '请选择实施周期' }]}>
                  <DatePicker.RangePicker style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col xs={24} md={12}>
                <Alert type="info" showIcon message="新项目从筹备开始" description="创建先保存项目资料和实施方案。确认开始项目准备后，再安排人员与日程、完成进场评审；现场实施需单独确认。" />
              </Col>
            </Row>
            <Row gutter={12}>
              <Col xs={24} md={12}>
                <Form.Item name="client" label="客户" rules={[{ required: true, message: '请输入客户' }]}>
                  <Input placeholder="客户公司名" />
                </Form.Item>
              </Col>
              <Col xs={24} md={12}>
                <Form.Item name="location" label="地点" rules={[{ required: true, message: '请输入项目地点' }]}>
                  <Input placeholder="上海" />
                </Form.Item>
              </Col>
            </Row>

            <Typography.Text strong className="create-section-title">现场车辆</Typography.Text>
            <Form.Item name="new_vehicles" label="车辆来源" initialValue={true}>
              <Radio.Group options={[{ label: '包含新造车辆', value: true }, { label: '全部使用已有车辆', value: false }]} />
            </Form.Item>
            <Typography.Paragraph type="secondary" className="create-section-help">
              按车型台数计算任务目标，创建后可到「现场 → 车辆」调整。不确定车型时可选「其他/定制」。
            </Typography.Paragraph>
            {dictError && (
              <Alert
                type="warning" showIcon style={{ marginBottom: 12 }}
                message="车型字典加载失败"
                description={dictError}
                action={<Button size="small" onClick={() => reloadDict()}>重试</Button>}
              />
            )}
            <Form.List
              name="vehicles"
              initialValue={[{ ...DEFAULT_VEHICLE_DRAFT }]}
              rules={[{ validator: async (_, value) => {
                if (!value || value.length === 0) throw new Error('请至少录入一个车型')
                for (const v of value) {
                  if (!v || !v.vehicle_type) throw new Error('请选择车型')
                  if (!v.quantity || Number(v.quantity) <= 0) throw new Error('台数必须大于 0')
                }
              } }]}
            >
              {(fields, { add, remove }, { errors }) => (
                <>
                  {fields.map(({ key, ...field }) => (
                    <Row gutter={8} align="middle" key={key} className="create-vehicle-row">
                      <Col xs={24} md={7}>
                        <Form.Item
                          {...field}
                          name={[field.name, 'vehicle_type']}
                          label="车型"
                          rules={[{ required: true, message: '请选择车型' }]}
                          style={{ marginBottom: 12 }}
                        >
                          <Select placeholder="车型" loading={dictLoading} options={toVehicleTypeSelectOptions(dictOptions)} />
                        </Form.Item>
                      </Col>
                      <Col xs={24} md={8}>
                        <Form.Item
                          {...field}
                          name={[field.name, 'model_name']}
                          label="型号"
                          rules={[{ required: true, message: '请输入型号' }]}
                          style={{ marginBottom: 12 }}
                        >
                          <Input placeholder="型号（如 T6-800）" />
                        </Form.Item>
                      </Col>
                      <Col xs={24} md={5}>
                        <Form.Item
                          {...field}
                          name={[field.name, 'quantity']}
                          label="台数"
                          rules={[{ required: true, message: '台数' }]}
                          style={{ marginBottom: 12 }}
                        >
                          <InputNumber min={1} placeholder="台数" style={{ width: '100%' }} />
                        </Form.Item>
                      </Col>
                      <Col xs={24} md={4}>
                        <Button
                          type="text"
                          danger
                          disabled={fields.length <= 1}
                          onClick={() => remove(field.name)}
                          style={{ marginBottom: 12 }}
                        >
                          删除
                        </Button>
                      </Col>
                    </Row>
                  ))}
                  <Button type="dashed" size="small" icon={<PlusOutlined />} onClick={() => add({ ...DEFAULT_VEHICLE_DRAFT })} block>
                    添加车型
                  </Button>
                  <Form.ErrorList errors={errors} />
                </>
              )}
            </Form.List>

            <Collapse className="create-optional-settings" items={[{ key: 'settings', label: '其他资料：关键事件、调度平台、服务器、地区与时区', forceRender: true, children: <>
            <Row gutter={12}>
              <Col xs={24} md={12}>
                <Form.Item name="overseas" label="实施地区" initialValue={false}><Radio.Group options={[{ label: '国内', value: false }, { label: '海外', value: true }]} /></Form.Item>
              </Col>
              <Col xs={24} md={12}>
                <Form.Item name="timezone" label="现场时区" initialValue={DEFAULT_TIMEZONE} tooltip="今日任务与填报撤回按现场时区判定，海外现场请选择当地时区。"><Select options={TIMEZONE_OPTIONS} /></Form.Item>
              </Col>
              <Col xs={24} md={12}>
                <Form.Item name="client_server" label="服务器由谁提供" initialValue={false}>
                  <Radio.Group options={[{ label: '我方提供', value: false }, { label: '客户提供', value: true }]} />
                </Form.Item>
              </Col>
              <Col xs={24} md={12}>
                <Form.Item name="dispatch_platform" label="调度平台"><Select aria-label="调度平台" allowClear options={DISPATCH_PLATFORMS} placeholder="选择 NDC / GRACE / 集成" /></Form.Item>

              </Col>
              <Col xs={24} md={12}>
                <Form.Item name="abbreviation" label="项目简称（选填）"><Input placeholder="例如：华东物流" /></Form.Item>
              </Col>
            </Row>
            <Row gutter={12}>{PLAN_EVENTS.map(key => <Col xs={24} md={8} key={key}><Form.Item name={["event_plans", key]} label={`${PROJECT_EVENT_LABELS[key]}计划日期`}><DatePicker style={{ width: '100%' }} /></Form.Item></Col>)}</Row>
            </> }]} />
          </Form>
        </div>
        {createStep === 2 && <div>
          <Typography.Title level={4}>{form.getFieldValue('name')}</Typography.Title>
          <Descriptions className="create-confirm-summary" column={2} items={[
            { key: 'client', label: '客户', children: form.getFieldValue('client') },
            { key: 'location', label: '地点', children: form.getFieldValue('location') },
            { key: 'range', label: '周期', children: (form.getFieldValue('range') ?? []).map((date: any) => date.format('YYYY-MM-DD')).join(' 至 ') },
            { key: 'vehicles', label: '车辆', children: `${createVehicles.reduce((count: number, vehicle: any) => count + (Number(vehicle.quantity) || 0), 0)} 台` },
            { key: 'template', label: '工作模板', children: templates.find((template) => template.id === tplId)?.name },
            { key: 'platform', label: '调度平台', children: DISPATCH_PLATFORMS.find(platform => platform.value === form.getFieldValue('dispatch_platform'))?.label || '未设置' },
            ...PLAN_EVENTS.map(key => ({ key, label: `${PROJECT_EVENT_LABELS[key]}计划日期`, children: form.getFieldValue(['event_plans', key])?.format('YYYY-MM-DD') || '未安排' })),
            { key: 'work', label: '工作内容', children: `${createTasks.length} 项工作 · ${previewDocuments.length} 项资料要求${documentBreakdown ? `（${documentBreakdown}）` : ''}` },
          ]} />
          <Alert type="info" showIcon message="保存为筹备，准备好后再开始" description="任务、检查与资料要求一起保存；创建后先核对任务，再安排人员、发布日程。开始现场实施需单独确认。" />
          <Collapse style={{ marginTop: 16 }} items={[{ key: 'documents', label: `查看资料要求（${previewDocuments.length} 项）`, children: <section className="create-preparation-preview" aria-label="项目资料要求预览">
            <Typography.Title level={5}>资料清单 · {previewDocuments.length} 项要求</Typography.Title>
            <Typography.Paragraph type="secondary">按当前调度平台显示第4–9阶段的资料要求；每车资料在车辆完整建档后生成，周期和事件触发资料按相应条件生成，尚未提交。</Typography.Paragraph>
            <div className="create-preparation-groups">
              {documentStages.map(stage => <section key={stage}>
                <Typography.Text strong>第{stage}阶段</Typography.Text>
                <ul>{previewDocuments.filter(row => row.stage_key === stage).map(row => <li key={row.id}>{row.code} {row.name} {row.scope === 'vehicle' && <Tag>每车</Tag>}{row.required && <Tag color="blue">必需</Tag>}</li>)}</ul>
              </section>)}
            </div>
            {!previewDocuments.length && <Typography.Text type="secondary">当前模板与平台没有匹配的标准资料要求，创建后可在资料清单中明确添加。</Typography.Text>}
            {legacyDocumentCount > 0 && <Alert type="info" message={`历史待分类 ${legacyDocumentCount} 项`} description="历史来源保留，需在模板资料要求中明确分类；不计作标准资料或已满足要求。" />}
            <Typography.Paragraph type="secondary">常用采购库 {procurementOptions.length} 项可选，不会自动带入项目；创建后按实际采购需求选择录入。</Typography.Paragraph>
          </section> }]} />
        </div>}
      </Modal>
    </div>
  )
}
