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

### The harness

**Every claim this project has made about being green was made in a zone the rig
does not run in.** `tools/test.sh` named no timezone. Six suites read the local
clock — `blockOf` buckets by hour, the 4am day boundary, every "took 3 for $48"
day header — so they answered in whichever zone the machine happened to be in,
and the machine was UTC while the driver is at UTC-4. Measured:

| | |
|---|---|
| `node tests/advice.test.js` in the container | All 410 passed |
| `TZ=America/New_York node tests/advice.test.js` | **409 passed, 1 FAILED** |
| `grep -n TZ tools/test.sh` | nothing |

The failure was `tests/advice.test.js`'s `A.blockOf(8.64e15) === 0`. `blockOf` is
`floor(getHours() / 3)` on the LOCAL clock and the largest representable instant
is 20:00 in New York, so the answer there is 6. The assertion's own comment says
what it was for — "the guard has not swallowed the ordinary case with them" — and
that claim is about whether a block came back at all, not which one. It now
asserts `!== null` and passes in America/New_York, UTC, Asia/Kolkata and
Pacific/Kiritimati.

*Not repaired the obvious way, which would have been unfalsifiable.* Deriving the
expectation as `Math.floor(new Date(8.64e15).getHours() / 3)` is `blockOf`'s own
body, so the check could never fail — this project's sixth fault class, installed
in the one file whose job is to catch it.

`tools/test.sh` now exports `TZ="${TZ:-America/New_York}"`, defaulted rather than
forced so a caller can still prove a suite is zone-independent — which is how the
one failure was found. `rpi/test_lint.py` holds the runner to it, and holds it to
naming the driver's own zone ON THE EXPORT LINE: written first as a search of the
whole file, it was satisfied by the explanatory comment, so `TZ=UTC` passed while
reinstating the exact fault. Three mutations, three named kills. All 37 suites
pass on the driver's clock; that one assertion was the only casualty.

**README said the withheld verdict was the rig's alone, and SCANNING.md said only Uber's wording is read.** The keypad withholds on four typed reasons (CHECK THE PAY, CHECK THE TIME, CHECK THE DISTANCE, CHECK PAY AND TIME; ui.js) and refuses LOG on the same four. The camera screens add CHECK THE TIME for a second leg they could not time, and NOT AN OFFER for a route planner or idle screen. The first rewrite called both of these a figure to check. The parser also reads a DoorDash Deliver-by card: '$8.75 / Deliver by 7:15 PM / 5.2 mi' at 6:45 PM is 30 min, $14.38/hr, PASS. Checks: 'README says what the keypad shows when it withholds a rate', 'README names what the camera screens add (2)', '...and does not call a screen that is not an offer a figure to check', 'SCANNING.md's limits name the deadline card the parser reads', 'SCANNING.md no longer says only Uber's wording is handled', 'rpi/README.md no longer says only Uber's wording is handled'.

**A mutation that has the same byte length as the source it replaces, written within the same second, is served from the stale .pyc, so the Python suite runs the PREVIOUS source.** Measured on this lane: `(mine, legs)` came back as 11 failures, exactly the prior mutation `(text, legs)`'s result. With a fresh PYTHONPYCACHEPREFIX per run it is 2. A reported mutation result from a Python suite is valid only when the bytecode cache is bypassed or moved for each run. Restoring in a finally does not help, because the stale file is the cache, not the source.

**rpi/test_loop.py's dropoff-window checks fail on timing, not on code.** The three failing checks are 'a press that found no address is answered, not left silent', '...and the log says it too' and '...said once'. They fail 4 runs in 4 against an untouched archive of 466b0cd on this 4-core host (load 0.86). The same tree passed once. On upgrade/parser-fix they failed 2 of 3 runs. The run lasts 6 s against a 1 s window, so the answer depends on scheduling. A check whose verdict depends on the host's load cannot be used to judge a change. It needs a clock the test drives.

**No read was ever timed on a Pi, one kind at a time: every cost this project states for the rig is an estimate or an x86 figure (unsure_payout's "about 1.5-2 s on the Pi (an ESTIMATE)", the spare threads' 407 -> 259 ms measured on the development box, the raise's +4559 ms read off the owner's health line).** `rpi/bench.py` sweeps sizes on a frame the owner saves, and times only the plain read. `tools/pi_bench.py`, run on the rig, draws its own screens (`rpi/testcards.py`, invented, no camera) and times N reads (5) of each of the six the rig makes — UberX through the centred box; DoorDash's stops card through a box drawn round an Uber card, rescued by the finder with its evened second read (the shadowed sheet) and again with the sheet refused and the box raised (a card stacked above it); that card's next read through the remembered crop; the planner across the whole screen; the map label — each with the spare threads on and off, one frame read again so every read of a kind does the same work, and prints median / p90 ms, how many gave the card's own answer, and the temperature (vcgencmd, else the thermal zone) and throttle flags (`scan_pi.throttling`) before and after. Safe beside the service: no camera, no file written, niceness 10, the service's state said under the table; a 150 s budget ends each cell early (after one read) so a Pi 4 is done inside three minutes. **Measured on x86** (N=2, this container): each case took the links it is named for (crops read: box, found, found evened; box, refused sheet, raised 0.09 and with spares the 0.18 started ahead; one read through the remembered crop), every read the card's answer; the whole run 7.3 s. The Pi's own table is what it is for and is not here yet. Checks: `tools/test_pi_bench.py` (34, a few seconds of reads on x86: --n 1 --json exits 0, the six reads in order, each timed once and right both ways, nice 10 or more, the heat before and after or why not, the service's state, nothing written in the repository, the table's lines, the 150 s default). Open: the owner's first run on the rig.

### The reader

**Five tesseracts could read at once on the Pi's four cores, and nothing ranked a card read above a map label.** The paired frame, the rescue's two links started ahead and DoorDash's map label each had an engine on a thread of its own, every one measured alone. The 9 Nov shift (931c50c) put the read itself at `read 979–1526` ms median, against 392 ms for the same card on `tools/pi_bench.py` with the service stopped, at 120–169% of a core and a load of 2.1–5.3. Every engine call now takes a slot (`pipeline.OCR_SLOTS`, 4, one per core) ranked card read, then spare link, then label, and the label reads only while fewer than two engines are (`LABEL_BELOW`); a link the chain let go of is stopped at its next slot (`_drop`, `_Dropped`). `UBERSCAN_OCR_SLOTS=0` is exactly the old behaviour.

*Two slots, the first guess, was measured and refused.* `tools/pi_bench.py --busy` (new: the scanner's `Reader`, `MapLabels`, `MapBands` and `write_snapshot` beside a stand-in camera loop, on rendered frames) on the development box, 4 cores, 30 DoorDash first reads a setting: the rescue read 182–186 ms median with no gate, **278 with 2** (every link waited for the box's reads, 143 ms median), 218 with 3, 190 with 4, 182 with 4 and the label held below 2. Uber reads 69–71, the remembered crop 94–96 and the loop's tick p95 8.4–9.6 ms at every setting; no tick late.

*And the gate did not find the gap.* On that box the busy reads took what they take alone (Uber 70–72 ms busy, 76 on the plain bench; three or more engines reading under 5% of the time), and switching off the label, the spare threads, the live view or the map band moved no median beyond ±5 ms. So the Pi's 2.5–4× is not reproduced by engines sharing cores; on the Pi the gate's effect on the printed read is an **estimate** of about nothing. What will say where it goes: `--busy` on the Pi (`alone` against `busy`), and the health line's new part, `ocr slots 4, reads waited 0ms median (...), label OCRs N of M waited +Xms median, ..., engines at once 1:A% 2:B% 3:C%` (`ocr` on the `seen` row), said when the gate held something back or beside a `time:` part. Not done, measured: a slower live view while a read runs (the view off moved the busy read by nothing), and reading the paired frame only when the first is unsure (a single frame 69 ms against a pair's 72 per frame; it is `unsure_payout`'s evidence).

*Accuracy against cf10ded,* over the 1,076 rendered frames of "The rescue's next read is started early" (rpi/README.md) read in pairs (2,152 frames through `look_many`, the spare threads on), through two slots and through one (the gate at its tightest: 1,156 of 2,152 reads waited, 139 ms median): **every frame the same payout, journey, crop, text, rescue and finder's word**, 1,318 frames with a payout on each side. No money rule was touched (CENTS_LOST, unsure_payout, money_is_clipped, rescue_refused), and the parser corpus does not pass through the gate.

Checks: `rpi/test_pipeline.py` (the slots handed out in rank order, the label held below a paired read while a spare link reads, a dropped link stopped and counted, no limit at 0, the environment's value, real paired reads the same through 0, 1 and 2 slots with a label reading beside them, `ms.slot` on every read), `rpi/test_scan_pi.py` (the part's figures and words, said only when the gate held back or beside `time:`, `ocr slots off`, through `Health` with a dark read left out), `tools/test_pi_bench.py` (`--busy`: three runs, both cards right, the tick and the stages timed, the label only beside the busy runs, the gate's figures only on its run, at most four engines, nothing written).

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

**A card's lost-leg check was asked of the whole frame against the legs the card boundary kept, so the bracket of a leg the boundary had cut read as a leg of this card that lost its minutes.** Measured on the week after 466b0cd: rows 908 and 450 went whole -> not whole on every frame in both ports, with untimedMiles 5.4 and 3.6. They were never spoken, the panel never settled, and they were journalled whole=0. No later frame could clear it. With the other card's distance the longer one, the panel printed 'a leg this reading could not time — 19.4 mi of it' about a card whose one leg was timed. The fix asks shortATime/untimedMiles of this card's words (`mine`) against every leg the frame read. The trap: that bracket was the only thing withholding two rides the frame had cut off after their first leg. With the fix alone, row 410 went from doubt to go, $98.31/hr, whole. So half_a_ride ships with it: another card in shot, one non-total leg, distance after its time -> short a timed leg of unknown size. It fires on 4 frames, rows 410 and 450. Checks: 'a crop whose card above is the longer journey...', 'row 410: a ride cut off after its first leg...', 'whole / row 908...', 'whole / one bare leg on a frame holding ONE card is left as it was...'.

**'Both apps print a payout to the cent' was false, and a next-card headline test built on it let a whole-dollar card below run into the one above.** Row 475 prints `$6 Guaranteed (incl. tip)` on all 7 frames, rows 374/479/584/602/604 print $6 or $7 the same way, and row 79's ride prints `$18 * 5.00`. A headline is now cents OR the card's label or the rider's star directly after it. Over every frame and text of the week, 0 of 121 cents-less non-chosen figures have a label or star directly after them, so it moves 0 rows. The residue, stated: 144 of 208 cents-less chosen payouts have junk between figure and label, and the gap cannot widen, because row 505's map glyph `$5 | Guaranteed` has the same shape as row 314's real `$19 | Guaranteed`. It errs long. Checks: 'a whole-dollar card below still bounds the first: DoorDash prints `$7 Guaranteed`', '...and so does a whole-dollar ride below, by the rider's star', 'a bare $5 off the map...'.

**The cards the reader guessed at now keep their picture, flag or no flag.**
338 of the week's 1,166 offers landed a row the reader was unsure of — 328 on
`recover_decimal`'s divide-by-ten (`milesCorrected`), 9 doubted, 9 suspect, 4
with uncertain miles. A wrong decimal guess moves the cost line tenfold, and
only the picture can say whether it was right, but pictures were kept only
under `--keep-scans`, off by default. One picture per doubtful offer (the read
that first landed it doubtful) now goes to `scans/doubt/`, capped at 400 (about
16MB, about eight days at that week's rate), oldest first, and the log says once
when a folder reaches its cap. Removing the keep fails 'a card the reader
corrected the miles on keeps its picture, with no flag asked'; keeping every
read fails '...one picture per doubtful offer' (2 for 1).

**The app's zone prompt was journalled as an offer, and the panel gave it a
verdict.** "Switch to this zone with peak pay! +$1.00/order ... Avg. offer wait
1min ... Don't switch" had its bonus read as the payout and the zone's wait as
the job's time: five times in the owner's week, three of them a confident PASS
($12.00/hr, $20.00/hr twice, $10.91/hr), one withheld, all counted in their
day. `PAY_IS_PER_ORDER`, in both ports beside `PAY_IS_A_DURATION`, refuses a
dollar figure followed by `/order`: the only money on all 29 of the prompts'
frames, and on no other frame of the week's 5,491 or text of the corpus's 340.
Refused at the figure rather than the screen, because anchoring on the
headline would also wipe a real card's payout in a crop that held both; the 14
real offers under a "Busy + Peak Pay" banner do not move, and seven are corpus
negatives. The prompt is written as a collection-only `kind: 'promo'` row, once
per bonus per five minutes. A skeptic found the first version left the card's
screen slate armed, so a navigation screen after the prompt was filed against
the card before it (reproduced through main(), 18s after); the slate is now
dropped on every read of a prompt.

**Uber's Est. delivery card was invisible. A town took the line under it as its
second name. And the card's own route line was read as a divider.** On 8
October an Uber Eats Early look card reached the rig printing `Est. delivery
4:15 PM • 8.6 mi`, where all 27 Early look rows in the owner's week print `N min
(x mi) total`. It parsed to $14.48 and 8.6 mi and nothing else: incomplete,
`empty`, no verdict, never journalled.

`DELIVER_BY` is widened to that wording in both ports, as one rule, not a
second. Its distance group, glued on by Uber's bullet, marks where the line
ends. The merchant and destination are then read from there by the same
leg-tail code that reads them after a total leg. At the phone's 3:45 PM the card
is 30 minutes, `fromDeadline`, $23.80/hr CLOSE CALL.

The group's glue is LEG's, measured on the card's own bullet: a glyph on 104 of
110 readings, a bare space on 6. A bare space still names no place on that
frame. It carries no charger-badge lookahead. LEG and LONE_MILES now share one
`NOT_THE_CHARGER`, `(?!\s*from\s+f)`, because the badge is `from f…` on all 476
of its readings. Before, a merchant called `From The Earth Brewing` cost the
card both ends and its distance: $28.96/hr, uncosted.

The Jimmy John's snap read the Accept button as `Pverel 8) 4 P`, and the dropoff
went to the journal as `Shadowood Pkwy SE, Atlanta Pverel`. Now `line_starts()`
says where the reader began each line. A town that has reached `PLACE_TOWN`
takes a name from the next line only if that name sits right after the town's
first name and the line is address-shaped. Refused: 97 readings in 53 rows, all
furniture or the next field. Kept: `Springs` and `County` wrapped onto their own
line (68 readings).

`Matching may take longer`, `Includes expected tip` and `Early look` all end a
place now.

Two shapes the chip had been hiding:
- **The route line.** Uber's line from the pickup's dot to the destination's
  reads as a pipe at the head of the lines it crosses. In front of the
  merchant's bracketed branch it cut the merchant's name off, and row 86
  published `(Dallas) Bone Creek Xing & River Run Dr, Dallas` as its pickup. In
  front of an address's wrapped last line it published `NW, Kennesaw` as the
  dropoff (rows 61, 277, 309). Both are drawing now, not dividers.
- **Scraps between the comma and the town.** `…, 28 kt Kennesaw` never matched
  the town rule. Two readings of one address became a two-stop route on the
  offers page (row 423). Those scraps now come out first, but only after an
  address-shaped head: row 397's merchant line has a comma in it.

| replay of the 1,166-offer week, both ports, bf/replay → q4/parser-fix | |
|---|---|
| rows moved | 174, every one in pickup/dropoff/places |
| ...moving a published pickup or dropoff | 136 |
| pay, minutes, miles, deliverBy, verdict, rate, whole, doubt moved | 0 |
| readings where the ports disagree | 0 before, 0 after |
| published rows showing one address twice | 15 → 9 |
| published ends with a scrap before the town | 71 → 12 |
| published place that was a wrapped town line, now the whole address | rows 277, 363 |
| row 86 pickup | `(Dallas)` → `Los Portales Mexican Restaurant (Dallas)`, and a dropoff |

*Not better:*
- Row 61 publishes no place. It had published a merchant fused to half a
  street, and `Ln, Powder Springs`.
- Row 412's frames 3 and 4 alone refuse a 61-character merchant and show the
  destination as their pickup. The window's row keeps the merchant.
- Longer-wins now picks junk-prefixed readings on rows 1094 (`bane I Cardinal
  Dr …`) and 1065 (`St Cedar Valley …`).
- Row 444 holds `…, Kennesaw` beside its `…, Bee`.
- Row 309 still publishes `SW, Marietta`.

*Not done:*
- A merchant printed without a bracketed branch is stored fused to its
  destination. Readings of 18 week rows do this, including the first panel read
  of row 419. An Est. delivery card with such a merchant inherits it.
- If Uber moved its estimate while the card is on screen, the window's vote
  would lag. Measured: three reads at $25.50/hr GO where the card said
  $23.80/hr CLOSE CALL. No one has seen Uber move one.

39d7a86's decoding re-checked against `toCsv()`: 1,166 of 1,166 cells
round-trip. 75 mutations, 75 named kills.


**A card taller than the drawn card box lost its payout, and the panel said there was no offer.** On 8 Oct an Uber Early-look card's $14.48 sat across the top of a box drawn round a shorter card; the reader got "Pit.". `rpi/cardfind.py` finds the card from its Accept/Match bar up and is sure only when every shape test passes (432 glare frames: sure of 348, wrong about none). `Scanner._look` re-reads a sure find above the box when the box read a journey and no payout, and keeps it only if it moves no minutes, miles or deadline the box read, holds exactly one dollar figure, and prints its payout as a card does (cents, or a whole dollar with its label). 576 rendered screens: Early-look rescued 73/144, two-order 79/144, stacked card 0/144, no rescued reading carrying a wrong figure; without the figure rule the stacked card gave $14.48 at the upper card's 3.1 mi on 76/144, and without the second-dollar rule a $22.75 card stacked over a DoorDash-shaped $9.40 was rescued complete on 3 of 60 frames (now 0 of 60). Said by the payout shown, not the last read: `cropFrom` on the line, PAY ? on live.html and " ?" on `--display`, an amber outline in both live views, `payFrom` in a Snap's reader.json, `rescued` in the health tally; the log's sample line says why the finder gave nothing. Off by `"cardFinder": false` / `--no-card-find`, byte-identical over 240 reads. Cost measured on x86 (finder 25-27 ms; a rescue's second read +200-243 ms on a 327-334 ms read); the Pi figure is an estimate and no guard was added. `scans/unparsed/` keeps a picture and its text of cards that showed a payout and no journey (cap 400), where new layouts such as DoorDash's land. The real 8 Oct images were lost with a replaced machine, so every figure here is on rendered cards, not real captures. Checks: test_cardfind 45 (new), test_pipeline 231→273, test_scan_pi 492→517, test_loop 269→300, test_dashboard 973→977, test_layout 2055→2097, test_lint 328→335.

**DoorDash's stops card never read whole, split cents read as whole dollars, and "( 09 mi)" was charged as 9 miles.** "3 stops (7.8 mi) · 30 min": LEG refused the bracket as glue, so the distance was an orphan and all 21 DoorDash offers of the 12 Oct shift journalled whole=0. `STOPS_LEAD` lets the bracket through only where it closes on the card's word for the stops (1,097 readings in the journal's 23,693 texts, no Uber leg among them); re-parsed, the 21 are whole, and whole through the accumulator; 1,089 texts become whole and nothing else moves, both ports agreeing. The stores are read off the card's own lines (`find_stores`), all the pickup end, so "Multiple dropoffs" no longer offers the second store as the destination; the card's count is kept as `stops`, voted across frames, on the reading. `PAY_CENTS_SPLIT` joins "$12 6 8" and "$12. 78" (both read $12.00): 15 texts of 7 payouts move, each up by under a dollar. A bracketed distance with a leading zero and no point that `recover_decimal` let stand ("( 09 mi)" for "(+ 0.9 mi)", 49 mph) leaves its leg without a distance: uncertain and not whole, 30 texts, all total legs. Checks: shared cases 4 (three parse, one whole), test_accumulate 1 (its frames now end on one misreading the count, so it holds the vote and not the last frame's), test_scan_pi 1 (`stops` on the reading, added), test_pipeline 1. 14 mutations, each killed by name.

**Uber's online map was not an idle screen.** "You're online" and "Finding trips" were handled nowhere; they are NOT_AN_OFFER in both ports and on the wire as `notAnOffer`. "Trip Radar" is deliberately not the phrase: it bleeds into 308 offer rows.


**DoorDash's place popup is read while a card is screened (14 Oct 2026).** The driver taps a stop on a DoorDash card before deciding and the phone shows its address. The store's sheet ("Pickup from / store / street / town / Directions") is on file five times in the 12 Oct journal, read by the card box 2.1-28.5 s after its card; `place_popup` / `placePopup` read all five and fire on none of 47,109 offer-row texts. It is filed onto the card being screened or nowhere (Assemble.popup): a role label, a card on the slot from before the frame, the same app, never an order in the car; a store's popup must name the card's pickup (one i/l slip) and end in the card's house number where one was printed; a customer's needs the card read within POPUP_CARD_MS (16 s, READ_STALE_MS) before the frame and one customer on the card. The store's door is the card's `pickupAddr`, the customer's the card's `dropoff` (`dropoffFrom: 'popup'`); at Took both enter the hold at rank `popup`, above card and seen and below planner, nav, label and press. Map view searches the door and says "addr from tap". The rig still presses nothing. Open: no customer popup has ever been read and its labels are inferred; the map pill (a bare street over the map, 12 Oct 16:03) has no role cue and is refused; the store's `pickupAddr` is not journaled before Took.


**A scanner review found twelve faults; eleven fixed.** Every interval in the loop, the accumulator, the tracker, autopilot's aiming and the journal's complaint repeat is timed on time.monotonic(); stamps stay on the wall clock, nothing rejects or corrects one (the declined clock guard is not this). A step back an hour had stopped the heartbeat and the ⌖ reads; a step forward with a read in flight wrote a false restart row. A planner block holding two "Expected by" lines is unbounded and `listShort` refuses a list whose pickups' orders outnumber its dropoffs, so a lost stop header no longer files another customer's door. Idle screens printing earnings no longer keep the verify beat running (15 reads in 30 s → 2). Address and store patterns are anchored so a 4 kB letter run parses in under 50 ms (was up to 2 s), identical on 17,970 texts in both ports. The read pool's workers are daemon threads (exit with a hung read 30.4 → 3.9 s). Accumulator votes are tallies (24.3 → 0.22 ms an add at 7,200 frames, merged readings identical). SHEET_NAME and find_stores no longer drift between ports. shift_report reads only the day's GPS logs and indexes placement in one pass (real 12 Oct 1.97 → 1.32 s, output identical); parse_line skips SKY lines before json.loads. Journal appends are fsynced (0.21 ms a row median on the development machine; the Pi's card not measured). Not done: the phone view's compose stays as it was, nothing faster kept the picture identical. Open: gps.py's --seconds loop and HEADLINE_LABEL; two n²/2 regex shapes remain on contrived inputs; server.js's appends are not fsynced.


**Uber's customer sheet was read as a planner, and its address never filed (17 Oct 2026).** With an order carried the driver pulled Uber's sheet all the way up (name; a place; the street, wrapped at its comma; "Town, GA"; "Business / Building name" and its value; "Dropoff type"; then "Drop off 1 order", the order code, the store, "Expected by") and pressed ⌖. PLANNER_STOP took "Drop off 1 order" for a stop header, so the press was answered by a planner of one dropoff (the order code its name, no address), the window closed on it, and the hold's planner field got that stop. The rig's own whole-screen read DID read the street and town: the 17 Oct journal's unpressed read of the sheet has them, and the photo's camera picture through `Scanner._read_box` (fit_for_ocr, to_grey, preprocess's CLAHE, psm 6) reads them at 1,000 to 2,200 rows; plain `tesseract img -` drops them. The drawn card box starts at the business label and never sees the address. So no OCR change. Fixed: `_customer_sheet` / `customerSheet`: a page with "Dropoff type" or the business label (SHEET_BUSINESS, its slips "©usiness / Building Name" and "MUOHICSS / SUNGINg name" included) and none of the planner's lines (title, "Address", "View details", "Waybill", the bar, a Pickup header) is no planner, and `screen_type` then says uber.nav. `sheet_dropoff` gives `place`, the pair's value or the line between the name and the street with its icons off; it reads from the business label alone where "Dropoff type" is lost; reach is counted from the label, so a value like "1200 Fable Tower" is never the street; a comma tail with no three letters in a row is icons, with the town on the next line; the name may sit 3 lines up (SHEET_NAME_REACH). `digest()`: a press with no other answer and no planner takes the sheet as its dropoff line (before, every press over an opened sheet was "nothing read"). Unprompted it files at rank `nav` as before. assemble.js unchanged. Measured against the parsers at 0e9214a: over the shared corpus (545 texts) and the rig's journal through 17 Oct (12,789 texts, the 12 Oct copy's 12,229 among them), `find_planner` and `screen_type` change on 2 texts, both 17 Oct customer sheets; `sheet_dropoff`'s address changes on none; `place` is new on 1 corpus text and 2 journal texts. Checks: 10 `sheets`, 2 `planner` and 1 `screens` cases in cases.json; a check in each port that each planner line put back makes the sheet a planner; test_scan_pi (screen_address, sighting); test_loop (a press over the sheet gets its address, asked, and no planner line; held and unpressed, it files `nav`). 41 mutations, each killed by name.

**A store's address under its name on DoorDash's card was thrown away, and its pickup had no pin (17 Oct 2026).** On the owner's afternoon shift the stops card printed the store's address on the line under the name, "<n> <Street>, <Town>, <ZIP> <ST>" (ZIP before the state) or "…, Marietta, 30." with the ZIP cut by the edge. `find_stores` took that line only as proof a store stood above it; the pickup was the name, Map view asked the NucBox for a chain's name in the card's disc, got "too many to be sure", and the stack line had no pickup pin. Fixed: `store_door` / `storeDoor` (STORE_DOOR) reads the line DIRECTLY under the name (a chip line between them, no) when it opens with a house number and carries a street and a town of three letters with no cut mark, then only a ZIP and a state in either order, each once; a ZIP under five digits as the last word is the edge and is dropped; anything else after the town refuses the line. It is the parse's new `pickupLine`, "<n> <street>, <town>[, <ST> <ZIP>]", only ever the pickup store's; `pickup` stays the name, `places`, `dropoff` and the journal are unchanged, and Uber cards never have one. The accumulator keeps the fullest door read under the merged pickup's name across frames; `emit_offer` carries it, and a door read after the row landed is told again; server.js keeps the offer whole as `scanner.offer`, unchanged; live.html's `mapWants` searches the tap's door, else `pickupLine`, else the name (searchPlan's street rule: door number kept, town cut). The pair figure is measured to that pin. Measured against the parser at ee4bc5c: over the shared corpus and sequences (490 distinct texts before this commit's cases) 3 texts gain a `pickupLine`, the three two-store "12 Ab Rd" cards, and no other field moves on any; over the 328 payout texts in the Python suites, none moves. No journal texts are in the repo. Checks: 8 `parse` and 17 `doors` cases in cases.json, both ports; test_accumulate (a door kept across frames); test_scan_pi (on the offer line); test_loop (told again when the door reads late); test_dashboard (Map view searches and pins the door, not the name, and says no tap). 24 mutations, each killed by name. Open: the hold's `fields.pickupAddr` at ✓ Took is still the card's name, not its door, so `heldPickup` cannot refuse that door read off a navigation screen as the held order's end (closed 18 Oct: the hold now keeps `pickupLine`, and heldPickup reads it; see The GPS); map.html and the journal still place a DoorDash pickup by its name.

**Of the rig's 100 kept unread pictures only eight were offers, and one of them never landed; an hour read as `1L` sent an 89-minute card out as GO at 29 (18 Oct 2026).** `scans/unparsed/` on the rig, 12 Oct 15:43 to 17 Oct 00:07, every picture looked at: 82 hold no card (75 a cloth over the lens, its weave read as `$` figures, and 7 near-black frames), 10 a screen that is not an offer (Finding trips 2, You're online 2, DoorDash's busier-zone prompt, the phone's app switcher 2, Uber's pickup navigation sheet, a navigation map 2), and 8 a real offer. Of the 8, 7 cost nothing: the journal (16 Aug-17 Oct, 17,795 rows) has the same card read whole by another frame 2.4 to 29 s away. A finger over the card 2 (the minutes of `– min (10.2 mi) total`, the whole middle of a card); a card fading in or out 3 (under the map, or after Accept, the reader got `$11.0` or `$3.55 ... 2 stops 1 mi) + 23 fin` with the `(6.4` gone); `Est.` read `s t.` 1; a card under one marked "no longer available", cut by the box 1. Those four read a different payout from the frames that landed, so each opened a new episode, which is why it was kept at all. **The eighth was lost**: DoorDash's `3 stops (11.8 mi) · 1 hr 0 min` read as `1hrO min`, the minutes token had no real digit, the leg was refused and the bracket was a distance no leg claimed; no other frame of the $14.20 card is in the journal. *The box:* it cut the card on 2 of the 8 and was the cause on at most 1, a card already journalled 8 s before; the camera code is unchanged. Fixed, both ports: `hour_vouches_for_minutes` / `hourVouchesForMinutes` lets a minutes token with no real digit through behind an hour unit with a number, the minutes 0-59 (`1 hr BB min` stays refused); the hour's own digit and number are asked of every leg straight after. DELIVER_BY reads `\b(?:e\s?)?s\s?t` for "Est" (`1st` and `Fastest` stay out). And, found on the journal while checking the first: LEG is IGNORECASE, so DC's `l` matches an `L` that DIGIT_FIX does not map, `1Lhr 29 min` passed the hour's real-digit guard, `to_number` gave None and `or 0` dropped the hour; the 12 Oct $31.28 card `1hr 29 min (34.6 mi) total` went from 89 min, `no`, to a last row of 29 min, `go`. An hour that is no number now refuses its leg, as a digitless hour does. Not fixed, and why: the finger's minutes and the fading cards' figures are not in the text, so any rule would be guessing them (Settled: no minutes from distance); the 3-line merchant on the `s t.` card still leaves its destination as the pickup, exactly as on the two frames that landed (the known fused-merchant shape). Measured, old against new, both ports: of the journal's 12,735 distinct texts 6 move, every one an `<n>Lhr` leg that had lost its hour (99→39, 89→29 twice, 69→9, 65→5, 61→1), now untimed and not whole; of the shared corpus's 507 texts before this commit's cases, 0 move; of the 100 unread texts, 2 (the `1hrO` card, now 60 min, one leg, whole; the `s t.` card, now deadline 4:04 PM, complete, whole); the ports agree on all 12,850. Checks: 5 `parse`, 3 `deadline` and 1 `whole` cases in cases.json, invented text in the readings' shapes; test_parser 1383→1408, corpus.test.js 1303→1328. 16 mutations, each killed by name. Open: 82 of the folder's 100 places went to a cloth; the folder's cap is 400, so that is room, not loss, but a payout read off fabric opens an episode.

**A card that takes exactly an hour prints `1 hr (21.1 mi) total`, with no minutes, and no frame of it was ever a journey (13 Nov 2026).** The rig's `scans/unparsed/` as of the 12 Nov shift (400 pictures, 20 Oct-12 Nov, build cf10ded on the 12th) holds five Uber cards, Delivery, Package and Shop & Deliver, whose duration line the reader gave back cleanly — `© 1hr (36.9 mi) total`, `© 1hr (7.6 mi) total` under `16 items (18 units)` — and every one parsed to a payout and a distance and nothing else. LEG wanted a minutes token after every hour unit, so the line was no leg at all; every frame of such a card reads the same way, so none could supply it, and each card was a payout with no journey: no verdict, never journalled. Fixed, both ports: LEG's minutes group has a second branch, HOUR_ONLY, an empty match where the unit `hr` or `hrs` is followed straight away by a bracket; `find_legs` / `findLegs` keep such a leg only with its hours (the hour's real digit and number asked as of every leg) and the distance read inside the bracket, as hours x 60 minutes. `Lhr (19.3 mi)` and `1Lhr(8.7 mi)`, four more of the folder's cards, stay refused like any hour that is no number; `1 hr (approx.)` is no leg. In the JavaScript port an empty match must step `lastIndex` before any `continue`, or exec finds it forever — it did, on a corpus text, before that line. Measured, old against new, both ports: of 1,498 distinct texts (the shared corpus and sequences, the folder's 400 kept readings, and the reader's re-reads of the 400 doubt pictures) exactly the five move, each from no minutes to 60, complete and whole, its places read as on any one-leg card; the ports agree on all. Checks: 6 `parse` and 1 `whole` cases in cases.json, invented cards; corpus.test.js 1702→1725, test_parser 1790→1813. Mutations: the distance requirement dropped, `hrs` dropped, the JavaScript empty-match step dropped — each killed by name or by the suite not finishing.

**On Uber's delivery card a lone corner was read as the pickup when the store line was lost (the owner, 20 Oct 20:44).** The held card's pickup became "<Del Lago> Cir NW & <Ellison> Lakes Dr NW, Kennesaw" (`fields.pickupAddr` from 'card') and its dropoff null: the reader lost the store line and `find_pickup` took the only place. On an Uber delivery card a cross-street corner is always the dropoff end; the store is a name, often "Store (n street)". Now both ports' `parse` mark every corner (`CORNER_PLACE`: "<street> & <street>, <town>", no bracket before the town, so "Hooters (Old 41 Hwy NW & N Roberts Rd)" is not one) the trip's end in `placeEnds` (`corner_ends`/`cornerEnds`) on a card whose leg is a "total" — Uber's delivery card; a RIDE card's pickup is the rider's corner and it prints no total, and DoorDash's stops card names its stores (`find_stores`). `find_pickup` never takes it, so with no store read the pickup is null and the corner the dropoff; the window (`rpi/accumulate.py`) narrows its merged list by the same ends. MEASURED over the shared corpus's 591 texts, both ports alike: 6 change, no ride card among them. Three are a corner alone after a store the reader lost (parse "...nor a bare $4 twelve characters after the payout", places "...and a bracket the camera invented does not disarm it..." and "...but a bracket the camera invented after a divider..."), now no pickup and the corner the dropoff. Three are a store glued to its customer's corner in one place ("Sugar Shane's Hawthorn Dr & Shady Gin, Dallas", "Papa Mario Pizza Kirk Ln NW & Kirk View Ct, Dallas", "Fable Grill - Lantern St Birch Ct & Kestrel Way, Atlanta"), now the dropoff where they were the pickup — wrong either way, and the corner in them is where the job ends. Checks: shared corpus 1328→1336 (js), test_parser 1408→1416 '[corner]' (the fault, the store read, a ride card's corner, a ride card cut to one leg); test_accumulate 320→322 '[corner]' (three corner-only frames, a store read between). Mutation testing skipped (fast lane). Mutations (catch-up, 21 Oct): 14, 7 per port (CORNER_PLACE's bracket, town and letters, the total gate, the caller, the kept ends); 6 killed by the '[corner]' cases above, 8 survived. 6 are killed by four new shared-corpus '[corner]' cases, both ports (a corner with no town, a store's bracket holding a corner and its town, a corner whose second street did not read, a house number and a street either side of an "&"). 2 (one per port: keeping the layout's end for a place that is no corner) were equivalent: a card with a total is never the two-leg layout, so every such end is null; `cornerEnds`/`corner_ends` now give null outright and say why.

**The phone's edge read as letters in front of a planner street's house number lost the door (the owner's 28 Oct shift, 17:48:56).** A whole-screen read of the Trip Planner gave both dropoffs' street lines as "Te <n> <Name> Rd NW" and "ie <n> <Name> Ln": STREET wants the house number first, so both stops kept the town alone and the held order no door. Both ports now take the labels' edge word (PLANNER_EDGE_WORD's shape: one or two letters, a mark or two, a space) off the front of a planner street line when a house number follows (`PLANNER_EDGE_HOUSE` / `plannerEdgeHouse`), in `_planner_address` and in `_planner_address_lines`' two "opens with a house number" tests (the one-line street-and-town and the line-of-marks layouts); nowhere outside the planner grammar. Measured over every text on file (38,692: every evidence journal, every snap's reader.json and every unparsed scan's text, and the shared corpus) against the parser before it: one find_planner answer moved, the 17:48:56 read, both streets gained; no other planner function moved. Shared cases 4 (two taken, three letters and no house number refused).

**A black screen cost 16-25 s a read in tesseract (29 Oct shift, 20:04-20:25 and 21:32-21:37).** Reads took a median 15.9-25.0 s in those windows against 1.5-2.6 s either side, CPU 67-74 °C, no throttling; the camera's word went dark/seeing with the box reading 1-7. The crops kept from the windows have a mean of 1.0-2.5 and a max of 7-9 of 255, and read 1.2-2.3 KB of noise words each where a card reads 50-230 bytes: the phone's screen was off and tesseract was reading the sensor's noise. Fixed: `Scanner._read_box` measures the fitted crop's 99.5th percentile on every fourth pixel (`bright_end`) and does not hand a crop under `DARK_SKIP_BELOW` = 9 to tesseract; it comes back as `parse('')`, text '', `skipped: 'dark'`, polarity left as it was. One choke point, so the card box, the verify beat, a found card and the whole-screen read nobody pressed for are all covered; the map-label read (`read_map_label`) is not, as it runs only off an offer that read. *Measured*, the 99.5th percentile of the fitted crop: the 24 kept crops (12-29 Oct) with no text in them, every one looked at, 1-9 (black screens 1-6, 29 Oct's 3-6; a dim cabin through an empty mount 8 and 9); the dimmest real card on file (17 Oct, a light-mode Exclusive card on a screen turned nearly down) 23; testcards' UberX card dimmed in a cabin reading 2 and read through the real Scanner, payout still read at 14 (light) and 13 (dark mode, box reading 4), not at 12 or under in either theme; rendered black noise 2-4. The floor sits just under where the reader stops reading anyway: a skip that drops a readable card costs a fare. Strided and full percentiles agree to a level on 362 of the 365 pictures on file and none crosses the floor. **A ⌖ press is never skipped** (`skip_dark=False` on its geometry): the driver asked, and a press that finds nothing is already answered (`found: false`), so no new panel message was needed. Health: counted as "N dark: not read" on the health line and `darkSkipped` on the `seen` row, kept out of the median read time; the log line is said at most once a `DARK_SAY_EVERY` (60 s) with how many reads it stands for, and `read_why` names it on the sample line. Not changed: verdicts, the offer path, the camera's dark/seeing watch, exposure. Checks: test_scan_pi (synthetic black noise skipped with no OCR; a whole-screen read skipped; a press's geometry read; a dark-mode card at 6% and a normal card read $16.05; the counters, the rate limit and the health lines); test_loop (no offer off black reads, one log line over several reads, the health line, darkSkipped on the `seen` row, a press's whole-screen reads handed over with the skip off and card-box reads with it on). Open: a cloth over the lens (75 of the 18 Oct entry's 100 pictures) reads 9-70 and is still read; the floor cannot take it without taking the dimmest cards too.

**A lowercase "s" read off the card's route line opened the held end, the panel's title and the NucBox's question (the owner's snap of 12 Nov 20:57, build cf10ded).** The add-on card read its dot between the store and the dropoff as "s" on a line of its own, and trim_place keeps a lone n, s, e or w at a place's front for "S Main St"; so the end was "s <Name> Blvd SW & <Name> St SW, Atlanta", big on the card as "s <Name> Student…". Uber prints a compass point as a capital, so a lowercase one standing alone in front is a scrap now (`PLACE_LEAD_COMPASS_SLIP`, `_lead_scrap` / `leadScrap`, both ports); a capital is kept. Over the shared corpus nothing else moves. Checks: cases.json `places` 2 (the slip dropped, a capital S kept).

**The panel's big title said "Teriyaki Madness a" (the owner's snaps of 12 Nov 20:04-20:06).** The Trip Planner's read put the scroll bar after the store's name as one lowercase letter, with no mark on the line, so `nameNoise` (which trims only a read that carries a mark) left it, and `plannerName` showed it as the next stop. Now one lowercase letter after a name with a capitalised word goes, for display only (the hold and the journal keep the read); a customer's lowercase "anise v" and a capital initial keep theirs. Checks: mapview.test.js 1 (five names).

### The order in the car

**An Uber add-on ticked while an order was in the car replaced that order, and the rig judged the next half hour against the add-on alone.** The owner's 16 Oct shift journal: twice ✓ Took on "+ $9.50 / Guaranteed (incl. tip) / +8 min (+1.3 mi) total" (and "+ $9.64 / +19 min (+3.8 mi)") with carrying two off wrote a drop row `by: 'replaced'` for an order whose Trip Planner door was on record, and held the add-on alone — no end, its own "+8 min" clock, gone 21 minutes later. No journal row said a card was an add-on. Uber paid each pair as ONE trip ($25.03 + $9.50 card → one $43.42 trip; $22.46 + $9.64 → one $36.53), and the owner's trip details show the first trip collected a second add-on, $6.89 ("9 min"), accepted on the phone with no Took ($25.03 + $9.50 + $6.89 = $41.42 expected; amounts only, from the owner's Uber trip details). The owner's decision (17 Oct 2026): handle add-ons so they do not confuse the rig, automate what the Trip Planner can give, keep ⌖ Scan as the backup. **Recognised:** both parser ports' `addon` (offer_parser.is_addon / isAddon) — the leg's plus signs (the screen type's own SCREEN_ADDON) or a "+" printed before the payout find_pay chose, never a DoorDash card; a union over the window (accumulate), on the offer line (scan_pi) and on the journal row (`addon: true`, else absent). Over the 473 distinct texts in tests/fixtures/cases.json and sequences.json, 6 say it: the 4 the screen type already called uber.addon and 2 whose leg lost its plus; no other text moves. **The rule (server.js, "a trip" above maxHeld):** an add-on Took with an Uber order in the car JOINS that order's trip — held beside it, `addOn: true`, `of` the trip's root holdId, no drop row, whatever `carryTwo` says; a second add-on joins the same trip (one trip of three). Every cap counts trips, not orders: carrying two off, a Took on anything else replaces the trip in the car, every order of it, `by: 'replaced'`, as it replaced the one order before; on, a Took past two trips puts down the trip ending soonest, said by the trip's pay. While a trip of two or more is held the carry-two machinery is in force (carryingTwo): Assemble.attribute, the pool, the chooser, Drop's chooser, the pair line and pair row against every order, `orders` to the panel. An add-on with no Uber order in the car (nothing held, or only DoorDash's) joins nothing and is taken as any card is, on its own clock. **Expiry:** an add-on is held to the trip's end at its Took (`ofEnds`, the holdEnds of the trip's last-taken order) plus its own card minutes × HOLD_OVERRUN — the existing carry-two rule, now for chains; card minutes and the clock only, nothing from distance. **Put down:** Drop, the GPS drop or expiry of the original puts down the original alone; its add-ons stay held, still one trip, the last one left held on its own; their rows say `addon: true, addonTo: <root holdId>` (the Took's mark row too), ids only. **The planner, automated:** a list seen whole with ONE order held is now remembered for growth (Assemble.sighting → noteView), so the first planner read after the add-on's Took that shows both orders' stops — two Pickup blocks, or "Pickup · 2 orders" — gives the add-on its door by `growth` and the original its own; with no list from before, the add-on's by `elimination` and the original's own door by the new `filed` cue (a dropoff on a list seen whole that IS one order's screen-filed end; two orders on one door decide nothing and are no tie for the map); growth and elimination are asked of three orders as of two. No cue files nothing: the doors wait in the pool, and the ⌖ chooser's answer for one decides the other (retryPool). A list whose foot is off the screen files nothing with a trip held — the lone-dropoff rule (`singleCardOnly`) is never reached with two held. Settled stands: no cue means no filing, the chooser never times out into a guess, no $/mile, no pace, no minutes from distance, no silence as an accept, no seventh control, the rig never presses the phone. **Panel:** an add-on's line reads "② +$9.50"; with three, ② onwards share the second line, "②–③ +$16.39 → 1/2 ends", and under an offer "· In car ① $25.03 · ②–③ +$16.39"; a list about another hold is dropped (the trip came apart and the server stopped sending one). Fits at 1024x600 and every panel, parked and driving (test_layout's new "three" and "between three" forms). Map view draws no figure through two of three orders: "order of stops unknown — no figure" (MV.heldRuns takes two ends; a run through ① and ② "incl. both orders" would leave ③ out). Checks: test_parser 1286→1305, corpus.test.js 1207→1226, assemble.test.js 272→286, advice.test.js 449→450, test_accumulate 315→317, test_journal 409→410, test_scan_pi 563→564, test_server 858→884, test_dashboard 1303→1308, test_layout 3890→3950. Mutations: parser 8 of 8 killed by name (each half of the rule, the DoorDash guard, a plus anywhere), assembler 8 of 8, server 27 of 27 (one more, the trip's end against its last-taken order's, was equivalent and the code now says the simpler), panel 5 of 5, accumulator 2, journal 2, advice 1, offer line 1. Open: an add-on card offered against ONE order in the car is still drawn as an ordinary offer (Settled, Stage 6); Map view has no detour figure with three orders in the car; an add-on accepted on the phone with no Took is not held, as no order is.

**An unprompted address sighting filed a Trip Planner pickup's town line as the held order's destination.** `find_address` took the last ZIP on the screen, the first pickup's "Kennesaw, GA 30144". `offer_parser.address_stop()` now finds the stop label nearest above an address: under a Pickup it is refused, pressed or not; under none it is refused unprompted or on planner layout (`addressNotDropoff` on the health line). The planner parser reads a town split from its ZIP and a street and town on one line, a lost header no longer lends its stop's address to the stop above, a dropoff with no address on screen is null, and nothing below "Stop New Requests" is read. With Took pressed and planner layout in the card box, one whole-screen read runs at most every 10 s (`.holding.json` written by server.js with `until`), sending stops only and never a destination. The ⌖ button is now labelled "⌖ Scan": it reads the screen. Over a screen that just read as no offer the panel says READING THE SCREEN, and a ⌖ read sends no reading cue.

**Card-rescue verifier faults, and an older tip/promo payout fault.** `payout_from` decides by the accumulator episode alone; the `not whole and pay is not None` guards could never decide anything and are gone, and its "no payout" and "⌖ read" checks use readings the real accumulator and parser made. The `--display` doubt line is fitted inside a 40px margin ("$1999.99 ?  120.0 min  45.3 mi" ended at x=835, now 718; usual lines pixel-identical). `PAY_PART` (both parser ports) stops a tip/promo/boost/surge/bonus/extra/Peak Pay figure in four grammatical shapes ("+$2.00 promo", "Boost +$3.00", "Includes $3.00 tip", "Surge $1.50 extra") from being the payout: with the headline cut off by the box, "Includes $3.00 tip" had read $3.00 PASS $5.1/hr and "+$2.00 promo" / "+$2.00 Peak Pay" $2.00 PASS $3.4/hr, each on 8 of 8 rendered frames; all now give no payout in the box and the finder rescues $14.48, and the second-dollar rule no longer refuses a rescued card for them. Open: "Tip $3.00" (keyword on one side only) is still taken as $3.00 PASS 8 of 8 inside the box; a pattern catching it would also match "Includes expected tip $14.48". The owner's week export was not available, so the corpus holds this rather than a replay. Checks: test_scan_pi 517->523, test_parser 1060->1084, corpus.test.js 1012->1036, test_pipeline 273->277.

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

**A ⌖ press found late was read for twelve more seconds, after the panel had stopped waiting.** dropoff_requested() accepted a press up to DROPOFF_WINDOW (12s) old, then the loop opened a fresh window from the pass that noticed it (`now + DROPOFF_WINDOW`). So one press was judged by two clocks. A press 11.5s old was read until 23.5s after it, plus a read in flight measured at up to 5.9s. Its address was filed as ASKED after live.html's 13s 'reading…' wait had ended. Fix: dropoff_requested() returns what is left of the press's own window, or None, and the loop sets `dropoff_until = now + left`. A press exactly the window old is refused, so the return is never 0.0. Trap: the fake reader lands 3 reads inside 0.08s, so a check staged by read count found the address with the fix in. It is staged by time instead, and the press is aged at the loop's first look rather than before startup. Checks: test_scan_pi '...only for the half second left of its own window, not twelve more' (fails when the loop's `now + DROPOFF_WINDOW` is restored) and 'a press exactly its window old is not taken with nothing left' (fails on `>`).

**A drop row names the order the rig was holding, and with two jobs in the car that is the wrong one.** The hold is one slot and the last tick takes it. A Drop at the first delivery puts down, and writes a row naming, the second job, which is still in the car. The press at the second delivery then writes nothing. On week.csv, 12 of 31 ticks landed while an earlier tick was held, and 7 landed inside the earlier tick's stated minutes; in 6 of those 7 the earlier job was stated to end first. The server.js /api/delivered comment and rpi/README.md now say a drop row is one job's elapsed time only where no other tick overlaps it. Prose only. The row stays collection-only and nothing reads it.

**A Took press from a panel that had fallen behind wrote a second pair row
for the card on the phone.** The mark carries the panel's copy of the offer so
a press after a server restart can still put the order in the car. That copy
stood in whenever the ids differed, which is also the case where the panel is
just behind: the socket drops, `/api/events` replays the last reading and never
the offer, and the driver ticks the card they took while the server is on the
next one. The older card took the slot, `/api/status` named it with the newer
card on the phone, and the newer card's next re-read looked like a new card, so
`recordPairing` wrote its row again. Reproduced against the real server: pair
rows `['o-a', 'o-b']` became `['o-a', 'o-b', 'o-b']`.

The copy now stands in only when nothing is on record. Otherwise the job the
driver ticked still goes in the car, from the panel's copy, and the card on
the slot is left alone. Only the panel sends that copy; the offers page's
ticks carry no offer and cannot put an old job in the car. Pinned in
`rpi/test_server.py`: '...and the card on record is still the one on the
phone' and '...and the newer card read again is still one pair row, not two'
fail against the old handler, and '...while the card the driver took is the
order in the car' fails if the copy is dropped instead of used (it held the
previous order, $10, not the ticked $12).

**One hand-drawn box had to be both the card and the screen, so a box tight
enough to keep the reader off the map made ⌖ blind to the trip planner.** Asked
for from the seat: after taking an offer the driver opens the trip planner,
whose restaurant and dropoff addresses sit outside where the cards land. A box
drawn by hand set the corners AND pinned the crop to all of them, and every
read — the ⌖ window's included — went through that one crop.

▣ Set box now asks for two: the screen, then the cards inside it (or **No card
box**, which is the old single box). The card box is stored as fractions of the
screen box in `cropBox`, the warp is sized to it (`cropbox.card_share`), and
offers are read there. While a ⌖ press is open, reads take all of the screen box
(`Geometry.whole`). Those reads answer the press and nothing else: they are the
card plus the map or planner round it, so they are never merged into the offer,
never priced and never journalled, and they do not steer the next card read's
crop or ink polarity. The request file carries both boxes, so the card box
cannot reach the rig without the screen box it is a fraction of, and a card box
too small to read refuses the whole request rather than being dropped.

Checks and mutations: routing every read to the card box fails 'a ⌖ press reads
the whole screen box' and '...and the address outside the card box is the
answer'; feeding whole-screen reads to the offer fails '...and that payout never
reached a verdict' (a $99 off the screen round the card reached the panel and
the journal); reading the whole box always fails eight offer checks; dropping
the card box from the server's file fails three named checks in
`tests/crop.test.js`; sending it in frame fractions fails '...the card box as
fractions of the SCREEN box, clamped to it'.

*Not built then:* reading EVERY stop off the trip planner. The ⌖ answer was
one destination, and a reader for the planner page needed a real picture of
it to be built and held against. Built since, off the rig's own live view of
one: the Trip Planner entry below.

**⌖ over Uber's Trip Planner answered "not read" with every stop on the screen,
and its first fix filed a door it could not be sure of and hid the panel's
warnings.** The planner prints no ZIP. On the rig's own live view of one, the
read path (fit_for_ocr to 1800, to_grey, preprocess, ocr_lines) gave
`find_address` → `None`. The press ran out its twelve seconds and said nothing
was there.

`offer_parser.find_planner` and `findPlanner` now read the planner by its own
grammar, held to one corpus:
- the stop header: "Pickup • N order(s)" or "Dropoff • N order(s)", where the
  bullet may come out as any glyph or not at all, but never a bracket;
- the name, and "Expected by", through the one `time_of_day`;
- under "Address", a street held to STREET and a "Town, ST" line held to STATES
  and TOWN.

Every field that does not read is null, and `find_address` is not loosened. On
the owner's week, 6,657 texts (5,491 frames plus 1,166 stored texts), none has a
stop header. parse, rate and find_address are unchanged in both ports, and no
row changed in the replay against the base parsers.

The trailing "S" in "4821 Kestrel Dr S" is the screen's scroll bar. A lone letter
after a street suffix is a real quadrant on 7 of the week's 1,802 places, so it
is dropped only when the town line also carries a tail. Without a ZIP the line
leaves out the state, because Advice.area returns null on "…, Marietta, GA".

A planner is read only during a press, off the whole-screen read. It answers the
press at once on its own line and the window shuts: 4 reads in the next five
seconds against 13 with it open.

**Counting dropoffs on the screen was not counting them on the trip** (found in
verification). On the rig's live view, one open stop's card is 308 of the list's
695 rows, so two open stops fill it. On a longer trip, the one dropoff left on
the glass may be another customer's, and it was being filed with `asked: true`.

`planner_bounded` and `plannerBounded` now require both ends of the list:
- the "Trip Planner" title with the first stop's header directly under it;
- "Waybill" after the last header.

What the measurements show:
- The whole live view lost "Waybill". All five crops of the same pixels to the
  phone's glass read it, one as "Waypbill".
- A drawn planner loses its title off the frame at a 900px mount, and reads
  whole at 850 down to 750.
- That "Waybill" follows the last stop rather than every stop is read off where
  it sits on the one planner photographed, which had a single stop.

`planner_destination(stops, bounded)` files the address only when there is one
dropoff, the list is bounded, and both street and town read. Otherwise it
returns its reason, `dropoffs`, `list` or `address`, on the planner line as
`unfiled`. On a planner, find_address's own answer is never taken, asked or
not. Unprompted, it was "77 Birch Ln NW", one of two customers.

**The panel worked out its own reason, and contradicted itself.** It counted
dropoffs, which was half the scanner's rule copied. It now shows the scanner's
reason in its own words, and test_lint holds the two lists together. The "end
not guessed" line now goes when the button shows an end.

On reload, server.js kept `holding.planner` until another planner replaced it,
so the note came back next to a green button. `forgetPlanner` now drops it at a
⌖ press and at a new offer on the record, the moments the panel forgets it. The
order going already took it.

**The stops took the notice's room.** They are `flex: none`. On the 3.5" hat's
scene picture, with a dead-journal and too-bright notice:
- the notice needs 139px; it had 121 on the glass, and 17 once four stops
  arrived;
- in the screen picture it went from 93 of 93 to 38.

`showStops` now removes stop lines from the end while the notice is cut,
counting them ("+ N more stops"), down to "▸ 4 stops: no room to list". That
leaves the notice 93 of 93 in the screen picture and 95 of 139 in the scene
picture. Nothing folds at 800x480 or 1024x600.

**keepPlaces.** Planner rows hold names and doors. The scanner says `keep` on
the line (false under "keepPlaces": false and under --no-journal), and server.js
writes the row only when it is true. The ⌖ `mark` and `pair` rows still ignore
the setting. That is older than this work and is named as open in README.md.

The one filed dropoff reaches the maps as a mark row. The other stops have no
offer to ride on, so they are not plotted.

**Checks that could not fail:**
- Drop and the press were checked after the one-second tick had already fixed
  the screen. They are now read in the same turn, the press with stops on the
  glass.
- "Kind and time uncut" measured up to the first " · ". It now measures the time
  itself.
- The unprompted suppression had no check.
- Earlier, a corpus state "6A" never reached STATES, and a CSS rule nothing
  could reach was deleted.

Checks: test_parser, corpus.test.js, parser.test.js, test_scan_pi, test_loop,
test_server, test_journal, test_dashboard, test_layout, test_lint.


**An address the phone printed under "Dropoff" while an order was held still needed a ⌖ press.** The driver: "set its destination whenever the screen shows an address directly under a Dropoff label". While ✓ Took is in force, an unprompted read whose address sits under a Dropoff label in its own stop block (`OP.address_under_dropoff`: the nearest label above says dropoff, and no other address lies between) — or the Trip Planner's one dropoff on `planner_auto`'s whole-screen read — goes out `labelled: 'dropoff'`, never on a press. server.js files it when the hold has no end or only the card's own (a corner, a town); never over a ⌖ press or an earlier screen-read end; only when read after the Took; never when it is one of the hold's planner pickups. Its mark row is `asked: false, labelled: true`, and the fold lets that mark past the card's own end on the offers page. Checks: test_server 'auto-dropoff:' 6, test_loop 5 (one added: a second address under another's label, the only shape `address_under_dropoff` decides on a whole-screen read), test_parser 'address_under_dropoff:' 5, test_scan_pi 2. 13 mutations, each killed by name.

**A Trip Planner dropoff at a hotel was read with no address, and the one dropoff on a list that ran off the screen was never filed.** The hotel block reads Address / <place> / <Town> / <n> <street>, <Town>, <ST>, no ZIP: no town line in the two lines under the label, so the stop kept its name and lost street, town and line, the card's corner stayed the destination, and GPS arrival never armed ('no house number'). Now, with no town line in those two, the street is the line opening with a house number, down to View details and no further, with its town on it or under it; the line above it is the stop's new `place` (shown, never the street, and never searched — until the owner's decision of 17 Oct, "An order's door on a campus" below, which searches it for a held end whose door the NucBox lacks), and the town said again is not the place. Both ports; every earlier shared case unchanged but `place: null`. And the owner's decision, trust a single-trip offer: on an unpressed whole-screen read only, a list whose end is below the screen ('list') showing exactly one Dropoff stop of one order with street and town sends it `singleCardOnly`; server.js files it only onto a held card of one order on one leg (`card.legs === 1`, `card.multiOrder === false` — the offer line now says `multiOrder`, from "(2 orders)", "+1 order" or any count of two or more), clears the planner's 'list' when it does, and every other auto-dropoff rule still applies. Checks: shared planner cases 4 (the hotel; a place over a one-line street and town, the town said again, and nothing taken past View details, added — each rule had no case that told it from its absence), test_loop 3, test_server 'auto-dropoff:' 5 (two legs, and the 'list' cleared, added), test_scan_pi 4 (`singleCardOnly` on the wire and `planner_lone_dropoff`'s rule, added). 23 mutations, each killed by name.

**The held order's own card, read again under a new id, was weighed against itself, and a second Took dropped the first order with no row.** Measured on the 12 Oct shift (04:00-04:00 New York): 9 cards logged under two ids each; one was the card just taken, and its pair row, 19 s after the Took, read stack `warn` under a PASS headline — 1 of the day's 44 pair rows. server.js `heldOwnCard`: a card arriving within `HELD_CARD_MS` (3 min) of the Took with the same pay to the cent, the same miles and card minutes, and the same pickup and dropoff wherever both carry one (case, commas and spacing ignored) is the held order's own card: no pair row, no stack line, `heldCard` on the offer and the reading; recognised on arrival, it stays so however long it is on the phone. The panel shows Took as "✓ Took $X · in car", a press records nothing, and a note says it is not a new offer; a Took sent for it anyway keeps the hold. A Took on another card while one is held writes the old hold's drop row `by: 'replaced'`, and the status row says "previous order put down" for a minute, from the reply and from the stream. Checks: test_server '[held again]' 12 and '[replaced]' 5 (a different distance, a different card time, and a recognised card read again past the window, added); test_dashboard 4 per panel and 1 (the reply's word, added). 24 mutations, each killed by name.

**Every decision about where the order in the car ends moved into `assemble.js` (Stage 3), and a Trip Planner is filed from several pages.** The server's dropoff branch, the singleCardOnly check, the planner pickup guard, forgetPlanner, recordPlanner's one-row rule, heldOwnCard and the scanner's planner_destination and planner_lone_dropoff live in a module with no I/O; server.js writes and says what it decides, and the scanner only types what it saw. With one hold every decision is the old one: test_server's 689 checks passed unchanged and 'one hold: the assembler files what the old branch filed' compares the two roads. Pages are stitched only on positive cues: same app, no other screen between, within STITCH_MS (20 s, chosen), aligned on shared `kind|name|time` keys or a cut header over the next page's address block with equal times, never where a page fits in two places; the list is bounded when the title and Waybill have been seen on linked pages. Each value on the hold says where it came from (press > label > planner > card > seen); a screen value given unprompted is replaced only by a press. `dropoff_said` is forgotten when `.holding.json` names a different order. Checks: tests/assemble.test.js over tests/fixtures/sequences.json, test_server, test_loop; 19 mutations, each killed by name.

**Screens are typed and kept as sightings (Stage 2).** `screen_type` / `screenType` names eleven screens (Uber offer, add-on, planner, pickup navigation, navigation, finding, Trip Radar; DoorDash offer, finding, switch; unknown). Built from the 12 Oct shift's 1,237 screen rows and its offer texts; over 12,230 distinct texts the two ports agree on every one. find_planner keeps an address block above the first header as a stop of kind None (`partial: 'top'`) and marks a last header with no address and no Waybill `partial: 'bottom'`; the planner line and every filing rule get only headed stops, as before. server.js counts sightings by type on /api/status and journals no address for them. Found, not fixed: find_planner reads DoorDash's "Pick up 2 orders" / "Drop off 2 orders" as headers; the scanner is safe because the offer test runs first.

**The same card was filed under two ids when the driver paged away and back.** OfferLog remembered one card; it now keeps the cards left in the last RESUME_WINDOW_MS (RECENT_CARDS, 8) and gives back the id of one identical to the cent, the minute, the mile and the places where both name any; the seq carries on. Replayed over the journal: 12 Oct 8 removed of 9, 0 wrong; all 288 removed of 5,199, 0 wrong found. server.js: the held card back under its own id is the held order, not a pair.

**Held orders became a list (Stage 4), and two can be carried behind `carryTwo` (Stage 5).** `scanner.held`, first-taken first, read only through `heldOrders(now)` / `holding(now)` and capped by `maxHeld()`; `holding.json` is `{v:2, orders:[Hold]}` (a v1 file restores as one order with its clock unchanged; the build before the list restores nothing from v2, checked against that build). With `"carryTwo": true` in rpi/config.json settings: a second Took adds (5 s Undo), a re-offer replaces `by:'replaced'`, a third Took puts down the order ending soonest, an Uber add-on is held with its base, a DoorDash two-order card is one hold, a planner that grows adds nothing. Attribution: the app must match and a read older than an order's Took is not that order's; then store name, "Expected by" against "Deliver by" ±2 min (chosen), list growth, elimination on a bounded list; a tie is broken only by the door inside exactly one card's disc. No cue: a ⌖ press opens a chooser over the verdict pane and files nothing unless a row is picked (closes in 10 s; a late answer is refused); an unprompted sighting waits unwritten. Drop is one tap at one door, otherwise the same chooser; GPS drops are per order. Rows gain `cue`, `carried`, `by:'chooser'`, `heldAlso[]`, `heldCount` (the offers page leaves heldCount>1 out of grading); with the flag off the mark and tally rows carry `would:{cue,held}` only. Checks across test_server, assemble.test.js, test_layout, test_dashboard, test_offerspage and test_scan_pi; every one mutated to fail by name.


**The navigation screen is read on its own while an order is held, and Uber's opened sheet is the dropoff by the owner's decision (14 Oct 2026).** While an order is held, a card-box read showing the planner, `uber.nav`, or an address under a "Deliver to"/"Dropoff" label asks for one whole-screen read (`auto_read_for`), one clock for every kind (`SCREEN_AUTO_EVERY`, 10 s). Its address rides the sighting and `assemble.js`'s `navCandidate` files it at a new rank, `nav` (press > label > nav > planner > card > seen): never over a press, over an earlier screen-read end only as the same street read fuller, only after the Took, never off `uber.pickupNav`, under a Pickup label, under no label, or as a held pickup. Uber's "Deliver to" bar prints a name, never an address, so on the 12 Oct screens the labelled read alone filed nothing. The opened sheet prints name, street, town (no ZIP) and "Dropoff type" below them: `sheet_dropoff` / `sheetDropoff` read it as a dropoff label (a real house number not starting with 0, the town on the street line or under it, a "First L." name above, no other address between). `screen_address`: on a frame typed uber.nav with no payout the "6 min · 1.7 mi" bar is taken out before it can make an offer; over the journal's 10,991 offer texts and 36,118 frames nothing changes. `numberFuller`: a later read on the same street and town with a longer house number ending in the filed one replaces it. Replayed on 12 Oct against the orders ticked: 4 of 18 held orders that showed navigation would have had their destination (22%); 10 of 18 sheet reads read. Open: the first filed read can carry a house number with leading digits lost, and its mark row is written before the full read replaces it. 45 mutations across the two passes, each killed by name.

**A held pickup stayed the next stop after the car had collected the food.** The door's arrive/dwell/leave rule is one function, `stepAt`, and each held pickup pin runs it (`visitPickups`): a pickup is marked `visited` with `by:'gps'` when the car LEAVES it. Replayed on 12 Oct: of the 2 orders whose restaurant stand-in fell inside the hold, both were marked 96 s and 56 s after the car left; marking at the dwell would have said "Dropoff" for up to five and a half minutes over a car still waiting for food. Pickups within 150 m of each other are visited together (the owner's figure). A planner read marks a pickup `by:'planner'` only when it shows the top of the list (its sighting's `page.top`) and a stop listed after the pickup; a read that still lists a visited pickup does not un-visit it. With two orders each pickup is the order's whose card names that store (`Assemble.attribute`); a pickup no cue gives to an order guards doors and is never marked. Visits live on the order's `pickups` in holding.json; the panel's next stop, Map view's run (visited drawn as a faded ✓) and MV.detourThrough's stops leave them out. Journal `kind:'visit'` rows carry the hold and pickup index, no address, no coordinate. test_dashboard's watchdog is 480 s (it ran within 4 s of 300) and a harness check says the headroom. Open: a pickup with no pin is never visited by GPS; a pin at the wrong branch where the car happens to wait 60 s would take the real restaurant off the run.


**A planner page with no stop header was unread.** Both parser ports return a page holding only an address block with Waybill under it as one stop `{kind:null, partial:'top'}` (no header anywhere, the address read, no title); `assemble.js` joins it under the previous page's `partial:'bottom'` header by the existing rules (same app, no screen between, within STITCH_MS, equal times where printed, one placement). Alone it files nothing; the planner line and every filing rule still count headed stops only. Corpus 6 cases, sequences 8. 14 mutations, each killed by name.


**With an order in the car, a ⌖ press while screening another card went onto the order and replaced its end.** Measured at b337a44 against the real server, one order held with its end on record and a different DoorDash card being screened, carrying two off and on alike: a press filed onto the held order whatever the phone showed; over the card's own customer popup the popup line had already filed that address on the card, so one address became both jobs' end; and the unpressed whole-screen read that popup asks for also made it the held order's end over an end its card printed. Now `Assemble.pressBetween` decides a press when one order is held and another card is screened (not the order's own card, not one already taken): to the card on the card's own place popup; to the order on Uber navigation or the Trip Planner read since its Took, of its app, naming its store; otherwise the Stage 5 chooser with ①, "This card" and Neither, filing nothing unless picked, closing after `CHOOSER_MS`, refusing a late answer. With two held, `whoseDropoff` first asks whether the screened card could own the press; while it could, `only` (elimination by app and Took) does not choose an order, and the chooser asks ①, ②, This card or Neither. A card given its end this way carries `dropoffFrom: 'press'` or `'chooser'`, becomes press rank at Took, and says "END · from ⌖"; the ⌖ button stays the held order's; `navCandidate` refuses a place popup. Nothing held: unchanged. 33 mutations, each killed by name. The flaky "key with the held pickup" check at 480x320 was the page's one-second repaint putting `between` back mid-measurement; the class is now removed inside each narrow-map measurement.


**A server review found sixteen faults in the multi-order and GPS-drop code, each reproduced and fixed.** Review ticks from the offers page or Close the shift no longer change the car (only via 'panel'); the GPS drop arms only on a card that says `multiOrder: false`; an end filed onto the order is saved to holding.json with or without a NucBox, and holding.json is written through a temporary file and a rename, an unreadable one kept as `.bad` with a log line; `only` is refused when a list seen whole has more dropoffs than the orders the hard rules leave, and an address no order can own is dropped rather than parked; STITCH_MS is 60 s, twice SCREEN_AUTO_HOT, so a hot Pi still stitches; the scanner's config save writes only its own keys onto the file on disk, the server caches carryTwo by mtime, and turning it off with two held never drops below what is held (a Took then replaces the first-taken, with its row); one pair row per order weighed and offer id; a Took from a panel behind the slot is dated from its own card; the beat carries `holding` when it changes, so an expiry takes Drop off the panel. Performance on a synthetic 22 MB / 50 MB journal: rowsFor after an append 4.5 / 10.6 ms → 0.01 ms, /api/today 4.3 / 7.5 → 1.8 / 2.5 ms, the fold byte-identical; days= folds round to local midnight and keep 3 (RSS 181 → 393 MB over 31 loads before, flat at about 175 after); holding.json written only on change (252 → 127 writes a simulated shift); the NucBox cache capped at 8 MB as well as by count (heap 185 → 36 MB at 500 long routes). Scanner-line handler faults are logged with their stack. 35 mutations, each killed by name.


**Two OCR slips and a garbled title lost a Trip Planner dropoff (16 Oct).** The shift page read "Addres" for the label and "<Town>. GA" for the town line, so the dropoff kept no street or town and the order kept the card's corner ("no house number"). Both ports now take the label at one edit from "Address", alone on its line (planner_furniture still needs the exact word), and a town line with "." or no separator before the state, only under an Address label, capitalised, not opening with a digit, and never "NE" in the loose form. 0 outputs changed over 532 corpus texts and 12,229 journal texts of 12 Oct. The page's title read "ny. mS", so by the owner's decision (17 Oct) a whole-screen page counts as the Trip Planner when its layout proves it: a Pickup and a Dropoff header, each with its Expected by, View details, and the Stop New Requests bar (`laidOut`, scanner and assembler); it never counts as the list's top, presses are unchanged, and every other lone-dropoff guard applies. 0 journal texts newly qualify. Checks: shared planner cases, 'a planner whose title was misread files its lone dropoff when its layout proves it' and its three refusals; 24 mutations, each killed by name.

**A planner street ending "Pl" read "P" or "PI" never found its door (16 Oct).** After the fix above the same evening's planner filed its dropoff, but the street came out "<Name> P" on one frame and "<Name> PI" on the next, and the NucBox found no door for either, so the hold said "not inside the card's reach" and GPS arrival never armed. Both ports now read a final "P", "PI", "P1" or "P|" on a planner street as "Pl" when the word before it is a name of two letters or more and not itself a street type ("<Name> St P" keeps its letter, as _planner_address decides). Planner streets only; every earlier shared case unchanged. Checks: shared planner cases 3 (P, PI, and a P after a street type); 4 mutations, each killed by name.

**A ⌖ press at the restaurant replaced the held order's door with the store's town (17 Oct).** Measured off the shift's snap bundle: an Uber order held ($11.09), its Trip Planner read unprompted and its dropoff filed with a house number (`from: 'planner'`); at the restaurant ⌖ was pressed over Uber's navigation to the store ("Arriving soon / <Store> / <n> <Street> & / Suite 128, <Town>, GA / 30066 / Note from business", typed `uber.pickupNav`), the read gave the town line alone, and `outranks()` lets a press past anything, so "<Town>, GA 30066" became the held order's end (`from: 'press'`, screen `uber.pickupNav`). The panel turned ⌖ green, "Dropoff read as <Town>", Map view ran the order to the town's centre, and every offer for the next 20 minutes was judged against it. `navCandidate` already refused an unprompted read off that screen; a press never met the check. `Assemble.dropoff` now refuses a PRESS going to a held order when its screen is `uber.pickupNav` ('a pickup screen', whatever line it read) or its line is a pickup of that order by any word on record (`heldPickup`: a planner pickup, the planner's `pickupAddr`, the card's pickup; 'a pickup'): nothing filed, no mark row, the hold's end unchanged. It is asked in `dropoff()` alone because every road a press takes onto a hold ends there (straight, `pressBetween`'s navigation cue, the chooser's order row, `attribute()` with two in the car). A press with nothing held still files on the card being screened, and every other rule is as it was, the chooser opening over a store's navigation with a card screened included. `dropoffArrived` answers the refused press on the stream with `{line: null, found: false, asked: true, refused, kept}`, never the line it read, so a panel from before this says "⌖ not read" and never green; `/api/choose` answers `filed: null` for it. live.html's ⌖ reads "⌖ a pickup", uncoloured, with "Restaurant screen, not where this order goes — kept <held end>. Press again over the customer's address." on its title and spoken label, until the press's other answers go or an address arrives. Checks: assemble.test.js 10 ('a press over Uber's navigation to the store is refused while an order is held, and the planner's door stays its end', the held pickup by each of its three words, pressBetween's cue, the screened card with nothing held, and the ordinary press that still replaces); test_server 6 end to end, carrying two off and on ('⌖ over Uber's navigation to the store leaves the held order's planner end on /api/status, writes no mark, and tells the panel why and what was kept, never the town', the held pickup's door, the chooser's row); test_dashboard 3 a panel; test_layout 2 a landscape panel (each of ⌖'s answers inside its button on the fullest bar). 14 mutations, each killed by name. Suites: assemble.test.js 272->282, test_server 858->864, test_dashboard 1303->1309, test_layout 3890->3898.

**An order's door on a campus was never pinned, and the delivered order stayed held (17 Oct; the owner's decision, the same day, to search the place).** An Uber order's door was "1000 <Road> NW, <Town>" on a university campus. The NucBox's Nominatim holds the road and no house 1000, so `searchHeldEnd` got the street alone ('nodoor', "no house number"), and so did Map view. GPS arrival never armed. The phone had printed the stop's place ("<Something> Parking Deck"), which the readers carry as `place` and which was shown and never searched (the hotel entry above). Now, only when the door search of the held end comes back 'nodoor' and a place is on the hold, the server asks the NucBox `q=<place>` alone in the same `discBox` (`searchHeldPlace`). It pins only what `MV.pickPlace` allows: a named feature (Nominatim `category` in `PLACE_KINDS`, which covers building, amenity, shop, office and the like, never `highway` or `place`, and with a name of its own), whose name `MV.placeNamed` takes for the place, inside the disc, alone or agreeing, from a list not cut at the limit. `placeNamed` ignores case, apostrophes and marks, reads "&" as "and", and reads 0/1/5 as o/l/s inside a word of three letters or more. It needs four letters, the same words in the same order, and at most one word one letter out (put in, taken out or changed), that word four letters or longer, with no slip in a word that carries a digit. So "Fable Parking Dec", the reader's own read, names "Fable Parking Deck"; "Wrenfield Deck", "Deck 1200"/"Deck 1300", "Lot A Deck"/"Lot B Deck" and "Gate 105"/"Gate Los" do not. The town is not sent, as with every NucBox question: the real install answered a q with a town after a comma with nothing. The pin is `by: 'place'` (`endBy`), now part of `heldEndState`, so /api/status, the beat and the mark reply carry it. The panel's in-car line reads "● armed by place" (narrower than "too many answers", the widest the layout test measures), and a refusal reads "no door, place not found" ("no door/place"). The restaurant and customer guards hold it as they hold a door. The public geocoder is never asked, and with `NUCBOX_SEARCH` unset nothing is sent. The place reaches the hold minimally: `emit_dropoff` sends `place` (the customer sheet's, else None), and `candidate`/`navCandidate` carry a planner stop's or a sheet sighting's. `Assemble.file` keeps it as `dropoffPlace` with the end it came with, and an end filed without one drops it. `endKeyOf`/`endWhyFor` use `endTextOf` (the dropoff, then the place), so a place learnt later for the same text is searched for; with no place it is the dropoff exactly, as old holding.json files have it. `nbxHits` adds `kind` and `called`. Map view's own walk falls back the same way through `NbxSearch.place` (`opts.place`, given only for the held end; `placeSearch` asks the server's question, so the two share its cache), draws the pin, and never posts it, since `/api/held-end` still takes doors only. Checks: mapview 505->542 (placeNamed's 23 cases, namedFeature, placeQuery, pickPlace on each branch, the words, through the server: pinned, asked as the place alone bounded, a road refused, a door outside the disc not replaced by the place, a held door never asking the place); assemble 6 (a sheet's, a planner stop's and a press's place onto the hold, taken away by an end without one, placeOf); test_server 12 '[place]' (pinned by place and said on status and the beat, asked once as q= alone with viewbox and bounded, the restaurant guard, the reader's lost letter, a word short, a road, outside the disc, a held door never asking, no place, a place learnt later, NUCBOX_SEARCH unset); test_scan_pi 1; test_dashboard 3 (the in-car line both ways, Map view pinning the place and not without one); test_layout 14 (the refusal's sentence and its chip, "no door or place" since the whole of it ran past three rows at 480x320). 50 mutations, each killed by name. Open: the owner should check what the real install answers for a read with a lost letter ("...Parking Dec"), which the fake answers as the deck. Only 'nodoor' falls back: a street the NucBox does not hold at all ('none'), or a dropoff with no house number, is not searched by its place.

**A ⌖ press over a store's navigation still filed the store's address onto the card being screened (17 Oct).** After 69c8bf7 a press off `uber.pickupNav` was refused for a held order, but with an order held and another card on the slot the chooser opened (the test said so), and "This card" filed the store's town onto the CARD. With nothing held the press filed onto the screened card straight away. Uber draws that screen only for an order accepted, never over an offer, so by the owner's rule ("a store's screen is never a dropoff for anyone") it is now refused whoever it would have gone to. `Assemble.dropoff` asks `storeScreen` for every press before the hold and the card are reached, and `storeScreen(null, d)` is 'a pickup screen' for that screen; the held pickup's words stay the hold's alone. `whoseDropoff` opens no chooser and asks no cue for such a press (`store`), with one order or two. The simplest honest answer: a chooser whose every row refuses is a question with no right answer. `dropoffArrived` says the refusal on the stream as 69c8bf7's did, `{line: null, found: false, refused, kept}`, with nothing held too, `kept` null ("nothing filed"), so the panel shows "⌖ a pickup" and never green. No AUDITS decision covered a press with nothing held over that screen. 69c8bf7's own entry recorded only that it still filed, and the screening-press habit the server's comments record is DoorDash's popup, which is untouched. An unpressed read off that screen was already refused (`navCandidate`). Changed tests: assemble.test.js "with nothing held a press over the store's navigation still files on the screened card" now says it is refused and the card keeps its end; test_server's chooser case under '⌖ at the restaurant' now expects no chooser and the refusal at once; and '...a press never replaces the held end without a cue or a pick' no longer expects a chooser for the store's navigation. Checks: assemble 3 more (no card, another screen still files, storeScreen with nothing held); test_server 'nothing held: ⌖ over Uber's navigation to a store is refused for the card being screened...', carrying two off and on. 7 mutations, 6 killed by name; the seventh (refusing an unpressed one too) survives, see Open. Open: an UNPRESSED dropoff line off `uber.pickupNav` (a card-box read under a Dropoff label) is still `seen`/label like any other, since only presses are refused; refusing it too changed no check. Suites, both entries: assemble.test.js 296->304, mapview.test.js 505->542, test_server 888->903, test_dashboard 1314->1317, test_layout 3958->3972, test_scan_pi 566->567.

**The planner's door "1830 <Name> Creek Cts SW" found nothing on the NucBox, so no pin and no GPS arrival (17 Oct, evening).** The owner's snap: an Uber order held, the card's fix good to ±24 m, its disc 12.6 mi, the Trip Planner's door printed with the app's "Cts" (the card's cross streets said "<Name> Creek Cts SW & <Name> Ct SW" too). The NucBox answered nothing (why is not measured: "Cts" is at best Courts to a search that reads "Ct" as Court): `endWhy` "not inside the card's reach", no pin, GPS arrival not armed. Now the door is asked ONCE more with the street's trailing type word left out, house number, name and quadrant kept ("1830 <Name> Creek SW"; `MV.streetRetry`, its types in `STREET_TYPES`, families of spellings: Cts, Ct, Crt, Court, Courts are one). It is asked only when the street as printed is not inside the card's reach (`MV.retryWanted`): 'none', or 'nodoor' with no answer inside the disc. A 'nodoor' with the street inside means the type word was not the trouble, and the place is asked as before. Never 'several' or 'capped'. An answer is taken only at door level (hasDoor in pickInDisc), inside the disc, alone or agreeing, AND on the same street (`MV.retryFits`): the same name words, then no type or one of the printed type's family, then a quadrant or none. So "1830 <Name> Creek Drive" is never the door of "...Creek Cts", because a wrong door is one the GPS would end a delivery at. `MV.afterRetry` picks the retry's answer when it pinned or found the street (the place is then asked as after any 'nodoor'), else the first's, whose refusal stands. The server (`searchHeldRetry`, `settleHeldEnd`, through `endAsk`, so nbxCache and the NucBox-down retry are as the first question's) and Map view (`NbxSearch.place`, `pickRetry` in `search`) ask the same words, so they share the server's cache. The pin stays `by: 'server'` (door level is door level, the panel unchanged), and `/api/status` holding gains `endAsked`, the street the door was found by when it was not the dropoff's own (pin `asked`), else null. The public geocoder is never asked; with NUCBOX_SEARCH unset nothing runs (armHeldEnd). Fake: "1830 Tansy Creek Cts SW" answers nothing, "1830 Tansy Creek SW" a Court door and the same number on Tansy Creek Drive, and "2040 Tansy Creek SW" the Drive's alone (invented). Checks: mapview 542->563 (streetRetry's 8 shapes, streetType, retryFits' 10 answers, pickRetry Court over Drive where pickInDisc says 'several', the Drive alone refused, capped and street-only, retryWanted's 7, afterRetry's 5; through the server: pinned and asked as the two questions, the second page from the cache with nothing asked, the Drive refused, a street found inside never asked again, no disc no retry); test_server 903->908 '[street retry]' (pinned, `endAsked`, both questions on the wire; the next order from the cache; the Drive refused with the first refusal; outside a 1.0 mi card refused; a door found as printed says no other street). Mutations: map-view 17 of 17 killed by name; server 5 of 6 killed by name (no retry, pickInDisc for pickRetry, the first answer only, no `asked` on the pin, a retry after a 'nodoor' inside the disc); the sixth, `asked` set whatever the retry answered, was equivalent (a pin on that path is only ever the retry's), and the code now says the simpler. Open: what the real install answers for a street with its type left out is not measured (the fake answers it as a free match on the name does), and the owner should check "1830 <Name> Creek SW" on the NucBox.

**The planner took the scroll bar and the stop's icon for the stop's place, and left the bar's letter on the street (17 Oct).** The same snap's first dropoff block read "Address E / 7 cy ee / <n> S <Name> Dr Sw a / Marietta, GA". Nothing in the two lines under the label was a town line, so the hotel layout (PLANNER_HOUSE) took "7 cy ee" as the stop's `place` (two letters in a row was the whole rule), and kept "Sw a" on the street, since PLANNER_LONE_LETTER only looks after a street TYPE and only on the town line's mark. A place is searched now (the campus entry above), so junk taken for one is a question asked of the NucBox. Both ports: (1) a place must be shaped like a name (`looks_like_a_name` / `looksLikeAName`): a word of three letters or more (PLACE_NAME_WORD) and letters for at least half of the line's non-space characters, for the planner's place (`_planner_place`, the first such line over the street) and the customer sheet's (`_sheet_place`); (2) a lone letter after a two-letter QUADRANT at the end of the street (PLANNER_QUADRANT_LETTER) is the bar's mark when the column shows on the town line (as before) OR on the label (`_planner_label_tail` / `plannerLabelTail`: anything after "Address", which the app never prints). After a quadrant the letter is no quadrant, so the label's mark is enough. After a suffix the town line's is still needed, because there the letter may be the real quadrant (Cobb Pkwy N). With both lines clean the letter is kept, as a unit's may be. The orphan stop (`_planner_orphan`) reads its label the same way. Measured before the new cases went in, over the shared corpus's 506 distinct texts (cases.json and sequences.json, `text` and `page`): find_planner and sheet_dropoff change on 0. Every place on file ("Larksour Inn & Suites Kennesaw NW", "Larksour Inn & Suites", "Fable Parking Deck", "Fable Parking Dec", "Fable Internationa", "1200 Fable Tower") is unchanged. No planner street in the corpus ended in a quadrant and a lone letter. The rig's journal is not in this tree, so it was not measured. Shared cases (invented streets): planner 7 (the 17 Oct block; a letter after a quadrant kept with both lines clean; taken on the town line's mark; the label's mark not taking a letter after a suffix; a junk line passed over for the name under it; "4 ~ }} Inn" no place; a stop the page begins in the middle of), sheets 2 (the same "4 ~ }} Inn"; a name-shaped place still kept). test_parser 1321->1337, corpus.test.js 1241->1257. Mutations: 11 per port, 22 of 22 killed by name (never/always/no label/no town line, the label on a suffix's letter, two letters for a name, no half-letters rule, the old sheet rule, the old planner rule, the label tail false, the orphan's label not passed).

**A batched Uber trip — one card, one ✓ Took, two doors — had its Trip Planner's dropoffs go unfiled, and nothing knew it had two (17 and 19 Oct; the owner's decision of 19 Oct).** 17 Oct: a card "$23.02 · 51 min (12.1 mi) · <Store A> (40 <St>) · <Cross> & <Cross>, <Town>" (legs 1, multiOrder false), then a planner of Pickup <Store A>, Pickup <Store B>, Dropoff <Cust 1> (Expected 5:42), Dropoff <Cust 2> (6:00), the card's corner the LAST dropoff's street; 19 Oct: one store, two dropoffs (7:27, 7:38). plannerDestination said 'dropoffs' and the order kept the card's corner (or one door). **The rule (`Assemble.batchPlan`, called by `sighting()` with ONE order held):** an unpressed planner read under its title or layout, the list seen whole (top and foot, one page or stitched — the existing bounded notion, never a list running off the screen) and not short, listing MORE than one dropoff, is that order's trip. Its end is the LAST door: the latest "Expected by" (unwrapped past midnight); a tie goes to the dropoff on the card's street when exactly one is, else the last on the screen, which is also the answer when any dropoff printed no time. It files as a planner end (`from: 'planner'`), over the card's corner and over an earlier door a navigation screen or planner filed unprompted, never over a press. The hold gains `batch: true` and `drops` [{line, name, expectedBy, key}]; the planner's stops stay as they were, its pickups pinned by the server's existing pickup search. Refusals, said on /api/status as `batchWhy`: 'card end elsewhere' (the card's corner or door names none of the dropoffs' streets — the list may hold an order taken on the phone with no Took), 'no card street' (a card that printed no street is no witness: nothing batched; a choice, not the owner's words), 'address' (the last door has no street and town — the order waits; an earlier one without is left off `drops` and does not stop the batch), 'an add-on'. With two orders held (an add-on's trip, carrying two, or two restored with the flag off) server.js drops a batch candidate whole, and sightingMany never makes one. **The GPS drop** arms on the end alone, so the first door never puts the order down; a pin posted for it is refused as not the order's end. **The batch goes with its order:** it lives on the hold, so a later Took (replacement rules unchanged), Drop, the GPS drop or expiry takes it. **Journal:** the mark row gains `batch: true, drops: N`, a flag and a count, no door list. **Panel:** "2 drops" in the in-car line: between offers after the pay ("$23.02 in car · 2 drops · ● armed"); under an offer at the head of the stop, the part that gives way ("· In car $23.02 · ▸ 2 drops, <street> · ● armed") — beside the pay it pushed the GPS words off the glass at 800x480 and 480x320 beside the scene picture with the card moving (measured), and on the 3.5" hat under an offer it is left out, since there even the stop has no room to give (it cut the stop's last letters); between offers the hat says it. `drops` on heldForPanel (null for one door); fits every panel parked and driving (test_layout "pair batch", "between batch"). Settled stands: no cue means no filing with two orders — this is one order and its own planner; the chooser never times out into a guess; the lone-dropoff rule (`singleCardOnly`, card.legs/multiOrder) is untouched; a press over the list is still the press's rule. Checks: assemble.test.js 326 → 343, test_server 934 → 948, test_dashboard 1334 → 1335, test_layout 4226 → 4306 (the README said 4226; 4306 counted here, both new forms included). Mutation testing deferred by the owner's decision of 19 Oct (speed for experimental); to run before main. Open: the CARD is not yet recognised as a batch — no snap of a batched offer card is on file — so the panel and the pair line treat it as one order until the planner is read; the visits to earlier doors are not marked. Mutations (catch-up, 21 Oct): 25 on batchPlan, its helpers (streetCore, cardStreets, cardEndOf, byKeys, batchWhy) and its road through sighting(), dropoff() and file(); 11 killed by the checks above, 14 survived and are now killed by 14 new named '[batch]' checks (one dropoff, `addOn` alone, `of` alone, a last door with no town, a tie with both doors on the card, past midnight, a door with no time, a short list, "and"/"at"/"/" corners, a house number making a street, the sighting's own reason, batchWhy for another hold, no house tally, the planner line's "dropoffs" cleared, the last door filed alone then batched); none equivalent. assemble.test.js. Mutations (catch-up, 21 Oct; the "2 drops" cue in live.html only): 5 run, 2 killed by '[batch] a batched trip says its doors' (between offers, and at the head of the stop under an offer), the cue under an offer on the 3.5" hat too by test_layout 'the card moving, "pair batch", is whole, nothing clipped, at 480x320, scene view', 2 survived and are now killed by test_dashboard: "1 drops" said for a count of one ('[batch] ...and a count of one says nothing of drops') and the line under READING THE SCREEN without it ('[batch] ...and beside the pay on the line under READING THE SCREEN').

**A garbled planner street filed first was never replaced by the clean reading of the same stop (19 Oct night).** The planner's dropoff read "1106 Commor" on several frames while the phone said "1106 Commons Ln"; both are a street and a town, the same conf, so outranks() kept the first and its end was never found. Now a later reading of the SAME planner stop (same key) is 'fuller' also when its street ends in a street type (offer-parser's STREET_SUFFIX, copied as assemble.js loads nothing) and the one held does not, the house numbers equal (`typedOver`). Never the garbled one back, never another number or stop, never one typed street over another. The dropoff text changes, so the held-end search runs again for it (one search per hold and text, as before). Checks: assemble 5; test_server '[typed street] ...'. Mutations (catch-up, 21 Oct): 7 on typedOver and its place in outranks(); 4 killed, 3 survived (the type word needing a name before it, the house number, the new reading typed) and are killed by three new precedence checks ('...nor one untyped reading over another', '...nor a bare type word with the street's name lost', '...nor a street with no house number'). MV.bareDoor is Map view's, not in this pass.

**Rescanning kept a wrong house number read once over the same stop read right every time after (the owner, 19 Oct 21:41).** The planner's dropoff "905 <Name> Dr" read "305 <Name> Dr" first and was filed; every later read said "905", the same stop key and as complete, so outranks() kept "305" (not 'fuller', not typed over), and sighting()'s once-per-line dedupe never let a repeat reach dropoff() at all. The door was never found. Now the hold keeps `dropoffReads`: the stop's key and the street lines (streetKey: house number and street) of its last `VOTE_READS` = 5 unprompted planner readings (CHOSEN, not measured), the filed one counted. `plannerVote`, asked by sighting() for every such reading before the dedupe, says a reading wins when its line is seen more often than the filed one's and as often as any; the winner passes the dedupe (`vote`), and dropoff() files it 'most read' only over a planner read of the same key. A tie keeps the filed one; another key starts the tally anew; never over a press or anything not that stop's planner read. The dropoff text changes, so the held-end search runs again. Checks: assemble 348 -> 354 '[vote]' (tie then win, a lone old read back, another key, a press, three readings once each, the window); test_server '[house vote]' ("1385" once then "1985" x3 -> "1985" filed, searched, pinned, its point on status). Mutation testing skipped (fast lane). Mutations (catch-up, 21 Oct): 15 on plannerVote, mostRead, dropoff()'s 'most read' and sighting()'s dedupe; 2 killed, 13 survived. 12 are killed by new '[vote]' checks (a pressed read and a non-planner read not counted, a read with no street not counted, another stop's own tally that never wins, the tally anew back on the filed stop, a press filed with the stop's key, a line outvoted by a third, dropoff() refusing a handed `vote` across keys, before the Took or over a label's end, the winner past the dedupe through sighting(), and '[batch] ...no house tally'); 1 was equivalent (plannerVote's `line === filed` early return: mostRead already refuses the filed line) and the line is gone.

**A clean card-box read of the planner never replaced the garbled whole-screen read filed first (the owner, 20 Oct 20:44, carrying two on).** The Trip Planner's dropoff "2100 <Ellison> Lakes Dr / Kennesaw, GA" was read whole-screen as "2100 <Ellison> Lake r" and filed (from 'planner', cue 'only'); the NucBox found nothing ("not inside the card's reach"). Every read after was a card-box read of the planner (not whole), which the scanner sends as a dropoff line under a Dropoff label — rank `label`, no stop key — and said "2100 <Ellison> Lakes Dr" cleanly; but the typed-street replacement (`typedOver`, e140e44) and the house vote (`dropoffReads`, 51fe6ca) counted only the same planner stop's whole-screen reads, and a label does not replace a planner. Now `Assemble.dropoff` files an unprompted read under a Dropoff label after the Took, at rank `label` or `planner` (box or whole, any key), over the filed PLANNER street when the house numbers are the same, its street ends in a type word and the filed one's does not (no type, or a garbled last word: "r") — 'typed street' (`labelTyped`), at its own rank. Never over a press or a label read, never the untyped one back, never one typed street over another or another number. The same box reads are counted in the filed stop's `dropoffReads` (`labelVote`; the tally started with the filed line where it was another stop's or none) and file 'most read' when they win, over a planner read only; planner reads are still counted by `plannerVote` alone. The text changes, so the held-end search runs again. Checks: assemble 370→383 '[box typed]' (the fault's shape at rank label, the garbled one back refused at both ranks, another key's typed planner read, an untyped "Commor", another number, typed over typed, a press, a label filed, unlabelled and before the Took) and '[box vote]' (a box read counted toward the planner's next, two box reads winning alone, a press, a tie); test_server 992→994 '[box typed]' (carrying two on: garbled planner filed, the box read replaces it, searched and pinned by the server; a ⌖ press kept). Mutation testing skipped (fast lane). Mutations (catch-up, 21 Oct): 17 on labelTyped, labelVote and their place in dropoff(); 4 killed, 13 survived. 5 were equivalent, the same fact asked twice: rank `label` or `planner` already means a label-proven read after the Took, unpressed and no navigation screen, and rank `label` already means no planner stop. So dropoff() no longer asks `labelled && !nav` before labelTyped, and labelVote asks `from !== 'label'` alone (its `proven` argument and `d.planner` test gone, and its `line !== filed`, which mostRead already refuses). The other 8 are killed by new '[box typed]'/'[box vote]' checks (a navigation read, a press carrying the stop's key, a planner end with no key, a tally of another stop started anew, the window of 5 for box reads, a box read with no street) and the existing ones. streets.js cutFits is another pass's.

**Both doors of an add-on trip went unfiled because the Trip Planner was only ever seen in pages scrolled (the owner, 20 Oct 19:06–19:08).** An Uber order ① ($8.14, the card's end a corner, "<A> Rd NW & <B> Cir NW, <Town>", no house number) held; an Uber add-on ② (+$16.43) accepted and held correctly, `addOn`, `of` ①. The planner then showed both doors across partial reads — "1800 <B> Cir NW, <Town>" (customer A) and "608 <C> St NW, <Town>" (customer B, Expected 7:48) — but never the list whole, so growth and elimination (both a list seen whole) never spoke and sightingMany offered nothing: ①'s end stayed the corner ('no house number'), ② had none. **The rule (`Assemble.streetCues`, asked by `attribute()` for every unprompted planner dropoff with two or more held, so by the pool's retry too):** `cardStreet` — the dropoff's street NAME (streetCore: house number, type and quadrant gone, as batchPlan compares) is one the order's OWN card printed for its end (cardStreets of `seenAs.dropoff`: its door, or either side of an "A & B" corner), and no other held order's card names it; two cards naming it is no cue. Then elimination-lite, cue `elimination`: exactly two held, the read at or after BOTH Tooks (the add-on's), one order's end a planner door on its own card's street, this dropoff on no held card's street and not that door — it is the other order's, only while that one has no screen-filed end. Never a pressed read, never over a pressed end, never a pickup of any held order (planner pickups, the card's store and bracket, `fields.pickupAddr`). **Lists not seen whole:** sightingMany now offers their dropoffs read whole as candidates marked `partial` (no store, no list for growth), once per line, only unprompted and only while some held card printed a street; a `partial` candidate is asked these two cues and nothing else — no `only`, name, deadline, growth, elimination proper or filed — and with neither it waits in the pool ("1 dropoff read · whose?"). Filed, each end goes through dropoffArrived, which re-arms the held-end search for every order (armHeldEnd). /api/status `orders[].cue` says the cue each end was filed on (`endCue` on the hold: 'cardStreet', 'elimination', 'growth', 'chooser', ...). Settled stands: no cue means no filing, the chooser never times out into a guess; a list whose foot is off the screen still never reaches the lone-dropoff rule with two held. Checks: assemble.test.js 354 → 370 ('[cardStreet]', '[elimination]': the corner both sides, two cards naming one street, a press, a pickup, a partial read before the add-on's Took is no `only`, the second door by elimination-lite and not before the add-on's Took, nor over a screen-filed or pressed end, the two scrolled pages through the pool); test_server 989 → 992 '[card street]' (the snap end to end, invented names). Mutation testing skipped (fast lane). Mutations (catch-up, 21 Oct): 26 on streetCues, aPickupOfAny, attribute()'s `partial` gates and sightingMany's partial offer; 9 killed, 17 survived. 16 are killed by new '[cardStreet]'/'[elimination]' checks (a non-planner read, one order held, a card of an order taken after the read, a pressed end, the planner's pickups and a filed pickupAddr, two cards naming the street with the other's end filed, another app, no Took time, the first door's street on both cards, no store/deadline/filed cue on a partial read, a pressed page, a page's one pickup as no store, a page read twice). 1 was equivalent (elimination's "nor the first order's own door again": that door is on its card's street, so cardStreet has answered it) and the clause is gone.


**A single trip's dropoff whose header the reader lost was no stop at all, so the hold kept the card's numberless street (the owner, 20 Oct 21:08).** One Uber order held. The Trip Planner read whole-screen as "... View details | o <Customer> J | Expected by 9:34 PM | Address | 2400 <Name> Creek Blvd | Marietta, GA | View details": "Dropoff · 1 order" lost to OCR, the stop's lines in the pickup's block, find_planner made no dropoff, and the hold kept the card's end "<Name> Creek Bivd, Marietta". A box read of the same block ("Dropoff +1 order | © <Customer> J. | ...") parsed as that dropoff in both ports already — PLANNER_STOP takes "+1" and "+ 1" as the bullet (cases added, no rule changed) — and filed nothing because the assembler takes no planner page that is not a whole-screen read (`sighting`: `s.whole !== true`), and `address_under_dropoff` needs a ZIP the planner never prints. The rule, chosen as the most conservative that files the fault: **the parser** (both ports, `_planner_lost_dropoff` / `plannerLostDropoff`) keeps the lost stop as `kind: 'dropoff'`, `orders: null`, `partial: 'header'` only when the page's ONE header is a Pickup of "1 order" with no orphan block above, its block holds exactly two "Expected by", the pickup's own "Address" and then "View details" stand straight over the lost name, and under the second time an "Address" with a street opening with a house number and a town read; planner_ends still says unbounded, and planner_stops leaves it off the planner line. **The assembler** (`Assemble.lostHeaderDropoff`, asked by `sighting` for an unprompted read whose verdict is 'list') files it only when the list is that one pickup and that one dropoff, one order held and not an add-on's, and the held card's own end names its street (cardStreets/streetCore, as the two-order `cardStreet` cue), as `singleCardOnly` (one order, one leg); with two held it is a `partial` candidate and only `cardStreet` can file it. `streetCore` now reads "Bivd" as Blvd's slip (the parser's STREET_WORD already did). mergeStop takes the header from a page that read one, and keeps `partial: 'header'` only when neither did. The stop's icon read "oO" / "o" in front of a name goes (`PLANNER_ICON`, `_planner_name` / `plannerName`, a first word of one or two o's with two letters left after it): the panel had shown "oO Outback Steakhouse". Shared corpus, measured over 519 distinct texts (cases.json, sequences.json): one existing answer changes, the 16 Oct planner's dropoff name "oO Lee R. H" -> "Lee R. H"; the lost-header rule adds a stop to no text but the seven new cases (the fault; a pickup of 2 orders, no "View details" over the name, no house number, two headers lost — none; "Dropoff +1 order" and "Dropoff + 1 order"). Checks: corpus.test.js 1336 -> 1350, test_parser 1416 -> 1430, assemble.test.js 383 -> 394 ('[lost header]': filed onto the card naming the street with "Bivd", over its own end, from the planner; a press, another street, a town, no card end, an add-on, before the Took, two legs; with two held, `cardStreet`; a header that read is not this rule's). Mutation testing skipped (fast lane). Mutations (catch-up, 21 Oct): 48 — 16 on lostHeaderDropoff, its call in sighting() and mergeStop; 12 per port on the lost-header stop; 4 per port on the icon (PLANNER_ICON, the name). 19 killed, 29 survived. 25 are killed by new checks: ten shared-corpus planner cases, both ports (a header after the lost stop, a Dropoff as the one header, no Address in the pickup's block, the link read twice, an Address label over the time, a street not opening with its number, an orphan block above, the icon alone as the name, the second time on the block's second line, "Oo J" keeping its o's) and '[lost header]' checks (a pickup of two orders, a second pickup, a second dropoff, no town, `addOn` alone, `of` alone, a page below reading the header, two header-lost reads stitched). 4 were equivalent and simplified: lostHeaderDropoff's `all.length !== 2` (one pickup and one dropoff are the list), sighting()'s `verdict.why === 'list'` (always so for this stop), mergeStop's header-blind `cut` (a header-lost stop always has its street and town), and offer-parser.js's `times[1] < 2` (its `block[t - 2]` is then undefined, which PLANNER_DETAILS refuses; Python keeps it, its index wraps, and the new case kills it there). Open: no whole-screen text of the fault is in the repo, so whether its title or the bar read is not known; a lost header on a stacked trip still files nothing.

**A Trip Planner street with a suite after it read as no street (the owner, 21 Oct 13:57).** The planner's pickup printed "1985 <Name> Parkway NW, STE 120" over "Kennesaw, GA 30152", and the stop came out `{street: null, line: "Kennesaw, GA 30152"}`: STREET takes words to the end of the line and a comma is not one. Both ports (`PLANNER_UNIT`, applied in `_planner_address` / `plannerAddress` after the edge furniture) now drop a trailing unit and keep the street: ", STE 120", ", Suite 120", ", Ste. 120", ", Unit 4", ", Apt 2B" — the word only after a comma, so a street named "Suite" or "Unit" is never cut and "4821 Kestrel Dr Unit 4" with no comma is kept as STREET took it — and "#120" with or without a comma; the unit is a number, a number with a letter on either side, or one letter. The unit is not kept (`unit` was optional): the NucBox has no door for a suite, and the street is what is searched. Measured over the shared corpus's 556 distinct texts (cases.json, sequences.json): 0 find_planner, planner_ends or planner_laid_out answers change, and the two ports agree on all 556. Shared planner cases: the fault's page (invented) and seven unit shapes (each listed form, the suite between a street and town on one line, a unit's letter beside the scroll bar's mark, the no-comma word kept). Mutation testing skipped (fast lane).

**A single trip's Trip Planner with its title scrolled off was never filed, because the held card's legs read 0 (the owner, 21 Oct 13:57).** One Uber order held, carrying two on. The planner read whole-screen with "Pickup - 1 order" as the first line and "Stop New Requests" as the last: no title, so planner_ends gave no top and the list was 'list'; the page was `laidOut`, so the lone-dropoff rule made its candidate, "2282 <Name>, Marietta" — and `singleCardOnly` refused it, since the held card read badly (legs 0, hasTotal false, multiOrder false) and the rule wants `card.legs === 1`. The panel said "list cut off: end not guessed" and the order kept the card's corner, no house number. **The rule, which narrows the lone-dropoff rule's `card.legs === 1` for THIS page shape only:** the parser (both ports, `planner_framed` / `plannerFramed`, on the sighting as `framed`) says a read is framed when its first stop header is a Pickup with only the title or furniture above it (no line with two letters in a row — nothing of a stop above) and the foot is on the screen (the bar, or "Waybill" after the last header); it bounds nothing, planner_ends is unchanged. The assembler (`Assemble.framedTrip`, asked by `sighting` of an unprompted lone-dropoff candidate) marks the candidate `framed` only when that page's own stops, and the list it is read as, are exactly one Pickup of "1 order" then one Dropoff of "1 order", none cut by an edge or header-lost, one order held and not an add-on's (`addOn`, `of`). `dropoff()` then takes `card.legs` 0 as well as 1 — 0 is the card's legs unread, the page itself the witness of one pickup and one dropoff — and still wants `multiOrder === false` and the legs a number (a card that never said its legs is refused), and files it as the planner (`from: 'planner'`), clearing the planner line's 'list'. Never with two held (sightingMany offers no lone dropoff), never off a press, and never over an end the driver pressed for (outranks). A framed read is deduped apart from an unframed one, so a read refused before does not hide it. Every other lone-dropoff guard applies. Measured over the shared corpus's 556 texts: `planner_framed` is true on 28, and none newly files — every framed page of one pickup and one dropoff with its door read is already bounded. **Then the street-index rescue** (Done, "The maps, again") finds the door: "2282 <Name>" for "2282 <Name>s Dr" is the word cut by its last letter with the type lost, `cutFits`' existing rule, and the door is asked by the street's own name; no rule changed. Checks: shared planner cases 79 → 90 (with an optional `framed` the two runners compare where a case states it: the fault, words above the header, no foot, a Dropoff first), test_parser 1458 → 1484, corpus.test.js 1378 → 1404, assemble.test.js 445 → 463 ('[framed]': the fault filed off a card of legs 0, the old refusal unframed, legs 1 and 2, two orders, multiOrder unsaid, legs unsaid, no card, `addOn`, `of`, a press, a pressed end kept, a refused unframed read not hiding the framed one, two held, framedTrip's shape one part at a time), test_scan_pi 568 → 569 (`framed` on the sighting), test_server 1043 → 1049 ('[framed]' end to end through the real server, a relay scanner and tests/fake-nucbox.js: the card's corner held, the unframed read refused as 'list', the framed read filed, the door pinned by the rescue as "2282 Corbins Drive" with the questions in order, the store's street without its suite; the fake's index gains an invented Corbins Drive). Mutation testing skipped (fast lane). Open: a framed page that is two pages stitched is asked of the newest page's own stops and the stitched list both, and no stitched case of it is on file.

**The trip's last stop on the Trip Planner, its Dropoff header cropped off, is filed as the order's end (the owner, 21 Oct 15:00).** One Uber order held ($17.62), its end the card's corner "<A> Flat Ct & <B> Rd, Marietta", no house number. A card-box read of the planner showed "Address / 3259 <Name> Oaks Dr / Marietta, GA / View details / Waybill / ... / Stop New Requests" with the Dropoff header above the crop, and filed nothing: a card-box read is no page to the assembler, and a headless stop has no kind. **The rule (the owner's): on Uber's Trip Planner the trip ends on a dropoff,** so the last stop block on the list is one whatever header it had. Both parser ports (`planner_foot` / `plannerFoot`, on the sighting as `footed`) say the shape: no stop header on the read, and its last "View details" straight under "Address", "<n> <street>" (PLANNER_HOUSE) and "<Town>, ST", with "Waybill" or the "Stop New Requests" bar straight under it. find_planner now keeps that block as the headless stop when the bar alone is the foot (it took only "Waybill" before); planner_ends is unchanged, so the bar bounds nothing. The assembler (`Assemble.footDropoff`, card box or whole, a whole read only where nothing else gave the page an end) files it at rank `label` only with exactly ONE order held and not an add-on's (`addOn`, `of`; sightingMany never asks), unpressed, read at or after the Took, its one stop that headless block with street and town read, and not one of the held order's pickups by any word on record (heldPickup). A press keeps its answer (outranks), and the block is said once per hold. Because `label` outranks `planner`, the same door read later under its header (stitched or whole, the same street) replaces it at rank planner with its customer and time ('same door'), so a stitch is never worse off for the foot having come first. Measured over the shared corpus's 627 texts: `planner_foot` is true on 2 (both headless pages written for the stitch), and 1 find_planner answer changes: the case "an address block with no header and no Waybill is not read" (bar only), now the trip's last stop by the owner's decision, renamed. Six stitch sequences (sequences.json) whose headless page stood alone now file it at rank label, their expectations and notes updated; the scrolling-up stitch files the foot first and the planner's reading of the same door over it. Checks: shared planner cases +3 (the fault's read, a line between "View details" and Waybill, a street with no number) with an optional `footed`; test_parser 1484 -> 1495, corpus.test.js 1404 -> 1415, assemble.test.js 463 -> 475 ('[foot]'), test_scan_pi +1 (`footed` on the sighting), test_server +3 ('[waybill last]': unshaped refused, a press refused, the read filed over the corner, end to end). Mutation testing skipped (fast lane).

**...and a pickup's block read as that last stop, caught by the scan-loop suite (22 Oct).** rpi/test_loop.py's "a pickup's address is never the order's destination" read a Trip Planner page whose Pickup header OCR'd as the bare word "Pickup" (no " - 1 order", so PLANNER_STOP did not take it as a header) over the store's name, its address and "View details", then the bar: no stop header on the read, so the rule above made the STORE's door the trip's last dropoff. The suite was not in the fast lane, so it went out on experimental that way. **The fix, both ports:** `planner_foot` / `plannerFoot` and the headless stop find_planner keeps (`_planner_headless` / `plannerHeadless`) refuse a read with a line that starts with the word Pickup or Picking up (PLANNER_PICKUP_WORD, a mark or two before it allowed) — a page that says Pickup anywhere is not a page whose only block is the trip's end. Checks: shared planner cases +2 (the bare "Pickup" over the store with Expected by and the bar; "Picking up -" over the store with Waybill), test_parser 1513 -> 1519, corpus.test.js 1433 -> 1439, test_loop passing again. Mutation testing skipped (fast lane).

**Every Uber add-on card lost its store and its destination (the owner's add-on of 22 Oct, 18:16, "no dropoff").** "+14 min (+ 4.1 mi) total": LEG allowed no plus inside the bracket, so the leg ended at "min", the tail after it began "(+ 4.1 mi) total" and was cut at its distance, and find_places read nothing after it. The distance was LONE_MILES', which is why nothing else showed it. Taken from the offers page 13 s after Drop was pressed on the order in the car (whose pickup screen was still on the phone), the add-on was held alone with no end at all. **The rule, both ports:** LEG takes `\+?` inside the bracket. **Measured** over 31,307 texts (the shared corpus and the 19 and 22 Oct journals) against the commit before: 753 change, every one an add-on card: 691 gain their destination and 666 their store; 38 change their time or distance, all for the better — the map's ETA bubble ("23min") over the card is no longer a second leg added to the card's own (41 minutes for an 18-minute add-on, 24 texts), and "(+ 0 mi)" is 0 miles rather than unknown (rate() gives no $/mi and no running cost; the panel says "--"). Checks: shared parse cases +3 (the add-on's ends, the bubble, +0 mi); test_parser 1582 -> 1603, corpus.test.js 1502 -> 1523, test_scan_pi, test_loop and assemble.test.js unchanged and green. Open: a store printed with no bracketed street ("<Store> #12" over the corner) still runs into the destination.

**A held pickup with no door anywhere on record was never searched, so the run had no restaurant and the guard nothing (the owner's ride of 23 Oct, 19:25: "it routed the Uber ride perfectly, missed the store pickup").** The card named "Momoyama Ramen & Hawaiian BBQ" with no street, the Trip Planner's last block gave the end (footDropoff) and no pickup block was read. The 18 Oct rule for the server's pickup pins said "never the store's name": a pickup pin withholds the GPS drop from any door within 150 m of it, and an agreeing answer for a NAME can be a branch the order is not from. **Changed, at the owner's request:** with NO door on record (no planner pickup, no filed pickupAddr, no `pickupLine`, no bracketed door), pickupAsks adds the card's pickup as a store's name (`pickupNamePlan`: searchPlan's 'name', never a corner or a street), and searchHeldPickupName asks it ONCE (q=, storeName's form) inside the held card's disc, choosing by the end's own rule for a place (MV.pickPlace: named features of that name only, one inside the disc or every one the same place). A chain's branches are refused ('several answers', or 'too many answers' past the ten asked for), a name the NucBox does not hold 'no door, place not found', and a door when one is on record is still the only thing asked. The pin is `from: 'card'`, `by: 'server'`, kept as any (keepPickupPin). Checks: test_server '[held pickups]' +2 (one Example Grill by its name, pinned from the card inside the disc; a chain's branches refused) and '[server pickups]' "no pickup address with a house number" now asks the name once and pins nothing; test_server 1109 -> 1111. The fake NucBox answers "Example Grill" by name. Open: a store sharing its name with an unrelated place inside the disc (a 21-mile card's disc is wide) is pinned if it is the only named feature there.

**A door search asked with the reader's misread of its type word (the owner's 22 Oct Early look card, "790 <Name> Bivd NW", its pickup "not inside the card's reach").** That reason covers nothing answered at all, and the address search holds no "Bivd". Map view's streetPlan, which the panel's searches and the server's door searches share, now puts back the type word's misreads before asking (`typeSlip`): Bivd/B1vd for Blvd, Tri for Trl, PI for Pl, Or for Dr — none of them a street type — only in the type's place (last, or last before a quadrant) and after a name of two letters or more, so "5 Or Rd" and "12 Tri Oak Ct" are untouched. Checks: tests/mapview.test.js 636 -> 638. Open: the card was an Early look (its distance is store to customer, no yardstick), read as "arty look - Order in progress", which EARLY_LOOK still takes by its second half.

**The 22 Oct shift's Trip Planner reads, replayed: three more kinds of the phone's edge noise, and the bar read by its icons (the owner, 23 Oct: "go ahead with the planner fixes from tonight's data").** The shift (7 orders, 2 of 7 ends pinned): five ends had no house number; the journal's automatic planner reads (`planner` rows, `asked: false`) and the snaps show the rig DID read the planner by itself, and its reads were refused on noise. 18:08, one Uber order held: the card box's read had the Dropoff block whole and the bar's words as "pe J bs a ci a ead ; i", so no foot; the whole read had "x Pickup +1 order x" (no header to PLANNER_STOP, so the pickup vanished) and "* <n> <Name> Dr NW" / "e" / "~ Kennesaw, GA ;" (the town two lines under the street, so lost). 21:03: "ropoff - 1 order", its D lost. **The rules, both ports:** (1) PLANNER_STOP takes the edge word (PLANNER_EDGE_WORD, now defined with it) in front of a header, but only before the one-word "Pickup"/"Dropoff" the planner writes: Uber's pickup screen's button "Wa Pick up 1 order" (twice on the 22 Oct journal) is no stop; (2) "Dropoff" may lose its D ("ropoff"), never "Pickup" its P (the kind is told by the first letter); planner_foot now refuses a last header that is a Pickup rather than wanting a D; (3) _planner_address_lines takes the town off the THIRD line under the label when the second holds no word and the first opens with a house number, and planner_foot's shape allows the same line; (4) the bar by its icons (PLANNER_ICON_Q over PLANNER_ICON_O: "o= Q" over "—o", "5 Q" over "—o", "S Q" over "=o"): on 7 of the 19 and 22 Oct journals' 30,771 texts, every one a Trip Planner, 4 with the bar's words unread; it ends planner_foot's run of icon lines as the words do, the two icon lines counted inside PLANNER_FOOT_ICONS. **Measured** over 31,302 texts (the shared corpus, sequences, and both journals) against the commit before: find_planner moves on 3 (the 18:08 whole read gains its pickup with its door and its dropoff's town; "ropoff" found; "by Dropoff + 1 order" reveals a batch's second dropoff, which now keeps that page from filing one door); planner_ends and planner_framed on none; planner_foot on 6 (both 18:08 reads, now filed as the trip's last stop with "<n> <Name> Dr NW, Kennesaw"; four of the 19 Oct journal's pages over the bar's icons); planner_laid_out on 1 (the 18:08 whole read). **Automatic association:** no code needed — the rig already reads the phone by itself while an order is held, every 10 s (30 s under the heat guard); the frames of the three holds with no planner read show Uber's driving screens (Trip Radar, navigation, an early-look card), where no door with a house number is printed, and the rig never presses the phone (Settled). Checks: shared planner cases +5 (the 18:08 card box by the icons, the 18:08 whole read, "ropoff", the button refused, a name under the search glass) and the assembler's barless page now takes the icons off too, with a check that the icons alone file the last block; test_parser 1569 -> 1582, corpus.test.js 1489 -> 1502, assemble.test.js 484 -> 486. Mutations (by hand, JS port): 9 run, 9 killed (the icon shape after a new case). Open: the 21:11 read of an add-on trip ("1 stop left · Deliver all by …") lost its Dropoff header entirely and cut its label to "Addre"; the 21:03 pickup's door "<n> George Busbee Pkwy . Kennesaw" over "GA 30144" (the comma read as a full stop, the state on the next line) is not read; the title's line read with noise under it ("i = = een 9") still unframes the list, which is right while a stop's tail looks the same.

**A DoorDash card whose store's door ran off the card before its town kept only the store's name, and got no pin (the owner's add-on offer of 22 Oct, 21:14, an Uber order in the car).** "$5.30 incl. tips / 2 stops (2.6 mi) · 20 min / Chick-fil-A / 830 <Name> Parkway North… / Customer dropoff": STORE_DOOR (17 Oct) wants "street, Town", the ellipsis took the comma, the rig asked the NucBox for the chain's name in the card's disc, "too many to be sure", no pickup pin, so no route and no figure for the offer. The town is never sent (map-view.js searchPlan cuts at the comma), so the street is the search. **The rule, both parser ports** (`store_door_cut` / `storeDoorCut`, store_door's fallback): no comma; a house number (an icon in front read as marks, or as one character before the number, dropped); a name with two letters in a row; a street type; after the type at most one word — a whole NW/NE/SW/SE kept, anything else (the edge's "North" of "Northwest") dropped, since a quadrant half read is another road's; an edge mark may end the line. Written as the street alone, which Map view asks as a door inside the card's disc (bareDoor). **Measured** over 26,570 texts (the shared corpus and the 19 Oct journal): 204 gain a `pickupLine`, every one a store's street under its name (Ernest W Barrett Parkway, Cobb Place Boulevard, South Marietta Parkway and the like); no other field of any parse moves. The shared door case "no town at all" ("12 Ab Rd" → none) is now the street, renamed. Checks: shared parse cases +4 (the cut door, a whole NW kept, a type cut refused, two words after the type refused) and door cases +1 (the icon read as a digit); test_parser 1544 -> 1569, corpus.test.js 1464 -> 1489, test_scan_pi 575 green. Open: the customer's street DoorDash's map labels on the same card ("<n> <Name> Ln NW") is not read, so the offer's dropoff is still unknown; and a door with its comma and a town the edge cut ("…Road Northwest, Sm…") still refuses, as before.

**Nothing on the panel said whether the NucBox was answering (the owner, 22 Oct, after a held order's map drew nothing: "the NucBox health on the panel").** The street index is the NucBox's own server.js on 8081, which a reboot does not restart, and a NucBox down looked exactly like an address it could not find. **Server:** each service set (NUCBOX_SEARCH, NUCBOX_ROUTER, NUCBOX_STREETS) has a state, `nbxHealth`: up, why and since. Every real question says it (nbxAskOnce → nbxNote): an answer is up, and TWO failures in a row are down, since one slow search past the timeout is the question's trouble. A probe every NBX_PROBE_MS (60 s, chosen; NUCBOX_PROBE_MS moves it, 0 stops it) asks paths that cost the services nothing and answer JSON whenever they run: Nominatim's /status, the street index's /api/streets (up with `loaded: false` is down: "no street index is loaded there"), and the router's /health, whose JSON refusal is OSRM answering. A probe's failure is down at once. /api/status carries `nucbox` (each service, null when not set) and the beat `nucboxDown` (the services down, by name), nothing about any address. **Panel:** live.html's health row, beside the GPS note and after the Pi chip, says "NucBox: streets down" (search, routes, streets by name, all three as "NucBox: down"), and nothing while each answers, the GPS note's own rule. **Suites:** tests/fake-nucbox.js answers the three probe paths as the real services do and never records them (FAKE_STREETS_UNLOADED=1 gives an index not loaded); test_server and test_dashboard start their servers with the probe off, and only the health checks turn it on. Checks: test_server '[nucbox health]' +7 (all up and none on the beat, the probes uncounted, the street index's port dead: down with why and named on the beat, an index not loaded, one failed search not down and two down, a service not set null), test_dashboard +8 (the note, all three beside the widest Pi chip and a sixteen-hour GPS on the glass, gone again; both panels). Mutations (by hand): the beat's list, two-in-a-row, the unloaded index and the real questions' report, each killed by name. Open: the note says the NucBox is down, not why (the "…" sheet and /api/status carry the why); a NucBox that answers its probe and fails every real question is said only after two of them.

**Every pin of the 9 Nov evening was refused "NucBox down" with the NucBox up all night, asked once more and then never, and the panel's word for it went unseen (the owner's shift on 931c50c).** The rig's log has `pin: none pickup … "NucBox down"` and `pin: none end … "NucBox down"` for every order from 19:12 to 00:27 EST; the NucBox had seventeen days of uptime and its streets relay active since 7 Nov. The car's hotspot had run out of data: Wi-Fi with no internet behind it, so Tailscale could not reach home. The probes did mark every service down, but the only word on the panel was healthNote's grey "NucBox: down" in the status row's small type, and endAsk / pickupAsk asked each search once more after END_RETRY_MS (30 s) and left it. **Server:** each service's run of failures is dated (`failSince`, kept apart from `since`: one failed question is the first second of an outage though not yet "down"), and its kind read off nbxAskOnce's own sentence (nbxWhyKind: timed out after 3 s / name lookup failed for ENOTFOUND and EAI_AGAIN / refused / network unreachable for ENETUNREACH and EHOSTUNREACH / what the NucBox answered). Every set service failing for NUCBOX_OFF_MS (60 s, chosen: the second probe) is `nucboxOff` {since, services, why, kind, rigOffline} on /api/status and the beat, `since` the last of the services' first failures, so a street index dead since the afternoon does not date an evening's outage; one line in the log on each change, `nucbox: unreachable (search, route, streets) — timed out after 3 s, failing since 7:12:04 PM` and `nucbox: back after 4 h 12 min; asking again for 3 pins`. A search refused 'NucBox down' is asked again after END_RETRY_MS × 1, 2, 4, then 10 (30 s, 1 min, 2 min, every 5 min) for as long as its order is held (nbxRetryDelay; the pickups' timers kept by text and cleared with the order); a rescue question past a search's own answer (endAsk's `unanswered`, the 26 Oct street index) is still asked once more and left. A service heard again (nbxNote's down → up) or the outage ending runs nbxRecover after a 1 s settle: every held end, pickup and store still refused 'NucBox down' and not pinned, each through the warming budget (earlyRoom, six new searches a minute, the rest queued and looked at every 10 s, re-checked at their turn), and the card on the slot (screeningCard) with its "not answered" early outcomes, its offerPin sides marked `Down` and its on-time hints marked `down` (roadLegs' second argument) let go and searchCardEarly run again. Found pins say `pin: found … by server after N asks` as any later find does. Nothing is decided differently: a pin found is kept by pinHeldEnd / keepPickupPin, first valid one winning. **Panel:** while `nucboxOff` stands, the status row's note starts with a chip in the pass colour, "NO NUCBOX", and its words at full strength, "since 7:12 PM · pins and maps paused"; the grey "NucBox: down" goes, and the shift line stands down to no width, its gap handed back (on "…" in full as ever) — `display: none` there made the 3.5" hat's row a pixel shorter, its "✓" being what set the height; the gap was the phone's last 3px; and the note's million-to-one shrink resistance had to be one again or it ran 643px off the hat. Its title says "No connection to the NucBox since 7:12 PM — pins and maps paused (timed out after 3 s). Usually the rig has no internet: check the hotspot's data, or switch to the phone's hotspot.", and "…" the same in one line without the time (two lines put the sheet's top 34px off the hat in the scene picture) (a refused connection: the services stopped at home; ENETUNREACH on every service: "The rig has no network at all"). Whole at the rig's 1024x600, the 800x480, a phone upright and the 3.5" hat, in both pictures (440px at 18px type, 369 at 15, 298 of the phone's 370px row at 12). When it clears, the card's own way line is walked again where it said NUCBOX DOWN; Map view is not re-walked without a press, because a place still unanswered would go to the public map, and the planner's fastest order already asks the router again at the next walk. **Suites:** tests/fake-nucbox.js's GET /__unreachable?on=1 takes every request and never answers (questions still listed), as a Tailscale peer behind a dead hotspot does. Checks: test_server '[nucbox off]' +22 (not off inside the minute, off after it with services, why, kind and the first failure's time, on the beat, the log line; the end's asks 0.9, 1.4, 2.4 s apart and nothing before the ×10; each "NucBox down" said once; back: end and pickup pinned by the server within a probe and the settle, the back line with "2 pins and the offer on the slot", each found line with its asks, the card read while down searched again, off cleared; refused and name lookup failed told apart; the re-asks waiting for a spent budget window and pinned after it), and the two old "asked exactly once more" checks now hold the backoff's count; test_dashboard +18 (the chip, words, colours, title, beside the Pi chip and GPS, refused and no-network hints, gone again; 800x480 and the 3.5" hat), test_layout +72 (four panels, both pictures: whole, the shift line standing down, the sentence on the title and its line on "…" on the glass, first beside the Pi chip, the row, bar and picture unmoved). Open: whether the rig itself is offline is said only for ENETUNREACH; the 9 Nov case (a timeout through a Tailscale route that exists) cannot be told from a NucBox switched off at home without asking a public host, which this rig does not do by itself, so the hint says "usually". Retry steps and the 60 s are chosen, not measured.

**The offers page could not rank the log by pay per mile (the owner, 22 Oct: "sort by the raw $/mile so I can get an idea of what is a good rate").** journal.html's order chips gain "Best $/mi": the card's payout over the card's miles, nothing taken off (`payPerMile`; null without both figures or under 0.1 mi, which sinks such a row as every ranking does), set-aside rows below the counted ones as for the other rankings; under it each row's line says its figure ("· $5.00/mi"), and under no other. A way to READ the log, not a rule: Settled stands — no $/mile acceptance rule or floor (the replay measured one 24% below $/hr), and the verdict, the state, the panel and every figure above the list are unchanged. Checks: rpi/test_offerspage.py 553 -> 556 (r7 at 2 mi leads where r4 leads pay; the figure to the cent; none under Highest pay).

**What $/mi has been worth taking was nowhere on the offers page, only where a card's $/mi sat in the log (the owner, 24 Oct: "What kind of analysis can be built into the offers page to help me decide what $/mi I should accept? The $/time can have error in it ... but $/mi is always correct", then "go ahead with all four").** `/api/journal` gains four aggregate fields, worked out in server.js over every offer in the window (before the `limit` cap; `taken` now reads the same uncapped window, so an order whose card fell under the cap is no longer missing from it), and journal.html draws each under "Restaurant waits": (1) `perMileSeen` — p25/p50/p75/p90 of raw $/mi (pay over the card's miles, `payPerMile`'s figure) of the counted offers seen, by app and trip length (under 4, 4-8, 8-12, 12+ mi) and by app and three-hour block (Advice.blockOf); a cell under PER_MILE_MIN = 8 offers keeps its count, no figures, and greys. (2) `cardVsReal` — per app, over orders put down at the door only (`by` 'gps' or 'screen'; a Drop press or the chooser counted out and said, 'replaced'/'expiry' not counted): the median real/card minutes ratio, its p25-p75 and the median minutes over. An Uber add-on put down at the door is left out and counted (`addons`): its card's minutes are only what it adds to the trip ("+8 min") and its real time is the trip's, so it would read as a run four times its card. An order carried with another stays in and is counted (`together`, off the drop row's `carried`, which `taken` now carries as `carried`, 1 for one order): its clock is its own, and the page says how many may be stretched by the other. Real MILES are not on this route: the per-order GPS miles come from the end-of-shift report off the GPS logs, one day per run (the Shift page shows them), and nothing the journal route reads has them, so `miles` is null and the page says so rather than inventing a figure. (3) `realByPerMile` — the same door-measured orders (add-ons out), gross pay over the real hours, by the card's $/mi band (under $1, $1-1.50, $1.50-2, $2+), n and median. (4) `refigured` — for an app with REFIGURED_MIN_RUNS = 5 or more door-measured orders, each counted offer's $/hr again with its card minutes scaled by that app's median real/card ratio (billed + minutes x (ratio - 1): the pad and shopping allowance left as they were), and how many cross the row's own target each way ("4 of 38 DoorDash offers would flip at 0.90x: 0 from accept to pass, 4 pass to accept"); an app short of orders says how many it has. **Descriptive only, and why:** Settled stands — no $/mile acceptance rule or payout floor, no re-timing at a pace, no minutes from distance, no heat map, no silence as an accept, no seventh control, the rig never presses the phone. Item 4 multiplies the card's OWN minutes by a clock measurement per app (Took to put-down, against the card); it never works minutes out of miles or a speed, so it is not the pace re-timing refused above, and it is a count printed on the offers page that feeds no verdict, state, target, advice or panel line (test_server checks every offer's own rate and state come back as written). Aggregates only: counts, ratios and dollars, no id, place or coordinate. Checks: rpi/test_server.py +18 '[per mile]'/'[card vs real]'/'[real by $/mi]'/'[refigured]' (invented journal of one evening: the percentiles to the cent, a thin cell, the door-only rule, an add-on put down by the GPS an hour after its Took left out without moving a figure, one carried with another counted, both flip directions, an app under the minimum, an empty journal, no ids in the fields); rpi/test_offerspage.py +15 (each table drawn, greyed, the minimums and "not a rule" said, the add-ons and carried-together said, the counts sentence, and nothing drawn on a feed without the fields); rpi/test_layout.py +4 a panel ('[per mile]': the four tables drawn off six GPS drops in its fixture, no cell off the glass, no sideways scroll). Open: the 8- and 5-order minimums are chosen, not measured; real miles per order would need the GPS log read per window on this route; an order carried with another is kept in the ratio, and how much the other stretched it is not separated.

**A ticked row with a tag scrolled the offers page 1px sideways on a 360px phone from 10:00 to 12:59 (found 27 Oct: rpi/test_offerspage.py's '[offers tick] ...beside the ✓ at 360x640' and '[in car list] ...fitting at 360x640' failed with `side: 1` at HEAD and at 235e3ec, which had passed the gate, most likely on a host off UTC).** Not the date and not a font: the TIMEZONE. The suite's NOW is fixed (1700000000000, 22:13 UTC) and the page prints each row's clock in the browser's zone, which is the host's. In UTC the 'in the car' feed's r0 and r1 read "10:13 PM" and "10:03 PM"; anywhere in the US they read a one-digit hour, and the same suite passes 574/574 under TZ=America/New_York. On those two rows (ticked, "stacked on") at 360px `.meta` had already shrunk to 0 and every other part is `flex: none`: dot 10 + `.big` 84 + ✓ 52 + tag 77.8 + clock 53.1 + five 10px gaps + `.when`'s own 6px pad ended the clock at 336.9px, and the chevron after it is turned 90° (`transform` counts toward the scrollable overflow; its box stands 5.6px past itself each side once turned), which ended it at 360.3: a 1px sideways scroll, on the owner's phone in the evening. A one-digit hour is 4.6px narrower and fitted. **Fixed in the CSS:** `.offer .when` loses `padding-left: 6px`, which only ever added to the row's 10px gap before the clock (`margin-left: auto` does the pushing), so the widest clock (tabular figures make every two-digit hour one width) ends 6px sooner and the chevron at 354.3. **And the check's environment:** the 'in the car' feed's browser context is now `timezoneId: 'UTC'`, so its 360px fit checks see the widest clock on every host rather than only on a UTC one; the other feeds stay in the host's zone, as the fixtures were written to survive (noon rows). Checks: no check changed, the two now pass in UTC and in New York.

**A single trip's planner on the glass, read whole and by the card box, and nothing filed: the order kept the card's corner and the map drew nothing (the owner's snaps of 22 Oct, 18:12).** One Uber order held ($14.21), its card read badly (legs 0, multiOrder false, hasTotal false), its end the card's corner "<A> Tri & <B> Rd NW" (no house number), its pickup the store's name and town only. The phone showed the whole Trip Planner: the title, "Pickup · 1 order" with the store's door, "Dropoff · 1 order" with the customer's, and the bar; no "Waybill". Six unprompted reads in 70 s were all refused 'list'. **The whole read** lost both doors to the cloth and bezel round the phone at the lines' edges: the pickup's label read "us Address" (and its link "MU View details"), the dropoff's street "\ <n> <Name> Dr NW > i"; and with the card's legs 0 the lone dropoff wants the page framed, which the 21 Oct rule refused for the words the status bar and the cloth made ABOVE the title. **The card-box read** saw the last stop alone, "Dropoff - 1 order", its block, the bar's icons ("5 Q", "—o") and the bar, and planner_foot wanted no header at all and the bar straight under "View details"; its street read "<Name> Or NW". **The rules, both parser ports:** (1) PLANNER_EDGE_WORD: one or two letters, a mark or two, then a space may stand in front of "Address" and "View details"; (2) PLANNER_EDGE_MARK: a mark no street prints (not a letter, digit, space or . , ' # & / ( ) -) after a space, with no three letters in a row after it, ends the street line; (3) PLANNER_OR_SLIP: "Or" as the street's last word, or last before a quadrant, after a name that is not a type, is "Dr" (streets.js names the slip and refuses it there, since no i/l edit makes it); (4) planner_framed: with the title on the read, only the lines between it and the first header are asked (planner_ends' own test for the top); (5) planner_foot: the read may carry headers, the LAST a Dropoff, no header lost anywhere on it (two "Expected by" under one header), no Pickup word in its block, and between "View details" and the bar up to PLANNER_FOOT_ICONS = 8 lines of at most four characters and no three letters in a row (the bar's icons); "Waybill" still straight under. **The assembler:** footDropoff takes the last stop of the sighting as a whole Dropoff when every other stop on it is a headed Pickup and the list is not short (listShort: a Pickup of 2 orders over one dropoff is a header lost), its customer left off as on a headless page (a name at rank label would stand over the planner's cleaner reading) and its time kept; and a whole read whose lone dropoff rule 1 refuses only because the card's legs went unread (legs 0, multiOrder false) is offered the foot beside it (`loneTaken`, rule 1's test factored out) — a card that SAID two legs or two orders, or no card, still refuses on evidence. Every other footDropoff guard stands: one order held, not an add-on's, unpressed, after the Took, not one of its pickups. Measured over 26,558 texts (the shared corpus and sequences, and the 19 Oct journal's 26,039): find_planner moves on 2, a headless last stop over the bar's icons (the corpus's invented twin and the journal's own), now read as the owner's rule says; planner_ends, planner_framed, planner_titled, planner_laid_out and planner_furniture move on none; planner_foot on 32, all pages that already give the order an end (title and Waybill) or the 21 Oct framed page, where it is the fallback only. The snap's two reads, through both ports: the whole read framed, both doors with street, town and time; the card box's footed, its door "<n> <Name> Dr NW". **The map:** it drew nothing because neither the corner nor the store's bare name was pinned; with a door filed the server's held-end search pins it at house level (TIGER) and Map view draws the route. Whether the NucBox's street index (port 8081, which a reboot does not restart) answered the corner is not on the snap: the owner is asked to check it. Checks: shared planner cases +8 (the 22 Oct whole read and card box, invented; a name, a word, a long line and too many lines between the block and the bar; a Pickup block last; "Or" after a type kept) and `footed: false` on the lost-header case; test_parser 1519 -> 1544, corpus.test.js 1439 -> 1464, assemble.test.js 475 -> 484 ('[foot 22 Oct]': the card box files at rank label with its time, the whole read as a planner end, a Pickup above allowed, another dropoff / a block of no kind / a Pickup of two orders / a cut Dropoff / a name peeking / an add-on / a press / before the Took / two held refused; '[framed]' footed beside the refusal, and the refusal kept without the foot). Mutations (fast, by hand): 16 run on the JS port and the assembler, 16 killed (5 survived the first run and are now pinned by the cases above).

**An order could be put down only by the GPS or by Drop, though the delivery app says itself when a delivery is done (the owner, 22 Oct: "make it more hands-free; managing multiple apps causes friction").** Many doors never arm (no house number), so Drop is pressed at the door. **What is on record**, searched first: the 19 Oct shift's journal (16 Aug to 20 Oct, 18,951 rows, 26,039 distinct texts in offer rows' frames and the 1,701 screen rows; it holds the 12 and 16 Oct files) has ONE completion screen, DoorDash's, 30 Aug 21:48, four reads of one delivery: "This dash so far / Total online time 25 min / Offers accepted 1 out of 7 / This offer v $8.95 / Continue dashing" (one read lost the button), no customer named. No Uber completion screen anywhere: no "Delivery complete", "Trip completed", "You earned", "Rate", "Delivered". Screen rows are only frames read after a card, so that silence is not evidence none was shown. Also on record and all BEFORE the drop: DoorDash's task pane, "Current task / Deliver to <name> / 9 min to complete / Pause orders after delivery / This offer $8.00 / This dash $0.00" (2 reads), Uber's navigation with "Verify - Enter delivery PIN" and the "Complete delivery" slider (1), the dash's "Dash summary" (2, its end), and a Quest's "1/1 trips completed" (1). And a fault on the way: the completion screen went on the journal as an OFFER, $8.95 over "25 min" of online time, WARN, a card a ✓ Took could take. **The rules.** Both parser ports: `delivered_screen` / `deliveredScreen` gives {app, screen, pay, name} or none; screen types `dd.delivered` and `uber.delivered`, asked after the offers and the planner and before DoorDash's other screens. DoorDash: "This dash so far" and "This offer $X" on one screen (not "This offer $X" alone, which the task pane prints). Uber: "Delivery completed" or "Trip completed" on one line, public knowledge only, refused beside DoorDash's own words. Refused for both on anything from before the drop on the same screen (`DELIVERED_NOT`: "Complete delivery", "delivery PIN", "Confirm order", the task pane's words, "Dash summary", swipe and slide), and one line at a time, so "...after delivery" over "Complete delivery" is not "delivery complete". The customer only from "Delivered to <name>". NOT_AN_OFFER gains "this dash so far", so that screen is no card. Measured over the 26,039 texts and the shared corpus: the four reads move (unknown -> dd.delivered, notAnOffer true) and nothing else. **The scanner** sends a `delivered` line (app, screen, pay, name, the frame's time) once while the screen stays up (`DeliveredSaid`, `DELIVERED_GAP_S` 60 s, chosen); the log names the app, never the customer. **The server** (`deliveredArrived`, a new put-down cause; Drop, the GPS drop and /api/delivered untouched) puts down an order of THAT app through `putDown`, the row `by: 'screen'`, on a positive cue only (`screenPick`): the app must match (an unknown app is none), a frame from before an order's Took is not that order's, with two or more of the app the customer the screen names against each order's own (`customersOf`: the customer its end was filed with, its planner stop still on record, a batch's doors) when exactly one matches, else the one order it can be about (the only one, or the only one taken before the frame) unless the screen names another customer than that order's known one. With two and no cue the Drop chooser opens on the panel (the stream's `chooser`, kind 'drop', the one Drop's press opens) and nothing goes unless the driver picks; its answer is Drop's own, `by: 'chooser'`. Nothing with no order of that app held. One put-down per screen: an app's screen again within `SCREEN_DROP_QUIET_MS` (120 s, chosen) does nothing, or the second of two held would be "the only one" for the same screen. Every screen writes a `delivered` row {app, pay, held, would, cue, holdId, acted}, no name. **Behind `"screenDrop": true`** in rpi/config.json's settings (SCREEN_DROP=1/0 for the suites), OFF by default: the DoorDash rule rests on one delivery and the Uber one on no reading at all; with it off the rows say what it would have done, for holding a shift against the driver's own Drops. The panel takes the hold off the message's `holding`, as it takes an expiry; live.html is unchanged and says nothing of the cause. Settled stands: never an accept, no silence read, the rig never presses the phone; no cue is no put-down and the chooser never times out into a guess. Checks: shared corpus +18 (screens 3, delivered 13, the parse case 2), test_parser 1495 -> 1513, corpus.test.js 1415 -> 1433, test_scan_pi 570 -> 575 (said once through main() over a screen read again and again, its frame time, the gap per app, the line), test_server 1052 -> 1065 ('[screen drop]': nothing held, one DoorDash order down by the screen and the panel told, the same screen inside the quiet window with an order taken since, the other app's screen, a frame before the Took, the next screen after the window, two Uber orders by the customer named, no cue opens the Drop chooser and its answer is Drop's, a known customer who is not the one named, off by default). Mutation testing skipped (fast lane). Open: a snap of each app's real completion screen, Uber's above all, before turning it on; DoorDash's prints no customer, so two DoorDash orders always ask; a screen's Drop chooser on the panel replaces a ⌖ chooser open there; two deliveries of one app inside the window, the second is not said.

**A door on a card-box read of the Trip Planner was never filed (the owner's 26 Oct shift, order #7, one Uber order held).** 44 s after the Took the card box read "Dropoff • 1 order" (its D cut), the customer, "Address", the building's name on a line of its own, "<n> <Name> Ave NE, Atlanta, GA" on one line, "View details", the bar's icons and the bar; find_planner read it as the dropoff with its door, and the order kept its card's corner ("no house number") to the Drop. Two refusals stacked: assemble.js's sighting() dropped every card-box read with a stop on it unread ("a card-box read is no page: it saw part of the screen"), and the one rule that does take a card-box read, the trip's last stop over the bar (offer_parser.planner_foot / footDropoff), wanted the street and the town on the two lines straight over "View details", which a place line and a one-line address are not. **Changed:** (1) under a Dropoff header, planner_foot / plannerFoot take the door in any layout the planner grammar reads (`_planner_foot_address`: one to three lines under "Address" that `_planner_address_lines` reads as a street with a house number and a town); the headless block keeps the strict shape. Over the 26 Oct shift's 36,530 texts this changes one (#7's), and over the 19 and 22 Oct journals' 30,771 none. (2) A card-box planner read with a stop on it is decided by the whole page's own rules, ONE page alone: the title or its layout, the list's two ends, the lone dropoff and the card's legs, the lost header, the trip's last stop — never `framed` (the box's top edge is not the list's), never pooled, stitched, pending, refused or a verdict (box reads come every second or two and would push the whole pages a stitch needs out of PAGES_MAX), and with two orders held still nothing (sightingMany takes whole reads only). The rules on whose door it is are unchanged. Replayed: #7's own read files its door at rank `label` (HEAD: nothing, the corner kept). Checks: 4 shared planner cases (corpus and test_parser), tests/assemble.test.js '[box 26 Oct]' +8, rpi/test_scan_pi.py +1 (the box read's sighting is footed, its door on it, and asks a whole read). Open: a box page is not stitched with whole pages, so a list whose only dropoff is read in the box and whose title only on a whole read still files by the foot rule alone; and the panel's planner line still comes from whole reads only (the box read files the door, it does not redraw the stops).

**A planner pickup was kept twice when its "Expected by" moved a minute and neither read had a street (the owner's 28 Oct shift, 20:36).** One restaurant's pickup read due 8:42, then 8:41; samePlannerStop needs times that agree when no door matches, sameDoorStop needs a street, so mergePlanner kept both. `sameNameStop` (asked after samePlannerStop and sameDoorStop have had every pair) now makes them one: same kind, both named and the same name by the noise-tolerant rule, initials that do not differ ("Pat Q." is not "Pat R."), doors that do not differ where both read one, and times within `NAME_SLIP_MINUTES` (5, chosen: a run slips a minute or two between reads; wrapped at midnight). Two names due the same minute stay two. Replayed over the shift's planner reads (ana1028), only the 20:36 merge changed, 3 pickups to 2. tests/assemble.test.js 4.

**"No house number" said two things on the panel and in the shift report (28 Oct).** server.js's END_WHY gave the NucBox's 'nodoor' — the street found, not the door — the same words as a text with no number printed at all; the shift report's pinning lines told them apart only by "(asked: door)". END_WHY.nodoor is now "street found, not that door", Map view's own caption for it (the only server.js change; the no-number refusal keeps "no house number"); live.html's END_WHY_SHORT says "not that door" (narrower than 'too many answers', the layout's widest), and journal.html's in-car list the same instead of the first three words. tools/shift_report.py passes the words through and needed nothing. Checks: test_server 15 expectations of 'no house number' that were the 'nodoor' refusal now say so; test_dashboard 1 added.

**An add-on's corner and the planner's three doors, read in the card box, filed nothing, and Map view's run left the first order out (the owner's snap of 29 Oct, 17:47: "if possible make the parser and routing more flexible it doesnt need to be perfect but close").** Two Uber orders held: ① its planner door refused "several answers" with its area kept (`endArea`), ② an add-on whose card printed a corner, `endWhy` "no house number". The Trip Planner's three dropoffs came as card-box reads, and `sightingMany` took whole reads only, so the door on one side of ②'s corner was never offered; the run went car -> D2 straight. **Filing** (assemble.js): a box read with two held now offers each door read whole as `partial`, for the card's-street cue alone (never pooled, stitched, a verdict, or off a press), so `cardStreet` files the door onto the one order whose card names its street. Elimination is conservative: never onto an order whose own card printed a street the door is not on (`streetCues`, and the list-seen-whole rule via `cardFits`) — before this, ①'s door filed by `cardStreet` handed the first customer's door to ② by elimination. A **town** check (`townClash`, a slip or the state allowed): an unprompted door in another town than an order's card printed is no `cardStreet`, elimination, growth or `filed` vote for it and no `only` (the store and deadline cues, the screen's own word for the order, stand). Not a refusal with ONE order held (`dropoff()` is unchanged): the suite's own fixtures, and border towns, show that would drop real ends, so the 28 Oct stale-label case is guarded only where two or more orders are held. **Drawing** (live.html, map-view.js `heldRunsDrawn`): with two orders and the figure refused, the run is still drawn, each end its pin where trusted, else a corner's street (`cornerSide`), else its general area (Map view's own, or the server's `endArea` for ① and now ② too), faded "≈", by road; an end with no point is left out and said. ②'s places are searched in ①'s disc grown by the add-on's miles (`disc2Of`, as server.js `heldDisc`). A corner met twice inside the disc within AREA_MI keeps its middle as an area (`cornerArea`), never a pin. No figure moves: `found` is untouched, so `mapRefusal`, `detourOrders`, the GPS drop and the guards read what they read before. **Names**: `MV.plannerName` drops the marks and stray one- or two-letter tokens round a customer's name where the read carries a mark ("7 © JesusR. te" -> "JesusR."); display only. Checks changed: assemble "[box 26 Oct] with two orders held a card-box page files nothing" now also asserts the door is offered `partial` and not filed; mapview "a corner refused for meeting twice" now expects the area words on each tip. Open: the run is drawn only when the router is set; without one the two-order straight run still uses pins alone.

**A trip's doors left the map mid-delivery (the owner, 30 Oct: "I noticed after getting 3 correct drop off locations the rig dropped it on the map after some time").** Traced over the 26, 28 and 29 Oct journals and code; the owner's own moment is not identified in the evidence, so these are the causes found, not a replay of it. (1) **An offer card took the Trip Planner off the order.** server.js's offer branch called `forgetPlanner` at every different card on the record; offers come up all through a batch. Replayed (hold1030/wipes.py): 15 of the 21 trips that had a planner lost it mid-trip (26 Oct 8/8, 28 Oct 4/7, 29 Oct 3/6), and no later planner read on the same trip put it back. The filed end (`fields.dropoff`, the END pin) survived; what went was every reader of the stops: /api/status sent `planner: null`, so a panel reload or rig restart (29 Oct 19:00, mid-#5) drew no D1/D2 and no planner pickups; the next planner page merged from nothing, so a page showing one door replaced the live panel's whole list and `MV.heldDrops`, which needs two dropoffs, drew none; `screenPick` lost the customer names; `pickupAsks` lost the planner's pickups. The live page kept its own copy (`heldPlan`) across offers until one of those. (2) **The planner went with the first order** (it lives on holding()), and the page keyed its copy by that order's holdId, so putting the first order down took the trip's doors off the map though the trip went on (28 Oct 20:34 #5 with #7 still held, 29 Oct 17:29 and 19:20). (3) **An order of a batch ran out on its own card's minutes** while its trip-mate was carried (holdEnds; only an add-on outlived its trip). Also checked: an END pin goes when the dropoff text changes (heldEndPin wants `endPin.dropoff === dropoff`, and a re-filed text is searched again) — 28 Oct #5 (city case only) and #7 re-filed and re-pinned; not a loss on record. 29 Oct #7 and #9 ran out beside another order with no planner and no add-on between them, so no batch rule would have kept them; on the GPS #7 stood 20:15-20:21, most likely its door, before it ran out at 20:26 (a Drop not pressed), and #9 is undecided (stops 21:11-21:14 and 21:37-21:50). **Changed:** (a) the offer branch no longer forgets the planner; `plannerTook` (placeTook) forgets it at a ✓ Took that is another trip — not an add-on joined to it and not on its stops by store, end street or customer (`onPlanner`); `setHeld` moves it onto the order now first when the order keeping it leaves and that one is on the same trip (`plannerStays`), else it goes with it; the order the panel is sent says `plannerHeld`, and live.html's `setHeldFrom` re-keys or drops `heldPlan` by it. (b) `holdEnds` is the latest of the order's own clock (`ownEnds`, unchanged), `tripTill` (while trip-mates are held, the latest of their own clocks) and `afterMate` (a trip-mate put down early: that moment plus its own minutes x HOLD_OVERRUN + grace), both set by `setHeld` (`tripClock`), so holding(), the scanner's handoff, the expiry row and the finishing watch's window (read at the press) agree. One trip = an add-on with its trip (tripOf) or both orders on the held planner (`sameTrip`). (c) Each order leaving the car is kept `DROPPED_KEEP_MS` (60 min, chosen) by its customers (`heldNames`) and end, with the orders it was carried with (`with`); an UNPROMPTED door (`asked: false`) naming a dropped order's customer, or on the end street of one still being finished, read while one of those orders is held and claimed by no order in the car by name or street, is filed onto nobody (`doorOfDropped`, in whoseDropoff); a watched order's door goes onto its watch (`door`) and, where the watch has no door, is searched in the order's disc (kept on the watch, `disc`; earlyDoor), a door found making it a 'door' watch. A press is never diverted. 28 Oct #5 itself would NOT have been caught: #6 was dropped with no end and no customer on record, so nothing named the door as #6's. Checks: test_server +18 ('[trip kept]', '[batch clock]', '[dropped door]'); three expectations changed — the mark reply's keys gain `plannerHeld`; "a different offer on the record takes it off" now keeps it; the carry-two planAt reads ([None, 1], [None, None] -> [2, 1], [2, None]) since the cards between them no longer forget, so the reads merge; tests/assemble.test.js +2 ('[customer]', Assemble.sameCustomer). Open: the panel's stop list (`plannerSaid`) still leaves the glass at a new card (forgetDest) while a reload brings it back from the kept planner; a watched order's door is not drawn on the map; a planner trip's orders matched only by store name (a chain's two branches) would be one trip; the extension lets an order the driver forgot to Drop stay on the list until its trip-mates' clocks.

**A held door's slipped quadrant kept over its clean read, and an add-on's corner glued to a town filed nothing (the owner's snap of 30 Oct, 20:21).** Two Uber orders held. ① its door filed off the Trip Planner (rank `label`) as "3344 <Name> Brook Way NUP, <Town>" — the planner's NW read "NUP" — and the NucBox refused it ("not inside the card's reach"); later reads said "... Way NW" and the hold kept the NUP (a label is not replaced by a planner read; typedOver asks only a planner street filed with no type). ② an add-on whose card parsed as "Kennesaw J <E> Way & <S> Plains Rd Marietta" (the line above's town and a stray letter in front of the corner, its own town run on with no comma); the planner's "1433 <E> Way, Marietta" was on the corner's first street, but `cardStreets` gave "kennesaw j <e>" and "<s> plains marietta", so the panel said "2 dropoffs read · whose?". **Parsers** (rpi/offer_parser.py QUADRANT_SLIP / offer-parser.js quadrantSlip): a closed list of the W's slips — "NUP", "NVV", "NIW", "N W", "NW." and the same for S — is the quadrant, only as a street's last word (its end, or before a corner's "&" or the town's comma), after a word; "N W"/"S W" only after a street type; never before a suite's comma. Asked of find_address's street, the planner's street and every card place. MEASURED over 39,302 texts (scratchpad evidence journals and the shared corpus): no text on file carries any of the slips; 2 answers move, both corners' "NW. ," becoming "NW ,"; four Sprouts brackets' "SW., Suite 200" moved until the suite guard was added, and do not. **Map view** (map-view.js unknownTail): a door whose last word after its type is a short word of letters that is neither a type nor a quadrant is asked once more without it by streetRetry (with no answer in the disc) and dirRetry (the street found, not the door), held to the same street by retryFits — one rule for the server's doorChain and Map view. **Filing** (assemble.js): `betterRead` — the same house number and words up to the last, the newer's last a quadrant or type where the kept one's is neither, the same town — replaces the kept read in `outranks` ('better read', any screen rank, never over a press), is a `sameDoor` cue in streetCues (one order's filed end only, off a list seen whole or not), and stops a box tally putting the slipped read back ('most read'). `cardStreets` cuts a corner's part: the words after its last type where the text gave no comma, and in front stray one- and two-letter words and a word that is the card's own town or stands before a lone letter, while a name and a type are left — the planner door's street compared as a word-boundary suffix past a town and stray letters only; the part as read is kept beside it. Replayed on the snap's own texts: base files nothing (the box read "no cue"; the planner seen whole pools two, "whose?"); now ② gets "1433 <E> Way, Marietta" by cardStreet, ① gets "... Way NW" by sameDoor ('better read' over the NUP), nothing pooled. Open: a part whose real name is a word and a letter ("<A> B <C> Rd") also matches "<C> Rd"; the card parse itself still glues the town and letter on (the panel shows it); a headless foot block read in the card box is still offered to nobody. Checks: cases.json 5 (3 planner, 1 address, 1 places); assemble 10; mapview 10; test_server 1.

**An Uber and a DoorDash order in the car at once: the DoorDash customer's town filed as the Uber order's end, and nothing filed by app (the owner's snaps of 31 Oct: "could it be improved to automatically associate the information with the correct order? Even if not, being able to route the drop off points for them is most important").** Two orders held, carrying two on: Uber with its Trip Planner's door filed (label, `cue: only` while it was alone), then DoorDash, no end. Nine seconds after the DoorDash Took a ⌖ press filed "<Town>, GA <zip>" onto the UBER order (`fields.dropoff` from 'press', screen `uber.nav`, journal mark `cue: only`): the press text is not in the snap, but DoorDash's "Deliver to <name> / <Town>, GA <zip>" types `uber.nav` at 4c40cbf (SCREEN_NAV's "deliver to"; DoorDash's delivery screens were all 'unknown' or worse) and reads exactly that line, so the press was given app 'uber', the hard rule left the Uber order alone, `only` chose it, and a press replaces anything. Every Uber planner read after it was "outranked by press" or "no cue", the end stayed a town ("no house number", no pin), and the DoorDash pickup screen ("Pickup for <name> / <Store> - (<branch>) / <n> <Name> Parkway / Northwest, <Town>") typed 'unknown' and was read for nothing. **Typing** (offer_parser.py and offer-parser.js, both SCREENS lists): `dd.deliver` — "Deliver to" with DoorDash's own words ("Current task", "Pause orders", "<n> min to complete", "This offer", "This dash"), its navigation's lone "Dropoff" over "<n> min Start", or a name over a town-and-ZIP line with no navigation bar (Uber's sheet prints "<Town>, GA" without a ZIP under a street) — and `dd.pickup`, a line opening "Pickup for". `dd_pickup_door` (Python) reads the store's door off the latter, its spelled-out type and quadrant wrapped onto the town's line, and scan_pi sends it on its own `pickupSeen` line while an order is held. **Filing by app** (assemble.js): with orders of different apps held, a sighting whose screen names an app that exactly one order has is decided by the ONE-order rules against that order (`sameAppOrders`, `sightingOne`: planner, lone dropoff, batch, foot, navigation), its candidates carrying the app; attribute() gives a read that the app leaves one order `cue: 'app'` (as strong as `only`, under the same guards); the hard rule already kept it off the other app's order. Same-app pairs are untouched. `dd.pickup` is a store's screen for either order (`storeScreen`, `navCandidate`), and `dd.deliver` an order taken's screen for pressBetween/cardCandidate as Uber's navigation is. **A town only** (`hasStreet`, `townOnly`): an end with a street on it is never replaced by a read without one, a press included ("a town only"); an end that is a town only gives way to any screen-proven read with a street ("over a town"). A town only may still fill a blank: the server never searches it for a door nor arms the GPS drop by it. **Pickups**: `pickupSeenArrived` files the DoorDash screen's door as the one DoorDash order's `fields.pickupAddr` (from 'label') and asks the NucBox (`pickupAsks`); two DoorDash orders or none, nothing. **Routing** (live.html, drawing only): the DoorDash card's map label (`dropoffGuess`, 990ad86) now rides onto its hold at ✓ Took and onto the panel's order while it has no end; Map view searches it in that card's disc and draws ② faded "≈" with a dashed leg from ①'s end, and the caption says "DoorDash dropoff not read yet" (with "② drawn ≈ from DoorDash's map" when it has one). Nothing approximate reaches `found`, a figure, a pin or the GPS drop. **Replayed** through HEAD and after (the snaps' reads and journal, the press as the DoorDash text above): HEAD — Uber "<Town>, GA <zip>" (press, uber.nav), DoorDash no end, its pickup the card's name; after — Uber "<n> <Name> Lake Dr NW, <Town2>" (its planner door, every later planner read filed by `app`), DoorDash "<Town>, GA <zip>" (an area, never a door), its pickup the screen's door; with the press still typed `uber.nav` (a frame with the bar), Uber keeps its door ("a town only") and DoorDash gets nothing. Checks changed: assemble's three `only` expectations with two apps held now say `app`; the shared corpus's DoorDash current-task screen and its "Dropoff / … / 12 min Start" navigation now type `dd.deliver` (were 'unknown'). Open: the press text that did it is not in the snap — the cause above is the one shape on record that reproduces the filed line; DoorDash's "Pickup from <store> … Directions" after an accept still typed `dd.placePopup` (the offer popup's shape) and filed nothing (since fixed: the taken order's pickup screen, below); ② by map label is searched in its card's disc, not round its placed pickup, so it is coarser than a card's guess.

**Every store's printed door on DoorDash's stops card, and how the card ends its list (the owner's snaps of 31 Oct: "How could the doordash orders be routed on the map with the given information on the screen? It would be great if the pins for the pickup and drop off could be captured and mapped").** Two-store cards — "$14.10 incl. tips / 3 stops (8.7 mi) · 33 min / <Store A> / 4410 <Name> Road Northwest, ... / <Store B> / 2516 <Name> Street, <Town>, 301... / Customer dropoff / Drop off 2 orders", and "$21.35 … / 4 stops (15.0 mi) · 53 min / <Store> / <n> <Name> Highway, <Town>, <ZIP> GA / <Store> / <n> … / Multiple dropoffs (2 stops)". Both parsers gave places [A, B], pickup A, stops, and `pickupLine` for A alone — and on the first card not even that: "…Northwest, ..." has its comma, so store_door_cut refused it, and nothing after the comma for STORE_DOOR's town. **Parsers** (rpi/offer_parser.py, offer-parser.js): `placeDoors`, beside `places` and the same length on a stops card (find_stores' own `doors`, so `placeDoors[places.index(pickup)]` is `pickupLine`), null where the line under a store is no door, [] on every other card; `store_door_town_cut` / `storeDoorTownCut` reads a door whose town the card's edge took just after the comma — the street before it whole, so a compass word after its type is kept ("Road Northwest"), after the comma only the edge's mark or one capitalised word it took ("Sm..."); `dropoffs` / `dropoffOrders` (dropoff_shape / dropoffShape) — 1 and N for "Customer dropoff" over "Drop off N orders", N and null for "Multiple dropoffs (N stops)", null when the count did not read, and nothing off a card with no stops line (Uber's "Customer dropoff" is endRefused's, not a shape). The icon in front of a store ("&", "ff", "@") was already cut by _store_name. **Accumulator**: every store's door kept by the merged index, the fullest reading standing, as `pickupLine`; the shape voted as `stops`. **Behaviour change**: "123 <Name> Road Northwest, Sm..." was no door (a cases.json `doors` case and a `parse` case said null) and is now "123 <Name> Road Northwest" — still never a town. Checks: cases.json — a `placeDoors` section of 6 run by each port's own sameList (a list in `parse` is one runner's === against the other's ==, which test_lint refuses), `doors` 5 new and 1 changed from null, `parse` 6 new and 1 changed from null; test_accumulate 4.

**No payout off DoorDash's stops card read through a box drawn round an Uber card (the owner's snaps of 31 Oct).** The card is a full-width sheet under a map that fills the top half of the screen, its payout at 0.45 of the screen; the card box ([0, 0.44, 1, 0.54] on that rig) was drawn round an Uber card. The reads came back with "$21.35" flush on the crop's top (money_is_clipped, parse(''), "pay at the box edge — not trusted") or starting at "3 stops (8.7 mi) - 33 min" (journey, no payout, "no pay read — box may cut it off"). The taller-card rescue never fired: on the rig's frames the finder said "not sure: the band near the bottom is not set in a card", on the rendered card "not solid" (the full-width Accept pill, two reds with its countdown); and the clipped read has no journey to ask it with. **Reader** (rpi/pipeline.py `raise_journey`, `RAISE_STEPS`, Scanner._look): a read through a drawn card box that names DoorDash's stops line (OP.STORES_LINE) with no payout and its journey read — the box's, or a clipped read's clipped text's, for its journey alone — is read again through the box raised 0.09 of the screen, then 0.18, its bottom kept, and kept under every rule a found card is (its own money_is_clipped, rescue_refused against the box's journey, one dollar figure, printed as a card prints one) and a stops line in its own text; never after the finder was sure and refused, never with cardFinder off; said cropFrom 'found' with `rescuedBy: 'raised'`. Uber cards and DoorDash's older card have no stops line and are untouched (every existing taller-card check unchanged). **Measured** on `testcards.dd_stores_screen` (one customer, two customers, dark; clean, glare, blur, shadow, sheen; three widths; flush and just-under boxes; 90 frames, x86): box alone 0 payouts; now 78 with the card's own figures (66 raised, 12 by the finder), 12 none (a shadowed light card whose stops line did not read), none wrong; a card stacked above with a bigger payout never reaches the panel. Cost: 123ms median (32–276) on a 141ms box read, only on such reads, every beat while such a card is up; on the Pi an estimate, ~1.2s. Open: the Pi cost is not measured; the finder itself still does not know DoorDash's layout (it is sure of the card only under a band of glare). Checks: test_pipeline 14.

**A DoorDash order with two stores: both pickups pinned from their printed doors, and the run car -> store 1 -> store 2 -> the end (the owner's snaps of 31 Oct: "It would be great if the pins for the pickup and drop off could be captured and mapped").** Before: the offer line carried the first store's door alone (`pickupLine`); Map view pinned it and ran car -> P -> the map label, past the second store; the order taken off it kept `pickupLine` and its map label (`dropoffGuess`, 6ae05c4), the server pinned one store (pickupAsks), and a DoorDash order has no Trip Planner, so the held run had no pickups at all once it had an end, and with one order held and no end its map label was never drawn (only as ②). **Offer line** (scan_pi `stores_of`): `stores`, every store in the card's order with its printed door ([] off any card but a stops card), and `dropoffs`, `dropoffOrders`; `says_many_dropoffs` is also true off a count of two or more. **Server**: `storesOf` keeps a DoorDash card's list of two or more onto its hold at ✓ Took with the shape (`stores`, `dropoffs`, `dropoffOrders`; absent on every other hold, key for key); pickupAsks asks every store's door as `pickupLine` is — door level, in the held card's disc — so each store gets its pin, the GPS drop's guard holds both restaurants and visitPickups marks each; heldEndState gives `stores` back in the card's order with each one's pin and visit (`heldStoresOf`), on the status, the beat and the panel's order; heldForPanel the shape. **Map view** (map-view.js `cardStores`, `heldStores`, `storesSkipped`, `guessShare`; live.html): the offer's other stores searched by their doors in the card's disc (NbxSearch.place: a door found is P2, an area "≈"), the trip run car -> P -> P2 -> its end, the map label searched round the LAST store; the held order's run car -> each store not behind the car (the server's pins) -> its end, or with no end yet its map label searched round its last store (MV.guessDisc), drawn faded "≈", never D; a store with no pin skipped and said ("route skips 1 store, not pinned"); a card for two customers with one label says "≈ 1 of 2 dropoffs from DoorDash's map; the other not known yet". Drawing only: no store or label is in `names`, `found`, a figure, a post or the GPS drop; the detour's stops are the planner's as before. A one-store DoorDash card and every Uber card draw exactly as they did. Open: the panel's caption for a held order with no end still says what it said; a map label on a two-customer card is searched as if it were the last stop (the run cannot know which customer it names); the server does not search an offer's other stores before the Took (Map view does) (it does since, at the card's read: below). Checks: test_server 7, test_scan_pi 4, mapview 6.
**Twelve dropoffs held for a trip of three: every read slipped a customer's door AND name at once (the owner's snap of 31 Oct, 21:46: "the addresses do not need to be linked to the order, it just needs to be mapped").** An Uber batch and its add-on held, the planner scrolled. The phone listed two pickups (one "2 orders") and three dropoffs; the hold's `planner.stops` had two pickups and TWELVE dropoffs, the panel "12 dropoffs: end not guessed". Each slipped read had become a stop: the house number with its first digits lost at the screen's left edge (two and three digits of a four-digit number), or one digit misread at the same length; "Bivd" for "Blvd"; the name mangled past `wordsAlike` (one customer read five ways, the screen's litter already gone — the mangling was inside the name's own word); the "Expected by" a minute or two apart. `samePlannerStop` wants the times equal, `sameDoorStop` the street key equal number and all (and its `namesClash` refused the mangled names), `sameNameStop` and `slotJoins` the names alike — with door and name off together, no rule could say "the same stop". **The rule (assemble.js `slipStop`, mergePlanner's last matching pass):** same kind; both read a door and its street after the number is the same with its type words made one (`SLIP_TYPES`: "Bivd"/"Boulevard" are "blvd", and the other long forms their short ones); the numbers equal, or one ENDS the other with two digits at least (`housesSlip` 'lost'), or as long, three digits and more, one digit apart ('one'); the times within `NAME_SLIP_MINUTES` (5) or either missing; and the names not two people (`namesSlip`): either unnamed, or initials that both read must agree ("Pat Q."/"Pat R." are two — asked before `sameName`, which reads them as one), then `sameName`, or two of their words within an edit per three letters of the longer (`NAME_SLIP_RATIO` 0.34, `editsApart` = Levenshtein), or a three-letter word two edits off a four-letter one ("jez." for "TezL"). A 'one' slip — the only one that can make two neighbours' doors one — is taken only where both reads printed a name. **The door kept** is the best supported (`doorWinner`): a number that ends in the other's is the fuller read and stands whatever the counts (numberFuller's rule, 12 Oct); otherwise the reading read more often, counted on the stop's `doorReads` ({house: reads}, written from the first merge of two numbers on, counted at every merge into that stop after; the reads before it count once); a tie to the fuller address block, then the kept door. Not even a ⌖ press puts back a number with its first digits lost; a press reading a digit differently still wins (press precedence). **The list against itself (`collapsePlanner`)**, before the top and foot trims: two entries `slipStop` calls one are merged where the earlier stands, so a hold already polluted heals at its next read, and a kept twin of a stop the read shows counts toward its door rather than going with a trim. Never two entries of the read in hand: what one read lists twice the app listed twice (test_server's carry-two planner lists one street twice and must place neither end on it). Only `slipStop` is asked there: `sameDoorStop` takes one door "whatever the times say", and two pickups at one store each due its own minute are two stops of one list. Everything that reads the planner reads `holding.planner.stops`, which mergePlanner writes (the panel's `heldPlan`, MV.heldDrops, server.js planAtOf / plannerVisits / ordersForPanel), so nothing else changed. Replayed in invented names and doors of the snap's shapes: the six reads were held as two pickups and ELEVEN dropoffs before (the pickups in the middle of them), two and three after, at the four-digit doors and the twice-read "915". **Kept two:** "Pat Q." and "Jules K." at one door due the same minute (merged, or already side by side); a digit apart with a name lost, or with two names; past five minutes; a one-digit "number"; two initials; another street; another kind. Settled stands: which stop is the order's end, the GPS drop, finishes and every figure are untouched (the end rules read the read's own stops, not the hold's). Checks: assemble.test.js 557 → 568 ('[slip]': the snap's sequence, its doors, its order, its counts, the polluted hold healed, the leaves one at a time, the press, the kept door on a tie, no `doorReads` written without a slip); no existing check changed. Open: a number read with its first digits lost AND a digit misread ("416" for "2416", the first digit gone and one misread) is not one door (one since where both reads name one customer: 'lostOne', below); the panel still said "3 dropoffs: end not guessed" for this trip — two orders held, the add-on's planner is attribution's (the end is not this rule's to give; given since by the held planner's card street, below); a polluted hold restored at boot shows its twelve until the next planner read (healed at boot since: `healPlanner`, below).

**Every planner door mapped, whoever's it is, and the fastest order through them said (the owner, same snap: "the addresses do not need to be linked to the order, it just needs to be mapped. Though it would be helpful if it optimized the shortest/fastest route").** Before, a planner dropoff reached Map view only as an order's end or, with ONE order in the car and an end filed, as a door listed before it (`MV.heldDrops`); with two in the car (the snap: a batch and its add-on) or no end ("3 dropoffs: end not guessed") the other doors were drawn nowhere. **Mapped (map-view.js `plannerDoors`; live.html `wantFor`'s `planDoors`, `plannerRun`, drawMap's `planRun`):** every held-planner stop whose street starts with its house number, pickups and dropoffs, in the app's order, lettered by kind as the app lists them (P1, P2, D1, D2, D3), a pickup keyed by `pickupKey` so a visited one is told as the run tells it. Each gets the point of a mark the walk already has (a held pickup's pin, the held end or ②'s by street, a batched door the ladder placed), else its door on the NucBox in the held card's disc (②'s where ①'s has none); a door no mark stands for is a ring (green pickup, amber dropoff) with its letter, faded "≈" where only its general area was found. **Ordered (`fastestOrder`):** only with the car's point and every stop still ahead at its DOOR (an area is drawing only, never a stop of a stated order). The router's drive seconds between them from a new relay, `/api/nbx/table` (server.js: OSRM `/table/v1/driving/…?annotations=duration`, two to `NBX_TABLE_POINTS_MAX` 10 points, square answer checked, nulls passed for the page to refuse, cached in nbxCache; a refusal or timeout is `unreachable`), else straight-line metres (`crowMatrix`). The rule a delivery cannot break: a dropoff whose order is known (`of`) waits for that order's pickups and every pickup of unknown order; a dropoff of unknown order — nearly all, the planner says no owner — waits for EVERY pickup not yet done (conservative on purpose: it can only miss a legal faster order, never advise delivering before collecting). Exhaustive up to `FASTEST_EXACT_MAX` 8 stops (pruned by the rule and the best so far), else nearest legal stop then 2-opt kept legal. Open route from the car, no return. **Said and drawn (`orderWords`):** "fastest order: P1 P2 D3 D1 D2 · saves 6 min vs the app's" off the router's seconds — OSRM's own free-flow duration, the figure the on-time hint stands on since the owner's decision of 20 Oct, not a pace — or, the router down, "shortest order (straight line): … · 1.2 mi less than the app's", never minutes from miles; "app's order is already fastest" (or "…shortest (straight line)") under `ORDER_SAME_S` 60 s / `ORDER_SAME_M` 0.1 mi (chosen, not measured). The order is a thin dashed sky-blue line (`mv-plan-run`, along the roads via runLine where the router draws it) and each stop's place in it a small sky-blue number beside its pin (`mv-plan-n`). The words go after the caption (MV.routeSaid's notes) and the layer is drawn only where it adds something (`plannerRunShown`: a door no other mark stands for, or an order faster than the app's past the thresholds), so the map and caption are byte for byte as before on every trip whose doors are all marked and driven in the app's order. Kept per stop set and car to ~100 m (`orderKey`, `planOrderKept`, 12 sets; only a router answer is kept, so a NucBox back up is used at the next walk); the NucBox down degrades to straight lines silently. **THE SAFETY LINE:** advice and drawing only — never in `names` or `found`, never posted, never a figure's stop, never the armed end, the GPS drop, a finish, the restaurant guard's or any $/hr; the end armed and every figure are unchanged. Settled stands: no $/mile rule, no payout floor, no pace re-timing, the rig never presses the phone. Checks: mapview.test.js 766 → 777 ('[planner doors]': every door in order and lettered, a numberless street and a town not doors, a stop listed twice once, pickupKey; '[fastest order]': exhaustive under the rule, words in the router's minutes, links unknown / known / partly known, already fastest and under a minute, straight-line miles, refusals for no stops / wrong size / a hole, ten stops by 2-opt still legal and no longer than the app's, crowMatrix and orderKey, the table through a stub relay kept and a NucBox down), test_server +4 ('[fastest order]': the relay's square answer, asked once then cached, a refusal is unreachable; the table's own refusals replace the one "no such NucBox endpoint" check, which pinned it absent) and +1 ('[slip]' end to end); tests/fake-nucbox.js answers `/table/v1/driving`. Open: test_dashboard / test_layout not extended for the new layer (no browser scenario of two orders and an unlinked third door yet); dropoffs passed (`dropsPassed`) are not taken off the order (a pickup visited is) (taken off since, on positive evidence: `planPassed`, below); a door whose search is refused leaves the order unsaid, without words; the add-on's own disc is not grown by its miles as the server's `heldDisc` grows it.

**The add-on's end never filed while every read of its door was a press, and "3 dropoffs: end not guessed" beside two orders that each had a door (the owner's snap of 31 Oct, 21:46, after the slip-healing above).** An Uber order of two customers held ($18.68, card end "<Name> Ct, <Town>"), then an add-on onto its trip ("+$9.57 / +16 min (+2.8 mi)", card end "<Name> Place Bivd, <Town>", no house number). The hold's merged planner listed two pickups and three dropoffs, the last "<n> <Name> Place Bivd, <Town>"; the first order's end was filed (`cue: cardStreet`) as another of them. Status: the add-on `endWhy: "no house number"`, `cue: null`; `holding.planner.unfiled: "dropoffs"`. **Why**: every planner read in the journal that showed the add-on's door was `asked: true` — a ⌖ press — and a pressed read with two held is the chooser's (streetCues answers `asked === false` only; plannerCandidates offers nothing off a pressed page not seen whole); the chooser closed with nobody picking. The pressed pages merged into the hold all the same (24 Oct), so the door was on the list the hold keeps, and nothing asked that list. And `unfiled` is set from each read's own verdict, so 'dropoffs' came back with every read whatever was filed. **The rule (assemble.js `heldPlanEnds`, asked by server.js `heldPlanFiled` after each planner line merges into the hold, two or more orders held, carrying two on or off):** for each order of the planner's app whose end the screen has NOT filed (`filedEnd` null: its card's end, or none) and whose card printed a street (`cardStreets`; "Bivd" and "Blvd" are both type words, so `streetCore` makes them one), the held planner's dropoffs read with street and town are counted on that street; the door is the order's only when exactly ONE is, it is not another order's filed end (`sameStreet`), no other order's card names the street, the towns do not clash (`townClash`), it is no held order's pickup, and the read is not older than the order's Took. Filed through the one road (`dropoffArrived`, forced, cue `cardStreet`, rank `planner`, the stop's customer and time with it), and a chooser open over the same door is closed. Never by position: with the other order's end filed and one dropoff left unclaimed, an add-on whose card printed no street ("Customer dropoff") is still not given it — nothing on record says Uber lists the add-on's door last. Never over a screen-filed end, a press above all. **The note**: once every order of the app has a screen-filed end (`settled`, asked again after the filings, since the road may refuse one), the planner's 'dropoffs' is said no longer, on the hold and the line about to be broadcast — "end not guessed" was true of no order in the car. Replayed in invented names: before, ② stayed the card's street and the note stood; after, ② is the door on its card's street, cue `cardStreet`, the note gone, ① untouched. Checks: assemble.test.js 594 → 607 ('[planEnd]': the snap, filed through the road with its customer and time and then settled, two doors on the street, the one door the other's filed end, another card naming the street, no card street with one left unclaimed, no door on the card's street, another town, a door without its town, a read before the Took, a pressed end, one order of the app); test_server +1 ('[trip end]': a pressed page end to end, mark rows, no chooser, `unfiled` null); no existing check changed. Open: an add-on whose card printed no street, beside an order with its end, still waits for a press answered from the chooser — elimination stays the unprompted, whole-list cue it was.

**DoorDash's own pickup screen after an accept typed as the offer's place popup, and filed nothing (the owner's snap of 31 Oct, 19:14).** Read 14.6 s after a DoorDash ✓ Took with the card gone: "YW Pickup from / <Store> * / Order includes / f Drink / @ <n> <Name> W <Name> Pkwy NW / <Town>, GA <zip>, USA / Directions". `place_popup` read it — a pickup role, the door, the store named "<Store> Order includes f Drink" — so it typed `dd.placePopup`, its popup line was for a card being screened (there was none to file onto), and the one DoorDash order's pickup stayed the card's name (the Open note of the two-app entry above). **The shape**: "Order includes" over the order's items is on this read and on none of the popup's five reads on file (12 Oct, cases.json `popups`; the nearest is "4 items" under the button), and a driver cannot see an order's contents before taking it. **Typing** (both parsers): `POPUP_ORDER` / `dd_pickup_from` (`ddPickupFrom`) — a "Pickup from" line with "Order includes" within `DD_FROM_REACH` (8, chosen: label, wrapped name, the words, four items) under it, and no offer furniture on the frame (`SCREEN_DD_OFFER`) — is `dd.pickup`, asked where "Pickup for" is; `place_popup` refuses a popup with "Order includes" under its label, so the screen is never a popup line. The offer's popup (no "Order includes") types `dd.placePopup` as before, its five reads unchanged. **Its door** (Python `dd_pickup_door`, `_dd_from_door`): the first house-number line under the label within reach that cuts as a street (an item such as "2 Garden Salad" has no type), its town as the popup reads one, the store's name the lines before "Order includes"; scan_pi sends it on the `pickupSeen` line as it sends "Pickup for"'s, and server.js `pickupSeenArrived` files it as the one DoorDash order's `fields.pickupAddr` (rank `label`) and asks the NucBox, or nobody with two DoorDash orders or none. Never a dropoff: `storeScreen` and `navCandidate` refuse `dd.pickup`. Checks: corpus.test.js 1639 → 1642 and test_parser 1722 → 1729 — two `screens` cases (the snap's shape; four items, the door past the popup's reach) and one `popups` case (refused), and in test_parser alone 4 more (the door and name, four items, the offer's popup unchanged, "Order includes" past the reach). Open: one read on record; a DoorDash screen of this shape whose items run past eight lines types 'unknown' (as before) and files nothing.

**What the raised box costs on the Pi is measured where it runs, not estimated (the owner's snaps of 31 Oct; the raise above).** The DoorDash stops card's raised re-read (pipeline.py `raise_journey`, `RAISE_STEPS`) was costed on the development box, 123 ms median on a 141 ms read, and on the Pi only by the same ratio, "about 1.2 s more per read". **The measurement**: `Scanner._look` times its raised reads, kept or refused, from the first raise to the last answer, and carries it on `ms` as `raise` (None on a read that did not raise). scan_pi's `Health` keeps each read's (`raised_ms`), and the health line says, after the rescued count and only in a window that had one, "N raised +Xms median" — every other part of the line, and every line of a window with none, as it was. The tally (`counters`) carries `raised` and `raisedMs`, so the `seen` row and a 📷 Snap's `reader.json` (its `health`) hold them too: 0 and null in a window with none. Measurement only: no figure, verdict, crop or read changes. Checks: test_scan_pi +4 (the count and median with a refused raise counted and an unraised read left out, the line's words in place, a new window with none, a window with none saying nothing); test_pipeline +2 (`ms.raise` on a kept raise within the total, and on a refused one) and one check widened (None with the finder off). Open: the first shift with a stops card on it says what the raise costs; the README's 1.2 s stays an estimate till then.

**Where a live read's time goes is measured at every hand-over, not guessed from the read's own clock (7 Nov 2026).** tools/pi_bench.py on the owner's Pi 4 (cooler on, never throttled): an Uber card 392 ms median, DoorDash's rescue 995–1231 ms, a remembered crop 536, the planner 331, the map label 140. The health lines from the road: 847–975 ms median idle, 1.7–2.4 s on shift, the rescue +3.5–4.6 s, one window 4877 ms — with `ps` putting scan_pi.py at 42–72% of ONE core and the machine mostly idle, so the reads were not short of CPU and the line's `median` (`ms.total`, the reader's own clock) could not say where the rest went. **The measurement** (scan_pi.py `ReadTimes`, `TIME_STAGES`, `TIME_SAY_MS`, `process_cpu`, `load_average`, `Health.cpu_share`, main's `read_clock` and `time_read`; pipeline.py `Scanner.gate_ms`; `Reader.submit`'s `meta` and the job's `clock`; `MapLabels.reads`/`reading`): every read is stamped on the monotonic clock where it changes hands, and the window keeps each stage's median — `wait` the motion gate from the first moving frame to the settled one, `held` a trigger kept back while the reader was busy or the tracker disputed the corners, `queue` submit to the reader thread starting plus the finished read waiting for the loop, `pair` the partner frame's capture, `age` the frame's age when the reader began, `warp` (`ms.warp`), `read` (the rest of `ms.total`), `acc` settle + accumulator + rate, `tell` digest's rest — with the reads that ran beside a map-label read, the label reads and the whole-screen reads counted, and this process's CPU (all threads, `time.process_time` over the window's wall time) as a share of one core with the one-minute load. ONE part on the health line, after the rescue's figures and only when the reads spent TIME_SAY_MS (100 ms, chosen: a quarter of the bench's card read) or more median outside the read itself (`age` not added twice) or one overlapped a label read: `time: wait 620 queue 180 pair 33 age 240 warp 40 read 390 acc 4 tell 10 ms median; 1 overlapped a label read, 2 label reads, 1 nav/planner read; cpu 63%, load 1.20` (invented); a 0 ms stage is left out; every other part of every line as it was. The `seen` row carries the figures as `time` (`waitMs`…`tellMs`, `n`, `overlapped`, `labelReads`, `wholeReads`, `cpuPct`, `load1`) whether the line said them or not; None with no read timed. **Overhead**, measured on the development box: 3.0 µs a read (nine clock reads and the add) and 39 µs a health line, against a 390 ms read — under 0.001%; the gate's one clock read on a moving frame and the loop's one a pass are a tenth of a µs. Measurement only: no read, verdict, row, crop or word on the panel changes, and a timing that throws is dropped (`time_read` is guarded). Checks: test_scan_pi +12 `[time]` (the medians with a missing figure not counted, the part's order and counts and CPU, the row's figures, a quiet window silent with `age` not double-counted, nothing timed, the part on a real Health line after the parts before it, the tally's figures, the windows of the other Health checks silent, the CPU share off the process clock and None over a short window, the load never raising, the gate's wait timed from the first moving frame); test_loop +3 (every read handed over with its clocks through the real main(), a real `seen` row's `time`, at most one part a line). Open: the first shift's lines say which stage the road's extra half-second to two seconds is; nothing is changed on the strength of it until they do.

**cardfind sure of DoorDash's stops card by its red pill, with the raise behind it (the owner's snaps of 31 Oct; the raise above).** The raise rescued 66 of the 90 rendered frames and the finder only 12, under glare: cardfind never knew the card. Rendered, its pill was "not solid" (the two reds 62 and 90 grey, 28 apart, past BAR_STEP); on the rig's frames "not set in a card"; and where the bar was found (the frames through a quad placed by hand) the walk ran up the map to the top of the screen box, the rig's sheet and map being 215 against 203, inside WALK. **Finder** (rpi/cardfind.py `_dd_pill`, `DD_WALK`, `DD_CREEP`, `DD_SOME`, `DD_SHEET`): handed the screen in colour, and only when its grey answer is not sure, it looks for the pill by its red — rows red across 70% of the screen, one pill-height deep, short of its sides — and walks up from it with a tolerance of 6 not 12, a reference that moves at most 2 levels a row (with FOLLOW alone it followed the rig's three-row edge up the map), half a block background not a quarter (the map's pale roads held three blocks "sheet" at a quarter), and a reference per column, not per block (a left-hand shadow ramps 40 levels across one block); the square test excuses one END block (the deepest shadow), every other test as it was. Sure, it says `DD_SHEET`. No Uber card has red: every Uber picture in test_cardfind, and DoorDash's older one-red card, answers in colour exactly what it answers in grey. **Reader** (rpi/pipeline.py Scanner._look): the finder gets the colour screen; it is also asked on a clipped DoorDash stops read, its read held to raise_journey's journey and to the raise's stops-line rule; a refused `DD_SHEET` read leaves the raise to try — a card stacked above on the sheet is in the sheet's crop (two dollar figures), and the box raised 0.09 reaches DoorDash's own payout first. **Measured**, the same 90 frames (x86, the same script both sides): right 78 / none 12 / wrong 0 before and after; now 77 by the finder and 1 by the raise (dark, blur, 760px), was 12 and 66. The 12 shadow misses: the finder is sure of the sheet on all 12 now, and its crop reads no payout — "$14.10" sits in the deepest of the shadow and the reader loses it, as it loses the stops line — so they are still none, refused for no payout. A card stacked above with a bigger payout reaches the panel at no width and through neither box (its $14.10 or nothing). Rig frames (hand-placed quad): sure at the sheet's top on two of the three with a red pill, both boxes; the third through one box, refused as turned through the other (a 4-row spread, SQUARE 3.6); the "Declined" frame (black pill) never takes the path. Cost (`ms.find`, finder plus found or raised reads): 171 ms median on the rescued frames against 166 before, on a 210-224 ms box read — a wash, since one read of the sheet replaces one read of the raised box; the look itself 6 ms. On the 12 shadow misses it is dearer: ~170 ms (a sure look and a refused read) where the unsure look cost 6 ms. Checks: test_cardfind 45 -> 85 (the three sheets at their top through both boxes, grey still unsure, the rig's 12-level map, the shadow, 30 degraded frames sure-means-right, roll, dimmed, stacked, a black pill and an edge-to-edge red band refused, every Uber picture the same in colour, its cost); test_pipeline 311: the DoorDash checks now by the finder, the raise held by an unsure finder, the shadow, the stacked card at three widths and both boxes, a found sheet refused for two figures and for no stops line with the raise after it, a clipped Uber read never asking. Open: the 12 shadow frames want the reader to read a payout in a deep shadow, not the finder; the rig numbers are four frames through a quad placed by hand, not the owner's screen box.

**The release gate on 4b6e148, red in six suites the commits since 4c40cbf had not run: a journal served again, two checks behind deliberate changes, a band timer, a deadline an hour out on a clock-change day, and load.** **test_liveview** (real, a privacy guard): 4c40cbf put `.jsonl` in server.js's `TYPES` so a snap's `journal-tail.jsonl` had a type, and `TYPES` is also `isServable`'s allowlist, so a `journal-backup.jsonl` in the root and a `backup/journal.jsonl` were served in full again. `.jsonl` is now in `SNAP_TYPES` only, asked by `/api/snaps/<folder>/<file>` and the snap bundle; the static handler never asks it. **test_layout** (the caption grew, the table did not): 6ae05c4 gave a DoorDash ② with no end its own caption, "DoorDash dropoff not read yet" with " — ⌖ Scan reads it off your phone" or " — ② drawn ≈ from DoorDash's map", and mapLine's bare `'doordash'` read as one more sentence. Both lines are in `CAPTION_LINES` (no chip: `captionChip` has none for them), the count 116 → 118, and mapLine asks a `dd2` flag `mapWants` sets. **test_loop** (the check was behind 9a8c97a): a store's door cut just after its comma ("<n> <Name> Road, Sm...") has been the street alone since `store_door_town_cut`, on purpose; the check still wanted no door first. It now wants the street first and the whole door told again. **mapview `[band] a hanging router`** (real, timer): a band given up on counted `Date.now() - began` as its wait, and Node's timer can fire a millisecond before that reaches the wait, leaving the next band "1 ms" to ask in; a band that times out now spends at least its whole wait. **test_dashboard "...and can be marked in its own right"** and **test_server's four `[screen drop]`** passed alone on this tree: load. The dashboard's flat 200 ms after the mark's press is now a wait for `aria-pressed` (2 s ceiling); the screen-drop chooser was not changed. **test_server's on-time and store-wait checks** (six, real, a clock fault): server.js `dueAt` made a card's "Deliver by" (minutes since midnight) as local midnight plus that many minutes, which on a day the clocks change is an hour off all day — on 1 Nov (US Eastern falls back) an order due this minute was "late 66", at 01:23 and again at 02:36 EST. It now sets the wall clock's hour and minute on that day and moves by a calendar day. And test_server's own `[shift]` check took "today's shift" as now less four hours, which on that day at 03:30 EST is 00:30 EDT the same date; the shift's day turns at 04:00 on the wall clock (the server's, live.html `dayStart`), and the check now asks that.

**A house number with its first digit lost AND one of the rest misread is one door when both reads name one customer ("416" for "2416", the slip entry's Open above).** The snap's scrolled reads had lost a four-digit number's first digits at the screen's left edge, or misread one digit at the same length; `housesSlip` took either ('lost', 'one'), never both on one read, so a read of "416" beside a kept "2416" stayed a second dropoff. **The rule (assemble.js `housesSlip` 'lostOne'):** the shorter number, three digits at least, is the longer's last digits with exactly one of them different ("416" against the "410" that ends "4410"). Three digits because two digits one off the end of a longer number agree on one digit only, which most doors of a street would pass. `slipStop` takes it as it takes 'one' — the slip that can make two neighbours one — only where BOTH reads printed a name and `namesSlip` calls them one person, on the same street with its type words made one, the times within `NAME_SLIP_MINUTES` or either missing. **The door kept** is the longer per `doorWinner` (the read that lost no digits), whichever came first, and a ⌖ press of the shorter does not put it back (mergePlannerStop treats 'lostOne' as 'lost'); the shorter's other digit is never written onto the longer — which read misread it is not known. **Kept two, as before:** "4418" with a name lost beside "Pat Q." at "4410"; "418" for another customer; initials apart; past five minutes; two digits off; a two-digit "16" against "2418"; another street; another kind. The polluted hold of the slip entry with an extra "416" for "2416" heals to its three dropoffs. Settled stands: the end rules, the GPS drop, finishes and every figure are untouched (they read the read's own stops). Checks: assemble.test.js 607 → 611 ('[slip]': both slips at once merged either way round, pressed, its reads counted; never on a lost name, two names, initials, five minutes, two digits off, two digits left, another street or kind; a lost time no bar and the neighbours two; the polluted hold healed); no existing check changed.

**A held planner restored from disk at boot is healed of its slips then, not at the next planner read (the slip entry's Open above).** A restart mid-delivery with a hold written before `slipStop` (or by any build that kept the slips) brought the snap's twelve dropoffs back onto the panel, Map view's doors and the fastest order until the scanner next read the Trip Planner — on a phone left on the map, minutes or the whole delivery. **Now** server.js `loadHolding` runs each restored hold's `planner.stops` through `Assemble.healPlanner` before the list is set: `collapsePlanner` with every entry kept (none `fromNew`), so `slipStop` is asked of every pair, the earlier standing and `doorWinner` keeping the door. The file does not say which stops came off one read, so collapsePlanner's "never two of the read in hand" cannot be asked at boot; it is the very pass the next planner read gives every kept stop it does not show, so nothing is merged at boot that the next read would not have merged, and a read that lists both again lists the second as its own stop. In memory only — the file is rewritten by the next write of the list, as every restored hold is — and a clean planner is returned as the object it was. "Pat Q." and "Jules K." at one door due the same minute stay two (namesSlip). The order's end, `unfiled`, the GPS drop, finishes and every figure are untouched. Checks: test_server +2 ('[slip]': a polluted hold of the snap's shapes — "16" and "416" for "2416", "315" for "915", "Bivd" for "Blvd" — restored as the pickup and three full doors with the two customers at one door kept two; its end and the planner's word as they were).

**A planner door the car has finished at leaves the fastest order and its "saves N min" (the fastest-order entry's Open above: "dropoffs passed are not taken off the order").** On a batch whose first order was delivered, its door stayed on the list the hold keeps until a planner read showed the list's top — which a phone left on the map never gives — so Map view's suggested order ran from the car back through a customer already served, and the minutes it said were measured through that door too. A pickup visited was already left out (`visited`). **Passed only on positive evidence that the car finished there:** (1) server.js `planPassed`, called by `putDown` for an order put down by the GPS (stopped at its pinned door, then left) or by the delivery app's completion screen (`'screen'`), and by `finishStep` for a Drop's watch finished `how: 'door'` (its door pin's line, kept on the watch as `end`, or the door read after the press, `watchDoor`); the door is kept on the planner the car still drives by (the first-taken's, which setHeld moves onto the trip's next order) as `planner.passed` [{line, by, at}], carried over every planner read, gone with the planner, at most `PLAN_PASSED_MAX` 12; `heldEndState` gives `dropsPassed` — each matched afresh to a stop as `planAtOf` matches an end (the street with its number, one stop only) and said by Map view's key (`MV.dropKey`), absent with none so every other beat is the shape it was. (2) On the page, a GPS STOP at a planner door that the walk placed at its DOOR (map-view.js `doorStopStep`, live.html `planStops`/`planSpots`, stepped by `stepDrops` on each beat): the server's own arrival rule — within 75 m plus the fix's error capped at 25 m for 60 s with no silence over 20 s, then two fixes past 300 m — never `dropPassStep`'s drive-past within 0.1 mi (a drawing's guess), never an approximate area. (3) A dropoff the app's planner no longer lists from its top is already gone from `holding.planner.stops` (mergePlanner's top trim): nothing new. **Never** a press of Drop — the owner drops orders early, before the door, on purpose (finishWatch, 29 Oct) — nor the chooser, a watch finished by 'area' or 'stop' (a red light can make one), an order running out, or a door on the list twice. `MV.plannerDoors(stops, done, passed)` makes a passed dropoff `done` as a visited pickup is, so `plannerRun` leaves it out of `ahead`: the order and its comparison with the app's run from the car through the remaining stops only; its ring, where no other mark stands for it, is drawn faded "✓", titled "— behind the car". **ADVICE ONLY:** `planner.passed` and `dropsPassed` are read by Map view's fastest order and nothing else — not the armed end, not the GPS drop, not a finish, not a figure, not attribution (`planAtOf` is untouched); the page's stops never reach the server. Settled stands: no $/mile rule, no payout floor, no pace re-timing, the rig never presses the phone. Checks: mapview.test.js +4 ('[planner doors]': a passed dropoff done by its key and a pickup never; the stop rule passed, and not off a drive-by, a short stop, one fix away, a silence, an area, a refused or grey fix; '[fastest order]': through the remaining stops with the saving against the app's order of those), test_server +3 ('[fastest order]': no `dropsPassed` with none and none off a press of Drop; ② put down by the app's completion screen puts its door behind the car on ①'s planner, ①'s door ahead; a planner read after it keeps it behind). Open: no suite drives the GPS put-down or a door-finished watch end to end for `dropsPassed` (both call the one `planPassed` the screen's test reaches); the page's stops are forgotten on a reload; the one-order batched run (`MV.heldDrops`, `dropPassStep`) is as it was.

**Every store's door on a DoorDash stops card searched when the card is read, not at the Took (the dd stores entry's Open above: "the server does not search an offer's other stores before the Took").** Map view searched an offer's second store by its door for the preview while the server asked the NucBox for it only after ✓ Took (`pickupAsks` over the hold's `stores`), so the second store's pin — the restaurant guard's, visitPickups', the held run's — landed a round trip after the press. **Now** server.js `searchCardEarly` also asks every other store's printed door of a DoorDash card with two or more (`storesOf`, DoorDash's only) exactly as pickupAsks will at the Took: a pickup's door through `earlyDoor` (`named` false, doorChain), door level, in THAT card's disc, so the Took's questions are answered from `nbxCache` and the status carries each store's pin at once (`heldStoresOf`); the Took's own search still runs and writes `searchMemo` as before. The first store's door is `pickupLine`, already asked; a store with no door is not asked by name; a dropoff is never asked as a store. The extra stores are counted against the warming budget (`EARLY_WARM_PER_MIN`, through `earlyRoom`, shared with `warmEarly`) — a store past the minute's budget is left to the Took, as every store was before — and once per card (`EARLY_CARDS`), as the card's own pickup and dropoff are. Drawing and pins only, as before: no figure, end, finish or GPS-drop rule changed. Checks: test_server +3 ('[dd stores]': the second store's door asked at the card's read inside its disc; the Took pins both with no new request and the status carries both pins in the card's order; an Uber card's list asks nothing).

**A DoorDash stops card's next read is one read, through the crop that rescued its last (the owner's rig, 2 Nov, b309e12: "35 reads, 25 complete; median 2295ms; ... 2 read the payout off a taller card found above the card box; 2 raised +4559ms median").** Every read of a stops card through a box drawn round an Uber card paid for the box's failed read (no payout, or clipped) and then the finder's sheet read and/or the raised re-reads — about 4.6 s on the Pi, on every verify beat for the 30-40 s the card is up, with nothing else read meanwhile. **Reader** (rpi/pipeline.py `CARD_BOX_FOR`, `card_box_refused`, `Scanner.card_box`, `_remember_card_box`, `forget_card_box`): settle() remembers the crop a read's payout was rescued off (finder or raise) with that read's journey, whether its text had a stops line, its polarity and the drawn box it was learned under; the next read of a drawn box tries that crop FIRST and keeps it only under the rescue's own rules — its own money_is_clipped, every journey figure the remembered one (None included, stricter than rescue_refused), one dollar figure, printed as a card prints one, a stops line where the learned read had one. Kept, the box, the finder and the raise are skipped (`cardBox: 'kept'`, cropFrom 'found', rescuedBy as learned, `ms.cardBox`); refused, the box and the whole chain run exactly as before (`cardBoxSaid`) and the crop is forgotten. Nothing of a payout is carried: each read reads its own off its own crop. Forgotten by any read that did not keep or re-learn it, a whole-screen read, a box drawn (use_manual_box), a corner re-lock or re-baseline, the accumulator starting another episode (scan_pi `card_box_episode`, for a card on the same journey with another payout), cardFinder off, a box other than the one it was learned under, and 15 s after the read that last kept it (monotonic). **Health**: "N via the card's last box" after the raised count, only in a window with one; `cardBox` in the tally and on the `seen` row. **Measured** (x86, the 90-frame DoorDash set — three screens, five degradations, three widths, both boxes — each card read four times through one Scanner, a fresh sensor draw each read, the same script both sides with the memory off and on): the 2nd-4th reads (270) median 369 ms before, 129 ms after (mean 365 -> 157); 232 of 270 kept through the remembered crop; right 234 / none 36 / wrong 0 both sides. A card changed between reads to another DoorDash card on the same journey with $16.40 read $16.40 through the crop; one on another journey ($21.35, 15.0 mi) refused it and was read by the chain; a card stacked above with $22.75, after the crop was learned or learned on it, gave $14.10 at three widths and both boxes, never $22.75. Pi: an ESTIMATE, not measured — the same 0.35 ratio on a rescued read of ~2.3 s + 4.56 s gives ~2.4 s, about 4.4 s saved per read after the first; the health line's new count and the `raised` figure falling are what will say. Checks: test_pipeline +18 (the first read learns, the next is one read through the crop with the finder unasked, `ms.cardBox`, the clock renewed, a same-journey card's own payout, another journey refused and re-learned, the stacked card both ways, each forgetting, card_box_refused's seven answers); test_scan_pi +7 (the count and line, none in a window with none, the episode forgetting, a drawn box forgetting). Open: the Pi saving is an estimate until a shift with a stops card says it; a paired read where one frame loses the payout forgets the crop for both, so the next read pays the chain once more.

**The polarity of every crop cost a tenth of a read, deciding three numbers numpy found by sorting a megapixel twice.** Profiled stage by stage (x86, rendered Uber, DoorDash and planner reads through Scanner._look, 6 frames each), `is_dark_mode` took 10-15 ms of a 93-141 ms read — the largest thing in it after tesseract (warp 3-4, upscale 3-4, CLAHE 1.5, parse <1) — because `np.percentile(gray, (5, 95))` and `np.median(gray)` each partition the whole ~900x1000 crop. **Reader** (rpi/pipeline.py `_order_levels`): the three figures come off one 256-bin histogram — numpy's own (n - 1) * q index and its own two-sided linear interpolation, the median as numpy averages an even count — so they are numpy's to the bit, not an approximation (bright_end's strided sample was refused here: an inverted light card is a lost card). **Measured**: identical to `np.percentile`/`np.median` on 3,147 of 3,147 pictures (3,000 random, 1x1 to 400x400, uniform/normal/two-level/banded; 147 crops the reader was handed off rendered screens, both themes, seven degradations) and every polarity decided off them, with and without the last answer as the hint (9,441 of 9,441); 10.9 ms -> 1.7 ms a crop. Pi: an ESTIMATE by the same ratio, roughly 9/10 of whatever the polarity costs there. Check: test_pipeline "the polarity's figures off a histogram are np.percentile's and np.median's, to the bit" (73 pictures). Note: numpy's interpolation formula is the one numpy has used since 1.22; a numpy older than that on the Pi would differ from it in the last bit at most, never in a polarity measured here.

**A rescued read waited on each link of its chain in turn, though no link's crop depends on the read before it (the owner, 4 Nov: "I got the new cooler and the temps are well controlled now"; the rig's lines: a DoorDash stops card's rescue +3.5 to +4.6 s on a 1.7-2.4 s read, and on 3 Nov two raised reads at banding 28.5 that found nothing).** The finder looks at the screen and the raised boxes are fixed steps; only the choice between them reads the read before. **Reader** (rpi/pipeline.py `_SPARE_WORKERS`, `_SparePool`, `_ahead`/`_taken`/`_drop`, `Scanner._finder_ahead`, `_found_card`, `spare_cores`; MAX_ENGINES 4 -> 6): while the box is read, the finder and its read of the card it finds run on a spare core (with the box read's own polarity, decided the same way off the same crop); while the box raised 0.09 is read, 0.18 is. The chain decides exactly as before, in order, on unchanged rules; a link started early is used only where the chain would have read it, read in place when its thread had not begun it, dropped otherwise. Two threads (one per paired frame; one alone measured 407 -> 400 ms, no gain), niceness 10, offered a job only when idle. **Heat-era limits, reviewed with the cooler**: the heat guard (HEAT_ON_C 75 / HEAT_OFF_C 70 and any throttle word now) KEPT unchanged — it never holds anything back on a cool Pi and reacts to real heat and to under-voltage — and now also stops the spare cores (scan_pi, on the beat's sample; said in the log when it changes); OMP_THREAD_LIMIT=1 KEPT, measured not a heat limit (one read 123 ms at 1 thread, 116 at 2, 122 at 4; a concurrent pair 120 / 120 / 1006 ms); VERIFY_EVERY/BACKOFF/MAX, SCREEN_AUTO_EVERY, the single-slot Reader, paired reads and DARK_SKIP_BELOW KEPT — their notes argue staleness, the owner's own read budget, two engines per core and twenty-second reads of noise, not heat. `--no-parallel` turns the spare cores off too. **Health**: "N rescues waited +Xms median" last of the rescue's figures (`ms.find` on a read the finder was asked on or a rescue found, not one kept through the card's last box), `rescueWait`/`rescueWaitMs` in the tally; nothing in a window with none. **Measured** (x86, 4 cores): 1,076 rendered frames against 86eb82a — the 576 taller-card screens, dash_stacked with and without the card above at ten widths, 192 DoorDash stops frames, 60 under banding to four times as strong, 72 four-read memory reads, 144 centred UberX/Shop/DoorDash, planner and stops card whole — every frame the same figures, crop, text, rescuedBy and finder sentence; right 597 / none 417 / wrong 8 both sides, the 8 single drawn-box reads with no rescue in them (an Exclusive card's $4.21 as $4.00 or $421.00 under banding or all-dark, UberX's $16.05 as $5.00 under glare), unchanged. One read at a time: frames past the box 295 -> 195 ms median; the 90-frame stops sweep 314 -> 152 ms, 78 right / 12 none / 0 wrong both. Paired first reads beside a stand-in camera loop (33 ms ticks of ~15 ms work, same process): stops cards 407 -> 259 ms, Early-look 391 -> 270, Uber cards that fit 120 -> 119; the loop's tick p95 20.7 -> 19.4 ms (27.4 unniced), no tick late. **Refused, measured**: skipping the rescue above a banding threshold — the dark stops card under banding scoring 25-48 was rescued on 24 of 24 frames, so a cut near 3 Nov's 28.5 loses payouts the chain reads; the light card lost its stops line and was raised on 1 of 24, costing nothing. Not measured worth it: a smaller read height for the found crop (the found read is now off the critical path). Pi: ESTIMATES by ratio — a first rescued read of ~2.3 + 3.5-4.6 s near 4.5 s; the new health figure is the measurement. Checks: test_pipeline +6 (spare on vs off identical over 11 screens and both raise steps, nothing offered on a centred read or with them off, spare_cores' answer); test_scan_pi +3 (the count, the line, none in a window with none). The rest of test_pipeline's reading block runs with the spare cores off, since it counts reads and asks in order. Open: the camera loop's real cost on the Pi was not measured, only a stand-in on x86; a Pi whose loop needs more than one core would see the live view share with the spares (niced, so it should win).

**A pin that did not come is said once in the log, and once more if it comes later (the owner: a shift's misses could not be counted).** Map view's "NO PIN · <door>, <why>" and /api/status's `endWhy`/`pickupsWhy` were there only while looked at; searchMemo held the last eight orders' searches in memory, written down only by a 📷 Snap. **Server** (server.js `pinSaidNone`, `pinSaidFound`, `pinDoorShort`, `pinWhichPickup`, `memoAsked`, PIN_SAID_MAX): one console line — the process's log, ~/HTTP_Server/logs/uberscan.log — the first time a held order's end, pickup or store N is known unpinned for a reason, in the server's own words (END_WHY's, 'no house number', 'no card fix', 'NucBox down'): `pin: none end #<holdId> "street found, not that door" (<door cut to 20 letters, no town>)`, `pin: none store 2 #<holdId> ...`; and once more if that order's same pin is later found, by the server's retry, band or place, or by Map view's post: `pin: found end #<holdId> by page after 1 ask` (searchMemo's own count of the NucBox's questions for it, `n`, not cut at SEARCH_MEMO_ASKS). Once per (order, which, reason) — and for the end per dropoff text — so the panel's polling, every armHeldEnd and the band's repeat refusal say nothing; a pin found at its first ask says nothing at all; the newest 400 kept in memory. An offer's early searches (searchCardEarly) say `pin: none offer end #<offerId> ...` only where the NucBox was asked and refused: a card with no house number is every Uber offer. Both sayers swallow their own faults; no search, pin, figure or GPS rule changed. tools/shift_report.py does not read the log, so it counts nothing yet. Checks: test_server +12 ('[pin said]': an end refused said once with its door cut short, not again on repeated status, found by the page after 1 ask, an end pinned at once silent, no house number, a card naming no pickup silent about one (the first run said "pickup 'no house number'" with no door for each), store 2 refused and later found by the page, store 1 silent, an offer's refusal, an offer with no number silent, both sayers guarded). Open: shift_report could count the lines for a day; the offer's pickup by name is not logged when unasked.

**A payout whose cents did not read was priced, and where both frames of a read lost them alike it was journalled and spoken (the 8 wrong payouts of b77b1d9's 1,076 rendered frames, traced through the loop, and a ninth their count did not score).** Every one is a single drawn-box read with no rescue: the Uber Eats Exclusive card's $4.21 read `$4:21`, `$4°21` or `$4. io 1` — MONEY_STRICT stopped at the mark and took $4.00 — or `$421` (no point at all); UberX's $16.05 under glare `$ 5 eee …`, $5.00; and, in the centred Shop set cmp.py left unscored, the $7.09 Shop & Deliver card rolled two degrees at 600px read `$7 .09`, $7.00. Re-read on five sensor seeds, the banded Exclusive card read a wrong figure on 5 of 5 at 680 and at 760 ($4.00, once $421.00) and 3 of 5 at 600, and the Shop card $7.00 on 4 of 5, so the two frames of a paired read agreed, Scanner locked, and through `main()` the card was journalled, announced and (with --speak) spoken at the wrong figure; the accumulator keys on the payout and votes nothing across reads, so a wrong figure that locks is the card. The glare $5.00 came from one seed of five, never locked, and still put "PASS ?" at $5.00 on the panel for its read (read_the_money publishes the frame that read a payout). The $421.00 is OP.doubt's 'pay': CHECK THE PAY, no rate. **Parsers** (rpi/offer_parser.py and offer-parser.js `CENTS_LOST`): a whole-dollar figure followed by a bare point, by one or two marks and then two digits with a real one among them, or by a space and a point and two such digits (not the rider's `*`, not a leg's minutes), is cents printed and not read; it competes as the largest figure and, if it wins with nothing of its value read whole, there is no payout — never the next figure down. cases.json +7, and `$16".l87`, a case named "a payout with a stray mark in it is refused, not half-read" that expected the half-read $16.00, now expects none. **Loop** (rpi/scan_pi.py `unsure_payout`): a payout printed neither to the cent nor with its label or star (OP.pay_is_printed), on a reading not locked, is not shown or priced on the panel — the panel's copy only, no payout and no verdict for that read; the reading itself, the destination guard, journal and voice (which wait for `locked`) are as they were; said once per card and figure in the log. **Measured** (against ea623ed): the 1,076 frames, scored sets right 597 / none 417 / wrong 8 → 600 / 420 / 2 and the Shop set's one wrong → right — 4 of the 7 lost-cents frames read the card's figure through the reader's own second look, 3 read none, no other payout or journey moved (3 no-payout DoorDash frames under banding changed which read's text they carry; one of them, `$21:35`, had read $21.00 in its box); every right payout of the 1,076 is printed, so `unsure_payout` holds back none; the 366 distinct texts with a dollar sign in the shared corpus: only `$16".l87` moves; both ports give the same payout, minutes, miles and completeness on 417 texts (the corpus's, the frames', the rule's edges). Left: the $421.00 (doubted, unchanged) and the $5.00, now never priced. Checks: test_loop +9 ("a payout whose cents did not read" over the frames' own texts — all-banded, `$7 .09` on every frame, misreads among right frames before and after; "a payout printed without its cents, read by one frame"; the whole-dollar controls: `$19 | Guaranteed` on both frames priced on the first read, `$7 Guaranteed` off one frame), test_money +36 (the 9 frames read in pairs over two seed pairs through the real Scanner: no payout but the card's, a doubted one or the glare frame's unprinted `$ 5`, nothing priced but the card's), cases.json +7. Open: two frames agreeing on the same wrong whole-dollar figure would still be priced (nothing rendered does it); a whole-dollar DoorDash card prints "incl. tips", which HEADLINE_LABEL does not take for its label, so read with its frames disagreeing it waits a read; the phone's scanner (scan.js) reads single frames and has no pair to wait for.

**Screens with a street and no accepted address were counted, never quoted (the owner's 2 Nov health line: "73 screens since start had a street on it and no address the rig would accept"; 2 of 7 orders ended unpinned, their ends the card's cross-street).** Counted in digest (rpi/scan_pi.py, `street_seen_no_address`): a read taken for no offer (screen_address), no find_address answer, and STREET_ENDS anywhere in the text. **Log** (`why_no_address`, `STREET_SAY_EVERY` 20 s): the read that counts one is quoted, three times a minute at most — the count since start, the screen's type, then what took its doors (a Trip Planner whose stops find_planner read, Uber's opened sheet, DoorDash's pickup screen) or the app's idle screen, then up to three address-looking lines cut to 40 letters with the reason: a door with no `, ST ZIP`, a cross-street (two names either side of `&` or `at`), no house number, a town alone, a state or ZIP that is not one, a ZIP with no "Town, ST". Log only; no count, rule or answer moved. **Measured, what the count is made of**: over the shared corpus (684 distinct texts) it would count 104 — 54 planners with their stops read, 15 opened sheets, 1 DoorDash pickup screen, 26 doors with no town/state/ZIP, 4 cross-streets, 2 with no house number, 1 idle screen, 1 ZIP with no "Town, ST"; over the 201 distinct read texts on the owner's 📷 Snap pages of 12 Oct – 2 Nov (scratch, not committed), 46 — 16 planners, 14 DoorDash idle screens ("You're in a good place to wait for offers": STREET_ENDS takes "place to" for a street), 7 DoorDash pickup screens, 9 doors with no ZIP (8 a planner's page read flat or its stop headers lost, 1 a road's label on Uber's map). On the snap pages streetNoAddress rose with the planner sightings (23 Oct 57-58 beside 37-41; 31 Oct 46-50 beside 52-55). **Looked for a door shape the parsers miss, found none safe**: every customer door in those 150 that no rule takes is one the corpus refuses by name — a sheet with no "Dropoff type", a town cut in half, a second address between the name and the label, map labels in capitals — so neither parser moved; no cross-street or town is taken as a door. Check: test_loop +8 (the quoted line with its reason and the count, once over three reads inside STREET_SAY_EVERY; each reason on an invented screen). Open: the count still includes planners and idle screens, and the 2 Nov unpinned orders' screens are not on file — the next shift's quoted lines are what can say why they were.

**The "no address" count takes only screens a door could be on; OCR litter is counted apart (7 Nov 2026).** With the samples above, the count reached 298 in one shift and what it quoted was litter off screens nobody could type: `unknown: "'a sie ee 2 e. ° ray st 1%" a door, no ", ST ZIP"` — a map's texture or a half-lit glass with an "st" in it, a screen that never had a door to give and so no evidence about the strict rule the count is kept to judge. scan_pi.py `door_could_matter`, `real_words`, `DOOR_SCREENS`, `Health.street_unreadable`: the count and its samples take a payout-free screen with something street-shaped on it only where it is typed as one that shows a door (uber.planner, uber.nav, uber.pickupNav, uber.delivered, dd.deliver, dd.pickup, dd.delivered, dd.placePopup), or its planner stops or Uber's opened sheet were read, or a street-like line of it is in real words — a word of three letters or more with a vowel, noise (a mark, a stray letter or two, a figure that is no number) in at most half its tokens; a number, a quadrant and a street's type word are neither. The rest is counted apart and never quoted: "N unreadable screens since start with street-like words" beside the count, only when there are any, and `streetUnreadable` on the `seen` row. Measured over the shared corpus (tests/fixtures, 678 distinct texts): of the 96 screens the count took, 95 still counted — every planner, sheet, navigation screen and door with no town — and the one set apart is a map's litter under an offer's title. Counted, not acted on: no read, destination, row or panel word changes. Checks: test_scan_pi +15 `[no address]` (litter and real lines each way, a planner's stops or a sheet counting whatever the words, a typed screen counting however littered, the real-words rule, the line's words apart and as a run total, one in English, none saying nothing, the tally's figure, the navigation label through the loop not set apart, litter through the loop counted apart and not as a street). Open: whether the idle screen's "a good place to wait" belongs in the count — it is typed dd.finding and passes the words test, so it stays, as why_no_address already names it.

**In the pillar's shadow, a DoorDash stops card lost its payout to the found card's read, though the finder found the sheet (rpi/testcards.py `shadow`: 12 of the stops sweep's 90 frames, both light drawings, every width and box).** "$14.10" sits at the left, in the deepest of a shade down to a quarter of the light, where CLAHE's tiles stretch the ramp and the ink together; the found read gave the journey and was refused for no payout. **Reader** (rpi/pipeline.py `even_light`, `EVEN_LIGHT_SPAN` 41, `preprocess(flatten=)`, `Scanner._found_card`): a found crop whose read gave no payout (not clipped, not left unread as dark) is read once more with its own background divided out — a 41px morphological closing is the ground — and the second read is used only if it has a payout; a found read that gave one is never read again, and the drawn box and the raised boxes are read as before. **Measured** (x86): the 90-frame sweep 78/12/0 → 90/0/0 right/none/wrong; the 1,076 rendered frames +17 payouts (the 12, a stacked stops card in shadow, three Early-look cards and a two-order card in daylight), no wrong one, no frame that read a payout or journey before reading another; even_light 2.3 ms on a 900x992 crop; the added read ~100 ms where the found read lost its payout (the 17: 132 → 238 ms median; 5 tried and still lost, 111 → 213), nothing elsewhere; Pi an ESTIMATE of one more read. **Refused, measured**: evening out every found read — +31 payouts but two right $21.35s read $21.38 under blur, a wrong figure added; a Gaussian background (sigma 40) and per-column percentiles read the 18 shadow frames too but at 71 and 17 ms against 9 for the closing (with preprocess); CLAHE clip 4 read none of the 12; a closing of 81 read as 41 did. Checks: test_pipeline (the shadowed sheet, both drawings and boxes, reads its own payout off the found card; no drawn box evened out, read alone or before its rescue, one found read evened out; even_light turns a quarter-to-full ramp white and keeps the ink dark). Open: the remembered crop a found read taught is read once, plainly, and a shadowed card's next read goes back through the chain (it reads right, a read later than it might).

**DoorDash's whole-dollar stops card read no payout through an Uber-shaped box, its `incl. tips` no label to the reader (16596d3's Open: "a whole-dollar DoorDash card prints 'incl. tips', which HEADLINE_LABEL does not take for its label, so read with its frames disagreeing it waits a read").** Worse than the read it waited: `pay_is_printed` is also what `pipeline.rescue_refused` holds a found crop to, so `rpi/testcards.py`'s stops card drawn at a whole `$14`, through BOX_DD_PAY or BOX_DD_BELOW, read `$14 incl. tips` off the finder's sheet and was refused — no payout on all 48 frames of a sweep (light and dark, one and two customers, both boxes, 600/680/760px, two seeds). **Parsers** (rpi/offer_parser.py and offer-parser.js `HEADLINE_LABEL`): `incl. tips` right after a figure — the point read as `.`, `,` or `:`, `tip` or `tips` — is its label. Only the word at once: Uber's `incl. $3 tip` chip starts with a figure and is not it, `$14 | incl. tips` is not at once. A label only says how a figure was printed; `CENTS_LOST` is asked of the figure alone, so `$14:10 incl. tips` is still no payout. offer-parser.js gains `payIsPrinted`, the twin of `pay_is_printed` (findPay's `printed`), and cases.json a `printed` section both ports answer (test_parser, corpus.test.js). **Measured**: the 48 frames now read $14.00 / 33 min / 8.7 mi off the found sheet, both frames of each pair printed and neither held by `unsure_payout`; the 667 distinct corpus texts (cases.json and sequences.json, 373 with a dollar sign) move nothing — payout, minutes, miles, places or the printed flag — every `incl. tips` card in them printing its cents; the two ports give the same printed answer on all 677 with this entry's cases. Checks: cases.json +2 parse (the `$14` stops card, `$14:10 incl. tips` no payout) and +8 `printed`; test_loop +3 (a `$14 incl. tips` frame beside a frame with no payout priced off one frame, nothing held in the log; `$14:10 incl. tips` on every frame never priced); test_money +8 (the stops card at $14 through both boxes, light and dark, paired: $14.00 and its journey, printed, neither frame held). Open: a whole-dollar card read with its label a mark away (`$14 | incl. tips`) still waits for two frames, as `$19 | Guaranteed` does.

**The map label of a card for two customers was routed as the last stop, under a caption saying the other customer was not known (cdfe959: "Multiple dropoffs (2 stops)", "≈ 1 of 2 dropoffs from DoorDash's map; the other not known yet").** The run Map view asked the road for was car -> store 1 -> store 2 -> the label, so the line ended at the label and drew the other customer somewhere before it — an order nobody gave, the fault the two-orders run already refuses ("one line through both would draw an order nobody gave", `MV.heldRuns`). The held order's run did the same with its `dropoffGuess`. **Map view** (map-view.js `guessOneOf`, `oneOfLeg`; live.html): on a card or a held order whose `dropoffs` is two or more, the road is asked to the pickups only (`routeLadder` with no end) and drawn solid as the job's run, and the label hangs off the last store on a dashed straight leg of its own (`mv-one-of`) — never a road, never the run's end; it starts at the last store because every pickup comes before any dropoff, which the card does say. With the stores behind the car, the held order's leg starts at the car. The ring's words say "one of the 2 dropoffs, which comes first not known"; the caption is guessShare's, unchanged, and is said also where no road could be asked (a lone store, nothing in the car). One-customer cards and Uber cards draw as they did. Drawing only, as before: the label is never `found`, posted, a figure's stop or the GPS drop's. Checks: mapview.test.js +3 (guessOneOf's count, oneOfLeg's two points and its refusals, the run with no end stopping at the last store); test_dashboard +2 (a two-customer card's label: one dashed two-point leg from the pickup to the ring, the ring's words and the caption, nothing posted; no other job line ends at the ring). Open: the held order's two-customer leg is not driven by a browser check (its card twin is).

**Two real neighbours with short names made one stop by the slip rule ("Kim" at 2416 and "Tim" at 2418 on one court, due two minutes apart; review of 6 Nov, invented).** `namesSlip` let any two names within an edit per three letters through, and a three-letter name one letter off ("Kim"/"Tim", "Joe"/"Jon") or two ("Ann"/"Dan") passed, so a digit-misread door ('one') with two neighbours' names was one stop — per read, and at boot (`healPlanner`) off a hold that listed both. A number lost to two digits ("20" for "120") with a name unread was one stop whoever it was. **Now** a word of four letters or fewer is held by the door: at one door as before; a number with its first digits lost ('lost') at most one letter off ("jez." for "Tez L.", the snap's first-letter slip; "Ann"/"Dan" are two edits and two customers); a digit misread ('one', 'lostOne') only `sameName` ("Quin C."/"QuinC."). Five letters and more keep the ratio, which the snap's five readings of one customer need. A 'lost' slip with a name unread on either read is taken only where three digits or more are left ("471" for "2471"). `healPlanner` asks `slipStop` and so heals nothing the per-read rule refuses. The snap's six reads, its polluted holds and the boot heal still come to two pickups and three dropoffs. Checks: assemble.test.js 611 → 614 ('[slip]': the neighbours kept two, per read and at boot; a lost name at three digits, a short name read the same a digit apart, a long name mangled a digit apart still one); one existing leaf moved from "10" to "410" — its point, a name lost, stands at three digits.

**A second door on the add-on's card street went uncounted when its town line was cut, and the one with a town was filed by force (review of 6 Nov, invented).** `heldPlanEnds` counted only dropoffs that read both street and town, so "212 Kestrel Place Blvd, Brookvale" beside "218 Kestrel Place Blvd" with no town passed "exactly one door on the card's street", and server.js `heldPlanFiled` filed it with `force`, skipping the chooser — one customer's door as the other's end. **Now** every headed dropoff that read a street is counted, its town or not (its `line` before the comma where it read no `street`); the door filed is still the one hit only, and still must have read its street and town. Checks: assemble.test.js 614 → 615 ('[planEnd] ...nor one door on the card's street with its town beside a second read without', by street and by line alone); no existing check changed.

**A held end on a real "Pt" street replaced by a planner's misread "Pl", the correct read then kept out (review of 6 Nov, invented).** assemble.js kept its own copy of the street types (offer-parser.js's `STREET_SUFFIX`), which lacks "Pt", "Cv", "Lndg", "Rdg", "Trce", "Gln" and the other USPS types map-view.js's retry knows, so `betterRead('120 Oak Pl', '120 Oak Pt')` called "Pt" a slipped last word like the snap's "NUP": `outranks` gave the misread 'better read', and the ~580 guard (`!betterRead(cur, d.line)`) then stopped the correct "Pt" coming back. **Now** `betterRead` and `typedOver` ask map-view.js's `STREET_TYPES` (`streetType`) — one list, required beside assemble.js in node, the only place it runs — and fire only where the kept read's last word is neither a type there nor a quadrant. "Row", in the old copy and not in map-view's, was added to `STREET_TYPES` so nothing that was a type stopped being one. **Kept short on purpose:** `hasStreet` and `typedEnd` still read the old list — they read a town beside a street, and "West Point, GA" ends on a USPS type: a wider list would make a town alone a street. Checks: assemble.test.js 615 → 616 ('[slip] betterRead: never over a last word that is a type Map view knows', outranks keeping the end); no existing check changed.

**"9 min to complete" filed as the DoorDash store's door, and the right door could not replace it (review of 6 Nov, invented).** rpi/offer_parser.py `DD_PICKUP_HOUSE` took any number and words after "Pickup for <name>" as the store's door — a time, an item's "2 Chicken Sandwich" — scan_pi sent it (`emit_pickup_seen`), and server.js `pickupSeenArrived` filed it at rank 'label' over the card's pickup; the store's real door read next was at the same rank with no planner key, so `outranks` refused it and the junk stood — searched, pinned or refused, as the GPS drop's guard. **Now** the parser asks `_dd_door_shaped`: the line's LAST street type ends the street (then a road's number, a quadrant, the comma, a suite at most — so "3 Way Combo" and "1 Street Taco" are no doors and "120 Court St" is one) and it is no count of minutes or items (`DD_NOT_DOOR`); `_dd_from_door` already asked a type. The server lets a door on a typed street (`typedDoor`: a house number then a word `MV.streetType` knows) replace a 'label' pickup off `dd.pickup` that names none, so a hold the old build wrote mends at its next read; a press or the card is left to `outranks`. Python only: the scanner is the screen's one reader, so cases.json is unchanged (the screen's type is not). Checks: test_parser 1778 → 1779 (a time, an item's count, an item with a type word, the door after an item still read, "Hwy 92" and a suite kept); test_server's two-app pickup check now sends the junk door first and wants the real one filed over it.

**The twins mended "Dr.. S W" differently: Python took every dot off the type before the quadrant, JavaScript one (review of 6 Nov, invented).** `quadrant_slip` asks that "N W"/"S W" follow a street type; Python stripped the word before it with `rstrip('.')`, offer-parser.js with `/\.$/`, so "52 <Name> Ridge Dr.. S W" was "...Dr.. SW" in Python and "...Dr.. S W" in JavaScript — one screen, two doors, on the rig and the phone. **Now** both take one dot, as every other type test in both ports allows (`DOOR_TYPE`, `LABEL_TYPE`: `\.?`): a type with two marks after it is not known to be one, and the slip is left as read. No case on file carried two dots, so nothing that read moved. Checks: cases.json +1 ('address': "...but "S W" after a type read with two dots"), test_parser 1779 → 1780, corpus.test.js 1691 → 1692.

**Nothing kept an order's whole story once it left the car (the owner, 7 Nov 2026: "Can you improve the logging to also document as much as possible about an order? It is helpful for records later").** The card was an offer row, the Took a mark, the end a drop, finished or undo row, a pickup visit an index with no name; which store each pickup was and where it was pinned, when the car stood there, the end as filed and who pinned it, the odometer since the Took, the snaps taken while it was carried and the orders beside it lived in holding.json and memory, and went with the order. tools/shift_report.py rebuilt what it could the next morning and could not rebuild what had only been memory. **Now** server.js writes one `kind: 'order'` row as each order leaves the car (`orderRow`), by every road: Drop, the chooser, the GPS drop, the completion screen, the offers page's untick, a Took that replaced it, an expiry, the panel's Took taken back (`untick`, which writes no drop row) and a boot past `MAX_HELD_FILE` (`boot`, which writes none either), each in the same append as that end's drop row. Built by setHeld as the order leaves (`orderDraft`, beside `pinOutcome`, kept `GONE_KEEP` deep in `goneRecords`) so its pins and searches are still known. Fields: ids and links (`id` the holdId, `offer`, `app`, `links.addon/addonTo/batch/tookOn`), the card as offered (pay, card and billed minutes, miles, deadline, stops, the verdict and $/hr shown, `reads` — counted on the slot as the card is re-read — and the places as printed: the hold's new `offered`, `offeredOf`), `times` (offered, took, at the door, pressed, ended, restarts), `pickups` (store, door, pin and by whom or why not, visited and how, the dwell's start `reachedAt` and the odometer `milesAt` that markVisited now keeps on the pickup), `dropoff` (text, rank, filed at, cue, pin, why, armed, a refused end's area `approx`), `guess` (DoorDash's map label, `approx`), `planner` (stops counted), `drive` (odometer miles since the Took and to the pickup, fixes, refused, gaps: `orderLive`/`orderBeat`, memory, a few additions per beat), `money` (`orderMoney`: pay / (minutes / 60) and pay / miles over `ORDER_PER_MILE_MIN` = 0.1, only for the report's delivery ends — the report's `rates`, held equal by its suite), `pinning`, `with` (the hold's new `withIds`), `snaps` (named on each held order at the press), `flags`, `missing`. Text cut at `ORDER_TEXT_MAX` (120), lists at `ORDER_LIST_MAX` (8), nulls left out: about a kilobyte. Stamped when written (`at`, `seq`; `times.ended` is the end), since rpi/doctor.py reads an earlier stamp after a later one as NTP stepping the clock. **A Drop the GPS goes on finishing** writes its row when the watch ends — finished at a door, area or stop (ended at the stop), out of window or pushed out by `FINISH_MAX` (the press stands, `finish: 'none'`) — the record kept on the watch in `finishing.json` across a restart (`orderWatchLine`); an Undo inside the watch takes it back with the order. An Undo of a press with no watch comes after its row is down: the order's next end writes a second row, readers take the newest by `at` and drop a row whose press an undo row names. **A restart mid-order** keeps all holding.json holds; the restored hold gets `restarts` and its drive counts from the boot (`drive.from: 'restart'`), and `missing` says so in words, as it says a hold from before the record has no card as offered. **Places follow keepPlaces**: the row restates places the journal already holds and adds the pins' coordinates, which no row carried — the "ids and words" rule narrowed for this row at the owner's request, as journal.py's `places` was — so with the scanner's `keep` false (now kept as `scanner.keepPlaces` off sighting and planner lines) it holds no store, door, dropoff, pin or area and says `places: false`. **The shift report** prefers the record (`records`, `_record_for` within `RECORD_MATCH_S`, `ended_by_record` in the drop rows' own words and rules), falls back to rebuilding, prints a place-free "Records" line per order and `record` in --json, takes miles off the record's odometer with no GPS log, and `--csv PATH` (with `--to`) writes the records CSV, `RECORD_COLUMNS`, places included — the one output with them, a file the owner names; bare `--csv`, the text and --json stay place-free. **The offers page** (journal.html) shows an "Order record" block in a ticked offer's opened row and an "Order records" section with **⤓ Download CSV**, the same columns built in the browser from `/api/journal`'s new `records` (server.js `orderRecords`: newest per order, undone presses out, oldest Took first, at most `ORDER_RECORDS_MAX`) — no new endpoint, through /api/journal's own door; static serving and its journal guards untouched. **The NucBox** stores the rows with no change to rpi/sync.py or ingest (syncKey's fallback, `[kind, id, seq]`). Checks: test_server 1339→1372 ('[order record]': every end, a GPS door/area/stop/none finish, the restored hold, keepPlaces off, an undone Drop, /api/journal's records, not an offer); test_journal 410→413; test_sync 207→211 (written by the real rig, carried whole, idempotent, served by the copy); tools/test_shift_report 208→233 ('[record]', '[record csv]', the formula and constants against server.js, the columns against journal.html); test_offerspage 595→612 ('[order record]', '[order record csv]'). Not mutation-tested.

**What Uber actually paid for an order lived only on its Earnings Activity screen, and nothing joined it to the card (the owner, 7 Nov 2026: "compare what uber actually paid compared to the expected pay of the order" ... "Can it automatically figure out which order it belongs to in the journal?").** The card says what an order will pay; the app's own screen says what it did, a tip hours later. **Now** the offers page's "What the app paid" box uploads screenshots of a day (`POST /api/earnings/shot`, the picture as the body: PNG, JPEG or WebP on its first bytes, HEIC refused with what to send, `EARNINGS_SHOT_MAX` 12MB with a Content-Length past it refused unread, `EARNINGS_SHOTS_MAX` 60 kept). server.js keeps each as `<id>.shot` in `earnings/` beside the journal (0600 in 0700, a partName temporary, gitignored), reads it with the `tesseract` command (`TESSERACT` or PATH, asked each time; `--psm 4 -l eng`, one thread, `EARNINGS_OCR_MS`), keeps `<id>.ocr`, and files its trips through `earnings.js`: `parse` (Uber's Earnings Activity: the day off the end line's year, the heading or the chip; per trip `finishedAt`, amount, tip as a figure or `processing`, type, Uber's minutes, seconds and miles, the pickup and its bracket, the dropoff's street and town; a scrolled-off top and a trip with no time skipped and said; `PARSERS.doordash` reads nothing and says no DoorDash screenshot has been seen), `sameEntry`/`mergeEntry` (one trip per app, day, minute and name or amount; a settled tip never un-settled by an older screenshot; the change kept in `history`), and `matchDay` (time 40, name 25 or -15, a chain's corner in the pickup door 10, dropoff street 15 or -10, minutes 10, miles 10; gate 20 min; `ACCEPT` 55 and `MARGIN` 15 over the next candidate and the next entry for that order, one order per trip; the app's clock offset from the day's confident matches, within 10 min; the driver's pick kept). Each new or changed trip is one `kind: 'earning'` row, v1, id `earn:<key>` and seq its stamp, so the sync carries it on syncKey's fallback; no pickup or dropoff with keepPlaces off. A screenshot with no day takes its upload's (`batch`). `GET /api/earnings`, `/pick`, `/reread`, `/forget` (the pictures go, every reading and row stays); the JSON ones insist on application/json. **Nothing is served**: `.shot`, `.ocr` and `.jsonl` are not in TYPES, so the allowlist answers 404 wherever JOURNAL moves the folder, and rpi/ is refused by name; static serving and the journal guards untouched, the whole of it one section of server.js and one line in route(). **The offers page** shows "Card $X → Paid $Y (base $B + tip $T)" or "(..., tip pending)" in the order's record (`paidLine`), the trips that need the driver with their top three for a one-tap pick, the trips with no order on file, what to install where tesseract is missing, and two-press delete; the records CSV (journal.html and `tools/shift_report.py --csv PATH`) gains `paid_total`, `paid_tip`, `tip_status`, `paid_minus_card` (`paidCells`/`paid_cells`, the newest row of each trip within `RECORD_MATCH_S` of the order's Took). **The Strategy tab** gains "Card vs paid" (tools/strategy.js `cardVsPaid`: by app, block and restaurant, n beside each, under `PAID_MIN_N` 5 thin, a pending tip out of every total and counted), and its one line, which names no restaurant; the end-of-shift report does not pass earnings to it, its text and --json naming no figure or place of them. Descriptive: nothing the rig decides reads what was paid. Checks: tests/earnings.test.js 139 (new; tests/fixtures/earnings.json, the shared corpus's shape), rpi/test_earnings.py 15 (new; rpi/testearnings.py draws the screen at 756px, the real tesseract reads it), test_server '[earnings]' +36, test_offerspage '[earnings]' and '[earnings csv]' +14, tools/test_shift_report 244 → 252, tests/strategy.test.js 80 → 90, tests/placesreport.test.js 358 → 366. Invented restaurants, streets and figures throughout; the owner's screenshot is not in the repository. Not mutation-tested.

**Uber's right-hand time was read as the trip's finish, and it is the trip's start (the owner's screenshots of 12 Nov 2026, compared by hand with the rig's order records for that evening).** In invented terms: six trips came up on the rig 18, 3, 0, 8, 9 and 0 minutes after Uber's time (the 18 a batch of two pickups accepted on the phone before the rig's Took; one Took came 19 minutes after its card), and Uber's own minutes and miles ended each trip 9 to 13 minutes before the rig's end; the last of the six expired on the rig and was never timed, and one had no Took at all. Matched on the finish, every one of them was scored against the wrong moment. **Now** `earnings.js` reads the time as `startedAt` (a row's old `finishedAt` read the same, so keys and trips stay) and scores out of 125: start 40 against the record's `times.offered` or `times.took`, whichever agrees better, on a lopsided band (full from 2 min before to 10 after, none from 8 before or 25 after, no candidate past 10 before or 30 after); finish 15, Uber's start plus its minutes (`endMs`) against `times.ended` only where that end is a delivery's (`DELIVERED`: drop, gps, chooser, screen, a finished press; never an expiry, a replacing Took or a take-back), full from 3 before to 15 after, none from 10 before or 25 after; name 25 or -15, corner 10, dropoff 15 or -10, miles 10 over a delivery only, and pay 10 (within 25 cents full, none from $2 or 15%, never a penalty, not while a tip is processing). Uber's minutes against the rig's Took-to-end are no longer a part of their own. `ACCEPT` 60, `MARGIN` 15: neither clock, nor both, is enough alone. The clock offset is the median of how far each confident match (75) fell OUTSIDE the full start band, within 10 min, so the rig's ordinary lag behind the phone is not taken for a clock fault. Rebuilt runs carry their offer's first sighting (`offeredAt`), and the earning row its match's `offeredAt`, `how` and `startBy`. On the invented evening built like the real one: all six matched clear (scores 90 to 114, margins the same), the one never on the rig "no order on file", no offset; with keepPlaces off the four clean deliveries still match and the batch and the expired order are left to the driver; with the rig's clock 12 minutes ahead every trip is still its own. Checks: tests/earnings.test.js 139 → 147, the [match] section rewritten for the start; test_server's and test_offerspage's '[earnings]' days rebuilt on the start. Invented throughout; the screenshots are not in the repository. Not mutation-tested.

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

*Re-measured on the 13–20 Sep week (1,166 offers, 431 in towns with enough of
them), and the conclusion moved.* 12–3am $20.94, 3–6pm $13.99; 65 of Atlanta's
113 in the first, 43 of Marietta's 101 in the second. Raw lead $5.33, held lead
$4.26, best-to-worst $6.33 → $4.98, four towns change places, p = 0.002. The
correction is still needed — it reorders four towns — but on this week the hour
is about a fifth of Atlanta's lead, not more than half. The figures above stay
as the record of what was measured then; the code and README now quote these.

*And that fix introduced a second error of its own, in the opposite direction.*
The hour's baseline was the median over the whole kept pool with the town
INCLUDED, so a town that owns most of an hour wrote the number it was then
measured against and had its own advantage subtracted from itself. Three texts
said otherwise — the driver-facing sentence ("than the same hours paid
elsewhere"), the note above it in `map.html`, and `advice.js`'s own comment ("a
town is being compared with the other towns on this page") — and the code did
none of it. Atlanta owns 65 of the 81 kept offers in the best-paying block:

| town | shipped | own offers left out | | town | shipped | left out |
|---|---|---|---|---|---|---|
| **Atlanta** | **+1.47** | **+3.28** | | Marietta | −0.54 | −0.98 |
| Kennesaw | +0.31 | +0.13 | | Dallas | −1.08 | −1.70 |
| Mableton | +0.19 | +0.13 | | Smyrna | −1.41 | −1.13 |
| Acworth | −0.05 | −0.23 | | Powder Springs | −1.45 | −1.69 |
| Woodstock | −0.11 | −0.13 | | | | |

Less than half the real figure on the one town where repositioning is a
decision, and three towns move — Acworth and Woodstock swap, Dallas goes from
seventh to last. The baseline is now what the OTHER towns paid in the same hour.
The bootstrap says which number to trust: over 400 resamples the town coming out
top is Atlanta in 305 of them under the new baseline and in 124 under the old,
where Woodstock — fifteen offers — took first place 107 times.

*What it does not touch is whether the ranking may be shown.* `p`, `h` and
`real` come from the Kruskal-Wallis on ranks forty lines earlier and never see
this baseline, so nothing here can talk the page into printing an order that
does not beat chance. Verified on the week: `p` stays 0.002 either way.

*A town with no elsewhere gets no figure, and that is not zero.* Where a town's
every hour held no other town there is nothing it can be said to have paid more
or less THAN, so `matched` is null and `MV.rankLead` prints a dash with no unit
— `null >= 0` is true in JavaScript, so the obvious formatter puts "+$NaN/hr" on
the page's most quotable figure. The formatting moved out of `map.html` to be
driven without a browser; five mutations, five kills.

*One existing check rested on the bug.* A fixture of two towns that share no
hour asserted `matched === 0` for both, and its own comment explained why: each
town WAS its hour's baseline and came out level with itself by construction. The
answer was right by accident. It now asserts null, that no hour-held ranking is
offered, and — the part that makes the fallback safe — that the medians it falls
back to are still labelled as chance, because those medians are the $21-against-
$11 landslide the whole section exists to refuse.

*Two of the new checks were wrong first.* One asserted that two identical towns
get the same figure, which is true under BOTH baselines, so it could not fail and
went; what discriminates is the size — 4.0 against the old 0.1. The other guarded
`placed.length > 1` where 1 is impossible, since a town is comparable only
because an hour held another town that is comparable by the same hour. Written as
`placed.length`, with the proof in the comment.

*And `tests/mapview.test.js` printed its own total two sections early.* Thirty
checks ran after the summary line and were counted but never announced, so a red
run printed "All 195 map-view checks passed" with the failures underneath it. The
summary goes last now, and the true count is 225.

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

**The map said the best three-hour stretch and the worst were $X apart, and X was how far apart the TOWNS were.** The clause printed rawSpread, the spread of the town medians, which does not depend on the blocks at all. Measured on the owner's week (TZ=America/New_York, newest N days back from the last offer, printed / true): 1 day $4.33 / $8.72, 2 days $7.10 / $5.91, 5 days $6.98 / $7.23, 7 days $6.33 / $6.95. Fix: Advice.areas returns hourSpread, the best block median minus the worst over the same kept pool and pens the held figures use. rawSpread stays where it means towns ('unheld it looks like'). Trap: on the full week the two are 62 cents apart, near enough to read as right. So the test journal puts the blocks $12 apart and the towns $6 apart, and quoting one as the other cannot pass by coincidence. Checks: advice 'the spread of the hours is the best hour against the worst'; test_map 'the sentence about the hours quotes how far apart the hours are'. A pin's popup also paired the hour-held position with the raw median: Kennesaw 3rd at $15.32 above Woodstock 4th at $15.80, 2 of 36 pairs backwards. It now goes through MV.standings, which quotes the rankLead figure the sidebar row leads with, and a town with no matched figure gets no ordinal. Checks: mapview 'a pin quotes its town's position with the figure it was ranked by' and the three test_map pin checks. Trap in the test fixture: the nominatim stub matched the first KNOWN town found anywhere in the query, and the page's hint put 'kennesaw' in every query, so three pins stacked on one point passed 'every town is pinned'. The stub now takes the earliest match, and '...each at its own town, not three on one point' fails if it is reverted.

**The server's geocode cache could be lost and the map said nothing.** Since 9f2bd1a, /api/places has answered `unreadable` for a places.json that will not parse. map.html loadPlaces tested only `ok`, which is true on that answer, so it took the empty set in silence. A places.json that exists but cannot be read (EACCES/EISDIR) answered only `stored: null`. The cost is 1,325 places and 24 minutes to rebuild. Fix, overriding plan 4.5, which would have deleted the field as unread: the page reads it and says it on the load line, with the server's reason and the cost ('looked up again'). The read-error case answers `unreadable` too, and ENOENT stays a silent empty cache. Trap: said any earlier, the journal's own line writes over it a moment later. Checks: test_map 'a server cache that will not parse is said on the load line' and its three followers; 'a server with its lookups intact is not said to have lost them' (so the reader can fail both ways); test_server '...and says so too, rather than looking like a fresh box'.

**The maps could not say where the car is now, or how sure the GPS was of
it.** Both now draw the heartbeat's newest fix as a dot inside a circle the
size of the GPS's own error, with "±28 m · 2 s old" in the map's corner.
What to draw is `MV.hereDot`, shared by `live.html`'s Map view and `map.html`,
and the gate it obeys is `rpi/gps.py`'s (see The GPS, below): nothing in
JavaScript judges a fix again. A fix the gate refused is no dot, and its
reason is said in the corner ("GPS too rough here (±129 m)", "GPS gives no
accuracy here", "GPS reports no 2D/3D fix"), never a dot that silently is not
there. A stale fix is drawn grey where it was, and a beat that stops coming
is greyed by the page once gps.py's `freshFor` runs out, its age counting on
(two durations, never two clocks subtracted). No fix at all is nothing drawn
and nothing said. The map never follows the dot (superseded 12 Oct: see "Map view follows the dot" under The GPS), because tiles cost hotspot
data nobody has measured, and there is no new control on the bar. The dot is
redrawn only when its position, error or grey changes, so the once-a-second
age tick does not close its popup. Commit c5204a3.

`map.html` asks `/api/status` every 10 s while visible. Measured on the three
status.json files the rig's own snaps kept, with the new fields added: 1,783
to 1,996 bytes an answer, at most 718,560 bytes an hour while open from
elsewhere. The label's fit was measured by `rpi/test_layout.py` on every panel
for every form it takes, at a four-digit error: inside the map, 44px clear of
the zoom buttons, at most two rows. On the 3.5" hat `map.html` scrolls and
leaves the map about forty pixels, so there it is held only to lying across
the map clear of the buttons.

Checks (mapview 232 → 251, test_map 208 → 219, test_dashboard 917 → 933,
test_layout 1436 → 1653, test_lint 318 → 321), each made to fail by name:
`fixOf` ignoring `gpsOk` fails 'a fix the GPS gate refused is no position
here'; a dot that never greys fails 'a dot whose beat stopped coming greys
once its time is up'; a rough fix drawn fails 'a rough fix is not drawn, and
says why with the figure'; the age frozen at the beat fails '...and its age
keeps counting, not frozen at the beat'; a map that re-anchors on every poll,
or a panel that follows the dot, fails '...and the map does not move with
it'; the label left unbounded fails '...clear of the zoom buttons at 480x320'.

*The verifier found the one fit to the dot could come minutes late.* The fit
belonged to whichever draw first HAD a dot: `live.html` kept `hereWanted`
standing until a fix came in, and `map.html` fitted "the first time there is
one". Entering Map view with gpsd still acquiring, then panning away, pulled
the view back to the car when the fix arrived: a fit on a beat, which is the
map moving with the GPS. The fit now belongs to the entry. `live.html` clears
it on the first draw of a Map view with the map built, dot or no dot, and
`map.html` on its first `/api/status` answer (or that ask failing). A late fix
is drawn and the view is left alone; ⛶ Map round again, or a reload, frames
it. Commit 204d3f8. Checks: test_dashboard '...and the view is not fitted to
it: the one fit was the entry's' (the old `if (hereWanted && key)` puts it
back and it fails, the fit being the pins plus [33.9706, -84.5499]); test_map
'...and the view is not fitted to it: the one fit was the first answer's'
(waiting for a dot fails it, the view going to [33.9526, -84.5499]).

**"+31.3 mi out of your way" was printed for a McDonald's 21.8 mi from the
car, on a job whose whole trip was 9.4 mi.** Two faults made it. The detour
line on `live.html`'s Map view was measured from `askCar`: the newest journal
row carrying a position, up to 20 minutes old and cached 120 s more, which is
another card's car. And nothing asked whether the map had found the right
branch of a chain, since `MV.farFrom` only accuses a pin past 75 mi.

Now `here` is `MV.cardFix`: the fix the scanner took once when the card landed
and put on the offer line, passed by the gate. `askCar`, `carFix`,
`FIX_STALE_MS`, `FIX_AGEING_MS` and the age hedges are deleted with it, and so
is the await they put between the key and the first mark. *The `partial`
entry above describes that await as it was; the one that remains in the
`finally` is `needLeaflet`.* A pin farther from a card's fix than the card's
own distance plus `SLACK_MI` (0.5, now shared with `judge()`) is refused, by
`MV.cardRefuses`, with a line that blames the map, never the world: "wrong
pin for McDonald's — 21.8 mi from you, past the card's 9.4 mi
(rig-corrected)". The order in the car keeps its card on the hold (`server.js`
`cardOf`: the fix, the gate's answer, the miles and the yardstick flags), and
its end is checked against its OWN card's fix the same way.

Which cards are a yardstick at all is `MV.cardYardstick`: the summed miles,
never `toPickupMiles`; never an Early look card; only a printed total or two
summed legs, so a one-leg card (DoorDash's shape) says "no yardstick yet"; and
a figure `rate()` doubted refuses as a suspect one does. Measured over the
week's 1,166 cards in that order: 10 none, 17 untrusted, 27 Early look, 528
one leg, 584 yardsticks (577 naming a pickup, 267 rig-corrected). Instead of
a figure, a card with no usable fix says which: "this card came up without a
GPS fix", "GPS fix on this card too rough to measure from (±129 m)", and the
same for the held card. Commit fc77935.

*The verifier found the refusal reached only after the held order's guards.*
With nothing in the car, or a held end the geocoder could not place, the same
McDonald's was drawn as an ordinary green pickup under "nothing in the car to
compare this against". And a refused pin kept its pickup colour, because only
`farFrom` turned a pin red: the map and its caption kept two rules for "this
pin is wrong". `drawMap` now asks `MV.cardRefuses` once per pin and uses the
one answer for the pin's colour, its popup and the line, where both refusals
come straight after the misread-name line and before every held-order guard.
The refusal leads its line because the 3.5" hat's clamp eats the tail:
measured by `rpi/test_layout.py` at the widest case (12 W's, 74.9, 99.9,
rig-corrected) the whole line does not fit three rows at 480x320, so the `,
past` clause is the declared tail and a check holds that what the clamp keeps
opens with "wrong pin for". `DISC_PLACE_SHOWN` is 12 because at 20 both disc
lines run past two rows at 800x480. A hold with no card (a holding.json from
before the server kept one) says "the rig kept no card for the order in your
car", not that it came up without a fix. And 'judge() and the card's disc
share the half mile' asserted `SLACK_MI === 0.5` and could not fail; it now
puts `judge()` at the disc's own edge, 9.85 and 9.95 mi on the same 9.4 mi
figure. Commit a3cf4e7.

Nothing Settled is reopened: the figure is still straight-line miles with no
minutes and no route through the new job's end, a pin is only refused and
coloured, never moved, and no distance reaches the verdict, $/hr or the stack
line. Checks (mapview 251 → 283, test_dashboard 935 → 943, test_stacking 170
→ 172, test_layout 1653 → 1768), each made to fail by name, among them:
`outsideCard` returning null fails 'a same-brand pin 21.8 mi from a fresh fix
on a 9.4 mi card is refused, not printed as "+31.3"'; the yardstick on
`toPickupMiles` fails '...measured on the summed figure, not the approach
leg'; `askCar` put back fails 'the detour comes from the card's own fix, not
the newest journal row that carries one' and 11 more; the refusal moved back
behind the held guards fails 'the pin is refused with nothing in the car too,
not hidden behind "nothing in the car to compare this against"'; a colour that
ignores the refusal fails '...drawn red, not as the pickup' and two more;
`setHolding` dropping the card fails "the order in the car keeps its own
card's fix and size"; `DISC_PLACE_SHOWN` 20 fails '...and nothing is cut short
at 800x480 (a pickup this card contradicts, a held end its card
contradicts)'.


**The panel's places went to a public geocoder one a second, chosen as its first answer, and the detour was a straight line.** The NucBox now runs Nominatim 4.5 (:8088) and OSRM (:5000) on the Georgia extract, and with `NUCBOX_SEARCH` / `NUCBOX_ROUTER` set in server.js's environment Map view asks them through `/api/nbx/search` and `/api/nbx/route` (fixed upstream parameters, anything else refused by name; OSRM's duration dropped before a page can see it). Empty settings are today, exactly. Each place is searched inside its card's disc (fix, card distance + 0.5 mi) and pinned only when it is alone or all inside agree, from a list not cut at the limit of 10 (`cutAt`); a house number is pinned only where the answer carries it ("street found, not that door"). The card's postal town is never sent and never used: the real install answered "Shadowood Pkwy SE, Atlanta" with nothing and the street alone in a box with two pieces in Cumberland, and a town tie-break picked the wrong piece in the verifier's probe. The detour is road(car→pickup→held end) − road(car→held end) in road miles, never minutes and never via the new job's end; it is refused below −0.05 mi ("router took different roads") or with any point snapped more than 0.2 mi. Only OSRM's NoRoute is "no road"; any other code is the router down and never cached. `NUCBOX_TIMEOUT_MS` is a wall clock including the connect (it was 5 s on Node 22 and unbounded on Node 18's agent against a host that never accepts, holding Map view). The page falls back to the public map only when the server says unreachable or not configured; a refused question is shown as a bug and sent nowhere. The README carries the driver's Docker commands and the install's real answers; no Tailscale address is committed, and test_lint holds that. Checks: mapview 283→347, test_server 526→573, test_dashboard 943→964, test_layout 1768→1941, test_lint 324→326. Open: cross streets and a street's stretch wait for a street index; map.html and the offers page still use the public geocoder.

**Map view's corners and numberless streets came from a public geocoder's one point, and the first street index matched names too loosely and measured a street to a point the card never named.** The NucBox's `tools/street_index.py` builds a JSON index of every named drivable way in the metro (-85.00,33.50,-83.95,34.40) from the Georgia extract; the NucBox's own server.js loads it with `NUCBOX_STREETS_FILE` and answers `/api/streets/cross|stretch`, relayed by the rig as `/api/nbx/cross|stretch` when `NUCBOX_STREETS` is set (asked only alongside `NUCBOX_SEARCH`). A corner is pinned where its two streets meet inside the card's disc, and refused when it meets several times there, not at all, or the streets run together. Names match exactly; with a directional on one side only (two names each with one the other lacks never match: "Main St NW" is not "S Main St"); after dropping litter only after a short-printed type, never a word before it ("Ol Canton Rd" had been asked as Canton Road a mile off); and by one misread letter, only i/l (177 of the 190 letter-for-letter differences between frames of one card), only among names inside the disc, and only when nothing else matched anywhere. On all 2,679 distinct street-like strings of the week that took OCR answers from 75 (5 a different real street, Beach/Beech among them) to 28 (none). A numberless street's figure is the straight-line detour at every point of its stretch in the disc, stated only as one answer ("on your way" everywhere, or a range under half a mile wide past it) and otherwise refused ("no figure for X — the street runs N mi in its card"); measured to the nearest point it had shown true +1.5 as +0.6 and true +0.4 as +5.1. The router is not asked for it ("· whole street, no road figure"), every road reason main showed is shown again, and "NucBox down, public map for the rest" is said when the NucBox answered places first. Comma-less corners (63 of 403) stay with Nominatim. Checks: streets 0→71, mapview 347→391, test_server 573→593, test_dashboard 964→973, test_layout 1941→2055, test_lint 326→328. Open: the metro's size and load figures are estimates until the exporter runs on the NucBox; a street type misread the same way in every frame ("Cedar Ridge Or") is refused, not matched.
**Map view drew where each place was looked for and how it was found, and the first version clipped its words, zoomed out to its circles, and lost the map when it failed.** Under the pins Map view draws the card's disc (blue; the held card's amber), every NucBox candidate as a grey dot (a corner's every meeting), one past the disc hollow, and a numberless street's stretch inside the disc, all from answers the walk already holds (5 relay requests, each once). A mark's words show in one box across the map's foot rather than a Leaflet tooltip, which clipped up to 92px on the hat, 12px at 800x480 and 21px on 390x844. The fit is the car and the pins only: the discs had zoomed the hat from 10 to 8 on a 9.4 mi card and to 7 on a 20 mi one. The decoration is drawn after the essentials, guarded and all-or-nothing, so a failure costs only it and the key says "how each was found: not drawn"; the key names only marks drawn. The text says what the disc is: the pickup's (and held end's) reach and where the NucBox searches; the dropoff is held to none; with no NucBox, the 60 mi public box and then wide. map.html rings a pin answered outside its box (hollow means "not used" on the panel), its popup gives the box actually searched (137 by 134 mi in Atlanta, not "60 mi"), and it has a one-line key. A check that could not fail (a stretch too long to send whole: the index sends no lines past its cap) was removed. Checks: mapview 391→420, test_dashboard 977→1005, test_map 221→228, test_layout 2097→2133, test_lint 335→339. Open: every server message while the same card is in Map view re-fits it, so a pan lasts until the next message.


**Map view's "crossing lines" were the tile grid.** `#viewWrap img`, the camera picture's rule, also matched Leaflet's tile `<img>`s in the same pane: every 256 px tile got a 1 px `--line` border and 14 px round corners, long slate lines one tile apart and a dark four-pointed star where four corners met. The rules say `#viewWrap > img`. With it: the tile pane alone muted (saturate .3, brightness .78, contrast .9; the same tiles, nothing new asked); pins 12 px solid with a dark P or D, the held order's end a 13 px ring edged in its own amber with a white D; runs 5 px over a 9 px dark casing; with the NucBox router set, the detour and the held order's run drawn along OSRM's road shape (the relay asks `overview=simplified&geometries=geojson`, fixed server-side, and hands on `line` or null; duration still dropped), straight otherwise; discs 1.25 px at .6 and hidden at any zoom where the radius is more than the view's longer side, the key following; between offers the map takes the verdict's column (`body.between`) and Leaflet is told its new size. test_liveview read the between-offers rule as placing #app and was red from this lane until the verification pass. Checks: test_dashboard (pin sizes and edges, added), test_layout, mapview, test_server's route shape. 29 mutations, each killed by name.

**The "on your way" figure ignored the held order's restaurant.** With a pickup still listed, the figure is the best of the new pickup before or after the restaurant, less the run car → restaurant → end (MV.detourThrough; with no stops it is MV.detour exactly). By road it is asked gap by gap, road(prev, pickup, next) − road(prev, next), at most 3 points a question through the existing relay; any refused gap refuses the figure. The caption says "incl. restaurant"; a restaurant with no pin, refused, past its card, misread or a numberless street is said, never measured past. The job's own leg is drawn by road. server.js also searches each planner pickup with a street on the NucBox inside the held card's disc (searchHeldPickup), so the restaurant guard no longer needs Map view, and a merchant's store-number tail is dropped for the NucBox name search only. Checks: `[held route]` in test_dashboard, the detourThrough and road checks in mapview, `[held pickups]` in test_server.

**Between offers the card said WAITING FOR AN OFFER with an order in the car, and the GPS drop's state never reached an open panel.** `heldEndState()` is the one source for /api/status, heldForPanel and the beat (`heldEnd`). Between offers, with an order held, the card shows the next stop large and one line of pay and GPS state; with an offer up that line moves under the card. The pair line sits above the figures, range first, with no verdict colour. Took on a card that has left the phone says its age. Open: on the 3.5" hat beside the scene picture a pair runs about 9 px past the card; the Took age makes the bar taller between offers (74-93 px against 55).


**Whether a second offer was on the way, with an order in the car, was said only in Map view's caption, and the map did not say the order of the stops.** One neutral line under the pair line now says it on the card, without ⛶ Map: "ON THE WAY · +0.0 mi · same side of town", "OUT OF THE WAY · +4.6 road mi · ends elsewhere", "CAN'T TELL · NO PIN · <place>, none fit the card", "CAN'T TELL · NUCBOX DOWN", "CHECKING THE ROUTE". It is the caption's answer, computed once (mapLine returns { said, fig }), with the ends from stack.ends; no verdict colour, larger when driving. The card's walk asks the NucBox through Map view's own NbxSearch: with Map view open it adds no question; shut, 3-4 a card while an order is held; the public geocoder only on ⛶ Map. The pins carry 1, 2, 3 in visiting order with the new pickup in the gap the figure chose, nothing numbered when the order is unknown; the held run is solid and the extra leg dashed; the view is fitted once per card on the settled draw and refits only for a new card or ⛶ Map, so a visit no longer pulls it off the follow. A failed Leaflet load is retried only on ⛶ Map or after 60 s; a card's pins and figure go once its reading is stale; NbxSearch keeps at most 100 answers; map.html's position request has an 8 s deadline. Settled: the detour still never runs through the new job's end, the half-mile cut-off is unchanged, no minutes. Open: a rig with no NucBox has no card line until ⛶ Map.

**Whether taking a second order still delivers both on time was not said anywhere (the owner's request of 20 Oct 2026).** By his decision, recorded under Settled beside "Do not re-time an offer at a pace", the NucBox router's own drive times may answer it, for this hint only. **Relay:** /api/nbx/route passes OSRM's `duration` (seconds, or null) beside the metres, the snaps and the line, and takes two to five points (`NBX_ROUTE_POINTS_MAX`: the car and two orders' four stops); Map view reads none of it. **Rule:** server.js `onTimeHint`: with ONE order in the car and the offer on record the reading's card, when the car (the offer card's own fix, `MV.cardFix`), the held order's pickup while not visited (one, from its kept pins; a pickup on record with no pin, or two ahead, is no answer), its door-level end (`heldEndPin`) and the offer's pickup and dropoff (searched here on the NucBox at door level inside the offer card's disc, `offerPin`) are all pinned, and both deadlines are known (the held order's Trip Planner "Expected by" for its dropoff stop by `planAtOf`, else its card's `deliverBy`; the offer's `deliverBy`, else its card minutes from now as Uber's promise), three orders of the stops are asked, no more: with the pickup ahead A-pick A-drop B-pick B-drop, A-pick B-pick A-drop B-drop, B-pick A-pick A-drop B-drop; with the food in the car A-drop B-pick B-drop, B-pick A-drop B-drop, B-pick B-drop A-drop. Each arrival is the router's leg times plus `PICKUP_ALLOW_S` = 300 s at every pickup before it, CHOSEN, NOT MEASURED (no restaurant wait is on record). "both on time" when some order makes both deadlines; otherwise the order least late in all, said by the later of the two, "① late ~N min" (the held order) or "② late ~N min" (the offer), whole minutes rounded up; nothing when anything is missing. **Fallback:** every pin the detour needs and no deadline (or no times) gives `offWayMi`, road(car (→ A-pick) → B-pick → A-drop) less road(car (→ A-pick) → A-drop), the new pickup either side of the held one, the shorter, refused below −0.05 mi; never via the new job's end (Settled). The card's way line already says that figure from the same roads, so the panel draws "+N.N mi out of the way" only where that line will not be up (no NucBox search). **Panel:** first in the pair line's words that give way (`.ontime` in `.more`, "both on time · with the one you have, over …"), no verdict colour: a chip of its own wrapped the row at 800x480 and a grid column of its own cut the range on the 3.5" hat (both measured in test_layout), so it gives way before the range, whole on every panel but the hat beside the scene picture, where the ellipsis takes "n ·"; the verdict, the state, the range and the pair row's arithmetic do not move. **Journal:** the pair row gains `onTime: 'both'|'late1'|'late2'|null`, with `lateMin` when late and `offWayMi` on the fallback, numbers only; a row whose hint is still being asked waits for it, `ONTIME_WAIT_MS` = 4 s at most, then is written with null; with no router set it is written at once, as before. Checks: test_server 983→988 (end to end through tests/fake-nucbox.js: both on time; the held order due this minute, late1 with its minutes; no deadline, the miles; the held end unpinned, nothing; the relay's duration and five points), test_dashboard 1337→1339 ("both on time", "② late ~7 min", none; nothing else on the card moves), test_layout 4306→4312 ("① late ~12 min" at the pair's widest: whole on every panel and picture but the hat's scene view, cut by "n ·" there). Fast lane: not mutation-tested, the full suite not run (lint, test_server, test_dashboard, test_layout were). Open: the hint is asked on a reading and shown on the next reading of the same card, with no push of its own; two orders in the car, or an add-on, have no hint; the allowance at a pickup is a constant, not a wait measured (closed 22 Oct for a store with two GPS waits on record: see "How long the car waits at a restaurant" under The GPS). Mutations (catch-up, 21 Oct): 17 run, 17 killed by name. The four checks above killed 8 (who is late, the least-late choice, the offer's minutes as its deadline, the card's deliverBy, the five points and the duration on the relay, the row's wait, the miles); 9 survived them and are killed by new '[on time]' checks, worked from the fake router's legs: an 11-minute offer is "② late ~3" only with PICKUP_ALLOW_S counted and the minutes rounded up; the planner's Expected by, read with the card on record, makes ① late; a held pickup ahead with no pin gives nothing; ahead and pinned with no deadline, 1.7 mi, the shorter side (the longer is 2.7); two orders in the car give nothing; an offer with no deadline and no minutes gives the miles. Found on the way: a new card forgets the planner (forgetPlanner), so the planner's deadline is used only when the planner is read while the card is on record, and the pair row (written on the first reading) never has it. test_server +6. Closed 22 Oct: onTimeInputs falls back to the Expected by filed on the hold with its end (`fields.expectedBy`, Assemble.file), before the card's `deliverBy`, so a planner read BEFORE the offer still times the held order, on the first reading and its pair row; test_server '[on time] the planner read before the offer, forgotten at its card...' +1. Mutations (catch-up, 21 Oct; live.html's pair line only): 7 run, 3 killed by the existing checks ('both' never said and the hint out of the redraw key by 'on time: the pair line says "both on time"...', the hint after the words by '...first in the pair line's words'); 4 survived and are now killed: ① numbered ② and a late with no minutes said ('~null') by test_dashboard 'on time: the held order late is ①; a late with no minutes says nothing; ... the road miles', the miles fallback never said by the same, the miles said with the NucBox search set by '[on time] with the NucBox search set the pair line leaves the road miles to the card's way line'.

**Settled: Map view's tile filter stays a filter.** An overlay draws 2.4-3 ms a frame cheaper but cannot desaturate (tile saturation 0.067 against the filter's 0.019), and at night its brightness-matched alpha leaves amber reaching 3:1 against 14% of the tile against 21%.

**A dropoff read short off a dark frame found no door, so no pin and no GPS arrival (19 Oct, night).** The Trip Planner's dropoff "1106 <Name> Ln, Marietta" was read off a dark grayscale frame as "L106 <Nam..>r / Marietta, GA" — the type gone, the name's last word cut and the letter at the cut misread — and filed "1106 <Nam..>r, Marietta". The NucBox's search answered nothing: `endWhy` "not inside the card's reach", no pin, GPS arrival not armed; the street-type retry had no type word to leave out. Now, LAST, where the street as printed (and without its type word, where that retry was asked) is not inside the card's reach (`MV.nameWanted`: `retryWanted`, and `afterRetry` kept the first answer), and only with `NUCBOX_STREETS` set, the NucBox's street index is asked which ONE street inside the disc's box the name as read is (`MV.nameAsked`, the street less its house number; `/api/streets/named?name=&box=`, box required, `streets.js named`): match's own rules counted among the streets reaching into the box (a name held as read anywhere decides, so a real street read right is never read as another), else `cut` (`cutFits`): the same name words but the last, which is the index's word cut short with at least `CUT_KEEP` = 4 letters before the cut read right and the cut letter anything, or whole with only the type lost; a type word or none on the index's side; directionals as match's; no digit, no read that kept its type, never a read longer than the word. A street only when exactly one fits (`among` 1); two near ones ("Brindler": Brindlewood Way, Brindleton Court) are none. The door is then asked ONCE by "<house> <the street as OSM spells it>" (`MV.nameRetry`) and taken only at door level inside the disc, held to that street's name and type when it has one (`MV.pickNamed`: pickRetry/retryFits, else pickInDisc); `afterRetry` chooses, so the first refusal stands otherwise and a street found without the door goes on to the place. The server (`searchHeldNamed`, both questions through `endAsk`, which takes a reader so the index's answer is checked by `streetAnswer('named')`, cached in nbxCache and a NucBox not answering handled as the first question's) and Map view (`NbxSearch.named`, only with `opts.streets`; the index down leaves the first answer, never the public map) ask the same URLs (`streetTarget`, shared with the relay, which now passes `/api/nbx/named`). The pin is `by: 'server'` with `asked` "1106 <Name> Lane", so `/api/status` says `endAsked`. The NucBox runs this same server.js: it answers `/api/streets/named` only after a pull and restart there. CUT_KEEP is chosen, not measured (no frame of the fault is in the repo). Fake: "1106 Tamaror" answers nothing, "1106 Tamarons Lane" a door 1.7 mi north-west of the Square, and the fake's `/api/streets/named` is the real `streets.named` over an invented three-street index. Checks: streets 71→88 (named's 15 shapes, the endpoint, its refusal without a box), mapview 578→592 (nameAsked, nameRetry both ways, pickNamed, nameWanted's 8; through the server: pinned with the three questions in order, all three from the cache for a second page, two near names neither and neither door asked, outside a 1.0 mi card, not without the index set or a disc), test_server 934→943 '[name rescue]' (pinned and `endAsked`, the wire, the cache, two near names, outside the disc, a door found as printed never asking, the relay's box rule and answer, NUCBOX_STREETS unset never asking). Mutation testing deferred by the owner's decision of 19 Oct (speed over depth on experimental), to run before main. Open: the held order's pickups (`searchHeldPickup`) do not ask the index; the owner should check what the real index answers for the fault's read. Mutations (catch-up, 21 Oct): 26 run, 25 killed by name, 1 equivalent. streets.named/cutFits 10 (no box, `among` 1, keys held to the box, CUT_KEEP at the cut, a typed read, a digit, the word whole, longer than the word, the letters before the cut, directionals): 8 killed by the existing shapes; "a read that kept its type" survived where the word was cut clean, and "...nor one cut clean before its type: 'Tamaro Ln'" now kills it; `if (r === w) return name.length < base.length` was equivalent (an untyped street read whole is the index's own key, which match's rules find first), and now says `return true`. map-view 9 (nameWanted's two guards, nameRetry's `among` and same-name refusals and its `retry`, pickNamed, `opts.streets`, `asked` on the pin, nameAsked's letters): 9 killed. server 7 (the street-index steps without NUCBOX_STREETS and after the type-word retry, `asked`, an end's `named`, streetAnswer's `among`, streetQuestion's box, a refused answer used): 3 killed; 4 survived, now killed by '[name rescue] after the type-word retry found nothing, the index is asked...' (a door printed "1106 Tamarons Ln"), '[name rescue] the index unset: ...' and '[name rescue] the index answering names beside two streets ...' (with the relay's 502 beside it). test_server +4, streets +1.

**The street-index rescue could not read a street whose last word was cut to a fragment after its type was lost (the owner, 20 Oct 20:44).** "2100 <Ellison> Lakes Dr" read "2100 <Ellison> Lake r": `cutFits` (9cddfb3) wants the cut word's letters read right but the last, and "Lake" + "r" is the word read right to its fourth letter and the type's remains — so `/api/streets/named` answered none. Now a last word of 1–2 letters after a full word (at least `CUT_KEEP` letters) is a FRAGMENT: it is left out, the word before it must be the index's word whole or cut with at least `CUT_KEEP` letters and none misread, the words before that the street's, and the index's street must have a type word (where the fragment came from). Compared as PRINTED (`named` passes the printed words as `sq.raw`): "Lake" is a type word in its short form ("lk") and "Lakes" is not. Only when exactly one street inside the box fits, as before. Checks: streets 95→102 '[fragment]' (the fault, the whole word with a two-letter fragment, two near streets none, an untyped street none, fewer than CUT_KEEP letters, a letter misread, the words before). The NucBox answers `/api/streets/named` with its own server.js, so it needs a pull and restart for this. Mutations (catch-up, 21 Oct), cutFits' fragment only: 10 run, 8 killed by name, 2 equivalent. 5 killed by the existing '[fragment]' shapes; three letters taken for a fragment, a word of three letters before it, and a digit in that word survived and are killed by '[fragment] ...three letters is no fragment', '...nor is one after a word shorter than CUT_KEEP' and '...nor after a word with a digit in it' (two invented streets added to the fixture); `cut.length >= CUT_KEEP` (frag already holds it) and `cut.length < word.length` (a cut the word's length that is its first letters is the word, which `q[n - 2] === word` takes) were equivalent and are gone. streets +3.

**Between offers the held order was a straight pickup-to-dropoff line, router or no router (owner, 19 Oct).** Map view's car came off the card's fix (`MV.cardFix`), and between offers there is no card, so the held run was drawn with no car in it — pickup pin to dropoff pin — and the road was never asked because `heldRoad` wanted a car. Now, with no card's fix, the run starts at the live GPS fix (the beat's, through `MV.hereDot`'s gate, never a grey one), KEPT by `MV.routeFrom` until the car is more than `ROUTE_MOVE_M` = 300 m from it or the leg changes (the end, a second end, the pickups still ahead): 300 m is chosen, not measured — past it the road visibly starts behind the car, under it the start is inside the fix's circle. The kept start is in Map view's key, so a far move or a new leg walks again and anything else is one road question per leg, answered from NbxSearch's cache; car → pickup → end along OSRM's `line` before the pickup is visited, car → end after; the single-order road no longer needs a car at all (pickup → end along the road with no fix). Straight only with the router unset or refusing (`runLine` null). Under an offer the run still starts at the card's fix, as the figure does. The offer's own trip (`mv-job`, its pickup → its dropoff, along the road when pinned) is now teal `#2dd4bf`, not the pickup pins' green, beside the run's amber and the violet detour, and the key gains "━ offer" when both trips are drawn. Drawing only: no figure from the live fix, no minutes, no route through the new job's end. Two orders in the car keep their road only under a stated figure, as before. Checks: mapview 595→604 (routeFrom kept/far/leg/no fix; runLine from the cache, a new leg), test_dashboard 1337→1344 `[road run]` (between offers along the road from the fix, nothing asked 100 m on, asked again 330 m on, car → end after the visit, straight with the router down, the offer's trip teal by road beside the amber run, the key naming both), test_layout (the key with every item, "━ offer" in it). No mutation run (fast lane). Open: the two-order run between offers is still straight. Mutations (catch-up, 21 Oct; panel and Map view drawing only): 15 run, 10 killed by the existing checks, 4 survivors killed by checks added here, 1 equivalent. map-view.js `routeFrom`: kept past 300 m instead of under it (mapview '[road run] ...a fix 100 m on keeps that start'), the leg ignored ('...and so does a new leg'), a copy returned for the kept start ('...the same object'), ROUTE_MOVE_M 3000 ('...the move is 300 m, chosen') killed; a fix with no lat or a NaN lon taken survived, now killed by mapview '[road run] ...nor with a fix missing a number'. live.html: the kept start out of the map's key ('[road run] ...a fix 330 m on asks again'), the road run without the live start ('[road run] between offers ... along the road from the live fix'), the straight run without it ('[road run] with the router down ...'), the offer's trip green again ('[road run] a screened card's own trip ... teal'), the key's offer item never set or never shown ('[road run] ...and the key names both trips', and the NucBox key checks) killed; a grey (stale) fix starting the run survived, now killed by test_dashboard '[road run] ...and a fix gone grey starts no run'; the two orders' straight runs without the live start survived, now killed by '[road run] ...and with two orders in the car each one's straight run starts at the live fix'; the leg key ignoring the pickups ahead survived (the visit came at the kept start), now killed by '[road run] ...and with the restaurant behind the car, a new leg ... 100 m on' (the visit's fix moved 100 m on); the kept start keyed under a card's fix too survived and is equivalent in what is drawn (under a card the run starts at the card's fix, so it only re-keys a walk that draws the same; the map walks on that beat with or without it), left as is. Simplified, equivalent: routeFrom's `kept.at` test (kept is only ever routeFrom's own answer) and showKey's `!lines.job` (the offer's trip is keyed only beside the run).

**A door whose road the NucBox found by its spelled-out middle initial, and not the door, was never pinned (the owner, 20 Oct 21:08).** An Uber order's pickup "Outback Steakhouse (810 Ernest West Barrett Parkway)" and the Trip Planner's "810 Ernest West Barrett Parkway, Kennesaw, GA 30144": `pickupsWhy` 'no house number' (pickInDisc 'nodoor', the road inside the disc). OSM names the road "Ernest W Barrett Parkway Northwest"; Uber spells the initial out. retryWanted leaves a 'nodoor' inside the disc alone (the type word is not the trouble there). Now, exactly there (`MV.dirWanted`), a door plan with a directional word inside its name — after its first name word, so "West Paces Ferry Rd" is asked as printed — or a quadrant last is asked ONCE more with each written the other way (`MV.dirRetry`, `dirFlip`: West<->W, North<->N, East<->E, South<->S, Northwest<->NW and the other three; "810 Ernest W Barrett Parkway"), held as the type-word retry is (pickRetry: door level, inside the disc, alone or agreeing, the same street by retryFits with "West" and "W" one word under `retry.dirs`, the type's family or none, a quadrant or none); `MV.afterDir` takes it only when it pinned, else the first 'nodoor' goes on as before (the place, the short street). One rule for the held end (server.js `searchHeldDir`, through endAsk, pin `asked`, /api/status `endAsked`), the held order's pickups (searchHeldPickup, `pickupsHow[].asked`) and Map view (NbxSearch.place), the same words, so they share the server's cache. The fake NucBox's "810 Ardley West Corwin Parkway" answers the road half a mile out, "810 Ardley W Corwin Parkway" the door 3.1 mi out, and "812 ..." a house on Ardley W Corwin Circle (invented). Checks: mapview 604 -> 624 (dirRetry's 10 shapes, dirFlip, retryFits' 6, pickRetry in a 5.0 and a 1.0 mi card, the Circle, the road alone, dirWanted's 7, afterDir's 4; through the server: pinned, both questions, a store's bracket from the cache, the Circle refused, outside a 1.0 mi card); test_server 994 -> 999 ('[directional retry]' 3: pinned with `endAsked`, the Circle, outside the disc; '[server pickups]' 2: an Uber card's bracketed door pinned with `asked`, the Circle refused). Mutation testing skipped (fast lane). Open: what the real install answers for "810 Ernest W Barrett Parkway" is not measured — the NucBox runs this server.js, so it needs a pull and restart there, and the owner should check that door. Mutations (catch-up, 21 Oct): 13 run, 13 killed by name (dirFlip's letters, the opening word kept, no flip no retry, a name of directionals only, dirWanted inside the disc, afterDir only a pin, retryFits' fold, the quadrant flipped, the type held; server: no directional step, its `asked`, pickRetry's street; Map view's step) by the existing dirRetry/dirWanted/afterDir/retryFits shapes, '[directional retry]' and mapview's through-the-server check. No check added.

**The held run to Map view's own pin on a numberless street was drawn straight with the router answering (the owner, 20 Oct 21:08).** The held end was Map view's street-level pin off the card's "<Name> Creek Blvd" (no house number) and the pickup had no pin; the relay answered /api/nbx/route with a line, yet the run was straight: live.html refused the road for any point that was a numberless street's (`stretch`). The run is a drawing and no figure, and the card names that street, so it is now asked along the roads — car, the pinned unvisited pickups, the end pin whatever its level — and straight only when the router fails or a pin is one the map calls wrong (red), as before. The detour's figure to such a street stays the straight-line range (stretchSpan). Checks: test_dashboard '[held route] ...the run to it drawn along the roads' replaces "the router not asked" (one route question, for the drawing, class `mv-held-run mv-road`). Mutation testing skipped (fast lane). Mutations (catch-up, 21 Oct): 2 run, 2 killed — the `stretch` gate put back on every run point, and on the end alone, both by test_dashboard '[held route] ...the run to it drawn along the roads'.

**How often the held end was pinned was nowhere on record (the owner, 21 Oct: "measure how often pinning works").** A drop row said when and how an order went, and nothing about whether the GPS drop had a pin to arm on, so a shift could not say how often pinning works or why it did not. Now every drop row — Drop, the GPS, the chooser, a Took that replaced it, the offers page's untick, its own clock (expiredRows) — carries `end: {by, why, asked}` and `pickups: {pinned, why}` (server.js `pinOutcome`, written by `withOutcome`). `by`: 'server' (the door as printed), 'type' / 'dir' / 'rescue' (the door found by the type-word, directional or street-index retry; the pin now keeps the retry's word as `via`), 'place', 'street', 'page' (Map view's post), null for no pin. `why`: heldEndState's endWhy (with a pin, why it did not arm; without, the refusal), else 'no dropoff', 'no NucBox search' or 'still asking'. `asked`: 'door' (asked as printed), 'street' (found under another spelling of its street), null (nothing asked). `pickups`: pickupState's count and reason. Words and counts only — no coordinate, no address, no street asked, by the journal's Settled rule (rows carry ids and words). The outcome is worked out by setHeld for each order as it leaves the list (`goneOutcomes`, the last `GONE_KEEP` = 16), before its searches are forgotten, from the raw list (pickupNearEnd takes it, since heldOrders inside setHeld would write the list again). tools/shift_report.py prints a "Pinning" section: per order "end pinned by server (asked: door); pickups 1 pinned", "end not pinned: no house number …", and "Pinned: N of M orders with a record (P%)", the rate being ends pinned at all (door, place or street, whoever pinned) over the orders whose row says; a row from before the field is counted apart; a word is cut at `WORD_MAX` = 32. Checks: test_server 999→1010 with the next entry's; '[pin log]' 4 (Drop's row, no address or coordinate in it, a replaced order's refusal, an early-pinned order's row) and the '[replaced]' shape check now with `end` and `pickups`; tools/test_shift_report 131→140 ('[pinning]' 9). Mutation testing skipped (fast lane). Open: a panel untick writes no drop row, so it has no outcome; what the real shifts' rate is waits for a shift on this build. Mutations (catch-up, 21 Oct): 15 run, 14 killed by name, 1 equivalent. server 10: 3 killed by '[pin log]'; 7 survived and are killed by new '[pin log]' checks: the rescue's `via` and `asked: 'street'` on a replaced row, a page pin's `asked: null` with NUCBOX_SEARCH set, 'no NucBox search', 'still asking' over a refusal kept for an earlier text, the pickups' refusal worked out before the searches are forgotten (goneOutcomes), and the expiry row's outcome. shift_report 5: 4 killed by '[pinning]'; the pickups' reason printed only with none pinned was equivalent (pickupState gives a reason only then) and the condition is gone. The '...carries no address or coordinate' check failed once by chance on a millisecond time holding "1981"; it now leaves the row's times out. test_server +6.

**An offer's doors were asked of the NucBox only after ✓ Took, and the other screens' addresses never (the owner, 21 Oct: "search as soon as a card appears, cheaply — the NucBox does the work", and "try to capture that information from every page scanned").** Now, with `NUCBOX_SEARCH` set, the scanner's offer line starts a search of the card's pickup (`pickupLine`, an Uber "Store (<n> <street>)") and dropoff at once, inside that card's disc (`searchCardEarly`, once per card id, `EARLY_CARDS` = 32; a card read before its fix is asked on the next reading), and while an order is held every address with a house number a scanner line reports — a sighting's stops (navigation screens, the customer sheet, planner pages), the planner line's stops, a dropoff line, a place popup (`addressesOf`) — is searched inside each held order's disc (`warmEarly`), at most `EARLY_WARM_PER_MIN` = 6 NEW searches in any 60 s (CHOSEN, NOT MEASURED), the rest dropped and not queued, a text already searched in that disc skipped before it is counted. Both through `earlyDoor`, by ONE chain of questions now shared with the held end and the held pickups (`doorChain`: the door, the type-word retry, the street-index rescue for an end, the directional retry; it replaces searchHeldRetry, searchHeldNamed, searchHeldDir and searchPickupRetry, the same questions in the same order), so a later ✓ Took — the panel's or the offers page's — asks the very same URLs and finds them in nbxCache: the pin at once, no request. Map view's relay and the on-time hint (`offerPin`, which now takes the retries too) read the same cache. A question asked while the same one is still out joins it (`nbxAsking`: one request, every waiter answered, bounded by the timeout). A NucBox that does not answer leaves the text refused as nothing for `END_RETRY_MS`, so a screen re-read every second does not ask a down NucBox again each time (the held end's and pickups' own retry still runs; '[held pickups]' asking once against a down NucBox held this). Bounded: answers in nbxCache (`NBX_CACHE_MAX` 500, `NBX_CACHE_BYTES` 8 MB), outcomes in `early` (`EARLY_MAX` = 200, oldest out). A door's only — a text with no house number is never asked — never the public geocoder, and nothing written to the journal. THE NUCBOX CARRIES THE LOAD: the rig sends a few small HTTP GETs (one to three per text) and keeps their small answers; the searching is the NucBox's Nominatim and street index. Checks: test_server '[early search]' 3 (a card read searched before the Took, dropoff and pickup once each inside its disc; a re-read asks nothing; ✓ Took pins the end and the restaurant with no new request), '[early warm]' 4 (nine doors on a planner page while held: six searched, inside the held disc; the same page again asks nothing; nothing held, nothing asked); mapview 624 unchanged through the server. Mutation testing skipped (fast lane). Open: a Took whose card's fix moved the disc's box (0.01°) since the first reading asks again; the place and short-street steps of the held end are not searched early; what six a minute costs the real NucBox is not measured. Mutations (catch-up, 21 Oct): 12 run, 11 killed by name, 1 equivalent. 6 killed by '[early search]', '[early warm]' and '[held pickups]'; 5 survived and are killed by new checks: '[early search] a card the NucBox did not answer is asked once, not again on a re-read', '...a card read before its fix is asked nothing, and is asked on the next reading with one', '[early warm] a door the NucBox did not answer is asked again past END_RETRY_MS' (two: the refusal's `until`, and its expiry), and '...once the window has passed, the three left are searched' — the window is now EARLY_WARM_MS (60 s, 3 s in the suite). warmEarly's `if (!orders.length) return` was equivalent (nothing to loop over) and is gone. doorChain itself is held by the 9cddfb3/1abae08 runs above. test_server +4.

**Map view routes whatever it can, and says which rung it stood on (the owner, 21 Oct 15:00: "It would be better if the map tried to route something or anything it can").** One Uber order held, its end the card's corner, the planner's pickup read "Kennesaw" alone, and nothing was routed. The held order's run, and the offer's own trip, now go down a ladder (`MV.routeRung`, `MV.routeLadder`): the door; a street-level point (a numberless street's stretch, or a short street the server pinned) - "route to street, not door"; the corner where its two streets meet on the NucBox street index (/api/streets/cross) - "route to corner" - or, where they do not meet in the disc, either street's point nearest the car (`NbxSearch.cornerStreet`) - "route to street, not door"; and with no end that can be drawn, the car to the pickups - "route to pickup only". A pin the map calls wrong (red) or a card refuses is no rung. With no pickup pinned by Map view the server's own pickup pin is used, now on heldEndState as `pickAt` (the first not visited). The words follow the caption (`MV.routeSaid`, "trip: " for the offer's), and a chipped caption keeps its chip with them after it. **Drawing only:** no figure comes of any rung, nothing of it is posted, and GPS arrival is armed exactly as before (pinHeldEnd sends only a door askNucBox found). The offer's trip is now drawn by road to a street's point as well (it was refused before), and with nothing in the car its car -> pickup leg goes by road. Server pickup pinning was checked, not changed: a planner pickup with no street is not asked (pickupKey), and the card's "<n> <street>" (bracketed or bare, searchPlan's door) is asked as a door already (pickupAsks). Checks: mapview.test.js 627 -> 636 ('[ladder]': each rung, the points, nothing to draw, the caption's words once, a chip kept, either street off a stub relay, no corner asked as one), test_server: the held description's keys gain `pickAt`; test_dashboard: the street and corner captions carry their rung. Mutation testing skipped (fast lane).

**The rig's map route on the driver's phone: `/live.html?route` (the owner, 21 Oct: "see that map route that was created on the rig ... so when I am waiting at a restaurant I can see if any new orders would fit along that route").** Checked first: `http://<rig>:8080/` is the keypad (index.html), map.html is the parked journal map with no held run, and live.html already lays out at 390x844 with Map view (test_layout), two ⛶ presses from the phone picture and never remembered, under the panel's Took/Drop/⌖/Set box bar. So no new page and no server change: live.html opened with `?route` (`ROUTE_VIEW`) starts in Map view, hides the picture, 📷 Snap, Undo, the chooser and every bar control but ▤ Offers (`body.routeview`), and gives the map at least 52vh upright; the verdict above it says the offer's pay, minutes, miles, the pair line, the on-time hint and the same-store note as on the panel, and the map is the panel's own drawing from the same `/api/status` and `/api/events` stream (held run car -> pickup -> dropoff down the ladder with its "route to street, not door" words, pins, the live car dot, the offer's trip in teal). Read-only where every write goes: `ask()` refuses any non-GET in route view before it leaves the page, so the phone never marks, drops, chooses, snaps or pins (the panel's own Map view posts the pins it finds). Linked as ⤳ Route from the offers page and, beside ◉ Live and under the same rule, the keypad; README names the URL. Checks: test_dashboard '[route view]' at 390x844 and 360x640 (Map view from the first frame, no picture, no 📷, only ▤ Offers; the held run by road; the map at least 45% of the height, no sideways scroll; the offer's road trip `#2dd4bf` beside the run with its pay above; no POST left the page, the held pickup's pin included), test_layout unchanged and green with the new links. No mutation run (fast lane). Open: the phone's car dot is the rig's GPS, so it is where the car is, not the phone.

**Two door answers a few hundred metres apart routed nothing (the owner, 24 Oct: "It is better for the map to route even if it is not exact as long as it gets the general area right for the use case of trip planning").** An Uber order held, its card's fix ±26 m and disc 14.9 mi, the Trip Planner's door "<number> <Name> Mill Rd SE, Marietta": the NucBox answered two doors of that number inside the disc, drawn as two circles almost touching, `pickInDisc` refused them `several` (two doors are not one place at `AGREE_MI`), the hat said "NO PIN · …, 2 fit its card and disagree", /api/status `endWhy: 'several answers'`, and nothing was routed. **The owner's decision:** for routing and trip planning, a door plan's `several` or `nodoor` refusal now carries `area` beside it (`withArea`, map-view.js) when EVERY candidate inside the disc is within `AREA_MI` (1 mile, chosen not measured: with two answers the middle is at most `ON_WAY_MI` from either; the same as `STREET_AGREE_MI`) - their `middleOf`, `approx: true`, `n` and the spread; `at` stays null and the `why` is kept. Never for `none`, `capped`, `together`, a corner, a merchant's name, a place by its name or no disc. Map view's run takes it as a new rung, `area` (`routeRung` says it before street or door), drawn to by road with a faded "≈" ring (never D); where the caption is that end's own refusal the area's words take the disc's figures' place in it (`routeSaid`'s `about`: "no pin for … — 2 fit its card and disagree · ≈ routed, 2 within 0.3 mi", chip "NO PIN · …, ≈ routed, 2 within 0.3 mi" - with the words after the disc's tail instead, test_layout measured the sentence past two rows at 800x480 and the chip past three on the hat), else a note after it, "≈ route to area, 2 within 0.3 mi" ("trip: …" for the offer's own dropoff); the candidates' tips say "≈ routed to the area, not a door". No figure is measured to it: the detour's refusal stands as it was. **THE SAFETY LINE: the GPS drop stays door level.** The area is never a pin: not in `found`, so never posted (`pinHeldEnd` needs `got.at` and `/api/held-end` refuses anything not door level); on the server it is kept apart as `endArea` (refuseHeldEnd), never `endPin`, so `heldEndPin`, the restaurant guard, the customer guard and the drop row's `pinOutcome` never see it, it never replaces a door pin (pinHeldEnd and the page's post delete it), and `endWhy` still says why the drop is not armed ('several answers', 'no house number' ...). heldEndState carries `endArea` (null with a pin, or for another dropoff text) for Map view's run, which falls back to it when its own search has none. Checks: mapview.test.js '[area]' (two doors 0.33 mi apart: no pin, `several`, area at middleOf; 2.5 mi apart and a third past AREA_MI: no area; none/capped/corner/merchant/no disc: no area; `nodoor` inside the disc: area, outside: none; the refusal's words unchanged; the rung, the note, the caption's words and chip, a note about another place, the trip's note, the tips, and through the server: the area beside `several` and kept past the place search), one Kestrel tip updated (its street now carries an area); test_server '[area]' (endArea kept and approximate, endPinned false, endWhy 'several answers', the area posted as the end refused 'not door level', a car waiting there and leaving arrives nowhere and drops nothing, 2.5 mi apart keeps none); test_layout: two caption forms, several at the rung's widest words and a street's one answer, measured and chipped (table 103 -> 105, declared tails 45 -> 47); test_server: the held description's and the beat's keys gain `endArea` (null beside a pin). tests/fake-nucbox.js gains invented "3150" / "3152 Thornbury Mill Rd SE". Open: with two orders in the car the run through both does not use an area; no figure is stated to an area (refused as before) - an approximate detour figure would be a new number on the panel and was not built. Mutation testing skipped.

**Trip Planner page 2 replaced page 1 on the hold, losing a batched trip's pickup, and the map's run skipped the first door (the owner's snap, 24 Oct 03:03–03:04).** One trip, ONE pickup ("Pickup • 2 orders"), two dropoffs. Page 1, read whole and scrolled: the pickup with its full door, customer A's dropoff by 3:23, customer B's header and nothing under it. The later reads were B's dropoff alone, then A and B. server.js put each read's stops on the hold IN PLACE of the last, so `holding.planner.stops` lost the pickup. pickupAsks (MV.heldPickups over those stops) then asked only the card's store by name ('several answers'), and Map view's run went car → D (B's door, armed) past A's door. **The rule, part 1 (`Assemble.mergePlanner`, called by the planner branch in server.js for every UNPRESSED read landing on a hold that keeps a planner):** a stop of the newer read and a kept one are one stop by keyOf, by kind and name with times that agree, or by kind and street (sameStreet) with no clashing name. Its header words come from the newer read where it printed them; its address block comes WHOLE from the fuller read (addressConf, the newer on a tie), as mergeStop does; a pickup's `of` is kept. A kept stop the newer read does not show is kept in place, next to its nearest kept neighbour still in the list. Two reads with nothing in common are ordered by their times (the kept read's last "Expected by" against the newer's first, midnight unwrapped). With no times, the newer goes first if its page shows the top, otherwise the kept goes first. Where two reads meet, a header with nothing under it and the stop beside it become one stop. So do two stops in one slot due at the same minute with doors that do not differ (a misread name). A kept header that is matched to nothing is left out. A newer read that shows the list's TOP (pageOf) drops the kept stops above its first stop, such as a pickup swiped or a door delivered. One that shows the FOOT drops the kept stops below its last. The planner line carries the merged list as `held`, and live.html's heldPlan and plannerSaid read it, so the live panel and a reload match. The line's own `stops` are still the page as read, and they are what the journal row and plannerVisits get, so a visit is still the app's word off one read from the top. Unchanged: which stop is the end (dropoff(), batchPlan, label and press rules work off the sightings, never the hold's stops). Also unchanged: a read answering a ⌖ press (`asked`) is kept as read, because the press forgot the planner first (forgetPlanner) — superseded the same day, see the next entry; forgetPlanner on a different offer; and a new order starts with no planner, since the merge lives on the hold. **The rule, part 2 (`MV.heldDrops`, `MV.dropPoint`, `MV.routeLadder`'s fifth argument; live.html mapWants/showMap/drawMap):** with ONE order in the car whose planner lists more than one dropoff, and exactly one of them on the end's street (Assemble.sameStreet's rule, restated in map-view.js because the page does not load assemble.js), the run is car → unvisited pickups → each dropoff listed BEFORE the end, in planner order → the end. Each is searched by NbxSearch.place in the HELD card's disc, a door by its number, otherwise its answers' general area (withArea, AREA_MI). Each is drawn as an amber ring, D1, D2… by its place on the planner, faded when it is only an area. One with no point, including a dropoff with no street (never searched by its name), is left off the line, and the caption says "route skips N dropoff(s), not found" (ROUTE_TAIL, so the chip keeps it). Only where the end is drawn; never with two orders in the car (MV.heldRuns' run); dropoffs after the end are not on it. DRAWING ONLY: they stay out of `names` and `found`, so nothing posts them (pinHeldEnd, pinHeldPickup), nothing figures them (detourThrough still gets the pickups alone), the public geocoder never sees them, and they are no door pin and no restaurant guard. **The GPS drop is untouched:** it arms on the end's door pin alone (/api/held-end refuses the first door, 409), and a car that waits at that door and leaves drops nothing (test_server '[planner pages]'). Settled stands: no pace, no minutes, no figure from the extra stops, no new bar control, nothing pressed on the phone. Checks: assemble.test.js 486 → 510 ('[planner pages]'), mapview.test.js 660 → 671 ('[batch run]'), test_server 1115 → 1121 ('[planner pages]': two pages merged, the end still the card's; the pickup that only page 1 showed is asked and pinned at a restart with the NucBox up, after page 1 was read with it down; the first door refused as the end and not arrived at; the next order's planner merges with nothing), test_dashboard 1397 → 1402 ('[batch run]': the road run through the placed dropoff, D2/D/P, the skip said, nothing about those doors posted), test_layout 4370 → 4378 (one caption row, the figure with the skip tail; the table's own counts 105 → 106 and 47 → 48 declared tails, because the row was added). No existing check changed its expectation. Open (the first three closed by the next entry): a ⌖ press still starts the planner fresh (forgetPlanner), so a press on page 2 loses page 1's pickup as before; the dashed detour leg of a stated figure still goes from the last pickup straight to the end, not through D1; delivered dropoffs leave the merged list only on a read from the top; the D1/D2 marks share letters with two orders' D1/D2 (never on one map: the drops are only drawn with one order). Mutation testing not run (fast lane).

**The ⌖ press merges too, the detour's dashed leg runs through D1, and a door the car has been to leaves the run (the owner, 24 Oct: "Would there be a way to have the scan button also merge?").** The three open items above. **1. A press merges (Assemble.mergePlanner's fourth argument, `pressed`; server.js's planner branch passes `read.planner.asked === true`).** /api/dropoff no longer calls forgetPlanner, so the held planner survives the press and the press's planner read merges into it by the same rules — matching, kept stops in place, the header-and-slot joins, the top / Waybill trims — with ONE difference, PRESS PRECEDENCE: for a stop both show, the pressed read's fields win wherever it read them, and its address block comes whole from the pressed read whenever it read any of it (`hasAddress`), not from addressConf's fuller read; the kept field stands only where the pressed read has nothing. A stop the pressed page does not show is kept. forgetPlanner stays for its other moment, a different card on the record (server.js, the offer branch). live.html: the ⌖ button still forgets its green answer at the press (forgetDest), but with an order in the car it puts the held planner stops back (`plannerSaid` kept, redrawn where they were drawn), and the answer's `held` list is what lands after it, so a reload between the press and its answer, or after a press that read an address, shows the same stops as the live panel. The reason none was filed stays the last read's. **2. The dashed detour leg (MV.detourOnward; drawMap's `gap.to` line).** Where the figure puts the new pickup after the held order's last pickup (detourThrough's `to` is the end), the dashed line from the pickup runs through each placed dropoff still ahead, in planner order, to the end. A gap that rejoins at a held restaurant is the one leg it was. DRAWING ONLY: the stated figure is still detourThrough's / NbxSearch.detour's, measured pickup → end; no mile is measured to a dropoff and no number on the panel moves. **3. A dropoff passed (MV.dropPassStep, DROP_NEAR_MI 0.1, DROP_LEFT_MI 0.2, MV.dropsAhead; live.html dropsPassed / dropSpots / stepDrops).** On each GPS beat whose fix is a good one (hereDot, not refused or grey), each dropoff the last Map view walk placed (door or area) is stepped: within 0.1 mi it is `near`, and a `near` one the fix is then more than 0.2 mi from is `passed` — both chosen, not measured (a door and its kerb past a ±25 m fix; twice that to leave, so a fix wandering at the edge does not call it left). A passed dropoff is off the run and off the dashed leg (not "skipped": done), and its mark reads "D1 ✓", faded. Page memory only, keyed by the order in the car and the stop (dropPassKey: hold + the stop's line + name), so it survives the status poll and a new hold does not inherit it; a reload forgets it. Never told to the server: the hold, its planner, the GPS drop and its door pin are untouched. Settled stands: no $/mile, no floor, no pace re-timing, no heat map, no silence as accept, no new bar control, nothing pressed on the phone. Checks: assemble.test.js 510 → 515 ('[press merge]': page 2 pressed keeps page 1's pickup; the pressed door wins whole over a fuller kept one, unpressed the fuller stays; the kept time and door where the pressed read has none; top and foot trims; nothing kept), mapview.test.js 671 → 679 ('[detour via drops]': the figure still to the end, the leg through D1 and D2, unplaced left out, a restaurant gap unchanged; '[drop passed]': the two distances, near-then-far, far alone, near alone, the edge, once passed stays, grey/refused/no point, the run and the leg without it), test_server 1121 → 1124 ('[press merge]': a press keeps the merged pages, its read merged with page 1's pickup kept and the pressed door winning, the reason the press's, the end the card's), test_dashboard 1402 → 1404 ('[drop passed]': at D2's door with the pickup made, then 0.41 mi on: car → end along the road, "D2 ✓" beside D). **Existing checks changed, each because it pinned the press forgetting:** test_server 'a ⌖ press takes the last planner off the order' → keeps it, and the reload after the end was read shows the end AND the stops (the old "not guessed" beside a green button stays off: unfiledNow says nothing once the order has an end, test_dashboard 'reloadedEnd'); test_server 'the order in the car carries the stops last read' → the presses' stops merged (Sam R. at Pat Q.'s door and minute is a stop of its own, two names); test_server '[carry two] one planner listing both orders sets the run order' → a different card on the record between its three planners (the moment that still forgets), since a pressed read leaving an end out no longer takes it off; test_server '[carry two] ...the stack line on the reading is against both' → within 0.1 of 25.0, because each leftEach is rounded to 0.1 on its own and the two added cards moved the reading to a second where the sum sat a tenth off; test_dashboard 'a press forgets what the last one read' → forgets the green answer and keeps the held stops, in the same turn and after the tick. Open: with the router's road for the figure (`road.line`, NbxSearch.detour's chosen gap) the dashed road still goes pickup → end along the road it was measured on, not through D1 — redrawing it would draw a road nobody measured, or ask the router again for drawing; only the straight legs go through D1. A passed door is a guess off the fix: a car that drives within 0.1 mi of a door it is not stopping at marks it done until a reload. test_layout not changed: "D1 ✓" is a mark's letter, not caption words (it overhangs the 26 px letter box a little; not measured). Mutation testing not run (fast lane).

**Review of 235e3ec..912dc8c (27 Oct): ten findings fixed (fast lane).** (1) `Assemble.mergePlanner` kept one stop twice when its "Expected by" moved between reads (samePlannerStop wanted timesAgree): a second matching pass (`sameDoorStop`, after every exact pair) makes the same kind on the same street with no clashing name one stop whatever the times, and a read showing the list's top AND its foot is the whole list (kept stops it does not show go; matched ones merge as before, press precedence included). (3) `slotJoins` no longer makes two NAMED customers due the same minute in one slot one stop; only a name one read lost joins. The existing check "one slot ... one stop, the newer read's name" (Mara/Jules, no doors) changed for that reason: it now asserts the two are kept, and a lost name joins. (2) live.html's Map view key carries the server's endArea as its rounded point and band flag, so a later band (bandHeldNow) walks again. (4) `NbxSearch.band` spends one BAND_WAIT_MS per walk in all (`budget.waited`, the bands' own waits only), so a hanging router delays the settled draw by one wait, not one per band. (5) tools/places_nightly.sh runs the report under `timeout` (PLACES_TIMEOUT, default 10800 s), opens the lock to append and stamps it on taking it, and a lock held past the limit is logged stuck, exit 2. (6) places_report.js counts fresh NucBox questions and the unanswered (`cache.asked`/`unreachable`); past 20% and 50 it writes nothing and exits 1 (`--allow-degraded` writes, said); failures were already never cached, now checked. (7) RIG_GPSLOG gets its trailing slash, ssh's words are an array (rsync's -e quoted with printf %q), a RIG_HOST starting with '-' is refused. (8) `pickInDisc` keeps a cut list's doors with the asked number for its area and band candidates where any are there; tests/fake-nucbox.js's Vessington lists now start at 10802/10902 (neighbours, never the asked door) so the existing cut-list checks keep meaning "all of them". (9) mapview.test.js holds MV.heldDrops' street rule to Assemble.sameStreet over 20 x 20 invented lines. (10) offer_parser.py `_planner_trim` strips [\s,] as the JS twin does; a shared planner case in cases.json pins it (both ports already agreed on it: no case found where the old trims gave different stops). Checks: assemble.test.js 515 → 521, mapview.test.js 733 → 738, corpus.test.js 1565 → 1567, test_parser 1645 → 1647, placesreport.test.js 279 → 292, test_dashboard 1407 → 1408 ('[area key]'), test_server 1173 (one expectation changed by (3): the '...and one that changes the stops writes them' read now keeps Mara T. beside Jules K.), test_layout 4520 and test_lint 365 unchanged. Each new check was seen to fail with its fix taken out. Open: the band wait is shared, not raced (bands still run one after another, so a slow-but-answering router can starve a later band); a pickup at one store for two orders whose times differ and that the newer read lists once is merged into one stop by (1).

**DoorDash doors routed nothing where the map had found their area (the owner's snap, 24 Oct, 19:23–19:25: "Seems to have trouble reading the doordash pins, the areas it highlighted was generally right. It is better to route something than nothing at all.").** DoorDash offer cards on screen, not yet taken, each card's pickup door printed. (a) "10495 <Name> Street, <Town>": the hat said "NO PIN · 10495…, none found" — the NucBox answered nothing for the door or for it with the type word left out. (b) "10800 <Name> Hwy, <Town>": "NO PIN · 10800…, too many to be sure" — the list cut at the NucBox's limit (`capped`), though the map drew what it held as a tight cluster in the right place. **The owner's decision, for routing only, on 7972d72's safety line:** (1) `capped` now carries `area` (withArea, `cut: true`) when every candidate the cut list holds inside the disc is within `AREA_MI` (the same mile: a cut list is less to go on, so it earns no wider spread), said "≈ route to area, 10+ within 0.3 mi". (2) A door plan whose answer after every retry (streetRetry, dirRetry, the index's name) is `none` asks ONCE more, for the STREET alone: its name as printed less the house number (`nameAsked`), of the street index (`/api/streets/whole` in the disc's box — searchHeldStreet's own question, so page and server share nbxCache; not the search again, which had just said it holds nothing of that name; no index, nothing asked; never the town). `MV.streetArea` takes it only where the index reads ONE name, no street of it in the box is too long to be sent whole (WHOLE_LINE_M, 2 km: a long street is no one area, and its piece nearest the disc's centre was NOT taken — the centre is the car, not the door), and every point of the streets that reach into the disc lies within `ROUGH_AREA_MI` (1.5 mi, chosen, not measured: one street sent whole, ≤1.24 mi, always fits; two of one name only as one neighbourhood's). The point is on the street nearest the middle of its points, `rough: true`, said "≈ route to street area". (3) Where it applies: the new offer's own pickup (the snap's case; areaEnd, routed car/pickup area -> dropoff, a faded green "≈" ring, never P) and dropoff, the held order's end (server.js settleHeldEnd -> `searchHeldStreetArea`; `endArea` keeps `cut`/`rough`, areaKept), the held order's pickups PAGE-SIDE ONLY (live.html: the run goes through a pickup's area only where every pickup is a door or an area; never posted — pinHeldPickup sends `got.at` alone — so never `pickupPins`, never the restaurant guard; the server's own pickup search is unchanged and keeps no area, no `pickupAreas`), and intermediate dropoffs (dropPoint already took any `area`). (4) Words: in an end's own refusal (`routeSaid`'s `about`, now [place, note, area] per end, so one end's area is never said in another's refusal; a cut list's "· the NucBox lists 10 at most" goes as the disc's tail does): "no pin for 10800… — too many to be sure · ≈ routed, 10+ within 0.3 mi", chip "NO PIN · 10800…, ≈ routed, 10+ within 0.3 mi"; "… — none found · ≈ routed to street area". A pickup's area is said ONLY in its own refusal ("≈ pickup area" after another end's refusal and its disc's tail, and the two longer forms before it, each ran past two rows at 800x480 and the chip past three on the hat); elsewhere its ring says it. **Untouched:** never in `found`, never posted, never `endPin`/`pickupPins`, never the GPS drop (a car waiting at either area and leaving drops nothing), never the restaurant or customer guard, no figure (the detour and the card's line refuse as before); Settled stands. Checks: mapview.test.js 679 -> 701 ('[area more]': capped compact -> area, cut, its middle; capped spread, no disc, a merchant -> none; words, chip, another end's area kept out; streetArea short -> rough on the street, long, two apart, outside, no disc, two names -> none; through the server: Pellmore's area beside `none` asked once as /whole, Dunmere none, no index never asked, the cut list's area) — one existing check changed: "[area] never for … 'capped' …" now uses the spread pair (3152), because a compact cut list is now an area by this decision; test_server 1124 -> 1130 ('[area more]': cut end area kept, endWhy 'too many answers', no arrival; street end area rough, asked once, no arrival; long street none; a held pickup on the cut list pins nothing, `pickupsWhy` 'too many answers', no `pickupAreas`); test_dashboard +1 ('[area more]' the snap's pickup on the panel: no P, one faded ring, "≈ routed, 10+", nothing posted) and two expectations updated because the offer's own pickup is now routed to its street's area: Jimmy John's caption ends "· ≈ routed to area" and its candidate's tip is compared without it; test_layout: three caption rows (cut list routed; none fit / none found routed to street area), table 106 -> 109, declared tails 48 -> 51. tests/fake-nucbox.js gains invented "10800"/"10900 Vessington Hwy" (ten cut, 0.3 mi / 3.5 mi apart) and, in its index, "Pellmore Street" (369 m) and "Dunmere Parkway" (3.7 km). Open: with an order held and the new offer's dropoff unplaced, its pickup area is not routed (the trip leg needs an end, as before); the held order's pickup areas are Map view's own search only (the server keeps none to send); the snap's real streets were not checked against the real index. Mutation testing skipped (fast lane).

**The distance band: the card's own miles, by road, among a refused door's candidates (the owner, 25 Oct: "Go ahead with the distance band").** Until now the disc (discFor: the card's miles + SLACK_MI, in a straight line from the card's fix) was the only distance a search held its candidates to, and it throws out only what is too far. The card says more: Uber prints the drive to the pickup (`toPickupMiles`) and the trip, DoorDash the whole job ("2 stops (2.5 mi)", car → store → customer). **The owner's decision, for routing and drawing only, on 7972d72's safety line.** (1) Where a door's search ends with several candidates and no pin — `several`, `capped` (with or without its cut-list area), or `none` with its street's pieces in the disc (a street too long for streetArea above all, or a short one) — the NucBox's router is asked the ROAD miles from the right origin to each candidate (a `none` street's points are its stretch of the street index in the disc's box, sampled every `BAND_STEP_M` 150 m, wider to stay within ten), and the candidates whose road miles sit within `bandMiles` of the card's target are kept. **Targets (MV.bandTarget), from printed figures only:** Uber pickup — from the card's fix (cardFix, the gate's fix; a disc's rough centre is not an origin), `toPickupMiles`; Uber dropoff — from the placed pickup (a door, or a band answer of ONE survivor: live.html bandOrigin), the trip: its own printed leg (`legDetail`) else `miles` − `toPickupMiles`; DoorDash pickup — from the fix, `miles` as an UPPER bound only (the road to the store is no longer than the road through it to the customer); DoorDash dropoff — from the placed pickup, `miles` less the road from the fix to that pickup; **the held order's dropoffs between** (MV.heldDrops) — from the held card's fix, `miles` as an upper bound ('any': no figure on the card is the road to one of them, but none is further by road than the whole job; a tighter target was not defensible, so none is used). A card of neither shape (one leg, cardYardstick's 'shape'), one judge() would not vouch for, a doubted one, an early look, no fix or no placed pickup: no band. (2) **`bandMiles` = max(`BAND_MIN_MI` 0.4 mi, `BAND_FRAC` 15% of the target), CHOSEN, NOT MEASURED:** the card rounds to a tenth; the app's road is not OSRM's fastest free-flow road; the fix is seconds off the platform's measurement (unmeasured, as cardYardstick says); a placed pickup is a door, not the kerb the app measured to. (3) **The band's area (MV.bandPick):** where what is kept is one general area (AREA_MI) AND something was thrown out, `{approx: true, band: true, n, miles, cardMi}` at the kept candidate nearest their middle (a door or a point of the street, never between two); said "≈ route to area, by card's 0.7 mi" — in its end's own refusal "… · ≈ routed, by card's 0.7 mi", chip "NO PIN · <place>, ≈ routed, by card's 0.7 mi" — and its ring's tip "the answer the card's miles by road fit, not the door". Nothing thrown out, nothing kept, or what is kept still spread: no band, and what was there before stands (the earlier area, else the refusal). Even ONE survivor is an area, never a pin. (4) **Asking (map-view.js NbxSearch.band, bandStreet; server.js bandHeldEnd, bandHeldNow, bandAsk):** the relay has no OSRM table service (`/api/nbx/table` is "no such NucBox endpoint", and none was added), so each candidate is one two-point route question — the page through /api/nbx/route and its cache (NbxSearch.road, as the detour asks), the server through roadLegs (`overview=false`, nbxCache). Bounded: at most `BAND_ASKS_MAX` 10 candidates a stop (more, no band), `BAND_CARD_ASKS` 24 road questions a Map view walk (live.html `bandLeft`), and `BAND_WAIT_MS` 4 s for the answers before the band is given up — router down, refusing, slow, or an origin moved past SNAP_MI to reach a road: no band, silently, today's behaviour; the panel never waits on it (the walk's other steps are unchanged; a candidate with no road or moved past SNAP_MI is simply not kept). (5) **Where it applies:** the new offer's own pickup and dropoff (live.html areaEnd's new `band` argument), the held end page-side and SERVER-side (settleHeldEnd → bandHeldEnd: the candidates are kept in memory on the end's search, `endSearch[id].bandCands`, until the order has exactly one pickup pin to measure from — keepPickupPin asks again — then asked once; the area is `endArea` with `band`/`cardMi` via areaKept, beside the refusal, whose `endWhy` stands; searchHeldStreetArea asks the long street's stretch for it the same way, through bandAsk, never endAsk, so an index not answering is no band and never "NucBox down" over a refusal already made; the page prefers the server's band over a plain area of its own), the held pickups page-side (Uber's `toPickupMiles` with one pickup, else the upper bound), and the dropoffs between (MV.dropPoint takes `bandArea` before `area`, `band: true`). The held card now keeps `toPickupMiles` and `stops` (server.js CARD_FIELDS) so the server and the page can set its targets. **Safety, as every area:** `at` stays null, the `why` is the refusal's, never in `found`, never posted (pinHeldEnd, pinHeldPickup send `got.at`), never `endPin`/`pickupPins`, never arms the GPS drop (a car waiting at the band's area and leaving drops nothing — test_server '[band]'), never the restaurant or customer guard, no figure. **NO CIRCULARITY:** the band chose its point BY the card's distance, so no figure or check of the card's distance or the detour is ever measured to it — every one reads `at`/`found`, which the band never writes (mapview '[band] no circularity'). **Distance only: the router's metres, never its seconds — no pace, no drive time, NO PACE RE-TIMING.** Settled stands: no $/mile rule, no payout floor, no heat map, no silence as accept, no seventh bar control, nothing pressed on the phone. The server's door pins and GPS rules are untouched. Checks: mapview.test.js 701 → 725 ('[band]': the width; the targets per app and stop, none for a one-leg, doubted, early or fixless card; Thornbury 3152's two doors as candidates; Uber pickup 0.7 keeps the near door as a band area, two two-point questions from the fix; its words and chip; Uber dropoff from the pickup; no pickup nothing asked; DoorDash pickup's ceiling drops the far door, a ceiling over both is no band; DoorDash dropoff less the road to the pickup; none survive → unchanged; a spread cut list stays spread, a 0.3 mi ceiling makes it one area; Dunmere Parkway's long stretch sampled, an area where the street crosses the card's 2.0 mi; sampling bound; no street index no ask; router down, router slow, budget spent → no band; a pin, a corner, a merchant → none; no circularity), test_server 1130 → 1136 ('[band]', router up: no area until the pickup is pinned, then the band's area at the near door, `band`, `cardMi` 0.7, still no pin and `several answers`, asked as two-point routes, waiting there and leaving drops nothing; router down: nothing kept), test_dashboard 1405 → 1406 ('[band]': a new Uber offer's pickup — no P, one faded ring said as the band's, "by card's 0.7 mi", nothing posted), test_layout: three caption rows (several, a cut list, a long street, each "≈ routed, by card's 88.8 mi"), table 109 → 112, declared tails 51 → 54. No existing check changed. tests/fake-nucbox.js: its stretch of the invented "Dunmere Parkway" is now one piece 5.4 mi due north of the Square (the fake router was already a quarter over the crow line). Open: with OSRM's table service behind the relay one question could replace up to ten; the held end's band waits for exactly one pickup pin (two pickups, or none pinned, no band) and is asked once per candidate list; a DoorDash target leans on OSRM's road to the pickup being the app's; held pickups' bands are Map view's own (the server keeps no pickup area); the card's `legDetail` is not kept on the held card, so the held trip is `miles` − `toPickupMiles`; the snap's real streets were not checked against the real router. Mutation testing skipped (fast lane).

**DoorDash's map label, read as a best guess at the customer's end, for drawing only (the owner, 27 Oct: "reading the doordash icons still doesnt seem to work if a best guess can be used for the map").** The case: "$11.45 incl. tips / 2 stops (13.1 mi) · 41 min / <Store> / <n> <Street> Southeast, <Town…> / Customer dropoff". DoorDash's map above the card draws the route car → store → customer and labels the customer's street in a white-on-black rounded label ("<n> <Name> Ave NE"; an earlier snap "<n> <Name> Pkwy"); the rig read only the card box, so the offer's dropoff was "Customer dropoff", unknown, and the map routed nothing past the store — the open item left by the 22 Oct cut-door entry above. **The reader (rpi/scan_pi.py `read_map_label`, `MapLabels`):** on a reading that is DoorDash's offer card (`OP.screen_type` 'dd.offer') with a payout and no dropoff (`wants_map_label`), locked and on the record, once per offer id, AFTER that offer's own line is out, on a thread of its own (never the card reader's, never the camera loop's; inline under --no-thread): the screen box warped straight from the read's own frozen corners (`PL.warp`, the frame the read used), the band of it from 6% to 62% of its height (`MAP_LABEL_BAND`; ends at a drawn card box's top where that sits inside it); skipped when the band's mean grey is under 90 (low light, a dark-mode map) or over 35% of it is near black; near-black pixels (brightest channel < 80, channel spread < 40, so a red route chip is none — HSV saturation was tried and a tinted snap's black pills read as saturated), opened to drop the route's thin line, holes filled, and the rows wide enough to be a pill kept: 1.8–8% of the screen's height, at least 2.5× as wide as tall and 15% of the screen wide, with white text inside; each box deskewed (`minAreaRect`, ≤ 8°: on the real 19:24 snap the un-deskewed read was "…Prwy"/"…Pewy" for "…Pkwy"), cut in from its rounded ends, inverted, scaled to 70 rows and read by tesseract as one line (psm 7); biggest first, at most 3 boxes, never past `MAP_LABEL_CAP_S` 1.5 s; a box at the screen's left edge is `clipped` (the street alone), at the right edge not read. Its answer is told on a SECOND offer line for the same id (`mapLabel`), and later lines for that id carry it. The offer line also now carries DoorDash's printed `stops`, which server.js's CARD_FIELDS and MapView.bandTarget's DoorDash targets read and which the line had never carried (so the DoorDash bands of 25 Oct could not fire off a real offer line). **The parser rule (twins `map_label` / `mapLabel`, shared cases `mapLabels`):** "<house number> <street words>[ <type>][ <quadrant>]", no town; the number DC-fixed with a real digit, never 0 or a leading 0; words letters or an ordinal; a type from STREET_SUFFIX with the planner's "Or"→"Dr" and "P"/"PI"→"Pl"; with no type two words of three letters; refused: ":" "$" "(" ")" "+" "·" and other marks, the app's words (Uber, Decline, Accept, Customer, dropoff, stops, min, mi, …), a one-word street, a number and no street, the card's own store name or door; `clipped` drops the number. **Placed and drawn (server.js `dropoffGuessOf`, map-view.js `guessDisc`/`guessOf`/ROUTE_NOTES.guess, live.html):** the server keeps it on the offer as `dropoffGuess` {line, from: 'dd map label'} — only on a DoorDash card with no dropoff of its own, carried across re-reads, the raw `mapLabel` dropped. Map view, with a pickup placed (a door, or its area) and no dropoff, searches it as a door on the NucBox inside the card's disc ROUND THE PICKUP (the whole job's miles + SLACK_MI, on a card judge() vouches for, not doubted, not an early look); several answers are chosen among by the distance band for DoorDash's dropoff (`bandTarget(card, 'dropoff')`: the job less the road from the fix to the pickup, from the pickup); the point (door, band area or area: `dropPoint`) is ALWAYS approximate: a faded "≈" ring, never D ("≈ where DoorDash's map labels the customer — a best guess, not the door"), the run pickup → it dashed teal (car → pickup → it where no pickup pin draws the car's leg), said "trip: ≈ from DoorDash's map" (not after a refusal already carrying an area's words: with both the caption ran past two rows at 800x480). **THE SAFETY LINE: DRAWING AND ROUTING ONLY.** Never `dropoff`, never in `names` or `found`, so never a figure's point: no detour, miles or minutes are measured to it (mapJudge reads `found`), never posted as a pin (pinHeldEnd, /api/held-end), never the GPS drop's, never the restaurant or customer guard's, never a hold's end — CARD_FIELDS and Assemble.cardFields leave it out, and a Took on a guessed card holds no end from it (the hold's dropoff comes from the post-accept screens as now); with an order in the car the pair row, its `said` and the reading's stack are the same with it as without (test_server). No pace, no minutes, no re-timing; Settled stands: no $/mile rule, no payout floor, no heat map, no silence as accept, no seventh bar control, the rig never presses the phone. NucBox health logic untouched (the snap's ECONNREFUSED street index is an ops matter). **On the real snaps (local only, not committed):** the 19:23 set's full phone pictures, cropped to the screen: the clipped "…0 <Name> <Name>" label read as "<Name> <Name>" clipped; "<n> <Name> <type>" and "<n> <Name> <type>" both read exactly, 40–230 ms here; no false label on any of the 24 snap images (card crops, panels, camera thumbnails). The 27 Oct snap's own camera picture is 480×360 (the label's text ~4 px tall): a box is found and nothing reads — the rig's full-resolution frame is what this is for, and it was not available. Checks: test_parser 1619 → 1645 / corpus.test.js 1539 → 1565 (26 mapLabels cases), test_scan_pi 575 → 597 (synthetic map screens: the pill read, a tilted one deskewed, one box among route, bubble, red chip and Accept bar, no label, the left edge clipped, the store refused, dim / whole-screen / no corners not looked at, the cap, a throwing OCR, the card box's top, wants_map_label, MapLabels once-per-offer on its thread and inline, the offer line's mapLabel and stops), test_server 1143 → 1151 ('dd map label': kept as dropoffGuess, carried across a re-read, none without a label / on an Uber card / on a card with its own dropoff, the pair row's verdict, worst and said the same with it as without, a Took holds no end from it), test_dashboard 1406 → 1407 ('[dd map label]': a faded "≈" ring at the guessed door, never D, the store still P, the caption the same but for its note, nothing posted), mapview.test.js 725 → 733 ('[guess]'), test_layout: two caption rows (table 112 → 114, declared tails 54 → 56; the two counts are the only existing checks changed). The offer line's new `stops` and `mapLabel` keys changed no existing check. Open: the label's position (which end of the route it marks) is not read, only its words, so a label naming the store is refused by name only; a dark-mode map is not read; with no pickup placed nothing is searched; the guessed end is the page's alone (the server searches nothing for it); the real full-resolution timing on a Pi 4 is not measured (the cap bounds it). Mutation testing skipped (fast lane).

**An Uber add-on's door was searched in a disc the size of its increment (the owner's 26 Oct shift, order #5: "+10 min", "+0.4 mi" onto #4, going to #4's own door).** MV.discFor took the add-on's 0.4 mi as the trip: a disc of 0.9 mi round where the add-on came up, and the door, where the car was at the Drop, 2.3 mi from it; #4's own disc (11.9 mi round its card) held it at 2.4 mi. And MV.cardRefuses would have called any right pin for an add-on's pickup past 0.4 mi wrong. **Changed:** server.js cardOf sets `addon: true` on an add-on's card only (isAddOnCard); MV.cardYardstick says `addon` for it (no yardstick by itself, with words on the map for 'new' and 'held'); and MV.discFor(card, base) for an add-on is the base disc's centre and its miles plus the increment (every stop of the joined trip is on a route no longer than the two together from where the base order was offered), server.js heldDisc giving the base: the order taken just before it on the same trip (tripOf), grown in turn when it is an add-on too. With no base held, or no increment it vouches, the add-on's own fix with no yardstick (the sixty-mile disc, a candidate still used only alone or when all agree). Every held-order search (searchHeldEnd, the pickups, warmEarly, the cue search, endWhy's `asked`) asks heldDisc. live.html's own walk still asks MV.discFor(heldCard) with no base, so an add-on's end is searched there in the wide disc, not the grown one. And tools/shift_report.py: an add-on (its Took's mark, its drop row or its card's `addon`) prints its card minutes and miles as "+10", "+0.4", carries a note, and is left out of every actual/card minutes ratio and of the card-minutes bands (counted by app for n and $/hr), the summary saying how many. Checks: tests/mapview.test.js +8, tools/test_shift_report.py '[add-on]' +8, rpi/test_server.py '[add-on disc]' +1, rpi/test_layout.py two caption rows for the new 'addon' words (the table's count 114 -> 116).

**The map label "<n> <Name> Pkwy N..." went unread on a DoorDash card read perfectly, so the offer had no dropoffGuess (the owner's snap of 2 Nov 16:31: "Here is another door dash page being read and failing to route, why did it not map it?").** The card: "$4.60 incl. tips / 2 stops (3.0 mi) · 22 min / <Store> / <n> <B> Pkwy, <Town>, <ZIP> GA / Customer dropoff", every read complete; the phone's map labelled the customer "<n> <Name> <Name> Pkwy N..." (DoorDash's ellipsis, the label too long for its pill) at its top left beside the "Uber" bubble; status said `dropoffGuess: null` 34 s later. **Did the reader run, and what did it read?** By hand, off the snap's full frame (the phone cut out with the map band's own corners from map.json, `read_map_label` as test_scan_pi calls it): one box, at the band's top left (15 rows under the band's top), read "<n> <Name> <Name> Pkwy N..." exactly, both snaps' frames (16:31:34 and :44) — and `OP.map_label` refused it: "N..." is no quadrant, no type and no name word, while the "…" form was always cut off by its edge strip. But the reader never saw that frame: `MapLabels` took ONE read per offer id, on the card's first frame read, and the map band kept off that same frame (map.jpg, 17 ms after the offer's id) shows DoorDash's map still zoomed in on the car, a different neighbourhood's streets, no route, no pins, no label — `map_label_boxes` finds no box in it (the "Uber" bubble is 0.13 of the screen wide, under MAP_LABEL_WIDE). Nothing else blocked it: `wants_map_label` held, the card's store and door (`store=`) do not refuse the label, and the bubble beside it is no box. **Fixed, both:** the twins' `MAP_LABEL_CUT` takes a trailing run of two dots or more, spaced or not, or a "…" with spaces or dots round it, off as the truncation mark before the label is judged, exactly as "…" was (one dot stays, an abbreviation's; a type the ellipsis cut is still no type). `MapLabels` takes an offer again on a later card frame while no label has been read — `MAP_LABEL_AGAIN_S` (2 s) after the last ask, `MAP_LABEL_TRIES` (5) asks at most, never again once one is read (counted before the job is queued, so the read's thread can mark it found). Both numbers chosen, not measured: how long DoorDash's map takes to settle is in no snap. Re-run on the snap's frames: "<n> <Name> <Name> Pkwy N", 47-49 ms. The card's dropoffGuess then rides onto the offer (second offer line, `mapLabel`), onto the hold at ✓ Took and onto the panel's order, drawn "≈" (test_server's new late-label case; the drawing is test_dashboard's '[dd map label]'). Checks: cases.json mapLabels +10 (both ports: corpus.test.js, test_parser); test_scan_pi +5 (a synthetic "..." label at the band's top left read, MapLabels re-asks a found-nothing offer two seconds apart until read and never after, at most five, its thread's found mark); test_server +2 ('dd map label told late on a one-store card'). Open: the label's top sat 15 of 1400 rows under MAP_LABEL_BAND's top on this mount; a phone sitting higher in the camera's frame could cut it, and the band was not moved without a frame that shows it.

**A DoorDash customer's pill came up after the five label asks were spent, and ⌖ never read it (the owner's snap of 7 Nov 21:34–21:35, build cef6eb1: "Here is another example trying to scan the door dash customers address from the pin. It read the business address as it is a full address but the customer is usually just the number and street").** The card: "$7.10 / 2 stops (4.8 mi) · 42 min / <Store> / <n> <Name> Road Northwest, Atla… / Customer dropoff", read well throughout; `dropoffGuess: null` in every status of the four snaps. Its frames: at the countdown's 0:48 (the snap's frame 0.8 s before the card's first read) DoorDash's **overview heat map** — orange busy zones, round flame pins, restaurant names in plain dark text, the car's dot, no route and no pill; at 0:21, 27 s later, the route with the customer's black pill "<n> <Name> Dr NW" above its person pin. **What the reader did with each, by hand** (the phone cut out of each full frame by hand, `read_map_label` as test_scan_pi calls it): the overview gives no box (its names are glyph strokes the opening removes, its pins round) and runs no OCR, 40 ms median; the route gives one box, read "<n> <Name> Dr NW" exactly, 48 ms median. The reader was right; `MapLabels` asked it too early. The card's reads came 0, 2.0, 6.1, 9.3, 10.1, 11.6 s … after its first (reads.json), so the five asks two seconds apart were all spent 11.6 s into a card read for 43 s, none after the 0:21 frame. And ⌖, pressed six times from 21:35:09 to :21 (reads kind "press", screen dd.offer) — with the pill up in the 21:35:17 frame — read only the screen's text: white-on-black, the pill is not in it, and the text's one full address is the store's door, refused as an offer's. **Fixed:** (1) `MapLabels` asks while the same offer's card is read and no label is: every card read `MAP_LABEL_AGAIN_S` (2 s) after the last ask, until `MAP_LABEL_LIFE_S` (75 s, chosen over DoorDash's minute-long countdown) after the first; the card leaving or a new offer id ends it. An ask whose map holds no label-shaped box (`read_map_label`'s new `seen`: `boxes` 0) is no attempt; `MAP_LABEL_TRIES` (20, chosen: a black "Decline" pill read on every frame still leaves forty seconds) caps only asks that had a box and read no street. Bound: 1 + 75/2 = 38 asks an offer, 20 of them read, each held to `MAP_LABEL_CAP_S`, on the label's own thread; at the Pi's 140 ms median (tools/pi_bench.py) an ask every two seconds is under a tenth of a core. One entry per offer, changed in place, with a `busy` mark so the read's thread and the loop never write one key at once. Replayed at the snap's read times on its own two frames: the old rule's five asks all on the overview and nothing read; the new one reads "<n> <Name> Dr NW" on the first card read after the route came up. (2) ⌖ over a DoorDash card (`digest`: the press's read `asked`, an offer, `wants_map_label`, the card on record with the same payout) hands the press's own frame to `MapLabels` as a press (`label_geometry`: the card's corners, not the whole-screen crop), which waives the spacing, life and cap but never runs two reads of one offer, and takes a waiting card read's place in the queue; a street found is told on the offer line as `mapLabel`, the offer's dropoffGuess — approximate, drawn "≈" only, never the press's dropoff answer (still "no address"), a pin, the GPS drop or a figure. The log says what the press found, once a press (`say_press_label`): the label, or "no label pill on the map", or the pill it read and refused. (3) The twins' map label refuses the card's store doors however the map spells them — a house number and first street word equal to a store door's first two words (`_label_same_door` / `labelSameDoor`; "<n> <Name> Rd NW" against a door printed "<n> <Name> Road Northwest") — and a label running on past its type and quadrant into a town; a comma, a ZIP and a two-letter state were refused already. Every store name and door on the card is handed in now (`label_stores`: `pickup`, `pickupLine`, and a stops card's `places` and `placeDoors`), not the first store's alone. The overview and route screens are rendered (`testcards.dd_stores_screen(map_view=...)`, invented names). Checks: cases.json mapLabels +10 (both ports); test_scan_pi +19, two retired with the five-ask rule (the rendered overview gives no box and no OCR, the route reads its pill, the store's door on the pill refused, MapLabels over the card's life reads the label on the first ask after the overview, a pill-less map asked until its life is up and a bad pill twenty times, a press's waivers, its place in the queue and its frame read through `label_geometry`); test_loop +13 (a card whose map changes under it from the overview to the route, asked more than five times on the overview and its label told after the route; ⌖ with the route up tells the label and logs it, the dropoff answer still none; ⌖ on the overview logs why and tells nothing; ⌖ on a pill showing the store's door tells nothing and names the pill). Open: when the pill first came up between 0:48 and 0:21 is in no frame; a card the motion gate does not read for six seconds (VERIFY_MAX) is asked no sooner.

**A store's door printed short ("<n> <B> Pkwy" under the store, OSM's road "<A> W <B> Parkway Northwest") got no pin; the store is now pinned by its name along that street, or its door asked by the full name (same snap).** Map view said "NO PIN · <n> <B>…, 2 found and they disagree" and drew the pickup as a band "≈"; mapwalk skipped it "not found" at door level, and the car's other order's pickup on the same road under its full name got only an area ("too many answers", a cut list of ten). Every question the door chain asks is about a street called "<B> Pkwy" — as printed, without its type, by the index's `named` (only for an end), a directional the other way — and neither the NucBox's Nominatim (no house number there) nor streets.js's four rules hold that name: `exact` wants every word, `dir` lets only a directional go. **The street index** (streets.js `tail`, `/api/streets/tail`, relayed as `/api/nbx/tail`, box required): the name as printed counted inside the box (never widened), else the streets with a way into the box whose name ENDS with the printed words at a word boundary on the short forms, a printed quadrant agreeing, the printed words ending in a type with a name word of three letters before it; `among`, names only for exactly one, and every such street's polylines in the box (none past POINTS_MAX, said `cutAt`). **The rule, one, in map-view.js** (`tailAsked`, `tailWanted`, `tailRetry`, `storeQuery`, `alongBox`, `pickStoreAlong`; `ALONG_M` 200 m and `STORE_ONE_M` 100 m, both chosen): for a PICKUP with its store's name, after the door chain pinned nothing (any refusal, never a NucBox down), with the street index set — (b) where the index knows ONE street by the tail, the door asked by that full name, held to that street at door level (`pickNamed`); else (a) the store's name asked in the box round the street's shape (the snap's card is no yardstick, "2 stops (3.0 mi)" with one leg and no total, so its disc is sixty miles, where any chain's name is a list cut at ten), pinned `by: 'store'` only where exactly ONE place of that name lies inside the card's reach AND within 200 m of the street. Several, none, a cut list, no shape: no pin, and the door chain's own refusal is what is said, as before. **Server**: `pickupTail` after `doorChain` in `searchHeldPickup` (pickupAsks now carries each door's `store`: the planner stop's name, the card's store for its printed door or a popup's, each listed store for its own) and in `earlyDoor` for a card's pickup (`searchCardEarly`, `offerPin`), so the Took's questions are the cache's; `pickupAsk` takes a street answer's reader and ends on the door's answer when a question past it is not answered (a NucBox on an older server answers /tail 404). **Map view**: `NbxSearch.place`'s `store` (live.html: the card's own pickup, its store's name beside a printed or tapped door), `storeTail`, the same questions in the same words. NEVER a dropoff: no store is ever handed with one (test_server: a dropoff on that street asks neither /tail nor the name). Approximate points are untouched: an area or band is still drawing only, and a store pin is an exact named place, one in the reach, on the card's street. Checks: streets.test.js +12 (`tail`'s rules, the endpoint, its box refusal); mapview.test.js +17 ('[store]': the parts, and through the real server and the fake NucBox the snap's shape pinned by the store, the cache shared, no index no ask, two along / one off / one along beside one off, the door by the full name first, out of reach none); test_server +5 ('[store along]': held pickup pinned from the card, asked as /tail then by name, two along refused with the door's own why, a dropoff never asked so, the card's early search answering the Took with no new request). Open: an Uber card's "Store (<n> <street>)" carries no separate store name and is not asked this way; a street the index splits under two names in the box is two streets, so (b) is not asked, (a) still is; how far the real stores sit from OSM's centre lines is not measured (ALONG_M chosen).
**An Uber card's store, printed "<Store> (<n> <street>)" with no name apart, was never asked the store-along-its-street way; the name before its bracket is now the store (the owner's Uber offers of 2 Nov).** The entry above closed with it open: the rule (the door by the street's one full name, else the store by its name along that street) wanted the store's name handed beside its door, which DoorDash's card gives (`pickup` and `pickupLine` apart) and Uber's does not — the parsers keep Uber's whole line as `pickup` (cases.json: "Uber's bracketed store keeps its door in `pickup`... and has no pickupLine") and searchPlan asks its bracket as the door. The owner's 2 Nov offers carried one restaurant's "<Store> (<n> <A> <B> Pkwy)" card after card, its door misread across the frames as "<B> l Pkwy" and "<B> | Phy)" (the parser keeps "<B> Phy"). Asked as read, every question is about a street called "<B> l Pkwy" or "<B> Phy", which neither the NucBox's search nor the street index holds, and `tailAsked` refuses a name with no type word: no door, no store, whatever the store's name. **No parser change**: the twins already give the line whole, and the split is the search's, as the door's always was. **map-view.js**: `bracketStore` — the text before the bracket searchPlan reads as the door (one regex now, `BRACKET_DOOR`, searchPlan's and bracketStore's), or null for a bare door, a name with no bracket, a bracket with no house number ("Kroger (Shiloh Square)"), a count ("Wasabi (2 orders)", refused though the parsers take it off), a name under three letters. `typeSlip` takes "Phy" for Pkwy (one store's frames, so one slip; no type is "Phy") and leaves out a lone "l" or "|" right before a type word, after a name word with the house number in front (no street's name holds a lone lowercase l; a capital initial stays, "<A> W <B> Pkwy"); the search only, never the stored text. **Handed for the card's PICKUP only, server and Map view alike**: live.html's `pickupStore` (the name before the bracket, also beside a tap's door on an Uber card, where the whole line was handed and `storeQuery` refused it as a street); server.js `pickupAsks` (the hold's field 'card' is the Uber line itself and is asked first, so it takes the name there, or the card's own text after it would be the same question already asked without it — the first test run caught exactly that) and `cardPickupStore`; the card's early search (`searchCardEarly`) and the on-time hint (`offerPin`) hand the same name for the same text, so ✓ Took's questions are the cache's. A dropoff is never handed one, even one printed in the same shape. Approximate points untouched: the pin is still a door or one named place inside the card's reach and along its street. Checks: mapview.test.js +8 ('[uber store]': the split and its refusals; the slips put back and the shapes left alone; through the real server and the fake NucBox the Uber line with no store refused as before, with its name pinned by the store, its two misreads the same pin from the cache, two branches along none); test_server +3 ('[uber store]': a held Uber order read "<B> l Pkwy" pinned by the server from the card; an Uber dropoff "<Store> (<n> <street>)" never asked by that name; an Uber card read asks its store at once and ✓ Took pins with no new request, read "Phy"). Open: the slips are two shapes off one store's frames, not a measured list; a name the reader littered in front ("ee <Store>") is asked as read, as DoorDash's store always was.
**The label reader's band started 6% down the screen, DoorDash's label sat 15 rows of 1400 under that edge, and a phone 2% higher in the mount lost it; the band now starts at the screen box's top (the 2 Nov map-label entry's Open).** The reader's band was `MAP_LABEL_BAND` (0.06, 0.62) of the warped screen box, its 6% to keep the phone's status bar out, and on the owner's snap of 2 Nov 16:31 the label's top was at 7.1% of the screen. The corners a read freezes are the screen box's, and the screen moves inside them as the phone sits higher or lower in the mount, so the margin was 1.1% of the screen. **Measured, not guessed** (scratch script, not committed): the repo's rendered DoorDash stops screen (testcards `dd_stores_screen`, no label of its own) with that snap's label drawn at 7.1%, a phone's status bar over the map — light (dark glyphs, a battery, signal bars) or dark (a black bar of white glyphs) — and a "Decline" pill at the top left, white with dark words or black with white words, the whole screen moved up 0, 2, 3, 4, 5 and 6% inside its box: at 6% the label read at 0% only, lost from 2% (its top cut, then gone); from the top, read at every shift in all eighteen screens. Nothing up there is a label: a light status bar's glyphs are thinner than the opening and go as the route's line does (no box); a dark bar with a few glyphs holds too little white for a label's text (no box), and with more (a percentage beside the battery) is a box the whole band wide, which runs into the right edge and is never read; a black "Decline" pill is a box (166 × 54 at 1400 rows), reads "Decline", and `OP.map_label` refuses it (no house number, an app word); a white one is no box. Over the twenty screens testcards draws (light and dark) the band from the top reads the same labels as from 6% (the two `dd_stores_screen` ones, true) and no other. **Fixed**: `MAP_LABEL_BAND` (0.0, 0.62); the drawn card box still ends it only below 0.26 (`MAP_LABEL_ROI_FLOOR`, the old 0.06 + 0.2, kept so moving the top moved nothing else, in `map_band` and `MapBands`' sidecar); and `read_map_label` takes a box that runs into the right edge off BEFORE counting `MAP_LABEL_MOST`, so a full-width dark bar (or a bezel, with the phone lower) never takes the label's read. Cost: 84 more rows (784 → 868 of 1400, +11%); 25 → 33 ms to find the boxes in that run and 44 → 42 ms for the whole read, on a machine shared with another job — within its noise, on the label's own thread under `MAP_LABEL_CAP_S` as before. A kept map band (MapBands, `map.jpg`) is now the screen box from its top too (rpi/README.md, 🗺 Map bands). Checks: test_scan_pi +6 (the band's numbers; the label read with the screen moved up 2%, 3.5% and 5% under a light or dark bar beside a white or black pill; the old top losing it at 2%; no label read off either bar or either pill; a dark bar never handed to the OCR, nor taking the label's place with one box allowed) and two changed (the kept band's rows and its sidecar's top). Open: the status bar and the pill are drawn from what a phone and DoorDash commonly show, not off a real frame of the owner's (none is in the repository); a real "Decline" pill dark enough and long enough to be read is refused by its words only.

**A road's designator left out as if it were a slipped quadrant: "Rd Ext" asked as the base road, and its door pinned (review of 6 Nov, invented).** map-view.js `unknownTail` (the 30 Oct "NUP" retry, in `streetRetry` and `dirRetry`, reached from server.js `doorChain`) dropped any one-to-five-letter word after a type that was no type or quadrant, so "1450 <Name> Springs Rd Ext, Canton" was asked again as "1450 <Name> Springs Rd" and `retryFits` took the base road's 1450: a door pin on another road, the GPS drop armed on it, where no pin is only the timer and Drop. **Now** a recognised designator (`DESIGNATORS`: Ext/Extn/Extension, Conn/Connector, Spur, Byp/Bypass, Alt/Alternate, Bus/Business) is never the word left out — no second question is asked for such a door, and none by `dirRetry` either — and a retry carries the designators the asked line printed after its type (`retry.keep`, only where there are any, so every other retry is the object it was); `retryFits` refuses an answer whose road lacks one ("Tansy Springs Road" for "...Rd Ext") and reads "Extension" as "Ext". The junk tails ("NUP", "Xq") are retried as before. Checks: mapview.test.js 825 → 833 (six designators never cut, no retry by either rule, `retryFits` refusing the base road and taking the extension spelt either way); no existing check changed.

**Four refusals were one label and 'none' was two things: the words now say what the search measured (the places report and the 7 Nov log, 9 Nov 2026).** The 45-day NucBox report's largest reason, "not found inside the card's reach: 1342", and the rig's `pin: none offer pickup … "not inside the card's reach"` for Wingstop (three), CVS (three) and Wendy's, claimed a reach nobody had measured. tools/places_report.js's WHY table printed those words for four refusals — pickInDisc's 'none', 'nodoor' and 'together' and pickPlace's 'noplace' — where server.js's END_WHY said them of 'none' alone; and 'none' itself is two things, because every question is `bounded=1` to the disc's box (`discBox`): a 'none' whose box held nothing (pickInDisc's `nearest` null — the door not on the NucBox under that street, or past the box, which nothing can tell apart) is not a door found too far out. **One vocabulary now, in map-view.js** (`refusalWords`, `REFUSAL_WORDS`), read by server.js (`endWhyOf`: the `pin:` log, `/api/status`'s `endWhy`/`pickupsWhy`, the drop row, the search memo's `reach.why`) and the report (`wordsOf`): 'none' with nothing answered is "no such door in the reach's box"; with the door answered outside every circle, "door found N mi out, past the reach" (N the card's fix to the nearest such door, one decimal; the report counts "door found past the reach", one label, no miles); "place" for "door" where a place was asked by its name (pickPlace's 'none' is named features outside, not a door); 'nodoor' "street found, not that door" and 'noplace' after a door "no door, place not found", both unchanged; 'noplace' for a store asked by name alone (the report's name pickups, a held pickup by name) "no place of that exact name in the reach's box" — placeNamed wants the same words, so "Utopian Bowl Kitchen" against OSM's "Utopian Bowl" is that, not a reach; 'together' "a corner whose streets run together"; 'several' and 'capped' as before (the report keeps "several places answer (a chain, or branches)"). Three faults found on the way: earlyDoor's outcome (`settle`) kept only `why`, so every offer refusal would have read "no such door" even with doors answered — it keeps `nearest` now; searchHeldPickupName dropped `nearest` the same way; and tools/shift_report.py's `WORD_MAX` (32) would have cut "door found 61.2 mi out, past the reach" (38), now 40. The panel's in-car line says "no such door" and "past reach" (live.html `endWhyShort`, `END_WHY_SHORT`; journal.html `endSaid`), never "door found 4.4", the first three words; the old words keep their short for a hold restored from before. Map view's own caption ("none fit the card · within 9.4 mi of you, nearest 1.2 mi") is unchanged: its tail already tells the two apart. Words only — nothing that pins, files or decides reads them; END_WHY's other keys are MV's words. Tests: tests/mapview.test.js `[words]` (the real pickInDisc and pickPlace over invented answers: a door 4.4 mi out of a 3.9 mi disc, an empty box, the street without its number, a name a word short, the rest, and no word naming the card's reach); tests/placesreport.test.js `[words]` (three invented pickups through `placePickup` counted apart in `coverage`, an area's "stood in for" in the same words); rpi/test_server.py `[words]` (`endWhyOf` over each refusal) and every status, drop row and log line that said "not inside the card's reach" (the offer pickup 3.35 mi out of its 3.3 mi disc now says "door found 3.4 mi out, past the reach"); rpi/test_dashboard.py `[no door]` (the two short words); tools/test_shift_report.py (the longest word kept whole).

**The places report asked a DoorDash pickup by its store's name and never by the door its card printed (the Open entry of 7 Nov, (4); 9 Nov 2026).** tools/places_report.js placed every row by `row.pickup`, and on a DoorDash stops card that is the store's NAME: the door printed under it (`pickupLine`; `stores`, the parser's `places`/`placeDoors`, on a card with two stores or more) was never read. So a DoorDash pickup was placed only where `MV.pickPlace` found a feature with the same name words, alone in the disc — and a one-leg card sets no radius, so the disc is sixty miles, where a chain's name is every branch and OSM's "Utopian Bowl" is not "Utopian Bowl Kitchen". The rig searches the printed door first (server.js `searchCardEarly`, `pickupAsks`). Now the report does, in the rig's order: `printedDoor` (the row's `pickupLine`, else the door its stores list beside the store it names, Assemble `sameStore`), then `placeRow`: the door through `placePickup` at door level in the card's disc with every retry, the store's name beside it for the street printed short (NbxSearch.place `store`, `MV.pickStoreAlong`, a 'name'-level point) only after the door refused; no point from it, the name alone as the report always asked it (pickPlace, one place of that name), so nothing placed before is lost; neither, the door's area, band or refusal, and the door's refusal is what is counted (`asked` says which text placed it; the band's road questions are spent only then). **Measured on invented stores, not on the record** (a scratch simulation, 400 stores round open water, 1000 DoorDash rows, the card's fix within 3 mi, 45% one-leg; the NucBox holding the door's number for 60% of stores, OSM's name the card's exact words for 50%, 40% a chain): points 244 → 657 (+413), none lost, none moved, none wrong against the invented truth; 548 by the door, 109 by the name; 343 more an approximate area beside the door's refusal (the street found inside the disc), counted at their level. The gain is the mix's: with doors held for 30% and exact names 80%, 682 → 786 (+104); with doors 80% and names 30%, 114 → 870 (+756), the four the name had put on a chain's wrong branch moved to the door. The Method tab says the rule. Tests: tests/placesreport.test.js `[dd door]` (the door from `pickupLine`, the stores list and the parser's lists, and none from a card that printed no door or a line that is no door; a name a word short refused by name and placed by its door with the store's name handed beside it; a door not held and a name that is one place, by the name; neither, the door's refusal in its words; a chain's name every branch and its door one; a row with no printed door placed exactly as before).

**An offer read with an order in the car was searched from the car alone; it gets the held orders' `also` circles now, on the rig and in the report (the Open entry of 7 Nov, (5); 9 Nov 2026).** The one real reach miss: an offer shown while another order is held may print miles that start at THAT order's end (the 29 Oct shift's #6), and the `also` circles that cure it (MV.afterParts round each held end, the card's miles + SLACK_MI + the end's `widen`) were put on a HELD order's card only (server.js `setAfter` at the Took, `cardForSearch`, `heldDisc`) — never on the offer before its Took (`searchCardEarly`, `offerPin`, Map view's preview), nor in the places report, whose rows carry no `after`. server.js `offerAfter`/`offerCard` give the offer the circles its Took would: `afterOf` of every order in the car when it is read, its own order aside (`heldCard`), at most MV.AFTER_MAX — in its pickup and dropoff search, the on-time hint's pins, and on the offer line itself (`after`, read afresh at every reading, absent with nothing held), which live.html's preview hands to MV.discFor as it is, so the preview searches and draws the same union the server searched and the hold will. The places report rebuilds `after` (`heldEndsOf`, `afterFor`) from the orders TAKEN and not yet put down when the card was first seen: each one's end the GPS at its drop where the GPS, the app's screen, a GPS-timed press or a GPS finish put it down (`widen` AFTER_GPS_WIDEN_MI, the rig's AGREE_MI — chosen, not measured; an untimed Drop press is no position), else its dropoff placed by the same chain (a door `widen` 0, an area its spread up to AREA_MI) — the rig's endAnchor. **Measured on invented geometry, the reachsim way** (10,000 stacked offers: the held end 0.5–8 mi crow from the car, the new store 0.3–5 road mi past it, trip 1–10 mi, road 1.3× crow): stores outside the disc 1,521 (15.2%) → 0. With an invented NucBox (the store's own door held 70% of the time, a door of the same text somewhere within 15 mi of the car 30%), through the real pickInDisc in the bounded box: right pins 4,761 → 5,601 (944 new; 104 lost to "several answers" where the decoy came inside the union too), wrong pins 630 → 589 — 101 gone (the true door now inside as well, so "several"), and **60 new wrong pins** (0.6%): the store's own door not on the NucBox and the same-text decoy inside the new circle only. That is the risk any circle of that size carries, the one a held order's `also` already took; no rule was loosened — a pin still needs door level, or one place of that name, inside the union, and a card with nothing held is searched in exactly the disc it was (10,000 of 10,000 identical). Tests: rpi/test_server.py `[stacked]` (an order held ending at its pinned door, an offer read at the Square whose store is that door and whose 2.8 mi start there: the offer line carries the held end, its pickup asked in the box round that end's circle, no `pin: none` for it — the `[reach]` offer beside it, read with no end in the car, still refused 3.4 mi out); tests/mapview.test.js (an offer line with `after` is the hold's disc and pins the door in the reach); tests/placesreport.test.js `[stacked]` (the GPS end, an untimed press falling to the dropoff's door, no circle with neither; a card before the Took, after the drop or the order's own gets none; the store outside the box from the car alone placed at door level from the end; a door inside neither circle still no pin).

**What "not inside the card's reach" is made of, and the one part of it that
is the reach (7 Nov 2026).** The NucBox places report over 45 shift days:
"Pickups placed: 1536 of 7984 (19.2%)", and its largest reason for the 6448
unplaced, "not found inside the card's reach: 1342" (20.8% of the unplaced,
16.8% of all), with 35 more "placed at area level [stood in for: not found
inside the card's reach]". The rig's log that day: `pin: none offer pickup
#… "not inside the card's reach" (Utopia at the…)`, `(CVS (1554 North…)`,
and "too many answers" for a third. **Measured 7 Nov, acted on 9 Nov.**
server.js `reachOf`/`discSet`/`reachCard`/`reachSaid` put, after the door on
every `pin: none` line whose refusal had answers to measure (and on the
search memo's verdict, a 📷 Snap's searches.json), how many answered and how
many were the door asked, the nearest refused answer's crow miles from the
disc's centre (and from an `also` circle's), the radius and how it was set
(the card's miles + SLACK_MI, the 60 mi default and why the card set none,
an add-on's trip, a rough fix's widening, `also` circles), the answer's
Nominatim kind and name cut to 30 letters, the card's own `toPickupMiles`,
and for an offer how many orders were in the car; for "too many answers"
the count, the cut, how many inside and their spread:
`... (Example Diner (1985…) - 3 answered, 3 at the door, the nearest 3.35 mi
from the centre, radius 3.3 mi (card 2.8 mi + 0.5 slack; card says 0.9 mi
to the pickup); nearest: place "1985, Cobb Parkway, Kennesaw, "` (invented,
the suite's fake). The words in quotes are END_WHY's, unchanged; nothing
that pins, files or decides reads `reach` (doorChain hands it as a fourth
argument; offerPin and the status word never see it). **What the code says
the 1342 are**, checked by reading and on invented data
(tools/places_report.js's own `placePickup` and `coverage`, never edited):
(1) *The report's label is four refusals, the rig's one.* Its WHY table
prints 'none', 'nodoor', 'noplace' and 'together' all as "not found inside
the card's reach"; the rig's END_WHY says it of 'none' only ('nodoor' is
"street found, not that door"). Four invented pickups through `placePickup`:
a door 4.35 mi out of a 3.9 mi disc, a door nothing answered, a store name
OSM spells with a word fewer ("Utopian Bowl Kitchen" against "Utopian
Bowl") in a 60 mi disc, and a street found without its number — the first
three all counted under the label, the fourth placed "at area level [stood
in for]" it. One of the four is the reach. (2) *A bounded search cannot see
far.* Every question is `bounded=1` in the disc's box, so an answer outside
the circle comes back only from the box's corners — 21.5% of its area, out
to 1.41 radii; anything farther is "nothing answered", the same line as a
door the NucBox does not hold. (3) *An Uber card with both legs or a printed
total cannot be too small for its pickup.* Its `miles` is the approach and
the trip summed (`toPickupMiles` is the approach split out of that same
sum, offer-parser.js `toPickup`), so the radius is at least the approach +
0.5 mi, and a crow distance is never longer than the road's: the pickup lies
inside unless the fix is more than 0.5 mi plus the whole trip from where
Uber measured — and the fix gate's 20 s staleness at 60 mph is 0.33 mi.
10,000 invented such cards (approach 0.3–8 mi, trip 1–12, road 1.3× crow):
0 outside, 0 with the fix 0.33 mi off. So "Uber's miles are trip miles, the
disc is too small when the car is far from the store" is wrong for every
card that sets a radius. (4) *A card that sets none is searched in sixty
miles.* DoorDash's one-leg cards ('shape', 528 of the week's 1,166) and
Early look (27) get BOX_MILES: nothing is outside that. And the report asks
such a pickup by the store's NAME — it reads `row.pickup`, never
`pickupLine` — where `MV.pickPlace` refuses 'noplace' unless OSM holds a
feature with the same words in the same number (`placeNamed`, one slip):
reach plays no part, the label says it did. (5) *The one real reach miss: a
card whose miles do not start at the car.* An offer read while an order is
held may print miles from that order's end (the 29 Oct shift's #6, the entry
below); the `also` circles that cure it are put on a HELD order's card only
(`heldDisc` via `cardForSearch`), never on an offer's (`earlyDoor`,
`searchCardEarly`) nor in the report, whose rows carry no `after`. 10,000
invented stacked offers (the held door 0.5–8 mi crow from the car, approach
0.3–5 mi, trip 1–10): 1,506 (15.1%) outside the disc, and only 521 of those
answered by the bounded box at all — the other 985 read "nothing answered".
**The fix, shipped 9 Nov:** (a), (b) and (c), each Done above: "Four
refusals were one label", "An offer read with an order in the car" and
"The places report asked a DoorDash pickup".
What settles it still: the next shift's `pin: none` lines, counted as nothing
answered / the door found outside / orders in the car. Tests:
rpi/test_server.py `[reach]` (the functions over invented answers: a door
past the edge, nothing answered, the street without its number, a cut list's
spread, two that disagree, nothing for a pin, a 'NucBox down' or no disc,
every way a radius is set, the name's cut, the tail as said; an offer
pickup's line through the real server and the fake NucBox; offerPin and the
pickups' status word never read it) and `[pin said]`'s three lines with the
tail.

**Uber's navigation banner printed the held order's whole door and the rig never read it (the owner's snaps of 12 Nov, build cf10ded).** Six of ten presses had the navigation up; the held end said "no house no." for long stretches under a banner reading "<n> <Street> Ln / <Town>, GA", 5 of the shift's 6 ends went unpinned, and the log's "a street and no address the rig would accept" (144 since start) quoted the map's street labels ("RD NW", "PL"). The card box is the lower half of the screen; the whole-screen read the navigation asks for did cover the banner, but preprocess() leaves a light map as it is and OCR_CONFIG tells tesseract not to retry inverted, so the white letters came back as "GEE @ oe «ae | r-) peste g eda" on every one of that shift's 10 whole-screen navigation reads on file. Now `pipeline.read_nav_banner` reads the band again on its own — found as the longest run of rows in the top 40% of the screen darker than half the screen's median (0.05-0.30 of the screen on all five navigation frames warped from the sensor; no run on the planner), inverted, scaled 1.5x (at 1x the second line was lost on two of five) — on a whole-screen read typed `uber.nav` in the light theme only, never on a card read. Measured on those five frames on the development box: the destination line read on all five, the whole door on three; 26-54 ms against 84-139 ms for the whole-screen read (0.31-0.47; one blurred frame 1.0), so on the Pi an ESTIMATED 0.6-1.8 s more on the 1.8-4.5 s `auto whole-screen` reads, not measured there. **Which leg it is**: `nav_banner` / `navBanner` take the band as the customer's door only in the customer's shape as Uber prints it everywhere on file — one house-number street and "Town, ST" with no ZIP — and refuse a bracket (a store's "Name (street)"), any "pick up" on the band or the screen, a ZIP (every store door on the planner and the three store banners carried one), and a second street (the turn's "250 ft <Road>" not counted). The sighting types it a dropoff, label `banner`; the assembler files it at the navigation's rank as it files the opened sheet, and refuses it as any held order's pickup. Checks: cases.json `navBanners` 13 (both ports), test_pipeline 10 (a rendered navigation screen's banner read whole-screen and not through the box, a store's banner no door, the band finder), test_scan_pi 2, assemble.test.js 2. Open: whether a banner door with no "Deliver to" on the frame may be filed is the owner's to confirm (it rests on the ZIP-less shape, as the 14 Oct sheet rested on its label); the Pi's own time for the band read; the dark theme is not read.

### The GPS

**Every position the rig kept was two bare numbers, and `keepPlaces: false`
kept them anyway.** `rpi/gps.py` kept gpsd's lat and lon and threw away what
gpsd says about them, so a four-satellite fix and a clear sky's were the same
downstream. And `rpi/journal.py`'s header said `"keepPlaces": false` turned
off "a record of where the driver was" while every row kept the coordinate.

Each fix now carries `mode` and `err` (gpsd's eph, in metres, with epx and
epy when sent; an NMEA fix carries GGA's quality and hdop). There is ONE gate,
`gps.usable(fix)`: mode 2 or better, an error present and at most
`FIX_ERR_MAX`, and inside the existing staleness rule, with a word for why
not (unrated, nomode, rough, stale). The Phone puts the answer on every fix
it hands out as `ok`/`why`, so nothing downstream asks again, and `MV.fixOf`
reads `gpsOk`: the box a place is searched in, the trail and the stray test
all refuse a fix the gate refused, or one nobody judged. The journal writes
seven fields (lat, lon, gpsAge, gpsErr, gpsMode, gpsOk, gpsWhy) through one
`fix_fields()`, and `keepPlaces: false` drops all seven. Commit 491518c.

`FIX_ERR_MAX` is 50 m, measured rather than chosen: the owner's VK-162 reads
eph 27.8 on mode 3 indoors; real gpsd 3.25 made a four-satellite HDOP 6.8
stream mode 3 with eph 129.2, so mode alone bounds nothing; and on gpsd's NMEA
path eph is HDOP × 19 (2.6 → 49.4, 2.7 → 51.3). Through the real `MV.detour`,
20,000 random metro triples with the car moved 50 m in a random direction:
the "+N mi" figure moved 0.017 mi at the median, 0.054 at p95 and 0.062 at
most, and the half-mile call flipped on 11 (0.06%). Traps: quality is judged
before age, so a rough fix that went stale is still `rough` and is never
greyed in as somewhere the car was; the gate goes stale on the Phone's own
`stale_after`, not the module's, so one Phone cannot hold two rules. Checks
(test_gps 99 → 137, test_journal → 405), each made to fail by name, among
them 'a mode-3 fix at 129.2 m is refused as rough' (a mode-only gate), 'quality
is judged before age: ...', 'keepPlaces:false writes no position' and 'a fix
nobody judged is written as not usable'.

*Left failing by it, then fixed in the fixture.* The full run on q5/detour-fix
failed one check, `rpi/test_offerspage.py` '...near where the car actually was'
(499 of 500): its fixture rows carried `lat`/`lon` with no `gpsOk`, the shape of
a row written before the gate, and `MV.fixOf` now refuses such a row as
unjudged, which is what the gate entry above means it to do. The fixture was
stale, not the page: the three rows now carry `gpsOk=True` and all 500 pass.
Rows in the real week carry no position at all (0 of 1,166), so no driver's
history loses a box to this.

**The card reached the panel with no position on it, and the panel borrowed
one.** `rpi/scan_pi.py` now asks `phone.fix()` ONCE per landing and hands that
one object to the journal row and to the offer line, which carries the same
seven fields and the card's yardstick for the detour line above (miles,
whole, hasTotal, legs, toPickupMiles, milesUncertain, milesCorrected,
earlyLook). The line keeps them under `keepPlaces: false`, as it keeps pickup
and dropoff: it is what the panel shows now, not a record. `earlyLook`,
measured over the week: 27 offers carry "Early look / Order in progress" in
102 of their 105 frames, OCR spells it "Early took" and "Arder in progress",
and the pattern finds all 27 and no other offer. It is kept out of `parse()`
so neither port nor the corpus grows a field no judge reads.

The heartbeat carries the newest fix whatever its age (`Phone.latest()`,
judged stale past 20 s) plus `freshFor`, so the page greys a dot without a
copy of the rule. `server.js` needed no change: it relays the beat whole, and
test_server now holds it to that. Measured: 121 bytes a beat as relayed (240
→ 361), 108,900 bytes an hour while a panel is open remotely. Commit bdfd374.
Checks (test_scan_pi 473 → 492, test_loop 261 → 267, test_server 524 → 526,
test_gps 137 → 139): 'the offer line and the row carry the same fix', against
a fake receiver answering differently on each call, fails to a second
`phone.fix()`; 'the beat carries the newest fix even once it is stale, judged
so' fails to `fix()` in place of `latest()`.

`rpi/README.md` now says how the USB receiver on the owner's rig is run, as
seen rather than "untried": gpsd 3.22 with `"driver":"u-blox"`, mode 3 at eph
27.8 m indoors, a static hold that keeps a parked receiver exactly still (so
a parked scatter test is not an accuracy test), and whether gpsd's u-blox
path reports the receiver's own accuracy or derives it from HDOP stated as
unmeasured. "The Pi has no GPS" and a `--gps` help naming only a phone app are
gone (commits e721a72, 72d61a8).

**A 📷 Snap keeps where the car was whatever `keepPlaces` says, and the
driver was told otherwise.** status.json is what `/api/status` answered (the
offer line's fix and the beat's), and reader.json has carried the fix at the
press, and the card's text, since before any position was added. Neither
README put a snap outside the setting, so a driver who turned it off was told
their positions were not kept, with up to a hundred folders of them on the
Pi. Said rather than honoured, on purpose: status.json is written by
`server.js`, which does not read the scanner's settings (the reason the mark
and pair rows already sit on the same list), and a snap is a picture of what
the panel showed, addresses and all. Dropping only the position from
reader.json would make a snap that kept the addresses and claimed to follow
the setting. A later change that makes snaps honour it has to make `server.js`
aware of `keepPlaces` first. Commit 6f0bac0. Checks: test_loop 'a snap keeps
where the car was even under keepPlaces:false, as rpi/README.md says' (fails,
getting None, if `reader_record` drops the fix); test_lint "rpi/README.md's
keepPlaces text says a 📷 Snap is outside it" and "...and so does
README.md's".

**The VK-162 under gpsd's binary u-blox mode froze TPV lat/lon for a whole shift, and the gate passed every fix.** Five consecutive TPVs had bit-identical lat/lon while their ECEF moved (+0.11 m x, -2.65 m y), and 1.5 h of driving later the heartbeat still carried the same point, 0.6 s old, gpsOk true; that ECEF lay 3,048.6-3,048.8 m west of the frozen lat/lon (east-west part, which needs no altitude). `rpi/gps.py`: parse_line derives lat/lon from a TPV's ECEF (Bowring; worst 4e-7 m over eight points) and uses them, `source:'ecef'` with a note, when gpsd's pair is more than ECEF_AGREE (50 m) away. Phone records `heldFor` and `heldMoved`, and `usable()` refuses `frozen` past FROZEN_AFTER 5 s while speed or ECEF speed is over 2 m/s or the ECEF has moved more than 25 m; a parked static hold passes. The panel says "GPS stuck on one spot", and map.html no longer calls every refusal "too rough". README: `GPSD_OPTIONS="-n -b"`, then replug the receiver (the rig now runs NMEA0183). Not recorded: the journal and heartbeat carry no `source`, so a fix taken from the ECEF looks like any good fix there. Checks: test_gps 139->171, mapview 420->423, test_layout 2133->2174 (with the map show), 13 mutations of `rpi/gps.py`, three of `map-view.js`, one of map.html and one of the layout table, each killed by name.

**Map view follows the dot, at its edges.** The driver asked for it ("visually it would be best for me to know it is working right"), which overturns the rule above that the map never follows. A fresh dot leaving the middle 60% of the map pans `live.html` to it at the current zoom; a grey dot or a refused fix moves nothing. A drag or a hand zoom pauses following and the corner says "not following"; ⛶ Map fits and resumes. A zoom within 1 s of the page's own fit or pan (OWN_MOVE_MS) is not the driver's. The same card in a new message no longer refits the view, which had pulled it back every 4 s. Measured with Leaflet 1.9.4 in the panel's 500x472 map along three straight 10 mi lines: 0.8-1.4 new tiles per mile at zoom 13, 2.1-3.2 at 14, 3.0-6.0 at 15, plus 6-9 on entry; 5-28 pans per 10 mi against 200 for panning on every beat, for nearly the same tiles. Tile bytes not measured. `map.html` still fits once and never follows.

**Map view dropped the held order's pin when the next card landed.** The rig still held the order (minutes 38, held 798 s), so the hold had not expired. The page learned the held end only from a ready reading (the Took reply cleared `heldEnds`, a ⌖ read changed only the button); `mapWants`' key ignored which place is the held end; and the held address carried OCR litter before the door ("ss be 4 1610 ... Blvd"), searched as a street name. Now the mark reply carries `held` and a ⌖ read filed onto the hold carries `holding` (`heldForPanel`), the key names the held end, and `MV.searchText` drops a run of short non-capital tokens before a house number, for the search only. Open: a deadline-derived delivery's hold can end early (10 min left gives 25 min).

**The held order's pickups are drawn.** Map view pins each Trip Planner pickup with a street (held card's disc, door-level, litter cleaned), as a green ring "◎ held pickup", and draws car → pickups → held end as straight lines. The planner parser puts a directional that wrapped to the town line back on the street ("... Parkway" / "Northwest, Marietta, GA 30060"). Leading name litter ("oe ") is dropped for display. Open: the detour figure still ignores the held pickup; the map does not know the car reached the restaurant.

**GPS drop.** With the held end pinned at door level (Map view posts it to `/api/held-end`; the server re-checks it with map-view.js's own `searchPlan`/`hasDoor` and keeps it only for the current hold and dropoff text), a car within 75 m + the fix's error (at most 125 m) for 45 s that then reads beyond 300 m on two good fixes puts the order down through the same `putDown` as Drop, the row marked `by:'gps'`. Only gpsOk, fresh fixes count. The panel says "at dropoff", then "dropped · left the dropoff". Known risks: a customer within about 125 m of the restaurant; 45 s stopped in traffic near the door; with two orders, only the last Took's door.


**The GPS drop armed only once Map view had been opened on the held order.** The driver: GPS arrival should arm without opening Map view. When the hold's dropoff is set or changes — ✓ Took with a card dropoff, ⌖ Scan, a sighting filed onto the hold — or a hold is restored at boot, and `NUCBOX_SEARCH` is set, server.js asks the NucBox itself (`searchHeldEnd`) by Map view's own functions: `searchPlan`'s street in `discBox` round the HELD card's disc, chosen by `pickInDisc`, kept only at door level and marked `by: 'server'`. One search per hold and dropoff text; a failure is asked once more after `NUCBOX_RETRY_MS` (30 s, chosen, not measured). Never the public geocoder; with `NUCBOX_SEARCH` unset nothing is sent. The first valid pin for a text wins (the page's later post is a no-op), and an answer for a hold or text that has moved on lands on nothing. /api/status says who pinned it (`endBy`) or why not (`endWhy`, only of the text it was given for). The relay and this search build the question and read the answer in one place (`nbxSearchTarget`, `nbxHits`). A second door test after `pickInDisc` could never refuse anything — `pickInDisc` keeps only answers that carry the house number — and was deleted in the verification pass. Checks: test_server '[auto arm]' 11 (8 with the lane; a hold restored at boot, and a reason not said of a new dropoff, added when undoing `armHeldEnd` at boot and the `endWhyFor` guard failed nothing); 14 mutations, each killed by name.

**The GPS drop's first numbers were guesses, and a door near the restaurant would end the order as the car left with the food.** Replayed against the driver's 12 Oct drive outside the repo (385 min, 23,163 fixes, 96.5% passed by the gate): parked, the fixes scattered 3.4 m from the stop's median at p50, 22.7 m at p99, 34.7 m at worst, while the receiver's own error read 27.6 m at p50; no parked fix was past 75 m, none past 300 m. The arrive radius is now 75 m plus the fix's error capped at 25 (100 m at most; it was 125). DWELL is 60 s (was 45): of 53 still stops of 45 s or more, 7 were under 60 s, and the three real doors held the car inside for 184, 243 and 794 s. A run of gate-refused (`rough`) fixes, up to 60 s with no silence over 20 s in it and good fixes inside on both sides, keeps the dwell without counting toward it; silence still resets after 20 s. LEAVE is unchanged (300 m on two consecutive good fixes; no false departure in the replay). The restaurant guard: a door within 150 m of a held pickup Map view pinned (POST /api/held-pickup, the newest 4 kept) is not armed, and /api/status says 'door next to the pickup'. That guard, not the radius, is what stops the restaurant: a door 50 or 75 m from each of the three restaurant stops, eight directions each, arrived 24 times of 24 at 125 m and at 100 m alike; 100 m away it arrived 1 of 24 at 125 m and 0 at 100 m; a door at the restaurant would have put the order down as the car left with the food, 21 and 43 min early on the two orders whose wait came after the Took. (The lane's commit and comment had the 1 of 24 as the 50-75 m doors at the 100 m radius; the comment now says what the replay measures.) Checks: test_server '[gps tune]' 9 (5 with the lane; refused time not counted, silence after a refused fix, a refused run past 60 s, and the fix's own error under the cap, added when undoing each failed nothing) and '[gps drop]' restaurant guard 4 (a pin for another order refused, added); test_dashboard 1 (the page posts the held pickup's pin, added). 13 mutations; 12 killed by name, and one is equivalent: `refusedTo !== null` adds nothing to the silence test beside it (`fix.at - null` is never under 20 s), so no check can tell it from its absence. Open, closed 18 Oct (the server pins the restaurant from the card, below): the guard needs the pickup pinned by Map view; a pickup never placed leaves a door beside the restaurant armed.

**GPS logs grew 5.4-9.0 MB an hour with nothing removing them.** tools/gpslog_tidy.py, run from Start.sh before gpspipe, gzips finished logs (4.6% of size) after reading the copy back, and deletes compressed logs past 60 days; dry run by default, confined to its directory, idle on an unset clock. Checks: tools/test_gpslog_tidy.py 45.


**Nothing measured what an offer really took.** `tools/shift_report.py --journal … --gps ~/gpslog --day YYYY-MM-DD [--csv]` gives one row per order taken: card pay, minutes and miles beside actual minutes (Took to end) and GPS miles (gate-passed fixes through `gps.Phone.take`, the panel's own gate; gaps over 60 s bridged and flagged; steps under FIX_ERR_MAX not counted), stops before a visit and at the door, whether another order was carried, and card pay over actual hours; medians by app and card-minutes band over reliable rows. A report: nothing imports it, no cost, no $/mile, no minutes from distance, no recommendation, no place or coordinate printed (each checked). Replaced orders and orders with no drop row are unreliable. 12 Oct: 7 taken, 4 reliable; two Drops were pressed well before the door, so its medians flatter the day. Checks: tools/test_shift_report.py 61; 25 mutations, each killed by name.


**An expired order left no journal row.** `heldOrders()` put an order past its clock down and wrote nothing, so `tools/shift_report.py` read an expiry and a lost hold alike as "no end". `expiredRows` writes `{kind:'drop', by:'expiry'}` dated at `holdEnds`, once per order: `holding.json` is rewritten first, so an order found expired at boot gets its row then and never again. shift_report reads it as "expired": not timed, unreliable, out of the summary. 7 mutations, each killed by name. Open: a power cut between the file write and the append loses that one row.

**An end-of-shift summary was worked out by hand, and a gap in the GPS log read as a stop.** On 16 Oct the rig was off for about 13 minutes while the car was driven a few miles. A stop detector that joined the fix before the gap to the fix after it called the whole gap a stop at start, and put the departure 10 minutes late. `tools/shift_report.py` now prints the shift's totals above the per-order table, from the same GPS reader and gate: rig on and off (the first and last usable fix), every gap over 60 s with its length and the straight-line distance across it, left start and back at start (beyond and then within 150 m of the first fix for 5 min or more), miles, minutes moving and stopped (speed under gps.py's measured 1 m/s), every stop of 4 min or more by time, length and miles from start to 0.1 (distance only: a ring around a point never printed; kept, not judged identifying), and the order count. A gap cuts the log. Its miles are not counted (the per-order miles still bridge it, and say so), no stop runs across it, its minutes are neither moving nor stopped, and a departure or arrival seen first after a gap is printed at that fix with "may have been any time from" the gap's start. A parked receiver adds no miles: a step needs JITTER_M and a fix that does not read parked. START_M, AWAY_S and LONG_STOP_S are chosen, not measured. Text only; the CSV is unchanged. Card against paid is not attempted, because the rig has no earnings. No panel control. Checks: tools/test_shift_report.py 76 → 129; 15 mutations (5 on the gap rule, 3 on parked jitter, 2 on printing a position), each killed by name.

**Today's shift could only be read at the rig, by a command (the owner, 22 Oct 2026).** tools/shift_report.py printed the totals, the orders and the Pinning section to a terminal on the rig, after the shift; on the phone, over the VPN, there was nothing. Now `shift.html` (◷ Shift on the route view's bar beside ▤ Offers — made by live.html only in ROUTE_VIEW, so the panel's bar is still its six; and a line near the top of the offers page, whose bar already holds six links at 360px) shows the driver's day now as the report computes it: the totals (rig on and off, left and back at start with "any time from" after a gap, miles between fixes only, moving, stopped, the gaps and the 4-minute stops by time, length and miles from start), each order's card pay, minutes and miles against actual minutes, GPS miles and actual $/hr, how it ended, reliable or not, its notes, the Pinning lines and rate, and the summary by app and band — upright, read-only (it sends only GETs), no address and no coordinate. **Run, not ported:** GET /api/shift (`?day=YYYY-MM-DD`, default the driver's day by advice.js's DAY_STARTS_AT) runs `shift_report.py --json` once per request and passes it through untouched. The report leans on gps.Phone.take (the one fix gate) and offer_parser.screen_type, both Python on this rig only, and on its own gap, stop and start rules — the ones the 16 Oct summary got wrong by hand — so a JS port would be second copies of all of it drifting with nothing to say so; the cost is a child process (1.32 s on the real 12 Oct shift here), so the answer is kept SHIFT_CACHE_MS (30 s) per day, a request during a run waits for that run, the child runs at nice 10 and is killed after SHIFT_TIMEOUT_MS (60 s) or 4 MB; no journal yet is an empty one (os.devNull), GPSLOG_DIR empty is "no log". `--json` (as_json) is built field by field — no offer id, no text, no place, no position — times in epoch ms, durations in seconds, distances in miles, each order's Pinning as the text's own phrase. Settled stands: the report describes and recommends nothing, and nothing decides on it; the test that held "nothing reads the report" now holds that server.js and shift.html are the only files that name it, and that server.js names it only inside the one section that runs it. No auth change: the page is on the rig's port like every other, reached over the VPN. Checks: tools/test_shift_report 141→159 with the panel's Undo entry's ('[json]' 12: the keys, the orders by number with no id, card against actual, the totals in ms, the Pinning phrase and rate, no log, no place, no coordinate; the readers check); test_server 1052→1077 with the panel's Undo entry's ('[shift]': today's day and the report's keys, an undone Drop no end, the totals off a GPS log, the Pinning phrase, no address, place or coordinate in the answer, the cache, a bad day refused, another day empty); test_dashboard 1368→1385 with the panel's Undo entry's ('[shift page]' at 390x844 and 360x640: every section, an order and a Pinning line each, no sideways scroll, nothing under 12px, the two links 44px, the report's words, no write; '[route view]' now ▤ Offers and ◷ Shift). Fast lane: not mutation-tested, the full suite not run. Open: shift.html is not in test_layout's PAGES (measured upright at the phone's two sizes only, by test_dashboard); the page does not refresh by itself ("Again" asks once more); a day past the GPS logs' KEEP_DAYS has no totals.

**A held card stamped rough had no disc, so its end was never searched.** The owner's 17 Oct afternoon: an Uber order taken downtown, its door filed by the Trip Planner, and /api/status said `endPinned: false, endWhy: 'no card fix'` for the whole delivery, so GPS arrival never armed. The held card's stamp was mode 3, 0.2 s old, gpsErr 73 m, refused by `usable()` as `rough` (over FIX_ERR_MAX 50 m), and `MV.discFor` → `cardFix` → `fixOf` refuses anything not `gpsOk` — though the disc it anchors was 10.8 mi, against which 73 m is 0.045 mi. Now `discFor` asks `discFix`: a fix the gate passed as before (not widened), and a fix refused ONLY as rough (`roughCentre`: `gpsWhy` 'rough', mode 2 or 3, gpsAge 0 to `GPS_STALE_AFTER_S` = gps.py's STALE_AFTER since `usable()` says rough before it asks the age, lat/lon finite, gpsErr at most `ROUGH_DISC_MAX_M` = 200 m) centres a disc widened by `ROUGH_WIDEN_K` = 2 × its error (the triangle inequality makes a centre off by e sound at R + e; the doubling is for eph's unknown certainty downtown). Both 200 m and ×2 are chosen, not measured: no journal or fixture in the repo carries a real gpsErr. 200 m holds the design study's 129.2 m mode-3 stream and is HDOP 10.5 on gpsd's NMEA path; over it the estimate itself is in doubt and there is no disc. `usable()` now asks frozen BEFORE rough, so a rough word promises the lat/lon was not stuck (a stuck and rough fix is `frozen`). Consumers checked: server `searchHeldEnd`/`armHeldEnd`/`searchHeldPlace`, `discBreak`, `armHeldPickups`/`searchHeldPickup` (all search discs: widened), Map view's `askNucBox` and disc drawing (`discShape`, `located`, `nbxRefusal`: disc-centred, widened), `stretchInDisc` (a mark only, no figure); `cardFix` itself is unchanged, so the panel's detour start (`here`), `cardRefuses`/`againstCard`, `fixLine` and the "ROUGH FIX · on your order's card ±73 m" chip, the beat's `countableFix`/`refusedFix`, `hereDot`, map.html's trail and the restaurant guard (pins, not fixes) all still refuse a rough fix as the car's position. Checks: tests/mapview.test.js 16 (widened by twice the error, no-yardstick widened, 2D, at/over the cap, stale/at STALE_AFTER/no age/negative, no mode/mode 1, no error, frozen/stale/nomode/unrated/unjudged still null, NaN, cardFix and the chip unchanged, no accusation); rpi/test_server.py 3 (held card stamped rough + Trip Planner door through tests/fake-nucbox.js: pinned by the server from 'planner', arrival counted; 250 m still 'no card fix'); rpi/test_gps.py 2 (frozen before rough); rpi/test_lint.py 3 (the order, STALE_AFTER copy, cap above FIX_ERR_MAX). 13 mutations, each killed by name.

**An order with no Trip Planner read had no restaurant for the guard, so a door beside the store was armed (the owner's decision of 18 Oct 2026: the server pins the restaurant itself).** The guard above read only pickups Map view posted and, since 3ca870a, the Trip Planner's pickups the server searched; a DoorDash order (no planner at all) or an Uber order whose planner the rig never read held no pickup, and `searchHeldEnd` armed a door 60 m from the store all the same. And the hold kept the store's NAME: the door DoorDash prints under it (`pickupLine`, b418b12) stayed on the offer. Now ✓ Took carries `pickupLine` onto the hold (a string, else null), and with `NUCBOX_SEARCH` set server.js asks the NucBox for every pickup address on record that has a house number (`pickupAsks`, the named check `pickupDoorPlan`): the planner's pickups (`from: 'planner'`), a `fields.pickupAddr` a planner or place popup filed (its own `from`), `pickupLine`, and an Uber card's "Store (<n> <street>)" (`from: 'card'`). Each is asked as the held end is: searchPlan's street in discBox round the held card's disc (`discFor`, a rough fix widened), pickInDisc at door level, one search per hold and text, one retry after NUCBOX_RETRY_MS, the street-type retry (streetRetry, retryWanted, pickRetry, afterRetry; the street asked kept as `asked`), never the public geocoder and never the store's name. A pin joins the list POST /api/held-pickup fills (keepPickupPin, the newest 4), `by: 'server'`. The first valid pin for a text wins, the server's or Map view's: a later post for that text moves nothing, and a pinned text is not asked again after a restart. /api/status's `holding`, and each entry of `orders`, says `pickupsPinned`, `pickupsHow` ([{by, from, asked}], `by` null for Map view's post) and, with nothing pinned, `pickupsWhy` ('no house number', 'no card fix', pickInDisc's refusals in END_WHY's words, 'NucBox down'). With `NUCBOX_SEARCH` unset it asks nothing and says nothing. With two orders or an add-on trip, each order's own card is asked under that order. One change is on purpose: a planner pickup with no house number is no longer asked for its street. 3ca870a kept any agreeing answer, which is a point somewhere on a mile of road: it withholds the drop from any door within 150 m of that point, and it is the circle visitPickups marks the restaurant visited by. Map view still pins and posts such a pickup. A card-door pin is named by its text, so visitPickups can mark it visited (a `visit` row) as it does a planner's. `Assemble.heldPickup` also compares `pickupLine` and the bracket's door (`bracketDoor`, the same expression as map-view.js searchPlan's, which test_lint holds equal), so a navigation screen showing the store's door is refused as 'a pickup'. That closes the DoorDash pickupLine entry's Open note for heldPickup. The fake NucBox gains a restaurant 60 m from the door at 1985 Cobb Parkway; every name and address is invented. Checks: rpi/test_server.py 911 → 929 ('[server pickups]' 14: a DoorDash `pickupLine` pinned and the 60 m door 'door next to the pickup', Uber "Store (1981 Cobb Pkwy)", no house number asked nothing, a non-string `pickupLine` not kept, the type-word retry, first pin wins, a nameless post at the same position, restart restores and asks nothing, a popup's door beside the card's bracket, two orders, NucBox down asked once more, Map view's post; '[held pickups]' 2 and one changed, since a pickup outside the disc is now retried without its type word; '[auto arm]' 1; '[rough disc]' 1); tests/assemble.test.js 304 → 308; rpi/test_lint.py 356 → 358. 37 mutations: 36 killed by name; one was equivalent (a string test in `bracketDoor` that `exec` already makes), so the test was removed. The first run also left one alive (the card's bracket ask hidden by the field holding the same text), and the popup check now covers it. Checks that could never refuse anything were taken out before the run (a second first-pin test in the answer path, a disc test in the hook, a dedupe). This closes the guard entry's Open note: the guard no longer needs Map view. Open: a pickup with no house number anywhere on record is still unguarded unless Map view pins it; /api/status says `pickupsWhy: 'no house number'`.

**A pickup door with its town line lost was never searched (19 Oct night).** A Trip Planner pickup read "840 <Name> W. <Name> Parkway" with no town under it, and searchPlan read a place with no comma as a merchant's name, so the server's pickup pinning said "no house number" and nothing pinned the restaurant for the guard. `MV.bareDoor` now reads a text with no comma that opens with a house number, has a name, and ends in a street type (STREET_TYPES, a quadrant after it or none) as a street with its door; the disc bounds the search where the town would have, door level only (pickInDisc). One rule in searchPlan, so the held end, the planner's, the card's and DoorDash's pickup texts all take it. A name that opens with a number and ends in no type ("1000 Degrees Pizza") stays a name. Checks: mapview 3; test_server '[held pickups] a door with no town ...' (end and pickup both pinned by the fake NucBox). Mutations (catch-up, 21 Oct), bareDoor only: 8 run, 7 killed by name, 1 equivalent. 3 killed by the existing three checks; the opening `w.length < 3` was equivalent (the same count is asked after the quadrant comes off) and is gone, after which the final count is killed by "77 Ln"; the house number, the name word and the trailing dots survived and are killed by mapview's "...a name of three words ending in a type but no house number stays a name, as does a number and a road number" and "...with the reader's dots after its type, left off". mapview +2.

**A door on a court the NucBox held without its house numbers never armed (the owner, 19 Oct).** The Trip Planner gave "306 <Name> Ct, <Town>" right; the NucBox's Nominatim held the court and not house 306, so `endWhy` was 'no house number', there was no pin, and GPS arrival never armed. Common in subdivisions: OSM has the street, not the numbers. Now, after the door search ends 'nodoor' and the place fallback found nothing or had no place to ask, and only with `NUCBOX_STREETS` set, server.js `searchHeldStreet` asks the street index once (new `/api/streets/whole`, streets.js `whole`: every street of the name as printed, by `match`'s rules, that has a way inside the disc's box, each WHOLE — its ways joined at shared nodes, so two same-named courts are two streets — with its length and, up to `WHOLE_LINE_M` 2 km, its polylines). The rule (`shortStreetIn`): `how` exact, dir or junk (an ocr read is not the same name); exactly ONE such street touching the held card's disc (one too long to send its shape counts: unknown is not none); and its whole length at most `SHORT_STREET_M` = 600 m, CHOSEN, not measured (no subdivision geometry in the repo). Then the pin is `by: 'street'` with `lines` and `metres`, and arrival, LEAVE and the restaurant guard all measure to the nearest point of the polyline (`pinMetres`, MV.nearestOn), with the same ARRIVE_M + capped error, DWELL 60 s, LEAVE 300 m on two fixes and PICKUP_GUARD_M 150 m. Otherwise the earlier refusal stands unchanged. Cached (nbxCache), never the public geocoder, nothing with `NUCBOX_STREETS` unset. The panel says "● armed by street" (live.html, that string only). The NucBox runs this server.js and needs a pull and restart to answer `/api/streets/whole`. Checks: tests/streets.test.js 88 → 95 (one court of two ways measured whole past the box, two courts of one name two streets, a street past 2 km said by length alone, no box, the endpoint and its box refusal); rpi/test_server.py 971 → 981, '[street arm]' 10 (a short court armed by street and asked once; arrival at its far end, 270 m from the pin's point; staying near; leaving drops once by the GPS; a 1.2 km road refused; two courts refused; the cache; a pickup 55 m from the street's far end disarms it and nothing drops; `NUCBOX_STREETS` unset asks nothing). Mutation testing skipped (fast lane). Open: the cap is a guess, and a street pin's lat/lon is its first node, and whether any page draws that point as a door was not checked. Mutations (catch-up, 21 Oct): 16 run, 16 killed by name. streets.whole 4 (the union at shared nodes, WHOLE_LINE_M, a street with no way in the box, no box): killed by the existing shapes. server 12: 6 killed by '[street arm]' and '[auto arm]'; 6 survived and are now killed by new '[street arm]' checks: an `ocr` read is refused ("21 Eliis Ct"), a court beside a street of its name too long to send ("40 Quarrel Ct") is one of two, one court touching a 0.7 mi card's disc and the other only its box arms ("77 Fennick Ct"), the street after a place found nowhere and after one too short to ask, and a read with no type word is not asked even where the index holds a street of that bare name ("12 Pembury"). The fake NucBox gains Ellis Court, the two Quarrel Courts and Pembury (invented). test_server +6. Mutations (catch-up, 21 Oct; the panel's string only): 2 run, both survived — no check read "● armed by street" — and are now killed by test_dashboard '[street arm] an end the server armed by the short street says so' (said as "● armed", said as "● armed by place"). The offers page's In car list said "● armed" for a street pin where the panel says "● armed by street"; journal.html's endSaid now says it too (test_offerspage '[in car list] four in the car').

**Map view said NO PIN over a held end the server had armed (the owner, 19 Oct).** With the end armed by street on the short street, Map view's own search showed "NO PIN · 305 …, street found, not that door" and drew no D: neither /api/status nor the beat carried the pin's point. Now heldEndState carries `endAt` ({lat, lon} of the pin, a street pin's first node; null with none), so /api/status, the beat and the mark reply have it, and live.html keeps it on `heldSaid`. In askNucBox, when the held end's own search finds no point and the server pinned that same end text (`serverEnd`: endPinned, endBy 'server', 'place' or 'street', endAt), the server's point is drawn as D in place of the refusal, and never posted back; a pin of Map view's own post (endBy null) is not taken. The map's key carries it, so a pin learnt on a beat redraws. Checks: test_dashboard '[server pin]' (drawn at its point, no "not that door", endBy null not drawn); test_server's beat and mark-reply shapes. Mutation testing skipped (fast lane). Open: the D is drawn at the street's first node, not where on the street the door is. Mutations (catch-up, 21 Oct; live.html): 6 run, 1 killed by the existing check, 4 survivors killed by checks added here, 1 equivalent. 'street' out of SERVER_PINS killed by '[server pin] Map view draws the held end the server armed by street as D'. Survived and now killed by test_dashboard '[server pin] ...nor a point the server does not say is pinned; and a pin the server makes later, said on a beat for the same card, is drawn then, and never posted back as Map view's door': `endPinned` not tested, the server's pin posted back to /api/held-end (an end text "4821, Kestrel Dr" that MV.hasDoor reads as a door), the pin left out of the map's key, `endAt` not kept off the beat. serverEnd's test of the end text against heldSaid.dropoff was equivalent (it is only asked for `heldEnds`, set with heldSaid from the same description) and is removed.

**How long the car waits at a restaurant was measured nowhere the rig could read it back (the owner, 22 Oct: "make the tool more hands-free and better for optimizing deliveries").** The on-time hint allowed a CHOSEN `PICKUP_ALLOW_S` = 300 s at every pickup, and the shift report's restaurant minutes were printed per order after the shift and read by nothing. **History:** server.js keeps one wait per held order whose pickup was pinned and visited BY THE GPS (visitPickups' `visit` row by 'gps'): from the start of the dwell that arrived (`dwellFrom`, on the pickup's record in holding.json, so a restart while waiting keeps it) to the last counted fix inside the arrive radius (stepAt's new `nearAt`, which changes no answer stepAt gives) — not to the visit, which is written a minute of driving later (96 s and 56 s on 12 Oct). Keyed by the pin rounded to `STORE_GRID_DEG` = 0.0005° (about 55 by 46 m here) and the store's name as Assemble.storeKey writes it; the name is the card's pickup less Uber's bracketed street (Assemble.storeOf, now exported), else the Trip Planner's name for that stop, and a "name" that starts with a house number or holds an " & " is no name and is not kept. Two stores visited together at one stop are one wait, under the pin the car stood at; a planner's visit has no dwell and no wait. Kept in rpi/store-waits.json beside the journal (git-ignored, with its `.part`; test_lint found both): the newest `STORE_WAITS_KEEP` = 10 waits of each store, `STORE_WAITS_MAX` = 500 stores waited at most recently, the rounded cell and nothing finer, written through a temporary and a rename, a file that does not parse said at boot and rewritten by the next wait. **Not backfilled:** a `visit` row carries the hold, the pickup's index and when the car had left, and by the journal's Settled rule no position; the pins live in holding.json only while the order is held, and no row holds a dwell's start. So nothing in the journal can be keyed by a store's place, and the history begins with this build; the visit rows are unchanged (checked). **Said:** `storeWaitFor(name, pin)` gives {n, avgMin, medianS} over every store of that name (sameStore, one i/l slip) within `STORE_NEAR_M` = SAME_SPOT_M (150 m) of the pickup's pin, or, with no pin, a name that is not a chain's (Assemble.chainName) whose stores on record are all one place; under `STORE_WAITS_MIN` = 2 visits, nothing. The reading carries `storeWait: {n, avgMin}` for the held order's own card (its first named pickup pin) or the offer (its pin from the early search when the offer line on record is this card, the line's pickup where the reading names none), and live.html's place line says "waited ~4 min avg (3) ·" after the same-store note, before the pickup (waitNote; its own separator, since the 3.5" hat puts the note's away), the mean in whole minutes, at least 1. **Hint:** onTimeInputs allows each pickup that store's median (`aWaitS` for the held order's pickup ahead, `bWaitS` for the offer's), PICKUP_ALLOW_S with under two on record; the verdict, the state, the range and the pair row's fields do not move. Descriptive only: no floor, no pace, no minutes from distance — every second in it is a clock reading less another. **Report:** tools/shift_report.py prints "Restaurant waits": by store name, the day's orders whose pickup the GPS visited once, with a stop found before the row, their count and median restaurant minutes; a planner's visit, two visits or no name are counted apart. The store's name is the one thing off a pickup the report prints, there alone; the bracketed street, the dropoff and every coordinate still never (checked). Checks: rpi/test_server.py 1052 → 1063 ('[store waits]': a 3-minute stop one wait of 180-190 s; kept at the cell, the name less its bracket; one visit says nothing; a second joins the first; a door is kept under no name; two visits, no pin: `{n: 2, avgMin: 3}`, the verdict the reading's own; another store none; the visit rows unchanged; after a restart; through tests/fake-nucbox.js, the 11-minute offer that is "② late ~3" with 300 s is "both on time" with a 60 s median and "② late ~8" with 600 s, and one wait leaves it ~3 with no note), rpi/test_dashboard.py 1368 → 1371 (the note after "same store as in car", nothing else on the card moving, none for one visit, alone with no order held, ~1 min under half a minute), rpi/test_layout.py 4330 → 4336 ("waited ~12 min avg (10)" whole on the address line after "same store as ②" at 1024x600 and 800x480 in both pictures; on the 3.5" hat that card's address line is put away, and the note with it), tools/test_shift_report.py 141 → 148 ('[waits]'), rpi/test_lint.py 357 → 359. Fast lane: not mutation-tested, the full suite not run. Open: on the 3.5" hat, where the address line is put away (measured under an offer with two orders in the car), the note goes with it and is not moved to the pair line; the hint's held pickup is its first named pin, not the planner's next; the history is per rig, and a store's first two visits say nothing.

**Six of nine pickups had no wait because a wait needed a pin (the owner, after the 7 Nov 2026 shift: "tonight seemed worse than usual with long wait times for many restaurants" … "I seemed to spend too long waiting for orders that reduced how much I could make substantially").** The shift report for 2026-11-07: 7 reliable orders, median actual/card 1.32 (usual 1.13), a 14-minute card that took 31.6 ($34.89/hr card, $17.45/hr actual) — and "Restaurant waits" measured ONE store (16.8 min), with "1 order waited with no one store to put it to": the wait was measured only at a pickup's GPS visit, and 6 of the 9 pickups were unpinned ("not inside the card's reach", "no door, place not found", "no house number"). **Report:** tools/shift_report.py `stop_waits` times a pickup with no GPS visit off the stop pattern: the first stop of `STOP_WAIT_MIN_S` = 120 s or more after the Took (stops(), the file's own rule: every fix within STOP_M of the first) that does not run into the order's end (`e >= end - NEAR_S`: the door) and is not another order's (another order's GPS visit or end at it, by dwell's rule) nor this order's own GPS visit; on a batch (the record's `card.stores`, two or more) one stop per unvisited pickup in the record's order. A GPS visit's minutes now go to the pickup its row names (`visitsPickup`, `visitSpans`). `waits()` gives per store n, `visits` and `stopWaits` apart, the median and the worst, a stop two orders shared once; the text adds a line per order (its wait, how found, card minutes against the clock split into waiting and the rest, card $/hr against actual), the shift's minutes at stores and their share of the rig's logging span, and "what waits cost" (`wait_totals`), all descriptive; the `--json` carries minutes and `from`, never a store's name (its "no place" check stands). With no log, the record's `stop` is read and said "the server's". **Server:** `stopWatchStep` keeps the car's stops off each beat's fix (within `STOP_WAIT_M` = 50 m of the first, no silence over GAP_MS, `STOP_WAIT_MIN_MS` = 120 s; in memory, the newest `STOP_LOG_MAX` = 60); at a delivery's end orderRow runs `stopWaitsOf`: the same rule (`STOP_NEAR_MS` = 120 s before the end is the door; another order's end, `stopEnds`, or within SAME_SPOT_M of another held order's pickup pin or of one of this order's GPS-visited pins, refuses a stop; a stop under way at the Took counts from it), writes `stop: {from, s}` on the record's unvisited pickup — two times, no position — and `storeStopHeard` keeps the wait in store-waits.json, `how: 'stop'`, under the card's store name and the cell of the CAR'S stop, one wait per stop. storeWaitsOut adds `stops` and `worstMin`; the places report's Store waits tab shows "worst wait" and "from the stop pattern", the Restaurants tab the worst after the median. Never an approximate point: the stop is the car's fixes, the name the card's. CHOSEN, NOT MEASURED: 120 s (the owner's "2 min"), 50 m, the door's 120 s. Checks: tools/test_shift_report.py 252 → 267 ('[stop waits]', an invented evening: a 90 s light not a store, the door not a store, a stop at another order's pinned pickup skipped, a batch's two stops in order, no stop no wait and said why, per store n/visits/stops/median/worst, the share, the cost, the text, no name in the JSON, the record's stop with no log), rpi/test_server.py ('[stop waits]': an unpinned pickup's record carries the stop and no place; the store's wait kept `how: 'stop'`, the door's stop none; a second, and storeWaitsOut's `stops` 2 and worst), tests/placesreport.test.js 366 → 369. Open: a two-minute stop on the way (a long light, a drive-through queue) is taken for the store and a store waited at under two minutes is unmeasured; the live rule cannot see another order's pinned pickup that was never visited unless its pin is held; not replayed against the 7 Nov GPS log, which this container does not hold.

**The card's store note said every hour's waits from two visits, so an evening that ran long said nothing different (the owner, 7 Nov 2026: "tonight seemed worse than usual with long wait times for many restaurants").** Checked against Settled first: "Do not re-time an offer at a pace" refuses any change to an offer's $/hr, verdict or range by an expected time, and the 20 Oct decision allows a store's median wait in the on-time hint only; neither forbids a note that moves nothing, which is what the 22 Oct note already was. So: server.js `storeWaitNote(name, pin, now)` — the stores storeWaitFor would read (its answer is the gate: a chain's branch with no pin, or a name at more than one place, says nothing), their waits at a GPS visit AND from the stop pattern (`how: 'stop'`, the entry above), only those whose local time of day is within `STORE_WAIT_HOURS_MS` = 2 h of now's either way round midnight, at least `STORE_WAIT_NOTE_MIN` = 3 of them, the median in whole minutes (at least 1). The reading carries `storeWait: {n, usualMin}` in place of `{n, avgMin}`, and live.html waitNote says "usually ~12 min wait (n=5) ·" where "waited ~4 min avg (3) ·" was, the store's own name being the pickup right after it on the line. The $/hr, the verdict, the target, the state and the range are the reading's own (checked); the on-time hint still reads storeWaitFor's median over the newest ten, all hours, as before. CHOSEN, NOT MEASURED: two hours, three waits; STORE_WAITS_KEEP stays 10 per store, so a store visited mostly at lunch may hold few evening waits. Checks: rpi/test_server.py ('[store waits]': two visits say nothing now, three say `{n: 3, usualMin: 3}` with the state, $/hr and target the reading's; after a restart; the same three shifted six hours say nothing; '[stop waits]': three stop-pattern waits make the note; the on-time fixture's waits stamped this hour, `{n: 3, usualMin: 1}`), rpi/test_dashboard.py ("usually ~4 min wait (n=3) ·" after the same-store note, nothing else moved, two waits nothing, ~1 min alone), rpi/test_layout.py ("usually ~12 min wait (n=10) ·" whole on the address line at 1024x600 and 800x480 in both pictures; on the 3.5" hat put away with the line, as before). Open: as the 22 Oct entry's — the hat drops it with the address line, and the history is per rig.

**A Drop pressed early to keep the stacking honest lost the delivery's real end (the owner, 29 Oct 2026: "I do drop deliveries early to avoid it computing the value for incoming deliveries that won't be stacked onto the order I am running, could it let me drop it so the computing is treated normally but track the GPS points?" — then "Go ahead and build it, fast track to experimental").** A press of Drop or the chooser's put-down is unchanged for everything that computes: the order leaves the list, the stack line and advice weigh the next card alone, the drop row is putDown's as before (`by` absent or 'chooser'), ↶ Undo is offered. What is added (server.js finishWatch, "finishing a dropped order") is a background watch, never in the list: the order's end and its window, kept in finishing.json beside the journal (holding.json's write: temporary and rename, synchronous, only when a watch opens, moves, finishes or is forgotten; read back at boot after the list), stepped on every heartbeat from the same fixes the GPS drop counts (countableFix). It ends with one row, `{v: 1, kind: 'finished', at, id, seq, holdId, how, dropAt}` (ids and times only; `seq` = `at`, the stop's start; `dropAt` the drop row's `at`), and nothing else — no panel word, no bar control (Settled: no seventh), no verdict or advice, no GPS drop of an order in the car, nothing pressed on the phone. `how`: 'door' — a door-level pin the GPS drop would arm on (not beside a pickup, one customer), arrived at by stepAt, the GPS drop's own rule (ARRIVE_M + error capped at 25, GPS_DWELL_MS, GAP_MS); 'area' — no pin, an approximate endArea: the first stop (every fix within the arrive radius of its first, for the dwell, no silence over GAP_MS) whose first fix is within FINISH_AREA_M (150 m) of the area, or half its spread where larger, capped at FINISH_AREA_CAP_M (400 m); 'stop' — no end: the first such stop once the car has been FINISH_MOVE_MI (0.2 mi) from the last good fix at the press (or the first after it), the weakest, said as such by every reader. Window: holdEnds (card minutes × 1.5 + HOLD_GRACE_MS from the Took); past it no row and the watch is forgotten; a new Took does not end one; at most FINISH_MAX (3), oldest dropped. No watch for an order with no stated minutes or one the GPS had already seen arrive (the press was at the door); setHeld forgets the watch of any order back in the car, which is how ↶ Undo cancels it. Not `kind: 'delivered'`, as proposed: that kind is already the completion screen's row (deliveredArrived), a different shape. Readers: tools/shift_report.py (_finished) ends a Drop/chooser order at the finished row its `dropAt` names, "Drop -> GPS 'door'" ('area', 'stop'), timed and reliable, `finished` on the order and in the JSON; server.js takenRuns gives such a run `by: 'finished-<how>'`, `endedAt` the finish, `pressedAt`/`pressedBy`, counted at the door by cardVsReal (atDoor) and by journal.html's "Card against what it took"; tools/places_report.js counts the three as at the door and real (FINISHED in AT_THE_DOOR and REAL_BY), and its GPS press-timing (timePresses) reads 'drop'/'chooser' only, so it applies to presses with no finished row. Chosen, not measured: 150 m, 400 m, 0.2 mi, 3 watches. No fix speed is on the beat, so "stopped" is the shift report's own stop shape; a gate-refused run resets a stop here (later, never earlier). Experimental, fast lane: no replay against a real shift yet.

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

**One read's whole dollar, printed with neither cents nor label, was priced on
the phone (16596d3's Open: "the phone's scanner (scan.js) reads single frames
and has no pair to wait for").** The Pi holds such a figure off its panel
until a second frame agrees (`scan_pi.unsure_payout`); `scan.js` painted
every complete read as it came, so the UberX glare frame's text — `$ 5 eee at
MRCS RE IN 8`, $5.00 for a $16.05 card, one sensor seed of five — put "PASS ?",
$5.00 and a rate over 23 minutes on the glass for a read. It never locked
(the read after did not agree), so it reached neither the buzz nor the
journal. The lock's own count is the agreement: `payHeld` holds a read's
payout when it is printed neither to the cent nor with its label or star
(`OfferParser.payIsPrinted`, asked of the read's text in `readOnce`) and
`agree` is under AGREE_TO_LOCK. Held is shown, never hidden: no payout and no
verdict, the card's minutes and miles still there, CONFIRMING THE PAY where
POINT AT THE OFFER would stand, and the note "Pay read without its cents or
its label — waiting for a second read to agree." A photo, which has no read
after it, holds it the same way and neither locks nor records it; another
photo is another read. Agreement, the lock and the journal are otherwise
untouched, and the harness's `consider(parsed)` with no text is not asked.
Checks: test_scanjs +9 (the glare text through `consider` with its text: held,
"--", the label and the note; the card's next read shown at $16.05; `$19 |
Guaranteed` held one read, then shown and locked when the next agrees; `$7
Guaranteed` and `$14 incl. tips` shown off one read; no text, not held).
Open: a photo of a whole-dollar card with a mark before its label (`$19 |
Guaranteed`) is never priced by Photo, as two photos do not agree with each
other; and the photo's hold is driven by no check (no rendered card reads
unprinted through the browser's reader to drive it with).

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

**Every verdict was net of a cost per mile nobody chose.** costPerMile was 0.3 on all 1,166 rows of the real week. That is the factory seed, set in rpi/config.json and read once at startup. Measured with rate() over week.csv, which reproduces the rig's 106 recorded greens, the week at $0.00/0.15/0.30/0.45/0.70 a mile has 290/181/106/78/52 green cards and 146.6/88.7/46.0/31.4/21.5 green job-hours. The fix is `/api/settings` in `server.js`, which takes costPerMile and no other key. It writes through the handoff dir under partName(). `rpi/scan_pi.py` takes the request in the loop (settings_requested), mutates cfg['settings'] in place, saves the file, re-reads the card on the phone, and reports the figure on the stream. GET answers from that report. SCANNER=0 answers scanner:false, and a POST there gets 409. Traps: the block also holds keepPlaces (whether addresses reach the journal) and pad/secondsPerItem (every stored rate), so the route and the reader both whitelist the KEY. PL.Scanner's startup settings copy fed only a rate digest() overwrote, so it was deleted, not guarded. The scanner stays the only writer of config.json. The taker claims the request by rename: read-then-clear deleted a second POST that landed in between. The keypad says the scanner is not running rather than promising a next reading. Checks: test_server, test_loop, test_pipeline, test_scan_pi ('...taken next, not deleted unread'), test_keypad, test_lint.

**The keypad's Targets sheet did not say whose settings it changes, then said it twice.** The panel puts ⌨ Type one press from the verdict. A target typed on the sheet moved the keypad's colours and nothing the panel said. A sentence at the top of the sheet in `index.html` (#settingsWhere) now says it changes this browser only, with cost per mile the one exception. The bottom note's 'Settings and history stay on this phone' was a second answer on the same sheet, and false after cost per mile could reach the rig. It now speaks about history only, and README.md's Targets paragraph was corrected to match. Checks: test_keypad '...and no other line on the sheet says where the settings go', test_lint '...which does not say the settings stay on the phone while the keypad sends cost per mile to the rig'.

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

### The camera

**The rig read once in 9.4 days, with the heartbeat beating and the panel saying
"scanner reading". The panel now says when the camera cannot see, and it says
only what the rig knows.** The scanner keeps one settled word for what the
camera can see: `seeing`, `stalled` or `dark`. That word reaches the driver five
ways:
- on the heartbeat, as `blind`;
- in the journal, as `camera` up rows;
- in the verdict's place on the panel: red, a dashed border, ⚠, and never PASS;
- as a red connection dot beside "scanner running, cannot see";
- in doctor's "the camera can see".

Once the panel has been told of a stall, the scanner goes quiet so that
server.js's silence watchdog restarts it. It does this at most once in ten
minutes (`STALL_AGAIN`, kept as a `.stalled` note in the handoff directory). A
stall inside those ten minutes stays up and keeps beating the word. Each stall
in a run is judged afresh, and only a stall ever leaves the note. Nothing is
read off a frozen picture: a frozen card re-read on the verify beat had kept the
watchdog from ever firing.

*Stalled* means a preview frame that is byte-identical to one of the last eight
frames. A frame with no pixel strictly between its lowest and highest value
does not count. The watch keeps eight because the camera cycles four buffers and
a read's extra capture never reaches it. Measured on a fake camera handing back
its four buffers in turn, three runs each:
- one frame kept, or four: never called stalled in 12.5 s;
- eight kept: called stalled at 6.8-7.1 s.

The premise that a working sensor never repeats a frame comes from testcards'
noise model, not from the IMX519. So every repeat is counted, on the health line
("N frames since start the same picture as one of the 8 before it — none, if the
sensor model the stall watch rests on holds for this camera") and on every
`seen` row (`repeats`). The suites' fake cameras had handed over the same bytes
1,199 times in 1,200, so they had been modelling a stalled camera all along.
They now flip a different half of the pixels on every capture; with only two
patterns taken in turn, a still card was called stalled at 7.3-7.6 s.

*Dark* is AutoGain's `lit` (the box's 90th percentile against LIT_ENOUGH, which
is 20) staying false for a minute on a hand-drawn box. Its first wording,
NOTHING IN VIEW / "put the phone in the mount", told a driver whose phone was
lit in the mount that it was not there. Its second, TOO DARK TO SEE / "No lit
screen the rig can see in its box", was still more than the rig knows. It is now
**TOO DARK TO BE SURE**, with the line "The rig may miss an offer arriving in a
box this dark — check the phone is in the mount with its screen on, and turn its
brightness up."

Measured on testcards' Uber card in a cabin reading 2, the motion gate's score
for a card arriving, against the 6.0 it needs (eight noise draws per level,
spread 0.02 at most):

| mode | box reading → gate score (draws noticed) |
|---|---|
| dark | 13 → 5.52 (0/8) |
| dark | 14 → 5.72 (0/8) or 6.04 (8/8), depending on the brightness behind the reading |
| dark | 15 → 6.27 (8/8); 19 → 7.90 (8/8) |
| light | 18 → 2.23 (0/8); 53 → 5.72 (0/8); 56 → 6.03 (8/8) |

The reading cannot tell dark mode from light mode, and under LIT_ENOUGH the gain
is held. So the most the rig can say is that it cannot be sure of seeing a card
arrive.

CAMERA STALLED said "The rig restarts it" even while it was sitting a stall out.
Its line now reads "The rig restarts it at most once in ten minutes; if this
stays or keeps coming back, reseat its cable."

Found on the way:
- The check "...and never as too dim" read the wire key `tooDim` off the loop's
  arguments, where it never appears, and it started the gain at 1.5. Both had to
  change before the check could fail.
- A box of pure black kept the previous beat's too_dim through an early return.
- `repeats` reached the tally but was dropped by the `seen` row.
- doctor read a dead run's word as current after a power cut that left no stop
  row. It now asks only while an `rpi/scan_pi.py` process is running, and with
  nothing scanning it prints "whether the camera can see — not asked" instead of
  a pass mark beside "the camera can see".
- doctor's age check imported scan_pi inside the journal's try. A failed import
  was reported as "the journal file is whole: FAIL" and skipped "the journal can
  be written". The camera check now has a try of its own.
- The per-stall reset and the rule that only a stall leaves the note had no
  checks; removing either now fails a named check.
- test_loop's runs shared /dev/shm. A stuck read made to leave the note wrote
  /dev/shm/uberscan-stalled while still passing all four of its checks. Every
  run now gets a handoff directory of its own.

72 mutations across the three rounds (31 + 31 + 10), each caught by name.

Merged onto the parser, panel, planner and snaps work, the word met two other
lines of the panel. The line under the verdict had become `noVerdictSaid` (The
panel, below), and under the word it stays empty. The reading it would be said
of is the one before the word, or one off a frozen picture, and "box may cut it
off" would send the driver to ▣ Set box over a camera that cannot see. With the
guard taken out, "...with no line claiming there is no offer, or a box cutting
the pay off, on a screen it cannot see" fails at all three panels, reading
"pay, no time — box may cut it off". The Trip Planner's stops are drawn in the
same between-offers branch the word takes, so the two share the card, and the
stops fold for the word's line as for any notice. At 800x480 and 1024x600 the
line stays whole beside all four stops. On the 3.5" hat's screen picture the
stops go down to their one counting line and the line keeps 93 of 93px. With
the fold switched off, the hat's line kept 47 of 93px in the screen picture
and 26 in the scene one, and "...and its line shows all it says, or the stops
are down to the one line that counts them" failed by name.

Open:
- No frame off the real IMX519 has been measured, so the stall premise rests on
  the `repeats` count from real shifts.
- A lit dark-mode screen reading 15-19, and some reading 14, is called TOO DARK
  TO BE SURE, although the gate would notice a card on it. The line says "may",
  and the word clears at the first read.
- Dark cannot see an empty mount in daylight, and sees nothing at all on a rig
  run with a fixed `--gain`.
- The cv2 `--display` panel and the voice do not say the camera's word.
- On the 3.5" hat's scene picture the line is cut with no stops under it at
  all. It has 130px; the dark line needs 139 and the stalled one 162. The check
  written for the merge found this; the stops did not cause it. The line was
  measured whole in the phone layout only.

### The clock

**A clock that is merely WRONG passed every guard in the rig, and the driver
found it.** Reported from the seat: "the time stamps are wrong on the offers
page, they show 4am when it is 9pm". Twenty-five offers reached the journal
stamped `1790409639879` onwards — 2026-09-26 08:00:39 UTC — when they were
really read about seven hours earlier, and the offers page rendered that as
4:00 AM in the viewer's own timezone, faithfully. The page was not the fault.
`at` is `int(time.time() * 1000)` off the Pi's own clock, with no timezone or
offset anywhere in the path, so the stored number was simply untrue.

*Nothing had a chance of catching it.* `CLOCK_BELIEVABLE_AFTER` wants only that
the year be 2025 or later; `futureCeiling` in `server.js` allows a whole day of
slack; and the panel shows no wall clock at all, so there was nothing on the rig
to disagree with. Between them they cover a Pi that boots in 1970 and a row
stamped in the year 5138, and they leave the whole space in the middle open.

*The money survived THIS error, and only this size of it.* A duration card
carries its own minutes, so 25 of 25 of these rows rate correctly. A DELIVERY
card takes its minutes from "deliver by 21:40" minus now, and `minutes_until`
wraps a negative gap by 24 hours, so a seven-hour skew turns a 45-minute job into
a seventeen-hour one and `SANE_MINUTES` refuses it. A SMALLER skew is not
refused: 25 to 39 minutes fast turns a $11.52/hr PASS into a confident GO with no
doubt flag, measured below under "doctor.py said a wrong clock". The owner has
declined a guard for it; this entry said the money was safe, and it was not.

*What CAN be seen is the correction, and it is permanent.* The journal is
append-only and written in order by one process, so `at` never goes backwards on
a rig — and NTP fixes a fast clock by stepping it BACKWARDS. That step stays in
the file for ever, and it names both that the clock was wrong and by how much,
months after the shift. `rpi/doctor.py` now reads it: on a replayed journal of 25
rows written seven hours fast followed by 15 written after the step, it reports
**"15 rows stamped before a row written earlier, by up to 7.1 hours"** and says
in the remedy that the file cannot be put right, being append-only, and that it
is the EARLIER rows which carry the wrong time.

Quiet on an ordinary shift, on one row, and on an empty file — and quiet on a
row from before the clock was set, which is a different fault with its own
handling and would otherwise read as a step. Not run on the copy machine, where
a backwards step is ordinary: the sync sends archives oldest-first, so `--all`
into a copy holding newer rows appends older ones after them, legitimately.

Five mutations. Four kill a named check; the fifth — taking the last row's stamp
as the high-water mark instead of the highest seen — is caught by the count of
affected rows rather than by the verdict, because on a journal that runs forwards
the two are the same walk.

*Still open.* The rows already written cannot be corrected, only identified. An
annotation row carrying a measured offset, applied by the fold the way a `mark`
is, would let the pages show the true time without editing history — it is the
shape this project already uses for corrections, and it is not built.

**doctor.py said a wrong clock leaves 'the money protected'. It does not.** Measured on rpi/offer_parser.py at SEED_SETTINGS, with the card $10.86 / 7.4 mi / Deliver by 9:15 PM read at a true 8:30 PM, stepping the clock one minute at a time:
- +0 is 45 min, $11.52/hr PASS
- +21..+24 is CLOSE CALL
- +25..+39 is a confident GO with no doubt (+30: 15 min, $34.56/hr)
- +40..+43 is doubt speed
- +44 is doubt time
- +420 (the seven-hour error that happened) is doubt time

The JS port agrees at +0, +30 and +44. The owner declined a clock guard. doctor finds the backwards step afterwards. The comment now says so, and does not re-argue the decision. advice.js's in-time bullet no longer gives '0 of 836 stated a deadline' as the reason; the count is 0 of 1,166 too. The question is not asked because nothing on record can check it and its minutes come off the clock. Checks: 'doctor.py no longer says a wrong clock leaves the money protected', 'advice.js no longer says a deadline card has nothing to measure against'.

**The Pi's clock at boot: GPS logs named for a stale minute, their first fixes stamped early, and the NucBox's "since" on the old clock (the owner's 26 Oct shift).** No real-time clock: after a reboot the Pi runs from the time saved at shutdown until NTP answers. The day's logs: `2026-10-26_1415` began at 14:30 (136 fixes, mode 3, stamped 923 s early, then a step), `2026-10-26_1526` at 17:38 (a 7,925 s step at line 30, before any fix), and the reboot's `2026-10-27_0004` at 00:59 (3,285 s, line 30). **Changed:** (a) tools/gpslog_name.py names a new log by gpsd's first fix's own UTC `time` (local minute, the shape shift_report reads), waiting up to two minutes, else by the clock, marked `-unsynced` unless `timedatectl` says NTP set it (a name shift_report reads for every day); rpi/README's gpspipe line uses it. Start.sh is not tracked: a Start.sh that names its log off `date` must be changed on the rig. (b) shift_report.load_fixes (and places_report through it) measures each step of the clock inside a log against the TPVs' own `time` (clock_steps: the stamps moved more than the GPS's clock did, past CLOCK_STEP_S, 60 s: a gpsd stall moves both alike, a receiver's own ~20 s leap-second offset stays under it) and moves every line before the step onto the clock after it, saying how many on the GPS line and in the JSON (`clockSteps`, `restamped`). A step with no GPS time on its far side moves nothing; the lines before such a step on 26 Oct carried no fix. On the 26 Oct `_1415`/`_1329` pair: 1 step, 136 fixes re-stamped; `_1526` and `_0004`: none measurable, no fix lost. (c) server.js nbxNote: a step of the wall clock against the monotonic one between two notes past 60 s moves every service's `since` and `at` by it, and logs it. Checks: tools/test_gpslog_tidy.py '[name]' +7, tools/test_shift_report.py '[clock step]' +6 and '[log name]' +1, rpi/test_server.py '[nucbox health]' +1. Not done: setting the Pi's clock from the GPS (gpsd's SHM into chrony) — the fix the rest of this works round; a system change for the owner.

### The backup

**The backup read one file where the card holds three, and sent a window where
the copy holds nothing.** Two separate holes in the only copy of the one artefact
this project calls irreplaceable, both ending with exit 0, a fresh `.synced`
stamp and `doctor` green. Measured against a real `server.js`:

| what the card held | what `rpi/sync.py` sent | what it said |
|---|---|---|
| 1,200 offers across two rolls | **100** | "sent 100 row(s) … now holds 100", `--all` |
| 905 offers over 90 days, empty copy | **302**, then nothing for ever | "sent 302 … 302 were new", exit 0 |

*The roll.* `rpi/journal.py`'s backstop moves the live file aside at 64MB and keeps
every roll, and nothing in the repository ever read one back — `server.js` stats
`.1`'s mtime and reads nothing. `rows_since` and the shortfall count both saw the
live file alone, so `--all`, whose own help says "send the whole journal", sent
the tail of it. Both now walk the chain oldest-first.

*And the roll is a season, not a lifetime.* `rpi/sync.py`'s docstring says "about
19MB a year" while `rpi/journal.py`'s own `last()` says "a year of driving — 40,000
rows, 68MB", which already exceeds the cap: the repository contradicts itself
about whether its own backstop can fire. Replaying the real week's frames through
the real accumulator gives 2.8 rows an offer and 5.7MB a week, so about four rolls
a year — and that is a floor, because the replay writes no `seen`, `screen`,
`pair` or `mark` rows.

*The window could not see across a roll either,* and that is why the count alone
was not enough: every archived row is older than `--days` by construction, so
`settled` saw ten rows against the copy's ten and called it even with fifty in
`.1`. A rolled card now also compares all-time counts, once, and only when it has
actually rolled.

*The empty copy was the other half.* `FIRST_RUN_DAYS` was documented as "what to
send when the far end has nothing, **or** cannot say what it has" and did both,
and the first half was the fault: a copy holding nothing is not a guess to be
bounded, it is a fresh install — the premise of the whole tool, and of the
documented `COPY=` migration that points JOURNAL at a new empty file. It cannot
self-repair either, and structurally: `settled` counts the rig's rows inside the
same window the first tick used, so the rows the window excluded are excluded
from the rig's own side and the two numbers agree. It converges only when the
newest row is hours old — that is, exactly when the rig is not scanning, which is
not when the timer runs.

*A damaged archive warns rather than blocking.* Extending the abort-on-unreadable
rule to the archives has a cost the live file does not: measured, a `.1` that
could not be opened made the first sync send NOTHING and exit 1, so a file
nothing had written to since the spring cost tonight's offers their backup. The
readable rows go, the warning names the file on stderr where `--quiet` cannot
silence it, and `--all` alone reports the failure — because `--all` is the run
that promised all of them.

*Two of the new checks were written wrong first.* One asserted the shortfall
across a roll and failed at 10 rows against 60, which was the fix being
incomplete rather than the check being wrong — the window, not the count. The
other called its fixture an ordinary tick while the copy was empty, so the
first-sync branch read the archives for a good reason and the check failed on its
own premise. Five mutations, five kills.

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

**That queue was right and was built for one endpoint out of three that needed
it.** `/api/places` does the same read, decide, write on a file two browsers
reach at once, and its own comment says what it was meant to do: "MERGED, never
written over. Two browsers place different days of the same journal, and a POST
that replaced the file would have whichever finished last throw the other's work
away." Measured against the real server — two concurrent POSTs of 600 places and
1, against a seeded 1,325-place file, ten runs:

| outcome | runs |
|---|---|
| `places.json` unparseable, `GET` answering `stored: 0` | 2 |
| one writer's whole batch lost, reply claiming `stored: 1925` over a file of 1,326 | 8 |
| correct | **0** |

The cache is what the Settled entry prices at 1,325 places and about 24 minutes
to rebuild, and the POST that destroyed it answered `ok: true`. With the queue,
ten of ten come out right at 1,926.

*One cure per fault, because two cures hid each other.* Three sites wrote a
fixed `<name>.part` where the crop endpoint appends a pid and a counter, and
`rpi/test_lint.py` had stated that rule in prose since it was written while
checking only that both name shapes are gitignored. Both cures were applied to
both endpoints first, and then neither could be tested: with the queue in place
the shared temporary is unreachable, and with unique names the missing queue
costs nothing the suite can see. So `/api/places` keeps the queue — it is the
lost update that costs the 24 minutes — and `/api/config/backup` keeps only the
unique name, because its read is a "has it changed" test and last-writer-wins is
the right answer there. Reverting either one now fails a named check.

*The rule is enforced rather than described.* `rpi/test_lint.py` reads both
files and asks of every `.part` it finds outside a comment that the line also
builds a name of its own. It failed as written, on two lines of prose inside a
`/* */` block — the check being wrong, not the file — and skips block
continuations now. Four sites, four mutations, four kills.

*What a missed release does here is documented rather than asserted.* The queue's
own comment already says a stranded request would hang every upload after it, and
on this endpoint that is what happens: the suite's second sequential POST hangs
and the file exits non-zero at that line. It is caught, but by a crash rather
than by a named check, so the check that follows the concurrent pair asks
separately whether a later batch is still answered.

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

**The journal's size was six unmeasured figures in twenty-one places, and the roll called a season of driving a bug.** Replaying week.csv's 1,166 offers from their own frames through the real OfferAccumulator, rate() and OfferLog.consider gives 3,265 rows, 2.80 rows an offer and 5,718,962 B a week. The busiest day was 2,278,585 B, the 64MB cap is 11.73 weeks, and a year of 52 such weeks is 297MB. The figure lives once, at journal.WEEK_BYTES. rpi/test_lint.py holds 21 quotations of '5.7MB a week' to it, each naming WEEK_BYTES within 300 characters, and refuses the retired yearly, per-shift and year-of-driving wordings. Trap: WEEK_BYTES is a FLOOR (the replay writes no seen, screen, pair or mark rows). The first roll message and doctor's free space both printed it as the rate, and the roll message called 'far fewer weeks' a fault, which is the false alarm again. Both now say 'at most'. Only rolls days apart are a fault: 64MB is 29 of the busiest day. Trap: the 150-265ms parse benchmark was a 20MB file of fifty thousand ~400 B rows, against the real 1,752 B a row. Re-timed with parseLines on 22.4MB / 12,766 real rows: 64-223ms over 48 runs (medians 87-93) on the development container. Not timed on a Pi 4. Rolls a year are 'at least four' (4.43 at the floor) everywhere. Checks: '...and every quotation is WEEK_BYTES' 5.7MB a week', 'no file gives the rolls a year as anything but "at least four"', 'no file gives the fifty-thousand-row benchmark as a real journal's parse', '...without reading fewer weeks than the floor as a fault'.

**A full SD card printed 'the journal can be written' and 'backed up N min ago' as two green lines over a stopped record.** Opening for append allocates nothing, so on a full card the open succeeds and the scanner fails later, at the write (ENOSPC). doctor.py now asks os.statvfs (f_bavail: the scanner is not root) and fails, and blocks, below FREE_WEEKS=4 x WEEK_BYTES = 22.9MB. It prints the free space either way, as 'at most' that many weeks. Trap avoided: no probe byte. This check once created the root-owned journal it was asking about. Trap: a statvfs that raises is not a read-only card, so it gets its own fix line. The fix line never tells the driver to delete the journal or its rolls. Checks: 'a card too small for a month of driving fails the write check' (a real 64kB tmpfs where mountable), 'a full card fails the write check though the journal opens for append' (stubbed statvfs), '...without blaming a read-only card', 'on a 64kB card the journal still opens for append' (this was once a literal True and could not fail).

**Persistent=true on the backup timer did nothing while its comment credited it with catching up missed runs.** systemd.timer(5): Persistent= 'only has an effect on timers configured with OnCalendar='. tools/install-sync.sh writes OnBootSec=2min + OnUnitActiveSec=10min, so OnBootSec is what runs a missed backup two minutes into the next boot. The line is deleted and its comment moved to OnBootSec. A rig installed earlier keeps the inert line until the installer is re-run. Checks: 'the sync timer runs at boot, which is what catches up a missed run', '...and sets no Persistent= on a timer with no OnCalendar= to obey it'.

**The rig never said when it stopped, crashed, lost the phone or lost its
GPS.** A rig whose phone GPS app had timed out wrote rows with no position,
exactly like one never given `--gps` (0 of 1,166 week rows carried one); the
server's crash counters reset on every restart; the health line's diagnostics
never left the Pi. The scanner now writes `kind: 'up'` rows on changes only — a
start (with GPS on or off and the Pi's uptime), a clean stop, the phone gone or
back after 60s, the GPS fix ok, stale or lost after 60s more — so a start with no
stop before it marks a crash or a power loss. The heartbeat carries the GPS
state and the Pi's temperature and throttling, `/api/status` carries the last
beat, and the panel's connection row says "GPS: no fix for N min" or "Pi
under-voltage" only when something is wrong. A skeptic found the first build
stamped up rows after a backwards NTP step hours wrong and could repeat ids
across boots (ids are now a random per-run token and a count), and doctor's
"stamps run forwards" failing on the start row a power-cut boot writes before
NTP (up rows are now set aside there).

Merged onto 📷 Snap, two answers had to become one. Snap had moved the status
answer into `statusNow()`, which a snap's status.json shares, so the heartbeat
went there rather than back into a second copy. And the health line's new
`seen` fields were a second computation of figures `counters()` already gave
Snap's reader.json from the same counters; `counters()` is now the one source
(with the median rounded and the flags plain booleans, as the row wanted), and
the health side adds only what it alone knows, the corners' state. A snap's
reader.json now carries the GPS and Pi fields of the last beat too, so it says
all of what the panel was told.

**A brownout in the car was seen only by `last -x` typed by hand (the 7 Nov 2026 shift: a boot with no shutdown before it, the server's "Uber Scan serving" at 04:09Z right after an order taken at 23:02 EST, and no software crash message anywhere).** The firmware's own witness, vcgencmd's since-boot under-voltage bit, rode the beat to the panel and the `seen` rows, and reached the log the driver pastes back nowhere. Now: scan_pi.PiHealth.warn_new logs "WARNING: the Pi reports under-voltage now (vcgencmd get_throttled) — check the power lead and the car's socket" the FIRST time each throttle word appears, now or since boot, once per word and half (the since-boot bits never clear until a reboot, so a line a sample would be noise); `power_part` puts "power: under-voltage now" / "power: under-voltage since boot" (and any other word beside it, "throttled since boot") on the health line, only when a word is set, before the crop (Health.report's new `pi`, PiHealth's `last`; still PI_EVERY = 30 s, a file read and one vcgencmd). server.js keeps run-state.json beside the journal (git-ignored with its `.part`): at start {v, boot, startedAt, clean: false}, `boot` the kernel's boot id (/proc/sys/kernel/random/boot_id; `BOOT_ID_FILE` for the suite); on SIGTERM/SIGINT {v, boot, stoppedAt, clean: true}, written before the exit. A start that finds `clean: false` says, beside the banner, "previous boot ended without a shutdown (power?)" when the boot id differs, "the server's previous run, this boot, ended without a clean stop (killed or crashed)" when it is the same, and a cause-unknown line with no id. Not `last -x`/wtmp: the server is not root, wtmp's format is the C library's, and the marker answers the one question asked — did the Pi go down under a running server. **Panel:** already there, checked and left: with under-voltage NOW the heat guard is on at the same sample and the connection row's chip says "LOW POWER" with no temperature beside it (rpi/test_dashboard.py 'a weak supply and a stale fix', 'LOW POWER · GPS: no fix for 123 min'; rpi/test_layout.py fits it at 480x320 and 800x480). Checks: rpi/test_scan_pi.py ('[power]': vcgencmd stubbed at 0x0, 0x50005 and 0x50000 — no warning, four warnings once, none again; power_part's six shapes; the health line with and without), rpi/test_server.py ('[run state]': a first start silent and marked unclean; SIGTERM marked clean; a clean stop silent; a SIGKILL then another boot id "previous boot ended without a shutdown (power?)" beside the banner; a SIGKILL in the same boot the server's own run, never "power?"). Open: a run-state.json from before this build is absent, so the first boot after the upgrade says nothing; a SIGKILL by systemd's stop timeout at a real shutdown reads as "killed" this boot, or "power?" across the reboot — the scanner's `up` rows and `last -x` still tell the two apart.

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

**The fourth figure in the raw row was the net one.** The submetrics under the
headline are the readout a driver checks against the phone in the two seconds
before a card times out, and three of them matched it. The fourth was `perMile`
off the reading, which is (pay − miles × costPerMile) ÷ miles — so $14.00 over
7.0 mi printed $1.70 sitting between the two boxes that divide to $2.00, and
nothing on the glass closed the gap unless the driver already knew what the rig
charges a mile. It is now pay ÷ miles. Nothing is withheld by that: the working
line directly below spells the deduction out in full, and the offers page and
the keypad both still carry the net rate, the keypad in a row that says "net
per mile" and means it.

*A cross-check, not a decision rule.* Settled's measurement stands — ranking
offers on $/mile earns $16.03/hr against $19.80 for $/hr — and this changes
nothing about what picks the offer. What it covers is the case the driver named:
an app that is twenty minutes optimistic raises no doubt at all, because
`SANE_MINUTES` runs from 2 to 240 minutes, so on exactly those cards the
headline is quietly wrong and pay over distance is quietly right. That case had
no reading anywhere on the panel.

*It survives one of the six doubts and no others,* because `doubt` names which
figure the reader cannot believe: `pay` would make this the same impossible
payout divided, `rate` and `speed` each leave either half open, `leg` means the
distance is a fraction of the journey, `screen` means there is no card at all —
and `time` is the one where the pay and the distance have each passed their own
test, which is precisely the card this figure exists for. Refused outright when
the distance is doubted, and when there is no distance, which is every delivery
card that states a deadline and no route.

*The denominator guard was deleted because no input could make it matter.*
Written first as `r.miles > 0 &&`, mirroring offer_parser's own
`miles and not miles_uncertain`, it looked like the load-bearing half. A
delivery card sends `miles` as null, the division comes out Infinity, and
`money` already answers `--` to that, to a zero and to a NaN — so the mutation
weakening it to `!== 0` survived the whole suite. The missing-distance case is
`money`'s refusal, and the check now kills a mutation there instead. Six
mutations, six named killers, one of them in a function three hundred lines
away from the change.

*And the README had been describing the raw formula all along.* Its math block
said `$/mile = pay / miles` while every screen in the project divided `net`,
so the one document that states the arithmetic had never matched any of it. It
now says `net / miles`, and names the driving panel as the one deliberate
exception.

**The shift row's median was the typical OFFER, printed one separator after the
driver's own takings.** `shiftSummary` builds it from `counted.map(o =>
o.perHour)` — every offer the window read — and 935 of the week's 1,166 were a
PASS. The words in front of it are "took 10 for $140 net", so the figure read as
the rate of the jobs just named. Replayed day by day on the 4am boundary against
the median of what was actually ticked:

| day | the row said | the jobs taken ran | out by |
|---|---|---|---|
| 13 Sep | $14/hr | $25.50 | 1.88x |
| 15 Sep | $11/hr | $21.70 | 1.96x |
| 18 Sep | $15/hr | $34.40 | 2.28x |
| 19 Sep | $17/hr | $31.00 | 1.82x |
| 20 Sep | $17/hr | $25.70 | 1.51x |

Pessimistic on all five driving days, beside a $25 target it looks measured
against. The offers page had this exact fault and its cure was to name the
population; its big figure reads `typical offer`.

*Copying those words was tried, measured, and is wrong on this screen.* The row
is ellipsised from the tail, and at 480px "typical offer -$17/hr" put the digits
at 507px against a box ending at 468px — the label ate the number it was
labelling, which trades the first fault class for the second. "typical" alone
overshot by 5px. The budget is exactly the seven characters `median ` already
spent, so the figure goes FIRST and the noun joins the tail: `-$17/hr an offer`.
That is the one arrangement where naming the population cannot cost the figure,
and it follows the rule this row already states — the figures lead, the count
and the set-aside are what a small screen loses.

*The check that proves it had to be rebuilt once.* Ranging over the digits at
480px was right; anchoring the range to the words beside them was not. A
mutation that changed the label made the measurement SKIP rather than fail,
because the regex stopped matching and the assertion sat behind a guard. It
finds the line's one rate by shape now, so the wording cannot switch it off.
Four mutations, four named killers.

**The pair row painted "take both" green under a PASS, and the record went on calling that green what the panel said after it was gone.** The pair line's green meant the time-weighted blend of the held job and the offer cleared the target, so money already earned carried the colour. Replaying week.csv with the 31 marks and holding()'s ×1.5 + 10 min expiry (target 25, 30c/mi) gave 267 pair lines and 71 greens. 45 of those greens were offers whose own net rate was under $25: 30 under PASS and 15 under CLOSE CALL. Redefining green as "own rate clears the target" would repeat the headline: it disagrees with the headline 0 times in 267. So the colour was deleted (ba1298b). The trap was the record: s.state stays on kind:'pair' rows so their shape holds, but the offers page read it as "Called it: take it", in the tally and in each row's dot. Rows since then carry stackShown:false and said, the headline's verdict off the card's own offer line. journal.html reads both through one pairSaid(). Older rows, which have no stackShown, still read stack.state, because on them it was on the glass. Checks: test_dashboard "...and the pair row takes no verdict state as a class"; test_server "...recording the verdict the panel showed for that card" and "...and that the pair line's own verdict was not on the panel"; test_offerspage 'pair era' feed (8 checks) and "...and no verdict colour on it either".

**⌖ Dropoff asked to be pressed on 400 cards a week that the panel was saying to PASS.** The ask was measured with DROPOFF_NOT_STATED over week.csv rows that have no dropoff: 457 cards, split no 400 / go 29 / warn 28, and all 4 ticks in that set were go or warn. The ask is now gated on the card's own verdict, which the offer line carries, and never on last.state. showDest runs before `last` is updated, so last.state can belong to the previous card. The ask drops to 57 a week. The offer line is re-told when that verdict moves on the same card, for example an item count read late that moves billed minutes but not the card's own. Otherwise the offer and the headline disagree about one card. Frame by frame over the week's stored scans, this happens on 1 row of 1,166. Checks: test_dashboard "...but does not ask to be pressed on a card the panel says to pass"; test_scan_pi "the offer carries the verdict its own card got"; test_loop "...and told again, same id and same journey, when its verdict moved".

**There was no way to keep a picture of the driving screen short of a phone
held up to the glass.** The panel is a browser on the Pi's 800x480 display,
driven by a bluetooth mouse, with no Print Screen key in reach, and the bar
already holds six (Settled). 📷 now sits at the end of the status row beside
the connection dot, costing the row and the bar no height; its width comes out
of the shift line, so only the camera is drawn (the word went to screen
readers: with it the median's digits are cut by 16px at 800x480, without it
they keep 22px). It is not drawn on the 480x320 hat or a phone, where even the
camera cuts the median (19px, 34px); `snaps.html` carries the press there.

`POST /api/snap` keeps `panel.png` (grim, then scrot or import, run as an
argument list and killed after 8s, with the desktop found the way a systemd
service must: `/run/user/<uid>`, the `wayland-*` socket, then `:0`), the camera
picture with its age (called old past 12s), what `/api/status` says, and
`snap.json` naming every missing part and why — word for word on the control.
The NucBox keeps the status and says why it kept nothing else. The newest 40
are kept; the reply and the log name what was removed. `snaps.html` lists them
newest first with thumbnails and download links; files are served only from
folders named the way a press names one, then checked by realpath.

The traps: a Pi whose clock still says 1970 names its new snap as the oldest,
so pruning would have deleted the press it just made (never the folder just
made now, and the note says so); an empty folder for a press that kept nothing
was removed after the reply, so a list straight after still showed it; serving
by path alone would serve any real folder inside snaps/; an X tool on a Wayland
desktop photographs only the X windows (Wayland is tried first); and a layout
check on a 101-character answer passed with the cutting removed (now the
202-character worst case). About fifty mutations across server.js, live.html,
snaps.html, journal.html, .gitignore and sw.js, each caught by name. The
snap-size figures (82kB panel PNG) were measured on Chromium's encoder and
should be re-measured on the Pi with grim.

**An independent check of the merged 📷 Snap found three faults it shipped
with.** A snap's age subtracted a stamp written before NTP from a now read
after it: measured, "20732 days ago" one way and 0 the other (now null, "age
unknown", whenever either side is below CLOCK_BELIEVABLE_AFTER). Two presses at
once on an unset clock with a full shelf deleted each other, because pruning
spared only the pressing folder (now every folder still being filled is
spared). And a failed write left a torn camera.jpg, status.json or snap.json
that the list then counted as kept (now unlinked before the reply; an
unreadable snap.json is told apart from a missing one). Also fixed: the PNG
check wanted only the signature (now IHDR and IEND too); serving and listing
disagreed about a link inside snaps/ (serving now asks the list); pruning was
said only in the JSON (now on the control); and where 📷 is drawn had three
different rules (now one, the status row's own width, measured on eleven
panel sizes). Nine unchecked branches each gained a named check. On the rig,
the first real snap measured panel.png at 212kB (scrot, X11), not the 82kB
Chromium's encoder gave, so forty snaps are about 9MB.

**📷 Snap now also asks the scanner what it last read.** A sixth handoff
request, `.snap.json`, taken with the same age guard as a ⌖ press, is
answered once with reader.jpg (the card the reader was handed, before
preprocess) and reader.json (that read's text, parsed fields and rate, the
health counters, the heartbeat flags, and GPS state). The server waits at
most 4s, polling, and says which part is missing and why. When the reader and
the panel both name a card and they differ, the line says so first — the
first version also fired when one side simply had no card, after a restart,
and a skeptic caught it. Each press appends one collection-only
`kind:'snap'` row, stamped when it is written (stamped at the press, it could
land up to 8s behind offer rows and read as a clock step to doctor.py), which
every journal reader passes over. On the NucBox the camera and the reader are
recorded together as not applying. Still open: the 3s answer window against
the 4s wait is measured only on the development box (3.0ms median, 5.1ms
worst), and the answer time on the Pi needs measuring.

**The panel said "no offer on screen" over a card whose pay the box had cut
off.** At 15:45 on 8 Oct the top edge of the card box ran through the middle of
an Uber Est. delivery card's $14.48. The reader got the tip line, the deadline,
8.6 mi and both addresses; the reading went out with no verdict, and the line
under the verdict said "scanner running, no offer on screen", a claim about the
phone the page has no way to know. `noVerdictSaid` now says what the reading
got, in words and no figures: "pay at the box edge — not trusted" when the
reader dropped the read for a payout flush against the box's top edge, "pay, no
time — box may cut it off" for a payout with no verdict, "no pay read — box may
cut it off" for a time, deadline, distance or place with no payout, and the old
sentence only for a reading that got nothing.

*The one card the rig KNOWS the box cut was the one the first version still
called "no offer".* `money_is_clipped` answers a payout flush against the box's
top edge with `parse('')`, and emit() sent that as an empty reading with nothing
saying why, while the scanner's own log said "the payout sat against the top
edge of the crop" — the tight box of `rpi/README.md` lost the payout that way on
13 of 42 cards. The 8 Oct card missed that path only because its cut digits read
as "gg Pit.". emit() now sends `clipped` and the loop passes it
(`rpi/test_scan_pi.py` 3 checks, `rpi/test_loop.py` 2 through `main()`, three
mutations).

*Not "a card is in view", which is the obvious sentence and false the other
way.* Of the corpus's 19 texts that read no payout, 18 read something and 12 of
those are not cards: the zone prompt (5) and Uber's map screen (7), every one of
which reads as 39 minutes and 1.0 mi. The map is the navigation screen a whole
delivery sits under, so "no pay read — box may cut it off" will be up for long
stretches of every delivery; it claims no card and its hedge is what keeps it
true there (a fixture off that corpus text holds it). On the real week's 5,491
stored frames — offer frames, which the navigation screens are not — the no-pay
line would have shown over the zone prompt and nothing else, 19 frames on five
prompts.

*Each sentence is no wider than the one it replaced, because `trackNote`
appends to this line.* The first wordings fitted alone and wrapped beside " ·
tracking 30px" at 800x480 and on the 3.5" hat, lifting the verdict label 12px
and 5px where the old sentence with the same note (226 of 228px on the hat) had
stayed on one line; the suite had measured `track: None` only. Shipped: 143.8,
144.7 and 150.7px against the old 157.7 at 10px, 230.0, 231.5 and 241.0 against
252.3 at 16px. `rpi/test_layout.py` measures every sentence alone and beside both
notes against the old line with the same note, on three panels in both pictures;
a "page still fits" check that could not fail (#app clips) was deleted, and
"every letter on the glass" is the one that sees a line run off. 46 checks in
`rpi/test_dashboard.py` hold what it says, off the rig's own 8 Oct reading
verbatim and one fixture per field the line is said off, each fixture held to
the fields emit() writes. Mutations: one per field, the clipped branch, the old
sentence, a figure on the line, "card in view", a line that needs a place, the
flag left off the wire or the call, and five wordings or wraps for the layout
(the lane's own first sentences among them) — each killed by name.

**The offer count lagged a saved card by up to three minutes, and the comment
beside the mark said marking was the only thing that changes it.** At 15:05 on 8
Oct the rig's own panel read "✓ 0 · 0 offers" under a card whose row had landed
27.6s earlier (offerAgeMs 27566). The page now asks five seconds after the
scanner's `{offer: …}` line (`emit_offer`, sent once the row is appended and the
file closed), once however many lines arrive in those five seconds (2.8 rows an
offer on the replayed week, up to ten for one card). A mark inside the window
answers the pending ask, and a hidden tab is left owing and asks on its first
visible tick. Replayed one line a card against the week's landing times: 1,099
asks rather than 1,166, at most nine in any minute — a floor, since a card's
later rows send lines the export has no times for; counted over the 3,265 rows
of the replay that measured `WEEK_BYTES`, each frame a read time after the last,
1,416 asks rather than 3,265, at most ten in a minute. *That is outside the
"every few minutes" budget of `/api/journal/newest`, on purpose and on
measurement:* only the first read of the journal pays the whole parse (44-59ms
on one week, 161-198ms on four); after an append readJournal reads only the new
bytes and /api/today measured 2.9-3.1ms median, 6.4ms worst on one week,
4.2-4.5ms and 9.9ms on four. The timer's comment and the README had justified
three minutes by the full parse as if every ask paid it, beside a second,
smaller cost for the same request; both now give the one. Twelve checks on the
page's own clock (Playwright `page.clock`), five mutations, each killed by name.

**A harmless library warning was the scanner's error.** The 8 Oct 15:45 snap has
`running: true` beside an `error` of leptonica's "Error in boxClipToRectangle:
box outside rectangle …". server.js stored every stderr chunk as `error`, and the
panel prints `error` as the reason a scanner is not running. `stderr` is now its
own field on /api/status, cleared when the next process starts. `error` is set
only by could-not-start, no-pipes, the watchdog, and the 'close' handler, which
writes "exited (<code|signal>)" plus the stderr printed with nothing on stdout
after it: a traceback, not a warning the loop read on past (a warning within
four seconds of a death that printed nothing is the one case it cannot
separate). *The obvious fix, promoting the stderr tail at exit, still hangs the
stale warning on the crash*: mutation S2, read back as "exited (3): Error in
boxClipToRectangle: …". Eight checks in `rpi/test_server.py` on one stand-in run
four times under the real server; five mutations, each killed by name.

**Leptonica's "box outside rectangle" came back on the 7 Nov 2026 rig log, over and over, beside "Error in pixScanForForeground: invalid box".** A box past the image is what the words suggest, so every crop handed to the reader was traced: the drawn box and the centred crop (Geometry.crop_box), the raised boxes (RAISE_STEPS), the remembered rescue crop (card_box), the finder's found card, the flattened second read, the map band (MAP_LABEL_BAND) and read_map_label's pill boxes. Every one already went through crop() or a max/min in pixels, and the reader is handed whole images (no SetRectangle), so none could be outside. `PL.clamp_box` now makes the clamp one named rule — a box already inside is the same floats, so the same pixels; an edge past the image moved to it, one axis at a time; an edge that is not a number the image's own (int(nan) used to raise mid-read) — applied in crop() and where the raised boxes, the remembered crop and the finder's box are made, so what reader.json says was read is the box read; map_band clamps its two fractions and map_label_image its box to the band. **What makes the two lines, measured on rendered cards (testcards) through the in-process engine, fd 2 captured:** 0 of 400 reads of random crops of the rendered screens (psm 6, 4 and 7 in turn); over screens warped through quads pushed up to a quarter past the frame, 0 of 450 reads under psm 6 and 18 of 450 under RECOVER_CONFIG (psm 4, the second look); and under psm 4, 21 of 200 reads of screens warped through quads distorted inside the frame, 20 of 200 through quads shifted partly out of the frame, 0 of 200 through mildly distorted ones. Trimming the out-of-frame band from the box changed nothing (17 and 17 of 200, every parse the same), so it is not a box past the image: it is tesseract's own page layout under psm 4 (libtesseract imports pixClipBoxToForeground, which reports both lines; that its image finder is the caller is read off tesseract's source, not traced here) clipping a box it computed itself over content cut at the crop's edge, and the read returns its text regardless. A 16 px white border round the image took the lines to 0 of 200 but changed 10 of 200 parses (some better, one payout lost), so it is NOT done: it would have to be weighed on the corpus and the money suite, and it is noise in a log, not a wrong figure. Checks: rpi/test_pipeline.py (clamp_box inside, past each edge, NaN, wholly outside; a read box past each edge of a rendered card reads the same pixels and text as the box clamped by hand, $16.05 off all four, nothing from leptonica on stderr; the remembered crop stored clamped; a map label box past each edge of the band cut as the clamped one). Open: the psm 4 lines themselves, above.

**A snap was six files, so a series of four was twenty-four, all named alike in a
Downloads folder.** The driver shares snaps with their assistant and means to
take a series per offer: waiting, the card, after the accept, the Trip Planner.
`snaps.html` now saves a snap as one `.html` (⤓ one file). It can also save a
snap with every newer one (⤓ with the N newer, the series it starts) or the
ticked ones (⤓ N chosen), as one file, oldest first. This is `GET
/api/snaps/bundle?snap=…`, built when asked and never stored. Pictures are data:
URIs, byte for byte. Each record is escaped text in a <pre>, and again byte for
byte behind a download link. The file has no script and no address outside it:
opened off the disk at 390x844 with the network off, it asks for nothing and
draws all three pictures. Each snap can carry a note of up to 80 characters,
typed on snaps.html so 📷 stays one click. It is kept in snap.json through a
temporary and a rename, and shown on the list and in the file. SNAPS_KEEP went
from 40 to 100: the rig's three real snaps are 276kB, 323kB and 246kB, so a
hundred is about 28MB. Measured over loopback on the development box: one snap
is 377,751 bytes in 8ms, six are 2.3MB in 25ms, and a hundred are 38MB in 375ms.
Over ten of those hundreds, /api/status answered within 24ms at worst, the same
as before the fix. The traps:
- A <script type="application/json"> block ends at the first `</script`, which
  tesseract's text can hold, so records travel as data: URIs.
- <pre> drops a leading newline.
- `<!--` in a record would swallow the rest of the file.
- Leaving out a name the rig did not have would hand over three snaps as the
  four chosen, so the whole request is refused.
- The stream ignored res.write's "full", so a slow phone had the series read
  into the Pi's memory behind the first snap. It now waits for drain.
- An 80-character note with no space pushed snaps.html and the bundle sideways
  on all six panels.

The lane's verifier found two more, each one question answered in two places:
- A snap still being taken was refused a note but bundled anyway. A screenshot
  half written (90,088 of 180,177 bytes) went out as "the rig's screen", under
  "no snap.json in this folder". stillKeeping() is now asked by pruning, the
  list, the note and the bundle; the bundle refuses with 409 and the list says
  "still being kept".
- A snap.json that is a link was refused by the note but read by the list and
  the bundle, which carried a file from outside snaps/ into a download.
  snapRecord now asks snapFiles, so all three say the folder has none.

The verifier also found three false comments and a check that crashed its suite
instead of failing by name; all are fixed. Forty-five mutations across server.js
and snaps.html, each caught by name. Still open: the build times are from the
development box, and the Pi's need measuring.


**The panel's small print was read at a glance from the seat, and most of it was not read at all.** Notices are chips — a state in capitals and what it means after the dot (`CEILING · miles unreadable`, `NO RATE · 7.8 mi untimed`, `SAME PICTURE · reseat its cable if this stays`), each sentence on its tooltip and one tap away, back on a second tap, a new card or 20 s; every refusal keeps its reason. On 1024x600 and larger the address and stops go 15→18px, labels 16→19 over figures 20→24, the line under the card and the status row 15/16→18/19; the notice stays at 16 (at 19 the chips took more of the card than the sentences). The status row is `● ✓7 $86 · $13/hr an offer 📷 …`; "an offer" stays, and "…" opens the rest for 10 s. Leaflet's zoom buttons are 48px on every panel. After civil dusk at the fix (MV.civilTwilight, within a minute of published Atlanta times) the page dims, falling back to the last kept fix, then day, and day on a 1970 clock; test_layout holds the night palette to the day's floors. 45 mutations, each killed by name. Open: the night palette is live.html only.


**The "…" sheet and the carry-two Undo overlapped, and the map caption's refusals were sentences.** With both up the sheet's centre landed on the Undo at every size; the sheet now sits above the Undo's fixed 52px by that height plus 6px, measured whole and apart at 1024x600, 800x480, 480x320 and the phone. Map caption refusals are chips in the notices' style ("NO FIGURE · card names no pickup", "NO PIN · <place>, none fit the card"), the sentence on the title and one tap away, back after 20 s, a second tap or a new line; figures and progress lines are unchanged. `MV.captionChip` reads the chip off the sentence and shows an unknown sentence whole; test_layout holds all 100 caption forms to their chip (65) or none (35) on six panels. 11 mutations killed by name; one that failed nothing was removed.


**A Pi at its soft temperature limit was read every 10 s for screens nobody pressed for.** `scan_pi.HeatGuard` puts the automatic whole-screen reads, and only those, at SCREEN_AUTO_HOT = 30 s: on at 75°C or any vcgencmd word NOW, off below 70°C with none, held between (Raspberry Pi's Pi 4 figures, not measured on the rig); since-boot words never turn it on. It reads the beat's own PiHealth sample. The beat and /api/status say `heatGuard`; the `seen` row is unchanged. Not done: skipping card-rescue's second read while hot, which recovers a payout above the drawn box. The Pi's words on the status row became the guard's chip, cause first (HOT 85°C, LOW POWER, SLOWED 82°C), with "· fewer auto reads" alone on the row; the plain "Pi temp limit" line could no longer be reached and was deleted. 27 mutations, each killed by name.

**The driving bar changed height twice per offer.** The Took age rode on the end of its label, so with six controls up the bar went from 55px to 74 or 93 and back when the next card came up. The controls now have a fixed height of two label lines (55.4px at 17px on every landscape panel, the hat included); the age, "not saved" and "in car" are a second line, short ("59m ago"). Checks: 'the bar is the same height with and without the Took age, at <panel>', 'the Took age is whole inside its button'. 6 mutations, each killed by name.

**The panel showed the whole card while the car was moving.** rpi/gps.py decides on every fix: driving from 2 consecutive usable fixes at 3 m/s or more; stopped after 5 s of usable fixes under 1 m/s; the band between holds; a refused fix never starts driving mode, and while driving a refused or stale fix holds the state for up to 10 s (or the staleness rule, if shorter), after which it ends. Replayed through Phone.take() over the 12 Oct logs (7.9 h): 86 entries, 12 stops under 10 s, 3-5 one-beat flickers, 35.8% of the shift driving (from 123, 43 and 14-23 before the hold). The beat carries `speed` and `driving`. The card side keeps the verdict, pay, $/hr, the pair line's range and the in-car line, larger, with the first notice and "+N more"; everything else waits for a stop; a tap shows the whole card for 10 s; no button; the map, picture, row and bar do not move. 32 mutations, each killed by name.

**Moving with an offer up, the card hid what the offer is decided on: the owner's decision of 17 Oct 2026 reverses that half of the driving form.** From a snap at 16 m/s, an Uber offer of $9.31 for 34 min (8.7 mi) from a KFC to a corner in Marietta, the panel showed PASS, $11.8/hr, $9.31 PAY and "CHECK MILES · decimal recovered", and nothing else. The owner: "it sometimes leaves info off the card ... it is better to have the full info presented." `showDriving` now puts `.live.moving` on the card side when gps.py says driving and render's offer branch will draw (`offerUp`: a ready reading, a rig that can see), and `.live.driving` (the entry above) only between offers. Moving with an offer, the card is the parked card at the parked sizes: minutes, miles, $/mi, both ends, the stops, the pair line, the card line, every notice (no "+N more"; a tap opens a notice's sentence), the in-car line and the reading's age. Put away: the read diagnostics (questions about the rig; the hat never shows them) and the ⤳ route link (a control that opens a tab over the panel, after a pair line that says the same in words). Below 1024x600 the working goes too (the sum from the figures to the headline). With an order held and the notices up at 800x480, the first notice ran off the card with it. On the 3.5" hat $/mi goes (the pay over the miles, both shown), the figures come back under a notice (parked hides them) three across, value over label, 34px where they were 46, and the rate is 6.5vw (31px) under a notice, still the largest type. The two ends get a line each (`#places .end`, each ellipsised, only for exactly two; parked keeps its one line), except on the hat. Not kept: the larger pay, rate, pair line and in-car line. Put over the whole card, those sizes ran 24 of the 48 offer forms past the card across the three panels and both pictures, 9 of 16 at 1024x600 (measured, not shipped). Kept: the driving form between offers, the held line larger, and the 10 s tap for the stops, which an offer no longer needs (a tap under an offer goes to what it lands on). No control. Checks: test_layout's moving forms, with the owner's long pickup under the notices alone and with the pair (`LONG_ENDS`), hold every offer form at every panel whole, nothing the parked card draws gone, smaller or larger but what is named, every notice, the dropoff whole on its own line; test_dashboard holds both forms, the change in the frame the card changes, a blind rig, three places on one line, and the peek between offers. 29 mutations: 27 killed by name; the two that survived had nothing to hold, and their code is gone (a hat rate rule for the pair that the parked pair rule outranked anyway, and a line-height); the ellipsis on each end first survived and is killed now that `LONG_ENDS` is long enough to be cut. Suites: test_dashboard 1317->1323, test_layout 3972->4190. Open, below: the hat beside the scene picture has no row for a pair, the figures and a notice at once.


**handoff.age read the clock before it stat'd the request, and the panel held driving mode for the fix's freshFor when the beats stopped.** age() now stats every copy and then reads the clock, so a press written between the two is aged on the next pass instead of dropped as "stamped 0s ahead of the clock" (measured on a 4-core development machine: 7-25 negative ages a run before, 0 in 800,000 after; no tolerance, the refusal of a request stamped ahead of the clock is unchanged). gps.py puts the hold's remaining seconds on the fix as `drivingFor`, and the page leaves driving mode when that runs out on its own clock, not after the fix's freshFor. Checks in test_handoff, test_scan_pi, test_gps and test_dashboard; 8 mutations, each killed by name.

**The panel stopped its own clock against an older map-view.js, rewrote the card on every message, and several controls said nothing.** `MV.nightFor` was called bare, so boot threw before the tick and a stopped rig read "just now" and green; it is guarded and each tick step runs alone. Writes compare first and built parts redraw only when what they say changes: per identical reading at 6x throttle, Map view 2.35 layouts and 38 ms became 0.35 and 13 ms, the phone view 1.35 and 37 ms became 0.05 and 8.3 ms; over a simulated hour at 10x, heap 2.04 → 4.70 MB and flat (was → 6.55 and rising), 1.17 layouts a message (was 1.97). The ⤳ route link and the "…" status link are kept rather than rebuilt (0 of 5 presses landed across a render before). A refused Undo leaves ✓ Took; the chooser drops "This card" when the card changes and says "not filed — press ⌖ again" on a refusal; ⌖'s "nothing held" calls orderDown(); the Set box hint keeps its instruction and, in the phone view, sits over the picture so the bar never narrows. The service worker is network-first within 3 s and re-caches the whole shell together, every write inside e.waitUntil, so one build's live.html never runs against another's map-view.js. A dead stream falls back to stills. Each with a named check and a mutation.

**The map flapped between full and half width on reads of screens with no offer.** The owner's 17 Oct afternoon, in Map view between offers: `setBetween` was passed `!busy`, and `busy` holds for READING_MS after any read starts, while the motion gate re-reads the Uber navigation screen, DoorDash's "Finding offers" and the zone prompts every few seconds — so each read dropped the map to half width under READING THE SCREEN and the no-offer result put it back. Now `(!busy || !!again)`: a read over a screen whose last reading came to nothing offer-like (`again`, `noVerdictSaid(r) === NO_OFFER_SAID`, the notion the label already used) keeps body.between. The column comes back for a reading with something of an offer (render's offer branch calls `setBetween(false)` in the same render, so a real card's verdict lands in one render), for a read after a reading with part of an offer (READING THE CARD), and for blind, aiming, a fault, a stale scanner, a notice or the Trip Planner's stops, as before. The first read with no reading yet (`r` null) still gives the column back: nothing says that screen is not a card, it is one read a shift so it cannot flap, and READING THE CARD is the cue the driver should see. Checks: rpi/test_dashboard.py 3 (a nav-screen read in progress keeps the map whole with READING THE SCREEN; a read after a part-offer reading is half width with READING THE CARD; the empty screen read to its end is whole again), beside the existing check that the offer's verdict is back in the same render. 3 mutations (`!busy`, `true`, `(!busy || !!r)`), each killed by name.

**An offer from the store of an order already in the car was not said to be (the owner's decision, 18 Oct 2026).** On 17 Oct a DoorDash card "$12.05 · 2 stops (8.4 mi) · <Store> / 113 <Street> NE, <Town>, 30060 GA" came up while an Uber order from "<Store> (113 <Street> NW)" was held, and nothing on the panel joined them. Now the card says "same store as ①" ("same store as in car" with one order) at the head of the address line, under the pair line; on the 3.5" hat, whose address line the card's way line puts away, "same store ①" on the pair line's first row, which there holds the range alone. A fact, not a rule or a score: the verdict, its state and rate, the range and the pair row's arithmetic are untouched. The rule is `Assemble.samePickup`: the DOOR when both sides have one (Uber's bracket, DoorDash's `pickupLine`, a tapped popup, the hold's own Trip Planner pickups) — the house number equal (O or l read for 0 or 1), the street equal less its quadrant, type and suite, one OCR look-alike (i/l/1, o/0, s/5) in a street of five letters or more; doors on both sides that disagree are two branches whatever the names say, and a chain's name at one door is one store. Else the NAME (sameStore) only when it is distinctive — not a listed national chain, a branch label ("Store 3317", "- 0020-Kennesaw") or under four letters — AND the two are proven within SAME_STORE_NEAR_MI, 0.5 mi, chosen and not measured: a pin this server keeps for the held order's own planner pickup against the card's gate-passed fix, plus the drive to the pickup the card printed and the fix's error, an upper bound; nothing to bound it, nothing said. Never "not the same". Computed in server.js (`sameStoreOf`), because the hold's tapped door, its planner pickups and their pins live only there and the pair row is written there: pair rows gain `sameStore: <holdId>`, ids only, absent when none; the reading's stack carries `sameStore` and `sameStoreN` only while the offer on record is that reading's card (the pay to the cent and the miles, the panel's `onRecordIs` rule), so it goes when the pair line goes. The hold now keeps its card's `pickupLine`. Not on the pair line elsewhere, measured: "same store as in car" (154 px) wrapped that row at 800x480 beside the phone and 1024x600 beside the scene picture, which a range, the ENDS chip and the route link leave 75 px, and put PASS outside the card. Checks: tests/assemble.test.js "same store: ..." and the 17 after it; test_server "same store: ..." (5); test_dashboard "same store: ..." (5); test_layout `...and "same store as in car" whole, on ...`, `...and "same store as ②" whole at ...` and `...the same-store note drawn moving as parked` (36). 15 mutations of the rule, 4 of the server and 7 of the panel, each killed by name. Open: the name rule needs the NucBox's pin of the held store and a card that prints its drive to the pickup, so a DoorDash card of one leg with no stops line says nothing by name; how often the note fires on a real shift is unmeasured.

**The camera and phone feed sat on the far side of the panel (the owner's request of 21 Oct 2026).** "Could you swap the camera/phone feed to the left side of the screen? I use the touch screen as a magnifying glass to read my phone while it is in the mount." The rig's 1024x600 panel is on the driver's right, so its left is the near side, and the picture pane (phone, scene and Map view) was to the right of the verdict card. Now it is on the left in every landscape layout — 1024x600, 800x480, 1280x800, 1024x768 and the 3.5" hat's 480x320 — and the card on the right. A mirror of the columns only: the columns are named in live.html's landscape block (`[pic-start] … [pic-end card-start] … [card-end]`) and every item is placed in `pic` or `card` instead of in column 1 or 2 (the card, the chooser, the Undo and the "…" sheet in `card`; the picture in `pic`; in the phone view the connection line and the bar in `card` beside a picture that takes every row), so the swap is the order of the names in the two templates. The one-column templates (no camera frame; Map view between offers) name their column both, so nothing card-side lands in an implicit second column; the between-offers rule that put the map in column 1 went with it, the template now doing it. Unchanged: the bar, its order and sizes and what is inside each pane; Map view across the whole width between offers; the portrait and phone layouts; the box-drawing taps, which are measured against the picture's own box. Found on the way: while ▣ Set box is drawing, its line and buttons are items in the pane's flex row beside the scene picture, the row is wider than the pane, and centred it spilled out of both ends; on the right that ran over the card, on the left it ran off the glass (the picture's left edge at -29px at 800x480), so test_dashboard's card box dragged from 10% in started off the screen and the driver hung in "snap: two boxes". `#viewWrap` is now `justify-content: safe center`: nothing moves while the row fits, and an overflowing row starts at the pane's edge and spills toward the card. Settled stands: no seventh bar control. Checks: test_layout 4312→4330 (the phone, the scene and the map beside a card left of the card on every landscape panel, under it upright at 390x844); test_liveview's placement check (each placed id a child of #app) holds for the named lines; test_dashboard 1357, unchanged, "snap: two boxes" the check that caught the overflow. Fast lane: not mutation-tested, the full suite not run (lint, test_layout, test_liveview, test_dashboard were).

**A Drop pressed a moment early could not be taken back (the owner, 22 Oct 2026: "fewer hands, less friction").** Drop put the order off the list, forgot its searches, pins' arming and planner, and wrote its drop row; the only way back was a fresh ✓ Took on a card long gone from the phone, which dates the order from the wrong card and loses everything learnt about it. Now, for `UNDO_DROP_MS` (10 s) after the panel's Drop — or the offers page's In car Drop, the same POST /api/delivered, bare or by holdIds (the chooser's answer included) — puts something down, the reply carries `undo: {id, forMs}` and that same button reads "↶ Undo" (live.html showDrop; on the offers page the dropped order's In car line stays, its Drop "↶ Undo"); no new control, so Settled stands: no seventh bar control. A press (POST /api/drop-undo `{id}`) restores EXACTLY what the press took, from a snapshot server.js took at the press (undoBefore: `scanner.held` cloned through JSON, the shape holding.json and a restart already keep, and Assemble's pool of addresses waiting between orders): the whole list as it stood, each order with its fields, endPin and pickupPins, planner, batch drops, add-on `of`/`ofEnds`, acceptedAt and tookAt (so its clock), in its place, through setHeld (holding.json, the scanner's handoff, the GPS drop re-armed); its kept pin outcome is forgotten so its next drop works it out afresh. **Written first:** one `{v, kind: 'undo', at, id, seq, undoes: 'drop', dropAt, holdId}` row per drop row the press wrote — ids and times only — and only once it is on disk are the orders put back (a row that could not be written puts nothing back, 503, the Undo still open, "↶ Undo · failed"). tools/shift_report.py reads the drop row an undo row names (id and `dropAt`) as never written, so the order ends at its next drop row; the fold and journal.py skip the kind as every other kind row. **Refused, nothing changed (409):** an id it did not give or already used ('nothing to undo'), after its seconds ('too late'), or once the car has changed some other way since — a Took, the GPS drop, another Drop, the offers page's untick, an expiry — ('the car changed'), rather than merging a snapshot into a car that is no longer there; a refused Undo leaves the drop standing and the button goes back to what the car says. Not offered for the GPS drop, an expiry, a Took that replaced the order or the offers page's untick: none is the driver's Drop. Every panel is told on the stream, `{holding, heldBy: 'undo'}` (with `orders` while two are carried). Checks: test_server 1052→1077 ('[drop undo]': a trip of two, the original pinned, planned and batched, dropped by holdId and put back with every fixture field equal and, on a second Drop and Undo, the server's own written list equal; the GPS drop armed again; one undo row naming the drop's own time, ids and times only; the same Undo twice and an unknown id refused; an earlier Undo refused after a later Drop and the later one restoring its own order; after 10.3 s 'too late' with nothing back; no Undo for a Drop on an empty car; 'the car changed' after the offers page's untick); test_dashboard 1368→1385 ('[drop undo]': Drop then "↶ Undo", no more bar controls than with the order in the car, a press posting the given id and the button Drop again, a refusal leaving nothing held, the Undo gone when its seconds run out); tools/test_shift_report 141→159 ('[undo]' 4: the next drop row is the end, none left is no end, another time or another kind takes nothing back); test_offerspage 551→553 (end to end against a server restored over a holding.json: the In car Drop leaves the line with "↶ Undo" and nothing held, a press puts the order back and the line is Drop again; the drop rows twice, the first named by its undo row). Found on the way: a second `function shiftSummary` (the /api/shift runner's first name) silently replaced /api/today's, and test_server's '/api/today' read timed out on it; renamed shiftReported. Fast lane: not mutation-tested, the full suite not run (lint, test_server, test_dashboard, test_shift_report, test_offerspage, test_layout and test_scanjs were). Open: the snapshot is process memory, so a restart inside the ten seconds forgets the Undo; the panel's own planner stops for Map view (heldPlan) and the read destination come back only with the next planner or ⌖, as after a reload; the race of a Took landing during the undo row's append is said and refused, its row already written.

**▣ Set box could not be confirmed: the drawing's words and buttons were under the offer card (the owner, 7 Nov 2026: "when I try to set the area to read on my phone I cant confirm the box as the text gets stuck behind the offer panel. Prioritize this first for experimental as I can't get readings to be reliable without it").** The owner's snap of 7 Nov 16:36 (build 8be872e, 1024x600) shows it: Set box lit, the scene picture in the left pane, and between it and the verdict card a column of "d / ag / cha / it / go / to / c / b", the instruction a few letters wide, the buttons under the card. The cause is the one the 21 Oct swap found and only half fixed: `#drawHint` and `#drawTools` are children of `#viewWrap`, a flex row built to centre the picture, so the drawing put a line of prose and a bar of buttons into the width the picture already filled. `safe center` kept the picture's left edge on the glass by spilling the row toward the card, and the spilt end was the part that confirms the box. Measured on the unchanged page over an offer: at 1024x600 the instruction 47px wide and 125 tall, Next 57px and ✕ Cancel 70, and the point at the centre of each the card; the same at 800x480 and on a phone on its side (844x390). Pressing Next made it worse: focus scrolls an `overflow: hidden` box to the focused button, so the pane slid 165px (183 at 800x480, 147 at 844x390), the picture's left edge went to -157px, and "✓ Read both boxes" could not be pressed at all. Upright on a phone (390x844, 360x780) it all fitted below the picture, but Next and Cancel were 42px tall. Fix, in live.html: while drawing, `#viewWrap.drawing` is a grid with a named place for each part. Upright it is a column: the instruction above the picture, the caption, the buttons. On a landscape screen the pane spans both columns, splitting them as the page does, so the picture keeps its column and the instruction and buttons sit where the card was. The card is `visibility: hidden` for the drawing's length and back, unchanged, when it ends. A column under the picture was tried first and measured worse: it took the picture from 388x292 to 361x272 and then 315x237 at 800x480, and to 241x182 then 221x166 at 844x390, shrinking between the two boxes. Three more things came out of measuring. (1) The picture is sized by its own shape while drawing (`width`/`height` auto inside `max-width`/`max-height`). The pane's `width: 100%` with `object-fit: contain` letterboxes it whenever the height binds, and at() and placeBox measure the box: kept for the sheet, that was a 410x281 box round a 375x281 picture at 844x390, every fraction sent off by up to 4%. The cost is no upscaling past the 480x360 frame, so 482x362 at 1024x600 against 500x376 at rest. (2) The instruction keeps three lines of room and the buttons two lines of label, so nothing moves between the steps. Left to their words, the picture went 41px down at Next upright, and on the landscape sheet every button 19px down under the press that had just landed on Next. A ResizeObserver also re-places the dashed and green boxes whenever the picture, the instruction, the buttons or the pane change size. Next placed the dashed box before changing the words, so upright it was drawn 41px off the picture's screen box (-0.046 of its height where 0.1 was dragged). (3) The six-second "boxes sent" line was the same fault in the scene: a 45x262 column beside the picture, its centre not on the line at 1024x600 and 800x480, the picture squeezed from 410 to 373 at 844x390. It now sits over the pane's top, as it already did in the phone view. The 3.5" hat's sheet is at 14px so the second step fits its 211px. Checks: test_dashboard "the drawing on every screen" drives both boxes at 1024x600, 800x480, 390x844, 360x780 and 844x390, from the scene, the phone view and Map view (both lend the scene), with a landscape scene frame. At both steps it holds the instruction and every button on the glass, inside the pane, whole, at least 44px tall, and the element five points across each hit. It also holds the picture's box to the picture's shape, the picture where it was at Next, ✓ Read both boxes under the point Next was pressed at, and the dashed box where the screen box was. Both boxes are read with real presses and each POST carries the dragged fractions; ✓ Read both boxes is pressed from the scene and Map view, No card box from the phone view. The same measurements, taken by a scratch driver on the unchanged page, fail at every landscape size (instruction and buttons not hit; the second press refused) and at 42px upright. test_dashboard 2084 (+671, the drawing on every screen), test_layout 4562, test_liveview 111 and test_lint 378 all pass, unchanged elsewhere: the non-drawing layouts, the six-second line's widths in the phone view, phone view and Map view. Fast lane: not mutation-tested.

**Under the verdict, "no pay read — box may cut it off" stood over Uber's navigation and Trip Planner for whole deliveries (the owner's snaps of 12 Nov, build cf10ded).** Five of the ten presses had it, over a turn arrow and a speed limit or the planner's stops, and READING THE CARD at every read of the same map, because the map's bar ("3 min · 1.1 mi", "Expected by") is a time and a distance with no payout, and neither screen is NOT_AN_OFFER (an add-on lands on top of either). The reader already typed every one of those reads (`uber.nav` 7, `uber.planner` 11 on that shift's counter) and threw the type away. `scan_pi.emit` now sends `screen` (OP.screen_type of the reading's words), and `noVerdictSaid` says "scanner running, no offer on screen" for a reading with no payout typed as a screen of an order taken (`uber.nav`, `uber.planner`, `uber.pickupNav`, `dd.deliver`, `dd.pickup`) — so the read after it is READING THE SCREEN, "no offer on screen · reading again". screen_type asks an offer's words first, so a card over the map that keeps any of them is typed as the card and keeps the hedge; the 8 Oct cut card and the corpus map text (which types as an offer) say what they said. Checks: test_dashboard (invented navigation and planner readings), test_scan_pi 2 (the type on the wire, a card typed as a card).

### The offers page

**The cost sweep's footnote read a two-sided test as a one-sided one, and
contradicted the table four lines above it.** `holds` is `target >= low &&
target <= high`, so a line can be too HIGH for a cheap mile and land inside once
the mile gets dearer. The note took the first rung where `holds` is false and
printed it as a ceiling — "your line is only inside the range while a mile costs
under about $0.15" — which is true only if `holds` never goes back. Swept over
the owner's own 1,166-offer week at every whole-dollar target from $5 to $45, it
contradicted the table it sits under at **34 of the 41 targets that render the
block**, in two ways:

| targets | n | what it printed | what the table said |
|---|---|---|---|
| $5–$15, $30–$45 | 27 | "under about $0.15" | **no rung holds at all**, $0.15 included |
| $16–$22 | 7 | "under about $0.15" | $0.45 and $0.60 hold, and at $20 so does the row marked **(yours)** |

$20 is the line the page itself recommends on that week, so the worst case is
the page telling a driver who took its advice to change the number it had just
given them. The owner's own $25 falls in the region where the old reading is
right, which is why it was never seen.

*No inequality, no interval, no assumption about the shape.* `Advice.costHolds`
returns the rates the line survives, the rates it does not, and which side the
driver's own rate falls, and the page lists them: "inside at $0.30, $0.45 and
$0.60 a mile and outside it at $0.15 and $0.22 — the $0.30 your rows use among
the first." True whatever the band does, including the shape that has no
cut-off to name at all: on a 60-row replay at half-hour spacing the line holds
at $0.15, fails at $0.22 and holds again at $0.30, $0.45 and $0.60.

*The fixture had to be found rather than written.* No existing window on the
offers page renders this block, because the ladder only appears when the
suggested line MOVES across the sweep — so the sentence had no page-level check
of any kind. Forty rows at fifteen-minute spacing is the smallest that both
renders it and reaches the failing shape; three-minute spacing leaves the advice
not READY and the block never appears, and seven hundred rows exceeds what the
browser driver's command line will take. Five checks on the page kill the old
sentence by name, and five mutations on `costHolds` are killed by the unit tests.

*And the fix broke the page twice before it worked.* The helper that joins the
rates was called `money`, which is the name of a page-wide formatter declared at
the top of `journal.html`; `var` hoists, so it shadowed the real one for the
whole function and emptied the entire advice block — nineteen checks, none of
them about the cost sweep, and no error in the console.

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

**The offers-page browser fixtures had reached exec()'s per-argument limit.** FEEDS was passed to node as one argv string: 127,286 bytes, against MAX_ARG_STRLEN of 131,072. One more feed (131,401) failed with "Argument list too long", and not one check ran. The driver now reads the fixtures from a file.

**The offers page printed the line kept as 'somewhere between' two ends that do not bound it.** Plan 4.4 withholds the too-picky / not-deciding instruction while 31 ticks cannot settle it. The first build printed the range as the ticked median and the all-cleared median ($30.20 and $24.90 on the real week), with 'the truth is somewhere between the two ends' under it. The driver took the ticks and SOME of the 191 unticked cleared cards. Measured with week.csv through Advice.advise, target $25, TZ=America/New_York: the median over the ticks plus any subset runs from $21.79 (the 24 cheapest added) to $36.02 (the 18 dearest), and $21.79 is on the other side of the $2 rule. Fix: Advice.ifCleared returns kept:{lo,hi} from a prefix/suffix scan (for fixed k the cheapest k give the lowest median, the dearest the highest), with ranks picked from two sorted lists. It is exact against brute force on 3,000 random markets, and 20,000 rows run in 11 ms. `agree` is asked of lo and hi. Trap: the empty clock is NOT bounded by its ends either, contrary to the verifier. runs() reads the ticks, so a taken job can join two runs and put the gap between them on the clock, and one cleared card lifts 48.3% to 48.7%. It is printed as its two named ends, never 'between'. Checks: '...the kept range at 31 ticks is the lowest and highest median any mix of the unticked cleared cards gives', 'the line kept runs from the cheapest mix … not between the two ends', '...and those are exactly the lowest and highest median any subset gives, on 400 small markets', '...and no sentence says the truth lies between the two ends'.

**The offers-page tick on a TICKED row was checked by nothing.** After plan 2.3 made the folded row's ✓ the control, every check pressed an unticked row. Drawing every tick unticked passed all 439 checks. On that page the driver's ticks vanished from the folded list, and a press on a ticked row re-posted accepted:true instead of unmarking. Fix: a pointer press on ticked row r3 asserts aria-pressed 'true' with class 'on', a post of {id, accepted:false}, and 'Unmarked as taken.'. Also, a refused mark no longer writes 'could not save' into the 52px ✓ (measured: 127px wide in the folded summary, under an aria-label still reading 'I took this'). The Undo bar says it with no Undo button, the aria-label says it, and the buttons are enabled again for a retry. Checks: 'a ticked row draws its tick pressed', '...and one press on it unmarks that row, and nothing else', 'a refused mark leaves the tick a ✓, the width it was', '...with no Undo offered for a mark never made', '...tells a screen reader too', '...and can be pressed again', '...with its Undo offered, after a refused mark hid it'.

**Nothing let the driver record a pass, so the ticks could only ever be a
sample.** 31 of 1,166 offers carried a tick, and a card passed on looked exactly
like a job taken and never ticked, so the advice had to range the line kept over
every mix of 191 unanswered cleared cards ($21.79 to $36.02, either side of where
it flips). "Close the shift" on the offers page lists a day's unanswered ACCEPT
and CLOSE CALL cards, parked, with Took and Passed posting `via: 'review'`; the
day is the log's own 4am day, and the counts it prints come from the same rule
the advice uses, so its total is the advice note's 191. A skeptic found three
faults in the first build: a night that ran past 4am left Saturday's 86 cards
(45%) unreachable (the section now steps to any day in the window); an old
panel's take-back, which sent `false`, folded as a pass (take-backs now send
`null`, and a `false` with no `via` folds as a take-back, because live.html never
reloads itself); and the row's distance was ellipsised away at 360px (it now
wraps). The app's end-of-session summary was not built: a row written on the
NucBox has no path back to the rig.

**A ✓ on the offers page now takes a RECENT card into the car, as ✓ Took on the panel would (the owner's decision of 19 Oct 2026).** "It will only map an order of the last card it scanned; offer cards can move very fast, making it easy to miss. Make it so I can map and scan from the offers page where the information is recorded, when I press the green check box that is already there." Until now the ✓ there (`via: 'offers'`) wrote the mark row and nothing else (the server review above: "Review ticks from the offers page ... no longer change the car"), so a card paged past on the phone could not be put in the car at all. **The rule (server.js offersTickHolds, two named checks):** `heldStillInForce` — the card's own hold would still be in force now had it been Took'd the moment it arrived (holdEnds from its arrival as cardArrivedAt keeps it, its own minutes × HOLD_OVERRUN + HOLD_GRACE_MS; no stated time is never in force) — and `noLaterTook` — no ✓ Took of ANOTHER card was pressed after it arrived (`tookPresses`, the last 16 Tooks of this process, and the `tookAt` of every order held, which survives a restart). Then it goes the panel Took's own path below the mark handler's `marked`: the hold from the card's reading AS THE SLOT HAD IT (`offerCards`, the last 120 cards' latest offer lines, process memory like the slot: pay, billed minutes, miles, cost, pickup, dropoff, `pickupLine`, app, deliverBy, the add-on flag, cardOf's fix and disc), acceptedAt the card's arrival, placeTook's replacement and add-on rules (carrying two off, a Took on another card replaces the trip, `by: 'replaced'`; an Uber add-on joins the trip in the car), Assemble.took and retryPool, and setHeld arming the GPS drop's end and pickup searches. Not built from the offers page's row: that is the journal's vote over every reading (bestReading) and carries no `pickupLine`, app, screen or `multiOrder`, so a hold built from it would arm what a Took on the same card would not; after a restart the tick records only. Anything else records only, as before, and the reply says why (`car.why`: `unseen`, `untimed`, `old`, `later`, `inCar` — the last for the order already in the car, which still rebuilds nothing). The ✓ taken back (or the page's Undo of a ✓) on an order in the car is Drop for that order, a drop row `by: 'offers'` (putDown), whoever took it. Settled stands: it is an explicit press on one named card, so it is not a silence read as an accept, and it names the card itself, so it is not Plan 2.1's hold on the previous card by timing; Close the shift's Took and Passed (`via: 'review'`) are unchanged. **Rows:** the mark row keeps `via: 'offers'` and gains `inCar: true` when it held (an add-on's keeps `addon`/`addonTo`); the order carries `tookOn: 'offers'` (holding.json, /api/status `holding`). tools/shift_report.py times such a mark as the Took; a ✓ that only recorded is still "marked taken on the offers page; never pressed in the car". **Panels:** told on the stream, `{holding, heldBy: 'offers'}` (and `orders` while carrying two), the shape a beat carries when what is held changes, so live.html is unchanged. **The page:** the bar under the list says what the ✓ did ("It is in the car now, as ✓ Took would put it.", "Recorded only: an order was taken after this card came up.", "... too long ago to be in the car now.", "Put down, as Drop would."), and the row of every order in the car, off /api/status, carries an "in car" tag in place of its other tags (a ticked row's summary at 360px already runs to its edge). Checks: rpi/test_server.py 943 → 957 ('[offers tick]': a recent card held from its own reading and dated from its arrival, its fields, the GPS drop armed by the server, `tookOn` and the slot left alone, the mark row, the reply, the stream, the take-back as a drop `by: 'offers'`, an unseen card, an old one, one after a later Took, one that came up after that Took replacing it, an add-on joining the trip and its row; the old "an offers-page Undo does not put it down" now says it does); rpi/test_offerspage.py 516 → 529 (the tag on the held row and no other, fitting at 1024x600 and 360x640 no worse than a ticked row without it with the ✓ still on top, and the bar's four sayings); tools/test_shift_report.py 129 → 131. Fast lane, with the owner on shift: not mutation-tested, and the full suite not run (lint, test_server, test_offerspage, test_shift_report were). Open: a restart forgets `offerCards`, so a card from before it records only; a card returned under its own id after paging is dated from its return, as cardArrivedAt dates it. Mutations (catch-up, 21 Oct): 16 run, 14 killed by name, 2 equivalent. 6 killed by the existing '[offers tick]' checks and test_shift_report's; 8 survived and are now killed by new ones: 'a card with no minutes records only, untimed', '...a card is timed by its billed minutes', 'a card nine cards back is dated from its own arrival' (past OFFER_ATS_MAX, so cardArrivedAt cannot stand in), 'a pass there on the order in the car puts it down like Drop', '...every panel is told on the stream that nothing is held', '...ticked again, it is back in the car: its own Took is not a later one', 'a card ticked after a later Took records only, that order put down since' (keepTookPress), and shift_report's '...`inCar` on a mark from anywhere but the offers page is no Took'. Equivalent, and simplified: heldStillInForce's `ends !== null` (offersTickHolds asks only of a card with minutes), and noLaterTook's read of the held orders' `tookAt` — every Took is in tookPresses, and after a restart offerCards is empty too, so no card asked about can have come up before a forgotten Took (the entry's "which survives a restart" bought nothing). test_server +7, test_shift_report +1. Mutations (catch-up, 21 Oct; journal.html's bar and tag only): 11 run, 9 killed by the existing checks (each saying of the bar, the holdId's `@` not stripped, the tag never repainted after a render, load() not asking the car — the driver hung in "in the car" — and the other tags not hidden, by the 360x640 fit check); 2 survived and are now killed by test_offerspage '[offers tick] the "in car" tag stands in place of the row's other tags, which come back once the order leaves the car' (never restored) and '[offers tick] ...and stands beside the ✓' (placed at the summary's end).

**An "In car" list at the top of the offers page, with Drop for each order (the owner's request of 20 Oct 2026: "keep it simple").** journal.html now opens on a small section listing the orders the server holds, off /api/status (`orders` while two are carried, else `holding`), the same fetch the rows' "in car" tag already made (askInCar): pay, app, the dropoff's street, "2 drops" for a batch, and the GPS drop's state in the panel's words ("● armed", "● armed by place", "at door", the first words of `endWhy`, "○ not armed"). One control per order, Drop, which is the panel's: with one order held the same bare POST /api/delivered as its Drop button (a drop row with no `by`), with two the order's holdId as the panel's chooser sends it (`by: 'chooser'`). Hidden when nothing is held; asked again on load() and after every press, no polling of its own. On the panel a tap on the in-car line (#heldLine, #heldLine2, or the card's last line under an offer) opens journal.html#incar, the page ▤ Offers opens, which scrolls to the section once it shows. Settled stands: no seventh bar control. While the driving form is up the first tap is the peek, as before (captured on the way down); a tap on the peeked card's in-car line opens the list. server.js: /api/status `holding` gains `app` (orders already had it). Checks: rpi/test_offerspage.py 529 → 545 (the line and its one Drop at 1024x600 and 360x640, no sideways scroll, Drop on top and 44px; Drop posts the bare POST and the section and the row's tag go; hidden with nothing held; end to end against a server restored over a holding.json: opened at #incar it shows the order near the top, Drop writes the drop row with no `by` and /api/status holds nothing); rpi/test_dashboard.py 1335 → 1337 (driving between offers the tap on the in-car line is the peek and goes nowhere; a second tap opens journal.html#incar). Fast lane: not mutation-tested, the full suite not run (lint, test_offerspage, test_dashboard, test_server were). Open: the list is not live while the page sits open; it refreshes on a range press or a Drop. Mutations (catch-up, 21 Oct): 16 run. live.html's tap: #heldLine left out and journal.html without #incar killed by '[in car list] ...a tap on the peeked card's in-car line opens the offers page'; `#detail .held` and #heldLine2 left out survived, now killed by test_dashboard '[in car list] under an offer a tap on the card's in-car line opens the offers page too' and '[in car list] with two in the car a tap on ②'s line opens the offers page too' (the navigation cancelled in the page, so the stage goes on). journal.html: 2 drops not said, the dropoff whole, the app left out, the holdId sent with one order, the section never hidden killed by the existing checks; by place, at the door, endWhy uncut, and (new) by street, each said wrong, survived or were new and are killed by test_offerspage '[in car list] four in the car: each line in the panel's words'; a bare Drop with two orders by '...Drop on one of them sends its holdId'; a refused Drop not said by '...and a Drop the server refuses says so'; the #incar scroll never made by '[in car list] opened at #incar with the page scrolled down, the section is scrolled to the top'.

**Every clock time on the offers page followed the browser's locale, and the owner's writes 24-hour (the owner, 2 Nov: "it would also be nice to have the 12 hr clock on the offers page").** journal.html wrote each row's time, the "ticked at" of an arrival, the review's first and last card and the run labels with `toLocaleTimeString(undefined, {hour, minute})`, and "Read at" with a bare `toLocaleString()`, so the locale chose the clock while the panel, the cards and the hour blocks (Advice.BLOCK_NAMES, "12–3pm") all speak AM/PM. Now one helper, `clock12` (hour12: true), for every one of them, and "Read at" the date and a 12-hour time with seconds. No hand-built HH:MM was on the page; the hour blocks were already 12-hour; sorts, keys and the 4am day boundary read the stamps, not the words. Checks: test_offerspage renders 'in the car' again in an en-GB browser (`in the car 24h`) and holds every row's time to "h:mm AM/PM", the same as the en-US page's; the review's expected clock now asks hour12.

**From the panel's Offers button there was no way to the Strategy tab (the owner, 7 Nov 2026: "How can I get to the strategy tab from the offers page?" ... "Yes add that, fast track to experimental").** journal.html linked the report as an 11px hint, "⌖ Where the good offers start", named for one tab of twenty and shown only where the server had a report of its own (a HEAD request for the report's page). The report is built and served on the NucBox (tools/places_nightly.sh), so on the rig — where the panel's Offers button opens the page — the link was always hidden. Now it is a row of its own under the top figures and their headline, 52px, "Strategy & places report", to `places/#strategy`. **Where it goes** is server.js `placesLink` (GET /api/placeslink, one function beside servePlaces, touching no other route): the server's own `places/` where PLACES_DIR has a report ('here'); else `NUCBOX_SITE`, a new optional setting ('setting'); else the address rpi/sync.py last reached, the `to` of the `.synced` stamp it writes beside the journal ('sync'). The last needs no new setting: the machine that keeps the copy is the one that builds and serves the report (places_nightly.sh reads its journal from that same server), and the stamp is written only by a sync that got through, so an address that never answered is never offered. **What leaves**: a URL's scheme, host, port and path, then `/places/#strategy`; a user:password in the address, a query and a fragment are dropped, SYNC_TOKEN is never read (it is in the sync unit, not the server's environment, and not in the stamp), and anything that is not http(s) is no link. The page sets the href as an attribute and only for its own `places/#strategy` or an http(s) address; a server from before the endpoint is asked the old way. Not done: the link from the rig opens only where the phone reaches the NucBox (the VPN the sync uses); nothing checks that from the page. Checks: rpi/test_offerspage.py 612 → 627 ('[report link]': each answer and their order, the password dropped, a non-http setting or stamp and a torn stamp no link; in Chromium at 360x640 the row shown on the NucBox and on the rig, saying so on the rig, hidden with nowhere to go, under the headline and above Targets, on the first screen, 52px, no sideways scroll). rpi/test_server.py's '[places]' check of the hidden row and its HEAD fallback still holds unchanged. Fast lane: not mutation-tested.

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

**What a card turns into, and what holding out for a line paid, measured
offline (7 Nov 2026).** The owner: "being able to know what is a good $/hr and
$/mi metrics to expect would help decide which offers to take and which to
decline." The replay above answers which line earns most at the cards' own
minutes; nothing said what a card of a given $/hr had actually turned into, or
priced a line with the measured time in it. `tools/strategy.js` does both, for
the NucBox report's Strategy tab (`tools/places_report.js`) and the end-of-shift
report's `--strategy` (`tools/shift_report.py`, which runs it under node rather
than keeping a Python copy), and each report hands it the orders as its OWN
rule timed them — the module never decides whether an order was delivered.

  - *The curve is a renewal model, not a second replay.* Free time is the
    shift (every card seen and every hold, joined across silences under
    `SHOWN_AT`) less every hold; λ(T) is the cards at T or more seen while
    free, per free hour; effective $/hr(T) = pay(T) / (1/λ(T) + time(T)) =
    P / (H + r(T) × C / 60), with time the card's minutes × the measured
    actual/card ratio r(T). r is taken over the timed orders whose card was at
    T or more, because picking high $/hr picks optimistic minutes (the
    re-timing entry in Settled): one ratio for every line flattered the high
    ones. Minutes times a ratio of minutes is `refigured`'s scaling, not a
    pace.
  - *A thin point is never the best.* Under `TARGET_OFFERS` offers at a line
    it is drawn hollow and kept out of the best and of the flat region
    (within `PLATEAU`, now exported from advice.js so both call one width a
    plateau). On the hand-worked fixture in `tests/strategy.test.js` the $26
    point is 22.50 on 10 offers against a best of 23.48: one more thin card
    and the tail would have "won".
  - *The per-block curves carry their own held-out check.* The Settled entry
    against a line per hour is run again on the record in hand: fitted on the
    other shift days, scored on the one left out, a line per block against
    one line. On the fixture whose answer is worked by hand, one line $26.34
    an hour on shift, a line per block $25.71, everything $18.62.
  - *What is not counted*: a card read twice (one per id, seen at its first
    reading), an untrusted card (it still says the rig was on), a card seen
    with an order in the car or an add-on card (not a free driver's choice),
    a card alone in a silence, an order with no time at the door, one put down
    in under 0.3 of its card, one whose clock stepped or ran past four hours,
    and every approximate point: nothing in the module reads a position.

What it does not see, and says: stacking (the curve is a driver who takes
nothing while carrying, so it reads low by what stacking earns); an order with
a Took and no drop row is free time in the NucBox report (takenRuns never lists
it); the miles between orders cost nothing on the net curve. How much record a
±$2 answer needs is arithmetic on the one measured week's night-to-night swing
($13.92 to $27.06): about 25 shift days, and 20 timed orders for a ratio inside
about 10%. Under 10 shift days, 12 timed orders or 20 free hours the summary
says "thin". tests/strategy.test.js 80, tests/placesreport.test.js 308 → 326,
tools/test_shift_report.py 233 → 244.

**Twenty tabs in four rows of pills, under a banner taller than a phone (the owner, 7 Nov 2026, who reads the report on a phone and a laptop: "consider how the page and tabs are laid out, is there a better format for all this information?").** Measured on a report built from invented fixtures (886 offers, 24 shift days) in headless Chromium: at 375px the first screen was the title and the four-paragraph banner, the twenty tabs wrapped below it, and the Strategy tab ran 7,270px of fourteen wide tables; the curve, squeezed under a 520px floor, scrolled sideways inside its box with the best line usually in the hidden half; and a hash changed after load (a link inside the page) did nothing, because the page read the address once. Reorganised, nothing cut, in `tools/places_report.js`:

  - *An Overview opens the page (`#overview`).* Tiles for the best line and its flat range, $/hr on shift gross and net, offers per free hour, card against actual, the typical offer, and the record with the Strategy tab's own "thin" sentence and the time it was made — each a link to its tab, its n under it — then the Strategy tab's best-line sentence word for word, the curve drawn small, time of day as bars, the Targets tab's town lines word for word, the share unplaced, the old banner whole, and every tab under its question. **It computes nothing**: every figure is picked out of the report object, so it cannot disagree with the tab it points to. The time-of-day bars are each block's own best line from strategy.js's slices, one colour, said to be point estimates with no test between them, beside the held-out check — the Settled entry against a line per hour stands.
  - *Grouped by question* (GROUPS): What to take, Where & when, Record, in a sticky nav of groups over the chosen group's tabs; under 480px the four groups share the width (in one line they needed 384px of a 343px column). Every old hash still opens its tab, an id inside a tab opens it there, and the address is read on every change. The Hours picker shows only on the tabs it reaches; every other tab keeps the banner's gist in one line.
  - *Folds*: the long tables sit in `<details>` under their headings, open as written (a laptop, or no script) and shut by the script on a phone. The name column stays put while a table scrolls. Rows under their floor in the Strategy tables are muted.

The Targets text, which is the offers page's word for word, is untouched; so is every figure, rule and floor. At 375px the Strategy tab is now 4,358px with its tables folded, the Overview's tiles are the first screen after the title, and no tab scrolls the page sideways (screenshots at 375 and 1280, light and dark, were looked at and not kept: the fixtures are invented but the page is a report). Checks: tests/placesreport.test.js 326 → 358, three order checks rewritten for the groups, and in Chromium (skipped where playwright is not) the hashes, the groups, the Hours picker, the folds at both widths, no sideways scroll and no script error offline. Not done: the ranked dot plots still scroll inside their box on a phone (their names need the width), and the Map still needs the internet.

---

## Settled — do not re-propose


**With two orders in the car the pair line weighed an offer against the first alone, and the detour measured the first's run alone (Stage 6).** `Advice.stackMany(held[], offer)` replaces `stack()`, now `stackMany([a])`, held identical to `stack()` as at bf6c403 over 527,472 corpus pairs and over the 12 Oct shift's 1,179 pair rows replayed. With two held: each order's net pro-rated by its own minutes left; the range from the larger of the longest order's minutes left and the offer's to the sum of all; `alone` over the longest single order; an Uber add-on's share is its card's extension; `ends` 'elsewhere' if any held end is; no minutes from distance. The panel says "with ① + ②" whole where "vs ① only" was (cut to "with ①" at 800x480 when it rode the words that give way). Pair rows gain `stack.over`. Detour: car → unvisited pickups → both ends, in the Trip Planner's order when one planner places both (`planAt`); otherwise both orderings, a figure only where they give one answer by the street-stretch rule, else "order of stops unknown — no figure". 33 mutations, each killed by name. Open: an Uber add-on against one held order is still drawn as an ordinary offer (6,780 of 527,472 corpus pairs would change); a two-order pair row's leftMinutes is the longest order's.

### The clock

**Do not re-time an offer at a pace, however the pace is derived.** It looks
like the one thing this rig cannot do — the driver's own complaint is "some apps
have very bad time estimates" — and it was designed, measured on the real week,
and killed on algebra. Re-timing at a speed is a `$/mile` floor wearing a clock:

```
retimedPerHour = net / (miles / pace)   =   (net / miles) x pace
```

`pace` is a constant wherever it is looked up, so "this offer survives being
re-timed" is identically "its net `$/mile` clears `target / pace`". Checked
numerically over the week's 106 ACCEPTs against a bare banded `$/mile` floor:
**0 disagreements out of 106**. The floors it amounts to are $3.42, $2.08,
$1.62, $1.45, $1.19 and $0.88 a mile over the bands `[0,4,6,8,10,14,inf)`. So it
lands the entry two above this one — *judge offers on $/mile* — by a route that
does not mention miles, and a replay gives up 18% of the week's money for
+0.7% on the hourly rate, inside a confidence interval that spans zero.

*The reference statistic was the whole answer, and nothing argued for it.* On
identical bands, the share of ACCEPTs that fail re-timing is 63% at the band
p25, 36% at the median, 31% at the mean and 14% at the p75. A headline of "36%
of your greens do not survive" was a choice of quantile written up as a
measurement. Two bands give the same 38 cards as six, which is the tell: the
banding was doing none of the work.

*And the cards refuse the proportionality the model needs.* Within a band,
minutes barely move with distance, so dividing by a speed is fitting a line
through the origin to a cloud that has no slope:

| band mi | n | intercept | slope min/mi | R² | what a pace forces |
|---|---|---|---|---|---|
| 0–4 | 186 | 24.0 | 0.77 | 0.003 | 8.20 |
| 4–6 | 195 | 15.9 | 2.16 | 0.013 | 5.00 |
| 6–8 | 191 | 4.2 | 3.65 | 0.035 | 3.90 |
| 8–10 | 194 | 32.4 | **0.05** | **0.000** | 3.47 |
| 10–14 | 194 | 20.7 | 1.24 | 0.014 | 2.85 |
| 14+ | 195 | 26.7 | 0.85 | 0.286 | 2.11 |

*There is also a selection effect that accounts for part of any such finding.*
`perHour` is `netPerMile x mph`, so choosing the offers with the highest `$/hr`
chooses offers with a high implied speed — 61% of ACCEPTs run above their band
median against 50% of all cards. Re-timing to the median then pulls exactly
those back. Some of "your greens do not survive" is regression to the mean on
the variable the verdict selected on.

What would NOT be this entry: a re-timing with a non-zero intercept, because
`minutes = a + b x miles` adds a payout term and stops being a `$/mile` rule. It
is a different proposal and has to be argued on its own evidence. It is not
argued here, and it disagrees with the pace form on 10% of the ACCEPTs, so
whoever proposes it is choosing a model, not reading the data.

The honest route to the driver's actual question needs elapsed times, not a
model of them, and 31 of 1,166 offers carry a tick. That is a data problem.

**The router's drive times are allowed for ONE hint, by the owner's decision of 20 Oct 2026.** His words: "Could the NucBox give an idea of the time? If time can't be determined, distance out of the way is a reasonable place to start as well", asking for "a simple call on the card if it can be calculated that taking the second order is reasonable for delivering on time for both". This narrows the entry above for that use only: OSRM's own `duration` over the road it chose (free-flow, no traffic) may say whether some order of the stops reaches both drops by their deadlines, beside the pair line (server.js `onTimeHint`; Done, "The maps, again"). It is still refused everywhere else: no pace, no minutes from distance, no re-timing of an offer, nothing into the verdict, the state, the rate or the range, and Map view does not read the duration the relay now passes.

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
`MV.farFrom` exists and is anchored on a measured GPS fix instead (the card's
own since the detour entry under Done, "The maps, again"); see
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

### The upgrade plan

**Plan 2.1 was not shipped: holding the Took subject on the previous card would name a declined card when the driver accepts the next one.** On week.json (1,166 offers, 31 ticks: go 24, warn 5, no 2), 29 of the 31 ticked cards follow an unticked card. That card landed less than 16 s (READ_STALE_MS) before the accepted one on 13 of 31, less than 20 s on 15, and less than 30 s on 19. Any hold driven by READ_STALE_MS leaves the button on the declined card through the prompt-press window of at least 13 real accepts. That would be a wrong tick, and a wrong hold in the car, written to a file that cannot be rewritten. The 'lost ticks' the plan counted (0 of 38 go/warn cards replaced within 10 s carry a tick) are confounded with ordinary declining. 35 of those 38 arrived less than 30 s after the card before them, with a median gap of 10.555 s, which is paging through offers. Crediting any of them as accepts would be reading silence as an accept. The plan's median gap to the next go/warn card is wrong: it is 102.055 s over n=221, not 107 s. The plan's Cost line ('live.html only') is also wrong, see the next entry. Plan 3.3 depended on this item and stays unbuilt.

**Plan 3.1 is superseded by the owner's decision (13 Oct 2026): the driver asked to carry two orders, and it is built behind `carryTwo` with a safeguard in place of the attribution guard this entry required.** The old measurement still describes the fault: with A retained, the ⌖ press for the job just accepted attached through holding(now) and became an asked:true dropoff on A's id. The rival-card guard stays refused. Its replacement is positive cues only, and otherwise the driver: with two orders held a ⌖ Scan or Drop attributes on a cue the screen gave (app, Took time, store, Expected by, list growth, elimination on a list seen whole), or opens a chooser over the verdict pane and files nothing unless the driver picks; left alone it closes after 10 s and the server refuses a late answer. An unprompted sighting with no cue waits unwritten. 'plan 3.1: Took A, Took B, ⌖ over B's navigation lands on B, never A' holds the fault. Do not re-propose carrying two without both halves: no cue means no filing, and the chooser never times out into a guess.

### What else the rig could collect

Weighed on 8 Oct 2026 against the week and the code, each proposal attacked by
a skeptic before it was kept. These did not survive, and why:

**An OBD-II dongle for fuel use is not worth fitting.** Its fuel figure is an
estimate until it is scaled by real fill-ups, so it adds nothing beyond the
fill-up log listed under Open, and the one question only it could answer —
idle fuel in the 23-minute overhead — has no permitted consumer: subtracting
it per hour moves the target, which is the tuning refused above.

**A car-cost ledger (tyres, service, depreciation) says nothing for months.**
A handful of receipts a year amortised per category is one $900 tyre set
divided by whatever miles came before it, and depreciation — the largest term —
is the driver's own estimate typed in, so the rig would add nothing to it.

**A weekly snap of the platform's acceptance tier is not a new fact.** The app
shows it permanently, and the only thing it could feed is how much to accept
by app, which is the per-app target tuning refused above.

**A Passed button on the driving bar does not fit and costs a tap per
decline.** The bar already overflows when two of its three conditional
buttons show, and about 45 declines a night inside a 33-second window is
driver effort spent while driving. The labels come from the end-of-shift
review instead (Open).

**A health row every two minutes, quiet ones included,** re-opens the decision
recorded at `worth_recording` in `rpi/scan_pi.py`: a quiet two minutes with the
phone out of the mount is not evidence, and would bury the windows that are.
What survives is richer `seen` rows and explicit up/down rows (Open).

### The phone

**Re-find.** Removed at the owner's request on 12 Oct 2026: it found a screen (on this mount, the map) and threw away the drawn boxes, and with Took, Drop and ⌖ up the bar hid ▣ Set box. ▣ Set box is on the bar in every state and is the way to fix the boxes; `autopilot --recalibrate` remains for automatic finding. Do not re-add a re-find control.

**The rig does not press Decline, and a remapped ring button should not
either.** Asked for on 8 Oct 2026: one press on the bluetooth ring to reject
an offer. A rig-driven click (the Pi posing as a bluetooth mouse) is refused
for the money: on Uber's offer card the card body itself is Accept, so a click
that lands a little off — the phone shifted in the mount, the layout changed —
accepts a job, the most expensive wrong action this project can take. A
remapping app on the phone (Button Mapper, Key Mapper, Tasker) dispatches taps
through an accessibility service, the same mechanism auto-accept bots use and
the one Uber and DoorDash deactivate drivers for, whoever presses the button.
What is left is free and safe: an offer that expires is a decline to both
apps, and a mouse right-click is Android's Back, which may or may not dismiss
an offer card — a thirty-second test on the phone, not something to build.

### The editions

**Lite is a mode of this repository, not a second repository and not a fork (the owner, Nov 2026).** Asked for by drivers who want "just a means to read their phone screen with the camera, and the card pay output card", on a display with no touch, running at boot. A separate repository was the obvious way to keep it simple, and it was refused for what it would copy: the reader, both parser ports and every money-safety rule (`CENTS_LOST`, `unsure_payout`, `money_is_clipped`, the rescue rules, the card finder, DoorDash's raise and evened read, the remembered crop) are where this project's fixes land, often several a week, and a copy would receive them late or never — exactly the code that decides what a driver is told an offer pays. So lite is one switch read once at boot (`LITE=1`, or `"lite": true` in the config's settings; `rpi/lite.py` for the scanner, `lite/lite.js` for the server) that shuts the NucBox, the reports, the uploads, the sync and the scanner's map-label and map-band threads, and keeps the camera, calibration, ▣ Set box, the settings, the reader, the verdict, speech and the offers log. Its panel (`lite/lite.html`) draws what the scanner already decided and decides nothing itself. A `lite` branch takes only builds that passed the gate; a public face, if ever, is a small wrapper repository that pulls from this one, never a copy. Do not re-propose splitting lite out, and do not give it its own copy of anything that reads a card or judges one: lite may turn things off, never fork them. `rpi/test_lite.py` holds every door both ways; the decision and the rules are in `CLAUDE.md` and `lite/README.md`.

## Measured on a real week — 1,166 offers, 13–20 Sep 2026

The numbers above this line came from a 272-card export. This is a bigger and
newer one, and it moves several of them. Where the two disagree, this wins.

**The rig reads well.** 97.9% whole, 0.8% suspect, one impossible reading in
1,166 and it was caught (`doubt`, `suspect`, `milesUncertain` all set). Reads
run 1.80s median, 2.80s p90, 5.4s max. Consecutive duplicate rows are 0.6%, so
the accumulator's identity rule is holding. Nothing here needs fixing.

**Most of a delivery is not driving.** Fitted over the 1,155 cards that state
both a distance and a duration, `minutes = 23.0 + 1.00 x miles`, R² = 0.285. A
**23-minute fixed overhead on every card**, and then a minute a mile on top —
so the driving is the smaller term on every job under 23 miles, which is 96% of
the week. The implied door-to-door speed is 16.3 mph median and it is almost
entirely an artefact of that constant: it runs 9.8 mph under 6 miles and 30.6
mph over 16 (shuffle p = 0.0000), not because the driver goes faster on long
jobs but because the overhead is spread over more miles. Any reasoning that
treats a card's minutes as proportional to its miles is reading that constant as
a speed. The entry under Settled about re-timing an offer is what happens when
you do.

**The reader stopped needing the ceiling.** `milesUncertain` is **4 of 1,166 on
this week, 0.3%** — against the 52-of-121 and 108-of-202 recorded further up this
file from earlier shifts. Zero of the 222 go-or-warn cards carry any notice at
all, so the "rate is a ceiling" line, the uncosted cap and the notice-versus-
figures rule at `live.html`'s `#verdict:has(#warn:not([hidden]))` are machinery
that fires on almost nothing now. Nothing to remove — a guard that stops firing
because the thing it guards against stopped happening is a guard that worked —
but the older percentages in this file describe a worse reader than the one
running, and anything reasoning from them is reasoning about 2026's spring.

**The line is right.** `Advice.advise` over the whole week: ready, stable,
spread $0 — $20 at every one of the six thresholds, plateau $20–$25, over 27.9
hours and 9 runs. The driver's $25 is inside that plateau and the difference is
−0.99%, so the target does not want changing.

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
back off the driver's own cards. That was the week before the USB receiver:
rows written since carry a position with its quality and the gate's answer,
and `keepPlaces: false` drops it (Done, "The GPS").

---

## Open — known, checked, not done

None of these are bugs on the road today. They are things worth doing that
nobody has done, listed so they are not rediscovered as news.

**A card taken with another order in the car is searched from that order's
end too (the owner's 29 Oct shift, 30 Oct 2026).** Order #6 was taken while
#5 was held — not an Uber add-on, no Early look — and its card's 4.3 mi ran
#5's door → #6's restaurant → #6's door (1.8 + 2.7 road mi); the door was
5.3 mi crow from the card's fix, outside its 4.8 mi disc, and refused "not
inside the card's reach" for the whole delivery (#5's door → #6's door: 2.6 mi
crow, off the GPS log). One rule in map-view.js: `MV.discFor` gives such a
card's disc an `also` part — the card's miles and SLACK_MI round each held
order's end, plus how far that end may be from its point (`MV.endAnchor`: a
door pin exactly, a street pin by its stretch, a kept area by its spread) —
and `MV.inDisc`/`discBox`/`clipToDisc`/`located`/`cardRefuses` read every
part, so the search and the accusation keep one edge. server.js keeps the
ends on the hold at the Took (`afterOf`/`after`, only orders that STAY in the
car, never one the Took replaces; refreshed by saveHold when a held end is
pinned later), heldDisc reads them through `cardForSearch`, and the held
card the panel hands Map view carries them, so the page draws the second
circle and searches as the server does. *Not* the held card's disc centre:
that widens the reach by the whole held disc (9.9 + 4.8 mi round a 9.4 mi
card), which holds nearly any door and undid the map's tie-break between two
orders ("a tie is broken only by the card whose reach holds the door" failed
with it). *Open:* an offer card on screen while an order is held is still
searched in its own disc only (earlyDoor, the card's pickup pin); a held end
pinned after the new order's end was already refused is not searched again
until something re-asks. Tests: tests/mapview.test.js ("taken with one"),
rpi/test_server.py `[after]`.

**Planner stop splits: a town-only line is no door, a missing time agrees,
a name run into its initial is the name (29 Oct, 30 Oct 2026).** assemble.js
`sameNameStop` held a town-only line ("<Town>, GA <zip>") to be a differing
door (`stopDoor`: only a line or street with a house number is a door now),
and asked both reads to be timed. "Herbie P." read untimed and then
"terbieP." was not the time at all: two edits apart, first letter misread and
the initial run on; `sameName` now also compares each word run into the
initial after it ("herbiep" against "terbiep", one letter apart, wordsAlike's
own rule) — never two different names ("Pat Q."/"PatR." and two first names
stay two). Merging the untimed stop moved it to its timed read's place and
left its old neighbours behind it out of time, so a kept stop placed by
position is moved by `timedSlot` only where that place breaks time with the
stops either side (`inTime`; ties keep their places). Replayed over every
journaled planner row of 19-29 Oct: 29 Oct 3P/4D → 2P/3D (Fire Stone 5:58/6:00
one, Herbie one), in time order; 21 Oct "Lynn C"/"tynnc" and 22 Oct
"Tom S."/"Toms" one stop each; five lists reordered into time order; one
two-read join that had been right by accident now lands a lone dropoff first
(the no-common branch puts reads side by side, unchanged) and the next read
puts it right. Tests: tests/assemble.test.js `[planner names]`.

**A store name with the trip's address glued on (29 Oct, 30 Oct 2026).**
tools/shift_report.py `unglued`: where a card text shows a line that starts
the pickup and the next line (a comma after two words or more) is the rest
of it, the store is that first line; never with a bracket, a first line with
a comma or a leading digit, or a wrapped name ("Gateway Center, <Town>").
Over the 242 orders the five journals hold: 8 stores change, all to the store
alone (e.g. "Tacos La Villa <Street> Pkwy W," → "Tacos La Villa"; two cross-
street pickups that were no store get theirs). The root is in the parser:
rpi/offer_parser.py `find_pickup`'s leg tail (the 130-character window that
"holds the merchant AND the address", split by `ends_at_town`) keeps the
store line and the destination line as one place when no bracket or town
splits them. Not changed there: the split is shared with the dropoff and the
corpus, and is not a small change. Tests: tools/test_shift_report.py `[waits]`.

**Slow reads at no heat are OCR on a black frame (29 Oct, 30 Oct 2026).**
20:04-20:25 and 21:32-21:37: the `seen` rows show 3-7 reads per two minutes
at a median 15.9-25.0 s (1.5-2.6 s either side), cpuC 67-74, no throttle bit,
saw 1 kept 0, and the camera's `up` rows flip dark (bright 1-7) and seeing
through both windows. The seven frames kept as unparsed scans in them
(ep37-ep40, ep46-ep48) read mean 1.0-2.5 and max 7-9 of 255 (ep40: 12.8/46),
against 71-190 mean for every other unparsed frame that day, and their OCR
texts are 1.2-2.3 KB of noise words against 50-230 bytes elsewhere: the
phone's screen was off or black, the timer reads (verify, resample, screen_auto
with an order held) went out anyway, and tesseract spent 15-25 s each making
words of sensor noise. The car was driving in both windows (67 % and 92 % of
fixes moving, as in the windows either side), and nothing was queued: the
reader takes one read at a time (queue of 1) and reads per window fell, not
rose. Not fixed: a floor on the frame's brightest pixels before OCR (a black
screen's max is under 10, a dark-mode card's text is far over) is the shape,
but where to put it against exposure.LIT_ENOUGH's own record of a lit card
reading 4-6 needs a dark-mode card frame measured, and it touches the loop.

**Targets: what to aim for, described — on the offers page and the places
report (30 Oct 2026).** The owner, verbatim: *"It would be helpful to know in
the offers page and or report the best areas to work in and realistic $/hr
and $/mile to target based on the data."* One computation, `Advice.targets`
(advice.js), used by server.js `targetsOut` (`/api/journal`'s `targets`, the
offers page's Targets box) and by tools/places_report.js (its Targets tab,
first). Per three-hour block and overall: P50/P75/P90 of the card $/hr
offered (type-7 quantiles, the places report's own, so its "top 10% from
$22.01" is the same number); the median real $/hr of timed takes (GPS,
screen, `finished-*`; the report also counts its GPS-timed Drops), net of the
card's cost so it sits on the card's scale; and the median and P75 raw $/mi
of the offers that cleared the driver's $/hr line. Floors: 30 offers per
block, 5 timed takes, 8 cleared offers; a town on `areas`' floor (8 on 2
outings) on the rig and the report's MIN_N (30) there. Towns are
`Advice.areas` with the hours held, named only where the test beats chance
AND the town's order-statistic 95% interval of its hour-held score is clear
of zero, with its top-10% share against the other towns' in the same hours;
otherwise "indistinguishable". *What it does not do, by the Settled list:*
the $/hr line is `advise`'s plateau over ALL hours and whether the target is
inside it — no line per block ("Do not tune the acceptance line to the
hour"), and the note under the box says so; $/mi is printed as "the $/mi the
good offers tend to have" beside the one-liner that ranking by $/mi earned
24% less, never a rule; no re-timing, no weekday term, no geocoding on the
rig, nothing into a verdict. *Open:* the rig's town scores (floor 8) and the
report's (floor 30) can differ for a thin town; the real $/hr is gross pay
less the card's estimated cost, not fuel measured; per-block town lines rest
on few outings until the record grows; `targetsOut` runs `advise` and up to
nine `areas` permutations per `/api/journal` load (about 25 ms on 480 offers
on the dev box, more on a Pi asked for All). Tests: tests/advice.test.js
(targets: floors, the replay reused, no-effect towns "indistinguishable",
nothing changed), rpi/test_server.py `[targets]`, rpi/test_offerspage.py
`[targets]`, tests/placesreport.test.js (the Targets tab).

**EXPERIMENTAL — the map band above every offer card is kept, for an offline
study; nothing reads it (29 Oct 2026).** The owner, verbatim: *"Yes add the map
saving, fast track to experimental."* Purpose: an offline prototype estimates
where an order drops off from the route the app draws on its map, and it can
only be scored against the GPS stop the delivery really made if the map was
kept at full resolution for the offers later taken — the 480x360 scene views
are too small (the pins measured 36–44 px in a 1000-row view of the phone).
So once per offer — Uber, DoorDash, an Uber add-on popup — the scanner writes
`map_band()`'s straightened crop above the card (~650x784 at the label
reader's 1400-row warp, ~100–150kB) to `rpi/mapbands/<offer id>.jpg` with a
`.json` sidecar: the offer id, time, app and screen, the screen corners and
the band's place in the warp, the card's pay, miles, minutes and pickup text,
and the fix the journal row got (`lat`/`lon`/`gpsOk`/`gpsErr`/`gpsAge`, none
under `"keepPlaces": false`). After the offer line, on a thread of its own
(`MapBands`), never in the verdict's way; JPEG quality 80, the encode held to
0.5 s (over it, dropped and tried on a later read); not on a ⌖ whole-screen
read, with no corners or in low light; at most three tries per offer. **Caps:**
a ring of 400 files and 150MB, the oldest first (`"mapBandsKeep"`,
`"mapBandsMB"`); a disk error is logged once and never stops the scanner. **On
by default**; `"mapBands": false` in the config or `MAP_BANDS=0` turns it off.
**Privacy:** the map shows the street names round a customer's door. The folder
is in `.gitignore` (rpi/test_lint.py asks git), `rpi/sync.py` sends only
journal rows and the config (rpi/test_sync.py runs a sync over a rig with
bands on disk and finds none of them in what it sent), and the server serves
none of it — the one way a band leaves the rig is a 📷 Snap, which carries the
newest band from the last two minutes into its folder as `map.jpg` and
`map.json`, to go where the driver sends that snap. Pulled in bulk by hand
(rpi/README.md). No readout, nothing on the panel, no figure or verdict
change. **The Settled list binds whatever is built on it:** no $/mile rules, no
payout floors, no pace re-timing, no heat map, no silence as accept, no
seventh bar control, and the rig never presses the phone. Open: how good the
estimate is has not been measured — that is what the bands are for.

**EXPERIMENTAL — every 📷 Snap keeps more of what the rig knew at the press
(31 Oct 2026).** The owner, verbatim: *"Yes add all of them, fast track to
experimental."* Beside the files a snap had, each press now keeps, local to
the rig: `build.json` (the commit, short hash and subject, read once from
`git log -1` with a fallback when git is not there; the server's start and
uptime, the machine's uptime), shown at the top of the snap's bundle;
`frame.jpg` (the scanner's newest full-resolution frame, JPEG 85, scaled down
only past 2000 px wide, re-encoded lower while over 900kB, encoded on a thread
of its own and dropped past 2 s — `answer_snap` in rpi/scan_pi.py);
`reads.json` (the scanner's last ten reads — time, kind: card box / ⌖ press /
auto whole-screen / map label, screen type, crop source, ms, text cut to 2kB,
dark-skip flag, the parse's pay/minutes/miles/pickup/dropoff; `ReadLog`);
`searches.json` (per held order, the last eight: the end search's key, plan
and disc with its `also` circles, the last five questions to the NucBox and up
to five trimmed candidates each, pickInDisc's/pickPlace's answer and the
verdict and why, the distance band's answer — and the same per pickup;
`searchMemo` in server.js, memory only, written by endAsk, pickupAsk,
pinHeldEnd, refuseHeldEnd, settleHeldEnd/Pickup and bandHeldNow, read back by
nothing); `mapwalk.json` (Map view's newest settled walk — each mark and its
kind: car, door pin, area, band, corner, street, guess; each place not drawn
and why; the caption — posted by live.html to `POST /api/mapwalk`, kept in
memory, newest only, 32kB at most, no file; "the page is not open" when none
came); `held.json` (holding.json as stored, each order's trip, `of`,
`afterOf`, holdEnds/ownEnds, tripTill/afterMate and its pickups' owners, the
merged planner, finishing.json's watches); `journal-tail.jsonl` (the last 50
rows, held to 200kB); `gps.json` and `health.json` (the beats' fixes and the
Pi's temperature, throttling, heat guard and camera word over ten minutes,
one per 5 s, the `seen` rows of that window off the journal tail — read time,
dark skips — and the scanner's counters off reader.json). **None is a part:**
the snap's line, `contents` and journal row are unchanged; snap.json says each
under `extras`, saved or why not. Every server file is held to 200kB; a snap
grows by well under 1.5 MB. A piece that cannot be had is logged once and the
snap goes on. **Privacy:** these hold addresses and positions; same rule as a
snap's pictures — `rpi/snaps/` is in `.gitignore`, served only by
`/api/snaps` and its bundle, never synced (rpi/sync.py sends journal rows and
the config only). Tests: rpi/test_scan_pi.py (reads ring, frame caps, thread,
failures), rpi/test_server.py (each file's shape, caps, the walk POST newest
only and refused when not JSON or too big, the page-not-open case, the bundle
and the build line, failures tolerated). The Settled list binds this as it
binds the map bands: no $/mile rules, no payout floors, no pace re-timing, no heat
map, no silence as accept, no seventh bar control, and the rig never presses
the phone. Open: frame.jpg's size and encode time on the Pi itself are not
measured; a Map view walk is posted only while the page is open on Map view.

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

*One shape of the 64 is settled since (the owner, 20 Oct 20:44; see Done,
"On Uber's delivery card a lone corner..."):* a cross-street corner on a card
with a "total" leg is the dropoff, never the pickup. How many of the 64 that
moves has not been replayed over the week; the shared corpus moves 6 of 591.

**No DoorDash screen is typed as one after an accept.** Its delivery screens type 'unknown', so a ⌖ press over a held DoorDash order's own screen while another card is up always asks the driver.

**An address under a Dropoff label read while another card is screened still files onto the held order** over an end its card printed (the label rule, kept). The sighting tally counts it: `kept: true` with `slot` not `held`.

**The heat guard's effect on the Pi's temperature is unmeasured;** a shift's `seen` rows (cpuC, throttled, medianMs) would say whether 30 s is enough.

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

**Where the good offers start, as an offline report on the NucBox (the owner,
25 Oct 2026: "It would be helpful know where and what places turn up good
offers ... a table is also very helpful").** Built as `tools/places_report.js`,
suite `tests/placesreport.test.js`; not yet run on the real journal, so no
figure from it is recorded here. It does not reopen the entry above, because
it is not that feature and it does not have that fault:

- *Not on the rig.* It runs on the NucBox against the copy at home's
  `/api/journal`, writes a page and CSVs to a folder outside the repository,
  and nothing on the rig, the panel or any page the rig serves reads it. No
  verdict, target or colour on the glass comes of it.
- *No colour bands, so no miscolouring.* The fault that refuted the heat map
  was a fixed band edge read at n=12. Here every ranked cell is a median and a
  bootstrap interval on a dot plot, and colour is given only where the
  grouping's own permutation test (Advice.areas, 2,000 shuffles) is under
  0.05 AND the cell's interval of its score is clear of zero. On a no-effect
  fixture, 40 worlds, at most 5 colour anything; the floor is 30 offers on two
  shift days, the low end of the 30-60 the entry derived, and below it a cell
  is listed "too few" with its n.
- *The hour is held.* The score is Advice.areas' `matched` — each offer
  against the OTHER cells in its own three-hour block — and the test shuffles
  within blocks. A fixture where one place is simply seen late at night
  (raw p < 0.05, medians $10 apart) comes out not significant and grey.
- *The biased third is on the page, not under it.* A pickup is placed only by
  map-view.js's rules as the server places a held order's pickup (a door by
  its door, a name by `pickPlace`, inside the card's disc, one answer or
  none), so a bare chain name is unplaced, and the placed-against-unplaced
  gap in $/hr and pay, with its test, per shift day, heads the report. The
  town table needs no pin and is not cut that way.
- *It still cannot say where to wait.* Offers are dispatched from near the
  car, so it ranks only places near where the driver already waits; the
  banner says so, and that it is offered, not earned.

Dropoffs (customers) are only counted by town and 2-mile cell for "where
trips leave you" (minutes to the next offer the rig said take); no door, name
or position is written, and a cell under ten trips is not named. The open
question is the real result: whether anything below town scale beats chance
on the larger journal, which the entry above found it did not on one week.

**The places report's second pass: takes, real time, waits, strand risk,
busy areas, the app split, add-ons, gone quiet, a weekly trend and $/mi (the
owner, 26 Oct 2026: "Go ahead with all of them, fast track to experimental,
having $/mi data is also a good metric to see").** Added to
`tools/places_report.js`, each item with checks in
`tests/placesreport.test.js`; not yet run on the real journal, so no figure is
recorded. Experimental and descriptive: counts, medians, bootstrap or Wilson
intervals, no test-ranked order and no colour, so the entry above's
colour-only-where-it-beats-chance rule is untouched, and nothing reaches the
rig. Held to the Settled list:

- *$/mi is read, not ruled.* The offers page's own payPerMile (pay over card
  miles, nothing off, none under 0.1 mi) as a column and a sortable view, with
  the page saying it is not an accept rule. No floor, no band, no verdict.
- *Real time is a clock less a clock.* Took to put-down off takenRuns, and only
  for put-downs at the door (`by` gps or screen): a Drop press can come early,
  so those are counted and left out. No minutes re-timed at a pace or worked
  out from distance.
- *No weekday term.* The weekly trend is ISO weeks of the hour-held score, a
  line to look at; weeks under 10 offers are left out, not drawn as zero.
- *Dropoffs stay counts by area.* Strand risk names a trip's town, and its
  2-mile cell only where "Where trips leave you" already names that cell (10+
  trips); the page and CSVs are checked for the dropoff's text and position.
- *Waits are joined only where the join is not a guess* — server.js
  storeWaitFor's no-pin rule: not a chain's name, one store of the name on
  record, one place of it in the report.
- *Busy spells are chosen thresholds, not measured ones*: 150 m, 3 minutes, a
  5-minute fix gap ending a spell, every taken order's Took to put-down cut
  out. Known gap: an order taken and never put down has no takenRuns row, so
  its time counts as waiting; and the spell's town is the NucBox map's name
  for its 2-mile cell's centre, which can straddle a town line.
- *Gone quiet is a rate per shift day out*, against the record's newest offer
  rather than today, so a week off or a journal that stopped syncing is not a
  place going quiet; flagged only on 30+ offers before, 3+ shift days since,
  5+ expected, Poisson p < 0.05 (or a rank test on the score, 10+ each side).
- *Add-on, multi-order, many-dropoff and early-look flags* are the row's own
  fields where it has them, else scan_pi's patterns over the row's texts —
  copies the suite holds equal to rpi/scan_pi.py's.

The nightly rebuild, `tools/places_nightly.sh`, swaps a symlink by one rename
only after a build that succeeded and wrote a page; a failed or half-written
run leaves the served report as it was. The rig's address is a setting in a
file on the NucBox, never in the repository.

**A Restaurants tab in the places report: pay compared by the name on the card,
placed or not (the owner, 26 Oct 2026: "Would it be possible to have a
comparison of different restaurants and their pay? That could be helpful").**
Added to `tools/places_report.js` with checks in `tests/placesreport.test.js`
(178 → 211); not yet run on the real journal, so no figure is recorded. The
Places tab ranks only pinned pickups, and the banner's own test says the
unpinned paid less; this tab groups by name and needs no pin, so it is the
fullest comparison the record allows. Held to the rules above and the Settled
list:

- *One name rule, the rig's.* storeLabel (Uber's bracket off), a name only
  where `MV.searchPlan` reads one (doors, streets and corners counted out),
  merged by `Assemble.storeKey` and `Assemble.sameStore` — the rule the waits
  are joined by. server.js keys its store waits by storeKey as well, but its
  `storeNameSaid` is not exported and is not copied. sameStore is not
  transitive; each name joins the most-offered name it matches. Known gap: a
  branch label ("McDonald's #1155") is a name of its own, as storeKey writes
  it, not folded into the chain.
- *Ranked as places are*: `cells` (Advice.areas, block-held shuffles,
  `matched`), 30 offers on 2 shift days, bootstrap intervals, colour only
  where the grouping beats chance and the interval is clear of zero; under
  the floor, "too few", never ranked, tested or coloured.
- *Descriptive beside it*: median pay, $/mi (read only, no floor), your take
  rate (Wilson), real $/hr and real − card minutes on put-downs at the door
  only, add-on and stacked share, the app split.
- *Waits by the one join rule* (`waitOf`, now shared with the waits tab): a
  restaurant's row only where the name is not a chain's, one store of it is
  on record and at most one branch of it is placed. A chain's wait is per
  branch, and the waits on record carry no place, so a chain's branch is
  never joined either.
- *Privacy*: pickups are businesses and their placed branches are shown with
  a position, as the Places tab shows them; the page and both CSVs are
  checked for a dropoff's text and position. Checked at 375 px in headless
  Chromium, light and dark: no page-wide sideways scroll, no script error,
  the table scrolls in its own box with the name column held.

**Placement levels, rig waits, GPS-timed presses and Best offers — the places report's third pass: the rig's whole search chain with levels,
the store waits from the rig, Drop presses timed by the GPS, and a Best
offers tab on the top of the distribution (the owner, 26 Oct 2026, after the
first real run placed 8% of pickups: "Go ahead with all three, fast track to
experimental. Also please implement the new statistics you mentioned as I am
trying to get the best offers which are higher than the median by a good
bit").** Added to `tools/places_report.js` and `tools/places_nightly.sh` with
checks in `tests/placesreport.test.js` (212 → 276); not yet run on the real
journal, so no figure is recorded here. Experimental. Held to the Settled
list and the heat-map entry:

- *One chain, the rig's.* Placement asks map-view.js NbxSearch.place — the
  chain server.js composes as doorChain (pickInDisc; streetRetry /
  retryWanted / pickRetry; dirRetry / dirWanted / afterDir; nameWanted /
  nameRetry / pickNamed; streetArea for a door nothing answered) — NbxSearch's
  corner for a cross street, the street index's `whole` read by MV.streetArea
  for a numberless street, and NbxSearch.band (MV.bandTarget, bandPick) for a
  refused door. No server.js code is copied. The street index is asked even
  with `--nominatim` (the first run's 662 corners went unasked because the
  direct path never asked it): `--streets`, else the server's relay, else its
  own loaded index; stdout says which. Road questions go through the relay's
  `/api/nbx/route`, at most `--road-asks`, cached with the rest.
- *Levels.* door, corner, name are a point; band, area, street are an area
  with its spread. **Places** take a point, and an area only within AGREE_MI
  (0.2 mi) of a point of the same store, or with its own spread ≤ 0.3 mi
  (chosen, not measured: a spread is the two farthest candidates, so its
  middle is within 0.15 mi of either — inside AGREE_MI). **The 2-mile grid**
  takes every level with spread ≤ AREA_MI (1 mi). Towns are unchanged. The
  Coverage tab counts each level and the refusal it stood in for, and the
  pay gap is re-measured with every level placed and with points alone.
- *Fix-less cards.* A printed door with its town or ZIP is searched in a disc
  round the driver's region — the bounding box of every good card fix in the
  record, 5 mi wider each way (chosen) — and kept only at door or corner level
  where an answer at the pin carries that town or ZIP; no band, no area (a
  region is no card's reach). A store name with no fix stays unplaced.
- *Store waits* come from `--waits` (the rig's `/api/journal`) when the main
  source has none; the nightly script passes `RIG_URL` (config file only) when
  it is set and answers. No address is committed.
- *A pressed drop timed by the GPS — chosen, not measured.* The stop the press
  belongs to (stillRuns: every fix within 100 m for 60 s or more, no fix gap
  over 5 min, beginning after the Took): the one containing the press, else
  the first starting within 10 min after (an early press), else the last
  ending within 5 min before (a late press); the real end is the stop's end,
  the car leaving the door. No stop: still excluded. Labelled
  `drop (gps-timed)`, counted apart, used in real $/hr and card-vs-real with a
  "GPS-timed" column. A clock less a clock: no pace, no distance-to-time.
  Known gap: a stop at the next pickup within 10 min of an early press would
  be taken for the door.
- *Top tier, hour-held.* Top 25% / 10% = at or over the 75th / 90th
  percentile $/hr of every offer in the same three-hour block (30 offers for
  a block to have one). These are percentiles to read, never a floor or a
  verdict. P75 and P90 (bootstrap interval at 30 values, the binomial
  order-statistic interval at 1,000 or more, for speed) and the top-10% share
  sit beside every main table's median.
- *Does top-10% share differ by area* — a new test: the statistic Σ (O − E)² / n
  per group, the top-10% marks permuted within each block (2,000 seeded
  shuffles), floors 30 offers on 2 shift days, all hours only; a group's
  score is its share less the other groups' share in the same hours, with a
  bootstrap interval; colour only where the test beats chance AND the
  interval clears zero. Checked against no effect, a strong effect and the
  hour wearing a town's clothes.
- *Per hour of waiting and expected $/hr* use the Busy tab's spells (no
  order in the car), 10 spells on 2 shift days: offers seen while parked
  there ÷ hours parked; the takes made while waiting (a Took inside the spell
  or 2 min after, chosen) — their pay ÷ (hours waited + their real hours),
  timed takes only, so it reads low where takes went untimed. The "every
  top-10% offer taken" line is offered, not earned, at card minutes, and
  ignores that a take ends the wait.
- *Dead miles* are the GPS log's straight lines (10 s apart, a little under
  the road) from a put-down to the next Took (≤ 90 min, the log unbroken,
  chosen) plus the next card's printed to-pickup miles; unpaid share = dead ÷
  (dead + the delivered trips' card miles). By dropoff town and cell, counts
  only; a cell under 10 measured trips is not named.
- *Offer size bands* (< 4, 4–8, 8–12, 12+ card miles) are descriptive; $/mi
  read only.
- Checked at 375 px in headless Chromium, light and dark, on a synthetic
  report: no page-wide sideways scroll, no script error, the Best tab first.

---

**One unlabelled bracketed leg on a lone card is called whole, and on a ride card that is the drive to the rider alone.** is_whole's single-leg clause says 'Uber labels every leg of a ride (away, trip, total)'. laid_out_approach measured 'away' on 0 of 1,166 rows. Measured on the week: rows 444 frame 0 and 805 frame 1 are ride frames whose trip leg did not read, and they read whole on the approach alone. Row 805's merge recovered; row 444's journal row is whole=0 for another reason. Not fixed, because the same shape is also an Eats card whose `total` did not read (`tota`, `te al`): 7 frames on 6 rows, all whole jobs. Telling them apart needs a text-level ride signal carried through the accumulator. half_a_ride answers it only where another card is in shot, and 'whole / one bare leg on a frame holding ONE card is left as it was' pins that boundary.

**What else to collect, vetted, and where each stands (8 Oct 2026).** Each
item was proposed against the week and attacked by a skeptic; the ones that
did not survive are under Settled, "What else the rig could collect".

- *Done:* pictures of the reads the rig doubted, kept always — see Done,
  "The cards the reader guessed at".
- *Being built:* peak-pay "Switch to this zone" prompts read as $1 offers (a
  fault, not a collection: five in the week showed a verdict on the panel);
  the end-of-shift review on the offers page (Took / Passed for the shift's
  unlabelled go and warn cards, plus the app's own session summary, written
  as ordinary marks with `via: 'review'`); 📷 Snap; rig up/down rows.
- *Next:* Snap asks the scanner for what only it has — the crop the reader was
  handed, its text, the health counters, GPS state and Pi temperature.
- *Waiting on a file from the driver:* importing the weekly earnings
  statement from drivers.uber.com, the only source of what was actually paid
  (tips, promotions, later tip changes) and a trip count that needs no ticks.
  The importer has to be written against one real download; no column list
  could be confirmed from outside.
- *Planned, asked for by the owner:* **TeslaMate on the NucBox.** The car is a
  Tesla Model 3, so the gas-car items first written here — a fill-up log typed
  at the pump, odometer readings typed at each end of a shift — are replaced by
  the car's own record. TeslaMate (open source, Docker, Postgres) logs every
  drive (time, distance, energy, route) and every charge (energy, cost at a
  home rate the driver enters) through Tesla's Fleet API, with nothing in the
  car and nothing over the rig's hotspot. Three uses, all on the offers page
  and none live on the panel: a measured ENERGY cost per mile shown beside the
  existing cost-per-mile comparison for the driver to adopt, never written into
  the setting (wear and depreciation still on top); a dated mileage log for
  taxes (the IRS rate changed on 1 Jul 2026); and unpaid miles per shift —
  the car's driven miles against the ticked jobs' miles. TeslaMate POLLS, and
  Tesla meters every request, so it is the after-shift record and not a live
  feed. Live position from the car needs Fleet Telemetry instead (the car
  pushes over its own LTE to a server, Tesla's sample config at 10s for
  location, reported down to about 1s), which needs a publicly reachable
  TLS endpoint and a paired virtual key, or a paid relay; for the rig's live
  position the phone's GPS over the shared hotspot, or a USB receiver on the
  Pi, is nearer, faster and free. Do not join the car to the 2GB hotspot: it
  downloads software updates over Wi-Fi.
- *Done since:* a USB GPS receiver on the Pi, with the fix quality gate it
  was conditional on — see Done, "The GPS", and the detour entry under "The
  maps, again", which is what the gate guards.
- *Worth doing, lower priority:* keeping cards that showed a payout but did
  not parse, for new layouts and the first DoorDash cards; tesseract's per-word confidence on the scans,
  collection only, until the doubt pictures show whether it predicts anything.

**Feeding the phone's screen to the Pi over HDMI was researched, not built
(8 Oct 2026).** The Fold6 does put its screen out over USB-C (Samsung lists
wired DeX for it); the setting that mirrors rather than starting DeX is under
Settings, Connected devices, Samsung DeX, Connected display. The Pi 4's two
micro-HDMI ports are outputs, so the input is a USB capture stick (MacroSilicon
MS2109, about $15, the one PiKVM and TinyPilot support). What decides it is the
Uber offer card, which the driver reports cannot be screenshotted: whether such
a window shows over a cable depends on Android's version and Samsung's build
(AOSP 15 QPR1+ treats wired displays as secure; Android 16 can start HDCP the
moment a protected layer appears), and whether a given MS2109 stick has HDCP
keys varies by brand. A TV is no test — it does HDCP. Only the real stick
settles it. Other costs found: the stick is an HDMI audio sink and can take the
phone's navigation voice; the mirror goes black when the phone sleeps;
folding changes the layout mid-shift; and the gain is modest — a portrait
phone fitted to 1080 lines puts the card near 540px against about 450px the
reader gets from the camera today, without glare but not much sharper. The
camera stays the input; a capture source is a contained change if a $15 test
ever shows the card.

**Forwarding the panel's touches to the phone is noted for later, not built
(17 Oct 2026).** The owner asked whether the Pi's touchscreen could drive the
phone (a Bluetooth HID pointer, every tap from a physical touch on the panel's
phone view, never from OCR or advice; Codex's `experiment/phone-touch-control`
branch, unmerged). The owner's decision: the Settled rule against a rig-driven
click stands unchanged, and the idea is kept here for the future. What stands
in its way: a forwarded tap lands where the camera's warp places the screen,
and on Uber's offer card the body is Accept, so a tap off by the mount's drift
accepts a job; Android reports a tap's source to the app, and whether Uber or
DoorDash treat an external pointer as automation is unknown and unpublished;
and the phone sits beside the panel, so the reach saved is small. Before any
build: a written answer from the apps' driver support that an external
Bluetooth pointer on the driver phone is allowed, then — off shift, apps signed
out — no forwarded tap while an offer card is on screen, an alignment check
that stops forwarding when the phone moves, a deliberate press-and-hold per
tap, and off by default with its state on show.

**The 3.5" hat beside the scene picture has no row for a pair line, the figures
and a notice at once, parked or moving.** Measured in rpi/test_layout.py, the
card is 228x191. Moving, with an order held, the pair line and the notices up,
the notice gets 11px of its 21px chip row and scrolls; parked it gets 9px. Parked, the
pair, two orders and the trip of three already run the verdict word over the
card's top there (the Open line in "Between offers the card said..."). Two
smaller things left by the owner's 17 Oct decision, which covers the card
moving: parked, a long pickup still ellipsises the dropoff off the one address
line (moving gives each end a line of its own), and on the hat the card line
takes the address line's row under a pair, parked and moving, so the ends are
not on that card at all. Nothing on the hat closes these without a smaller
headline or a figure gone; it is the panel with the least room and is not the
rig's own.

**A store pinned along its street when its own branch is missing from OSM and another of its chain is on the same road (review of 6 Nov; checked, not changed).** map-view.js `pickStoreAlong` pins a store by its name where exactly ONE place of that name lies inside the card's reach and within `ALONG_M` (200 m) of the card's street — and that is all it asks: the name is searched in `alongBox` (the street's own shape, 200 m wider), never in the disc. The comment at `ALONG_M` said "what stands behind it is ... one place of that name in the whole disc"; the code never asked it, and the Done entry and the tests describe the code, not the comment (now corrected). So if the card's branch is not in OSM and another branch of the chain sits within 200 m of any part of the same road inside the disc, that branch is pinned — the pickup pin, the run and the GPS drop's guard on the wrong store, possibly miles along the road. **Why not enforced here:** asking the name in the whole disc and pinning only where it is the one place there would undo the rule's own case — the 2 Nov snap's card is no yardstick, its disc sixty miles, and a chain's name there is a list cut at ten (`capped`, no pin) — and would reverse a tested decision ('[store] ... one along it beside one off it is the pin', mapview.test.js; test_server '[store along]'). What would settle it: whether the card's house number can place the store along the road (the index sends shapes, not numbers), or the owner's word on trading the 2 Nov rescue for this refusal; a measured count of chains with two branches on one road in the metro would size the risk.

**The order record's reach is the journal's (7 Nov 2026).** The rig reads one journal file: past `MAX_BYTES` (64MB) rpi/journal.py moves it to `.1`, and from then the rig's /api/journal, the offers page and its CSV see only the live file, and tools/shift_report.py only the file it is given (name `.1` for an older day). Every roll is kept and the sync sends them (`chain_of`), and the NucBox's copy — server.js appends, it never rolls — keeps every order row, so the long-term record is the copy at home; nothing exports a year from the phone yet. Also open: the shift report reads a completion screen's end (`how: 'screen'`) as no delivery, as it reads that drop row, though server.js's `takenRuns` counts it at the door; a card ticked twice after a Drop is one holdId (the card's arrival), so its first order's row is superseded by the second's; the snaps list is untested against a real snap (the snap tool is not run by the record's checks); and `scanner.keepPlaces` is unknown until the scanner's first sighting or planner line, and taken as keepPlaces' default, kept.

**The earnings matcher is tuned on invented days built like one real evening, and two things about Uber's screen are still guesses (8 Nov 2026; the time read as the start, 13 Nov).** The owner's screenshots are not in the repository, so `earnings.js`'s weights (start 40, finish 15, name 25, corner 10, dropoff 15, miles 10, pay 10) and thresholds (`ACCEPT` 60, `MARGIN` 15, the start and finish bands, the offset from two confident matches) are held to invented days shaped like one evening of seven trips; a week of real uploads against the order records would say whether "needs you" is asked too often or too seldom. The pay part leans the matcher toward orders whose pay held, so a trip whose tip was cut has a little less to match on; it is never a penalty, and on that evening seven of eight trips were within 25 cents. Guessed: that a trip past midnight under a day's heading belongs to the small hours after it (`startMs`, the driver's 4am day; never seen on a screenshot); and that tesseract reads the real screen as it reads the drawn one — dark mode, the real map's labels and the phone's own font are untried. Also open: a screenshot that shows no day is filed only with a dated one in the same upload; two different trips of one minute at one restaurant with the same amount would be kept as one; rows written on the NucBox stay on the NucBox (the sync runs rig to NucBox), so the rig's own offers page shows what was paid only for uploads made to the rig; with keepPlaces off the rows keep no names, so a later re-match (a pick, Read again) has only the clocks, miles and pay; and no DoorDash earnings screen can be read until a screenshot of one is seen.

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
