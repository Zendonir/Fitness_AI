/// <reference lib="webworker" />
import { build, files, version } from '$service-worker';

const STATIC = `ff-static-${version}`;
const API = 'ff-api-v1';
const ASSETS = [...build, ...files.filter((f) => !f.endsWith('.DS_Store'))];
// Lesende API-Antworten, die offline aus dem Cache kommen dürfen
const API_CACHE = [/^\/api\/auth\/me$/, /^\/api\/stats\/today/, /^\/api\/meals/, /^\/api\/training\/today/, /^\/api\/exercises/,
  /^\/api\/plans/, /^\/api\/workouts/, /^\/api\/favorites/, /^\/api\/foods\/recent/, /^\/api\/dashboards/, /^\/api\/body/,
  /^\/api\/muscles/, /^\/api\/coach\/hints/, /^\/api\/recipes/];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(STATIC).then((c) => c.addAll([...ASSETS, '/'])).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== STATIC && k !== API).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;

  if (url.pathname.startsWith('/api/')) {
    if (!API_CACHE.some((r) => r.test(url.pathname))) return;
    event.respondWith(
      fetch(req).then((res) => {
        if (res.ok) { const copy = res.clone(); caches.open(API).then((c) => c.put(req, copy)); }
        return res;
      }).catch(async () => (await caches.match(req)) || new Response(JSON.stringify({ detail: 'Offline' }), {
        status: 503, headers: { 'Content-Type': 'application/json' }
      }))
    );
    return;
  }
  if (ASSETS.includes(url.pathname)) {
    event.respondWith(caches.match(url.pathname).then((r) => r || fetch(req)));
    return;
  }
  if (req.mode === 'navigate') {
    event.respondWith(fetch(req).catch(() => caches.match('/')));
  }
});

self.addEventListener('push', (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch { data = { title: 'FitForge', body: event.data?.text() }; }
  event.waitUntil(self.registration.showNotification(data.title || 'FitForge', {
    body: data.body || '',
    icon: '/icons/icon-192.png',
    badge: '/icons/badge-72.png',
    tag: data.tag || 'fitforge',
    renotify: data.tag === 'rest-timer',
    vibrate: data.tag === 'rest-timer' ? [200, 100, 200, 100, 400] : [100],
    data: { url: data.url || '/' }
  }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = event.notification.data?.url || '/';
  event.waitUntil((async () => {
    const all = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const c of all) {
      if ('focus' in c) { await c.focus(); c.navigate?.(url); return; }
    }
    await self.clients.openWindow(url);
  })());
});

self.addEventListener('message', (event) => {
  if (event.data === 'skipWaiting') self.skipWaiting();
});
