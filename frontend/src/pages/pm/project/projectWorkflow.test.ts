import { describe, expect, it } from 'vitest'
import { projectStageGuidance, projectWorkflow, type WorkflowInput } from './projectWorkflow'
const ready: WorkflowInput = { status: 'preparing', vehicles: 2, tasks: 12, members: 2, plans: 12, drafts: 0, unassigned: 0, kickoffReady: true, prepReady: true, severeIssues: 0, progress: 0 }
describe('人工推进和概况筹备清单', () => {
  it('unknown original state remains visible and never creates a status decision', () => {
    const result=projectWorkflow({...ready,status:'legacy_unknown',progress:100,severeIssues:2})
    expect(result.action).toMatchObject({title:'查阅历史记录',path:'/activity'})
    expect(result.action.description).toContain('legacy_unknown')
    expect(result.action.status).toBeUndefined()
  })
  it('uses the five ordered setup areas and moves only to the adjacent ready state', () => {
    expect(projectWorkflow(ready).checklist.map(row=>row.title)).toEqual(['车型','人员','资料清单','周计划','发车前资料确认'])
    expect(projectWorkflow(ready).action.status).toBe('ready')
    expect(projectWorkflow({...ready,vehicles:0}).action.path).toBe('/edit?section=vehicles')
    expect(projectWorkflow({...ready,members:0}).action.path).toBe('/edit?section=members')
    expect(projectWorkflow({...ready,kickoffReady:false}).action.path).toBe('/documents?stage=4')
    expect(projectWorkflow({...ready,unassigned:1}).action.path).toBe('/plan?view=weeks')
    expect(projectWorkflow({...ready,prepReady:false}).action.path).toBe('/documents?review=1')
  })
  it('describes signoffs and milestones without retired project states', () => {
    expect(projectStageGuidance('preparing')?.next).toBe('ready')
    expect(projectStageGuidance('ready')?.next).toBe('executing')
    expect(projectStageGuidance('executing')?.next).toBe('acceptance')
    expect(projectStageGuidance('executing')?.description).toContain('调试完工单')
    for(const state of ['draft','planning','commissioning','pilot'])expect(projectStageGuidance(state)).toBeNull()
  })
  it('keeps serious issues first and full progress still requires a separate human decision', () => {
    expect(projectWorkflow({...ready,status:'executing',severeIssues:1}).action.path).toBe('/issues')
    expect(projectWorkflow({...ready,status:'executing',progress:100}).action.path).toBe('/documents?stage=6')
    expect(projectWorkflow({...ready,status:'executing',progress:100}).action.status).toBeUndefined()
    expect(projectWorkflow({...ready,status:'acceptance',progress:100}).action.path).toBe('/documents?acceptance=1')
  })
  it.each(['completed','archived','suspended'])('%s does not restart setup or advance on a percentage',status=>{
    const result=projectWorkflow({...ready,status,vehicles:0,progress:100})
    expect(result.setup).toBe(false);expect(result.action.status).toBeUndefined()
  })
})
