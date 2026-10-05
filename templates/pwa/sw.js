/* LaneKit service worker ({{ version }})
 * Strategy: only static assets are cached. HTML, JSON APIs, media and
 * WebSockets always go to the network – attendance data must never be stale.
 * Navigations that fail (no connection) show a small offline page.
 */
const VERSION = '{{ version }}';
const STATIC_CACHE = 'lanekit-static-' + VERSION;
const PRECACHE = {{ precache_json|safe }};

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith('lanekit-') && k !== STATIC_CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;           // CDN assets: browser default

  // Static files: stale-while-revalidate
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.open(STATIC_CACHE).then((cache) =>
        cache.match(req).then((hit) => {
          const net = fetch(req).then((res) => { if (res.ok) cache.put(req, res.clone()); return res; }).catch(() => hit);
          return hit || net;
        })
      )
    );
    return;
  }

  // Page navigations: network only, offline page as fallback
  if (req.mode === 'navigate') {
    event.respondWith(fetch(req).catch(() => caches.match('/offline/')));
  }
  // everything else (API, media, ws): untouched
});
