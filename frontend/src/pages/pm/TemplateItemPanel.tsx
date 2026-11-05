import { useEffect, useRef, useState, type MutableRefObject } from 'react'
import { Button, Checkbox, DatePicker, Input, InputNumber, Popconfirm, Segmented, Select, Switch, Upload, message } from 'antd'
import { ArrowUpOutlined, CloseOutlined, DeleteOutlined, PaperClipOutlined, PlusOutlined, SafetyOutlined, UploadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { api, errMsg } from '../../api/client'
import { itemBody, KIND_NAMES, newFile, templateItemsApi, type ItemKind, type TemplateFieldDef, type TemplateItem, type TemplateSection, type TemplateTree } from '../../api/templateItems'
import TemplateFileEditor, { fileProblem } from './TemplateFileEditor'
import { IconAction } from '../../components/IconAction'

export type SaveState = { state: 'saving' | 'saved' | 'error'; error?: string }
export function SaveBadge({ save }: { save?: SaveState }) {
  if (!save) return null
  return <span className={`tpl-save is-${save.state}`} role={save.state === 'error' ? 'alert' : 'status'}>
    {save.state === 'saving' ? '保存中…' : save.state === 'error' ? save.error || '保存失败' : '已保存'}
  </span>
}

type Props = {
  templateId: string; item: TemplateItem; sections: TemplateSection[]; fields: TemplateFieldDef[]; editable: boolean
  flushRef: MutableRefObject<(() => Promise<void>) | null>
  onTree: (tree: TemplateTree) => void; onClose: () => void; onReload: () => Promise<unknown> | void
}

const detail = (error: any) => { const text = error?.response?.data?.detail; return typeof text === 'string' ? text : Array.isArray(text) ? text.map((row: any) => String(row?.msg ?? '').replace(/^Value error, /, '')).join('；') : errMsg(error) }

/**
 * Everything about one row of a template, edited in place. Typing saves itself shortly after you stop; switches save at once.
 * The parent awaits `flushRef` before switching rows so nothing typed is lost.
 */
export default function TemplateItemPanel({ templateId, item, sections, fields, editable, flushRef, onTree, onClose, onReload }: Props) {
  const [draft, setDraft] = useState(item)
  const [save, setSave] = useState<SaveState>()
  const [openFile, setOpenFile] = useState<number | null>(item.files.length === 1 && item.kind === 'file' ? 0 : null)
  const [newCheck, setNewCheck] = useState('')
  const version = useRef(item.version)
  const latest = useRef(draft)
  const timer = useRef<ReturnType<typeof setTimeout>>()
  const queue = useRef<Promise<unknown>>(Promise.resolve())
  const lastSent = useRef(JSON.stringify(itemBody(item)))
  latest.current = draft

  // A save of this row elsewhere (blank form, reload) brings a new version; keep typing, adopt the version and server-side ids.
  useEffect(() => {
    version.current = item.version
    setDraft(old => ({ ...old, files: old.files.map((file, index) => ({ ...file, id: file.id ?? item.files[index]?.id, code: file.code || item.files[index]?.code || '', blank_file: item.files.find(row => row.id === file.id)?.blank_file ?? (file.id ? null : file.blank_file) })), checks: old.checks.map((check, index) => ({ ...check, id: check.id ?? item.checks[index]?.id })), reference_docs: item.reference_docs }))
  }, [item])

  const persist = async () => {
    const current = latest.current
    const body = itemBody({ ...current, version: version.current })
    const problem = !current.name.trim() ? '名称不能为空' : current.files.map(fileProblem).find(Boolean) || (current.kind === 'file' && !current.files.length ? '资料至少要有一份文件' : '') || (current.checks.some(check => !check.name.trim()) ? '检查要点不能为空' : '')
    if (problem) { setSave({ state: 'error', error: problem }); return }
    const text = JSON.stringify({ ...body, version: undefined })
    if (text === lastSent.current) return
    lastSent.current = text
    queue.current = queue.current.then(async () => {
      setSave({ state: 'saving' })
      try {
        const tree = await templateItemsApi.updateItem(templateId, item.id, { ...body, version: version.current })
        const saved = tree.sections.flatMap(section => section.items).find(row => row.id === item.id)
        if (saved) version.current = saved.version
        setSave({ state: 'saved' })
        onTree(tree)
      } catch (error) {
        lastSent.current = ''
        setSave({ state: 'error', error: detail(error) })
      }
    })
    await queue.current
  }
  const schedule = (delay = 600) => { clearTimeout(timer.current); timer.current = setTimeout(() => { timer.current = undefined; void persist() }, delay) }
  const flush = async () => { if (timer.current) { clearTimeout(timer.current); timer.current = undefined; await persist() } else await queue.current }
  useEffect(() => { flushRef.current = flush; return () => { if (flushRef.current === flush) flushRef.current = null } })
  useEffect(() => () => { if (timer.current) { clearTimeout(timer.current); void persist() } }, [])

  const change = (patch: Partial<TemplateItem>, delay = 600) => { if (!editable) return; setDraft(old => { const next = { ...old, ...patch }; latest.current = next; return next }); schedule(delay) }
  const setKind = (kind: ItemKind) => change({ kind, per_vehicle: kind === 'work' ? draft.per_vehicle : false, checks: kind === 'work' ? draft.checks : [], files: kind === 'file' && !draft.files.length ? [newFile(draft.name)] : draft.files }, 0)
  const moveCheck = (index: number, to: number) => { const checks = [...draft.checks]; const [row] = checks.splice(index, 1); checks.splice(to, 0, row); change({ checks }, 0) }
  const addCheck = () => { const name = newCheck.trim(); if (!name) return; change({ checks: [...draft.checks, { name, required: true, safety: false }] }, 0); setNewCheck('') }
  const run = async (operation: () => Promise<TemplateTree>, success: string) => {
    try { await flush(); const tree = await operation(); onTree(tree); message.success(success) } catch (error) { message.error(detail(error)) }
  }
  const download = async (fileId: string, filename: string) => {
    try { const blob = await templateItemsApi.downloadBlank(templateId, item.id, fileId); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = filename; a.click(); URL.revokeObjectURL(url) }
    catch (error) { message.error(detail(error)) }
  }
  const uploadReference = async (file: File) => {
    const data = new FormData(); data.append('file', file)
    try { await api.post(`/templates/${encodeURIComponent(templateId)}/tasks/${item.id}/reference-docs`, data); message.success('参考文件已上传'); await onReload() } catch (error) { message.error(detail(error)) }
  }
  const removeReference = async (refId: string) => {
    try { await api.delete(`/templates/${encodeURIComponent(templateId)}/tasks/${item.id}/reference-docs/${refId}`); message.success('参考文件已删除'); await onReload() } catch (error) { message.error(detail(error)) }
  }
  const downloadReference = async (refId: string, filename: string) => {
    try { const result = await api.get(`/templates/${encodeURIComponent(templateId)}/tasks/${item.id}/reference-docs/${refId}/download`, { responseType: 'blob' }); const url = URL.createObjectURL(result.data); const a = document.createElement('a'); a.href = url; a.download = filename; a.click(); URL.revokeObjectURL(url) }
    catch (error) { message.error(detail(error)) }
  }
  const remove = async () => {
    clearTimeout(timer.current); timer.current = undefined
    try { const tree = await templateItemsApi.removeItem(templateId, item.id); onTree(tree); message.success(`已删除「${item.name}」`); onClose() } catch (error) { message.error(detail(error)) }
  }

  const fieldInput = (field: TemplateFieldDef) => {
    const value = draft.fields[field.id]
    const set = (next: string | number | null | undefined) => {
      const values = { ...draft.fields }
      if (next === null || next === undefined || next === '') delete values[field.id]; else values[field.id] = next
      change({ fields: values }, field.field_type === 'text' || field.field_type === 'number' ? 600 : 0)
    }
    if (field.field_type === 'number') return <InputNumber aria-label={field.name} value={typeof value === 'number' ? value : value ? Number(value) : null} disabled={!editable} onChange={next => set(next as number | null)} style={{ width: '100%' }} />
    if (field.field_type === 'date') return <DatePicker aria-label={field.name} value={value ? dayjs(String(value)) : null} disabled={!editable} onChange={next => set(next ? next.format('YYYY-MM-DD') : null)} style={{ width: '100%' }} />
    if (field.field_type === 'select') return <Select aria-label={field.name} allowClear value={value as string | undefined} disabled={!editable} onChange={next => set(next)} options={field.options.map(option => ({ value: option, label: option }))} />
    return <Input aria-label={field.name} value={value === undefined ? '' : String(value)} maxLength={2000} disabled={!editable} onChange={e => set(e.target.value)} />
  }

  const section = sections.find(row => row.id === draft.section_id)
  return <aside className="tpl-panel" aria-label={`编辑：${item.name}`}>
    <header className="tpl-panel-head">
      <Segmented size="small" aria-label="类型" value={draft.kind} disabled={!editable} onChange={value => setKind(value as ItemKind)}
        options={(['work', 'file', 'purchase'] as ItemKind[]).map(kind => ({ value: kind, label: KIND_NAMES[kind] }))} />
      <SaveBadge save={save} />
      <IconAction label="关闭" icon={<CloseOutlined />} onClick={() => void flush().then(onClose)} />
    </header>
    <div className="tpl-panel-body">
      <label className="tpl-field"><span>名称</span><Input aria-label="名称" value={draft.name} maxLength={200} disabled={!editable} onChange={e => change({ name: e.target.value })} /></label>
      <div className="tpl-switches">
        {draft.kind === 'work' && <label title="在车辆进度表里每台车各记一次"><Switch size="small" checked={draft.per_vehicle} disabled={!editable} onChange={per_vehicle => change({ per_vehicle }, 0)} />每台车各做一次</label>}
        <label title="新建项目时列出来让你勾选，不勾就不带入"><Switch size="small" checked={draft.optional} disabled={!editable} onChange={optional => change({ optional }, 0)} />可选（新建项目时勾选才带入）</label>
      </div>
      {draft.kind === 'purchase' && <div className="tpl-form-pair">
        <label className="tpl-field"><span>数量</span><InputNumber aria-label="数量" min={0} value={draft.quantity} placeholder="项目里再定" disabled={!editable} onChange={quantity => change({ quantity: quantity as number | null })} style={{ width: '100%' }} /></label>
        <label className="tpl-field"><span>单位</span><Input aria-label="单位" value={draft.unit} maxLength={20} placeholder="台 / 套 / 米" disabled={!editable} onChange={e => change({ unit: e.target.value })} /></label>
        <label className="tpl-field tpl-field-wide"><span>规格 / 型号</span><Input aria-label="规格" value={draft.spec} maxLength={300} disabled={!editable} onChange={e => change({ spec: e.target.value })} /></label>
      </div>}

      {draft.kind === 'work' && <section className="tpl-panel-block" aria-label="检查要点">
        <h4>检查要点<span>{draft.checks.length}</span></h4>
        <ol className="tpl-checks">
          {draft.checks.map((check, index) => <li key={check.id ?? `new-${index}`}>
            <Input aria-label={`检查要点 ${index + 1}`} variant="borderless" value={check.name} maxLength={300} disabled={!editable}
              onChange={e => change({ checks: draft.checks.map((row, i) => i === index ? { ...row, name: e.target.value } : row) })} />
            <Checkbox checked={check.safety} disabled={!editable} onChange={e => change({ checks: draft.checks.map((row, i) => i === index ? { ...row, safety: e.target.checked } : row) }, 0)}><SafetyOutlined /> 安全</Checkbox>
            <Checkbox checked={!check.required} disabled={!editable} onChange={e => change({ checks: draft.checks.map((row, i) => i === index ? { ...row, required: !e.target.checked } : row) }, 0)}>选做</Checkbox>
            {editable && <span className="tpl-check-actions">
              <IconAction size="small" label="上移" icon={<ArrowUpOutlined />} disabled={index === 0} onClick={() => moveCheck(index, index - 1)} />
              <IconAction size="small" label={`删除检查要点 ${index + 1}`} icon={<DeleteOutlined />} onClick={() => change({ checks: draft.checks.filter((_, i) => i !== index) }, 0)} />
            </span>}
          </li>)}
        </ol>
        {editable && <Input aria-label="加一条检查要点" placeholder="加一条检查要点，回车添加" value={newCheck} maxLength={300} onChange={e => setNewCheck(e.target.value)} onPressEnter={addCheck}
          suffix={<Button type="link" size="small" disabled={!newCheck.trim()} onClick={addCheck}>添加</Button>} />}
      </section>}

      <section className="tpl-panel-block" aria-label="要交的文件">
        <h4>要交的文件<span>{draft.files.length}</span>{section && <em>属于「{section.stage_name}」阶段</em>}</h4>
        <ul className="tpl-files">
          {draft.files.map((file, index) => <TemplateFileEditor key={file.id ?? `new-${index}`} file={file} open={openFile === index} editable={editable} saved={!!file.id}
            onToggle={() => setOpenFile(openFile === index ? null : index)}
            onChange={next => change({ files: draft.files.map((row, i) => i === index ? next : row) })}
            onRemove={() => { change({ files: draft.files.filter((_, i) => i !== index) }, 0); setOpenFile(null) }}
            onUpload={blank => file.id && void run(() => templateItemsApi.uploadBlank(templateId, item.id, file.id!, blank), '空白模板已上传')}
            onDownload={() => file.id && file.blank_file && void download(file.id, file.blank_file.filename)}
            onClearBlank={() => file.id && void run(() => templateItemsApi.removeBlank(templateId, item.id, file.id!), '已移除空白模板引用')} />)}
        </ul>
        {!draft.files.length && <p className="tpl-empty-note">{draft.kind === 'file' ? '资料至少要有一份文件' : '这件事不需要交文件'}</p>}
        {editable && <Button size="small" icon={<PlusOutlined />} onClick={() => { change({ files: [...draft.files, newFile()] }, 99999); setOpenFile(draft.files.length) }}>加一份文件</Button>}
      </section>

      {fields.length > 0 && <section className="tpl-panel-block" aria-label="自定义字段">
        <h4>自定义字段</h4>
        <div className="tpl-custom-fields">{fields.map(field => <label key={field.id} className="tpl-field"><span>{field.name}</span>{fieldInput(field)}</label>)}</div>
      </section>}

      <label className="tpl-field"><span>说明</span><Input.TextArea aria-label="说明" value={draft.note} maxLength={5000} autoSize={{ minRows: 2, maxRows: 8 }} placeholder="可选：做法、注意事项" disabled={!editable} onChange={e => change({ note: e.target.value })} /></label>

      {draft.kind === 'work' && <section className="tpl-panel-block" aria-label="参考文件">
        <h4>参考文件<span>{draft.reference_docs.length}</span></h4>
        <ul className="tpl-refs">
          {draft.reference_docs.map(ref => <li key={ref.id}>
            <Button type="link" size="small" icon={<PaperClipOutlined />} onClick={() => void downloadReference(ref.id, ref.filename)}>{ref.filename}</Button>
            {editable && <Popconfirm title={`删除参考文件「${ref.filename}」？`} okText="删除" okButtonProps={{ danger: true }} cancelText="取消" onConfirm={() => void removeReference(ref.id)}>
              <IconAction size="small" label={`删除参考文件 ${ref.filename}`} icon={<DeleteOutlined />} />
            </Popconfirm>}
          </li>)}
        </ul>
        {editable && <Upload showUploadList={false} beforeUpload={file => { void uploadReference(file); return false }}><Button size="small" icon={<UploadOutlined />}>上传参考文件</Button></Upload>}
      </section>}
    </div>
    {editable && <footer className="tpl-panel-foot">
      <Popconfirm title={`删除「${item.name}」？`} description="已建的项目不受影响。" okText="删除" okButtonProps={{ danger: true }} cancelText="取消" onConfirm={() => void remove()}>
        <Button danger type="text" icon={<DeleteOutlined />}>删除这件事</Button>
      </Popconfirm>
    </footer>}
  </aside>
}
