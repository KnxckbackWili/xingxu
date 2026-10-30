import { useEffect, useRef, useState } from 'react'
import { Alert, Avatar, Button, Empty, Modal, Select, Skeleton, Space, Typography, message } from 'antd'
import { UserOutlined } from '@ant-design/icons'
import { userApi, projectApi } from '../../../api'
import { api, errMsg } from '../../../api/client'
import { useProjectWriteBlocked } from '../../../hooks/useProjectCapability'
import { Link } from 'react-router-dom'
import { ROLE_NAME } from '../../../constants/roles'
import { WorkPageHeader, WorkSection } from '../../../components/WorkPage'
import { confirmMemberRemoval } from '../../../api/memberRemoval'

/** 项目团队：实际参与人员和成员权限。 */
export default function TeamPage({ project, onReload, canEdit: canManageMembers, onSchedule, inlineSetup = false, onDirtyChange }: {
  project: any
  onReload?: () => void
  canEdit?: boolean
  onSchedule?: () => void
  inlineSetup?: boolean
  onDirtyChange?: (dirty: boolean) => void
}) {
  const writeBlocked = useProjectWriteBlocked(project.status)
  const canEdit = !!canManageMembers && !writeBlocked
  const memberIds: string[] = project?.members ?? []
  const [users, setUsers] = useState<any[]>([])
  const [usersError, setUsersError] = useState(false)
  const [usersLoading, setUsersLoading] = useState(true)
  const [membersOpen, setMembersOpen] = useState(false)
  const [selectedMembers, setSelectedMembers] = useState<string[]>([])
  const [memberError, setMemberError] = useState('')
  const [savingMembers, setSavingMembers] = useState(false)
  const usersRequest = useRef(0)
  const loadUsers = async () => {
    const request = ++usersRequest.current
    setUsersLoading(true)
    setUsersError(false)
    try { const result = project.capabilities !== undefined ? (await api.get(`/projects/${project.id}/people`, { params: canEdit ? { include_candidates: true } : undefined })).data : await userApi.listActive(); if (request === usersRequest.current) setUsers(result) } catch { if (request === usersRequest.current) setUsersError(true) }
    finally { if (request === usersRequest.current) setUsersLoading(false) }
  }
  useEffect(() => { void loadUsers(); return () => { usersRequest.current++ } }, [project.id, canEdit])
  const members = memberIds.map((id) => users.find((user) => user.id === id) ?? { id, display_name: `成员 ${id}`, role: '' })
  useEffect(() => { if (inlineSetup) setSelectedMembers(project.members ?? []) }, [inlineSetup, project.id, project.version])
  useEffect(() => { if (inlineSetup) onDirtyChange?.([...selectedMembers].sort().join(',') !== [...memberIds].sort().join(',')) }, [selectedMembers, memberIds, inlineSetup, onDirtyChange])
  const memberLock = useRef(false)
  const memberRequest=useRef<AbortController|null>(null)
  useEffect(()=>()=>{memberRequest.current?.abort()},[project.id])
  const saveMembers = async () => {
    if (memberLock.current || !canEdit) return
    memberLock.current = true
    setSavingMembers(true)
    setMemberError('')
    const scope=new AbortController();memberRequest.current=scope
    try {
      const removed=memberIds.filter(id=>!selectedMembers.includes(id))
      const confirmed=await confirmMemberRemoval(project.id,removed,scope.signal)
      if(confirmed===undefined || scope.signal.aborted)return
      await projectApi.update(project.id, { members: selectedMembers, version: project.version,...(removed.length?{member_removal_confirmations:confirmed}:{}) })
      message.success('项目成员已更新，请在日程中核对每项任务的执行人')
      setMembersOpen(false)
      onDirtyChange?.(false)
      onReload?.()
    } catch (error) { setMemberError(errMsg(error)) }
    finally { if(memberRequest.current===scope){memberLock.current = false; setSavingMembers(false);memberRequest.current=null} }
  }

  return (
    <div className="project-people-page">
      {!inlineSetup && <WorkPageHeader title="项目人员" description="添加实际参与项目的人，再到日程安排每天的任务。"
        meta={`项目经理：${project?.manager_name || '未指定'} · 技术负责人：${project?.technical_manager_name || '未指定'}`}
        primary={canEdit && !['completed', 'archived', 'suspended'].includes(project.status) ? <Button type="primary" onClick={() => { setSelectedMembers(memberIds); setMembersOpen(true) }}>添加人员</Button> : undefined} />}
      <WorkSection title={`参与人员 · ${members.length} 人`}>
        {memberError && !membersOpen && <Alert type="error" showIcon message={memberError} action={<Button href={`/pm/projects/${project.id}/schedule`}>去日程改派</Button>} style={{ marginBottom: 12 }} />}
        {usersError && <Alert type="error" showIcon message="成员姓名加载失败" action={<Button onClick={loadUsers}>重试</Button>} />}
        {inlineSetup && <Typography.Paragraph type="secondary">选好参与人员并保存，再安排执行日期和任务。</Typography.Paragraph>}
        {inlineSetup && canEdit && !['completed', 'archived', 'suspended'].includes(project.status) && <div className="startup-member-picker">
          <label htmlFor="startup-members">选择实际参与项目的人员</label>
          <Select id="startup-members" aria-label="项目参与人员" mode="multiple" showSearch optionFilterProp="label" value={selectedMembers}
            disabled={savingMembers || usersLoading || usersError} onChange={setSelectedMembers} placeholder="输入姓名选择，可同时安排多人"
            options={[...users.map(user => ({ value: user.id, label: `${user.display_name || user.username}（${ROLE_NAME[user.role] ?? user.role}）` })), ...memberIds.filter(id => !users.some(user => user.id === id)).map(id => ({ value: id, label: `原成员 ${id}` }))]} />
          <Space wrap><Button type="primary" loading={savingMembers} disabled={usersError || usersLoading || [...selectedMembers].sort().join(',') === [...memberIds].sort().join(',')} onClick={saveMembers}>保存人员安排</Button>
          {onSchedule && memberIds.length > 0 && <Button onClick={onSchedule}>下一步：分配日程</Button>}</Space>
        </div>}
        {onSchedule && !inlineSetup && memberIds.length > 0 && <Button onClick={onSchedule} style={{ marginBottom: 12 }}>下一步：分配日程</Button>}
        {usersLoading ? <Skeleton active paragraph={{ rows: 3 }} /> : members.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未安排执行成员" />
        ) : (
          <div className="project-member-grid" aria-busy={usersLoading}>
            {members.map((member: any) => {
              const role = member?.role ?? ''
              return (
                <div key={member?.id ?? member?.user_id ?? role} className="team-member-card">
                  <Avatar size={36} icon={<UserOutlined />} />
                  <div>
                    <Typography.Text strong>{member?.display_name ?? member?.username ?? member?.user_id ?? '-'}</Typography.Text>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {ROLE_NAME[role] ?? '项目成员'}
                    </Typography.Text>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </WorkSection>
      {!inlineSetup && project.capabilities !== undefined && <Link to={`/pm/projects/${project.id}/edit`}>在项目设置中查看和调整成员授权</Link>}
      <Modal okText="保存成员" cancelText="取消" title="安排项目成员" open={membersOpen} onCancel={() => { if (!savingMembers) setMembersOpen(false) }} onOk={saveMembers} confirmLoading={savingMembers} okButtonProps={{ disabled: usersLoading || usersError }} maskClosable={false}>
        {memberError && <Alert type="error" showIcon message={memberError} action={<Button href={`/pm/projects/${project.id}/schedule`}>去日程改派</Button>} />}
        <Typography.Paragraph>加入项目后，成员可查看项目；日程发布后，才能在「今天」中看到分配给自己的工作。</Typography.Paragraph>
        <Select aria-label="项目成员" mode="multiple" showSearch optionFilterProp="label" style={{ width: '100%' }} value={selectedMembers} disabled={savingMembers} onChange={setSelectedMembers} options={[...users.map((user) => ({ value: user.id, label: `${user.display_name || user.username}（${ROLE_NAME[user.role] ?? user.role}）` })), ...memberIds.filter((id) => !users.some((user) => user.id === id)).map((id) => ({ value: id, label: `原成员 ${id}` }))]} />
      </Modal>
    </div>
  )
}
