import { beforeEach,expect,it,vi } from 'vitest'
import { fireEvent,render,screen,waitFor } from '@testing-library/react'
import WorkerProjectsPage from './WorkerProjectsPage'
const mocks=vi.hoisted(()=>({list:vi.fn(),navigate:vi.fn()}))
vi.mock('react-router-dom',()=>({useNavigate:()=>mocks.navigate}))
vi.mock('../../api',()=>({projectApi:{list:mocks.list}}))
vi.mock('../../stores/auth',()=>({useAuth:()=>({user:{role:'worker',id:'u',permission_overrides:{'project.read':true}}})}))
beforeEach(()=>{vi.clearAllMocks();mocks.list.mockResolvedValue([{id:'p1',name:'可见现场',client:'客户',location:'地点',status:'executing',vehicle_progress:{percent:40}}])})
it('从project.read列表读取车辆进度，不依赖工作台权限',async()=>{
 render(<WorkerProjectsPage/>);expect(await screen.findByText('40%')).toBeVisible();expect(screen.getByRole('link',{name:'进入本周'})).toHaveAttribute('href','/worker/week');fireEvent.click(screen.getByRole('button',{name:'查看项目：可见现场'}));expect(mocks.navigate).toHaveBeenCalledWith('/worker/projects/p1')
})
it('未知进度不显示0，列表失败可重试',async()=>{
 mocks.list.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce([{id:'p1',name:'可见现场',status:'executing',vehicle_progress:{percent:null}}]);render(<WorkerProjectsPage/>);expect(await screen.findByText('项目暂时无法加载')).toBeVisible();fireEvent.click(screen.getByRole('button',{name:'重新加载'}));expect(await screen.findByText('进度暂不可用')).toBeVisible();await waitFor(()=>expect(mocks.list).toHaveBeenCalledTimes(2))
})
