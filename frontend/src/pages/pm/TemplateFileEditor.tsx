import { Button, Input, InputNumber, Popconfirm, Select, Switch, Upload } from 'antd'
import { DeleteOutlined, DisconnectOutlined, DownloadOutlined, DownOutlined, RightOutlined, UploadOutlined } from '@ant-design/icons'
import type { TemplateFile } from '../../api/templateItems'

export const TIMINGS: Record<string, string> = { on_demand: '需要时交（无固定截止）', weekly: '每周交', before_event: '某个事件之前', after_event: '某个事件之后', after_milestone: '某个节点完成后', on_trigger: '发生某种情况后', lifetime: '整个项目期间更新，归档前交' }
export const EVENTS: Record<string, string> = { internal_kickoff: '内部启动会', ship: '发车', arrival_all: '全部到场', vehicle_arrival: '该车到场', delivery_signed: '到货签收', commissioning_done: '调试完工', go_live: '上线运行', training_done: '培训完成', acceptance: '项目验收', handover: '交付售后' }
const MILESTONES = ['delivery_signed', 'commissioning_done', 'go_live', 'training_done', 'acceptance', 'handover']
export const TRIGGERS: Record<string, string> = { accident: '事故', quality: '质量问题', member_leave: '人员离开项目' }
const WEEKDAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
const PLATFORMS = [{ value: 'NDC', label: 'NDC' }, { value: 'GRACE', label: 'GRACE' }, { value: 'integrated', label: '集成' }]
const RULE_EMPTY = { timing_event: null, timing_offset_hours: null, timing_weekday: null, trigger_type: null }
const days = (hours: number | null | undefined) => hours == null ? null : Math.round(hours / 24 * 100) / 100
const offsetText = (hours: number | null | undefined) => !hours ? '' : hours % 24 === 0 ? ` ${hours / 24} 天` : ` ${hours} 小时`

/** When a file is due, in a few words. */
export function timingLabel(file: Pick<TemplateFile, 'timing_type' | 'timing_event' | 'timing_offset_hours' | 'timing_weekday' | 'trigger_type'>) {
  if (file.timing_type === 'weekly') return `每${WEEKDAYS[(file.timing_weekday ?? 1) - 1]}`
  if (file.timing_type === 'on_demand') return '需要时交'
  if (file.timing_type === 'lifetime') return '项目期间更新'
  const event = file.timing_type === 'on_trigger' ? TRIGGERS[file.trigger_type ?? ''] ?? '' : EVENTS[file.timing_event ?? ''] ?? ''
  if (!file.timing_offset_hours) return `${event}时`
  return `${event}${file.timing_type === 'before_event' ? '前' : '后'}${offsetText(file.timing_offset_hours)}`
}

/** A file's rule is complete enough to save. */
export function fileProblem(file: TemplateFile): string {
  if (!file.name.trim()) return '文件名称不能为空'
  if (['before_event', 'after_event', 'after_milestone'].includes(file.timing_type) && (!file.timing_event || file.timing_offset_hours == null)) return `「${file.name}」请选择事件并填写天数`
  if (file.timing_type === 'weekly' && !file.timing_weekday) return `「${file.name}」请选择每周几交`
  if (file.timing_type === 'on_trigger' && (!file.trigger_type || file.timing_offset_hours == null)) return `「${file.name}」请选择发生什么情况`
  return ''
}

type Props = {
  file: TemplateFile; open: boolean; editable: boolean; saved: boolean
  onToggle: () => void; onChange: (file: TemplateFile) => void; onRemove: () => void
  onUpload: (file: File) => void; onDownload: () => void; onClearBlank: () => void
}

/** One file a row hands in: a one-line summary that opens into its full rule. */
export default function TemplateFileEditor({ file, open, editable, saved, onToggle, onChange, onRemove, onUpload, onDownload, onClearBlank }: Props) {
  const set = (patch: Partial<TemplateFile>) => onChange({ ...file, ...patch })
  const kind = file.timing_type
  const eventOptions = Object.entries(EVENTS).filter(([key]) => kind === 'after_milestone' ? MILESTONES.includes(key) : key !== 'vehicle_arrival' || (kind === 'after_event' && file.scope === 'vehicle')).map(([value, label]) => ({ value, label }))
  const changeTiming = (value: string) => set({ ...RULE_EMPTY, timing_type: value, ...(value === 'lifetime' ? { timing_event: 'internal_kickoff' } : ['before_event', 'after_event', 'after_milestone', 'on_trigger'].includes(value) ? { timing_offset_hours: 0 } : {}) })
  const summary = [file.scope === 'vehicle' ? '每台车一份' : '', timingLabel(file), file.required ? '' : '可不交', file.confidential_default ? '保密' : ''].filter(Boolean).join(' · ')
  return <li className={`tpl-file${open ? ' is-open' : ''}`}>
    <button type="button" className="tpl-file-head" aria-expanded={open} onClick={onToggle}>
      {open ? <DownOutlined /> : <RightOutlined />}
      <span className="tpl-code">{file.code || '自动编号'}</span>
      <span className="tpl-file-name">{file.name || '未命名文件'}</span>
      <span className="tpl-file-meta">{summary}</span>
    </button>
    {open && <div className="tpl-file-body">
      <div className="tpl-form-pair">
        <label className="tpl-field"><span>编号</span><Input aria-label="文件编号" value={file.code} maxLength={40} placeholder="不填自动编号" disabled={!editable} onChange={e => set({ code: e.target.value })} /></label>
        <label className="tpl-field tpl-field-wide"><span>文件名称</span><Input aria-label="文件名称" value={file.name} maxLength={300} disabled={!editable} onChange={e => set({ name: e.target.value })} /></label>
      </div>
      <div className="tpl-switches">
        <label><Switch size="small" checked={file.required} disabled={!editable} onChange={required => set({ required })} />必须交</label>
        <label><Switch size="small" checked={file.scope === 'vehicle'} disabled={!editable} onChange={vehicle => set({ scope: vehicle ? 'vehicle' : 'project', ...(!vehicle && file.timing_event === 'vehicle_arrival' ? { timing_event: null } : {}) })} />每台车一份</label>
      </div>
      <label className="tpl-field"><span>什么时候交</span><Select aria-label="什么时候交" value={kind} disabled={!editable} onChange={changeTiming} options={Object.entries(TIMINGS).map(([value, label]) => ({ value, label }))} /></label>
      {['before_event', 'after_event', 'after_milestone', 'on_trigger'].includes(kind) && <div className="tpl-form-pair">
        {kind === 'on_trigger'
          ? <label className="tpl-field"><span>发生什么</span><Select aria-label="发生什么" value={file.trigger_type ?? undefined} disabled={!editable} onChange={trigger_type => set({ trigger_type })} options={Object.entries(TRIGGERS).map(([value, label]) => ({ value, label }))} /></label>
          : <label className="tpl-field"><span>{kind === 'after_milestone' ? '哪个节点' : '哪个事件'}</span><Select aria-label="哪个事件" value={file.timing_event ?? undefined} disabled={!editable} onChange={timing_event => set({ timing_event })} options={eventOptions} /></label>}
        <label className="tpl-field"><span>{kind === 'before_event' ? '提前' : '之后'}</span>
          <InputNumber aria-label="相隔天数" min={0} max={36500} addonAfter="天" disabled={!editable} value={days(file.timing_offset_hours)}
            onChange={value => set({ timing_offset_hours: value == null ? null : Math.round(Number(value) * 24) })} /></label>
      </div>}
      {kind === 'weekly' && <label className="tpl-field"><span>每周几交</span><Select aria-label="每周几交" value={file.timing_weekday ?? undefined} disabled={!editable} onChange={timing_weekday => set({ timing_weekday })} options={WEEKDAYS.map((label, index) => ({ value: index + 1, label }))} /></label>}
      <details className="tpl-more">
        <summary>更多：平台、保密、外部查看</summary>
        <label className="tpl-field"><span>只用于某个调度平台</span><Select aria-label="只用于平台" allowClear placeholder="所有平台都用" value={file.platform ?? undefined} disabled={!editable} onChange={platform => set({ platform: platform ?? null })} options={PLATFORMS} /></label>
        <div className="tpl-switches">
          <label><Switch size="small" checked={file.confidential_default} disabled={!editable} onChange={value => set({ confidential_default: value, ...(value ? { external_visible_default: false } : {}) })} />默认保密</label>
          <label><Switch size="small" checked={file.external_never_visible} disabled={!editable} onChange={value => set({ external_never_visible: value, ...(value ? { external_visible_default: false } : {}) })} />禁止外部查看</label>
          <label><Switch size="small" checked={file.external_visible_default} disabled={!editable || file.confidential_default || file.external_never_visible} onChange={external_visible_default => set({ external_visible_default })} />默认对外可见</label>
        </div>
        <label className="tpl-field"><span>模板编号</span><Input aria-label="模板编号" value={file.template_no} maxLength={100} placeholder="可选，如模板16" disabled={!editable} onChange={e => set({ template_no: e.target.value })} /></label>
        <label className="tpl-field"><span>给提交人的说明</span><Input.TextArea aria-label="文件说明" value={file.note} maxLength={5000} autoSize={{ minRows: 1, maxRows: 6 }} disabled={!editable} onChange={e => set({ note: e.target.value })} /></label>
      </details>
      <div className="tpl-blank">
        <span className="tpl-blank-label">空白模板</span>
        {file.blank_file ? <Button type="link" size="small" icon={<DownloadOutlined />} onClick={onDownload}>{file.blank_file.filename}</Button> : <span className="tpl-blank-none">{saved ? '尚未上传' : '保存后可上传'}</span>}
        {editable && saved && <Upload showUploadList={false} beforeUpload={blank => { onUpload(blank); return false }}>
          <Button size="small" icon={<UploadOutlined />}>{file.blank_file ? '替换' : '上传'}</Button>
        </Upload>}
        {editable && file.blank_file && <Popconfirm title="移除空白模板引用？已建项目里的文件不受影响。" okText="移除" cancelText="取消" onConfirm={onClearBlank}>
          <Button size="small" type="text" danger icon={<DisconnectOutlined />}>移除</Button>
        </Popconfirm>}
        {editable && <Popconfirm title={`删除文件「${file.name}」？`} okText="删除" okButtonProps={{ danger: true }} cancelText="取消" onConfirm={onRemove}>
          <Button size="small" type="text" danger icon={<DeleteOutlined />} className="tpl-file-remove">删除文件</Button>
        </Popconfirm>}
      </div>
    </div>}
  </li>
}
