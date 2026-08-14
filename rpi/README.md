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

Two things run continuously to stop that:

| | |
|---|---|
| **Corner tracking** (`track.py`) | The screen is re-found every 0.4s on the preview stream the motion gate already holds, which costs about a millisecond. A candidate must be the right size, in roughly the right place, and say the same thing five checks running before the corners are eased 35% of the way toward it — so drift is followed within about two seconds and a hand crossing the frame is not followed at all. A candidate that keeps insisting from somewhere else for twice as long, *and is the same size of thing*, is treated as the mount having been knocked and adopted whole. |
| **Crop recovery** (`fit_roi`) | If reads stop finding a payout — or find one hard against the top edge of the crop, which means the crop is cutting the card — the whole screen is read once and the crop is re-fitted to where the payout actually is. The new box is written back to `config.json`, so the next run starts from what this one learned. |

Both are reported in the live view, and `--no-track` turns the first off.

The recovery pass is what makes a bad crop self-correcting rather than silent.
It costs one slow read (~0.6s here, more on a Pi) at the moment it fires, and
normal fast reads resume immediately afterwards.

### Self-correction has to be harder than it sounds

The first version of that recovery was far worse than the problem. A scanner
logged **70 re-fits in twenty minutes**, each one moving the crop somewhere new
— `y` wandering between 0.02 and 0.38, height between 0.44 and 0.98 — and spent
the time between them reading whichever slice of screen the last mistake had
chosen. It looked exactly like the scanner being slow.

Three things caused it, and all three are worth stating because they are the
general shape of this hazard:

1. **A payout is not an offer.** The driving screen shows the day's earnings.
   Money with no journey under it is furniture, and fitting the crop to it is
   how a working scanner talks itself onto the wrong half of the screen. A
   re-fit now requires a *complete* read — a payout with a leg.
2. **Noise makes journeys too.** The minute unit used to accept a bare "m", so
   `ZIM` out of the road texture parsed as a 21-minute leg — which made the
   earnings screen above look complete. The unit must now be spelled out, and
   the number must contain a real digit.
3. **A thin crop asks for a huge picture.** Read height is derived from the
   crop's share of the screen, so a crop that re-fitted itself to 0.18 asked for
   a 5000px warp: a 40MB image and an OCR pass to match. That is capped now.

What remains is deliberately conditional rather than slow: several reads must
fail in a row with nothing succeeding between them, and two whole-screen
searches must agree on where the card really is. Those conditions are what makes
it safe, so the *intervals* can be short — every second spent deciding is a
second spent reading the wrong part of the screen. A crop that is genuinely
misplaced repairs itself in about **three reads, six seconds of Pi time**;
replayed against offers interleaved with driving screens it moves **zero**
times.

### The crop is loose on purpose

A tight crop looks efficient and is not. The card's top edge moves with the
phone, with the service badge above the payout, and with the card type, and a
crop that clips the payout does not degrade — it reports no offer at all, or
reads the rating underneath as one. Measured against cards drawn anywhere from
0.34 to 0.58 down the screen:

| Crop | Exact reads | Lost the payout entirely |
|---|---|---|
| `[0.02, 0.48, 0.96, 0.50]` (old) | 28/42 | **13** |
| **`[0.0, 0.40, 1.0, 0.60]`** | **42/42** | **0** |
| `[0.0, 0.30, 1.0, 0.70]` | 42/42 | 0, but slower and no better |

Where nothing was being clipped, the loose crop scored exactly the same as the
tight one (57/72) for about 7ms. Going wider than this starts costing accuracy
to the map text it drags in, so it sits at the far edge of free.

One trap is worth naming, because it is invisible and it points the wrong way.
Text size in the finished image depends on the *warp height*, and the warp
height used to be derived from the crop's share of the screen — so widening the
crop to stop it clipping the payout would have **shrunk the text**, keeping more
of the card and reading less of it. The warp is now derived from how much of a
screen a card is (`CARD_SHARE`), which is a property of the card rather than of
however much slack the crop is carrying. For the same reason `card_source_pixels`
reports the height of the *card*, not of the crop: it is what the aiming floor is
judged against, and measuring the crop instead would have quietly passed mounts
that are too far away.

## Where the speed comes from

Not from tuning the OCR engine. From refusing to run it:

| | |
|---|---|
| **Motion gate** | A 640×480 luma stream answers "did anything change?" for ~1ms. The full read only happens when the answer is yes, so idle cost is near zero. |
| **Settle wait** | After a change, it waits for the picture to stop moving. Reading a frame mid-transition just wastes a read on motion blur. |
| **Warp to the screen** | Tesseract's cost scales with pixels. Feeding it a card instead of a 16MP frame is worth more than every other optimisation combined. |
| **Crop to the card** | Uber puts the card in roughly the same place every time. Cropping to it saves a good share of the pixels, for no loss of accuracy — but the crop is deliberately loose, see below. |
| **Hand over a file, not an array** | pytesseract's array path routes the image through PIL, whose PNG encoder measured **93ms** — over a third of a read, spent compressing a picture tesseract immediately decompresses. An uncompressed PGM encodes in 0.1ms and reads identically: **262ms → 157ms**. It goes in `/dev/shm`, so the SD card is never in the hot path. |
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
| **Green outline** | the four corners locked in at calibration. Every frame is perspective-warped from inside it, which is what makes the text square rather than skewed. If it is not hugging the phone's screen, the calibration is stale — recalibrate. |
| **White inset** | the exact image handed to the reader: de-skewed, cropped to the card, contrast boosted. If the pay, minutes and miles are legible there, the reader has everything it needs. |

**If the green outline covers the whole view, it has not found your phone.** The
screen is located by splitting the frame into light and dark, which needs some
darker surround to split against — fill the frame edge to edge and the brightest
region *is* the picture. That used to calibrate happily on a frame-shaped
"screen", which makes the card region an arbitrary strip of the room and
explains a scan area that looks far too narrow. It is now rejected, and the
overlay says `frame is all screen — back off so a dark border surrounds the
phone`.

Fill most of the frame with the phone, but leave a margin of something darker
around it.

The view refreshes about twice a second while the page is open and drops to
every three seconds when nothing is watching, because a live picture is only
worth CPU while someone is looking at it. That rate is the *preview*; verdicts
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
python3 rpi/test_accumulate.py  # 27 checks on merging across frames
python3 rpi/test_pipeline.py    # 69 checks on where, how big, and what to log
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
setup: corners [[951, 300], [1456, 301], [1455, 1399], [950, 1398]]
read 1 found nothing usable (no payout in the crop, 1 in a row).
       Reader saw: '34 min (3.6 mi) total\nDollar General (925 Shiloh Rd Nw)\n...'
crop moved: [0.00 0.66 1.00 0.34] -> [0.00 0.47 1.00 0.33] (reads were failing; the card
       was found there by two whole-screen searches that agreed)
screen not visible — is the phone lit and in frame?
health over 120s: 7 reads, 5 complete; median 259ms; 2 found no payout; crop
       [0.00 0.47 1.00 0.33]; crop moved 1x since start; corners held, drift 7px from saved
```

The `Reader saw:` line is the one that settles arguments. In the example above
the crop is sitting below the payout — the text starts at the journey line — and
that is visible at a glance without needing the rig. Two rounds of fixes here
were diagnosed from exactly this kind of evidence: `S 4S Rhodes` out of a street
address became a $45 offer, and `ZIM` out of map texture became a 21-minute leg.

`health` lines appear at most every two minutes and only when reads have
happened, so a quiet scanner stays quiet. The same detail is on `live.html`
under **what the reader read**, which is quicker if you are standing at the car.

## Known limits

- The picamera2 layer — capture configuration, pinned exposure and focus — is
  **written but not tested on hardware**, because this was built without a Pi
  or a camera attached. It now pins the sensor mode, reads the motion gate's
  luma straight out of the YUV buffer, and only sets focus controls the camera
  actually reports, but none of that has met the real module yet. Everything below it (warp, crop, preprocess, OCR,
  parse, motion gate, tracking, crop recovery, calibration, bench) is tested and
  passing.
- Timings are from x86, not a Pi 4. Run `bench.py`.
- Tested against a rendered replica with synthetic lens degradation, not a real
  lens pointed at a real phone in a moving car. The corner tracker in particular
  is tested against synthesised frames of a bright rectangle on a dark ground,
  which is what the detector keys on but is kinder than a windscreen at night.
- Crop recovery needs the payout to be legible *somewhere* on the screen. If the
  card is out of frame entirely, or the phone is too far away to resolve the
  digits at all, it will keep looking and reporting nothing — correctly, but it
  cannot fix a mount that was never good enough.
- Only Uber's current card wording is handled. A layout change breaks parsing,
  which is why the typed keypad on `index.html` stays the reliable path.
