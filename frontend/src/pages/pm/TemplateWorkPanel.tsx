import { useEffect, useRef, useState } from 'react'
import { Button, Checkbox, Divider, Input, Popconfirm, Segmented, Select, Typography, Upload } from 'antd'
import { ArrowDownOutlined, ArrowUpOutlined, CheckOutlined, CloseOutlined, DeleteOutlined, LoadingOutlined, PaperClipOutlined, PlusOutlined, UploadOutlined, WarningOutlined } from '@ant-design/icons'
import type { WorkItem, WorkPhase } from '../../api/workItems'
import { stageLabel } from '../../constants/stages'
import { useVehicleTypes } from '../../hooks/useVehicleTypes'
import { downloadDocumentResource } from '../../api/projectDocuments'
import { IconAction } from '../../components/IconAction'

export type SaveState = { state: 'saving' | 'saved' | 'error'; error?: string }
type Check = { key: string; name: string; description: string; is_required: boolean; is_safety_critical: boolean }
type Props = {
  item: WorkItem; phases: WorkPhase[]; steps: { key: string; name: string }[]; templateId: string; canManage: boolean; save?: SaveState
  onPatch: (patch: Record<string, unknown>) => Promise<void>; onDelete: () => void; onMove: (delta: -1 | 1) => void; canMove: { up: boolean; down: boolean }
  onCreateStep: (name: string) => Promise<string>; onUpload: (file: File) => void; onRemoveRef: (id: string, filename: string) => void; onClose: () => void
}

const SCOPES = [{ value: 'need_wms', label: 'WMS 对接' }, { value: 'need_charging', label: '自动充电' }]
const checksOf = (item: WorkItem): Check[] => (item.check_definitions ?? []).map((c, index) => ({ key: `${item.id}-${index}`, name: c.name, description: c.description ?? '', is_required: c.is_required, is_safety_critical: c.is_safety_critical }))
const payload = (checks: Check[]) => checks.filter(c => c.name.trim()).map(c => ({ name: c.name.trim(), description: c.description.trim(), is_required: c.is_required, is_safety_critical: c.is_safety_critical }))
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)

export function SaveBadge({ save }: { save?: SaveState }) {
  if (!save) return null
  if (save.state === 'saving') return <span className="tpl-save is-saving" role="status"><LoadingOutlined />保存中</span>
  if (save.state === 'error') return <span className="tpl-save is-error" role="alert"><WarningOutlined />{save.error || '保存失败'}</span>
  return <span className="tpl-save" role="status"><CheckOutlined />已保存</span>
}

/** Everything about one template work item, edited in place: text saves when you leave the field, choices save at once. */
export default function TemplateWorkPanel({ item, phases, steps, templateId, canManage, save, onPatch, onDelete, onMove, canMove, onCreateStep, onUpload, onRemoveRef, onClose }: Props) {
  const { options: vehicleTypes } = useVehicleTypes()
  const [name, setName] = useState(item.name)
  const [description, setDescription] = useState(item.description ?? '')
  const [label, setLabel] = useState(item.group_label ?? '')
  const [kind, setKind] = useState(item.kind)
  const [checks, setChecks] = useState<Check[]>(() => checksOf(item))
  const [newStep, setNewStep] = useState('')
  const focusCheck = useRef<string | null>(null)
  useEffect(() => { setName(item.name); setDescription(item.description ?? ''); setLabel(item.group_label ?? ''); setKind(item.kind); setChecks(checksOf(item)) }, [item.id])
  useEffect(() => { setKind(item.kind) }, [item.kind])
  const phase = phases.find(p => p.work_items.some(w => w.id === item.id))
  const disabled = !canManage

  const saveName = () => { const value = name.trim(); if (!value) { setName(item.name); return } if (value !== item.name) void onPatch({ name: value }) }
  const saveText = (key: 'description' | 'group_label', value: string) => { if (value !== (item[key] ?? '')) void onPatch({ [key]: value }) }
  const saveChecks = (next: Check[]) => { if (!same(payload(next), payload(checksOf(item)))) void onPatch({ checks: payload(next) }) }
  const editCheck = (key: string, change: Partial<Check>, commit = false) => {
    const next = checks.map(c => c.key === key ? { ...c, ...change } : c)
    setChecks(next); if (commit) saveChecks(next)
  }
  const blankCheck = (): Check => { const key = `${item.id}-new-${Date.now()}`; focusCheck.current = key; return { key, name: '', description: '', is_required: true, is_safety_critical: false } }
  const addStep = async () => {
    const value = newStep.trim(); if (!value) return
    const key = await onCreateStep(value); setNewStep('')
    await onPatch({ kind: 'vehicle', vehicle_step_key: key })
  }

  return <aside className="tpl-panel" aria-label={`编辑工作项：${item.name}`}>
    <header className="tpl-panel-head">
      <span className="tpl-panel-kicker">{phase ? `${stageLabel(phase.stage_key)} / ${phase.name}` : '工作项'}</span>
      <SaveBadge save={save} />
      {canManage && <span className="tpl-panel-move">
        <IconAction label="上移" icon={<ArrowUpOutlined />} disabled={!canMove.up} onClick={() => onMove(-1)} />
        <IconAction label="下移" icon={<ArrowDownOutlined />} disabled={!canMove.down} onClick={() => onMove(1)} />
      </span>}
      <IconAction label="关闭编辑" icon={<CloseOutlined />} onClick={onClose} />
    </header>
    <div className="tpl-panel-body">
      <Input className="tpl-panel-title" aria-label="工作项名称" value={name} maxLength={200} disabled={disabled} variant="borderless"
        onChange={e => setName(e.target.value)} onBlur={saveName} onPressEnter={e => (e.target as HTMLInputElement).blur()} />
      <Input.TextArea aria-label="工作说明" placeholder="写给现场的说明：做什么、怎么算完成" value={description} disabled={disabled} autoSize={{ minRows: 2, maxRows: 10 }} maxLength={20000}
        onChange={e => setDescription(e.target.value)} onBlur={() => saveText('description', description)} />

      <div className="tpl-fields">
        <label className="tpl-field-row"><span>所在分组</span>
          <Select aria-label="所在分组" value={phase?.id} disabled={disabled} onChange={value => void onPatch({ phase_id: value })} popupMatchSelectWidth={false}
            options={phases.map(p => ({ value: p.id, label: `${stageLabel(p.stage_key)} / ${p.name}` }))} />
        </label>
        <div className="tpl-field-row"><span id={`kind-${item.id}`}>记录方式</span>
          <Segmented aria-labelledby={`kind-${item.id}`} value={kind} disabled={disabled} options={[{ value: 'other', label: '完成 / 未完成' }, { value: 'vehicle', label: '逐车记录' }]}
            onChange={value => { const next = value as WorkItem['kind']; setKind(next); if (next === 'other' && item.kind === 'vehicle') void onPatch({ kind: 'other' }) }} />
        </div>
        {kind === 'vehicle' && <label className="tpl-field-row"><span>车辆环节</span>
          <Select aria-label="车辆环节" value={item.kind === 'vehicle' ? item.vehicle_step_key ?? undefined : undefined} placeholder="选择每台车在哪个环节记录" disabled={disabled}
            status={item.kind !== 'vehicle' ? 'warning' : undefined} onChange={value => void onPatch({ kind: 'vehicle', vehicle_step_key: value })}
            options={steps.map(s => ({ value: s.key, label: s.name }))}
            dropdownRender={menu => <>{menu}{canManage && <div className="tpl-select-add"><Input size="small" placeholder="新建环节，如：防撞测试" value={newStep} maxLength={50}
              onChange={e => setNewStep(e.target.value)} onKeyDown={e => e.stopPropagation()} onPressEnter={() => void addStep()} />
              <Button size="small" type="link" icon={<PlusOutlined />} disabled={!newStep.trim()} onClick={() => void addStep()}>新建</Button></div>}</>} />
        </label>}
        {kind === 'vehicle' && item.kind !== 'vehicle' && <p className="tpl-field-hint">选好环节后才会改为逐车记录。</p>}
        {kind === 'vehicle' && <label className="tpl-field-row"><span>适用车型</span>
          <Select aria-label="适用车型" mode="multiple" allowClear placeholder="全部车型" value={item.applicable_vehicle_types} disabled={disabled} options={vehicleTypes}
            onChange={value => void onPatch({ applicable_vehicle_types: value })} />
        </label>}
        <label className="tpl-field-row"><span>业务范围</span>
          <Select aria-label="业务范围" mode="multiple" allowClear placeholder="所有项目都带入" value={item.scope_conditions} disabled={disabled} options={SCOPES}
            onChange={value => void onPatch({ scope_conditions: value })} />
        </label>
        <label className="tpl-field-row"><span>标签</span>
          <Input aria-label="标签" placeholder="可选，如 WMS/MES 对接" value={label} disabled={disabled} maxLength={200}
            onChange={e => setLabel(e.target.value)} onBlur={() => saveText('group_label', label)} onPressEnter={e => (e.target as HTMLInputElement).blur()} />
        </label>
      </div>

      <Divider orientation="left" plain>检查要求 {checks.filter(c => c.name.trim()).length}</Divider>
      <ul className="tpl-checks" aria-label="检查要求">{checks.map((check, index) => <li key={check.key}>
        <div className="tpl-check-main">
          <Input aria-label={`检查要求${index + 1}`} placeholder="检查内容" value={check.name} disabled={disabled} maxLength={300} variant="borderless"
            autoFocus={focusCheck.current === check.key} onChange={e => editCheck(check.key, { name: e.target.value })} onBlur={() => saveChecks(checks)}
            onPressEnter={() => { saveChecks(checks); setChecks([...checks.slice(0, index + 1), blankCheck(), ...checks.slice(index + 1)]) }} />
          <Input aria-label={`检查要求${index + 1}说明`} placeholder="说明（可选）" value={check.description} disabled={disabled} maxLength={10000} variant="borderless" size="small"
            onChange={e => editCheck(check.key, { description: e.target.value })} onBlur={() => saveChecks(checks)} />
        </div>
        <Checkbox checked={check.is_required} disabled={disabled} onChange={e => editCheck(check.key, { is_required: e.target.checked }, true)}>必需</Checkbox>
        <Checkbox checked={check.is_safety_critical} disabled={disabled} onChange={e => editCheck(check.key, { is_safety_critical: e.target.checked }, true)}>安全关键</Checkbox>
        {canManage && <IconAction label={`删除检查要求${index + 1}`} icon={<DeleteOutlined />} onClick={() => { const next = checks.filter(c => c.key !== check.key); setChecks(next); saveChecks(next) }} />}
      </li>)}</ul>
      {canManage && <Button type="dashed" block icon={<PlusOutlined />} onClick={() => setChecks([...checks, blankCheck()])}>添加检查</Button>}

      <Divider orientation="left" plain>参考文档 {item.reference_docs.length}</Divider>
      <ul className="tpl-refs">{item.reference_docs.map((ref: any) => <li key={ref.id}>
        <Button type="link" icon={<PaperClipOutlined />} onClick={() => void downloadDocumentResource(`/templates/${templateId}/tasks/${item.id}/reference-docs/${ref.id}/download`, ref.filename)}>{ref.filename}</Button>
        {ref.note && <Typography.Text type="secondary">{ref.note}</Typography.Text>}
        {canManage && <Popconfirm title={`删除参考文档「${ref.filename}」？`} okText="删除" cancelText="取消" onConfirm={() => onRemoveRef(ref.id, ref.filename)}>
          <IconAction label={`删除参考文档「${ref.filename}」`} icon={<DeleteOutlined />} /></Popconfirm>}
      </li>)}</ul>
      {canManage && <Upload showUploadList={false} beforeUpload={file => { onUpload(file); return false }}><Button icon={<UploadOutlined />}>上传参考文档</Button></Upload>}
    </div>
    {canManage && <footer className="tpl-panel-foot">
      <Popconfirm title={`删除工作项「${item.name}」？`} description="已创建的项目不受影响。" okText="删除" okButtonProps={{ danger: true }} cancelText="取消" onConfirm={onDelete}>
        <Button danger type="text" icon={<DeleteOutlined />}>删除工作项</Button>
      </Popconfirm>
    </footer>}
  </aside>
}
