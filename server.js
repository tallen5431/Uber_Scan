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
// The NucBox's street index (see "the NucBox's street index" below). Plain
// CommonJS, no browser half: only this server and the suites read it.
var Streets = require('./streets.js');
// Map view's own rules for where a place is, so "door level" means one thing.
// A UMD like advice.js that touches no browser global at load. Used here for
// the GPS drop (see gpsArrival) and the server's own search for its end (see
// searchHeldEnd): searchPlan, hasDoor, discFor, discBox, pickInDisc and
// crowMiles, so a pin is held to exactly the door rule the page chooses by.
var MV = require('./map-view.js');
// The assembler: every decision about where the order in the car ends — an
// address the scanner read, a Trip Planner over one page or several, the
// planner's stops coming off the hold. A UMD like advice.js with no I/O; this
// file keeps the writing and the saying. See assemble.js.
var Assemble = require('./assemble.js');
// ...and its memory: the planner pages seen, the pending pool, what the hold
// was last told. Process memory, like the slot.
var assembly = Assemble.fresh();

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
 * Started automatically wherever rpi/autopilot.py exists — that is, on any
 * checkout of this repository that has the rig's code in it. There is no
 * environment variable to set, since a process manager runs `npm start` with no
 * shell to set one in. SCANNER=0 turns it off.
 *
 * NOT gated on rpi/config.json, which is what this said. The autopilot
 * calibrates itself, so waiting for that file would mean waiting for a manual
 * step that no longer exists — see scannerEnabled(), which says so, and
 * calibrated(), which reads config.json for the status field and gates
 * nothing.
 *
 * Worth being exact about because of which way the error points. A driver on a
 * never-calibrated Pi reads this, concludes no camera process has been
 * spawned, and runs `python3 rpi/calibrate.py` or `rpi/preview.py` by hand —
 * against a camera this process is already holding. Both READMEs describe the
 * real behaviour; only this paragraph did not.
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
  // The scanner's sightings, counted by screen type: see countSighting. A
  // lifetime tally for the same reason as `wedged`.
  screens: {},
  // What went wrong with the scanner process, and nothing else. See `stderr`
  // beside it, and the 'close' handler, which is the one place a process's own
  // words become this.
  error: null,
  // The last few lines the scanner printed to stderr, kept as what they are.
  //
  // They used to be stored straight into `error`, every chunk of them, and a
  // running scanner prints things there that are not errors. The 📷 Snap of
  // 8 Oct 15:45 has `running: true` beside error "Error in boxClipToRectangle:
  // box outside rectangle Error in pixScanForForeground: invalid box", which is
  // leptonica, inside tesseract, narrating a crop it clipped — while the scanner
  // went on reading. The panel prints `error` as the reason when the scanner is
  // NOT running, so a crash with nothing to say for itself (a SIGKILL, a
  // segfault in the camera driver) would have been explained to the driver by
  // whatever the library had muttered last, possibly hours before.
  stderr: null,
  // Set up HERE and never again, which is the difference that matters: these
  // two are facts about the DRIVER'S CAR, not about the scanner process, so
  // startScanner() deliberately leaves them alone. See the note there.
  offer: null,         // the last offer read, so it can still be marked taken
  offerAt: null,
  // ...and when it was last READ, which offerAt is not: offerAt is when the
  // card came onto the slot and does not move while it is re-read. What a
  // customer's place popup is held to (popupArrived).
  offerSeenAt: null,
  // ...and offerAt for the cards on the slot before it, newest last, as
  // {id, at}: what a ✓ Took from a panel that has fallen behind dates its
  // order from (cardArrivedAt). As many as rpi/journal.py keeps ids for
  // (RECENT_CARDS, 8).
  offerAts: [],
  // The orders being carried, first-taken first: a LIST, capped at MAX_HELD.
  // Read through heldOrders() and holding(), never directly. See holding().
  held: [],
  // What the running scanner says it is pricing a mile at — its own word, off
  // the stream, not a file on this machine. A fact about the PROCESS, so
  // startScanner() clears it: the next one reads config.json afresh and says
  // again. See /api/settings.
  costPerMile: null
};

var listeners = [];    // open server-sent-event responses
// The orders in the car as the last beat said them (holdIds, space-joined), or
// null before the first: the beat carries `holding` when this changes.
var beatHeldSaid = null;

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
  // SCANNER_ARGS is the whole command line under SCANNER_CMD (the tests use
  // it for a stand-in scanner) and extra flags for the autopilot otherwise —
  // --keep-scans, --no-track, --screen-fps — which had no route at all under
  // `npm start` or the service, though the README documents every one.
  var extra = process.env.SCANNER_ARGS
    ? process.env.SCANNER_ARGS.split(' ').filter(function (a) { return a; }) : [];
  if (cmd) args = extra;
  else args = args.concat(extra);
  if (process.env.SCANNER_SPEAK !== '0' && !cmd) args.push('--speak');

  scanner.proc = spawn(bin, args, { cwd: ROOT });
  scanner.started = Date.now();
  scanner.error = null;
  scanner.stderr = null;           // ...and what the last process printed
  scanner.heardAt = null;          // nothing from the scan loop yet
  scanner.costPerMile = null;      // ...and nothing about its settings either
  scanner.beat = null;             // ...nor a heartbeat. See /api/status.
  // What is NOT cleared here, and why.
  //
  // `started`, `error`, `stderr` and `heardAt` are facts about the PROCESS, and
  // a new process makes them false. The order in the car is not one of those.
  // It is a fact about the driver's car, established by their own press of
  // "Took", and a camera that crashed says nothing about whether there is food
  // on the back seat.
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

  // What this process last printed to stderr with nothing on stdout since —
  // set by the stderr handler below, emptied by any stdout at all, and read
  // only when it exits. Per process, so a new one starts with none.
  var lastWords = '';

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
    // The reason it is not running, which is now true: it exited. Not over
    // an `error` already set for this process — "could not start" before
    // this, or the watchdog's account of a kill it made — since both are
    // better accounts of this same exit than an exit code.
    //
    // With its last words, and only its last words: stderr this process
    // printed and said nothing on stdout after. A traceback is the last thing
    // a Python crash prints, so it qualifies. A library warning the scan loop
    // carried on reading through has a heartbeat behind it — one every four
    // seconds at most (ALIVE_EVERY in rpi/scan_pi.py) — so it does not, and
    // a SIGKILL or a segfault that said nothing says "exited (SIGKILL)"
    // rather than borrowing the last thing anything muttered. It is still in
    // `stderr`, for whoever opens the status link. The one case this cannot
    // tell apart is a warning in the last four seconds before a death that
    // printed nothing, which then rides along behind an exit it did not cause
    // — and even then the line opens with the exit, which is true.
    if (!scanner.error) {
      scanner.error = 'exited (' + (signal || code) + ')'
                    + (lastWords ? ': ' + lastWords : '');
    }
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
    // Anything at all: a reading, a heartbeat, a log line. The process was
    // still going after whatever it last put on stderr.
    lastWords = '';
    buffered += chunk.toString();
    var lines = buffered.split('\n');
    buffered = lines.pop();          // keep the partial line for next time
    lines.forEach(function (line) {
      line = line.trim();
      if (!line) return;
      var read;
      try {
        read = JSON.parse(line);
      } catch (e) {
        console.log('scanner: ' + line);   // not JSON, so it is a log line
        return;
      }
      if (!read || typeof read !== 'object') {
        console.log('scanner: ' + line);   // JSON, but no message: a log line too
        return;
      }
      // ...and a message this process then fails on is ITS fault, said as one
      // with the stack that names where. One try round both used to log a
      // throw anywhere below as `scanner: <the line>`, the shape of a
      // library's chatter on the scanner's stdout: a planner line whose stops
      // held a null was printed as if the scanner had said it, with nothing
      // pointing at this file.
      try {
        read.at = Date.now();
        // A sighting (rpi/scan_pi.py, emit_sighting): what a whole-screen or
        // planner read saw, typed by its screen. Counted by that type for
        // /api/status, and — Stage 3 — handed to the assembler, which is now
        // where a Trip Planner's one dropoff comes from: off one page as the
        // scanner used to decide it, or off several pages stitched. What it
        // offers goes through the one dropoff path below (dropoffArrived),
        // exactly as a dropoff line from the scanner does, and is said to the
        // panel as one. The sighting itself is still not broadcast and writes
        // no row: its stops are names and front doors, and the stream is
        // somewhere they have not been before. See countSighting.
        if (read.sighting) {
          countSighting(read.sighting);
          var sightedNow = Date.now();
          // The orders in the car, as the assembler takes them: one is the
          // order (Stage 3, unchanged), two only while carrying two is on.
          var assembled = Assemble.sighting(assembly, assemblerHeld(sightedNow),
                                            read.sighting, sightedNow);
          assembled.candidates.forEach(function (c) {
            var said = { dropoff: c, at: Date.now() };
            dropoffArrived(said);
            if (said.dropoff) broadcast(said);
          });
          // ...and what waited for a cue asked again: this sighting may be it.
          retryPool();
          return;
        }
        // DoorDash's place popup (rpi/scan_pi.py, emit_popup): an address the
        // driver tapped a stop on the card being screened to show. Filed onto
        // that card or nowhere, by the assembler; never onto the order in the
        // car. See popupArrived.
        if (read.popup) {
          popupArrived(read.popup, Date.now());
          return;
        }
        if (read.phase) {
          scanner.phase = read.phase;
          scanner.status = read;
          if (read.message) console.log('scanner[' + read.phase + ']: ' + read.message);
        }
        // Setup messages carry no rate, so they must not overwrite the last read.
        if (read.ready !== undefined) scanner.last = read;
        // The cost per mile the scan loop is using, said when it starts and
        // whenever the driver changes it. See /api/settings.
        if (read.settings && typeof read.settings.costPerMile === 'number') {
          scanner.costPerMile = read.settings.costPerMile;
        }
        // Which offer is on the record, so the driving screen can offer to mark
        // it as taken. Held here as well as pushed, because a tab opened after
        // the card has gone — which is the normal case, the driver accepts on
        // the phone and the card disappears — would otherwise have nothing to
        // mark. Cleared by nothing: the last offer stays markable until the
        // next one replaces it.
        if (read.offer && typeof read.offer.id === 'string') {
          // The same card read again — a fuller reading of it, or the scanner
          // resuming it after a restart — replaces what is on record and
          // keeps the mark; a different card starts afresh, and is the one
          // moment the pairing below is written. Before this every restart
          // mid-card wrote a second pair row for the same id.
          var sameCard = scanner.offer && scanner.offer.id === read.offer.id;
          if (sameCard && scanner.offer.accepted !== undefined) {
            read.offer.accepted = scanner.offer.accepted;
          }
          // ...and the destination read off the PHONE, for the same reason.
          //
          // A later reading is a better reading of the CARD. It says nothing
          // about what the phone answered when the driver asked it, and this
          // assignment replaces the slot object wholesale — so without this the
          // press was thrown away by the next reading of the card it belonged
          // to, which arrives within seconds because every card here is read
          // repeatedly as the reading improves.
          //
          // What made that a wrong ADDRESS rather than a lost one: the guard
          // below is `wasAsked || !scanner.offer.dropoff`, and wiping the field
          // re-opens it. The next unprompted sighting — a navigation screen
          // left up, the previous job's — was then accepted over the press and
          // appended as a second mark. Reproduced end to end: pressed for
          // "123 Oak St", the card read again, and the panel and the journal
          // both ended up saying "999 Wrong Way Dr".
          if (sameCard && scanner.offer.dropoffScanned && scanner.offer.dropoff) {
            read.offer.dropoff = scanner.offer.dropoff;
            read.offer.dropoffScanned = true;
            // ...and whether it was pressed for, which the hold made from this
            // card at ✓ Took takes as its provenance (Assemble.cardFields).
            read.offer.dropoffFrom = scanner.offer.dropoffFrom;
          }
          // ...and the store's door a place popup gave it, for the same
          // reason: the next reading of the card is seconds away and knows
          // nothing of the tap.
          if (sameCard && scanner.offer.pickupAddr) {
            read.offer.pickupAddr = scanner.offer.pickupAddr;
          }
          // ...and whether this is the order already in the car, back on the
          // phone (heldOwnCard). Decided once, on arrival, and carried across
          // re-reads like the mark: the panel shows it as the order taken, and
          // no pairing row is written for it below.
          //
          // Under its OWN id as well as under a new one. The scanner now keeps
          // a card's id when the driver pages away and back (rpi/journal.py,
          // RECENT_CARDS), so the held card returns after another card under
          // the held order's id — which is that order by the journal's own
          // word, however long after the Took. This tested `!==` for as long
          // as a held id could only reappear as the same slot (sameCard), and
          // with `!==` that return was paired with itself.
          //
          // ANY order in the car, first-taken first: with two held, the second
          // one's card back on the phone is that order too.
          var carriedNow = heldOrders(Date.now()).filter(function (h) {
            return read.offer.id === h.id || heldOwnCard(h, read.offer, Date.now(), false);
          })[0] || null;
          if (sameCard && scanner.offer.heldCard) {
            read.offer.heldCard = scanner.offer.heldCard;
          } else if (!sameCard && carriedNow) {
            read.offer.heldCard = holdIdOf(carriedNow);
          }
          scanner.offer = read.offer;
          if (!sameCard) {
            scanner.offerAt = Date.now();
            scanner.offerAts = scanner.offerAts.filter(function (c) {
              return c.id !== read.offer.id;
            }).concat([{ id: read.offer.id, at: scanner.offerAt }]).slice(-OFFER_ATS_MAX);
          }
          // ...and its reading, for the offers page's ✓ (offersTickHolds).
          keepOfferCard(scanner.offer, scanner.offerAt);
          scanner.offerSeenAt = Date.now();
          // ...and the Trip Planner a press read goes, as it goes off the
          // panel at this moment. See forgetPlanner.
          if (!sameCard) forgetPlanner(Date.now());
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
          //
          // Not for the held order's own card come back, under its own id or
          // a new one: that is one order measured against itself (above).
          if (!sameCard && !scanner.offer.heldCard) {
            recordPairing(scanner.offer, Date.now(), scanner.last);
          }
        }
        // The destination, read off the screen that comes AFTER the accept:
        // see dropoffArrived, which is this branch moved out so an address the
        // assembler made off a planner's sighting takes the same road.
        dropoffArrived(read);
        // ...and, with two orders in the car, what waited for a cue asked
        // again: an address just filed may be the one that eliminates.
        retryPool();
        // Uber's Trip Planner, read off the whole screen because ⌖ was
        // pressed: every stop of the trip in order. See emit_planner.
        //
        // To the panel on the stream — the broadcast below sends it whole, as
        // it sends a dropoff line — and onto the order in the car, so a panel
        // reloaded mid-delivery shows the stops it showed before. Kept there
        // for exactly as long as the panel keeps them, which is not as long as
        // the order: see forgetPlanner. With nothing held there is nothing to
        // attach them to, and like an address read with nothing held they are
        // shown and not kept. Through holding(), for the reason the dropoff
        // branch gives. The stops and the scanner's reason for filing none of
        // them as the order's end travel together, so a reloaded panel says
        // the same thing about the button as the live one did.
        //
        // NOT a destination. The one dropoff of a planner is the assembler's
        // to give, off the `sighting` the scanner sends just before this line
        // for the same read (the two carry the read's `at`), and it is filed by
        // dropoffArrived like every other; nothing here reads an address out
        // of the stops, so there is one rule for where an order ends. The
        // reason none was filed is the assembler's too, and goes onto the line
        // here so the panel says it: a scanner from before the assembler said
        // its own on the line, and that is believed as it was.
        //
        // Into the journal only when the scanner says the record may hold
        // them — `keep`, which is `"keepPlaces"` and --no-journal: the stops
        // are customers' names and front doors.
        if (read.planner && Array.isArray(read.planner.stops)) {
          var plannedAt = Date.now();
          if (!('unfiled' in read.planner)) {
            var verdict = Assemble.verdictFor(assembly, read.planner.at);
            read.planner.unfiled = verdict === undefined ? null : verdict;
          }
          var heldNow = holding(plannedAt);
          // With two orders in the car, a pickup whose name is ONE of their
          // cards' pickups (Assemble.sameStore) is marked with that order's
          // id, `of`, which Map view numbers its pin by (P1, P2). One that
          // fits both, or neither, is no order's and stays a plain P.
          // The page this read was, off its sighting (same `at`): its app
          // for ownPickups, and whether it shows the top of the list.
          var plannerPage = Assemble.pageOf(assembly, read.planner.at);
          ownPickups(read.planner.stops, plannedAt, plannerPage, read.planner.at);
          if (heldNow) {
            var heldWas = JSON.stringify(scanner.held);
            heldNow.planner = { stops: read.planner.stops,
                                unfiled: read.planner.unfiled || null };
            // ...and a pickup it lists no longer marked visited, by the
            // planner's word (plannerVisits) — only off a read that shows
            // the list from its top. It writes the orders when this changed
            // them (`heldWas`).
            plannerVisits(heldNow, read.planner.stops, plannedAt,
                          !!(plannerPage && plannerPage.top === true), heldWas);
            // ...and its pickups searched for on the NucBox, for the
            // restaurant guard (searchHeldPickup); a no-op for one already
            // asked about on this hold.
            armHeldPickups(heldNow);
          }
          if (read.planner.keep === true) recordPlanner(read.planner, plannedAt);
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
        // The heartbeat itself, kept for /api/status. It goes to the panel
        // the way it always has — broadcast whole, below, which is how
        // tooBright and notSaving reach it and now the GPS and the Pi's
        // temperature and throttling too — and this is only the copy the raw
        // status link beside the connection dot can show afterwards. The page
        // does not seed itself from it: like tooBright, it waits for the next
        // beat, which is ALIVE_EVERY (four seconds) away at most.
        if (read.alive) {
          scanner.beat = read;
          // ...and the held pickups: one the car has stopped at and left is
          // visited, and off the run (visitPickups). Before the door, so the
          // state the beat carries below has it.
          visitPickups(read, Date.now());
          // ...and the GPS drop's one input: whether this beat's fix puts the
          // car at the held order's door, or takes it away (gpsArrival). The
          // answer rides the beat to the panel, which says "at dropoff".
          read.atDropoff = gpsArrival(read, Date.now());
          // ...and the rest of the GPS drop's state, on the same beat. Between
          // offers no reading arrives to carry heldForPanel, and that is when
          // the panel's in-car line is the card's whole message: a pin armed
          // or refused while the driver drives would otherwise reach the glass
          // at the next offer. Null with nothing held. See heldEndState.
          var heldBeat = holding(Date.now());
          read.heldEnd = heldBeat ? heldEndState(heldBeat) : null;
          // ...and every order's, with carrying two on (ordersForPanel).
          if (heldBeat && carryingTwo(Date.now())) read.orders = ordersForPanel(Date.now());
          // ...and the hold itself, heldForPanel's shape as a reading carries
          // it, on the first beat after what is held changed. An order put
          // down on its own clock (heldOrders, holdEnds) was said to no
          // panel: no press made it, and no reading comes between offers to
          // carry `holding` — so Drop and the in-car line stayed up over an
          // empty car until the next card. Only on a change, so a beat is
          // the size it was.
          var heldNowSig = heldOrders(Date.now()).map(holdIdOf).join(' ');
          if (heldNowSig !== beatHeldSaid) {
            beatHeldSaid = heldNowSig;
            read.holding = heldForPanel(heldBeat);
          }
        }
        broadcast(read);
      } catch (e) {
        console.error('server: a scanner line could not be handled: '
                      + (e && e.stack ? e.stack : String(e)));
      }
    });
  });

  // Kept, and not called an error. See `stderr` where `scanner` is built: a
  // running scanner's stderr is mostly libraries talking, and the one time it
  // explains anything is when it is the last thing said before an exit, which
  // the 'close' handler above is the one place that knows.
  scanner.proc.stderr.on('data', function (c) {
    var text = c.toString().trim();
    if (!text) return;
    console.error('scanner: ' + text);
    scanner.stderr = text.split('\n').slice(-3).join(' ');
    lastWords = scanner.stderr;
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

/* The files this side leaves requests in for the camera side: somebody is
 * watching and which view they want, read this box, read the destination, a
 * cost per mile, what the reader last read.
 * Files, because the scanner is sometimes a child of this process and
 * sometimes a systemd unit that has never heard of it.
 *
 * In RAM where there is any. All of them exist for seconds, none should survive
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
var DROPOFF_PATH = handoffPath('.dropoff');
var CROP_PATH = handoffPath('.cropbox.json');
var SETTINGS_PATH = handoffPath('.settings.json');
var SNAP_ASK_PATH = handoffPath('.snap.json');
var HOLDING_ASK_PATH = handoffPath('.holding.json');
/* One counter for every temporary this process publishes through a rename, so
 * no two of them can pick the same name. It was `cropSeq` and served the one
 * endpoint that had the rule applied; three other sites wrote a fixed
 * `<name>.part` and `rpi/test_lint.py` states the rule those three broke. */
var partSeq = 0;

function partName(base) {
  return base + '.' + process.pid + '.' + (partSeq++) + '.part';
}
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
  /* ...and a name of its own, for the same reason the three other renames in
   * this file now have one. This write is not request-driven, but it is called
   * from more than one place and up to thirty times a second, so two of them
   * interleaving into one fixed `.part` publishes a mixture — and what this
   * file holds is the name of the picture the driver is watching. A torn name
   * reads as "no view named, use the scene", which is the exact wrong answer
   * the rename above was added to prevent. */
  var tmp = partName(WATCH_PATH);
  fs.writeFile(tmp, want + '\n', function (err) {
    if (err) { fs.unlink(tmp, function () {}); return; }
    fs.rename(tmp, WATCH_PATH, function (renameErr) {
      if (renameErr) fs.unlink(tmp, function () {});
    });
  });
}

/* How long a card stays "the one in front of the driver", for the purpose of
 * attaching an address to it.
 *
 * The panel's own verdict goes stale at sixteen seconds of silence, and this is
 * deliberately far longer, because the two are answering different questions. A
 * verdict has to stop being trusted quickly: it is a number the driver acts on
 * and a stale one is a wrong one. Attaching an address is not that — it is a
 * note on a card that was definitely on the screen a moment ago, and the driver
 * has to leave this panel, tap the dropoff on their phone, wait for the map to
 * settle and come back. Sixteen seconds would not survive doing the thing the
 * button asks for.
 *
 * Two minutes, and it is a ceiling rather than a target: what it exists to
 * refuse is an address landing on a card from an hour ago, read while the
 * driver was pointing the camera at something else entirely. Inside two
 * minutes there is no other card it could plausibly belong to — the rig would
 * have read one and replaced the slot.
 *
 * Overridable for the same reason HOLD_GRACE_MS is: a check that has to wait
 * out two minutes of real clock to prove the ceiling exists is a check nobody
 * runs, and a ceiling nothing proves is a ceiling that quietly stops being
 * one. */
var SCREENING_MS = Number(process.env.SCREENING_MS);
if (!isFinite(SCREENING_MS) || SCREENING_MS < 0) SCREENING_MS = 120000;

/* The card being screened, or null — the offer on the slot, while it is still
 * recent enough for an address read now to belong to it.
 *
 * Asked as a function for the same reason holding() is: `scanner.offer` is the
 * raw slot and holds the last card read whenever that was, which on a rig left
 * running overnight is a card from yesterday. */
function screeningCard(now) {
  var o = scanner.offer;
  if (!o || typeof o.id !== 'string' || !o.id) return null;
  if (!scanner.offerAt) return null;
  return (now - scanner.offerAt) <= SCREENING_MS ? o : null;
}

/* How long after its card was last read a CUSTOMER'S place popup may still be
 * about it. A store's popup names its store and is matched to the card's
 * pickup (Assemble.popup); a customer's names nobody, so the only witness is
 * that the card was on the screen around the tap. Sixteen seconds is the
 * panel's own figure for that question — live.html's READ_STALE_MS, past which
 * it stops treating the verdict as the card in front of the driver — and
 * rpi/test_lint.py holds the two equal. Measured on the five store popups on
 * file: read 2.1, 2.8, 3.9, 4.4 and 28.5 s after their card's last row; the
 * last would be refused for a customer, and is filed for a store by its
 * name. */
var POPUP_CARD_MS = 16000;

/* DoorDash's place popup, arrived from the scanner: Assemble.popup decides,
 * and this files, writes and says. A store's door goes onto the card as
 * `pickupAddr`, which Map view searches and ✓ Took carries into the hold; a
 * customer's becomes the card's end, written to the journal as a screening
 * sighting's end is, with `labelled` (the popup's own role label is what lets
 * it past the card's own end in the marks fold, as it was let past it here)
 * and `from: 'popup'`, which nothing folds on and is there to say where it came
 * from. No address in the log: the role and the reason. The card goes back to
 * every panel at once with what it now holds — the card is under the popup,
 * so the reading that would have carried it is not coming. */
function popupArrived(p, now) {
  var card = screeningCard(now);
  var said = Assemble.popup(card, p, { held: heldOrders(now), offerAt: scanner.offerAt,
                                       seenAt: scanner.offerSeenAt, cardMs: POPUP_CARD_MS });
  var whose = p && p.role === 'pickup' ? "store's" : "customer's";
  if (said.to !== 'card') {
    console.log('place popup: the ' + whose + ' address not filed: ' + said.why);
    return;
  }
  Assemble.filePopup(card, p, said);
  console.log('place popup: the ' + whose + ' address filed on the card being screened');
  if (said.field === 'dropoff') {
    appendLines(JSON.stringify({
      v: 1, kind: 'mark', at: Date.now(), id: card.id, dropoff: p.line,
      asked: false, labelled: true, from: 'popup'
    }) + '\n', function (err) {
      if (err) console.error('journal: could not record a popup dropoff: ' + err.message);
    });
  }
  broadcast({ offer: card, popup: { role: p.role, field: said.field, line: p.line } });
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

/* The order in the car, kept where a power cut cannot take it.
 *
 * `scanner.held` is process memory, and this is "a box velcroed into a car
 * where the ignition is the power switch" — rpi/calibrate.py's own words. A
 * driver who presses Took, drives to the restaurant, switches the engine off
 * and walks in comes back to a rig with no order in the car: the stack line
 * goes quiet, Drop and the dropoff scan disappear, and every card for the rest
 * of that delivery is judged standalone, with nothing on the glass saying why.
 * On the owner's week 58% of accepted jobs have a `go`-rated offer arrive while
 * they are still running, so that is a real decision made without the figure it
 * was built for.
 *
 * THE COMMENT AT /api/delivered ARGUED THE OPPOSITE and it is answered rather
 * than ignored. It said the hold "is memory only, and a restarted server simply
 * has no order in hand, which is the safe way to be wrong" — in the present
 * tense, after this file had stopped doing it, and rpi/README.md said the
 * same; both now describe this file instead. Both halves are right about the
 * ERRORS — forgetting an order that is there costs advice,
 * remembering one that is not puts a pair rate on the glass for a job already
 * delivered, and the second is worse. What does not follow is that keeping it
 * causes the second: `holding()` expires an order on its own stated time plus
 * HOLD_OVERRUN plus HOLD_GRACE_MS, and a restored one is read through exactly
 * that. A hold that has outlived its own clock is refused whether it came from
 * memory or from disk.
 *
 * Its own file, not the journal. The journal is the one artefact that cannot be
 * regenerated and its ingest is idempotent over the whole file; this is a
 * scrap of state about right now. Same reasoning, and the same shape, as
 * places.json beside it.
 *
 * Written synchronously, and that is deliberate on a box whose power can go at
 * any moment: the whole point is to survive the instant between the press and
 * the engine stopping, and a queued write does not. It is one small object,
 * once per accept.
 */
function holdPath() {
  return path.join(path.dirname(JOURNAL_PATH), 'holding.json');
}

/* The fields of an offer line that say where the car was when the card came
 * up and how far the card says the job runs — the gate's answer included.
 *
 * Kept with the order in the car, because Map view checks the held order's end
 * against its OWN card: a straight line from where that card came up to where
 * the map put its end cannot be longer than the distance it printed (plus
 * MapView.SLACK_MI), and where it is, the map found the wrong end. The order
 * carried `miles` and nothing else, so its end was a pin with nothing to
 * contradict it. Copied, never judged here: map-view.js decides what each
 * field allows (MapView.cardFix, MapView.cardYardstick). */
var CARD_FIELDS = ['lat', 'lon', 'gpsAge', 'gpsErr', 'gpsMode', 'gpsOk', 'gpsWhy',
                   'miles', 'whole', 'hasTotal', 'legs', 'milesUncertain',
                   'milesCorrected', 'earlyLook', 'doubt', 'multiOrder'];

function cardOf(offer) {
  var out = {};
  CARD_FIELDS.forEach(function (k) {
    if (offer && offer[k] !== undefined) out[k] = offer[k];
  });
  return out;
}

/* ---------- the orders in the car: a list ----------------------------------
 *
 * Stage 4 of the multi-order design. The hold was one slot; it is now a list,
 * first-taken first, capped at MAX_HELD — maxHeld(), ONE unless carrying two is
 * on (Stage 5, carryTwo below), so with the flag off every answer this file
 * gives is the one it gave with the slot. What changed is only the
 * shape: holding.json is `{v: 2, orders: [Hold]}`, `.holding.json` names
 * every order (`holds: [ids]`) and is in force until the LATEST of their ends,
 * and the live part of each GPS arrival is kept per hold (`arrivals`).
 *
 * A Hold is the object the slot held, plus:
 *   holdId    its name on the wire (holdIdOf): `<id>@<acceptedAt>`
 *   app       'uber' | 'doordash' | null, off the offer line
 *   tookAt    when ✓ Took was pressed, which is not acceptedAt (the card's
 *             own time: see the mark handler)
 *   deliverBy the card's "Deliver by", minutes since midnight, or null
 *   addOn     whether the card was Uber's offer to add to a trip in progress
 *             (isAddOnCard: the parser's `addon`, or the screen `uber.addon`)
 *   of        for an add-on taken onto a trip, the holdId of that trip's ROOT
 *             order (tripOf); else null — an add-on with no Uber order held
 *   ofEnds    for an add-on, when that trip ended as it stood at the Took
 *             (the holdEnds of its order taken last, which is the latest of
 *             its orders'), which the add-on outlives: see holdEnds
 *
 * Read through heldOrders(now) and holding(now), never off `scanner.held`:
 * those are the questions "which orders are being carried RIGHT NOW", and an
 * order past its own clock is not one. rpi/test_lint.py holds that nothing
 * reads the slot's old name. */
function maxHeld() {
  return carryTwo() ? 2 : 1;
}

/* ---------- a trip: an order and the Uber add-ons joined to it ---------------
 *
 * The owner's decision of 17 Oct 2026, after the 16 Oct shift: twice the
 * driver ticked an Uber add-on ("+ $9.50 / +8 min (+1.3 mi) total") with an
 * order in the car, and with carrying two off the Took REPLACED that order —
 * a drop row `by: 'replaced'` for the first, whose Trip Planner door was on
 * record, and a hold that knew only the add-on: no end, and its own "+8 min"
 * clock, run out 21 minutes later. Every offer for the next half hour was
 * weighed against the wrong order. Uber paid each original and its add-on as
 * ONE trip ($25.03 + $9.50 card, one $43.42 trip; $22.46 + $9.64, one $36.53),
 * and the owner's trip details for the first show a second add-on on the same
 * trip ($25.03 + $9.50 + $6.89 = $41.42 expected), accepted on the phone with
 * no Took on the rig. An add-on is always joined to the trip in progress, so
 * holding it beside that trip is never a guess.
 *
 * So the list's unit for every CAP is the trip, not the order. A trip is an
 * order and every add-on whose `of` names it (tripOf): an add-on is joined to
 * the ROOT of the trip it was taken onto, so a chain of two add-ons is one
 * trip of three, and stays one trip when the root is put down. maxHeld() is
 * how many trips — one with carrying two off, two with it on — so with no
 * add-on held every answer here is the one it was.
 *
 * And while a trip of two or more is held, the carry-two machinery is in force
 * whatever `carryTwo` says (carryingTwo): an address is filed onto one of its
 * orders on a positive cue or the driver's pick from the chooser, and
 * otherwise nowhere (AUDITS.md, Settled: no cue means no filing, and the
 * chooser never times out into a guess). With carrying two off and no trip
 * joined, nothing changes: a Took on anything but an add-on replaces the order
 * in the car as it always did. */
function isAddOnCard(o) {
  return !!o && (o.addon === true || o.screen === 'uber.addon');
}

// The trip an order is part of, by the holdId of its root: an add-on's `of`,
// else its own name.
function tripOf(h) {
  return h && h.addOn && typeof h.of === 'string' && h.of ? h.of : holdIdOf(h);
}

// The trips among `list`, first-taken first, by tripOf.
function tripsIn(list) {
  var keys = [];
  (list || []).forEach(function (h) {
    var k = tripOf(h);
    if (keys.indexOf(k) === -1) keys.push(k);
  });
  return keys;
}

// Whether two of `list` are one trip: an add-on held with its trip.
function tripJoined(list) {
  return tripsIn(list).length < (list || []).length;
}

/* Whether the carry-two machinery is in force: carrying two is on, or a trip
 * of two or more is in the car (see above). Asked where `carryTwo()` was asked
 * by every path that files, draws or weighs more than one order. */
function carryingTwo(now) {
  return carryTwo() || tripJoined(heldOrders(now));
}

// When the trip `key` ends: the latest of its orders' holdEnds in `list`, or
// null when none of them states a time.
function tripEnds(list, key) {
  var ends = null;
  (list || []).forEach(function (h) {
    if (tripOf(h) !== key) return;
    var e = holdEnds(h);
    if (e !== null && (ends === null || e > ends)) ends = e;
  });
  return ends;
}

/* The order an add-on card is taken onto: the Uber order in the car taken
 * last, add-on or not — its trip is the trip in progress — or null with no
 * Uber order held (nothing held, or only another app's), when the add-on is
 * held as an order of its own on its own clock. */
function addOnBase(inCar) {
  return (inCar || []).filter(function (o) { return o.app === 'uber'; }).pop() || null;
}

/* ---------- carrying two orders: the flag ------------------------------------
 *
 * Stage 5. The driver asked to carry two orders, and AUDITS.md's Settled had
 * refused it (plan 3.1) for one reason: with two in the car, the ⌖ press for
 * the second attached to the first, in an append-only file. The owner's
 * decision overrides that entry with a safeguard in place of the refused
 * rival-card guard: with two held, an address is filed only on a positive cue
 * (Assemble.attribute) or when the driver picks it from a chooser, and is
 * otherwise filed nowhere.
 *
 * Behind `"carryTwo": true` in rpi/config.json's `settings`, false unless it
 * says exactly true. Read where it is asked, not at boot: the scanner rewrites
 * that file whole and keeps keys it does not know, and a restart mid-shift is
 * an aim-and-calibrate cycle. CARRY_TWO=1 or 0 in the environment overrides
 * it, for the suites. With it off, MAX_HELD is one and the server does what
 * Stage 4 did — a second Took replaces — and only says, in a `would` field on
 * rows it already writes, what attribution would have done. */
/* ...and read again only when the file has changed (its mtime, size and
 * inode), not on every call: it is asked on every beat, reading and planner
 * line, and a shift's worth of those read and parsed the file 16,599 times
 * (measured at f80d0c2 over a simulated shift of 5,000 beats, two orders held;
 * once, with this). A stat is all an unchanged file costs now. The scanner
 * replaces the file through a rename, which a new inode says even inside one
 * mtime tick. */
var carryTwoSeen = null;

function carryTwo() {
  var env = process.env.CARRY_TWO;
  if (env === '1') return true;
  if (env === '0') return false;
  var file = path.join(ROOT, 'rpi', 'config.json');
  var st;
  try { st = fs.statSync(file); } catch (e) { carryTwoSeen = null; return false; }
  var c = carryTwoSeen;
  if (c && c.mtime === st.mtimeMs && c.size === st.size && c.ino === st.ino) return c.on;
  var on = false;
  try {
    var cfg = JSON.parse(fs.readFileSync(file, 'utf8'));
    on = !!(cfg && cfg.settings && cfg.settings.carryTwo === true);
  } catch (e) {
    on = false;
  }
  carryTwoSeen = { mtime: st.mtimeMs, size: st.size, ino: st.ino, on: on };
  return on;
}

/* The orders in the car as the assembler is handed them: the first-taken
 * alone — exactly what it had before the list — unless carrying two is in
 * force (carryingTwo: on, or an add-on held with its trip) and two or more
 * are held, when it is the list. */
function assemblerHeld(now) {
  var list = heldOrders(now);
  return carryingTwo(now) && list.length >= 2 ? list : (list[0] || null);
}

/* The name a hold goes by on the wire: the card's id and when it was on the
 * screen. The panel has no other handle on "the order in the car", and a pin
 * posted for one hold must never land on the next (see /api/held-end). Kept on
 * the hold as `holdId` since the list, made the same way. */
function holdIdOf(h) {
  if (!h) return null;
  return typeof h.holdId === 'string' && h.holdId
    ? h.holdId : String(h.id) + '@' + String(h.acceptedAt);
}

/* The hold as it is written: the slot's object, its new fields filled in where
 * it came from a file or a caller older than them. Changes nothing a reader of
 * the old fields sees. */
function asHold(h) {
  if (!h.holdId) h.holdId = String(h.id) + '@' + String(h.acceptedAt);
  if (h.app === undefined) h.app = null;
  if (h.tookAt === undefined) {
    h.tookAt = h.seenAs && typeof h.seenAs.tookAt === 'number' ? h.seenAs.tookAt : h.acceptedAt;
  }
  if (h.deliverBy === undefined) h.deliverBy = null;
  if (h.addOn === undefined) h.addOn = false;
  if (h.of === undefined) h.of = null;
  if (h.ofEnds === undefined) h.ofEnds = null;
  return h;
}

/* The whole list, written: memory, holding.json, the scanner's handoff, and
 * the per-hold searches. ONE function for every change — a Took, a Drop, a pin
 * kept on one order — so the copies cannot disagree. */
function setHeld(list) {
  scanner.held = (list || []).filter(Boolean);
  var tmp = null;
  try {
    if (scanner.held.length) {
      // Through a temporary and a rename, like every other file this process
      // publishes. Written in place, a power cut mid-write — this box's
      // ordinary way of stopping — left a file cut short, and loadHolding
      // read that as nothing held: the order in the car gone at the next boot
      // with no word said. A rename is all or nothing. No fsync, as the
      // journal's own appends take none (appendLines).
      tmp = partName(holdPath());
      fs.writeFileSync(tmp, JSON.stringify({ v: 2, orders: scanner.held }));
      fs.renameSync(tmp, holdPath());
    } else {
      fs.unlinkSync(holdPath());
    }
  } catch (e) {
    // A hold that could not be written is a hold that will not survive a
    // reboot, which is where this started — said once rather than swallowed,
    // and never fatal: the panel works from memory either way and the driver
    // is mid-shift.
    if (e && e.code !== 'ENOENT') console.error('holding: ' + e.message);
    if (tmp) { try { fs.unlinkSync(tmp); } catch (e2) { /* never written */ } }
  }
  tellScannerHeld(scanner.held);
  forgetHoldsGone(scanner.held);
  scanner.held.forEach(function (h) {
    armHeldEnd(h);
    armHeldPickups(h);
  });
}

/* One order changed in place — a pin, an arrival, a refusal — written with
 * the rest. A no-op for an order no longer on the list. */
function saveHold(h) {
  if (scanner.held.indexOf(h) === -1) return;
  setHeld(scanner.held);
}

/* Until when an order is in the car, for the scanner, which cannot ask.
 *
 * The scanner reads Uber's Trip Planner and navigation screens on its own
 * while an order is held — see `screen_auto` in rpi/scan_pi.py — and "is an
 * order held" is this process's question, answered by holding(). The scanner
 * is sometimes this process's child and sometimes a systemd unit that has
 * never heard of it, so it is told the way every other request is: a handoff
 * file. What goes in it is the moment holding() itself stops answering yes —
 * the LATEST of the orders' holdEnds, the one expression of that — so the
 * scanner needs no word from here when the orders run out, and a server that
 * died mid-delivery leaves a file that goes stale on its own clock rather than
 * one that says "held" for ever.
 *
 * Through a rename, like every other file this process publishes, so the
 * scanner never reads half of one. Gone when nothing is held. */
function tellScannerHeld(list) {
  var ends = null;
  var ids = [];
  (list || []).forEach(function (h) {
    var e = holdEnds(h);
    if (e === null) return;
    ids.push(holdIdOf(h));
    if (ends === null || e > ends) ends = e;
  });
  try {
    if (ends === null) {
      fs.unlinkSync(HOLDING_ASK_PATH);
      return;
    }
    var tmp = partName(HOLDING_ASK_PATH);
    // ...and WHICH orders, as holdIdOf names them: the scanner forgets the
    // last address it volunteered when this changes (`dropoff_said` in
    // rpi/scan_pi.py), so one refused for the order before — a screen read
    // before the Took — is offered again for this one.
    fs.writeFileSync(tmp, JSON.stringify({ until: ends, holds: ids }));
    fs.renameSync(tmp, HOLDING_ASK_PATH);
  } catch (e) {
    // Said, not thrown: the cost of a lost one is the automatic planner read
    // and nothing else — ⌖ reads the planner exactly as before.
    if (e && e.code !== 'ENOENT') console.error('holding handoff: ' + e.message);
  }
}

/* One order off the file, or null: a stamp that is a number and not after the
 * clock reading it. */
function heldFromFile(h) {
  if (!h || typeof h !== 'object' || typeof h.acceptedAt !== 'number'
      || !isFinite(h.acceptedAt)) return null;
  if (h.acceptedAt > Date.now()) return null;
  return asHold(h);
}

// The most TRIPS a file is read with (tripsIn: an order and its add-ons are
// one), whatever MAX_HELD is now: a file holding more is cut to this many,
// first-taken first. Not MAX_HELD itself, so a restart does not throw away an
// order already in the car — a Took is where the cap applies, and it is said
// there. By trips, so a trip of three restored at boot comes back whole.
var MAX_HELD_FILE = 2;

function firstTrips(list, n) {
  var keep = tripsIn(list).slice(0, n);
  return list.filter(function (h) { return keep.indexOf(tripOf(h)) !== -1; });
}

/* ...and read back once, at startup, which is the only moment it means
 * anything.
 *
 * BOTH DIRECTIONS on the clock, for the same reason journal.py's resume() does
 * it: a Pi has no real-time clock, it boots in 1970 and jumps when the network
 * arrives. A hold stamped after the clock now reading it makes `over` in
 * holding() permanently negative, so the order would never expire and the
 * panel would offer a pair line against it for the rest of the shift.
 * Refusing is always available and costs one delivery's advice.
 *
 * TWO SHAPES. `{v: 2, orders: [...]}` is this file's; an object with no `v`
 * is the one-slot file every build before the list wrote, and is WRAPPED as
 * one order, its clock untouched (asHold names it as it was named). The other
 * way round is safe by construction: a v2 file has no `acceptedAt` of its own,
 * so a build from before the list — which asks for exactly that — holds
 * nothing, rather than a list read as one order. A `v` this build does not
 * know is nothing either. Returns the first-taken order still carried, or
 * null, for the boot line. */
function loadHolding() {
  var raw;
  try { raw = fs.readFileSync(holdPath(), 'utf8'); } catch (e) { return null; }
  var f;
  try {
    f = JSON.parse(raw);
  } catch (e) {
    f = null;
    // A file that does not parse — cut short by a power cut when it was
    // written in place, or damaged since — was read as nothing held and said
    // nothing: the order in the car gone at boot, the stack line judging the
    // next card alone, and no line anywhere. Measured at f80d0c2 with the
    // file's last nine bytes cut off: /api/status `holding: null`, and not a
    // word in the log. Said now, and the file kept aside rather than
    // overwritten by the next Took, so what it held can still be read.
    var aside = holdPath() + '.bad';
    var kept = true;
    try { fs.renameSync(holdPath(), aside); } catch (e2) { kept = false; }
    console.error('holding: ' + holdPath() + ' could not be read (' + e.message
                  + '), so no order in the car is restored'
                  + (kept ? '; it is kept as ' + aside : ''));
  }
  var list = [];
  if (f && typeof f === 'object' && f.v === 2 && Array.isArray(f.orders)) {
    list = f.orders.map(heldFromFile).filter(Boolean);
  } else if (f && typeof f === 'object' && f.v === undefined) {
    var one = heldFromFile(f);
    if (one) list = [one];
  }
  scanner.held = firstTrips(list, MAX_HELD_FILE);
  // Through heldOrders(), so an order that has outlived its own clock is put
  // down here rather than waiting to be noticed — and so the answer to "is
  // there an order in the car" is the same function at boot as it is
  // everywhere else.
  var still = heldOrders(Date.now());
  // ...and the scanner told, since a hold restored at boot is a hold.
  if (still.length) tellScannerHeld(still);
  still.forEach(function (h) {
    armHeldEnd(h);
    armHeldPickups(h);
  });
  return still.length ? still[0] : null;
}

/* The moment a hold stops being an order in the car: its stated time, half
 * again, and the grace — or null for a hold with no stated time, which
 * holding() never counts as carried. One expression, for holding() and for the
 * scanner's handoff (tellScannerHeld), so the two cannot disagree about when an
 * order ends. */
function holdEnds(h) {
  var stated = (typeof h.minutes === 'number' && isFinite(h.minutes) && h.minutes > 0)
    ? h.minutes : null;
  if (stated === null) return null;
  var own = h.acceptedAt + stated * HOLD_OVERRUN * 60000 + HOLD_GRACE_MS;
  // An add-on (Uber's "+ $", "+N min" card, taken onto a trip in progress) is
  // done no sooner than the trip it joins, and then its own added minutes,
  // half again: the later of that and its own clock. Its card's minutes are
  // the minutes it ADDS, so its own clock alone ends it before the trip — on
  // 16 Oct the "+8 min" add-on's hold ran out 21 minutes after its Took.
  // `ofEnds` is the whole trip's end at the Took (placeTook), so a second
  // add-on outlives the first. The trip's stated minutes and the clock, and
  // nothing worked out from a distance. Frozen at the Took: the root put down
  // early (Drop, the GPS) leaves the add-on held to that end all the same,
  // until its own Drop — an end the rig cannot see coming is not a reason to
  // forget an order the driver still carries.
  if (h.addOn && typeof h.ofEnds === 'number' && isFinite(h.ofEnds)) {
    return Math.max(own, h.ofEnds + stated * HOLD_OVERRUN * 60000);
  }
  return own;
}

/* One sighting, counted by its screen type (rpi/scan_pi.py's emit_sighting;
 * the types are offer_parser.SCREENS). A run tally on the scanner's health
 * block of /api/status, `screens`, kept like `fell` and `wedged` for the life
 * of this process: how many of each screen the rig has seen since the server
 * started is the question, and a count that reset with each scanner restart
 * would answer a different one. Nothing else is read off the line — not its
 * stops, not its address, not its app — and nothing is stored. A type that is
 * not a short word is counted as 'unknown', never dropped, so a malformed
 * line still shows as a sighting. */
function countSighting(s) {
  var type = s && typeof s.screen === 'string' && /^[A-Za-z.]{1,40}$/.test(s.screen)
    ? s.screen : 'unknown';
  scanner.screens[type] = (scanner.screens[type] || 0) + 1;
}

/* The orders being carried right now, first-taken first. One past its own
 * clock is put down here (written, and the scanner told, and a drop row
 * journaled: see expiredRows); one with no stated time is kept on the list and
 * never counted, as the slot kept it.
 *
 * Asked on every beat, so the filter is all an ordinary call pays: the write
 * below runs only on the call that finds an order gone, and that call is once
 * per order, because the same call takes the order off the list. */
function heldOrders(now) {
  var gone = scanner.held.filter(function (h) {
    var ends = holdEnds(h);
    return ends !== null && now > ends;
  });
  if (gone.length) {
    setHeld(scanner.held.filter(function (h) { return gone.indexOf(h) === -1; }));
    expiredRows(gone);
  }
  return scanner.held.filter(function (h) { return holdEnds(h) !== null; });
}

/* A journal row about an order in the car — a Took's mark, a drop of any
 * kind — saying so when that order is an Uber add-on: `addon: true`, and
 * `addonTo`, the holdId of the trip's root it was taken onto (tripOf), when
 * there was one. Ids only: the root's own row says the rest. Nothing is added
 * for an ordinary order, so its rows are the shape they always were, and a
 * reader of the journal can tell an add-on's drop from a replaced order's. */
function asAddOnRow(row, h) {
  if (h && h.addOn) {
    row.addon = true;
    if (typeof h.of === 'string' && h.of) row.addonTo = h.of;
  }
  return row;
}

/* A drop row for each order put down by its own clock, `by: 'expiry'`.
 *
 * Before this an expiry wrote nothing, so the shift report (tools/) read an
 * order that ran out exactly as it read one the server lost — "no end" — and
 * the two are different faults. The row is DATED AT holdEnds, the moment the
 * server stopped counting the order, not at the call that noticed: that call
 * is the next beat or request, and after a restart it is the boot, possibly
 * hours later. `seq` is the same moment, so the sync keys one expiry as one
 * row.
 *
 * ONCE PER ORDER, including across a restart, because of the order of the two
 * writes: the list (holding.json) is rewritten first, synchronously, by
 * setHeld in heldOrders, and the row is appended after. An order found
 * already expired at boot is still on the file, so loadHolding's heldOrders
 * finds it gone and this writes its row then; the file it rewrites no longer
 * names it, so the next boot does not write it again. The writes the other way
 * round would write the row twice after a power cut between them; this way
 * round loses it in that window instead, which is the cost appendLines already
 * names for a power cut, and an append that fails is said like any other.
 *
 * `acceptedAt` as the other drop rows carry it. Its `at - acceptedAt` is the
 * card's own minutes, half again, plus the grace — the card again, not a
 * measurement — and the shift report says so rather than timing it. */
function expiredRows(gone) {
  var rows = gone.map(function (h) {
    var ends = holdEnds(h);
    return JSON.stringify(asAddOnRow({ v: 1, kind: 'drop', at: ends, id: h.id, seq: ends,
                                       acceptedAt: h.acceptedAt, by: 'expiry' }, h)) + '\n';
  });
  appendLines(rows.join(''), function (err) {
    if (err) console.error('journal: could not record an expiry: ' + err.message);
  });
}

/* The first-taken order being carried, or null: what every one-order answer
 * on this server is about — the stack line, the pair row's `held`, the panel's
 * in-car line. */
function holding(now) {
  var list = heldOrders(now);
  return list.length ? list[0] : null;
}

/* The order named `id` (holdIdOf) among those carried now, or null. */
function heldById(id, now) {
  var list = heldOrders(now);
  for (var i = 0; i < list.length; i++) if (holdIdOf(list[i]) === id) return list[i];
  return null;
}

/* ---------- two orders in the car: whose address, and the chooser -----------
 *
 * Stage 5, with carrying two on (carryTwo). The safeguard the owner put in
 * place of AUDITS.md's refused rival-card guard: with two orders held, an
 * address read off the screen is filed onto one of them only when a POSITIVE
 * cue says which (Assemble.attribute: the app, the Took, the store, the
 * deadline, the list growing, elimination on a list seen whole). With none:
 *
 *   - a ⌖ press opens the CHOOSER on the panel — a sheet over the verdict pane,
 *     not a control on the bar — and nothing is filed unless the driver picks
 *     a row. It closes after CHOOSER_MS (10 s) with nothing filed;
 *   - an unprompted sighting waits in the assembler's pool (Assemble.park),
 *     unwritten, and the panel says how many are waiting ("2 dropoffs read ·
 *     whose?"), until a later read gives it a cue (retryPool) or one of the
 *     two orders leaves the car and it is dropped. One the hard rules leave
 *     to no order (`nobody`) is not parked: no later cue can give it one.
 *
 * With carrying two off, nothing here changes what is filed between ORDERS:
 * whoseDropoff only works out what attribution WOULD have said, over the order
 * in the car and the one a Took last replaced while its clock still runs
 * (`shadows`), and that goes on the mark or tally row this already writes, as
 * `would`. What it does change, on and off alike, is a ⌖ press with one order
 * in the car and another card being screened: the order against the card,
 * by a cue or the chooser (pressBetween). */
var CHOOSER_MS = envNumber('CHOOSER_MS', 10000);
var choosing = null;
var chooseSeq = 0;
// The orders a Took replaced with carrying two off, while their own clock
// runs: memory only, for `would` and nothing else.
var shadows = [];

function shadowsNow(now) {
  shadows = shadows.filter(function (h) {
    var e = holdEnds(h);
    return e !== null && now <= e;
  });
  return shadows;
}

/* {stop, order, cue, would, store} for one address arriving — `store` when it
 * is a press off Uber's navigation to a store, which nobody is given — and
 * `order` undefined to leave dropoffArrived's own choice (the first-taken)
 * alone, an order to file onto that one, or null for none — and so the card being screened, where
 * Assemble.dropoff gives it one; `stop` when nothing is to be filed at all.
 * `force` is a decision already made — the chooser's row, or the pool's cue —
 * and is taken as it is. */
function whoseDropoff(read, force, now) {
  var d = read.dropoff;
  var out = { stop: false, order: undefined, cue: null, would: null };
  if (force) {
    out.order = force.order || null;
    out.cue = force.cue || null;
    return out;
  }
  if (!d || typeof d.line !== 'string') return out;
  // A PRESS over Uber's navigation to a store (uber.pickupNav) is nobody's
  // dropoff (Assemble.dropoff, rule 5; the owner, 17 Oct): not the order's in
  // the car, not the card's being screened. So no cue is looked for and no
  // chooser opened over it — it opened when a card was on the slot, and
  // "This card" filed the store's address onto the card — and it goes on to
  // Assemble.dropoff, which refuses it for whoever it would have gone to, and
  // the panel is told at once (dropoffArrived). `store` says so there.
  if (d.asked !== false && Assemble.storeScreen(null, d)) {
    out.store = true;
    return out;
  }
  var orders = heldOrders(now);
  if (!carryingTwo(now)) {
    if (!orders.length) return out;
    var w = Assemble.attribute(assembly, shadowsNow(now).concat(orders), d);
    out.would = { cue: w.cue, held: w.order ? holdIdOf(w.order) : null };
    // ...and a press with a card being screened: the order in the car, the
    // first-taken, against that card (pressBetween).
    return pressBetween(out, d, orders[0], now);
  }
  if (orders.length < 2) {
    if (orders.length) {
      out.cue = 'only';
      return pressBetween(out, d, orders[0], now);
    }
    return out;
  }
  // Two orders and a press while a card is being screened that it could
  // belong to (Assemble.cardCandidate): the card's on the card's own place
  // popup, as pressBetween has it with one order; and otherwise no order is
  // given it by the hard rules alone — `only` — but on a cue that names it,
  // or the chooser asks: ①, ②, This card, Neither.
  var screened = d.asked !== false
    && Assemble.cardCandidate(orders, screeningCard(now), d);
  if (screened && Assemble.ownPopup(screeningCard(now), d)) {
    out.order = null;
    out.cue = 'popup';
    return out;
  }
  var a = Assemble.attribute(assembly, orders, d, screened ? { card: true } : null);
  if (a.order) {
    out.order = a.order;
    out.cue = a.cue;
    return out;
  }
  out.stop = true;
  if (d.asked !== false) {
    console.log('dropoff read with two orders in the car, ' + a.why + ': the chooser is open');
    openChooser('scan', d, orders, now);
  } else if (a.why === 'nobody') {
    // ...not one an order in the car can own at all: another app's screen, or
    // a read from before both Tooks. The pool is for an address a LATER cue
    // may decide, and no cue moves the hard rules — retryUnowned asks the
    // same two orders the same question — so parked it said "1 dropoff read ·
    // whose?" until one of them left the car. Measured at f80d0c2: two
    // DoorDash orders held, an Uber navigation screen read unprompted, and
    // `unowned: 1` on /api/status for as long as both were carried.
    console.log('dropoff seen with two orders in the car, nobody\'s: not kept');
  } else {
    console.log('dropoff seen with two orders in the car, ' + a.why + ': waiting for a cue');
    Assemble.park(assembly, d, orders);
    broadcast({ unowned: Assemble.unowned(assembly) });
  }
  // ...and a cue that fitted both may yet be broken on the map.
  if (a.why === 'tie') discBreak(d, orders, a.ties[0]);
  return out;
}

/* A ⌖ press with ONE order in the car and another card being screened
 * (screeningCard): whose it is, the order's or the card's, is decided on a cue
 * the screen gave (Assemble.pressBetween) — the card's own place popup, or
 * the order's navigation or Trip Planner read since its Took — and otherwise
 * by the driver, from the chooser: rows ①, "this card" and Neither, filing
 * nothing unless one is picked, closing after CHOOSER_MS, a late answer
 * refused. With carrying two off as well as on. AUDITS.md's Open entry on
 * the ⌖ button while an order is in the car: measured at b337a44 against
 * this server, a press here replaced the held order's end whatever the
 * screen showed. `out` is whoseDropoff's, given back with the decision on it:
 * `order` null for the card (dropoffArrived then files it there, as a
 * screening press), the order for the order, or `stop` with the chooser
 * open. Nothing changes for a sighting, with no card, or over the order's own
 * card. */
function pressBetween(out, d, held, now) {
  var said = Assemble.pressBetween(held, screeningCard(now), d);
  if (!said) return out;
  if (said.to === 'card') {
    out.order = null;
    out.cue = said.cue;
  } else if (said.to === 'hold') {
    out.order = held;
    out.cue = said.cue;
  } else {
    out.stop = true;
    console.log('dropoff read with an order in the car and a card on the slot, '
                + said.why + ': the chooser is open');
    openChooser('scan', d, [held], now);
  }
  return out;
}

/* The tie-break, and only that (Assemble.attribute): a cue fitted both orders
 * and none fitted one. The address is searched on the NucBox inside each
 * order's card disc, by the rule the held end is pinned by (searchPlan's
 * street, pickInDisc, a door — hasDoor); found at door level inside EXACTLY
 * ONE of them, it is that order's, filed under the cue that tied, and the
 * chooser it was waiting in closes — or it leaves the pool. Found in both,
 * in neither, no NucBox, no door: nothing changes, and the driver's chooser
 * or the pool stand as they were. The public geocoder is never asked. */
function discBreak(d, orders, cue) {
  if (!NBX.search) return;
  var plan = MV.searchPlan(d.line);
  if (!plan || plan.kind !== 'street' || !plan.door) return;
  var term = nbxTerm(plan.street);
  if (!term) return;
  var inside = [];
  var left = orders.length;
  var one = function () {
    left -= 1;
    if (left > 0 || inside.length !== 1) return;
    var o = heldById(holdIdOf(inside[0]), Date.now());
    if (!o) return;
    if (choosing && choosing.d === d) {
      choosing = null;
      broadcast({ chooser: null });
    } else if (!Assemble.unpark(assembly, d.line)) {
      return;
    }
    console.log('dropoff found inside one card\'s reach only: filed by ' + cue);
    var said = { dropoff: d, at: Date.now() };
    dropoffArrived(said, { order: o, cue: cue });
    if (said.dropoff) broadcast(said);
    broadcast({ unowned: Assemble.unowned(assembly) });
  };
  orders.forEach(function (o) {
    var disc = MV.discFor(o.card || null);
    if (!disc) return one();
    var target = nbxSearchTarget('street', term, MV.discBox(disc));
    var take = function (out) {
      var res = MV.pickInDisc(out.hits, disc, plan, out.cutAt);
      if (res.at && MV.hasDoor(res.at, plan.house)) inside.push(o);
      one();
    };
    if (nbxCache.has(target)) return take(nbxCache.get(target));
    nbxAsk(target, function (err, body) {
      if (err || !Array.isArray(body)) return one();
      var out = nbxHits(body);
      nbxRemember(target, out);
      take(out);
    });
  });
}

/* The chooser, opened over the ⌖ press it answers: a row for each order in
 * the car, and — while a card is being screened (screeningCard) that is not
 * one of them — that card as a row of its own, since the press may have been
 * about it. "Neither" is the panel's own row. One at a time: a second press
 * replaces the first's. Said to every panel on the stream. */
function openChooser(kind, d, orders, now) {
  var card = screeningCard(now);
  choosing = { id: 'choose-' + now + '-' + (++chooseSeq), kind: kind, d: d,
               among: orders.map(holdIdOf),
               // ...not a card that IS one of the orders in the car: the
               // last Took's own card is usually still the one on the slot.
               card: card && !card.heldCard
                 && !orders.some(function (o) { return o.id === card.id; }) ? card.id : null,
               until: now + CHOOSER_MS };
  broadcast({ chooser: chooserForPanel(now) });
}

/* The open chooser as the panel draws it, or null: its rows ① and ② with each
 * order's pay and end (null where none is filed — the panel says "?"), the
 * card row, the address it is about, and how long it has left. */
function chooserForPanel(now) {
  var c = choosing;
  if (!c || now > c.until) return null;
  var rows = [];
  heldOrders(now).forEach(function (o, i) {
    if (c.among.indexOf(holdIdOf(o)) === -1) return;
    rows.push({ pick: holdIdOf(o), n: i + 1, pay: numOrNull(o.pay), end: o.dropoff || null });
  });
  var card = c.card && scanner.offer && scanner.offer.id === c.card
    ? { pick: 'card', pay: numOrNull(scanner.offer.pay) } : null;
  return { id: c.id, kind: c.kind, line: c.d.line, rows: rows, card: card,
           closesInMs: c.until - now };
}

/* The addresses in the pool asked again (Assemble.retryUnowned), and every one
 * a cue now decides filed through the one road, with that cue. Called after a
 * sighting, an address filed, a Took and a Drop. With carrying two off there
 * is no pool. */
function retryPool() {
  if (!carryingTwo(Date.now())) return;
  var before = Assemble.unowned(assembly);
  var found = Assemble.retryUnowned(assembly, heldOrders(Date.now()));
  found.forEach(function (f) {
    var said = { dropoff: f.d, at: Date.now() };
    dropoffArrived(said, { order: f.order, cue: f.cue });
    if (said.dropoff) broadcast(said);
  });
  if (found.length || Assemble.unowned(assembly) !== before) {
    broadcast({ unowned: Assemble.unowned(assembly) });
  }
}

/* A Trip Planner's pickups, each marked with the order it is for (`of`),
 * when the assembler's own cues decide one (Assemble.attribute): the app —
 * Uber's planner is no DoorDash order's — the Took — a read older than an
 * order's Took is not that order's — and the store the stop names against
 * each card's pickup (MV.plannerName, less the icon's letters). Never the
 * deadline, growth or elimination, which are about a dropoff. Map view
 * numbers that pin P1 or P2, and a held pickup is filed, pinned and visited
 * under that order (pickupOwner). Two orders from one store, or no cue,
 * leave it no order's: a plain P, and nothing ever marked of it. With one
 * order there is nothing to decide. `page` is the read's (Assemble.pageOf),
 * for its app; `at` the read's own time. */
function ownPickups(stops, now, page, at) {
  var orders = heldOrders(now);
  stops.forEach(function (st) { if (st) delete st.of; });
  if (!carryingTwo(now) || orders.length < 2) return;
  stops.forEach(function (st) {
    if (!st || st.kind !== 'pickup') return;
    var a = Assemble.attribute(assembly, orders, {
      app: page && page.app ? page.app : null,
      at: typeof at === 'number' ? at : null,
      store: MV.plannerName(st.name) || null });
    if (a.order) st.of = holdIdOf(a.order);
  });
}

/* Where a Took puts its order, and what it puts down. Returns {replaced,
 * added, putDownPay}: `replaced` the orders put down, each to have its drop row
 * `by: 'replaced'` (an empty list for none).
 *
 * Both ways, first:
 *   - the same card id again is a Took pressed twice: replaced in place, no
 *     drop row, as before;
 *   - an ADD-ON card (isAddOnCard: the parser's `addon`, "+ $9.50" over "+8
 *     min (+1.3 mi)", or Uber's screen `uber.addon`) with an Uber order in the
 *     car JOINS that order's trip (addOnBase, tripOf): held beside it, no
 *     drop row, no cap — the trip is one order to every cap — and it runs no
 *     shorter than the trip does (holdEnds). The owner's decision of 17 Oct
 *     2026; see "a trip" above maxHeld. With no Uber order in the car it is
 *     taken as any other card is, below, on its own clock.
 *
 * Carrying two off: the trip in the car, as Stage 4 had the order — the Took
 * replaces it, every order of it (and they are kept as shadows for `would`).
 * With two trips in the car already, it replaces the first-taken, and the
 * other stays until its own end: the flag going off never puts down an order
 * it held.
 *
 * Carrying two on:
 *   - a RE-OFFER of an order in the car — same miles, card minutes and both
 *     ends, a different pay, inside HELD_CARD_MS of that order's Took
 *     (Assemble.reOffer) — replaces it, `by: 'replaced'`;
 *   - anything else is ADDED, and a Took past MAX_HELD trips puts down the
 *     trip whose clock ends soonest (tripEnds), every order of it, `by:
 *     'replaced'`, and the panel says its pay.
 * A DoorDash card for two orders ("Drop off 2 orders") is one card and one
 * Took, so one order here: nothing counts its stops. */
function placeTook(took, marked, inCar, now) {
  var out = { replaced: [], added: false, putDownPay: null };
  var same = inCar.filter(function (o) { return o.id === took.id; })[0] || null;
  var base = null;
  if (isAddOnCard(marked)) {
    took.addOn = true;
    // Never onto itself: a Took pressed twice on the add-on is `same`.
    base = addOnBase(inCar.filter(function (o) { return o !== same; }));
    if (base) {
      took.of = tripOf(base);
      // The trip's end: the order taken last on it, as every order of the
      // trip taken after the first outlives the one before it (holdEnds).
      took.ofEnds = holdEnds(base);
    }
  }
  if (same) {
    setHeld(inCar.map(function (o) { return o === same ? took : o; }));
    return out;
  }
  if (base) {
    out.added = true;
    setHeld(inCar.concat([took]));
    return out;
  }
  if (!carryTwo()) {
    // Any other Took replaces the first-taken trip, with a drop row for each
    // of its orders — and every OTHER trip in the car stays, until its own
    // clock or Drop. With two held and the flag read off (turned off
    // mid-shift, or two restored from holding.json) this kept the Took alone:
    // the second order left the car with no row, and nothing said it had.
    // Measured at f80d0c2: two orders restored at boot, carrying two off, one
    // Took — holding.json named only the new order and the journal had a drop
    // row for the first alone.
    var first = inCar.length ? tripOf(inCar[0]) : null;
    var before = inCar.filter(function (o) { return tripOf(o) === first; });
    if (before.length) {
      out.replaced = before;
      shadows = before.slice();
    }
    setHeld(inCar.filter(function (o) { return before.indexOf(o) === -1; }).concat([took]));
    return out;
  }
  var again = inCar.filter(function (o) {
    return Assemble.reOffer(o, marked, now, HELD_CARD_MS);
  })[0];
  if (again) {
    out.replaced = [again];
    setHeld(inCar.map(function (o) { return o === again ? took : o; }));
    return out;
  }
  var list = inCar.concat([took]);
  if (tripsIn(list).length > maxHeld()) {
    var soonest = tripsIn(inCar).sort(function (a, b) {
      return tripEnds(inCar, a) - tripEnds(inCar, b);
    })[0];
    var gone = inCar.filter(function (o) { return tripOf(o) === soonest; });
    out.replaced = gone;
    // ...said by its pay: the trip's, every order of it.
    var pays = gone.map(function (o) { return numOrNull(o.pay); })
      .filter(function (p) { return p !== null; });
    out.putDownPay = pays.length
      ? Math.round(pays.reduce(function (a, b) { return a + b; }, 0) * 100) / 100 : null;
    list = list.filter(function (o) { return gone.indexOf(o) === -1; });
  }
  out.added = inCar.length >= 1;
  setHeld(list);
  return out;
}

/* Which orders one tap of Drop puts down with two in the car, or null for the
 * chooser: the one order whose pinned door the latest good fix is at (the
 * GPS drop's own arrival circle), else the one order the GPS has seen arrive.
 * Nothing else decides — not which was taken first, not which ends sooner. */
function dropDecides(orders, now) {
  var beat = scanner.beat;
  var f = beat && beat.gps && beat.gps.fix;
  if (f && f.gpsOk === true && typeof f.freshFor === 'number' && f.freshFor > 0
      && typeof f.lat === 'number' && typeof f.lon === 'number'
      && typeof f.gpsErr === 'number' && isFinite(f.gpsErr)) {
    var at = orders.filter(function (o) {
      var pin = heldEndPin(o);
      return pin && pinMetres(f, pin)
        <= ARRIVE_M + Math.min(f.gpsErr, ARRIVE_ERR_CAP_M);
    });
    if (at.length === 1) return at;
  }
  var arrived = orders.filter(function (o) { return !!o.arrivedAt; });
  return arrived.length === 1 ? arrived : null;
}

/* An address the scanner read, or one the assembler made off a planner's
 * sighting: decided by Assemble.dropoff, then written and said here. This was
 * the dropoff branch of the scanner's line handler, moved out unchanged in
 * what it writes, so both roads end in one place. `read` is the message the
 * stream will be sent: `read.dropoff` is deleted when nothing should be said,
 * and `read.holding` set when the hold took it. */
function dropoffArrived(read, force) {
  // The destination, read off the screen that comes AFTER the accept.
  //
  // It goes onto the order in the car and nowhere else. An offer card
  // does not name where a delivery ends - 106 of this driver's 604 cards
  // print "Customer dropoff" and no address - so `holding.dropoff` was
  // null on 18% of accepted jobs, which is what makes the stacking advice
  // silent on 39% of the pairs it is asked about.
  //
  // It also goes onto the CARD ON THE PANEL, when there is no order in
  // the car and there is a card.
  //
  // This paragraph used to say the opposite — "only when there IS an
  // order in the car... nothing here touches `scanner.offer`" — and the
  // reasoning behind it was sound for the flow it was written for. Read
  // with nothing held and no card up, this is an address belonging to no
  // job, and storing it would measure the next offer against wherever
  // the driver happened to be pointing the camera.
  //
  // What that missed is the driver's actual habit: "for doordash orders
  // I need to tap the customer drop off location to show the address
  // when screening". They reveal the address BEFORE deciding, because
  // where a job ends is half of whether it is worth taking. In that
  // moment there is no held order — and there is a card, with an id, on
  // the panel, which is not "wherever the camera happened to be
  // pointing". The guard that matters was never "an order is held", it
  // was "this address belongs to something identifiable".
  //
  // So: the held order first, because with one in the car that is the
  // stronger claim — every pair judged against it is nonsense without an
  // end. Otherwise the offer on the slot, and only while it is still the
  // card in front of the driver. With neither, nothing is stored, which
  // is exactly what happened before.
  //
  // ...except a PRESS with both there: an order in the car and another card
  // being screened. "The held order first" gave the press to the order
  // whatever the phone showed, and replaced the end it had — so a press is
  // now the order's or the card's on a cue the screen gave, or the
  // driver's pick from the chooser (whoseDropoff, pressBetween).
  //
  // Asked through holding(), never off `scanner.held` directly. That
  // field is the raw list; holding() is the question "is an order being
  // carried RIGHT NOW", and it is not the same question - an order whose
  // stated time has run out, plus half again, plus ten minutes, is
  // already forgotten by the panel and by the stack line. Reading the
  // slot here would attach the address to a job everything else has
  // given up on.
  // What the assembler decides about it, every rule in one place: whether it
  // goes onto the order in the car, onto the card being screened, or nowhere,
  // and from which rank. See Assemble.dropoff. Below is what is written and
  // said about the answer.
  //
  // A Trip Planner's lone dropoff off a list whose end was below the screen
  // (`singleCardOnly`, Assemble.plannerLoneDropoff) is filed only onto a held
  // order whose card was ONE order on ONE leg, and is otherwise dropped whole,
  // with this line in the log.
  var dNow = Date.now();
  var carrying = holding(dNow);
  // A batched trip's last door (Assemble.batchPlan) is for ONE order in the
  // car and no other shape: with two held — an add-on's trip, carrying two,
  // or two restored with the flag off — the planner's doors are two orders'
  // and are filed on cues (attribute), never as one order's batch. Dropped
  // whole, and not said.
  if (read.dropoff && read.dropoff.batch && heldOrders(dNow).length !== 1) {
    delete read.dropoff;
    return;
  }
  // WHOSE IT IS, with two orders in the car (Stage 5): see whoseDropoff. It
  // names the order the rest of this function files onto, in place of the
  // first-taken, or says nothing is to be filed — the chooser is open, or the
  // address waits in the pool — and then nothing below runs. `cue` is how it
  // was decided, for the mark row; `would`, with carrying two off, is what
  // attribution would have decided, for the rows this already writes.
  var who = whoseDropoff(read, force, dNow);
  if (who.stop) {
    delete read.dropoff;
    return;
  }
  if (who.order !== undefined) carrying = who.order;
  var cue = who.cue;
  var would = who.would;
  var said = read.dropoff ? Assemble.dropoff(carrying, read.dropoff, screeningCard(dNow))
    : null;
  if (said && said.drop) {
    console.log('planner dropoff not filed: the list ran off the screen and '
                + 'the held card is not a single trip');
    delete read.dropoff;
  }
  if (read.dropoff && typeof read.dropoff.line === 'string') {
    // Whether the driver ASKED for this one, or the rig simply saw it.
    //
    // The scanner now reports an address off any screen that has one and
    // no payout, not only inside the window a button press opens — the
    // driver taps the dropoff pin on their phone, which is a screen
    // change the motion gate already reads, so the rig was looking
    // straight at it and throwing it away for want of a second action.
    //
    // The two are not the same claim. A press is the driver saying "this
    // screen is the destination", and it overrules what the card said.
    // An unprompted sighting is the rig filling in a blank: it may fill
    // one and may not overwrite one. Otherwise a navigation screen left
    // up between offers would quietly rewrite the destination of a card
    // that had named its own — a confidently wrong answer arrived at
    // without anybody asking a question.
    //
    // Missing means asked, so a scanner older than this field keeps the
    // behaviour it had.
    var wasAsked = said.asked;
    var kept = said.kept;
    // ...and whether an unasked one is LABEL-PROVEN: the screen printed
    // it under "Dropoff" in its own stop block (rpi/scan_pi.py, digest),
    // which the driver asked to be enough, with no ⌖, while their own
    // ✓ Took is in force. It may replace an end the CARD gave
    // (`dropoffScanned` false) — a door beats the card's corner or town
    // — and never one that came off the screen, pressed or seen.
    //
    // Two guards against a planner still up from the trip before. Seen
    // after the Took: `at` is the scanner's clock when it read the
    // screen, and a read older than the hold is not about it. And not
    // one of the hold's own planner pickups: a restaurant's door filed
    // as where the customer lives is the confidently wrong direction,
    // so that one is refused outright, blank or not.
    //
    // In Assemble.dropoff's words now: a press replaces anything; a label- or
    // planner-proven one replaces the card's end; one with no label fills a
    // blank; and nothing unprompted moves what the screen already said.
    // `fields` on the hold says which of them each value is.
    var labelled = said.labelled;
    if (said.to === 'hold') {
      // ...and the hold's `fields`, `dropoff` and `dropoffScanned` together;
      // a planner lone dropoff that files clears the planner's 'list'.
      Assemble.file(carrying, read.dropoff, said, assembly);
      // ...and how the order was chosen for this end, with two in the car
      // (`only`, a cue's name — 'cardStreet', 'elimination', ... — or
      // 'chooser'), for /api/status's `orders[].cue`; null with one.
      carrying.endCue = cue || null;
      // ...and into holding.json, which it reached only by way of the NucBox
      // search (armHeldEnd, searchHeldEnd's save) — so with NUCBOX_SEARCH
      // unset, a ⌖ end the driver pressed for lived in memory alone, and a
      // restart in the driveway brought the order back with the card's end.
      // Measured at f80d0c2: a ⌖ end filed and on the panel, holding.json
      // still holding the card's end, and /api/status saying the card's end
      // (`from: 'card'`) after a restart.
      saveHold(carrying);
      // ...and written down, which it was not.
      //
      // This is the case the button EXISTS for. An offer card does not
      // say where a delivery ends — Uber prints "Customer dropoff" and
      // the address only appears on the screen after the accept — so the
      // whole point is to capture it once the order is in the car. That
      // path updated process memory and nothing else.
      //
      // It reached disk only if another card happened to arrive before
      // the order ended, because the pairing row carries the held job's
      // dropoff. Finish a delivery with no offer in between, or end the
      // shift, or restart the server, and the address the driver had
      // deliberately captured was simply gone — off the offers page, off
      // the map, out of the stack line's reasoning, with nothing saying
      // it had ever been there.
      //
      // Its own mark, the same shape and the same `asked` bit as the
      // screening path writes, so the fold applies both by one rule.
      if (carrying.id) {
        appendLines(JSON.stringify({
          v: 1, kind: 'mark', at: Date.now(),
          id: carrying.id,
          dropoff: read.dropoff.line,
          asked: wasAsked,
          // Only on a label-proven one, so the fold can let it past the
          // card's own end as the live path just did. See the marks fold.
          labelled: labelled || undefined,
          // How the order was chosen, with carrying two on — `only`, a cue's
          // name, or `chooser` — and, with it off, what attribution would
          // have said ({cue, held}). Ids and a word: no address. See
          // whoseDropoff.
          cue: cue || undefined,
          would: would || undefined,
          // ...and a batched trip's (Assemble.batchPlan): that the end is
          // the last of `drops` doors on one card. A flag and a count, no
          // address beyond the end the row already names.
          batch: read.dropoff.batch ? true : undefined,
          drops: read.dropoff.batch ? read.dropoff.batch.drops.length : undefined
        }) + '\n', function (err) {
          // Said out loud for the same reason the screening branch says
          // it: a read-only SD card mid-shift is the classic Pi failure,
          // and the panel would otherwise go on confirming an address
          // that reached nothing.
          if (err) {
            console.error('journal: could not record a held dropoff: '
                          + err.message);
          }
        });
      }
    } else if (carrying) {
      // Held, already knows where it ends, and nobody asked. Nothing to
      // do — and nothing to say either, because the driver did not ask a
      // question to be answered.
    } else if (said.to === 'card') {
      // Onto the card being screened, and onto its journal row.
      //
      // In memory first, because the panel and the stack line read
      // `scanner.offer` and a destination that only reached the file
      // would be invisible until the page was reloaded. `dropoffScanned`
      // travels with it for the same reason it does on a held order: a
      // destination the rig READ off a navigation screen and one the
      // CARD stated are different degrees of evidence, and the row has
      // to be able to say which it is holding.
      Assemble.fileCard(scanner.offer, read.dropoff, said, cue);
      // ...and, decided over an order in the car (`cue`: the card's own
      // popup, or the chooser — pressBetween), the card goes to every panel
      // with the end it now holds, as a popup's does: the panel's chip for
      // an end from a press is the card's, and the card's reading that would
      // carry it is not coming while the phone shows the address. Not with
      // nothing held, where the screening press is answered as it was.
      if (cue) read.offer = scanner.offer;
      // ...and appended, as its own line naming the offer. The same
      // shape as a tick: the journal is append-only, so this is a note
      // ABOUT a row rather than an edit to it, and the copy at home
      // merges it by the same newest-wins rule as everything else.
      appendLines(JSON.stringify({
        v: 1, kind: 'mark', at: Date.now(),
        id: scanner.offer.id,
        dropoff: read.dropoff.line,
        // Whether the driver ASKED, carried onto the row rather than
        // being decided here and forgotten.
        //
        // The guard above is about the card on the slot AT THIS MOMENT;
        // the fold that applies this mark is about the row on disk,
        // which is merged newest-wins from every reading of that offer
        // and can carry a dropoff the in-memory card has since lost —
        // readings of one card differ, and `bestReading` borrows ends
        // from whichever one had them. Without this field the fold has
        // no way to tell a press from a sighting and overwrites either
        // way, which is a wrong destination written into an append-only
        // file that syncs to the NUC.
        //
        // Absent means asked, matching how the reading itself is read
        // above, so rows written before this field existed keep the
        // behaviour they were written under.
        asked: wasAsked,
        // ...and how it was given this card over the order(s) in the car:
        // `chooser` when the driver picked it, `popup` when the press read
        // the card's own place popup (whoseDropoff, pressBetween).
        cue: cue || undefined
      }) + '\n', function (err) {
        // Said out loud, because every other write to this file says so
        // and this one is a deliberate press the driver expects to be
        // kept. An SD card remounted read-only mid-shift is the classic
        // Pi failure — rpi/journal.py names it — and the panel would go
        // on confirming "Dropoff read as ..." off the stream, which is
        // broadcast whether or not the row landed. The address would
        // then be gone at the next restart with nothing anywhere having
        // mentioned it, while the pairing row written seconds earlier
        // logged ITS failure on the same file.
        if (err) {
          console.error('journal: could not record a dropoff: ' + err.message);
        }
      });
    }
    // What was read is said to the panel over the stream, which is
    // where it was always coming from: live.html listens for
    // `msg.dropoff.line` and shows it on the button. A driver who
    // presses this with nothing to attach an address to still sees what
    // was read, and that is what they need.
    //
    // ...but only if they PRESSED, or if it was kept.
    //
    // That distinction did not exist when this was written: every
    // dropoff message followed a press, so "say what was read" was
    // always an answer to a question somebody asked. Unprompted
    // sightings broke it. The branch above refuses to overwrite a
    // destination the card itself stated and says so — "nothing to say
    // either, because the driver did not ask a question to be answered"
    // — and then the stream said it anyway, because the broadcast is
    // outside all of this.
    //
    // What the driver saw: holding an order whose destination came off
    // the card, a navigation screen for somewhere else catches one read,
    // and the panel's ⌖ button turns green reading "Dropoff read as
    // <the other address>". It is not the held job's destination, it is
    // not on the record, and /api/status cannot correct it — the poll
    // only rewrites `destSaid` when the held order is `dropoffScanned`
    // or when there is no held order at all, and this is neither. It
    // stands until the order ends.
    //
    // A press still shows what was read even when nothing could be
    // attached to it, which is the case the paragraph above is about and
    // is deliberately unchanged.
    // One tally row per unprompted address that arrives while an order is
    // in the car. It changes nothing and is here to answer one question.
    //
    // AUDITS.md refuses a guard on this path twice — refusing an
    // unprompted address whenever a rival card had been read recently —
    // because measured, it discards the HELD job's own destination, and
    // permanently: `dropoff_said` in rpi/scan_pi.py is set on emit and
    // never cleared, so an address refused once is never volunteered
    // again for that delivery. The refusal is right, but it was argued
    // from a firing rate nobody has measured, and that is the wrong way
    // to leave it.
    //
    // The counters the reader already keeps cannot answer it.
    // `addressAsOffer` and `streetNoAddress` describe the FRAME — was
    // there a payout on it, was there a street with no address. The
    // question here is about ATTRIBUTION, and only this process knows
    // both halves of it: what is in the car, and what is on the slot.
    //
    // So: whether an order was carried (this row exists at all), which
    // one, which card the driver was actually looking at, and what was
    // done with the address. `slot !== held` on a row whose `kept` is
    // true is a screening tap that may have been filed onto the wrong
    // job — the population the guard would have been for. `kept` false
    // is the other half, the tap that was discarded because the held
    // order already knew where it was going, which is its own Open entry.
    //
    // NO ADDRESS ON THIS ROW, deliberately. It is a tally, not a record
    // of where anybody lives, and the journal syncs to a second machine.
    // Two ids and a boolean answer the question; the street does not.
    //
    // Cheap by construction: the reader emits an address only off a frame
    // with no payout and no merchant on it, and suppresses a repeat of a
    // line it has already said, so this is roughly once per distinct
    // address seen rather than once per frame.
    //
    // `id` is stamped from the clock the way the reader's `seen` rows
    // are, and carries the same caveat: two in one millisecond would be
    // one key to the sync and one of them would be dropped. The reader
    // cannot produce two distinct addresses that close together.
    //
    // A kind this build invented is safe on both the fold and the sync:
    // the fold skips kinds it does not know ("something newer than this
    // reader") and syncKey carries an unknown kind across on its id and
    // seq, which is what the pair rows' own comment there is about.
    if (said.tally) {
      var sightedAt = Date.now();
      var onSlot = screeningCard(sightedAt);
      appendLines(JSON.stringify({
        v: 1, kind: 'sighting', at: sightedAt,
        id: 'sighting-' + sightedAt, seq: 1,
        held: carrying.id || null,
        // Null when the slot holds nothing recent enough to be what the
        // driver is looking at — which is a different answer from "the
        // same card", and the count needs to tell those apart.
        slot: onSlot ? onSlot.id : null,
        kept: !!kept,
        // With carrying two off: what attribution would have said, {cue,
        // held}, ids only. With it on: how this order was chosen.
        would: would || undefined,
        cue: cue || undefined
      }) + '\n', function (err) {
        // Said out loud like every other write on this path. A tally that
        // silently stopped being written would be read months later as a
        // rate of zero, which is the one wrong answer it can give.
        if (err) {
          console.error('journal: could not record a dropoff sighting: '
                        + err.message);
        }
      });
    }
    if (!wasAsked && !kept) { delete read.dropoff; }
    // ...and a PRESS for the order in the car that was not kept, which is a
    // store's screen and nothing else (Assemble.dropoff, rule 5: a press
    // otherwise replaces anything). Said, because the driver asked — but NOT
    // as what was read. The panel turns ⌖ green over any `dropoff.line` and
    // titles it "Dropoff read as <line>", and on 17 Oct that line was the
    // store's town: a green button over an end the order did not have. So
    // the line goes and the refusal comes in its place — why, and the end
    // the order kept — on the shape a press that found nothing already has
    // (`found: false`, `asked`), so a panel from before this says "not read",
    // which is true of the order, and never green. No mark row: nothing was
    // filed.
    //
    // ...and a press off Uber's navigation to a store with NO order in the
    // car (whoseDropoff `store`): refused for the card being screened as for
    // a hold, and said the same way, with no order's end to name as kept.
    if (wasAsked && !kept && (carrying || who.store)) {
      console.log('dropoff press not filed: ' + said.why
                  + (carrying ? ', the order keeps its end' : ', nothing filed'));
      read.dropoff = { line: null, found: false, asked: true, refused: said.why,
                       kept: carrying ? (carrying.dropoff || null) : null, at: read.dropoff.at };
    }
    // ...and an address filed onto the order in the car goes to the
    // panel AS that order's end, not only as the button's words.
    //
    // The driver's report: "I accepted a delivery, it mapped the drop
    // off address but it did not hold those pins when it scanned a
    // doordash card." The page learned where a held order ends only
    // from a READING (withStack), so a ⌖ read after ✓ Took turned the
    // button green and put nothing on Map view; what the map was
    // showing was the accepted CARD's own dropoff, drawn as this card's
    // "and drop it here", and the next card took it off the glass with
    // the card it belonged to. Measured in rpi/test_dashboard.py's
    // stage 'the held end, from the press': after the ⌖ read the map
    // had the car and the pickup and no held pin.
    //
    // Only when it was kept on the HOLD: an address filed onto the card
    // being screened, or read with nothing to file it on, is not where
    // the order in the car is going.
    //
    // `holding` is the first-taken order, as on every message — with two in
    // the car the address may have gone onto the second, which `orders` says.
    if (kept && carrying) {
      read.holding = heldForPanel(holding(Date.now()));
      if (carryingTwo(Date.now())) read.orders = ordersForPanel(Date.now());
    }
    //
    // `scanner.dropoff` and `scanner.dropoffAt` were kept here for that
    // and are gone. They were written on every read and not one line in
    // this repository ever read them back — the comment above them said
    // "so the page can say what was read", which the page does, from the
    // stream, having never asked for these. State nothing consults is
    // not a store, it is a claim in a comment.
    //
    // The reload case they would have covered is covered by the two
    // fields that are real: a held order carries `dropoff` and
    // `dropoffScanned`, and since this change so does the card on the
    // slot, both of which /api/status already sends.
  }
  // A dropoff filed onto the hold above is searched for on the NucBox
  // (searchHeldEnd); a no-op when nothing new was filed.
  if (read.dropoff) heldOrders(Date.now()).forEach(armHeldEnd);
}

/* ---------- the held order's own card, back under a new id -----------------
 *
 * After ✓ Took the same card can come back onto the phone and be logged again
 * under a NEW id. The scanner's OfferLog kept one card's identity, so a card
 * paged away from and back to was a new offer as far as the journal could tell
 * (see the dupe-id note in the commit that added this). It now remembers the
 * last few cards and gives one back its id inside ninety seconds
 * (rpi/journal.py, RECENT_CARDS), which the offer line's own-id test answers;
 * a return it cannot recognise — after a restart, past the ninety seconds, an
 * address read differently — still arrives under a new id, and this is for
 * those. The server then judged it against the held
 * order as a second job: a pair row in the append-only journal and a stack
 * line on the panel, for one order measured against itself. Measured on the
 * 12 Oct shift: 9 cards were logged under two ids each, one of them the card
 * just taken, back 33 s after its last row; its pair row (19 s after the Took)
 * reads stack `warn` under a PASS headline.
 *
 * The same card here is the card the driver pressed Took on, figure for
 * figure: pay to the cent, the same miles and the same card minutes, and the
 * same pickup and dropoff wherever both readings carry one (case, commas and
 * spacing ignored). Uber's own re-offers that differ by a few cents ("Includes
 * expected tip" against "Guaranteed") are different offers and stay paired.
 * And only within HELD_CARD_MS of the press: the order is on its way after
 * that, and a card the same to the cent is a new one.
 *
 * Not an accept detector. Nothing is marked and nothing is put in the car:
 * the driver already said they took THIS card, and this only stops the rig
 * from asking them about it a second time. */
var HELD_CARD_MS = envNumber('HELD_CARD_MS', 3 * 60000);

/* The figures a card is recognised by, and the test itself: moved to the
 * assembler (Assemble.cardSeen, Assemble.heldOwnCard), which is handed the
 * window and what the slot already says. Kept under these names so the call
 * sites read as they did. */
function cardSeen(c, reading) {
  return Assemble.cardSeen(c, reading);
}

function heldOwnCard(held, card, now, reading) {
  return Assemble.heldOwnCard(held, card, now, reading, HELD_CARD_MS,
                              scanner.offer ? scanner.offer.heldCard : null);
}

/* ---------- the GPS drop: at the held order's door, then gone from it -------
 *
 * The driver's words: "It can be safe to assume I have completed the order if
 * I am at the customer's address." So the order in the car is put down, by
 * the same code Drop runs (putDown), once the car has been AT the held
 * order's end and has then LEFT it. Never while it is still there.
 *
 * Not an accept detector, and it presses nothing: it only ends a hold the
 * driver started with ✓ Took. It reads no silence — every step is a GPS fix
 * the gate passed. And it turns no distance into minutes: the hold still
 * expires on its own stated clock, this only ends it sooner, as Drop does.
 *
 * WHERE THE END IS comes from Map view's rule and nowhere else: this server
 * searches the NucBox for it by that rule as soon as the hold names a dropoff
 * (searchHeldEnd), and when the page pins the held end at DOOR level — searchPlan says the dropoff names a house
 * number, and the NucBox answer it chose carries that number (MV.hasDoor),
 * inside the held card's disc — it posts the pin to /api/held-end. The first
 * pin for a dropoff wins. A street or a town is never an end for this: a pin
 * a few hundred metres off is a drop at the wrong house or no drop at all,
 * and refusing is the cheap error — the timer and Drop still apply. With no
 * NucBox set and Map view never opened on that hold, there is no pin and
 * nothing here happens.
 *
 * The numbers, from a replay of the driver's real 12 Oct drive (385 min of
 * fixes, replayed outside the repo). Parked, the car's fixes
 * scattered 3.4 m from where it stood at the median, 22.7 m at p99 and
 * 34.7 m at worst, while the receiver's own error estimate read 27.6 m at the
 * median — about eight times the real scatter — and no parked fix was ever
 * past 75 m from its stop. So ARRIVE_M is 75 m plus the fix's error capped at
 * 25 (ARRIVE_ERR_CAP_M): 100 m at most, where it was 75 + the gate's 50 =
 * 125. What the cap does NOT do is keep the car's wait for the food from
 * arriving at a door near the restaurant. Replayed with a door placed round
 * each of the drive's three restaurant stops, eight directions each: 50 or
 * 75 m away it arrived 24 times of 24 at 125 m AND at 100 m; 100 m away, 1 of
 * 24 at 125 m and 0 at 100 m. A door at the restaurant would have put the
 * order down as the car left with the food, 21 and 43 min early on the two
 * orders whose wait came after the Took. The restaurant guard below
 * (pickupNearEnd) is what stops that, not the radius. (Re-run in the
 * verification pass; the first version of this paragraph had the 1 of 24 as
 * the 50-75 m doors at 100 m.)
 *
 * DWELL_S is 60 s inside. The drive held 53 still stops of 45 s or more; 60 s
 * removes 7 of them, and the real doors held the car inside for 184, 243 and
 * 794 s, so none is lost. Between counted fixes there may be no silence over
 * GAP_S (gps.py's own 20 s staleness line): at 30 mph a car crosses a 200 m
 * circle in 15 s, so driving past does not arrive; a crawl in stopped
 * traffic beside the door can, and is what to watch for. But a run of fixes
 * the GATE refused (err over 50 m, `rough`) is not silence: the replay had
 * runs of 21-45 s of them parked at a door, and resetting the dwell on them
 * delayed one drop. Such a run, up to REJECTED_GAP_S (60 s) and with good
 * fixes inside the circle on both sides of it, keeps the dwell; the time in
 * it does not count toward it. A stretch of no fixes at all still resets
 * after GAP_S.
 *
 * LEAVE_M is 300 m on TWO consecutive good fixes, unchanged: the replay found
 * no false departure with it. Settable for the suite, like HOLD_GRACE_MS. */
function envNumber(name, dflt) {
  var v = Number(process.env[name]);
  return (isFinite(v) && v >= 0 && process.env[name] !== undefined && process.env[name] !== '')
    ? v : dflt;
}
var ARRIVE_M = 75;            // plus the fix's own error, capped below
var ARRIVE_ERR_CAP_M = 25;    // so 100 m at most (the gate itself stops at 50)
var LEAVE_M = 300;
var LEAVE_FIXES = 2;
var DWELL_MS = envNumber('GPS_DWELL_MS', 60000);
var GAP_MS = envNumber('GPS_GAP_MS', 20000);
var REJECTED_GAP_MS = 60000;
// A door this close to one of the held order's pickups is not armed. See
// pickupNearEnd.
var PICKUP_GUARD_M = 150;
var PICKUP_PINS_MAX = 4;
// How long the panel says "dropped · left the dropoff" after one.
var GPS_DROP_SAID_MS = 60000;
// ...and "previous order put down" after a Took that replaced a hold.
var HELD_REPLACED_SAID_MS = 60000;
// ...and how long the panel offers to undo a Took that added a second order.
var UNDO_ADDED_MS = 5000;

// The live part of the arrival, which is not worth an SD write per fix: where
// the dwell started and the last fix counted; `skippedMs`, the time in
// gate-refused runs since then that does not count toward it; and
// `refusedFrom`/`refusedTo`/`silentMs`, the run of refused fixes since the
// last counted one (its first and last, and its longest stretch of nothing at
// all). `arrivedAt` and the pin ARE on the hold, and so in holding.json,
// because those are the facts a restart in the driveway must not forget.
//
// One per order, by holdId (`arrivals`): two orders in the car are two doors,
// and a dwell counted at one is not a dwell at the other. Memory only, as the
// one was; an order put down takes its own with it (forgetHoldsGone).
var arrivals = {};

function resetArrival(id) {
  if (!id) return null;
  arrivals[id] = freshArrival(id);
  return arrivals[id];
}

function arrivalOf(id) {
  return arrivals[id] || resetArrival(id);
}

/* A beat's fix as this file will count it, or null: the gate passed it, it is
 * still inside gps.py's staleness rule (`freshFor`, which a scanner older than
 * that field does not send — refused, not guessed), and it is a fix this file
 * has not already counted. Its time is the server's arrival less its age. */
function countableFix(beat, now, arrival) {
  var g = beat && beat.gps;
  var f = g && g.fix;
  if (!f) return null;
  if (f.gpsOk !== true) { refusedFix(f, now, arrival); return null; }
  if (typeof f.freshFor !== 'number' || !(f.freshFor > 0)) return null;
  if (typeof f.lat !== 'number' || typeof f.lon !== 'number'
      || !isFinite(f.lat) || !isFinite(f.lon)) return null;
  if (typeof f.gpsErr !== 'number' || !isFinite(f.gpsErr)) return null;
  var age = (typeof f.gpsAge === 'number' && isFinite(f.gpsAge) && f.gpsAge >= 0)
    ? f.gpsAge : null;
  if (age === null) return null;
  var at = now - age * 1000;
  if (arrival.lastFixAt !== null && at <= arrival.lastFixAt) return null;
  return { lat: f.lat, lon: f.lon, err: f.gpsErr, at: at };
}

/* A fix the gate refused as `rough` (err over FIX_ERR_MAX), kept only as a
 * time: it proves the receiver was still talking, so a run of them is not the
 * silence GAP_MS resets on. Its position is never used. Only a fresh one, and
 * only after a counted fix (the run is measured from it). */
function refusedFix(f, now, arrival) {
  if (f.gpsWhy !== 'rough' || arrival.lastFixAt === null) return;
  if (typeof f.freshFor !== 'number' || !(f.freshFor > 0)) return;
  if (typeof f.gpsAge !== 'number' || !isFinite(f.gpsAge) || f.gpsAge < 0) return;
  var at = now - f.gpsAge * 1000;
  var last = arrival.refusedTo === null ? arrival.lastFixAt : arrival.refusedTo;
  if (at <= last) return;
  arrival.silentMs = Math.max(arrival.silentMs, at - last);
  if (arrival.refusedFrom === null) arrival.refusedFrom = at;
  arrival.refusedTo = at;
}

/* The held end this file may arrive at, or null: a door-level pin made for
 * this hold and for the dropoff it still names (a ⌖ press can change it). */
function heldEndPin(h) {
  var p = h && h.endPin;
  if (!p || p.doorLevel !== true || p.dropoff !== h.dropoff) return null;
  return p;
}

/* The restaurant guard: whether one of the held orders' pickups, pinned by
 * Map view (/api/held-pickup), is within PICKUP_GUARD_M of its end. The 12 Oct
 * replay: a door 50-75 m from a restaurant the car waited at arrived there 24
 * times of 24, and would have dropped the order on leaving with the food,
 * 19-43 min early. A door that close is not armed at all — the timer and Drop
 * still end the order — and /api/status says why.
 *
 * EVERY order's pickups, not only this one's: with two in the car the car
 * waits at the second order's restaurant too, and a first order's door beside
 * it would arrive there the same way. With one order it is that order's. */
function pickupNearEnd(h, pin) {
  var picks = [];
  heldOrders(Date.now()).concat(h && scanner.held.indexOf(h) === -1 ? [h] : [])
    .forEach(function (o) {
      if (Array.isArray(o.pickupPins)) picks = picks.concat(o.pickupPins);
    });
  return picks.some(function (p) {
    return pinMetres(p, pin) <= PICKUP_GUARD_M;
  });
}

/* The customer guard: why an order's card does not let the GPS drop arm on
 * its pinned door, or null when it does. A card for more than one order
 * ("Drop off 2 orders", a batched Uber trip — scan_pi.says_multi_order) is
 * one Took and one hold with TWO customers' doors, and the pin is whichever
 * the ⌖ read: the car stops there and leaves for the second with the order
 * still half in the car. Measured at f80d0c2: a two-customer DoorDash card
 * held, its first customer's door pinned, the car stopped there and left, and
 * a drop row `by: 'gps'` put the order down. Only a card that SAYS one order
 * arms — `multiOrder: false`, as every offer line from a current scanner
 * carries — the rule Assemble.dropoff already keeps for a planner's lone
 * dropoff, and for the reason it gives: a card from a scanner too old to say
 * is no witness that there is one door. The timer and Drop still end it. */
function notOneCustomer(h) {
  var c = h && h.card;
  if (c && c.multiOrder === false) return null;
  return c && c.multiOrder === true ? 'two customers' : 'customer count unread';
}

/* ---------- the held end, searched for by this server --------------------
 *
 * The driver: GPS arrival should arm without opening Map view. So when the
 * hold's dropoff is set or changes (✓ Took with a card dropoff, ⌖ Scan, a
 * sighting filed onto the hold) and NUCBOX_SEARCH is set, this server asks
 * the NucBox the question Map view would — searchPlan's street, in discBox
 * round the HELD card's disc (discFor: its fix, its distance plus SLACK_MI),
 * chosen by pickInDisc (one answer, or every answer one place) — and keeps
 * the pin only when it is DOOR level: the dropoff names a house number and
 * the chosen answer carries it (hasDoor). Map view's own functions, so the
 * page and the server cannot keep two rules for "door level".
 *
 * ...and where the NucBox has the street and not the door ('nodoor') and the
 * phone printed a place for the stop (`dropoffPlace`), the place by its name
 * in the same disc: searchHeldPlace, the owner's decision of 17 Oct 2026, by
 * map-view.js pickPlace's rules, pinned `by: 'place'`.
 *
 * ...and before either, where the street AS PRINTED is not inside the card's
 * reach (MV.retryWanted), the door once more with the street's type word left
 * out (searchHeldRetry, MV.streetRetry: "1830 <Name> Creek Cts SW" asked
 * again as "1830 <Name> Creek SW", the 17 Oct evening snap), an answer kept
 * only at the same door on the same street (MV.pickRetry). Map view's
 * NbxSearch.place asks the same second question. And where the street WAS
 * found inside the reach and not the door, once more with a directional
 * inside its name the other way (searchHeldDir, MV.dirRetry: "810 <A> West
 * <B> Parkway" asked as "810 <A> W <B> Parkway", the 20 Oct fault).
 *
 * The public geocoder is never asked: it is the page's fallback, rationed and
 * outside the VPN, and a pin the GPS ends a delivery on is the NucBox's or
 * none. With NUCBOX_SEARCH unset nothing here sends anything.
 *
 * ONE search per hold and dropoff text (`endSearch.key`); a failure or a
 * timeout is asked once more after END_RETRY_MS and then left. A refusal is
 * kept on the hold as `endWhy` (with `endWhyFor`, the text it is about, so a
 * changed dropoff does not wear the old reason) and /api/status says it, so
 * the driver can see why the GPS drop is not armed. The first valid pin for a
 * text wins, this one or the page's, and an answer that comes back after the
 * hold or its text changed is dropped. END_RETRY_MS is settable for the suite,
 * like GPS_DWELL_MS; 30 s is chosen, not measured. */
var END_RETRY_MS = envNumber('NUCBOX_RETRY_MS', 30000);
// One per order, by holdId: {key, timer}.
var endSearch = {};

function endKeyOf(h) {
  return h && typeof h.dropoff === 'string' && h.dropoff
    ? holdIdOf(h) + '\n' + endTextOf(h) : null;
}

/* The place the phone printed for the held end's stop (`dropoffPlace`,
 * Assemble.file: off a ⌖ press's dropoff line, a navigation sheet, or a Trip
 * Planner stop), or null. */
function placeOf(h) {
  return h && typeof h.dropoffPlace === 'string' && h.dropoffPlace ? h.dropoffPlace : null;
}

/* What a search of the held end is ABOUT: its dropoff text, and its place
 * after a newline when it has one. The key a search is asked once by, and
 * what a refusal is kept for (`endWhyFor`), so a place learnt for the same
 * dropoff text is searched for — and a refusal said of the text alone is not
 * said of the text and its place. With no place it is the dropoff text,
 * exactly, so a holding.json written before places were kept reads the same. */
function endTextOf(h) {
  var place = placeOf(h);
  return h.dropoff + (place ? '\n' + place : '');
}

/* The hook: called for each order after the list is written (setHeld), after
 * a scanner line may have filed a dropoff onto one, and at boot. A no-op
 * unless the order names a dropoff this server has not yet searched for. */
function armHeldEnd(h) {
  if (!NBX.search || !h) return;
  var id = holdIdOf(h);
  var key = endKeyOf(h);
  var was = endSearch[id];
  if (was && key === was.key) return;
  if (was && was.timer) clearTimeout(was.timer);
  endSearch[id] = { key: key, timer: null };
  // Nothing to search, already pinned, or already refused before a restart
  // for a reason another asking would not change (a NucBox down is asked).
  if (!key || heldEndPin(h)
      || (h.endWhyFor === endTextOf(h) && h.endWhy !== 'NucBox down')) return;
  searchHeldEnd(key, 1);
}

// The order this search is still about, or null.
function endHold(key) {
  var hit = null;
  heldOrders(Date.now()).forEach(function (h) {
    var on = endSearch[holdIdOf(h)];
    if (on && on.key === key && endKeyOf(h) === key) hit = h;
  });
  return hit;
}

function refuseHeldEnd(h, why) {
  h.endWhy = why;
  h.endWhyFor = endTextOf(h);
  saveHold(h);
}

// pickInDisc's refusals, in the panel's words — and pickPlace's one of its
// own, the place asked after the door and nothing of that name answered.
var END_WHY = { nodoor: 'no house number', none: 'not inside the card\'s reach',
                several: 'several answers', capped: 'too many answers',
                noplace: 'no door, place not found' };

/* One search question for the held end, answered from nbxCache or asked;
 * `answered(out)` with nbxHits' answer. A NucBox that does not answer is
 * 'NucBox down' on the hold and is asked once more, the whole search from the
 * top, after END_RETRY_MS. The door's question and the place's both come
 * through here — and the street index's (searchHeldNamed), whose answer
 * `read` turns into what is kept (streetAnswer), or null for one that is not
 * an answer, which is the NucBox not answering as any other is. */
function endAsk(key, attempt, target, answered, read) {
  read = read || function (body) { return Array.isArray(body) ? nbxHits(body) : null; };
  if (nbxCache.has(target)) return answered(nbxCache.get(target));
  nbxAsk(target, function (err, body) {
    var out = err ? null : read(body);
    if (!err && !out) err = 'not an answer';
    if (err) {
      var now = endHold(key);
      if (!now || heldEndPin(now)) return;
      refuseHeldEnd(now, 'NucBox down');
      var on = endSearch[holdIdOf(now)];
      if (attempt === 1 && on) {
        on.timer = setTimeout(function () {
          on.timer = null;
          searchHeldEnd(key, 2);
        }, END_RETRY_MS);
      }
      return;
    }
    nbxRemember(target, out);
    answered(out);
  });
}

/* The pin, kept on the hold as /api/held-end keeps one, plus who chose it:
 * 'server' for the door, 'place' for the place (searchHeldPlace). Door level
 * either way — the level the GPS drop arms at (heldEndPin) — and the
 * restaurant guard (pickupNearEnd) and the customer guard (notOneCustomer)
 * hold it to the same rules whoever chose it. */
function pinHeldEnd(h, at, by, asked) {
  h.endPin = { dropoff: h.dropoff, lat: at.lat, lon: at.lon,
               doorLevel: true, pinnedAt: Date.now(), by: by };
  // ...and the street the door was found by when it was not the dropoff's
  // own (searchHeldRetry: the type word left out; searchHeldNamed: the one
  // street the street index says the name as read is).
  if (asked) h.endPin.asked = asked;
  delete h.arrivedAt;
  delete h.endWhy;
  delete h.endWhyFor;
  resetArrival(holdIdOf(h));
  saveHold(h);
}

function searchHeldEnd(key, attempt) {
  var h = endHold(key);
  if (!h) return;
  var plan = MV.searchPlan(h.dropoff);
  if (!plan || plan.kind !== 'street' || !plan.door) return refuseHeldEnd(h, 'no house number');
  var disc = MV.discFor(h.card || null);
  if (!disc) return refuseHeldEnd(h, 'no card fix');
  var said = nbxTerm(plan.street);
  if (!said) return refuseHeldEnd(h, 'no house number');
  var target = nbxSearchTarget('street', said, MV.discBox(disc));
  function answered(out) {
    var now = endHold(key);
    if (!now || heldEndPin(now)) return;    // moved on, or the page pinned first
    // Door level is pickInDisc's own rule: with a house number in the plan
    // (required above) it keeps only answers that carry it, and refuses with
    // 'nodoor' when none does. A second hasDoor here could never refuse
    // anything — undone, no check failed — and was a second place answering
    // the same question.
    var res = MV.pickInDisc(out.hits, disc, plan, out.cutAt);
    // The street as printed not inside the card's reach: its door asked once
    // more with the type word left out (MV.streetRetry; the 17 Oct evening
    // snap, "<Name> Creek Cts SW" answered with nothing), held to the same
    // street and the same door (MV.pickRetry).
    var again = MV.streetRetry(plan);
    if (again && MV.retryWanted(res, out.hits, disc)) {
      return searchHeldRetry(key, attempt, disc, again, res, out.hits, plan);
    }
    // ...and with no type word to leave out, the street index asked which
    // street the name as read is (MV.nameWanted; the 19 Oct night fault).
    if (NBX.streets && MV.nameWanted(res, out.hits, disc, null)) {
      return searchHeldNamed(key, attempt, disc, plan, res);
    }
    // ...and the street found inside the disc and not the door, a directional
    // inside its name the other way (MV.dirRetry; the 20 Oct "Ernest West
    // Barrett" fault), before the place and the short street are asked.
    var dir = MV.dirRetry(plan);
    if (dir && MV.dirWanted(res, out.hits, disc)) {
      return searchHeldDir(key, attempt, disc, dir, res);
    }
    settleHeldEnd(key, attempt, disc, res, null);
  }
  endAsk(key, attempt, target, answered);
}

/* ...the directional retry: ONE more question, the street with its
 * directional words the other way ("810 <A> West <B> Parkway" asked as "810
 * <A> W <B> Parkway"), in the same discBox, through endAsk. Its answer is acted
 * on only when it pinned the door on the same street (MV.pickRetry,
 * MV.afterDir); else the first answer, a 'nodoor', goes on as before. */
function searchHeldDir(key, attempt, disc, dir, first) {
  var said = nbxTerm(dir.street);
  if (!said) return settleHeldEnd(key, attempt, disc, first, null);
  endAsk(key, attempt, nbxSearchTarget('street', said, MV.discBox(disc)), function (out) {
    var two = MV.afterDir(first, MV.pickRetry(out.hits, disc, dir, out.cutAt));
    settleHeldEnd(key, attempt, disc, two, two === first ? null : dir.street);
  });
}

/* The door's answer acted on, from the first question or the retry (`asked`,
 * the street the retry found it by, kept on the pin as `asked` and said on
 * /api/status as `endAsked`; null for the street as printed). The street and
 * not the door, and the phone printed a place for the stop: the place is
 * asked next, in the same disc (the owner, 17 Oct). */
function settleHeldEnd(key, attempt, disc, res, asked) {
  var now = endHold(key);
  if (!now || heldEndPin(now)) return;
  if (!res.at && res.why === 'nodoor' && placeOf(now)) {
    return searchHeldPlace(key, attempt, disc, asked);
  }
  // ...and with no place, or none found, the street itself when it is short
  // (searchHeldStreet, the owner's fault of 19 Oct).
  if (!res.at && res.why === 'nodoor') {
    return searchHeldStreet(key, attempt, disc, asked, END_WHY.nodoor);
  }
  if (!res.at) {
    return refuseHeldEnd(now, END_WHY[res.why] || 'no house number');
  }
  pinHeldEnd(now, res.at, 'server', asked);
}

/* ...the retry itself: ONE more question, the street less its type word, in
 * the same discBox, through endAsk (nbxCache first, the NucBox's down handled
 * as the first question's is). MV.afterRetry chooses which answer is acted
 * on: the retry's when it pinned or found the street, else the first's, whose
 * refusal the driver is told ("not inside the card's reach"). */
function searchHeldRetry(key, attempt, disc, again, first, firstHits, plan) {
  var said = nbxTerm(again.street);
  if (!said) return settleHeldEnd(key, attempt, disc, first, null);
  var target = nbxSearchTarget('street', said, MV.discBox(disc));
  endAsk(key, attempt, target, function (out) {
    var two = MV.pickRetry(out.hits, disc, again, out.cutAt);
    // Neither the street as printed nor without its type word: the street
    // index asked which street the name as read is (searchHeldNamed).
    if (NBX.streets && MV.nameWanted(first, firstHits, disc, two)) {
      return searchHeldNamed(key, attempt, disc, plan, first);
    }
    // A pin here is only ever the retry's own (the first had none, or no
    // retry was asked), so the street it was found by is the retry's.
    settleHeldEnd(key, attempt, disc, MV.afterRetry(first, two), again.street);
  });
}

/* ...and last, the door by the ONE street the NucBox's street index says the
 * name as read is (the owner's fault of 19 Oct, night: the Trip Planner's
 * "1106 <Name> Ln" read off a dark frame as "L106 <Nam..>" and filed "1106
 * <Nam..>"; the NucBox's search found nothing, there was no type word to leave
 * out, and GPS arrival never armed). Asked only when the street as printed,
 * and without its type word where it had one, is not inside the card's reach
 * (MV.nameWanted), and only with NUCBOX_STREETS set; never the public
 * geocoder. Two questions, each once, each through endAsk (nbxCache first, a
 * NucBox not answering handled as the first question's is):
 *
 *   1. the street index, /api/streets/named: the name as read (MV.nameAsked,
 *      the street less its house number) inside the disc's box. Its answer is
 *      a street only when exactly one street there can be that read
 *      (streets.js named: its own matcher, or a type lost and the last word
 *      cut short, CUT_KEEP); two near names are none, never the likelier.
 *   2. the NucBox's search, the house number and that street's own name
 *      (MV.nameRetry), held as any door is: hasDoor in pickInDisc, inside the
 *      disc, alone or agreeing — and to that street's name and type where it
 *      has one (pickRetry, retryFits), so a door on another street of a like
 *      name the search hands back is not taken.
 *
 * A pin is `by: 'server'` with the street it was found by kept as `asked`
 * (/api/status `endAsked`, "1106 <Name> Lane"). MV.afterRetry chooses as for
 * the type-word retry: the door, or the street found and not the door (the
 * place is then asked), else the first question's refusal stands. */
function searchHeldNamed(key, attempt, disc, plan, first) {
  var said = nbxTerm(MV.nameAsked(plan) || '');
  if (!said) return settleHeldEnd(key, attempt, disc, first, null);
  var target = streetTarget('named', { name: said, box: MV.discBox(disc) });
  endAsk(key, attempt, target, function (ans) {
    var p2 = MV.nameRetry(plan, ans);
    var said2 = p2 ? nbxTerm(p2.street) : null;
    if (!said2) return settleHeldEnd(key, attempt, disc, first, null);
    endAsk(key, attempt, nbxSearchTarget('street', said2, MV.discBox(disc)), function (out) {
      var two = MV.pickNamed(out.hits, disc, p2, out.cutAt);
      settleHeldEnd(key, attempt, disc, MV.afterRetry(first, two), p2.street);
    });
  }, function (body) {
    var a = streetAnswer('named', body);
    return a.error ? null : a;
  });
}

/* ...and the held end by its PLACE, the owner's decision of 17 Oct 2026, asked
 * only after the door search above found the street and not the door: the
 * NucBox's Nominatim, q= the place as read (MV.placeQuery) — the town never
 * sent, as it never is (map-view.js says why) — in the same discBox, and the
 * end only where MV.pickPlace says: a named feature, not a road, whose own
 * name is the place (MV.placeNamed), inside the held card's disc, alone or
 * agreeing. Pinned `by: 'place'`, which /api/status and the panel say. The
 * public geocoder is never asked, and with NUCBOX_SEARCH unset nothing here
 * runs at all (armHeldEnd). The fault it is for: an order's door "1000 <Road>
 * NW, <Town>" on a campus, the road on the NucBox and house 1000 not, the stop
 * named "<Something> Parking Deck" on the phone, and the delivered order held
 * because GPS arrival never armed. */
function searchHeldPlace(key, attempt, disc, asked) {
  var h = endHold(key);
  if (!h) return;
  var said = nbxTerm(MV.placeQuery(placeOf(h)) || '');
  if (!said) return searchHeldStreet(key, attempt, disc, asked, END_WHY.noplace);
  var target = nbxSearchTarget('q', said, MV.discBox(disc));
  endAsk(key, attempt, target, function (out) {
    var now = endHold(key);
    if (!now || heldEndPin(now)) return;
    var res = MV.pickPlace(out.hits, disc, placeOf(now), out.cutAt);
    if (!res.at) {
      return searchHeldStreet(key, attempt, disc, asked, END_WHY[res.why] || END_WHY.noplace);
    }
    pinHeldEnd(now, res.at, 'place');
  });
}

/* ...and last, the held end by its STREET, when the street is short: the
 * owner's fault of 19 Oct 2026. The Trip Planner gave "306 <Name> Ct, <Town>"
 * right; the NucBox's Nominatim holds the court and not house 306 (OSM maps a
 * subdivision's streets long before anyone adds its house numbers), so the
 * door search ended 'no house number', there was no place, and GPS arrival
 * never armed on an order delivered to that court.
 *
 * Asked only after the door search found the street and not the door
 * ('nodoor') and the place fallback found nothing or had nothing to ask, and
 * only with NUCBOX_STREETS set — never the public geocoder. ONE question,
 * through endAsk (nbxCache first, a NucBox not answering handled as the
 * first's): the street index's /api/streets/whole, the street's name as
 * printed (MV.nameAsked) inside the disc's box, which answers every street of
 * that name reaching into the box WHOLE, by its own matcher (streets.js
 * match: case, USPS abbreviations, a directional on one side) — a read that
 * needed the ocr rule is not the same name and is not used. A street is its
 * ways joined at shared nodes, so two courts of one name in two subdivisions
 * are two.
 *
 * Armed only when exactly ONE such street touches the held card's disc (a
 * street too long to send its shape counts as one: unknown is not none) and
 * its whole length is at most SHORT_STREET_M. Then the GPS arrives when a
 * usable fix is within the arrive radius of ANY point of the street's
 * polyline (pinMetres, MV.nearestOn: distance to the segment), with the same
 * DWELL, LEAVE and restaurant guard as a door (a pickup within
 * PICKUP_GUARD_M of any point of it disarms it). The pin is `by: 'street'`
 * (the panel's "● armed by street"), still door level, because a court of a
 * few hundred metres is where the car stops for that door and nowhere else.
 * Otherwise the earlier refusal (`why`) stands, unchanged.
 *
 * SHORT_STREET_M is 600 m, CHOSEN, not measured: no subdivision's geometry
 * is in the repository to fit it to. What it rests on: a cul-de-sac or court
 * is typically 100-400 m; at 600 m the farthest the car can be from the true
 * door and still be "on the street" is about 600 m + the arrive radius, and
 * LEAVE_M (300 m) is measured from the street too, so leaving means leaving
 * the street. A through road of a mile is an arterial and never arms so. */
var SHORT_STREET_M = 600;

function searchHeldStreet(key, attempt, disc, asked, why) {
  var h = endHold(key);
  if (!h) return;
  var plan = [asked, h.dropoff].map(function (t) {
    return typeof t === 'string' && t ? MV.searchPlan(t) : null;
  }).filter(function (pl) { return pl && MV.streetRetry(pl); })[0];
  var said = NBX.streets && plan ? nbxTerm(MV.nameAsked(plan) || '') : null;
  if (!said) return refuseHeldEnd(h, why);
  var target = streetTarget('whole', { name: said, box: MV.discBox(disc) });
  endAsk(key, attempt, target, function (ans) {
    var now = endHold(key);
    if (!now || heldEndPin(now)) return;
    var one = shortStreetIn(ans, disc);
    if (!one) return refuseHeldEnd(now, why);
    pinHeldEnd(now, one.at, 'street', asked);
    now.endPin.lines = one.lines;
    now.endPin.metres = one.metres;
    saveHold(now);
  }, function (body) {
    var a = streetAnswer('whole', body);
    return a.error ? null : a;
  });
}

/* The one short street of the index's answer that touches the disc, as
 * {at, lines, metres}, or null: the named check searchHeldStreet arms by. */
function shortStreetIn(ans, disc) {
  if (!ans || ['exact', 'dir', 'junk'].indexOf(ans.how) < 0) return null;
  var touching = ans.streets.filter(function (st) {
    return st.lines === null || st.lines.some(function (l) {
      return l.some(function (pt) {
        return MV.crowMiles(disc.at, { lat: pt[0], lon: pt[1] }) <= disc.miles;
      });
    });
  });
  if (touching.length !== 1) return null;
  var st = touching[0];
  if (!st.lines || st.metres > SHORT_STREET_M) return null;
  return { at: { lat: st.lines[0][0][0], lon: st.lines[0][0][1] },
           lines: st.lines, metres: st.metres };
}

/* How far `p` is from a pin, in metres: from its point, or for a street pin
 * (`lines`, searchHeldStreet) from the nearest point of the street. */
function pinMetres(p, pin) {
  if (pin && Array.isArray(pin.lines)) {
    var near = MV.nearestOn(pin.lines.map(function (l) {
      return l.map(function (pt) { return { lat: pt[0], lon: pt[1] }; });
    }), p);
    if (near) return near.miles * 1609.344;
  }
  return MV.crowMiles(p, pin) * 1609.344;
}

/* ---------- the held order's pickups, searched for by this server ----------
 *
 * The restaurant guard (pickupNearEnd) is only as good as the pickups it is
 * given, and until 3ca870a only Map view gave them (/api/held-pickup): with
 * Map view never opened on a hold the guard held nothing, and searchHeldEnd
 * armed a door next to the restaurant all the same — the case the guard is
 * there for (the 12 Oct replay, at PICKUP_GUARD_M). 3ca870a searched the Trip
 * Planner's pickups, so an order with no planner read — every DoorDash order,
 * and an Uber one whose planner the rig never saw — still left the guard
 * empty. THE OWNER'S DECISION, 18 Oct 2026: the server pins the held order's
 * restaurant itself, so the guard is always on.
 *
 * So when an order is held and NUCBOX_SEARCH is set, this server asks the
 * NucBox for each pickup address on record for it (pickupAsks): the Trip
 * Planner's pickups (MV.heldPickups: street with its town), the store's door
 * a planner or DoorDash's place popup filed on the hold (`fields.pickupAddr`),
 * the door DoorDash's stops card printed under the store's name (`pickupLine`,
 * carried onto the hold at ✓ Took), and an Uber card's "Store (<n> <street>)"
 * (searchPlan's bracket). Each exactly as the held end is asked
 * (searchHeldEnd): searchPlan's street in discBox round the HELD card's disc
 * (MV.discFor — a rough fix widened), chosen by pickInDisc, and the street
 * less its type word once more where the street as printed is not inside the
 * card's reach (MV.streetRetry, retryWanted, pickRetry, afterRetry), and
 * with a directional inside its name the other way where the street was found
 * inside and not the door (MV.dirRetry, dirWanted, afterDir). Map
 * view's own functions, so the page and the server keep one rule.
 *
 * DOOR LEVEL ONLY (pickupDoorPlan): an address with a house number, kept only
 * where pickInDisc finds that number (hasDoor, its own rule). Until the
 * owner's decision a planner pickup with no number was asked for its street
 * and any agreeing answer kept; a street is a mile of road, and a pin kept
 * along it withholds the GPS drop from whatever door happens to be within
 * PICKUP_GUARD_M of it — and is the circle visitPickups marks the restaurant
 * visited by. A pickup with no house number anywhere on record is not asked,
 * and /api/status says so (`pickupsWhy: 'no house number'`); Map view still
 * pins it as it always has, and posts it. A corner ("A & B") is the street
 * index's question, which this server does not ask. The store's NAME is never
 * asked: a chain's name inside a disc is whichever branch, the wrong
 * restaurant at the confidence of the right one.
 *
 * The position is kept as /api/held-pickup keeps one (keepPickupPin), `by:
 * 'server'` with the source it came from (`from`) and, when the type-word
 * retry found it, the street asked (`asked`): one path, so the two cannot
 * keep pickups two ways, and the newest PICKUP_PINS_MAX kept as before. The
 * FIRST valid pin for a pickup text wins, this server's or Map view's
 * (pickupPinFor): a text already pinned is not asked, and an answer that
 * lands after the page pinned it is dropped, as the end's is.
 *
 * The public geocoder is never asked; with NUCBOX_SEARCH unset nothing here
 * sends anything. ONE search per hold and pickup text (`pickSearch.asked`); a
 * failure or a timeout is asked once more after END_RETRY_MS, as the end's
 * is, and an answer that comes back after the hold changed is dropped. A
 * refusal is kept in memory by text (`pickSearch.why`) — a restart asks again
 * — and /api/status says how many pickups the guard holds and how each was
 * pinned (pickupState). With two orders in the car, or a trip and its Uber
 * add-ons, each order's own card is asked under that order, and the
 * planner's pickups (kept on the first-taken) land on the order whose card
 * names the store (keepPickupPin, pickupOwner). */
// One per order, by holdId: {asked, timers, why}.
var pickSearch = {};

/* The named check: a pickup text's search plan when it is a street with a
 * house number (searchPlan's door), else null. The one rule for "this pickup
 * may be asked", for the asking and for /api/status's reason. */
function pickupDoorPlan(q) {
  var plan = typeof q === 'string' && q ? MV.searchPlan(q) : null;
  return plan && plan.kind === 'street' && plan.door ? plan : null;
}

/* Every pickup address on record for this order that may be asked, as
 * [{q, from}], first source first: 'planner' (its Trip Planner's stops,
 * MV.heldPickups' `q`, the name visitPickups marks it by), the source a filed
 * `fields.pickupAddr` says ('planner', 'popup'; its 'card' is the card's
 * pickup below), and 'card' (DoorDash's printed door `pickupLine`, then the
 * card's pickup itself, which searchPlan reads as a door only in an Uber
 * "Store (<n> <street>)"). A text on it twice is asked once
 * (armHeldPickups' `asked`), under the first source. */
function pickupAsks(h) {
  var out = [];
  function add(q, from) {
    if (pickupDoorPlan(q)) out.push({ q: q, from: from });
  }
  if (h.planner) MV.heldPickups(h.planner.stops).forEach(function (p) { add(p.q, 'planner'); });
  var f = Assemble.fieldsOf(h).pickupAddr;
  if (f) add(f.value, f.from);
  add(h.pickupLine, 'card');
  add(h.pickup, 'card');
  return out;
}

/* The pin kept for this pickup text on any order in the car, or null: the
 * first valid one wins (keepPickupPin), and a text pinned is not asked. */
function pickupPinFor(q) {
  var hit = null;
  heldOrders(Date.now()).forEach(function (o) {
    (Array.isArray(o.pickupPins) ? o.pickupPins : []).forEach(function (p) {
      if (!hit && p.q === q) hit = p;
    });
  });
  return hit;
}

/* The hook, beside armHeldEnd: for each order after the list is written
 * (a ✓ Took among them, with its card's door), when a Trip Planner read lands
 * on one, and at boot. A no-op for a pickup text already asked about on that
 * order, or already pinned. */
function armHeldPickups(h) {
  if (!NBX.search || !h) return;
  var id = holdIdOf(h);
  var on = pickSearch[id] || (pickSearch[id] = { asked: {}, timers: [], why: {} });
  pickupAsks(h).forEach(function (a) {
    if (on.asked[a.q] || pickupPinFor(a.q)) return;
    on.asked[a.q] = true;
    searchHeldPickup(id, a, 1);
  });
}

// The order this search is still about, or null.
function pickHold(id) {
  return pickSearch[id] ? heldById(id, Date.now()) : null;
}

/* The per-order state of an order no longer on the list goes with it: its
 * end search and its timer, its pickup searches and theirs, and its arrival.
 * Called by setHeld, so every way an order leaves takes them. */
function forgetHoldsGone(list) {
  var ids = (list || []).map(holdIdOf);
  Object.keys(endSearch).forEach(function (id) {
    if (ids.indexOf(id) !== -1) return;
    if (endSearch[id].timer) clearTimeout(endSearch[id].timer);
    delete endSearch[id];
  });
  Object.keys(pickSearch).forEach(function (id) {
    if (ids.indexOf(id) !== -1) return;
    pickSearch[id].timers.forEach(clearTimeout);
    delete pickSearch[id];
  });
  Object.keys(arrivals).forEach(function (id) {
    if (ids.indexOf(id) === -1) delete arrivals[id];
  });
  // ...and the arrivals at its pickups (visitPickups).
  Object.keys(pickArrivals).forEach(function (k) {
    if (ids.indexOf(pickArrivals[k].holdId) === -1) delete pickArrivals[k];
  });
}

/* One pickup asked: `a` is pickupAsks' {q, from}. Nothing with no disc
 * round the held card (MV.discFor), which /api/status says (pickupsWhyOf).
 * As searchHeldEnd asks the end, and the street less its type word once more when the street as printed
 * is not inside the card's reach (searchPickupRetry). */
function searchHeldPickup(id, a, attempt) {
  var h = pickHold(id);
  if (!h) return;
  var plan = pickupDoorPlan(a.q);
  var disc = MV.discFor(h.card || null);
  var said = plan ? nbxTerm(plan.street) : null;
  if (!said || !disc) return;
  var target = nbxSearchTarget('street', said, MV.discBox(disc));
  pickupAsk(id, a, attempt, target, function (out) {
    var res = MV.pickInDisc(out.hits, disc, plan, out.cutAt);
    var again = MV.streetRetry(plan);
    if (again && MV.retryWanted(res, out.hits, disc)) {
      return searchPickupRetry(id, a, attempt, disc, again, res);
    }
    // ...and the street found inside and not the door: a directional inside
    // its name the other way (MV.dirRetry), as the held end asks it.
    var dir = MV.dirRetry(plan);
    if (dir && MV.dirWanted(res, out.hits, disc)) {
      var said2 = nbxTerm(dir.street);
      if (said2) {
        return pickupAsk(id, a, attempt, nbxSearchTarget('street', said2, MV.discBox(disc)),
          function (out2) {
            var two = MV.afterDir(res, MV.pickRetry(out2.hits, disc, dir, out2.cutAt));
            settleHeldPickup(id, a, two, two === res ? null : dir.street);
          });
      }
    }
    settleHeldPickup(id, a, res, null);
  });
}

/* ...the retry: ONE more question, the street less its type word, in the
 * same discBox, an answer kept only at the same door on the same street
 * (MV.pickRetry), and MV.afterRetry choosing which answer is acted on. */
function searchPickupRetry(id, a, attempt, disc, again, first) {
  var said = nbxTerm(again.street);
  if (!said) return settleHeldPickup(id, a, first, null);
  var target = nbxSearchTarget('street', said, MV.discBox(disc));
  pickupAsk(id, a, attempt, target, function (out) {
    settleHeldPickup(id, a, MV.afterRetry(first, MV.pickRetry(out.hits, disc, again, out.cutAt)),
                     again.street);
  });
}

/* One question for a pickup, answered from nbxCache or asked; `answered(out)`
 * only while the order is still held. A NucBox that does not answer is
 * 'NucBox down' for that text, and the whole search is asked once more, from
 * the top, after END_RETRY_MS. A text the page pinned while this was out is
 * not asked about here a second time: keepPickupPin keeps the first, the one
 * place that rule is. */
function pickupAsk(id, a, attempt, target, answered) {
  function go(out) {
    if (pickHold(id)) answered(out);
  }
  if (nbxCache.has(target)) return go(nbxCache.get(target));
  nbxAsk(target, function (err, body) {
    if (!err && !Array.isArray(body)) err = 'not a list';
    if (err) {
      if (!pickHold(id)) return;
      pickSearch[id].why[a.q] = 'NucBox down';
      if (attempt === 1) {
        pickSearch[id].timers.push(setTimeout(function () {
          searchHeldPickup(id, a, 2);
        }, END_RETRY_MS));
      }
      return;
    }
    var out = nbxHits(body);
    nbxRemember(target, out);
    go(out);
  });
}

/* The answer acted on: a door kept `by: 'server'`, or the refusal kept for
 * /api/status in pickInDisc's words (END_WHY, the end's). `asked` is the
 * street the type-word retry found it by, else null. */
function settleHeldPickup(id, a, res, asked) {
  var now = pickHold(id);
  if (!now) return;
  if (!res.at) {
    pickSearch[id].why[a.q] = END_WHY[res.why] || 'no house number';
    return;
  }
  keepPickupPin(now, res.at, a.q, { by: 'server', from: a.from, asked: asked });
}

/* What /api/status says of one order's pickups: how many the guard holds
 * (`pickupsPinned`), how each was pinned (`pickupsHow`, oldest first: `by`
 * 'server' or null for Map view's post, `from` the source this server asked,
 * `asked` the street when the type-word retry found it), and, with none
 * pinned, why (`pickupsWhy`): 'no house number' when no pickup on record has
 * one, 'no card fix' when the held card has no disc, else the last refusal
 * of the first text asked (END_WHY's words, or 'NucBox down'); null while
 * one is still being asked, or with NUCBOX_SEARCH unset, when this server
 * asks nothing and says nothing. */
function pickupState(h) {
  var pins = Array.isArray(h.pickupPins) ? h.pickupPins : [];
  return { pickupsPinned: pins.length,
           pickupsHow: pins.map(function (p) {
             return { by: p.by || null, from: p.from || null, asked: p.asked || null };
           }),
           pickupsWhy: pins.length ? null : pickupsWhyOf(h) };
}

function pickupsWhyOf(h) {
  if (!NBX.search) return null;
  var asks = pickupAsks(h);
  if (!asks.length) return 'no house number';
  if (!MV.discFor(h.card || null)) return 'no card fix';
  var on = pickSearch[holdIdOf(h)];
  var said = asks.map(function (a) { return on ? on.why[a.q] : null; }).filter(Boolean);
  return said.length ? said[0] : null;
}

/* Keep one of the held order's pickups, from Map view (/api/held-pickup) or
 * this server's own search: at most PICKUP_PINS_MAX, the newest, one per
 * position. `how` is this server's {by, from, asked}, or null for the page.
 *
 * ...ONE per pickup text: the first valid pin for a text wins (the end's
 * rule, /api/held-end), so a pin already kept for it — this server's door or
 * the page's — is not moved by a second opinion, and an arrival or a visit
 * already counted at it stands.
 *
 * ...and the guard asked again there and then. A door armed before its
 * restaurant was known may already have counted the car waiting at the
 * restaurant as an arrival — in the 12 Oct replay a door 50-75 m from the
 * restaurant "arrived" 1 time in 24 at today's 100 m, and 24 in 24 at the
 * 125 m before it — and gpsArrival only stops counting from the next beat. Left on the hold, that arrival is "arrived" on
 * /api/status for a door that is not armed, and should the guard stop holding
 * (a newer pickup pushing this one out of the PICKUP_PINS_MAX kept) the next
 * departure puts the order down on it. So a pickup that puts the armed door
 * inside the guard takes the arrival and the dwell with it. */
function keepPickupPin(h, at, q, how) {
  if (typeof q === 'string' && q && pickupPinFor(q)) return;
  // With two orders in the car, onto the order the pickup is (pickupOwner);
  // one that is nobody's stays where it was asked for, for the guard, which
  // reads every order's pins.
  if (typeof q === 'string' && q && heldOrders(Date.now()).length >= 2) {
    var own = entryOf(q, Date.now());
    if (own) h = own.h;
  }
  var was = null;
  var picks = (Array.isArray(h.pickupPins) ? h.pickupPins : []).filter(function (p) {
    if (p.lat === at.lat && p.lon === at.lon) { was = p; return false; }
    return true;
  });
  // ...named by the text it was searched for (`q`: MV.heldPickups' planner
  // line, or the card's door), which is what the GPS marks visited
  // (visitPickups). A pin with no name — a page from before the field — still
  // guards the door, and is never visited: there is no pickup to say it of. A
  // second opinion at the same position without a name keeps the name it had,
  // and who pinned it.
  var pin = { lat: at.lat, lon: at.lon };
  if (typeof q === 'string' && q) pin.q = q;
  else if (was && was.q) pin.q = was.q;
  var by = how || (was && was.by ? was : null);
  if (by) {
    pin.by = by.by;
    if (by.from) pin.from = by.from;
    if (by.asked) pin.asked = by.asked;
  }
  picks.push(pin);
  h.pickupPins = picks.slice(-PICKUP_PINS_MAX);
  // Every order's door, since the guard is every order's pickups (see
  // pickupNearEnd): a second order's restaurant can sit beside the first's.
  heldOrders(Date.now()).forEach(function (o) {
    var pin = heldEndPin(o);
    if (pin && pickupNearEnd(o, pin)) {
      delete o.arrivedAt;
      resetArrival(holdIdOf(o));
    }
  });
  saveHold(h);
}

/* ---------- the held order's pickups, visited -------------------------------
 *
 * The driver: stopping at the held order's restaurant should mark that pickup
 * done, and the panel's next stop, Map view's run and the "on your way" figure
 * move on to the dropoff by themselves. Until this the only way a pickup left
 * them was a planner read that no longer listed it, and Uber's planner keeps
 * a pickup until the driver swipes it in the app.
 *
 * So each held pickup pin that names its pickup (`q`, keepPickupPin) runs the
 * door's own rule (stepAt): inside ARRIVE_M + min(err, 25) for DWELL_MS, then
 * past LEAVE_M on LEAVE_FIXES good fixes. The pickup is marked on LEAVING,
 * not when the dwell is met, and the 12 Oct replay is why (385 min of fixes,
 * the stand-in for each order's restaurant being the longest still stop of
 * 45 s or more between its Took and its door; replayed outside the repo). Of
 * the three orders the drive can replay, two had their stand-in inside the
 * hold: order 1's Took was pressed while the car waited there, order 2's
 * stop was 6.2 min after its Took. Marked on leaving, they were marked 96 s
 * and 56 s after the car left (on 4 s beats; 90 s and 50 s on every fix).
 * Marked at the dwell, it would have been 20 s and 332 s BEFORE it left — the
 * panel saying "Dropoff" for five and a half minutes over a car still waiting
 * for the food. A stop late is the cheap error: the restaurant stays the next
 * stop for a minute or so of driving away from it. Order 3's Took came 7.5
 * min after the car left the longest stop before it, so the GPS has nothing
 * to mark there; that is what the planner's own word is for (plannerVisits).
 * A pin 50 or 75 m off the stand-in still visited in all 8 directions on both
 * orders; 100 m off, in 3 of 8 and 0 of 8. Every other still stop in those
 * holds was 1,987 m or more from the stand-in.
 *
 * Two pickups within SAME_SPOT_M of each other are visited together: two
 * stores in one plaza are one stop for the car, and parked at one it may be
 * outside the other's radius for the whole wait. 150 m is the owner's
 * figure, the guard's (PICKUP_GUARD_M), chosen and not measured.
 *
 * Visited is for good: a later planner read that still lists the pickup does
 * not take it back — the app keeps listing it until the swipe — and the
 * order's end is still the order's end. The result is on the order, and so
 * in holding.json (`pickups`); the dwell's live part is memory, as the
 * door's is, and an arrival is kept on the pickup like the door's so a
 * restart while waiting at the restaurant leaves with it. A journal row
 * (`kind: 'visit'`) says which, never where. Nothing is turned into minutes:
 * a visit moves a stop off the run and changes no time anywhere. */
var SAME_SPOT_M = 150;
// One per pin, by holdId and position: two pins are two circles.
var pickArrivals = {};

function freshArrival(id) {
  return { holdId: id, insideSince: null, lastFixAt: null, outCount: 0,
           skippedMs: 0, refusedFrom: null, refusedTo: null, silentMs: 0 };
}

function pickArrivalOf(h, pin) {
  var key = holdIdOf(h) + '\n' + pin.lat + ',' + pin.lon;
  return pickArrivals[key] || (pickArrivals[key] = freshArrival(holdIdOf(h)));
}

/* The order's own record of one pickup, by its planner line, made the first
 * time either a planner read or a pin names it: `{q}`, and once visited
 * `visited`, `visitedAt` and `by`. Its place in `h.pickups` is the index the
 * journal row gives, so it is never reordered. */
function pickupEntry(h, q) {
  if (!Array.isArray(h.pickups)) h.pickups = [];
  for (var i = 0; i < h.pickups.length; i++) if (h.pickups[i].q === q) return h.pickups[i];
  var e = { q: q };
  h.pickups.push(e);
  return e;
}

/* The one order in the car already holding a record of this pickup, as
 * {h, e}, or null — none, or (never made, but never guessed between) two. */
function entryOf(q, now) {
  var hit = null;
  var many = false;
  heldOrders(now).forEach(function (o) {
    (Array.isArray(o.pickups) ? o.pickups : []).forEach(function (e) {
      if (e.q !== q) return;
      if (hit) many = true;
      hit = { h: o, e: e };
    });
  });
  return many ? null : hit;
}

/* Whose pickup this is, by its planner line: {h, e}, or null for nobody's.
 * With one order in the car, that order's, its record made if it is new.
 * With two, the order that holds a record of it — made when it was the only
 * order, or by a planner read whose cues gave the stop to one order
 * (ownPickups' `of`, in plannerVisits) — and otherwise NOBODY's: a pickup no
 * cue gave an order is never filed under the first one, so its pin guards a
 * door and nothing is ever marked of it. */
function pickupOwner(q, now) {
  var orders = heldOrders(now);
  if (orders.length === 1) return { h: orders[0], e: pickupEntry(orders[0], q) };
  return entryOf(q, now);
}

/* Mark these pickups visited — [{h, e}] — write a row for each and save. The
 * row: {v, kind: 'visit', at, id, seq, holdId, pickup, by}, `pickup` the
 * index in that order's `pickups`. No address and no coordinate: what was
 * visited is in holding.json for as long as the order is, and the journal
 * holds only that one was and when. `id` is the order and the index, which
 * can be visited once, so syncKey's [kind, id, seq] is one row's. */
function markVisited(list, now, by) {
  var rows = [];
  var saved = [];
  list.forEach(function (x) {
    if (x.e.visited) return;
    x.e.visited = true;
    x.e.visitedAt = now;
    x.e.by = by;
    delete x.e.arrivedAt;
    delete x.e.after;
    var id = holdIdOf(x.h);
    var i = x.h.pickups.indexOf(x.e);
    rows.push(JSON.stringify({ v: 1, kind: 'visit', at: now, id: id + '#' + i, seq: now,
                               holdId: id, pickup: i, by: by }) + '\n');
    if (saved.indexOf(x.h) === -1) saved.push(x.h);
  });
  saved.forEach(saveHold);
  if (!rows.length) return;
  appendLines(rows.join(''), function (err) {
    if (err) console.error('journal: could not record a pickup visit: ' + err.message);
  });
}

/* One heartbeat, for the pickups: each named pin of each order in the car,
 * stepped by stepAt, and on leaving one, every pickup pinned within
 * SAME_SPOT_M of it marked visited with it — each under the order it is
 * (pickupOwner), and one that is nobody's not at all. */
function visitPickups(beat, now) {
  var orders = heldOrders(now);
  orders.forEach(function (h) {
    (Array.isArray(h.pickupPins) ? h.pickupPins : []).forEach(function (pin) {
      if (typeof pin.q !== 'string') return;
      var own = pickupOwner(pin.q, now);
      if (!own || own.e.visited) return;
      var step = stepAt(pickArrivalOf(h, pin), beat, now, pin, !!own.e.arrivedAt);
      if (step === 'arrive') {
        own.e.arrivedAt = now;
        saveHold(own.h);
      }
      if (step !== 'left') return;
      var here = [];
      orders.forEach(function (o) {
        (Array.isArray(o.pickupPins) ? o.pickupPins : []).forEach(function (p) {
          if (typeof p.q !== 'string') return;
          if (MV.crowMiles(p, pin) * 1609.344 > SAME_SPOT_M) return;
          var other = pickupOwner(p.q, now);
          if (other) here.push(other);
        });
      });
      markVisited(here, now, 'gps');
    });
  });
}

/* A Trip Planner read landing on the order: its pickups recorded, and one it
 * listed before and lists no longer marked visited, `by: 'planner'` — the
 * app's own word that the stop is behind the car.
 *
 * "No longer lists" means the list has MOVED PAST it: this read shows a stop
 * a read that listed the pickup showed after it (`after`). A read cut
 * short above the pickup — the screen's foot, a stop block that grew — does
 * not list it either, and that is not a visit; a pickup marked by that would
 * put the dropoff next with the restaurant still ahead, and visited is for
 * good. A read that lists the pickup leaves a visited one visited.
 *
 * ...and only off a read that shows the list from its TOP (`top`: the
 * sighting's page.top, planner_ends' title-over-the-first-stop, found by the
 * read's `at`, Assemble.pageOf). A read scrolled down shows the stops after
 * the first pickup without it, which is the shape of "moved past" exactly;
 * it marks nothing. A planner line with no sighting of its read is not
 * known to show the top, and marks nothing either.
 *
 * With two orders in the car each pickup is recorded under the order its
 * cues give it (ownPickups' `of`), and one they give neither is recorded
 * under nobody (pickupOwner). */
function stopKey(s) {
  if (!s || !s.kind) return null;
  var k = s.kind === 'pickup' ? MV.pickupKey(s) : (s.line || s.street || s.name || null);
  return k ? s.kind + '\n' + k : null;
}

function plannerVisits(h, stops, now, top, heldWas) {
  var keys = stops.map(stopKey);
  var listed = [];
  var orders = heldOrders(now);
  stops.forEach(function (s, i) {
    var q = s && s.kind === 'pickup' ? MV.pickupKey(s) : null;
    if (!q) return;
    listed.push(q);
    var own = orders.length < 2 ? h : (s.of ? heldById(s.of, now) : null);
    var had = entryOf(q, now);
    var e = had ? had.e : own ? pickupEntry(own, q) : null;
    if (!e || e.visited) return;
    // Added to, never cut: a read showing less after the pickup is a read
    // cut shorter, not evidence that what it no longer shows is gone.
    e.after = (e.after || []).concat(keys.slice(i + 1).filter(function (k) {
      return k && (e.after || []).indexOf(k) === -1;
    }));
  });
  // Written when this read changed the orders — its stops, a pickup's record,
  // the stops seen after one — and not otherwise. `heldWas` is the list as
  // text before the caller put this read's stops on the order. It wrote
  // holding.json on every planner line, and the scanner reads the planner on
  // its own as often as SCREEN_AUTO_EVERY (rpi/scan_pi.py, 10 s) while an
  // order is held: the same bytes onto the SD card, over and over.
  if (JSON.stringify(scanner.held) !== heldWas) saveHold(h);
  if (!top) return;
  var gone = [];
  orders.forEach(function (o) {
    (Array.isArray(o.pickups) ? o.pickups : []).forEach(function (e) {
      if (!e.visited && listed.indexOf(e.q) === -1
          && (e.after || []).some(function (k) { return keys.indexOf(k) !== -1; })) {
        gone.push({ h: o, e: e });
      }
    });
  });
  markVisited(gone, now, 'planner');
}

/* One heartbeat. Returns what the panel is told on that beat: whether the car
 * is at a held order's dropoff now. Puts an order down on the departure from
 * its own door — each order by its own pin and its own arrival, so leaving
 * one door puts down that order and no other. */
function gpsArrival(beat, now) {
  var at = false;
  heldOrders(now).slice().forEach(function (h) {
    if (arriveOne(h, beat, now)) at = true;
  });
  return at;
}

/* One beat's step at one pin, for whatever stands there — a held order's door
 * (arriveOne) or one of its pickups (visitOne): ONE rule for "the car stopped
 * here, then left", so a door and a restaurant cannot come to mean two things
 * by it. `arrived` is whether that place's arrival is already counted.
 * Returns null when the beat brings no fix to count, else what this fix did:
 *   'out'    outside the arrive radius (the dwell, if any, is reset)
 *   'in'     inside it, the dwell not yet met
 *   'arrive' inside it, and the dwell met on this fix
 *   'at'     arrived before, and still within LEAVE_M
 *   'going'  arrived before, and past LEAVE_M on fewer than LEAVE_FIXES
 *   'left'   arrived before, and past LEAVE_M on LEAVE_FIXES in a row
 * The numbers are the 12 Oct replay's, at the head of this section. */
function stepAt(arrival, beat, now, pin, arrived) {
  var fix = countableFix(beat, now, arrival);
  if (!fix) return null;
  var gap = arrival.lastFixAt === null ? Infinity : fix.at - arrival.lastFixAt;
  // A gap the gate's refusals filled: no silence in it over GAP_MS, from the
  // last counted fix through the run to this one, and no longer than
  // REJECTED_GAP_MS in all.
  var refused = arrival.refusedTo !== null && gap <= REJECTED_GAP_MS
    && Math.max(arrival.silentMs, fix.at - arrival.refusedTo) <= GAP_MS;
  arrival.lastFixAt = fix.at;
  arrival.refusedFrom = arrival.refusedTo = null;
  arrival.silentMs = 0;
  var metres = pinMetres(fix, pin);
  if (!arrived) {
    var within = ARRIVE_M + Math.min(fix.err, ARRIVE_ERR_CAP_M);
    if (metres > within) { arrival.insideSince = null; return 'out'; }
    if (arrival.insideSince === null || (gap > GAP_MS && !refused)) {
      arrival.insideSince = fix.at;
      arrival.skippedMs = 0;
    } else if (gap > GAP_MS) {
      arrival.skippedMs += gap;       // inside on both sides; not counted
    }
    return fix.at - arrival.insideSince - arrival.skippedMs < DWELL_MS ? 'in' : 'arrive';
  }
  if (metres <= LEAVE_M) { arrival.outCount = 0; return 'at'; }
  arrival.outCount += 1;
  return arrival.outCount < LEAVE_FIXES ? 'going' : 'left';
}

function arriveOne(h, beat, now) {
  var arrival = arrivalOf(holdIdOf(h));
  var pin = heldEndPin(h);
  if (!pin || pickupNearEnd(h, pin) || notOneCustomer(h)) return false;
  var step = stepAt(arrival, beat, now, pin, !!h.arrivedAt);
  if (step === 'arrive') {
    h.arrivedAt = now;
    saveHold(h);   // the arrival survives a restart in the driveway
    return true;
  }
  if (step === 'at') return true;
  if (step !== 'left') return false;
  putDown(now, 'gps', function () {
    var left = holding(now);
    var said = { gpsDrop: { at: now, saidForMs: GPS_DROP_SAID_MS } };
    // With an order left in the car the panel is told which one went and what
    // is left, on the same message: a gpsDrop alone means "nothing held".
    if (left) {
      said.gpsDrop.holdId = holdIdOf(h);
      said.gpsDrop.pay = numOrNull(h.pay);
      said.holding = heldForPanel(left);
      said.orders = ordersForPanel(now);
    }
    broadcast(said);
  }, [h]);
  return false;
}

/* Put orders in the car down, and write a drop row for each: the one path both
 * Drop (/api/delivered) and the GPS take. `by` is 'gps' for the second and
 * absent from the row for a press, so rows written before this are the shape
 * they always were. `which` is the orders to put down, as heldOrders gave
 * them; absent, the first-taken — the only one there is while one is all the
 * car carries. `done(wasHolding)`. See /api/delivered for the row. */
function putDown(now, by, done, which) {
  // heldOrders(), not the raw list, and asked BEFORE the list is rewritten.
  var live = heldOrders(now);
  // How many orders were in the car at the moment: a drop row written with
  // two held says so (`carried: 2`), because its `at - acceptedAt` is then an
  // elapsed time for the named order only if the press named the right one.
  var carried = live.length;
  var dropped = (which || live.slice(0, 1)).filter(function (h) {
    return live.indexOf(h) !== -1;
  });
  // ...and, asked for no order in particular, one with no stated time goes as
  // well: it is never counted as carried, and Drop always cleared the slot.
  setHeld(scanner.held.filter(function (h) {
    return dropped.indexOf(h) === -1 && (which || holdEnds(h) !== null);
  }));
  if (!dropped.length) return done(false);
  var rows = dropped.map(function (d) {
    var row = { v: 1, kind: 'drop', at: now, id: d.id, seq: now,
                acceptedAt: d.acceptedAt };
    if (by) row.by = by;
    if (carried >= 2) row.carried = carried;
    return JSON.stringify(asAddOnRow(row, d)) + '\n';
  });
  appendLines(rows.join(''), function (err) {
    if (err) console.error('journal: could not record a drop: ' + err.message);
    done(true);
  });
  // ...and an address waiting to be someone's is dropped if one of the orders
  // it was waiting between has gone (Assemble.retryUnowned).
  retryPool();
}

/* The offer as Advice.stack has to see it: timed the way the HELD job is timed.
 *
 * `stack` reads `offer.minutes`, and the two sides of the comparison were not
 * the same quantity. The held job is stored with `billedMinutes` where it has
 * one — the driver's own pad and shopping allowance included — and the new
 * offer arrived as the reading, whose `minutes` is what the CARD printed. So a
 * shop order was compared against a ride's worth of clock.
 *
 * Measured on a real pair: a $22.00 shop order billed at 95 minutes, an
 * identical card offered against it. Timed off the card the panel draws a
 * worst case of $18.86/hr over 95-140 minutes; timed the way the held job is
 * timed it is $13.89/hr over 95-190. The floor was overstated by 36% on the
 * one line that exists to say whether a second job is worth taking.
 *
 * And on a delivery card it was not overstated, it was absent. Uber and
 * DoorDash state a deadline and no duration, so `minutes` is null there,
 * `stack` returns null at its own guard, and the line said nothing at all —
 * on the whole of that half of a shift, with nothing on the screen to say a
 * question had been asked and not answered.
 *
 * `billedMinutes` and nothing else. A fallback to `cardMinutes` was written
 * here and taken out again: rate() sets both from the same computation, so
 * whenever the first is absent the second is too — measured on a card with no
 * pay and on one with no time, where `ready` is false and both come back null.
 * A second source that can never answer when the first could not is a branch
 * no input reaches, and this project deletes those rather than leaving them to
 * look like they are protecting something.
 *
 * A reading with neither is left exactly as it arrived, which is what it was
 * before this function existed: `stack` has its own guard and returns null. */
function timedLikeTheHeldJob(read) {
  if (!read) return read;
  var billed = read.billedMinutes;
  if (typeof billed !== 'number' || !isFinite(billed)) return read;
  if (billed === read.minutes) return read;
  return Object.assign({}, read, { minutes: billed });
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
/* The order in the car as the stream describes it to the panel: what Map view
 * pins and the stack line weighs. One shape, said from three places — a
 * reading (withStack), the mark reply that put the order in the car, and an
 * address the ⌖ press filed onto it — because the page's map draws the held
 * end from whichever of them spoke last, and two of them used not to say it at
 * all: see the dropoff branch in startScanner and /api/offers/mark. */
/* The GPS drop's state for the order in the car, in the three fields the
 * panel's in-car line says it from (live.html, gpsDropSaid): whether a
 * door-level pin is on it, whether the GPS has seen the car arrive there, and,
 * when it is not armed, why — a pin next to one of its pickups (pickupNearEnd),
 * a card that does not say one customer (notOneCustomer), or this server's
 * refusal of the dropoff text it still names (searchHeldEnd). And a fourth,
 * `visited`, the pickups behind the car.
 * ONE function, for /api/status, heldForPanel and the beat, so the status link
 * and the panel cannot give two answers about one pin. */
function heldEndState(h) {
  var pin = heldEndPin(h);
  return { endPinned: !!pin, arrived: !!h.arrivedAt,
           // ...who pinned it: 'server' (the door, searchHeldEnd), 'place'
           // (its place, searchHeldPlace), 'street' (a short street,
           // searchHeldStreet), or null for Map view's post. Here and not on
           // /api/status alone, so the panel's in-car line can say an end
           // pinned by its place is ("● armed by place").
           endBy: pin ? (pin.by || null) : null,
           // ...and where, so Map view draws the server's pin as D in place
           // of its own search's refusal (a street pin's point is its first
           // node). Null with no pin.
           endAt: pin ? { lat: pin.lat, lon: pin.lon } : null,
           endWhy: pin
             ? (pickupNearEnd(h, pin) ? 'door next to the pickup' : notOneCustomer(h))
             : h.endWhyFor === endTextOf(h) ? (h.endWhy || null) : null,
           // ...and its pickups the car has called at (visitPickups,
           // plannerVisits), by planner line (MV.pickupKey): the panel's next
           // stop, Map view's run and the figure's stops leave them out. On
           // the same three messages, for the same reason: a visit happens
           // between offers.
           visited: (Array.isArray(h.pickups) ? h.pickups : []).filter(function (e) {
             return e.visited;
           }).map(function (e) { return e.q; }) };
}

// A batched trip's door count (Assemble.batchPlan, file), or null for an
// order of one door. Two at least, or it is no batch.
function batchDrops(h) {
  return h && h.batch === true && Array.isArray(h.drops) && h.drops.length >= 2
    ? h.drops.length : null;
}

function heldForPanel(held) {
  return held
    ? Object.assign({ pay: held.pay, minutes: held.minutes, dropoff: held.dropoff || null,
        // ...and the place the phone printed for that stop, which Map view
        // asks for when the door is not on the NucBox (map-view.js pickPlace).
        place: placeOf(held),
        // What /api/held-end is told the pin is for. See holdIdOf.
        holdId: holdIdOf(held),
        // Its card's fix and size, so Map view can check this order's end
        // against them — see cardOf.
        card: held.card || null,
        // ...and, on a batched trip (Assemble.batchPlan), how many doors it
        // has: the panel's "2 drops" beside the pay. Null otherwise.
        drops: batchDrops(held) },
        // ...and the GPS drop's state, which the in-car line on the panel
        // says. It was on /api/status alone — fetched once, at load — so a
        // panel left open never learned that a pin had armed or been refused.
        heldEndState(held))
    : null;
}

function withStack(read, now) {
  if (!read || !read.ready) return read;
  var held = holding(now);
  read.holding = heldForPanel(held);
  // The order in the car, on the phone again: no pair to weigh, and the panel
  // says what it is. See heldOwnCard. Any order in the car, first-taken first.
  var own = heldOrders(now).filter(function (h) {
    return heldOwnCard(h, read, now, true);
  })[0];
  read.heldCard = own ? holdIdOf(own) : null;
  // Against every order in the car while carrying two is on (Stage 6,
  // Advice.stackMany), and the panel says which: "with ① + ②". With one
  // order that is stack() to the byte.
  read.stack = held && !read.heldCard
    ? Advice.stackMany(pairedWith(now, held), addOnAsCarded(timedLikeTheHeldJob(read)),
                       { target: read.target, band: read.band,
                         costPerMile: read.costPerMile }, now)
    : null;
  // Carrying two OFF with two in the car — a holding.json written while it
  // was on, read back at boot (MAX_HELD_FILE) — is weighed against the first
  // alone, as before Stage 6, and the line still says so ("vs ① only").
  if (read.stack && !carryingTwo(now) && heldOrders(now).length >= 2) read.stack.vsFirst = true;
  // ...and whether the offer's pickup is the store of one of those orders
  // (sameStoreOf): its holdId and its number on the line. Off the offer LINE,
  // which carries the doors and the fix a reading does not, and only while
  // that line is this reading's card (offerIsReading): a new card's reading
  // arrives before its line, and the store of the card before is not said
  // under it. On the stack, so it goes when the pair line goes.
  if (read.stack && offerIsReading(scanner.offer, read)) {
    var same = sameStoreOf(pairedWith(now, held), scanner.offer);
    if (same) {
      read.stack.sameStore = same.holdId;
      read.stack.sameStoreN = same.n;
    }
    // ...and the on-time hint, said beside the pair line (onTimeHint): asked
    // here, answered on a later reading of the same card once it is in.
    var ot = onTimeHint(scanner.offer, now);
    if (ot && ot.onTime) {
      read.stack.onTime = ot.onTime;
      if (ot.lateMin) read.stack.lateMin = ot.lateMin;
    } else if (ot && typeof ot.offWayMi === 'number') {
      read.stack.offWayMi = ot.offWayMi;
    }
  }
  if (carryingTwo(now)) {
    read.orders = ordersForPanel(now);
    read.unowned = Assemble.unowned(assembly);
  }
  return read;
}

/* The orders an offer is weighed against, first-taken first: every one in
 * the car while carrying two is on, and otherwise the first-taken alone, as
 * it was before the list — so with the flag off the pair line and the pair
 * row are what they were, whatever holding.json brought back. `held` is
 * holding(now), which the callers have already asked. */
function pairedWith(now, held) {
  return carryingTwo(now) ? heldOrders(now) : (held ? [held] : []);
}

/* A reading of an Uber add-on card, typed as one for Advice.stackMany.
 * The screen is on the OFFER LINE (scan_pi.emit_offer, OP.screen_type off the
 * card's whole text) and not on the reading, whose text is cut to 200
 * characters; so it is taken from the card on record, and only when this
 * reading IS that card — the same pay to the cent, card minutes and miles
 * (Assemble.cardSeen, the figures heldOwnCard recognises a card by). A
 * reading not proven to be that card is weighed as an ordinary offer, which
 * is the WIDER range: an add-on's shortest time is the longer one. Only
 * stackMany with two orders reads it (an add-on with one is drawn as it
 * always was). */
function addOnAsCarded(read) {
  var o = scanner.offer;
  if (!read || !o || !isAddOnCard(o) || !carryingTwo(Date.now())) return read;
  var c = Assemble.cardSeen(o, false), r = Assemble.cardSeen(read, true);
  if (!c || !r || c.pay === null || r.pay === null
      || Math.round(c.pay * 100) !== Math.round(r.pay * 100)
      || c.minutes !== r.minutes || c.miles !== r.miles) return read;
  return Object.assign({}, read, { screen: 'uber.addon' });
}

/* ---------- the same store as an order in the car --------------------------
 *
 * The owner's decision of 18 Oct 2026: an offer whose pickup is the same
 * restaurant as an order in the car is SAID so on the pair line — "same store
 * as ①", "same store as in car" with one — and nothing else changes: not the
 * verdict, not the state, not the range, not the pair row's arithmetic. The
 * rule is Assemble.samePickup (the door when both sides have one, quadrant
 * and type and one OCR look-alike tolerated; the name only when it is
 * distinctive and the two pickups are proven within half a mile).
 *
 * WHY HERE AND NOT ON THE PANEL. Three of the doors the rule reads live on
 * this side only — a hold's tapped `fields.pickupAddr`, its Trip Planner's
 * pickups (kept on the first order) and the pins this server keeps for them
 * — and the pair row is written here, so the record says which order the
 * offer shared a store with (`sameStore: <holdId>`, ids only, never the
 * store) under the same rule the glass used. The panel draws what it is
 * sent, as it draws the range.
 *
 * Against the orders the pair line weighs the offer against (pairedWith):
 * the note sits on that line and names one of ITS orders. `orders` is that
 * list, first-taken first; the first that shares the store is named. Never
 * the offer against its own hold (the held card come back is not paired). */
function sameStoreOf(orders, offer) {
  if (!offer || !orders || !orders.length) return null;
  var stops = orders[0] && orders[0].planner && Array.isArray(orders[0].planner.stops)
    ? orders[0].planner.stops : [];
  var mine = Assemble.pickupSide(offer, null, null);
  for (var i = 0; i < orders.length; i++) {
    var h = orders[i];
    if (!h || h.id === offer.id) continue;
    var side = Assemble.pickupSide(h, stops, holdIdOf(h));
    var by = Assemble.samePickup(side, mine, pickupsApartFn(side, offer));
    if (by) return { holdId: holdIdOf(h), n: i + 1, by: by };
  }
  return null;
}

/* Whether the offer on record is the card this reading is of: the pay to the
 * cent and the miles, which emit and emit_offer take off the same figures —
 * the rule live.html's onRecordIs holds the map's answer to. Not minutes: a
 * delivery card's count down between the two. */
function offerIsReading(o, read) {
  return !!o && !!read && typeof o.pay === 'number' && typeof read.pay === 'number'
    && Math.round(o.pay * 100) === Math.round(read.pay * 100)
    && (o.miles === undefined ? null : o.miles) === (read.miles === undefined ? null : read.miles);
}

/* The name rule's bound: how far apart the held store and the offer's pickup
 * can be, in miles, by what is PROVEN — or null. The held store's position is
 * a pin this server keeps for one of its own planner pickups (pickupPins, by
 * MV.pickupKey; any order's list, since with one order a pin stays where it
 * was asked); the offer's is its card's fix, which the gate passed
 * (MV.cardFix), and the drive to the pickup the card printed
 * (`toPickupMiles`) plus the fix's own error. A road is never shorter than
 * the straight line, so the pickup is inside that circle, and the sum is an
 * upper bound by the triangle inequality. Not slack for the car's motion
 * between the platform's figure and the fix: seconds, at most a few hundred
 * feet, and unmeasured (as MV.cardYardstick says). No pin, no fix or no
 * approach leg: null, and the name decides nothing. A function, so it is
 * worked out only when the names have already matched. */
function pickupsApartFn(side, offer) {
  return function () {
    var fix = MV.cardFix(offer).at;
    var leg = offer && offer.toPickupMiles;
    if (!fix || typeof leg !== 'number' || !isFinite(leg) || leg < 0) return null;
    var keys = (side.stops || []).map(MV.pickupKey).filter(Boolean);
    var err = typeof offer.gpsErr === 'number' && isFinite(offer.gpsErr) ? offer.gpsErr : 0;
    var best = null;
    heldOrders(Date.now()).forEach(function (o) {
      (Array.isArray(o.pickupPins) ? o.pickupPins : []).forEach(function (p) {
        if (keys.indexOf(p.q) === -1) return;
        var d = MV.crowMiles(fix, p) + leg + err / 1609.344;
        if (best === null || d < best) best = d;
      });
    });
    return best;
  };
}

/* Every order in the car as the panel draws it: heldForPanel's shape, with its
 * number (① first-taken), its app, and whether it is an add-on and to which.
 * Said beside `holding` (the first) only while carrying two is on. */
function ordersForPanel(now) {
  var list = heldOrders(now);
  // The Trip Planner's stops are kept on the first-taken order (the planner
  // branch in startScanner files them through holding()), and are the
  // panel's `heldPlan`.
  var stops = list[0] && list[0].planner && Array.isArray(list[0].planner.stops)
    ? list[0].planner.stops : [];
  return list.map(function (h, i) {
    var o = Object.assign(heldForPanel(h), { n: i + 1, app: h.app || null,
                                             addOn: !!h.addOn, of: h.of || null,
                                             // ...and the cue its end was
                                             // filed on (dropoffArrived).
                                             cue: h.endCue || null },
                          // ...and its pickups as the guard holds them, each
                          // order its own (pickupState).
                          pickupState(h));
    // With two in the car, where on that planner this order's end is
    // (planAt): Map view runs the car through both orders in the planner's
    // order only when it places both ends (MV.heldRuns). Absent with one,
    // whose shape is unchanged.
    if (list.length >= 2) o.planAt = planAtOf(stops, h);
    return o;
  });
}

/* The one dropoff stop of a Trip Planner that is this order's end, by its
 * index, or null: the stop on the same street as the order's end as it
 * stands (Assemble.sameStreet — the street before the first comma, case,
 * commas and spacing ignored, the rule plannerPickup and elimination stand
 * on), and only when exactly one stop is. Asked when the orders are sent,
 * against the end as it stands then, so an end filed after the planner was
 * read is asked again rather than remembered from before it. */
function planAtOf(stops, h) {
  if (!h || !h.dropoff) return null;
  var at = [];
  stops.forEach(function (s, i) {
    if (s && s.kind === 'dropoff' && Assemble.sameStreet(s.line || s.street, h.dropoff)) {
      at.push(i);
    }
  });
  return at.length === 1 ? at[0] : null;
}

/* ---------- on time for both: the owner's decision of 20 Oct 2026 ----------
 *
 * "Could the NucBox give an idea of the time? If time can't be determined,
 * distance out of the way is a reasonable place to start as well" — a simple
 * call on the card, when it can be worked out, that taking the second order
 * still delivers both on time. AUDITS.md records the decision: the NucBox
 * router's (OSRM's) own DRIVE TIMES are allowed for this one hint, narrowing
 * the Settled refusal of minutes for this use only. Still no pace, no minutes
 * from distance, and nothing here moves the verdict, the state or the range.
 *
 * Asked only with ONE order in the car and one offer on the glass, and only
 * when every point is pinned: the car (the offer card's own fix, as the
 * detour starts from it), the held order's pickup while the car has not
 * called there (one, from its kept pins; a pickup on record with no pin is
 * no answer), its end (the door-level pin GPS arrival arms on), and the
 * offer's pickup and dropoff, each searched here on the NucBox at door
 * level inside the offer card's disc (offerPin). And both deadlines: the
 * held order's Trip Planner "Expected by" for its dropoff stop (planAtOf),
 * else its card's deliverBy; the offer's deliverBy, else its own card
 * minutes from now, which is Uber's promise for it.
 *
 * Then at most three orders of the stops are asked of the router, the
 * sensible ones and no others:
 *   pickup still ahead   A-pick A-drop B-pick B-drop | A-pick B-pick A-drop
 *                        B-drop | B-pick A-pick A-drop B-drop
 *   food in the car      A-drop B-pick B-drop | B-pick A-drop B-drop |
 *                        B-pick B-drop A-drop
 * each arrival the sum of the router's leg times plus PICKUP_ALLOW_S for
 * every pickup stop before it. 'both' when some order reaches each drop by
 * its deadline; otherwise the order least late in all, said by whichever of
 * the two is later ('late1' the held order, 'late2' the offer) and by how
 * many whole minutes, rounded up. Null when anything cannot be had.
 *
 * With every pin the extra road distance needs and no deadline (or a router
 * that gave no times), `offWayMi`: road(car → B-pick → A-drop) less
 * road(car → A-drop), with the held pickup in front when it is still ahead
 * and the new pickup either side of it, the shorter. NEVER through where the
 * new job ends (Settled: "Do not widen the detour"). The card's own way line
 * (live.html showWay) already says this figure from the same roads, so the
 * panel draws this one only where that line is not up. */

// The time allowed at each pickup for the food, in seconds. CHOSEN, NOT
// MEASURED: no restaurant wait is on record anywhere in this repository.
var PICKUP_ALLOW_S = 5 * 60;
// How long a pair row waits for a hint still being asked, then is written
// with `onTime: null` (ms).
var ONTIME_WAIT_MS = envNumber('ONTIME_WAIT_MS', 4000);
// A road figure this far below zero is the router choosing different roads
// (the detour figure's own bound, map-view.js).
var ONTIME_NEG_MI = 0.05;

var offerPins = {};   // offer id -> { pickup: pin|null|undefined, dropoff: ... }
var onTimes = {};     // inputs key -> { hint, waiters } (hint undefined while asked)
var ONTIME_KEEP = 32;

function onTimeKeep(map, key, val) {
  map[key] = val;
  var keys = Object.keys(map);
  if (keys.length > ONTIME_KEEP) delete map[keys[0]];
}

/* One side of the offer pinned at door level inside its card's disc, or null
 * where it cannot be; undefined while asked. Asked once per offer and side. */
function offerPin(offer, side) {
  var on = offerPins[offer.id];
  if (!on) {
    on = { pickup: undefined, dropoff: undefined };
    onTimeKeep(offerPins, offer.id, on);
  }
  if (on[side] !== undefined || on[side + 'Asking']) return on[side];
  var text = side === 'pickup' ? (offer.pickupLine || offer.pickup) : offer.dropoff;
  var plan = text ? MV.searchPlan(text) : null;
  var disc = MV.discFor(cardOf(offer));
  var said = plan && plan.kind === 'street' && plan.door ? nbxTerm(plan.street) : null;
  if (!NBX.search || !said || !disc) {
    on[side] = null;
    return null;
  }
  var target = nbxSearchTarget('street', said, MV.discBox(disc));
  var settle = function (out) {
    on[side + 'Asking'] = false;
    var res = out ? MV.pickInDisc(out.hits, disc, plan, out.cutAt) : null;
    on[side] = res && res.at ? { lat: res.at.lat, lon: res.at.lon } : null;
    onTimeAgain(offer);
  };
  if (nbxCache.has(target)) {
    settle(nbxCache.get(target));
    return on[side];
  }
  on[side + 'Asking'] = true;
  nbxAsk(target, function (err, body) {
    if (err || !Array.isArray(body)) return settle(null);
    var out = nbxHits(body);
    nbxRemember(target, out);
    settle(out);
  });
  return undefined;
}

// Minutes since midnight as the nearest such moment to `now` (ms).
function dueAt(minOfDay, now) {
  if (typeof minOfDay !== 'number' || !isFinite(minOfDay)) return null;
  var d = new Date(now);
  d.setHours(0, 0, 0, 0);
  var t = d.getTime() + minOfDay * 60000;
  if (t < now - 12 * 3600000) t += 86400000;
  else if (t > now + 12 * 3600000) t -= 86400000;
  return t;
}

/* What the hint is worked out from, or { none: true } when it cannot be, or
 * { pending: true } while the offer's pins are still being asked. */
function onTimeInputs(offer, now) {
  var orders = heldOrders(now);
  if (orders.length !== 1 || !offer || typeof offer.id !== 'string') return { none: true };
  var h = orders[0];
  if (h.id === offer.id) return { none: true };
  var car = MV.cardFix(offer).at;
  var aDrop = heldEndPin(h);
  if (!car || !aDrop) return { none: true };
  var listed = Array.isArray(h.pickups) ? h.pickups : [];
  var visited = listed.filter(function (e) { return e.visited; }).map(function (e) { return e.q; });
  var ahead = listed.filter(function (e) { return !e.visited; }).map(function (e) { return e.q; });
  var pins = (Array.isArray(h.pickupPins) ? h.pickupPins : []).filter(function (p) {
    return p.q && visited.indexOf(p.q) === -1;
  });
  // A pickup ahead with no pin, or more than one ahead: not a run to time.
  if (pins.length > 1 || ahead.some(function (q) {
    return !pins.some(function (p) { return p.q === q; });
  })) return { none: true };
  var bPick = offerPin(offer, 'pickup');
  var bDrop = offerPin(offer, 'dropoff');
  if (bPick === undefined || bDrop === undefined) return { pending: true };
  var stops = h.planner && Array.isArray(h.planner.stops) ? h.planner.stops : [];
  var at = planAtOf(stops, h);
  var aDue = dueAt(at !== null && stops[at] ? stops[at].expectedBy : null, now);
  if (aDue === null) aDue = dueAt(h.deliverBy, now);
  var bDue = dueAt(offer.deliverBy, now);
  if (bDue === null && typeof offer.minutes === 'number' && isFinite(offer.minutes)
      && offer.minutes > 0) bDue = now + offer.minutes * 60000;
  var pt = function (p) { return p ? { lat: p.lat, lon: p.lon } : null; };
  return { car: pt(car), aPick: pins.length ? pt(pins[0]) : null, aDrop: pt(aDrop),
           bPick: pt(bPick), bDrop: pt(bDrop), aDue: aDue, bDue: bDue };
}

/* One route question of the router, ours alone: the leg times and metres
 * (no shape), or null for any answer that is not a route, a refusal, or a
 * point moved past the detour's SNAP_MI to reach a road. */
function roadLegs(pts, done) {
  var target = NBX.route + '/route/v1/driving/' + pts.map(function (p) {
    return p.lon.toFixed(6) + ',' + p.lat.toFixed(6);
  }).join(';') + '?overview=false';
  if (nbxCache.has(target)) return done(nbxCache.get(target));
  nbxAsk(target, function (err, body) {
    var r0 = !err && body && body.code === 'Ok' && Array.isArray(body.routes) && body.routes[0];
    var wps = body && Array.isArray(body.waypoints) ? body.waypoints : [];
    var legs = r0 && Array.isArray(r0.legs) ? r0.legs : [];
    var num = function (x) { return typeof x === 'number' && isFinite(x) && x >= 0; };
    var out = null;
    if (r0 && legs.length === pts.length - 1 && wps.length === pts.length
        && wps.every(function (w) {
          return w && num(w.distance) && w.distance / 1609.344 <= MV.SNAP_MI;
        })
        && legs.every(function (l) { return l && num(l.distance); })) {
      out = { metres: legs.map(function (l) { return l.distance; }),
              seconds: legs.every(function (l) { return num(l.duration); })
                ? legs.map(function (l) { return l.duration; }) : null };
    }
    if (out) nbxRemember(target, out);
    done(out);
  });
}

function sumOf(xs) {
  return xs.reduce(function (a, b) { return a + b; }, 0);
}

/* The hint from the inputs: { onTime, lateMin, offWayMi }, through done(). */
function onTimeWork(inp, done) {
  var P = 'P', D = 'D';
  var seqs = inp.aPick
    ? [[[inp.aPick, P, 1], [inp.aDrop, D, 1], [inp.bPick, P, 2], [inp.bDrop, D, 2]],
       [[inp.aPick, P, 1], [inp.bPick, P, 2], [inp.aDrop, D, 1], [inp.bDrop, D, 2]],
       [[inp.bPick, P, 2], [inp.aPick, P, 1], [inp.aDrop, D, 1], [inp.bDrop, D, 2]]]
    : [[[inp.aDrop, D, 1], [inp.bPick, P, 2], [inp.bDrop, D, 2]],
       [[inp.bPick, P, 2], [inp.aDrop, D, 1], [inp.bDrop, D, 2]],
       [[inp.bPick, P, 2], [inp.bDrop, D, 2], [inp.aDrop, D, 1]]];
  var none = { onTime: null, lateMin: null, offWayMi: null };
  // The detour, never through the new job's end: car (→ A-pick) → A-drop
  // against the same with B-pick put in, either side of A-pick.
  var distance = function () {
    if (!inp.bPick) return done(none);
    var asks = [[inp.car].concat(inp.aPick ? [inp.aPick] : [], [inp.aDrop])].concat(inp.aPick
      ? [[inp.car, inp.bPick, inp.aPick, inp.aDrop], [inp.car, inp.aPick, inp.bPick, inp.aDrop]]
      : [[inp.car, inp.bPick, inp.aDrop]]);
    var got = [], left = asks.length;
    asks.forEach(function (pts, i) {
      roadLegs(pts, function (r) {
        got[i] = r;
        if (--left) return;
        if (got.some(function (g) { return !g; })) return done(none);
        var miles = got.map(function (g) { return sumOf(g.metres) / 1609.344; });
        var extra = Math.min.apply(null, miles.slice(1)) - miles[0];
        done({ onTime: null, lateMin: null,
               offWayMi: extra < -ONTIME_NEG_MI ? null : Math.round(Math.max(0, extra) * 10) / 10 });
      });
    });
  };
  if (inp.aDue === null || inp.bDue === null || !inp.bPick || !inp.bDrop) return distance();
  var left = seqs.length, best = null;
  seqs.forEach(function (seq) {
    roadLegs([inp.car].concat(seq.map(function (s) { return s[0]; })), function (r) {
      if (r && r.seconds) {
        var t = inp.now, late = { 1: 0, 2: 0 };
        seq.forEach(function (s, i) {
          t += r.seconds[i] * 1000;
          if (s[1] === D) late[s[2]] = Math.max(0, t - (s[2] === 1 ? inp.aDue : inp.bDue));
          else t += PICKUP_ALLOW_S * 1000;
        });
        if (!best || late[1] + late[2] < best[1] + best[2]) best = late;
      }
      if (--left) return;
      if (!best) return distance();
      if (!best[1] && !best[2]) return done({ onTime: 'both', lateMin: null, offWayMi: null });
      var who = best[1] >= best[2] ? 1 : 2;
      done({ onTime: 'late' + who, lateMin: Math.ceil(best[who] / 60000), offWayMi: null });
    });
  });
}

/* The hint for this offer now: the answer, null for none, or undefined while
 * it is being asked (then `waiter`, if given, is called with it once it is
 * in). Nothing at all without NUCBOX_ROUTER. */
function onTimeHint(offer, now, waiter) {
  if (!NBX.route) return null;
  var inp = onTimeInputs(offer, now);
  if (inp.none) return null;
  if (inp.pending) {
    var pk = offer.id + '\npending';
    if (waiter) {
      var pw = onTimes[pk] || { hint: undefined, waiters: [] };
      onTimeKeep(onTimes, pk, pw);
      pw.waiters.push(waiter);
    }
    return undefined;
  }
  // Pins and deadlines, never `now`: a card's hint is worked out once.
  var key = offer.id + '\n' + JSON.stringify(inp);
  var on = onTimes[key];
  if (on) {
    if (on.hint === undefined && waiter) on.waiters.push(waiter);
    return on.hint;
  }
  on = { hint: undefined, waiters: [] };
  onTimeKeep(onTimes, key, on);
  inp.now = now;
  onTimeWork(inp, function (hint) {
    on.hint = hint;
    var w = on.waiters;
    on.waiters = [];
    w.forEach(function (f) { f(hint); });
  });
  // The waiter is called only when the answer is not returned here.
  if (on.hint === undefined && waiter) on.waiters.push(waiter);
  return on.hint;
}

// An offer pin answered: whoever waited on the pins asks again.
function onTimeAgain(offer) {
  var pw = onTimes[offer.id + '\npending'];
  if (!pw || !pw.waiters.length) return;
  var w = pw.waiters;
  pw.waiters = [];
  w.forEach(function (f) {
    var h = onTimeHint(offer, Date.now(), f);
    if (h !== undefined) f(h);
  });
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
 *
 * ONE ROW PER PAIRING: the same card against the same order(s) in the car is
 * one decision, however often it comes back. The scanner keeps a card's id
 * when the driver pages away from it and back (rpi/journal.py, RECENT_CARDS),
 * and its return is a new card on the slot here (not `sameCard`), so it was
 * written again. Measured at f80d0c2: an order held, card A, card B, A paged
 * back to — pair rows A, B, A, and the offers page listed three pairings for
 * two. Kept in memory for the last PAIRED_MAX pairings, as process memory
 * like the slot: a restart may write one twice.
 */
var PAIRED_MAX = 32;
var paired = [];

function recordPairing(offer, now, reading) {
  var held = holding(now);
  if (!held || !offer || typeof offer.id !== 'string') return;
  var pairKey = pairedWith(now, held).map(holdIdOf).join(' ') + '\n' + offer.id;
  if (paired.indexOf(pairKey) !== -1) return;
  paired = paired.concat([pairKey]).slice(-PAIRED_MAX);
  // With the on-time hint still being asked of the NucBox (onTimeHint), the
  // row waits for it, ONTIME_WAIT_MS at most, and is written as it stood at
  // `now`. With no router set it is written here and now, as it always was.
  var wrote = false;
  var go = function (hint) {
    if (wrote) return;
    wrote = true;
    writePairing(offer, now, reading, held, hint || null);
  };
  var hint = onTimeHint(offer, now, go);
  if (hint !== undefined) return go(hint);
  setTimeout(function () { go(null); }, ONTIME_WAIT_MS);
}

function writePairing(offer, now, reading, held, hint) {
  // The driver's money, off the READING — not off the offer line.
  //
  // The offer line is what scan_pi.emit_offer() prints, and it has never
  // carried target, band or costPerMile: they are the driver's settings, not
  // properties of a card, and they ride the reading beside it. Taking them
  // from `offer` handed Advice.stack three undefineds, which default to zero —
  // a target of $0/hr that every rate on earth clears.
  //
  // So every pair row ever written said the panel had advised TAKE IT. The
  // range and the geography in the row were right; the one field the row
  // exists for was a constant. Measured on a real pair — $12.45 over 30 min in
  // the car, a $3.00 over 40 min card offered against it, target 25: the panel
  // showed 'no' and the row recorded 'go'.
  //
  // That is worse than not recording it. The comment above says this file is
  // here to answer "when it said take both, was it right?", and a notebook in
  // which it always said take both cannot be graded — it can only mislead
  // whoever grades it.
  //
  // `withStack` two functions up has always read them off the reading. This is
  // the same three values from the same place.
  var money = reading || {};
  // Against what the pair line weighed it against (pairedWith): every order
  // in the car while carrying two is on. The offer line carries its own
  // screen, so an add-on is typed here without addOnAsCarded.
  var s = Advice.stackMany(pairedWith(now, held), timedLikeTheHeldJob(offer),
                           { target: money.target, band: money.band,
                             costPerMile: money.costPerMile }, now);
  // ...and if there is no reading to take them from, the honest row says the
  // panel's verdict is unknown rather than inventing one. `stack: null`
  // already means "it said nothing", which is a different claim, so this is
  // said in its own field.
  var judged = typeof money.target === 'number';
  var all = heldOrders(now);
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
    // What the pair line showed: the range, the span, the geography. Null
    // when it said nothing, which is a measurement in its own right and must
    // not be dropped as "no data".
    //
    // `state` inside it is the pair's arithmetic against the target, and it
    // is NOT what the panel said. It was drawn as the pair line's colour until
    // the colour came off, because it painted "take both" green under a PASS
    // headline 45 times in the real week, off money the held job had already
    // earned. It is still written, so a row keeps its shape and the offers
    // page's buckets keep working over every row on disk; `said` below is the
    // verdict the driver was shown.
    stack: s ? { pay: s.pay, worst: s.worst, best: s.best,
                 minMinutes: s.minMinutes, maxMinutes: s.maxMinutes,
                 leftMinutes: s.leftMinutes,
                 // Whether that money is the pair or a ceiling on it. Without
                 // it a capped CLOSE CALL and a genuine one are the same row
                 // in the record, and they are not the same call.
                 uncosted: !!s.uncosted,
                 // Three-valued, and `!!` flattened it to two. `null` is the
                 // claim WITHHELD — the offer card printed no distance, so
                 // the pair's rate is a ceiling and cannot be held against
                 // the job in the car — and `false` is the claim made and
                 // answered no. Coerced together, the record could not tell
                 // the offers page which it was, and the page printed the no.
                 state: s.state,
                 sure: s.sure === null ? null : !!s.sure,
                 ends: s.ends || null } : null,
    // False when this row was written with no reading to take the driver's
    // target from, so the state above is not the pair's arithmetic against
    // the target in force. Absent from rows written before this existed,
    // which is the same unknown.
    judged: judged,
    // The one verdict on the glass when this card arrived: its headline, off
    // the offer line, which carries its own card's state. Not off `reading`,
    // which is whatever reading came last and names no card; the offer line
    // does. Null from a scanner that does not send the state with the offer.
    said: typeof offer.state === 'string' ? offer.state : null,
    // ...and the stamp that tells this row from the ones before it. The
    // journal is append-only, and every pair row written while the colour was
    // drawn has `stack.state` as a verdict the driver saw; every row from here
    // on has it as one they did not. Absent means the colour was on the panel.
    stackShown: false
  };
  // ...and with carrying two on, every order in the car: `held` stays the
  // first-taken and `heldAlso` the others in the same shape. `heldCount` is
  // how many there were.
  //
  // `stack.over`, with two or more, is how many orders the range was
  // measured over — all of them, since Stage 6 (Advice.stackMany). A row
  // with heldCount 2 and no `over` was written before that, when the range
  // was the card against the first order alone ("vs ① only" on the panel);
  // the journal is append-only, so the two kinds of row are told apart by
  // this and nothing else. Absent with one order, whose row is unchanged.
  if (carryingTwo(now)) {
    row.heldAlso = all.slice(1).map(function (o) {
      return { pay: numOrNull(o.pay), minutes: numOrNull(o.minutes),
               dropoff: o.dropoff || null, scanned: !!o.dropoffScanned,
               heldMs: Math.max(0, now - o.acceptedAt) };
    });
    row.heldCount = all.length;
    if (row.stack && all.length > 1) row.stack.over = all.length;
  }
  // ...and the order in the car whose store this offer's pickup is, by its
  // holdId (sameStoreOf, the rule the pair line says it by): ids only, the
  // store's name and door are on the rows they came from. Absent when none
  // is, or when nothing could tell, so a row written before it reads the
  // same as one with no shared store — which is what the glass said then.
  var same = sameStoreOf(pairedWith(now, held), offer);
  if (same) row.sameStore = same.holdId;
  // ...and the on-time hint the card showed beside the pair line: 'both',
  // 'late1' (the order in the car), 'late2' (this offer) or null for none,
  // with the whole minutes late, or the road miles out of the way it fell
  // back to. Numbers only: no point, no stop, no time of day.
  row.onTime = hint ? hint.onTime : null;
  if (hint && typeof hint.lateMin === 'number') row.lateMin = hint.lateMin;
  if (hint && typeof hint.offWayMi === 'number') row.offWayMi = hint.offWayMi;
  appendLines(JSON.stringify(row) + '\n', function (err) {
    if (err) console.error('journal: could not record a pairing: ' + err.message);
  });
}

/* The Trip Planner's stops come off the order in the car at the moments the
 * driving screen forgets them — live.html's forgetDest — so a panel reloaded
 * mid-delivery shows what the live one showed, and not stops it had already
 * dropped.
 *
 * They were kept until the order went or another planner replaced them, which
 * is longer than the panel keeps them, and the difference was on the glass: a
 * two-dropoff planner, then ⌖ over the navigation screen, which read the
 * order's end — and a reload brought back "2 dropoffs: end not guessed" beside
 * a green button reading that very end (reproduced through this server). The
 * panel forgets them at a press, when the order goes, and when a different
 * offer goes on the record; the order going takes them with it here, and this
 * is the other two. The read destination beside them is the order's end and
 * goes on being used by the stack line whatever the panel shows, so it is not
 * dropped here: only the answer to the press is. */
function forgetPlanner(now) {
  Assemble.forgetPlanner(holding(now));
}

/* The Trip Planner, written down: collection only. Nothing reads these rows
 * back — the fold skips a kind it has no use for ("something newer than this
 * reader") and resume() in rpi/journal.py skips every kind — so they change no
 * figure on any page. What they are for is the question no file on this rig can
 * answer yet: how a stacked trip actually ran, stop by stop, against the times
 * the app said to expect.
 *
 * `id` and `seq` because syncKey drops a kind row without them, and the copy at
 * home would then hold none. Stamped from the clock like a sighting, with the
 * same caveat, which cannot bite here: two planners in one millisecond would
 * need two ⌖ presses answered in it.
 *
 * ONE ROW FOR ONE PLANNER. A driver checking an answer presses again, and the
 * screen has not changed: the same stops read twice inside PLANNER_SAME_MS are
 * one row, not a row per press. Kept on the stops exactly as read, so a stop
 * finished, an order added or a name read differently is a new row — a second
 * reading that disagrees is evidence, and only a repeat is noise. Timed from
 * the row last written, so a planner unchanged for longer than that is written
 * again: "still these stops at this time" is a fact the first row did not
 * hold. Process memory, so a restart may write one planner twice; that is a
 * duplicate a reader can see, where a lost row is not.
 *
 * Settable for the reason SCREENING_MS is: a check that has to wait out five
 * minutes of real clock to prove the window ends is a check nobody runs.
 *
 * ONLY WHEN THE SCANNER SAYS `keep`. These rows hold customers' names and
 * front doors, and `"keepPlaces": false` is documented as keeping addresses
 * out of the journal; this server does not read the scanner's settings, so the
 * scanner says it on the line. It was written regardless at first, which made
 * the setting a claim this file did not honour for the most personal rows it
 * writes. The ⌖ mark rows and the pairing rows beside it still carry a read
 * destination whatever the setting says — that is older than this, and named
 * as open in README.md rather than fixed in passing. */
var PLANNER_SAME_MS = Number(process.env.PLANNER_SAME_MS);
if (!isFinite(PLANNER_SAME_MS) || PLANNER_SAME_MS < 0) PLANNER_SAME_MS = 5 * 60000;
var plannerWritten = null;

function recordPlanner(planner, now) {
  // Whether a row is due is Assemble.plannerRowDue's rule; the row is this.
  var due = Assemble.plannerRowDue(plannerWritten, planner.stops, now, PLANNER_SAME_MS);
  if (!due) return;
  plannerWritten = due;
  appendLines(JSON.stringify({
    v: 1, kind: 'planner', id: 'planner-' + now, seq: 1, at: now,
    stops: planner.stops,
    // Always true from this scanner, which reads a planner only under a press;
    // written so the row says on its face what it answered, as a mark does.
    asked: planner.asked === true
  }) + '\n', function (err) {
    // Said out loud, like every other write on this path: a tally that stopped
    // being written would be read later as a rig that never saw a planner.
    if (err) console.error('journal: could not record a trip planner: ' + err.message);
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
 * written to the SD card, against 5.7MB a *week* for the journal (measured in
 * rpi/journal.py's WEEK_BYTES). Every byte of it is stale two frames later and
 * none of it needs to survive a reboot, so writing it to the one part of this
 * system that wears out was
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
var CSV_COLUMNS = ['at', 'pay', 'minutes', 'billedMinutes', 'miles',
                   // How much of `minutes` and `miles` was the drive to the
                   // pickup rather than the job. Empty on a card that stated
                   // one total and never split it, which is most deliveries.
                   // Subtract them and what is left is the job itself, which is
                   // the only form of these figures that says anything about
                   // the distance between two places.
                   'toPickupMinutes', 'toPickupMiles', 'items',
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
                   // ...and for the one doubt that names a leg rather than a
                   // figure, how far that leg was. "leg" on its own cannot tell
                   // a missing walk to the door from a missing trip, which is
                   // the difference between a reading that was nearly right and
                   // one out by a factor of eight. Empty on every other row.
                   'suspect', 'doubt', 'untimedMiles', 'accepted', 'hidden',
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

// The card box drawn INSIDE the screen box, as [x, y, w, h] fractions of the
// screen box — null when none was drawn — or a string saying what was wrong.
// The same rule as rpi/cropbox.py's parse_card, which checks it again on the
// way in: offers are read in this box, and a ⌖ press reads the whole screen
// box, because a trip planner's addresses sit outside where the cards land.
function cropCard(body) {
  if (body.card === undefined || body.card === null) return null;
  if (!Array.isArray(body.card) || body.card.length !== 4) {
    return 'a card box needs x, y, w, h';
  }
  var c = body.card.map(fractionOrNull);
  if (c.indexOf(null) !== -1) return 'card box corners must be numbers';
  c[2] = Math.min(c[2], 1 - c[0]);
  c[3] = Math.min(c[3], 1 - c[1]);
  if (c[2] < MIN_CROP_SIDE || c[3] < MIN_CROP_SIDE) {
    return 'that card box is too small to read anything from — drag a bigger one';
  }
  return c;
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

// Decoded by Node's own StringDecoder rather than chunk by chunk. `text +=
// chunk` on a Buffer stringifies each TCP segment on its own, so a two-byte
// character split across two segments — an 'é' in a place name, sent over car
// wifi in more than one packet — arrived as two replacement characters and
// was stored that way for good, because the row's identity is its id and the
// browser's next re-send of the correct bytes was refused as a duplicate.
//
// Over the cap, the buffer is dropped and the rest of the body is read and
// thrown away rather than the socket being destroyed. Destroying it is what this
// did, and it meant the refusal could not be read: Node resets the connection
// when a response ends with the request still arriving, so the 400 explaining
// what was wrong never reached the sender. sync.py cannot tell a reset from
// being out of range — a car is offline most of the time, so out of range exits
// 0 and says "will try again next time" — and a rig whose uploads had grown too
// big would have reported success and backed up nothing, permanently. Measured:
// a 9MB upload came back as `ConnectionResetError`, and now comes back as a
// readable 400 that sync.py exits non-zero on.
//
// This is a near-miss cure and not a guarantee, which is worth being exact
// about. Node stops feeding the request once the response is finished, so past
// roughly twice the cap the sender's remaining write still fails — measured:
// 9MB readable, 16MB a broken pipe. There is no way to fix that from here; a
// server cannot make a client read an answer it is not looking at yet, short of
// `Expect: 100-continue`, which urllib does not send. What it does cover is the
// case that actually happens: a body a little over the limit, from a sender
// whose idea of the limit has drifted. The guarantee lives at the other end,
// where sync.py now measures its chunks in the same unit as this cap.
function readBody(req, cap, done) {
  var text = '';
  var over = false;
  req.setEncoding('utf8');
  req.on('data', function (chunk) {
    if (over) return;
    text += chunk;
    if (text.length > cap) { over = true; text = ''; done(new Error('too big')); }
  });
  req.on('error', function () { if (!over) { over = true; done(new Error('aborted')); } });
  req.on('end', function () { if (!over) { over = true; done(null, text); } });
}

function readJsonBody(req, done) {
  var text = '';
  var over = false;
  req.setEncoding('utf8');
  req.on('data', function (chunk) {
    if (over) return;
    text += chunk;
    // Drained rather than destroyed, for the reason in readBody above.
    if (text.length > MAX_BODY) { over = true; text = ''; done(new Error('too big')); }
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
    //
    // All three fields, or the fact is only half repaired. This borrowed
    // `places` alone — the list a reader looks at — and left `pickup` and
    // `dropoff`, which are the two fields everything DOWNSTREAM asks for: the
    // offers page hides a row's map controls without them, map.html's whole
    // working set is `o.pickup || o.dropoff`, and Advice.sameArea compares
    // dropoffs. So a card whose winning reading lost the map to glare came
    // back with "Where: Chick-fil-A → Old Mountain Rd NW" printed on it and no
    // way to put it on a map, which reads as the page contradicting itself
    // about one row.
    //
    // From the SAME lender, not from whichever reading happens to have each
    // one. Two readings of a card can disagree about where it goes, and a
    // pickup off one with a dropoff off another is a journey neither of them
    // read.
    //
    // Unconditionally, because this branch is reached only when the winner has
    // no places — and both ends are derived FROM places in every writer this
    // project has, so a winner with no places has no ends either. A guard
    // asking whether it does was written here and taken out again rather than
    // left to look like it was protecting something.
    if (lender) {
      best = Object.assign({}, best, {
        places: lender.places,
        pickup: lender.pickup || null,
        dropoff: lender.dropoff || null
      });
    }
  }
  return best;
}

// Folded once per change to the journal, not once per request.
//
// readJournal hands back the same array until the file changes and a new one
// after, so the array's identity and length say whether this answer is still
// the answer. Measured on a year's journal after the parse was made free:
// this fold was what remained — ~100ms over 51,000 rows on a desktop, on
// every offers-page load and every /api/today poll after a new offer.
var latestCache = null;

/* The rows that can change an answer about offers at or after `floor`.
 *
 * WHY THIS EXISTS. readJournal is already incremental — it tail-reads and only
 * parses the bytes that arrived — but the FOLD was not. latestCache is keyed on
 * the rows array, and readJournal hands back a new array after every append, so
 * during a shift every scanned offer made the next page load re-fold the whole
 * journal. Measured on a year-sized one: 4 ms idle, 182 ms after a single
 * appended row, and the scanner appends every few seconds. That is the cost the
 * driver actually feels, and asking for "today" did not avoid a line of it.
 *
 * WHAT MAY BE DROPPED, and it is much less than it looks. A card may be dropped
 * only if EVERY reading of it is older than the floor and none of them predates
 * the clock. Everything else stays:
 *
 *   - every `mark` and `rule`, whenever written. A rule written months ago
 *     hides a card scanned today (see the rule fold below); a mark written
 *     today changes a card scanned months ago.
 *   - every `seen` and `pair` at or after the floor. They ride on the folded
 *     array as properties, and both callers count them only at or after their
 *     own floor (/api/journal's `watched` and its pairings; shiftSummary reads
 *     neither). Before, they were kept from the whole file, as was every other
 *     kind — screen, sighting, drop, visit, planner and kinds this build has
 *     never heard of — which the fold skips without reading ("something newer
 *     than this reader"): it reads mark, rule, seen and pair and nothing else,
 *     so a kind row it skips changes no answer. Measured at f80d0c2 on a
 *     synthetic 22 MB journal (rows from rpi/journal.py's own writer over the
 *     corpus texts, kind rows in the shapes this server writes), today's
 *     window kept all 11,404 kind rows in the file; it keeps 489 now, and the
 *     fold answers the same, offer for offer.
 *   - every reading of a card any of whose readings is in the window. Splitting
 *     one card's readings across the floor would change bestReading's vote, and
 *     so the pay, minutes, miles and $/hr reported for it, depending on which
 *     range button was pressed. That is a confidently wrong number, which is
 *     the fault this project exists to refuse.
 *   - every row stamped before the clock was believable. A Pi boots in 1970 and
 *     jumps when NTP arrives; those rows are in no window by construction, and
 *     the page counts them in `beforeClock` and says so.
 *
 * FILE ORDER IS PRESERVED. bestReading breaks a tie by taking the last row it
 * was handed, so a filter that reordered would change which reading wins.
 *
 * A floor of 0 means "All", and then there is nothing to drop.
 *
 * WHERE THIS MAY NOT BE USED, and it has been asked twice: /api/journal/newest,
 * /api/journal/notes and POST /api/journal/ingest must keep reading every row.
 * Ingest is the one that cannot be argued with — its idempotence is a syncKey
 * set built over the whole file, so a windowed set stops recognising rows it
 * has already stored and appends them again on every sync tick. The header of
 * readJournal above records what a short set did last time: 60 duplicate rows,
 * `ok: true`, and a `have` that was wrong. See AUDITS.md.
 *
 * CARRIED FORWARD ACROSS APPENDS. readJournal's new array after an append is
 * the old one's rows, the same objects, with the new ones after; so the window
 * worked out over the first `n` rows stands, and only the rows after it are
 * looked at. Walking the whole file again on each append is what made
 * /api/today's cost grow with the journal: measured at f80d0c2 on synthetic
 * journals, this function alone took a median of 4.5 ms after each append at
 * 22 MB and 10.6 ms at 50 MB (0.01 ms now), and /api/today 4.3 ms and 7.5 ms
 * (1.8 ms and 2.5 ms now).
 * Worked out afresh when the array is not that one grown (the file rewritten,
 * a half-written last line read again, a window not kept) and when an
 * appended reading puts in the window a card whose earlier readings it had
 * left out — those must come back in at their own places in the file. */
var WINDOWS_MAX = 3;
var windows = [];

function inWindow(r, floor) {
  var at = (typeof r.at === 'number' && isFinite(r.at)) ? r.at : 0;
  return at >= floor || at < CLOCK_BELIEVABLE_AFTER;
}

// A kind row the fold reads, for this floor: see above.
function foldReads(r, floor) {
  if (r.kind === 'mark' || r.kind === 'rule') return true;
  return (r.kind === 'seen' || r.kind === 'pair') && (r.at || 0) >= floor;
}

/* One row onto a window: kept or not, and false when the window cannot take
 * it without being worked out again. */
function windowTakes(w, r) {
  if (r.kind) {
    if (foldReads(r, w.floor)) w.out.push(r);
    return true;
  }
  if (!r.id) {
    if (inWindow(r, w.floor)) w.out.push(r);
    return true;
  }
  if (w.wanted.has(r.id)) { w.out.push(r); return true; }
  if (!inWindow(r, w.floor)) { w.dropped.add(r.id); return true; }
  if (w.dropped.has(r.id)) return false;
  w.wanted.add(r.id);
  w.out.push(r);
  return true;
}

function windowOver(rows, floor) {
  var w = { floor: floor, rows: rows, n: rows.length, out: [], wanted: new Set(),
            dropped: new Set() };
  for (var i = 0; i < rows.length; i++) {
    var r = rows[i];
    if (!r.kind && r.id && inWindow(r, floor)) w.wanted.add(r.id);
  }
  for (var j = 0; j < rows.length; j++) windowTakes(w, rows[j]);
  return w;
}

function rowsFor(rows, floor) {
  if (!floor) return rows;
  var w = null;
  windows = windows.filter(function (x) {
    if (x.floor === floor) w = x;
    return x.floor !== floor;
  });
  var grown = w && w.n > 0 && rows.length >= w.n && rows[0] === w.rows[0]
    && rows[w.n - 1] === w.rows[w.n - 1];
  if (grown) {
    for (var i = w.n; i < rows.length; i++) {
      if (!windowTakes(w, rows[i])) { grown = false; break; }
    }
  }
  if (grown) {
    w.rows = rows;
    w.n = rows.length;
  } else {
    w = windowOver(rows, floor);
  }
  windows.push(w);
  if (windows.length > WINDOWS_MAX) windows.shift();
  // The window's own array, which the next append grows in place: the fold
  // reads it once, synchronously, and keeps nothing of it.
  return w.out;
}

/* Keyed on the floor as well as the array, because rowsFor builds a new array
   every time and a cache keyed on identity alone would never hit again. All
   thrown away together the moment the file changes.

   THE FLOOR TO THE DAY, AND THREE OF THEM. /api/journal?days= asks from
   `now - days`, a floor that moves every millisecond, so every load folded
   afresh and kept its answer beside the last one's for as long as the file did
   not change: measured at f80d0c2, RSS 181 MB to 393 MB over 31 days=30 loads
   of a synthetic 22 MB journal (172 to 178 MB now). The fold now runs from
   local midnight on or before the floor asked for — a window that holds every
   row the exact one does, and both callers keep only what is at or after
   their own floor (shiftSummary, /api/journal) — and the last WINDOWS_MAX
   answers are kept. */
function dayFloor(floor) {
  if (!floor) return 0;
  var d = new Date(floor);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

function latestPerOffer(rows, floor) {
  var key = dayFloor(floor || 0);
  if (!latestCache || latestCache.rows !== rows || latestCache.n !== rows.length) {
    latestCache = { rows: rows, n: rows.length, byFloor: [] };
  }
  var hit = latestCache.byFloor.filter(function (e) { return e.floor === key; })[0];
  if (!hit) {
    hit = { floor: key, offers: latestPerOfferUncached(rowsFor(rows, key)) };
    latestCache.byFloor.push(hit);
    if (latestCache.byFloor.length > WINDOWS_MAX) latestCache.byFloor.shift();
  }
  return hit.offers;
}

function latestPerOfferUncached(rows) {
  var byId = Object.create(null);
  var out = [];
  var marks = Object.create(null);
  var rules = [];
  // How many cards the rig watched go past, from the scanner's own tally. Kept
  // beside the offers rather than in them: it is a fact about the window, not
  // about any one card, and the page needs both to say what fraction was
  // recorded.
  var seen = [];
  // Every time the panel was asked whether to take a second job with one
  // already in the car, and what it answered. Kept beside the offers for the
  // same reason `seen` is: a pairing is not a card, it is a moment — two cards
  // and a clock — and folding it into either card would lose the other.
  var pairs = [];
  var readings = Object.create(null);

  rows.forEach(function (r) {
    if (!r || typeof r !== 'object') return;
    if (r.kind === 'mark') {
      // Folded by WHEN each mark was made, not by where it sits in the file.
      // There are two journals now that can each carry a mark about one
      // offer — the rig's and the copy's, with the copy's coming back over
      // the sync — and a row appended last is not the row made last: a tick
      // in the car at 11:00 must beat an un-tick made at home at 10:00 even
      // when the un-tick arrives afterwards. Per field, because a mark may
      // carry only `accepted` or only `hidden`, and an older row about the
      // other field is still the newest word on that one.
      if (r.id) {
        var m = marks[r.id] || (marks[r.id] = {});
        var when = (typeof r.at === 'number' && isFinite(r.at)) ? r.at : 0;
        // A `false` that names no surface is a TAKE-BACK, folded exactly as a
        // `null` is — not a pass.
        //
        // No press before Passed existed meant "I passed on it": the `false`
        // in every older mark is the ✓ pressed again, the panel's Took pressed
        // again, or the offers page's Undo after a first ✓. And a page loaded
        // before an upgrade goes on writing those after it, with no `via`:
        // live.html never reloads itself and sw.js serves the cached copy
        // first. Read as a pass, one such take-back took the card out of
        // Close the shift's list and out of Advice.ifCleared's mix at once —
        // measured against this server, an old-style ✓ and ✓-again folded to
        // `accepted: false`, and labels then said passed 1, open 0. A pass
        // is now only ever sent with `via` (Passed sends 'review'), so the
        // missing field is exactly what tells the two apart. Newest-wins
        // still applies: it is a withdrawal, and beats an older tick.
        var said = r.accepted === false && r.via === undefined ? null : r.accepted;
        if (said !== undefined && when >= (m.acceptedAt || 0)) {
          m.accepted = said; m.acceptedAt = when;
        }
        if (r.hidden !== undefined && when >= (m.hiddenAt || 0)) {
          m.hidden = r.hidden; m.hiddenAt = when;
        }
        // Where the job went, read off the phone rather than off the card.
        //
        // Folded by `at` like the other two and for the same reason: a
        // destination read in the car at 11:00 must beat one read at home at
        // 10:00 whichever order the two journals merge in. Its own field, not
        // folded in with `accepted`, because a mark may carry only one of them
        // and an older row about the other is still the newest word on it.
        //
        // A PRESS OUTRANKS A SIGHTING, whenever each of them arrived.
        //
        // Newest-wins alone is right between two of a kind and wrong across
        // them: a navigation screen caught at 11:05 is not better evidence
        // than the driver deliberately answering at 11:00, and folding on `at`
        // alone let the later one erase both the address and the fact that a
        // press had ever happened. The comment here used to warn about the
        // opposite — "folding it separately would let a press at 11:00 vouch
        // for a sighting at 11:05" — which is a real hazard and is why the bit
        // still travels with the address rather than on its own. It was
        // guarding the direction that could not happen.
        //
        // Kept even though the live path can no longer produce that pair,
        // because this fold also merges the copy synced from the NUC, where
        // rows arrive in whatever order the two journals are reconciled in.
        var rAsked = r.asked !== false;
        var beatsIt = m.dropoff === undefined
          || (rAsked && !m.dropoffAsked)
          || (rAsked === m.dropoffAsked && when >= (m.dropoffAt || 0));
        if (typeof r.dropoff === 'string' && r.dropoff && beatsIt) {
          m.dropoff = r.dropoff; m.dropoffAt = when;
          // ...and whether anybody ASKED for it, carried with the address
          // rather than folded on its own, because it is a property of THIS
          // address and not of the offer. Folding it separately would let a
          // press at 11:00 vouch for a sighting at 11:05.
          //
          // Absent means asked, matching the reading and the mark, so rows
          // written before the field existed keep the behaviour they were
          // written under. Named `dropoffAsked` rather than `asked` because
          // `marks` is a per-field fold and a bare `asked` reads as a property
          // of the mark as a whole, which is how the first version of this was
          // wrong: the field was simply never copied here, so every sighting
          // arrived at the guard below as `undefined` and was let through as a
          // press.
          m.dropoffAsked = r.asked !== false;
          // ...and whether an unasked one was label-proven, carried the same
          // way and for the same reason: it is what lets this mark past the
          // card's own end below, as the live path let it past the hold's.
          m.dropoffLabelled = r.labelled === true;
        }
      }
      return;
    }
    if (r.kind === 'rule') { rules.push(r); return; }
    if (r.kind === 'seen') { seen.push(r); return; }
    // A copy, for the reason the offers below are copied: `accepted` is
    // written onto it further down and the rows readJournal hands over live
    // across requests. Pushed as itself, the outcome written by one fold was
    // still on the cached row at the next, so an answer taken back left the
    // pairing saying "passed" for as long as the process ran — measured
    // through this server: pass, withdraw, and the pair still read false.
    if (r.kind === 'pair') { pairs.push(Object.assign({}, r)); return; }
    if (r.kind) return;                       // something newer than this reader
    // Copies, because `hidden` and `accepted` are written onto these below
    // and the rows readJournal hands over now live across requests.
    if (!r.id) { out.push(Object.assign({}, r)); return; }
    if (!(r.id in byId)) {
      // The slot is claimed here and filled below, so the order of `out` is
      // still the order the cards were first seen in the file.
      byId[r.id] = out.length; out.push(null); readings[r.id] = [r]; return;
    }
    readings[r.id].push(r);
  });

  /* The vote, once per card rather than once per reading.
     This ran on every reading as it arrived and threw the answer away when the
     next one came: a card read three times was voted on three times and copied
     three times, and two of each were discarded. bestReading is O(k^2) in the
     readings of one card, so doing it per arrival made the whole fold O(k^3)
     for that card, and the copies were the bulk of the garbage — measured at
     87,600 allocations to produce 43,800 offers on a year-sized journal.
     The answer is identical: bestReading([r]) returns r for a single reading,
     and for more it is a pure function of the whole list, which is what it is
     handed here. */
  Object.keys(byId).forEach(function (id) {
    out[byId[id]] = Object.assign({}, bestReading(readings[id]));
  });

  out.forEach(function (o) {
    // A rule hides every reading of one card. The test offer a driver keeps
    // presenting to check the rig still works would otherwise need hiding again
    // after every check.
    //
    // The NEWEST matching rule wins, by `at` — not the last one in the file.
    // That is the same correction the mark fold above carries a paragraph
    // about, and rules travel over the same two-way sync: sync.py pulls both
    // kinds from /api/journal/notes and ingest appends them at the end of the
    // receiving file. So on whichever machine did not make the newer rule, the
    // older one lands last and won.
    //
    // Measured through the real ingest door: a copy holding the driver's 11:00
    // "put this back", sent the rig's 10:00 "hide every card like this", went
    // from 2 offers visible to 0 — and the driving screen's shift line simply
    // read short, because /api/today carries no hidden count at all.
    //
    // The match itself is unchanged, three `===` on the same three fields: a
    // key built by joining them would quietly make null and undefined the same
    // thing, and those are different answers about whether a card had a
    // distance.
    var winner = null;
    rules.forEach(function (rule) {
      var m = rule.match || {};
      if (m.pay === o.pay && m.minutes === o.minutes && m.miles === o.miles
          && rule.hidden !== undefined) {
        var when = (typeof rule.at === 'number' && isFinite(rule.at)) ? rule.at : 0;
        if (!winner || when >= winner.at) winner = { hidden: rule.hidden, at: when };
      }
    });
    if (winner) o.hidden = winner.hidden;
    var mark = o.id && marks[o.id];
    if (mark) {
      // Three answers, and the page needs all three kept apart: `true` taken,
      // `false` passed, and NO FIELD for a card nobody has answered for. A
      // withdrawal (`null`, see the mark handler) takes part in the newest-wins
      // fold above like either answer — a ✓ taken back at 11:00 beats the ✓
      // made at 10:00 — and then copies nothing, so the row comes out exactly
      // as an unmarked one does. Nothing else could have put the field there:
      // rpi/journal.py and journal-client.js never write `accepted` onto a
      // reading.
      if (mark.accepted === true || mark.accepted === false) o.accepted = mark.accepted;
      if (mark.hidden !== undefined) o.hidden = mark.hidden;   // an id beats a rule
      // A destination the driver revealed beats one the card never gave — and
      // beats one it DID give, too, because a card's own dropoff is what the
      // reader made of a line of OCR and this is what the phone actually said
      // when asked. `dropoffScanned` marks the difference so nothing
      // downstream has to guess which kind it is holding.
      //
      // WHEN ASKED. That sentence was the whole justification and it stopped
      // being true when the scanner began reporting addresses nobody pressed
      // for: an unprompted sighting is not the phone answering a question, it
      // is a navigation screen that happened to be in front of the camera, and
      // it may belong to the job before this one. So it may fill a blank and
      // may not overwrite — the same rule the live path already keeps, which
      // this did not, because the guard there tests the card in MEMORY and
      // this tests the row on disk. Those diverge: the row is merged
      // newest-wins across every reading of the offer and `bestReading`
      // borrows ends from whichever reading had them, so a card whose later
      // readings lost the address still has one here.
      //
      // Absent means asked, so the rows already in this journal — and any
      // written by an older rig still reporting only presses — keep the
      // behaviour they were written under.
      // ...and a LABEL-PROVEN sighting may overwrite the card's own end too,
      // the one rule the live path files it by: the marks fold above already
      // keeps a press over it, so what is left to beat here is the card.
      if (mark.dropoff && (mark.dropoffAsked || mark.dropoffLabelled || !o.dropoff)) {
        o.dropoff = mark.dropoff;
        o.dropoffScanned = true;
      }
    }
  });

  out.sort(function (a, b) { return (a.at || 0) - (b.at || 0); });
  out.seen = seen;
  // Whether the driver went on to take the offer they were being advised
  // about. Joined here rather than on the page, because the mark can be on an
  // offer the window's own filters have already dropped — hidden, or older
  // than the range — and a pairing whose outcome silently became "no" would be
  // worse than one that says nothing. `undefined` means unmarked, which is a
  // third answer and not a "no" — and a withdrawn answer is that third one too,
  // or the offers page counts it as "marked either way".
  pairs.forEach(function (p) {
    var mark = p.id && marks[p.id];
    if (mark && (mark.accepted === true || mark.accepted === false)) {
      p.accepted = mark.accepted;
    }
  });
  out.pairs = pairs;
  return out;
}

// Make sure the directory a file is about to be written into exists.
//
// Cheap enough to do on every write: mkdir with recursive succeeds silently
// when the directory is already there, which it is after the first one.
function withDirectory(file, done) {
  var dir = path.dirname(file);
  fs.mkdir(dir, { recursive: true }, function (err) {
    if (err && err.code !== 'EEXIST') return done(err);
    // EEXIST is fine when what exists is a directory. A file standing where
    // the directory should be also answers EEXIST, and was taken as fine
    // here while every append then failed with ENOTDIR.
    fs.stat(dir, function (statErr, st) {
      if (statErr) return done(statErr);
      if (!st.isDirectory()) {
        var e = new Error(dir + ' is not a directory');
        e.code = 'ENOTDIR';
        return done(e);
      }
      done(null);
    });
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

// Returns how many rows were taken, and counts what could not be.
//
// Skipping a line that will not parse is right — the file is append-only, it
// cannot be repaired, and one bad line must not cost the other fifty thousand.
// Saying nothing about it was not. This is the one artefact of this project
// that cannot be regenerated, and a row disappearing out of every figure with
// nothing anywhere saying so is the failure this file keeps writing comments
// about.
//
// One torn row is the accepted cost of a power cut, and journal.py's append
// says so in as many words. A card beginning to fail is not one row, and it is
// the case where knowing early is the difference between a backup that saves
// the shift and one that copies the hole.
//
// `torn` is an OUT parameter rather than a second return, because the caller
// needs both numbers and the count has to accumulate across the incremental
// reads below.
function parseLines(text, rows, torn) {
  var n = 0;
  text.split('\n').forEach(function (line) {
    line = line.trim();
    if (!line) return;
    try {
      var row = JSON.parse(line);
      if (row && typeof row === 'object') { rows.push(row); n++; return; }
    } catch (e) { /* falls through */ }
    if (torn) torn.n++;
  });
  return n;
}

// The journal, parsed once, and after that only the part that grew.
//
// It was read and parsed whole on every call, on the event loop that also
// relays the live picture to the panel. The first timing, 150-265ms on a
// desktop, was of a 20MB file of fifty thousand short rows — about 400 bytes
// a row, where the real week's average 1,752 (rpi/journal.py's WEEK_BYTES,
// 5.7MB a week over 3,265 rows) — so it was not a real journal's shape, and
// calling it three and a half weeks counted its bytes and not its rows.
// Re-timed on real rows: a third of the 64MB roll, 22.4MB and 12,766 rows of
// the replayed week, parses here in 64-223ms over 48 runs (medians 87-93) on
// the development container. Not timed on a Pi 4, which is slower.
//
// Every offers-page load paid it. Worse, every offer the scanner appends
// changes the file, so the driving screen's next /api/today poll paid it
// again: a frozen picture, every few minutes, for the whole shift.
//
// The file is append-only apart from the 64MB roll, so what was parsed last
// time is still true and only the bytes past it are new. Kept: the inode,
// the size, the mtime, where the last complete line ended, and the rows.
// Same inode and size and mtime: the rows as they are. Same inode, larger:
// read from the end of the last complete line, and parse what is whole. A
// different inode — the roll, or a backup restored over the top — or a
// smaller file: start again. The last line may be mid-write when this looks;
// it is parsed if it parses, as before, but the offset stays at its start so
// it is read again, once, when it is finished — and the row it made is taken
// back first, so it is never counted twice.
//
// latestPerOffer copies every row it annotates, because these rows now
// outlive one request.
var journalCache = null;

/* One read at a time, however many callers ask at once.
 *
 * Every reader used to do the whole job for itself: its own whole-file Buffer,
 * its own whole-file string, its own split array of one string per line, and
 * its own parsed rows. Deliberately, and for a real reason — the comment
 * further down explains what two readers sharing one array did to the counts —
 * but it means the cost multiplies by the number of readers rather than being
 * paid once.
 *
 * Measured on a year-sized journal: one cold read peaks at 588 MB of resident
 * memory, three concurrent cold reads at 1414 MB. Three at once is not a
 * hypothetical; rpi/test_server.py fires exactly that and names the callers —
 * the driving screen's poll, the offers page and the sync's /api/journal/newest
 * all land just after the scanner appends. On a Pi sharing its RAM with
 * OpenCV and Tesseract, the difference is whether the rig swaps.
 *
 * So the readers queue instead. The winner does the work and everyone waiting
 * gets its answer, which is the same arrangement a cache hit already has: the
 * hit path hands `c.rows` straight to the caller, so sharing one array between
 * readers is the existing contract, not a new one. What must not be shared is
 * an array still being APPENDED to, and that is exactly what this prevents.
 *
 * A waiter that joined during the read can be one append behind. That is the
 * same staleness as arriving a moment earlier and hitting the cache, and it
 * errs in the safe direction for the one caller where it matters: a sync
 * reconciling against /api/journal/newest that sees fewer rows re-sends, where
 * one that saw more would skip. */
/* One ingest at a time, from the read to the append.
 *
 * readWaiters above serialises the READ and nothing else — and for two
 * overlapping ingests it makes matters worse rather than better, because they
 * SHARE one read and are therefore guaranteed to see the same pre-append
 * journal. Each then builds its own `seen` set from those rows, finds every
 * key in its batch absent, and appends the lot. The append-only file this
 * project calls irreplaceable ends up holding each row twice, both ends reply
 * `ok: true`, and `have` is wrong in the same breath.
 *
 * Measured against a real server: a 400-row journal, two simultaneous POSTs of
 * the same 60 rows. Both answered `added: 60, have: 460`; the file held 520
 * lines, 460 distinct keys, 60 stored twice.
 *
 * The second-order harm is the one that costs offers. sync.py's shortfall
 * check compares ROW counts, not distinct offers, on both sides — so a copy
 * whose rows are doubled reports about twice what it really holds, and the
 * check cannot fire until the copy has lost more than half of everything. A
 * real gap then hides behind the doubling for good.
 *
 * Two reachable routes with no contrivance: sync.py's own stderr tells the
 * operator to run it by hand with --all, and the installed timer keeps ticking
 * every ten minutes while they do; and a retry after a dropped connection can
 * overlap the request it is retrying.
 *
 * A queue rather than a mutex flag, so a caller cannot forget to wait. */
/* ...and the same queue by name, because ingest was not the only endpoint that
 * does a read, then a decision, then a write, on a file two callers can reach
 * at once. `/api/places` and `/api/config/backup` both do, and both were
 * unserialised.
 *
 * Measured on the real server, two concurrent POSTs of 600 places and 1 against
 * a seeded 1,325-place file, ten runs: TWO left `places.json` unparseable and
 * `GET /api/places` answering `stored: 0`, and the other EIGHT lost one
 * writer's batch entirely — while replying `stored: 1925` over a file holding
 * 1,326. None of the ten came out right. The endpoint's own comment ten lines
 * into the handler says what it was meant to do: "MERGED, never written over.
 * Two browsers place different days of the same journal, and a POST that
 * replaced the file would have whichever finished last throw the other's work
 * away." That is precisely what it did.
 *
 * A name per file rather than one global queue, so a slow sync cannot sit in
 * front of a geocode batch that touches nothing it touches. Keyed on the lock's
 * PURPOSE and not on the path, because the path is configurable and two names
 * for one file would be two queues over it.
 */
var lockQueues = Object.create(null);

function fileLock(name, run) {
  var q = lockQueues[name] || (lockQueues[name] = { waiting: [], running: false });
  q.waiting.push(run);
  if (!q.running) nextLocked(name);
}

function ingestLock(run) { return fileLock('ingest', run); }

function nextLocked(name) {
  var q = lockQueues[name];
  var run = q.waiting.shift();
  if (!run) { q.running = false; return; }
  q.running = true;
  var done = false;
  var release = function () {
    // No path in the handler reaches this twice — each exit is a `return` on
    // `fail` or `finish` and there is exactly one of them per request — so
    // this guard does not fire today and no test can make it. It is here
    // because of what a double release WOULD do: shift two runs off the queue
    // and start both, which is the very fault this lock exists to stop, and a
    // future exit path that forgot the `return` would do it silently.
    if (done) return;
    done = true;
    // On its own tick, so this reply is handed to send() before the next
    // ingest's read begins and a slow read cannot sit in front of it.
    // Correctness does not rest on this — the append is already done by the
    // time release is called — so it is latency, not safety.
    setImmediate(function () { nextLocked(name); });
  };
  try {
    run(release);
  } catch (e) {
    // A throw before the handler reached a reply must not strand every later
    // upload behind a lock nobody holds. The rethrow keeps the fault visible.
    release();
    throw e;
  }
}

var readWaiters = null;

function readJournal(done) {
  if (readWaiters) { readWaiters.push(done); return; }
  readWaiters = [done];
  readJournalNow(function (rows, err, torn) {
    var waiting = readWaiters;
    readWaiters = null;
    waiting.forEach(function (fn) {
      // A throw in one caller must not starve the others now that they share a
      // read. Rethrown on its own tick so it still reaches the process the way
      // it did when every caller had a read of its own — swallowed here, a
      // fault in one endpoint would become silence in all of them.
      try { fn(rows, err, torn); }
      catch (e) { setImmediate(function () { throw e; }); }
    });
  });
}

function readJournalNow(done) {
  fs.stat(JOURNAL_PATH, function (statErr, st) {
    if (statErr) {
      journalCache = null;
      // Nothing recorded yet is not an error. Anything else is.
      return done(statErr.code === 'ENOENT' ? [] : null, statErr);
    }
    var c = journalCache;
    if (c && c.ino === st.ino && c.size === st.size && c.mtime === st.mtimeMs) {
      return done(c.rows, null, c.torn || 0);
    }
    var grew = c && c.ino === st.ino && st.size > c.size && st.mtimeMs >= c.mtime;
    // Same inode and larger is not proof of an append. `cp backup journal`
    // rewrites the file in place, keeps the inode, and can leave it larger —
    // and a tail read from the old offset would then bolt the middle of one
    // file onto the rows of another. So the last complete line that was
    // parsed is kept, read again first, and if it is no longer there this is
    // not the file that was parsed, and it is read from the start.
    //
    // The whole line, not its last few bytes. The first version kept sixty-
    // four and a rewrite sailed through it: every row this program writes
    // ENDS in the same fixed fields — `"whole": true, "settled": true, ...}`
    // — and differs at its start, where the id and the timestamp are. A test
    // fixture with the same shape produced three offers where there were two.
    var mark = grew ? c.mark : Buffer.alloc(0);
    var from = grew ? c.offset - mark.length : 0;
    fs.open(JOURNAL_PATH, 'r', function (openErr, fd) {
      if (openErr) {
        journalCache = null;
        return done(openErr.code === 'ENOENT' ? [] : null, openErr);
      }
      var want = Math.max(0, st.size - from);
      var buf = Buffer.alloc(want);
      fs.read(fd, buf, 0, want, from, function (readErr, n) {
        fs.close(fd, function () {});
        if (readErr) { journalCache = null; return done(null, readErr); }
        buf = buf.slice(0, n);
        if (grew) {
          if (!buf.slice(0, mark.length).equals(mark)) {
            journalCache = null;
            // ...and not readJournal: this call already owns the queue, so
            // going back through the front door would park it behind itself.
            return readJournalNow(done);
          }
          buf = buf.slice(mark.length);
        }
        // A COPY of the cached rows, never the cached array itself. Two
        // reads in flight after one append both start from the same cache,
        // and pushing onto its array from both left every new row in it
        // twice for the rest of the process: the offers page's tally
        // doubled, a pairing listed twice, /api/journal/newest reporting
        // more rows than the file held — which is the number sync.py
        // reconciles against. Measured: three concurrent reads after two
        // appended rows left `have` at 9 for a file of 5 lines. Each reader
        // builds its own array now and whichever finishes last stores a
        // correct one. The mid-write line is taken back at the same time.
        var rows = grew ? c.rows.slice(0, c.rows.length - (c.pending || 0)) : [];
        var cut = buf.lastIndexOf(10);                      // the last newline
        // Counted on the COMPLETE lines only, and that distinction is the whole
        // of the rule. A line with no newline after it is not torn, it is the
        // row being written right now — the scanner appends while this reads —
        // and counting it would report a fault on every busy shift. It becomes
        // a complete line on the next append either way: journal.py starts a
        // fresh line when the last one never finished, so a stub left by a
        // power cut is terminated before the next row goes on, and it is
        // counted here the moment it is.
        var torn = { n: grew ? (c.torn || 0) : 0 };
        parseLines(buf.slice(0, cut + 1).toString('utf8'), rows, torn);
        var pending = parseLines(buf.slice(cut + 1).toString('utf8'), rows, null);
        // The last complete line, newline included: everything after the
        // newline before it. `mark` is at least the previous last line, so
        // the new one is entirely in hand even when this read added no
        // newline at all.
        var whole = Buffer.concat([mark, buf.slice(0, cut + 1)]);
        var prev = whole.length > 1 ? whole.lastIndexOf(10, whole.length - 2) : -1;
        journalCache = { ino: st.ino, size: st.size, mtime: st.mtimeMs,
                         offset: from + mark.length + cut + 1, pending: pending,
                         mark: whole.slice(prev + 1),
                         torn: torn.n,
                         rows: rows };
        done(rows, null, torn.n);
      });
    });
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
/* ...overridable, for one reason: the branch that asks whether THIS machine's
 * clock is set is otherwise unreachable from a test, because a suite cannot
 * move the system clock. That branch is not decoration — without it, a ceiling
 * taken off an unset clock answers `newest: 0` and loses more than the fault it
 * guards. An unreachable guard is how this session found a stuck outline going
 * unreported for a whole shift, so this one gets a seam.
 *
 * Same shape as SCREENING_MS and HOLD_GRACE_MS. Validated, and the default is
 * untouched: a value that is not a positive number is ignored rather than
 * believed, because a typo here would silently move what counts as a moment. */
var _clockAfterEnv = Number(process.env.CLOCK_BELIEVABLE_AFTER);
if (isFinite(_clockAfterEnv) && _clockAfterEnv > 0) {
  CLOCK_BELIEVABLE_AFTER = _clockAfterEnv;
}

/* ...and the other end of believable: 1 Jan 2100.
 *
 * A row can carry a moment that never happened. journal-client.js stamps `at`
 * from the phone's own Date.now(), and a phone with a wrong clock — or a
 * corrupted row — lands whatever it says in the append-only journal, which
 * nothing can go back and edit. This file already knows it: three places clamp
 * an incoming `since` against this exact number and call it "an epoch-ms moment
 * in this century", and one of them was written after a row stamped 1e20 took
 * the whole server down from inside a file callback.
 *
 * Named here because it was written out four times and the place that needed it
 * most did not have it — see /api/journal/newest. */
var CLOCK_BELIEVABLE_UNTIL = 4102444800000;

/* ...and how far ahead of THIS machine's own clock a row may be stamped.
 *
 * The ceiling above refuses the year 5138, which is what a corrupted row looks
 * like. It does not refuse what a WRONG CLOCK looks like, and that is the
 * common case: journal-client.js stamps `at` from the phone's own Date.now(),
 * so a phone a month fast lands a row a month ahead — comfortably inside this
 * century, comfortably past 1 Jan 2100's reach.
 *
 * That one row stops the backup. /api/journal/newest answers with it, sync.py
 * sets `floor = newest - 1h`, and from that tick no real offer is ever at or
 * above the floor again. Measured against the real server: a rig journal of 40
 * offers plus one row stamped now+45 days, then six ordinary ticks with five
 * offers appended before each — rig 71 rows, copy 41, 30 missing, exit 0,
 * .synced stamp refreshed, doctor green. Every row written after the poison
 * landed, and silent at every step, which is exactly the failure the paragraph
 * at /api/journal/newest already describes for the 1e20 case. The ceiling added
 * for that one was set too far out to catch this one. */
var CLOCK_AHEAD_SLACK = 24 * 60 * 60 * 1000;

/* The newest moment a row may claim, asked of this machine's own clock.
 *
 * Guarded on whether that clock is worth asking. This same file runs on the Pi,
 * which has no RTC and boots in 1970 until NTP arrives — CLOCK_BELIEVABLE_AFTER
 * above exists for exactly that. A ceiling taken off an unset clock would put
 * EVERY row above it and answer `newest: 0`, which loses far more than the
 * fault being fixed: measured on a 1,225-row journal, 606 offers silently
 * dropped in the default configuration with no poison row present at all.
 *
 * So when the clock cannot be trusted, fall back to the fixed ceiling. That is
 * no better than today and no worse, and today does not lose anything here. */
function futureCeiling() {
  return Date.now() >= CLOCK_BELIEVABLE_AFTER
    ? Math.min(CLOCK_BELIEVABLE_UNTIL, Date.now() + CLOCK_AHEAD_SLACK)
    : CLOCK_BELIEVABLE_UNTIL;
}

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
  /* Windowed for the same reason the offers page is, and by the same rule.
     This folded the whole journal and then kept the rows at or after `since` —
     so the driving screen, which asks about the shift in progress and nothing
     else, paid for every offer the rig has ever read, on a poll, on the loop
     that also feeds the camera panel.
     `early` still counts, because rowsFor keeps every pre-clock row on purpose:
     a Pi boots in 1970 and those rows are in no window by construction, and
     this figure is how the driver is told they exist. */
  var offers = latestPerOffer(rows, since);
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
    // ...and what those were worth, net, off the SAME rows the count comes
    // from. journal.html's netTotal, line for line: pay less the running cost
    // the row itself recorded, and the cost carried separately so the panel
    // can say "after costs" only when something was actually taken off. The
    // driving screen said "took 3" all shift and never what the three were
    // worth, which is the one number a driver wants at nine at night.
    earned: counted.filter(function (o) { return o.accepted; })
      .reduce(function (t, o) {
        var c = (typeof o.cost === 'number' && isFinite(o.cost)) ? o.cost : 0;
        return t + (o.pay || 0) - c;
      }, 0),
    earnedCost: counted.filter(function (o) { return o.accepted; })
      .reduce(function (t, o) {
        return t + ((typeof o.cost === 'number' && isFinite(o.cost)) ? o.cost : 0);
      }, 0),
    median: percentileOf(rates, 0.5),
    beforeClock: early
  };
}

// One answer, kept until the journal changes underneath it.
//
// The parse is synchronous once the file is in hand — split, then a JSON.parse
// per line — and it runs on the event loop that also drives the 12ms MJPEG tick
// and touches the file telling the scanner somebody is watching. The live file
// reaches 64MB before it rolls — at most about twelve weeks at the 5.7MB a
// week rpi/journal.py's WEEK_BYTES measures — and a third of that in real
// rows, 22.4MB, parses in 64-223ms on the development container (see
// parseLines' caller above) and more on a Pi 4, so a page that asks
// repeatedly cannot be paying that every time. /api/journal/newest already sets the house budget for a journal-reading
// GET at "every few minutes"; this keeps to it and then some.
//
// Keyed on SIZE as well as mtime because the file is append-only apart from the
// 64MB roll, so size is monotonic where mtime granularity is not guaranteed.
// The cached value is the finished summary. The parsed rows have a cache of
// their own now, in readJournal, and latestPerOffer copies every row it
// writes `hidden` or `accepted` onto — so this one stays a cache of the
// answer, keyed the same way, and does not reach into the other.
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
      // `text` the same way, and for a reason measured on this driver's own
      // export rather than argued about.
      //
      // It is what the reader read, line breaks and all, because the line
      // breaks are the part a later question is most likely to need. Put in a
      // cell raw and quoted, that is legal CSV — a quoted field may contain
      // newlines, every proper reader handles it, and the 104 records in that
      // export all have their 37 cells. It is also 2076 physical lines for 104
      // offers, 103 of the 104 spanning more than one. `wc -l` says 2075
      // offers. head, grep, a five-line script and any importer that splits on
      // newlines all say something different from the truth, and none of them
      // says it is guessing.
      //
      // JSON has the property wanted here: the text round-trips exactly, and
      // one record is one line. `scans` is already encoded this way, two lines
      // up, for the neighbouring version of the same problem.
      if (k === 'text' && typeof v === 'string') v = JSON.stringify(v);
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

/* What /api/status answers, as an object rather than as a response.
 *
 * Its own function because two things now ask it the same question: the
 * endpoint, and 📷 Snap, which keeps what the endpoint would have said at the
 * moment of the press as status.json beside the picture of the panel. Two
 * copies of this object would be two answers to "what was on the rig when
 * this was taken" free to drift apart, and the whole use of a snap is that
 * it can be held up against the screen it came from. */
function statusNow() {
  return {
    scanner: {
      enabled: scannerEnabled(),
      calibrated: calibrated(),
      phase: scanner.phase,
      running: !!scanner.proc,
      restarts: scanner.restarts,
      // ...and how many times it has fallen over ALL EVENING, which the
      // number above deliberately does not say.
      //
      // `restarts` is a backoff ladder and resets after any run longer than
      // HEALTHY_RUN_MS, which is right for a backoff and wrong for a record:
      // a rig that hit four unrelated hiccups across a shift, each time
      // coming back and running for minutes, answered this endpoint with
      // `restarts: 0`. Nothing anywhere said the camera had gone down at
      // all.
      //
      // This tally was already being kept for exactly that and was read by
      // nothing. Same argument as `wedged` below, which the comment there
      // states: "a lifetime tally, deliberately not cleared when the
      // replacement starts: it is the only trace a wedge leaves".
      fell: scanner.lifetimeRestarts || 0,
      // Times it was killed for going quiet while still running, as opposed
      // to times it fell over on its own. The two have different causes and
      // a count that merges them explains neither.
      wedged: scanner.wedged || 0,
      // The sightings the scanner has sent, by screen type (countSighting),
      // and only the counts: the lines themselves go nowhere.
      screens: Object.assign({}, scanner.screens),
      // A successful restart clears `error`, as it should — there is no
      // current problem. This is what is left to say a camera went quiet at
      // all, which is the difference between "it is fine now" and "it is fine
      // now for the third time this evening".
      wedgedAt: scanner.wedgedAt || null,
      startedAt: scanner.started,
      // What went wrong with this process — it could not start, could not be
      // attached to, went quiet, or exited — and never what a working one
      // printed.
      error: scanner.error,
      // ...and what it has printed: the last lines of its stderr, which on a
      // running rig are libraries talking. See `stderr` where `scanner` is
      // built for why the two are not one field.
      stderr: scanner.stderr
    },
    // A copy re-stacked against the hold as it is NOW, exactly as the
    // event stream's replay does. broadcast() stacks the stored reading
    // itself, so served raw it carried the pair line computed at read
    // time: press Drop and reload, and the panel showed "+ $25–50/hr with
    // the one you have" under the verdict while the Drop button beside it
    // was hidden because nothing was held.
    last: scanner.last ? withStack(Object.assign({}, scanner.last), Date.now()) : null,
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
      return h ? Object.assign({ pay: h.pay, minutes: h.minutes, holdId: holdIdOf(h),
                   // ...and its app, for the offers page's In car list.
                   app: h.app || null,
                   // ...who pinned it ('server', 'place', or null for Map
                   // view) is heldEndState's `endBy`, merged in below with
                   // the rest of the GPS drop's state — pinned, arrived, and
                   // why not armed.
                   // ...and the place the phone printed for its stop, which
                   // the end is searched by when its door is not on the
                   // NucBox (searchHeldPlace).
                   place: placeOf(h),
                   // ...and, when this server found the door by asking again
                   // with the street's type word left out (searchHeldRetry),
                   // the street it asked: "1830 <Name> Creek SW" for a door
                   // printed "...Creek Cts SW". Null otherwise.
                   endAsked: (function () {
                     var pin = heldEndPin(h);
                     return pin && pin.asked ? pin.asked : null;
                   }()),
                   // ...and how many of its pickups the guard holds, from Map
                   // view or this server's search (keepPickupPin), merged
                   // in below: pickupsPinned, pickupsHow, pickupsWhy
                   // (pickupState).
                   // Where it ends, and whether that came off the card or
                   // off a scan of the screen after the accept. The panel
                   // needs the difference: a card-derived dropoff is a
                   // cross-street, a scanned one is a full address, and the
                   // button that asks for one should stop offering itself
                   // once it has been answered.
                   dropoff: h.dropoff || null,
                   dropoffScanned: !!h.dropoffScanned,
                   // ...and where each of its ends came from: the assembler's
                   // `fields`, {value, from, conf, at, screen} each. See
                   // Assemble.fieldsOf, which makes them for a hold restored
                   // from a file written before they existed.
                   fields: Assemble.fieldsOf(h),
                   // ...and the planner pages it is still waiting on.
                   pending: Assemble.pending(assembly),
                   // ...and the Trip Planner's stops, when ⌖ read one while
                   // this order was in the car, with the scanner's reason for
                   // filing none of them as its end: {stops, unfiled}. Kept
                   // as long as the panel keeps them, which is shorter than
                   // the scanned destination beside it — see forgetPlanner.
                   planner: h.planner || null,
                   // ...and a batched trip (Assemble.batchPlan): `batch`, its
                   // doors {line, name, expectedBy, key} in `drops` — the end
                   // above is the last of them — or, with none, why the
                   // planner's dropoffs were not taken for one (`batchWhy`:
                   // 'card end elsewhere', 'no card street', 'address', 'an
                   // add-on'; null when no list of two dropoffs was seen).
                   batch: batchDrops(h) !== null,
                   drops: batchDrops(h) !== null ? h.drops : null,
                   batchWhy: batchDrops(h) !== null ? null
                     : Assemble.batchWhy(assembly, h),
                   // ...and its card's fix and size, for Map view's check of
                   // where it ends. See cardOf.
                   card: h.card || null,
                   heldMs: Math.max(0, Date.now() - h.acceptedAt) },
                   // ...and 'offers' when the offers page's ✓ took it
                   // (offersTickHolds); absent for the panel's Took.
                   h.tookOn ? { tookOn: h.tookOn } : {},
                   // endPinned, arrived, endWhy: see heldEndState.
                   heldEndState(h), pickupState(h)) : null;
    }()),
    // Every order in the car and the addresses waiting for an owner, while
    // carrying two is on (ordersForPanel); and whether it is.
    carryTwo: carryTwo(),
    orders: carryingTwo(Date.now()) ? ordersForPanel(Date.now()) : undefined,
    unowned: carryingTwo(Date.now()) ? Assemble.unowned(assembly) : undefined,
    // ...and the chooser, if one is open (openChooser).
    chooser: chooserForPanel(Date.now()),
    lastAgeMs: (scanner.last && typeof scanner.last.at === 'number')
      ? Math.max(0, Date.now() - scanner.last.at) : null,
    heardAgeMs: scanner.heardAt
      ? Math.max(0, Date.now() - scanner.heardAt) : null,
    // The last heartbeat, as the scanner sent it: the GPS's state and the
    // age of its newest fix, the Pi's temperature and throttling with the
    // reason for either one that could not be read, whether the heat guard
    // is putting off the reads nobody pressed for, and the five notices
    // that already rode it. Without this every one of them was on the event
    // stream and nowhere else, so the status link — the one place a person
    // diagnosing a rig is sent — could not say whether the GPS had a fix or
    // the Pi was throttling.
    //
    // Its age rather than the `at` this server stamped it with on arrival:
    // the same duration-not-timestamp rule as everything above, because
    // whatever reads this does not share this machine's clock. Cleared with
    // the process, because every word in it is about that process.
    beat: (function () {
      if (!scanner.beat) return null;
      var b = Object.assign({}, scanner.beat);
      var at = b.at;
      delete b.at;
      delete b.alive;
      b.ageMs = Math.max(0, Date.now() - at);
      return b;
    }()),
    status: scanner.status
  };
}

/* ---------- 📷 Snap: the panel as it looked, kept to be shown to someone ----
 *
 * Asked for in the driver's own words: "a button to take a screenshot on the
 * Pi rig so I can easily capture screen shots of the program, and what it
 * looks like to share with you". The panel is a browser on the Pi's own
 * display, driven with a bluetooth mouse, so there is no Print Screen key in
 * reach and nothing on the glass that can take a picture of itself. Showing
 * anybody what it looked like meant a phone held up to the windscreen.
 *
 * One press keeps a folder, named for the moment on this machine's clock,
 * holding the things that between them answer "what was it doing":
 *
 *   panel.png    the Pi's display, taken by the desktop's own tool — the page
 *                as the rig painted it, which no other browser reproduces
 *   camera.jpg   the live picture the scanner last wrote, and how old it was
 *   status.json  what /api/status would have answered at the press: the
 *                reading on the panel, the reader's text when the reading
 *                carries it, the offer on record and the order in the car
 *   reader.jpg   the card the scanner last read, as it came off the warp —
 *                the picture tesseract's input was made from — which nothing
 *                else keeps: the camera picture is the whole scene, and a
 *                misread is a question about the few hundred pixels read
 *   reader.json  the scanner's own account of that read — its time, text,
 *                parse and rate, the offer it has on record, its health
 *                counters, its last heartbeat and the phone's GPS — written
 *                by the scanner into this folder when asked (see askReader)
 *
 * ...and snap.json, which says which of those it has and, for each one it has
 * not, why. A folder with no panel.png and nothing saying why is the second
 * fault class in the shape of a directory: "no screenshot tool", "no desktop
 * to take it from" and "the press never arrived" look identical, and they want
 * three different fixes.
 *
 * Beside the journal, like holding.json and places.json, so a machine that
 * moves its data with JOURNAL moves these with it. On the rig that is rpi/,
 * inside the checkout, which .gitignore covers and rpi/test_lint.py holds it
 * to: a picture of a phone with a customer's address on it does not belong in
 * a public remote. None of it goes out through the static handler — rpi/ is
 * refused there by name — only through /api/snaps below, which takes a folder
 * and a file from two short lists and never a path, and through the bundle
 * beside it (sendSnapBundle), which takes folders from the first of those
 * lists and files from the second.
 */
var SNAPS_DIR = path.join(path.dirname(JOURNAL_PATH), 'snaps');

/* How many to keep. The oldest go first, and the reply and the log name them.
 *
 * A count rather than a size, because a count is what a driver can hold in
 * their head — "the newest hundred are there" — and the size of one is
 * measured rather than unknown. The rig's three real snaps of 8 October, all
 * six files each, are 276kB (the Jimmy John's card), 323kB (the Est. delivery
 * card) and 246kB (a Trip Planner): panel.png is 180–214kB of each (scrot,
 * X11, the 1024x600 panel), the camera picture 18–58kB, reader.jpg 24–45kB and
 * the three records 5–8kB together. A note adds 14 bytes and its own length
 * to snap.json. So a hundred is about 28MB on the one part of the rig that
 * wears out — more than the 16MB the kept card pictures are allowed
 * (SCANS_KEEP, 400 at ~40kB), and asked for: the driver snaps a series per
 * offer — waiting for offers, the card, after the accept, the Trip Planner —
 * and forty was ten offers' worth.
 *
 * Overridable for the reason HOLD_GRACE_MS is: a check that has to press a
 * hundred times to watch the hundred-and-first arrive is a check nobody
 * runs. */
var SNAPS_KEEP = Math.floor(Number(process.env.SNAPS_KEEP));
if (!isFinite(SNAPS_KEEP) || SNAPS_KEEP < 1) SNAPS_KEEP = 100;

/* How long the screenshot tool may take before it is killed and the snap is
 * kept without it. Well inside the twenty seconds the panel itself waits for
 * any answer (POST_TIMEOUT_MS in live.html, ASK_MS in snaps.html), so a tool
 * that hangs comes back as a reason on the control rather than as the panel
 * giving up on the press and the driver left not knowing whether anything was
 * kept. rpi/test_server.py hangs a tool against this default and holds the
 * answer inside the pages' own deadline, read out of the pages. Overridable so
 * the other hang checks need not wait it out. */
var SNAP_TOOL_MS = Number(process.env.SNAP_TOOL_MS);
if (!isFinite(SNAP_TOOL_MS) || SNAP_TOOL_MS <= 0) SNAP_TOOL_MS = 8000;

/* Past this the camera picture is still kept — it is evidence of what the
 * scanner last saw — but it is never presented as what was in front of the
 * camera at the press.
 *
 * The picture's own age, from the file's mtime: the question is whether THIS
 * picture is the one at the press, and only the picture can answer it. A
 * running scan loop rewrites it every SNAPSHOT_IDLE = 3.0s with nobody
 * watching (rpi/scan_pi.py) and thirty times a second with somebody watching,
 * so twelve seconds is four idle rewrites missed. rpi/test_server.py reads
 * SNAPSHOT_IDLE out of scan_pi.py and holds a picture two rewrites old as
 * current and one six rewrites old as old.
 *
 * It is not the panel's rule, and the two can disagree. live.html dims its
 * picture on silence from the scanner (STALE_MS, timed from the last message
 * the page heard), which asks how long since the scanner said anything; this
 * asks how old the picture is. The same twelve seconds, two different clocks.
 * panel.png beside it shows what the panel said. */
var SNAP_FRAME_STALE_MS = 12000;

// The folder names this server makes, and the files it puts in them. The only
// two things /api/snaps/<name>/<file> will accept, so nothing typed into that
// URL is ever a path.
var SNAP_NAME = /^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(-\d{2})?$/;
var SNAP_FILES = ['panel.png', 'camera.jpg', 'status.json', 'snap.json',
                  'reader.jpg', 'reader.json'];
// How every PNG opens — its signature, then its image header, which the format
// requires first — and how every PNG ends: the empty IEND chunk and its CRC.
// The tail is what a tool cut off part way, or a card that filled under it,
// does not have.
var PNG_HEAD = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
                            0, 0, 0, 13, 0x49, 0x48, 0x44, 0x52]);
var PNG_TAIL = Buffer.from([0, 0, 0, 0, 0x49, 0x45, 0x4e, 0x44, 0xae, 0x42, 0x60, 0x82]);

// Sortable as text, in local time, because the name is what a person reads in
// a file listing: 2026-10-07_21-14-03. It sorts by the clock it was stamped
// on, which repeats one hour a year when the clocks go back; inside that hour
// two snaps can list out of order, and nothing is lost by it.
function snapStamp(when) {
  var two = function (n) { return (n < 10 ? '0' : '') + n; };
  return when.getFullYear() + '-' + two(when.getMonth() + 1) + '-'
       + two(when.getDate()) + '_' + two(when.getHours()) + '-'
       + two(when.getMinutes()) + '-' + two(when.getSeconds());
}

function spellAge(ms) {
  var s = Math.round(ms / 1000);
  if (s < 90) return s + 's';
  if (s < 90 * 60) return Math.round(s / 60) + ' min';
  return (s / 3600).toFixed(1) + 'h';
}

/* How long before `now` a stamp this machine wrote was, or null when that
 * cannot be known.
 *
 * Both are this machine's clock, so the subtraction looks safe, and it is not:
 * the Pi boots in 1970 and jumps when the network arrives, so a stamp written
 * before the jump and a `now` read after it are two different clocks. A snap
 * taken in the minute after boot and listed once the clock was set came out
 * 20,732 days old; one taken yesterday and listed on a rig that has just
 * rebooted came out 0s old, because the negative was clamped. A stamp or a now
 * below CLOCK_BELIEVABLE_AFTER is a clock nobody had set, and an age with one
 * of those on either side is not an age. Both below is no better: two unset
 * clocks can be two boots, each starting from 1970. */
function clockAge(stamp, now) {
  if (typeof stamp !== 'number' || !isFinite(stamp)) return null;
  if (stamp < CLOCK_BELIEVABLE_AFTER || now < CLOCK_BELIEVABLE_AFTER) return null;
  return Math.max(0, now - stamp);
}

/* Where the desktop is, for a server that was not started from it.
 *
 * Under the service this process has no session at all: systemd hands it no
 * XDG_RUNTIME_DIR, no WAYLAND_DISPLAY and no DISPLAY, so a screenshot tool run
 * with this process's environment finds nothing to photograph. It runs as the
 * account that installed it (User= in rpi/install-service.sh), which is the
 * account the Pi logs into the desktop as — so the session is this uid's, and
 * can be found where that uid's sessions always are.
 *
 * Wayland first. Raspberry Pi OS on a Pi 4 has run a Wayland compositor since
 * Bookworm — wayfire, and labwc on newer images — and both still give X
 * programs an X display, so a DISPLAY is usually there as well. An X tool
 * pointed at it photographs only the X windows on a Wayland desktop, which is
 * a picture that looks like an answer and is not one. */
function displaySession() {
  var runtime = process.env.XDG_RUNTIME_DIR
    || (typeof process.getuid === 'function' ? '/run/user/' + process.getuid() : '');
  var looked = [];
  if (runtime) {
    var names = [];
    if (process.env.WAYLAND_DISPLAY) names.push(process.env.WAYLAND_DISPLAY);
    try {
      // `wayland-1`, never `wayland-1.lock`, which sits beside every socket.
      fs.readdirSync(runtime).sort().forEach(function (n) {
        if (/^wayland-\d+$/.test(n) && names.indexOf(n) === -1) names.push(n);
      });
    } catch (e) { /* no runtime directory: nobody is logged in to a desktop */ }
    for (var i = 0; i < names.length; i++) {
      try {
        if (fs.statSync(path.resolve(runtime, names[i])).isSocket()) {
          return { kind: 'wayland',
                   env: { XDG_RUNTIME_DIR: runtime, WAYLAND_DISPLAY: names[i] } };
        }
      } catch (e) { /* named but not there; try the next */ }
    }
    looked.push('no wayland-* socket in ' + runtime);
  }
  var display = process.env.DISPLAY;
  if (!display) {
    try {
      if (fs.statSync('/tmp/.X11-unix/X0').isSocket()) display = ':0';
    } catch (e) { /* no X server either */ }
  }
  if (display) {
    var env = { DISPLAY: display };
    // An X server refuses a client that cannot show it the cookie, and the
    // service has no XAUTHORITY of its own. The desktop account's is where
    // the display manager left it.
    if (!process.env.XAUTHORITY) {
      var cookie = path.join(os.homedir(), '.Xauthority');
      try { fs.accessSync(cookie, fs.constants.R_OK); env.XAUTHORITY = cookie; } catch (e) { /* none */ }
    }
    return { kind: 'x11', env: env };
  }
  looked.push('no X display');
  return { kind: null, why: 'no display session found', detail: looked.join(', ') };
}

// The tool each kind of desktop takes a picture with, best first, and the
// argv each wants. An argv, never a command line: nothing here goes through a
// shell, so a path with a space or a quote in it is just a path.
var SNAP_TOOLS = {
  wayland: [{ bin: 'grim', argv: function (out) { return [out]; } }],
  x11: [{ bin: 'scrot', argv: function (out) { return [out]; } },
        { bin: 'import', argv: function (out) { return ['-window', 'root', out]; } }]
};
var SNAP_INSTALL = {
  wayland: { why: 'grim is not installed', fix: 'sudo apt install grim' },
  x11: { why: 'no screenshot tool is installed (scrot or import)',
         fix: 'sudo apt install scrot' }
};

// Found on PATH the way a shell would, without asking one.
function onPath(bin) {
  var dirs = (process.env.PATH || '').split(path.delimiter);
  for (var i = 0; i < dirs.length; i++) {
    if (!dirs[i]) continue;
    var full = path.join(dirs[i], bin);
    try {
      fs.accessSync(full, fs.constants.X_OK);
      if (fs.statSync(full).isFile()) return full;
    } catch (e) { /* not here */ }
  }
  return null;
}

/* panel.png, or the reason there is none. `done` is called exactly once. */
function takePanel(out, done) {
  var part = { what: 'panel', file: 'panel.png', saved: false };
  var session = displaySession();
  if (!session.kind) {
    return done(Object.assign(part, { why: session.why, detail: session.detail }));
  }
  var tool = null;
  var bin = null;
  for (var i = 0; i < SNAP_TOOLS[session.kind].length && !bin; i++) {
    tool = SNAP_TOOLS[session.kind][i];
    bin = onPath(tool.bin);
  }
  if (!bin) {
    return done(Object.assign(part, SNAP_INSTALL[session.kind],
                              { session: session.kind }));
  }
  part.tool = tool.bin;
  part.session = session.kind;
  var settled = false;
  var said = '';
  var timer = null;
  var finish = function (why) {
    if (settled) return;
    settled = true;
    clearTimeout(timer);
    if (why) {
      // Whatever a killed or failed tool left behind is not a picture of the
      // panel, and a half-written PNG beside a reason would be two answers.
      fs.unlink(out, function () {});
      part.why = why;
      return done(part);
    }
    // Exit 0 is the tool's word; the file is the evidence. A tool that
    // reports success over an empty, foreign or half-written file is a
    // picture nobody could open, kept under a name that promises one. So the
    // file has to open the way a PNG opens and end the way one ends; eight
    // bytes of signature alone was believed as a screenshot.
    fs.open(out, 'r', function (openErr, fd) {
      if (openErr) {
        part.why = tool.bin + ' finished without writing a picture';
        return done(part);
      }
      var head = Buffer.alloc(PNG_HEAD.length);
      var tail = Buffer.alloc(PNG_TAIL.length);
      fs.fstat(fd, function (statErr, st) {
        var size = statErr ? 0 : st.size;
        fs.read(fd, head, 0, head.length, 0, function (headErr, gotHead) {
          var whole = size >= head.length + tail.length;
          var tailAt = whole ? size - tail.length : 0;
          fs.read(fd, tail, 0, tail.length, tailAt, function (tailErr, gotTail) {
            fs.close(fd, function () {
              var bad = null;
              if (statErr || headErr || gotHead !== head.length || !head.equals(PNG_HEAD)) {
                bad = 'wrote something that is not a PNG';
              } else if (!whole || tailErr || gotTail !== tail.length || !tail.equals(PNG_TAIL)) {
                bad = 'wrote a PNG that stops before its end';
              }
              if (bad) {
                return fs.unlink(out, function () {
                  part.why = tool.bin + ' ' + bad;
                  done(part);
                });
              }
              part.saved = true;
              part.bytes = size;
              done(part);
            });
          });
        });
      });
    });
  };
  var child;
  try {
    child = spawn(bin, tool.argv(out), {
      env: Object.assign({}, process.env, session.env),
      stdio: ['ignore', 'ignore', 'pipe']
    });
  } catch (e) {
    return finish('could not start ' + tool.bin + ': ' + (e.code || e.message));
  }
  timer = setTimeout(function () {
    try { child.kill('SIGKILL'); } catch (e) { /* already gone */ }
    finish(tool.bin + ' did not finish in ' + spellAge(SNAP_TOOL_MS));
  }, SNAP_TOOL_MS);
  child.on('error', function (err) {
    finish('could not start ' + tool.bin + ': ' + (err.code || err.message));
  });
  // Absent when the process is out of descriptors — see startScanner, where
  // reading `.on` off a missing pipe took the whole server down.
  if (child.stderr) {
    child.stderr.on('data', function (c) { said = (said + c).slice(-400); });
  }
  child.on('close', function (code, signal) {
    if (code === 0) return finish(null);
    var last = said.trim().split('\n').pop() || '';
    finish(tool.bin + ' failed (' + (signal || 'exit ' + code) + ')'
           + (last ? ': ' + last.slice(0, 120) : ''));
  });
}

/* Why no scanner can have anything for a snap, or null when one is running.
 * One answer for the camera picture and the reader's crop alike, which were
 * two questions asked of the same two facts — and one answer to whether that
 * is a part missing or a part that does not apply here. A scanner that is not
 * running is a part missing. A machine that runs none, the copy at home, has
 * no camera picture to keep any more than a reader to ask, and the camera was
 * filed as missing there while the reader's two were filed as not applying:
 * one reason, two classes, in the journal row, the panel's line and the
 * problems snaps.html lists. Given as the fields a part takes, so the reason
 * and its class cannot travel apart. */
function scannerAbsent() {
  if (!scannerEnabled()) return { why: 'no scanner runs on this machine', applies: false };
  if (!scanner.proc) return { why: 'the scanner is not running' };
  return null;
}

/* camera.jpg — the picture /api/frame.jpg would have served at the press —
 * with its age, or the reason there is none.
 *
 * One picture, not every candidate: framePath() already takes the freshest of
 * them, and the others are by construction older copies of the same view.
 *
 * Opened once and both dated and copied through that one descriptor. The
 * scanner renames a new frame into place up to thirty times a second, so a
 * stat by name and a copy by name can be two different frames, and the age
 * written down would belong to the other one. */
function keepCamera(out, done) {
  var part = { what: 'camera', file: 'camera.jpg', saved: false };
  var none = function () { return scannerAbsent() || { why: 'no camera picture yet' }; };
  fs.open(framePath(), 'r', function (openErr, fd) {
    if (openErr) return done(Object.assign(part, none()));
    fs.fstat(fd, function (statErr, st) {
      if (statErr || !st.isFile() || !st.size) {
        return fs.close(fd, function () { done(Object.assign(part, none())); });
      }
      fs.readFile(fd, function (readErr, data) {
        fs.close(fd, function () {
          if (readErr) {
            return done(Object.assign(part, {
              why: 'could not read the camera picture: ' + (readErr.code || readErr.message) }));
          }
          fs.writeFile(out, data, function (writeErr) {
            if (writeErr) {
              // A card that fills part way through leaves the file made and
              // torn, under a name the list would then show as a picture
              // beside a reply that said none was kept. It goes first.
              return fs.unlink(out, function () {
                done(Object.assign(part, {
                  why: 'could not keep the camera picture: ' + (writeErr.code || writeErr.message) }));
              });
            }
            part.saved = true;
            part.bytes = data.length;
            var now = Date.now();
            part.ageMs = clockAge(st.mtimeMs, now);
            if (part.ageMs === null) {
              // Neither current nor old: nothing can say which.
              part.stale = null;
              part.why = 'camera picture of unknown age: ' + (now < CLOCK_BELIEVABLE_AFTER
                ? 'the rig\'s clock is not set'
                : 'it was written before the rig\'s clock was set');
              return done(part);
            }
            part.stale = part.ageMs > SNAP_FRAME_STALE_MS;
            // Kept, and said to be old in the same breath. The reason the
            // scanner is not refreshing it goes with it where there is one,
            // because "old" alone does not say whether to wait or to look.
            if (part.stale) {
              var absent = scannerAbsent();
              part.why = 'camera picture ' + spellAge(part.ageMs) + ' old'
                       + (absent ? ', ' + absent.why : '');
            }
            done(part);
          });
        });
      });
    });
  });
}

/* reader.jpg and reader.json: what only the scanner has, asked of it.
 *
 * status.json says what the panel showed; it cannot say what the reader was
 * looking at. The card cropped off the warp — what preprocess() turns into
 * tesseract's input — is made, read and dropped inside the scan loop, the
 * health counters reach a log line every two minutes, and
 * the phone's GPS is reported nowhere — so the one process holding them is
 * asked. A press writes a request into the handoff directory naming its
 * folder, through a temporary of its own and a rename like every request
 * here, and the scan loop answers into the folder once: snap_requested and
 * answer_snap in rpi/scan_pi.py.
 *
 * Waited for, never blocked on: the folder is looked in every
 * SNAP_READER_POLL_MS on a timer, for SNAP_READER_MS, and then the part is
 * said to be missing. The scanner refuses a request older than its
 * SNAP_ANSWER_WINDOW, a second inside this, so no answer can land in a folder
 * after its snap.json has said there was none.
 *
 * One press at a time. The request is one file, so a second press written
 * before the loop took the first would replace it, and the first would wait
 * out four seconds for an answer that went to the other: "the scanner did not
 * answer" said of a scanner that did. The second waits its turn instead.
 *
 * Where no scanner runs — the copy at home — neither part applies, and they
 * are recorded as that, with the reason, rather than as parts that failed:
 * scannerAbsent's answer, the camera's too. */
var SNAP_READER_MS = 4000;
var SNAP_READER_POLL_MS = 100;
var readerAsks = [];

/* Both reader parts, missing for one reason: `{why}`, or scannerAbsent()'s
 * answer, which says whether they apply here at all. */
function readerMissing(absent) {
  return [Object.assign({ what: 'crop', file: 'reader.jpg', saved: false }, absent),
          Object.assign({ what: 'reader', file: 'reader.json', saved: false }, absent)];
}

/* `done([crop, reader])`, once. `panelOffer` is the offer id /api/status had
 * at the press, which the reader's own is held against. */
function askReader(dir, panelOffer, done) {
  if (!scannerEnabled()) return done(readerMissing(scannerAbsent()));
  readerAsks.push({ dir: dir, panelOffer: panelOffer, done: done });
  if (readerAsks.length === 1) askNextReader();
}

function askNextReader() {
  var ask = readerAsks[0];
  if (!ask) return;
  var finish = function (parts) {
    readerAsks.shift();
    ask.done(parts);
    askNextReader();
  };
  // At its turn rather than at its press: a scanner that fell over while the
  // press before this one waited is not running now.
  var absent = scannerAbsent();
  if (absent) return finish(readerMissing(absent));
  var tmp = partName(SNAP_ASK_PATH);
  var failed = function (err) {
    fs.unlink(tmp, function () {});
    finish(readerMissing({ why: 'could not ask the scanner: ' + (err.code || err.message) }));
  };
  fs.writeFile(tmp, JSON.stringify({ folder: ask.dir }), function (writeErr) {
    if (writeErr) return failed(writeErr);
    fs.rename(tmp, SNAP_ASK_PATH, function (renameErr) {
      if (renameErr) return failed(renameErr);
      // A timer for the deadline, not a clock: the Pi's clock jumps when the
      // network sets it, and a wait measured across that is not four seconds.
      var gaveUp = false;
      var deadline = setTimeout(function () { gaveUp = true; }, SNAP_READER_MS);
      (function look() {
        fs.readFile(path.join(ask.dir, 'reader.json'), 'utf8', function (err, text) {
          if (!err) {
            clearTimeout(deadline);
            return readerAnswered(ask, text, finish);
          }
          if (gaveUp) {
            return finish(readerMissing({ why: 'the scanner did not answer in '
                                               + spellAge(SNAP_READER_MS) }));
          }
          setTimeout(look, SNAP_READER_POLL_MS);
        });
      }());
    });
  });
}

/* The answer, as two parts. reader.json arrives last (answer_snap writes the
 * crop first), so by the time it is here reader.jpg is there or it is not. */
function readerAnswered(ask, text, finish) {
  var said = null;
  try { said = JSON.parse(text); } catch (e) { said = null; }
  if (!said || typeof said !== 'object') said = null;
  var reader = { what: 'reader', file: 'reader.json', saved: true,
                 bytes: Buffer.byteLength(text) };
  if (!said) {
    reader.why = 'reader.json cannot be read';
  } else {
    // Which card the reader has on record, against the one the panel had at
    // the press. Both are the scanner's record of the last card that landed —
    // this server's copy, off the scanner's offer line, as it stood at the
    // press, and the scanner's own as it stands at its answer — so they name
    // two cards when one landed in between, and reader.jpg and reader.json
    // are then a read made after the press, not the one status.json's offer
    // came from; or when the scanner was restarted and resumed another than
    // the one this server kept. Either way the snap's own two accounts are of
    // different cards, and that is said first (see snapSaid). Not a card that
    // has not landed: a verdict for one leaves both on the card before it.
    //
    // Both, or nothing is said. A side with no card on record is not a second
    // card: a scanner restarted after its last card was too old to resume
    // (RESUME_WINDOW_MS in rpi/journal.py) has none while this server keeps
    // the one it was told about, and a server started under a scanner that
    // resumed one has none of its own. Each was said as "reader none, panel
    // o-1" on every press until the next card landed. The two ids are in
    // snap.json either way.
    reader.offer = said.offer && typeof said.offer === 'object' ? said.offer.id || null : null;
    reader.panelOffer = ask.panelOffer;
    if (reader.offer && reader.panelOffer && reader.offer !== reader.panelOffer) {
      reader.warn = 'reader and panel on different cards: reader '
                  + (reader.offer || 'none') + ', panel ' + (reader.panelOffer || 'none');
    }
  }
  fs.lstat(path.join(ask.dir, 'reader.jpg'), function (err, st) {
    var crop = { what: 'crop', file: 'reader.jpg', saved: false };
    if (!err && st.isFile()) {
      crop.saved = true;
      crop.bytes = st.size;
    } else {
      crop.why = said && typeof said.noCrop === 'string' ? said.noCrop
        : 'the scanner kept no reader.jpg and did not say why';
    }
    finish([crop, reader]);
  });
}

// What a part that is missing is called, in the line the panel shows.
var SNAP_NOUN = { panel: 'screenshot', camera: 'camera picture', status: 'status',
                  crop: 'reader crop', reader: 'reader record' };

/* The one line that says what a snap holds: the panel's message, the log
 * line, and the summary the snaps page shows under each one. Written once so
 * the three cannot word the same snap three ways. The screenshot first,
 * because it is what the press was for and the line is cut from the end —
 * after one thing only: the reader and the panel on different cards (see
 * readerAnswered), which says the snap's own pictures and records do not
 * belong together, and anybody laying reader.jpg beside status.json's number
 * would be laying two cards side by side.
 *
 * Parts missing for one reason are said once, so a scanner that is down is
 * "no camera picture, reader crop or reader record: the scanner is not
 * running" rather than the same reason three times on a line that is cut.
 * A part that does not apply on this machine is not missing, and is not said. */
function snapSaid(parts, notes) {
  var warns = [];
  var bits = [];
  var missing = Object.create(null);
  parts.forEach(function (p) {
    if (p.warn) warns.push(p.warn);
    if (p.applies === false) return;
    if (p.saved) {
      if (p.why) bits.push(p.why);
      return;
    }
    if (!missing[p.why]) {
      missing[p.why] = [];
      bits.push({ why: p.why, nouns: missing[p.why] });
    }
    missing[p.why].push(SNAP_NOUN[p.what]);
  });
  var said = warns.concat(bits.map(function (b) {
    if (typeof b === 'string') return b;
    var n = b.nouns;
    return 'no ' + (n.length === 1 ? n[0] : n.slice(0, -1).join(', ') + ' or ' + n[n.length - 1])
         + ': ' + b.why;
  }), notes);
  return 'saved' + (said.length ? ' — ' + said.join('; ') : '');
}

/* The snap folders on disk, oldest first, and whether the directory could be
 * read at all. Synchronous, like the hold file: a hundred folders are a
 * hundred directory entries, this is asked for by a press rather than on a
 * timer (once per name in a request: a bundle of a hundred is a hundred
 * reads, 5ms on the development box), and
 * a callback ladder here would be the most intricate code in the feature for
 * no gain. Real directories only — a link dropped in among them is listed by
 * nothing and served by nothing.
 *
 * This and snapFiles below are the whole of what counts as a snap, and both
 * the list and /api/snaps/<folder>/<file> ask them. Serving used to have a
 * rule of its own — a name the right shape, then realpath inside snaps/ — so
 * a link named like a snap, pointing at a folder in snaps/ that is not one,
 * was served while the list never showed it. */
function snapNames() {
  try {
    return {
      names: fs.readdirSync(SNAPS_DIR, { withFileTypes: true })
        .filter(function (d) { return d.isDirectory() && SNAP_NAME.test(d.name); })
        .map(function (d) { return d.name; })
        .sort(),
      unreadable: null
    };
  } catch (e) {
    // Missing is an empty list. Anything else is a list that cannot be
    // read, which is a different answer and is given as one.
    return { names: [], unreadable: e.code === 'ENOENT' ? null : (e.code || 'unknown') };
  }
}

/* ...and the files in one: the ones a press writes (SNAP_FILES), each a real
 * file. A link is not one, whatever it is named and wherever it points. */
function snapFiles(name) {
  var files = [];
  SNAP_FILES.forEach(function (file) {
    try {
      var st = fs.lstatSync(path.join(SNAPS_DIR, name, file));
      if (st.isFile()) files.push({ file: file, bytes: st.size });
    } catch (e) { /* not in this one */ }
  });
  return files;
}

/* The folders a press has made and not yet finished: claimed, being filled,
 * and not yet sealed with its snap.json or removed for holding nothing. */
var snapsFilling = {};

/* Whether a snap is still being kept, which is one question with one answer
 * for everything that asks it: pruning, which never removes one; the list,
 * which says so in place of its line; a note, which is refused until it is
 * kept; and a bundle, which is refused too. Until seal() the folder can hold a
 * screenshot the tool is part way through writing and no snap.json, and a
 * bundle used to be built of it anyway: a screenshot tool that wrote half of
 * the rig's real 180,177-byte Trip Planner panel.png and took three seconds
 * over the rest, bundled in between, was handed on with 90,088 bytes of it
 * inline as "the rig's screen", under "no snap.json in this folder, so
 * nothing says what is missing" — while a note on the same snap was refused
 * as still being kept. The window is the press itself: the screenshot's up
 * to SNAP_TOOL_MS, and SNAP_READER_MS for the reader. */
function stillKeeping(name) {
  return Object.prototype.hasOwnProperty.call(snapsFilling, name);
}

/* Down to SNAPS_KEEP, oldest first, never one that is still being filled.
 *
 * Not a nicety. A Pi has no real-time clock and boots in 1970; a snap taken
 * before the network sets the clock is named for 1970, sorts as the oldest
 * folder there is, and would otherwise be deleted by the very press that made
 * it — a reply saying "saved" over a folder that is already gone. Sparing only
 * the press's own folder was not enough: two presses at once on an unset
 * clock and a full shelf are two 1970 folders, the oldest two there are, and
 * the first to finish removed the other while its screenshot was still being
 * taken. That one was answered "saved", with "could not write snap.json:
 * ENOENT" on the end, over a folder that no longer existed, and the log named
 * the newest snap on the rig as the oldest one removed. */
function pruneSnaps() {
  var names = snapNames().names;
  var over = names.length - SNAPS_KEEP;
  if (over <= 0) return [];
  var gone = [];
  names.filter(function (n) { return !stillKeeping(n); }).slice(0, over)
    .forEach(function (name) {
      try {
        fs.rmSync(path.join(SNAPS_DIR, name), { recursive: true, force: true });
        gone.push(name);
      } catch (e) {
        console.error('snap: could not remove ' + name + ': ' + e.message);
      }
    });
  return gone;
}

/* Make the folder, keep what can be kept, and say what could not.
 *
 * `done(err, record)`: err only when there is nowhere to put anything, which
 * is the one failure that keeps nothing at all. Every other failure is a part
 * missing with its reason, inside a reply that is ok. */
function takeSnap(done) {
  // Both taken NOW, at the press, before the screenshot is waited on. The tool
  // can take seconds and the rig goes on reading through them; status.json is
  // a record of what was on the panel when the driver pressed, not of whatever
  // had arrived by the time the slowest part finished.
  var at = Date.now();
  var pressed = statusNow();
  var status = JSON.stringify(pressed, null, 2) + '\n';
  fs.mkdir(SNAPS_DIR, { recursive: true }, function (dirErr) {
    if (dirErr) return done(dirErr);
    var stamp = snapStamp(new Date(at));
    var n = 1;
    // Two presses in one second are two snaps, not one overwritten. Two
    // digits, so `-10` cannot sort before `-9`.
    (function claim() {
      var name = n === 1 ? stamp : stamp + '-' + (n < 10 ? '0' : '') + n;
      fs.mkdir(path.join(SNAPS_DIR, name), function (mkErr) {
        if (mkErr && mkErr.code === 'EEXIST' && n < 99) { n++; return claim(); }
        if (mkErr) return done(mkErr);
        snapsFilling[name] = true;
        fill(name);
      });
    }());
  });

  function fill(name) {
    var dir = path.join(SNAPS_DIR, name);
    // The pictures first, then the records, which is the order the line the
    // panel shows takes them in.
    var parts = [null, null, null, null, null];
    var waiting = parts.length;
    var landed = function (i) {
      return function (part) {
        parts[i] = part;
        if (--waiting === 0) seal(name, dir, parts);
      };
    };
    takePanel(path.join(dir, 'panel.png'), landed(0));
    keepCamera(path.join(dir, 'camera.jpg'), landed(1));
    // Resolved, because the scanner is handed this path and its working
    // directory is not necessarily this one's.
    askReader(path.resolve(dir), pressed.offer ? pressed.offer.id || null : null,
              function (two) {
                landed(2)(two[0]);
                landed(4)(two[1]);
              });
    var statusAt = path.join(dir, 'status.json');
    fs.writeFile(statusAt, status, function (err) {
      if (!err) {
        return landed(3)({ what: 'status', file: 'status.json', saved: true,
                           bytes: Buffer.byteLength(status) });
      }
      // Torn, like a camera picture that could not be written — see keepCamera.
      fs.unlink(statusAt, function () {
        landed(3)({ what: 'status', file: 'status.json', saved: false,
                    why: 'could not write it: ' + (err.code || err.message) });
      });
    });
  }

  function seal(name, dir, parts) {
    // The one way out, so the folder stops being one in progress — open to
    // pruning — however the press ends.
    var answer = function (err, record) {
      delete snapsFilling[name];
      done(err, record);
    };
    if (!parts.some(function (p) { return p.saved; })) {
      // Not one part landed — a full card, a read-only card. An empty folder
      // would list as a snap with a reason for every part and no picture, so it goes,
      // and the press is answered as the failure it was — once it is gone,
      // so a list asked for straight after the answer cannot still show it.
      // The reasons of the parts that apply here: "no scanner runs on this
      // machine" is not why nothing could be kept, three times over. And no
      // journal row, there being no folder left for one to name.
      var e = new Error(parts.filter(function (p) { return p.applies !== false; })
        .map(function (p) { return p.why; }).join('; '));
      e.code = 'NOTHING';
      return fs.rm(dir, { recursive: true, force: true }, function () { answer(e); });
    }
    var notes = [];
    // Said rather than discovered. See pruneSnaps for what a 1970 name costs.
    if (at < CLOCK_BELIEVABLE_AFTER) {
      notes.push('the rig\'s clock is not set, so it is filed under ' + name.slice(0, 4));
    }
    var pruned = pruneSnaps();
    // ...and what made room for it, in the line the control shows. The
    // hundred-and-first press removes the first, and a control that says only
    // "saved" over that is a snap gone with nothing on the panel saying so.
    if (pruned.length) {
      notes.push('removed the oldest to keep ' + SNAPS_KEEP + ': ' + pruned.join(', '));
    }
    var record = {
      v: 1, name: name, at: at,
      contents: parts, notes: notes,
      said: snapSaid(parts, notes),
      pruned: pruned, keep: SNAPS_KEEP
    };
    var sealed = path.join(dir, 'snap.json');
    fs.writeFile(sealed, JSON.stringify(record, null, 2) + '\n', function (err) {
      // The parts are on disk either way; what is lost is the note saying
      // what is missing, so that is what the log and the reply say — and the
      // torn file goes, so the list says there is no snap.json rather than
      // reading half of one.
      var then = function () {
        console.log('snap: ' + name + ' ' + record.said);
        // Answered once the row is down, so a journal read straight after the
        // reply finds it.
        appendLines(JSON.stringify(snapRow(record, err)) + '\n', function (rowErr) {
          // Said out loud like every other append here, and not on the panel:
          // the snap is on disk whether or not its index row is.
          if (rowErr) console.error('journal: could not record snap ' + name + ': ' + rowErr.message);
          answer(null, record);
        });
      };
      if (!err) return then();
      console.error('snap: could not write snap.json for ' + name + ': ' + err.message);
      record.notes.push('could not write snap.json: ' + (err.code || err.message));
      record.said = snapSaid(parts, record.notes);
      fs.unlink(sealed, then);
    });
  }
}

/* The journal's note of a snap, so one can be found from the record of the
 * shift it was taken in — the folders are pruned to a hundred and named by a clock
 * that can read 1970; the journal is kept and synced.
 *
 * A `kind` row, collection only: nothing reads it into a rate. The readers of
 * the journal pass over a kind they do not use — the fold behind the offers
 * page and the CSV, /api/journal/newest's offer count, /api/journal/notes, and
 * journal.py's last(), which the scanner resumes from — and rpi/test_server.py
 * asks each of them. syncKey carries it to the copy at home on its id and seq,
 * which is why both are here: a kind row without them is dropped by the sync.
 *
 * Stamped when it is written, like a mark, a pair or a sighting, and not at
 * the press. It is written once the slowest part has landed — up to
 * SNAP_TOOL_MS for the screenshot — and the scan loop goes on appending
 * offers meanwhile, so a row stamped at the press landed behind the one
 * before it: the backwards step rpi/doctor.py reads as NTP correcting the
 * clock mid-shift, and tells the driver to give the Pi a network. The press's
 * own moment is the folder's name, and `at` in its snap.json. `snap-<at>`,
 * with the caveat the sighting rows carry: two rows written in one
 * millisecond would be one key to the sync.
 *
 * Files rather than parts, because a file is what somebody goes looking for:
 * which were kept, which are missing and why, and which do not apply on this
 * machine — so the copy at home's own snaps are not read as failures. */
function snapRow(record, sealErr) {
  var kept = [];
  var missing = {};
  var notHere = {};
  record.contents.forEach(function (p) {
    if (p.saved) kept.push(p.file);
    else if (p.applies === false) notHere[p.file] = p.why;
    else missing[p.file] = p.why;
  });
  if (sealErr) missing['snap.json'] = 'could not write it: ' + (sealErr.code || sealErr.message);
  else kept.push('snap.json');
  var at = Date.now();
  return { v: 1, kind: 'snap', id: 'snap-' + at, seq: 1, at: at,
           folder: record.name, parts: kept, missing: missing, notApplicable: notHere };
}

/* Whether a name is one of the snaps the list shows. The one question every
 * request that names a snap asks — a file out of one, a note on one, a bundle
 * of several — so there is no second rule for what a snap is to drift from
 * snapNames. Anything that is not a string the list holds is not a snap:
 * `..`, a path, a folder made by hand, a link named like one. */
function isSnap(name) {
  return typeof name === 'string' && snapNames().names.indexOf(name) !== -1;
}

/* A snap's own record, snap.json, as everything that reads one reads it:
 * {record}, or no record and whether the file is missing rather than
 * unreadable. A snap.json is one by snapFiles' rule — a real file, never a
 * link wherever it points — and that is asked here, once, for the list, for a
 * bundle and for a note written into it. It used to be asked by the note
 * alone: a snap.json that was a link to a file outside snaps/ had its said,
 * its note and its whys listed, and carried into a bundle that leaves the rig,
 * while a note on the same folder was refused as having no snap.json. Now all
 * three say there is none, which is also what the folder's file list says. */
function snapRecord(name) {
  if (!snapFiles(name).some(function (f) { return f.file === 'snap.json'; })) {
    return { record: null, missing: true };
  }
  try {
    var record = JSON.parse(fs.readFileSync(path.join(SNAPS_DIR, name, 'snap.json'), 'utf8'));
    if (!record || typeof record.said !== 'string') throw new Error('no line in it');
    return { record: record, missing: false };
  } catch (e) {
    return { record: null, missing: e.code === 'ENOENT' };
  }
}

/* One snap: what it holds, what it is missing, and its note. The list's entry
 * for it, and the head of its section in a bundle — one description of a
 * folder, so the page and the file handed on cannot say two things about it.
 *
 * An age rather than a time, measured on this machine's clock, for the reason
 * /api/status gives: the phone reading this is not the machine that wrote it,
 * and the name already says the local time to anybody who wants it — and no
 * age at all where the stamp or the clock reading it was never set (clockAge),
 * which snaps.html says as "age unknown". */
function describeSnap(name, now) {
  var dir = path.join(SNAPS_DIR, name);
  var read = snapRecord(name);
  var record = read.record;
  var at = record && typeof record.at === 'number' ? record.at : null;
  if (at === null) {
    try { at = fs.statSync(dir).mtimeMs; } catch (e) { at = null; }
  }
  return {
    name: name,
    ageMs: clockAge(at, now),
    files: snapFiles(name),
    // Each part that is missing, and each kept with something to say about
    // it — a camera picture too old to be the one at the press. Not a part
    // that does not apply on this machine: the reader's, on the copy at home.
    problems: record && Array.isArray(record.contents)
      ? record.contents.filter(function (p) {
        return p && p.applies !== false && (!p.saved || p.why);
      })
      : [],
    // A folder with no record of its own — made by hand, by a build before
    // this one, or by a press whose snap.json could not be written — says
    // so instead of claiming a clean bill. A record that is there and
    // cannot be read — torn by a full card or a power cut mid-write — is
    // not the same answer, and is not given as if it were. And a press still
    // under way has none yet, which is not having none (stillKeeping).
    said: stillKeeping(name) ? 'still being kept, so nothing says yet what is missing'
      : record ? record.said
      : read.missing ? 'no snap.json in this folder, so nothing says what is missing'
      : 'snap.json in this folder cannot be read, so nothing says what is missing',
    // What the driver called it, if anything — see keepSnapNote.
    note: record && typeof record.note === 'string' ? record.note : null
  };
}

/* Every snap, newest first. */
function describeSnaps() {
  var found = snapNames();
  var now = Date.now();
  var snaps = found.names.slice().reverse().map(function (name) {
    return describeSnap(name, now);
  });
  return { snaps: snaps, unreadable: found.unreadable };
}

/* ---------- a note on a snap: "trip planner", "after accept" -----------------
 *
 * The driver snaps a series per offer — waiting for offers, the card, after
 * the accept, the Trip Planner — and a folder name says when each was taken,
 * not which of the four it is. So a snap can carry a few words, set on
 * snaps.html from a phone or the copy at home, and never asked for at the
 * press: 📷 on the driving screen stays one click.
 *
 * Kept in the snap's own snap.json, under `note`, so it goes where the snap
 * goes — listed with it, carried into a bundle of it, and pruned with it.
 * Rewritten through a temporary of its own and a rename, like every file this
 * server rewrites, so a list read during the write sees the record before or
 * after the note and never half of one.
 *
 * Refused, with the reason, rather than tidied: a name the list does not show
 * (isSnap); a note that is not text, is longer than SNAP_NOTE_MAX, or holds a
 * control character — a line break among them, because the note is a label
 * on one line wherever it is shown; a snap still being kept (stillKeeping);
 * and a folder with no snap.json the list can read, because writing one there
 * would make a record that says nothing about what the folder holds.
 *
 * The still-being-kept refusal is for the reason it gives, not a guard against
 * seal() writing over a note: seal() writes snap.json once, and a note is only
 * ever written into a snap.json that is there, so neither can write over the
 * other. Without it a note sent during the press is refused all the same, as
 * "this snap has no snap.json to keep a note in" (measured, with the refusal
 * taken out) — true of the folder that second and wrong about the snap, which
 * will have one in a moment. Blank, after trimming, takes the note away. */
var SNAP_NOTE_MAX = 80;

/* `done(status, reply)`, once. */
function keepSnapNote(body, done) {
  var name = body.snap;
  if (!isSnap(name)) return done(404, { ok: false, error: 'no snap by that name' });
  if (typeof body.note !== 'string') return done(400, { ok: false, error: 'a note is text' });
  var note = body.note.trim();
  // Counted the way a browser's maxlength counts, in UTF-16 units, so the box
  // on snaps.html (which is handed this limit) and this agree on every note.
  if (note.length > SNAP_NOTE_MAX) {
    return done(400, { ok: false, error: 'a note is at most ' + SNAP_NOTE_MAX
                                         + ' characters, and this one is ' + note.length });
  }
  if (/[\u0000-\u001f\u007f]/.test(note)) {
    return done(400, { ok: false, error: 'a note is one line of text' });
  }
  if (stillKeeping(name)) {
    return done(409, { ok: false, error: 'this snap is still being kept; try again in a moment' });
  }
  // The record as the list reads it — a link named snap.json is not one, and
  // nothing is read or written through it (snapRecord).
  var read = snapRecord(name);
  if (!read.record) {
    return done(409, { ok: false, error: read.missing
      ? 'this snap has no snap.json to keep a note in'
      : 'this snap\'s snap.json cannot be read, so there is nowhere to keep a note' });
  }
  var record = read.record;
  if (note) record.note = note;
  else delete record.note;
  var file = path.join(SNAPS_DIR, name, 'snap.json');
  var tmp = partName(file);
  var failed = function (err) {
    fs.unlink(tmp, function () {});
    console.error('snap: could not keep a note on ' + name + ': ' + err.message);
    done(500, { ok: false, error: 'could not keep the note: ' + (err.code || err.message) });
  };
  fs.writeFile(tmp, JSON.stringify(record, null, 2) + '\n', function (writeErr) {
    if (writeErr) return failed(writeErr);
    fs.rename(tmp, file, function (renameErr) {
      if (renameErr) return failed(renameErr);
      done(200, { ok: true, snap: name, note: note || null });
    });
  });
}

/* ---------- a snap, or a series of them, as one file to hand on -------------
 *
 * The driver shares snaps with their assistant, and a snap is six files: a
 * series of four is twenty-four, named alike in a Downloads folder. So one
 * .html instead, built when it is asked for and never kept: each picture
 * inside it as a data: URI, byte for byte; each record shown as its text and
 * carried again, byte for byte, as a data: URI behind a link that saves it.
 * Nothing in it reaches for the network and nothing in it runs — there is no
 * script — so it opens on a phone in a car park: rpi/test_dashboard.py opens
 * one off the disk in a browser at a phone's size with the network off.
 *
 * Not a <script type="application/json"> block for the records: one ends at
 * the first `</script` inside it and parses differently after a `<!--`, and
 * reader.json carries tesseract's text, which is whatever the camera saw.
 * Escaping either makes it not the file any more; a data: URI cannot be ended
 * by what is in it. The <pre> beside it is the same text, for reading: escaped
 * for HTML, and opened with a newline, which the parser drops, so a record
 * that begins with one keeps it.
 *
 * Which snaps: every name asked for has to be one the list shows (isSnap's
 * rule, snapNames), and one that is not refuses the whole request rather than
 * being left out of it — a file of three handed over as the four that were
 * chosen is a snap gone with nothing saying so. Asked twice is once. In time
 * order whatever order they were asked in, oldest first, because a series
 * reads in the order it was taken: the list's own order, which is the folder
 * names' (and so files a 1970 snap first, as the list does last). The files
 * in each are snapFiles' — real files the press writes, never a link — and
 * its line and note are snapRecord's, by the same rule.
 *
 * And finished: a snap still being kept refuses the request, 409, as a note
 * on it is refused (stillKeeping). Its screenshot can be part way written,
 * and a file that leaves the rig would carry half a picture as the rig's
 * screen. Refused rather than left out, for the reason a name the rig does
 * not have is.
 *
 * Streamed a snap at a time, each file read without blocking, so a long
 * series neither holds the event loop — the driving screen's event stream
 * rides it — nor every picture in memory at once. The next snap is not read
 * until the one before it has gone out to the phone: res.write said "full"
 * otherwise, and a phone on a slow link was still taking the first snap of a
 * hundred while the rest were read in behind it, all held in the Pi's memory
 * (rpi/test_server.py stops reading a bundle part way and measures this). A
 * file that cannot be read by the time its turn comes, a snap pruned while
 * the bundle was being built among them, is said in its place: the reply was
 * sent as 200 before it was read, so the file has to say it. */
function snapBundle(asked) {
  var want = asked === undefined ? [] : [].concat(asked);
  if (!want.length) return { status: 400, error: 'name a snap to bundle: ?snap=<folder>' };
  for (var i = 0; i < want.length; i++) {
    if (!isSnap(want[i])) return { status: 404, error: 'no snap named ' + JSON.stringify(want[i]) };
    if (stillKeeping(want[i])) {
      return { status: 409, error: 'snap ' + JSON.stringify(want[i])
                                   + ' is still being kept; try again in a moment' };
    }
  }
  return { names: snapNames().names.filter(function (n) { return want.indexOf(n) !== -1; }) };
}

// What each file a press writes is, in a few words, for the two places that
// have to say: snaps.html, as each picture's alt text, and a bundle, which is
// opened with no rig to ask — under each picture and above each record. Plain
// words, written into a bundle as they are, so no markup character and no
// double quote.
var SNAP_ABOUT = {
  'panel.png': 'the rig\'s screen',
  'camera.jpg': 'the camera\'s last picture',
  'reader.jpg': 'the crop the reader last read',
  'status.json': 'what /api/status said at the press',
  'reader.json': 'the scanner\'s account of its last read',
  'snap.json': 'what the press kept, and why anything is missing'
};
// Which of them are pictures, in the order they are laid side by side — on
// snaps.html, which is handed this list, and at the head of a bundle's
// section, before the records.
function isPicture(file) {
  return /^image\//.test(TYPES[path.extname(file)] || '');
}
var SNAP_PICTURES = SNAP_FILES.filter(isPicture);
var BUNDLE_ORDER = SNAP_PICTURES.concat(SNAP_FILES.filter(function (f) { return !isPicture(f); }));

// Text, never an attribute: the three characters markup can start with, and
// not a quote, which status.json is full of. A bundle is read as text by
// somebody's assistant as often as it is opened in a browser, and every key
// written as &quot;scanner&quot; made the records unreadable that way. The
// attributes a bundle writes are folder names and SNAP_ABOUT, and neither can
// hold a quote.
function escapeHtml(text) {
  return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// Its own colours, not styles.css: nothing outside the file can be reached.
var BUNDLE_CSS = [
  ':root { color-scheme: light dark; }',
  'body { margin: 0 auto; max-width: 900px; padding: 12px 16px 40px;',
  '       font: 15px/1.45 system-ui, sans-serif; }',
  'h1 { font-size: 19px; margin: 0 0 6px; }',
  'h2 { font-size: 17px; margin: 0; font-variant-numeric: tabular-nums; }',
  // A note is any 80 characters, and 80 with no space in them ran a heading
  // off the side of every screen rpi/test_layout.py opens this on.
  'h1, h2, .toc { overflow-wrap: anywhere; }',
  'h2 .note { font-weight: 400; }',
  'section { border-top: 1px solid #8886; padding: 14px 0 6px; }',
  '.said { margin: 4px 0 10px; }',
  '.lost { color: #c33; }',
  'figure { margin: 0 0 12px; }',
  'img { display: block; max-width: 100%; height: auto; border: 1px solid #8886;',
  '      border-radius: 6px; }',
  'figcaption, summary, .lead, .toc { font-size: 14px; }',
  'summary { padding: 10px 0; cursor: pointer; }',
  'pre { margin: 0 0 6px; padding: 8px; border-radius: 6px; background: #8882;',
  '      font-size: 12px; white-space: pre-wrap; overflow-wrap: anywhere; }',
  'details a { display: inline-block; padding: 10px 0; }'
].join('\n');

function bundleHead(snaps) {
  var one = snaps.length === 1;
  var title = one
    ? '📷 Snap ' + snaps[0].name + (snaps[0].note ? ' — ' + snaps[0].note : '')
    : '📷 ' + snaps.length + ' snaps, ' + snaps[0].name + ' to ' + snaps[snaps.length - 1].name;
  var head = '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
    + '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    + '<title>' + escapeHtml(title) + '</title>\n<style>\n' + BUNDLE_CSS + '\n</style>\n'
    + '</head>\n<body>\n<h1>' + escapeHtml(title) + '</h1>\n'
    + '<p class="lead">' + (one ? 'Every file kept for this snap'
                                : 'Every file kept for each of these snaps, oldest first')
    + ': the pictures as they are, and each record as its text, with the file itself'
    + ' behind the link under it.</p>\n';
  if (!one) {
    head += '<ol class="toc">\n' + snaps.map(function (s) {
      return '<li><a href="#' + s.name + '">' + s.name
           + (s.note ? ' — ' + escapeHtml(s.note) : '') + '</a></li>\n';
    }).join('') + '</ol>\n';
  }
  return head;
}

/* One snap's section, `done(html)` once its files have been read in turn. */
function bundleSection(snap, done) {
  var have = snap.files.map(function (f) { return f.file; });
  var files = BUNDLE_ORDER.filter(function (f) { return have.indexOf(f) !== -1; });
  var html = '<section id="' + snap.name + '">\n<h2>' + snap.name
    + (snap.note ? ' <span class="note">— ' + escapeHtml(snap.note) + '</span>' : '')
    + '</h2>\n<p class="said">' + escapeHtml(snap.said) + '</p>\n';
  var i = 0;
  (function next() {
    if (i === files.length) return done(html + '</section>\n');
    var file = files[i++];
    var about = file + ' — ' + SNAP_ABOUT[file];
    fs.readFile(path.join(SNAPS_DIR, snap.name, file), function (err, data) {
      if (err) {
        html += '<p class="lost">' + about + ': could not be read when this file was made ('
              + escapeHtml(err.code || err.message) + ')</p>\n';
        return next();
      }
      // Each file's size is in snap.json, which is in here too; said again
      // beside each picture it would be a second formatter of a size to keep
      // in step with snaps.html's.
      var uri = 'data:' + TYPES[path.extname(file)].split(';')[0] + ';base64,'
              + data.toString('base64');
      if (isPicture(file)) {
        html += '<figure><img src="' + uri + '" alt="' + SNAP_ABOUT[file]
              + '"><figcaption>' + about + '</figcaption></figure>\n';
      } else {
        html += '<details><summary>' + about + '</summary>\n<pre>\n'
              + escapeHtml(data.toString('utf8')) + '</pre>\n<a download="' + snap.name + '-'
              + file + '" href="' + uri + '">save ' + file + ' as it is on the rig</a>'
              + '</details>\n';
      }
      next();
    });
  }());
}

/* The bundle, answered. `names` are snapBundle's: checked, and in time order. */
function sendSnapBundle(res, names) {
  var now = Date.now();
  var snaps = names.map(function (name) { return describeSnap(name, now); });
  // The snap's own name, which is what it is called everywhere else: on the
  // list, in the journal row, and in the per-file downloads on snaps.html.
  var file = (names.length === 1 ? names[0] : names[0] + '_to_' + names[names.length - 1])
           + '.html';
  res.writeHead(200, {
    'Content-Type': 'text/html; charset=utf-8',
    'Content-Disposition': 'attachment; filename="' + file + '"',
    'Cache-Control': 'no-store'
  });
  res.write(bundleHead(snaps));
  var i = 0;
  (function next() {
    if (i === snaps.length) return res.end('</body>\n</html>\n');
    bundleSection(snaps[i++], function (html) {
      // The next snap once this one is on its way, and not before: see
      // "Streamed a snap at a time" above. A phone that gives up on the
      // download stops the reading with it, there being no drain after that.
      if (res.write(html)) return next();
      res.once('drain', next);
    });
  }());
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

/* Where a mark was pressed: the only three places one can be.
 *
 *   panel   the driving screen's Took, pressed in the car, about the last
 *           offer on record;
 *   offers  the ✓ and the hide buttons on the offers page, pressed parked, on
 *           whichever row the driver went looking for;
 *   review  "Close the shift" on the same page, which asks about every card
 *           the panel cleared on the newest day that nobody has answered for.
 *
 * Kept because the ticks are a sample and HOW it was chosen is where it
 * leans. On the owner's week 31 of 1,166 offers carry a tick, and the advice
 * rests every figure about the driver's own decisions on those 31: 24 ACCEPT,
 * 5 CLOSE CALL, 2 PASS — whichever cards the driver remembered to tick, and
 * nothing on file says where each press was made. The review asks about all
 * of a day's cleared cards instead, so the two kinds of answer will not be the
 * same population, and a row that cannot say which it is cannot be counted
 * apart from the other later.
 *
 * Nothing folds `via` onto an offer and no figure reads which surface it
 * names. The fold reads one thing about it, its ABSENCE: a `false` with no
 * `via` was written by a page from before Passed existed, and is a take-back
 * (see latestPerOfferUncached).
 *
 * A fixed set, and anything else is REFUSED before a byte is written, never
 * stored and never dropped. Stored, it would be the free-text field the
 * handler below promises this unauthenticated endpoint does not have. Dropped
 * quietly, a page that misspelt its own name would go on writing marks with
 * no provenance and look as though it worked. Absent stays legal, because
 * every mark already in a journal was written without it. */
var MARK_VIA = ['panel', 'offers', 'review'];

/* ...and which of them may put an order in the car or take one out: the
 * driving panel's Took, and a page old enough to send no `via`. The offers
 * page's ✓ and Close the shift's Took and Passed are answers about a card for
 * the record — a REVIEW of the shift, made parked or at home — and the mark
 * row is all they write. Before this either of them, ticking the card still on
 * the slot, put it in the car: measured at f80d0c2, an order delivered and
 * Drop pressed, then Close the shift's Took on the next card, and /api/status
 * held it; and an offers-page ✓ on the card of the order already in the car
 * rebuilt that order from its card, its ⌖ end gone back to the card's.
 *
 * Since the owner's decision of 19 Oct 2026 the offers page's ✓ on a RECENT
 * card is a ✓ Took on that card, and its take-back on an order in the car is
 * Drop: see offersTickHolds. Not through here — that is a question about one
 * card and the clock, not about the surface — and an offers-page ✓ on the
 * order already in the car still rebuilds nothing ('inCar'). */
function marksTheHold(via) {
  return via === undefined || via === 'panel';
}

/* When the card a Took names came onto the slot: offerAt while it is still
 * the card there, else the time kept for it in scanner.offerAts, else null.
 * A ✓ Took from a panel that has fallen behind names the card BEFORE the one
 * on the slot (the mark handler's `offered` copy), and was dated from the
 * newer card's offerAt — so its clock (holdEnds) started at a card it was not.
 * Measured at f80d0c2: a card up for 3.0 s before the next, then Took on it,
 * and the order said it had been held 11 ms. */
var OFFER_ATS_MAX = 8;

function cardArrivedAt(id) {
  if (scanner.offer && scanner.offer.id === id && scanner.offerAt) return scanner.offerAt;
  var hit = scanner.offerAts.filter(function (c) { return c.id === id; })[0];
  return hit ? hit.at : null;
}

/* --- the offers page's ✓ on a RECENT card puts that order in the car --------
 *
 * The owner's decision of 19 Oct 2026: "It will only map an order of the last
 * card it scanned; offer cards can move very fast, making it easy to miss.
 * Make it so I can map and scan from the offers page where the information is
 * recorded, when I press the green check box that is already there." The
 * panel's ✓ Took names the card on the slot (or the panel's copy of the one
 * before it), and the driver paging fast past a card they accepted on the
 * phone has nothing left on the panel to press for it.
 *
 * So the offers page's ✓ (via 'offers') on a card that is RECENT is a ✓ Took
 * on that card: the same path below the mark handler's `marked` — the hold
 * from the card's reading as the slot had it (pay, minutes, miles, pickup,
 * dropoff, pickupLine, the add-on flag, the card's fix and disc: cardOf),
 * placeTook's replacement and add-on rules, the assembler told, the GPS drop
 * and pickup searches armed by setHeld. It is a press on one named card, so it
 * is not a silence read as an accept (AUDITS.md, Settled), and it names the
 * card itself, so it is not Plan 2.1's hold on the previous card by timing.
 *
 * RECENT, both of these (offersTickHolds, the named checks):
 *   heldStillInForce  the card's own hold would still be in force now had it
 *                     been Took'd the moment it arrived: holdEnds from its
 *                     arrival (the time cardArrivedAt keeps for it), its own
 *                     clock — no stated time is never in force;
 *   noLaterTook       no ✓ Took of another card was pressed after it arrived
 *                     (tookPresses, and the tookAt of every order held, which
 *                     survives a restart): the driver went on to take a later
 *                     job, and putting this one in the car now would replace
 *                     or stack onto that one on a review's word.
 * And the server must still have the card's reading (offerCards, process
 * memory like the slot and offerAts): the offers page's row is the journal's
 * vote over every reading (bestReading), which carries no pickupLine, app,
 * screen or multiOrder, so a hold built from it would arm what a Took on the
 * same card would not. After a restart the tick records only, and says so.
 *
 * Anything else is today's behaviour: the mark row and nothing more, and the
 * reply says why (`car.why`: 'unseen', 'untimed', 'old', 'later', 'inCar')
 * for the page to say. The mark row of one that held says `inCar: true`, and
 * the order says `tookOn: 'offers'`, so a reader can tell it from a review
 * label (the shift report in tools/ times it as a Took). Close the shift's Took and
 * Passed (via 'review') are unchanged: they answer for a whole day's cards.
 *
 * Taking it back is Drop: the ✓ pressed again (or the page's Undo of a ✓) on
 * an order in the car puts that order down with a drop row `by: 'offers'`
 * (putDown), whichever surface put it there. */
var OFFER_CARDS_MAX = 120;
var offerCards = [];
var TOOK_PRESSES_MAX = 16;
var tookPresses = [];

// The latest reading of a card the slot held, against when it last came up
// (the slot's offerAt, as offerAts keeps it). Newest last.
function keepOfferCard(card, at) {
  offerCards = offerCards.filter(function (c) { return c.id !== card.id; })
    .concat([{ id: card.id, at: at, card: card }]).slice(-OFFER_CARDS_MAX);
}

// Every ✓ Took that put an order in the car, the panel's or this page's.
function keepTookPress(id, at) {
  tookPresses = tookPresses.concat([{ id: id, at: at }]).slice(-TOOK_PRESSES_MAX);
}

function heldStillInForce(card, at, now) {
  var probe = { minutes: typeof card.billedMinutes === 'number'
                  ? card.billedMinutes : card.minutes,
                acceptedAt: at };
  var ends = holdEnds(probe);
  return ends !== null && now <= ends;
}

function noLaterTook(id, at) {
  var tooks = tookPresses.concat(scanner.held.map(function (h) {
    return { id: h.id, at: h.tookAt };
  }));
  return !tooks.some(function (t) {
    return t.id !== id && typeof t.at === 'number' && t.at > at;
  });
}

// {card, at} for a tick that puts the order in the car, else {why}.
function offersTickHolds(id, now) {
  var kept = offerCards.filter(function (c) { return c.id === id; })[0];
  if (!kept) return { why: 'unseen' };
  var card = kept.card;
  var inCar = heldOrders(now).some(function (h) {
    return h.id === id || (card.heldCard && holdIdOf(h) === card.heldCard);
  });
  if (inCar) return { why: 'inCar' };
  var minutes = typeof card.billedMinutes === 'number' ? card.billedMinutes : card.minutes;
  if (!(typeof minutes === 'number' && minutes > 0)) return { why: 'untimed' };
  if (!heldStillInForce(card, kept.at, now)) return { why: 'old' };
  if (!noLaterTook(id, kept.at)) return { why: 'later' };
  return { card: card, at: kept.at };
}

/* --- the NucBox's map services: a search and a router, at home -------------
 *
 * The NucBox runs Nominatim (Georgia) and OSRM (car profile, Georgia) behind
 * Tailscale. Two settings name them, and they are this server's settings the
 * way PORT, JOURNAL and SYNC_TOKEN are: its environment, set where the server
 * is started (the unit's `Environment=` lines, or Start.sh on the owner's
 * rig). Empty by default, and empty is today: GET /api/nbx answers both false,
 * the two endpoints below answer "not set here", and no page asks either.
 *
 *   NUCBOX_SEARCH   Nominatim's base, e.g. http://100.x.y.z:8088
 *   NUCBOX_ROUTER   OSRM's base,      e.g. http://100.x.y.z:5000
 *   NUCBOX_STREETS  the NucBox's own server.js, which answers where two
 *                   streets meet and the stretch of one from its street
 *                   index (NUCBOX_STREETS_FILE there), e.g.
 *                   http://100.x.y.z:8080
 *                   (the NucBox's Tailscale address)
 *
 * On the NucBox itself the same endpoints work against its own copy
 * (http://127.0.0.1:8088, :5000 and :8080), because nothing here knows which
 * machine it is on.
 *
 * WHY THROUGH HERE AND NOT FROM THE BROWSER. The panel is served from this
 * machine and is all that talks to it; a browser asking the NucBox directly
 * would need the NucBox's address in the page, Tailscale on whatever opened
 * the page, and CORS on two servers nobody configured for it. And this is
 * the one place that can say plainly when the NucBox did not answer, with
 * the reason, rather than a page seeing a failed fetch.
 *
 * NOT AN OPEN PROXY. Two fixed paths upstream, with only the parameters they
 * need, each checked for shape; anything else is refused by name before a
 * byte leaves. The browser cannot choose the host, the path, the format or
 * the limit. Security is out of scope on this rig (it is all behind a VPN),
 * but a relay that forwards whatever it is handed is a different thing from
 * an endpoint that answers one question, and it costs nothing to be the
 * second. */
function nbxBase(name) {
  var v = String(process.env[name] || '').trim();
  if (!v) return null;
  var u;
  try { u = new URL(v); } catch (e) { u = null; }
  if (!u || (u.protocol !== 'http:' && u.protocol !== 'https:')) {
    // Said at startup and treated as unset, so a typo is not a silent
    // "unreachable" on every press of the map.
    console.error(name + ' is not an http(s) URL (' + v + '), so it is ignored');
    return null;
  }
  return v.replace(/\/+$/, '');
}
var NBX = { search: nbxBase('NUCBOX_SEARCH'), route: nbxBase('NUCBOX_ROUTER'),
            streets: nbxBase('NUCBOX_STREETS') };
// Which setting names each relayed question's service, for the words.
var NBX_SETTING = { search: 'NUCBOX_SEARCH', route: 'NUCBOX_ROUTER', cross: 'NUCBOX_STREETS',
                    stretch: 'NUCBOX_STREETS', named: 'NUCBOX_STREETS',
                    whole: 'NUCBOX_STREETS' };
// The questions the NucBox's street index answers (streetsRoute there, the
// relay and searchHeldNamed and searchHeldStreet here).
var STREET_ASKS = ['cross', 'stretch', 'named', 'whole'];
/* Short, because the one caller is a panel read while driving and the
 * alternative it falls back to is already there. Three seconds is chosen,
 * not measured: nobody has timed the real install over Tailscale, and a
 * NucBox that takes longer than this to name ten branches is one the driver
 * is better off not waiting for. NUCBOX_TIMEOUT_MS moves it (the suites use
 * it). */
var NBX_TIMEOUT_MS = Number(process.env.NUCBOX_TIMEOUT_MS) > 0
  ? Number(process.env.NUCBOX_TIMEOUT_MS) : 3000;
/* A small cache of answers, in memory only. The NucBox's data changes when
 * the driver re-imports Georgia, not between two presses, and a card re-read
 * forty times a second must not ask forty times. Only answers are kept — a
 * NucBox that did not answer is asked again next time. Oldest out first. */
var NBX_CACHE_MAX = 500;
var nbxCache = new Map();
/* The most an answer may be. Ten search results in jsonv2's shape, each with
 * the real install's "McDonald's, 2700, Windy Hill Road Southeast, ..." name,
 * are 4,891 bytes (measured on tests/fake-nucbox.js); a three-point route
 * with overview=false and 84-character waypoint hints is 786. With the road's
 * shape asked for too (overview=simplified, nbxRoute) a route carries one
 * point per bend OSRM kept, about 23 bytes each as GeoJSON — an estimate,
 * not measured on the real install — so NBX_LINE_MAX's 5,000 points is
 * about 115 kB, inside this. Anything near this is not one. */
var NBX_BODY_MAX = 256 * 1024;
/* How many candidates a search asks for. Ten: enough for every branch of a
 * chain inside a disc the size of a card's distance, mostly — the real
 * install answered ten McDonald's in a 0.2-degree box round Marietta, which
 * is exactly this many, so a list that comes back this long is said to be
 * cut (`cutAt`) and the page will not claim "only one fits" from it. */
var NBX_LIMIT = 10;
// How long a search term may be: the parser's MAX_PLACE is 60, so 120 is
// room for a whole bracketed address and nothing a page of this rig sends.
var NBX_TERM_MAX = 120;

/* ...and by SIZE as well as by count. A route with the road's shape is up to
 * NBX_LINE_MAX points, and 500 of those are not a small cache: measured at
 * f80d0c2, 500 routes of 5,000 points each (103,959 bytes an answer) through
 * /api/nbx/route left 185.5 MB of heap in use after a full collection, from
 * 6.6 MB, on a Pi that shares its memory with the camera, OpenCV and
 * Tesseract. NBX_CACHE_BYTES bounds the answers' size as JSON (what each is
 * sent as), oldest out first; an answer bigger than all of it is sent and not
 * kept. 8 MB is chosen, not measured against a need: 80 of the largest
 * routes, or every search a shift asks; the same 500 routes leave 35.8 MB
 * (the objects weigh more than their JSON). NUCBOX_CACHE_BYTES moves it (the
 * suite does). */
var NBX_CACHE_BYTES = envNumber('NUCBOX_CACHE_BYTES', 8 * 1024 * 1024);
var nbxCacheBytes = 0;
var nbxSizes = new Map();

function nbxRemember(key, value) {
  var size = Buffer.byteLength(JSON.stringify(value));
  if (nbxCache.has(key)) {
    nbxCacheBytes -= nbxSizes.get(key) || 0;
    nbxCache.delete(key);
    nbxSizes.delete(key);
  }
  if (size > NBX_CACHE_BYTES) return;
  nbxCache.set(key, value);
  nbxSizes.set(key, size);
  nbxCacheBytes += size;
  while (nbxCache.size > NBX_CACHE_MAX || nbxCacheBytes > NBX_CACHE_BYTES) {
    var oldest = nbxCache.keys().next().value;
    nbxCacheBytes -= nbxSizes.get(oldest) || 0;
    nbxCache.delete(oldest);
    nbxSizes.delete(oldest);
  }
}

/* One question to the NucBox. `done(err, parsedJson)`; `err` is always a
 * sentence about the NucBox, never about the place.
 *
 * THE TIMEOUT IS A WALL CLOCK over the whole question, connecting included.
 * It used to be req.setTimeout, which is a socket's IDLE timer and is only
 * armed on a socket that exists: against a host that never accepts (a
 * listener with its backlog full, or an address nothing routes to) it did
 * not fire at 0.5 s. Measured: on Node 22 the global agent's own 5 s socket
 * timeout ended it at 5009 ms, still saying "did not answer within 0.5 s";
 * with an Agent of Node 18's kind (no socket timeout of its own) it was still
 * waiting at 15021 ms, and the verifier saw ~127 s against 10.255.255.1 —
 * the kernel's SYN retries — the whole of it holding live.html's mapBusy, so
 * every Map press in that time returned without doing anything. A timer
 * started here, before the connect, cleared by the first ending of any kind,
 * and destroying the request when it fires, is the one thing that means
 * what the sentence says. */
function nbxAsk(target, done) {
  var u;
  try { u = new URL(target); } catch (e) { return done('the NucBox address is not a URL'); }
  var lib = u.protocol === 'https:' ? https : http;
  var finished = false;
  var req = null;
  var timer = setTimeout(function () {
    end('the NucBox did not answer within ' + (NBX_TIMEOUT_MS / 1000) + ' s');
    if (req) req.destroy();
  }, NBX_TIMEOUT_MS);
  function end(err, body) {
    if (finished) return;
    finished = true;
    clearTimeout(timer);
    done(err, body);
  }
  req = lib.get(target, { headers: { 'Accept': 'application/json' } }, function (up) {
    var chunks = [], size = 0;
    up.on('data', function (c) {
      size += c.length;
      if (size > NBX_BODY_MAX) {
        end('the NucBox answered with more than ' + NBX_BODY_MAX + ' bytes');
        req.destroy();
        return;
      }
      chunks.push(c);
    });
    up.on('end', function () {
      var parsed;
      try { parsed = JSON.parse(Buffer.concat(chunks).toString('utf8')); }
      catch (e) { parsed = undefined; }
      // OSRM answers its refusals as HTTP 400 with its own string `code`,
      // and they are handed on for the route reply to tell apart — there,
      // and only there (nbxRoute): "NoRoute" is an answer about the points;
      // every other code (InvalidQuery, InvalidValue, NoSegment, TooBig...)
      // is the router not answering. Any other status is the NucBox not
      // answering the question.
      if (up.statusCode !== 200
          && !(up.statusCode === 400 && parsed && typeof parsed.code === 'string')) {
        return end('the NucBox answered ' + up.statusCode);
      }
      if (parsed === undefined) return end('the NucBox answered something that is not JSON');
      end(null, parsed);
    });
    up.on('error', function (e) { end('the NucBox stopped answering (' + (e.code || e.message) + ')'); });
  });
  req.on('error', function (e) {
    end('the NucBox did not answer (' + (e.code || e.message) + ')');
  });
}

/* The one search question this rig asks the NucBox's Nominatim: `term` is
 * 'q' or 'street', `said` the checked text, `vb` a checked viewbox or null.
 * The relay below and the server's own held-end search (searchHeldEnd) both
 * build it here, so the two cannot ask differently — or miss each other in
 * nbxCache. */
function nbxSearchTarget(term, said, vb) {
  return NBX.search + '/search?format=jsonv2&limit=' + NBX_LIMIT + '&' + term + '='
       + encodeURIComponent(said)
       + (vb ? '&viewbox=' + encodeURIComponent(vb) + '&bounded=1' : '');
}

/* A Nominatim list as the page reads it: where, and what it is called (the
 * name is where a house number shows, map-view.js hasDoor) — and, for the
 * held end's place (map-view.js pickPlace, the owner's rule of 17 Oct), what
 * KIND of thing it is (jsonv2 `category`: a road is 'highway', a parking deck
 * 'amenity') and the feature's OWN name (`called`, jsonv2 `name`, '' for an
 * address with none) — and the limit,
 * as `cutAt`, when the list stopped at it (null when it did not). A full list
 * is not "every one in the box": Nominatim ranks by importance, not by
 * distance, so an eleventh inside the card's disc may be the one that was not
 * sent, and "only one fits" cannot be said of a list that was cut. */
function nbxHits(body) {
  return { ok: true, cutAt: body.length >= NBX_LIMIT ? NBX_LIMIT : null,
           hits: body.map(function (h) {
             return { lat: Number(h.lat), lon: Number(h.lon),
                      name: String(h.display_name || ''),
                      kind: typeof h.category === 'string' ? h.category : null,
                      called: typeof h.name === 'string' ? h.name : '' };
           }).filter(function (h) { return isFinite(h.lat) && isFinite(h.lon); }) };
}

/* The query, or the reason it is refused. `allowed` is every key this
 * endpoint reads; a key outside it, or one given twice, refuses the request
 * whole rather than being dropped — a page that sent it is not this one. */
function nbxQuery(req, allowed) {
  var q = url.parse(req.url, true).query;
  var others = Object.keys(q).filter(function (k) { return allowed.indexOf(k) < 0; });
  if (others.length) return { error: 'refused: ' + others.join(', ') };
  var twice = Object.keys(q).filter(function (k) { return typeof q[k] !== 'string'; });
  if (twice.length) return { error: 'given more than once: ' + twice.join(', ') };
  return { q: q };
}

// "lon,lat" — finite, and on the planet — handed on exactly as written, so
// the NucBox's cache and this one see the same question the page asked.
function nbxPoint(s) {
  var m = /^(-?\d{1,3}(?:\.\d{1,7})?),(-?\d{1,2}(?:\.\d{1,7})?)$/.exec(String(s));
  if (!m) return null;
  return (Math.abs(Number(m[1])) <= 180 && Math.abs(Number(m[2])) <= 90)
    ? m[1] + ',' + m[2] : null;
}

// "left,top,right,bottom" — two nbxPoints — as written, or null.
function nbxBox(s) {
  var corners = String(s).split(',');
  var a = corners.length === 4 && nbxPoint(corners[0] + ',' + corners[1]);
  var b = corners.length === 4 && nbxPoint(corners[2] + ',' + corners[3]);
  return a && b ? a + ',' + b : null;
}

// A name as a page may send one: 1 to NBX_TERM_MAX printable characters.
function nbxTerm(v) {
  var said = String(v).trim();
  return said && said.length <= NBX_TERM_MAX && !/[\u0000-\u001f]/.test(said) ? said : null;
}

/* A question about streets — `which` is 'cross' (a, b, box), 'stretch'
 * (name, box) or 'named' (name, box: the one street the name as read can be
 * inside the box, streets.js named) — checked for shape, or { error }. ONE check for both ends:
 * the rig's relay below and the NucBox's own /api/streets answer the same
 * question, so they refuse the same things for the same reasons, and a
 * question the relay passed is one the NucBox will take. The box is
 * optional, as the search's viewbox is: without one the whole index is
 * asked. */
function streetQuestion(req, which) {
  var names = which === 'cross' ? ['a', 'b'] : ['name'];
  var sq = nbxQuery(req, names.concat(['box']));
  if (sq.error) return sq;
  var out = {};
  for (var i = 0; i < names.length; i++) {
    out[names[i]] = sq.q[names[i]] === undefined ? null : nbxTerm(sq.q[names[i]]);
    if (!out[names[i]]) {
      return { error: names.join(' and ') + ' must each be 1 to ' + NBX_TERM_MAX
                      + ' printable characters' };
    }
  }
  out.box = null;
  if (sq.q.box !== undefined) {
    out.box = nbxBox(sq.q.box);
    if (!out.box) return { error: 'box is left,top,right,bottom' };
  }
  // ...except 'named', which is a guess between streets and is only ever
  // asked inside a card's box (streets.js named answers nothing without one),
  // and 'whole', the streets of a name that reach into a card's box.
  if ((which === 'named' || which === 'whole') && !out.box) {
    return { error: which + ' needs a box' };
  }
  return out;
}

/* The NucBox street index's own URL for a checked question (streetQuestion's
 * `st`): the rig's relay and the server's own held-end search (searchHeldNamed)
 * both build it here, so the two ask in the same words and share nbxCache. */
function streetTarget(which, st) {
  return NBX.streets + '/api/streets/' + which + '?'
       + (which === 'cross'
          ? 'a=' + encodeURIComponent(st.a) + '&b=' + encodeURIComponent(st.b)
          : 'name=' + encodeURIComponent(st.name))
       + (st.box ? '&box=' + encodeURIComponent(st.box) : '');
}

/* What the NucBox's street index answered, as the fields the page reads, or
 * { error } for an answer that is not one. Strict, all or nothing: a meeting
 * or a point that is not two finite numbers refuses the whole answer rather
 * than being dropped from it, because a corner list with one corner quietly
 * missing is "only one fits" said of a list that was not whole. */
function streetAnswer(which, body) {
  var fin = function (v) { return typeof v === 'number' && isFinite(v); };
  var names = function (side) {
    return side && Array.isArray(side.names) && side.names.every(function (n) {
      return typeof n === 'string';
    }) ? { names: side.names, how: typeof side.how === 'string' ? side.how : null } : null;
  };
  var cut = body && fin(body.cutAt) ? body.cutAt : null;
  if (which === 'named') {
    var one = names(body);
    // `among` a count, and names given only with exactly one street: a list
    // of names beside two streets is not "the one street".
    if (!body || body.ok !== true || !one || !fin(body.among) || body.among < 0
        || (one.names.length > 0 && body.among !== 1)) {
      return { error: 'the NucBox street index answered something that is not one street' };
    }
    return { ok: true, names: one.names, how: one.how, among: body.among };
  }
  if (which === 'whole') {
    var w = names(body);
    // Each street a length and its ways' polylines, or null for one too long
    // to have been sent: all or nothing, as the rest.
    if (!body || body.ok !== true || !w || !Array.isArray(body.streets)
        || !body.streets.every(function (st) {
          return st && fin(st.metres) && st.metres >= 0 && (st.lines === null
            || (Array.isArray(st.lines) && st.lines.every(function (l) {
              return Array.isArray(l) && l.length >= 2 && l.every(function (pt) {
                return Array.isArray(pt) && pt.length === 2 && fin(pt[0]) && fin(pt[1]);
              });
            })));
        })) {
      return { error: 'the NucBox street index answered something that is not a street\'s '
                      + 'length' };
    }
    return { ok: true, names: w.names, how: w.how, streets: body.streets.map(function (st) {
      return { metres: st.metres, lines: st.lines };
    }) };
  }
  if (which === 'cross') {
    var a = names(body && body.a), b = names(body && body.b);
    if (!body || body.ok !== true || !a || !b || !Array.isArray(body.meets)
        || !body.meets.every(function (m) {
          return m && fin(m.lat) && fin(m.lon) && fin(m.n) && fin(m.spanM);
        })) {
      return { error: 'the NucBox street index answered something that is not where two '
                      + 'streets meet' };
    }
    return { ok: true, a: a, b: b, cutAt: cut, meets: body.meets.map(function (m) {
      return { lat: m.lat, lon: m.lon, n: m.n, spanM: m.spanM, shared: !!m.shared };
    }) };
  }
  var s = names(body);
  if (!body || body.ok !== true || !s || !Array.isArray(body.lines)
      || !body.lines.every(function (l) {
        return Array.isArray(l) && l.every(function (pt) {
          return Array.isArray(pt) && pt.length === 2 && fin(pt[0]) && fin(pt[1]);
        });
      })) {
    return { error: 'the NucBox street index answered something that is not a street' };
  }
  return { ok: true, names: s.names, how: s.how, cutAt: cut, lines: body.lines };
}

/* OSRM's GeoJSON route geometry as the page draws it, [[lat, lon], ...], or
 * null for anything that is not one. Null and not a refusal of the whole
 * answer: the metres are the figure the caption states and they stand on
 * their own; without a shape the page draws the straight line it always
 * drew, which is a line that looks like what it is. All or nothing, because a
 * road with one point quietly missing is a line drawn through a field. */
var NBX_LINE_MAX = 5000;
// The most points one route question carries: the car and two orders' four
// stops (onTimeHint).
var NBX_ROUTE_POINTS_MAX = 5;
function nbxLine(g) {
  var c = g && g.type === 'LineString' && Array.isArray(g.coordinates) ? g.coordinates : null;
  if (!c || c.length < 2 || c.length > NBX_LINE_MAX) return null;
  var out = [];
  for (var i = 0; i < c.length; i++) {
    var p = c[i];
    if (!Array.isArray(p) || p.length < 2 || typeof p[0] !== 'number' || typeof p[1] !== 'number'
        || !isFinite(p[0]) || !isFinite(p[1]) || Math.abs(p[0]) > 180 || Math.abs(p[1]) > 90) {
      return null;
    }
    out.push([p[1], p[0]]);
  }
  return out;
}

function nbxRoute(req, res) {
  var reply = function (code, body) {
    send(res, code, JSON.stringify(body), { 'Content-Type': 'application/json; charset=utf-8' });
  };
  var p = req.url.split('?')[0];
  if (p === '/api/nbx') {
    // What the page asks first, so with nothing set it does what it always
    // did. Whether, not where: the addresses stay on this machine.
    return reply(200, { ok: true, search: !!NBX.search, route: !!NBX.route,
                        streets: !!NBX.streets });
  }
  var which = { '/api/nbx/search': 'search', '/api/nbx/route': 'route',
                '/api/nbx/cross': 'cross', '/api/nbx/stretch': 'stretch',
                '/api/nbx/named': 'named', '/api/nbx/whole': 'whole' }[p] || null;
  if (!which) return reply(404, { ok: false, error: 'no such NucBox endpoint' });
  var streetish = STREET_ASKS.indexOf(which) >= 0;
  var base = NBX[streetish ? 'streets' : which];
  if (!base) {
    return reply(404, { ok: false, configured: false,
                        error: 'no NucBox ' + (streetish ? 'street index' : which)
                               + ' is set on this machine (' + NBX_SETTING[which] + ')' });
  }
  var target;
  if (streetish) {
    var st = streetQuestion(req, which);
    if (st.error) return reply(400, { ok: false, error: st.error });
    // The NucBox's own server answers these, at the same path with the same
    // parameters, checked by the same function; nothing else is sent.
    target = streetTarget(which, st);
  } else if (which === 'search') {
    var sq = nbxQuery(req, ['q', 'street', 'viewbox']);
    if (sq.error) return reply(400, { ok: false, error: sq.error });
    var term = sq.q.q !== undefined ? 'q' : sq.q.street !== undefined ? 'street' : null;
    if (!term || (sq.q.q !== undefined && sq.q.street !== undefined)) {
      return reply(400, { ok: false, error: 'one of q or street, not both and not neither' });
    }
    var said = nbxTerm(sq.q[term]);
    if (!said) {
      return reply(400, { ok: false, error: term + ' must be 1 to ' + NBX_TERM_MAX
                                            + ' printable characters' });
    }
    // NBX_LIMIT, fixed here, and the page decides among them — told
    // whether the list stopped at it (`cutAt` below).
    var vb = null;
    if (sq.q.viewbox !== undefined) {
      vb = nbxBox(sq.q.viewbox);
      if (!vb) return reply(400, { ok: false, error: 'viewbox is left,top,right,bottom' });
    }
    target = nbxSearchTarget(term, said, vb);
  } else {
    var rq = nbxQuery(req, ['points']);
    if (rq.error) return reply(400, { ok: false, error: rq.error });
    var pts = String(rq.q.points || '').split(';').map(nbxPoint);
    // Up to five since the on-time hint (onTimeHint): the car and the four
    // stops of two orders. Map view still asks two or three.
    if (pts.length < 2 || pts.length > NBX_ROUTE_POINTS_MAX || pts.some(function (x) { return !x; })) {
      return reply(400, { ok: false, error: 'points is two to five lon,lat pairs, ;-separated' });
    }
    // The shape of the road as well as its length: simplified (OSRM thins
    // it to the zoom that frames the whole route, which is the zoom Map view
    // fits to) and as GeoJSON, so the page draws the route along the roads
    // rather than as a straight line across them. Fixed here like the rest;
    // the page still sends nothing but its points.
    target = NBX.route + '/route/v1/driving/'
           + pts.join(';') + '?overview=simplified&geometries=geojson';
  }
  if (nbxCache.has(target)) return reply(200, nbxCache.get(target));
  nbxAsk(target, function (err, body) {
    // `unreachable: true` is the field a page falls back to the public map
    // on (map-view.js NbxSearch.get), as is `configured: false` above: both
    // say there is no NucBox to ask. Every other refusal here — a 400 for a
    // question this relay will not pass on, a 404 for a path it does not
    // have — is the page asking wrongly, a bug, and the page says so rather
    // than quietly asking somebody else.
    var down = function (why) {
      reply(502, { ok: false, unreachable: true, error: why });
    };
    if (err) return down(err);
    var out;
    if (which === 'search') {
      if (!Array.isArray(body)) {
        return down('the NucBox search answered something that is not a list');
      }
      // What the page reads and nothing else: see nbxHits.
      out = nbxHits(body);
    } else if (streetish) {
      out = streetAnswer(which, body);
      if (out.error) return down(out.error);
    } else if (body && body.code === 'NoRoute') {
      // An answer, and kept: the router saying there is no road between
      // these points will say it again. ONLY this code. Every other one OSRM
      // sends with its 400 used to be relayed as "no road" too, and cached,
      // so a router refusing the question read as a fact about the map until
      // this server restarted; those fall to `down` below — never cached,
      // and the page says "NucBox router down".
      out = { ok: false, noRoute: true,
              error: 'the router found no road between these points (NoRoute)' };
    } else {
      var r0 = body && body.code === 'Ok' && Array.isArray(body.routes) && body.routes[0];
      // How far OSRM moved each point to reach a road (its waypoints[].
      // distance, metres), one per point asked, in order. A pin snapped a
      // long way is a route from somewhere else; the page refuses the road
      // figure past its bound and says so (map-view.js SNAP_MI).
      var wps = body && Array.isArray(body.waypoints) ? body.waypoints : [];
      var snaps = wps.map(function (w) { return w && w.distance; });
      if (!r0 || typeof r0.distance !== 'number' || !isFinite(r0.distance)) {
        return down('the NucBox router answered ' + String((body && body.code) || '?').slice(0, 40)
                    + ', not a route');
      }
      if (snaps.length !== pts.length || !snaps.every(function (d) {
        return typeof d === 'number' && isFinite(d) && d >= 0;
      })) {
        return down('the NucBox router answered without how far it moved each point');
      }
      // The distance, the road's shape and, since the owner's decision of
      // 20 Oct 2026 (AUDITS.md, Done, "On time for both"), OSRM's own
      // `duration` in seconds, or null when it sent none. It is the ROUTER's
      // drive time over the road it chose, free-flow with no traffic in it —
      // not a pace and not minutes from distance, both still refused
      // (Settled: "Do not re-time an offer at a pace"). One use is allowed:
      // the on-time hint beside the pair line (onTimeHint). Map view does
      // not read it.
      out = { ok: true, metres: r0.distance, snaps: snaps, line: nbxLine(r0.geometry),
              duration: typeof r0.duration === 'number' && isFinite(r0.duration) && r0.duration >= 0
                ? r0.duration : null };
    }
    nbxRemember(target, out);
    reply(200, out);
  });
}

/* --- the NucBox's street index ---------------------------------------------
 *
 * Where two named streets meet, and the stretch of one, answered from the
 * file tools/street_index.py made from the Georgia extract (streets.js does
 * the answering; README, "The NucBox at home"). It runs HERE, in the
 * NucBox's own copy of this server, because that server already runs there
 * and is already reached over Tailscale: one setting on each machine and no
 * third service to install, start and keep up.
 *
 *   NUCBOX_STREETS_FILE   the index, on the NucBox (e.g. ~/streets.json)
 *
 * Read once, at start, whole into memory; the server prints how long that
 * took and what it holds. A file that is set and cannot be read is said at
 * start and answered as such on every question — never as "no such street",
 * which would be a fact about Georgia made up from a bad file. Unset is the
 * ordinary install: /api/streets says nothing is loaded. */
var STREETS_FILE = String(process.env.NUCBOX_STREETS_FILE || '').trim();
var STREETS = { ix: null, why: null, ms: null, heapMb: null };
// The most points a stretch answer carries (streets.js POINTS_MAX); the
// suites move it.
var STREETS_POINTS_MAX = Number(process.env.NUCBOX_STREETS_POINTS_MAX) > 0
  ? Number(process.env.NUCBOX_STREETS_POINTS_MAX) : Streets.POINTS_MAX;
if (STREETS_FILE) {
  var streetsT0 = Date.now();
  try {
    STREETS.ix = Streets.load(STREETS_FILE);
    STREETS.ms = Date.now() - streetsT0;
    STREETS.heapMb = Math.round(process.memoryUsage().heapUsed / 1048576);
  } catch (e) {
    STREETS.why = 'the street index at ' + STREETS_FILE + ' could not be read ('
                + String((e && (e.code || e.message)) || e).slice(0, 120) + ')';
  }
}

function streetsRoute(req, res) {
  var reply = function (code, body) {
    send(res, code, JSON.stringify(body), { 'Content-Type': 'application/json; charset=utf-8' });
  };
  var p = req.url.split('?')[0];
  if (p === '/api/streets') {
    return reply(200, STREETS.ix
      ? { ok: true, loaded: true, counts: STREETS.ix.counts, bbox: STREETS.ix.bbox,
          loadMs: STREETS.ms, heapMb: STREETS.heapMb }
      : { ok: true, loaded: false, error: STREETS.why });
  }
  var which = /^\/api\/streets\/([a-z]+)$/.exec(p);
  which = which && STREET_ASKS.indexOf(which[1]) >= 0 ? which[1] : null;
  if (!which) return reply(404, { ok: false, error: 'no such street endpoint' });
  if (!STREETS.ix) {
    return STREETS.why ? reply(503, { ok: false, error: STREETS.why })
      : reply(404, { ok: false, configured: false,
                     error: 'no street index is loaded here (NUCBOX_STREETS_FILE)' });
  }
  var st = streetQuestion(req, which);
  if (st.error) return reply(400, { ok: false, error: st.error });
  var box = Streets.boxOf(st.box);
  var out = which === 'cross' ? Streets.cross(STREETS.ix, st.a, st.b, box)
    : which === 'named' ? Streets.named(STREETS.ix, st.name, box)
    : which === 'whole' ? Streets.whole(STREETS.ix, st.name, box)
    : Streets.stretch(STREETS.ix, st.name, box, STREETS_POINTS_MAX);
  out.ok = true;
  return reply(200, out);
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
      // Two answers and a way of taking either back.
      //
      // `true` is "I took this" and `false` is "I passed on this" — a KNOWN
      // pass, which Advice.ifCleared stops counting as a card that might have
      // been taken. `null` is neither: it withdraws whatever was said, and the
      // fold below leaves the offer with no `accepted` at all, which is what
      // an offer nobody marked carries.
      //
      // The third one is needed because there are presses that undo an
      // answer rather than give the opposite one: the ✓ pressed again, the
      // panel's Took pressed again ("Press again if that was wrong"), and the
      // offers page's Undo. Before a pass meant anything those wrote `false`,
      // and false and absent were read alike everywhere, so it did not matter.
      // It matters now: a ✓ mis-tapped onto the wrong row and undone at once
      // would have been filed as a pass the driver never made, and the review
      // would have stopped asking about that card. A page still running the
      // old code sends that `false` with no `via`, and the fold reads it as
      // the take-back it is.
      if (typeof body.accepted === 'boolean' || body.accepted === null) {
        note.accepted = body.accepted;
      }
      if (typeof body.hidden === 'boolean') note.hidden = body.hidden;
      if (note.accepted === undefined && note.hidden === undefined) {
        return send(res, 400, JSON.stringify({ ok: false, error: 'nothing to note' }),
                    { 'Content-Type': 'application/json; charset=utf-8' });
      }
      // Which surface the press came from: one of MARK_VIA or absent, and
      // anything else refused here, before the append.
      if (body.via !== undefined) {
        if (MARK_VIA.indexOf(body.via) === -1) {
          return send(res, 400, JSON.stringify({ ok: false, error: 'unknown via' }),
                      { 'Content-Type': 'application/json; charset=utf-8' });
        }
        note.via = body.via;
      }
      // The offers page's ✓ on a RECENT card is a ✓ Took on it (offersTickHolds);
      // asked before the row is written, so the row can say it held.
      var fromOffers = note.kind === 'mark' && note.via === 'offers' && note.accepted === true
        ? offersTickHolds(note.id, Date.now()) : null;
      var offersHolds = !!(fromOffers && fromOffers.card);
      if (offersHolds) note.inCar = true;
      // A ✓ Took on an Uber add-on says so on its own mark row: `addon: true`
      // and, when an Uber order is in the car, `addonTo` — the root of the
      // trip it joins (addOnBase, tripOf), ids only. Asked here, before the
      // row is written, of the card the handler below will take the order
      // from (the slot's, or the panel's copy when the slot holds none or is
      // behind) and of the car as it stands — the same question placeTook
      // asks of the same two a moment later. On 16 Oct no row said a ticked
      // card was an add-on at all.
      if (note.kind === 'mark' && note.accepted === true && (marksTheHold(note.via) || offersHolds)) {
        var aboutCard = offersHolds ? fromOffers.card
          : scanner.offer && scanner.offer.id === note.id ? scanner.offer
          : body.offer && typeof body.offer === 'object' && body.offer.id === note.id
            ? body.offer : null;
        if (isAddOnCard(aboutCard) && !aboutCard.heldCard) {
          note.addon = true;
          var addOnto = addOnBase(heldOrders(Date.now()).filter(function (o) {
            return o.id !== note.id;
          }));
          if (addOnto) note.addonTo = tripOf(addOnto);
        }
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
        //
        // Or the offer the panel sends with the mark. After a server restart
        // mid-shift the offer on record is gone — it is process memory — but
        // the panel still shows "Took $10.00?" for it and the driver presses
        // it. The mark was written and no order went in the car: Drop and
        // Dropoff never appeared and the next card was judged alone, on the
        // one path this feature exists for. The panel knows the offer it is
        // marking, so it says, and that stands in when nothing is on record.
        //
        // ...ONLY when nothing is on record. It used to stand in whenever the
        // mark named a different card, which is also the case where the panel
        // is simply BEHIND: the socket dropped, /api/events replays the last
        // reading and never the offer, and the driver ticks the card they
        // took while the server has already moved on to the next one. The
        // older card then replaced the newer one on the slot, /api/status said
        // 'a' with 'b' on the phone, and b's next re-read was no longer the
        // same card — so recordPairing wrote b's pair row a second time, into
        // a file that cannot be corrected. Reproduced against this server:
        // pair rows ['a', 'b'] became ['a', 'b', 'b'].
        //
        // The order still goes in the car — that is what the driver said —
        // from the panel's copy of it, and the card on the slot is left alone.
        var marked = null;
        var offered = body.offer && typeof body.offer === 'object'
            && body.offer.id === note.id && typeof note.id === 'string';
        // ...from the driving panel only (marksTheHold): a review tick is the
        // mark row above and nothing else — the slot and the car untouched.
        if (note.kind === 'mark' && note.accepted !== undefined && marksTheHold(note.via)) {
          if (scanner.offer && scanner.offer.id === note.id) {
            marked = scanner.offer;
          } else if (offered && !scanner.offer) {
            scanner.offer = Object.assign({}, body.offer);
            scanner.offerAt = scanner.offerAt || Date.now();
            marked = scanner.offer;
          } else if (offered) {
            marked = Object.assign({}, body.offer);
          }
        } else if (offersHolds) {
          // ...or the offers page's ✓ on a recent card: that card's reading as
          // the slot had it, and the slot left alone.
          marked = fromOffers.card;
        }
        // The order a Took is about to put down, if it replaces one: see the
        // drop row below.
        var replacedHold = null;
        // ...and, with carrying two on, whether this Took ADDED an order
        // beside one already in the car (the panel offers to undo that), and
        // the pay of an order a Took past MAX_HELD put down (said).
        var addedHold = null;
        var putDownPay = null;
        var carriedAtTook = 0;
        var joinedAtTook = false;
        if (marked) {
          marked.accepted = note.accepted;
          var before = holding(Date.now());
          // ...and it becomes the order in the car, which is what the next
          // offer gets measured against. Taking the mark back puts it down
          // again: the driver pressed it twice because they did not take it,
          // and stacking onto a job they refused is the same wrong number as
          // stacking onto one they already delivered.
          //
          // Except a Took on the held order's own card come back under a new
          // id (heldOwnCard): the order in the car is the one the driver took
          // already, and replacing it would restart its clock and write a
          // drop for an order that is still in the car.
          //
          // ANY order in the car's own card: with two carried, a Took on the
          // second's card come back is that order too.
          var inCar = heldOrders(Date.now());
          carriedAtTook = inCar.length;
          joinedAtTook = tripJoined(inCar);
          if (note.accepted && before && marked.heldCard
              && inCar.some(function (h) { return holdIdOf(h) === marked.heldCard; })) {
            // the mark is written; the hold stands as it is
          } else if (note.accepted) {
            // A second ✓ Took while an order is still held used to replace
            // it in silence: the first order left the car with no drop row,
            // and the journal could not say how it ended. With carrying two
            // off the first is put down — and SAID: a drop row `by:
            // 'replaced'`, and a note on the panel. With it on, the second is
            // ADDED, and only a re-offer or a Took past MAX_HELD puts one
            // down, said the same way (placeTook).
            var tookAt = Date.now();
            // When its card came onto the slot — this card's, not the slot's
            // (cardArrivedAt): see `acceptedAt` below. One no longer kept
            // came before the card on the slot, so that card's offerAt is the
            // nearest bound on it, as it was before.
            // The offers page's tick: when that card arrived, as offersTickHolds
            // judged it recent by.
            var cardAt = (offersHolds ? fromOffers.at : null)
              || cardArrivedAt(marked.id) || scanner.offerAt || tookAt;
            var took = asHold({
              id: marked.id,
              pay: marked.pay,
              minutes: typeof marked.billedMinutes === 'number'
                ? marked.billedMinutes : marked.minutes,
              miles: marked.miles,
              cost: marked.cost,
              // Where this one ENDS, so the next offer can be judged on more
              // than the clock. See Advice.sameArea: two pickups on the same
              // block are ordinary, two dropoffs twenty miles apart is the
              // trap, and only the second is worth refusing over.
              dropoff: marked.dropoff || null,
              // ...and whether that destination came off the CARD or off a scan
              // of the driver's screen. Carried, because it was being dropped
              // here and the loss was permanent.
              //
              // The ⌖ Dropoff button works before the accept as well as after:
              // an offer card usually prints "Customer dropoff" and no address
              // — 129 of this driver's 272 cards name no destination at all —
              // so tapping the address open while SCREENING is the ordinary
              // way to find out where a job goes before taking it. That path
              // sets `dropoffScanned` on the card (see the screening branch
              // above); this object copied `dropoff` and left the flag behind,
              // so the order went into the car with a scanned address wearing
              // a card-read label.
              //
              // It is not a display detail. recordPairing writes
              // `scanned: !!held.dropoffScanned` into the append-only journal,
              // and the header above it says that field IS the difference the
              // button exists to make — "whether the destination came off the
              // card or off a scan of the screen after the accept". Every pair
              // judged against an order screened this way recorded the wrong
              // answer to the one question it was there to answer, and a
              // journal row cannot be corrected later.
              //
              // Measured against the real server, screening press then accept:
              // the card reads `dropoffScanned: true` and the held order read
              // `false`, with the address itself identical.
              dropoffScanned: !!marked.dropoffScanned,
              pickup: marked.pickup || null,
              // ...and the store's door DoorDash's stops card printed under
              // that name (the parser's `pickupLine`, "<n> <street>, <town>"),
              // a non-empty string or null: what this server searches the
              // restaurant by for the GPS drop's guard (pickupAsks), what a
              // navigation screen's address is refused as the store's by
              // (Assemble.heldPickup), and what the same-store note reads as
              // this order's pickup (sameStoreOf). The hold kept the name
              // alone, and a chain's name is no place.
              pickupLine: typeof marked.pickupLine === 'string' && marked.pickupLine
                ? marked.pickupLine : null,
              // Whether this reading was one the rig would state a verdict
              // about. A doubted order in the car makes every pair judged
              // against it nonsense, and an uncosted one makes the pair's
              // money gross — and Advice.stack can only apply either rule to
              // what it is handed. Carried rather than recomputed: rate()
              // decided both, and a second derivation is a second thing to
              // drift.
              doubt: marked.doubt || null,
              uncosted: !!marked.uncosted,
              // From when the card was on the screen, not from the press.
              // The panel keeps "Took?" for the last offer however old it
              // is, so a mark can be hours late — the driver ticking last
              // night's job the next morning — and a hold dated from the
              // press would then stack the morning's first offer onto a
              // job finished at midnight. Dated from the card, holding()
              // expires it on the card's own clock, which for a prompt
              // press is the same moment. THIS card's: a Took from a panel
              // behind the slot names the card before it (cardArrivedAt).
              acceptedAt: cardAt,
              // ...and where the car was when its card came up, with the
              // card's own size: what live.html's Map view checks this
              // order's end against. See cardOf.
              card: cardOf(marked),
              // The card as the driver took it, and when they pressed: what
              // recognises it if it comes back under a new id. See
              // heldOwnCard. Not `dropoff` above, which a ⌖ press rewrites.
              seenAs: Object.assign(cardSeen(marked, false), { tookAt: tookAt }),
              // Where each of its ends came from, and when: the assembler's
              // record (Assemble.cardFields), kept beside `dropoff` and
              // `dropoffScanned` above, which it keeps in step.
              fields: Assemble.cardFields(marked, cardAt),
              // ...and the list's own fields (see MAX_HELD): which app, the
              // press, the card's deadline. A scanner older than the offer
              // line's `app` and `deliverBy` leaves them null.
              app: typeof marked.app === 'string' ? marked.app : null,
              tookAt: tookAt,
              deliverBy: typeof marked.deliverBy === 'number' ? marked.deliverBy : null,
              addOn: false,
              of: null
            });
            // ...and which surface took it, for the offers page's alone.
            if (offersHolds) took.tookOn = 'offers';
            keepTookPress(took.id, tookAt);
            // Placed by placeTook: replacing the order in the car, as the
            // slot did, with carrying two off; added beside it with it on.
            var placed = placeTook(took, marked, inCar, tookAt);
            replacedHold = placed.replaced;
            putDownPay = placed.putDownPay;
            if (placed.added) addedHold = took;
            // ...and the assembler told: its pool of planner pages is retried
            // against this hold, where everything read before the Took is
            // about the order before and is refused.
            Assemble.took(assembly, assemblerHeld(Date.now()));
            retryPool();
          } else {
            // Through holding() as well: taking the mark back off an order the
            // rest of the rig has already forgotten should not depend on which
            // of the two ways of asking this line happens to use.
            var carried = heldOrders(Date.now()).filter(function (h) {
              return h.id === note.id;
            });
            if (carried.length) {
              setHeld(scanner.held.filter(function (h) { return carried.indexOf(h) === -1; }));
            }
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
        //
        // ...and, beside the yes or no, the order as the stream describes it
        // (heldForPanel), so Map view has the held end from this moment and
        // not from the next reading. Until one arrived the page drew the
        // accepted card's dropoff as that CARD's, and lost it with the card.
        // The offers page's ✓ taken back (or a pass) on an order in the car is
        // Drop for that order, `by: 'offers'` (offersTickHolds' header).
        var offersPutDown = [];
        if (note.kind === 'mark' && note.via === 'offers'
            && (note.accepted === null || note.accepted === false)) {
          offersPutDown = heldOrders(Date.now()).filter(function (h) { return h.id === note.id; });
          if (offersPutDown.length) putDown(Date.now(), 'offers', function () {}, offersPutDown);
        }
        var heldAfter = holding(Date.now());
        // The replaced order's drop row, the same shape putDown writes, and
        // the panel told — every panel, through the stream, and this one in
        // the reply too in case its stream is down. Best-effort like every
        // annotation: the mark is already on disk and is the driver's fact.
        // A row for EACH order put down: a trip replaced is every order of it
        // (placeTook), an add-on's row saying so (asAddOnRow).
        if (replacedHold && replacedHold.length) {
          var dropNow = Date.now();
          var dropRows = replacedHold.map(function (r) {
            var dropRow = { v: 1, kind: 'drop', at: dropNow, id: r.id,
                            seq: dropNow, acceptedAt: r.acceptedAt,
                            by: 'replaced' };
            // ...with two in the car at the press, as putDown says it.
            if (carriedAtTook >= 2) dropRow.carried = carriedAtTook;
            return JSON.stringify(asAddOnRow(dropRow, r)) + '\n';
          });
          appendLines(dropRows.join(''), function (dropErr) {
            if (dropErr) console.error('journal: could not record a replaced hold: '
                                       + dropErr.message);
          });
          var replacedSaid = { at: dropNow, saidForMs: HELD_REPLACED_SAID_MS };
          // A Took past MAX_HELD says WHICH order it put down, by its pay.
          if (putDownPay !== null) replacedSaid.pay = putDownPay;
          broadcast({ heldReplaced: replacedSaid });
        }
        var tookReply = { ok: true, note: note,
                          replaced: replacedHold && replacedHold.length
                            ? Object.assign({ at: Date.now(), saidForMs: HELD_REPLACED_SAID_MS },
                                            putDownPay !== null ? { pay: putDownPay } : {})
                            : null,
                          holding: !!heldAfter,
                          held: heldForPanel(heldAfter) };
        // With carrying two on: every order, and the one this Took ADDED —
        // the panel's Undo for it sends the untick this handler already
        // takes (accepted: null), which puts that order down and no other.
        // ...and with it in force by a trip (carryingTwo) — joined by this
        // Took, or before it: the panel's list is then the one in the car,
        // not the trip this Took replaced.
        if (carryTwo() || joinedAtTook || carryingTwo(Date.now())) {
          tookReply.orders = ordersForPanel(Date.now());
          tookReply.added = addedHold && heldById(holdIdOf(addedHold), Date.now())
            ? { holdId: holdIdOf(addedHold), id: addedHold.id,
                pay: numOrNull(addedHold.pay), undoForMs: UNDO_ADDED_MS }
            : null;
        }
        // The offers page is told what its press did to the car: put the order
        // in it, recorded only (and why), or put it down. And every panel is
        // told on the stream, as a reading tells it (`holding` with no
        // `ready`): no panel made this press, so no reply reaches one.
        if (note.kind === 'mark' && note.via === 'offers') {
          var nowHeld = heldOrders(Date.now()).filter(function (h) {
            return h.id === note.id;
          })[0] || null;
          tookReply.car = offersHolds ? { held: !!nowHeld, holdId: holdIdOf(nowHeld) }
            : offersPutDown.length ? { putDown: true }
            : fromOffers ? { held: false, why: fromOffers.why }
            : null;
          if (offersHolds || offersPutDown.length) {
            var carSaid = { holding: heldForPanel(heldAfter), heldBy: 'offers' };
            if (carryingTwo(Date.now())) carSaid.orders = ordersForPanel(Date.now());
            broadcast(carSaid);
          }
        }
        send(res, 200, JSON.stringify(tookReply),
             { 'Content-Type': 'application/json; charset=utf-8' });
      });
    });
  }

  /* Put the order down. The driver has dropped it off and the next offer is a
   * standalone job again.
   *
   * Separate from the mark, and deliberately: the mark is a permanent fact
   * about the journal — this offer was taken — and dropping it off does not
   * make that untrue, so the mark is never touched here. The hold itself is
   * not in the journal either: it lives in holding.json beside it, written by
   * setHeld() and read back by loadHolding() — see the comment above
   * those, which answers what this one used to say ("memory only").
   *
   * WHAT IS APPENDED is a second fact, not an edit of the first: a `kind:
   * 'drop'` row saying that at this moment the driver pressed Drop on this
   * offer. It is the one quantity the ledger says the rig lacks — the re-timing
   * entry in AUDITS.md's Settled closes on "the honest route to the driver's
   * actual question needs elapsed times, not a model of them ... That is a data
   * problem" — and it costs the driver nothing, because they already press
   * Drop and the hold already knows when the card was on the screen.
   *
   * COLLECTION ONLY. Nothing in this repository reads a drop row, and nothing
   * may divide by `at - acceptedAt`: an observed elapsed time turned into a
   * rate on the glass is the re-timing Settled refuses, arriving by a new door.
   * It is data to be held against the card's own stated minutes, by hand, once
   * a week of it exists. And it is censored: a row exists only for a press
   * made while holding() still held the job, so a delivery that ran past its
   * stated time × HOLD_OVERRUN + HOLD_GRACE_MS leaves no press row. It leaves
   * a `by: 'expiry'` row instead (expiredRows), dated when that clock ran out:
   * when the rig stopped counting the job, not when the job ended. Absence of
   * a press is not "never delivered".
   *
   * And it names the order the RIG was holding, which is not always the one
   * just delivered. The hold is one slot and the last tick takes it, so with
   * two jobs in the car a Drop pressed at the first delivery puts down — and
   * writes a row naming — the second, which is still in the car; the press at
   * the second delivery then finds nothing held and writes nothing. On the
   * week of 1,166 offers, 7 of the 31 ticks landed while an earlier tick was
   * still inside its own stated minutes, and in 6 of those the earlier job was
   * stated to end first. So `at - acceptedAt` on a drop row is an elapsed time
   * for the named job only when no other tick overlaps it; whoever reads these
   * rows checks the marks either side before trusting one.
   *
   * The tick that takes the slot now says so: it writes a drop row for the
   * order it put down, `by: 'replaced'` (see the mark handler), so a first job
   * no longer leaves the record with nothing saying how its hold ended. Its
   * `at - acceptedAt` is the time to the second tick, not to a delivery, and
   * is never an elapsed time for anything.
   *
   * `seq` is the press time, NOT 1. syncKey carries an unknown kind across on
   * `[kind, id, seq]`, so with a constant seq every drop row for one offer
   * collapses onto one key and the second is thrown away on the copy at home
   * as a duplicate of the first — the same collapse the `id: null` paragraph
   * in syncKey records. Re-ticking the same card and dropping it again is two
   * presses and two rows. Keyed by the fallback rather than by a branch of its
   * own, so a NucBox one build behind still stores it.
   *
   * It answers the same either way. Pressing "delivered" with nothing in the
   * car is not an error a driver needs told about; it is the state they wanted,
   * and there is no offer to name, so nothing is written. */
  if (req.method === 'POST' && req.url.split('?')[0] === '/api/delivered') {
    // holding(), not the raw slot: "there was an order to put down" has to mean
    // the same thing here as it does on the panel, or the driver is told they
    // put down a job the rig stopped counting an hour ago.
    //
    // Asked BEFORE the list is rewritten, and kept: after it, holding()
    // answers null and the row would have no offer to name (putDown).
    //
    // The row: {v, kind: 'drop', at, id, seq, acceptedAt}, `acceptedAt` dated
    // from the card as the hold is — see acceptedAt in the mark handler — so
    // this is the same clock holding() expires the job on. putDown() writes
    // it, for this press and for the GPS drop alike (which adds `by: 'gps'`);
    // a Took that replaces a hold writes the same row with `by: 'replaced'`,
    // and an order that outlives its own clock `by: 'expiry'`, dated when the
    // clock ran out (expiredRows).
    //
    // The order is down whether or not the row landed, so the answer is
    // still ok: the panel believes this reply about the HOLD (see the Drop
    // handler in live.html) and the hold is gone. The lost row is said out
    // loud like every other append on this server, because a collection
    // that silently stopped would be read in a week as a driver who never
    // pressed Drop.
    //
    // WITH TWO ORDERS IN THE CAR (carrying two on, or an add-on held with its
    // trip: carryingTwo) a press names one of them,
    // and the server does not guess which. One tap puts down the order the
    // latest good fix is at the pinned door of, or the one the GPS has seen
    // arrive (dropDecides); otherwise nothing is put down and the reply is a
    // chooser for the panel — ①, ② or both — whose answer comes back as
    // `holdIds`, and those rows say `by: 'chooser'`. Every row written with
    // two in the car says `carried: 2` (putDown).
    return readJsonBody(req, function (bodyErr, body) {
      var asked = (!bodyErr && body) || {};
      var now = Date.now();
      var orders = heldOrders(now);
      // ...and whether two were carried by a trip (carryingTwo) at the press:
      // the reply then says what is left, though one add-on left alone is no
      // longer a trip of two.
      var twoAtPress = carryingTwo(now);
      var json = { 'Content-Type': 'application/json; charset=utf-8' };
      var answer = function (was, extra) {
        var reply = { ok: true, wasHolding: was };
        if (carryTwo() || twoAtPress) {
          var left = holding(Date.now());
          reply.holding = !!left;
          reply.held = heldForPanel(left);
          reply.orders = ordersForPanel(Date.now());
        }
        send(res, 200, JSON.stringify(Object.assign(reply, extra || {})), json);
      };
      if (Array.isArray(asked.holdIds)) {
        var picked = orders.filter(function (o) {
          return asked.holdIds.indexOf(holdIdOf(o)) !== -1;
        });
        if (!picked.length) return answer(false);
        return putDown(now, 'chooser', function (was) { answer(was); }, picked);
      }
      if (twoAtPress && orders.length >= 2) {
        var one = dropDecides(orders, now);
        if (!one) {
          return answer(true, { choose: {
            kind: 'drop', closesInMs: CHOOSER_MS,
            rows: orders.map(function (o, i) {
              return { pick: holdIdOf(o), n: i + 1, pay: numOrNull(o.pay),
                       end: o.dropoff || null };
            }) } });
        }
        return putDown(now, null, function (was) { answer(was); }, one);
      }
      return putDown(now, null, function (was) { answer(was); });
    });
  }

  /* The chooser's answer (openChooser): {id, pick}, `pick` one of its rows —
   * an order's holdId, 'card', or 'neither'. Filed by the one road
   * (dropoffArrived) with `cue: 'chooser'`, onto the order or the card picked,
   * and said on the stream as any filed address is. Refused, filing nothing,
   * when the chooser it names has closed (CHOOSER_MS) or been replaced, or the
   * row is not one of its own. 'neither' files nothing and closes it. */
  if (req.method === 'POST' && req.url.split('?')[0] === '/api/choose') {
    return readJsonBody(req, function (err, body) {
      var json = { 'Content-Type': 'application/json; charset=utf-8' };
      var now = Date.now();
      var c = choosing;
      if (err || !body || !c || body.id !== c.id || now > c.until) {
        return send(res, 409, JSON.stringify({ ok: false, error: 'closed' }), json);
      }
      var said = { dropoff: c.d, at: now };
      if (body.pick === 'neither') {
        choosing = null;
        broadcast({ chooser: null });
        return send(res, 200, JSON.stringify({ ok: true, filed: null }), json);
      }
      if (body.pick === 'card') {
        if (!c.card || !scanner.offer || scanner.offer.id !== c.card) {
          return send(res, 409, JSON.stringify({ ok: false, error: 'not one of its rows' }), json);
        }
        choosing = null;
        dropoffArrived(said, { order: null, cue: 'chooser' });
      } else {
        var order = c.among.indexOf(body.pick) !== -1 ? heldById(body.pick, now) : null;
        if (!order) {
          return send(res, 409, JSON.stringify({ ok: false, error: 'not one of its rows' }), json);
        }
        choosing = null;
        dropoffArrived(said, { order: order, cue: 'chooser' });
      }
      broadcast({ chooser: null });
      if (said.dropoff) broadcast(said);
      retryPool();
      // ...a row whose order refused the press (a store's screen: Assemble.
      // dropoff, rule 5) filed nothing, and the reply says so; the stream has
      // just said why.
      var filed = said.dropoff && !said.dropoff.refused ? body.pick : null;
      send(res, 200, JSON.stringify({ ok: true, filed: filed }), json);
    });
  }

  /* The held order's end, pinned at door level by Map view (live.html).
   *
   * Body: {holdId, dropoff, lat, lon, name, doorLevel: true}. Kept on the hold
   * — and so in holding.json — only when every part of it is THIS hold's: the
   * hold it names is the one in the car, the dropoff it was pinned for is the
   * one the hold still names, and the door rule holds here too, asked of the
   * same functions the page chose it by (MV.searchPlan's house number, found
   * in the answer's name by MV.hasDoor). Anything else is refused with a
   * reason and changes nothing: a pin for a previous order, a street, a town.
   * See gpsArrival for what the pin is used for. */
  if (req.method === 'POST' && req.url.split('?')[0] === '/api/held-end') {
    return readBody(req, 4096, function (err, text) {
      var json = { 'Content-Type': 'application/json; charset=utf-8' };
      var body = null;
      try { body = err ? null : JSON.parse(text); } catch (e) { body = null; }
      if (!body || typeof body !== 'object') {
        return send(res, 400, JSON.stringify({ ok: false, error: 'not JSON' }), json);
      }
      // The order the pin names, among those in the car: with more than one,
      // a pin for one is not refused for not being the first.
      var h = heldById(body.holdId, Date.now());
      var why = null;
      var plan = h && typeof h.dropoff === 'string' ? MV.searchPlan(h.dropoff) : null;
      if (!holding(Date.now())) why = 'nothing held';
      else if (!h) why = 'not the order in the car';
      else if (body.dropoff !== h.dropoff) why = 'not where that order ends';
      else if (body.doorLevel !== true || !plan || plan.kind !== 'street' || !plan.door
               || !MV.hasDoor({ name: body.name }, plan.house)) why = 'not door level';
      else if (typeof body.lat !== 'number' || typeof body.lon !== 'number'
               || !isFinite(body.lat) || !isFinite(body.lon)
               || Math.abs(body.lat) > 90 || Math.abs(body.lon) > 180) why = 'no position';
      if (why) return send(res, 409, JSON.stringify({ ok: false, error: why }), json);
      // The first valid pin for this dropoff wins — the server's own search
      // (searchHeldEnd) or an earlier post — and a later one is a no-op, so an
      // arrival already counted is never reset by a second opinion.
      if (!heldEndPin(h)) {
        h.endPin = { dropoff: h.dropoff, lat: body.lat, lon: body.lon,
                     doorLevel: true, pinnedAt: Date.now() };
        // A new end: whatever was learnt about being at an old one (for a
        // dropoff the hold no longer names) is not about this one.
        delete h.arrivedAt;
        delete h.endWhy;
        delete h.endWhyFor;
        resetArrival(holdIdOf(h));
        saveHold(h);
      }
      send(res, 200, JSON.stringify({ ok: true }), json);
    });
  }

  /* One of the held order's pickups, pinned by Map view (live.html) inside
   * the held card's disc. Body: {holdId, lat, lon, q}. Kept on the hold (at
   * most PICKUP_PINS_MAX, the newest) for the restaurant guard (pickupNearEnd):
   * a door within PICKUP_GUARD_M of one is not armed; and, named by `q` — the
   * planner line it was searched for — for the GPS to mark that pickup
   * visited (visitPickups). A `q` that is not a string is no name. A pin
   * for another hold, or with no position, is refused and changes nothing.
   * This server searches for the same pickups itself (searchHeldPickup), so
   * Map view need not be opened for the guard to hold; the first valid pin
   * for a text wins, the page's or the server's (keepPickupPin), and the
   * page's says no `by`. */
  if (req.method === 'POST' && req.url.split('?')[0] === '/api/held-pickup') {
    return readBody(req, 1024, function (err, text) {
      var json = { 'Content-Type': 'application/json; charset=utf-8' };
      var body = null;
      try { body = err ? null : JSON.parse(text); } catch (e) { body = null; }
      if (!body || typeof body !== 'object') {
        return send(res, 400, JSON.stringify({ ok: false, error: 'not JSON' }), json);
      }
      var h = heldById(body.holdId, Date.now());
      var why = null;
      if (!holding(Date.now())) why = 'nothing held';
      else if (!h) why = 'not the order in the car';
      else if (typeof body.lat !== 'number' || typeof body.lon !== 'number'
               || !isFinite(body.lat) || !isFinite(body.lon)
               || Math.abs(body.lat) > 90 || Math.abs(body.lon) > 180) why = 'no position';
      if (why) return send(res, 409, JSON.stringify({ ok: false, error: why }), json);
      // The one path this server's own search keeps a pickup by too, guard
      // and all (keepPickupPin).
      keepPickupPin(h, { lat: body.lat, lon: body.lon },
                    typeof body.q === 'string' ? body.q : null, null);
      send(res, 200, JSON.stringify({ ok: true }), json);
    });
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
    // A press asks the question again, and the panel forgets the last answer's
    // stops the moment it is pressed: so does the order in the car. See
    // forgetPlanner.
    forgetPlanner(Date.now());
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

  // Rows arriving from a scanner that is not this machine.
  //
  // The rig lives in a car behind cellular NAT, so nothing here can reach it —
  // it has to push, and it pushes to whatever host is running this file with
  // SCANNER=0 and JOURNAL pointed at the copy. That copy is the reason this
  // exists: the journal is the one irreplaceable thing the rig produces, 5.7MB
  // a week of driving (rpi/journal.py's WEEK_BYTES, where that is measured),
  // and until now there was exactly one of it, on an SD card, in a car.
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
      // Held from here, not from readJournal: the body is already in hand by
      // now, so the lock covers the read-modify-write and nothing slower.
      // Every path out of the handler below goes through `fail` or `finish`,
      // and both release.
      ingestLock(function (release) {
      var fail = function (why, code) {
        release();
        send(res, code || 400, JSON.stringify({ ok: false, error: why }),
             { 'Content-Type': 'application/json; charset=utf-8' });
      };
      var finish = function (body) {
        release();
        send(res, 200, body,
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
          return finish(JSON.stringify({ ok: true, added: 0,
                                         malformed: malformed,
                                         have: existing.length }));
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
          finish(JSON.stringify({ ok: true, added: fresh.length,
                                  malformed: malformed,
                                  have: existing.length + fresh.length }));
          });
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
  /* Places the BROWSER has looked up, kept where they outlive the browser.
   *
   * The map page's geocode cache lived in localStorage and nowhere else, so it
   * belonged to whichever browser did the placing. Check the map on the laptop
   * and again on the phone and that is two full runs; clear site data and it is
   * gone. Measured on the owner's own week: 1,325 distinct places at the
   * one-a-second rate limit is about 24 minutes to rebuild. "It can always be
   * looked up again" is true and is not the same as cheap.
   *
   * THE RIG STILL NEVER GEOCODES. This stores an answer the browser already
   * has; nothing here asks anybody anything. That rule is about who talks to
   * the geocoder, and it is unchanged.
   *
   * Kept in its own file and deliberately NOT in the journal. Ingest's
   * idempotence is a syncKey set built over the whole journal, and the journal
   * is the one artefact that cannot be regenerated — a cache that can be
   * regenerated has no business sharing a file with it.
   *
   * The place NAMES are already on any machine running this: they are the
   * `pickup` and `dropoff` on every journal row, and the journal already syncs.
   * What this adds is a latitude and a longitude for a string that is here
   * anyway, which is why it is stored beside the journal on whichever host the
   * driver points the page at — the NUC, if that is where they do map checks.
   */
  // The NucBox's search and router, relayed — see nbxRoute.
  if (req.method === 'GET' && /^\/api\/nbx(\/|$)/.test(req.url.split('?')[0])) {
    return nbxRoute(req, res);
  }
  // ...and the street index, on the machine that has it — see streetsRoute.
  if (req.method === 'GET' && /^\/api\/streets(\/|$)/.test(req.url.split('?')[0])) {
    return streetsRoute(req, res);
  }

  if (req.url.split('?')[0] === '/api/places') {
    var placesPath = path.join(path.dirname(JOURNAL_PATH), 'places.json');
    var placesReply = function (code, body) {
      send(res, code, JSON.stringify(body),
           { 'Content-Type': 'application/json; charset=utf-8' });
    };
    if (req.method === 'GET') {
      return fs.readFile(placesPath, 'utf8', function (readErr, text) {
        // A file that is not there yet is an empty cache, not a fault: the
        // first map check on a fresh box is the ordinary way this starts.
        if (readErr && readErr.code === 'ENOENT') {
          return placesReply(200, { ok: true, places: {}, stored: 0 });
        }
        // ...and a file that IS there and cannot be read is the same lost 24
        // minutes as one that will not parse, so it says so the same way. It
        // answered `stored: null` and nothing else, which no page reads as
        // anything: were places.json's permissions to change on the NUC, or
        // a directory to take its name, the map would simply be slow again
        // for those 24 minutes with no word about why.
        if (readErr) {
          return placesReply(200, { ok: true, places: {}, stored: null,
                                    unreadable: 'places.json could not be read ('
                                                + (readErr.code || readErr.message) + ')' });
        }
        var held;
        try { held = JSON.parse(text); } catch (e) { held = null; }
        if (!held || typeof held !== 'object' || Array.isArray(held)) {
          // Said rather than swallowed. A cache file that will not parse is a
          // silent re-run of all 24 minutes, and the driver would be told
          // nothing about why.
          return placesReply(200, { ok: true, places: {}, stored: 0,
                                    unreadable: 'places.json did not parse' });
        }
        placesReply(200, { ok: true, places: held,
                           stored: Object.keys(held).length });
      });
    }
    // ...and thrown away, which is the one control that can remove a bad
    // answer from this rig at all.
    //
    // Without this, map.html's "Forget lookups" cleared the BROWSER's copy and
    // said "remembered lookups thrown away" — and the next press of Load
    // copied every one of them back off this server, because loadPlaces() GETs
    // the whole set and load() is also what runs when the page opens. The
    // button undid itself, silently, on the first thing anyone presses after
    // it.
    //
    // Whole-file and not per key. Correcting ONE place was proposed twice and
    // refused twice — see AUDITS — and this is not that: it is the wholesale
    // wipe the page already offered and could not deliver.
    if (req.method === 'DELETE') {
      return fs.readFile(placesPath, 'utf8', function (readErr, text) {
        var had = 0;
        if (!readErr) {
          try {
            var held = JSON.parse(text);
            if (held && typeof held === 'object' && !Array.isArray(held)) {
              had = Object.keys(held).length;
            }
          } catch (e) { had = 0; }
        }
        fs.unlink(placesPath, function (rmErr) {
          // Already absent is the state this asks for, not a failure to reach
          // it. Anything else is said rather than swallowed: a button that
          // reports success over a file it could not remove is the fault this
          // endpoint exists to end.
          if (rmErr && rmErr.code !== 'ENOENT') {
            console.error('places: ' + rmErr.message);
            return placesReply(500, { ok: false, error: rmErr.code });
          }
          placesReply(200, { ok: true, removed: had });
        });
      });
    }
    if (req.method === 'POST') {
      return readBody(req, MAX_SYNC_BODY, function (err, text) {
        if (err) return placesReply(400, { ok: false, error: err.message });
        var sent;
        try { sent = JSON.parse(text); } catch (e) { sent = null; }
        if (!sent || typeof sent !== 'object' || Array.isArray(sent)) {
          return placesReply(400, { ok: false, error: 'not a set of places' });
        }
        // MERGED, never written over. Two browsers place different days of the
        // same journal, and a POST that replaced the file would have whichever
        // finished last throw the other's work away — the same fault the map
        // page's own remember() was fixed for.
        // Serialised, because what follows is a read, a merge and a write on a
        // file two browsers reach at once.
        //
        // THE QUEUE IS THE CURE HERE, not the unique temporary below. Measured
        // on the real server, two concurrent POSTs of 600 places and 1 against
        // a seeded 1,325-place file, ten runs: two left the file unparseable
        // and the other eight lost one writer's batch entirely, replying
        // `stored: 1925` over a file holding 1,326. Zero of ten came out right;
        // with the queue, ten of ten do. The unique name cannot be tested at
        // this site at all — the queue means two writes never hold the
        // temporary at once — so it is here as the uniform rule
        // `rpi/test_lint.py` now enforces across all four renames in this
        // repository, and not as a claim about this endpoint. What the queue
        // buys that a name cannot is the lost update: the second read must not
        // happen before the first write lands, and that is the eight.
        fileLock('places', function (release) {
        // Every exit from here goes through `done`, so the queue cannot be left
        // held by a path that forgot. `release` is idempotent — it guards a
        // double shift — but a MISSED release strands every later batch behind
        // a lock nobody holds, and that is the failure this shape removes
        // rather than documents. There are five exits below and all five are a
        // `return done(...)`.
        var done = function (code, body) { release(); placesReply(code, body); };
        fs.readFile(placesPath, 'utf8', function (readErr, before) {
          var held = {};
          if (!readErr) {
            try { held = JSON.parse(before) || {}; } catch (e) { held = {}; }
            if (typeof held !== 'object' || Array.isArray(held)) held = {};
          }
          var added = 0;
          Object.keys(sent).forEach(function (k) {
            var v = sent[k];
            // A coordinate, or null for "asked, nothing there" — which is worth
            // keeping, because it is what stops the next run asking again. What
            // is NOT kept is undefined, "could not ask": storing that would
            // turn one dead spot on I-75 into a permanent answer.
            var ok = v === null
              || (v && typeof v === 'object'
                  && typeof v.lat === 'number' && isFinite(v.lat)
                  && typeof v.lon === 'number' && isFinite(v.lon));
            if (!ok) return;
            if (!Object.prototype.hasOwnProperty.call(held, k)) added++;
            held[k] = v;
          });
          if (!added) {
            return done(200, { ok: true, added: 0,
                                stored: Object.keys(held).length });
          }
          var body = JSON.stringify(held) + '\n';
          var tmp = partName(placesPath);
          withDirectory(placesPath, function (dirErr) {
            if (dirErr) {
              console.error('places: ' + dirErr.message);
              return done(500, { ok: false, error: dirErr.message });
            }
            fs.writeFile(tmp, body, function (writeErr) {
              if (writeErr) {
                fs.unlink(tmp, function () {});
                console.error('places: ' + writeErr.message);
                return done(500, { ok: false, error: writeErr.message });
              }
              // Renamed rather than written in place, the same way the config
              // backup is: a half-written cache that will not parse costs the
              // whole 24 minutes back.
              fs.rename(tmp, placesPath, function (renameErr) {
                if (renameErr) {
                  fs.unlink(tmp, function () {});
                  console.error('places: ' + renameErr.message);
                  return done(500, { ok: false, error: 'could not save' });
                }
                done(200, { ok: true, added: added,
                             stored: Object.keys(held).length });
              });
            });
          });
        });
        });
      });
    }
  }

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
      //
      // The overlap here needs no imagining: sync.py's own stderr tells the
      // operator to run `--all` by hand while the installed ten-minute timer
      // keeps ticking. Two of those at once left `config-backup.json`
      // unparseable at 60,168 bytes — one body's JSON followed by part of the
      // other's — and what is lost is the copy of the calibration on the one
      // machine that is NOT in the car. Re-aiming a camera at the roadside is
      // an afternoon, and the loss is believed until somebody tries to restore.
      //
      // The unique `.part` name below is the whole cure, and deliberately the
      // ONLY one. A queue was written here too and then taken out: unlike the
      // places batch there is nothing to lose to a lost update — the read is
      // only a "has it changed" test, so last-writer-wins is the right answer
      // and a redundant write is the worst a race can cost. With both in place
      // neither could be tested, because each hid the other; the suite passed
      // with the temporary's name reverted. One cure, one check.
      var fin = function (code, b) { reply(code, b); };
      fs.readFile(dest, 'utf8', function (readErr, before) {
        if (!readErr && before === body) return fin(200, { ok: true, changed: false });
        var tmp = partName(dest);
        withDirectory(dest, function (dirErr) {
          if (dirErr) {
            console.error('config backup: ' + dirErr.message);
            return fin(500, { ok: false,
                                error: 'could not create ' + path.dirname(dest)
                                       + ' (' + dirErr.code + ')' });
          }
          fs.writeFile(tmp, body, function (writeErr) {
          if (writeErr) {
            fs.unlink(tmp, function () {});
            console.error('config backup: ' + writeErr.message);
            return fin(500, { ok: false,
                                error: 'could not save (' + writeErr.code + ')' });
          }
          fs.rename(tmp, dest, function (renameErr) {
            if (renameErr) {
              fs.unlink(tmp, function () {});
              console.error('config backup: ' + renameErr.message);
              return fin(500, { ok: false, error: 'could not save' });
            }
            console.log('config backup: updated ' + dest);
            fin(200, { ok: true, changed: true });
          });
          });
        });
      });
    });
  }

  // What the far end already has, so a sender knows where to start. Cheap
  // enough to call every few minutes and the only thing the rig needs to ask.
  // The driver's own tags, verbatim, for the rig to pull back from the copy.
  //
  // The sync ran one way. A tick made on the copy at home — the likelier
  // place to review a week, on a monitor rather than an 800x480 panel — was
  // written to the copy's journal and stayed there: the rig's offers page
  // showed that week untagged and its advice ran without the ticks, and
  // advise() says itself that tagging a handful of trips is worth more than
  // another shift of scanning. This is the other direction. Raw rows, not
  // the folded view /api/journal gives, because what is being copied is the
  // record of what the driver did, and the rig folds it itself. Unauthenticated
  // like /api/journal/newest: the same VPN, the same driver's own data.
  if (req.method === 'GET' && req.url.split('?')[0] === '/api/journal/notes') {
    var sinceNotes = clampNumber((url.parse(req.url, true).query || {}).since,
                                 0, 4102444800000, 0);
    return readJournal(function (rows, readErr) {
      if (!rows) {
        return send(res, 200, JSON.stringify({
          ok: false, readable: false,
          error: 'cannot read the journal (' + (readErr && readErr.code || 'unknown') + ')'
        }), { 'Content-Type': 'application/json; charset=utf-8' });
      }
      // The driver's tags, and the offers the driver made — typed on the
      // keypad or read by the phone's own scanner — which are rows nothing
      // but a browser wrote and so exist only where that browser was pointed.
      // Made on the copy at home, they would otherwise stay there like a mark
      // did.
      var notes = rows.filter(function (r) {
        return r && (r.kind === 'mark' || r.kind === 'rule'
                     || r.typed === true || r.browser === true)
          && (r.at || 0) >= sinceNotes;
      });
      send(res, 200, JSON.stringify({ ok: true, notes: notes }),
           { 'Content-Type': 'application/json; charset=utf-8' });
    });
  }

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
      // ...and the same count over a window the sender names, which is what
      // makes the reconciliation below an apples-to-apples one.
      //
      // The sender only ever ships the last `--days`, so the offers it holds
      // from before that window are not a gap and must not be counted as one.
      // It windows its own side; if this side answers with an all-time total,
      // the comparison is a windowed count against an unwindowed one and the
      // shortfall can never be seen. `since` is the sender's window, anchored
      // to this copy's own newest row so both edges are the same instant.
      var since = Number((url.parse(req.url, true).query || {}).since);
      var wantWindow = isFinite(since) && since > 0;
      // Worked out once per request rather than per row: it is a fact about
      // this machine's clock, not about the row, and asking Date.now() forty
      // thousand times inside a fold would also let the ceiling drift while
      // the fold is running.
      var ceiling = futureCeiling();
      var newest = 0, offers = 0, offersSince = 0;
      rows.forEach(function (r) {
        if (r.kind) return;                       // a tag, not an offer
        offers++;
        /* A moment that never happened is not a position in the offers.
         *
         * This line compared `(r.at || 0)` and then assigned the RAW `r.at`,
         * with no ceiling at either end. One row stamped 1e20 — a phone with a
         * wrong clock, and journal-client.js takes `at` from the phone's own
         * Date.now() — made this answer `newest: 1e20`. sync.py sets
         * `floor = newest - 1h` from that, rows_since then keeps only rows
         * below CLOCK_BELIEVABLE_AFTER, and every real offer from that moment
         * on is skipped. For ever: nothing ever looks further back.
         *
         * And it is silent at every step. The shortfall check cannot see it —
         * its own window is anchored to the same poisoned `newest`, so both
         * sides count the one bad row and agree. The run exits 0, says
         * "nothing new" (suppressed by --quiet in the installed unit) and
         * refreshes the .synced stamp, so doctor.py reports a backup made
         * minutes ago. The only copy of the one file that cannot be
         * regenerated stops growing while both ends report success.
         *
         * Sanitised once and used for both answers, because a row that is not
         * a moment is not inside the sender's window either — and counting it
         * there would be the same disagreement one line down. Erring this way
         * makes the far end look short and the sender re-send, which is the
         * safe direction; the other way round is the one that loses rows. */
        var at = (typeof r.at === 'number' && isFinite(r.at)
                  && r.at <= ceiling) ? r.at : 0;
        if (wantWindow && at >= since) offersSince++;
        if (at > newest) newest = at;
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
                                      // ...counted over the window the sender
                                      // asked about, when it asked. Absent
                                      // when it did not, and absent from older
                                      // builds, which is how the sender knows
                                      // to fall back to the whole-file
                                      // comparison rather than reading a
                                      // missing key as a copy holding nothing.
                                      offersSince: wantWindow ? offersSince : undefined,
                                      can: SYNC_CAN }),
           { 'Content-Type': 'application/json; charset=utf-8' });
    });
  }

  /* The driver's cost per mile — ONE key, and deliberately not "the settings".
   *
   * Every verdict the rig prints is net of it, and it was the one number in
   * them nobody had chosen: `costPerMile` is 0.3 on all 1,166 rows of the real
   * week, the factory seed, because the rig's copy lives in a JSON file edited
   * over SSH and read once at startup. It moves the answer a lot. Re-scored at
   * $0.00 / $0.15 / $0.30 / $0.45 / $0.70 a mile — rate()'s own arithmetic,
   * which reproduces the rig's 106 recorded greens exactly at $0.30 — the same
   * week has 290 / 181 / 106 / 78 / 52 green cards and 146.6 / 88.7 / 46.0 /
   * 31.4 / 21.5 green job-hours: 89 hours or 31 between two defensible
   * figures. The rig cannot work it out (31 of those 1,166 offers are ticked
   * taken, so its miles are offered miles, not driven ones); it has to be told.
   *
   * WHY ONE KEY. The `settings` block is not a list of preferences. It also
   * holds `keepPlaces`, which decides whether addresses are written into the
   * append-only journal at all, and `pad` and `secondsPerItem`, which move
   * `billedMinutes` and so every rate the rig prints and stores. A route
   * scoped to "the block" could switch off place recording, or shift the money
   * on every row that follows, from a screen, with nothing on any page saying
   * so. So a body naming anything but `costPerMile` is refused whole, and the
   * scan loop reads nothing but `costPerMile` out of the file either.
   *
   * WHY IT SAYS WHICH MACHINE. The copy at home runs this same server, with
   * SCANNER=0 and an rpi/config.json of its own. A POST there would write a
   * file no scanner ever reads and answer ok — the driver would believe the
   * rig had it. So `scanner` is in every answer, and a machine with none
   * refuses the write rather than performing it.
   *
   * Through the handoff directory rather than into rpi/config.json. The scan
   * loop writes that file from its own memory, whole — save_config, at four
   * call sites before this one — so a value this process wrote there could be
   * written back
   * over by the scanner's next save before it had read it — an ok answered for
   * a change that silently un-happens. The scanner takes the request, applies
   * it in the loop, saves it itself, and says what it is now using; GET answers
   * from that, not from a file.
   *
   * Nothing is restarted for it: a restart is an aim-and-calibrate cycle mid-
   * shift. The panel's existing "after $0.30/mi costs" on every reading is how
   * the driver sees it take effect.
   */
  if (req.url.split('?')[0] === '/api/settings'
      && (req.method === 'GET' || req.method === 'POST')) {
    var settingsReply = function (code, body) {
      send(res, code, JSON.stringify(body),
           { 'Content-Type': 'application/json; charset=utf-8' });
    };
    // A request written and not yet taken, so a panel opened in between can
    // say the change is on its way rather than that it did not happen.
    var pendingCost = function (then) {
      fs.readFile(SETTINGS_PATH, 'utf8', function (err, text) {
        var sent = null;
        if (!err) {
          try { sent = JSON.parse(text).costPerMile; } catch (e) { sent = null; }
        }
        then(typeof sent === 'number' ? sent : null);
      });
    };
    if (req.method === 'GET') {
      if (!scannerEnabled()) {
        return settingsReply(200, { ok: true, scanner: false, costPerMile: null,
                                    pending: null });
      }
      return pendingCost(function (pending) {
        settingsReply(200, { ok: true, scanner: true, running: !!scanner.proc,
                             // null until the scan loop has said: aiming and
                             // calibrating come first, and a figure read off a
                             // file here would be a guess about the process.
                             costPerMile: scanner.costPerMile,
                             pending: pending });
      });
    }
    return readJsonBody(req, function (err, body) {
      if (err || !body || Array.isArray(body)) {
        return settingsReply(400, { ok: false, error: 'not a JSON object' });
      }
      var others = Object.keys(body).filter(function (k) { return k !== 'costPerMile'; });
      if (others.length) {
        return settingsReply(400, {
          ok: false,
          error: 'only costPerMile can be set here; refused: ' + others.join(', ') });
      }
      var cost = body.costPerMile;
      // A number, not something that reads as one. The config file is lenient
      // because a person hand-edits it (see OP.setting); a screen sends JSON,
      // and "0.45" arriving as a string is a client that is not this one.
      //
      // And no more than the keypad's own box allows (ui.js bindSetting clamps
      // setCost to 0..10). Without it the two doors answered the same question
      // two ways: the keypad would never send 45, but a slip on any other
      // client would have the rig price every mile at $45, and every reading
      // after it would print a confident PASS under "after $45.00/mi costs".
      if (typeof cost !== 'number' || !isFinite(cost) || cost < 0 || cost > 10) {
        return settingsReply(400, { ok: false,
                                    error: 'costPerMile must be a number from 0 to 10' });
      }
      if (!scannerEnabled()) {
        return settingsReply(409, {
          ok: false, scanner: false,
          error: 'no scanner runs on this machine, so nothing here would use '
                 + 'it — set it on the rig' });
      }
      // A name per request, for the reason /api/crop gives: two presses landing
      // together would interleave into one shared `.part` and the rename would
      // publish the mixture. No queue as well — there is nothing to merge, the
      // last figure typed is the right one, and a second cure would hide
      // whether the first one works (see /api/config/backup).
      var tmp = partName(SETTINGS_PATH);
      fs.writeFile(tmp, JSON.stringify({ costPerMile: cost }), function (writeErr) {
        var failed = function (e) {
          fs.unlink(tmp, function () {});
          console.error('settings: ' + e.message);
          settingsReply(500, { ok: false, scanner: true, error: 'could not save' });
        };
        if (writeErr) return failed(writeErr);
        fs.rename(tmp, SETTINGS_PATH, function (renameErr) {
          if (renameErr) return failed(renameErr);
          settingsReply(200, { ok: true, scanner: true, running: !!scanner.proc,
                               costPerMile: scanner.costPerMile, pending: cost });
        });
      });
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
      var card = cropCard(body);
      if (typeof card === 'string') return bad(card);
      // Written to a temporary name and renamed, because the scanner may be
      // reading this exact path at this exact moment and half a JSON object
      // parses as nothing at all.
      //
      // A name of its own per request, because one shared `.part` defeats the
      // very thing the rename is for: two drags landing together — a double tap
      // on a laggy link is all it takes — have both writes interleaving into one
      // file, and the rename then publishes whichever mixture won. Unique names
      // make each rename genuinely atomic with respect to the other.
      var tmp = partName(CROP_PATH);
      var failed = function (err) {
        fs.unlink(tmp, function () {});     // never leave a .part behind
        send(res, 500, JSON.stringify({ ok: false, error: 'could not save the box' }),
             { 'Content-Type': 'application/json; charset=utf-8' });
        console.error('crop box: ' + err.message);
      };
      fs.writeFile(tmp, JSON.stringify({ quad: quad, card: card }), function (writeErr) {
        if (writeErr) return failed(writeErr);
        fs.rename(tmp, CROP_PATH, function (renameErr) {
          if (renameErr) return failed(renameErr);
          send(res, 200, JSON.stringify({ ok: true, quad: quad, card: card }),
               { 'Content-Type': 'application/json; charset=utf-8' });
        });
      });
    });
  }

  // 📷 Snap — see takeSnap. POST because it writes, and because a GET would be
  // taken by anything that prefetches links. Answers once every part has
  // either landed or given its reason, so the reply is the whole account of
  // the press rather than a promise about it.
  if (req.method === 'POST' && req.url.split('?')[0] === '/api/snap') {
    return takeSnap(function (err, record) {
      if (err) {
        var why = err.code === 'NOTHING'
          ? 'nothing could be kept: ' + err.message
          : 'could not make a folder for it in ' + SNAPS_DIR + ': ' + (err.code || err.message);
        console.error('snap: ' + why);
        return send(res, 500, JSON.stringify({ ok: false, error: why }),
                    { 'Content-Type': 'application/json; charset=utf-8' });
      }
      send(res, 200, JSON.stringify(Object.assign({ ok: true }, record)),
           { 'Content-Type': 'application/json; charset=utf-8' });
    });
  }

  // ...and a note on one, from snaps.html: {snap: <folder>, note: <text>}.
  // See keepSnapNote.
  if (req.method === 'POST' && req.url.split('?')[0] === '/api/snap/note') {
    return readJsonBody(req, function (err, body) {
      var answer = function (status, reply) {
        send(res, status, JSON.stringify(reply), { 'Content-Type': 'application/json; charset=utf-8' });
      };
      if (err || !body) return answer(400, { ok: false, error: 'bad body' });
      keepSnapNote(body, answer);
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
    return send(res, 200, JSON.stringify(statusNow()),
                { 'Content-Type': 'application/json; charset=utf-8' });
  }

  // The snaps, for snaps.html and for anybody fetching them off the rig.
  if (pathname === '/api/snaps') {
    var shelf = describeSnaps();
    return send(res, 200, JSON.stringify({
      ok: true,
      // Where they are on the rig, so they can be copied off it some other way.
      where: SNAPS_DIR,
      keep: SNAPS_KEEP,
      // Which files are pictures, in the order snaps.html lays them out; what
      // each file is, which it gives each picture as its alt text; and how
      // long a note may be, which its note box is held to. A bundle says the
      // same.
      pictures: SNAP_PICTURES,
      about: SNAP_ABOUT,
      noteMax: SNAP_NOTE_MAX,
      unreadable: shelf.unreadable,
      snaps: shelf.snaps
    }), { 'Content-Type': 'application/json; charset=utf-8' });
  }

  // One or several snaps as one .html: /api/snaps/bundle?snap=<folder>&snap=…
  // Under /api/snaps/ with the rest, and before the route below that answers
  // everything else there; `bundle` is no name a press makes. See
  // sendSnapBundle.
  if (pathname === '/api/snaps/bundle') {
    var bundle = snapBundle(parsed.query.snap);
    if (bundle.error) {
      return send(res, bundle.status, bundle.error + '\n', { 'Content-Type': 'text/plain; charset=utf-8' });
    }
    return sendSnapBundle(res, bundle.names);
  }

  /* ...and one file out of one of them: a folder the list names, and a file
   * the list says that folder holds — snapNames (by way of isSnap) and
   * snapFiles, the list's own two questions, so nothing is served that the
   * list does not show.
   *
   * Nothing typed into the URL becomes a path until both have said yes, so
   * `..`, an encoded `..`, an absolute path and a name with a slash in it are
   * never looked up at all — and everything under /api/snaps/ is answered
   * here, so none of them falls through to the static handler to be judged by
   * a different rule. Neither answer follows a link, so a name that is right
   * and a link that points at rpi/config.json is not a snap file. That is
   * also why there is no realpath recheck here any more: a folder and a file
   * that are both real, inside snaps/, cannot resolve anywhere else, and the
   * recheck it would have been could not fail. */
  if (pathname.indexOf('/api/snaps/') === 0) {
    var snapAsk = /^\/api\/snaps\/([^/]+)\/([^/]+)$/.exec(pathname);
    var snapHeld = snapAsk && isSnap(snapAsk[1])
      && snapFiles(snapAsk[1]).some(function (f) { return f.file === snapAsk[2]; });
    if (!snapHeld) return send(res, 404, 'not found', { 'Content-Type': 'text/plain' });
    return serveFile(req, res, path.join(SNAPS_DIR, snapAsk[1], snapAsk[2]));
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
    return readJournal(function (rows, readErr, torn) {
      // This one may degrade — a driver looking at the offers page is better
      // served by the page than by a 500 — but not silently. An empty history
      // and an unreadable one look identical otherwise, and the second is the
      // one worth acting on.
      var unreadable = rows ? null : (readErr && readErr.code || 'unknown');
      rows = rows || [];
      /* The window, worked out before the fold rather than after it.
         It was computed forty lines below and used only to filter the fold's
         OUTPUT, so a request for today folded the whole year and then threw
         nearly all of it away. The figure is identical either way — rowsFor
         keeps every row that can change an answer inside the window — but the
         work is now proportional to the window the driver asked for. */
      var floor = since || (days > 0 ? Date.now() - days * 86400000 : 0);
      var offers = latestPerOffer(rows, floor);
      // Both taken off the array before anything filters it. `filter` returns a
      // new array and these ride on the old one as properties, so a line moved
      // below the first filter would quietly become an empty list — which reads
      // on the page as a shift where the rig was never asked, rather than as a
      // reader that dropped them.
      var seen = offers.seen || [];
      var pairs = offers.pairs || [];
      // The window first, then the count of what is hidden inside it.
      //
      // Counting before the filter meant the page said "3 offers are hidden and
      // left out of everything here" while looking at today, where "here" is
      // the window and the 3 were every hidden offer the journal has ever held.
      // A number that does not describe what is on screen is worse than no
      // number, because it is the one a driver checks their arithmetic against.
      // Rows stamped before the rig had a clock, taken out of EVERY window and
      // counted, rather than out of three windows and left in the fourth.
      //
      // A Pi has no real-time clock. It boots in 1970 and jumps when NTP
      // arrives, and anything it read before then is on disk with a date in
      // 1970. Those rows fell outside Today, 7 days and 30 days without a word
      // said — and on All, where `floor` is zero, they came BACK: a phantom
      // day headed "Thu, Jan 1" at the far end of the list, its offers counted
      // in every figure on the page under a date nobody drove. shiftSummary
      // already counts these for the driving screen; this is the same rule for
      // the same rows, and the page says how many there are.
      var beforeClock = 0;
      offers = offers.filter(function (r) {
        // Hidden ones are not counted, because shiftSummary does not count
        // them either, and the two pages printed different figures for the
        // same file: 2 here, 1 on the driving screen, over one hidden test
        // card read before NTP arrived.
        if ((r.at || 0) < CLOCK_BELIEVABLE_AFTER) {
          if (!r.hidden) beforeClock += 1;
          return false;
        }
        return !floor || (r.at || 0) >= floor;
      });
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
        // A journal that could not be READ is refused here rather than
        // downloaded as an empty spreadsheet.
        //
        // The branch above it exists for exactly this — "an empty history and
        // an unreadable one look identical otherwise, and the second is the
        // one worth acting on" — and the JSON reply carries `unreadable`,
        // `torn` and `truncated` further down so the offers page can say all
        // three. This branch returned before any of them, and toCsv([]) is a
        // header line and nothing else: 200 OK, Content-Disposition,
        // `uber-scan-offers.csv`, no rows. Indistinguishable from a quiet
        // week, on the one artefact a driver saves and a backup script
        // collects. README.md calls this "a CSV of everything".
        //
        // The state is not hypothetical: readJournal's own comment records a
        // server running as a user that could append to the journal and not
        // read it.
        if (unreadable) {
          return send(res, 503, 'the journal could not be read (' + unreadable
                      + ')\n', { 'Content-Type': 'text/plain; charset=utf-8' });
        }
        // Lines that WERE written and are now unreadable, and rows the cap
        // dropped. Neither can be a row in the file — a spreadsheet with an
        // extra row in it is a spreadsheet with a wrong total — so they go in
        // the headers, where curl -i and every HTTP client can see them and
        // nothing that parses the CSV has to change.
        var head = {
          'Content-Type': 'text/csv; charset=utf-8',
          'Content-Disposition': 'attachment; filename="uber-scan-offers.csv"'
        };
        if (torn) head['X-Uber-Scan-Torn'] = String(torn);
        if (total > offers.length) {
          head['X-Uber-Scan-Truncated'] = offers.length + ' of ' + total;
        }
        return send(res, 200, toCsv(offers), head);
      }
      // What the rig watched go past, over the same window. Summed here rather
      // than shipped row by row: there is one of these every couple of minutes
      // of scanning and the page wants the total, not the series.
      var watched = { saw: 0, kept: 0 };
      seen.forEach(function (r) {
        // The same clock rule as the offers, or on All — where `floor` is
        // zero — the cards tallied before NTP set the clock were counted as
        // watched while every offer from that stretch was set aside, and the
        // fraction recorded read lower than it was.
        if ((r.at || 0) < CLOCK_BELIEVABLE_AFTER) return;
        if (floor && (r.at || 0) < floor) return;
        watched.saw += r.saw || 0;
        watched.kept += r.kept || 0;
      });
      // Row by row, unlike `seen`, and not capped by `limit`.
      //
      // There is one of these per offer read with a job already in the car —
      // a handful in a shift, not the thousands the offer log holds — and each
      // one is a decision the driver may want to check against what happened.
      // A total would answer none of the questions worth asking of them.
      //
      // Newest first, because a shift is read from its end: the pairing a
      // driver wants is nearly always the one they just made.
      var window = pairs.filter(function (r) { return !floor || (r.at || 0) >= floor; })
                        .sort(function (a, b) { return (b.at || 0) - (a.at || 0); });
      send(res, 200, JSON.stringify({ count: offers.length, total: total,
                                      truncated: total > offers.length,
                                      days: days, hidden: hidden,
                                      watched: watched,
                                      // Null unless the journal is there and
                                      // could not be read, in which case the
                                      // emptiness below is not a record of a
                                      // quiet week.
                                      unreadable: unreadable,
                                      // Not a window figure: these rows have
                                      // no date, so they are in no window,
                                      // and the count is the same whichever
                                      // range is asked for.
                                      beforeClock: beforeClock,
                                      // Lines in the file that would not parse
                                      // at all. Different from `unreadable`,
                                      // which is the whole file being
                                      // unavailable: these are rows that were
                                      // written and are now gone, and they
                                      // cannot be got back. Reported for the
                                      // same reason `beforeClock` is — a row
                                      // missing from every figure with nothing
                                      // saying so is the one failure this
                                      // project keeps writing sections about.
                                      torn: torn || 0,
                                      pairs: window,
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
  // The order in the car, if the last run of this server left one behind.
  //
  // Said out loud, because it is state the driver did not press anything for
  // on THIS run and the panel will start offering pair lines against it. The
  // silent version of this would be a rig that quietly believes something
  // about the car that nobody told it.
  var back = loadHolding();
  if (back) {
    console.log('\ncarrying an order from before the restart: $'
                + (typeof back.pay === 'number' ? back.pay.toFixed(2) : '?')
                + ', ' + back.minutes + ' min'
                + (back.dropoff ? ' to ' + back.dropoff : '')
                + '\n  press Drop on the panel if it has already been delivered');
  }
  tidyGpsLogs();
});

/* The GPS logs, tidied once each time the server starts.
 *
 * tools/gpslog_tidy.py was a line the driver had to add to an untracked
 * Start.sh by hand, so a `git pull` never brought it; the logs went on filling
 * the card (5.4-9.0 MB an hour while driving). Run from here it arrives with
 * the pull. The tool's own rules decide everything: it skips the newest log
 * and anything written in the last ten minutes (gpspipe may be writing either),
 * does nothing on a clock that is not yet set, and never leaves the directory
 * it is given. A second run from a Start.sh that still has the line is the
 * same run again and finds nothing to do.
 *
 * GPSLOG_DIR names the directory (default ~/gpslog, where the README's gpspipe
 * line writes); GPSLOG_DIR= with nothing turns it off. A missing directory is
 * a rig without GPS logging and says nothing. The tidy runs beside the server,
 * never in its way: a failure is said once and the server carries on. */
var GPSLOG_DIR = process.env.GPSLOG_DIR !== undefined
  ? process.env.GPSLOG_DIR : path.join(os.homedir(), 'gpslog');

function tidyGpsLogs() {
  if (!GPSLOG_DIR) return;
  var st;
  try { st = fs.statSync(GPSLOG_DIR); } catch (e) { return; }
  if (!st.isDirectory()) return;
  var said = '';
  var child = spawn('python3',
                    [path.join(ROOT, 'tools', 'gpslog_tidy.py'), '--apply', GPSLOG_DIR],
                    { cwd: ROOT, stdio: ['ignore', 'pipe', 'pipe'] });
  function keep(d) { said = (said + d).slice(-4096); }
  child.stdout.on('data', keep);
  child.stderr.on('data', keep);
  child.on('error', function (e) {
    console.error('gps logs: the tidy could not run: ' + e.message);
  });
  child.on('close', function (code) {
    var last = said.trim().split('\n').pop() || '';
    if (code) console.error('gps logs: the tidy failed (exit ' + code + '): ' + last);
    else if (last) console.log('gps logs: ' + last);
  });
}

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

// Say now if the journal cannot be written where JOURNAL points, rather than
// on the first upload. On a fresh copy machine, `JOURNAL=/var/lib/uberscan/…`
// as a normal user started cleanly, answered /api/journal/newest with nothing,
// passed the rig's install gate, and only the first ingest failed with EACCES.
// The directory is made here if it can be, and the fix is printed if not.
if (process.env.JOURNAL) {
  withDirectory(JOURNAL_PATH, function (err) {
    if (!err) return;
    var dir = path.dirname(JOURNAL_PATH);
    console.error('\nJOURNAL points at ' + dir + ', which this user cannot create (' + err.code + ').');
    console.error('  sudo mkdir -p ' + dir + ' && sudo chown $USER ' + dir);
    console.error('  or point JOURNAL somewhere under your home directory.');
  });
}

// The NucBox's services, when set, so a map that falls back to the public one
// can be traced to a setting rather than guessed at. Nothing is said when
// neither is set: that is the ordinary install and today's behaviour.
if (NBX.search || NBX.route || NBX.streets) {
  console.log('\nNucBox search: ' + (NBX.search || 'not set (NUCBOX_SEARCH)')
              + '\nNucBox router: ' + (NBX.route || 'not set (NUCBOX_ROUTER)')
              + '\nNucBox streets: ' + (NBX.streets || 'not set (NUCBOX_STREETS)'));
}
// The street index this machine holds, when it holds one: what is in it and
// what it cost to load, measured here, so the driver reads the real figures
// off the NucBox rather than the estimate in the README.
if (STREETS.ix) {
  var sc = STREETS.ix.counts;
  console.log('\nStreet index: ' + sc.names + ' names, ' + sc.ways + ' ways, ' + sc.nodes
              + ' nodes from ' + STREETS_FILE + ', loaded in ' + STREETS.ms + ' ms, heap '
              + STREETS.heapMb + ' MB');
} else if (STREETS.why) {
  console.error('\n' + STREETS.why + ' — /api/streets answers that, not "no such street".');
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
