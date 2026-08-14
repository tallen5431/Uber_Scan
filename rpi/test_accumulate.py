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

acc = OfferAccumulator()
acc.add(P.parse('$8.00 28 min (4.0 mi) trip'), now=600.0)
merged = acc.add(P.parse('$8.00 23 min (4.0 mi) trip'), now=600.5)
eq('tie takes the shorter time', merged['minutes'], 23)

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

# --- the merged result still rates correctly --------------------------------
acc = OfferAccumulator()
acc.add(P.parse('$12.45 23 min (8.4 mi) trip'), now=1000.0)
merged = acc.add(P.parse('$12.45 5 min (1.2 mi) away 23 min (8.4 mi) trip'), now=1000.5)
rate = P.rate(merged, {'target': 25, 'costPerMile': 0.30})
eq('merged rate uses both legs', round(rate['perHour'], 2), 20.51)
single = P.rate(P.parse('$12.45 23 min (8.4 mi) trip'), {'target': 25, 'costPerMile': 0.30})
eq('one leg alone flatters the offer', round(single['perHour'], 2) > round(rate['perHour'], 2), True)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d accumulator checks passed' % ok)
sys.exit(1 if bad else 0)
