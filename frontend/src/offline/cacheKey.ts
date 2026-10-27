/** Account-scoped cache keys separate shared-device sessions. */
export const OFFLINE_ACCOUNT_HEADER = 'X-AGV-Offline-Account'
// API responses are private/no-store. Loaded views can still enqueue exact
// offline operations; their payload queue is not an HTTP response cache.
export function isCacheableWorkerRequest(_: { url: URL; request: Request }) {
  return false
}
export function workerCacheKey({ request }: { request: Request }): string {
  const url = new URL(request.url)
  // An account-scoped key also prevents a slow A response from repopulating
  // a shared URL cache after logout/login B cleared it.
  url.searchParams.set('__agv_account', request.headers.get(OFFLINE_ACCOUNT_HEADER) || '')
  return url.toString()
}
