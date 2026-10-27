import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {act,fireEvent,screen,waitFor,within} from '@testing-library/react'
import {Modal,ConfigProvider} from 'antd'
const h=vi.hoisted(()=>({get:vi.fn()}))
vi.mock('./client',()=>({api:{get:h.get}}))
import {confirmMemberRemoval} from './memberRemoval'
beforeEach(()=>{ConfigProvider.config({holderRender:children=><ConfigProvider theme={{token:{motion:false}}}>{children}</ConfigProvider>})})
afterEach(()=>{act(()=>Modal.destroyAll());ConfigProvider.config({holderRender:undefined});vi.clearAllMocks()})
const preview={warning:'离开项目前请完成文档交接',removed:[{user_id:'a',name:'张工',documents:[{code:'6.7',name:'项目人员文档留存',required:true}]},{user_id:'b',name:'李工',documents:[{code:'6.7',name:'项目人员文档留存',required:true}]}]}
it('shows every real removed member and requires a separate acknowledgement before returning IDs',async()=>{
  h.get.mockResolvedValue({data:preview});let result:Promise<string[]|undefined>
  await act(async()=>{result=confirmMemberRemoval('p1',['a','b'])})
  const modal=within(await screen.findByRole('dialog'))
  await waitFor(()=>{expect(modal.getByText('张工')).toBeVisible();expect(modal.getByText('李工')).toBeVisible()})
  expect(modal.getAllByText(/6.7 项目人员文档留存/)).toHaveLength(2)
  fireEvent.click(modal.getByRole('button',{name:'已核对，确认移出'}))
  expect(await result!).toEqual(['a','b'])
  expect(h.get).toHaveBeenCalledWith('/projects/p1/members/removal-preview?removed_ids=a&removed_ids=b',{signal:undefined})
})
it('cancel or leaving the project does not confirm removal',async()=>{
  h.get.mockResolvedValue({data:preview});const controller=new AbortController();let result:Promise<string[]|undefined>
  await act(async()=>{result=confirmMemberRemoval('p1',['a','b'],controller.signal)})
  await screen.findByRole('dialog');act(()=>controller.abort())
  expect(await result!).toBeUndefined()
  await waitFor(()=>expect(screen.queryByRole('dialog')).toBeNull())
})
it('adding members needs no removal preview',async()=>{
  expect(await confirmMemberRemoval('p1',[])).toEqual([]);expect(h.get).not.toHaveBeenCalled()
})
