import { Checkbox, Collapse, Space, Tag, Typography } from 'antd'

/** Legacy module envelopes are read-only transport; selections are work IDs. */
export function flatWorkItems(phases: any[]) {
  return phases.filter(p => p.name !== '项目准备').flatMap(phase => (phase.work_items ?? (phase.modules ?? []).filter((m: any) => !m.prep_only).flatMap((m: any) => (m.tasks ?? []).map((t: any) => ({ ...t, source_module_id: m.id, group_label: t.group_label || m.name })))).map((t: any) => ({ ...t, phase_id: phase.id, phase_name: phase.name })))
}
export function selectedWorkItems(phases: any[], selected: string[], excluded: string[] = []): string[] {
  return flatWorkItems(phases).filter(t => (selected.includes(t.id) || selected.includes(t.source_module_id)) && !excluded.includes(t.id)).map(t => t.id)
}
export default function TemplateScope({ phases, selected, onSelected, excluded, onExcluded, disabled = false, review = false, showAll = false }: {
  phases: any[]; selected: string[]; onSelected: (value: string[]) => void; excluded: string[]; onExcluded: (value: string[]) => void
  disabled?: boolean; review?: boolean; showAll?: boolean; [key: string]: unknown
}) {
  const all = flatWorkItems(phases)
  const chosen = selectedWorkItems(phases, selected, excluded)
  const change = (ids: string[], checked: boolean) => {
    onSelected(checked ? [...new Set([...chosen, ...ids])] : chosen.filter(id => !ids.includes(id)))
    onExcluded(excluded.filter(id => !ids.includes(id)))
  }
  const stages = phases.filter(p => p.name !== '项目准备')
  return <section aria-label="工作项范围">
    <Space><Tag color="blue">已选 {chosen.length} 项工作</Tag><Tag>{all.filter(t => chosen.includes(t.id)).reduce((n, t) => n + (t.check_definitions?.length ?? t.check_items?.length ?? 0), 0)} 项检查要求</Tag></Space>
    <Collapse defaultActiveKey={stages.map(p => p.id)} key={stages.map(p => p.id).join('|')} items={stages.map(phase => {
      const work = all.filter(t => t.phase_id === phase.id)
      return { key: phase.id, label: phase.name, extra: <Checkbox aria-label={`选择阶段 ${phase.name}`} disabled={disabled} checked={!!work.length && work.every(t => chosen.includes(t.id))} indeterminate={work.some(t => chosen.includes(t.id)) && !work.every(t => chosen.includes(t.id))} onClick={e => e.stopPropagation()} onChange={e => change(work.map(t => t.id), e.target.checked)} />,
        children: work.filter(t => !review || showAll || chosen.includes(t.id)).map(task => <div key={task.id} style={{ margin: '10px 0' }}><Checkbox disabled={disabled} checked={chosen.includes(task.id)} onChange={e => change([task.id], e.target.checked)}>{task.name}</Checkbox>{task.group_label && <Tag>{task.group_label}</Tag>}<Tag>{(task.kind ?? (task.quantity_type === 'per_vehicle' ? 'vehicle' : 'other')) === 'vehicle' ? '关联车辆环节' : '完成 / 未完成'}</Tag><Typography.Paragraph type="secondary" style={{ marginLeft: 24 }}>{task.description || '无补充说明'}</Typography.Paragraph></div>) }
    })} />
  </section>
}
