/* eslint-disable no-restricted-globals */
import { clientsClaim } from 'workbox-core'
import { ExpirationPlugin } from 'workbox-expiration'
import { precacheAndRoute, cleanupOutdatedCaches, matchPrecache } from 'workbox-precaching'
import { registerRoute, setCatchHandler } from 'workbox-routing'
import { CacheableResponsePlugin } from 'workbox-cacheable-response'
import { NetworkFirst, StaleWhileRevalidate } from 'workbox-strategies'

self.skipWaiting()
clientsClaim()
precacheAndRoute(self.__WB_MANIFEST)
cleanupOutdatedCaches()

// Always ask the server for the current app shell. The precached shell is used
// only when the NAS is unreachable, so an old PWA cannot mask a deployment.
registerRoute(
  ({ request, url }) => request.mode === 'navigate' && !url.pathname.startsWith('/api/'),
  new NetworkFirst({
    cacheName: 'agvpm-pages',
    networkTimeoutSeconds: 4,
    plugins: [
      new CacheableResponsePlugin({ statuses: [200] }),
      new ExpirationPlugin({ maxEntries: 20, maxAgeSeconds: 7 * 24 * 60 * 60 }),
    ],
  }),
)

// Old API snapshots may contain another account's records or private original
// files cached as navigation. Queued operations and upload IndexedDB are separate.
self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    await caches.delete('agvpm-api')
    if ((await caches.keys()).includes('agvpm-pages')) {
      const pages = await caches.open('agvpm-pages')
      for (const request of await pages.keys()) {
        if (new URL(request.url).pathname.startsWith('/api/')) await pages.delete(request)
      }
    }
  })())
})

// Static assets that are not in the precache (e.g. lazy-loaded PM chunks)
// get a runtime cache fallback so the app still opens on the NAS without network.
registerRoute(
  ({ request }) => ['script', 'style', 'image', 'font'].includes(request.destination),
  new StaleWhileRevalidate({
    cacheName: 'agvpm-assets',
    plugins: [
      new CacheableResponsePlugin({ statuses: [200] }),
      new ExpirationPlugin({ maxEntries: 80, maxAgeSeconds: 30 * 24 * 60 * 60 }),
    ],
  }),
)

setCatchHandler(async ({ event }) => {
  if (event.request.destination === 'document') {
    return (await matchPrecache('/index.html')) || Response.error()
  }
  return Response.error()
})
