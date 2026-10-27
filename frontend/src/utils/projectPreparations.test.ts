import { expect, it } from 'vitest'
import { entryReady, projectPreparations } from './projectPreparations'
const phases = [{ name: '系统联调', modules: [{ id: 'charge', name: '更名后的充电实施', preparation_conditions: ['need_charging'], tasks: [{ id: 'c1', name: '安装' }] }, { id: 'wms', name: '客户订单对接', preparation_conditions: ['need_wms'], tasks: [{ id: 'w1', name: '联调' }] }] }]
const preps = [{ id: 'p1', name: '充电区域施工', condition: 'need_charging' }, { id: 'p2', name: '接口协议', condition: 'need_wms' }, { id: 'p3', name: '发货', condition: 'new_vehicles' }]
const facts = { new_vehicles: false, client_server: false, overseas: false }
it('previews explicit work links and removes them when work is deselected or excluded', () => {
  expect(projectPreparations(phases, preps, ['charge'], [], facts).map(item => item.name)).toEqual(['充电区域施工'])
  expect(projectPreparations(phases, preps, [], [], facts)).toEqual([])
  expect(projectPreparations(phases, preps, ['charge'], ['c1'], facts)).toEqual([])
  expect(projectPreparations(phases, preps, ['wms'], [], facts)[0].source).toBe('实施工作：客户订单对接')
})
it('vehicle facts are independent from work and template switches do not keep old links', () => {
  expect(projectPreparations(phases, preps, [], [], { ...facts, new_vehicles: true }).map(item => item.name)).toEqual(['发货'])
  expect(projectPreparations([], preps, ['charge'], [], facts)).toEqual([])
})
it('includes execution preparation tasks and deduplicates their matching checklist items', () => {
  const preparationPhase = [{ name: '进场准备', modules: [{ id: 'entry', tasks: [{ id: 't1', name: '现场确认' }, { id: 't2', name: '网络检查' }] }] }]
  const result = projectPreparations(preparationPhase, [{ id: 'p1', name: '现场确认', condition: 'default' }], ['entry'], [], facts)
  expect(result.map(item => item.name)).toEqual(['现场确认', '网络检查'])
})


it('requires current readiness and never treats an invalidated risk review as ready', () => {
  expect(entryReady({ state_key: 'forced_ready', entry_confirmed: true, void: false })).toBe(true)
  expect(entryReady({ state_key: 'forced_ready', entry_confirmed: true, void: true })).toBe(false)
  expect(entryReady({ state_key: 'ready', entry_unmet: 1 })).toBe(false)
  expect(entryReady({ state_key: 'ready', entry_unmet: 0, missing: ['清单缺失'] })).toBe(false)
  expect(entryReady({ state_key: 'ready', entry_unmet: 0, missing: [] })).toBe(true)
  expect(entryReady(undefined)).toBe(false)
})
