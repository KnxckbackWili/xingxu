import { beforeEach,expect,it,vi } from 'vitest'
const { get }=vi.hoisted(()=>({get:vi.fn()}))
vi.mock('./client',()=>({api:{get,post:vi.fn(),put:vi.fn(),delete:vi.fn()}}))
import { projectApi } from './index'
beforeEach(()=>get.mockReset())
it('every private detail read checks the server rather than reusing a prior permission snapshot',async()=>{
 get.mockResolvedValueOnce({data:{id:'p',permission_version:1}}).mockResolvedValueOnce({data:{id:'p',permission_version:2}})
 expect((await projectApi.get('p')).permission_version).toBe(1);expect((await projectApi.get('p')).permission_version).toBe(2);expect(get).toHaveBeenCalledTimes(2)
})
it('a failed fresh read does not expose a cached successful private result',async()=>{
 get.mockResolvedValueOnce({data:{id:'private-p'}}).mockRejectedValueOnce(new Error('forbidden'))
 await projectApi.get('private-p');await expect(projectApi.get('private-p')).rejects.toThrow('forbidden')
})
it('passes abort semantics and the captured view account independently',async()=>{
 get.mockResolvedValue({data:{id:'p'}});const controller=new AbortController();await projectApi.get('p',{signal:controller.signal,expectedAccount:'actor-a'})
 expect(get).toHaveBeenCalledWith('/projects/p',{signal:controller.signal,headers:{'X-AGV-Expected-Account':'actor-a'}})
})
