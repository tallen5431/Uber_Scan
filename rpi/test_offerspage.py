"""What the offers page SAYS, as opposed to how it is laid out.

    python3 rpi/test_offerspage.py

rpi/test_layout.py loads this page at six panel sizes and measures whether it
fits and whether it can be read. Nothing checked what it claimed. That gap is
where three faults lived, all of them the same shape — a sentence about the
data that the data does not support:

  * A journal that exists and could not be opened rendered byte-identically to
    a quiet week, both of them ending "If you have been driving and it is still
    empty, the rig is reading nothing — the live view will say why." The server
    had already worked out which it was and sent `unreadable`; the page read
    that field only on a path the empty case returns before reaching.

  * The headline said "You marked 6 as taken, worth $59.93 after running costs"
    and the day header, for the same six offers, said "took 6 for $73.70" —
    23% apart, and structurally always on screen together.

  * A window whose only rows were hidden said nothing about the hiding and
    blamed the camera instead.

So the page is driven in a real browser with `fetch` replaced before its script
runs, and fed the exact JSON /api/journal emits. Nothing here is about pixels;
it is about whether a driver reading the page is told the truth.

Skipped where a browser cannot be had, the same way the other browser checks
skip.
"""

import json
import os
import subprocess
import sys
import tempfile

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
    print('%s — skipping the offers-page checks' % why)
    sys.exit(0)


NOW = 1700000000000

# Six offers taken out of twelve, with a running cost on each — the shape that
# made the headline and the day line disagree. The numbers are chosen so the
# gap is unmissable: $2.00 of cost against $10.00 of pay, six times over, is
# $48.00 net against $60.00 gross — and across all twelve, $96.00 against
# $120.00.
def offer(i, accepted=False, cost=2.0, pay=10.0, minutes=20.0, state=None,
          places=None, hidden=False, suspect=False, text=None):
    row = {
        'id': 'r%d' % i, 'at': NOW - i * 600000, 'firstAt': NOW - i * 600000,
        'pay': pay, 'minutes': minutes, 'miles': 6.0,
        'perHour': round((pay - cost) / (minutes / 60.0), 2),
        'grossPerHour': round(pay / (minutes / 60.0), 2),
        'cost': cost, 'costPerMile': 0.33, 'target': 25, 'band': 15,
        'legs': 2, 'whole': True, 'accepted': accepted,
    }
    # What the panel printed in the car at the time, which is what "What you
    # took" groups by. Left off entirely by default, because rows written
    # before the field existed are exactly the case the fourth bar is for —
    # and TOOK_SIX below is what proves those rows are not silently dropped.
    if state is not None:
        row['state'] = state
    if places is not None:
        row['places'] = places
    if hidden:
        row['hidden'] = True
    if suspect:
        row['suspect'] = True
    if text is not None:
        row['text'] = text
    return row


TOOK_SIX = [offer(i, accepted=(i < 6)) for i in range(12)]

# What the panel said about the jobs that were actually worked. Every group has
# its own median so a bar built from the wrong pile cannot land on the right
# number by accident: ACCEPT $30 and $36 -> $33, CLOSE $24 twice -> $24, PASS
# one at $18. One ticked row is hidden, so six were ticked and five can be
# counted, and the heading has to say so rather than print five under a
# headline that says six.
VERDICTS = [
    offer(0, accepted=True, pay=12.0, state='go'),      # $30/hr
    offer(1, accepted=True, pay=10.0, state='warn'),    # $24/hr
    offer(2, accepted=True, pay=10.0, state='warn'),    # $24/hr
    offer(3, accepted=True, pay=8.0, state='no'),       # $18/hr
    offer(4, accepted=True, pay=14.0, state='go'),      # $36/hr
    offer(5, pay=10.0, state='go'),                     # cleared, never ticked
    offer(6, accepted=True, pay=10.0, state='go', hidden=True),
    offer(7, pay=10.0, state='no'),
    # ...and one typed on the keypad. No verdict recorded, not ticked, so it
    # lands under no chip but All — and its row has to say what it is.
    dict(offer(8, pay=10.0), typed=True),
]

# Five offers through Chattanooga, of which four can be counted and three were
# worked; one job on its own in Soddy Daisy; two in Dalton that were set aside
# and so have no rate to give at all.
#
# The fifth Chattanooga row is the point of the set: it was ticked — the driver
# took that job — and the scanner misread it, so it is set aside. Every figure
# in the sentence has to be over the four that could be counted and not over
# the five that matched, and it is only a mixed set that can tell the two
# apart. Sorted, the four are [$24, $24, $30, $30] and interpolate to $27; put
# the misread $84 back in and the median moves to $30, three clear $25 instead
# of two, and the money taken goes from $18.00 to $46.00.
SEARCHABLE = [
    offer(0, accepted=True, pay=12.0, state='go',
          places=['Chattanooga TN', 'Ringgold GA']),
    offer(1, accepted=True, pay=10.0, state='warn',
          places=['Chattanooga TN', 'Fort Oglethorpe GA']),
    offer(2, pay=12.0, state='go', places=['Chattanooga TN', 'Hixson TN']),
    offer(3, pay=10.0, state='warn', places=['East Ridge TN', 'Chattanooga TN']),
    offer(4, pay=14.0, state='go', places=['Soddy Daisy TN']),
    offer(5, pay=10.0, state='no', places=['Dalton GA'], suspect=True),
    offer(6, pay=10.0, state='no', places=['Dalton GA'], suspect=True),
    offer(7, pay=10.0, state='no'),
    # ...and the misread one carries what the reader actually read, with a
    # '<' in it, because OCR off a photograph of a phone can contain anything
    # and this is the first card text to reach innerHTML on this page.
    offer(8, accepted=True, pay=30.0, places=['Chattanooga TN'], suspect=True,
          text='Deliver by 7:42 PM\n$30.00 <total>\n20 min\nChattanooga TN'),
]

# Typed into the box on the page, in this order, against SEARCHABLE.
QUERIES = ['chattanooga', 'soddy', 'dalton', 'nowhere at all']

# Three weeks, one offer a day at noon UTC — noon so that neither the 4am
# shift boundary nor a browser in another zone can move a row to the next
# date — with the pay set by the weekday, so every bar of the day-of-week
# chart has three identical rates under it and its median is exactly that
# number: $18 + $6 per weekday, Sunday first, so Sunday $18, Monday $24 ... a
# Saturday $54. Three rows per weekday because the check is on the median,
# and a median of three equal numbers cannot be interpolated into a
# coincidence.
import datetime as _dt
NOON = NOW - 10 * 3600000           # NOW is 22:13 UTC; this is 12:13 UTC
def _js_weekday(at_ms):
    """getDay(): Sunday is 0. Python's weekday() puts Monday at 0."""
    return (_dt.datetime.utcfromtimestamp(at_ms / 1000).weekday() + 1) % 7
WEEKS = [
    offer(100 + d, pay=8.0 + 2 * _js_weekday(NOON - d * 86400000), state='go')
    for d in range(21)
]
for _i, _r in enumerate(WEEKS):
    _r['at'] = _r['firstAt'] = NOON - _i * 86400000
# ...plus two rows that only the right grouping gets right.
#
# One at 1am on the first Sunday of the window. The calendar calls that
# Sunday; the driver's day, bounded at 4am, calls it Saturday night, which is
# what it was — so it belongs under Sat, at Saturday's pay, and Sat carries
# four rows to Sunday's three. Grouped on the calendar it would land the other
# way round.
_first_sun = next(r for r in WEEKS if _js_weekday(r['at']) == 0)
_late = offer(140, pay=8.0 + 2 * 6, state='go')
_late['at'] = _late['firstAt'] = _first_sun['at'] - 11 * 3600000   # 01:13 UTC Sun
WEEKS.append(_late)
# Three set-aside Wednesdays at an impossible rate. The chart is drawn over
# the COUNTED offers, like every other chart on the page; over the raw window
# these would drag Wednesday from $36 to $168.
for _k in range(3):
    _bad = offer(150 + _k, pay=102.0, state='go', suspect=True)
    _wed = next(r for r in WEEKS if _js_weekday(r['at']) == 3)
    _bad['at'] = _bad['firstAt'] = _wed['at'] + (_k + 1) * 600000
    WEEKS.append(_bad)

# ...and a ticked job with offers inside its stated minutes, one of which was
# itself ticked. `offer(i)` is spaced ten minutes apart and counts BACKWARDS
# from NOW, so a 30-minute job at index 5 covers indices 4, 3 and 2.
BUSY_JOB = dict(offer(5, accepted=True), minutes=30.0, pay=16.05,
                perHour=26.0, id='thejob')
INSIDE = [dict(offer(4), id='in-a'),
          dict(offer(3, accepted=True), id='in-b'),   # a stack: ticked as well
          dict(offer(2), id='in-c')]
OUTSIDE = [dict(offer(0), id='after'), dict(offer(11), id='before')]
BUSY_ROWS = [BUSY_JOB] + INSIDE + OUTSIDE

# One pairing, so the section that reads the stacking record is exercised by
# something other than the layout file.
PAIR = {
    'v': 1, 'kind': 'pair', 'at': NOW - 300000, 'id': 'r0',
    'held': {'pay': 12.0, 'minutes': 30, 'dropoff': 'Oak Ln, Marietta',
             'scanned': True, 'heldMs': 600000},
    'offer': {'pay': 9.0, 'minutes': 20, 'dropoff': 'Chastain Rd NW, Kennesaw',
              'pickup': None},
    'stack': {'pay': 17.4, 'worst': 26.1, 'best': 34.8, 'leftMinutes': 20,
              'minMinutes': 20, 'maxMinutes': 40, 'state': 'go', 'sure': True,
              'ends': 'elsewhere', 'uncosted': False},
}

# Dots and rankings. The newest row was judged at a lower target than the
# rest, so re-judging a row against "today's" target would colour it
# differently from the verdict it records; and the misread every real journal
# carries — $1,184 for twenty minutes — led every ranking until rankings
# learned to leave set-aside rows at the bottom.
DOTS = [offer(101, pay=12.0, state='go'),              # $30/hr at 25
        offer(102, pay=8.0, state='no'),               # $18/hr: PASS at 25, ACCEPT at 18
        offer(103, pay=9.0, state='warn'),             # $21/hr
        offer(104, pay=1184.0, state='go', suspect=True),
        offer(100, pay=12.0, state='go')]              # newest, target 18
# Last in the feed and a minute old: the page takes its target from the
# most recent row that is not in the future, in feed order.
DOTS[-1]['at'] = DOTS[-1]['firstAt'] = NOW - 60000
DOTS[-1]['target'] = 18

# Runs of scanning: twelve stretches three hours apart, three cards five
# minutes apart in each, and three such stretches for the small case. The
# chart shows the latest eight and offers the rest, and the way it says so
# has to be read back rather than assumed.
def _runs(count):
    rows = []
    for k in range(count):
        for j in range(3):
            r = offer(200 + k * 3 + j, pay=9.0 + k, state='go')
            r['at'] = r['firstAt'] = NOW - (k * 3 * 3600000 + (2 - j) * 300000)
            rows.append(r)
    return rows


RUNS = _runs(12)
FEW_RUNS = _runs(3)

# The four answers /api/journal can give. Every field here is one the server
# actually sends — see the send() call in the /api/journal branch.
FEEDS = {
    'busy': {'count': len(BUSY_ROWS), 'total': len(BUSY_ROWS), 'truncated': False,
             'days': 7, 'hidden': 0, 'watched': {'saw': 6, 'kept': 6},
             'unreadable': None, 'pairs': [], 'offers': BUSY_ROWS},
    'took six': {'count': 12, 'total': 12, 'truncated': False, 'days': 7,
                 'hidden': 0, 'watched': {'saw': 14, 'kept': 12},
                 'unreadable': None, 'pairs': [PAIR], 'offers': TOOK_SIX},
    'verdicts': {'count': len(VERDICTS), 'total': len(VERDICTS),
                 'truncated': False, 'days': 7, 'hidden': 1,
                 'watched': {'saw': 8, 'kept': 8},
                 'unreadable': None, 'pairs': [], 'offers': VERDICTS},
    # A window with rows and nothing countable in it: three misreads. The
    # page takes its "nothing usable" path here, which used to build its own
    # list and ignore the chips, the order and the search box.
    'all aside': {'count': 3, 'total': 3, 'truncated': False, 'days': 7,
                  'hidden': 0, 'watched': {'saw': 3, 'kept': 3},
                  'unreadable': None, 'pairs': [],
                  'offers': [offer(0, pay=1030.0, state='no', suspect=True),
                             offer(1, accepted=True, pay=1184.0, suspect=True),
                             offer(2, pay=1251.0, state='no', suspect=True)]},
    # A row the panel refused because the card showed a leg it could not time.
    # Every figure in it is one the card printed, so nothing about its SIZE is
    # wrong — which is exactly why it may not borrow the sentences written for
    # rows whose figures are out of range, nor the one about a crop that
    # clipped the card. Beside it, an ordinary row, so a page that explained
    # everything this way would be caught too.
    'leg': {'count': 2, 'total': 2, 'truncated': False, 'days': 7, 'hidden': 0,
            'watched': {'saw': 2, 'kept': 2},
            'unreadable': None, 'pairs': [],
            'offers': [dict(offer(0, pay=18.40, minutes=5.0, state='doubt',
                                  suspect=True), doubt='leg', untimedMiles=7.8,
                            whole=False, miles=2.1, perHour=213.24,
                            grossPerHour=220.8),
                       offer(1, pay=10.0, minutes=20.0, state='no')]},
    'dots': {'count': len(DOTS), 'total': len(DOTS), 'truncated': False,
             'days': 7, 'hidden': 0, 'watched': {'saw': 5, 'kept': 5},
             'unreadable': None, 'pairs': [], 'offers': DOTS},
    'runs': {'count': len(RUNS), 'total': len(RUNS), 'truncated': False,
             'days': 7, 'hidden': 0, 'watched': {'saw': 36, 'kept': 36},
             'unreadable': None, 'pairs': [], 'offers': RUNS},
    'few runs': {'count': len(FEW_RUNS), 'total': len(FEW_RUNS), 'truncated': False,
                 'days': 7, 'hidden': 0, 'watched': {'saw': 9, 'kept': 9},
                 'unreadable': None, 'pairs': [], 'offers': FEW_RUNS},
    'weeks': {'count': len(WEEKS), 'total': len(WEEKS), 'truncated': False,
              'days': 30, 'hidden': 0, 'watched': {'saw': 21, 'kept': 21},
              'unreadable': None, 'pairs': [], 'offers': WEEKS},
    'searchable': {'count': len(SEARCHABLE), 'total': len(SEARCHABLE),
                   'truncated': False, 'days': 7, 'hidden': 0,
                   'watched': {'saw': 8, 'kept': 8},
                   # Two rows the rig read before its clock was set. They are
                   # in no window and the page has to say so.
                   'beforeClock': 2,
                   'unreadable': None, 'pairs': [], 'offers': SEARCHABLE},
    'unreadable': {'count': 0, 'total': 0, 'truncated': False, 'days': 7,
                   'hidden': 0, 'watched': {'saw': 0, 'kept': 0},
                   'unreadable': 'EACCES', 'pairs': [], 'offers': []},
    'all hidden': {'count': 0, 'total': 0, 'truncated': False, 'days': 7,
                   'hidden': 4, 'watched': {'saw': 4, 'kept': 4},
                   'unreadable': None, 'pairs': [], 'offers': []},
    'genuinely empty': {'count': 0, 'total': 0, 'truncated': False, 'days': 7,
                        'hidden': 0, 'watched': {'saw': 0, 'kept': 0},
                        'unreadable': None, 'pairs': [], 'offers': []},
}

DRIVER = r'''
const { chromium } = require('playwright');
const [base, feedsJson, queriesJson] = process.argv.slice(2);
const FEEDS = JSON.parse(feedsJson);
// Typed into the page's own search box, one after another, against the feed
// built for them. The box re-renders on a 120ms timer, so each one is given
// time to land before the sentence beside it is read back.
const QUERIES = JSON.parse(queriesJson);

// The page's own fetch, replaced before its script runs. Everything above it —
// render(), the wording, the arithmetic — is the real thing off disk.
//
// Only /api/journal is answered from the fixture; anything else the page asks
// for goes to the real server, so a request this stub forgot shows up as a
// failure rather than as a page that silently rendered half.
const STUB = (feed) => `
  window.__asked = [];
  // How many times the expensive parts ran. advice.js assigns window.Advice
  // once, after this script, so an accessor here sees it land and wraps the
  // two entry points a keystroke must never reach: the replay behind the
  // advice and the busy join over the whole window.
  window.__calls = { advise: 0, busy: 0 };
  (function () {
    var held;
    Object.defineProperty(window, 'Advice', {
      configurable: true,
      get: function () { return held; },
      set: function (v) {
        held = v;
        if (v && typeof v.advise === 'function' && typeof v.busy === 'function') {
          var a = v.advise, b = v.busy;
          v.advise = function () { window.__calls.advise++; return a.apply(this, arguments); };
          v.busy = function () { window.__calls.busy++; return b.apply(this, arguments); };
        }
      }
    });
  })();
  const REAL = window.fetch;
  window.fetch = function (url, opts) {
    window.__asked.push(String(url));
    if (String(url).indexOf('/api/journal') === 0) {
      return Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve(${JSON.stringify(feed)}),
        text: () => Promise.resolve(${JSON.stringify(JSON.stringify(feed))}),
      });
    }
    return REAL.call(window, url, opts);
  };
`;

const TEXT = (sel) => {
  const el = document.querySelector(sel);
  if (!el) return null;
  return (el.textContent || '').replace(/\s+/g, ' ').trim();
};

(async () => {
  let browser;
  for (const exe of JSON.parse(process.env.PW_EXES || '[]').concat([null])) {
    try { browser = await chromium.launch(exe ? { executablePath: exe } : {}); break; }
    catch (e) {}
  }
  if (!browser) throw new Error('no chromium');
  const out = {};
  // A step that never settles is reported as a skip naming the feed it hung
  // on, rather than as a suite that sat until the runner's timeout killed
  // it in silence.
  let stage = 'start';
  setTimeout(() => {
    console.log(JSON.stringify({ skip: 'the driver hung on "' + stage + '"' }));
    process.exit(2);
  }, 400000).unref();
  for (const [name, feed] of Object.entries(FEEDS)) {
    stage = name;
    const ctx = await browser.newContext({ viewport: { width: 900, height: 900 } });
    const page = await ctx.newPage();
    await page.addInitScript(STUB(feed));
    await page.goto(base + '/journal.html', { waitUntil: 'domcontentloaded' })
              .catch(() => {});
    await page.waitForTimeout(1500);
    out[name] = await page.evaluate((sel) => {
      const text = new Function('s', 'return (' + sel + ')(s)');
      const list = (s) => [].slice.call(document.querySelectorAll(s))
        .map((e) => (e.textContent || '').replace(/\s+/g, ' ').trim());
      return {
        headline: text('#headline'),
        nothing: document.getElementById('nothing').hidden
          ? null : text('#nothing'),
        caveats: list('#caveats li'),
        days: list('.day'),
        pairsHead: document.getElementById('pairsHead').hidden
          ? null : text('#pairsHead'),
        pairsLead: document.getElementById('pairsLead').hidden
          ? null : text('#pairsLead'),
        rows: document.querySelectorAll('#log details.offer').length,
        asked: window.__asked.length,
        // What the panel had said about the jobs that were worked.
        tookHead: document.getElementById('tookHead').hidden
          ? null : text('#tookHead'),
        weekHead: document.getElementById('weekHead').hidden
          ? null : text('#weekHead'),
        week: [].slice.call(document.querySelectorAll('#week .block'))
          .map(function (b) {
            return { label: b.querySelector('.label').textContent.trim(),
                     amount: b.querySelector('.amount').textContent.trim(),
                     n: b.querySelector('.n').textContent.trim() };
          }),
        took: [].slice.call(document.querySelectorAll('#took .block'))
          .map(function (b) {
            return { label: b.querySelector('.label').textContent.trim(),
                     amount: b.querySelector('.amount').textContent.trim(),
                     n: b.querySelector('.n').textContent.trim() };
          }),
        // What each row says about arriving during a ticked job, opened.
        arrivals: [].slice.call(document.querySelectorAll('#log details.offer'))
          .map(function (d) {
            d.open = true;
            var dt = [].slice.call(d.querySelectorAll('dt'))
              .filter(function (e) { return e.textContent.trim() === 'Arrived'; })[0];
            var tags = [].slice.call(d.querySelectorAll('summary .tag'))
              .map(function (e) { return e.textContent.trim(); });
            // What the reader read, when the row carries it. Read back as
            // textContent so a '<' the OCR produced comes back as a '<' and
            // not as the start of an element.
            var pre = d.querySelector('.cardtext pre');
            var worth = [].slice.call(d.querySelectorAll('dt'))
              .filter(function (e) { return e.textContent.trim() === 'Worth knowing'; })[0];
            return { tags: tags,
                     id: d.getAttribute('data-id'),
                     worth: worth ? worth.nextElementSibling.textContent.trim() : null,
                     // The element, not its text: an empty box and no box
                     // read identically through textContent, and the first
                     // version of the check below could not tell them apart.
                     hasCardtext: !!d.querySelector('.cardtext'),
                     cardtext: pre ? pre.textContent : null,
                     cardtextTags: pre ? pre.querySelectorAll('*').length : 0,
                     arrived: dt ? dt.nextElementSibling.textContent
                                     .replace(/\s+/g, ' ').trim() : null };
          }),
      };
    }, TEXT.toString());
    // The chips and the order, on the feed with a verdict spread. Each press
    // is read back as the rows it left, the sentence describing them, and
    // whether the day headers survived — a ranking has no days.
    if (name === 'verdicts') {
      out[name].picks = {};
      out[name].callsAtLoad = await page.evaluate(() => Object.assign({}, window.__calls));
      const peek = () => page.evaluate(() => {
        const n = document.getElementById('findNote');
        return { rows: [].slice.call(document.querySelectorAll('#log details.offer'))
                          .map((d) => d.getAttribute('data-id')),
                 note: n.hidden ? null : (n.textContent || '').replace(/\s+/g, ' ').trim(),
                 days: document.querySelectorAll('#log .day').length,
                 more: (document.getElementById('more').textContent || '').trim() };
      });
      for (const pick of ['took', 'go', 'warn', 'no', 'aside', 'busy', 'all']) {
        await page.click('#chips button[data-pick="' + pick + '"]');
        await page.waitForTimeout(250);
        out[name].picks[pick] = await peek();
      }
      for (const sort of ['perHour', 'pay', 'minutes', 'newest']) {
        await page.click('#sorts button[data-sort="' + sort + '"]');
        await page.waitForTimeout(250);
        out[name].picks['sort:' + sort] = await peek();
      }
      // A chip and a ranking together, then a mark made inside the selection:
      // the list must stay selected and ranked through the redraw.
      await page.click('#chips button[data-pick="took"]');
      await page.click('#sorts button[data-sort="perHour"]');
      await page.waitForTimeout(250);
      out[name].picks['took+perHour'] = await peek();
      // ...and five keystrokes in the box, each past the 120ms debounce.
      for (const ch of ['1', '0', '.', '0', '0']) {
        await page.type('#find', ch);
        await page.waitForTimeout(250);
      }
      out[name].callsAfterAll = await page.evaluate(() => Object.assign({}, window.__calls));
    }
    // The colour of each row's dot against the verdict it records, and where
    // the set-aside row lands in a ranking.
    if (name === 'dots') {
      const dots = () => page.evaluate(() =>
        [].slice.call(document.querySelectorAll('#log details.offer')).map((d) => ({
          id: d.getAttribute('data-id'),
          aside: d.classList.contains('aside'),
          dot: (d.querySelector('.dot') || { className: '' }).className.replace('dot', '').trim() })));
      out[name].dots = {};
      for (const pick of ['no', 'go', 'all']) {
        await page.click('#chips button[data-pick="' + pick + '"]');
        await page.waitForTimeout(250);
        out[name].dots[pick] = await dots();
      }
      out[name].ranked = {};
      for (const sort of ['perHour', 'pay']) {
        await page.click('#sorts button[data-sort="' + sort + '"]');
        await page.waitForTimeout(250);
        out[name].ranked[sort] = (await dots()).map((d) => d.id);
      }
      out[name].findKeyboard = await page.evaluate(() =>
        document.getElementById('find').getAttribute('inputmode'));
    }
    if (name === 'leg') {
      out[name].detail = await page.evaluate(() => {
        const all = [].slice.call(document.querySelectorAll('#log details.offer'));
        const d = all.filter((x) => x.getAttribute('data-id') === 'r0')[0];
        if (!d) return { ids: all.map((x) => x.getAttribute('data-id')) };
        d.open = true;
        const flat = (el) => el ? (el.textContent || '').replace(/\s+/g, ' ').trim() : '';
        return { aside: d.classList.contains('aside'),
                 why: flat(d.querySelector('.why, .aside-why, p')),
                 all: flat(d) };
      });
    }
    // The chips and the order on the nothing-usable path.
    if (name === 'all aside') {
      const rows = () => page.evaluate(() => ({
        rows: [].slice.call(document.querySelectorAll('#log details.offer'))
                 .map((d) => d.getAttribute('data-id')),
        days: document.querySelectorAll('#log .day').length,
        note: document.getElementById('findNote').hidden ? null
          : (document.getElementById('findNote').textContent || '').replace(/\s+/g, ' ').trim() }));
      out[name].asIs = await rows();
      await page.click('#chips button[data-pick="took"]');
      await page.waitForTimeout(250);
      out[name].tookChip = await rows();
      await page.click('#chips button[data-pick="all"]');
      await page.click('#sorts button[data-sort="pay"]');
      await page.waitForTimeout(250);
      out[name].byPay = await rows();
    }
    // The runs chart: what it shows, what its button says, and what a press
    // does. Every row is read back as its label and amount so the folded
    // eight can be held against the tail of the twelve.
    if (name === 'runs' || name === 'few runs') {
      const runsNow = () => page.evaluate(() => {
        const b = document.getElementById('runsAll');
        return { head: document.getElementById('runsHead').hidden
                   ? null : (document.getElementById('runsHead').textContent || '').replace(/\s+/g, ' ').trim(),
                 rows: [].slice.call(document.querySelectorAll('#runs .block')).map((e) =>
                   (e.querySelector('.label').textContent + ' ' + e.querySelector('.amount').textContent)
                     .replace(/\s+/g, ' ').trim()),
                 button: b.hidden ? null : (b.textContent || '').trim(),
                 pressed: b.getAttribute('aria-pressed'),
                 height: b.hidden ? 0 : b.getBoundingClientRect().height };
      });
      out[name].runs = { folded: await runsNow() };
      if (out[name].runs.folded.button) {
        await page.click('#runsAll');
        await page.waitForTimeout(250);
        out[name].runs.opened = await runsNow();
        await page.click('#runsAll');
        await page.waitForTimeout(250);
        out[name].runs.refolded = await runsNow();
      }
    }
    if (name === 'took six') {
      // A mark, made on an opened row a long way down the list: the row
      // must still be open and on screen afterwards. The mark goes to the
      // real server (only /api/journal is stubbed), which answers, and the
      // list is redrawn from the same feed.
      out[name].mark = await page.evaluate(async () => {
        const rows = document.querySelectorAll('#log details.offer');
        const d = rows[rows.length - 1];
        d.open = true;
        d.scrollIntoView({ block: 'center' });
        const before = { y: window.scrollY, top: d.getBoundingClientRect().top };
        d.querySelector('button[data-act="took"]').click();
        await new Promise((r) => setTimeout(r, 900));
        const again = document.querySelector('#log details.offer[data-id="' + d.getAttribute('data-id') + '"]');
        return { id: d.getAttribute('data-id'), before: before,
                 open: !!(again && again.open),
                 top: again ? again.getBoundingClientRect().top : null,
                 y: window.scrollY, inner: window.innerHeight,
                 undo: (document.getElementById('undoWhat').textContent || '').trim() };
      });
      // Two loads in flight: the slower earlier one must not paint over the
      // window pressed later. 7 days is answered after 1.5s with the feed;
      // Today is answered at once with nothing.
      out[name].race = await page.evaluate(async (empty) => {
        const feedFetch = window.fetch;
        window.fetch = function (url, opts) {
          const u = String(url);
          if (u.indexOf('/api/journal?') === 0 && u.indexOf('days=7') !== -1) {
            return new Promise((r) => setTimeout(() => r(feedFetch(url, opts)), 1500));
          }
          if (u.indexOf('/api/journal?') === 0) {
            return Promise.resolve({ ok: true, status: 200,
              json: () => Promise.resolve(empty), text: () => Promise.resolve(JSON.stringify(empty)) });
          }
          return feedFetch(url, opts);
        };
        document.querySelector('#ranges button[data-days="7"]').click();
        await new Promise((r) => setTimeout(r, 50));
        document.querySelector('#ranges button[data-days="1"]').click();
        await new Promise((r) => setTimeout(r, 2200));
        const pressed = [].slice.call(document.querySelectorAll('#ranges button'))
          .filter((b) => b.getAttribute('aria-pressed') === 'true').map((b) => b.getAttribute('data-days'));
        window.fetch = feedFetch;
        return { pressed: pressed,
                 rows: document.querySelectorAll('#log details.offer').length,
                 days: document.querySelectorAll('#log .day').length,
                 nothing: document.getElementById('nothing').hidden ? null
                   : (document.getElementById('nothing').textContent || '').slice(0, 40),
                 headline: (document.getElementById('headline').textContent || '').trim(),
                 scale: (document.getElementById('blockScale').textContent || '').trim() };
      }, FEEDS['genuinely empty']);
      // The feed again, then a search and a window that fails: nothing of
      // the previous window may stand under the apology, and a chip must
      // not bring it back.
      out[name].failed = await page.evaluate(async () => {
        const feedFetch = window.fetch;
        document.querySelector('#ranges button[data-days="7"]').click();
        await new Promise((r) => setTimeout(r, 400));
        const box = document.getElementById('find');
        box.value = 'marietta';
        box.dispatchEvent(new Event('input', { bubbles: true }));
        await new Promise((r) => setTimeout(r, 400));
        const withRows = { pairs: !document.getElementById('pairsHead').hidden,
                           note: !document.getElementById('findNote').hidden,
                           scale: (document.getElementById('blockScale').textContent || '').trim() };
        window.fetch = function (url, opts) {
          if (String(url).indexOf('/api/journal?') === 0) return Promise.reject(new Error('down'));
          return feedFetch(url, opts);
        };
        document.querySelector('#ranges button[data-days="30"]').click();
        await new Promise((r) => setTimeout(r, 400));
        const down = { pairs: !document.getElementById('pairsHead').hidden,
                       note: !document.getElementById('findNote').hidden,
                       scale: (document.getElementById('blockScale').textContent || '').trim(),
                       nothing: (document.getElementById('nothing').textContent || '').slice(0, 25) };
        document.querySelector('#chips button[data-pick="go"]').click();
        await new Promise((r) => setTimeout(r, 300));
        const chipped = document.querySelectorAll('#log details.offer').length;
        window.fetch = feedFetch;
        box.value = '';
        box.dispatchEvent(new Event('input', { bubbles: true }));
        document.querySelector('#chips button[data-pick="all"]').click();
        await new Promise((r) => setTimeout(r, 300));
        return { withRows: withRows, down: down, chipped: chipped };
      });
      await page.click('#ranges button[data-days="7"]').catch(() => {});
      await page.waitForTimeout(400);
    }
    // A chip that picks nothing, on the feed with no verdicts on its rows.
    if (name === 'took six') {
      await page.click('#chips button[data-pick="no"]');
      await page.waitForTimeout(250);
      out[name].emptyPick = await page.evaluate(() => {
        const n = document.getElementById('findNote');
        return { rows: document.querySelectorAll('#log details.offer').length,
                 note: n.hidden ? null : (n.textContent || '').replace(/\s+/g, ' ').trim() };
      });
      await page.click('#chips button[data-pick="all"]');
      await page.waitForTimeout(250);
    }
    // ...and then the search box, on the one feed built to be searched. Typed
    // rather than assigned, because the note is redrawn by the box's own
    // `input` handler and setting `.value` fires nothing.
    if (name === 'searchable') {
      out[name].searches = {};
      for (const q of QUERIES) {
        await page.fill('#find', q);
        await page.waitForTimeout(400);
        out[name].searches[q] = await page.evaluate(() => {
          const n = document.getElementById('findNote');
          return { note: n.hidden ? null
                     : (n.textContent || '').replace(/\s+/g, ' ').trim(),
                   rows: document.querySelectorAll('#log details.offer').length };
        });
      }
      // ...and cleared again, because an empty box must take the note away
      // rather than leave the last answer standing over the whole list.
      await page.fill('#find', '');
      await page.waitForTimeout(400);
      out[name].searches[''] = await page.evaluate(() => {
        const n = document.getElementById('findNote');
        return { note: n.hidden ? null : (n.textContent || '').trim(),
                 rows: document.querySelectorAll('#log details.offer').length };
      });
    }
    await page.close();
    await ctx.close();
  }
  await browser.close();
  console.log(JSON.stringify(out));
})().catch((e) => { console.log(JSON.stringify({ skip: String(e && e.message) })); });
'''


def free_port():
    import socket
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


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
    import time
    import urllib.request
    for _ in range(120):
        try:
            urllib.request.urlopen(base + '/api/status', timeout=1).read()
            break
        except Exception:
            time.sleep(0.1)
    else:
        raise RuntimeError('the server never came up')

    driver = os.path.join(work, 'offerspage.js')
    open(driver, 'w').write(DRIVER)
    run = subprocess.run(
        ['node', driver, base, json.dumps(FEEDS), json.dumps(QUERIES)],
        env=dict(os.environ, NODE_PATH=os.pathsep.join(NODE_PATHS),
                 PW_EXES=json.dumps([
                     os.environ.get('CHROMIUM', ''),
                     '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
                 ])),
        capture_output=True, text=True, timeout=600)
    line = (run.stdout or '').strip().split('\n')[-1] if run.stdout else ''
    try:
        got = json.loads(line)
    except Exception:
        skip('the browser produced nothing (%s)'
             % (run.stderr or '')[-200:].replace('\n', ' '))
    if got.get('skip'):
        skip(got['skip'])

    # --- the page reached its own data ---------------------------------------
    for name in FEEDS:
        ok_('%s was rendered' % name, got.get(name) is not None)
    if any(got.get(n) is None for n in FEEDS):
        raise SystemExit(1)

    # --- net and gross may not disagree about the same offers ----------------
    #
    # --- the runs chart shows the latest few and offers the rest ------------
    # Measured on a fortnight of offers at 800x480 before this: seventeen runs
    # on a week put "By time of day" 1,911px down the page, three panel
    # screens of bars between the headline and the chart that says which hours
    # pay. It sits after those charts now, and shows eight.
    rn = got['runs']['runs']
    fold = rn['folded']
    ok_('twelve runs are counted in the heading (%r)' % (fold['head'] or '')[:40],
        fold['head'] is not None and '12 of them' in fold['head'])
    eq('...and eight are drawn', len(fold['rows']), 8)
    ok_('...with a button naming the rest (%r)' % fold['button'],
        fold['button'] is not None and '12' in fold['button'])
    ok_('...tall enough to press in a car (%.0fpx)' % fold['height'], fold['height'] >= 44)
    opened = rn.get('opened') or {}
    eq('pressing it draws all twelve', len(opened.get('rows') or []), 12)
    eq('...the eight it showed being the latest eight',
       fold['rows'], (opened.get('rows') or [])[-8:])
    eq('...and the button says so', opened.get('pressed'), 'true')
    eq('pressing it again folds them back', len((rn.get('refolded') or {}).get('rows') or []), 8)
    few = got['few runs']['runs']['folded']
    eq('three runs are all drawn', len(few['rows']), 3)
    ok_('...with nothing to press', few['button'] is None)

    # --- a mark leaves the row where it was -------------------------------
    mk = got['took six'].get('mark') or {}
    ok_('the row acted on was opened and scrolled to before the mark',
        mk.get('before') and mk['before'].get('y', 0) > 0)
    ok_('the mark was made (%r)' % mk.get('undo'), 'taken' in (mk.get('undo') or ''))
    ok_('...and the row is still open afterwards', mk.get('open'))
    ok_('...and still on screen (top %r of %r)' % (mk.get('top'), mk.get('inner')),
        mk.get('top') is not None and 0 <= mk['top'] < (mk.get('inner') or 0))

    # --- the later window wins ------------------------------------------
    rc = got['took six'].get('race') or {}
    eq('after 7 days then Today, Today is the window pressed', rc.get('pressed'), ['1'])
    eq('...and the rows on the page are today\'s (none)', rc.get('rows'), 0)
    eq('...with no day headers from the week', rc.get('days'), 0)
    ok_('...and the empty state, not the week\'s headline (%r)' % (rc.get('headline') or '')[:40],
        rc.get('nothing') is not None and 'cleared the line' not in (rc.get('headline') or ''))
    eq('...and no chart scale left over', rc.get('scale'), '')

    # --- a window that cannot be fetched leaves nothing of the last one -----
    fl = got['took six'].get('failed') or {}
    wr = fl.get('withRows') or {}
    ok_('with rows on the page there is a pairing, a search sentence and a scale',
        wr.get('pairs') and wr.get('note') and wr.get('scale'))
    dn = fl.get('down') or {}
    ok_('the apology is up (%r)' % dn.get('nothing'), 'Cannot reach' in (dn.get('nothing') or ''))
    ok_('...with no pairing under it', not dn.get('pairs'))
    ok_('...no search sentence', not dn.get('note'))
    eq('...no chart scale', dn.get('scale'), '')
    eq('...and a chip brings nothing back', fl.get('chipped'), 0)

    # --- the dot is the verdict the row records ---------------------------
    dz = got['dots']
    passing = [d for d in (dz['dots'].get('no') or []) if not d['aside']]
    ok_('the PASS chip lists rows', bool(passing))
    eq('...and every one of them wears a PASS dot', sorted(set(d['dot'] for d in passing)), ['no'])
    accepting = [d for d in (dz['dots'].get('go') or []) if not d['aside']]
    eq('...as every row under ACCEPT wears an ACCEPT dot',
       sorted(set(d['dot'] for d in accepting)), ['go'])
    ranked = dz['ranked'].get('perHour') or []
    ok_('Best $/hr does not lead with the set-aside misread (%r)' % ranked[:2],
        ranked and ranked[0] != 'r104')
    eq('...which is last', ranked[-1] if ranked else None, 'r104')
    eq('...and last under Highest pay too', (dz['ranked'].get('pay') or [None])[-1], 'r104')
    ok_('the find box does not ask the phone for a keypad with no letters (%r)'
        % dz.get('findKeyboard'), dz.get('findKeyboard') not in ('decimal', 'numeric'))

    # Six taken offers, $10.00 each with $2.00 of running cost: $48.00 net,
    # $60.00 gross. The headline was already net; the day header was not, and
    # any rendered "took N for $X" guarantees the headline is above it, so the
    # two were never apart.
    took = got['took six']
    ok_('the headline names what was taken (%r)' % (took['headline'] or '')[:70],
        'marked' in (took['headline'] or ''))
    ok_('...net, and saying so',
        '$48.00' in took['headline'] and 'after running costs' in took['headline'])
    no_('...and not the gross total', '$60.00' in took['headline'])
    ok_('there is a day header to compare it with', bool(took['days']))
    day = ' '.join(took['days'])
    ok_('the day header agrees with the headline about the same six (%r)'
        % day[-60:], 'took 6 for $48.00' in day)
    no_('...rather than quoting the gross figure beside a net rate',
        '$60.00' in day)
    # The whole line, not only the half that was wrong: the median beside these
    # totals is net, and a line carrying a net rate and gross money is the
    # fault its own comment names.
    no_('nothing else on the day line is gross either', '$120.00' in day)
    ok_('...the offered total is net too ($96 of $120)', '$96.00' in day)

    # --- an unreadable journal is not a quiet week ---------------------------
    blind = got['unreadable']
    ok_('an unreadable journal says so in the headline (%r)'
        % (blind['headline'] or '')[:70],
        'could not be read' in (blind['headline'] or ''))
    ok_('...and in the panel', 'could not be read' in (blind['nothing'] or ''))
    # The claim that was being made instead. It sends a driver to debug a
    # camera that is working, over a file that is sitting on disk intact.
    no_('...and never claims the rig is reading nothing',
        'reading nothing' in ((blind['headline'] or '') + (blind['nothing'] or '')))
    ok_('...with the server\'s own reason kept',
        any('EACCES' in c for c in blind['caveats']))
    # The notes were blanked on this path, which is the one path where the note
    # IS the explanation for the emptiness above it.
    ok_('...and the notes are not thrown away', len(blind['caveats']) > 1)
    # No row to read a cost per mile off, so nothing is said about one.
    no_('...and nothing is invented about running costs',
        any('running cost' in c for c in blind['caveats']))

    # --- a window that is entirely hidden is not an empty one ----------------
    hid = got['all hidden']
    ok_('a hidden-only window says what is hiding the rows (%r)'
        % (hid['nothing'] or '')[:70], 'hidden' in (hid['nothing'] or ''))
    no_('...and does not blame the camera',
        'reading nothing' in (hid['nothing'] or ''))
    ok_('...and the count reaches the notes',
        any('4 offers are hidden' in c for c in hid['caveats']))

    # --- and a genuinely empty one still reads as it did ---------------------
    #
    # The point of the two branches above is that this one keeps its wording.
    # A page that hedged every empty state would have lost the message that is
    # right when the rig really has read nothing.
    empty = got['genuinely empty']
    ok_('an empty journal still says the scanner has recorded nothing (%r)'
        % (empty['nothing'] or '')[:70],
        'No offers recorded yet' in (empty['nothing'] or ''))
    ok_('...and still sends the driver to the live view',
        'reading nothing' in (empty['nothing'] or ''))
    eq('...with no rows listed', empty['rows'], 0)

    # --- offers that arrived while a ticked job was running ------------------
    #
    # Only the positive case is ever stated. This can see ticked jobs and
    # nothing else, and 49 ticks across eight days of the driver's own record is
    # plainly not every job worked — so an unmarked row means "no ticked job was
    # running", never "you were free". Measured over the seven exports, the
    # share that looks busy tracks how hard the driver was ticking rather than
    # how busy they were: 3.5% of offers on the three days carrying one to three
    # ticks, 27.7% on the four days carrying ten or eleven.
    busy = got['busy']
    arr = busy['arrivals']
    eq('every seeded row is listed', len(arr), 6)
    inside = [a for a in arr if a['arrived']]
    eq('the three offers inside the ticked job are marked', len(inside), 3)
    ok_('...saying how far into it they arrived (%r)'
        % (inside[0]['arrived'] or '')[:60],
        all('min into a job you ticked at' in (a['arrived'] or '') for a in inside))
    # The strongest thing to get wrong: the driver demonstrably took this one.
    stacks = [a for a in arr if 'stacked on' in a['tags']]
    eq('the one inside the window that was itself ticked is a stack', len(stacks), 1)
    ok_('...and says so rather than calling it unavailable',
        'you ticked this one too' in (stacks[0]['arrived'] or ''))
    during = [a for a in arr if 'during a job' in a['tags']]
    eq('...and the other two are marked plainly', len(during), 2)
    # No chip and no row is the whole of what is said about the rest. A page
    # that wrote "you were free" here would be wrong on about 130 rows of the
    # driver's own record, concentrated on the days somebody forgot to tick.
    silent = [a for a in arr if not a['arrived']]
    eq('the rest say nothing at all', len(silent), 3)
    no_('...and never claim the driver was free',
        any('free' in ' '.join(a['tags']).lower() for a in arr))
    # ...and the note that stops the silence being read as its opposite.
    ok_('the note says what the marking is worked out from',
        any('no ticked job was running, not that you were free' in c
            for c in busy['caveats']))
    # With nothing ticked the feature has said nothing, and a note about it
    # would be noise on every window that has no ticks in it.
    no_('...and it stays away when nothing is ticked',
        any('during a job' in c for c in got['unreadable']['caveats']))

    # --- the stacking record reaches the page --------------------------------
    ok_('the second-jobs section appears when there are pairings (%r)'
        % (took['pairsHead'] or '')[:60],
        'Second jobs' in (took['pairsHead'] or ''))
    ok_('...saying which way the panel went (%r)' % (took['pairsLead'] or '')[:70],
        'take it' in (took['pairsLead'] or ''))
    for name in ('unreadable', 'all hidden', 'genuinely empty'):
        eq('...and staying away when there are none: %s' % name,
           got[name]['pairsHead'], None)

    # --- what was taken, against what the panel had said about it ------------
    #
    # Read in one direction only. Every row behind these bars is ticked, so the
    # denominator is a set of jobs somebody said they worked; the other
    # direction — "of what it cleared, how much did you take" — would divide by
    # a pile that is mostly rows nobody pressed a button on.
    v = got['verdicts']
    bars = {b['label']: b for b in v['took']}
    ok_('the taken chart appears once something is ticked (%r)'
        % (v['tookHead'] or '')[:70], v['tookHead'] is not None)
    eq('...with one bar per verdict the panel can give', len(v['took']), 3)
    eq('...ACCEPT is the two cleared jobs', bars.get('ACCEPT', {}).get('n'), '2')
    # $30 and $36 interpolate to $33. A bar built from the wrong pile would not
    # land here: CLOSE is $24 and PASS is $18.
    eq('...at their own median, not the page\'s',
       bars.get('ACCEPT', {}).get('amount'), '$33')
    eq('...CLOSE is the two it hedged', bars.get('CLOSE', {}).get('n'), '2')
    eq('...at $24', bars.get('CLOSE', {}).get('amount'), '$24')
    # The one that matters most. Taking a job the panel said to pass is the
    # decision the target exists to inform, and what it paid is the answer.
    eq('...PASS is the one taken against the advice',
       bars.get('PASS', {}).get('n'), '1')
    eq('...and says what that one paid', bars.get('PASS', {}).get('amount'), '$18')
    # Six ticked, five countable: a heading printing five under a page that
    # counts six ticks is two numbers on one screen that do not add up.
    ok_('...and the heading reconciles the ticks it could not count (%r)'
        % (v['tookHead'] or '')[-60:],
        '5 of 6 you ticked that could be counted (1 set aside)'
        in (v['tookHead'] or ''))
    # A verdict nobody recorded is not a fourth kind of advice, so the bar for
    # it stays away unless something is actually in it.
    no_('...with no empty fourth bar', 'no verdict' in ' '.join(
        b['label'] for b in v['took']))
    # ...and rows written before the verdict was recorded are not dropped: the
    # older fixture carries no `state` at all and its six ticks must still be
    # somewhere, or the chart and the headline disagree about the same offers.
    tookbars = {b['label']: b for b in took['took']}
    eq('rows with no recorded verdict get their own bar',
       tookbars.get('no verdict', {}).get('n'), '6')
    eq('...and the three real verdicts still show, empty',
       [tookbars.get(k, {}).get('n') for k in ('ACCEPT', 'CLOSE', 'PASS')],
       ['0', '0', '0'])
    # Nothing ticked is not "you took nothing". It is a driver who has never
    # pressed the button, and three empty bars would be a claim about their
    # shift made out of the absence of one.
    for name in ('unreadable', 'all hidden', 'genuinely empty'):
        eq('...and the section stays away with nothing ticked: %s' % name,
           got[name]['tookHead'], None)

    # --- what the search found, and what it was worth ------------------------
    #
    # The figures at the top of the page are the whole window's and do not move
    # when the box is typed into. "Do the Chattanooga runs pay?" is the question
    # somebody types a place in to ask, and the answer used to be a filtered
    # list and nothing else.
    s = got['searchable']['searches']
    chatt = s['chattanooga']['note'] or ''
    eq('a search narrows the list', s['chattanooga']['rows'], 5)
    ok_('...and says how many of how many (%r)' % chatt[:60],
        '5 of 9 offers match "chattanooga"' in chatt)
    # Over the four that could be counted, never the five that matched: with
    # the misread $84 back in, [$24, $24, $30, $30, $84] has a median of $30.
    ok_('...with the median of what it found, not the page\'s (%r)' % chatt[-90:],
        'Typical $27/hr across the 4 that could be counted' in chatt)
    # ...and the same set again. Counting the misread one would make it three.
    ok_('...and how many of those cleared the line',
        '2 of them clearing $25/hr' in chatt)
    # Net, like every figure on this page: $12.00 and $10.00 of pay, $2.00 of
    # running cost off each. The driver ticked a third — they took that job —
    # but the scanner misread the card, so its $28.00 is not money this page
    # will claim they earned.
    ok_('...and what was worked out of them, net (%r)' % chatt[-60:],
        'You marked 2 of them as taken, worth $18.00' in chatt)
    # A median of one offer is that offer. Calling it typical invites it to be
    # read as a pattern, which one job is not.
    one = s['soddy']['note'] or ''
    eq('a search matching one offer finds one', s['soddy']['rows'], 1)
    ok_('...and names it as a single job rather than a typical one (%r)'
        % one[-70:],
        'The one of them that could be counted paid $36/hr' in one)
    no_('...and does not call one offer typical', 'Typical' in one)
    # Rows that were set aside are still listed — that is the whole reason the
    # log keeps them — but there is no rate to give for them, and "median --"
    # would be a figure where there is none.
    none = s['dalton']['note'] or ''
    eq('offers that were all set aside are still listed', s['dalton']['rows'], 2)
    ok_('...and the note says there is no rate to give (%r)' % none[-70:],
        'not one of them could be counted' in none)
    no_('...rather than printing a dash as a rate', '--' in none)
    miss = s['nowhere at all']['note'] or ''
    ok_('a search matching nothing says so (%r)' % miss[:60],
        'Nothing in this stretch matches' in miss)
    eq('...and clearing the box takes the note away', s['']['note'], None)
    eq('...and puts every row back', s['']['rows'], len(SEARCHABLE))

    # --- by day of the week ------------------------------------------------
    #
    # Shown once the window holds a fortnight, on the driver's 4am-bounded
    # day, Monday first. Each fixture bar rests on three identical rates, so
    # a median landing on the right number is a median over the right rows.
    wk = got['weeks']
    ok_('the day-of-week chart appears over three weeks (%r)'
        % (wk['weekHead'] or '')[:60], wk['weekHead'] is not None)
    ok_('...saying how many days are behind it',
        'across 21 days' in (wk['weekHead'] or ''))
    eq('...Monday first, Sunday last',
       [b['label'] for b in wk['week']],
       ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'])
    # Three under every bar but Saturday, which has the 1am row as well —
    # grouped on the driver's day, not the calendar's. Grouped on the calendar
    # it is Sunday that would read 4.
    eq('...three offers under every bar, four under Saturday',
       [b['n'] for b in wk['week']], ['3', '3', '3', '3', '3', '4', '3'])
    wkbars = {b['label']: b['amount'] for b in wk['week']}
    eq('...Sunday at its own median', wkbars.get('Sun'), '$18')
    eq('...Monday at its', wkbars.get('Mon'), '$24')
    eq('...and Saturday at its', wkbars.get('Sat'), '$54')
    # The three set-aside Wednesdays at $300/hr are not in this. Over the raw
    # window they would make it $168.
    eq('...and Wednesday over the counted rows only', wkbars.get('Wed'), '$36')
    # A week of offers is one day per bar, and one day's median is already on
    # its day header — the chart would be the list again, drawn as a pattern.
    for name in ('verdicts', 'took six', 'searchable'):
        eq('...and it stays away over a single day: %s' % name,
           got[name]['weekHead'], None)
    eq('...with no bars drawn behind the hidden heading',
       got['verdicts']['week'], [])

    # --- which offers to list, and in what order ---------------------------
    #
    # Both act on the list alone. The figures above are the whole window's and
    # must stay so — a selection fed into the advice block recommends halving
    # the target off two taps. VERDICTS is r0..r7: taken r0-r4 and r6 (r6
    # hidden), ACCEPT r0 r4 r5 r6, CLOSE r1 r2, PASS r3 r7, and r6 is the one
    # set-aside row. Ranked by $/hr the top is r4 at $36; by pay it is r4 at
    # $14.00; by length every row is 20 minutes so the tie falls to newest.
    p = v['picks']
    eq('the Took chip lists the ticked rows and nothing else',
       sorted(p['took']['rows']), ['r0', 'r1', 'r2', 'r3', 'r4', 'r6'])
    ok_('...and the sentence says what was picked (%r)' % (p['took']['note'] or '')[:60],
        '6 of 9 offers you marked as taken' in (p['took']['note'] or ''))
    eq('PASS lists what the panel said PASS to', sorted(p['no']['rows']), ['r3', 'r7'])
    eq('CLOSE lists what it hedged', sorted(p['warn']['rows']), ['r1', 'r2'])
    eq('ACCEPT lists what it cleared, by the verdict on the row',
       sorted(p['go']['rows']), ['r0', 'r4', 'r5', 'r6'])
    # The chip and the chart above it must count the same rows: the chart's
    # PASS bar says 1 taken, and the one taken row under this chip is r3.
    eq('...so a bar up there has the same rows as its chip down here',
       [r for r in p['no']['rows'] if r in ('r0', 'r1', 'r2', 'r3', 'r4', 'r6')], ['r3'])
    eq('Set aside lists the row that could not be counted', p['aside']['rows'], ['r6'])
    # offer(i) is ten minutes apart, counting backwards from NOW, and every row
    # is twenty minutes long — so a ticked row's window holds exactly the one
    # row after it in time. r4, r3, r2 and r1 are ticked and each covers the
    # next: r3, r2, r1, r0. r6 is ticked too but hidden, and Advice.busy is
    # built over usable() rows only, so its window does not exist and r5 is
    # not inside it. The chip must agree with the "during a job" tag on the
    # rows, which is the same join.
    eq('During a job lists exactly the rows inside a ticked window',
       sorted(p['busy']['rows']), ['r0', 'r1', 'r2', 'r3'])
    ok_('...and the sentence says so (%r)' % (p['busy']['note'] or '')[:70],
        '4 of 9 offers that arrived during a ticked job' in (p['busy']['note'] or ''))
    eq('All puts every row back', len(p['all']['rows']), 9)
    # The typed one says so, and nothing else does.
    typed = {a['id']: a['worth'] for a in v['arrivals']}
    ok_('a row typed on the keypad says so (%r)' % (typed.get('r8') or '')[:50],
        'typed on the keypad' in (typed.get('r8') or ''))
    no_('...and a row the camera read does not',
        any('typed' in (w or '') for i, w in typed.items() if i != 'r8'))
    eq('...and takes the sentence away', p['all']['note'], None)
    ok_('newest keeps the day headers', p['all']['days'] >= 1)
    eq('Best $/hr ranks the list', p['sort:perHour']['rows'][0], 'r4')
    eq('...and a ranking has no days', p['sort:perHour']['days'], 0)
    eq('Highest pay ranks by the card', p['sort:pay']['rows'][0], 'r4')
    ok_('Longest ranks by minutes, ties to newest (%s)' % p['sort:minutes']['rows'][:2],
        p['sort:minutes']['rows'][0] == 'r0')
    ok_('Newest restores the day headers', p['sort:newest']['days'] >= 1)
    # Twelve chip and sort presses and five keystrokes, and the expensive
    # parts of the page ran for none of them. They used to run for every one:
    # the whole render, measured at 150-224ms a keystroke over 3,000 offers on
    # a desktop browser, and the Pi's own browser is several times slower.
    at_load, after = v.get('callsAtLoad') or {}, v.get('callsAfterAll') or {}
    ok_('the advice replay ran when the page loaded (%s)' % at_load.get('advise'),
        (at_load.get('advise') or 0) >= 1)
    ok_('...and the busy join too', (at_load.get('busy') or 0) >= 1)
    eq('a chip, a sort or a keystroke re-runs neither',
       (after.get('advise'), after.get('busy')),
       (at_load.get('advise'), at_load.get('busy')))
    eq('a chip and a ranking compose', p['took+perHour']['rows'][0], 'r4')
    eq('...over the picked rows only', len(p['took+perHour']['rows']), 6)
    # A chip that picks nothing says so in a sentence of its own. The clause
    # that follows a count does not survive "Nothing": the first version of
    # this printed "Nothing in this stretch match".
    empty = took.get('emptyPick') or {}
    eq('a chip picking nothing lists nothing', empty.get('rows'), 0)
    ok_('...and says so, grammatically (%r)' % (empty.get('note') or '')[:60],
        'The panel said PASS to nothing in this stretch' in (empty.get('note') or ''))

    # --- the list on the nothing-usable path ------------------------------
    #
    # A window whose every row was set aside takes an early exit in render()
    # that used to build its own list, so the chips, the order and the search
    # box did nothing there. It goes through the same list code now.
    aside_feed = got['all aside']
    eq('every set-aside row is listed', len(aside_feed['asIs']['rows']), 3)
    eq('the Took chip works on the nothing-usable path',
       aside_feed['tookChip']['rows'], ['r1'])
    ok_('...with the sentence (%r)' % (aside_feed['tookChip']['note'] or '')[:60],
        '1 of 3 offers you marked as taken' in (aside_feed['tookChip']['note'] or ''))
    eq('...and so does the order', aside_feed['byPay']['rows'], ['r2', 'r1', 'r0'])
    eq('...without day headers', aside_feed['byPay']['days'], 0)

    # --- a row refused for a leg, and the two sentences it must not borrow -
    #
    # The row used to arrive here saying `state: 'doubt'` and `doubt: null`,
    # because journal.py worked the verdict out a second time with a function
    # that can only see three numbers. The page then explained it with the first
    # branch that matched — a crop that clipped the card — which is a specific
    # claim about a card that was fully in the crop, and its verdict line fell
    # through to "the reading is outside anything a real offer does", which is
    # false of every figure in it.
    leg = (got.get('leg') or {}).get('detail') or {}
    ok_('the refused row was found', bool(leg))
    if leg:
        ok_('...and is set aside', leg.get('aside'))
        whole = leg.get('all') or ''
        ok_('...explained by the leg that never read (%r)'
            % whole[max(0, whole.find('leg')) - 30:][:90],
            'could not time' in whole)
        ok_('...with how much of the journey that was', '7.8 mi' in whole)
        # The two it must NOT borrow. Both were what the page really said.
        ok_('...not as a crop that clipped the card',
            'was in the crop' not in whole)
        ok_('...and not as a figure outside anything a real offer does',
            'outside anything a real offer does' not in whole)
        ok_('...nor flagged as a figure out of range',
            'outside the range a real offer falls in' not in whole)
        # Said plainly where the verdict would be, because "no verdict" with a
        # dash beside it reads as "this was never recorded".
        ok_('...and the verdict line says a leg never read',
            'a leg of the journey never read' in whole)

    # --- what the reader actually read -----------------------------------
    #
    # On the wire for every row and thrown away by this page, so the one
    # screen somebody opens to ask "why does this row say $30?" was the one
    # that could not answer. Only the misread row carries text in the fixture,
    # so a page printing it on every row would fail the second check.
    by_id = {a['id']: a for a in got['searchable']['arrivals']}
    read = by_id.get('r8', {})
    ok_('a row carries what the reader read (%r)' % (read.get('cardtext') or '')[:40],
        read.get('cardtext') and 'Deliver by 7:42 PM' in read['cardtext'])
    # OCR output is text, never markup: the '<total>' the reader produced has
    # to come back as five characters, not as an element.
    ok_('...as text, with the angle bracket the reader produced still in it',
        '<total>' in (read.get('cardtext') or ''))
    eq('...and not as markup', read.get('cardtextTags'), 0)
    eq('...and rows with no text carry no box at all, empty or otherwise',
       [a['id'] for a in got['searchable']['arrivals'] if a['hasCardtext']], ['r8'])

    # --- rows read before the rig had a clock ------------------------------
    #
    # In no window whichever range is pressed, and until now said nowhere on
    # this page: dropped without a word on Today/7/30 and back as a phantom
    # 1970 day on All. The server now counts them; the page has to say so.
    ok_('offers read before the clock was set are named (%r)'
        % ' | '.join(c[:60] for c in got['searchable']['caveats']),
        any('2 offers were read before the rig’s clock had been set' in c
            for c in got['searchable']['caveats']))
    no_('...and not when there are none',
        any('clock had been set' in c for c in got['took six']['caveats']))

finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d offers-page checks passed' % ok)
sys.exit(1 if bad else 0)
