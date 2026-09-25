"""The phone's own scanner, driven through a real browser.

    python3 rpi/test_scanjs.py

scan.js runs the same parser as the rig over tesseract.js, on a phone the driver
is holding, and until now nothing tested it end to end at all. The hook it needs
was already there — `window.__scan`, with the comment "exposed so the test
harness can drive the same pipeline headlessly" — and no harness ever used it.

What that cost, measured: the browser handed the reader a picture sized by width
rather than by pixels, and because the scale was `Math.min(2, 1400 / width)` it
*upscaled* a phone-sized crop by up to double. Past about a megapixel tesseract
stops reading the largest text on the card, so every Uber Eats shop order came
back with its journey, its item count and its merchant read perfectly and no
payout at all. The rest of the card reading fine is what made it invisible.

Skipped where a browser cannot be had, the same way the live-view checks skip
without node: the Pi does not carry Playwright and does not need to.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ok = bad = 0


def eq(name, got, want):
    global ok, bad
    if got == want:
        ok += 1
    else:
        bad += 1
        print('FAIL  %s: got %r want %r' % (name, got, want))


def ok_(name, cond):
    eq(name, bool(cond), True)


def no_(name, cond):
    eq(name, bool(cond), False)


def skip(why):
    print('%s — skipping the browser-scanner checks' % why)
    sys.exit(0)


if shutil.which('node') is None:
    skip('no node on this machine')

import cv2                                                   # noqa: E402
import numpy as np                                           # noqa: E402
import pipeline as PL                                        # noqa: E402
import testcards as TC                                       # noqa: E402

if not TC.available():
    skip('no PIL or no usable font')

# Playwright drives the browser, and it is the one thing here that is not
# already a dependency of this project. Found however node can find it.
FIND_PW = '''
try { require.resolve('playwright'); process.stdout.write('yes'); }
catch (e) { process.stdout.write('no'); }
'''
env = dict(os.environ)
if 'NODE_PATH' not in env:
    for guess in ('/opt/node22/lib/node_modules', '/usr/lib/node_modules',
                  '/usr/local/lib/node_modules'):
        if os.path.isdir(os.path.join(guess, 'playwright')):
            env['NODE_PATH'] = guess
            break
found = subprocess.run(['node', '-e', FIND_PW], capture_output=True, env=env)
if found.stdout.strip() != b'yes':
    skip('no playwright')


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


# The card as a driver frames it in the reticle: the offer, not the whole phone.
CARDS = [('a ride card', TC.uberx_screen, 16.05),
         ('a shop order', TC.shop_screen, 7.09),
         ('a delivery card', TC.doordash_screen, 41.11)]

DRIVER = r'''
const { chromium } = require('playwright');
const fs = require('fs'), path = require('path');
const [base, dir] = process.argv.slice(2);
const cards = JSON.parse(fs.readFileSync(path.join(dir, 'cards.json'), 'utf8'));

(async () => {
  let browser;
  for (const exe of JSON.parse(process.env.PW_EXES || '[]').concat([null])) {
    try {
      browser = await chromium.launch(exe ? { executablePath: exe } : {});
      break;
    } catch (e) { /* try the next one */ }
  }
  if (!browser) { console.log(JSON.stringify({ skip: 'no chromium' })); return; }
  const page = await (await browser.newContext(
    { viewport: { width: 420, height: 900 } })).newPage();
  await page.goto(base + '/scan.html', { waitUntil: 'domcontentloaded' });
  // A running cost, because without one there is nothing to take off and the
  // raw rate and the net rate are one number. costPerMile defaults to 0, so a
  // page opened cold cannot exercise the difference between them at all.
  await page.evaluate(() => localStorage.setItem('uberscan.settings.v1',
    JSON.stringify({ target: 25, band: 15, costPerMile: 0.35, pad: 0,
                     secondsPerItem: 0 })));
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForFunction('window.__scan && window.__scan.ready()',
                             null, { timeout: 180000 });
  const out = { reads: {}, fit: {} };
  for (const c of cards) {
    const data = 'data:image/png;base64,'
      + fs.readFileSync(path.join(dir, c.file)).toString('base64');
    const r = await page.evaluate(async s => {
      const got = await window.__scan.readImage(s);
      return { pay: got.parsed.pay, minutes: got.parsed.minutes,
               miles: got.parsed.miles, ready: got.rate.ready,
               state: got.rate.state, perHour: got.rate.perHour || null,
               gross: got.rate.grossPerHour || null,
               shown: document.getElementById('perHour').textContent.trim(),
               raw: document.getElementById('rawRate').textContent.trim(),
               rawShown: !document.getElementById('rawRate').hidden };
    }, data);
    out.reads[c.name] = r;
  }
  // ...and the same cards with no running cost set at all, where the raw rate
  // and the net rate are one number and showing it twice is noise beside the
  // one figure that decides an offer. Without this pass nothing exercises the
  // negative side of that rule: every card in the corpus has a distance, so
  // with a cost per mile set they all differ.
  await page.evaluate(() => localStorage.setItem('uberscan.settings.v1',
    JSON.stringify({ target: 25, band: 15, costPerMile: 0, pad: 0,
                     secondsPerItem: 0 })));
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForFunction('window.__scan && window.__scan.ready()',
                             null, { timeout: 180000 });
  out.free = {};
  for (const c of cards) {
    const data = 'data:image/png;base64,'
      + fs.readFileSync(path.join(dir, c.file)).toString('base64');
    out.free[c.name] = await page.evaluate(async s => {
      const got = await window.__scan.readImage(s);
      return { ready: got.rate.ready, state: got.rate.state,
               perHour: got.rate.perHour || null,
               gross: got.rate.grossPerHour || null,
               rawShown: !document.getElementById('rawRate').hidden };
    }, data);
  }

  for (const wh of JSON.parse(process.env.FIT_CASES)) {
    out.fit[wh.join('x')] = await page.evaluate(
      p => window.__scan.fitForOcr(p[0], p[1]), wh);
  }

  // Half a card: what the page says when the reading is not whole.
  const frag = 'data:image/png;base64,'
    + fs.readFileSync(path.join(dir, 'fragment.png')).toString('base64');
  out.fragment = await page.evaluate(async s => {
    const got = await window.__scan.readImage(s);
    return { pay: got.parsed.pay, ready: got.rate.ready, state: got.rate.state,
             perHour: got.rate.perHour || null,
             shown: document.getElementById('perHour').textContent.trim(),
             label: document.getElementById('verdictLabel').textContent.trim(),
             warned: !document.getElementById('warn').hidden,
             warning: document.getElementById('warn').textContent.trim() };
  }, frag);

  // A reader that throws every cycle must not leave the last verdict standing.
  out.afterThrow = await page.evaluate(async () => {
    const before = document.getElementById('perHour').textContent.trim();
    window.__scan.failRead(4);
    return { before: before,
             after: document.getElementById('perHour').textContent.trim(),
             label: document.getElementById('verdictLabel').textContent.trim() };
  });

  // A locked card reaches the journal, once per card; a fragment does not; and
  // with the rig out of reach the row is kept and goes with the next lock.
  const journal = () => page.evaluate(async () => {
    const r = await fetch('/api/journal?days=1');
    const d = await r.json();
    return d.offers.map(o => ({ id: o.id, browser: o.browser, pay: o.pay,
                                minutes: o.minutes, miles: o.miles,
                                perHour: o.perHour, state: o.state, kind: o.kind }));
  });
  const whole = 'data:image/png;base64,'
    + fs.readFileSync(path.join(dir, cards[0].file)).toString('base64');
  const shop = 'data:image/png;base64,'
    + fs.readFileSync(path.join(dir, cards[1].file)).toString('base64');
  // Every whole card read above recorded a row of its own; let those land
  // before the snapshot everything below is a difference from. The delivery
  // card is judged against the clock and is not whole to this harness, so
  // the last card recorded above was the shop order and the ride card below
  // is a new offer. Ride and shop alternate from here: a different payout is
  // a different offer, whatever came before it.
  await page.waitForTimeout(800);
  out.recorded = { before: await journal() };
  out.recorded.read = await page.evaluate(async s => {
    const got = await window.__scan.readImage(s);
    return { pay: got.parsed.pay, perHour: got.rate.perHour, state: got.rate.state };
  }, whole);
  await page.waitForTimeout(500);
  out.recorded.afterWhole = await journal();
  // The same card, read again a moment later: one card, one row.
  await page.evaluate(async s => { await window.__scan.readImage(s); }, whole);
  await page.waitForTimeout(500);
  out.recorded.afterAgain = await journal();
  out.recorded.fragmentComplete = await page.evaluate(async s => {
    return (await window.__scan.readImage(s)).parsed.complete;
  }, frag);
  await page.waitForTimeout(500);
  out.recorded.afterFragment = await journal();
  await page.route('**/api/journal/ingest',
                   r => r.fulfill({ status: 503, contentType: 'text/plain', body: 'down' }));
  await page.evaluate(async s => {
    window.__shop = (await window.__scan.readImage(s)).parsed;
  }, shop);
  await page.waitForTimeout(500);
  out.recorded.whileDown = await journal();
  out.recorded.queued = await page.evaluate(
    () => JSON.parse(localStorage.getItem('uberscan.unsent.v1') || '[]').length);
  // ...and the driver is told. One more read of the SAME card, which records
  // nothing — the ninety-second window makes it the same offer — purely to
  // get a render out of the page, because the status line is written per read
  // and the flush above had not answered yet when the last one ran.
  await page.evaluate(async s => { await window.__scan.readImage(s); }, shop);
  out.recorded.downStatus = await page.evaluate(
    () => document.getElementById('statusline').textContent);
  await page.unroute('**/api/journal/ingest');
  await page.evaluate(async s => { await window.__scan.readImage(s); }, whole);
  await page.waitForTimeout(600);
  out.recorded.afterBack = await journal();
  out.recorded.queuedAfter = await page.evaluate(
    () => JSON.parse(localStorage.getItem('uberscan.unsent.v1') || '[]').length);
  // ...and the line goes quiet again, which matters as much as its appearing:
  // a warning that stays up after the thing it warns about is over is a
  // warning nobody reads the next time. A duplicate read again, for a render
  // that happens after the flush above has actually answered.
  await page.evaluate(async s => { await window.__scan.readImage(s); }, whole);
  out.recorded.backStatus = await page.evaluate(
    () => document.getElementById('statusline').textContent);
  // The same payout after the window has passed is an offer of its own.
  await page.evaluate(async s => {
    window.__scan.ageRecord(91000);
    await window.__scan.readImage(s);
  }, whole);
  await page.waitForTimeout(500);
  out.recorded.afterAged = await journal();

  // The loop's own path: the frames agree on the shop order and lock, three
  // frames read nothing and the lock is dropped, the frames agree again. One
  // card, one row — and the sighting in between is what keeps the ninety
  // seconds running from the last sight of the card rather than from the row.
  out.relock = await page.evaluate(() => {
    const card = window.__shop;
    const nothing = OfferParser.parse('');
    const states = [];
    states.push(window.__scan.consider(card).locked, window.__scan.consider(card).locked);
    window.__scan.ageRecord(60000);
    states.push(window.__scan.consider(card).locked);
    window.__scan.ageRecord(60000);
    for (let i = 0; i < 3; i++) states.push(window.__scan.consider(nothing).locked);
    states.push(window.__scan.consider(card).locked, window.__scan.consider(card).locked);
    return { complete: card.complete, nothingComplete: nothing.complete, states: states };
  });
  await page.waitForTimeout(600);
  out.recorded.afterRelock = await journal();

  // A fragment of the card is a sight of it too, when it reads as complete.
  // The fragment is the ride card's, so the ride card first, as a new offer
  // after the window; then sixty seconds, the fragment, sixty more, the card.
  await page.evaluate(async s => {
    window.__scan.ageRecord(91000);
    await window.__scan.readImage(s);
  }, whole);
  await page.evaluate(async s => {
    window.__scan.ageRecord(60000);
    await window.__scan.readImage(s);
  }, frag);
  await page.evaluate(async s => {
    window.__scan.ageRecord(60000);
    await window.__scan.readImage(s);
  }, whole);
  await page.waitForTimeout(500);
  out.recorded.afterFragmentSight = await journal();

  // A whole card off a photo is a lock and goes to the journal. The last
  // card recorded above is the ride card, so the shop order is a new one.
  await page.setInputFiles('#photo', path.join(dir, cards[1].file));
  await page.waitForFunction(() => !/reading photo/.test(document.getElementById('statusline').textContent),
                             null, { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(600);
  out.recorded.afterPhoto = await journal();

  // Two readings of ONE delivery card that disagree about the deadline and the
  // item count. The lock signature was pay|minutes|miles, and on a delivery
  // card `minutes` is null — the duration comes from the deadline and the
  // shopping allowance from the item count — so these two agreed perfectly and
  // locked, which is acting on a glitch with the ceremony of acting on a
  // number.
  out.disagree = await page.evaluate(() => {
    var CARD = 'Uber Eats $18.77 6 items Deliver by 7:15 PM 3.6 mi Pickup '
             + "McDonald's";
    // Differs on the DEADLINE ONLY — same pay, same items, same distance — so
    // a signature that added the item count and stopped there would still let
    // this pair lock. The deadline is the denominator on these cards.
    var LATER = 'Uber Eats $18.77 6 items Deliver by 9:15 PM 3.6 mi Pickup '
              + "McDonald's";
    // ...and this one on the ITEM COUNT only, which is the shopping allowance.
    var MORE = 'Uber Eats $18.77 8 items Deliver by 7:15 PM 3.6 mi Pickup '
             + "McDonald's";
    var a = OfferParser.parse(CARD), b = OfferParser.parse(LATER);
    // Cleared the way the page itself clears: three reads that see nothing
    // drop the lock and the running agreement. There is no back door for it,
    // which is the right shape — a test reaching past the loop would not be
    // testing the loop.
    var blank = OfferParser.parse('');
    var clear = function () {
      for (var i = 0; i < 4; i++) window.__scan.consider(blank);
    };
    clear();
    var lockedOnDisagreement = window.__scan.consider(a).locked
                            || window.__scan.consider(OfferParser.parse(LATER)).locked;
    clear();
    var lockedOnItems = window.__scan.consider(OfferParser.parse(CARD)).locked
                     || window.__scan.consider(OfferParser.parse(MORE)).locked;
    // ...and the same card twice must still lock, or this would be a rule
    // that simply refuses everything.
    clear();
    window.__scan.consider(OfferParser.parse(CARD));
    var lockedOnAgreement = window.__scan.consider(OfferParser.parse(CARD)).locked;
    var s = { target: 25, band: 15, costPerMile: 0.30, nowMinutes: 18 * 60 + 57 };
    return {
      lockedOnDisagreement: lockedOnDisagreement,
      lockedOnItems: lockedOnItems,
      lockedOnAgreement: lockedOnAgreement,
      // How far apart the two verdicts are, so the check can say what was at
      // stake rather than only that something differed.
      rateA: OfferParser.rate(a, s).perHour,
      rateB: OfferParser.rate(b, s).perHour,
      minutesA: a.minutes, deadlineA: a.deliverBy, deadlineB: b.deliverBy
    };
  });
  out.photoStatus = await page.evaluate(() => document.getElementById('statusline').textContent);

  // A one-shot message stands long enough to be read: Reset in the sheet,
  // then a read, and the message is still there.
  await page.click('#btnSettings');
  await page.click('#setResetBox');
  out.holdAt0 = await page.evaluate(() => document.getElementById('statusline').textContent);
  await page.evaluate(async s => { await window.__scan.readImage(s); }, whole);
  out.holdAfterRead = await page.evaluate(() => document.getElementById('statusline').textContent);
  await page.evaluate(() => { document.getElementById('settingsSheet').hidden = true; });

  // A read that never answers: reported as a failed read, the reader thrown
  // away and loaded again, and the next read works.
  out.stall = await page.evaluate(async s => {
    window.__scan.stall(400);
    // Bounded here too: a scanner with no deadline on a read would leave
    // this waiting for ever, which is a hung suite rather than a failed check.
    const got = await Promise.race([window.__scan.readImage(s),
      new Promise(r => setTimeout(() => r({ failed: false, hung: true }), 20000))]);
    const status = document.getElementById('statusline').textContent;
    const t0 = Date.now();
    while (!window.__scan.ready() && Date.now() - t0 < 60000) await new Promise(r => setTimeout(r, 200));
    const again = await window.__scan.readImage(s);
    return { failed: !!got.failed, status: status, restarts: window.__scan.restarts(),
             ready: window.__scan.ready(), pay: again.parsed && again.parsed.pay,
             label: document.getElementById('verdictLabel').textContent.trim() };
  }, whole);

  // Two rows kept a moment apart, the second while the first is in flight:
  // both go, and the one answer names both. Last, because these land in the
  // journal every count above is a difference of.
  out.midflight = await page.evaluate(async () => {
    const parsed = { pay: 9.5, minutes: 20, miles: 5, legs: 2, complete: true };
    const rate = { ready: true, state: 'no', perHour: 28.5, grossPerHour: 30,
                   perMile: 1.9, cost: 1.75, minutes: 20 };
    const settings = { target: 25, band: 15, costPerMile: 0.35 };
    const mk = () => JournalClient.keep(
      JournalClient.row(parsed, rate, settings, { browser: true, prefix: 't' }));
    const a = mk();
    const flight = JournalClient.flush();
    const b = mk();
    const answer = await flight;
    return { ok: answer.ok, sentA: answer.sent.includes(a.id),
             sentB: answer.sent.includes(b.id),
             left: JSON.parse(localStorage.getItem('uberscan.unsent.v1') || '[]').length };
  });

  // The two ends of a queue that has run out of room.
  //
  // It had no ceiling of its own and swallowed every storage failure, so on
  // the owner's own week — 1,166 offers put through row() one at a time, 831
  // bytes each at the mean — it met the browser's 5MB at about 3,100 rows and
  // then lost every further offer in silence: keep() handed the row back, the
  // phone buzzed, and nothing was stored. Driven here at a tenth of the real
  // scale, because the shape is what is being checked and 3,100 rows of
  // JSON.stringify per keep is a minute of the suite for the same answer.
  out.queueFull = await page.evaluate(() => {
    const KEY = 'uberscan.unsent.v1';
    const parsed = { pay: 11.25, minutes: 20, miles: 5, legs: 1, complete: true };
    const rate = { ready: true, state: 'no', perHour: 33.75, grossPerHour: 35,
                   perMile: 2.25, cost: 1.75, minutes: 20 };
    const settings = { target: 25, band: 15, costPerMile: 0.35 };
    const mk = () => JournalClient.keep(
      JournalClient.row(parsed, rate, settings, { browser: true, prefix: 'q' }));
    const stored = () => JSON.parse(localStorage.getItem(KEY) || '[]');

    // Seeded to exactly the ceiling rather than scanned to it. Every row
    // carries an `at`, because what the ceiling sheds and what it says about
    // it are both being checked.
    const cap = JournalClient.QUEUE_CAP;
    // Checked before it is used as a loop bound. A ceiling that is not a
    // countable number is the fault this block is about, and finding it out by
    // seeding rows until the suite times out tells nobody which line to look
    // at — mutating QUEUE_CAP to Infinity did exactly that.
    if (!(typeof cap === 'number' && isFinite(cap) && cap > 0 && cap < 100000)) {
      return { cap: String(cap), capUsable: false };
    }
    const seed = [];
    for (let i = 0; i < cap; i++) seed.push({ id: 's' + i, at: 5000 + i });
    localStorage.setItem(KEY, JSON.stringify(seed));

    const over = mk();
    const afterCap = stored();
    const capTrouble = JournalClient.trouble();

    // A store that refuses outright: private mode, or an origin full of
    // something else. The queue must come through it untouched — the rows
    // already in it are the ones that cannot be rebuilt — and the row in hand
    // must come back as the null it is.
    const real = localStorage.setItem.bind(localStorage);
    let refused, afterRefusal, refusedTrouble;
    try {
      localStorage.setItem = (k, v) => {
        if (k === KEY) { const e = new Error('quota'); e.name = 'QuotaExceededError'; throw e; }
        return real(k, v);
      };
      refused = mk();
      afterRefusal = stored();
      refusedTrouble = JournalClient.trouble();
    } finally {
      localStorage.setItem = real;
    }

    // ...and the store comes back, which it does the moment the queue drains.
    const kept = mk();
    const recovered = JournalClient.trouble();

    localStorage.removeItem(KEY);
    return {
      cap: cap,
      capUsable: true,
      keptAfterRecovery: !!kept,
      keptOverCap: !!over,
      heldAtCap: afterCap.length,
      oldestKept: afterCap[0] && afterCap[0].at,
      dropped: capTrouble && capTrouble.dropped,
      through: capTrouble && capTrouble.through,
      refusedIsNull: refused === null,
      heldAfterRefusal: afterRefusal.length,
      lost: refusedTrouble && refusedTrouble.lost,
      // A full store is not a permanent condition: the rig answers, the
      // flush drains the queue, and the next row lands. So the PRESENT-tense
      // warning has to clear while the count of what was lost does not.
      refusingWhileRefused: !!(refusedTrouble && refusedTrouble.refusing),
      refusingAfterRecovery: !!(recovered && recovered.refusing),
      lostAfterRecovery: recovered && recovered.lost,
      droppedUnchanged: refusedTrouble && capTrouble
                        && refusedTrouble.dropped === capTrouble.dropped
    };
  });

  // The status line once rows have been lost AND the rig is out of reach,
  // which is the state a long outage actually produces: the ceiling only bites
  // after the rig has been away long enough to fill a thousand-row queue.
  //
  // The three clauses were early returns in that order, so the permanent loss
  // hid the live backlog for the rest of the page's life — and the backlog is
  // the only one of the three a driver can act on. The dropped line also ended
  // "the queue is full, find the rig", which stays on the glass after the rig
  // answers and the queue drains, because trouble() never clears.
  //
  // Driven through the page's own render, not a hook: `consider` is the loop's
  // own path and the status line is what the driver reads.
  await page.route('**/api/journal/ingest',
                   r => r.fulfill({ status: 503, contentType: 'text/plain', body: 'down' }));
  out.lossAndBacklog = await page.evaluate(async (src) => {
    // The rig unreachable, the honest way: a flush that the stub refuses.
    // reachable() is module state in journal-client and there is no back door
    // to it, which is the point — this is the same call the page makes.
    JournalClient.keep(JournalClient.row(
      { pay: 41.11, minutes: 20, miles: 5, legs: 2, complete: true },
      { ready: true, state: 'no', perHour: 123.3, grossPerHour: 125,
        perMile: 8.2, cost: 1.75, minutes: 20 },
      { target: 25, band: 15, costPerMile: 0.35 },
      { browser: true, prefix: 'lb' }));
    await JournalClient.flush();
    // A read is what renders the status line — `consider` is the loop's
    // agreement path and deliberately does not paint. This is the page's own
    // render, not a hook that writes the line directly.
    // status() gives a one-shot message a 2500ms hold and suppresses the
    // routine line for that long — an earlier block in this probe fails a read
    // on purpose, and its message was still holding the line here. Waited out
    // BEFORE the render, because a render during the hold paints nothing and
    // the line then reads as this block's answer when it is the last block's.
    await new Promise(r => setTimeout(r, 2700));
    await window.__scan.readImage(src);
    return { line: document.getElementById('statusline').textContent,
             trouble: JSON.stringify(JournalClient.trouble()),
             reachable: JournalClient.reachable(),
             waiting: JournalClient.waiting() };
  }, whole);
  await page.unroute('**/api/journal/ingest');

  // A rate that is only a ceiling, on the screen that had nothing to say
  // about it. rate() caps the verdict at CLOSE CALL when a cost per mile is
  // set and the card states no chargeable distance — and live.html and the
  // offers page both name it in words. This one showed "/hr" like any other
  // number, so the only clue was an amber verdict on a card whose printed rate
  // clears the target, which reads as the rig being cautious rather than as
  // the figure being an upper bound.
  out.ceiling = await page.evaluate(() => {
    var card = "Uber Eats $18.77 Includes expected tip 25 min total Pickup "
             + "McDonald's Deliver to Customer";
    var settings = { target: 25, band: 15, costPerMile: 0.35 };
    var parsed = OfferParser.parse(card);
    var rate = OfferParser.rate(parsed, settings);
    // Driven through the page's own path rather than a back door: two frames
    // agree so the card locks and becomes `lastResult`, then setting the cost
    // per mile re-renders from it. A hook that painted the screen directly
    // would be testing the hook.
    var blank = OfferParser.parse('');
    for (var i = 0; i < 4; i++) window.__scan.consider(blank);
    window.__scan.consider(parsed);
    window.__scan.consider(parsed);
    var cost = document.getElementById('setCost');
    cost.value = '0.35';
    cost.dispatchEvent(new Event('input', { bubbles: true }));
    var warn = document.getElementById('warn');
    return { uncosted: !!rate.uncosted, state: rate.state,
             perHour: rate.perHour,
             warn: (warn.textContent || '').replace(/\s+/g, ' ').trim(),
             warnShown: !warn.hidden,
             headline: (document.getElementById('perHour') || {}).textContent || '' };
  });

  // The three figures under the headline, on a card whose distance rate() had
  // to repair. The deadline is built from the browser's own clock so the card
  // states the same eighteen minutes whenever this runs.
  out.decimal = await page.evaluate(() => {
    var due = new Date(Date.now() + 18 * 60000);
    var h = due.getHours(), m = due.getMinutes();
    var stamp = ((h % 12) || 12) + ':' + (m < 10 ? '0' : '') + m
              + ' ' + (h < 12 ? 'AM' : 'PM');
    var card = "Decline High paying offer! Your Platinum status gave you "
             + "priority for this offer. $41.11 Guaranteed (incl. tips) 98 mi "
             + "Deliver by " + stamp + " Pickup Papa John's Store 3317 "
             + "(2 orders) Customer dropoff";
    var parsed = OfferParser.parse(card);
    var blank = OfferParser.parse('');
    for (var i = 0; i < 4; i++) window.__scan.consider(blank);
    window.__scan.consider(parsed);
    window.__scan.consider(parsed);
    // The same nudge the ceiling case uses: a settings change re-renders from
    // `lastResult`, so the screen being read back is the page's own render of
    // this card rather than a hook that painted it.
    var cost = document.getElementById('setCost');
    cost.value = '0.30';
    cost.dispatchEvent(new Event('input', { bubbles: true }));
    var txt = function (id) {
      return (document.getElementById(id).textContent || '').trim();
    };
    return { parsedMiles: parsed.miles, checked: parsed.milesChecked,
             pay: txt('vPay'), min: txt('vMin'), mile: txt('vMile'),
             warn: (document.getElementById('warn').textContent || '')
                     .replace(/\s+/g, ' ').trim(),
             headline: txt('perHour') };
  });

  // The note on the glass says which mode the box is actually in, after the
  // checkbox that decides it has been flipped.
  out.boxNote = await page.evaluate(() => {
    var note = function () {
      var n = document.getElementById('adjustNote');
      return { text: (n.textContent || '').replace(/\s+/g, ' ').trim(),
               shown: !n.hidden };
    };
    var setFull = function (on) {
      var f = document.getElementById('setFullFrame');
      f.checked = on;
      f.dispatchEvent(new Event('change', { bubbles: true }));
    };
    var btn = document.getElementById('btnBox');
    var adjusting = function () {
      return document.body.classList.contains('adjusting');
    };
    setFull(false);
    if (!adjusting()) btn.click();          // into adjust mode, box in use
    var boxMode = note();
    setFull(true);                          // ...the box stops being read
    var afterTick = note();
    setFull(false);                         // ...and starts again
    var afterUntick = note();
    var stillAdjusting = adjusting();
    var labelWhileOn = btn.textContent.trim();
    btn.click();                            // out of adjust mode
    // Flipping the checkbox outside adjust mode must not switch the note on.
    setFull(true);
    var idleShown = note().shown;
    var idleLabel = btn.textContent.trim();
    setFull(false);
    return { boxMode: boxMode, afterTick: afterTick, afterUntick: afterUntick,
             stillAdjusting: stillAdjusting, labelWhileOn: labelWhileOn,
             idleShown: idleShown, idleLabel: idleLabel };
  });

  // What the phone stores in the journal's `text` column, against what the rig
  // stores in the same column of the same file.
  out.rowText = await page.evaluate(() => {
    var card = '$8.83\n23 min (4.6 mi) total\nPickup\nPapa Johns (Kennesaw)\n'
             + 'Cobb Pkwy NW, Acworth';
    var settings = { target: 25, band: 15, costPerMile: 0.30 };
    var parsed = OfferParser.parse(card);
    var rate = OfferParser.rate(parsed, settings);
    var row = JournalClient.row(parsed, rate, settings,
                                { browser: true, prefix: 'q' });
    // A frame whose crop took in the screen behind the card: the case the cap
    // is for, and the one where an uncapped column ran to two thousand chars.
    var spill = OfferParser.parse(card + ' '
                                  + 'Uber Eats Home Account Earnings '.repeat(80));
    var spillRow = JournalClient.row(
      spill, OfferParser.rate(spill, settings), settings,
      { browser: true, prefix: 'q' });
    // The keypad hands row() a bare {pay, minutes, miles} with no text at all.
    var typed = JournalClient.row({ pay: 10, minutes: 20, miles: 5 },
                                  { perHour: 30, state: 'go' }, settings,
                                  { browser: true, prefix: 'k' });
    // Re-parsing what is stored must give back what was parsed, or the stored
    // form is lossy in a way that matters.
    var back = OfferParser.parse(row.text);
    return {
      newlines: (row.text.match(/\n/g) || []).length,
      rawNewlines: (parsed.rawText.match(/\n/g) || []).length,
      flatNewlines: (parsed.text.match(/\n/g) || []).length,
      reparsePay: back.pay, reparseMiles: back.miles, parsedPay: parsed.pay,
      spillRead: spill.rawText.length, spillStored: spillRow.text.length,
      typedText: typed.text === undefined ? 'undefined' : String(typed.text),
      hasCardMinutes: 'cardMinutes' in row,
      rowMinutes: row.minutes,
    };
  });

  // A settings box being retyped is not a request for the default.
  //
  // Driven through the page's own input handler and read back off the STORED
  // object, because the fault is that the substituted value was saved: a driver
  // interrupted mid-backspace went back to driving against a line they never
  // chose, and it was still there for the next card.
  out.blankBox = await page.evaluate(() => {
    var parsed = OfferParser.parse('$12.40 24 min (6.6 mi) trip');
    var blank = OfferParser.parse('');
    for (var i = 0; i < 4; i++) window.__scan.consider(blank);
    window.__scan.consider(parsed);
    window.__scan.consider(parsed);
    var stored = function () {
      return JSON.parse(localStorage.getItem('uberscan.settings.v1') || '{}');
    };
    var type = function (id, v) {
      var f = document.getElementById(id);
      f.value = v;
      f.dispatchEvent(new Event('input', { bubbles: true }));
    };
    // The verdict WORD, without the trailing "?" the label adds while the card
    // is not locked. Whether this fixture locks is not what is being measured
    // here and pinning it would make the check fragile about something else.
    var label = function () {
      return (document.getElementById('verdictLabel').textContent || '')
        .replace(/\s*\?$/, '').trim();
    };
    type('setCost', '0.33');
    type('setTarget', '40');
    var chosen = { target: stored().target, label: label() };
    type('setTarget', '');
    var blanked = { target: stored().target, label: label() };
    // ...and leaving the box puts the number actually in force back into it,
    // so the screen and the store cannot disagree about what the line is.
    var f = document.getElementById('setTarget');
    f.dispatchEvent(new Event('change', { bubbles: true }));
    var shown = f.value;
    // A real number still lands, or the guard would have turned the box off.
    type('setTarget', '25');
    var retyped = { target: stored().target, label: label() };
    // The quieter half: a blanked COST box dropped the deduction entirely.
    type('setCost', '');
    var costBlank = stored().costPerMile;
    return { chosen: chosen, blanked: blanked, shown: shown,
             retyped: retyped, costBlank: costBlank };
  });

  // The row the phone writes, built from the REAL parser and the REAL verdict
  // rather than from a literal beside it.
  //
  // That distinction is the check. The fixture above hands row() a hand-written
  // `rate`, and a hand-written rate cannot notice that row() was reading the
  // wrong object: it took minutes and miles off the PARSE, where
  // rpi/journal.py takes both off the verdict and says why. On this card —
  // $41.11, "98 mi", "Deliver by 7:15 PM", read at 18:57 — the two disagree
  // completely, because the duration comes from the deadline and the distance
  // has had a lost decimal put back.
  out.rowAgrees = await page.evaluate(() => {
    var card = 'Decline High paying offer! $41.11 Guaranteed (incl. tips) '
             + '98 mi Deliver by 7:15 PM Pickup Papa Johns';
    var settings = { target: 25, band: 15, costPerMile: 0.30,
                     nowMinutes: 18 * 60 + 57 };
    var parsed = OfferParser.parse(card);
    var rate = OfferParser.rate(parsed, settings);
    var row = JournalClient.row(parsed, rate, settings,
                                { browser: true, prefix: 'q' });
    return {
      shownRate: rate.perHour, shownMinutes: rate.cardMinutes,
      shownMiles: rate.miles, shownCorrected: !!rate.milesCorrected,
      rowMinutes: row.minutes, rowMiles: row.miles,
      rowCorrected: row.milesCorrected, rowFromDeadline: row.fromDeadline,
      rowPay: row.pay, rowGross: row.grossPerHour,
      // What the parse alone would have given, so the check can say the two
      // really are different and is not passing by coincidence.
      parsedMinutes: parsed.minutes, parsedMiles: parsed.miles,
      // Which end is which. The Pi's rows carry these and the browser's did
      // not, so every offer read on the PHONE was invisible to both map
      // surfaces — each of which filters on exactly these two fields — with
      // the places sitting in the row all along.
      rowPickup: row.pickup, rowDropoff: row.dropoff,
      parsedPickup: parsed.pickup, parsedDropoff: parsed.dropoff
    };
  });

  // ...on a card that names both ends, since the one above names none.
  out.rowEnds = await page.evaluate(() => {
    var settings = { target: 25, band: 15, costPerMile: 0.30 };
    var parsed = OfferParser.parse(
      '$8.83\n23 min (4.6 mi) total\nPickup\nPapa Johns (Kennesaw)\n'
      + 'Cobb Pkwy NW, Acworth');
    var rate = OfferParser.rate(parsed, settings);
    var row = JournalClient.row(parsed, rate, settings,
                                { browser: true, prefix: 'e' });
    return { pickup: row.pickup, dropoff: row.dropoff,
             places: row.places || [],
             parsedPickup: parsed.pickup, parsedDropoff: parsed.dropoff };
  });

  // The same figures, to the same number of places the Pi writes them to.
  out.rowRounds = await page.evaluate(() => {
    var build = function (settings, card) {
      var parsed = OfferParser.parse(card);
      var rate = OfferParser.rate(parsed, settings);
      return { row: JournalClient.row(parsed, rate, settings,
                                      { browser: true, prefix: 'r' }),
               rate: rate };
    };
    var plain = build({ target: 25, band: 15, costPerMile: 0.30 },
      'Delivery\n$8.83\n23 min (4.6 mi) total\nPickup\nMcDonalds\nCustomer dropoff');
    // A shopping allowance makes the billed minutes fractional - 7 items at 25
    // seconds is 25.9166... - which is the only way the one-decimal field can
    // tell a rounded figure from an unrounded one. With a whole 23 in it, every
    // version of this passes.
    var padded = build({ target: 25, band: 15, costPerMile: 0.30,
                         secondsPerItem: 25, pad: 0 },
      'Delivery\n$8.83\n23 min (4.6 mi) total\nDeliver by 7:15 PM\n'
      + 'Cherry Cricket\n7 items 4.6 mi\nPickup\nMcDonalds');
    // ...and a card with no distance, where the verdict has no per-mile at all.
    var nodist = build({ target: 25, band: 15, costPerMile: 0.30 },
      'Delivery\n$9.17\nDeliver by 7:15 PM\nPickup\nWendys\nCustomer dropoff');
    return { perHour: plain.row.perHour, grossPerHour: plain.row.grossPerHour,
             perMile: plain.row.perMile, cost: plain.row.cost,
             billedMinutes: plain.row.billedMinutes,
             // The verdict's own figures, unrounded, so the checks can prove
             // the row is not copying something that was already short.
             rawPerHour: plain.rate.perHour,
             padMinutes: padded.row.billedMinutes,
             rawPadMinutes: padded.rate.minutes,
             // Reported as a WORD, not as the value. A missing figure comes
             // back from the verdict as `undefined`, and rounding it
             // arithmetically gives NaN - which JSON turns into `null` on the
             // way out of the browser. So a check comparing the serialized
             // value to None passed over a row carrying NaN, and the guard that
             // prevents it looked like dead weight. The type is the only way to
             // tell the two apart from here.
             nullPerMile: String(nodist.row.perMile),
             nullPerMileIsNumber: typeof nodist.row.perMile === 'number',
             rawNullPerMile: String(nodist.rate.perMile) };
  });

  // Registered by this page on its own: a phone that only ever opened
  // /scan.html had nothing cached and got a browser error in a garage.
  out.swAuto = await page.evaluate(async () => (await navigator.serviceWorker.getRegistrations()).length);

  // ...and the same asked of the PANEL, in the one browser profile that has
  // nobody else to register for it.
  //
  // sw.js lists live.html in ASSETS and that file's comments treat the panel as
  // part of the offline shell — it is the screen bolted to the car, it must
  // come up with no network, and that is the stated reason it does not load
  // advice.js for one integer. It never registered the worker. The only three
  // registrations in the repo were scan.js, ui.js and journal.html, so the
  // panel was covered only when that same profile had already opened one of
  // them, and then only because sw.js claims clients at scope '/'.
  //
  // A CONTEXT OF ITS OWN, opening nothing else. On the Pi the gap is usually
  // masked, because index.html is where the driver lands and ui.js registers
  // there; the profile that matters is a browser pointed straight at
  // /live.html and at nothing before it, which is the dashboard panel and the
  // 480x320 hat. Sharing this page's context would have tested the mask.
  out.panelSw = await (async () => {
    const ctx3 = await browser.newContext({ viewport: { width: 800, height: 480 } });
    const p3 = await ctx3.newPage();
    // `domcontentloaded`, not `load`: this page holds an open MJPEG stream, so
    // the load event never fires on it. That is not incidental to the check —
    // it is the reason the registration cannot be hung off `load` the way the
    // keypad and the phone scanner hang theirs.
    await p3.goto(base + '/live.html', { waitUntil: 'domcontentloaded' })
            .catch(() => {});
    await p3.waitForFunction(
      async () => (await navigator.serviceWorker.getRegistrations()).length > 0,
      null, { timeout: 10000 }).catch(() => {});
    const n = await p3.evaluate(async () =>
      (await navigator.serviceWorker.getRegistrations()).length);
    await ctx3.close();
    return n;
  })();

  // The reader failing to load, as a language file that never arrives would
  // have it: the deadline passes with no reader.
  out.engineDown = await (async () => {
    const ctx2 = await browser.newContext({ viewport: { width: 420, height: 900 } });
    const p2 = await ctx2.newPage();
    // A deadline the load cannot meet stands in for the language file that
    // never arrives: the reader's own fetches happen inside its worker,
    // where a route on the page or the context does not reach them.
    await p2.goto(base + '/scan.html?engineDeadline=1', { waitUntil: 'domcontentloaded' });
    await p2.waitForFunction(() => /failed to load/.test(document.getElementById('statusline').textContent),
                             null, { timeout: 20000 }).catch(() => {});
    const status = await p2.evaluate(() => document.getElementById('statusline').textContent);
    const failed = await p2.evaluate(() => window.__scan && window.__scan.engineFailed());
    await p2.setInputFiles('#photo', path.join(dir, cards[0].file));
    await p2.waitForTimeout(300);
    const photo = await p2.evaluate(() => document.getElementById('statusline').textContent);
    await ctx2.close();
    return { status: status, failed: failed, photo: photo };
  })();

  // The offline cache: which caches exist, and does the app shell refresh.
  out.sw = await page.evaluate(async () => {
    const reg = await navigator.serviceWorker.register('/sw.js');
    await navigator.serviceWorker.ready;

    /* Wait to be *controlled*, not merely for a worker to exist.
     *
     * `ready` resolves once the scope has an active registration. It says
     * nothing about this page: a page loaded before the worker registered
     * starts life uncontrolled, and a fetch from an uncontrolled page goes
     * straight to the network without the worker ever seeing it. sw.js calls
     * clients.claim() in activate, which fixes that — asynchronously, some
     * milliseconds later.
     *
     * So the vendor fetch below was racing the claim. Win the race and the
     * engine is cached; lose it and the file is fetched, nothing is stored,
     * and no amount of waiting afterwards produces the entry. That is what was
     * happening: green on an idle machine, red inside a full run, twice.
     */
    for (let i = 0; i < 100 && !navigator.serviceWorker.controller; i++) {
      await new Promise(r => setTimeout(r, 100));
    }
    const controlled = !!navigator.serviceWorker.controller;

    /* ...and ask again rather than once. Even controlled, the worker hands the
     * response back before it finishes putting a copy in the cache, so there
     * is a moment when the engine cache exists and is empty. Re-fetching is
     * free — the second one is served from the cache the first one filled. */
    let keys = [], held = {};
    for (let i = 0; i < 100; i++) {
      try { await fetch('vendor/lang/eng.traineddata.gz'); } catch (e) {}
      keys = await caches.keys();
      held = {};
      for (const k of keys) {
        const c = await caches.open(k);
        held[k] = (await c.keys()).map(r => new URL(r.url).pathname);
      }
      const engine = Object.keys(held).some(k =>
        held[k].some(p => p.indexOf('/vendor/') !== -1));
      if (engine) break;
      await new Promise(r => setTimeout(r, 100));
    }
    return { keys: keys, scope: reg.scope, held: held, controlled: controlled };
  });

  /* --- the box a driver drags, pulled all the way in -----------------------
   *
   * The one control on this page that overrides the reader, and it discarded
   * the drag on most of its handles. The resize clamp lands on exactly
   * `x1 - MIN_BOX`, and `x1 - (x1 - MIN_BOX)` in binary floating point is
   * 0.07999999999999996 against a floor of 0.08 — so validBox() returned null
   * on release and the whole box reverted to the CSS default.
   *
   * Silently, and only on release: applyBox() runs on every move with the
   * unvalidated value, so the box follows the finger the whole way in and then
   * snaps back. That reads as the page ignoring the driver.
   *
   * Driven as a thumb drives it: press a handle, drag far past the minimum,
   * lift. Every handle, at three sizes, because the numbers that produce the
   * error come off the element's own rectangle and that changes with the
   * panel.
   */
  {
    const HANDLES = [
      ['top-left', 0.02, 0.02, 1, 1], ['top-right', 0.98, 0.02, -1, 1],
      ['bottom-left', 0.02, 0.98, 1, -1], ['bottom-right', 0.98, 0.98, -1, -1],
      ['left edge', 0.02, 0.5, 1, 0], ['right edge', 0.98, 0.5, -1, 0],
      ['top edge', 0.5, 0.02, 0, 1], ['bottom edge', 0.5, 0.98, 0, -1],
    ];
    out.drags = {};
    for (const [w, h] of [[800, 480], [1024, 600], [390, 844]]) {
      const ctx2 = await browser.newContext({ viewport: { width: w, height: h } });
      const page2 = await ctx2.newPage();
      for (const [name, fx, fy, ix, iy] of HANDLES) {
        await page2.goto(base + '/scan.html', { waitUntil: 'domcontentloaded' });
        await page2.evaluate(() => localStorage.removeItem('uberscan.settings.v1'));
        await page2.reload({ waitUntil: 'domcontentloaded' });
        await page2.waitForTimeout(400);
        // The box is only draggable in adjust mode, and only when the whole
        // frame is not being read.
        await page2.click('#btnBox').catch(() => {});
        await page2.waitForTimeout(120);
        // Who answers a press at that handle, before pressing it.
        //
        // The drag below fails either way if something is in front of the box,
        // and that failure looks identical to arithmetic getting it wrong. So
        // ask separately: this is the question the fix is about, and the fix
        // for one is not the fix for the other.
        out.covering = out.covering || {};
        out.covering[w + 'x' + h + ' ' + name] = await page2.evaluate(([fx, fy]) => {
          const el = document.getElementById('reticle');
          const b = el.getBoundingClientRect();
          const t = document.elementFromPoint(b.x + b.width * fx, b.y + b.height * fy);
          if (!t) return 'nothing';
          // The box itself, or one of its own corner marks, is the right
          // answer. Anything else is something drawn over the control.
          return (t === el || el.contains(t)) ? 'the box'
            : (t.id || t.className || t.tagName);
        }, [fx, fy]);
        const r = await page2.evaluate(() => {
          const b = document.getElementById('reticle').getBoundingClientRect();
          return { x: b.x, y: b.y, w: b.width, h: b.height };
        });
        const from = { x: r.x + r.w * fx, y: r.y + r.h * fy };
        // Far past the floor in both axes, which is what pulling a corner
        // until it stops moving does.
        const to = { x: from.x + ix * r.w * 0.9, y: from.y + iy * r.h * 0.9 };
        await page2.mouse.move(from.x, from.y);
        await page2.mouse.down();
        await page2.mouse.move(from.x + (to.x - from.x) / 2,
                               from.y + (to.y - from.y) / 2, { steps: 4 });
        await page2.mouse.move(to.x, to.y, { steps: 4 });
        await page2.mouse.up();
        await page2.waitForTimeout(150);
        out.drags[w + 'x' + h + ' ' + name] = await page2.evaluate(() => {
          let stored = null;
          try { stored = (JSON.parse(localStorage.getItem('uberscan.settings.v1'))
                          || {}).box; } catch (e) {}
          const el = document.getElementById('reticle');
          return { stored: stored,
                   // What the element is actually showing. A discarded box
                   // leaves the inline styles cleared and the CSS default back.
                   inline: el.style.width || null };
        });
      }
      await page2.close();
      await ctx2.close();
    }
  }

  await browser.close();
  console.log(JSON.stringify(out));
})().catch(e => { console.log(JSON.stringify({ skip: 'browser: ' + e.message })); });
'''

# Sizes a reticle on a phone actually produces, plus the ends of the range.
FIT_CASES = [[540, 680], [720, 905], [1080, 1358], [1620, 2037],
             [400, 300], [2000, 2500], [100, 90]]

work = tempfile.mkdtemp()
proc = None
try:
    manifest = []
    for name, make, pay in CARDS:
        screen = make()
        card = screen[int(screen.shape[0] * 0.42):, :]
        fname = name.replace(' ', '-') + '.png'
        cv2.imwrite(os.path.join(work, fname), card)
        manifest.append({'name': name, 'file': fname})
    # Half a card: one leg, which always reads better than the offer is.
    frag = TC.uberx_screen()
    frag = frag[int(frag.shape[0] * 0.42):int(frag.shape[0] * 0.72), :]
    cv2.imwrite(os.path.join(work, 'fragment.png'), frag)
    with open(os.path.join(work, 'cards.json'), 'w') as fh:
        json.dump(manifest, fh)
    driver = os.path.join(work, 'drive.js')
    with open(driver, 'w') as fh:
        fh.write(DRIVER)

    port = free_port()
    proc = subprocess.Popen(
        ['node', os.path.join(ROOT, 'server.js')],
        env=dict(env, PORT=str(port), SCANNER='0',
                 JOURNAL=os.path.join(work, 'j.jsonl')),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = 'http://127.0.0.1:%d' % port
    import urllib.request
    for _ in range(120):
        try:
            urllib.request.urlopen(base + '/api/status', timeout=1).read()
            break
        except Exception:
            time.sleep(0.1)
    else:
        raise RuntimeError('the server never came up')

    exes = [p for p in (
        os.environ.get('PLAYWRIGHT_CHROMIUM'),
        '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
    ) if p and os.path.exists(p)]
    run = subprocess.run(
        ['node', driver, base, work],
        env=dict(env, PW_EXES=json.dumps(exes), FIT_CASES=json.dumps(FIT_CASES)),
        capture_output=True, timeout=600)
    tail = (run.stdout or b'').decode('utf-8', 'replace').strip().splitlines()
    if not tail:
        skip('the browser produced nothing (%s)'
             % (run.stderr or b'').decode('utf-8', 'replace').strip()[-160:])
    got = json.loads(tail[-1])
    if got.get('skip'):
        skip(got['skip'])

    # --- every card shape reads, or says nothing ---------------------------
    for name, make, pay in CARDS:
        r = got['reads'][name]
        ok_('%s: right, or says nothing — never something else' % name,
            (not r['ready']) or r['pay'] == pay)

    # --- and the payout is actually read -----------------------------------
    # The property above was true throughout the bug: a shop order with no
    # payout is not `ready`, so "right or silent" held while the phone app was
    # useless on a whole card shape. Silence is only acceptable when the picture
    # is bad, and these are clean renders.
    for name, make, pay in CARDS:
        eq('%s: the payout is read from a clean card' % name,
           got['reads'][name]['pay'], pay)

    shop = got['reads']['a shop order']
    eq('...including a shop order, which is the one that was lost', shop['pay'], 7.09)
    eq('...with its journey', shop['minutes'], 34)
    eq('...and its distance', shop['miles'], 3.6)
    ok_('...and a rate on the screen', shop['shown'].startswith('$'))

    # ...with the raw figure beside it, where the two differ.
    #
    # The headline is net and is labelled "/hr" whether a mileage cost came off
    # it or not, so this page and the rig's showed numbers that are only
    # sometimes the same thing with nothing on either saying which. A shop order
    # over 3.6 miles has a cost, so the two figures differ and both belong on
    # screen; where they do not differ, printing one twice beside itself is
    # noise next to the one number that decides an offer.
    ok_('...and the raw rate beside it', shop['rawShown'])
    ok_('...labelled as the raw one', shop['raw'].endswith('raw'))
    ok_('...and it is the bigger of the two, being before costs',
        shop['gross'] is not None and shop['gross'] > shop['perHour'])
    for name, make, pay in CARDS:
        r = got['reads'][name]
        if not r['ready'] or r['gross'] is None:
            continue
        # There is no raw figure beside a headline that is not a figure. The
        # page withholds the rate entirely when it doubts it, and a lone
        # "$2.5 raw" under a "--" would be the withheld number printed anyway.
        #
        # Keyed off what is on the screen rather than off the state name behind
        # it, because this check began as a restatement of the page's rule that
        # dropped one of its clauses — and a second copy of a rule that has
        # drifted is the fault this project keeps finding. It only surfaced at
        # certain hours: the delivery fixture says "Deliver by 7:15 PM" and is
        # judged against the clock, so read in the small hours its deadline is
        # sixteen hours out, the rate comes to $2.33/hr, and the page doubts it.
        # Read at noon the same card is judged and the check passed.
        judged = r['shown'] != '--'
        same = round(r['gross']) == round(r['perHour'])
        eq('%s: the raw rate is shown exactly when it differs' % name,
           bool(r['rawShown']), judged and not same)

    # ...and with no running cost set, where there is nothing to take off and
    # the two rates are one number.
    free = got.get('free') or {}
    checked = 0
    for name, make, pay in CARDS:
        r = free.get(name) or {}
        if not r.get('ready') or r.get('gross') is None:
            continue
        checked += 1
        eq('%s: net and raw are one number with no cost set' % name,
           round(r['gross']), round(r['perHour']))
        ok_('%s: ...so it is not printed twice' % name, not r['rawShown'])
    ok_('the no-cost pass actually read something', checked > 0)

    # --- a delivery card is judged against the clock, or not at all --------
    # The container's clock makes the deadline hours away, which is exactly the
    # case the doubt guard is for: a number is refused rather than shown.
    delivery = got['reads']['a delivery card']
    ok_('a deadline the clock cannot make sense of is refused, not shown',
        delivery['state'] != 'doubt' or delivery['shown'] == '--')

    # --- half a card says so, in words -------------------------------------
    # A single leg is the same pay over less time, so it always reads *better*
    # than the offer is — "$16.00 3 min away" is a confident green $320/hr for
    # a card whose truth is $35.30. doubt() cannot see it (3 minutes and $16 are
    # both ordinary) and the distance is not uncertain, so the only thing that
    # can argue with the number is a sentence saying the journey is not all
    # there. live.html has had one for a while; this page had the "?" on the
    # word and nothing on the figure, which is the wrong half to hedge.
    frag = got['fragment']
    if frag['ready']:
        ok_('half a card is called out on the phone too', frag['warned'])
        ok_('...in the same words as the driving screen',
            'may not be all there' in frag['warning'])
        ok_('...while the label hedges as well', frag['label'].endswith('?'))
    else:
        ok_('half a card shows no rate at all', frag['shown'] == '--')

    # --- a reader that throws does not leave the last verdict standing ------
    # On a throw neither consider() nor render() ran, so every number on the
    # screen kept its previous value. An engine that throws every cycle — a
    # phone that has run its worker out of memory — therefore held a green
    # ACCEPT and a dollar figure from an offer that was already gone, admitted
    # to only by the status line.
    thrown = got['afterThrow']
    eq('a run of failed reads clears the rate', thrown['after'], '--')
    ok_('...and the verdict with it',
        thrown['label'] in ('POINT AT THE OFFER', 'READ AGAIN'))

    # --- a locked card reaches the journal ----------------------------------
    #
    # This page read a card, showed a verdict, and forgot it — the same hole
    # the keypad had, on the other screen a driver reaches for when the rig
    # cannot read. Driven through the real server, and read back as the
    # offers page will see it.
    rec = got.get('recorded') or {}
    before = len(rec.get('before') or [])
    eq('a locked card writes one row to the journal',
       len(rec.get('afterWhole') or []) - before, 1)
    # The row this read wrote, by difference: the cards read earlier in this
    # driver each recorded one too.
    seen = set(o['id'] for o in (rec.get('before') or []))
    new = [o for o in (rec.get('afterWhole') or []) if o['id'] not in seen]
    ok_('...marked as the phone scanner\'s', len(new) == 1 and new[0].get('browser') is True)
    ok_('...as an offer, not a kind the offers page would drop',
        new and new[0].get('kind') is None)
    eq('...with the figures the screen showed',
       (new[0].get('pay'), new[0].get('state')) if new else None,
       ((rec.get('read') or {}).get('pay'), (rec.get('read') or {}).get('state')))
    ok_('...and the rate (%r)' % (new[0].get('perHour') if new else None),
        new and abs((new[0].get('perHour') or 0) - ((rec.get('read') or {}).get('perHour') or -1)) < 0.06)
    # The lock is dropped after three frames that read nothing, and the card
    # is still there when the frames agree again. That second lock was a
    # second row — the same offer twice in the journal and in every median —
    # for every glare frame and every hand across the lens. The rig's journal
    # has always had the rule for this; the phone now has the same one.
    eq('the same card locked again a moment later is not a second row',
       len(rec.get('afterAgain') or []) - before, 1)
    eq('a fragment writes nothing', len(rec.get('afterFragment') or []) - before, 1)
    eq('with the rig out of reach nothing arrives', len(rec.get('whileDown') or []) - before, 1)
    eq('...and the row is kept', rec.get('queued'), 1)
    # Kept and said. A backlog against a rig that is not answering is the one
    # state a driver can still act on — before the ceiling, and long before
    # the browser starts refusing rows — so it is the one the screen names.
    # Nothing said it before: the page showed the verdict, buzzed, and looked
    # exactly as it does when every row is landing.
    ok_('...and the screen says the rig has not answered (%r)'
        % (rec.get('downStatus') or '')[:60],
        'waiting' in (rec.get('downStatus') or '')
        and 'has not answered' in (rec.get('downStatus') or ''))
    eq('...and goes with the next lock, both of them', len(rec.get('afterBack') or []) - before, 3)
    eq('...leaving nothing kept', rec.get('queuedAfter'), 0)
    ok_('...and the screen stops saying it (%r)' % (rec.get('backStatus') or '')[:60],
        'waiting' not in (rec.get('backStatus') or ''))
    eq('the same payout ninety seconds after the last sight of it is a new offer',
       len(rec.get('afterAged') or []) - before, 4)
    relock = got.get('relock') or {}
    states = relock.get('states') or []
    ok_('the harness reading is whole and the blank one is not',
        relock.get('complete') is True and relock.get('nothingComplete') is False)
    ok_('the frames agreeing locks the loop', len(states) == 8 and states[1] is True)
    ok_('...three frames reading nothing drop the lock', len(states) == 8 and states[5] is False)
    ok_('...and the frames agreeing again find it', len(states) == 8 and states[7] is True)
    eq('a lock lost and found on one card is one row, the window running from '
       'the last sight of it', len(rec.get('afterRelock') or []) - before, 5)
    fc = rec.get('fragmentComplete')
    eq('a fragment that reads complete is a sight of the card too'
       if fc else 'a fragment that reads incomplete is no sight of the card',
       len(rec.get('afterFragmentSight') or []) - before, 6 if fc else 7)

    # A whole card off a photo is a lock. It showed ACCEPT, "confirmed" and
    # the green corners and reached nothing, on the night Photo gets used.
    eq('a whole card read from a photo is one row in the journal',
       len(rec.get('afterPhoto') or []) - before, (6 if fc else 7) + 1)
    ok_('...and the screen said so (%r)' % (got.get('photoStatus') or '')[:40],
        'confirmed' in (got.get('photoStatus') or ''))
    # A one-shot message holds through the next read.
    ok_('Reset says so (%r)' % (got.get('holdAt0') or ''), 'back to its default' in (got.get('holdAt0') or ''))
    ok_('...and still says so after the next read (%r)' % (got.get('holdAfterRead') or '')[:40],
        'back to its default' in (got.get('holdAfterRead') or ''))
    # A read that never answers.
    st = got.get('stall') or {}
    ok_('a read that never answers is a failed read (%r)' % (st.get('status') or '')[:50],
        st.get('failed') and 'read failed' in (st.get('status') or ''))
    eq('...the reader is loaded again', st.get('restarts'), 1)
    ok_('...and answers', st.get('ready'))
    eq('...reading the next card (%r)' % st.get('pay'), st.get('pay'), 16.05)
    # The shell, registered from this page.
    eq('scan.html registers the offline shell on its own', got.get('swAuto'), 1)
    # ...and so does the panel, in a browser that has opened nothing else. This
    # is the page with the hard "must come up with no network" requirement and
    # it was the one page not asking for the shell.
    eq('live.html registers the offline shell on its own',
       got.get('panelSw'), 1)
    ed = got.get('engineDown') or {}
    ok_('a reader that never loads is called failed (%r)' % (ed.get('status') or '')[:50],
        'failed to load' in (ed.get('status') or '') and ed.get('failed') is True)
    ok_('...and Photo says so rather than "try again in a moment" (%r)' % (ed.get('photo') or '')[:50],
        'reload' in (ed.get('photo') or '') and 'moment' not in (ed.get('photo') or ''))

    # A row kept while a flush was in flight waited for the next flush — the
    # next lock, or the next time the page opened — with the rig answering
    # the whole time. It goes with a flight of its own now, and the one
    # answer names it, so a page marking rows sent sees it go.
    mid = got.get('midflight') or {}
    ok_('two rows kept a moment apart both reach the rig', mid.get('ok'))
    ok_('...the answer naming the first', mid.get('sentA'))
    ok_('...and the one kept while the first was in flight', mid.get('sentB'))
    eq('...leaving nothing kept', mid.get('left'), 0)

    # --- a queue that has run out of room ---------------------------------
    #
    # Measured against the owner's real week before any of this was written:
    # 4,664 offers (four passes of the 1,166) put to the old keep() at
    # Chrome's 5MB, charged in UTF-16 as it charges it. It said yes to all
    # 4,664. Three thousand two hundred and sixty-five landed. One thousand
    # three hundred and ninety-nine went nowhere, with keep() returning the
    # row every time, and from row 3,266 onward EVERY offer was lost — not
    # occasionally, permanently, until a rig answered. That is the second
    # fault class exactly: something disappearing with nothing saying so.
    qf = got.get('queueFull') or {}
    ok_('the full queue was exercised', bool(qf))
    eq('the ceiling is a number rows can be counted against (%r)' % qf.get('cap'),
       qf.get('capUsable'), True)
    if qf.get('capUsable'):
        eq('a row past the ceiling is still kept', qf.get('keptOverCap'), True)
        eq('...and the queue stays at the ceiling', qf.get('heldAtCap'), qf.get('cap'))
        # From the front, so what survives is the most recent: the rows the
        # offers page's medians and the shift advice are about.
        eq('...having shed the oldest', qf.get('dropped'), 1)
        eq('...and named the moment the record now starts at',
           qf.get('through'), 5000)
        eq('...which is one before the oldest still held',
           qf.get('oldestKept'), 5001)
        # The other end: a store that will not take the write at all.
        eq('a row the browser refuses comes back as null, not as a row',
           qf.get('refusedIsNull'), True)
        eq('...leaving every row already queued exactly where it was',
           qf.get('heldAfterRefusal'), qf.get('cap'))
        eq('...counted as lost', qf.get('lost'), 1)
        # A refused write shed nothing, because it never landed. Counting it
        # as a drop would put a number on screen for rows that are still on
        # the disk — a confidently wrong one, which is the first fault class.
        eq('...and not also counted as dropped', qf.get('droppedUnchanged'), True)
        # A full store is not permanent. The count of what was lost is; the
        # warning that it is happening is not, and a present-tense claim that
        # outlives the thing it describes is the fifth fault class — the same
        # one the "find the rig" advice on this line already had.
        eq('the refusal is reported while it is happening',
           qf.get('refusingWhileRefused'), True)
        eq('...the next row lands once the store takes writes again',
           qf.get('keptAfterRecovery'), True)
        eq('...so the present-tense warning clears',
           qf.get('refusingAfterRecovery'), False)
        eq('...while the count of what was lost does not',
           qf.get('lostAfterRecovery'), 1)

    # --- the loss and the live backlog share one line ---------------------
    #
    # The ceiling only bites after the rig has been out of reach long enough to
    # fill a thousand-row queue, so "rows were dropped" and "the rig is not
    # answering" are the SAME moment, not alternatives. The three clauses were
    # early returns in that order, which meant the permanent loss hid the live
    # backlog for the rest of the page's life — and the backlog is the only one
    # of the three a driver can act on.
    lb = got.get('lossAndBacklog') or {}
    ok_('the queue really is in trouble for this block (%s)' % lb.get('trouble'),
        lb.get('trouble') not in (None, 'null'))
    eq('...and the rig really is out of reach', lb.get('reachable'), False)
    ok_('...with rows actually waiting (%s)' % lb.get('waiting'), (lb.get('waiting') or 0) > 0)
    ok_('the line names what was lost (%r)' % (lb.get('line') or '')[:80],
        'not in the journal' in (lb.get('line') or '')
        or 'NOT SAVING' in (lb.get('line') or ''))
    ok_('...and still names the backlog, which is the part that can be acted on',
        'has not answered' in (lb.get('line') or ''))
    # An instruction that stops being true the moment the rig answers, on a
    # line that never clears, is this project's fifth fault class.
    ok_('...and gives no advice that goes stale when the rig comes back',
        'find the rig' not in (lb.get('line') or '')
        and 'queue is full' not in (lb.get('line') or ''))

    # --- a rate that is only a ceiling, said in words ---------------------
    #
    # rate() caps the verdict at CLOSE CALL when a cost per mile is set and the
    # card states no chargeable distance, because the headline is then gross —
    # an upper bound, not the offer. live.html and the offers page both name
    # it. This screen — the one a driver uses when the rig is not there — put
    # "/hr" on it like any other number, so the only clue was an amber verdict
    # on a card whose printed rate clears the target, which reads as caution
    # rather than as a bound.
    ceil = got.get('ceiling') or {}
    ok_('the uncosted card was measured', bool(ceil))
    if ceil:
        ok_('the card really is uncosted, or nothing below means anything',
            ceil.get('uncosted') is True)
        eq('...and the verdict is capped, as it always was', ceil.get('state'), 'warn')
        ok_('...and now the screen says the rate is a ceiling (%r)'
            % (ceil.get('warn') or '')[:60],
            'ceiling' in (ceil.get('warn') or ''))
        ok_('...on the glass, not hidden', ceil.get('warnShown'))
        # The same sentence live.html uses, which is the point: a driver
        # checking one screen against the other has to find them agreeing.
        ok_('...in the same words as the driving screen',
            'No distance on the card' in (ceil.get('warn') or ''))

    # --- the row that exists to be checked against the phone ---------------
    #
    # The MILES cell took the PARSE's distance while the rate above it, the
    # journal row this page writes, live.html, the Pi's panel and the CSV all
    # take the verdict's. On a card stating a deadline and no duration the
    # parse never checks the distance at all — `milesChecked` is
    # `minutes !== null` — so rate() is where a lost decimal is put back, and
    # this cell printed the figure from before the repair. The corpus's own
    # $41.11 DoorDash card with `9.8 mi` read as `98 mi` gave $127/hr ACCEPT,
    # PAY $41.11, MIN 18, MILE 98.0, with this page's own note underneath
    # saying a decimal had been recovered. Nothing on that screen added up.
    dec = got.get('decimal') or {}
    ok_('the deadline card was read', bool(dec))
    if dec:
        # The preconditions, stated rather than assumed: if the parse ever
        # starts checking this card's distance itself the two figures become
        # the same number and every check below passes for the wrong reason.
        eq('the parse leaves this card\'s distance unchecked',
           dec.get('checked'), False)
        eq('...and reads it as the lost-decimal figure', dec.get('parsedMiles'), 98)
        eq('...while the cell shows the distance the verdict used',
           dec.get('mile'), '9.8')
        eq('...beside the card\'s own pay', dec.get('pay'), '$41.11')
        eq('...and the minutes the deadline left', dec.get('min'), '18')
        # The note and the number have to agree. A screen that announces a
        # repair and then prints the unrepaired figure is worse than one that
        # says nothing, because the sentence tells the driver to trust it.
        ok_('...and the note that says a decimal was recovered is on the glass '
            '(%r)' % (dec.get('warn') or '')[:70],
            'decimal' in (dec.get('warn') or ''))

    # --- two readings that disagree must not lock -------------------------
    #
    # AGREE_TO_LOCK exists because "two readings that agree is the difference
    # between acting on a number and acting on a glitch". The signature was
    # pay|minutes|miles — and on a delivery card `minutes` is null, the
    # duration comes from the deadline and the shopping allowance from the item
    # count. So two readings two hours apart on the deadline agreed perfectly
    # and locked.
    dis = got.get('disagree') or {}
    ok_('the disagreement case was measured', bool(dis))
    if dis:
        # The stake, said in the check rather than assumed: these are the same
        # card read twice, and the verdicts are eight times apart.
        ok_('the two readings really do give different verdicts ($%s vs $%s)'
            % (round(dis.get('rateA') or 0, 2), round(dis.get('rateB') or 0, 2)),
            abs((dis.get('rateA') or 0) - (dis.get('rateB') or 0)) > 20)
        ok_('...and the card states no duration of its own, which is the point',
            dis.get('minutesA') is None)
        ok_('...with the deadlines genuinely apart',
            dis.get('deadlineA') != dis.get('deadlineB'))
        eq('two readings that disagree about the deadline alone do not lock',
           dis.get('lockedOnDisagreement'), False)
        # Separately, because a signature that added the item count and
        # stopped there would pass the check above and still be wrong.
        eq('...nor two that disagree about the item count alone',
           dis.get('lockedOnItems'), False)
        # ...and the rule still lets a real agreement through.
        eq('...while the same card read twice still does',
           dis.get('lockedOnAgreement'), True)

    # --- and the row says what the phone showed ---------------------------
    #
    # row() took `minutes` and `miles` off the PARSE. rpi/journal.py takes both
    # off the verdict, and carries a comment saying why: on a delivery card the
    # duration comes from the deadline, and the distance may have had a lost
    # decimal put back. Neither of those is in the parse.
    #
    # So every offer typed on the keypad or read by the phone's scanner went
    # into the journal with figures that do not produce its own rate. The
    # suite could not see it because the fixture beside it hands row() a
    # hand-written `rate`, which is the drift this project keeps finding.
    # --- the note about the box, after the box stops being read -------------
    #
    # setAdjusting() writes that sentence only at the instant adjust mode is
    # entered, and the whole-frame checkbox is the one control that can make it
    # false afterwards. Both directions went stale; the second is the one that
    # matters. "The box is not used" left standing while sourceRect() has just
    # started cropping every read to it tells the driver the crop is off while
    # the crop is deciding whether anything is read at all.
    bn = got.get('boxNote') or {}
    ok_('the box note was driven through the checkbox', bool(bn))
    if bn:
        box, tick, untick = (bn.get('boxMode') or {}, bn.get('afterTick') or {},
                             bn.get('afterUntick') or {})
        ok_('adjust mode with the box in use says to drag it (%r)'
            % (box.get('text') or '')[:60], 'Drag the box' in (box.get('text') or ''))
        ok_('...and the note is on the glass', box.get('shown'))
        ok_('ticking whole-frame says the box is not used (%r)'
            % (tick.get('text') or '')[:60],
            'not used' in (tick.get('text') or ''))
        no_('...and stops telling the driver to drag it',
            'Drag the box' in (tick.get('text') or ''))
        # The half the original report missed, and the dangerous one.
        ok_('unticking it says to drag the box again (%r)'
            % (untick.get('text') or '')[:60],
            'Drag the box' in (untick.get('text') or ''))
        no_('...and stops saying the box is not used while it is being read',
            'not used' in (untick.get('text') or ''))
        # Re-stating the mode must not leave it: the note is rewritten, not the
        # mode toggled. A fix that flipped adjust mode off would pass both
        # checks above and make the ▣ button do the opposite of its label.
        ok_('...without leaving adjust mode', bn.get('stillAdjusting'))
        eq('...and the button still offers the way out',
           bn.get('labelWhileOn'), '▣ Done')
        # ...and flipping the checkbox from the normal screen must not put an
        # adjust-mode note on a page that is not adjusting.
        no_('flipping it outside adjust mode shows no note', bn.get('idleShown'))
        eq('...and leaves the button alone', bn.get('idleLabel'), '▣ Box')

    # --- one column of one file, written under two rules --------------------
    #
    # rpi/journal.py stores the reading the reader gave — line breaks and all —
    # capped at TEXT_KEPT. journal-client.js stored the FLATTENED form with no
    # cap, into the same column of the same append-only file. Flattening is
    # irreversible and journal.html renders this column inside a <pre>, so rig
    # rows showed the card and phone rows showed one run-on line; server.js's
    # CSV says of the column "It is what the reader read, line breaks and all".
    rt = got.get('rowText') or {}
    ok_('the stored reading was measured', bool(rt))
    if rt:
        # The two forms really do differ, or nothing below means anything.
        eq('the reader gives line structure', rt.get('rawNewlines'), 4)
        eq('...and flattening destroys it', rt.get('flatNewlines'), 0)
        eq('the phone stores the form that keeps it', rt.get('newlines'), 4)
        # Lossless: what is stored still parses to what was read. Keeping raw
        # would not be worth much if it cost the row its own numbers.
        eq('...and what is stored still parses back to the same card',
           rt.get('reparsePay'), rt.get('parsedPay'))
        eq('...distance included', rt.get('reparseMiles'), 4.6)
        # The cap, on the frame it exists for.
        ok_('a reading that spilled onto the screen behind the card is long (%r)'
            % rt.get('spillRead'), (rt.get('spillRead') or 0) > 1500)
        eq('...and is capped where the rig caps it', rt.get('spillStored'), 600)
        # The keypad hands row() no text at all and must still write no column.
        eq('a typed offer still stores no reading', rt.get('typedText'), 'undefined')
        # The dead twin, removed in the same change: `cardMinutes` was the
        # `minutes` expression character for character, so no input could make
        # the two differ, and the comment over it named journal.html as printing
        # "one or the other off this" — journal.html has no occurrence of it.
        # rpi/journal.py folds cardMinutes into `minutes` and writes no such key.
        eq('the stored row does not carry a second copy of its own minutes',
           rt.get('hasCardMinutes'), False)
        eq('...having already chosen between them', rt.get('rowMinutes'), 23)

    # --- a box being retyped is not a request for the default ---------------
    #
    # `bind()` here answered a blank box with `DEFAULTS[key]` and SAVED it,
    # while ui.js - which binds these same five keys against this same stored
    # object, 'uberscan.settings.v1' - answers it by keeping what is there, with
    # a comment saying why. Two answers to one question, and only one of them
    # had been thought about.
    #
    # A driver edits these at the wheel, so a half-typed box is the normal state
    # and not an edge case. Measured on this card: at their own $40 line it is a
    # PASS, and a backspace turned it into an ACCEPT and left $25 in the store.
    bb = got.get('blankBox') or {}
    ok_('the blanked-settings-box case was driven', bool(bb))
    if bb:
        chosen, blanked, retyped = (bb.get('chosen') or {}, bb.get('blanked') or {},
                                    bb.get('retyped') or {})
        # First, that the card really is a PASS at the line the driver chose -
        # otherwise the flip below proves nothing.
        eq('at the line the driver set, this card is a PASS', chosen.get('label'), 'PASS')
        eq('...against the target they typed', chosen.get('target'), 40)
        # The fault, both halves: the verdict must not move, and the line they
        # never chose must not reach the store.
        eq('backspacing the target box does not change the verdict',
           blanked.get('label'), 'PASS')
        eq('...nor quietly store a line the driver never chose',
           blanked.get('target'), 40)
        # ...and the box shows what is actually in force when they leave it, so
        # an empty box cannot read as "no target set".
        eq('leaving the box puts the number in force back into it',
           str(bb.get('shown')), '40')
        # The guard must not turn the box off: a real number still lands, and
        # here it lands hard enough to flip the verdict the other way.
        eq('a number typed into the box still lands', retyped.get('target'), 25)
        eq('...and the verdict follows it', retyped.get('label'), 'ACCEPT')
        # The quieter half. A blanked cost box dropped the deduction: on
        # "$18.50 22 min (9.4 mi)" at 33c/mile that is $41.99/hr reading
        # $50.45/hr, with `uncosted` still false so the "this rate is a ceiling"
        # notice never appears to say a cost was missing.
        eq('...and a blanked cost box does not drop the running cost',
           bb.get('costBlank'), 0.33)

    ra = got.get('rowAgrees') or {}
    ok_('the row was built from the real parser', bool(ra))
    if ra:
        # First: the two really do disagree, or nothing below means anything.
        ok_('the parse and the verdict disagree on this card (%r vs %r min, '
            '%r vs %r mi)' % (ra.get('parsedMinutes'), ra.get('shownMinutes'),
                              ra.get('parsedMiles'), ra.get('shownMiles')),
            ra.get('parsedMinutes') != ra.get('shownMinutes')
            and ra.get('parsedMiles') != ra.get('shownMiles'))
        eq('the row keeps the minutes the verdict was made over',
           ra.get('rowMinutes'), ra.get('shownMinutes'))
        eq('...and the distance it was made over', ra.get('rowMiles'),
           ra.get('shownMiles'))
        eq('...saying the decimal was put back, because it was',
           ra.get('rowCorrected'), True)
        eq('...and that the minutes are a deadline, not a stated duration',
           ra.get('rowFromDeadline'), True)
        # The property all of that is for: the row's own figures produce the
        # row's own rate. A reader months later can check it against nothing
        # but itself.
        gross = ra.get('rowGross')
        pay, mins = ra.get('rowPay'), ra.get('rowMinutes')
        worked = (pay / (mins / 60.0)) if (pay and mins) else None
        ok_('the row can be reconciled with itself (%s/hr from $%s over %s min)'
            % (round(worked, 2) if worked else None, pay, mins),
            worked is not None and abs(worked - gross) < 0.05)

    # --- and to the same number of places the Pi writes them to ------------
    #
    # rpi/journal.py puts every one of these through _round; journal-client.js
    # did not put them through anything. Same field, same project, same file on
    # disk, and the second rule was absent rather than different - which is the
    # shape that drifts without anybody noticing, because both pages round for
    # display and the only place a person meets the stored figure is the CSV.
    # Measured on this card: the Pi wrote 19.43 and the phone wrote
    # 19.434782608695652 into the column beside it.
    # --- which end is which, on a row the browser wrote ---------------------
    #
    # The Pi's rows carry `pickup` and `dropoff`; the browser's carried only
    # `places`. Both map surfaces ask for the two fields and not the list — the
    # offers page hides a row's map controls without them, and map.html's whole
    # working set is `o.pickup || o.dropoff` — so an offer read on the phone
    # was on no map at all. That is the worst half to lose: the phone's scanner
    # exists for the nights the rig cannot read, so those rows are the ones
    # with no other record of where the job went.
    _ends = got.get('rowEnds') or {}
    ok_('the browser parser names both ends of this card',
        _ends.get('parsedPickup') and _ends.get('parsedDropoff'))
    eq('...and the row it writes carries the pickup',
       _ends.get('pickup'), _ends.get('parsedPickup'))
    eq('...and the dropoff', _ends.get('dropoff'), _ends.get('parsedDropoff'))
    # ...and an end the card did NOT name is absent from the row rather than
    # present and empty, which downstream would read as "this went somewhere".
    # The card two fixtures up prints "Pickup Papa Johns" and no destination.
    _ra2 = got.get('rowAgrees') or {}
    eq('a card naming only its pickup writes that pickup',
       _ra2.get('rowPickup'), _ra2.get('parsedPickup'))
    ok_('...and it really is only the pickup', bool(_ra2.get('parsedPickup'))
        and not _ra2.get('parsedDropoff'))
    no_('...so the row carries no dropoff at all', _ra2.get('rowDropoff'))

    rr = got.get('rowRounds') or {}
    ok_('the rounding fixture produced a row', bool(rr))
    if rr:
        # First, that there was anything to round. A card whose rate came out
        # exactly two places long would pass every check below without the
        # rounding existing at all.
        raw = rr.get('rawPerHour')
        ok_('the verdict\'s own rate has more places than a row keeps (%r)' % raw,
            isinstance(raw, float) and round(raw, 2) != raw)
        for field, dp in (('perHour', 2), ('grossPerHour', 2), ('perMile', 2),
                          ('cost', 2), ('billedMinutes', 1)):
            v = rr.get(field)
            ok_('the row stores %s to %d place%s (%r)'
                % (field, dp, '' if dp == 1 else 's', v),
                v is None or (isinstance(v, (int, float))
                              and round(float(v), dp) == float(v)))
        # ...and it is the same number, not merely a short one.
        eq('...and it is the figure the Pi would have written for this card',
           rr.get('perHour'), 19.43)

        # The one-decimal field, on a card where it is not already whole. A
        # shopping allowance of 25 seconds over 7 items bills 25.9166... minutes.
        raw_pad = rr.get('rawPadMinutes')
        ok_('a shopping allowance bills a fraction of a minute (%r)' % raw_pad,
            isinstance(raw_pad, float) and round(raw_pad, 1) != raw_pad)
        eq('...and the row keeps one decimal of it', rr.get('padMinutes'), 25.9)

        # ...and a figure the card never supported stays missing rather than
        # becoming arithmetic. Not zero, and - the part that took finding - not
        # NaN either: NaN serializes to `null`, so a row carrying it reads
        # afterwards exactly like a row that honestly had no distance.
        eq('the verdict has no per-mile on a card with no distance',
           rr.get('rawNullPerMile'), 'undefined')
        eq('...and the row does not turn that into arithmetic',
           rr.get('nullPerMile'), 'undefined')
        eq('...so nothing numeric is stored for it at all',
           rr.get('nullPerMileIsNumber'), False)

    # --- the offline cache keeps the engine and refreshes the app ----------
    # The version constant used to be the whole mechanism: forget to bump it and
    # an installed phone serves the old code for ever, which is exactly what
    # happened to two fixes in two commits. The app shell revalidates in the
    # background now, so forgetting costs one page load.
    #
    # And the engine lives in a cache of its own. It was never in ASSETS — it
    # only ever arrived opportunistically, under the same key the activate
    # handler deletes — so the obvious fix, bumping the version, would have
    # thrown away 15MB of reader and left an offline phone unable to scan at
    # all, in the name of shipping a scanner fix.
    # First, because everything below it depends on this and nothing below it
    # would say so. An uncontrolled page fetches straight past the worker, so
    # the engine cache stays empty and the failure reads as "the worker did not
    # cache the engine" when the truth is "the worker never saw the request".
    ok_('the page is under the worker before anything is asked of it',
        got['sw'].get('controlled'))
    held = got['sw']['held']
    shells = [k for k in held if k.startswith('uberscan-shell-')]
    blobs = [k for k in held if k.startswith('uberscan-vendor-')]
    eq('the worker installs one app-shell cache', len(shells), 1)
    eq('...and one for the vendored engine', len(blobs), 1)
    ok_('the shell holds the app', any(p.endswith('scan.js') for p in held[shells[0]]))
    ok_('...and not the engine',
        not any('/vendor/' in p for p in held[shells[0]]))
    ok_('the engine cache holds the engine',
        any('/vendor/' in p for p in held[blobs[0]]))

    # The half of this that a single page load cannot exercise: what survives a
    # *version change*. Bumping the shell runs activate again, and activate
    # deletes every cache it is not told to keep — so the check is that it is
    # told to keep the engine. Asserted on the source, and said plainly rather
    # than dressed up as a runtime test, because reaching it for real would mean
    # serving two different workers to one page.
    worker_src = open(os.path.join(ROOT, 'sw.js')).read()
    keep = [l for l in worker_src.splitlines() if 'caches.delete(k)' in l]
    eq('activate has one rule about what to delete', len(keep), 1)
    ok_('...and it spares the app shell', 'SHELL' in keep[0])
    ok_('...and the vendored engine, which install does not put back',
        'BLOB' in keep[0])
    ok_('...which is a different cache from the shell', shells[0] != blobs[0])

    # Every page this server serves is in the shell. map.html was the one that
    # was not, and the fallback below answered for it with index.html — so
    # offline, "Map check" opened the ride calculator under the map's own URL.
    # Asserted against the directory rather than a hand-written list, so a page
    # added later has to be thought about rather than quietly left out.
    listed = [l for l in worker_src.splitlines()
              if l.strip().startswith("'") and l.strip().rstrip(',').endswith("'")]
    shelled = ' '.join(listed)
    for page in sorted(f for f in os.listdir(ROOT) if f.endswith('.html')):
        ok_('the shell holds %s' % page, ("'" + page + "'") in shelled)

    # ...and the app shell answers for the app's own entry and nothing else. A
    # navigation this build has never heard of gets an honest refusal, not a
    # page pretending to be the one that was asked for. The worker already
    # refuses the identical substitution for scripts, in as many words.
    ok_('an uncached navigation is not answered with the app shell',
        "path === '' || path === 'index.html'" in worker_src)
    ok_('...and says so rather than failing blank',
        'not in the offline copy' in worker_src)

    # --- the browser sizes its picture the way the Pi does ------------------
    # This is the rule that broke, and it broke by drifting from the Pi's. Both
    # are now the same two numbers, so the check is that they still agree.
    for w, h in FIT_CASES:
        want = PL.fit_for_ocr(np.zeros((h, w, 3), np.uint8))
        js = got['fit']['%dx%d' % (w, h)]
        eq('the browser sizes %dx%d as the Pi does' % (w, h),
           (js['w'], js['h']), (want.shape[1], want.shape[0]))
        ok_('...inside the pixel budget at %dx%d' % (w, h),
            js['w'] * js['h'] <= PL.MAX_OCR_PIXELS + 2000)

    # --- the box survives being pulled all the way in -----------------------
    #
    # A box dragged to its minimum came back null from validBox, because the
    # resize clamp produces exactly `x1 - MIN_BOX` and `x1 - (x1 - MIN_BOX)`
    # is one ulp under the floor. Measured with the gestures below — each
    # handle pulled inwards until it stops — that is the three top handles at
    # all three sizes, 9 of the 24; the other clamp, `x0 + MIN_BOX`, lands one
    # ulp above and survives, so which handles break depends on which way the
    # finger goes. Together with the overlay above, 15 of the 24 did nothing.
    #
    # What a driver saw: the box tracking their finger all the way in, then
    # snapping back to the default crop the moment they lifted it. No message,
    # no rule stated — the control simply did not work.
    # Nothing drawn over the box may take a press aimed at it. `#adjustNote` —
    # the line reading "drag the box onto the offer card, or a corner to
    # resize" — was sitting on top of three of the corners it names, on the
    # 800x480 panel the rig is bolted to and on a phone. 1024x600 has the room
    # and worked, which is why it looked fine wherever it was tried.
    covering = got.get('covering') or {}
    ok_('the handles were asked who answers for them', len(covering) >= 24)
    blocked = sorted(k for k, v in covering.items() if v != 'the box')
    eq('every handle of the reading box answers to a press', blocked, [])

    drags = got.get('drags') or {}
    ok_('the drags were measured', len(drags) >= 24)
    kept = [k for k, v in sorted(drags.items()) if v.get('stored')]
    lost = [k for k, v in sorted(drags.items()) if not v.get('stored')]
    eq('every handle keeps the box it was dragged to (%d of %d)'
       % (len(kept), len(drags)), lost, [])
    # ...and the element shows it, rather than reverting to the stylesheet.
    blank = [k for k, v in sorted(drags.items()) if not v.get('inline')]
    eq('...and the picture shows the box that was kept', blank, [])
    # The floor is still a floor. A box below it is refused, which is what the
    # slack must not have undone.
    for w, h in ((0.079, 0.5), (0.5, 0.079), (0.0, 0.5)):
        ok_('a box %gx%g is still refused as too small' % (w, h),
            'null' in subprocess.run(
                ['node', '-e',
                 'const s=require("fs").readFileSync(%r,"utf8");'
                 'const m=s.match(/function validBox[\\s\\S]*?\\n  \\}/)[0];'
                 'const MIN_BOX=0.08;'
                 'const f=new Function("MIN_BOX", m + ";return validBox");'
                 'console.log(String(f(MIN_BOX)([0.1,0.1,%g,%g])));'
                 % (os.path.join(ROOT, 'scan.js'), w, h)],
                capture_output=True, text=True).stdout)
finally:
    if proc is not None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
    shutil.rmtree(work, ignore_errors=True)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d browser-scanner checks passed' % ok)
sys.exit(1 if bad else 0)
