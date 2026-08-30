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

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d journal checks passed' % ok)
sys.exit(1 if bad else 0)
