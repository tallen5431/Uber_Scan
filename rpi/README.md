# Raspberry Pi scanner (IMX519)

A Pi 4 with a camera on a fixed mount, watching the driving phone. This is the
version worth building: a fixed mount is what makes the reading reliable, and it
removes the alignment problem that makes the handheld phone-camera version
fiddly.

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

## Install

```sh
sudo apt install -y python3-picamera2 python3-opencv tesseract-ocr espeak-ng
pip3 install pytesseract --break-system-packages
```

`espeak-ng` is only needed for `--speak`.

## Calibrate

Put a live offer — or any bright screen — on the phone, then:

```sh
python3 rpi/calibrate.py
```

It finds the screen automatically, writes `rpi/config.json`, and saves
`rpi/config-preview.png`. **Look at that preview.** It is the exact image
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
big colour panel if you have a screen attached. `--save-misses DIR` keeps frames
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

## Known limits

- The picamera2 layer — capture configuration, pinned exposure and focus — is
  **written but not tested on hardware**, because this was built without a Pi
  or a camera attached. Everything below it (warp, crop, preprocess, OCR,
  parse, motion gate, calibration, bench) is tested and passing.
- Timings are from x86, not a Pi 4. Run `bench.py`.
- Tested against a rendered replica with synthetic lens degradation, not a real
  lens pointed at a real phone in a moving car.
- Only Uber's current card wording is handled. A layout change breaks parsing,
  which is why the typed keypad on `index.html` stays the reliable path.
