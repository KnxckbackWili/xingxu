import { expect,it,vi } from 'vitest'
import { render,screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import MyPage from './MyPage'
vi.mock('./RecordsPage',()=>({default:()=> <div>实际记录面板</div>}))
vi.mock('../../api/client',()=>({api:{get:vi.fn().mockResolvedValue({data:{records:[],summary:{actual_records:0,completed:0,assisted:0}}})},errMsg:()=> '读取失败'}))
vi.mock('../../stores/auth',()=>({useAuth:()=>({user:{id:'worker',role:'worker',system_permissions:['personal.records.read']}})}))
it('旧统计深链显示按周实际记录，返回本周入口',async()=>{
 render(<MemoryRouter initialEntries={['/worker/my?tab=stats']}><MyPage/></MemoryRouter>);expect(screen.getByText('实际记录面板')).toBeVisible();expect(await screen.findByText('当周没有实际记录')).toBeVisible();expect(screen.getByRole('link',{name:'返回本周'})).toHaveAttribute('href','/worker/week');expect(screen.queryByRole('tab',{name:'个人统计'})).not.toBeInTheDocument()
})
