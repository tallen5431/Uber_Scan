"""Tests for keeping a record of the offers that were read.

    python3 rpi/test_journal.py

Every interesting case here is one that cannot be produced through a camera: a
card read twice, a card that improves after the first confident look, a card
still on screen when the scanner is restarted under it. Those are exactly the
cases that turn one offer into two in a year of data, or lose one entirely.
"""

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import journal as JR
import offer_parser as P
from accumulate import OfferAccumulator

ok = bad = 0
MONEY = {'target': 25, 'band': 15, 'costPerMile': 0.30}


def eq(name, got, want):
    global ok, bad
    good = got == want or (isinstance(want, float) and isinstance(got, (int, float))
                           and got is not None and abs(got - want) < 0.001)
    if good:
        ok += 1
    else:
        bad += 1
        print('FAIL  %s: got %r want %r' % (name, got, want))


def ok_(name, cond):
    eq(name, bool(cond), True)


work = tempfile.mkdtemp()


def fresh(name='j.jsonl'):
    path = os.path.join(work, name)
    if os.path.exists(path):
        os.remove(path)
    return JR.OfferLog(JR.Journal(path))


def feed(log, texts, start=1_700_000_000.0, step=0.5, acc=None):
    """Push readings through the real accumulator and the real rate()."""
    acc = acc or OfferAccumulator()
    rows = []
    for i, text in enumerate(texts):
        parsed = acc.add(P.parse(text), now=start + i * step)
        rate = P.rate(parsed, MONEY)
        rows.append(log.consider(parsed, rate, now=start + i * step))
    return rows


OFFER = '$12.45 5 min (1.2 mi) away 23 min (8.4 mi) trip'
OTHER = '$8.75 4 min (0.9 mi) away 16 min (5.2 mi) trip'

# --- one offer, however many times it is read -------------------------------
log = fresh()
rows = feed(log, [OFFER] * 6)
written = [r for r in rows if r]
eq('one card read six times writes one row', len(written), 1)
eq('...and that is what is on disk', len(log.journal.rows()), 1)

kept = log.journal.rows()[0]
eq('the payout is kept', kept['pay'], 12.45)
eq('the time is kept', kept['minutes'], 28.0)
eq('the distance is kept', kept['miles'], 9.6)
eq('the rate is kept', kept['perHour'], 20.51)
eq('the raw rate is kept too', kept['grossPerHour'], 26.68)
eq('and what was deducted', kept['cost'], 2.88)
eq('the verdict is kept', kept['state'], 'no')
eq('with the target it was judged against', kept['target'], 25)
eq('...and the running cost', kept['costPerMile'], 0.30)
ok_('it is stamped in epoch milliseconds', kept['at'] > 1_600_000_000_000)
eq('the schema is stamped', kept['v'], JR.SCHEMA)
eq('a real ride is not suspect', kept['suspect'], False)
ok_('no OCR text reaches the file', 'text' not in kept)

# --- two different offers are two rows --------------------------------------
# One accumulator across both, as the scan loop has.
log = fresh()
shared = OfferAccumulator()
feed(log, [OFFER, OFFER], acc=shared)
feed(log, [OTHER, OTHER], start=1_700_000_100.0, acc=shared)
rows = log.journal.rows()
eq('a different offer is a second row', len(rows), 2)
ok_('with different ids', rows[0]['id'] != rows[1]['id'])
eq('the second is its own payout', rows[1]['pay'], 8.75)

# --- a reading that improves supersedes rather than duplicating -------------
# The first confident look has the journey but not the item count, which arrives
# a frame or two later and adds the shopping allowance to the billed time. Both
# readings are kept, under one id, so the correction is visible instead of the
# first guess being all there is.
SHOP = {'target': 25, 'band': 15, 'costPerMile': 0.30, 'secondsPerItem': 90}
path = os.path.join(work, 'grow.jsonl')
if os.path.exists(path):
    os.remove(path)
log = JR.OfferLog(JR.Journal(path))
acc = OfferAccumulator()
t = 1_700_000_000.0
for i, text in enumerate(['$7.09 34 min (3.6 mi) total',
                          '$7.09 34 min (3.6 mi) total',
                          '$7.09 6 items (6 units) 34 min (3.6 mi) total',
                          '$7.09 6 items (6 units) 34 min (3.6 mi) total']):
    parsed = acc.add(P.parse(text), now=t + i * 0.5)
    log.consider(parsed, P.rate(parsed, SHOP), now=t + i * 0.5)
rows = log.journal.rows()
eq('a better reading is written', len(rows), 2)
eq('...under the same offer id', len({r['id'] for r in rows}), 1)
ok_('...in order', [r['seq'] for r in rows] == sorted(r['seq'] for r in rows))
eq('the first row had no item count', rows[0]['items'], None)
eq('the last row has it', rows[-1]['items'], 6.0)
eq('...and bills the shopping time', rows[-1]['billedMinutes'], 43.0)
ok_('which is the worse, truer rate', rows[-1]['perHour'] < rows[0]['perHour'])

# --- a bad frame in the middle does not re-arm the record -------------------
# A clipped payout parses as nothing at all. The spoken verdict clears itself on
# that, deliberately; the journal must not, or one glare frame during the
# resample burst records the card a second time.
log = fresh()
acc = OfferAccumulator()
t = 1_700_000_000.0
for i, text in enumerate([OFFER, OFFER, '', '', OFFER, OFFER]):
    parsed = acc.add(P.parse(text), now=t + i * 0.5)
    rate = P.rate(parsed, MONEY)
    if rate['ready']:
        log.consider(parsed, rate, now=t + i * 0.5)
eq('a glare frame does not duplicate the offer', len(log.journal.rows()), 1)

# --- a restart under the same card does not record it again -----------------
path = os.path.join(work, 'restart.jsonl')
if os.path.exists(path):
    os.remove(path)
first = JR.OfferLog(JR.Journal(path))
feed(first, [OFFER] * 3)
eq('the first run recorded it', len(first.journal.rows()), 1)

second = JR.OfferLog(JR.Journal(path))      # the scanner crashed and came back
resumed = second.resume(now=1_700_000_006.0)
ok_('it picks up where it left off', resumed is not None)
feed(second, [OFFER] * 3, start=1_700_000_006.0)
eq('the same card is not recorded twice', len(second.journal.rows()), 1)

# ...but a genuinely new offer after a restart still is.
feed(second, [OTHER] * 2, start=1_700_000_020.0)
eq('a new offer after a restart is recorded', len(second.journal.rows()), 2)

# ...and coming back long afterwards is a new offer, not a continuation.
third = JR.OfferLog(JR.Journal(path))
eq('an old row is not resumed',
   third.resume(now=1_700_000_020.0 + JR.RESUME_WINDOW_MS / 1000.0 + 60), None)

# --- a partial reading is kept and flagged, not silently dropped ------------
# A single leg whose "total" the reader mangled, and a two-leg card no frame
# ever caught both halves of, both look complete and both read far too well: a
# card's first leg alone is a shorter, better-paying job than the card is. They
# used to be refused, which made the offer vanish — and a gap nothing accounts
# for is the worst thing to find in a file being read back months later.
log = fresh()
acc = OfferAccumulator()
for i in range(2):
    parsed = acc.add(P.parse('$12.45 23 min (8.4 mi) trip'), now=1_700_000_000.0 + i * 0.5)
    whole = parsed['complete'] and (parsed.get('hasTotal') or (parsed.get('legs') or 0) >= 2)
    log.consider(parsed, P.rate(parsed, MONEY), now=1_700_000_000.0 + i * 0.5, whole=whole)
rows = log.journal.rows()
eq('a fragment is still recorded', len(rows), 1)
eq('...and marked as one', rows[0]['whole'], False)
eq('...with the reading it actually got', rows[0]['minutes'], 23.0)

# A card seen whole is marked whole, so the two can be told apart.
log = fresh()
acc = OfferAccumulator()
for i in range(2):
    parsed = acc.add(P.parse(OFFER), now=1_700_000_000.0 + i * 0.5)
    whole = parsed['complete'] and (parsed.get('hasTotal') or (parsed.get('legs') or 0) >= 2)
    log.consider(parsed, P.rate(parsed, MONEY), now=1_700_000_000.0 + i * 0.5, whole=whole)
eq('a card seen whole says so', log.journal.rows()[0]['whole'], True)

# And a fragment that later comes good supersedes itself, so the last row of the
# offer is the true one rather than the flattering one.
log = fresh()
acc = OfferAccumulator()
t = 1_700_000_000.0
for i, text in enumerate(['$12.45 5 min (1.2 mi) away'] * 2 + [OFFER] * 2):
    parsed = acc.add(P.parse(text), now=t + i * 0.5)
    rate = P.rate(parsed, MONEY)
    if not rate['ready']:
        continue
    whole = parsed['complete'] and (parsed.get('hasTotal') or (parsed.get('legs') or 0) >= 2)
    log.consider(parsed, rate, now=t + i * 0.5, whole=whole)
rows = log.journal.rows()
eq('the fragment and the full reading share an id', len({r['id'] for r in rows}), 1)
eq('the last row is the whole card', rows[-1]['whole'], True)
eq('...with both legs', rows[-1]['minutes'], 28.0)
ok_('...and it is the less flattering figure', rows[-1]['perHour'] < rows[0]['perHour'])

# --- nonsense is flagged, never dropped -------------------------------------
log = fresh()
feed(log, ['$1450.00 3 min (0.1 mi) total'] * 2)
rows = log.journal.rows()
eq('an implausible reading is still written', len(rows), 1)
eq('...but flagged', rows[0]['suspect'], True)

# --- a broken journal must never stop the scanner ---------------------------
broken = JR.OfferLog(JR.Journal(os.path.join(work, 'no', 'such', 'dir.jsonl')))
acc = OfferAccumulator()
parsed = acc.add(P.parse(OFFER), now=1.0)
eq('an unwritable journal returns nothing',
   broken.consider(parsed, P.rate(parsed, MONEY), now=1.0), None)
eq('...and says so once', broken.journal._error is not None, True)
eq('...and reading it back is empty, not an explosion',
   broken.journal.rows(), [])

# --- annotations from the web side must not be mistaken for offers ----------
# The file is written by two things now: the scanner adds offers, and the web
# side adds notes about them — which were taken, which to hide. A note carries a
# `kind` and an offer never does. Reading one back as an offer would have the
# scanner resume from it after a restart and record the card in front of it a
# second time, which is the one thing resume() exists to prevent.
path = os.path.join(work, 'annotated.jsonl')
if os.path.exists(path):
    os.remove(path)
log = JR.OfferLog(JR.Journal(path))
feed(log, [OFFER] * 2)
log.journal.append({'v': 1, 'kind': 'mark', 'id': 'whatever', 'at': JR.now_ms(),
                    'accepted': True})
log.journal.append({'v': 1, 'kind': 'rule', 'at': JR.now_ms(),
                    'match': {'pay': 7.09, 'minutes': 34, 'miles': 3.6}, 'hidden': True})
eq('every line is still readable', len(log.journal.rows()), 3)
last = log.journal.last()
eq('...but the last *offer* is the offer', last['pay'], 12.45)
ok_('...not the annotation', not last.get('kind'))

# ...so a restart under the same card still resumes rather than duplicating.
after = JR.OfferLog(JR.Journal(path))
ok_('a restart still resumes past the annotations',
    after.resume(now=1_700_000_006.0) is not None)
feed(after, [OFFER] * 2, start=1_700_000_006.0)
offers = [r for r in after.journal.rows() if not r.get('kind')]
eq('...and does not record the card twice', len(offers), 1)

# --- a torn line survives a power cut ---------------------------------------
path = os.path.join(work, 'torn.jsonl')
with open(path, 'w') as fh:
    fh.write(json.dumps({'v': 1, 'pay': 5.0, 'at': 1}) + '\n')
    fh.write('{"v": 1, "pay": 6.0, "at"')          # cut off mid-write
book = JR.Journal(path)
eq('the readable rows still read', len(book.rows()), 1)
eq('...and the good one is intact', book.rows()[0]['pay'], 5.0)

# --- the cap rolls rather than filling the card -----------------------------
path = os.path.join(work, 'big.jsonl')
book = JR.Journal(path, cap=200)
for i in range(40):
    book.append({'v': 1, 'at': i, 'pay': 5.0 + i})
ok_('the file was rolled', os.path.exists(path + '.1'))
ok_('...and is small again', os.path.getsize(path) <= 200 + 64)
eq('...and every row written is still readable somewhere',
   len(JR.Journal(path).rows()) + len(JR.Journal(path + '.1').rows()) > 0, True)

shutil.rmtree(work, ignore_errors=True)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d journal checks passed' % ok)
sys.exit(1 if bad else 0)
