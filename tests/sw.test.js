/* The offline worker, sw.js, in a real browser against a plain file server.
   Run with: node tests/sw.test.js

   rpi/test_scanjs.py holds the worker's two-build rules against server.js;
   this holds the one question a phone asks of it with no signal: does the page
   it opens come up? It did not for the phone's own entry point. keepShell
   stores no query and a plain Cache.match compares the whole URL, so
   live.html?route — the address README, index.html and the offers page all
   give a phone — was answered "No network, and this page is not saved" while
   live.html itself sat in the cache. The same miss came online whenever the
   rig took longer than SHELL_WAIT_MS to answer.

   No server.js: a few lines of static file server, so the only program under
   test is the worker. /api/lite says a full rig, which is the whole shell.
   Skipped (said, not failed) where playwright or chromium cannot be had, as
   the browser suites skip. Nothing here is a real place or person. */
'use strict';
var http = require('http');
var fs = require('fs');
var path = require('path');

var ROOT = path.join(__dirname, '..');
var ok = 0, bad = 0;
function check(name, cond, got) {
  if (cond) { ok++; return; }
  bad++;
  console.log('FAILED: ' + name + (got === undefined ? '' : ' (got ' + JSON.stringify(got) + ')'));
}

var TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
              '.css': 'text/css', '.png': 'image/png', '.json': 'application/json',
              '.webmanifest': 'application/manifest+json' };

// How long the next navigations to live.html are held before they are
// answered: 0 is at once, which is the rig on localhost; more than the
// worker's SHELL_WAIT_MS is the car wifi that opens and never answers.
var holdLive = 0;
var offline = false;

function serve(req, res) {
  var u = new URL(req.url, 'http://x');
  if (offline) { req.socket.destroy(); return; }
  if (u.pathname === '/api/lite') {
    res.writeHead(200, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
    return res.end('{"lite":false}');
  }
  var rel = u.pathname === '/' ? 'index.html' : decodeURIComponent(u.pathname.slice(1));
  var file = path.join(ROOT, rel);
  if (file.indexOf(ROOT + path.sep) !== 0 || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
    res.writeHead(404, { 'Content-Type': 'text/plain' });
    return res.end('not here');
  }
  var send = function () {
    res.writeHead(200, { 'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream',
                         'Cache-Control': 'no-cache' });
    res.end(fs.readFileSync(file));
  };
  if (rel === 'live.html' && holdLive) setTimeout(send, holdLive);
  else send();
}

(async function main() {
  var pw = null;
  try { pw = require('playwright'); } catch (e) { pw = null; }
  if (!pw) { console.log('(the offline worker checks skipped: no playwright)'); return finish(); }
  var b = null;
  try { b = await pw.chromium.launch(); } catch (e) { b = null; }
  if (!b) { console.log('(the offline worker checks skipped: no chromium)'); return finish(); }

  var srv = http.createServer(serve);
  await new Promise(function (r) { srv.listen(0, '127.0.0.1', r); });
  var base = 'http://127.0.0.1:' + srv.address().port + '/';
  var src = fs.readFileSync(path.join(ROOT, 'sw.js'), 'utf8');
  var waitMs = +(/var SHELL_WAIT_MS = (\d+);/.exec(src) || [])[1];
  check('sw.js names SHELL_WAIT_MS', waitMs > 0, waitMs);

  try {
    var ctx = await b.newContext({ viewport: { width: 390, height: 844 } });
    // The CDN's Leaflet and anything else off this host: refused, as with no
    // signal, so nothing below waits on the internet.
    await ctx.route(/^https?:\/\/(?!127\.0\.0\.1)/, function (rt) { rt.abort(); });
    var p = await ctx.newPage();
    await p.goto(base + 'index.html');
    var installed = await p.evaluate(async function () {
      await navigator.serviceWorker.register('sw.js');
      await navigator.serviceWorker.ready;
      return true;
    }).catch(function (e) { return String(e); });
    check('the worker installs from the plain server (the whole shell answered)', installed === true, installed);
    await p.reload();
    check('...and is in control after a reload',
          await p.evaluate(function () { return !!navigator.serviceWorker.controller; }));

    async function open(addr) {
      var t0 = Date.now();
      var r = await p.goto(base + addr, { waitUntil: 'domcontentloaded' }).catch(function () { return null; });
      return { status: r ? r.status() : null, ms: Date.now() - t0,
               title: await p.title().catch(function () { return null; }),
               search: await p.evaluate(function () { return location.search; }).catch(function () { return null; }) };
    }

    // No signal at all: the server refuses every connection.
    offline = true;
    var plain = await open('live.html');
    check('offline: live.html opens from the cache', plain.status === 200 && /Live/.test(plain.title), plain);
    var route = await open('live.html?route');
    check('offline: live.html?route opens as the panel, not as "this page is not saved"',
          route.status === 200 && /Live/.test(route.title), route);
    check('...under its own address, so the page sees ?route and draws the route view',
          route.search === '?route', route.search);
    var other = await open('journal.html?x=1');
    check('offline: any shell page under a query opens as itself (journal.html?x=1)',
          other.status === 200 && /Offers/.test(other.title), other);
    var stranger = await open('nothere.html?route');
    check('offline: a page the shell never held is still the honest notice, not a cached page',
          stranger.status === 503 && stranger.title === 'Offline', stranger);
    // A script keeps the exact match: a query on it is a cache-buster, and
    // an answer for a different one is not the script asked for.
    var script = await p.evaluate(function () {
      return fetch('scan.js?v=no-such-build').then(function (r) { return 'answered ' + r.status; },
                                                   function () { return 'refused'; });
    });
    check('offline: a script under a query it was never cached with is refused, not answered from the cache',
          script === 'refused', script);
    offline = false;

    // Online, and the rig slower than the worker will wait: the cached panel
    // answers at SHELL_WAIT_MS rather than the offline notice.
    holdLive = waitMs + 2500;
    var slow = await open('live.html?route');
    check('a rig slower than SHELL_WAIT_MS: live.html?route opens from the cache',
          slow.status === 200 && /Live/.test(slow.title), slow);
    check('...at the worker\'s wait, not the rig\'s', slow.ms < waitMs + 2000, slow.ms);
    holdLive = 0;
  } finally {
    await b.close();
    srv.close();
  }
  finish();
})().catch(function (e) { console.log('FAILED: ' + (e && e.stack || e)); bad++; finish(); });

function finish() {
  console.log(bad ? '\n' + ok + ' passed, ' + bad + ' FAILED'
                  : '\nAll ' + ok + ' offline-worker checks passed');
  process.exit(bad ? 1 : 0);
}
