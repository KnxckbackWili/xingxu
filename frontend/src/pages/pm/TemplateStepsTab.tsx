import { useEffect, useRef, useState } from 'react'
import { Input, message } from 'antd'
import { ArrowDownOutlined, ArrowUpOutlined, CarOutlined, DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { api, errMsg } from '../../api/client'
import type { WorkPhase } from '../../api/workItems'
import { useAuth } from '../../stores/auth'
import { ensureVerifiedAccount } from '../../utils/verifiedAccount'
import { IconAction } from '../../components/IconAction'
import { SaveBadge, type SaveState } from './TemplateWorkPanel'

type Step = { key: string; name: string }

/** Vehicle steps edited in place: rename by typing, reorder with the arrows, add with Enter. Each change saves the whole order. */
export default function TemplateStepsTab({ templateId, steps, setSteps, phases, canManage }: { templateId: string; steps: Step[]; setSteps: (steps: Step[]) => void; phases: WorkPhase[]; canManage: boolean }) {
  const { user } = useAuth()
  const [names, setNames] = useState<Record<string, string>>({})
  const [save, setSave] = useState<SaveState>()
  const [adding, setAdding] = useState('')
  const queue = useRef<Promise<unknown>>(Promise.resolve())
  useEffect(() => { setNames(Object.fromEntries(steps.map(s => [s.key, s.name]))) }, [steps])
  const linked = (key: string) => phases.flatMap(p => p.work_items).filter(item => item.kind === 'vehicle' && item.vehicle_step_key === key)

  const persist = (next: Step[]) => {
    const previous = steps
    setSteps(next)
    queue.current = queue.current.then(async () => {
      setSave({ state: 'saving' })
      try { ensureVerifiedAccount(user?.id); await api.put(`/templates/${templateId}/vehicle-steps`, { steps: next }); setSave({ state: 'saved' }) }
      catch (e) { setSteps(previous); setSave({ state: 'error', error: errMsg(e) }); message.error(errMsg(e)) }
    })
  }
  const rename = (key: string) => {
    const value = (names[key] ?? '').trim()
    const step = steps.find(s => s.key === key)
    if (!step) return
    if (!value) { setNames(old => ({ ...old, [key]: step.name })); return }
    if (value !== step.name) persist(steps.map(s => s.key === key ? { ...s, name: value } : s))
  }
  const swap = (index: number, delta: -1 | 1) => { const next = [...steps]; [next[index], next[index + delta]] = [next[index + delta], next[index]]; persist(next) }
  const add = () => {
    const value = adding.trim(); if (!value) return
    persist([...steps, { key: `step_${globalThis.crypto?.randomUUID?.().replace(/-/g, '') ?? Date.now().toString(36)}`, name: value }]); setAdding('')
  }

  return <div className="tpl-tab tpl-steps">
    <div className="tpl-toolbar">
      <span className="tpl-toolbar-note">每台车按这个顺序逐车记录。逐车工作在“工作”页签里选择所属环节。</span>
      <SaveBadge save={save} />
    </div>
    <ol className="tpl-step-rows" aria-label="车辆环节">{steps.map((step, index) => {
      const work = linked(step.key)
      return <li key={step.key}>
        <span className="tpl-stage-key">{index + 1}</span>
        <div className="tpl-step-main">
          <Input aria-label={`车辆环节${index + 1}名称`} value={names[step.key] ?? step.name} maxLength={50} disabled={!canManage} variant="borderless" className="tpl-step-name"
            onChange={e => setNames(old => ({ ...old, [step.key]: e.target.value }))} onBlur={() => rename(step.key)} onPressEnter={e => (e.target as HTMLInputElement).blur()} />
          <span className="tpl-step-work">{work.length ? work.map(item => <span key={item.id}><CarOutlined aria-hidden />{item.name}</span>) : '暂无逐车工作'}</span>
        </div>
        {canManage && <span className="tpl-step-actions">
          <IconAction label={`上移车辆环节${index + 1}`} icon={<ArrowUpOutlined />} disabled={!index} onClick={() => swap(index, -1)} />
          <IconAction label={`下移车辆环节${index + 1}`} icon={<ArrowDownOutlined />} disabled={index === steps.length - 1} onClick={() => swap(index, 1)} />
          <IconAction label={work.length ? `车辆环节${index + 1}仍有关联工作，不能删除` : `删除车辆环节${index + 1}`} icon={<DeleteOutlined />} disabled={!!work.length || steps.length <= 1}
            onClick={() => persist(steps.filter(s => s.key !== step.key))} />
        </span>}
      </li>
    })}</ol>
    {canManage && steps.length < 30 && <div className="tpl-step-add">
      <PlusOutlined aria-hidden />
      <Input aria-label="新车辆环节名称" placeholder="添加环节，回车保存" value={adding} maxLength={50} variant="borderless" onChange={e => setAdding(e.target.value)} onPressEnter={add} onBlur={add} />
    </div>}
  </div>
}
