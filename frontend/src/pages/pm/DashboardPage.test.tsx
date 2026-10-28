import {act,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {beforeEach,expect,it,vi} from 'vitest'
import {MemoryRouter} from 'react-router-dom'
const h=vi.hoisted(()=>({overview:vi.fn(),statistics:vi.fn(),user:{id:'a',role:'pm',permission_version:1,permission_overrides:{} as Record<string,boolean>}}))
vi.mock('../../stores/auth',()=>({useAuth:()=>({user:h.user})}))
vi.mock('../../api/workbench',async original=>({...await original<typeof import('../../api/workbench')>(),workbenchApi:{overview:h.overview,statistics:h.statistics}}))
const w=vi.hoisted(()=>({issues:vi.fn(),week:vi.fn()}))
vi.mock('../../api/client',async original=>({...await original<typeof import('../../api/client')>(),api:{get:w.issues}}))
vi.mock('../../api/fieldWeek',()=>({fieldWeekApi:{week:w.week}}))
import DashboardPage from './DashboardPage'
const doc={id:'d1',document_id:'d1',project_id:'p1',project_name:'项目甲',code:'6.2',name:'本周生命周期表',due_at:'2026-10-27T12:00:00Z',due_is_estimated:false,timezone:'Asia/Shanghai',vehicle_label:'',overdue_days:1}
const overview={projects:[{id:'p1',name:'项目甲',status:'executing',percent:70,vehicle_progress:{target:125,completed:50,quantity_unknown:false,percent:40},document_attention:{overdue:[doc],overdue_count:1,timezone:'Asia/Shanghai'},next_signoff:{...doc,id:'sign',code:'6.10.1',name:'到货签收单'}}],this_week_documents:[doc],weekly_plan:{state:'unavailable',count:null,items:null}}
const statistics={projects:1,active_projects:1,completed_projects:0,status_distribution:[],vehicle_progress:{target:125,completed:50,quantity_unknown:false,percent:40},documents:{this_week_count:1,overdue_count:1},issues:{open:0,critical:0}}
const show=()=>render(<MemoryRouter><DashboardPage/></MemoryRouter>)
beforeEach(()=>{vi.resetAllMocks();h.user={id:'a',role:'pm',permission_version:1,permission_overrides:{}};h.overview.mockResolvedValue(overview);h.statistics.mockResolvedValue(statistics)
 w.issues.mockResolvedValue({data:{items:[]}});w.week.mockResolvedValue({state:'available',plans:[],unassigned:[],assistable:[],vehicle_matrices:{},this_week_documents:[],my_issues:[],windows:{},warnings:[],permissions:{record:true,upload:true,issues:true}})})
it('shows current document, vehicle and next-signoff facts with safe deep links',async()=>{
 show();expect(await screen.findByText('50/125 个车辆环节')).toBeVisible()
 expect(screen.getByText('现场实施')).toBeVisible();expect(screen.getByText(/本周计划暂不可读取/)).toBeVisible()
 const links=screen.getAllByRole('link',{name:'6.2 本周生命周期表'});expect(links.every(link=>link.getAttribute('href')==='/pm/projects/p1/documents?document=d1')).toBe(true)
 expect(screen.getByRole('link',{name:'6.10.1 到货签收单'})).toHaveAttribute('href','/pm/projects/p1/documents?document=sign')
 expect(screen.queryByText(/耗时|今日填报|下达日程/)).toBeNull();expect(h.statistics).not.toHaveBeenCalled()
 fireEvent.click(screen.getByText('统计'));await waitFor(()=>expect(h.statistics).toHaveBeenCalledOnce())
})
it('supports the independent statistics permission without reading the workbench',async()=>{
 h.user.permission_overrides={'workspace.view':false,'insights.view':true};show()
 expect(await screen.findByText(/已完成 50 \/ 125 个车辆环节/)).toBeVisible();expect(h.overview).not.toHaveBeenCalled()
 expect(h.statistics).toHaveBeenCalledOnce();expect(screen.queryByText('项目甲')).toBeNull()
})
it('does not load denied statistics even when workspace reading is allowed',async()=>{
 h.user.permission_overrides={'insights.view':false};show();await screen.findByText('我的项目')
 expect(screen.queryByText('统计')).toBeNull();expect(h.statistics).not.toHaveBeenCalled()
})
it('does not display successful zero counts after a read failure',async()=>{
 h.overview.mockRejectedValue(new Error('read failed'));show();expect(await screen.findByText('工作台暂不可读取')).toBeVisible()
 expect(screen.queryByText('暂无需要处理的事项')).toBeNull();expect(screen.queryByText('需要处理')).toBeNull()
})
it('hides the previous account immediately and ignores its delayed response',async()=>{
 let finish!:(value:typeof overview)=>void;h.overview.mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve})).mockResolvedValue({projects:[],this_week_documents:[],weekly_plan:{state:'available',count:0,items:[],unknown_count:0,unknown_items:[]}})
 const view=show();h.user={...h.user,id:'b'};view.rerender(<MemoryRouter><DashboardPage/></MemoryRouter>)
 expect(await screen.findByText('暂无需要处理的事项')).toBeVisible();await act(async()=>finish(overview));expect(screen.queryByText('项目甲')).toBeNull()
})
it('keeps partially unread document and signoff states unknown',async()=>{
 h.overview.mockResolvedValue({projects:[{id:'p1',name:'项目甲',status:'preparing'}]});show()
 expect(await screen.findByText('逾期资料尚未完整读取。')).toBeVisible();expect(screen.getByText('签单状态尚未完整读取。')).toBeVisible()
 expect(screen.getByText('车辆进度未读取')).toBeVisible();expect(screen.queryByText('暂无需要处理的事项')).toBeNull()
})
it('lists overdue and unverified published weekly plan cells from the real contract',async()=>{
 const cell={id:'c1',project_id:'p1',project_name:'项目甲',task_id:'t1',name:'场地勘测',week_start:'2026-10-19',state:'incomplete',url:'/pm/projects/p1/plan?view=weeks&week=2026-10-19&cell=c1'}
 h.overview.mockResolvedValue({...overview,weekly_plan:{state:'available',count:1,items:[cell],unknown_count:1,unknown_items:[{...cell,id:'c2',name:'多车联调'}]}});show()
 expect(await screen.findByRole('link',{name:'场地勘测'})).toHaveAttribute('href',cell.url)
 expect(screen.getByText('已逾期未完成')).toBeVisible();expect(screen.getByText('完成情况待核对')).toBeVisible()
 expect(screen.queryByText(/本周计划暂不可读取/)).toBeNull()
})
it('shows an empty weekly attention state instead of an error when nothing is overdue',async()=>{
 h.overview.mockResolvedValue({...overview,weekly_plan:{state:'available',count:0,items:[],unknown_count:0,unknown_items:[]}});show()
 fireEvent.click(await screen.findByRole('button',{name:'周计划 0'}));expect(screen.getByText('暂无周计划待处理')).toBeVisible();expect(screen.queryByText(/本周计划暂不可读取/)).toBeNull()
})

it('merges documents, weekly plan, issues and signoffs into one filterable list, with my week beside it',async()=>{
 w.issues.mockResolvedValue({data:{items:[{id:'i1',title:'急停后无法复位',project_id:'p1',project_name:'项目甲',status:'open',severity:'high',assignee_id:null,assignee_name:''},{id:'i2',title:'他人处理中',project_id:'p1',project_name:'项目甲',status:'open',severity:'low',assignee_id:'other',assignee_name:'乙'}]}})
 w.week.mockResolvedValue({state:'available',plans:[{id:'cell',project_id:'p1',project_name:'项目甲',mode:'finish',work_item:{name:'场地勘测',phase_name:'进场准备',check_items:[{id:'c'}]}}],unassigned:[],assistable:[],vehicle_matrices:{},this_week_documents:[],my_issues:[],windows:{},warnings:[],permissions:{record:true,upload:true,issues:true}})
 show()
 expect(await screen.findByRole('link',{name:'急停后无法复位'})).toHaveAttribute('href','/pm/projects/p1/issues')
 expect(screen.queryByText('他人处理中')).toBeNull()
 expect(screen.getByRole('button',{name:'全部 3'})).toHaveAttribute('aria-pressed','true')
 fireEvent.click(screen.getByRole('button',{name:'问题 1'}))
 expect(screen.queryByRole('link',{name:'6.2 本周生命周期表'})).toBeNull();expect(screen.getByRole('link',{name:'急停后无法复位'})).toBeVisible()
 expect(await screen.findByText('场地勘测')).toBeVisible();expect(screen.getByRole('link',{name:'去登记'})).toHaveAttribute('href','/worker/week')
})
it('keeps the list honest when issues cannot be read',async()=>{
 w.issues.mockRejectedValue(new Error('offline'));h.overview.mockResolvedValue({projects:[],this_week_documents:[],weekly_plan:{state:'available',count:0,items:[],unknown_count:0,unknown_items:[]}});show()
 expect(await screen.findByText('问题尚未读取。')).toBeVisible();expect(screen.queryByText('暂无需要处理的事项')).toBeNull()
})
