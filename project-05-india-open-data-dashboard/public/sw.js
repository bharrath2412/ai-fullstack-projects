/*
 * AirGrid service worker — hand-written so the caching strategy is visible and auditable.
 *
 *   app shell  -> cache-first, refreshed in the background (stale-while-revalidate)
 *   data JSON  -> stale-while-revalidate, so the dashboard is readable offline
 *   API calls  -> network-first with a cache fallback, never cached POSTs
 *
 * Bump CACHE_VERSION when you change the shell.
 */
const CACHE_VERSION = 'airgrid-v1';
const SHELL_CACHE = `${CACHE_VERSION}-shell`;
const DATA_CACHE = `${CACHE_VERSION}-data`;

const SHELL_ASSETS = ['/', '/index.html', '/manifest.webmanifest', '/icons/icon-192.png'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(SHELL_CACHE);
      await cache.addAll(SHELL_ASSETS).catch(() => {});
      await self.skipWaiting();
    })(),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(keys.filter((key) => !key.startsWith(CACHE_VERSION)).map((key) => caches.delete(key)));
      await self.clients.claim();
    })(),
  );
});

const isDataRequest = (url) => url.pathname.endsWith('.json') || url.pathname.startsWith('/api/');

async function staleWhileRevalidate(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  const network = fetch(request)
    .then((response) => {
      if (response && response.ok) cache.put(request, response.clone());
      return response;
    })
    .catch(() => null);
  return cached || (await network) || new Response('{"offline":true}', {
    headers: { 'content-type': 'application/json' },
  });
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === 'navigate') {
    event.respondWith(
      (async () => {
        try {
          const fresh = await fetch(request);
          const cache = await caches.open(SHELL_CACHE);
          cache.put('/', fresh.clone());
          return fresh;
        } catch {
          const cache = await caches.open(SHELL_CACHE);
          return (await cache.match('/')) || (await cache.match('/index.html')) || Response.error();
        }
      })(),
    );
    return;
  }

  if (isDataRequest(url)) {
    event.respondWith(staleWhileRevalidate(request, DATA_CACHE));
    return;
  }

  event.respondWith(staleWhileRevalidate(request, SHELL_CACHE));
});
