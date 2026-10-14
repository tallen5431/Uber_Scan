#!/usr/bin/env python3
"""What each order taken on a shift really took, beside what its card said.

    python3 tools/shift_report.py --journal rpi/journal.jsonl --gps ~/gpslog --day 2026-10-12
    python3 tools/shift_report.py --journal rpi/journal.jsonl --gps ~/gpslog --day 2026-10-12 --csv

One row per order taken: its app and card pay, the card's minutes and miles,
when Took was pressed, when and how the order ended, the minutes that really
passed, the miles the GPS log says the car drove in between, the minutes
stopped at the restaurant and at the door, whether another order was in the
car at the same time, and the card's pay over the minutes that really passed.
Then a short table by app and by the card's minutes: the median of actual over
card minutes, and the median actual $/hr. It describes; it recommends nothing.

A REPORT, AND NOTHING READS IT. Nothing on the rig imports this file or its
output: not the live rating, not the target, not advice.js, not the panel.
tools/test_shift_report.py holds that by name. AUDITS.md's Settled entry on
re-timing an offer ends "The honest route to the driver's actual question
needs elapsed times, not a model of them", and this is those elapsed times,
measured, after the shift. Turning them into a rule — a pace, a floor, a
per-app line — is what Settled refuses, and this file does not take the step.

NO COST, AND NO $/MILE. The GPS miles are a measurement printed beside the
card's own miles. Nothing here multiplies them by anything: a car-cost ledger
is refused in Settled, and pay over miles is the $/mile rule refused there too.
Nothing here works minutes out of miles either; every minute printed is a
clock reading subtracted from another.

NO ADDRESS AND NO COORDINATE IN THE OUTPUT. The journal's offer rows carry the
card's text, pickup and dropoff, and the GPS log is nothing but positions. The
report prints none of them — the app is read off the card's text by
offer_parser.screen_type, the same function the scanner names it with, and the
text goes no further. Positions are used for distances and stops and are
never printed, in the text or the CSV.

WHAT COUNTS AS AN ORDER, read off the journal's marks the way server.js's
latestPerOfferUncached folds them: the newest mark wins, by its `at`, and an
offer whose newest answer is `true` was taken; a `null` or a `false` after it
takes it back. Its Took is the panel press that put it in the car (`via:
'panel'`, or no `via` from a page older than the field): the first `true`
after the last answer that was not one. A `true` from the
offers page or the end-of-shift review labels the card and puts nothing in the
car, so an order marked only there has no Took and no times, and says so.

HOW AN ORDER ENDED is its first drop row at or after the Took: a press of Drop
(the row has no `by`), `gps` (the server saw the car leave the pinned door),
`chooser` (Drop with two in the car, the driver picking which), or `replaced`
(a later Took put it down — its time is the next Took, not a delivery). The
server writes NO row when an order outlives its own clock (holding() just
stops counting it; see /api/delivered's comment), so an order with no drop row
has no end on record: it expired, or the server lost the hold. Both
`replaced` and no-row are UNRELIABLE, marked on the row, and left out of the
summary: a replaced order's minutes are the gap to the next Took, and an
expired one's would be the card's own minutes x 1.5 + 10, which is the card
again, not a measurement.

THE GPS LOG is `gpspipe -w -uu` output in one directory, `.jsonl` or the
`.jsonl.gz` tools/gpslog_tidy.py leaves. `-uu` stamps every line with the
Pi's clock, the same clock the server stamps the journal with, which is what
lets a fix be put beside a Took. Every TPV goes through gps.parse_line and
gps.Phone.take, the path the live rig uses, with a clock reading the line's own
stamp, and only fixes gps.usable() passes are used. A line stamped before the
Pi's clock was set (sync.CLOCK_BELIEVABLE_AFTER) cannot be placed beside
anything and is counted, not used.
"""

import argparse
import bisect
import collections
import csv
import functools
import gzip
import io
import json
import os
import re
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'rpi'))
import gps as G                                               # noqa: E402
import offer_parser as OP                                     # noqa: E402
import sync                                                   # noqa: E402

# Below this a -uu stamp is a Pi that had not heard from NTP yet, in seconds.
CLOCK_FLOOR = sync.CLOCK_BELIEVABLE_AFTER / 1000.0

# A silence between two usable fixes longer than this is a GAP: the miles
# across it are a straight line from the fix before to the fix after, which is
# the shortest the car can have driven, and the row says how many gaps and how
# long. 60 s, as asked by the owner. The receiver sends about once a second.
GAP_S = 60.0

# How far a fix must be from the last one counted before the step between them
# is added to the miles. A parked receiver wanders inside its own error, and
# summing that wander a second at a time is miles the car never drove.
# Measured on the 12 Oct shift's 14 logs (30,304 fixes the gate passed):
# counted every step, the whole log reads 250.1 mi, and 5.65 mi of that is
# inside the 58 stops stops() finds in it (4.67 hours parked). Those stops
# still gather 2.96 mi at 10 m, 2.26 at 20 m, 1.57 at 30 m, and none at 50 m,
# since a stop is a run inside STOP_M. The whole log reads 244.1 mi at 50 m:
# 6.0 mi fewer than every step, against 5.65 mi of stop wander, so this costs
# the real driving about 0.35 mi in 244 (corners cut between fixes, and wander
# at a light too short to be a stop; the two cannot be told apart here). And
# it is the gate's own figure: a move no larger than an error the gate passes
# is not a move it can vouch for.
JITTER_M = G.FIX_ERR_MAX

# A STOP is a run of usable fixes all within STOP_M of the run's first, lasting
# at least STOP_MIN_S. STOP_M is gps.FIX_ERR_MAX: a parked receiver is allowed
# to wander as far as an error the gate already passes. STOP_MIN_S is the
# server's own dwell before it calls a car arrived at a door (DWELL_MS, 60 s);
# the value is the same, the rule is this file's.
STOP_M = G.FIX_ERR_MAX
STOP_MIN_S = 60.0

# How long before the visit row, or the end, a stop may have ended and still
# be the stop at that place. A GPS drop and a GPS visit are written on LEAVING
# (300 m on two fixes, server.js's LEAVE_M), and a press of Drop can come as
# the car pulls away. Chosen, not measured.
NEAR_S = 120.0

# The bands the summary groups card minutes into. Chosen, not fitted to
# anything: the point is to see whether the long cards and the short ones
# keep their word differently, not where a line falls.
BANDS = ((0, 20), (20, 30), (30, 45), (45, None))

# The ends that are a delivery, and the word each is printed as.
HOW = {None: 'Drop', 'gps': 'GPS drop', 'chooser': 'chooser'}

_STAMP = re.compile(r'^(?:\d{4}-\d\d-\d\d \d\d:\d\d:\d\d )?(\d+(?:\.\d+)?): (\{.*)$')


@functools.lru_cache(maxsize=None)
def day_starts_at():
    """The driver's day boundary, read out of advice.js where it is written.

    Read, not copied: rpi/test_lint.py exists to stop a second copy of this
    number drifting from the first, and a Python one would be a third."""
    with open(os.path.join(ROOT, 'advice.js'), encoding='utf-8') as fh:
        m = re.search(r'\bvar\s+DAY_STARTS_AT\s*=\s*([0-9]+)\s*;', fh.read())
    if not m:
        raise SystemExit('shift_report: advice.js no longer says DAY_STARTS_AT')
    return int(m.group(1))


def day_window(day):
    """[start, end) of the driver's day `day` ('YYYY-MM-DD'), in ms, local."""
    y, mo, d = (int(x) for x in day.split('-'))
    h = day_starts_at()
    start = time.mktime((y, mo, d, h, 0, 0, 0, 0, -1))
    end = time.mktime((y, mo, d + 1, h, 0, 0, 0, 0, -1))
    return start * 1000.0, end * 1000.0


# --- the journal ----------------------------------------------------------

def read_journal(path):
    """(rows, unreadable): every line that is a JSON object, and a count of
    those that are not, which the report prints."""
    rows, bad = [], 0
    with open(path, 'rb') as fh:
        for raw in fh:
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except ValueError:
                bad += 1
                continue
            if isinstance(row, dict):
                rows.append(row)
            else:
                bad += 1
    return rows, bad


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else None


def orders(rows):
    """Every order taken in the journal, as dicts, ordered by Took (an order
    with no Took last). See the module docstring for the rules."""
    marks = collections.defaultdict(list)
    drops = collections.defaultdict(list)
    visits = collections.defaultdict(list)
    readings = collections.defaultdict(list)
    for r in rows:
        kind = r.get('kind')
        if kind == 'mark' and r.get('id') and 'accepted' in r:
            marks[r['id']].append(r)
        elif kind == 'drop' and r.get('id') and _num(r.get('at')) is not None:
            drops[r['id']].append(r)
        elif kind == 'visit' and isinstance(r.get('holdId'), str) \
                and _num(r.get('at')) is not None:
            visits[r['holdId'].split('@')[0]].append(r)
        elif kind is None and r.get('id'):
            readings[r['id']].append(r)
    out = []
    for oid, ms in marks.items():
        ms = sorted(ms, key=lambda m: _num(m.get('at')) or 0)
        final, took = None, None
        for m in ms:
            final = m['accepted']
            # Whether a `false` is a pass or a take-back (server.js tells them
            # apart by `via`) does not matter here: either way the order is
            # out of the car, and either way it was not taken.
            if final is True:
                if took is None and m.get('via') in (None, 'panel'):
                    took = _num(m.get('at'))
            else:
                took = None
        if final is not True:
            continue
        out.append(_order(oid, took, readings.get(oid, []),
                          drops.get(oid, []), visits.get(oid, [])))
    out.sort(key=lambda o: (o['took'] is None, o['took'] or 0))
    _alongside(out)
    return out


def _order(oid, took, readings, drops, visits):
    o = {'id': oid, 'took': took, 'end': None, 'how': None, 'reliable': False,
         'carried': None, 'visits': [], 'notes': []}
    # The card as it stood when Took was pressed: the last reading of it
    # written at or before the press. Not the server's vote over every reading
    # (bestReading), which may have been made after the press and is a
    # different question.
    readings = sorted(readings, key=lambda r: _num(r.get('at')) or 0)
    card = None
    for r in readings:
        if took is None or (_num(r.get('at')) or 0) <= took:
            card = r
    card = card or (readings[0] if readings else {})
    o['app'] = OP.screen_type(card.get('text') or '')['app'] if card.get('text') else None
    o['pay'] = _num(card.get('pay'))
    o['cardMinutes'] = _num(card.get('minutes'))
    o['cardMiles'] = _num(card.get('miles'))
    o['billedMinutes'] = _num(card.get('billedMinutes'))
    if took is None:
        o['how'] = 'no Took'
        o['notes'].append('marked taken on the offers page; never pressed in the car, so not timed')
        return o
    after = sorted((d for d in drops if d['at'] >= took), key=lambda d: d['at'])
    if after:
        d = after[0]
        o['end'] = d['at']
        o['carried'] = _num(d.get('carried'))
        if d.get('by') in HOW:
            o['how'] = HOW[d.get('by')]
            o['reliable'] = True
        elif d.get('by') == 'replaced':
            o['how'] = 'replaced'
            o['notes'].append('unreliable: put down by the next Took, so its end is that Took, not a delivery')
        else:
            # A newer build's word, printed short: it is a server field, never
            # a place, and no row can make this line run on.
            o['how'] = 'drop by %s' % str(d.get('by'))[:16]
            o['notes'].append('unreliable: a drop row this report does not know')
    else:
        o['how'] = 'no end'
        o['notes'].append('unreliable: no drop row; it expired on its own clock, or the server lost it')
    o['visits'] = sorted(v['at'] for v in visits
                         if v['at'] >= took and (o['end'] is None or v['at'] <= o['end']))
    o['actualMinutes'] = (o['end'] - took) / 60000.0 if o['end'] is not None else None
    return o


@functools.lru_cache(maxsize=None)
def _server_number(pattern):
    with open(os.path.join(ROOT, 'server.js'), encoding='utf-8') as fh:
        m = re.search(pattern, fh.read(), re.M)
    if not m:
        raise SystemExit('shift_report: server.js no longer says %s' % pattern)
    return m


def hold_span(minutes):
    """The longest the server would have counted an order of `minutes` as in
    the car, in ms: holdEnds' own HOLD_OVERRUN and HOLD_GRACE_MS, read out of
    server.js rather than copied (the default grace: an HOLD_GRACE_MS set in
    the rig's environment is not knowable from here)."""
    over = float(_server_number(r'^var HOLD_OVERRUN = ([0-9.]+);').group(1))
    g = _server_number(r'^if \(!isFinite\(HOLD_GRACE_MS\).*= ([0-9]+) \* ([0-9]+);$')
    return minutes * over * 60000 + int(g.group(1)) * int(g.group(2))


def _alongside(out):
    """'yes', 'no' or '?' on each order: was another order in the car with it.

    Yes when its drop row says two were carried, or when its Took-to-end
    overlaps another's. An order with no end on record has only a bound: the
    server stops counting it at holdEnds (hold_span from the Took, which is no
    earlier than the card's own time the server counts from, so the bound
    errs long), or with no card minutes, at the end of its driver's day. An
    overlap inside a bound is '?', never 'yes' — it may have gone sooner.
    No Took at all is '?'."""
    for o in out:
        if o['took'] is None:
            o['last'] = None
        elif o['end'] is not None:
            o['last'] = o['end']
        else:
            minutes = _num(o.get('billedMinutes')) or o['cardMinutes']
            if minutes:
                o['last'] = o['took'] + hold_span(minutes)
            else:
                d = time.localtime(o['took'] / 1000.0 - day_starts_at() * 3600)
                o['last'] = day_window(time.strftime('%Y-%m-%d', d))[1]
    for o in out:
        if o['took'] is None:
            o['alongside'] = '?'
            continue
        if o['carried'] is not None and o['carried'] >= 2:
            o['alongside'] = 'yes'
            continue
        said = 'no'
        for p in out:
            if p is o or p['took'] is None:
                continue
            if o['took'] < p['last'] and p['took'] < o['last']:
                if o['end'] is not None and p['end'] is not None:
                    said = 'yes'
                    break
                said = '?'
        o['alongside'] = said


# --- the GPS log ------------------------------------------------------------

def _open(path):
    if path.endswith('.gz'):
        return io.TextIOWrapper(gzip.open(path, 'rb'), encoding='utf-8', errors='replace')
    return open(path, encoding='utf-8', errors='replace')


def load_fixes(directory):
    """(fixes, info). `fixes` is [(t, lat, lon)] for every fix gps.usable()
    passed, sorted by t (seconds, the Pi's clock), or None when there is no
    log at all. `info` counts what was read and what was refused, and why."""
    info = {'files': 0, 'positions': 0, 'passed': 0, 'refused': collections.Counter(),
            'unstamped': 0, 'beforeClock': 0}
    if not directory or not os.path.isdir(directory):
        return None, info
    names = sorted(n for n in os.listdir(directory)
                   if n.endswith('.jsonl') or n.endswith('.jsonl.gz'))
    fixes = []
    for name in names:
        info['files'] += 1
        now = [0.0]
        # One Phone per file: one gpspipe run is one stream, and the hold
        # bookkeeping (`heldFor`) is about consecutive fixes of one stream.
        phone = G.Phone('gpspipe-log', clock=lambda: now[0])
        with _open(os.path.join(directory, name)) as fh:
            for line in fh:
                m = _STAMP.match(line.strip())
                if not m:
                    if line.lstrip().startswith('{'):
                        info['unstamped'] += 1
                    continue
                got = G.parse_line(m.group(2))
                if got is None:
                    continue
                t = float(m.group(1))
                if t < CLOCK_FLOOR:
                    info['beforeClock'] += 1
                    continue
                info['positions'] += 1
                now[0] = t
                phone.take(got)
                fix = phone.latest()
                if fix['ok']:
                    info['passed'] += 1
                    fixes.append((t, fix['lat'], fix['lon']))
                else:
                    info['refused'][fix['why']] += 1
    fixes.sort()
    return fixes, info


def _between(fixes, t0, t1):
    ts = [f[0] for f in fixes]
    return fixes[bisect.bisect_left(ts, t0):bisect.bisect_right(ts, t1)]


def _apart(a, b):
    return G.metres_apart(a[1], a[2], b[1], b[2])


def track(fixes, t0, t1):
    """The GPS miles between t0 and t1 (seconds), and what to say about them:
    {'miles', 'gaps', 'gapSeconds', 'head', 'tail'} — `miles` None with no
    usable fix in the span. `head`/`tail` are the seconds at either end with
    no fix at all, which no miles cover."""
    inside = _between(fixes, t0, t1)
    out = {'miles': None, 'gaps': 0, 'gapSeconds': 0.0, 'head': None, 'tail': None}
    if not inside:
        return out
    out['head'] = inside[0][0] - t0
    out['tail'] = t1 - inside[-1][0]
    metres = 0.0
    anchor = prev = inside[0]
    for f in inside[1:]:
        if f[0] - prev[0] > GAP_S:
            out['gaps'] += 1
            out['gapSeconds'] += f[0] - prev[0]
        d = _apart(anchor, f)
        if d >= JITTER_M:
            metres += d
            anchor = f
        prev = f
    out['miles'] = metres / 1609.344
    return out


def stops(fixes):
    """[(start, end)] seconds, each a run of fixes within STOP_M of its first
    lasting at least STOP_MIN_S."""
    out, i, n = [], 0, len(fixes)
    while i < n:
        j = i
        while j + 1 < n and _apart(fixes[i], fixes[j + 1]) <= STOP_M:
            j += 1
        if fixes[j][0] - fixes[i][0] >= STOP_MIN_S:
            out.append((fixes[i][0], fixes[j][0]))
        i = j + 1
    return out


def dwell(fixes, lo, event):
    """Minutes stopped at the place `event` (seconds) marks leaving, or None:
    the last stop after `lo` that had begun by `event` and ended no more than
    NEAR_S before it, counted up to `event` at the latest."""
    best = None
    for s, e in stops(_between(fixes, lo, event + NEAR_S)):
        if s <= event and e >= event - NEAR_S:
            best = (s, min(e, event))
    return None if best is None else (best[1] - best[0]) / 60.0


def measure(o, fixes):
    """Put the GPS figures on one order, in place."""
    o['gpsMiles'] = o['restaurantMinutes'] = o['doorMinutes'] = None
    if o['took'] is None or o['end'] is None:
        return
    if fixes is None:
        o['notes'].append('no GPS log; miles blank')
        return
    t0, t1 = o['took'] / 1000.0, o['end'] / 1000.0
    tr = track(fixes, t0, t1)
    if tr['miles'] is None:
        o['notes'].append('no usable GPS fix between Took and end; miles blank')
        return
    o['gpsMiles'] = tr['miles']
    if tr['gaps']:
        o['notes'].append('%d GPS gap%s over %d s bridged in a straight line (%.1f min)'
                          % (tr['gaps'], '' if tr['gaps'] == 1 else 's', GAP_S,
                             tr['gapSeconds'] / 60.0))
    for edge, word in (('head', 'first'), ('tail', 'last')):
        if tr[edge] > GAP_S:
            o['notes'].append('no GPS fix for the %s %.1f min; not in the miles'
                              % (word, tr[edge] / 60.0))
    visits = [v / 1000.0 for v in o['visits']]
    if visits:
        got = [dwell(fixes, t0, v) for v in visits]
        if any(g is not None for g in got):
            o['restaurantMinutes'] = sum(g for g in got if g is not None)
    if o['reliable']:
        o['doorMinutes'] = dwell(fixes, visits[-1] if visits else t0, t1)


# --- the report -------------------------------------------------------------

def report(journal, gps_dir, day):
    """Everything the CLI prints, as data: {'orders', 'summary', 'info'}."""
    rows, bad = read_journal(journal)
    start, end = day_window(day)
    every = orders(rows)
    fixes, info = load_fixes(gps_dir)
    mine = []
    for o in every:
        when = o['took']
        if when is None:
            continue
        if start <= when < end:
            mine.append(o)
    # Orders marked taken with no Took are placed by their card's own time.
    for o in every:
        if o['took'] is None:
            at = None
            for r in rows:
                if r.get('kind') is None and r.get('id') == o['id'] and _num(r.get('at')):
                    at = r['at']
                    break
            if at is not None and start <= at < end:
                mine.append(o)
    for o in mine:
        measure(o, fixes)
        # Only over a delivery. A replaced order's minutes run to the next
        # Took, and its pay over them would be a rate nobody earned.
        o['perHour'] = (o['pay'] / (o['actualMinutes'] / 60.0)
                        if o['reliable'] and o['pay'] is not None and o.get('actualMinutes')
                        else None)
    info['unreadable'] = bad
    info['gpsMissing'] = fixes is None
    return {'orders': mine, 'summary': summary(mine), 'info': info,
            'day': day, 'start': start, 'end': end}


def _band(m):
    if m is None:
        return 'no card minutes'
    for lo, hi in BANDS:
        if m >= lo and (hi is None or m < hi):
            return '%d+ min' % lo if hi is None else '%d-%d min' % (lo, hi)
    return 'no card minutes'


def summary(rows):
    """By app and by card-minutes band, over the reliable rows: n, the median
    of actual over card minutes, and the median actual $/hr."""
    good = [o for o in rows if o['reliable'] and o.get('actualMinutes')]
    out = {'reliable': len(good), 'of': len(rows), 'byApp': [], 'byBand': []}
    for key, name in (('byApp', lambda o: o['app'] or 'unknown'),
                      ('byBand', lambda o: _band(o['cardMinutes']))):
        groups = collections.OrderedDict()
        for o in good:
            groups.setdefault(name(o), []).append(o)
        order = [_band(lo) for lo, _ in BANDS] + ['no card minutes'] if key == 'byBand' \
            else sorted(groups)
        for label in order:
            if label not in groups:
                continue
            os_ = groups[label]
            ratio = [o['actualMinutes'] / o['cardMinutes'] for o in os_ if o['cardMinutes']]
            rate = [o['perHour'] for o in os_ if o['perHour'] is not None]
            out[key].append({'group': label, 'n': len(os_),
                             'ratio': statistics.median(ratio) if ratio else None,
                             'perHour': statistics.median(rate) if rate else None})
    return out


def _clock(ms):
    return '' if ms is None else time.strftime('%H:%M', time.localtime(ms / 1000.0))


def _f(v, fmt):
    return '' if v is None else fmt % v


COLUMNS = ('app', 'card pay', 'card min', 'card mi', 'took', 'ended', 'how',
           'actual min', 'GPS mi', 'restaurant min', 'door min', 'with another',
           'actual $/hr', 'reliable')


def cells(o):
    return (o['app'] or '?', _f(o['pay'], '$%.2f'), _f(o['cardMinutes'], '%g'),
            _f(o['cardMiles'], '%g'), _clock(o['took']), _clock(o['end']), o['how'],
            _f(o.get('actualMinutes'), '%.1f'), _f(o.get('gpsMiles'), '%.1f'),
            _f(o.get('restaurantMinutes'), '%.1f'), _f(o.get('doorMinutes'), '%.1f'),
            o['alongside'], _f(o.get('perHour'), '$%.2f'), 'yes' if o['reliable'] else 'NO')


def text(rep):
    out = []
    info = rep['info']
    out.append('Shift of %s, %s to %s: %d order%s taken'
               % (rep['day'], time.strftime('%a %H:%M', time.localtime(rep['start'] / 1000)),
                  time.strftime('%a %H:%M', time.localtime(rep['end'] / 1000)),
                  len(rep['orders']), '' if len(rep['orders']) == 1 else 's'))
    if info['gpsMissing']:
        out.append('GPS: no log found; every GPS column is blank')
    else:
        refused = ', '.join('%s %d' % kv for kv in sorted(info['refused'].items()))
        out.append('GPS: %d log%s, %d positions, %d passed the gate%s%s'
                   % (info['files'], '' if info['files'] == 1 else 's', info['positions'],
                      info['passed'], ' (refused: %s)' % refused if refused else '',
                      ''.join('; not used: %d %s' % (info[k], w) for k, w in
                              (('unstamped', 'with no -uu stamp'),
                               ('beforeClock', 'stamped before the clock was set'))
                              if info[k])))
    if info['unreadable']:
        out.append('Journal: %d unreadable line%s skipped'
                   % (info['unreadable'], '' if info['unreadable'] == 1 else 's'))
    out.append('')
    table = [('#',) + COLUMNS] + [(str(i + 1),) + cells(o) for i, o in enumerate(rep['orders'])]
    widths = [max(len(r[c]) for r in table) for c in range(len(table[0]))]
    for r in table:
        out.append('  '.join(c.ljust(w) for c, w in zip(r, widths)).rstrip())
    notes = [(i + 1, n) for i, o in enumerate(rep['orders']) for n in o['notes']]
    if notes:
        out.append('')
        out.extend('  #%d %s' % n for n in notes)
    s = rep['summary']
    out.append('')
    out.append('Over the %d reliable order%s of %d (an order replaced or with no end is left out):'
               % (s['reliable'], '' if s['reliable'] == 1 else 's', s['of']))
    for key, title in (('byApp', 'by app'), ('byBand', 'by card minutes')):
        out.append('  %s' % title)
        if not s[key]:
            out.append('    nothing to summarise')
        for g in s[key]:
            out.append('    %-16s n=%-3d median actual/card minutes %-6s median actual $/hr %s'
                       % (g['group'], g['n'], _f(g['ratio'], '%.2f'),
                          _f(g['perHour'], '$%.2f')))
    return '\n'.join(out) + '\n'


CSV_COLUMNS = ('id', 'app', 'card_pay', 'card_minutes', 'card_miles', 'took', 'ended',
               'how', 'actual_minutes', 'gps_miles', 'restaurant_minutes', 'door_minutes',
               'with_another', 'actual_per_hour', 'reliable', 'notes')


def to_csv(rep):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator='\n')
    w.writerow(CSV_COLUMNS)
    stamp = lambda ms: '' if ms is None else time.strftime(          # noqa: E731
        '%Y-%m-%d %H:%M:%S', time.localtime(ms / 1000.0))
    for o in rep['orders']:
        w.writerow((o['id'], o['app'] or '', _f(o['pay'], '%.2f'), _f(o['cardMinutes'], '%g'),
                    _f(o['cardMiles'], '%g'), stamp(o['took']), stamp(o['end']), o['how'],
                    _f(o.get('actualMinutes'), '%.2f'), _f(o.get('gpsMiles'), '%.2f'),
                    _f(o.get('restaurantMinutes'), '%.2f'), _f(o.get('doorMinutes'), '%.2f'),
                    o['alongside'], _f(o.get('perHour'), '%.2f'),
                    'yes' if o['reliable'] else 'no', '; '.join(o['notes'])))
    return buf.getvalue()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--journal', required=True, help='the journal, e.g. rpi/journal.jsonl')
    ap.add_argument('--gps', help='the gpspipe log directory, e.g. ~/gpslog '
                                  '(missing or absent: the GPS columns are blank)')
    ap.add_argument('--day', required=True, help="the driver's day, YYYY-MM-DD "
                                                 '(it starts at advice.js\'s DAY_STARTS_AT)')
    ap.add_argument('--csv', action='store_true', help='CSV instead of text')
    args = ap.parse_args(argv)
    if not re.match(r'^\d{4}-\d\d-\d\d$', args.day):
        ap.error('--day must be YYYY-MM-DD')
    rep = report(args.journal, os.path.expanduser(args.gps) if args.gps else None, args.day)
    sys.stdout.write(to_csv(rep) if args.csv else text(rep))
    return 0


if __name__ == '__main__':
    sys.exit(main())
