import ExternalSharePanel from './ExternalSharePanel'
import TeamPage from './TeamPage'
import VehicleLifecyclePage from './VehicleLifecyclePage'
import { useLocation, useNavigate } from 'react-router-dom'
import HolidayCalendarNotice from '../../../components/HolidayCalendarNotice'
import { DISPATCH_PLATFORMS, PLAN_EVENTS, PROJECT_EVENT_LABELS, planFormValues, planPayload, plannedDate } from '../../../constants/projectEvents'
import { useProjectCapability, useProjectWriteBlocked } from '../../../hooks/useProjectCapability'
import ProjectOwnerPanel from './ProjectOwnerPanel'
import WeeklyPlanSettings from './WeeklyPlanSettings'
import MemberPermissions from './MemberPermissions'
import Tabs from '../../../components/VisibleTabs'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Card, Form, Input, DatePicker, Button, Table, Select, message, Tag, Row, Col, Typography, Popconfirm, Modal } from 'antd'
import { SaveOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { projectApi, userApi, type Project } from '../../../api'
import { api, errMsg } from '../../../api/client'
import { projectDocumentsApi } from '../../../api/projectDocuments'
import { useAuth } from '../../../stores/auth'
import { TIMEZONE_OPTIONS, DEFAULT_TIMEZONE } from '../../../constants/timezones'
import { ROLE_NAME } from '../../../constants/roles'
import { useUnsavedNavigation } from '../../../hooks/useUnsavedNavigation'
import { WorkPageHeader } from '../../../components/WorkPage'

const infoSnapshot = (values: any) => JSON.stringify({
  name: values.name ?? '', abbreviation: values.abbreviation ?? '', client: values.client ?? '',
  location: values.location ?? '', timezone: values.timezone || DEFAULT_TIMEZONE,
  range: (values.range ?? []).map((date: any) => date?.format('YYYY-MM-DD') ?? ''),
  event_plans: planPayload(values.event_plans), dispatch_platform: values.dispatch_platform ?? null,
  description: values.description ?? '', staffing_notes: values.staffing_notes ?? '',
  technical_manager_id: values.technical_manager_id ?? '',
})
const projectInfoFields = (project: Project) => ({
  name: project.name, abbreviation: project.abbreviation, client: project.client,
  location: project.location, timezone: project.timezone || DEFAULT_TIMEZONE,
  range: [dayjs(project.start_date), dayjs(project.end_date)],
  event_plans: planFormValues(project), dispatch_platform: project.dispatch_platform ?? null,
  description: project.description, staffing_notes: project.staffing_notes,
  technical_manager_id: project.technical_manager || undefined,
})
const fieldsFromSnapshot = (snapshot: string) => {
  const values = JSON.parse(snapshot)
  return { ...values,
    range: values.range.map((value: string) => value ? dayjs(value) : null),
    event_plans: Object.fromEntries(PLAN_EVENTS.map(key => [key, values.event_plans?.[key] ? dayjs(values.event_plans[key]) : null])),
    technical_manager_id: values.technical_manager_id || undefined,
  }
}

/**
 * 项目编辑：精细调整中心（简洁分组）
 * 基本信息 / 成员 / 任务调整（目标数量、追加任务、适用性）
 */
export default function EditPage({ project, onReload }: { project: Project; onReload: () => void }) {
  const { user } = useAuth()
  const location = useLocation(); const navigate = useNavigate()
  const isOwner = user?.role === 'admin' || (user?.role === 'pm' && project.manager === user.id)
  const writeBlocked = useProjectWriteBlocked(project.status)
  const hasEditPermission = useProjectCapability('project.update', isOwner || !!project.is_co_manager)
  const canEdit = !writeBlocked && hasEditPermission
    && user?.permission_overrides?.['project.update'] !== false
    && user?.permission_overrides?.['project.read'] !== false
  const [users, setUsers] = useState<any[]>([])
  const [infoForm] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const [infoDirty, setInfoDirty] = useState(false)
  const saveLock = useRef(false)
  const finishSave = () => { saveLock.current = false; setSaving(false) }
  const [settingsTab, setSettingsTab] = useState(() => new URLSearchParams(location.search).get('section') || 'info')
  const [coDraftEpoch, setCoDraftEpoch] = useState(0)
  const tabDialog = useRef<ReturnType<typeof Modal.confirm> | null>(null)
  const tabDecision = useRef(0)
  const closeTabDialog = useCallback(() => {
    tabDecision.current += 1
    tabDialog.current?.destroy()
    tabDialog.current = null
  }, [])
  useEffect(() => closeTabDialog, [closeTabDialog])
  const [, setDirty] = useUnsavedNavigation({ title: '项目设置有未保存的修改', beforeConfirm: closeTabDialog })
  const dirtyAreas = useRef({ info: false, coManagers: false, external: false, members: false, vehicles: false, owner: false, schedule: false })
  const updateDirty = useCallback((area: 'info' | 'coManagers' | 'external' | 'members' | 'vehicles' | 'owner' | 'schedule', value: boolean) => {
    dirtyAreas.current[area] = value
    if (area === 'info') setInfoDirty(value)
    setDirty(Object.values(dirtyAreas.current).some(Boolean))
  }, [setDirty])
  const coManagersDirty = useCallback((value: boolean) => updateDirty('coManagers', value), [updateDirty])
  const externalDirty = useCallback((value: boolean) => updateDirty('external', value), [updateDirty])
  const membersDirty = useCallback((value:boolean)=>updateDirty('members',value),[updateDirty])
  const vehiclesDirty = useCallback((value:boolean)=>updateDirty('vehicles',value),[updateDirty])
  const ownerDirty = useCallback((value:boolean)=>updateDirty('owner',value),[updateDirty])
  const scheduleDirty = useCallback((value:boolean)=>updateDirty('schedule',value),[updateDirty])
  const infoBaseline = useRef('')
  const infoBaselineVersion = useRef<number | undefined>(project.version)
  const formProject = useRef<string | null>(null)

  useEffect(() => {
    const fields = projectInfoFields(project)
    // Preserve drafts when this component receives a same-project update.
    // The parent may instead unmount on reload, so saving disables new input.
    if (formProject.current !== project.id || infoSnapshot(infoForm.getFieldsValue(true)) === infoBaseline.current) {
      infoForm.setFieldsValue(fields)
      infoBaseline.current = infoSnapshot(fields)
      infoBaselineVersion.current = project.version
      updateDirty('info', false)
    }
    formProject.current = project.id
    ;(project.capabilities !== undefined ? api.get(`/projects/${project.id}/people`, { params: isOwner ? { include_candidates: true } : undefined }).then(r => r.data) : userApi.listActive()).then(setUsers).catch(() => {})
  }, [project, infoForm, updateDirty])

  const switchSettingsTab = (next: string) => {
    if (next === settingsTab || saveLock.current || tabDialog.current) return
    if (!Object.values(dirtyAreas.current).some(Boolean)) {
      setSettingsTab(next)
      return
    }
    const decision = ++tabDecision.current
    tabDialog.current = Modal.confirm({
      title: '项目设置有未保存的修改',
      content: '继续填写会保留当前内容；放弃修改后将切换到所选设置。',
      okText: '放弃修改并切换', cancelText: '继续填写',
      onOk: () => {
        if (decision !== tabDecision.current) return
        closeTabDialog()
        const fields = projectInfoFields(project)
        infoForm.setFieldsValue(fields)
        infoBaseline.current = infoSnapshot(fields)
        infoBaselineVersion.current = project.version
        dirtyAreas.current = { info: false, coManagers: false, external: false, members: false, vehicles: false, owner: false, schedule: false }
        setInfoDirty(false)
        setDirty(false)
        setCoDraftEpoch(value => value + 1)
        setSettingsTab(next)
      },
      onCancel: () => { if (decision === tabDecision.current) closeTabDialog() },
    })
  }

  const persistInfo = async (values: any) => {
    try {
      if (infoSnapshot(values) === infoBaseline.current) return
      const saved = await projectApi.update(project.id, {
        version: infoBaselineVersion.current,
        event_plans: planPayload(values.event_plans), dispatch_platform: values.dispatch_platform ?? null,
        name: values.name, abbreviation: values.abbreviation, client: values.client, location: values.location,
        timezone: values.timezone || DEFAULT_TIMEZONE,
        start_date: values.range[0].format('YYYY-MM-DD'), end_date: values.range[1].format('YYYY-MM-DD'),
        description: values.description,
        staffing_notes: values.staffing_notes,
        ...(isOwner ? { technical_manager_id: values.technical_manager_id ?? null } : {}),
      })
      infoBaseline.current = infoSnapshot(values)
      infoBaselineVersion.current = saved?.version ?? (infoBaselineVersion.current === undefined ? undefined : infoBaselineVersion.current + 1)
      updateDirty('info', infoSnapshot(infoForm.getFieldsValue(true)) !== infoBaseline.current)
      message.success('已保存')
      onReload()
    } catch (e) { message.error(errMsg(e)) }
    finally { finishSave() }
  }

  const cancelInput = () => {
    if (!canEdit || saving) return
    infoForm.setFieldsValue(fieldsFromSnapshot(infoBaseline.current))
    updateDirty('info', false)
  }

  const saveInfo = async (values: any) => {
    if (!canEdit || saveLock.current) return
    saveLock.current = true
    setSaving(true)
    const nextDate = values.event_plans?.ship?.format('YYYY-MM-DD') ?? null
    if (nextDate === plannedDate(project, 'ship')) return persistInfo(values)
    try {
      const data = await projectDocumentsApi.list(project.id)
      const pending = data.documents.filter(item => item.status === 'pending' && item.applicable !== false && item.due_at)
      Modal.confirm({
        title: '确认调整计划发车日期',
        content: <div><p>{plannedDate(project, 'ship') || '未安排'} → {nextDate || '未安排'}</p>
          <p>有 {pending.length} 项待提交资料已有截止时间。资料截止以清单显示为准；实际事件时间和既有日程不会随计划自动移动，请核对资料清单。</p>
          <ul>{pending.slice(0, 8).map((item: any) => <li key={item.id}>{item.name}：{item.due_at}{item.due_is_estimated ? "（预计）" : ""}</li>)}</ul>
          {pending.length > 8 && <p>其余 {pending.length - 8} 项请到资料清单核对。</p>}
          <a href={`/pm/projects/${project.id}/documents`} target="_blank" rel="noreferrer">查看资料截止</a> · <a href={`/pm/projects/${project.id}/plan?view=weeks`} target="_blank" rel="noreferrer">查看周计划</a></div>,
        okText: '只保存发车日期', cancelText: '返回修改', onOk: () => persistInfo(values), onCancel: finishSave,
      })
    } catch (error) { message.error(`日期影响核对失败，请重试：${errMsg(error)}`); finishSave() }
  }

  return (
    <>
    <HolidayCalendarNotice years={project?.missing_holiday_years} />
    <WorkPageHeader title="项目设置" description="维护项目资料、成员、车型与负责人；工作项及周计划到「计划」调整。" />
    <Tabs
      className="project-settings-tabs"
      activeKey={settingsTab}
      onChange={switchSettingsTab}
      items={[
        {
          key: 'info',
          disabled: saving,
          label: '基本信息',
          children: (
            <Card className="project-info-form" size="small" style={{ maxWidth: 760 }}>
              <Form form={infoForm} layout="vertical" disabled={!canEdit || saving} onFinish={saveInfo} onValuesChange={(_, values) => {
                if (canEdit && !saving) {
                  const snapshot = infoSnapshot(values)
                  updateDirty('info', snapshot !== infoBaseline.current)
                }
              }}>
                <Form.Item name="name" label="项目名称" rules={[{ required: true }]}><Input /></Form.Item>
                <Row gutter={12}>
                  <Col xs={24} md={12}><Form.Item name="client" label="客户"><Input /></Form.Item></Col>
                  <Col xs={24} md={12}><Form.Item name="location" label="地点"><Input /></Form.Item></Col>
                </Row>
                <Form.Item name="dispatch_platform" label="调度平台"><Select aria-label="调度平台" allowClear options={DISPATCH_PLATFORMS} placeholder="选择 NDC / GRACE / 集成" /></Form.Item>
                <Row gutter={12}>{PLAN_EVENTS.map(key => <Col xs={24} md={8} key={key}><Form.Item name={["event_plans", key]} label={`${PROJECT_EVENT_LABELS[key]}计划日期`}><DatePicker style={{ width: "100%" }} /></Form.Item></Col>)}</Row>
                <Form.Item name="range" label="实施周期" rules={[{ required: true, message: '请选择实施开始和结束日期' }]}><DatePicker.RangePicker style={{ width: '100%' }} /></Form.Item>
                <Form.Item name="technical_manager_id" label="技术负责人" extra="每个项目指定一名项目经理或实施工程师作为技术负责人；项目协管不能变更正式负责人。">
                  <Select aria-label="技术负责人" allowClear showSearch optionFilterProp="label" disabled={!isOwner || !canEdit || saving} placeholder="选择技术负责人"
                    options={users.filter((u) => ['lead', 'technician', 'pm', 'worker'].includes(u.role)).map((u) => ({ label: `${u.display_name}（${ROLE_NAME[u.role] ?? u.role}）`, value: u.id }))} />
                </Form.Item>
                <Form.Item name="description" label="说明"><Input.TextArea rows={2} /></Form.Item>
                <details className="work-detail-summary project-info-extra"><summary>其他资料：简称、时区与人员备注</summary>
                  <Row gutter={12}><Col xs={24} md={12}><Form.Item name="abbreviation" label="项目简称"><Input /></Form.Item></Col>
                  <Col xs={24} md={12}><Form.Item name="timezone" label="现场时区" tooltip="今日任务与撤回期限按现场时区判定。"><Select aria-label="现场时区" options={TIMEZONE_OPTIONS} /></Form.Item></Col></Row>
                  <Form.Item name="staffing_notes" label="人员安排参考" extra="记录姓名、能力或驻场建议；实际参与人员请在本页「成员」维护。"><Input.TextArea rows={3} /></Form.Item>
                </details>
                {canEdit && <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  <Button type="primary" htmlType="submit" loading={saving} icon={<SaveOutlined />}>保存</Button>
                  {infoDirty && <Button disabled={saving} onClick={cancelInput}>放弃本次编辑</Button>}

                </div>}
              </Form>
            </Card>
          ),
        },
        { key:'members',label:'成员',disabled:saving,children:<TeamPage key={`${project.id}:${coDraftEpoch}`} project={project} onReload={onReload} canEdit={canEdit && project.capabilities?.includes('project.manage_members') !== false} inlineSetup onDirtyChange={membersDirty} onSchedule={()=>navigate(`/pm/projects/${project.id}/plan?view=weeks`)} /> },
        { key:'schedule',label:'排期设置',disabled:saving,children:<WeeklyPlanSettings key={`${project.id}:${coDraftEpoch}`} project={project} onReload={onReload} onDirtyChange={scheduleDirty}/> },
        { key:'vehicles',label:'车型配置',disabled:saving,children:<VehicleLifecyclePage key={`${project.id}:${coDraftEpoch}`} project={project} onReload={onReload} configurationOnly onDirtyChange={vehiclesDirty} /> },
        {
          key: 'member-permissions',
          disabled: saving,
          label: '成员授权',
          children: <MemberPermissions key={project.id} project={project}
            members={(project.members ?? []).map(id => users.find(person => person.id === id) ?? { id, display_name: id })} onReload={onReload} />,
        },
        {
          key: 'co-managers',
          disabled: saving,
          label: '项目协管',
          children: <ProjectCoManagers key={`${project.id}:${coDraftEpoch}`} project={project} users={users} canEdit={isOwner && canEdit} onReload={onReload} onDirtyChange={coManagersDirty} />,
        },
        {
          key: 'external',
          disabled: saving,
          label: '外部查看',
          children: <ExternalSharePanel key={`${project.id}:${coDraftEpoch}`} projectId={project.id} enabled={user?.id === project.manager && hasEditPermission && user?.permission_overrides?.['project.read'] !== false} onDirtyChange={externalDirty} />,
        },
        {
          key: 'owner',
          disabled: saving,
          label: '负责人',
          children: <ProjectOwnerPanel key={`${project.id}:${coDraftEpoch}`} project={project} onReload={onReload} onDirtyChange={ownerDirty} />,
        },
      ]}
    />

          </>
  )
}

function ProjectCoManagers({ project, users, canEdit, onReload, onDirtyChange }: { project: Project; users: any[]; canEdit: boolean; onReload: () => void; onDirtyChange: (value: boolean) => void }) {
  const [form] = Form.useForm()
  const grants = project.co_managers ?? []
  useEffect(() => { form.resetFields(); onDirtyChange(false) }, [project.id, form, onDirtyChange])
  const save = async (values: any) => {
    try {
      const next = [
        ...grants.filter((grant) => grant.user_id !== values.user_id),
        { user_id: values.user_id, expires_at: values.expires_at?.format('YYYY-MM-DD') },
      ]
      await projectApi.update(project.id, { co_managers: next.map(({ user_id, expires_at }) => ({ user_id, expires_at })) })
      message.success('项目协管授权已保存')
      form.resetFields()
      onDirtyChange(false)
      onReload()
    } catch (error) { message.error(errMsg(error)) }
  }
  const remove = async (userId: string) => {
    try {
      await projectApi.update(project.id, { co_managers: grants.filter((grant) => grant.user_id !== userId).map(({ user_id, expires_at }) => ({ user_id, expires_at })) })
      message.success('协管授权已撤销')
      onReload()
    } catch (error) { message.error(errMsg(error)) }
  }
  return <Card size="small" title="项目级协管授权" style={{ maxWidth: 760 }}>
    <Typography.Paragraph type="secondary">
      适合只有一名实施工程师的小项目。协管可共同维护工作项、周计划、成员、问题和资料，但负责人更换、项目删除和继续授权仍单独校验。
    </Typography.Paragraph>
    {canEdit && <Form form={form} layout="inline" onFinish={save} onValuesChange={(_, values) => onDirtyChange(!!values.user_id || !!values.expires_at)} style={{ marginBottom: 16 }}>
      <Form.Item name="user_id" rules={[{ required: true, message: '请选择协管人员' }]}>
        <Select aria-label="项目协管人员" showSearch optionFilterProp="label" placeholder="选择实施/技术人员" style={{ width: 240 }} options={users.filter((item) => ['worker', 'technician', 'pm'].includes(item.role) && item.id !== project.manager).map((item) => ({ value: item.id, label: `${item.display_name}（${ROLE_NAME[item.role] ?? item.role}）` }))} />
      </Form.Item>
      <Form.Item name="expires_at" rules={[{ required: true, message: '请选择授权截止日期' }]}><DatePicker placeholder="授权截止日期" /></Form.Item>
      <Button type="primary" htmlType="submit">授权协管</Button>
    </Form>}
    <Table size="small" rowKey="user_id" pagination={false} dataSource={grants} locale={{ emptyText: '暂无项目协管' }} columns={[
      { title: '协管人员', dataIndex: 'display_name', render: (value: string) => value || '未知账号' },
      { title: '岗位', dataIndex: 'role', width: 120, render: (value: string) => ROLE_NAME[value] ?? value },
      { title: '有效期至', dataIndex: 'expires_at', width: 140, render: (value: string) => value || '长期' },
      { title: '状态', dataIndex: 'is_active', width: 100, render: (value: boolean) => <Tag color={value ? 'green' : 'default'}>{value ? '生效中' : '已过期'}</Tag> },
      ...(canEdit ? [{ title: '操作', width: 90, render: (_: any, item: any) => <Popconfirm title="撤销该协管授权？" onConfirm={() => remove(item.user_id)}><Button size="small" danger type="link">撤销</Button></Popconfirm> }] : []),
    ]} />
  </Card>
}
