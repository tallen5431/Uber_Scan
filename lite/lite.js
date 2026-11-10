/* The lite edition, as the server sees it: one bit, read once, and the few
 * places it is asked.
 *
 *   var Lite = require('./lite/lite.js');
 *   var LITE = Lite.on(ROOT, process.env);
 *
 * WHY A MODE AND NOT A COPY (the owner's decision, Nov 2026; CLAUDE.md, and
 * AUDITS.md under Settled). Lite is for drivers who want the camera to read
 * the offer and one big card to say whether it is worth it — a display, no
 * touch screen, on at boot. Everything that decides what that card says (the
 * reader, the parser, CENTS_LOST, unsure_payout, money_is_clipped, the rescue
 * rules, the card finder, DoorDash's raise and evened read, the remembered
 * crop) is the full rig's own code, and a fix to any of it has to reach both
 * on the day it is made. So the full server runs, and this file only says
 * which of its doors are shut.
 *
 * WHAT IS SHUT, and why each:
 *   - the NucBox, all of it (search, route, streets — and so pins, Map view's
 *     run, map labels on a card, the planner's fastest order, store searches):
 *     server.js empties its NBX bases at boot, which every one of those
 *     already treats as "not set here", the ordinary install's state. Not one
 *     question leaves the rig; rpi/test_lite.py counts them on the fake.
 *   - the places report and the shift report (/places, /api/placeslink,
 *     /api/shift, shift.html): reports over weeks of data, run parked, on the
 *     full rig's machine at home.
 *   - earnings screenshots (/api/earnings*): an OCR job of its own on the Pi.
 *   - the journal's ingest (/api/journal/ingest): that is the copy machine's
 *     door, and a lite rig is never the copy. Its own sync is off in
 *     rpi/sync.py, and lite/install.sh installs no timer.
 *   - the pins Map view posts (/api/held-end, /api/held-pickup) and its walk
 *     (/api/mapwalk): there is no map to post them from.
 *   - map.html: a page that is nothing but the NucBox's answers.
 * Refused with 404 and a JSON body saying "lite", so a page that asks finds
 * an answer it already handles (a refused fetch) and a person who asks finds
 * out why.
 *
 * WHAT IS KEPT, deliberately: the camera and its aim, calibration, ▣ Set box
 * and the settings (on live.html and index.html, for a phone on the same
 * Wi-Fi — the panel itself needs no touch), the reader and every money rule,
 * the verdict against the driver's own target and cost per mile, speech, and
 * the journal (the local offers log, and /api/journal to read it).
 *
 * READ ONCE, at boot, unlike carryTwo and screenDrop in server.js which are
 * read per call: those are switches inside a running shift; this is which
 * program is running. LITE=1/0 in the environment first, then `"lite": true`
 * in rpi/config.json's settings, exactly as rpi/lite.py reads it — the scanner
 * the server spawns inherits the same environment and reads the same file, so
 * the two halves cannot disagree. Anything unreadable is the full rig.
 */
'use strict';

var fs = require('fs');
var path = require('path');

// Where the panel lives. `/` goes here under lite (see answer()).
var PAGE = '/lite/lite.html';

function fromConfig(root) {
  try {
    var cfg = JSON.parse(fs.readFileSync(path.join(root, 'rpi', 'config.json'), 'utf8'));
    return !!(cfg && cfg.settings && typeof cfg.settings === 'object'
              && cfg.settings.lite === true);
  } catch (e) {
    return false;
  }
}

function on(root, env) {
  var v = (env || {}).LITE;
  if (v === '1') return true;
  if (v === '0') return false;
  return fromConfig(root);
}

// The doors shut under lite: [test, what it was, for /api/lite and the 404].
// Paths, not methods: a GET of /api/earnings is as much the feature as a POST.
var OFF = [
  [/^\/places(\/|$)/, 'the places report'],
  [/^\/api\/placeslink$/, 'the places report'],
  [/^\/api\/shift$/, 'the shift report'],
  [/^\/shift\.html$/, 'the shift report'],
  [/^\/api\/earnings(\/|$)/, 'earnings screenshots'],
  [/^\/api\/journal\/ingest$/, 'the journal copy (sync)'],
  [/^\/api\/held-(end|pickup)$/, 'map pins'],
  [/^\/api\/mapwalk$/, 'Map view'],
  [/^\/map\.html$/, 'Map view']
];

// What lite says it keeps, for /api/lite — the same list as lite/README.md.
var KEEPS = ['camera and aim', 'calibration', 'Set box', 'settings',
             'the reader and every money-safety rule',
             'the verdict ($/hr, $/mi, pay, minutes, miles against your target and cost per mile)',
             'spoken verdict (optional)', 'the offers log'];
var OFF_NAMES = ['the NucBox (search, routes, streets, pins, maps, fastest order, store searches)']
  .concat(OFF.map(function (o) { return o[1]; }).filter(function (w, i, a) {
    return a.indexOf(w) === i;
  }))
  .concat(['map label reads and map bands on the scanner (rpi/lite.py)',
           'journal sync (rpi/sync.py)']);

// What was shut for this path, or null.
function shut(pathname) {
  for (var i = 0; i < OFF.length; i++) if (OFF[i][0].test(pathname)) return OFF[i][1];
  return null;
}

/* Asked first by server.js's handler, before its own routing. Returns true
 * when it answered. `lite` is the boot-time bit; `send` is server.js's own
 * (so the headers are the same as every other answer). /api/lite is answered
 * either way, so the panel and a test can ask which program is running. */
function answer(lite, req, res, send) {
  var pathname;
  try { pathname = decodeURIComponent(String(req.url || '').split('?')[0]); } catch (e) {
    return false;   // server.js's own route() answers a bad URL, as ever
  }
  var json = { 'Content-Type': 'application/json; charset=utf-8' };
  if (pathname === '/api/lite') {
    send(res, 200, JSON.stringify(lite ? { lite: true, page: PAGE, off: OFF_NAMES, keeps: KEEPS }
                                       : { lite: false }), json);
    return true;
  }
  if (!lite) return false;
  if (pathname === '/' && (req.method === 'GET' || req.method === 'HEAD')) {
    // A redirect, not the page served under `/`: its address then says what
    // it is, and the keypad stays at /index.html for a phone that wants it.
    res.writeHead(302, { Location: PAGE, 'Cache-Control': 'no-cache' });
    res.end();
    return true;
  }
  var what = shut(pathname);
  if (what) {
    send(res, 404, JSON.stringify({ ok: false, lite: true,
                                    error: what + ': not part of the lite edition' }), json);
    return true;
  }
  return false;
}

/* The NucBox's three bases, emptied: what every NucBox path in server.js
 * already reads as "not set here" — no probe, no search, no route, no pin.
 * In place, so anything holding the object sees it. */
function noNucbox(nbx) {
  Object.keys(nbx).forEach(function (k) { nbx[k] = null; });
  return nbx;
}

module.exports = { on: on, answer: answer, shut: shut, noNucbox: noNucbox,
                   PAGE: PAGE, OFF: OFF, OFF_NAMES: OFF_NAMES, KEEPS: KEEPS };
