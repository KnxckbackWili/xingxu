import { expect,it,vi } from 'vitest'
import { projectApi } from './index'
import { api } from './client'
vi.mock('./client',()=>({api:{get:vi.fn()}}))
it('rechecks the same private project for each captured account rather than returning another account TTL entry',async()=>{
  vi.mocked(api.get).mockResolvedValueOnce({data:{id:'p',name:'A-visible',capabilities:['project.update']}}).mockResolvedValueOnce({data:{id:'p',name:'B-visible',capabilities:[]}})
  const a=await projectApi.get('p',{expectedAccount:'a'})
  const b=await projectApi.get('p',{expectedAccount:'b'})
  expect(a.name).toBe('A-visible');expect(b.name).toBe('B-visible');expect(api.get).toHaveBeenCalledTimes(2)
  expect(api.get).toHaveBeenNthCalledWith(1,'/projects/p',{signal:undefined,headers:{'X-AGV-Expected-Account':'a'}})
  expect(api.get).toHaveBeenNthCalledWith(2,'/projects/p',{signal:undefined,headers:{'X-AGV-Expected-Account':'b'}})
})
