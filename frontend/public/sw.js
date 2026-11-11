// 行序 4 has no offline cache. This file replaces the service worker that earlier versions
// installed: it removes their caches, unregisters itself and reloads the pages it controlled,
// so nobody keeps seeing the old interface.
self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys()
    await Promise.all(keys.map((key) => caches.delete(key)))
    await self.registration.unregister()
    const pages = await self.clients.matchAll({ type: 'window' })
    pages.forEach((page) => page.navigate(page.url))
  })())
})
