import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { ConfigProvider } from 'antd'
import { ProjectCapabilitiesContext, ProjectStatusContext } from '../../../hooks/useProjectCapability'
const h=vi.hoisted(()=>({preview:vi.fn(),transfer:vi.fn(),navigate:vi.fn(),reload:vi.fn(),user:{id:'pm',role:'pm'}}))
vi.mock('../../../stores/auth',()=>({useAuth:()=>({user:h.user})}))
vi.mock('react-router-dom',()=>({useNavigate:()=>h.navigate}))
vi.mock('../../../api/projectTransfer',()=>({projectTransferApi:{preview:h.preview,transfer:h.transfer}}))
import ProjectOwnerPanel from './ProjectOwnerPanel'
const preview={project_id:'p1',version:3,current_manager:{id:'pm',name:'原经理'},candidates:[{id:'next',name:'李经理'}],removed:[{user_id:'pm',name:'原经理',documents:[{code:'6.7',name:'工作交接',required:true}]}]}
function show(id='p1') {return render(<ConfigProvider theme={{token:{motion:false}}}><ProjectStatusContext.Provider value="ready"><ProjectCapabilitiesContext.Provider value={['project.update','project.manage_members']}><ProjectOwnerPanel project={{id,manager:'pm',manager_name:'原经理',status:'ready'} as any} onReload={h.reload}/></ProjectCapabilitiesContext.Provider></ProjectStatusContext.Provider></ConfigProvider>)}
async function fill(){fireEvent.click(screen.getByRole('button',{name:'更换负责人'}));await screen.findByText('原经理 将离开当前项目职责范围');fireEvent.mouseDown(screen.getByRole('combobox',{name:'新项目负责人'}));fireEvent.click(await screen.findByText('李经理'));fireEvent.change(screen.getByLabelText('更换负责人理由'),{target:{value:'现场负责人交接调整'}})}
beforeEach(()=>{vi.resetAllMocks();h.user={id:'pm',role:'pm'};h.preview.mockResolvedValue(preview);h.transfer.mockResolvedValue({id:'p1',viewer_retains_access:true})})
it('requires the concrete departure acknowledgement and guards duplicate saving',async()=>{
 let finish!:(value:unknown)=>void;h.transfer.mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve}));show();await fill()
 const save=screen.getByRole('button',{name:'保存负责人'});expect(save).toBeDisabled()
 fireEvent.click(screen.getByRole('checkbox',{name:'已核对原经理的离场资料安排'}));fireEvent.click(save);fireEvent.click(save)
 await waitFor(()=>expect(h.transfer).toHaveBeenCalledOnce());expect(h.transfer).toHaveBeenCalledWith('p1',preview,'next','现场负责人交接调整',['pm'])
 await act(async()=>finish({id:'p1',viewer_retains_access:true}));expect(h.reload).toHaveBeenCalledOnce()
})
it('preserves the reason after a stale response and requires a fresh snapshot and acknowledgement',async()=>{
 h.transfer.mockRejectedValueOnce({response:{status:409,data:{detail:'项目已变化'}}});show();await fill();fireEvent.click(screen.getByRole('checkbox'))
 fireEvent.click(screen.getByRole('button',{name:'保存负责人'}));expect(await screen.findByText('当前预览已失效，请重新核对后保存')).toBeVisible()
 expect(screen.getByLabelText('更换负责人理由')).toHaveValue('现场负责人交接调整');expect(screen.getByRole('button',{name:'保存负责人'})).toBeDisabled()
 h.preview.mockResolvedValueOnce({...preview,version:4});fireEvent.click(screen.getByRole('button',{name:'重新核对'}))
 await waitFor(()=>expect(h.preview).toHaveBeenCalledTimes(2));expect(screen.getByRole('checkbox')).not.toBeChecked()
 fireEvent.click(screen.getByRole('checkbox'));await waitFor(()=>expect(screen.getByRole('button',{name:'保存负责人'})).toBeEnabled())
 fireEvent.click(screen.getByRole('button',{name:'保存负责人'}));await waitFor(()=>expect(h.transfer).toHaveBeenLastCalledWith('p1',expect.objectContaining({version:4}),'next','现场负责人交接调整',['pm']))
})
it('returns a departing viewer to the list when the server reports access ended',async()=>{
 h.transfer.mockResolvedValueOnce({id:'p1',viewer_retains_access:false});show();await fill();fireEvent.click(screen.getByRole('checkbox'));fireEvent.click(screen.getByRole('button',{name:'保存负责人'}))
 await waitFor(()=>expect(h.navigate).toHaveBeenCalledWith('/pm/projects',{replace:true}));expect(h.reload).not.toHaveBeenCalled()
})
it('does not offer the action to an ordinary co-manager',()=>{
 h.user={id:'co-manager',role:'pm'};show();expect(screen.queryByRole('button',{name:'更换负责人'})).toBeNull();expect(h.preview).not.toHaveBeenCalled()
 expect(screen.getByText('仅当前负责人或管理员可更换负责人')).toBeVisible()
})
it('does not accept a preview for another project',async()=>{
 h.preview.mockResolvedValueOnce({...preview,project_id:'other'});show();fireEvent.click(screen.getByRole('button',{name:'更换负责人'}))
 await waitFor(()=>expect(screen.getByText('负责人预览不属于当前项目，请重新读取')).toBeVisible());expect(screen.getByRole('button',{name:'保存负责人'})).toBeDisabled();expect(h.transfer).not.toHaveBeenCalled()
})
