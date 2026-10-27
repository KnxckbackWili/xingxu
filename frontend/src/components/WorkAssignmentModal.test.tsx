import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { ConfigProvider } from 'antd'
const h=vi.hoisted(()=>({list:vi.fn(),post:vi.fn(),verify:vi.fn(),close:vi.fn(),saved:vi.fn(),user:{id:'pm',role:'pm',permission_overrides:{}} as any}))
vi.mock('../api/weeklyPlans',()=>({weeklyPlansApi:{list:h.list}}))
vi.mock('../api/client',()=>({api:{post:h.post},errMsg:(e:any)=>e.message||'请求失败'}))
vi.mock('../stores/auth',()=>({useAuth:()=>({user:h.user})}))
vi.mock('../utils/verifiedAccount',()=>({ensureVerifiedAccount:h.verify}))
import WorkAssignmentModal from './WorkAssignmentModal'
const context={projectId:'p1',personId:'u1',date:'2026-10-29',repair:{unitId:'unit1',eventId:'fault1',title:'驱动轮故障'}}
const model={permissions:{edit:true},timezone:'Asia/Shanghai',members:[{id:'u1',name:'王工',active:true}]}
const show=(value:any=context)=>render(<ConfigProvider theme={{token:{motion:false}}}><WorkAssignmentModal context={value} onClose={h.close} onSaved={h.saved}/></ConfigProvider>)
beforeEach(()=>{vi.clearAllMocks();h.user={id:'pm',role:'pm',permission_overrides:{}};h.list.mockResolvedValue(model);h.post.mockResolvedValue({data:{created:true}});h.verify.mockImplementation(()=>undefined)})
it('creates one explicit weekly draft with several separate planning fields and no hours',async()=>{
 let finish!:(v:any)=>void;h.post.mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve}));show();const save=await screen.findByRole('button',{name:'保存为周计划草稿'});await waitFor(()=>expect(save).toBeEnabled())
 fireEvent.change(screen.getByLabelText('维修安排说明'),{target:{value:'带驱动轮和工具'}});fireEvent.click(save);fireEvent.click(save)
 await waitFor(()=>expect(h.post).toHaveBeenCalledOnce());expect(h.post).toHaveBeenCalledWith('/projects/p1/vehicle-units/unit1/events/fault1/weekly-plans',{week_start:'2026-10-26',assignee_ids:['u1'],mode:'finish',notes:'带驱动轮和工具'});expect(h.verify).toHaveBeenCalledWith('pm')
 await act(async()=>finish({data:{created:true}}));expect(h.saved).toHaveBeenCalledOnce();expect(h.close).toHaveBeenCalledOnce()
})
it('keeps a duplicate result explicit without pretending to overwrite or publish the old plan',async()=>{
 h.post.mockResolvedValueOnce({data:{created:false}});show();const save=await screen.findByRole('button',{name:'保存为周计划草稿'});await waitFor(()=>expect(save).toBeEnabled());fireEvent.click(save)
 await waitFor(()=>expect(screen.getByText('本周已存在此维修计划格，本次填写尚未修改原安排')).toBeVisible());expect(h.saved).not.toHaveBeenCalled();expect(h.close).not.toHaveBeenCalled();expect(save).toBeDisabled();expect(screen.getByRole('link',{name:'前往周计划核对并修改'})).toHaveAttribute('href','/pm/projects/p1/plan?view=weeks&week=2026-10-26')
})
it('preserves notes after a failed save and rereads without automatically replaying it',async()=>{
 h.post.mockRejectedValueOnce(new Error('暂时不可保存'));show();const save=await screen.findByRole('button',{name:'保存为周计划草稿'});await waitFor(()=>expect(save).toBeEnabled());fireEvent.change(screen.getByLabelText('维修安排说明'),{target:{value:'保留现场工具备注'}});fireEvent.click(save)
 await screen.findByText('暂时不可保存');fireEvent.click(screen.getByRole('button',{name:'重新读取'}));await waitFor(()=>expect(h.list).toHaveBeenCalledTimes(2));expect(screen.getByLabelText('维修安排说明')).toHaveValue('保留现场工具备注');expect(h.post).toHaveBeenCalledOnce()
})
it('does not submit a daily arrangement from a retained old context',async()=>{
 show({entry:{project_id:'p1',id:'old-daily',work_date:'2026-10-27'}});expect(await screen.findByRole('link',{name:'打开项目周计划'})).toHaveAttribute('href','/pm/projects/p1/plan?view=weeks');expect(screen.getByRole('button',{name:'保存为周计划草稿'})).toBeDisabled();expect(h.list).not.toHaveBeenCalled();expect(h.post).not.toHaveBeenCalled()
})
it('denies repair planning when the system explicitly forbids schedule maintenance',async()=>{
 h.user={...h.user,permission_overrides:{'project.manage_schedule':false}};show();await waitFor(()=>expect(screen.getByText('本账号当前没有此项目的周计划维护权限')).toBeVisible());expect(screen.getByRole('button',{name:'保存为周计划草稿'})).toBeDisabled()
})
