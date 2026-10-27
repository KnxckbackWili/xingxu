import { beforeEach,expect,it,vi } from 'vitest'
import { fireEvent,render,screen,waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import WorkerProjectDetailPage from './WorkerProjectDetailPage'
const mocks=vi.hoisted(()=>({get:vi.fn(),project:vi.fn(),documents:vi.fn(),download:vi.fn()}))
vi.mock('react-router-dom',async()=>({...await vi.importActual('react-router-dom'),useParams:()=>({projectId:'p1'})}))
vi.mock('../../api/client',()=>({api:{get:mocks.get},errMsg:()=> '无权查看'}))
vi.mock('../../api',()=>({projectApi:{get:mocks.project}}))
vi.mock('../../api/projectDocuments',()=>({projectDocumentsApi:{list:mocks.documents},downloadDocumentResource:mocks.download}))
beforeEach(()=>{vi.clearAllMocks();mocks.project.mockResolvedValue({name:'可见项目',status:'executing'});mocks.get.mockResolvedValue({data:{steps:[],units:[]}});mocks.documents.mockResolvedValue({definitions:[{id:'rule-1',code:'6.2',name:'生命周期表',blank_file_id:'file'}],documents:[]})})
it('只读展示并走有鉴权空白模板下载入口，不读日程',async()=>{
 render(<MemoryRouter><WorkerProjectDetailPage/></MemoryRouter>);fireEvent.click(await screen.findByRole('button',{name:'下载空白模板'}));await waitFor(()=>expect(mocks.download).toHaveBeenCalledWith('/projects/p1/documents/requirements/rule-1/blank-file','6.2-空白模板'));expect(mocks.get.mock.calls.every(([url])=>!url.includes('/schedule')&&!url.includes('/worker/today'))).toBe(true);expect(screen.getByRole('link',{name:'进入本周'})).toHaveAttribute('href','/worker/week?project_id=p1')
})
it('项目读取被拒绝不显示任何已取回资料内容',async()=>{
 mocks.project.mockRejectedValue(new Error('404'));render(<MemoryRouter><WorkerProjectDetailPage/></MemoryRouter>);expect(await screen.findByText('项目信息未能完整读取')).toBeVisible();expect(screen.queryByText('生命周期表')).not.toBeInTheDocument()
})
