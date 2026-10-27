import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { ConfigProvider } from 'antd'
import { MemoryRouter } from 'react-router-dom'
import type { WeeklyPlanView, PlanCell } from '../../../api/weeklyPlans'
const h=vi.hoisted(()=>({list:vi.fn(),create:vi.fn(),update:vi.fn(),publish:vi.fn(),preview:vi.fn(),defaultRules:vi.fn(),draft:vi.fn(),excel:vi.fn(),verify:vi.fn(),changed:vi.fn(),user:{id:'pm',role:'pm',permission_version:0,permission_overrides:{}} as any}))
vi.mock('../../../api/weeklyPlans',async original=>({...await original<object>(),weeklyPlansApi:h}))
vi.mock('../../../stores/auth',()=>({useAuth:()=>({user:h.user})}))
vi.mock('../../../utils/verifiedAccount',()=>({ensureVerifiedAccount:h.verify}))
vi.mock('../../../api/client',()=>({errMsg:(e:any)=>e.response?.data?.detail||e.message||'读取失败'}))
import SchedulePage from './SchedulePage'
const start='2026-10-26'
const cell=(id='c1',changes:Partial<PlanCell>={}):PlanCell=>({id,project_id:'p1',task_id:'w1',task_name:'接线核对',phase_id:'phase',phase_name:'现场工作',group_label:'电气',kind:'other',scope:{vehicle_unit_ids:[]},week_start:start,week_end:'2026-11-01',mode:'finish',target_count:null,assignee_ids:['worker'],assignees:[{id:'worker',name:'李工',active:true}],notes:'',intent_review_required:false,published:false,is_cancelled:false,version:4,permissions:{edit:true,claim:false},completion:{state:'planned',is_complete:false,overdue:false,completed_count:0,required_count:1,expected_count:1,quantity_unknown:false,target_review_required:false,warnings:[]},...changes})
const fixture=(changes:Partial<WeeklyPlanView>={}):WeeklyPlanView=>({cells:[cell()],work_items:[{id:'phase',name:'现场工作',work_items:[{id:'w1',name:'接线核对',kind:'other',group_label:'电气',vehicle_step_key:null,applicable_vehicle_types:[],version:1},{id:'w2',name:'单车检查',kind:'vehicle',group_label:'',vehicle_step_key:'inspection',applicable_vehicle_types:[],version:1}]}],weeks:[{week_start:start,week_end:'2026-11-01',holiday_days:[],makeup_workdays:[],missing_holiday_years:[]}],warnings:[],timezone:'Asia/Shanghai',members:[{id:'worker',name:'李工',active:true}],vehicles:[{id:'real-u1',label:'AGV-01'}],vehicle_types:['潜伏式'],settings:{rest_mode:'two',rest_days:[],skip_holidays:true},permissions:{read:true,edit:true,publish:true,export:true,claim:false},summary:{state:'available',published_count:0,draft_count:1,overdue_count:0,in_progress_count:0},...changes})
const project={id:'p1',name:'现场项目',status:'executing',timezone:'Asia/Shanghai',capabilities:['project.manage_schedule'],version:2} as any
function page(p=project){return <MemoryRouter><ConfigProvider theme={{token:{motion:false}}}><SchedulePage projectId={p.id} project={p} onProjectChange={h.changed}/></ConfigProvider></MemoryRouter>}
const show=()=>render(page())
beforeEach(()=>{vi.clearAllMocks();h.user={id:'pm',role:'pm',permission_version:0,permission_overrides:{}};h.list.mockResolvedValue(fixture());h.create.mockResolvedValue(cell('new'));h.update.mockResolvedValue(cell());h.publish.mockResolvedValue({});h.draft.mockResolvedValue({});h.defaultRules.mockResolvedValue({rules:[],suggestions:[],warnings:[]});h.verify.mockImplementation(()=>undefined)})
it('shows work by week and keeps planned people separate from actual completion',async()=>{
 show();expect(await screen.findByRole('region',{name:'周计划表'})).toBeVisible()
 expect(screen.getByText('接线核对')).toBeVisible();expect(screen.getByText('李工')).toBeVisible();expect(screen.getByText('计划完成')).toBeVisible()
 expect(screen.queryByText('计划 0 项')).toBeNull();expect(screen.getByRole('link',{name:'排期设置'})).toHaveAttribute('href','/pm/projects/p1/edit?section=schedule')
})
it('allows a server-authorized field role and honors an explicit system denial',async()=>{
 h.user={id:'worker',role:'worker',permission_overrides:{}};const view=show();await screen.findByRole('button',{name:'新增计划格'})
 h.user={...h.user,permission_version:1,permission_overrides:{'project.manage_schedule':false}};view.rerender(page())
 await waitFor(()=>expect(h.list).toHaveBeenCalledTimes(2));expect(screen.queryByRole('button',{name:'新增计划格'})).toBeNull();expect(await screen.findByText('接线核对')).toBeVisible()
})
it('creates non-vehicle completion plans without a quantity and rejects duplicate clicks',async()=>{
 let finish!:(v:any)=>void;h.create.mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve}));show()
 fireEvent.click(await screen.findByRole('button',{name:'安排接线核对 '+start}));fireEvent.change(screen.getByLabelText('周计划备注'),{target:{value:'核对现场接线'}})
 const save=screen.getByRole('button',{name:'保存计划'});fireEvent.click(save);fireEvent.click(save)
 await waitFor(()=>expect(h.create).toHaveBeenCalledOnce());expect(h.create).toHaveBeenCalledWith('p1',expect.objectContaining({task_id:'w1',mode:'finish',target_count:null,assignee_ids:[],notes:'核对现场接线'}));expect(h.verify).toHaveBeenCalledWith('pm')
 await act(async()=>finish(cell('new')))
})
it('requires positive vehicle targets and never invents a zero target',async()=>{
 show();fireEvent.click(await screen.findByRole('button',{name:'安排单车检查 '+start}));expect(screen.getByRole('button',{name:'保存计划'})).toBeDisabled()
 fireEvent.change(screen.getByRole('spinbutton',{name:'计划完成车辆台数'}),{target:{value:'2'}});fireEvent.click(screen.getByRole('button',{name:'保存计划'}))
 await waitFor(()=>expect(h.create).toHaveBeenCalledWith('p1',expect.objectContaining({task_id:'w2',target_count:2,scope:{vehicle_unit_ids:[]}})))
})
it('publishes only explicitly selected cell versions',async()=>{
 h.list.mockResolvedValue(fixture({cells:[cell(),cell('other',{week_start:'2026-11-02',week_end:'2026-11-08'})]}));show()
 fireEvent.click(await screen.findByRole('checkbox',{name:'选择接线核对 '+start+' 本工作项'}));fireEvent.click(screen.getByRole('button',{name:'发布已选 1 格'}));fireEvent.click(within(screen.getByRole('dialog',{name:'发布选定周计划'})).getByRole('button',{name:'确认发布'}))
 await waitFor(()=>expect(h.publish).toHaveBeenCalledWith('p1',[{id:'c1',version:4}]))
})
it('edits an already published plan directly and preserves input after a stale refusal',async()=>{
 h.list.mockResolvedValue(fixture({cells:[cell('c1',{published:true})]}));h.update.mockRejectedValueOnce({response:{status:409,data:{detail:'计划版本已变化'}}});show()
 fireEvent.click(await screen.findByRole('button',{name:'编辑接线核对 '+start+' 本工作项'}));fireEvent.change(screen.getByLabelText('周计划备注'),{target:{value:'保留这次修改'}});fireEvent.click(screen.getByRole('button',{name:'保存计划'}))
 await waitFor(()=>expect(screen.getByText('请重新读取最新计划后再保存')).toBeVisible());expect(screen.getByLabelText('周计划备注')).toHaveValue('保留这次修改');expect(screen.getByRole('button',{name:'保存计划'})).toBeDisabled();expect(h.update).toHaveBeenCalledWith('p1','c1',expect.objectContaining({version:4,notes:'保留这次修改'}));expect(h.update.mock.calls[0][2]).not.toHaveProperty('task_id')
})
it('previews generation before saving and binds the confirmed body to its token',async()=>{
 h.preview.mockResolvedValue({proposals:[{...cell(),kind:'other'}],warnings:['缺少发车日期的阶段未生成'],preview_token:'preview-sha'});show();fireEvent.click(await screen.findByRole('button',{name:'生成初稿'}))
 await waitFor(()=>expect(screen.getByRole('combobox',{name:'现场工作关键事件'})).toBeEnabled());fireEvent.mouseDown(screen.getByRole('combobox',{name:'现场工作关键事件'}));fireEvent.click(await screen.findByText('发车前倒推'));fireEvent.click(screen.getByRole('button',{name:'预览初稿'}))
 await screen.findByText('缺少发车日期的阶段未生成');expect(h.draft).not.toHaveBeenCalled();fireEvent.click(screen.getByRole('button',{name:'保存为草稿'}))
 await waitFor(()=>expect(h.draft).toHaveBeenCalledWith('p1',{phase_rules:[{phase_id:'phase',anchor:'before_ship',offset_weeks:0,mode:'finish'}],preview_token:'preview-sha'}))
})
it('shows failed reads as unknown without empty-plan statistics',async()=>{
 h.list.mockRejectedValueOnce(new Error('当前不可读取'));show();expect(await screen.findByText('周计划暂不可读取')).toBeVisible();expect(screen.queryByText(/已发布 0/)).toBeNull();expect(screen.queryByRole('button',{name:'新增计划格'})).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'重试读取'}));expect(await screen.findByRole('region',{name:'周计划表'})).toBeVisible()
})
it('ignores a late response for the previous project',async()=>{
 let old!:(v:any)=>void;h.list.mockImplementationOnce(()=>new Promise(resolve=>{old=resolve})).mockResolvedValue(fixture({work_items:[],cells:[]}));const view=show();view.rerender(page({...project,id:'p2',name:'第二项目'}))
 await screen.findByText('本范围尚无工作项，请先在计划的工作项页维护');await act(async()=>old(fixture()));expect(screen.queryByText('接线核对')).toBeNull()
})
it('requests cancelled plans explicitly for management and keeps their original state',async()=>{
 show();const toggle=await screen.findByRole('switch',{name:'显示已取消计划格'});h.list.mockResolvedValueOnce(fixture({cells:[cell('c1',{is_cancelled:true})]}));fireEvent.click(toggle)
 await waitFor(()=>expect(h.list).toHaveBeenLastCalledWith('p1',expect.any(String),6,true));expect(await screen.findByText('已取消')).toBeVisible();expect(screen.queryByRole('checkbox',{name:'选择接线核对 '+start+' 本工作项'})).toBeNull()
})

it('marks explicit rest days and holidays while keeping a makeup weekend as work',async()=>{
 h.list.mockResolvedValue(fixture({settings:{rest_mode:'two',rest_days:['2026-10-28'],skip_holidays:true},weeks:[{week_start:start,week_end:'2026-11-01',holiday_days:['2026-10-30'],makeup_workdays:['2026-10-31'],missing_holiday_years:[]}]}));show()
 expect(await screen.findByText('项目休息日：10-28、10-30、11-01')).toBeVisible();expect(screen.getByText('补班：10-31')).toBeVisible()
})
it('refuses an incomplete draft preview without enabling its confirmation',async()=>{
 h.preview.mockResolvedValue({proposals:[],warnings:[]});show();fireEvent.click(await screen.findByRole('button',{name:'生成初稿'}));await waitFor(()=>expect(screen.getByRole('combobox',{name:'现场工作关键事件'})).toBeEnabled());fireEvent.mouseDown(screen.getByRole('combobox',{name:'现场工作关键事件'}));fireEvent.click(await screen.findByText('发车前倒推'));fireEvent.click(screen.getByRole('button',{name:'预览初稿'}))
 await waitFor(()=>expect(screen.getByText('初稿响应不完整，请重新预览')).toBeVisible());expect(screen.getByRole('button',{name:'保存为草稿'})).toBeDisabled();expect(h.draft).not.toHaveBeenCalled()
})

it('uses source-based default rules and still requires preview before draft creation',async()=>{
 h.defaultRules.mockResolvedValue({rules:[{phase_id:'phase',anchor:'before_ship',offset_weeks:1,mode:'finish'}],suggestions:[{phase_id:'phase',phase_name:'现场工作',anchor:'before_ship',offset_weeks:1,mode:'finish',source_phase_id:'phase-01',source_label:'标准模板：进场准备',window_start:'2026-10-19',window_end:'2026-10-25',week_start:'2026-10-19',reason:'按模板来源安排在发车周之前'}],warnings:['自建阶段需要手工选择规则']});h.preview.mockResolvedValue({proposals:[cell()],warnings:[],preview_token:'verified-preview'});show()
 fireEvent.click(await screen.findByRole('button',{name:'生成初稿'}));await waitFor(()=>expect(screen.getByText('自建阶段需要手工选择规则')).toBeVisible());expect(screen.getByRole('button',{name:'保存为草稿'})).toBeDisabled();expect(h.draft).not.toHaveBeenCalled()
 fireEvent.click(screen.getByText('查看初始建议的来源、窗口与理由'));expect(screen.getByText('标准模板：进场准备')).toBeVisible();expect(screen.getByText('按模板来源安排在发车周之前')).toBeVisible()
 fireEvent.click(screen.getByRole('button',{name:'预览初稿'}));await waitFor(()=>expect(h.preview).toHaveBeenCalledWith('p1',{phase_rules:[{phase_id:'phase',anchor:'before_ship',offset_weeks:1,mode:'finish'}]}));await waitFor(()=>expect(screen.getByRole('button',{name:'保存为草稿'})).toBeEnabled());fireEvent.click(screen.getByRole('button',{name:'保存为草稿'}));await waitFor(()=>expect(h.draft).toHaveBeenCalledWith('p1',{phase_rules:[{phase_id:'phase',anchor:'before_ship',offset_weeks:1,mode:'finish'}],preview_token:'verified-preview'}))
})
it('preserves manual generation when default-rule reads fail',async()=>{
 h.defaultRules.mockRejectedValueOnce(new Error('建议暂不可读取'));show();fireEvent.click(await screen.findByRole('button',{name:'生成初稿'}));await waitFor(()=>expect(screen.getByText(/默认初稿建议暂不可读取/)).toBeVisible());await waitFor(()=>expect(screen.getByRole('combobox',{name:'现场工作关键事件'})).toBeEnabled());expect(screen.getByRole('button',{name:'重新读取初稿建议'})).toBeEnabled();expect(screen.getByRole('button',{name:'保存为草稿'})).toBeDisabled()
})

it('requires an explicit source review and reason to resolve uncertain legacy plan intent',async()=>{
 h.list.mockResolvedValue(fixture({cells:[cell('legacy',{intent_review_required:true,published:true,completion:{...cell().completion,state:'unknown',is_complete:false,overdue:false}})]}));show();expect(await screen.findByText('原计划意图待核对')).toBeVisible();fireEvent.click(screen.getByRole('button',{name:'编辑接线核对 '+start+' 本工作项'}));await waitFor(()=>expect(screen.getByText('旧计划的完成意图待核对')).toBeVisible());expect(screen.getByRole('button',{name:'保存计划'})).toBeDisabled()
 fireEvent.click(screen.getByRole('checkbox',{name:'已核对原始来源，按本次填写重新定义计划'}));expect(screen.getByRole('button',{name:'保存计划'})).toBeDisabled();fireEvent.change(screen.getByLabelText('旧计划意图核对理由'),{target:{value:'按原始会议记录重新明确本周进行中'}});fireEvent.mouseDown(screen.getByRole('combobox',{name:'计划方式'}));fireEvent.click(await screen.findByText('本周进行中'));fireEvent.click(screen.getByRole('button',{name:'保存计划'}))
 await waitFor(()=>expect(h.update).toHaveBeenCalledWith('p1','legacy',expect.objectContaining({version:4,mode:'in_progress',target_count:null,confirm_intent:true,reason:'按原始会议记录重新明确本周进行中'})))
})
