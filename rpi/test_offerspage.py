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
def offer(i, accepted=False, cost=2.0, pay=10.0, minutes=20.0):
    return {
        'id': 'r%d' % i, 'at': NOW - i * 600000, 'firstAt': NOW - i * 600000,
        'pay': pay, 'minutes': minutes, 'miles': 6.0,
        'perHour': round((pay - cost) / (minutes / 60.0), 2),
        'grossPerHour': round(pay / (minutes / 60.0), 2),
        'cost': cost, 'costPerMile': 0.33, 'target': 25, 'band': 15,
        'legs': 2, 'whole': True, 'accepted': accepted,
    }


TOOK_SIX = [offer(i, accepted=(i < 6)) for i in range(12)]

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
const [base, feedsJson] = process.argv.slice(2);
const FEEDS = JSON.parse(feedsJson);

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
        // What each row says about arriving during a ticked job, opened.
        arrivals: [].slice.call(document.querySelectorAll('#log details.offer'))
          .map(function (d) {
            d.open = true;
            var dt = [].slice.call(d.querySelectorAll('dt'))
              .filter(function (e) { return e.textContent.trim() === 'Arrived'; })[0];
            var tags = [].slice.call(d.querySelectorAll('summary .tag'))
              .map(function (e) { return e.textContent.trim(); });
            return { tags: tags,
                     arrived: dt ? dt.nextElementSibling.textContent
                                     .replace(/\s+/g, ' ').trim() : null };
          }),
      };
    }, TEXT.toString());
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
        ['node', driver, base, json.dumps(FEEDS)],
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

finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d offers-page checks passed' % ok)
sys.exit(1 if bad else 0)
