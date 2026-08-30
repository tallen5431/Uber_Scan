# Raspberry Pi scanner (IMX519)

The Pi does everything: its own camera watches the phone screen, and the Pi
reads the offer and tells you the rate. Nothing is sent anywhere, no second
device is involved, and it needs no network once it is set up.

This is the version worth building. A fixed mount is what makes the reading
reliable, and it removes the alignment problem that makes a hand-held camera
fiddly.

> The browser scanner (`scan.html`) is a **different, phone-based** experiment
> and is not part of this. It uses the browser's camera API, which cannot see a
> CSI camera — opening it on the Pi fails with `NotFoundError` no matter what
> permissions you grant, because there is no webcam to find. Everything below
> uses the camera directly instead.

## Quickstart

```sh
sudo apt install -y python3-picamera2 python3-opencv tesseract-ocr espeak-ng
pip3 install pytesseract --break-system-packages

python3 rpi/autopilot.py --speak
```

That is the whole thing. The autopilot checks its dependencies, and if the rig
is not calibrated it serves the aiming preview on
`http://<this-pi>:8081/`, waits for the mount to be big enough and sharp enough
for several readings in a row, calibrates itself from that frame, and starts
scanning. Already calibrated, it goes straight to scanning. `--recalibrate`
starts over.

"That frame" is meant literally, and for a while it was not. Aiming proved six
frames in a row were big enough and sharp enough, and then calibration grabbed
*one more* frame and wrote the corners it found in that one, unchecked. The gap
between them is exactly where a hand comes off the bracket, the phone dims a
step, headlights swing across the dash, or the lens hunts once more. Unlike a
bad read, a bad calibration is permanent: it is the quad every read of the
shift gets cropped from, and the only thing the driver sees is `no offer on the
screen to test against`, which is also what a perfect calibration says when the
phone happens to be idle. Calibration now looks through six frames, keeps the
sharpest one that clears the same two floors aiming used, and if none of them
do, writes nothing and says which way it went wrong. A box you drew by hand is
never refused — it exists because the detector could not find the phone, so
sending you back to that phase is no kind of answer — but it still gets pinned
in the sharpest of the six rather than in whichever arrived first.

It prints what it is doing at each step:

```
[aim] not calibrated — open http://<this-pi>:8081/ and move the mount until green
[aim] card is 290 px, needs 450 — move the camera closer
[aim] good: 873 px, sharp 772
[calibrated] wrote config.json
[scanning] starting scanner
$10.61/hr PASS  (pay $7.09, 34 min, 3.6 mi)
```

**If it never gets past `[aim]`,** the detector cannot see your phone — a
reflection, a second lit screen, or no dark border to tell the screen from the
room. Open `/live.html`, press **▣ Set box** and drag a box around the offer
card: that calibrates the rig on what you drew and starts it scanning. See
[Draw the box yourself](#draw-the-box-yourself).

Only one process can hold the camera, which is why this is one process rather
than four scripts to run in the right order. The individual steps still exist —
`doctor.py`, `preview.py`, `calibrate.py`, `scan_pi.py` — for when you want to
poke at one of them, but stop the autopilot first.

**If the web server is running this project, the scanner is already going.**
Starting a second one by hand gets you a clear refusal rather than libcamera's
"Failed to acquire camera: Device or resource busy":

```
the camera is already in use by this project (pid 3559) ...
```

Stop the server's copy first (`SCANNER=0` in its environment, or stop the
service) if you want to drive the camera by hand.

### Or run it from the web server

If you already manage this project with a process supervisor that runs
`npm start`, the scanner can live there instead of in its own service — nothing
to configure, since a supervisor gives you no shell to configure it in. The
server runs the **autopilot**, so an uncalibrated Pi sets itself up rather than
waiting for you: `/live.html` shows the aiming numbers, turns into the verdict
once calibration succeeds, and the camera preview is on port 8081 meanwhile.

| | |
|---|---|
| `/live.html` | the verdict, full screen, updating live — with the camera view |
| `/api/status` | scanner state and the last read, as JSON |
| `/api/events` | server-sent events, one per read |
| `/api/frame.jpg` | the most recent camera view, refreshed every couple of seconds |

The scanner is restarted with a backoff if it dies, its errors appear in
`/api/status`, and the site keeps serving throughout. `SCANNER=0` disables it,
`SCANNER_SPEAK=0` keeps it silent.

It is also restarted if it stops working **without** dying. A CSI camera that
stops delivering frames leaves `capture_request()` blocked forever: the process
is up, systemd is content, `/api/status` still says `running: true`, the live
page keeps its green dot, and the loop never turns again — a rig that looks fine
and reads nothing for the rest of the night. The scan loop says "still here"
every four seconds whether or not it has read anything, so thirty seconds of
silence from a running scanner is now a `SIGKILL` and the same restart a crash
would get. `SCANNER_SILENT_MS` moves the window. `/api/status` carries a
`wedged` count and a `wedgedAt`, and neither is cleared by the restart: `error`
correctly goes back to null once the replacement is up, and these are what is
left to tell you whether tonight was the first time or the fourth.

### Or as its own service

```sh
sudo bash rpi/install-service.sh
journalctl -u uberscan -f       # watch it work
```

Use one or the other, not both — two processes cannot share the camera.

Stop the service before recalibrating, so the camera is free:
`sudo systemctl stop uberscan`.

## Why the fixed mount changes everything

The phone-camera experiment kept losing the decimal point in `3.6 mi` — a
decimal is one or two pixels through a hand-held lens, and losing it turns a
$7.09 offer into negative earnings. On the Pi that failure mostly disappears,
because the geometry is known:

- the four corners of the phone screen are found at calibration, and **kept on
  the phone from then on** (see below);
- every frame is perspective-warped straight-on before OCR, so the text is
  square and evenly scaled instead of skewed;
- focus and exposure are pinned, so nothing hunts.

On the same test frame that defeated the handheld pipeline, the warped version
reads `3.6` unaided — the plausibility guard never has to fire. The guard is
still there as a backstop.

### ...but a mount is not a clamp

The corners are not used directly. The card is cropped as a *fraction* of
whatever they enclose, and that makes the whole thing sensitive to the phone
moving in a way that is easy to miss: slide the phone up until its top edge
leaves the frame, and the detected screen shrinks to the part still visible. The
same fraction now lands lower on the real screen, the crop walks off the payout,
and the scanner reports — perfectly confidently — that there is no offer, on a
screen with an offer on it.

One thing runs continuously to stop that, and one thing used to:

| | |
|---|---|
| **Corner tracking** (`track.py`) | The screen is re-found every 0.4s on the preview stream the motion gate already holds, which costs about a millisecond. A candidate must be the right **size and shape for the calibrated screen** — not for wherever the corners have got to, which is the distinction that matters, see below. Past that gate, a small correction is followed on the first check; a bigger move has to say the same thing five checks running, and is then either eased 35% of the way toward (if it is nearby) or taken whole (if it is not, which is a phone put back or a mount knocked). `--no-track` turns it off. |
| **Crop fitting** | There used to be a second mechanism here that moved the crop about looking for the card. It is gone — see below. |

### The gate was watching the cabin

The motion gate decides whether a frame is worth reading, and it is a mean
absolute difference over a thumbnail — of the **whole sensor frame**. The phone
is about a quarter of that. `scan_pi.py`'s own framing note says as much:
"the phone occupies perhaps a third of the frame: call it 160 pixels across"
of 480. Everything else is a dark cabin that does not change between frames, and
a mean divides the signal by all of it.

Measured on rendered cards mounted in a rendered cabin at 25%, 33% and 45% of
the frame, across blank-to-card and card-to-card transitions in both themes:

| | fires |
|---|---|
| over the whole frame, as shipped | **8 of 18** |
| over the phone window | **18 of 18** |

Every miss was in dark mode or a card-to-card swap. A card arriving on a
dark-mode phone at the documented framing scored **4.59 against a threshold of
6.0**.

The consequence is worse than a late read. A gate that does not fire leaves
`card_on_screen` false, and neither the resample burst nor the verify beat can
fire without it — so the card is not read late, **it is not read at all**. This
rig is driven at night: one recorded shift ran from half past eight in the
evening until half past two in the morning.

The fix is one argument. `quad_window` already existed for the exposure
measurement — it takes the preview frame, the calibrated quad in sensor
coordinates, and the scale between them — so the gate now takes the same scale
the tracker uses and measures the phone. Without a scale, or before a quad is
known, it is the whole frame exactly as before: an uncalibrated rig has no phone
to crop to, and the wide statistic is the honest one then.

Two things this does **not** claim. A payout swapped on an otherwise identical
card moves a few hundred pixels and no difference gate can see it — that is what
the verify beat is for, and asserting it would be asking the gate for something
it cannot do. And these are rendered cards in a rendered cabin; the structural
claim that a mean over the frame divides the phone's signal down does not depend
on the renders, but the magnitudes do.

The mutation that mattered was the third one. Removing the crop was caught by
`test_pipeline.py`; making the *loop* stop passing the scale was caught by
nothing, because a gate that works and a caller that never asks it are different
facts. `test_scan_pi.py` now records how the loop calls the gate. The fallback
needed a real quad to test, too: a synthetic quad centred in the frame clamps to
an empty box at 1:1 and `quad_window` hands back the whole image regardless, so
it could not tell a working fallback from a broken one. The rig's own calibrated
quad starts at x=564 of 2328, which at 1:1 on a 640-wide preview is a 76-pixel
strip down one edge — and the mutant scored 0.00 on it, which is `feed()` never
firing again.

### The crop stopped chasing the card

There used to be a whole machine here. The crop found itself: fit the box to
wherever the payout and the lines beneath it landed, widen it when reads
failed, tighten it when they worked, with agreement counting, settling times,
and a rule that a crop had to prove itself before it earned the right to sit
still. Every one of those rules was added to fix a real misbehaviour, and each
one did.

It still could not converge. A rig logged **sixteen crop moves in eighteen
minutes**, height going 0.70, 0.45, 0.70, 0.54, 0.74, 0.54, 0.71, 0.82, 0.92,
0.66, 0.46, 0.80, and spent the gaps reading whichever slice the last move had
chosen.

The interesting part is that nothing was malfunctioning. An UberX card and a
Shop & Deliver card are different heights. A two-leg card is taller than a
one-leg card. **Every one of those fits was correct for the card in front of
it, and wrong for the next one.** A crop learned from the last offer is a
memory of a card that is no longer on the screen, and no amount of hysteresis
fixes a design that is remembering the wrong thing.

So it is derived instead. Two things are known without learning anything:

- how much of the quad is card — measured per read, `card_share_of_quad`;
- that the card is aimed at the middle of the frame, because that is a thing a
  driver can actually do, and the one running this rig says they do.

That is enough to place a box (`centred_roi`), it costs nothing, and it is
right for the card *currently* in front of the camera rather than the last one.
It has the property the old machine could not have at any level of care: the
same mount produces the same box, every read, forever.

Across both card types, five card positions and mounts from 520px to 1450px of
screen width — **42/42 exact reads**, and the box is identical for an UberX
card and a Shop & Deliver card at every mount:

| screen in frame | card's share of the quad | crop |
|---|---|---|
| 520–760px (whole phone visible) | 0.50 | 0.70 |
| 900px | 0.52 | 0.72 |
| 1200px | 0.70 | 0.90 |
| 1450px | 0.84 | 1.00 — read whole |

**What was lost.** The old fitting could find a card the crop had slid off
entirely. Nothing can do that now, because nothing needs to: the crop cannot
slide off something it recomputes every read. What genuinely goes is the case where the
card is *not* near the middle — a phone mounted so the offer sits in a corner
now needs aiming rather than fixing itself. That is the trade, and it is the
one the driver asked for.

The one guard that survives is `money_is_clipped`: a payout hard against the
cut edge of the crop is half a number, and half a number still reads as a
number — a `4.95` rating with its top shaved became a `$45.00` offer in
testing. There is nowhere better to re-fit to any more, so the answer is to
report nothing. A missed offer costs one fare; a phantom $45 one costs an hour
driving it.

### The crop is loose on purpose

The box is the card's own height plus a fifth of the quad (`CROP_SLACK`), not
the card's height exactly. A tight crop looks efficient and is not: the card's
top edge moves with the service badge above the payout and with the card type,
and a crop that clips the payout does not degrade gracefully — it reports no
offer at all, or reads the rating underneath as one. Measured against cards
drawn anywhere from 0.34 to 0.58 down the screen, back when the crop was a
hand-set box:

| Crop | Exact reads | Lost the payout entirely |
|---|---|---|
| `[0.02, 0.48, 0.96, 0.50]` (tight) | 28/42 | **13** |
| **`[0.0, 0.40, 1.0, 0.60]`** | **42/42** | **0** |
| `[0.0, 0.30, 1.0, 0.70]` | 42/42 | 0, but slower and no better |

Where nothing was being clipped, the loose crop scored exactly the same as the
tight one for about 7ms. The slack costs almost nothing and the clipping costs
everything, which is why it errs generous — and why on a close mount, where the
card plus slack comes to more than the whole visible screen, the honest answer
is to read all of it.

One trap is worth naming, because it is invisible and it points the wrong way.
Text size in the finished image depends on the *warp height*, and if the warp
height were derived from the crop, widening the crop to stop it clipping the
payout would **shrink the text** — keeping more of the card and reading less of
it. The warp comes from how much of the quad the card is, which is a property
of the mount rather than of however much slack the box is carrying. For the
same reason `card_source_pixels` reports the height of the *card*, not of the
crop.

## Where the speed comes from

Not from tuning the OCR engine. From refusing to run it:

| | |
|---|---|
| **Motion gate** | A 640×480 luma stream answers "did anything change?" for ~1ms. The full read only happens when the answer is yes, so idle cost is near zero. |
| **Settle wait** | After a change, it waits for the picture to stop moving. Reading a frame mid-transition just wastes a read on motion blur. |
| **Warp to the screen** | Tesseract's cost scales with pixels. Feeding it a card instead of a 16MP frame is worth more than every other optimisation combined. |
| **Crop to the card** | The card is aimed at the middle of the frame, so the crop is the middle of the quad, sized to the card. On the rig's own health lines this is worth about **200ms of a 1100ms read** — real, but far less than the old self-fitting crop cost by wandering. |
| **Never look at the page upside down** | When a page scores badly, tesseract runs the whole thing a second time inverted, in case it was white-on-black. `preprocess()` hands it dark text on a light card every time, so that pass can never help — and it is charged exactly where it hurts, on the reads that fail. A map costs **282ms with it and 211 without**, a dark screen **199 against 154**. Half a shift's reads are of something that is not an offer, so over a realistic mix the median read goes **586ms → 438ms** with no change in what it reads. `-c tessedit_do_invert=0`. That "every time" is a promise `preprocess` now has to keep rather than assume — a phone in dark mode falsifies it, and [it turns the picture over](#when-the-phone-is-in-dark-mode) so the switch stays honest. |
| **Hand over a file, not an array** | pytesseract's array path routes the image through PIL, whose PNG encoder measured **93ms** — over a third of a read, spent compressing a picture tesseract immediately decompresses. An uncompressed PGM encodes in 0.1ms and reads identically: **262ms → 157ms**. It goes in `/dev/shm`, so the SD card is never in the hot path. Now only the fallback path: the kept engine is handed the array itself. |
| **Do not start tesseract at all** | Every read spawned a `tesseract`, and a fresh process re-loads and unpacks the LSTM model before it looks at a pixel — **81.8ms of a 129.1ms read, 63% of it**, paid again on each of the 4 (median) to 14 (worst) reads merged into one offer. The engine is now initialised once and kept: same `libtesseract.so.5` the binary wraps, already on the box as its dependency, so nothing is installed. Byte-identical output, checked row for row across light and dark cards at four mount distances in both page-segmentation modes. A whole read goes **187.1ms → 88.3ms**. See [Keeping the engine](#keeping-the-engine). |
| **Look in the middle first** | The screen is the biggest bright thing *that the middle of the frame is inside*, falling back to plain biggest. Size alone is a guess about the scene and it loses to a lit dashboard panel or a window at dusk; with a panel larger and brighter than the phone beside it, the old rule locked onto the panel and read nothing while this one reads the card. |
| **Track on the small stream** | Re-finding the corners uses the 640×480 luma the motion gate already has, not a shrunk-down sensor frame: **0.96ms against 6.98ms**, almost all of the difference being the shrinking. It also means tracking needs no full-resolution capture at all, so it keeps working at full rate while the scanner is otherwise idle. |
| **Confirm in parallel, not in series** | A verdict waits for two reads that agree, and that confirmation earns its keep: over rippling, soft, glared and dim frames, one read claiming a whole offer was **wrong 1 time in 36**, and two agreeing were wrong none. So the checking is not what gets shortened — the waiting is. The frame after the trigger is captured too and both are read at once, which measured **56% of the cost of two in a row** and halves the time to a verdict for exactly the same evidence. Requires `OMP_THREAD_LIMIT=1`, which scan_pi sets: unpinned, two tesseract instances fight over all four cores and the same pair took **46 seconds** against 435ms. `--no-parallel` goes back to one at a time. |
| **Stop when there is nothing left to learn** | Sampling continues after a card appears so a leg missed by one frame can be caught by the next — but it stops as soon as the reading is *whole* (a total, or both legs of a two-leg card) and two reads running agree. In a 30-frame run over one offer that is 2 reads instead of 9. What keeps sampling is the case that needs it: a single leg that is not a total, which is the shape of a card with a leg still missing. |
| **Do not hold the camera while reading** | The read ran inline, so for its ~1.4s the loop serviced no capture requests: the live view froze, and the tracker's 0.4s recheck — the thing that corrects the corners the *next* read will use — could not run either. It now runs on a thread, with the geometry frozen and handed over alongside the frames so a read is a pure function of the two. Measured with the read pinned at 1.2s, the worst gap between live-view frames goes **1220ms → 67ms**, and the second number does not contain the read at all: it is the loop's own slowest step, so it stays put as the read gets slower. `--no-thread` is the way back. See [The read does not hold the camera](#the-read-does-not-hold-the-camera). |

...and then one place where it is worth spending, in the opposite direction:

| | |
|---|---|
| **Read size** | The cropped card is scaled *up* to 900px before OCR. Tesseract is trained on scanned pages and wants roughly a 20px x-height; a healthy 420px card cropped out of a 900px screen arrives with eight lines of text on it and an x-height near 10px, squarely in the regime where it starts inventing digits. Interpolation adds no information, but it puts the strokes back on the grid the engine expects. |

## Measured

Two sweeps, on a desktop-class x86 container, using camera-simulated frames of
real offer cards.

**Read size is the accuracy lever.** Exact reads — all three of pay, minutes and
miles correct — over 36 synthesised frames spanning card sizes from 350 to 500
sensor pixels, three noise seeds, straight-on and tilted:

| Read size | Exact reads | OCR |
|---|---|---|
| as cropped (~450px) | 12/36 | 158ms |
| **scaled to 900px** | **29/36** | **257ms** |

Every one of the seven remaining failures is the detector declining to find the
screen at all on the smallest, most tilted frames — not a misread. Sharpening
and Otsu binarisation were tried here too and both made things markedly worse:
an unsharp mask eats the thin `$`, and Otsu closes up the small digits.

**Warp height is the speed lever**, median of repeated reads at a 900px read
size:

| Crop | Warp height | Pixels to OCR | OCR | Total | Result |
|---|---|---|---|---|---|
| whole screen | 1400 | 644×1400 | 162ms | 166ms | correct |
| whole screen | 900 | 414×900 | 134ms | 136ms | correct |
| whole screen | 700 | 414×900 | 133ms | 136ms | **fails** |
| card only | 1100 | 794×900 | 179ms | 183ms | correct |
| **card only** | **900** | **794×900** | **178ms** | **181ms** | **correct** |
| card only | 700 | 795×900 | 172ms | 176ms | correct |

Everything before the OCR call — warp, crop, scale, CLAHE, staging the file —
totals **2.7ms**, and parsing the text costs 0.3ms. There is nothing left to
optimise outside the engine itself; what is left is not calling it.

Things tried here that did **not** help, so they are not in the code: an unsharp
mask (19/40, it eats the thin `$`), Otsu binarisation (25/40, it closes up the
small digits), a character whitelist (loses the distance entirely), `--psm 4`
and `--psm 11` (both slower, no more accurate), `tessedit_do_invert=0`, and
pinning `OMP_THREAD_LIMIT`. The last two are worth re-measuring on a Pi 4, where
the core count differs — `bench.py` is the way to check.

**A Pi 4 is slower than this — expect roughly 2–4×**, so budget ~0.4–0.8s per
read and a couple of seconds to a verdict two reads agree on. Against a 30–45
second offer window that is ample. Measure it yourself with `bench.py` rather
than trusting these numbers; that is what it is for — it sweeps both axes, and
the read-size rows are the ones worth reading first.

Between offers the cost is the motion gate plus corner tracking, measured
together at **0.6ms per frame** — the scanner is asleep almost all of the time,
which is the only reason a Pi 4 can do this at all.

### While a card is up

The motion gate cannot help here, and that is the expensive part. A *replacement*
offer redraws a few digits inside an otherwise identical card, which moves the
frame difference to 0.33 against a threshold of 6.0 — indistinguishable from
nothing happening. So the only way to know the verdict on screen still belongs
to the card in front of the driver is to look, on a timer.

That timer used to be a flat 2.5s. At ~1.4s a read on a Pi 4, that is **56% of
wall clock inside tesseract** for as long as an offer sits there. It also bought
almost nothing: the recording above spends seventy seconds re-reading a card
that says the same thing every time.

So the beat **backs off while nothing changes** — ×1.6 per identical read, up to
a ceiling — and snaps straight back to 2.5s the instant a reading differs or the
screen empties. The case the timer exists for costs exactly what it did before,
one beat; the case it was wasting on settles at about **12% duty instead of
56%**.

**The ceiling is that duty divided into what a read costs**, and it moved when
the read did. It was 12s while a read was ~1.4s. Keeping the engine alive
roughly halved that — the owner's shift recorded a median `ms` of 1517 before
the change and it measured 2.12× end to end, so call it 715ms — and 12% of a
715ms read is **6s**. Same duty, half the wait.

The wait is the thing being bought. A replacement offer does not move the motion
gate, so the ceiling is exactly how long a driver can be looking at a verdict
belonging to the previous card:

| | read cost | ceiling | duty | worst case |
|---|---|---|---|---|
| a flat beat | ~1.4s | 2.5s | 56% | 2.5s |
| backing off, slow reader | ~1.4s | 12s | 12% | 12s |
| backing off, kept engine | ~0.75s | **6s** | 12% | **6s** |

The ceiling is now reached after two identical reads running (2.5 → 4.0 → 6.0)
rather than four. `READ_SECONDS` in scan_pi.py is where that cost is written
down; two constants are derived from it and one of them lives in another file,
which is how the last one went stale.

### What the preflight can and cannot see

`doctor.py` is what a driver runs when the rig will not work, and it was silent
about the two states that are working-but-worse — the two that are invisible
from the outside precisely because the fallback is deliberate:

| | |
|---|---|
| **reading engine** | Whether the OCR runs in this process or spawns a `tesseract` per card. Both read identically and one is about twice as quick; the fallback is silent by design, so the only symptom is a `ms` column in the journal that is double what it should be, noticed months later. |
| **scratch space** | Whether `/dev/shm` is writable. On it, the live view and the OCR staging images cost nothing. Without it they go to the SD card at roughly **5GB an hour**, onto the one component in the rig that wears out, and nothing anywhere says so. |

Neither is blocking, and that is the point of adding them rather than the
detail. A rig spawning a process per card reads every card correctly; a rig
with no RAM disk still scans. Reporting either as a refusal to start would make
the report noise, and the whole value of a preflight is that its failures mean
something.

`test_doctor.py` holds it to that: it runs the real thing, checks every line is
marked `ok` or `FAIL` rather than printed into the void, compares both new
findings against the thing they claim to describe, and then forces the slow path
with `UBERSCAN_TESSERACT=binary` and asserts the report *changes* while the
blocking count and the exit code do not.

### Where the job goes, on the screen that decides

The scanner has sent `places` on every read since it learned to read a map, and
until now the only screens that painted it were the offers page and the CSV.
The driving screen — the one a driver is actually looking at while the timer
runs — was the one that could not tell them whether they recognise the job.

One line under the figures, ellipsised, dimmer than the numbers, and two places
joined with an arrow the way the offers page writes them so the two screens read
alike. It is what you scan to recognise a job rather than what you judge it by,
so it is never allowed to take room from the headline: an address runs to sixty
characters and this panel is read at arm's length in a moving car.

It clears when the card does. Left up, the last job's address reads as belonging
to whatever arrives next.

### Marking one as taken, from the seat

Whether the driver pressed Accept is the one fact the rig cannot see, and it
must never press it — so a driver saying so is the only way that fact ever
reaches the record. Until now saying so meant opening the offers page, finding
the row among the ones that scrolled past while driving, and pressing it there:
four deliberate actions with a bluetooth mouse, after the timer had started.

It is one button on the driving screen now, and the interesting part is what it
is named. `live.html` replaces its verdict on any reading that carries a
`ready`, and a phone showing the navigation screen produces exactly that — so
**by the time a driver has accepted, the card is already gone from the panel**.
A button saying "took it" would be marking something they can no longer see, and
on a screen where the previous offer's figures were still up a second ago, that
is a mismarked row rather than a missing one. So the scanner announces which
offer it just wrote — `{"offer": {"id", "pay", "minutes", "perHour"}}` — the
server holds it on `/api/status`, and the button carries the amount: **`Took
$8.04?`**, then **`✓ Took $8.04`**. It survives a reload and a dropped socket,
because the normal case is the driver looking at this screen *after* the card
has gone.

Three things it does not do:

- **It does not mark by the figures.** `{match: {pay, minutes, miles}}` is a
  rule that catches every offer paying that to the cent, and two genuinely
  different cards doing that inside one window is a case already in
  `test_repeats.py`. It marks by journal id.
- **It does not touch the phone.** Same rule as everything else here: the rig
  reads, it does not tap. The label is past tense for that reason — an
  imperative on a panel next to a live verdict can be read as doing something to
  the offer.
- **It does not announce once per read.** The card is re-read for as long as it
  sits on screen; the announcement is guarded so it goes out once per card. Left
  unguarded it is a message a second on the socket the driving screen watches
  for verdicts, and the suite fails on the count, not on the distinct ids —
  asserting only that the ids matched passes just as well when every read
  announces again.

Pressing it again unmarks it, which is a note of its own rather than a deletion.
The mark belongs to the offer and not to the button: when a new card is
announced the button goes back to unmarked, so a mark left set cannot be
inherited by whatever arrives next — the same failure the address line avoids by
clearing.

### ...and what the shift adds up to

Marking was write-only. A driver could put a fact into the record from the
driving screen and never see it come back: the figures that fact feeds live on
the offers page, which is the wrong screen to be on while driving.

One line on the status row now: **`· 9 offers · 1 set aside · took 3 · median
$26/hr`**. Three things decided it.

**Where.** Not inside the verdict card. That card has 20–50px of slack at
800×480, and the rules that fire when a notice shows already spend a line's
worth of it buying the headline room back — on one real shift that was 52 of 121
offers. Its overflow does not scroll either: `#verdict` centres its children with
plain `center`, so the excess clips off the *top* and the word ACCEPT goes first.
The status row is `auto` height and already holds one line, so a second item on
it is nearly free, and it outlives a card — which is the point. The address above
clears when the offer goes because it belongs to that offer. A shift does not.

**Who computes it.** The server, from `require('./advice.js')`. The alternative
was loading 25KB of advice engine onto a page that must start fast, or writing a
third copy of "a row worth counting" — and `advice.js:116` and `journal.html:480`
both record what happened the last time that rule existed twice: a duplicate that
never excluded hidden rows, masked for exactly as long as nobody asked the server
for them. `/api/today` takes `since` from the *browser*, for the same reason
`/api/journal` does: 4am is the boundary, and only the page knows what timezone
the car is in.

Every figure comes off one filtered set, which is the rule the offers page
learned the hard way. In particular **taken is counted first and accepted
second**: an offer marked as taken whose reading was partial is not in the taken
figure, because it is not in the median either. Taking `accepted` over the raw
window instead would put a bigger number on the driving screen than the offers
page shows for the same day.

There is deliberately no dollar total. `pay` is what the card offered, not what
was earned, and a gross sum beside a net median is the exact sentence the offers
page was corrected for.

**What it costs.** A full journal parse — split, then a `JSON.parse` per line —
on the event loop that also drives the 12ms MJPEG tick and touches the file
telling the scanner somebody is watching. A year of driving is ~19MB and the best
part of a second of frozen loop on a Pi 4. So the page asks every three minutes,
matching the budget `/api/journal/newest` already set for a journal-reading GET,
and the answer is cached against the journal's size and mtime — append-only means
size is monotonic where mtime granularity is not. The cache holds the finished
summary and never the parsed rows, which `latestPerOffer` writes `hidden` and
`accepted` onto.

Four states print words instead of a count, because in each of them a plausible
number would be a wrong one: the rig's clock has not been set (it has no RTC,
boots in 1970, and its unit is not ordered after time-sync — so it genuinely can
record offers before it knows what day it is); the journal could not be read,
which looks identical to a quiet day; the journal rolled past 64MB inside this
window, which also looks like a quiet day — tested on the roll's own age, since
`journal.py` rolls with `os.replace` and nothing ever removes the sibling, so
"a `.1` exists" is true forever after the first roll and would announce it every
quiet morning for years; and the endpoint is not there at all, which is what
a build one `git pull` behind does — as a *text/plain* 404, so `.json()` rejects
rather than returning a status to branch on. Offers stamped before the clock
was set can never fall inside a day window; the count of them is in the
response but deliberately not on the line, because it is true of every day
forever and a suffix that never clears would blame this shift for rows from
some past boot.

#### The two figures that would have disagreed

Adding a count beside the mark button made an existing fault visible and
introduced a second one, and both are the same failure: two figures forty pixels
apart, about the same act the driver just performed.

`tookState` was page-local and never seeded, so marking an offer and reloading
the panel offered to mark it again — while the count had already counted it. The
mark route now records `accepted` against the offer the driving screen is
holding, and the page seeds from it. And marking refetched nothing, so pressing
"took it" and watching the number beside it not move was the whole experience
until the next poll. Marking is the only thing on this screen that changes the
count, so it is the one time the figures are worth asking for off the timer.

`test_dashboard.py` holds both: it asks whether the count moved, and — because
asserting a hidden line on a page that never got an answer proves nothing, since
it starts hidden — it puts figures on the panel first and then takes the endpoint
away.

#### What an adversarial review of it found

Six reviewers over the finished diff, each finding independently put to three
refuters. Twenty-one claims, and the ones that survived were all the same shape
— a figure that was *nearly* the offers page's figure:

- **Hidden rows were counted twice over.** `/api/journal` drops them before the
  offers page ever sees one, so a hidden row is in neither its count nor its
  set-aside figure. Here it was in *both*: counted as an offer, then rejected by
  `trustworthy` and reported as one the scanner had set aside. The driving
  screen read "6 offers · 2 set aside" where the offers page read "5 offers (1
  set aside)" for the same day — and blamed the reader for an exclusion the
  driver had made. Three of the six reviewers found this independently and one
  reproduced it against a running server.
- **`beforeClock` was an all-time tally on a line about today.** Removed from
  the line.
- **`rolled` announced a roll forever.** Five findings hit this one.
- **"waiting for the clock" was unreachable on the rig.** The panel's browser
  runs on the Pi, so an unset clock made `dayStart()` a 1970 moment, which the
  server refuses — correctly — and the line simply vanished with nothing said.
  The page now checks its own clock first; the server's answer still covers a
  phone with a good clock looking at a rig without one.
- **A hung fetch froze the figures for the shift**, and a mark landing during
  the slow poll was dropped and then repainted with the pre-mark count.
- **Two checks that could not fail.** `oneLine` compared a flex item's height to
  its container's, which is true of every flex item at every size. And seven
  existing mark-button checks had been re-parented under an unrelated `if`.

The `rolled` fix then failed its own new check, which is why it was written: the
flag depends on the sibling's mtime and on `since`, neither of which is the file
the cache is keyed on, so a roll that happened while `journal.jsonl` itself did
not change was served the previous answer's `false` — the one state it exists to
report, reported wrong. It is answered outside the cache now, like `clockSet`.

**Known limit:** the machine at home runs the same `server.js` and will answer
with its own journal, which the sync timer leaves up to eleven minutes behind,
and marks made there never flow back. The line sits directly beside "no Pi
scanner on this machine", which is the signal that it is a copy — but it is not
suppressed there, and the figures are the copy's.

### Nothing the rig writes may become a commit

`rpi/.camera.lock` is written into the checkout and holds a pid, and nothing
ignored it — so `git add -A` on the Pi committed a working directory's worth of
state to a public remote. Adding the line is the fix; the interesting part is
that a hand-kept list is what let it happen, and checking the list found two
more.

Every one of these files is written through a temporary and renamed into place,
and the temporary names are not all `<name>.part`: the crop endpoint appends a
pid and a counter, so `.cropbox.json.4321.7.part`, because two drags landing
together must not interleave into one file. Named exactly, three of those were
committable. They are globs now.

`test_lint.py` derives the list from the code rather than keeping its own:
anything joined onto `rpi/` as a literal, plus handoff.py's fallback names, has
to be covered by `.gitignore` — including a `.part`, a pid-suffixed `.part` and
a `.tmp` for each. The next runtime file cannot be forgotten, because nothing
has to remember it.

### A verdict is only as fresh as its own clock

The driving screen seeds itself from `/api/status` so a tab that has just opened
is not blank until the next read, and the server sends the last reading again to
every socket that connects for the same reason. Both were adopted as if they had
just happened. Open the dashboard against a rig that stopped an hour ago and its
last ACCEPT was painted at full confidence: **12 seconds before it dimmed, 20
before anything said how old it was** — and every reconnect after that started
the clock over, for as long as the tab stayed open.

That is the confidently-wrong number this project's first rule is about, on the
one screen whose entire job is a verdict, arriving without anything going wrong.

The fix is that both now carry **how old they are**, not when they happened.
`/api/status` answers with `lastAgeMs` and `heardAgeMs`, the replayed reading is
marked `replay` and carries `ageMs`, and all four are computed on the sending
machine's own clock. Ages rather than timestamps for a reason this page already
had written down about `at`: a Pi has no real-time clock, it boots in 1970 and
jumps when the network arrives, so subtracting one machine's idea of now from
another's is how "12 seconds old" became "fifty-six years old" — and worse, how
a negative age never tripped the staleness test at all. A duration has no origin
to disagree about.

An age that is missing or negative is treated as older than the window rather
than newer: a verdict of unknown age is exactly the one not to vouch for.

### Keeping the engine

Everything above is about running tesseract less. This one is about the part of
each run that was not reading anything.

`pytesseract` spawns a `tesseract` process per call, and that process loads and
unpacks the LSTM model before it looks at a single pixel. Measured here by
timing a read of a blank 32×32 image — whatever that costs is what is spent
before there is anything to recognise:

| | |
|---|---|
| a real card | 129.1 ms |
| a blank 32×32 | 81.8 ms |
| **so, startup** | **63% of every read** |

And paid again on each of the 4 (median) to 14 (worst) reads that merge into one
stored offer. A whole read, end to end through `Scanner.read`:

| | spawned per read | engine kept |
|---|---|---|
| read | 187.1 ms | **88.3 ms** |
| of which OCR | 169.3 ms | 71.4 ms |

**Same engine, not a different one.** `libtesseract.so.5` is what the `tesseract`
binary is a thin wrapper around, and it is already on the box as that binary's
own dependency — nothing is installed, and the rig keeps the binary too. Same
traineddata, same `--oem 1`, same `tessedit_do_invert=0`, page-segmentation mode
set per call so the psm-4 retry shares the engine rather than building a second.

That "same" is the whole claim, so it is checked rather than asserted:
`test_tesseract.py` reads light and dark screens at four mount distances across
all three card layouts, in both modes, and compares the two paths' per-word
tables **row for row**. 24 of 24 identical, down to the confidence figures.

**One engine per thread**, because `look_many` reads two frames at once and a
`TessBaseAPI` cannot be shared. Each holds its own model: measured **+11.7MB**
for the first and +14.2MB for the second, which is the price of this — memory
for time.

That is also what made the paired read a memory leak, and it is worth writing
down because the mistake is invisible from either side on its own.
`look_many` built its `ThreadPoolExecutor` inside a `with` and shut it down at
the end of the call. Free when a read was a process; ruinous once the engine
belongs to the thread, because a fresh pair of threads per read is a fresh pair
of engines per read. Measured: **12 engines after six paired reads, RSS 151MB →
286MB**, climbing for as long as the shift lasted, on a box with no swap. The
pool now outlives the call:

| | spawned binary | engine kept |
|---|---|---|
| paired read | 194.3 ms | **100.6 ms** |
| engines after 21 of them | — | 2, RSS flat at 159MB |

Under that sits a plain ceiling, `MAX_ENGINES`. The pool is the fix; the ceiling
is there because the thing being guarded against is a Pi running out of memory
mid-shift, and the cost of hitting it by mistake is one slow read.

**Every way it can fail ends with the rig still reading.** A missing library, a
missing symbol, an init that returns non-zero, an exception mid-shift: any of
them and the read goes to the binary, permanently, with one line in the log. A
command line the shim does not fully understand — `--dpi`, a word list — is
handed over rather than guessed at, because silently dropping a flag would read
the card under settings nobody chose. `UBERSCAN_TESSERACT=binary` is the way
back without a code change.

Two details worth knowing. `GetTSVText` is reached by its C++ symbol, since the
C wrapper does not export it; that is the one brittle thing here, it is looked
up at load, and its absence is simply another reason to use the binary. And the
library narrates to stderr — "Estimating resolution as 146" on every read —
which as a subprocess went to a pipe pytesseract discarded and in-process would
go to the rig's own log several times a second; `debug_file` sends it back where
it was.

`OMP_THREAD_LIMIT=1` moved from `scan_pi.main()` to `pipeline` at import for the
same reason all of this works: the engine is in this process now, and libgomp
reads the environment when it starts rather than when a subprocess is spawned.

**The "~1.4s a read on a Pi 4" figures elsewhere in this file predate this**, and
so do the arguments built on them — the verify beat's duty cycle, the case for
taking the read off the camera loop. They were measured with a process per read
and none of them has been re-measured on a Pi since. Both numbers here are off a
faster machine, so the honest thing to carry over is the ratio and not the
milliseconds: something close to half. A real shift's journal is the place to
check it, and it records `ms` on every row — the shift these figures were chased
with had a median of 1517ms.

### The read does not hold the camera

Cutting how *often* a read happens does nothing about what happens *during* one,
and that was the worse half. The read ran inline in the loop that holds the
camera, so for its whole duration no capture request was serviced: the live view
stopped, and it stopped hardest exactly when there was an offer on screen to look
at. It cost more than the picture — the tracker's 0.4s recheck could not run
either, and that recheck is what corrects the corners the *next* read will use.
The loop already knew, in a comment: a rig on record reached its verdict after
5.7 seconds and eight reads, seven of them of a rectangle that was being replaced.

The read now runs on a thread of its own and the loop keeps its camera. What
makes that safe is that the two halves were already separable:

* **`look_many(frames, now, geom)`** is the reading, and is a pure function of
  the frames and a frozen `Geometry` — the corners, the crop, the card's share
  of the quad, which way up the ink is. The geometry travels *with* the frames,
  because by the time a read finishes the tracker may well have eased the
  corners along, and a frame warped against corners measured after it was
  captured lands the crop where the card is not.
* **`settle(outs, geom)`** is everything the Scanner believes — the agreement
  counter, the measured card share, the dropped and recovered tallies — and it
  stays on the loop's thread, in frame order, exactly as before. So "two reads
  said the same thing" still means the same thing every run.

Measured through the real loop over a fake camera, with the read held at a fixed
1.2s, worst gap between live-view frames:

| | worst gap |
| --- | --- |
| read on the loop (`--no-thread`) | **1220ms** — the read, exactly |
| read beside it (default) | **67ms** — one and a half frames |

The point is not the ratio, it is that the second number **does not contain the
read at all**. It is the loop's own slowest step, so it stays where it is when
the read gets slower; on a Pi 4, where a read is ~1.4s rather than the ~200ms of
the machine these numbers came from, the first row grows and the second does not.

Two smaller things fell out of measuring it. One read at a time, always — two
would be four tesseract instances on four cores, the same mistake as an unpinned
`OMP_THREAD_LIMIT` and about as expensive — so a motion-gate trigger arriving
while the reader is busy is *remembered* rather than dropped; the gate fires once
per settling, and a dropped trigger is a card never read. And the live-view frame
is now written **before** the paired partner capture rather than after: waiting
for the next sensor frame and copying twelve megabytes of it is the longest thing
left on the loop, and that one reordering took the worst gap from 113ms to 67ms.

`--no-thread` puts the read back on the loop. Nothing needs it; it is there
because a threading change to the loop that holds the camera should ship with a
way back.

Card height 900 with the card crop and a 900px read size is the recommended
starting point: near the floor for speed, with real margin before reading
collapses.

## The phone does not have to fit in the frame

It used to have to, and that was the wrong call. The reasoning was sound and the
conclusion was backwards, so it is worth writing down which part was which.

Too close is a real failure mode, and a silent one. The detector finds the
*visible* part of the screen, which is a perfectly good rectangle, so nothing
complains — but every measurement after it is taken against a screen that is not
the whole screen. A real rig logged corners at `y=0` and `y=1746` of a 1748-row
frame, spent an hour walking its crop into worse and worse places looking for
the payout, and took 1.4–2.0s a read doing it.

All of that was true, and all of it was one fault: **the crop was a fraction of
the detected quad**, so it only meant anything if the quad was the whole screen.
Refusing to run unless the whole screen was visible fixed the symptom by
outlawing the mount.

And that mount is the one you want. A phone is about 2.15 times taller than it
is wide, the frame is 4:3, so fitting all of it makes the *width* the constraint
and leaves the screen occupying under half the frame height — around 400px of
card, the floor, from a rig that had 870 before it backed off. Clipping the map
away is precisely what buys the resolution that makes the text readable.

So the crop is placed from the measured geometry instead — how much of the quad
is card, centred — which does not care how much of the screen is showing. On a
mount close enough to clip the map away that comes out at or near the whole
visible view, which is the right answer: there is nothing there but card.

Spill is now reported and not refused — aiming says *"the top of the screen is
out of frame, which is fine as long as the whole offer card is visible"*, and
that last clause is the whole rule. Point it at the card, get as close as you
like, and let the map go.

### The number you aim by

One thing did not survive the change unaltered. `card_source_pixels` measured
the card by taking the detected screen's height and multiplying by the card's
share of it — which stops meaning anything the moment the screen is taller than
the frame, because the height being measured is then the *frame's*. It
saturates: past that point, moving closer cannot make it go up.

Which would have been a fine bug to ship, since the reading sits at ~439px right
under the 450 "good" mark, and the fix for a number that will not go green is to
move closer, and moving closer does nothing. The advice above would have walked
you into a wall.

A clipped screen is measured *across* instead, where nothing is missing, using
the shortest aspect ratio phones come in (18:9 — real ones are 19.5:9 or 20:9,
so this errs low, which is the right way to err for a floor):

| screen width in frame | spill | reported | real card | verdict |
|---|---|---|---|---|
| 340px | — | 368 | 368 | too small |
| 400px | — | 433 | 433 | workable |
| 480px | top | 479 | 520 | good |
| 660px | top | 659 | 715 | good |
| 900px | top | 899 | 975 | good |

### ...and the same mistake, one layer down

`CARD_SHARE` is the card's share of a **whole screen**, 0.5. Half the file used
it as though it were the card's share of the **quad**, and those are the same
number only when the whole screen is in frame.

A rig logged corners spanning 1690 rows of a 1748-row frame with the top of the
phone off the edge. Its quad was 86% card. Treated as 50% card, every read
warped the screen to 1800px tall when 1120 would do:

| | warp | what the reader got |
|---|---|---|
| quad assumed 50% card | 1444×1800 (2.60MP) | 977×1023 — shrunk to fit the ceiling |
| quad measured at 80% card | 900×1121 (1.01MP) | 900×943 — not shrunk at all |

`card_share_of_quad` measures it instead of assuming, and `centred_roi` sizes
the crop from that measurement rather than from a guess.

**How much that is worth is worth being straight about**, because the obvious
story is wrong. The obvious story: `MAX_OCR_PIXELS` caps what tesseract is
handed, the scaling to reach that cap is uniform, so an oversized warp came out
with its text below the size the code had just decided it needed — and on a
narrow crop that would cost the payout.

It does not. Cropped short and wide at four different heights and read both
ways, the trimmed version got its card down to 650px and still read the payout
every time. And the cap it was trimming to buys less than it appears to:

| what the reader was handed | OCR |
|---|---|
| 1.83MP | 227ms |
| 0.93MP | 193ms |
| 0.76MP | 180ms |
| 0.46MP | 167ms |

Four times the pixels for 26% more time. Tesseract's cost is the recogniser
walking the text, not the image — so "linear in pixels" is folklore, sizing the
picture down is not where reads get faster, and neither is sizing it up where
they break. What the wrong `card_share` really cost was 1.6MP of warping per
read for nothing, and a crop floor that could not be set correctly because
nothing knew how big the card was.

**The camera view on `/live.html` is live while aiming**, so the page telling
you to move the mount also shows you the mount. That matters more since the
refusal above: aiming is now a state you can be held in, and being held there
with no picture is being asked to aim blind. Port 8081 still serves the same
overlay as a full-size MJPEG stream if you want it — but note that the address
to open is the Pi's, not `localhost`, since the phone you are holding while you
move the bracket is not the Pi.

## Darkness and the wavy screen

A phone display is not a lit object, it is a strobe. Backlights and OLED panels
dim by switching on and off — commonly in the 60/120/240/480 Hz family — and a
rolling shutter reads the sensor one row at a time, so different rows of one
frame catch different parts of that cycle. The result is horizontal bands that
drift down the picture, which looks like the screen rippling and gives the
reader a band of the card that is dark this frame and light the next.

The cure is arithmetic, not filtering: an exposure lasting a whole number of
flicker cycles collects the same light in every row, and the banding cancels
exactly. Simulating a rolling shutter against a square-wave-dimmed panel
(`test_exposure.py`, so this is checkable without a phone):

| Exposure | 60 Hz | 120 Hz | 240 Hz |
|---|---|---|---|
| 8333µs | **102** | 0.1 | 0.1 |
| 12000µs *(the old default)* | **56** | **8.2** | **3.4** |
| **16667µs** | **0.1** | **0.1** | **0.1** |
| 25000µs | **40** | 0.1 | 0.1 |

16667µs is one 60Hz cycle, two of 120 and four of 240, so it is quiet against
all of them — and it is 39% brighter than the 12000µs this used to run at, which
is the other half of the complaint. It is the default now, and calibration
measures the real thing anyway: it tries **every** candidate against the actual
phone — the daylight rungs included, since those are where a bright screen
pushes the rig at run time — and elects the quietest one long enough for a dark
car. What the rest of them scored is kept rather than narrated, as
`exposureLadder`; see below.

Brightness is then handled by **gain first, exposure only along a ladder this
screen measured quiet** — a phone dims itself, and a screen set up in daylight is
a much darker subject at 2am. Full auto-exposure is not the answer: it hunts on a
strobing emissive panel and would undo the flicker arithmetic the moment it
decided the picture was dim. `--gain` pins it; `--no-auto-gain` stops it moving.

There is only one quantity worth controlling, and it is not the gain: how bright
the picture comes out is gain **times** exposure and nothing else. So the loop
decides what that product should be and then buys it with the longest exposure it
can afford and the least gain — exposure up to the calibrated value is free, gain
is noise. Written the other way round, as a rule for gain plus a separate rule for
exposure plus interlocks to stop them fighting, every interlock existed because
the two had fought: worst of them, moving a rung changed the brightness by a
factor of two all by itself, so lengthening a card that was merely a little dark
blew it out, which shortened it straight back, for ever. With the product
controlled a rung change is paid for in gain and the picture does not move, so
that cycle cannot be written down.

Both show up in the health line — `screen brightness 190/205; banding 0.4; gain
2.1` — so "it looks dark" and "it looks wavy" can be confirmed with a number
rather than argued about. Which is how the next one was caught.

That brightness figure used to be measured on the image handed to the reader,
which has been through CLAHE and, on a dark-mode phone, inverted. Contrast
stretching lands any card near the target whatever the exposure did, and the
inversion makes it read **backwards**: a dark-mode card far too dark reported
241 against a target of 205. The one instrument for "the picture looks too
bright" was answering a different question from the one the exposure loop steers
by. It comes off the raw screen window now, at the same beat, so the log and the
controller are talking about the same picture.

### Measure the screen, not the room

A rig logged `card brightness 233/205 ... gain 8.00`, then `237/205 ... gain
6.78`, then `198/205 ... gain 8.00`. Over-exposed, and asking for more gain
anyway, while hunting against its own 8.0 ceiling.

The gain loop was measuring the whole frame. Most of that frame is dark car,
and it distorts the two numbers differently:

- **Brightness** takes the 90th percentile, which is a stand-in for "the bright
  part, not the surround". Stand-ins drift: how well it picks out the card
  depends on how much of the frame the card is.
- **Clipped fraction** has no stand-in at all. It is a share of whatever it is
  given, so the dark surround divides it directly. A card with a fifth of it
  blown out came to 9% of the frame against an 8% threshold — the guard that
  exists precisely to stop this barely fired.

The corners are known, so the light can be measured on the screen instead of on
the room, which is what both numbers meant in the first place. It matters
beyond exposure: gain is also what amplifies a panel's flicker, and the same
logs show `banding 19.9 (rippling)` and `28.4` at railed gain against `0.5`
when calibration measured it. Rippling fails reads, failed reads trigger
whole-screen searches, and a search costs a second read — so a diluted
brightness measurement shows up at the far end as the scanner being slow.

### Turning the phone's brightness up

One nudge of a phone's brightness slider used to end a shift, and every link in
the chain was individually reasonable.

The loop steers by `brightness`, which is the 90th percentile of the screen.
Past the clipping point that number **stops moving**: measured on the rig's own
test cards it reads 255.0 at 1.25x too bright and still 255.0 at 8x. So the
control could not tell a nudge from an eightfold and answered both with the same
18% step on a six-second beat — **36 seconds of blown-out card after a doubling,
48 after an eightfold**, against an offer that lives 30 to 45 seconds.

Then, with the gain on its floor, it shortened the exposure. The fallback ladder
was a constant in the source, and on a 60Hz panel — the commonest family, and the
one the 16667us default is chosen for — the rung below it is 8333us, half a
dimming cycle. Simulating a rolling shutter over a PWM backlight and scoring it
with the project's own `banding_score`, where 4.0 already means rippling:

|            | 60Hz | 120Hz | 240Hz | 480Hz |
|------------|-----:|------:|------:|------:|
| **8333us** | 128.8|   2.0 |   2.6 |   0.7 |
| **16667us**|   2.2|   1.3 |   1.4 |   0.5 |
| **20000us**|  40.5|  32.0 |   9.7 |   7.8 |
| **25000us**|  53.0|   2.8 |   1.3 |   0.7 |
| **33333us**|   2.5|   0.7 |   0.7 |   0.1 |

And then the trap closed. A rippling screen never settles — against the real
motion gate, 8333us on a 60Hz panel reads **75.2** where the settle threshold is
2.0 — and the exposure control was gated on the picture having settled. So the
branch that would have given the exposure back never ran again. `should_read`
needs the picture to settle too, so nothing was read either. Simulated end to
end on the real loop at twice the brightness: **wedged after 19 seconds, one read
in six minutes**, with the loop still saying "still here" every four seconds and
the live page showing a green dot.

Four changes, and the first is the one that matters:

* **The exposure control is not gated on the picture settling.** It never needed
  to be: a percentile and a count of full-well pixels do not care whether the
  frame is moving. The tracker's settled gate stays where it earns its keep.
* **The fallback ladder is measured, not assumed.** Calibration already scored
  every candidate on the driver's own phone and threw the numbers away into a
  prose sentence; they are kept now as `exposureLadder` in `config.json`, and
  the run loop will only ever step onto a rung that came back quiet. The
  daylight rungs are measured too — they were the ones the rig actually used and
  the only ones nobody had checked. A rig with no measured ladder keeps the old
  guess for the old emergency only, and says so at startup.
* **The cut is sized by search rather than by a constant.** It starts at the
  ordinary 18% and grows while the picture keeps coming back at full well, so a
  nudge costs one beat and an eightfold costs six, on a one-second beat while
  blown — because a blown card is unreadable anyway, so there is no offer being
  disturbed.
* **When there is nothing left to give, it says so.** On a 60Hz phone there is
  no quiet rung below the calibrated one, so the honest answer to a phone
  brighter than the camera can take is to hold the flicker-safe exposure, leave
  the card a little bright, and put *Phone screen too bright for the camera —
  turn its brightness down a notch* on the screen the driver is looking at. That
  is the only remedy that exists, and it belongs to them.

Measured on the same rig, before and after — seconds until the card is off the
rail, and until it is properly exposed again:

|              | 1.25x | 1.5x |  2x |  3x |  4x |  6x |  8x |
|--------------|------:|-----:|----:|----:|----:|----:|----:|
| **before**   |    6s |  12s | 36s | 24s | 42s | 30s | 48s |
| **off the rail** | 1s |  2s |  3s |  4s |  5s |  5s |  6s |
| **back on target** | 1s | 2s | 3s |  4s | 11s |  5s | 12s |

and at 2x and 3x on a 60Hz phone the rig now holds 16667us, keeps reading, and
asks the driver to turn the screen down after two seconds.

Two candidates also left `FLICKER_SAFE`. picamera2 defaults a video
configuration's frame duration to 33333us and an exposure cannot outlast its
frame, so 40000 and 50000 were requested during calibration, silently clamped to
33333, and whichever won was written to `config.json` as "measured against this
screen" naming a number the sensor never used. 33333us is already two whole 60Hz
cycles, and longer exposures buy motion smear on a card read from a moving car.

## When the phone is in dark mode

A phone set to dark mode — and a DoorDash card, which looks the same — breaks
two assumptions at once, in different places, and only one of them is the
obvious one.

**The reader could not read it.** Tesseract is run with
`tessedit_do_invert=0`, which switches off its own white-on-black retry. That
was a sound trade for as long as `preprocess()` handed it dark text on a light
card *every* time, and dark mode falsifies that silently: the reader returned
`Ee y Piece ek te | So | — — ee ee ne ee oo` and the offer was simply never
seen. So `preprocess` decides which way up the ink is and turns the picture over
when it has to, which keeps the promise the engine switch was made on.

Decided from the picture, not from a setting — a phone's theme follows the time
of day and nobody is going to tell the rig. The card is mostly background, so
its median *is* its background, and the question is which end of the card's own
range that sits at. Relative rather than absolute, because inverting a light
card does not degrade the reading, it destroys it, and a badly underexposed
light card is exactly what a fixed `median < 128` gets wrong: over twelve
renderings — both themes, windscreen glare, gain pushed, exposure starved,
half-cards — the relative test got 12 of 12 and the fixed one 11. Letting
tesseract do the flip instead also works and costs a whole second pass over
every dark page, 255ms against 359ms.

It holds its previous answer when a picture is too close to call. Real cards
never waver — all four in the corpus decided the same way over 60 noisy frames
each — but a picture that is genuinely half one thing and half the other flipped
16 times in 60, and the frames either side of a flip get *subtracted from one
another*. Two frames of one still picture judged opposite ways score **200.7**
on `banding_score` against 0.7 for two judged alike, where 4.0 already means
"rippling" — and the exposure is chosen by ranking candidates on exactly that
number, so a single flip during calibration condemns the right exposure and
writes another to `config.json` for the whole shift.

**The detector could not find it**, which is what made this look like a reading
fault rather than a locating one. The brightness search assumes the screen is
the bright object in a dim cabin. A dark-mode screen does not merely break that,
it *straddles* it: the map above the sheet renders around grey 44 and the sheet
itself around 19, so with a car interior anywhere between them no single
threshold can hold both halves of one screen. What came back was not "no
screen", which would at least have been honest — it was **the map**, at the full
width of the phone and 47% of its height, on every check, with the crop then
taken as a fraction of it. The reader was being handed a piece of a map.

So a second search asks how far each pixel is from the *cabin* — measured from
the frame's outer ring, since the card is aimed at the middle — rather than how
bright it is. Neither half of a dark screen looks like upholstery, so that one
holds both. It does not replace the brightness search: it needs the frame's edge
to actually be cabin, which stops being true on a very close mount, and it has
nothing to measure against on a windscreen that fills the frame.

Both run, and where they overlap the taller wins — but only if it is
*materially* taller **and** what it adds has writing on it.

Both halves of that rule were bought the hard way. Height alone cost accuracy on
every ordinary frame, because the difference mask carries a blur halo and
returns a box about 1% bigger than the brightness search's exact one. And height
plus materiality was still wrong, in the other direction: a phone sits in a
case, in a cradle, and a case is as unlike upholstery as a screen is — so the
difference search finds the *handset*, 25% taller than the screen, and won.
Detection went from 240x619 to 306x766 with every crop fraction downstream
measured off plastic. What separates a dark offer sheet from a phone case is not
size, it is that one has writing on it: measured over the disputed region,
eroded away from the seam so the boundary between the two answers is not what
gets measured, a case scores **0.000** whatever colour it or the upholstery is,
and a dark offer sheet scores **0.116 to 0.145**.

Measured over 16 cabin brightnesses × 4 cards, detection is right in 62 of 64.
The two misses are the cabin rendering at the same grey as the card itself — one
level wide, where no threshold can separate them and the behaviour is what it
already was. Reading is right in 16 of 16. Detection costs about 3ms more on the
thumbnail the tracker uses every 0.4s, on top of 9.6ms of which 6.3ms is the
resize that happens either way.

**Known limit:** a phone in a *white* case is detected as the case rather than
the screen. A white case against upholstery is the bright thing in the frame and
the screen is only a few levels above it, so the brightness search returns it —
and did long before any of this. Draw the box yourself if you have one.

## Hardware setup

**Sensor mode — the one setting that can quietly ruin framing.** `rpicam-hello
--list-cameras` on this module reports:

| Mode | Rate | Sensor window | Field of view |
|---|---|---|---|
| 1280×720 | 80fps | 2560×1440 crop | **cropped** |
| 1920×1080 | 60fps | 3840×2160 crop | **cropped** |
| **2328×1748** | **30fps** | full 4656×3496 | **full** — 2×2 binned |
| 3840×2160 | 18fps | 3840×2160 crop | **cropped** |
| 4656×3496 | 9fps | full 4656×3496 | **full** |

The small modes are *windows onto the sensor*, not scaled-down full frames.
Picking 1080p to "go faster" narrows the field of view and can push the phone
partly out of shot. Only 2328×1748 and 4656×3496 see everything, so those are
the only two `calibrate.py --mode` offers, and `scan_pi.py` pins the mode
explicitly rather than letting the size request choose one.

**Tuning files are per pipeline, not interchangeable.** Pi 5 uses `pisp`, Pi 4
and earlier use `vc4`, and a tuning written for one ISP does not describe the
other. The search order follows the machine's own pipeline, and the tuning is
only overridden when the pipeline's own file lacks autofocus and another has it
— otherwise libcamera's own choice stands.

**2328×1748 is the default and the right one.** 30fps is far more than this
needs, and 2×2 binning gives cleaner pixels in a dim car. Go to 4656×3496 only
if calibration says the card is too small — 9fps is still plenty, since offers
do not arrive sixty times a second.

**Framing.** Because 2328×1748 is binned, the card carries half the pixel
density the headline 16MP suggests. Two numbers matter, and they are not the
same: **380px** of card height is where reading measurably stops working, and
**450px** is where there is comfortable margin. Anything between is workable and
the tools say so rather than refusing. Below 380 no later upscaling recovers
detail the mount never caught.

**Camera.** The IMX519 needs its overlay enabled in `/boot/firmware/config.txt`:

```
camera_auto_detect=0
dtoverlay=imx519
```

Recent Raspberry Pi OS ships this overlay; if `libcamera-hello --list-cameras`
does not see the sensor, install Arducam's driver package for the module and
re-check. Reboot after editing.

**Mount.** The whole design assumes the camera cannot move relative to the
phone. Bolt both to the same bracket — not one to the dash and the other to a
vent. Any shift means re-running `calibrate.py`.

Aim for the phone screen filling most of the frame, square-on, at around 25cm
(the default `--lens 4.0` focuses there). Avoid a straight-on reflection of a
side window; a few degrees of tilt kills a specular glare without hurting the
warp.

**Phone.** Turn auto-brightness off and brightness up. Auto-brightness changes
exposure mid-offer, which is exactly what the pinned camera settings are trying
to avoid.

## Focus

The IMX519 has a motorised lens, and left alone it sits wherever it was, which
is usually blurry. Focus is decided once and then pinned, because a fixed mount
has nothing to track and a refocus mid-offer costs more than the read does:

**`rpicam-still --help` listing `--autofocus-mode` proves nothing.** Those flags
are compiled into rpicam-apps for every camera, so the help text reads the same
whether or not your sensor can focus. `python3 rpi/doctor.py` answers it
properly, by reading the tuning files themselves:

```
FAIL  autofocus available   none of 1 tuning file(s) for imx519 contain an AF algorithm
      fix: install Arducam's tuning for this module, then re-run...
      no AF  /usr/share/libcamera/ipa/rpi/vc4/imx519.json
```

If Arducam's tuning ends up somewhere non-standard, point straight at it:
`UBERSCAN_TUNING=/path/to/imx519.json`.

**Autofocus may not exist even though the control does.** libcamera
advertises `AfMode` for this sensor, but Raspberry Pi's stock `imx519.json`
tuning contains no autofocus *algorithm*, so setting it logs

```
WARN IPARPI ipa_base.cpp:797 Could not set AF_MODE - no AF algorithm
```

and the lens never moves — manual `LensPosition` included, since the same
algorithm applies it. The code now reads the tuning file rather than trusting
the control list: it loads an autofocus-capable tuning if one is installed, and
otherwise says so instead of pretending. To get autofocus, install Arducam's
tuning for the module; without it, focus the lens by hand using the sharpness
number in the preview, which works either way.

- `preview.py` runs **continuous autofocus** while you aim (when the tuning
  supports it), and overlays both a sharpness score and the lens position;
- `calibrate.py` runs one autofocus cycle and records that position in
  `config.json`;
- `scan_pi.py` pins the recorded position at startup.

So a blurry feed means either you have not calibrated since moving the mount, or
autofocus never ran. The preview overlay says which: it prints `focus NNN` and
marks the frame `BLURRY` below the usable threshold. A sharp card scores in the
hundreds; a visibly soft one scores under twenty.

`--lens 4.0` on either script pins focus manually instead, in dioptres — 4.0 is
25cm, 3.0 is 33cm, 2.0 is 50cm.

## Aim the camera

A CSI camera is invisible to browsers, so `scan.html` will never show this feed —
open it in Chromium on the Pi and you get `NotFoundError`, because there is no
V4L2 webcam to find. Use this instead:

```sh
python3 rpi/preview.py        # then open http://<pi>:8081/ on the phone
```

It streams the frame with the detected phone screen outlined and the number that
decides whether any of this works: how many real sensor pixels tall the offer
card is. Green means the mount is close enough, red means no amount of tuning
later will save it. Move the bracket until it goes green, then calibrate.

`--save shot.png` writes one annotated frame instead of serving, and
`--image f.png` runs the same overlay on a still, which is how it is tested
off-Pi.

### Landscape is the breakpoint, not 620 pixels

The across-the-screen layout used to be behind
`(orientation: landscape) and (max-height: 620px)`, and the height term was a
mistake that took a while to surface. It was written when the only landscape
targets were an 800x480 touchscreen and a 1024x600 HDMI panel; every larger one
silently missed it. A **1280x800 panel — a tablet on its side, which is what
this rig ended up bolted to — is landscape and 800px tall, so it missed by 180
pixels and got the phone design**. Measured there: a 460px column down the
middle of a 1280px screen, the readout stacked above the picture instead of
beside it, the verdict pushed **221px off the top of the glass**, and the page
819px tall in 800px of screen.

One thing that widening it broke, and which the same suite then caught: the
across-the-screen layout deliberately lifts the shared `max-width: 480px` so
the charts and the log rows can use the panel, and the log page had never met a
desktop-sized window before. Body text ran **1892px wide on a 1920 screen** —
around two hundred characters a line — and 1252px on the 1280 panel. The bars
keep the width, because a bar is read by length rather than by reading along
it; the sentences are capped at 72 characters and the page at 1180px.

It is bare `(orientation: landscape)` now. That says exactly what it means —
this screen is wider than it is tall, so lay the page out across it — and there
is no size of landscape screen for which the answer is different. The
`max-height: 380px` block stays as an extra squeeze inside it for the 3.5"
hat. `rpi/test_layout.py` renders every page at 1280x800 and 1024x768 as well
as the small panels, and holds every stylesheet to the same two conditions.

The verdict also takes the height of the column it is in rather than only the
height of its own words, on the driving screen as well as the keypad — at
1280x800 it was 352px of a 788px column with the rest black, which is the
complaint that started all of this, one screen along.

### The screen bolted to the dashboard

Every layout in this project assumes a phone: tall, narrow, held about 30cm from
the eye. The rig's own panel is the opposite — wide, short, and sitting where a
driver can reach it without leaning, call it 60cm. So `live.html` turns itself
into two columns on a landscape screen under 620px tall: the verdict beside the
camera view, with the connection line and the controls across the bottom.

It had never once done that. `#viewWrap` carried `grid-column: 2` but was nested
one level inside `.live`, and a grid places its own children and nobody else's —
so the property applied to nothing. Rendered at 800x480 and measured: two columns
of 431px and 345px, the verdict drawn at 431px instead of 784px, the camera view
stacked underneath it in the same column, **43% of the glass black**, and the page
768px tall in 480px of screen so the bar of controls fell off the bottom.

It survived because it is invisible without a camera. With no frame the
`:has(.gone)` rule collapses the grid to one column and the page looks right,
which is the state every development machine is in. There is a structural check
for it now, in `test_liveview.py`: every id the dashboard block gives a
`grid-column` to has to be a direct child of the grid that places it.

A 1024x600 panel — the common 7" HDMI one — missed the breakpoint by 40px and got
the phone layout instead: a 480px column down the middle of a 1024px screen, and
the headline rate scrolled off the top. The breakpoint is 620px now, in both
files, and the two files are checked to agree, because half a page in one design
and half in the other is worse than either.

The type was the other half of the complaint. Same pixel density as a phone at
twice the distance means every letter subtends half the angle, and the small
things were all literal pixel values that the breakpoint could not reach —
11px on the labels under the figures, 12.5px on the working line, 13px on the
four buttons. They are 15-17px on a dashboard panel now, and the headline rate is
sized against the panel's height as well as its width, so a 1024x600 screen
spends its extra room on the one number it exists for: 92px before, 140px now.

### The other three pages

`live.html` was the one that got measured; the other three were not, and every
fault above had a twin somewhere else. Each of the four is now rendered at
800x480, 1024x600, 480x320 and on a phone, and what comes out is checked rather
than looked at — `test_layout.py`.

**The keypad wasted half the panel.** Its verdict already spanned the full
height of the left-hand column and declined it: 175px of card in a 468px column,
so 40% of an 800x480 screen was flat black and 45% of a 1024x600 one. The
headline rate is what that height is for. It is 88px now instead of 60, and the
row of controls runs the width of the screen instead of the right-hand third —
which was the only way five labels fit in it without wrapping or being cut off
mid-word.

**...and scrolled sideways on a phone.** `grid-auto-columns: 1fr` is
`minmax(auto, 1fr)`, and that `auto` floor is the longest word in the button.
Five of them — Targets, History, Offers, Live, Camera — floored the row at 408px
on a 390px screen, so the whole page laid out 408px wide. A page that scrolls
down is a nuisance; a page that scrolls sideways is one where the controls are
off the edge of the glass. On a 3.5" panel the same bar wrapped to three rows
and pushed the page 445px into 320px of screen.

**The scanner drew its controls on top of its own status line.** `.scanbar`
declared five columns for six buttons. The sixth flowed onto an implicit second
row, and that row lands exactly where `#statusline` sits — so the one line that
says *why* nothing is being read ("loading reader…", "searching…", "read
failed") was printed underneath a button at every size this rig ships on. It is
`grid-auto-flow: column` now, which cannot go out of step with the markup, and
the layers are checked for overlap rather than counted by hand. Its buttons also
never had the 44px floor the rest of the project defends: they were 43px on a
phone and 37px on a panel.

**A message and a state shared a class name, again.** `scan.css` declared a bare
`.warn` for the notice box inside the verdict. Nothing on any page carries
`class="warn"` — the box is `class="notice"` — so the only element that rule
ever matched was `.verdict.warn`, the CLOSE CALL panel itself, which came out a
different shape from the other three verdicts. `styles.css` documents this exact
trap a few lines above its own `.notice`.

**And the font was never the one anybody thought.** The stack led with
`-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto`, none of which exists on
Raspberry Pi OS. Measured in the rig's own browser by drawing the same string in
each family: all four came back identical to a family that was never installed,
so the whole stack fell through to `system-ui`, which there is DejaVu Sans — the
widest face on the machine. The same sentence measures 339px in it against 300px
in Liberation Sans and 268px in the browser's own default, and every width in
the file was budgeted against a phone's narrower face. That is most of why
labels that sit on one line on the phone wrap on the panel. `Piboto` — Raspberry
Pi OS's own UI font — and `Noto Sans` are named ahead of the generic now. A
phone never sees them; the four names above still win there.

The offer log got the same treatment as the live view had: it was rendering at
9.5, 10 and 11 pixels — the day headers, the time each offer came in, the rate
before costs, the count beside every bar, and the sentence explaining why a row
was set aside. Those sizes live in that page's own `<style>` block, which loads
after the shared stylesheet and so beat anything set for them there.

### Starting with the Pi

`rpi/install-service.sh` writes a systemd unit. Two things were wrong with it
for as long as it existed, and neither could have been noticed by running
anything.

It started `scan_pi.py`, which is the scanner and nothing else: it reads
`rpi/config.json` and begins. On a rig that has never been calibrated there is
no config, so it exits at once — and the unit restarts on failure, so the
result was a service respawning every five seconds forever behind a blank live
view. The script printed a warning about that instead of avoiding it.
Everything else in the project goes through `autopilot.py`, which checks the
camera, serves the aiming preview until the mount is good, calibrates the
moment the frame holds steady, and then `exec`s the scanner in its own place so
there is still one process for systemd to stop. It runs that now.

And `StartLimitIntervalSec=0` sat in `[Service]`. systemd moved it to `[Unit]`
in v230 and does not error on the old placement: it logs `Unknown key name` and
carries on with the default, so the line meant to stop the unit giving up was
being silently dropped. Five starts inside ten seconds and it would have
stopped trying for good — on the one machine with nobody watching it.

`rpi/test_service.py` runs the installer against a temporary root with `id` and
`systemctl` shadowed, and reads back what it wrote: which script is started,
that the script exists, which section each key landed in, and that the paths
are baked in from wherever the script was run.

### Dark, but not flat

The palette is dark on purpose: this is looked at through a windscreen at
night, and a light panel in a dark car is a lamp pointed at the driver. What
was wrong was never the darkness — it was the *steps* between the darks.

Measured as WCAG computes it, against the background:

| | before | now |
|---|---|---|
| a card or a key, as a shape | **1.11:1** | 1.55:1 |
| its border, against the card | **1.31:1** | 2.3:1 |
| the labels under every figure | 7.27:1 | 8.94:1 |
| the word ACCEPT, on its green | **3.55:1** | 4.34:1 |
| the words CLOSE CALL, on amber | **4.30:1** | 4.67:1 |

1.11:1 means the boxes were not boxes. Every key on the pad, every card in the
log and every button in the bottom bar was filled with a colour a ninth of a
step from the page behind it, and turned up in daylight they washed into one
flat rectangle. The background is untouched; everything drawn on top of it
moved up.

Green saturates before it reaches 4.5:1 against the green it sits on — there is
no lighter green that is still green, and darkening the panel would break the
brightest-to-darkest ladder that carries the verdict for a driver who cannot
separate red from green. So the label is instead never drawn below 18px bold,
which is where the standard asks 3:1 rather than 4.5:1, and 4.34 clears that
with room. Amber had headroom and took it.

None of this is eyeballed: `rpi/test_layout.py` computes every ratio from
`styles.css` and fails below the floor, and checks the four verdict panels
still run brightest to darkest.

### A dim phone was being treated as an empty mount

The complaint was "some conditions make the video feed very dim". The cause is
one word in a conditional.

`LIT_ENOUGH` is a brightness below which the window probably holds no lit
screen — the dark inside of a car rather than a phone. Its own comment says it
is "used only as a backstop for when nothing is tracking the screen, since a
caller that knows the phone is missing says so outright". The code did not do
that. The branch read `has_screen and bright >= LIT_ENOUGH`, so a tracker
locked onto a phone still lost the argument to a constant, and any screen
reading under 20 took the empty-mount path: lengthen to the longest exposure,
then stop.

Measured, on a screen reading 4: the gain sat at its starting 1.5 for ever,
with **5.3x of headroom untouched**, and the picture stayed dark. The claim in
that comment — "a phone at its dimmest still reads several times this" — is
contradicted twenty lines further down the same file, which records a real
night-time card reading **6**.

`has_screen` has three answers now rather than two. `True` and `False` are the
tracker's and are believed; `None` is a caller that cannot know — `--no-track`,
or nothing following the corners yet — and only then does brightness speak for
itself. Measured on the same dim screen, the gain now climbs 1.5 → 3 → 6 → 8 in
three beats, and the published picture goes from a mean of 20.7 to 114.9.

**And it says when it has run out.** `stuck` was only ever set off the short
end: gain on its floor, no shorter rung, "turn the phone brightness down".
Railed the other way — gain on its ceiling, already on the longest rung, screen
still under target — nothing was reported at all. There is a `too_dim` now, on
the health line and on the live page, saying to turn the phone up or move the
mount out of the shade.

**What is deliberately not done.** The picture is not tone-mapped for the eye.
It would be free and it would look better, and it would also make a rig that
has run out of light *look* fine — which is exactly what the notice above
exists to prevent. The exposure is the truth about the exposure.

**The limit that remains.** With the tracker lost, the gain is still held:
raising it against dark upholstery is what once wound the rig to its ceiling
chasing a card that was not there, and took a minute to climb down from just as
the driver picked the phone up. The exposure is still given back in that state
— measured, 2083us to 16667us, an eightfold recovery — so a rig that shortened
itself into a hole climbs out of it. A phone so dim that the detector cannot
find it even then stays dim until "⟳ Re-find" or a brighter screen.

### Reading the phone *through* the live view

The live view was written to answer one question — is the camera pointed at the
right thing? — and everything about it follows from that. The whole scene,
shrunk to 480px, the corners drawn on in green, quality 60, and between reads
it is made from the 640x480 luma preview rather than the sensor, because copying
twelve megabytes to make a thumbnail was most of what the picture cost.

There is a second way this rig gets used, and it needs the opposite picture. The
phone sits in the mount pointing at the camera, where it cannot be read or
reached; pair a bluetooth mouse to it and the rig's own display becomes the only
sight of the phone there is. Then the offer card has to be legible in this
picture, and so does whichever button the pointer is over.

The scene view cannot be that picture at any size. Measured against a synthetic
rig frame with the phone in a realistic mount position: the phone lands in
**123x206** of those 480 pixels. Enlarging the `<img>` enlarges those 206 rows.
The information is not in the file.

So `⛶ Phone` publishes a different picture rather than a bigger one — the same
perspective warp the reader uses, from the sensor frame, filling the frame at
1000px tall:

| | scene | phone |
|---|---|---|
| the phone, in the file | 123 x 206 | 573 x 1000 |
| the phone, on an 800x480 panel | 88 x 148 | 269 x 468 |
| file size | 8.7 kB | 23.5 kB |
| compose | 1.8 ms warp + 0.8 ms encode | 1.8 ms warp + 3.2 ms encode |

Three times the linear size on the glass and five times the linear detail behind
it. Not the OCR image, which is contrast-stretched, thresholded and sometimes
inverted — a picture of a page rather than of a screen — and not cropped to the
reading box either, because that box is deliberately the part of the screen a
*price* lives in and the Accept button is outside it on every card shape here.
A view you cannot see the button in is not one you can drive the phone from.

**It is what the page opens on.** Aiming the mount is something you do once, at
the start of a shift or after a bump; reading the phone through the panel is
what the rest of the shift consists of. Landing in the scene view meant the
driver pressed a button to get to the useful picture every time the page
reloaded, and the choice is remembered anyway, so the default was costing a
press to reach the view they had already chosen. `⛶ Scene` is the way back and
it is one press, same as before.

**And the picture is now whole.** `#viewWrap img { max-height: 100% }` was
resolving against a wrapper that took the height of its contents rather than
the height of the row, so the percentage had nothing to measure against and was
ignored. The phone drew 612px tall in a 468px row and `overflow: hidden` took
the difference off both ends — **109px off the top**, which on an offer card is
where the payout is, and 23px off the bottom. It got worse on bigger panels:
137px off the top at 1024x600, 138px at 1280x800. Stretching the wrapper to its
row gives the percentage a number to resolve against, and the phone is centred
in it whole at every panel size the suite measures.

**How big it can get, which is a question with an arithmetic answer.** A phone
is portrait and this panel is landscape, so the picture is bound by *height*:
468 of the 800x480 panel's 480 rows, everything else being the 6px page margins.
Given that height the phone's own shape fixes the width — 269px for the quad
these numbers came from, narrower for a taller phone — and no arrangement of
columns changes it. Splitting the panel 50/50 was tried and measured: the phone
came out the same 269x468, the rest of its 400px column went black, and the
other half paid for it — the address under the figures sliced to 11px of its
17px line, the age line wrapped onto two, and the five controls went from 559px
of bar to 388px, close enough that `▣ Set box` and `⟳ Re-find` touch. So the
picture's column is sized to the picture and the rest of the panel goes to the
verdict and the controls. The one lever that makes the phone bigger is
`▣ Set box`: a tighter quad is a bigger warp of less phone.

**What it costs.** The sensor frame, which is the copy the scene view exists to
avoid. Composing is actually cheaper than the scene view — that one's expense
was never the shrink but the card inset warped out of the sensor — so the price
is the 12MB copy, and it is the one thing here much dearer on a Pi than on the
machine these numbers came from.

Fifteen frames a second, not the scene view's thirty. This picture is
watched to read a card that is not moving and, increasingly, to see where a
mouse pointer is: the phone is worked with a bluetooth mouse and this is where
the cursor is watched, and a cursor below about ten frames a second stops
feeling attached to the hand. The right number is a property of the machine
rather than of the code, so it is a flag:

```sh
python3 rpi/autopilot.py --screen-fps 20   # raise it until reads slow down
python3 rpi/autopilot.py --screen-fps 6    # or drop it on a busy rig
```

Clamped to 2-30 rather than refused: the failure modes at the ends are a slide
show and a Pi composing frames between camera frames, and neither is worth
stopping a shift over. The sensor delivers 30 a second in the default mode, so
above that it would be paying for duplicates.

**Only while somebody is looking at it.** The web side already touches
`rpi/.viewing` whenever a browser fetches a frame, and that file now carries
which view was asked for — a query parameter on `/api/frame.jpg` and
`/api/frame.mjpeg`, because an `<img>` cannot set a header. In the file rather
than in an endpoint of its own so the two facts expire together: a mode set by
its own call would outlive the tab that set it, and the scanner would go on
buying sensor frames for nobody. An unknown word, an empty file or an older
server all mean the scene.

It is written through a rename. Once the file had contents worth reading it also
had a window in which it had none, and the scanner reads it on its own clock up
to thirty times a second; catching the truncate makes it see an empty file,
read that — correctly — as "the scene", and cache it against an mtime that may
not move again for a second.

**Where it falls back.** No corners, or corners that have wandered off the
frame, and the scene comes back instead. That is the useful answer rather than
the tidy one: the scene view is the picture that shows *why* there is no phone
view — the phone out of frame, the mount knocked, the outline sitting on a
reflection — and it is the one a driver fixes that from.

`▣ Set box` switches back to the scene on its own. A box dragged on the picture
is sent as a fraction of the camera frame, and the phone view is not the camera
frame; the same drag would land somewhere else entirely and the failure would be
silent — a box accepted, the quad moved, and the scanner reading a patch of car
door. There is nothing lost by switching, since you cannot draw the phone's
outline on a picture already cropped to it.

### Reading the live view

| | |
|---|---|
| **Green outline** | where the corners are *now* — calibration as the tracker has since moved it, not as it was written down. If it is not hugging the phone's screen, see below, or draw it yourself with ▣ Set box. |
| **White inset** | the exact image handed to the reader: de-skewed, cropped to the card, contrast boosted. Literally the reader's own last picture rather than a re-creation of it, so it can lag the outline by a read. If the pay, minutes and miles are legible there, the reader has everything it needs. |

The view refreshes at **the camera's own rate — thirty a second — while the page
is open**, and the phone view at fifteen. That got cheaper before it got faster:
a snapshot used to copy a 12MB frame, draw the outline on it at full size,
shrink it with an area filter and then warp a second copy of a card the reader
had already made. It now shrinks once with a linear filter, draws on the small
picture and reuses the reader's card — about a quarter of the work, so four
times the frame rate still costs less than the old rate did.

### The rate you ask for is not the rate you get

Composing a frame costs 5.5ms here — 1.10ms to copy, 1.16ms to warp, 3.20ms to
encode — which is a ceiling of 183 a second, and the server delivered 58.7
distinct parts a second when fed by a 60fps writer. Neither of those was the
limit. The limit was the *schedule*.

The snapshot is due-checked once per camera frame and nowhere else, so the only
rates this loop can produce are the camera's divided by whole numbers: 30, 15,
10, 7.5 on the binned sensor. The check was a strict `elapsed > period`, which
always lands on the next one **down** — the frame arriving exactly on the
deadline is a hair early, gets skipped, and its successor is a whole camera
frame late. Simulated against a 30fps sensor:

| asked for | delivered, strict `>` | delivered, nearest frame |
|---|---|---|
| 10 | 7.8 | 10.1 |
| 15 | 10.6 | 15.1 |
| 18 | 15.1 | 15.1 |
| 20 | 15.1 | 16.5 |
| 24 | 15.1 | 30.1 |
| 25 | 15.1 | 30.1 |
| 30 | 16.5 | 30.1 |

So `--screen-fps` was close to meaningless above 15 — 18, 20, 24 and 25 all
delivered the same 15.1 — and the scene view's own default was a third short of
its label. `snapshot_due()` now allows half a camera frame of slack, which takes
whichever frame is *nearest* the deadline rather than the first one past it: an
unachievable rate rounds to the closest achievable one instead of always
downward, and an achievable one is actually achieved.

The slack is measured, not assumed. The loop keeps a smoothed gap between camera
frames, ignoring anything over a second as a stall rather than a rate, so this
stays right on a rig running the 9fps full-sensor mode or the 60fps cropped one.
Before two frames have been seen there is no measurement and the slack is zero,
which costs the first frame of a session and nothing else.

The rows that still do not land on their label — 18 and 20 arriving at 15.1 and
16.5 — are
the honest answer rather than a remaining bug. There is no way to publish 20
frames a second from a sensor delivering 30 without publishing some of them
twice, and a duplicate frame is a wasted encode and a wasted 8.7kB. The number
to reach for on this sensor is 30, 15, 10 or 7.5; anything else is a request to
be rounded.

It does not live on the SD card. The view refreshes up to thirty times a second
while someone is watching, at ~50kB a frame — roughly **5GB an hour written to
the card**, against about 19MB a *year* for the journal. Every byte
of it is stale two frames later and none of it needs to survive a reboot, so it
goes to `/dev/shm`, which is RAM. `pipeline.py` has staged its OCR images there
all along for exactly this reason; the live frame simply never got the same
treatment, and it was writing fifty thousand times more to the one part of the
system that wears out than the data worth keeping does.

The two sides pick that path independently — this is Python and the web side is
JavaScript — and nothing detects a mismatch, so the server takes whichever
candidate is *freshest* rather than whichever exists. That keeps the view
working whichever the scanner chose, including a rig running an old scanner
against a new server. `FRAME=/some/path.jpg` overrides it, the way `JOURNAL`
does for the offers.

It is also composed from the *preview* stream rather than the sensor. A preview
is a 480px thumbnail of a car interior with a box on it, and making one used to
mean copying twelve megabytes of sensor frame and discarding 99% of it — 8ms of
pure memory traffic, at up to fourteen frames a second. The sensor frame is now
copied only when something is going to *read* it. The reader still gets full
resolution; the only thing lost is colour in a picture nobody reads colour from.

The view is deliberately smaller than what the scanner reads: 480px at quality
60, about 50kB a frame against 136kB at the old 640/80. What limits it is bytes
over the car's wifi, not pixels on the Pi — composing and encoding one costs a
few milliseconds either way. The page also asks for the next frame only once the
last has arrived, so a weak signal makes it slow rather than making it lag
further behind the longer you watch. None of this touches the read: that is
warped from the full sensor frame and never goes near this path.

**A green outline that ends up too small** was possible, and it was worse than
it looked. Three things had to be true at once, and all three were.

**The size test was relative.** It compared a candidate against the corners as
they stood, not against the calibration — so every step was "the same size as
the last one", every step looked reasonable, and the outline walked downhill.
Six candidates each 80% of the one before left it at 63% of the calibrated
screen. Adding the check to the drift path did not fix this: `ease_toward` has
no floor either, it just converges over a few more checks, and a drift-only
collapse emits no `corners re-locked` line at all — so a log's re-lock count is
a lower bound on how far things moved.

**Then the trap closed.** At 63%, the real phone is 1.57× the shrunken box —
outside the band the *other* way. The one thing the tracker exists to find
became the one thing it could no longer accept, with the detector handing it
corners that were exactly right and both gates refusing them. Not "for a
while": a rig sat like that for 1500 checks, twelve and a half minutes, with
the phone plainly in frame, and moved zero pixels.

**And the band was not self-inverse.** `1/0.78` is 1.2821 and the upper bound
was a rounded 1.28, so there was a sliver where A could adopt B and B could
never adopt A back. Measured: a quad at 0.780 of the screen recovers; one at
0.778 never does.

**The size test could not see shape at all.** `span` is the mean of the
diagonals, and a diagonal is one number about a rectangle that needs two. A
1340×230 strip — the Accept button and the dark beneath it — scores 0.82
against a 695×1512 phone and sails through a function called `same_size`. That
is the outline in the photograph, with a readable `$16.05` sitting above it.

So there is one gate now, `looks_like_the_screen`, and it is **absolute** —
measured against the calibration, which never moves, because the phone does not
change size and the mount is fixed — and it checks **shape as well as scale**.
The band is `(0.78, 1/0.78)` so it answers the same question both ways round.

That gate is strong enough to pay for the recovery being quick. A phone put
back used to need twice the agreement of any other move: 4.2s measured, of
which 93% was the counting, and nearer 10s on a Pi because a read in flight
stops the loop honouring the 0.4s recheck at all. It is the same bar as
everything else now:

| | before | after |
|---|---|---|
| phone removed, an Accept-shaped strip in frame | adopted it | refused, corners hold |
| phone put back | 4.2s (≈10s on a Pi), or never | **instant** |
| mount genuinely knocked 150px | 4.2s | **2.4s** |
| a nudge of a few px | instant | instant |
| a hand across the frame for 2.4s | ignored | ignored |

One more thing was hiding this. `status()['drift']` is measured against the
last *save*, and `mark_saved` re-baselines it — so a rig 826px off the phone
reported `corners held, drift 0px from saved` on every health line, forever.
The health line now leads with `wander`, the distance from the calibration this
run started at, which is never re-baselined and can still see the problem after
the file has caught up with it.

**If the green outline covers the whole view, it has not found your phone.** The
screen is located by splitting the frame into light and dark, which needs some
darker surround to split against — fill the frame edge to edge and the brightest
region *is* the picture. That used to calibrate happily on a frame-shaped
"screen", which makes the card region an arbitrary strip of the room and
explains a scan area that looks far too narrow. It is now rejected, and the
overlay says `frame is all screen — back off so a dark border surrounds the
phone`.

Get as close as you like, but leave a margin of something darker down at least
two opposite sides. On a good mount that is the left and right — the phone runs
off the top and bottom, and those edges are the map you wanted rid of.

**When no amount of aiming helps, draw the box.** ▣ Set box on `/live.html`
takes the detector out of it entirely: what you drag is what gets read. See
[Draw the box yourself](#draw-the-box-yourself).

The view drops to a frame every three seconds when nothing is watching, because
a live picture is only worth CPU while someone is looking at it. That rate is
the *preview*; verdicts
are not on a timer at all — a read fires as soon as the picture changes.

**While scanning, the view moves to the app.** The aiming preview only runs
during setup, since the scanner needs the camera for itself afterwards. From
then on `/live.html` shows the same picture: the whole frame with the
calibrated corners drawn on it, and inset, the exact card image handed to the
reader. Aim problems show up in the first, focus and glare in the second. It is
written every couple of seconds even when nothing is happening, so a blank
stretch between offers still proves the camera is alive.

### How fast the live view actually is

The picture on the rig's own screen is what a driver watches to decide whether
to press Accept, so the lag between the phone changing and the panel showing it
is the whole quality of it. Measured end to end through the real page, against a
writer producing 30 frames a second:

| | distinct frames/s | http requests in 5s |
|---|---|---|
| before — polling a still, 60ms floor | **13.7** | 216 |
| polling, 30ms floor | 25.6 | 162 |
| **streaming (`/api/frame.mjpeg`)** | **28.4** | **1** |

Two ceilings had to move. The scanner was composing a view 14 times a second, so
the page could not show more than that however often it asked; it is 25 now.
Composing and encoding one 480px view costs about 2.2ms on a development machine
against synthetic noise — the worst case a JPEG encoder ever sees — so call it
10ms on a Pi 4 with a real frame, a quarter of one of four cores, and only while
somebody is looking.

The other was the page, which fetched a whole still over HTTP, waited, waited a
further 60ms and fetched again — a request, a file read, a response and a decode
for every frame whether or not the picture had changed. The server now holds one
connection open and writes a part only when the frame on disk is genuinely new.

**A viewer on the far end of the car's wifi cannot carry 30 frames a second of
50kB each, and does not have to.** The stream respects back-pressure, so a slow
link receives fewer frames rather than falling further behind the longer it
watches. The rig's own screen is a loopback socket and gets all of them.

Polling is kept as the fallback. A stream is one more thing that can fail — a
proxy that buffers it, a browser that will not render it — and a still that
arrives slowly beats a picture that never appears; the page switches over on its
own after four seconds without a frame.

## Calibrate

Put a live offer — or any bright screen — on the phone, then:

```sh
python3 rpi/calibrate.py
```

It finds the screen automatically, writes `rpi/config.json`, saves
`rpi/config-preview.png`, and reports the card's height in sensor pixels. It
also **runs one real read against that frame and tells you what it got**:

```
read from this frame: $7.09, 34.0 min, 3.6 mi — the calibration works
```

which is a different claim from "wrote config.json", and the one worth having
before driving off. The preview is that read's own picture rather than a
rebuild of it, so it is literally what tesseract was handed. It should be a
straight-on, sharp, glare-free card.

If the detector locked onto something brighter than the phone, pass corners
by hand:

```sh
python3 rpi/calibrate.py --corners 135,229,830,134,838,1979,70,1874
```

Targets live in the same file — edit `settings` for your `target`, `costPerMile`,
`pad` and `secondsPerItem`.

## Draw the box yourself

The detector is right almost always and useless in the cases where it is not: a
windscreen reflection brighter than the phone, a second lit screen, a phone with
nothing darker around it to be told apart from. None of those can be aimed out
of. The rig reads a strip of the car indefinitely, reports `corners held` while
it does, and the fix used to be ssh and eight pixel coordinates guessed off a
photograph — which is not a fix anyone makes at the roadside.

So say where the card is instead. On **`/live.html`**, press **▣ Set box**, drag
a box around the offer card in the camera view, and press **✓ Read this box**.
The green outline moves onto it within a second or two, which is the
confirmation worth having.

It works during aiming as well as while scanning, and that is the point: when
the detector never finds the phone, the aiming phase is the one that never ends,
so a box drawn there is what gets the rig calibrated and scanning at all.

Three things change together, and they only make sense together:

- the corners become the box you drew;
- **`cropBox` is pinned to all of it** — the automatic path derives a crop
  *inside* the quad, because it knows the quad is a whole phone screen and cards
  differ in height. Nothing knows that about a hand-drawn box, and a derived
  crop would take 15% off the top, which is where the payout is;
- **corner tracking goes off**, and `config.json` records `manualBox: true` so it
  stays off across restarts. A tracker judges candidates against a calibrated
  *screen*; left on, it would refuse everything or, once its stall watchdog
  fired, move the box back onto whatever it believes the screen is. Undoing the
  override is the one thing an override must not do.

**⟳ Re-find is the way back.** With a hand-drawn box in force it looks for the
screen on the next frame and, if it finds one, makes that the calibration and
turns tracking back on. If it finds nothing it says so and keeps your box —
throwing it away first would leave the rig reading corners nobody has checked,
which is the state you drew the box to escape.

Same thing from the command line, for a rig you are already ssh'd into — as
fractions of the frame, `x,y,w,h`:

```sh
python3 rpi/calibrate.py --box 0.1,0.35,0.8,0.3
```

Fractions rather than pixels throughout, deliberately. What you drew on is a
480px JPEG of a 2328px sensor frame, and corners measured against one size and
read against another are refused on every check, forever, while the health line
goes on saying the corners are held — see the note under **Calibrate** about a
still of the wrong size.

Four keys in `config.json` are about where to look, and they mean different
things.

- **`quad`** is the calibration — the corners as found when you calibrated.
  Only calibration writes it, and the corner tracker judges every candidate
  against it.
- **`trackedQuad`** is where the tracking has got to. Written while scanning so
  the next run resumes without re-converging; ignored by `--no-track`.
- **`cropBox`** pins the crop. Normally absent, and then the crop is placed per
  read from the measured geometry. `calibrate.py --full-screen` writes one, and
  you can put a `[x, y, w, h]` box there by hand — the escape hatch if the
  automatic placement ever misbehaves on a mount nobody anticipated.
- **`manualBox`** says a person drew the corners. Written by ▣ Set box and by
  `calibrate.py --box`, and it turns corner tracking off for as long as it is
  there. ⟳ Re-find removes it, along with the `cropBox` pin that came with it.

Four more are about light, and only the first two are settings a person would
ever edit.

- **`exposureTime`** is the exposure calibration elected, in microseconds — the
  one it measured this phone does not ripple at. `--exposure` overrides it.
- **`analogueGain`** is where the last run left the gain, so a restart begins
  near the light it was last in rather than at a guess.
- **`exposureWhy`** is what every candidate scored, in prose, for a person
  reading the file.
- **`exposureLadder`** is the same measurement for the program: the rungs that
  came back quiet on this screen, and the only ones a bright phone may push the
  exposure down onto. Absent on a config written before this existed, and the
  scanner then says so at startup and keeps its old guess for the one emergency
  it was always used for. Re-run calibration to measure them.

A pin lives under its own key rather than under `roi` deliberately. Every
`config.json` written before the crop became derived carries an `roi`, and
honouring an inherited one would silently disable the placement — including,
for the oldest files, restoring the tight `[0.02, 0.48, 0.96, 0.50]` box that
lost the payout on 13 of 42 test cards. A stale `roi` key is now ignored.

### The headline is a *net* rate

`costPerMile` defaults to **$0.30** here, and it comes off the top. That makes
the number on screen a rate after vehicle running costs, not the one you get by
dividing pay by time:

| | Live11 | Live12 |
|---|---|---|
| pay, minutes, miles | $7.09, 34, 3.6 | $16.05, 23, 8.4 |
| gross — pay ÷ time | $12.51/hr | $41.87/hr |
| less miles × $0.30 | −$1.08 | −$2.52 |
| **shown** | **$10.61/hr** | **$35.30/hr** |

The arithmetic was always right and always tested. What was missing was any way
to tell: the page showed `$10.6/hr` with a `PAY $7.09` beside it, and the two
do not reconcile without knowing about a deduction nothing mentioned. A driver
checking the number by hand concludes the scanner cannot divide.

So the page now says which it is. With a cost set the headline reads `/hr net`,
the pay figure becomes **net pay** ($6.01, not $7.09), and the caption spells
the deduction out: `$7.09 less 3.6 mi × $0.30 = $1.08`. Set `costPerMile` to
`0` and it reads `/hr`, `pay`, and no caption — the gross number, matching what
you would work out yourself.

Worth knowing: the browser scanner (`ui.js`) defaults this to **0** while the
Pi defaults it to **0.30**, so the two show different numbers for the same
offer. Both now label themselves, but pick one and set it in both if you use
both.

### Both rates, on every screen that shows one

Labelling the headline is not the same as showing the other number, and for a
long time only two of six surfaces showed it at all. The raw rate lived in
live.html's working block and in the offers page; the browser scanner, the
keypad and the rig's own OpenCV panel printed a net figure under a plain `/hr`
and nothing else. So a driver reading $14.7/hr off the dashboard, typing the
same offer into the keypad and getting $21.0, had two screens disagreeing with
nothing on either saying why.

Now every one of them prints the raw figure beside the net one, small, in the
same words — `$21.0 raw` — and **only where the two actually differ**. Where no
mileage came off they are one number, and printing it twice beside itself is
noise next to the one figure that decides an offer.

The dashboard's working block had three separate ways to lose that figure, and
none of them looked like a value the page had failed to work out:

| | |
|---|---|
| a notice was showing | The `:has(#warn)` rule hid the whole block to buy back height. One of the notices is "distance unreadable", a stored property of the merged reading that never clears — so on **52 of one shift's 121 offers** the raw rate was not slow to arrive, it never arrived. Those are the same rows where no mileage came off, so the block had no net line either and rendered nothing at all. It now takes the height from the net line, which is the headline in small type. |
| a short landscape screen | `.working { display: none }` below 380px tall — a phone held sideways to check the rig. It now keeps the raw line and drops the pay-and-time half of it, which is a check against the card rather than a figure. At 480×320 that reads `$21.0/hr raw` on one line. |
| a delivery card | The row divided by the card's *stated* duration, and a delivery card states a deadline instead — so the whole DoorDash half of a shift printed `$8.04 in -- min = $21.0/hr raw`, a sum with nothing under the line. It now falls back to `cardMinutes`, the same fallback the figures below it already used. |

`test_dashboard.py` drives the real page with the real messages at three panel
sizes and asserts the raw row is on the glass, carries a figure, says which
figure it is, and contains no dash. `test_keypad.py` and `test_scanjs.py` hold
the other two surfaces to the same rule in both directions — shown when the
numbers differ, absent when they do not.

### Picking a number

$0.30 is a petrol midsize with some depreciation in it. Built up from parts,
for rideshare miles (tyres wear faster than the brochure says):

| | energy/fuel | tyres | service | depreciation | total |
|---|---|---|---|---|---|
| **Model 3**, home charging | $0.037 | $0.033 | $0.015 | — | **$0.09** |
| **Model 3**, supercharging | $0.090 | $0.033 | $0.015 | — | **$0.14** |
| **Model 3** + depreciation | $0.037 | $0.033 | $0.015 | $0.10 | **$0.19** |
| petrol midsize, 30mpg @ $3.50 | $0.117 | $0.018 | $0.050 | — | **$0.18** |
| petrol midsize + depreciation | $0.117 | $0.018 | $0.050 | $0.10 | **$0.28** |

Energy assumes 250 Wh/mi including charging losses, home at $0.15/kWh and
Supercharger at $0.36/kWh; tyres a $1,000 set over 30,000 miles.

An EV's *running* cost really is about half a petrol car's, and most of what
remains is tyres rather than fuel. **Depreciation is the judgement call**, not
the arithmetic: it is the largest single term, it varies more than everything
else combined, and whether it belongs in a per-offer decision is a question
about your own finances rather than about the car. Leave it out and the number
tells you what a trip costs you today; put it in and it tells you what it costs
over the life of the car.

```json
"settings": { "target": 25, "band": 15, "costPerMile": 0.10, "pad": 0, "secondsPerItem": 0 }
```

`0` gives the gross rate, which is pay divided by time and nothing else.

### Picking the target, from your own offers

`target` was the one number here nobody checked. It gets picked once — $25/hr
sounds like a reasonable wage — and every verdict after that is measured
against it.

A target is not a wage. It is a decision about **how long to wait**, and whether
it is right depends on what the next offer is likely to be and how soon it
comes. That is a local fact about a market and a set of hours, not something
that can be reasoned out in advance.

Set it too low and every hour goes on work that barely clears its own costs.
Set it too high and the car sits still: the offers that clear the line really
are better, and there are not enough of them to fill a shift. The first failure
is loud. The second is silent — a screen full of PASS looks like discipline —
and it is the one that keeps being made.

A shift is a chain of cycles: wait for something worth taking, drive it, wait
again. So for a candidate line:

```
earned per hour  =   average net pay of the offers at or above the line
                    -------------------------------------------------
                     average wait for one   +   average trip length
```

Estimating that wait is where the first version of this went wrong, and the way
it went wrong is worth recording. It fitted a renewal-reward model, which needs
an arrival rate, which needs a number of minutes separating "waiting for an
offer" from "not driving". On one real 234-offer recording that constant moved
the answer from 30 offers/hour to 88 as it went from 45 minutes to 5. Everything
downstream inherited it.

The gaps say why. Half are under thirty seconds and ninety per cent under two
and a half minutes; then a cliff, and thirteen gaps of fifteen to forty minutes.
That second group is not the market going quiet — it is the length of a trip,
with no card on the screen to read.

So **Where to draw the line** estimates nothing. It replays the real stream of
offers in the order they arrived: when free, take the first at or above the
line, then be busy exactly as long as that offer said, ignoring what arrives
meanwhile — which is what actually happened to the offers that came in during a
trip. The clock runs until the last trip *finishes*, not until the last offer
appeared; without that, every run got one free trip and a recording broken into
more pieces produced a higher line from the same offers.

### A trip is not a break

That paragraph above about the fifteen-to-forty-minute gaps sat in this file for
a while as a diagnosis nothing acted on. Splitting the recording into runs still
measured each gap from when the previous offer *appeared* — so a driver who
accepted a thirty-minute job and saw nothing for thirty-one minutes was recorded
as having taken a break.

On the 245-offer recording, eight of the fifteen gaps over ten minutes came
immediately after an accepted trip, and subtracting each trip's own length left
between minus nine and plus twelve minutes of real waiting. Raw, those gaps
smear evenly across 15–38 minutes and there is nowhere defensible to cut.
Corrected, the tail is 12, 17, 20, 22, 28, 36 — and then 168 and 953, which are
the actual breaks.

The effect on the answer is the whole difference between having one and not:

| | suggested line, by where the recording is cut |
| --- | --- |
| gaps measured raw | 15min → **$39**, 20 → $35, 30 → $19, 45 → $19, 60 → $19, 90 → $19 — refused as *unsettled*, $21 swing |
| trip time subtracted | 15min → **$19**, 20 → $19, 30 → $19, 45 → $19, 60 → $19, 90 → $19 — **spread zero** |

The same data that could not name a line now names $18–19 and does not care
where you cut it. That is the stability check working as designed: it was
failing not because the recording was short but because the arithmetic was
counting the driver's own trips as time off.

This only knows about trips the driver **tagged**. An untagged take still reads
as a break, and it is not guessed at — so `unexplained()` counts the silences
nothing accounts for, and when the answer is unsettled the page asks for those
rather than for another shift. On this recording eleven trips were tagged out of
233 offers, and tagging a few more of the long silences is worth more than a
whole extra day of scanning.

One honest limit, unfixable from here: while the driver was on a trip the
scanner saw no offers, so periods of real work look like periods with no offers
on the market. That biases the replay *against* low lines, which can't fill a
gap it has no offers for — so the suggested line is, if anything, conservative.

**It refuses far more often than it answers,** and each refusal says which:

| | |
|---|---|
| not enough yet | under 40 offers, two hours, or six trips |
| unsettled | the line moves by more than $6 depending on how the recording is split — it shows the range, and asks for tags on unaccounted silences if there are any, otherwise for more shifts |
| nothing to choose | taking everything earned within 5% of any line, so there is no line to draw |

What it will never report is a dollars-per-hour you would earn. That depends
entirely on how much of the recorded time was driving rather than parked, which
the scanner cannot see: on the same data it ranged from $22 to $78.

### Delivery cards, and where an offer went

Uber states a journey as legs — `19 min (8.5 mi)` — and the reader was built
around that. DoorDash does not state a duration at all. It gives a deadline
(`Deliver by 7:15 PM`), a distance on its own, and the merchant.

Three real DoorDash cards parsed to **nothing**: no minutes, so no legs; no
legs, so no miles; and with no minutes the offer is incomplete, gets no verdict
and never reaches the journal. Every delivery offer that driver was shown was
invisible to the rig.

The deadline is the honest denominator for one of these. It is not the drive
time — it is how long the job occupies you, waiting at the counter included,
which is what an hourly rate is meant to divide by. `parse()` reports it as a
clock time and `rate()` does the subtraction, because a parser that reads the
clock cannot be held to a fixed corpus. A row says which it used:
`fromDeadline` is true when the minutes came from a deadline rather than from a
stated duration.

| card | reads as |
|---|---|
| `$41.11 … 9.8 mi … Deliver by 7:15 PM … Pickup Papa John's Store 3317` | $41.11, 9.8 mi, 46 min left, *Papa John's Store 3317* |
| `+$16.00 … Additional 6.9 mi … Deliver by 7:08 PM … Pickup Buffalo Wild Wings` | $16.00, 6.9 mi, 39 min left, *Buffalo Wild Wings* |
| `Deliver by 6:39 PM Cherry Cricket 4 items 0.6 mi $8.00` | $8.00, 0.6 mi, 4 items, 10 min left, *Cherry Cricket* |
| `UberX $10.30 19 min (8.5 mi) Mae Dell Rd & Riggins Dr … 12 mins (6.6 mi) Camp Jordan Pkwy` | $10.30, 31 min, 15.1 mi, both addresses |

A Pi 4 has **no real-time clock**. With no network it boots somewhere in 1970 and
jumps forward when it first reaches an NTP server, which in a car can be minutes
into a shift or not at all — and an hour of skew turns a 45-minute delivery into
a 105-minute one, or into a deadline already passed that wraps to twenty-three
hours, with the verdict looking exactly as confident either way. So the clock has
to earn the right to be used: anything before 2025 is treated as unset, and a
delivery card then goes **unjudged** rather than judged on a guess. Ride cards
state their own minutes and are unaffected.

**Places are stored now**, which reverses something this project used to refuse
on purpose. Without somewhere named, an offer read months ago is a row of
figures that cannot be matched to any job you remember — and a record you
cannot check is not much of a record. The offers page searches on them: type
`papa john` or `chattanooga` into the find box.

Only what the card printed, and only against an anchor the card also printed —
the merchant behind a `Pickup` label, the merchant under a deadline, the address
after a leg. Never free text off the map: the `4 mi from fast charger` badge and
the `(2 orders)` after a store name are both things a looser reader would have
swallowed, and a journal full of half-read map furniture would be worse than one
that cannot be searched by place.

It is a real trade and worth stating plainly. This is a record of where you were
and when, it lives on a card in a vehicle, and it is copied to a machine at home.

```json
"settings": { "keepPlaces": false }
```

turns it off and changes nothing else.

### How well the three card shapes actually read

For a long time this was an open question with a confident-sounding answer. The
end-to-end test — the only one that goes picture → warp → crop → tesseract →
dollars — rendered exactly two cards, both light-mode and both Uber-family. The
delivery card's three fixtures were **text**: they went straight into the parser
and never near a lens. So every claim about reading a DoorDash offer rested on a
string somebody had typed out by hand, which is the wrong half to test — that
card is laid out unlike the other two in exactly the ways the pipeline is
sensitive to, with the payout pushed down under a banner, a distance standing
alone with no time beside it, and a shorter card that puts the crop somewhere
else entirely.

It is drawn now, and measured. Reading the payout correctly, at three mount
distances, in both themes:

| | clean | glare | soft | dim cabin | phone turned right up | rippling screen |
| --- | --- | --- | --- | --- | --- | --- |
| ride card | ✓ | ✓ | ✓ | ✓ | ✓ | refuses |
| shop order | ✓ | ✓ | ✓ | ✓ | ✓ | refuses |
| delivery card | ✓ | ✓ | ✓ | ✓ | ✓ | refuses |

**A delivery card is as reliable as a ride card**, and slightly tougher under
ripple — it holds to amplitude 24 where the ride card goes at 18, having fewer
small lines to lose. Glare across the middle of the card, a mount shaken soft,
and a phone dimmed for a night shift all cost nothing on any of the three.

The over-bright column is modelled the way a sensor actually fails rather than
as a multiply: charge that will not fit in a well spills into its neighbours and
the lens veils the frame with a share of its own light. That distinction is the
whole test. A bare multiply leaves black text perfectly black however blown out
the white is, so it would say this condition costs nothing — where in fact the
veiling is exactly what eats the thin strokes of a payout.

Swept from correctly exposed to six times too bright, in steps of a quarter:

```
  ride card       RRRRRRRRR--pp-pp-----
  shop order      RRRRRRRRRR-p---------
                  x1.0 ......... x3.5 ......... x6.0
  R right verdict    p payout misread, no verdict reached    - refused
```

Right up to about **3.25x**, then refusals. In between there is a band where the
payout is genuinely misread — at 4x the reader returns `$16 05`, the decimal
point bloomed away, and the parser makes that $16.00 instead of $16.05. **No
wrong verdict is reached anywhere in the sweep**, and the reason is structural
rather than lucky: the decimal point is a small feature, the journey underneath
it is small text, and both die at the same brightness. A card that has lost its
decimal point has also lost its minutes, so the reading is incomplete and never
gets rated. The first rule holds because the damage is not selective.

Ripple is the one that beats all of them, which is expected: it is the screen's
refresh beating against the shutter, and it is what the flicker-safe exposure
exists to prevent. The amplitudes above are past what a correctly exposed rig
produces.

The number that matters is not in that table. Sweeping ripple from nothing to
well past the failure point, across every shape: **no reading ever reached a
verdict with a wrong payout.** Every single failure came back as no payout at
all. That is the project's first rule holding as a measured property rather than
as an intention, and it is now asserted on every run — each shape, under each
kind of damage, has to be either right or silent, never a third thing.

### ...and the rate is not the payout

That assertion checked `parsed['pay'] == true_pay`, and its own comment called
that "the payout the card was drawn from". But the number on the screen is pay
divided by time, less distance times cost. **Checking one of the three inputs
checks none of the answer**, and the gap was not hypothetical.

Adding the over-bright column above turned one up immediately. A ride card at
three times the brightness it was exposed for read `20 min (7.3 m1) trip` — the
`i` of `mi` bloomed into a `1` — so the second leg handed its twenty minutes to
the sum and none of its distance. The reading was 23 minutes over **1.1 of its
8.4 miles**: `complete`, `whole`, unflagged, and rated at a confident
**$41.01/hr for an offer worth $35.30/hr**.

Every guard missed it, and for the same reason. They all look for a distance
that is too *big* — `check_distance` exists because losing the decimal in
"3.6 mi" turns a 6mph errand into a 63mph one — and this failure produces a
distance that is too *small*, which reads as an ordinary slow trip. Missing
miles are missing cost, so it errs optimistic, which is the one direction that
turns a pass into an accept. The corpus had an instance of it all along, filed
under a name that says the opposite of what it asserted.

So a leg with minutes and no distance now makes the journey's distance
uncertain, and makes the reading **not whole** — which is the right answer twice
over, because another frame is exactly what fixes it: the accumulator merges
legs across frames for this reason, and `whole` is what keeps the loop
resampling until it has. The same rule is in the browser parser, in the
accumulator's merge across a window, and in the shared corpus.

The first version of that rule asked whether some *other* leg had kept its
distance, so one leg losing its miles was caught and **both** losing them was
not — which is the wrong way round, because the second leaves less evidence
rather than more. With no leg carrying a distance the total is simply `null`,
indistinguishable from a card that states no distance: nothing is flagged,
`rate()` charges no mileage for a distance it does not have, and the row is
whole and unsuspicious, so its **gross** rate is pooled into every median on the
offers page beside everyone else's net ones. Measured on
`$16.05 25 min (11.q5 mi) away 17 min (3.q mi) trip`, both distances mangled:
$22.93/hr, whole, unflagged, counted.

It is two legs or more now, and it does not ask about the others. A single leg
is left alone, because it can be a total — `$7.09 34 min total` states no
distance and is a whole journey by itself — and one plain leg is already not
whole for having no second half.

Making `is_whole` read `legDetail` turned up one more thing, which is the point
of the whole mechanism. A merged reading starts life as a copy of the **last
frame's** parse, so every summary field has to be rebuilt from the window or it
describes one frame instead of the sum — `milesUncertain` already was, for
exactly this reason, and `legDetail` was not, because until now nothing read it
off a merge. So a window that had already recovered the trip distance from a
good frame, correct at 8.4 miles and not uncertain, went back to `whole: false`
on the next damaged frame: a card the rig had read correctly stopped being
spoken, kept being resampled, and reached the journal as a fragment. The legs
are rebuilt from the window now, and once a distance is recovered it stays
recovered — which is what merging across frames is *for*.

### What went past unrecorded

The one thing a journal can never contain is what is not in it. Every figure on
the offers page divides by the offers that were *read*, so a rig quietly missing
a third of them looks exactly like a rig missing none — the medians shift, the
suggested line shifts, and nothing anywhere says why.

The nearest honest thing to a miss rate: **a read that found a payout is proof a
card was in front of the camera**, and an accumulator episode that ends with no
journal row is one the rig watched go past. Both are counted, on the same
two-minute beat as the health line, and written to the journal as a
`kind: "seen"` row — the same convention the driver's own tags use, so nothing
that reads offers has to learn about them and the sync carries them already.

The offers page turns the pair into a sentence: *"3 times the scanner picked a
payout off the screen and never managed to record it — 25% of the 12 it saw."*
Usually that is two reads that never agreed before the card was gone.

Two things it is careful about, both of which would make it a lie otherwise:

* **it is a floor, not a rate.** An offer the reader never saw at all is
  invisible to this exactly as it is to everything else. The page says so in the
  same breath rather than in a footnote.
* **it counts sightings, not offers.** One card watched, lost behind a hand and
  picked up again is two sightings of one offer. The wording never invites the
  figure to be compared with the number of rows below it; what it is for is the
  ratio.

Counted on the transition rather than when the card goes, which is the less tidy
of the two and the only correct one: a card still on the screen when the window
closes has not ended, so waiting would drop the last card of every window and
never count one that sat there for a whole shift. The cost is that a single card
can be seen in one window and kept in the next, and that costs nothing, because
both totals are added up over the whole range before anything divides them.

### When the reading cannot be true

Not every misread is noise. In one shift of 234 offers, three had lost a decimal
point — `$11.84` read as `$1184` — and two had a misread time that put the trip
at 110 and 120 mph. Each was shown in green as **ACCEPT** and spoken aloud:
*"accept, three thousand five hundred an hour."*

A reading outside what a real offer does now gets **no verdict at all**: a colour
that is deliberately none of the other three, the name of the figure to check —
the pay, the time, the distance — and the card's own numbers underneath. The
headline rate is withheld, because at that size it is read before the label
above it.

| | flagged when |
|---|---|
| pay | outside $1 – $300 |
| time | outside 2 – 240 min |
| speed | miles ÷ time over 75 mph, on trips of a mile or more |

Only the direction that produces a wrong ACCEPT is checked. A reading that
*understates* an offer costs a decline, and the next offer is under two minutes
away; one that overstates it puts you in the car for forty minutes for six
dollars. Crawling through traffic at 6 mph is a real thing that happens and gets
a PASS, not a query.

The bounds sit clear of anything genuine in that data — the best real offer was
$45/hr, and the fastest real trip averaged 56 mph over a 115-mile highway run —
so a card has to be misread rather than unusual to trip them. The row is still
written, still complete, and now carries a `doubt` field naming the figure. A
reading this project got wrong is the most useful row in the file.

## Run

```sh
python3 rpi/scan_pi.py --speak
```

Reads are printed as they happen. `--speak` says the verdict aloud once per
offer, at the point two reads agree — "pass, twelve an hour" — which is the
right output for driving, since it needs no glance at all. `--display` shows a
big colour panel if you have a screen attached, and `--list-modes` prints what
the sensor reports if you want to check the table above against your module. `--save-misses DIR` keeps frames
that failed to parse so you can feed them back through `bench.py`.

`--no-track` pins the corners to exactly what calibration found, instead of
following the phone. Only worth it if tracking is misbehaving — a genuinely
fixed mount loses nothing by leaving it on, and a mount that moves loses offers
without it.

### Gain holds when the phone is away

Gain adapts to a phone dimming itself, measured on the screen's own corner of
the frame. Once the phone is out of the mount that corner is dark upholstery,
which reads as a very dim card — so the gain used to wind up chasing something
that was not there, reaching its 8x ceiling in about 78 seconds. The phone then
came back to a card blown out at 8x and needed a further **minute** of
six-second steps to climb down, which is exactly the minute the driver had
picked the phone up to look at an offer.

Gain is now held whenever the tracker has lost the screen, so what the phone
comes back to is the last value that suited a real card. With `--no-track` there
is no tracker to ask, so darkness speaks for itself: below `LIT_ENOUGH` nothing
in view is a lit screen. A phone that genuinely has dimmed still gets brightened
— it reads several times that threshold even at its dimmest.

### The middle of the frame is the anchor

The card is presented in the middle. That makes "which bright shape does the
centre of the frame fall inside" the one piece of evidence here that never goes
stale — stored position goes wrong the moment the mount is nudged, and stored
size the moment the phone is re-seated, but where the driver aims the card does
not change. The detector already prefers the shape containing the centre; the
tracker now agrees with it.

So a screen holding the centre while the corners are somewhere else is taken as
the phone, after the usual agreement and in about two seconds. Shape still has
to match — that is what tells a screen from the Accept bar beneath it — but
**size deliberately does not**, because a size the calibration refuses is
exactly the state that used to leave the corners stuck with no way out.

It cannot settle every case. Corners sitting *on* the screen at the wrong size
still hold the centre, and that is equally "the phone was re-seated" and "the
outline is on part of the screen"; no amount of looking separates them. That is
what the timeout below and the **⟳ Re-find** button are for.

### Re-find, when it needs telling

**⟳ Re-find** in the live view puts the corners back where calibration left them
and drops every piece of accumulated evidence, so the next screen argues for
itself from nothing. It is a POST to `/api/recalibrate`, which touches
`rpi/.recalibrate`; the scanner notices within a check and deletes it. A file
rather than a signal, for the same reason `.viewing` is one — the scanner is
sometimes a child of the web server and sometimes a systemd unit that has never
heard of it, and a file works identically either way.

### When the corners get stuck

Candidates are judged against the calibration, never against wherever the
corners have drifted to — a relative test has no floor, and six candidates each
80% of the last walked one rig down to 63% of its screen, after which the real
phone was too *big* to be accepted and it sat there permanently.

The anchored test fixes that and creates its own version of it. A screen the
calibration does not recognise can never be adopted, however plainly it is
there: re-seat the phone a quarter further back, or knock the mount closer, and
the size test refuses the real screen on **every check, forever**. The corners
freeze. And because a candidate *was* found each time, `misses` stays at zero,
so the health line goes on reporting the corners held — the green box simply
stops moving and nothing says why.

So there is one bound. Corners that sit off a steady, phone-shaped screen for
`RECOVER_AFTER` (30s) are taken as the stuck party: they move onto it and the
stored calibration is written off as out of date, with a log line saying so.
The health line distinguishes three states now — held, **stuck**, lost — where
it used to call the first two the same thing.

Two things keep that from reopening the walk it replaced:

* **the candidate has to hold still.** A walk downhill is a sequence of
  *different* boxes; the anchor resets the moment one moves away from the last
  by more than the agreement tolerance, so the clock never runs. A phone that
  has genuinely been re-seated sits still, so its clock runs from the first
  check.
* **only the size test is given up, never the shape one.** Size is what
  legitimately changes when a phone is re-seated; shape is what tells a screen
  from the Accept bar beneath it. A strip can sit there all day and will never
  be adopted.

It is a recovery, not a repair: re-run calibration when convenient, or the next
start begins from the same stale corners.

## Keeping the offers

Every offer the scanner is confident about gets one line in `rpi/journal.jsonl`,
so a shift can be looked at afterwards. `journal.html` on the web side reads it
and draws the distribution, the time-of-day blocks and the ride/shop split; the
raw file is JSON Lines and needs nothing but `json.loads` per line.

The write happens on the same confidence the spoken verdict uses — a whole
reading, two frames agreeing, a rate ready — so the file and the voice can never
disagree about what was read. What the two do *not* share is when to forget:
speech resets on any empty read so the next card gets announced, and doing that
here would record the same offer twice every time a glare frame landed in the
middle of a resample burst. The journal forgets an offer only when the
accumulator says the card changed.

A reading can improve after the scanner is first sure of it — a leg arriving
late, an item count two frames behind. That is worth keeping rather than hiding,
so the better reading is appended as another row with the same `id`. Nothing is
ever rewritten in place, which is what makes it safe to append to from a process
that can be killed at any moment.

### One card, one offer

Which readings share an `id` is decided by the **payout**. It is the figure the
card leads with, the one this reader gets right most often, and the one a driver
would use to say "that is the same offer"; the rest of the card moves while the
accumulator collects the legs, which is exactly when the `id` must not change.
Same payout, inside ninety seconds, is the same card.

That rule used to be "an identical reading", which OCR defeats by its nature.
One real Uber card in Chattanooga, seventy seconds, four rows:

| time | pay | minutes | miles | rate |
| --- | --- | --- | --- | --- |
| 19:50:37 | $10.30 | 31 | 15.1 | $11.17/hr |
| 19:51:28 | $1030 | 31 | 15.1 | **$1,984.78/hr** |
| 19:51:41 | $10.30 | 40 | 23.6 | $4.83/hr |
| 19:51:47 | $10.30 | 31 | 15.1 | $11.17/hr |

Four offers, as far as anything downstream could tell — four rows in the export,
four points in the median. There was one card. The middle two are a lost decimal
point and a stale leg merged into a fresh one, and the second of those was
caused by the first: `$1030` declared itself a new offer *and* became the payout
the next reading was compared against, so the correct `$10.30` that followed
looked like a third card.

So a reading the parser already calls impossible cannot claim an identity of its
own and cannot become the one others are matched against. It is still written —
it is evidence, and a gap is worse than a bad row — it just attaches to the card
in front of it.

### Which reading to believe

**Readings of one `id` vote; the majority wins.** This replaced "take the last
row", which is right when a reading improves and wrong when it degrades — the
scanner also re-reads a card every few seconds for as long as it is on screen,
and any one of those can be the bad one. Being last is not evidence of being
right. Above, the majority answer is $10.30/31min/15.1mi whatever order the four
arrive in.

Agreement on the payout counts for more than agreement on minutes or miles. A
row flagged `suspect` never wins however often the same misreading repeats, and
a `whole: false` row loses to any whole one. A tie goes to the later row, which
is the old behaviour and the right one for a reading that genuinely improved.

A whole row is chosen rather than the best of each field stitched together: a
row is internally consistent — its `$/hr` was worked out from its own pay,
minutes and miles — and a composite would have a headline that does not follow
from the figures printed beside it, which is the one thing this project refuses
to show.

A reading the scanner never saw *whole* — a single leg whose "total" the reader
mangled, or a two-leg card no frame caught both halves of — is written with
`whole: false` rather than refused. Such a reading always flatters the offer, so
it must never reach a median, and `journal.html` sets it aside and says how many.
But refusing it made the offer *vanish*, and a gap nothing accounts for is the
worst thing to find in a file being read back months later. If a later frame does
see the card whole, it supersedes the partial row anyway.

Three deliberate omissions:

* **no accept/decline column.** The scanner cannot see the Accept button and
  must never touch it, so anything here would be a guess presented as a record.
* ~~**no OCR text.**~~ **Superseded.** The reason given here was that "the
  useful part is already parsed into numbers; what is left is pickup addresses"
  — and a later change added a `places` column that stores exactly those
  addresses, in the row, in the CSV and in the sync. What was left out to
  protect is now kept beside it, so the omission was costing evidence and
  protecting nothing that was not already there.

  It cost more than it looked. 568 real offers on record and **not one
  recoverable card**: every figure the reader derived is in the file and the
  text it derived them from is not, so every question about the parser has had
  to be answered against rendered replicas. The "Avg. wait time at pickup" line
  that switched the running cost off on a third of one shift was found from
  three mangled fragments that happened to survive in `places` — because the
  addresses were kept and the reading was not.

  The row now carries the reading, truncated at 220 characters: a ride card
  reads to about 80, and the headroom is for the frames where the crop takes in
  a slice of the map, which are exactly the frames worth studying. It adds about
  90 bytes to a 623-byte row — single-digit megabytes over a year of driving,
  against a 64MB roll. It is the last column of the CSV so a spreadsheet puts it
  off the right-hand edge and every column before it keeps the position it has
  always had.

  The protection that mattered is unchanged and is below: `rpi/journal.jsonl` is
  gitignored, and the static server hands over only files whose extension is one
  the site is built from — `.html`,
  `.css`, `.js`, the icons, the fonts, the traineddata. It used to be the other
  way round, a list of paths to refuse, and a list of paths to refuse has to be
  remembered every time something new appears beside `server.js`. It was not:
  `rpi/` and `ssl/` were refused *by name*, so the journal in `rpi/` was safe and
  a copy of that same journal anywhere else was not. `journal-backup.jsonl` in
  the root, `backup/journal.jsonl`, `logs/uberscan.log` — all served in full,
  pickup addresses included, to anyone on the car's wifi. Those are exactly the
  files a person makes when they are being careful with their data.
* **no failing.** A full card or a read-only filesystem costs the journal and
  nothing else. The scanner exists to read offers and keeps reading them.

```sh
python3 rpi/scan_pi.py --no-journal        # keep no record
python3 rpi/scan_pi.py --journal /some/other/path.jsonl
JOURNAL=/some/other/path.jsonl npm start   # ...and tell the web side where it went
```

The scanner and the web server have to name the same file. Nothing detects a
mismatch: the page simply reports no offers while the scanner writes happily to
somewhere else.


Rows carry the `target`, `band` and `costPerMile` in force when they were
written, because a stored "PASS" is unreadable a month after the target moved.

### The keypad had no test

`ui.js` is the fallback input path: what a driver uses when the camera cannot
read a card, or when there is no rig at all and this is an app on a phone. Its
arithmetic is the shared parser's and is covered by the corpus; the four
hundred lines around that arithmetic were covered by nothing.

Three faults are recorded in its own comments, which is to say all three
shipped, and each is a *confidently wrong number* rather than a crash:

  - **The settings entry is shared with the camera scanner**, which keeps
    `secondsPerItem` and `fullFrame` in it. Writing it back wholesale deleted
    them, so changing anything on this page silently reset the shopping
    allowance to zero — and scan.html then rated Shop & Deliver offers as if
    the shopping took no time. Nothing resyncs the two pages.
  - **`ready` was measured against the padded total** rather than the typed
    minutes. Restoring that bug and typing a payout with a ten-minute pickup
    pad set gives, measured: a green **ACCEPT at $96.3/hr** for an offer with
    no time on it at all.
  - **`perMile` was gross** while the rate beside it was net, so the same offer
    read $1.91/mi here and $1.56/mi on the Pi, with neither screen saying why.

`rpi/test_keypad.py` opens the page in a real browser and presses the keys,
because `ui.js` exports nothing and that is how a thumb reaches it anyway. Forty
four checks: those three, plus what the digits do (one decimal point, two
places, a six-figure cap, a dropped leading zero), stepping between the three
fields, the physical keyboard a rig might have plugged in, the draft that is
kept across a reload and dropped after three minutes — an offer from an hour
ago is a number the driver will read as this one — the logging cap, and the
page still adding up an offer with `localStorage` throwing on every call, which
is private mode, a full quota, or a browser with site data turned off.

Each of the five behaviours worth having is verified by breaking it: restore
any one of them and the check named for it fails.

### A leg is a leg because the card says so

The wait-line fix above matched a phrase. That was the wrong shape of rule, and
probing for others showed why: a promo chip's **"15 min left"** and an ETA
badge's **"arrives in 9 min"** each became a third leg on a two-leg card and
tripped the same guard. A phrase list would have needed both, and then the next
one.

Uber labels every leg of a journey — *away*, *trip*, *total* — and prints its
distance beside its time. So the card's own grammar decides it:

- a minutes-only token **with** a label is a leg whose distance did not read,
  which is the damage the guard was written for;
- one **without** a label was never a leg.

That subsumes the wait line and needs no vocabulary of things that are not legs.
It also **fails safe**: a real leg that loses *both* its label and its distance
is read as not-a-leg, so the other legs' distance is charged instead of none at
all — a cost that is too low rather than absent, which is the less optimistic of
the two errors and the only direction that matters. That is the "charge the
partial distance" idea this work set out to do, arrived at from the other side.

A cap on leg count would have been wrong: a stacked order really does have four,
and the corpus now pins one.

**The field had to survive three hops, and it was dropped at two of them.**
`parse()` builds the legs; `legDetail` projects them; the accumulator rebuilds
them across frames — and `is_whole` re-runs the rule over whichever it is handed.
Neither projection carried `labelled` at first, and neither failed loudly: the
rule simply stopped seeing any leg as labelled, so a card whose distance read as
"7.3 m1" called itself whole again. The suite caught both. `test_accumulate.py`
now asserts the property rather than the instances — every field a leg carries
survives both projections — so the next field added takes the same trip safely.

### The line about waiting that switched the running cost off

The plan was to charge the *partial* distance when a leg lost its miles, on the
grounds that a partial distance is an under-estimate and charging it tightens
the bound. Measuring first showed the premise was wrong, and the real fault is
smaller and worse.

Uber prints **"Avg. wait time at pickup 4 min"** under the pickup address. It is
a duration with no distance beside it, so it matches `LEG`, becomes a **third
leg on a two-leg card**, and trips `legs_short_a_distance` — which reads a leg
without miles as OCR damage and marks the whole distance untrusted. `rate()`
then charges no mileage at all.

The distance was complete the entire time.

The fingerprint in the data is unmissable once you look for it: **67 of the 70
three-leg cards** on one real shift were flagged, and a ride card has exactly two
legs. The uncertain rows are *longer* journeys than the trusted ones — 37 minutes
against 28, 12.8 miles against 7.7 — which is the opposite of what a truncated
distance would look like, and exactly what an extra minutes-only leg produces.
Three of them still carry the phrase in the journal, mangled the way a camera
mangles things: `Avo Wait (ime at pickup`, `walt time at plclaup: min`, `aan at
pickup`.

Replayed over the same 202 offers:

| | before | after |
|---|---|---|
| rated with **no running cost** | 108 (53%) | **41 (20%)** |
| CLOSE CALL | 58 | 27 |
| PASS | 139 | 168 |
| ACCEPT | 2 | **4** |

Twenty-nine offers stop sitting in a capped CLOSE CALL and become honest passes,
because their distance is now charged and they do not clear the target. Two
become real ACCEPTs — green lights the arithmetic supports, rather than ones
manufactured by a deduction that never happened.

Two things it deliberately does not do. **The wait minutes still count**: the
driver still waits, it is time the offer occupies them, and dropping it would
raise the rate, which is the dangerous direction. And **a leg that really did
lose its distance is still doubted** — the guard keeps doing the job it was
written for; the corpus pins both directions, and the mutation that treats every
minutes-only leg as a wait fails on the second.

The pattern is forgiving because it is read through a lens, and it is consulted
only in a short window around a leg that already matched, so a stray "wait"
elsewhere on the card cannot invent one. It looks **before** the figure as well
as after, because the card prints the phrase first.

### Keeping enough to answer the next question

Every parser fix on this page was found from evidence that happened to survive.
The wait-line was found from three mangled fragments that lived on in `places`
because the addresses were kept and the text was not. The distance thrown away
by a length check was found because the text finally *was* kept. Each time, the
question could only be asked because something had been recorded for a different
reason.

Three things were still being discarded, and each is the answer to a question
that has already come up.

**The line breaks.** `parse()` works on `normalize()`'s output — whitespace
flattened to single spaces — so no rule has to care how the engine broke the
lines. That flattening throws away *which line each figure sat on*, and a card's
meaning is partly in its lines: `2.4 mi · 20 min` on one line is one journey,
while a distance and a duration on separate lines are two different facts. Both
of the last two parser fixes were rediscovering line structure from punctuation
because the structure itself had been dropped before anything could look at it.
The journal keeps the unflattened reading now; `normalize()` is deterministic,
so the flat form can always be made again from it.

**Every frame, not the one that won.** A card is read four to eight times and the
frames disagree — that disagreement is the entire reason the accumulator exists.
Only the winner reached disk, with no account of what it beat, so the one record
of what this camera does to a real screen at night was the single reading that
happened to come out on top. Distinct readings are kept, deduplicated (a card
sitting still says the same thing repeatedly) and capped at eight, and they go
into the CSV as a `scans` column joined with pipes.

**The picture itself** — `--keep-scans`. This is the one that changes what can be
asked. Whether a crop was too tight, whether a threshold ate a decimal point,
whether a different psm would have found the missing leg: all of it is
answerable offline from the card image and *none* of it is answerable from the
text, because the text is what the damage left behind. What is written is the
greyscale card as it came off the warp, **before** `preprocess()` — a picture of
preprocess's own output cannot be used to judge preprocess.

Off by default, because this writes to an SD card in a car and a feature that
quietly fills one is worse than a feature nobody has. Bounded even when on: 400
pictures, oldest first, about 40kB each. Written only on the reads that land a
row, so what is on disk is the offers in the journal rather than every glance at
an empty mount. Named by offer id and stamped, so a row and a picture can be put
back together months later with no second index to go wrong — and sorting the
names sorts them by time, which is what lets the pruning be a slice. Never fatal:
this is evidence, not the job.

They land in `rpi/scans/`, which is gitignored for the same reason the journal
is, and more so — a photograph of the driver's phone with the addresses on it is
the same fact in a stronger form.

**And the export had no test at all.** It is the one path by which a shift's
readings leave the rig, and every question on this page was answered from the
file it produces, so a column silently missing from it costs a whole shift of
evidence and shows up as nothing. It is checked now.

### Both ends of the job, lost to a length check

Stacking two orders needs to know where they go, and the first measurement of
that said only **26%** of cards yielded both ends. That number was not about the
cards. It was about a `> 60` in `find_places`.

The commonest delivery card states one total leg and then both ends of the job:

```
27 min (7.3 mi) total   Rick's Hotwings (Kennesaw)   Hamby Place Dr NW &
Travistock Pl NW, Acworth
```

There is no `Pickup` label to anchor on and only one leg, so the leg-tail rule
took the whole thing as ONE place — 71 characters of merchant and address
together — and the 60-character cap threw it away entire. Not truncated:
**discarded**, both ends, silently, on 53 of one shift's 210 cards.

The card's own grammar separates them. Uber prints the merchant with its branch
in brackets, so the closing bracket is the seam. Two more rules came out of the
same measurement:

- **An address ends at its town.** Nothing on the card marks the end of one,
  which is what left `Lakeview Ter & Windmill Dr, Dallas ill` in the journal —
  the `ill` is the bottom icon row. A comma, a capitalised name or two, and
  stop. The possessive is allowed, because a card does not always end on a town:
  `Roswell Road, Johnny's Hideaway` ends on the venue, and a first version cut
  it to `Roswell Road, Johnny`.
- **The leg-tail window is 130 characters, not 80.** With merchant and address
  sharing one tail, 80 cut the town off the end of the half that matters:
  `Double Branches Ln & Sagamore Ct. Dal`.

And one that was never about this card at all. **The two parser ports had
drifted**: the JavaScript split a tail on a pipe and kept both halves, and the
Python cut at the pipe and dropped everything past it. A pipe is what a camera
makes of a divider, so no hand-written fixture had one and the shared corpus
never saw the disagreement — while on 21 of one shift's 309 cards the phone
stored a dropoff the rig did not.

| of 210 untruncated cards | before | after |
|---|---|---|
| no address at all | 64 | **14** |
| one end only | 68 | 54 |
| **both ends** | 78 | **142** |

The two ports now agree on all 309 real cards across pay, time, distance and
addresses — a stronger check than the fixtures alone can make.

**A stray that the corpus caught.** Somewhere in this work `'L': '1'` got into
`DIGIT_FIX` in both ports. It looks harmless and it is not: `53L min` becomes
531 minutes, and the corpus has a case for exactly that shape — "a leg whose
minutes have rubbish stuck to them is not a leg" — because two stacked guesses
is how noise becomes data. It failed four checks in both languages.

### Two orders at once, and the question this rig can honestly answer

Working two apps, the driver accepts an order and a second offer arrives while
the first is still in the car. The question is whether both fit.

The obvious answer is to map the four addresses and route them. **This rig
cannot do that, and the driver's own 836-offer export is what says so:**

| | |
|---|---|
| the car's network | offline most of the time — nothing can be geocoded while the card is on screen |
| caching geocodes ahead of time | 971 place sightings, **814 distinct**. A cache built from three days of driving covers **11%** of the next day's. Restaurants repeat; customers do not. |
| the town, where it is stated | on 69% of addresses — but 66 of 177 say "Atlanta", which is twenty miles across. A centroid there is not a location. |
| a deadline to be "in time" against | **not one card in 836 stated one** |

So the rig does not pretend to know the geography. It answers the part that is
arithmetic — the part a driver cannot do at a glance, and the part the card
really does state — and it answers it as a **range**:

```
+ the one you have: $20–34/hr over 30–50 min · beats finishing alone
```

**worst** is the two jobs sharing no road at all: the new one starts when the
old one ends and the minutes add. Any overlap at all makes it better, so it is a
true floor. **best** is the new one riding along inside the old, costing only
the longer of the two. Nothing can beat it. Where between them the truth sits is
a fact about two maps on a phone the driver is already holding.

That is the division of labour: the rig does the arithmetic the driver cannot do
while driving, and the driver does the geography the rig cannot see. Naming a
single number would be claiming that geography, which is the one thing it must
not do.

**ACCEPT only when the whole range clears the line**, for the same reason a rate
with no running cost taken off it cannot earn one: a range that straddles the
target is a maybe, and a maybe drawn in green is a wrong answer.

The order in hand is pro-rated by its remaining time rather than counted whole.
A driver twenty minutes into a twenty-five minute job is not earning the entire
fare in the last five minutes, and treating them as if they were makes "just
finish it" beat everything on earth in the closing moments of every order.

**It expires on its own clock.** A driver pulling into traffic will not reliably
press a second button when they drop off, and an order that never ends puts a
stale job's minutes against every offer for the rest of the shift — a wrong
number that gets more wrong the longer it sits. The card's stated duration ends
it, at half again that plus ten minutes, because orders run long. Ending it
early costs a figure the driver could have used; ending it late costs a wrong
one, and only the standalone verdict is unaffected either way.

`Drop` puts it down sooner. It is memory only and deliberately not written to
the journal: the mark is a permanent fact — this offer was taken — and dropping
it off does not make that untrue. A restarted server simply has nothing in hand,
which is the safe way to be wrong.

**What it cost the bar of controls.** Two of the six are conditional — "Took
$8.04" with an offer on the record, "Drop" with an order in the car — so with
both up the bar goes from five buttons to seven, and measured across every panel
this ships on, not one has room:

| panel | bar | seven buttons |
|---|---|---|
| 1280x800 | 804px | 107px each — "Took $12.45?" wants ~110 |
| 1024x600 | 662px | 88px |
| 800x480 | 559px | 71px — "Set box" wants 78 |
| 480x320 | 280px | 34px |

The bar is narrower than the window on all of them because the phone picture
sits beside it, which is how a first attempt keyed on the *window* read 800px,
decided there was room, and clipped four labels on the one screen this thing is
bolted to. So there is no width threshold: with both conditional buttons up, the
two links that lead somewhere else — the keypad and the offer log, both read
parked — stand down, and the five used while the car is moving stay. The layout
suite measures the bar in all three states and holds the crowded one to clipping
nothing the six-button bar did not already clip.

### A suite that skipped two checks and said it passed

The crop-box suite hands the file the web server wrote to `rpi/cropbox.py`, so
the two halves of that contract are held to one format. Its check count had been
moving between 14 and 16 between runs, which is the only trace it left.

`pythonReadsIt()` returned `null` for "python3 is not here, skip this" — and
`take_request()` legitimately returns JSON `null` when there is no pending box.
Two different facts, one value. So a round trip where nothing was written
reported itself as a missing interpreter, printed a friendly note, and the run
said **All 16 passed** with fourteen of them run.

The outcome is discriminated now: `ran` says whether the interpreter worked,
`value` is whatever it said, and only `ran === false` skips — with the reason
printed, so the next time it does skip there is something to act on.

Still outstanding: the suite binds port 8791 by name, so two runs in quick
succession can collide and one fails. Every other browser suite here takes a
free port from the OS.

### The distance that was on the card and thrown away

The wait-line fix above was found from three mangled fragments that happened to
survive in `places`, because the text itself was not kept. The next shift kept
it — 309 cards, verbatim, off this driver's own phone — and the first question
put to that corpus found a bigger fault than the one it was built for.

**37 of the 309 printed a distance the parser did not take. All 37 for the same
reason, and it was not the OCR.**

The commonest card this driver is shown is the delivery offer:

```
$7.20 Guaranteed (incl. tips) 2.4 mi + 20 min @ Pickup McDonald's
```

The distance and the time are two halves of **one line**. The card's own
separator is an interpunct, and the camera renders it as `+`, `-`, `«`, `™`,
`=`, `.`, `+-`, `-+-` or a stray letter — which looks like the problem and is
not. `LONE_MILES` matches every one of those forms. It was never consulted.

The "20 min" half matched `LEG` and became a minutes-only leg. The lone-distance
branch is guarded by "only when the legs found nothing", and the guard was
written as `not used` — which asks whether any leg was found, not whether any
distance was. So a pseudo-leg four characters away from the number blocked it,
and the distance was dropped.

Three things follow from one dropped number, and all three were visible in the
export:

| | of 309 cards |
|---|---|
| distance printed, not taken | **37** |
| ...of those, rated with no mileage charged | **37** |
| ...of those, held `complete` but never `whole` | **37** |

So the panel showed a **ceiling as if it were a rate** — median 26% high, p90
45%, worst 133% — which is the exact failure the uncosted cap exists to contain,
arriving through the one door the cap cannot see. And it showed it *with a
question mark*, for the life of the offer: never spoken, set aside on the offers
page, and resampled until the card went away, for a reading that had the pay,
the distance and the time and nothing left to learn.

The fix is one word in each port, and it is a rule the file already had.
`legs_short_a_distance` decides what counts as part of a journey: a leg that
states a distance, **or one the card labelled** (`away`, `trip`, `total`). Uber
labels every leg of a ride, so a labelled leg with no distance is damage and
another frame may still fix it; an unlabelled minutes-only token was never a leg.
The lone distance is consulted when nothing that *travels* was found, and
`is_whole` asks the same question of a single token: labelled means half a ride
card, unlabelled means a whole delivery card.

Replayed over the 210 cards that were not truncated — the ones where the stored
text is exactly what the reader saw:

| | before | after |
|---|---|---|
| distance dropped | 31 | **0** |
| held unfinished | 31 | **0** |
| rated with no running cost | 31 | **0** |
| CLOSE CALL | 15 | 6 |
| PASS | 178 | 186 |
| ACCEPT | 17 | 18 |

Almost all of the movement is a hedge becoming an honest PASS. The single new
ACCEPT is a $25.60 GoPuff run over 8.3 miles and 36 minutes: $38.52/hr net of
its own mileage, held at CLOSE CALL before only because the cap was doing its
job on a rate with no cost taken off it.

What the corpus could **not** answer is as much the point. 99 of the 309 cards
sat exactly on the 220-character cap, cut off at the end — where the pickup, the
dropoff and a ride's second leg are written — so re-parsing them gives a
different answer from the one the rig gave, and the rows most worth studying are
the ones the column could not speak for. The cap is 600 now. The check that
guarded it asserted only an upper bound, which any cap satisfies; it now also
holds a real full-length card whole.

### The fifty-dollar offer that was a fifty-cent chip

`find_pay` takes the largest dollar figure on the card, and said so: *"the offer
headline is the largest dollar figure; promo lines are smaller."* That premise
is true of the card and false of the photograph.

Uber prints a chip under the headline saying what part of the total came from
where — `+$0.50 included`, `+$2.39 included for priority`. A decimal point is a
pixel or two through a lens and it is the first thing to go, so `+$0.50` reads
as `+$050`, and fifty dollars is a bigger number than the offer.

Twice on one shift:

| card's real payout | what the chip read as | verdict shown |
|---|---|---|
| $13.08 | **$50.00** | **ACCEPT**, $71/hr |
| $21.06 | **$50.00** | **ACCEPT**, $68/hr |

Two green lights, on offers worth a third of what the panel said. Nothing caught
them. The sane-rate ceiling fires above $200/hr and these sat comfortably under
it — which is the whole difficulty with a plausible wrong number: every guard
here is built to catch the implausible ones. A third card read `+$170 included`
over a real $12.05 and *was* caught, only because $170 over nine minutes is
$1133/hr and no guard was needed to find that suspicious.

Eight of the 309 cards took a chip as the payout. Five of those had no readable
headline at all, so the rig was rating a job on its priority bonus: $1.85 over
25 minutes, reported as **−$7/hr**.

The rule is the card's own grammar, the same way `LEG_TAIL` is: a **plus**, an
amount, and the word the card prints to say what the amount is, **with nothing
in between**. That last clause is the whole safety of it. The headline reads
`$11.42 Guaranteed (incl. tip)` — "incl" is right there too, but "Guaranteed"
sits in the way, and a version that allows twenty characters of slack swallows
the headline instead. Two corpus cases pin that, and the mutation that loosens
it fails on both.

Verified against all 309 cards: three recover their true payout, no card loses
one, and the two ports agree on every row — pay, minutes and miles — which is a
stronger check than the fixture corpus alone can make.

The other five now report **no payout** rather than a small wrong one. That is
the right answer and not a lesser one: their headline never reached the OCR, so
the reading is incomplete, the panel says so, and the accumulator keeps looking.
A rate of −$7/hr derived from a priority chip is not a smaller error than an
honest blank; it is the same error wearing a number.

Across all 309 cards, with this and the dropped-distance fix together:

| | stored at the time | today |
|---|---|---|
| ACCEPT | 26 | 28 |
| CLOSE CALL | 24 | 14 |
| PASS | 257 | 262 |
| refused as doubtful | 2 | 0 |
| held incomplete | 0 | 5 |

The two doubts are gone because the readings that provoked them are now correct
rather than merely distrusted, and five cards that were being rated off a chip
are now honestly unfinished.

### The red run that was nothing to do with the code

`crop.test.js` failed on a parser change:

    FAIL  the scanner reads back the box this server wrote: got null

It had nothing to do with the parser. The three handoff files live in
`/dev/shm` under fixed names, and `take_request()` *removes* the request as it
reads it — so any other process on the machine that calls it takes this test's
box away. A second checkout, a scanner already running, another copy of the
suite: any of them, and the round trip reads nothing and blames whatever was
being changed at the time. It cost the better part of a debugging session, and
the change it accused was innocent.

That is worse than a missing test. A suite that fails for reasons outside the
code under test teaches you to re-run it rather than read it, and the next real
failure gets the same shrug.

`UBERSCAN_HANDOFF_DIR` now overrides the directory, honoured by `handoffDir()`
in server.js and `_dir()` in `rpi/handoff.py` alike, and only when it names a
directory the process can actually write to — a stale line in a shell profile
must not be able to quietly disconnect the two halves of the rig, so an
unusable value falls back to the rule that was there before. The crop test gives
itself a private directory and hands the same one to both the server it spawns
and the python it calls.

It is not only a test fixture. Two copies of this project on one machine — a
development checkout beside the live rig — have always shared those three
filenames, which means a crop drawn on one screen moves the other one's camera.

`test_handoff.py` already ran the real `handoffDir` out of server.js and
compared it path-for-path with the Python; it now does that under the override
too, because an override only one side honours is exactly the
button-that-does-nothing failure the module exists to prevent. Proved by running
the crop test against a loop hammering `take_request()` on the shared path: it
passes.

### The leg that lost its minutes, and took its distance with it

`legs_short_a_distance` catches a leg that lost its miles. This is its mirror,
and the more dangerous half: **minutes are the denominator**, so a leg dropped
for having none makes the journey shorter in time *and* in miles, and the rate
looks bigger twice over.

Five of the 604 cards, from two causes, and four of the five turn a PASS into an
ACCEPT:

| what the card printed | what happened | the frame alone | the eight frames voted |
|---|---|---|---|
| `$9.05 ★5.00 min (44 mi)` | the star rating sits where the duration goes; `00` reads as zero minutes | **$49.62/hr ACCEPT** | $19.86/hr PASS |
| `$8.07 ★490 ll min (35 mi)` | the minutes spelled entirely in stand-ins | **$35.40/hr ACCEPT** | $15.89/hr PASS |
| `$12.04 … 1 min ll mins (5.4 mi)` | the same | **$40.24/hr ACCEPT** | $19.48/hr PASS |
| `$11.02 ★5.00 min (5.2 mi)` | the rating again | **$59.82/hr ACCEPT** | $45.87/hr ACCEPT |

Both refusals are *right*. `HAS_DIGIT` is correct to refuse `ll min` — "stacked
guesses are how noise becomes data" — and `5.00` is a rating, not a duration.
What was wrong is that **the leg's distance went with them**.

The rule needs no phrase list, because the card already says it: a bracketed
distance belongs to the time printed beside it, which is exactly what `LEG`'s
trailing group encodes. So a bracketed distance sitting outside every leg is a
leg the reader failed on. Zero false positives across the 604 — not on a shop
card's `(6 units)`, not on the distance-first card whose leg keeps its own
distance, not on the `+14 min (+ 2.0 mi)` shape.

And the answer is not to guess the missing time. It is to stop calling the
reading whole: the rig keeps looking, the panel says it has not finished, and a
later frame supplies the leg — which is what already rescued three of these five
at scan time. Five cards go from `whole` to unfinished and nothing else moves.

The flag is **ANDed** across the merge window, unlike everything else in
`accumulate.py`, which ORs. The others ask "did any frame see this?"; this one
asks "has any frame managed to read the whole journey yet?", and one that did is
the answer. Fed the damaged frame twice and the good one once, in any order, the
merge publishes 7.0 miles over 22 minutes and $18.95/hr — the truth — instead of
2.6 miles over 10 minutes and $49.62.

Thirteen mutations, thirteen caught, including a straight revert and both halves
of the merge rule.

### Two screens, one card, two answers

Found by pointing five adversaries at work that had already shipped, with one
instruction: break it. All five landed something.

**The browser doubted a reading it had already repaired.** `rate()` reaches a
verdict with `miles` — the distance after its own recovery pass — and then asks
`doubt()` whether to stand behind it. The Python passed `miles`. The JavaScript
passed `parsed.miles`, the number *before* the repair. On a delivery card with
19 minutes left on the deadline:

    $8.25 Guaranteed (incl. tip)  24 mi  Deliver by 6:05 PM

both ports publish 2.4 miles, charge $0.72 of mileage on 2.4, and print
$23.78/hr — and then the Pi says CLOSE CALL while the browser withholds the
verdict entirely, because 24 miles over 19 minutes is 75.8 mph. Not the cautious
port; the incoherent one. `d4cb918` changed the Python line and touched the
JavaScript file in the same commit without making the matching change, and the
shared corpus missed it by a hair: its fixture for that card sits at 25 minutes,
where the original speed is under `doubt()`'s limit, and asserts miles and cost
but never `state`. It does now.

**A guard failing in both directions at once.** The real-digit rule two sections
up was applied to the lone distance as well, and there it has no backstop:
refusing the token leaves the card with *no* distance, so no mileage is charged,
the rate goes UP, and the verdict is capped. `l.S mi + 25 min` on a $12.50 offer
published **$30.00/hr CLOSE CALL** where the truth is 1.5 miles and a **$28.92/hr
ACCEPT** — a real green light clipped, and the number it was clipped to inflated.
A `1` lost to an `l` or an `I` is this OCR's commonest single confusion.

The amendment is the shape of the thing rather than a longer list: the badges the
rule was written against are bare — `Smi`, `Lmi`, `Imi`, `4, Smi ~ fast charger`
— while a real distance on this card prints a decimal point. A token that kept
its point kept its structure, so it is read; a bare one is still refused. Zero of
the 604 cards change either way; this closes a hole rather than fixing an
observed error.

**And a correction to the section below.** Its first version said this driver's
fastest real offer runs at 43 mph. That was the fastest of one shift's *green*
offers, not of all of them. The fastest confirmed offer on file is 41.4 miles in
47 minutes — 52.9 mph — so `MAX_MPH` at 55 has about two miles an hour of
headroom, not twelve.

The attack that produced that correction also argued the recovery should not fire
between 55 and 75 mph at all. It was tried, and the corpus refused it: `$7.09
34 min (36 mi) total` is a real card at 63.5 mph whose distance really is 3.6
miles, and three long-standing fixtures rest on it. Every *confirmed* real offer
on file sits at or below 52.9 mph, and the one row above the line — 115.6 miles
in 123 minutes — had already been marked uncertain by the rig itself. So
recovery in that band is right for this rig on the evidence available, and the
change was reverted rather than shipped. The exposure is real and stated here
rather than closed: a genuine offer above 55 mph whose distance printed no
decimal would be cut to a tenth of itself.

### One card, filed as five offers

A journal row is an offer the rig finished with. Two rows carrying the same
payout and the same duration a few seconds apart are not two offers a driver was
shown; they are one card whose window closed and re-opened while it was still on
screen. **90 cards in this driver's journal were filed more than once — 104
surplus rows, 7.6% of it**, every one of them counted again in every median on
the offers page, and eleven disagreeing with themselves about the distance. One
`$12.99` card off Dave's Hot Chicken appears three times inside 35 seconds, and
the first copy says 17 miles where the other two say 7.7.

Two mechanisms, and they turned out to be the same root cause as everything else
in this section.

**The leg had nothing to be recognised by.** `accumulate.py` matches a reading
to a leg slot on *either* its time or its distance agreeing — deliberately, and
the reasoning is in `_slot_for`: each field fails differently and neither is
reliable alone. But on the distance-first card the leg carried no distance, so
only exact equality of minutes was left. One frame reading `28 min` as `26 min`
lined up with nothing, `_is_a_different_card` called it a replacement, and the
window reset. Teaching `LEG` the distance-first shape gives the slot its second
signal back.

**The window was a stopwatch, not a silence.** It was measured from the *first*
reading — `now - self.started` — so it expired while the driver was still
looking at the card. The module's own `QUIET` constant already had the right
idea one screen up: *"readings of one card arrive in a burst; a gap means the
burst ended."* A burst is bounded by silence. It now closes after twelve seconds
of nothing.

Measured on one card fed to the real accumulator:

| | today | with both |
|---|---|---|
| 16 frames over 45s, minutes wobbling twice | **5 offers** | **1** |
| 40 frames over 2 minutes, clean | **8 offers** | **1** |
| a different card, same payout, 10 minutes later | 2 | 2 |
| a replacement card, same payout, immediately | 2 | 2 |

The distance is voted on now too, because it rides on the leg: a delivery card
read as 7.9, 7.9, 1.9, 7.9 and 79 miles published the wrong number in 48 of 120
arrival orders and now publishes 7.9 in all 120.

The two that must still separate, still separate — and neither relies on the
clock. A different payout keys differently; a replacement paying the same to the
cent is caught by `_is_a_different_card`, which outranks the window and was
written for exactly that case.

The `LEG` change is a group renumber in both ports, which is the real hazard:
Python's unmatched groups are `None` and JavaScript's are `undefined`, and a
port that misses one index is a silent wrong number rather than a crash. Both
ports agree on all 741 texts on file, every field. **121 of the 604 cards get an
honest leg, and not one published number moves** — no pay, no miles, no minutes,
no flag, no verdict. The distance was always being found; it just was not part
of the leg it belonged to.

Fifteen mutations, fifteen caught, including a straight revert of each half.

### The distance check that ran before the distance arrived

Five lines of code motion, and the largest correctness change in this file's
history by the number of readings it rescues.

`check_distance` sat above the `LONE_MILES` branch. On every card whose distance
the *legs* do not carry — which is the delivery card this driver is mostly shown,
`8.0 mi + 25 min`, where the `25 min` half is a minutes-only leg and the distance
arrives a few lines below — the check ran while `miles` was still `None`,
returned immediately, and the distance was then set **after the last thing that
could have looked at it**. And then stamped `milesChecked: True`, whose own
comment claimed the check had already run against the legs' own minutes. It had
not. That flag also gates `rate()`'s second attempt at recovery, so the false
stamp shut the other door too.

**140 of the 604 cards on file take that path.** Five of them are damaged, and
were being published at 98, 117, 157, 196 and 2220 mph — three at a *negative*
dollars per hour, because the phantom distance ate the whole fare as mileage
cost:

| what the card printed | before | after |
|---|---|---|
| `+21 min (+55 mi) total` — a real Applebee's run | 157 mph, −$26.89/hr, refused | 5.5 mi, **$15.54/hr** |
| `+23 min (+75 mi) total` | 196 mph, −$40.25/hr, refused | 7.5 mi, **$12.57/hr** |
| `+18 min (+35 mi) total` | 117 mph, −$14.93/hr, refused | 3.5 mi, **$16.57/hr** |
| `+8 min (+13 mi) total` | 98 mph, $4.50/hr, refused | 1.3 mi, **$30.83/hr — an ACCEPT** |
| `74mi+-thr2min` | 2220 mph, cost $22.20 charged | distrusted, uncosted, still refused |

And the class, not just the instances. Strip the decimal from the distance of
every card that takes the lone path and ask what each version does:

| | repaired | refused outright | silently wrong |
|---|---|---|---|
| before | 0 | 115 | 13 |
| after | **119** | 0 | 9 |

A lost decimal on the driver's dominant card format meant *no verdict at all*,
115 times over. It now means the right number, 119 times.

**It is code motion and nothing else.** `check_distance` never returns `None`,
so the `miles is None` test in the branch above is unchanged by moving the call
below it, and every card whose distance came from a leg gets the identical
answer. Measured twice: all 604 cards clean, zero differences; and again with the
decimal stripped from all 462 leg-borne texts, zero differences. Twelve
mutations, twelve caught.

**What it costs, stated plainly.** It extends the divide-by-ten recovery to the
lone-distance path, and that is the optimistic direction — the one this project
cares about most. A genuine long haul whose decimal the camera lost is now
silently shortened: `$45.00 ... 60 mi + 55 min` is 60 miles and $29.45/hr today
and becomes 6 miles and $47.13/hr, with $16.20 of real mileage cost gone. Three
things bound it, and none is a proof. The card prints the decimal on 131 of the
140 lone-path cards, and `60.0 mi` is refused. `MAX_MPH` is 55; this driver's fastest
*confirmed* offer runs 41.4 miles in 47 minutes — 52.9 mph — so the headroom is
about two miles an hour, not the twelve an earlier version of this section
claimed. (The 43 mph figure quoted there was the fastest of the shift's *green*
offers, not of all of them.) One journal row does sit above the line, 115.6
miles in 123 minutes at 56.4 mph, and the rig had already marked its distance
uncertain.
And zero of the 604 cards land in the 55–75 mph band where a lost decimal is
neither recovered nor doubted. It is the same exposure `recover_decimal` has
always carried on the time-first format, where it fired 36 times and was right
every time.

**Why the fixtures came with it.** All 27 lone-path texts already in the corpus
sit far below `MAX_MPH`, so every one of the 573 checks passed identically with
and without the motion — the suite could not have caught a revert. Six new cases
pin it: the real Applebee's card, the same delivery card damaged and undamaged, a
believable whole-number distance that must *not* be divided, one too far gone to
divide that must be doubted rather than charged, and a distance that printed its
decimal being believed at 60 mph.

**What it does not fix,** because the same audit measured these and they stay
open: `legs_short_a_distance` still fires zero times on all 604 cards; the
accumulator still does not vote on a lone distance, so the $15.60 GoPuff card
still publishes 1.9 miles in two of six arrival orders; and a lone distance that
reads too *small* is still unguarded in both versions, since `check_distance`
only ever divides.

### The ACCEPT that was a road

The rig photographs whatever is on the phone, and between jobs that is the map.
One screen off this driver's own shift, read as an offer:

    The Townes at Chastain ... Windsor Drive ...
    3min   8   11 min   $ 22min   &   Ti min   3 min (1.0 mi)
    Fastest route now due to traffic conditions   Saves gas   Add stops   Share

Route alternatives, with a map glyph in front of one of them that read as a
dollar sign. `find_pay` took **$22**, the four durations summed to 39 minutes,
and the panel showed a green **ACCEPT at $33.38/hr — for a road**. It went into
the journal as an offer and into the medians as a rate. Its door-to-door speed
was 2 mph, against a median of 17 for the shift's real offers.

No list of screens, and no attempt to decide what an offer "looks like": that
road was found by asking what the *payout* is, and a payout is never glued to a
unit. A card says what its money is — `Guaranteed`, `Includes expected tip` — or
says nothing, and the ride cards say nothing at all: 231 of the 604 print no such
word, so a rule keyed on the label would have thrown away a third of the shift.

The narrow version is the shipped one. Only the abbreviations these screens
print — `min`, `mins`, `mi` — and not the spelled-out forms `LEG` tolerates,
because a merchant is exactly what sits beside a payout when the label between
them does not read, and `$12 Minute Maid Park` would otherwise lose its payout.
`Mi Casa` is the collision that remains, and it fails in the safe direction: no
payout, so no verdict, rather than a wrong one.

The test of whether it is narrow enough is a real card off the same shift:

    $13.05  *% 493  © Verified   $ 12 min (6.3 mi)   Paces Ferry Rd NW, Atlanta

A stray glyph in front of the leg, on an offer the driver actually took. The $12
is refused and the $13.05 headline is untouched. One card in 604 changes — the
map stops being an offer and becomes an unfinished reading, which is what it is.
Eleven mutations, eleven caught.

**43 of the shift's 49 green lights survive a re-read and a speed check.** The
six that do not are the two priority chips, the two `$ Bound Ct` phantoms, this
road, and one card where a star rating ate a journey leg. The driver took none
of them.

### A street name that read as an eighty-dollar offer

`DC` is the parser's list of characters OCR swaps for digits — `O` for 0, `S`
for 5, `B` for 8. It exists so a number that lost one character to the lens is
still read as the number it is, and that is right. What it did not say is that a
token made ENTIRELY of those stand-ins is not a number missing a character. It
is a word.

Off a real card, two lines under the headline:

    $9.03 Guaranteed (incl. tip)  30 min (10.8 mi) total
    Doro's Italian Restaurant (Acworth)   $ Bound Ct & Shoals

`B` reads as 8, `o` reads as 0, and **"$ Bound" became an $80.00 payout**. The
largest dollar figure wins, so a $9.03 delivery was published at **$153.52/hr,
ACCEPT** — the highest-rated green of that shift. The dollar sign was real. Every
digit after it was a guess.

The rule was already in the file, one function away, in these words: *"the number
in front of it has to contain a real digit. 'SI min' is two guesses stacked, and
stacked guesses are how noise becomes data."* Durations had it. Money never did.

It now applies to the payout, to **both halves** of a rejoined split headline —
`$S 8.75 Guaranteed` would otherwise glue a guessed `S` to a confirmed `8.75` and
invent $58.75 — and to a lone distance, where `4, Smi ~ fast charger` off a real
card reads as five miles.

Two cards in 604 change, both from the phantom $80 to their true $9.03 and from
ACCEPT to PASS. No corpus text moves. Ten mutations, ten caught — and one of
them, "the split rule checks only the cents half", survived the first pass and is
the reason the `$S 8.75` case exists.

**Not applied to a leg's distance,** and the reason is worth keeping. Refusing
`(SO mi)` leaves the leg with a time and no distance, and on a single leg the
card labelled `total` that reading calls itself *whole*: no distance means no
mileage charged, so `$12.45 20 min (SO mi) total` goes from $32.85/hr with a
distance to **$37.35/hr without one**, unflagged, and into the medians. Today the
same token becomes 50 miles, which `check_distance` catches as 150 mph and pulls
back. A guard that turns a caught error into a silent one is not a guard. The
honest fix is for a leg that lost its distance to stop the reading being whole,
which `legs_short_a_distance` does for two legs and cannot do for one — and that
belongs with that work.

### One payout, read as two numbers, filed as two offers

The headline is the biggest type on the card, and the crop's own edge runs
through it. The space between the dollars and the cents comes back wider than it
is, and `$18.75` arrives as `$1 8.75`. `find_pay` reads the largest dollar
figure it can see, which is **$1**.

Nine of the 309 cards on file, four distinct offers:

| what the card said | what the panel said | verdict shown | verdict owed |
|---|---|---|---|
| $25.60, 36 min, 8.3 mi | $2 | PASS, −$0.82/hr | **ACCEPT, $38.52/hr** |
| $18.75, 39 min, 18.0 mi | $1 | PASS, −$6.77/hr | PASS, $20.54/hr |
| $15.60, 37 min, 7.9 mi | $1 | PASS, −$2.22/hr | **CLOSE CALL, $21.45/hr** |
| $10.40, 40 min, 12.1 mi | $1 | PASS, −$3.95/hr | PASS, $10.16/hr |

The first row is a real green light the driver never saw. But the worse fault is
the one in the middle column: **some frames of the same card read the headline
whole and some split it**, and the accumulator keys a card by its payout. One
physical offer files as two, and the panel alternates between two verdicts while
the driver is looking at it — one card in the export flickers between $28.85/hr
and $1.54/hr five times in seventeen seconds.

The halves are only put back together where **the card's own label follows** —
`Guaranteed`, `Includes expected tip`. That is the whole safety of it, and the
direction of the danger decides the design: a fabricated payout is a *larger*
number, and a larger number is a green light. Gluing on digits alone would read
`$8 5.00`, where the 5.00 is a star rating, as an eighty-five dollar offer.

Two things the rule refuses, both from the same reasoning:

- **Only a plain space may sit between the halves**, because that space *is* the
  defect — one number printed with too wide a gap. Anything else between them
  means they are two things. Let the gap hold four characters of slack and 60 of
  the 420 texts on file change what they match.
- **A chip split the same way is still a chip.** `+$5 0.00 included` over a real
  $13.08 headline is the same fifty-dollar lie as `+$050 included` two sections
  up, so `PAY_CHIP` had to learn the split form too — otherwise the rule that
  rejoins numbers hands the chip straight back as the payout. That was a real
  defect in the first draft of this, caught by mutation rather than by a card.

Fourteen mutations, twelve caught. The two survivors are equivalent, and
provably rather than by inspection: allowing the gap to be empty only ever
re-reads a number `MONEY_STRICT` already read to the same value, and widening
the dollars half past three digits can only produce five integer digits, which
is above the sane bound in every case.

Across the 309: nine cards recover their payout, **no card's payout changes that
was already right**, and none of the 140 texts in the shared corpus matches at
all.

### The ACCEPT that was made of a missing deduction

202 offers off one real shift, and the arithmetic behind every verdict in it:

| | offers | median $/hr | ACCEPT |
|---|---|---|---|
| a running cost was charged | 94 | $12.03 | **2** |
| none was charged | 108 | ~$23 | **33** |

The target is $25. So **53% of the shift was rated with no running cost at
all**, and that is where all but two of the ACCEPTs came from. Twenty of the
thirty-five fall below the target once the distance printed on the card is
charged — a floor, not an estimate, because on those rows the distance itself
is partial.

The mechanism was one line, and the flag feeding it was right. When a leg loses
its miles, `legs_short_a_distance` marks the reading, and its docstring names
the danger exactly: the error "errs optimistic, which is the one direction that
turns a pass into an accept." Then `rate()` answered that flag by charging *no*
mileage at all — optimistic again, by a second route. The comment on it said
falling back to gross "overstates the rate slightly". On this shift that
overstatement ran to a **median of 30%, a p90 of 173% and a maximum of 334%**.

`target` is a net line. A rate with no cost off it is a **ceiling** on the
offer, not the offer, so it cannot be compared to that line. The verdict is now
capped at CLOSE CALL rather than the number being withheld: the driver still
sees the rate, the addresses and the arithmetic, and decides. What they no
longer get is a green light the arithmetic cannot support. Replayed over the
same 202 offers, ACCEPT goes from 35 to 2, thirty become CLOSE CALL, three stop
getting a verdict at all, and **nothing that was a PASS moves**.

**What it still cannot do.** The cap stops an upper bound earning an ACCEPT; it
cannot stop it reading a band high. $16.05 over 34 minutes and 33.7 miles is
$10.48/hr costed and $28.32/hr uncosted — a clear pass showing as a close call,
and no cap fixes that while the number is still on screen, because that number
is all the rig knows. `test_money.py` asserts the guarantee that holds and
counts the residual rather than hiding it. Shrinking it means charging the
*partial* distance instead of none: where a leg's miles are missing the sum is
an under-estimate, so charging it tightens the bound rather than inventing
anything. That is a change to the cost model, and it is the next one to make.

### A distance nobody could check

A delivery card states a distance with no time beside it. `check_distance` needs
a denominator to work — losing the decimal in "3.6 mi" is caught because it turns
a 6 mph errand into a 63 mph one — so with no minutes it returned the number
untouched, unflagged, and a lost decimal went straight into the running cost.

**2.4 mi read as 24 mi is charged $7.20 of mileage instead of $0.72.** $18.1/hr
becomes $2.5/hr, with nothing on any screen saying the distance was doubted. A
ride card never had this hole, because its legs carry their own minutes.

The machinery was always there and unreachable. `check_distance(25, 24.0,
had_decimal=False)` already returns 2.4 and says it corrected it — it just needs
a denominator, and for a delivery card that is the time left until its deadline,
which is worked out in `rate()` because it needs the clock. So the re-check
happens there, and `rate()` now returns the distance it actually judged with, the
way it already returns the minutes it judged with and for exactly the same
reason. The journal and the panel take it from there, so a row cannot record 24
miles beside a rate worked out over 2.4.

Two guards make it safe, and each was found by a check failing rather than by
foresight.

**A printed decimal is not "recovered" away.** The fact is lost the moment the
string becomes a float — "10.0 mi" and "10 mi" arrive identical — so the token's
own punctuation is carried through `parse()`. Tested where it decides the
answer: 60.0 miles with 25 minutes to run is 144 mph, so the recovery *would*
fire and make it 6.0, and the printed point is the only thing stopping it. The
first version of that fixture used 10.0 mi at an ordinary speed, where
`check_distance` never reaches the recovery at all and the guard was doing no
work — the mutation walked straight through it.

**An absent flag means leave it alone.** `milesChecked` says the parser had
nothing to check the distance against. A caller building the reading by hand —
the keypad, a test, an old row being re-rated — has no such key, and reading its
absence as "not checked" let `rate()` recover a decimal from a distance that had
already been checked, or typed: a hand-entered **115 miles over 63 minutes came
back as 11.5**, and the speed doubt that should have fired never did. It is an
explicit `is False` now, and `test_money.py` pins it.

### A guard a shorter trip walks under

`SANE_RATE_OVER_MINUTES` was written as a boundary and implemented as two
branches, which made it a **step**. Below ten minutes nothing applied but
`SANE_PAY`'s own $300 ceiling, so:

| | verdict |
|---|---|
| $136 over **10** minutes | doubt, $810/hr |
| $136 over **9** minutes | **ACCEPT, $899/hr** |

$300 over three minutes was a green ACCEPT at $6000/hr. A guard a shorter trip
walks under is not a guard.

It is one expression now — `pay / (max(minutes, SANE_RATE_OVER_MINUTES) / 60)` —
so the ceiling never loosens as the duration shrinks. Below the boundary that is
a flat cap on the **pay**: $33.33, the payout that reaches `SANE_RATE` at ten
minutes. It refuses none of the 568 real offers on record — the largest under
ten minutes is $5.00 — and no corpus card that was not already wrong.

**And it caught something the investigation said no bound could.** One verifier
concluded the fix was orthogonal to the failure OCR actually produces and that
the honest change was presentation instead. A challenger refuted that with a
card sitting in this project's own corpus: `$47.53 9 min (3.1 mi) trip 53L min
(18.6 mi) away`. The second leg reads as rubbish and is correctly dropped, which
leaves the nine-minute pickup leg carrying the whole payout — parsed complete,
`is_whole` False, and rated **ACCEPT at $310.67/hr where the truth over 62
minutes is $46**. The continuous ceiling catches it. A lost leg makes pay,
minutes and miles each individually plausible; it is the rate they imply
together that cannot be true.

Both were right about different things. Some lost legs clear the cap and are
caught; the one the pictures produced — $16.05 over 4 minutes, $241/hr — sits
below the $300/hr the corpus pins as an ordinary short hop, and no ceiling can
have both. That one belongs to `whole`, below.

### The panel in the car did not hedge

`live.html` computes `settled = r.locked && r.whole !== false` and appends a
"?" to the verdict when a reading is a fragment. `render_panel` — the OpenCV
panel actually bolted to the dashboard — never saw `whole` at all, so the same
reading the web page qualified showed in the car as a flat green ACCEPT. The
loop already had the value: it computes `whole` and hands it to the resample
burst, to `emit`, to the voice and to the journal. The panel was the one
consumer left out.

It arrives as an argument rather than being recomputed, because `is_whole` has a
deadline branch — a delivery card is legitimately whole with no legs at all, and
a panel restating the test from the legs would qualify every delivery card the
rig reads. It defaults to `True`, so a caller that does not know cannot cast
doubt on a reading that never earned it.

The same pass found `DOUBT_LABELS` had no entry for `rate`, the reason added
with the ceiling above — so a card the other two screens named as CHECK PAY AND
TIME fell back to READ AGAIN on the one screen where the driver cannot go and
look it up. `test_scan_pi.py` now derives the reasons from the parser's own
source and asserts the panel has a name for every one, so the next reason cannot
be forgotten either.

### The second look that could not happen

`_look` takes a second OCR pass in a different page-segmentation mode when the
first found no payout. It was gated on the reading having minutes — and a
delivery card never has any. Over **591 rendered delivery reads it fired zero
times**, against 10% of ride reads and 13% of shop reads: dead code for one of
the three card shapes the rig supports. Widened, it fires on 3.7% of delivery
reads and recovered the payout on 8 of them, every one correct, with no wrong
read introduced.

Two details decided it, and neither was in the original proposal.

**`is not None`, not truthiness.** `deliverBy` is minutes since midnight, so a
card saying "Deliver by 12:00 AM" carries **0** — falsey. The truthiness test
would have left the block dead through the one hour it is most likely to be
read, on a rig whose recorded shift ran to half past two in the morning.

**The agreement check had to be tightened in the same commit.** Its job is that
a second opinion which also rewrites the journey is a different reading, not a
recovered payout. On a ride card it pins the two numbers the rate is made of. On
a delivery card `minutes` is None on *both* sides — degenerate on 591 of 591
reads — so `miles` alone was carrying it, and on 2 of the 22 firings miles was
None on both sides too: **nothing at all anchoring the swap**. Meanwhile the
deadline, which is what `rate()` divides the payout by on this card shape, was
the one field left free to move. A retry shifting 7:15 PM to 9:15 PM turns
$49.79/hr into $13.80/hr; to 6:45 PM, into a confident $143/hr. Widening the
gate without closing that is the one ordering that makes the rig worse.

Both are named functions now — `worth_a_second_look` and `second_look_agrees` —
rather than expressions inside a method that needs a camera frame to reach. The
first version of their tests re-implemented the gate beside the assertions, so
the only thing tying test to code was a string search for the source line: a
mutation to the gate could fail the grep but never the behaviour. A check that
cannot fail on behaviour is not checking behaviour.

### $816 an hour, on a card that said $1.36

Five readings that shift reached the panel as ACCEPT at between $103 and $816
an hour. `doubt()` checks the payout against a sane range, the duration against
a sane range, and the two together against a sane speed — and **nothing checked
the pay against the time**. $136 is inside `SANE_PAY`, ten minutes is inside
`SANE_MINUTES`, and $816/hr is a decimal point that did not survive the read.
The same card read correctly elsewhere in the file says $1.36.

The first version of the check was a flat rate ceiling, and the corpus refused
it — correctly. **$/hr is unbounded as the duration shrinks**: $10 for a
two-minute half-mile hop is $300/hr and is an ordinary offer, which the corpus
has held since long before this. A ceiling that clips a real offer is the same
failure as one that lets a misread through, pointed the other way. So the
ceiling applies only above ten minutes, where a rate describes the card rather
than a tip dominating it: over $33 for ten minutes, $100 for thirty, $200 for
an hour. None of which these apps pay.

It is its own reason, `rate`, rather than a variant of `pay`, because the pay
may be right and the time wrong — and "check the payout" would send a driver to
the wrong half of the card. The panel says **CHECK PAY AND TIME** and withholds
the rate.

### A rate with no running cost taken off it

`rate()` charges no mileage at all for a distance it does not trust, which is
the right call — costing a journey on a number that was misread invents the
correction as well as the distance. The consequence is that such a row's `$/hr`
is a gross figure, and on a rig with a cost per mile it sits in the list a few
dollars above where it belongs.

Nothing the scanner writes today lands there. Every route to `milesUncertain`
also trips `suspect` or `whole === false`, both already excluded from every
figure, and `test_journal.py` asserts that as a property rather than trusting
the coincidence. This is about the rows already on disk.

Until 19 August the two thresholds were different numbers reached by different
reasoning in different parts of `offer_parser.py`: a distance was distrusted
above `MAX_MPH`, 55, and a reading called suspect above `SANE_MPH`, 75. Every
journey computing between the two — a real highway run, or a misread landing in
that band — was written distrusted, **not** suspect, and whole. Those rows are
indistinguishable from clean ones to every test that came after, and each of
them pulls the median, both quartiles and the recommended line upwards.

`Advice.trustworthy` excludes them now, guarded on the row's own
`costPerMile`: at zero nothing was ever deducted from anything, so a cost-free
rate is not out of step with its neighbours and dropping it there would be
throwing away a perfectly good offer for a difference that does not exist. The
offers page explains such a row rather than listing it silently.

### Three sentences on the offers page that were not true

**Two percentages of two different totals, side by side.** The headline read
"At $25/hr, 52% of 48 offers cleared the line — though only about 38% were
yours to take". The first figure is over every usable offer in the range. The
second is `Advice.replay`'s, over only the offers that fall inside a run of
scanning, because `runs()` drops the rest — on the sample above, 13 of the 48.
A reader subtracts them, and gets a number about nothing. Both are counts now,
each printed next to the total it is out of, and the replay gets its own
sentence rather than hanging off the first with a "though", which is what made
it read as a correction to the figure before it. `replay()` returns `seen`
alongside `takes` so the denominator can be stated rather than implied.

**A gross total in a page of net ones.** "You marked 6 as taken, worth $342.10
at a typical $34/hr" summed the payouts. The `$34/hr` beside it is after
running costs, the note at the foot of the page says "Rates are after $0.35/mi
of running costs", and every other figure on the page obeys that. Now this one
does too — and only claims to when something was actually subtracted, since
with costs set to zero the two totals are the same number.

**"No rate could be worked out from this reading" — printed under a rate.**
A row is set aside if it is hidden, suspect, or not whole. The explanation had
a branch for each of those but hidden, so a row the driver had hidden
themselves fell through to the generic last line, two lines under its own
perfectly good `$/hr`. It is the one row on that page whose absence from the
figures is explained by something the driver remembers doing, and it was the
one given no explanation.

While there: a chart of one bar is not a comparison. "Rides and shop orders"
drawn over a single row labelled "Not stated" tells the reader nothing, twice.
That section and the time-of-day one now go when there is nothing to compare,
instead of leaving a heading over an empty box that reads as a chart which
failed to draw.

### Three files, and where they live

The browser asks the camera side for three things, and each is a file:
`.viewing` (somebody is watching, and which of the two views they want),
`.recalibrate` (forget where you think the phone is), `.cropbox.json` (read
this box, drawn by hand). Files rather than a socket or a signal, because the
scanner is sometimes a child of the web server and sometimes a systemd unit
that has never heard of it.

They lived in `rpi/`, on the card. Everything about them says they should not:
each exists for seconds, none should survive a reboot, and once `.viewing`
started carrying which view the driver wants, the web side began rewriting it
about once a second for as long as a browser was fetching frames. The live
frame moved to `/dev/shm` for exactly this reason and these were left behind.
They are there now — `uberscan-viewing`, `uberscan-recalibrate`,
`uberscan-cropbox.json` — with the aiming picture and the OCR staging images.

**Found by a rule, not by a list.** The live frame can afford to be sloppy
about this: `framePath` in `server.js` takes whichever candidate is freshest,
which is right either way because one side writes it and the other reads it.
These are handshakes. A request written where the reader is not looking is not
a stale picture — it is a button that does nothing and never says so. So both
sides answer the same question the same way (is `/dev/shm` a directory this
process may write in?) and get the same answer, because they run as the same
user: the unit's `User=` is the account that installed it, and otherwise the
scanner is the server's own child. `rpi/handoff.py` holds the Python version,
`server.js` the JavaScript one, and `rpi/test_handoff.py` runs both and
compares the answers character for character.

The readers still look in the old place too, and clear both. Upgrading is a
`git pull` that moves both sides at once, but the scanner is a long-running
process and the web server is restarted far more often, so on one machine the
two really can be minutes apart — and a request left lying in the other
location would be adopted whenever the scanner next restarted, moving the crop
or throwing away a good calibration hours after it was asked for.

The aiming picture came along too. `autopilot.py` wrote it to `rpi/` while the
scanner it hands over to wrote to RAM, so the web side had two candidates to
choose between by mtime when it should only ever have had one — and the picture
a driver aims the mount by was a different file from the one they watch offers
on.

### Getting them off the car

#### A copy that cannot be read is not an empty copy

The far end de-duplicates by building a set of what it already holds, which is
what makes an upload idempotent and is the reason a timer can run it every ten
minutes. Those rows came from a reader that answered `[]` to **every** error —
including a journal that is there and cannot be read. An empty set makes every
incoming row look new.

Reproduced against the real server, running as a user that could append to the
journal but not read it, which is the one shape that reaches this (every error
that also breaks the append is already refused loudly):

```
GET  /api/journal/newest  ->  {"ok":true,"newest":0,"have":0,"offers":0}
POST /api/journal/ingest  ->  {"ok":true,"added":20,...}      x3
lines on disk (started 20): 80
```

Sixty duplicate rows, `ok: true`, and a `have` that is wrong. And `newest: 0`
disables the repair as well: the rig computes no shortfall, falls through to a
thirty-day floor, and re-sends a month of offers every ten minutes for as long
as the fault lasts — with both ends reporting success the whole time. The only
backup quietly filling with copies is the exact failure the sync design lists
first among the ones it must not have.

`ENOENT` is still "nothing recorded yet". Anything else now says so:

* **ingest** refuses with 500 rather than appending what it cannot de-duplicate.
* **newest** still answers `200`, and still says what the build `can` do — a rig
  told nothing about a reachable machine goes on to blame it for being out of
  date — but it reports `readable: false` and offers no number at all, because
  the number is what triggers the thirty-day re-send.
* **the rig** declines to send, on stderr rather than through `say()`, and exits
  non-zero. `--quiet` is for the routine chatter of a ten-minute timer; this is
  a standing fault at the other end, and it is the one the install gate has to
  catch, since a backup that cannot merge is not a backup.
* **the offers page** still renders, but says `The journal could not be read` —
  an empty history and an unreadable one look identical otherwise, and only one
  of them is worth acting on.


The journal is the only thing this rig produces that cannot be made again. The
scanner can be reflashed in an afternoon; a year of what the work actually paid
cannot. Until there is a second copy it lives on one SD card, in a vehicle,
which is the least durable place in the system.

So `rpi/sync.py` pushes it to a machine that stays at home. That machine runs
**this same server** with the camera side switched off:

```sh
# on the machine keeping the copy
SCANNER=0 JOURNAL=/var/lib/uberscan/journal.jsonl npm start
```

`JOURNAL` wants to point *outside* the checkout — left at the default the copy
lands in `rpi/journal.jsonl` inside the clone, which works but stands your only
backup next to a `git clean`. The directory is created if it is not there, and
`config-backup.json` lands beside it.

`SCANNER=0` is not optional on that machine. Without it the server tries to
start the camera scanner, fails on the missing picamera2, and restart-loops
every few seconds forever — harmless to the ingest endpoint but a spinning child
process and a log full of nothing.

That is the whole install. `SCANNER=0` is already a supported mode — it exists
so the site keeps working when the camera does not — and it gives the offers
page, the JSON API and the CSV export with no camera, no picamera2 and no OCR.

```sh
# on the rig
cd ~/Uber_Scan && git pull
bash tools/install-sync.sh http://nuc.lan:8080
```

That works out where the checkout is, which account owns it, and where python3
lives, rather than assuming any of them — **and it runs the sync once before
installing anything.** If that fails it stops and says why, because a timer that
has never succeeded once is a timer that fails quietly forever.

The first version of this shipped ready-made unit files with `User=pi` and
`/home/pi/Uber_Scan` written into them. That is the default on a fresh Raspberry
Pi OS image and wrong the moment anyone names their account something else — and
it fails at `systemctl enable` with a message about a missing unit file, which
points nowhere near the actual problem.

```sh
systemctl list-timers uberscan-sync.timer    # when it next runs
sudo systemctl start uberscan-sync.service   # run it now
journalctl -u uberscan-sync.service -n 20    # what it said
```

**The rig pushes; nothing pulls.** A car is behind cellular NAT and cannot be
reached from outside, so the direction is not a preference. It also means the
sync works the same on the driveway and on the motorway rather than only when
parked — *if* you give it an address that works from the road. A Tailscale or
WireGuard name does; a `192.168.x.x` one only syncs when the car is at home,
which is the one time the data was never really at risk.

**It is idempotent, and that is the entire design.** Every row can say what makes
it itself, and the far end appends only what it has never seen — so the same
batch can arrive twice, or ten times, and nothing duplicates. There is no stored
offset to drift out of step, no resume logic, and no state on the rig beyond the
journal itself. A connection dropped half way through costs nothing: the next run
sends the same rows again and they land. The sender is allowed to be crude
because the receiver cannot be fooled.

A reading of an offer is identified by its `id` and `seq` — a better read of a
card already seen is the same id at a higher seq. **The rows you make by hand are
not shaped like that**, and for a while they did not cross at all: a mark ("I
took this one") has an id but no seq, and a rule ("stop showing me my own test
card") has neither, because on the machine that writes them there is one journal
and nothing to de-duplicate against. Every tag was refused and counted under a
`malformed` total nobody reads, while the offers around them went across and the
copy looked complete. A note is now identified by when it was written and what it
said — both fixed when it lands on disk, neither ever rewritten — so tags already
sitting in a journal cross over on the next run without anything being changed.

A row of a `kind` the receiving build has never heard of is carried across rather
than dropped, as long as it can say which row it is. The copy is meant to outlive
the build that filled it.

Each run asks what the far end already has and sends from an hour before that.
The overlap is deliberate — two machines do not share a clock, and a row can be
written while a request is in flight. Re-sending an hour costs a few kilobytes;
missing a row loses an offer permanently.

**Being out of range is not a fault.** A car is offline most of the time, so a
failed connection prints one line and exits 0. A timer that reports a problem
every ten minutes for a normal condition is a timer nobody reads. A *refusal* —
a token that does not match, a body over the cap — exits non-zero, because
retrying will not fix it.

There is no authentication by default, on the assumption that the machine
keeping the copy is somewhere only you can reach — a LAN, or behind a VPN. If
that stops being true, set `SYNC_TOKEN` on the far end and pass `--token` from
the rig, and the ingest endpoint starts requiring it. Unset, it costs one
comparison. Note that this is the only part of the project that accepts writes
from off the machine; everything else is a read.

`config.json` goes across too, into `config-backup.json` beside the journal —
400 bytes holding the corners, the lens, the flicker-safe exposure and your own
target and running costs. None of it is irreplaceable the way the offers are;
every number can be measured again. But re-aiming a camera and re-deriving an
exposure at the roadside is an afternoon, and it is small enough that there is
no reason to make anyone spend one. It is written only when it changes, and
something that is not a calibration is refused rather than stored — a backup
that cannot be restored is worse than none, because it is believed.
`--no-config` turns it off.

## Tuning

```sh
python3 rpi/bench.py --image some-frame.png
```

Sweeps warp heights, crops and read sizes on your hardware and prints where
reading breaks. Take the smallest warp height that still reads and leave margin.
The `read size` rows show what scaling the card up before OCR costs and buys;
`as-is` is the old behaviour, and it is worth seeing the difference on your own
frames rather than taking the table above on trust.

If reads fail in the car but the preview looked fine, the usual causes are, in
order: glare across the card, exposure too short (raise `--exposure`; below
~10000µs OLED dimming shows as dark bands), and focus (`--lens`, in dioptres —
4.0 is 25cm, 3.0 is 33cm).

## One offer, several looks

A single frame is not always a complete read. Glare across one line or a blink
of defocus can cost a leg, and a card listing a pickup *and* a trip then reports
only the half that survived — which reads as a shorter, better-paying job than
it is. On a real card that difference was $25.90/hr against $20.51/hr: at a $25
target, accept versus pass.

So readings of the same offer are merged over a short window. The pay is the
key — a different payout is a different offer, and the window resets rather than
lending one card's distance to another. Legs are identified by their distance,
so re-reading the same leg does not add it twice; only a genuinely different leg
extends the total. Where two readings of one leg disagree, the more frequent
wins, and a tie takes the shorter time, which errs towards making an offer look
worse rather than better.

This needs more than one look, and the motion gate only fires once per card
because a card sitting still is not a change. After anything with a payout is
read, the scanner therefore keeps sampling for a few seconds. Reads report
`legs` and `mergedFrom` so a merged answer is visible as one.

## Correctness

All of it, in one command:

```sh
npm test                # all 30 suites, 4064 checks
npm run test:quick      # ...minus the two that run tesseract
```

That command did not exist for a long time. `npm test` ran the three JavaScript
suites and the Python ones could be run only by knowing to loop over
`rpi/test_*.py`, so the eight hundred checks covering the camera, the reader,
the tracker and the money were in practice run by whoever remembered them.
`tools/test.sh` runs the lot, prints a line each, and exits non-zero if any of
them fails.

The Pi parser is a port of the browser one, and both run the same corpus:

```sh
node tests/corpus.test.js       # 592 checks, the shared corpus
node tests/parser.test.js       #  83 on the browser side alone
node tests/advice.test.js       # 122 on what line to tell a driver to draw
node tests/crop.test.js         #  16 on the trip from a drag to a crop box
python3 rpi/test_parser.py      # 625 — the same corpus, plus the Pi's own
python3 rpi/test_accumulate.py  # 132 on merging readings across frames, on a
                                #     recovered leg staying recovered, and on
                                #     one address read twice staying one place
python3 rpi/test_pipeline.py    # 227 on where to look, how big, what to log,
                                #     and the two pictures the live view sends
python3 rpi/test_exposure.py    # 133 on flicker, brightness, gain and
                                #     exposure, and on both ends of running out
python3 rpi/test_track.py       # 122 on following the phone as it drifts
python3 rpi/test_journal.py     # 172 on keeping one row per offer, and on a
                                #     distrusted distance always saying so twice
python3 rpi/test_repeats.py     #  54 on one card read many times
python3 rpi/test_calibrate.py   #  54 on what calibration may overwrite, and
                                #     which frame it is allowed to write from
python3 rpi/test_cropbox.py     #  32 on a box drawn by hand
python3 rpi/test_money.py       # 255 from a picture of a card to a $/hour,
                                #     and on a rate with no running cost off
                                #     it never earning an ACCEPT
python3 rpi/test_scan_pi.py     # 210 on the loop that holds the camera, on
                                #     which live view it is being asked for,
                                #     and on one card being named once however
                                #     many times it is read
python3 rpi/test_sync.py        #  84 on getting the offers off the car, and
                                #     on a far end that cannot read its own copy
python3 rpi/test_scanjs.py      #  53 on the phone's own scanner, through a
                                #     real browser (skipped without Playwright)
python3 rpi/test_liveview.py    #  84 on the picture the driver watches, on
                                #     nothing else being served with it, on the
                                #     dashboard layout being wired up, on which
                                #     of the two views was asked for, on the
                                #     offer a reopened tab can still mark, and
                                #     on one shift's figures being counted the
                                #     way the offers page counts them
python3 rpi/test_watchdog.py    #  15 on a scanner that runs without working
python3 rpi/test_autopilot.py   #  37 on the one command that takes the rig
                                #     from nothing to scanning, and on the
                                #     branch that used to brick it
python3 rpi/test_keypad.py      #  48 on the fallback input path, driven
                                #     through a real browser one key at a time
python3 rpi/test_lint.py        #  50 on the faults that only surface when a
                                #     cold branch runs, and on nothing the rig
                                #     writes being committable (flake8 optional)
python3 rpi/test_handoff.py     #  37 on the three files the browser and the
                                #     camera pass requests through, and on both
                                #     sides finding them in the same place
python3 rpi/test_service.py     #  27 on the systemd unit the installer writes
python3 rpi/test_camera.py      #  34 on which tuning file opens the camera, and
                                #     on who is already holding it
python3 rpi/test_doctor.py      #  30 on the preflight running to the end, and
                                #     on slower not being reported as broken
python3 rpi/test_tesseract.py   # 116 on the kept OCR engine reading exactly as
                                #     the spawned binary did, and on every way
                                #     it can fail ending with the rig reading
python3 rpi/test_dashboard.py   # 218 on what the driving screen shows while a
                                #     card is being read, after, once the card
                                #     has gone and only the driver knows they
                                #     took it, and on the shift figures saying
                                #     words rather than a number whenever one
                                #     would be wrong (skipped without
                                #     Playwright)
python3 rpi/test_layout.py      # 258 on every page fitting the screen it is
                                #     bolted to and being readable from the
                                #     driving seat (skipped without Playwright)
```

If the two parsers ever disagree, that suite fails. Edit one, re-run both.

One class of disagreement the corpus could not see, until it was given cases
that reach it. **Python's `\d` and `\b` are Unicode-aware and JavaScript's are
not** — `٢٠` is a number to one and not to the other, and an accented letter
ends a word for one and not the other. On
`$16.05 3 min (1.1 mi) away ٢٠ min (7.3 mi) trip` the Pi read both legs and
reported 23 minutes at $41.87/hr; the browser matched only the first and
reported 3 minutes at **$321/hr**. Every shared pattern in `offer_parser.py` is
now compiled with `re.ASCII` — except `normalize()`'s whitespace pattern, which
is the one place the Unicode reading is the right one, since JavaScript's `\s`
matches non-breaking spaces too. Tesseract with `-l eng` emits such characters
rarely; "rarely" is not "never", and two screens giving one card two different
verdicts is the exact failure a shared corpus exists to prevent.

`test_scan_pi.py` is the one that runs the whole thing. It drives the real
`main()` over a fake camera — nothing else is stubbed — and the camera is fake
so that it can hold the loop to account: it counts every capture request handed
out and every one given back, and notices a double release as well as a leak.
Every other suite covers a piece; this covers what they add up to, which is
where lifecycle faults live and nowhere else.

`rpi/testcards.py` draws the cards those two use. It is test-only and is not
imported by anything on the rig. It renders in either theme, so the same card
that checks the money in daylight checks it in dark mode.

The corpus includes the false positives that cost real money, because they read
as perfectly ordinary text. Each of these came off a real rig:

- `E 61 St & S Rhodes Ave` was read as `S 4S Rhodes`, which the loose money
  pattern turned into a **$45.00 offer** — a confident ACCEPT on a $7 job. The
  fallback for a dollar sign misread as `S` now insists on cents.
- `20 min (7.3 mi)` was read as `(73 mi)`. Left alone that does more than
  inflate the distance: the merger keys legs by distance, so it filed a *third*
  leg beside the real one and a 23-minute card reported **43 minutes and 81.4
  miles**. A leg is now checked against its own time and a lost decimal put back
  while it is still recognisable as the leg it came from.
- `ZIM`, out of map texture, parsed as a **21-minute leg**, which made a screen
  with no offer on it look like a complete offer. The minute unit must now be
  spelled out and the number must contain a real digit.

## If something is wrong

`python3 rpi/doctor.py` checks each dependency, the camera, and the calibration,
and prints the exact command to fix whatever is missing. It also runs the parser
against a known offer, so a green line there means the reading logic is sound and
the problem is the mount or the camera.

### Reading the log

The scanner's log is written to be pasted into a bug report. It says nothing
per-read — that would bury it — and everything that matters otherwise:

```
setup: capture 2328x1748, card ~549px on the sensor (floor 380), crop [0.00 0.40 1.00 0.60],
       warp 1800px, reader gets 900px, lens 4.00 dioptres
setup: exposure 16667us (a whole number of 60/120/240Hz cycles, so the screen should
       not band), gain 1.50 (tracking the screen)
setup: corners [[951, 300], [1456, 301], [1455, 1399], [950, 1398]]
read 1 found nothing usable (no payout in the crop, 1 in a row).
       Reader saw: '34 min (3.6 mi) total\nDollar General (925 Shiloh Rd Nw)\n...'
crop moved: [0.00 0.66 1.00 0.34] -> [0.00 0.47 1.00 0.33] (reads were failing; the card
       was found there by two whole-screen searches that agreed)
screen not visible — is the phone lit and in frame?
health over 120s: 7 reads, 5 complete; median 259ms; 2 found no payout; card
       brightness 190/205; banding 0.4; gain 2.10; crop [0.00 0.47 1.00 0.33]; crop
       moved 1x since start; corners held, drift 7px from saved
```

The `Reader saw:` line is the one that settles arguments. In the example above
the crop is sitting below the payout — the text starts at the journey line — and
that is visible at a glance without needing the rig. Two rounds of fixes here
were diagnosed from exactly this kind of evidence: `S 4S Rhodes` out of a street
address became a $45 offer, and `ZIM` out of map texture became a 21-minute leg.

`health` lines appear at most every two minutes and only when reads have
happened, so a quiet scanner stays quiet. The same detail is on `live.html`
under **what the reader read**, which is quicker if you are standing at the car.

`crop moved` says which of the two moves it was, because they mean opposite
things about how the scanner is doing — `reads were failing` is a repair,
`reads were working` is a working crop being trimmed. A log that called both a
failure made a healthy scanner look broken.

**libcamera is told to be quiet.** Opening the camera used to narrate itself at
INFO on stderr — which media node it bound, which yaml it read, the sensor
format it picked — seven lines each time, twice a run, all of which a
supervisor that tags stderr as an error files under errors. The lines actually
worth having (tuning file, autofocus, sensor mode) this program prints in its
own words, so `LIBCAMERA_LOG_LEVELS` is set to `*:WARN` unless you have already
set it. Warnings and errors still come through.

**If your log grows without end**, that is whatever supervises this, not this.
The `[system]`, `[SETUP]` and `[ERR]` tags in `logs/uberscan.log` are added by
the process manager that runs `npm start`; this program only writes lines to
stdout and stderr and never opens a log file. Truncate per run where that file
is opened — `>` instead of `>>` in a shell wrapper, or `flags: 'w'` instead of
`'a'` in a Node `createWriteStream`.

## Known limits

- The picamera2 layer — capture configuration, pinned exposure and focus — is
  **written but not tested on hardware**, because this was built without a Pi
  or a camera attached. It now pins the sensor mode, reads the motion gate's
  luma straight out of the YUV buffer, and only sets focus controls the camera
  actually reports, but none of that has met the real module yet. Everything below it (warp, crop, preprocess, OCR,
  parse, motion gate, tracking, crop placement, calibration, bench) is tested
  and passing.
- Timings are from x86, not a Pi 4. Run `bench.py`.
- Tested against a rendered replica with synthetic lens degradation, not a real
  lens pointed at a real phone in a moving car. The corner tracker in particular
  is tested against synthesised frames of a bright rectangle on a dark ground,
  which is what the detector keys on but is kinder than a windscreen at night.
- The crop assumes the card is aimed at the middle of the frame. It no longer
  hunts for a card it has lost, because it no longer has anything to lose — but
  the flip side is that a mount putting the offer in a corner needs aiming
  rather than fixing itself. Nothing here can fix a mount that was never good
  enough.
- Only Uber's current card wording is handled. A layout change breaks parsing,
  which is why the typed keypad on `index.html` stays the reliable path.
