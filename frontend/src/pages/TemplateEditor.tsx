import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Button, Result, Skeleton, message } from 'antd'
import { DownloadOutlined, LeftOutlined, UploadOutlined } from '@ant-design/icons'
import { api, errMsg } from '../api/client'
import type { Template, TemplateKind, TemplateRow, TemplateSnapshot } from '../api/types'
import Grid, { TextCell, type Column } from '../components/Grid'
import ImportModal from '../components/ImportModal'
import { useAuth } from '../stores/auth'
import { listOps } from '../sync/rows'
import { useLive } from '../sync/useLive'
import { download } from '../utils/format'
import './project/project.css'
import './Templates.css'

const SECTIONS: { kind: TemplateKind; title: string; hint: string; add: string; columns: Column<TemplateRow>[] }[] = [
  { kind: 'step', title: '车辆环节', hint: '车辆表里的每一列。每台车都要逐个打勾。', add: '输入环节名称后回车，例如：到货、调试、交付',
    columns: [{ key: 'name', title: '环节', label: '环节', primary: true, required: true }] },
  { kind: 'work', title: '工作', hint: '项目里要做的事，按阶段分组。', add: '输入工作内容后回车',
    columns: [{ key: 'stage', title: '阶段', label: '阶段', width: '26%' }, { key: 'name', title: '工作内容', label: '工作内容', primary: true, required: true, multiline: true }] },
  { kind: 'document', title: '资料', hint: '项目要交的资料清单。', add: '输入资料名称后回车',
    columns: [{ key: 'name', title: '资料名称', label: '资料名称', primary: true, required: true }] },
  { kind: 'item', title: '物品', hint: '要带到现场或采购的物品。', add: '输入物品名称后回车',
    columns: [{ key: 'name', title: '名称', label: '名称', primary: true, required: true, width: '30%' }, { key: 'spec', title: '规格', label: '规格' },
      { key: 'quantity', title: '数量', label: '数量', type: 'number' }, { key: 'unit', title: '单位', label: '单位', width: 80 }] },
]

export default function TemplateEditor() {
  const { id = '' } = useParams()
  const base = `/templates/${id}`
  const live = useLive<TemplateSnapshot>(base)
  const navigate = useNavigate()
  const { user } = useAuth()
  const [importing, setImporting] = useState(false)
  const ops = listOps<TemplateSnapshot, TemplateRow>(live, base, 'rows', 'rows', { stage: '阶段', name: '名称', spec: '规格', quantity: '数量', unit: '单位' }, {}, user?.id ?? '')
  const byKind = useMemo(() => {
    const map = new Map<TemplateKind, TemplateRow[]>()
    for (const row of live.data?.rows ?? []) map.set(row.kind, [...(map.get(row.kind) ?? []), row])
    return map
  }, [live.data])
  if (!live.data) {
    return live.error ? <Result status="warning" title="打不开这个模板" subTitle={live.error} extra={<Button type="primary" onClick={() => navigate('/templates')}>回到模板</Button>} /> : <Skeleton active paragraph={{ rows: 8 }} />
  }
  const template = live.data.template
  const setField = async (field: keyof Template & string, to: string) => {
    const from = template[field]
    live.mutate((data) => ({ ...data, template: { ...data.template, [field]: to } }))
    try { await live.track(api.patch(base, { [field]: { from, to } })) } catch (failure) {
      live.mutate((data) => ({ ...data, template: { ...data.template, [field]: from } }))
      message.error(errMsg(failure))
    }
  }
  return <div className="template-editor">
    <header className="project-head">
      <Link to="/templates" className="project-back"><LeftOutlined /> 全部模板</Link>
      <div className="project-title-row">
        <h1 className="project-title"><TextCell value={template.name} label="模板名称" required strong onCommit={(next) => setField('name', next)} /></h1>
        <div className="project-actions">
          <Button icon={<UploadOutlined />} onClick={() => setImporting(true)}>从 Excel 导入</Button>
          <Button icon={<DownloadOutlined />} onClick={() => download(`${base}/export.xlsx`)}>导出 Excel</Button>
        </div>
      </div>
      <div className="project-meta"><label className="is-wide"><span>说明</span><TextCell value={template.note} label="模板说明" placeholder="未填" onCommit={(next) => setField('note', next)} /></label></div>
    </header>
    {SECTIONS.map((section) => {
      const rows = byKind.get(section.kind) ?? []
      const stages = section.kind === 'work' ? [...new Set(rows.map((row) => row.stage).filter(Boolean))] : []
      const columns = section.kind === 'work' ? section.columns.map((column) => (column.key === 'stage' ? { ...column, options: stages } : column)) : section.columns
      return <section key={section.kind} className="template-section" aria-label={section.title}>
        <header className="section-head"><h2>{section.title}</h2><p>{section.hint}</p></header>
        <Grid label={`模板的${section.title}`} rows={rows} columns={columns} empty="还没有内容"
          onSet={(row, key, value) => ops.set(row, key as keyof TemplateRow & string, value)}
          onAdd={(text) => ops.add({ kind: section.kind, name: text, stage: section.kind === 'work' ? rows[rows.length - 1]?.stage ?? '' : '', spec: '', quantity: null, unit: '' })}
          addPlaceholder={section.add} onDelete={(row) => void ops.remove(row)} onMove={(row, offset) => void ops.move(rows, row, offset)} onReorder={(ids) => void ops.reorder(ids)} />
      </section>
    })}
    <ImportModal open={importing} title="从 Excel 导入模板内容" url={`${base}/import`} hint="请使用本页“导出 Excel”得到的文件格式：工作、资料、车辆环节、物品四张表。已有的内容不会重复添加。"
      onClose={() => setImporting(false)} onDone={live.refresh} />
  </div>
}
