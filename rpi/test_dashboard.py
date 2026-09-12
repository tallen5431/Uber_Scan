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

# A card whose trip leg lost its minutes. Every figure in it is one the card
# really printed — $18.40 and five minutes are each ordinary — so the pair
# clears every check on the figures, and the rate came out over the drive to
# the rider instead of the job: $220.80/hr, green, against a true $12.40. What
# the card also printed is the 7.8 miles beside the minutes that did not read.
UNTIMED = dict(UNCERTAIN, state='doubt', doubt='leg', pay=18.40,
               minutes=5.0, cardMinutes=5.0, billedMinutes=5.0, miles=2.1,
               perHour=220.8, grossPerHour=220.8, whole=False,
               untimedMiles=7.8)

# A card that costs more to drive than it pays. $2.50 over 12.4 miles at the
# IRS rate the README recommends is -$13.24/hr — an ordinary delivery card, not
# a misread, and the shape this page has a rule about: "-$10.60", not "$-10.6",
# because a minus wedged between the dollar and the digits is a dash at a
# glance. The headline honoured it and the working line under it did not, so the
# same loss appeared twice on one screen and one of them read as a gain.
LOSS = dict(UNCERTAIN, state='no', pay=2.50, minutes=28.0, cardMinutes=28.0,
            billedMinutes=28.0, miles=12.4, cost=8.68, perHour=-13.24,
            grossPerHour=5.36, perMile=-1.07, milesUncertain=False,
            uncosted=False, whole=True)

READINGS = {'uncertain': UNCERTAIN, 'deducted': DEDUCTED, 'deadline': DEADLINE,
            'impossible': IMPOSSIBLE, 'untimed': UNTIMED, 'loss': LOSS}

# ...and every field above has to be one the rig actually sends.
#
# These fixtures are hand-written, which is what lets them stage a card the
# camera cannot be made to produce. It also lets them stage a MESSAGE the
# scanner cannot produce, and then every check below is measured against a
# shape that does not exist. `uncosted` was exactly that: the fixture set it,
# live.html's `if (r.uncosted)` branch fired here and passed, and scan_pi.emit
# had never put the key on the wire — so the "rate is a ceiling" line this file
# claims to have verified had never once appeared in the car, on 26% of the
# driver's offers.
#
# Read off emit()'s own source rather than by calling it, because calling it
# needs a tracker, a scanner and a camera. A key here that emit does not write
# is a fixture inventing a field; the reverse is fine, since a fixture need not
# exercise everything.
def _emitted_keys():
    import re
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'scan_pi.py')).read()
    start = src.index('def emit(rate, parsed, ms')
    body = src[start:src.index('\ndef ', start + 10)]
    return set(re.findall(r"^\s{8}'([a-zA-Z_]+)':", body, re.M))

DRIVER = r'''
const { chromium } = require('playwright');
const [base, panelsJson, readingsJson, framesJson] = process.argv.slice(2);
const FRAMES = JSON.parse(framesJson || '{}');
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

// The picture the rig sends once it has found the phone: portrait, and the
// only shape the page lays out as a phone. Nothing on this test server writes
// a frame, and without one the page is in the scene layout, which is not the
// one a driver is looking at.
const phoneFrame = async (page) => {
  if (!FRAMES.portrait) return false;
  await page.route('**/api/frame.*', (route) => route.fulfill({
    status: 200, contentType: 'image/jpeg', body: Buffer.from(FRAMES.portrait, 'base64') }));
  return true;
};
const framed = (page) => page.waitForFunction(
  () => document.getElementById('view').naturalWidth > 0, null, { timeout: 10000 }).catch(() => {});

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
  // Where the driver is, so a step that never settles — a click on a button
  // that is not there waits thirty seconds; a page that never answers waits
  // for ever — is reported as a skip naming the section, rather than as a
  // suite that hung until the runner's own timeout killed it in silence.
  let stage = 'start';
  setTimeout(() => {
    console.log(JSON.stringify({ skip: 'the driver hung in "' + stage + '"' }));
    process.exit(2);
  }, 300000).unref();
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
      // How old the reading is, and the diagnostics beside it. These are two
      // different questions sharing one line, and the 3.5" hat wants only one
      // of them — so they are measured separately on every panel.
      slot.age = await page.evaluate(LOOK, '#detail .age');
      slot.diag = await page.evaluate(LOOK, '#detail .diag');
      // Inside the CARD, not merely inside the screen. LOOK answers against the
      // viewport, and the verdict is a centred flex column inside a box the
      // grid has already sized — so content that does not fit spills out of
      // both ends of the card while still landing on the glass. Asked against
      // the window alone, a verdict label painted across the top border of its
      // own panel passes; asked against the box, it does not. This is the same
      // question `inVerdict` asks of the stack line, which is the only part of
      // this card that was ever asked it.
      // Whether the reason for the doubt can be read without scrolling for it.
      //
      // The line above this one is what stops a long notice taking the verdict
      // with it, and it does that by letting the notice scroll — which is the
      // right trade and a poor thing to rely on from the driving seat. What the
      // 3.5" hat's smaller notice type is FOR is not having to: the three notes
      // an uncertain reading writes are the worst a real card produces, and on
      // every panel they have to fit whole.
      slot.wholeNote = await page.evaluate(() => {
        const w = document.getElementById('warn');
        if (w.hidden) return null;
        if (w.scrollHeight <= w.getBoundingClientRect().height + 1) return true;
        // Not whole — so the rest of it has to be somewhere a driver can get
        // to. Scrolled for real rather than inferred: an overflow:visible box
        // reports a scrollHeight past its own height too, and simply paints
        // the words outside where #app clips them away.
        w.scrollTop = 0;
        w.scrollTop = 9999;
        const moved = w.scrollTop > 0;
        w.scrollTop = 0;
        return moved ? 'scrolls' : false;
      });
      slot.inCard = await page.evaluate(() => {
        const v = document.getElementById('verdict').getBoundingClientRect();
        const over = [];
        ['#verdictLabel', '.rate.big', '#working', '.submetrics', '#places',
         '#stack', '#warn'].forEach((sel) => {
          const e = document.querySelector(sel);
          if (!e) return;
          const r = e.getBoundingClientRect();
          if (r.height === 0) return;
          if (r.top < v.top - 0.5 || r.bottom > v.bottom + 0.5) over.push(sel);
        });
        return over;
      });
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
  stage = 'marking an offer as taken, from the screen the driver is looking at';
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
                               // Net, and with a cost recorded, so the panel
                               // is entitled to say so. Moves with the mark
                               // for the same reason the count does.
                               earned: n === 1 ? 48.4 : 61.9,
                               earnedCost: n === 1 ? 12.0 : 15.5,
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

    // ...and what the button becomes once a destination HAS been read.
    //
    // It used to become the address itself. The bar is a grid of equal columns
    // and there are six or seven of them, so this button is 122px wide on the
    // rig's own panel while a 42-character address needs 238 - it arrived as
    // "1234 Daffodil L...", which is neither a label nor an address anyone can
    // check. There is no width to win: the bar is full.
    await page.evaluate(() => window.__es.push({ dropoff: {
      line: '1234 Daffodil Ln, Powder Springs, GA 30127',
      street: '1234 Daffodil Ln', city: 'Powder Springs',
      state: 'GA', zip: '30127' } }));
    await page.waitForTimeout(200);
    out.destAfterScan = await page.evaluate(() => {
      const el = document.getElementById('dest');
      const r = el.getBoundingClientRect();
      return { text: (el.textContent || '').trim(),
               w: Math.round(r.width),
               clipped: el.scrollWidth > el.clientWidth + 1,
               done: el.classList.contains('done'),
               // The answer has to reach a screen reader too, which cannot see
               // a colour.
               label: el.getAttribute('aria-label') || '',
               title: el.getAttribute('title') || '',
               fits: document.documentElement.scrollWidth
                     <= document.documentElement.clientWidth + 1 };
    });
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

  // --- both jobs at once, and the two things only that line can say --------
  stage = 'both jobs at once, and the two things only that line can say';
  //
  // The stack line had no browser check at all, which is how it shipped as one
  // nowrap ellipsised string with the map link appended as a child. Everything
  // this line alone can tell you sat at the END of that string, so it was the
  // first thing cut; and an inline-block child of a clipped box is laid out
  // past the edge rather than wrapped, so at 480x320 the link's box started
  // 235px outside its parent and elementFromPoint at its centre found nothing.
  //
  // Measured on the glass at both panels the rig is actually used on.
  for (const panel of [['800x480', 800, 480], ['480x320', 480, 320]]) {
    const ctx = await browser.newContext({
      viewport: { width: panel[1], height: panel[2] }, deviceScaleFactor: 1,
    });
    const page = await ctx.newPage();
    await page.addInitScript(STUB.replace('REPLAY_BODY', 'null'));
    await phoneFrame(page);
    await page.goto(base + '/live.html', { waitUntil: 'domcontentloaded' })
              .catch(() => {});
    await page.waitForFunction('window.__es !== undefined', null,
                               { timeout: 10000 }).catch(() => {});
    await framed(page);
    // The worst realistic shape: a range, the "beats finishing alone" clause,
    // a geography verdict, and a route link — everything competing for the row.
    await page.evaluate((r) => window.__es.push(r),
      Object.assign({}, READINGS.deducted, {
        holding: { pay: 12, minutes: 30,
                   dropoff: 'Cochran Ridge Rd & Jewel Cole Rd, Hiram' },
        stack: { pay: 16.8, minMinutes: 30, maxMinutes: 50, worst: 20.2,
                 best: 33.6, state: 'warn', sure: true, ends: 'elsewhere',
                 route: 'https://www.google.com/maps/dir/?api=1&origin=A'
                      + '&destination=B&travelmode=driving' } }));
    await page.waitForTimeout(200);
    out['stack ' + panel[0]] = await page.evaluate(() => {
      const row = document.querySelector('#stack');
      const inside = (el) => {
        if (!el) return null;
        const r = el.getBoundingClientRect();
        const p = row.getBoundingClientRect();
        const hit = document.elementFromPoint(Math.round(r.left + r.width / 2),
                                              Math.round(r.top + r.height / 2));
        return { there: true,
                 inside: r.right <= p.right + 1 && r.left >= p.left - 1
                         && r.bottom <= p.bottom + 1 && r.top >= p.top - 1,
                 reachable: !!hit && (hit === el || el.contains(hit)),
                 text: (el.textContent || '').trim() };
      };
      const sum = document.querySelector('#stack .sum');
      // The address, measured against its own line box. A flex item with
      // `overflow: hidden` has no automatic minimum size, so in the verdict
      // column both of these were shrinkable to NOTHING while the rate block
      // beside them kept every pixel.
      const pl = document.querySelector('#places');
      const plcs = pl && getComputedStyle(pl);
      const line = plcs
        ? (parseFloat(plcs.lineHeight) || parseFloat(plcs.fontSize) * 1.2) : 0;
      return {
        shown: !row.hidden,
        places: pl ? { h: Math.round(pl.getBoundingClientRect().height),
                       line: Math.round(line),
                       shown: !pl.hidden } : null,
        rowClipped: row.scrollWidth > row.clientWidth + 1,
        // ...and inside the verdict's own box, not painted over its bottom
        // border and on into whatever is drawn below. On the 3.5" hat the
        // phone layout left the verdict 192px for 225px of content, and this
        // row — the one on the panel a driver presses — was under the
        // connection line.
        inVerdict: (() => {
          const v = document.getElementById('verdict').getBoundingClientRect();
          const r = row.getBoundingClientRect();
          return r.bottom <= v.bottom - 1 && r.top >= v.top + 1;
        })(),
        // The half that is MEANT to give way, and it has to actually be doing
        // so or the checks below prove nothing about priority.
        sumEllipsised: !!sum && sum.scrollWidth > sum.clientWidth + 1,
        // The other end of the same box. A pair is the tallest this card ever
        // gets, and the verdict centres what will not fit — so the row below
        // going over the bottom border and the headline going off the TOP are
        // one fault measured twice, and only the first half was ever asked.
        onGlass: (() => {
          const seen = (sel) => {
            const e = document.querySelector(sel);
            if (!e) return false;
            const r = e.getBoundingClientRect();
            return r.height > 0 && r.top >= 0 && r.bottom <= window.innerHeight + 1;
          };
          return seen('#verdictLabel') && seen('#perHour');
        })(),
        ends: inside(document.querySelector('#stack .ends')),
        link: inside(document.querySelector('#stack .maplink')),
        fits: document.documentElement.scrollWidth
              <= document.documentElement.clientWidth + 1
           && document.documentElement.scrollHeight
              <= document.documentElement.clientHeight + 1,
      };
    });

    // ...and the same row when the rig has NOTHING to say about where the two
    // jobs end, which is about half of real pairs.
    //
    // The two silences drew the identical line: "I checked and found nothing to
    // warn you about" and "I have no idea". The range is still coloured by the
    // pay arithmetic, so an unchipped green row read at a glance as a pair that
    // came back clean — the exact wrong "these end near each other" this rig
    // prices at an hour of driving and a rating.
    const whole = (el) => {
      if (!el) return null;
      const r = el.getBoundingClientRect();
      const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      const chars = []; let n;
      while ((n = walk.nextNode())) {
        const rg = document.createRange();
        for (let i = 0; i < n.length; i++) {
          rg.setStart(n, i); rg.setEnd(n, i + 1);
          const c = rg.getBoundingClientRect();
          if (!c.width && !c.height) continue;
          chars.push({ ch: n.data[i],
                       ok: c.left >= r.left - 0.5 && c.right <= r.right + 0.5 });
        }
      }
      return chars.filter((c) => c.ok).map((c) => c.ch).join('');
    };
    // No address on the order in the car, which is the half a driver can do
    // something about: 106 of this driver's 604 cards print a merchant and no
    // address, and the dropoff button in the bar is what rescues them.
    await page.evaluate((r) => window.__es.push(r),
      Object.assign({}, READINGS.deducted, {
        holding: { pay: 12, minutes: 30, dropoff: null },
        stack: { pay: 16.8, minMinutes: 30, maxMinutes: 50, worst: 20.2,
                 best: 33.6, state: 'warn', sure: true, ends: null,
                 route: null } }));
    await page.waitForTimeout(250);
    out['unknown ' + panel[0]] = await page.evaluate((src) => {
      const seen = new Function('return (' + src + ')')();
      const chip = document.querySelector('#stack .ends');
      const dest = document.getElementById('dest');
      return {
        chip: chip ? (chip.textContent || '').trim() : null,
        chipWhole: seen(chip),
        chipColour: chip ? getComputedStyle(chip).color : null,
        // The range is what this row exists for and has to survive the chip.
        sumSeen: seen(document.querySelector('#stack .sum')),
        destClass: dest ? dest.className : null,
        fits: document.documentElement.scrollWidth
              <= document.documentElement.clientWidth + 1,
      };
    }, whole.toString());
    // ...and the same silence when the HELD order does have an address, so the
    // button is not asking to be pressed for something it cannot fix.
    await page.evaluate((r) => window.__es.push(r),
      Object.assign({}, READINGS.deducted, {
        holding: { pay: 12, minutes: 30, dropoff: 'Oak Ln, Marietta' },
        stack: { pay: 16.8, minMinutes: 30, maxMinutes: 50, worst: 20.2,
                 best: 33.6, state: 'warn', sure: true, ends: null,
                 route: null } }));
    await page.waitForTimeout(250);
    out['known-end ' + panel[0]] = await page.evaluate(() => {
      const dest = document.getElementById('dest');
      const chip = document.querySelector('#stack .ends');
      return { destClass: dest ? dest.className : null,
               chip: chip ? (chip.textContent || '').trim() : null };
    });

    // A notice longer than any card produces today, on the smallest panel.
    //
    // The three the `uncertain` fixture stacks are 139px of prose in a 191px
    // verdict, and smaller type alone is enough for those — which would leave
    // the rule that lets the notice SHRINK doing nothing any input could show.
    // The rule is not there for today's three. It is there because notices are
    // sentences and the set of them grows: this page has added four since it
    // was written, and the verdict is a centred column, so the first one that
    // does not fit does not push the prose out of the bottom of the card, it
    // slides the headline and the verdict out of the top. That failure is
    // silent and it is on the screen with the least room to spare.
    //
    // Written straight into the element because what is being measured is the
    // stylesheet, not the sentence: any notice this long has the same shape.
    await page.evaluate(() => {
      const w = document.getElementById('warn');
      w.hidden = false;
      w.textContent = ('Distance unreadable — rate is a ceiling. ').repeat(12);
    });
    await page.waitForTimeout(200);
    out['longnote ' + panel[0]] = await page.evaluate(() => {
      const v = document.getElementById('verdict').getBoundingClientRect();
      const w = document.getElementById('warn');
      const r = w.getBoundingClientRect();
      const out = [];
      ['#verdictLabel', '.rate.big', '#warn'].forEach((sel) => {
        const e = document.querySelector(sel);
        if (!e) return;
        const b = e.getBoundingClientRect();
        if (b.height === 0) return;
        if (b.top < v.top - 0.5 || b.bottom > v.bottom + 0.5) out.push(sel);
      });
      return {
        over: out,
        // ...and the prose is reachable rather than deleted: what will not fit
        // scrolls. A notice cut with no way to see the rest would be this
        // page's own second-worst fault instead of its worst.
        //
        // Scrolled for real, not inferred from scrollHeight. A box with
        // `overflow: visible` reports a scrollHeight past its own height too —
        // it simply paints outside instead — so the arithmetic answers yes for
        // both the version that works and the version that loses the words.
        // Asking the box to move and looking at where it went cannot.
        scrolls: (() => {
          w.scrollTop = 0;
          w.scrollTop = 9999;
          const moved = w.scrollTop > 0;
          w.scrollTop = 0;
          return moved;
        })(),
        cut: Math.round(w.scrollHeight - r.height),
        fits: document.documentElement.scrollHeight
              <= document.documentElement.clientHeight + 1,
      };
    });

    await page.close();
    await ctx.close();
  }

  // --- a rate the rig could not cost, and one that cannot be true ----------
  stage = 'a rate the rig could not cost, and one that cannot be true';
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

    // A rate below zero, which is the one case where HOW a number is written
    // decides whether it is read as a loss or a gain.
    await page.evaluate((r) => window.__es.push(r), READINGS.loss);
    await page.waitForTimeout(200);
    out.loss = await page.evaluate(() => ({
      rate: (document.querySelector('#perHour') || {}).textContent || '',
      // Every figure on the glass at once, so a "$-" anywhere is caught
      // wherever it is written rather than only where it was looked for.
      //
      // Walked as text NODES, skipping script and style: body.textContent
      // includes the page's own inline source, and this page's source contains
      // the string "$-10.6" inside the comment explaining why it must never
      // render one. The first version of this check failed on that comment,
      // which is the check measuring the wrong thing rather than the page
      // being wrong.
      body: (function () {
        var walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
          acceptNode: function (n) {
            var tag = n.parentNode && n.parentNode.nodeName;
            return (tag === 'SCRIPT' || tag === 'STYLE')
              ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
          }
        });
        var out = [], node;
        while ((node = walk.nextNode())) out.push(node.nodeValue);
        return out.join(' ').replace(/\s+/g, ' ');
      })(),
    }));

    // ...and the third kind, where no figure is wrong and the reading is
    // nonetheless not the offer: the card printed two legs and only one of
    // them was timed.
    await page.evaluate((r) => window.__es.push(r), READINGS.untimed);
    await page.waitForTimeout(200);
    out.untimed = {
      label: await page.evaluate(LOOK, '#verdictLabel'),
      rate: await page.evaluate(LOOK, '#perHour'),
      pay: await page.evaluate(LOOK, '#vPay'),
      min: await page.evaluate(LOOK, '#vMin'),
      warn: await page.evaluate(LOOK, '#warn'),
    };
    await page.close();
    await ctx.close();
  }

  // --- Re-find, and the two things it may actually have done ---------------
  stage = 'Re-find, and the two things it may actually have done';
  //
  // Pressing Re-find is a driver saying the outline is wrong. The scanner may
  // refuse — a hand-drawn box is only given up for a screen it can see, and
  // with --no-track there are no corners to move — and the refusal used to go
  // to the log and nowhere else, while this button went on to say
  // "re-finding". So a refused press and a press that worked looked identical
  // from the seat, and the driver went back to driving through corners they
  // had just rejected.
  {
    const ctx = await browser.newContext({
      viewport: { width: 800, height: 480 }, deviceScaleFactor: 1,
    });
    const page = await ctx.newPage();
    await page.addInitScript(STUB.replace('REPLAY_BODY', 'null'));
    await page.route('**/api/recalibrate', (route) => route.fulfill({
      status: 200, contentType: 'application/json', body: '{"ok":true}',
    }));
    await page.goto(base + '/live.html', { waitUntil: 'domcontentloaded' })
              .catch(() => {});
    await page.waitForFunction('window.__es !== undefined', null,
                               { timeout: 10000 }).catch(() => {});
    await page.evaluate(() => window.__es.push(
      { phase: 'scanning', message: '' }));
    await page.evaluate(() => window.__es.push(
      { alive: true, at: Date.now(), tooBright: false, tooDim: false,
        refindRefused: null }));
    await page.waitForTimeout(150);
    out.refind = { before: await page.evaluate(LOOK, '#warn') };

    await page.click('#reset');
    await page.waitForTimeout(250);
    // All the POST proves is that a file was touched. It has not reached the
    // scanner and cannot speak for it.
    out.refind.pressed = await page.evaluate(LOOK, '#reset');

    // The scanner's answer, on the beat — which is the only channel that runs
    // in this state, because "no screen to find" is also "no reading coming".
    const REFUSED = 'Re-find found no screen — the box you drew is still in '
                  + 'use. Try again with the phone lit and a darker border '
                  + 'around it.';
    await page.evaluate((m) => window.__es.push(
      { alive: true, at: Date.now(), tooBright: false, tooDim: false,
        refindRefused: m }), REFUSED);
    await page.waitForTimeout(200);
    out.refind.refused = await page.evaluate(LOOK, '#warn');

    // It is not a blip on one beat: it stands until a press actually works,
    // because the state it describes — corners the driver rejected, still in
    // use — stands until then too.
    await page.evaluate((m) => window.__es.push(
      { alive: true, at: Date.now(), tooBright: false, tooDim: false,
        refindRefused: m }), REFUSED);
    await page.waitForTimeout(200);
    out.refind.stillRefused = await page.evaluate(LOOK, '#warn');

    // ...and a reading arriving does not bury it either: the notes on a
    // reading are rendered by a different branch of the same function.
    await page.evaluate((r) => window.__es.push(r), READINGS.deducted);
    await page.waitForTimeout(200);
    out.refind.onReading = await page.evaluate(LOOK, '#warn');

    await page.evaluate(() => window.__es.push(
      { alive: true, at: Date.now(), tooBright: false, tooDim: false,
        refindRefused: null }));
    await page.waitForTimeout(200);
    out.refind.cleared = await page.evaluate(LOOK, '#warn');
    await page.close();
    await ctx.close();
  }

  // --- the connection line and the bar, against the server's snapshot ------
  stage = 'the connection line and the bar, against the server\'s snapshot';
  //
  // What /api/status says at load is a snapshot, and four things on this
  // page believed it for the rest of the shift, or believed the stream over
  // it in the one place they should not have.
  {
    const page = await browser.newContext({ viewport: { width: 800, height: 480 } }).then((c) => c.newPage());
    await page.addInitScript(STUB.replace('REPLAY_BODY', 'null'));
    const reading = { ready: true, state: 'go', perHour: 30.0, grossPerHour: 36.0,
                      pay: 10.0, minutes: 20.0, miles: 4.0, cost: 1.4, target: 25, band: 15 };
    // A snapshot taken while the scanner was being restarted: not running,
    // last heard from a moment ago, last reading fifteen seconds old, an
    // order in the car.
    await page.route('**/api/status*', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ ok: true, status: 'scanning',
        scanner: { enabled: true, running: false, error: 'exited' },
        last: reading, lastAgeMs: 15000, heardAgeMs: 900,
        offer: { id: 'o-1', pay: 10.0, minutes: 20.0, billedMinutes: 20.0, miles: 4.0, cost: 1.4 },
        offerAgeMs: 15000,
        holding: { pay: 9.0, minutes: 20.0, dropoff: null, dropoffScanned: false } }),
    }));
    await page.route('**/api/today*', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ offers: 3, counted: 3, setAside: 0, took: 1, median: 20,
                             beforeClock: 0, unreadable: null, rolled: false, clockSet: true }) }));
    const marks = [];
    await page.route('**/api/offers/mark', async (route) => {
      marks.push(JSON.parse(route.request().postData() || '{}'));
      await route.fulfill({ status: 500, contentType: 'application/json',
                            body: JSON.stringify({ ok: false, error: 'disk full' }) });
    });
    await page.route('**/api/dropoff', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ ok: true, holding: false }) }));
    await page.route('**/api/delivered', (route) => route.fulfill({
      status: 500, contentType: 'application/json', body: JSON.stringify({ ok: false }) }));
    await phoneFrame(page);
    stage = 'snap: load';
    await page.goto(base + '/live.html', { waitUntil: 'domcontentloaded' }).catch(() => {});
    await page.waitForFunction('window.__es !== undefined', null, { timeout: 10000 }).catch(() => {});
    await framed(page);
    await page.waitForTimeout(600);
    // The stub's socket never opens on its own; the page treats a socket
    // that has not opened as "reconnecting", which is not what this is
    // about.
    await page.evaluate(() => { if (window.__es && window.__es.onopen) window.__es.onopen(); });
    await page.waitForTimeout(100);
    stage = 'snap: seeded';
    const conn = () => page.evaluate(() => ({
      conn: document.getElementById('conn').textContent.trim(),
      dot: document.getElementById('dot').classList.contains('on') }));
    out.snap = { seeded: await conn() };
    // The stream replays the reading, fifteen seconds old, as it does on
    // every connect. That must not move the heartbeat clock.
    await page.evaluate((r) => window.__es.push(Object.assign(
      { replay: true, ageMs: 15000, holding: { pay: 9.0, minutes: 20.0, dropoff: null } }, r)), reading);
    await page.waitForTimeout(150);
    out.snap.afterReplay = await conn();
    // ...and then the scanner itself speaks, which is the scanner running.
    await page.evaluate(() => window.__es.push({ alive: true }));
    await page.waitForTimeout(150);
    out.snap.afterHeartbeat = await conn();
    // Now the bar. The order is in the car per the snapshot; the reply to
    // ⌖ Dropoff says it no longer is.
    stage = 'snap: dest';
    out.snap.dropBefore = await page.evaluate(() => document.getElementById('drop').hidden);
    out.snap.destBefore = await page.evaluate(() => document.getElementById('dest').hidden);
    await page.evaluate(() => document.getElementById('dest').click());
    await page.waitForTimeout(400);
    out.snap.dropAfterDest = await page.evaluate(() => document.getElementById('drop').hidden);
    stage = 'snap: took';
    await page.click('#took');
    await page.waitForTimeout(500);
    out.snap.tookAfterFail = await page.evaluate(() => ({
      text: document.getElementById('took').textContent.trim(),
      failed: document.getElementById('took').classList.contains('failed') }));
    out.snap.markBody = marks[0] || null;
    // ...and then the NEXT card arrives, which nobody has pressed anything
    // for. A failure belongs to the press that failed; carried onto a later
    // card it asserts a write went wrong on an offer the driver never touched,
    // and the label invites them to retry it — which would write a real mark
    // and a real pairing row for the wrong job.
    stage = 'snap: next card after a failed mark';
    await page.evaluate(() => window.__es.push({
      ready: true, state: 'go', perHour: 30.0, grossPerHour: 36.0, pay: 14.25,
      minutes: 20.0, miles: 4.0, cost: 1.4, target: 25, band: 15,
      offer: { id: 'o-2', pay: 14.25, minutes: 20.0, billedMinutes: 20.0,
               miles: 4.0, cost: 1.4 } }));
    await page.waitForTimeout(200);
    out.snap.tookNextCard = await page.evaluate(() => ({
      text: document.getElementById('took').textContent.trim(),
      failed: document.getElementById('took').classList.contains('failed'),
      title: document.getElementById('took').title || '' }));
    // The same question for the order in the car. A failed Drop must not
    // paint the next order's button as having failed before it is pressed.
    //
    // The order has to be back in the car first: the Dropoff press above
    // already put it down, and a Drop pressed with nothing held is a failure
    // about no order at all, which is a different case from this one.
    stage = 'snap: next hold after a failed drop';
    await page.evaluate(() => window.__es.push({
      ready: true, state: 'go', perHour: 30.0, grossPerHour: 36.0, pay: 14.25,
      minutes: 20.0, miles: 4.0, cost: 1.4, target: 25, band: 15,
      holding: { pay: 9.0, minutes: 20.0, dropoff: null } }));
    await page.waitForTimeout(150);
    await page.evaluate(() => document.getElementById('drop').click());
    await page.waitForTimeout(300);
    out.snap.dropAfterFail = await page.evaluate(() => ({
      text: document.getElementById('drop').textContent.trim(),
      failed: document.getElementById('drop').classList.contains('failed') }));
    // The order that failed to go down is still in the car, and the rig keeps
    // saying so on every reading. That is not a new order, and forgetting the
    // failure there would take the retry away from the one press that needs
    // it — so the label has to survive its own order being re-reported.
    await page.evaluate(() => window.__es.push({
      ready: true, state: 'go', perHour: 30.0, grossPerHour: 36.0, pay: 14.25,
      minutes: 20.0, miles: 4.0, cost: 1.4, target: 25, band: 15,
      holding: { pay: 9.0, minutes: 20.0, dropoff: null } }));
    await page.waitForTimeout(200);
    out.snap.dropSameHold = await page.evaluate(() => ({
      text: document.getElementById('drop').textContent.trim(),
      failed: document.getElementById('drop').classList.contains('failed') }));
    // Carried on a reading, which is the only way a hold ever reaches this
    // page — see the `msg.ready` guard the holding branch sits behind.
    await page.evaluate(() => window.__es.push({
      ready: true, state: 'go', perHour: 30.0, grossPerHour: 36.0, pay: 14.25,
      minutes: 20.0, miles: 4.0, cost: 1.4, target: 25, band: 15,
      holding: { pay: 11.0, minutes: 25.0, dropoff: null } }));
    await page.waitForTimeout(200);
    out.snap.dropNextHold = await page.evaluate(() => ({
      text: document.getElementById('drop').textContent.trim(),
      failed: document.getElementById('drop').classList.contains('failed'),
      hidden: document.getElementById('drop').hidden }));
    // ...and a failure on THIS order sticks to this one. Without the held
    // order being tracked as it changes, a second failure would still be
    // filed against the first order, and the job actually in the car would
    // clear it the moment the rig mentioned it again.
    stage = 'snap: a second failure belongs to the second order';
    await page.evaluate(() => document.getElementById('drop').click());
    await page.waitForTimeout(300);
    await page.evaluate(() => window.__es.push({
      ready: true, state: 'go', perHour: 30.0, grossPerHour: 36.0, pay: 14.25,
      minutes: 20.0, miles: 4.0, cost: 1.4, target: 25, band: 15,
      holding: { pay: 11.0, minutes: 25.0, dropoff: null } }));
    await page.waitForTimeout(200);
    out.snap.dropSecondFail = await page.evaluate(() => ({
      text: document.getElementById('drop').textContent.trim(),
      failed: document.getElementById('drop').classList.contains('failed') }));
    // Set box, then Cancel: the phone view comes back and the preference
    // is not touched.
    out.snap.viewBefore = await page.evaluate(() => ({
      phone: document.body.classList.contains('phoneview'),
      stored: localStorage.getItem('uberscan.liveView') }));
    stage = 'snap: setBox';
    await page.click('#setBox');
    await page.waitForTimeout(200);
    out.snap.viewDrawing = await page.evaluate(() => ({
      phone: document.body.classList.contains('phoneview'),
      stored: localStorage.getItem('uberscan.liveView') }));
    // The view is borrowed for the length of the drawing and may not be given
    // back mid-drag. The guard on Set box checks the view at the moment it is
    // PRESSED and never again, and the toggle used to stay live throughout —
    // so a driver could switch to the phone view with a box half-drawn, and
    // "Read this box" re-checked only that the box was big enough before
    // POSTing it as CAMERA FRAME fractions and answering "box sent" in green.
    // The phone view is one rectangle out of the camera frame, flattened and
    // blown up, so the same drag lands somewhere else entirely.
    stage = 'snap: the view is locked while drawing';
    out.snap.lockedWhileDrawing = await page.evaluate(() => {
      var b = document.getElementById('viewMode');
      var was = document.body.classList.contains('phoneview');
      b.click();                                   // the driver tries anyway
      return { disabled: b.disabled, title: b.title || '',
               phoneBefore: was,
               phoneAfter: document.body.classList.contains('phoneview') };
    });
    await page.waitForTimeout(150);

    stage = 'snap: cancel';
    await page.click('#drawCancel');
    await page.waitForTimeout(200);
    out.snap.viewAfter = await page.evaluate(() => ({
      phone: document.body.classList.contains('phoneview'),
      stored: localStorage.getItem('uberscan.liveView'),
      // ...and given back once the drawing ends, or the button is simply
      // broken from then on.
      viewEnabled: !document.getElementById('viewMode').disabled }));
    await page.close();
  }
  // --- a connection that opens and never closes ---------------------------
  stage = 'a connection that opens and never closes';
  //
  // Not a refusal and not an outage: a socket the rig accepts and never
  // answers on, which is what a car hotspot the Pi is associated with but
  // cannot reach through actually produces. `fetch` has no timeout of its own,
  // so the promise stays pending and nothing after it runs — and every control
  // on the bar cleared its busy flag in the `.then()` after the fetch. One
  // press and the button sat at "…", disabled, for the rest of the shift, with
  // nothing saying why and no way back but reloading the page.
  //
  // All five at once and one wait, because the wait is the real twenty seconds
  // this page uses and there is no reason to spend it five times. ⌖ Dropoff
  // needs the longest: its own thirteen-second window starts only once the
  // fetch settles, which under this fault it never did.
  {
    const ctx = await browser.newContext({
      viewport: { width: 800, height: 480 }, deviceScaleFactor: 1,
    });
    const page = await ctx.newPage();
    // The deadline is twenty seconds and ⌖ Dropoff's own window is thirteen
    // more, and waiting those out for real would put this driver past the
    // watchdog that keeps a hung section from eating the whole run. The page's
    // clock is moved instead: the timers are the real ones, at their real
    // settings, and only the waiting is skipped.
    await page.clock.install();
    await page.addInitScript(STUB.replace('REPLAY_BODY', 'null'));
    await phoneFrame(page);
    // Every door this page pushes at, held open and never answered. `/api/today`
    // and `/api/status` are deliberately NOT among them: the figures freezing
    // is a different fault with its own checks, and leaving them working keeps
    // this about the bar.
    for (const path of ['**/api/offers/mark', '**/api/delivered',
                        '**/api/dropoff', '**/api/recalibrate', '**/api/crop']) {
      await page.route(path, () => { /* never fulfilled, never aborted */ });
    }
    await page.goto(base + '/live.html', { waitUntil: 'domcontentloaded' }).catch(() => {});
    await page.waitForFunction('window.__es !== undefined', null, { timeout: 10000 }).catch(() => {});
    await framed(page);
    // An offer on record and an order in the car, so Took, Drop and ⌖ Dropoff
    // are all on the bar to be pressed.
    await page.evaluate(() => window.__es.push({
      ready: true, state: 'go', perHour: 30.0, grossPerHour: 36.0, pay: 10.0,
      minutes: 20.0, miles: 4.0, cost: 1.4, target: 25, band: 15,
      holding: { pay: 9.0, minutes: 20.0, dropoff: null },
      // `offer`, not an `id` on the reading: "Took $10.00?" names the offer on
      // RECORD, which is a different thing from the card on screen and arrives
      // in its own field. Without it the button is hidden and the press below
      // waits for a control that is never going to appear.
      offer: { id: 'o-hang', pay: 10.0, minutes: 20.0, billedMinutes: 20.0,
               miles: 4.0, cost: 1.4 } }));
    await page.waitForTimeout(300);
    const barState = () => page.evaluate(() => {
      const one = (id) => {
        const e = document.getElementById(id);
        return { text: (e.textContent || '').trim(), off: !!e.disabled,
                 hidden: !!e.hidden };
      };
      return { took: one('took'), drop: one('drop'), dest: one('dest'),
               reset: one('reset'), crop: one('drawUse') };
    });
    // Bounded, and the failure kept rather than thrown: a control that is not
    // there is a result, and an unbounded click on one spends the whole
    // driver's budget waiting for it. The same note as on the view toggle.
    const press = (id) => page.click(id, { timeout: 4000 })
      .then(() => true, () => false);
    out.hung = { pressedOk: {} };
    for (const id of ['#took', '#drop', '#dest', '#reset']) {
      out.hung.pressedOk[id] = await press(id);
    }
    // The crop control needs a box drawn before it will send anything, which
    // is a drag on the picture — done through the page's own pointer events so
    // the box is the one a driver would have made.
    await press('#setBox');
    await page.waitForTimeout(200);
    const wrap = await page.locator('#viewWrap').boundingBox();
    if (wrap) {
      await page.mouse.move(wrap.x + wrap.width * 0.3, wrap.y + wrap.height * 0.3);
      await page.mouse.down();
      await page.mouse.move(wrap.x + wrap.width * 0.7, wrap.y + wrap.height * 0.7,
                            { steps: 8 });
      await page.mouse.up();
      await page.waitForTimeout(150);
      out.hung.pressedOk['#drawUse'] = await press('#drawUse');
    }
    await page.waitForTimeout(400);
    out.hung.pressed = await barState();
    out.hung.drew = !!wrap;
    // Twenty seconds for the deadline, thirteen more for ⌖ Dropoff's own
    // window, and a second of slack.
    await page.clock.runFor(34500);
    await page.waitForTimeout(400);
    out.hung.after = await barState();
    await page.close();
    await ctx.close();
  }

  // The replay on its own, against a snapshot that says the scanner IS
  // running — the one above says it is not, and that line takes precedence
  // over the staleness one, so it could not show this.
  {
    stage = 'snap: replay alone';
    const page = await browser.newContext({ viewport: { width: 800, height: 480 } }).then((c) => c.newPage());
    await page.addInitScript(STUB.replace('REPLAY_BODY', 'null'));
    const reading = { ready: true, state: 'go', perHour: 30.0, grossPerHour: 36.0,
                      pay: 10.0, minutes: 20.0, miles: 4.0, cost: 1.4, target: 25, band: 15 };
    await page.route('**/api/status*', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ ok: true, status: 'scanning',
        scanner: { enabled: true, running: true, error: null },
        last: reading, lastAgeMs: 15000, heardAgeMs: 900, offer: null, holding: null }) }));
    await page.route('**/api/today*', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ offers: 0, counted: 0, setAside: 0, took: 0,
                             beforeClock: 0, unreadable: null, rolled: false, clockSet: true }) }));
    await page.goto(base + '/live.html', { waitUntil: 'domcontentloaded' }).catch(() => {});
    await page.waitForFunction('window.__es !== undefined', null, { timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(600);
    await page.evaluate(() => { if (window.__es && window.__es.onopen) window.__es.onopen(); });
    await page.evaluate((r) => window.__es.push(Object.assign({ replay: true, ageMs: 15000 }, r)), reading);
    await page.waitForTimeout(150);
    out.replayAlone = await page.evaluate(() => ({
      conn: document.getElementById('conn').textContent.trim(),
      dot: document.getElementById('dot').classList.contains('on') }));
    await page.close();
  }

  // --- the phone view is for a picture of a phone ---------------------------
  //
  // On its first boot the rig writes a landscape scene while it aims, and the
  // page lands in the phone view. Laid out as a phone that picture squeezed
  // the verdict to 153px and the bar's buttons to 24px at 800x480.
  for (const shape of Object.keys(FRAMES)) {
    stage = 'frame: ' + shape;
    const page = await browser.newContext({ viewport: { width: 800, height: 480 } }).then((c) => c.newPage());
    await page.addInitScript(STUB.replace('REPLAY_BODY', 'null'));
    await page.route('**/api/status*', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ ok: true, status: 'aim',
        scanner: { enabled: true, running: true, error: null },
        last: null, lastAgeMs: null, heardAgeMs: 900, offer: null, holding: null }) }));
    await page.route('**/api/today*', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ offers: 0, counted: 0, setAside: 0, took: 0,
                             beforeClock: 0, unreadable: null, rolled: false, clockSet: true }) }));
    await page.route('**/api/frame.*', (route) => route.fulfill({
      status: 200, contentType: 'image/jpeg', body: Buffer.from(FRAMES[shape], 'base64') }));
    await page.goto(base + '/live.html', { waitUntil: 'domcontentloaded' }).catch(() => {});
    await page.waitForFunction(() => document.getElementById('view').naturalWidth > 0,
                               null, { timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(300);
    out['frame ' + shape] = await page.evaluate(() => ({
      phoneMode: document.getElementById('viewMode').getAttribute('aria-pressed'),
      phoneLayout: document.body.classList.contains('phoneview'),
      verdictW: Math.round(document.getElementById('verdict').getBoundingClientRect().width),
      imgW: document.getElementById('view').naturalWidth,
      imgH: document.getElementById('view').naturalHeight,
      note: document.getElementById('viewNote').textContent.trim() }));
    await page.close();
  }

  // --- the shift line when the figures cannot be trusted -------------------
  stage = 'the shift line when the figures cannot be trusted';
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
    // One job taken whose mileage cost more than it paid.
    ['negative', { offers: 2, counted: 2, setAside: 0, took: 1, median: 9,
                   earned: -1.25, earnedCost: 5.25, beforeClock: 0,
                   unreadable: null, rolled: false, clockSet: true }, 200],
    // ...and a whole stretch of them, so the MEDIAN itself is below zero. A
    // rig with the IRS rate set and a run of short, far offers gets here, and
    // this line wrote "$-12/hr" — the shape the page has a comment refusing.
    ['redshift', { offers: 4, counted: 4, setAside: 0, took: 2, median: -12,
                   earned: -8.40, earnedCost: 14.0, beforeClock: 0,
                   unreadable: null, rolled: false, clockSet: true }, 200],
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
  stage = '...and when the endpoint stops answering';
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
  stage = 'a page opened against a rig that stopped an hour ago';
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
_sent = _emitted_keys()
ok_('the scanner\'s own payload could be read', len(_sent) > 20)
for _name, _reading in sorted(READINGS.items()):
    _invented = sorted(k for k in _reading if k not in _sent)
    eq('the %s fixture stages only fields the rig sends' % _name, _invented, [])

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

    # Two pictures the rig can send: the landscape scene it writes while it
    # is aiming, and the portrait phone it writes once it has found one.
    FRAMES = {}
    try:
        import base64
        import io
        from PIL import Image
        for name, size in (('landscape', (640, 480)), ('portrait', (573, 1000))):
            buf = io.BytesIO()
            Image.new('RGB', size, (44, 48, 56)).save(buf, format='JPEG', quality=70)
            FRAMES[name] = base64.b64encode(buf.getvalue()).decode('ascii')
    except ImportError:
        # The stack row and the Set-box round trip are measured in the phone
        # layout, which the page only takes for a portrait picture; with no
        # picture to send they would be measured in the scene layout instead,
        # which is not the one in the car.
        skip('no PIL, so there is no frame to put the page in the phone layout')
    driver = os.path.join(work, 'dashboard.js')
    open(driver, 'w').write(DRIVER)
    readings = READINGS
    proc2 = subprocess.run(
        ['node', driver, base, json.dumps(PANELS), json.dumps(READINGS),
         json.dumps(FRAMES)],
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
                                   'placesAfter', 'age', 'diag')
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
            # ...and so is the word above it. The verdict is a centred flex
            # column, so a block of prose too tall for it overflows at BOTH
            # ends: the `uncertain` fixture carries three notices at once, and
            # on the 3.5" hat that put the headline 2px above the glass and the
            # word PASS 25px above it, with #app's `overflow: hidden` cutting
            # them off. Every check here passed — the text was in the DOM, and
            # nothing had asked where it landed.
            ok_('%s: ...and the word above it, which is the verdict' % where,
                r['verdict']['shown'])
            eq('%s: ...and nothing in the card hangs outside it' % where,
               r.get('inCard'), [])
            # The `uncertain` fixture is the only one of the three that writes a
            # notice, and it writes all three at once — the worst a real card
            # produces. On a panel with room it reads whole.
            #
            # On the 3.5" hat it does not, and that is measured rather than
            # hoped: with the figures already hidden the card has 83px left and
            # the three notes are 127 of them at the hat's smaller 11px type,
            # four lines over. Nothing available closes a gap that size — the
            # headline giving up as much again as it gives a pair is worth 18 —
            # so on this one panel the reason for the doubt is a line and a bit
            # plus a scroll. The check says which panel does which, so that the
            # day one of them changes, it is a failure and not a discovery.
            if r.get('wholeNote') is not None:
                # Whole, or scrollable. Never cut.
                ok_('%s: ...and the reason for the doubt is all reachable'
                    % where, r['wholeNote'] in (True, 'scrolls'))
                if key == 'uncertain':
                    eq('%s: ...reading whole on a panel with the room for it, '
                       'and by scrolling on the one without' % where,
                       r['wholeNote'], 'scrolls' if panel == '480x320' else True)

            # --- how old the reading is, on every panel --------------------
            #
            # A driver watching a phone through this page is asking one question
            # continuously: do these numbers belong to the card in front of me,
            # or to the one before it? The age is the whole answer, and it is
            # not derivable from anything else on the screen.
            #
            # The 3.5" hat had it hidden. `#detail` carries the age AND the
            # diagnostics — the read time, the leg count, the tracker's drift —
            # and the hat's stylesheet reclaimed the line by hiding the block,
            # which is a fair trade for the diagnostics and a bad one for the
            # age. The same rule also took the two sentences the no-card branch
            # writes into that block: "nothing from the scanner for 40s — it may
            # have stopped", and the instruction for aiming the mount. So the
            # smallest screen, the one a driver can work out the least from, was
            # the only one that could not tell a stopped scanner from a quiet
            # one. They are separate elements now and this asks for them
            # separately.
            ok_('%s: how old the reading is, is on the glass' % where,
                r['age']['shown'])
            ok_('%s: ...as a time and not a blank' % where,
                'ago' in r['age']['text'] or 'just now' in r['age']['text'])
            # ...and the half that genuinely has no room on the hat does give
            # way there, or this is just the old block back under a new name.
            if panel == '480x320':
                ok_('%s: ...while the diagnostics beside it stand down' % where,
                    not r['diag']['shown'])
            else:
                ok_('%s: ...with the diagnostics beside it' % where,
                    r['diag']['shown'])
                ok_('%s: ...which say how long the read took' % where,
                    'ms' in r['diag']['text'])

            ok_('%s: the panel still fits' % where, r['fits'])

    # --- marking an offer as taken, from the driving screen --------------
    idle = got.get('tookIdle') or {}
    offered = got.get('tookOffered') or {}
    gone = got.get('tookAfterCard') or {}
    marked = got.get('tookMarked') or {}
    undone = got.get('tookUndone') or {}
    nxt = got.get('tookNext') or {}
    posted = got.get('tookPosted') or []

    # --- a connection that opens and never closes ------------------------
    #
    # The failure this page is bolted into a car for. `fetch` has no timeout of
    # its own, so a socket that is accepted and never answered on leaves the
    # promise pending for ever — and every control on the bar cleared its busy
    # flag in the `.then()` after the fetch. One press on a bad connection and
    # the button sat at "…", disabled, for the rest of the shift.
    hung = got.get('hung') or {}
    ok_('the bar was pressed against a connection that never answers',
        bool(hung.get('pressed')))
    if hung.get('pressed'):
        pressed, after = hung['pressed'], hung.get('after') or {}
        # Each control in turn, because they have five different busy states
        # and four different ways of showing one.
        ok_('pressing Took while nothing answers puts it to work',
            pressed['took']['text'] == '…' or pressed['took']['off'])
        ok_('...and it comes back rather than sitting there for the shift',
            after.get('took', {}).get('text') != '…')
        ok_('...saying the record was not made (%r)'
            % (after.get('took', {}).get('text'),),
            'not saved' in (after.get('took', {}).get('text') or '').lower())

        eq('pressing Drop while nothing answers puts it to work',
           pressed['drop']['text'], '…')
        ok_('...and it comes back', after.get('drop', {}).get('text') != '…')
        ok_('...saying the order is still in the car',
            'failed' in (after.get('drop', {}).get('text') or '').lower())

        # ⌖ Dropoff is the slowest: its own thirteen-second window starts only
        # once the fetch settles, and under this fault it never did.
        # ⌖ Dropoff says its busy state in the label rather than by disabling —
        # the bar is a grid of equal columns and there is no width for a second
        # word, so "reading…" IS the disabled state. Asked about `disabled`
        # instead, this check passed over a button stuck at "⌖ reading…" for
        # the rest of the shift.
        eq('pressing Dropoff while nothing answers puts it to work',
           pressed['dest']['text'], '⌖ reading…')
        eq('...and it offers itself again afterwards',
           after.get('dest', {}).get('text'), '⌖ Dropoff')

        eq('pressing Re-find while nothing answers puts it to work',
           pressed['reset']['off'], True)
        ok_('...and it comes back', not after.get('reset', {}).get('off'))

        if hung.get('drew'):
            eq('sending a crop box while nothing answers puts it to work',
               pressed['crop']['off'], True)
            ok_('...and the button is offered again, so the box can be re-sent',
                not after.get('crop', {}).get('off'))

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

        # ...and once a destination is read, the control stays a control.
        scanned = got.get('destAfterScan') or {}
        ok_('the button still says what pressing it does after a scan',
            'Dropoff' in (scanned.get('text') or ''))
        ok_('...rather than becoming the address it read',
            '1234' not in (scanned.get('text') or ''))
        ok_('...unclipped on the panel the rig actually uses',
            not scanned.get('clipped'))
        # The answer is said in colour, because the bar has no width to give.
        ok_('...marked as answered', scanned.get('done'))
        # ...and out loud, because a colour is the only thing that changed.
        ok_('...and said to a screen reader, which cannot see a colour',
            '1234 Daffodil Ln' in (scanned.get('label') or ''))
        ok_('...with the address still readable on the control',
            '1234 Daffodil Ln' in (scanned.get('title') or ''))
        ok_('...and the panel still fits', scanned.get('fits'))

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
           [{'id': n.get('id'), 'accepted': n.get('accepted')} for n in posted],
           [{'id': 'o1', 'accepted': True},
            {'id': 'o2', 'accepted': True},
            {'id': 'o2', 'accepted': False}])
        # ...and carries the offer it names, so a server that has restarted
        # and forgotten the offer can still put the order in the car.
        eq('...each carrying the offer it names',
           [(n.get('offer') or {}).get('id') for n in posted], ['o1', 'o2', 'o2'])

        # It has to be usable in a moving car and must not break the panel.
        for name, slot in (('offered', offered), ('marked', marked)):
            ok_('the control is a real target when %s (%dx%d)'
                % (name, slot.get('w') or 0, slot.get('h') or 0),
                (slot.get('w') or 0) >= 80 and (slot.get('h') or 0) >= 44)
            ok_('...with nothing clipped off it when %s' % name,
                not slot.get('clipped'))
            ok_('...and the panel still fits when %s' % name, slot.get('fits'))

    # --- both jobs at once, on the glass ---------------------------------
    #
    # This line had no browser check at all. It shipped as one nowrap,
    # ellipsised string with the map link appended as a child, and both of the
    # things it alone can say sat at the END of that string: the geography
    # words went first, leaving amber that also means "the range straddles your
    # target", and the link — the one thing on this panel a driver is meant to
    # press — was laid out 235px outside its own box at 480x320, where
    # elementFromPoint found nothing at all.
    for panel in ('800x480', '480x320'):
        row = got.get('stack ' + panel) or {}
        ok_('%s: the stacked figure is shown' % panel, row.get('shown'))
        if not row.get('shown'):
            continue
        ok_('%s: ...and the row itself is not clipped' % panel,
            not row.get('rowClipped'))
        ok_('%s: ...and sits inside the verdict, not over its edge' % panel,
            row.get('inVerdict'))
        # ...without the verdict paying for it out of the other end. A pair is
        # the tallest this card gets, and what does not fit is centred, so
        # anything that buys room for the stack line by leaving the column
        # taller than its box pushes the headline and the word above it off the
        # top of the glass instead. Both halves, or neither is a check.
        ok_('%s: ...with the headline and the word above it still on the glass'
            % panel, row.get('onGlass'))
        # The priority has to be REAL, not just declared: the arithmetic is the
        # half that gives way, and if it is not actually being cut here then the
        # two checks below are passing on a row with room to spare and would say
        # nothing about what happens when there is none.
        ok_('%s: ...with the arithmetic the part that gives way' % panel,
            row.get('sumEllipsised'))
        ends = row.get('ends') or {}
        ok_('%s: where the pair ends survives whole' % panel,
            ends.get('inside'))
        ok_('%s: ...and can be read, not just measured' % panel,
            ends.get('reachable'))
        eq('%s: ...saying which' % panel, ends.get('text'), 'ENDS ELSEWHERE')
        link = row.get('link') or {}
        ok_('%s: the route link is inside its own box' % panel,
            link.get('inside'))
        ok_('%s: ...and can actually be pressed' % panel, link.get('reachable'))
        ok_('%s: ...and the panel still fits' % panel, row.get('fits'))

        # A notice longer than any card writes today. The verdict is a centred
        # column, so prose it cannot hold does not overflow downwards where it
        # would be noticed — it slides the headline and the word above it off
        # the top of the card. The notice is the item that has to give, and on
        # the 3.5" hat what it gives has to still be reachable.
        long_ = got.get('longnote ' + panel) or {}
        eq('%s: a notice too long for the card does not push the verdict out '
           'of it' % panel, long_.get('over'), [])
        ok_('%s: ...and the panel still fits' % panel, long_.get('fits'))
        if panel == '480x320':
            ok_('%s: ...with the part that did not fit scrollable, not '
                'deleted (%spx of it)' % (panel, long_.get('cut')),
                long_.get('scrolls'))

        # The other answer this line can give, which used to be no answer at
        # all: about half of real pairs print too little for the geography to
        # be decided, and the row said nothing and changed nothing.
        blind = got.get('unknown ' + panel) or {}
        eq('%s: a pair with nowhere named says so' % panel,
           blind.get('chip'), 'ENDS ?')
        eq('%s: ...whole, not truncated to a shape' % panel,
           blind.get('chipWhole'), 'ENDS ?')
        # Not one of the three verdict colours, for the reason .verdict.doubt is
        # not: this is a refusal, not a worse "near" or a softer "elsewhere".
        ok_('%s: ...in the colour that means the rig declined (%s)'
            % (panel, blind.get('chipColour')),
            blind.get('chipColour') == 'rgb(201, 182, 242)')
        # ...and the number the row exists for survives the chip taking width.
        ok_('%s: ...with the range still whole beside it (%r)'
            % (panel, blind.get('sumSeen')),
            '/hr' in (blind.get('sumSeen') or ''))
        ok_('%s: ...and the panel still fitting' % panel, blind.get('fits'))
        # The one actionable difference, on the control that acts on it. The
        # order in the car has no address, so every pair judged against it will
        # keep coming back ENDS ? until this button is pressed.
        ok_('%s: the dropoff button asks to be pressed (%r)'
            % (panel, blind.get('destClass')),
            'wanted' in (blind.get('destClass') or ''))
        # ...and not when pressing it would change nothing, which is what stops
        # it being a light that is always on.
        known = got.get('known-end ' + panel) or {}
        eq('%s: ...and still says the geography is unknown' % panel,
           known.get('chip'), 'ENDS ?')
        ok_('%s: ...but stops asking once that end is on record (%r)'
            % (panel, known.get('destClass')),
            'wanted' not in (known.get('destClass') or ''))

        # ...and the address above it, which is the other item in that column
        # with no minimum size. It drew 9px tall for a 15px font on the rig's
        # own panel, and 0px once the stack line grew — the address of the job,
        # on the one screen a driver looks at while deciding, at no height at
        # all. There is no such thing as most of a line.
        pl = row.get('places') or {}
        ok_('%s: the address is shown' % panel, pl.get('shown'))
        ok_('%s: ...at a full line, not squeezed to a sliver (%spx of %spx)'
            % (panel, pl.get('h'), pl.get('line')),
            (pl.get('h') or 0) >= (pl.get('line') or 99) * 0.9)

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

    # --- a loss, written so it reads as one ------------------------------
    #
    # live.html states the rule at line 615 — "-$10.60", not "$-10.6", because
    # a minus sign wedged between the dollar and the digits is a dash at a
    # glance — and honoured it in the headline, in `money`, and on the `earned`
    # figure. The working line under the headline had its own copy of the
    # formatter and did not, so a -$13.24/hr card printed "-$13.2" big and
    # "$-13.2" immediately below it. The shift line's median had the same slip.
    #
    # Reachable on an ordinary card: $2.50 over 12.4 miles at the $0.70 IRS
    # rate the README recommends.
    loss = got.get('loss') or {}
    ok_('the loss reading was measured', bool(loss))
    if loss:
        ok_('a rate below zero is shown as a loss in the headline (%r)'
            % (loss.get('rate') or '').strip(),
            (loss.get('rate') or '').strip().startswith('-$'))
        # The property, asked of the whole screen rather than of one element:
        # nowhere on the glass may a dollar sign be followed by a minus.
        _where = (loss.get('body') or '')
        _at = _where.find('$-')
        ok_('...and nowhere on the screen is a minus written after the dollar (%r)'
            % (_where[max(0, _at - 45):_at + 15] if _at >= 0 else ''),
            _at < 0)
        ok_('...while the figure itself is still there to read',
            '13.2' in (loss.get('body') or ''))

    # The kind where every figure is one the card printed. $18.40 is an
    # ordinary payout and five minutes an ordinary leg; the pair clears
    # SANE_RATE at the ten-minute floor, so nothing about the arithmetic can
    # refuse it. What is wrong is that the five minutes are the drive to the
    # rider and the card also said an hour and twenty-four for the trip —
    # $220.80/hr in green against a true $12.40.
    ut = got.get('untimed') or {}
    ok_('the untimed-leg reading was measured', bool(ut.get('label')))
    if ut.get('label'):
        label = (ut['label'].get('text') or '').strip()
        ok_('a reading missing most of its journey is never an accept (%r)' % label,
            'ACCEPT' not in label)
        ok_('...and points at the time, which is the half that is short',
            'TIME' in label)
        eq('...withholding the rate rather than printing $220.80/hr',
           (ut.get('rate') or {}).get('text'), '--')
        # The figures stay: the driver is holding the same card and is the one
        # who can see the leg the rig could not read.
        ok_('...while the payout it read stays on screen',
            '18.4' in ((ut.get('pay') or {}).get('text') or ''))
        ok_('...and the minutes it was going to divide by',
            '5' in ((ut.get('min') or {}).get('text') or ''))
        # The label has room for three words. A driver who reads only
        # "CHECK THE TIME" learns that a number looks odd, not that the rig is
        # holding a fraction of the job — so the reason goes where there is
        # room for it, with the size of the missing piece in it.
        warn = (ut.get('warn') or {}).get('text') or ''
        ok_('...saying in words what is missing (%r)' % warn[:70],
            'could not time' in warn)
        ok_('...and how much of the journey that was',
            '7.8 mi' in warn)
        ok_('...on the glass, not pushed off it', (ut.get('warn') or {}).get('shown'))

    # --- a Re-find the scanner refused -----------------------------------
    #
    # The one state on this page where the DRIVER has acted and the rig has
    # not. Everything else here is the rig reporting something it saw; this is
    # the rig declining to do a thing it was told to, and until the refusal
    # reached the glass the button said "re-finding" regardless and the driver
    # went on reading offers through corners they had already rejected.
    rf = got.get('refind') or {}
    ok_('the refused re-find was measured', bool(rf))
    if rf:
        eq('nothing is said about re-finding before the button is pressed',
           (rf.get('before') or {}).get('shown'), False)
        # The POST's own promise knows only that a web handler touched a file.
        # It has not spoken to the scanner, so it may not speak for it.
        pressed = ((rf.get('pressed') or {}).get('text') or '').strip()
        ok_('the button claims only what the press proved (%r)' % pressed,
            'asked' in pressed)
        ok_('...and not that anything has been re-found', 'find' not in pressed)
        refused = ((rf.get('refused') or {}).get('text') or '')
        ok_('the scanner\'s refusal reaches the glass (%r)' % refused[:60],
            'no screen' in refused and 'box you drew' in refused)
        ok_('...on the glass, not pushed off it',
            (rf.get('refused') or {}).get('shown'))
        ok_('...and it stands on the next beat, not just the one that brought it',
            'no screen' in ((rf.get('stillRefused') or {}).get('text') or ''))
        # Different branch of render(): the notes on a reading are built
        # separately from the notes shown while there is no reading, and a
        # refused re-find belongs in both. The offer that arrives while the
        # corners are wrong is exactly the offer being read through them.
        ok_('...and survives an offer arriving',
            'no screen' in ((rf.get('onReading') or {}).get('text') or ''))
        ok_('...and goes when the scanner says the next one worked',
            'no screen' not in ((rf.get('cleared') or {}).get('text') or ''))

    # --- the snapshot at load is a snapshot ------------------------------
    sn = got.get('snap') or {}
    ok_('the snapshot was measured', bool(sn))
    if sn:
        # /api/status said the scanner was not running at the moment the page
        # loaded — the seconds of a restart. The stream is the scanner
        # talking, and that wins from then on.
        ok_('a page loaded during a restart says so at first (%r)' % sn['seeded'].get('conn'),
            'not running' in (sn['seeded'].get('conn') or ''))
        # The replay carries the reading's age, not the heartbeat's; the
        # heartbeat was 900ms ago per the snapshot, so nothing is stale.
        ok_('...a replayed reading does not put the scanner fifteen seconds in the past (%r)'
            % sn['afterReplay'].get('conn'),
            'nothing from the scanner' not in (sn['afterReplay'].get('conn') or ''))
        ok_('...and a replay alone is not the scanner running',
            'not running' in (sn['afterReplay'].get('conn') or ''))
        ra = got.get('replayAlone') or {}
        ok_('with the scanner running, a replayed reading leaves the heartbeat clock alone (%r)'
            % ra.get('conn'), ra and 'nothing from the scanner' not in (ra.get('conn') or ''))
        ok_('...and the dot lit', ra.get('dot'))
        ok_('...but a heartbeat is (%r)' % sn['afterHeartbeat'].get('conn'),
            'not running' not in (sn['afterHeartbeat'].get('conn') or ''))
        ok_('...and lights the dot', sn['afterHeartbeat'].get('dot'))
        # The reply to Dropoff says the order is gone; the bar follows it.
        eq('with an order in the car the Drop button is on the bar', sn.get('dropBefore'), False)
        eq('...and goes when the dropoff reply says the order is no longer held',
           sn.get('dropAfterDest'), True)
        # A mark the journal could not take does not look like one nobody made.
        ok_('a mark the journal refused says so on the button (%r)' % sn['tookAfterFail'].get('text'),
            'not saved' in (sn['tookAfterFail'].get('text') or '') and sn['tookAfterFail'].get('failed'))
        eq('...and the mark carried the offer it names, for a server that has forgotten it',
           ((sn.get('markBody') or {}).get('offer') or {}).get('id'), 'o-1')
        # ...but it belongs to that press and that card, and to nothing after.
        # One dropped POST used to make the panel report a failed write on
        # every card for the rest of the shift, on offers nobody had touched,
        # with a title inviting a retry that would have written a real mark
        # against the wrong job.
        nxt = sn.get('tookNextCard') or {}
        ok_('the next card is not reported as a write that failed (%r)' % nxt.get('text'),
            'not saved' not in (nxt.get('text') or ''))
        ok_('...and is not painted as failed', not nxt.get('failed'))
        ok_('...and is offered on its own terms (%r)' % nxt.get('text'),
            '14.25' in (nxt.get('text') or ''))
        ok_('...without inviting a retry of somebody else\'s failure (%r)' % nxt.get('title'),
            'retry' not in (nxt.get('title') or '').lower())
        # The same on the other button: a refused Drop says so...
        fail_drop = sn.get('dropAfterFail') or {}
        ok_('a refused drop says so on its button (%r)' % fail_drop.get('text'),
            'failed' in (fail_drop.get('text') or '').lower() or fail_drop.get('failed'))
        # ...keeps saying it while that same order is still being carried, or
        # the retry the driver needs disappears off the one press that failed.
        same_hold = sn.get('dropSameHold') or {}
        ok_('...and goes on saying it while that order is still in the car (%r)'
            % same_hold.get('text'),
            'failed' in (same_hold.get('text') or '').lower() or same_hold.get('failed'))
        # ...and stops saying it once a different order is in the car.
        nxt_hold = sn.get('dropNextHold') or {}
        ok_('the next order in the car is not reported as a failed drop (%r)'
            % nxt_hold.get('text'), 'failed' not in (nxt_hold.get('text') or '').lower())
        ok_('...nor painted as one', not nxt_hold.get('failed'))
        # ...and a refusal on the order now being carried stays with THAT one.
        second = sn.get('dropSecondFail') or {}
        ok_('a second refusal is filed against the order it happened on (%r)'
            % second.get('text'),
            'failed' in (second.get('text') or '').lower() or second.get('failed'))
        # Set box borrows the scene and gives the phone view back.
        ok_('the page lands in the phone view', sn['viewBefore'].get('phone'))
        ok_('Set box switches to the scene to draw on', not sn['viewDrawing'].get('phone'))
        eq('...without rewriting the remembered view', sn['viewDrawing'].get('stored'), None)
        ok_('...and Cancel brings the phone view back', sn['viewAfter'].get('phone'))

        # The box is drawn on the SCENE and sent as fractions of the camera
        # frame. The phone view is one rectangle out of that frame, flattened
        # and blown up, so the same drag lands somewhere else entirely — and
        # "Read this box" re-checked only that the box was big enough. A box
        # accepted, a quad moved, the scanner reading a patch of car door, and
        # a green "box sent" on the glass.
        lw = sn.get('lockedWhileDrawing') or {}
        ok_('the drawing starts on the scene', lw.get('phoneBefore') is False)
        eq('...and the view cannot be switched back while a box is being drawn',
           lw.get('disabled'), True)
        eq('...so pressing it anyway changes nothing',
           lw.get('phoneAfter'), lw.get('phoneBefore'))
        ok_('...with the button saying why (%r)' % (lw.get('title') or ''),
            'cancel first' in (lw.get('title') or ''))
        # ...and given back afterwards, or the button is broken from then on.
        eq('the view can be switched again once the drawing ends',
           sn['viewAfter'].get('viewEnabled'), True)

    # --- the phone view is for a picture of a phone ------------------------
    land = got.get('frame landscape') or {}
    port = got.get('frame portrait') or {}
    if land and port:
        ok_('the page lands in the phone mode', land.get('phoneMode') == 'true')
        ok_('...and a landscape scene arrived (%rx%r)' % (land.get('imgW'), land.get('imgH')),
            (land.get('imgW') or 0) > (land.get('imgH') or 0))
        ok_('...which is not laid out as a phone', not land.get('phoneLayout'))
        ok_('...so the verdict keeps its width (%rpx)' % land.get('verdictW'),
            (land.get('verdictW') or 0) >= 300)
        ok_('...and the caption says the rig is still finding the phone (%r)' % land.get('note'),
            'finds the phone' in (land.get('note') or ''))
        ok_('a portrait phone is laid out as one', port.get('phoneLayout'))
        ok_('...with the flattened-phone caption', 'flattened' in (port.get('note') or ''))

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
        # What the taken ones were worth. This check used to forbid any dollar
        # total here, and its reason still stands: `pay` is what the card
        # offered, and a GROSS sum beside a net median is the sentence the
        # offers page was corrected for. What is printed now is net — pay less
        # the running cost each row recorded, off the same rows the count comes
        # from, the same rule as the offers page's "took 6 for $48.00" — and
        # says so. "Offered" is still the word that must not appear.
        ok_('...and what they were worth, net, in the day header\'s own words',
            'took 2 for $48 net' in (first.get('text') or ''))
        ok_('...never as what was offered',
            'offered' not in (first.get('text') or ''))
        ok_('...and still only one rate on the line',
            (first.get('text') or '').count('/hr') == 1)
        # The money before the count. The line is one line, cut with an
        # ellipsis where it does not fit, and it does not fit on the 480px
        # hat or a phone: measured against a fortnight of offers, 392px of
        # text in 223px on the hat and 314px in 172px on the phone, and what
        # was cut was the tail — "took 2 for $27 net · median $20/hr", the two
        # figures a driver glances down for. They lead now, so what the
        # ellipsis takes is the count of offers and the set-aside figure.
        text = first.get('text') or ''
        ok_('...with what was taken before how many offers there were',
            'took' in text and 'offers' in text and text.index('took') < text.index('offers'))
        ok_('...and the median before them too',
            '/hr' in text and text.index('/hr') < text.index('offers'))
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
        ok_('...and the money with it',
            'took 3 for $62 net' in (after.get('text') or ''))

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
        # This stub carries no `earned` — it is the shape a server one release
        # behind answers with — and the count has to stand alone as it always
        # did, not print "for $undefined" or "for $NaN".
        ok_('...and a server that sends no total leaves the count alone (%r)'
            % (early.get('text') or '')[-30:],
            'took 1' in (early.get('text') or '')
            and ' for $' not in (early.get('text') or ''))

    # A net below zero, signed the way every other figure on these pages is.
    # The first version printed "$-1".
    neg = got.get('shift_negative') or {}
    ok_('the negative-net state was measured', bool(neg))
    if neg:
        ok_('...and prints the sign before the dollar (%r)' % (neg.get('text') or '')[-24:],
            'took 1 for -$1 net' in (neg.get('text') or ''))
        ok_('...never as $-1', '$-' not in (neg.get('text') or ''))

    # ...and the median, which had its own copy of the same slip. A shift of
    # short, far offers with a running cost set puts this below zero.
    red = got.get('shift_redshift') or {}
    ok_('the below-zero median was measured', bool(red))
    if red:
        ok_('the shift median is signed before the dollar (%r)'
            % (red.get('text') or '')[-34:],
            'median -$12/hr' in (red.get('text') or ''))
        ok_('...never as $-12', '$-' not in (red.get('text') or ''))
        # Whole dollars, which is what this line has always shown: a median
        # read at a glance from the driving seat does not want a decimal.
        ok_('...and still in whole dollars', '-$12.0' not in (red.get('text') or ''))


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
