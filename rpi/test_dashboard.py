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
                cost=2.4, perMile=0.7, milesUncertain=False, whole=True)
# A delivery card states a deadline and no duration, so `minutes` is null and
# the rate was worked out over `cardMinutes`. The raw row divided by `minutes`
# and printed "$12.00 in -- min = $21.2/hr raw" — a sum with nothing under the
# line, on the whole DoorDash half of a shift.
DEADLINE = dict(UNCERTAIN, state='warn', pay=12.0, minutes=None, cardMinutes=34.0,
                billedMinutes=34.0, perHour=21.18, grossPerHour=21.18,
                fromDeadline=True, deliverBy=1140, miles=None, whole=True,
                milesUncertain=False, cost=0)

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
      await page.addInitScript(STUB);
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
    readings = {'uncertain': UNCERTAIN, 'deducted': DEDUCTED,
                'deadline': DEADLINE}
    proc2 = subprocess.run(
        ['node', driver, base, json.dumps(PANELS), json.dumps(readings)],
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
                                   'rate', 'raw', 'net', 'warn')
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
            ok_('%s: the headline rate is on the glass' % where,
                r['rate']['shown'])
            ok_('%s: the panel still fits' % where, r['fits'])

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
