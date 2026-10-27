import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Input, Space, Typography } from 'antd'
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
  return <section aria-label="模板车辆环节">
    <Typography.Paragraph>按顺序配置车辆进度表环节。保存后只用于新项目，已有项目保留原环节。</Typography.Paragraph>
    {error && <Alert type="error" message={error} action={<Button onClick={() => void load()}>重试读取</Button>} />}
    {steps.map((s, i) => <Space key={s.key} style={{ display: 'flex', marginBottom: 10 }}><span>{i + 1}</span><Input aria-label={`车辆环节${i + 1}名称`} value={s.name} disabled={!canManage || saving} onChange={e => setSteps(old => old.map((row, index) => index === i ? { ...row, name: e.target.value } : row))} />
      {canManage && <><Button disabled={!i || saving} onClick={() => setSteps(old => { const next = [...old]; [next[i - 1], next[i]] = [next[i], next[i - 1]]; return next })}>上移</Button><Button disabled={steps.length <= 1 || saving} onClick={() => setSteps(old => old.filter((_, index) => index !== i))}>删除环节</Button></>}
    </Space>)}
    {canManage && <Space><Button disabled={loading || saving || steps.length >= 30} onClick={() => setSteps(old => [...old, { key: `step_${crypto.randomUUID().replace(/-/g, '')}`, name: '' }])}>添加车辆环节</Button><Button type="primary" disabled={loading || !steps.length || steps.some(s => !s.name.trim())} loading={saving} onClick={() => void save()}>保存车辆环节</Button></Space>}
  </section>
}
