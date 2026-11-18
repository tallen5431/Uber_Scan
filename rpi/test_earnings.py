"""Uber's Earnings Activity, from a picture to the trips on it.

    python3 rpi/test_earnings.py

The owner, 7 Nov 2026: "compare what uber actually paid compared to the
expected pay of the order, here is a screen shot of the daily summary page."
The offers page uploads such screenshots and server.js reads them with the
`tesseract` command and earnings.js. tests/earnings.test.js holds the parser
to tesseract's TEXT (tests/fixtures/earnings.json); this holds the two
together on PICTURES of the screen — rpi/testearnings.py draws the owner's
layout at the phone's size with invented restaurants, streets and figures —
run through the real tesseract with exactly the arguments the server passes
it (server.js earningsOcr: `--psm 4 -l eng`, one OpenMP thread). The faults
that matter live between the two: a time at the right edge filed on another
line, a map's labels read as words, a grey tip line in a smaller face, a JPEG
of the same screen.

Skipped where there is no tesseract, no PIL or no node, as the other
picture suites skip.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import testearnings as T                                       # noqa: E402

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
    print('%s — skipping the earnings-screen checks' % why)
    sys.exit(0)


if not shutil.which('tesseract'):
    skip('no tesseract on this machine')
if not shutil.which('node'):
    skip('no node on this machine')
if not T.available():
    skip('no PIL or no font to draw a screen with')

# When the screenshots are read: 8 Nov 2026, 2pm New York, the morning after
# the day they show.
NOW = 1794146400000
WORK = tempfile.mkdtemp()

# One node process reads every text given it, through earnings.js as the
# server requires it.
PARSE = r"""
const E = require(process.argv[1]);
const texts = JSON.parse(require('fs').readFileSync(0, 'utf8'));
console.log(JSON.stringify(texts.map((t) => E.parse(t, { now: %d }))));
""" % NOW


def ocr(path):
    """tesseract as server.js's earningsOcr runs it."""
    return subprocess.run(['tesseract', path, 'stdout', '--psm', '4', '-l', 'eng'],
                          env=dict(os.environ, OMP_THREAD_LIMIT='1'),
                          capture_output=True, text=True, timeout=120).stdout


def parse_all(texts):
    out = subprocess.run(['node', '-e', PARSE, os.path.join(ROOT, 'earnings.js')],
                         input=json.dumps(texts), capture_output=True, text=True, timeout=60)
    return json.loads(out.stdout)


def want(trip):
    """A TRIPS row as the parser should give it back."""
    amount, kind, mins, secs, miles, clock, tip, pickup, dropoff = trip
    h, m = clock.split()[0].split(':')
    h = int(h) % 12 + (12 if clock.endswith('PM') else 0)
    name, _, detail = pickup.partition(' (')
    street, town = dropoff.split(', ')[:2]
    canceled = mins is None
    extras = None
    if tip and 'Surge' in tip:
        extras = {'surge': float(tip.split()[2][1:])}
    return {'amount': float(amount[1:]), 'startedAt': '%02d:%s' % (h, m),
            'tip': 'processing' if tip == 'Tip processing' else (float(tip.split()[0][1:]) if tip else None),
            'type': kind.split(' · ')[0] if canceled else kind, 'minutes': mins, 'seconds': secs,
            'miles': None if canceled else float(miles),
            'pickup': {'name': name, 'detail': detail.rstrip(')')},
            'dropoff': {'street': street, 'town': town},
            'status': 'canceled' if canceled else 'completed',
            'canceledBy': 'you' if canceled else None, 'extras': extras}


# The screens: the owner's layout as drawn; the time on the trip's line; the
# same screen as a JPEG (a phone's share sheet can make one); and a scroll —
# no header, the first trip's top cut off, no end line.
SCREENS = {
    'png': T.screen(),
    'time on the trip line': T.screen(time_row='detail'),
    'jpeg': T.screen(),
    'scrolled': T.screen(header=False, end=None, top_skip=200),
    # A second day, its own trips: a tip that settled at $3.00, and a chain's
    # bracket of a corner.
    'another day': T.screen(trips=[
        ('$14.10', 'Delivery', 18, 2, '3.40', '9:05 PM', '$3.00 Tip',
         'Imaginary Bistro (Faketown)', 'Example Ave, Faketown, GA, USA'),
        ('$9.80', 'Delivery', 31, 40, '7.25', '8:12 PM', 'Tip processing',
         'Make-Believe Burgers (Placeholder Rd & Mock Ln)', 'Fictional Ct SW, Notaville, GA, USA')],
        day='Fri, Nov 6', chip='11/6', end='End of activities during Nov 6, 2026'),
    # The 12 Nov layout's two new lines: a tip and a surge on one line, and a
    # trip canceled on the phone.
    'surge and canceled': T.screen(trips=T.TRIPS_12, day='Thu, Nov 12', chip='11/12',
                                   end='End of activities during Nov 12, 2026'),
}
paths = {}
for name, im in SCREENS.items():
    p = os.path.join(WORK, name.replace(' ', '-') + ('.jpg' if name == 'jpeg' else '.png'))
    T.save(im.convert('RGB'), p, 'JPEG' if name == 'jpeg' else 'PNG')
    paths[name] = p
# The 17 Nov layout: rides beside deliveries, the icons, a canceled entry
# whose time cannot be read between two trips, the chips, a ride over an
# hour; as drawn and as a JPEG.
for name, kind in (('rides', 'PNG'), ('rides jpeg', 'JPEG')):
    p = os.path.join(WORK, name.replace(' ', '-') + ('.jpg' if kind == 'JPEG' else '.png'))
    T.save(T.screen17().convert('RGB'), p, kind)
    paths[name] = p
    SCREENS[name] = None
names = list(SCREENS)
got = dict(zip(names, parse_all([ocr(paths[n]) for n in names])))


def bare(entries):
    """Entries without what each keeps of its block's raw lines (checked
    on its own below), so they compare with `want`."""
    out = []
    for e in entries:
        e = dict(e)
        e.pop('lines', None)
        out.append(e)
    return out

# --- the owner's layout, as drawn --------------------------------------------
for name in ('png', 'time on the trip line', 'jpeg'):
    g = got[name]
    eq('[screen %s] Uber\'s screen, its day from the end line' % name,
       (g['app'], (g['day'] or {}).get('iso'), (g['day'] or {}).get('from')), ('uber', '2026-11-07', 'end'))
    eq('[screen %s] every trip, in the screen\'s order, with every field' % name,
       bare(g['entries']), [want(t) for t in T.TRIPS])
    eq('[screen %s] nothing stepped over' % name, (g['others'], g['notes']), ([], []))

# --- a scroll -------------------------------------------------------------------
g = got['scrolled']
eq('[screen scrolled] no header and no end line: no day said (the server takes its batch\'s)',
   g['day'], None)
eq('[screen scrolled] the first trip, its top scrolled off, is skipped and said; the two below read whole',
   ([e['startedAt'] for e in g['entries']], g['notes']),
   (['16:50', '15:58'], ['the top of the first trip was scrolled off; its rest was skipped']))
eq('[screen scrolled] ...and they are the same trips the top of the day read', bare(g['entries']),
   [want(t) for t in T.TRIPS[1:]])

# --- another day ----------------------------------------------------------------
g = got['another day']
eq('[screen another day] its own day, a settled tip and a pending one, a chain\'s corner in the bracket',
   ((g['day'] or {}).get('iso'), [(e['startedAt'], e['amount'], e['tip'], e['pickup']) for e in g['entries']]),
   ('2026-11-06', [('21:05', 14.1, 3.0, {'name': 'Imaginary Bistro', 'detail': 'Faketown'}),
                   ('20:12', 9.8, 'processing',
                    {'name': 'Make-Believe Burgers', 'detail': 'Placeholder Rd & Mock Ln'})]))

# --- a surge, and a trip canceled on the phone ------------------------------------
g = got['surge and canceled']
eq('[screen surge and canceled] its day, and every trip with every field: the tip and the surge off one line, '
   'the canceled trip with no minutes or miles and its places kept',
   ((g['day'] or {}).get('iso'), bare(g['entries'])), ('2026-11-12', [want(t) for t in T.TRIPS_12]))
eq('[screen surge and canceled] ...the surge no block of its own, nothing stepped over', (g['others'], g['notes']),
   ([], []))

# --- rides, icons and a canceled trip between two trips (17 Nov) ----------------


def want17(t):
    """A TRIPS_17 row as the parser should give it back."""
    icon, amount, kind, dur, miles, clock, tip, chip, pickup, dropoff = t
    h, m = clock.split()[0].split(':')
    h = int(h) % 12 + (12 if clock.endswith('PM') else 0)
    hrs = int(dur.split(' hr')[0]) if ' hr' in dur else 0
    mins = int(dur.split(' min')[0].split()[-1])
    secs = int(dur.split(' sec')[0].split()[-1]) if 'sec' in dur else 0
    street, town = dropoff.split(', ')[:2]
    if icon == 'ride':
        ps, pt = pickup.split(', ')[:2]
        pick = {'name': ps, 'detail': pt, 'address': True}
    else:
        name, _, detail = pickup.partition(' (')
        pick = {'name': name, 'detail': detail.rstrip(')') or None}
    e = {'amount': float(amount[1:]), 'startedAt': '%02d:%s' % (h, m),
         'tip': float(tip.split()[0][1:]) if tip else None, 'type': kind,
         'minutes': 60 * hrs + mins, 'seconds': secs, 'miles': float(miles), 'pickup': pick,
         'dropoff': {'street': street, 'town': town}, 'status': 'completed', 'canceledBy': None, 'extras': None}
    if icon == 'ride':
        e['ride'] = True
    if chip:
        e['chips'] = [chip.lower()]
    return e


for name in ('rides', 'rides jpeg'):
    g = got[name]
    eq('[screen %s] its day; every trip but the canceled one read whole, rides with their streets, the chips, '
       'the ride over an hour' % name,
       ((g['day'] or {}).get('iso'), bare(g['entries'])),
       ('2026-11-17', [want17(t) for t in T.TRIPS_17 if t[0] != 'canceled']))
    eq('[screen %s] the canceled trip, its time unreadable, never takes the next trip\'s time: skipped and said, '
       'and the tally accounts for every entry' % name,
       (g['notes'], g['tally']['seen'], g['tally']['read'], g['tally']['skipped'], g['tally']['unread'],
        g['tally']['cut']),
       (['a $0.00 trip with no time on it was skipped'], 6, 5,
        [{'amount': 0, 'status': 'canceled', 'why': 'no time'}], [], 0))
    ok_('[screen %s] each trip keeps its block\'s raw lines for "what was read"' % name,
        all(isinstance(e.get('lines'), list) and 3 <= len(e['lines']) <= 14 for e in g['entries']))

# --- Uber's Acceptance rate screen (the owner, 15 Nov 2026) -----------------------
# The Gold card's optional reader: Uber's own three figures and its k/10, read
# as server.js goldShotRead reads them — `--psm 4`, and `--psm 6` again when
# that leaves any of the three unread. Invented figures throughout.
ACC = r"""
const E = require(process.argv[1]);
const texts = JSON.parse(require('fs').readFileSync(0, 'utf8'));
console.log(JSON.stringify(texts.map((t) => E.acceptanceScreen(t))));
"""


def acc_read(path):
    def text(psm):
        return subprocess.run(['tesseract', path, 'stdout', '--psm', psm, '-l', 'eng'],
                              env=dict(os.environ, OMP_THREAD_LIMIT='1'),
                              capture_output=True, text=True, timeout=120).stdout

    def parse(texts):
        out = subprocess.run(['node', '-e', ACC, os.path.join(ROOT, 'earnings.js')],
                             input=json.dumps([texts]), capture_output=True, text=True, timeout=60)
        return json.loads(out.stdout)[0]
    first = text('4')
    got = parse([first])
    whole = got['ok'] and got['last10'] is not None and got['rate'] is not None
    return got if whole else parse([first, text('6')])


for name, im, want_ in (
        ('2 of the last 10, read "2/110"', T.acceptance_screen(rate=17, last10=2, requests=100, accepted=17,
                                                                declined=83),
         {'requests': 100, 'accepted': 17, 'declined': 83, 'rate': 17, 'last10': 2}),
        ('as drawn', T.acceptance_screen(),
         {'requests': 100, 'accepted': 23, 'declined': 77, 'rate': 23, 'last10': 4}),
        ('a bigger phone, under 100 requests', T.acceptance_screen(rate=6, last10=1, requests=48, accepted=3,
                                                                    declined=45, scale=1.4),
         {'requests': 48, 'accepted': 3, 'declined': 45, 'rate': 6, 'last10': 1})):
    p = T.save(im, os.path.join(WORK, 'acc-%d.png' % len(name)))
    g = acc_read(p)
    eq('[acceptance %s] the three figures, the percentage and the last ten, checked' % name,
       ({k: g[k] for k in want_}, g['ok'], g['problems']), (want_, True, []))

# --- the size it is read at -----------------------------------------------------
# The owner's phone: about 756 wide. Drawn at that width and no wider, so the
# suite reads what an upload from that phone would be.
eq('[screen] drawn at the phone\'s width', SCREENS['png'].size[0], 756)
eq('[screen] the rides layout drawn at the phone\'s width too', T.screen17().size[0], 756)
ok_('[screen] ...and at least its height (%r)' % (SCREENS['png'].size,), SCREENS['png'].size[1] >= 2000)

shutil.rmtree(WORK, ignore_errors=True)
print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d earnings-screen checks passed' % ok)
sys.exit(1 if bad else 0)
