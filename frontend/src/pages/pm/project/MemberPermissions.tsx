import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Card, Checkbox, Modal, Space, Tag, Typography } from 'antd'
import { projectApi, type Project } from '../../../api'
import { errMsg } from '../../../api/client'
import { useAuth } from '../../../stores/auth'
import { permissionsApi, type PermissionReason } from '../../../api/permissions'
import { useProjectWriteBlocked } from '../../../hooks/useProjectCapability'

export const CAPABILITY_LABELS: Record<string, string> = {
  'project.delete': '删除项目（职责权限）',
  'project.update': '编辑项目资料与现场信息',
  'project.manage_members': '安排项目成员',
  'project.manage_plan': '编辑工作项、资料要求与车辆台账',
  'project.manage_schedule': '编辑并发布周计划',
  'project.manage_issues': '管理项目问题',
  'project.export': '导出项目',
  'project.archive': '归档与复盘操作',
  'project.manage_inventory': '管理现场物品',
}

export default function MemberPermissions({ project, members, onReload }: {
  project: Project
  members: Array<{ id: string; display_name?: string; role?: string; inherited_capabilities?: string[] }>
  onReload?: () => void
}) {
  const { user } = useAuth()
  const canInspect = (userId: string) => user?.id === userId || user?.role === 'admin' || project.capabilities?.includes('project.manage_members')
  const canGrant = !!project.capabilities?.includes('project.manage_members') || project.capabilities === undefined
  const [reasonMember, setReasonMember] = useState<string | null>(null)
  const [reasons, setReasons] = useState<PermissionReason[]>([])
  const [reasonsLoading, setReasonsLoading] = useState(false)
  const [reasonsError, setReasonsError] = useState('')
  const reasonSequence = useRef(0)
  const reasonProjectId = useRef(project.id)
  useEffect(() => { setReasonMember(null); return () => { reasonSequence.current++ } }, [project.id])
  const explain = async (userId: string) => {
    const sequence = ++reasonSequence.current
    reasonProjectId.current = project.id
    setReasonMember(userId); setReasons([]); setReasonsError(''); setReasonsLoading(true)
    try {
      const data = await permissionsApi.projectReasons(project.id, userId)
      if (sequence === reasonSequence.current) setReasons(data.items)
    } catch (error) { if (sequence === reasonSequence.current) setReasonsError(errMsg(error)) }
    finally { if (sequence === reasonSequence.current) setReasonsLoading(false) }
  }
  const writeBlocked = useProjectWriteBlocked(project.status)
  const snapshot = useRef({ id: project.id, version: project.version, grants: project.member_permissions ?? [] })
  const saveLock = useRef(false)
  const [editing, setEditing] = useState<string | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const grants = project.member_permissions ?? []
  const grantable = project.grantable_capabilities ?? []
  const save = async () => {
    if (!editing || saveLock.current || snapshot.current.id !== project.id || writeBlocked || !grantable.length || !canGrant) return
    saveLock.current = true
    setSaving(true); setError('')
    try {
      await projectApi.update(project.id, {
        version: snapshot.current.version,
        member_permissions: [
          ...snapshot.current.grants.filter(grant => grant.user_id !== editing),
          ...(selected.length ? [{ user_id: editing, capabilities: selected }] : []),
        ],
      })
      setEditing(null)
      onReload?.()
    } catch (err) { setError(errMsg(err)) }
    finally { saveLock.current = false; setSaving(false) }
  }
  return <Card title="成员操作授权" size="small" style={{ marginTop: 16 }}>
    <Typography.Paragraph type="secondary">成员默认可查看项目。以下额外操作权限仅对本项目生效，不会变更账号角色，也不允许转授权限。清空选项并保存可撤销额外授权；负责人等既有职责权限仍保留。</Typography.Paragraph>
    {members.map(member => <div key={member.id} style={{ marginBottom: 12 }}>
      <Space wrap><Typography.Text strong>{member.display_name || member.id}</Typography.Text>
        {canInspect(member.id) && <Button size="small" onClick={() => void explain(member.id)}>查看无权限原因</Button>}
        {!!member.inherited_capabilities?.length && <Typography.Text type="secondary">职责自带（不可在此撤销）：{member.inherited_capabilities.map(cap => CAPABILITY_LABELS[cap] ?? cap).join('、')}</Typography.Text>}
        {(grants.find(grant => grant.user_id === member.id)?.capabilities ?? []).map(cap => <Tag key={cap}>{CAPABILITY_LABELS[cap] ?? cap}</Tag>)}
        {!grants.some(grant => grant.user_id === member.id && grant.capabilities.length) && <Typography.Text type="secondary">无额外操作授权</Typography.Text>}
        {member.role === 'readonly' && <Typography.Text type="secondary">只读预设不能授予写权限</Typography.Text>}
        {!!grantable.length && !writeBlocked && canGrant && member.role !== 'readonly' && <Button size="small" onClick={() => {
          snapshot.current = { id: project.id, version: project.version, grants: grants.map(grant => ({ ...grant, capabilities: [...grant.capabilities] })) };
          setEditing(member.id); setSelected(grants.find(grant => grant.user_id === member.id)?.capabilities ?? []); setError('')
        }}>配置授权</Button>}
      </Space>
    </div>)}
    <Modal key={project.id} title={`查看权限原因 · ${members.find(member => member.id === reasonMember)?.display_name ?? ''}`} open={reasonMember !== null && reasonProjectId.current === project.id}
      onCancel={() => { reasonSequence.current++; setReasonMember(null) }} footer={<Button onClick={() => { reasonSequence.current++; setReasonMember(null) }}>关闭</Button>}>
      {reasonsLoading && <Typography.Paragraph>正在核对已保存的权限…</Typography.Paragraph>}
      {reasonsError && <Alert type="error" showIcon message={reasonsError} action={<Button onClick={() => reasonMember && void explain(reasonMember)}>重试</Button>} />}
      {reasons.map(item => <p key={item.key}><Tag color={item.allowed ? 'green' : 'default'}>{item.name}</Tag>{item.reason}</p>)}
    </Modal>
    <Modal title={`配置本项目授权 · ${members.find(member => member.id === editing)?.display_name ?? ''}`} open={editing !== null}
      onCancel={() => { if (!saving) setEditing(null) }} onOk={save} okText="保存授权" cancelText="取消" confirmLoading={saving}
      okButtonProps={{ disabled: writeBlocked || !grantable.length || !canGrant }} maskClosable={false}>
      {error && <Alert type="error" showIcon message={error} description="若项目已被其他人更新，请先刷新再重新核对授权。" action={<Button onClick={() => { setEditing(null); onReload?.() }}>刷新并重新核对</Button>} />}
      <Checkbox.Group aria-label="本项目操作权限" value={selected} onChange={values => setSelected(values as string[])}
        disabled={saving} options={grantable.map(value => ({ value, label: CAPABILITY_LABELS[value] ?? value }))} />
      <Typography.Paragraph type="secondary" style={{ marginTop: 12 }}>取消全部勾选会撤销该成员的额外操作授权。项目查看和本人任务填报不受影响。</Typography.Paragraph>
    </Modal>
  </Card>
}
