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
    bare = [w for w in ('Nowhere', 'Example Ave', 'Faketown') if w in got]
    eq('no address or coordinate in the output: no place in the %s' % name, bare, [])
    # The store's name is printed in one place, the Restaurant waits section,
    # and its bracketed street (above) never.
    _named = got.replace(got[got.index('Restaurant waits'):got.index('Pinning')], '') \
        if 'Restaurant waits' in got else got
    eq('...and the store\'s name nowhere but its Restaurant waits line in the %s' % name,
       'Bistro' in _named, False)
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
    'replaced, expired, put down with another too soon, pressed down too soon, driven well '
    'short of its card or with no end is left out' in out)
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

# --- the day's own logs, and no others -------------------------------------------
# gpslog_tidy keeps KEEP_DAYS of logs, and a day's report read every one of
# them. It reads, by the names gpspipe gives them, the logs that can hold a fix
# the day's orders are measured over: those begun inside the day (or before the
# last of its orders' ends) and the newest begun before it, which may be the
# one still running across the day's start.
_lone = os.path.join(work, 'gps-neighbour')
os.mkdir(_lone)
with open(os.path.join(_lone, '2026-03-02_2300.jsonl'), 'w') as fh:
    for p in POINTS:
        fh.write(stamped(p[0], tpv(*p)))
_alone = SR.report(JOURNAL, _lone, '2026-03-03')
ok_("a log begun the evening before and running through the day is read for it "
    "(A's GPS miles)", {o['id']: o for o in _alone['orders']}['A']['gpsMiles'] is not None)
_many = os.path.join(work, 'gps-many')
shutil.copytree(_lone, _many)
for _name, _day in (('2026-03-01_1200.jsonl', 1), ('2026-03-02_0900.jsonl', 2),
                    ('2026-03-05_1000.jsonl', 5)):
    with open(os.path.join(_many, _name), 'w') as fh:
        for _k in range(10):
            _t = at(12, _k, day=_day) // 1000
            fh.write(stamped(_t, tpv(_t, LAT0, LON0, 8.0)))
_dr = SR.report(JOURNAL, _many, '2026-03-03')
eq("a day's report reads the logs that can hold its fixes and not the other days' "
   "(read, left)", (_dr['info']['files'], _dr['info']['otherDays']), (1, 3))
eq('...and its rows are what that one log gives alone',
   [SR.cells(o) for o in _dr['orders']], [SR.cells(o) for o in _alone['orders']])
ok_('...and the header says how many it left', '3 logs of other days not read' in SR.text(_dr))
eq('a log whose name gives no day is always read', SR._logs_for(
    ['gps-00.jsonl', '2026-03-05_1000.jsonl'], (at(4, 0), at(4, 0, day=4))), ['gps-00.jsonl'])
eq('...and a name with the date alone counts as the whole of that date: the day '
   'before, the day and the day after are read for a day that starts at 4am',
   SR._logs_for(['2026-03-01.jsonl', '2026-03-02.jsonl', '2026-03-03.jsonl',
                 '2026-03-04.jsonl', '2026-03-05.jsonl'], (at(4, 0), at(4, 0, day=4))),
   ['2026-03-02.jsonl', '2026-03-03.jsonl', '2026-03-04.jsonl'])

# --- an order with no Took is placed by its first reading -------------------------
# One pass over the journal now, for every such order at once. The FIRST
# reading still decides the day: N is read on the 3rd and again on the 4th.
_nj = os.path.join(work, 'journal-n.jsonl')
with open(_nj, 'w') as fh:
    for r in (offer('N', at(21, 0), 6.00, 15, 3.0), offer('N', at(21, 0, day=4), 6.00, 15, 3.0),
              mark('N', at(21, 30, day=4), True, via='review')):
        fh.write(json.dumps(r) + '\n')
eq('an order with no Took is on the day of its first reading, and not the next',
   ([o['id'] for o in SR.report(_nj, None, '2026-03-03')['orders']],
    [o['id'] for o in SR.report(_nj, None, '2026-03-04')['orders']]), (['N'], []))

# --- the shift's totals -------------------------------------------------------
#
# A second invented evening, on the 5th, built for the totals alone: on the
# same invented line of latitude, `pos` metres east of where the log begins.
#
#   17:00:00-17:11  parked at start (+-2 m of wander)
#   17:11-17:24     NOTHING: the rig off while the car drove 3,000 m away —
#                   the 16 Oct shape, which must be a gap and not a stop
#   17:24-17:34     drive east 6,000 m
#   17:34-17:50     parked, 16 min (9,000 m from start)
#   17:50-17:55     drive east 3,000 m
#   17:55-17:58     parked 3 min, and the receiver jumps 100 m and back four
#                   times at a speed of nothing: not miles, and not a stop
#                   long enough to list
#   17:58-18:08     drive east 6,000 m
#   18:08-18:14     parked (18,000 m out)
#   18:14-18:20     NOTHING: the rig rebooted where it stood
#   18:20-18:26     parked, the same place: two stops either side of a gap
#   18:26-18:56     drive west 18,000 m, back to start
#   18:56-19:10     parked at start until the log ends
T5 = lambda h, m, sec=0: at(h, m, sec, day=5) // 1000            # noqa: E731


def evening5():
    pts, pos = [], 0.0

    def hold(t0, t1, jumps=()):
        for t in range(t0, t1):
            jump = 100.0 if t in jumps else (2.0 if t % 2 else -2.0)
            pts.append((t, LAT0, lon_at(pos + jump), 8.0, 0.0))

    def drive(t0, t1, speed):
        nonlocal pos
        for t in range(t0, t1):
            pts.append((t, LAT0, lon_at(pos), 8.0, abs(speed)))
            pos += speed

    hold(T5(17, 0), T5(17, 11))
    pos = 3000.0
    drive(T5(17, 24), T5(17, 34), 10.0)
    hold(T5(17, 34), T5(17, 50))
    drive(T5(17, 50), T5(17, 55), 10.0)
    hold(T5(17, 55), T5(17, 58), jumps={T5(17, 55, 30), T5(17, 56), T5(17, 56, 30), T5(17, 57)})
    drive(T5(17, 58), T5(18, 8), 10.0)
    hold(T5(18, 8), T5(18, 14))
    hold(T5(18, 20), T5(18, 26))
    drive(T5(18, 26), T5(18, 56), -10.0)
    hold(T5(18, 56), T5(19, 10))
    return pts


DRIVEN5 = 6000.0 + 3000.0 + 6000.0 + 18000.0            # metres between fixes
GPS5 = os.path.join(work, 'gps-totals')
os.mkdir(GPS5)
_p5 = evening5()
with gzip.open(os.path.join(GPS5, '2026-03-05_1700.jsonl.gz'), 'wt') as fh:
    for p in _p5:
        if p[0] < T5(18, 15):
            fh.write(stamped(p[0], tpv(*p)))
with open(os.path.join(GPS5, '2026-03-05_1819.jsonl'), 'w') as fh:
    for p in _p5:
        if p[0] >= T5(18, 15):
            fh.write(stamped(p[0], tpv(*p)))
J5 = os.path.join(work, 'journal-5.jsonl')
with open(J5, 'w') as fh:
    for r in (offer('P', at(17, 29, 50, day=5), 8.00, 20, 4.0), mark('P', at(17, 30, day=5), True),
              drop('P', at(17, 45, day=5)),
              offer('Q', at(18, 0, day=5), 9.00, 25, 5.0), mark('Q', at(18, 1, day=5), True),
              drop('Q', at(18, 20, day=5))):
        fh.write(json.dumps(r) + '\n')

rep5 = SR.report(J5, GPS5, '2026-03-05')
t5 = rep5['totals']
eq('totals: rig on and off are the first and last usable fix',
   (t5['on'], t5['off']), (T5(17, 0), T5(19, 10) - 1))
eq('totals: the two silences over 60 s are the gaps, each from the fix before '
   'to the fix after', [(g['from'], g['to']) for g in t5['gaps']],
   [(T5(17, 11) - 1, T5(17, 24)), (T5(18, 14) - 1, T5(18, 20))])
near('...and the first came back 3,000 m (1.9 mi) from where it went quiet',
     t5['gaps'][0]['apartMiles'], 2998.0 / 1609.344, 0.01)

# The gap rule: miles, stops and minutes never cross a gap.
near('a gap counts no miles: the shift is the 33,000 m driven between fixes, '
     'not the 3,000 m across the first gap', t5['miles'], DRIVEN5 / 1609.344, 0.15)
stops5 = [(s['from'], round(s['seconds'])) for s in t5['stops']]
eq('a gap does not merge into a stop: parked, rebooted, parked is two stops, '
   'each ending or starting at the gap',
   [x for x in stops5 if T5(18, 0) <= x[0] < T5(18, 30)],
   [(T5(18, 8), 6 * 60 - 1), (T5(18, 20), 6 * 60 - 1)])
eq('...and the stop at start ends where the log went quiet, not at the first '
   'fix after the gap', stops5[0], (T5(17, 0), 11 * 60 - 1))
eq('...and says which edges the log cut',
   [[k for k in ('fromOn', 'afterGap', 'beforeGap', 'toOff') if s[k]] for s in t5['stops']],
   [['fromOn', 'beforeGap'], [], ['beforeGap'], ['afterGap'], ['toOff']])
near('a gap is neither moving nor stopped: 55 min moving', t5['moving'] / 60.0, 55.0, 0.05)
near('a gap is neither moving nor stopped: 56 min stopped (parked, less the '
     'second before each gap)', t5['stopped'] / 60.0, 56.0 - 3 / 60.0, 0.05)
near('...and the 19 min of gaps are counted apart', t5['gapSeconds'] / 60.0, 19.0 + 2 / 60.0, 0.01)
eq('...and the three add up to the time the rig was on',
   round(t5['moving'] + t5['stopped'] + t5['gapSeconds'] + t5['noSpeed']),
   t5['off'] - t5['on'])

# A departure after a gap.
eq('a departure after a gap is the first fix after it', t5['left']['at'], T5(17, 24))
eq('...and says from when it may have been', t5['left']['since'], T5(17, 11) - 1)
# Back within START_M of the first fix (2 m west of 0): driving west at 10 m/s
# from 18,000 m, the first fix at 148 m or less is 1,786 s after 18:26.
eq('back at start: the first fix within START_M on the way in', t5['back']['at'],
   T5(18, 26) + 1786)
eq('...with no gap before it, so no "may have been"', t5['back']['since'], None)

# Parked jitter is not miles.
eq('a stop under 4 min is not listed (17:55, 3 min)',
   [x for x in stops5 if T5(17, 50) <= x[0] < T5(17, 58)], [])
eq('stops of 4 min or more, by time', [x[0] for x in stops5],
   [T5(17, 0), T5(17, 34), T5(18, 8), T5(18, 20), T5(18, 56)])
eq('...and their distance from start, never a position',
   [('start' if s['atStart'] else round(s['fromStartMiles'], 1)) for s in t5['stops']],
   ['start', 5.6, 11.2, 11.2, 'start'])

_jit = [(float(t), LAT0, lon_at(2.0 if t % 2 else -2.0), 0.0) for t in range(0, 1800)]
eq('jitter while parked is not miles: half an hour of +-2 m wander is 0.0 mi',
   SR.run_metres(_jit), 0.0)
# ...and the same with no speed on the fixes, or a speed reading noise of 1.5
# m/s, which the parked rule cannot see: JITTER_M is what holds it then.
eq('...nor with no speed to say it was parked',
   SR.run_metres([(f[0], f[1], f[2], None) for f in _jit]), 0.0)
eq('...nor with a speed that reads noise', SR.run_metres([(f[0], f[1], f[2], 1.5) for f in _jit]),
   0.0)
_jump = [(float(t), LAT0, lon_at(100.0 if t % 60 == 30 else 0.0), 0.0) for t in range(0, 600)]
eq('...nor a parked receiver jumping 100 m and back at a speed of nothing',
   SR.run_metres(_jump), 0.0)
_go = [(float(t), LAT0, lon_at(10.0 * t), 10.0) for t in range(0, 101)]
# ...short by at most the last step under JITTER_M, which the gate cannot vouch for.
near('...while a car driven 1,000 m at 10 m/s is 1,000 m', SR.run_metres(_go), 1000.0,
     SR.JITTER_M)
_nospeed = [(f[0], f[1], f[2], None) for f in _go]
near('...and one whose fixes give no speed is not said to be parked',
     SR.run_metres(_nospeed), 1000.0, SR.JITTER_M)

# Departures without a gap, never leaving, and not coming back.
_out = ([(float(t), LAT0, lon_at(0.0), 0.0) for t in range(0, 600)]
        + [(600.0 + t, LAT0, lon_at(5.0 + 10.0 * t), 10.0) for t in range(1, 601)])
_to = SR.totals(_out, 0, 10 ** 6)
eq('a departure with no gap is the first fix beyond START_M, and has no "since"',
   (_to['left']['at'], _to['left']['since']), (615.0, None))
eq('...and a car still away at the last fix is not back', (_to['back'], _to['stillAway']),
   (None, True))
_lap = ([(float(t), LAT0, lon_at(0.0), 0.0) for t in range(0, 300)]
        + [(300.0 + t, LAT0, lon_at(10.0 * t), 10.0) for t in range(1, 31)]
        + [(330.0 + t, LAT0, lon_at(300.0 - 10.0 * t), 10.0) for t in range(1, 31)]
        + [(360.0 + t, LAT0, lon_at(0.0), 0.0) for t in range(1, 300)])
eq('a minute out and back (a car park, a lap of the block) is not leaving',
   SR.totals(_lap, 0, 10 ** 6)['left'], None)
_twice = ([(float(t), LAT0, lon_at(0.0), 0.0) for t in range(0, 600)]
          + [(600.0 + t, LAT0, lon_at(1000.0), 0.0) for t in range(0, 600)]
          + [(1200.0 + t, LAT0, lon_at(0.0), 0.0) for t in range(0, 600)]
          + [(1800.0 + t, LAT0, lon_at(1000.0), 0.0) for t in range(0, 600)]
          + [(2400.0 + t, LAT0, lon_at(0.0), 0.0) for t in range(0, 600)])
_tw = SR.totals(_twice, 0, 10 ** 6)
eq('out and back twice: left at the first leaving, back at the last return',
   (_tw['left']['at'], _tw['back']['at'], _tw['stillAway']), (600.0, 2400.0, False))
eq('no fix on the day: no totals', SR.totals(_out, 10 ** 6, 2 * 10 ** 6), None)

# What is printed.
code5, out5 = run(['--journal', J5, '--gps', GPS5, '--day', '2026-03-05'])
eq('the totals CLI exits 0', code5, 0)
tot_text = out5[out5.index('Shift totals'):out5.index('\n#  app')]
ok_('the totals are printed above the per-order table', out5.index('Shift totals') < out5.index('#  app'))
for _want in ('rig on          17:00', 'rig off         19:09',
              'left start      17:24, the first fix after a gap in the log: it may have been '
              'any time from 17:10',
              'back at start   18:55', 'miles driven    20.5, between fixes only: the 2 gaps '
              'below not counted',
              'moving          55 min', 'stopped         56 min', 'in gaps         19 min, '
              'counted as neither', 'miles driven in a gap are not counted',
              '17:10-17:24   13.0 min, the car 1.9 mi', '17:34   16.0 min  5.6 mi from start',
              '18:08    6.0 min  11.2 mi from start, then the log went quiet',
              '18:20    6.0 min  11.2 mi from start, after a gap in the log',
              '17:00   11.0 min  at start, from rig on, then the log went quiet',
              'orders taken    2'):
    ok_('the totals say %r' % _want, _want in tot_text)
for name, got, shape in (
        ('totals', tot_text, r'12\.34|45\.67|\d+\.\d{2,}'),
        ('whole report on the 5th', out5, r'12\.34|45\.67|11\.34|44\.67|\d+\.\d{4,}')):
    eq('no address or coordinate in the output: nothing shaped like a lat/lon in the %s'
       % name, re.findall(shape, got), [])
ok_('...and every number in the totals is a clock, whole minutes or one decimal',
    all(re.fullmatch(r'\d{1,4}(?:\.\d)?', n) for n in re.findall(r'[\d.]*\d', tot_text)))
said = re.findall(r'\b(should|recommend\w*|avoid|worth|better|prefer\w*|target|take more|skip)\b',
                  tot_text, re.I)
eq('the totals describe and recommend nothing', said, [])
ok_('the CSV stays one row per order, with no totals in it',
    run(['--journal', J5, '--gps', GPS5, '--day', '2026-03-05', '--csv'])[1].count('\n') == 3)
_out3 = run(['--journal', JOURNAL, '--gps', GPSDIR, '--day', '2026-03-03'])[1]
ok_("the first evening's report prints its totals too, with its gap",
    'Shift totals' in _out3 and '18:14-18:18' in _out3)
ok_('a day with logs but no fix on it says so',
    'Shift totals: no usable GPS fix on this day'
    in run(['--journal', J5, '--gps', GPS5, '--day', '2026-03-07'])[1])

# --- the offers page's ✓ that put the order in the car (19 Oct 2026) ------------
#
# server.js offersTickHolds: a ✓ there on a recent card is a Took, and its mark
# row says `inCar: true`. One without it is a label, as before.
_ot = {o['id']: o for o in SR.orders([
    offer('P', at(18, 0), 11.0, 30, 4.0), offer('Q', at(18, 5), 8.0, 20, 3.0),
    dict(mark('P', at(18, 2), True, via='offers'), inCar=True),
    mark('Q', at(18, 30), True, via='offers'),
    drop('P', at(18, 40))])}
eq('[offers tick] a ✓ on the offers page that held the order is its Took, and ends at Drop',
   (_ot['P']['took'], _ot['P']['how'], _ot['P']['end']), (at(18, 2), 'Drop', at(18, 40)))
eq('[offers tick] ...one that only recorded is still no Took', _ot['Q']['how'], 'no Took')
_ot2 = {o['id']: o for o in SR.orders([
    offer('R', at(18, 0), 11.0, 30, 4.0),
    dict(mark('R', at(18, 2), True, via='review'), inCar=True)])}
eq('[offers tick] ...and `inCar` on a mark from anywhere but the offers page is no Took',
   _ot2['R']['how'], 'no Took')

# --- how each order's end was pinned (21 Oct 2026) ----------------------------
#
# server.js pinOutcome: every drop row says, in words, how the order's end was
# pinned for the GPS drop or why not, and how many of its pickups were pinned.
# The rate is the orders pinned at all over the orders whose row says.
def pinned_drop(oid, when, by, end, pickups, **kw):
    return dict(drop(oid, when, by=by, **kw), end=end, pickups=pickups)


_pj = os.path.join(work, 'pin.jsonl')
with open(_pj, 'w') as fh:
    for r in [
        offer('P1', at(18, 0), 11.0, 30, 4.0), mark('P1', at(18, 1), True),
        pinned_drop('P1', at(18, 30), 'gps', {'by': 'server', 'why': None, 'asked': 'door'},
                    {'pinned': 1, 'why': None}),
        offer('P2', at(18, 40), 8.0, 20, 3.0), mark('P2', at(18, 41), True),
        pinned_drop('P2', at(19, 0), None,
                    {'by': None, 'why': 'no house number', 'asked': 'door'},
                    {'pinned': 0, 'why': 'no house number'}),
        offer('P3', at(19, 10), 9.0, 25, 5.0), mark('P3', at(19, 11), True),
        pinned_drop('P3', at(19, 20), 'replaced',
                    {'by': 'place', 'why': 'door next to the pickup', 'asked': 'door'},
                    {'pinned': 1, 'why': None}),
        offer('P4', at(19, 30), 7.0, 20, 3.0), mark('P4', at(19, 31), True),
        drop('P4', at(19, 50)),
        offer('P5', at(20, 0), 7.0, 20, 3.0), mark('P5', at(20, 1), True),
        pinned_drop('P5', at(20, 20), None,
                    {'by': 'x' * 80, 'why': None, 'asked': None}, 'not a dict'),
    ]:
        fh.write(json.dumps(r) + '\n')
_prep = SR.report(_pj, None, '2026-03-03')
_pby = {o['id']: o['pin'] for o in _prep['orders']}
eq('[pinning] a drop row\'s end and pickups are read off it, as words',
   _pby['P1'], {'by': 'server', 'why': None, 'asked': 'door', 'pickups': 1,
                'pickupsWhy': None})
eq('[pinning] ...an end not pinned keeps its reason', (_pby['P2']['by'], _pby['P2']['why']),
   (None, 'no house number'))
eq('[pinning] ...a replaced order\'s row says too', _pby['P3']['by'], 'place')
eq('[pinning] ...a row from before the field says nothing', _pby['P4'], None)
eq('[pinning] ...a newer build\'s long word is cut, and pickups not a dict are unknown',
   (len(_pby['P5']['by']), _pby['P5']['pickups']), (SR.WORD_MAX, None))
eq('[pinning] the rate: ends pinned over the orders whose row says',
   SR.pinning(_prep['orders']), {'recorded': 4, 'pinned': 3, 'unrecorded': 1})
_ptext = SR.text(_prep)
_psec = _ptext[_ptext.index('Pinning'):_ptext.index('Over the ')]
ok_('[pinning] the text prints a Pinning section, one line per order (%r)' % _psec,
    '#1 end pinned by server (asked: door); pickups 1 pinned' in _psec
    and '#2 end not pinned: no house number (asked: door); pickups 0 pinned: no house number'
    in _psec
    and '#3 end pinned by place, not armed: door next to the pickup' in _psec
    and '#4 no record' in _psec)
ok_('[pinning] ...and the shift\'s pinned rate',
    'Pinned: 3 of 4 orders with a record (75%); 1 without one' in _psec)
eq('[pinning] a shift with no order prints no Pinning section',
   'Pinning' in SR.text(SR.report(_pj, None, '2026-03-05')), False)

# --- restaurant waits (22 Oct 2026) -------------------------------------------
#
# By store, over the day's orders whose pickup the GPS visited once: how many
# and the median of their restaurant minutes. Names only. The evening's A is
# the one: 'Imaginary Bistro (1 Nowhere Ln)', 6.5 min before its GPS visit.
_wtext = SR.text(rep)
_wsec = _wtext[_wtext.index('Restaurant waits'):_wtext.index('Pinning')]
ok_('[waits] the text prints a Restaurant waits section: A\'s store, one visit, its minutes '
    '(%r)' % _wsec, re.search(r'\n  Imaginary Bistro  1 visit  median 6\.[4-6] min\n', _wsec))
eq('[waits] the store is the card\'s pickup less its bracketed street; a door, a corner and '
   'no text are no store; the planner\'s icon letters go',
   [SR.store_name(t) for t in ('Imaginary Bistro (1 Nowhere Ln)', 'Larkspur Tacos (113 Quil',
                               '1981 Cobb Pkwy NW, Kennesaw', 'Elm St & Oak Ave, Faketown',
                               None, '', 'oe Larkspur Tacos')],
   ['Imaginary Bistro', 'Larkspur Tacos', None, None, None, None, 'Larkspur Tacos'])


def _wo(store, minutes, by=('gps',)):
    return {'store': store, 'restaurantMinutes': minutes, 'visitsBy': list(by)}


_wr = SR.waits([_wo('Larkspur Tacos', 4.0), _wo('LARKSPUR TACOS', 2.0),
                _wo('Larkspur Tacos', 9.0), _wo('Wren Street Noodles', 3.5),
                _wo('Wren Street Noodles', None),
                _wo('Example Grill', 5.0, by=('planner',)),
                _wo('Example Grill', 5.0, by=('gps', 'gps')), _wo(None, 6.0)])
eq('[waits] one store however its name is cased, by name, with its visits and median; '
   'an order with no minutes is no visit',
   [(g['store'], g['visits'], g['median']) for g in _wr['stores']],
   [('Larkspur Tacos', 3, 4.0), ('Wren Street Noodles', 1, 3.5)])
eq('[waits] ...a planner\'s visit, two visits and no name are not put to a store, and counted',
   _wr['uncounted'], 3)
_wnone = SR.text(dict(rep, orders=[dict(by['D'])]))
ok_('[waits] a shift with nothing measured says so',
    'Restaurant waits' in _wnone and '  none measured\n' in _wnone)

# --- a Drop taken back by ↶ Undo (22 Oct 2026) ---------------------------------
#
# server.js /api/drop-undo writes {kind: 'undo', undoes: 'drop', id, dropAt,
# holdId}: the drop row with that id and `at` did not happen, and the order's
# end is its next drop row.
def undo(oid, when, drop_at):
    return {'v': 1, 'kind': 'undo', 'at': when, 'id': oid, 'seq': when, 'undoes': 'drop',
            'dropAt': drop_at, 'holdId': '%s@%d' % (oid, drop_at - 1)}


_ur = [offer('U1', at(18, 0), 11.0, 30, 4.0), mark('U1', at(18, 1), True),
       drop('U1', at(18, 10)), undo('U1', at(18, 10, 4), at(18, 10)),
       drop('U1', at(18, 35), by='gps'),
       offer('U2', at(19, 0), 8.0, 20, 3.0), mark('U2', at(19, 1), True),
       drop('U2', at(19, 10), by='chooser', carried=2), undo('U2', at(19, 10, 3), at(19, 10)),
       offer('U3', at(20, 0), 8.0, 20, 3.0), mark('U3', at(20, 1), True),
       drop('U3', at(20, 10)), undo('U3', at(20, 10, 3), at(20, 9)),
       offer('U4', at(21, 0), 8.0, 20, 3.0), mark('U4', at(21, 1), True),
       drop('U4', at(21, 10)), dict(undo('U4', at(21, 10, 3), at(21, 10)), undoes='mark')]
_uo = {o['id']: o for o in SR.orders(_ur)}
eq('[undo] a Drop taken back did not happen: the order ends at its next drop row',
   (_uo['U1']['how'], _uo['U1']['end'], _uo['U1']['actualMinutes']), ('GPS drop', at(18, 35), 34.0))
eq('[undo] ...and one taken back with no later row has no end on record, unreliable',
   (_uo['U2']['how'], _uo['U2']['end'], _uo['U2']['reliable'], _uo['U2']['carried']),
   ('no end', None, False, None))
eq('[undo] ...an undo row names its drop by id AND the drop\'s own time: another time is '
   'not that drop', (_uo['U3']['how'], _uo['U3']['end']), ('Drop', at(20, 10)))
eq('[undo] ...and an undo of anything but a drop takes no drop back',
   (_uo['U4']['how'], _uo['U4']['end']), ('Drop', at(21, 10)))

# --- put down with another, and too soon (the 26 Oct shift's #8) ------------------
#
# One chooser press puts two orders down at the same `at`. An order put down so
# within TOGETHER_S of another's end, in under TOO_SOON of its card's minutes,
# is not timed; one carried the whole way beside the other (an add-on) is.
# Times and figures shaped like the 26 Oct evening; every row invented.
_tj = os.path.join(work, 'together.jsonl')
with open(_tj, 'w') as fh:
    for r in [
        # #1 and #2: an order and its add-on ("+10 min"), one press at 19:40:43.
        offer('W1', at(19, 8, 50), 17.0, 36, 11.9), mark('W1', at(19, 8, 59), True),
        offer('W2', at(19, 13, 30), 8.5, 10, 0.4), mark('W2', at(19, 13, 41), True),
        drop('W1', at(19, 40, 43), by='chooser', carried=2),
        drop('W2', at(19, 40, 43), by='chooser', carried=2),
        # #3 and #4: an order 46 min in, and one taken 113 s before the press.
        offer('T1', at(20, 37, 50), 15.0, 29, 9.3), mark('T1', at(20, 38, 2), True),
        offer('T2', at(21, 22, 20), 13.0, 20, 6.6), mark('T2', at(21, 22, 28), True),
        drop('T1', at(21, 24, 21), by='chooser', carried=2),
        drop('T2', at(21, 24, 21), by='chooser', carried=2),
        # #5: a Drop two minutes after its Took with nothing else put down.
        offer('T5', at(21, 59, 50), 9.0, 20, 4.0), mark('T5', at(22, 0), True),
        drop('T5', at(22, 2)),
        # #6 and #7: two Drops 61 s apart, the second three minutes in.
        offer('T6', at(22, 29, 50), 12.0, 30, 6.0), mark('T6', at(22, 30), True),
        offer('T7', at(23, 7, 50), 9.0, 20, 4.0), mark('T7', at(23, 8), True),
        drop('T6', at(23, 10)), drop('T7', at(23, 11, 1)),
        # #8 and #9: a GPS drop a minute in, beside a Drop: the GPS saw it leave.
        offer('T8', at(23, 19, 50), 12.0, 30, 6.0), mark('T8', at(23, 20), True),
        offer('T9', at(23, 49, 50), 9.0, 20, 4.0), mark('T9', at(23, 50), True),
        drop('T8', at(23, 51)), drop('T9', at(23, 51, 10), by='gps'),
        # #10 and #11: one replaced by the next Took, which is Dropped 30 s
        # later: a Took is no press that put anything down.
        offer('R1', at(1, 59, 50, day=4), 12.0, 30, 6.0), mark('R1', at(2, 0, day=4), True),
        offer('R2', at(2, 4, 50, day=4), 9.0, 20, 4.0), mark('R2', at(2, 5, day=4), True),
        drop('R1', at(2, 5, day=4), by='replaced'), drop('R2', at(2, 5, 30, day=4)),
    ]:
        fh.write(json.dumps(r) + '\n')
_trep = SR.report(_tj, None, '2026-03-03')
_tby = {o['id']: o for o in _trep['orders']}
eq('[together] (the premise: the orders in Took order)',
   [o['id'] for o in _trep['orders']],
   ['W1', 'W2', 'T1', 'T2', 'T5', 'T6', 'T7', 'T8', 'T9', 'R1', 'R2'])
eq('[together] an order put down in the same press as another, 1.9 min into a 20 min card, '
   'is unreliable: no $/hr, no door minutes',
   (_tby['T2']['reliable'], _tby['T2']['perHour'], _tby['T2']['doorMinutes']),
   (False, None, None))
eq('[together] ...and its row names the other order by number and says how soon',
   [n for n in _tby['T2']['notes'] if 'put down with' in n],
   ["unreliable: put down with #3 within 113 s of its Took; 1.9 min against the card's 20 "
    "is that order's Drop, not this one's delivery"])
eq('[together] ...while the order whose press it was stays reliable',
   (_tby['T1']['reliable'], round(_tby['T1']['actualMinutes'], 1)), (True, 46.3))
eq('[together] an add-on put down with its order, 27 min against "+10", is carried, not '
   'too soon: both reliable', (_tby['W1']['reliable'], _tby['W2']['reliable'],
                               round(_tby['W2']['actualMinutes'], 1)), (True, True, 27.0))
eq('[together] a quick Drop with nothing else put down names no other order...',
   [n for n in _tby['T5']['notes'] if 'put down with' in n], [])
eq('[too soon] ...but is unreliable on its own (the 28 Oct shift): a press 2 min into a '
   '20 min card is not the door, and its row says so',
   (_tby['T5']['reliable'], _tby['T5']['perHour'],
    [n for n in _tby['T5']['notes'] if n.startswith('unreliable')]),
   (False, None, ["unreliable: put down by a press (Drop) 2.0 min after its Took, under 0.3 of "
                  "the card's 20 min; a press at the pickup or on the way, not a delivery"]))
eq('[together] two Drops 61 s apart are not put down together; the second, three minutes '
   'into 20, is too soon on its own',
   (_tby['T6']['reliable'], _tby['T7']['reliable'],
    [n for n in _tby['T6']['notes'] + _tby['T7']['notes'] if 'put down with' in n]),
   (True, False, []))
eq('[together] ...nor a GPS drop beside a Drop: the GPS saw it leave the door, and no '
   'minutes test holds a GPS drop', (_tby['T8']['reliable'], _tby['T9']['reliable']), (True, True))
eq('[together] ...nor a Drop 30 s after another order was replaced by its Took, which is '
   'too soon on its own', (_tby['R1']['how'], _tby['R2']['reliable'],
                           [n for n in _tby['R2']['notes'] if 'put down with' in n]),
   ('replaced', False, []))
eq('[together] the summary leaves them out', _trep['summary']['reliable'], 6)
ok_('[together] ...and the text prints the reason under the table',
    "#4 unreliable: put down with #3 within 113 s of its Took" in SR.text(_trep))

# --- pressed too soon, and never driven (the 28 Oct shift) ------------------------
#
# Four orders Dropped at or past the pickup read "reliable" at $105-$165/hr.
# A press under TOO_SOON of the card's minutes is not the door; and by any end,
# GPS miles under SHORT_MILES of the card's, over a log with no gap and a fix
# at both ends, are an order not driven. On the invented track above: parked
# 18:27-18:47, a gap 18:15-18:18, 5 m/s east from 18:47 (3,000 m by 18:57),
# and nothing after 19:20. Every row invented.
_sj = os.path.join(work, 'short.jsonl')
_addon_mark = dict(mark('S6', at(18, 28), True), addon=True)
with open(_sj, 'w') as fh:
    for r in [
        # S1: a GPS drop 19 min into a 20 min card, the car parked throughout.
        offer('S1', at(18, 27, 20), 9.0, 20, 5.0), mark('S1', at(18, 27, 30), True),
        drop('S1', at(18, 46, 30), by='gps'),
        # S2: a Drop 18 min into 20 (its minutes pass), 4 mi on the card, parked.
        offer('S2', at(18, 27, 50), 9.0, 20, 4.0), mark('S2', at(18, 28), True),
        drop('S2', at(18, 46)),
        # S3: 14 min of 25 across the 18:15 gap, 20 mi on the card: 5.2 mi read
        # with the gap bridged, which is the least it drove, not the most.
        offer('S3', at(18, 11, 50), 9.0, 25, 20.0), mark('S3', at(18, 12), True),
        drop('S3', at(18, 26)),
        # S4 and S5: 18:47 to 18:57, 1.86 mi driven, GPS drops: 5.0 on the
        # card is 0.37 of it, 5.6 is 0.33.
        offer('S4', at(18, 46, 50), 9.0, 10, 5.0), mark('S4', at(18, 47), True),
        drop('S4', at(18, 57), by='gps'),
        offer('S5', at(18, 46, 50), 9.0, 10, 5.6), mark('S5', at(18, 47), True),
        drop('S5', at(18, 57), by='gps'),
        # S6: an add-on ("+10 min", "+4 mi") Dropped 2 min in, parked: neither
        # test is read for what an add-on's card only adds.
        offer('S6', at(18, 27, 50), 6.0, 10, 4.0), _addon_mark,
        drop('S6', at(18, 30)),
        # S7: a GPS drop at 18:05, Took at 17:52, before the log's first fix
        # after its frozen ten seconds (17:58): 1.9 mi logged of 10 on the
        # card, and 6 min not logged.
        offer('S7', at(17, 51, 50), 9.0, 13, 10.0), mark('S7', at(17, 52), True),
        drop('S7', at(18, 5), by='gps'),
    ]:
        fh.write(json.dumps(r) + '\n')
_srep2 = SR.report(_sj, GPSDIR, '2026-03-03')
_sby = {o['id']: o for o in _srep2['orders']}
eq('[never driven] a GPS drop with the car parked from Took to end, 0 of 5 mi, is unreliable: '
   'no $/hr, no door minutes', (_sby['S1']['reliable'], _sby['S1']['perHour'],
                                _sby['S1']['doorMinutes']), (False, None, None))
eq('[never driven] ...and its row says the miles against the card\'s',
   [n for n in _sby['S1']['notes'] if n.startswith('unreliable')],
   ["unreliable: the GPS log, unbroken from Took to end, has the car drive 0.0 mi against "
    "the card's 5, under 0.35 of it; put down before it was driven, so its minutes are not "
    "a delivery's"])
eq('[never driven] a Drop whose minutes pass (18 of 20) is held to the miles as well',
   (_sby['S2']['reliable'], any('has the car drive 0.0 mi' in n for n in _sby['S2']['notes'])),
   (False, True))
eq('[never driven] miles read across a gap prove nothing: 5.2 of 20 with the 18:15 gap '
   'bridged stays reliable', (_sby['S3']['reliable'], round(_sby['S3']['gpsMiles'], 1)),
   (True, 5.2))
eq("[never driven] ...nor a log that ends before the order does (the evening's D: 1.9 of "
   "12 mi, its last 20 min unlogged)", (by['D']['reliable'], round(by['D']['gpsMiles'], 1)),
   (True, 1.9))
eq("[never driven] ...nor one that begins after the order's Took (1.9 of 10, its first 6 "
   "min unlogged)", (_sby['S7']['reliable'], round(_sby['S7']['gpsMiles'], 1)), (True, 1.9))
eq('[never driven] the line: 1.86 mi driven is reliable against 5.0 (0.37) and not against '
   '5.6 (0.33)', (_sby['S4']['reliable'], _sby['S5']['reliable']), (True, False))
eq('[too soon] [never driven] an add-on pressed down 2 min into "+10", parked, is held to '
   'neither', (_sby['S6']['addon'], _sby['S6']['reliable']), (True, True))

# --- as JSON, for the phone's shift page (22 Oct 2026) ---------------------------
code_js, out_js = run(['--journal', JOURNAL, '--gps', GPSDIR, '--day', '2026-03-03', '--json'])
eq('[json] the CLI exits 0 with --json', code_js, 0)
_js = json.loads(out_js)
eq('[json] one object: the day, the GPS, the totals, the orders, the pinning, the summary',
   sorted(_js), ['day', 'end', 'gps', 'orders', 'pinning', 'start', 'summary', 'totals',
                 'unreadable'])
eq('[json] the orders as the text has them, by number and with no id',
   [(o['n'], o['how'], o['reliable']) for o in _js['orders']],
   [(i + 1, o['how'], o['reliable']) for i, o in enumerate(rep['orders'])])
ok_('[json] ...no offer id on any order', all('id' not in o for o in _js['orders']))
eq('[json] card against actual on each order, as the report measures it',
   [(o['pay'], o['cardMinutes'], o['actualMinutes']) for o in _js['orders'][:2]],
   [(12.0, 30, 30.0), (9.0, 20, 25.0)])
eq('[json] the totals in epoch ms and seconds: rig on and off, as the text prints them',
   (_js['totals']['on'], _js['totals']['off']),
   (rep['totals']['on'] * 1000.0, rep['totals']['off'] * 1000.0))
eq('[json] ...left and back, miles, moving and stopped',
   (_js['totals']['left'] and _js['totals']['left']['at'], round(_js['totals']['miles'], 6),
    _js['totals']['moving'], _js['totals']['stopped']),
   (rep['totals']['left'] and rep['totals']['left']['at'] * 1000.0,
    round(rep['totals']['miles'], 6), rep['totals']['moving'], rep['totals']['stopped']))
eq('[json] each order\'s pinning in the text\'s own words, and the rate',
   ([o['pin'] for o in _js['orders']][:1], _js['pinning']),
   ([SR.pin_text(rep['orders'][0]['pin'])],
    dict(SR.pinning(rep['orders']), rate=None)))
_jsp = json.loads(run(['--journal', _pj, '--day', '2026-03-03', '--json'])[1])
eq('[json] ...with a record, the rate as the text rounds it', _jsp['pinning'],
   {'recorded': 4, 'pinned': 3, 'unrecorded': 1, 'rate': 75})
eq('[json] no GPS log: no totals, and it says the log is missing',
   (lambda j: (j['totals'], j['gps']['missing']))(
       json.loads(run(['--journal', JOURNAL, '--gps', gone, '--day', '2026-03-03',
                       '--json'])[1])), (None, True))
_bare = [w for w in ('Nowhere', 'Example Ave', 'Faketown', 'Bistro') if w in out_js]
eq('[json] no address or coordinate in the JSON: no place', _bare, [])
eq('[json] ...and no coordinate (every number in it is a time, a length or a count)',
   re.findall(r'12\.34|45\.67|11\.34|44\.67', out_js), [])

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
# ...but one page SHOWS it (22 Oct 2026): shift.html, through server.js's GET
# /api/shift, which runs this file with --json and passes the answer through.
# Those two and no other; and in server.js the name stays inside the one
# section that runs it, so nothing there keeps or weighs what it says.
# ...and the places report (tools/places_report.js, the owner's of 25 Oct),
# which runs on the NucBox and never on the rig: it borrows this file's GPS
# gate (load_fixes) to read the logs the rig wrote, and nothing of the
# report's own figures. It and its suite are named here so a second reader
# on the rig still fails this check.
readers = [r for r in readers if r not in ('tools/places_report.js', 'tests/placesreport.test.js')]
eq('nothing on the rig reads the report (the rating, the target, advice.js, the panel); '
   'only the shift page shows it, through the server',
   readers, ['server.js', 'shift.html'])
with open(os.path.join(ROOT, 'server.js'), encoding='utf-8') as fh:
    _srv = fh.read()
_sec = re.search(r'/\* -{6,} the shift, on the phone.*?/\* -{6,} the shift ends', _srv, re.S)
eq('...and server.js names it only inside the section that runs it for /api/shift',
   (_srv.count('shift_report'), _sec and _sec.group(0).count('shift_report') or 0),
   (_srv.count('shift_report'),) * 2)
ok_('...a section there is (%r)' % bool(_sec), _sec and 'shift_report' in _sec.group(0))

# --- an Uber add-on's card minutes are an increment (the owner's 26 Oct) --------
#
# Order #5 of 26 Oct was a "+10 min" add-on onto #4, delivered with it 27
# minutes after its Took: 2.7 x "its card" in the by-card-minutes medians,
# though the card's 10 minutes were only what it added. Invented: X a 30 min
# card, Y its "+10 min" add-on (the Took's mark says `addon`, as server.js
# asAddOnRow writes it), each put down by its own Drop.
_aoj = os.path.join(work, 'addon.jsonl')
with open(_aoj, 'w') as fh:
    for r in [offer('X', at(18, 0), 12.0, 30, 6.0), mark('X', at(18, 0, 10), True),
              offer('Y', at(18, 9, 50), 8.5, 10, 0.4),
              dict(mark('Y', at(18, 10), True), addon=True, addonTo='X@1'),
              drop('X', at(18, 35)), dict(drop('Y', at(18, 50)), addon=True, addonTo='X@1')]:
        fh.write(json.dumps(r) + '\n')
_aorep = SR.report(_aoj, None, '2026-03-03')
_ao = _aorep['orders']
_aob = {o['id']: o for o in _ao}
eq('[add-on] the Took\'s mark makes the order an add-on; the order it joined is not',
   (_aob['Y']['addon'], _aob['X']['addon'], _aob['Y']['reliable']), (True, False, True))
eq('[add-on] ...its card minutes and miles print as the increment',
   SR.cells(_aob['Y'])[2:4], ('+10', '+0.4'))
_aos = SR.summary(_ao)
eq('[add-on] ...it counts in its app\'s n and $/hr, and in no actual/card ratio: the median is '
   'the base order\'s alone (34.8/30), not 40/10 beside it',
   [(g['group'], g['n'], round(g['ratio'], 3)) for g in _aos['byApp']],
   [('uber', 2, round(_aob['X']['actualMinutes'] / 30.0, 3))])
eq('[add-on] ...and in no card-minutes band', [(g['group'], g['n']) for g in _aos['byBand']],
   [(SR._band(30), 1)])
eq('[add-on] ...and the summary says how many it left out', _aos['addOns'], 1)
_aot = SR.text(_aorep)
ok_('[add-on] ...in the text, by its note and by the summary\'s line',
    'an add-on: its card minutes and miles are what it added' in _aot
    and '1 add-on counted by app, and left out of every actual/card minutes ratio' in _aot)
ok_('[add-on] ...and the JSON says it per order',
    [o['addon'] for o in SR.as_json(_aorep)['orders']] == [False, True])
# ...and the card's own `addon` says it too, with no mark saying so.
eq('[add-on] ...or the card\'s own `addon`',
   SR.orders([dict(offer('Z', at(18, 0), 8.0, 10, 0.4), addon=True),
              mark('Z', at(18, 0, 10), True)])[0]['addon'], True)

# --- a step of the Pi's clock inside one log (the owner's 26 Oct) ---------------
#
# The 26 Oct `_1415` log: 136 fixes stamped 923 s early, then the stamps step
# forward as NTP answers, the TPVs' own `time` running on through it. Those
# fixes are moved onto the clock the log ends on; a gpsd stall (both clocks
# move alike), a receiver's own small offset (21 s, under CLOCK_STEP_S) and a
# step with no GPS time before it move nothing. Invented track.
def _steplog(name, rows):
    d = os.path.join(work, name)
    os.mkdir(d)
    with open(os.path.join(d, '2026-03-03_1800.jsonl'), 'w') as fh:
        for stamp, body in rows:
            fh.write(stamped(stamp, body))
    return d


_g0 = at(18, 0) / 1000.0
_good = [(_g0 + i, tpv(_g0 + i, LAT0, lon_at(10.0 * i), 5.0, 10.0)) for i in range(60)]
_stepped = [((g - 923 if i < 30 else g), b) for i, (g, b) in enumerate(_good)]
eq('[clock step] measured against the TPVs\' own time: one step of +923 s, at the line '
   'the stamps jumped',
   SR.clock_steps([(t, SR._gps_seconds(b)) for t, b in _stepped]), [(30, 923.0)])
_fx, _fi = SR.load_fixes(_steplog('step-fwd', _stepped))
eq('[clock step] ...and every fix before it re-stamped onto the clock after it, said so',
   ([round(f[0] - _g0) for f in _fx] == list(range(60)), _fi['clockSteps'], _fi['restamped']),
   (True, 1, 30))
_back = [((g + 600 if i < 30 else g), b) for i, (g, b) in enumerate(_good)]
_fx, _fi = SR.load_fixes(_steplog('step-back', _back))
eq('[clock step] ...a step backwards, the same',
   ([round(f[0] - _g0) for f in _fx] == list(range(60)), _fi['clockSteps']), (True, 1))
_stall = [(g + (300 if i >= 30 else 0), tpv(g + (300 if i >= 30 else 0), LAT0, lon_at(10.0 * i),
                                            5.0, 10.0)) for i, (g, b) in enumerate(_good)]
_small = [((g - 21 if i < 30 else g), b) for i, (g, b) in enumerate(_good)]
_dark = [(_g0 - 3285 + i, '{"class":"SKY","satellites":[]}') for i in range(10)] + _good
eq('[clock step] ...not a gap in the log (gpsd stalled: both clocks moved), not a receiver\'s '
   '21 s, not a step with no GPS time on its far side',
   [SR.load_fixes(_steplog(n, rows))[1]['clockSteps']
    for n, rows in (('stall', _stall), ('small', _small), ('dark', _dark))], [0, 0, 0])
_srep = dict(rep, info=dict(rep['info'], clockSteps=1, restamped=30))
ok_('[clock step] ...and the text\'s GPS line says it',
    "the Pi's clock stepped 1 time inside a log, and 30 positions before a step were "
    "re-stamped by the GPS's own time" in SR.text(_srep))
eq('[clock step] ...as the JSON does',
   [SR.as_json(_srep)['gps'][k] for k in ('clockSteps', 'restamped')], [1, 30])

# ...and a log named by tools/gpslog_name.py (the GPS's own minute) is read
# back as beginning at that minute; one it marked `-unsynced` as saying no
# date, so every day's report reads it.
import gpslog_name as GN                                      # noqa: E402
_nt = at(17, 38) / 1000.0
eq('[log name] gpslog_name\'s name is read back as its minute; its unsynced one as no date',
   (SR._log_began(GN.name_for(_nt) + '.jsonl')[0] / 1000.0,
    SR._log_began(GN.name_for(_nt, synced=False) + '.jsonl')), (_nt, None))

shutil.rmtree(work)
print('FAILED: %d of %d' % (bad, ok + bad) if bad
      else '\nAll %d shift report checks passed' % ok)
sys.exit(1 if bad else 0)
