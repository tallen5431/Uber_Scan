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

**The hour guard left the third of the three rows it was written for, and the
ledger recorded that row as needing nothing.** The `Thr` fix refuses a leg
whose hour word sits in front of it with no number read. Row 961's card says
`11.5 mi + 1hr 11 min` — 71 minutes — and four of its seven frames render the
hour as `Thr`/`thr` and were refused. **Two render it as `the`**, which is not
an hour word, matched nothing, kept their 11-minute vote and won the
consensus. The rig filed 11 minutes at **$49.36/hr against a target of 25** —
a green ACCEPT, spoken aloud, on a job worth $7.65/hr net. The entry above
listed 961 among the rows that "do not move: consensus was already right".

*Widening it to `the` alone made the row worse, not better.* With those two
frames refused the last one standing is `1hrt1 min`, where the hour group
takes the `1` and the `hr` and the stray `t` throws the minutes out of the
match — so the leg reads ONE minute over 11.5 miles and the row went from
$68/hr to **$750/hr**. Caught by replaying the week rather than by the suite,
which was green throughout.

*So the allowance is for a stray letter after the hour word as well,* and it
is on the hour words ALONE. `the[a-z]{0,2}` would swallow `another` and
`other`; `hr[a-z]{0,2}` catches `1hrt` and nothing in the week or the corpus
besides. Row 961 now has no reading at all, which is the honest answer when
every frame's minutes are damaged — and the only row of 1,166 that moves.

*Measured before it was written, because `the` is a common English word:*
across the owner's 5,491 frames and the corpus's 314 texts it sits in front of
a minutes token exactly twice, both of them row 961's, both in the same
`<miles> mi+the <minutes> min @ Pickup` shape. Three corpus cases pin it,
including `Another 20 min`, which still reads twenty. Five mutations die,
including the one that lets the allowance spread to `the`.


**The end vote published one place as BOTH ends of a job, and the entry above
banked it as a win.** The vote shipped this morning counted every frame's own
`pickup`/`dropoff`. A frame that read ONE name calls it the pickup because it
is the only place it has — that is `find_pickup`'s positional default, not a
reading — and counting those let the default outvote the frames that had
actually distinguished the two ends.

*Measured on the owner's week against the code as it stood before the vote:*
**5 rows published a byte-identical pickup and dropoff** where 0 did before.
`find_dropoff` forbids this outright — "where a job starts is not where it
ends, whatever else is true" — and its own comment calls it "the commonest
wrong answer the parser gave". Row 397 came out `Ridenour Ct` → `Ridenour Ct`
where one frame had plainly read `Dairy Queen Grill & Chill (…)` → `Ridenour
Ct`. Row 2 lost `Culver's` as its start. Row 480 came out REVERSED, the street
as the pickup and `MRR's Deli (…)` as the customer's address.

*And the entry above measured the wrong things.* It checked agreement with the
frames' unanimous verdict and with the card's layout, and never asked whether
the two published ends were the same place. Its "0 destinations lost, 4
gained" counted four re-publications of the start as four gains.

*Three rules, and each was found by a fixture the one before it could not
distinguish.*

  - **Only a frame that saw BOTH ends votes.** The root cause, and it subsumes
    the row-18 case `card_spoke` was written for: seven frames reading one leg
    now say nothing rather than saying it seven times.
  - **The brackets outrank the count, as the layout does.** "A shop is what
    the card brackets," says `find_pickup`. Row 480's subtlety is that the
    WINDOW holds a properly bracketed merchant the voting frame did not have,
    because the OCR closed that bracket on one frame and not another — so the
    merged list knows better than any single frame did, which is what a union
    is for.
  - **A job does not end where it starts.** A count knows nothing about the
    other end unless it is told.

*Everything the original change was for survives.* Agreement with the frames'
unanimous verdict is still 261 of 269, up from 248. Against the card's layout
the numbers are unchanged — 107 starts and 101 ends right, 12 and 18 wrong. 0
destinations lost. Identical ends 5 → **0**.

Two of the first three fixtures written for this passed against the broken
code, because each accidentally supplied a layout or a closed bracket that
rescued the case. The one that pins it carries row 397's own two properties:
no layout, and a bracket the OCR left open.


**Two checks that could not fail, one of which had never executed at all.**
The sixth fault class, found inside this project's own suites.

  - **A round-trip over the CSV export ran zero times, on every run.**
    `rpi/test_stacking.py` fetches `/api/journal.csv`, loops for a row with a
    `scans` column and asserts the frames parse back. The fixture's readings
    are a scanner replay and none of them carries that column, so the loop
    body was never entered. The comment above it hedged — "need not have
    reached the journal by the time the export is fetched" — but the outcome
    was not flaky, it was **0 of 0 on every run**.

    Fixed in two halves, because either alone leaves it able to die again: a
    row carrying real frames is written into the journal, and the loop now
    COUNTS what it found and fails if that is nothing. The frame text holds a
    pipe, which is the whole reason the column is JSON rather than a join —
    the card's icon row and its dividers both arrive as pipes, and joining
    frames with `" | "` once split 19% of its own rows mid-frame.

  - **The corpus's nine `round2` cases never reached the JavaScript.**
    `round2` exists because Python's `round()` takes a half to the nearest
    EVEN digit — 2.675 to 2.67 — where `Math.round` gives 2.68, and the two
    ports must not store a distance that differs in the second decimal. The
    Python runner called `P.round2`, a real call into the module under test.
    The JavaScript runner did the hundredths arithmetic itself, in the test
    file — a third copy of a rule `offer-parser.js` had two of, inline, at two
    call sites. **Either of those two could have been changed with all nine
    cases still passing.**

    `round2` is written once in the JavaScript now, called at both sites and
    exported — the same reason `setting` is exported, which that file already
    says: a rule nothing can reach from a test is a rule that drifts unseen.

*One guard here is a lint check rather than a mutation, and the reason is
worth keeping.* An inlined copy of the rounding behaves identically to the
call, so no mutation can show the difference — it is not wrong until the day
someone changes one and not the other. `rpi/test_lint.py` counts the copies
instead. Writing that check also caught a quoted example of the expression
inside a comment, which the count included; the comment is worded without the
code now, rather than the check weakened to ignore it.

Four mutations, each dying to a named check. Stacking 158 to 161, lint 152 to
154.


**Two pieces of the parser that read as protection and provided none, deleted
rather than documented.** This project's fourth fault class is a branch no
input can reach, and its rule for one is to delete it. Both of these were in
both ports.

  - **`only_card` kept newlines that `normalize()` had already destroyed.**
    The blanking helper was `'\n' if ch == '\n' else ' '`, under a docstring
    that justified it: "line shape is structure: the item count and the Pickup
    anchor are both read off line starts". Both halves are false. `parse()` is
    the only caller and hands in `normalize(raw_text)`, whose whitespace rule
    has already collapsed every newline to a space — there was never a newline
    here to keep — and neither `ITEMS` nor `PICKUP` is anchored to a line
    start: they use `\b` and `$`, and nothing in the file compiles with
    `re.M`. The test that exercises it passes a frame with no newline in it
    either.
  - **A 0.5 mph floor on decimal recovery, at four sites.** `check_distance`
    reaches its recovery clause only after `mph <= MAX_MPH` has returned, so
    `mph` is above 55 whenever the clause runs and `mph / 10` is above 5.5 —
    the floor cannot be the thing that decides. `recover_decimal` has the
    identical shape, and so do both JavaScript twins. Searched exhaustively
    over every whole minute to 600 and every tenth of a mile to 400: **0
    inputs where the floor is what refuses.** Both docstrings described a
    two-sided range and only the upper half was ever live.

*Nothing moves.* The two ports pass unchanged, and a replay of the real week
through the accumulator moves **no field on any of the 1,166 offers**. Five
mutations confirm what remains is load-bearing: each surviving upper bound
dies, at all four sites, and so does blanking at all.


**The address line drew the two ends in the order the FRAMES arrived, on the
one screen that is read while driving.** `places` is the accumulator's union of
every name every frame read, appended as the frames arrive. The two-ends fix
gave `pickup` and `dropoff` the journey order and deliberately left that list
alone — so three surfaces went on joining the list with an arrow and claiming
an order it has not got: `live.html`'s address row and the offers page's log
row and detail row. Measured through the real accumulator over the owner's
week: **12 of 1,166 readings drew the arrow backwards** — `Happy Hawg BBQ
(Hiram)` shown as the destination of a delivery that starts there — and **182
drew a three- or four-stop chain for a job with two ends**, because the union
holds every reading of every name.

*The same page already answered it the other way.* The offers page's detail
SHEET drew `[pickup, dropoff]`, a few hundred lines from the log row that drew
the union. And on the panel, `live.html`'s map mode pinned `pickup` as the
start while its own address row above printed the reverse — ten miles and two
towns apart, on one card, at one moment.

*One rule, in `map-view.js` beside `judge`, `statedBy` and `unchecked`, which
were centralised for this reason.* `MV.ends` REORDERS what the card printed
and never adds to it: both ends must be in `places` or the list comes back
untouched. 12 of the 12 backwards rows come out right and 164 of the 182
chains come down to two ends; **0 rows lose a where-line**.

*The "never adds" half is the part worth writing down, because the first
version of this got it wrong.* Returning `[pickup, dropoff]` outright folds in
a dropoff the DRIVER revealed on their phone — which the offers page keeps in
a row of its own, under its own label, and says why two lines above the code
that would have done the folding: "folding it into Where would hide that a
card printing 'Customer dropoff' now has an address at all". A rule that put a
phone reading in the card's mouth would have been a new fault of exactly the
class this entry is about.

*So the sheet does not ask this rule, and that is not an oversight.* It draws
the two points it is about to map, whichever way each end was learned; "Where"
is what the card printed. Different questions, different right answers, and
both now say so where they sit. The lint added with this change asks that each
page ASKS the shared rule, rather than forbidding the pair from ever appearing
— which was what the first version of the check did, and it failed on the
sheet for being right.

Six checks on `MV.ends` and two in the lint; five mutations die, including the
one that stops checking whether the card named an end at all.


**A distance no frame ever read was counted into a card, and it silenced the
doubt every frame had raised.** A leg claims a slot when EITHER its duration or
its distance agrees — right, and argued at `_slot_for`. What was never decided
is which of two legs gets the slot when both have a claim. The card's print
order decided, and it gave the slot to the weaker claim.

Row 298 is the shape. One frame read the card as a single leg, `5 min
(1.4 mi)`, so the window opened one slot holding both numbers. The next two
frames read two legs — `5 min` with no distance, then `5 min (1.4 mi)`. The
distance-less leg is printed first, matched that slot on minutes alone and took
it; the leg agreeing on BOTH was pushed into a slot of its own. The one
distance that had been read was then counted in both slots, and 1.4 miles
became 2.8.

*The damage is not the arithmetic.* `legs_short_a_distance` looks for a leg
with no miles, found none, so `milesUncertain` went False and `is_whole` True.
A card whose first leg's distance was never read was published as settled — 10
minutes over 2.8 miles, **$18.96/hr, state `no`** — and `is_whole` stopped the
loop resampling the very card that needed another look. What every frame
actually read is 10 minutes over 1.4 miles with one distance missing, which
`rate()` reports as a ceiling: $24.00/hr with `uncosted`, state `warn`.

*Fixed by assigning slots in two passes* — the legs that agree with an open
slot on both fields first, then the rest in print order. Two passes rather than
a sort key, because `taken` moves as slots are claimed and a key computed up
front would be stale by the time it was read.

*What it does to the week: one row, and three fields on it.* Only row 298
moves, and only `miles`, `milesUncertain` and `legDetail`. Nothing else in
1,166 offers changes.

*And what was NOT a fault, which cost a measurement to establish.* The
reporting of this counted 4 rows carrying "a leg that says its distance did not
read while carrying one", and treated all four as damage. Three of them — rows
307, 853 and 951 — are ordinary and correct: one leg, read six times, its
distance caught by two frames and missed by four. A merged slot flagged
`lostMiles` while holding a distance is exactly what a window is FOR. Row 298
is the different thing, and the difference is not visible in the flag: its 1.4
miles were never read as that leg's distance by any frame at all. They are
another leg's number, filed under the wrong slot. The first version of the
comment in the code made the same overclaim and was corrected.

Four mutations, each dying to a named check: the two-pass order removed, the
order reversed, a distance-less leg allowed to match "both", and "both"
loosened to "either".


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
right, 12 and 18 wrong. 0 destinations lost, 4 gained — and that last
figure was wrong, in a way the entry below corrects: all four were the
START republished as the end. The 6 remaining
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

Rows 625 and 881 carry damaged frames too and do not move: the guard drops
their bad votes and consensus was already right without them. **Row 961 was
listed here as a third and it was not one** — see the entry below, which
repairs it. Its surviving frames were the two that lost the hour a different
way, and it stayed in the journal at $49.36/hr on a $7.65/hr job. Row 699
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

**Every payout-free frame was read and thrown away, and the tick is the one
column nothing else can fill.** 31 of 1,166 offers on the owner's week carry a
tick and every earnings figure divides by them. The rig cannot see the Accept
press and must never make it, so the only evidence is the screen the phone goes
to afterwards — and `an_offer` in `digest()` was already separating that screen
from a card in order to hunt for an address on it. One of those frames per
landed card is now kept as a `kind: "screen"` row carrying the raw reading, the
id of the card it followed and how long after.

*Collection only, and that is not temporary caution.* Nothing reads these rows
and nothing writes `accepted` from one. There is no corpus: nothing on file says
what a navigation screen reads as through this camera at night, so a recogniser
written now would be a regex tuned to a screenshot deciding the one field every
figure is gated on, and a wrong tick is a taken job that never happened in the
file that cannot be rewritten. What gets built on these rows gets measured
against ticks the driver made by hand first.

What is written: once per landed card and at most twice, because a navigation
screen sits in front of the camera for a whole delivery and is read every time
the map moves; inside three minutes of that card, so a phone picked up an hour
later is not filed against it; never on a `clipped` read, because `clipped`
means the payout WAS found flush against the top of the crop and the reader
answers it with an empty parse; and the raw reading rather than the flattened
one, because on these screens the line is the grammar.

**Four faults in the first version of it, all found by attacking the diff
rather than by reading it, and all of the kind this ledger exists for.**

*It could file a screen against a card the driver did not take, which is the
only one of these that would have put a lie in the journal.* The slate is armed
by a card REACHING the file, and a card needs two agreeing reads to lock while
only a locked reading is written — so a card can be seen, counted in `saw`, and
never land. That gap is not hypothetical; it is the whole reason `saw` minus
`kept` is on the health line. Reproduced through `main()`: card A lands, card B
is read once and never locks, the driver accepts B, and the navigation screen
after it is written `after: <A>`. Indistinguishable from a real pairing, in the
corpus the detector is to be measured on, in the file that cannot be rewritten.
Any payout that is not the armed card's now drops the slate — a missing row
instead of a wrong one, which is the direction this rig always takes.

*It reused `an_offer`, which would have refused the screens it was collecting.*
That test's second arm exists so an address is never taken off a card whose
merchant survived a lost payout, and it rests on a measurement stated in the
code: a navigation screen names no merchant, "it says `Dropoff <address> 12 min
Start` and `places` comes back empty". Measured on DoorDash. Uber's post-accept
screen names its destination the way a card names a shop — `BCG Atlanta / 1075
Peachtree St NE Ste 3800, Atlanta, GA` off the owner's own screenshot — so the
merchant arm would have thrown away the best evidence in the set, silently, and
left a corpus of only the screens that read badly. The payout alone is the
grammar now, and what the frame named is written onto the row instead of being
acted on.

*"Once per card" was really once per landed ROW.* Both append paths in
`consider` armed the slate outright, and a card does not write one row — it
writes one per reading that improves on the last, plus a settled upgrade. So a
card that landed four rows re-opened the question three times after its screen
had already been answered.

*And the state behind all of it was three fields where two of the guards were
unreachable.* On a fresh log the "already answered" test compared None with
None, came out true, and returned the right answer for the wrong reason — so
deleting the guard that was actually about it changed no behaviour and nothing
in the suite could tell.

One thing was **refused** rather than fixed. A single glared frame of a card
reads as payout-free over a card, which is the positive class in the negative
slot, and the obvious cure is to refuse any frame taken while a card was still
up at the previous read. Measured against the loop: reads are driven by a motion
gate, so the frame right after an accept is sometimes the only one, and refusing
it loses the screen rather than mislabelling it. It is written with
`cardWasUp: true` and superseded by the first clean frame — two rows at most,
sharing an id, separated by `seq`.

Two fixtures were built to drive that supersede through the real loop and
neither survives the screen detector: a light navigation screen blows the
exposure out with the gain already at its floor and never gets read, a dark one
is not seen at all. Both were deleted rather than left in passing for the wrong
reason, and the one thing they were for is asserted on the source instead —
which is the same answer, and the same paragraph of reasoning, that
`read_the_money`'s wiring check in that file already carries.

**The one control on the bar that could not report its own failure.** The rig
emitted a dropoff only from inside `if found:`, so a press that found no
address produced no line at all, and the panel's own thirteen-second timer
repainted the button exactly as it was. The driver tapped the address open on
their phone, pressed, waited, and got the same grey button whether it had
worked or not. Every other control there names its failure: "Took … · not
saved", "Drop · failed", "⟳ failed", "could not set the box: …". A control that
cannot say it failed is one that gets abandoned, and abandoning this one costs
the geography half of the stacking advice — the stack line is already silent on
39% of the pairs it is asked about, and 50% of the owner's offers carry no
dropoff at all.

*Answered from the RIG, not from a timer on the page, and that distinction is
the whole of why this took a change on both sides.* `asked` is
`started < dropoff_until`, so a read that BEGAN before the deadline still
counts and still emits when it lands — 1.8s median on this Pi, 5.9s at worst
measured. A page giving up on its own clock would print "not read" and then be
corrected by a green address a moment later, which is this project's first
fault class used to cure its second. So the rig waits for any read that could
still answer — the same predicate `asked` itself uses — and then says so.

**A check found a real fault rather than guarding one.** The press was closed
only by an address off an *asked* read, so a read straddling the deadline sent
the address, the panel put it up in green, and the press stayed outstanding
until the empty answer arrived over the address already showing: two claims
about one press, the second contradicting the first, on the screen the driver
reads while moving. Any address closes the press now. `asked` still travels on
the message, so the server goes on telling a press from a sighting where that
matters.

On the panel the failure uses the same `failed` class every other control does,
stops asking to be pressed in amber while it is saying it failed — two states
on one button is one too many at 74px — clears when an address arrives, and
clears when a new card lands, because a failure belonging to the last card
would otherwise suppress the amber ask on the next one. Twelve mutations across
the two sides, all killed; the in-flight wait is pinned on the source, because
these checks run `--no-parallel` where a read is synchronous and `reader.busy`
is never true at the moment the window is judged.

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

**The scans were the last thing on the offers page.** The driver's own words:
"make it so it shows the most recent scans at the top, as I have to scroll down
to actually get to them." The list was already newest-first *within itself* —
what it was not was near the top of the page. It sat under the advice block,
four charts, the runs and the pairings, so reaching the thing a person opens
this page to look at meant scrolling past everything they might stay for.

Moved above all of it. The block's own comments had to move with it: "every
figure above stays the whole window's" became "below", and a sheet line reading
"it is in none of the figures above" now says "on this page". The order is
pinned in `rpi/test_offerspage.py` on the source rather than the rendered page,
because it is an order and not a behaviour, and because the way it regresses is
an edit to this file — the same reason `rpi/test_map.py` counts the selects in
its bar.

**"Where the money is" said the offers came to the driver where they already
were, and 86% of them are labelled by where the job ENDS.** `MV.townFor` takes
the dropoff's town and falls back to the pickup's — right for coverage, since a
pickup is usually a merchant with no town in it — but nothing downstream said
which end any row came off. Measured on the owner's week: of 482 placed
offers, **415 are labelled by the dropoff and 67 by the pickup**. So the
closing note was a claim about the driver's POSITION, on a page where no row
carries one, about a ranking that is mostly a ranking of where jobs finish.

The note now says a town is whichever end named one, dropoff first, that a town
near the top is mostly a town jobs **end** in, and outright that nothing here
knows where the car was. Each ranked row carries the tally when it is mostly
one end — counted over that group's own `offers`, so it can never disagree with
the count beside it — and says nothing when it is not.

`townFor` is now derived from a new `townEndFor` rather than restating the
precedence. Written the other way round first, which is two copies of one rule:
the first edit to either would have made the rows disagree with the ranking
they sit in.

*The dollar claim that came with this was refuted and is not the reason it was
done.* Re-grouping on pickups alone, on the driver's own clock, gives 103
offers in 5 towns at p = 0.174 — which does not clear the page's own
`AREA_ALPHA`, so that version would print "this ranking is not worth acting
on". The fault fixed here is the sentence, not the arithmetic.

The suite's fixture carries every ranked town on the PICKUP, so the page can
prove the silence and not the sentence; the other half is in
`tests/mapview.test.js` against `townEndFor` itself, including the case with a
town at both ends — without which the precedence can be swapped and every
other check still passes. Measured, by swapping it.

**The order in the car did not survive the ignition.** `scanner.holding` was
process memory, on "a box velcroed into a car where the ignition is the power
switch" — `rpi/calibrate.py`'s own words. Press Took, drive to the restaurant,
switch the engine off, walk in, come back: no order in the car, the stack line
quiet, Drop and the dropoff scan gone, every card for the rest of that delivery
judged standalone with nothing on the glass saying why. On the owner's week 58%
of accepted jobs have a `go`-rated offer arrive while they are still running,
so that is a real decision made without the figure the feature exists for.

***The comment at `/api/delivered` argued the opposite, and it is answered
rather than ignored.*** It said the hold "is memory only, and a restarted
server simply has no order in hand, which is the safe way to be wrong". Both
halves are right about the ERRORS: forgetting an order that is there costs
advice, remembering one that is not puts a pair rate on the glass for a job
already delivered, and the second is worse. What does not follow is that
keeping it causes the second. `holding()` expires an order on its own stated
time plus `HOLD_OVERRUN` plus `HOLD_GRACE_MS`, and a restored one is read
through exactly that — a hold that has outlived its clock is refused whether it
came from memory or from disk.

Its own file beside the journal, not in it: the journal is the one artefact
that cannot be regenerated and its ingest is idempotent over the whole file,
while this is a scrap of state about right now. Same shape and same reasoning
as `places.json`. Written synchronously on purpose — the whole point is to
survive the instant between the press and the engine stopping, and a queued
write does not.

Both directions on the clock, for the reason `rpi/journal.py`'s `resume()` gives: a
Pi boots in 1970 and jumps when the network arrives, and `over` is
`now − acceptedAt − …`, so a stamp ahead of the clock now reading it never goes
positive and the order would never expire. A missing stamp does the same thing
through NaN, and a string one passes `isFinite` — all three are refused. The
restore answers through `holding()` so the boot line cannot announce an order
`/api/status` then denies, and a hold file that will not parse leaves the
server up and quiet rather than printing a stack trace at a driver who has
never heard of it. Seven mutations, all killed.

**Two rules for what a town is, and the map's ranking used the worse one.**
`map-view.js`'s `townOf` carried its own judgement — a comma, a shape, a
lowercase letter — while `advice.js`'s `PLACE_TOWN` carried another. `townOf`'s
own comment said it had been lifted out of `localityOf` "rather than written a
second time, because the area ranking needs exactly this judgement and two
copies of 'what counts as a town' would answer differently the first time
either was touched". A second copy already existed and already did.

*Measured on the owner's 1,325 distinct place strings, on the driver's own
clock: they disagree on 81 (6.1%), and every disagreement goes map-view's way
and map-view is wrong on all of them.* 69 towns it cannot see through OCR
damage or a ZIP tail (`…, } Acworth`, `322 Thompson Dr, Dallas, GA 30132-3289`),
7 junk strings it accepts (`li woods`, `a tt acworth`), and 5 where it keeps
the damage **inside** the name — so `F Marietta` and `Marietta` ranked as two
towns.

**It changed the advice, which is why this was worth doing.** Ranked through
`Advice.area` instead, 48 more offers are placed, every town gains rows
(Atlanta 98→113, Marietta 84→101, Kennesaw 70→77), the ranking gets *stronger*
— p = 0.008 becomes p = 0.002 — and the order moves: **Acworth falls from 2nd
to 4th and Kennesaw rises from 5th to 2nd**. A driver acting on the shipped
list was being pointed at the wrong town.

The rule is now handed IN rather than copied: `townOf`, `townFor`,
`townEndFor` and `localityOf` take it as an argument and `map.html` — the only
page that calls any of them, and one that loads both files — passes
`Advice.area`. Not a global lookup and not a quiet fallback: without a rule
they answer null, because a fallback is how the duplication grows back.
`live.html` loads `map-view.js` and deliberately not `advice.js`, and calls
none of these four.

One piece of the old judgement stays map-view's and is stated where it lives:
an all-capitals tail is an abbreviation or a fragment of a road name, not a
place anybody lives. `Advice.area` reads `LAS` as a town quite happily, so
`ies, LAS` has to be refused here. The test moved onto the SOURCE string,
because the rule hands back a lowercased town and every answer would pass it
otherwise — and the answer is title-cased on the way out, since that is what
the ranking prints while the rule lowercases in order to compare.

### The maps, again

**The map could not say where the money was, and the obvious way to make it
say so is noise.** The driver asked for "areas where it might be best to find
high paying rides, the time of day and day of the week likely also a critical
factor". The page had no answer: it was built to check whether the rig was
right about where the work happened, which is a narrower question.

The feature everybody wants is a league table of the places the cards named.
**It is a coin toss.** Permutation-tested on the owner's own week, on his own
clock: 19 places clearing 5 offers on 2 outings, p = **0.2260**; with a floor
of 8, p = **0.9400**. The table that would have shipped reads *Shake Shack
$18.57 ... Chipotle $7.27*, a best-to-worst spread of $11.30 — and dealing the
same rates out at random makes a spread that big or bigger **36% of the time**.
A driver would have crossed town to sit outside a restaurant chosen by chance,
on a page that had told them it was the best one.

The TOWN survives: 9 towns, 367 offers, p = **0.0000**, Atlanta $20.01/hr to
Dallas $13.54. It survives both objections a sceptic raises. Not one night out
of the metro — restricted to the 8 towns seen on four or more separate outings
it is still p = 0.0000. Not trip length wearing a hat — tested inside each
third of the distance range it holds in all three (p = 0.0000 / 0.0020 /
0.0000) with Atlanta leading each, and Atlanta's median trip is 9.2 miles
against Marietta's 9.5 for $20.07 against $14.63.

**And it shipped once with most of that spread being the clock.** A town's rate
is tangled with WHEN the driver is in it: 12-3am paid $21.24 and 3-6pm $14.17,
and 57 of Atlanta's 98 offers are in the first while 40 of Marietta's 82 are in
the second. Raw, Atlanta led Marietta by $5.38; held at the same hours it is
$2.45, best-to-worst falls from $6.47 to $3.69, and three towns change places —
a number a driver acts on, four times larger than the truth. Caught by two
independent readers of the working tree before it reached `main`, not by the
suite, which was green. The ranking is now by what is left once each offer is
measured against its own three-hour block, and the permutation is confined to
shuffle WITHIN blocks so the test asks the question the number answers. Once a
block is picked there is nothing left to hold still and the page says so.

So `Advice.areas` groups on the town the rig read off the CARD, never on a
coordinate, and **runs the test in the page** on whatever is loaded rather than
trusting a threshold tuned to one week. The ranks are computed once and a
shuffle only reassigns them, so it is O(n) a shuffle and costs milliseconds.
What the driver gets on their own week is nine towns and "chance does this well
under 1% of the time"; pick a three-hour block and the same page says the
ranking is not worth acting on — on his clock not one block he works can tell
its towns apart (12-3am leaves one town standing; 3-6pm, 6-9pm and 9pm-12 come
out at p = 0.18, 0.58, 0.08).

Three things worth not rediscovering:

  - **It asks nobody anything.** The grouping is off the card, so the ranking
    is on screen the moment the offers land, before "Place them on a map" and
    whether or not it is ever pressed. A lookup may POSITION one of these
    figures and may never CHANGE one, which is the rule at the head of
    `map-view.js` applied to arithmetic instead of to distance.
  - **`daysIn` was the wrong count for this and `outingsIn` exists for it.**
    A block lies inside one calendar date by construction, which is why
    `daysIn` counts dates; an area does not. A single shift from 8pm to 2am
    touches two dates, so a town seen on that ONE night out reported two days
    and cleared a floor of two — the "one evening wearing a habit's clothes"
    the floor exists to refuse, arriving through the calendar. On the owner's
    week the calendar says six dates where five shifts were driven.
  - **`whenNote` was switched to outings wholesale, and half of it wanted
    dates.** The day cuts need `outingsIn` — a Saturday night spanning midnight
    is one outing — but a BLOCK lies inside one calendar date by construction,
    which is `daysIn`'s own stated argument where `daysIn` is written. Switched
    for both, the sentence under a single 12-3am block read "2 separate days of
    it are in this window" whenever the fixture's offers straddled 4am. It
    depends on the wall clock, so it passed when it was written and went red in
    the gate hours later. `whenNote` now picks the count from what was picked.
  - **And the fixture that caught it was wall-clock-dependent itself.** The two
    towns in `rpi/test_map.py` took their town from `i % 2` and their night
    from `i % 2` as well, so each landed on exactly one outing and the
    two-outing floor dropped both — the same coupling the advice fixtures had
    already been caught on once. Town and night are separate terms now, the two
    towns sit five hours apart so they are always in different blocks, and the
    single-town state the page needs is BUILT rather than searched for. Held
    green at every three-hour offset around the clock.
  - **Measure on the DRIVER's clock.** The first pass of every figure above was
    taken in UTC by a container four hours away, which puts each offer into the
    wrong three-hour block: a census of 382/220/112/0/0/0/254/198 against the
    true 196/33/0/0/2/361/201/373 that `advice.js` already recorded. The town
    ranking is timezone-free and was unharmed; the weekend/weekday figure was
    not, and read twice as strong as it is ($15.23 v $13.20 at p = 0.0000
    against the true $14.93 v $14.05 at p = 0.036).

**What it will not answer, and says so on the page.** These are the offers that
came to the driver where they already were. A town they have never sat in
cannot appear, and one they passed through once will not clear the floor — so
it ranks the places they already work, not everywhere they could. No amount of
data from this rig fixes that: the rig only ever sees the offers that reached
it.



**The chain told the driver to press a button that cannot place the job it
was about.** `chainRun` counts the taken jobs sitting inside a hop that are
not drawn. `MV.jobsIn` gates on `pickup || dropoff`, so a taken job whose card
named NEITHER end is never in `placedNow` and never in `drawn`, however many
times the walk runs. Counted as "not in the last lookup" it printed **press
"Place them on a map"** — an instruction that cannot be followed, on a line
that can never clear. 62 of the owner's 1,166 rows name neither end and **4 of
his 31 taken jobs** do.

This is the same defect the nag under the `when` box had, recorded above, and
it is fixed the same way: count against what COULD be placed rather than
against everything. The hop still says the car did not go straight from one
end to the other, because that is true; it stops claiming a button will mend
it.

*The headline had to move with the popup, and that is the half a first pass
would have missed.* `broken()` decides whether a hop's miles go into
"straight-line miles nobody paid for" — the figure this whole toggle exists to
report — or into the "job missing inside" bucket. Left out of it, a hop
holding an unplaceable taken job counted as a distance nobody drove, inflating
the one number a driver reads as real. The first three mutations passed with
that still wrong, because the checks only read the popup text; a fourth check
pins the headline, and at "any time" that hop is the only broken one, so
dropping `nowhere` makes the clause vanish outright rather than shift a
decimal.

Four checks, four mutations, each dying to a named one. Map 166 to 170.


**"Forget lookups" threw nothing away, and said it had.** The button cleared
the browser's copy of the geocode cache and printed "remembered lookups thrown
away". Every answer this page has ever produced is POSTed to `/api/places`,
`loadPlaces()` GETs the whole set back, and `load()` is what runs on the next
press of Load **and when the page opens** — so every lookup came straight
back, on the first thing anyone pressed afterwards. The one control that can
remove a bad geocode removed nothing, and the page said otherwise.

*Not the cure that was refused.* Per-place correction was proposed twice and
refused twice, and this is not it: it is the wholesale wipe the page already
offered and could not deliver. `DELETE /api/places` removes the file and says
how many it held; already-absent is the state it asks for, not a failure.

*And the words now match in both directions.* On success the page says it
reached the server and how many went. When the DELETE fails it says "cleared
on this device only — the server still has them, and the next Load will bring
them back", which is the sentence a driver actually needs, instead of
reporting a success it did not have.

Five mutations die: the endpoint removed, the count faked, a reply sent
without removing anything, the page not asking the server, and the words no
longer saying where. Server checks 151 to 157, map 162 to 166.

*Two of the three problems finding this cost were mine, and are worth the
line.* The first probe cleared the cache in the middle of the driver and moved
"a second run re-asks only what it could not ask the first time" from 1
question to 3 — the check reading an emptied cache, not a fault in the page;
it runs last now, with the reason beside it. The second waited a fixed 800ms
for the DELETE and read the server before the fetch had finished, which looks
exactly like the fix not working.


**"Drawn end to end" was two different numbers on one screen, and the status
line counted an accusation as a success.** `map.html` draws a pair whose
pickup or dropoff landed nowhere near the rest of the shift as a **red dashed
line captioned "This cannot be right"**. Three readers decided that
separately. `render()` and the sidebar's heading tested `impossible ||
fromStray || toStray`; `placeAll`'s own `drawn` — the figure printed in the
status line under the same map — tested only `impossible`. So the line under
the map said a pair had been drawn end to end while that pair sat on the map
in red, dashed, accusing itself.

*The stray half cannot be folded into `impossible`, and that is why the two
rules could differ at all.* `impossible` needs a stated distance to argue
against — a yardstick — so on a card that gives no distance it cannot fire
however far the pin lands. A stray end is then the only thing saying the pair
is wrong, and the status line was the one reader not asking. 15 of the owner's
579 both-ended pairs are in that state.

*One rule, `MV.accused`, beside `judge`, `statedBy`, `unchecked` and `ends` —
the same drawer, for the same reason.* All three readers ask it, and the
sidebar's own comment already said what the page must not do: "a map that
quietly shows the third of the offers it managed is a map that says the rig is
doing better than it is."

*The test that matters is the one that could tell the rules apart, and the
first one could not.* The suite already had a stray in a `placeAll` run — but
that pair was ALSO `impossible`, so both rules agreed on it and a mutation
putting the old test back survived. The scenario added here gives the card no
distance at all, which is what leaves `impossible` unable to fire: both pairs
place at both ends, neither is impossible, one has a pin in another state, and
`drawn` is 1.

Eleven checks on the rule and the run, four in `rpi/test_lint.py`, and five
mutations die — including each of `map.html`'s two readers quietly reverting
to `p.impossible` on its own. The lint names both readers separately rather
than asking whether the file mentions the rule anywhere, because one reader
reverting while the other still asks is exactly the shape of this entry.


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
pressing Place could not move it — 62 of the owner's 1,166 rows name neither
end. (That figure said 58 when it was written and was wrong then, not made
stale since: replayed at three of today's revisions it is 62 at every one.) And widening the box **without pressing Place again** left the window
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

**The MILES cell printed the distance from before the repair.** `scan.html`'s
three figures under the headline exist to be checked against the phone, and
this one took the PARSE's distance while the rate above it, the journal row
this page writes, `live.html`, the Pi's panel and the CSV all take the
verdict's. On a card stating a deadline and no duration the parse never checks
the distance at all — `milesChecked` is `minutes !== null` — so `rate()` is
where a lost decimal is put back, and this cell showed the figure from before
it. The corpus's own $41.11 DoorDash card with `9.8 mi` read as `98 mi`, at
18:57: headline **$127/hr ACCEPT**, PAY $41.11, MIN 18, MILE **98.0**, with
this page's own note directly underneath saying a decimal had been recovered.
Nothing on that screen added up — $41.11 over 18 minutes less $0.30/mi on 98
miles is $39/hr, not $127.

The cell one line above it has taken the verdict's minutes since the billed/
card split, under a comment saying this row exists to be checked against the
phone; this one silently did not. `846c050` fixed the ROW for this exact card
and left the SCREEN two lines away. The fixture builds its deadline from the
browser's own clock, so the card states the same eighteen minutes whenever the
suite runs, and it asserts the preconditions — that the parse leaves this
card's distance unchecked and reads it as 98 — so that a future parser change
making the two figures equal cannot let it pass for the wrong reason.

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

**The phone and the keypad priced a mile at nothing, and called 182 of the
week's offers a green ACCEPT that the rig would not have.** `rpi/calibrate.py`
states the distinction where the answer lives: `offer_parser.DEFAULT_SETTINGS`
has `costPerMile` 0 and means *"nobody has told me what this car costs, so do
not invent a deduction"*; `SEED_SETTINGS` is the other question, *"what should
a driver start from"*, and says 0.30. That file already records the two being
confused once — "written out by hand in three places, one of which was a
diagnostic that hardcoded 0.30 while the parser it was diagnosing used 0" —
and `ui.js` and `scan.js` were the fourth and fifth. Both took the parser's
refusal as the driver's starting line.

Measured on the owner's week, every row of which the rig scored at 0.30 and
re-scored at 0: **182 of 1,157 offers (15.7%) come out a green ACCEPT the rig
would not have shown green, at a median $6.80/hr overstatement**, and 202 more
soften from PASS to CLOSE CALL. A third of the week reads more favourably on a
phone than it does in the car — a wrong number on a screen the driver acts on,
on the two surfaces that have no calibrate step to correct them.

Both now seed from 0.30. The three are held together in `rpi/test_lint.py`,
which also asserts the parser's own 0 is still 0: it is not a stale copy of the
seed, it is the other answer, and an edit making all four agree would delete
the distinction. All four drift directions were mutated and each killed a
named check. A driver who genuinely pays nothing to drive a mile still sets it
to zero, and `ui.js` already relabels "net pay" to "trip pay" when they do.

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

**`FULL_FOV_MODES` had a second copy that nothing read, and a card-height floor
was argued for with a number the code has never used.** Two documentation
faults in the files that decide where the camera points.

  - **A dead second table.** `rpi/scan_pi.py` carried its own `FULL_FOV_MODES`
    with a paragraph explaining that the IMX519's two smaller modes are
    *cropped* out of the sensor rather than scaled down. Nothing read it —
    `start_camera` takes `main_size` straight from the config and never checks
    it against the table, and no test mentions it — so it stated a rule the
    file it sat in does not apply, with no caller to make the two observably
    drift. Deleted; the live one is `rpi/calibrate.py`'s, which `--mode` is
    chosen from.

  - **The comment justifying the card-height floor named 350px.** The constant
    beside it is 380, the refusal `rpi/calibrate.py` prints says "below about
    380 px", `rpi/README.md` says 380 and `rpi/test_calibrate.py` pins 380 — so
    the one drifted copy was the comment that exists to justify the constant.
    It also argued that refusing anywhere between its two numbers "would be
    enforcing a preference as though it were a limit", beside code that refuses
    below 380, which is inside that range. A reader tuning this floor was being
    argued at with a number nothing has ever used.

**The preflight answered "can this rig focus?" from every tuning directory on
the machine, while the loader only ever reads this pipeline's.** `tuning_report`
searches all three ISP directories on purpose — its comment says so and
`rpi/test_camera.py` pins it — because "there is an autofocus tuning here and it
is for the wrong ISP" is exactly the diagnosis somebody needs. `rpi/doctor.py` then
built the VERDICT out of that listing: `usable = [t for t in tunings if t[1]]`
over every directory. On a Pi 4 with an autofocus tuning under `rpi/pisp/` and
none under `rpi/vc4/` it printed `ok  autofocus available` and ended **All
good.** over a lens libcamera will never move.

That state is not hypothetical: `camera.tuning_dirs()`'s own docstring records
this machine having been in it — "the search fell through to pisp looking for
autofocus and found it there", and handing a pisp tuning to vc4 registers no
cameras at all. The rig's own answer for the identical machine is
`supported: False`, which the autopilot speaks as "no working autofocus" and the
scan loop prints as "focus not settable". And the fix line — the one instruction
that repairs it — is printed only on a failure, so it was withheld precisely
when it was needed.

`camera.focus_answer` is now the single rule, the restricted search plus the
`UBERSCAN_TUNING` override, and both `start_camera` and the preflight ask it.
A stranded file is named as one rather than counted as missing, and the listing
still shows it, marked `(not loaded here)`. The tuning root is overridable
through `UBERSCAN_IPA_ROOT` for the same reason `UBERSCAN_SYNC_TIMER` is: a
branch that can only be exercised on a machine with tuning files installed is a
branch nothing runs until it is wrong again.

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

**A clock behind the stamp clamped the backup's age to zero, so the check could
not fail.** `rpi/doctor.py` measured it as `max(0.0, now - last['at'])` and then
asked `hours < 24`. With this machine's clock at or before the stamp that is
`0.0`, so the line printed `ok  offers backed up off the car   0 min ago, to
http://nuc.lan:8080` — a specific, confident number — over a copy nobody had
reached for days, and `0.0 < 24` is always true, so in that state the check
could not fail at all.

Not a contrived state. By this project's own boot model a Pi has no clock, boots
in 1970 and jumps forward when the network arrives — which is the same
condition, **no network**, under which the backup is most likely to be stale —
and fake-hwclock restoring a pre-shutdown time after the engine cut power does
it too. Measured end to end against a real `rpi/sync.py` run: a four-day-old stamp
reports `96.0 hours` with the clock right and `0 min ago` with the clock five
days behind. Reproduced at six hours, forty days and fifty-five years ahead;
all three printed the same zero.

Every other place here that turns the Pi's clock into a judgement guards it
first — `futureCeiling()` falls back to the fixed ceiling, `todaySummary()`
reports `clockSet`, the scan loop refuses deadlines below `CLOCK_BELIEVABLE_AFTER`,
and `rpi/sync.py` defines that constant and is imported two lines above this —
and this was the only verdict about the one artefact that cannot be
regenerated. It now says it cannot tell, and names the clock, the way the
`last is None` branch above it already handles its own ambiguity. This is the
fourth way the rig has reported a healthy backup it did not have.

**The journal-writability probe created the journal.** The comment said "it
creates nothing that was not there, writes no byte, and asks the filesystem the
exact question the scanner will ask it" — and `open(path, 'a')` creates the file
when it is absent, which is every first run on a fresh rig, the run this
script's own docstring recommends. The claim is load-bearing: it is the
justification for running this probe against the file the project calls
irreplaceable. Worse with `sudo`, which most of the doctor's own fix lines begin
with: the journal is then created root-owned in a user-owned directory and the
scanner, running as the driver, cannot append to it — the preflight causing the
fault it exists to find. The absent case now asks the DIRECTORY, which is the
same question the first row will ask it.

**Two uploads in flight together each appended the whole batch, and the
doubling then hid a real gap from the repair that exists to find it.**
`/api/journal/ingest` is a read-modify-write — read the journal, build the
`seen` set of sync keys from what came back, append what is not in it — with
nothing holding the three steps together. `readWaiters` serialises the READ
and nothing else, and for two overlapping ingests it makes matters *worse*:
they share one read, so they are guaranteed to see the same pre-append
journal. Each finds every key in its batch absent and appends the lot.

*Measured against a real server*, not argued: a 400-row journal, two
simultaneous POSTs of the same 60 rows. Both answered `added: 60, have: 460`.
The file held **520 lines, 460 distinct keys, 60 stored twice** — in the one
file this project calls irreplaceable, with `ok: true` on both replies.

*The second-order harm is the one that costs offers.* `rpi/sync.py`'s
shortfall check compares ROW counts on both sides, not distinct offers. A copy
whose rows are doubled therefore reports roughly twice what it holds, and the
check cannot fire until the copy has lost more than half of everything. A
genuine gap then sits behind the doubling indefinitely, with the ordinary tick
printing success and `doctor` green.

*And the collision needs no contriving.* `rpi/sync.py`'s own stderr tells the
operator to run it by hand with `--all`, describing it as "safe, just slower",
while the installed ten-minute timer keeps ticking. A retry after a dropped
connection can also overlap the request it is retrying.

Fixed with a serial queue around the read-modify-write — a queue rather than a
flag, so a caller cannot forget to wait. Every exit from the handler now goes
through `fail` or `finish` and both release, because the failure mode of a
lock is worse than the bug it fixes: one stranded request would hang every
upload after it. Each early exit was walked separately against a live server —
an empty body, a malformed line, a batch already stored, and a journal that
cannot be read at all — and an ordinary upload still goes through after each.

Four checks in `rpi/test_server.py`, and the lock removed fails three of them
with 80 rows where 50 belong. Two guards inside it cannot be killed by any
test and say so in the code rather than pretending otherwise: the
double-release guard, which no current path reaches, and the `setImmediate`,
which buys latency and not safety.


**One bad byte put "Offers are NOT being saved" on the driving screen over a
journal that was taking every write, and it never cleared.** `rows()` opens the
journal `'rb'` and decodes one line at a time with `replace`, so a corrupt byte
costs its own line and no other — that is a fix this file already records.
`count()`, ninety lines further down in the same class, opened the same file
with a bare `open()`. The decode then happens strictly inside its loop, one
byte that is not valid UTF-8 raises `UnicodeDecodeError` out of it, the blanket
`except` catches it, and the answer to "how many rows are in this file" is
**0** for a file holding a year of work. The same question, answered two ways,
in one class, drifting by the whole file.

*The half that reached the driver is worse than the count.* That `except` calls
`_complain`, which sets the error `failing()` reports and `live.html` prints as
**"Offers are NOT being saved"** — the one notice this project added so a
driver would know the irreplaceable file had died. `rpi/scan_pi.py` calls `count()`
at startup and reads `failing()` on every heartbeat, so the notice stood from
boot, over a journal in perfect health, and led the note list.

*And it did not clear on a successful append, which is what the code looked
like it promised.* `_error` is cleared only by an append that works — but the
next `count()` raised again and set it straight back. Measured on the five-row
fixture `rpi/test_journal.py` already ships for the sibling bug: `rows()` 3,
`count()` 0, `failing()` set **before and after** a row was written on top.
The notice stood for the rest of the shift and came back on every watchdog
restart.

Fixed by reading it the way `rows()` does. Counting needs no decode at all —
the question is how many lines were written, and a line that will not parse was
still written — so the loop counts non-blank lines in binary and cannot raise
on the file's contents. Four checks added to the fixture that was already
there, and the text-mode open dies to three of them.


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

**The machine holding the only off-car copy was installed by typing a command
into a terminal.** The rig gets a systemd unit and the sync gets a timer; the
receiving end — which holds the one artefact this project calls irreplaceable —
was documented as `SCANNER=0 JOURNAL=… npm start` and the words "that is the
whole install". So the backup ended the moment that machine rebooted, the
terminal closed, or an unattended upgrade restarted something.

*And nothing would have said so.* `far_end()` returns None on a refused
connection and `rpi/sync.py` exits 0, both deliberately, because a car is offline
most of the time and a timer that complains every ten minutes about a normal
condition is a timer nobody reads. Correct for being out of range — and it
means a backup that has simply stopped looks identical from the car, while the
only copy is one SD card in a vehicle.

`rpi/install-service.sh` now takes `COPY=<path>` and writes the same unit with
three lines changed: `SCANNER=0`, `JOURNAL`, and no audio or video groups. One
script and one template rather than two units that drift — the two ends run the
same server, which is the whole reason this works at all. Each of the three is
checked in BOTH directions, because `SCANNER=0` on the rig stops it scanning
just as surely as its absence on the copy machine starts a restart loop against
the missing picamera2. It also makes the journal's directory and hands it over,
which the README told the operator to do by hand: the installer is already
root, and that is the one moment in the install where it is free.

`tools/install-sync.sh`'s own failure text pointed at `SCANNER=0 npm start` and
omitted `JOURNAL` — so an operator following the gate's advice landed the only
backup inside the clone, next to a `git clean`. It names the installer now.

### The panel

**A health window whose only news was "a card reached the journal" was thrown
away, and the offers page then called that card missing.** `saw` goes up on the
first read that finds a payout; `kept` goes up on the read that lands the row.
They are different moments, and `Health.report` resets the window between them
whenever a boundary falls in the gap. On the owner's own week **104 of 1,166
offers** have at least one read between the two — median 3, p90 5, max 7, which
at a 1.85s read is three to thirteen seconds.

`note_tally` refused to write any window without a `saw`, so when no other card
arrived in the second window the `kept` was dropped; the health line was gated
the same way, so the log said nothing either. `server.js` sums both over the
rows that exist, so a 1 and a 0 reached the offers page as "**1 offer is
missing from everything above**" — about a card sitting in the journal. That is
the figure whose whole job is to say what the file is missing, reporting a miss
against a file that is complete, which is the fault the forty lines of comment
around it were written to fix for glare frames, arriving through the window
boundary instead. At 1,166 offers over 27.9 driving hours it is on the order of
one phantom a week, and the point of the number is that it is trusted.

`worth_recording` is now the single rule and takes either count. The gate is
kept, because a quiet two minutes with the phone out of the mount is still not
evidence and would bury the windows that are.

**The kept engine's failure policy was the opposite of what two texts said, in
both directions.** `rpi/pipeline.py`'s own header and `rpi/README.md` both say
that any failure — a missing library, a missing symbol, an init returning
non-zero, an exception mid-read — hands the read back to the binary
permanently, with one line in the log. The handler stated a third thing in its
own comment, "this one is dead; the next read builds a fresh one. Twice in a
row and the library is the problem", and honoured none of the three.

A failure inside the constructor never reached `_tess_off` at all:
`engine = engines[key] = _Tesseract(...)` does not assign when the constructor
raises, so `engine` was still None and the `if engine is not None:` guard
skipped both the close and the giving up. An `Init2` returning non-zero — no
`eng.traineddata` where the library's NULL datapath resolves, easily different
under the systemd unit from the shell the binary was tried in — therefore
printed nothing, left the library live, and made the rig re-attempt
`TessBaseAPICreate` and the LSTM model load **on every read for the rest of the
shift** before running the binary anyway. And the retry policy the comment
described was never implemented: nothing counted to two, and one exception
inside `read()` already turned the library off for good.

Permanent is the right one and is what was promised. The existing check could
not see any of it: it set `_TESS_SAID = True` with the note "the message is not
what is tested" and never looked at `_TESS_LIB`, so the missing log line, the
still-live library and the per-read model load were all invisible to it.

**Seven screens name the reason a verdict was withheld, and every one was
missing a different one.** `rate()` can refuse to price a card for six reasons
— `pay`, `time`, `rate`, `speed`, `leg`, `screen` — and seven surfaces turn
that into words: the Pi's panel and its voice, the driving view's label and its
voice, the phone scanner, and the keypad's label and its refusal toast. The
panel had no `leg`; the voice had no `rate`, `leg` or `screen`; the driving
view and its voice had no `screen`; the phone had neither `leg` nor `screen`;
the keypad had no `rate`. Each fell through to "READ AGAIN", so the same card
was named on one screen and unexplained on the next.

The project had already fixed one instance of this drift and left five behind:
`rpi/scan_pi.py`'s own comment says the `rate` entry was added "because without it
this panel fell back to READ AGAIN while the other two screens named it".

*And the check written that day to stop it happening again could not see the
two reasons that were forgotten next.* It derived the list from
`inspect.getsource(doubt)` and took the `return` values out of it, which finds
four of the six: `leg` and `screen` are decided in `rate()`, not in `doubt()`,
and are assigned rather than returned. So the panel had no name for `leg` for
as long as `leg` existed, under a check whose own comment said the next reason
could not be forgotten and a paragraph in `rpi/README.md` repeating it. That is
the sixth fault class — a check that cannot fail for the case it names — and it
is worse than no check at all, because the sentence beside it is believed. Both
have been corrected, and the derivation moved one step back: the list is the
parser's, and the lint holds the list against the source.

The gap is sharpest on the keypad, because `rate` is the ONLY reason that
catches a decimal that slipped while staying inside `SANE_PAY`. **$11.84 typed
as $118.40 is one wrong key** — 0 instead of `.` — and over twenty minutes it
is $355/hr. The pad refused it correctly and then said "CHECK THAT AGAIN" where
`scan.html` and `live.html` both name the two figures. `index.html` includes
the shared parser for exactly that refusal; the sentence the driver read did
not agree with it.

The WORDS stay with each screen — a 480x320 hat, an 800x480 panel, a phone, a
keypad and a voice genuinely need different ones — and the LIST is now shared:
`DOUBT_REASONS` in both parser ports, with `TYPED_DOUBT_REASONS` for the four a
typed entry can reach. The keypad builds `rate()`'s argument itself, with no
legs and no card text, so `leg` and `screen` cannot fire there and naming them
would be a dead branch; `rpi/test_lint.py` refuses both directions. It also
holds the list against what `doubt()` and `rate()` can actually return, so a
seventh reason cannot be added without every screen being told. Nine mutations
die, one per table plus the list itself.

**Numbers in the documentation that nothing counted, and had drifted.** Both
of these are the fifth fault class, in the two files that describe this
project rather than run it.

  - **The caption table was miscounted in its own suite, twice.**
    `rpi/test_layout.py` said "only two entries" declare a tail the 3.5" hat
    may ellipsise; **three** do. The third is `the figure at its longest,
    nothing found`, whose tail is `" · 1 not found"` — added deliberately
    because "not found" and "not asked" are not interchangeable, and then left
    out of the record of what the clamp eats. The same file said the row "can
    say twenty things" where it can say twenty-one. The entry above this one
    repeated the first of those, naming two of the three tails.

    Corrected, and the suite now ASSERTS both numbers rather than describing
    them, so the next entry cannot be added without that paragraph being read
    again. Both assertions die when the old figures are put back.

  - **The two suite tables were stale in 24 of 36 rows and disagreed with each
    other.** Measured against a real run: `tests/corpus.test.js` was 720 in
    `rpi/README.md` and 681 in `SCANNING.md` against **793**;
    `rpi/test_layout.py` said 429 against 795; `rpi/test_server.py` said 48
    against 157; `rpi/test_lint.py` said 59. And `rpi/test_gps.py`, 89 checks,
    was in **neither document** — a whole suite with no row anywhere.

    The counts cannot be checked without running everything, which is what
    `tools/test.sh` is for. What can be checked is that no suite is missing
    from the list, which is the half that goes wrong in silence: a suite is
    added, nobody writes the row, and nothing ever says so. One check per
    suite file now, 37 of them.

*That guard caught its own author within the minute.* Adding those 37 checks
took `rpi/test_lint.py` from 156 to 197 and made the row just corrected for it
stale again — which is the whole argument for the table above in one move.
(This sentence said 193, which was the count before the ledger entry beside it
added four more backticked paths for the file-exists check to walk. The
commit's own README row says 197. Two numbers written minutes apart, in the
entry about numbers nothing counts.)


**Two notes on the driving screen that described a moment long past, one of
them masking the note that was about now.**

  - **The notice strip read "starting scanner" between every pair of offers,
    all shift.** `phase` is set from any message carrying a `phase` key and
    never cleared. `rpi/autopilot.py`'s last word before it `execv`s into the
    scanner is `{phase: 'scanning', message: 'starting scanner'}`, and
    `rpi/scan_pi.py` emits **no phase at all** — so that message was the last
    one there would ever be, and the between-offers branch appends
    `p.message` to the strip unconditionally. That branch is where this rig
    spends most of its time, as the dashboard suite's own comment says.

    A phase is a moment, not a state, so the spent one is dropped when the
    scanner itself speaks — the thing it was narrating has happened. Only
    `scanning`: `error` and `aim` are states a driver has to act on and must
    outlive a heartbeat. The headline does not move, because
    `PHASE_LABEL.scanning` is `WAITING FOR AN OFFER` and so is the fallback
    when there is no phase at all.

  - **`trackNote` printed a lifetime counter in the present tense.**
    `QuadTracker.jumps` counts every re-lock since the process started and is
    reset nowhere — not even by `start_over`, the ⟳ Re-find path, which
    clears `misses`, `_off_since`, `agreeing` and `_candidate` and leaves this
    alone. So one re-lock at any point put "re-locked on the phone" on the
    detail line for the rest of the shift. The rig's own health log carries
    the same number correctly labelled, "re-locked %dx since start".

    **The cost was the note underneath it.** The three clauses are an
    `else if` chain with the lifetime count sitting between two LIVE states,
    so after the first re-lock the drift note could never be shown again.
    Saying a true thing about the past in the present tense cost the one note
    here that is about now.

    Not replaced with a recent-re-lock note, because nothing measures one:
    `status()` publishes `jumps`, `moves`, `misses` and `rebaselines`, and
    every one of them counts since start.

*Why the suite could not see either.* Every phase check in
`rpi/test_dashboard.py` pushed `message: ''`. The probe added here sends the
message the rig actually sends, and reads the strip from the between-offers
branch. Three mutations die: the spent phase kept, the wrong phase cleared,
and the `jumps` note put back. 565 checks to 568.


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
texture". Three lines declare a trailing clause the hat may eat, and
that is all any of them loses: `" · 1 not asked"` and `" · 1 not found"` off
the detour's tally, and `", so no distance"` off the misread-name line. (This
said "two lines" and named two of the three; `rpi/test_layout.py`'s own
comment said the same, and both were corrected once the table was counted.
The suite now asserts the two numbers rather than describing them.)

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

**Two copies of the 4am day boundary, and nothing held them together.**
`advice.js` holds the number — the area ranking needed to know how many
separate OUTINGS a town was seen on, which is not the same question as how many
calendar dates — and `journal.html` and `map.html` read it from there. The
driving screen does not, because it does not load `advice.js` at all: it is the
screen in the car, it has to come up from the service worker with no network,
and pulling a library in for one integer would be paying for that at the worst
possible moment. So the second copy stays, and it is on purpose.

What the copy costs is drift, and the drift would have been silent and
expensive. The boundary decides which offers belong to tonight, so a panel at 4
and a journal at 3 print two different takings for the same shift with neither
able to say which was the shift — the same fault the `MAX_PLACES` and
`TEXT_KEPT` checks in `rpi/test_lint.py` exist for, arriving through a copy
this project decided to keep. So the copy is allowed and the drift is not: the
same file now reads the integer out of both sources and compares them, and
asserts that the two pages which *can* import it still do rather than quietly
growing a third. All four failure shapes were mutated and each killed a named
check.

**The pair line outlived the order it was about, by one second, for ever.**
`render()` runs on the one-second tick and repainted `showStack(r.stack)` from
`last` — the stored reading, whose stack was computed while an order was still
held. That undid all three of the page's own `showStack(null)` calls: press
Drop and "+ $26 to $35/hr with the one you have" was back under the verdict a
second later, beside a Drop button that had already gone, until the next
reading arrived 2.5 to 6.0 seconds after. The un-tick path never even
flickered, because that handler calls `showDrop` and `showDest` and not
`showStack`.

`server.js` fixed exactly this on the RELOAD path and its comment describes the
same screen — "press Drop and reload, and the panel showed '+ $25-50/hr with
the one you have' under the verdict while the Drop button beside it was hidden
because nothing was held" — and wrapped `/api/status`'s `last` in `withStack`.
The live path was left holding the reading's own copy. The page now applies
`withStack`'s own rule to the stored reading: no hold, no pair line.

It bites in the ordinary stacking case, which is not rare on this driver's
week: 58% of accepted jobs have a `go`-rated offer arrive while they are still
running, and 7 of 30 consecutive ticked pairs actually overlap. The check waits
a full tick after the press, because the press itself clears the line — the
fault is what the repaint puts back — and it is measured on both panels.

**The one page that must survive a dead network never asked for the offline
shell.** `sw.js` lists `live.html` in ASSETS and this project states the
panel's offline requirement as a hard constraint — it is the screen bolted to
the car, and it is the stated reason the panel does not load `advice.js` for a
single integer. It never registered the service worker. The only three
registrations were `scan.js`, `ui.js` and `journal.html`, so the panel was
covered only when the same browser profile had already opened the keypad, the
phone scanner or the offers page, and then only because `sw.js` claims clients
at scope `/`. On the Pi that is usually true — `index.html` is where the driver
lands and `ui.js` registers there — so the exposed profile is a browser pointed
straight at the panel's own URL and nothing else, which is the dashboard
and the 480x320 hat.

*The obvious fix is dead code on this page, and the check is what proved it.*
Copied from the keypad, `window.addEventListener('load', ...)` registers
nothing at all: the panel holds an open MJPEG stream, so the load event never
fires. Written that way first, the new check timed out waiting for `load` and
counted zero registrations — so the version that looks right in a diff and does
nothing was caught before it shipped. It registers at the end of boot instead.

The existing checks made the gap look covered without testing it:
`rpi/test_scanjs.py` asserts every `.html` in the directory is in ASSETS, which
is a check about the LIST, and separately that `scan.html` registers. Nothing
asked this page. It does now, in a browser context that opens nothing else,
because sharing a context would test the mask rather than the gap.

### The offers page

**A pairing's withheld claim was printed as its opposite.** "Beats finishing
what you have" is the one clause of a stacking answer stated flat, because it
is the only one that does not depend on the geography. `Advice.stack` returns
`sure` for it and that field had three meanings in two values: the claim made
and yes, the claim made and no, and the claim **withheld** because the offer
card printed no chargeable distance, so the pair's rate is a ceiling while the
rate it would be held against is net. `journal.html` read it as `sure ? 'yes,
even sharing no road at all' : 'no — the worst end is below finishing alone'`,
so every withheld pairing was told the opposite of what had been withheld. Of
the (held, gross-offer) pairs drawable from the owner's own week, **77.4% have
`worst >= alone`** — the printed "no" is false about three times in four.

`sure` is now `null` where the claim is withheld and the page has three
branches, the third naming the ceiling. Null and not a second field because
there is one question here and "not asked" is one of its answers; every reader
that tests it for truth — `live.html`'s ` · beats finishing alone`, the panel's
own line — keeps behaving as before, null being falsy. `server.js` recorded it
as `!!s.sure`, which flattened the three back to two on the way to disk, and
now stores the null. Rows written before this carry `false` for both and
nothing can separate them afterwards: the comparison it rests on is not in the
file. The check that pins it is three pairings in one feed, and it fails if any
two of them read alike.

**One row with a stamp no clock can read collapsed the whole page into "Cannot
reach the scanner".** The by-time-of-day pass has had a guard for such a row
since a card arrived stamped `1e20` — `Advice.blockOf` returns null and the row
is counted, not dropped. The day-of-week pass 70 lines below it never got one:
it walked `offers` itself and indexed `week[dayOf(r.at).getDay()]`, which is
`week[NaN]`, which is `undefined`, and the push threw. `render()` runs inside a
`.then()`, so the TypeError went to `load()`'s `.catch()` and the page painted
a positive claim about the network over a journal the server had read perfectly
and answered 200 with: headline, both charts, the week chart, "What you took",
the whole offer log and every caveat line gone, and **nothing in the console** —
no `pageerror`, no `unhandledrejection`.

It needs 14 or more distinct days in the window as well as the corrupt stamp,
which is why no fixture reached it: the existing `no clock` feed is four rows
three hours apart, so `enoughDays` is false and the pass never ran. Both passes
now read one list — the pass above keeps the rows it could place and the one
below walks those — so the readable/unreadable verdict is made once rather than
in two places that can drift. The count is named on both headings. The new feed
is the clean three-week one plus the poison row, and it must produce **the same
seven bars with the same medians and counts**, which is what makes it a check on
the row being skipped rather than on the page merely surviving.

**A failed range press left the three biggest figures on the page standing.**
The page is read over Tailscale from a machine in a car, so any range button can
land while the link is down. The handler for that clears the log, the charts,
the pairings, the search sentence, the headline and every caveat — and did not
touch `p25`, `p50` and `p75`, which are the largest type on the page and the
only thing above the fold. So the previous window's answer stood in full size
under "Cannot reach the scanner", unlabelled, to a question the driver had since
asked differently. The empty-window path has always set all three to `--`; this
handler was written separately and did not. The check presses a range button
with the next fetch rejected, and reads the figures before the press as its
control.

**The running-cost note counted the rows the page had just said it left out.**
`showCaveats` was handed `kept` — every row in the window — and its last note
describes the rows the FIGURES are made of. The note directly above it says how
many readings were "left out of the figures above", so the two sentences
disagreed by exactly that number: **26 of 1,166** on the owner's own week.

Not only the count. A set-aside row is the likeliest one to carry a different
cost per mile, because the keypad and the phone write zero where the rig writes
$0.30 — so a window of four net rates with one doubtful keypad row in it printed
"the figures above mix what offers paid before the car with what they paid after
it" over figures that mix nothing at all. It now gets `offers`. The fixture is
four counted rows at $0.30 and two set-aside at nothing, and on the old code it
produces that exact sentence.

**The Shop bar was half cards the card never called shop orders.** The chart is
meant to split on what the card called itself, and the paragraph above it says
so at length — "an item count is a fact about the OCR". The rule underneath was
`r.shop ? Shop : r.legs >= 2 ? Rides : (typeof r.shop === 'boolean' || r.items)
? Shop : Not stated`, and its `typeof` clause is unreachable: it needs `r.shop`
falsy AND a boolean, i.e. exactly `false`, which no writer can produce —
`rpi/journal.py` writes `True if parsed.get('shop') else None`,
`journal-client.js` writes `parsed.shop ? true : null`, and the parser emits
only `True` or `None`. Measured over the week: 1,133 rows with no shop field, 33
with a truthy one, **none with a false one**. So the clause that actually
decided it was `r.items`, the one thing the paragraph refuses to split on, and
`rate()`'s own comment records DoorDash printing "4 items" on a restaurant
pickup nobody shops for.

Measured on the replayed week: the shipped rule gave Rides 109 / Shop 49 (median
$12.42) / Not stated 982, and 26 of those 49 — **53% of the bar** — were
single-leg cards never called shop orders. That 49 is the same 4.2% of rows the
week's `items` figure counts, which is the cross-check that it was the item
count deciding. On the chip alone it is Rides 109 / Shop 23 ($11.05) / Not
stated 1,008. The dead clause is deleted and `r.items` with it.

**A refused window left the previous one's figures standing under the
refusal.** `showAdvice` has two exits: the ready one ends in
`showAdviceCost()`, and the not-ready one wrote the refusal, blanked the
working and returned — while leaving the section VISIBLE. So the ordinary
after-shift sequence put "not enough trips yet" on the glass with the last
range's wait table, line-set-against-line-kept sentence and "N% of the time
the car was empty" still underneath it, with nothing saying they belonged to a
different window. It calls `showAdviceCost(a)` on that path now, rather than
blanking the element, so one function owns what that section holds.

Pinned on the source, and that is the honest trade rather than the lazy one:
the sequence it guards is ready-then-refused, and no fixture in that suite can
produce it — the ones whose advice is ready are ready on every range and the
ones that refuse refuse on every range, so a browser check written over them
would pass with the line deleted. That is the shape of check this project
removes. `rpi/test_loop.py` makes the same trade for the same reason.

**The three biggest figures on the page did not say what they were figures
of.** "$11 · $15 · $20 /hr" under "quarter below · typical · quarter above"
are percentiles of every offer READ, which is a fact about the market and
reads exactly like a fact about the driver. 935 of the owner's 1,166 offers
are PASS and 31 were worked: the median of what was actually ticked is
**$30.20/hr against a typical offer of $15**. The same confusion was caught
once already one line down — "$21 TYPICAL" reading as a payout rather than a
rate — and fixed by attaching the unit to the figure. This is the other half:
the unit says `/hr` and the label now says of what. The check asks the MIDDLE
one specifically, because a noun on either wing while the figure in the centre
still reads "typical" leaves the misreading where it was — measured, by
mutating exactly that.

**The line got an apparatus; the other number in every verdict was never
checked once.** A verdict is (pay − miles × costPerMile) ÷ hours. This project
built `replay`, `bestAt`, a plateau, a stability test across six break
thresholds and leave-one-night-out validation to check the THRESHOLD, and has
three Settled entries refusing rules that lose to it. It never asked whether
the denominator's input is right. It is not measured — it is a seed:
`rpi/calibrate.py` sets a new config to 30c and its own comment calls that "a
petrol midsize with some depreciation in it", a figure the driver is expected
to edit. On the owner's week it is 30c on all 1,166 rows, which is what never
editing it looks like.

It matters because it moves the answer. `Advice.costLadder` re-scores the
window at half the driver's rate through double it, and on that week:

| a mile costs | line | range | the driver's $25 |
|---|---|---|---|
| $0.15 | $24 | $24–29 | inside |
| $0.22 | $21 | $21–27 | inside |
| **$0.30 (theirs)** | **$20** | **$20–25** | inside, at the top edge |
| $0.45 | $18 | $18–21 | **outside** |
| $0.60 | $16 | $16–20 | **outside** |

So "your line is right" is true *conditional on a number nobody measured*. The
page says so now, and only when the recommendation actually moves across the
sweep — on a week where it holds at every rate there is nothing to warn about.

The rate is read off the rows rather than asked for: every row carries the
deduction and the distance it was applied to, so it is already in the data.
Median, because one misread distance would otherwise move it. The sweep is
anchored on the driver's own rate rather than a fixed list — a table not
containing their number would be answering somebody else's question — and each
rate is re-scored THROUGH `usable()` rather than beside it, so a sweep can
never drift from the figure it is a sweep of.

*Two things the tests caught that the code claimed.* "A dearer mile can never
ask for a higher line" was asserted as arithmetic and is false: the replay
picks the best of a ladder of whole dollars, and lowering every rate can move
which rung wins either way. It held on the real week — $24, $21, $20, $18, $16
— and that is a fact about that week. And an explicit `if (!(mine > 0)) return
null` could not be made to fail: a null rate and a zero rate are both already
refused further down, so the branch went, and the behaviour it stated is
pinned against the outcome instead.

### The advice

**The page said where to draw the line and never what holding one costs.**
A line is a decision about WAITING and nothing priced the waiting. What makes
that worth pricing is that offers are not scarce: 1,140 reached this rig over
26 hours of scanning, **43 an hour, 81% of them less than a minute after the
one before**, and genuinely distinct — only 1.1% of consecutive pairs share a
payout, 3.6% share both ends. Declining costs seconds, so the line is the whole
game. Three things now sit under the recommendation, all off offers already in
the journal:

  - **What each line takes and what it costs.** At $20, 24% of offers clear it
    and the next is 2 minutes off; at $25, 9.4% and 6 minutes; at $35, 2.3% and
    28 minutes with a 2.6-hour tail. Measured inside runs, so a break is never
    a wait. The lines are the DRIVER's target and steps either side, not a
    fixed ladder — a table that ignores the number in their settings answers
    somebody else's question.
  - **The line set against the line kept.** $25 in the settings against a
    median $30.20 actually ticked — the top 4.8% of what came past, worth about
    $3/hr in the replay. Silent when nothing is ticked: the median of what
    merely arrived is the market, not a decision.
  - **Where the clock went.** 13.6 of 26.4 scanning hours carrying somebody, so
    48% of the time the car was empty. Intervals MERGED, so a stacked pair
    occupies the clock once (summing durations gives 15.5 h and 59% busy), and
    the clock runs to the end of the last trip rather than the last scan, which
    is `replay()`'s own stated rule.

*The idle figure is a ceiling and says so.* An unticked trip is
indistinguishable from a break, so `unexplained()`'s silence count rides with
it. **With no ticks at all the figure is refused outright** — the first version
announced "100% of the time it was on, the car was empty" over a driver who had
simply never pressed the tick, a false headline over a true caveat. Caught by
the offers-page fixture, which has no ticks in it.

*And the closing sentence of the working had to change.* It said what a driver
would earn an hour "depends on how much of that time was driving rather than
parked, which the scanner cannot see" — which was true until the paragraph
above it started reporting exactly that. The scanner still cannot; a tick can,
for the trips that got one. Left standing it would have denied a number printed
four inches above it, which is the fifth fault class.

**Two acceptance rules were tested against the replay and both lose.** Recorded
here because both are things a driver would reasonably try.

  - **$/mile costs 24% against $/hr.** Same shift, same replay: best $/hr rule
    $19.80/hr at a $22 line; best $/mile rule $16.03 at $1.00/mi; a payout
    floor $14.25, barely above taking everything at $13.94. Combining did not
    help — $/hr >= 20 AND not a shop order came out at $19.18, below $/hr >= 20
    alone.
  - **A line per hour overfits.** In-sample the 12-3am block wants $30 and
    earns $29.64 where a flat $22 earns $24.63, which looks like $5/hr left on
    the table. Leave one night out, fitting on the other four: a line per block
    $19.50/hr, one fitted flat line $18.93, and **a plain $22 fitted to nothing
    $19.76**. The fitted line is worse than the unfitted one. Night-to-night
    swing is $13.92 to $27.06 and swamps the tuning.

None of these model the drive to the pickup — `toPickupMinutes` is null on all
1,166 rows — so the absolute figures are optimistic. The comparisons between
rules are fair; the omission falls on all of them equally.


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
The day-of-week pass is the one that does not walk `offers`: it walks the rows
the by-time-of-day pass could place, because a stamp with no readable hour has
no readable weekday either and that is one verdict, not two. `enoughDays` in
front of it is a COST guard and nothing else — it stops a fortnight's bucketing
being thrown away on a short window, and for a while this entry described it as
though it guarded the pass against bad input. It does not; see "One row with a
stamp no clock can read" under Done for what that cost.

**Do not narrow `Advice.busy` or the day grouping to the 300 rendered rows.**
The busy chip and its note describe the whole window, so a join over a sample
would make the sentence disagree with the list beneath it.

**Prewarming the parse at boot is not obviously right.** It moves a ~300 MB
allocation and several seconds of CPU into the one moment memory is tightest —
boot is when the scanner is starting Python, OpenCV and Tesseract. Do it only if
the first load after a reboot is reported as a real problem, and then delay it a
few seconds after `listen` rather than running it inline.

**A silence does not mean the driver accepted, and no threshold makes it
one.** Only 31 of 1,166 offers carry a tick, every earnings figure on every
screen rests on those 31, and the obvious way to recover the rest is to read
the gaps: a stretch with no cards in it looks exactly like a driver who is out
on a job. `unexplained()` already counts those stretches, so listing the offer
in front of each one and asking "did you take this?" is a few lines away.

**It is wrong, and the owner's own week says so against the ticks it already
has.** These are known accepts with a known job length, so sensitivity here is
measured rather than argued:

| a silence of | catches | of the 31 known ticks | and also fires on |
|---|---|---|---|
| 5 min | 17 | 55% | 61 offers that were not ticked |
| 10 min | 12 | 39% | 26 |
| 20 min | 6 | 19% | 12 |
| **30 min** (what `SHOWN_AT` uses) | **2** | **6%** | **8** |

The cause is not a badly chosen threshold, it is the app: **offers keep
arriving during a job.** Median stated length of a ticked job is 29 minutes and
the median gap to the next card after one is **5.4 minutes** — 45% of accepted
jobs have another card on the screen inside five minutes, 16% inside one. That
is the stacking feature working as designed, and `Advice.stack` exists in this
repo because of it. A phone that goes on offering work through the whole
delivery cannot fall silent to mark the start of it.

So the prompt would miss more than half of what it is for at its most generous
setting and 94% of it at the setting the pages actually use, while proposing
several times more offers than it got right. Filling the gap in the record with
guesses of that quality is worse than the gap: a wrong tick is a taken job that
never happened, in the one file that cannot be rewritten, and it moves every
$/hr figure that follows.

*The 8 unexplained silences the offers page reports are still worth the
driver's attention* — they are the stretches nothing accounts for, which is a
true statement and is all that page claims. What is refused here is reading
them backwards into "these offers were accepted".

**What is left is the screen**, which is where the evidence actually is: after
an accept the phone shows a navigation screen carrying "Deliver to <name>", a
turn instruction and a speed limit, and no payout and no Accept button
anywhere on it. The rig computes `an_offer` for exactly that shape already and
throws the frame away. Nothing on file says what one of those screens reads as
through this camera, at night, so there is no corpus to build a recogniser on
and none can be invented from a screenshot. Collecting one is the next step,
and it must not write `accepted` until it has been measured against ticks the
driver made by hand.

### The maps

**Do not tune the acceptance line to the hour, the weekday or anything else in
your own history.** It is the obvious next step after the by-time-of-day chart
and it loses money. In-sample the 12-3am block wants a $30 line and earns
$29.64/hr where a flat $22 earns $24.63. Held out one night at a time, fitting
on the other four: a line per block earns **$19.50/hr**, one fitted flat line
**$18.93**, and a plain $22 fitted to nothing **$19.76**. Fitting makes it
worse, both ways. The night-to-night swing on the owner's week is $13.92 to
$27.06 and no tuning survives it. `advise` already gives the answer the data
supports — a plateau, and whether the driver's line is inside it.

**Do not judge offers on $/mile, or on a payout floor.** Replayed over the same
shift: $/hr at $22 earns $19.80/hr, the best $/mile rule $16.03, the best
payout floor $14.25, and taking everything $13.94. $/mile is 24% worse than the
rule the rig already uses. Combining them does not help either.

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

*Still refused, and the box now holds a weekend/weekday cut anyway — which is
not the same thing, and the difference is the word `x` above.* Every figure in
this entry is about weekday CROSSED WITH block, and a grid is what two
controls side by side build. There is one control: the day cuts are options in
the same `when` select as the hours, so picking `weekends` un-picks `9pm-12`
and the thirteen one-date cells cannot be reached. `rpi/test_map.py` asserts
that there is exactly one `select` in the bar, so the refused question stays
unreachable rather than merely discouraged.

The coarse cut alone is supportable where the crossed one is not: 598 counted
offers on 3 outings against 542 on 2, $14.93 against $14.05, p = 0.036. The
seven-way split needed no rule of its own — Saturday, Friday and Tuesday each
rest on ONE outing, so the two-outing floor under every figure on that page
drops them and what is left cannot be ranked against itself.

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
cache away. The cure proposed by the audit was refused; see Settled.

*This entry used to end "the button at least works now", and that was wrong
twice over.* It cleared only the browser's copy while the server kept every
answer and handed them back on the next press of Load, so it threw nothing
away at all — see Done. It does now, and the entry above is what is left after
that: wiping every good lookup to remove one bad one is still the only remedy
this page has.

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

***Done — the town table shipped, and it is `Advice.areas` on the map.*** The
paragraph below is what it was built from and every word of it held up. What it
did not anticipate is that the ranking needed a significance test of its own:
the place-level table it warns about is noise at p=0.23, and the map now refuses
any ranking that does not beat chance on whatever is loaded. The hour is held
still per the paragraph further down — Atlanta's raw lead over the fourth town
is $4.20 and $1.09 once each offer is measured against its own block. See "The
map could not say where the money was" under Done. The rest of this entry
stands as the record of why the heat map itself is still refused.

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
| Six surfaces at once — the reader's ends, the map pages, the offer log, the two ports' shared corpus, `server.js`, the docs — each finding then attacked by two lenses | 20 raised, 17 survived, 3 refuted. All 17 fixed across 16 commits, `fd4253d..55cd663`. |
| The same six again, plus that sweep's **own** commits, which had never been read by anything but their author | 18 raised, 17 survived, 1 refuted. Two of the 17 were faults the previous sweep had introduced the same day (`_voted_end` publishing one place as both ends of a job; the hour guard leaving the third row it was written for, recorded in the ledger as needing nothing). All 17 fixed across 6 commits, `ce62ad8..a4755ac`. |

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
