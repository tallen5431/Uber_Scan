"""What tools/twin_ids.py says about one card filed under two ids.

    python3 tools/test_twin_ids.py

Every row here is invented: made-up streets in a made-up town, payouts and
times chosen so the answer is known before it runs. The output is meant to be
pasted into a conversation, so the last checks hold that it carries no place,
no payout, no id and no time of day.
"""

import io
import json
import os
import sys
import tempfile
import contextlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import twin_ids as TW                                         # noqa: E402

ok = bad = 0


def eq(name, got, want):
    global ok, bad
    if got == want:
        ok += 1
    else:
        bad += 1
        print('FAIL %s: got %r, want %r' % (name, got, want))


T0 = 1790000000000          # an invented moment; only differences matter
SHOP = '12 Quillfeather Lane'
DOOR = '880 Marrowbend Court'
OTHER = '41 Tansy Row'


def row(i, seq, at, first, pay, minutes, miles, places=(SHOP, DOOR), app='uber', **kw):
    r = {'v': 1, 'id': i, 'seq': seq, 'at': T0 + at * 1000, 'firstAt': T0 + first * 1000,
         'pay': pay, 'minutes': minutes, 'miles': miles, 'places': list(places), 'app': app}
    r.update(kw)
    return r


def rows_for(*rows):
    return [json.dumps(r) for r in rows]


def found(*rows):
    return TW.twins(*TW.readings_by_id(rows_for(*rows)))


# A misread payout opens a second id, and the card's right payout comes back
# under it: the case report_check's breakdown points at.
f = found(row('A', 1, 0, 0, 12.50, 20, 8.1), row('A', 2, 8, 0, 12.50, 20, 8.1),
          row('B', 1, 30, 30, 12.58, 20, 8.1), row('B', 2, 36, 30, 12.50, 20, 8.1))
eq('a misread payout: one pair', len(f['pairs']), 1)
p = f['pairs'][0]
eq('...counted by the payout, a small change', p['why'], 'payout, 25 cents or less')
eq('...8 cents up', p['payCents'], 8)
eq('...the gap from the first id\'s last reading', p['gapS'], 22.0)
eq('...the second id came back to the first\'s figures', p['backLater'], True)
eq('...readings counted', (p['readingsA'], p['readingsB']), (2, 2))

# The decimal point lost: $1250 for $12.50. Not believable, and still the
# payout that split the ids.
f = found(row('A', 1, 0, 0, 12.50, 20, 8.1), row('B', 1, 10, 10, 1250.0, 20, 8.1))
eq('a lost decimal point', f['pairs'][0]['why'], 'payout, a decimal point')
eq('...not believable', f['pairs'][0]['bBelievable'], False)

# Same payout, a minute more.
f = found(row('A', 1, 0, 0, 9.75, 14, 4.0), row('B', 1, 20, 20, 9.75, 15, 4.0))
eq('the minutes', f['pairs'][0]['why'], 'minutes')
eq('...one minute', f['pairs'][0]['minutes'], 1)

# Same payout and minutes, the miles read differently.
f = found(row('A', 1, 0, 0, 9.75, 14, 4.0), row('B', 1, 20, 20, 9.75, 14, 4.9))
eq('the miles', f['pairs'][0]['why'], 'miles')
eq('...0.9 mi', f['pairs'][0]['miles'], 0.9)

# No miles on the second: _returning never matches a reading without them.
f = found(row('A', 1, 0, 0, 9.75, 14, 4.0), row('B', 1, 20, 20, 9.75, 14, None))
eq('no miles', f['pairs'][0]['why'], 'no miles on the second')

# Everything identical: something before _returning made the second id.
f = found(row('A', 1, 0, 0, 9.75, 14, 4.0), row('B', 1, 20, 20, 9.75, 14, 4.0))
eq('identical', f['pairs'][0]['why'], 'identical')

# Not a twin: another app, another door, too far apart, no places at all.
eq('another app is not a twin', found(row('A', 1, 0, 0, 9.75, 14, 4.0),
                                      row('B', 1, 20, 20, 9.75, 14, 4.0, app='doordash'))['pairs'], [])
eq('another door is not a twin', found(row('A', 1, 0, 0, 9.75, 14, 4.0),
                                       row('B', 1, 20, 20, 9.75, 14, 4.0, places=(SHOP, OTHER)))['pairs'], [])
far = found(row('A', 1, 0, 0, 9.75, 14, 4.0), row('B', 1, 200, 200, 9.75, 14, 4.0))
eq('three minutes apart is not a twin', far['pairs'], [])
eq('...nor close', far['closePairs'], 0)
eq('no places is not a twin', found(row('A', 1, 0, 0, 9.75, 14, 4.0, places=()),
                                    row('B', 1, 20, 20, 9.75, 14, 4.0, places=()))['pairs'], [])
# The shop alone on one side agrees with shop and door on the other, as
# _places_agree has it.
eq('the shop alone agrees', len(found(row('A', 1, 0, 0, 9.75, 14, 4.0),
                                      row('B', 1, 20, 20, 9.75, 15, 4.0, places=(SHOP,)))['pairs']), 1)

# Rows that are not readings are skipped, and a broken line too.
by_id, order = TW.readings_by_id(rows_for(
    {'kind': 'pair', 'at': T0}, {'kind': 'mark', 'id': 'A', 'at': T0, 'accepted': True},
    row('A', 1, 0, 0, 9.75, 14, 4.0)) + ['{not json', ''])
eq('only readings are read', (order, len(by_id['A'])), (['A'], 1))

# The summary counts by reason, most first.
f = found(row('A', 1, 0, 0, 12.50, 20, 8.1), row('B', 1, 30, 30, 12.58, 20, 8.1),
          row('B', 2, 36, 30, 12.50, 20, 8.1),
          row('C', 1, 300, 300, 7.00, 11, 3.0), row('D', 1, 320, 320, 7.10, 11, 3.0),
          row('E', 1, 600, 600, 5.00, 9, 2.0), row('F', 1, 620, 620, 5.00, 10, 2.0))
s = TW.summary(f)
eq('summary: three pairs', s['twinPairs'], 3)
eq('summary: by reason, most first', list(s['why'].items()),
   [('payout, 25 cents or less', 2), ('minutes', 1)])
eq('summary: one came back', s['secondIdCameBackToTheFirstsFigures'], 1)
eq('summary: the median gap', s['gapMedianS'], 20.0)

# The printed output, run as the owner would: no place, payout, id or time.
with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, 'journal.jsonl')
    with open(path, 'w') as fh:
        fh.write('\n'.join(rows_for(
            row('1790000000000-1250', 1, 0, 0, 12.50, 20, 8.1),
            row('1790000030000-1258', 1, 30, 30, 12.58, 20, 8.1),
            row('1790000030000-1258', 2, 36, 30, 12.50, 20, 8.1))) + '\n')
    for flags in ([], ['--pairs', '5'], ['--json', '--pairs', '5']):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = TW.main([path] + flags)
        text = out.getvalue()
        eq('runs %s' % (flags or 'plain'), code, 0)
        eq('%s: says the reason' % (flags or 'plain'), 'payout, 25 cents or less' in text, True)
        leaked = [w for w in ('Quillfeather', 'Marrowbend', '12.5', '12.58', '1250',
                              '1790000', 'uber') if w in text]
        eq('%s: no place, payout, id, time or app printed' % (flags or 'plain'), leaked, [])
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        eq('a missing journal says so', TW.main([os.path.join(d, 'none.jsonl')]), 1)

print('%d passed, %d failed' % (ok, bad))
if bad:
    print('FAILED')
sys.exit(1 if bad else 0)
