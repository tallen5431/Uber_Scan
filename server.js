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

// The one rule about which offers count towards a figure derived from more than
// one of them. Required rather than restated: advice.js:116 records that this
// test existed in two places once and the copies drifted, and journal.html:480
// records what that cost — a duplicate that never excluded hidden rows, masked
// for as long as nobody asked the server for them.
//
// advice.js is a UMD whose first branch is CommonJS, it touches no browser
// global at load time, and tests/advice.test.js has required it from Node since
// it was written. A relative require resolves against this file's directory,
// not the cwd, so it survives however the server is started.
var Advice = require('./advice.js');

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

/* ...and the other way round: only the kinds of file a website is made of.
 *
 * The rule above is a denylist, and a denylist has to be remembered every time
 * something new appears next to server.js. It was not. `rpi/` and `ssl/` are
 * refused by name, so the journal in `rpi/` is safe — and a copy of that same
 * journal anywhere else is not. Verified against the running server: a manual
 * `journal-backup.jsonl` in the root, a `backup/journal.jsonl`, and a
 * `logs/uberscan.log` were all served in full to anyone on the car's wifi,
 * pickup addresses included. Those are the exact files a person makes when they
 * are being careful with their data.
 *
 * So the question is turned around. Every file this site actually ships —
 * checked against sw.js's own precache list and everything under icons/ and
 * vendor/ — already has a type in TYPES, because TYPES is the list of what a
 * page is built from. Anything else is not part of the site and is not served,
 * whatever it is called and wherever it is put. A new directory of data
 * appearing next to the server is then safe by default rather than safe if
 * somebody remembers.
 */
function isServable(pathname) {
  return Object.prototype.hasOwnProperty.call(
    TYPES, path.extname(pathname).toLowerCase());
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
  // A lifetime tally, deliberately not cleared when the replacement starts: it
  // is the only trace a wedge leaves. A camera that goes quiet twice a shift is
  // a hardware conversation, and zeroing the count at every restart would mean
  // /api/status always said none.
  wedged: 0,
  wedgedAt: null,      // when the last one happened, for the same reason
  error: null,
  // Set up HERE and never again, which is the difference that matters: these
  // two are facts about the DRIVER'S CAR, not about the scanner process, so
  // startScanner() deliberately leaves them alone. See the note there.
  offer: null,         // the last offer read, so it can still be marked taken
  offerAt: null,
  holding: null        // the order being carried, if any. See holding().
};

var listeners = [];    // open server-sent-event responses

// How long a scanner has to stay up before its next exit counts as a fresh
// problem rather than another rung of the same one. Comfortably longer than the
// camera takes to open and fail, comfortably shorter than a shift.
var HEALTHY_RUN_MS = 60000;

// How long a *running* scanner may say nothing before it is treated as wedged.
//
// Everything below restarts a scanner that exits. Nothing restarted one that
// stayed alive and stopped working — and that is a real state: a CSI camera
// that stops delivering frames leaves capture_request() blocked forever, so the
// process is up, systemd is content, the loop never turns and the driver has a
// rig that looks fine and reads nothing for the rest of the shift.
//
// It became detectable when the scan loop started saying "still here" every
// four seconds whether or not it has read anything. Thirty seconds is seven of
// those beats, which is slack enough for a Pi under load and short enough that
// a wedge costs one offer rather than an evening.
//
// Armed only once that beat has been heard, so it can never fire during aiming
// or calibration: those phases are the autopilot's, they emit on their own
// schedule, and they already give up on a timeout of their own.
var SILENT_MS = Number(process.env.SCANNER_SILENT_MS) || 30000;
// Checked often enough that the deadline means roughly what it says — a fixed
// five-second tick would turn a short SILENT_MS into a much longer one, which
// matters for the test that wedges a scanner on purpose and for anyone who
// tightens the window on a rig that beats faster.
var SILENT_TICK_MS = Math.max(200, Math.min(5000, Math.round(SILENT_MS / 4)));
var silentTimer = null;

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
  scanner.heardAt = null;          // nothing from the scan loop yet
  // What is NOT cleared here, and why.
  //
  // `started`, `error` and `heardAt` are facts about the PROCESS, and a new
  // process makes them false. The order in the car is not one of those. It is
  // a fact about the driver's car, established by their own press of "Took",
  // and a camera that crashed says nothing about whether there is food on the
  // back seat.
  //
  // Clearing it meant a wedge mid-delivery — the watchdog kills a scanner
  // blocked in the camera driver roughly every minute it stays blocked — threw
  // the order away: the stack line went silent for the rest of that delivery,
  // and Drop and the destination scan vanished off the panel with a job still
  // in the car. That is the one time the pairing advice is worth anything.
  //
  // Both of these already end on their own terms: holding() expires an order on
  // the card's stated time, and the offer on record is served with an age the
  // panel judges for itself. Neither needs a process restart to end it, and a
  // restart is the wrong reason. They are set up once, where the object is
  // built, and this function does not mention them.
  console.log('scanner: started ' + bin + ' ' + args.join(' '));

  // Without this, a missing python3 or a bad SCANNER_CMD emits an 'error' with
  // nothing listening, which in Node is an uncaught exception — so the failure
  // to start the scanner takes down the web server that was reporting on it.
  // The site is meant to keep working when the camera side does not.
  scanner.proc.on('error', function (err) {
    scanner.error = 'could not start ' + bin + ': ' + err.message;
    console.error('scanner: ' + scanner.error);
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

  // ...and the pipes are not guaranteed to exist. When the process runs out of
  // file descriptors there are none left to build them from, so spawn returns a
  // child whose `stdout` and `stderr` are undefined, and reading `.on` off that
  // throws a TypeError right here — synchronously, inside the caller, taking
  // down the web server that was about to report the problem.
  //
  // That is not a hypothetical pairing. Until the fix a few hundred lines below
  // this, every download a phone abandoned leaked a descriptor, so a rig that
  // had been up long enough arrived at exactly this state and then died on its
  // next scanner restart. The 'close' handler ABOVE already knows what to do
  // about EMFILE — it names it — and it only ever needed the chance to run.
  //
  // Above, and that word is the whole point. It used to be below, and this
  // early return came first — so the one path that says "retrying" attached no
  // retry. `scanner.proc` stayed set, /api/status kept answering running:true,
  // the panel kept its green dot, and the rig read nothing for the rest of the
  // shift with the log line "Retrying." on screen and nothing retrying. This
  // comment described a fix the code returned past.
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
        // Which offer is on the record, so the driving screen can offer to mark
        // it as taken. Held here as well as pushed, because a tab opened after
        // the card has gone — which is the normal case, the driver accepts on
        // the phone and the card disappears — would otherwise have nothing to
        // mark. Cleared by nothing: the last offer stays markable until the
        // next one replaces it.
        if (read.offer && typeof read.offer.id === 'string') {
          scanner.offer = read.offer;
          scanner.offerAt = Date.now();
          // ...and if there is an order in the car, WRITE THE PAIRING DOWN.
          //
          // Without this a shift produces no evidence about the one feature it
          // was driven to test. The offer rows record what each card said and
          // whether the driver marked it taken; the advice that was on the
          // panel when they decided — the range, the state, whether the two
          // jobs were called near or elsewhere — was computed in this process's
          // memory, shown once, and lost. Afterwards there is no way to ask the
          // only question that matters: when it said take both, was it right?
          //
          // Once per offer, here, because this is the moment an offer goes on
          // the record and it happens exactly once. Doing it in withStack()
          // would write five rows a second for as long as the card is on the
          // phone.
          //
          // Its own row with a `kind`, like a mark or a rule, so every reader
          // that walks this file already knows to skip it — including the
          // scanner's own resume(), which must never mistake an annotation for
          // the last offer.
          recordPairing(scanner.offer, Date.now());
        }
        // The destination, read off the screen that comes AFTER the accept.
        //
        // It goes onto the order in the car and nowhere else. An offer card
        // does not name where a delivery ends - 106 of this driver's 604 cards
        // print "Customer dropoff" and no address - so `holding.dropoff` was
        // null on 18% of accepted jobs, which is what makes the stacking advice
        // silent on 39% of the pairs it is asked about.
        //
        // Only when there IS an order in the car. Read with nothing held, this
        // is an address belonging to no job, and storing it would measure the
        // next offer against wherever the driver happened to be pointing the
        // camera. It is also why nothing here touches `scanner.offer`: the
        // offer is a card that was read, and this is not one.
        //
        // Asked through holding(), never off `scanner.holding` directly. That
        // field is the raw slot; holding() is the question "is an order being
        // carried RIGHT NOW", and it is not the same question - an order whose
        // stated time has run out, plus half again, plus ten minutes, is
        // already forgotten by the panel and by the stack line. Reading the
        // slot here would attach the address to a job everything else has
        // given up on.
        if (read.dropoff && typeof read.dropoff.line === 'string') {
          var carrying = holding(Date.now());
          if (carrying) {
            carrying.dropoff = read.dropoff.line;
            carrying.dropoffScanned = true;
          }
          // Kept either way, so the page can say what was read even when there
          // was nothing to attach it to - a driver who presses the button with
          // no order held needs to see that, not silence.
          scanner.dropoff = read.dropoff;
          scanner.dropoffAt = Date.now();
        }
        // The scan loop's own voice — a reading or a heartbeat — as opposed to
        // the autopilot's progress messages. Only this arms the watchdog, and
        // only this feeds it.
        // `reading` counts too: it is sent from inside the loop the moment a
        // read is handed over, so it proves the loop is turning exactly as a
        // heartbeat does — and on a busy screen it is the message that arrives.
        if (read.ready !== undefined || read.alive || read.reading) {
          scanner.heardAt = Date.now();
        }
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

}

/* Kill a scanner that is running and has stopped saying anything.
 *
 * A kill rather than anything cleverer: there is nothing to negotiate with a
 * process blocked inside a camera driver, and everything needed to bring it
 * back already exists — the 'close' handler above restarts it with the same
 * backoff it uses for a crash, so a camera that is genuinely gone produces a
 * retry every minute rather than a spin.
 *
 * SIGKILL, not SIGTERM. The scan loop handles SIGTERM by unwinding cleanly,
 * which is right when it is able to run; a wedged one cannot, and a signal it
 * never processes would leave this timer firing forever against a process that
 * has already been asked nicely. This is the case where the polite path has
 * been ruled out by the diagnosis.
 */
function watchForSilence() {
  if (shuttingDown || !scanner.proc) return;
  // Never armed before the scan loop has spoken once: aiming and calibration
  // are the autopilot's phases, they keep their own schedule, and they have
  // their own give-up timeout.
  if (!scanner.heardAt) return;
  var quiet = Date.now() - scanner.heardAt;
  if (quiet <= SILENT_MS) return;
  scanner.wedged = (scanner.wedged || 0) + 1;
  scanner.wedgedAt = Date.now();
  scanner.error = 'the scanner stopped reporting for ' + Math.round(quiet / 1000)
                + 's while still running — restarting it';
  console.error('scanner: ' + scanner.error);
  // Cleared first, so a kill that takes a moment to land cannot make this fire
  // again on the next tick against the same process.
  scanner.heardAt = null;
  try {
    scanner.proc.kill('SIGKILL');
  } catch (e) {
    console.error('scanner: could not kill the wedged process: ' + e.message);
  }
}

/* The three files this side leaves requests in for the camera side: somebody
 * is watching and which view they want, re-find the phone, read this box.
 * Files, because the scanner is sometimes a child of this process and
 * sometimes a systemd unit that has never heard of it.
 *
 * In RAM where there is any. All three exist for seconds, none should survive
 * a reboot, and `.viewing` is now rewritten about once a second for as long as
 * a browser is fetching frames — which is a second's worth of card wear for
 * something that is stale a second later. The live frame moved to /dev/shm for
 * exactly this reason and these were left behind.
 *
 * This is `_dir()` in rpi/handoff.py, written again rather than shared,
 * because one side is JavaScript and the other is Python. It has to be a rule
 * both sides evaluate to the same answer rather than a list of candidates:
 * FRAME_CANDIDATES below can take whichever file is freshest and be right
 * either way, because a frame is written by one side and read by the other. A
 * request written where the reader is not looking is not a stale picture, it
 * is a button that does nothing. They agree because they run as the same user
 * — the systemd unit's User= is the account that installed it, and otherwise
 * the scanner is this process's own child. rpi/test_handoff.py holds the two
 * implementations to the same answer.
 *
 * The readers look in the old place too, so a scanner that has not been
 * restarted since the last `git pull` still hears these.
 */
function handoffDir() {
  // One machine, more than one rig. The three filenames are fixed and the
  // directory is shared with everything else on the box, so two copies of this
  // project running at once — a second rig, a development checkout beside the
  // live one, a test suite while the scanner is up — write to and consume each
  // other's requests. A crop drawn on one screen moves the other one's camera.
  // Set UBERSCAN_HANDOFF_DIR and both sides use it. Honoured only when it names
  // a directory this process can write to, so a stale value in a profile cannot
  // quietly disconnect the two halves of the rig. Mirrors _dir() in handoff.py.
  var asked = process.env.UBERSCAN_HANDOFF_DIR;
  if (asked) {
    try {
      fs.accessSync(asked, fs.constants.W_OK);
      if (fs.statSync(asked).isDirectory()) return asked;
    } catch (e) { /* not a directory, or not ours to write in */ }
  }
  try {
    fs.accessSync('/dev/shm', fs.constants.W_OK);
    if (fs.statSync('/dev/shm').isDirectory()) return '/dev/shm';
  } catch (e) { /* no shm, or not ours to write in */ }
  return path.join(ROOT, 'rpi');
}

function handoffPath(base) {
  var dir = handoffDir();
  // Invisible-by-dot is right in a checkout and useless anywhere else, which is
  // where you look to find out what is holding memory. Named so it is obvious
  // whose it is and safe to delete. Mirrors _name() in handoff.py, which asks
  // the same question the same way round: dotted only in the checkout itself.
  return path.join(dir, dir === path.join(ROOT, 'rpi')
    ? base : 'uberscan-' + base.replace(/^\./, ''));
}

var WATCH_PATH = handoffPath('.viewing');
var RESET_PATH = handoffPath('.recalibrate');
var DROPOFF_PATH = handoffPath('.dropoff');
var CROP_PATH = handoffPath('.cropbox.json');
var cropSeq = 0;
var lastTouch = 0;
var lastView = '';

/* Which picture the browser is asking for, carried in the file that already
 * says somebody is asking. Two views: `scene` is the wide shot with the
 * corners drawn on, for aiming the camera; `screen` is the phone's own screen
 * flattened and filling the frame, for reading the phone through the rig's
 * display. See SCREEN_HEIGHT in rpi/scan_pi.py for why it has to be a
 * different picture rather than a bigger one.
 *
 * In the file rather than in a new endpoint because the two facts expire
 * together. A mode set by its own request would outlive the browser that set
 * it — close the tab in phone view and the scanner keeps paying for phone
 * frames nobody is looking at, until something else happens to correct it.
 * Written by the request for a frame, so it lasts exactly as long as someone
 * is fetching frames, and an unknown or missing value is the scene.
 */
function touchWatchFile(view) {
  var want = view === 'screen' ? 'screen' : 'scene';
  var now = Date.now();
  // The mtime only needs to be recent — but a *change* of view has to go
  // through at once, or switching costs the driver up to a second of looking
  // at the wrong picture and wondering whether the button worked.
  if (now - lastTouch < 1000 && want === lastView) return;
  lastTouch = now;
  lastView = want;
  /* Written through a rename, the same way the scanner writes a frame.
   *
   * Once this file had contents worth reading it also had a window in which it
   * had none: writeFile truncates and then writes, and the scanner reads this
   * on its own clock, up to thirty times a second. Catching the gap makes the
   * scanner see an empty file, which it reads — correctly — as "no view named,
   * use the scene", and it then caches that against the mtime. If the mtime of
   * the truncate and of the write land in the same tick, the cache is not
   * invalidated and the driver watches the wrong picture until the next write,
   * up to a second later. A rename has no such window: the scanner sees the
   * old contents or the new ones. */
  fs.writeFile(WATCH_PATH + '.part', want + '\n', function (err) {
    if (err) return;
    fs.rename(WATCH_PATH + '.part', WATCH_PATH, function () {});
  });
}

/* The order the driver is currently carrying, or null.
 *
 * Marking an offer taken is already recorded — it is what the shift line counts
 * — but it was only ever a fact about the past. Working two apps at once needs
 * it as a fact about the present: while an order is in the car, the next offer
 * is not a standalone job, it is a second one to fit around the first.
 *
 * It expires on its own clock. A driver who has just accepted on their phone
 * and is pulling into traffic will not reliably press a second button when they
 * drop off, and an order that never ends would put a stale job's minutes
 * against every offer for the rest of the shift — a wrong number that gets more
 * wrong the longer it sits. So the card's own stated duration ends it, with a
 * margin: an order runs long, and finishing a little late is normal.
 *
 * The margin is generous on purpose. Ending it early costs a stacking figure
 * the driver could have used; ending it late costs a wrong one. Neither is
 * free, but the panel only shows this alongside the standalone verdict, which
 * is unaffected either way — so the cheaper mistake is to keep offering it.
 */
var HOLD_OVERRUN = 1.5;      // an order may take half again its stated time
// ...plus ten minutes, before it is forgotten.
//
// Settable, like SCANNER_SILENT_MS and for the same reason. Expiry is the one
// thing about a carried order that no test could reach: ten minutes of grace
// is ten minutes of waiting, so every path that asks "is an order being
// carried" was checked only on orders that were plainly still live, and the
// four places that answered it off the raw slot instead of through holding()
// were indistinguishable from the ones that did it properly.
//
// Written the long way rather than `Number(env) || default`, because the value
// this exists to allow is ZERO and that idiom would throw it away.
var HOLD_GRACE_MS = Number(process.env.HOLD_GRACE_MS);
if (!isFinite(HOLD_GRACE_MS) || HOLD_GRACE_MS < 0) HOLD_GRACE_MS = 10 * 60000;

function holding(now) {
  var h = scanner.holding;
  if (!h) return null;
  var stated = (typeof h.minutes === 'number' && isFinite(h.minutes) && h.minutes > 0)
    ? h.minutes : null;
  if (stated === null) return null;
  var over = (now - h.acceptedAt) - (stated * HOLD_OVERRUN * 60000) - HOLD_GRACE_MS;
  if (over > 0) {
    scanner.holding = null;
    return null;
  }
  return h;
}

/* What the pair would pay, when there is a pair.
 *
 * Worked out here rather than on the page because the order being carried is
 * this process's knowledge — several panels may be open and a figure computed
 * in each of them is a figure that can disagree with itself.
 *
 * Applied to the replay a new listener gets as well as to live readings, and
 * that is not a tidiness point: a panel opened in the middle of a delivery is
 * precisely when a second app's offer is on the phone, and a replay without
 * this shows the driver a standalone verdict for a job they cannot do alone.
 * Computed against the clock at the moment it is sent, so a reading replayed
 * ten minutes later is stacked against ten fewer minutes.
 */
function withStack(read, now) {
  if (!read || !read.ready) return read;
  var held = holding(now);
  read.holding = held
    ? { pay: held.pay, minutes: held.minutes, dropoff: held.dropoff || null }
    : null;
  read.stack = held
    ? Advice.stack(held, read, { target: read.target, band: read.band,
                                 costPerMile: read.costPerMile }, now)
    : null;
  return read;
}

/* The pairing, written down at the moment it is made.
 *
 * The stack line is the newest and least-proven thing on this rig, and until
 * this it left no trace: a shift driven to test it came back with the offers
 * and the marks, and nothing at all about what the panel had ADVISED. "When it
 * said take both, was it right?" was unanswerable from the file the shift
 * produced, which makes the shift a test of nothing.
 *
 * What is recorded is what a person would need to grade one decision without
 * having been there: both ends, both payouts, the range the panel drew, the
 * colour it drew it in, and the geography verdict — including the ones where
 * the geography said nothing, because "how often can it say anything" is the
 * question this feature lives or dies by.
 *
 * `held.dropoff` and `held.dropoffScanned` together are the other half of it:
 * whether the destination came off the card or off a scan of the screen after
 * the accept, which is the difference the ⌖ Dropoff button exists to make.
 *
 * Best-effort. A journal that cannot be written must never stop the panel from
 * answering — the advice is the product, this is the notebook.
 */
function recordPairing(offer, now) {
  var held = holding(now);
  if (!held || !offer || typeof offer.id !== 'string') return;
  var s = Advice.stack(held, offer, { target: offer.target, band: offer.band,
                                      costPerMile: offer.costPerMile }, now);
  var row = {
    v: 1, kind: 'pair', at: now, id: offer.id,
    // The order already in the car.
    held: {
      pay: numOrNull(held.pay), minutes: numOrNull(held.minutes),
      dropoff: held.dropoff || null,
      scanned: !!held.dropoffScanned,
      heldMs: Math.max(0, now - held.acceptedAt)
    },
    // ...and the one being judged against it.
    offer: {
      pay: numOrNull(offer.pay), minutes: numOrNull(offer.minutes),
      dropoff: offer.dropoff || null, pickup: offer.pickup || null
    },
    // What the panel actually said. Null when it said nothing, which is a
    // measurement in its own right and must not be dropped as "no data".
    stack: s ? { pay: s.pay, worst: s.worst, best: s.best,
                 minMinutes: s.minMinutes, maxMinutes: s.maxMinutes,
                 state: s.state, sure: !!s.sure, ends: s.ends || null } : null
  };
  appendLines(JSON.stringify(row) + '\n', function (err) {
    if (err) console.error('journal: could not record a pairing: ' + err.message);
  });
}

function broadcast(read) {
  withStack(read, Date.now());
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
                   // Which end is which. `places` below is what the card
                   // printed; these say which of them is the shop and which is
                   // somebody's front door, so an export can be replayed
                   // through Advice.sameArea to see what the rig would have
                   // said about stacking any two of these offers.
                   'pickup', 'dropoff',
                   // Where it went, joined with a semicolon so one cell holds
                   // both ends of a ride without breaking the comma-separated
                   // file it sits in.
                   'places', 'deliverBy', 'fromDeadline', 'ms',
                   // Every OTHER frame's reading of the same card, joined with
                   // a pipe. The row's `text` is the one that won; a card is
                   // read four to eight times and where those readings DIFFER
                   // is the only record of what this camera does to a real
                   // screen at night. Pipes because the separator here is a
                   // comma and a mangled card is full of them.
                   'scans',
                   // At the end, deliberately — toCsv appends `when` after
                   // it, so this is the second-to-last column and the
                   // human-readable timestamp keeps the edge it has always had.
                   //
                   // The only column that is not a figure: it is what the
                   // reader read, kept so a question about the parser can be
                   // answered against this driver's own cards instead of
                   // against rendered replicas. A spreadsheet puts it out to
                   // the right where it is out of the way until it is wanted,
                   // and every column before it keeps its position.
                   'text'];

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
  // A pairing has an id and no seq, which is the shape the fallback below
  // rejects — so without this branch every one of them would be dropped by the
  // sync, quietly, under a `malformed` count nobody reads. That is the same
  // failure this comment block already describes for marks, and it would land
  // on exactly the rows a shift is driven to collect: the copy on the box at
  // home would have the offers and none of the advice.
  //
  // Identified like a mark: which offer, and when it was written. Both are
  // fixed the moment it lands on disk and neither is rewritten.
  if (row.kind === 'pair') {
    if (typeof row.id !== 'string' || !row.id) return null;
    return key(['p', row.id, row.at]);
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
  // The winner is taken whole, and an address is not one of the fields the vote
  // is about — so a reading that scored best on pay, minutes and miles took its
  // empty `places` with it and the offers page showed no address for a card
  // another reading of the same card had read the map off perfectly well.
  //
  // Only ever filled in, never overruled: where the winner has an address that
  // is the one to show, because it is the reading the numbers came from.
  //
  // And borrowed from a reading that agrees about the card before any other.
  // "The first row with an address" is not a rule, it is an accident of order:
  // on a card read three times where the outvoted reading had one address and
  // an agreeing reading had another, it showed the outvoted one's.
  if (!(best && best.places && best.places.length)) {
    var lends = rows.filter(function (r) {
      return r !== best && r.places && r.places.length && !r.suspect
        && r.whole !== false;
    });
    var agrees = lends.filter(function (r) {
      return r.pay === best.pay && r.minutes === best.minutes
        && r.miles === best.miles;
    });
    var lender = (agrees.length ? agrees : lends)[0];
    // Copied rather than assigned into. These row objects come straight off the
    // journal and are read again by the next request.
    if (lender) best = Object.assign({}, best, { places: lender.places });
  }
  return best;
}

function latestPerOffer(rows) {
  var byId = Object.create(null);
  var out = [];
  var marks = Object.create(null);
  var rules = [];
  // How many cards the rig watched go past, from the scanner's own tally. Kept
  // beside the offers rather than in them: it is a fact about the window, not
  // about any one card, and the page needs both to say what fraction was
  // recorded.
  var seen = [];
  var readings = Object.create(null);

  rows.forEach(function (r) {
    if (!r || typeof r !== 'object') return;
    if (r.kind === 'mark') {
      if (r.id) marks[r.id] = Object.assign(marks[r.id] || {}, r);
      return;
    }
    if (r.kind === 'rule') { rules.push(r); return; }
    if (r.kind === 'seen') { seen.push(r); return; }
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

  out.sort(function (a, b) { return (a.at || 0) - (b.at || 0); });
  out.seen = seen;
  return out;
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

/* The journal, as rows. `done(rows, err)`: rows is [] when there is simply no
 * journal yet, and null when there is one and it could not be read.
 *
 * Those two used to be the same answer, and the comment below said why — a
 * missing file is not an error. It is not; the other thing is. A journal that
 * exists and cannot be read answered [] as well, and [] is not "I do not know",
 * it is "there is nothing", which the sync endpoints believe.
 *
 * Reproduced against the real server, running as a user that could append to
 * the journal but not read it — which is the one shape that reaches this, since
 * every error that also breaks the append is already refused loudly. Twenty
 * rows on disk, then the same twenty POSTed three times:
 *
 *     GET  /api/journal/newest  -> {"ok":true,"newest":0,"have":0,"offers":0}
 *     POST /api/journal/ingest  -> {"ok":true,"added":20,...}   three times
 *     lines on disk: 80
 *
 * The de-duplication that makes ingest idempotent is a set built from the rows
 * already there, so an empty set makes every incoming row look new. Sixty
 * duplicate rows, `ok: true`, and a `have` that is wrong. And `newest: 0` sends
 * the rig back to a thirty-day floor, so it re-sends everything every ten
 * minutes and the far end appends all of it, reporting success each time. The
 * backup quietly fills with copies while both ends say it is working.
 */
/* What this build of the far end understands. Sent whether or not the journal
 * can be read, because it is how a sender tells a current build from an old one
 * — and a rig told nothing about a reachable machine goes on to blame it for
 * being out of date. */
var SYNC_CAN = ['ingest', 'config', 'mkdir', 'count'];

function readJournal(done) {
  fs.readFile(JOURNAL_PATH, 'utf8', function (err, text) {
    // Nothing recorded yet is not an error. Anything else is.
    if (err) return done(err.code === 'ENOENT' ? [] : null, err);
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

// 1 Jan 2025. Below this a timestamp is not a moment, it is a Pi that has not
// heard from NTP yet: the board has no real-time clock, boots in 1970 and jumps
// when the network arrives, and its systemd unit is ordered After=multi-user
// only — so it genuinely can record offers before its clock is right.
// scan_pi.py holds the same number for the same reason and will not judge a
// delivery deadline below it.
//
// Those rows are stamped 1970 on disk forever. They cannot fall inside any
// day window, so a shift figure has to either lie about them or say how many it
// could not place. It says.
var CLOCK_BELIEVABLE_AFTER = 1735689600000;

// The value below which a given share of offers fall, interpolated between the
// two straddling samples. A byte-for-byte port of journal.html's percentile()
// on purpose: the driving screen and the offers page must not be able to print
// different medians for the same day, and two implementations that round
// differently would do exactly that on an even-sized window.
function percentileOf(sorted, share) {
  if (!sorted.length) return null;
  if (sorted.length === 1) return sorted[0];
  var pos = share * (sorted.length - 1);
  var low = Math.floor(pos), high = Math.ceil(pos);
  return sorted[low] + (sorted[high] - sorted[low]) * (pos - low);
}

// What one shift adds up to, over rows the journal has already been read into.
//
// Every figure here comes off ONE filtered set, which is the rule journal.html
// learned the hard way: its median already excluded the rows it set aside and
// the money beside it did not, so a day carrying two misread payouts announced
// two and a half thousand dollars offered next to a median of thirteen.
// Figures on one line that disagree about what they are counting are worse
// than one figure.
//
// `counted` is journal.html's counted() — Advice.trustworthy plus a rate to
// draw — and nothing else. The isFinite is belt over braces: JSON cannot carry
// a NaN, so it can never change the answer for a row that came off disk, and
// it keeps the median's arithmetic from being handed one if a caller ever
// builds rows some other way.
function shiftSummary(rows, since) {
  var offers = latestPerOffer(rows);
  var early = 0;
  var window = [];
  offers.forEach(function (o) {
    // A row the driver hid is not an offer they were made — the test card
    // presented to check the rig is not a job. /api/journal drops these before
    // the offers page ever sees them, so a hidden row is in neither its count
    // nor its set-aside figure, and this has to drop them too. Left in, they
    // landed in BOTH: counted as an offer, then rejected by trustworthy and
    // reported as one the scanner had set aside. The driving screen said "6
    // offers · 2 set aside" where the offers page said "5 offers (1 set
    // aside)" for the same day, and blamed the reader for an exclusion the
    // driver had made.
    if (o.hidden) return;
    var at = (typeof o.at === 'number' && isFinite(o.at)) ? o.at : null;
    if (at === null) return;
    if (at < CLOCK_BELIEVABLE_AFTER) { early += 1; return; }
    if (at >= since) window.push(o);
  });
  var counted = window.filter(function (o) {
    return Advice.trustworthy(o)
      && typeof o.perHour === 'number' && isFinite(o.perHour);
  });
  var rates = counted.map(function (o) { return o.perHour; })
    .sort(function (a, b) { return a - b; });
  return {
    // Offers, not readings. latestPerOffer folds the four-to-fourteen readings
    // one card produces down to the one row that card became — counting rows
    // would make a single offer look like a busy afternoon.
    offers: window.length,
    counted: counted.length,
    // Named rather than dropped. A row vanishing from a figure with nothing
    // saying so is the failure this project keeps writing sections about.
    setAside: window.length - counted.length,
    // Counted FIRST, then accepted — the same order journal.html uses. Taking
    // it off the raw window instead would put a bigger number on the driving
    // screen than the offers page shows for the same day.
    took: counted.filter(function (o) { return o.accepted; }).length,
    median: percentileOf(rates, 0.5),
    beforeClock: early
  };
}

// One answer, kept until the journal changes underneath it.
//
// The parse is synchronous once the file is in hand — split, then a JSON.parse
// per line — and it runs on the event loop that also drives the 12ms MJPEG tick
// and touches the file telling the scanner somebody is watching. A year of
// driving is a ~19MB journal and something on the order of a second of frozen
// loop on a Pi 4, so a page that asks repeatedly cannot be paying that every
// time. /api/journal/newest already sets the house budget for a journal-reading
// GET at "every few minutes"; this keeps to it and then some.
//
// Keyed on SIZE as well as mtime because the file is append-only apart from the
// 64MB roll, so size is monotonic where mtime granularity is not guaranteed.
// The cached value is the finished summary — never the parsed rows, which
// latestPerOffer writes `hidden` and `accepted` onto, safe today only because
// every request re-parses them fresh.
var shiftCache = null;

function todaySummary(since, done) {
  // Whether this machine's own clock can be believed at all. The browser cannot
  // check it — the browser's clock is fine, it is the rig's that is not — and
  // every figure below is a window on a timeline the rig may not yet know it is
  // on.
  //
  // Answered fresh on every request and deliberately NOT part of what is
  // cached. It changes on its own, without the journal changing: a rig that
  // boots, is looked at, and only then hears from NTP would otherwise keep
  // serving "waiting for the clock" out of the cache until the next offer was
  // written — through the whole first part of a shift, on a rig that by then
  // knew perfectly well what day it was.
  var clockSet = Date.now() >= CLOCK_BELIEVABLE_AFTER;
  var answered = function (answer) {
    // A shallow copy, because the cached object outlives this request and is
    // handed to the next one. Writing the flag onto it would work today and
    // become a shared-state bug the moment anything else is stamped per
    // request.
    var out = {};
    Object.keys(answer).forEach(function (k) { out[k] = answer[k]; });
    out.clockSet = clockSet;
    // Answered fresh for the same reason, and found by the check that covers
    // it: this depends on the SIBLING's mtime and on `since`, neither of which
    // is the journal file the cache is keyed on. Cached, a roll that happened
    // while journal.jsonl itself did not change was served the previous
    // answer's `false` — the one state it exists to report, reported wrong.
    // The stat only runs when there are no offers to report anyway.
    out.rolled = false;
    if (!out.offers && !out.unreadable) {
      try {
        out.rolled = fs.statSync(JOURNAL_PATH + '.1').mtimeMs >= since;
      } catch (e) { /* no sibling: this journal has never rolled */ }
    }
    done(out);
  };
  fs.stat(JOURNAL_PATH, function (statErr, st) {
    var size = st ? st.size : -1;
    var stamp = st ? st.mtimeMs : -1;
    if (shiftCache && shiftCache.size === size && shiftCache.stamp === stamp
        && shiftCache.since === since) {
      return answered(shiftCache.answer);
    }
    readJournal(function (rows, readErr) {
      // Empty and unreadable are different answers and the page says different
      // things about them. readJournal answers [] for a journal that is not
      // there yet and null for one that is there and could not be read.
      var answer;
      if (!rows) {
        answer = { unreadable: (readErr && readErr.code) || 'unknown' };
      } else {
        answer = shiftSummary(rows, since);
        answer.unreadable = null;
        // A journal that just rolled past 64MB is empty for the same reason a
        // brand new one is, and the difference matters: without this the panel
        // says "no offers yet" at eleven at night. Nothing here reads the .1
        // sibling — that is a bigger change than a status line — but it can at
        // least decline to claim the day was quiet.
        //
        // "A sibling exists" is NOT the test. journal.py rolls with os.replace
        // and nothing ever removes the .1, so one roll makes that true forever
        // and every quiet morning afterwards would announce a roll that
        // happened months ago — which is a worse lie than the one this is here
        // to prevent. What makes it this shift's business is the roll having
        // happened inside this window.

      }
      // An unreadable journal is not cached. It is a transient the next request
      // may not hit, and keying it on a size and mtime that did not change
      // would hold the failure up until the file did.
      if (size >= 0 && rows) {
        shiftCache = { size: size, stamp: stamp, since: since, answer: answer };
      }
      answered(answer);
    });
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
      // A list — the places an offer went, or every frame's reading of it — as
      // one cell. Semicolons for addresses, because the separator here is a
      // comma and an address is full of them; pipes for readings, because a
      // mangled card is full of semicolons too.
      // `scans` as JSON, everything else joined for a spreadsheet to read.
      //
      // The separator used to be " | " and the frames are OCR of a phone
      // screen: this project's own comments record that the card's icon row
      // and its dividers both come back as pipes, and `trim_place` cuts at the
      // first one for exactly that reason. So the column added to make the
      // frames analysable was splitting 19% of its own rows mid-frame -
      // measured on the first export that carried it, 57 of 296.
      //
      // JSON has no such collision: the quoting below already handles commas
      // and quotes, and a reader gets the frames back exactly as the rig saw
      // them. The other list columns keep the readable join - `places` is two
      // or three short strings a person reads in a cell, not something parsed
      // back.
      if (Array.isArray(v)) v = k === 'scans' ? JSON.stringify(v) : v.join('; ');
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
        // Remember it against the offer the driving screen is holding, so a
        // reload does not forget. The button's state was page-local: mark an
        // offer, reload the panel, and it offered to mark it again — while the
        // shift line beside it had already counted it. Two figures forty pixels
        // apart disagreeing about the same thing the driver just did.
        //
        // Only when it names that offer. A mark for anything else is about a
        // row on the offers page and says nothing about what is on this screen.
        if (note.kind === 'mark' && scanner.offer && scanner.offer.id === note.id
            && note.accepted !== undefined) {
          scanner.offer.accepted = note.accepted;
          // ...and it becomes the order in the car, which is what the next
          // offer gets measured against. Taking the mark back puts it down
          // again: the driver pressed it twice because they did not take it,
          // and stacking onto a job they refused is the same wrong number as
          // stacking onto one they already delivered.
          if (note.accepted) {
            scanner.holding = {
              id: scanner.offer.id,
              pay: scanner.offer.pay,
              minutes: typeof scanner.offer.billedMinutes === 'number'
                ? scanner.offer.billedMinutes : scanner.offer.minutes,
              miles: scanner.offer.miles,
              cost: scanner.offer.cost,
              // Where this one ENDS, so the next offer can be judged on more
              // than the clock. See Advice.sameArea: two pickups on the same
              // block are ordinary, two dropoffs twenty miles apart is the
              // trap, and only the second is worth refusing over.
              dropoff: scanner.offer.dropoff || null,
              pickup: scanner.offer.pickup || null,
              acceptedAt: Date.now()
            };
          } else {
            // Through holding() as well: taking the mark back off an order the
            // rest of the rig has already forgotten should not depend on which
            // of the two ways of asking this line happens to use.
            var carried = holding(Date.now());
            if (carried && carried.id === note.id) scanner.holding = null;
          }
        }
        // ...and whether there is now an order in the car, because marking is
        // the ONLY moment the panel can learn it in time to matter.
        //
        // The driver accepts on their phone, the card vanishes from the mount,
        // they press "Took" here - and the destination is on the phone RIGHT
        // NOW. But the panel only heard about a held order through a reading
        // (see withStack, which attaches `holding` when `read.ready`), and
        // there is no reading: the card is gone. So the two buttons that exist
        // for this exact moment, Drop and the destination scan, stayed hidden
        // until the NEXT offer card arrived - by which time the phone is
        // showing that card and not the address.
        //
        // Answered off the same question as everywhere else, so a hold the
        // server has already expired does not put a button back on the panel.
        send(res, 200, JSON.stringify({ ok: true, note: note,
                                        holding: !!holding(Date.now()) }),
             { 'Content-Type': 'application/json; charset=utf-8' });
      });
    });
  }

  /* Put the order down. The driver has dropped it off and the next offer is a
   * standalone job again.
   *
   * Separate from the mark, and deliberately: the mark is a permanent fact
   * about the journal — this offer was taken — and dropping it off does not
   * make that untrue. Only one of the two belongs on disk. This changes nothing
   * but what the panel measures the next card against, so it is memory only,
   * and a restarted server simply has no order in hand, which is the safe way
   * to be wrong.
   *
   * It answers the same either way. Pressing "delivered" with nothing in the
   * car is not an error a driver needs told about; it is the state they wanted. */
  if (req.method === 'POST' && req.url.split('?')[0] === '/api/delivered') {
    // holding(), not the raw slot: "there was an order to put down" has to mean
    // the same thing here as it does on the panel, or the driver is told they
    // put down a job the rig stopped counting an hour ago.
    var wasHolding = !!holding(Date.now());
    scanner.holding = null;
    return send(res, 200, JSON.stringify({ ok: true, wasHolding: wasHolding }),
                { 'Content-Type': 'application/json; charset=utf-8' });
  }

  // The one thing on this server that is not a read. It asks the scanner to
  // forget where it thinks the phone is; POST because it changes something, and
  // because a GET would be followed by anything that prefetches links.
  // "Read the screen in front of you as a destination."
  //
  // A request file rather than a reply, like every other thing the web side
  // asks the camera side for: the scanner is sometimes a child of this process
  // and sometimes a systemd unit that has never heard of it, and a file works
  // identically either way. The answer comes back up the scanner's own stdout
  // as a `dropoff` line, which is why this returns as soon as the ask is
  // written rather than waiting for one.
  if (req.method === 'POST' && req.url.split('?')[0] === '/api/dropoff') {
    return fs.writeFile(DROPOFF_PATH, '', function (err) {
      if (err) return send(res, 500, JSON.stringify({ ok: false, error: err.message }),
                           { 'Content-Type': 'application/json; charset=utf-8' });
      // ...and the same question the same way. This is what the page uses to
      // tell the driver whether the address it is about to read has a job to go
      // onto; answered off the raw slot it would promise one that no longer
      // exists, and the address would land somewhere nothing reads.
      send(res, 200, JSON.stringify({ ok: true, holding: !!holding(Date.now()) }),
           { 'Content-Type': 'application/json; charset=utf-8' });
    });
  }

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
      readJournal(function (existing, readErr) {
        // Without the rows already here there is no de-duplication, and
        // appending anyway turns every re-send into a copy. Refusing is the
        // only honest answer: the sender retries, and nothing is lost.
        if (!existing) {
          return fail('cannot read the journal to merge into it ('
                      + (readErr && readErr.code || 'unknown') + ')', 500);
        }
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
    return readJournal(function (rows, readErr) {
      // Answering 0 here is not a small error: the sender treats it as "the
      // far end has nothing", falls back to a thirty-day floor and re-sends a
      // month of offers, every ten minutes, for as long as the fault lasts.
      //
      // But not a 500 either, because this endpoint is also how the sender
      // works out what the far end can do — whether it understands `mkdir`,
      // whether it is an old build at all — and a rig told nothing about a
      // reachable machine goes on to blame it for being out of date. So it
      // answers, says it cannot read, and simply does not offer a number.
      if (!rows) {
        return send(res, 200, JSON.stringify({
          ok: false, readable: false,
          error: 'cannot read the journal (' + (readErr && readErr.code || 'unknown') + ')',
          can: SYNC_CAN
        }), { 'Content-Type': 'application/json; charset=utf-8' });
      }
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
                                      can: SYNC_CAN }),
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
  var wantView = '';
  try {
    var parsed = url.parse(req.url, true);
    pathname = decodeURIComponent(parsed.pathname);
    // Node hands back an array for a repeated key. Only the frame endpoints
    // look at this, and only ever for one of two known words, so anything
    // else — an array, a number, a novel — falls through to the scene.
    wantView = typeof parsed.query.view === 'string' ? parsed.query.view : '';
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
        // Times it was killed for going quiet while still running, as opposed
        // to times it fell over on its own. The two have different causes and
        // a count that merges them explains neither.
        wedged: scanner.wedged || 0,
        // A successful restart clears `error`, as it should — there is no
        // current problem. This is what is left to say a camera went quiet at
        // all, which is the difference between "it is fine now" and "it is fine
        // now for the third time this evening".
        wedgedAt: scanner.wedgedAt || null,
        startedAt: scanner.started,
        error: scanner.error
      },
      last: scanner.last,
      // How old those two are, in milliseconds, measured entirely on this
      // machine's clock.
      //
      // Ages rather than timestamps, and for the reason live.html already
      // documents about `at`: a Pi has no real-time clock, so it boots in 1970
      // and jumps when the network arrives. Handing a browser one machine's
      // absolute time to subtract from another's is how "12 seconds old"
      // became "fifty-six years old", and worse, how a negative age never
      // tripped the stale test at all. A duration has no origin to disagree
      // about.
      //
      // Without these the page seeded a verdict from here and started its own
      // staleness clock at zero, so opening the dashboard against a rig that
      // died an hour ago painted that offer's ACCEPT at full confidence: 12
      // seconds before it dimmed, 20 before anything said "last read ... ago".
      // The last offer written to the journal, and how long ago — the same
      // duration-not-timestamp rule as everything else here.
      offer: scanner.offer || null,
      offerAgeMs: scanner.offerAt ? Math.max(0, Date.now() - scanner.offerAt) : null,
      // The order in the car, so a panel opened or reloaded mid-delivery knows
      // there is one. An age rather than a timestamp, like everything else
      // here: the two machines' clocks are not the same clock.
      holding: (function () {
        var h = holding(Date.now());
        return h ? { pay: h.pay, minutes: h.minutes,
                     // Where it ends, and whether that came off the card or
                     // off a scan of the screen after the accept. The panel
                     // needs the difference: a card-derived dropoff is a
                     // cross-street, a scanned one is a full address, and the
                     // button that asks for one should stop offering itself
                     // once it has been answered.
                     dropoff: h.dropoff || null,
                     dropoffScanned: !!h.dropoffScanned,
                     heldMs: Math.max(0, Date.now() - h.acceptedAt) } : null;
      }()),
      lastAgeMs: (scanner.last && typeof scanner.last.at === 'number')
        ? Math.max(0, Date.now() - scanner.last.at) : null,
      heardAgeMs: scanner.heardAt
        ? Math.max(0, Date.now() - scanner.heardAt) : null,
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
    touchWatchFile(wantView);
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
          touchWatchFile(wantView);
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
    touchWatchFile(wantView);
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
    // The last reading, so a tab that has just connected is not blank until the
    // next one. Marked as the replay it is, and carrying its own age: the page
    // stamps every message bearing `ready` as freshly read, so without this a
    // dropped socket coming back re-aged a dead rig's verdict to zero — once
    // per reconnect, for as long as the tab stayed open.
    if (scanner.last) {
      // A copy, and `withStack` writes onto the copy. Stacking the stored
      // reading itself would leave a figure on it that goes stale the moment
      // the order is put down, and every later replay would carry it.
      res.write('data: ' + JSON.stringify(withStack(Object.assign({}, scanner.last, {
        replay: true,
        ageMs: (typeof scanner.last.at === 'number')
          ? Math.max(0, Date.now() - scanner.last.at) : null
      }), Date.now())) + '\n\n');
    }
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
    return readJournal(function (rows, readErr) {
      // This one may degrade — a driver looking at the offers page is better
      // served by the page than by a 500 — but not silently. An empty history
      // and an unreadable one look identical otherwise, and the second is the
      // one worth acting on.
      var unreadable = rows ? null : (readErr && readErr.code || 'unknown');
      rows = rows || [];
      var offers = latestPerOffer(rows);
      var seen = offers.seen || [];
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
      // What the rig watched go past, over the same window. Summed here rather
      // than shipped row by row: there is one of these every couple of minutes
      // of scanning and the page wants the total, not the series.
      var watched = { saw: 0, kept: 0 };
      seen.forEach(function (r) {
        if (floor && (r.at || 0) < floor) return;
        watched.saw += r.saw || 0;
        watched.kept += r.kept || 0;
      });
      send(res, 200, JSON.stringify({ count: offers.length, total: total,
                                      truncated: total > offers.length,
                                      days: days, hidden: hidden,
                                      watched: watched,
                                      // Null unless the journal is there and
                                      // could not be read, in which case the
                                      // emptiness below is not a record of a
                                      // quiet week.
                                      unreadable: unreadable,
                                      offers: offers }),
           { 'Content-Type': 'application/json; charset=utf-8' });
    });
  }

  // What the shift adds up to so far, for the one line of it the driving screen
  // shows. The offers page works this out for itself from the rows it already
  // has; the driving screen has no rows and must not grow a second copy of the
  // rule for deciding which ones count, so the arithmetic happens here.
  if (pathname === '/api/today') {
    var tq = url.parse(req.url, true).query || {};
    var sinceMs = parseInt(tq.since, 10);
    // Required, and required to be believable. /api/journal can afford
    // clampNumber's zero fallback because `days` independently defaults to 30;
    // alone, a zero floor means the entire journal, which the caller would then
    // put on a panel under the word "today". A window this endpoint cannot
    // believe is an error, never a silent all-time figure.
    //
    // The browser names it, for the reason /api/journal takes it from the
    // browser too: only the page knows where the driver is, and therefore when
    // their day began. 4am, in their timezone, is journal.html's boundary and
    // the one the page sends.
    if (!isFinite(sinceMs) || sinceMs < CLOCK_BELIEVABLE_AFTER
        || sinceMs > 4102444800000) {
      return send(res, 400, JSON.stringify({
        ok: false,
        error: 'since must be an epoch-ms moment in this century'
      }), { 'Content-Type': 'application/json; charset=utf-8' });
    }
    return todaySummary(sinceMs, function (answer) {
      send(res, 200, JSON.stringify(answer),
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
  // Not 403: whether a file of that kind exists here is not this server's
  // business to confirm, and a directory request has already been turned into
  // index.html by the time it reaches here.
  if (!isServable(pathname)) {
    return send(res, 404, 'not found', { 'Content-Type': 'text/plain' });
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
  // Checked often enough that the reported silence is roughly true, cheaply
  // enough that it is not worth thinking about: one comparison a few times a
  // window. unref so it can never be the thing keeping the process alive.
  silentTimer = setInterval(watchForSilence, SILENT_TICK_MS);
  if (silentTimer.unref) silentTimer.unref();
} else if (process.env.SCANNER === '0') {
  console.log('\nPi scanner disabled (SCANNER=0).');
}
