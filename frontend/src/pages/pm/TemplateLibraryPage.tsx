import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, Button, Empty, Input, Modal, Select, Skeleton, Tag, Tooltip } from 'antd'
import { FileTextOutlined, PlusOutlined, StarFilled } from '@ant-design/icons'
import { api, errMsg } from '../../api/client'
import { useAuth } from '../../stores/auth'
import { hasSystemPermission } from '../../constants/systemPermissions'
import { STAGES } from '../../constants/stages'
import { ensureVerifiedAccount } from '../../utils/verifiedAccount'
import { WorkPageHeader } from '../../components/WorkPage'
import { RefreshAction } from '../../components/IconAction'
import { templateStatus, type TemplateRow } from './templateMeta'
import './TemplateEditorPage.css'

const total = (counts?: Record<string, number>) => Object.values(counts ?? {}).reduce((a, b) => a + b, 0)

/** The template library: one card per template with its shape along stages 4–9; a card opens the template. */
export default function TemplateLibraryPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const canManage = hasSystemPermission(user, 'system.templates.manage')
  const canCreateProject = hasSystemPermission(user, 'projects.create')
  const [templates, setTemplates] = useState<TemplateRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [draft, setDraft] = useState<{ name: string; from: string }>()
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
    try { ensureVerifiedAccount(user?.id); const result = await api.post('/templates', { name: draft.name.trim(), copy_from: draft.from }); setDraft(undefined); navigate(`/pm/templates/${result.data.id}`) }
    catch (e) { setError(errMsg(e)) } finally { setBusy(false) }
  }

  const peak = Math.max(1, ...templates.flatMap(t => STAGES.map(s => (t.summary?.work[s.key] ?? 0) + (t.summary?.documents[s.key] ?? 0))))
  const card = (t: TemplateRow) => {
    const work = total(t.summary?.work); const docs = total(t.summary?.documents)
    return <li key={t.id} className="tpl-card">
      <button type="button" className="tpl-card-main" onClick={() => navigate(`/pm/templates/${t.id}`)} aria-label={`打开模板「${t.name}」`}>
        <span className="tpl-card-top">
          <span className="tpl-card-icon" aria-hidden="true">{t.is_system ? <StarFilled /> : <FileTextOutlined />}</span>
          <span className="tpl-card-name">{t.name}</span>
          <Tag color={t.is_system ? 'blue' : t.status === 'published' ? 'green' : undefined}>{templateStatus(t)}</Tag>
        </span>
        <span className="tpl-card-desc">{t.description || '没有说明'}</span>
        <span className="tpl-card-shape" aria-label={`各阶段：${STAGES.map(s => `${s.name} ${t.summary?.work[s.key] ?? 0} 项工作 ${t.summary?.documents[s.key] ?? 0} 份资料`).join('；')}`}>
          {STAGES.map(s => {
            const w = t.summary?.work[s.key] ?? 0; const d = t.summary?.documents[s.key] ?? 0
            return <Tooltip key={s.key} title={`${s.key} · ${s.name}：${w} 项工作 · ${d} 份资料`}>
              <span className="tpl-shape-col"><span className="tpl-shape-bar"><span style={{ height: `${Math.max(w + d ? 12 : 0, ((w + d) / peak) * 100)}%` }} /></span><span className="tpl-shape-key">{s.key}</span></span>
            </Tooltip>
          })}
        </span>
        <span className="tpl-card-stats"><span><strong>{work}</strong> 工作</span><span><strong>{docs}</strong> 资料</span><span><strong>{t.summary?.vehicle_steps ?? 0}</strong> 车辆环节</span></span>
      </button>
      <footer className="tpl-card-foot">
        <span>v{t.version || 1}{t.usage_count ? ` · 已用于 ${t.usage_count} 个项目` : ''}</span>
        {canCreateProject && <Button type="link" size="small" onClick={() => navigate(`/pm/projects?create=1&template=${encodeURIComponent(t.id)}`)}>用它新建项目</Button>}
      </footer>
    </li>
  }

  return <div className="tpl-library-page">
    <WorkPageHeader title="项目模板" description="新项目从模板带入工作、资料要求、车辆环节和采购物料。修改模板不影响已创建的项目。"
      primary={canManage && <Button type="primary" icon={<PlusOutlined />} onClick={() => setDraft({ name: '', from: 'default' })}>新建模板</Button>}
      tools={<RefreshAction label="刷新模板库" loading={loading} onClick={load} />} />
    {error && <Alert type="error" showIcon message={error} className="tpl-alert" action={<Button size="small" onClick={() => void load()}>重试</Button>} />}
    {loading && !templates.length ? <Skeleton active paragraph={{ rows: 6 }} />
      : !templates.length ? <Empty description="还没有模板" />
      : <ul className="tpl-card-grid" aria-label="模板库">{templates.map(card)}</ul>}
    <Modal title="新建模板" open={!!draft} onCancel={() => { if (!busy) setDraft(undefined) }} onOk={() => void create()} confirmLoading={busy} okText="创建并打开" cancelText="取消" okButtonProps={{ disabled: !draft?.name.trim() }}>
      <label className="tpl-field"><span>模板名称</span><Input aria-label="模板名称" value={draft?.name} maxLength={200} placeholder="例如：叉车重载项目模板" onChange={e => setDraft(old => old && { ...old, name: e.target.value })} onPressEnter={() => void create()} /></label>
      <label className="tpl-field"><span>以哪个模板为起点</span><Select aria-label="起点模板" value={draft?.from} onChange={from => setDraft(old => old && { ...old, from })} options={templates.map(t => ({ value: t.id, label: t.name }))} /></label>
    </Modal>
  </div>
}
