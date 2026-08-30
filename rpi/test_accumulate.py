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
LEG_FIELDS = ('minutes', 'miles', 'isTotal', 'labelled')

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

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d accumulator checks passed' % ok)
sys.exit(1 if bad else 0)
