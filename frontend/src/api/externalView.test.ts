import { afterEach, expect, it, vi } from 'vitest'
import { externalViewApi } from './externalView'
import { isCacheableWorkerRequest, OFFLINE_ACCOUNT_HEADER } from '../offline/cacheKey'
afterEach(() => vi.unstubAllGlobals())
it('keeps raw secrets in bootstrap body and sessions in headers with no credentials/cache', async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ view: {} }), blob: async () => new Blob(['original']) })
  vi.stubGlobal('fetch', fetcher)
  await externalViewApi.bootstrap('raw-secret')
  expect(fetcher).toHaveBeenCalledWith('/api/external/bootstrap', expect.objectContaining({ method: 'POST', body: JSON.stringify({ token: 'raw-secret' }), credentials: 'omit', cache: 'no-store', referrerPolicy: 'no-referrer', redirect: 'error' }))
  await externalViewApi.view('readonly-session')
  expect(fetcher).toHaveBeenLastCalledWith('/api/external/view', expect.objectContaining({ headers: { Authorization: 'Bearer readonly-session' }, credentials: 'omit', cache: 'no-store' }))
  expect(fetcher.mock.calls.every(([url]) => !url.includes('secret') && !url.includes('session'))).toBe(true)
  for (const path of ['/api/external/view', '/api/external/documents/d/versions/v/download', '/api/projects/p/external-shares']) {
    const url = new URL(path, 'https://example.test')
    const request = { headers: new Headers({ [OFFLINE_ACCOUNT_HEADER]: 'fake-account' }) } as Request
    expect(isCacheableWorkerRequest({ url, request })).toBe(false)
  }
})
it('does not reflect a failed body or credential in the external error', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 401, json: async () => ({ token: 'never-reflect' }) }))
  await expect(externalViewApi.bootstrap('never-reflect')).rejects.toThrow('分享已到期')
})
