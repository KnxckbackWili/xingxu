import { act, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
const h=vi.hoisted(()=>({statistics:vi.fn(),user:{id:'a',role:'pm',permission_version:1,permission_overrides:{} as Record<string,boolean>}}))
vi.mock('../stores/auth',()=>({useAuth:()=>({user:h.user})}))
vi.mock('../api/workbench',()=>({workbenchApi:{statistics:h.statistics}}))
vi.mock('../api/client',()=>({errMsg:(error:Error)=>error.message}))
import WorkspaceStatistics from './WorkspaceStatistics'
const data={projects:3,active_projects:2,completed_projects:1,status_distribution:[{status:'executing',count:2}],vehicle_progress:{target:10,completed:4,quantity_unknown:false,percent:40},documents:{this_week_count:5,overdue_count:2},issues:{open:6,critical:1}}
beforeEach(()=>{vi.resetAllMocks();h.user={id:'a',role:'pm',permission_version:1,permission_overrides:{}};h.statistics.mockResolvedValue(data)})
it('reads only current aggregate statistics with its own permission',async()=>{
  h.user.permission_overrides={'workspace.view':false,'insights.view':true}
  render(<WorkspaceStatistics/>);expect(await screen.findByText(/已完成 4 \/ 10 个车辆环节/)).toBeVisible()
  expect(screen.getByText('现场实施')).toBeVisible();expect(h.statistics).toHaveBeenCalledOnce()
  expect(screen.queryByText(/工时|人天|单位耗时/)).toBeNull()
})
it('does not fetch or display aggregates when statistics is explicitly denied',()=>{
  h.user.permission_overrides={'insights.view':false};render(<WorkspaceStatistics/>);expect(h.statistics).not.toHaveBeenCalled();expect(screen.queryByLabelText('统计')).toBeNull()
})
it('clears a prior account immediately and ignores its delayed response',async()=>{
  let finish!:(value:typeof data)=>void
  h.statistics.mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve})).mockResolvedValue({...data,projects:1,vehicle_progress:{...data.vehicle_progress,completed:1,percent:10}})
  const view=render(<WorkspaceStatistics/>);h.user={...h.user,id:'b'};view.rerender(<WorkspaceStatistics/>)
  expect(await screen.findByText(/已完成 1 \/ 10 个车辆环节/)).toBeVisible()
  await act(async()=>finish(data));expect(screen.queryByText(/已完成 4 \/ 10 个车辆环节/)).toBeNull()
})
it('keeps failed data unknown instead of rendering zero successes',async()=>{
  h.statistics.mockRejectedValue(new Error('暂时断网'));render(<WorkspaceStatistics/>);expect(await screen.findByText('统计暂不可读取')).toBeVisible()
  await waitFor(()=>expect(screen.queryByText('可见项目')).toBeNull())
})
