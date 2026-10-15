"""What tools/shift_report.py says each order taken really took.

    python3 tools/test_shift_report.py

Every row and every position here is invented. The journal is one made-up
evening of eleven marks; the GPS log is a straight drive east along a line of
latitude nowhere near the driver, written in gpspipe's own `-w -uu` shape,
half of it gzipped the way tools/gpslog_tidy.py leaves it. The track is built
from distances, so what the report should say is known before it runs.
"""

import contextlib
import csv
import gzip
import io
import json
import math
import os
import subprocess
import re
import shutil
import sys
import tempfile
import time

os.environ['TZ'] = os.environ.get('TZ') or 'America/New_York'
time.tzset()

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import shift_report as SR                                     # noqa: E402

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


def near(name, got, want, tol):
    ok_('%s (got %r, want %r +- %r)' % (name, got, want, tol),
        got is not None and abs(got - want) <= tol)


def at(h, m, s=0, day=3):
    """Local ms on 2026-03-0<day> (EST: the clocks go forward on the 8th)."""
    return int(time.mktime((2026, 3, day, h, m, s, 0, 0, -1)) * 1000)


# --- the invented evening ---------------------------------------------------
#
#   A  uber      $12.00  30 min card  Took 18:00  visit 18:12  Drop 18:30
#   B  doordash   $9.00  20 min card  Took 18:20  GPS drop 18:45   (A in car)
#   C  uber       $8.00  15 min card  Took 19:00  replaced 19:10 by D's Took
#   D  uber      $15.00  40 min card  Took 19:10  Drop 19:40 (GPS ends 19:20)
#   E  uber       $7.00  20 min card  Took 20:00  no drop row at all
#   F  doordash  $10.00  25 min card  Took 20:15  chooser 20:40, two in the car
#   G  uber       marked taken on the offers page only; never pressed
#   H  uber       Took, then taken back from the panel (null)
#   I  uber       Took, then an old page's bare `false`: a take-back too
#   M  uber       $9.00  20 min card  Took 21:30  expired 21:55, by the row
#                 (the rig's grace shorter than the default: the row, not
#                 this report's reckoning of holdEnds, 21:30 + 40 = 22:10)
#   L  uber       Took 22:00, ended by a drop row from a newer build
#   J  uber       Took at 03:30 on the 3rd: the day before's shift
#   K  uber       $6.00  10 min card  Took 03:30 on the 4th: still the 3rd's
#                 shift, by advice.js's 4am day; Drop 03:50

PICKUP = 'Imaginary Bistro (1 Nowhere Ln)'
DROPOFF = '742 Example Ave, Faketown'
UBER = '$%.2f\n%d min (%.1f mi) total\n' + PICKUP + '\n' + DROPOFF + '\nAccept'
DASH = '$%.2f\nDeliver by 9:45 PM\n' + PICKUP + '\nAccept\nDecline\n%.1f mi'


def offer(oid, when, pay, minutes, miles, app='uber'):
    text = UBER % (pay, minutes, miles) if app == 'uber' else DASH % (pay, miles)
    return {'v': 1, 'id': oid, 'at': when, 'seq': 1, 'pay': pay, 'minutes': minutes,
            'billedMinutes': minutes, 'miles': miles, 'text': text, 'pickup': PICKUP,
            'dropoff': DROPOFF, 'lat': 12.3456, 'lon': 45.6789}


def mark(oid, when, accepted, via='panel'):
    row = {'v': 1, 'kind': 'mark', 'id': oid, 'at': when, 'accepted': accepted}
    if via is not None:
        row['via'] = via
    return row


def drop(oid, when, by=None, carried=None):
    row = {'v': 1, 'kind': 'drop', 'at': when, 'id': oid, 'seq': when, 'acceptedAt': when - 1}
    if by:
        row['by'] = by
    if carried:
        row['carried'] = carried
    return row


ROWS = [
    # A: misread a minute before, the card as taken ten seconds before, and a
    # later reading the report must not take for what was taken.
    offer('A', at(17, 59), 11.00, 30, 6.0), offer('A', at(17, 59, 50), 12.00, 30, 6.0),
    offer('A', at(18, 1), 99.00, 30, 6.0),
    mark('A', at(18, 0), True),
    {'v': 1, 'kind': 'visit', 'at': at(18, 12), 'id': 'A@%d#0' % at(17, 59, 50),
     'seq': at(18, 12), 'holdId': 'A@%d' % at(17, 59, 50), 'pickup': 0, 'by': 'gps'},
    drop('A', at(18, 30), carried=2),
    offer('B', at(18, 19, 50), 9.00, 20, 3.2, app='dd'), mark('B', at(18, 20), True),
    drop('B', at(18, 45), by='gps'),
    offer('C', at(18, 59, 50), 8.00, 15, 3.0), mark('C', at(19, 0), True),
    offer('D', at(19, 9, 50), 15.00, 40, 12.0), mark('D', at(19, 10), True),
    drop('C', at(19, 10), by='replaced'),
    drop('D', at(19, 40)),
    offer('E', at(19, 59, 50), 7.00, 20, 4.0), mark('E', at(20, 0), True),
    offer('F', at(20, 14, 50), 10.00, 25, 5.0, app='dd'), mark('F', at(20, 15), True),
    drop('F', at(20, 40), by='chooser', carried=2),
    offer('G', at(21, 0), 5.00, 12, 2.0), mark('G', at(23, 30), True, via='review'),
    offer('H', at(21, 10), 5.00, 12, 2.0), mark('H', at(21, 10, 10), True),
    mark('H', at(21, 10, 20), None),
    offer('I', at(21, 20), 5.00, 12, 2.0), mark('I', at(21, 20, 10), True, via=None),
    mark('I', at(21, 20, 20), False, via=None),
    offer('L', at(21, 59, 50), 5.00, 12, 2.0), mark('L', at(22, 0), True),
    drop('L', at(22, 20), by='teleport'),
    offer('M', at(21, 29, 50), 9.00, 20, 4.0), mark('M', at(21, 30), True),
    drop('M', at(21, 55), by='expiry'),
    offer('J', at(3, 29, 50), 5.00, 12, 2.0), mark('J', at(3, 30), True), drop('J', at(3, 45)),
    offer('K', at(3, 29, 50, day=4), 6.00, 10, 2.0), mark('K', at(3, 30, day=4), True),
    drop('K', at(3, 50, day=4)),
]

# --- the invented track -------------------------------------------------------
#
# East along 12.3456 N from 45.6789 E: invented, and checked below to appear
# nowhere in what the report prints.
LAT0, LON0 = 12.3456, 45.6789
PER_M = 1.0 / (SR.G.WGS84_A * math.cos(math.radians(LAT0)) * math.pi / 180.0)


def lon_at(metres):
    return LON0 + metres * PER_M


def track_points():
    """[(t seconds, lat, lon, eph, speed)] at one a second, and the metres driven
    between Took and Drop of A, which is what its GPS miles must come to."""
    pts = []
    pos = 0.0

    def hold(t0, t1):
        for t in range(t0, t1):
            # A parked receiver's wander, two metres either way.
            pts.append((t, LAT0, lon_at(pos + (2.0 if t % 2 else -2.0)), 8.0, 0.0))

    def drive(t0, t1, speed, skip=()):
        nonlocal pos
        for t in range(t0, t1):
            if not any(a <= t < b for a, b in skip):
                pts.append((t, LAT0, lon_at(pos), 8.0, speed))
            pos += speed

    s = lambda h, m, sec=0: at(h, m, sec) // 1000              # noqa: E731
    # Ten seconds of a lat/lon that does not move by one bit while the TPV
    # says 10 m/s: what the owner's VK-162 sent under gpsd's binary mode.
    # gps.usable() calls the fixes past FROZEN_AFTER (5 s) `frozen`, and
    # only through gps.Phone.take's bookkeeping can it know.
    for t in range(s(17, 50), s(17, 50, 10)):
        pts.append((t, LAT0, LON0, 8.0, 10.0))
    hold(s(17, 58), s(18, 0))
    drive(s(18, 0), s(18, 5), 10.0)                     # 3,000 m
    hold(s(18, 5), s(18, 11, 30))                       # the restaurant, 6.5 min
    # 9,300 m, with nothing from the receiver for 18:15-18:18: a gap of three
    # minutes the report has to bridge, in a straight line, and say so.
    drive(s(18, 11, 30), s(18, 27), 10.0, skip=[(s(18, 15), s(18, 18))])
    hold(s(18, 27), s(18, 47))                          # the door
    drive(s(18, 47), s(19, 20), 5.0)
    # One fix the gate refuses (eph 80 m, over FIX_ERR_MAX), five km north in
    # the middle of A's drive: used, it would add ten km.
    pts.append((s(18, 20), LAT0 + 0.045, lon_at(0), 80.0, 0.0))
    pts.sort()
    return pts, 3000.0 + 9300.0


def tpv(t, lat, lon, eph, speed=0.0):
    return json.dumps({'class': 'TPV', 'device': '/dev/ttyACM0', 'mode': 3,
                       'time': time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime(t)),
                       'lat': lat, 'lon': lon, 'eph': eph, 'speed': speed},
                      separators=(',', ':'))


def stamped(t, body):
    return '%s %.6f: %s\n' % (time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(t)), t, body)


work = tempfile.mkdtemp()
JOURNAL = os.path.join(work, 'journal.jsonl')
with open(JOURNAL, 'w') as fh:
    for r in ROWS:
        fh.write(json.dumps(r) + '\n')
    fh.write('{"half a row\n')
GPSDIR = os.path.join(work, 'gpslog')
os.mkdir(GPSDIR)
POINTS, A_METRES = track_points()
split = at(18, 5) // 1000
with gzip.open(os.path.join(GPSDIR, '2026-03-03_1758.jsonl.gz'), 'wt') as fh:
    fh.write(stamped(POINTS[0][0], '{"class":"VERSION","release":"3.25"}'))
    for p in POINTS:
        if p[0] < split:
            fh.write(stamped(p[0], tpv(*p)))
with open(os.path.join(GPSDIR, '2026-03-03_1805.jsonl'), 'w') as fh:
    # A line from a Pi whose clock was not set yet, at a far-off place, and
    # one gpspipe wrote with no stamp: both counted, neither used.
    fh.write(stamped(12.5, tpv(12.5, LAT0 - 1.0, LON0 - 1.0, 8.0)))
    fh.write(tpv(0, LAT0 - 1.0, LON0 - 1.0, 8.0) + '\n')
    for p in POINTS:
        if p[0] >= split:
            fh.write(stamped(p[0], tpv(*p)))
            if p[0] % 5 == 0:
                fh.write(stamped(p[0], '{"class":"SKY","satellites":[]}'))


def run(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = SR.main(argv)
    return code, buf.getvalue()


rep = SR.report(JOURNAL, GPSDIR, '2026-03-03')
by = {o['id']: o for o in rep['orders']}

# --- which orders ---------------------------------------------------------------
eq('orders taken: every Took on the day, by Took, then the one never pressed',
   [o['id'] for o in rep['orders']], ['A', 'B', 'C', 'D', 'E', 'F', 'M', 'L', 'K', 'G'])
ok_('a Took taken back from the panel is not an order', 'H' not in by)
ok_("...nor one an old page took back with a bare false", 'I' not in by)
ok_("the day is the driver's: 03:30 on the 3rd is the shift before", 'J' not in by)
ok_("...and 03:30 on the 4th is still this one (advice.js's 4am)", 'K' in by)
eq('one marked taken on the offers page only has no Took', by['G']['took'], None)
eq('...and says so', by['G']['how'], 'no Took')
eq('the card is the reading on the panel at the Took, not one read after',
   by['A']['pay'], 12.00)
eq("the app is read off the card's text", (by['A']['app'], by['B']['app']),
   ('uber', 'doordash'))
eq('card minutes and miles are the card\'s own', (by['A']['cardMinutes'], by['A']['cardMiles']),
   (30, 6.0))

# --- actual minutes ---------------------------------------------------------
near('actual minutes: A, Took 18:00 to Drop 18:30', by['A']['actualMinutes'], 30.0, 1e-9)
near('actual minutes: B, Took 18:20 to the GPS drop at 18:45', by['B']['actualMinutes'], 25.0, 1e-9)
near('actual minutes: D, Took 19:10 to Drop 19:40', by['D']['actualMinutes'], 30.0, 1e-9)
near('actual minutes: F, Took 20:15 to the chooser at 20:40', by['F']['actualMinutes'], 25.0, 1e-9)
eq('how each ended', [by[k]['how'] for k in 'ABCDEF'],
   ['Drop', 'GPS drop', 'replaced', 'Drop', 'no end', 'chooser'])
near('actual $/hr is card pay over the actual hours (A: $12 over 0.5 h)',
     by['A']['perHour'], 24.0, 1e-9)

# --- unreliable ends ----------------------------------------------------------
eq('replaced or expired orders are unreliable: C replaced, E with no end',
   (by['C']['reliable'], by['E']['reliable']), (False, False))
ok_('...and each row says why',
    any('unreliable' in n for n in by['C']['notes'])
    and any('unreliable' in n for n in by['E']['notes']))
eq('...while a Drop, a GPS drop and the chooser are not',
   [by[k]['reliable'] for k in 'ABDF'], [True, True, True, True])
eq('a drop row this build does not know is unreliable, and named (L)',
   (by['L']['reliable'], by['L']['how']), (False, 'drop by teleport'))
eq('an order with no end has no actual minutes, not the card\'s clock',
   by['E']['actualMinutes'], None)

# --- an expiry row ------------------------------------------------------------
# server.js's expiredRows: an order that outlived its own clock is written
# `by: 'expiry'`, dated when the server stopped counting it.
eq('an expiry row is an end that is "expired", not "no end" (M)',
   (by['M']['how'], by['M']['reliable']), ('expired', False))
eq('...whose minutes are not measured: no actual minutes, no $/hr, no end clock',
   (by['M']['actualMinutes'], by['M']['perHour'], by['M']['end']), (None, None, None))
ok_('...and the row says it expired, and why it is not timed',
    any(n.startswith('unreliable: expired on its own clock at 21:55') for n in by['M']['notes']))
ok_('...not the note for an order with no row at all',
    not any('lost the hold' in n for n in by['M']['notes'])
    and any('lost the hold' in n for n in by['E']['notes']))
eq('...and its row bounds what rode with it: L, taken at 22:00, after the expiry '
   'at 21:55 and before 22:10',
   (by['M']['alongside'], by['L']['alongside']), ('no', 'no'))
eq('...nor is GPS measured over it', by['M']['gpsMiles'], None)
eq('replaced or expired orders are unreliable: no $/hr off a replaced order\'s 10 minutes',
   by['C']['perHour'], None)

# --- the GPS ----------------------------------------------------------------
near('GPS miles: A drove 12,300 m, Took to Drop', by['A']['gpsMiles'],
     A_METRES / 1609.344, 0.05)
ok_('miles bridged and flagged over a gap: A says one gap bridged',
    any(re.search(r'1 GPS gap over 60 s bridged in a straight line \(3\.0 min\)', n)
        for n in by['A']['notes']))
eq('only gate-passed fixes count: the eph 80 m fix is refused as rough',
   rep['info']['refused'].get('rough'), 1)
eq('a lat/lon frozen while the car moves is refused, through gps.Phone.take (4 of 10)',
   rep['info']['refused'].get('frozen'), 4)
eq('a line stamped before the clock was set is counted, not used', rep['info']['beforeClock'], 1)
eq('...and one with no -uu stamp', rep['info']['unstamped'], 1)
eq('both logs are read, the gzipped one too', rep['info']['files'], 2)
ok_('D, whose log ends 20 minutes before its Drop, says the miles miss them',
    any('no GPS fix for the last 20.0 min' in n for n in by['D']['notes']))
ok_('F, with no fix at all in its span, has no miles and says so',
    by['F']['gpsMiles'] is None
    and any('no usable GPS fix' in n for n in by['F']['notes']))
near('time at the restaurant: A stood 6.5 min before the visit row',
     by['A']['restaurantMinutes'], 6.5, 0.15)
near('time at the door: A, stopped from 18:27 to the Drop at 18:30',
     by['A']['doorMinutes'], 3.0, 0.15)
eq('no visit row, no restaurant time (D)', by['D']['restaurantMinutes'], None)
eq('a replaced order has no door time (C)', by['C']['doorMinutes'], None)

# --- carried alongside --------------------------------------------------------
eq('carried alongside: A (its drop row says two) and B (inside A)',
   (by['A']['alongside'], by['B']['alongside']), ('yes', 'yes'))
eq('...not D, taken as C was put down', by['D']['alongside'], 'no')
eq("...and F yes, on its chooser row's word (E, beside it, has no end)",
   by['F']['alongside'], 'yes')
eq("...while E is '?': F was taken inside the 40 min the server would count E",
   by['E']['alongside'], '?')

# --- the summary ------------------------------------------------------------
s = rep['summary']
eq('the summary is over the reliable rows: A, B, D, F, K of 10',
   (s['reliable'], s['of']), (5, 10))
apps = {g['group']: g for g in s['byApp']}
near('uber: median actual/card minutes over A 1.0, D 0.75, K 2.0',
     apps['uber']['ratio'], 1.0, 1e-9)
near('uber: median actual $/hr over A $24, D $30, K $18', apps['uber']['perHour'], 24.0, 1e-9)
near('doordash: median actual/card minutes over B 1.25, F 1.0', apps['doordash']['ratio'], 1.125, 1e-9)
near('doordash: median actual $/hr over B $21.60, F $24', apps['doordash']['perHour'], 22.8, 1e-9)
eq('bands in order, by the card\'s minutes',
   [(g['group'], g['n']) for g in s['byBand']],
   [('0-20 min', 1), ('20-30 min', 2), ('30-45 min', 2)])

# --- what is printed ----------------------------------------------------------
code, out = run(['--journal', JOURNAL, '--gps', GPSDIR, '--day', '2026-03-03'])
code_csv, out_csv = run(['--journal', JOURNAL, '--gps', GPSDIR, '--day', '2026-03-03', '--csv'])
eq('the CLI exits 0', (code, code_csv), (0, 0))
for name, got in (('text', out), ('CSV', out_csv)):
    bare = [w for w in ('Nowhere', 'Example Ave', 'Faketown', 'Bistro') if w in got]
    eq('no address or coordinate in the output: no place in the %s' % name, bare, [])
    coords = re.findall(r'12\.34|45\.67|11\.34|44\.67|\d+\.\d{4,}', got)
    eq('no address or coordinate in the output: no coordinate in the %s' % name, coords, [])
rows = list(csv.DictReader(io.StringIO(out_csv)))
eq('the CSV has a row per order', [r['id'] for r in rows],
   ['A', 'B', 'C', 'D', 'E', 'F', 'M', 'L', 'K', 'G'])
eq('...and marks the unreliable ones', [r['reliable'] for r in rows],
   ['yes', 'yes', 'no', 'yes', 'no', 'yes', 'no', 'no', 'yes', 'no'])
eq('...and an expiry is "expired" with no end clock in it',
   [(r['how'], r['ended'], r['actual_minutes']) for r in rows if r['id'] == 'M'],
   [('expired', '', '')])
ok_('the text summary names expired orders among those left out',
    'replaced, expired or with no end is left out' in out)
ok_('the text says the 1 unreadable journal line was skipped', '1 unreadable line skipped' in out)
summary_text = out[out.index('Over the '):]
said = re.findall(r'\b(should|recommend\w*|avoid|worth|better|prefer\w*|target|take more|skip)\b',
                  summary_text, re.I)
eq('the summary describes and recommends nothing', said, [])

# --- a missing GPS log ----------------------------------------------------------
gone = os.path.join(work, 'no-such-dir')
code, out = run(['--journal', JOURNAL, '--gps', gone, '--day', '2026-03-03'])
eq('a missing GPS log: the report still runs', code, 0)
ok_('a missing GPS log: the header says there is none', 'GPS: no log found' in out)
miss = SR.report(JOURNAL, gone, '2026-03-03')
mb = {o['id']: o for o in miss['orders']}
eq('a missing GPS log: miles blank on every row',
   [o['gpsMiles'] for o in miss['orders']], [None] * len(miss['orders']))
ok_('a missing GPS log: each timed row says so',
    all(any('no GPS log' in n for n in mb[k]['notes']) for k in 'ABCDF'))
near('...and the minutes are still measured', mb['A']['actualMinutes'], 30.0, 1e-9)
code, _ = run(['--journal', JOURNAL, '--day', '2026-03-03'])
eq('...and --gps left out is the same', code, 0)

# --- nothing reads it ---------------------------------------------------------
readers = []
# The files git tracks, not a walk of the directory: a walk also reads other
# checkouts kept under the tree (.claude/worktrees/…), whose copies of this
# very suite then count as readers of the report.
_tracked = subprocess.run(['git', 'ls-files'], cwd=ROOT, capture_output=True,
                          text=True, check=True).stdout.split()
for rel in _tracked:
    if any(part in rel.split('/') for part in ('node_modules', 'vendor')):
        continue
    f = os.path.basename(rel)
    path = os.path.join(ROOT, rel)
    if rel in ('tools/shift_report.py', 'tools/test_shift_report.py'):
        continue
    if not f.endswith(('.js', '.html', '.py', '.sh')):
        continue
    with open(path, encoding='utf-8', errors='replace') as fh:
        src = fh.read()
    if f.endswith(('.js', '.html')) and 'shift_report' in src:
        readers.append(rel)
    elif f.endswith('.py') and re.search(r'^\s*(?:import|from)\s+shift_report\b', src, re.M):
        readers.append(rel)
eq('nothing on the rig reads the report (the rating, the target, advice.js, the pages)',
   readers, [])

shutil.rmtree(work)
print('FAILED: %d of %d' % (bad, ok + bad) if bad
      else '\nAll %d shift report checks passed' % ok)
sys.exit(1 if bad else 0)
