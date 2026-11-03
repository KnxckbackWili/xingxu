import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, Button, Empty, Input, Modal, Select, Skeleton, Tag, message } from 'antd'
import { FileTextOutlined, PlusOutlined, StarFilled } from '@ant-design/icons'
import { api, errMsg } from '../../api/client'
import { useAuth } from '../../stores/auth'
import { hasSystemPermission } from '../../constants/systemPermissions'
import { ensureVerifiedAccount } from '../../utils/verifiedAccount'
import { WorkPageHeader } from '../../components/WorkPage'
import { RefreshAction } from '../../components/IconAction'
import type { TemplateRow } from './templateMeta'
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

  // One standard template is enough: vehicle types and optional modules are chosen per project.
  const others = templates.filter(t => !t.is_system)
  const mergeAll = () => Modal.confirm({
    title: `把 ${others.length} 个模板并入标准模板？`,
    content: <><p>只补充标准模板里还没有的工作、资料要求、车辆环节和采购物料，已有内容不变；之后删除这些模板。已建的项目不受影响。</p><ul>{others.map(t => <li key={t.id}>{t.name}</li>)}</ul></>,
    okText: '全部并入', cancelText: '取消',
    onOk: async () => {
      setBusy(true)
      try {
        ensureVerifiedAccount(user?.id)
        let work = 0, documents = 0
        for (const t of others) { const result = await api.post(`/templates/${t.id}/merge`); work += result.data.added.work_items; documents += result.data.added.documents }
        message.success(`已合并，标准模板新增 ${work} 项工作、${documents} 份资料要求`)
      } catch (e) { setError(errMsg(e)) } finally { setBusy(false); void load() }
    },
  })

  const card = (t: TemplateRow) => {
    const work = total(t.summary?.work); const docs = total(t.summary?.documents)
    return <li key={t.id} className="tpl-card">
      <button type="button" className="tpl-card-main" onClick={() => navigate(`/pm/templates/${t.id}`)} aria-label={`打开模板「${t.name}」`}>
        <span className="tpl-card-top">
          <span className="tpl-card-icon" aria-hidden="true">{t.is_system ? <StarFilled /> : <FileTextOutlined />}</span>
          <span className="tpl-card-name">{t.name}</span>
          {t.is_system && <Tag color="blue">默认</Tag>}
        </span>
        <span className="tpl-card-desc">{t.description || '没有说明'}</span>
        <span className="tpl-card-stats"><span><strong>{work}</strong> 项工作</span><span><strong>{docs}</strong> 份资料</span><span><strong>{t.summary?.vehicle_steps ?? 0}</strong> 个车辆环节</span></span>
      </button>
      <footer className="tpl-card-foot">
        <span>{t.usage_count ? `已用于 ${t.usage_count} 个项目` : ''}</span>
        {canCreateProject && <Button type="link" size="small" onClick={() => navigate(`/pm/projects?create=1&template=${encodeURIComponent(t.id)}`)}>用它新建项目</Button>}
      </footer>
    </li>
  }

  return <div className="tpl-library-page">
    <WorkPageHeader title="项目模板" description="新建项目时从模板带入工作、资料、车辆环节和采购物料。改模板不影响已建的项目。"
      primary={canManage && <Button type="primary" icon={<PlusOutlined />} onClick={() => setDraft({ name: '', from: 'default' })}>新建模板</Button>}
      tools={<RefreshAction label="刷新模板库" loading={loading} onClick={load} />} />
    {error && <Alert type="error" showIcon message={error} className="tpl-alert" action={<Button size="small" onClick={() => void load()}>重试</Button>} />}
    {canManage && others.length > 0 && <Alert type="info" showIcon className="tpl-alert" message="一个标准模板就够用"
      description="车型和可选模块（电梯、自动门、PLC 等）在新建项目时勾选，不必为每种车维护一份模板。"
      action={<Button loading={busy} onClick={mergeAll}>全部并入标准模板</Button>} />}
    {loading && !templates.length ? <Skeleton active paragraph={{ rows: 6 }} />
      : !templates.length ? <Empty description="还没有模板" />
      : <ul className="tpl-card-grid" aria-label="模板库">{templates.map(card)}</ul>}
    <Modal title="新建模板" open={!!draft} onCancel={() => { if (!busy) setDraft(undefined) }} onOk={() => void create()} confirmLoading={busy} okText="创建并打开" cancelText="取消" okButtonProps={{ disabled: !draft?.name.trim() }}>
      <label className="tpl-field"><span>模板名称</span><Input aria-label="模板名称" value={draft?.name} maxLength={200} placeholder="例如：叉车重载项目模板" onChange={e => setDraft(old => old && { ...old, name: e.target.value })} onPressEnter={() => void create()} /></label>
      <label className="tpl-field"><span>以哪个模板为起点</span><Select aria-label="起点模板" value={draft?.from} onChange={from => setDraft(old => old && { ...old, from })} options={templates.map(t => ({ value: t.id, label: t.name }))} /></label>
    </Modal>
  </div>
}
