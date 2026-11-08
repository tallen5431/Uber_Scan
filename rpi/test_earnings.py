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
    return {'amount': float(amount[1:]), 'finishedAt': '%02d:%s' % (h, m),
            'tip': 'processing' if tip == 'Tip processing' else (float(tip.split()[0][1:]) if tip else None),
            'type': kind, 'minutes': mins, 'seconds': secs, 'miles': float(miles),
            'pickup': {'name': name, 'detail': detail.rstrip(')')},
            'dropoff': {'street': street, 'town': town}}


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
}
paths = {}
for name, im in SCREENS.items():
    p = os.path.join(WORK, name.replace(' ', '-') + ('.jpg' if name == 'jpeg' else '.png'))
    T.save(im.convert('RGB'), p, 'JPEG' if name == 'jpeg' else 'PNG')
    paths[name] = p
names = list(SCREENS)
got = dict(zip(names, parse_all([ocr(paths[n]) for n in names])))

# --- the owner's layout, as drawn --------------------------------------------
for name in ('png', 'time on the trip line', 'jpeg'):
    g = got[name]
    eq('[screen %s] Uber\'s screen, its day from the end line' % name,
       (g['app'], (g['day'] or {}).get('iso'), (g['day'] or {}).get('from')), ('uber', '2026-11-07', 'end'))
    eq('[screen %s] every trip, in the screen\'s order, with every field' % name,
       g['entries'], [want(t) for t in T.TRIPS])
    eq('[screen %s] nothing stepped over' % name, (g['others'], g['notes']), ([], []))

# --- a scroll -------------------------------------------------------------------
g = got['scrolled']
eq('[screen scrolled] no header and no end line: no day said (the server takes its batch\'s)',
   g['day'], None)
eq('[screen scrolled] the first trip, its top scrolled off, is skipped and said; the two below read whole',
   ([e['finishedAt'] for e in g['entries']], g['notes']),
   (['16:50', '15:58'], ['the top of the first trip was scrolled off; its rest was skipped']))
eq('[screen scrolled] ...and they are the same trips the top of the day read', g['entries'],
   [want(t) for t in T.TRIPS[1:]])

# --- another day ----------------------------------------------------------------
g = got['another day']
eq('[screen another day] its own day, a settled tip and a pending one, a chain\'s corner in the bracket',
   ((g['day'] or {}).get('iso'), [(e['finishedAt'], e['amount'], e['tip'], e['pickup']) for e in g['entries']]),
   ('2026-11-06', [('21:05', 14.1, 3.0, {'name': 'Imaginary Bistro', 'detail': 'Faketown'}),
                   ('20:12', 9.8, 'processing',
                    {'name': 'Make-Believe Burgers', 'detail': 'Placeholder Rd & Mock Ln'})]))

# --- the size it is read at -----------------------------------------------------
# The owner's phone: about 756 wide. Drawn at that width and no wider, so the
# suite reads what an upload from that phone would be.
eq('[screen] drawn at the phone\'s width', SCREENS['png'].size[0], 756)
ok_('[screen] ...and at least its height (%r)' % (SCREENS['png'].size,), SCREENS['png'].size[1] >= 2000)

shutil.rmtree(WORK, ignore_errors=True)
print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d earnings-screen checks passed' % ok)
sys.exit(1 if bad else 0)
