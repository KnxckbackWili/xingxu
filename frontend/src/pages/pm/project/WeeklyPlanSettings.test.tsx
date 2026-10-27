import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { ConfigProvider } from 'antd'
const h=vi.hoisted(()=>({settings:vi.fn(),saveSettings:vi.fn(),reload:vi.fn(),dirty:vi.fn(),verify:vi.fn(),user:{id:'pm',role:'pm',permission_overrides:{}} as any}))
vi.mock('../../../api/weeklyPlans',async original=>({...await original<object>(),weeklyPlansApi:h}))
vi.mock('../../../stores/auth',()=>({useAuth:()=>({user:h.user})}))
vi.mock('../../../utils/verifiedAccount',()=>({ensureVerifiedAccount:h.verify}))
vi.mock('../../../api/client',()=>({errMsg:(e:any)=>e.response?.data?.detail||e.message}))
import WeeklyPlanSettings from './WeeklyPlanSettings'
const project={id:'p1',name:'项目',status:'executing',capabilities:['project.manage_schedule'],version:2} as any
const initial={settings:{rest_mode:'none',rest_days:['2026-10-28'],skip_holidays:false},version:7,warnings:[]}
const show=()=>render(<ConfigProvider theme={{token:{motion:false}}}><WeeklyPlanSettings project={project} onReload={h.reload} onDirtyChange={h.dirty}/></ConfigProvider>)
beforeEach(()=>{vi.clearAllMocks();h.user={id:'pm',role:'pm',permission_overrides:{}};h.settings.mockResolvedValue(initial);h.saveSettings.mockResolvedValue({...initial,version:8});h.verify.mockImplementation(()=>undefined)})
it('saves calendar settings with the fresh settings version and preserves the explicit date list',async()=>{
 show();await screen.findByLabelText('手动休息日');fireEvent.click(screen.getByRole('radio',{name:'周日休息'}));fireEvent.change(screen.getByLabelText('手动休息日'),{target:{value:'2026-10-28\n2026-11-01\n2026-10-28'}});fireEvent.click(screen.getByRole('button',{name:'保存排期设置'}))
 await waitFor(()=>expect(h.saveSettings).toHaveBeenCalledWith('p1',{version:7,rest_mode:'one',rest_days:['2026-10-28','2026-11-01'],skip_holidays:false}));expect(h.verify).toHaveBeenCalledWith('pm');expect(h.reload).toHaveBeenCalledOnce()
})
it('rejects an impossible business date locally and keeps the input',async()=>{
 show();await screen.findByLabelText('手动休息日');fireEvent.change(screen.getByLabelText('手动休息日'),{target:{value:'2026-02-31'}});fireEvent.click(screen.getByRole('button',{name:'保存排期设置'}))
 expect(await screen.findByText('请按每行 YYYY-MM-DD 填写有效的休息日期')).toBeVisible();expect(h.saveSettings).not.toHaveBeenCalled();expect(screen.getByLabelText('手动休息日')).toHaveValue('2026-02-31')
})
it('keeps changes after a stale refusal and requires an explicit fresh read',async()=>{
 h.saveSettings.mockRejectedValueOnce({response:{status:409,data:{detail:'项目已变化'}}});show();await screen.findByLabelText('手动休息日');fireEvent.change(screen.getByLabelText('手动休息日'),{target:{value:'2026-11-01'}});fireEvent.click(screen.getByRole('button',{name:'保存排期设置'}))
 expect(await screen.findByText('设置预览已失效，请重新读取后保存')).toBeVisible();expect(screen.getByLabelText('手动休息日')).toHaveValue('2026-11-01');expect(screen.getByRole('button',{name:'保存排期设置'})).toBeDisabled();expect(h.settings).toHaveBeenCalledOnce()
})
it('does not request or mutate settings after an explicit system denial',()=>{
 h.user={...h.user,permission_overrides:{'project.manage_schedule':false}};show();expect(screen.getByText('本账号当前没有周计划维护权限')).toBeVisible();expect(h.settings).not.toHaveBeenCalled();expect(h.saveSettings).not.toHaveBeenCalled()
})
