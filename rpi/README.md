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

python3 rpi/doctor.py        # checks every dependency, prints the fix for each
python3 rpi/preview.py       # open http://<pi>:8081/ and aim until it reads green
python3 rpi/calibrate.py     # locks in the screen corners
python3 rpi/scan_pi.py --speak
```

That last command is the whole product: it watches, and when an offer appears it
says *"pass, twelve an hour"* out loud. Speech is the right output in a car — it
needs no glance at all. `--display` draws a big colour panel instead if you have
a screen on the Pi, and reads are always printed to the terminal.

### Or run it from the web server

If you already manage this project with a process supervisor that runs
`npm start`, the scanner can live there instead of in its own service. Once
`rpi/config.json` exists — that is, once you have calibrated — `npm start`
launches the scanner alongside the site automatically. There is nothing to
configure, because a supervisor gives you no shell to configure it in.

| | |
|---|---|
| `/live.html` | the verdict, full screen, updating live |
| `/api/status` | scanner state and the last read, as JSON |
| `/api/events` | server-sent events, one per read |

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

- the four corners of the phone screen are found **once**, at calibration;
- every frame is perspective-warped straight-on before OCR, so the text is
  square and evenly scaled instead of skewed;
- focus and exposure are pinned, so nothing hunts.

On the same test frame that defeated the handheld pipeline, the warped version
reads `3.6` unaided — the plausibility guard never has to fire. The guard is
still there as a backstop.

## Where the speed comes from

Not from tuning the OCR engine. From refusing to run it:

| | |
|---|---|
| **Motion gate** | A 640×480 luma stream answers "did anything change?" for ~1ms. The full read only happens when the answer is yes, so idle cost is near zero. |
| **Settle wait** | After a change, it waits for the picture to stop moving. Reading a frame mid-transition just wastes a read on motion blur. |
| **Warp to the screen** | Tesseract's cost scales with pixels. Feeding it a 363×450 card instead of a 16MP frame is worth more than every other optimisation combined. |
| **Crop to the card** | Uber puts the card in the same place every time. Cropping to it roughly halves the pixels again, for no loss of accuracy. |

## Measured

On a desktop-class x86 container, median of repeated reads, using a
camera-simulated frame of a real offer card:

| Crop | Warp height | Pixels to OCR | OCR | Total | Result |
|---|---|---|---|---|---|
| whole screen | 1400 | 588×1400 | 311ms | 316ms | correct |
| whole screen | 900 | 378×900 | 270ms | 273ms | correct |
| card only | 1100 | 443×550 | 222ms | 226ms | correct |
| **card only** | **900** | **363×450** | **227ms** | **229ms** | **correct** |
| card only | 700 | 283×350 | 194ms | 195ms | correct |
| card only | 500 | 201×250 | 151ms | 152ms | **fails** |

Warp costs 1–3ms and parsing 0.1–0.4ms; effectively all the time is OCR.

**A Pi 4 is slower than this — expect roughly 2–4×**, so budget ~0.5–1s per
read and ~1–2s to a verdict two reads agree on. Against a 30–45 second offer
window that is ample. Measure it yourself with `bench.py` rather than trusting
these numbers; that is what it is for.

Card height 900 with the card crop is the recommended starting point: it is
near the floor for speed while keeping real margin before 500, where reading
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

**2328×1748 is the default and the right one.** 30fps is far more than this
needs, and 2×2 binning gives cleaner pixels in a dim car. Go to 4656×3496 only
if calibration says the card is too small — 9fps is still plenty, since offers
do not arrive sixty times a second.

**Framing.** Because 2328×1748 is binned, the card carries half the pixel
density the headline 16MP suggests. `calibrate.py` measures the card's height
in real sensor pixels and tells you whether it is enough — below about 350px it
stops reading, and no later upscaling recovers detail the mount never caught.
Aim to fill the frame with the phone; on the test frame a well-filled shot
measures ~870px against a 450px floor.

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

- `preview.py` runs **continuous autofocus** while you aim, and overlays both a
  sharpness score and the lens position it settles at;
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

## Tuning

```sh
python3 rpi/bench.py --image some-frame.png
```

Sweeps warp heights and crops on your hardware and prints where reading breaks.
Take the smallest height that still reads and leave margin.

If reads fail in the car but the preview looked fine, the usual causes are, in
order: glare across the card, exposure too short (raise `--exposure`; below
~10000µs OLED dimming shows as dark bands), and focus (`--lens`, in dioptres —
4.0 is 25cm, 3.0 is 33cm).

## Correctness

The Pi parser is a port of the browser one. Both run the same corpus:

```sh
node tests/corpus.test.js     # 81 checks
python3 rpi/test_parser.py    # the same 81 checks
```

If the two ever disagree, that suite fails. Edit one, re-run both.

## If something is wrong

`python3 rpi/doctor.py` checks each dependency, the camera, and the calibration,
and prints the exact command to fix whatever is missing. It also runs the parser
against a known offer, so a green line there means the reading logic is sound and
the problem is the mount or the camera.

## Known limits

- The picamera2 layer — capture configuration, pinned exposure and focus — is
  **written but not tested on hardware**, because this was built without a Pi
  or a camera attached. It now pins the sensor mode, reads the motion gate's
  luma straight out of the YUV buffer, and only sets focus controls the camera
  actually reports, but none of that has met the real module yet. Everything below it (warp, crop, preprocess, OCR,
  parse, motion gate, calibration, bench) is tested and passing.
- Timings are from x86, not a Pi 4. Run `bench.py`.
- Tested against a rendered replica with synthetic lens degradation, not a real
  lens pointed at a real phone in a moving car.
- Only Uber's current card wording is handled. A layout change breaks parsing,
  which is why the typed keypad on `index.html` stays the reliable path.
