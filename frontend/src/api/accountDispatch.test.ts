import axios, { AxiosError, AxiosHeaders, type AxiosAdapter, type InternalAxiosRequestConfig } from 'axios'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api, tokenStore } from './client'
import { setOfflineAccount } from '../offline/queue'

const originalAdapter = api.defaults.adapter
beforeEach(() => {
  vi.restoreAllMocks(); localStorage.clear(); sessionStorage.clear(); tokenStore.clear()
  document.cookie = 'agvpm_session=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT'
})
afterEach(() => { api.defaults.adapter = originalAdapter; setOfflineAccount(null); vi.restoreAllMocks() })
const response = (config: InternalAxiosRequestConfig) => ({ data: {}, status: 200, statusText: 'OK', headers: {}, config })

it.each(['get', 'post'] as const)('captures view A before asynchronous %s dispatch can observe a B binding', async method => {
  const seen: string[] = []
  api.defaults.adapter = (async config => { seen.push(String(config.headers['X-AGV-Expected-Account'])); return response(config) }) satisfies AxiosAdapter
  setOfflineAccount('view-a')
  const pending = method === 'post' ? api.post('/worker/operations', { client_uuid: 'exact-original-intent' }) : api.get('/worker/week')
  setOfflineAccount('view-b')
  await pending
  expect(seen).toEqual(['view-a'])
})

it('keeps captured A on a refresh retry after the browser binding has changed to B', async () => {
  const seen: string[] = []
  api.defaults.adapter = (async config => {
    seen.push(String(config.headers['X-AGV-Expected-Account']))
    if (seen.length === 1) throw new AxiosError('expired', 'ERR_BAD_REQUEST', config, undefined,
      { ...response(config), status: 401, statusText: 'Unauthorized' })
    return response(config)
  }) satisfies AxiosAdapter
  const refresh = vi.spyOn(axios, 'post').mockResolvedValue({ data: {}, status: 200, statusText: 'OK', headers: {}, config: { headers: new AxiosHeaders() } })
  document.cookie = 'agvpm_session=1; path=/'
  setOfflineAccount('view-a')
  const pending = api.post('/worker/operations', { client_uuid: 'same-original-intent' })
  setOfflineAccount('view-b')
  await pending
  expect(refresh).toHaveBeenCalledTimes(1)
  expect(seen).toEqual(['view-a', 'view-a'])
})
