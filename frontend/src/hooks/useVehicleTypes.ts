import { useCallback, useEffect, useState } from 'react'
import { vehicleTypeApi } from '../api'

export interface VehicleTypeOption {
  id: string
  name: string
  is_enabled: boolean
  sort_order: number
}

/**
 * 车型字典加载（HYPE-63）：业务页面（项目创建 / 现场信息 / 模板适用车型）
 * 统一从后端字典取启用项，不再硬编码；加载失败暴露可理解错误与重试。
 */
export function useVehicleTypes() {
  const [options, setOptions] = useState<VehicleTypeOption[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string>('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setOptions(await vehicleTypeApi.list())
    } catch (e: any) {
      setOptions([])
      setError(e?.response?.data?.detail ?? '车型字典加载失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  return { options, loading, error, reload: load }
}

/** 把启用字典项转成 AntD Select options（label/value 均为车型名）。 */
export function toVehicleTypeSelectOptions(
  options: VehicleTypeOption[],
  extraNames: string[] = [],
): Array<{ label: string; value: string }> {
  const seen = new Set<string>()
  const rows: Array<{ label: string; value: string }> = []
  for (const o of options) {
    if (seen.has(o.name)) continue
    seen.add(o.name)
    rows.push({ label: o.name, value: o.name })
  }
  // 历史值（已停用 / 字典外）追加为可选项，保证编辑时保留原值不清空
  for (const name of extraNames) {
    if (!name || !name.trim() || seen.has(name)) continue
    seen.add(name)
    rows.push({ label: `${name}（历史）`, value: name })
  }
  return rows
}
