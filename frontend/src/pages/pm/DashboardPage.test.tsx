import {act,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {beforeEach,expect,it,vi} from 'vitest'
import {MemoryRouter} from 'react-router-dom'
const h=vi.hoisted(()=>({overview:vi.fn(),statistics:vi.fn(),user:{id:'a',role:'pm',permission_version:1,permission_overrides:{} as Record<string,boolean>}}))
vi.mock('../../stores/auth',()=>({useAuth:()=>({user:h.user})}))
vi.mock('../../api/workbench',async original=>({...await original<typeof import('../../api/workbench')>(),workbenchApi:{overview:h.overview,statistics:h.statistics}}))
import DashboardPage from './DashboardPage'
const doc={id:'d1',document_id:'d1',project_id:'p1',project_name:'项目甲',code:'6.2',name:'本周生命周期表',due_at:'2026-10-27T12:00:00Z',due_is_estimated:false,timezone:'Asia/Shanghai',vehicle_label:'',overdue_days:1}
const overview={projects:[{id:'p1',name:'项目甲',status:'executing',percent:70,vehicle_progress:{target:125,completed:50,quantity_unknown:false,percent:40},document_attention:{overdue:[doc],overdue_count:1,timezone:'Asia/Shanghai'},next_signoff:{...doc,id:'sign',code:'6.10.1',name:'到货签收单'}}],this_week_documents:[doc],weekly_plan:{state:'unavailable',count:null,items:null}}
const statistics={projects:1,active_projects:1,completed_projects:0,status_distribution:[],vehicle_progress:{target:125,completed:50,quantity_unknown:false,percent:40},documents:{this_week_count:1,overdue_count:1},issues:{open:0,critical:0}}
const show=()=>render(<MemoryRouter><DashboardPage/></MemoryRouter>)
beforeEach(()=>{vi.resetAllMocks();h.user={id:'a',role:'pm',permission_version:1,permission_overrides:{}};h.overview.mockResolvedValue(overview);h.statistics.mockResolvedValue(statistics)})
it('shows current document, vehicle and next-signoff facts with safe deep links',async()=>{
 show();expect(await screen.findByText('50/125 个车辆环节')).toBeVisible()
 expect(screen.getByText('现场实施')).toBeVisible();expect(screen.getByText('本周计划暂不可读取')).toBeVisible()
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
 h.user.permission_overrides={'insights.view':false};show();await screen.findByText('项目与车辆进度')
 expect(screen.queryByText('统计')).toBeNull();expect(h.statistics).not.toHaveBeenCalled()
})
it('does not display successful zero counts after a read failure',async()=>{
 h.overview.mockRejectedValue(new Error('read failed'));show();expect(await screen.findByText('工作台暂不可读取')).toBeVisible()
 expect(screen.queryByText('暂无逾期资料')).toBeNull();expect(screen.queryByText('本周暂无待交资料')).toBeNull()
})
it('hides the previous account immediately and ignores its delayed response',async()=>{
 let finish!:(value:typeof overview)=>void;h.overview.mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve})).mockResolvedValue({projects:[],this_week_documents:[],weekly_plan:{state:'ready',count:0,items:[]}})
 const view=show();h.user={...h.user,id:'b'};view.rerender(<MemoryRouter><DashboardPage/></MemoryRouter>)
 expect(await screen.findByText('本周暂无待交资料')).toBeVisible();await act(async()=>finish(overview));expect(screen.queryByText('项目甲')).toBeNull()
})
it('keeps partially unread document and signoff states unknown',async()=>{
 h.overview.mockResolvedValue({projects:[{id:'p1',name:'项目甲',status:'ready'}]});show()
 expect(await screen.findByText('逾期资料尚未完整读取')).toBeVisible();expect(screen.getByText('签单状态尚未完整读取')).toBeVisible()
 expect(screen.getByText('车辆进度未读取')).toBeVisible();expect(screen.queryByText('暂无逾期资料')).toBeNull()
})
