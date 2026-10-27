import { expect,it,vi } from 'vitest'
import { fireEvent,render,screen } from '@testing-library/react'
import RecordsPage from './RecordsPage'
import { api } from '../../api/client'
vi.mock('../../api/client',()=>({api:{get:vi.fn()},errMsg:()=> '实际记录读取失败'}))
vi.mock('../../stores/auth',()=>({useAuth:()=>({user:{id:'worker',role:'worker',system_permissions:['personal.records.read','worker.report']}})}))
it('服务端仅允许当前本人记录修订，历史版本只读',async()=>{
 vi.mocked(api.get).mockResolvedValue({data:{records:[{id:'r1',project_id:'p',project_name:'现场',target_name:'完成工作',completion_date:'2026-10-26',recorded_at:'2026-10-27T01:00:00Z',actor_name:'本人',action:'record',is_done:true,can_edit:true,can_retract:true},{id:'r2',project_name:'现场',target_name:'历史版本',completion_date:'2026-10-20',recorded_at:'2026-10-20T01:00:00Z',actor_name:'本人',action:'edit',is_done:true,can_edit:false,can_retract:false}]}})
 render(<RecordsPage/>);expect(await screen.findByText('完成日期 2026-10-26')).toBeInTheDocument();expect(screen.getAllByRole('button',{name:/撤\s*回/})).toHaveLength(1);expect(screen.queryByRole('list',{name:'本范围完成数量'})).not.toBeInTheDocument()
})
it('读取失败不显示空历史，支持明确重试',async()=>{
 vi.mocked(api.get).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({data:{records:[]}});render(<RecordsPage/>);expect(await screen.findByText('实际记录读取失败')).toBeInTheDocument();expect(screen.queryByText('本周暂无实际记录')).not.toBeInTheDocument();fireEvent.click(screen.getByRole('button',{name:/重\s*试/}));expect(await screen.findByText('本周暂无实际记录')).toBeInTheDocument()
})
