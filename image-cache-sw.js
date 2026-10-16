// Cache versioned same-origin snapshots, shared by pages and image exports.
const CACHE = 'another-tier-cn-images-v1';
const LIMIT = 1200;
const pending = new Map();
self.addEventListener('install', event => event.waitUntil(self.skipWaiting()));
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));

async function readImage(request) {
  let cache;
  try {
    cache = await caches.open(CACHE);
    const cached = await cache.match(request);
    if (cached) return cached;
  } catch { /* Storage may be disabled; fetching still works. */ }
  const response = await fetch(request);
  if (cache && response.ok && response.headers.get('Content-Type')?.startsWith('image/')) {
    try {
      await cache.put(request, response.clone());
      const url = new URL(request.url);
      const keys = await cache.keys();
      for (const key of keys) {
        if (key.url !== request.url && new URL(key.url).pathname === url.pathname) await cache.delete(key);
      }
      const remaining = await cache.keys();
      for (const key of remaining.slice(0, Math.max(0, remaining.length - LIMIT))) await cache.delete(key);
    } catch { /* Quota failures must not prevent a successfully fetched image. */ }
  }
  return response;
}

self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);
  const root = new URL('mirror-images/', self.registration.scope);
  if (request.method !== 'GET' || url.origin !== root.origin || !url.pathname.startsWith(root.pathname)
      || !/^[0-9a-f]{12}$/.test(url.searchParams.get('v') || '')) return;
  // Share concurrent page/export requests until the cache write completes.
  let loading = pending.get(url.href);
  if (!loading) {
    loading = readImage(request).finally(() => pending.delete(url.href));
    pending.set(url.href, loading);
  }
  event.respondWith(loading.then(response => response.clone()));
});
