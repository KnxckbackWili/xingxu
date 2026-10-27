import { render,screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach,expect,it,vi } from 'vitest'
import MyPage from './MyPage'
const { records,get,actor }=vi.hoisted(()=>({records:vi.fn(()=> 'actual record data'),get:vi.fn(),actor:{user:{id:'u1',role:'worker',system_permissions:[] as string[]}}}))
vi.mock('./RecordsPage',()=>({default:records}))
vi.mock('../../api/client',()=>({api:{get},errMsg:()=> '读取失败'}))
vi.mock('../../stores/auth',()=>({useAuth:()=>({user:actor.user})}))
beforeEach(()=>{vi.clearAllMocks();actor.user.system_permissions=[];get.mockResolvedValue({data:{records:[],summary:{actual_records:0,completed:0,assisted:0}}})})
it('记录权限关闭时不读取本人记录和周报',()=>{
 render(<MemoryRouter><MyPage/></MemoryRouter>);expect(screen.getByText('本人记录查看权限已关闭')).toBeVisible();expect(records).not.toHaveBeenCalled();expect(get).not.toHaveBeenCalled()
})
it('本人记录权限不要求全局统计',async()=>{
 actor.user.system_permissions=['personal.records.read'];render(<MemoryRouter><MyPage/></MemoryRouter>);expect(screen.getByText('actual record data')).toBeVisible();expect(await screen.findByText('当周没有实际记录')).toBeVisible();expect(get).toHaveBeenCalledWith('/worker/week-report',{params:undefined,headers:{'X-AGV-Expected-Account':'u1'}})
})
