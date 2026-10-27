import { describe,expect,it } from 'vitest'
import { PROJECT_NAV_ITEMS,PROJECT_PRIMARY_SECTIONS,PROJECT_MORE_KEYS,PROJECT_PAGE_INFO,PROJECT_NAV_GROUPS,PROJECT_ITEM_BY_KEY,PROJECT_CHILD_BY_SEGMENT,resolveProjectNav,childSegment,defaultChildKey,filterProjectNav,filterProjectActions,PROJECT_ACTIONS } from './projectNav'
describe('project navigation',()=>{
 it('has exactly six daily destinations and four More destinations from one definition',()=>{
  expect(PROJECT_PRIMARY_SECTIONS.map(row=>row.label)).toEqual(['概况','计划','车辆','资料','问题','现场'])
  expect(PROJECT_MORE_KEYS).toEqual(['reports','history','export','edit'])
  expect(PROJECT_NAV_GROUPS.flatMap(group=>group.items)).toEqual(PROJECT_NAV_ITEMS)
  expect(Object.values(PROJECT_PAGE_INFO).every(row=>row.aliases.length===0)).toBe(true)
 })
 it('keeps every retained destination addressable without duplicate leaf routes',()=>{
  const paths=PROJECT_NAV_ITEMS.flatMap(item=>item.children?.map(child=>child.path)??[item.path])
  expect(new Set(paths).size).toBe(paths.length)
  for(const item of PROJECT_NAV_ITEMS)expect(PROJECT_ITEM_BY_KEY[item.key]).toBe(item)
  expect(defaultChildKey(PROJECT_ITEM_BY_KEY.field)).toBe('inventory')
  expect(childSegment('field','handover')).toBe('handover')
  expect(PROJECT_CHILD_BY_SEGMENT.history.parentKey).toBe('activity')
 })
 it.each([
  ['overview','overview',null],['documents','delivery',null],['files','delivery',null],['archive','delivery',null],['preparation','delivery',null],
  ['tasks','plan',null],['schedule','plan',null],['vehicles','vehicles',null],['site','vehicles',null],['inventory','field','inventory'],['handover','field','handover'],
  ['history','activity','history'],['activity','activity','history'],['reports','activity','reports'],['edit','overview',null],['export','delivery',null],['start','overview',null],['unknown','overview',null],
 ])('resolves the retained %s link to its current renderer', (url,parent,child)=>expect(resolveProjectNav(url)).toEqual({parent,child}))
 it('shares readable project destinations across roles while keeping writes separate',()=>{
  for(const role of ['pm','admin','worker','intern','readonly'])expect(filterProjectNav(PROJECT_NAV_GROUPS,role,[])).toEqual(PROJECT_NAV_GROUPS)
  expect(filterProjectActions(PROJECT_ACTIONS,'readonly',false,[]).some(item=>item.key==='report')).toBe(false)
  expect(filterProjectActions(PROJECT_ACTIONS,'worker',false,[]).some(item=>item.key==='export')).toBe(false)
  expect(filterProjectActions(PROJECT_ACTIONS,'worker',false,['project.export']).some(item=>item.key==='export')).toBe(true)
 })
})
