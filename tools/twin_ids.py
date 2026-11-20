#!/usr/bin/env python3
"""Why one card was filed under two ids: counts only, from the journal.

    python3 tools/twin_ids.py [journal.jsonl] [--pairs N] [--json]

report_check's re-offered breakdown on the owner's copy (Nov 2026) found the
pair half of server.js markReoffered marking cards seen a median 27 s apart,
half of them the same pay and two thirds the same route: one card on the
phone, two ids in the journal, so about one offer in twenty counted twice. The
fix belongs to rpi/journal.py (OfferLog.consider, _returning), which the
reader shares, and it cannot be chosen without knowing WHICH of _returning's
tests the second id failed. This says that, and nothing else.

What it reads: every reading row (`id`, `seq`, `at`, `firstAt`, `pay`,
`minutes`, `miles`, `places`, `app`), grouped by id. Two ids are a twin pair
when the second was first seen within GAP_S of the first's last reading, they
are the same app (or one did not say), and their places agree by the
journal's own rule (_places_agree, which OP.same_place decides) with each
naming at least one. Every such pair is then held against what _returning
asks, in its order — the payout to the cent, the minutes and the miles of the
first id's last believable reading — and counted by the first test it fails.

What it prints: counts, and with --pairs one line a pair of DIFFERENCES — the
gap in seconds, the payout's change in cents, the minutes' and miles' change,
how many readings each id had, whether a later reading of the second id came
back to the first id's figures. Never a place, never a payout, never an id or
a time of day: the output is meant to be pasted into a conversation about the
code, and the privacy rule is the repository's (CLAUDE.md).

Default journal: rpi/journal.jsonl beside this checkout, the file server.js
reads (JOURNAL_PATH). Reads only.
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'rpi'))
import offer_parser as OP                                     # noqa: E402
from journal import _cents, _places_agree                     # noqa: E402

# A card is up well under a minute: the same line server.js REOFFER_GAP_MS
# draws between one card filed twice and an order that came round again.
GAP_S = 60


def readings_by_id(lines):
    """Reading rows by id, each id's rows in the file's order, and the ids in
    the order they were first seen. Pairs, marks, notes and anything
    unreadable are skipped: only an offer reading has an id and a seq."""
    by_id, order = {}, []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or row.get('kind') or not row.get('id') \
                or not isinstance(row.get('at'), (int, float)):
            continue
        if row['id'] not in by_id:
            by_id[row['id']] = []
            order.append(row['id'])
        by_id[row['id']].append(row)
    return by_id, order


def _believable(row):
    return row.get('pay') is not None and \
        OP.doubt(row.get('pay'), row.get('minutes'), row.get('miles')) is None


def _span(rows):
    first = min(r.get('firstAt', r['at']) for r in rows)
    return first, max(r['at'] for r in rows)


def _places(rows):
    out = []
    for r in rows:
        for p in r.get('places') or []:
            if isinstance(p, str):
                OP.merge_place(out, p)
    return out


def _figures(row):
    return (row.get('minutes'), row.get('miles'))


def _diff(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return round(b - a, 2)
    return None


def why_split(a_rows, b_rows):
    """The first of _returning's tests the second id's first reading fails
    against the first id's last believable one, in _returning's order, or
    'identical' when it fails none (so something before _returning decided:
    the accumulator's newCard, or the first id never reaching the recent
    list). Also the differences, for --pairs."""
    kept = [r for r in a_rows if _believable(r)]
    b0 = b_rows[0]
    out = {'readingsA': len(a_rows), 'readingsB': len(b_rows)}
    if not kept:
        out['why'] = 'first id never believable'
        return out
    a = kept[-1]
    out['payCents'] = None if a.get('pay') is None or b0.get('pay') is None \
        else int(round((b0['pay'] - a['pay']) * 100))
    out['minutes'] = _diff(a.get('minutes'), b0.get('minutes'))
    out['miles'] = _diff(a.get('miles'), b0.get('miles'))
    out['labelledA'] = bool(a.get('payLabelled'))
    out['labelledB'] = bool(b0.get('payLabelled'))
    out['bBelievable'] = _believable(b0)
    # Did the second id come back to the first's figures later? Then the
    # split was one passing reading, and every reading after it was filed
    # under the wrong id because the episode had already moved on.
    out['backLater'] = any(_cents(r.get('pay')) == _cents(a.get('pay'))
                           and _figures(r) == _figures(a) for r in b_rows[1:])
    if b0.get('miles') is None:
        out['why'] = 'no miles on the second'
    elif _cents(b0.get('pay')) != _cents(a.get('pay')):
        p, q = a.get('pay'), b0.get('pay')
        if p and q and (abs(q / p - 10) < 0.5 or abs(p / q - 10) < 0.5
                        or abs(q / p - 100) < 5 or abs(p / q - 100) < 5):
            out['why'] = 'payout, a decimal point'
        elif abs(out['payCents'] or 0) <= 25:
            out['why'] = 'payout, 25 cents or less'
        else:
            out['why'] = 'payout, more than 25 cents'
    elif b0.get('minutes') != a.get('minutes'):
        out['why'] = 'minutes'
    elif b0.get('miles') != a.get('miles'):
        out['why'] = 'miles'
    elif not _places_agree(b0.get('places') or [], _places(a_rows)):
        out['why'] = 'places, first reading'
    else:
        out['why'] = 'identical'
    return out


def twins(by_id, order, gap_s=GAP_S):
    """Consecutive ids (by first seen) that look like one card twice."""
    spans = {i: _span(by_id[i]) for i in order}
    ids = sorted(order, key=lambda i: spans[i][0])
    pairs, close = [], 0
    for prev, cur in zip(ids, ids[1:]):
        gap = (spans[cur][0] - spans[prev][1]) / 1000.0
        if gap > gap_s:
            continue
        close += 1
        a_rows, b_rows = by_id[prev], by_id[cur]
        apps = {r.get('app') for r in a_rows + b_rows if r.get('app')}
        if len(apps) > 1:
            continue
        pa, pb = _places(a_rows), _places(b_rows)
        if not pa or not pb or not _places_agree(pb, pa):
            continue
        one = why_split(a_rows, b_rows)
        one['gapS'] = round(gap, 1)
        pairs.append(one)
    return {'ids': len(order), 'closePairs': close, 'pairs': pairs}


def summary(found):
    pairs = found['pairs']
    why = {}
    for p in pairs:
        why[p['why']] = why.get(p['why'], 0) + 1
    gaps = sorted(p['gapS'] for p in pairs)
    return {
        'ids': found['ids'],
        'idsWithinAMinuteOfTheLast': found['closePairs'],
        'twinPairs': len(pairs),
        'why': dict(sorted(why.items(), key=lambda kv: -kv[1])),
        'secondIdCameBackToTheFirstsFigures': sum(1 for p in pairs if p.get('backLater')),
        'secondReadingNotBelievable': sum(1 for p in pairs if p.get('bBelievable') is False),
        'labelledFirstNotSecond': sum(1 for p in pairs if p.get('labelledA') and not p.get('labelledB')),
        'labelledSecondNotFirst': sum(1 for p in pairs if p.get('labelledB') and not p.get('labelledA')),
        'gapMedianS': gaps[(len(gaps) - 1) // 2] if gaps else None,
        'overlapping': sum(1 for p in pairs if p['gapS'] < 0),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('journal', nargs='?',
                    default=os.environ.get('JOURNAL') or os.path.join(ROOT, 'rpi', 'journal.jsonl'))
    ap.add_argument('--pairs', type=int, default=0,
                    help='also print N pairs, differences only')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args(argv)
    try:
        with open(args.journal, encoding='utf-8', errors='replace') as f:
            by_id, order = readings_by_id(f)
    except OSError as e:
        print('could not read %s: %s' % (args.journal, e.strerror), file=sys.stderr)
        return 1
    found = twins(by_id, order)
    s = summary(found)
    keys = ('gapS', 'why', 'payCents', 'minutes', 'miles', 'readingsA',
            'readingsB', 'backLater', 'bBelievable', 'labelledA', 'labelledB')
    shown = [{k: p.get(k) for k in keys} for p in found['pairs'][:args.pairs]]
    if args.json:
        print(json.dumps({'summary': s, 'pairs': shown}, indent=1))
        return 0
    print('ids %d; %d first seen within %d s of the one before; %d of those '
          'look like one card twice' % (s['ids'], s['idsWithinAMinuteOfTheLast'],
                                        GAP_S, s['twinPairs']))
    print('what the second id differed in first (journal.py _returning\'s order):')
    for k, n in s['why'].items():
        print('  %-30s %d' % (k, n))
    for k in ('secondIdCameBackToTheFirstsFigures', 'secondReadingNotBelievable',
              'labelledFirstNotSecond', 'labelledSecondNotFirst', 'gapMedianS',
              'overlapping'):
        print('%s: %s' % (k, s[k]))
    if shown:
        print('gap_s why pay_cents minutes miles readings back_later believable labelled')
        for p in shown:
            print('%s | %s | %s | %s | %s | %s/%s | %s | %s | %s/%s' % (
                p['gapS'], p['why'], p['payCents'], p['minutes'], p['miles'],
                p['readingsA'], p['readingsB'], p['backLater'], p['bBelievable'],
                p['labelledA'], p['labelledB']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
