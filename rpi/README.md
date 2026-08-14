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
| **Corner tracking** (`track.py`) | The screen is re-found every 0.4s on the preview stream the motion gate already holds, which costs about a millisecond. A candidate must be the same size as the screen already held and in roughly the right place; a small correction of something that passes both is followed on the first check, and a larger move has to say the same thing five checks running before the corners are eased 35% of the way toward it. A candidate that keeps insisting from somewhere else for twice as long, and is still the same size of thing, is treated as the mount having been knocked and adopted whole. `--no-track` turns it off. |
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
| **Never look at the page upside down** | When a page scores badly, tesseract runs the whole thing a second time inverted, in case it was white-on-black. `preprocess()` hands it dark text on a light card every time, so that pass can never help — and it is charged exactly where it hurts, on the reads that fail. A map costs **282ms with it and 211 without**, a dark screen **199 against 154**. Half a shift's reads are of something that is not an offer, so over a realistic mix the median read goes **586ms → 438ms** with no change in what it reads. `-c tessedit_do_invert=0`. |
| **Hand over a file, not an array** | pytesseract's array path routes the image through PIL, whose PNG encoder measured **93ms** — over a third of a read, spent compressing a picture tesseract immediately decompresses. An uncompressed PGM encodes in 0.1ms and reads identically: **262ms → 157ms**. It goes in `/dev/shm`, so the SD card is never in the hot path. |
| **Look in the middle first** | The screen is the biggest bright thing *that the middle of the frame is inside*, falling back to plain biggest. Size alone is a guess about the scene and it loses to a lit dashboard panel or a window at dusk; with a panel larger and brighter than the phone beside it, the old rule locked onto the panel and read nothing while this one reads the card. |
| **Track on the small stream** | Re-finding the corners uses the 640×480 luma the motion gate already has, not a shrunk-down sensor frame: **0.96ms against 6.98ms**, almost all of the difference being the shrinking. It also means tracking needs no full-resolution capture at all, so it keeps working at full rate while the scanner is otherwise idle. |
| **Stop when there is nothing left to learn** | Sampling continues after a card appears so a leg missed by one frame can be caught by the next — but it stops as soon as the reading is *whole* (a total, or both legs of a two-leg card) and two reads running agree. In a 30-frame run over one offer that is 2 reads instead of 9. What keeps sampling is the case that needs it: a single leg that is not a total, which is the shape of a card with a leg still missing. |

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

`card_share_of_quad` measures it instead of assuming, and `min_crop_height`
refuses a fit that could not hold the card it now knows the size of.

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
| **Green outline** | where the corners are *now* — calibration as the tracker has since moved it, not as it was written down. If it is not hugging the phone's screen, see below. |
| **White inset** | the exact image handed to the reader: de-skewed, cropped to the card, contrast boosted. Literally the reader's own last picture rather than a re-creation of it, so it can lag the outline by a read. If the pay, minutes and miles are legible there, the reader has everything it needs. |

The view refreshes about **seven times a second** while the page is open. That
got cheaper before it got faster: a snapshot used to copy a 12MB frame, draw the
outline on it at full size, shrink it with an area filter and then warp a second
copy of a card the reader had already made. It now shrinks once with a linear
filter, draws on the small picture and reuses the reader's card — about a
quarter of the work, so nearly three times the frame rate still costs less than
the old rate did.

**A green outline that is too small** used to be possible, and quietly. A
candidate has to be the same size as the screen already held before it can be
adopted — but that check was only on the dramatic path, the one that re-locks
onto a moved mount and takes the new corners whole. Ordinary drift only eases
35% of the way toward a candidate, which looked harmless enough not to need it.

Easing has no floor. A candidate a fifth too small sits comfortably inside the
distance test, so the outline could be walked down onto the white card, or onto
the lit half of a dimmed screen, a third at a time — every individual step
reasonable, the end state a box around part of a phone, and a crop measured
against it that is wrong in a way nothing downstream can detect. The size check
now guards both paths. Having it there is also what makes the outline *quicker*:
a small correction of something already the right size cannot be a hand or a
reflection, so it is followed on the first check rather than after five.

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

## Calibrate

Put a live offer — or any bright screen — on the phone, then:

```sh
python3 rpi/calibrate.py
```

It finds the screen automatically, writes `rpi/config.json`, saves
`rpi/config-preview.png`, and reports the card's height in sensor pixels. **Look at that preview.** It is the exact image
tesseract will be handed. It should be a straight-on, sharp, glare-free card.
If the detector locked onto something brighter than the phone, pass corners
by hand:

```sh
python3 rpi/calibrate.py --corners 135,229,830,134,838,1979,70,1874
```

Targets live in the same file — edit `settings` for your `target`, `costPerMile`,
`pad` and `secondsPerItem`.

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

The Pi parser is a port of the browser one. Both run the same corpus:

```sh
node tests/corpus.test.js       # 127 checks
python3 rpi/test_parser.py      # the same 127 checks
python3 rpi/test_accumulate.py  # 38 checks on merging across frames
python3 rpi/test_pipeline.py    # 84 checks on where, how big, and what to log
python3 rpi/test_exposure.py    # 38 checks on flicker, brightness and gain
python3 rpi/test_track.py       # 43 checks on following the phone
```

If the two parsers ever disagree, that suite fails. Edit one, re-run both.

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
