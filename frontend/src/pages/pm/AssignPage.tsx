import { useEffect, useMemo, useState, useRef } from 'react'
import {
  Card, Typography, Tag, Select, Space, message, Input, Table, Pagination, Empty, Modal, Drawer, Divider, Button, Tooltip,
  Progress, Segmented, Checkbox,
} from 'antd'
import {
  UserOutlined, ProjectOutlined, WarningOutlined, PlusOutlined,
} from '@ant-design/icons'
import { api,errMsg } from '../../api/client'
import { userApi, projectApi } from '../../api'
import { useAuth } from '../../stores/auth'
import { ROLE_LABEL } from '../../constants/roles'
import { STATUS_LABEL, STATUS_COLOR, ACTIVE_PROJECT_STATUSES } from '../../constants/status'
import { useMediaQuery } from '../../hooks/useMediaQuery'
import { MEDIA_QUERY } from '../../constants/breakpoints'
import { confirmMemberRemoval } from '../../api/memberRemoval'

/**
 * 安排人员：按人 / 按项目 两个视图（mode 切换），共用同一份数据与保存逻辑。
 * - people：以人为主——参与项目（全部 Tag，✕ 移除）、加入项目（Select 搜项目即加）、并行项目数
 * - projects：以项目为主——成员（全部 Tag，✕ 移除）、添加成员（Select 搜人即加）、项目进度
 * 一人可同时在多个项目（members 数组式保存，无任何单选限制）。
 */
export default function AssignPage({ mode = 'people' }: { mode?: 'people' | 'projects' }) {
  const isMobile = useMediaQuery(MEDIA_QUERY.mobile)
  const [users, setUsers] = useState<any[]>([])
  const [projects, setProjects] = useState<any[]>([])
  const [personSearch, setPersonSearch] = useState('')
  const [personPage, setPersonPage] = useState(1)
  const [projSearch, setProjSearch] = useState('')
  const [roleFilter, setRoleFilter] = useState<string>('')
  const [loadFilter, setLoadFilter] = useState<string>('')
  const [saving, setSaving] = useState<string | null>(null)
  const memberRequests=useRef(new Map<string,AbortController>())
  useEffect(()=>()=>{memberRequests.current.forEach(controller=>controller.abort())},[])
  const [selectedProjectId, setSelectedProjectId] = useState('')
  const [projectStatusFilter, setProjectStatusFilter] = useState('')
  const [candidateSearch, setCandidateSearch] = useState('')
  const [candidateRole, setCandidateRole] = useState('')
  const [candidateScope, setCandidateScope] = useState<string>('recommended')
  const [candidatePage, setCandidatePage] = useState(1)
  const [selectedCandidateIds, setSelectedCandidateIds] = useState<string[]>([])
  const [projPage, setProjPage] = useState(1)
  // 今日任务数（people-overview，负荷参考）
  const [overview, setOverview] = useState<Record<string, any>>({})
  // 人员配置池：只返回容量与项目数，不暴露无关项目详情。
  const [workload, setWorkload] = useState<Record<string, any>>({})
  // 人员详情 Drawer（查看完整分配 / 调整 / 移出，替代 Tag 墙直接操作）
  const [drawerUser, setDrawerUser] = useState<any | null>(null)
  const { user } = useAuth()
  const canEditProject = (project: any) => !!project && user?.permission_overrides?.['project.manage_members'] !== false && (Array.isArray(project.capabilities) ? project.capabilities.includes('project.manage_members') : ['admin', 'pm'].includes(user?.role ?? ''))

  const load = async () => {
    try {
      const [u, p, po, pool] = await Promise.all([
        userApi.listActive(),
        projectApi.list(),
        api.get('/dashboard/people-overview').then((r) => r.data).catch(() => []),
        api.get('/dashboard/assignment-pool').then((r) => r.data.items).catch(() => []),
      ])
      setUsers(u.filter((person: any) => !['admin', 'director'].includes(person.role)))
      setProjects(p.filter((x: any) => ACTIVE_PROJECT_STATUSES.includes(x.status)))
      setOverview(Object.fromEntries(po.map((x: any) => [x.id, x])))
      setWorkload(Object.fromEntries(pool.map((x: any) => [x.id, x])))
    } catch {
      message.error('数据加载失败')
    }
  }
  useEffect(() => {
    load()
  }, [])

  useEffect(() => {
    if (!selectedProjectId && projects.length) setSelectedProjectId(projects[0].id)
  }, [projects, selectedProjectId])

  useEffect(() => {
    setCandidatePage(1)
  }, [selectedProjectId, candidateSearch, candidateRole, candidateScope])

  useEffect(() => {
    setPersonPage(1)
  }, [personSearch, roleFilter, loadFilter])

  useEffect(() => {
    setSelectedCandidateIds([])
  }, [selectedProjectId])

  const memberSet = useMemo(() => {
    const map: Record<string, Set<string>> = {}
    for (const p of projects) {
      map[p.id] = new Set(p.members ?? [])
      if (p.manager) map[p.id].add(p.manager)
    }
    return map
  }, [projects])

  /** 一人参与的未归档项目数，优先使用跨项目配置池的真实总数。 */
  const projCountOf = (uid: string) => workload[uid]?.project_count
    ?? projects.filter((p) => memberSet[p.id]?.has(uid)).length

  const saveProjectMembers = async (pid: string, nextMembers: string[]) => {
    if (!canEditProject(projects.find(p => p.id === pid)) || memberRequests.current.has(pid)) return false
    const before = memberSet[pid] ?? new Set<string>()
    const next = new Set(nextMembers)
    setSaving(pid)
    const scope=new AbortController();memberRequests.current.set(pid,scope)
    try {
      const removed=(projects.find(p=>p.id===pid)?.members || []).filter((id:string)=>!next.has(id))
      const confirmed=await confirmMemberRemoval(pid,removed,scope.signal)
      if(confirmed===undefined || scope.signal.aborted)return false
      const result = await api.put(`/projects/${pid}`, { members: [...next], version: projects.find(p => p.id === pid)?.version ?? 0,...(removed.length?{member_removal_confirmations:confirmed}:{}) })
      setProjects((list) => list.map((p) => (p.id === pid ? { ...p, ...result.data } : p)))
      setWorkload((current) => {
        const changed = { ...current }
        for (const uid of new Set([...before, ...next])) {
          const delta = (next.has(uid) ? 1 : 0) - (before.has(uid) ? 1 : 0)
          if (!delta || !changed[uid]) continue
          const projectCount = Math.max(0, (changed[uid].project_count ?? 0) + delta)
          changed[uid] = {
            ...changed[uid],
            project_count: projectCount,
            is_recommended: (changed[uid].load_percent ?? 0) < 80 && projectCount < 3,
          }
        }
        return changed
      })
      return true
    } catch (e: any) {
      const detail = errMsg(e)
      message.error(detail)
      if (typeof detail === 'string' && detail.includes('未完成的已下达工作')) Modal.info({
        title: '请先交接已下达工作', content: <div><p>{detail}</p><a href={`/pm/projects/${pid}/schedule`}>去项目日程改派</a></div>,
      })
      if (e.response?.status === 409) await load()
      return false
    } finally {
      if(memberRequests.current.get(pid)===scope)memberRequests.current.delete(pid)
      setSaving(null)
    }
  }

  /** 加入/移除成员（数组式保存，支持一人多项目；本地同步防闪烁） */
  const setMember = async (pid: string, uid: string, add: boolean) => {
    if (!canEditProject(projects.find(p => p.id === pid))) return
    const next = new Set(memberSet[pid] ?? [])
    if (add) next.add(uid)
    else next.delete(uid)
    await saveProjectMembers(pid, [...next])
  }

  const roleOptions = useMemo(() => {
    const seen = new Set<string>()
    const list: { label: string; value: string }[] = []
    for (const u of users) {
      if (!seen.has(u.role)) {
        seen.add(u.role)
        list.push({ label: ROLE_LABEL[u.role] ?? u.role, value: u.role })
      }
    }
    return list
  }, [users])

  // ===== 按人视图 =====
  const personRows = useMemo(() => {
    let list = users
    const q = personSearch.trim().toLowerCase()
    if (q) list = list.filter((u) => (u.display_name ?? '').toLowerCase().includes(q))
    if (roleFilter) list = list.filter((u) => u.role === roleFilter)
    if (loadFilter === 'unassigned') list = list.filter((u) => projCountOf(u.id) === 0)
    if (loadFilter === 'busy') list = list.filter((u) => (workload[u.id]?.load_percent ?? 0) >= 100 || projCountOf(u.id) >= 4)
    if (loadFilter === 'available') list = list.filter((u) => (workload[u.id]?.load_percent ?? 0) < 80 && projCountOf(u.id) < 3)
    return list
  }, [users, personSearch, roleFilter, loadFilter, workload, projects, memberSet])
  const PERSON_PAGE_SIZE = 12
  const shownPersonRows = personRows.slice((personPage - 1) * PERSON_PAGE_SIZE, personPage * PERSON_PAGE_SIZE)

  const peopleView = (
    <Card
      size="small"
      title={<Space><UserOutlined style={{ color: '#1677ff' }} />人员负荷<Typography.Text type="secondary">{personRows.length} 人</Typography.Text></Space>}
    >
      <Space size={8} wrap style={{ marginBottom: 12 }}>
        <Input size="small" allowClear placeholder="搜姓名" style={{ width: 150 }} value={personSearch}
          onChange={(e) => setPersonSearch(e.target.value)} />
        <Select size="small" allowClear placeholder="角色" style={{ width: 120 }} value={roleFilter || undefined}
          onChange={(v) => setRoleFilter(v ?? '')} options={roleOptions} />
        <Select size="small" allowClear placeholder="负荷" style={{ width: 120 }} value={loadFilter || undefined}
          onChange={(v) => setLoadFilter(v ?? '')} options={[
            { label: '超负荷', value: 'busy' }, { label: '可安排', value: 'available' }, { label: '未分配', value: 'unassigned' },
          ]} />
      </Space>
      {isMobile ? (
        personRows.length === 0
          ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有符合条件的人员" />
          : (
            <>
              <div className="mobile-card-list">
                {shownPersonRows.map((u) => {
                  const projs = projects.filter((p) => memberSet[p.id]?.has(u.id))
                  const n = projCountOf(u.id)
                  const wl = workload[u.id]
                  const pct = wl?.load_percent ?? null
                  const today = overview[u.id]?.today_tasks ?? 0
                  return (
                    <Card key={u.id} size="small">
                      <Space direction="vertical" size={6} style={{ width: '100%' }}>
                        <div className="mobile-card-row">
                          <span className="mobile-card-title-sm">{u.display_name}</span>
                          <Tag>{ROLE_LABEL[u.role] ?? u.role}</Tag>
                        </div>
                        <div className="mobile-card-row">
                          <span className="mobile-card-label">当前项目</span>
                          <span className="mobile-card-value">
                            <Space size={4} wrap style={{ rowGap: 4 }}>
                              {projs.length === 0
                                ? <Typography.Text type="secondary" style={{ fontSize: 12 }}>未参与任何项目</Typography.Text>
                                : projs.slice(0, 2).map((p) => <Tag key={p.id} style={{ fontSize: 11 }}>{p.name}</Tag>)}
                              {projs.length > 2 && <Tag style={{ fontSize: 11, cursor: 'pointer' }} onClick={() => setDrawerUser(u)}>+{projs.length - 2}</Tag>}
                            </Space>
                          </span>
                        </div>
                        <div className="mobile-card-row">
                          <span className="mobile-card-label">负荷</span>
                          <span className="mobile-card-value">
                            <Space size={4} wrap style={{ rowGap: 4 }}>
                              <Tag style={{ fontSize: 11, color: n >= 4 ? '#cf1322' : n >= 3 ? '#ad4e00' : '#237804' }}>{n} 项目</Tag>
                              {pct != null && <Tag style={{ fontSize: 11, color: pct >= 100 ? '#cf1322' : pct >= 80 ? '#ad4e00' : '#237804' }}>周负荷 {pct}%</Tag>}
                              <Tag style={{ fontSize: 11 }} color={today > 0 ? 'cyan' : 'default'}>今日 {today}</Tag>
                              {n >= 4 && <Typography.Text style={{ fontSize: 11, color: '#cf1322' }}><WarningOutlined /> 超负荷</Typography.Text>}
                            </Space>
                          </span>
                        </div>
                        <div className="mobile-card-actions">
                          <Button className="touch-target" onClick={() => setDrawerUser(u)}>查看安排</Button>
                        </div>
                      </Space>
                    </Card>
                  )
                })}
              </div>
              {PERSON_PAGE_SIZE < personRows.length && (
                <Pagination simple size="small" current={personPage} pageSize={PERSON_PAGE_SIZE} total={personRows.length} onChange={setPersonPage} style={{ marginTop: 12, textAlign: 'right' }} />
              )}
            </>
          )
      ) : (
      <Table
        rowKey="id"
        size="small"
        scroll={{ x: 'max-content' }}
        pagination={{ defaultPageSize: 12, pageSizeOptions: [12, 24, 48], showSizeChanger: true, showTotal: (total) => `共 ${total} 人` }}
        loading={!users.length && !projects.length}
        dataSource={personRows}
        columns={[
          {
            title: '人员', dataIndex: 'display_name', width: 110, fixed: 'left' as const,
            render: (v: string, u: any) => (
              <Space size={6}>
                <Typography.Text strong>{v}</Typography.Text>
                <Tag color="default" style={{ fontSize: 10 }}>{ROLE_LABEL[u.role] ?? u.role}</Tag>
              </Space>
            ),
          },
          {
            title: '当前项目', key: 'projs',
            render: (_: any, u: any) => {
              const list = projects.filter((p) => memberSet[p.id]?.has(u.id))
              if (list.length === 0) return <Typography.Text type="secondary" style={{ fontSize: 12 }}>未参与任何项目</Typography.Text>
              return (
                <Space size={4} wrap>
                  {list.slice(0, 2).map((p) => (
                    <Tag key={p.id} style={{ fontSize: 11 }}>{p.name}</Tag>
                  ))}
                  {list.length > 2 && (
                    <Tag style={{ fontSize: 11, cursor: 'pointer' }} onClick={() => setDrawerUser(u)}>+{list.length - 2}</Tag>
                  )}
                </Space>
              )
            },
          },
          {
            title: '负荷', key: 'n', width: 130,
            render: (_: any, u: any) => {
              const n = projCountOf(u.id)
              const today = overview[u.id]?.today_tasks ?? 0
              const wl = workload[u.id]
              const pct = wl?.load_percent ?? null
              const color = n >= 4 ? '#cf1322' : n >= 3 ? '#ad4e00' : '#237804'
              return (
                <Space size={4} wrap>
                  <Tag style={{ fontSize: 11, color }}>{n} 项目</Tag>
                  {pct != null && (
                    <Tooltip title={`本周计划 ${wl.planned_hours}h / 可用 ${wl.available_hours}h（估算）`}>
                      <Tag style={{ fontSize: 11, color: pct >= 100 ? '#cf1322' : pct >= 80 ? '#ad4e00' : '#237804' }}>
                        周负荷 {pct}%
                      </Tag>
                    </Tooltip>
                  )}
                  <Tag style={{ fontSize: 11 }} color={today > 0 ? 'cyan' : 'default'}>今日 {today}</Tag>
                  {n >= 4 && <Typography.Text style={{ fontSize: 11, color: '#cf1322' }}><WarningOutlined /> 超负荷</Typography.Text>}
                </Space>
              )
            },
          },
          {
            title: '操作', key: 'ops', width: 100,
            render: (_: any, u: any) => (
              <Button size="small" onClick={() => setDrawerUser(u)}>查看安排</Button>
            ),
          },
        ]}
      />
      )}
    </Card>
  )

  // ===== 人员配置工作台 =====
  const projRows = useMemo(() => {
    let list = projects
    const q = projSearch.trim().toLowerCase()
    if (q) list = list.filter((p) => (p.name ?? '').toLowerCase().includes(q) || (p.client ?? '').toLowerCase().includes(q))
    if (projectStatusFilter) list = list.filter((p) => p.status === projectStatusFilter)
    return list
  }, [projects, projSearch, projectStatusFilter])
  const projPageCount = Math.max(1, Math.ceil(projRows.length / 12))
  const curProjPage = Math.min(projPage, projPageCount)
  const shownProjs = projRows.slice((curProjPage - 1) * 12, curProjPage * 12)
  const selectedProject = projects.find((project) => project.id === selectedProjectId) ?? null
  const canEdit = canEditProject(selectedProject)
  const currentMembers = selectedProject
    ? users.filter((person) => memberSet[selectedProject.id]?.has(person.id))
    : []
  if (selectedProject?.manager && !currentMembers.some((person) => person.id === selectedProject.manager)) {
    currentMembers.unshift({
      id: selectedProject.manager,
      display_name: selectedProject.manager_name || '项目负责人',
      role: 'pm',
    })
  }
  const candidateRows = useMemo(() => {
    if (!selectedProject) return []
    let list = users.filter((person) => !memberSet[selectedProject.id]?.has(person.id))
    const q = candidateSearch.trim().toLowerCase()
    if (q) {
      list = list.filter((person) => {
        return [person.display_name, ROLE_LABEL[person.role]]
          .some((value) => (value ?? '').toLowerCase().includes(q))
      })
    }
    if (candidateRole) list = list.filter((person) => person.role === candidateRole)
    if (candidateScope === 'recommended') list = list.filter((person) => workload[person.id]?.is_recommended ?? true)
    if (candidateScope === 'available') list = list.filter((person) => (workload[person.id]?.load_percent ?? 0) < 80)
    if (candidateScope === 'unassigned') list = list.filter((person) => projCountOf(person.id) === 0)
    return [...list].sort((a, b) => {
      const loadScore = (workload[a.id]?.load_percent ?? 0) - (workload[b.id]?.load_percent ?? 0)
      if (loadScore) return loadScore
      const projectScore = projCountOf(a.id) - projCountOf(b.id)
      return projectScore || a.display_name.localeCompare(b.display_name, 'zh-CN')
    })
  }, [selectedProject, users, memberSet, candidateSearch, candidateRole, candidateScope, workload, projects])
  const candidatePageSize = 20
  const shownCandidates = candidateRows.slice(
    (candidatePage - 1) * candidatePageSize,
    candidatePage * candidatePageSize,
  )

  const addSelectedCandidates = async () => {
    if (!selectedProject || selectedCandidateIds.length === 0) return
    const next = new Set(memberSet[selectedProject.id] ?? [])
    selectedCandidateIds.forEach((id) => next.add(id))
    const addedCount = selectedCandidateIds.length
    if (await saveProjectMembers(selectedProject.id, [...next])) {
      message.success(`已为「${selectedProject.name}」加入 ${addedCount} 人`)
      setSelectedCandidateIds([])
    }
  }

  const projectsView = (
    <div className="staffing-workbench">
      <aside className="staffing-projects">
        <div className="staffing-panel-heading">
          <div><ProjectOutlined /><Typography.Text strong>选择项目</Typography.Text></div>
          <Typography.Text type="secondary">{projRows.length} 个</Typography.Text>
        </div>
        <div className="staffing-project-filters">
          <Input allowClear placeholder="搜索项目或客户" value={projSearch}
            onChange={(event) => { setProjSearch(event.target.value); setProjPage(1) }} />
          <Select allowClear placeholder="项目状态" value={projectStatusFilter || undefined}
            onChange={(value) => { setProjectStatusFilter(value ?? ''); setProjPage(1) }}
            options={ACTIVE_PROJECT_STATUSES.map((value) => ({ value, label: STATUS_LABEL[value] ?? value }))} />
        </div>
        <div className="staffing-project-list">
          {shownProjs.map((project) => (
            <button key={project.id} type="button"
              className={`staffing-project-item ${selectedProjectId === project.id ? 'active' : ''}`}
              onClick={() => setSelectedProjectId(project.id)}>
              <span className="staffing-project-name">{project.name}</span>
              <span className="staffing-project-meta">
                <Tag color={STATUS_COLOR[project.status] ?? 'default'}>{STATUS_LABEL[project.status] ?? project.status}</Tag>
                <span>{memberSet[project.id]?.size ?? 0} 人</span>
              </span>
            </button>
          ))}
          {shownProjs.length === 0 && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配项目" />}
        </div>
        {projRows.length > 12 && (
          <Pagination simple size="small" current={curProjPage} pageSize={12} total={projRows.length}
            onChange={setProjPage} className="staffing-project-pagination" />
        )}
      </aside>

      <section className="staffing-main">
        {!selectedProject ? <Empty description="请先选择一个项目" /> : <>
          <div className="staffing-project-header">
            <div>
              <Space size={8} wrap>
                <Typography.Title level={5} style={{ margin: 0 }}>{selectedProject.name}</Typography.Title>
                <Tag color={STATUS_COLOR[selectedProject.status] ?? 'default'}>{STATUS_LABEL[selectedProject.status] ?? selectedProject.status}</Tag>
              </Space>
              <Typography.Text type="secondary">{selectedProject.client || '未填写客户'} · {selectedProject.location || '未填写地点'}</Typography.Text>
            </div>
            <div className="staffing-project-numbers">
              <span><strong>{currentMembers.length}</strong>当前成员</span>
              <span><strong>{candidateRows.length}</strong>匹配候选</span>
            </div>
          </div>

          {selectedProject.staffing_notes && (
            <div className="staffing-notes">
              <Typography.Text strong>资料中的人员安排参考</Typography.Text>
              <Typography.Paragraph style={{ margin: '4px 0 0', whiteSpace: 'pre-wrap' }}>{selectedProject.staffing_notes}</Typography.Paragraph>
              <Typography.Text type="secondary">请根据系统账号和当前负荷手动确认，不会自动绑定同名人员。</Typography.Text>
            </div>
          )}

          <div className="staffing-current-team">
            <div className="staffing-section-title">
              <Typography.Text strong>当前项目组</Typography.Text>
              <Typography.Text type="secondary">{currentMembers.length} 人</Typography.Text>
            </div>
            {currentMembers.length ? (
              <div className="staffing-member-grid">
                {currentMembers.map((person) => {
                  const pool = workload[person.id] ?? {}
                  const isOwner = person.id === selectedProject.manager
                  return (
                    <div className="staffing-member" key={person.id}>
                      <div className="staffing-person-name">
                        <Typography.Text strong>{person.display_name}</Typography.Text>
                        <Tag>{isOwner ? '负责人' : ROLE_LABEL[person.role] ?? person.role}</Tag>
                      </div>
                      <Typography.Text type="secondary">周负荷 {pool.load_percent ?? 0}%</Typography.Text>
                      {canEdit && !isOwner && (
                        <Button type="text" size="small" danger disabled={saving !== null}
                          onClick={() => Modal.confirm({
                            title: `把「${person.display_name}」移出项目？`,
                            content: '移出后此人不再收到该项目日程通知，也不能填报该项目进度。',
                            okText: '移出', cancelText: '取消',
                            onOk: () => setMember(selectedProject.id, person.id, false),
                          })}>移出</Button>
                      )}
                    </div>
                  )
                })}
              </div>
            ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="项目组还没有成员" />}
          </div>

          <div className="staffing-candidate-section">
            <div className="staffing-candidate-toolbar">
              <div className="staffing-section-title">
                <Typography.Text strong>候选人员池</Typography.Text>
                <Typography.Text type="secondary">按负荷和并行项目数排序</Typography.Text>
              </div>
              <Segmented size="small" value={candidateScope} onChange={(value) => setCandidateScope(String(value))}
                options={[{ label: '推荐', value: 'recommended' }, { label: '可安排', value: 'available' }, { label: '无项目', value: 'unassigned' }, { label: '全部', value: 'all' }]} />
            </div>
            <div className="staffing-candidate-filters">
              <Input allowClear placeholder="搜索姓名或角色" value={candidateSearch}
                onChange={(event) => setCandidateSearch(event.target.value)} />
              <Select allowClear placeholder="角色" value={candidateRole || undefined} onChange={(value) => setCandidateRole(value ?? '')}
                options={roleOptions} />
              {(candidateSearch || candidateRole) && (
                <Button type="text" onClick={() => { setCandidateSearch(''); setCandidateRole('') }}>清除筛选</Button>
              )}
            </div>
            {isMobile ? (
              shownCandidates.length === 0
                ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前条件下没有候选人" />
                : (
                  <div className="mobile-card-list">
                    {shownCandidates.map((person) => {
                      const pool = workload[person.id] ?? {}
                      const percent = pool.load_percent ?? 0
                      const count = projCountOf(person.id)
                      const checked = selectedCandidateIds.includes(person.id)
                      const togglePerson = (id: string) => setSelectedCandidateIds((prev) => prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id])
                      return (
                        <Card key={person.id} size="small" onClick={() => togglePerson(person.id)} style={{ cursor: 'pointer' }}>
                          <Space direction="vertical" size={6} style={{ width: '100%' }}>
                            <div className="mobile-card-row">
                              <Checkbox checked={checked} aria-label="选择该候选人" onClick={(e) => e.stopPropagation()} onChange={() => togglePerson(person.id)} />
                              <span className="mobile-card-title-sm">{person.display_name}</span>
                              {workload[person.id]?.is_recommended && <Tag color="success">推荐</Tag>}
                            </div>
                            <div className="mobile-card-row">
                              <span className="mobile-card-label">岗位</span>
                              <span className="mobile-card-value">
                                <Space size={4} wrap style={{ rowGap: 4 }}>
                                  <Typography.Text>{ROLE_LABEL[person.role] ?? person.role}</Typography.Text>
                                </Space>
                              </span>
                            </div>
                            <div className="mobile-card-row">
                              <span className="mobile-card-label">本周容量</span>
                              <span className="mobile-card-value" style={{ flex: 1, minWidth: 140 }}>
                                <Progress percent={percent} size="small" status={percent >= 100 ? 'exception' : 'normal'} aria-label="成员负荷进度" format={() => `${percent}% · ${pool.planned_hours ?? 0}h`} />
                              </span>
                            </div>
                            <div className="mobile-card-row">
                              <span className="mobile-card-label">并行项目</span>
                              <span className="mobile-card-value"><Typography.Text type={count >= 4 ? 'danger' : count >= 3 ? 'warning' : undefined}>{count} 个</Typography.Text></span>
                            </div>
                          </Space>
                        </Card>
                      )
                    })}
                  </div>
                )
            ) : (
            <Table
              rowKey="id"
              size="small"
              scroll={{ x: 'max-content' }}
              dataSource={shownCandidates}
              pagination={false}
              locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前条件下没有候选人" /> }}
              rowSelection={{
                selectedRowKeys: selectedCandidateIds,
                preserveSelectedRowKeys: true,
                onChange: (keys) => setSelectedCandidateIds(keys.map(String)),
                getCheckboxProps: () => ({ 'aria-label': '选择该行' } as any),
              }}
              columns={[
                {
                  title: '人员', dataIndex: 'display_name', width: 160,
                  render: (name: string, person: any) => <Space size={6}>
                    <Typography.Text strong>{name}</Typography.Text>
                    {workload[person.id]?.is_recommended && <Tag color="success">推荐</Tag>}
                  </Space>,
                },
                {
                  title: '角色', key: 'role', width: 180,
                  render: (_: any, person: any) => <div>
                    <Typography.Text>{ROLE_LABEL[person.role] ?? person.role}</Typography.Text>
                  </div>,
                },
                {
                  title: '本周容量', key: 'load', width: 210,
                  sorter: (a: any, b: any) => (workload[a.id]?.load_percent ?? 0) - (workload[b.id]?.load_percent ?? 0),
                  render: (_: any, person: any) => {
                    const pool = workload[person.id] ?? {}
                    const percent = pool.load_percent ?? 0
                    return <Tooltip title={`计划 ${pool.planned_hours ?? 0}h / 可用 ${pool.available_hours ?? 40}h`}>
                      <Progress percent={percent} size="small" status={percent >= 100 ? 'exception' : 'normal'} aria-label="成员负荷进度"
                        format={() => `${percent}% · ${pool.planned_hours ?? 0}h`} />
                    </Tooltip>
                  },
                },
                {
                  title: '并行项目', key: 'projects', width: 100,
                  sorter: (a: any, b: any) => projCountOf(a.id) - projCountOf(b.id),
                  render: (_: any, person: any) => {
                    const count = projCountOf(person.id)
                    return <Typography.Text type={count >= 4 ? 'danger' : count >= 3 ? 'warning' : undefined}>{count} 个</Typography.Text>
                  },
                },
              ]}
            />
            )}
            <div className="staffing-candidate-footer">
              <Pagination size="small" current={candidatePage} pageSize={candidatePageSize} total={candidateRows.length}
                showSizeChanger={false} showQuickJumper={candidateRows.length > 60}
                showTotal={(total) => `共 ${total} 人`} onChange={setCandidatePage} />
              <div className={`staffing-selection ${selectedCandidateIds.length ? 'active' : ''}`}>
                <Typography.Text>{selectedCandidateIds.length ? `已选择 ${selectedCandidateIds.length} 人` : '勾选人员后可批量加入'}</Typography.Text>
                {selectedCandidateIds.length > 0 && <Button type="text" onClick={() => setSelectedCandidateIds([])}>取消选择</Button>}
                <Button type="primary" icon={<PlusOutlined />} disabled={!canEdit || selectedCandidateIds.length === 0}
                  loading={saving === selectedProject.id} onClick={addSelectedCandidates}>加入项目</Button>
              </div>
            </div>
          </div>
        </>}
      </section>
    </div>
  )

  return (
    <>
      {mode === 'projects' ? projectsView : peopleView}

      {/* 人员详情 Drawer：完整分配 / 调整 / 移出（替代 Tag 墙直接操作） */}
      <Drawer
        title={drawerUser ? (
          <Space size={8}>
            <span>{drawerUser.display_name}</span>
            <Tag color="default" style={{ fontSize: 11 }}>{ROLE_LABEL[drawerUser.role] ?? drawerUser.role}</Tag>
          </Space>
        ) : ''}
        open={!!drawerUser}
        onClose={() => setDrawerUser(null)}
        width={isMobile ? '100%' : 420}
      >
        {drawerUser && (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              参与 {projCountOf(drawerUser.id)} 个项目 · 并行数：<span style={{ color: '#237804' }}>绿=正常</span> / <span style={{ color: '#ad4e00' }}>黄=偏高</span> / <span style={{ color: '#cf1322' }}>红=超负荷</span>
            </Typography.Text>
            <Divider style={{ margin: '4px 0' }} />
            <Typography.Text strong>当前安排</Typography.Text>
            {projects.filter((p) => memberSet[p.id]?.has(drawerUser.id)).map((p) => {
              const n = projCountOf(drawerUser.id)
              return (
                <div key={p.id} style={{ display: 'flex', alignItems: 'center', gap: 8, border: '1px solid #f0f0f0', borderRadius: 8, padding: '8px 10px' }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <Typography.Text style={{ fontSize: 13 }}>{p.name}</Typography.Text>
                    <div>
                      <Tag color="blue" style={{ fontSize: 11 }}>{STATUS_LABEL[p.status] ?? p.status}</Tag>
                      <Tag style={{ fontSize: 11, color: n >= 4 ? '#cf1322' : n >= 3 ? '#ad4e00' : '#237804' }}>
                        {n} 个并行
                      </Tag>
                    </div>
                  </div>
                  {canEditProject(p) && (
                    <Button
                      size="small"
                      danger
                      onClick={() => {
                        Modal.confirm({
                          title: `把「${drawerUser.display_name}」移出「${p.name}」？`,
                          content: '移出后此人不再收到该项目日程通知，也不能再填报该项目进度。',
                          okText: '移出',
                          cancelText: '取消',
                          onOk: () => setMember(p.id, drawerUser.id, false),
                        })
                      }}
                    >
                      移出
                    </Button>
                  )}
                </div>
              )
            })}
            {projects.filter((p) => memberSet[p.id]?.has(drawerUser.id)).length === 0 && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>未参与任何项目</Typography.Text>
            )}
            {projects.some(canEditProject) && (
              <>
                <Divider style={{ margin: '4px 0' }} />
                <Typography.Text strong>加入项目</Typography.Text>
                <Select
                  size="small"
                  showSearch
                  optionFilterProp="label"
                  placeholder="搜项目，选中即加入"
                  style={{ width: '100%' }}
                  disabled={saving !== null}
                  value={null}
                  onChange={(pid: string) => { setMember(pid, drawerUser.id, true) }}
                  options={projects
                    .filter((p) => canEditProject(p) && !memberSet[p.id]?.has(drawerUser.id))
                    .map((p) => ({ value: p.id, label: `${p.name}（${memberSet[p.id]?.size ?? 0}人）` }))}
                  notFoundContent={<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="这个人已在所有项目里" />}
                />
              </>
            )}
          </Space>
        )}
      </Drawer>
    </>
  )
}
