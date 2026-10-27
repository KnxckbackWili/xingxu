import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Input, Popconfirm, Space } from 'antd'
import type { Project } from '../../../api'
import { api, errMsg } from '../../../api/client'
import { useAuth } from '../../../stores/auth'
import { useUnsavedNavigation } from '../../../hooks/useUnsavedNavigation'

export default function LegacyLifecycleRepair({ project, onChanged }: { project: Project; onChanged: () => void }) {
  const { user } = useAuth()
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const locked = useRef(false)
  const generation = useRef(0)
  const [, setDirty] = useUnsavedNavigation()
  useEffect(() => { generation.current++; locked.current = false; setBusy(false); setReason(''); setError(''); return () => { generation.current++ } }, [project.id, user?.id])
  useEffect(() => { setDirty(!!reason.trim()); return () => setDirty(false) }, [reason, setDirty])
  if (!project.legacy_lifecycle?.requires_repair) return null
  const repair = async () => {
    if (locked.current || user?.role !== 'admin' || !reason.trim()) return
    const ticket = generation.current
    locked.current = true; setBusy(true); setError('')
    try {
      await api.post(`/projects/${project.id}/lifecycle-repair`, { version: project.version, reason: reason.trim() })
      if (ticket === generation.current) { setReason(''); setDirty(false); onChanged() }
    } catch (failure) { if (ticket === generation.current) setError(errMsg(failure)) }
    finally { if (ticket === generation.current) { locked.current = false; setBusy(false) } }
  }
  return <Alert type="warning" showIcon message="历史状态需明确核对，项目暂时只读"
    description={<Space direction="vertical" style={{ width: '100%' }}>
      <span>原状态：{project.legacy_lifecycle.original_status || '空值'}。原记录和文件已保留。</span>
      {user?.role === 'admin' && <><span>根据备份和操作记录核对后，可明确重置筹备；后续仍需逐阶段检查资料和批准，系统不推定原状态。</span>
        <Input.TextArea aria-label="历史状态核对依据" value={reason} onChange={event => setReason(event.target.value)} disabled={busy} maxLength={5000} rows={2} />
        <Popconfirm title="核对后明确重置为筹备？" description="原历史状态保留，完成和验收资格不会自动取得。" onConfirm={repair} disabled={busy || !reason.trim()}>
          <Button disabled={busy || !reason.trim()} loading={busy}>核对后重置筹备</Button>
        </Popconfirm></>}
      {error && <Alert type="error" message={error} />}
    </Space>} />
}
