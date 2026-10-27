import { afterEach, describe, expect, it, vi } from 'vitest'

const apiGet = vi.fn()
const apiPost = vi.fn()
const apiPut = vi.fn()

vi.mock('../api/client', () => ({
  api: {
    get: (...args: unknown[]) => apiGet(...args),
    post: (...args: unknown[]) => apiPost(...args),
    put: (...args: unknown[]) => apiPut(...args),
  },
  errMsg: () => 'mock-error',
  tokenStore: { access: 'test-token' },
}))

import { vehicleTypeApi } from '../api'
import { toVehicleTypeSelectOptions } from './useVehicleTypes'

/**
 * HYPE-63 车型字典前端回归：
 * toVehicleTypeSelectOptions 把启用字典项映射为 Select 选项，历史值以「（历史）」保留、去重；
 * vehicleTypeApi 端点路径与既有 REST 风格一致。
 */
describe('toVehicleTypeSelectOptions', () => {
  const dict = [
    { id: 'a', name: '潜伏式', is_enabled: true, sort_order: 1 },
    { id: 'b', name: '堆高车', is_enabled: true, sort_order: 2 },
  ]

  it('启用字典项 → {label,value} 同值选项', () => {
    expect(toVehicleTypeSelectOptions(dict)).toEqual([
      { label: '潜伏式', value: '潜伏式' },
      { label: '堆高车', value: '堆高车' },
    ])
  })

  it('历史值（已停用/字典外）以「（历史）」追加，且不覆盖字典项', () => {
    const rows = toVehicleTypeSelectOptions(dict, ['进口叉车', '堆高车', '老式叉车'])
    expect(rows).toEqual([
      { label: '潜伏式', value: '潜伏式' },
      { label: '堆高车', value: '堆高车' },
      { label: '进口叉车（历史）', value: '进口叉车' },
      { label: '老式叉车（历史）', value: '老式叉车' },
    ])
  })

  it('空字符串 / 纯空格 / 与字典重复的历史值被忽略；带首尾空格的历史值保留', () => {
    const rows = toVehicleTypeSelectOptions(dict, ['', '潜伏式', ' ', ' 半成品 '])
    expect(rows).toHaveLength(3)
    expect(rows.map((r) => r.value)).not.toContain('')
    expect(rows.map((r) => r.value)).not.toContain(' ')
    // 「 半成品 」首尾空格不 trim，仍视为独立历史值（与后端行为一致：仅字典名精确匹配）
    expect(rows).toContainEqual({ label: ' 半成品 （历史）', value: ' 半成品 ' })
  })
})

describe('vehicleTypeApi 端点', () => {
  afterEach(() => vi.clearAllMocks())

  it('list → GET /vehicle-types（普通用户读取启用项）', async () => {
    apiGet.mockResolvedValue({ data: [{ id: 'a', name: '潜伏式' }] })
    const rows = await vehicleTypeApi.list()
    expect(apiGet).toHaveBeenCalledWith('/vehicle-types')
    expect(rows).toEqual([{ id: 'a', name: '潜伏式' }])
  })

  it('listAll → GET /vehicle-types/all（管理员含停用）', async () => {
    apiGet.mockResolvedValue({ data: [{ id: 'a', name: '潜伏式', is_enabled: false }] })
    await vehicleTypeApi.listAll()
    expect(apiGet).toHaveBeenCalledWith('/vehicle-types/all')
  })

  it('create → POST /vehicle-types，reorder → PUT /vehicle-types/reorder', async () => {
    apiPost.mockResolvedValue({ data: { id: 'a', name: '双向车' } })
    await vehicleTypeApi.create({ name: '双向车' })
    expect(apiPost).toHaveBeenCalledWith('/vehicle-types', { name: '双向车' })

    apiPut.mockResolvedValue({ data: { ok: true } })
    await vehicleTypeApi.reorder(['a', 'b'])
    expect(apiPut).toHaveBeenCalledWith('/vehicle-types/reorder', { ids: ['a', 'b'] })
  })

  it('update → PUT /vehicle-types/{id}（启停/排序/重命名）', async () => {
    apiPut.mockResolvedValue({ data: { id: 'a', is_enabled: false } })
    await vehicleTypeApi.update('a', { is_enabled: false })
    expect(apiPut).toHaveBeenCalledWith('/vehicle-types/a', { is_enabled: false })
  })
})
