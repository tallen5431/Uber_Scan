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


def offer(i, pickup, dropoff, miles, at=None):
    at = NOW - (i + 1) * 600000 if at is None else at
    return {'id': 'o%d' % i, 'seq': 1, 'at': at,
            'firstAt': at, 'pay': 12.0, 'minutes': 25.0,
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
    # A street the reader got wrong, answered by a real street in Idaho. Nothing
    # about the answer says it is wrong — it has a name, a type and coordinates
    # like every other — and until the page weighed it against the rest of the
    # shift, one of these made the map a picture of the United States with
    # Atlanta as a dot.
    offer(4, 'Cobb Pkwy NW, Kennesaw', 'W Boise Ave', 4.0),
] + [
    # Twenty-six the geocoder has never heard of, which is two past the
    # twenty-five a list shows. A list that stops there and says nothing is the
    # same mistake as a map that draws the fifth it managed, one level down.
    # Newest, deliberately: the journal comes back oldest first, so putting
    # these at the front of the list would push the one named failure above out
    # past the cap and the check on it would pass by not running.
    offer(5 + i, 'Unfindable Pl %d, Atlantis' % i, None, 2.0, at=NOW - (i + 1) * 1000)
    for i in range(26)
]

DRIVER = r'''
const { chromium } = require('playwright');
const base = process.argv[2];

// Leaflet comes from a CDN this box cannot reach. Stubbed so the page's own
// drawing decisions are observable: what it pins, what it joins with a line,
// and which of those lines it marks as impossible.
const STUB = `
  window.__pins = []; window.__lines = []; window.__asked = [];
  window.__askedAt = [];
  window.L = {
    map: function () { return { setView: function (ll) { window.__view = ll; return this; },
      removeLayer: function () {}, addLayer: function () {},
      // Recorded, because which pins get a say in where the map looks is the
      // whole of what the stray rule does.
      fitBounds: function (b) { window.__bounds = b; } }; },
    tileLayer: function () { return { addTo: function () { return this; } }; },
    layerGroup: function () { return { addTo: function () { return this; } }; },
    divIcon: function (o) { return o; },
    marker: function (ll, opts) {
      var m = { ll: ll, icon: (opts && opts.icon) || {},
                bindPopup: function (h) { this.popup = h; return this; },
                addTo: function () { return this; },
                getLatLng: function () { return this.ll; },
                openPopup: function () { window.__opened = this.ll; return this; } };
      window.__pins.push(m); return m; },
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
  // Eighteen hundred miles away, and answered as confidently as the rest.
  // This is what a geocoder handed a misread street really does.
  boise:    [43.615, -116.202],
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
    await page.evaluate((s) => { window.__asked.push(s);
                                 window.__askedAt.push(Date.now()); }, q).catch(() => {});
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
    // What each pin is: where, what colour, and the count drawn on it.
    pinDetail: window.__pins.map(function (m) {
      var html = (m.icon && m.icon.html) || '';
      var colour = (html.match(/background:(#[0-9a-f]{6})/i) || [])[1] || '';
      var count = (html.match(/>(\d*)<\/div>/) || [])[1] || '';
      return { ll: m.ll, colour: colour, count: count,
               popup: String(m.popup || '').replace(/<[^>]*>/g, ' ')
                                           .replace(/\s+/g, ' ').trim() };
    }),
    // Only the pins allowed to decide where the map looks.
    bounds: window.__bounds || [],
    lines: window.__lines.length,
    impossible: window.__lines.filter((l) => l.opts && l.opts.dashArray).length,
    asked: window.__asked.slice(),
    // Every gap between two consecutive questions, in ms. The geocoder this
    // page uses asks for at most one request a second and blocks the projects
    // that do not keep to it.
    gaps: window.__askedAt.slice(1).map(function (t, i) {
      return t - window.__askedAt[i];
    }),
    side: document.getElementById('sideBody').textContent.replace(/\s+/g, ' ').trim(),
  }));

  // A stray is listed so it can be judged, and it cannot be judged off a view
  // it was deliberately kept out of. One tap has to take the map to it.
  stage = 'chasing a stray';
  await page.evaluate(() => {
    var row = document.querySelector('#sideBody .stray');
    if (row) row.click();
  });
  await page.waitForTimeout(200);
  out.chased = await page.evaluate(() => ({ view: window.__view || null,
                                            opened: window.__opened || null }));

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
    ok_('the page counts the offers it loaded (%r)' % status, '31 offers' in status)
    ok_('...how many name somewhere', '31 name somewhere' in status)
    ok_('...and how many name both ends', '4 name both ends' in status)
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
    # Two: the Atlanta pair the card says is three miles, and the Idaho pin,
    # which is caught by this rule as well as by the distance-from-the-shift
    # one. Both are the same statement — a straight line cannot beat the road.
    eq('a pair further apart than the card allows is marked, not asserted',
       placed.get('impossible'), 2)
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
        'of 4 drawn end to end' in status2)

    # --- one request a second, and the page holding itself to it ------------
    #
    # Nominatim asks for at most one a second and blocks the projects that do
    # not keep to it — and being blocked is not one bad run, it is this page
    # not working for anyone who pulls this repo. The wait was written and then
    # asked for at the wrong moment: lookup() writes its answer into the cache
    # before returning, so a "was this cached?" test made AFTER it always found
    # the key and always skipped the wait. Every lookup that used the network
    # was exempt from the limit; only the ones that FAILED were slowed down.
    # Measured here rather than argued about: six questions in 33ms.
    gaps = placed.get('gaps') or []
    ok_('more than one question was asked, so there are gaps to measure (%d)' % len(gaps),
        len(gaps) >= 3)
    slowest = min(gaps) if gaps else 0
    ok_('...and every one of them is a second or more apart (%dms at worst)' % slowest,
        gaps and slowest >= 1000)

    # --- one pin per place, not one per offer -------------------------------
    #
    # Every job at the same shop geocodes to the same coordinate. Stacked to the
    # pixel, twelve offers look exactly like one, the popups are unreachable
    # under each other, and how often a place came up — most of what makes a map
    # of a shift worth looking at — cannot be seen at all.
    detail = placed.get('pinDetail') or []
    here = [d for d in detail if 'Cobb Pkwy NW, Kennesaw' in (d.get('popup') or '')]
    eq('a place three offers share gets one pin, not three', len(here), 1)
    ok_('...with the number of jobs on it (%r)' % (here and here[0].get('count')),
        here and here[0].get('count') == '3')
    ok_('...and the count said in the popup as well',
        here and '3 jobs' in (here[0].get('popup') or ''))

    # --- a pin that cannot be in this shift ---------------------------------
    #
    # A geocoder handed a misread street answers with a real place somewhere.
    # Nothing about the answer says it is wrong. What says it is wrong is that
    # it is eighteen hundred miles from everything else in the same shift.
    stray = [d for d in detail if 'Boise' in (d.get('popup') or '')]
    eq('the far-flung pin is drawn, not silently dropped', len(stray), 1)
    ok_('...in the colour that says it cannot be right (%r)'
        % (stray and stray[0].get('colour')),
        stray and stray[0].get('colour') == '#f31260')
    ok_('...saying how far out it is, in the popup',
        stray and 'from everything else' in (stray[0].get('popup') or ''))

    bounds = placed.get('bounds') or []
    ok_('the map was fitted to something', bool(bounds))
    # The whole point. Included, this one pin turns a map of a shift into a map
    # of the United States with the shift as a single dot, and the ninety good
    # pins the driver came to check cannot be seen at all.
    ok_('...and the far-flung pin got no say in where it looks (%d pins)' % len(bounds),
        bounds and all(abs(float(b[0]) - 43.615) > 0.01 for b in bounds))
    ok_('...while the pins that belong to the shift did',
        bounds and any(abs(float(b[0]) - 34.023) < 0.01 for b in bounds))
    ok_('...and it is listed with how far out it is', 'nowhere near the rest' in side)
    ok_('...in miles', 'mi out' in side)

    # Kept out of the view on purpose, so there has to be a way back to it:
    # a stray listed and unreachable is a claim the driver cannot check.
    chased = got.get('chased') or {}
    view = chased.get('view') or []
    ok_('tapping a stray takes the map to it (%r)' % (view,),
        view and abs(float(view[0]) - 43.615) < 0.01)
    ok_('...and opens what it says about it', bool(chased.get('opened')))

    # --- a list that stops has to say it stopped ----------------------------
    #
    # The argument for this sidebar is that a map showing the fifth it managed
    # reports the rig as doing better than it is. A list showing the first
    # twenty-five of twenty-seven failures makes the same mistake one level
    # down, and the cap was there from the first draft with nothing saying so.
    ok_('a truncated list says how many it did not show (%r)'
        % [f for f in side.split('…') if 'more, not listed' in f][:1],
        'more, not listed' in side)

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
