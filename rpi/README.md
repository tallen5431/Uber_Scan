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
| **Hand over a file, not an array** | pytesseract's array path routes the image through PIL, whose PNG encoder measured **93ms** — over a third of a read, spent compressing a picture tesseract immediately decompresses. An uncompressed PGM encodes in 0.1ms and reads identically: **262ms → 157ms**. It goes in `/dev/shm`, so the SD card is never in the hot path. |
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
a 12s ceiling — and snaps straight back to 2.5s the instant a reading differs or
the screen empties. The case the timer exists for costs exactly what it did
before, one beat; the case it was wasting on settles at **12% duty instead of
56%**. The ceiling is reached after four identical reads running (2.5 → 4.0 →
6.4 → 10.2 → 12.0), and it is also the worst case for how long a replacement
offer can sit unnoticed.

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
measures the real thing anyway: it tries each flicker-safe candidate against the
actual phone and keeps the quietest that still lights the card, recording what
every candidate scored.

Brightness is then handled by **gain, never exposure** — a phone dims itself, and
a screen set up in daylight is a much darker subject at 2am. Full auto-exposure
is not the answer: it hunts on a strobing emissive panel and would undo the
flicker arithmetic the moment it decided the picture was dim. So the exposure
stays where it was measured and gain tracks the screen in small steps every few
seconds, which cannot reintroduce banding. `--gain` pins it; `--no-auto-gain`
stops it moving.

Both show up in the health line — `card brightness 190/205; banding 0.4; gain
2.1` — so "it looks dark" and "it looks wavy" can be confirmed with a number
rather than argued about. Which is how the next one was caught.

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

### Reading the live view

| | |
|---|---|
| **Green outline** | where the corners are *now* — calibration as the tracker has since moved it, not as it was written down. If it is not hugging the phone's screen, see below, or draw it yourself with ▣ Set box. |
| **White inset** | the exact image handed to the reader: de-skewed, cropped to the card, contrast boosted. Literally the reader's own last picture rather than a re-creation of it, so it can lag the outline by a read. If the pay, minutes and miles are legible there, the reader has everything it needs. |

The view refreshes about **seven times a second** while the page is open. That
got cheaper before it got faster: a snapshot used to copy a 12MB frame, draw the
outline on it at full size, shrink it with an area filter and then warp a second
copy of a card the reader had already made. It now shrinks once with a linear
filter, draws on the small picture and reuses the reader's card — about a
quarter of the work, so nearly three times the frame rate still costs less than
the old rate did.

It does not live on the SD card. The view refreshes about fourteen times a
second while someone is watching, at ~50kB a frame — roughly **2.5GB an hour
written to the card**, against about 19MB a *year* for the journal. Every byte
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

**A viewer on the far end of the car's wifi cannot carry 25 frames a second of
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

Three keys in `config.json` are about where to look, and they mean different
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
* **no OCR text.** The useful part is already parsed into numbers; what is left
  is pickup addresses. `rpi/journal.jsonl` is gitignored and the server refuses
  to serve anything under `rpi/`.
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

### Getting them off the car

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
bash tools/install-sync.sh http://nuc.lan:8081
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
npm test                # all 17 suites, 1833 checks
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
node tests/corpus.test.js       # 310 checks, the shared corpus
node tests/parser.test.js       #  83 on the browser side alone
node tests/advice.test.js       #  77 on what line to tell a driver to draw
node tests/crop.test.js         #  16 on the trip from a drag to a crop box
python3 rpi/test_parser.py      # 343 — the same corpus, plus the Pi's own
python3 rpi/test_accumulate.py  #  78 on merging readings across frames
python3 rpi/test_pipeline.py    # 192 on where to look, how big, and what to log
python3 rpi/test_exposure.py    #  84 on flicker, brightness, gain and exposure
python3 rpi/test_track.py       # 122 on following the phone as it drifts
python3 rpi/test_journal.py     #  69 on keeping one row per offer
python3 rpi/test_repeats.py     #  48 on one card read many times
python3 rpi/test_calibrate.py   #  30 on what calibration may overwrite
python3 rpi/test_cropbox.py     #  32 on a box drawn by hand
python3 rpi/test_money.py       # 144 from a picture of a card to a $/hour
python3 rpi/test_scan_pi.py     # 120 on the loop that holds the camera
python3 rpi/test_sync.py        #  67 on getting the offers off the car
python3 rpi/test_liveview.py    #  18 on the picture the driver watches
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
