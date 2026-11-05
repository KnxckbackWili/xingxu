import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, Button, Empty, Input, Modal, Select, Skeleton, Tag } from 'antd'
import { CarOutlined, PlusOutlined, StarFilled } from '@ant-design/icons'
import { api, errMsg } from '../../api/client'
import { useAuth } from '../../stores/auth'
import { hasSystemPermission } from '../../constants/systemPermissions'
import { ensureVerifiedAccount } from '../../utils/verifiedAccount'
import { WorkPageHeader } from '../../components/WorkPage'
import { RefreshAction } from '../../components/IconAction'
import type { TemplateRow } from './templateMeta'
import { toVehicleTypeSelectOptions, useVehicleTypes } from '../../hooks/useVehicleTypes'
import './TemplateEditorPage.css'


/** The template library: one template per vehicle type plus the general one; a card opens the template. */
export default function TemplateLibraryPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const canManage = hasSystemPermission(user, 'system.templates.manage')
  const canCreateProject = hasSystemPermission(user, 'projects.create')
  const [templates, setTemplates] = useState<TemplateRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [draft, setDraft] = useState<{ name: string; from: string; vehicleType?: string; named?: boolean }>()
  const { options: vehicleDictionary } = useVehicleTypes()
  const [busy, setBusy] = useState(false)
  const generation = useRef(0)
  const load = async () => {
    const seq = ++generation.current; setLoading(true)
    try { const result = await api.get('/templates'); if (seq === generation.current) { setTemplates(result.data); setError('') } }
    catch (e) { if (seq === generation.current) setError(errMsg(e)) }
    finally { if (seq === generation.current) setLoading(false) }
  }
  useEffect(() => { void load(); return () => { generation.current++ } }, [user?.id])
  const create = async () => {
    if (!draft?.name.trim() || busy || !canManage) return
    setBusy(true)
    try { ensureVerifiedAccount(user?.id); const result = await api.post('/templates', { name: draft.name.trim(), copy_from: draft.from, vehicle_type: draft.vehicleType ?? null }); setDraft(undefined); navigate(`/pm/templates/${result.data.id}`) }
    catch (e) { setError(errMsg(e)) } finally { setBusy(false) }
  }

  const taken = new Map(templates.filter(t => t.vehicle_type).map(t => [t.vehicle_type!, t.name]))
  const typeOptions = toVehicleTypeSelectOptions(vehicleDictionary, []).map(option => ({ ...option, disabled: taken.has(String(option.value)), label: taken.has(String(option.value)) ? `${option.label}（已有模板）` : option.label }))
  const missing = toVehicleTypeSelectOptions(vehicleDictionary, []).map(option => String(option.value)).filter(type => !taken.has(type))
  const startDraft = (vehicleType?: string) => setDraft({ name: vehicleType ? `${vehicleType}模板` : '', from: 'default', vehicleType })
  // General template first, then one per vehicle type in dictionary order.
  const order = (t: TemplateRow) => t.is_system ? -1 : t.vehicle_type ? (vehicleDictionary.findIndex(o => o.name === t.vehicle_type) + 1 || 999) : 10_000
  const sorted = [...templates].sort((a, b) => order(a) - order(b))

  const card = (t: TemplateRow) => {
    const count = t.summary ?? { work: 0, file: 0, purchase: 0, files: 0, sections: 0 }
    return <li key={t.id} className="tpl-card">
      <button type="button" className="tpl-card-main" onClick={() => navigate(`/pm/templates/${t.id}`)} aria-label={`打开模板「${t.name}」`}>
        <span className="tpl-card-top">
          <span className="tpl-card-icon" aria-hidden="true">{t.is_system ? <StarFilled /> : <CarOutlined />}</span>
          <span className="tpl-card-name">{t.name}</span>
          {t.is_system ? <Tag color="blue">通用</Tag> : t.vehicle_type ? <Tag color="geekblue">{t.vehicle_type}</Tag> : <Tag>未设车型</Tag>}
        </span>
        <span className="tpl-card-desc">{t.description || '没有说明'}</span>
        <span className="tpl-card-stats"><span><strong>{count.work + count.file + count.purchase}</strong> 件事</span><span><strong>{count.work}</strong> 项工作</span><span><strong>{count.purchase}</strong> 项采购</span><span><strong>{count.files}</strong> 份文件</span></span>
      </button>
      <footer className="tpl-card-foot">
        <span>{t.usage_count ? `已用于 ${t.usage_count} 个项目` : ''}</span>
        {canCreateProject && <Button type="link" size="small" onClick={() => navigate(`/pm/projects?create=1&template=${encodeURIComponent(t.id)}`)}>用它新建项目</Button>}
      </footer>
    </li>
  }

  return <div className="tpl-library-page">
    <WorkPageHeader title="项目模板" description="一个车型一个模板；新建项目选了车型就用它的模板，没有专用模板的车型用通用模板。改模板不影响已建的项目。"
      primary={canManage && <Button type="primary" icon={<PlusOutlined />} onClick={() => startDraft(missing[0])}>新建模板</Button>}
      tools={<RefreshAction label="刷新模板库" loading={loading} onClick={load} />} />
    {error && <Alert type="error" showIcon message={error} className="tpl-alert" action={<Button size="small" onClick={() => void load()}>重试</Button>} />}
    {loading && !templates.length ? <Skeleton active paragraph={{ rows: 6 }} />
      : !templates.length ? <Empty description="还没有模板" />
      : <ul className="tpl-card-grid" aria-label="模板库">{sorted.map(card)}</ul>}
    {canManage && !loading && missing.length > 0 && <p className="tpl-library-missing">还没有专用模板的车型：{missing.map(type => <Button key={type} size="small" type="link" onClick={() => startDraft(type)}>{type}</Button>)}</p>}
    <Modal title="新建模板" open={!!draft} onCancel={() => { if (!busy) setDraft(undefined) }} onOk={() => void create()} confirmLoading={busy} okText="创建并打开" cancelText="取消" okButtonProps={{ disabled: !draft?.name.trim() }}>
      <label className="tpl-field"><span>车型</span><Select aria-label="模板车型" allowClear placeholder="不选 = 通用模板" value={draft?.vehicleType} options={typeOptions}
        onChange={(vehicleType?: string) => setDraft(old => old && { ...old, vehicleType, name: old.named ? old.name : vehicleType ? `${vehicleType}模板` : '' })} /></label>
      <label className="tpl-field"><span>模板名称</span><Input aria-label="模板名称" value={draft?.name} maxLength={200} placeholder="例如：叉车模板" onChange={e => setDraft(old => old && { ...old, name: e.target.value, named: true })} onPressEnter={() => void create()} /></label>
      <label className="tpl-field"><span>以哪个模板为起点</span><Select aria-label="起点模板" value={draft?.from} onChange={from => setDraft(old => old && { ...old, from })} options={templates.map(t => ({ value: t.id, label: t.name }))} /></label>
    </Modal>
  </div>
}
