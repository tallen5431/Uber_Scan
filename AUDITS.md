# What has already been looked at

This file exists so the same ground is not dug twice. It records three things
and the middle one is the point:

1. **Done** — what was found and fixed, with the commit that did it.
2. **Settled** — proposals that were made, checked against the code, and found
   to be *wrong*. Re-proposing one of these costs a day. Each says why it died.
3. **Open** — findings that survived checking and are genuinely not done. These
   are known. Finding one again is not a discovery.

Everything below was checked against the real code rather than argued from the
outside, and the measurements are from a box roughly 5–8× faster than a Pi 4
unless they say otherwise. Where a decision has a home in the source, the
reasoning lives there too and this file only points at it.

---

## Done — found, fixed, and tested against being undone

Listed so the same fault is not reported as news, and so the shape of the fix
is findable. Every one of these is mutation-tested: the old behaviour is put
back mechanically and a named check has to fail.

### The reader

**Which end a name is was still being decided by the order the FRAMES
arrived, one layer below where that was fixed.** `place_ends` fixed the
parser's half and this entry is the rest of it. `merged['places']` is a union
appended as frames contribute; `find_dropoff`'s rule is "the last place the
card named", which is a true statement about ONE frame's list and a guess
about a union. So a name one late frame invented sat after the name every
earlier frame had read, and won for no better reason than arriving last.

The earlier entry's "After: 1 of 1,166" is not wrong, but it measures one
thing: rows whose merged label the card's own LAYOUT contradicts. `place_ends`
is silent on nine cards in ten, and where it says nothing that figure has
nothing to say either.

*Measured against what the frames themselves read.* Of the 269 rows where
every frame that named a destination named the same one, the merge published
something else on **21**: 9 a different place entirely, 8 a dirtier reading of
the right one, and 4 no destination at all. The journal holds, as destinations,
`N I Fried Rice Master y vis` and `rey i e ae Wy Popeyes Louisiana Chicken
(159 ey i Cobb Pkwy` on cards where every frame agreed on a real street. This
is the one field the append-only journal cannot repair afterwards.

*The fix counts the frames' own answers instead of re-reading the union.* Each
frame's `find_pickup`/`find_dropoff` already ran on that frame's own list,
where "the last place the card named" is true. `merge_place` already returns
the index it merged to — it was given that return value so a second list could
be kept in step, which is how `place_ends` works — so the tally is kept by the
same index and the fuzzy half of the join is not done twice.

**The union is untouched.** It exists because an address is the field a single
frame loses, and one frame seeing it has to be enough — which it still is,
because a lone vote is a unique winner. What the count removes is only the case
where frames disagreed and the last to arrive won.

*Two clauses decide when the count does NOT speak, and both are measured.*

  - **The card's own layout outranks it, where the layout settles the
    question.** Row 18 is why: seven frames read only the trip leg and call its
    one place the pickup, because it is the only one they have; the eighth
    reads the whole card and its layout says the other name is the start. Seven
    votes to one, and the one is right. Without this clause the count
    contradicts the card's layout on 2 more starts than the rule it replaced —
    it would hand back the row `place_ends` was written for.
  - **...but only where it settles it.** Two names both marked "the end" is two
    frames disagreeing about that end, not a card with two destinations, and
    the union's order is what picks between them today. So the gate is "the
    card names exactly one", not "names any" — the same distinction
    `_CONTRADICTED` draws one name at a time. A split count says nothing
    either, and defers rather than letting a dict's iteration order decide.

*What it does to the week.* 109 rows move, 30 pickups and 79 dropoffs, and
**no other field moves at all**. Agreement with the frames' own unanimous
verdict goes from 248 of 269 to **261**: a different place 9 to 1, lost 4 to 1,
dirtier 8 to 6. Against the card's layout — the metric the previous fix was
measured on — the numbers are **identical to before**, 107 starts and 101 ends
right, 12 and 18 wrong. 0 destinations lost, 4 gained. The 6 remaining
"dirtier" are `merge_place` keeping the longer of two readings, which is its
own deliberate rule and not this one.

Eight mutations, each dying to a named check: the layout clause removed, the
count silenced, a tie picking arbitrarily, each gate loosened to "names any",
each tally never counted, and the least-voted winning.


**Sixty minutes vanished from a card whose hour read as a letter, and the
ledger believed this fault already closed.** `l hr 10 min` was fixed long ago:
the hours group takes digit lookalikes, and `find_legs` refuses a leg whose
hour matched but carries no real digit. `DC` — the lookalike class — stops
short of `T` on purpose, because "letters like G and T are corrected inside a
confirmed number but are too risky to match on", which is right. The
consequence was not seen: when OCR renders `1hr` as **`Thr`**, the hours group
matches NOTHING, the scan starts at the minutes instead, and the guard never
runs at all — it is gated on that group having matched. The leg then looks
perfectly clean: no label, no total, one leg, so `is_whole` calls the reading
finished and `doubt()` sees an ordinary pay over ordinary minutes. The rig
stops resampling, speaks it, and files it.

21 legs across the owner's 5,491 frames say an hour this way, always in one
card shape — `3.8 mi + Thr 21min @ Pickup` — and always glued. 0 of the
corpus's 314 texts had it, so nothing existing moves.

*What it did to the journal, measured by replaying the real accumulator both
ways.* **Two rows of 1,166 change, and they change differently:**

  - **Row 736 is repaired, not merely refused.** Five of its six frames read
    `Thr 21min`; frame 1 read `1hr21min`. The majority won, so `minutes: 21`
    and `perHour: 42.46` are what the journal holds — against the card's real
    1 hr 21 min, **$11.85/hr**. Refusing the five damaged votes lets the frame
    that read it correctly win, which is exactly what "so the next frame
    supplies it" was supposed to mean.
  - **Row 790 has no reading at all now, and that is the right answer.** Its
    minutes never read on any frame: two say `1hrttmin`, one says `Thr 11min`.
    The journal holds `minutes: 11, perHour: 105.22` — a green ACCEPT at
    **$120.27/hr** on a card of at least 71 minutes. No verdict beats that one.

Rows 625, 881 and 961 carry damaged frames too and do not move: the guard
drops their bad votes and consensus was already right without them. Row 699
moves only on the glass — its first frame read 20 minutes and showed a green
$61.05/hr before consensus corrected it to 80; that frame is now refused.

*A first version of this fix was wrong in a way worth recording, because it is
a shape that would recur.* The rule looks back at the text before the match for
an hour word, anchored at the end. Written `$`, it behaves differently in the
two ports — Python's `$` ALSO matches just before a trailing newline and
JavaScript's does not — so Python refused a leg JavaScript kept. `\Z` is exact
in both. It was caught by testing the boundary the rule was written to draw,
and the comment that first explained the anchor was itself wrong: it claimed an
hour word on the line above belongs to another line of the card, when
`normalize()` has already turned the newlines into spaces before `find_legs`
is ever called. The anchor still matters for callers that have not normalized;
the reason given for it did not survive being checked.

Four corpus cases, each carrying a pay so that `complete: false` is caused by
the minutes and not by a card with no money on it — the first draft of them
asserted a refusal that would have held whatever the parser did. Five mutations
across both ports, each dying to a named case: the guard removed, bare `hr`
dropped from the unit list, and the gap between unit and minutes closed up.


**An approach leg that no other frame saw was published as a distance — and
the entry describing this fault had the wrong row, the wrong numbers and the
wrong cause.** Open said `check_distance` is asked of the card and never of a
leg, so "one absurd leg passes inside a believable card", and gave row 659:
`1 min (3.8 mi)`, 228 mph, inside a card reading 12.4 mi over 17 min. Replayed
through the real accumulator over the real frames, every part of that is wrong.

  - **Row 659 is not a fault at all.** It arrives on eight frames. Three read
    the approach as `1 min`, five read `11 min`, and `_consensus` takes the
    majority — so the rig records `toPickupMinutes: 11.0` over 3.8 mi, 21 mph,
    which is right. The 228 mph exists only in a single-frame `parse()`, the
    instrument this file already warns about under the bracket fix.
  - **The card's own figures were wrong too**: 27 min and 12.4 mi, not 17.
  - **0 cards in 1,166 hide an absurd leg inside a believable total**, which
    is precisely the mechanism the entry claimed. 1 leg of the week's 102
    approach legs is over `UNREADABLE_MPH`, and the card around it reads
    135.8 mph, so `milesUncertain` was already true there.

*The real fault is narrower and has a different cause.* Row 18 arrives on eight
frames. **One** reads `1 min (46.0 mi)`; the other seven see no approach leg at
all. `isApproach` is ORed across a window rather than voted on — deliberately,
so a glare frame cannot lose a leg the card really printed — so a leg one frame
in eight invented survives the merge, and the rig publishes `toPickupMiles:
46.0` for a job whose entire trip is 10.6 miles. `milesUncertain` covers the
total; nothing covered that number.

*Nothing on the glass reads it, and that is worth writing down because the
obvious guess is wrong.* `MV.detour` — the "+N mi out of your way" line — is
crow-flies arithmetic over two geocoded pins and never touches these fields.
`rpi/journal.py` records them; `tools/measure_places.js` is the only thing that
computes from them. A wrong number in the journal, not on the panel.

*Fixed by a fourth refusal in `to_pickup`*, where the docstring already
promises to refuse rather than guess, and which is the one rule that decides —
so word-labelled cards are covered by the same clause as laid-out ones. The
threshold is `UNREADABLE_MPH` and not `MAX_MPH` because the corpus had already
settled that argument in a case named "a plausible short leg is left alone,
however fast it rounds to": 2 min over 2.0 mi is 60 mph and real, because leg
times are whole minutes and too coarse to argue with.

*The stated reason for deferring it was wrong as well.* Open said a guard here
"would move corpus cases and needs its own pass". It moves **0 of the corpus's
32 approach cards** and **1 of the real week's 102** — row 18, and nothing
else. Three cases pin it: 74 mph kept, 78 mph refused inside a card that reads
25.8 mph and is believed (the shape the old entry described, which the week
does not contain), and row 18's own `1 min (46.0 mi)`. Five mutations across
both ports, each dying to a named case.

*What it costs, stated rather than buried.* `tools/measure_places.js` subtracts
`toPickupMiles` from the card total to get the road between two places, and on
row 18 the two errors were cancelling: 56.6 − 46.0 = 10.6, which is right. With
the leg refused that sample becomes 56.6 mi and is marked inexact, so it drops
out of `exactSpread`. One sample of the week, on a card `milesUncertain`
already condemned, which was only ever right by coincidence and could not be
known to be.

*Not done here, and worth knowing first.* The phantom leg is still in the
card's SUM, and `milesUncertain` on a total makes `rate()` charge no mileage at
all — which `check_distance`'s own comment calls "the one direction that turns
a PASS into an ACCEPT". Taking an impossible leg out of the sum is a different
rule: it moves the verdict rather than a label, and whether a leg is phantom or
merely mis-timed cannot be told at the sum.


**The two ends of a job were taken off the two ends of a list that is in the
order the FRAMES arrived, not the order of the journey.** `merged['places']` is
appended as each frame contributes, `find_pickup` took `places[0]` and
`find_dropoff` the last — so a window whose later frame supplied the pickup
recorded it after the dropoff and the ends came out swapped.

Measured by replaying the real accumulator over the real frames and asking, per
place, which leg the CARD printed it against — the `whose` list `find_places`
already builds. **10 of 1,166 rows had a merged label the card's own layout
contradicts**, in three shapes: ends swapped (18, 113, 298, 659), the
destination replaced by a second reading of the pickup's own street (213, 811,
812), and one name that the card put at the far end (307, 1149). The tenth,
321, is refused on purpose — its first line states minutes and no distance, so
it is not the layout at all. Row 18 prints `min (46 mi)` / `Cobb Pkwy NW,
Acworth` / `24 mins (10.6 mi)` / `Canton Rd, Marietta`, and the rig recorded
the two ends the wrong way round, ten miles apart.

Not only a label: `live.html` publishes "+N mi out of your way" off this card's
`pickup`, `advice.js` decides stacking off `dropoff`, and `badEnd` only fires
for a geocode far from the CAR, so a real street ten miles from the right one
passed silently.

The card already states which end is which — by where it prints the name — and
`find_places` already recorded it. The fix gives that fact back rather than
touching `MAX_PLACES` or the last-entry rule: `place_ends` reads the order,
`parse()` emits it as `placeEnds`, the accumulator keeps it in step with
`places` (a name two frames put at two different ends is damage, not a vote, so
it refuses), and the two `find_*` scans are NARROWED by it — every existing
guard still runs over what remains. `two_leg_layout` is the shared predicate
both rules ask, so they cannot drift about what the layout is.

**After: 1 of 1,166, which is the deliberate refusal.** Row 18 reads
`Cobb Pkwy NW, Acworth → Canton Rd, Marietta`; row 307 recovers
`Burnap St & Rose Ln, Marietta`, the destination that was being dropped from
the middle of the list. Through the real accumulator **9 rows move and the only
fields that move on any of them are `pickup` and `dropoff` — 0 rows where a
field the panel shows moves**, 0 approach splits gained or lost, and 0
disagreements between the ports over all 1,166 texts.

*Two branches no input could reach were deleted with it, and one that looked
dead was put back.* `laid_out_approach`'s dropoff clause: after the narrowing,
`find_dropoff` can only return a place at the second leg or at no leg, and the
second cannot happen because such a place came off the `Pickup` anchor and
`_labelled_pickup` always matches it in a single-frame parse. Instrumented over
1,476 real and corpus texts: reached 110 times, saw `1` every time. Deleting it
moves 0 rows. The accumulator's `place_ends` fallback likewise — `_merged` is
only reached after every place has been merged in. And `leg_travels(legs[0])`,
deleted hours earlier as subsumed by the approach rule's distance guard, is
live again: `place_ends` publishes no number and has no such guard, so there it
is the only thing between a wait line and being read as where the job starts.
**A branch is dead only with respect to its callers**, and that one grew a
second.

**A frame holding two cards priced one and described the other.** `one_card()`
bounded the legs and nothing else, so the distance, deadline, item count and
merchant went on reading the whole frame while the payout took the largest.
30 of this driver's 272 cards arrive on such a frame. Fixed in `ae510ce` by
`card_span`/`only_card` in both ports; the measurement is at the foot of this
file.

**A glare frame threw away a verdict the rig already had.** `collect()` took
the last frame of the batch whether or not it carried a payout. `read_the_money`
now picks the newest frame that states one and folds the rest in. `123fa02`.

**The card's own border was read as a divider, so a merchant was cut in half
and its tail welded onto the destination.** A branch address is bracketed and
wraps across two lines; the crop takes the card's border with it and the reader
returns it as a pipe at the head of the continuation line. `find_places` split
on the first pipe unconditionally, so `Hooters (Old 41 Hwy NW & N | Roberts
Rd)` became a pickup of `Hooters (Old 41 Hwy NW & N` and a dropoff beginning
`Roberts Rd)`. Measured on the owner's week — **48 of 580 stored dropoffs
(8.3%) and 21 of 1,107 pickups carry an unmatched `)`**, and on 41 of the 48
the text before the stray bracket is a substring of that same card's own
pickup, so it is the merchant's name and not a coincidence of shape. Three
changes, mirrored in both ports: `_divider_bar` ignores a pipe standing between
a `(` and its `)`; `_cut_at_tail` replaces `PLACE_TAIL.split(...)[0]`, which
cannot tell a border from a divider because split does not say where the match
was; and `_closes_what_it_never_opened` refuses a place carrying half a bracket
outright, because nothing can say where the seam was. Re-parsing all 1,166 real
texts: **poisoned places 51 → 0, dropoffs named 476 → 500**, pickups unchanged
at 1,080, and **0 disagreements between the Python and JavaScript ports before
or after**. The bracket must CLOSE — without that clause a `(` the camera made
out of sludge disarms the stopper for the rest of the line — and the refusal is
one-directional: making it symmetrical costs 29 of the 500 dropoffs and 8 of
the 1,080 pickups, all clean addresses. Four cases in the shared corpus's
`places` section; every clause dies to a mutation, including the one that
passes before and after, which exists so nobody reads this as "a pipe never
divides".

*The cost, stated rather than buried — and the first version of this paragraph
was wrong.* Seven rows lose their dropoff **to a single-frame parse**. Four had
a poisoned one (`'Hedgeway Cir & Hedgeway Ct ,) tt Kennesaw'`) and are the
fault being fixed. The other three were named here as rows 2, 434 and 822,
recording a destination as a pickup. **They do not.** All three come out right
on the rig, because the rig writes the MERGED reading and `self.places` is a
union across the window: another frame read the merchant with its bracket
closed, so row 2 is `Culver's (2460 Kennesaw Due West x NS Rd)` →
`Cumberland Creek Trl SW…`, and 434 and 822 likewise. The measurement behind
the original claim was `parse()` on one stored text, which is the right
instrument for what the PARSER does and the wrong one for what the RIG
records. Checked by replaying the real accumulator over the real frames.

The lesson is the one this session kept repaying: a single-frame number
describes the parser, and every claim about what reaches the journal has to go
through `OfferAccumulator` first.

*Rows already in the journal are not repaired by this and cannot be.* It stops
the 48-a-week from growing. The 69 poisoned strings already written are there
for good, and `places.json` holds a geocode for some of them.

**The card stated the drive to the pickup and the parser could only read the
word for it.** `to_pickup()` requires a leg matching `APPROACH_TAIL =
/\baway\b/`, and the word appears on **0 of the owner's 1,166 offers** — so a
feature with tests, a CSV column and a consumer in `tools/measure_places.js`
produced nothing on a week of driving. The split is not absent from the cards:
110 print it as a LAYOUT — a leg, the place it arrives at, a leg, the place
THAT one arrives at — and `find_places` already walks the legs in order and
knows which one each place sat against. It threw the index away at the
`return`. `find_places(text, legs, whose)` now fills it in, the same shape
`find_pay(text, _where)` already uses so the two answers cannot disagree, and
`laid_out_approach` reads the order and sets the same flag `away` would have
set — so `to_pickup` stays the one rule that decides, and the flag travels to
the accumulator, which ORs it across the window exactly as it already ORs a
lost "away".

*Not by size.* On the two-leg cards the first leg is the shorter one only 62%
of the time, so taking the smaller would be a guess dressed as a reading and
every fourth one would be wrong. That mutation fails five named corpus checks.

*Measured through the REAL accumulator over the REAL frame sequences of all
1,166 offers.* **103 rows gain a split (8.8%), and the only fields that move on
any of them are `toPickupMinutes` and `toPickupMiles` — 0 rows where anything
the panel shows moves.** 0 disagreements between the Python and JavaScript
ports, before or after, over every field. The approach is a median 35% of the
card's stated miles. `tools/measure_places.js legs()` goes from 0 exact samples
to **41 of its 47 samples at town grain (87%) and 58 of 64 at town+quadrant
(91%)** — run here against the merged rows, not quoted.

*The `isTotal` refusal was a branch no check could reach.* Its only observable
effect is on `legDetail[].isApproach` — `to_pickup` refuses those cards either
way — and the shared corpus cannot carry it, because `tests/corpus.test.js`
compares a `parse` expectation with `got === want`, which is false for every
list. So it is hand-written twice, once per port, and `rpi/test_lint.py` holds
the two cards in step and now also refuses any `parse` or `rate` expectation
that is a list, since such a case passes in Python and fails in JavaScript for
every input.

*The cap widened, and the first account of it here was wrong.* `_within_caps`
keeps a cap per kind, so the window's effective total is `max_approach +
max_other`. While `isApproach` came only from the word, `max_approach` was
always 0 and the sum was one cap. This entry first said the widening was real
but that "this week does not exercise it" — true of the week, and false about
the risk. A code review of the commit found it reachable with **three ordinary
frames**: two clean readings of a $12.45 ride card and one that lost the
dropoff merged to **57.0 min / 13.0 mi on a card that is 28.0 / 9.6**, so
**$19.5/hr published as $8.3/hr**, `complete`, not uncertain, with nothing on
the glass saying why. The worst thing this project can do, introduced by the
commit that read the layout.

Closed two ways, both needed. The kinds are counted by the **slot** each leg
landed in rather than by the flag its frame carried — a frame whose crop cut
off the dropoff makes `laid_out_approach` refuse, so it reported both its legs
as the other kind and raised that kind's ceiling for the whole window. And the
caps are **recomputed over every frame** instead of raised as a running
maximum, because a window often learns which leg is the approach from its
second frame and a maximum taken once keeps the first frame's answer for good.
Replaying all 1,166 real windows, the count whose caps sum above the most legs
one frame saw goes **7 → 0**, and the merged reading still moves only in
`toPickupMinutes` and `toPickupMiles`. `rpi/test_accumulate.py` checks every
frame ordering — the running-maximum mutation is caught only by the one with
the glare frame FIRST — and the halves case the per-kind split exists for.

*And the cure had an unbounded list in it.* `frame_slots`, which the recompute
walks, kept one entry per FRAME — and a window does not roll over while the
card is still being read, because `stale` is measured from the last add. At
`RESAMPLE_EVERY` (0.5s) that is two entries a second for as long as the driver
looks at the card. Measured on one ordinary two-leg card: a minute on screen
gives 120 entries, ten minutes 1,200, an hour **7,200 — of which exactly one
is distinct**, every time, because the frames of a card land in the same slots.
Unbounded memory and an unbounded loop, per frame, on the Pi that is also
relaying the live picture. A set is exact here, since a maximum over a multiset
is the maximum over its set, and it holds one entry after an hour.

*A pickup-wait line sits exactly where the approach goes — twice.* The card prints
`Avg. wait time at pickup: 3 min` first, above the merchant, which is the
layout slot the drive to the pickup occupies — so it was published as the
approach: three minutes, no distance, nothing marked uncertain.
`legs_short_a_distance` already had the test for "a line that travels", inline;
it is now `leg_travels`/`legTravels`, written once and asked by both, because
two copies of that rule is the third fault class.

*"A `toPickup` corpus case pins it in both ports" is what this said, and it
stopped being true two commits later.* Adding the stricter distance guard below
subsumed `leg_travels` for the leg being published — a line failing
`leg_travels` has no distance, no label and no lost distance, so it fails the
stronger test too — and mutating the whole clause out then left all 810 python
and 766 shared-corpus checks green. Half of it was a branch no input could
reach and is deleted; the other half, the test on the SECOND line, is live and
reachable (a wait line printed BETWEEN the merchant and the customer) and now
has a case of its own. Both halves die to a named mutation. Worth recording
because the claim was true when written and was falsified by a later commit of
the same evening — a check does not stay pinned just because it once was.

That was not enough, and a second review found why. `leg_travels` accepts a
leg on `lostMiles` — a distance printed beside it that did not read — which is
right where it asks whether a card is MISSING a distance and wrong where a
number gets published off the answer. One frame whose merchant name fails to
read leaves the tail after `3 min` beginning with the bracket of the line
below, `LEG_LOST_MILES` fires, and the wait line looks like a leg. The
accumulator ORs `isApproach` across the window, so **one such frame in five
stamps the whole card**: measured on [clean, damaged, clean, clean, clean],
the merged row carried `toPickupMinutes: 3.0` for a card stating no split at
all, and that is what the journal writes and `tools/measure_places.js` reads as
geography. `rpi/accumulate.py` already refuses to trust one frame's
`lostMiles` — it counts `lostSeen` and votes, and says why. So
`laid_out_approach` now requires the leg it PUBLISHES to state its distance,
which is stricter than `leg_travels` on purpose. It costs 2 of the 93 firing
cards and both were already useless: a split with no distance gives a null
`toPickupMiles`, the one field `legs()` needs, and it marks such a sample
`exact: false`.

*And the loss line's present tense outlived what it described.* The `dropped`
clause was cured of exactly this and the `lost` clause beside it was left
alone: `refused` is monotonic, so "this phone will not keep them" stayed on
the glass after the rig answered, the flush drained the queue and every
`keep()` landed again. A full store is a recoverable state, not a permanent
one. `trouble()` now carries `refusing`, the last `keep()`'s own answer, which
clears — the present-tense warning is shown only while it is present tense,
and the count of what has already gone is stated as the past fact it is.

### The order in the car

**A destination scanned while SCREENING lost its provenance the moment the card
went in the car.** The ⌖ Dropoff button works before the accept as well as
after, and before is the ordinary use — an offer card usually prints "Customer
dropoff" and no address, so tapping it open is how a driver finds out where a
job goes *before* taking it. The card carried `dropoffScanned`; the object built
when it was accepted copied the address and left the flag behind.

Not a display detail. `recordPairing` writes `scanned` into the append-only
journal off that field, and the header above it says that field *is* "the
difference the ⌖ Dropoff button exists to make". So every pair judged against an
order screened this way recorded the wrong answer to the one question it was
there to answer, and a journal row cannot be corrected afterwards. Measured
against the real server: the card read `dropoffScanned: true`, the held order
read `false`, the address identical.

**A wider guard here was proposed and refused, twice.** The sweep suggested
refusing an unprompted address whenever a rival card had been read recently, on
the theory that a screening tap could be misfiled onto the held job. Measured,
the guard discards the *held job's own* destination on the ordinary busy-shift
sequence. The hazard it defends against also cannot occur on an ordinary
screening tap: `rpi/scan_pi.py` already refuses every address off a frame
carrying a payout or a merchant.

**Why that loss is permanent, which is the part worth not re-deriving.** It is
not bounded by the two-minute screening window, as the proposal assumed.
`dropoff_said` has exactly two assignments in `rpi/scan_pi.py` — `None` at loop
start, and the line it is set to on emit — and the comment above it says so
itself: "never cleared — there is no moment in this loop that means a new job
began". So a held job's own address refused once by such a guard is never
volunteered again for that delivery. The only rescue is a ⌖ press, because the
suppression is `not asked`. The guard would trade a class-1 fault for a class-2
one on a path whose firing rate nobody has measured.

**That measurement is now being taken.** The reader's `addressAsOffer` /
`streetNoAddress` counters could never settle it: they measure the FRAME — was
there a payout on it, a street with no address — and the question is about
ATTRIBUTION, which only `server.js` can see, because only it knows what is in
the car and what is on the slot at the same moment.

So `server.js` writes one `kind: 'sighting'` row per unprompted address that
arrives while an order is carried. It changes no behaviour. The row carries the
held order's id, the id of the card on the slot if it is recent enough to be
what the driver is looking at (`screeningCard`, else null), and whether the
address was filed. **No address is on the row** — it is a tally, not a record
of where anybody lives, and the journal syncs to a second machine.

Cheap by construction: the reader emits an address only off a frame with no
payout and no merchant, and suppresses a repeat of a line it has already said,
so this is roughly once per distinct address seen rather than once per frame.

After a few real shifts, read it with:

    node -e '
    var fs = require("fs");
    var s = fs.readFileSync(process.argv[1], "utf8").split("\n").filter(Boolean)
      .map(function (l) { try { return JSON.parse(l); } catch (e) { return null; } })
      .filter(function (r) { return r && r.kind === "sighting"; });
    var rival = s.filter(function (r) { return r.slot && r.slot !== r.held; });
    console.log("unprompted addresses seen with an order in the car:", s.length);
    console.log("  ...with a different card on the slot:", rival.length);
    console.log("  ...filed onto the held order:",
                rival.filter(function (r) { return r.kept; }).length);
    console.log("  ...discarded:",
                rival.filter(function (r) { return !r.kept; }).length);
    ' rpi/journal.jsonl

`slot !== held` with `kept` true is the population the guard would have been
for: a screening tap that may have been filed onto the wrong job. If that count
is near zero the guard must never be written. `kept` false is the other half —
the tap discarded because the held order already knew where it was going —
which sizes the Open entry below about the ⌖ button.

### The maps, again

**The map could not be asked WHEN, so it showed two different maps stacked.**
`journal.html` already buckets every offer by hour and by weekday; `map.html`
had only a day count. On the owner's week that meant one map of 1,166 offers
in which the 3-6pm map (Kennesaw/Marietta/Acworth, $13.52) and the 12-3am map
(78% Atlanta, $18.26) read as one place — and AUDITS had already measured that
this makes about a third of "Atlanta pays more" really "late night pays more".

A `when` box of the same eight three-hour blocks the offer log's chart uses.
Picking one narrows the pins, the trail, the sidebar counts and the walk
itself, and the status line says **how many separate days are behind the
answer**, which is what stops one night being read as a habit. It also cuts
the first walk: 1,325 places at 1.1s is 24.3 minutes for the whole window
against 3.9-9.5 for a block.

*Three faults were introduced by the first version of this and caught before
it landed, all reachable by the flow it advertises.* The nag under the box
counted `missing` against every offer while `placed` can only hold offers that
named somewhere, so a complete walk still read "N not yet" for ever and
pressing Place could not move it — 58 of the owner's 1,166 rows name neither
end. And widening the box **without pressing Place again** left the window
spanning jobs the last walk never looked up: `hidden` means "the box is hiding
it", which is false at "any time", so the chain reported "0.0 straight-line
miles nobody paid for" over a hop with a taken job inside it, and denied taken
jobs outright in the block it had not walked. The second and third are the
narrow-direction fault this feature fixed, ninety degrees away.

*And their fixes had no check that could fail.* All three survived mutation
until a fixture row naming neither end was added and the widened-but-not-
replaced state was driven — the suite had no row without a pickup, so the
nag's condition was structurally unreachable, and the driver always pressed
Place again after widening. Each fix now dies to a named mutation.

Two comments were re-measured rather than decremented: `map.html`'s "header
98px, bar 138, notice 108, 121px left for the map" is now header 64, bar 137,
notice 108, map 156 — the header and map figures had been stale for a while
and `bar 138` was the one still true, which this change moved. And the bar
carries eight now, not seven: two text boxes, the new select, and five
buttons. `rpi/test_layout.py` calls that "six controls and two text boxes",
which was one over when it was written and is exact now.

**`judge()` accused two pins on a distance the reader would not finish or
vouch for — and printed the rig's own repair of that distance as "card said".**

*The entry that filed this named the one flag that cannot fire.* It said to
guard on `milesUncertain`. Measured: of the 579 pairs `judge()` can draw on the
owner's week, **2 carry `milesUncertain` and exactly 1 also states a figure** —
and that one's distance is inflated, so `crow > stated + 0.5` can never hold.
A guard written on that flag alone would have been a check that never fires.
The reachable population is `whole === false` or `suspect`: **15 of the 579**,
three of which state how much of the journey is missing (5.6 mi held of a card
printing a 56-mi leg), so the straight line wins by construction. All three
carry `milesUncertain: false`. `milesUncertain` stays in the rule anyway, for
the phone's scanner, which sets it exactly rather than advisorily.

*What the driver saw.* A red dashed line captioned **"This cannot be right"**
over a pair whose two pins are both exactly where they belong, on a card whose
distance the rig had already refused to stand behind — and the real fault, a
leg that lost its distance, named nowhere. `judge()` now computes a named
`yardstick`, accuses only behind it, and reports `unjudged` with the reason
rather than silently dropping the pair, which would be the second fault class
dressed as a fix for the first.

*And the figure was quoted as the card's on 45.3% of every pair this page can
draw.* 262 of 579 are `milesCorrected` — a decimal the reader lost and put
back — so "card said 9.5 mi total" stood over a card printing 95. A driver
doing the one thing the page exists for, checking the rig against the screen,
finds a different number and concludes the page is broken. `statedBy` and
`unchecked` are written once and asked by all four surfaces that print this.

*The wording says less than the first pass wanted it to, and that is the
correction.* "a lost decimal put back" asserts THIS figure is the repair, and
the flag does not mean that: `rpi/accumulate.py` ORs `milesCorrected` across
the window and its own comment calls it advisory — "if any frame needed a
decimal put back, the distance is worth a glance". So the published figure may
be one no frame ever divided. It now says a decimal had to be put back while
reading this card and to check it against the screen, which is true of both the
rig's ORed flag and the phone's exact one.

*Two of the four surfaces were left behind by the first pass, and neither was
covered.* The accusation sidebar still read "the whole distance the card
stated" over rows whose figure the card never printed, and the withheld row
named "its N mi" with no attribution at all — and deleting that attribution
left all 118 map checks green. The fixture had no pair that is BOTH corrected
and accused, which is the commoner half of that section on the real week, so
the path could not be exercised. Both are fixed, both are pinned, and the
count-shaped checks that broke when the fixture gained the case were rewritten
to state the rule instead of the count.

`README.md` promised "the distance the card itself stated" and "a longer one
means a pin is in the wrong place". Both were false after this; both moved in
the same commit, as did `map-view.js`'s own file header, which stated the
pre-change rule inside the change that replaced it.

**The live map drew nothing until every lookup finished, and left the LAST
card's pins up while it waited.** Measured against the real `map-view.js` at a
500ms round trip, press to first mark: 1.6s for a card naming no dropoff, 3.8s
for three fresh places, 6.0s when the box refuses all three. The car goes down
first at ~0ms and each place as it lands. Fixed in `8d986d1`, together with the
companion entry — the held order's pin and this card's were byte-identical,
both `{radius: 9, fillOpacity: 1, fillColor: '#f5a524'}`, so the one comparison
the driver opened the map to make had to be done by clicking each dot with a
bluetooth mouse at the wheel.

*This entry sat under Open for three commits after it shipped*, which is the
fifth fault class in the ledger whose job is to prevent it — and it cost a
later pass an agent, which re-derived a built feature before noticing. Checked
against the source rather than the commit message: `live.html:2916` has the
`finally` clause, `map-view.js:773` has `if (onward)` with the throttle gone,
`live.html:3020` has the ring.

*One of the four "not optional" corrections was wrong, and the code is right.*
It said to ring THIS card's dropoff rather than the held one. What shipped
rings the held one, under a rule that covers all four marks instead: **solid is
part of the offer being decided, a ring is context the driver did not choose
just now** — so the car is ringed too. AUDITS' version needs a second meaning
for the same flag and leaves the car, the only measured point on the map,
outside both readings. Two checks pin the shipped rule, including "...and the
same ring on the car, so it is one rule and not two".

*Settled, and the `partial` term was itself the fault.* The `finally` is now
`if (viewMode !== 'map') mapFor = null;`. The old reasoning was that `mapFor`
is frozen for the whole walk, so `partial` already implied the mode had
changed — and **the implication runs one way only**. `partial` true did imply
the mode had changed; the mode changing did not imply `partial`, because
`await askCar()` sits between taking the key and putting the first mark up. On
this rig that wait is paid on EVERY press, because no journal row carries a GPS
position so `carFix` never caches — and even once rows do, it holds for 120s,
so the first press of each window still pays it. A press landing in that window
(⛶ Phone, or ▣ Set box) left the key set with **nothing drawn for that card**,
so returning to the map restated the previous card's detour over the previous
card's pins, under this card's figures, for good. Proved rather than argued:
the unpatched file fails three of the new checks and reports `asked: []` — the
new card's places were never sent to the geocoder at all.

The MODE half stands and is now measured: 1 draw with the clause, 5 in 6
seconds and climbing under `if (partial)` alone, and the panel hangs outright
if the key is nulled unconditionally. One residual is deliberate — a `drawMap`
that throws keeps its key, and `lastBounds` is assigned only after `fitBounds`,
so that path still shows the previous card's line and view. A stale map that
stops beats an unbounded retry on a panel read while driving.

*Three of the four corrections had no check that could fail.* Reverting the
early car draw, restoring `walk()`'s `% 3` throttle, or both at once each left
all 553 dashboard checks green, and the `partial` line had no check at all. The
stale-pin check that did ship survives a full revert, because two of that
fixture card's three places are cached so even a throttled walk finishes in
~20ms. Twelve checks now cover them, each dying to a named mutation.


**"Forget lookups" was undone by any page left open.** `remember()` wrote the
page's *whole in-memory cache* back to the device on every answer, so the panel
in the car restored its entire history the next time it looked anything up.
Measured: five answers in memory, the desk page presses Forget and the device
empties, the panel answers one more place and all five are back — including the
bad geocode the button exists to remove — and a page opened afterwards believes
them again. It now writes the one key it just answered.

The ordering of the two lines under it is the fix, not incidental: the write
happens first and the device snapshot is adopted only if it landed, so a page
whose storage refuses writes keeps what it has paid for in memory. Adopting
first would drop each answer as the next arrived and make a second press re-ask
every place at a second apiece. `tests/mapview.test.js` pins both directions.

### The phone's scanner

**A blank settings box stored the default, and saved it.** `bind()` in
`scan.js` answered a half-typed field with `DEFAULTS[key]`, while `ui.js` —
which binds the *same five keys against the same stored object*,
`uberscan.settings.v1` — answers it by keeping what is there, with a comment
saying why. Two answers to one question and only one of them thought about.
Measured on "$12.40 24 min (6.6 mi) trip" at 33c/mile: at the driver's own $40
line the card is a PASS, and backspacing the target box turned it into an
ACCEPT and left $25 in the store, so the line they never chose was still there
for the next card. A blanked *cost* box is quieter and worse — the deduction is
simply dropped, $41.99/hr reads $50.45/hr, and `uncosted` stays false so the
"this rate is a ceiling" notice never appears. `scan.js` now ships `ui.js`'s
rule; `DEFAULTS` backs `load()` only, which is the job it should have had.

**The phone wrote the journal's `text` column under a different rule from the
rig.** `rpi/journal.py` stores the reading the reader gave — line breaks and
all — capped at `TEXT_KEPT = 600`. `journal-client.js` stored the *flattened*
form with no cap, into the same column of the same append-only file.
Flattening is irreversible and `journal.html` renders that column inside a
`<pre>`, so rig rows showed the card and phone rows showed one run-on line;
`server.js`'s CSV says of it "It is what the reader read, line breaks and all",
which was false for every phone row. Measured: a frame whose crop took in the
screen behind the card ran to 2,639 characters, of which the rig stores 600 and
the phone stored all of them. Re-parsing either form gives identical results in
every field but `rawText` itself, so storing raw costs nothing. `TEXT_KEPT` is
now a second copy of one number — normally refused here, but the two ends
cannot import from each other and the alternative was no cap at all;
`rpi/test_lint.py` holds them in step.

**`row.cardMinutes` was the `minutes` expression character for character.** No
input could make the two differ, `journal.html` contains no occurrence of it,
and the comment above it said `journal.html` printed "one or the other off
this" — it reads `fromDeadline`. `rpi/journal.py` folds `cardMinutes` into
`minutes` and writes no such key, so the two writers of one file disagreed
about its shape. Removed from the stored row. **On the READING payload the
distinction is real and must stay** — `scan_pi.emit()` sends both as different
claims and they diverge on every deadline card. That half of the filed finding
is refuted; see Settled.

**The unsent queue had no ceiling and swallowed every storage failure, so
offers stopped being saved and the phone went on buzzing.** `journal-client.js`
saved the queue with `try { localStorage.setItem(...) } catch (e) {}` and
`keep()` handed the row back regardless, so the caller could not tell a row
that was kept from one that was not. `scan.js` buzzed and showed the verdict
either way; `ui.js` read `.id` off the return and **threw inside `logOffer`**,
where nothing catches — so on the keypad the press did nothing at all: no
history entry, no buzz, no toast, the typed figures still on the keys.
Measured against the owner's own week rather than argued: a stored row is 831
bytes of JSON at the mean and 987 at the ninetieth (1,166 offers put through
`row()` one at a time), so at Chrome's 5MB — charged in UTF-16, as it charges
it — four passes of that week put 4,664 offers to `keep()`, it said yes to all
4,664, **3,265 landed and 1,399 went nowhere**, and from row 3,266 onward every
offer was lost, permanently, until a rig answered. Now: a `QUEUE_CAP` of 1,000
— six days of that week's heaviest scanning with a rig never once reachable —
shedding oldest-first and counting what it shed and through what time; `save()`
reports instead of swallowing; a refused write sheds *nothing*, because it
never landed, so the rows already queued are exactly where they were and only
the row in hand is lost. `keep()` returns null for that row, `scan.js` leads
its status line with it the way `live.html` leads its notes with `notSaving`,
and the keypad marks the entry "not in the journal" rather than letting it read
like one that is merely waiting. The backlog itself is named too — "N offers
waiting — the rig has not answered" — which is the only one of the three a
driver can still act on, and it appears long before either ceiling.

**...and the line that reported it gave advice that went stale, and hid the one
part a driver could act on.** Found by re-reading the commit above with the
same lens it was written with. `queueNote` was three early returns in
severity order, and `trouble()` never clears — rows that went nowhere do not
come back when the rig does. So the dropped line, which ended "the queue is
full, find the rig", stayed on the glass after the rig answered and the queue
drained (the fifth fault class), and because it returned early it **masked**
the live backlog for the rest of the page's life. Those two are the same
moment, not alternatives: the ceiling only bites after the rig has been out of
reach long enough to fill a thousand-row queue, so the state that produces a
drop is exactly the state where "N waiting — the rig has not answered" is the
line worth reading. Now the permanent facts are stated as facts with no advice
attached, and the actionable line is added to them rather than returned instead
of them. Checked through the page's own render on the real status line, and the
three mutations — the stale advice back, only the first clause shown, the
backlog clause silenced — each fail a named check.

**The box note went stale in both directions, and the worse one was unfiled.**
`setAdjusting()` writes its sentence only at the instant adjust mode is
entered, and the whole-frame checkbox is the one control that can falsify it
afterwards. Ticking it left "drag the box onto the card" over a box whose drag
handler returns immediately — annoying and visibly inert. **Unticking** it left
"the box is not used" standing while `sourceRect()` had just started cropping
every read to that box: the driver is told the crop is off while the crop
decides whether anything is read at all. One line, `setAdjusting(adjusting())`
in the change handler.

### The keypad

**The "storage that will not answer" block was never run with storage off.**
`rpi/test_keypad.py` installed a throwing `localStorage` with `page.evaluate`
and then ran `page.reload()` underneath it — and a reload is a new realm, so
the property defined on the old `window` went with it. Every check in that
block had been running against a perfectly ordinary store since it was
written. Proved rather than asserted: with `ui.js`'s settings guard removed —
a change that makes the keypad show `--` instead of `$30.0` and throw on load
— the old harness passed all 92 checks. `addInitScript` runs before each
document instead, which is the moment that matters, because `loadSettings`,
`loadHistory` and `restoreDraft` all read at import. The block now reports
`storageReallyOff` as its first check, so the harness says whether it is doing
what its name claims, and the same mutation now fails three checks. This is
the project's sixth fault class — a check that cannot fail — found in the one
place that is meant to catch the others.

**The keypad keeps a private shadow of a queue it shares with the phone
scanner, so its count goes permanently wrong.** `ui.js` stores a per-row `sent`
boolean, and the only thing that can ever set it true is this page's own flush.
The queue it shadows — `uberscan.unsent.v1` — is shared with `scan.js`, which
empties it on every lock and on page open. So: log an offer with the rig out of
reach, tap 📷 Camera once the rig is back, come back to the keypad. The row is
in the journal; the keypad still says "kept here only", across reloads, for
ever. Then it becomes a wrong number — the toast counts every row with
`sent === false`, so it inflates monotonically. Measured: **"3 kept on this
phone — the rig did not answer"** with exactly one row genuinely on the queue.

The direction is conservative, and the cost is that the page's only report of
whether the irreplaceable record is complete saturates and stops meaning
anything. `JournalClient.pending(id)` already answers this correctly, is
exported, and has zero callers repo-wide.

Not built: attacked, and the proposed cure has a correctness regression in the
dangerous direction. Reconciling on "absent from the queue" also marks a row
sent that `keep()` never stored because storage was refused — the storage-off
case under Open. It needs a `queued` flag recorded at `keep()` time so that row
is never reconciled and goes on saying "kept here only", which is true.

### The service worker

**The background refresh is fired and forgotten.** Both cache writes happen
outside the fetch event's lifetime, so the line that makes "the entry replaced"
true was never guaranteed to run. Real but small: a lost refresh costs one more
stale load, and the next open with a live worker replaces the entry. The
three-line fix (`e.waitUntil(fresh)` inside the `caches.match` callback) is
correct; the severity claims around it were not — it is not "fails every time
on a bad link", and the trigger is the browser process being killed under
memory pressure, not swiping away from the app.

### The aiming

**A guard against a stuck outline was written, commented, and placed one line
too late — so it never ran.** `rpi/track.py`'s miss branch called
`_forget_stall()` unconditionally, and that nulls `_off_since` itself, so the
`if self.misses >= LOST_AFTER` guard under it could never do anything. The
comment above the guard already described the behaviour it was meant to have.
Proved rather than argued: with the guard's body deleted outright, all 138
tracker checks still passed.

What it cost, driving the real tracker against the real detector on the
re-seated-phone frame the suite already uses — the phone put back a quarter
further away, so `same_size` refuses the real screen for ever and the corners
freeze:

| one blank check every | reported "corners stuck" at |
|---|---|
| never | 5.5s |
| 30s | 5.5s |
| 10s | 5.5s |
| **5s** | **never** |
| **2s** | **never** |

A blank check is the ordinary case: a hand reaching to tap Accept, a frame
caught mid-redraw, a screen washed out in daylight — and that last one is the
very state the "outline stuck" message blames, so the condition that sticks the
corners is the condition that blanks the detector. Meanwhile `misses` returns to
0 on the next hit, so `lost` stays false and the corners never move, so `drift`
and `wander` are 0.0: the health line prints "corners held, 0px from
calibration" for the whole shift while the crop is on a rectangle that is not
the card. Every number downstream is then read off the wrong pixels.

### The backup

**A row from the future stopped the backup dead, and the first fix for it was
set too far out.** `rpi/sync.py` resumes from `newest - 1h`, so one row stamped
ahead of real time makes that floor a moment no real offer ever reaches, and
every offer from that tick on is silently skipped — for ever, because nothing
looks further back. Silent at every step: the shortfall check anchors its own
window to the same poisoned `newest` so both sides agree, the run exits 0, the
`.synced` stamp is refreshed, and doctor reports a backup made minutes ago.

`CLOCK_BELIEVABLE_UNTIL` was added earlier in this session for exactly this and
set at 1 Jan 2100 — which catches the corrupted `1e20` row it was written for
and does **not** catch the common case. `journal-client.js` stamps `at` from the
phone's own `Date.now()`, so a phone a month fast lands a row a month ahead,
seventy years under the ceiling. Measured against the real server: `newest`
came back 45 days in the future. Now bounded by this machine's own clock plus a
day.

**And the guard on that is not decoration.** The ceiling is taken off
`Date.now()`, and this same file runs on a Pi with no RTC that boots in 1970
until NTP arrives. A ceiling off an unset clock puts every row above it and
answers `newest: 0` — measured by the attacker at **606 of 1,225 offers lost**,
silently, in the default configuration with no poison row present. So when the
clock cannot be vouched for it falls back to the fixed ceiling: no better than
before, and no worse. `CLOCK_BELIEVABLE_AFTER` is overridable by env solely so
that branch is reachable from a test — this session has already found one
unreachable guard costing a whole shift.

**Three ways the rig reported a healthy backup it did not have.** A row stamped
past the end of time ended the window for every row behind it; the journal being
unwritable was not checked at all; and the verdict on the off-car backup was
inverted with respect to the danger, so the check passed in exactly the case it
exists for. `a5cbe64`, plus the `CLOCK_BELIEVABLE_UNTIL` clamp in `server.js`.

### The panel

**The panel's caption row had a budget written where nothing could enforce it,
and it was not a budget that could be kept.** `live.html` states the rule at
the `mapDrew` call — "this line is a row of the panel, and at 15px a sentence
that explains itself fully runs to three of them" — and then emitted sentences
that took six.

*The entry that filed this was wrong twice.* It said "nine sentences up to 125
characters". Measured by rendering each one through `rpi/test_layout.py`'s own
machinery and counting rows off per-character client rects: **twelve forms off
ten branches**, the longest fixed string 127 characters — and the worst line
has no length of its own at all. `if (badEnd)` interpolates a place read off a
card, bounded only by the parser's `MAX_PLACE` of 60, so the line runs to 171
characters and six rendered rows. That is the case a driver actually hits: it
is the sentence naming which pin is wrong, on the card where they are trying to
find out.

*Capped in rows, not rewritten, and the measurement decided which.* One row is
not reachable at 480×320 for the mode's own figure line, so the budget is
restated as rows and enforced in CSS — `-webkit-line-clamp: 2` on a dashboard
panel, `3` on the hat, both derived from the detour line's own rendered height
on each panel rather than chosen. The map's floor goes from 301px/104px to
334px/154px; 104px was below the suite's own floor for "a map rather than a
texture". Two lines are still ellipsised on the hat and both lose only a
trailing clause: `" not asked"` off the detour's tally, and the tail of
`", so no distance"` off the misread-name line.

*And the line printed `&amp;` where the `&` should be, on 39.2% of places.*
`mapSay` assigns `textContent`, which needs no HTML escaping, and the caption
ran the place through `esc()` on the way. **520 of the owner's 1,325 distinct
places contain an `&`** — "Hawthorn Dr &amp; Shady Gin, Dallas" on the glass.
It now goes through `shortPlace`, which cuts at a space near twenty characters
and does not escape.

*36 of the 196 new checks could not fail, and that was caught before they
landed.* The caption table filled an undeclared "what may be cut" field with
the whole sentence, making `_text.startswith(_keep)` and `_drop == ''` true of
every string. Only rows that declare the field are linted now: 819 → 783. And
the clamp itself is checked rather than only its effect, so `cap` is no longer
the same number answered in two places — the suite could have said 2 while the
stylesheet said 4 and every row-count check would still have passed.

**A journal that had stopped taking writes was invisible on the glass.** A
read-only SD card is the classic Pi failure, it is completely silent, and
everything above it goes on working: the rig reads the card, prices it, speaks
the verdict and paints a green ACCEPT while nothing reaches the one file that
cannot be regenerated. The only sign was a line in a log on a headless box.
The driver's own tick already reported its failures, because that write goes
through a request that can answer 500 — the offers themselves are written from
inside the scan loop with nobody to answer, so the notice now rides the
heartbeat beside `tooBright` and `refindRefused`, and leads the note list in
both branches of the panel.

Worth knowing if this is ever touched again: with the notice and the wire both
in place and the loop not passing it, every suite still passed and the panel
was still silent. The check that closes that gap is in `rpi/test_loop.py`,
against the real `main()`, and it is the only place that link can be reached.
The panel's two branches also build their notices separately, and `render()`
picks between them on `last.ready` — a phase message alone does not move it,
so a check that means to measure the between-offers branch has to send a
reading that is not ready.

### The advice

**The threshold and the headline counted different piles.** `bestAt` reports
`offers` as what the replay walked — rows dropped with their single-offer run
are not evidence it used — and the ready gate went on testing `rows.length`. A
window could be refused by the number it printed and admitted by a number it
did not. Both now ask the walked pile, and the refusal carries `setAside` so
the page can reconcile its own two counts rather than leaving a reader to find
the gap.

**`sure` was the one clause stated without a hedge, on a figure that may be a
ceiling.** `state` has been capped for the uncosted case since it was written;
`sure` compared the same two kinds of money and said "beats finishing alone"
anyway — in the one clause the 3.5" hat has room for. Withheld now when the
OFFER is the gross side, and deliberately **not** when the held job is: that
direction understates, which is the safe one and not worth losing a true claim
over. The asymmetry is worked out in the comment at the `offerGross` line.

**"Held at every threshold" was printed as "the same line comes out".** The
stability check allows the recommended figure to wander by `UNSTABLE_SPREAD`
across the six ways the recording is cut into runs, which is $6 — a fifth to a
third of the line itself on the targets this driver sets. The offers page
claimed the line never moved over all of it, in the one sentence whose job is
to say why the number can be trusted. It now says where the line actually went
and by how much, and keeps the strong wording for the case that earns it.

The threshold was deliberately **not** tightened: a line steady to within a few
dollars over six different cuts is a real finding, and the refusal above it is
for when it is not. The fault was the wording. The case is common — over a
thousand synthetic markets, 104 came out answered with a line that moved, 49 of
them by $3 or more — and the fixture that pins it is a shared generator in both
`tests/advice.test.js` and `rpi/test_offerspage.py`, whose line is $24 at the
two shortest cuts and $30 at the other four. If that generator is ever touched:
Python's integers are exact and a double is not, so the JS side steps the LCG
in `BigInt` or the two ports walk different markets.

**Occupancy was asked of the previous row rather than of the shift.** `runs()`
and `unexplained()` measured each gap from `freeAgain(rows[i - 1])`, so a single
card scanned during a tagged trip threw the rest of that trip's length away.
Measured, on a tagged hour-long trip with an offer glimpsed at five minutes and
the next arriving at fifty-eight: the run split, the offer after the trip was
dropped as a run of one, and a silence was counted against the one stretch that
was tagged — so the page asked for a tag on the trip that had one. Without the
mid-trip scan the old arithmetic was right, which is backwards: a row being
*seen* made the record worse. `busy()` had it right all along, which is why
`occupancy()` now exists and all three read it.

---

## Settled — do not re-propose

### The journal read

**Do not window `/api/journal/newest`, `/api/journal/notes` or
`POST /api/journal/ingest`.** All three need every row in the file, and ingest
needs it absolutely: its idempotence is a `syncKey` set built over the whole
journal, so a windowed set stops recognising rows it has already stored and
appends them again on every sync tick — permanent corruption of the one artefact
that cannot be regenerated. `readJournal`'s own header records what a short set
did last time: 60 duplicate rows, `ok: true`, and a `have` that was wrong.
`newest` is the sync's reconciliation source (`have` over every row, `newest`
over every kindless row); `notes` filters each row's own `at` against a `since`
the *sender* chose, which is 0 under `sync.py --all`. The window belongs between
`readJournal` and the fold, which is where `rowsFor` now is.

**Do not add a chunked or streaming parse to cut memory.** Measured: `VmHWM`
equals `VmRSS` after a cold parse (362,580 kB vs 362,580 kB). There is no
transient spike above the retained rows to reclaim — the buffer, the string and
the split array are collected as the parse proceeds. It would add a state
machine to the one function that must never lose a row, for nothing.

**Do not make `readJournal` index-only** (a `syncKey` set for ingest, running
totals for newest, re-read for the rest). It is the only route to a real cut in
the ~305 MB of resident rows, and it turns "the journal, as rows" into three
derived indexes that must each stay true. `/api/journal?days=0` needs every row
anyway. If memory ever becomes an actual failure on the rig, cap the heap first:
`ExecStart=$NODE --max-old-space-size=400 …` in `rpi/install-service.sh` bounds
it without touching application code (measured: 381 MB → 301 MB, no OOM, no
measurable slowdown).

**Do not add a server-side cap on `days` or `limit`.** `tools/measure_places.js`
asks for `days=3650&limit=20000`, and the CSV link asks for `limit=0`
deliberately — see the comment at `journal.html` explaining that a ceiling is
still a cap. `days` must stay an honest span.

**Do not merge the three chart passes** over `offers` in `journal.html`. Each is
cheap and each is readable; merging saves a few ms on *All* and costs clarity.
The one exception was the day-of-week pass, which was discarded outright and is
now guarded.

**Do not narrow `Advice.busy` or the day grouping to the 300 rendered rows.**
The busy chip and its note describe the whole window, so a join over a sample
would make the sentence disagree with the list beneath it.

**Prewarming the parse at boot is not obviously right.** It moves a ~300 MB
allocation and several seconds of CPU into the one moment memory is tightest —
boot is when the scanner is starting Python, OpenCV and Tesseract. Do it only if
the first load after a reboot is reported as a real problem, and then delay it a
few seconds after `listen` rather than running it inline.

### The maps

**Do not add a weekday term to the map's time filter.** It is the obvious
next step and the data refuses it. A 168-hour window holds each weekday-and-
block exactly once, so on the owner's week **all 13 occupied weekday x block
cells came off a single calendar date apiece — 0 offers pooling more than one
date**. Three of the seven weekday options are empty all week (the driver
worked 5 dates: Sun, Tue, Fri, Sat, Sun). Blocks alone pool 4 of 6 occupied
cells across multiple dates, covering 97.0% of the week. Weekend/weekday x
block is the middle option and is also worse: 4 of 9 cells, 68.9%. At 30 days
the server truncates 5,000 of 5,444 rows and the walk goes to ~100 minutes.
The sibling page already refuses the 8x coarser version below 14 days.

**The geocode cache IS worth keeping — this entry was wrong, and is corrected
here rather than deleted.** It argued that the cache should not be kept on a
server because it is "regenerable", leaning on `advice.js`'s measurement that a
cache built from three days covers 11% of the next day's places. Two things
were wrong with that:

- **Regenerable is not the same as cheap.** Measured on the owner's real week,
  1,325 distinct places at the one-a-second rate limit is about **24 minutes**
  to rebuild. The 11% figure is about a *later day's* places; it says nothing
  about re-placing the days you already placed, which is what actually happens
  when the cache is lost.
- **It was localStorage and nothing else**, so it belonged to whichever browser
  did the placing. Laptop then phone is two full runs, and clearing site data
  loses it.

The privacy objection was wrong too. The cache key *is* the place name — and
those names are already on any machine running this, because `pickup` and
`dropoff` are fields on every journal row and the journal already syncs. What a
cache adds is a latitude and longitude for a string that is there anyway.

So: `GET`/`POST /api/places`, stored in its own file beside the journal. Done.
**Deliberately not in the journal**: ingest's idempotence is a syncKey set over
the whole file, and something regenerable has no business sharing a file with
the one artefact that is not. And the rig still never geocodes — this stores an
answer the browser already holds; nothing on this side asks anybody anything.

Still true from the original entry, and still the reason there is no
newest-wins rule: two machines that answered the same string differently have
no way to choose, so the first answer stands until "Forget lookups".

The *merge* the entry pointed at had a real bug, and that is fixed — see Done.

**The map is not two presses from the phone by accident.** The cycle is
Phone → Scene → Map → Phone on one control, because the bottom bar holds six and
a seventh sheds one. A proposal to reorder or shortcut it misread what the code
does and was net-zero at best.

**`dropoffScanned` does not mean "read off the driver's phone".** A proposal to
distinguish card-read from phone-read dropoffs on the maps inverted what that
flag actually marks. Read the fold in `server.js` before building on it.

**Do not widen the detour to include where the new job ends.** It is
`car → pickup → where the order in the car is going`, because that order *has*
to be delivered; where the new job ends after that is a further guess. This is
already stated at the `mapLine` call site in `live.html`.

**Do not make "on your way" proportional** (e.g. a percentage of the route
rather than the half-mile cut-off). It would put a second geocoded number on the
panel for the driver to act on, which the header of `map-view.js` forbids.

**Do not run `straysAmong` against the median of two points** on `live.html`.
With a pickup and a dropoff the median *is* the midpoint, so both ends come out
equally far and **both are accused** — the good pin condemned beside the bad one.
Measured, not reasoned: `straysAmong` on such a pair returns 2. This is why
`MV.farFrom` exists and is anchored on the car's measured GPS fix instead; see
`map-view.js`. *(Done — the panel now marks the wrong pin and withholds the
figure. Before it, a misread street answered in Idaho produced "+3619.4 mi out
of your way" on the driving panel.)*

**Do not re-draw a stacked hop out of the dropoff the car had not reached.**
The proposal manufactures a confidently wrong number and proposes a check that
cannot fail.

### The reader

**`cardMinutes` on the READING payload is not a duplicate of `minutes`.** It
was filed as one. `scan_pi.emit()` sends `minutes` (the card's own figure),
`cardMinutes` (the minutes the verdict was made over, which on a delivery card
is time-until-deadline) and `billedMinutes` (with the driver's pad and shopping
allowance added) — three different claims, and the first two diverge on every
deadline card. Merging them would put a stated duration and a deadline
countdown under one name on the one screen that has to tell them apart. The
duplicate that *was* real lived in `journal-client.js` and is fixed; see Done.

**A glare frame IS an episode boundary, if you only model it.** The one-line
fix under Done is right, but the sequence that shows the fault is narrow and
easy to get wrong. A payout-free read is only miscounted **before the card has
landed** — once a reading is on disk the `same_card` guard recognises the
payout and hides it. Measured against the real loop, not a model of it:

| glare on | cards on disk | saw | kept |
|---|---|---|---|
| nothing | 1 | 1 | 1 |
| read 3 only (after landing) | 1 | 1 | 1 |
| read 2 only (before landing) | 1 | **2** | 1 |
| reads 2, 4, 6 | 1 | **4** | 1 |

A simulation that leaves out `same_card` reports an overcount everywhere and is
wrong about which sequences matter. Drive `rpi/test_loop.py`'s `run()` instead.

**Do not gate `accumulate.QUIET` on the window's reading being whole.** The
*observation* behind it is correct and worth knowing: `QUIET = 2.0` is justified
at the top of `rpi/accumulate.py` as "four times the resample cadence", but that
arithmetic is against `RESAMPLE_EVERY`, which is how often the loop *asks* for a
frame. The reader is single-slot and `rpi/scan_pi.py` measures a read at
`READ_SECONDS` 1.85 median, 3.7 at p90 — so the real gap between two readings of
one card routinely exceeds the threshold, and the verify beat (2.5 s backing off
to 6.0 s) always does.

The proposed cure is still wrong, and the suite says so. Gating on the window
being whole (`held_total or len(self.legs) >= 2`) makes the window never settle
on a **single-leg** card — "$12.99 Guaranteed (incl. tips) 7.7 mi + 28 min",
which is the commonest shape this driver sees — so a genuinely different card
with the same payout arriving six seconds later is merged into the one before
it. Tried: `...and so is one that replaces it straight away` drops from 2
episodes to 1. An audit that claimed to have verified this cure named a method
(`_merged_view`) that does not exist, so it cannot have run what it described.

The exposure is also narrower than it first looks. `quiet` is already tested
*last*, after every leg has failed to line up, so a re-read of the same card
that arrives late does not reach it — only a frame in which **no** leg lines up
does. If this is ever revisited, the thing to change is the constant's
calibration against the measured read time, not a wholeness gate, and the two
replacement cases in `rpi/test_accumulate.py` are the ones that decide it.

**Per-place correction of a bad geocode was proposed twice and refused twice**
in its stated form — a button on the page the driver is not on, whose remedy
cannot change its own output. The *problem* is real and is listed under Open
below; it is the proposed cure that was wrong.

---

## Measured on a real week — 1,166 offers, 13–20 Sep 2026

The numbers above this line came from a 272-card export. This is a bigger and
newer one, and it moves several of them. Where the two disagree, this wins.

**The rig reads well.** 97.9% whole, 0.8% suspect, one impossible reading in
1,166 and it was caught (`doubt`, `suspect`, `milesUncertain` all set). Reads
run 1.80s median, 2.80s p90, 5.4s max. Consecutive duplicate rows are 0.6%, so
the accumulator's identity rule is holding. Nothing here needs fixing.

**The line is right.** `Advice.advise` over the whole week: ready, stable,
spread $0 — $20 at every one of the six thresholds, plateau $20–$25, over 27.9
hours and 9 runs. The driver's $25 is inside that plateau and the difference is
−0.6%, so the target does not want changing.

**Almost everything is a pass.** 935 of 1,166 are PASS, 116 warn, 106 go, and
31 were ticked as taken. Median offer $14.56/hr against a $25 line.

**`toPickupMinutes` is null on all 1,166.** It is not that the split is absent
from the cards — 110 of them state it plainly, e.g. "$26.04 / 8 min (3.2 mi) /
Ector Chase NW…, Kennesaw / 39 mins (25.1 mi) / Hale St NE…, Atlanta", where the
first leg is the drive to the pickup and the second is the trip. `to_pickup()`
requires a leg matching `APPROACH_TAIL = /\baway\b/`, and **the word "away"
appears on 0 of the 1,166 texts** — against 29 of the 152 corpus fixtures, where
the approach is extracted on 24. Uber's current card states the split
positionally instead of labelling it. So a feature with tests, a CSV column and
a consumer in `tools/measure_places.js` produces nothing on a week of driving.

Do NOT cure this by taking the first leg: on those 110 cards the first leg is
the shorter one only 62% of the time, so size is not the signal. The layout is —
leg, pickup place, leg, dropoff place — and `find_places` already knows where
those places sit. Any fix is a parser change across both ports and the shared
corpus, which is why it is written down here rather than done in passing.
**Done** — `laid_out_approach` reads exactly that; see "The reader" under Done.

**The dropoff carries a fragment of the pickup on 8.3% of cards.** 48 of the 580
dropoffs hold an unmatched `)`:

    pickup  'Hooters (Old 41 Hwy NW & N l Roberts Rd)'
    dropoff 'Roberts Rd) Georgia State Route 5 N &!-575 N, Cobb County'

A merchant name wrapping across lines is being cut in the wrong place, and the
tail is prepended to the dropoff. That string then goes to a geocoder, so this
is one of the sources of the stray pins on `map.html`. **Fixed** — the card's
own border was being read as a divider; see "The reader" under Done. The rows
already written keep their poisoned strings.

**No deadline cards at all.** `fromDeadline` and `deliverBy` are 0 of 1,166, and
`items` is filled on 4.2%. This driver is on Uber, whose cards state a duration.
The deadline path is not dead code — the corpus has such cards — but it has
never fired for them, so a claim that it matters "on every delivery card" should
not be repeated without saying whose.

**No row carries a GPS position.** `map.html` says "none carry a position", so
`anchorFor` answers null for every place and nothing can be boxed. Combined with
a `near` field that held a *placeholder* rather than a value, every one of the
1,325 distinct places went to a world-wide geocoder as a bare string — and 47
came back "nowhere near the rest", up to 7,627 miles out: Papa Johns Pizza,
McDonald's, Burger King, Wendy's. Fixed by `localityOf`, which reads the town
back off the driver's own cards. Whether the rig's GPS should be recording a
position on rows at all is a separate question nobody has asked yet.

---

## Open — known, checked, not done

None of these are bugs on the road today. They are things worth doing that
nobody has done, listed so they are not rediscovered as news.

**A card with one readable place calls it the pickup, and 474 of 1,166 rows
rest on that.** Where the card's own layout names the end, the rig now follows
it: that is `place_ends`, shipped with the two-ends fix recorded under Done. It
settles 4 of the 478 one-place rows in the owner's week — three pickups and row
1149's dropoff — and leaves the other 474, **40.7% of the week**, labelled by
position alone, because `find_pickup` takes `places[0]` and nothing said which
end it was.

Most of those are right for a reason position does not supply. 410 of the 474
(86.5%) are a bare merchant name — `Zaxbys`, `Carrabba's Italian Grill` — and
for a delivery the merchant IS where the job starts. The population that is
genuinely a coin flip is the 64 street-shaped ones, **5.5% of the week**:
`Canton Rd, Marietta` is as plausible an end as a start, and the card did not
say which.

*The evidence this entry used to give was wrong, and the correction is already
in Done.* It named rows 2, 434 and 822 as one-place cards recording a
destination as a pickup. They do not: all three come out right on the rig,
because the merged reading is a union across the window and another frame read
the merchant with its bracket closed. That claim was measured with `parse()` on
one stored text, which describes the PARSER and not the RIG. Every number above
is a replay of the real accumulator over the real frames.

Still not bundled with the two-ends fix, and for a sharper reason than before:
what would actually move these 64 rows is a merchant test — something that
knows `Zaxbys` is a shop and `Canton Rd` is not. `PLACE_IS_A_SHOP` is not that
test. It wants a trailing bracket, and it finds one on 10 of the 474.

**While an order with a known destination is in the car, the ⌖ button cannot
serve the card being screened at all.** The owner's stated habit is to tap the
customer dropoff open to read the address *while screening* a DoorDash offer.
Measured against the real server, carrying a job whose end is already on
record and a different card on the slot:

| the driver | what happens |
|---|---|
| taps the address open, no press | discarded — the empty `else if (carrying)` branch. The screened card gets nothing, and nothing says so. |
| taps it open and presses ⌖ | the address lands on the **held** job, replacing the destination it already had. |

So one route silently does nothing and the other quietly rewrites where the
order in the car is going — which feeds `MV.detour` and the "+N mi out of your
way" figure on the panel. The screening branch below is unreachable whenever
anything is carried.

Deliberately not fixed here, because the fix is the same ambiguity the refused
guard above is about: an address seen while carrying one job and screening
another may belong to either, and the rig cannot tell from the frame. The
`kind: 'sighting'` rows described under Settled are now counting it: the `kept:
false` half of that tally is this entry's population, and it should be read
before anything is built.

**A wrong remembered lookup can only be fixed by wiping every good one.**
`map.html` is the one surface that can *identify* a bad geocode — the stray rows
are already listed and already tappable — and all it can do is throw the whole
cache away. (The cure proposed by the audit was refused; see Settled. The
button at least *works* now — see Done.)

**A heat map of $/hr by area, asked for, designed, and refuted on the data.**
The driver's words: "visualize the $/hr in different areas around Atlanta ...
helpful for predicting where my time would be best spent."

The two things that blocked it are shipped: `map-view.js`'s `localityOf` boxes
the geocoder to the driver's own towns, and `GET`/`POST /api/places` keeps the
answers on the NucBox so the 24-minute re-place is paid once. A full design was
then written and attacked by two independent reviewers. **Both refuted it, on
the same fault, and every number below was reproduced at least twice.**

*The fault that decides it.* The design set a minimum of 12 offers a cell,
calibrated against "how often does the median of 12 land outside the middle 80%
of the week" — about 4-5%, which sounds fine. But the map does not paint at
those edges; it paints at fixed band boundaries. Re-scored against the boundary
that is actually drawn, a cell with **no area effect whatever** takes the wrong
colour **21-25% of the time at n=12** — roughly two miscoloured cells on an
eight-cell map, with only one map in ten coming out clean. A confidently wrong
number on the glass, which is this project's worst fault class, and it was
invisible because the floor and the scale were tuned separately. Whatever is
built, **those two must be derived together and the table for that exact pair
must sit in the comment.** Moving the top edge to $19.50 takes it to 7.0% at
n=12; keeping the edge means a floor of 30-60, which this week supports in
zero cells.

*There is no signal below town scale.* Kruskal-Wallis over distinct places,
n>=5: H=25.46 against a shuffled p95 of ~31.8, p~0.22 — reproduced to the
decimal by two reviewers independently. Over towns it is strong (H~65 against
p95~17), and it collapses the moment Atlanta is removed (p~0.14-0.48). **The
finest distinction this week supports is Atlanta against the northwest
suburbs.** A grid finer than that draws a difference the data cannot measure.

*And a third of the week cannot be placed at all.* A bare merchant name is
geocodable but not locatable — a geocoder answers "McDonald's" as confidently
as it answers an intersection, and it is not the branch the card meant. 462 of
1,107 named pickups are a bare brand with no street or number, 68 of those
strings repeating across 293 offers. Nothing catches it: `judge()`'s
`impossible` needs a second pin and 90% of them have none, `straysAmong`'s
FAR_MILES is 75 and Atlanta-to-Kennesaw is 24. Excluding them leaves ~422
offers (36%) — and **that third is not a random third**: pickups naming a
street pay a median $15.97 against $14.08 for the rest, gap $1.89,
permutation p=0.0001. The map's population earns ~$2/hr more than the week it
would claim to summarise.

*The area effect is partly a time effect, and this is the one that would give
bad advice.* Measured here with the repo's own `Advice.area`, local hours:

| local | n | median | | town | n | median |
|---|---|---|---|---|---|---|
| 14:00-17:00 | 254 | $13.54 | | atlanta | 101 | $20.07 |
| 17:00-20:00 | 198 | $13.66 | | kennesaw | 71 | $15.51 |
| 20:00-23:00 | 382 | $13.98 | | marietta | 95 | $14.42 |
| **23:00-02:00** | 220 | **$17.74** | | acworth | 38 | $13.84 |
| **02:00-05:00** | 112 | **$16.73** | | powder springs | 19 | $12.24 |

Atlanta is **71% of town-labelled offers between 23:00 and 02:00 and 0-4%
between 14:00 and 20:00**. Its raw $5.58/hr advantage falls to **$3.91 within
the same hours of the day**. So about a third of "Atlanta pays more" is really
"late night pays more", and a map showing area without time tells the driver to
drive to Atlanta at 4pm — which this week says is worth about $14. **Any
version of this feature carries the hour or it is answering the wrong
question**, which made the time filter a precondition rather than a companion.
That precondition is now met: the `when` box ships, eight three-hour blocks of
it, and Settled says why it carries no weekday term.

*The cheaper thing to try first.* A **town table** needs no geocoder, no new
map pane, no ninth control on a bar that already carries eight and wraps on
the 3.5" hat, and no 24-minute wait: `Advice.area()`
already labels 475 of 1,166 rows with a town read off the driver's own cards,
and `tools/measure_places.js`'s `keyOf(place, 'town')` already groups by it.
Eight buckets at n>=12 covering 436 offers — **more than the heat map's 422** —
labelled with words the driver reads rather than a coordinate. Crossed with the
five hour blocks above it answers "where and when", which is the actual
question, and every cell of it is checkable by eye.

Two things to get right whatever is built, both about honesty rather than code,
and both still true:

- It is a map of what was **offered** there, not what was **earned** there. 935
  of 1,166 offers were passed. The heading has to say so, or it reads as income.
- The pickup is where the job STARTS, not where the driver WAS when the card
  arrived. Those differ, and with no row carrying a position the second is not
  knowable at all. "Where the good offers start" is the honest title; "where to
  sit and wait" is a claim this data cannot make.

Median, not mean, per cell — and the reason is stronger than it used to say
here: the tail is a $185.46 card, not a $41 one, and the mean's false-hot rate
never recovers (3.2% at n=30 and 0.7% still at n=60, against the median's 0.4%
by n=30).

---

## What has been swept, and when

| Area | Outcome |
|---|---|
| `map.html`, `live.html` map mode, the offer log's map sheet, `map-view.js` | 25 proposals, 14 survived checking, 11 refuted. Fixes in `06a6dd8`, `ebc80df`, `f5cfb96`, `c98f6fb`. |
| `readJournal` / `latestPerOffer` / every consumer of a journal read | 43 consumer claims mapped and verified. Fix in `d864163`. |
| `map.html` layout, on every panel, for the first time | Four faults on the first run. Fix in `d829bb9`. |
| The pin badge said "jobs" and counted offers | `4d0accc`. It says offers, and the popup keeps taken / passed on / never marked apart. |
| The offer log's map sheet named a colour that was not drawn | Fix in this commit: it names the pin that is there, the end that is missing, and which of the three kinds of missing it is. |
| The reader, the sync, the keypad, the ops scripts, `advice.js`, silent-failure paths repo-wide | 29 hunted, 16 survived checking, 13 refuted. The worst is recorded below; what has landed is under Done. |
| The last five of those, re-checked one agent apiece and then attacked by two more | All five real, one reframed (`cardMinutes`), two proposed cures refuted with measurements. Four fixed; the fifth — the phone's unsent queue — is under Open with the reasoning its cure needs. |
| The top Open items and `server.js`, which had never been swept as a unit | Two shipped (the screened dropoff's provenance, "Forget lookups"); one Open entry refuted outright and moved to Settled (syncing the geocode cache); two designs survived attack and are under Open with their corrections (the live map's draw order, the phone's unsent queue). |

### The worst fault this sweep found

`one_card()` bounded the **legs** and nothing else. Every other field a card
states — the distance, the deadline, the item count, and the `Pickup` anchor
that names the merchant — went on reading the whole frame and taking the first
match anywhere on it, while the payout took the largest. On a frame holding two
cards that means the rig prices one card and describes the other. Measured, in
both ports:

| | pay | miles | items | verdict |
|---|---|---|---|---|
| top card alone | $8.00 | 0.6 | 4 | $50.85/hr go |
| bottom card alone | $14.00 | 9.4 | 12 | **$9.81/hr no** |
| both on one frame | $14.00 | 0.6 | 4 | **$90.85/hr go** |

A pass published as a green accept, spoken aloud, `is_whole()` so the rig stops
resampling, and written to the append-only journal carrying the wrong card's
distance, deadline, items and merchant. **30 of this driver's 272 cards** arrive
on a frame with two payout-sized amounts.

Fixed by `card_span`/`only_card`: the chosen card's words are the gap between
the two *neighbouring* payouts. That span had to work for both layouts in the
corpus, which print their figures on opposite sides of the money — anchoring on
the chosen payout itself is right for one and points straight at the neighbour
for the other.

Two facts about the rig that keep coming up and are worth not re-deriving, both
measured over the owner's own 272-card export:

- `find_address()` returns `None` on **all 272** texts, and no exported text
  contains a `, ST ZIP` anchor. Every one of those is an *offer card*, though —
  not the dropoff screen the driver taps — so whether it ever fires there is
  still open, and needs health lines from a real shift plus `--keep-scans`
  frames of a tapped screen to settle.
- **129 of 272** cards name no dropoff at all; 78 of those literally print
  "Customer dropoff". Any feature that needs a destination before accepting is
  designing for the minority case.
