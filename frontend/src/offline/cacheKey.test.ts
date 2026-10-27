import { expect, it } from 'vitest'
import { isCacheableWorkerRequest, OFFLINE_ACCOUNT_HEADER, workerCacheKey } from './cacheKey'
it('keeps legacy cache identities distinct while private APIs are never cached', () => {
  const url = new URL('https://agv.example/api/worker/today?date=2026-09-30')
  const a = new Request(url, { headers: { [OFFLINE_ACCOUNT_HEADER]: 'a' } })
  const b = new Request(url, { headers: { [OFFLINE_ACCOUNT_HEADER]: 'b' } })
  expect(workerCacheKey({ request: a })).not.toBe(workerCacheKey({ request: b }))
  expect(new URL(workerCacheKey({ request: a })).searchParams.get('date')).toBe('2026-09-30')
  expect(isCacheableWorkerRequest({ url, request: a })).toBe(false)
  expect(isCacheableWorkerRequest({ url, request: new Request(url) })).toBe(false)
  expect(isCacheableWorkerRequest({ url: new URL('https://agv.example/api/projects'), request: a })).toBe(false)
})
