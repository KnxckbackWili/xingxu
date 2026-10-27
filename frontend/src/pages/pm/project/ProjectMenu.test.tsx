import {beforeEach,expect,it,vi} from 'vitest'
import {render,screen,fireEvent,within,waitFor} from '@testing-library/react'
import {ProjectMenuContent} from './ProjectMenu'
const h=vi.hoisted(()=>({user:{id:'a',role:'admin',permission_overrides:{} as Record<string,boolean>}}))
vi.mock('../../../stores/auth',()=>({useAuth:()=>({user:h.user})}))
const nav=vi.fn()
function show(overrides:Partial<Parameters<typeof ProjectMenuContent>[0]>={}){return render(<ProjectMenuContent projectId="p1" activeParent="overview" activeChild={null} onNavigate={nav} {...overrides}/>)}
async function more(){fireEvent.click(screen.getByRole('button',{name:'更多'}));return within(await screen.findByRole('dialog'))}
beforeEach(()=>{nav.mockClear();h.user={id:'a',role:'admin',permission_overrides:{}}})
it('shows exactly six daily destinations and More on every viewport',async()=>{
 const view=show();const common=within(screen.getByRole('navigation',{name:'项目常用功能'}))
 expect(common.getAllByRole('button').map(button=>button.textContent)).toEqual(['概况','资料','车辆','计划','问题','现场','更多'])
 expect(view.container.querySelector('.project-navigation-sidebar')).toBeNull()
 const extra=await more();for(const label of ['报告','操作记录','导出','项目设置'])expect(extra.getByRole('button',{name:label})).toBeVisible()
 for(const old of ['任务','日程','人员','开工向导'])expect(screen.queryByRole('button',{name:old})).toBeNull()
})
it('keeps vehicle progress separate from field inventory and contacts',()=>{
 const view=show({activeParent:'vehicles'});expect(screen.getByRole('button',{name:'车辆'})).toHaveAttribute('aria-current','page')
 expect(screen.queryByRole('navigation',{name:'现场内容'})).toBeNull()
 view.rerender(<ProjectMenuContent projectId="p1" activeParent="field" activeChild="inventory" onNavigate={nav}/>)
 const field=within(screen.getByRole('navigation',{name:'现场内容'}));expect(field.getAllByRole('button').map(button=>button.textContent)).toEqual(['物品','联系人'])
 fireEvent.click(field.getByRole('button',{name:'联系人'}));expect(nav).toHaveBeenLastCalledWith('/pm/projects/p1/handover')
})
it.each([['概况','overview'],['资料','documents'],['车辆','vehicles'],['计划','plan'],['问题','issues'],['现场','inventory']])('navigates %s to its current location',(name,path)=>{show();fireEvent.click(screen.getByRole('button',{name}));expect(nav).toHaveBeenCalledWith(`/pm/projects/p1/${path}`)})
it('keeps readable settings while export and audit remain separately authorized',async()=>{
 h.user={id:'a',role:'worker',permission_overrides:{'system.audit.read':false}}
 show({capabilities:[]});const extra=await more()
 expect(extra.getByRole('button',{name:'项目设置'})).toBeVisible();expect(extra.queryByRole('button',{name:'导出'})).toBeNull();expect(extra.queryByRole('button',{name:'操作记录'})).toBeNull()
})
it('does not clear search when navigation is blocked and closes only after a committed route',async()=>{
 const view=show({navigationKey:'/pm/projects/p1/documents',activeParent:'delivery'})
 const extra=await more();fireEvent.change(extra.getByRole('textbox',{name:'查找项目功能'}),{target:{value:'项目设置'}})
 fireEvent.click(extra.getByRole('button',{name:'项目设置'}));expect(nav).toHaveBeenCalledWith('/pm/projects/p1/edit')
 expect(screen.getByRole('dialog')).toBeVisible();expect(extra.getByRole('textbox')).toHaveValue('项目设置')
 view.rerender(<ProjectMenuContent projectId="p1" activeParent="overview" activeSpecial="edit" activeChild={null} onNavigate={nav} navigationKey="/pm/projects/p1/edit"/>)
 await waitFor(()=>expect(screen.queryByRole('dialog')).toBeNull())
})
it('does not retain old search aliases',async()=>{
 show();const extra=await more();fireEvent.change(extra.getByRole('textbox'),{target:{value:'甘特图'}})
 expect(extra.getByText('没有找到功能，请按名称或用途查找。')).toBeVisible()
})
it('owns the project keyboard shortcut, restores More focus, and leaves modals alone',async()=>{
 show();const fallback=vi.fn((event:KeyboardEvent)=>{if(!event.defaultPrevented)called()});const called=vi.fn();window.addEventListener('keydown',fallback)
 try{
  fireEvent.keyDown(window,{key:'k',metaKey:true});await screen.findByRole('textbox',{name:'查找项目功能'});expect(called).not.toHaveBeenCalled()
  fireEvent.keyDown(window,{key:'Escape'});await waitFor(()=>expect(screen.getByRole('button',{name:'更多'})).toHaveFocus())
  await more();const modal=document.createElement('div');modal.className='ant-modal';const button=document.createElement('button');modal.append(button);document.body.append(modal)
  fireEvent.keyDown(button,{key:'Escape'});expect(screen.getByRole('dialog')).toBeVisible();modal.remove()
 }finally{window.removeEventListener('keydown',fallback)}
})
