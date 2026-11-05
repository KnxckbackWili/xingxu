import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import VehicleProgressSummary from './VehicleProgressSummary'
it('shows completed vehicle steps out of the target',()=>{
  render(<VehicleProgressSummary value={{target:125,completed:50,percent:40,quantity_unknown:false}}/> )
  expect(screen.getByText('50/125 个车辆环节')).toBeVisible()
})
it('does not turn unknown scope into a zero or complete percentage',()=>{
  render(<VehicleProgressSummary value={{target:0,completed:0,percent:null,quantity_unknown:true}}/> )
  expect(screen.getByText('车辆范围待核对')).toBeVisible();expect(screen.queryByText('0%')).toBeNull();expect(screen.queryByText('100%')).toBeNull()
})
it('distinguishes unread progress from a known empty fleet',()=>{
  const view=render(<VehicleProgressSummary/>);expect(screen.getByText('车辆进度未读取')).toBeVisible()
  view.rerender(<VehicleProgressSummary value={{target:0,completed:0,percent:0,quantity_unknown:false}}/> )
  expect(screen.getByText('暂无车辆范围')).toBeVisible()
})
