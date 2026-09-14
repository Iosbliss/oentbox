// oentbox service worker
// Scope is the whole site (served from /sw.js, see core.views.service_worker).
// Strategy:
//  - /api/* and /admin/*            -> never intercepted, always network
//  - /static/* (css/js/img/fonts)   -> cache-first, revalidated in the background
//  - everything else (HTML pages)   -> network-first, falling back to cache when offline
const CACHE_VERSION = 'oentbox-v4';

const APP_SHELL = [
  '/',
  '/static/css/styles.css',
  '/static/js/common.js',
  '/static/js/home.js',
  '/static/js/browse.js',
  '/static/js/saved.js',
  '/static/js/youtube.js',
  '/static/js/title.js',
  '/static/js/data.js',
  '/static/js/download_manager.js',
  '/static/manifest.json',
  '/static/img/icon-192.png',
  '/static/img/icon-512.png',
];

self.addEventListener('install', (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_VERSION).then((cache) => cache.addAll(APP_SHELL).catch(() => {}))
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_VERSION).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/admin/')) return;

  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(request).then((cached) => {
        const network = fetch(request)
          .then((response) => {
            if (response && response.ok) {
              const clone = response.clone();
              caches.open(CACHE_VERSION).then((cache) => cache.put(request, clone));
            }
            return response;
          })
          .catch(() => cached);
        return cached || network;
      })
    );
    return;
  }

  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response && response.ok) {
          const clone = response.clone();
          caches.open(CACHE_VERSION).then((cache) => cache.put(request, clone));
        }
        return response;
      })
      .catch(() => caches.match(request).then((cached) => cached || caches.match('/')))
  );
});
