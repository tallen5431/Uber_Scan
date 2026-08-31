#!/usr/bin/env python3
"""Live scanner for a Pi camera pointed at the driving phone.

    python3 rpi/scan_pi.py --speak

Two streams come off the sensor at once: a tiny one that answers "did anything
change?" for almost nothing, and a full one that is only ever touched when the
answer is yes. Idle cost is a few milliseconds per frame; the expensive read
happens once per offer, not sixty times a second.

Every camera control that could hunt — exposure, white balance, focus — is
pinned. A fixed mount means there is nothing to track, and an autofocus pass
mid-offer costs more time than the OCR does.
"""

import argparse
import json
import os
import re
import queue
import subprocess
import sys
import threading
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cropbox as CX
import exposure as EX
import handoff as HO
import offer_parser as OP
import pipeline as PL
import journal as JR
import track as TR
from accumulate import OfferAccumulator

DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')


DEFAULT_SNAPSHOT = HO.frame()

# The motion gate means whole minutes can pass with no read, so the snapshot is
# refreshed on a timer as well. Cheap: a warp and a resize, no OCR.
#
# Two rates, because a live view is only worth CPU while a person is looking at
# it. The server touches a file whenever the browser fetches a frame; within
# that window the view is worth refreshing quickly, and outside it a slow tick
# is enough to prove the camera is alive.
#
# The fast rate is what someone watching the page actually experiences, so it is
# set by what looks alive rather than by what is cheap. Raising it was paid for
# first: a snapshot used to copy a 12MB frame, draw on it at full size, shrink
# it with an area filter and then warp a second copy of a card the reader had
# already made. It now shrinks once, draws on the small picture and reuses the
# reader's card — about a quarter of the work.
#
# 25 a second, measured rather than guessed. Composing and encoding one 480px
# view costs about 2.2ms on a development machine against synthetic noise, which
# is the worst case a JPEG encoder ever sees — call it 10ms on a Pi 4 with a real
# frame. That is a quarter of one of four cores, paid only while somebody is
# actually looking, and the reads leave most of those cores idle.
#
# It was 14, which capped the live view below what the rig's own screen could
# show. That panel is what the driver watches to decide whether to press Accept,
# and fourteen frames a second looks like a slide show next to the phone beside
# it. Measured end to end through the real page: 13.7 distinct frames a second
# before, 28.4 after.
#
# A viewer on the far end of the car's wifi cannot carry 25 frames a second of
# 50kB each, and does not have to — the stream respects back-pressure, so a slow
# link simply receives fewer frames rather than falling further behind the longer
# it watches. The rig's own screen, which is a loopback socket, gets all of them.
#
# ...and none of that was what the rig actually did. The snapshot is due-checked
# once per camera frame and nowhere else, so the only rates it can produce are
# the camera's divided by whole numbers — 30, 15, 10, 7.5 on the binned sensor.
# The check was a strict "elapsed > period", which always lands on the next one
# *down*, because the frame arriving on the deadline is a hair early and gets
# skipped. Simulated against a 30fps sensor, this 25 delivered 15.1. The
# 13.7-vs-28.4 measurement above was of the fetch-a-still fallback, not of this.
#
# Taking the frame nearest the deadline rather than the first one past it puts
# this on 30 — which is the sensor's own rate, the honest ceiling, and what the
# paragraph above was aiming at. Written as the sensor's rate rather than as the
# 0.04 it used to be, since every ask between 23 and 30 now rounds to the same
# 30 and a number that cannot be delivered is a number that misleads whoever
# reads it next.
SNAPSHOT_FAST = 1 / 30.0
SNAPSHOT_IDLE = 3.0

# The live view is a *view*, not a read. It exists so the driver can see what
# the camera is pointed at, and it is looked at on a phone over the car's wifi —
# so what limits it is bytes on the link, not pixels on the Pi. Composing and
# encoding one costs a few milliseconds either way; a 640px frame at quality 80
# is about 136kB, which at ten a second is 1.4MB/s of wifi and is why the
# picture lagged.
#
# 480px at quality 60 is about 50kB, near a third of that, and it is still twice
# the resolution anything in this picture is judged at: the aim is read from a
# green outline and the focus from the inset, which is the reader's own image
# and is pasted in rather than resampled here. None of it touches what the
# scanner reads — that is warped from the full sensor frame at OCR_CARD_HEIGHT
# and never goes near this path.
SNAPSHOT_WIDTH = 480
SNAPSHOT_QUALITY = 60

# ...all of which is true of a view used to *aim* the camera, and none of it is
# true of one used to read the phone.
#
# The rig's screen is bolted where the driver can see it, and the phone is not:
# it sits in the mount pointing at the camera. Working it with a bluetooth mouse
# and reading it off this panel makes the live view the driver's only sight of
# the phone — so the offer card has to be legible in it, and so does whichever
# button the pointer is over.
#
# The scene view cannot be that picture at any size. Between reads it is made
# from the 640x480 luma preview and published 480px wide, and the phone occupies
# perhaps a third of the frame: call it 160 pixels across for a screen whose
# text is small at 1080. Enlarging the <img> enlarges those 160 pixels. The
# information is not in the file.
#
# So the phone view is a different picture rather than a bigger one: the same
# perspective warp the reader uses, from the sensor frame, filling the frame.
# 1000px tall against a phone occupying maybe 900 of the sensor's 1748 rows is
# roughly one-for-one — no invented detail, and about six times the linear
# resolution the scene view gives the same screen.
SCREEN_HEIGHT = 1000
# Higher than the scene's 60. Text at the size a phone draws it is exactly what
# JPEG's chroma subsampling and ringing damage first, and this picture exists to
# be read rather than glanced at.
SCREEN_QUALITY = 78

# The phone view costs what the scene view was written to avoid: it needs the
# sensor frame, which is the 12MB copy that branch exists to skip.
#
# Measured on a development machine against a synthetic rig frame: the warp is
# 1.8ms and the JPEG 3.2ms on worst-case noise, so composing one is about 5ms —
# genuinely cheaper than the scene view, whose expense was never the shrink but
# the card inset warped out of the sensor. The sensor copy on top is the real
# price, and it is the one thing here that is much dearer on a Pi than on this
# machine.
#
# It does not need 25 a second either way. The scene view is watched for motion
# — is the phone still in the box, has the mount slipped — and a slide show
# there reads as a fault. This one is watched to read a card that is not moving
# and, increasingly, to see where a mouse pointer is: the driver works the
# phone with a bluetooth mouse and this picture is where they watch the cursor.
# A cursor at ten frames a second feels attached to the hand; below that it
# does not.
#
# Fifteen, then, rather than the first cautious ten — the compose is ~5ms and
# the sensor copy is the rest, so this is a fraction of one core even on a Pi.
# It is also a flag, `--screen-fps`, because the right number is a property of
# the machine rather than of this code: raise it until the reads slow down, or
# drop it on a busy rig. Nothing else on this loop depends on it.
#
# Paid only while somebody has actually asked for this view, which is what
# .viewing carries.
SNAPSHOT_SCREEN = 1 / 15.0

# Below this the picture is a slide show and above it the Pi is composing
# frames nobody sees between camera frames — the sensor delivers 30 a second in
# the default mode, so asking for more than that buys duplicates.
SCREEN_FPS_LIMITS = (2.0, 30.0)

# What the browser asked to look at. Anything else is the scene, so a truncated
# write, an empty file or an older server that writes nothing all land on the
# view that has always been there.
VIEW_SCENE = 'scene'
VIEW_SCREEN = 'screen'

# The motion gate fires once per offer, because a card sitting still is not a
# change. One frame is therefore the only sample there would ever be, and one
# frame is where a leg gets lost to glare or a blink of defocus. After anything
# is read, keep reading for a few seconds so the accumulator has more than one
# view of the same card to work from.
RESAMPLE_WINDOW = 4.0
RESAMPLE_EVERY = 0.5

# ...and how often to look again once a card *has* been read whole.
#
# Not resampling — that is the burst above, which exists to collect a leg one
# frame missed. This is the slow beat that keeps the answer honest while a card
# is on screen, and it exists because the motion gate cannot see a new offer
# arrive.
#
# The gate compares one frame against the last as a mean absolute difference
# over a 160x120 thumbnail, which is the right question for "has the phone
# changed at all" and the wrong one for "is this a different offer". Measured on
# two cards of the same layout with different numbers, a whole new offer scores
# **0.33** against a threshold of 6.0 — and cropping the comparison to the card
# only takes it to 0.73, because a few digits are a tiny share of any area. A
# statistic that counts changed pixels instead does no better: a new offer moves
# 0.45% of them and an ordinary band of windscreen glare moves 0.42%, so
# separating the two would cost a false read on every passing reflection and
# still miss offers.
#
# So the gate is left alone and this is answered by looking. The cost is bounded
# and only paid while a card is up: one read every few seconds for the ten or
# twenty seconds an offer is on screen. What it buys is that the verdict on
# screen belongs to the card in front of the driver. Without it, an offer
# replaced in place by the next one left the previous card's ACCEPT sitting
# there, which is a confidently wrong number about a different job.
VERIFY_EVERY = 2.5

# ...and how far that beat backs off while the answer keeps coming back the
# same, up to a ceiling.
#
# A read costs about 1.4 seconds of a Pi 4, of which 91% is inside tesseract,
# and a card sits on the screen for tens of seconds. Re-reading it every 2.5s
# for all of that is the loop's largest single expense and it buys almost
# nothing: one real recording has the same card read four times in seventy
# seconds, every reading identical, four rows in the journal.
#
# The beat exists because a *replacement* offer does not move the motion gate,
# so the only way to notice one is to look. That is still true — this only
# changes how often, and only while nothing has changed. Every read that comes
# back different resets it to VERIFY_EVERY immediately, so the case it was
# written for costs exactly what it did before: one beat.
VERIFY_BACKOFF = 1.6

# What a read costs, near enough for the arithmetic that hangs off it.
#
# Not measured here — it cannot be, this file has no camera — but it is the
# number two constants below and one in live.html are derived from, and leaving
# it implicit is how they went out of step with a reader that got faster. The
# owner's own shift recorded a median `ms` of 1517 before the engine stopped
# being thrown away per read, and that change measured 2.12x end to end on a
# development machine: 1517 / 2.12 is about 715ms. Rounded up, because being
# wrong in this direction only costs a slightly lazier beat.
READ_SECONDS = 0.75

# ...and the ceiling, which is that cost divided by the duty cycle this is
# willing to spend on looking at a card that has not changed.
#
# It was 12.0, chosen when a read was ~1.4s: 1.4/12 is a 12% duty, against the
# 56% a flat 2.5s beat cost. The duty was the whole argument, and the read then
# halved, so the same argument now lands at 6.0 — 0.75/6.0 is the same 12% for
# half the wait.
#
# The wait is what this buys. A *replacement* offer does not move the motion
# gate, so the ceiling is exactly how long the driver can be looking at a
# verdict that belongs to the previous card. Twelve seconds of that was the
# price of a slow reader; it is not the price of this one.
VERIFY_MAX = 6.0


class Reader:
    """The OCR, moved off the loop that holds the camera.

    A read is about 1.4 seconds on a Pi 4, 91% of it inside tesseract, and for
    all of that the loop below used to be doing nothing whatever: no capture
    requests serviced, so no frames written for the live view — the picture the
    driver is looking at to decide whether to press Accept freezes for a second
    and a half, every time, and it freezes hardest exactly when there is an
    offer on screen to look at.

    It cost more than the picture. The tracker's 0.4s recheck could not run
    either, and that recheck is what corrects corners the read is about to use.
    The loop already knew: "a read costs several hundred milliseconds during
    which nothing else in this loop runs — including the tracker, whose recheck
    is what would fix the corners", and a rig on record reached its verdict
    after 5.7 seconds and eight reads, seven of them of a rectangle that was
    being replaced.

    So the read moves to a thread and the loop keeps its camera. What makes
    that safe is that the two halves were already separable: `look_many` is a
    pure function of the frames and a frozen Geometry, and `settle` — the
    agreement counter, the measured card share, which way up the ink is —
    stays on the loop's thread, in frame order, exactly as before. Nothing is
    shared but a queue.

    One read at a time. Two would be two tesseract instances fighting over a
    Pi's four cores, which is the same mistake as an unpinned OMP_THREAD_LIMIT
    and costs as much.
    """

    def __init__(self, scanner, threaded=True):
        self.scanner = scanner
        self.threaded = threaded
        self.busy = False
        self._work = queue.Queue(maxsize=1)
        self._done = queue.Queue()
        self._stop = threading.Event()
        self._thread = None
        if threaded:
            self._thread = threading.Thread(target=self._serve, name='reader',
                                            daemon=True)
            self._thread.start()

    def submit(self, frames, now, geom):
        """Hand over frames to read. Call only when not busy."""
        self.busy = True
        if not self.threaded:
            self._done.put(self._job(frames, now, geom))
            return
        self._work.put((frames, now, geom))

    def take(self):
        """The finished read, or None if there is not one yet.

        Returns a dict with `outs` (settled, in frame order), `frames`, and
        `error` — never raises, because a read is the one part of this loop
        that touches an external engine and a rig that dies on one bad frame
        costs a minute of not scanning.
        """
        try:
            done = self._done.get_nowait()
        except queue.Empty:
            return None
        self.busy = False
        if done['error'] is None:
            # On the loop's thread, deliberately. See Scanner.settle.
            done['outs'] = self.scanner.settle(done['outs'], done['geom'])
        return done

    def _job(self, frames, now, geom):
        try:
            return {'outs': self.scanner.look_many(frames, now, geom=geom),
                    'geom': geom, 'frames': frames, 'error': None}
        except BaseException as e:                 # noqa: BLE001 — see take()
            # ...except the two that are not a failed read at all.
            #
            # Under --no-thread this runs on the loop's own thread, and a
            # KeyboardInterrupt or the SystemExit that _stop_on_sigterm raises
            # for a SIGTERM lands right here — a read is over a second long, so
            # that is where a stop signal usually lands. Reporting it as a read
            # failure means the log says "read failed: SystemExit" once, the
            # rate limiter silences every one after it, and the loop carries on
            # holding the camera until the supervisor gives up and SIGKILLs it
            # — skipping cam.close() and the atexit that clears the scratch
            # file in /dev/shm, which is the exact leak that handler exists to
            # prevent. Ctrl-C behaves the same: it does nothing, silently.
            #
            # On the reader thread there is no such case. Signals are delivered
            # to the main thread only, and there is nothing above this to
            # unwind to: letting anything out would kill the reader, leaving
            # `busy` stuck True and the rig alive but never reading again.
            if not self.threaded and not isinstance(e, Exception):
                raise
            return {'outs': None, 'geom': geom, 'frames': frames, 'error': e}

    def _serve(self):
        while not self._stop.is_set():
            try:
                job = self._work.get(timeout=0.25)
            except queue.Empty:
                continue
            if job is None:
                return
            self._done.put(self._job(*job))

    def close(self):
        self._stop.set()
        if self._thread is None:
            return
        try:
            self._work.put_nowait(None)
        except queue.Full:
            pass
        # Bounded: the camera is being closed either way, and a reader still
        # inside tesseract must not be what stops the process exiting.
        self._thread.join(timeout=3.0)


def next_verify(every, was, now, card_on_screen):
    """How long to wait before looking again, and what that answer was.

    Returns (seconds, signature-to-compare-next-time). Lifted out of the loop
    because the property that matters is a sentence about a sequence — a
    changed reading is always looked at again at the fast beat, however long
    the beat had grown before it — and that cannot be checked against a loop
    that needs a camera to turn over.
    """
    if not card_on_screen:
        return VERIFY_EVERY, None
    if now == was:
        return min(VERIFY_MAX, every * VERIFY_BACKOFF), was
    return VERIFY_EVERY, now

# In RAM where there is any, and looked for in the checkout as well — see
# handoff.py for why these three files moved and why the rule is a rule rather
# than a list.
WATCH_PATH = HO.path(HO.VIEWING)
WATCH_PATHS = HO.candidates(HO.VIEWING)
WATCH_WINDOW = 10.0

# Touched by the web side when the driver asks for the outline to be re-found.
# A file rather than a signal or a socket, for the same reason .viewing is one:
# the scanner is sometimes a child of the web server and sometimes a systemd
# unit that has never heard of it, and a file works identically either way.
#
# It exists because the automatic recovery cannot always be sure. Corners that
# have drifted off to one side are unambiguous — the card is in the middle of
# the frame and they are not — but corners sitting concentric with the screen
# at the wrong size are not: that is equally "the phone was re-seated" and "the
# outline is on part of the screen", and no amount of looking tells them apart.
# The driver can see which it is in one glance at the live view, so the honest
# answer is to let them say.
RESET_PATH = HO.path(HO.RECALIBRATE)


# A Pi 4 has no real-time clock. With no network it boots somewhere in 1970 and
# jumps forward whenever it first reaches an NTP server, which in a car can be
# minutes into a shift or not at all.
#
# That did not matter until a delivery card's duration started coming from
# "Deliver by 7:15 PM" minus the current time. A clock an hour out turns a
# 45-minute job into a 105-minute one, or into a deadline that has already
# passed and wraps to twenty-three hours — and the verdict looks exactly as
# confident either way.
#
# So the clock has to earn the right to be used. Anything before this and it is
# obviously unset rather than merely wrong; a delivery card then goes unjudged,
# which is the correct outcome for an offer whose duration nothing here knows.
# Ride cards state their own minutes and are unaffected.
CLOCK_BELIEVABLE_AFTER = 1735689600.0        # 2025-01-01, well before this code


def clock_minutes(now=None):
    """Minutes since midnight, or None if the clock cannot be trusted."""
    now = time.time() if now is None else now
    if not now or now < CLOCK_BELIEVABLE_AFTER:
        return None
    local = time.localtime(now)
    return local.tm_hour * 60 + local.tm_min


def reset_requested():
    """True once per request, and never fatal if the file cannot be removed.

    Both places are checked and both are cleared: a web server one `git pull`
    behind this process writes to the other one, and a request left lying in
    either would be acted on whenever the scanner next restarted — throwing
    away a good calibration mid-shift for no reason the driver could see.
    """
    try:
        asked = any(os.path.exists(p) for p in HO.candidates(HO.RECALIBRATE))
    except OSError:
        return False
    if not asked:
        return False
    HO.clear(HO.RECALIBRATE)
    return True


def dropoff_requested():
    """True once per press of "read the dropoff". Same shape as reset_requested.

    Separate from the reading itself: this only says the driver asked. What it
    buys is a window — see DROPOFF_WINDOW — because the phone is showing a
    navigation screen that is not going to move, and the motion gate reads a
    still picture as nothing happening.
    """
    try:
        asked = any(os.path.exists(p) for p in HO.candidates(HO.DROPOFF))
    except OSError:
        return False
    if not asked:
        return False
    HO.clear(HO.DROPOFF)
    return True


# How long to keep reading after the button. The driver presses it, then has to
# get the destination onto the screen — a tap or two, or just waiting for the
# app to settle after the accept. One read at the instant of the press would
# photograph whatever was there before they did any of that.
#
# Twelve seconds is the same figure the offer window uses and for the same
# reason: long enough to cover a person doing one thing on a phone, short enough
# that the rig is not still hunting for an address when the next offer arrives.
DROPOFF_WINDOW = 12.0


def use_manual_box(scanner, quad_px):
    """Read exactly the box a person drew, and stop deriving one inside it.

    Three settings, and they only make sense together. The corners are the box.
    The crop is pinned to all of it, because a crop derived from the box would
    trim the top off the very thing the driver framed. And the card's share of
    the quad is 1.0 — the box *is* the card — which keeps the warp at the height
    the reader wants instead of twice it.
    """
    scanner.quad = np.array(quad_px, dtype=np.float32)
    scanner.roi = list(CX.PIN_WHOLE)
    scanner.fixed_card_share = 1.0
    scanner.card_share = 1.0


_watch_cache = (None, VIEW_SCENE)


def watching():
    """Whether anyone is looking, and at which view.

    One file, because the two questions have one answer: a view nobody asked
    for is not being watched, and a watcher who has not said which view wants
    the one that has always been there. The web side rewrites this whenever a
    browser fetches a frame, so the mode cannot drift away from who is
    actually looking — it expires with them.

    Called once per camera frame, so up to thirty times a second, and this file
    is on the card rather than in /dev/shm: the mtime is a stat the kernel
    answers out of its dentry cache, but reading it is an open, a read and a
    close each time. The web side rewrites it at most once a second, so the
    contents are cached against the mtime and only read when that moves.
    """
    global _watch_cache
    try:
        stamp = None
        chosen = None
        for candidate in WATCH_PATHS:
            try:
                seen_at = os.path.getmtime(candidate)
            except OSError:
                continue
            if stamp is None or seen_at > stamp:
                stamp, chosen = seen_at, candidate
        if stamp is None:
            return False, VIEW_SCENE
        if time.time() - stamp >= WATCH_WINDOW:
            return False, VIEW_SCENE
        if _watch_cache[0] != stamp:
            with open(chosen) as fh:
                want = fh.read(16).strip()
            _watch_cache = (stamp, VIEW_SCREEN if want == VIEW_SCREEN else VIEW_SCENE)
    except (OSError, ValueError):
        return False, VIEW_SCENE
    return True, _watch_cache[1]


def snapshot_interval(view=VIEW_SCENE, seen=None, screen_every=None):
    if seen is None:
        seen = watching()[0]
    if not seen:
        return SNAPSHOT_IDLE
    if view != VIEW_SCREEN:
        return SNAPSHOT_FAST
    return SNAPSHOT_SCREEN if screen_every is None else screen_every


def snapshot_due(now, last, period, tick):
    """Whether this camera frame is the one to publish.

    Checked once per camera frame and nowhere else, so the only rates this can
    produce are the camera's divided by whole numbers — 30, 15, 10, 7.5 on the
    binned sensor. Which of them a request lands on is what this decides.

    A strict `elapsed > period` always lands on the next one *down*: the frame
    arriving exactly on the deadline is a hair early, gets skipped, and the
    next one is a whole camera frame late. Simulated against a 30fps sensor,
    asking for 15 delivered 10.6, and 18, 20, 24 and 25 all delivered 15.1 —
    so the flag was close to meaningless above 15 and the default was a third
    short of its own label.

    Half a frame of slack takes whichever frame is *nearest* the deadline, so
    an unachievable rate rounds to the closest achievable one instead of always
    downward. `tick` is the measured gap between camera frames; None before
    two have been seen, which only costs the first frame of a session.
    """
    return (now - last) >= period - (tick or 0.0) * 0.5


def screen_every(fps):
    """Seconds between phone-view frames, from a rate a person typed.

    Clamped rather than refused. This is a comfort setting on somebody's own
    rig, and the failure modes at the ends are a slide show and a Pi composing
    frames between camera frames — neither worth stopping a shift over. A rate
    of zero or less would be a division by zero, which is worth refusing.
    """
    low, high = SCREEN_FPS_LIMITS
    try:
        want = float(fps)
    except (TypeError, ValueError):
        return SNAPSHOT_SCREEN
    if not (want > 0):
        return SNAPSHOT_SCREEN
    return 1.0 / min(high, max(low, want))


def load_config(path):
    if not os.path.exists(path):
        sys.exit('no %s — run calibrate.py first' % path)
    with open(path) as fh:
        return json.load(fh)


_config_error = None


def save_config(path, cfg):
    """Write the calibration back, atomically and never fatally.

    Atomically because the web server reads this file to report what the scanner
    is doing, and must never see a half-written one. Never fatally because this
    is a convenience — it saves the next run rediscovering what this one already
    knows — and a read-only card or a full disk is no reason to stop reading
    offers. The scanner keeps the corrected values in memory either way.
    """
    global _config_error
    try:
        tmp = path + '.part'
        with open(tmp, 'w') as fh:
            json.dump(cfg, fh, indent=2)
        os.replace(tmp, path)
        _config_error = None
    except Exception as e:
        message = str(e)
        if message != _config_error:
            _config_error = message
            print('could not save calibration (further identical errors '
                  'suppressed): %s' % message)


LORES = (640, 480)

# IMX519 modes, from `rpicam-hello --list-cameras`. The two smallest are
# *cropped* out of the sensor, not scaled down: 1280x720 sees only a
# 2560x1440 window and 1920x1080 only 3840x2160, so both throw away field of
# view. Only these two see the whole sensor, which is what a phone in a mount
# needs.
FULL_FOV_MODES = {
    '2328x1748': (2328, 1748),   # 2x2 binned, 30fps — the default
    '4656x3496': (4656, 3496),   # full resolution, 9fps
}


def start_camera(cfg, exposure_us, gain, lens):
    import camera as CAM

    cam, focus = CAM.open_camera()
    cap = cfg.get('capture', {})
    main_size = (cap.get('width', 2328), cap.get('height', 1748))

    # Pin the sensor mode explicitly. Left to itself picamera2 picks a mode from
    # the requested size, and on this sensor a smaller pick silently crops the
    # field of view — which moves the phone out of the calibrated quad.
    cam.configure(cam.create_video_configuration(
        main={'size': main_size, 'format': 'RGB888'},
        lores={'size': LORES, 'format': 'YUV420'},
        raw={'size': main_size},
        buffer_count=4,
    ))

    cam.start()
    time.sleep(1.0)

    # A phone screen is an emissive, PWM-dimmed panel: auto-exposure hunts on it,
    # and an exposure that is not a whole number of dimming cycles aliases into
    # rolling bands that drift down the picture. Pin both, and pick the exposure
    # by arithmetic rather than by taste — see exposure.py.
    ctrls = {
        'AeEnable': False,
        'AwbEnable': False,
        'ExposureTime': int(exposure_us),
        'AnalogueGain': float(gain),
    }

    # Advertised controls prove nothing: a tuning file with no autofocus
    # algorithm still exposes AfMode and then ignores every lens position.
    if focus.get('supported') and 'AfMode' in cam.camera_controls:
        from libcamera import controls
        ctrls['AfMode'] = controls.AfModeEnum.Manual
        ctrls['LensPosition'] = lens
    else:
        print('focus not settable (%s) — it is whatever the mount distance gives'
              % focus.get('reason', 'no autofocus'))

    cam.set_controls(ctrls)
    time.sleep(0.5)
    return cam


_read_error = None


def _read_failed(exc):
    """Report a read that raised, once per distinct fault.

    Rate-limited by message the same way the snapshot and config writers are:
    whatever makes one frame fail usually makes the next hundred fail too, and
    a log that repeats it at thirty lines a second buries the one line that
    said what happened.
    """
    global _read_error
    message = '%s: %s' % (type(exc).__name__, exc)
    if message != _read_error:
        _read_error = message
        log('read failed (further identical errors suppressed): %s' % message)


def _read_ok():
    """Forget the last fault, so its return is reported rather than suppressed.

    The rate limiter compares against the last message seen and never cleared
    it, so a fault that came back an hour later — a full disk that was emptied
    and filled again, a camera that recovered and failed once more — matched the
    suppressed message and was silent for the rest of the shift. The other rate
    limiters in this file clear on success for the same reason.
    """
    global _read_error
    _read_error = None


_snapshot_error = None


def write_snapshot(frame, cfg, path, quad=None, roi=None, card=None, scale=None,
                   view=VIEW_SCENE):
    """Write what the camera sees, for the live page. Never fatally.

    `quad` overrides the calibrated corners so the outline follows the tracker
    rather than lagging behind it, `roi` is the box being read, and `card` is
    the reader's own last picture, which saves warping another one.

    `scale` says the frame is the preview stream rather than the sensor, and by
    how much — the corners are stored in capture coordinates, so they have to
    come down onto the smaller picture. See the call site for why that is worth
    doing: the sensor frame exists to be read, and copying twelve megabytes of
    it to make a 480px thumbnail is most of what the live view costs.

    `view` picks between aiming the camera and reading the phone through it.
    See SCREEN_HEIGHT.
    """
    global _snapshot_error
    quality = SNAPSHOT_QUALITY
    try:
        if quad is None:
            quad = np.array(cfg['quad'], dtype=np.float32)
        if scale is not None:
            quad = np.asarray(quad, dtype=np.float32) / np.asarray(scale, dtype=np.float32)
        if frame.ndim == 2:
            # The outline is drawn in green and the preview stream is luma, so
            # it has to become a colour picture before anything coloured goes on
            # it — otherwise the box comes out grey on grey.
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        picture = None
        if view == VIEW_SCREEN:
            picture = PL.screen_view(frame, quad, SCREEN_HEIGHT)
            if picture is not None:
                quality = SCREEN_QUALITY
        if picture is None:
            # No corners, or corners nothing could be warped out of. Falling
            # back to the scene is the useful answer rather than the tidy one:
            # it is the picture that shows *why* there is no phone view — the
            # phone out of frame, the mount knocked, the outline sitting on a
            # reflection — and it is the one the driver fixes that from.
            picture = PL.snapshot(frame, quad, roi,
                                  cfg.get('cardHeight', 900),
                                  width=SNAPSHOT_WIDTH, card=card,
                                  warp_card=scale is None)
    except Exception as e:
        message = str(e)
    else:
        message = PL.write_jpeg(path, picture, quality=quality)
    # This runs several times a second; repeating one broken thing that often
    # buries everything else in the log.
    if message and message != _snapshot_error:
        print('snapshot failed (further identical errors suppressed): %s' % message)
    _snapshot_error = message


# --- keeping the picture the reader was given -------------------------------
#
# The journal keeps what the OCR produced. It cannot keep what the OCR was
# LOOKING at, and that is the half every question about read quality needs:
# whether a crop was too tight, whether a threshold ate a decimal point,
# whether a different psm would have found the leg that went missing. All of it
# is answerable offline from the card image and none of it is answerable from
# the text, because the text is what the damage left behind.
#
# The greyscale card as it came off the warp, before preprocess(): that is the
# input to the decisions worth changing, and a picture of preprocess's own
# output cannot be used to judge preprocess.
#
# Off by default. This writes to an SD card in a car, and a feature that quietly
# fills one is worse than a feature nobody has. Turned on for a shift when there
# is a question worth answering, and bounded even then.
SCANS_KEEP = 400          # ...and the oldest go first
SCAN_QUALITY = 72         # ~40KB a card at the height the reader uses


def scan_dir(journal_path):
    """Where card pictures go: beside the journal, in a directory of their own."""
    return os.path.join(os.path.dirname(os.path.abspath(journal_path)), 'scans')


def prune_scans(where, keep=SCANS_KEEP):
    """Oldest first, so a long shift cannot outgrow the card it is written to."""
    try:
        names = sorted(n for n in os.listdir(where) if n.endswith('.jpg'))
    except OSError:
        return 0
    dropped = 0
    for name in names[:max(0, len(names) - keep)]:
        try:
            os.remove(os.path.join(where, name))
            dropped += 1
        except OSError:
            pass
    return dropped


def save_scan(image, offer_id, where, at=None, keep=SCANS_KEEP):
    """Keep one card picture. Never fatally: this is evidence, not the job.

    Named by the offer it belongs to and stamped, so a row in the journal and a
    picture on disk can be put back together months later without a second index
    to go wrong. Sorting the names sorts them by time, which is what lets the
    pruning above be a slice.
    """
    if image is None or not offer_id:
        return None
    try:
        os.makedirs(where, exist_ok=True)
        stamp = int((time.time() if at is None else at) * 1000)
        safe = re.sub(r'[^A-Za-z0-9_.-]', '_', str(offer_id))[:40]
        path = os.path.join(where, '%013d-%s.jpg' % (stamp, safe))
        problem = PL.write_jpeg(path, image, quality=SCAN_QUALITY)
        if problem:
            return None
        prune_scans(where, keep)
        return path
    except Exception:
        return None


def log(message):
    """A human-readable line for the log file.

    Deliberately not JSON. In --json mode every read goes to stdout as an
    object for the web server to parse; anything that fails to parse is passed
    through to the log instead, which is exactly where these belong. The point
    of them is that a log someone pastes back should be enough to diagnose the
    problem without also needing the rig.
    """
    sys.stdout.write(message + '\n')
    sys.stdout.flush()


# How often to summarise, and how often at most to quote what the reader saw.
# Both are rate limits rather than schedules: a quiet scanner says nothing.
HEALTH_EVERY = 120.0
SAMPLE_EVERY = 20.0


class Health:
    """Counts what happened, and says so occasionally.

    A per-read line would bury the log and a silent scanner cannot be
    diagnosed. This reports a summary only when something has actually
    happened since the last one.
    """

    def __init__(self):
        self.reset(None)
        self.relocks = 0
        self.rebaselines = 0
        self.gain = None
        self.bright = None
        self.banding = None
        # What the exposure is now, and what calibration measured it at. Only
        # worth a line when they differ — see report().
        self.exposure = None
        self.measured_exposure = None
        # The phone is brighter than the camera can take at any setting that
        # does not make the screen ripple. Not a fault in the rig, and the one
        # thing that fixes it is a slider on the driver's phone.
        self.too_bright = False
        self.too_dim = False

    def reset(self, now):
        # None rather than time.time(): the window starts when the first read
        # arrives, so the clock this is judged against is always the caller's.
        self.since = now
        self.reads = self.complete = self.no_pay = self.clipped = 0
        # Reads that raised. Counted here so the health line can still appear
        # when every one of them did: the guard in report() used to be `not
        # self.reads`, which is exactly true when the reader is broken, so the
        # log went quiet at the moment it had the most to say.
        self.failed = 0
        # Cards the rig definitely saw against cards it managed to record.
        #
        # The journal can only hold what was read, so the one number it can
        # never contain is how much it missed. This is the honest half of that:
        # a read that found a payout is proof a card was in front of the camera,
        # and an episode that ends without a journal row is one the rig watched
        # go past. It cannot see an offer it never read at all — no counter can
        # — so this is a floor on the miss rate rather than the whole of it, and
        # it is labelled that way everywhere it is shown.
        self.saw = self.kept = 0
        self.ms = []

    def add(self, out, parsed, card=None, previous=None):
        self.reads += 1
        self.ms.append(out['ms']['total'])
        if card is not None:
            # Banding only. `card` here is the image handed to the reader, which
            # has been through CLAHE and, on a dark-mode phone, inverted — and
            # banding survives both, because it is a difference between two
            # frames treated identically.
            #
            # Brightness does not survive either, which is why it is no longer
            # taken here. A contrast-stretched card reads near the target
            # whatever the exposure did, and an inverted one reads *backwards*:
            # a dark-mode card that is far too dark reported 241 against a
            # target of 205. That number is the one diagnostic for "the picture
            # looks too bright", and it was answering a different question from
            # the one the exposure loop steers by. It is set at the AutoGain
            # beat now, off the raw screen window, so the log and the controller
            # are talking about the same picture.
            if previous is not None and previous.shape == card.shape:
                self.banding = EX.banding_score([previous, card])
        if parsed.get('complete'):
            self.complete += 1
        if parsed.get('pay') is None:
            self.no_pay += 1
        if out.get('clipped'):
            self.clipped += 1

    def report(self, now, tracker, scanner):
        """Say what has happened lately. Returns the tally, or None if silent.

        The tally goes back to the caller because the counts are worth keeping
        as well as printing: the log is on the machine nobody reads, and how
        many cards went past unrecorded is a question a driver asks about a
        shift, days later, from the offers page.
        """
        if self.since is None:
            self.since = now
        if now - self.since < HEALTH_EVERY or not (self.reads or self.failed):
            return None
        if not self.reads:
            # Every read raised. There are no timings to summarise and nothing
            # else here is meaningful, but saying so is the whole point.
            log('health over %ds: %d reads, ALL FAILED — see the read failure '
                'above for what went wrong' % (now - self.since, self.failed))
            tally = {'over': int(now - self.since), 'saw': self.saw,
                     'kept': self.kept, 'reads': 0, 'failed': self.failed}
            self.reset(now)
            return tally
        median = sorted(self.ms)[len(self.ms) // 2]
        bits = ['%d reads, %d complete' % (self.reads, self.complete),
                'median %.0fms' % median]
        if self.failed:
            bits.append('%d failed' % self.failed)
        if self.saw:
            bits.append('%d card%s seen, %d recorded'
                        % (self.saw, '' if self.saw == 1 else 's', self.kept))
        if self.no_pay:
            bits.append('%d found no payout' % self.no_pay)
        if self.clipped:
            bits.append('%d had the payout at the crop edge' % self.clipped)
        # Brightness and banding, because "the picture looks dark" and "the
        # screen looks wavy" are things a person notices and a log should be
        # able to confirm or deny with a number.
        if self.bright is not None:
            bits.append('screen brightness %d/%d'
                        % (round(self.bright), round(EX.TARGET_BRIGHT)))
        if self.banding is not None:
            bits.append('banding %.1f%s' % (self.banding,
                                            ' (rippling)' if self.banding > 4.0 else ''))
        if self.gain is not None:
            bits.append('gain %.2f' % self.gain)
        # A shortened exposure is the one thing that can make the screen ripple
        # on a rig that measured a flicker-safe one, so if the banding number
        # above is high, the reason for it belongs on the same line.
        if self.exposure is not None and self.exposure != self.measured_exposure:
            bits.append('exposure %dus, borrowed against %dus for daylight'
                        % (self.exposure, self.measured_exposure))
        if self.too_dim:
            bits.append('TOO DARK with nothing left to give — turn the phone '
                        'brightness up')
        if self.too_bright:
            bits.append('OVER-EXPOSED with nothing left to give — turn the '
                        'phone brightness down')
        bits.append('crop %s' % _fmt_roi(scanner.crop_box))
        if tracker is not None:
            status = tracker.status()
            # Both numbers, because they answer different questions and the
            # reassuring one can be reassuring while the corners are nowhere
            # near the phone: drift is against the last save, which moves.
            # Three states, not two. "Held" used to cover being frozen beside
            # the screen as well as tracking it, because a candidate was found
            # on every check either way and only `misses` was being reported.
            where = ('lost' if status['lost']
                     else 'stuck' if status.get('stalled') else 'held')
            bits.append('corners %s, %.0fpx from calibration (%.0fpx since last save)'
                        % (where, status.get('wander', status['drift']), status['drift']))
            if self.relocks:
                bits.append('re-locked %dx since start' % self.relocks)
            if self.rebaselines:
                bits.append('un-stuck %dx — the stored calibration is out of date'
                            % self.rebaselines)
        log('health over %.0fs: %s' % (now - self.since, '; '.join(bits)))
        tally = {'over': int(now - self.since), 'saw': self.saw,
                 'kept': self.kept, 'reads': self.reads, 'failed': self.failed}
        self.reset(now)
        return tally


def _fmt_roi(roi):
    return 'whole screen' if not roi else '[%.2f %.2f %.2f %.2f]' % tuple(roi)


def say(text):
    try:
        subprocess.Popen(['espeak-ng', '-s', '165', text],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        pass


def spoken(rate):
    # A reading that cannot be true gets named, not priced. Saying "accept,
    # three thousand five hundred an hour" out loud is worse than saying
    # nothing: the driver is looking at the road, the voice is the whole of
    # what they get, and a number that confident is one they will act on.
    if rate['state'] == 'doubt':
        return {'pay': 'check the pay.', 'time': 'check the time.',
                'speed': 'check the distance.'}.get(rate.get('doubt'),
                                                    'read that again.')
    dollars = int(round(rate['perHour']))
    word = {'go': 'accept', 'warn': 'close', 'no': 'pass'}[rate['state']]
    return '%s. %d an hour.' % (word, dollars)


def show(frame_text, rate, parsed, ms, locked):
    if not rate['ready']:
        print('%s  no offer' % frame_text)
        return
    flags = []
    if rate.get('doubt'):
        flags.append('%s outside anything a real offer does — no verdict'
                     % rate['doubt'])
    if parsed['milesCorrected']:
        flags.append('decimal recovered')
    if parsed['milesUncertain']:
        flags.append('distance unreadable, cost ignored')
    if parsed.get('grew'):
        flags.append('%d legs merged from %d reads'
                     % (parsed.get('legs') or 0, parsed.get('mergedFrom') or 0))
    print('%s  $%.2f/hr  %-4s  pay $%.2f  %s min  %s mi%s  [%.0fms]%s'
          % (frame_text, rate['perHour'], rate['state'].upper(), parsed['pay'],
             parsed['minutes'], parsed['miles'],
             '  (%s)' % '; '.join(flags) if flags else '',
             ms['total'], '  LOCKED' if locked else ''))


# How often to say "still here" when there is nothing to report.
#
# The driving page decides the scanner has stopped when it has not heard
# anything for twelve seconds, and it used to infer that from reads — which was
# always a little indirect and is now wrong. Between offers the motion gate can
# hold a still picture for minutes without a single read, and *during* an offer
# the verify beat backs off to twelve seconds, so a card sitting unchanged with
# a 1.4s read on the end of the beat produces a 13.4s silence. The page would
# dim the verdict and say the rig had stopped at the exact moment the driver is
# reading it to decide.
#
# So the loop says so itself, on a beat well inside that window. It is one small
# line of JSON: no verdict, no numbers, nothing that can overwrite a reading —
# `ready` is absent, which is what the server and the page both key on. What it
# proves is the thing actually worth proving, which is that the loop is turning.
# A wedged loop stops sending it; a process that is merely idle does not.
ALIVE_EVERY = 4.0


def emit_alive(too_bright=False, too_dim=False):
    """The beat, and the one condition that has to reach the driver without one.

    `tooBright` rides here rather than on a reading because the state it
    describes is precisely the state where there may be no reading: the phone is
    brighter than the camera can take, the card is washing out, and the remedy
    is a slider the driver has in their hand. Sent every beat so the page can
    clear it as soon as it goes away, and outside `ready` so it can never
    overwrite a verdict.
    """
    print(json.dumps({'alive': True, 'at': int(time.time() * 1000),
                      'tooBright': bool(too_bright),
                      'tooDim': bool(too_dim)}), flush=True)


def emit_reading():
    """A card is in front of the reader and the reader has started on it.

    The one thing the driver could not see. A read is about 1.4 seconds on a
    Pi 4 and 91% of it is inside tesseract, and for every one of those seconds
    the dashboard said WAITING FOR AN OFFER over a row of dashes — which is what
    it says when there is nothing on the phone at all. The card was there, the
    rig had noticed it, and the panel was reporting the opposite.

    Sent when the frames are handed over rather than when the verdict comes
    back, because the whole point is the gap between the two. Like the
    heartbeat, it carries no `ready` and no numbers, so it cannot overwrite a
    verdict or vouch for one — it says only that the wait has a reason.
    """
    print(json.dumps({'reading': True, 'at': int(time.time() * 1000)}),
          flush=True)


def emit_dropoff(address, ms=None):
    """The destination, once the driver has asked for it and it has been read.

    Its own line, like the offer id and for the same reason: it is not part of a
    verdict and must not be able to stand in for one. Nothing about this reading
    says anything about an offer — there is no offer on the screen, there is a
    navigation app — so it carries no `ready`, no rate and no pay.

    Emitted once per press. The window stays open afterwards only until an
    address is found; a second one arriving would be the driver having moved on
    to a different screen, and the first is the one they asked about.
    """
    print(json.dumps({'dropoff': {
        # What to show and what to store. `city` and `zip` are what the
        # geography is actually decided on — see Advice.sameArea — and `line` is
        # what the driver reads to tell whether the scan worked.
        'line': address.get('line'),
        'street': address.get('street'),
        'city': address.get('city'),
        'state': address.get('state'),
        'zip': address.get('zip'),
        'ms': ms,
        'at': int(time.time() * 1000)}}), flush=True)


def emit_offer(offer_id, parsed, rate):
    """Which offer is now on the record, so the driver can say they took it.

    The one thing the rig cannot see is the driver pressing Accept, and it must
    never press it — so whether an offer was taken is a fact only the driver
    has. Recording it meant opening the offers page afterwards and finding the
    row, which is a thing nobody does at the wheel and few people do later.

    So the driving screen gets a button, and this is what makes that possible:
    the journal's own id for the card that was just written. Without it the page
    could only mark by pay-and-minutes, which is a *rule* — it would mark every
    offer paying that to the cent, and this project has two genuinely different
    cards doing exactly that inside one window (see test_repeats.py).

    Sent as its own line rather than on the reading, because the id is not known
    until after the journal has been written and the reading has already gone
    out. Like the heartbeat, it carries no `ready` and no verdict, so it can
    neither overwrite one nor stand in for one.

    The pay and the minutes ride along so the button can *name* what it will
    mark. By the time a driver has accepted on their phone the card is gone from
    the panel — the scanner sees the navigation screen and the verdict clears —
    so a button saying only "took it" would be marking something the driver can
    no longer see.
    """
    print(json.dumps({'offer': {
        'id': offer_id,
        'pay': parsed.get('pay'),
        # The card's own minutes, not the billed ones: a figure with the
        # driver's pickup pad added would not match the card they are trying to
        # remember. `or`, not a two-argument `get` — `rate` always carries the
        # key and it is `None` on a card that stated no duration, so the default
        # would never have been reached.
        'minutes': rate.get('cardMinutes') or parsed.get('minutes'),
        'perHour': round(rate['perHour'], 2) if rate.get('ready') else None,
        # Everything server.js builds `scanner.holding` out of when the driver
        # marks this offer as taken. It read six fields off this object and was
        # sent four, so the order in the car had no distance, no running cost
        # and no ends.
        #
        # `cost` is the one that moved money: Advice.stack subtracts the NEW
        # offer's running cost and took the held job's as zero, so the "+ the
        # one you have" range on the driving screen came out silently high -
        # about $1.80/hr on a five-mile job at 30c a mile, with nothing on the
        # screen saying so. `billedMinutes` is what the pair's time is measured
        # over, and `dropoff` is the end sameArea compares against.
        'billedMinutes': rate.get('billedMinutes', parsed.get('minutes')),
        'miles': rate.get('miles', parsed.get('miles')),
        'cost': (round(rate['cost'], 2)
                 if rate.get('ready') and rate.get('cost') is not None else None),
        'dropoff': parsed.get('dropoff'),
        'pickup': parsed.get('pickup'),
    }, 'at': int(time.time() * 1000)}), flush=True)


def emit(rate, parsed, ms, locked, tracker=None, scanner=None, whole=None):
    """One JSON object per line, flushed, so a parent process sees reads live."""
    payload = {
        'track': tracker.status() if tracker is not None else None,
        'ready': rate['ready'],
        'locked': locked,
        'state': rate['state'],
        # Which figure is impossible, so the page can name it rather than just
        # refusing to say anything. The numbers below are still sent: the driver
        # is looking at the same card and is the one who can tell which of them
        # the camera got wrong.
        'doubt': rate.get('doubt'),
        'perHour': round(rate['perHour'], 2) if rate['ready'] else None,
        # Both rates, and the time they were both divided by. The card's own
        # minutes are below as `minutes`, for checking against the phone; these
        # are what the arithmetic actually used, which differ once `pad` or
        # `secondsPerItem` is set. Sending both is what lets the page show a
        # sum that adds up instead of one it has to guess at.
        'grossPerHour': round(rate['grossPerHour'], 2) if rate['ready'] else None,
        'billedMinutes': round(rate['minutes'], 1) if rate['ready'] else None,
        # `is not None`, not truthiness: this is a number that can legitimately
        # be zero, and now that it is net of running costs it can be negative
        # too. Testing it for truth turned "you break exactly even per mile"
        # into "--".
        'perMile': (round(rate['perMile'], 2)
                    if rate.get('perMile') is not None else None),
        'pay': parsed['pay'],
        'minutes': parsed['minutes'],
        # The minutes the verdict was made over, and where they came from. On a
        # ride card this is the card's own figure; on a delivery card the card
        # states none and this is the time left until its deadline. Sent
        # separately from `billedMinutes`, which has the driver's own pad and
        # shopping allowance added and is a different claim again.
        'cardMinutes': rate.get('cardMinutes'),
        'fromDeadline': bool(rate.get('fromDeadline')),
        'deliverBy': parsed.get('deliverBy'),
        'places': parsed.get('places') or [],
        # Which of those places is which end, and the line the verdict was
        # judged against. All four were missing, and between them they made the
        # whole stacking half of the driving screen a fiction.
        #
        # `dropoff` and `pickup`: Advice.stack asks sameArea(active.dropoff,
        # offer.dropoff) to say whether two jobs END near each other, and
        # server.js stores the same field against the order in the car. Neither
        # side ever had it - the reading carried `places` and nothing named the
        # two ends - so `ends` and `route` were null on EVERY real reading. The
        # town rule, the ZIP rule and the map link had never once fired in the
        # car; every measurement of them was made on journal rows, which derive
        # the fields separately and therefore have them.
        'dropoff': parsed.get('dropoff'),
        'pickup': parsed.get('pickup'),
        # `target` and `band`: Advice.stack takes the target from the reading
        # and falls back to ZERO when it is not a number - and `worst >= 0` is
        # true of almost every pair, so the stack line was painted GREEN, "take
        # both", for pairs that lose money against simply finishing the order
        # already in the car. rate() has returned both of these all along; they
        # simply never made it onto the wire.
        'target': rate.get('target'),
        'band': rate.get('band'),
        # The distance the verdict was made over. On a delivery card parse()
        # had no time to check it against and rate() recovers a lost decimal
        # there, so taking it from parsed would put 24 miles on the panel
        # beside a rate worked out over 2.4.
        'miles': rate.get('miles', parsed['miles']),
        'items': parsed['items'],
        'milesCorrected': rate.get('milesCorrected', parsed['milesCorrected']),
        'milesUncertain': rate.get('milesUncertain', parsed['milesUncertain']),
        # What was taken off the top, and at what rate. Without these the page
        # cannot explain its own headline: a driver who works out 7.09 over 34
        # minutes gets $12.51/hr and the screen says $10.61, with nothing on it
        # saying that 3.6 miles of running costs came out first.
        'cost': round(rate['cost'], 2) if rate.get('ready') else None,
        'costPerMile': rate.get('costPerMile'),
        'ms': round(ms['total']),
        'text': (parsed.get('text') or '')[:200],
        'legs': parsed.get('legs'),
        'mergedFrom': parsed.get('mergedFrom', 1),
        'grew': bool(parsed.get('grew')),
        # Whether the reading is finished, which is not the same claim as
        # `locked` and is the one the driver needs. `locked` means two
        # consecutive frames parsed the same — and two frames that both lose the
        # pickup leg to the same glare agree perfectly with each other. This
        # loop already knows the difference: it is what decides whether to keep
        # resampling and whether to speak, and it was the only consumer. The
        # page was left to infer a finished reading from `locked` and drew a
        # plain ACCEPT on a card missing half its journey, which reads as a much
        # better offer than it is.
        'whole': None if whole is None else bool(whole),
    }
    sys.stdout.write(json.dumps(payload) + '\n')
    sys.stdout.flush()


def _stop_on_sigterm():
    """Turn the supervisor's stop signal into an ordinary unwind.

    server.js stops the scanner with SIGTERM, and autopilot execv's into this
    process so that is where it lands. Python's default action for it ends the
    process without unwinding, which skips `finally: cam.stop()` and skips the
    atexit handler that deletes the OCR scratch file — a megabyte of /dev/shm,
    which is RAM, left behind on every stop. Raising SystemExit instead runs
    both.
    """
    import signal

    def handler(signum, frame):
        raise SystemExit(0)

    try:
        signal.signal(signal.SIGTERM, handler)
    except (ValueError, OSError):
        pass                    # not the main thread, or no such signal here


def main():
    _stop_on_sigterm()
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default=DEFAULT_CONFIG)
    ap.add_argument('--speak', action='store_true', help='say the verdict aloud via espeak-ng')
    ap.add_argument('--display', action='store_true', help='fullscreen verdict on an attached screen')
    ap.add_argument('--exposure', type=int, default=None,
                    help='microseconds. Defaults to the value measured at calibration, '
                         'or %d — one 60Hz cycle, which is also two of 120 and four of '
                         '240, so it does not band against any of them'
                         % EX.DEFAULT_EXPOSURE)
    ap.add_argument('--gain', type=float, default=None,
                    help='fixed analogue gain. Omit to let it track the phone dimming '
                         'itself, which is what a screen does at night')
    ap.add_argument('--no-auto-gain', action='store_true',
                    help='never adjust gain; use exactly what --gain says')
    ap.add_argument('--lens', type=float, default=None,
                    help='dioptres (1/metres): 4.0 focuses at 25cm. Defaults to the '
                         'value autofocus found during calibration')
    ap.add_argument('--json', action='store_true',
                    help='emit one JSON object per read on stdout, for another process to consume')
    ap.add_argument('--list-modes', action='store_true',
                    help='print the sensor modes this camera reports, then exit')
    ap.add_argument('--save-misses', metavar='DIR',
                    help='write frames that failed to parse, for tuning')
    ap.add_argument('--snapshot', default=DEFAULT_SNAPSHOT,
                    help='where to write the live view the web UI shows ("" to disable)')
    # Off unless asked for. See save_scan: this writes to an SD card in a car,
    # and a feature that quietly fills one is worse than a feature nobody has.
    ap.add_argument('--keep-scans', type=int, nargs='?', const=SCANS_KEEP,
                    default=0, metavar='N',
                    help='keep the last N card pictures beside the journal, for '
                         'working out why a read came back wrong (default off; '
                         'bare flag keeps %d)' % SCANS_KEEP)
    ap.add_argument('--journal', default=JR.DEFAULT_PATH,
                    help='where to keep every confident offer, for looking at '
                         'a shift afterwards. The web side reads the default '
                         'path, so if you move it, set JOURNAL to match or the '
                         'offers page will keep saying there is nothing there')
    ap.add_argument('--no-journal', action='store_true',
                    help='read offers without keeping any record of them')
    ap.add_argument('--no-parallel', action='store_true',
                    help='read one frame at a time. The default reads the '
                         'confirming frame alongside the first, which is 56%% '
                         'of the wall clock for the same evidence')
    ap.add_argument('--no-track', action='store_true',
                    help='never re-find the phone; use the calibrated corners exactly')
    ap.add_argument('--screen-fps', type=float, default=1.0 / SNAPSHOT_SCREEN,
                    help='frames a second for the phone view (default %d); it '
                         'buys a full sensor frame each time, so raise it until '
                         'reads slow down' % round(1.0 / SNAPSHOT_SCREEN))
    ap.add_argument('--no-thread', action='store_true',
                    help='read on the camera loop instead of beside it. The '
                         'default keeps the live view and the corner tracking '
                         'running through a read; this is the way back if a '
                         'rig ever misbehaves with it')
    args = ap.parse_args()

    if args.list_modes:
        from picamera2 import Picamera2
        cam = Picamera2()
        for m in cam.sensor_modes:
            print(m)
        cam.close()
        return

    cfg = load_config(args.config)
    health = Health()

    # Say so once, at the top, when a number in the settings block cannot be
    # read as one. The parser falls back to the documented default either way —
    # see offer_parser.setting — but silently using 25 when the driver typed
    # something else is how a shift gets scanned against the wrong target. This
    # block is hand-edited on the driver's instruction, so a stray quote or a
    # deleted value is a keystroke away, and the log is the only place it can
    # surface before the offers start.
    for key, default in sorted(OP.DEFAULT_SETTINGS.items()):
        given = (cfg.get('settings') or {}).get(key)
        if given is not None and OP.setting(given, None) is None:
            log('settings: %r is not a number I can use for %s, so %s is being '
                'used instead. Check the settings block in %s.'
                % (given, key, default, args.config))


    # Corners a person drew, rather than ones the detector found. They change
    # three things at once — see use_manual_box — and they turn tracking off,
    # because a tracker judges candidates against a calibrated *screen* and
    # would move a hand-drawn box back onto whatever it believes that is. The
    # driver overrode the detector; letting the tracker overrule them would put
    # the rig straight back where it was.
    manual = bool(cfg.get(CX.MANUAL_KEY))

    # Start tracking from where the last run ended, if it wrote that down —
    # a fixed mount usually has not moved between runs, so resuming saves
    # re-converging. `quad` stays the calibration; see QuadTracker.calibrated.
    scanner = PL.Scanner(
        # Resume where the last run ended — but only when tracking is on to
        # pull it back. --no-track promises the calibrated corners exactly, and
        # pinning a position no run can correct is the opposite of that.
        quad=np.array((None if (args.no_track or manual) else cfg.get('trackedQuad'))
                      or cfg['quad'], dtype=np.float32),
        card_height=cfg.get('cardHeight', 900),
        # A pin has to be asked for, under a key only a pin is written to.
        # `roi` cannot serve: every config.json written before the crop became
        # derived has one, and honouring an inherited value silently disables
        # the placement. The boxes in the wild are [0,0,1,1] (harmless but
        # slow), [0,0.40,1,0.60], and [0.02,0.48,0.96,0.50] — the old tight
        # crop, which lost the payout on 13 of 42 test cards.
        roi=cfg.get('cropBox'),
        # A hand-drawn box is all card. Measured as half a screen it would be
        # warped twice as tall as the reader can use, then shrunk back down
        # against the pixel budget — same text, three times the work, smaller
        # by the time it is read.
        card_share=1.0 if manual else None,
        settings=cfg.get('settings', {}),
    )
    # The tracker works in the small stream's coordinates and reports in the
    # capture's, so it needs the ratio between them.
    cap = cfg.get('capture', {})
    track_scale = (cap.get('width', 2328) / float(LORES[0]),
                   cap.get('height', 1748) / float(LORES[1]))
    capture_size = (cap.get('width', 2328), cap.get('height', 1748))
    # Start from where the last run left off, but judge candidates against the
    # calibration itself — see QuadTracker.calibrated.
    tracker = None if (args.no_track or manual) else TR.QuadTracker(
        scanner.quad, scale=track_scale,
        calibrated=np.array(cfg['quad'], dtype=np.float32))

    # Calibration already found focus with autofocus; reuse it rather than
    # making the driver rediscover a number that cannot change on a fixed mount.
    lens = args.lens if args.lens is not None else cfg.get('lensPosition') or 4.0

    # Exposure is chosen for flicker, not for brightness; gain then does the
    # brightening, because gain cannot reintroduce banding and exposure can.
    exposure_us = (args.exposure if args.exposure is not None
                   else cfg.get('exposureTime') or EX.DEFAULT_EXPOSURE)
    gain = args.gain if args.gain is not None else cfg.get('analogueGain') or 1.5
    # The rungs to fall back down when the light is more than gain can answer.
    # Calibration measured the banding of every candidate on this driver's own
    # phone; `exposureLadder` is which of them came back quiet. Without one —
    # a config written before this existed — AutoGain keeps its old guess about
    # panels in general, and says so, because on a 60Hz phone the first rung
    # below the calibrated exposure is the one that makes the screen ripple.
    ladder = cfg.get('exposureLadder')
    auto_gain = (None if (args.no_auto_gain or args.gain is not None)
                 else EX.AutoGain(gain, exposure=exposure_us,
                                  **({'candidates': ladder} if ladder else {})))
    cam = start_camera(cfg, exposure_us, gain, lens)
    if args.save_misses:
        os.makedirs(args.save_misses, exist_ok=True)
    if args.display:
        cv2.namedWindow('uber-scan', cv2.WND_PROP_FULLSCREEN)
        cv2.setWindowProperty('uber-scan', cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    # OpenMP is pinned to one thread per tesseract instance in pipeline.py, at
    # import, because that is now the last moment it can be: the engine runs
    # inside this process and libgomp reads the environment when it starts, not
    # when a subprocess is spawned. See PL.OMP_THREAD_LIMIT for why it is pinned.
    pair_reads = not args.no_parallel

    # Everything that decides what gets read, in one place, once. A log without
    # this is a log where every question starts with "what was it set to?".
    import calibrate as CAL
    quad = scanner.quad
    # The frame shape matters to the measurement, not just to the spill note
    # below: a screen taller than the frame has to be measured across rather
    # than down, or this reports the frame's height back at you.
    frame_shape = (cap.get('height', 1748), cap.get('width', 2328))
    log('scanning — ctrl-c to stop')
    log('setup: capture %dx%d, card ~%dpx on the sensor (floor %d), crop %s, '
        'warp %dpx, reader gets %dpx, lens %s%s'
        % (cap.get('width', 0), cap.get('height', 0),
           CAL.card_source_pixels(quad, frame_shape), CAL.MIN_CARD_PIXELS,
           _fmt_roi(scanner.crop_box),
           scanner.read_height, scanner.ocr_height,
           ('%.2f dioptres' % lens) if lens else 'fixed',
           '' if tracker is not None else
           (', reading a box set by hand — corner tracking OFF' if manual
            else ', corner tracking OFF')))
    log('setup: reads %s, %s'
        % ('paired — the confirming frame is read alongside the first'
           if pair_reads else 'one at a time (--no-parallel)',
           'beside the camera loop, which keeps the live view and the corner '
           'tracking going through one' if not args.no_thread
           else 'on the camera loop (--no-thread)'))
    log('setup: exposure %dus (%s), gain %.2f (%s)'
        % (exposure_us,
           'a whole number of 60/120/240Hz cycles, so the screen should not band'
           if exposure_us in EX.FLICKER_SAFE else 'not a standard flicker period',
           gain, 'tracking the screen' if auto_gain else 'fixed'))
    # Which rungs a bright phone can push it onto, and whether anybody checked.
    # A ladder measured on this screen is the difference between falling back
    # onto a quiet exposure and falling back onto one that ripples.
    if auto_gain is not None:
        below = [c for c in auto_gain.candidates if c < exposure_us]
        log('setup: if the phone gets brighter than gain can answer, exposure '
            'falls back to %s (%s)'
            % (', '.join('%dus' % c for c in reversed(below)) or 'nothing shorter',
               'measured quiet on this screen' if ladder
               else 'NOT measured on this screen — re-run calibration to '
                    'measure them, since a rung that bands is worse than a '
                    'card that is a little bright'))
    log('setup: corners %s' % [[int(x), int(y)] for x, y in quad])
    spill = PL.touches_edge(quad, frame_shape)
    if spill:
        log('setup: the screen runs off the %s of the frame. That is expected on a '
            'close mount and is not a problem — the crop is fitted to the card by '
            'content, not to the screen by fraction.' % ' and '.join(spill))
    accumulator = OfferAccumulator()
    last_sample = 0.0
    previous_card = None
    failures = 0
    spoke_for = None
    # The offer the driving screen has already been told about. Once per card,
    # not once per read: a card sits on screen for tens of seconds and is
    # re-read throughout, and the page needs the id rather than a heartbeat.
    told_offer = None
    frames = 0
    last_snapshot = 0.0
    # How long the camera actually leaves between frames, smoothed. Measured
    # rather than assumed: the sensor mode decides it (30fps binned, 9fps at
    # full resolution) and a rig may be started on either.
    tick = None
    last_tick = None
    # Read once here rather than per frame: it cannot change while running, and
    # this sits in the loop that also holds the camera.
    phone_view_every = screen_every(getattr(args, 'screen_fps', None))
    resample_until = 0.0
    # Which card the burst above is for, so it is armed once per card rather
    # than once per read. See where it is set.
    resample_for = None
    # Until when the driver's "read the dropoff" press is still live, and the
    # last address it produced. See DROPOFF_WINDOW and dropoff_requested.
    dropoff_until = 0.0
    dropoff_seen = None
    last_dropoff_read = 0.0
    last_resample = 0.0
    last_verify = 0.0
    verify_every = VERIFY_EVERY
    verify_signature = None
    card_on_screen = False
    settled_on = None
    # A read the gate asked for while the reader was still busy with the last
    # one. Remembered rather than dropped: the gate fires once, on the frame a
    # moving picture settles, so a trigger thrown away is a card never read.
    read_wanted = False
    last_alive = 0.0
    # The card currently being watched, and what has become of it. See
    # Health.saw — an episode that ends having shown a payout but written
    # nothing is a card the rig saw and failed to keep.
    seen_episode = None
    seen_pay = False
    seen_kept = False
    reader = Reader(scanner, threaded=not args.no_thread)

    # Every offer the scanner is sure of, kept so a shift can be looked at
    # afterwards. Seeded from the file rather than from nothing: the scanner is
    # restarted with a backoff when it dies, and a card sits on screen far
    # longer than a restart takes, so starting empty meant coming back to the
    # same offer and recording it twice.
    scans_where = scan_dir(args.journal)
    offer_log = None
    if not args.no_journal:
        offer_log = JR.OfferLog(
            JR.Journal(args.journal),
            keep_places=cfg.get('settings', {}).get('keepPlaces', True) is not False)
        # Counted, not built. This line says how many offers are on record and
        # it used to ask for every one of them as a Python object to find out —
        # 68MB on a year of driving, at every startup, on a Pi, beside a
        # resume() that was doing the same thing again.
        kept = offer_log.journal.count()
        resumed = offer_log.resume()
        log('journal: %s (%d offer%s so far)%s'
            % (args.journal, kept, '' if kept == 1 else 's',
               ', still on the last one' if resumed else ''))
    def digest(out, frame):
        """Everything a read means, once the reading itself is done.

        On the loop's thread, always — the accumulator, the journal, the voice
        and the agreement counter are all order-sensitive, and none of them is
        what made a read expensive. Only the OCR moved. Returns True when the
        driver has asked the display window to close.
        """
        # Everything below that outlives one read. A name missed here becomes a
        # local, silently, and the state it was carrying stops carrying — which
        # is how a loop rewritten into a closure loses its memory without
        # anything failing loudly enough to notice.
        nonlocal failures, settled_on, resample_until, resample_for, card_on_screen
        nonlocal dropoff_until, dropoff_seen
        nonlocal seen_episode, seen_pay, seen_kept
        nonlocal verify_every, verify_signature, last_verify, previous_card
        nonlocal last_sample, spoke_for, told_offer
        parsed = accumulator.add(out['parsed'])
        # The clock, for a delivery card that states a deadline instead of
        # a duration. Passed in rather than read inside the parser, which
        # has to stay a pure function of the text it was given so it can be
        # held to a fixed corpus.
        settings = dict(cfg.get('settings', {}))
        minutes_now = clock_minutes()
        if minutes_now is not None:
            settings['nowMinutes'] = minutes_now
        rate = OP.rate(parsed, settings)
        out['parsed'], out['rate'] = parsed, rate

        # The destination, when the driver asked for one and this reading has
        # it. Taken from the frame's OWN parse, not from the merged reading:
        # the accumulator exists to vote between frames of one offer card, and
        # a navigation screen is not an offer — it has no payout, so it never
        # enters a window and the merge has nothing to say about it.
        #
        # Ahead of everything below, because none of that applies either. A
        # screen with an address and no payout is `complete: False`, which is
        # the branch that decides the reading is not worth a verdict — correct
        # for an offer, and it would throw this away.
        if time.time() < dropoff_until and dropoff_seen is None:
            found = (out['parsed'] or {}).get('address')
            if found:
                dropoff_seen = found
                # Closed the moment it is answered, and what that closes is the
                # READ BEAT below - not this branch. `dropoff_seen` already
                # stops a second answer on its own, so an earlier comment
                # claiming this guards against overwriting was naming a job it
                # does not do, which is how a line like it gets deleted later.
                #
                # What it saves is up to two dozen more forced reads over the
                # rest of the window, and on a Pi a read is several seconds of
                # the whole computer's attention. Left open, the driver presses
                # the button, gets their address, and then finds the rig
                # unresponsive until the twelve seconds run out.
                dropoff_until = 0.0
                if args.json:
                    emit_dropoff(found, ms=out.get('ms'))
                log('destination read: %s' % found.get('line'))
        # Anything with a payout is worth a second look; anything without is
        # not an offer and should not hold the loop open.
        #
        # But a second look is all it takes once the reading is whole — a
        # total, or both legs of a two-leg card — and two reads running have
        # said the same thing. Sampling on past that point re-reads a card
        # nothing more can be learned from, which on a Pi is several seconds
        # of a small computer's whole attention. What keeps sampling is the
        # case that needs it: a single leg that is not a total, which is
        # exactly the shape of a card with a leg still missing.
        # Counted here because the Scanner stopped counting when the crop
        # stopped moving, and the log line that says "N in a row" is the
        # one that tells a bad frame from a broken mount. It had been
        # printing 0 every time, on every rig.
        failures = 0 if parsed['complete'] else failures + 1

        signature = (parsed['pay'], parsed['minutes'], parsed['miles'])
        # See OP.is_whole. Called rather than restated: this rule was written
        # out here and again in the browser scanner, both said "a total or two
        # legs", and a delivery card has neither — so every one of them was
        # permanently a fragment.
        whole = OP.is_whole(parsed)
        # Two different questions, kept apart.
        #
        # `stable` is the merged reading holding still across two reads, and
        # nothing else — which is what the journal's field of that name says
        # it stores. It has to be taken here because `settled_on` is
        # overwritten a few lines below; asking again after the overwrite
        # compares the signature with itself and is true on every read, so
        # every row was being stored as settled and the flag said nothing.
        #
        # Whether to STOP resampling is a stricter question: a reading that
        # holds still while a leg is still missing has not finished, it has
        # only stopped changing. Conjoining the two into the stored flag
        # made it redundant with `whole` instead of independent of it.
        stable = signature == settled_on
        # Whether there is still a card in front of the camera, which is
        # what the slow beat above is gated on. Taken from the payout rather
        # than from `complete`, because a card whose journey was lost is
        # still a card and is exactly the reading worth looking at again.
        card_on_screen = parsed.get('pay') is not None
        if not card_on_screen:
            last_verify = 0.0
        # The same card saying the same thing needs looking at less often
        # the longer it goes on saying it. Anything different — a
        # replacement offer, a leg that finally read, a figure that moved —
        # drops straight back to the fast beat, which is the case this
        # whole mechanism exists for.
        verify_every, verify_signature = next_verify(
            verify_every, verify_signature, signature, card_on_screen)

        # The short burst of extra looks after a card appears, so a leg one
        # frame missed can be caught by the next.
        #
        # Armed once per card, not once per read. Re-arming on every read makes
        # the burst self-sustaining: each read inside it pushes the end four
        # seconds further out, so a card that never reads *whole* — a single
        # plain leg with no total, which is eight of the owner's 245 rows —
        # holds the reader at one read every half second for as long as it is on
        # the screen. That is the opposite of what the verify beat's backoff is
        # for, and it wins, because it is checked first.
        if whole and stable:
            resample_until = 0.0
            resample_for = None
        elif parsed.get('pay') and parsed.get('episode') != resample_for:
            resample_for = parsed.get('episode')
            resample_until = time.time() + RESAMPLE_WINDOW
        settled_on = signature
        health.add(out, parsed, out.get('card'), previous_card)
        previous_card = out.get('card')

        # When a read comes back wrong, the one thing worth having is what
        # the reader actually saw. Rate limited, because a screen with no
        # offer on it fails constantly and correctly.
        now = time.time()
        if not parsed['complete'] and (now - last_sample) > SAMPLE_EVERY:
            last_sample = now
            why = ('the payout sat against the top edge of the crop'
                   if out.get('clipped') else
                   'no payout in the crop' if parsed['pay'] is None else
                   'a payout but no journey')
            log('read %d found nothing usable (%s, %d in a row). Reader saw: %r'
                % (frames, why, failures,
                   (out.get('text') or '').strip()[:220]))
        tally = health.report(now, tracker, scanner)
        note_tally(tally)

        if args.json:
            emit(rate, parsed, out['ms'], out['locked'], tracker, scanner, whole=whole)
        else:
            show('#%d' % frames, rate, parsed, out['ms'], out['locked'])

        if args.save_misses and not parsed['complete']:
            cv2.imwrite(os.path.join(args.save_misses, 'miss-%d.png' % int(time.time())), frame)

        # Speak once per offer, never per frame — and only once the
        # reading is *whole*.
        #
        # `locked` means two consecutive raw frames parsed the same, which
        # is not the same claim: two frames that both lose the pickup leg
        # to the same glare agree perfectly with each other. The loop
        # already computes `whole` for exactly this distinction and uses it
        # to decide whether to keep resampling; speaking before it is
        # announcing a number the scanner is still in the middle of
        # correcting, and a two-leg card missing a leg reads as a much
        # better offer than it is.
        if args.speak and out['locked'] and whole and rate['ready']:
            sig = (parsed['pay'], parsed['minutes'])
            if sig != spoke_for:
                spoke_for = sig
                say(spoken(rate))
        if not rate['ready']:
            spoke_for = None

        # Keep the offer. Same confidence the spoken verdict uses, so the
        # file and the voice can never disagree about what was read.
        #
        # Unlike `spoke_for`, nothing here is cleared by a read that came
        # back empty. Clearing on a bad read is right for speech — the next
        # card should be announced even if it pays the same — but it is
        # wrong for a file: a clipped payout parses as nothing at all, so
        # one glare frame during the resample burst would re-arm the gate
        # and record the same card twice. What separates one offer from the
        # next here is the accumulator's own episode, which is the thing
        # that actually knows.
        #
        # Whether the reading had settled is recorded rather than required.
        # A card whose OCR never holds still is the marginal reading most
        # worth studying afterwards, and refusing to write it would leave
        # the hardest offers missing with nothing to say so.
        #
        # `whole` is recorded rather than required, for the same reason
        # `settled` is. Requiring it dropped two real shapes without a
        # word: a single-leg card whose "total" the reader mangled, and a
        # two-leg card no single frame ever caught both halves of. Those
        # readings are optimistic — a card's first leg alone looks like a
        # much better job than the card is — so they must not reach a
        # median. But dropping them makes the offer *vanish*, and a gap
        # nothing accounts for is the worst thing to find in a file being
        # read back months later. Written and flagged: the page sets them
        # aside and says how many, and if a later frame does see the card
        # whole it supersedes the partial row anyway.
        # Which card this reading belongs to, and whether that card has yet
        # made it into the file. See Health.saw: an episode with a payout in it
        # is a card the rig certainly saw, and one that ends with nothing
        # written is one it watched go past.
        # Counted the moment it happens, not when the card goes.
        #
        # Waiting for the episode to end sounds tidier and loses the last card
        # of every window: a card still on the screen when the two minutes are
        # up has not ended, so it is never counted, and one that sits there for
        # a whole shift is never counted at all. Counting on the transition can
        # split one card across two windows — seen in the first, kept in the
        # second — which costs nothing, because both totals are added up over
        # the whole range before anyone divides them.
        episode = parsed.get('episode')
        if episode != seen_episode:
            seen_episode = episode
            seen_pay = False
            seen_kept = False
        if parsed.get('pay') is not None and not seen_pay:
            seen_pay = True
            health.saw += 1

        if offer_log is not None and rate['ready'] and out['locked']:
            landed = offer_log.consider(parsed, rate, ms=out['ms']['total'],
                                        locked=out['locked'], whole=whole,
                                        settled=stable) is not None
            # Nothing written because there was nothing new to say means an
            # earlier reading of this same card already landed, which is still
            # a card that reached the file.
            if (landed or offer_log.id is not None) and not seen_kept:
                seen_kept = True
                health.kept += 1
            # The picture the reader was given, against the offer it produced.
            #
            # Written on the reads that land a row rather than on every read, so
            # what is on disk is the offers in the journal and not every glance
            # at an empty mount. `landed` is false on a re-read that said
            # nothing new, and that is the right moment to skip: the card has
            # not changed and neither would its picture.
            if args.keep_scans and landed and offer_log.id:
                save_scan(out.get('fitted'), offer_log.id, scans_where,
                          keep=args.keep_scans)
            # ...and say which offer that is, once per card rather than once
            # per read. The driving screen holds it so the driver can mark it
            # as taken without going and finding the row afterwards.
            if args.json and offer_log.id is not None and offer_log.id != told_offer:
                told_offer = offer_log.id
                emit_offer(offer_log.id, parsed, rate)

        if args.display:
            cv2.imshow('uber-scan', render_panel(rate, parsed, whole=whole))
            if cv2.waitKey(1) & 0xFF == ord('q'):
                return True
        return False

    def note_tally(tally):
        """Keep the health tally, not just print it.

        A `kind` row, the same way the web side records a tag: an offer never
        carries one, so nothing that reads offers has to learn about these, and
        the sync already carries them. Written only when a card was actually
        seen — a quiet two minutes with the phone out of the mount is not
        evidence about anything and would bury the windows that are.
        """
        if offer_log is None or not tally or not tally.get('saw'):
            return
        at = JR.now_ms()
        offer_log.journal.append({
            'v': JR.SCHEMA, 'kind': 'seen', 'at': at,
            # An id and a seq because the sync keys on that pair; without them
            # every one of these would look like the same row to the far end.
            'id': 'seen-%d' % at, 'seq': 1,
            'over': tally.get('over'), 'saw': tally.get('saw'),
            'kept': tally.get('kept'),
        })

    def collect():
        """Take a finished read, if there is one, and act on it."""
        done = reader.take()
        if done is None:
            return False
        if done['error'] is None:
            _read_ok()
        else:
            # A read is the one part of this loop that touches an external
            # engine, a homography and a JPEG encoder, and any of them can
            # throw on one bad frame: a degenerate quad, a tesseract
            # invocation that fails, a full disk. Killing the process for it
            # means the supervisor's backoff, a camera re-open, and roughly a
            # minute of not scanning — for a frame that would have been
            # replaced 30ms later.
            _read_failed(done['error'])
            # Counted so the two-minute health line can still appear when every
            # read is failing — see Health.report.
            health.failed += 1
            note_tally(health.report(time.time(), tracker, scanner))
            return False
        batch = done['outs']
        # The earlier frame's reading is evidence too: the accumulator merges
        # partial reads, and a leg lost to glare in one frame is often present
        # in the other.
        for earlier in batch[:-1]:
            accumulator.add(earlier['parsed'])
        return digest(batch[-1], done['frames'][0])

    try:
        while True:
            # A read that finished while the camera kept running. Taken here,
            # at the top, because everything below can `continue` past it.
            if collect():
                break

            # ...and a word to say the loop is turning, on a beat the driving
            # page's staleness test comfortably clears. See ALIVE_EVERY: a
            # verdict is not proof of life, because a still picture produces no
            # reads and a card sitting unchanged produces one every twelve
            # seconds. Emitted before the capture below, so a camera that has
            # stopped delivering frames stops this too — which is exactly the
            # fault worth showing.
            if args.json:
                now_alive = time.time()
                if now_alive - last_alive > ALIVE_EVERY:
                    last_alive = now_alive
                    emit_alive(too_bright=health.too_bright,
                               too_dim=health.too_dim)
            request = cam.capture_request()
            try:
                # The Y plane leads the YUV420 buffer, and luma is all the gate
                # needs. Taken from the flat buffer rather than a reshaped array
                # so the chroma planes cannot be mistaken for image rows.
                buf = request.make_buffer('lores')
                luma = np.frombuffer(buf, dtype=np.uint8,
                                     count=LORES[0] * LORES[1]).reshape((LORES[1], LORES[0]))
                now = time.time()
                if last_tick is not None:
                    gap = now - last_tick
                    # A gap of a second is a stall, not a frame rate.
                    if 0 < gap < 1.0:
                        tick = gap if tick is None else tick * 0.9 + gap * 0.1
                last_tick = now
                # `track_scale` confines the gate to the phone. Without it the
                # mean is taken over the whole cabin and a card appearing on a
                # dark-mode screen scores below the threshold — see _motion.
                do_read = scanner.should_read(luma, track_scale)
                moved = False           # did the corners shift on this frame?

                # Re-find the phone on this same small frame. A mount is not a
                # clamp, and corners a centimetre out slide the crop off the
                # payout — which looks exactly like no offer being on screen.
                #
                # Done here, on the stream the motion gate already has, it costs
                # about a millisecond and needs no full-resolution capture at
                # all; finding the corners on a sensor frame costs seven times
                # as much, almost entirely in shrinking the frame down to this
                # size. Blurred frames are skipped: a smeared edge is a worse
                # guess than the corners already held.
                if reset_requested():
                    if manual:
                        # Re-find is also the way *out* of a hand-drawn box, and
                        # it has to find something before it throws one away:
                        # dropping the box first would leave the rig reading
                        # corners nobody has checked, which is the state the
                        # driver drew the box to escape.
                        found = PL.detect_screen_quad(luma, work_width=PL.DETECT_WIDTH)
                        if found is None:
                            log('re-find asked for, but there is no screen in view to '
                                'find — the box you drew is still in use. Try again '
                                'with the phone lit and a darker border around it.')
                        else:
                            quad_px = (np.asarray(found, dtype=np.float32)
                                       * np.asarray(track_scale, dtype=np.float32))
                            manual = False
                            scanner.quad = quad_px
                            scanner.roi = None
                            scanner.fixed_card_share = None
                            cfg['quad'] = [[float(x), float(y)] for x, y in quad_px]
                            CX.clear_in_config(cfg)
                            save_config(args.config, cfg)
                            tracker = None if args.no_track else TR.QuadTracker(
                                quad_px, scale=track_scale, calibrated=quad_px)
                            # Same reason as the box below: the corners and the
                            # crop both just changed under a still picture.
                            moved = do_read = True
                            log('back to finding the phone automatically: the screen '
                                'in view now is the calibration, the crop is derived '
                                'from it again, and tracking is %s'
                                % ('off (--no-track)' if tracker is None else 'on'))
                    elif tracker is not None:
                        tracker.start_over()
                        scanner.quad = tracker.quad
                        cfg.pop('trackedQuad', None)
                        save_config(args.config, cfg)
                        log('outline reset: back to the calibrated corners, and '
                            'the next screen in the middle of the frame will be '
                            'taken as the phone')
                    else:
                        log('outline reset asked for, but tracking is off '
                            '(--no-track), so the corners are already fixed')

                # "The screen in front of you is the destination."
                #
                # An offer card does not say where a delivery ends - 106 of this
                # driver's 604 cards print "Customer dropoff" and no address, so
                # 18% of everything the rig sees can never name a destination
                # before it is accepted. The address is on the screen that comes
                # after, and this is the driver saying so.
                #
                # It opens a window rather than taking one reading, because the
                # press and the address are not simultaneous: the driver still
                # has to get the destination up, and the phone then sits
                # perfectly still showing it - which is precisely what the
                # motion gate scores as nothing happening.
                if dropoff_requested():
                    dropoff_until = now + DROPOFF_WINDOW
                    dropoff_seen = None
                    # `do_read` here looks redundant against the beat further
                    # down, and on the FIRST press it is: last_dropoff_read
                    # starts at 0.0, so the beat fires on this same pass. It is
                    # not redundant on a second press within half a second of
                    # the last read of the first window, which is the only case
                    # that separates them - worth half a second, not worth a
                    # timing-sensitive test, and written down so it does not get
                    # deleted as dead on the strength of the first press alone.
                    moved = do_read = True
                    log('reading the destination for the next %d seconds: put '
                        'the address on the phone' % int(DROPOFF_WINDOW))

                # A box drawn on the live view. It arrives as fractions of the
                # frame, which is the only form that survives the trip: what the
                # driver drew on was a 480px JPEG of a 2328px sensor frame.
                drawn = CX.take_request()
                if drawn is not None:
                    manual = True
                    use_manual_box(scanner, CX.in_pixels(drawn, capture_size))
                    CX.apply_to_config(cfg, drawn, capture_size)
                    save_config(args.config, cfg)
                    tracker = None
                    # Read it now. The whole crop just changed, and the motion
                    # gate cannot tell — it watches the frame, and the frame is
                    # a card sitting still, which is exactly what it looks like
                    # while somebody draws a box round it. Without this, pressing
                    # "read this box" does nothing visible until the picture next
                    # moves, which reads as the button not having worked.
                    moved = do_read = True
                    log('crop box set by hand to [%s] of the frame: reading exactly '
                        'that, with corner tracking off until re-find is pressed'
                        % CX.describe(drawn))

                if tracker is not None and scanner.settled:
                    was = tracker.status()
                    jumps_before, lost_before = tracker.jumps, was['lost']
                    stalled_before = was['stalled']
                    rebased_before = tracker.rebaselines
                    if tracker.update(luma, now):
                        scanner.quad = tracker.quad
                        # Where tracking has got to, kept apart from `quad`,
                        # which is the calibration and is written only by
                        # calibrate.py / autopilot.py.
                        cfg['trackedQuad'] = [[float(x), float(y)] for x, y in tracker.quad]
                    # A re-lock is a different rectangle, so it is a different
                    # picture to read as surely as a different picture would be
                    # — and the motion gate cannot see it, because it watches
                    # the frame and the frame did not change. Without this the
                    # read that finally uses the corrected box waits for the
                    # resample tick, or for the driver to move something.
                    #
                    # Only a re-lock. The ordinary path eases 35% of the way to
                    # the candidate on each check and reports every one of those
                    # steps as a move, so treating "moved" as "read again" put
                    # fourteen reads through one stationary card where two had
                    # done. A few pixels of drift does not invalidate the read
                    # that just happened; being on a different phone does.
                    if tracker.jumps > jumps_before or tracker.rebaselines > rebased_before:
                        moved = do_read = True
                    if tracker.rebaselines > rebased_before:
                        health.rebaselines += 1
                        log('corners un-stuck: the screen in front of the camera '
                            'is not the size the stored calibration describes, and '
                            'has been steadily so for %ds, so the corners were '
                            'moved onto it and the calibration taken as out of '
                            'date. Reading carries on — but re-run calibration '
                            'when you can, or the next start will be stuck again.'
                            % TR.RECOVER_AFTER)
                    elif tracker.jumps > jumps_before:
                        health.relocks += 1
                        log('corners re-locked: the phone is somewhere the stored '
                            'calibration did not expect, and has been for several '
                            'checks running. Mount moved?')
                    lost_now = tracker.status()['lost']
                    if lost_now != lost_before:
                        log('screen %s' % ('not visible — is the phone lit and in frame?'
                                           if lost_now else 'visible again'))
                    # Being stuck used to be one word in a health line every two
                    # minutes, which is not where anybody was looking. The
                    # automatic recovery handles a phone that has been re-seated;
                    # what it deliberately will not do is adopt a candidate of
                    # the wrong shape, and the commonest wrong shape is the white
                    # offer card on its own — the crop is a fraction of the
                    # corners, so corners drawn round the card read the journey
                    # and lose the payout. That case cannot be fixed by moving
                    # the box, only by the person who can see the screen.
                    stalled_now = tracker.status()['stalled']
                    if stalled_now != stalled_before:
                        log('outline stuck: the corners have been off the screen '
                            'the camera can see for %ds. If the box is drawn '
                            'round part of the offer card rather than the whole '
                            'phone, the screen is probably washed out — shade it '
                            'or dim it. Otherwise press reset on the live page, '
                            'or re-run calibration.' % TR.STALL_VISIBLE
                            if stalled_now else 'outline unstuck: the corners are '
                            'back on the screen')
                    if tracker.needs_save(now):
                        save_config(args.config, cfg)
                        tracker.mark_saved(now)

                # A phone dims itself. A screen set up in daylight is a much
                # darker subject at two in the morning, and a fixed exposure that
                # suited one leaves the other too dark to read. Exposure stays
                # where it was measured — moving it would undo the flicker
                # arithmetic — and gain does the adapting, slowly, off the same
                # small frame the gate just used.
                #
                # Measured on the screen, not the frame. The dark car around
                # the phone is most of the picture and none of the subject: it
                # drags the brightness reading down and divides the blown-out
                # fraction by however much of the frame it fills, so a card
                # sitting at 237 with a fifth of it clipped still asked for
                # more gain. Rig logs showed the gain hunting between 6.8 and
                # its 8.0 ceiling while the card was over-exposed the whole
                # time, which is also what turns a screen's flicker into the
                # ripple that fails reads.
                #
                # And only while there is a screen there to expose for. The
                # window is wherever the phone was last seen, so once the phone
                # is out of the mount it is dark upholstery, and the gain used
                # to wind up chasing a card that had gone — railing at 8x in
                # about 78 seconds and then needing a further minute of
                # six-second steps to come back down once the phone returned.
                # That minute lands exactly when the driver has picked the phone
                # up to look at an offer.
                #
                # Deliberately NOT gated on the picture having settled, which
                # is what it used to be, and which made the two halves of this
                # into a trap that closed. Shortening the exposure is what a
                # blown-out card provokes; on a 60Hz panel the rung below the
                # calibrated one made the screen ripple; a rippling screen never
                # settles — the motion gate reads 75 against a settle threshold
                # of 2 — so this branch never ran again, the exposure could
                # never be given back, and `should_read` never fired either. One
                # nudge of the phone's brightness slider ended the shift, with
                # the loop still saying "still here" every four seconds.
                #
                # Nothing here needed a still picture in the first place: a
                # percentile and a count of full-well pixels do not care whether
                # the frame is moving. The tracker's own settled gate is above,
                # where it earns its keep.
                #
                # With no corners there is no screen to expose for, and the
                # fallback used to be the whole frame — which exposure.py spends
                # eleven lines explaining is the one thing not to hand it, since
                # the dark car around the phone is most of the picture and none
                # of the subject. Skipping the beat is the honest answer.
                if auto_gain is not None and scanner.quad is not None:
                    lit = PL.quad_window(luma, scanner.quad, track_scale)
                    # None, not True, when nothing is tracking: --no-track
                    # leaves this caller with no answer to give, and saying
                    # "yes, there is a phone" when it cannot know is what the
                    # LIT_ENOUGH backstop is there to cover. Saying it out loud
                    # is what let the backstop be applied only where it belongs.
                    have_screen = (None if tracker is None
                                   else not tracker.status()['lost'])
                    was_exposure = auto_gain.exposure
                    # The photometric picture, before any preprocessing — the
                    # same window and the same measure the controller steers by,
                    # so the health line's number is the controller's number.
                    health.bright = EX.brightness(lit)
                    ctrls = auto_gain.update(lit, now, has_screen=have_screen)
                    if ctrls:
                        cam.set_controls(ctrls)
                    if 'AnalogueGain' in ctrls:
                        cfg['analogueGain'] = round(auto_gain.gain, 3)
                        health.gain = auto_gain.gain
                    # Daylight through a windscreen can blow the card out with
                    # the gain already on its floor, and then the exposure is
                    # the only thing left. It is given back the moment there is
                    # gain to trade for it, and never goes above what
                    # calibration measured.
                    if auto_gain.exposure != was_exposure:
                        log('exposure %s to %dus: %s'
                            % ('shortened' if auto_gain.exposure < was_exposure
                               else 'given back', auto_gain.exposure,
                               'the card was blown out with the gain already at '
                               'its floor'
                               if auto_gain.exposure < was_exposure
                               else 'traded back against gain, which is the noisy '
                                    'half of the same brightness'))
                    # Deliberately not written to cfg: the borrowed value is a
                    # response to the light right now, and persisting it would
                    # start a night shift on a noon exposure with nothing to
                    # tell it that is wrong. cfg keeps what calibration measured.
                    health.exposure = auto_gain.exposure
                    health.measured_exposure = auto_gain.measured
                    # Out of room: the phone is brighter than this camera can
                    # take at any setting that does not make the screen ripple.
                    # The only remedy left belongs to the driver, so it goes on
                    # the screen they are looking at rather than into a log.
                    if auto_gain.too_bright != health.too_bright:
                        health.too_bright = auto_gain.too_bright
                        log('the phone is brighter than the camera can take — '
                            'turn the screen brightness down a notch'
                            if auto_gain.too_bright
                            else 'the picture is back inside what the camera '
                                 'can take')
                    # ...and the other end of the same complaint, which nothing
                    # used to report at all: everything spent, and the screen
                    # still under target. The picture is dark, the reads get
                    # worse, and the remedy — the phone's own brightness, or a
                    # mount sitting in shadow — is the driver's.
                    if auto_gain.too_dim != health.too_dim:
                        health.too_dim = auto_gain.too_dim
                        log('the phone is dimmer than the camera can make up '
                            'for — turn the screen brightness up a notch'
                            if auto_gain.too_dim
                            else 'there is enough light again')

                # Keep sampling for a short while after a card appears, so a leg
                # missed by one frame can still be picked up by the next.
                if not do_read and now < resample_until and (now - last_resample) > RESAMPLE_EVERY:
                    do_read = True
                    last_resample = now

                # ...and through a dropoff window, on the same beat, for the
                # same reason: a still picture produces no reads at all and the
                # address is on a still picture by definition.
                if not do_read and now < dropoff_until \
                        and (now - last_dropoff_read) > RESAMPLE_EVERY:
                    do_read = True
                    last_dropoff_read = now

                # ...and the slow beat, for as long as there is a card there.
                # See VERIFY_EVERY: a new offer arriving in place of the old one
                # does not move the motion gate, so the only way to know the
                # verdict still belongs to the card on screen is to look.
                if not do_read and card_on_screen and (now - last_verify) > verify_every:
                    do_read = True
                    last_verify = now

                # ...and a trigger that was held back while the reader was busy.
                #
                # Taken here, above the gate below rather than under it, so a
                # deferred read goes through exactly the same checks a fresh one
                # does. Held back a few lines lower, it would be the one kind of
                # read that could skip them.
                if not do_read and read_wanted and not reader.busy:
                    read_wanted, do_read = False, True

                # ...but not while the outline is visibly on the wrong thing.
                #
                # This used to be a feedback loop as well as a waste: a read
                # costs several hundred milliseconds during which nothing else
                # in this loop ran — including the tracker, whose 0.4s recheck
                # is what would fix the corners — so reading a crop taken from
                # corners the detector could already see were wrong postponed
                # the correction that would have made the next read good. A rig
                # reached its verdict after 5.7 seconds and eight reads, seven
                # of them of the rectangle being replaced.
                #
                # The feedback half is gone now that the read runs beside the
                # loop and the tracker keeps its slot through one. What is left
                # is the plain waste, which is reason enough to keep it.
                #
                # A move above overrides this, because the whole point of
                # waiting is to read the moment the corners arrive.
                if do_read and not moved and tracker is not None \
                        and tracker.disputing(now):
                    do_read = False

                # One read at a time, and never a trigger thrown away.
                #
                # Two reads at once would be four tesseract instances on a Pi's
                # four cores, which is the same mistake as an unpinned
                # OMP_THREAD_LIMIT and costs as much. But the motion gate fires
                # exactly once — on the frame where a moving picture settles —
                # so a trigger dropped because the reader was busy is a card
                # that is never read at all. It is remembered instead, and taken
                # on the first frame the reader is free, which is a slightly
                # later and slightly fresher frame of the same card.
                if do_read and reader.busy:
                    read_wanted, do_read = True, False

                # Grab the full frame for a read, or when the live view is due —
                # otherwise nothing is ever seen between offers.
                seen_by, want_view = watching()
                # Half a camera frame of slack, and `>=` rather than `>`.
                #
                # This is checked once per camera frame and nowhere else, so
                # the achievable rates are the camera's rate divided by whole
                # numbers — 30, 15, 10, 7.5 on a binned sensor. A strict
                # "elapsed > period" always lands on the *next* one down,
                # because the frame that arrives exactly on the deadline is a
                # hair early and gets skipped. Simulated against a 30fps
                # sensor: 15 asked for delivered 10.6, and 18, 20, 24 and 25
                # all delivered 15.1 — so the flag was close to meaningless
                # above 15 and the default was a third short of its own label.
                #
                # Taking the frame nearest the deadline instead rounds to the
                # closest achievable rate rather than always down. Nothing
                # downstream objects: measured through the real server, the
                # stream carries 58.7 parts a second.
                due = args.snapshot and snapshot_due(
                    now, last_snapshot,
                    snapshot_interval(want_view, seen_by, phone_view_every), tick)
                if not do_read and not due:
                    continue
                # The sensor frame is copied only when something is going to
                # *read* it. A live view is a 480px thumbnail of a car interior
                # with a box drawn on it, and it was being made by copying
                # twelve megabytes of sensor and throwing 99% of it away — 8ms
                # of pure memory traffic on this machine, and a good deal more
                # on a Pi, at up to fourteen frames a second. The preview stream
                # is already in hand, already the right sort of size, and the
                # only thing lost is colour in a picture nobody reads colour
                # from. The reader still gets the sensor, at full resolution.
                #
                # ...and the phone view is the case that needs it back. It is a
                # picture of the phone's screen made to be read, and the preview
                # stream does not contain the text: warping 640x480 luma up to a
                # 1000px screen invents every pixel of it. So that view buys the
                # sensor frame, and pays for it by composing eight times a
                # second instead of twenty-five — see SNAPSHOT_SCREEN. Only
                # while somebody is actually looking at it; the moment they stop
                # asking, `watching()` says so and this goes back to the
                # preview.
                want_sensor = due and seen_by and want_view == VIEW_SCREEN
                if do_read or want_sensor:
                    # picamera2's "RGB888" hands back B, G, R ordered arrays,
                    # which is exactly what OpenCV expects. The name is the odd
                    # one out.
                    frame, preview_scale = request.make_array('main'), None
                else:
                    # Copied, because `luma` is a view onto the request's own
                    # buffer and the request is released a few lines below —
                    # after which that memory goes back to the camera to be
                    # filled again. 300KB, against the 12MB this branch exists
                    # to avoid.
                    frame, preview_scale = luma.copy(), track_scale
            finally:
                request.release()

            # Before the partner capture below, not after it. Waiting for the
            # next sensor frame and copying twelve megabytes of it is the
            # longest thing left on this loop now that the reading has moved
            # off — measured, it was the whole difference between a worst-case
            # 61ms gap in the live view and a 113ms one. The picture costs the
            # same either way; it just arrives at the start of that stretch
            # instead of at the end of it.
            if args.snapshot and (due or do_read):
                write_snapshot(frame, cfg, args.snapshot, quad=scanner.quad,
                               roi=scanner.crop_box, card=previous_card,
                               scale=preview_scale,
                               # The phone view only when somebody is asking for
                               # it. A read composes a snapshot too, and one
                               # written on the reader's schedule to a page
                               # nobody has open should not be the expensive
                               # kind.
                               view=want_view if seen_by else VIEW_SCENE)
                # The frame's own clock, not the clock after composing it.
                # Composing costs a few milliseconds and charging them to the
                # next interval makes every period that much longer than asked.
                last_snapshot = now

            if not do_read:
                continue

            # A verdict needs two reads that agree, so when one is due, take
            # the frame after it as well and read both at once. The sensor is
            # already producing them 33ms apart, and two reads together cost
            # 56% of two in a row — so the confirmation stops costing a second
            # of wall clock while an offer is timing out. It is the same
            # evidence, gathered at the same time instead of one after the
            # other. --no-parallel falls back to one at a time.
            partner = None
            if pair_reads:
                partner_request = cam.capture_request()
                try:
                    partner = partner_request.make_array('main')
                finally:
                    partner_request.release()

            frames += 1
            # Handed over rather than done here. The geometry goes with the
            # frames — see PL.Geometry — because by the time the read finishes
            # the tracker may well have moved the corners, and a frame warped
            # against corners measured after it was captured lands the crop
            # somewhere the card is not.
            reader.submit([frame] if partner is None else [frame, partner],
                          time.time(), scanner.geometry())
            # Before the read, not after it. The dashboard has nothing else to
            # go on for the second and a half this takes — see emit_reading.
            if args.json:
                emit_reading()
            if not reader.threaded and collect():
                break

    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        reader.close()
        cam.stop()
        cam.close()
        if args.display:
            cv2.destroyAllWindows()


# BGR. 'doubt' is deliberately none of the other three and not a near-miss of
# any of them: at arm's length the colour is read before the word is.
COLOURS = {'go': (100, 201, 23), 'warn': (36, 165, 245), 'no': (75, 50, 240),
           'doubt': (92, 45, 58), 'empty': (36, 27, 20)}
LABELS = {'go': 'ACCEPT', 'warn': 'CLOSE', 'no': 'PASS'}
DOUBT_LABELS = {'pay': 'CHECK PAY', 'time': 'CHECK TIME', 'speed': 'CHECK MILES',
                # Both figures can be sane alone and impossible together, so
                # this one names the pair rather than picking a side — telling
                # a driver to check the payout sends them to the wrong half of
                # the card when the time is what was misread. Added with the
                # reason itself; without it this panel fell back to READ AGAIN
                # while the other two screens named it.
                'rate': 'CHECK PAY & TIME'}


def render_panel(rate, parsed, size=(800, 480), whole=True):
    """Big, flat, readable at a glance and at arm's length.

    `whole` says the whole journey was in view. A reading without it is a
    FRAGMENT, and a fragment always flatters the offer — the pickup leg of a
    two-leg card on its own is a shorter, better-paying job than the card
    describes. live.html has qualified its verdict with a "?" for exactly this
    since it was written; this panel, the one actually bolted to the dashboard,
    did not, so the same reading the web page hedged showed here as a flat
    green ACCEPT.

    It arrives as an argument rather than being worked out here, because
    `is_whole` has a deadline branch: a delivery card is legitimately whole with
    no legs at all, and a panel that restated the test from the legs would
    qualify every delivery card the rig reads. The loop already has the value.

    Defaults True so that a caller which does not know cannot accidentally
    cast doubt on a reading that never earned it.
    """
    panel = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    # `.get`, not `[...]`: this is the scan loop, and a state this function has
    # not been taught about must cost a dull panel rather than a KeyError that
    # takes the whole rig down mid-shift. Adding 'doubt' to the parser did
    # exactly that here, twice, in a file the parser's own tests never touch.
    panel[:] = COLOURS.get(rate['state'] if rate['ready'] else 'empty',
                           COLOURS['empty'])
    if not rate['ready']:
        cv2.putText(panel, 'waiting', (40, 260), cv2.FONT_HERSHEY_SIMPLEX, 2.2, (200, 200, 200), 4)
        return panel

    # A reading that cannot be true gets the figure to look at and the card's
    # own numbers, and not the rate — $3548/hr at this size is the most
    # convincing thing on the rig and the most wrong.
    if rate['state'] == 'doubt':
        cv2.putText(panel, DOUBT_LABELS.get(rate.get('doubt'), 'READ AGAIN'),
                    (40, 150), cv2.FONT_HERSHEY_SIMPLEX, 2.6, (255, 255, 255), 6)
        cv2.putText(panel, '$%.2f  %s min  %s mi'
                    % (parsed['pay'], parsed['minutes'], parsed['miles']),
                    (40, 300), cv2.FONT_HERSHEY_SIMPLEX, 1.8, (255, 255, 255), 4)
        cv2.putText(panel, 'that is not what a real offer looks like',
                    (40, 380), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (210, 210, 210), 2)
        return panel

    # The verdict, and a question mark when it is drawn from a fragment. Same
    # mark and same meaning as the web page, so a driver reading one screen and
    # then the other is not learning two vocabularies.
    cv2.putText(panel, LABELS.get(rate['state'], '') + ('' if whole else ' ?'),
                (40, 90), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (255, 255, 255), 5)
    cv2.putText(panel, '$%.0f/hr' % rate['perHour'], (36, 300),
                cv2.FONT_HERSHEY_SIMPLEX, 6.0, (255, 255, 255), 12)
    # ...and the same offer before running costs, where that is a different
    # number. The headline is net and says "/hr" either way, so this panel and
    # the web one showed figures that are only sometimes the same thing. Only
    # where they differ, because a number repeated beside itself is noise next
    # to the one figure the panel exists for.
    gross = rate.get('grossPerHour')
    if gross is not None and round(gross) != round(rate['perHour']):
        cv2.putText(panel, '$%.0f/hr raw' % gross, (40, 350),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1, (210, 210, 210), 2)
    cv2.putText(panel, '$%.2f  %s min  %s mi' % (parsed['pay'], parsed['minutes'], parsed['miles']),
                (40, 400), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 3)
    return panel


if __name__ == '__main__':
    main()
