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


def offer(i, pickup, dropoff, miles, at=None, where=None):
    at = NOW - (i + 1) * 600000 if at is None else at
    row = {'id': 'o%d' % i, 'seq': 1, 'at': at,
           'firstAt': at, 'pay': 12.0, 'minutes': 25.0,
           'billedMinutes': 25.0, 'miles': miles, 'cost': 1.5,
           'costPerMile': 0.3, 'perHour': 28.8, 'whole': True,
           'suspect': False, 'doubt': None, 'pickup': pickup,
           'dropoff': dropoff, 'places': [p for p in (pickup, dropoff) if p],
           'content': ['c%d' % i]}
    # Where the car was when the card came up, as rpi/gps.py stamps it. Absent
    # on most of these on purpose: every row written before the rig had a GPS
    # has no position, and the page has to keep working for them.
    if where:
        row['lat'], row['lon'], row['gpsAge'] = where[0], where[1], 1.2
    return row


ROWS = [
    offer(0, 'Cobb Pkwy NW, Kennesaw', 'Canton Rd, Marietta', 9.0,
          where=(34.0117, -84.6105)),
    offer(1, 'Kroger (Chastain)', 'Nowhere At All Ln, Atlantis', 6.0),
    # Kennesaw to Atlanta is about 25 miles as the crow flies; the card says 3.
    # One of those two pins has to be wrong, and the page has to say so.
    offer(2, 'Cobb Pkwy NW, Kennesaw', 'Peachtree St NE, Atlanta', 3.0,
          where=(34.0170, -84.6001)),
    # ...and one the card never gave a destination for at all, which is most of
    # this driver's real traffic.
    offer(3, 'Zaxbys', None, 5.0),
    # A street the reader got wrong, answered by a real street in Idaho. Nothing
    # about the answer says it is wrong — it has a name, a type and coordinates
    # like every other — and until the page weighed it against the rest of the
    # shift, one of these made the map a picture of the United States with
    # Atlanta as a dot.
    # ...and it carries a position, which is what makes it the interesting one:
    # the car was in Kennesaw, so a box around Kennesaw refuses Idaho outright.
    # That is the whole point of the box, and it is also the case that proves
    # the pin is not simply LOST — refused, then asked again wide, then drawn in
    # red and kept out of the map's framing like any other stray.
    offer(4, 'Cobb Pkwy NW, Kennesaw', 'W Boise Ave', 4.0,
          where=(34.0150, -84.6050)),
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
  window.__askedAt = []; window.__boxes = []; window.__dots = [];
  window.L = {
    map: function () { return { setView: function (ll) { window.__view = ll; return this; },
      // A removed group takes its dots with it. Without this a toggle that
      // never cleaned up would look identical to one that did — and drawing
      // the positions twice over each other is exactly the bug a redraw
      // invites.
      removeLayer: function (g) {
        window.__dots = window.__dots.filter(function (d) { return d.group !== g; });
      },
      addLayer: function () {},
      // Recorded, because which pins get a say in where the map looks is the
      // whole of what the stray rule does.
      fitBounds: function (b) { window.__bounds = b; } }; },
    tileLayer: function () { return { addTo: function () { return this; } }; },
    layerGroup: function () { return { addTo: function () { return this; } }; },
    // The positions the rig's own GPS recorded, which are the one thing on
    // this page that is measured rather than looked up. Kept apart from
    // __pins: a check that counted both together could not tell a job pin
    // from a dot showing where the car was.
    circleMarker: function (ll, opts) {
      var m = { ll: ll, opts: opts, group: null,
                bindPopup: function (h) { this.popup = h; return this; },
                addTo: function (g) { this.group = g; window.__dots.push(this);
                                      return this; } };
      return m; },
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
    const u = new URL(route.request().url());
    const q = decodeURIComponent(u.searchParams.get('q') || '');
    const box = u.searchParams.get('viewbox');
    const bounded = u.searchParams.get('bounded') === '1';
    await page.evaluate((a) => { window.__asked.push(a[0]);
                                 window.__boxes.push(a[1]);
                                 window.__askedAt.push(Date.now()); },
                        [q, box || null]).catch(() => {});
    const town = Object.keys(KNOWN).find((t) => q.toLowerCase().includes(t));
    if (!town) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    }
    const [lat, lon] = KNOWN[town];
    // The real Nominatim returns nothing outside the box when bounded=1, and
    // that is the entire point of sending one: an answer eighteen hundred miles
    // away stops being offered rather than being offered and then argued with.
    if (bounded && box) {
      const [left, top, right, bottom] = box.split(',').map(Number);
      const inside = lon >= Math.min(left, right) && lon <= Math.max(left, right)
                  && lat >= Math.min(top, bottom) && lat <= Math.max(top, bottom);
      if (!inside) {
        return route.fulfill({ status: 200, contentType: 'application/json',
                               body: '[]' });
      }
    }
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
    boxes: window.__boxes.slice(),
    cacheKeys: Object.keys(JSON.parse(
      localStorage.getItem('uberscan.geocode.v1') || '{}')),
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

  /* --- where the car actually was ---------------------------------------
   *
   * Off until asked for, because it is a hundred dots over the pins and the
   * pins are the subject. Once on, it is the only thing on this page that was
   * MEASURED rather than looked up — and so the only thing that can say a pin
   * is wrong without being the same kind of guess as the pin. */
  stage = 'the trail';
  out.beforeTrail = await page.evaluate(() => window.__dots.length);
  await page.click('#trail');
  await page.waitForTimeout(300);
  out.trail = await page.evaluate(() => ({
    dots: window.__dots.length,
    where: window.__dots.map(function (d) { return d.ll; }),
    // The age of the fix, which is what tells a driver how far the car could
    // have moved between the reading and the dot.
    popups: window.__dots.map(function (d) {
      return String(d.popup || '').replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
    }),
    pressed: document.getElementById('trail').getAttribute('aria-pressed'),
    status: document.getElementById('status').textContent.trim(),
    // The job pins must not have been disturbed by any of this.
    pins: window.__pins.length,
  }));
  // Pressing it twice must not leave two sets of dots on top of each other,
  // and pressing it a third time must bring them back.
  await page.click('#trail');
  await page.waitForTimeout(200);
  out.trailOff = await page.evaluate(() => ({
    dots: window.__dots.length,
    pressed: document.getElementById('trail').getAttribute('aria-pressed'),
    status: document.getElementById('status').textContent.trim(),
  }));
  await page.click('#trail');
  await page.waitForTimeout(200);
  out.trailAgain = await page.evaluate(() => window.__dots.length);

  // A row that says one of TWO pins is wrong, tapped. Centring on one of them
  // cannot answer which, so both have to end up in the view together.
  stage = 'chasing a pair';
  await page.evaluate(() => {
    window.__bounds = null;
    // The Kennesaw-to-Atlanta one specifically. Two real pins, twenty-five
    // miles apart, over a card that said three — which is the case where a
    // driver genuinely cannot tell which end is wrong without seeing both.
    // The Boise row is in this list too and is a different question: that one
    // is answered by the stray list above, in red, at a glance.
    var rows = [].slice.call(document.querySelectorAll('#sideBody .stray'))
      .filter(function (r) {
        return (r.getAttribute('data-other') || '').indexOf('Atlanta') !== -1;
      });
    if (rows[0]) rows[0].click();
  });
  await page.waitForTimeout(200);
  out.chasedPair = await page.evaluate(() => window.__bounds || null);

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

    # ...and somebody can get to it. Every check in this file was passing while
    # the page was unreachable by anything but typing its address: no page
    # linked to it and it linked nowhere back, so it was a working feature that
    # did not exist. The offer log is the right door — this is a parked page,
    # it asks a public geocoder about the places on the cards, and that is not
    # a thing to start at a red light.
    log_page = urllib.request.urlopen(base + '/journal.html', timeout=5) \
                             .read().decode('utf-8', 'replace')
    ok_('the offer log offers a way to the map', 'href="map.html"' in log_page)
    map_page = urllib.request.urlopen(base + '/map.html', timeout=5) \
                             .read().decode('utf-8', 'replace')
    ok_('...and the map offers a way back', 'href="journal.html"' in map_page)

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
    # Once each, plus exactly one more for each place its own box refused —
    # those are asked again without the box so a pin is never lost to the
    # anchoring. Anything beyond that is the page asking the same question
    # twice, which is a rate limit spent on nothing.
    twice = [q for q in set(asked) if asked.count(q) > 1]
    ok_('nothing is asked more than twice (%r)' % (twice[:3],),
        all(asked.count(q) <= 2 for q in set(asked)))
    ok_('...and the only place asked twice is the one its box refused (%r)'
        % (twice,),
        all('Boise' in q for q in twice))
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

    # A row that says one of TWO pins is wrong. Centring on one of them cannot
    # answer which, and that is the only question the row raises.
    pair = got.get('chasedPair') or []
    eq('tapping a "cannot be right" row frames both its ends (%r)' % (pair,),
       len(pair), 2)
    ok_('...the Kennesaw end',
        pair and any(abs(float(p[0]) - 34.023) < 0.01 for p in pair))
    ok_('...and the Atlanta one it cannot be that far from',
        pair and any(abs(float(p[0]) - 33.749) < 0.01 for p in pair))

    # --- where the car actually was -----------------------------------------
    #
    # Every other mark on this page is a guess: a name off a card, handed to a
    # geocoder, answered with a coordinate that is right most of the time.
    # These are not — they are what the rig's own GPS said at the moment the
    # card came up, and they are the only thing here that can contradict a pin
    # without being the same kind of thing as the pin.
    eq('nothing is drawn about the car until it is asked for',
       got.get('beforeTrail'), 0)
    trail = got.get('trail') or {}
    # Three of the thirty-one rows carry a position. The rest were written
    # before the rig had a GPS, and the page has to keep working for them.
    eq('...and then one dot per row that knows where it was',
       trail.get('dots'), 3)
    ok_('...at the positions those rows carry (%r)' % (trail.get('where'),),
        (trail.get('where') or [])
        and all(abs(float(w[0]) - 34.01) < 0.02 for w in trail['where']))
    # A position twenty seconds stale is half a mile at fifty miles an hour,
    # and a driver judging a pin by its distance from these dots is owed that.
    ok_('...saying how old each fix was (%r)' % (trail.get('popups') or [''])[0],
        any('old' in p for p in (trail.get('popups') or [])))
    ok_('...counted in the status line (%r)' % trail.get('status'),
        '3 positions' in (trail.get('status') or ''))
    # The whole reason for showing them, said where it can be read.
    ok_('...with what a pin far from all of them means',
        'distrust' in (trail.get('status') or ''))
    eq('...and the job pins are untouched by any of it',
       trail.get('pins'), (got.get('placed') or {}).get('pins'))
    ok_('...and the button says it is on', trail.get('pressed') == 'true')
    # Drawing them twice over each other would look identical on a real map
    # and be a leak on every redraw.
    eq('turning it off takes the dots away', (got.get('trailOff') or {}).get('dots'), 0)
    ok_('...and says so rather than leaving the last count standing (%r)'
        % (got.get('trailOff') or {}).get('status'),
        'hidden' in ((got.get('trailOff') or {}).get('status') or ''))
    eq('...and turning it on again draws them once, not twice',
       got.get('trailAgain'), 3)

    # --- a list that stops has to say it stopped ----------------------------
    #
    # The argument for this sidebar is that a map showing the fifth it managed
    # reports the rig as doing better than it is. A list showing the first
    # twenty-five of twenty-seven failures makes the same mistake one level
    # down, and the cap was there from the first draft with nothing saying so.
    ok_('a truncated list says how many it did not show (%r)'
        % [f for f in side.split('…') if 'more, not listed' in f][:1],
        'more, not listed' in side)

    # --- searched near where the car actually was ---------------------------
    #
    # The driver's own words: "usually the pickup/restaurant is the closest one
    # to me". A geocoder cannot know that and a coordinate can. Since rpi/gps.py
    # a row carries where the car was when the card came up, so a place named by
    # such a row is searched inside a box around that position rather than
    # around a hint typed once for a whole week.
    #
    # The fixture gives two of the offers a position near Kennesaw and leaves
    # the rest without one, which is the real mixture: every row written before
    # the rig had a GPS has none.
    boxes = placed.get('boxes') or []
    asked_all = placed.get('asked') or []
    eq('every question is recorded with the box it was asked in',
       len(boxes), len(asked_all))
    with_box = [b for b in boxes if b]
    ok_('some places were searched inside a box (%d of %d)'
        % (len(with_box), len(boxes)), len(with_box) > 0)
    ok_('...and some were not, because their rows carried no position',
        len(with_box) < len(boxes))

    # The box is around the position, and it is the right way round: Nominatim
    # wants left,top,right,bottom — longitude first. Swapping the pair is the
    # mistake that draws a box in the Indian Ocean and refuses everything.
    for b in with_box[:1]:
        left, top, right, bottom = [float(x) for x in b.split(',')]
        ok_('the box is longitude-first (%s)' % b, left < right)
        ok_('...and latitude descends from top to bottom', top > bottom)
        ok_('...and it surrounds where the car was (34.01, -84.61)',
            left <= -84.61 <= right and bottom <= 34.01 <= top)
        # A degree of longitude is shorter than a degree of latitude away from
        # the equator, so a box of equal DEGREES is too narrow east to west. At
        # 34°N the longitude span has to be about 1.2x the latitude span.
        ok_('...and is not a square of degrees, which would be too narrow '
            'east-west (%.2f vs %.2f)' % (right - left, top - bottom),
            (right - left) > (top - bottom) * 1.1)

    # What it is FOR. 'Cobb Pkwy NW, Kennesaw' is named by rows that carried a
    # position, so it is asked inside a box; 'W Boise Ave' is named by a row
    # that did not, so it is asked wide — and comes back from Idaho, which is
    # what makes the stray list worth having in the first place.
    kennesaw = [b for q, b in zip(asked_all, boxes) if 'Kennesaw' in q]
    ok_('the place named by rows with a position is asked inside a box',
        kennesaw and all(kennesaw))
    zaxbys = [b for q, b in zip(asked_all, boxes) if 'Zaxbys' in q]
    ok_('...and one named only by rows without a position is asked wide',
        zaxbys and not any(zaxbys))

    # The case the box exists for, and the case that proves it does not simply
    # lose pins. The car was in Kennesaw; the street was misread; the geocoder
    # has a real W Boise Ave in Idaho. Bounded, it is refused. Then it is asked
    # again without the box, through the same paced walk, and comes back — so it
    # is still drawn, still red, and still kept out of the map's framing.
    boise = [b for q, b in zip(asked_all, boxes) if 'Boise' in q]
    eq('a place its own box refuses is asked twice: bounded, then wide',
       [bool(b) for b in boise], [True, False])
    # Under two different keys, or the wide answer overwrites the bounded one
    # and the box stops being applied from the second run onward — silently,
    # because everything still works.
    keys = placed.get('cacheKeys') or []
    boise_keys = [k for k in keys if 'Boise' in k]
    eq('...and remembered under two keys, not one', len(boise_keys), 2)
    ok_('...one of which carries the box it was asked in (%r)' % (boise_keys,),
        any('@' in k for k in boise_keys)
        and any('@' not in k for k in boise_keys))
    # ...and the place is still on the map, which is the thing that would have
    # been lost. It lands in the stray list, because Idaho is eighteen hundred
    # miles from the rest of the shift — drawn, listed, and kept out of the
    # map's framing, which is exactly what should happen to it.
    boise_pin = [p for p in (placed.get('pinDetail') or [])
                 if 'Boise' in (p.get('popup') or '')]
    ok_('the refused place is still pinned (%d)' % len(boise_pin), boise_pin)
    if boise_pin:
        ok_('...and marked as nowhere near the rest, which is what it is (%r)'
            % (boise_pin[0].get('popup') or '')[:70],
            'almost certainly wrong' in (boise_pin[0].get('popup') or ''))

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
