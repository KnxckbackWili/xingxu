import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Modal, Typography, message } from 'antd'
import { DeleteOutlined } from '@ant-design/icons'
import { projectApi, type Project } from '../api'
import { errMsg } from '../api/client'
import { useAuth } from '../stores/auth'
import type { PermissionUser } from '../constants/systemPermissions'
import './ProjectDeleteButton.css'
import { IconAction } from './IconAction'

type DeletableProject = Pick<Project, 'id' | 'name' | 'manager' | 'capabilities' | 'version' | 'can_delete'>
export function canDeleteProject(project: DeletableProject, user: PermissionUser | null | undefined) {
  if (!user || user.permission_overrides?.['project.delete'] === false || user.permission_overrides?.['project.read'] === false) return false
  if (typeof project.can_delete === 'boolean') return project.can_delete
  if (Array.isArray(project.capabilities)) return project.capabilities.includes('project.delete')
  return user.role === 'admin' || (!!user.id && project.manager === user.id && ['pm', 'lead'].includes(user.role ?? '')) || user.permission_overrides?.['project.delete'] === true || !!user.system_permissions?.includes('project.delete')
}

/** One explicit confirmation; the server backs up before any soft deletion. */
export default function ProjectDeleteButton({ project, onDeleted }: { project: DeletableProject; onDeleted: () => void }) {
  const { user } = useAuth()
  const scopeKey = JSON.stringify([project.id, project.version, project.can_delete, project.capabilities, user?.id, user?.role, user?.permission_version, user?.permission_overrides, user?.system_permissions])
  const scope = useRef({ key: scopeKey, generation: 0 })
  if (scope.current.key !== scopeKey) scope.current = { key: scopeKey, generation: scope.current.generation + 1 }
  const generation = scope.current.generation
  const [openScope, setOpenScope] = useState<string | null>(null)
  const open = openScope === scopeKey
  const [fresh, setFresh] = useState<{ scope: string; project: DeletableProject } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [conflict, setConflict] = useState(false)
  const lock = useRef(false)
  const alive = useRef(true)
  const readController = useRef<AbortController | null>(null)
  const current = fresh?.scope === scopeKey ? fresh.project : project
  const allowed = canDeleteProject(current, user)
  const context = useRef({ id: project.id, allowed })
  context.current = { id: project.id, allowed }
  const sameScope = () => alive.current && scope.current.generation === generation
  useEffect(() => { setFresh(null); setOpenScope(null); setError(''); setConflict(false); readController.current?.abort() }, [scopeKey])
  useEffect(() => { alive.current = true; return () => { alive.current = false; readController.current?.abort() } }, [])
  const readCurrent = async () => {
    if (!sameScope() || lock.current) return
    lock.current = true; setBusy(true)
    const id = project.id
    const controller = new AbortController()
    readController.current = controller
    try {
      const data = await projectApi.get(id, { signal: controller.signal })
      if (!sameScope()) return
      if (data.id !== id) { setError('项目读取结果不匹配，请返回列表重新加载'); return }
      setFresh({ scope: scopeKey, project: data }); setConflict(false)
      setError(canDeleteProject(data, user) ? '' : '删除权限已变化，此项目当前不能删除。')
    } catch (cause) { if (sameScope() && !controller.signal.aborted) setError(errMsg(cause)) }
    finally { lock.current = false; if (alive.current) setBusy(false) }
  }
  const remove = async () => {
    if (!sameScope() || !context.current.allowed || conflict || current.version === undefined || lock.current) return
    lock.current = true; setBusy(true); setError('')
    const id = project.id
    try {
      await projectApi.remove(id, { version: current.version })
      if (!sameScope()) return
      setOpenScope(null); message.success('项目已备份并放入回收站，可还原原项目'); onDeleted()
    } catch (cause: any) {
      if (!sameScope()) return
      setError(errMsg(cause)); setConflict(cause.response?.status === 409)
    } finally { lock.current = false; if (alive.current) setBusy(false) }
  }
  if (!allowed && !open) return null
  return <span className="project-delete-action" onClick={event => event.stopPropagation()}>
    {allowed && <IconAction label="删除项目" disabled={busy} danger icon={<DeleteOutlined aria-hidden />} aria-label={`删除项目：${project.name}`} onClick={() => {
      setError(''); setConflict(false); setOpenScope(scopeKey)
      if (project.version === undefined) void readCurrent()
    }} />}
    <Modal className="project-delete-modal" title="删除这个项目？" open={open} onOk={remove}
      onCancel={() => { if (!lock.current) setOpenScope(null) }} okText="备份并删除" cancelText="保留项目"
      confirmLoading={busy} okButtonProps={{ danger: true, disabled: !allowed || current.version === undefined || conflict }}
      cancelButtonProps={{ disabled: busy }} closable={!busy} maskClosable={!busy}>
      <Typography.Title level={5} className="project-delete-name">{current.name}</Typography.Title>
      <Typography.Paragraph>系统会先备份此项目的资料和文件，再将项目放入回收站。备份失败时不会删除。</Typography.Paragraph>
      <Typography.Paragraph>无需审批。删除后项目会从工作列表移除；你可以在「项目回收站」还原原项目，原状态、成员和记录都会保留。</Typography.Paragraph>
      {busy && <Typography.Text type="secondary">正在处理，请等待结果后再离开。</Typography.Text>}
      {error && <Alert type="error" showIcon message={conflict ? '项目已变化，请重新核对后确认' : '未能确认删除结果，请核对后重试'} description={error}
        action={conflict ? <Button disabled={busy} onClick={() => void readCurrent()}>重新读取项目</Button> : undefined} />}
      {!busy && current.version === undefined && <Button onClick={() => void readCurrent()}>重新读取项目版本</Button>}
    </Modal>
  </span>
}
