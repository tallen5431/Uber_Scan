#!/usr/bin/env python3
"""Replay a real week's frames through both parser ports, and say what moved.

    python3 tools/replay_week.py week.csv --out before.json
    ... change the parser ...
    python3 tools/replay_week.py week.csv --out after.json --diff before.json

The suite holds the parser to a corpus of a few hundred cleaned texts. A week
of driving is five and a half thousand frames nobody cleaned, and the corpus
cannot say what a change to the reader does to them. The card-boundary rules
are where that bites: the week this was written, widening one guard by one
word produced a $750/hr row with every suite green. So a parser change is
replayed over a whole week before it ships, and every row whose pay, minutes,
miles, pickup, dropoff, verdict, rate, wholeness or doubt moves is printed with
both readings. See FIELDS.

WHAT IS REPLAYED, per row of the export (numbered from 1, the way a spreadsheet
and every AUDITS.md entry number them):

    py.merged   every frame, in order, through rpi/offer_parser.parse, the real
                OfferAccumulator and rate() — what the rig publishes
    py.panel    the same merge after each frame in turn — what the panel shows
                while that frame is the latest read (scan_pi.py rates
                accumulator.add()'s return, not the frame)
    py.frames   each frame alone through parse() and rate() — what one read
                says before the merge has a say
    js.frames   each frame alone through offer-parser.js, the same way
    py.text / js.text   the row's stored `text` column, which is the one frame
                the journal kept beside the merged reading

The browser port has no accumulator, so it is held to the frames and the text;
the two ports are held to each other on every one of them, and any frame the
two ports read differently is printed too.

THE FRAMES ARE READ WITH json.loads, NEVER BY SPLITTING ON "|". The `scans`
column is a JSON array. It replaced a " | "-joined string because that
separator split 19% of the rows mid-frame (server.js records it), and on the
real week 5,881 pipe characters sit INSIDE frame texts — OCR reads a card's
border as one. A replay that split on the pipe would be replaying frames the
camera never took.

THE TEXT IS DECODED WITH json.loads TOO. server.js writes `text` through
JSON.stringify so that one offer is one line of the file, which makes the cell
a JSON string: quoted, with every line break written as a backslash and an n.
This tool handed the cell over as it stood, so the `text` readings were of one
run-on line full of literal "\\n"s — a frame the reader never returned. On the
real week every one of the 1,166 cells carries them, and 1,073 read differently
from the decoded text: places on all 1,073, pickup on 965, dropoff on 472, and
pay, verdict and rate on one. Both ports were fed the same wrong string, so
they agreed with each other throughout and nothing said so.

Rates are taken with each row's own target, band and costPerMile, so a verdict
is judged against the line the driver had set that night, not today's.
"""

import argparse
import csv
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'rpi'))

import offer_parser as OP                     # noqa: E402
from accumulate import OfferAccumulator       # noqa: E402

csv.field_size_limit(1 << 30)

# What a row is compared on. The first six are the ones a driver acts on; the
# places are there because the card boundary's other fault is a merchant or a
# destination blanked with nothing saying so, which moves no number at all.
#
# `whole`, the rate's `doubt` and `untimedMiles` are there because they decide
# what happens to a reading without moving its number. `whole` is the flag the
# voice waits for (scan_pi.py speaks only a locked, whole reading), the panel
# settles on (live.html prints ", still reading." until it is true), and the
# journal records — a row stored whole=0 is set aside by the offers page. This
# tuple left all three out while summary() computed `whole` for every reading,
# so the diff of the change that fixed rows 450 and 908 printed their numbers
# and was blind to both going whole -> not whole on every frame: offers that
# would never be spoken again, reported as "no published state moved".
# untimedMiles is the figure live.html prints in "a leg this reading could not
# time"; the doubt is which of the rate's refusals fired.
#
# `deliverBy` because it is the denominator of every card that states a time
# of delivery instead of a duration, and it moves no other field here: rate()
# is run without the clock, so a frame that gains a deadline stays `empty` and
# only this column can say the reader now sees one. Widening the deadline rule
# to Uber's "Est. delivery" card was replayed blind to it until it was added.
FIELDS = ('pay', 'minutes', 'miles', 'deliverBy', 'pickup', 'dropoff', 'state',
          'perHour', 'places', 'whole', 'doubt', 'untimedMiles')

# A second apart, which is well inside the accumulator's window and about the
# pace the rig reads at. The merge keys on silence, not on the clock, so any
# spacing under WINDOW gives the same answer.
FRAME_SECONDS = 1.8


def settings_of(row):
    def num(key, default):
        try:
            return float(row.get(key) or default)
        except ValueError:
            return default
    return {'target': num('target', 25), 'band': num('band', 15),
            'costPerMile': num('costPerMile', 0.3)}


def summary(parsed, rate):
    per_hour = rate.get('perHour') if rate.get('ready') else None
    return {
        'pay': parsed.get('pay'),
        'minutes': parsed.get('minutes'),
        'miles': parsed.get('miles'),
        'deliverBy': parsed.get('deliverBy'),
        'pickup': parsed.get('pickup'),
        'dropoff': parsed.get('dropoff'),
        'places': list(parsed.get('places') or []),
        'state': rate.get('state'),
        # Unrounded: Python's round() and JavaScript's Math.round() part on a
        # half cent, and that is not a disagreement between the parsers.
        'perHour': per_hour,
        'whole': OP.is_whole(parsed) if parsed.get('pay') else None,
        'doubt': rate.get('doubt'),
        'untimedMiles': parsed.get('untimedMiles'),
    }


def read_rows(path):
    with open(path, newline='') as fh:
        rows = list(csv.DictReader(fh))
    out = []
    for n, row in enumerate(rows, 1):
        raw = row.get('scans') or ''
        frames = json.loads(raw) if raw.strip() else []
        if not isinstance(frames, list):
            raise SystemExit('row %d: scans is not a JSON array' % n)
        raw = row.get('text') or ''
        text = json.loads(raw) if raw else ''
        if not isinstance(text, str):
            raise SystemExit('row %d: text is not a JSON string' % n)
        out.append({'row': n, 'at': row.get('at'), 'frames': frames,
                    'text': text, 'settings': settings_of(row)})
    return out


def replay_python(rows):
    out = {}
    for r in rows:
        settings = r['settings']
        acc = OfferAccumulator()
        merged = None
        frames = []
        panel = []
        for i, frame in enumerate(r['frames']):
            parsed = OP.parse(frame)
            frames.append(summary(parsed, OP.rate(parsed, settings)))
            merged = acc.add(parsed, now=1000.0 + i * FRAME_SECONDS)
            panel.append(summary(merged, OP.rate(merged, settings)))
        text = OP.parse(r['text'])
        out[r['row']] = {
            'at': r['at'],
            'merged': summary(merged, OP.rate(merged, settings)) if merged else None,
            'panel': panel,
            'frames': frames,
            'text': summary(text, OP.rate(text, settings)),
        }
    return out


def replay_js(rows):
    feed = [{'row': r['row'], 'frames': r['frames'], 'text': r['text'],
             'settings': r['settings']} for r in rows]
    got = subprocess.run(['node', os.path.join(HERE, 'replay_week.js')],
                         input=json.dumps(feed), capture_output=True, text=True,
                         check=True)
    return {int(k): v for k, v in json.loads(got.stdout).items()}


def same(a, b):
    if isinstance(a, float) or isinstance(b, float):
        if a is None or b is None:
            return a is b
        return abs(a - b) < 0.005
    return a == b


def changed(a, b, fields=FIELDS):
    if a is None or b is None:
        return [] if a is b else ['reading']
    return [f for f in fields if not same(a.get(f), b.get(f))]


def show(tag, a, b, fields):
    def one(s):
        if s is None:
            return 'nothing'
        return ', '.join('%s=%r' % (f, s.get(f)) for f in fields)
    print('    %-10s before  %s' % (tag, one(a)))
    print('    %-10s after   %s' % ('', one(b)))


def diff(old, new):
    moved = 0
    for n in sorted(new['py'], key=int):
        k = str(n)
        lines = []
        for port in ('py', 'js'):
            a, b = old[port].get(k), new[port].get(k)
            if port == 'py':
                f = changed(a['merged'], b['merged'])
                if f:
                    lines.append(('py.merged', a['merged'], b['merged'], f))
                for i, (pa, pb) in enumerate(zip(a.get('panel', []),
                                                 b.get('panel', []))):
                    f = changed(pa, pb)
                    if f:
                        lines.append(('py.panel%d' % i, pa, pb, f))
            f = changed(a['text'], b['text'])
            if f:
                lines.append(('%s.text' % port, a['text'], b['text'], f))
            for i, (fa, fb) in enumerate(zip(a['frames'], b['frames'])):
                f = changed(fa, fb)
                if f:
                    lines.append(('%s.f%d' % (port, i), fa, fb, f))
        if lines:
            moved += 1
            print('row %s (at=%s)' % (k, new['py'][k]['at']))
            for tag, a, b, f in lines:
                show(tag, a, b, f)
    return moved


def ports_disagree(snap):
    """Every frame and text the two ports read differently. Printed, not
    fixed here — a disagreement is the corpus's business."""
    out = []
    for k, py in snap['py'].items():
        js = snap['js'][k]
        pairs = [('text', py['text'], js['text'])]
        pairs += [('f%d' % i, a, b) for i, (a, b)
                  in enumerate(zip(py['frames'], js['frames']))]
        for tag, a, b in pairs:
            f = changed(a, b, FIELDS)
            if f:
                out.append((k, tag, a, b, f))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('csv', help='a week exported from /api/journal.csv')
    ap.add_argument('--out', help='write this replay here, to diff against later')
    ap.add_argument('--diff', help='an earlier --out to compare this replay with')
    args = ap.parse_args(argv)

    rows = read_rows(args.csv)
    snap = {'py': {str(k): v for k, v in replay_python(rows).items()},
            'js': {str(k): v for k, v in replay_js(rows).items()}}
    frames = sum(len(r['frames']) for r in rows)
    pipes = sum(f.count('|') for r in rows for f in r['frames'])
    print('%d rows, %d frames, %d pipe characters inside frames'
          % (len(rows), frames, pipes))

    split = ports_disagree(snap)
    print('%d frame/text readings where the two ports disagree' % len(split))
    for k, tag, a, b, f in split:
        print('  row %s %s: %s' % (k, tag, ', '.join(
            '%s py=%r js=%r' % (x, a.get(x), b.get(x)) for x in f)))

    if args.out:
        with open(args.out, 'w') as fh:
            json.dump(snap, fh)
    if args.diff:
        with open(args.diff) as fh:
            old = json.load(fh)
        moved = diff(old, snap)
        print('%d of %d rows moved' % (moved, len(rows)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
