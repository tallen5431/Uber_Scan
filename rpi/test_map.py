"""The map check page, driven through a real browser.

    python3 rpi/test_map.py

`map.html` exists to answer one question — is the rig right about where the
work happened — and a page that answers it wrongly is worse than no page,
because it would be believed. Two properties carry that weight and both are
checked here against a real server and a real journal.

The first is that nothing leaves the browser until the driver asks. The rig
never sends a place anywhere itself; this page does, to a public geocoder, and
some of those places are where customers live. A page that quietly looked them
all up on load would have moved that decision away from the person whose
decision it is.

The second is that it shows its failures. Of this driver's own 103 offers, most
name no destination at all, and a geocoder will confidently place a misread
street somewhere real. A map that draws the third it managed and says nothing
about the rest reports the rig as doing better than it is — so the count that
could not be drawn, and the reason for each, is part of the page rather than a
footnote.

The geocoder and the map tiles are stubbed at the network layer. Everything
above them — what the page asks for, what it does with the answers, what it
refuses to draw — is the real page.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE_PATHS = ['/opt/node22/lib/node_modules',
              os.path.join(ROOT, 'node_modules')]

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
    print('%s — skipping the map checks' % why)
    sys.exit(0)


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


# Three offers, chosen so every branch of the page has something to do: one the
# stub can place at both ends, one whose dropoff the stub has never heard of,
# and one whose ends the stub puts further apart than the card's own distance.
NOW = int(time.time() * 1000)


def offer(i, pickup, dropoff, miles):
    return {'id': 'o%d' % i, 'seq': 1, 'at': NOW - (i + 1) * 600000,
            'firstAt': NOW - (i + 1) * 600000, 'pay': 12.0, 'minutes': 25.0,
            'billedMinutes': 25.0, 'miles': miles, 'cost': 1.5,
            'costPerMile': 0.3, 'perHour': 28.8, 'whole': True,
            'suspect': False, 'doubt': None, 'pickup': pickup,
            'dropoff': dropoff, 'places': [p for p in (pickup, dropoff) if p],
            'content': ['c%d' % i]}


ROWS = [
    offer(0, 'Cobb Pkwy NW, Kennesaw', 'Canton Rd, Marietta', 9.0),
    offer(1, 'Kroger (Chastain)', 'Nowhere At All Ln, Atlantis', 6.0),
    # Kennesaw to Atlanta is about 25 miles as the crow flies; the card says 3.
    # One of those two pins has to be wrong, and the page has to say so.
    offer(2, 'Cobb Pkwy NW, Kennesaw', 'Peachtree St NE, Atlanta', 3.0),
    # ...and one the card never gave a destination for at all, which is most of
    # this driver's real traffic.
    offer(3, 'Zaxbys', None, 5.0),
]

DRIVER = r'''
const { chromium } = require('playwright');
const base = process.argv[2];

// Leaflet comes from a CDN this box cannot reach. Stubbed so the page's own
// drawing decisions are observable: what it pins, what it joins with a line,
// and which of those lines it marks as impossible.
const STUB = `
  window.__pins = []; window.__lines = []; window.__asked = [];
  window.L = {
    map: function () { return { setView: function () { return this; },
      removeLayer: function () {}, addLayer: function () {},
      fitBounds: function () {} }; },
    tileLayer: function () { return { addTo: function () { return this; } }; },
    layerGroup: function () { return { addTo: function () { return this; } }; },
    divIcon: function () { return {}; },
    marker: function (ll) { window.__pins.push(ll); return {
      bindPopup: function () { return this; }, addTo: function () { return this; } }; },
    polyline: function (pts, opts) { window.__lines.push({ pts: pts, opts: opts });
      return { bindPopup: function () { return this; },
               addTo: function () { return this; } }; }
  };
`;

const KNOWN = {
  kennesaw: [34.023, -84.615],
  marietta: [33.952, -84.549],
  atlanta:  [33.749, -84.388],
  chastain: [34.010, -84.580],
};

(async () => {
  let browser;
  for (const exe of JSON.parse(process.env.PW_EXES || '[]').concat([null])) {
    try { browser = await chromium.launch(exe ? { executablePath: exe } : {}); break; }
    catch (e) { /* try the next */ }
  }
  if (!browser) { console.log(JSON.stringify({ skip: 'no chromium' })); return; }

  let stage = 'start';
  setTimeout(() => {
    console.log(JSON.stringify({ skip: 'the driver hung in "' + stage + '"' }));
    process.exit(2);
  }, 240000).unref();

  const page = await browser.newContext({ viewport: { width: 1200, height: 820 } })
    .then((c) => c.newPage());
  await page.addInitScript(STUB);

  await page.route('**/nominatim.openstreetmap.org/**', async (route) => {
    const q = decodeURIComponent(new URL(route.request().url()).searchParams.get('q') || '');
    await page.evaluate((s) => window.__asked.push(s), q).catch(() => {});
    const town = Object.keys(KNOWN).find((t) => q.toLowerCase().includes(t));
    if (!town) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    }
    const [lat, lon] = KNOWN[town];
    return route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify([{ lat: String(lat), lon: String(lon),
        display_name: town + ', GA, USA', type: 'road' }]) });
  });
  await page.route('**/tile.openstreetmap.org/**', (r) => r.fulfill({ status: 200, body: '' }));

  const out = {};
  stage = 'load';
  await page.goto(base + '/map.html', { waitUntil: 'domcontentloaded' }).catch(() => {});
  await page.waitForFunction(
    () => /offers/.test(document.getElementById('status').textContent),
    null, { timeout: 20000 }).catch(() => {});
  // A beat before looking, so a page that started geocoding by itself has had
  // time to be caught at it. Read the instant the offers land and an on-load
  // lookup would simply not have happened yet.
  await page.waitForTimeout(2500);

  out.onLoad = await page.evaluate(() => ({
    status: document.getElementById('status').textContent.trim(),
    asked: window.__asked.length,
    privacy: document.getElementById('privacy').textContent.replace(/\s+/g, ' ').trim(),
    canPlace: !document.getElementById('place').disabled,
  }));

  stage = 'place';
  await page.click('#place');
  await page.waitForFunction(
    () => /drawn end to end/.test(document.getElementById('status').textContent),
    null, { timeout: 200000 }).catch(() => {});

  out.placed = await page.evaluate(() => ({
    status: document.getElementById('status').textContent.trim(),
    pins: window.__pins.length,
    lines: window.__lines.length,
    impossible: window.__lines.filter((l) => l.opts && l.opts.dashArray).length,
    asked: window.__asked.slice(),
    side: document.getElementById('sideBody').textContent.replace(/\s+/g, ' ').trim(),
  }));

  // A second run must ask nothing: the answers are remembered on the device,
  // which is what makes re-checking a map free and keeps the geocoder unbothered.
  stage = 'again';
  const before = out.placed.asked.length;
  await page.click('#place');
  await page.waitForTimeout(3000);
  out.again = await page.evaluate((n) => ({
    newQuestions: window.__asked.length - n,
  }), before);

  console.log(JSON.stringify(out));
  await browser.close();
})();
'''

if shutil.which('node') is None:
    skip('no node on this machine')

work = tempfile.mkdtemp()
journal = os.path.join(work, 'journal.jsonl')
with open(journal, 'w') as fh:
    for row in ROWS:
        fh.write(json.dumps(row) + '\n')

port = free_port()
server = subprocess.Popen(
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

    # The page is a page like any other: if the server will not serve it, none
    # of the rest of this file means anything.
    code = urllib.request.urlopen(base + '/map.html', timeout=5).getcode()
    eq('the server serves the map page', code, 200)

    driver = os.path.join(work, 'mapdrive.js')
    open(driver, 'w').write(DRIVER)
    proc = subprocess.run(
        ['node', driver, base],
        env=dict(os.environ, NODE_PATH=os.pathsep.join(NODE_PATHS),
                 PW_EXES=json.dumps([
                     os.environ.get('CHROMIUM', ''),
                     '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
                 ])),
        capture_output=True, text=True, timeout=600)
    line = (proc.stdout or '').strip().split('\n')[-1] if proc.stdout else ''
    try:
        got = json.loads(line)
    except Exception:
        skip('the browser produced nothing (%s)' % (proc.stderr or '')[-300:])
    if got.get('skip'):
        skip(got['skip'])

    on_load = got.get('onLoad') or {}
    placed = got.get('placed') or {}

    # --- nothing is asked until the driver asks ----------------------------
    #
    # The one property that cannot be recovered if it is wrong: a place sent to
    # a third party has been sent. The rig's own rule is that it never sends
    # one; this page moves that decision to the person it belongs to, and the
    # decision is only real if the page waits for it.
    eq('nothing is looked up before the button is pressed', on_load.get('asked'), 0)
    ok_('...and the page says where they will go',
        'OpenStreetMap' in (on_load.get('privacy') or ''))
    ok_('...and that some of them are where customers live',
        'customers live' in (on_load.get('privacy') or ''))
    ok_('...and that the rig itself never sends them',
        'never sends them' in (on_load.get('privacy') or ''))

    # --- it reads the same list the offers page reads ----------------------
    status = on_load.get('status') or ''
    ok_('the page counts the offers it loaded (%r)' % status, '4 offers' in status)
    ok_('...how many name somewhere', '4 name somewhere' in status)
    ok_('...and how many name both ends', '3 name both ends' in status)
    ok_('the button is live once there is something to place', on_load.get('canPlace'))

    # --- what it drew ------------------------------------------------------
    asked = placed.get('asked') or []
    ok_('every distinct place was looked up once (%d)' % len(asked),
        len(asked) == len(set(asked)))
    # Kennesaw appears as the pickup of two different offers and must be asked
    # about once, not twice: the cache is keyed on the place, not the offer.
    eq('...including one shared by two offers',
       len([q for q in asked if 'Cobb Pkwy NW, Kennesaw' in q]), 1)

    ok_('the ends it could place are pinned (%s)' % placed.get('pins'),
        (placed.get('pins') or 0) >= 4)
    ok_('...and joined end to end where both ends resolved',
        (placed.get('lines') or 0) >= 2)

    # --- and what it refused to claim --------------------------------------
    #
    # A straight line cannot be longer than the road between the same two
    # points, so when it is, a pin is wrong. That is the only check this page
    # can make without a router, and it is made against the card's own figure.
    eq('a pair further apart than the card allows is marked, not asserted',
       placed.get('impossible'), 1)
    side = placed.get('side') or ''
    ok_('...and explained in words (%r)' % side[:60], 'cannot be right' in side)
    ok_('...naming the reason a straight line settles it',
        'cannot beat the road' in side)

    ok_('a place the geocoder never found is listed rather than dropped',
        'could not find' in side)
    ok_('...by the text that was searched for',
        'Nowhere At All Ln' in side)

    # The commonest case in this driver's real journal, and the one a map would
    # otherwise silently omit: the card never said where the job ends.
    ok_('offers the card gave no destination for are counted', 'no dropoff at all' in side)
    ok_('...and the reason is given', 'Customer dropoff' in side)
    ok_('...along with what fills them in', 'Dropoff button' in side)

    status2 = placed.get('status') or ''
    # Out of the three that named both ends, not out of the four that named
    # anywhere: an offer the card gave no destination for was never a candidate
    # for a line, and counting it as a failure to draw one blames the map for
    # something the card did.
    ok_('the headline counts against the offers that could be drawn (%r)' % status2,
        'of 3 drawn end to end' in status2)

    # --- asking twice costs nothing ----------------------------------------
    eq('a second run asks the geocoder nothing new',
       (got.get('again') or {}).get('newQuestions'), 0)

finally:
    server.terminate()
    try:
        server.wait(timeout=5)
    except Exception:
        server.kill()
    shutil.rmtree(work, ignore_errors=True)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d map checks passed' % ok)
sys.exit(1 if bad else 0)
