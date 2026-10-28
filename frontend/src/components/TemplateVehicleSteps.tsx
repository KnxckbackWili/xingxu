import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Input, Typography } from 'antd'
import { ArrowDownOutlined, ArrowUpOutlined, DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { IconAction } from './IconAction'
import { api, errMsg } from '../api/client'

export default function TemplateVehicleSteps({ templateId, canManage }: { templateId: string; canManage: boolean }) {
  const [steps, setSteps] = useState<{ key: string; name: string }[]>([])
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(true)
  const lock = useRef(false)
  const generation = useRef(0)
  const active = useRef(templateId); active.current = templateId
  const load = async () => {
    const g = ++generation.current; setLoading(true); setError('')
    try { const r = await api.get(`/templates/${templateId}/vehicle-steps`); if (g === generation.current) setSteps(r.data) }
    catch (e) { if (g === generation.current) setError(errMsg(e)) }
    finally { if (g === generation.current) setLoading(false) }
  }
  useEffect(() => { setSteps([]); void load(); return () => { generation.current++ } }, [templateId])
  const save = async () => {
    if (lock.current || loading) return
    const id = templateId; const gen = generation.current
    lock.current = true; setSaving(true)
    try { await api.put(`/templates/${id}/vehicle-steps`, { steps }); if (active.current === id && gen === generation.current) setError('') }
    catch (e) { if (active.current === id && gen === generation.current) setError(errMsg(e)) }
    finally { lock.current = false; setSaving(false) }
  }
  const move = (from: number, to: number) => setSteps(old => { const next = [...old]; [next[from], next[to]] = [next[to], next[from]]; return next })
  return <section aria-label="模板车辆环节" className="template-steps">
    <Typography.Paragraph type="secondary">车辆进度表按这里的顺序逐车记录；保存后只用于新项目，已有项目保留原环节。</Typography.Paragraph>
    {error && <Alert type="error" message={error} action={<Button onClick={() => void load()}>重试读取</Button>} />}
    <ol className="template-step-list">{steps.map((s, i) => <li key={s.key}>
      <span className="template-step-index" aria-hidden="true">{i + 1}</span>
      <Input aria-label={`车辆环节${i + 1}名称`} value={s.name} disabled={!canManage || saving} maxLength={50}
        onChange={e => setSteps(old => old.map((row, index) => index === i ? { ...row, name: e.target.value } : row))} />
      {canManage && <span className="row-icon-actions">
        <IconAction label={`上移车辆环节${i + 1}`} icon={<ArrowUpOutlined />} disabled={!i || saving} onClick={() => move(i, i - 1)} />
        <IconAction label={`下移车辆环节${i + 1}`} icon={<ArrowDownOutlined />} disabled={i === steps.length - 1 || saving} onClick={() => move(i, i + 1)} />
        <IconAction label={`删除车辆环节${i + 1}`} icon={<DeleteOutlined />} danger disabled={steps.length <= 1 || saving} onClick={() => setSteps(old => old.filter((_, index) => index !== i))} />
      </span>}
    </li>)}</ol>
    {canManage && <div className="template-step-actions"><Button icon={<PlusOutlined />} disabled={loading || saving || steps.length >= 30} onClick={() => setSteps(old => [...old, { key: `step_${crypto.randomUUID().replace(/-/g, '')}`, name: '' }])}>添加车辆环节</Button><Button type="primary" disabled={loading || !steps.length || steps.some(s => !s.name.trim())} loading={saving} onClick={() => void save()}>保存车辆环节</Button></div>}
  </section>
}
