#!/usr/bin/env node
/* Static file server for Uber Scan.
 *
 * This project is a website, not a Node program — the JavaScript in it runs in
 * a browser. Hosts that look for a Node entry point should land here, which is
 * why package.json points "main" and "start" at this file.
 *
 *   node server.js              # http://localhost:8080
 *   PORT=3000 node server.js
 *
 * No dependencies, so there is nothing to install first.
 */

'use strict';

var http = require('http');
var https = require('https');
var fs = require('fs');
var path = require('path');
var url = require('url');

var os = require('os');
var spawn = require('child_process').spawn;

var ROOT = __dirname;
var PORT = parseInt(process.env.PORT, 10) || 8080;
var HTTPS_PORT = parseInt(process.env.HTTPS_PORT, 10) || 8443;
var HOST = process.env.HOST || '0.0.0.0';
var SSL_DIR = path.join(ROOT, 'ssl');

var TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.webmanifest': 'application/manifest+json; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.wasm': 'application/wasm',
  '.txt': 'text/plain; charset=utf-8',
  // Served as an opaque blob on purpose. This is the OCR language model, which
  // the reader inflates itself — labelling it Content-Encoding: gzip would have
  // the browser silently decompress it first and hand the reader garbage.
  '.gz': 'application/octet-stream'
};

/* Things that must never leave the machine, however they are asked for.
 *
 * This server sits on a LAN, on plain http, with no authentication — every
 * file under ROOT is one GET away from anyone on the same wifi. That is fine
 * for a page of HTML and catastrophic for `ssl/ca-key.pem`, which is the
 * private key of the certificate authority `tools/make-cert.sh` asks you to
 * install on your phone as a trust anchor. Anyone who fetches it can mint a
 * certificate your phone will believe, for any site.
 *
 * `rpi/` is denied because nothing there is meant for a browser: the live
 * frame has its own route, and config.json is the rig's calibration.
 */
var PRIVATE = /(^|\/)(ssl|rpi|node_modules|\.git)(\/|$)|(^|\/)\./i;
var SECRET_EXT = /\.(pem|key|crt|cer|p12|pfx|jks)$/i;

function isPrivate(pathname) {
  return PRIVATE.test(pathname) || SECRET_EXT.test(pathname);
}

/* ---------- the Pi scanner, as a child of this process ----------
 *
 * Started automatically when rpi/config.json exists, because that file only
 * exists once the camera has been aimed and calibrated — which is exactly the
 * point at which running the scanner starts making sense. There is no
 * environment variable to set, since a process manager runs `npm start` with no
 * shell to set one in. SCANNER=0 turns it off.
 */
var scanner = {
  proc: null,
  last: null,          // most recent read
  phase: null,         // check / aim / calibrated / scanning / error
  status: null,        // most recent non-read message, e.g. aiming progress
  started: null,
  restarts: 0,
  error: null
};

var listeners = [];    // open server-sent-event responses

// How long a scanner has to stay up before its next exit counts as a fresh
// problem rather than another rung of the same one. Comfortably longer than the
// camera takes to open and fail, comfortably shorter than a shift.
var HEALTHY_RUN_MS = 60000;

// The autopilot calibrates itself, so it runs whenever the Pi scanner code is
// present — waiting for a config file would mean waiting for a manual step that
// no longer exists.
function scannerEnabled() {
  if (process.env.SCANNER === '0') return false;
  try {
    fs.statSync(path.join(ROOT, 'rpi', 'autopilot.py'));
    return true;
  } catch (e) {
    return false;
  }
}

function calibrated() {
  try {
    fs.statSync(path.join(ROOT, 'rpi', 'config.json'));
    return true;
  } catch (e) {
    return false;
  }
}

function startScanner() {
  var cmd = process.env.SCANNER_CMD;
  var args = cmd ? [] : [path.join(ROOT, 'rpi', 'autopilot.py'), '--json'];
  var bin = cmd || 'python3';
  if (cmd) args = process.env.SCANNER_ARGS ? process.env.SCANNER_ARGS.split(' ') : [];
  if (process.env.SCANNER_SPEAK !== '0' && !cmd) args.push('--speak');

  scanner.proc = spawn(bin, args, { cwd: ROOT });
  scanner.started = Date.now();
  scanner.error = null;
  console.log('scanner: started ' + bin + ' ' + args.join(' '));

  // Without this, a missing python3 or a bad SCANNER_CMD emits an 'error' with
  // nothing listening, which in Node is an uncaught exception — so the failure
  // to start the scanner takes down the web server that was reporting on it.
  // The site is meant to keep working when the camera side does not.
  scanner.proc.on('error', function (err) {
    scanner.error = 'could not start ' + bin + ': ' + err.message;
    console.error('scanner: ' + scanner.error);
  });

  // ...and the pipes are not guaranteed to exist. When the process runs out of
  // file descriptors there are none left to build them from, so spawn returns a
  // child whose `stdout` and `stderr` are undefined, and reading `.on` off that
  // throws a TypeError right here — synchronously, inside the caller, taking
  // down the web server that was about to report the problem.
  //
  // That is not a hypothetical pairing. Until the fix a few hundred lines below
  // this, every download a phone abandoned leaked a descriptor, so a rig that
  // had been up long enough arrived at exactly this state and then died on its
  // next scanner restart. The 'close' handler underneath already knows what to
  // do about EMFILE — it names it — and it only ever needed the chance to run.
  if (!scanner.proc.stdout || !scanner.proc.stderr) {
    scanner.error = 'could not attach to ' + bin + ': no pipes (out of file '
                  + 'descriptors?). Retrying.';
    console.error('scanner: ' + scanner.error);
    return;
  }

  var buffered = '';
  scanner.proc.stdout.on('data', function (chunk) {
    buffered += chunk.toString();
    var lines = buffered.split('\n');
    buffered = lines.pop();          // keep the partial line for next time
    lines.forEach(function (line) {
      line = line.trim();
      if (!line) return;
      try {
        var read = JSON.parse(line);
        read.at = Date.now();
        if (read.phase) {
          scanner.phase = read.phase;
          scanner.status = read;
          if (read.message) console.log('scanner[' + read.phase + ']: ' + read.message);
        }
        // Setup messages carry no rate, so they must not overwrite the last read.
        if (read.ready !== undefined) scanner.last = read;
        broadcast(read);
      } catch (e) {
        console.log('scanner: ' + line);   // not JSON, so it is a log line
      }
    });
  });

  scanner.proc.stderr.on('data', function (c) {
    var text = c.toString().trim();
    if (text) console.error('scanner: ' + text);
    scanner.error = text.split('\n').slice(-3).join(' ');
  });

  // 'close', not 'exit'. A process that starts and then dies emits both, but a
  // process that never starts at all — python3 missing, SCANNER_CMD wrong or
  // not executable, EMFILE — emits 'error' and then 'close' and *never* 'exit'.
  // Hanging the retry off 'exit' meant that case scheduled nothing, ever:
  // scanner.proc stayed set so /api/status kept answering running:true, the
  // live page kept its green dot and WAITING FOR AN OFFER, and every offer of
  // the shift was missed with nothing on screen admitting it. The comment above
  // names this exact failure and only half of it was handled.
  scanner.proc.on('close', function (code, signal) {
    console.error('scanner: exited (' + (signal || code) + ')');
    var ranFor = Date.now() - scanner.started;
    scanner.proc = null;
    if (shuttingDown) return;
    // Back off so a camera that is missing or busy does not spin the CPU.
    //
    // The count is of *consecutive* failures, which is what a backoff is for,
    // and it used to be a lifetime tally. A rig that had scanned all day and hit
    // four unrelated hiccups was thereafter 48 seconds from restarting after any
    // of them — 48 seconds of a shift with the camera off, because of things
    // that had gone right hours earlier. A child that stayed up long enough to
    // be doing its job did not fail to start, so the ladder resets.
    if (ranFor > HEALTHY_RUN_MS) scanner.restarts = 0;
    scanner.lifetimeRestarts = (scanner.lifetimeRestarts || 0) + 1;
    var delay = Math.min(60000, 3000 * Math.pow(2, Math.min(scanner.restarts, 4)));
    scanner.restarts++;
    console.error('scanner: retrying in ' + Math.round(delay / 1000) + 's');
    setTimeout(startScanner, delay);
  });
}

var WATCH_PATH = path.join(ROOT, 'rpi', '.viewing');
var RESET_PATH = path.join(ROOT, 'rpi', '.recalibrate');
// Where a box drawn on the live view is left for the camera side to pick up.
// A file, like the two above, because the scanner is sometimes a child of this
// process and sometimes a systemd unit that has never heard of it.
var CROP_PATH = path.join(ROOT, 'rpi', '.cropbox.json');
var cropSeq = 0;
var lastTouch = 0;

function touchWatchFile() {
  var now = Date.now();
  if (now - lastTouch < 1000) return;      // the mtime only needs to be recent
  lastTouch = now;
  fs.writeFile(WATCH_PATH, '', function () {});
}

function broadcast(read) {
  var payload = 'data: ' + JSON.stringify(read) + '\n\n';
  listeners = listeners.filter(function (res) {
    try {
      res.write(payload);
      return true;
    } catch (e) {
      return false;
    }
  });
}

// A throw nobody caught costs one request, not the shift.
//
// Node's advice is to let the process die here, and for a server behind a
// supervisor with load balanced away from it that is right. This is not that.
// This is a single box velcroed into a car with no supervisor above it, and the
// thing it is doing at the moment it dies is the reason the driver is looking
// at it. Coming back up wrong is better than not coming back.
//
// It also cannot be replaced by wrapping the handlers, and that is the point:
// most of this server's work happens in fs callbacks, and by the time one of
// those runs the request's stack — and any try/catch on it — is long gone. One
// journal row stamped 1e20 took the whole server down from inside readFile,
// with the request-level try/catch two frames too far away to see it.
//
// Deliberately not a recovery mechanism. It logs loudly and carries on so the
// fault is findable, rather than swallowing it into a shrug.
process.on('uncaughtException', function (err) {
  console.error('uncaught: ' + ((err && err.stack) || err));
  console.error('  the request that caused it is lost; the server is still up.');
});
process.on('unhandledRejection', function (reason) {
  console.error('unhandled rejection: ' + ((reason && reason.stack) || reason));
});

var shuttingDown = false;
['SIGTERM', 'SIGINT'].forEach(function (sig) {
  process.on(sig, function () {
    shuttingDown = true;
    if (scanner.proc) scanner.proc.kill('SIGTERM');
    process.exit(0);
  });
});

// Where the scanner keeps its offers. Overridable for the same reason the
// scanner's --journal is: the two have to name the same file, and a mismatch is
// silent — the page just says "no offers recorded yet" while the scanner
// happily writes somewhere else.
var JOURNAL_PATH = process.env.JOURNAL || path.join(ROOT, 'rpi', 'journal.jsonl');

/* Where the scanner leaves the live view.
 *
 * It belongs in RAM, not on the card. The view refreshes about fourteen times a
 * second while someone is watching, at ~50kB a frame — roughly 2.5GB an hour
 * written to the SD card, against about 19MB a *year* for the journal. Every
 * byte of it is stale two frames later and none of it needs to survive a
 * reboot, so writing it to the one part of this system that wears out was
 * paying a real cost for nothing. pipeline.py already stages its OCR images in
 * /dev/shm for exactly this reason; the live frame simply never got the same
 * treatment.
 *
 * Resolved per request rather than once, and by mtime rather than existence,
 * because the two sides pick their path independently — this file is JavaScript
 * and the scanner is Python, and nothing detects a mismatch: the page would
 * simply say "no camera view yet" while the scanner wrote happily somewhere
 * else. Taking whichever candidate is freshest means the view keeps working
 * whichever the scanner chose, including on a rig running an old scanner
 * against a new server. Two stats per request, at fourteen requests a second,
 * against reading a 50kB JPEG — not worth caching.
 */
var FRAME_CANDIDATES = [
  process.env.FRAME,
  '/dev/shm/uberscan-live.jpg',
  path.join(ROOT, 'rpi', 'live-frame.jpg')
].filter(Boolean);

// How often to look for a newer frame, and how many viewers may stream at once.
// The poll is a stat() on a file in RAM — microseconds — and the cap is a
// backstop against a page left open in twenty tabs rather than an expected
// limit: a car has one screen and maybe a phone.
var MJPEG_POLL = 12;
var MAX_MJPEG = 6;
var MJPEG_BOUNDARY = 'uberscanframe';
var mjpegClients = 0;

function framePath() {
  if (process.env.FRAME) return process.env.FRAME;
  var best = null;
  var newest = -1;
  FRAME_CANDIDATES.forEach(function (candidate) {
    try {
      var stat = fs.statSync(candidate);
      if (stat.mtimeMs > newest) { newest = stat.mtimeMs; best = candidate; }
    } catch (e) { /* not there; try the next */ }
  });
  return best || FRAME_CANDIDATES[FRAME_CANDIDATES.length - 1];
}

// Columns worth putting in a spreadsheet, in the order a person reads them.
// Not every field in the row: `content` is an internal fingerprint and `v`,
// `seq` and `id` only matter to whatever is collapsing the rows, which has
// already happened by the time anything gets here.
var CSV_COLUMNS = ['at', 'pay', 'minutes', 'billedMinutes', 'miles', 'items',
                   'perHour', 'grossPerHour', 'perMile', 'cost', 'state',
                   'target', 'band', 'costPerMile', 'legs', 'mergedFrom', 'hasTotal', 'shop',
                   'milesCorrected', 'milesUncertain', 'whole', 'settled',
                   // `suspect` says not to trust a row; `doubt` says which
                   // figure to go and look at. A spreadsheet full of rows
                   // flagged 1 with nothing saying why is a column people learn
                   // to ignore.
                   // `hidden` only ever appears with ?hidden=1, and without it
                   // that export is a spreadsheet with the driver's own test
                   // card silently mixed into it and no way to tell which row
                   // it is — which is the entire reason they hid it.
                   'suspect', 'doubt', 'accepted', 'hidden',
                   // Where it went, joined with a semicolon so one cell holds
                   // both ends of a ride without breaking the comma-separated
                   // file it sits in.
                   'places', 'deliverBy', 'fromDeadline', 'ms'];

function numOrNull(v) {
  return (typeof v === 'number' && isFinite(v)) ? v : null;
}

// Smaller than this either way and it is a mis-tap, not a box: at 5% of a
// 2328px frame the card would be 116px tall against a 380px floor, so there is
// nothing readable inside it. Kept in step with rpi/cropbox.py, which checks
// the same thing again on the way in — this side is here so a bad drag comes
// back as a 400 rather than sitting in a file the scanner then ignores.
var MIN_CROP_SIDE = 0.05;

function fractionOrNull(v) {
  if (typeof v !== 'number' || !isFinite(v)) return null;
  return Math.min(1, Math.max(0, v));
}

// A crop request as four corners in fractions of the frame, ordered top-left,
// top-right, bottom-right, bottom-left — or a string saying what was wrong
// with it. Takes a dragged rectangle (`box`) or four corners (`quad`), for a
// box that has to be skewed onto an off-axis screen.
function cropQuad(body) {
  var points;
  if (Array.isArray(body.quad)) {
    if (body.quad.length !== 4) return 'a quad needs four corners';
    points = [];
    for (var i = 0; i < 4; i++) {
      var p = body.quad[i];
      if (!Array.isArray(p) || p.length !== 2) return 'each corner is an [x, y] pair';
      var x = fractionOrNull(p[0]), y = fractionOrNull(p[1]);
      if (x === null || y === null) return 'corners must be numbers';
      points.push([x, y]);
    }
  } else if (Array.isArray(body.box)) {
    if (body.box.length !== 4) return 'a box needs x, y, w, h';
    var b = body.box.map(fractionOrNull);
    if (b.indexOf(null) !== -1) return 'corners must be numbers';
    points = [[b[0], b[1]], [Math.min(1, b[0] + b[2]), b[1]],
              [Math.min(1, b[0] + b[2]), Math.min(1, b[1] + b[3])],
              [b[0], Math.min(1, b[1] + b[3])]];
  } else {
    return 'expected a box or a quad';
  }

  var xs = points.map(function (p) { return p[0]; });
  var ys = points.map(function (p) { return p[1]; });
  if (Math.max.apply(null, xs) - Math.min.apply(null, xs) < MIN_CROP_SIDE ||
      Math.max.apply(null, ys) - Math.min.apply(null, ys) < MIN_CROP_SIDE) {
    return 'that box is too small to read anything from — drag a bigger one';
  }
  // Ordered here rather than trusted: the same drag started from the bottom
  // right is the same box, and the scanner warps whatever order it is given.
  var by = function (score, pick) {
    return points.reduce(function (best, p) {
      return pick(score(p), score(best)) ? p : best;
    });
  };
  var sum = function (p) { return p[0] + p[1]; };
  var diff = function (p) { return p[1] - p[0]; };
  var lower = function (a, b) { return a < b; };
  var higher = function (a, b) { return a > b; };
  return [by(sum, lower), by(diff, lower), by(sum, higher), by(diff, higher)];
}

// Small on purpose. Nothing this server accepts is bigger than a couple of
// numbers, so a body that keeps arriving is not a large request, it is a client
// that should be hung up on.
var MAX_BODY = 4096;

// ...except a journal upload, which is a batch of rows rather than a couple of
// numbers. A week of driving is about 400KB; this is the ceiling that stops a
// mistake filling the disk, not a target.
var MAX_SYNC_BODY = 8 * 1024 * 1024;

// Unset by default: the rig this was written for keeps the whole machine behind
// a VPN, so the upload has no secret to carry. Set it and the ingest endpoint
// starts requiring an X-Sync-Token header that matches.
var SYNC_TOKEN = process.env.SYNC_TOKEN || '';

function readBody(req, cap, done) {
  var text = '';
  var over = false;
  req.on('data', function (chunk) {
    if (over) return;
    text += chunk;
    if (text.length > cap) { over = true; req.destroy(); done(new Error('too big')); }
  });
  req.on('error', function () { if (!over) { over = true; done(new Error('aborted')); } });
  req.on('end', function () { if (!over) { over = true; done(null, text); } });
}

function readJsonBody(req, done) {
  var text = '';
  var over = false;
  req.on('data', function (chunk) {
    if (over) return;
    text += chunk;
    if (text.length > MAX_BODY) { over = true; req.destroy(); done(new Error('too big')); }
  });
  req.on('error', function () { if (!over) { over = true; done(new Error('aborted')); } });
  req.on('end', function () {
    if (over) return;
    over = true;
    try {
      var parsed = JSON.parse(text || '{}');
      done(null, (parsed && typeof parsed === 'object') ? parsed : null);
    } catch (e) {
      done(e);
    }
  });
}

function clampNumber(raw, low, high, fallback) {
  var n = parseInt(raw, 10);
  if (!isFinite(n)) return fallback;
  return Math.max(low, Math.min(high, n));
}

// The scanner appends a further row for the same offer every time it looks
// again, so an id arrives as several readings and one of them has to be picked
// — see bestReading. Rows written before ids existed, or by something else,
// keep their own identity.
//
// Annotations live in the same file and are told apart by carrying a `kind`,
// which an offer never does. They are applied over the offers here rather than
// stored on them, because the file is append-only in both directions: the
// scanner adds offers while this adds notes, and neither can safely rewrite a
// line the other might be reading.
// What makes a row the same row, so sending it twice changes nothing.
//
// A reading of an offer carries an `id` and a `seq`, and that pair is its
// identity: a better read of a card already seen is the same id at a higher
// seq. That was once the only shape a row came in, so the sync simply demanded
// both — and threw away, quietly and under a `malformed` count nobody reads,
// the one kind of row a driver produces by hand. A mark ("I took this one") has
// an id but no seq. A rule ("stop showing me my own test card") has neither,
// because on the machine that wrote it there is one journal and nothing to
// de-duplicate against.
//
// So a note is identified by when it was written and what it said. Both are
// fixed the moment it lands on disk and neither is rewritten, which makes it
// survive being sent again exactly as cleanly as a reading does — and means
// notes already sitting in a journal sync across without being touched.
function syncKey(row) {
  if (!row || typeof row !== 'object') return null;
  // JSON, not concatenation with a separator.
  //
  // Joining the parts with '/' meant a key could be forged by a value that
  // contained one: id 'a/1' at seq 2 and id 'a' at seq '1/2' produced the
  // identical string 'o/a/1/2', and the second row was then discarded as a
  // duplicate of the first. Nothing this project writes contains a slash, but
  // this endpoint takes rows from off the machine, and "our own writer happens
  // not to do that" is not a property the receiver can rely on when what is at
  // stake is silently dropping an offer.
  var key = function (parts) { return JSON.stringify(parts); };
  if (row.kind === 'mark') {
    if (typeof row.id !== 'string' || !row.id) return null;
    return key(['m', row.id, row.at, row.accepted, row.hidden]);
  }
  if (row.kind === 'rule') {
    var m = row.match || {};
    return key(['r', row.at, m.pay, m.minutes, m.miles, row.accepted, row.hidden]);
  }
  // Anything else needs the pair. A kind this build has never heard of is
  // carried across rather than dropped, as long as it can say which row it is:
  // the copy is meant to outlive the build that filled it.
  //
  // `undefined` was the only thing rejected, so `id: null` sailed through and
  // every id-less row in a batch collapsed onto the one key "o/null/1" — the
  // first was stored and the rest thrown away as duplicates of it. null is not
  // an identity.
  if (row.id === null || row.id === undefined || row.id === '') return null;
  if (row.seq === null || row.seq === undefined) return null;
  return key([row.kind ? 'k' + row.kind : 'o', row.id, row.seq]);
}

/* Which reading of one card to believe, out of the several the rig took.
 *
 * It used to be simply the last: a later row about the same id supersedes the
 * earlier one, on the reasoning that a reading improves as the accumulator
 * collects the legs a single frame missed. That is usually true and it is not
 * always true — the scanner also re-reads a card every few seconds for as long
 * as it is on the screen, and any one of those can be the bad one. Being last
 * is not evidence of being right.
 *
 * So they vote. One real card read four times gave 31min/15.1mi, then a lost
 * decimal point in the payout, then a bad merge at 40min/23.6mi, then
 * 31min/15.1mi again — and the majority is the right answer, whichever order
 * they arrived in.
 *
 * A whole row is chosen rather than a field-by-field composite. A row is
 * internally consistent — its $/hr was worked out from its own pay, minutes and
 * miles — and stitching the best of each together would produce a row whose
 * headline does not follow from the figures printed beside it, which is exactly
 * the kind of number this project refuses to show.
 */
function bestReading(rows) {
  if (rows.length === 1) return rows[0];
  var has = function (v) { return v !== null && v !== undefined; };
  var best = null, bestScore = -Infinity;
  for (var i = 0; i < rows.length; i++) {
    var r = rows[i];
    var score = 0;
    for (var j = 0; j < rows.length; j++) {
      if (i === j) continue;
      var o = rows[j];
      if (o.pay === r.pay) score += 3;          // the field the card leads with
      if (o.minutes === r.minutes) score += 2;
      // Two readings that both lost the distance are not agreeing about it.
      // `null === null` said they were, so a pair of readings that missed the
      // miles out-voted the one reading that saw them.
      if (has(o.miles) && o.miles === r.miles) score += 2;
    }
    // A reading that cannot be true never wins, however many times the same
    // misreading happened to repeat.
    if (r.suspect) score -= 1000;
    // Nor does half a card: a fragment is the same pay over less time, which
    // always reads better than the offer was.
    if (r.whole === false) score -= 100;
    // Nor does a reading with no distance, when another reading of the same
    // card has one. rate() charges no mileage cost for a distance it does not
    // have, so such a row's $/hr is gross wearing net's clothes — $26.68
    // against a true $20.51 on one real card — and unlike an uncertain
    // distance it carries no flag to say so. Small enough that `whole` and
    // `suspect` still outrank it; big enough to beat the later-row tie-break,
    // which is what actually decided this before.
    if (!has(r.miles) && rows.some(function (o) { return has(o.miles); })) {
      score -= 3;
    }
    // Ties go to the later row, which is the old behaviour and the right one
    // when there is nothing to choose between them.
    //
    // The starting score is -Infinity and not -1 for the reason the penalties
    // above are large: two suspect readings of one card both score about -993,
    // nothing cleared -1, and this returned null. That null went into the offer
    // list, the annotation pass dereferenced it, and /api/journal answered 500
    // — the whole offers page blank because one card was misread twice. Pay-
    // based matching made it likelier, by filing a repeated misreading under
    // one id instead of two.
    if (score >= bestScore) { bestScore = score; best = r; }
  }
  return best;
}

function latestPerOffer(rows) {
  var byId = Object.create(null);
  var out = [];
  var marks = Object.create(null);
  var rules = [];
  var readings = Object.create(null);

  rows.forEach(function (r) {
    if (!r || typeof r !== 'object') return;
    if (r.kind === 'mark') {
      if (r.id) marks[r.id] = Object.assign(marks[r.id] || {}, r);
      return;
    }
    if (r.kind === 'rule') { rules.push(r); return; }
    if (r.kind) return;                       // something newer than this reader
    if (!r.id) { out.push(r); return; }
    if (!(r.id in byId)) { byId[r.id] = out.length; out.push(r); readings[r.id] = [r]; return; }
    readings[r.id].push(r);
    out[byId[r.id]] = bestReading(readings[r.id]);
  });

  out.forEach(function (o) {
    // A rule hides every reading of one card. The test offer a driver keeps
    // presenting to check the rig still works would otherwise need hiding again
    // after every check.
    rules.forEach(function (rule) {
      var m = rule.match || {};
      if (m.pay === o.pay && m.minutes === o.minutes && m.miles === o.miles
          && rule.hidden !== undefined) {
        o.hidden = rule.hidden;
      }
    });
    var mark = o.id && marks[o.id];
    if (mark) {
      if (mark.accepted !== undefined) o.accepted = mark.accepted;
      if (mark.hidden !== undefined) o.hidden = mark.hidden;   // an id beats a rule
    }
  });

  return out.sort(function (a, b) { return (a.at || 0) - (b.at || 0); });
}

// Make sure the directory a file is about to be written into exists.
//
// Cheap enough to do on every write: mkdir with recursive succeeds silently
// when the directory is already there, which it is after the first one.
function withDirectory(file, done) {
  fs.mkdir(path.dirname(file), { recursive: true }, function (err) {
    done(err && err.code !== 'EEXIST' ? err : null);
  });
}

/* Append lines, starting a fresh one if the last never finished.
 *
 * A power cut mid-write leaves a partial line with no newline on it — one lost
 * row, which readJournal skips and which this file is built to tolerate.
 * Appending straight onto that stub fuses it to the next row and loses that one
 * too, silently and for good. One torn row is the cost of a power cut; two is a
 * missing byte. The same guard is in rpi/journal.py, for the writer at the
 * other end of the sync. */
function appendLines(text, done) {
  fs.stat(JOURNAL_PATH, function (statErr, st) {
    if (statErr || !st.size) return fs.appendFile(JOURNAL_PATH, text, done);
    fs.open(JOURNAL_PATH, 'r', function (openErr, fd) {
      if (openErr) return fs.appendFile(JOURNAL_PATH, text, done);
      var last = Buffer.alloc(1);
      fs.read(fd, last, 0, 1, st.size - 1, function (readErr) {
        fs.close(fd, function () {
          var torn = !readErr && last[0] !== 0x0a;
          fs.appendFile(JOURNAL_PATH, torn ? '\n' + text : text, done);
        });
      });
    });
  });
}

function readJournal(done) {
  fs.readFile(JOURNAL_PATH, 'utf8', function (err, text) {
    if (err) return done([]);           // nothing recorded yet is not an error
    var rows = [];
    text.split('\n').forEach(function (line) {
      line = line.trim();
      if (!line) return;
      try {
        var row = JSON.parse(line);
        if (row && typeof row === 'object') rows.push(row);
      } catch (e) { /* a line torn by a power cut; skip it */ }
    });
    done(rows);
  });
}

function toCsv(offers) {
  var lines = [CSV_COLUMNS.concat(['when']).join(',')];
  offers.forEach(function (r) {
    var cells = CSV_COLUMNS.map(function (k) {
      var v = r[k];
      if (v === null || v === undefined) return '';
      if (typeof v === 'boolean') return v ? '1' : '0';
      if (typeof v === 'number') return String(v);
      // A list — the places an offer went — as one cell. Semicolons, because
      // the separator here is a comma and an address is full of them.
      if (Array.isArray(v)) v = v.join('; ');
      return '"' + String(v).replace(/"/g, '""') + '"';
    });
    // A second, human-readable stamp. A spreadsheet will not turn epoch
    // milliseconds into a date on its own, and the whole point of exporting is
    // to ask when things happened.
    // Defensively, because `new Date(x).toISOString()` throws rather than
    // returning anything for a value it cannot represent — and `r.at || 0` only
    // catches the falsy ones. A row stamped 1e20 sailed through that guard and
    // through the day filter and then took the whole server down from inside an
    // fs callback, where no request-level try/catch can reach it.
    var when = new Date(r.at || 0);
    cells.push('"' + (isFinite(when.getTime()) ? when.toISOString() : '') + '"');
    lines.push(cells.join(','));
  });
  return lines.join('\n') + '\n';
}

function send(res, status, body, headers) {
  res.writeHead(status, Object.assign({ 'Cache-Control': 'no-cache' }, headers || {}));
  res.end(body);
}

// Anything thrown while routing becomes a 500 for that one request instead of
// the end of the process. This server is the scanner's parent — when it dies
// the child's next stdout write gets EPIPE and the camera side goes down with
// it, so a single malformed URL took out the whole rig and nothing restarted
// it: install-service.sh supervises scan_pi.py, and the documented way to run
// the site is a bare `npm start`. rpi/README.md promises the site keeps serving
// while the scanner comes and goes; that promise cannot survive the web server
// being the fragile half.
function handler(req, res) {
  try {
    route(req, res);
  } catch (e) {
    console.error('request failed: ' + req.method + ' ' + req.url + ' — ' + e.message);
    try {
      send(res, 500, 'server error', { 'Content-Type': 'text/plain' });
    } catch (ignored) {
      // Headers already went out. Nothing to say; just do not take the process
      // down over it.
    }
  }
}

function route(req, res) {
  // Noting what happened to an offer: which ones were taken, and which to hide.
  //
  // It appends a line and can do nothing else. There is no field here for free
  // text and no way to reach an existing row, because this server has no
  // authentication and sits on whatever wifi the car is near — so the worst a
  // stranger can do with it is add a note to a journal they cannot read the
  // addresses out of, and nothing they add can destroy a reading.
  //
  // Hiding is a note too, for the same reason. A mis-tap on a phone in a moving
  // car should cost an entry in a list, not a row of data that took a shift to
  // collect.
  if (req.method === 'POST' && req.url.split('?')[0] === '/api/offers/mark') {
    return readJsonBody(req, function (err, body) {
      if (err || !body) return send(res, 400, JSON.stringify({ ok: false, error: 'bad body' }),
                                    { 'Content-Type': 'application/json; charset=utf-8' });
      var note = { v: 1, at: Date.now() };
      if (typeof body.id === 'string' && body.id.length && body.id.length < 80) {
        note.kind = 'mark';
        note.id = body.id;
      } else if (body.match && typeof body.match === 'object') {
        note.kind = 'rule';
        note.match = {
          pay: numOrNull(body.match.pay),
          minutes: numOrNull(body.match.minutes),
          miles: numOrNull(body.match.miles)
        };
        if (note.match.pay === null || note.match.minutes === null) {
          return send(res, 400, JSON.stringify({ ok: false, error: 'a rule needs a pay and a time' }),
                      { 'Content-Type': 'application/json; charset=utf-8' });
        }
      } else {
        return send(res, 400, JSON.stringify({ ok: false, error: 'no offer named' }),
                    { 'Content-Type': 'application/json; charset=utf-8' });
      }
      if (typeof body.accepted === 'boolean') note.accepted = body.accepted;
      if (typeof body.hidden === 'boolean') note.hidden = body.hidden;
      if (note.accepted === undefined && note.hidden === undefined) {
        return send(res, 400, JSON.stringify({ ok: false, error: 'nothing to note' }),
                    { 'Content-Type': 'application/json; charset=utf-8' });
      }
      appendLines(JSON.stringify(note) + '\n', function (writeErr) {
        if (writeErr) return send(res, 500, JSON.stringify({ ok: false, error: writeErr.message }),
                                  { 'Content-Type': 'application/json; charset=utf-8' });
        send(res, 200, JSON.stringify({ ok: true, note: note }),
             { 'Content-Type': 'application/json; charset=utf-8' });
      });
    });
  }

  // The one thing on this server that is not a read. It asks the scanner to
  // forget where it thinks the phone is; POST because it changes something, and
  // because a GET would be followed by anything that prefetches links.
  if (req.method === 'POST' && req.url.split('?')[0] === '/api/recalibrate') {
    return fs.writeFile(RESET_PATH, '', function (err) {
      if (err) return send(res, 500, JSON.stringify({ ok: false, error: err.message }),
                           { 'Content-Type': 'application/json; charset=utf-8' });
      send(res, 200, JSON.stringify({ ok: true }),
           { 'Content-Type': 'application/json; charset=utf-8' });
    });
  }

  // Rows arriving from a scanner that is not this machine.
  //
  // The rig lives in a car behind cellular NAT, so nothing here can reach it —
  // it has to push, and it pushes to whatever host is running this file with
  // SCANNER=0 and JOURNAL pointed at the copy. That copy is the reason this
  // exists: the journal is the one irreplaceable thing the rig produces, about
  // 19MB a year, and until now there was exactly one of it, on an SD card, in a
  // car.
  //
  // Idempotent on purpose, and that is the whole design. Every row can say what
  // makes it itself (see syncKey), so the same batch can arrive twice — or ten
  // times — and only what this file has never seen gets appended. That removes
  // the bookkeeping that normally breaks a sync: there is no stored offset to
  // drift out of step, no resume logic, nothing to repair after a connection
  // drops mid-upload. The sender can be crude and still be correct.
  //
  // Deliberately unauthenticated by default, because the deployment this was
  // written for keeps the whole machine behind a VPN. SYNC_TOKEN turns on a
  // check if that ever stops being true; unset, this costs one comparison.
  if (req.method === 'POST' && req.url.split('?')[0] === '/api/journal/ingest') {
    if (SYNC_TOKEN && req.headers['x-sync-token'] !== SYNC_TOKEN) {
      return send(res, 403, JSON.stringify({ ok: false, error: 'bad token' }),
                  { 'Content-Type': 'application/json; charset=utf-8' });
    }
    return readBody(req, MAX_SYNC_BODY, function (err, text) {
      var fail = function (why, code) {
        send(res, code || 400, JSON.stringify({ ok: false, error: why }),
             { 'Content-Type': 'application/json; charset=utf-8' });
      };
      if (err) return fail(err.message);
      readJournal(function (existing) {
        var seen = {};
        existing.forEach(function (r) {
          var k = syncKey(r);
          if (k) seen[k] = true;
        });
        var fresh = [];
        var malformed = 0;
        text.split('\n').forEach(function (line) {
          line = line.trim();
          if (!line) return;
          var row;
          try { row = JSON.parse(line); } catch (e) { malformed++; return; }
          var key = syncKey(row);
          // Nothing that can be sent twice without being recognised can be
          // stored, because there would be no way to avoid writing it again on
          // the next upload.
          if (!key) { malformed++; return; }
          if (seen[key]) return;
          seen[key] = true;
          fresh.push(JSON.stringify(row));
        });
        if (!fresh.length) {
          return send(res, 200, JSON.stringify({ ok: true, added: 0,
                                                 malformed: malformed,
                                                 have: existing.length }),
                      { 'Content-Type': 'application/json; charset=utf-8' });
        }
        // Appended, like the scanner does it: O_APPEND, one write, so a reader
        // part way through never sees half a row.
        //
        // The directory is made first, because the commonest way this fails is
        // that nobody made it. JOURNAL is usually pointed somewhere outside the
        // checkout — /var/lib/uberscan is the obvious choice — and setting the
        // variable is the memorable half of that; mkdir is the half that gets
        // forgotten, and the rig then gets HTTP 500 with the reason sitting in
        // a log it cannot see.
        withDirectory(JOURNAL_PATH, function (dirErr) {
          if (dirErr) {
            console.error('journal ingest: ' + dirErr.message);
            return fail('could not create ' + path.dirname(JOURNAL_PATH)
                        + ' (' + dirErr.code + ')', 500);
          }
          appendLines(fresh.join('\n') + '\n', function (writeErr) {
          if (writeErr) {
            console.error('journal ingest: ' + writeErr.message);
            // The errno, because 'could not append' is not something anyone can
            // act on and this is the only message that reaches the machine that
            // needs to act. ENOENT is a directory nobody made; EACCES is a
            // process that cannot write where it was pointed.
            return fail('could not append (' + writeErr.code + ')', 500);
          }
          console.log('journal ingest: +' + fresh.length + ' row(s), '
                      + (existing.length + fresh.length) + ' total');
          send(res, 200, JSON.stringify({ ok: true, added: fresh.length,
                                          malformed: malformed,
                                          have: existing.length + fresh.length }),
               { 'Content-Type': 'application/json; charset=utf-8' });
          });
        });
      });
    });
  }

  // The rig's calibration, kept beside the offers.
  //
  // 400 bytes, and it is the corners, the lens, the flicker-safe exposure and
  // the driver's own target and running costs. None of it is irreplaceable the
  // way the journal is — it can all be measured again — but re-aiming a camera
  // and re-deriving an exposure at the roadside is an afternoon nobody wants,
  // and it is small enough that there is no reason not to keep a copy.
  //
  // Stored beside the journal rather than over this machine's own config: the
  // host keeping the copy is not a scanner and must not be turned into one by a
  // backup landing on it.
  if (req.method === 'POST' && req.url.split('?')[0] === '/api/config/backup') {
    if (SYNC_TOKEN && req.headers['x-sync-token'] !== SYNC_TOKEN) {
      return send(res, 403, JSON.stringify({ ok: false, error: 'bad token' }),
                  { 'Content-Type': 'application/json; charset=utf-8' });
    }
    return readBody(req, MAX_BODY * 16, function (err, text) {
      var reply = function (code, body) {
        send(res, code, JSON.stringify(body),
             { 'Content-Type': 'application/json; charset=utf-8' });
      };
      if (err) return reply(400, { ok: false, error: err.message });
      var parsed;
      try { parsed = JSON.parse(text); } catch (e) { parsed = null; }
      // Refused rather than stored if it is not a config: a backup that cannot
      // be restored is worse than none, because it is believed.
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)
          || !parsed.quad) {
        return reply(400, { ok: false, error: 'not a calibration' });
      }
      var dest = path.join(path.dirname(JOURNAL_PATH), 'config-backup.json');
      var body = JSON.stringify(parsed, null, 2) + '\n';
      // Only when it changed. This arrives on every sync tick and a calibration
      // changes a handful of times in a rig's life.
      fs.readFile(dest, 'utf8', function (readErr, before) {
        if (!readErr && before === body) return reply(200, { ok: true, changed: false });
        var tmp = dest + '.part';
        withDirectory(dest, function (dirErr) {
          if (dirErr) {
            console.error('config backup: ' + dirErr.message);
            return reply(500, { ok: false,
                                error: 'could not create ' + path.dirname(dest)
                                       + ' (' + dirErr.code + ')' });
          }
          fs.writeFile(tmp, body, function (writeErr) {
          if (writeErr) {
            fs.unlink(tmp, function () {});
            console.error('config backup: ' + writeErr.message);
            return reply(500, { ok: false,
                                error: 'could not save (' + writeErr.code + ')' });
          }
          fs.rename(tmp, dest, function (renameErr) {
            if (renameErr) {
              fs.unlink(tmp, function () {});
              console.error('config backup: ' + renameErr.message);
              return reply(500, { ok: false, error: 'could not save' });
            }
            console.log('config backup: updated ' + dest);
            reply(200, { ok: true, changed: true });
          });
          });
        });
      });
    });
  }

  // What the far end already has, so a sender knows where to start. Cheap
  // enough to call every few minutes and the only thing the rig needs to ask.
  if (req.method === 'GET' && req.url.split('?')[0] === '/api/journal/newest') {
    return readJournal(function (rows) {
      // The newest *offer*, not the newest row.
      //
      // The sender resumes from an hour before this, so whatever it means has
      // to be "how far through the offers I am". Every row counted equally,
      // and the driver's own tags are rows: ticking "I took this" on the copy
      // machine stamped a row with the current time, the rig then resumed from
      // an hour before *that*, and every offer older than an hour that had not
      // yet been sent was skipped — permanently, because nothing ever looks
      // further back. Tagging one offer here could quietly cost a day of them.
      var newest = 0, offers = 0;
      rows.forEach(function (r) {
        if (r.kind) return;                       // a tag, not an offer
        offers++;
        if ((r.at || 0) > newest) newest = r.at;
      });
      // What this build can do, so the sender can tell "I am misconfigured"
      // from "the far end is old" without a human having to compare error
      // strings. A rig spent two rounds on that: the copy machine had not been
      // updated, the only symptom was an error message missing a detail the new
      // build adds, and nothing said so.
      send(res, 200, JSON.stringify({ ok: true, newest: newest, have: rows.length,
                                      // So the sender can notice it holds more
                                      // than this copy does and repair the gap
                                      // itself, rather than needing somebody to
                                      // think of running --all.
                                      offers: offers,
                                      can: ['ingest', 'config', 'mkdir', 'count'] }),
           { 'Content-Type': 'application/json; charset=utf-8' });
    });
  }

  // The box to read, drawn by hand on the live view.
  //
  // The scanner finds the phone by looking for it, which is right almost always
  // and useless in the cases where it is wrong: a windscreen reflection, a
  // second lit screen, a phone with nothing darker around it to be told apart
  // from. There is no aiming your way out of those — the rig reads a strip of
  // the car forever — and the only fix used to be ssh and eight pixel
  // coordinates guessed off a photograph. So the person looking at the picture
  // can draw the answer instead.
  //
  // Fractions of the frame, never pixels: what they drew on is a 480px JPEG of
  // a 2328px sensor frame, and corners measured against one size and read
  // against another are refused on every check forever, silently.
  if (req.method === 'POST' && req.url.split('?')[0] === '/api/crop') {
    return readJsonBody(req, function (err, body) {
      var bad = function (why) {
        send(res, 400, JSON.stringify({ ok: false, error: why }),
             { 'Content-Type': 'application/json; charset=utf-8' });
      };
      if (err || !body) return bad('bad body');
      var quad = cropQuad(body);
      if (typeof quad === 'string') return bad(quad);
      // Written to a temporary name and renamed, because the scanner may be
      // reading this exact path at this exact moment and half a JSON object
      // parses as nothing at all.
      //
      // A name of its own per request, because one shared `.part` defeats the
      // very thing the rename is for: two drags landing together — a double tap
      // on a laggy link is all it takes — have both writes interleaving into one
      // file, and the rename then publishes whichever mixture won. Unique names
      // make each rename genuinely atomic with respect to the other.
      var tmp = CROP_PATH + '.' + process.pid + '.' + (cropSeq++) + '.part';
      var failed = function (err) {
        fs.unlink(tmp, function () {});     // never leave a .part behind
        send(res, 500, JSON.stringify({ ok: false, error: 'could not save the box' }),
             { 'Content-Type': 'application/json; charset=utf-8' });
        console.error('crop box: ' + err.message);
      };
      fs.writeFile(tmp, JSON.stringify({ quad: quad }), function (writeErr) {
        if (writeErr) return failed(writeErr);
        fs.rename(tmp, CROP_PATH, function (renameErr) {
          if (renameErr) return failed(renameErr);
          send(res, 200, JSON.stringify({ ok: true, quad: quad }),
               { 'Content-Type': 'application/json; charset=utf-8' });
        });
      });
    });
  }

  if (req.method !== 'GET' && req.method !== 'HEAD') {
    return send(res, 405, 'method not allowed', { 'Content-Type': 'text/plain' });
  }

  var pathname;
  try {
    pathname = decodeURIComponent(url.parse(req.url).pathname);
  } catch (e) {
    return send(res, 400, 'bad request', { 'Content-Type': 'text/plain' });
  }

  // A percent-encoded NUL survives decodeURIComponent as a real \0, and every
  // check below it is string work that lets it through: path.resolve keeps it,
  // ROOT-containment still matches, and PRIVATE wants `rpi` followed by `/` or
  // end-of-string, which \0 is neither — so /rpi%00/config.json walked straight
  // past the guard on the private directory. It then reached fs.realpath, which
  // validates its argument synchronously and throws, and `GET /%00` killed the
  // server outright. No file has a NUL in its name, so there is nothing here to
  // serve and nothing to be lost by refusing early.
  if (pathname.indexOf('\0') !== -1) {
    return send(res, 400, 'bad request', { 'Content-Type': 'text/plain' });
  }

  if (pathname === '/api/status') {
    return send(res, 200, JSON.stringify({
      scanner: {
        enabled: scannerEnabled(),
        calibrated: calibrated(),
        phase: scanner.phase,
        running: !!scanner.proc,
        restarts: scanner.restarts,
        startedAt: scanner.started,
        error: scanner.error
      },
      last: scanner.last,
      status: scanner.status
    }), { 'Content-Type': 'application/json; charset=utf-8' });
  }

  // The scanner writes this every couple of seconds while it runs. Serving it
  // from here means the live view needs no second server and no camera of its
  // own — the one process holding the camera is the one producing the picture.
  /* The live view as a stream rather than a thousand little requests.
   *
   * The polling loop this replaces asks for a whole new frame over HTTP, waits
   * for it, then waits a floor of 60ms and asks again — about 17 a second at
   * best, and every one of those is a request, a file read, a response and an
   * image decode whether or not the picture has changed since the last one.
   * The driver watches this screen to decide whether to press Accept, so the
   * lag between the phone changing and the panel showing it is the whole
   * quality of the thing.
   *
   * Here the server holds the connection open and writes a part whenever the
   * frame on disk is actually new. No request per frame, no cache-busting
   * query, no floor — the rate becomes whatever the scanner is writing, which
   * is the honest ceiling. Unchanged frames cost one stat() and nothing else.
   */
  if (pathname === '/api/frame.mjpeg') {
    if (mjpegClients >= MAX_MJPEG) {
      return send(res, 503, 'too many viewers', { 'Content-Type': 'text/plain' });
    }
    mjpegClients++;
    touchWatchFile();
    res.writeHead(200, {
      'Content-Type': 'multipart/x-mixed-replace; boundary=' + MJPEG_BOUNDARY,
      'Cache-Control': 'no-store, no-cache, must-revalidate',
      'Pragma': 'no-cache',
      'Connection': 'close'
    });
    // Send the head now rather than letting it wait behind the first frame.
    // Before the scanner has written anything there is no first frame, so the
    // viewer sat looking at a connection it could not distinguish from a
    // stalled one — and the page's fallback waits on exactly that signal.
    if (res.flushHeaders) res.flushHeaders();

    var lastSent = -1;
    var closed = false;
    var timer = null;

    var stop = function () {
      if (closed) return;
      closed = true;
      mjpegClients--;
      clearTimeout(timer);
      try { res.end(); } catch (e) { /* already gone */ }
    };
    res.on('close', stop);
    res.on('error', stop);

    var tick = function () {
      if (closed) return;
      var file = framePath();
      fs.stat(file, function (statErr, st) {
        if (closed) return;
        if (statErr || st.mtimeMs === lastSent) {
          timer = setTimeout(tick, MJPEG_POLL);
          return;
        }
        fs.readFile(file, function (readErr, data) {
          if (closed) return;
          if (readErr || !data.length) {
            timer = setTimeout(tick, MJPEG_POLL);
            return;
          }
          lastSent = st.mtimeMs;
          // Someone is watching, so the scanner should keep composing at its
          // fast rate. Cheap and throttled inside touchWatchFile.
          touchWatchFile();
          var head = '--' + MJPEG_BOUNDARY + '\r\n'
                   + 'Content-Type: image/jpeg\r\n'
                   + 'Content-Length: ' + data.length + '\r\n\r\n';
          // Respect back-pressure: if the socket is full, wait for it to drain
          // rather than queueing frames the viewer will never catch up with.
          var more = res.write(head + '');
          res.write(data);
          more = res.write('\r\n') && more;
          if (more) timer = setTimeout(tick, MJPEG_POLL);
          else res.once('drain', function () { if (!closed) tick(); });
        });
      });
    };
    return tick();
  }

  if (pathname === '/api/frame.jpg') {
    // Tell the scanner someone is looking, so it refreshes the view quickly
    // instead of on its idle tick. Throttled: this fires twice a second.
    touchWatchFile();
    return fs.readFile(framePath(), function (err, data) {
      if (err) {
        return send(res, 404, 'no frame yet', { 'Content-Type': 'text/plain' });
      }
      send(res, 200, data, {
        'Content-Type': 'image/jpeg',
        'Content-Length': data.length,
        'Cache-Control': 'no-store'
      });
    });
  }

  if (pathname === '/api/events') {
    res.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive'
    });
    res.write('retry: 2000\n\n');
    if (scanner.last) res.write('data: ' + JSON.stringify(scanner.last) + '\n\n');
    listeners.push(res);
    req.on('close', function () {
      listeners = listeners.filter(function (r) { return r !== res; });
    });
    return;
  }

  // Everything the scanner has kept. The file itself is inside rpi/, which the
  // static handler refuses to serve, and it stays that way — this returns the
  // rows and nothing else, so the path is never taken from the request.
  if (pathname === '/api/journal' || pathname === '/api/journal.csv') {
    var q = url.parse(req.url, true).query || {};
    var days = clampNumber(q.days, 0, 3650, 30);
    var limit = clampNumber(q.limit, 0, 20000, 5000);
    // The page can name an exact start instead of a span. It has to, for
    // "today": a trailing 24 hours folds last night's shift into this morning's
    // figures, and only the browser knows where the driver is and therefore
    // when their day began.
    var since = clampNumber(q.since, 0, 4102444800000, 0);
    var withHidden = q.hidden === '1';
    return readJournal(function (rows) {
      var offers = latestPerOffer(rows);
      // The window first, then the count of what is hidden inside it.
      //
      // Counting before the filter meant the page said "3 offers are hidden and
      // left out of everything here" while looking at today, where "here" is
      // the window and the 3 were every hidden offer the journal has ever held.
      // A number that does not describe what is on screen is worse than no
      // number, because it is the one a driver checks their arithmetic against.
      var floor = since || (days > 0 ? Date.now() - days * 86400000 : 0);
      if (floor) {
        offers = offers.filter(function (r) { return (r.at || 0) >= floor; });
      }
      var hidden = offers.filter(function (r) { return r.hidden; }).length;
      // Hidden rows are still on disk — nothing here deletes — but they are out
      // of every figure and every export unless asked for by name. The test card
      // a driver presents to check the rig is not an offer they were made, and
      // leaving it in quietly drags the median toward whatever that card says.
      if (!withHidden) {
        offers = offers.filter(function (r) { return !r.hidden; });
      }
      // How many there really are in this window, kept before the cap. Without
      // it the page cannot tell a window of 5000 offers from a window of
      // 60000 truncated to 5000 — and it was labelling the second one "All",
      // computing the median and the $/hr ladder over an unannounced subset.
      var total = offers.length;
      if (limit && offers.length > limit) offers = offers.slice(-limit);
      if (pathname === '/api/journal.csv') {
        return send(res, 200, toCsv(offers), {
          'Content-Type': 'text/csv; charset=utf-8',
          'Content-Disposition': 'attachment; filename="uber-scan-offers.csv"'
        });
      }
      send(res, 200, JSON.stringify({ count: offers.length, total: total,
                                      truncated: total > offers.length,
                                      days: days, hidden: hidden,
                                      offers: offers }),
           { 'Content-Type': 'application/json; charset=utf-8' });
    });
  }

  if (pathname.endsWith('/')) pathname += 'index.html';

  // Resolve first, then confirm the result is still inside ROOT, so "..", an
  // encoded traversal and an absolute path all fail the same way.
  var file = path.resolve(ROOT, '.' + pathname);
  if ((file !== ROOT && !file.startsWith(ROOT + path.sep)) || isPrivate(pathname)) {
    return send(res, 403, 'forbidden', { 'Content-Type': 'text/plain' });
  }

  // ...and again after following links. Resolving the *path* proves nothing
  // about where a symlink inside ROOT actually points, and a lexical check
  // alone would happily serve whatever it aims at.
  fs.realpath(file, function (linkErr, real) {
    if (linkErr) return send(res, 404, 'not found', { 'Content-Type': 'text/plain' });
    if (real !== ROOT && !real.startsWith(ROOT + path.sep)) {
      return send(res, 403, 'forbidden', { 'Content-Type': 'text/plain' });
    }
    serveFile(req, res, real);
  });
}

function serveFile(req, res, file) {
  fs.stat(file, function (err, stat) {
    if (err || !stat.isFile()) {
      return send(res, 404, 'not found', { 'Content-Type': 'text/plain' });
    }
    var headers = {
      'Content-Type': TYPES[path.extname(file).toLowerCase()] || 'application/octet-stream',
      'Content-Length': stat.size,
      'Cache-Control': 'no-cache'
    };
    if (req.method === 'HEAD') return send(res, 200, '', headers);

    res.writeHead(200, headers);
    var stream = fs.createReadStream(file);
    stream.on('error', function () { res.destroy(); });
    // The client going away has to close the file, and pipe() will not do it.
    // `Readable.pipe` unpipes when the destination errors but never destroys
    // the source, and an fs.ReadStream only tidies itself up on its own 'end'
    // or 'error' — so a half-read file paused by a vanished socket keeps its
    // descriptor for the life of the process. Measured: 25 aborted downloads,
    // 25 descriptors, never returned.
    //
    // That is the ordinary case here, not an edge one. This is served over a
    // car's wifi to a phone: /scan.html pulls a 3.9MB wasm reader and a 2.9MB
    // language model on a cold load, and the screen locking or the driver
    // walking out of range part way through is a Tuesday. The failure at the
    // far end is worse than a crash because nothing announces it — /api/status
    // keeps answering `running: true`, so the page keeps its green dot while
    // every new request fails to open anything.
    res.on('close', function () { stream.destroy(); });
    stream.pipe(res);
  });
}

// Browsers gate the camera, home-screen install and service workers behind a
// secure context, so over plain http on a LAN address the scanner cannot open a
// camera at all.
//
// Certificates are found on disk rather than configured, because the usual way
// this runs is a process manager invoking `npm start` — there is no shell in
// which to set an environment variable. Drop a pair in ./ssl (npm run cert) and
// https starts appearing on the next restart, alongside http rather than
// instead of it, so nothing that already points at the http port breaks.
function findCert() {
  var cert = process.env.SSL_CERT || path.join(SSL_DIR, 'cert.pem');
  var key = process.env.SSL_KEY || path.join(SSL_DIR, 'key.pem');
  try {
    return { cert: fs.readFileSync(cert), key: fs.readFileSync(key), certPath: cert };
  } catch (e) {
    return null;
  }
}

function lanAddresses() {
  var out = [];
  var ifaces = os.networkInterfaces();
  Object.keys(ifaces).forEach(function (name) {
    (ifaces[name] || []).forEach(function (nic) {
      if (nic.family === 'IPv4' && !nic.internal) out.push(nic.address);
    });
  });
  return out;
}

// A listener that cannot bind must not take the other one down with it. The
// https port failing is an inconvenience; the process dying under a supervisor
// that restarts it is a loop.
function listen(server, port, label, fatal, onReady) {
  server.on('error', function (err) {
    var why = err.code === 'EADDRINUSE' ? 'port ' + port + ' is already in use' : err.message;
    console.error('\ncould not start ' + label + ': ' + why);
    if (fatal) process.exit(1);
    console.error(label + ' is off; the rest of the server is still running.');
  });
  server.listen(port, HOST, onReady);
}

var tls = findCert();

listen(http.createServer(handler), PORT, 'http', true, function () {
  console.log('Uber Scan serving ' + ROOT);
  console.log('  http://localhost:' + PORT + '/');
  lanAddresses().forEach(function (ip) {
    console.log('  http://' + ip + ':' + PORT + '/   (keypad only — see below)');
  });
});

if (tls) {
  listen(https.createServer({ cert: tls.cert, key: tls.key }, handler),
         HTTPS_PORT, 'https', false, function () {
    console.log('\nhttps using ' + tls.certPath);
    lanAddresses().forEach(function (ip) {
      console.log('  https://' + ip + ':' + HTTPS_PORT + '/   <- open this on the phone');
    });
    console.log('A self-signed certificate warns once; accepting it makes the');
    console.log('origin secure, which is what the camera and install need.');
  });
} else {
  console.log('\nNo certificate in ./ssl, so http only. The browser camera page and');
  console.log('home-screen install need a secure context: they work on localhost,');
  console.log('but not over a LAN address. Run `npm run cert` and restart to fix.');
  console.log('(The Pi scanner below does not care — it never touches a browser.)');
}

if (scannerEnabled()) {
  console.log('\nPi scanner running here too' +
    (calibrated() ? '.' : ' — not calibrated yet, so it starts by aiming.'));
  if (!calibrated()) {
    // Deliberately not "localhost": the phone you are holding while you move
    // the mount is not this machine, and localhost there is the phone.
    console.log('  aim the camera: open /live.html — the camera view is live while aiming');
    console.log('  (or http://<this-pi>:8081/ for a full-size stream)');
  }
  console.log('  live verdict: /live.html      state: /api/status');
  startScanner();
} else if (process.env.SCANNER === '0') {
  console.log('\nPi scanner disabled (SCANNER=0).');
}
