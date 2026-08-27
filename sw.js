/* Offline cache.
 *
 * This used to be cache-first with a hand-bumped version, and the version was
 * load-bearing: forget it and a phone that has already installed the app serves
 * the old code forever. The comment said so — "bumped whenever a file in ASSETS
 * changes" — and it still went wrong twice in two commits. `scan.js` was fixed
 * so the phone could read a shop order at all, `offer-parser.js` was fixed so a
 * card with no readable distance stopped feeding a gross rate into the medians,
 * and neither reached a single installed phone, because the constant below did
 * not move. A rule that has to be remembered on every commit is a rule that
 * gets forgotten on some commit.
 *
 * So the shell is stale-while-revalidate now: served from cache at once, then
 * re-fetched in the background and the entry replaced. Forgetting to bump costs
 * one page load instead of costing everything, and the version is a convenience
 * rather than the mechanism.
 *
 * The two caches are separate for a reason that would have bitten the obvious
 * fix. `vendor/` — the OCR engine and its language data, about 15MB — was never
 * in ASSETS; it only ever landed in the cache opportunistically, in the fetch
 * handler, under the same key. `activate` deletes every cache that is not the
 * current one. So simply bumping the version would have deleted the engine and
 * install would not have put it back: a phone with no signal would have lost
 * the scanner entirely, in the name of shipping a scanner fix.
 */
var SHELL = 'uberscan-shell-v40';

/* Bumped only when the vendored engine itself changes, which is rare and
 * deliberate. Held apart from the shell so that shipping app code never costs
 * anyone 15MB of re-download, and never leaves an offline phone without a
 * reader. */
var BLOB = 'uberscan-vendor-v1';

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

function isVendor(pathname) {
  return pathname.indexOf('/vendor/') !== -1;
}

self.addEventListener('install', function (e) {
  e.waitUntil(
    caches.open(SHELL)
      .then(function (c) { return c.addAll(ASSETS); })
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (e) {
  e.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.map(function (k) {
        // Both survive. Deleting BLOB here is what would cost an offline phone
        // its reader; deleting neither is what would leave old shells around.
        return (k === SHELL || k === BLOB) ? null : caches.delete(k);
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

  /* The engine and its language data: many megabytes, and they only change
   * when someone re-vendors them. Cache-first and left alone, so a page load
   * never re-fetches them and a bump of the app shell never evicts them. */
  if (isVendor(url.pathname)) {
    e.respondWith(
      caches.match(e.request).then(function (hit) {
        if (hit) return hit;
        return fetch(e.request).then(function (res) {
          if (res && res.ok && res.type === 'basic' && !url.search) {
            var copy = res.clone();
            caches.open(BLOB).then(function (c) { c.put(e.request, copy); });
          }
          return res;
        });
      })
    );
    return;
  }

  /* Everything else: answer from cache immediately if it is there, and refresh
   * the entry in the background either way. The driver sees the cached page at
   * cache-first speed and the next load has the new code — which is the whole
   * difference between shipping a fix late and not shipping it.
   *
   * A background fetch that fails must leave the cached copy alone, which is
   * what the empty catch is for: offline is the case this file exists for. */
  e.respondWith(
    caches.match(e.request).then(function (hit) {
      var fresh = fetch(e.request).then(function (res) {
        // Query strings are skipped: they are cache-busters here, and storing
        // them accumulates entries nothing will ever ask for again.
        if (res && res.ok && res.type === 'basic' && !url.search) {
          var copy = res.clone();
          caches.open(SHELL).then(function (c) { c.put(e.request, copy); });
        }
        return res;
      }).catch(function () {
        // Nothing cached and no network. A navigation can still be answered
        // with the app shell; anything else has to fail as itself, because
        // handing back index.html in place of a script is a stranger failure
        // than not answering at all.
        if (hit) return hit;
        return e.request.mode === 'navigate'
          ? caches.match('index.html') : Response.error();
      });
      return hit || fresh;
    })
  );
});
