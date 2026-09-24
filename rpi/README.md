# Raspberry Pi scanner (IMX519)

The Pi does everything: its own camera watches the phone screen, and the Pi
reads the offer and tells you the rate. No second device is involved in the
reading, no picture of a card leaves the car, and it needs no network to
scan — a rig with no signal all shift reads offers and shows verdicts exactly
as it does with one.

One thing does leave, once you set it up: `rpi/sync.py` copies the journal to a
machine at home on a timer, because a year of what the work paid living on one
SD card in a vehicle is the least durable arrangement in the system. That is
opt-in, it is the offers and the calibration and nothing else, and it goes to a
machine you own. See **Getting the offers off the car**.

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
sudo bash rpi/install-service.sh                        # verdicts spoken aloud
sudo SPEAK=0 bash rpi/install-service.sh                # printed to the journal only
sudo ARGS="--keep-scans" bash rpi/install-service.sh    # flags for the scanner
journalctl -u uberscan -f                               # watch it work
```

The service **is** the web server: it runs `server.js`, which spawns the
autopilot exactly as `npm start` does, so a rig booted this way has the
driving screen, the offers page and the scanner from one unit. It used to run
the scanner alone, and a rig booted that way had a driving screen that could
never show a verdict — readings reach the panel only through the server that
spawned the scanner.

Use one or the other, not both — two processes cannot share the camera, and
two servers cannot share the port. Stop the service before `npm start` or any
of the `rpi/` scripts by hand: `sudo systemctl stop uberscan`.

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

**The ceiling was set as that duty divided into what a read costs**, and it
moved when the read appeared to. It was 12s while a read was ~1.4s; keeping the
engine alive was thought to have roughly halved that — the owner's shift
recorded a median `ms` of 1517 before the change and it measured 2.12× end to
end, so 715ms was assumed — and 12% of a 715ms read is 6s. Same duty, half the
wait, and the table below said so.

**That 715ms never existed.** It was extrapolated from a speed-up seen on a
development machine. Measured over 272 real offers out of the owner's own
journal the median read is **1846ms** and the p90 is **3657ms**, so the duty at
a 6s ceiling is **31%**, not 12% — and it has been 31% for as long as the
ceiling has been 6s. The number was wrong; the rig was not.

| | read cost | ceiling | duty | worst case |
|---|---|---|---|---|
| a flat beat | ~1.4s | 2.5s | 56% | 2.5s |
| backing off, slow reader | ~1.4s | 12s | 12% | 12s |
| backing off, as assumed | ~0.75s | 6s | 12% | 6s |
| **backing off, as measured** | **1.85s** | **6s** | **31%** | **6s** |

**6s stays, on the other argument.** The wait is the thing being bought: a
replacement offer does not move the motion gate — 0.33 against a threshold of
6.0 — so the ceiling is exactly how long a driver can be looking at a verdict
belonging to the previous card. A third of a backed-off beat spent re-reading a
card that is not changing is a real cost on a Pi that is also drawing a
dashboard, and the lever is the ceiling; but every second added to it is a
second spent deciding on a card that has gone, and that is money. The trade
belongs to whoever drives the rig.

The ceiling is reached after two identical reads running (2.5 → 4.0 → 6.0)
rather than four. `READ_SECONDS` in scan_pi.py is where that cost is written
down; two constants are derived from it and one of them lives in another file,
which is how the last one went stale — and then this paragraph, the comment
beside `VERIFY_MAX`, and the one beside `STALE_MS` in live.html all went stale
the same way when the measured figure replaced the assumed one.

Not one of the CHECKS went stale with them, and that is the difference worth
keeping. `rpi/test_scan_pi.py` reads `READ_STALE_MS` and `STALE_MS` out of
live.html rather than copying them, and derives the healthy gap from
`VERIFY_MAX + READ_SECONDS_SLOW` rather than quoting a number — so correcting
the read cost moved every bound at once. Prose cannot do that. What prose can
do is name the constant instead of its value, which is what these three now
do.

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

### Collecting the evidence for a tick the rig could make itself

The button above is one press, and it is still a press. Measured on the owner's
real week: **31 of 1,166 offers carry a tick**, and every earnings figure on
every screen — the takings line, the $/hr the advice is fitted to, the cost of
holding a line — divides by those 31. The record is not wrong, it is thin, and
it is thin in the one column nothing else can supply.

**The cheap way to thicken it does not work, and the owner's own ticks are what
prove it.** A quiet stretch in the record looks exactly like a driver out on a
job, `unexplained()` already counts those stretches, and listing the offer in
front of each one is a few lines away. Against the 31 known ticks, a silence of
thirty minutes — what the pages already use — catches **2** of them and fires on
8 offers that were not ticked; at its most generous, five minutes, it catches 17
and fires on 61. The threshold is not the problem. The app is: median stated
length of an accepted job is 29 minutes and the median gap to the next card
after one is **5.4 minutes**, because offers keep arriving through the whole
delivery. That is the stacking feature working as designed, and it is why
`Advice.stack` exists at all. A phone that goes on offering work cannot fall
silent to mark the start of a job.

What is left is the screen. After an accept the phone shows a navigation screen
— a turn instruction, a speed limit, "Deliver to <name>" — with **no payout and
no Accept button anywhere on it**. `an_offer` in `digest()` is already the test
that separates that from a card, and until now every one of those frames was
read, counted twice on the health line, and thrown away.

So one is now kept, as a `kind: "screen"` row alongside the marks, the rules and
the pairings:

```
after      the id of the card this screen followed
afterMs    how long after it was read
text       the reading, raw, line breaks and all, capped like any other
places     what the reader made of it, recorded rather than acted on
cardWasUp  whether a card was still on screen at the previous read
```

What decides whether a row is written:

- **Once per card, and at most twice.** A navigation screen sits in front of
  this camera for a whole delivery and is read every time the map moves.
  Unbounded, one job would append a few hundred rows of the same screen to a
  file that is only ever appended to. One row per card that reached the file —
  not per landed *row*, which is what the first version of this really did,
  since a card writes one row per reading that improves on the last plus a
  settled upgrade. On the owner's measured week that bound is about 1,166 rows
  and a third of a megabyte.
- **Inside three minutes of that card.** An accept happens inside the card's own
  countdown, so the screen after it is seconds away. The window is for the other
  case — a driver who stops scanning and comes back an hour later to a phone
  showing something — which would otherwise be filed against a card from an hour
  ago.
- **Not a clipped read.** `clipped` means the payout *was* found and was sitting
  flush against the top of the crop, and the reader answers that with an empty
  parse — a card with no payout in it, which no test of the parse can see
  through.
- **The raw reading, not the flattened one.** On these screens the LINE is the
  grammar. "Deliver to Daria I." is a line; the same words scattered through a
  flattened blob are not evidence of anything.
- **Not after a card the rig saw and never recorded.** A card needs two agreeing
  reads to lock and only a locked reading is written, so a card can be seen,
  counted in `saw`, and never reach the journal — which is the gap `saw` minus
  `kept` exists to measure. The slate is armed by a card *landing*, so without
  this the anchor is "the last card that landed" while the driver is looking at
  a different one: card A lands, card B is read once and never lands, the driver
  accepts **B**, and the screen after it is written against **A**. A pairing
  naming an offer they did not take, indistinguishable from a real one. Any
  payout that is not the armed card's now drops the slate, and the cost is a
  missing row instead of a wrong one.

Two things it deliberately does **not** decide, and both were wrong in the first
version:

- **A merchant name does not make it a card.** The address hunt next door
  refuses any frame naming a place, on a measurement that says a navigation
  screen names none — *"it says `Dropoff <address> 12 min Start` and `places`
  comes back empty"*. That was measured on DoorDash. Uber's post-accept screen
  names its destination the way a card names a shop: `BCG Atlanta / 1075
  Peachtree St NE Ste 3800, Atlanta, GA`. Reusing that test would have refused
  exactly the screens worth collecting, silently, and the corpus would have come
  back holding only the ones that read badly. The payout alone is the grammar,
  and what the frame named goes **onto the row**.
- **One glared frame of a card is labelled, not refused.** A card that loses its
  payout for a single frame reads as payout-free over a card, which is the
  positive class in the negative slot. Refusing such a frame was the first
  answer and it was worse: reads are driven by a motion gate, so the frame right
  after an accept is sometimes the only one, and refusing it loses the screen
  rather than mislabelling it. So it is written with `cardWasUp: true`, and the
  first frame with no card behind it supersedes it — two rows at most, sharing
  an id, separated by `seq`, which is the same convention every superseded
  reading in this file already uses.

**Nothing reads them, and nothing writes `accepted` from them.** That is the
whole discipline of this feature and it is not temporary caution. Nothing on
file says what one of these screens reads as through this camera, at night,
through a windscreen — so a recogniser written today would be a regex tuned to a
screenshot, deciding the one field every earnings figure is gated on. A wrong
tick is a taken job that never happened, in the file that cannot be rewritten.
The rows are collected, they sync to the NUC on their own, and what gets built
on them gets measured against ticks the driver made by hand first.

### ...and what the shift adds up to

Marking was write-only. A driver could put a fact into the record from the
driving screen and never see it come back: the figures that fact feeds live on
the offers page, which is the wrong screen to be on while driving.

One line on the status row now: **`· took 3 for $61 net · median $26/hr · 9
offers · 1 set aside`**. Three things decided it.

The money leads. It used to read "9 offers · 1 set aside · took 3 · median
$26/hr", counts first, and the line is ellipsised from the right on a narrow
panel — so the two figures a driver is actually working towards were the two
most likely to be cut. What the taken jobs paid is net, and says `net` only
when a running cost was really taken off.

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
with its own journal, which the sync timer leaves up to eleven minutes behind.
The line sits directly beside "no Pi scanner on this machine", which is the
signal that it is a copy — but it is not suppressed there, and the figures are
the copy's. (Marks made there used to stay there; the timer's run now brings
them back — see the sync section.)

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

*That paragraph described the intent and not the handler, in both directions.*
A failure inside the engine's constructor never reached the giving-up at all —
`engine = engines[key] = _Tesseract(...)` does not assign when the constructor
raises, so the `if engine is not None:` guard skipped it — and an init
returning non-zero therefore printed nothing, left the library live, and made
the rig re-attempt `TessBaseAPICreate` and the LSTM model load on **every read
for the rest of the shift** before running the binary anyway. Meanwhile the
comment inside that handler claimed a third policy — "this one is dead; the
next read builds a fresh one, twice in a row and the library is the problem" —
which nothing counted and nothing implemented, since one exception inside
`read()` already turned the library off for good. Both halves now do what this
paragraph says.

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

*The verdict is the LOADER's, not the listing's, and for a while it was not.*
The report shows every tuning file on the machine, including ones in another
ISP pipeline's directory, because "there is an autofocus tuning here and it is
for the wrong ISP" is precisely the diagnosis somebody needs — and the verdict
was built from that same wide list. On a Pi 4 with an autofocus tuning under
`rpi/pisp/` and none under `rpi/vc4/` it printed `ok  autofocus available` and
ended **All good.** over a lens libcamera will never move, while the rig's own
answer for the same machine was `supported: False`. Both now ask
`camera.focus_answer`, which is the restricted search plus the `UBERSCAN_TUNING`
override, and a stranded file is reported as one:

```
FAIL  autofocus available   an autofocus tuning exists but not in the pipeline
                            this machine runs (.../rpi/pisp/imx519.json) —
                            libcamera will not load it, and handing it over
                            registers no cameras at all
      no AF  /usr/share/libcamera/ipa/rpi/vc4/imx519.json
      AF     /usr/share/libcamera/ipa/rpi/pisp/imx519.json   (not loaded here)
```

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
  Only calibration writes it. The corner tracker judges every candidate's SHAPE
  against it always, and its SIZE against it until an automatic re-baseline
  moves the size reference for the rest of that run. The file is untouched
  either way, which is what ⟳ Re-find restores.
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
was left alone at first, because it can be a total — `$7.09 34 min total` states
no distance and is a whole journey by itself — and one plain leg is already not
whole for having no second half. That exemption has since been replaced by the
question it was standing in for; see *…and that piece of work, done*.

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
itself from nothing — including undoing an automatic re-baseline, which is the
case it exists for. "Corners on the screen at the wrong size" is equally "the
phone was re-seated" and "the outline is on part of the screen", and that is
exactly the call the watchdog has already made; the person watching the live
view can see which it was, so they get to overrule it. For a while they could
not: the re-baseline moved the same reference this button restores, so the press
landed on the box the watchdog had just adopted and the green box did not move.
If the phone really has been re-seated the rig will take the corners back about
half a minute later, and the log says so rather than leaving a correct press
looking like a failure. It is a POST to `/api/recalibrate`, which touches
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

Flags for the scanner reach it through the server that spawns it:
`SCANNER_ARGS="--keep-scans --screen-fps 6" npm start`, or
`sudo ARGS="--keep-scans" bash rpi/install-service.sh` for the service. That
route did not exist for a long time — every flag below was documented and none
of them could be given to the rig as it actually runs.

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

**The picture itself** — `--keep-scans` (`SCANNER_ARGS="--keep-scans" npm start`
on the rig as it runs). This is the one that changes what can be asked. Whether
a crop was too tight, whether a threshold ate a decimal point, whether a
different psm would have found the missing leg: all of it is
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

**What the rows now keep so that this can be reopened.** Every card states its
journey as a total, and part of that total is driving to the pickup rather than
doing the job. The parser has always read the split — Uber labels the leg
`away` — and the journal threw it away, keeping only the sum.

That sum is the right figure to judge an offer on, because the driver spends the
approach either way. It is the wrong figure for any question about *where* the
work is, because the approach moves with wherever the car happened to be when
the card arrived: the same two places produce a different total every time. So
no row could ever say how far apart two places are.

`toPickupMinutes` and `toPickupMiles` are on every row the RIG writes from now
on, and null wherever the card did not split it, which is most delivery cards.
Null and not zero: a zero would be subtracted, the approach would vanish into
the job, and the result would be a confident wrong distance rather than an
absent one. See `to_pickup()`, which refuses three separate ways.

Rows the browser writes — a typed offer, or a card the phone's own scanner read
— do not carry the pair at all: `journal-client.js` builds its own row and has
never had these fields. They are a minority of the journal and they are not
wrong, merely silent, which reads the same way as a card that stated no split.
The measurement counts a row without them as one whose approach is unknown.

It is recorded ahead of anything being built on it because the journal is
append-only. A row already on disk cannot be repaired, so every shift that went
by without this is a shift nothing can go back for.
`tools/measure_places.js` reports what share of the history is clean, and that
share rises on its own.

### What 103 real offers said about mapping any of this

The driver exported a shift and asked whether there was enough location in it to
draw a map. Measured on that file rather than argued about:

| | |
|---|---|
| offers | 103 |
| cards printing `Customer dropoff` and no address | 48 |
| legs on the card | one on 91 of them |
| `toPickupMinutes` / `toPickupMiles` filled in | **0** (see below — the parser could not read the layout yet) |
| dropoffs the parser recorded | 57 |
| ...that were the pickup again | **35** |

Three things follow, and the first two are corrections rather than opinions.

**The approach split does not exist on these cards — half right, and the
wrong half is the half that stopped anyone looking.** 91 of the 103 state one
leg — `2.9 mi • 21min`, or `43 min (8.9 mi) total` — and never separate the
drive to the restaurant from the drive to the customer. That much holds. What
followed from it did not: "anything built on subtracting the approach would be
building on almost no data" was read as settled for months, and it was measured
on 103 cards.

On the owner's full week of 1,166 the field was null on **every single row**,
and the reason was not that the cards do not state the split. It is that the
parser could only read it as the WORD `away`, which appears on **0 of 1,166**.
110 of them print the split plainly, as a layout:

    $26.04
    8 min (3.2 mi)                                 <- the drive TO the pickup
    Ector Chase NW & Ector Overlook NW, Kennesaw   <- the pickup
    39 mins (25.1 mi)                              <- the trip
    Hale St NE & Inman Village Pkwy NE, Atlanta    <- the dropoff

`laid_out_approach` reads that order and sets the same flag `away` would have
set, so `to_pickup` stays the only rule that decides. It fires on **103 of the
1,166** once the accumulator has folded the frames — 8.8%, where the approach
is a median 35% of the card's stated miles. Not by size: on the two-leg cards
the first leg is the shorter one only 62% of the time, so taking the smaller
would be a guess dressed as a reading and every fourth one would be wrong.

**The parser was inventing destinations.** Of 57 dropoffs recorded, 35 were the
restaurant the driver was collecting from, recorded as where the customer lives
— the commonest wrong answer the parser gave, and on its own enough to make a
map of these rows meaningless. `find_dropoff` refuses two ways now: when the
card says `Customer dropoff` in its own words, and when the answer would be the
place the job starts from. That took the 57 down to 22, and cost exactly one
genuine pair.

**What is left is real but thin.** 22 of 103 offers name two distinct ends, and
they are proper street addresses — `Payne Rd & Stately Dr, Woodstock`,
`Villa Rica Hwy, Dallas`, `Greenside Dr, Austell`. That is the honest ceiling
for mapping the offers themselves: about one in five. The other route to a
destination is the ⌖ Dropoff scan, which reads the address off the phone and is
the only place a customer's full address ever appears.

**That scan now runs before the decision as well as after it.** It was built
for the screen that comes after the accept, and that is the wrong moment: the
driver's own words are *"for doordash orders I need to tap the customer drop
off location to show the address when screening so it would be possible to
search on the map"*. They reveal the address BEFORE deciding, because where a
job ends is half of whether it is worth taking — and the rig was looking away.

So ⌖ Dropoff appears in one more state: no order in the car, a card on the
panel, and no destination on it. It asks to be pressed only when the card
REFUSED one — `endRefused`, which parse() and the accumulator both now report,
because "Uber printed *Customer dropoff*" and "the reader found nothing" arrive
identically as a null dropoff and only the first is a state a tap can fix.

The address then lands on the card being screened rather than on an order in
the car, appended as a note naming the offer the same way a tick is. server.js
used to refuse exactly this, and the paragraph saying so was right about the
danger and wrong about the guard: *"Read with nothing held, this is an address
belonging to no job"*. The guard that was doing the work was never "an order is
held", it was "this belongs to something identifiable" — so it became
`screeningCard()`, an id and a two-minute clock. An address read long after the
card left the screen still lands nowhere.

`map.html` is where to look at all of this: it pins what it can, joins the two
ends of each job, and — the half that matters for checking — lists what it could
not place and why. Four things were wrong with the first draft of it, and they
are in [the section on the map](#four-faults-in-a-page-built-to-find-faults).

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

### Two figures the phone wrote differently from the rig

Both found by an audit fleet pointed at the seams between the two ports, and
both verified by running the real code before anything was changed.

**A pair that loses money could not be written down.** Every money figure on the
driving screen goes through `rateText()`, which puts the minus in FRONT of the
dollar — "$-16" is a dash at a glance from the driving seat. The stack line was
the one formatter that did not, and being a range made it worse: `'$' + lo +
'–' + hi` on two negatives is `$-16–-31`, an en dash wedged between two minus
signs. Measured on a real shape (two long cheap jobs, 62c/mile eating them):

    + $-16–-31/hr with the one you have, over 55–105 min

And the range is backwards. `worst` divides the pair's money by the LONGER time
and `best` by the shorter — above zero that makes `worst` the smaller number,
below zero it reverses, because dividing a negative by a smaller number makes it
more negative. So the low end printed first was the larger of the two. Both ends
now go through a signed formatter, ordered by value, separated by the word "to"
rather than a dash that cannot survive a minus beside it.

**The phone wrote its money unrounded.** `rpi/journal.py` puts `perHour`,
`grossPerHour`, `perMile` and `cost` through `_round` at two places and
`billedMinutes` at one. `journal-client.js` put them through nothing. The same
field, written by the same project, into the same file, under two rules — and
the second rule was *absent* rather than different, which is the shape that
drifts without anybody noticing. On one card ($8.83, 23 min, 4.6 mi) the Pi
wrote `19.43` and the phone wrote `19.434782608695652` into the column beside
it. Both pages round for display, so the only place a person meets it is the CSV
the README calls "a CSV of everything", and anything that later groups or diffs
on those values gets two populations that never compare equal.

**The interesting part is the guard, which took three tries to make testable.**
Rounding has to leave a missing figure alone, and on a card with no distance the
verdict's `perMile` is `undefined` — so arithmetic on it gives NaN, and *NaN
serializes to `null`*. A row carrying NaN therefore reads on disk exactly like a
row that honestly had no distance. The first check compared the serialized value
to `None` and passed over both, which made the guard look like dead weight; the
mutation run is what said so. The check now reports the TYPE across the browser
boundary, which is the only thing that can tell them apart. Eight mutants, eight
caught.

Two fixtures had to be built rather than reused, for the same reason as ever: a
card with whole minutes cannot tell a rounded one-decimal field from an
unrounded one, so the billed-minutes check needs a shopping allowance (7 items
at 25 seconds bills 25.9166… minutes), and the missing-figure check needs a card
that names no distance at all.

### The rig invented two offers out of screens that were not offers

272 real cards arrived from the owner's own rig — every row carrying both what
the parser concluded AND the raw OCR it concluded it from, which makes the whole
export a ground truth the parser can be re-run against.

The payout is read reliably: a re-parse of all 272 texts disagrees with the
stored `pay` on **zero** rows. What is not reliable is knowing when there is no
offer on the screen at all.

**Uber's route planner, read as a $120 ACCEPT.**

    Drive i & x
    a 8 50 min $ 50 min $120
    5 min (2.3 mi)
    @ Add stops < Share o

$120 over 105 minutes — three "legs", 50 + 50 + 5 — at $68.18/hr, `state: go`,
green, `suspect: false`, no doubt at all.

**DoorDash's idle screen, read as $376.50/hr.**

    $12.55
    This dash
    Hong Kong Chinese
    Finding offers.
    You're in a good place to wait for offers
    Zone offer wait
    1-2 min

The dash's takings so far became the payout and the zone's *wait estimate*
became the job's duration. The app is saying, in so many words, that it has no
offers.

Neither is catchable by the numbers. $68/hr is an ordinary rate; $12.55 is under
the flat pay cap `doubt()` applies below ten minutes. And a positive test — "a
real card says Accept, or Guaranteed, or Pickup" — is not available either: **79
of the 272 carry none of those**. They are ride offers that read as a payout, a
rating and two legs, so demanding an anchor would refuse a third of the real
traffic.

What is left is the app's own furniture. `NOT_AN_OFFER` holds two phrases — `add
stops` and `finding offers` — each the only evidence against its own phantom,
each appearing on no genuine card in the 272. A card offering a job does not
announce that it is looking for one.

Four phrases were written first. Mutation testing showed two of them earned
nothing: the idle screen was already caught by `finding offers` without them, so
they went, and the comment that would have claimed each was necessary went with
them. Seven mutants, seven caught, across both ports.

**Withheld, not dropped.** It is a `doubt` reason like the others: the row is
written, `suspect` is set, it is in none of the figures, and the panel says NOT
AN OFFER instead of a rate. If this rule ever fires on a genuine card it costs
one verdict the driver can still read off the phone — where refusing to parse
would lose the row and leave a hole nothing could account for later.

Three of 272 cards change. All three are phantoms. All three previously produced
a confident verdict.

### What a read really costs

The same export settles a number that had been estimated rather than measured.
`READ_SECONDS` was 0.75, derived in a comment as *"the owner's own shift recorded
a median of 1517ms before the engine stopped being thrown away per read, and
that change measured 2.12x on a development machine: 1517 / 2.12 is about
715ms"*. A development machine is not a Pi 4 that is also drawing a dashboard,
and the speed-up did not arrive on the rig:

    min 390   p25 1405   median 1846   p75 2636   p90 3657   p99 4812   max 5915

**99.3% of real reads are slower than the 750ms assumed**, and every piece of
arithmetic hanging off it was optimistic.

It was also one constant doing two jobs. *Typical* is for duty cycle — what
share of the verify beat is spent re-reading a card that is not changing — and
the median is the right statistic for that. *Worst case* is for the driving
page's staleness window, and a median is precisely the wrong statistic for a
bound, because one read in two is slower than it. So there are two now:
`READ_SECONDS` (1.85, the median) and `READ_SECONDS_SLOW` (3.7, the p90, with
the measured max of 5.9 written down beside it).

Two things followed. The page's verdict window was 12s against an honest healthy
gap of 6.0 + 3.7 = 9.7s — it was sized for 6.75s and left 2.3s of slack where it
meant to leave most of the gap again. At the worst read measured, a perfectly
good verdict came within **90 milliseconds** of being dimmed as stale, on the
hardest card, which is the one a driver most needs to trust. It is 16s now.

And the suite's claim that "the ceiling spends about a tenth of the time
reading" was true about a constant and false about the rig: the real figure is
31%. The check states the measured band now. Getting that third back means
raising `VERIFY_MAX`, which lets a *replacement* card sit unread for longer —
money against CPU, and a trade that belongs to whoever drives the rig rather
than to a test file.

### A leg the window had, thrown away; a destination the card refused, invented

Both from the audit fleet, both verified by running the real code before
anything was changed, and both in `accumulate.py` — the module that turns
several half-read frames into one offer.

**The union of legs was capped by a bound pointing the wrong way.** The comment
read: *"No frame of a real card lists more legs than the card has, so the most
any single frame reported is a ceiling on the union."* The first clause is true
and the second does not follow from it. If every frame sees at most N legs, N is
a **lower** bound on what the card has — and it was being used as an upper bound
on what the union may keep, which throws away real legs in precisely the case
this module exists for: the card no single frame ever read whole.

Measured on a $16.05 two-leg ride card read three times — trip leg alone, then
away leg twice — the window held both legs and the merge returned only the away
leg: **$188.64/hr on a card worth $32.47/hr**, drawn green. The frame that
produces it is the one the pipeline locks on, two identical reads being what
locking means. A note appears beside it (`whole: false`), but `rate()` still says
ACCEPT and `scan_pi` writes the row on `ready and locked`, not on `whole`.

The cap is counted per KIND now. An approach leg and a trip leg are different
things — the card's own wording says which — so a union holding one of each is
not evidence of a misread, while an invented leg still lands in the same kind as
its neighbours and is outvoted there. The suite's own check used to assert the
old behaviour, with a comment conceding the cap "cannot tell that case from this
one". It can now. Six mutants, six caught.

**And the merge invented a destination on a card that refused to give one.** The
comment there was mine, from earlier in this same session: *"the per-frame
refusal has already done its work: a frame that saw 'Customer dropoff'
contributed no dropoff to `self.places`"*. That is false. `self.places` is
`find_places()` output, which carries no refusal; the refusal lives in
`find_dropoff`, behind the `text` the merge deliberately withholds.

Withholding the text is still right — `find_dropoff` searches it for each place,
and the merged text is ONE frame's while `places` is the union of all of them, so
a place another frame contributed is not in that string at all. What was missing
is that the refusal has to travel separately. It is a union across the window
now, like the places are, and for the mirror-image reason: a frame that missed an
address is not evidence there was none, and a frame that missed the refusal is
not evidence the card named somewhere.

Reachable, and demonstrated: a delivery card reading "Customer dropoff" whose
crop caught a street off the map behind it parses per-frame to `dropoff: None`
and merged to `'Lake Dr SE, Marietta'` — a destination the card explicitly
declined to give, written to the journal, pinned on the map, and handed to
`sameArea()` as the answer to whether a second job sends the driver backwards.

### A check that fired one run in four with nothing wrong

Chasing the leg fix turned up a suite failure that was not the leg fix. The same
check fails at HEAD, once in four runs under load, and it is worth writing down
because of *why*.

`test_scan_pi.py` asserted that "a card that never reads whole stops being
re-read every half second", as a rate: reads per second over the stretch after
the resample burst. The drive produces 12 reads, of which **exactly one** lands
after the settle mark. A rate computed from one read is not a rate — it is the
question "did that read land more than 0.83s after the mark", and the answer
moves with how busy the machine is. Under load the drive stalls, the last read
lands earlier, the span shrinks, and the rate goes *up* through the threshold.

The fault the check exists for is a shape, not a rate: each read inside the
burst used to push the burst's end four seconds further out, so a card that never
reads whole was re-read every half second for as long as it sat on screen. With
that bug the reads spread across the drive; without it they bunch at the front
and stop. That is a ratio of two counts, which no amount of load can move.
Mutating the real arming condition now gives 9 of 22 reads after the burst
against 1 of 12 when healthy — a shape, with room either side of it.

A check that fires when nothing is wrong is worse than no check, because it
teaches whoever reads it to skip the line.

### Searching near where the car actually was

The driver's own words: *"usually the pickup/restaurant is the closest one to
me"*. That is exactly the question a geocoder cannot answer and a coordinate
can. Handed "Chipotle" it returns a Chipotle; handed a misread street it returns
a real street somewhere; both come back with the same confidence.

So `rpi/gps.py` is now wired in. `--gps HOST[:PORT]` on the scanner, and every
offer row carries `lat`, `lon` and `gpsAge` — where the car was when the card
came up, and how old that fix was. Absent whenever it is not known, which is
most rows: no `--gps`, no answer, or a fix over twenty seconds old all produce
the same honest nothing.

**It is off until you pass it, and `npm start` does not pass it for you.** The
server spawns the autopilot, which hands anything it does not recognise down to
the scanner, so the whole route is one environment variable:

```sh
SCANNER_ARGS="--gps 100.x.y.z" npm start      # the phone's Tailscale address
```

The phone's GPS server app listens on 2947 and the port can be left off. Under
systemd it goes in the unit's `Environment=` line, next to the other
`SCANNER_ARGS` flags.

Without it nothing is broken and nothing says so either, because there is
nothing to say: rows carry no position, `map.html` searches on the typed hint
the way it always did, and **◍ Where you were** draws nothing and reports "none
carry a position". That last sentence is the one to look for when the feature
seems to be doing nothing — it is the page saying the rows never knew, not the
page failing to draw them.

`map.html` then searches each place inside a box around where the car was, using
Nominatim's `viewbox` with `bounded=1`. Sixty miles: generous enough that no
real delivery is refused, tight enough that the nearest street of the same name
in another state is. A place is boxed **only when the rows that named it carried
a position** — the middle of the whole range was tried as a fallback and
deliberately dropped, because on a journal where only the last week has
positions it would box a place from eight months and two cities ago to last
week's metro and refuse it.

**Three things went wrong writing this, and all three were caught by the checks
rather than by reading it back.**

A box that refuses everything would lose pins to a feature meant to gain them.
So a place its own box refused is asked again without one, and what comes back
is judged by the stray test like anything else. The first version did that
retry *inside* `lookup`, which sent two questions back to back under a rule of
one per second — measured against the suite's stub at 3ms apart. Being blocked
by Nominatim would stop this page working for everyone who pulls the repo. The
rate limit is now a property of the page rather than of one loop: a single
`paced()` wrapper waits *before* a request based on when the last one went out,
which also removes the "except the last one" special case that a sleep-after
needs.

The box has to be longitude-first (`left,top,right,bottom`) and it must not be a
square of *degrees* — a degree of longitude at 34°N is about 57 miles against
latitude's 69, so equal degrees draws a box a fifth too narrow in the direction
this driver's metro is widest.

And the cache key has to carry the box, or the wide answer overwrites the
bounded one and the anchoring silently stops applying from the second run
onward.

Seven mutants, seven caught — but only after the fixture was changed. The
original one never made a box refuse anything, so the retry, the enforcement
and the cache key were all unexercised and three mutants sailed through. The
fixture now gives the offer whose street was misread a position near Kennesaw,
so its Idaho answer is refused by its own box, asked again wide, and drawn red
as a stray. That is the whole feature in one row.

### Asking the phone where it is

The Pi has no GPS and no clock. The phone in the mount has both, and a GPS
server app on it hands them out over TCP on port 2947 — gpsd's port — to
anything that asks. `rpi/gps.py` is the thing that asks.

It is worth having because the geocoder is the weak link in everything this rig
says about *where*. Handed "Chipotle" it answers with a Chipotle; handed a
misread street it answers with a real street; both come back with the same
confidence and neither is necessarily in the state the driver is in. A
coordinate taken at the moment the card was read turns all of that from a guess
into a lookup bounded to where the car actually was.

Try it before anything depends on it:

```sh
python3 rpi/gps.py --from 100.75.197.117:2947
```

That address should be the phone's **Tailscale** one rather than its hotspot
one — the hotspot's DHCP address changes and the tailnet's does not, so the
same command keeps working when the rig is on wifi at home.

**Most of the file is about not answering.** A rig somebody drives with cannot
afford a position that is confidently wrong, and the phone's app runs on a
timer — the one this was written against showed "Runtime Left 4:48" — so it
stopping mid-shift is not an edge case. A fix older than twenty seconds is
therefore NO fix, `fix()` returns None, and None is always available and always
honest. The reader is off unless asked for, never blocks the scan loop, never
holds a lock across the network, and reconnects quietly for ever.

**The clock is the trap.** The Pi boots in 1970 and leaps forward when NTP
answers, so the GPS's own timestamps cannot be compared against the Pi's wall
clock to decide freshness — the two disagree by decades at boot. Staleness is
measured entirely against the local clock: when we received the line, against
what the local clock says now. Both readings come from the same wrong clock, so
the error cancels and the answer is right while the rig still thinks it is 1970.
A clock that jumps *backwards* mid-shift yields a negative age, and negative is
refused too rather than reading as fresh.

**Two protocols, because port 2947 is not a promise.** Real gpsd greets with a
JSON VERSION banner and says nothing until it is asked to WATCH; several phone
apps take the same port and simply push NMEA at whoever connects. Both are
handled, and which is in use is decided by what arrives rather than by a flag.
The WATCH command is sent only after a gpsd banner has actually been seen, so
an app that merely borrowed the port is never sent something it did not
advertise.

`rpi/test_gps.py` is 89 checks and weighted the way the risk is — a little on
parsing a good sentence, most of it on refusing to produce a number. It runs
against a real socket on a real port, because the framing, the threading and
the reconnect are the parts most likely to be wrong and a stubbed transport
would check none of them; only the clock is faked. Seventeen mutants, seventeen
caught, including every one of the refusals: Null Island, a latitude past the
pole, an RMC the receiver marked void, a GGA with quality 0, a sentence that
fails its own checksum, knots stored as metres per second, `ddmm.mmmm` read as
a decimal, a boolean where a latitude should be, a sentence split across two
packets, a sender with no line endings at all, and a stopped reader still
showing a green light.

### A page nothing linked to, five buttons one press from dead, and a backup with a hole in it

**The map page did not exist.** Not in the sense of being unwritten — it works,
it has its own suite, and every check in that suite was passing. Nothing linked
to it. No page pointed at `map.html` and `map.html` pointed nowhere back, so the
only way in was to type the address and the only way out was the back button. A
working feature nobody can reach is not a feature, and a suite that proves it
works without asking whether anyone can get to it is the shape this project
keeps finding. The offer log now carries `⌖ Map` and the map carries a way back,
and the map suite asks for both — it was the file already holding "the server
serves the map page", one question short of the useful one.

The offer log is the right door rather than the driving screen: the map sends
place names to a public geocoder at one request a second, which is a thing to do
parked on a monitor, not at a red light.

**Five controls, one press from dead for the rest of the shift.** `fetch` has no
timeout of its own. A socket the far end accepts and never answers on — which is
exactly what a car hotspot the Pi is associated with but cannot reach through
produces — leaves the promise pending for ever, and nothing after it runs. Every
control on the driving screen's bar cleared its busy flag in the `.then()` after
the fetch. So Took, Drop, ⌖ Dropoff, ⟳ Re-find and "✓ Read this box" each sat at
"…", disabled, from one press until the page was reloaded, with nothing saying
why.

`loadShift` already knew this and guarded itself, in a comment explaining the
exact failure. That guard is now `ask()` and all six go through it: a deadline
makes the promise settle, `AbortError` lands in the `.catch` each control already
has, and the "not saved" state a driver can act on is what appears. Seven
mutants, seven caught — the last after the check for ⌖ Dropoff was rewritten,
because it asked about `disabled` and that button says its busy state in its
label, so it passed over a control stuck at "⌖ reading…" for the shift.

Driving it needed Playwright's fake clock. Twenty seconds of real waiting, plus
the thirteen ⌖ Dropoff takes on top, put the browser driver past the watchdog
that stops a hung section eating the whole run — the timers are the real ones at
their real settings, and only the waiting is skipped.

**The offers read before the rig knew what time it was were never backed up.**
The Pi has no clock: it boots in 1970 and jumps when the network arrives, and a
card read in between is on disk stamped with a moment that never happened. Every
ordinary sync sends from an hour before the copy's newest row — a number in the
trillions — so a 1970 stamp is below the floor and was stepped over. Only a
hand-run `--all` ever carried one.

The reconciliation could not catch it either: both ends count inside the same
window, a row with no date is in no window on either side, so the counts agreed
and nothing looked missing. Meanwhile the offers page tells the driver those rows
are "still in the journal file on disk" — true, and on exactly one disk, the SD
card in the car, which is the thing the backup exists for. They go on every tick
now; there are never many, and the far end stores an (id, seq) pair once however
often it arrives.

**The target advice quoted a different line from the one it recommended.** The
page prints one sentence: *"taking the first one at or above $12 whenever free
gives 173 trips."* At $12 it gives 187. `suggested` is the bottom of the plateau
and `trips`, `takes` and `hours` were read off the argmax, which is a different
line — this file had already caught the same mistake twice, for the stability
check and for the gain, written the reasoning out both times, and not applied it
to the counts.

The interesting part is why it survived. Usually those two lines are the same
number: the replay curve climbs to its peak and the 95% band spreads upward from
there, so the bottom of the plateau IS the argmax. A sweep of 3,897 shapes that
produced an answer separated them in none. The check needed a two-population
market — a bulk of cheap offers around $10/hr against a dense cluster from $38 to
$52 — to put a shallow shoulder under the peak and pull the plateau's bottom down
to $12. The check says out loud that the two lines are far enough apart on that
fixture to tell, because on any other recording it could not fail.

That hunt also corrected a measurement of my own. A first attempt reported the
page saying 108 trips where the line gives 314, which was not a fault at all —
the comparison had been made against a different row set, not a different line.

### One limit written in two units, and the screen that hid the clock

**The backup had a size it could not check.** `sync.py` chunked its uploads at
2000 **rows**; `server.js` refuses a body over 8MB of **bytes**. Nothing held the
two together — the tie was a sentence, "a row is a few hundred bytes", and a row
is not a fixed size. It grows every time a field is added to what is worth
keeping, and `places`, `text`, `untimedMiles` and `mergedFrom` all arrived after
that 2000 was chosen. (Measured today: a row carrying two addresses and its OCR
text is 1062 bytes, so 2000 of them is 2MB. The margin was real. It was also
invisible from either constant.)

What made that worth fixing rather than documenting is how it fails. Measured: a
9MB upload came back to the sender as `ConnectionResetError`, because the far end
called `req.destroy()` before writing its 400 and Node resets a connection whose
response ends with the request still arriving. `sync.py` cannot tell a reset from
being out of range — and being out of range is *normal in a car*, so it says
"will try again next time" and exits 0. The only backup of the only irreplaceable
thing on the rig would have stopped working, permanently, while every tick
reported success. Its own comment claimed a body over the cap arrives as an
`HTTPError` worth a non-zero exit; that branch was unreachable.

Both ends. `readBody` now drops the buffer and drains the rest instead of
destroying the socket, so the refusal is readable — and that is a near-miss cure,
not a guarantee, which the comment there now says: past roughly twice the cap
Node stops feeding the request and the sender's remaining write still breaks
(measured: 9MB readable, 16MB a broken pipe). No server can make a client read an
answer it is not looking at yet. So the guarantee lives on the sender, which now
measures chunks in the same unit as the cap they have to fit inside, at half of
it — the far end counts characters and this counts bytes, and bytes are never
fewer. A row too big for a chunk of its own is still sent rather than skipped:
dropping it would lose a row in silence, which is the failure the whole limit
exists to prevent, one row further along. Six mutants, six caught.

**`Scanner.feed()` was a second way in, and the wrong one.** Gate the frame, then
read it — and nothing called it. The loop in `scan_pi.py` does those two steps
itself because between them it re-finds the phone's corners, converts them to
sensor coordinates and decides whether this is the card it was already watching.
Worse than redundant: `feed` called `should_read(frame)` with no scale, and the
scale is what confines the motion gate to the phone. Without it the gate measures
the whole picture and fires on a hand moving past the windscreen. Anyone who
found it and used it would have got a scanner that read on the wrong frames, from
a method whose name says it is the normal way in. Deleted, with a check that it
stays deleted.

**The 3.5" hat had the clock hidden.** `#detail` is not only diagnostics. It is
how old the reading is — the one figure on the driving screen that is acted on
continuously, because it is what says whether the numbers belong to the card in
front of you or the one before it — and, when there is no card, the whole of what
the page has to say: *"nothing from the scanner for 40s — it may have stopped"*,
and the instruction for aiming the mount. The hat's stylesheet reclaimed the line
with `#detail { display: none; }`. So the smallest screen, the one with the least
room to work anything out, was the only one that could not tell a stopped scanner
from a quiet one and had no instructions for pointing the camera. The diagnostics
now have an element of their own — they were bare text nodes, which CSS cannot
address, and that is *why* the whole block had to go — and the line stays.

Putting it back needed 10px the panel did not have, and looking for them found
something worse. **The verdict was already sliding off its own card.** `#verdict`
is a centred flex column, so content taller than it spills equally out of *both*
ends, and the top of the card is where the word ACCEPT and the rate live. On a
card carrying three notices at once — a distance that could not be read, an hour
worked out without one, a journey still arriving — the hat put the headline 2px
above the glass and the word PASS 25px above it, clipped away by `#app`. On the
800x480 panel the rig is actually bolted to, a long enough notice did the same.
Every existing check passed: the text was in the DOM, and nothing had asked where
it landed.

One declaration fixes it, and not the obvious one. A flex item's automatic
minimum size is its own content, so the block of prose refused to give even
though it was the only item with anything to give — and the rule that removes
that floor is `overflow` being anything but `visible`. `overflow-y: auto` makes
the notice shrinkable and what does not fit reachable, in the same word. A
`min-height: 0` beside it is what everyone reaches for and changes nothing; the
mutation run is what said so.

Two more on the hat: the four card figures went from a value stacked over its
label to a value beside it — 41px rather than 78, nothing dropped and nothing
smaller — and the headline gives up as much again as it already gives a pair,
only when there is a pair, so the stack line stops hanging outside the card it
belongs to. Eight mutants, eight caught, after three survivors sent three of
these back: `min-height: 0` did nothing, a `scrollHeight` comparison answered yes
for the version that scrolls *and* the version that paints the words off the
screen, and smaller notice type on the hat bought a fraction of a line and a
claim nothing could check. That one is not in the file. **What the checks say
now** is that a notice is whole or scrollable but never cut, that the three-note
card reads whole on a panel with the room and by scrolling on the one without,
and that nothing in the card hangs outside it — asked against the card's box and
not the window, because overflow eats the padding first and a verdict label
painted across its own border passes every question about the glass.

### Six places the record disagreed with the screen

Every one of these is the same shape: a number the driver saw, written down or
locked in or carried forward as a *different* number. None of them threw.

**The log row was re-deriving what the panel had already decided.**
`journal-client.js` built its row out of `parsed`, not out of the verdict. On a
delivery card that is two different offers. The card states "24 mi" with no time
beside it, `rate()` recovers the lost decimal to 2.4 and works the hour out over
that, and the row went to disk saying 24 — beside a `$/hr` computed over 2.4.
A row that cannot be reconciled with itself is worse than a missing row, because
it argues. Minutes had the same split: a delivery card's minutes are the time
left until the deadline, which `parse()` cannot know and `rate()` does. The row
now takes `cardMinutes`, `miles`, `fromDeadline`, `milesCorrected` and
`milesUncertain` off the verdict, and only falls back to the card's own figures
for a reading that predates them. Four mutants, four caught.

**The lock could not see two-thirds of the card.** `scan.js` decided a reading
had settled by comparing `pay|minutes|miles` against the last one. A DoorDash
card carries a deadline and an item count and — the case that made this real —
*the same three numbers two hours apart*, one worth `$58.97/hr` and one worth
`$7.69/hr`, because the hours left until the deadline had run down. The
signature saw no change and locked the stale verdict. It is now
`pay|minutes|miles|deliverBy|items`. Holding this took splitting the fixture so
that the deadline and the item count each differ alone; with both moving at
once, either half of the fix looked sufficient. Four mutants, four caught.

**"No distance on the card" was printed as a rate, not as a ceiling.** When
`uncosted` was set, the note explained the *distance*, and the big number above
it stood unqualified. The hour worked out without a distance is an upper bound —
every mile that is really there only makes it worse — so the note now says so in
the sentence that is actually about the number: *"No distance on the card — rate
is a ceiling"*, and *"Distance unreadable — rate is a ceiling"* when a distance
was there and could not be read. Two mutants, two caught.

**Hiding a card and un-hiding it left the outcome to file order.** A `rule` row
says *hide every card matching these three numbers*; un-hiding writes another
with `hidden: false`. The fold took whichever it met last in the file, which is
insertion order and not time order — and rows arrive out of order routinely,
because the sync appends a chunk from the rig into a copy that has been written
to at home. The fold is now by `rule.at`, newest wins, with `>=` so that two
rules sharing a millisecond still resolve to the later one in the file. Two
mutants, two caught.

**A recalibration from a saved image threw the focus away.** `calibrate.py
--from-image` has no camera, so it has no lens position to measure, and it wrote
`null` — over a `lensPosition: 4.62` that a real run had measured against the
real mount. The scanner then fell back to a hardcoded `4.0` and every card after
that was read slightly soft. It now keeps what was on disk when it cannot
measure, and still takes an explicit `--lens`. Proving that needed a check that
`--lens 3.1` *wins*, or "always keep the old one" passes too. Two mutants, two
caught.

**The Set box button stayed live while the box was being drawn.** Switching the
view out from under an in-progress drag left the drawing bound to a frame that
was no longer on screen. The button is now disabled for the duration, with a
title saying why.

### Four checks that could not fail, one of them written that morning

The audit's twelfth agent was pointed at the suites rather than the code, on
this project's own rule that a check which cannot fail is worse than no check.
It found four, and the first is the worst kind: a check written to verify a fix
made the same day, reported as verification, that had never run.

**`test_stacking.py`** compared the recorded pair verdict against the live panel
with `get('/api/status').get('stack')`. `/api/status` has no top-level `stack` —
the panel's is at `last.stack` — so the value was always `{}` and the `if _live:`
around it meant the comparison had never once executed. There is no `if` now: an
empty answer is a failure, because that endpoint is supposed to be showing a
pair. Proved by forcing the panel's own verdict to 'go' and watching the suite
fail, which it previously would not have.

**`test_scan_pi.py`** guarded two resample checks with `if span > 2.0`. Measured
across runs, the span is about 0.4s — a nine-second drive, but the reads bunch at
the start — so those two checks had never executed either, and the suite's count
was two short with nothing saying so. The span is a property of the harness, so
it is asserted rather than tiptoed around; the count went from 263 to 266.

**`test_pipeline.py`** had `eq('it is a function of the geometry and nothing
else', centred_roi(0.64), centred_roi(0.64))` — a pure function called twice in a
row and compared with itself, which is as true of a function that accumulates as
of one that does not. Mutating `centred_roi` to widen with the history of shares
it had seen left it passing. Other calls go in between now, and that mutation is
caught.

**`tests/advice.test.js`** had `if (a.ready) { ok_('a market this clear gets an
answer', a.ready); … }` — true by construction inside the branch — with an else
arm that accepted a refusal, so five checks could go quiet and the count would
just drop. And a second `else { ok_(…, true) }`, which is the shape stated
outright. The answerable market now asserts an answer; the refusal arm names
which refusal.

### A loss that read as a gain, next to the same figure written correctly

live.html states the rule at line 615: *"-$10.60", not "$-10.6". A minus sign
wedged between the dollar and the digits is a dash at a glance.* `rateText`,
`money` and the `earned` figure all honour it. The working line under the
headline had **its own copy** of the formatter and did not, and so did the shift
line's median — so a card worth -$13.24/hr printed

    -$13.2     the headline
    $-13.2     the working line, immediately below it

Reachable on an ordinary card at the IRS rate the README itself recommends:
$2.50 over 12.4 miles at $0.70/mile. The duplicate is deleted — the working line
calls `rateText` — and the median is signed the way the `earned` figure three
lines above it already was. The check is made against every rendered text node
on the page rather than one element, so a `$-` written anywhere is caught; it
walks text nodes and skips `<script>`, because the page's own source contains
the string `"$-10.6"` inside the comment explaining why it must never render one.

### ...and the other half of the pairing fix

Teaching `recordPairing` to use the driver's real target fixed what gets written
from now on. Every pair row already on disk still says `go`, and the offers page
was still reporting those as *"the panel said: take it"* — in the tally, in the
per-row "Called it" line, and in the colour of each dot.

`judged` is the row saying whether its verdict is the one the driver was shown.
It is absent on every older row, and absent is not "fine" — it is the unknown,
and this page may not report an unknown as a word the panel used. Those rows now
read **not recorded**, with a sentence saying why and their own figures left
alone, and they are counted in their own bucket rather than as a verdict: how
many of the record cannot be graded is the measurement, and folding them into
"no answer" would have hidden it just as reporting them as "take it" did.

### A brute force run against the wrong flags

Last week's `untimed_miles` deleted its own guard for a token that will not
become a number, on the strength of a brute force over every token `DC` can
produce — 10,709,310 of them, none of which failed. The brute force was run
against `DC` **case-sensitively**. `LEG_ORPHAN` is compiled `IGNORECASE`:

    DC case-sensitive: 0123456789BIOQSZbilosz
    DC IGNORECASE    : 0123456789BILOQSZbiloqsz

`L` and `q` are in the class and `DIGIT_FIX` has no entry for either, so
`(3.q mi)` is a bracket the pattern really produces and `to_number` answers
None for it. With a second orphan already holding a number the comparison was
`None > 9.0` — a **TypeError out of parse()**, on the Pi, where the browser port
returned 9. A read that raises is a card the rig does not read.

The lesson is narrower than "always guard": a claim about what a regex can
produce has to be made against the flags it is compiled with.

Restoring the skip is half of it. The other half is that an orphan which will
not coerce still means a leg went untimed — the size is simply unknown, and
unknown is not small. `most_of_the_journey_missing` refuses on `shortATime`
when there is no number, the same way it refuses a reading with no distance at
all. Returning None and letting the rule read it as "nothing missing" would
have dropped the refusal exactly where the reading is worst.

### Two ends the window kept and then threw away

`_merged` rebuilds `places` from the whole window because "an address is exactly
the field a single frame loses" — and then `pickup` and `dropoff` were still
whatever `dict(parsed)` copied off the frame that lost it. A card whose map was
read three times and lost on the fourth merged like this:

    places  : ['Celebration Blvd, Acworth', 'N Cobb Pkwy NW, Acworth']
    pickup  : None
    dropoff : None

Those two fields are what the journal row stores, what `map.html` pins, and what
the stacking advice asks `sameArea()` about. The window's whole reason for
keeping the addresses stopped one field short of everything that uses them. Both
are re-derived from the merged places now, through the parser's own rules —
including the refusal for a card that prints "Customer dropoff" and no address,
which is the fault `find_dropoff` was corrected for in the first place.

### The cap that deleted what it moved aside

`_roll_if_huge` moved the live journal onto `<journal>.1` with `os.replace`,
which overwrites. So the **second** roll deleted the first archive — no
exception, no complaint, nothing on disk to say it had happened. On the same
mechanism at a small cap: **39 rows written, 9 still findable afterwards.**

That is the failure mode of the very thing the cap is for. `MAX_BYTES` says it
exists so a bug writing on every frame instead of every offer cannot quietly
fill the card, and in exactly that case this rolled again and again and shredded
everything behind it. The chain is shifted now — `.1` becomes `.2`, `.2` becomes
`.3` — so nothing is destroyed and `.1` stays the newest, which is what
server.js stats to notice a roll at all. A second roll also says so out loud,
because a hundred and twenty-eight megabytes of journal on a rig that makes a
few megabytes a year is a bug, not a season.

### A recovery that had never once fired

`track.py` has a rule for the state the rest of the tracker cannot get out of:
*"a screen that holds the centre, while the corners do not, is not a candidate
to be weighed against a stored size — it is the phone."* It is guarded by
`self.agreeing >= self.centre_agree`, and the size gate twelve lines below sets
`agreeing = 0` on every refusal.

The centre rule exists **for** candidates the size gate refuses. It was gated on
a counter that its own precondition had just cleared, so it could never reach
two. Measured over 40 checks of a phone re-seated to 0.72x sitting on the frame
centre, with the corners parked aside: `centred` stayed 0.

The rig did get out of that state — by the 30-second re-baseline, which fired
and moved the corners. So this was a redundancy as well as a dead branch, and
what it was worth was speed: half a minute of reading through corners that are
on the wrong thing is most of an offer's life. It has its own counter now and
adopts on the third check. Its guards were never exercised in that whole time,
so they are pinned too: a wide bright thing is not the phone, nor a tall narrow
one, nor a phone the corners are already on, nor an empty mount.

### Two copies of the crop, and a multiplier that was never checked

`crop_box` and `read_height` existed byte for byte on both `Geometry` and
`Scanner`, and both copies were live: Geometry's are what `_look` reads,
Scanner's are what scan_pi reads for the health line and for the crop outline on
the live view. Two answers to one question drift, and these two decide which
pixels tesseract is handed. Scanner's delegate to Geometry now.

And the module docstring's headline argument — *"four times the pixels measured
26% more time, so the wins are in not running it, not in shaving pixels"* — has
the arithmetic wrong. 1.83MP against 0.76MP is **2.4** times the pixels, not
four. The 26% was measured; the multiplier attached to it was not.

### One bad byte, and the whole journal read as empty

A twelve-agent read of the tree, each agent held to this file's own standards
and made to prove its findings by running them. The two worst are both about
the same thing: a figure or a record that is confidently wrong.

**`rpi/journal.py` opened the journal as text.** The decode then happens for the
whole file at once, so a single corrupt byte anywhere in it raises
`UnicodeDecodeError` out of the iteration, the catch-all at the bottom throws
away every row already parsed, and `rows()` hands back `[]`. Measured on a
five-row file with one byte flipped:

| reader | rows | torn |
|---|---|---|
| `server.js` | **4** | **1** |
| `rpi/journal.py` | **0** | **0** |

Four lines were still perfect JSON and Python returned none of them — and
reported the file as whole, because the torn counter added the week before
never ran either. One failing card sector cost the entire journal, silently.
Read as bytes now, decoded a line at a time, so a bad byte costs its own line
and no other. Two readers of one file disagreeing about what is in it is the
fault this project keeps finding; this was the side that was wrong.

**And `[]` meant two different things.** A file that cannot be opened at all is
not a file with nothing in it, and every caller read it as the second. `sync.py`
took the empty list as "nothing new", exited 0, and **stamped the copy fresh on
the way out** — which `doctor.py` then reported as a healthy backup made minutes
ago, next to its own journal check finding zero rows and zero torn and passing.
A rig saying everything was fine while nothing at all was being copied off it,
which is the one direction this backup must never fail in. `rows()` now sets
`unreadable`; the sync refuses to stamp and exits non-zero; the preflight fails
and says it is not an empty journal.

### Every pairing said the panel had advised taking it

`recordPairing` took the driver's money off the wrong object:

```js
Advice.stack(held, offer, { target: offer.target, band: offer.band,
                            costPerMile: offer.costPerMile }, now)
```

`offer` is what `scan_pi.emit_offer()` prints, and it has never carried those
three: they are the driver's settings, not properties of a card, and they ride
the *reading* beside it. So `Advice.stack` got three undefineds, which default
to zero — a target of $0/hr that every rate on earth clears. Measured on a real
pair, $12.45 over 30 minutes in the car against a $3.00 over 40 card at a $25
target:

    what the PANEL showed : {"state":"no",  ...}
    what the ROW recorded : {"state":"go",  ...}

The range and the geography in the row were right. The one field the row exists
for was a constant. The comment above that function says the file is there to
answer *"when it said take both, was it right?"* — and a notebook in which it
always said take both cannot be graded, only believed.

**The suite passed throughout, and its own fixture is why.** `test_stacking.py`
supplied `target`, `band` and `costPerMile` on the offer it fed in — fields the
real scanner does not send — so the code under test was handed the very thing
whose absence was the defect. That file carries a long comment at the top about
this exact trap, written when it happened before. It had grown back on the
pairing path. The fixture no longer invents them, and the check is now on the
verdict's **value**, held against what `/api/status` is showing at the same
moment, rather than on the key being present.

### A token the installer had just proved works, dropped by systemd

`tools/install-sync.sh` wrote `Environment=SYNC_TOKEN=$SYNC_TOKEN` unquoted.
`rpi/install-service.sh` next door carries nine lines about exactly this hazard
over `SCANNER_ARGS`; the sibling had none. Asked of systemd itself:

    token 'a b'    -> Invalid environment assignment, ignoring: b
    token 'pc%25'  -> Failed to resolve specifiers in SYNC_TOKEN=..., ignoring

A passphrase with a space in it — which the installer has *just tested by using
it to reach the copy* — is truncated into a log nobody reads. The far end then
answers 403 to every run and the backup stops, with an installed timer and a
success message on screen.

Quoted now, and the `%` doubled, since systemd expands specifiers inside
`Environment=` even within quotes. The quoting could not simply be written into
the heredoc: bash performs quote removal *inside* `${SYNC_TOKEN:+...}`, so the
quotes were gone before the line reached the file — measured, not guessed. The
line is built in a variable first. That installer had no test at all; it has one
now, and it asks systemd rather than a regex.

### A hole in the one file that cannot be rebuilt

Three readers of `journal.jsonl` had the same line in them:

```js
} catch (e) { /* a line torn by a power cut; skip it */ }
```

```python
except ValueError:
    continue        # a torn line; skip it and carry on
```

Skipping is right. The file is append-only, it cannot be repaired, and one bad
line must not cost the other fifty thousand. Saying **nothing** was not.

This is the one artefact the rig produces that cannot be regenerated. A row that
will not parse is an offer that is gone — nothing keeps a second copy of a line,
and the machine at home faithfully receives the hole. It vanished out of every
figure on every page with nothing anywhere saying so, which is the failure this
file keeps writing sections about, on the file that can least afford it.

The write side had already thought about this. `append` starts a fresh line when
the last one never finished, so a stub left by a power cut costs one row and
does not fuse to the next — its comment says *one torn row is the cost of a power
cut; two is a missing byte*. The read side was the half that never reported the
one.

**One is not the case worth alarming about.** The card loses power when the
engine does. The case worth alarming about is a number that grows, because that
is an SD card beginning to go, and the entire value of noticing is noticing while
there is still something to copy off it. So: `/api/journal` counts them beside
`beforeClock`, the offers page names them in the same list and says plainly that
those offers cannot be recovered, and the preflight passes at one and fails at
more — *copy the journal off it now, then check the card*.

**The line being written right now is not a casualty.** The scanner appends
while everything else reads, so the last line of a live journal routinely has no
newline on it yet. Counting it would report a fault on every busy shift. Only
lines that are terminated and still will not parse are counted — and a real
stub becomes terminated on the next append, so nothing is missed by waiting.

Ten mutations, ten caught, including the two that matter most for a count kept
across an incremental read: one that reset it on every parse of the part that
grew, and one that counted the row in flight.

### The row that said it was refused and would not say why

`journal.py` was working the verdict out a second time:

```python
why = OP.doubt(pay, minutes, miles)      # three numbers
```

`rate()` already decided that, and it decides it on more: `OP.doubt` takes three
figures and can only ask whether those three can be true, while `rate()` also
weighs the shape of the reading and refuses a rate worked out over one leg of a
journey the card printed two of. So the moment the refusal above existed, the
two answers came apart — a card the panel refused at $220.80/hr was written down
as `state: 'doubt'` with `doubt: None`. **A row saying it was not judged and
declining to say why**, which is the one thing a record of a refusal is for. The
CSV column had been exporting a blank reason for it.

The offers page then explained it with the first branch that matched: *the
scanner never saw the whole card — only part of the journey was in the crop*.
The card was fully in the crop. Its second leg was in the picture and its hour
read as an `l`. A wrong explanation is worse than a vague one, because it is
read while deciding whether the rig made the mistake or the driver did.

The row takes the verdict from `rate()` now, the way `miles` and `minutes`
already do and for the reason already written above them — two answers to one
question drift. It keeps `untimedMiles` too, since `leg` alone cannot tell a
missing walk to the door from a missing trip, and that is the difference between
a reading that was nearly right and one out by a factor of eight. The page has
its own sentence for it, ahead of the crop one, and the flag no longer calls it
*outside the range a real offer falls in* — nothing about it is.

The medians were never affected: `whole === false` is true of every such row and
`trustworthy()` excludes it. That held by argument rather than by construction,
so the row now marks itself `suspect` as well — `whole` is an *argument* to
`row_for`, and a caller that got it wrong would have put a $213/hr reading into
the figures.

Seven mutations, seven caught, after two rounds. The first round had two
survivors and both were the check's fault rather than the code's: the fallback
for a hand-built rate dict was being proved with a card where *nothing was
wrong*, so both branches answered `None` and dropping the fallback looked like a
working change. And a second `if why == 'leg'` guard turned out to be reachable
by no input at all — `rate()` already sets the field only for that verdict — so
it was deleted rather than propped up with a contrived fixture.

### 104 offers, 2076 lines, and no check on the export

The CSV is the one thing this project produces that leaves the machine and is
opened by something else. Every page here is driven through a real browser. The
export was tested by being looked at.

`text` is the reader's own output, line breaks and all, because the line breaks
are the part a later question is most likely to need. Put in a cell raw and
quoted, that is **legal** CSV — a quoted field may contain newlines, every
proper reader handles it, and all 104 records in the driver's own export have
their 37 cells.

It is also 2076 physical lines for 104 offers, **103 of the 104 spanning more
than one**. `wc -l` says 2075 offers. So does `head`, so does `grep`, so does
any five-line script or importer that splits on newlines — and not one of them
says it is guessing. The fix is the one already used two lines above it in the
same function, where `scans` is JSON-encoded to dodge the neighbouring version
of this problem: the text round-trips exactly and one record is one line.

The suite it never had now holds the export to the properties a spreadsheet
fails silently on — every record carrying the header's cells, an address with a
comma in it surviving as one cell, a quote the reader invented not ending the
field early, booleans as something summable, an absent field empty rather than
the word `None` — and to the round trip, so the column keeps being able to
answer the question it is in the file for. Five mutations, five caught.

### Four faults in a page built to find faults

`map.html` exists to let a person check what the rig read, because the rig
cannot. Driven through a real browser against a stubbed geocoder, it had four
faults of its own, and the first one is the one that would have cost someone
else something.

**The rate limit applied to nothing at all.** Nominatim asks for at most one
request a second and blocks the projects that do not keep to it — and being
blocked is not one bad run, it is this page not working for anyone who pulls
this repo. The wait was written, and then asked for at the wrong moment:

```js
var hit = await lookup(q);                 // lookup() caches its own answer
...
if (!cached(q)) await sleep(1100);         // ...so this is never true
```

`lookup()` writes the answer into the cache before it returns, so the test made
after it always found the key and always skipped the wait. Every lookup that
used the network was exempt from the limit; only the ones that *failed* were
slowed down, since a failure is not cached. Measured against the suite's stub:
**six questions in 33 milliseconds**, under a rule of one a second. The fix is
to ask before the call, not after — and the deeper fix is that the query string
was being built by hand in three places and only one of the three was consulted
at the right time. It is built in one now. The suite records the gap between
every pair of questions and holds the smallest to a second: 1105ms measured,
3ms on the reverted code.

**One bad lookup hid the whole shift.** A geocoder handed a misread street
answers anyway, with a real place somewhere and the same confidence as the right
one. That is *exactly* what this page is for — a person spots a pin in Idaho
instantly, where the rig never could. But `fitBounds` over a set containing that
pin is a map of the United States with the shift as a single dot, so the one bad
lookup hides the ninety good ones the driver came to check. Pins further than 75
miles from the **median** of the rest — the median, because the mean is dragged
by the very outlier being looked for — are now drawn in red, listed with how far
out they are, and given no say in where the map looks. 75 miles refuses nothing
real: a long ride is forty.

Listing them and keeping them off-screen is a contradiction, so each listed
stray takes the map to it when tapped. A stray that cannot be reached is a claim
the driver cannot check, which is the thing this page is against.

**A hundred offers at a dozen shops looked like a dozen jobs.** Every job at the
same merchant geocodes to the same coordinate, and the page was stacking one
marker per *offer* on the same pixel: popups unreachable under each other, and
how often a place actually came up — most of what makes a map of a shift worth
looking at — invisible. One pin per distinct place now, with the number of jobs
drawn on it, keyed on the place **as the card wrote it** rather than on the
coordinate: two spellings that happen to resolve to the same point are two
things the rig read, and what the rig read is the subject.

**And the sidebar lists stopped at twenty-five in silence.** The whole argument
for that sidebar is that a map showing the fifth it managed reports the rig as
doing better than it is. A list showing the first twenty-five of twenty-eight
failures makes the identical mistake one level down. Each list says how many it
did not show.

Nine mutations, nine caught. The suite gained a pin in Idaho, a place shared by
three offers, and twenty-six addresses nobody can find — the last two past the
cap, deliberately, and dated newest so the journal's own ordering does not push
the one named failure out past it and let a check pass by not running.

### $220.80 an hour, on a card where every figure was right

    UberX $18.40  5 min (2.1 mi) away  l hr 24 min (7.8 mi) trip

The trip leg's hour is an `l`, so that leg has no readable duration and
`find_legs` refuses it — correctly. The leg is then dropped whole, taking its
7.8 miles with it, and the journey the rate is worked out over becomes **the
drive to the rider**: $18.40 over five minutes. **$220.80/hr, green ACCEPT,
against a true $12.40 PASS.**

Nothing on the panel hedged it, and no check on the figures could. `$18.40` is
an ordinary payout, `5 min` an ordinary leg, and the pair clears `SANE_RATE` at
the ten-minute floor by a comfortable margin — `doubt()` passed it, and was
right to. `is_whole` was already false, so the rig went on resampling, but a
card whose hour never reads properly stands there in green for the whole life of
the offer.

**What was wrong was not a number.** It was that most of the journey was not in
the reading at all — and the card says so, in the distance printed beside the
minutes that did not read. `shortATime` has been detecting exactly that since
the orphan-bracket rule was written; it was spent on `is_whole` and on nothing
else, and `is_whole` only slows the rig down. It never reached the money.

**Which leg went missing decides how bad it is**, and that is the reason this is
not simply `shortATime`. Two cards from the corpus, one character apart:

| card | reading | true |
|---|---|---|
| `$16.05 ٣ min (1.1 mi) away 20 min (7.3 mi) trip` | $48/hr | $42/hr |
| `$16.05 3 min (1.1 mi) away ٢٠ min (7.3 mi) trip` | **$321/hr** | $42/hr |

The first lost the approach, which costs the journey the two minutes it takes to
reach the rider — a hedge, not a refusal, and refusing it would cost the driver
a usable answer on a card the rig very nearly read. The second lost the trip,
which costs it the job.

`untimed_miles` reads the orphan brackets as numbers rather than counting them,
and the rule is a comparison: **when the leg that could not be timed is bigger
than the journey the reading holds, no rate is shown.** 1.1 against 7.3 is a
hedge; 7.3 against 1.1 is a refusal. No label is needed for it, which matters on
cards where the labels did not read either. A reading holding no distance at all
is the same case: knowing nothing about how far a job goes is not a reason to
trust its minutes.

It joins `doubt` — `'leg'` — so the machinery is the one already there: the
verdict is withheld, every figure stays on screen because the driver is holding
the same card, and the row still reaches the journal, because a reading this
project got wrong is the most useful row in the file. The panel says CHECK THE
TIME with the reason under it in words, including how much of the trip is
missing. A frame that reads the leg clears it.

Of 266 corpus cards, eleven carry an orphan distance and **three** change
verdict — every one of them the catastrophic kind. The stacked card whose
`(4.0 mi)` belongs to no leg keeps its PASS; the approach-leg case above keeps
its ACCEPT.

Sixteen mutations, sixteen caught, across both ports and the panel. Two of them
found real gaps rather than confirming the fix: no corpus card exercised a
reading with no distance at all, and none had two untimed legs to prove the
larger is the one that counts. A seventeenth — an orphan whose digits will not
coerce — could not be caught, and brute force over all **10,709,310** tokens
`LEG_ORPHAN` can produce says why: not one of them fails to become a number.
The guard was deleted rather than kept as a line no check can fail on.

### The focus the shift was pinned at, and the frame it came from

Calibration keeps the sharpest of six frames, because the frame it writes the
corners from is the frame every read of the shift is cropped against. It then
measures the exposure on that screen — eight rungs, three frames each — and only
after that writes the file, including:

    'lensPosition': source.lens_position,

`source.lens_position` is not a property of the calibration. `preview.py`
rewrites it from the metadata of **every frame it pulls**, so by the time this
line runs it holds the focus the lens had drifted to at the end of two dozen
frames taken at forced exposures, with the lens free to hunt the whole way.
Measured on a fixture stepping the lens 0.02 a frame: the kept frame was taken
at **4.06** and the file was written with **4.60**, thirty frames later. The
scanner pins that number for the entire shift.

It is the quiet kind of wrong. `config.json` looks right. `config-preview.png`
looks right, because the preview is rendered from the kept frame. Nothing says
anything. The only symptom is that every read of the night is a little softer
than it should be — and a softer read is a misread leg, or a lock that never
happens, which is an offer that never reaches the journal at all.

The lens now travels with the frame: `_frame_to_keep` reads it in the same
breath as `source.frame()` and returns it alongside the frame and the quad, and
`calibrate_from` writes the one that came back. Three mutations, three caught —
the old line restored, the lens taken from the last frame of the run rather than
the kept one, and the read moved one frame early.

### A notice that told the driver to dim a phone in their pocket

`too_bright` puts a red line on the driving screen: *the phone is brighter than
the camera can take — turn the screen brightness down a notch.* It is set from
`_split` saying the camera is out of room — gain on its floor, no shorter rung
to fall to.

An empty mount in direct sun is out of room in exactly the same way. `too_dim`
has been guarded against that case since an empty cradle was first told apart
from a dim card, on the grounds that *the driver would turn up a phone that is
in their pocket*; the identical guard was simply missing from this end. Driven
on the exposure harness with the tracker reporting no screen, forty beats of
sunlit empty cradle raised the complaint every time.

The guard goes on what **sets** the flag, not on the flag:

```python
self.too_bright = self.too_bright or (stuck and lit_screen)
```

`... and lit_screen` over the whole expression reads better and is wrong. A card
at full well is a card whose corners are hardest to hold, so the beat on which
the complaint is truest is the beat the tracker is likeliest to have dropped —
and that version takes the notice off the screen at exactly that moment. Nothing
is needed to clear it: the branch above already does, on the first beat that can
measure the card at all. Three mutations, three caught, including the shape that
silences the notice on any rig running `--no-track`.

The controls were left alone deliberately, and it is a real trade. The same
sunlit cradle walks the exposure down to the shortest rung and the gain to its
floor, and the returning phone then needs six beats — **36 seconds**, against an
offer that lives 30 to 45 — to climb back. Gating the *cut* on `has_screen` is
the obvious fix and it deadlocks: a card blown out is a card the tracker cannot
find, so the rig would refuse to darken the picture that is the reason it cannot
see. That is the hole the down-branch already has eleven lines explaining. The
false sentence is fixed; the recovery is measured and left.

### A button that said it had done something it refused to do

Pressing **⟳ Re-find** is the driver saying the outline is wrong. From that press
on, the rig is reading through corners they have already judged bad.

The scanner may refuse. A hand-drawn box is only given up for a screen it can
actually see, and with `--no-track` there are no corners for the press to move
at all. Both refusals went to the log — which is not a place anyone looks from
the driving seat — and the button went on to say **"⟳ re-finding"** regardless,
because the only thing it waits for is a web handler that touches a file and has
never spoken to the scanner. A refused press and a press that worked were
indistinguishable from the seat.

Three changes, and the first is the smallest: the button now says **"⟳ asked"**,
which is the whole of what the POST proves.

The reason rides the heartbeat, as the scanner's own sentence rather than a
flag — the two refusals want different things from the driver, and only that end
knows which happened. It has to be the heartbeat: the commonest refusal is *there
is no screen in view to find*, which is also *no reading is coming*, so any
channel needing a reading would be silent in precisely the case it exists for.
The live page renders it in both branches of `render()`, since the offer that
arrives while the corners are wrong is exactly the offer being read through them.

And it **expires**, after 25 seconds. That is there for `--no-track`, where the
refusal is permanently true: with no expiry the first press would put a notice
up for the rest of the shift, and a notice that cannot be cleared is one the
driver stops reading — which costs the notices that can be. Press again and it
comes straight back.

Nine mutations, nine caught. The ninth is the one worth naming: an earlier round
of eight caught everything and the suite was still wrong, because one of the
eight — deleting the clear-on-success — was run against the browser suite, which
never loads `scan_pi.py`. Chasing that MISS is what found the `--no-track` notice
that could never go away, and one unreachable clear, now deleted rather than
kept as a line no check can fail on.

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

### Sized for the driving seat, and a column that ate its own frames

**The controls are 52px, not the 44px both platform guidelines give.** That
number is written for a phone held in the hand by somebody looking at it; this
is a tablet bolted to a dashboard, pressed at arm's length by somebody who has
just parked and is about to pull out. The guideline floor is the smallest thing
that works, and the room was there. Text on the offers page — the one screen
that is *read* rather than glanced at — goes up with it: the log rows to 17px,
the payout to 26px, and nothing on a panel below 15px.

Both floors are enforced by `rpi/test_layout.py`, which renders every page in a
real browser at all six panels this ships on. **The floors were raised first and
the CSS made to meet them**, which is how the work stayed honest: 32 failures,
then 12, then 1, then none.

**Neither floor is a flat number, and pretending otherwise broke the 3.5" hat.**
480x320 cannot show 15px labels above a five-row keypad — raised there, the page
went past the bottom of its own glass, and a control out of reach is worse than
a label leaned in for. So the floor is 52px and 15px on a panel with the room,
44px and 12px where there is none.

Two things fell out of doing it:

* **`scan.css` set the scan bar's controls twice**, and the later of the two
  identical selectors won. A `min-height` put in the first rule was silently
  overridden — the exact hazard the comment beside `.bottombar [hidden]` in
  `styles.css` was written about, in a different file.
* **`.scanbar` is styled in `scan.css`, not `styles.css`.** I added a
  duplicate set of rules to the shared sheet before checking, and they were
  dead weight that broke two structural checks. Removed.

**And the `scans` column was eating its own frames.** It was added so the OCR's
disagreements could be measured, and exported joined with `" | "` — while the
frames are OCR of a phone screen, whose icon row and dividers both come back as
pipes. `trim_place` cuts at the first one for exactly that reason.

Measured on the first export that carried the column: **57 of 296 rows, 19%,
split mid-frame**, and the damage is invisible because a fragment of a card
still looks like a card. It is JSON now, which cannot collide with its own
content.

**What that export finally settles.** Two sections up, this file says the
corpus cannot say how many frames the rig really gets per card, because the 604
texts are *distinct* texts and a card read eight times identically appears once.
The `scans` export answers it:

    2 frames   20  (6.8%)
    3 frames    6  (2.0%)
    4 frames  164  (55.4%)
    6 frames   44  (14.9%)
    8 frames   20  (6.8%)
    12+        13

**Not one single-frame offer in 296.** The merge gets four or more looks at 93%
of cards, so every rule in this file that votes across frames is doing real
work — and the "98% single frame" that the deduplicated corpus implied was the
artifact this file warned it would be. The same export shows **zero duplicate
rows**, where 7.6% of the old journal was surplus.

### Six more the same review found, and what they had in common

The first pass on that review fixed four findings. Fifteen survived refutation,
and every one of the rest reproduced exactly as reported. What they published:

| | shown | true |
|---|---|---|
| `(8.L mi)` — a 1 read as an L | **$72.49/hr green** | $63.92/hr |
| the lone vote elects the 10x reading | $25.29/hr | $43.80/hr |
| a replacement card inherits the old one | **$53.49/hr green** | $21.53/hr |
| one truncated frame poisons a card | $17.52/hr uncosted | $13.45/hr |
| losing the total line resets the merge | 2.0 mi, filed twice | 6.0 mi |

**A card with no legs could never be a replacement.** The deadline delivery card
states no duration and no legs, so nothing could line up *or fail to* line up,
and `_is_a_different_card` returned False before reaching any other test. A
genuinely different offer paying the same to the cent inside the twelve-second
window merged into the old episode and was published with the old card's
distance **and** the old card's deadline — and never filed at all, because
`episode` never moved. Such a card states two things that can be compared
instead: where it goes and when it is due. **Both** must differ: one field is
what OCR does all day, which is why both are voted on in the first place.

**A frame that lost the total line was called a replacement.** A card printing
legs *and* a total parses to the total alone, so a later frame that loses that
line reports two ordinary legs, they line up with nothing, and "two legs means a
whole journey" reset the window mid-burst — on a frame that is the same card
read slightly worse. The whole-journey signal is still there; two legs only
count as one when the card on record is not itself a total.

**`lostMiles` is now counted, not ORed.** It is one frame's claim about damage,
and the slot it lands on falsely is the one that never gains a distance: a
pickup-wait line whose tail begins with the *next* leg's bracket once that leg
is truncated away. One such frame stamped the wait line for the life of the
offer. A majority is what the rest of this class does with a field frames
disagree about.

**The lone-distance vote elected the corrupt reading.** One token read twice
arrives as two numbers — the frame that also caught the duration has had its
decimal point put back, the frame that lost both reports the raw ten-times value
— and a tie breaks towards the larger. `milesChecked` then locked it in, because
the minutes came from the good frame and `rate()` therefore never re-checked it.
The obvious fix, folding a ten-times reading back on sight, **is wrong in the
other direction**: a card that really says 24 miles, misread once as `2.4`,
would fold to 2.4 and publish a green accept on a job with ten times the
driving. So the winner is judged against the merged minutes by `check_distance`
— the rule already tuned for exactly this — asked with the winning reading's own
decimal flag, so one frame and eight agree about the same card.

**And the rule could not see the damage it was written for.** `lostMiles` only
inspected the 14 characters *after* the leg match, so it could only ever see a
bracket the LEG regex **failed** to consume. That catches damage on the unit,
`(8.1 m1)`, and is blind to damage on the digits — which is the class the rule
exists for. `(8.L mi)` is a 1 read as an L, which this parser calls the
commonest single confusion there is: `DC` accepts the L, the bracket is
swallowed by the match, the tail begins at the address, and the leg drops
silently out of the journey. A leg's distance group that matched and produced no
number is the same statement, read from the other side.

**What they had in common.** Five of the six are places where a *per-frame*
observation was treated as a fact about the card, or where a rule could only see
one of the two shapes its own damage takes. That is the same mistake as the
missing wire fields one section down: a thing was checked on the path it was
written for and not on the path it actually runs.

Nine mutations, nine caught — including the one that mattered most, whether a
majority is really needed or a unanimity would do. It is: a leg mangled in two
frames of three and merely absent in the third is a leg the card printed a
distance for.

### The stacking advice had never once run in the car

An adversarial review of this session's work - seven independent reviewers, each
finding refuted by a skeptic told to default to "not real" - turned up two
defects that between them made the whole stacking half of the driving screen a
fiction for as long as it has existed.

**The reading did not carry where the job ends.** `Advice.stack` asks
`sameArea(active.dropoff, offer.dropoff)`, and the scanner's payload carried
`places` and nothing naming the two ends. So `offer.dropoff` was `undefined` on
every real reading, `ends` and `route` were permanently null, and the town rule,
the quadrant rule, the ZIP rule and the map link **had never fired in a car**.
Every measurement in the sections above was made on journal rows, which derive
those fields separately and therefore have them.

**The reading did not carry the target either**, and that one published a wrong
answer rather than no answer. `stack()` falls back to a target of **zero** when
it is not given a number, and `worst >= 0` is true of almost every pair - so the
stack line was painted **green, "take both", for pairs that lose money against
simply finishing the order already in the car**. `rate()` has returned both
`target` and `band` all along; they simply never reached the wire.

**Why the suite passed throughout, which is the part worth keeping.** The
end-to-end stacking test spawns the real server against a fake scanner, and the
fake was a hand-written literal that included `"target": 25.0, "band": 15.0` -
fields the real scanner did not send. The comment above it asserted that
readings carry them. The fixture supplied the very field whose absence was the
defect, and the assertions it enabled all passed.

So the fake reading is now **generated by calling the real `emit()`**, and a
short list names every field `Advice.stack` and `withStack` read off a reading.
A hand-written fixture can drift from the program it stands in for; this cannot.
Four mutations confirm it: the target dropped from the wire, the band dropped,
the dropoff dropped, both ends dropped - all caught, where before this the first
three were the shipped state.

`band` is deliberately *not* in that list. `stack()` does not read it, so an
assertion that the wire carries it would pass for no reason - and one
unbreakable entry teaches you to trust the whole list less. It is still emitted,
because the call site asks for it.

**Two more the same review confirmed.** `journal.py` called `find_dropoff` without
the card's text, so the "a place the card labelled Pickup is a pickup" rule
could not run and the commonest delivery card - `@ Pickup Crumbl / Customer
dropoff`, which names no address at all - was **stored with the restaurant as
the destination**, disagreeing with the live reading about the same card. And
`CITY_JUNK` stripped the icon row on the comma path but not on the
street-suffix path, which is the one this parser calls *the case to expect*: a
screen puts the street and town on two lines, `normalize` joins them with a
space, and the town came out as `l Atlanta` - which `PLACE_TOWN` cannot read at
all, because its junk allowance covers a single uppercase letter and not a
lowercase one.

**What this says about the rest of it.** Every geography figure in the sections
above - the 39%, the 48%, the town distribution - was measured on journal rows
and is unaffected. But no claim in them about what the *driver saw* was true,
and this file made several. They are corrected where they appear.

### Letting the driver check the map, because the rig cannot

The stack line says what it *checked* — same town, same side, elsewhere — in the
card's own words, because a town and a compass quadrant are all these cards
print. It cannot say how far apart the two jobs finish in minutes, and the
obvious way to fix that is to geocode the addresses and subtract.

**That is the wrong tool, and the reason is the failure mode.** A geocoder run
by this rig turns a misread street into a confident coordinate, and the
coordinate into a distance on the panel: wrong, precise-looking, and silent —
the failure this project refuses above all others. Feed it `Daffodll Ln` and it
answers as readily as for the real street.

Handed to a map instead, the same misreading is **a pin in the wrong place**,
which a person spots instantly and dismisses. The check moves from the machine,
which cannot perform it, to the driver, who can. And no coordinates are needed
at all: the cards name places in words — `Duval Ct & Manchester Ln, Villa Rica` —
and a map takes words.

    https://www.google.com/maps/dir/?api=1&origin=<held dropoff>
                                   &destination=<offer dropoff>&travelmode=driving

So the offers page grows `⚑ pickup`, `⚑ dropoff` and `⤳ route` on every row that
named somewhere, and the driving screen's stack line grows a `⤳ route` between
the two **dropoffs** — which is how far apart the two jobs finish, the half the
arithmetic cannot reach and the half the driver said decides it.

It answers better than the thing it replaces, too: real driving time with live
traffic, where a straight line between two ends is three miles that might be
five minutes or twenty. No API key, no rate limit, no cost. And because the
request is made by the driver's browser rather than by the rig, **no customer's
home address is sent anywhere by the rig itself** — which matters, because these
are not the driver's addresses to hand to a third party, and there are about two
hundred of them a shift.

The ampersand is why this is encoded rather than pasted: **72% of this driver's
distinct dropoffs are cross-streets**, so an unencoded `&` would truncate the
query on nearly three quarters of them.

**It refuses more than it links.** Icon-row scrap, a single letter, a pair of
bare initials — every real place has a word in it, so two letters running is the
floor. A link to a map of somewhere irrelevant is worse than no link: it costs a
press and a moment's belief, and the driver is deciding. Half of real pairs name
one end or neither, and those get no route rather than a route to nowhere.

Eight mutations, eight caught — the ampersand left raw, scrap searched anyway, a
single letter and a pair of initials accepted, a route built from one end, the
route reversed, the route dropped, and the route drawn between the *pickups*
instead of the ends.

**What this does not do:** it is a press, not a number. The panel still cannot
tell you at a glance how far apart two jobs end — that needs coordinates, and
the measurement that would justify them is in the section above. This is the
90% of the value at 5% of the risk, and it may well be enough.

### What holding a line costs, and the two rules that do not work

`Advice.advise` says where to draw the line. It never said what holding one is
*like*, and that is the half a driver actually decides on — a line is a
decision about waiting, and nothing here priced the waiting.

**The fact that reframes it: offers are not scarce.** 1,140 reached this rig
over 26 hours of scanning — **43 an hour**, and **81% of them arrive less than
a minute after the one before**. They are not one card read twice: only 1.1% of
consecutive pairs share a payout and 3.6% share both ends. Declining costs
seconds. So the line is the entire game, and three things about it are now on
the page.

**1. What each line takes, and what it costs in waiting.** Measured between
offers inside a run of scanning, so a break is never counted as a wait:

| hold out for | of what comes past | typical wait | slowest 1 in 10 |
|---|---|---|---|
| $20/hr | 24% | 2 min | 11 min |
| **$25/hr** | 9.4% | 6 min | 33 min |
| $30/hr | 4.8% | 9 min | 73 min |
| $35/hr | 2.3% | 28 min | 2.6 hours |

The lines are the driver's own target and steps either side of it, not a fixed
ladder — a table that ignores the number in their settings is answering
somebody else's question. The last column is the one that decides whether a
line is liveable: a six-minute typical wait with a half-hour tail is a
different evening from one with an eight-minute tail.

**2. The line you set against the line you keep.** These are different numbers
and only one of them is in the settings. The owner's target is $25 and the
median of what they actually ticked is **$30.20** — the top 4.8% of everything
that came past, and worth about $3/hr in the replay. Being too picky is the
failure that hides itself: it looks like standards and shows up only as an
empty evening. Silent when nothing is ticked, because the median of what merely
*arrived* is the market and not a decision.

**3. Where the clock went.** 13.6 of 26.4 scanning hours on a job that was
ticked, so **48% of the time the rig was on, the car was empty**. That is the
number a line is really chosen against. Two things it is careful about:
intervals are **merged**, so a stacked pair occupies the clock once rather than
twice (summing the trips instead gives 15.5 hours and a driver who was 59%
busy); and the clock runs to the end of the last trip rather than the last
scan, which is the rule `replay()` already states.

*And it is a ceiling on idleness, not a measurement.* An unticked trip is
indistinguishable from a break, so every one of them inflates it — the page
prints the count of silences nothing accounts for (8 on the owner's week) and
says what it is. **With no ticks at all it refuses the figure outright**: the
first version announced "100% of the time it was on, the car was empty" over a
driver who had simply never pressed ✓, with a true caveat underneath a false
headline.

#### Two rules that were tested and do not work

Both are things a driver would reasonably try, and both cost money. They are
here so nobody builds them.

**$/hr is the right thing to judge on — $/mile would cost 24%.** Replaying the
same shift under each rule, accepting the first offer that passes and then
being busy for as long as it said:

| rule | best it reaches |
|---|---|
| **$/hr at or above $22** | **$19.80/hr** |
| $/mile at or above $1.00 | $16.03/hr |
| payout at or above $7 | $14.25/hr |
| take everything | $13.94/hr |

A payout floor is barely better than accepting everything. Combining rules did
not help either ($/hr ≥ 20 *and* not a shop order came out at $19.18, below
$/hr ≥ 20 alone).

**Do not vary the line by hour — it overfits.** In-sample it looks compelling:
the best line at 12–3am is $30 and earns $29.64/hr where a flat $22 earns
$24.63, which reads as $5/hr left on the table. Held out one night at a time,
fitting on the other four:

| | |
|---|---|
| a line per block, fitted | $19.50/hr |
| one flat line, fitted | $18.93/hr |
| **a plain $22, fitted to nothing** | **$19.76/hr** |

The fitted flat line is *worse* than the unfitted one. Night-to-night swing —
$13.92 to $27.06 across five nights — swamps anything the tuning finds, and
`advise` already gives the humble answer: a plateau of $20–$25, with the
driver's $25 inside it at a cost of 1%.

**What none of this models:** the drive to the pickup. `toPickupMinutes` is
null on all 1,166 rows — Uber states the split positionally and `to_pickup()`
needs the word `away`, which appears on none of them — so every replay figure
above is optimistic in absolute terms. The comparisons between rules are fair,
since the omission falls on all of them equally.

### Where the money is, and the ranking that had to be thrown away

The driver's own request: *"find areas where it might be best to find high
paying rides, the time of day and day of the week likely also a critical
factor."* The map had no answer to that at all — it was a page for checking
whether the rig was right about where the work happened, which is a different
question and a narrower one.

The obvious feature is a league table of the places the cards named. It is
easy, it is what everybody asks for, and **it is noise.** Measured on the
owner's own week, 1,140 counted offers over five driving days, by permutation
test — group the rates, take Kruskal–Wallis H, then deal the same rates back
out into the same group sizes a few hundred times and see how often chance does
as well:

| grouping | groups | offers | p | |
|---|---|---|---|---|
| the place the card named | 19 | 163 | 0.2260 | **noise** |
| ...with a floor of 8 offers | 5 | 79 | 0.9400 | **noise** |
| the **town**, from either end | 9 | 367 | 0.0000 | real |
| the three-hour block *(control)* | 5 | 1,138 | 0.0000 | real |

All of it on the **driver's** clock. That is not a detail: this rig's owner is
at UTC-4, and measuring the same week in UTC puts every offer four hours into
the wrong three-hour block — a census of 382/220/112/0/0/0/254/198 against the
true 196/33/0/0/2/361/201/373, which would have printed "no offers" over the
second-busiest block he works. `Advice.blockOf` reads the local clock, and the
first pass of these measurements did not.

The table that would have shipped reads *Shake Shack $18.57 … Chipotle $7.27* —
a spread of $11.30 between best and worst, which sounds like a finding and is
not: shuffling those same rates at random produces a spread that big or bigger
**36% of the time**. A driver would have crossed town to sit outside a
restaurant picked by a coin toss, on a page that had told them it was the best
one. That is this project's first fault class in the one place it costs a shift.

**The town survives, and survives the objections.** Not one night out of the
metro: restricted to the seven towns seen on four or more separate outings it is
still p < 0.001. Not trip length in disguise either — tested inside each third
of the distance range separately it holds in all three (p = 0.0000 / 0.0020 /
0.0000) with Atlanta leading each one, and the best town's median trip is no
longer than the worst's: Atlanta $20.07/hr over 9.2 miles against Marietta
$14.63 over 9.5.

**And most of that spread is the clock.** A town's rate is tangled with *when*
the driver is in it: on this week the 12–3am block paid $21.24 and 3–6pm paid
$14.17, and **57 of Atlanta's 98 offers are in the first** while 40 of
Marietta's 82 are in the second. Ranked raw, Atlanta leads Marietta by $5.38 —
and a driver who drove there at six in the evening would get the six-o'clock
rate. Held at the same hours the lead is $2.45, the gap from best to worst
falls from **$6.47 to $3.69**, and three towns change places. The town still
matters (the stratified test is p = 0.002) and it matters about half as much as
it looks.

So the ranking is by what is left once the hour is held still: each offer
measured against what its own three-hour block paid across the whole list, and
the permutation confined to shuffle *within* blocks so the test asks the same
question the number answers. The median is still on the row, because what a
town paid is a fact worth having — it is just not the answer to "where should I
go". Once the driver picks a block there is nothing left to hold still, and the
page goes back to the plain median and says the plainer sentence.

`Advice.areas` groups on the town, ranks by that, prints the offers
and the separate outings behind every row — and **runs the test in the page**,
on whatever is loaded, refusing the ranking when it does not beat chance. The
thresholds above are one week of one driver; a constant tuned to them would be
wrong somewhere else without saying so. Running the test costs almost nothing:
the ranks are computed once and a shuffle only reassigns them.

What the driver sees on their own week: nine towns led by Mableton and Atlanta,
*"dealing these same rates out between these same towns at random does this well
under 1% of the time."* Pick a three-hour block and the same page
refuses: on the driver's own clock not one of the blocks he works can tell its
towns apart — 12–3am leaves a single town standing, and 3–6pm, 6–9pm and
9pm–12 come out at p = 0.18, 0.58 and 0.08. The ranking a driver would most
like to have is the one the data will not support, and the page says so rather
than printing it.

**It asks nobody anything.** The grouping is the town the rig read off the card,
never a coordinate, so the ranking is on screen the moment the offers land —
before *Place them on a map* has been pressed and whether or not it ever is. A
lookup may position one of these figures; it may never change one. That is the
rule at the head of `map-view.js`, and it is why this is the one answer on the
page that needs no network.

**Day of week, which is the half that had to be refused.** `AUDITS.md` already
settled against a weekday term in this filter, and the measurement behind that
refusal holds: a 168-hour window holds each weekday-and-block exactly once, so
every occupied cell of that grid comes off a single date. On this week Saturday,
Friday and Tuesday rest on **one outing apiece** — "Saturdays pay $16.82" and
"that Saturday paid $16.82" are the same sentence, and only one of them is
advice.

What is offered instead is the coarsest cut, in the **same box** as the hours
rather than a second box beside it — so picking *weekends* un-picks *9pm–12* and
the grid that was refused cannot be built. Weekend against weekday is 598 counted
offers on 3 outings against 542 on 2, $14.93 against $14.05, and the test puts
it at p = 0.0360 — real, and only just, which is itself worth seeing. The seven-way split needs no special-casing to refuse: the same
floor that guards every other figure here drops a weekday resting on one outing,
and what is left cannot be ranked against itself.

**What it will not tell you**, said on the page: these are the offers that came
to you where you already were. A town you have never sat in cannot appear, and
one you passed through once will not clear the floor. It ranks the places you
already work, not everywhere you could — and no amount of data from this rig can
fix that, because the rig only ever sees the offers that reached it.

### The address the card will not show you until you have taken the job

106 of the driver's 604 offer cards print **"Customer dropoff"** and no address.
Uber does not say where a delivery ends until it has been accepted. That is 18%
of every card the rig sees, and it is what drives **39% of the pairs** where the
stacking advice can say nothing:

    silent: 1 side named no dropoff at all       2968  (30%)
    silent: 2 sides named no dropoff at all       905  (9%)
    silent: a dropoff named, no town read off it  583  (6%)
    silent: both placed, only a quadrant matched  358  (4%)

**81% of the silence is "there is no address to work with."** No parser reaches
an address that is not on the screen, and no geocoder does either — so the fix
is to read the screen that comes *after* the accept. The driver presses
**⌖ Dropoff** on the driving screen and the rig reads whatever the phone is
showing as an address.

**The anchor is a state code followed by five digits,** and that choice is the
whole design. It is the one part of a US address that is short, positional and
**checkable**: `GA 30127` is a state and a ZIP or it is not, where a street name
misread by one letter is still a perfectly plausible street name and nothing
downstream can tell. A state that is not a state produces `None` and the panel
says it did not read — the ZIP is repaired from stand-ins (`3O127` is this OCR's
commonest confusion), the state deliberately is not, because repairing the check
is inventing the one token that exists to refuse.

**Why the ZIP and not a geocoder.** A geocoder returns a confident coordinate
for `Daffodll Ln` as readily as for the real one — a wrong distance wearing
decimal precision, which is the failure this project refuses above all others.
A ZIP needs no service, no network in a car, and no relevance score nobody can
calibrate. It is also the right *resolution*: a metro ZIP is a few square miles,
where "same town" in Atlanta is a hundred and thirty-five of them and **44% of
this driver's placed dropoffs are in Atlanta**.

**The integration that had to land with it.** `PLACE_TOWN` anchors on the END of
a string and a full address ends in a ZIP — so before `PLACE_ZIP` was stripped
first, `area()` of a scanned address returned **null**, and the geography would
have gone *silent on exactly the orders the scan was added to rescue*. Caught by
asking the question before writing the code, not after.

**`same-zip` only strengthens, never vetoes.** Two ZIPs that merely differ are
not evidence of distance — they tile finely, so neighbours are next door, and
concluding `elsewhere` from that would refuse stacks a mile apart. A wrong
`elsewhere` costs a fare; a wrong `near` costs an hour and a rating. So a
fine-grained key is safe for sharpening an agreement and never for manufacturing
a disagreement. How far apart two *different* ZIPs are needs their centroids,
which this rig does not have and will not guess at.

**What the grammar has to do that a regex alone does not.** A real screen puts
the street and the town on two lines, so `normalize()` joins them with a space
and there is no comma to split on. `1234 Daffodil Ln Powder Springs` has no
grammar for where the street stops, and the group takes four words back — so the
town reads as `Daffodil Ln Powder Springs` and two readings of the same street
disagree about where they are. The USPS suffix list is the break, taken at the
**last** suffix in the group: `Powder Springs Rd Marietta` puts the real break at
the later of two, and so does `Mill Run Ct Marietta` from the other direction.
Where no suffix is found the city is `None` rather than a guess — per-field
refusal, the same as a leg that keeps its minutes and gives up its distance.

Both ports agree on 772 corpus texts, 5064 damaged ones and 5700 address-shaped
ones. Twenty-one mutations, twenty-one caught — the state check removed, the
state repaired like a number, the ZIP range widened, the ZIP left unrepaired,
the first address on the screen taken instead of the last, the comma requirement
dropped, the split taken at the first suffix, the street loosened to
anything-but-a-comma, the street reaching back over the previous address, the
icon row left in front of the town, the ZIP stripped but not reported, and every
way of making `same-zip` say more than it should.

**What is still open, and it is the honest part:** none of this has met a real
post-acceptance screen. The shapes above are reasoned from what a US address is,
not measured from what Uber draws, and the one that decides the layout — whether
the full address appears at accept or only after pickup — is unanswered. The ZIP
anchor survives almost any layout; the street/city split is where a surprise
would land.

#### A read that outlived the window it went out in

`digest()` judged the window by `time.time()` at the moment the reading LANDED.
A read is over a second on a Pi, so a window closing while one was in flight
threw the answer away: the read went out with the window open, found the
address, and arrived a second past the deadline to be told it was too late.

And it is the worst second to lose. The driver who took a moment to get the
destination up is exactly the driver whose address is found by the last read of
the window — the case the window exists for.

The reader now carries the launch time back on the finished read, and the window
is judged by when the picture was **taken**. That is the only clock the far end
can honestly use.

**The check for it was vacuous first, and that is worth writing down.** The
harness replaces `time.sleep` with one that caps every wait at 10ms — which is
how the loop gets driven quickly — so a stub calling `time.sleep(1.6)` to stage
a slow read staged nothing at all. The test asserted a destination came out, one
did, and it passed for reasons unrelated to the thing it was testing. The
mutation survived all 245 checks.

It now holds the genuine `time.sleep`, captured at import before anything
patches it. Clean: 245 pass. Mutant: `a destination found by a read that
outlived its window is still the answer: got 0 want 1`.

This is the same defect class this file keeps recording, written while hunting
it: **a check that cannot fail is worse than no check, because it is counted.**

#### …and the button for it could not be reached on the path it was built for

Worth stating plainly, because it is the third time in one sitting: the scanner
end worked, the server end worked, both were tested end to end — and **the panel
never opened the door**.

The flow this feature exists for is exactly one sequence. The driver accepts on
their phone. The card vanishes from the mount. They press **Took** on the panel.
*The destination is on the phone right now.* That is the moment.

But `holdingNow` in `live.html` was only ever set from a **reading**:

    if (msg.ready) { holdingNow = !!msg.holding; showDrop(); showDest(); }

and there is no reading — there is no card. `/api/status` is fetched once, at
page load, and never polled. So `#drop` and `#dest` stayed hidden until the
**next** offer card arrived, by which time the phone is showing that card and
pressing ⌖ Dropoff photographs the wrong screen. The one feature built for the
18% of cards that print "Customer dropoff" and no address could not be used the
way it was designed to be used.

Marking is the only moment the panel can learn this in time, so `/api/offers/mark`
now answers with `holding` — through `holding(Date.now())` like everything else,
so a hold the server has already expired does not put a button back on the
panel — and the took handler reveals both controls from it, believing the server
rather than the press.

**What the test had to do to be worth anything.** The existing browser check
already pressed Took, and its route stub answered `{"ok":true}` — which is
precisely the shape that hid this. The stub now returns `holding`, and the two
buttons are measured **on the glass** after the mark: on screen, sized, not
`display:none`, not scrolled off. Reverting the handler fails both.

#### The tests covered every piece of this and none of the path

A review made the point by breaking it. Replace the body of the request branch
in the main loop with `pass`, and the branch at the top of `digest()` with
`if False and …`, and the button is completely dead — the press clears the
request file and the rig never reads or emits a destination. `test_scan_pi.py`
still printed **"All 232 main-loop checks passed"** and exited 0. `/api/dropoff`
and the server's handling of a `dropoff` line had no test whatsoever.

Every piece *was* covered: `dropoff_requested()` takes a request exactly once,
`DROPOFF_WINDOW` is a plausible number, `emit_dropoff()` writes a line with
nothing on it that could be mistaken for a verdict. Covering the pieces is not
covering the path — the same lesson as the wire fields, arriving from a
different direction.

Three separate pieces of wiring have to hold, and only the middle one explains
why the fix is not just "read once when the button is pressed":

| | |
|---|---|
| the press opens a window | the request branch in the loop |
| **the window keeps taking reads** | the beat beside the resample beat |
| an address found there goes out | the branch at the top of `digest()` |

The screen showing a destination is a **navigation** screen. It does not move,
so the motion gate scores it as nothing happening and produces no reads at all.
Without that beat the driver presses the button, brings the address up, and the
rig never looks. So the test drives a **still, blank** camera with a reader that
shows the wrong screen twice and then the address — every read in the run is one
the window asked for, and the destination is found on the third.

The server end is driven the same way `test_stacking.py` already drives the
stack: a real server, a fake scanner on the stdin contract, and the destination
line **generated by the real `emit_dropoff()`** rather than written out by hand
— the fixture rule that caught the `target`/`dropoff` wire defects. Its own
handoff directory, so the button's only effect — a file — is somewhere the test
can look for it, and so a scanner running on the same machine cannot eat the
request.

One collision is worth naming, because the shape of the payload is what survives
it. **Every reading on that same stdout already carries a `dropoff` of its own**
— a cross-street off the card, as a plain string — and the fake scanner sends
one five times a second. The server tells the two apart by `.line`, not by the
key. Told apart by the key, a scanned address would be overwritten by a
cross-street belonging to a different card within 200ms, and the test asserts
exactly that it is not.

Sixteen mutations, fourteen caught, starting with the reviewer's own two: the
press does nothing, the digest branch never fires, the window opens but is never
read through, the window never closes so the next screen overwrites the answer,
the request is never taken so the button fires forever, nothing is emitted, the
button writes no request or writes it where the scanner is not looking, the
answer never reaches the order in the car, it is stored but not marked as
scanned, and the page is never told.

**And the two that lived were worth more than the fourteen.**

The first was small: *the press does not force the first read.* It is nearly
equivalent — `last_dropoff_read` starts at zero, so the beat further down the
loop fires on the same pass anyway. Nearly, not quite: a *second* press within
half a second of the first window's last read would wait for the beat. Half a
second, not worth a timing-sensitive test, and now written down in the code so
the line is not deleted as dead on the strength of the first press alone.

The second opened up a real defect.

#### One question, four different ways of asking it

The mutation was *attach the destination even with nothing in the car* — invent
an order for the address to land on. It survived, and the reason it survived was
the interesting part: the test asked `/api/status`, which answers through
`holding(now)`, and `holding()` refuses an object with no positive stated time.
The fabricated order was invisible *exactly where the assertion looked*.

Following that back, **four places read `scanner.holding` raw** while everything
else asked `holding(now)` — and they are not the same question. `scanner.holding`
is the slot; `holding(now)` is "is an order being carried *right now*", and it
expires one whose stated time has run out, plus half again, plus ten minutes.

| | reads the slot | should ask |
|---|---|---|
| the scanner-read attach | `if (scanner.holding)` | `holding(now)` |
| `/api/dropoff` | `holding: !!scanner.holding` | `holding(now)` |
| `/api/delivered` | `wasHolding: !!scanner.holding` | `holding(now)` |
| un-marking an offer | `scanner.holding.id === note.id` | `holding(now)` |

So an order the panel had already forgotten was still an order to three of these.
Press **⌖ Dropoff** and the page says yes, there is a job to attach this address
to. Press **dropped off** and it says you put one down. Neither is true, and the
screen in front of the driver has been showing no order for an hour.

**Why it had never been caught, and it is two obstacles rather than one.** Ten
minutes of grace is ten minutes of waiting, so every path was only ever checked
on orders plainly still alive — `HOLD_GRACE_MS` is now settable, the way
`SCANNER_SILENT_MS` already was, and the suite runs with it at zero. And a live
scanner sends a reading five times a second, every one of which goes through
`withStack` and therefore through `holding()`, which expires the order as a side
effect — so within 200ms the raw slot is null too and the two ways of asking
agree again. The fake scanner needed a way to go **quiet**. That is not a
contrivance: a camera side that has died, with no panel open polling it, is
exactly the shape of the real failure.

One more trap, met twice while writing it: `holding()` **nulls** an expired order
as it answers, so the first endpoint asked properly hides the difference from
every endpoint asked after it. The checks now use one order per question, each
asked first.

Eight mutations of the corrected code, five caught, and **three are equivalent
by construction — which is what the fix was for**: with every reader asking the
same question, an invented order is unreachable, a field written onto an expired
one is unreachable, and un-marking reaches `scanner.holding === null` down both
paths (the raw version nulls it; the correct version's `holding()` already did).

### A guard that could not fire, because the damage removed its own evidence

`legs_short_a_distance` exists for one failure: a two-leg journey where one
leg's distance did not read, so the sum is a whole journey's *time* against part
of its distance. The missing miles are missing **cost**, so the rate comes out
too high — the one direction that turns a pass into a green accept.

It fired on **one of the driver's 604 cards**, and on **none** of 1080 readings
with a leg's distance deliberately broken. Not because the damage is rare, but
because of what the rule counts. A leg is part of the journey if it states a
distance or if the card *labelled* it one, and `LEG_TAIL` is a word list —
`away`, `trip`, `total`. This driver's ride cards do not use those words. They
label a leg with an **address**:

    $21.08   5 min (1.8 mi) Grace St & Main St, Kennesaw
             12 min (8.1 mi) Oak Ln, Marietta

Both legs count as travel purely because they carry distances. The moment one
loses its distance it drops out of the set the rule counts, the count falls to
one, and the rule returns False. **The damage removed the evidence of itself.**

What that cost, measured: of 1061 readings with one distance broken, **845
published a higher rate than the truth with nothing flagged, and 289 crossed a
verdict boundary** — a $17.30/hr pass shown as a green $29.34/hr accept, a
$22.50/hr close call shown as $34.36/hr.

**The third clause.** A leg is also part of the journey when a distance is
printed beside it that did not read — a bracket sitting where the distance
should be, on a leg that has none. That is grammar, not vocabulary, and it is
what a wait line, a promo chip and an ETA badge do not have.

The whole rule is in where the bracket sits. It must be the **first** thing
after the minutes:

    20 min (7.3 m1) trip                    <- the bracket is this leg's
    Avg. wait time at pickup: 1 min 9 mins (2.6 mi) Sedgefield Rd

A bracket appears in the wait line's tail too — it belongs to the leg after it.
Searching the tail loosely fires on **43% of clean cards**, which is worse than
the version this rule already rejected for firing on a third of them. Anchored,
it fires on 3%, and every one of those is an `Add a delivery` card whose
distance really is printed and really did not read.

**The measurement that changed the design.** The first version also required a
digit inside the bracket — a second belt, and a hole: the number is exactly what
the damage removes, so `9 min (~ mi)` carries no digit to find. Over 3466
readings damaged four different ways, the digit clause **halved** what the rule
caught, 2096 down to 1052, and bought nothing — both versions fire on zero of
the 604 clean cards. It was measured against one kind of damage and would have
shipped looking fine.

**What it does:** 845 optimistic-unflagged readings fall to 337, and the verdict
crossings from 289 to 109. Not one clean card is newly doubted. Both ports agree
on all 771 clean and 5064 damaged texts, every field.

**What is left, and it is now the bigger half:** 335 of the remaining 337 have a
**single** leg, which the rule exempts on purpose because a single leg can be a
total — `$7.09 34 min total` states no distance and is a whole journey by itself.
`lostMiles` can tell those apart too, and that is the next piece of work rather
than a clause bolted onto this one.

#### …and that piece of work, done

The exemption was never about the **count**. It was about not being able to tell
a total from a leg whose distance failed to read — and `lostMiles` is exactly
what tells them apart: a total prints no bracket where a distance would go, a
damaged leg still has one.

So the single-leg case is now asked the same question as the rest, plus one
guard:

```python
if len(legs) == 1:
    return bool(legs[0].get('lostMiles')) and miles is None
```

**The `miles is None` clause is the whole risk, and it is not a belt.** The
`Add a delivery` cards have one leg whose distance did not read *and* a lone
distance the branch further down `parse()` recovers a few lines later — so they
end up with the **right** number. Doubting those would throw away a good
reading, which this project treats as exactly as bad as publishing a wrong one.

That is also why the call **moved**. It used to sit beside the leg sum, where
the only distance in scope is what the legs carried; on an `Add a delivery` card
that is `None` for a few more lines and the rule would have doubted every one of
them. It is now asked below the lone-distance branch and below `check_distance`,
where `miles` is what the reading actually ended up with. The merge had to move
the same way — `accumulate.py` asks it of the **merged** distance, not of the
merged legs alone, and that is a second place the same mistake was available.

**What it does,** measured against four kinds of OCR damage rather than one:

| | |
|---|---|
| damaged readings still publishing an optimistic rate that it catches | **828** |
| readings it newly doubts that were **not** optimistic | **4** |
| clean cards newly doubted | **2**, and both are genuinely damaged — `(g3 mi)` and `(+0 mi)` — and already carry no distance |

The four it clips are the cost, and they are cheap: every one shows the *same*
rate before and after (`$16.29 no → $16.29 no`, `$24.15 warn → $24.15 warn`), so
what changes is a doubt marker, not a verdict.

Twenty-three mutations, twenty-three caught, across both ports and the merge —
the clause removed, never fired, always fired, the `miles` guard dropped,
inverted, and (in JavaScript) narrowed to `null` so a missing argument slips
past; `lostMiles` dropped, `labelled` swapped in for it, `isTotal` made an
exemption; `parse()` not asking, asking without the distance; `is_whole` asking
without it; the merge not asking, and asking without the merged distance. Three
of those survived the first run — the two "a caller that forgets the argument"
mutants and the merge one — and each got a fixture rather than an argument.
`legsShortADistance` is exported from the JavaScript port for that reason: every
shipping caller passes `miles`, so nothing reachable through `parse()` exercised
the default, and a default nothing exercises is a default nobody checked.

Nineteen mutations of twenty caught, across both ports and all three hops the
field takes — the clause removed, the anchor dropped, the anchor loosened to let
another leg's minutes through, the digit clause restored, the field forced true,
forced false, set on a leg that has its distance, dropped from `legDetail`,
dropped from the merge, and ANDed there instead of ORed. The survivor is the
gap width, `{0,3}` against `{0,8}`: **zero differences across 4070 readings**, so
it is arbitrary and is written down as arbitrary rather than pinned by a fixture
invented to make it look otherwise.

### The decimal point that belonged to a number it was no longer attached to

Three fields on a merged reading were still being taken from whichever frame
arrived last. Two of them decide whether the distance may be divided by ten:

* **`milesChecked`** says a duration stood beside the distance when
  `check_distance` ran, and it is the gate on `rate()`'s second attempt. It is a
  fact about the *merged* minutes, so a frame that lost the leg and arrived last
  could report `False` on a window that had a duration — opening a recovery on
  the **sum** of the legs, which is the one thing the merge deliberately
  forbids: dividing a sum by ten is not a correction any single misread can
  justify.
* **`milesHadDecimal`** says the card printed a point, which is what stops a
  card that really reads `10.0 mi` being "recovered" to `1.0`.
* and the **lone distance** — the one no leg claimed, the `Add a delivery`
  shape where a plus inside the bracket defeats the leg's own distance group —
  was not voted on at all. Everything else that moves money is: the minutes, the
  legs' distances, the item count, the deadline. This one was whatever the last
  frame said, and it is the one number with no leg duration beside it for
  `check_distance` to catch a misread with.

**Voting is not enough, and the obvious fix is wrong.** The natural move is to
OR `milesHadDecimal` across the window, the way `hasTotal` and `labelled` are
ORed: one frame seeing the point is enough, and losing it is what a glare frame
does. That is right for a distance off the legs and **backwards** for a lone
one. Take a card printing `2.4 mi`, read as `24 mi` by three frames of four.
The vote publishes 24 — and the single frame that saw the point would, under an
OR, be enough to tell `rate()` the card printed one, which is exactly what
forbids recovering the 24 back to 2.4. The flag would use one frame's evidence
of the error to block the fix for it.

So the point travels **with the winning reading** rather than across the window:
`self.lone_miles` holds `(miles, had_decimal)` pairs, and the published flag is
what the frames that read the winning value said. It comes out right in both
directions — if 24 won and none of those frames saw a point, recovery is allowed
and lands on 2.4; if the card really says `24.0` and one frame dropped the
point, the frames that read 24 still carry it and recovery stays forbidden. A
distance off the legs keeps the OR, where it decides nothing: a leg carries its
own minutes, so `milesChecked` is `True` and `rate()` never asks.

**Reach: zero, measured twice.** Replaying all 604 real frames through the
accumulator in their recorded time order, before and after, moves **not one of
604 readings** on any of sixteen fields, nor the verdict, nor the rate. Planting
the damage this exists for — the decimal point stripped from one, two and three
frames of the same card, 559 damaged replays — gives the identical 545 repaired
/ 1 flagged / 13 wrong before and after. This is a hole closed, not a bug
repaired, and the tests are synthetic because the corpus cannot reach it.

**Why the corpus cannot reach it,** and a caution about a number this file will
not print: these 604 texts are *distinct* texts, one per journal row after
deduplication, so a card read eight times with the same result appears once.
That makes almost every offer in this corpus look like a single frame, which
would say the merge is idle on 98% of cards — and it is an artifact of the
export, not a fact about the rig. The `scans` column added on 2026-08-30 keeps
every frame; it is what will answer the question, and until it does the question
is open.

Twenty-three mutations, twenty-three caught: the flag reverting to the last
frame, `milesChecked` reverting, inverted, pinned true and pinned false, the
point ORed across the window and ANDed across the winners, forced true and
forced false, taken from the first and from the last lone frame, the lone
distance taken from the first frame, the last, the smallest and the largest,
consulted when the legs already had one and never consulted at all, and the
window's own OR turned into an AND. Fifty-four new checks, most of them asserting
the *property* — that every arrival order of the same frames merges to the same
thing — rather than a case, because the defect was the order dependence itself.

### Six invisible characters deciding whether a road is an offer

The two parsers are held to one corpus, and the corpus is text. Whitespace is
where that stops being enough: **Python's `\s` is Unicode and JavaScript's is
not**, and they disagree about exactly six characters — U+001C to U+001F and
U+0085 collapse in Python only, U+FEFF in JavaScript only.

`normalize()` runs `\s+` in both ports, so a card carrying one of the six
arrives as two different strings and every rule downstream reads a different
card. It reaches a published number, and in both directions. The map screen two
sections down is refused because a payout is never glued to a unit — and with
one space swapped:

| the character between `22` and `min` | the Pi | the browser |
|---|---|---|
| an ordinary space | refuses it | refuses it |
| U+0085, U+001C–U+001F | refuses it | **publishes a $22 offer** |
| U+FEFF | **publishes a $22 offer** | refuses it |

Whichever port collapsed the character does the right thing and the other rates
a road. Same card, same rule, two answers — decided by something with no
appearance at all.

So each port is told about the other's set and both collapse the union. No card
on file carries any of the six, so this is a hole closed rather than a bug
repaired; the corpus now holds all six, which is what keeps it closed. Five
mutations, five caught, including each port reverting to its own language's
idea of a space.

### Does the second order END anywhere near the first?

`stack()` has always answered half the question. It knows what two jobs pay
together and returns an honest RANGE — `worst` where the times simply add,
`best` where the new job rides along inside the old one — because which of those
is true depends on geography it could not see. This is that missing half.

The driver put the requirement precisely: *"close enough so that I don't take two
orders that end up in completely different places"*. Not a distance. A veto.
And: *"the drop off locations will always pretty much be someone's home address
and not the restaurant"*, which turns out to be the rule the parser needed.

**Which end is which.** `find_places` returned an unlabelled list, and on some
cards the last entry is the merchant. A shop is a name the card bracketed —
`Kroger (Shiloh Square)`, `GoPuff (Drive)`, `McDonald's® (Wade Green)` — so the
dropoff is the last place that is *not* bracketed. Over 562 cards naming any
place, the last is a bracketed shop on 9, every one a card where only the
merchant read at all, so the honest answer there is nothing rather than a
restaurant. A ride card names the pickup street then the dropoff street, so the
last is still the end; an address split across two entries leaves the tail last,
which is the half carrying the town.

**Where a place is, as coarsely as the card allows.** Two signals, both printed:
the town after the last comma (65% of places) and the compass quadrant these
addresses carry (47%). A town alone is far too coarse — Atlanta is 250 of the
960 places on file — and the quadrant is what splits it: the Atlanta dropoffs
run NE 50, NW 20, SE 10, SW 5. Together they are about the granularity of *side
of town*, which is what was asked for.

**Deliberately asymmetric**, because the two mistakes cost different amounts. A
wrong "elsewhere" costs a stack that could have been taken. A wrong "near" costs
an hour, a late delivery and a rating. So `near` is said only when the two agree
on everything they both state, and `elsewhere` the moment they disagree on
anything. A shared quadrant with no town is a whole side of the metro and
promises nothing.

Measured against the driver's own stacked pairs — every one correct:

| the two dropoffs | verdict |
|---|---|
| Park Pl, **Atlanta** → Cobalt Dr **NW, Atlanta** | near |
| Cobalt Dr NW, **Atlanta** → E Twin Oaks Dr SE, **Smyrna** | elsewhere |
| Cochran Ridge Rd, **Hiram** → Chastain Meadows Pkwy NW, **Marietta** | elsewhere — the twenty-mile pair |
| Luckie St NW, Atlanta → *Taco Bell (930 Spring Street)* | nothing said |

It says **what it checked**, not how far apart they are, because how far apart
they are is not something these cards can support. A town and a quadrant that
both agree is `same side of town`; a town alone is `same town`, a weaker claim
reported as one. That distinction was not there at first, and the data insisted
on it: **354 of the agreeing pairs on file are Atlanta NE to Atlanta NE**, and
northeast Atlanta is not a neighbourhood. The word "nearby" was a promise the
cards cannot keep. The driver knows which of their towns are big; the rig should
not pretend to.

Over all 10,007 pairs of offers that appeared within twenty minutes of each
other: **39% elsewhere, 8% same town, 5% same side of town, 48% nothing said.**

That last number started at a worse place. Of the 135 dropoffs the rig could not
put on a map, **112 were not dropoffs at all** — they were shop names the card
had labelled, standing in for somebody's front door. `PLACE_IS_A_SHOP` only
catches a *bracketed* name, and the commonest delivery card prints `@ Pickup
Crumbl` with no bracket and nothing else. So the card's own label decides it
now: a place printed after the word "Pickup" is a pickup however it is named.

The discriminator is the card's layout rather than a list of separators. Between
the label and the shop there is nothing but marks — `@ Pickup |`, `@ Pickup 3)`,
the icon row the crop catches. Between the label and a *later* leg's address
there is always a leg, and a leg is spelled with letters: `at pickup: 1 min
10 mins (4.6 mi) N Cobb Pkwy NW`. So "no letters in between" is the whole rule.

A character window sat beside it and was deleted: on all 604 cards the two
agreed exactly, so the number was a second thing to get wrong rather than a
second guard — and with it gone, every mutation of the rule is caught.

Two smaller reads came with it. A town can follow a full stop, because a street
abbreviation eats the comma (`Sagamore Ct. Dallas`), and a short run of icon-row
junk can sit between the two (`Hidden Forest Ct, } Marietta`, `New Towne Dr, , :
Powder Springs`). Fifteen more towns read, none of them false. Together:
unplaceable dropoffs **135 → 25**, and the pairs the rig can call rose from 50%
to 52%.

The 48% that remain are the honest limit — cards where the dropoff carried
neither a town nor a quadrant — and saying so is better than a guess that costs
an hour.

The journal and the CSV export record both ends beside `places`, so a shift can
be replayed through `sameArea` afterwards and the rule argued with on real data
rather than on the four pairs above. That is not decoration: the pairing itself
lives in the web server's memory and never reaches a file, so without the two
ends written down a test shift produces no evidence about this feature at all.

One trap worth writing down. A quadrant has to be a word of its own. 28 of the
places on file contain an ALL-CAPS word — `HOME DEPOT 0156`, `GOODFELLAS PIZZA &
WINGS`, `MIDTOWN` — and **KENNESAW has an NE inside it**. Without the word
boundary a shouting town donates a compass point it never printed, and two
dropoffs in the same town read as opposite sides of it. Twelve mutations, twelve
caught, and that one needed a test of its own.

#### The same icon, in the other case

The junk allowance in front of the town took a non-letter glyph *or a single
**uppercase** letter*, because the card's icon row lands between the comma and
the town. That is not a rule about towns. It is an accident of which glyph
tesseract picked for the same mark:

    Crestmont Pkwy & Haygoode Dr, E Marietta          <- read
    Daffodil Ln & Lilac Springs Dr, j Powder Springs  <- silent
    Grant Dr NW & Russell Dr NW, i Kennesaw           <- silent
    Campus Loop Rd NW & Owl Dr, a Kennesaw            <- silent

`area()` returned **null** on 25 of the 1528 places on file — no town, no
verdict, nothing on the stack line — with the town printed perfectly plainly
beside a piece of furniture. `offer_parser.py` has carried a comment about this
exact asymmetry since the address reader was written (it strips the junk with
`CITY_JUNK` on the address path for the same reason); this is the other half of
it, on the path the cards themselves take.

No US town name is preceded by a standalone one-letter word, so nothing real is
skipped, and a whole lower-case *word* is still refused — `Cobalt Dr NW, near
Marietta` reads no town, because a word there is either part of the name or
evidence this is not an address. On the driver's 210 distinct dropoffs it places
three more and moves **414 pairs off "cannot say" onto an answer** — 382
`elsewhere`, 32 `same-town` — while changing no answer that was already given.

#### The word after the town

`PLACE_TOWN` allows a *second* capitalised word, because towns have them —
Powder Springs, Sandy Springs and Lithia Springs are all on this driver's
cards — and it anchors on the END of the string. So one more capitalised word
out of the OCR simply joins the town:

    Cobb Pkwy NW, Acworth Page
    Canton Pl NW, Kennesaw State
    Farmington Dr SW & Hereford Ct SW, Marietta BORE
    Rd) Riverside Pkwy & Silverton Trl, Austell Chipotle

**21 of the 73 distinct town readings on file are a real town with a junk word
stuck to it,** and one more is the mirror — `sandy`, where the card said Sandy
Springs. Between them they were turning **96 pairs** of real dropoffs into
`elsewhere` on nothing but OCR damage: a stack refused for a job in the same
town.

Dropping the second word is not the fix. The regex anchors on the end, so
`Sandy Springs` would then read as `springs` and the two readings of it would
stop relating at all. What every one of these has in common is that **one
reading is the other plus or minus a whole word at the end** — and that is the
test. The word boundary is what makes it safe: Douglas and Douglasville are two
different Georgia towns, 150 miles apart, and this does not join them.

**It only ever withdraws an `elsewhere`; it never manufactures a `near`.** Over
every pair of the 210 distinct dropoffs on file, 96 pairs move from `elsewhere`
to *null* and **nothing else moves** — no new `same-town` is created, and not
one of the 22 town pairs it stops calling `elsewhere` is actually two different
towns. Reporting them as `same-town` instead would have been the easy version
and the wrong one: it stakes the expensive mistake — an hour and a rating — on a
guess about OCR damage, where silence costs a fare and is what this line already
gives on half of real pairs. Getting past the town veto is not the same as
agreeing, so these land in the branch that says nothing, alongside "a quadrant
on its own is a whole side of the metro".

Nine mutations, nine caught — the rule removed, always true, never true, the
word boundary dropped so Douglas joins Douglasville, the prefix looked for at
the wrong end, the two sides not sorted by length so it only works one way
round, and both ways of promoting "might be one town" into a claim that they
are near.

**Both geography fixes together,** over every pair of the 210 distinct dropoffs
on file:

| | before | after |
|---|---|---|
| cannot say | 12314 | **11996** |
| `elsewhere` | 8913 | 9199 |
| `same-town` | 414 | 446 |
| `same-side` | 304 | 304 |

318 pairs move off silence onto an answer — and the movement *inside*
`elsewhere` matters more than the total: 96 pairs that were being called far
apart on nothing but a junk word now say nothing, and 382 that were saying
nothing now have a town to compare.

### A control that stopped being a control

Once a destination had been read, the **⌖ Dropoff** button's label became the
address it read. The review called this "overflowing across its neighbours in
the bottom bar". Measured, that is wrong — nothing overlaps, the bar does not
scroll and the page still fits. What actually happens is worse in a quieter way.

The bar is a grid of **equal columns** and there are six or seven of them, so on
the rig's own 800x480 panel each button is **122px** wide. A 42-character
address needs **238px**. The driver got `1234 Daffodil L…` — which is neither a
label saying what pressing it does, nor an address they can check.

I was wrong about the remedy first, too: I measured "408px of unused bar" and
thought the button could simply grow. That summed three of the bar's *six*
visible buttons. Six columns of 122px plus five 8px gaps is 772 of 774. **The
bar is full.** There is no width to win.

So the answer is said in **colour** — which this panel already trusts a driver
to read before they read words, and which costs no width at all. The label stays
`⌖ Dropoff`; a `done` class turns it the same green the verdict uses for yes.
The address itself goes where there is room: the button's `title`, and the stack
line's own geography. And it is put on `aria-label` as well, because a colour is
the only thing that changed and a screen reader cannot see one.

One thing this does **not** fix, and it is worth naming: at 480x320 the column
is 69px and `⌖ Dropoff` alone needs 74, so that label is clipped on the small
panel whether or not anything was scanned. That is the bar being over-subscribed
at that size, not this feature, and it is a different piece of work.

### A fix that measured worse than the defect, and was not made

A review found a real structural inconsistency in the merge: `merged['places']`
is rebuilt from the union across frames, but `merged['dropoff']` and
`merged['pickup']` are still whatever the LAST FRAME parsed. That is the defect
shape this project names in its own principles — *a per-frame observation is not
a fact about the card* — and it feeds the order in the car, so it feeds the
stacking geography and the pairing rows.

The obvious fix is one line: recompute `dropoff` from the merged places, the way
`journal.py` already does. **Measured against 238 real multi-frame offers, it
makes things worse.**

| | |
|---|---|
| dropoff unchanged | 200 |
| gained one it currently lacks | 15 — **11 of them merchant scrap** |
| changed to a different one | 23 |

The gains are the tell: `Little Caesars Ss Maret`, `Chili's Grill & Bar (6
items) te ele eee)`, `cls) Ct)`, `Papa John's Store 414 AME ne`. The union of
every frame's places is a bag containing every misreading any frame made, and
`find_dropoff` picks from it by position, not by confidence — so it reaches for
the restaurant when the customer's street was the thing that failed to read.

And two of the 23 changes are outright destructive:

    Cherry St NE, Marietta               ->  Vella Gir 000%, Renan
    10th St NW & Williams St NW, Atlanta ->  Dabbs Xing & Shepard Ct, Acworth

A different address, in a different town, presented as where the job ends.

**Voting instead of unioning is worse still.** Take `find_dropoff` of each
frame's own places and keep the majority: 215 unchanged, 4 gained (two of them
scrap) and **14 real destinations lost**, because OCR of a street almost never
agrees byte-for-byte across frames and a strict majority never forms.

So the question became: *does any of this reach the driver?* The stacking advice
reads exactly one thing off a dropoff — `area()`. Over the 124 offers where any
frame named one:

| | |
|---|---|
| every frame agrees on the town | **108** |
| only one frame named a town | 1 |
| no frame named a town | 9 |
| frames **disagree** | **6** |

And five of those six are the junk-word shape `couldBeOneTown` already treats as
one town: `austell` / `austell res`, `atlanta` / `atlanta eater`, `mableton` /
`mableton perot`, `marietta` / `marietta bore`, `lithia springs` / `lithia`.

**One offer in 124 is a genuine disagreement.** Every fix measured costs an order
of magnitude more than that. So the code is unchanged, and this is written down
so the next person to notice the inconsistency does not spend the afternoon
re-deriving it — the inconsistency is real, and correcting it is not free.

#### Two more of the same shape, measured and left alone

**`uncosted` never reaches the stack line.** `rate()` computes it — a rate with
no mileage deducted, because the distance could not be trusted — and uses it to
withhold green from the verdict panel. It is emitted nowhere, so `stack()` has
never seen it and can paint a pair green off the same rate the panel above it
deliberately would not. Real, and structurally the same mistake as the wire
fields this file already records.

Measured: **5 of 892 offers are uncosted, and 1 clears the target** — so one
offer in 892 could show amber above and green below. Worth knowing; not worth a
change that has to be got exactly right in the expensive direction.

The reason it is now this rare is worth recording on its own. An earlier note in
this file measured *52 of one shift's 121 offers* as `milesUncertain` and *108
of 202* as uncosted. Over the 892 distinct card texts on file the same parse
gives **3 doubted distances and 5 uncosted rates**. Not a like-for-like
comparison — those were merged readings from single shifts and these are single
frames — and single frames should look *worse*, not better. The leg recovery,
the distance checks and the single-leg clause did that.

**`stack()` divides by stated minutes, not billed minutes.** On a shop-and-
deliver card `rate()` bills extra minutes for the shopping and can return PASS,
while `stack()` divides by the smaller stated figure and can return green for
the same card. The mechanism is real. It needs `secondsPerItem` set and an item
count on the card to bite at all, which is why it has not been seen; it is
recorded here rather than fixed blind, because changing which minutes the
pairing divides by moves every stacked figure on the panel and that is not a
change to make without a shift's data to check it against.

### The offer card still on the phone is not the destination

The destination window opens the instant the button is pressed, and the driver
*then* has to get the address up — so the first reads of almost every window are
of the offer card still sitting there. That was safe only because an offer card
yields no address, which this file asserted in a comment:

> None on every one of the 604 offer cards on file.

**True of that corpus. Over the 900 texts on file now it is five.** A merchant's
branch address carries the same `, ST ZIP` anchor a real address does:

    800 Forrest St NW, Atlanta, GA 30318      <- off a Delivery card, twice
    100 Rosemont Ct, Hiram, GA 30141
    2603 E, GA 30106                          <- and two fragments
    Austell, GA 30106

Any one of them ends the window with the wrong answer *and stops it looking* —
the first address found wins. The order in the car is then recorded as ending
where it started, the stack line compares the next offer against a restaurant,
and the pairing written to the journal calls it `scanned: true`: a full address,
confidently wrong, which is the expensive direction.

**A measured claim in a comment goes stale as the corpus grows, and this one was
load-bearing.** The destination scan trusted it and had no guard of its own.

The guard is the payout. *A screen with a payout on it is an offer, not a
destination* — grammar, not a phrase list, and it costs nothing because a
navigation screen has no payout to lose. All five of those cards carry one, so
it closes the path completely. The comment in both ports now says what the data
says.

My own first attempt at this overstated it: synthetic cards like `Dollar General
(925 Shiloh Rd Nw, Kennesaw, GA 30144)` made it look like *every* delivery card
leaked its merchant address. Real ones print `Dollar General (925 Shiloh Rd Nw)`
with no state and no ZIP, so the anchor never fires. Measuring turned "this
happens constantly" into "this happens 5 times in 900" — still worth closing,
but not the thing the synthetic test claimed.

### A shift driven to test the stacking advice was a test of nothing

The offers reach the journal. The marks reach the journal. **The advice did
not.** The stack line was computed in the web server's memory, painted once, and
lost — so after a shift the file held what every card said and which ones the
driver took, and nothing whatever about what the panel had told them.

Which makes the only question worth asking unanswerable: *when it said take
both, was it right?*

That is not a gap in the analysis, it is a gap in the experiment. A shift driven
to test this feature produced no evidence about it.

So a pairing is now written down at the moment it is made — one row per offer,
`kind: 'pair'`, alongside the marks and the rules:

```
held   pay, minutes, dropoff, SCANNED, heldMs
offer  pay, minutes, dropoff, pickup
stack  pay, worst, best, minMinutes, maxMinutes, state, sure, ends
```

Everything a person needs to grade one decision without having been there: both
ends, both payouts, the range the panel drew, the colour it drew it in, and the
geography verdict. `held.scanned` is the other half — whether that destination
came off the card or off the **⌖ Dropoff** scan, which is the difference that
button exists to make and the thing most worth measuring.

**A null stack is recorded as null rather than skipped.** "How often can it say
anything at all" is the question this feature lives or dies by, and a file that
only contains the times it spoke would answer it wrong.

Written **once per offer**, where an offer goes on the record — not in
`withStack()`, which runs five times a second for as long as the card is on the
phone. Best-effort: a journal that cannot be written must never stop the panel
answering. The advice is the product; this is the notebook.

**And the sync had to learn it, or the whole thing was pointless.** A pairing
has an id and no `seq`, which is exactly the shape `syncKey` rejects — the same
failure its own comment already records for marks, where "a shift's worth of
tags went nowhere, silently, under a malformed count nobody looks at". Without a
`pair` branch every one would have been dropped on the way to the box at home,
which is the only machine where a shift gets analysed. Reverting that branch
fails four checks; reverting the recorder fails the pairing outright.

### The stack line said two things and could show neither

The line that answers "can I take both?" had **no browser check at all**, which
is how it shipped as one `nowrap`, ellipsised string with the map link appended
as a child element. Measured on the rig's own panel:

| | 800x480 | 480x320 |
|---|---|---|
| text wanted / box | 784px / 750px | 754px / 434px |
| `⤳ route` box, relative to its parent | 34px outside | **235px outside** |
| `elementFromPoint` at the link's centre | the link | **nothing** |
| `#places` height, for a 15px font | **9px** | **0px** |

Three separate failures, one cause each.

**Both of the things this line alone can say were at the END of the string,** so
both were the first thing the ellipsis ate. `ENDS ELSEWHERE` went first, leaving
amber — and amber already means "the range straddles your target". The driver
was shown one colour standing for two different claims, with the words that tell
them apart cut off. That is the claim that costs an hour when it is missed.

**An inline-block child of an `overflow: hidden` box is laid out past the edge,
not wrapped.** So the link — the one thing on this panel a driver is meant to
press — had its box entirely outside the parent on the small panel, where
`elementFromPoint` at its centre found nothing at all. It could not be pressed.

**And a flex item with `overflow: hidden` has no automatic minimum size.** Both
the address and the stack line have it, to ellipsise — so in the verdict column
both were shrinkable to *nothing* while the 125px rate block beside them kept
every pixel. The address of the job, on the one screen a driver looks at while
deciding, drew nine pixels tall for a fifteen-pixel font.

It is now a flex row with the priority stated: the arithmetic shrinks and
ellipsises, because the same figures are on the panel above it; the geography
and the link never shrink, because nothing else says them. The geography became
a **chip** rather than more words in the same run — the complaint was that one
colour meant two things, and a shape the arithmetic cannot take is readable at a
glance in a way another shade is not. And the one-line facts are `flex: none`,
because there is no such thing as most of a line.

Ten checks on the glass, at both panels, measuring what a driver can actually
see and reach: the row unclipped, the arithmetic actually giving way (or the
rest proves nothing), the chip and the link inside their box and
`elementFromPoint`-reachable, and the address at a full line. Reverting the
layout fails ten of them; reverting the `flex: none` fails two more at 0px.

### Two ways the rig could go quiet and never come back

Both in `startScanner()`, both found by an adversarial review of the lifecycle,
and both cost a whole shift rather than one offer.

**The retry that was never scheduled.** When a process runs out of file
descriptors there are none left to build pipes from, so `spawn` returns a child
whose `stdout` and `stderr` are undefined. The guard for that writes
*"Retrying."* and returns — and it returned **before** the `'close'` handler
that schedules the retry was attached. So nothing retried. `scanner.proc` stayed
set, `/api/status` kept answering `running: true`, the panel kept its green dot,
and the rig read nothing for the rest of the shift with "Retrying." in the log
and nothing retrying.

The comment sitting above it said the close handler *"only ever needed the
chance to run"*. The code returned past it. A comment describing a fix the
control flow skips is worse than no comment: it is why nobody looked again.

Handlers now go on immediately after the spawn, before any guard can return.
Checked structurally — the ordering, asserted on the source — and labelled as
structural, because nothing a test can do to this server makes `spawn` hand back
a child with no pipes. The choice was that check or none, and this failure is
too expensive to leave unwatched.

**The order in the car, thrown away by a restart.** `startScanner()` cleared
`scanner.holding` and `scanner.offer` on every start. The watchdog kills a
scanner blocked in the camera driver roughly every minute it stays blocked — so
a wedge mid-delivery took the order with it: the stack line went silent for the
rest of that delivery, and Drop and the destination scan vanished off the panel
with a job still in the car. That is the one time the pairing advice is worth
anything.

The distinction the code was missing: `started`, `error` and `heardAt` are facts
about the **process**, and a new process makes them false. The order in the car
is a fact about the **driver's car**, established by their own press of "Took".
A camera that crashed says nothing about whether there is food on the back seat.
Both already end on their own terms — `holding()` expires an order on the card's
stated time, and the offer is served with an age the panel judges for itself —
so neither needs a restart to end it, and a restart is the wrong reason. They
are set up once, where the object is built, and `startScanner()` does not mention
them.

Driven for real: the watchdog suite marks an offer taken, lets the scanner wedge,
and checks the order is still there after the replacement starts. The fake
scanner emits that offer on its FIRST start only, so "the order survived" cannot
be confused with "the replacement said it again". Reverting the fix fails all
three.

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
open: a lone distance that reads too *small* is still unguarded in both
versions, since `check_distance` only ever divides. The other two are done —
`legs_short_a_distance` firing zero times on all 604 cards is fixed four
sections up, and the third one on this list — the accumulator
not voting on a lone distance, so the $15.60 GoPuff card published 1.9 miles in
two of six arrival orders — is fixed three sections up, along with the two flags
that decide what may be done to the number it publishes.

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
look it up.

*And the check written to stop that happening again could not see the two
reasons that were forgotten next.* It derived the list from
`inspect.getsource(doubt)`, which finds four of the six: `leg` and `screen` are
decided in `rate()`, not in `doubt()`, and are assigned rather than returned. So
the panel had no name for `leg` for as long as `leg` existed, under a sentence
here saying the next reason could not be forgotten. Both parser ports now carry
`DOUBT_REASONS`, `rpi/test_lint.py` holds that list against what `doubt()` and
`rate()` can actually produce, and it asks each of the **seven** surfaces that
turn a reason into words — the panel, the rig's voice, the driving screen and
its voice, the phone scanner, the keypad and the keypad's refusal toast — to
cover every reason it can be given and none it cannot. Every one of them was
missing a different entry when that check was written.

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
backup next to a `git clean`. The server creates the directory itself when it
is allowed to, so a path under your home directory needs nothing done to it.
Somewhere like `/var/lib` it is not allowed to, and then it prints this and
tells you to run it:

```sh
sudo mkdir -p /var/lib/uberscan && sudo chown $USER /var/lib/uberscan
```

**It keeps serving either way**, so a running server is not by itself evidence
that the journal has anywhere to go. That is deliberate — the pages and the
verdict are worth more than the write — but it means the line is worth reading
for. It is the last thing printed at startup, after the addresses.
`config-backup.json` lands beside the journal.

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

**The rig does the reaching, both ways.** A car is behind cellular NAT and
cannot be reached from outside, so the direction is not a preference. It also
means the sync works the same on the driveway and on the motorway rather than
only when parked — *if* you give it an address that works from the road. A
Tailscale or WireGuard name does; a `192.168.x.x` one only syncs when the car
is at home, which is the one time the data was never really at risk.

The same run also asks the copy for what *you* did there — a tick or a hide
made on its offers page, an offer typed on its keypad — and hands those to the
rig's own server, so both journals end up saying the same thing about the same
offer whichever machine you said it on. That needs the rig's server address,
which is `http://127.0.0.1:8080` unless you moved it: pass `--local` or set
`SYNC_LOCAL` to match `PORT`. If the rig's server is not answering, the run
says so on stderr and still exits 0 — the offers still went. `--no-pull` is the
old, one-way behaviour.

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
lending one card's distance to another. A leg is matched to one already seen
when *either* its duration or its distance agrees, so re-reading the same leg
does not add it twice and a misread field lands in the slot it belongs to; only
a genuinely different leg extends the total.

Where two readings of one leg disagree, the more frequent wins, and a tie takes
the **larger** value. Two arguments, and they agree: OCR drops a digit far more
often than it adds one, so of two equally popular readings the larger is the one
that was not corrupted; and more minutes is a lower `$/hr` while more miles is
more running cost, so the larger reading is the one that understates the offer.
(This used to take the *smaller* value, on the stated grounds that a shorter
time makes an offer look worse. It does the opposite — `$/hr` is pay over time —
and one frame reading `23 min` as `3 min` tied one-all and won, reporting a
$20.51/hr pass as $93.38/hr, the strongest accept of the shift.)

Everything that moves money is decided this way and not by whichever frame
arrived last: the minutes, each leg's distance, a distance no leg claimed, the
item count and the deadline. The two flags that decide what may be *done* to the
distance — whether a duration stood beside it, and whether the card printed a
decimal point — are rebuilt from the merge too, and the decimal point travels
with the reading that won the vote rather than across the window.

Addresses are the exception: they are kept rather than voted on, because an
address is not arithmetic and the failure that matters is not seeing one at all.

This needs more than one look, and the motion gate only fires once per card
because a card sitting still is not a change. After anything with a payout is
read, the scanner therefore keeps sampling for a few seconds. Reads report
`legs` and `mergedFrom` so a merged answer is visible as one.

## Correctness

All of it, in one command:

```sh
npm test                # all 37 suites, 6200-odd checks
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
node tests/corpus.test.js       # 793 checks, the shared corpus
node tests/parser.test.js       #  98 on the browser side alone
node tests/advice.test.js       # 339 on what line to tell a driver to draw
node tests/crop.test.js         #  16 on the trip from a drag to a crop box
node tests/measure.test.js      #  64 on the measurement that decides how this
                                #     rig should learn geography — held hardest
                                #     to the rule that a table may not be
                                #     scored on rows it was built from
python3 rpi/test_parser.py      # 837 — the same corpus, plus the Pi's own
python3 rpi/test_accumulate.py  # 303 on merging readings across frames, on a
                                #     recovered leg staying recovered, and on
                                #     one address read twice staying one place
python3 rpi/test_pipeline.py    # 227 on where to look, how big, what to log,
                                #     and the two pictures the live view sends
python3 rpi/test_exposure.py    # 182 on flicker, brightness, gain and
                                #     exposure, on both ends of running out,
                                #     and on an empty mount in the sun never
                                #     being reported as a phone
python3 rpi/test_track.py       # 144 on following the phone as it drifts, and
                                #     on the centre recovery that never fired
python3 rpi/test_gps.py         #  89 on the position stamped beside a card:
                                #     that a fix too old to mean anything is
                                #     refused rather than rounded, and that a
                                #     row written before the rig had a GPS
                                #     still reads
python3 rpi/test_journal.py     # 270 on keeping one row per offer, on a
                                #     distrusted distance always saying so twice,
                                #     and on the row agreeing with the screen
                                #     about why a verdict was withheld
python3 rpi/test_repeats.py     #  54 on one card read many times
python3 rpi/test_calibrate.py   #  75 on what calibration may overwrite,
                                #     which frame it is allowed to write from,
                                #     and the focus that frame was taken at
python3 rpi/test_cropbox.py     #  32 on a box drawn by hand
python3 rpi/test_money.py       # 255 from a picture of a card to a $/hour,
                                #     and on a rate with no running cost off
                                #     it never earning an ACCEPT
python3 rpi/test_scan_pi.py     # 336 on the loop that holds the camera, on
                                #     which live view it is being asked for,
                                #     and on one card being named once however
                                #     many times it is read
python3 rpi/test_sync.py        # 180 on getting the offers off the car, and
                                #     on a far end that cannot read its own copy
python3 rpi/test_scanjs.py      # 201 on the phone's own scanner, through a
                                #     real browser (skipped without Playwright)
python3 rpi/test_liveview.py    # 111 on the picture the driver watches, on
                                #     nothing else being served with it, on the
                                #     dashboard layout being wired up, on which
                                #     of the two views was asked for, on the
                                #     offer a reopened tab can still mark, and
                                #     on one shift's figures being counted the
                                #     way the offers page counts them
python3 rpi/test_watchdog.py    #  22 on a scanner that runs without working
python3 rpi/test_autopilot.py   #  45 on the one command that takes the rig
                                #     from nothing to scanning, and on the
                                #     branch that used to brick it
python3 rpi/test_keypad.py      #  94 on the fallback input path, driven
                                #     through a real browser one key at a time
python3 rpi/test_lint.py        # 228 on the faults that only surface when a
                                #     cold branch runs, and on nothing the rig
                                #     writes being committable (flake8 optional)
python3 rpi/test_handoff.py     #  50 on the three files the browser and the
                                #     camera pass requests through, and on both
                                #     sides finding them in the same place
python3 rpi/test_service.py     #  45 on the systemd units BOTH installers
                                #     write, asking systemd itself whether an
                                #     environment assignment survived
python3 rpi/test_camera.py      #  42 on which tuning file opens the camera, and
                                #     on who is already holding it
python3 rpi/test_doctor.py      # 100 on the preflight running to the end, on
                                #     slower not being reported as broken, and
                                #     on a journal with a hole in it being
                                #     reported at one line and failed at more
python3 rpi/test_tesseract.py   # 125 on the kept OCR engine reading exactly as
                                #     the spawned binary did, and on every way
                                #     it can fail ending with the rig reading
python3 rpi/test_dashboard.py   # 568 on what the driving screen shows while a
                                #     card is being read, after, once the card
                                #     has gone and only the driver knows they
                                #     took it, and on the shift figures saying
                                #     words rather than a number whenever one
                                #     would be wrong (skipped without
                                #     Playwright)
python3 rpi/test_layout.py      # 795 on every page fitting the screen it is
                                #     bolted to and being readable from the
                                #     driving seat (skipped without Playwright)
python3 rpi/test_offerspage.py  # 364 on the offers page as a driver reads it:
                                #     the search, the undo, the runs and the
                                #     empty states (skipped without Playwright)
python3 rpi/test_stacking.py    # 166 on judging a second job against the one
                                #     already in the car
python3 rpi/test_server.py      # 157 on the server's own edges: two readers of
                                #     the journal at once, a mark for an offer
                                #     it has forgotten, a scanner re-reading
                                #     the same card, a journal directory that
                                #     is not one — and on the CSV export, which
                                #     is the one thing here that leaves the
                                #     machine and had no check at all
python3 rpi/test_map.py         # 191 on the map check page: that it asks
                                #     nobody anything until told to, that it
                                #     keeps to one geocoder request a second,
                                #     that it shows what it could not place —
                                #     including the pins that landed in
                                #     another state — and that the positions
                                #     the rig's own GPS recorded are drawn
                                #     only when asked for
node tests/mapview.test.js      # 195 on the deciding behind both maps, with
                                #     no map: the geometry, the cache, and the
                                #     one-request-a-second rule against a fake
                                #     clock, which is what makes the awkward
                                #     cases — two walks in a row, a cache hit
                                #     mid-walk, a hotspot that drops — cost
                                #     milliseconds instead of seconds
python3 rpi/test_loop.py        #  52 on the scan loop re-telling a card once
                                #     the rest of it arrives, going quiet when
                                #     a read never returns, and saying so when
                                #     a button press is refused
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
screen not visible — is the phone lit and in frame?
health over 120s: 7 reads, 5 complete; median 259ms; 2 found no payout; screen
       brightness 190/205; banding 0.4; gain 2.10; crop [0.00 0.40 1.00 0.60];
       corners held, 7px from calibration (3px since last save)
```

The `Reader saw:` line is the one that settles arguments. In the example above
the crop is sitting below the payout — the text starts at the journey line — and
that is visible at a glance without needing the rig. Two rounds of fixes here
were diagnosed from exactly this kind of evidence: `S 4S Rhodes` out of a street
address became a $45 offer, and `ZIM` out of map texture became a 21-minute leg.

`health` lines appear at most every two minutes and only when reads have
happened, so a quiet scanner stays quiet. The same detail is on `live.html`
under **what the reader read**, which is quicker if you are standing at the car.

`corners` says three things, not two: `held` is the tracker following the
phone, `stuck` is a candidate found on every check that is not the phone, and
`lost` is no candidate at all. Both distances are given because they answer
different questions — how far the phone has wandered from where it was
calibrated, and how far since the corners were last saved, which moves.
There is no `crop moved` line any more: the mechanism that walked the crop
about looking for the card is gone, and the crop is what calibration set.

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
