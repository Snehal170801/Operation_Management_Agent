/* Operation Agents service worker. It exists so the app can be installed and so a page opened with no connection says so politely.
 *
 * It deliberately does NOT cache anything else: orders, approvals, prices and sign-in tokens are live, private data, and a stale copy of them
 * would be worse than none. Every request that is not a page navigation goes straight to the network untouched, and the API is on another
 * origin that this worker never sees. Only the offline page itself is stored. */
const OFFLINE = '/offline.html'
const CACHE = 'oa-offline-v1'

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll([OFFLINE, '/icons/icon-192.png'])).then(() => self.skipWaiting()))
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const request = event.request
  if (request.mode !== 'navigate') return                      // not a page: leave it to the browser (no caching, no changes)
  event.respondWith(fetch(request).catch(() => caches.match(OFFLINE)))
})
