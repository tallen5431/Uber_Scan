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
  for (const [name, feed] of Object.entries(FEEDS)) {
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
            return { tags: tags,
                     id: d.getAttribute('data-id'),
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
