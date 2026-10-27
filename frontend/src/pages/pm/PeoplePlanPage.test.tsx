import { beforeEach,expect,it,vi } from 'vitest'
import { render,screen,waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import PeoplePlanPage from './PeoplePlanPage'
const mocks=vi.hoisted(()=>({get:vi.fn(),actor:{id:'pm',role:'pm',permission_overrides:{} as Record<string,boolean>}}))
vi.mock('../../api/client',()=>({api:{get:mocks.get},errMsg:()=> '周计划读取失败'}))
vi.mock('../../api',()=>({availabilityApi:{createUnavailability:vi.fn()}}))
vi.mock('../../stores/auth',()=>({useAuth:()=>({user:mocks.actor})}))
vi.mock('../../components/UnavailabilityManager',()=>({default:()=>null}))
const data={state:'ready',week_start:'2026-10-26',weeks:4,people:[{id:'worker1',name:'现场同事',cells:[{id:'c1',project_id:'p1',project_name:'当前项目',task_name:'实际工作',week_start:'2026-10-26',mode:'in_progress',target_count:null}],unavailable:[{start_date:'2026-10-27',end_date:'2026-10-28'}],conflicts:[{week_start:'2026-10-26',project_ids:['p1','p2']}]}],warnings:[],calendar:[],permissions:{manage_unavailability:false}}
beforeEach(()=>{vi.clearAllMocks();mocks.actor.permission_overrides={};mocks.get.mockResolvedValue({data})})
it('按周展示真实项目、不可用时段及跨项目冲突，不显示日负荷',async()=>{
 render(<MemoryRouter><PeoplePlanPage/></MemoryRouter>);expect(await screen.findByText('当前项目')).toBeVisible();expect(screen.getByText('同周多个项目安排，请核对')).toBeVisible();expect(screen.getByText(/不可用 2026-10-27/)).toBeVisible();expect(screen.queryByText('可用工时')).not.toBeInTheDocument();expect(screen.queryByRole('button',{name:'登记不可用时段'})).not.toBeInTheDocument()
})
it('本人深链和只有个人权限时不请求团队范围',async()=>{
 mocks.actor.permission_overrides={'workspace.view':false,'personal.schedule.read':true};render(<MemoryRouter initialEntries={['/pm/people?view=mine']}><PeoplePlanPage/></MemoryRouter>);await waitFor(()=>expect(mocks.get).toHaveBeenCalledWith('/people/weeks',{params:{scope:'mine',weeks:4},headers:{'X-AGV-Expected-Account':'pm'}}));expect(screen.queryByText('团队周计划')).not.toBeInTheDocument()
})
it('读取失败与缺节假日年份明确提示，不显示假空安排',async()=>{
 mocks.get.mockResolvedValue({data:{...data,state:'unavailable',people:[],warnings:[{message:'周计划尚未读取'}],calendar:[{missing_holiday_years:[2030]}]}});render(<MemoryRouter><PeoplePlanPage/></MemoryRouter>);expect(await screen.findByText('周计划尚未读取')).toBeVisible();expect(screen.getByText('缺少年度节假日数据：2030')).toBeVisible();expect(screen.getByText('周计划状态未知')).toBeVisible()
})
