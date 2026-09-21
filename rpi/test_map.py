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

import re
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


def no_(name, cond):
    eq(name, bool(cond), False)


def skip(why):
    print('%s — skipping the map checks' % why)
    sys.exit(0)


def hung(stage):
    """A driver that stopped is a FAILED suite, not a skipped one.

    `skip` is for a machine that cannot run these at all — no chromium — where
    exiting 0 is right, because nothing was learned and nothing was broken. A
    driver that hung is the opposite: it reached some particular control and
    waited for it until the watchdog gave up, which is a fact about the page,
    and it used to report that by exiting 0. tools/test.sh then counted the
    suite as passed with none of its checks run.

    Not hypothetical — it happened to the dashboard suite the day this was
    written, hiding a real regression behind "all 37 suites passed".
    """
    print('FAIL  the driver hung in "%s" — none of the %s checks ran'
          % (stage, 'map'))
    print('\n%d passed, %d FAILED' % (ok, bad + 1))
    sys.exit(1)


def crashed(stderr):
    """A driver that RAN and produced nothing is a FAILED suite.

    This used to be a skip, which exits 0, so `tools/test.sh` counted the suite
    as passed with none of its checks run. It is the same conflation `hung()`
    was written for and it was only half fixed: a driver that stops answering
    is caught, a driver that THROWS still slipped through as "the browser
    produced nothing".

    A machine that cannot run these at all — no chromium — is the one case
    where exiting 0 is right, and every driver here now says so explicitly by
    printing {skip: 'no chromium'} and returning. That is a signal; this is the
    absence of one. Reading the difference out of stderr was considered and
    rejected: it makes the suite guess from a message it does not control.
    """
    tail = (stderr or '').strip()[-400:]
    print('FAIL  the driver produced nothing — none of the %s checks ran'
          % 'map')
    if tail:
        print('      ' + tail.replace('\n', '\n      '))
    print('\n%d passed, %d FAILED' % (ok, bad + 1))
    sys.exit(1)


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


def offer(i, pickup, dropoff, miles, at=None, where=None, minutes=25.0,
          whole=True, suspect=False, corrected=False):
    # `whole` and `suspect` are what say whether the distance beside them is a
    # yardstick — see judge() in map-view.js. Defaulted to a clean reading,
    # because that is what nearly every row is; the two rows below that are not
    # exist because the page must not accuse a pin on a distance the reader
    # itself did not finish.
    at = NOW - (i + 1) * 600000 if at is None else at
    row = {'id': 'o%d' % i, 'seq': 1, 'at': at,
           'firstAt': at, 'pay': 12.0, 'minutes': minutes,
           'billedMinutes': minutes, 'miles': miles, 'cost': 1.5,
           'costPerMile': 0.3, 'perHour': 28.8, 'whole': whole,
           'milesCorrected': corrected,
           'suspect': suspect, 'doubt': None, 'pickup': pickup,
           'dropoff': dropoff, 'places': [p for p in (pickup, dropoff) if p],
           'content': ['c%d' % i]}
    # Where the car was when the card came up, as rpi/gps.py stamps it. Absent
    # on most of these on purpose: every row written before the rig had a GPS
    # has no position, and the page has to keep working for them.
    if where:
        row['lat'], row['lon'], row['gpsAge'] = where[0], where[1], 1.2
    return row


ROWS = [
    # ...and its distance is the rig's repair of the card's, not the card's:
    # the read lost the decimal in "9.0 mi", made 90, computed a speed no car
    # makes and divided by ten. 328 of the owner's 1,166 offers are this, and
    # every surface that printed the figure called it "card said 9 mi total"
    # while the card said 90.
    offer(0, 'Cobb Pkwy NW, Kennesaw', 'Canton Rd, Marietta', 9.0,
          where=(34.0117, -84.6105), corrected=True),
    # Also five minutes, and also load-bearing: it makes the LAST hop a plain
    # empty run, so the fixture carries one hop of each kind — stacked, empty,
    # and spanning a job that could not be placed — with real miles on the two
    # that must not be folded together.
    offer(1, 'Kroger (Chastain)', 'Nowhere At All Ln, Atlantis', 6.0, minutes=5.0),
    # Kennesaw to Atlanta is about 25 miles as the crow flies; the card says 3.
    # One of those two pins has to be wrong, and the page has to say so.
    # Five minutes, not twenty-five, and that is load-bearing for the chain: the
    # next card comes up ten minutes later, so this is the one pair in the
    # fixture that is NOT a stack. Without it every hop here is stacked and the
    # headline's "miles nobody paid for" is honestly 0.0 — which tests nothing
    # about the arithmetic that separates the two.
    # ...and CORRECTED as well, which is the combination the accusation
    # sidebar had no cover for: o0 is corrected but not accused, o2 was accused
    # but not corrected, so the one row that prints an accusation ABOUT a
    # repaired figure existed nowhere. 262 of the owner's 579 drawable pairs
    # are corrected, so on the real week it is the commoner half of that
    # section, and the note over it said "the card stated".
    offer(2, 'Cobb Pkwy NW, Kennesaw', 'Peachtree St NE, Atlanta', 3.0,
          where=(34.0170, -84.6001), minutes=5.0, corrected=True),
    # ...and one the card never gave a destination for at all, which is most of
    # this driver's real traffic.
    # Placeable nowhere — the stub has never heard of Zaxbys and the card gave
    # no destination — and stamped to sit in time BETWEEN two jobs that can be
    # placed. That is what makes the hop spanning it a hop the car did not
    # drive end to end, which the headline must not count as empty miles.
    offer(3, 'Zaxbys', None, 5.0, at=NOW - 1500000),
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
    # ...and one the geocoder could not be REACHED about, which is a different
    # fact from one it has never heard of and used to be reported as the same
    # one. A driver in a dead spot on I-75 was told a dozen of their streets do
    # not exist, and went looking at the crop for a fault that was the tunnel.
    #
    # Deliberately carries no position, so it gets no box and is therefore not
    # part of the "asked wide" retry — one question in the first run, one in
    # the second, which is what the cache check below counts on.
    #
    # ...and no pickup either, which is the shape that catches a real mistake:
    # the list decides which end is missing, and asking "is there no pickup
    # pin?" answers YES for a row that never named a pickup, then reads the
    # bucket off a name that does not exist. It also keeps this row out of
    # every count the rest of the suite pins — it names one end, so "name both
    # ends", "drawn end to end" and the shared-pin count are all untouched.
    offer(31, None, 'Unreachable Way, Atlantis', 5.0),
    # The accusation this page must NOT make. Marietta to Atlanta is about
    # fifteen miles as the crow flies and the row carries three — which under
    # the old rule is "This cannot be right, one of these pins is wrong", in
    # red, dashed, and in the sidebar. But the reading never finished: a leg
    # lost its distance, so three miles is a fraction of the journey and losing
    # that comparison says nothing whatever about the two pins, which are both
    # exactly where they should be.
    #
    # Both place strings are already asked about by the rows above, so this
    # adds no question, no pin and no cache key — only a line, which is the
    # thing under test. It is not ticked as taken either, so the chain is
    # untouched.
    offer(32, 'Canton Rd, Marietta', 'Peachtree St NE, Atlanta', 3.0,
          whole=False),
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
        // Lines go too, and for the same reason: a chain toggled off that
        // merely stopped adding lines would look identical to one that took
        // its own away, and pressing it twice would leave two sets of dashes
        // over each other.
        window.__lines = window.__lines.filter(function (l) { return l.group !== g; });
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
    polyline: function (pts, opts) {
      // The popup and the group it was added to are both kept. What a line
      // SAYS is half of what it is for — a hop that draws the right dashes
      // over the wrong words is a map that lies about a line that is fine —
      // and the group is what makes turning it off observable.
      var l = { pts: pts, opts: opts, group: null,
                bindPopup: function (h) { this.popup = h; return this; },
                addTo: function (g) { this.group = g; return this; } };
      window.__lines.push(l); return l; }
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
    console.log(JSON.stringify({ __hung: stage }));
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
    // The network, not the geocoder. An aborted request is what a dead spot
    // actually looks like to the page: no status, no body, a rejected fetch.
    // Nothing may be stored for it, or a tunnel becomes a permanent verdict.
    if (q.indexOf('Unreachable') !== -1) { return route.abort(); }
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
    // What each line SAYS, which is the half of it a colour cannot carry:
    // whether the figure beside the straight line is the card's or the rig's
    // repair of it, and whether the pair is being accused or left alone.
    linePopups: window.__lines.map(function (l) {
      return String(l.popup || '').replace(/<[^>]*>/g, ' ')
                                  .replace(/\s+/g, ' ').trim();
    }),
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

  /* --- the miles nobody paid for ----------------------------------------
   *
   * Each job already draws its own line, and that line is distance the card
   * paid for. What nothing drew is the run BETWEEN two jobs, which is the
   * whole of what makes a stack good or bad and is invisible on a map of
   * unconnected pairs. Off until asked for, like the trail, and joining only
   * the offers the driver ticked as taken. */
  stage = 'the chain';
  out.beforeChain = await page.evaluate(() => window.__lines.length);
  await page.click('#chain');
  await page.waitForTimeout(300);
  out.chain = await page.evaluate((n) => {
    var fresh = window.__lines.slice(n);
    return {
      hops: fresh.length,
      pts: fresh.map(function (l) { return l.pts; }),
      colours: fresh.map(function (l) { return l.opts && l.opts.color; }),
      dashed: fresh.every(function (l) { return !!(l.opts && l.opts.dashArray); }),
      popups: fresh.map(function (l) {
        return String(l.popup || '').replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
      }),
      pressed: document.getElementById('chain').getAttribute('aria-pressed'),
      status: document.getElementById('status').textContent.trim(),
      // The job lines and the job pins must not have been disturbed by any of
      // this: the chain is drawn over the map, not instead of it.
      before: n, pins: window.__pins.length
    };
  }, out.beforeChain);
  // Twice must not leave two sets of dashes on top of each other, and a third
  // press has to bring them back.
  await page.click('#chain');
  await page.waitForTimeout(200);
  out.chainOff = await page.evaluate((n) => ({
    lines: window.__lines.length,
    was: n,
    pressed: document.getElementById('chain').getAttribute('aria-pressed'),
    status: document.getElementById('status').textContent.trim(),
  }), out.beforeChain);
  await page.click('#chain');
  await page.waitForTimeout(200);
  out.chainAgain = await page.evaluate((n) => window.__lines.length - n,
                                       out.beforeChain);

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

  /* --- Forget lookups, and whether it forgets anything ------------------
   *
   * The button cleared the BROWSER's copy and said "remembered lookups thrown
   * away". Every answer this page produces is POSTed to /api/places,
   * loadPlaces() GETs the whole set back, and load() runs on the next press of
   * Load AND when the page opens - so the one control that can remove a bad
   * geocode undid itself on the first thing anyone pressed after it.
   *
   * LAST, deliberately: it empties the cache every stage above depends on.
   * Put after `place` it moved "a second run re-asks only what it could not
   * ask the first time" from 1 question to 3 - the check reading an emptied
   * cache rather than a fault in the page. */
  stage = 'forget';
  out.forget = { before: Object.keys(
    (await (await fetch(base + '/api/places')).json()).places || {}).length };
  await page.click('#forget');
  await page.waitForFunction(
    () => /thrown away|only/.test(document.getElementById('status').textContent),
    null, { timeout: 15000 }).catch(() => {});
  out.forget.said = await page.evaluate(
    () => document.getElementById('status').textContent.trim());
  out.forget.after = Object.keys(
    (await (await fetch(base + '/api/places')).json()).places || {}).length;
  out.forget.here = await page.evaluate(() => Object.keys(JSON.parse(
    localStorage.getItem('uberscan.geocode.v1') || '{}')).length);

  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.log(JSON.stringify(
  // A throw anywhere in this driver is a FAULT, not a machine that
  // could not run the checks. Reported as `skip` it exited 0 and the
  // whole suite counted as passed with nothing run. The one real skip
  // — no chromium — is printed above, before anything can throw.
  { __crashed: String((e && e.stack) || e) })); });
'''

if shutil.which('node') is None:
    skip('no node on this machine')

work = tempfile.mkdtemp()
journal = os.path.join(work, 'journal.jsonl')
with open(journal, 'w') as fh:
    for row in ROWS:
        fh.write(json.dumps(row) + '\n')
    # ...and which of them the driver actually ran, which is the only thing
    # that may be joined into a route. A journal is mostly offers that were
    # turned down, and chaining those in time order would draw a picture of a
    # shift that never happened.
    #
    # Five, chosen to cover every branch of the chain in one shift:
    #   o4  oldest, and its dropoff landed in Idaho — the chain has to leave
    #       from the end that is not a stray, or the empty miles it quotes come
    #       out eighteen hundred instead of twenty;
    #   o2  both ends real and far apart;
    #   o1  dropoff the geocoder never heard of, so one usable end;
    #   o0  both ends real;
    #   o5  neither end placeable, and newest — a taken job that cannot be
    #       drawn must still be counted, and counting it off the running tally
    #       would lose it precisely because it came last.
    #   o3  taken, and placeable nowhere — the stub has never heard of Zaxbys
    #       and the card gave no destination — sitting in time BETWEEN two that
    #       can be placed. That is the mid-chain gap: the hop that spans it did
    #       not have the car driving straight from one of its ends to the
    #       other, so its straight line is not a distance anybody drove and the
    #       headline must not count it as empty miles.
    for oid in ('o0', 'o1', 'o2', 'o3', 'o4', 'o5'):
        fh.write(json.dumps({'v': 1, 'kind': 'mark', 'at': NOW,
                             'id': oid, 'accepted': True}) + '\n')

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
        crashed(proc.stderr)
    # A hang first, and separately, because the two mean opposite
    # things — see hung().
    # A throw in the driver, which the catch at its foot now reports as
    # its own thing rather than as a skip.
    if got.get('__crashed'):
        crashed(got['__crashed'])
    if got.get('__hung'):
        hung(got['__hung'])
    if got.get('skip'):
        skip(got['skip'])

    on_load = got.get('onLoad') or {}
    placed = got.get('placed') or {}

    # --- the one control that can remove a bad geocode ---------------------
    #
    # It cleared the browser's copy and said "remembered lookups thrown away".
    # Every answer this page produces is POSTed to /api/places, loadPlaces()
    # GETs the whole set back, and load() runs on the next press of Load AND
    # when the page opens - so the button undid itself on the first thing
    # anyone pressed after it, silently, and a driver watching a bad pin come
    # back had no way to know why.
    forget = got.get('forget') or {}
    ok_('the placing filled the server cache first', (forget.get('before') or 0) > 0)
    eq('...and Forget lookups empties it there too', forget.get('after'), 0)
    eq('...and on the device', forget.get('here'), 0)
    ok_('...and says it reached the server, not just this browser (%r)'
        % (forget.get('said') or '')[:70], 'server' in (forget.get('said') or ''))

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
    ok_('the page counts the offers it loaded (%r)' % status, '33 offers' in status)
    ok_('...how many name somewhere', '33 name somewhere' in status)
    ok_('...and how many name both ends', '5 name both ends' in status)
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
    # ...and the accusation does not put the rig's own repair in the card's
    # mouth. o2 is both accused and corrected, which is the commoner half of
    # this section on the real week: 262 of 579 drawable pairs are corrected.
    # A driver sent back to the screen to check "3 mi" against a card that
    # printed 30 concludes the page is broken.
    # Bounded to the section: `side` is the whole sidebar and the sections
    # below this one legitimately say "card said" about pairs whose figure the
    # card really did state.
    _wrong_at = side.find('cannot be right')
    _wrong_end = side.find('could not be checked', _wrong_at)
    _wrong = side[_wrong_at:(_wrong_end if _wrong_end > 0 else len(side))]
    # The blanket note must not attribute to the card at all: it stands over
    # every row in the section, and 262 of the owner's 579 drawable pairs
    # carry a figure the card did not print.
    no_('the accusation’s note does not attribute the figure to the card (%r)'
        % _wrong[:100], 'the card stated' in _wrong)
    ok_('...saying whose figure it is instead', 'this reading carries' in _wrong)
    # ...and the corrected pair's own row says so, while the pair whose figure
    # the card really did state keeps the plain wording. Both are in this
    # section, which is why a flat "no 'card said' here" would be wrong.
    ok_('the repaired pair’s row says a decimal was put back', 'put back' in _wrong)
    ok_('...and the pair the card really did state keeps the plain wording',
        'card said' in _wrong)

    # --- ...and only where the card's figure is a yardstick -----------------
    #
    # o32 is Marietta to Atlanta carrying three miles, which the rule above
    # accuses on sight. Its reading never finished — a leg lost its distance —
    # so those three miles are a fraction of the journey, and a straight line
    # beating a fraction says nothing about either pin. Under the old rule this
    # was a third red dashed line and a third row under "cannot be right".
    _pops = placed.get('linePopups') or []
    eq('a pair whose card figure is only part of the journey is drawn plainly',
       len([p for p in _pops if 'only part of this card was read' in p]), 1)
    ok_('...and is not among the lines marked impossible (%d dashed)'
        % (placed.get('impossible') or 0),
        (placed.get('impossible') or 0) == 2)
    ok_('...with the accusation withheld rather than made (%r)'
        % ([p for p in _pops if 'only part of this card was read' in p] or [''])[0][:120],
        all('cannot be right' not in p
            for p in _pops if 'only part of this card was read' in p))
    ok_('...and the reason on the line itself, not only in a list',
        any('fraction of the journey' in p for p in _pops))
    # Withdrawn, not vanished. A pair that silently stops being checked looks
    # exactly like a pair that was checked and passed, which is the second
    # fault class dressed as a fix for the first.
    ok_('...and counted in the sidebar under its own heading (%r)'
        % side[side.find('could not be checked') - 3:][:80],
        '1 that could not be checked' in side)
    ok_('...saying why a fraction of a journey settles nothing',
        'loses that comparison every time' in side)
    ok_('...and naming the pair it is about', 'Canton Rd, Marietta' in side)
    # ...and saying WHOSE figure the one it is not checking is. MV.unchecked
    # phrases it "its N mi", which attributes to the card by default, and on
    # the real week 12 of the 14 rows this section fires on carry a figure the
    # rig repaired. Without this check the attribution can be deleted from the
    # row and all 118 checks stay green — which is what it did.
    _nc = side[side.find('could not be checked'):]
    ok_('the withheld row says whose figure it is not checking (%r)' % _nc[:110],
        'card said' in _nc or 'put back' in _nc)

    # --- and whose figure the line is measured against ----------------------
    #
    # o0's distance is the rig's repair, not the card's: check_distance divides
    # by ten to put back a decimal the read lost. Every surface printed that as
    # "card said 9 mi total", and the card said 90 — on 328 of the owner's
    # 1,166 offers, 262 of the 579 that name both ends. A driver who goes back
    # to the card to settle which pin is wrong finds a different number and
    # concludes the page is broken.
    # Two of them now: o0, which is corrected and drawn plainly, and o2, which
    # is corrected AND accused. The second is the combination the accusation
    # sidebar had no cover for, and on the real week it is the commoner half of
    # that section — 262 of 579 drawable pairs are corrected.
    _fixed = [p for p in _pops if 'decimal' in p]
    eq('every repaired distance says so rather than being quoted as the card’s'
       ' (%r)' % (_fixed or [''])[0][:90], len(_fixed), 2)
    ok_('...and none of them claims the card said it',
        all('card said' not in p for p in _fixed))
    # Each gives ITS OWN figure, not just one of them: a check that only looks
    # at _fixed[0] passes while the other prints nothing to check against.
    ok_('...while each still gives the figure its line was measured against',
        all(any(f + ' mi total' in p for f in ('9', '3')) for p in _fixed)
        and any('9 mi total' in p for p in _fixed)
        and any('3 mi total' in p for p in _fixed))
    # The ordinary case keeps the ordinary wording. Without this the change
    # could have replaced one blanket claim with another.
    ok_('...and a figure the card really did state is still the card’s (%r)'
        % ([p for p in _pops if 'card said' in p] or [''])[0][:80],
        any('card said' in p and 'decimal' not in p for p in _pops))

    ok_('a place the geocoder never found is listed rather than dropped',
        'could not find' in side)
    ok_('...by the text that was searched for',
        'Nowhere At All Ln' in side)

    # ...and the two kinds of missing pin are told apart. "We asked and there
    # is no such place" is about the OCR; "we never got to ask" is about the
    # network, and only one of them is worth going to look at the rig for.
    ok_('a lookup the network refused is not reported as a place that does '
        'not exist', 'could not be asked' in side)
    ok_('...naming it, so the driver can see which one it was',
        'Unreachable Way' in side)
    # The one that WAS asked stays where it was. A split that swept everything
    # into the new heading would pass both checks above and say nothing.
    _find_at = side.find('could not find')
    _ask_at = side.find('could not be asked')
    ok_('...while a place that really was asked stays under "could not find"',
        _find_at != -1 and _ask_at != -1
        and _find_at < side.find('Nowhere At All Ln') < _ask_at)

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
        'of 5 drawn end to end' in status2)

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
    ok_('...with the number of offers on it (%r)' % (here and here[0].get('count')),
        here and here[0].get('count') == '3')
    # OFFERS, not jobs. Most offers are turned down, so a pin reading 12 on a
    # shop the driver took two from said they had worked there twelve times —
    # a fact about the rig's scanning, wearing the clothes of a fact about the
    # driver's evening.
    ok_('...and the count said in the popup as well',
        here and '3 offers' in (here[0].get('popup') or ''))
    # ...and what became of them, in the three states the data really has. Two
    # of these three cards are ticked as taken in the fixture above; the third
    # was never marked, and "0 taken" over an unmarked card reads as a refusal,
    # which is the same wrong reporting one level down.
    ok_('...with how many of them were taken (%r)'
        % (here and (here[0].get('popup') or '')[:160]),
        here and 'you took' in (here[0].get('popup') or ''))
    # All three of this place's offers are ticked in the fixture above, so this
    # says three took and nothing else. The unmarked and passed-on wordings are
    # checked in tests/mapview.test.js, where a fixture costs nothing — here
    # they would mean un-ticking a card the chain checks depend on.
    ok_('...as all three of them, since all three are ticked',
        here and '3 you took' in (here[0].get('popup') or ''))
    no_('...and nothing is claimed about offers that were passed on',
        here and 'passed on' in (here[0].get('popup') or ''))

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
    # The number, not the word around it. A check for "old" passes on the
    # sentence with the figure taken out of it, which is the whole of what
    # this is for — 1.2 seconds is nothing and 20 is half a mile at fifty
    # miles an hour.
    ok_('...saying how old each fix was (%r)' % (trail.get('popups') or [''])[0],
        all('fix was 1.2s old' in p for p in (trail.get('popups') or [''])))
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

    # --- the miles nobody paid for ------------------------------------------
    #
    # Five jobs were ticked as taken. Four of them can be put somewhere, so
    # three hops join them; the fifth can be put nowhere and is stepped over
    # rather than breaking the chain or disappearing from the reckoning.
    chain = got.get('chain') or {}
    eq('nothing is joined up until it is asked for', got.get('beforeChain'),
       (got.get('placed') or {}).get('lines'))
    eq('...and then the taken jobs are joined in order', chain.get('hops'), 3)
    ok_('...in a colour of their own, so a hop is not read as a paid mile (%r)'
        % (chain.get('colours'),),
        (chain.get('colours') or []) and all(c == '#c084fc' for c in chain['colours']))
    ok_('...and dashed, because nothing was measuring this run', chain.get('dashed'))
    ok_('...and the button says it is on', chain.get('pressed') == 'true')
    eq('...and the job pins are untouched by any of it',
       chain.get('pins'), (got.get('placed') or {}).get('pins'))

    # THE check on this feature. The oldest taken job ended, according to the
    # card, on a street the geocoder answered with Boise. Chaining to that pin
    # would quote eighteen hundred empty miles for a shift inside one metro,
    # and — worse — draw the evening as a trip to Idaho and back. The job is
    # still in the chain; it is joined by the end that is not a stray.
    pts = chain.get('pts') or []
    ok_('no hop is drawn to the pin in another state (%r)' % (pts,),
        pts and all(abs(float(p[0]) - 43.615) > 0.01
                    for line in pts for p in line))
    status3 = chain.get('status') or ''
    ok_('the empty miles are totalled where they can be read (%r)' % status3,
        'nobody paid for' in status3)
    # Twenty-ish miles of it, Atlanta back up to Chastain and across to
    # Kennesaw. The figure is the point: a chain that reached Boise would put
    # this near two thousand and the sentence around it would be unchanged.
    _miles = re.search(r'([\d.]+) straight-line miles', status3)
    ok_('...counting the jobs it joined', '3 hops between 6 jobs' in status3)
    # THE arithmetic. A stacked hop's own popup says in as many words that it
    # "is not an empty run", and the total above it was folding that hop's
    # miles into "miles nobody paid for" — the same question answered two ways
    # on the same line, inflated exactly on the shifts where the driver stacked
    # well, which is the reading this toggle exists to support.
    ok_('stacked miles are reported apart from the empty ones (%r)' % status3,
        'did not drive empty' in status3)
    _stacked = re.search(r'([\d.]+) mi across (\d+) stacked pair', status3)
    ok_('...as their own figure and count (%r)'
        % (_stacked and _stacked.group(0)),
        _stacked and int(_stacked.group(2)) >= 1)

    pops = chain.get('popups') or []

    # THE cross-check, and the shape of the fault it replaces: the headline and
    # the popups were answering the same question two ways on the same line.
    # Each popup states its own miles and says whether it was a stack or had a
    # job missing inside it, so the headline's "nobody paid for" figure is
    # DERIVABLE from them — and a range check on it is not, which is how the
    # old total passed while folding in miles its own popups called not empty.
    _hops = []
    for _p in pops:
        _m = re.search(r'straight line ([\d.]+) mi', _p)
        if not _m:
            continue
        _hops.append((float(_m.group(1)), 'a stack' in _p,
                      'could not be put on' in _p))
    eq('every hop drawn states its own miles', len(_hops), len(pts))
    # The Boise guard, moved off the headline and onto the whole chain. A hop
    # drawn to the pin in another state would put this near two thousand, and
    # every sentence around it would be unchanged. It is checked on the TOTAL
    # rather than on one of the three figures, because which bucket such a hop
    # lands in depends on flags that have nothing to do with the mistake.
    ok_('the whole chain is a shift inside one metro, not a trip to Idaho '
        '(%.1f mi)' % sum(m for m, _s, _x in _hops),
        5.0 < sum(m for m, _s, _x in _hops) < 75.0)
    _wantEmpty = sum(m for m, st, miss in _hops if not st and not miss)
    _wantStack = sum(m for m, st, miss in _hops if st and not miss)
    ok_('the headline counts exactly the hops its own popups call empty '
        '(%r vs %.1f)' % (_miles and _miles.group(1), _wantEmpty),
        _miles and abs(float(_miles.group(1)) - _wantEmpty) < 0.15)
    ok_('...and the stacked figure counts exactly the ones they call stacks '
        '(%r vs %.1f)' % (_stacked and _stacked.group(1), _wantStack),
        _stacked and abs(float(_stacked.group(1)) - _wantStack) < 0.15)
    _over = re.search(r'([\d.]+) mi across (\d+) hop.? with a job missing', status3)
    _wantOver = sum(m for m, st, miss in _hops if miss)
    ok_('...and the third figure counts exactly the ones with a job missing '
        'inside (%r vs %.1f)' % (_over and _over.group(1), _wantOver),
        _over and abs(float(_over.group(1)) - _wantOver) < 0.15)
    # ...and the fixture really does carry one hop of each kind, or all three
    # checks above would pass with the arithmetic put back the way it was.
    ok_('the shift contains a stacked hop, an empty one, and one with a job '
        'missing (%r)' % (_hops,),
        any(st and not miss for _m, st, miss in _hops)
        and any(not st and not miss for _m, st, miss in _hops)
        and any(miss for _m, st, miss in _hops))
    # ...and so is a hop the car did not drive end to end, because a job it
    # could not place is sitting inside it.
    _over = re.search(r'([\d.]+) mi across (\d+) hop.? with a job missing', status3)
    ok_('...and a hop with a job missing inside it is not counted as empty either (%r)'
        % (_over and _over.group(0)), bool(_over))
    # A taken job that could not be put anywhere is not quietly dropped. It is
    # the newest of the five, which is exactly the one a running tally loses.
    ok_('...and saying the taken jobs it could not place were stepped over (%r)'
        % status3, '2 taken jobs have no pin' in status3)

    # What a hop SAYS is half of what it is for. A driver reading these is
    # deciding whether the second offer was worth taking, and the two facts
    # that answer that are how far apart the ends were and whether the next
    # card came up while the last job was still running.
    ok_('a hop says where it left and where it arrived (%r)' % (pops[:1],),
        pops and any('Peachtree' in p and 'Chastain' in p for p in pops))
    ok_('...how far that was with nobody in the car',
        pops and all('with nobody in the car' in p for p in pops))
    # The rig's only clock is when each CARD CAME UP. Worded as drive time it
    # would be a measurement invented out of two unrelated timestamps.
    ok_('...and says which clock that is, rather than implying drive time',
        pops and all('between the two offers coming up' in p for p in pops))
    # A second offer that came up mid-job is the case where the line is NOT an
    # empty run, and saying nothing about it would let a driver read a second
    # pickup on the way as a dead run across the metro. Not all of them: the
    # five-minute card above is deliberately over before the next one arrives.
    ok_('...and a second offer that came up mid-job is called a stack',
        pops and any('a stack' in p for p in pops))
    ok_('...while one that came up after the last job was due to end is not',
        pops and any('a stack' not in p for p in pops))

    eq('turning it off takes the dashes away', (got.get('chainOff') or {}).get('lines'),
       (got.get('chainOff') or {}).get('was'))
    ok_('...and says so rather than leaving the last total standing (%r)'
        % (got.get('chainOff') or {}).get('status'),
        'hidden' in ((got.get('chainOff') or {}).get('status') or ''))
    eq('...and turning it on again draws them once, not twice',
       got.get('chainAgain'), 3)

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

    # --- asking twice costs nothing, except what could not be asked --------
    #
    # Everything that was ANSWERED is remembered and not asked again, which is
    # what makes re-checking a map free. The one place the network refused is
    # deliberately not remembered — a transport failure stored as "no such
    # place" is a wrong answer kept forever, and the driver would have to know
    # to clear the cache to undo a tunnel. So it, and only it, is asked again.
    #
    # A count rather than "more than zero": if this ever reads 2 the wide
    # retry has started firing on it, and if it reads 27 the cache has stopped
    # working and the reason would be hidden by a looser check.
    eq('a second run re-asks only what it could not ask the first time',
       (got.get('again') or {}).get('newQuestions'), 1)

finally:
    server.terminate()
    try:
        server.wait(timeout=5)
    except Exception:
        server.kill()
    shutil.rmtree(work, ignore_errors=True)

# ---------------------------------------------------------------------------
# The `when` box: asking the map about a time.
# ---------------------------------------------------------------------------
#
# Its own journal and its own server, because every count above is pinned to
# the fixture above and a row added there to make two blocks would move a
# hundred of them.
#
# WHY THERE IS NO WEEKDAY BOX BESIDE IT, measured on the owner's real week and
# recorded here so it is not proposed again: `days` defaults to 7, a 168-hour
# window holds each weekday-and-block exactly once, and all thirteen occupied
# cells of that grid came off a single calendar date apiece. A "Fri" option
# would be a date picker wearing a habit's clothes. What the box says instead
# is how many separate days are behind the answer, which is the claim that
# actually needs checking — and that is what is checked here.

BLOCK_MS = 3 * 3600000


def _block_base():
    """The start of the 3-hour block before the current one, local time.

    Computed rather than hard-coded so these rows fall in known blocks
    whatever hour the suite is run at, and in the past whatever hour that is.
    The page reads local hours off the browser's clock, which is this
    machine's clock, so Python and the page agree by construction.
    """
    now = time.localtime()
    start = time.mktime((now.tm_year, now.tm_mon, now.tm_mday,
                         (now.tm_hour // 3) * 3, 0, 0, 0, 0, -1)) * 1000
    return start - BLOCK_MS


WBASE = _block_base()

# Three taken jobs, arranged so that filtering to one block leaves a hop with a
# taken job inside it that the filter — and only the filter — is hiding.
# Within one day that cannot happen: a block is a contiguous stretch of clock,
# so nothing can fall between two of its own rows. Across two days it can, and
# does, six times on the owner's real week.
#
#   wa1  yesterday, in block A      shown when block A is picked
#   wb1  today, in block B          HIDDEN when block A is picked
#   wa2  today, in block A          shown when block A is picked
#
# So the hop wa1 -> wa2 has a job the driver took sitting inside it, and
# MV.chain cannot know: it is handed the offers on the glass, so wb1 is not in
# `taken` and cannot raise `skipped`, which is silent at zero. The violet line
# between two of this driver's own jobs is the one mark on the page that would
# be read as a distance they actually drove.
WHEN_ROWS = [
    offer(60, 'Cobb Pkwy NW, Kennesaw', 'Canton Rd, Marietta', 9.0,
          at=int(WBASE - 86400000 + 600000)),
    # Block B, and the only row that names Acworth — so picking block A takes
    # a PIN off the map and not only a row out of a count. A fixture whose
    # blocks share all their places would pass a filter that changed the
    # sentence and drew the same map.
    # ...and it carries a position, where o62 in block A does not. Where the
    # car WAS is the one thing on this page that is measured rather than
    # looked up, and a whole window of those dots left standing under a
    # three-hour map is the previous card's pins left up under this one's —
    # which this project already refuses on the driving panel.
    offer(61, 'Acworth Due West Rd NW', 'Peachtree St NE, Atlanta', 12.0,
          at=int(WBASE - 2 * 3600000), where=(34.066, -84.677)),
    offer(62, 'Cobb Pkwy NW, Kennesaw', 'Peachtree St NE, Atlanta', 20.0,
          at=int(WBASE + 40 * 60000), where=(34.023, -84.615)),
    # A third row in block A, on the SAME day as o62, so the figure the box
    # prints is a count of days and not of rows: three offers, two days.
    # ...and it names no destination, which is the shape most of this driver's
    # real traffic has — 129 of 272 on the older export — so the sidebar's
    # "with no dropoff at all" heading has something to count inside a block.
    offer(63, 'Canton Rd, Marietta', None, 4.0,
          at=int(WBASE + 10 * 60000)),
    # ...and a SECOND one with no destination, in block B. Without it the
    # window and the block hold the same number of them and a count over the
    # wrong one of the two reads correctly by coincidence — which is how a
    # check that cannot fail gets written.
    offer(64, 'Acworth Due West Rd NW', None, 3.0,
          at=int(WBASE - 90 * 60000)),
    # A misread street the geocoder answers in Idaho, in block B. The stray
    # list is an ACCUSATION against a lookup, and the box has to carry the
    # accusations that belong to what it is showing and no others: a block
    # that drew no Idaho pin must not head its sidebar "1 nowhere near the
    # rest".
    offer(65, 'W Boise Ave', None, 2.0, at=int(WBASE - 150 * 60000)),
    # A row that names NEITHER end, in block A. 58 of the owner's 1,166 do,
    # and without one here the nag under the box counts against every offer
    # while `placed` can only ever hold the ones that named somewhere — so it
    # says "1 not yet" after a complete walk, for ever, and pressing Place
    # cannot move it. Every other row in this fixture has a pickup, which made
    # that difference structurally zero and the check unwritable.
    offer(66, None, None, 5.0, at=int(WBASE + 25 * 60000)),
]

WHEN_DRIVER = r'''
const { chromium } = require('playwright');
const base = process.argv[2];
const KNOWN = {
  kennesaw: [34.023, -84.615], marietta: [33.952, -84.549],
  atlanta: [33.749, -84.388], chastain: [34.010, -84.580],
  acworth: [34.066, -84.677],
  // Eighteen hundred miles away, answered as confidently as the rest. This is
  // what a geocoder handed a misread street really does, and it is what the
  // stray list is for.
  boise: [43.615, -116.202],
};
const STUB = `
  window.__pins = []; window.__lines = []; window.__dots = [];
  window.L = {
    map: function () { return { setView: function () { return this; },
      removeLayer: function (g) {
        window.__pins = window.__pins.filter(function (p) { return p.group !== g; });
        window.__lines = window.__lines.filter(function (l) { return l.group !== g; });
        window.__dots = window.__dots.filter(function (d) { return d.group !== g; });
      },
      addLayer: function () {}, fitBounds: function () {} }; },
    tileLayer: function () { return { addTo: function () { return this; } }; },
    layerGroup: function () { return { addTo: function () { return this; } }; },
    circleMarker: function (ll) {
      var m = { ll: ll, group: null, bindPopup: function () { return this; },
                addTo: function (g) { this.group = g; window.__dots.push(m); return m; } };
      return m; },
    divIcon: function (o) { return o; },
    marker: function (ll, opts) {
      var m = { ll: ll, group: null, bindPopup: function (h) { this.popup = h; return this; },
                addTo: function (g) { this.group = g; window.__pins.push(this); return this; },
                getLatLng: function () { return this.ll; },
                openPopup: function () { return this; } };
      return m; },
    polyline: function (pts, opts) {
      var l = { pts: pts, opts: opts, group: null,
                bindPopup: function (h) { this.popup = h; return this; },
                addTo: function (g) { this.group = g; window.__lines.push(l); return l; } };
      return l; }
  };
`;

(async () => {
  let browser;
  for (const exe of JSON.parse(process.env.PW_EXES || '[]').concat([null])) {
    try { browser = await chromium.launch(exe ? { executablePath: exe } : {}); break; }
    catch (e) { /* try the next */ }
  }
  if (!browser) { console.log(JSON.stringify({ skip: 'no chromium' })); return; }
  let stage = 'start';
  setTimeout(() => { console.log(JSON.stringify({ __hung: stage })); process.exit(2); },
             180000).unref();

  const page = await browser.newContext({ viewport: { width: 1200, height: 820 } })
    .then((c) => c.newPage());
  await page.addInitScript(STUB);
  // Counted here rather than in the page. A page.evaluate from inside a route
  // handler runs while the page is blocked on the very request being handled,
  // which is a deadlock waiting to be discovered by somebody debugging
  // something else.
  let asked = 0;
  await page.route('**/nominatim.openstreetmap.org/**', async (route) => {
    const q = decodeURIComponent(new URL(route.request().url())
      .searchParams.get('q') || '').toLowerCase();
    asked += 1;
    // Most specific first, and that is not tidiness. The page appends the
    // `near` hint to every query — it fills it from the driver's own cards —
    // so a misread street asked "W Boise Ave, Marietta" contains the name of
    // a town this stub knows, and a first-match-wins stub answers it in
    // Marietta. The pin the stray list exists to catch would then land in
    // Georgia with the rest and the check on it would pass by not running.
    const key = ['boise', 'chastain', 'acworth', 'kennesaw', 'atlanta',
                 'marietta'].filter((k) => q.indexOf(k) >= 0)[0];
    await route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify(key
        ? [{ lat: String(KNOWN[key][0]), lon: String(KNOWN[key][1]), display_name: key }]
        : []) });
  });
  await page.route('**/tile.openstreetmap.org/**', (r) => r.fulfill({ status: 200, body: '' }));
  await page.route('**/unpkg.com/**', (r) => r.fulfill({ status: 200, body: '' }));

  const out = {};
  stage = 'load';
  await page.goto(base + '/map.html', { waitUntil: 'domcontentloaded' }).catch(() => {});
  await page.waitForFunction(
    () => !/loading/.test(document.getElementById('status').textContent || ''),
    null, { timeout: 30000 });

  // The lookup count travels with every reading, because "moving the box
  // asked nothing" is only a claim if the two counts came from the same kind
  // of measurement at both ends.
  const look = async () => Object.assign(await page.evaluate(() => ({
    status: document.getElementById('status').textContent || '',
    pins: window.__pins.length,
    lines: window.__lines.map(function (l) { return l.popup || ''; }),
    dots: window.__dots.length,
    // The sidebar's headings, which are counts over the offers the page is
    // SHOWING. Each one is a sentence a driver reads as being about the map
    // in front of them.
    heads: [].slice.call(document.querySelectorAll('#sideBody h2'))
      .map(function (h) { return (h.textContent || '').trim(); }),
  })), { asked: asked });

  out.box = await page.evaluate(() => {
    const sel = document.getElementById('block');
    return sel ? { options: [].slice.call(sel.options).map((o) => o.textContent),
                   value: sel.value } : null;
  });

  // THE saving, and it only exists before anything is cached: a walk is one
  // question a second and the owner's week is 1,325 distinct places, about
  // twenty-four minutes. Picking a block first is what turns that into the
  // 3.9 to 9.5 minutes each of that week's live blocks costs.
  stage = 'a block, placed first';
  await page.selectOption('#block', String(process.env.BLOCK_A));
  await page.waitForTimeout(250);
  await page.click('#place');
  await page.waitForFunction(
    () => /drawn end to end/.test(document.getElementById('status').textContent || ''),
    null, { timeout: 60000 });
  out.blockFirst = await look();
  await page.selectOption('#block', '');
  await page.waitForTimeout(250);

  // Widened WITHOUT pressing Place again: the window now spans jobs the last
  // walk never looked up. The chain has to say so rather than report 0.0 miles
  // over them or deny they were taken.
  stage = 'widened without re-placing';
  await page.click('#chain');
  await page.waitForTimeout(300);
  out.widened = await look();
  out.widenedStatus = await page.evaluate(
    () => document.getElementById('status').textContent || '');
  out.widenedHops = await page.evaluate(() =>
    [].slice.call(document.querySelectorAll('.leaflet-popup-content'))
      .map((n) => (n.textContent || '').trim()));
  await page.click('#chain');
  await page.waitForTimeout(200);

  stage = 'any time, placed';
  await page.click('#place');
  await page.waitForFunction(
    () => /drawn end to end/.test(document.getElementById('status').textContent || ''),
    null, { timeout: 60000 });
  out.all = await look();
  await page.click('#chain');
  await page.waitForTimeout(300);
  out.allChain = await look();
  out.allChainStatus = await page.evaluate(
    () => document.getElementById('status').textContent || '');

  // Where the car was, on, so the block below is picked with it showing —
  // which is the state in which a stale dot would actually be seen.
  stage = 'the trail';
  await page.click('#trail');
  await page.waitForTimeout(300);
  out.allTrail = await look();

  stage = 'block A';
  await page.selectOption('#block', String(process.env.BLOCK_A));
  await page.waitForTimeout(400);
  out.blockA = await look();

  // ...and what the trail SAYS about itself under the filter, which is a
  // different line from the dots it draws and was wrong while they were right.
  await page.click('#trail');
  await page.waitForTimeout(150);
  await page.click('#trail');
  await page.waitForTimeout(250);
  out.blockATrail = await look();

  // The chain's own headline under the filter. It is got by pressing the
  // toggle, the way it is got at any other time: moving the `when` box says
  // what the box did — including how many separate days are behind the answer,
  // which is the one sentence on this page that must not be crowded out — and
  // does not restate a figure the driver did not just ask for.
  await page.click('#chain');
  await page.waitForTimeout(150);
  await page.click('#chain');
  await page.waitForTimeout(300);
  out.blockAChain = await look();

  stage = 'block B';
  await page.selectOption('#block', String(process.env.BLOCK_B));
  await page.waitForTimeout(400);
  out.blockB = await look();

  stage = 'an empty block';
  await page.selectOption('#block', String(process.env.BLOCK_EMPTY));
  await page.waitForTimeout(400);
  out.blockEmpty = await look();

  stage = 'back to any time';
  await page.selectOption('#block', '');
  await page.waitForTimeout(400);
  out.backToAll = await look();

  // Pressing Load with a block already picked. The box is not reset by a
  // load, so the counts the page reports after one have to be the block's.
  stage = 'reload under a block';
  await page.selectOption('#block', String(process.env.BLOCK_A));
  await page.waitForTimeout(250);
  await page.click('#load');
  await page.waitForFunction(
    () => !/loading/.test(document.getElementById('status').textContent || ''),
    null, { timeout: 30000 });
  await page.waitForTimeout(300);
  out.reloaded = await look();
  await page.selectOption('#block', '');
  await page.waitForTimeout(250);

  console.log(JSON.stringify(out));
  await browser.close();
})().catch((e) => { console.log(JSON.stringify({ __crashed: String((e && e.stack) || e) })); });
'''

work2 = tempfile.mkdtemp()
journal2 = os.path.join(work2, 'journal.jsonl')
with open(journal2, 'w') as fh:
    for row in WHEN_ROWS:
        fh.write(json.dumps(row) + '\n')
    for oid in ('o60', 'o61', 'o62'):
        fh.write(json.dumps({'v': 1, 'kind': 'mark', 'at': int(WBASE),
                             'id': oid, 'accepted': True}) + '\n')

port2 = free_port()
server2 = subprocess.Popen(
    ['node', os.path.join(ROOT, 'server.js')],
    env=dict(os.environ, SCANNER='0', PORT=str(port2), JOURNAL=journal2),
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
base2 = 'http://127.0.0.1:%d' % port2

_hour = time.localtime(WBASE / 1000).tm_hour
BLOCK_A = _hour // 3
BLOCK_B = (_hour - 2) // 3 if (_hour - 2) >= 0 else ((_hour - 2) % 24) // 3
# A block with nothing in it, which must exist for the empty case to be
# reachable: four rows cannot fill eight blocks.
BLOCK_EMPTY = [b for b in range(8) if b not in (BLOCK_A, BLOCK_B)][0]

try:
    for _ in range(120):
        try:
            urllib.request.urlopen(base2 + '/api/status', timeout=1).read()
            break
        except Exception:
            time.sleep(0.1)
    else:
        raise RuntimeError('the second server never came up')

    driver2 = os.path.join(work2, 'whendrive.js')
    open(driver2, 'w').write(WHEN_DRIVER)
    proc2 = subprocess.run(
        ['node', driver2, base2],
        env=dict(os.environ, NODE_PATH=os.pathsep.join(NODE_PATHS),
                 BLOCK_A=str(BLOCK_A), BLOCK_B=str(BLOCK_B),
                 BLOCK_EMPTY=str(BLOCK_EMPTY),
                 PW_EXES=json.dumps([
                     os.environ.get('CHROMIUM', ''),
                     '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
                 ])),
        capture_output=True, text=True, timeout=600)
    line2 = (proc2.stdout or '').strip().split('\n')[-1] if proc2.stdout else ''
    try:
        w = json.loads(line2)
    except Exception:
        crashed(proc2.stderr)
    if w.get('__crashed'):
        crashed(w['__crashed'])
    if w.get('__hung'):
        hung(w['__hung'])
    if w.get('skip'):
        skip(w['skip'])

    # --- the box itself ----------------------------------------------------
    box = w.get('box')
    ok_('the map can be asked about a time at all', box is not None)
    if box:
        eq('...with the eight blocks the offer log draws its chart on, '
           'and "any time"', len(box['options']), 9)
        # The NAMES, from Advice.BLOCK_NAMES, because this box and that chart
        # cut the same week and a page keeping its own copy of eight edges is
        # where two answers to one question come from.
        eq('...named exactly as the offer log names them',
           box['options'][1:],
           ['12\u20133am', '3\u20136am', '6\u20139am', '9am\u201312',
            '12\u20133pm', '3\u20136pm', '6\u20139pm', '9pm\u201312'])
        eq('...and it opens on any time, so the page is what it was',
           box['value'], '')

    # --- it reaches the map, not only the status line ----------------------
    allv, a, b = w.get('all') or {}, w.get('blockA') or {}, w.get('blockB') or {}
    ok_('the whole window draws pins (%r)' % allv.get('pins'), allv.get('pins', 0) >= 4)
    ok_('...and picking a block draws fewer (%r vs %r)'
        % (a.get('pins'), allv.get('pins')),
        0 < a.get('pins', 0) < allv.get('pins', 0))
    eq('...and going back to any time puts them all back',
       (w.get('backToAll') or {}).get('pins'), allv.get('pins'))

    # --- how many separate days are behind the answer ----------------------
    #
    # THE check on this feature. Two blocks, two offers each on the owner's
    # scale, and the difference between them is the whole claim: one rests on
    # two separate days and one rests on one, and a map that showed them
    # identically would let a single evening be read as a habit. On the real
    # week the three busiest blocks pool three evenings each and 3–6am is 33
    # offers all belonging to one night.
    ok_('a block spanning two days says so (%r)' % (a.get('status') or '')[:110],
        'separate days of it are in this window' in (a.get('status') or ''))
    # Two, over THREE offers, which is what makes it a count of days.
    ok_('...and says how many (%r)' % (a.get('status') or '')[:110],
        '2 separate days' in (a.get('status') or ''))
    ok_('...over more offers than that, or it is counting rows (%r)'
        % (a.get('status') or '')[:40], (a.get('status') or '').startswith('4 offers'))
    # ...and the nag under the box does NOT ask for a lookup that cannot
    # happen. `missing` counted against every offer while `placed` can only
    # hold the ones that named somewhere, so o66 — which names neither end,
    # the shape 58 of the owner's 1,166 rows have — read as "1 not yet" after
    # a COMPLETE walk, for ever, and pressing Place could not move it.
    no_('a complete walk leaves nothing "not yet" (%r)'
        % (a.get('status') or '')[:70], 'not yet' in (a.get('status') or ''))
    ok_('...while still counting what it did look up (%r)'
        % (a.get('status') or '')[:70],
        'already looked up' in (a.get('status') or ''))
    ok_('a block that is really one day says THAT, in words (%r)'
        % (b.get('status') or '')[:110],
        'that is a day, not a habit' in (b.get('status') or ''))
    # ...and the two wordings are not both always printed.
    no_('...and the two-day block does not also call itself one day',
        'not a habit' in (a.get('status') or ''))
    no_('...and the one-day block does not claim separate days',
        'separate days' in (b.get('status') or ''))
    ok_('...and each names the block it is talking about (%r)'
        % (a.get('status') or '')[:60], ' only, and ' in (a.get('status') or ''))

    # A block with nothing in it says so rather than drawing an empty map in
    # silence, which is this project's second fault class.
    e = w.get('blockEmpty') or {}
    eq('an empty block draws nothing', e.get('pins'), 0)
    ok_('...and says there is nothing there (%r)' % (e.get('status') or '')[:90],
        'no day in this window has any' in (e.get('status') or ''))

    # --- the walk itself is narrowed, which is the only thing this saves ---
    #
    # The box is a filter on a page whose expensive act is a rate-limited walk
    # over every distinct place in the window: 1,325 of them on the owner's
    # real week, about twenty-four minutes at GAP_MS. Picking the block first
    # is what makes that 3.9 to 9.5 minutes for each of the five blocks that
    # week actually has offers in. A page that drew the block but walked the
    # window would look identical and cost the same as no filter at all.
    bf = w.get('blockFirst') or {}
    ok_('placing with a block picked walks only that block (%r asked, then %r '
        'for the whole window)' % (bf.get('asked'), allv.get('asked')),
        (bf.get('asked') or 0) > 0
        and (bf.get('asked') or 0) < (allv.get('asked') or 0))

    # --- Load, with the box already on a block -----------------------------
    #
    # The box survives a load — it is a question about the journal, not about
    # one fetch — so every figure the page prints after one is a figure about
    # the block. This is the sentence the driver reads first.
    # --- the window widened without walking it again ------------------------
    #
    # Picking a block BEFORE the first press is the flow this feature
    # advertises — it cuts the first walk from 24 minutes to a few. Widening
    # afterwards then leaves the window spanning jobs the last walk never
    # looked up, and `hidden` is defined as "the box is hiding it", which is
    # false at "any time". So the chain said "0.0 straight-line miles nobody
    # paid for" over a hop with a taken job inside it and nothing else. That is
    # the second fault class, and it is the same fault the narrow direction was
    # fixed for, ninety degrees away — the driver only ever exercises the
    # narrow one.
    _wd = w.get('widenedStatus') or ''
    ok_('the chain says a hop spans a job it never looked up (%r)' % _wd[:130],
        'missing inside' in _wd)
    ok_('...rather than reporting the hop as empty road',
        '0.0 straight-line miles nobody paid for' not in _wd
        or 'missing inside' in _wd)

    rl = (w.get('reloaded') or {}).get('status') or ''
    ok_('loading with a block picked counts the block (%r)' % rl[:100],
        rl.startswith('4 offers · '))
    ok_('...and still says how many days are behind it (%r)' % rl[:110],
        '2 separate days of it are in this window' in rl)

    # --- an accusation belongs to what is on the glass ---------------------
    #
    # A stray is this page accusing a LOOKUP of being wrong, and the list is
    # tappable so the driver can go and judge it. Carrying the window's
    # accusations into a block that drew none of them would head the sidebar
    # "1 nowhere near the rest" over a map with nothing wrong on it.
    heads = ' | '.join(a.get('heads') or [])
    allHeads = ' | '.join(allv.get('heads') or [])
    ok_('the whole window accuses the Idaho lookup (%r)' % allHeads[:70],
        '1 nowhere near the rest' in allHeads)
    ok_('...and a block that drew none of it accuses nothing (%r)' % heads[:70],
        '0 nowhere near the rest' in heads)

    # --- where the car was follows the box too -----------------------------
    #
    # These dots are the one thing on this page that is MEASURED rather than
    # looked up, and they are the only thing that can contradict a pin without
    # being the same kind of thing as the pin. A whole window of them left
    # standing under a three-hour map is the last card's pins left up under
    # this one's, which the driving panel already refuses.
    at = w.get('allTrail') or {}
    eq('the whole window shows every position the rig recorded', at.get('dots'), 2)
    eq('...and a block shows only the ones inside it', a.get('dots'), 1)
    eq('...and going back to any time brings the other one back',
       (w.get('backToAll') or {}).get('dots'), 2)

    # ...and the sentence the trail writes about itself, which is not the same
    # thing as the dots it drew. "2 positions the rig recorded — 2 of these
    # offers carry none" over a map showing one of them is a figure that does
    # not describe what is on screen, which this page has already been fixed
    # for once: see the truncation notice in load().
    tn = (w.get('blockATrail') or {}).get('status') or ''
    ok_('the trail counts the positions in the block, not in the window (%r)'
        % tn[:90], tn.startswith('1 position '))
    # Three, not two, since o66 joined block A: it names neither end and
    # carries no position, which is the shape that made the nag's count
    # checkable at all.
    ok_('...and says how many of THESE offers carry none (%r)' % tn[:90],
        '3 of these offers carry none' in tn)

    # ...and so does the sidebar's own count of cards that named no
    # destination. Most of this driver's traffic is that shape, so it is the
    # heading a reader checks the map against.
    ok_('the sidebar counts the cards with no dropoff inside the block (%r)'
        % heads[-60:], '2 with no dropoff at all' in heads)

    # --- the chain across a job the filter is hiding -----------------------
    #
    # MV.chain is handed the offers on the glass, so a taken job the box
    # removed is not in `taken` and cannot raise `skipped` — and `skipped` is
    # silent at zero, so the hop would assert by omission that the car went
    # straight from one end to the other. Six hops on the owner's real week do
    # exactly this, one of them with seven taken jobs inside it.
    hidden = [t for t in (a.get('lines') or []) if 'outside the time you picked' in t]
    ok_('a hop over a job the box is hiding says so (%d of %d lines)'
        % (len(hidden), len(a.get('lines') or [])), len(hidden) == 1)
    ok_('...naming how many, and that the driver took it (%r)'
        % (hidden[0][-170:] if hidden else None),
        hidden and '1 job you took in between is outside' in hidden[0])
    # ...and it is not a sentence the page always prints, or it says nothing.
    no_('...and no hop says it when no block is picked',
        any('outside the time you picked' in t
            for t in ((w.get('allChain') or {}).get('lines') or [])))
    # The headline has to agree with the popups, which is the arithmetic this
    # page already got wrong once for stacked hops: a hop with a job inside it
    # is not a distance anybody drove, whichever reason it is missing for.
    ac = (w.get('blockAChain') or {}).get('status') or ''
    ok_('...and the headline counts it as a hop with a job missing inside '
        '(%r)' % ac[:170],
        'with a job missing inside' in ac
        and 'missing only because of the time you picked' in ac)
    # ...which means it is NOT in the empty-miles figure. That arithmetic was
    # wrong here once already, for stacked hops, and the fix was to count only
    # the hops that really were empty.
    ok_('...and not in the miles nobody paid for (%r)' % ac[:170],
        '0.0 straight-line miles nobody paid for' in ac)

    # --- and moving the box does not start another walk --------------------
    #
    # The walk is one question a second and the owner's week is 1,325 distinct
    # places, about twenty-four minutes. A box that re-entered it would be
    # unusable — and it would turn the page's two buttons off while it ran,
    # on a page somebody opened to look at a map.
    #
    # Counting the GEOCODER'S questions cannot say this and was tried first:
    # the cache answers a second walk over the same places without asking
    # anybody anything, so a count of questions stays put whether the walk
    # happened or not. That is a check that cannot fail, which is this
    # project's sixth fault class, so it is not the check. What a walk cannot
    # hide is its own report — it ends by writing "N of M drawn end to end"
    # over the status line — so the box's own sentence surviving there is the
    # thing that says no walk ran.
    for label, got_ in (('a block', a), ('an empty one', e),
                        ('and any time again', w.get('backToAll') or {})):
        st = got_.get('status') or ''
        ok_('moving the box to %s starts no second walk (%r)' % (label, st[:60]),
            'offers here' in st or 'offer here' in st)
        no_('...and does not restate a run over it (%r)' % st[:60],
            'drawn end to end' in st)
    ok_('...over a page that really did walk (%r)' % (allv.get('asked'),),
        (allv.get('asked') or 0) >= 4)

finally:
    server2.terminate()
    try:
        server2.wait(timeout=5)
    except Exception:
        server2.kill()
    shutil.rmtree(work2, ignore_errors=True)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d map checks passed' % ok)
sys.exit(1 if bad else 0)
