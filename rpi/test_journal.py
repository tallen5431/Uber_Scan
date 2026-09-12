"""Tests for keeping a record of the offers that were read.

    python3 rpi/test_journal.py

Every interesting case here is one that cannot be produced through a camera: a
card read twice, a card that improves after the first confident look, a card
still on screen when the scanner is restarted under it. Those are exactly the
cases that turn one offer into two in a year of data, or lose one entirely.
"""

import json
import os
import time
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import journal as JR
import offer_parser as P
from accumulate import OfferAccumulator
from accumulate import SCANS_PER_OFFER as ACCUM_SCANS

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
# The reading itself, which this file deliberately did NOT keep until now.
#
# The omission had a stated reason — "the useful part is already parsed into
# numbers; what is left is pickup addresses" — and that reason was superseded by
# a later change: `places` stores exactly those addresses, in the row, in the
# CSV and in the sync. What was left out to protect is now kept beside it.
#
# What the omission cost is measurable. 568 real offers on record and not one
# recoverable card, so every question about the parser has been answered against
# rendered replicas — and the "Avg. wait time at pickup" line that switched the
# running cost off on a third of one shift was found only from three mangled
# fragments that survived in `places`, because the addresses were kept and the
# text was not.
# `.get`, not `[...]`. A missing key here raised a KeyError and took the rest of
# the file with it, so removing the field looked like a crash rather than a
# failed check — and every check below it stopped running. A mutation that stops
# the suite is not the same as a mutation the suite catches.
eq('the reading is kept, so the corpus can be this driver\'s own cards',
   kept.get('text'), OFFER)
eq('...and it is bounded, because a bad crop reads half the map as well',
   len(kept.get('text') or '') <= JR.TEXT_KEPT, True)

# ...and bounded is only half of it. The bound was 220, and the first export to
# carry this column came back with 99 of its 309 cards sitting exactly on it: a
# third of the corpus cut off, and cut off at the END, where the pickup, the
# dropoff and a ride's second leg are written. The check above passes at any cap
# at all, including one that keeps nothing useful — an upper bound cannot say
# whether the column does its job.
#
# This is a real card off the driver's own phone, at the length a real card
# actually runs to. Kept whole or the column is not worth having.
LONG_CARD = (
    "| UR jiedmont Park a ; y ees ae ave ied nA SS S ANKHEAD : ' ; - CCE "
    "CiGem Exclusive x i + $11.42 Guaranteed (incl. tip) 14 min (2.0 mi) "
    "total Taco Bell (930 Spring Street) I Ivan Allen Jr Blvd NW & Spring "
    "St NW, Atlanta Avg. wait time at pickup: 3 min Accept Decline")
long_log = fresh('long.jsonl')
feed(long_log, [LONG_CARD] * 3)
long_kept = (long_log.journal.rows()[0] if long_log.journal.rows() else {}).get('text') or ''
ok_('a real card is longer than the old cap (%d chars)' % len(LONG_CARD),
    len(LONG_CARD) > 220)
eq('...and the cap keeps one whole rather than cutting its addresses off',
   long_kept, LONG_CARD)

# --- what the reader saw, all of it -----------------------------------------
#
# Two separate things the journal keeps so a question about the OCR can be asked
# of what the camera really produced.
#
# The LINE BREAKS. Every parser rule works on the flattened text, and flattening
# throws away which line each figure sat on — which is the part of a card's
# meaning the last two parser fixes had to rediscover from punctuation.
LINED = ('$8.40 Guaranteed (incl. tip)\n'
         '2.4 mi \u00b7 20 min\n'
         'Pickup McDonald\'s\n'
         'Cobb Pkwy NW, Acworth')
lines_log = fresh('lines.jsonl')
feed(lines_log, [LINED] * 3)
lined = (lines_log.journal.rows() or [{}])[-1]
ok_('the reading is kept with its line breaks', '\n' in (lined.get('text') or ''))
eq('...exactly as the reader gave it', lined.get('text'), LINED)

# ...and EVERY FRAME, not the one that won. A card is read several times and the
# frames disagree; that disagreement is the whole reason the accumulator exists,
# and only the winner used to reach disk.
DIM = "$8.40 Guaranteed (incl. tip) 2.4 mi + 20 min Pickup McDonald's"
GLARE = "$8.40 Guaranteed (incl. tip) 2.4 mi + 20 min Pickup McDonaId's"   # a misread
frames_log = fresh('frames.jsonl')
feed(frames_log, [DIM, GLARE, DIM, GLARE])
# The LAST row, not the first. A reading that improves is appended, and the
# export takes the latest per offer — so the first row is what was known
# after one frame, which is exactly what this is checking is not all there is.
kept_row = (frames_log.journal.rows() or [{}])[-1]
scans = kept_row.get('scans') or []
ok_('every distinct reading of the card is kept', len(scans) >= 2)
ok_('...including the one that lost the vote', GLARE in scans)
ok_('...and the one that won', DIM in scans)
eq('...with the repeats left out, because a still card says the same thing',
   len(scans), len(set(scans)))
ok_('...and each of them bounded like the reading itself',
    all(len(t) <= JR.TEXT_KEPT for t in scans))

# A card read once has nothing to disagree with, and must not grow a list for
# the sake of it.
one_log = fresh('one.jsonl')
feed(one_log, [DIM])
only = (one_log.journal.rows() or [{}])[-1]
ok_('a card read once still records what was read',
    (only.get('scans') or [None])[0] == DIM)

# The bound. A card that will not settle is exactly the one producing the most
# distinct texts, and it must not be the one that fills the SD card.
many_log = fresh('many.jsonl')
feed(many_log, ["$8.40 Guaranteed (incl. tip) 2.4 mi + 20 min Pickup McDonald's %d" % i
                for i in range(20)])
many = (many_log.journal.rows() or [{}])[-1]
ok_('...and a card that never settles cannot grow without bound',
    len(many.get('scans') or []) <= ACCUM_SCANS)

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
# ...and it does not pretend the card is on disk.
#
# `id` is assigned the moment consider() decides a reading is a new card,
# BEFORE the append is attempted, so it says only that this process has a name
# for the card. scan_pi's health counter was reading it as "this card reached
# the file": with the journal unwritable — an SD card remounted read-only
# mid-shift is the classic Pi failure — eight cards produced eight ids, zero
# rows, and the two-minute status line read "8 cards seen, 8 recorded". The one
# counter built to say how much the journal is missing reported no misses at
# the moment it was missing everything.
ok_('a card the journal refused has an id all the same', broken.id is not None)
eq('...and nothing recorded as having landed', broken.landed_id, None)
ok_('...so the two do not agree, which is what the health line asks',
    broken.landed_id != broken.id)
# The same question of a journal that works has to answer the other way, or
# the check above is satisfied by a counter that never counts anything.
good = fresh()
feed(good, [OFFER])
ok_('a card that reached the file says so', good.landed_id is not None)
eq('...naming the card that landed', good.landed_id, good.id)
# One failure does not condemn the next success: a card lands after the disk
# comes back, and the counter has to follow it.
recovered = JR.OfferLog(JR.Journal(os.path.join(work, 'recovered.jsonl')))
acc2 = OfferAccumulator()
p2 = acc2.add(P.parse(OFFER), now=1.0)
recovered.journal.path = os.path.join(work, 'no', 'such', 'dir.jsonl')
recovered.consider(p2, P.rate(p2, MONEY), now=1.0)
eq('a refused card leaves the landed marker alone', recovered.landed_id, None)
recovered.journal.path = os.path.join(work, 'recovered.jsonl')
acc3 = OfferAccumulator()
p3 = acc3.add(P.parse(OTHER), now=200.0)
recovered.consider(p3, P.rate(p3, MONEY), now=200.0)
eq('...and the next card that lands sets it', recovered.landed_id, recovered.id)

# --- a journal that stays broken keeps saying so ----------------------------
#
# "Say it once" became "say it once, ever". A path that fails identically on
# every offer printed one line and then nothing for the rest of the shift,
# because the message never changes — so the evidence that the irreplaceable
# file is not being written scrolls off a headless box's log within minutes of
# the failure starting.
import io as _io                                               # noqa: E402
import contextlib as _ctx                                      # noqa: E402
quiet = JR.Journal(os.path.join(work, 'no', 'such', 'dir.jsonl'))
buf = _io.StringIO()
with _ctx.redirect_stdout(buf):
    for _ in range(50):
        quiet.append({'id': 'x'})
eq('fifty failures in a row are one line, not fifty',
   buf.getvalue().count('could not use the offer journal'), 1)
buf = _io.StringIO()
quiet._said_at = time.time() - JR.Journal.REPEAT_AFTER_S - 1
with _ctx.redirect_stdout(buf):
    quiet.append({'id': 'x'})
eq('...and it is said again once the interval has passed',
   buf.getvalue().count('could not use the offer journal'), 1)

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
last = log.journal.last() or {}
# `.get`, and `or {}` above. A mutation that makes last() return the annotation
# — or nothing — used to raise KeyError here and take every check below it with
# it, so a broken reader looked like a crashed file rather than a failed claim.
# A mutation that stops the suite is not the same as one the suite catches.
eq('...but the last *offer* is the offer', last.get('pay'), 12.45)
ok_('...not the annotation', not last.get('kind'))

# ...so a restart under the same card still resumes rather than duplicating.
after = JR.OfferLog(JR.Journal(path))
ok_('a restart still resumes past the annotations',
    after.resume(now=1_700_000_006.0) is not None)
feed(after, [OFFER] * 2, start=1_700_000_006.0)
offers = [r for r in after.journal.rows() if not r.get('kind')]
eq('...and does not record the card twice', len(offers), 1)

# --- "settled" means the reading stopped moving, so it has to be able to -----
# A row is only ever written on the read where the reading *changed*, so at that
# moment "this reading has stopped moving" is false by construction. 208 of 245
# rows in one real journal claimed the reading was still changing — including
# cards read identically four times running — and the offers page printed that
# warning on 85% of everything in it. A flag that fires on nearly every row is
# not a flag, it is a description of the mechanism that wrote it.
log = fresh('settling.jsonl')
acc = OfferAccumulator()
t = 1_700_000_000.0
previous = None
for i in range(6):
    parsed = acc.add(P.parse(OFFER), now=t + i * 0.5)
    sig = (parsed['pay'], parsed['minutes'], parsed['miles'])
    log.consider(parsed, P.rate(parsed, MONEY), now=t + i * 0.5,
                 settled=(sig == previous), whole=True)
    previous = sig
rows = log.journal.rows()
eq('a card that settles is superseded once, not once per look', len(rows), 2)
eq('...under the same id', len({r['id'] for r in rows}), 1)
eq('the first row is honest that it had just changed', rows[0]['settled'], False)
eq('...and the second says it stopped changing', rows[-1]['settled'], True)
eq('...carrying the same reading', rows[-1]['pay'], rows[0]['pay'])
eq('...and the same journey', rows[-1]['minutes'], rows[0]['minutes'])
ok_('...as a later row, so the reader prefers it',
    rows[-1]['seq'] > rows[0]['seq'])

# A reading that never holds still is never upgraded, which is the whole point
# of keeping the flag at all.
log = fresh('never-settles.jsonl')
acc = OfferAccumulator()
for i, pay in enumerate(['$12.45', '$12.45', '$12.45']):
    text = '%s 5 min (1.2 mi) away %d min (8.4 mi) trip' % (pay, 23 + i)
    parsed = acc.add(P.parse(text), now=t + 100 + i * 0.5)
    log.consider(parsed, P.rate(parsed, MONEY), now=t + 100 + i * 0.5,
                 settled=False, whole=True)
ok_('a reading that keeps moving is never marked settled',
    not any(r['settled'] for r in log.journal.rows()))

# --- a torn line survives a power cut ---------------------------------------
path = os.path.join(work, 'torn.jsonl')
with open(path, 'w') as fh:
    fh.write(json.dumps({'v': 1, 'pay': 5.0, 'at': 1}) + '\n')
    fh.write('{"v": 1, "pay": 6.0, "at"')          # cut off mid-write
book = JR.Journal(path)
eq('the readable rows still read', len(book.rows()), 1)
eq('...and the good one is intact', book.rows()[0]['pay'], 5.0)

# ...and the next row written after the power cut is not eaten by the stub.
#
# A torn line has no newline on the end of it, so appending straight onto it
# fuses the two into one unparseable line — and the reader skips unparseable
# lines. One lost row is the price of a power cut and this file is built to pay
# it; two is a missing byte, and the second one is the offer written after the
# car came back, which nothing would ever have said was missing.
eq('the next row after a torn line still lands', book.append(
    {'v': 1, 'pay': 7.0, 'at': 3}), True)
back = JR.Journal(path).rows()
eq('...and reads back', len(back), 2)
eq('...as itself', back[-1]['pay'], 7.0)
eq('...with the row before it still there', back[0]['pay'], 5.0)

# The ordinary case must not grow a blank line per row.
path = os.path.join(work, 'tidy.jsonl')
tidy = JR.Journal(path)
for i in range(3):
    tidy.append({'v': 1, 'at': i, 'pay': 1.0 + i})
eq('an untorn journal gains no blank lines',
   open(path).read().count('\n\n'), 0)
eq('...and reads back whole', len(JR.Journal(path).rows()), 3)

# A journal that does not exist yet is not a torn one.
path = os.path.join(work, 'first.jsonl')
first = JR.Journal(path)
first.append({'v': 1, 'at': 1, 'pay': 2.0})
eq('the very first row needs no newline before it',
   open(path).read().startswith('{'), True)

# --- the cap rolls rather than filling the card -----------------------------
path = os.path.join(work, 'big.jsonl')
book = JR.Journal(path, cap=200)
for i in range(40):
    book.append({'v': 1, 'at': i, 'pay': 5.0 + i})
ok_('the file was rolled', os.path.exists(path + '.1'))
ok_('...and is small again', os.path.getsize(path) <= 200 + 64)
eq('...and every row written is still readable somewhere',
   len(JR.Journal(path).rows()) + len(JR.Journal(path + '.1').rows()) > 0, True)

# --- an address survives every path a row is written by --------------------
#
# The settled upgrade rebuilds the row from the *current* reading, and 93 of one
# real shift's 121 rows go through it. A reading that had lost the map to glare
# therefore superseded a row that had the address with one that did not — and
# the superseding row is the newest, which is the one every reader takes.
WITH = ('UberX $12.45 5 min (1.2 mi) away Chastain Rd NW, Kennesaw '
        '23 min (8.4 mi) trip Canton Rd, Marietta')
WITHOUT = '$12.45 5 min (1.2 mi) away 23 min (8.4 mi) trip'
WHERE = ['Chastain Rd NW, Kennesaw', 'Canton Rd, Marietta']

log = fresh('places.jsonl')
acc = OfferAccumulator()
t = 1_700_000_000.0
for i, text in enumerate([WITH, WITHOUT, WITHOUT, WITHOUT]):
    parsed = acc.add(P.parse(text), now=t + i * 0.5)
    # `settled` from the second look on, as the scan loop reports it once a
    # reading stops moving. That is the path that rebuilds the row.
    log.consider(parsed, P.rate(parsed, MONEY), now=t + i * 0.5, settled=i > 0)
rows = log.journal.rows()
ok_('the card that named two places was recorded', len(rows) >= 1)
eq('the first row has the address', rows[0]['places'], WHERE)
eq('...and so does the last, however it was written',
   rows[-1]['places'], WHERE)
ok_('...including the settled upgrade', any(r.get('settled') for r in rows))

# The other order, and the one the address usually arrives in: the first look
# misses the map and a later one finds it. `content_of` does not look at the
# address, so that read writes no new row at all — the address has to reach the
# row some other way or it never lands.
log = fresh('places-late.jsonl')
acc = OfferAccumulator()
for i, text in enumerate([WITHOUT, WITHOUT, WITH]):
    parsed = acc.add(P.parse(text), now=t + i * 0.5)
    log.consider(parsed, P.rate(parsed, MONEY), now=t + i * 0.5)
eq('an address found on a later look still reaches the journal',
   log.journal.rows()[-1]['places'], WHERE)

# ...and the setting still turns the whole thing off. A remembered list that
# ignored the flag would keep storing addresses after it was switched off,
# which is the one behaviour this feature promised it would not have.
log = JR.OfferLog(JR.Journal(os.path.join(work, 'no-places.jsonl')),
                  keep_places=False)
acc = OfferAccumulator()
for i, text in enumerate([WITH, WITHOUT]):
    parsed = acc.add(P.parse(text), now=t + i * 0.5)
    log.consider(parsed, P.rate(parsed, MONEY), now=t + i * 0.5)
eq('keepPlaces off stores no address at all',
   [r['places'] for r in log.journal.rows()], [[]] * len(log.journal.rows()))

shutil.rmtree(work, ignore_errors=True)


# --- an uncertain distance never reaches the offers page dressed as a good one
#
# rate() charges no mileage at all for a distance it does not trust, so such a
# row's $/hr is gross wearing net's clothes. That is fine while something says
# so — and something does, twice over: server.js's bestReading drops a row 100
# points for not being whole and 1000 for being suspect, so an uncertain row can
# never out-vote a clean reading of the same card. But it only works because
# every route to `milesUncertain` also trips one of those two flags, and that is
# true today by an accident of arithmetic rather than by anything written down.
#
# There are exactly two routes. A journey whose legs disagree about having a
# distance is not whole (offer_parser.legs_short_a_distance). A distance that
# implies a speed no card can mean is uncertain past UNREADABLE_MPH — and
# `suspect` is decided by SANE_MPH, which happens to be the same 75.0, reached
# by different reasoning in a different part of the file.
#
# So the second route holds only while UNREADABLE_MPH >= SANE_MPH, and the
# dangerous edit is *lowering* it. Drop it to 60 — which sounds cautious, and
# reads as tightening a guard — and every sum between 60 and 75 mph becomes a
# distance the reading will not be costed on while nothing else marks it. Such a
# row is whole, not suspect, carries no mileage cost at all, and beats the clean
# reading of the same card in bestReading if two frames produced it. Its
# cost-free $/hr then goes into the list and into every median on the page.
#
# So the property is asserted rather than the coincidence: whatever the two
# numbers are, a row that distrusts its own distance must admit it some other
# way as well. The sums below deliberately include several that land just under
# the line, since a case in the middle of the range cannot see this at all.
def a_row(text):
    parsed = P.parse(text)
    rate = P.rate(parsed, MONEY)
    return JR.row_for(parsed, rate, 1_700_000_000_000, offer_id='p', seq=1,
                      ms=1400, locked=True, settled=True,
                      whole=P.is_whole(parsed))


uncertain_rows = 0
for pay in ('$16.05', '$41.11'):
    for first in ('1 min (0.4 mi)', '3 min (1.1 mi)', '25 min (11.q5 mi)',
                  '25 min (1q.5 mi)'):
        for second in ('20 min (7.3 mi)', '20 min (7.3 m1)', '4 min (73.5 mi)',
                       '2 min (88.2 mi)', '40 min (0.2 mi)',
                       # Sums landing just under the line, which is where the
                       # two thresholds would come apart if either moved.
                       '3 min (5.9 mi)', '4 min (6.8 mi)', '5 min (10.4 mi)',
                       # ...and both legs losing their distance, which
                       # leaves no distance at all rather than a short one.
                       '17 min (3.q mi)'):
            row = a_row('%s %s away %s trip' % (pay, first, second))
            if not row['milesUncertain']:
                continue
            uncertain_rows += 1
            ok_('a row that distrusts its distance says so another way too: %s %s'
                % (first, second),
                row['suspect'] or row['whole'] is False)

ok_('...and the sweep actually produced some to check', uncertain_rows >= 6)

# --- and a row the medians will count has a distance to be costed on --------
#
# The sweep above asks whether an uncertain distance owns up to it. This asks
# the question from the other end, and it is the one that catches a distance
# that never appeared at all.
#
# journal.html counts a row into every median on the page when Advice.trustworthy
# accepts it — not hidden, not suspect, `whole` not false — and rate() charges no
# mileage for a distance it does not have. So a two-leg card whose distances BOTH
# failed to read lands as `miles: null`, which is indistinguishable from a card
# that states no distance: nothing marks it, and its gross rate is pooled with
# everyone else's net ones. Measured on
# `$16.05 25 min (11.q5 mi) away 17 min (3.q mi) trip`: $22.93/hr, whole,
# unflagged, counted.
#
# One leg losing its distance used to be caught and both losing it did not,
# which is the wrong way round — the second leaves less evidence, not more.
def trustworthy(row):
    """journal.html's rule for a row worth counting, as advice.js states it."""
    return not row.get('hidden') and not row['suspect'] and row['whole'] is not False


counted_rows = 0
for first, second in (('25 min (11.q5 mi)', '17 min (3.q mi)'),
                      ('25 min (11.q5 mi)', '17 min (3.7 mi)'),
                      ('3 min (1.1 mi)', '20 min (7.3 m1)'),
                      ('3 min (1.1 mi)', '20 min (7.3 mi)')):
    row = a_row('$16.05 %s away %s trip' % (first, second))
    if not trustworthy(row):
        continue
    counted_rows += 1
    ok_('a counted two-leg row has a distance: %s %s' % (first, second),
        row['miles'] is not None)
    ok_('...and was actually costed on it: %s %s' % (first, second),
        (row['cost'] or 0) > 0)

eq('...and exactly one of those four is fit to count', counted_rows, 1)

# The same property from the other side: a row that is neither suspect nor
# short a leg has a distance it is willing to be costed on.
clean = a_row('$16.05 3 min (1.1 mi) away 20 min (7.3 mi) trip')
eq('a clean two-leg reading is costed', clean['milesUncertain'], False)
ok_('...and is whole', clean['whole'])
ok_('...and is not suspect', not clean['suspect'])
ok_('...and its mileage actually came off the top', (clean['cost'] or 0) > 0)

# --- reading the end of the journal without reading all of it ---------------
#
# `last()` reads backwards from the end of the file and `count()` counts lines,
# where both used to build every row into memory first. On a year of driving —
# 40,000 rows, 68MB — that was 287ms and 68MB of Python objects at every
# startup, on a Pi, to answer "what was the last offer".
#
# The saving comes from byte handling, and byte handling is where this kind of
# rewrite goes wrong: a row that straddles the read block, a file with no
# trailing newline, an annotation at the end that has to be skipped past. Each
# of those is a way to return the wrong row or none at all, and the old
# implementation is the thing to be right against.
def _old_last(j):
    for row in reversed(j.rows()):
        if not row.get('kind'):
            return row
    return None


_endwork = tempfile.mkdtemp()


def _journal_of(name, lines):
    path = os.path.join(_endwork, name)
    with open(path, 'w') as fh:
        fh.write(lines)
    return JR.Journal(path)


_cases = {
    'an empty file': '',
    'a single offer': json.dumps({'at': 1, 'pay': 5}) + '\n',
    # The last LINE is an annotation; the last OFFER is the row before it.
    # Reading backwards has to walk past it rather than stop at it.
    'an annotation written last':
        json.dumps({'at': 1, 'pay': 5}) + '\n' + json.dumps({'at': 2, 'kind': 'mark'}) + '\n',
    'nothing but annotations':
        json.dumps({'at': 1, 'kind': 'mark'}) + '\n' + json.dumps({'at': 2, 'kind': 'mark'}) + '\n',
    'blank lines in the middle':
        json.dumps({'at': 1, 'pay': 5}) + '\n\n\n' + json.dumps({'at': 2, 'pay': 9}) + '\n\n',
    # No trailing newline: the last row is the partial-looking one, and it is
    # a whole row. A reader that discards the fragment loses the offer.
    'no trailing newline':
        json.dumps({'at': 1, 'pay': 5}) + '\n' + json.dumps({'at': 2, 'pay': 9}),
}
# ...and a file big enough that the last offer is not in the final read block,
# with a long tail of annotations after it so the walk has to cross a boundary.
_big = ''.join(json.dumps({'at': i, 'pay': 5.0, 'pad': 'x' * 300}) + '\n'
               for i in range(300))
_big += ''.join(json.dumps({'at': 900 + i, 'kind': 'mark'}) + '\n' for i in range(400))
_cases['the last offer is several blocks back'] = _big

# ...and the case the block reading actually turns on: the last offer's row
# STRADDLES the boundary, so half of it arrives in one read and half in the
# next. Get the joining wrong and the row is either lost — the answer becomes
# an older offer, or none — or its first half is parsed as a row in its own
# right. The count is searched for rather than written down, so this keeps
# meaning what it says if a row's shape changes.
_OFFER = json.dumps({'at': 1, 'pay': 5.0, 'pad': 'x' * 120}) + '\n'
_HEAD = ''.join(json.dumps({'at': 100 + i, 'pay': 1.0, 'pad': 'y' * 200}) + '\n'
                for i in range(20))
_straddle = None
for _n in range(1500, 2600):
    _notes = ''.join(json.dumps({'at': 900 + i, 'kind': 'mark'}) + '\n'
                     for i in range(_n))
    _body = _HEAD + _OFFER + _notes
    _edge = len(_body) - 65536          # the first byte of the final read
    if len(_HEAD) < _edge < len(_HEAD) + len(_OFFER):
        _straddle = _body
        break
ok_('a straddling case could be built', _straddle is not None)
if _straddle:
    _cases['the last offer straddles a block boundary'] = _straddle

for _name, _body in _cases.items():
    _j = _journal_of(_name.replace(' ', '_') + '.jsonl', _body)
    eq('the end of the journal is found with %s' % _name, _j.last(), _old_last(_j))
    eq('...and counted without building it, with %s' % _name,
       _j.count(), len(_j.rows()))
shutil.rmtree(_endwork, ignore_errors=True)

# --- which end is which -----------------------------------------------------
# A row records what the card printed AND which of those is the shop and which
# is somebody's front door, because that is what a second offer gets judged
# against. Derived from the row's own `places` so a trimmed list stays honest.
_ends = JR.row_for(
    P.parse("Exclusive x $11.88 Guaranteed (incl. tip) 35 min (17.9 mi) total "
            "| Mellow Mushroom (Acworth) \\ Lakeview Ter & Windmill Dr, Dallas"),
    {'ready': True, 'state': 'no'}, at=1000)
eq('a row names the shop it starts at', _ends['pickup'], 'Mellow Mushroom (Acworth)')
eq('...and the door it ends at', _ends['dropoff'], 'Lakeview Ter & Windmill Dr, Dallas')

_shoponly = JR.row_for(
    P.parse("$15.60 Guaranteed (incl. tips) 7.9 mi + 37 min @ Retail pickup GoPuff (Drive)"),
    {'ready': True, 'state': 'no'}, at=1000)
eq('a card that named only the shop records no dropoff', _shoponly['dropoff'], None)

_trimmed = JR.row_for(
    P.parse("Exclusive x $11.88 Guaranteed (incl. tip) 35 min (17.9 mi) total "
            "| Mellow Mushroom (Acworth) \\ Lakeview Ter & Windmill Dr, Dallas"),
    {'ready': True, 'state': 'no'}, at=1000, places=[])
eq('...and a row whose places were trimmed away records neither',
   (_trimmed['pickup'], _trimmed['dropoff']), (None, None))

# --- how much of the journey was getting to the work ------------------------
#
# The row has always held the card's TOTAL time and distance, which is the right
# figure to judge an offer on: the driver spends the approach either way. It is
# the wrong figure for any question about where the WORK is, because it moves
# with wherever the car happened to be when the card arrived — the same two
# places produce a different total every time.
#
# Nothing can put this back for a row already written, which is why it is
# checked at the row rather than only at the parser: the parser reading it and
# the journal dropping it is exactly the state this was in.
_split = a_row('UberX $12.45 5 min (1.2 mi) away Old 41 Hwy NW, Kennesaw '
               '23 min (8.4 mi) trip Celebration Blvd, Acworth')
eq('the row keeps the whole journey the card stated',
   (_split['minutes'], _split['miles']), (28.0, 9.6))
eq('...and how much of it was the drive to the pickup',
   (_split['toPickupMinutes'], _split['toPickupMiles']), (5.0, 1.2))
# The subtraction the whole field exists to make possible.
eq('...so what is left is the job itself',
   (round(_split['minutes'] - _split['toPickupMinutes'], 1),
    round(_split['miles'] - _split['toPickupMiles'], 1)), (23.0, 8.4))

# A delivery card states one total and never says how much of it is the drive
# to the restaurant. Null, not zero: a zero would be subtracted and would make
# the approach vanish into the job, which is a confident wrong distance between
# two places rather than an absent one.
_whole_total = a_row('Shop & Deliver $7.09 6 items 34 min (3.6 mi) total '
                     'Five Guys (3450 Cobb Pkwy. NW)')
eq('a card that never split its journey records no split',
   (_whole_total['toPickupMinutes'], _whole_total['toPickupMiles']), (None, None))
ok_('...while still recording the journey itself',
    _whole_total['minutes'] == 34.0 and _whole_total['miles'] == 3.6)

# The field has to be on every row, present or absent, or a reader cannot tell
# "this card did not say" from "this rig was too old to record it".
for _name, _row in (('a split card', _split), ('an unsplit one', _whole_total)):
    ok_('%s carries both halves of the field' % _name,
        'toPickupMinutes' in _row and 'toPickupMiles' in _row)

# --- the row and the screen have to say the same thing -----------------------
#
# The row was working the verdict out a second time. OP.doubt() takes three
# numbers and can only ask whether those three can be true; rate() also weighs
# the SHAPE of the reading and refuses a rate worked out over one leg of a
# journey the card printed two of. So a card the panel refused at $220.80/hr
# was written down as `state: 'doubt'` with `doubt: None` — a row saying it was
# not judged and declining to say why, which is the one thing a record of a
# refusal is for. The offers page then explained it as a crop that clipped the
# card: a specific claim, and a false one.
_leg = a_row('UberX $18.40 5 min (2.1 mi) away l hr 24 min (7.8 mi) trip')
_leg_rate = P.rate(P.parse('UberX $18.40 5 min (2.1 mi) away l hr 24 min (7.8 mi) trip'),
                   MONEY)
eq('a row refused for a leg records that it was refused',
   _leg['state'], 'doubt')
eq('...and says which refusal it was, as the screen did',
   (_leg['doubt'], _leg_rate['doubt']), ('leg', 'leg'))
eq('...with how much of the journey never got timed',
   _leg['untimedMiles'], 7.8)
# Belt and braces, and the braces matter: `whole` is an ARGUMENT to row_for, so
# a caller that got it wrong would put a $213/hr reading into the medians. The
# row marks itself not-to-be-trusted on its own account as well.
ok_('...and is kept out of the figures without relying on its caller',
    _leg['suspect'] is True)
ok_('...while still carrying every figure it read, for the record',
    _leg['pay'] == 18.4 and _leg['minutes'] == 5.0 and _leg['miles'] == 2.1)

# ...and the field is on every row, present or absent, for the same reason
# toPickup* is: a reader cannot otherwise tell "nothing was missing" from "this
# rig was too old to say".
for _name, _row in (('a refused row', _leg), ('an ordinary one', _whole_total)):
    ok_('%s carries the untimed distance' % _name, 'untimedMiles' in _row)
eq('an ordinary row has none', _whole_total['untimedMiles'], None)

# The fallback, for a rate dict built by hand — the keypad, a test, an older row
# being re-rated — which has no verdict in it to take.
#
# The figures here are deliberately impossible: $1030 over ten minutes is the
# lost decimal point this project has on record, and $1030 is past SANE_PAY on
# its own. A row built from a dict with no verdict in it must still get one, or
# dropping the fallback would look like a working change — both paths answer
# None on a card where nothing is wrong.
_HAND_BUILT = {'ready': True, 'state': 'go', 'perHour': 6180.0,
               'grossPerHour': 6180.0, 'minutes': 10.0, 'miles': 3.0,
               'cardMinutes': 10.0, 'net': 1030.0, 'cost': 0.0,
               'perMin': 103.0, 'perMile': 343.3, 'target': 25, 'band': 15,
               'costPerMile': 0.0, 'billedMinutes': 10.0}
_typed = JR.row_for(P.parse('$1030.00 10 min (3.0 mi) total'), _HAND_BUILT,
                    1_700_000_000_000, offer_id='t', seq=1)
eq('a rate with no verdict in it still gets one worked out', _typed['doubt'], 'pay')
ok_('...and the row is written rather than refused', _typed['pay'] == 1030.0)
ok_('...and marked not to be trusted, as it would have been either way',
    _typed['suspect'] is True)

# --- a line that will not read is an offer that is gone ----------------------
#
# Skipping it is right: the file is append-only, it cannot be repaired, and one
# bad line must not cost the other fifty thousand. Saying nothing about it was
# not. This is the one artefact the rig produces that cannot be regenerated,
# and a row disappearing out of every figure with nothing anywhere saying so is
# the failure this project keeps writing sections about.
import tempfile as _tf

_torn_dir = _tf.mkdtemp()
_torn_path = os.path.join(_torn_dir, 'offers.jsonl')
_GOOD = {'v': 3, 'id': 'g1', 'seq': 1, 'at': 1_789_000_000_000, 'pay': 10.0}
_NEXT = {'v': 3, 'id': 'g2', 'seq': 1, 'at': 1_789_000_060_000, 'pay': 11.0}
with open(_torn_path, 'w') as _fh:
    _fh.write(json.dumps(_GOOD) + '\n')
    # A row the engine interrupted, and then terminated by the next append.
    _fh.write(json.dumps(_NEXT)[:30] + '\n')
    # ...and the row being written right now, which is not a casualty.
    _fh.write(json.dumps(_NEXT)[:30])

_torn_log = JR.Journal(_torn_path)
_kept = _torn_log.rows()
eq('a torn line costs its own row and no other', len(_kept), 1)
eq('...and is counted rather than passed over in silence', _torn_log.torn, 1)
# The distinction that stops this reporting a fault on every busy shift: the
# scanner appends while everything else reads, so the last line of a live
# journal routinely has no newline on it yet. It is not torn, it is not
# finished — and append() terminates it before writing the next row, so a real
# casualty is counted the moment the car comes back.
ok_('...counting the row being written now as neither read nor lost',
    _torn_log.torn == 1 and len(_kept) == 1)

# --- one bad byte costs one line, not the file -------------------------------
#
# Opened as text, the decode happens for the whole file at once: a single
# corrupt byte raises UnicodeDecodeError out of the iteration, the handler at
# the bottom throws away every row already parsed, and rows() hands back an
# empty list with `torn` reporting the file as whole. Measured before the fix
# on exactly this fixture: four of the five lines still perfect JSON, and NONE
# of them returned.
#
# server.js reads the same file the other way — buffers split on the newline
# byte, each piece decoded on its own — and kept the four. Two readers of one
# file disagreeing about what is in it is the fault this project keeps finding.
_bad_path = os.path.join(_torn_dir, 'badbyte.jsonl')
_raw = bytearray()
for _i in range(5):
    _raw += (json.dumps({'v': 3, 'id': 'b%d' % _i, 'seq': 1,
                         'at': 1_789_000_000_000 + _i, 'pay': 10.0}) + '\n').encode()
_still_good = sum(1 for _l in bytes(_raw).split(b'\n') if _l.strip())
_raw[200] = 0xff
open(_bad_path, 'wb').write(bytes(_raw))
_bad_log = JR.Journal(_bad_path)
_bad_rows = _bad_log.rows()
eq('a corrupt byte costs its own line and no other', len(_bad_rows), _still_good - 1)
eq('...and that line is counted, not passed over', _bad_log.torn, 1)
eq('...and the read is not reported as having failed', _bad_log.unreadable, None)
# The rows that survived have to be usable, not just counted: this is the file
# a backup is about to copy.
ok_('...with the surviving rows intact',
    all(isinstance(r, dict) and r.get('pay') == 10.0 for r in _bad_rows))

# --- a file that cannot be read is not a file with nothing in it -------------
#
# The distinction the callers could not make. sync.py read an empty list as
# "nothing new", exited 0 and stamped the copy fresh, which doctor.py then
# reported as a healthy backup made minutes ago — a rig saying everything is
# fine while nothing at all is being copied off it.
_gone = os.path.join(_torn_dir, 'nodir', 'offers.jsonl')
_unreadable = JR.Journal(_gone)
eq('a journal that is simply absent reads as empty', _unreadable.rows(), [])
eq('...and says nothing failed, because nothing did', _unreadable.unreadable, None)

# Staged as a DIRECTORY where the journal should be, rather than by taking the
# read permission away: the rig's own suites are run as root often enough that
# a chmod-based fixture would quietly stop testing anything, and a check that
# cannot fail is worse than no check. A directory refuses everybody.
_locked = os.path.join(_torn_dir, 'notafile.jsonl')
os.mkdir(_locked)
_locked_log = JR.Journal(_locked)
eq('a journal that cannot be opened reads as empty too', _locked_log.rows(), [])
ok_('...but says so, so nobody reads the emptiness as a quiet week',
    bool(_locked_log.unreadable))
ok_('...naming what stopped it (%r)' % (_locked_log.unreadable or '')[:48],
    'directory' in (_locked_log.unreadable or '').lower())

# A whole file reports none, or the count above means nothing.
_whole_path = os.path.join(_torn_dir, 'whole.jsonl')
with open(_whole_path, 'w') as _fh:
    _fh.write(json.dumps(_GOOD) + '\n')
    _fh.write(json.dumps(_NEXT) + '\n')
_whole_log = JR.Journal(_whole_path)
eq('an intact journal reads every row', len(_whole_log.rows()), 2)
eq('...and reports nothing torn', _whole_log.torn, 0)

# The count belongs to the last read, not to the life of the object: a journal
# re-read after the card was replaced must not still be reporting the old hole.
_torn_log.rows()
eq('a second read does not add the same casualty twice', _torn_log.torn, 1)

# ...and the write side's own guarantee, which is what keeps ONE torn line from
# becoming two: a stub is terminated before the next row goes on, so the offer
# written after the car came back is not fused to the one that was lost.
_after = JR.Journal(_torn_path)
ok_('an append after a torn line lands on its own line',
    _after.append({'v': 3, 'id': 'g3', 'seq': 1, 'at': 1_789_000_120_000,
                   'pay': 12.0}))
_after_rows = _after.rows()
eq('...so the offer after the power cut survives', len(_after_rows), 2)
# Two now, and that is the rule working rather than failing. The stub this
# fixture left open was a casualty all along — it was simply not finished, so
# nothing could say yet — and terminating it is what turns "cannot tell" into
# a count. The offer written after it is whole, which is the property that
# matters: one power cut costs one row, not two.
eq('...and the stub it was fused against is now counted too', _after.torn, 2)
shutil.rmtree(_torn_dir, ignore_errors=True)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d journal checks passed' % ok)
sys.exit(1 if bad else 0)
