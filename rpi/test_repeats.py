"""One card, one offer — and which of its readings to believe.

    python3 rpi/test_repeats.py

Every offer in this journal is read many times. The motion gate fires, the
accumulator collects the legs, and then the card just sits there being re-read
every few seconds until the driver decides. That is by design, and for most of
the project's life the extra readings cost nothing, because an identical reading
is dropped and a better one supersedes.

Then a real recording produced this, one Uber card in Chattanooga, seventy
seconds, four rows:

    19:50:37  $10.30   31 min   15.1 mi      $11.17/hr
    19:51:28  $1030    31 min   15.1 mi   $1,984.78/hr
    19:51:41  $10.30   40 min   23.6 mi       $4.83/hr
    19:51:47  $10.30   31 min   15.1 mi      $11.17/hr

Four offers, as far as anything downstream could tell — four rows in the export,
four points in the median, and one of them claiming two thousand dollars an
hour. There was one card.

Two mechanisms had to fail together for that. On the writing side, "the same
card again" meant an identical reading, which OCR defeats by its nature. On the
reading side, the last row of an id won, which is right when a reading improves
and wrong when it degrades — being last is not evidence of being right.

So this file checks both halves against that recording: that the rig writes one
offer, and that the reader picks $10.30/31min/15.1mi out of the four readings
whatever order they arrive in. The far end is the real server.js.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import journal as JR                                          # noqa: E402
import offer_parser as P                                      # noqa: E402
from accumulate import OfferAccumulator                       # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MONEY = {'target': 25, 'band': 15, 'costPerMile': 0.30}
ok = bad = 0


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


def fresh(name):
    path = os.path.join(work, name)
    if os.path.exists(path):
        os.remove(path)
    return JR.OfferLog(JR.Journal(path))


def feed(log, texts, start=1_700_000_000.0, step=20.0, acc=None):
    """Readings through the real accumulator, the real rate(), the real log."""
    acc = acc or OfferAccumulator()
    for i, text in enumerate(texts):
        parsed = acc.add(P.parse(text), now=start + i * step)
        whole = bool(parsed.get('complete')) and (
            bool(parsed.get('hasTotal')) or (parsed.get('legs') or 0) >= 2)
        log.consider(parsed, P.rate(parsed, MONEY), now=start + i * step,
                     whole=whole)
    return log.journal.rows()


# The Chattanooga card, as the camera actually read it. The second line is the
# decimal point lost; the third is the accumulator merging a stale leg into a
# fresh one, which is where 40 min and 23.6 mi come from.
GOOD = '$10.30 12 min (5.1 mi) away 19 min (10.0 mi) trip'
LOST_POINT = '$1030 12 min (5.1 mi) away 19 min (10.0 mi) trip'
BAD_MERGE = '$10.30 12 min (5.1 mi) away 28 min (18.5 mi) trip'

# =====================================================================
# The writing side: what the rig files.
# =====================================================================

rows = feed(fresh('chattanooga.jsonl'), [GOOD, LOST_POINT, BAD_MERGE, GOOD])
eq('the four readings that made four offers are one offer',
   len({r['id'] for r in rows}), 1)
eq('...with every reading still on disk', len(rows), 4)
ok_('...in order', [r['seq'] for r in rows] == [1, 2, 3, 4])
eq('...sharing one first-seen time', len({r['firstAt'] for r in rows}), 1)
eq('the impossible reading is still flagged', rows[1]['suspect'], True)
eq('...and says which figure is impossible', rows[1]['doubt'], 'pay')

# The check that keeps the fix honest: a genuinely different card, arriving
# well inside the ninety-second window, is still a second offer. Matching on
# payout would be worthless if it also swallowed the next ride.
rows = feed(fresh('two.jsonl'),
            [GOOD, GOOD, '$8.75 4 min (0.9 mi) away 16 min (5.2 mi) trip'])
eq('a different payout is still a different offer',
   len({r['id'] for r in rows}), 2)

# Same payout, but long enough later that it cannot be the same card on the
# same screen. Two $10.30 rides in an evening is ordinary.
log = fresh('window.jsonl')
feed(log, [GOOD, GOOD], start=1_700_000_000.0)
feed(log, [GOOD], start=1_700_000_000.0 + 200.0, acc=OfferAccumulator())
eq('the same payout past the window is a new offer',
   len({r['id'] for r in log.journal.rows()}), 2)

# An impossible reading is not an identity. If it were, the correct reading
# that follows would find nothing to attach to — which is exactly how the
# third row above became a third offer.
rows = feed(fresh('garbage-first.jsonl'), [LOST_POINT, GOOD, GOOD])
eq('a bad first reading does not fork the offer',
   len({r['id'] for r in rows}), 1)
eq('...and the good reading that follows is kept', rows[-1]['pay'], 10.30)

# Nor may it set the anchor for what comes next: a real card after an
# impossible one, at a different payout, is a different card.
rows = feed(fresh('garbage-then-other.jsonl'),
            [GOOD, GOOD, LOST_POINT, '$8.75 4 min (0.9 mi) away 16 min (5.2 mi) trip'])
eq('an impossible reading does not hide the next card',
   len({r['id'] for r in rows}), 2)

# A restart under a card whose last recorded reading was the impossible one.
# Adopting $1030 as the anchor would make the next correct reading a new offer,
# which is the same bug arriving by a different road.
path = os.path.join(work, 'resume.jsonl')
if os.path.exists(path):
    os.remove(path)
feed(JR.OfferLog(JR.Journal(path)), [GOOD, LOST_POINT])
back = JR.OfferLog(JR.Journal(path))
adopted = back.resume(now=1_700_000_030.0)
ok_('the restart adopts the card on screen', adopted is not None)
eq('...without believing its impossible payout', back.pay, None)
feed(back, [GOOD], start=1_700_000_040.0)
eq('...so the reading after the restart is the same offer',
   len({r['id'] for r in back.journal.rows()}), 1)

# The case the old rule existed for still holds: a reading that grows as the
# accumulator collects the second leg is one offer, not two.
rows = feed(fresh('grow.jsonl'),
            ['$10.30 12 min (5.1 mi) away', GOOD, GOOD], step=0.5)
eq('a reading that fills in is one offer', len({r['id'] for r in rows}), 1)
ok_('...and the partial reading is marked as partial', rows[0]['whole'] is False)
ok_('...while the finished one is not', rows[-1]['whole'] is True)

# =====================================================================
# The reading side: which of them the journal page shows.
# =====================================================================


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def reading(offer_id, seq, at, pay, minutes, miles, whole=True, suspect=False):
    """One row as the rig writes it, with only the fields the vote reads."""
    return {'v': 1, 'id': offer_id, 'seq': seq, 'at': at, 'firstAt': at,
            'pay': pay, 'minutes': minutes, 'miles': miles,
            'billedMinutes': minutes, 'perHour': round(pay / minutes * 60, 2),
            'grossPerHour': round(pay / minutes * 60, 2), 'perMile': 1.0,
            'cost': 0.0, 'state': 'no', 'target': 25, 'band': 15,
            'costPerMile': 0.3, 'legs': 2, 'hasTotal': False,
            'whole': whole, 'suspect': suspect}


if shutil.which('node') is None:
    print('no node on this machine — skipping the consensus checks')
else:
    served = os.path.join(work, 'served.jsonl')
    port = free_port()
    proc = subprocess.Popen(
        ['node', os.path.join(ROOT, 'server.js')],
        env=dict(os.environ, SCANNER='0', PORT=str(port), JOURNAL=served),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = 'http://127.0.0.1:%d' % port

    def write(rows):
        with open(served, 'w') as fh:
            for r in rows:
                fh.write(json.dumps(r) + '\n')

    def offers():
        body = urllib.request.urlopen(base + '/api/journal?days=0', timeout=5).read()
        return json.loads(body.decode('utf-8'))['offers']

    write([])
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen(base + '/api/status', timeout=1).read()
                break
            except Exception:
                time.sleep(0.1)
        else:
            raise RuntimeError('the server never came up')

        T = 1_700_000_000_000

        # The recording, in the order it happened. The majority answer is
        # 31 min / 15.1 mi, and the last row happens to agree — so this alone
        # would not distinguish the new rule from the old one.
        write([reading('c', 1, T, 10.30, 31, 15.1),
               reading('c', 2, T + 50_000, 1030.0, 31, 15.1, suspect=True),
               reading('c', 3, T + 63_000, 10.30, 40, 23.6),
               reading('c', 4, T + 70_000, 10.30, 31, 15.1)])
        got = offers()
        eq('four readings of one card are one offer', len(got), 1)
        eq('...at the payout three of them agree on', got[0]['pay'], 10.30)
        eq('...over the minutes three of them agree on', got[0]['minutes'], 31)
        eq('...and the distance', got[0]['miles'], 15.1)
        eq('...so the rate is the believable one', got[0]['perHour'], 19.94)

        # Now the one that does. Same four readings, bad merge arriving last:
        # taking the latest row would show a $4.83/hr ride that never existed.
        write([reading('c', 1, T, 10.30, 31, 15.1),
               reading('c', 2, T + 50_000, 1030.0, 31, 15.1, suspect=True),
               reading('c', 3, T + 63_000, 10.30, 31, 15.1),
               reading('c', 4, T + 70_000, 10.30, 40, 23.6)])
        got = offers()
        eq('a bad reading arriving last does not win', got[0]['minutes'], 31)
        eq('...on distance either', got[0]['miles'], 15.1)

        # An impossible reading loses even when it is the one that repeats.
        # Tesseract makes the same mistake twice quite happily.
        write([reading('c', 1, T, 1030.0, 31, 15.1, suspect=True),
               reading('c', 2, T + 5_000, 1030.0, 31, 15.1, suspect=True),
               reading('c', 3, T + 10_000, 10.30, 31, 15.1)])
        eq('a repeated impossible reading still loses', offers()[0]['pay'], 10.30)

        # Half a card is the same money over less time, which always reads
        # better than the offer was. It does not get to win on repetition.
        write([reading('c', 1, T, 10.30, 12, 5.1, whole=False),
               reading('c', 2, T + 3_000, 10.30, 12, 5.1, whole=False),
               reading('c', 3, T + 8_000, 10.30, 31, 15.1)])
        got = offers()
        eq('a repeated partial reading still loses', got[0]['minutes'], 31)
        ok_('...and the offer shown is a whole one', got[0]['whole'])

        # With nothing to choose between them, the later row wins — which is
        # the old behaviour, and the right one for a reading that improves.
        write([reading('c', 1, T, 10.30, 31, 15.1),
               dict(reading('c', 2, T + 4_000, 10.30, 31, 15.1), items=6.0,
                    billedMinutes=40.0, perHour=15.45)])
        got = offers()
        eq('a tie goes to the newer reading', got[0]['items'], 6.0)
        eq('...so a correction is still a correction', got[0]['billedMinutes'], 40.0)

        # One reading is one reading.
        write([reading('c', 1, T, 10.30, 31, 15.1)])
        eq('a single reading is left alone', offers()[0]['minutes'], 31)

        # Two cards, read messily, stay two cards.
        write([reading('a', 1, T, 10.30, 31, 15.1),
               reading('b', 1, T + 1_000, 8.75, 20, 6.1),
               reading('a', 2, T + 2_000, 10.30, 40, 23.6),
               reading('b', 2, T + 3_000, 8.75, 20, 6.1),
               reading('a', 3, T + 4_000, 10.30, 31, 15.1)])
        got = offers()
        eq('two cards are two offers', len(got), 2)
        by_id = {o['id']: o for o in got}
        eq('...each voted on its own readings', by_id['a']['minutes'], 31)
        eq('...and the other untouched', by_id['b']['pay'], 8.75)
        eq('...without the vote mixing them', by_id['b']['minutes'], 20)

        # A reading that lost the distance is not a reading that agrees about
        # it. `null == null` said it was, so two readings that missed the miles
        # out-voted the one that saw them — and rate() charges no mileage for a
        # distance it does not have, so the winner's $/hr was gross wearing
        # net's clothes, with no flag to say so.
        write([reading('c', 1, T, 12.45, 28, None),
               reading('c', 2, T + 4_000, 12.45, 28, 9.6),
               reading('c', 3, T + 8_000, 12.45, 28, None)])
        got = offers()
        eq('two readings that lost the distance do not outvote one that has it',
           got[0]['miles'], 9.6)

        # ...and with the distance-less reading arriving last, which is the case
        # the old later-wins tie-break decided the wrong way.
        write([reading('c', 1, T, 12.45, 28, 9.6),
               reading('c', 2, T + 4_000, 12.45, 28, None)])
        eq('...nor does one arriving last', offers()[0]['miles'], 9.6)

        # A card that genuinely has no distance is untouched: the penalty only
        # applies when some other reading of the same card saw one.
        write([reading('c', 1, T, 12.45, 28, None),
               reading('c', 2, T + 4_000, 12.45, 28, None)])
        got = offers()
        eq('a card with no distance at all is still one offer', len(got), 1)
        eq('...and is not made up', got[0]['miles'], None)

        # Every reading impossible is still an offer, not a hole. Two misreads
        # of one card both score about -993; the starting score used to be -1,
        # nothing cleared it, the vote returned nothing, and the annotation pass
        # then dereferenced that nothing — a 500 on /api/journal and a blank
        # page, because one card was misread twice.
        write([reading('c', 1, T, 1030.0, 31, 15.1, suspect=True),
               reading('c', 2, T + 4_000, 1030.0, 31, 15.1, suspect=True)])
        got = offers()
        eq('a card misread twice still comes back as an offer', len(got), 1)
        eq('...still flagged', got[0]['suspect'], True)

        # The same, mixed: nothing here is a good reading and it must still
        # answer.
        write([reading('c', 1, T, 1030.0, 31, 15.1, suspect=True),
               reading('c', 2, T + 4_000, 10.30, 12, 5.1, whole=False)])
        got = offers()
        eq('a suspect and a fragment still make one offer', len(got), 1)
        eq('...and the fragment beats the impossible one', got[0]['pay'], 10.30)

        # The vote must not disturb what a driver said about the offer. A mark
        # is keyed on the id, not on a reading, so it applies to whichever
        # reading wins.
        write([reading('c', 1, T, 10.30, 31, 15.1),
               reading('c', 2, T + 4_000, 10.30, 40, 23.6),
               reading('c', 3, T + 8_000, 10.30, 31, 15.1),
               {'v': 1, 'kind': 'mark', 'id': 'c', 'at': T + 60_000,
                'accepted': True}])
        got = offers()
        eq('a mark survives the vote', got[0]['accepted'], True)
        eq('...on the reading the vote chose', got[0]['minutes'], 31)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

shutil.rmtree(work, ignore_errors=True)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d repeat-reading checks passed' % ok)
sys.exit(1 if bad else 0)
