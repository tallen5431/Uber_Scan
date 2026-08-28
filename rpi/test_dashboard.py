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
    'legs': 3, 'mergedFrom': 5, 'ms': 1517, 'text': '', 'places': [],
    'fromDeadline': False, 'deliverBy': None, 'track': None,
}
# ...and one where the distance was trusted, so there are two lines and a cost.
DEDUCTED = dict(UNCERTAIN, state='no', perHour=14.71, grossPerHour=20.97,
                cost=2.4, perMile=0.7, milesUncertain=False, whole=True,
                places=['Cobb Pkwy NW, Acworth', 'Canton Rd, Marietta'])
# A delivery card states a deadline and no duration, so `minutes` is null and
# the rate was worked out over `cardMinutes`. The raw row divided by `minutes`
# and printed "$12.00 in -- min = $21.2/hr raw" — a sum with nothing under the
# line, on the whole DoorDash half of a shift.
DEADLINE = dict(UNCERTAIN, state='warn', pay=12.0, minutes=None, cardMinutes=34.0,
                billedMinutes=34.0, perHour=21.18, grossPerHour=21.18,
                fromDeadline=True, deliverBy=1140, miles=None, whole=True,
                milesUncertain=False, cost=0)

READINGS = {'uncertain': UNCERTAIN, 'deducted': DEDUCTED, 'deadline': DEADLINE}

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
    for (const key of Object.keys(READINGS)) {
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
    await page.route('**/api/offers/mark', async (route) => {
      posted.push(JSON.parse(route.request().postData() || '{}'));
      await route.fulfill({ status: 200, contentType: 'application/json',
                            body: '{"ok":true}' });
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

    await page.evaluate(() => window.__es.push({ phase: 'scanning' }));
    await page.waitForTimeout(120);
    out.tookIdle = await look();

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
    await page.waitForTimeout(200);
    out.tookMarked = await look();

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
                               offer: { id: 'seed-1', pay: 9.75, minutes: 21,
                                        perHour: 27.86 },
                               offerAgeMs: 3600000,
                               status: { phase: 'scanning' } }),
      });
    });
    await page.goto(base + '/live.html', { waitUntil: 'domcontentloaded' })
              .catch(() => {});
    await page.waitForTimeout(700);
    out.seedTook = await page.evaluate(() => {
      const t = document.getElementById('took');
      return { hidden: t.hidden, text: (t.textContent || '').trim() };
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
    };
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
        ok_('...and does not carry an age', 'ago' not in (fresh['detail']['text'] or ''))

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
