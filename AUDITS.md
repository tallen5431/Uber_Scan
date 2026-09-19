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

**A frame holding two cards priced one and described the other.** `one_card()`
bounded the legs and nothing else, so the distance, deadline, item count and
merchant went on reading the whole frame while the payout took the largest.
30 of this driver's 272 cards arrive on such a frame. Fixed in `ae510ce` by
`card_span`/`only_card` in both ports; the measurement is at the foot of this
file.

**A glare frame threw away a verdict the rig already had.** `collect()` took
the last frame of the batch whether or not it carried a payout. `read_the_money`
now picks the newest frame that states one and folds the rest in. `123fa02`.

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

**The box note went stale in both directions, and the worse one was unfiled.**
`setAdjusting()` writes its sentence only at the instant adjust mode is
entered, and the whole-frame checkbox is the one control that can falsify it
afterwards. Ticking it left "drag the box onto the card" over a box whose drag
handler returns immediately — annoying and visibly inert. **Unticking** it left
"the box is not used" standing while `sourceRect()` had just started cropping
every read to that box: the driver is told the crop is off while the crop
decides whether anything is read at all. One line, `setAdjusting(adjusting())`
in the change handler.

### The backup

**Three ways the rig reported a healthy backup it did not have.** A row stamped
past the end of time ended the window for every row behind it; the journal being
unwritable was not checked at all; and the verdict on the off-car backup was
inverted with respect to the danger, so the check passed in exactly the case it
exists for. `a5cbe64`, plus the `CLOCK_BELIEVABLE_UNTIL` clamp in `server.js`.

### The panel

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

## Open — known, checked, not done

None of these are bugs on the road today. They are things worth doing that
nobody has done, listed so they are not rediscovered as news.

**The live map draws nothing until every lookup finishes.** At one geocoder
request a second that is several seconds of empty rectangle during a decision
measured in tens of seconds. Drawing the car first, then each place as it lands,
would put something useful on the glass immediately.

**The two dropoff pins are pixel-identical** — the held order's and this card's.
The thing the driver came to compare has to be told apart by clicking each dot.
`mapDot` already takes a `ring` flag that carries the right meaning.

**`judge()`'s "this cannot be right" uses a distance the rig already distrusted.**
Where `milesUncertain` is set there is no yardstick at all, so the pair should be
marked unjudged rather than accused; where `milesCorrected` is set the popup
should say the card's figure was corrected.

**The geocode cache does not sync to the NUC.** It is the one thing the owner
asked to sync that does not: `remember()` goes to real lengths to merge across
two *tabs* and does nothing across two *machines*, while the journal syncs both
ways.

**A wrong remembered lookup can only be fixed by wiping every good one.**
`map.html` is the one surface that can *identify* a bad geocode — the stray rows
are already listed and already tappable — and all it can do is throw the whole
cache away. (The cure proposed by the audit was refused; see Settled.)

**No map can be asked about a time.** `journal.html` already buckets every offer
by hour and by weekday; `map.html` has only a day count. A weekday plus
three-hour-block filter would make the map answer a question *before* a shift
rather than only after one — on the parked desk page, where the six-control panel
bar does not bind.

**The phone's unsent queue only ever grows, and fails silently when it is
full.** `uberscan.unsent.v1` is shortened only by a flush that lands, and on a
phone with no rig reachable — a documented mode, since the README offers GitHub
Pages, where the ingest POST 404s — nothing ever prunes it. Measured: about
156 KB per 200-offer shift, roughly 5,000 rows to fill a 5 MB localStorage. At
that point `save()` catches the QuotaExceededError and swallows it, `keep()`
hands back a row that was not stored, and `scan.js` has already set `recorded`,
so the card is gone and the page still paints its verdict. `journal-client.js`
opens by saying nothing here "loses anything when [the network] is absent",
which is exactly the case in which it does.

The cure needs care and is not what it first looks like: `record()` is called
on the **lock transition**, not per frame, so simply withholding `recorded`
does not retry the card — it waits for three empty reads to drop the lock. And
`save()` failing means storage-off (private mode, blocked site data) at least
as often as storage-full, so a message naming either one is wrong half the
time. The honest shape is: have `save()` report success, keep `recorded` so the
card is not re-entered, say something true on a bounded hold, and give
`scan.html` the queue count `ui.js` already gives the keypad. Do the README in
the same commit if a cap is ever added, or the cap becomes a false claim there.

**The panel's caption row has a stated budget that one sentence in ten keeps.**
`live.html` writes the rule down — short, because the line is a row of the panel
— and then emits nine sentences up to 125 characters. Either cap the row and let
the map keep its height, or rewrite the nine.

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
