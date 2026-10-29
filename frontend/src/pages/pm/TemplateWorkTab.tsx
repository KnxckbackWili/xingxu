import { useState } from 'react'
import { Button, Drawer, Dropdown, Empty, Input, Modal, Tag, Typography, Upload, message } from 'antd'
import { CarOutlined, CheckCircleOutlined, DeleteOutlined, EditOutlined, MoreOutlined, PaperClipOutlined, PlusOutlined, RightOutlined, SearchOutlined, UploadOutlined } from '@ant-design/icons'
import { api } from '../../api/client'
import type { WorkItem, WorkPhase } from '../../api/workItems'
import { STAGES, STAGE_NAME, stageLabel } from '../../constants/stages'
import { downloadDocumentResource } from '../../api/projectDocuments'
import { IconAction } from '../../components/IconAction'
import WorkItemEditor from '../../components/WorkItemEditor'
import { StageOutline, StageSection, outlineStages } from './TemplateOutline'

type Step = { key: string; name: string }
type Props = {
  templateId: string; phases: WorkPhase[]; steps: Step[]; canManage: boolean; loading: boolean; busy: boolean
  mutate: (run: () => Promise<unknown>) => Promise<void>; onReload: () => Promise<void> | void; onCreateStep: (name: string) => Promise<string>
}
type GroupDialog = { mode: 'create' | 'rename'; stage: string; phase?: WorkPhase; name: string }

const SCOPES: Record<string, string> = { need_wms: 'WMS 对接', need_charging: '自动充电' }
export const stageOf = (phase: WorkPhase) => phase.stage_key ?? '6'

/** Template work: stage → work group → work item; a row opens the item's details, group actions sit in one menu. */
export default function TemplateWorkTab({ templateId, phases, steps, canManage, loading, busy, mutate, onReload, onCreateStep }: Props) {
  const [keyword, setKeyword] = useState('')
  const [group, setGroup] = useState<GroupDialog>()
  const [detailId, setDetailId] = useState<string>()
  const [editor, setEditor] = useState<{ item?: WorkItem; phaseId?: string }>()
  const term = keyword.trim().toLowerCase()
  const matches = (item: WorkItem) => !term || `${item.name} ${item.group_label ?? ''} ${item.description ?? ''}`.toLowerCase().includes(term)
  const stepName = (key?: string | null) => steps.find(s => s.key === key)?.name
  const all = phases.flatMap(phase => phase.work_items.map(item => ({ item, phase })))
  const detail = all.find(row => row.item.id === detailId)
  const counts: Record<string, number> = {}
  for (const { phase, item } of all) if (matches(item)) counts[stageOf(phase)] = (counts[stageOf(phase)] ?? 0) + 1

  const saveGroup = async () => {
    if (!group?.name.trim()) return
    const name = group.name.trim(); const current = group
    await mutate(async () => {
      if (current.mode === 'create') await api.post(`/templates/${templateId}/work-phases`, { name, stage_key: current.stage })
      else await api.put(`/templates/${templateId}/work-phases/${current.phase!.id}`, { name })
      setGroup(undefined)
    })
  }
  const groupMenu = (phase: WorkPhase) => ({
    items: [
      { key: 'add', icon: <PlusOutlined />, label: '添加工作项' },
      { key: 'rename', icon: <EditOutlined />, label: '重命名' },
      { key: 'move', label: '移到其他阶段', children: STAGES.filter(s => s.key !== stageOf(phase)).map(s => ({ key: `move:${s.key}`, label: `移到 ${s.key} · ${s.name}` })) },
      { type: 'divider' as const },
      { key: 'delete', icon: <DeleteOutlined />, danger: true, disabled: phase.work_items.length > 0, label: phase.work_items.length ? '删除分组（先移走工作项）' : '删除分组' },
    ],
    onClick: ({ key }: { key: string }) => {
      if (key === 'add') setEditor({ phaseId: phase.id })
      if (key === 'rename') setGroup({ mode: 'rename', stage: stageOf(phase), phase, name: phase.name })
      if (key.startsWith('move:')) { const target = key.slice(5); void mutate(async () => { await api.put(`/templates/${templateId}/work-phases/${phase.id}`, { stage_key: target }); message.success(`已移到「${STAGE_NAME[target]}」`) }) }
      if (key === 'delete') Modal.confirm({ title: `删除空分组「${phase.name}」？`, okText: '删除', okButtonProps: { danger: true }, cancelText: '取消', onOk: () => mutate(() => api.delete(`/templates/${templateId}/work-phases/${phase.id}`)) })
    },
  })

  const row = (phase: WorkPhase) => (item: WorkItem) => <li key={item.id}>
    <button type="button" className="tpl-row" onClick={() => setDetailId(item.id)}>
      <span className="tpl-row-title"><span className="tpl-row-name">{item.name}</span>
        {item.group_label && item.group_label !== phase.name && <span className="tpl-row-tag">{item.group_label}</span>}</span>
      <span className="tpl-row-meta">
        {item.kind === 'vehicle' && <span className="tpl-meta is-vehicle" title="逐车记录"><CarOutlined aria-hidden />{stepName(item.vehicle_step_key) ?? '未关联环节'}</span>}
        {!!item.check_definitions?.length && <span className="tpl-meta" title="检查要求"><CheckCircleOutlined aria-hidden />{item.check_definitions.length}</span>}
        {!!item.reference_docs.length && <span className="tpl-meta" title="参考文档"><PaperClipOutlined aria-hidden />{item.reference_docs.length}</span>}
        <RightOutlined className="tpl-row-chevron" aria-hidden />
      </span>
    </button>
  </li>

  const groupBlock = (phase: WorkPhase) => {
    const items = phase.work_items.filter(matches)
    if (term && !items.length) return null
    return <div key={phase.id} className="tpl-group" role="region" aria-label={`工作分组：${phase.name}`}>
      <div className="tpl-group-head">
        <strong>{phase.name}</strong><span className="tpl-group-count">{items.length}</span>
        {canManage && <Dropdown trigger={['click']} disabled={busy} menu={groupMenu(phase)}><IconAction label={`分组「${phase.name}」操作`} icon={<MoreOutlined />} /></Dropdown>}
      </div>
      {items.length ? <ul className="tpl-list">{items.map(row(phase))}</ul>
        : <p className="tpl-empty">还没有工作项{canManage && <Button type="link" size="small" onClick={() => setEditor({ phaseId: phase.id })}>添加</Button>}</p>}
    </div>
  }

  const refs = detail?.item.reference_docs ?? []
  return <div className="tpl-tab">
    <div className="tpl-toolbar">
      <Input allowClear prefix={<SearchOutlined />} placeholder="查找工作项" aria-label="查找工作项" value={keyword} onChange={e => setKeyword(e.target.value)} />
      {canManage && <Button type="primary" icon={<PlusOutlined />} disabled={!phases.length || loading || busy} onClick={() => setEditor({ phaseId: phases.find(p => stageOf(p) === '6')?.id ?? phases[0]?.id })}>添加工作项</Button>}
    </div>
    {term && !Object.keys(counts).length ? <Empty description="没有匹配的工作项" /> : <StageOutline id="tpl-work" label="工作" unit="项工作" stages={outlineStages(counts)}>
      {STAGES.map(stage => {
        const groups = phases.filter(phase => stageOf(phase) === stage.key)
        if (term && !counts[stage.key]) return null
        return <StageSection key={stage.key} outlineId="tpl-work" stage={stage.key} title={stageLabel(stage.key)} meta={counts[stage.key] ? `${counts[stage.key]} 项` : '暂无工作'}
          actions={canManage && <IconAction label={`在「${stage.name}」添加工作分组`} icon={<PlusOutlined />} disabled={busy || loading} onClick={() => setGroup({ mode: 'create', stage: stage.key, name: '' })} />}>
          {groups.map(groupBlock)}
        </StageSection>
      })}
    </StageOutline>}

    <Drawer title={detail?.item.name} open={!!detail} onClose={() => setDetailId(undefined)} width={520}
      extra={canManage && detail && <Button icon={<EditOutlined />} onClick={() => { setEditor({ item: detail.item }); setDetailId(undefined) }}>编辑工作项</Button>}>
      {detail && <div className="tpl-detail">
        {detail.item.description ? <Typography.Paragraph className="tpl-detail-desc">{detail.item.description}</Typography.Paragraph> : <Typography.Paragraph type="secondary">没有工作说明</Typography.Paragraph>}
        <dl className="tpl-facts">
          <dt>位置</dt><dd>{stageLabel(stageOf(detail.phase))} / {detail.phase.name}</dd>
          <dt>记录方式</dt><dd>{detail.item.kind === 'vehicle' ? `逐车记录 · ${stepName(detail.item.vehicle_step_key) ?? '未关联车辆环节'}` : '完成 / 未完成'}</dd>
          {detail.item.group_label && detail.item.group_label !== detail.phase.name && <><dt>分组标签</dt><dd>{detail.item.group_label}</dd></>}
          {!!detail.item.applicable_vehicle_types?.length && <><dt>适用车型</dt><dd>{detail.item.applicable_vehicle_types.join('、')}</dd></>}
          {!!detail.item.scope_conditions?.length && <><dt>业务范围</dt><dd>{detail.item.scope_conditions.map(key => SCOPES[key] ?? key).join('、')}</dd></>}
        </dl>
        <h4>检查要求 <span>{detail.item.check_definitions?.length ?? 0}</span></h4>
        {detail.item.check_definitions?.length ? <ul className="tpl-detail-list">{detail.item.check_definitions.map((check, index) => <li key={index}>
          <strong>{check.name}</strong>{check.is_required && <Tag color="blue">必需</Tag>}{check.is_safety_critical && <Tag color="red">安全关键</Tag>}
          {check.description && <Typography.Text type="secondary">{check.description}</Typography.Text>}
        </li>)}</ul> : <p className="tpl-empty">无</p>}
        <h4>参考文档 <span>{refs.length}</span></h4>
        {refs.length ? <ul className="tpl-detail-list">{refs.map((ref: any) => <li key={ref.id} className="tpl-ref">
          <Button type="link" icon={<PaperClipOutlined />} onClick={() => void downloadDocumentResource(`/templates/${templateId}/tasks/${detail.item.id}/reference-docs/${ref.id}/download`, ref.filename)}>{ref.filename}</Button>
          {ref.note && <Typography.Text type="secondary">{ref.note}</Typography.Text>}
          {canManage && <IconAction label={`删除参考文档「${ref.filename}」`} icon={<DeleteOutlined />} danger disabled={busy} onClick={() => Modal.confirm({ title: `删除参考文档「${ref.filename}」？`, okText: '删除', cancelText: '取消', onOk: () => mutate(() => api.delete(`/templates/${templateId}/tasks/${detail.item.id}/reference-docs/${ref.id}`)) })} />}
        </li>)}</ul> : <p className="tpl-empty">无</p>}
        {canManage && <Upload showUploadList={false} beforeUpload={file => { const target = detail.item.id; void mutate(async () => { const body = new FormData(); body.append('file', file); await api.post(`/templates/${templateId}/tasks/${target}/reference-docs`, body) }); return false }}>
          <Button icon={<UploadOutlined />} disabled={busy}>上传参考文档</Button>
        </Upload>}
      </div>}
    </Drawer>

    <WorkItemEditor canEdit={canManage} open={!!editor} templateId={templateId} item={editor?.item} defaultPhaseId={editor?.phaseId} phases={phases} steps={steps}
      onCreateStep={canManage ? onCreateStep : undefined} onClose={() => setEditor(undefined)} onSaved={onReload} />
    <Modal title={group?.mode === 'rename' ? '重命名工作分组' : `在「${STAGE_NAME[group?.stage ?? '6']}」添加工作分组`} open={!!group} onCancel={() => { if (!busy) setGroup(undefined) }}
      onOk={() => void saveGroup()} confirmLoading={busy} okText="保存分组" cancelText="取消" okButtonProps={{ disabled: !canManage || !group?.name.trim() }}>
      <Input aria-label="工作分组名称" value={group?.name} onChange={e => setGroup(old => old && { ...old, name: e.target.value })} maxLength={100} placeholder="例如：现场勘测、单车调试" onPressEnter={() => void saveGroup()} />
    </Modal>
  </div>
}
