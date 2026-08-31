"""What the driving screen shows while a card is being read, and after.

    python3 rpi/test_dashboard.py

The other browser suite measures whether the pages fit. This one drives
live.html with the messages the scanner actually sends and checks what a driver
would see, because both faults it was written for were invisible to a page
loaded with nothing on it.

The first: for the second and a half a read takes, the panel said WAITING FOR
AN OFFER over a row of dashes — which is what it says when the phone is blank.
The card was there and the rig had already started on it.

The second: the raw $/hr is on this page in exactly one place, the working
block, and a landscape rule deleted that block whenever a notice was showing.
One of the notices is "distance unreadable", which is a stored property of the
merged reading and never clears — so on 52 of one real shift's 121 offers the
raw figure was not slow, it never appeared. Those are the same offers where no
mileage was deducted, so the block had no other line in it: a hidden empty box,
bought at the price of the one number it existed to show.

Neither is about how the page looks. Both are about whether a number that was
sent to the page reaches the glass.

EventSource is stubbed before the page's own script runs, so the real message
handler, the real render() and the real stylesheet are all exercised — only the
socket is fake. The server is the real server.js.
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The rig's own panel, and the small hat, which has rules of its own.
PANELS = [('800x480', 800, 480), ('1280x800', 1280, 800), ('480x320', 480, 320)]

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


def skip(why):
    print('%s — skipping the dashboard checks' % why)
    sys.exit(0)


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


# A card off the owner's own shift. `milesUncertain` is the common case — 52 of
# 121 — and the one where the raw rate is the only rate there is: no distance
# trusted means no mileage cost, which means net and raw are the same number and
# the working block has a single line in it.
UNCERTAIN = {
    'ready': True, 'locked': True, 'state': 'warn', 'doubt': None,
    'perHour': 21.82, 'grossPerHour': 21.82, 'billedMinutes': 22.0,
    'perMile': None, 'pay': 8.0, 'minutes': 22.0, 'cardMinutes': 22.0,
    'miles': 6.9, 'items': None, 'cost': 0, 'costPerMile': 0.3,
    'milesCorrected': False, 'milesUncertain': True, 'whole': False,
    # No mileage came off, and a cost per mile is set — so this rate is a
    # ceiling on the offer rather than the offer. 108 of 202 offers on one real
    # shift were rated this way.
    'uncosted': True,
    'legs': 3, 'mergedFrom': 5, 'ms': 1517, 'text': '', 'places': [],
    'fromDeadline': False, 'deliverBy': None, 'track': None,
}
# ...and one where the distance was trusted, so there are two lines and a cost.
DEDUCTED = dict(UNCERTAIN, state='no', perHour=14.71, grossPerHour=20.97,
                cost=2.4, perMile=0.7, milesUncertain=False, whole=True,
                uncosted=False,
                places=['Cobb Pkwy NW, Acworth', 'Canton Rd, Marietta'])
# A delivery card states a deadline and no duration, so `minutes` is null and
# the rate was worked out over `cardMinutes`. The raw row divided by `minutes`
# and printed "$12.00 in -- min = $21.2/hr raw" — a sum with nothing under the
# line, on the whole DoorDash half of a shift.
DEADLINE = dict(UNCERTAIN, state='warn', pay=12.0, minutes=None, cardMinutes=34.0,
                billedMinutes=34.0, perHour=21.18, grossPerHour=21.18,
                fromDeadline=True, deliverBy=1140, miles=None, whole=True,
                milesUncertain=False, cost=0)

# A payout whose decimal point did not survive the read. $136 is inside the
# sane range for a payout and ten minutes is inside the sane range for a trip;
# it is the pair that cannot be true, and nothing tested the pair until five
# readings of one shift reached the panel as ACCEPT between $103 and $816/hr.
IMPOSSIBLE = dict(UNCERTAIN, state='doubt', doubt='rate', pay=136.0,
                  minutes=10.0, cardMinutes=10.0, billedMinutes=10.0, miles=3.1,
                  perHour=816.0, grossPerHour=816.0, whole=True)

READINGS = {'uncertain': UNCERTAIN, 'deducted': DEDUCTED, 'deadline': DEADLINE,
            'impossible': IMPOSSIBLE}

DRIVER = r'''
const { chromium } = require('playwright');
const [base, panelsJson, readingsJson] = process.argv.slice(2);
const PANELS = JSON.parse(panelsJson), READINGS = JSON.parse(readingsJson);

// The page's own socket, replaced before its script runs. Everything above the
// socket — the message handler, render(), the stylesheet — is the real thing.
const STUB = `
  window.__sent = [];
  class FakeEventSource {
    constructor(url) { this.url = url; window.__es = this; }
    close() {}
    push(obj) {
      window.__sent.push(obj);
      if (this.onmessage) this.onmessage({ data: JSON.stringify(obj) });
    }
  }
  window.EventSource = FakeEventSource;
  window.__replay = REPLAY_BODY;
`;

// What a driver can actually see: on screen, with a box, not display:none, and
// not scrolled off the glass.
//
// A function, not a string of one. Handed a string, page.evaluate treats it as
// an expression to evaluate rather than a function to call, so it returns the
// closure — which does not serialise, and every measurement came back
// undefined while the run still reported success.
const LOOK = (sel) => {
  const el = document.querySelector(sel);
  if (!el) return { there: false, shown: false, text: '' };
  const r = el.getBoundingClientRect();
  const cs = getComputedStyle(el);
  return {
    there: true,
    shown: r.width > 0 && r.height > 0 && cs.display !== 'none'
           && cs.visibility !== 'hidden' && Number(cs.opacity) > 0.05
           && r.top >= 0 && r.bottom <= window.innerHeight + 1,
    text: (el.textContent || '').replace(/\s+/g, ' ').trim(),
  };
};

(async () => {
  let browser;
  for (const exe of JSON.parse(process.env.PW_EXES || '[]').concat([null])) {
    try {
      browser = await chromium.launch(exe ? { executablePath: exe } : {});
      break;
    } catch (e) { /* try the next one */ }
  }
  if (!browser) { console.log(JSON.stringify({ skip: 'no chromium' })); return; }

  const out = {};
  for (const panel of PANELS) {
    const ctx = await browser.newContext({
      viewport: { width: panel[1], height: panel[2] }, deviceScaleFactor: 1,
    });
    // Named, not every key: READINGS also carries a reading the panel is
    // meant to refuse, and the per-panel sweep below asserts a verdict is
    // shown. The Python half walks the same three by name.
    for (const key of ['uncertain', 'deducted', 'deadline']) {
      const page = await ctx.newPage();
      await page.addInitScript(STUB.replace('REPLAY_BODY', 'null'));
      await page.goto(base + '/live.html', { waitUntil: 'domcontentloaded' })
                .catch(() => {});
      await page.waitForFunction('window.__es !== undefined', null,
                                 { timeout: 10000 }).catch(() => {});
      const slot = {};

      // 1. The scanner is running and nothing is on the phone.
      await page.evaluate(() => window.__es.push(
        { phase: 'scanning', message: '' }));
      await page.evaluate(() => window.__es.push(
        { alive: true, at: Date.now(), tooBright: false, tooDim: false }));
      await page.waitForTimeout(120);
      slot.idle = await page.evaluate(LOOK, '#verdictLabel');

      // 2. A card has arrived and the reader has started on it. No verdict
      //    rides this message, so it must not disturb one.
      await page.evaluate(() => window.__es.push(
        { reading: true, at: Date.now() }));
      await page.waitForTimeout(120);
      slot.reading = await page.evaluate(LOOK, '#verdictLabel');
      slot.readingRate = await page.evaluate(LOOK, '#perHour');

      // 3. The read came back.
      await page.evaluate((r) => window.__es.push(r), READINGS[key]);
      await page.waitForTimeout(180);
      slot.verdict = await page.evaluate(LOOK, '#verdictLabel');
      slot.rate = await page.evaluate(LOOK, '#perHour');
      slot.raw = await page.evaluate(LOOK, '.working .raw');
      slot.net = await page.evaluate(LOOK, '.working .net');
      slot.warn = await page.evaluate(LOOK, '#warn');
      slot.places = await page.evaluate(LOOK, '#places');
      // The card goes away. An address left on screen would read as belonging
      // to whatever arrives next.
      await page.evaluate(() => window.__es.push(
        { ready: false, state: 'empty', track: null }));
      await page.waitForTimeout(150);
      slot.placesAfter = await page.evaluate(LOOK, '#places');
      await page.evaluate((r) => window.__es.push(r), READINGS[key]);
      await page.waitForTimeout(150);
      slot.fits = await page.evaluate(() => {
        const d = document.documentElement;
        return d.scrollHeight <= d.clientHeight + 1
            && d.scrollWidth <= d.clientWidth + 1;
      });
      out[panel[0] + ' ' + key] = slot;
      await page.close();
    }
    await ctx.close();
  }

  // --- marking an offer as taken, from the screen the driver is looking at -
  //
  // The rig cannot see the Accept button and must never press it, so whether an
  // offer was taken is a fact only the driver has. The catch is the ordering:
  // they accept ON THE PHONE, the card is replaced by a navigation screen, the
  // scanner reads no card and the verdict clears — so by the time they can say
  // "I took that", the thing they took is no longer on the panel. The control
  // therefore marks the last offer on RECORD and is named after it.
  {
    const ctx = await browser.newContext({
      viewport: { width: 800, height: 480 }, deviceScaleFactor: 1,
    });
    const page = await ctx.newPage();
    const posted = [];
    // The response carries `holding`, because the real one does and because
    // that is the whole point of the two checks below: marking is the ONLY
    // moment the panel can learn there is an order in the car in time to be
    // useful. A stub that answered `{"ok":true}` and nothing else is what let
    // the destination button stay hidden on the one path it was built for.
    await page.route('**/api/offers/mark', async (route) => {
      const body = JSON.parse(route.request().postData() || '{}');
      posted.push(body);
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ ok: true, holding: !!body.accepted }),
      });
    });
    // The shift figures, and how many times the page asked for them. The
    // answer changes on the second ask so a refetch is visible rather than
    // inferred — a count that never moved would look identical to one that was
    // refetched and happened to be the same.
    const shiftAsked = [];
    await page.route('**/api/today*', async (route) => {
      shiftAsked.push(route.request().url());
      const n = shiftAsked.length;
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ offers: 9, counted: 8, setAside: 1,
                               took: n === 1 ? 2 : 3, median: 21,
                               beforeClock: 0, unreadable: null,
                               rolled: false, clockSet: true }),
      });
    });
    await page.addInitScript(STUB.replace('REPLAY_BODY', 'null'));
    await page.goto(base + '/live.html', { waitUntil: 'domcontentloaded' })
              .catch(() => {});
    await page.waitForFunction('window.__es !== undefined', null,
                               { timeout: 10000 }).catch(() => {});
    const look = () => page.evaluate(() => {
      const t = document.getElementById('took');
      const r = t.getBoundingClientRect();
      return { hidden: t.hidden, text: (t.textContent || '').trim(),
               pressed: t.getAttribute('aria-pressed'),
               w: Math.round(r.width), h: Math.round(r.height),
               clipped: t.scrollWidth > t.clientWidth + 1,
               fits: document.documentElement.scrollWidth
                     <= document.documentElement.clientWidth + 1 };
    });

    // The shift line, measured the same way as everything else on this panel:
    // on-glass, on one line, and not widening the row it sits on.
    const lookShift = () => page.evaluate(() => {
      const s = document.getElementById('shift');
      const r = s.getBoundingClientRect();
      const cs = getComputedStyle(s);
      const conn = document.getElementById('conn').getBoundingClientRect();
      // Against its own line box, NOT against the row it sits in. "No taller
      // than my flex container" is true of every flex item at every size and
      // for every string — it was a check that could not fail, which left the
      // whole nowrap/ellipsis rule unguarded.
      const line = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.2;
      return { hidden: s.hidden, text: (s.textContent || '').trim(),
               shown: !s.hidden && r.width > 0 && r.height > 0
                      && r.top >= 0 && r.bottom <= window.innerHeight + 1,
               size: Math.round(parseFloat(cs.fontSize)),
               oneLine: r.height <= line * 1.6,
               // ...and it gives way rather than wrapping the message beside
               // it, which is the one that matters most when it appears.
               connLines: Math.round(conn.height / line),
               fits: document.documentElement.scrollWidth
                     <= document.documentElement.clientWidth + 1 };
    });

    await page.evaluate(() => window.__es.push({ phase: 'scanning' }));
    await page.waitForTimeout(120);
    out.tookIdle = await look();
    // Asked for at load, before any card has arrived — a shift is not about
    // the offer on screen and must not wait for one.
    out.shiftFirst = await lookShift();

    await page.evaluate((r) => window.__es.push(r), READINGS.deducted);
    await page.evaluate(() => window.__es.push(
      { offer: { id: 'o1', pay: 8.04, minutes: 23, perHour: 14.71 }, at: 1 }));
    await page.waitForTimeout(150);
    out.tookOffered = await look();

    // The driver accepts on the phone; the card goes.
    await page.evaluate(() => window.__es.push(
      { ready: false, state: 'empty', track: null }));
    await page.waitForTimeout(150);
    out.tookAfterCard = await look();

    // Short, and recorded rather than awaited into a stall. page.click waits
    // for the element to become clickable, so a control that is hidden when it
    // should not be turns a failed check into a ten-minute hang — which is how
    // the mutation that hides it after the card goes was "caught" the first
    // time. A check that stalls is not a check that failed.
    const press = () => page.click('#took', { timeout: 3000 }).then(() => true,
                                                                   () => false);
    out.tookClicked = await press();
    await page.waitForTimeout(400);
    out.tookMarked = await look();
    // ...and the two controls for the order now in the car.
    //
    // THIS is the moment the destination is on the phone: the driver accepted,
    // the card went, and they pressed "Took". No reading is coming - there is
    // no card to read - so a panel that only learns about a held order from a
    // reading leaves ⌖ Dropoff hidden until the NEXT offer arrives, by which
    // point the phone shows that offer and the button photographs the wrong
    // screen. Measured on the glass, not off a variable.
    const lookBar = (id) => page.evaluate((sel) => {
      const el = document.getElementById(sel);
      if (!el) return { there: false, shown: false, text: '' };
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      return { there: true,
               shown: !el.hidden && r.width > 0 && r.height > 0
                      && cs.display !== 'none' && r.top >= 0
                      && r.bottom <= window.innerHeight + 1,
               text: (el.textContent || '').trim() };
    }, id);
    out.destAfterMark = await lookBar('dest');
    out.dropAfterMark = await lookBar('drop');
    // Marking is the one thing on this screen that changes the count, so it is
    // the one time the figures are worth asking for off the timer. Left to the
    // three-minute poll, a driver would press "took it" and watch the number
    // beside it not move — the same two-figures-disagreeing failure, now inside
    // one panel.
    out.shiftAfterMark = await lookShift();
    out.shiftAsked = shiftAsked.length;

    // A different offer arrives while the last one is STILL MARKED, which is
    // the ordering that matters and the one an undo-first test cannot reach: a
    // mark belongs to an offer, not to the button, and a tick carried over
    // would tell the driver they had recorded something they had not.
    await page.evaluate(() => window.__es.push(
      { offer: { id: 'o2', pay: 12.45, minutes: 30, perHour: 22.1 }, at: 2 }));
    await page.waitForTimeout(150);
    out.tookNext = await look();

    // ...and the new one marks and unmarks as its own.
    out.tookClickedNext = await press();
    await page.waitForTimeout(200);
    out.tookNextMarked = await look();
    out.tookClickedAgain = await press();
    await page.waitForTimeout(200);
    out.tookUndone = await look();
    out.tookPosted = posted;
    await page.close();
    await ctx.close();
  }

  // --- a rate the rig could not cost, and one that cannot be true ----------
  //
  // Two states a driver has to be able to tell apart at a glance from the
  // driving seat. The first is a real offer whose running cost could not be
  // taken off, so the number on the panel is a ceiling: it may clear the target
  // or be nowhere near it. The second is a reading that cannot be true at all.
  {
    const ctx = await browser.newContext({
      viewport: { width: 800, height: 480 }, deviceScaleFactor: 1,
    });
    const page = await ctx.newPage();
    await page.addInitScript(STUB.replace('REPLAY_BODY', 'null'));
    await page.goto(base + '/live.html', { waitUntil: 'domcontentloaded' })
              .catch(() => {});
    await page.waitForFunction('window.__es !== undefined', null,
                               { timeout: 10000 }).catch(() => {});

    // A rate that cleared the target on a distance nobody could use.
    await page.evaluate((r) => window.__es.push(r),
      Object.assign({}, READINGS.uncertain, { state: 'warn', perHour: 27.24,
                                              grossPerHour: 27.24 }));
    await page.waitForTimeout(200);
    out.ceiling = {
      label: await page.evaluate(LOOK, '#verdictLabel'),
      warn: await page.evaluate(LOOK, '#warn'),
      rate: await page.evaluate(LOOK, '#perHour'),
    };

    // ...and one that cannot be true. $136 over ten minutes.
    await page.evaluate((r) => window.__es.push(r), READINGS.impossible);
    await page.waitForTimeout(200);
    out.impossible = {
      label: await page.evaluate(LOOK, '#verdictLabel'),
      rate: await page.evaluate(LOOK, '#perHour'),
      pay: await page.evaluate(LOOK, '#vPay'),
    };
    await page.close();
    await ctx.close();
  }

  // --- the shift line when the figures cannot be trusted -------------------
  //
  // Every one of these is a state where a plausible-looking count would be a
  // confidently wrong number, which is the thing this project refuses to print.
  // The rig's clock has not been set, so it does not know what day it is on;
  // the journal could not be read, which looks exactly like a quiet day unless
  // it says so; the journal just rolled past 64MB and is empty for a reason
  // that is not "no offers yet"; and the endpoint is not there at all, which is
  // what an older build does — as a text/plain 404, so the page's .json()
  // rejects rather than returning a status to branch on.
  for (const [key, body, status] of [
    ['clock', { clockSet: false }, 200],
    ['unreadable', { offers: 0, counted: 0, setAside: 0, took: 0, median: null,
                     beforeClock: 0, unreadable: 'EIO', clockSet: true }, 200],
    ['rolled', { offers: 0, counted: 0, setAside: 0, took: 0, median: null,
                 beforeClock: 0, unreadable: null, rolled: true,
                 clockSet: true }, 200],
    ['early', { offers: 3, counted: 3, setAside: 0, took: 1, median: 18,
                beforeClock: 4, unreadable: null, rolled: false,
                clockSet: true }, 200],
  ]) {
    const ctx = await browser.newContext({
      viewport: { width: 800, height: 480 }, deviceScaleFactor: 1,
    });
    const page = await ctx.newPage();
    await page.route('**/api/today*', async (route) => {
      await route.fulfill(status === 404
        ? { status: 404, contentType: 'text/plain', body: 'not found' }
        : { status: 200, contentType: 'application/json',
            body: JSON.stringify(body) });
    });
    await page.addInitScript(STUB.replace('REPLAY_BODY', 'null'));
    await page.goto(base + '/live.html', { waitUntil: 'domcontentloaded' })
              .catch(() => {});
    await page.waitForFunction('window.__es !== undefined', null,
                               { timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(300);
    out['shift_' + key] = await page.evaluate(() => {
      const s = document.getElementById('shift');
      return { hidden: s.hidden, text: (s.textContent || '').trim() };
    });
    await page.close();
    await ctx.close();
  }

  // --- ...and when the endpoint stops answering -----------------------------
  //
  // Asserting the line is hidden on a page that never got an answer proves
  // nothing: it starts hidden in the markup. The property that matters is that
  // figures which WERE on the panel come off it when they can no longer be
  // vouched for — an older build one git pull behind answers text/plain to an
  // unknown /api path, so .json() rejects rather than returning a status.
  {
    const ctx = await browser.newContext({
      viewport: { width: 800, height: 480 }, deviceScaleFactor: 1,
    });
    const page = await ctx.newPage();
    let asks = 0;
    await page.route('**/api/today*', async (route) => {
      asks += 1;
      await route.fulfill(asks === 1
        ? { status: 200, contentType: 'application/json',
            body: JSON.stringify({ offers: 7, counted: 7, setAside: 0, took: 2,
                                   median: 19, beforeClock: 0,
                                   unreadable: null, rolled: false,
                                   clockSet: true }) }
        : { status: 404, contentType: 'text/plain', body: 'not found' });
    });
    await page.route('**/api/offers/mark', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json',
                            body: '{"ok":true}' });
    });
    await page.addInitScript(STUB.replace('REPLAY_BODY', 'null'));
    await page.goto(base + '/live.html', { waitUntil: 'domcontentloaded' })
              .catch(() => {});
    await page.waitForFunction('window.__es !== undefined', null,
                               { timeout: 10000 }).catch(() => {});
    const peek = () => page.evaluate(() => {
      const s = document.getElementById('shift');
      return { hidden: s.hidden, text: (s.textContent || '').trim() };
    });
    await page.evaluate((r) => window.__es.push(r), READINGS.deducted);
    await page.evaluate(() => window.__es.push(
      { offer: { id: 'g1', pay: 8.04, minutes: 23, perHour: 14.71 }, at: 1 }));
    await page.waitForTimeout(300);
    out.shiftBefore = await peek();
    // Marking refetches, and this time the endpoint is not there.
    await page.click('#took', { timeout: 3000 }).catch(() => {});
    await page.waitForTimeout(500);
    out.shiftLost = await peek();
    out.shiftLostAsks = asks;
    await page.close();
    await ctx.close();
  }

  // --- a page opened against a rig that stopped an hour ago ----------------
  //
  // The seed and the SSE replay both hand over the last reading. The page used
  // to start its own staleness clocks at zero for both, so a dead rig's ACCEPT
  // was painted at full confidence: twelve seconds before it dimmed, twenty
  // before anything said how old it was.
  {
    const ctx = await browser.newContext({
      viewport: { width: 800, height: 480 }, deviceScaleFactor: 1,
    });
    const page = await ctx.newPage();
    await page.addInitScript(
      STUB.replace('REPLAY_BODY', JSON.stringify(READINGS.deducted)));
    // The server is real, so /api/status is intercepted rather than faked
    // wholesale: everything else about the page stays as it ships.
    await page.route('**/api/status', async (route) => {
      const stale = Object.assign({}, READINGS.deducted, { at: 1 });
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ scanner: { running: true }, last: stale,
                               lastAgeMs: 3600000, heardAgeMs: 3600000,
                               // ...and which offer is on the record, which is
                               // the only way a page that has just opened can
                               // know: the socket replays the last reading, not
                               // the last offer.
                               // ...and whether it has already been marked.
                               // The button's state was page-local, so a
                               // reload offered to mark an offer that was
                               // already on the record — while the shift count
                               // beside it had already counted it.
                               offer: { id: 'seed-1', pay: 9.75, minutes: 21,
                                        perHour: 27.86, accepted: true },
                               offerAgeMs: 3600000,
                               status: { phase: 'scanning' } }),
      });
    });
    await page.goto(base + '/live.html', { waitUntil: 'domcontentloaded' })
              .catch(() => {});
    await page.waitForTimeout(700);
    out.seedTook = await page.evaluate(() => {
      const t = document.getElementById('took');
      return { hidden: t.hidden, text: (t.textContent || '').trim(),
               pressed: t.getAttribute('aria-pressed') };
    });
    out.stale = {
      detail: await page.evaluate(LOOK, '#detail'),
      verdict: await page.evaluate(LOOK, '#verdictLabel'),
      dimmed: await page.evaluate(
        () => document.getElementById('verdict').classList.contains('stale')),
    };

    // ...and the same reading arriving as a replay on a reconnect, which the
    // page stamped as freshly read once per reconnect for as long as it stayed
    // open.
    await page.evaluate(() => window.__es.push(
      Object.assign({}, window.__replay, { replay: true, ageMs: 3600000 })));
    await page.waitForTimeout(200);
    out.replay = {
      detail: await page.evaluate(LOOK, '#detail'),
      dimmed: await page.evaluate(
        () => document.getElementById('verdict').classList.contains('stale')),
    };
    // A genuine live read clears it again — the point is an accurate clock,
    // not a permanently pessimistic one.
    await page.evaluate((r) => window.__es.push(r), READINGS.deducted);
    await page.waitForTimeout(200);
    out.fresh = {
      detail: await page.evaluate(LOOK, '#detail'),
      dimmed: await page.evaluate(
        () => document.getElementById('verdict').classList.contains('stale')),
      // Set apart from the diagnostics it shares a line with, or it is one
      // grey fragment among five and reads as "1517ms" does.
      age: await page.evaluate(() => {
        const el = document.querySelector('#detail .age');
        if (!el) return null;
        const cs = getComputedStyle(el);
        const line = getComputedStyle(document.getElementById('detail'));
        return { text: (el.textContent || '').trim(),
                 first: document.getElementById('detail').firstChild === el,
                 weight: Number(cs.fontWeight),
                 lineWeight: Number(line.fontWeight),
                 colour: cs.color, lineColour: line.color };
      }),
    };
    // Nothing arrives for three seconds. The age is the one figure on this
    // page that changes while the page sits still, and a clock that only
    // updates when a reading lands is a clock that says "just now" for as
    // long as the rig is broken.
    await page.waitForTimeout(3000);
    out.aged = await page.evaluate(
      () => (document.querySelector('#detail .age') || {}).textContent || '');
    await page.close();
    await ctx.close();
  }

  await browser.close();
  console.log(JSON.stringify(out));
})().catch((e) => { console.log(JSON.stringify({ skip: String(e && e.message) })); });
'''

NODE_PATHS = [p for p in (os.environ.get('NODE_PATH'),
                          '/opt/node22/lib/node_modules') if p]
env_probe = dict(os.environ, NODE_PATH=os.pathsep.join(NODE_PATHS))
if subprocess.call(['node', '-e', 'require("playwright")'], env=env_probe,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
    skip('no playwright')

work = tempfile.mkdtemp()
journal = os.path.join(work, 'journal.jsonl')
open(journal, 'w').close()
port = free_port()
proc = subprocess.Popen(
    ['node', os.path.join(ROOT, 'server.js')],
    env=dict(os.environ, SCANNER='0', PORT=str(port), JOURNAL=journal),
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
base = 'http://127.0.0.1:%d' % port

try:
    for _ in range(120):
        try:
            urllib.request.urlopen(base + '/api/status', timeout=1).read()
            break
        except Exception:
            time.sleep(0.1)
    else:
        raise RuntimeError('the server never came up')

    driver = os.path.join(work, 'dashboard.js')
    open(driver, 'w').write(DRIVER)
    readings = READINGS
    proc2 = subprocess.run(
        ['node', driver, base, json.dumps(PANELS), json.dumps(READINGS)],
        env=dict(os.environ, NODE_PATH=os.pathsep.join(NODE_PATHS),
                 PW_EXES=json.dumps([
                     os.environ.get('CHROMIUM', ''),
                     '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
                 ])),
        capture_output=True, text=True, timeout=600)
    line = (proc2.stdout or '').strip().split('\n')[-1] if proc2.stdout else ''
    try:
        got = json.loads(line)
    except Exception:
        skip('the browser produced nothing (%s)'
             % (proc2.stderr or '')[-200:].replace('\n', ' '))
    if got.get('skip'):
        skip(got['skip'])

    for panel, _w, _h in PANELS:
        for key in ('uncertain', 'deducted', 'deadline'):
            where = '%s %s' % (panel, key)
            r = got.get(where)
            ok_('%s was measured' % where, r is not None)
            # Every slot, not just the dict. A measurement that came back
            # undefined used to vanish from the JSON and take its checks with
            # it, so the run passed by not looking.
            missing = [k for k in ('idle', 'reading', 'readingRate', 'verdict',
                                   'rate', 'raw', 'net', 'warn', 'places',
                                   'placesAfter')
                       if not isinstance((r or {}).get(k), dict)]
            eq('%s: every element was measured' % where, missing, [])
            if not r or missing:
                continue

            # --- the second and a half nothing accounted for ---------------
            eq('%s: an empty screen says it is waiting' % where,
               r['idle']['text'], 'WAITING FOR AN OFFER')
            eq('%s: a card under the reader says so instead' % where,
               r['reading']['text'], 'READING THE CARD')
            # The safety property. A message with no `ready` must not put a
            # number on the panel, because there is no number in it.
            eq('%s: ...without inventing a rate to go with it' % where,
               r['readingRate']['text'], '--')
            # ...and it must not survive the verdict it was waiting for.
            # A trailing "?" is the page saying the reading is not settled yet,
            # which is a different claim from "no card here" and is allowed.
            ok_('%s: the verdict replaces it' % where,
                r['verdict']['text'].rstrip(' ?')
                in ('ACCEPT', 'CLOSE CALL', 'PASS'))

            # --- the number that was sent and never shown ------------------
            ok_('%s: the raw $/hr is on the glass' % where, r['raw']['shown'])
            ok_('%s: ...with a figure in it' % where, '$' in r['raw']['text'])
            # A sum with something under the line. The row divided by the
            # card's stated duration, and a delivery card states a deadline
            # instead — so the whole DoorDash half of a shift read "$12.00 in
            # -- min = $21.2/hr raw", which is the one figure this panel had to
            # be argued into showing at all, over a dash.
            ok_('%s: ...and nothing in it is a dash' % where,
                '--' not in r['raw']['text'])
            ok_('%s: ...labelled as the raw one' % where,
                'raw' in r['raw']['text'])

            # Where the job goes. Sent on every read since the scanner learned
            # to read a map, and painted on no screen a driver looks at while
            # deciding — including this one, which is the one they look at.
            want = READINGS[key].get('places') or []
            eq('%s: the address is on the glass exactly when there is one' % where,
               bool(r['places']['shown']), bool(want))
            if want:
                for place in want:
                    ok_('%s: ...and names %s' % (where, place),
                        place in r['places']['text'])
            ok_('%s: ...and goes when the card does' % where,
                not r['placesAfter']['shown'])
            ok_('%s: the headline rate is on the glass' % where,
                r['rate']['shown'])
            ok_('%s: the panel still fits' % where, r['fits'])

    # --- marking an offer as taken, from the driving screen --------------
    idle = got.get('tookIdle') or {}
    offered = got.get('tookOffered') or {}
    gone = got.get('tookAfterCard') or {}
    marked = got.get('tookMarked') or {}
    undone = got.get('tookUndone') or {}
    nxt = got.get('tookNext') or {}
    posted = got.get('tookPosted') or []

    ok_('the mark control was measured', bool(offered))
    if offered:
        # Pressable at all — the property the timeout above turns from a stall
        # into a result.
        ok_('the control can actually be pressed', got.get('tookClicked'))
        ok_('...and pressed again to take it back off',
            got.get('tookClickedAgain'))
        # Nothing to mark before the scanner has written anything.
        ok_('there is nothing to mark before an offer is recorded', idle.get('hidden'))
        ok_('an offer on the record offers itself', not offered.get('hidden'))
        # Named, because the driver will be looking at it after the card has
        # gone and cannot otherwise tell which offer they are about to mark.
        ok_('...and says which offer', '8.04' in (offered.get('text') or ''))
        ok_('...as a question, not an instruction to the phone',
            (offered.get('text') or '').endswith('?'))

        # The case the whole design turns on: the driver accepts on the phone,
        # the card is replaced, the verdict clears — and the offer is still
        # markable, still named.
        ok_('the offer is still markable once the card has gone',
            not gone.get('hidden'))
        ok_('...and still named', '8.04' in (gone.get('text') or ''))

        ok_('marking says so', (marked.get('text') or '').startswith('\u2713'))
        eq('...to assistive tech as well', marked.get('pressed'), 'true')

        # ...and the two controls for the order that is now in the car appear
        # ON THE MARK, which is the only moment they are any use.
        #
        # The driver accepts on the phone, the card goes, they press "Took" \u2014
        # and the destination is on the phone RIGHT NOW. No reading is coming,
        # because there is no card to read. The panel used to learn about a
        # held order only from a reading, so \u2316 Dropoff stayed hidden until the
        # NEXT offer card arrived; by then the phone shows that card, and the
        # button reads the wrong screen. The one feature built for the 18% of
        # cards that name no address could not be reached on its own path.
        dest_now = got.get('destAfterMark') or {}
        drop_now = got.get('dropAfterMark') or {}
        ok_('the destination button appears the moment the offer is marked',
            dest_now.get('shown'))
        ok_('...saying what it reads', 'Dropoff' in (dest_now.get('text') or ''))
        ok_('...and so does the one that puts the order down',
            drop_now.get('shown'))

        # A mark belongs to an offer, not to the button. This is asked while
        # the previous offer is still marked: a tick carried onto the next card
        # tells the driver they recorded something they did not.
        eq('the next offer starts unmarked', nxt.get('pressed'), 'false')
        ok_('...and shows no tick', not (nxt.get('text') or '').startswith('\u2713'))
        ok_('...and is named after itself', '12.45' in (nxt.get('text') or ''))
        ok_('...and can be marked in its own right',
            (got.get('tookNextMarked') or {}).get('pressed') == 'true')

        ok_('pressing again takes it back off',
            (undone.get('text') or '').endswith('?'))

        # By id every time, and each mark against the offer that was on record
        # when it was pressed. Marking by pay-and-minutes would be a rule
        # catching every offer paying that to the cent.
        eq('...and every note names one offer by id, in order',
           posted, [{'id': 'o1', 'accepted': True},
                    {'id': 'o2', 'accepted': True},
                    {'id': 'o2', 'accepted': False}])

        # It has to be usable in a moving car and must not break the panel.
        for name, slot in (('offered', offered), ('marked', marked)):
            ok_('the control is a real target when %s (%dx%d)'
                % (name, slot.get('w') or 0, slot.get('h') or 0),
                (slot.get('w') or 0) >= 80 and (slot.get('h') or 0) >= 44)
            ok_('...with nothing clipped off it when %s' % name,
                not slot.get('clipped'))
            ok_('...and the panel still fits when %s' % name, slot.get('fits'))

    # --- a rate the rig could not cost, and one that cannot be true ------
    #
    # The panel's whole job is a verdict, and these are the two states where a
    # plausible-looking one would be wrong. On the owner's own shift of 202
    # offers, 108 were rated with no running cost at all and 33 of the 35
    # ACCEPTs came out of that pool; five readings reached the panel as ACCEPT
    # at between $103 and $816 an hour.
    ceiling = got.get('ceiling') or {}
    ok_('the uncosted state was measured', bool(ceiling.get('label')))
    if ceiling.get('label'):
        # Never ACCEPT. It may clear the target or be nowhere near it, and the
        # rig cannot tell which — CLOSE CALL is the honest answer.
        # startswith, because the panel appends " ?" while a reading is still
        # unsettled and that suffix is its own true statement. The property
        # here is the word, and above all that the word is not ACCEPT.
        label = (ceiling['label'].get('text') or '').strip()
        ok_('a rate with no mileage off it is a close call (%r)' % label,
            label.startswith('CLOSE CALL'))
        ok_('...and never an accept', 'ACCEPT' not in label)
        ok_('...and the number is still shown, because it is still evidence',
            ceiling.get('rate', {}).get('shown'))
        ok_('...with a notice saying it is a ceiling',
            'ceiling' in ((ceiling.get('warn') or {}).get('text') or ''))
        ok_('...which is on the glass, not pushed off it',
            (ceiling.get('warn') or {}).get('shown'))

    impossible = got.get('impossible') or {}
    ok_('the impossible reading was measured', bool(impossible.get('label')))
    if impossible.get('label'):
        # $136 over ten minutes. Each figure is sane alone; the pair cannot be.
        # Naming the pair matters — telling the driver to check the payout
        # would send them to the wrong half of the card when the time is what
        # was misread.
        eq('a reading that cannot be true names the pair, not a side',
           (impossible['label'].get('text') or '').strip(), 'CHECK PAY AND TIME')
        eq('...and withholds the rate rather than printing $816/hr',
           (impossible.get('rate') or {}).get('text'), '--')
        ok_('...while the figures it was working from stay on screen',
            '136' in ((impossible.get('pay') or {}).get('text') or ''))

    # --- what the shift adds up to, on the row under the verdict ---------
    first = got.get('shiftFirst') or {}
    ok_('the shift line was measured', bool(first))
    if first:
        # It is not about the offer on screen, so it must not wait for one:
        # this is read before any card has arrived.
        ok_('the shift shows before any card has', first.get('shown'))
        ok_('...saying how many offers', '9 offers' in (first.get('text') or ''))
        ok_('...how many were set aside rather than dropping them',
            'set aside' in (first.get('text') or ''))
        ok_('...how many were taken', 'took 2' in (first.get('text') or ''))
        ok_('...and the median rate', '$21/hr' in (first.get('text') or ''))
        # No dollar total. `pay` is what the card offered, not what was earned,
        # and a gross sum beside a net median is the sentence the offers page
        # was corrected for.
        ok_('...and does not claim a total earned',
            'offered' not in (first.get('text') or '')
            and '$21/hr' in (first.get('text') or '')
            and (first.get('text') or '').count('$') == 1)
        # On the glass and on one line, on the panel this is bolted to.
        ok_('...on one line', first.get('oneLine'))
        eq('...and the connection message beside it still on one',
           first.get('connLines'), 1)
        ok_('...without widening the panel', first.get('fits'))
        ok_('...at a size that can be read from the driving seat (%spx)'
            % first.get('size'), (first.get('size') or 0) >= 12)

    after = got.get('shiftAfterMark') or {}
    ok_('the shift line after a mark was measured', bool(after))
    if after:
        # Two figures forty pixels apart, about the same act the driver just
        # performed. If the count does not follow the button they contradict
        # each other on the panel.
        eq('...and the count is asked for again when an offer is marked',
           got.get('shiftAsked'), 2)
        ok_('...so the taken figure follows the button',
            'took 3' in (after.get('text') or ''))

    # A number that cannot be right is not printed. Each of these is a state
    # where the count would look perfectly plausible and be wrong.
    for key, must in (('clock', 'clock'),
                      ('unreadable', 'could not be read'),
                      ('rolled', 'rolled')):
        slot = got.get('shift_' + key) or {}
        ok_('the %s state was measured' % key, bool(slot))
        if slot:
            ok_('...and says so rather than counting (%s)' % key,
                must in (slot.get('text') or ''))
            ok_('...and prints no offer count (%s)' % key,
                'offer' not in (slot.get('text') or ''))

    # An older build has no such route and answers text/plain, so .json()
    # rejects. Asserting a hidden line on a page that never got an answer proves
    # nothing — it starts hidden. The property is that figures which WERE on the
    # panel come off it once they cannot be vouched for.
    before, lost = got.get('shiftBefore') or {}, got.get('shiftLost') or {}
    ok_('the shift line was on the panel first', bool(before))
    if before:
        ok_('...showing a shift', '7 offers' in (before.get('text') or ''))
        eq('...and the failed ask really happened', got.get('shiftLostAsks'), 2)
        ok_('...and it comes off when the figures can no longer be had',
            lost.get('hidden'))

    # Offers the rig recorded before its clock was set are stamped 1970 and
    # cannot fall inside any day window. That is true of every day forever, so
    # naming them on a line about today was a suffix that never cleared and
    # blamed this shift for rows from some past boot. The count stays in the
    # response; it is not a figure for this row.
    early = got.get('shift_early') or {}
    ok_('the pre-clock state was measured', bool(early))
    if early:
        ok_('...and an all-time tally is not printed on a line about today',
            'before the clock' not in (early.get('text') or ''))
        ok_('...while today\'s own figures still are',
            '3 offers' in (early.get('text') or ''))


    # --- a rig that stopped an hour ago does not look live --------------
    #
    # The seed and the SSE replay both hand the page the last reading. It used
    # to start its own staleness clocks at zero for both, so a dead rig's
    # verdict was painted at full confidence — twelve seconds before it dimmed,
    # twenty before anything said how old it was — on every load, and again on
    # every reconnect for as long as the tab stayed open.
    stale = got.get('stale') or {}
    ok_('the seeded verdict was measured', bool(stale.get('detail')))
    if stale.get('detail'):
        ok_('an hour-old reading is marked stale on load', stale.get('dimmed'))
        ok_('...and says how long ago it was read',
            'ago' in (stale['detail']['text'] or ''))
        ok_('...in something other than seconds-since-page-load',
            's ago' in (stale['detail']['text'] or '')
            and ' 0s ago' not in (stale['detail']['text'] or ''))

    # A page that has just opened knows the last offer only from the seed: the
    # socket replays the last *reading*, and a driver who accepted on the phone
    # gets back to this screen after the card has already gone. A stale verdict
    # and a markable offer are different things — the verdict is dimmed above
    # because it may no longer be true, while which offer was last written is a
    # fact that does not go off.
    seed_took = got.get('seedTook') or {}
    ok_('the seeded mark control was measured', bool(seed_took))
    if seed_took:
        ok_('a page opened after the card has gone can still mark it',
            not seed_took.get('hidden'))
        ok_('...and is named after the offer it would mark',
            '9.75' in (seed_took.get('text') or ''))
        # ...and remembers that it was already marked. Without this the button
        # forgot every reload and offered to mark an offer the shift count on
        # the same row had already counted.
        eq('...and a mark already on the record survives the reload',
           seed_took.get('pressed'), 'true')
        ok_('...showing it as marked rather than offering again',
            (seed_took.get('text') or '').startswith('✓'))

    replay = got.get('replay') or {}
    ok_('the replayed verdict was measured', bool(replay.get('detail')))
    if replay.get('detail'):
        ok_('a reconnect does not make an old reading fresh again',
            replay.get('dimmed'))

    # ...and a real read clears it. The point is an accurate clock, not a
    # permanently pessimistic one — a page that never trusts a verdict is as
    # useless as one that always does.
    fresh = got.get('fresh') or {}
    ok_('the live reading was measured', bool(fresh.get('detail')))
    if fresh.get('detail'):
        ok_('a genuine read is not stale', not fresh.get('dimmed'))
        # The age used to appear only once a reading had gone stale, which is
        # the moment it is least useful: the card is already dimmed and the
        # driver has already stopped believing it. It is on the line always
        # now, so this says what a fresh one reads as rather than that it reads
        # as nothing — "does not carry an age" would still pass on "just now",
        # which is an age, and would have gone on passing on "0s ago".
        eq('...and a fresh one says so in words',
           (fresh['detail']['text'] or '').split(' · ')[0], 'just now')
        ok_('...rather than counting from zero',
            's ago' not in (fresh['detail']['text'] or ''))

    # Legible as itself, which for a figure sharing a line with four
    # diagnostics is not the same as being present. Set in the same grey at the
    # same weight, "12s ago" and "1517ms" are two of five `·`-separated
    # fragments and the eye has to read the line to find the one it wanted.
    aged = fresh.get('age') or {}
    ok_('the age has an element of its own', bool(aged))
    if aged:
        ok_('...at the front of the line', aged.get('first'))
        ok_('...heavier than the diagnostics beside it (%s vs %s)'
            % (aged.get('weight'), aged.get('lineWeight')),
            (aged.get('weight') or 0) > (aged.get('lineWeight') or 0))
        ok_('...and not in their grey (%s vs %s)'
            % (aged.get('colour'), aged.get('lineColour')),
            aged.get('colour') and aged.get('colour') != aged.get('lineColour'))
    # ...and it counts on its own, with nothing arriving to make it.
    later = (got.get('aged') or '').strip()
    ok_('the age keeps counting while the page sits still (%r)' % later,
        later.endswith('s ago') and later != '0s ago')

    # The whole point of the notice case: a card whose distance could not be
    # read carries a notice for its entire life, and that is exactly when the
    # raw rate is the only rate there is.
    for panel, _w, _h in PANELS:
        r = got.get('%s uncertain' % panel)
        if not r:
            continue
        ok_('%s: an unreadable distance is still announced' % panel,
            r['warn']['shown'])
        ok_('%s: ...and the raw rate survives the announcement' % panel,
            r['raw']['shown'])
        # There is no net line on this card — no distance trusted means no
        # mileage cost — so hiding the working left an empty box on screen.
        ok_('%s: ...which is the only line there is' % panel,
            not r['net']['there'] or not r['net']['shown'])

finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d dashboard checks passed' % ok)
sys.exit(1 if bad else 0)
