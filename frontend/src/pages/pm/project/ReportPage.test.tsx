import { beforeEach,expect,it,vi } from 'vitest'
import { render,screen } from '@testing-library/react'
import ReportPage from './ReportPage'
const mocks=vi.hoisted(()=>({get:vi.fn()}))
vi.mock('../../../api/client',()=>({api:{get:mocks.get},errMsg:()=> '报告未能读取'}))
const data={period_label:'2026-10-26 ~ 2026-11-01',summary:{actual_records:2,completed_work:1,vehicle_completions:1,assisted_count:1,issues_opened:0,open_issues:0},completed_items:[{id:'r1',completion_date:'2026-10-26',recorded_at:'2026-10-27T01:00:00Z',target_name:'实际核验',actor_name:'真实操作人',assisted_user_name:'被协助同事',action:'record',is_done:true}],document_summary:{submitted:1,versions:1,overdue:0},document_submissions:[],vehicle_progress_changes:[],risks:[],next_plan:null,next_plan_state:'unavailable'}
beforeEach(()=>{mocks.get.mockReset();mocks.get.mockResolvedValue({data})})
it('展示真实完成日期、登记人和协助对象，不返回旧混单位数量',async()=>{
 render(<ReportPage projectId="p1" projectName="当前项目"/>);expect(await screen.findByText('真实操作人')).toBeVisible();expect(screen.getByText('被协助同事')).toBeVisible();expect(screen.getByText('2026-10-27T01:00:00Z')).toBeVisible();expect(screen.queryByText('完成数量')).not.toBeInTheDocument();expect(screen.getByText('周计划尚未读取')).toBeVisible()
})
it('报告读取失败不伪造空周报',async()=>{
 mocks.get.mockRejectedValue(new Error('offline'));render(<ReportPage projectId="p1" projectName="当前项目"/>);expect(await screen.findByText('报告未能读取')).toBeVisible();expect(screen.queryByText('当期没有车辆进度变化记录')).not.toBeInTheDocument()
})
