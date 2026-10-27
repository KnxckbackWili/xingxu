export interface UnitQuantity {
  unit: string
  completed: number
  target: number
}

/** Physical quantities can only be added when their units match. */
export function groupQuantities(tasks: Array<{ unit?: string; completed: number; target_quantity: number | null }>): UnitQuantity[] {
  const groups = new Map<string, UnitQuantity>()
  for (const task of tasks) {
    const unit = task.unit?.trim() || '项'
    const group = groups.get(unit) ?? { unit, completed: 0, target: 0 }
    group.completed += task.completed
    group.target += task.target_quantity ?? 0
    groups.set(unit, group)
  }
  return [...groups.values()]
}

export function formatQuantities(groups: UnitQuantity[]): string {
  return groups.map(group => `${Number(group.completed.toFixed(3))}/${Number(group.target.toFixed(3))} ${group.unit}`).join('；') || '暂无填报目标'
}
