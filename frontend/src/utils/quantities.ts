export interface UnitQuantity {
  unit: string
  completed: number
  target: number
}

export function formatQuantities(groups: UnitQuantity[]): string {
  return groups.map(group => `${Number(group.completed.toFixed(3))}/${Number(group.target.toFixed(3))} ${group.unit}`).join('；') || '暂无填报目标'
}
