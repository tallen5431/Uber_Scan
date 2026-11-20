/* The places report's outside world: the server's journal, the NucBox's
 * answers and their cache, the GPS log through tools/shift_report.py, the
 * rig's store waits, and the command itself (parseArgs, main). The rules
 * are tools/places_report.js's header; analyse is that file's. */

'use strict';

var fs = require('fs');
var os = require('os');
var path = require('path');
var cp = require('child_process');

var A = require('../../advice.js');
var MV = require('../../map-view.js');

var ST = require('./stats.js');
var PL = require('./place.js');
var TB = require('./tables.js');
var WW = require('./whenwhere.js');
var RN = require('./render.js');
var CSV = require('./csv.js');
var MIN_N = ST.MIN_N, NBX_LIMIT = ST.NBX_LIMIT, AT_THE_DOOR = ST.AT_THE_DOOR, minOf = ST.minOf,
    maxOf = ST.maxOf, counted = ST.counted, seenAt = ST.seenAt, cellOf = ST.cellOf;
var REGION_MARGIN_MI = PL.REGION_MARGIN_MI, BAND_WAIT_OFFLINE_MS = PL.BAND_WAIT_OFFLINE_MS,
    regionOf = PL.regionOf, printedDoor = PL.printedDoor, placeRow = PL.placeRow,
    placeDropoff = PL.placeDropoff, heldEndsOf = PL.heldEndsOf, afterFor = PL.afterFor;
var SPELL_THIN_S = TB.SPELL_THIN_S, spellsOf = TB.spellsOf, heldOf = TB.heldOf, timePresses = TB.timePresses;
var cardFixAfter = WW.cardFixAfter;
var summary = RN.summary, html = RN.html;
var csvOf = CSV.csvOf, dropCsv = CSV.dropCsv, tableCsv = CSV.tableCsv, MORE_CSVS = CSV.MORE_CSVS,
    shareCsv = CSV.shareCsv, levelsCsv = CSV.levelsCsv, restCsv = CSV.restCsv,
    restBranchCsv = CSV.restBranchCsv, strategyCsv = CSV.strategyCsv, coverageCsv = CSV.coverageCsv;

// The repository, which the report refuses to be written inside, and
// tools/, where shift_report.py is for the GPS log's two helpers.
var ROOT = path.resolve(__dirname, '..', '..');
var TOOLS = path.resolve(__dirname, '..');

// analyse is tools/places_report.js's, which requires this file for main:
// asked for when main runs, by which time both have loaded.
function analyse() { return require('../places_report.js').analyse.apply(null, arguments); }

/* --- talking to the server, the NucBox and the GPS log -------------------- */

async function getJson(u) {
  var res = await fetch(u, { headers: { Accept: 'application/json' } });
  var body = null;
  try { body = await res.json(); } catch (e) { body = null; }
  return { ok: res.ok, status: res.status, body: body };
}

/* The whole journal, a page of JOURNAL_PAGE at a time (the reporting
 * review's R2). The server lists at most 20,000 offers, the newest, and the
 * report read one answer, so past 20,000 it quietly described the newest
 * 20,000 and said so only on stdout. It now asks again for the offers before
 * the oldest it holds (`until`, the server's), keeping the first answer's
 * takes, records and every figure the server worked over the whole window,
 * until the server says nothing was cut. A server from before `until` sends
 * the same page again: no new offer, so it stops, and the answer keeps
 * `truncated`, which the page now says at its head. `getter` stands in for
 * the network in the checks. */
var JOURNAL_PAGE = 20000;
var JOURNAL_PAGES_MAX = 50;
async function loadJournal(base, sinceMs, getter) {
  var get = getter || getJson;
  var root = base.replace(/\/+$/, '') + '/api/journal?days=3650&limit=' + JOURNAL_PAGE
    + (sinceMs ? '&since=' + sinceMs : '');
  async function one(until) {
    var u = root + (until ? '&until=' + until : '');
    var got = await get(u);
    if (!got.ok || !got.body) throw new Error(u + ' answered ' + got.status);
    if (got.body.unreadable) throw new Error('the server could not read its journal (' + got.body.unreadable + ')');
    return got.body;
  }
  var body = await one(null);
  var offers = Array.isArray(body.offers) ? body.offers.slice() : [];
  var seen = Object.create(null);
  offers.forEach(function (o) { if (o && typeof o.id === 'string') seen[o.id] = true; });
  var page = body, pages = 1;
  while (page.truncated && pages < JOURNAL_PAGES_MAX) {
    var oldest = Infinity;
    (page.offers || []).forEach(function (o) { if (o && typeof o.at === 'number' && o.at < oldest) oldest = o.at; });
    if (!isFinite(oldest)) break;
    // One past the oldest, so a second offer at that same moment, cut off
    // by the cap, comes too; the ids already held are skipped.
    page = await one(oldest + 1);
    pages += 1;
    var fresh = (page.offers || []).filter(function (o) { return !(o && typeof o.id === 'string' && seen[o.id]); });
    if (!fresh.length) break;
    fresh.forEach(function (o) { if (o && typeof o.id === 'string') seen[o.id] = true; });
    offers = fresh.concat(offers);
  }
  body.offers = offers;
  body.pages = pages;
  body.count = offers.length;
  body.truncated = offers.length < (body.total || 0);
  return body;
}

/* A Nominatim jsonv2 list as server.js's relay hands it to a page (nbxHits):
 * where, the display name (where a door shows), the category and the
 * feature's own name, and the limit as `cutAt`. The direct path must hand
 * map-view.js exactly what the relay would, so the same rules decide. */
function hitsOf(list) {
  return { ok: true, cutAt: list.length >= NBX_LIMIT ? NBX_LIMIT : null,
           hits: list.map(function (h) {
             return { lat: Number(h.lat), lon: Number(h.lon), name: String(h.display_name || ''),
                      kind: typeof h.category === 'string' ? h.category : null,
                      called: typeof h.name === 'string' ? h.name : '' };
           }).filter(function (h) { return isFinite(h.lat) && isFinite(h.lon); }) };
}

/* The fetch an NbxSearch is given. Its paths are the relay's (`/api/nbx/search?...`,
 * `/cross?...`, ...): a search goes to `nominatim` directly when one is named,
 * else through the server's own relay; the street index's questions only
 * through the relay. Every answer is kept in `cache` by its question — an
 * answer, never a failure: a NucBox down (502, `unreachable`) or any status
 * but 200 is asked again next time. Each question not from the cache is
 * counted in `cache.asked`, and one the NucBox did not answer (thrown,
 * `unreachable`, a 5xx) in `cache.unreachable`, for main's DEGRADED check. */
function tallyAsk(cache, unreachable) {
  cache.asked = (cache.asked || 0) + 1;
  if (unreachable) cache.unreachable = (cache.unreachable || 0) + 1;
}

/* A run whose fresh questions the NucBox mostly did not answer: offers left
 * unplaced for a Nominatim or relay that was down, not for where they are.
 * Its report is not written (the nightly keeps the old one) unless
 * --allow-degraded. Chosen, not measured: more than DEGRADED_SHARE of the
 * fresh questions AND more than DEGRADED_MIN of them, so a few misses on a
 * warm cache never refuse a night. */
var DEGRADED_SHARE = 0.2;
var DEGRADED_MIN = 50;

function degraded(cache) {
  var asked = cache.asked || 0, bad = cache.unreachable || 0;
  return bad > DEGRADED_MIN && bad > DEGRADED_SHARE * asked
    ? { asked: asked, unreachable: bad } : null;
}

function nbxFetch(opts) {
  var cache = opts.cache;
  var server = opts.server.replace(/\/+$/, '');
  // The street index's questions go to `opts.streets` (streetsBase: a relay's
  // /api/nbx, or a server's own /api/streets), else this server's relay.
  var streetsAt = opts.streets ? opts.streets.replace(/\/+$/, '') : server + '/api/nbx';
  function reply(status, body) {
    return { ok: status === 200, status: status, json: function () { return Promise.resolve(body); } };
  }
  return async function (asked) {
    // NbxSearch puts its base in front ('/api/nbx', its default: an empty
    // base is no base to it), and the question is what follows.
    var pathAsked = String(asked).replace(/^\/api\/nbx(?=\/)/, '');
    if (Object.prototype.hasOwnProperty.call(cache.answers, pathAsked)) {
      cache.hits += 1;
      return reply(200, cache.answers[pathAsked]);
    }
    var body, status;
    try {
      if (opts.nominatim && /^\/search\?/.test(pathAsked)) {
        var q = new URLSearchParams(pathAsked.slice('/search?'.length));
        var term = q.has('q') ? 'q' : 'street';
        var u = opts.nominatim.replace(/\/+$/, '') + '/search?format=jsonv2&limit=' + NBX_LIMIT + '&' + term
          + '=' + encodeURIComponent(q.get(term) || '')
          + (q.get('viewbox') ? '&viewbox=' + encodeURIComponent(q.get('viewbox')) + '&bounded=1' : '');
        var r = await getJson(u);
        if (!r.ok || !Array.isArray(r.body)) {
          tallyAsk(cache, true);
          return reply(502, { ok: false, unreachable: true, error: 'Nominatim answered ' + r.status });
        }
        body = hitsOf(r.body); status = 200;
      } else if (/^\/(cross|stretch|named|whole)\?/.test(pathAsked)) {
        var r3 = await getJson(streetsAt + pathAsked);
        body = r3.body || {}; status = r3.status;
      } else {
        var r2 = await getJson(server + '/api/nbx' + pathAsked);
        body = r2.body || {}; status = r2.status;
      }
    } catch (e) {
      tallyAsk(cache, true);
      return reply(502, { ok: false, unreachable: true, error: String(e && e.message || e) });
    }
    tallyAsk(cache, !!(body && body.unreachable) || !(status < 500));
    if (status === 200 && body && body.ok !== undefined && !body.unreachable) {
      cache.answers[pathAsked] = body;
      cache.fresh += 1;
      if (opts.onFresh) opts.onFresh();
    }
    return reply(status, body);
  };
}

/* Where the street index is asked: `url` as given — a path ending /api/nbx
 * is a relay (server.js nbxRoute: /api/nbx/cross...), a bare server is its
 * own index (/api/streets/cross..., server.js streetsRoute, NUCBOX_STREETS_FILE
 * loaded there) — or, unasked, this server's relay when it has one set, else
 * this server's own index when it has one loaded. Returns { base, said } or
 * { base: null, said } with why not. */
async function streetsBase(server, url) {
  server = server.replace(/\/+$/, '');
  async function probe(base) {
    try {
      if (/\/api\/nbx$/.test(base)) {
        var a = await getJson(base);
        return a.ok && a.body && a.body.streets ? base : null;
      }
      var b = await getJson(base.replace(/\/api\/streets$/, '') + '/api/streets');
      return b.ok && b.body && b.body.loaded ? base.replace(/\/api\/streets$/, '') + '/api/streets' : null;
    } catch (e) { return null; }
  }
  if (url) {
    var u = url.replace(/\/+$/, '');
    var got = await probe(u);
    return got ? { base: got, said: got } : { base: null, said: 'none — ' + u + ' did not answer as a street index' };
  }
  var relay = await probe(server + '/api/nbx');
  if (relay) return { base: relay, said: relay + ' (the server\'s relay)' };
  var own = await probe(server);
  if (own) return { base: own, said: own + ' (the server\'s own index)' };
  return { base: null, said: 'none — ' + server + ' has no relay to one (NUCBOX_STREETS) and no index loaded; give --streets' };
}

/* The rig's store waits, for a source whose /api/journal carries none (the
 * NucBox's copy holds no store-waits file): `url`'s /api/journal `waits`. */
/* The trips read off the app's earnings screenshots (server.js
 * /api/earnings, since 8 Nov 2026), for the Strategy tab's card vs paid. A
 * server from before it answers 404, and the tab says none were uploaded. */
async function loadEarnings(base) {
  try {
    var got = await getJson(base.replace(/\/+$/, '') + '/api/earnings?days=3650');
    return got.ok && got.body && Array.isArray(got.body.entries) ? got.body.entries : [];
  } catch (e) {
    return [];
  }
}

/* The Gold card's setting (server.js /api/gold, since 15 Nov 2026): the
 * goal and Uber's own figures, for the Strategy tab's acceptance lines. A
 * server from before it answers 404, and the defaults stand (25%, no
 * figures). */
async function loadGold(base) {
  try {
    var got = await getJson(base.replace(/\/+$/, '') + '/api/gold');
    var st = got.ok && got.body && got.body.settings;
    return st ? { goal: st.goal, uber: st.uber } : null;
  } catch (e) {
    return null;
  }
}

async function loadWaits(url) {
  var got = await getJson(url.replace(/\/+$/, '') + '/api/journal?days=1&limit=1');
  if (!got.ok || !got.body || !Array.isArray(got.body.waits)) throw new Error(url + ' answered ' + got.status + ' with no waits');
  return got.body.waits;
}

/* The GPS log, read by tools/shift_report.py (rpi/gps.py's gate on every
 * fix, in Python because that is where the gate is: one rule in one place),
 * asked two things: every usable fix in a window, thinned (`fixes`), and the
 * car's position at each moment asked, the nearest usable fix within its
 * NEAR_S (`at`).
 *
 * ONE READ FOR BOTH. Each was its own Python run of load_fixes over every log
 * in its window: on an invented record of 1.06M fixes, 24 s and 23.7 s of an
 * 80 s build, the same logs read twice. The second question cannot go in the
 * first run's input (its moments are the drops timePresses moves off the
 * first answer), so main keeps one helper open (gpsLog) and asks it twice.
 * The helper keeps each log's fixes as it reads them (load_log: a log's
 * fixes do not depend on which others are read beside it) and answers each
 * window from the logs load_fixes would read for it, sorted as it sorts, so
 * the answers are load_fixes's to the byte. Nothing is cached on disk: the
 * fixes live in that process and go with it. gpsAt and gpsFixes, one
 * question each, are the same helper asked once. */
var GPS_HELPER = [
  'import bisect, json, os, sys',
  'sys.path.insert(0, sys.argv[1])',
  'import shift_report as SR',
  'd = sys.argv[2]',
  'names = SR.log_names(d)[0] if d and os.path.isdir(d) else []',
  'per = {}',
  'def window(lo, hi):',
  '    pick = SR._logs_for(names, (lo, hi))',
  '    fixes, passed = [], 0',
  '    for n in pick:',
  '        if n not in per:',
  '            per[n] = SR.load_log(d, n)',
  '        fixes.extend(per[n][0])',
  '        passed += per[n][1]["passed"]',
  '    fixes.sort(key=lambda f: f[:3])',
  '    return fixes, len(pick), passed',
  'for line in sys.stdin:',
  '    req = json.loads(line)',
  '    if req["op"] == "fixes":',
  '        fixes, files, passed = window(req["from"], req["to"])',
  '        out, last = [], None',
  '        for f in fixes:',
  '            if f[0] * 1000.0 < req["from"] or f[0] * 1000.0 > req["to"]:',
  '                continue',
  '            if last is None or f[0] - last >= req["thin"]:',
  '                out.append([round(f[0], 1), round(f[1], 6), round(f[2], 6)])',
  '                last = f[0]',
  '        got = {"fixes": out, "files": files, "passed": passed}',
  '    else:',
  '        ts = req["times"]',
  '        out, files, passed = [None] * len(ts), 0, 0',
  '        if ts:',
  '            fixes, files, passed = window(min(ts) * 1000.0 - 3600e3, max(ts) * 1000.0 + 3600e3)',
  '            keys = [f[0] for f in fixes]',
  '            for n, t in enumerate(ts):',
  '                i = bisect.bisect_left(keys, t)',
  '                best = None',
  '                for j in (i - 1, i):',
  '                    if 0 <= j < len(keys) and abs(keys[j] - t) <= SR.NEAR_S:',
  '                        if best is None or abs(keys[j] - t) < abs(best[0] - t):',
  '                            best = fixes[j]',
  '                out[n] = [best[1], best[2]] if best else None',
  '        got = {"at": out, "files": files, "passed": passed}',
  '    sys.stdout.write(json.dumps(got) + "\\n")',
  '    sys.stdout.flush()',
].join('\n');

function fixesAsk(fromMs, toMs, thin) {
  return { op: 'fixes', from: fromMs, to: toMs, thin: thin || SPELL_THIN_S };
}
function atAsk(timesMs) {
  return { op: 'at', times: timesMs.map(function (t) { return t / 1000; }) };
}

function gpsOnce(dir, ask) {
  var got = cp.spawnSync('python3', ['-c', GPS_HELPER, TOOLS, dir], {
    input: JSON.stringify(ask) + '\n', encoding: 'utf8', maxBuffer: 512 * 1024 * 1024 });
  if (got.status !== 0) throw new Error('reading the GPS log failed: ' + (got.stderr || got.error || '').toString().slice(0, 400));
  return JSON.parse(got.stdout);
}

/* The positions at `timesMs`, [[lat, lon] | null] in order, as `at`. */
function gpsAt(dir, timesMs) { return gpsOnce(dir, atAsk(timesMs)); }

/* Every usable fix in [fromMs, toMs], thinned to one per `thin` seconds, as
 * [[tSec, lat, lon]] in `fixes`. */
function gpsFixes(dir, fromMs, toMs, thin) { return gpsOnce(dir, fixesAsk(fromMs, toMs, thin)); }

/* The helper kept open for main's two questions: { fixes(), at(), close() },
 * each question a Promise of what gpsFixes and gpsAt answer. Started on the
 * first question; close() ends it, and main closes it in a finally. */
function gpsLog(dir) {
  var child = null, buf = '', waiting = [], err = '', ended = null;
  function start() {
    child = cp.spawn('python3', ['-c', GPS_HELPER, TOOLS, dir], { stdio: ['pipe', 'pipe', 'pipe'] });
    child.stdout.setEncoding('utf8');
    child.stdout.on('data', function (d) {
      buf += d;
      var k;
      while ((k = buf.indexOf('\n')) >= 0) {
        var line = buf.slice(0, k);
        buf = buf.slice(k + 1);
        var w = waiting.shift();
        if (w) { try { w.ok(JSON.parse(line)); } catch (e) { w.no(e); } }
      }
    });
    child.stderr.on('data', function (d) { err = (err + d).slice(-4000); });
    child.on('error', function (e) { ended = e; });
    child.on('close', function (code) {
      ended = ended || new Error('reading the GPS log failed: ' + (err || 'exit ' + code).slice(0, 400));
      waiting.splice(0).forEach(function (w) { w.no(ended); });
    });
  }
  function ask(q) {
    if (!child) start();
    return new Promise(function (ok, no) {
      if (ended) { no(ended); return; }
      waiting.push({ ok: ok, no: no });
      child.stdin.write(JSON.stringify(q) + '\n');
    });
  }
  return {
    fixes: function (fromMs, toMs, thin) { return ask(fixesAsk(fromMs, toMs, thin)); },
    at: function (timesMs) { return ask(atAsk(timesMs)); },
    close: function () { if (child && !ended) { ended = new Error('closed'); child.stdin.end(); } },
  };
}

/* The town a 2-mile cell's centre is in, by the NucBox's own Nominatim
 * (reverse, zoom 12: the town level), or null. The cell's centre is asked,
 * never a spell's own position, and the answer is kept in the cache. */
async function cellTownOf(fetchFn, nominatim, cache, c) {
  var q = '/reverse?lat=' + c.lat.toFixed(5) + '&lon=' + c.lon.toFixed(5);
  if (Object.prototype.hasOwnProperty.call(cache.answers, q)) { cache.hits += 1; return cache.answers[q].town; }
  var r;
  try {
    r = await fetchFn(nominatim.replace(/\/+$/, '') + '/reverse?format=jsonv2&zoom=12&lat=' + c.lat.toFixed(5)
                      + '&lon=' + c.lon.toFixed(5), { headers: { Accept: 'application/json' } });
  } catch (e) { return null; }
  if (!r || !r.ok) return null;
  var body = null;
  try { body = await r.json(); } catch (e) { return null; }
  var ad = (body && body.address) || {};
  var town = ad.city || ad.town || ad.village || ad.hamlet || ad.suburb || null;
  cache.answers[q] = { ok: true, town: town };
  cache.fresh += 1;
  return town;
}

/* --- the command --------------------------------------------------------- */

function inside(child, parent) {
  var rel = path.relative(parent, child);
  return rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel));
}

function realish(p) {
  // The nearest existing ancestor's real path, so a symlink into the repo is
  // caught before anything is written.
  var abs = path.resolve(p), tail = [];
  while (!fs.existsSync(abs)) { tail.unshift(path.basename(abs)); abs = path.dirname(abs); }
  return path.join.apply(null, [fs.realpathSync(abs)].concat(tail));
}

function home(p) { return p && p[0] === '~' ? path.join(os.homedir(), p.slice(1)) : p; }

function parseArgs(argv) {
  var o = { server: null, out: path.join(os.homedir(), 'places-report'), gps: null, since: null,
            nominatim: null, cache: path.join(os.homedir(), '.cache', 'uber-scan', 'places-report-answers.json'),
            gap: MV.NBX_GAP_MS, minN: MIN_N, streets: null, waits: null, relay: null, roadAsks: 5000,
            allowDegraded: false, checks: null };
  for (var i = 0; i < argv.length; i++) {
    var a = argv[i];
    var val = function () { if (i + 1 >= argv.length) throw new Error(a + ' wants a value'); return argv[++i]; };
    if (a === '--out') o.out = home(val());
    else if (a === '--gps') o.gps = home(val());
    else if (a === '--since') o.since = val();
    else if (a === '--nominatim') o.nominatim = val();
    else if (a === '--cache') o.cache = home(val());
    else if (a === '--gap') o.gap = Number(val());
    else if (a === '--min-n') o.minN = Number(val());
    else if (a === '--streets') o.streets = val();
    else if (a === '--waits') o.waits = val();
    else if (a === '--relay') o.relay = val();
    else if (a === '--road-asks') o.roadAsks = Number(val());
    else if (a === '--allow-degraded') o.allowDegraded = true;
    else if (a === '--checks') o.checks = val();
    else if (a === '-h' || a === '--help') o.help = true;
    else if (/^--/.test(a)) throw new Error('unknown option ' + a);
    else if (!o.server) o.server = a;
    else throw new Error('one server address, not two');
  }
  if (!o.server) o.server = 'http://localhost:8082';
  if (o.since && !/^\d{4}-\d\d-\d\d$/.test(o.since)) throw new Error('--since is YYYY-MM-DD');
  if (!(o.minN >= 2)) throw new Error('--min-n is a number, 2 or more');
  if (!(o.gap >= 0)) throw new Error('--gap is milliseconds');
  if (!(o.roadAsks >= 0)) throw new Error('--road-asks is a number');
  // A page's name beside index.html, never a path or a URL: it goes into an
  // href as written.
  if (o.checks !== null && !/^[A-Za-z0-9_-][A-Za-z0-9._-]*\.html$/.test(o.checks)) {
    throw new Error('--checks is a page name beside the report, e.g. checks.html');
  }
  [['--streets', o.streets], ['--waits', o.waits], ['--relay', o.relay]].forEach(function (x) {
    if (x[1] && !/^https?:\/\//.test(x[1])) throw new Error(x[0] + ' is an http(s) URL');
  });
  return o;
}

var USAGE = [
  'usage: node tools/places_report.js [http://localhost:8082] [--out ~/places-report]',
  '         [--gps ~/gpslog] [--since YYYY-MM-DD] [--nominatim http://localhost:8088]',
  '         [--cache ~/.cache/uber-scan/places-report-answers.json] [--gap ms] [--min-n 30]',
  '         [--streets URL] [--waits URL] [--relay URL] [--road-asks 5000] [--allow-degraded]',
  '         [--checks checks.html]',
  '',
  'Run on the NucBox. Reads the copy at home (its /api/journal), places pickups with the',
  'NucBox\'s own Nominatim (directly with --nominatim, else through that server\'s /api/nbx),',
  'and writes index.html and CSVs to --out, which must be outside the repository.',
  'With --gps, also the spells parked with no order in the car (the Busy tab), Drop presses',
  'timed by the GPS, and dead miles after a drop.',
  '--streets: the street index (a relay\'s .../api/nbx, or a server with one loaded); by default',
  'the server\'s relay, else its own index — asked EVEN WITH --nominatim.',
  '--waits: a server whose /api/journal carries the rig\'s store waits (the rig\'s :8080),',
  'used when the main source carries none.',
  '--relay: a server whose /api/nbx relay (search, router, street index) is asked instead of',
  'the journal\'s server\'s: the copy at home may keep the journal and the site and have no',
  'NucBox settings of its own.',
  '--road-asks: road questions the distance band may ask in all (through the relay\'s',
  '/api/nbx/route; cached).',
  '--allow-degraded: write the report even when more than ' + DEGRADED_SHARE * 100 + '% (and more than '
    + DEGRADED_MIN + ') of the',
  'fresh NucBox questions went unanswered; without it such a run writes nothing and exits 1.',
  '--checks: the page beside the report that the header links to (places_nightly.sh writes',
  'checks.html there: report_check and twin_ids, counts only).',
  'Every night: tools/places_nightly.sh (see the README, "Every night, on the NucBox").',
].join('\n');

async function main(argv) {
  var o;
  try { o = parseArgs(argv); } catch (e) {
    console.error(e.message + '\n\n' + USAGE);
    process.exitCode = 2;
    return;
  }
  if (o.help) { console.log(USAGE); return; }
  var outDir = realish(o.out), cacheFile = realish(o.cache);
  if (inside(outDir, fs.realpathSync(ROOT)) || inside(cacheFile, fs.realpathSync(ROOT))) {
    console.error('refused: the report and its cache hold real places and must not be written inside the '
                  + 'repository (' + ROOT + '). Pick --out and --cache outside it.');
    process.exitCode = 2;
    return;
  }
  var sinceMs = null;
  if (o.since) {
    var ymd = o.since.split('-').map(Number);
    sinceMs = new Date(ymd[0], ymd[1] - 1, ymd[2], A.DAY_STARTS_AT).getTime();
  }

  var body;
  try { body = await loadJournal(o.server, sinceMs); } catch (e) {
    console.error('could not read ' + o.server + ': ' + (e && e.message || e));
    process.exitCode = 1;
    return;
  }
  var offers = Array.isArray(body.offers) ? body.offers : [];
  if (body.truncated) {
    console.error('warning: the server sent ' + body.count + ' of ' + body.total
                  + ' offers (its limit, and it did not page: an older server?). Narrow the window with --since.');
  } else if (body.pages > 1) {
    console.log('journal: ' + body.count + ' offers, read in ' + body.pages + ' pages of ' + JOURNAL_PAGE);
  }

  // The relay asked: --relay, else the journal's own server.
  var relay = (o.relay || o.server).replace(/\/+$/, '');
  var settings = { search: false, streets: false, route: false };
  try {
    var s = await getJson(relay + '/api/nbx');
    if (s.ok && s.body) settings = { search: !!s.body.search, streets: !!s.body.streets, route: !!s.body.route };
  } catch (e) { /* an older server: no relay */ }
  var nominatim = o.nominatim || (settings.search ? null : 'http://localhost:8088');
  // The street index EVEN WITH --nominatim (the first real run's 662 corners
  // went unasked): --streets, else the server's relay, else its own index.
  var st = await streetsBase(relay, o.streets);
  var roadSaid = settings.route ? relay + '/api/nbx/route (the relay), at most '
    + o.roadAsks + ' questions' : 'none — ' + relay + ' has no router set (NUCBOX_ROUTER), so no distance band';
  console.log('search: ' + (nominatim ? nominatim + ' (direct)' : relay + '/api/nbx (relay)'));
  console.log('street index: ' + st.said);
  console.log('router: ' + roadSaid);

  var cache = { answers: {}, hits: 0, fresh: 0, asked: 0, unreachable: 0 };
  try {
    var held = JSON.parse(fs.readFileSync(cacheFile, 'utf8'));
    if (held && held.v === 1 && held.answers && typeof held.answers === 'object') cache.answers = held.answers;
  } catch (e) { /* none yet */ }
  function saveCache() {
    fs.mkdirSync(path.dirname(cacheFile), { recursive: true });
    var tmp = cacheFile + '.part';
    fs.writeFileSync(tmp, JSON.stringify({ v: 1, answers: cache.answers }));
    fs.renameSync(tmp, cacheFile);
  }
  var nbx = new MV.NbxSearch({ base: '/api/nbx', gap: o.gap, bandWait: BAND_WAIT_OFFLINE_MS,
    fetch: nbxFetch({ cache: cache, server: relay, nominatim: nominatim, streets: st.base,
                      onFresh: function () { if (cache.fresh % 100 === 0) saveCache(); } }) });
  var region = regionOf(offers.filter(counted));
  console.log('region for cards with no fix: ' + (region ? region.box.s + ',' + region.box.w + ' to ' + region.box.n
              + ',' + region.box.e + ' (the box round ' + region.fixes + ' good card fixes, ' + REGION_MARGIN_MI
              + ' mi wider each way)' : 'none (no good card fix in the record)'));
  var ctx = { region: region, road: settings.route, budget: { left: o.roadAsks } };

  // The GPS log, once: presses timed, drops placed, spells, dead miles.
  var taken = Array.isArray(body.taken) ? body.taken : [];
  var spanTimes = offers.filter(counted).map(seenAt).filter(isFinite);
  var fx = null, presses = null;
  // One helper for both questions of the log (gpsLog), closed however this ends.
  var gps = o.gps ? gpsLog(o.gps) : null;
  try {
    if (o.gps && spanTimes.length) {
      fx = await gps.fixes(minOf(spanTimes) - 3600e3, maxOf(spanTimes) + 3600e3);
      var tp = timePresses(taken, fx.fixes);
      taken = tp.taken;
      presses = tp.stats;
      console.log('presses timed by the GPS: ' + presses.timed + ' of ' + presses.pressed + ' (' + presses.inside
                  + ' inside a stop, ' + presses.early + ' early, ' + presses.late + ' late; ' + presses.none + ' no stop, '
                  + presses.short + ' at a stop the car had not driven the order to)');
    }

    // Taken trips: the GPS log at the drop, else the dropoff's door.
    var byId = Object.create(null);
    offers.forEach(function (row2) { if (row2 && typeof row2.id === 'string') byId[row2.id] = row2; });
    var atDoor = taken.filter(function (t) { return AT_THE_DOOR.indexOf(t.by || 'drop') >= 0 && byId[t.id]; });
    var gpsPos = Object.create(null);
    if (o.gps && atDoor.length) {
      var g = await gps.at(atDoor.map(function (t) { return t.endedAt; }));
      atDoor.forEach(function (t, j) { if (g.at[j]) gpsPos[t.id + '@' + t.endedAt] = { lat: g.at[j][0], lon: g.at[j][1] }; });
      console.error('GPS log: ' + g.files + ' files, ' + g.passed + ' usable fixes, '
                    + Object.keys(gpsPos).length + ' of ' + atDoor.length + ' drops placed by it');
    }
  } finally {
    if (gps) gps.close();
  }
  var dropPins = Object.create(null);
  for (var t = 0; t < atDoor.length; t++) {
    var trip = atDoor[t], key = trip.id + '@' + trip.endedAt;
    if (gpsPos[key]) continue;
    var at = await placeDropoff(nbx, byId[trip.id].dropoff, byId[trip.id], !!st.base, { region: region });
    if (at) dropPins[key] = at;
  }
  saveCache();
  // Where each taken order ended, for the cards read while it was in the car
  // (heldEndsOf, afterFor): the GPS at its drop, else its dropoff placed.
  var heldEnds = await heldEndsOf(nbx, taken, byId, gpsPos, !!st.base, region);
  saveCache();

  // Every pickup the rig stands behind, asked once per (text, card disc box).
  var placed = new Array(offers.length);
  var memo = new Map();
  var todo = 0, done = 0, inCar = 0;
  offers.forEach(function (row) { if (counted(row) && row.pickup) todo += 1; });
  for (var i = 0; i < offers.length; i++) {
    var row = offers[i];
    if (!counted(row) || !row.pickup) continue;
    // ...searched from the ends of the orders in the car when it came up as
    // well (afterFor: the `also` circles the rig gives such a card).
    var after = afterFor(row, heldEnds);
    if (after.length) inCar += 1;
    var card = after.length ? Object.assign({}, row, { after: after }) : row;
    var disc = MV.discFor(card);
    var spec = settings.route ? MV.bandTarget(row, 'pickup') : null;
    // (Its printed door in the key as well: one store's name with two doors
    // is two questions — placeRow asks the door first.)
    var k = (printedDoor(row) || '') + '\u0001' + row.pickup + '\u0000' + (disc ? MV.discBox(disc) + '/' + disc.miles.toFixed(2)
                                          + '/' + disc.at.lat.toFixed(3) + ',' + disc.at.lon.toFixed(3) : '-')
      + (spec ? '/' + spec.miles + (spec.upper ? '+' : '') : '')
      + (after.length ? '/also ' + MV.discBox(disc) + ' ' + after.map(function (e) {
        return e.lat.toFixed(4) + ',' + e.lon.toFixed(4) + '+' + e.widen;
      }).join(';') : '');
    if (!memo.has(k)) memo.set(k, await placeRow(nbx, card, !!st.base, ctx));
    placed[i] = memo.get(k);
    done += 1;
    if (done % 200 === 0) console.error('  pickups ' + done + ' of ' + todo + ' (' + cache.fresh + ' asked, '
                                        + cache.hits + ' from the cache)');
  }
  saveCache();
  console.log('offers read with an order in the car, searched from its end too: ' + inCar);

  // A NucBox down for the run: nothing written, so the nightly keeps the
  // report it has (review, 27 Oct: it used to write one with the offers
  // unplaced and swap it in).
  var down = degraded(cache);
  if (down) {
    var downSaid = down.unreachable + ' of ' + down.asked + ' fresh NucBox questions went unanswered (the search, '
      + 'Nominatim or the relay down?)';
    if (!o.allowDegraded) {
      console.log('NOT WRITTEN: ' + downSaid + '; the report would leave those offers unplaced. '
                  + 'Run again when it answers, or pass --allow-degraded.');
      process.exitCode = 1;
      return;
    }
    console.log('DEGRADED, written anyway (--allow-degraded): ' + downSaid);
  }

  function dropAt(tr) {
    var kk = tr.id + '@' + tr.endedAt;
    if (gpsPos[kk]) return { at: gpsPos[kk], how: 'gps' };
    if (dropPins[kk]) return { at: dropPins[kk], how: 'pin' };
    return cardFixAfter(offers, tr.endedAt);
  }

  // Spells parked with no order in the car, over the record's own span.
  var spells = null, cellTown = Object.create(null);
  if (fx) {
    spells = spellsOf(fx.fixes, heldOf(taken));
    console.error('spells: ' + spells.length + ' parked with no order in the car, off ' + fx.fixes.length
                  + ' fixes (one per ' + SPELL_THIN_S + ' s)');
    if (nominatim || o.nominatim) {
      var seenCells = Object.create(null);
      for (var si = 0; si < spells.length; si++) {
        var sc = cellOf(spells[si]);
        if (!sc || seenCells[sc.id]) continue;
        seenCells[sc.id] = true;
        cellTown[sc.id] = await cellTownOf(fetch, nominatim || o.nominatim, cache, sc);
      }
      saveCache();
    }
  }

  // ...and the towns of the cells the car's own fixes fall in (the Waited
  // tab), named by the same reverse lookup and cache.
  if (nominatim || o.nominatim) {
    var fixCells = Object.create(null);
    for (var fi = 0; fi < offers.length; fi++) {
      var ff = counted(offers[fi]) ? MV.fixOf(offers[fi]) : null;
      var fc = ff ? cellOf(ff) : null;
      if (!fc || fixCells[fc.id] || fc.id in cellTown) continue;
      fixCells[fc.id] = true;
      cellTown[fc.id] = await cellTownOf(fetch, nominatim || o.nominatim, cache, fc);
    }
    saveCache();
  }

  // Store waits: the source's, else the rig's (--waits) when the source has none.
  var waits = Array.isArray(body.waits) ? body.waits : [];
  var waitsFrom = waits.length ? o.server : null;
  if (!waits.length && o.waits) {
    try {
      waits = await loadWaits(o.waits);
      waitsFrom = o.waits;
    } catch (e) { console.error('store waits: ' + (e && e.message || e) + '; none used'); }
  }
  console.log('store waits: ' + waits.length + (waitsFrom ? ' from ' + waitsFrom : ' (none on record)'));

  var earnings = await loadEarnings(o.server);
  console.log('earnings: ' + earnings.length + ' trips read off uploaded screenshots');

  var gold = await loadGold(o.server);

  var report = analyse(offers, taken, placed, dropAt, {
    minN: o.minN, waits: waits, spells: spells, cellTown: cellTown, fixes: fx ? fx.fixes : null,
    earnings: earnings, gold: gold,
    // The order records (server.js orderRecords, since 7 Nov): the Strategy
    // tab's miles where an order left one. An older server sends none.
    records: Array.isArray(body.records) ? body.records : [],
    presses: presses, region: region, streetsSaid: st.said, roadSaid: roadSaid, waitsFrom: waitsFrom,
    source: { server: o.server, count: body.count, total: body.total, pages: body.pages || 1,
              truncated: !!body.truncated, since: o.since, checks: o.checks } });
  fs.mkdirSync(outDir, { recursive: true });
  fs.writeFileSync(path.join(outDir, 'index.html'), html(report));
  // Every CSV through one door, so none is written without csv.js's BOM.
  function writeCsv(name, text) { fs.writeFileSync(path.join(outDir, name), CSV.BOM + text); }
  writeCsv('places.csv', csvOf(report, 'place'));
  writeCsv('towns.csv', csvOf(report, 'town'));
  writeCsv('grid.csv', csvOf(report, 'grid'));
  writeCsv('dropoff_towns.csv', dropCsv(report, 'dropTown'));
  writeCsv('dropoff_grid.csv', dropCsv(report, 'dropGrid'));
  writeCsv('coverage.csv', coverageCsv(report));
  writeCsv('restaurants.csv', restCsv(report));
  writeCsv('restaurant_branches.csv', restBranchCsv(report));
  writeCsv('top_share_tests.csv', shareCsv(report));
  writeCsv('coverage_levels.csv', levelsCsv(report));
  writeCsv('strategy_curve.csv', strategyCsv(report));
  Object.keys(MORE_CSVS).forEach(function (name) {
    writeCsv(name, tableCsv(report, MORE_CSVS[name][0], MORE_CSVS[name][1]));
  });
  console.log(summary(report));
  console.log('\nWritten: ' + path.join(outDir, 'index.html') + ' (and ' + (11 + Object.keys(MORE_CSVS).length)
              + ' CSVs beside it)');
  console.log('NucBox questions: ' + cache.fresh + ' asked, ' + cache.hits + ' answered from ' + cacheFile);
}

module.exports = {
  JOURNAL_PAGE: JOURNAL_PAGE, loadJournal: loadJournal, hitsOf: hitsOf, DEGRADED_SHARE: DEGRADED_SHARE,
  DEGRADED_MIN: DEGRADED_MIN, degraded: degraded, nbxFetch: nbxFetch, streetsBase: streetsBase,
  loadEarnings: loadEarnings, loadWaits: loadWaits, gpsAt: gpsAt, gpsFixes: gpsFixes, gpsLog: gpsLog, cellTownOf: cellTownOf,
  inside: inside, realish: realish, parseArgs: parseArgs, main: main,
};
