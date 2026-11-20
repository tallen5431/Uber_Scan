# What has already been looked at

This file exists so the same ground is not dug twice. It records three things
and the middle one is the point:

1. **Done** — what was found and fixed, with the commit that did it: in
   [AUDITS-DONE.md](AUDITS-DONE.md), split out in Nov 2026 when this file
   reached the one-megabyte cap rpi/test_lint.py holds every tracked file to.
   New Done entries go there, under the heading that fits.
2. **Settled** — proposals that were made, checked against the code, and found
   to be *wrong*. Re-proposing one of these costs a day. Each says why it died.
3. **Open** — findings that survived checking and are genuinely not done. These
   are known. Finding one again is not a discovery.

Everything below was checked against the real code rather than argued from the
outside, and the measurements are from a box roughly 5–8× faster than a Pi 4
unless they say otherwise. Where a decision has a home in the source, the
reasoning lives there too and this file only points at it.

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

### The reports

**Home is not taken out of When & where, Waited or Busy (the owner, 20 Nov 2026: "Having home included is fine").** The product review found those three count the stay at home as waiting, so a driver who goes online at home has the home's 2-mile cell ranked as an area and its hours in every slot's rate; `homeOf` (each driver day's starting stay, and anything within 0.3 mi of a usual start) would take it out. Asked, the owner kept it in. Applying it would move the line every one of those tables, the hour strip and the floors are built on, and would also take out a genuine first stay at a restaurant row; the time at home is time online, and the driver knows which cell is home. The Offers around you tab and the Overview's waiting areas still leave home out, because a dot or a named area there would draw the house, which is a privacy rule and not a statistic. Do not re-propose taking home out of the three.

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

**What round B of the reporting work left undone, on purpose (Nov 2026).** (1) The owner's special days live in `special-days.json` beside each server's journal, so the rig and the NucBox each keep their own: rpi/sync.py carries journal rows and notes, not this file, and a day marked on the phone is not marked on the NucBox's report until it is marked there too (a `kind` of journal row would ride the sync, at the cost of a new row type on both ends). The places report's front page does not leave special days or re-offered cards out; the Trends tab's switches are its only reading of them. (2) The re-offered rule is two shapes the journal can show; an order offered again with a new pickup text (a misread name) or under another app is not caught, and two orders from one store to one door inside 30 min are caught as one; checked only on invented journals, never on the owner's. (3) Where on the offers page reads the newest 5,000 offers the list holds on a long range (said under it).

**Left from the reporting review's fix round A (Nov 2026), on purpose.** (1) /api/trends' time column is not delta-encoded (T9's optional half): gzip took the 3x answer from 1.32 MB to 455 kB, and a second encoding is one more thing for `unpack` and its checks to hold. (2) The first chunk of a Trends draw still holds the month thirds and the hour × date timeline, about 1.2 s of the 3x record on a 4x-throttled phone; moving them after the paint is one line in journal.html's `PARTS` once the layout round says what opens first. (3) A match already filed keeps the card pay it was filed with until its day is filed again (an upload, a pick): F6's corrected `cardPay` reaches new and re-filed matches only, so the week card's paid-against-the-card can still show an old $1.68 match until then. (4) The offers page's Gold card (/api/gold, server.js `goldOrders`) does not carry the drop row's `by`, so there a Took taken back on the offers page is still an accept; the places report's Gold section no longer counts it. (5) At a 40% night-to-night swing the week card still names a best or worst slot in 60% of weeks: those evenings did differ, and the card now says "that evening"; it is not a pattern and is not shaded as one. (6) The review's own repro scripts f4_rulers.js, f5_takenback.js and f6_cardpay.js call strategy.js and earnings.js directly without the new inputs (`rulers`, `by`, the folded offers), so they print the old figures; the fixed paths are the places report's and the server's, and the suites hold those. (7) The Trends tab's layout and wording are a later round's; nothing here moved a section. (8) tools/report_check.js has been run on the real journal once (its Done entry above); what it found about re-offered cards is not yet acted on.

**On the rig's panel, one moving card has no row left for its notice (Nov 2026, with the half-width card).** At 1024x600 the card is 500px and laid in fixed rows; under the address the slot holds the pair line, the on-the-way line and the notices. With the widest pair (a loss to $133, 55–105 min, a ceiling, ENDS ELSEWHERE on a row of its own), the on-the-way line, a long pickup, the car moving (each end a line) and the notices up, the slot is full before the first chip: the notice is squeezed to nothing and its chips are a scroll away (without the on-the-way line it keeps 16px of a 29px chip row). test_layout holds every other form whole and lets this one's notice go. Since the pickup and the dropoff have a line each parked as well (Nov 2026), the same form parked is in the same place. Ways out, none taken: a smaller headline (it is 141px; 40px more slot would take it near 95), the pair's chips beside its range (they do not fit 476px), or the address on one line while moving (the owner's 17 Oct decision gives each end a line).

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
nine `areas` permutations once per journal state and window (keptAnswer,
Nov 2026): a load with nothing appended since is free, but the first load
after each appended offer still pays it whole (about 25 ms on 480 offers on
the dev box, about 200 ms on an invented 15,000 over 30 days, more on a Pi
asked for All). Tests: tests/advice.test.js
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

**Readings filed before the 17 Nov reader fix keep their rows, a wrong one among them (18 Nov 2026).** A screenshot uploaded before the fix was filed with the old reader, and nothing re-reads a kept reading's text: "Read again" reads only pictures not read yet. Uploading the screenshot again files the trips the new reader finds, but the canceled $0.00 trip the old reader filed at the next ride's time stays on file as its own row (a canceled and a completed trip of one minute are two trips) until a way to re-read a kept reading and retire the rows it no longer produces is built; the day's tally on the page is computed from the reading's text by the reader as it stands, so it can say "6 read" beside rows the old reader wrote. Also open: an amount that lost its point AND its glyph (bare digits, no "$") is not read; the ride matching by street is tuned on one invented ride card, as the rest of the matcher is on invented days; and the ride kinds Uber prints are a list from one screenshot plus the usual names.

**The earnings matcher is tuned on invented days built like one real evening, and two things about Uber's screen are still guesses (8 Nov 2026; the time read as the start, 13 Nov).** The owner's screenshots are not in the repository, so `earnings.js`'s weights (start 40, finish 15, name 25, corner 10, dropoff 15, miles 10, pay 10) and thresholds (`ACCEPT` 60, `MARGIN` 15, the start and finish bands, the offset from two confident matches) are held to invented days shaped like one evening of seven trips; a week of real uploads against the order records would say whether "needs you" is asked too often or too seldom. The pay part leans the matcher toward orders whose pay held, so a trip whose tip was cut has a little less to match on; it is never a penalty, and on that evening seven of eight trips were within 25 cents. Guessed: that a trip past midnight under a day's heading belongs to the small hours after it (`startMs`, the driver's 4am day; never seen on a screenshot); and that tesseract reads the real screen as it reads the drawn one — dark mode, the real map's labels and the phone's own font are untried. Also open: a screenshot that shows no day is filed only with a dated one in the same upload or under a day picked on the page; two different trips of one minute at one restaurant with the same amount would be kept as one; rows written on the NucBox stay on the NucBox (the sync runs rig to NucBox), so the rig's own offers page shows what was paid only for uploads made to the rig; with keepPlaces off the rows keep no names, so a later re-match (a pick, Read again) has only the clocks, miles and pay; and no DoorDash earnings screen can be read until a screenshot of one is seen.

**Miles driven between jobs, and restaurant dwell, cannot be read off the journal alone (Trends round, Nov 2026).** Measured in the code before building: the only journal rows with a position are offer rows. `seen` rows (scan_pi `note_tally`) and health tallies carry no fix; order rows carry the drive's total miles off the live GPS but no track; `drop` and `finished` rows say how an order ended, not where. So between jobs the positions are the cards' own, as often as cards come (the Waited tab prints the median gap and P90 for its window), and a path through them is a lower bound, which is what the places report shows; miles actually driven need the GPS log, which only the Best tab's dead miles reads (`--gps`). Dwell at a pickup needs fixes during the wait at the store, which the journal has only when a card happens to arrive there; server.js `storeWaitsOut` already measures store waits live from the GPS stream (the stop pattern after a Took), and re-measuring them from card fixes was not built. Also open from that round: `/api/trends` is refused under lite in server.js rather than in `lite/lite.js`'s list of shut doors, which another round was changing at the time — moving it into that list is one line; and the Trends tab's grid and calendar compare against the whole range's median, so a range spanning a pay change shades the old weeks against the new ones (the daily chart shows that shift, the grid does not say it).

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
