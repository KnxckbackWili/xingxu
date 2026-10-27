/** A voided review must never appear current in startup or overview. */
export function entryReady(summary: any): boolean {
  if (!summary || summary.void) return false
  return summary.entry_confirmed === true || (summary.state_key === 'ready'
    && !(summary.entry_unmet ?? summary.blocked ?? 0) && !(summary.missing?.length))
}

/** Preparation preview follows the same explicit module links as project creation. */
export function projectPreparations(phases: any[], templatePreps: any[], selected: string[], excluded: string[], facts: { new_vehicles: boolean; client_server: boolean; overseas: boolean }) {
  const sources: Record<string, string> = { default: '通用准备' }
  if (facts.new_vehicles) sources.new_vehicles = '车辆来源：包含新造车辆'
  if (facts.client_server) sources.client_server = '服务器：客户提供'
  if (facts.overseas) sources.overseas = '实施地点：海外'
  const work = phases.filter((phase) => phase.name !== '项目准备').flatMap((phase) =>
    (phase.modules ?? []).filter((module: any) => !module.prep_only && selected.includes(module.id)).map((module: any) => ({
      phase, module, tasks: (module.tasks ?? []).filter((task: any) => !excluded.includes(task.id)),
    })))
  for (const { module, tasks } of work) {
    if (!tasks.length) continue
    for (const condition of module.preparation_conditions ?? []) sources[condition] = `实施工作：${module.name}`
  }
  const items = templatePreps.filter((item) => sources[item.condition]).map((item) => ({ ...item, source: sources[item.condition] }))
  const names = new Set(items.map((item) => item.name))
  // Existing execution preparation tasks become tracked preparations on creation too.
  for (const { phase, tasks } of work) {
    if (!/准备|进场/.test(phase.name)) continue
    for (const task of tasks) {
      if (names.has(task.name)) continue
      const definition = templatePreps.find((item) => item.name === task.name)
      items.push({ ...definition, id: task.id, name: task.name, source: `实施工作：${phase.name}`, blocks_entry: definition?.blocks_entry ?? false })
      names.add(task.name)
    }
  }
  return items
}
