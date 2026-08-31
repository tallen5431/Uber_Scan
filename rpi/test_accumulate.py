"""Tests for merging readings across frames.

    python3 rpi/test_accumulate.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import offer_parser as P
from accumulate import OfferAccumulator

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


# --- the case from the road: one frame sees one leg, the next sees the other --
acc = OfferAccumulator()
first = acc.add(P.parse('$12.45 23 min (8.4 mi) trip'), now=100.0)
eq('single leg alone / minutes', first['minutes'], 23)
eq('single leg alone / miles', first['miles'], 8.4)

second = acc.add(P.parse('$12.45 5 min (1.2 mi) away 23 min (8.4 mi) trip'), now=101.0)
eq('both legs merged / minutes', second['minutes'], 28)
eq('both legs merged / miles', second['miles'], 9.6)
eq('both legs merged / count', second['legs'], 2)
# This frame saw both legs itself, so nothing was carried in for it.
eq('no growth when the frame saw it all', second['grew'], False)
eq('reports frames used', second['mergedFrom'], 2)

# The leg the first frame missed is retained even when a later frame loses it,
# and that frame is the one whose reading was genuinely extended.
third = acc.add(P.parse('$12.45 23 min (8.4 mi) trip'), now=102.0)
eq('retains the missed leg', third['minutes'], 28)
eq('reports growth for the frame that needed it', third['grew'], True)

# --- re-reading the same leg must not double it -----------------------------
acc = OfferAccumulator()
for t in range(4):
    merged = acc.add(P.parse('$7.09 34 min (3.6 mi) total'), now=200.0 + t)
eq('same leg four times / minutes', merged['minutes'], 34)
eq('same leg four times / miles', merged['miles'], 3.6)
eq('same leg four times / legs', merged['legs'], 1)
eq('did not claim growth', merged['grew'], False)

# --- a different offer must not inherit anything ----------------------------
acc = OfferAccumulator()
acc.add(P.parse('$12.45 5 min (1.2 mi) away 23 min (8.4 mi) trip'), now=300.0)
other = acc.add(P.parse('$4.50 8 min (2.0 mi) total'), now=301.0)
eq('new pay resets / minutes', other['minutes'], 8)
eq('new pay resets / miles', other['miles'], 2.0)
eq('new pay resets / frames', other['mergedFrom'], 1)

# --- and neither must a stale one, however identical the payout -------------
acc = OfferAccumulator(window=10.0)
acc.add(P.parse('$9.00 6 min (1.0 mi) away 20 min (5.0 mi) trip'), now=400.0)
later = acc.add(P.parse('$9.00 20 min (5.0 mi) trip'), now=460.0)
eq('expired window resets', later['minutes'], 20)
eq('expired window / frames', later['mergedFrom'], 1)

# --- disagreement on the same leg takes the popular, then the cautious ------
acc = OfferAccumulator()
acc.add(P.parse('$8.00 28 min (4.0 mi) trip'), now=500.0)
acc.add(P.parse('$8.00 23 min (4.0 mi) trip'), now=500.5)
merged = acc.add(P.parse('$8.00 23 min (4.0 mi) trip'), now=501.0)
eq('majority reading wins', merged['minutes'], 23)

# A tie is a coin toss, so it has to land on the side that costs nothing to be
# wrong about. This asserted the shorter time, on the reasoning that a shorter
# time flatters the offer less — which is backwards, because $/hr is pay over
# time: at $8.00, 23 minutes is $20.87/hr and 28 minutes is $17.14/hr, so the
# shorter reading is the *optimistic* one. It is also the corrupted one under
# the accumulator's own premise that OCR drops digits rather than adding them.
acc = OfferAccumulator()
acc.add(P.parse('$8.00 28 min (4.0 mi) trip'), now=600.0)
merged = acc.add(P.parse('$8.00 23 min (4.0 mi) trip'), now=600.5)
eq('tie takes the longer time, which is the cautious one', merged['minutes'], 28)

# The same tie in the distance, where the larger reading is cautious for the
# other reason: it is the one that charges full running costs.
acc = OfferAccumulator()
acc.add(P.parse('$8.00 23 min (8.0 mi) trip'), now=650.0)
merged = acc.add(P.parse('$8.00 23 min (3.0 mi) trip'), now=650.5)
eq('tie takes the longer distance', merged['miles'], 8.0)

# A majority still beats the tie-break in either direction — the caution is
# only ever the tiebreaker, never an override of what the frames actually saw.
acc = OfferAccumulator()
for t, when in (('$8.00 23 min (4.0 mi) trip', 660.0),
                ('$8.00 23 min (4.0 mi) trip', 660.5),
                ('$8.00 28 min (4.0 mi) trip', 661.0)):
    merged = acc.add(P.parse(t), now=when)
eq('a majority for the shorter time still wins', merged['minutes'], 23)

# --- a total still replaces the legs it summarises --------------------------
acc = OfferAccumulator()
acc.add(P.parse('$9.00 8 min (2.0 mi) to store 14 min (4.0 mi) to customer'), now=700.0)
merged = acc.add(P.parse('$9.00 22 min (6.0 mi) total'), now=700.5)
eq('total wins over merged legs', merged['minutes'], 22)
eq('total wins / miles', merged['miles'], 6.0)

# --- items survive a frame that loses them ----------------------------------
acc = OfferAccumulator()
acc.add(P.parse('$7.09 6 items (6 units) 34 min (3.6 mi) total'), now=800.0)
merged = acc.add(P.parse('$7.09 34 min (3.6 mi) total'), now=800.5)
eq('items retained', merged['items'], 6)

# --- nothing to key on passes straight through ------------------------------
acc = OfferAccumulator()
merged = acc.add(P.parse('blurry nonsense'), now=900.0)
eq('unkeyed passes through', merged['complete'], False)
eq('unkeyed merges nothing', merged['mergedFrom'], 0)

# --- a misread field must not become a leg of its own -----------------------
# From a real capture: one frame read "23 min (8.4 mi)" as "(3.4 mi)". Keyed by
# distance, that opened a third slot and a 28-minute offer reported 51 minutes
# for the rest of the window. 3.4 miles in 23 minutes is a believable 9 mph, so
# no plausibility guard can catch it — only knowing it is the same leg can.
acc = OfferAccumulator()
GOOD = '$12.45 5 min (1.2 mi) away 23 min (8.4 mi) trip'
acc.add(P.parse(GOOD), now=100.0)
acc.add(P.parse(GOOD), now=101.0)
misread = acc.add(P.parse('$12.45 5 min (1.2 mi) away 23 min (3.4 mi) trip'), now=102.0)
eq('a misread distance does not add a leg', misread['legs'], 2)
eq('...and is outvoted on distance', misread['miles'], 9.6)
eq('...leaving the time alone', misread['minutes'], 28)
after = acc.add(P.parse(GOOD), now=103.0)
eq('and it does not linger', after['minutes'], 28)

# The same in the other direction: the duration misread, the distance proving
# the two readings are one leg.
acc = OfferAccumulator()
acc.add(P.parse('$8.00 23 min (4.0 mi) trip'), now=200.0)
acc.add(P.parse('$8.00 23 min (4.0 mi) trip'), now=201.0)
merged = acc.add(P.parse('$8.00 28 min (4.0 mi) trip'), now=202.0)
eq('a misread duration does not add a leg either', merged['legs'], 1)
eq('...and is outvoted on time', merged['minutes'], 23)

# A card really listing two legs of the same duration keeps both, because
# within one frame they cannot be the same leg however alike they read.
acc = OfferAccumulator()
both = acc.add(P.parse('$9.00 5 min (1.2 mi) away 5 min (2.5 mi) trip'), now=300.0)
eq('equal durations in one frame stay two legs', both['legs'], 2)
eq('...and both count', both['minutes'], 10)
eq('...including their distances', both['miles'], 3.7)

# No frame of a real card lists more legs than the card has, so the union
# cannot exceed the most any single frame saw.
acc = OfferAccumulator()
acc.add(P.parse('$9.00 5 min (1.2 mi) away 20 min (6.0 mi) trip'), now=400.0)
acc.add(P.parse('$9.00 5 min (1.2 mi) away 20 min (6.0 mi) trip'), now=401.0)
odd = acc.add(P.parse('$9.00 5 min (1.2 mi) away 41 min (9.9 mi) trip'), now=402.0)
eq('the union never exceeds one frame\'s worth', odd['legs'], 2)
eq('...keeping the best-supported', odd['minutes'], 25)

# --- the merged result still rates correctly --------------------------------
acc = OfferAccumulator()
acc.add(P.parse('$12.45 23 min (8.4 mi) trip'), now=1000.0)
merged = acc.add(P.parse('$12.45 5 min (1.2 mi) away 23 min (8.4 mi) trip'), now=1000.5)
rate = P.rate(merged, {'target': 25, 'costPerMile': 0.30})
eq('merged rate uses both legs', round(rate['perHour'], 2), 20.51)
single = P.rate(P.parse('$12.45 23 min (8.4 mi) trip'), {'target': 25, 'costPerMile': 0.30})
eq('one leg alone flatters the offer', round(single['perHour'], 2) > round(rate['perHour'], 2), True)

# --- the item count is voted on, like everything else that moves money ------
# It used to take whichever frame happened to be last, so one misread outvoted
# every good reading before it purely by arriving after them. The count is not
# decoration: it buys shopping time. At 90s an item, "12 items" misread as "2"
# on the last frame of a $18.40 shop order took a 56-minute job to 41 minutes,
# and $17.75/hr PASS to $24.25/hr.
SHOPPING = {'target': 25, 'band': 15, 'costPerMile': 0.30, 'secondsPerItem': 90}
TWELVE = '$18.40 12 items (12 units) 38 min (6.1 mi) total'
MISREAD = '$18.40 2 items (2 units) 38 min (6.1 mi) total'
for label, order in (('misread last', [TWELVE, TWELVE, MISREAD]),
                     ('misread first', [MISREAD, TWELVE, TWELVE]),
                     ('misread in the middle', [TWELVE, MISREAD, TWELVE])):
    acc = OfferAccumulator()
    for i, text in enumerate(order):
        merged = acc.add(P.parse(text), now=800.0 + i * 0.5)
    eq('the majority item count wins, %s' % label, merged['items'], 12)
    eq('...so the rate is the true one, %s' % label,
       round(P.rate(merged, SHOPPING)['perHour'], 2), 17.75)

# A tie takes the larger count, for the same reason a tie in the minutes takes
# the longer time: more shopping is the cautious side of a coin toss.
acc = OfferAccumulator()
for i, text in enumerate([MISREAD, TWELVE]):
    merged = acc.add(P.parse(text), now=900.0 + i * 0.5)
eq('a tie in the item count takes the larger', merged['items'], 12)

# A frame that loses the count entirely must not erase one already seen.
acc = OfferAccumulator()
acc.add(P.parse(TWELVE), now=950.0)
merged = acc.add(P.parse('$18.40 38 min (6.1 mi) total'), now=950.5)
eq('a frame that misses the items keeps the count', merged['items'], 12)

# --- the merged distance is judged on its own, not on the last frame's -------
# The plausibility check runs inside parse(), on one frame's own numbers. The
# merge then replaces those numbers and used to keep the verdict, so a single
# frame that lost the leading digit of "23 min" — 8.4 miles in 8 minutes, 63mph,
# correctly flagged — left "distance unreadable" stuck to the merged 9.6 miles
# over 28 minutes, an ordinary 21 mph. rate() charges no mileage on a distance
# it does not trust, so the running cost silently vanished and a PASS was
# published as an ACCEPT.
GOOD = '$12.45 5 min (1.2 mi) away 23 min (8.4 mi) trip'
DIGIT_LOST = '$12.45 5 min (1.2 mi) away 3 min (8.4 mi) trip'
acc = OfferAccumulator()
for i, text in enumerate((GOOD, GOOD, DIGIT_LOST)):
    merged = acc.add(P.parse(text), now=1100.0 + i * 0.5)
eq('one bad frame is outvoted on the numbers', merged['minutes'], 28.0)
eq('...and its doubt does not outlive them', merged['milesUncertain'], False)
money = {'target': 25, 'band': 15, 'costPerMile': 0.30}
eq('so the mileage cost is still charged',
   round(P.rate(merged, money)['cost'], 2), 2.88)
eq('...and the verdict is the true one',
   P.rate(merged, money)['state'], P.rate(P.parse(GOOD), money)['state'])

# A merged distance that really is implausible must still be doubted.
acc = OfferAccumulator()
for i in range(2):
    merged = acc.add(P.parse('$12.45 4 min (40.0 mi) total'), now=1200.0 + i * 0.5)
eq('a merged sum that is genuinely mad is flagged', merged['milesUncertain'], True)

# --- a replacement card cannot wear the previous one's journey --------------
# The window keys on the payout, and identical payouts recur — minimum fares
# repeat to the cent. The replacement's legs match none of the stored slots, so
# they opened new ones, and the trim kept the best-supported slots, which are
# always the older card's. The new offer was reported *entirely* with the old
# one's time and distance: an 11-minute $63.65/hr job shown as a 28-minute
# $20.51/hr one. Worse, the contaminated merge reproduces the old signature
# exactly, so the loop stops resampling and never looks again.
REPLACEMENT = '$12.45 2 min (0.5 mi) away 9 min (2.1 mi) trip'
for gap, label in ((0.6, 'swapped fast'), (3.0, 'swapped after a pause')):
    acc = OfferAccumulator()
    acc.add(P.parse(GOOD), now=1300.0)
    acc.add(P.parse(GOOD), now=1300.5)
    merged = acc.add(P.parse(REPLACEMENT), now=1300.5 + gap)
    eq('%s / minutes are its own' % label, merged['minutes'], 11.0)
    eq('%s / miles are its own' % label, merged['miles'], 2.6)
    eq('%s / nothing inherited' % label, merged['mergedFrom'], 1)

# A late re-read of the SAME card is that card, not a new one. The motion gate
# fires once per card, so a second look is often seconds later — and the gap
# used to be tested on its own, before anything asked whether the frame lined up
# with what was already known. A frame that had lost the pickup leg to glare
# then became the whole answer: 28 minutes and 9.6 miles collapsed to 23 and
# 8.4, and a $20.51/hr PASS was published as $25.90/hr ACCEPT.
acc = OfferAccumulator()
acc.add(P.parse(GOOD), now=1340.0)
acc.add(P.parse(GOOD), now=1340.5)
merged = acc.add(P.parse('$12.45 23 min (8.4 mi) trip'), now=1343.0)
eq('a late re-read keeps the whole journey', merged['minutes'], 28.0)
eq('...and the whole distance', merged['miles'], 9.6)
eq('...and rates as the true one',
   round(P.rate(merged, money)['perHour'], 2), 20.51)

# ...and the cases that protects. A frame that finally catches a leg glare had
# been hiding also matches no stored slot, and must NOT be read as a new card.
acc = OfferAccumulator()
acc.add(P.parse('$12.45 23 min (8.4 mi) trip'), now=1400.0)
merged = acc.add(P.parse(GOOD), now=1400.5)
eq('a fuller frame still merges', merged['minutes'], 28.0)
eq('...and is not mistaken for a new card', merged['mergedFrom'], 2)

# The hardest version: each frame catches a *different* single leg, so neither
# lines up with what is on record. A leg count cannot separate this from a
# replacement card — both frames show one leg — which is why the test is
# whether the frame shows a whole journey, and a lone plain leg never does.
acc = OfferAccumulator()
acc.add(P.parse('$12.45 5 min (1.2 mi) away'), now=1500.0)
merged = acc.add(P.parse('$12.45 23 min (8.4 mi) trip'), now=1500.5)
eq('two different single legs are still one card', merged['mergedFrom'], 2)
# What it then reports is a separate matter, and unchanged by any of this: the
# union is capped at the most legs any single frame saw, which is one, so the
# second leg is trimmed back off. The cap is what stops a misread duration
# inventing a leg, and it cannot tell that case from this one. The loop does
# not act on the result — `whole` requires a total or two legs, so nothing is
# spoken and it keeps resampling until a frame sees the card entire.
eq('the union is still capped at one frame\'s worth', merged['legs'], 1)

# A card whose total line arrives after its legs matches no slot either, and
# resetting to it is harmless: a total is the whole journey by itself.
acc = OfferAccumulator()
acc.add(P.parse(GOOD), now=1600.0)
merged = acc.add(P.parse('$12.45 28 min (9.6 mi) total'), now=1600.5)
eq('a total that supersedes the legs still reads right', merged['minutes'], 28.0)
eq('...with the whole distance', merged['miles'], 9.6)

# --- a delivery card survives the merge ------------------------------------
# A DoorDash card states a deadline where an Uber card states a duration, and
# the parser is careful about that: "Deliver by 7:15 PM" makes a card complete
# without any minutes on it, because the deadline *is* the duration once
# something has told it the time.
#
# That rule was then written out a second time here, and the second copy had no
# deadline clause. So the card parsed complete, went through the accumulator,
# and came back incomplete — and rate() refuses an incomplete reading, so a
# whole shape of offer produced no verdict, no journal row and nothing on
# screen. The rule now lives in one function that both call.
DELIVERY = '$41.11 Guaranteed 9.8 mi Deliver by 7:15 PM Pickup Papa Johns'
parsed = P.parse(DELIVERY)
eq('a delivery card parses complete on its deadline', parsed['complete'], True)
eq('...with no minutes at all', parsed['minutes'], None)

acc = OfferAccumulator()
merged = acc.add(dict(parsed), now=1700.0)
eq('...and is still complete after the merge', merged['complete'], True)
eq('...keeping the deadline the completeness rests on', merged['deliverBy'], 1155)
eq('...and still no minutes', merged['minutes'], None)

# End to end: with a clock, that reading is judgeable. Without the fix above it
# was not, however many frames saw it.
judged = P.rate(merged, {'target': 25, 'costPerMile': 0.30,
                         'nowMinutes': 18 * 60 + 29})
eq('a merged delivery card can be judged', judged['ready'], True)
eq('...on minutes worked out from the deadline', judged['cardMinutes'], 46.0)
eq('...and says so', judged['fromDeadline'], True)

# Read twice, as it would be, it stays complete rather than degrading.
again = acc.add(P.parse(DELIVERY), now=1700.5)
eq('read again, still complete', again['complete'], True)
eq('...and still one card', again['mergedFrom'], 2)

# --- a leg's distance, once recovered, stays recovered ----------------------
#
# This is what merging across frames is *for*: one frame loses the trip
# distance, another catches it, and the window keeps the better answer. A leg
# with minutes and no distance makes the reading not whole, so the loop goes on
# resampling — and the whole point of that is the frame that fixes it.
#
# What must not happen is losing it again. `merged` starts life as a copy of the
# last frame's parse, so every summary field has to be rebuilt from the window
# or it describes one frame instead of the sum. `milesUncertain` was already
# rebuilt for exactly this reason, and `legDetail` was not — it did not matter
# until is_whole started reading it. Measured before the fix: a window correct
# at 8.4 miles and not uncertain went back to `whole: False` on the next
# damaged frame, so a card the rig had already read correctly stopped being
# spoken, kept being resampled, and reached the journal as a fragment — which
# keeps it out of every median on the offers page.
DAMAGED = '$16.05 3 min (1.1 mi) away 20 min (7.3 m1) trip'
CLEAN = '$16.05 3 min (1.1 mi) away 20 min (7.3 mi) trip'

acc = OfferAccumulator()
seen = []
for i, text in enumerate([DAMAGED, DAMAGED, CLEAN, DAMAGED, DAMAGED]):
    seen.append(acc.add(P.parse(text), now=1_700_000_000.0 + i * 0.5))

eq('a lost leg distance is short before it is found', seen[0]['miles'], 1.1)
eq('...and says so', seen[0]['milesUncertain'], True)
eq('...and is not whole', P.is_whole(seen[0]), False)

eq('one good frame recovers the distance', seen[2]['miles'], 8.4)
eq('...and clears the doubt', seen[2]['milesUncertain'], False)
eq('...and makes the reading whole', P.is_whole(seen[2]), True)

for i in (3, 4):
    eq('a later bad frame does not lose it again (frame %d)' % (i + 1),
       seen[i]['miles'], 8.4)
    eq('...nor re-raise the doubt (frame %d)' % (i + 1),
       seen[i]['milesUncertain'], False)
    eq('...nor un-whole a finished reading (frame %d)' % (i + 1),
       P.is_whole(seen[i]), True)

# The legs the summary is made of describe the window, not whichever frame
# arrived last — which is the thing that went wrong.
eq('the merged legs are the window\'s', len(seen[4]['legDetail']), 2)
eq('...with the distance the window found',
   sorted(l['miles'] for l in seen[4]['legDetail']), [1.1, 7.3])

# --- an address one frame saw is not lost to the frame after it -------------
#
# The address sits at the edge of the crop, in small type, over a map — which
# is exactly the field a single frame drops. `merged = dict(parsed)` took the
# last frame's, so one frame losing it lost it for the offer.
WITH = ('UberX $12.45 5 min (1.2 mi) away Chastain Rd NW, Kennesaw '
        '23 min (8.4 mi) trip Canton Rd, Marietta')
WITHOUT = '$12.45 5 min (1.2 mi) away 23 min (8.4 mi) trip'

eq('the card names two places', P.parse(WITH)['places'],
   ['Chastain Rd NW, Kennesaw', 'Canton Rd, Marietta'])
eq('...and the frame that lost the map names none', P.parse(WITHOUT)['places'], [])

acc = OfferAccumulator()
acc.add(P.parse(WITH), now=600.0)
after = acc.add(P.parse(WITHOUT), now=600.5)
eq('a frame that missed the address does not erase it',
   after['places'], ['Chastain Rd NW, Kennesaw', 'Canton Rd, Marietta'])

# ...and the other way round, which is the commoner order: the first look
# misses the map and a later one catches it.
acc = OfferAccumulator()
acc.add(P.parse(WITHOUT), now=700.0)
later = acc.add(P.parse(WITH), now=700.5)
eq('...and an address found late still arrives',
   later['places'], ['Chastain Rd NW, Kennesaw', 'Canton Rd, Marietta'])

# A different card is a different window, so nothing carries over. Two offers
# paying different amounts are never one offer.
acc = OfferAccumulator()
acc.add(P.parse(WITH), now=800.0)
other = acc.add(P.parse('$19.06 5 min (1.2 mi) away 23 min (8.4 mi) trip'),
                now=800.5)
eq('the next card does not inherit the last one\'s address', other['places'], [])

# One address read twice is one address. A union on exact strings keeps both —
# and the offers page joins places with an arrow, so a card whose pickup was
# read once with a comma and once without is rendered as a two-stop route that
# never happened. That is worse than the missing address the union fixes, and
# the last-frame behaviour it replaced could not produce it.
WITH_COMMA = '$12.45 5 min (1.2 mi) away Cobb Pkwy NW, Acworth 23 min (8.4 mi) trip'
NO_COMMA = '$12.45 5 min (1.2 mi) away Cobb Pkwy NW Acworth 23 min (8.4 mi) trip'
eq('the two frames really do read it differently',
   P.parse(WITH_COMMA)['places'] == P.parse(NO_COMMA)['places'], False)
acc = OfferAccumulator()
acc.add(P.parse(WITH_COMMA), now=900.0)
twice = acc.add(P.parse(NO_COMMA), now=900.5)
eq('one address read two ways stays one address', len(twice['places']), 1)
eq('...and the fuller reading is the one kept',
   twice['places'], ['Cobb Pkwy NW, Acworth'])

# ...and the other direction, which is the whole risk of merging at all: the
# two genuinely different ends of a card must survive as two.
acc = OfferAccumulator()
ends = acc.add(P.parse('$12.45 5 min (1.2 mi) away Chastain Rd NW, Kennesaw '
                       '23 min (8.4 mi) trip Canton Rd, Marietta'), now=950.0)
eq('the two ends of a real card are still two places', len(ends['places']), 2)

# Same street, different town is a different place. It is the nearest thing to a
# hard case for the test above and it must come down on this side of it.
acc = OfferAccumulator()
acc.add(P.parse('$12.45 5 min (1.2 mi) away Cobb Pkwy NW, Acworth 23 min (8.4 mi) trip'),
        now=960.0)
towns = acc.add(P.parse('$12.45 5 min (1.2 mi) away Cobb Pkwy NW, Kennesaw '
                        '23 min (8.4 mi) trip'), now=960.5)
eq('the same street in two towns is two places', len(towns['places']), 2)

# Never more than one card's worth, however many frames read the map. Four
# frames, four genuinely different corners.
acc = OfferAccumulator()
CORNERS = ('Chastain Rd NW, Kennesaw', 'Canton Rd, Marietta',
           'Airport Rd NW, Kennesaw', 'Post Woods Dr, Atlanta',
           'Dallas Hwy, Marietta')
for i, corner in enumerate(CORNERS):
    many = acc.add(P.parse('$12.45 5 min (1.2 mi) away %s 23 min (8.4 mi) trip'
                           % corner), now=900.0 + i * 0.5)
eq('five corners do not become five places on a card that holds four',
   len(many['places']), 4)

# --- what a leg has to carry, all the way through -------------------------
#
# `labelled` says the card called this a leg of the journey, and is_whole
# re-runs legs_short_a_distance over whatever it is given. So the field has to
# survive three hops: parse() builds the legs, legDetail projects them, and this
# merger rebuilds them across frames. It was dropped at the second and third on
# the way in, and each time the rule did not fail loudly — it simply stopped
# seeing any leg as labelled, so a card whose distance read as "7.3 m1" called
# itself whole again.
#
# Asserted as a property of the hop rather than as three separate cases,
# because the next field added to a leg will take the same trip.
LEG_FIELDS = ('minutes', 'miles', 'isTotal', 'labelled', 'lostMiles')

acc_fields = OfferAccumulator()
for _i in range(2):
    _m = acc_fields.add(P.parse('$16.05 5 min (1.1 mi) away 18 min (7.3 mi) trip'))
_detail = _m.get('legDetail') or []
eq('the merger returns the legs it was given', len(_detail) >= 2, True)
for _f in LEG_FIELDS:
    eq('...each carrying %s through the merge' % _f,
       [_f in l for l in _detail], [True] * len(_detail))

# ...and a raw parse projects the same set, so the two shapes is_whole is asked
# about cannot disagree about what a leg is.
_raw = (P.parse('$16.05 5 min (1.1 mi) away 18 min (7.3 mi) trip')['legDetail'] or [])
for _f in LEG_FIELDS:
    eq('a raw reading projects %s too' % _f,
       [_f in l for l in _raw], [True] * len(_raw))

# The property that matters, end to end: a distance lost in one frame is not
# whole, whether it is asked of the raw reading or of the merged one.
_broken = '$16.05 3 min (1.1 mi) away 20 min (7.3 m1) trip'
eq('a leg whose distance did not read is not whole, raw',
   P.is_whole(P.parse(_broken)), False)
acc_broken = OfferAccumulator()
_mb = None
for _i in range(2):
    _mb = acc_broken.add(P.parse(_broken))
eq('...nor once it has been merged across frames', P.is_whole(_mb), False)

# --- one card is one offer, for as long as it is on screen -----------------
#
# The window used to be measured from the FIRST reading, so it expired while the
# driver was still looking at the card and the same offer was filed again. On
# this driver's journal 90 cards were filed more than once — 104 surplus rows,
# 7.6% of it, each counted again in every median. A burst is bounded by silence,
# which is what QUIET already says; the window now closes after `window` seconds
# of nothing.
CARD = ("$12.99 Guaranteed (incl. tips) 7.7 mi + 28 min "
        "@ Pickup Dave's Hot Chicken f\u00a5 Customer dropoff")
OTHER = ("$12.99 Guaranteed (incl. tips) 3.1 mi + 11 min "
         "@ Pickup Chipotle f\u00a5 Customer dropoff")


def _episodes(frames, step=3.0, start=1000.0):
    """Feed frames as the rig would and count the offers that get filed."""
    box = OfferAccumulator()
    seen, last = [], None
    for i, (text, when) in enumerate(frames):
        last = box.add(P.parse(text), now=when if when is not None
                       else start + i * step)
        seen.append(box.episode)
    return len(set(seen)), last


_n, _m = _episodes([(CARD, None)] * 40)
eq('a card on screen for two minutes is one offer', _n, 1)
eq('...built from every frame of it', _m.get('mergedFrom'), 40)

# A frame misreading the minutes used to line up with no slot, which made it a
# replacement card. The distance now on the leg is the second signal that keeps
# it attached — see LEG in offer_parser.py.
_wobble = ([(CARD, None), (CARD.replace('28 min', '26 min'), None)]
           + [(CARD, None)] * 6
           + [(CARD.replace('28 min', '2B min'), None)]
           + [(CARD, None)] * 7)
_n, _m = _episodes(_wobble)
eq('a frame that misreads the minutes does not start a new offer', _n, 1)
eq('...and the misreadings are outvoted', _m.get('minutes'), 28.0)
eq('...leaving the distance alone', _m.get('miles'), 7.7)

# The distance is voted on too, now that it rides on the leg. Before that it
# was whatever the last frame said: a delivery card read 7.9, 7.9, 1.9, 7.9 and
# 79 published the wrong number in 48 of 120 arrival orders.
GOPUFF = ("$15.60 Guaranteed (incl. tips) 7.9 mi + 37 min "
          "@ Retail pickup GoPuff (Drive)")
_n, _m = _episodes([(GOPUFF, None), (GOPUFF, None),
                    (GOPUFF.replace('7.9 mi', '1.9 mi'), None),
                    (GOPUFF, None),
                    (GOPUFF.replace('7.9 mi', '79 mi'), None)])
eq('a delivery card whose distance wobbles is still one offer', _n, 1)
eq('...and the distance is the one most frames read', _m.get('miles'), 7.9)
eq('...not the one the last frame happened to read', _m.get('mergedFrom'), 5)

# A leg that lost its minutes is dropped whole, taking its distance with it, so
# the reading is not finished — and one frame that reads the card properly is
# what finishes it. ANDed across the window rather than ORed, unlike everything
# else here, and taken from the last frame before that.
_LOST = ("Exclusive x $9.05 * 5.00 min (44 mi) . Gresham Rd "
         "Avg. wait time at pickup: 1 min 9 mins (2.6 mi) Sedgefield Rd")
_READ = ("Exclusive x $9.05 * 12 min (4.4 mi) . Gresham Rd "
         "Avg. wait time at pickup: 1 min 9 mins (2.6 mi) Sedgefield Rd")

_n, _m = _episodes([(_LOST, None)] * 3)
eq('every frame short a time leaves the reading unfinished',
   _m.get('shortATime'), True)
eq('...so it is not whole', P.is_whole(_m), False)

_n, _m = _episodes([(_LOST, None), (_READ, None), (_LOST, None)])
eq('one frame that read the card clears it', _m.get('shortATime'), False)
eq('...even though a later frame lost the leg again', P.is_whole(_m), True)
eq('...and the merged journey has both legs', _m.get('miles'), 7.0)
eq('...and the time the lost leg was hiding', _m.get('minutes'), 22.0)

_n, _m = _episodes([(_LOST, None), (_LOST, None), (_READ, None)])
eq('...whichever order the good frame arrives in', _m.get('shortATime'), False)

# --- the distance's own two markers describe the merge, not the last frame ---
#
# `milesChecked` and `milesHadDecimal` are not numbers, they are the two things
# rate() consults before it decides whether the distance may be divided by ten.
# Both came out of `dict(parsed)` — the frame that happened to arrive last — so
# on a card with no stated duration the answer moved with frame order and
# nothing else. Neither is a fact about a frame: one describes the merged
# minutes, the other the merged distance.
#
# `_orders` asserts the property rather than a case, because the defect IS the
# order dependence: every arrival order of the same frames has to agree.
def _perms(items):
    if len(items) <= 1:
        return [tuple(items)]
    out = []
    for i, item in enumerate(items):
        for rest in _perms(items[:i] + items[i + 1:]):
            out.append((item,) + rest)
    return out


def _agree(name, frames, keys, want):
    """Assert every distinct arrival order of `frames` merges to the same thing.

    Permuted by position rather than by text, so a card fed to it twice is fed
    to it twice and the label says which frame went where.
    """
    for order in sorted(set(_perms(tuple(range(len(frames)))))):
        box = OfferAccumulator()
        last = None
        for i, at in enumerate(order):
            last = box.add(P.parse(frames[at]), now=3000.0 + i * 0.5)
        eq('%s [%s]' % (name, ''.join(str(at) for at in order)),
           dict((k, last.get(k)) for k in keys), want)


# The commonest card this driver is shown. "20 min" is a minutes-only leg and
# the "2.4 mi" four characters away belongs to it, so a frame that reads the
# card whole has a duration beside its distance. A frame that loses the "+ 20
# min" half to glare does not, and reports milesChecked False.
W_hole = "$7.20 Guaranteed (incl. tips) 2.4 mi + 20 min @ Pickup McDonald's"
H_alf = "$7.20 Guaranteed (incl. tips) 24 mi @ Pickup McDonald's"

MARKERS = ('minutes', 'miles', 'milesChecked', 'milesHadDecimal')

# One frame that read the duration is enough, in any position — and a lone 24
# read by two frames does not touch a distance the legs already carry.
_agree('a duration one frame read is a duration the merge has',
       [W_hole, H_alf, H_alf], MARKERS,
       {'minutes': 20.0, 'miles': 2.4,
        'milesChecked': True, 'milesHadDecimal': True})
_agree('...and two of them do not make it any more true',
       [W_hole, W_hole, H_alf], MARKERS,
       {'minutes': 20.0, 'miles': 2.4,
        'milesChecked': True, 'milesHadDecimal': True})

# ...and when no frame ever read one, the merge says so, which is what leaves
# rate() free to check the distance against the deadline instead.
_agree('a card no frame timed is not checked', [H_alf, H_alf, H_alf], MARKERS,
       {'minutes': None, 'miles': 24.0,
        'milesChecked': False, 'milesHadDecimal': False})

# Where the distance came off the legs the flag decides nothing — a leg carries
# its own minutes, so milesChecked is True and rate() never asks — but it is
# written to the journal and read by a person, so it still has to say what the
# card printed rather than something convenient. ORed there, like hasTotal: one
# frame seeing the point is enough, and losing it is what a glare frame does.
_BARE = '$16.05 5 min (1 mi) away 18 min (7 mi) trip'
_POINT = '$16.05 5 min (1.1 mi) away 18 min (7 mi) trip'
eq('a card can print no decimal point at all',
   P.parse(_BARE)['milesHadDecimal'], False)

_agree('...and the merge does not invent one', [_BARE, _BARE, _BARE],
       ('miles', 'milesHadDecimal', 'milesChecked'),
       {'miles': 8.0, 'milesHadDecimal': False, 'milesChecked': True})
# The distance itself is still voted on, so the outvoted "1.1" does not move
# the sum — but the point it printed is remembered, which is the whole
# difference between this field and the number beside it.
_agree('...nor lose the one frame that saw it', [_BARE, _BARE, _POINT],
       ('miles', 'milesHadDecimal', 'milesChecked'),
       {'miles': 8.0, 'milesHadDecimal': True, 'milesChecked': True})

# The lone distance — the one no leg claimed — is voted on like the minutes and
# the items. It used to be whichever frame arrived last, and there is no leg
# duration beside it for check_distance to catch a misread with.
GOOD_LONE = '$18.55 Add a delivery (+2.4 mi) Deliver by 7:15 PM'
LOST_LONE = '$18.55 Add a delivery (+24 mi) Deliver by 7:15 PM'
eq('the two readings really do differ',
   (P.parse(GOOD_LONE)['miles'], P.parse(LOST_LONE)['miles']), (2.4, 24.0))
eq('...and disagree about the decimal point too',
   (P.parse(GOOD_LONE)['milesHadDecimal'],
    P.parse(LOST_LONE)['milesHadDecimal']), (True, False))

_agree('the popular lone reading wins', [GOOD_LONE, GOOD_LONE, LOST_LONE],
       ('miles', 'milesHadDecimal'), {'miles': 2.4, 'milesHadDecimal': True})

# And the case the pairing exists for. When the misreading is the popular one
# the published distance is 24, and the decimal point must NOT be ORed in from
# the single frame that saw it: that flag is what forbids recovering 24 back to
# 2.4, so an OR would use one frame's evidence of the error to block the fix for
# it. Asked of the winning reading's own frames it comes out False, and rate()
# recovers the distance against the deadline.
_agree('a decimal point does not survive the reading that carried it',
       [GOOD_LONE, LOST_LONE, LOST_LONE],
       ('miles', 'milesHadDecimal'), {'miles': 24.0, 'milesHadDecimal': False})

# ...and the other direction, which is what a blanket "never OR" would break: a
# card that really says 24.0, read once as 24, still forbids the recovery.
REAL_LONE = '$18.55 Add a delivery (+24.0 mi) Deliver by 7:15 PM'
_agree('a card that really says 24.0 keeps its point',
       [REAL_LONE, REAL_LONE, LOST_LONE],
       ('miles', 'milesHadDecimal'), {'miles': 24.0, 'milesHadDecimal': True})

# What all of that is spent on. Twenty minutes to the deadline makes 24 miles a
# 72 mph delivery and 2.4 miles a 7.2 mph one, so the two cards are told apart
# by the money and not by a flag.
_CFG = {'target': 25.0, 'costPerMile': 0.30, 'pad': 0,
        'nowMinutes': 18 * 60 + 55}


def _rate(frames):
    box = OfferAccumulator()
    last = None
    for i, text in enumerate(frames):
        last = box.add(P.parse(text), now=3100.0 + i * 0.5)
    return P.rate(last, _CFG)


eq('a 2.4 mile job is rated as one, however the point read',
   round(_rate([GOOD_LONE, LOST_LONE, LOST_LONE])['perHour'], 2), 53.49)
eq('...and so is the same card read right',
   round(_rate([GOOD_LONE, GOOD_LONE, LOST_LONE])['perHour'], 2), 53.49)
eq('...while a card that really is 24 miles is charged for them',
   round(_rate([REAL_LONE, REAL_LONE, LOST_LONE])['perHour'], 2), 34.05)

# What must still separate two offers, and does not depend on the clock.
_n, _ = _episodes([(CARD, 1000.0), (CARD, 1003.0), (CARD, 1006.0),
                   (OTHER, 1600.0), (OTHER, 1603.0)])
eq('a different card with the same payout, ten minutes later, is a new offer',
   _n, 2)
_n, _ = _episodes([(CARD, 1000.0), (CARD, 1003.0), (CARD, 1006.0),
                   (OTHER, 1012.0), (OTHER, 1015.0)])
eq('...and so is one that replaces it straight away', _n, 2)

# Silence is what ends a window, so the same card seen again much later is a
# second offer rather than a continuation of the first.
_n, _ = _episodes([(CARD, 1000.0), (CARD, 1003.0),
                   (CARD, 9000.0), (CARD, 9003.0)])
eq('the same card an hour later is a second offer', _n, 2)

# --- a leg that lost its distance says so, all the way through the merge ----
#
# This driver's ride cards label a leg with an ADDRESS, not with `away` or
# `trip`, so a leg that loses its distance drops out of the set
# legs_short_a_distance counts and the rule cannot fire. `lostMiles` is the
# third clause that fixes it — a bracket sitting where the distance should be —
# and it takes the same three hops `labelled` does, which is why it is in
# LEG_FIELDS above. Here it is asserted through the merge, in both directions.
_ADDR_HURT = ('$21.08 5 min (1.8 mi) Grace St & Main St, Kennesaw '
              '12 min (8.1 m1) Oak Ln, Marietta')
_ADDR_OK = ('$21.08 5 min (1.8 mi) Grace St & Main St, Kennesaw '
            '12 min (8.1 mi) Oak Ln, Marietta')

eq('a damaged address card is not whole on its own',
   P.is_whole(P.parse(_ADDR_HURT)), False)

# The flag is about a leg that LOST a distance, so a leg that has one never
# claims it. Nothing in the rule depends on that — a leg with miles is already
# part of the journey — but the field is projected into legDetail and written to
# the journal, where it is read as a statement about the card. A field that says
# "a distance here did not read" beside a distance that did is a lie in a file
# somebody will one day measure from.
#
# A real card off this driver's shift does exactly this: a stray bracket
# between a leg's distance and the address after it. Thirteen legs across the
# clean and damaged corpora sit like that, and every one of them has its
# distance.
_STRAY = ('| Exclusive x le a ; $10.04 *% 497 @ Verified 16 min (6.6 mi) ; '
          '( Roswell Rd, Atlanta Avg. wait time at pickup: 1 min } 18 mins '
          '(10.2 mi) ¢ Dunwoody Xing, Atlanta 4, 7 mi from fast charger')
eq('a stray bracket after a leg that has its distance claims nothing',
   [l.get('lostMiles') for l in P.parse(_STRAY)['legDetail']],
   [False, False, False])
eq('...and the card is read whole', P.is_whole(P.parse(_STRAY)), True)
eq('...with both legs in the journey', P.parse(_STRAY)['miles'], 16.8)

eq('a leg that read its distance does not claim to have lost one',
   [l.get('lostMiles') for l in P.parse(_ADDR_OK)['legDetail']],
   [False, False])
_n, _m = _episodes([(_ADDR_OK, None)] * 3)
eq('...and merging three good frames does not invent one',
   [l.get('lostMiles') for l in _m['legDetail']], [False, False])
# ...including the frame where the bracket really is sitting there unread, once
# another frame has supplied the distance the merge now carries.
_n, _m = _episodes([(_ADDR_HURT, None), (_ADDR_OK, None)])
eq('...nor keep one after the distance arrives', P.is_whole(_m), True)

_n, _m = _episodes([(_ADDR_HURT, None)] * 3)
eq('...nor once three frames of it have been merged', P.is_whole(_m), False)
eq('...and the merged leg still says its distance was there',
   [l.get('lostMiles') for l in _m['legDetail']], [False, True])
eq('...so the reading is doubted rather than published short',
   _m['milesUncertain'], True)

# One frame that read the distance settles it, in either order — the same
# property the rest of the merge keeps, and the reason the loop goes on
# sampling a reading that is not whole.
_n, _m = _episodes([(_ADDR_HURT, None), (_ADDR_OK, None), (_ADDR_HURT, None)])
eq('one frame that read the distance makes it whole', P.is_whole(_m), True)
eq('...with both legs\' distance in the sum', _m['miles'], 9.9)
_n, _m = _episodes([(_ADDR_HURT, None), (_ADDR_HURT, None), (_ADDR_OK, None)])
eq('...whichever order that frame arrives in', P.is_whole(_m), True)

# And the line that is not a leg stays not a leg. A pickup wait has a bracket
# in its tail too — belonging to the leg after it — so the bracket has to be
# the FIRST thing after the minutes or this card stops being whole.
_WAIT = ('Exclusive x $9.05 12 min (4.4 mi) Gresham Rd '
         'Avg. wait time at pickup: 1 min 9 mins (2.6 mi) Sedgefield Rd')
_n, _m = _episodes([(_WAIT, None)] * 3)
eq('a pickup wait between two good legs is still whole', P.is_whole(_m), True)
eq('...and nothing about it is doubted', _m['milesUncertain'], False)
eq('...and no leg of it claims a lost distance',
   [l.get('lostMiles') for l in _m['legDetail']], [False, False, False])

# And the case that decides the anchor's shape. Loosen it from "no word
# character before the bracket" to "any three characters" and this card breaks:
# the leg after the wait line has lost its `mins`, leaving " 9 (2.6 mi)", so the
# bracket falls within three characters of the WAIT LINE's minutes and the wait
# line becomes a leg of the journey. The reading is damaged either way — the
# mirror rule catches it, a distance with no time — but the wait line is still
# not a leg, and a rule that decides it is has stopped answering the question it
# was written for.
_WAIT_HURT = ('Exclusive x $9.05 12 min (4.4 mi) Gresham Rd '
              'Avg. wait time at pickup: 1 min 9 (2.6 mi) Sedgefield Rd')
_hurtp = P.parse(_WAIT_HURT)
eq('a wait line is not a leg even when the next leg lost its unit',
   [l.get('lostMiles') for l in _hurtp['legDetail']], [False, False])
eq('...so the distance that did read is not doubted',
   _hurtp['milesUncertain'], False)
eq('...and the card is unfinished for the reason that is true of it',
   (P.is_whole(_hurtp), _hurtp['shortATime']), (False, True))

# --- four things an adversarial review found in this merge -----------------
#
# Every one reproduced exactly as reported, and every one published a wrong
# number on the driving screen.

# 1. A card with NO LEGS could never be seen as a replacement. The deadline
# delivery card states no duration and no legs, so nothing could line up or fail
# to line up, and a genuinely different offer paying the same to the cent inside
# the stale window merged into the old episode - published with the old card's
# distance AND the old card's deadline, and never filed at all because
# `episode` did not move.
_C1 = '$18.55 Add a delivery (+2.4 mi) Deliver by 7:15 PM'
_C2 = '$18.55 Add a delivery (+8.0 mi) Deliver by 7:40 PM'
acc = OfferAccumulator()
for _i in range(3):
    _m = acc.add(P.parse(_C1), now=9000.0 + _i * 0.5)
eq('the first deadline card reads as itself', (_m['miles'], _m['deliverBy']),
   (2.4, 1155))
_first = _m['episode']
_m = acc.add(P.parse(_C2), now=9004.5)
eq('a different deadline card is a different card', _m['episode'] != _first, True)
eq('...and says so, which is how the journal files it', _m['newCard'], True)
eq('...carrying its own distance', _m['miles'], 8.0)
eq('...and its own deadline', _m['deliverBy'], 1180)

# ...but ONE field differing is what OCR does all day, and both the deadline and
# the lone distance are voted on for exactly that reason. A frame that misreads
# one of them must not throw the window away.
for _bad, _name in (('$18.55 Add a delivery (+2.4 mi) Deliver by 7:45 PM',
                     'a misread deadline'),
                    ('$18.55 Add a delivery (+8.0 mi) Deliver by 7:15 PM',
                     'a misread distance')):
    acc = OfferAccumulator()
    for _i in range(3):
        _m = acc.add(P.parse(_C1), now=9100.0 + _i * 0.5)
    _was = _m['episode']
    _m = acc.add(P.parse(_bad), now=9104.5)
    eq('%s alone is not a new card' % _name, _m['episode'], _was)

# 2. A frame that loses the TOTAL line was declared a replacement card. A card
# printing legs and a total parses to the total alone, so a later frame that
# loses that line reports two ordinary legs, they line up with nothing, and
# "two legs means a whole journey" reset the window mid-burst - on a frame that
# is the same card read slightly worse.
_T = ('$9.00 8 min (2.0 mi) to store 14 min (4.0 mi) to customer '
      '22 min (6.0 mi) total')
_NOTOTAL = '$9.00 8 min (2.0 mi) to store 14 min (4.q mi) to customer'
acc = OfferAccumulator()
for _i, _t in enumerate([_T, _T, _NOTOTAL]):
    _m = acc.add(P.parse(_t), now=9200.0 + _i * 0.5)
eq('losing the total line does not start a new offer', _m['newCard'], False)
eq('...and the journey the good frames read is kept', _m['miles'], 6.0)
eq('...along with its time', _m['minutes'], 22.0)

# 3. One damaged frame poisoned a wait-line slot for the life of the offer.
# `lostMiles` is one frame's claim about damage, not a fact about the card, and
# ORing it stamped a slot that never gains a distance: a pickup-wait line whose
# tail begins with the NEXT leg's bracket once that leg is truncated away.
_GOOD = ('Exclusive x $9.05 12 min (4.4 mi) Gresham Rd '
         'Avg. wait time at pickup: 1 min 18 mins (2.6 mi) Sedgefield Rd')
_CUT = ('Exclusive x $9.05 12 min (4.4 mi) Gresham Rd '
        'Avg. wait time at pickup: 1 min (2.6 m')
acc = OfferAccumulator()
for _i, _t in enumerate([_GOOD, _CUT, _GOOD, _GOOD]):
    _m = acc.add(P.parse(_t), now=9300.0 + _i * 0.5)
eq('one truncated frame does not poison the card', _m['milesUncertain'], False)
eq('...and the reading is still finished', P.is_whole(_m), True)
eq('...with the journey the good frames read', (_m['minutes'], _m['miles']),
   (31.0, 7.0))

# ...and a leg that really did lose its distance in most frames still says so.
_HURT = ('$21.08 5 min (1.8 mi) Grace St & Main St, Kennesaw '
         '12 min (8.1 m1) Oak Ln, Marietta')
acc = OfferAccumulator()
for _i in range(3):
    _m = acc.add(P.parse(_HURT), now=9400.0 + _i * 0.5)
eq('a leg damaged in every frame is still doubted', _m['milesUncertain'], True)

# ...and MOST frames is enough, which is the difference between a majority and
# a unanimity and the reason this is the former. A leg whose distance is
# mangled in two frames of three and simply absent in the third is a leg the
# card printed a distance for; requiring every frame to agree would let one
# clean-looking frame excuse the damage the others saw.
_MANGLED = ('$21.08 5 min (1.8 mi) Grace St & Main St, Kennesaw '
            '12 min (8.1 m1) Oak Ln, Marietta')
_ABSENT = ('$21.08 5 min (1.8 mi) Grace St & Main St, Kennesaw '
           '12 min Oak Ln, Marietta')
acc = OfferAccumulator()
for _i, _t in enumerate([_MANGLED, _MANGLED, _ABSENT]):
    _m = acc.add(P.parse(_t), now=9450.0 + _i * 0.5)
eq('damaged in two frames of three still counts',
   [l['lostMiles'] for l in _m['legDetail']], [False, True])
eq('...so the reading is doubted', _m['milesUncertain'], True)

# ...and a single frame's claim, outvoted, is not enough - the other half of
# the same rule, and the case the pickup-wait line above is a real instance of.
acc = OfferAccumulator()
for _i, _t in enumerate([_MANGLED, _ABSENT, _ABSENT]):
    _m = acc.add(P.parse(_t), now=9460.0 + _i * 0.5)
eq('one frame of three is outvoted',
   [l['lostMiles'] for l in _m['legDetail']], [False, False])

# 4. The lone-distance vote elected the decimal-dropped reading. One token read
# twice arrives as two numbers - the frame that also caught the duration has had
# its point put back, the frame that lost both reports the raw ten-times value -
# and a tie breaks towards the larger. `milesChecked` was then True, because the
# minutes came from the good frame, so rate() never re-checked it either.
_A = '$16.05 Add a delivery (+2.4 mi) 21 min'
_B = '$16.05 Add a delivery (+24 mi)'
for _order, _name in (([_A, _B], 'good then damaged'),
                      ([_B, _A], 'damaged then good'),
                      ([_A, _A, _B, _B], 'two of each')):
    acc = OfferAccumulator()
    for _i, _t in enumerate(_order):
        _m = acc.add(P.parse(_t), now=9500.0 + _i * 0.5)
    eq('a lost point does not win the lone vote [%s]' % _name, _m['miles'], 2.4)

# The fold that was NOT used, and why. Judging the winner against the time is
# check_distance's job and is already tuned for it; folding a ten-times reading
# back on sight is wrong in the other direction - a card that really says 24
# miles, misread once as "2.4", would fold to 2.4 and publish a green accept on
# a job with ten times the driving.
_REAL = '$16.05 Add a delivery (+24 mi) 55 min'
_SLIP = '$16.05 Add a delivery (+2.4 mi) 55 min'
acc = OfferAccumulator()
for _i, _t in enumerate([_REAL, _REAL, _SLIP]):
    _m = acc.add(P.parse(_t), now=9600.0 + _i * 0.5)
eq('a real long trip is not folded away by one slipped point',
   _m['miles'], 24.0)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d accumulator checks passed' % ok)
sys.exit(1 if bad else 0)
