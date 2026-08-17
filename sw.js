/* Offline cache. Bumped whenever a file in ASSETS changes. This is cache-first, so a phone
 * that has the old worker keeps serving the old page forever otherwise —
 * v7 shipped before live.html, styles.css and offer-parser.js all changed,
 * which would have hidden every one of those changes behind a stale cache. */
var CACHE = 'uberscan-v23';

var ASSETS = [
  './',
  'index.html',
  'styles.css',
  'ui.js',
  'offer-parser.js',
  'scan.html',
  'scan.css',
  'scan.js',
  'live.html',
  'journal.html',
  'advice.js',
  'manifest.webmanifest',
  'icons/icon-192.png',
  'icons/icon-512.png',
  'icons/maskable-512.png',
  'icons/apple-touch-icon.png'
];

self.addEventListener('install', function (e) {
  e.waitUntil(
    caches.open(CACHE)
      .then(function (c) { return c.addAll(ASSETS); })
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (e) {
  e.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.map(function (k) {
        return k === CACHE ? null : caches.delete(k);
      }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (e) {
  if (e.request.method !== 'GET') return;

  var url = new URL(e.request.url);
  if (url.origin !== self.location.origin) return;

  /* The live endpoints must never touch the cache, and a cache-first worker
   * gets all three of them wrong in a different way:
   *
   *   /api/status    answers once and is then frozen at that answer forever,
   *                  because Cache.match happily satisfies a request that
   *                  asked for `cache: 'no-store'`. The page would seed
   *                  itself from a snapshot of whatever the scanner was
   *                  doing the first time it was ever opened.
   *   /api/frame.jpg is fetched with a cache-busting `?t=<ms>` twice a
   *                  second, and every distinct URL is a distinct cache
   *                  entry — a few hours of watching fills the quota with
   *                  stale JPEGs.
   *   /api/events    is server-sent events: a response body that never ends.
   *                  Cloning it into cache.put() buffers a stream with no
   *                  last byte.
   *
   * None of it is any use offline either — it is all live state from a
   * scanner that is, by definition, not running.
   */
  if (url.pathname.indexOf('/api/') === 0) return;

  e.respondWith(
    caches.match(e.request).then(function (hit) {
      if (hit) return hit;
      return fetch(e.request).then(function (res) {
        // Cache same-origin successes so a first visit online works offline
        // later. Query strings are skipped: they are cache-busters here, and
        // storing them accumulates entries nothing will ever ask for again.
        if (res && res.ok && res.type === 'basic' && !url.search) {
          var copy = res.clone();
          caches.open(CACHE).then(function (c) { c.put(e.request, copy); });
        }
        return res;
      }).catch(function () {
        return caches.match('index.html');
      });
    })
  );
});
