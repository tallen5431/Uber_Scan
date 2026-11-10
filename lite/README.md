# Uber Scan lite

A camera reads the offer on your phone, and a screen beside it shows one big
card: **ACCEPT**, **CLOSE CALL** or **PASS**, the dollars per hour in large
type, and under it the pay, the minutes, the miles and the dollars per mile —
judged against *your* target and *your* cost per mile. Nothing to touch. It
starts with the car.

It is the same program as the full rig, with the experimental half switched
off — not a copy of it. Every fix to how a card is read, and every rule that
stops a misread payout from becoming a green ACCEPT, reaches lite the day it
is made. (Why it is built that way is in [../CLAUDE.md](../CLAUDE.md) and in
AUDITS.md under Settled.)

## What it does

- Watches the phone with its own camera, aims and calibrates itself the first
  time (the card's bottom line says "aim the camera at the phone", then
  "calibrating"), and reads every Uber and DoorDash offer that appears.
- Draws one card, readable from the driver's seat: the verdict word and its
  colour, $/hr large, then pay, minutes, miles and $/mi, and a line saying
  what the target was and whether running costs came off it.
- Says when it is unsure rather than guessing: **CHECK THE PAY**, **CHECK THE
  TIME**, **NOT AN OFFER**, a **?** after a verdict that is not settled yet,
  **pay ?** when the payout came from a card the rig had to go looking for, and
  no verdict at all for a payout cut by the edge of the box.
- Says the verdict aloud, if a speaker is fitted (optional).
- Keeps a small log of the offers it read, on the Pi (`rpi/journal.jsonl`).
- A quiet status line at the bottom: **camera ok**, **no card**,
  **calibrating**, **LOW POWER — check the power lead**, **not connected**.

## What it does not do

Lite switches off everything that needs the NucBox (a home server some full
rigs talk to), a touch screen, or a lot of the Pi's time:

| Off in lite | Kept in lite |
|---|---|
| NucBox search, routes and streets — and with them pins, maps, map labels, the fastest order, store searches | The camera, its aim, calibration |
| Map view and the map pins it posts | ▣ Set box and the settings, from a phone on the same Wi-Fi |
| DoorDash's map-label reads and the map bands (scanner threads) | The reader and every money-safety rule |
| The places report and the shift report | The verdict: $/hr, $/mi, pay, minutes, miles, against your target and cost per mile |
| Earnings screenshots | Spoken verdict (optional) |
| Journal sync to a machine at home | The offers log, on the Pi |

The page at `/api/lite` on the rig lists the same, from the running program.

## What you need

Three tiers. Only the first has been run as a rig; the others are what we
expect to work and what to watch for. If you try one, `tools/pi_bench.py`
tells you how it compares (see **Judging a board** below).

### 1. Recommended — the tested class

| Part | Notes |
|---|---|
| Raspberry Pi 4, 4 GB (or Pi 5, 4 GB) | The full rig runs on a Pi 4. A Pi 5 is faster; its camera cable is the narrow 22-pin one (buy the matching cable). |
| Raspberry Pi Camera Module 3 (12 MP, autofocus) | The owner's rig uses an Arducam 16 MP autofocus module (IMX519), which needs a driver; Camera Module 3 is the same class, works with Raspberry Pi OS out of the box and is the one to buy. Not yet run on a lite build. |
| 5–7" HDMI display, 800x480 or 1024x600 | No touch needed. A 3.5" 480x320 also fits the card. |
| Quality 12 V → USB-C 5 V 3 A car adapter, and a short, thick cable | The most common fault in a car. A weak supply shows as **LOW POWER** on the card, slows the Pi and can corrupt its card. Pi 5: a 5 V 5 A supply. |
| Case with a heatsink and fan | A parked car in summer is an oven. |
| 32 GB high-endurance microSD | "High endurance" (made for dashcams) survives power cuts and constant writing far better. |
| A mount holding the phone and the camera together | The camera must not move relative to the phone. One bracket, not two mounts. About 25 cm from the screen, square-on. |
| Speaker (optional) | For spoken verdicts. USB or a small amplified speaker on the 3.5 mm jack (Pi 4). |

### 2. Budget — untested

Cheaper, and not yet tried. Expect to tune.

- **Raspberry Pi Zero 2 W** (512 MB, four Cortex-A53 cores). Expect reads
  about 3–4× slower than a Pi 4. RAM is tight for node, python and tesseract
  together, and a full browser on top is too much: run it with `KIOSK=none`
  and use a phone or tablet as the display (below), or no display and spoken
  verdicts. Its camera connector is the narrow 22-pin one — buy the Zero
  camera cable. The reader lets up to four tesseracts run at once
  (`OCR_SLOTS` in rpi/pipeline.py; lite never uses the map label's share).
  Four engines may be more than 512 MB holds: on a Zero, try
  `UBERSCAN_OCR_SLOTS=2` in the service's environment and time it with
  `tools/pi_bench.py --busy`. Not yet measured, so not yet the default.
- **A used Raspberry Pi 3B+** (1 GB). Slower than a Pi 4, more room than a
  Zero.
- **A 5 MP OV5647 camera clone.** Fixed focus is fine on a fixed mount: set
  the focus once, by turning the lens, at the distance the phone sits.
- **A 3.5" 480x320 screen** (SPI or HDMI). The card is checked at that size.
- **No screen at all**, with spoken verdicts through a small speaker.
- **An old phone or tablet as the display**, on the same Wi-Fi as the Pi
  (the Pi's own hotspot, or the car's): it just opens
  `http://<the-pi>:8080/` in its browser. Nothing to install on it.

### 3. Judging a board

`python3 tools/pi_bench.py` times the reads this program makes, on screens it
draws itself — no camera, no phone, safe beside the running service. Compare
with a Pi 4:

| Read | Pi 4 |
|---|---|
| Uber card | 392 ms median |
| DoorDash rescue (the slow card) | about 1.0–1.2 s |

A board two or three times slower than that still reads every offer, a beat
later. Much slower, and a card can come and go before it is read.

### Memory

Measured on the development machine (64-bit, not a Pi), lite on:

| Process | Resident |
|---|---|
| The server (`server.js`), idle | about 62 MB (the same with lite off: it is the same program) |
| The scanner's code loaded (python, OpenCV, numpy), before the camera | about 50 MB |

Not yet measured on a Pi: the scanner with the camera running and tesseract
reading (each camera frame at the default mode is about 12 MB), and Chromium,
which on its own commonly takes 150 MB or more — which is why a Zero 2 W
should leave the browser to a phone.

## Setting it up

On a fresh **Raspberry Pi OS Bookworm** (Lite or with Desktop), with the
camera, the display and the network connected:

```sh
sudo apt install -y git
git clone -b lite <this repository's address> uberscan
cd uberscan
sudo bash lite/install.sh
```

That installs what it needs (the camera library, OpenCV, tesseract, node,
espeak-ng, the browser), sets the program to start with the Pi with lite on,
and opens the card full screen on the display at every boot:

- **With a desktop**, from the desktop's autostart, with autologin on and
  screen blanking off.
- **Without one (Lite)**, through `cage`, a one-window kiosk, on the screen
  the Pi boots to.

Options, given before `bash`:

```sh
sudo SPEAK=0 bash lite/install.sh        # no spoken verdicts
sudo KIOSK=none bash lite/install.sh     # no browser on the Pi: a phone or tablet shows the card
sudo APT=0 bash lite/install.sh          # skip the packages (re-running with no network)
```

Then:

1. Put the phone in the mount with its screen on, brightness up and
   auto-brightness off. The card says **AIM THE CAMERA** until the phone fills
   enough of the picture, then **CALIBRATED**, then **WAITING FOR AN OFFER**.
2. Set your target and cost per mile from a phone on the same Wi-Fi:
   `http://<the-pi>:8080/index.html` (the ⚙︎ settings). The default target is
   $25/hr.
3. If the card is not being found, draw the box yourself: open
   `http://<the-pi>:8080/live.html` on the phone and press **▣ Set box**.
4. Reboot once and watch it come back by itself.

The log, if something is wrong: `journalctl -u uberscan -f`.

Trying lite on a full rig for one boot, without installing anything: stop the
service and start the server with the switch on, `sudo systemctl stop
uberscan && LITE=1 npm start`, then open `http://<the-pi>:8080/` — the card.
`sudo systemctl start uberscan` puts the full rig back.

## Safety

- **Place the display where a glance does not take your eyes off the road** —
  near your line of sight, never where you have to look down or away. Do not
  block airbags, the windscreen's swept area or your view of the mirrors.
- Read the card only when it is safe to. The verdict is advice about money;
  driving comes first.
- Check local law on mounting screens and phones in a vehicle.
- The rig never touches the phone: you accept or decline on the phone
  yourself, as always.

## Updating

```sh
cd uberscan
git pull
sudo bash lite/install.sh
```

The `lite` branch only ever receives builds that passed the full test suite.
Re-running the installer is safe: it only installs what is missing and
rewrites its own files.

## Coming

- **Read-only filesystem and a watchdog** (milestone 2): so cutting the
  ignition never corrupts the SD card, and a hung Pi restarts itself.
- **First-boot setup page behind a QR code** (milestone 3): the card shows a
  QR code the first time; scan it with the phone to set the Wi-Fi, the target
  and the cost per mile, and to draw the box.
- **A ready-made SD image** through releases, so setting up is "write the
  card, plug it in".
- **Budget boards measured**: the Zero 2 W and an OV5647 camera, timed with
  `tools/pi_bench.py` and the memory measured with the camera running.
