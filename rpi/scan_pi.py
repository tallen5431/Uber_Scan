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
import copy
import json
import math
import os
import re
import queue
import shutil
import subprocess
import sys
import threading
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cropbox as CX
import exposure as EX
import gps as GPS
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
# Measured on a development machine against a synthetic rig frame with sensor
# noise on it (testcards' UberX card, ±12 levels): write_snapshot's phone view
# is 5.2 to 5.7ms with OpenCV on its four threads — warp 2.2ms, JPEG 2.0ms — and
# 9.1 to 9.5ms on one (warp 5.5ms, JPEG 2.5ms), which is what it gets when the
# reader has the other cores. The 12MB sensor copy is 1.0ms on top here, and it
# is the one thing here that is much dearer on a Pi than on this machine; none
# of it has been timed on the Pi. Keeping the warp's transform and output
# buffer between frames was tried and measured no faster (within the noise of
# four runs either way), and every cheaper warp tried (remap on kept maps, 27%
# faster on one thread) moves pixels, so the picture is the warp the reader
# uses, at the cost above.
#
# It does not need 25 a second either way. The scene view is watched for motion
# — is the phone still in the box, has the mount slipped — and a slide show
# there reads as a fault. This one is watched to read a card that is not moving
# and, increasingly, to see where a mouse pointer is: the driver works the
# phone with a bluetooth mouse and this picture is where they watch the cursor.
# A cursor at ten frames a second feels attached to the hand; below that it
# does not.
#
# Fifteen, then, rather than the first cautious ten. At the costs above that is
# 9 to 16% of one core here, compose and copy, while somebody watches; on a Pi
# it is more, by an amount not measured.
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
# A read costs about 1.8 seconds of a Pi 4, of which most is inside tesseract,
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

# What a read costs. TWO numbers, because two different questions were being
# answered by one of them.
#
# There was a single `READ_SECONDS = 0.75`, derived rather than measured: "the
# owner's own shift recorded a median of 1517ms before the engine stopped being
# thrown away per read, and that change measured 2.12x on a development machine:
# 1517 / 2.12 is about 715ms". A development machine is not a Pi 4 that is also
# drawing a dashboard, and the speedup did not arrive on the rig.
#
# Measured on 272 real offers out of the owner's own journal:
#
#     min 390   p25 1405   median 1846   p75 2636   p90 3657   p99 4812   max 5915
#
# 99.3% of real reads are slower than the 750ms that was assumed. So every piece
# of arithmetic hanging off it was out, and out in the optimistic direction.
#
# The two questions are not the same question:
#
#   TYPICAL is for duty cycle — what share of the verify beat is spent reading a
#   card that is not changing. The median is the right statistic: it says what
#   the rig usually does.
#
#   SLOW is for worst-case gaps — how long the driving page may hear nothing
#   from a HEALTHY rig before it is entitled to dim the verdict. A median is the
#   wrong statistic for a bound; one read in two is slower than it, and dimming
#   a good verdict is the failure being guarded against. The p90 is used, and
#   the max is written down beside it so the margin is visible.
#
# Rounded to a tenth. Nothing here is fine enough to care past that.
READ_SECONDS = 1.85           # median of the owner's own 272
READ_SECONDS_SLOW = 3.7       # p90; the worst measured was 5.9
# How long one read may be in flight before the rig treats itself as stuck.
# A read that never returns left the loop alive, beating, silent and never
# reading again: every card's trigger was deferred to `read_wanted` and never
# taken, no health line was printed, and server.js kept hearing `alive` so
# it never restarted anything. Past this the heartbeat stops, which is what
# the thirty-second silence watchdog on the other side is for.
READ_STUCK_S = 60.0

# ...and the ceiling, which is how long the driver can be looking at a verdict
# that belongs to the card BEFORE the one on the screen.
#
# That is the whole of what this number buys, and it is worth being exact about
# why. A replacement offer is the same layout, the same colours and different
# digits, so it moves the motion gate by 0.33 against a threshold of 6.0 —
# indistinguishable from nothing happening. Looking on a timer is the only
# thing that notices it, and this ceiling is how long that takes at worst.
#
# THE DUTY CYCLE IS NO LONGER THE ARGUMENT, AND USED TO BE.
#
# This paragraph used to read: "It was 12.0, chosen when a read was ~1.4s:
# 1.4/12 is a 12% duty... the read then halved, so the same argument now lands
# at 6.0 — 0.75/6.0 is the same 12% for half the wait."
#
# The 0.75 was never measured. It was extrapolated from a speed-up seen on a
# development machine, and READ_SECONDS above now carries the owner's own 272
# reads instead: a median of 1.85s. So the real duty at this ceiling is 31%,
# not 12%, and it always was — the number was wrong, not the rig.
#
# 6.0 stays, on the other argument. A third of a backed-off beat spent
# re-reading a card that is not changing is a real cost on a Pi that is also
# drawing a dashboard, and raising the ceiling is the lever — but every second
# added is a second a driver can spend reading a verdict about a card that is
# gone, and that is money. The trade belongs to whoever drives the rig.
#
# What is NOT allowed is the old sentence: it told a future reader the duty was
# 12%, which is an invitation to restore 12.0 on arithmetic that was never
# true. See the duty check in rpi/test_scan_pi.py, which states the real figure
# and is wide enough to notice it moving.
VERIFY_MAX = 6.0


class Reader:
    """The OCR, moved off the loop that holds the camera.

    A read is about 1.8 seconds on a Pi 4, most of it inside tesseract, and for
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
        # When the read in flight was submitted, on the MONOTONIC clock; None
        # when none is. It is only ever subtracted from — "stuck for how long",
        # "begun inside the ⌖ window" — and a wall clock NTP steps forward an
        # hour turned a read in flight into one an hour old, so the loop wrote
        # a restart row for a reader that was working (rpi/test_loop.py, "a
        # wall clock stepped an hour").
        self.since = None
        if threaded:
            self._thread = threading.Thread(target=self._serve, name='reader',
                                            daemon=True)
            self._thread.start()

    def submit(self, frames, now, geom):
        """Hand over frames to read. Call only when not busy.

        `now` comes back on the finished read as `at`, and it is the only clock
        the far end can honestly use. A read is over a second on a Pi, so
        anything decided by `time.time()` after it lands is asking about a
        moment more than a second later than the picture it is judging.

        ...and `since` comes back on it as `began`: the same moment on the
        monotonic clock, for the intervals digest() times off it. `at` is a
        stamp for the wire and the journal; `began` is never written anywhere.
        """
        self.busy = True
        self.since = time.monotonic()
        if not self.threaded:
            self._done.put(self._job(frames, now, geom, self.since))
            return
        self._work.put((frames, now, geom, self.since))

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
        self.since = None
        if done['error'] is None:
            # On the loop's thread, deliberately. See Scanner.settle.
            done['outs'] = self.scanner.settle(done['outs'], done['geom'])
        return done

    def _job(self, frames, now, geom, began=None):
        try:
            return {'outs': self.scanner.look_many(frames, now, geom=geom),
                    'geom': geom, 'frames': frames, 'at': now, 'began': began,
                    'error': None}
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
            return {'outs': None, 'geom': geom, 'frames': frames, 'at': now,
                    'began': began, 'error': e}

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



def read_the_money(batch):
    """Which frame of one read to publish: the last that saw a payout.

    A read hands back two frames 33ms apart. accumulate.add short-circuits on a
    payout-free frame — it hands the parse straight back with mergedFrom 0 —
    which the destination branch in digest() deliberately relies on. So
    publishing the later frame whatever it said meant that when the partner
    frame was the one that lost its payout to glare or to the crop edge, the
    merge was bypassed for the whole read.

    Measured: frame one merges to a complete reading, 23.0 min and 8.4 mi on a
    $16.05 card; frame two is the same card with the payout gone and publishes
    complete False, mergedFrom 0 and a rate that is not ready. The panel paints
    grey WAITING over a verdict the rig had worked out 33 milliseconds earlier.

    When NO frame in the batch has a payout the last one is chosen, exactly as
    before: a genuinely payout-free screen — a navigation app, a dropoff
    address — still has to digest as itself.
    """
    chosen = len(batch) - 1
    for i in range(len(batch) - 1, -1, -1):
        money = ((batch[i] or {}).get('parsed') or {}).get('pay')
        if isinstance(money, (int, float)) and not isinstance(money, bool) \
                and money > 0:
            return i
    return chosen
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


def order_held(now=None):
    """Whether the web side says an order is in the car right now.

    server.js writes `.holding.json` holding `until`, the moment its own
    holding() stops answering yes (holdEnds there), whenever the order in the
    car changes, and removes it when there is none. Judged against `until`
    here rather than by the file's presence, so a server that died mid-delivery
    does not leave the scanner believing in an order for the rest of the shift.
    Anything unreadable is no order: this decides only whether the rig reads
    the planner without a press, and ⌖ reads it either way.
    """
    return held_signature(now) is not None


def held_signature(now=None):
    """Which order the web side says is in the car right now, or None.

    The same note order_held reads, by the same rule — judged against
    `until`, anything unreadable is no order — answering with the order's
    name as server.js gives it (`holds`, holdIdOf there). A note from a server
    older than that field names no order and answers '' while it is in force:
    still an order, for order_held, and never a change, for the loop.

    `holds` is a LIST of names since server.js carries orders as a list, and
    one name from a server before that: either way the answer is one string,
    the names joined in the server's order, so a second order taken — or one
    of two put down — is a change of signature like any other.

    What it is for: `dropoff_said` in main() is forgotten when this changes,
    so an address volunteered for — and refused for — the order before is
    offered again for this one.
    """
    now = time.time() if now is None else now
    for candidate in HO.candidates(HO.HOLDING):
        try:
            with open(candidate, encoding='utf-8') as fh:
                note = json.load(fh)
            until = note.get('until')
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(until, (int, float)) and now * 1000.0 < until:
            holds = note.get('holds')
            if isinstance(holds, list):
                return ' '.join(h for h in holds if isinstance(h, str))
            return holds if isinstance(holds, str) else ''
    return None


def dropoff_requested(now=None):
    """Seconds left of a press's window, once per press; None when there is none.

    Both places are looked in and both are cleared — see handoff.clear for why:
    a web server one `git pull` behind this process writes to the other one,
    and a request left lying in either would be acted on whenever the scanner
    next restarted. Answers with how much of the window is left rather than
    True, for the reason at the foot of this.

    Separate from the reading itself: this only says the driver asked. What it
    buys is a window — see DROPOFF_WINDOW — because the phone is showing a
    navigation screen that is not going to move, and the motion gate reads a
    still picture as nothing happening.

    ...AND ONLY WHILE THE PRESS IS STILL ABOUT THE SCREEN IN FRONT OF IT.

    The request was a bare file with no age, and this asked only whether it
    existed. /api/dropoff writes it and answers ok without asking whether a
    scanner is listening, and handoff files live in /dev/shm, which a scanner
    restart does not clear. So a press made while this process was down — the
    child between restarts on server.js's backoff, a wedge-kill, the systemd
    unit stopped — sat on disk until the next loop pass and was honoured then,
    against whatever was on the phone by then. An address read that way is
    filed as ASKED: onto the order in the car if there is one, else onto the
    card on the slot, overwriting a destination the card stated for itself,
    and in the journal's fold a press outranks every sighting. That is a
    destination nobody asked about, written into a file that cannot be
    corrected, from a press the driver had long since given up on.

    A press whose own window would already have shut — DROPOFF_WINDOW old or
    more — cannot still be about the screen the driver was looking
    at, so it is cleared and not acted on, and the log says so. So is one
    stamped AHEAD of the clock, which is a clock that stepped (see
    `handoff.age`), not a fresh press. Refusing costs the driver one more tap;
    honouring costs a wrong address on the record.

    Nothing is sent to the panel. live.html stops saying "reading…" 13 seconds
    after the server answers the press, whatever happens, so a stale press is
    found after the panel has stopped waiting for it, and a "not read"
    arriving then is the late contradiction the ⌖ button's handling was built
    to avoid.
    """
    # No `except OSError` round this, which there was and nothing could reach:
    # HO.age catches the one call in it that can fail, the stat of each copy,
    # and the rest — the environment, isdir and access, which answer False
    # rather than raise, and the clock — cannot.
    pressed = HO.age(HO.DROPOFF, now)
    if pressed is None:
        return None
    HO.clear(HO.DROPOFF)
    if pressed < 0:
        log('ignored a destination request stamped %ds ahead of the clock: the '
            'clock has stepped since, so how old the press is cannot be told'
            % int(-pressed))
        return None
    if pressed >= DROPOFF_WINDOW:
        log('ignored a destination request from %ds ago: older than its '
            '%d-second window, so it is not about the screen on the phone now'
            % (int(pressed), int(DROPOFF_WINDOW)))
        return None
    # ...and the window it opens is the one THIS age was judged against.
    #
    # This returned True, and the loop then opened a fresh window from the
    # moment it noticed: `dropoff_until = now + DROPOFF_WINDOW`. Two answers to
    # "is this press still open", with two anchors. A press 11.5s old passed the
    # test above as inside its window and was then read for twelve more seconds
    # — to 23.5s after the press, plus a read in flight measured at up to 5.9s —
    # and whatever turned up was filed as ASKED, well after live.html had
    # stopped saying "reading…" 13s after the press was answered. Returning what
    # is left makes the window end at press + DROPOFF_WINDOW whichever pass
    # notices it, so the test and the window are one predicate. Always above
    # zero, since an age of exactly the window is refused above, so a caller
    # testing the answer for truth cannot lose a press to a 0.0.
    return DROPOFF_WINDOW - pressed


# How long to keep reading after the button. The driver presses it, then has to
# get the destination onto the screen — a tap or two, or just waiting for the
# app to settle after the accept. One read at the instant of the press would
# photograph whatever was there before they did any of that.
#
# Twelve seconds is the same figure the offer window uses and for the same
# reason: long enough to cover a person doing one thing on a phone, short enough
# that the rig is not still hunting for an address when the next offer arrives.
DROPOFF_WINDOW = 12.0
# At most one whole-screen read every this many seconds that nobody pressed for,
# WHATEVER asked for it — a planner, a navigation screen, a Dropoff label (see
# auto_read_for). One clock for all of them, `screen_auto_at` in main(): the
# owner's figure is "at most one read every ~10 s", and a driver who flicks
# between the planner and the map is still one phone in front of one Pi. A
# whole-screen read is a second or more of the Pi's attention (1.8s median on
# the rig), so this keeps the screen after the accept from crowding out the
# card box while it sits on the phone for a whole delivery.
SCREEN_AUTO_EVERY = 10.0
# ...and this many while the Pi is hot (HeatGuard): the same reads, at most a
# third as often. At the 1.8s median that caps them at 18% of the Pi's time
# through a delivery, and at 6% while hot — arithmetic on that median, for a
# screen that asks at every chance, not a measurement of the rig. These are the
# only reads it touches: an offer, a ⌖ press and a 📷 Snap are read when they
# always were.
SCREEN_AUTO_HOT = 30.0


def screen_auto_every(hot):
    """The least time between two whole-screen reads nobody pressed for: the
    one interval digest() asks before it wants one, which the heat guard's
    state chooses between."""
    return SCREEN_AUTO_HOT if hot else SCREEN_AUTO_EVERY


def auto_read_for(text, planner=None):
    """What in a card-box read asks for an unpressed whole-screen read while an
    order is held: 'planner', 'nav', 'label', or None for nothing.

      planner  the planner's stop grammar (`planner`, find_planner's headed
               stops) or its furniture: the card box on the rig is the bottom
               half of the screen and has never caught the planner's title.
      nav      Uber's navigation (OP.screen_type 'uber.nav'). On the 12 Oct
               shift 179 of the 1,237 payout-free card-box reads were this.
               The box holds the bottom sheet, which reads "Deliver to <name>"
               collapsed, or opened the name, street, town and "Dropoff type"
               that OP.sheet_dropoff reads; the whole-screen read is where the
               assembler takes either from.
      label    any other screen whose address sits under a "Deliver to" or
               "Dropoff" label in its own block (OP.address_under_dropoff):
               DoorDash's "Dropoff <address> 12 min Start" is typed 'unknown',
               and is the shape that rule was built on.

    Only ASKS. Not uber.pickupNav as a kind of its own: a store's navigation
    asks only if it shows one of the three, and what the read then gives is the
    assembler's, which files nothing off a pickup screen or from under a Pickup
    label (assemble.js, navCandidate)."""
    if planner is not None or OP.planner_furniture(text):
        return 'planner'
    if OP.screen_type(text)['screen'] == 'uber.nav':
        return 'nav'
    if OP.address_under_dropoff(text):
        return 'label'
    return None


def settings_requested():
    """A cost per mile the driver typed on a screen, once; None when there is none.

    Written by POST /api/settings, which answers only for a machine that runs a
    scanner. Taken from both places for the reason handoff.clear gives, and
    never fatal.

    ONE KEY. The block this lands in is not a list of preferences: `keepPlaces`
    decides whether addresses are written into the append-only journal at all,
    and `pad` and `secondsPerItem` move `billedMinutes` and so every rate the
    rig prints AND STORES. The route refuses a body naming any of them; this
    reads `costPerMile` out of whatever is in the file and nothing else, so a
    request written some other way — by hand, by a server a `git pull` behind —
    cannot switch off address recording or shift the money on every row that
    follows.

    Not aged, unlike a dropoff press. That press is about the screen in front of
    the camera and goes stale with it; this is about the car, and a figure typed
    while the scanner was between restarts is still the figure the driver meant
    when it comes back.

    A finite number of zero or more, as the route insists. A bool is refused
    although Python calls it a number: `true` is not a price.

    TAKEN BY RENAME, NOT READ AND THEN CLEARED. This used to read the file and
    then HO.clear() every place it might be. A POST is a rename onto the same
    name, so one landing between the read and the clear was deleted unread:
    the route had answered ok, the keypad said the rig had it, and the loop
    went on pricing at the figure before. Renaming the request to a name of
    this process's own takes exactly the file that was there; one renamed in
    after that is a new file under the old name, left for the next pass.
    Both places are still emptied, for the reason handoff.clear gives.
    """
    raw = None
    for candidate in HO.candidates(HO.SETTINGS):
        mine = '%s.taken-%d' % (candidate, os.getpid())
        try:
            os.rename(candidate, mine)
        except OSError:
            continue
        try:
            if raw is None:
                with open(mine) as fh:
                    raw = fh.read()
        except (IOError, OSError) as e:
            log('could not read a settings request (%s): the cost per mile in '
                'use is unchanged' % e)
        try:
            os.remove(mine)
        except OSError:
            pass
    if raw is None:
        return None
    try:
        cost = json.loads(raw).get('costPerMile')
    except (ValueError, AttributeError):
        cost = None
    if (isinstance(cost, bool) or not isinstance(cost, (int, float))
            or not math.isfinite(cost) or cost < 0):
        log('ignored a settings request with no usable cost per mile in it '
            '(%r): the cost per mile in use is unchanged' % raw[:80])
        return None
    return float(cost)


def emit_settings(settings):
    """The cost per mile this scanner is pricing with, on its own line.

    Said once when the loop starts and again whenever the driver changes it,
    so GET /api/settings answers with what the running scanner is USING — not
    with what a file says, which a hand edit over SSH can make disagree with the
    process until the next restart. The value rate() will actually take, after
    the same fallback it applies, so a figure it cannot read is reported as the
    figure it prices with instead.

    Like the heartbeat, no `ready`, so it cannot stand in for a verdict.
    """
    print(json.dumps({'settings': {'costPerMile': OP.setting(
        (settings or {}).get('costPerMile'), OP.DEFAULT_SETTINGS['costPerMile'])}}),
        flush=True)


# How old a 📷 Snap request may be and still be answered.
#
# server.js waits SNAP_READER_MS (4s) for reader.json and then seals the folder
# with "the scanner did not answer". An answer written after that would sit in
# a folder whose snap.json says it is not there — two accounts of one press. So
# the window closes a second earlier than the wait, which leaves the answer
# itself and the server's tenth-of-a-second poll inside the margin. Measured on
# the development box, not the Pi: answering with the test ride card's real
# crop (1134x881, a 33kB reader.jpg and 3kB of reader.json) took 3.0ms median
# and 5.1ms at worst over 50. rpi/test_server.py reads both figures and holds
# them apart.
SNAP_ANSWER_WINDOW = 3.0


def snap_requested(now=None):
    """The snap folder a 📷 press asked about, once per press; None when none.

    The same age guard dropoff_requested applies and for the same reason: the
    request lives in /dev/shm, which a scanner restart does not clear, so a
    press made while this process was down — or aiming, or calibrating, which
    is still the server's child and not yet this loop — would be found later
    and answered into a folder the server sealed long ago. One older than its
    window, or stamped ahead of a clock that has since stepped back, is cleared
    and logged and not answered.

    And a folder that is not there is not made. The server makes the folder,
    and one that has gone was removed by a press that kept nothing; writing
    into a fresh one of that name would be a snap with no record of its own.
    """
    # Unguarded: HO.age catches the stat that can fail, and nothing else in
    # it raises. See dropoff_requested.
    pressed = HO.age(HO.SNAP, now)
    if pressed is None:
        return None
    raw = None
    for candidate in HO.candidates(HO.SNAP):
        try:
            with open(candidate) as fh:
                raw = fh.read()
            break
        except (IOError, OSError):
            continue
    HO.clear(HO.SNAP)
    if pressed < 0:
        log('ignored a snap request stamped %ds ahead of the clock: the clock '
            'has stepped since, so how old the press is cannot be told'
            % int(-pressed))
        return None
    if pressed >= SNAP_ANSWER_WINDOW:
        log('ignored a snap request from %ds ago: older than its %gs window, '
            'so an answer could land after the server has said there was none'
            % (int(pressed), SNAP_ANSWER_WINDOW))
        return None
    try:
        folder = json.loads(raw or '').get('folder')
    except (ValueError, AttributeError):
        folder = None
    if not isinstance(folder, str) or not os.path.isdir(folder):
        log('ignored a snap request naming no folder that is there (%r)'
            % (raw or '')[:120])
        return None
    return folder


def age_ms(stamp, now):
    """How long before `now` a stamp off this process's clock was, in ms.

    None when that cannot be told: either was read before the network set the
    clock (see CLOCK_BELIEVABLE_AFTER), or the stamp is ahead of now, which is
    the clock stepping back between the two — not a reading from the future.
    """
    if stamp < CLOCK_BELIEVABLE_AFTER or now < CLOCK_BELIEVABLE_AFTER or stamp > now:
        return None
    return int(round((now - stamp) * 1000))


def beat_extra(beat):
    """The rest of a kept beat as the wire carried it: `gps` (is the fix fresh,
    and the fix the maps drew), the Pi's fields, spread the way emit_alive
    spreads them, and `heatGuard`.

    `gps` here is what the panel was shown, as of that beat; reader.json's own
    `gps` beside it is the link to gpsd or the phone's app and the fix as it
    is at the press. Two different moments, both worth having in a snap.
    """
    extra = beat[2] if len(beat) > 2 else {}
    out = {'gps': extra.get('gps')}
    out.update(extra.get('pi') or {})
    out['heatGuard'] = bool(extra.get('heat_guard'))
    return out


def reader_record(last, now, offer_log=None, counters=None, beat=None,
                  phone=None):
    """What reader.json says: the reader's own account of the moment.

    `last` is the read the loop kept (see `last_read` in main), or None before
    the first one has come back. Nothing here reads the camera: a snap is
    about what the panel was showing, and a fresh read would be a picture of
    something else.

    `offer` is the card on record and whether it reached the journal, or a
    sentence when there is no journal to have one. server.js holds its id
    against the offer /api/status had at the press, and says so when both name
    a card and not the same one: a card landed between the press and this
    answer, or this process restarted onto another, and the crop here is not
    the read behind status.json's offer. See readerAnswered there.

    `heartbeat` is the last beat as the wire carried it, and how long ago —
    not the conditions worked out again now, which could disagree with what
    the panel was told. `gps` is the phone's own word and its fix, when the
    rig was asked to listen to one.
    """
    record = {'v': 1, 'answeredAt': int(now * 1000)}
    if last is None:
        record['read'] = None
        record['noCrop'] = 'no read yet'
    else:
        record['read'] = {'at': int(last['at'] * 1000),
                          'ageMs': age_ms(last['at'], now),
                          # A ⌖ read of the whole screen box, not the card crop.
                          'wholeScreen': last['wholeScreen'],
                          'crop': last['crop'],
                          # ...and whether that crop is the box the driver
                          # drew or a card found above it — this read's own.
                          'cropFrom': last.get('cropFrom', 'drawn'),
                          # ...and where the payout in `parsed` came from,
                          # which a merge can make a found card's though this
                          # read was the box: what the panel's line says as
                          # cropFrom. See payout_from.
                          'payFrom': last.get('payFrom', 'drawn'),
                          'text': last['text'],
                          'parsed': last['parsed'],
                          'rate': last['rate']}
    record['episode'] = (last['parsed'].get('episode')
                         if last is not None else None)
    record['offer'] = ('not kept: --no-journal' if offer_log is None
                       else {'id': offer_log.id,
                             'landed': offer_log.id is not None
                             and offer_log.landed_id == offer_log.id})
    record['health'] = counters
    record['heartbeat'] = ('none sent yet' if beat is None
                           else dict(alive_flags(**beat[1]),
                                     **beat_extra(beat),
                                     ageMs=age_ms(beat[0], now)))
    record['gps'] = ('gps off' if phone is None
                     else {'state': phone.state(), 'fix': phone.fix()})
    return record


# --- 📷 Snap, the richer kind (EXPERIMENTAL; the owner, 31 Oct 2026: "Yes add
# all of them, fast track to experimental") ----------------------------------
#
# Two more files only this process has, beside reader.json: frame.jpg, the
# newest full-resolution sensor frame the loop holds, and reads.json, the last
# SNAP_READS_KEEP reads. Local to the rig like every file in a snap (snaps/ is
# in .gitignore, served only through server.js's /api/snaps, never synced),
# and they leave it only when the owner uploads that snap.
#
# frame.jpg: JPEG SNAP_FRAME_QUALITY, scaled down only past SNAP_FRAME_MAX_W,
# and encoded again lower while it is over SNAP_FRAME_MAX_BYTES. Encoding a
# full sensor frame is tens of milliseconds on a Pi, so with a reader thread it
# is done on a thread of its own (answer_snap's `threaded`) and the camera loop
# never waits for it; past SNAP_FRAME_CAP_S it is dropped and said, and
# reader.json still goes.
SNAP_READS_KEEP = 10
SNAP_READ_TEXT_MAX = 2048
SNAP_FRAME_MAX_W = 2000
SNAP_FRAME_QUALITY = 85
SNAP_FRAME_MAX_BYTES = 900 * 1024
SNAP_FRAME_CAP_S = 2.0


class ReadLog(object):
    """The last SNAP_READS_KEEP reads, for a snap's reads.json. Memory only.

    One entry per read the loop collected: when, what kind (card box, a ⌖
    press, a whole-screen read nobody pressed, DoorDash's map label), the
    screen type, the crop's source, how long it took, the text cut to
    SNAP_READ_TEXT_MAX, whether it was skipped as too dark, and the parse's
    pay, minutes, miles, pickup and dropoff. Nothing here is read back by
    anything but a snap."""

    def __init__(self, keep=SNAP_READS_KEEP):
        self.keep = keep
        self.items = []

    def add(self, at, kind, out=None, parsed=None, ms=None, skipped_dark=False,
            text=None, crop_from=None):
        out = out or {}
        parsed = parsed if isinstance(parsed, dict) else (out.get('parsed') or {})
        text = text if text is not None else (out.get('text') or '')
        if ms is None:
            got = out.get('ms')
            ms = got.get('total') if isinstance(got, dict) else got
        try:
            screen = OP.screen_type(text or '')['screen']
        except Exception:                           # noqa: BLE001 — never fatal
            screen = None
        entry = {'at': int(at * 1000) if at else None, 'kind': kind,
                 'screen': screen,
                 'cropFrom': crop_from or out.get('cropFrom') or None,
                 'ms': int(round(ms)) if isinstance(ms, (int, float)) else None,
                 'skippedDark': bool(skipped_dark),
                 'text': (text or '')[:SNAP_READ_TEXT_MAX],
                 'textCut': len(text or '') > SNAP_READ_TEXT_MAX}
        for k in ('pay', 'minutes', 'miles', 'pickup', 'dropoff'):
            entry[k] = parsed.get(k)
        self.items.append(entry)
        del self.items[:-self.keep]
        return entry

    def snapshot(self):
        return [dict(e) for e in self.items]


def snap_frame_jpeg(frame, max_w=SNAP_FRAME_MAX_W, quality=SNAP_FRAME_QUALITY,
                    max_bytes=SNAP_FRAME_MAX_BYTES):
    """(bytes, info) for frame.jpg, or (None, why). Never raises."""
    try:
        if frame is None or not hasattr(frame, 'shape') or frame.size == 0:
            return None, 'no frame held yet'
        h, w = frame.shape[:2]
        img = frame
        if w > max_w:
            img = cv2.resize(frame, (max_w, max(1, int(round(h * max_w / float(w))))),
                             interpolation=cv2.INTER_AREA)
        q = int(quality)
        while True:
            ok, buf = cv2.imencode('.jpg', img, [int(cv2.IMWRITE_JPEG_QUALITY), q])
            if not ok:
                return None, 'jpeg encoding failed'
            if len(buf) <= max_bytes or q <= 40:
                break
            q -= 15
        if len(buf) > max_bytes:
            return None, 'frame.jpg would be %d bytes, over its %d' % (len(buf), max_bytes)
        return buf.tobytes(), {'width': int(img.shape[1]), 'height': int(img.shape[0]),
                               'sourceWidth': int(w), 'sourceHeight': int(h),
                               'quality': q, 'bytes': int(len(buf))}
    except Exception as e:                          # noqa: BLE001 — never fatal
        return None, 'could not encode frame.jpg: %s' % e


def _write_bytes(where, data):
    with open(where + '.part', 'wb') as fh:
        fh.write(data)
    os.replace(where + '.part', where)


def answer_snap(folder, last, record, band=None, reads=None, frame=None,
                threaded=False, clock=time.monotonic):
    """reader.jpg, then reader.json, into the folder a press named. Never fatal.

    ...and, the richer snap (EXPERIMENTAL), `reads` (ReadLog.snapshot()) as
    reads.json and `frame` ({'frame', 'at', 'source'}: the newest sensor frame
    the loop holds) as frame.jpg. reads.json is written here; frame.jpg, with a
    thread, on its own thread, which then writes reader.json — so reader.json
    is still the last file and still means "complete". A piece that cannot be
    written is said in reader.json (`reads`, `frame`) and the rest goes on.
    With `threaded` the answer is True once the thread is started.
    """
    if reads is not None:
        try:
            _write_bytes(os.path.join(folder, 'reads.json'),
                         json.dumps({'v': 1, 'keep': SNAP_READS_KEEP, 'reads': reads},
                                    indent=1).encode('utf-8'))
            record['reads'] = {'file': 'reads.json', 'n': len(reads)}
        except (IOError, OSError, TypeError, ValueError) as e:
            record['reads'] = 'could not write reads.json: %s' % e
            _snap_extra_said('reads.json', e)
    if frame is None:
        return _answer_snap(folder, last, record, band)
    if not threaded:
        record['frame'] = _snap_frame(folder, frame, clock)
        return _answer_snap(folder, last, record, band)

    def job():
        try:
            record['frame'] = _snap_frame(folder, frame, clock)
        except Exception as e:                      # noqa: BLE001 — never fatal
            record['frame'] = 'could not write frame.jpg: %s' % e
        _answer_snap(folder, last, record, band)
    try:
        threading.Thread(target=job, name='snap-frame', daemon=True).start()
    except RuntimeError as e:
        record['frame'] = 'could not start the frame thread: %s' % e
        return _answer_snap(folder, last, record, band)
    return True


_snap_extras_told = set()


def _snap_extra_said(name, e):
    """Log a snap piece that could not be written, once per piece and reason."""
    key = (name, type(e).__name__, getattr(e, 'errno', None))
    if key in _snap_extras_told:
        return
    _snap_extras_told.add(key)
    log('snap: could not write %s (%s); the snap goes on without it, and this '
        'is said once' % (name, e))


def _snap_frame(folder, frame, clock=time.monotonic):
    """frame.jpg written; what reader.json says of it."""
    began = clock()
    data, info = snap_frame_jpeg((frame or {}).get('frame'))
    if data is None:
        return info
    took = clock() - began
    if took > SNAP_FRAME_CAP_S:
        return 'frame.jpg dropped: encoding took %.1fs, over its %gs' % (took, SNAP_FRAME_CAP_S)
    try:
        _write_bytes(os.path.join(folder, 'frame.jpg'), data)
    except (IOError, OSError) as e:
        _snap_extra_said('frame.jpg', e)
        return 'could not write frame.jpg: %s' % e
    at = frame.get('at')
    info.update(file='frame.jpg', source=frame.get('source') or 'sensor',
                ageMs=age_ms(at, time.time()) if isinstance(at, (int, float)) else None,
                encodeMs=int(round(took * 1000)))
    return info


def _answer_snap(folder, last, record, band=None):
    """reader.jpg, then reader.json — answer_snap's original half.

    reader.jpg is `last['fitted']`: the greyscale card as it came off the warp,
    before preprocess() — the picture tesseract's input was made from, which is
    what "why did it read that?" is asked of. In that order, because the
    server takes reader.json arriving as the answer being complete.

    `band`, MapBands.latest()'s answer: the newest offer's map band, copied in
    as map.jpg and map.json before reader.json (see MAP_BANDS_DIR). reader.json
    says which offer it was, or why there is none.
    """
    if last is not None:
        problem = PL.write_jpeg(os.path.join(folder, 'reader.jpg'),
                                last['fitted'], quality=SCAN_QUALITY)
        if problem:
            record['noCrop'] = 'could not write reader.jpg: %s' % problem
    if band:
        try:
            for src, name in ((band['jpg'], 'map.jpg'), (band.get('json'), 'map.json')):
                if src and os.path.isfile(src):
                    dst = os.path.join(folder, name)
                    shutil.copyfile(src, dst + '.part')
                    os.replace(dst + '.part', dst)
            record['mapBand'] = {'offerId': band.get('offerId'), 'file': 'map.jpg',
                                 'ageS': round(time.time() - band.get('savedAt', 0), 1)}
        except (IOError, OSError, KeyError, TypeError) as e:
            record['mapBand'] = 'could not copy the map band: %s' % e
    else:
        record['mapBand'] = None
    where = os.path.join(folder, 'reader.json')
    try:
        with open(where + '.part', 'w') as fh:
            json.dump(record, fh, indent=2)
        os.replace(where + '.part', where)
    except (IOError, OSError, TypeError, ValueError) as e:
        try:
            os.remove(where + '.part')
        except OSError:
            pass
        log('could not answer a snap into %s: %s' % (folder, e))
        return False
    log('snap: said what the reader last read into %s' % folder)
    return True


def card_finder_off(cfg, args):
    """Why the card finder is off, or None when it is on.

    Two ways to turn it off, and both give the reads this rig gave before it
    existed: every read is the drawn box, as drawn (rpi/test_pipeline.py holds
    them to that). The config key for a rig that should stay that way; the flag
    for one run.
    """
    if getattr(args, 'no_card_find', False):
        return '--no-card-find'
    if cfg.get('cardFinder') is False:
        return 'cardFinder is false in the config'
    return None


def card_finder_says(scanner, off, config_path=None):
    """The setup line's account of looking above the card box. One sentence.

    Off, and why; or on but with nothing to look for, and why; or on. "Nothing
    to look for" is PL.room_above's answer — the same function _look asks
    before it asks the finder, so the line cannot say the finder is looking
    when the reader never would.
    """
    if off:
        return ('card finder OFF (%s): a card taller than the card box loses its '
                'payout, as it did before there was one' % off)
    if not PL.drawn_card_box(scanner.roi):
        return ('card finder idle: no card box is drawn, so no card can be taller '
                'than one')
    if not PL.room_above(scanner.roi):
        return ('card finder idle: the card box starts at the top of the screen '
                'box, so there is nothing above it to look in')
    return ('card finder on: a read through the card box that finds a journey and '
            'no payout looks above the box for a taller card, and says so as '
            'cropFrom "found"%s' % (' (cardFinder: false in %s turns it off)'
                                   % config_path if config_path else ''))


def use_manual_box(scanner, quad_px, card=None):
    """Read exactly the box a person drew, and stop deriving one inside it.

    Three settings, and they only make sense together. The corners are the box.
    The crop is the card box the driver drew inside it, or all of the box when
    they drew none — never one derived, because that would trim the top off the
    very thing the driver framed. (One exception, and it is not a derived crop:
    a read through the card box that comes back with a journey and no payout
    may be read again through a taller card found above it — pipeline.py's
    _look, cardfind.py — and says so as cropFrom "found".) And the card's share
    of the quad is the card box's height (1.0 when the box *is* the card), which
    keeps the warp at the height the reader wants instead of twice it.
    """
    scanner.quad = np.array(quad_px, dtype=np.float32)
    scanner.roi = list(card) if card else list(CX.PIN_WHOLE)
    scanner.fixed_card_share = CX.card_share(card)
    scanner.card_share = CX.card_share(card)


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
        cfg = json.load(fh)
    _config_base[path] = copy.deepcopy(cfg)
    return cfg


_config_error = None
# The config as this process last read or wrote it, by path: what save_config
# measures its own changes against.
_config_base = {}
_MISSING = object()


def _changes_onto(disk, base, cfg):
    """`disk` with what this process changed — `cfg` against `base` — put onto
    it: a key it set or altered takes its value, a key it removed goes, and a
    key it never touched keeps whatever the file now says. Dicts are merged a
    level at a time, so a setting added beside one this process changed
    survives too."""
    for key, value in cfg.items():
        was = base.get(key, _MISSING)
        if was == value:
            continue
        if isinstance(value, dict) and isinstance(disk.get(key), dict):
            _changes_onto(disk[key], was if isinstance(was, dict) else {}, value)
        else:
            disk[key] = copy.deepcopy(value)
    for key in base:
        if key not in cfg:
            disk.pop(key, None)
    return disk


def save_config(path, cfg):
    """Write the calibration back, atomically and never fatally.

    Atomically because the web server reads this file to report what the scanner
    is doing, and must never see a half-written one. Never fatally because this
    is a convenience — it saves the next run rediscovering what this one already
    knows — and a read-only card or a full disk is no reason to stop reading
    offers. The scanner keeps the corrected values in memory either way.

    ONLY WHAT THIS PROCESS CHANGED, onto the file as it is now. It wrote its
    whole start-up copy back, so a key the owner put into the file after the
    scanner started was gone at its next save — `"carryTwo": true` in
    `settings` among them, which server.js reads off this file mid-shift, so
    carrying two turned itself off under two orders in the car. The tracker
    saves on its own clock (needs_save), so that was minutes, not a restart.
    Now the file is read again and only the keys this process set, altered or
    removed since it last read or wrote it are put onto it.
    """
    global _config_error
    try:
        base = _config_base.get(path)
        try:
            with open(path) as fh:
                disk = json.load(fh)
        except (OSError, ValueError):
            disk = None
        if base is None or not isinstance(disk, dict):
            # Nothing to merge onto, or nothing known of what was read: the
            # whole copy, as before.
            out = cfg
        else:
            out = _changes_onto(disk, base, cfg)
        tmp = path + '.part'
        with open(tmp, 'w') as fh:
            json.dump(out, fh, indent=2)
        os.replace(tmp, path)
        _config_base[path] = copy.deepcopy(cfg)
        _config_error = None
    except Exception as e:
        message = str(e)
        if message != _config_error:
            _config_error = message
            print('could not save calibration (further identical errors '
                  'suppressed): %s' % message)


LORES = (640, 480)

# How many buffers the camera cycles through. Named because the stall watch
# looks back over twice this many preview frames — see Repeats — since a camera
# stuck handing back a ring of stale buffers repeats a frame this many captures
# apart rather than on the next one.
CAMERA_BUFFERS = 4

# The table of full-field-of-view IMX519 modes used to be copied out here as
# well, with its own paragraph explaining that the two smaller modes are
# *cropped* out of the sensor rather than scaled down. Nothing in this file read
# it — not start_camera, which takes `main_size` straight from the config, and
# not any test — so it was a second statement of a rule this file does not
# apply, with no caller to make the two observably drift. Deleted; the live one
# is calibrate.FULL_FOV_MODES, which `--mode` is actually chosen from.


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
        buffer_count=CAMERA_BUFFERS,
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
                   view=VIEW_SCENE, found=None):
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

    `found` is the card found above the drawn card box that gave the payout
    the panel is showing (payout_from) — fractions of the screen, outlined in
    amber in either view (PL.outline_found), and None the rest of the time.
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
                if found:
                    ph, pw = picture.shape[:2]
                    PL.outline_found(picture, [[0, 0], [pw - 1, 0], [pw - 1, ph - 1],
                                               [0, ph - 1]], found)
        if picture is None:
            # No corners, or corners nothing could be warped out of. Falling
            # back to the scene is the useful answer rather than the tidy one:
            # it is the picture that shows *why* there is no phone view — the
            # phone out of frame, the mount knocked, the outline sitting on a
            # reflection — and it is the one the driver fixes that from.
            picture = PL.snapshot(frame, quad, roi,
                                  cfg.get('cardHeight', 900),
                                  width=SNAPSHOT_WIDTH, card=card,
                                  warp_card=scale is None, found=found)
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

# ...EXCEPT the cards the rig itself was unsure of, which are kept always.
#
# On the owner's week 338 of 1,166 offers (29%) landed a row the reader had
# doubts about: 328 with `milesCorrected` — recover_decimal's divide-by-ten,
# which moves the cost line tenfold if it guessed wrong — 9 doubted, 9 suspect,
# 4 with uncertain miles. Whether each guess was right is a question only the
# picture can answer, and those are exactly the reads nobody asked to keep. One
# picture per offer, the read that first landed it doubtful, in a folder of
# their own with the same cap: 400 at ~40KB is ~16MB, about eight days of
# this week's rate, the oldest going first.
DOUBT_DIR = 'doubt'

# ...and the cards that showed a payout and did not parse into a journey.
#
# A card the parser has never seen laid out — a new Uber layout, the first
# DoorDash cards this rig reads — arrives exactly like that: the payout is the
# one thing every card prints the same way, and everything after it is in a
# grammar the parser does not have yet. The log quotes the reader's text for
# one of them every SAMPLE_EVERY seconds, at most, and nothing else is kept;
# a layout is built from pictures of it, and those were thrown away. So the
# first such read of each card keeps its picture here, with the raw text the
# reader made of it beside it as a .txt of the same name. Same machinery and
# the same 400-picture cap as the doubt folder; the cap takes each .txt with
# its picture. Never off a ⌖ read: that is the whole screen box, a map or a
# planner round the card, and not a card the parser failed on.
#
# Not only new layouts, though. A card whose first read found the payout and
# not the journey, and whose next read parsed, keeps that first read here too:
# read_why says exactly NO_JOURNEY, "a payout but no journey", when it is
# judged. On the owner's measured week that was 59 of the 1,166 cards. Kept
# rather than filtered: the
# picture is written before the next read exists, and at its first read a
# card that never parses looks the same as one that parses a read later.
UNPARSED_DIR = 'unparsed'

# Why a read was not usable, in the words the log uses — one rule for the log's
# sample line and for which pictures go into UNPARSED_DIR. See read_why.
NO_JOURNEY = 'a payout but no journey'


def payout_from(kept, out, parsed):
    """Where the payout a reading SHOWS came from: ('found' or 'drawn', the card
    for the live view to outline in amber or None, what to keep for next time).

    Not where this read came from. The panel shows the MERGED reading, and a
    card read once off a card found above the drawn box (out['cropFrom'],
    pipeline.Scanner._look) and then through the box as drawn stays the same
    accumulator episode, at the same payout, with what the found read put into
    the merge still in it. Said per read, the panel's line went back to "drawn"
    and the amber outline came down on the box's first read of the card, while
    the panel went on showing the payout the found card gave.

    So it is said per episode. `kept` is (episode, crop) for the last found
    card that gave an episode its payout, or None. Every reading of that
    episode that shows a payout is "found" and outlines that card; a reading
    with no payout, another episode or a ⌖ read is "drawn" with no outline.
    Kept with its episode rather than with the outline, because a line with no
    payout between two reads of the same card (the accumulator passes it
    through with no episode) or a ⌖ read takes the outline down, and the next
    read of that card, back in the same episode, has to put it back on the
    card it means. A later read of the box that holds the payout itself does
    not clear it either: the merge still holds what the found read put in it,
    and the "?" on the panel asks for a look, not a different decision.

    The episode is the whole test, because only a merged reading with a payout
    has one: accumulate.add passes a reading with no payout through without
    it, and a ⌖ read is never merged (digest), so neither can equal a kept
    episode. A found read always has one: rescue_refused refuses a found card
    with no payout, and the parser never reads a payout of $0. This used to
    ask "not a ⌖ read, and a payout" as well, ahead of the episode; no input
    could make those two decide anything, so a version without either passed
    every check, and the checks that named "a ⌖ read" and "no payout" were not
    holding the thing that decides them. test_scan_pi holds the episode, and
    holds that those two readings carry none.
    """
    episode = parsed.get('episode')
    if out.get('cropFrom') == 'found':
        kept = (episode, out.get('crop'))
    if kept is not None and episode == kept[0]:
        return 'found', kept[1], kept
    return 'drawn', None, kept


def read_why(out, parsed):
    """Why this read was not usable, or None when it was.

    The sentence the log's sample line quotes, and the test for UNPARSED_DIR:
    a picture is kept when this says NO_JOURNEY. One function, so the line in
    the log and the folder on disk cannot disagree about which reads those are.
    """
    if parsed.get('complete'):
        return None
    if out.get('skipped') == 'dark':
        return 'too dark to read, so not read'
    if out.get('clipped'):
        return 'the payout sat against the top edge of the crop'
    if parsed.get('pay') is None:
        return 'no payout in the crop'
    return NO_JOURNEY


def doubted(row):
    """Is this journal row one the reader was unsure of? See DOUBT_DIR."""
    return bool(row and (row.get('milesCorrected') or row.get('milesUncertain')
                         or row.get('suspect') or row.get('doubt')))


def scan_dir(journal_path):
    """Where card pictures go: beside the journal, in a directory of their own."""
    return os.path.join(os.path.dirname(os.path.abspath(journal_path)), 'scans')


_pruning_said = set()


def prune_scans(where, keep=SCANS_KEEP):
    """Oldest first, so a long shift cannot outgrow the card it is written to.

    Says so the first time a folder reaches its cap in a run, once: pictures
    going is the bound working, but pictures going with nothing saying so is
    the second fault class.
    """
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
        # ...and the reader's text beside it, where there is one (see
        # UNPARSED_DIR): a .txt left after its picture is text nobody can put
        # a card to, and it is not counted against the cap.
        try:
            os.remove(os.path.join(where, name[:-len('.jpg')] + '.txt'))
        except OSError:
            pass
    if dropped and where not in _pruning_said:
        _pruning_said.add(where)
        log('%s is at its %d-picture cap: the oldest are now deleted as new '
            'ones arrive' % (where, keep))
    return dropped


def save_scan(image, offer_id, where, at=None, keep=SCANS_KEEP, text=None):
    """Keep one card picture. Never fatally: this is evidence, not the job.

    Named by the offer it belongs to and stamped, so a row in the journal and a
    picture on disk can be put back together months later without a second index
    to go wrong. Sorting the names sorts them by time, which is what lets the
    pruning above be a slice.

    `text`, when given, is written beside the picture under the same name as a
    .txt — the reader's own text for it. See UNPARSED_DIR.
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
        if text is not None:
            with open(path[:-len('.jpg')] + '.txt', 'w', encoding='utf-8') as fh:
                fh.write(text)
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

# READS LEFT UNREAD BECAUSE THE CROP WAS BLACK (PL.DARK_SKIP_BELOW), said at
# most this often. On 29 Oct the screen sat off for twenty minutes at a stretch,
# and a line per read would have been a line every couple of seconds saying the
# same thing; one a minute says it and how many reads it covered. Counted in
# the health line as "dark: not read" and on the `seen` row as `darkSkipped`,
# whole-screen reads nobody pressed for included — those return from digest()
# before the health tally, so the count is taken where every read arrives.
DARK_SAY_EVERY = 60.0


class Health:
    """Counts what happened, and says so occasionally.

    A per-read line would bury the log and a silent scanner cannot be
    diagnosed. This reports a summary only when something has actually
    happened since the last one.
    """

    def __init__(self):
        self.reset(None)
        # When the last "screen too dark to read" line was said, on the
        # caller's monotonic clock, and how many skips since. See not_read_dark.
        self._dark_said = None
        self._dark_unsaid = 0
        self.relocks = 0
        self.rebaselines = 0
        # The destination scan's two blind spots, counted for the whole run
        # rather than per window — these are questions asked about a shift,
        # days later, and a counter that resets every thirty seconds cannot
        # answer them. See digest(), where both are incremented.
        #
        # `address_refused_as_offer` is the rule-1 guard's own firing rate: a
        # frame that yielded a full address off a screen the rig judged to be
        # an offer rather than a destination — because it carried a payout, or
        # because it named a merchant, which is the half of that grammar that
        # survives a payout lost to glare or the crop edge.
        #
        # `street_seen_no_address` is a frame with no payout, something
        # street-shaped in the text, and no address out of it. This is the one
        # expected to move, and what it measures is how much of the driver's
        # missing destination is find_address being strict on purpose.
        self.address_refused_as_offer = 0
        self.street_seen_no_address = 0
        # `address_not_dropoff` is the label guard's firing rate: an address
        # off a payout-free screen that was refused because the screen did not
        # print it under a Dropoff label — under a Pickup one, or, unprompted,
        # under none. See digest().
        self.address_not_dropoff = 0
        # `screens_kept` is how many payout-free screens were recorded as
        # having followed a card — the corpus an accept-detector has to be
        # built on, and which does not exist yet. A run total for the same
        # reason as the two above: it answers a question about a shift.
        #
        # Counted at all because this is a collection, and a collection that
        # quietly stops collecting reads months later as a rate of zero. One
        # row per card is the bound, so on a shift of a hundred offers this is
        # a number under a hundred; anything near the offer count means every
        # card is being followed by a screen, and anything at zero means none
        # of them is.
        #
        # Deliberately NOT widened into the tally beside the other two, and the
        # difference is what each of them records. Those two count frames the
        # rig threw away, so a number in a log on a car computer was the only
        # trace they left and the `seen` row is what gets them off the Pi. This
        # one counts rows that went straight into the journal, which syncs on
        # its own — putting the count beside them would be one question
        # answered in two places, and the second would be the one nothing
        # could correct.
        self.screens_kept = 0
        # Preview frames that were the same picture, byte for byte, as one just
        # before them — Repeats' evidence of a stalled camera. A run total, and
        # the measurement the stall watch rests on: that a working camera never
        # hands one over is testcards' sensor model, not the IMX519, and a
        # count above nought on a line from a shift that read is this camera
        # saying otherwise. See STALL_SAY.
        self.repeats = 0
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
        # Reads whose payout came off a card found above the drawn card box —
        # see pipeline.Scanner._look. Beside `clipped` because they answer the
        # same question from the other side: how often the box the driver drew
        # was the wrong height for the card in front of it.
        self.rescued = 0
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
        # Reads whose crop had nothing bright enough in it to be text, and so
        # were never handed to tesseract (PL.DARK_SKIP_BELOW). Kept out of
        # `ms`: a skipped read costs a millisecond, and the median read time is
        # what says whether the Pi is reading slowly.
        self.dark_skipped = 0

    def add(self, out, parsed, card=None, previous=None):
        self.reads += 1
        if out.get('skipped') != 'dark':
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
        if out.get('cropFrom') == 'found':
            self.rescued += 1

    def not_read_dark(self, now, peak):
        """Count one read left unread for a black crop; the log line, when due.

        Every read the loop collects that PL skipped comes here, card-box and
        whole-screen alike (see DARK_SAY_EVERY), and the count is the window's,
        like `reads`. The line is rate-limited on its own clock — `now` is the
        caller's monotonic one — and says how many skips it stands for.
        """
        self.dark_skipped += 1
        self._dark_unsaid += 1
        if self._dark_said is not None and now - self._dark_said < DARK_SAY_EVERY:
            return None
        self._dark_said = now
        n, self._dark_unsaid = self._dark_unsaid, 0
        return ('screen too dark to read: the brightest of the crop was %s/255, '
                'under the %d a card\'s text reaches at its dimmest, so it was not '
                'handed to the reader (%d read%s like it since this was last said) '
                '— is the phone\'s screen on?'
                % ('?' if peak is None else '%d' % round(peak), PL.DARK_SKIP_BELOW,
                   n, '' if n == 1 else 's'))

    def counters(self, now):
        """Every figure report() speaks of, as it stands, without saying it.

        report() hands the same dict back as its tally, so the two cannot count
        differently. Asked by 📷 Snap mid-window too, which is why this neither
        logs nor starts a new window: a press would otherwise cut the two-minute
        health line short and reset the counts the `seen` row is built from.
        `over` is None before the first read has opened a window.
        """
        return {'over': None if self.since is None else int(now - self.since),
                'reads': self.reads, 'complete': self.complete,
                'failed': self.failed, 'noPay': self.no_pay,
                'clipped': self.clipped, 'rescued': self.rescued,
                'darkSkipped': self.dark_skipped,
                'medianMs': (int(round(sorted(self.ms)[len(self.ms) // 2]))
                             if self.ms else None),
                'saw': self.saw, 'kept': self.kept,
                # Run totals, not window totals — see __init__.
                'streetNoAddress': self.street_seen_no_address,
                'addressAsOffer': self.address_refused_as_offer,
                'addressNotDropoff': self.address_not_dropoff,
                'screensKept': self.screens_kept,
                'repeats': self.repeats,
                'relocks': self.relocks, 'rebaselines': self.rebaselines,
                'bright': self.bright, 'banding': self.banding,
                'gain': self.gain, 'exposure': self.exposure,
                'measuredExposure': self.measured_exposure,
                'tooBright': bool(self.too_bright), 'tooDim': bool(self.too_dim)}

    def report(self, now, tracker, scanner):
        """Say what has happened lately. Returns the tally, or None if silent.

        The tally goes back to the caller because the counts are worth keeping
        as well as printing: the log is on the machine nobody reads, and how
        many cards went past unrecorded is a question a driver asks about a
        shift, days later, from the offers page.
        """
        if self.since is None:
            self.since = now
        if now - self.since < HEALTH_EVERY or not (self.reads or self.failed
                                                   or self.dark_skipped):
            return None
        tally = self.counters(now)
        if not self.reads and not self.failed:
            # Nothing but whole-screen reads left unread for a black crop,
            # which never reach add(). Said, because a window of them is a
            # screen that was off.
            log('health over %ds: %d dark: not read'
                % (now - self.since, self.dark_skipped))
            tally.update(self._window(tracker))
            self.reset(now)
            return tally
        if not self.reads:
            # Every read raised. There are no timings to summarise and nothing
            # else here is meaningful, but saying so is the whole point.
            log('health over %ds: %d reads, ALL FAILED — see the read failure '
                'above for what went wrong' % (now - self.since, self.failed))
            # Reachable on the journal and not only in the log: `saw` is
            # counted after the read that saw it, so a window can open on a
            # card it inherited and then fail every read it makes — and that
            # is the window whose diagnostics are most worth having.
            tally.update(self._window(tracker))
            self.reset(now)
            return tally
        bits = ['%d reads, %d complete' % (self.reads, self.complete),
                # None when every read in the window was skipped as dark.
                'median %s' % ('-' if tally['medianMs'] is None
                               else '%.0fms' % tally['medianMs'])]
        if self.dark_skipped:
            bits.append('%d dark: not read' % self.dark_skipped)
        if self.failed:
            bits.append('%d failed' % self.failed)
        # `or self.kept`, because the two are counted at different moments and
        # a window boundary can fall between them. `saw` goes up on the first
        # read that finds a payout and `kept` on the read that lands the row,
        # and on the owner's own week 104 of 1,166 offers have at least one
        # read between the two — median 3, max 7, which at a 1.85s read is
        # three to thirteen seconds. Gated on `saw` alone, a window whose only
        # news was "a card reached the journal" said nothing at all.
        if self.saw or self.kept:
            bits.append('%d card%s seen, %d recorded%s'
                        % (self.saw, '' if self.saw == 1 else 's', self.kept,
                           '' if self.saw else ' (first seen before this window)'))
        if self.no_pay:
            bits.append('%d found no payout' % self.no_pay)
        if self.clipped:
            bits.append('%d had the payout at the crop edge' % self.clipped)
        if self.rescued:
            bits.append('%d read the payout off a taller card found above the '
                        'card box' % self.rescued)
        # Outside the tracker block on purpose: these say nothing about the
        # corners, and a rig started with --no-track is exactly the one whose
        # destination scan is worth watching.
        #
        # ...and SAID to be run totals, which every other number on this line is
        # not. The line is headed "health over 120s" and everything else in it
        # was counted inside that window and reset; these two are kept for the
        # whole run, because they answer a question about a shift. Without the
        # marker a driver reading two consecutive lines sees "3 screens" and
        # then "3 screens" and concludes it happened twice — or sees it climb
        # and reads a rate that is really a total. `relocks` below has said
        # "since start" for exactly this reason since long before these existed.
        if self.street_seen_no_address:
            bits.append('%d screen%s since start had a street on it and no '
                        'address the rig would accept'
                        % (self.street_seen_no_address,
                           '' if self.street_seen_no_address == 1 else 's'))
        if self.address_refused_as_offer:
            bits.append('%d address%s since start refused for being on an '
                        'offer card'
                        % (self.address_refused_as_offer,
                           '' if self.address_refused_as_offer == 1 else 'es'))
        if self.address_not_dropoff:
            bits.append('%d address%s since start refused for not being under '
                        'a Dropoff label'
                        % (self.address_not_dropoff,
                           '' if self.address_not_dropoff == 1 else 'es'))
        if self.screens_kept:
            bits.append('%d screen%s since start recorded as following a card'
                        % (self.screens_kept,
                           '' if self.screens_kept == 1 else 's'))
        # Said as the premise it is, not as a fact about the sensor: that a
        # working camera hands over none is testcards' model, and this count
        # is how this camera answers it. "A live camera's never are" claimed
        # the answer before any real frame had been asked.
        if self.repeats:
            bits.append('%d frame%s since start the same picture as one of the '
                        '%d before it — none, if the sensor model the stall '
                        'watch rests on holds for this camera'
                        % (self.repeats, '' if self.repeats == 1 else 's',
                           2 * CAMERA_BUFFERS))
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
            bits.append('corners %s, %.0fpx from calibration (%.0fpx since last save)'
                        % (corners_word(status), status.get('wander', status['drift']),
                           status['drift']))
            if self.relocks:
                bits.append('re-locked %dx since start' % self.relocks)
            if self.rebaselines:
                # "the size it judges against", not "the calibration". The
                # calibration itself is kept for the run — it is what `wander`
                # is measured against — and saying
                # otherwise sent a driver to re-calibrate over something the
                # rig had already worked around.
                bits.append('un-stuck %dx — the size the tracker judges against '
                            'is out of date' % self.rebaselines)
        log('health over %.0fs: %s' % (now - self.since, '; '.join(bits)))
        tally.update(self._window(tracker))
        self.reset(now)
        return tally

    def _window(self, tracker):
        """What the `seen` row carries beyond counters(): the corners' state.

        The rest of the window's diagnostics — complete, noPay, clipped,
        medianMs, tooDim, tooBright, relocks — were first written here as a
        second copy of what counters() already says from the same counters.
        Two functions answering one question drift, so counters() is the one
        answer (the tally starts from it) and this adds only what it cannot
        know: the tracker, which report() is handed and counters() is not.

        `corners` is None with nothing tracking — --no-track, or a box drawn by
        hand — which is not the same answer as 'held'.
        """
        return {'corners': (None if tracker is None
                            else corners_word(tracker.status()))}


def corners_word(status):
    """'lost', 'stuck' or 'held', for the health line and the `seen` row alike.

    Three states, not two. "Held" used to cover being frozen beside the screen
    as well as tracking it, because a candidate was found on every check either
    way and only `misses` was being reported.
    """
    return ('lost' if status['lost']
            else 'stuck' if status.get('stalled') else 'held')


def worth_recording(tally):
    """Whether a health window has news the journal should keep.

    A quiet two minutes with the phone out of the mount is not evidence about
    anything and would bury the windows that are. A window in which a card was
    SEEN or a card was RECORDED is evidence, and it used to have to be the
    former.

    `saw` goes up on the first read that finds a payout; `kept` goes up on the
    read that lands the row. They are different moments and `report()` resets
    the window between them whenever a boundary falls in the gap — on the
    owner's own week, 104 of 1,166 offers have at least one read between the
    two (median 3, p90 5, max 7). When that happened and no other card arrived
    in the second window, the `kept` was thrown away: `server.js` sums `saw`
    and `kept` over the rows that exist, so a 1 and a 0 became "1 offer is
    missing from everything above" on the offers page, about a card sitting in
    the journal. That is the figure whose whole job is to say what the file is
    missing, reporting a miss against a file that is complete — the same fault
    the surrounding comments were written to fix for glare frames, arriving
    through the window boundary instead.
    """
    return bool(tally) and bool(tally.get('saw') or tally.get('kept'))


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
        # All six reasons, in the driving screen's own words. This had three,
        # and the voice is the whole of what a driver gets while they are
        # looking at the road: a card doubted for its RATE — the one reason
        # that catches a decimal that slipped while staying inside SANE_PAY —
        # was spoken as "read that again" here and as "check the pay and the
        # time" by live.html, about the same card on the same rig.
        return {'pay': 'check the pay.', 'time': 'check the time.',
                'speed': 'check the distance.',
                'rate': 'check the pay and the time.',
                'leg': 'check the time, most of the trip did not read.',
                'screen': 'not an offer.'}.get(rate.get('doubt'),
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
# the verify beat backs off to VERIFY_MAX, so a card sitting unchanged with a
# read on the end of the beat produces a silence of the two added together —
# 6.0 + 3.7 is 9.7s at the p90 read, and the worst read measured is 5.9s. The
# page would dim the verdict and say the rig had stopped at the exact moment the
# driver is reading it to decide.
#
# The figures in this paragraph were "twelve seconds" and "a 1.4s read", giving
# 13.4s, and both were stale: the ceiling is 6.0 and a read is 1.85s at the
# median. The conclusion survived the correction, which is luck rather than
# design — see READ_SECONDS, where the estimate that produced them is replaced
# by the owner's own 272 measured reads.
#
# So the loop says so itself, on a beat well inside that window. It is one small
# line of JSON: no verdict, no numbers, nothing that can overwrite a reading —
# `ready` is absent, which is what the server and the page both key on. What it
# proves is the thing actually worth proving, which is that the loop is turning.
# A wedged loop stops sending it; a process that is merely idle does not.
ALIVE_EVERY = 4.0


def not_saving_notice(log):
    """The panel's sentence for a journal that is refusing writes, or None.

    A sentence and not a flag: the end
    that knows what went wrong is this one, and the page must not be in the
    business of guessing a driver's situation from an errno. The errno rides
    along all the same — on a Pi, "Read-only file system" is the entire
    diagnosis, and a driver who cannot act on it can at least repeat it.

    `--no-journal` says nothing. Nothing is being saved there either, and that
    is what the driver asked for; a warning about it would be permanent and
    therefore furniture.
    """
    why = log.journal.failing() if log is not None else None
    if not why:
        return None
    # Short because it competes with the verdict for a 3.5" panel, and leading
    # with the consequence rather than the cause because the consequence is the
    # part that is true for every errno.
    return 'Offers are NOT being saved: %s' % why


def emit_alive(too_bright=False, too_dim=False, not_saving=None, blind=None,
               gps=None, pi=None, heat_guard=False):
    """The beat, and the conditions that have to reach the driver without one.

    `tooBright` rides here rather than on a reading because the state it
    describes is precisely the state where there may be no reading: the phone is
    brighter than the camera can take, the card is washing out, and the remedy
    is a slider the driver has in their hand. Sent every beat so the page can
    clear it as soon as it goes away, and outside `ready` so it can never
    overwrite a verdict.

    `notSaving` is the second, and the one this rig had no channel for at all.
    The journal refusing writes is the only failure here that costs something
    which cannot be got back: a washed-out card can be re-read, a box drawn
    wrong can be drawn again, and an offer nobody wrote down is gone. It
    is a sentence or None, never a flag — the reason belongs to the scanner,
    which is the only end that knows it. It
    rides the heartbeat rather than a reading because the whole point is that
    the readings go on looking perfect while it happens — server.js writes its
    own rows through a request and can answer 500, and the driver's tick
    already reports that way, but the offers themselves are written from inside
    this loop with nobody to answer.

    `gps` and the Pi's own health are the last two, and they ride here for the
    reason `notSaving` does: the readings go on looking perfect while either is
    wrong. A phone whose GPS app has timed out costs every row from then on its
    position, and a rig with no `--gps` wrote rows exactly like it — 0 of the
    1,166 on the owner's week carry one, and nothing anywhere said whether that
    was a choice or a fault. A Pi that is throttling reads slower and says so
    nowhere. `gps` is `{state, ageSeconds, fix}` — the word UpDown has settled
    on, which is the same word the journal is told, how old the newest fix is,
    and that fix itself with its quality and the gate's answer (beat_fix), for
    the maps' "you are here" dot.
    `pi` is PiHealth.sample()'s four fields, spread onto the beat as names of
    their own the way the flags above are: the page reads `cpuC` and
    `throttled`, and the reason beside each null goes on to /api/status.

    `blind` is the camera's word when it cannot see — 'stalled' or 'dark',
    UpDown's settled word and so the journal's — and None while it can. It
    rides here for the reason all of these do and more than any of them: a rig
    that cannot see produces no readings at all, so this beat is the only
    message left to carry the news. It was the one condition with no channel:
    the owner's rig read once in 9.4 days, beating every four seconds, and the
    panel said "scanner reading" for all of it. A word and not a sentence, like
    `tooDim`, because the page needs two things from it — a label short enough
    to stand where the verdict stands, and the line saying what to do — and
    only the page knows how much room it has for each.

    `heatGuard` is whether the heat guard (HeatGuard) has the reads nobody
    pressed for SCREEN_AUTO_HOT apart instead of SCREEN_AUTO_EVERY: true or
    false, never null, and judged off this beat's own `cpuC` and `throttled`.
    The guard's thresholds are the scanner's, so the page is told the state
    and does not work it out again from the figures beside it.
    """
    beat = {'alive': True, 'at': int(time.time() * 1000)}
    beat.update(alive_flags(too_bright, too_dim, not_saving, blind))
    beat['gps'] = gps
    beat.update(pi or {})
    beat['heatGuard'] = bool(heat_guard)
    print(json.dumps(beat), flush=True)


def alive_flags(too_bright=False, too_dim=False, not_saving=None, blind=None):
    """The beat's four conditions as the wire carries them.

    Its own function so 📷 Snap's reader.json says the last beat in the words
    the beat said it, rather than in a second spelling of the same four.
    """
    return {'tooBright': bool(too_bright), 'tooDim': bool(too_dim),
            'notSaving': not_saving or None,
            'blind': blind or None}


def emit_reading():
    """A card is in front of the reader and the reader has started on it.

    The one thing the driver could not see. A read is about 1.8 seconds on a
    Pi 4 and 91% of it is inside tesseract, and for every one of those seconds
    the dashboard said WAITING FOR AN OFFER over a row of dashes — which is what
    it says when there is nothing on the phone at all. The card was there, the
    rig had noticed it, and the panel was reporting the opposite.

    Sent when the frames are handed over rather than when the verdict comes
    back, because the whole point is the gap between the two. Like the
    heartbeat, it carries no `ready` and no numbers, so it cannot overwrite a
    verdict or vouch for one — it says only that the wait has a reason.

    Only for a read that is looking for an offer, which is the read whose end
    is a message carrying `ready`. A ⌖ read of the whole screen is not one —
    see where this is called. And "a card" is the panel's word, not this
    message's: the loop does not know a card is there until the read says so,
    so live.html says READING THE SCREEN instead when the last read found no
    offer at all.
    """
    print(json.dumps({'reading': True, 'at': int(time.time() * 1000)}),
          flush=True)


# --- the rig's own account of itself: up, down, the phone, the GPS, the Pi ----
#
# The rig never said when it stopped, crashed, lost sight of the phone or lost
# its GPS. Every one of those was either a line in a log on a headless box or a
# counter in server.js that dies with the server — `fell` and `wedged` start
# again at nought on every restart — so a shift could not be asked afterwards
# whether the rig was running through it. A silence in the journal reads the
# same whether the driver was between offers or the camera was dead.
#
# What is written is CHANGES and nothing else. A row every quiet two minutes
# was proposed and refused (AUDITS.md, "What else the rig could collect", and
# the gate at worth_recording): a quiet window is not evidence and would bury
# the windows that are. So each of these is a row when something became true,
# once it has stayed true long enough to be news, and nothing in between.
#
# Collection only. Nothing divides by these and nothing reads them into a
# verdict; the offer rows, the advice and the panel's figures are untouched by
# any of it.

# How long the camera has to have lost the phone's screen before the journal is
# told it has gone.
#
# The state already existed — the tracker's `lost`, logged as "screen not
# visible — is the phone lit and in frame?" — and went only to that log. A
# driver lifting the phone to look at a card loses it for a few seconds, many
# times a shift, and a row for every one of those is the quiet-window row above
# under another name. A minute outlasts a glance and still puts a phone left on
# the seat, a screen gone dark or a mount knocked out of line on record within
# a minute of it happening.
PHONE_HOLD = 60.0

# ...and the same for the GPS. gps.py already rides out twenty seconds of a
# hotspot stumbling before a fix counts as stale (STALE_AFTER); this is how long
# it has to stay that way beyond that before it is a row, and a word on the
# panel. What usually ends a fix is the phone's own app, which runs on a timer
# and does not come back by itself — so this is a wait for the stumble to
# clear, not for the fault to.
GPS_HOLD = 60.0

# --- a rig that cannot see, and says so ----------------------------------------
#
# Measured on the owner's own rig, from its own log: one scanner process ran
# from 27 Sep to 8 Oct without a restart and made ONE read in 814,077 seconds —
# its read counter went 1092 to 1093 across 9.4 days, a full shift of offers on
# 7 Oct among them — with the screen reading 1-2 of 205 in the reads either
# side. The heartbeat beat throughout, the panel said "scanner reading", and
# nothing reached the journal. A restart at 02:38 brought reading straight back.
# Whether the phone was out of the mount or too dim to see in it, or the
# camera's feed had stalled, is not known, so a dark box and a stalled feed are
# both watched for, and both are one word: what the camera can see. 'seeing',
# 'stalled' or 'dark', on the beat as `blind` (None while seeing) and in the
# journal as `camera` rows.
#
# STALLED is the camera handing over the very same picture, byte for byte, as
# one of the few frames before it. Not a still picture — the SAME one. A live
# sensor does not do that: its noise moves pixels on every frame however still
# the scene, and two frames agreeing on all 307,200 of them is not something
# noise does. Measured with the sensor model the suites' own cards are
# drawn with (testcards.mount's sigma of 3 a sensor pixel, drawn fresh for each
# frame and shrunk to the 640x480 preview), over 59 consecutive pairs at each of
# three cabins — two as dark as the owner's, whose box read 2 and 3 of 205
# against the owner's 1-2, and the suites' empty mount at 24: no pair alike,
# and the fewest pixels that differed between any two frames was 102,285 of the
# 307,200. The suites' fake cameras were the opposite — a still render handed
# over every time: replayed at their own pace, a capture every 10ms for 12
# seconds, 1,199 of 1,200 consecutive pairs were identical, the one exception
# being the card arriving — so they now differ frame to frame the way a sensor
# does, and the stall is what a fake does when it is told to freeze.
#
# Against the frames before it, not only the last one, because the camera
# cycles CAMERA_BUFFERS buffers: one stuck handing the same ring back would
# never repeat on the very next frame. Twice that many, because a read takes a
# capture the watch never sees. See Repeats, which measured both and what they
# cost.
#
# That is a model, not the IMX519. No frame off the real sensor exists here to
# measure, so the rig measures it itself: every repeat is counted from start
# (Health.repeats), the health line says how many there were, and every `seen`
# row carries the count to the copy machine. A working camera that repeats a
# frame now and then would show it there, on a shift that read, long before
# six seconds of them made a stall.
#
# A frame is no evidence when nothing in it can show noise. Every pixel on one
# of its two extremes is that frame: a flat one — a box of black, a sensor at
# full well — and one that is black clamped against full well, the two places
# a sensor's noise is clipped away. Two of those match whatever the camera is
# doing, so a repeat of one is not counted, and darkness is the other watcher's
# to judge. A frame with a single pixel between its extremes carries noise, and
# a repeat of it is a repeat.
#
# One repeat is therefore already proof, and the hold is not there to doubt it.
# It is there because of what a frozen picture does while it lasts: frozen on an
# offer card, the verify beat goes on re-reading the same card every few
# seconds and every reading comes back fresh, so the panel paints a live,
# confident verdict about a card that left the phone long ago. VERIFY_MAX is
# how long this rig already lets a verdict outlive its card — the ceiling on a
# replaced card going unnoticed — and a frozen camera is given no longer.
STALL_SAY = VERIFY_MAX

# A restart cures a stall — the owner's did, at once — and it is the only cure
# this rig has, so a stall is answered by going quiet for server.js's watchdog
# to restart. But nothing limited how often: a camera a restart does NOT cure
# stalls again in the first seconds of every run, and the cycle — STALL_SAY's
# six seconds to say it, SILENT_MS's thirty of silence, server.js's backoff,
# capped at a minute — goes round all night, writing a start, a camera stalled
# and a rig restart row every time, while the panel flicks between the
# autopilot starting up and CAMERA STALLED. Were the premise above wrong for
# this sensor, the same loop would run on a working camera every time the scene
# sat still.
#
# So a stall asks for a restart at most once every STALL_AGAIN. Going quiet over
# one leaves a note for the run after it (handoff.STALLED), and a stall said
# while that note is younger than this stays up instead: it goes on beating the
# stall to the panel and comparing every frame, so a camera that comes back is
# seen on the frame it does — and it goes quiet for the next restart only when
# the note has aged out. One restart in ten minutes, six an hour at most, where
# only the backoff limited it before; and a second stall that soon after a
# restart is a camera whose cable wants reseating, which the panel says.
#
# The note's age is its mtime against the wall clock, handoff.age's idiom. A
# clock that steps between the two makes the age wrong for that one note: a
# step back reads as a note from the future and the restart is asked for, as
# it was before this existed, and the backoff still bounds it.
STALL_AGAIN = 600.0

# DARK is the box the rig reads holding nothing it counts as a lit screen, for
# as long as a phone has to be gone before it is news. Asked only where nothing
# tracks the corners — a box drawn by hand, or --no-track — because there the
# tracker's `phone gone` cannot fire, and on the owner's rig the box IS drawn by
# hand. Where the tracker runs it answers this already and a second row about
# the same absence would be the same question asked twice.
#
# "No lit screen" is not a threshold of its own. It is AutoGain's `lit` — the
# window's brightness against exposure.LIT_ENOUGH, the same answer the gain
# already refuses to brighten an empty mount on — so the rig cannot call a box
# empty for the gain and full for the panel. The hold is PHONE_HOLD, for the
# same reason: a minute outlasts a glance, on either kind of rig.
#
# It does NOT say the phone is gone, because brightness cannot tell a missing
# phone from a dim one: this repo has a lit screen on record reading 4 and a
# night-time card reading 6 (exposure.LIT_ENOUGH's own note), and the owner's
# reads either side of the blind week were 1-2. Nor that the rig cannot see a
# card arrive — that too is more than it knows. What it can say is that it
# cannot be SURE of seeing one. Under LIT_ENOUGH the gain does not rise on its
# own — that is the guard — and the motion gate, which is what sends a read
# when a card lands, scores a card arriving by how much the box changed, and in
# a dim box nothing changes by much. Measured on testcards' Uber card mounted
# 1200px wide in a cabin reading 2, as dark as the owner's, the screen turned
# down by scaling it and a fresh draw of the sensor noise for each frame: the
# gate's score against its CHANGE_T of 6.0 for the card arriving over the map,
# by what the box read before it came (AutoGain's own reading of it). Eight
# draws of the noise at each level near either line moved a score by 0.02 at
# most; two scores to a reading are two brightnesses that round to it:
#
#   light mode   7 -> 0.62   11 -> 1.28   18 -> 2.23 | 23 -> 2.48   46 -> 5.39
#                                                      53 -> 5.72   56 -> 6.03
#   dark mode    3 -> 1.26    8 -> 3.21   13 -> 5.20, 5.52   14 -> 5.72, 6.04
#                                          15 -> 6.27   17 -> 7.08   19 -> 7.90
#
# So under LIT_ENOUGH (the bar) a light-mode card is not noticed at any reading
# measured, and a dark-mode one is from 14 or 15 up — by under five per cent at
# 15 and by about a third at 19. The box's reading cannot tell the two modes
# apart, so a lit dark-mode screen reading 15 to 19, and some reading 14, is
# called dark although the gate would notice a card landing on it, and a light
# one at the same reading is not seen at all: what holds for both is that the
# rig cannot be sure. Above the bar a light card is still missed at 53 and noticed from 56,
# but there the screen counts as lit and the gain climbs on it, up to twice
# over a beat (exposure.UP_MAX), or says too dim when it has nothing left to
# climb with; under it the gain is held, so nothing gets better and nothing but
# this says so. (The reader itself is not the limit: handed the dark-mode card
# reading 4, it read $16.05, 23 min and 8.4 mi. Nothing sends it one.)
#
# The word is therefore 'dark', the panel's is TOO DARK TO BE SURE, and the
# remedy it gives covers both causes — the phone in the mount, its screen on
# and turned up. That is also what keeps it apart from `tooDim`: that is a
# screen the gain counted as lit and spent everything on, this is one it never
# counted, and AutoGain decides both off the same `lit`.
#
# Not on a pass where a read went out — the rig was looking. Most reads are the
# motion gate's, and the one a card arriving sends is the first sign of it,
# seconds before the gain's next look at the box. Reads a timer sends count
# too (the verify beat, a resample or dropoff window, a deferred trigger),
# which can only hold the word back, never bring it on.


# How often to ask the Pi how hot it is and whether it is throttling. The
# temperature is a file read; the throttling is a process (vcgencmd), which is
# not worth starting on every four-second beat — and need not be, because the
# firmware's own since-boot bits remember a dip between two samples. Thirty
# seconds can lose WHEN a supply sagged, never WHETHER it did.
PI_EVERY = 30.0

# The heat guard: the whole-screen reads nobody pressed for, put off while the Pi
# is hot (SCREEN_AUTO_HOT in place of SCREEN_AUTO_EVERY), and nothing else.
#
# The owner reports their Pi 4 at 60-80°C on a shift, and vcgencmd's 0x80000 —
# the soft temperature limit, reached since boot. Past that limit the firmware
# cuts the clock, and while it does every read is slower, the offers' included.
# On top of the offers the rig now reads the planner, the navigation screen and
# labelled dropoffs on its own every SCREEN_AUTO_EVERY while an order is held:
# load nobody asked for at that moment, and the one load that can wait.
#
# ON at 75°C, or at any throttle word NOW (THROTTLE_BITS). Raspberry Pi's own
# figures for the Pi 4, not measured on this rig: the soft limit is 80°C, and
# the clock is cut from there to the hard limit at 85°C. 75 puts the reads off
# before the firmware has to step in, inside the 60-80 the owner reports and
# below the limit the rig has already hit. A word NOW is the firmware already
# acting, or about to — a capped or throttled clock, the soft limit, or the
# under-voltage that is the other reason it caps one (see THROTTLE_BITS) — so
# the temperature no longer decides: every read is slower whatever the figure,
# and a sagging supply is asked for less. The since-boot words never turn it
# on: 0x80000 is since-boot only, and one hot minute at 6pm would slow these
# reads for the rest of the boot.
#
# OFF below 70°C with no word now, and between the two as it was. The band is so
# that what the slower reads save cannot switch it off at one sample and the
# heat bring it back at the next; how many degrees they save on the rig has not
# been measured. It changes at most once a PI_EVERY, the sample it is handed,
# and from the same sample the beat carries as `cpuC` — no second reader.
#
# Not the card finder's second read, though it was the obvious other thing to
# put off: README "A card taller than the card box" measures it at 200ms
# median (178-275) on the development box, and it is how a payout above the
# drawn box is read at all — the Early-look card's $14.48 on 73 of 144 frames,
# and the panel said no offer before it. Skipping it while hot loses that
# payout, and it is an offer read.
HEAT_ON_C = 75.0
HEAT_OFF_C = 70.0

# The words gps.Phone.state() uses, in the words the beat and the journal use.
# `looking` is a phone asked for that has not handed over one position since the
# rig started — lost from the start, as far as the rows are concerned; `stale`
# is one that did and has not since. gps.py's own test says why those two are
# kept apart: "the phone stopped talking" and "there is no phone" want
# different answers from the driver.
GPS_WORDS = {'fixed': 'ok', 'stale': 'stale', 'looking': 'lost', 'off': 'off'}

# vcgencmd get_throttled, bit by bit. The low four are NOW and the same four
# sixteen places up are SINCE BOOT — so a Pi that dipped once at 6pm still
# says so at midnight, which is what makes the rows worth keeping, and only the
# low four ever put anything on the panel.
#
# Listed cause first: under-voltage and the (soft) temperature limit are WHY, a
# capped or throttled clock is what the firmware did about it. The panel has
# room for one word beside the GPS note on the 3.5" hat — measured, the full
# list for a weak supply ("under-voltage, throttled") and a stale GPS together
# ran 370px into the 315px the row has there — so it takes the first, and the
# first is the one with a remedy: the power lead, or shade. "temp limit" and
# not "soft temp limit" for the same 315px: with a GPS two hours stale beside
# it the longer word was cut by 2px. live.html names 'under-voltage' too — it
# is the one word it does not put the temperature beside — so a rename here
# is a rename there.
THROTTLE_BITS = ((0, 'under-voltage'), (3, 'temp limit'), (2, 'throttled'),
                 (1, 'capped'))

THERMAL = '/sys/class/thermal/thermal_zone0/temp'


def gps_now(phone, refused=None):
    """(word, ageSeconds, why) for the GPS as it is this moment, unsettled.

    `refused` is the reason `--gps` was given and could not be used — an
    address that would not parse. That rig asked for a position and will never
    get one, and saying 'off' for it would be the panel keeping quiet about the
    very fault the flag was typed to avoid. It reads as lost, with the reason.
    """
    if phone is None:
        return ('lost', None, refused) if refused else ('off', None, None)
    s = phone.state()
    return GPS_WORDS[s['state']], s.get('ageSeconds'), s.get('error')


def beat_fix(phone):
    """The newest fix whatever its age, as the heartbeat carries it — or None.

    For the panel's "you are here" dot, and in the journal's own seven fields
    (`lat`, `lon`, `gpsAge`, `gpsErr`, `gpsMode`, `gpsOk`, `gpsWhy`; see
    JR.fix_fields) so that a page reads a beat's position exactly as it reads
    a row's. Phone.latest() rather than fix(): a fix past gps.py's twenty
    seconds is still where the car WAS, judged `stale`, and the panel draws it
    grey rather than letting it vanish with nothing saying why. The gate's
    answer comes with it from gps.py; nothing here or on the page asks again.

    ...and `freshFor`, gps.py's count of the seconds this fix has left inside
    its staleness rule. A beat that stops coming — the scanner gone, the link
    down — leaves the page holding a fix nobody will re-judge, and this is
    what lets the page grey it on its own clock without a copy of the rule.

    ...and `speed` (m/s, to a tenth, None where the receiver gave none) and
    `driving`, gps.py's answer to whether the car is being driven as of this
    fix (DRIVING_SPEED there): the panel's driving form reads it and asks
    nothing again. Beside the journal's seven fields rather than among them:
    JR.FIX_FIELDS are what an offer row is written with, and a row says where
    its card was read, not how fast.

    ...and `drivingFor`, the seconds that answer has left of gps.py's hold
    (DRIVING_HOLD), for the same reason as `freshFor`: a beat that stops
    coming leaves the page holding a driving state nobody will end, and this
    is when gps.py would have ended it. Without it the page went by
    `freshFor`: up to 20 s on the rig against the hold's 10.
    """
    got = phone.latest() if phone is not None else None
    if not got:
        return None
    speed = got.get('speed')
    return dict(JR.fix_fields(got), freshFor=got.get('freshFor'),
                speed=(round(speed, 1) if isinstance(speed, (int, float))
                       and not isinstance(speed, bool) else None),
                driving=got.get('driving') is True,
                drivingFor=got.get('drivingFor'))


def cpu_temp(path=THERMAL):
    """(degrees C, None) or (None, why). One file, millidegrees in it."""
    try:
        with open(path) as fh:
            return round(int(fh.read().strip()) / 1000.0, 1), None
    except (OSError, ValueError) as e:
        return None, str(e) or e.__class__.__name__


def throttling(run=subprocess.run):
    """({now, sinceBoot}, None) or (None, why).

    `run` is injected so the suite can hand it what a real Pi answers. On
    anything that is not a Pi there is no vcgencmd, and the answer is None
    with that said rather than an empty list, which would read as "checked,
    and fine".
    """
    try:
        done = run(['vcgencmd', 'get_throttled'], capture_output=True,
                   text=True, timeout=1.0)
    except FileNotFoundError:
        return None, 'no vcgencmd on this machine'
    except (OSError, subprocess.SubprocessError) as e:
        return None, 'vcgencmd: %s' % (str(e) or e.__class__.__name__)
    found = re.search(r'throttled=(0x[0-9a-fA-F]+)', done.stdout or '')
    if done.returncode != 0 or not found:
        return None, 'vcgencmd said %r' % ((done.stdout or done.stderr or '')
                                           .strip()[:80])
    bits = int(found.group(1), 16)
    return {'now': [w for b, w in THROTTLE_BITS if bits >> b & 1],
            'sinceBoot': [w for b, w in THROTTLE_BITS if bits >> (b + 16) & 1]}, None


class HeatGuard(object):
    """Whether the Pi is too hot for the reads nobody pressed for: `on` at
    HEAT_ON_C or any throttle word now, off below HEAT_OFF_C with none, and
    as it was in between. See HEAT_ON_C.

    A temperature that cannot be read leaves the words to decide alone, which
    is off with none: a guard that held on to a figure it can no longer see
    would slow the reads for the rest of the run on nobody's say-so.
    """

    def __init__(self):
        self.on = False

    def see(self, pi):
        cpu = pi.get('cpuC')
        now = (pi.get('throttled') or {}).get('now')
        if now or (cpu is not None and cpu >= HEAT_ON_C):
            self.on = True
        elif cpu is None or cpu < HEAT_OFF_C:
            self.on = False
        return self.on


class PiHealth(object):
    """The Pi's temperature and throttling, asked at most every PI_EVERY.

    Four fields, each figure beside the reason it is missing when it is: a
    null that does not say why reads the same as a Pi that was never asked.

    ...and `guard`, the heat guard, shown each sample as it is taken, so it
    judges the very figures the beat and the `seen` row carry, whichever of
    them asked. Not one of the four: the row is the journal's, and the guard's
    state rides the beat alone.
    """

    def __init__(self, every=PI_EVERY, temp=cpu_temp, throttle=throttling):
        self.every, self._temp, self._throttle = every, temp, throttle
        self.at = None
        self.last = None
        self.guard = HeatGuard()

    def sample(self, now):
        if self.at is None or now - self.at >= self.every:
            cpu, cpu_why = self._temp()
            thr, thr_why = self._throttle()
            self.last = {'cpuC': cpu, 'cpuCWhy': cpu_why,
                         'throttled': thr, 'throttledWhy': thr_why}
            self.at = now
            self.guard.see(self.last)
        return dict(self.last)


def uptime(path='/proc/uptime'):
    """Seconds since the machine booted, or None where there is no such file.

    On the start row because "started with no stop before it" has two causes
    that want different answers: the scanner died and the Pi carried on (a
    crash, or server.js's SIGKILL of a wedged camera), or the Pi itself went
    down — its power cut, or a reboot. A start soon after boot is the second;
    one hours into the Pi's uptime is the first. Read off the kernel rather than
    the wall clock, which on a Pi boots in 1970 and cannot say how long anything
    has been running until the network arrives.
    """
    try:
        with open(path) as fh:
            return int(float(fh.read().split()[0]))
    except (OSError, ValueError, IndexError):
        return None


class Held(object):
    """A word that only changes once the new one has lasted.

    `quick` names the words that are taken at once: the good news. A phone
    back in view or a fix back is true the moment it is seen, and holding it a
    minute would leave the panel complaining about a GPS that is working. Bad
    news has to last `hold` seconds first. Each change is at least `hold` apart
    from the next bad one, so however a state flickers the journal gains at
    most two rows a `hold`.

    `holds` gives a bad word a hold of its own, for a state with two kinds of
    bad news that are not equally patient — the camera's, where a stalled feed
    is said far sooner than a dark box.
    """

    def __init__(self, word, hold, quick=(), holds=None):
        self.word = word
        self.hold = hold
        self.quick = quick
        self.holds = holds or {}
        self._next = None
        self._since = None

    def update(self, raw, now):
        """Returns (new word, seconds it had lasted) on a change, else None."""
        if raw == self.word:
            self._next = None
            return None
        if raw != self._next:
            self._next, self._since = raw, now
        lasted = now - self._since
        if raw in self.quick or lasted >= self.holds.get(raw, self.hold):
            self.word, self._next = raw, None
            return raw, lasted
        return None


class Repeats(object):
    """Whether each preview frame is the same picture as one of the few before
    it — the stall watch's evidence. See STALL_SAY.

    Keeps copies of the last `keep` frames, so a camera stuck handing back its
    ring of buffers is caught as surely as one handing back a single frame.
    Twice CAMERA_BUFFERS and not once, because the loop does not see every
    capture: a read pairs its frame with the next one (`pair_reads`), and that
    capture never comes past here. A buffer whose last turn was a read's
    partner was last seen two turns back, so with only four kept, every read
    on the verify beat broke the run of repeats and the hold began again.
    Measured on the suites' fake camera handing back four buffers in turn, at
    the real STALL_SAY, three runs each: one kept or four, no stall said in
    the 12.5 seconds of it; eight kept, the row written 6.8 to 7.1 seconds
    after the freeze every time.

    A sparse sample of each is compared first, as bytes: on a working camera
    it differs at once, so a whole frame is only compared when its sample
    matched, which is to say on a stall. Measured on the development machine,
    two sets of nine runs of 4,000 frames each: on frames that differed from
    the last in half their pixels, medians of 0.026 and 0.025ms a frame against
    the last eight, where the last one alone, compared whole and copied as it
    was, took 0.027 and 0.028ms; on a stall, where every compare matches and
    the frame's extremes are asked as well, 0.134 and 0.127ms against 0.068
    and 0.069ms — paid only while there is nothing to read.
    """

    # One pixel in this many each way: 1,200 of the preview's 307,200.
    SAMPLE = 16

    def __init__(self, keep=2 * CAMERA_BUFFERS):
        self.keep = keep
        self._kept = []
        self._samples = []
        self._slot = 0

    def seen(self, luma):
        """True when `luma` is a frame already handed over, byte for byte, and
        one that would show a sensor's noise if there were any — see STALL_SAY.
        Keeps a copy of it either way."""
        sample = luma[::self.SAMPLE, ::self.SAMPLE].tobytes()
        same = any(old == sample and np.array_equal(luma, self._kept[i])
                   for i, old in enumerate(self._samples))
        if same:
            # Every pixel on one of the frame's two extremes — flat, or black
            # clamped against full well — leaves noise nowhere to show.
            lo, hi = int(luma.min()), int(luma.max())
            same = bool(np.any((luma > lo) & (luma < hi)))
        if len(self._kept) < self.keep:
            self._kept.append(luma.copy())
            self._samples.append(sample)
        else:
            # Into the oldest copy's own memory, rather than a new one a frame.
            # A copy and not the frame itself: `luma` may be a view onto the
            # request's buffer, which goes back to the camera.
            np.copyto(self._kept[self._slot], luma)
            self._samples[self._slot] = sample
            self._slot = (self._slot + 1) % self.keep
        return same


def sight_now(frozen, lit, reading):
    """What the camera can see this moment, unsettled: 'stalled', 'dark' or
    'seeing'. See STALL_SAY and the note under it.

    `frozen`: Repeats.seen() said this frame had been handed over before.
    `lit`: AutoGain's `lit` where nothing tracks the corners, else None — the
    tracker's rigs answer this with the phone rows. `reading`: a read was
    handed over since this was last asked, so the rig was looking — see the
    note under STALL_SAY for which reads those are.

    A stall outranks the dark: a frozen picture is dark or lit as it happened
    to be when it froze, and says nothing about the box now.
    """
    if frozen:
        return 'stalled'
    if lit is False and not reading:
        return 'dark'
    return 'seeing'


class UpDown(object):
    """The rig's `kind: 'up'` rows: start, stop, the phone, the GPS.

        {v, kind: 'up', id: 'up-<run>-<n>', seq: 1, at, about, state, ...}

    `about` is 'rig', 'phone', 'gps' or 'camera', so 'lost' on its own is never
    asked to say what was lost.

      rig    start   once the loop is about to run, with `gps` (whether --gps
                     was given) and `uptime` (seconds since the Pi booted)
             stop    on a clean exit: ctrl-c, the supervisor's SIGTERM, or the
                     display window closed. NOT on a crash and not on SIGKILL,
                     which is the point — a start with no stop before it marks
                     a run that ended without one, and `uptime` on that start
                     says whether the Pi went down with it.
             restart the loop has gone quiet so the supervisor kills and
                     restarts it, with `why`: a read stuck past READ_STUCK_S,
                     or a camera stalled (at most once in STALL_AGAIN). The
                     SIGKILL that follows leaves no stop, so this is the row
                     that says it was asked for.
      phone  gone    the camera has not found the screen for PHONE_HOLD
             back    it has again
      gps    ok / stale / lost, settled over GPS_HOLD, with `ageSeconds` (the
                     newest fix's age) and `why` (gps.py's own error, if any)
      camera stalled the same picture, byte for byte, as one of the frames
                     before it, for STALL_SAY
             dark    nothing the gain counts as a lit screen in the box for
                     PHONE_HOLD, with nothing tracking the corners; with
                     `bright`, what it read. Not "no phone": a dim one reads
                     the same — see the note under STALL_SAY
             seeing  either of those over

    Every change carries `forSeconds`: how long the new state had already
    lasted when it was written, so a 'gone' says when it really began.

    Nothing about the phone is written while nothing is looking for it — a rig
    run with --no-track, or one reading a box drawn by hand. The last phone row
    then stands until the stop, so a box drawn while the phone was out of sight
    leaves a 'gone' with no 'back'; the stop row is where that run's account
    ends.

    `at` is the clock's, as it is on every other row, and the id is not built
    from it. The sync keys on id and seq, so two rows sharing an id are one row
    to the copy at home and the second is dropped there with nothing saying
    so; the id is therefore this run's own token and the row's number in the
    run, which no clock can make repeat. It was `up-<at>`, with `at` pushed
    past the last row's to keep the ids apart, and both halves were wrong:
      * the push held `at` at the run's high-water mark after NTP stepped a
        fast clock back — the seven hours AUDITS.md "The clock" records as
        real. Measured: a 'gps stale' row written three hours after a 7h step
        back was stamped 3.98 hours from when it happened, on the rows whose
        whole purpose is to say when the rig failed;
      * and it kept ids apart within one run only. Replayed: two boots that
        reached the loop in the same millisecond before NTP, 25.123s after
        1970, both wrote 'up-25123', and the copy at home keeps the first row
        with an id and drops the second. How often two boots land in one
        millisecond was not measured; with the token it does not matter.
    `n` also orders a run's rows when the clock cannot: a start row stamped
    before NTP and the rows after it are still 1, 2, 3.
    """

    def __init__(self, journal, asked_gps, phone_hold=None, gps_hold=None,
                 stall_say=None):
        self.journal = journal
        # Read here rather than as defaults, so a check that shortens the module
        # constant reaches the loop's own instance.
        phone_hold = PHONE_HOLD if phone_hold is None else phone_hold
        self.phone = Held('back', phone_hold, quick=('back',))
        # What the camera can see. A box too dark to be sure of seeing a card
        # arrive in, on a rig with nothing tracking it, may be a phone gone or
        # one turned down, so it waits as long as a phone does; a stall is said
        # far sooner — see STALL_SAY.
        self.camera = Held('seeing', phone_hold, quick=('seeing',),
                           holds={'stalled': STALL_SAY if stall_say is None
                                  else stall_say})
        # When the camera's word last changed, on the caller's clock, so the
        # restart can say how long a stall had lasted.
        self.camera_since = None
        # None, not 'ok', before the phone has said anything: the beat would
        # otherwise say 'ok' about a GPS that has not produced a position, and
        # the page and the status endpoint would both repeat it.
        self.gps = Held(None if asked_gps else 'off',
                        GPS_HOLD if gps_hold is None else gps_hold, quick=('ok',))
        self.gps_age = None
        # Random rather than read off the machine: the pid repeats across
        # boots, and the clock is the thing this is here to stop trusting.
        # 48 bits: a run a day for thirty years is 10,980 runs, and the
        # chance any two of them share a token is about 1 in 4.7 million.
        self.run = os.urandom(6).hex()
        self._n = 0

    def _write(self, about, state, **extra):
        if self.journal is None:
            return False
        self._n += 1
        row = {'v': JR.SCHEMA, 'kind': 'up', 'id': 'up-%s-%d' % (self.run, self._n),
               'seq': 1, 'at': JR.now_ms(), 'about': about, 'state': state}
        row.update(extra)
        return self.journal.append(row)

    def start(self, gps, booted):
        return self._write('rig', 'start', gps=bool(gps), uptime=booted)

    def stop(self):
        return self._write('rig', 'stop')

    def restart(self, why):
        return self._write('rig', 'restart', why=why)

    def watch(self, now, lost, gps, sight='seeing', bright=None):
        """`lost`: the tracker's word, or None with nothing tracking.
        `gps`: gps_now()'s (word, ageSeconds, why). `sight`: sight_now()'s
        word, and `bright` the box's brightness to put on a 'dark' row.

        Returns the camera's new word when it changed, else None."""
        if lost is not None:
            moved = self.phone.update('gone' if lost else 'back', now)
            if moved:
                self._write('phone', moved[0], forSeconds=int(moved[1]))
        word, age, why = gps
        self.gps_age = age
        moved = self.gps.update(word, now)
        if moved:
            self._write('gps', moved[0], forSeconds=int(moved[1]),
                        ageSeconds=age, why=why)
        moved = self.camera.update(sight, now)
        if not moved:
            return None
        self.camera_since = now - moved[1]
        extra = {'forSeconds': int(moved[1])}
        if moved[0] == 'dark':
            extra['bright'] = None if bright is None else round(bright, 1)
        self._write('camera', moved[0], **extra)
        return moved[0]

    def beat(self, fix=None):
        """What the heartbeat says about the GPS: the settled word, the
        newest fix's age as it is now, and `fix` — beat_fix()'s newest
        position with its quality and the gate's answer, or None."""
        return {'state': self.gps.word, 'ageSeconds': self.gps_age, 'fix': fix}

    def blind(self):
        """What the heartbeat says about the camera: None while it can see,
        else the settled word, 'stalled' or 'dark'."""
        return None if self.camera.word == 'seeing' else self.camera.word


def screen_address(shot, text):
    """(an_offer, address, sheet) for one frame: whether it is to be taken for
    an offer — digest()'s payout-or-merchant test — the address find_address
    gave it, and the address on Uber's opened navigation sheet (OP.sheet_dropoff),
    None on a frame taken for an offer.

    ONE EXCEPTION to the merchant arm. Uber's navigation bar, "6 min © 1.7
    mi", is minutes and miles like a card's leg, and parse() reads the lines
    under it as the leg's place: 10 of the 12 Oct shift's 179 reads typed
    uber.nav came out with a place and no payout, every one with the bar on
    it, 7 of them the opened sheet. So on a frame typed uber.nav with no
    payout, the text is parsed again with the bar's lines out
    (OP.nav_without_bar), and only if THAT still finds a payout or a place is
    the frame an offer; its address is the bar-free parse's, so the bar can
    never be read into the street ("7 mi - 2950 …"). A payout always makes an
    offer, and a screen typed anything else keeps both arms: an offer card is
    typed by its own furniture ahead of navigation (OP.screen_type). Measured
    on the journal copied with the 12 Oct shift: over its 10,991 offer rows'
    texts and their 36,118 frames this changes the answer for none (8 of them
    type uber.nav, and every one still reads as an offer), and for exactly
    the 10 screen rows above."""
    an_offer = shot.get('pay') is not None or bool(shot.get('places'))
    address = shot.get('address')
    if an_offer and shot.get('pay') is None \
            and OP.screen_type(text or '')['screen'] == 'uber.nav':
        bare = OP.parse(OP.nav_without_bar(text))
        if bare.get('pay') is None and not bare.get('places'):
            an_offer, address = False, bare.get('address')
    return an_offer, address, (None if an_offer else OP.sheet_dropoff(text))


def screen_said(text):
    """What a screen says about WHOSE an address read off it is: {'app',
    'screen', 'expectedBy'} — the app and screen type (OP.screen_type), and the
    one "Expected by" time the screen prints, minutes since midnight, or None
    where it prints none or more than one (a Trip Planner lists a time per
    stop, and which is this address's is the assembler's question). Uber's
    navigation bar prints the stop's time ("4 min · 0.6 mi / Expected by 8:20
    PM"); with two orders in the car server.js holds it against each card's
    "Deliver by" (Assemble.attribute, the deadline cue)."""
    kind = OP.screen_type(text or '')
    times = set()
    for line in re.split(r'[\r\n]+', text or ''):
        m = OP.PLANNER_EXPECTED.search(OP.normalize(line))
        if m:
            due = OP.time_of_day(m.group(1), m.group(2), m.group(3))
            if due is not None:
                times.add(due)
    return {'app': kind['app'], 'screen': kind['screen'],
            'expectedBy': times.pop() if len(times) == 1 else None}


def emit_dropoff(address, ms=None, asked=True, labelled=False, text=None):
    """The destination, once it has been read off the screen.

    Its own line, like the offer id and for the same reason: it is not part of a
    verdict and must not be able to stand in for one. Nothing about this reading
    says anything about an offer — there is no offer on the screen, there is a
    navigation app — so it carries no `ready`, no rate and no pay.

    Emitted once per press. The window stays open afterwards only until an
    address is found; a second one arriving would be the driver having moved on
    to a different screen, and the first is the one they asked about.
    """
    # A window that closed with nothing on it, which is an answer and not a
    # silence. `None` rather than a blank address: every field below would be
    # null anyway, and a caller reading `line` would have to tell "the rig
    # found nothing" from "the rig read an address with no line in it", which
    # are different things. The shape stays the same so the receiving end has
    # one branch to add and not a second message to learn.
    if address is None:
        print(json.dumps({'dropoff': {
            'line': None, 'street': None, 'city': None, 'state': None,
            'zip': None, 'found': False, 'asked': bool(asked), 'ms': ms,
            'at': int(time.time() * 1000)}}), flush=True)
        return
    print(json.dumps({'dropoff': {
        'found': True,
        # What to show and what to store. `city` and `zip` are what the
        # geography is actually decided on — see Advice.sameArea — and `line` is
        # what the driver reads to tell whether the scan worked.
        'line': address.get('line'),
        'street': address.get('street'),
        'city': address.get('city'),
        'state': address.get('state'),
        'zip': address.get('zip'),
        # ...and the place the phone printed for the stop, where the read
        # gave one (OP.sheet_dropoff's `place`, "<Something> Parking Deck");
        # None from find_address, which reads none. Carried to the hold
        # (assemble.js file) because the owner decided on 17 Oct that the
        # held end is searched by it when the NucBox has the street and not
        # the door (server.js searchHeldPlace); before that it was shown and
        # never searched, and rode only on the sighting.
        'place': address.get('place') or None,
        # Whether the driver ASKED for this one, or the rig simply saw it.
        #
        # The two are different claims and the receiving end treats them
        # differently: a press is the driver saying "this screen is the
        # destination", and it overrules whatever the card said. An unprompted
        # sighting is the rig filling in a blank, and it may only fill a blank
        # — see server.js, which will not let one overwrite a destination the
        # card itself named.
        'asked': bool(asked),
        # 'dropoff' when nobody asked and the screen printed this address under
        # a Dropoff label in its own stop block (digest()); None otherwise. A
        # press needs no label, so it never carries one. The assembler lets a
        # labelled sighting replace the card's own end on the held order, and
        # nothing else. A Trip Planner's addresses never come this way: they
        # are the assembler's to file, off the sighting (emit_sighting).
        'labelled': 'dropoff' if labelled and not asked else None,
        'ms': ms,
        # ...and what the screen says about whose it is, for server.js to
        # attribute it with two orders in the car: see screen_said.
        **screen_said(text),
        'at': int(time.time() * 1000)}}), flush=True)


def emit_popup(popup, at=None):
    """DoorDash's place popup, read off the screen while a card is being
    screened: the address the driver tapped a stop on the card to show, and
    which stop it was (OP.place_popup).

    Its own line, for the reason the dropoff line has one: it carries no
    verdict and must not stand in for one. And not a dropoff line, because
    that line's road ends on the order in the car when there is one, and this
    is never about the order in the car: server.js files it onto the card on
    the slot or nowhere (Assemble.popup). `at` is when the frame was TAKEN,
    which is what "read after the card appeared" is asked of. The store's
    name rides along because the server matches it to the card's pickup; no
    customer's name is read."""
    print(json.dumps({'popup': {
        'role': popup.get('role'), 'name': popup.get('name'),
        'line': popup.get('line'), 'street': popup.get('street'),
        'city': popup.get('city'), 'state': popup.get('state'),
        'zip': popup.get('zip'), 'app': 'doordash', 'screen': 'dd.placePopup',
        'at': at if at is not None else int(time.time() * 1000)}}), flush=True)


# How long an app's completion screen must have been gone before it is said
# again: the screen stays up until the driver taps on, and is read on every
# beat it stays. Chosen, not measured — the one screen on record was read four
# times in a second — and the server keeps its own quiet window as well
# (SCREEN_DROP_QUIET_MS), so a flicker cannot put down a second order.
DELIVERED_GAP_S = 60.0


class DeliveredSaid(object):
    """Whether a completion screen read now is a new one to say, by app: yes
    the first time, and after DELIVERED_GAP_S with none of that app's read.
    Every read of it moves the clock on, so one screen left up for ten minutes
    is said once."""

    def __init__(self):
        self.last = {}

    def fresh(self, app, now):
        was = self.last.get(app)
        self.last[app] = now
        return was is None or now - was >= DELIVERED_GAP_S


def emit_delivered(said, at=None):
    """The delivery app's own screen from after a delivery
    (OP.delivered_screen): its app and screen, the pay it printed and the
    customer it named, either None where it printed none.

    Its own line, for the reason the popup line has one: it carries no verdict
    and is no offer, whatever payout its "This offer $8.95" reads as. server.js
    puts the order of that app in the car down on it, or opens the Drop
    chooser, behind `"screenDrop": true` (deliveredArrived); never an accept.
    `at` is when the frame was TAKEN: a screen read before an order's Took is
    not that order's."""
    print(json.dumps({'delivered': {
        'app': said.get('app'), 'screen': said.get('screen'),
        'pay': said.get('pay'), 'name': said.get('name'),
        'at': at if at is not None else int(time.time() * 1000)}}), flush=True)


def emit_planner(stops, keep=False, ms=None, asked=True, at=None):
    """Uber's Trip Planner, read off the whole screen because ⌖ was pressed.

    Its own line, for the reason a dropoff is: the screen is a list of stops,
    not an offer, so it carries no `ready`, no rate and no pay and can neither
    replace a verdict nor stand in for one. `stops` is OP.find_planner's list,
    in the order the screen gave it — every stop, the ones whose fields did not
    read included, so the panel shows what is there rather than what parsed.

    No `unfiled` any more: whether a planner gives the order in the car its
    end, and the word for why not, is the assembler's (assemble.js,
    plannerDestination), decided off the sighting this read sent just before
    this line. server.js puts the reason on this line before the panel sees
    it, so the panel still says the one reason that was decided rather than
    working out its own. `at` is that read's, the same stamp the sighting
    carries, which is how the server pairs the two.

    `keep` is whether the journal may hold the stops: names and front doors,
    which `"keepPlaces": false` and --no-journal both say the record is not to
    have. server.js writes the planner row only when this is true. The panel
    is shown the stops either way: showing is not recording.

    `asked` is on the line so a row written from it says on its face whether
    it answered a press, as a dropoff mark does: True under ⌖, False for the
    read the rig makes on its own while an order is held (`screen_auto` in
    main()).
    """
    print(json.dumps({'planner': {'stops': stops,
                                  'keep': bool(keep), 'asked': bool(asked), 'ms': ms,
                                  'at': int(time.time() * 1000) if at is None else at}}),
          flush=True)


def planner_stops(stops):
    """find_planner's stops as the planner line and every rule that files have
    always had them: the headed stops only, without `partial`. None for None.

    find_planner now also keeps the stop a page begins in the middle of (kind
    None) and marks the stops a page edge cut. Those are for the sighting,
    which the assembler stitches pages from; handed to the log or the panel's
    "▸ Dropoff" line, a stop of no kind would be a None to join or a pickup
    drawn as a dropoff. So the planner line is given exactly what it was given
    before, and the sighting is given all of it.

    ...and not the dropoff whose header the reader lost (`partial: 'header'`,
    OP._planner_lost_dropoff): no header printed its kind, and only the
    assembler, on the held card's witness, may take it for one."""
    if stops is None:
        return None
    return [{k: v for k, v in s.items() if k != 'partial'}
            for s in stops if s.get('kind') and s.get('partial') != 'header'] or None


# The fields of a stop on a sighting, in this order, whichever screen it came
# off: a planner's stop has them all; an address off any other screen has the
# address, its label and the screen's one "Expected by", and None for the rest.
SIGHTING_STOP = ('kind', 'orders', 'name', 'place', 'expectedBy', 'street', 'city',
                 'state', 'zip', 'line', 'partial', 'label')


def sighting_stops(text, stops, address, sheet=None):
    """The stops a sighting carries, and the page's two ends, as
    (stops, {'top', 'bottom'}).

    Off a planner, `stops` is find_planner's whole list — the cut stops
    included, each saying where it was cut — and each stop's `label` is the
    word its header printed, which is its kind; the stop above the first
    header printed none. The page's ends are planner_ends'.

    Off any other screen, the one address the frame gave (`address`, already
    None where the frame carried a payout or a merchant: digest()'s `an_offer`
    refusal, unchanged), labelled by the stop label in front of it
    (OP.address_stop). It is TYPED a pickup under a Pickup label and only a
    pickup, a dropoff only where OP.address_under_dropoff says it sits in a
    Dropoff label's own block, and otherwise of no kind. No page ends: only
    the planner's list has them.
    """
    if stops is not None:
        top, bottom = OP.planner_ends(text)
        out = []
        for s in stops:
            one = {k: s.get(k) for k in SIGHTING_STOP}
            one['label'] = s.get('kind')
            out.append(one)
        return out, {'top': top, 'bottom': bottom}
    # Uber's opened navigation sheet, its address over "Dropoff type" with the
    # customer's name above (OP.sheet_dropoff; `sheet` is None wherever
    # digest() took the frame for an offer). The owner's decision: that is the
    # dropoff, typed so, its label the words the sheet printed.
    if sheet:
        one = {k: sheet.get(k) for k in SIGHTING_STOP}
        one['kind'] = 'dropoff'
        one['label'] = 'dropoff type'
        one['expectedBy'] = screen_said(text)['expectedBy']
        return [one], {'top': None, 'bottom': None}
    if not address:
        return [], {'top': None, 'bottom': None}
    label = OP.address_stop(text)
    one = {k: address.get(k) for k in SIGHTING_STOP}
    one['kind'] = ('pickup' if label == 'pickup' else
                   'dropoff' if OP.address_under_dropoff(text) else None)
    one['label'] = label
    # ...and the one "Expected by" the screen prints, as the dropoff line
    # carries it (screen_said): Uber's navigation bar prints the stop's time,
    # and with two orders in the car it is the deadline cue the assembler
    # attributes a navigation destination by.
    one['expectedBy'] = screen_said(text)['expectedBy']
    return [one], {'top': None, 'bottom': None}


def order_count(stops):
    """How many orders a planner's dropoffs say they are, summed — or None
    when there is no dropoff on it, or one whose count did not read. A
    count the screen did not finish saying is not a count."""
    drops = [s for s in stops if s.get('kind') == 'dropoff']
    if not drops or any(not isinstance(s.get('orders'), int) for s in drops):
        return None
    return sum(s['orders'] for s in drops)


def emit_sighting(text, stops, address, asked, whole, keep=False, at=None, sheet=None):
    """Stage 2 of the multi-order design: what a whole-screen read or a planner
    read SAW, typed by its screen, and nothing more.

        {sighting: {at, asked, whole, titled, laidOut, framed, footed, app, screen,
                    page: {top, bottom},
                    stops: [{kind, orders, name, place, expectedBy, street,
                             city, state, zip, line, partial, label}],
                    orderCount, keep}}

    Stage 3: THE TRIP PLANNER IS FILED FROM THIS LINE. server.js counts it by
    `screen` and hands it to the assembler (assemble.js), which stitches a
    planner's pages and decides whether its one dropoff is the order's end —
    the decision planner_destination and planner_lone_dropoff made here
    before. This side only types what it saw: `titled` is whether the "Trip
    Planner" title is on the screen, which an unpressed planner read needs to
    be filed, and `laidOut` whether its layout proves it a planner with the
    title misread (OP.planner_laid_out), which stands in for it, and `framed`
    whether a Pickup header opens the read with the foot of the screen under
    it (OP.planner_framed), which the assembler asks of a single trip's page
    whose title scrolled off, and `footed` whether the read is the trip's last
    stop block, its header cropped off, with the list's foot straight under
    it (OP.planner_foot), which the assembler files as a dropoff with one
    order held, card box or whole. The server still writes no journal row from it and broadcasts it
    to no one; an address filed off it goes to the panel as a dropoff line
    does.

    The frame-local refusals stay here, where the frame is: `address` is the
    one digest() already refused on a payout or a merchant, and an address
    under a Pickup label is typed a pickup only (sighting_stops). `keep` is
    emit_planner's: whether the record may hold names and doors, said so a
    later stage that does keep them has the answer the rig had.
    """
    print(json.dumps({'sighting': sighting(text, stops, address, asked, whole,
                                           keep=keep, at=at, sheet=sheet)}), flush=True)


def sighting(text, stops, address, asked, whole, keep=False, at=None, sheet=None):
    """The sighting line's body, built: see emit_sighting, which prints it."""
    kind = OP.screen_type(text)
    listed, page = sighting_stops(text, stops, address, sheet)
    return {'at': int(time.time() * 1000) if at is None else at,
            'asked': bool(asked), 'whole': bool(whole),
            'titled': OP.planner_titled(text),
            'laidOut': OP.planner_laid_out(text),
            'framed': OP.planner_framed(text),
            'footed': OP.planner_foot(text),
            'app': kind['app'], 'screen': kind['screen'], 'page': page,
            'stops': listed,
            'orderCount': order_count(stops) if stops is not None else None,
            'keep': bool(keep)}


# Uber's "Early look • Order in progress" badge: an offer shown while the
# driver is still on a job, whose distance may be counted from where that job
# ends rather than from the car. Said on the offer line so the next thing to
# measure a pin against a card's own distance can refuse these as a yardstick.
#
# Measured over the week's 1,166 offers, every frame text in `scans` and the
# row's `text`: 27 offers carry it, in 102 of their 105 frames. The OCR spells
# it "Early look", "Early took" and "Arder in progress", and the two halves
# each miss on some frame that the other catches (25 and 26 alone, 27 either);
# this pattern finds all 27 and fires on no other offer that week.
#
# Not in parse(), deliberately: nothing judges a card on it, the offer line is
# its only reader, and a parse() field is a field both ports and the shared
# corpus must carry. And `False` means only that no frame the reader was given
# said it: the Est. delivery card snapped on 10 Oct was an Early look card whose
# crop began below the badge.
EARLY_LOOK = re.compile(r'\bearly\s*[lt]ook\b|\b[oa]rder\s*in\s*progress\b', re.I)


def says_early_look(parsed):
    """Whether any text this reading was built from carries the badge — the
    frames the window kept as well as its own, since one frame of five can be
    the one that caught it."""
    texts = list(parsed.get('scans') or []) + [parsed.get('text') or '']
    return any(EARLY_LOOK.search(t or '') for t in texts)


# A card for more than one order: "(2 orders)" after DoorDash's pickup, the
# "+1 order" a stacked add-on shows, any count of two or more before "orders".
# Said on the offer line beside `legs`, for the one reader that needs it: the
# assembler files a Trip Planner's lone dropoff off a list whose end is below
# the screen only onto a held order whose card was ONE order on ONE leg — see
# plannerLoneDropoff in assemble.js. A card that says nothing of orders is not
# multi; a read that lost the words is why `legs` is asked as well.
MULTI_ORDER = re.compile(r'\+\s*\d+\s*orders?\b|\b(?:[2-9]|[1-9]\d)\s*orders\b', re.I)
# ...and a card for more than one CUSTOMER, which is a different thing:
# DoorDash's "Multiple dropoffs (2 stops)". "Drop off 2 orders" under one
# "Customer dropoff" is two orders to one door and is not this. Said on the
# offer line for the one reader that needs it: a customer's place popup is
# filed onto the card only when the card has one customer to be about
# (Assemble.popup).
MANY_DROPOFFS = re.compile(r'multiple\s*drop\s*-?\s*offs', re.I)


def says_many_dropoffs(parsed):
    """Whether any text this reading was built from names more than one
    dropoff. Every frame the window kept, as says_early_look."""
    texts = list(parsed.get('scans') or []) + [parsed.get('text') or '']
    return any(MANY_DROPOFFS.search(t or '') for t in texts)


def says_multi_order(parsed):
    """Whether any text this reading was built from marks the card as more
    than one order. Every frame the window kept, as says_early_look."""
    texts = list(parsed.get('scans') or []) + [parsed.get('text') or '']
    return any(MULTI_ORDER.search(t or '') for t in texts)


# --- DoorDash's map label ---------------------------------------------------
#
# The owner, 27 Oct: "reading the doordash icons still doesnt seem to work if a
# best guess can be used for the map". A DoorDash card whose dropoff reads only
# "Customer dropoff" has, on the map above it, a white-on-black rounded label
# naming the customer's street with its house number ("<n> <Name> Ave NE") at
# the route's end. The card box never reads it. This does, once per offer,
# after the card's own reading and its offer line are out:
#
#   1. the screen box warped straight (PL.warp, the same corners the read
#      used), and the band of it above the card: MAP_LABEL_BAND, down to the
#      drawn card box's top where one sits inside that band;
#   2. a light map, or nothing: the band's mean grey under MAP_LABEL_DIM (low
#      light, a dark-mode map) or more than MAP_LABEL_DARK_SHARE of it near
#      black, and the label is not looked for;
#   3. near-black, unsaturated pixels (a red route chip is not one), opened to
#      drop the route's thin line, each blob's holes filled (the white text),
#      and the rows of it wide enough to be a pill kept: a box at least
#      MAP_LABEL_ASPECT times as wide as it is tall, of the label's height
#      (MAP_LABEL_TALL), with white text inside;
#   4. each box deskewed (the phone sits a degree or two off square), cut in
#      from its rounded ends, inverted to dark text on light, and read by
#      tesseract as ONE LINE (psm 7); OP.map_label decides whether it is a
#      street, refusing the app's own words and the card's own store;
#   5. the first box that reads as one is the answer, biggest first, at most
#      MAP_LABEL_MOST boxes, and never past MAP_LABEL_CAP_S of wall clock.
#
# A box that runs into the screen's left edge is `clipped`: its digits can be
# the tail of a longer number, so the street goes alone. One that runs into the
# right edge is not read: its street type is what was cut.
#
# On its own thread (MapLabels), so the camera loop never waits on it and the
# card's reader never shares its time: the card's verdict is out before this
# starts. A GUESS FOR DRAWING ONLY — see emit_offer's `mapLabel`.
MAP_LABEL_BAND = (0.06, 0.62)
MAP_LABEL_HEIGHT = 1400          # the screen box warped to this many rows
MAP_LABEL_DIM = 90               # mean grey of the band below which: not looked for
MAP_LABEL_DARK_SHARE = 0.35
MAP_LABEL_BLACK = 80             # a label's grey is under this...
MAP_LABEL_CHROMA = 40            # ...and its colour's spread (a red chip is not one)
MAP_LABEL_TALL = (0.018, 0.08)   # a label's height, of the screen box's
MAP_LABEL_ASPECT = 2.5
MAP_LABEL_WIDE = 0.15            # ...and its width, of the screen box's
MAP_LABEL_MOST = 3
MAP_LABEL_CAP_S = 1.5
MAP_LABEL_OCR = '--oem 1 --psm 7 -c tessedit_do_invert=0'
MAP_LABEL_TEXT_ROWS = 70         # a label's box, scaled to this many rows to read


def map_band(frame, geom, height=MAP_LABEL_HEIGHT):
    """The map above the card, straightened: a BGR image, or None with no
    corners or a whole-screen read. The band's bottom is the drawn card box's
    top where that sits inside MAP_LABEL_BAND, else the band's own."""
    if frame is None or geom is None or getattr(geom, 'quad', None) is None \
            or getattr(geom, 'whole', False):
        return None
    q = np.asarray(geom.quad, dtype=np.float32).reshape(4, 2)
    if not np.all(np.isfinite(q)):
        return None
    screen = PL.warp(frame, q, height=height)
    if screen.ndim == 2:
        screen = cv2.cvtColor(screen, cv2.COLOR_GRAY2BGR)
    top, bottom = MAP_LABEL_BAND
    roi = getattr(geom, 'roi', None)
    if roi and top + 0.2 < float(roi[1]) < bottom:
        bottom = float(roi[1])
    h = screen.shape[0]
    return screen[int(top * h):int(bottom * h)]


def _runs(flags):
    out, start = [], None
    for i, v in enumerate(list(flags) + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((start, i))
            start = None
    return out


def map_label_boxes(band, screen_h):
    """The dark rounded label boxes in `band`, biggest first:
    [(x, y, w, h)], or [] for a band too dim or too dark to hold one."""
    if band is None or band.size == 0:
        return []
    # Grey as the brightest channel, and colour as the spread between the
    # channels in grey levels rather than HSV's saturation, which a tinted
    # picture's near-black pixels make large for nothing.
    hi_c = band.max(axis=2)
    grey = hi_c
    chroma = hi_c.astype(np.int16) - band.min(axis=2)
    dark = ((grey < MAP_LABEL_BLACK) & (chroma < MAP_LABEL_CHROMA)).astype(np.uint8)
    if float(grey.mean()) < MAP_LABEL_DIM or float(dark.mean()) > MAP_LABEL_DARK_SHARE:
        return []
    H, W = band.shape[:2]
    k = max(3, int(round(screen_h * 0.005))) | 1
    opened = cv2.morphologyEx(dark, cv2.MORPH_OPEN,
                              cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    found = cv2.findContours(opened, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = found[0] if len(found) == 2 else found[1]
    lo, hi = MAP_LABEL_TALL[0] * screen_h, MAP_LABEL_TALL[1] * screen_h
    boxes = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w < MAP_LABEL_WIDE * W or h < lo:
            continue
        filled = np.zeros((h, w), np.uint8)
        cv2.drawContours(filled, [c - [x, y]], -1, 1, -1)
        for r0, r1 in _runs(filled.mean(axis=1) >= 0.45):
            rh = r1 - r0
            if not lo <= rh <= hi:
                continue
            cols = _runs(filled[r0:r1].mean(axis=0) >= 0.5)
            if not cols:
                continue
            c0, c1 = max(cols, key=lambda cc: cc[1] - cc[0])
            bw = c1 - c0
            if bw < MAP_LABEL_ASPECT * rh or bw < MAP_LABEL_WIDE * W:
                continue
            inside = grey[y + r0:y + r1, x + c0:x + c1]
            # White text inside: a black blob with none is a road's shadow
            # or a building, not a label.
            if not 0.04 <= float((inside > 170).mean()) <= 0.6:
                continue
            boxes.append((x + c0, y + r0, bw, rh))
    boxes.sort(key=lambda b: -b[2] * b[3])
    return boxes


def map_label_image(band, box):
    """One label box, deskewed, cut in from its rounded ends and inverted to
    dark text on light, at MAP_LABEL_TEXT_ROWS rows: what tesseract reads."""
    x, y, w, h = box
    H, W = band.shape[:2]
    pad = int(h * 0.3)
    x0, y0, x1, y1 = max(0, x - pad), max(0, y - pad), min(W, x + w + pad), min(H, y + h + pad)
    grey = cv2.cvtColor(band[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    dark = (grey < MAP_LABEL_BLACK).astype(np.uint8)
    found = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = found[0] if len(found) == 2 else found[1]
    angle, cx, cy, bw, bh = 0.0, x - x0 + w / 2.0, y - y0 + h / 2.0, float(w), float(h)
    if contours:
        (rx, ry), (rw, rh), ra = cv2.minAreaRect(max(contours, key=cv2.contourArea))
        if rw < rh:
            rw, rh, ra = rh, rw, ra + 90
        if ra > 45:
            ra -= 90
        if ra < -45:
            ra += 90
        if abs(ra) <= 8 and rh <= 1.4 * h:
            angle, cx, cy, bw, bh = ra, rx, ry, rw, rh
    if angle:
        m = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)
        grey = cv2.warpAffine(grey, m, (grey.shape[1], grey.shape[0]),
                              borderMode=cv2.BORDER_REPLICATE)
    cut_x, cut_y = bh * 0.3, bh * 0.12
    a0, a1 = int(max(0, cx - bw / 2 + cut_x)), int(min(grey.shape[1], cx + bw / 2 - cut_x))
    b0, b1 = int(max(0, cy - bh / 2 + cut_y)), int(min(grey.shape[0], cy + bh / 2 - cut_y))
    if a1 - a0 < 8 or b1 - b0 < 4:
        return None
    inner = 255 - grey[b0:b1, a0:a1]
    scale = MAP_LABEL_TEXT_ROWS / float(inner.shape[0])
    inner = cv2.resize(inner, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return cv2.copyMakeBorder(inner, 15, 15, 15, 15, cv2.BORDER_REPLICATE)


def read_map_label(frame, geom, store=None, ocr=None, cap_s=MAP_LABEL_CAP_S,
                   clock=time.monotonic):
    """DoorDash's map label off `frame`: {'line', 'clipped', 'raw', 'ms'}, or
    None. `store` is the card's store name and door, which a label may not
    name (OP.map_label). Never raises; never reads past `cap_s`."""
    began = clock()
    ocr = ocr or (lambda image: PL.ocr(image, MAP_LABEL_OCR))
    try:
        band = map_band(frame, geom)
        if band is None:
            return None
        W = band.shape[1]
        for box in map_label_boxes(band, MAP_LABEL_HEIGHT)[:MAP_LABEL_MOST]:
            if clock() - began > cap_s:
                return None
            x, _, w, _ = box
            if x + w >= W - 2:
                continue
            clipped = x <= 2
            image = map_label_image(band, box)
            if image is None:
                continue
            raw = (ocr(image) or '').strip()
            if clock() - began > cap_s:
                return None
            line = OP.map_label(raw, clipped=clipped, store=store)
            if line:
                return {'line': line, 'clipped': clipped, 'raw': raw,
                        'ms': int((clock() - began) * 1000)}
    except Exception:                               # noqa: BLE001 — a guess
        return None
    return None


def wants_map_label(parsed):
    """Is this reading DoorDash's offer card with no customer's door on it —
    the card the map label is read for?"""
    return bool(parsed and parsed.get('pay') is not None and not parsed.get('dropoff')
                and OP.screen_type(parsed.get('text') or '')['screen'] == 'dd.offer')


class MapLabels(object):
    """read_map_label, off the camera's loop and the card's reader: one at a
    time, the newest offer's only, on a thread of its own. `submit` never
    blocks (a label already being read keeps its turn); `take` hands back
    (offer_id, answer) once, answer None for none found. With `threaded`
    False (--no-thread) the read runs in `submit`, capped as ever."""

    def __init__(self, threaded=True, read=None):
        self.read = read or read_map_label
        self.threaded = threaded
        self._work = queue.Queue(maxsize=1)
        self._done = queue.Queue()
        self._asked = set()
        self._thread = None
        if threaded:
            self._thread = threading.Thread(target=self._serve, name='maplabel', daemon=True)
            self._thread.start()

    def submit(self, offer_id, frame, geom, store=None):
        if offer_id is None or offer_id in self._asked:
            return False
        job = (offer_id, frame, geom, store)
        if not self.threaded:
            self._asked.add(offer_id)
            self._done.put(self._job(*job))
            return True
        try:
            self._work.put_nowait(job)
        except queue.Full:
            return False
        self._asked.add(offer_id)
        if len(self._asked) > 64:
            self._asked = set(list(self._asked)[-32:])
            self._asked.add(offer_id)
        return True

    def take(self):
        try:
            return self._done.get_nowait()
        except queue.Empty:
            return None

    def _job(self, offer_id, frame, geom, store):
        try:
            return offer_id, self.read(frame, geom, store=store)
        except Exception:                           # noqa: BLE001
            return offer_id, None

    def _serve(self):
        while True:
            job = self._work.get()
            if job is None:
                return
            self._done.put(self._job(*job))

    def close(self):
        if self._thread is None:
            return
        try:
            self._work.put_nowait(None)
        except queue.Full:
            pass


# --- the map band, kept: data collection only ---------------------------------
#
# The owner, 29 Oct: "Yes add the map saving, fast track to experimental."
# EXPERIMENTAL, AND COLLECTION ONLY. An offline prototype (estimating where an
# order drops off from the route the app draws on its map) needs the map at
# full resolution for offers that were later taken, to be scored afterwards
# against the GPS stop the delivery really made. The 480x360 scene views are
# too small: the pins are 36–44 px in a 1000-row view of the phone and a few
# pixels in the scene view. So once per offer — Uber and DoorDash, an add-on
# popup included — the map band above the card (map_band, the same straightened
# crop the DoorDash label reader uses) is written to <journal dir>/mapbands/
# as <offer id>.jpg with a small .json beside it. Nothing reads it here: no
# panel, no figure, no verdict uses it.
#
#   - AFTER the offer line, on a thread of its own (MapBands), never in the
#     read's way; the warp, the encode and the write all happen there. The
#     encode and write are held to MAP_BANDS_CAP_S: an encode that took longer
#     is dropped rather than written, and the offer is tried again later.
#   - not on a whole-screen read, with no corners, or in low light (the band's
#     mean grey under MAP_BANDS_DIM) — tried again on the card's next read, at
#     most MAP_BANDS_TRIES times; saved once, never again for that offer.
#   - a ring: at most MAP_BANDS_KEEP files and MAP_BANDS_MB megabytes, the
#     oldest (by mtime) going first. ~100–150kB a band, so 400 is ~50MB.
#   - never fatal: a disk error is logged once and the band skipped.
#   - on by default; `"mapBands": false` in the config, or MAP_BANDS=0 in the
#     environment, turns it off. `"mapBandsKeep"` and `"mapBandsMB"` move the
#     caps.
#
# PRIVATE. The map shows street names round a customer's door. The folder is
# in .gitignore, rpi/sync.py sends only journal rows and the config, and the
# server serves none of it — only a 📷 Snap carries the newest band (from the
# last SNAP_BAND_AGE_S) into that snap's folder as map.jpg and map.json, which
# goes where the driver chooses to send that snap.
MAP_BANDS_DIR = 'mapbands'
MAP_BANDS_KEEP = 400
MAP_BANDS_MB = 150
MAP_BANDS_QUALITY = 80
MAP_BANDS_CAP_S = 0.5
# Mean grey under this: no picture of a screen at all (screen off, camera
# blind). Low, because a dark-mode map at night is dark and is still a map.
MAP_BANDS_DIM = 16
MAP_BANDS_MAX_ROWS = 1400        # map_band gives ~780 at MAP_LABEL_HEIGHT; a guard
MAP_BANDS_TRIES = 3
SNAP_BAND_AGE_S = 120


def map_bands_dir(journal_path):
    """Where the map bands go: beside the journal, like the scans."""
    return os.path.join(os.path.dirname(os.path.abspath(journal_path)), MAP_BANDS_DIR)


def map_bands_setting(cfg, env=None):
    """(on, keep, max_bytes, why_off) from the config and the environment."""
    env = os.environ if env is None else env
    cfg = cfg or {}

    def number(key, default):
        v = cfg.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            return v
        return default

    keep = int(number('mapBandsKeep', MAP_BANDS_KEEP))
    max_bytes = int(number('mapBandsMB', MAP_BANDS_MB) * 1024 * 1024)
    flag = str(env.get('MAP_BANDS', '')).strip().lower()
    if flag in ('0', 'off', 'false', 'no'):
        return False, keep, max_bytes, 'MAP_BANDS=%s' % env.get('MAP_BANDS')
    if cfg.get('mapBands') is False:
        return False, keep, max_bytes, 'mapBands is false in the config'
    return True, keep, max_bytes, None


def _encode_jpeg(image, quality):
    ok, buf = cv2.imencode('.jpg', image, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    return buf.tobytes() if ok else None


def map_band_meta(offer_id, parsed, geom, where=None, keep_places=True, at=None):
    """The sidecar's fields that the loop knows at the offer line: the offer,
    the screen it was read off, the card's own numbers and the fix the row got.
    The band's own geometry is added when it is cut (MapBands._job)."""
    parsed = parsed or {}
    kind = OP.screen_type(parsed.get('text') or '')
    roi = getattr(geom, 'roi', None)
    quad = getattr(geom, 'quad', None)
    meta = {'v': 1, 'offerId': offer_id,
            'at': int((time.time() if at is None else at) * 1000),
            'app': kind['app'], 'screen': kind['screen'],
            'geom': {'quad': (np.asarray(quad, dtype=float).reshape(4, 2).round(1).tolist()
                              if quad is not None else None),
                     'roi': list(roi) if roi else None},
            'pay': parsed.get('pay'), 'miles': parsed.get('miles'),
            'minutes': parsed.get('minutes'),
            'pickup': parsed.get('pickup'), 'pickupLine': parsed.get('pickupLine'),
            'dropoff': parsed.get('dropoff')}
    fix = JR.fix_fields(where, keep_places=keep_places)
    meta.update({k: fix[k] for k in ('lat', 'lon', 'gpsOk', 'gpsErr', 'gpsAge')})
    return meta


class MapBands(object):
    """The map band of each offer, kept once, off the loop. See MAP_BANDS_DIR.

    `submit` never blocks and never raises: a band already being cut keeps its
    turn and this one is tried on the card's next read. `latest()` is the
    newest band written, for a 📷 Snap. `threaded` False (--no-thread) does
    the work in `submit`, capped as ever."""

    def __init__(self, where, keep=MAP_BANDS_KEEP, max_bytes=MAP_BANDS_MB * 1024 * 1024,
                 threaded=True, encode=None, clock=time.monotonic,
                 cap_s=MAP_BANDS_CAP_S, band=None):
        self.where = where
        self.keep = keep
        self.max_bytes = max_bytes
        self.encode = encode or _encode_jpeg
        self.band = band or map_band
        self.clock = clock
        self.cap_s = cap_s
        self.threaded = threaded
        self.saved = []              # offer ids kept, newest last (bounded)
        self.tries = {}
        self.outcomes = []           # (offer_id, what) — for the tests and the log
        self._latest = None
        self._lock = threading.Lock()
        self._said = set()
        self._work = queue.Queue(maxsize=1)
        self._thread = None
        if threaded:
            self._thread = threading.Thread(target=self._serve, name='mapband', daemon=True)
            self._thread.start()

    def submit(self, offer_id, frame, geom, meta=None):
        try:
            with self._lock:
                if offer_id is None or offer_id in self.saved \
                        or self.tries.get(offer_id, 0) >= MAP_BANDS_TRIES:
                    return False
            job = (offer_id, frame, geom, dict(meta or {}))
            if self.threaded:
                try:
                    self._work.put_nowait(job)
                except queue.Full:
                    return False
            with self._lock:
                self.tries[offer_id] = self.tries.get(offer_id, 0) + 1
                if len(self.tries) > 64:
                    for k in list(self.tries)[:32]:
                        self.tries.pop(k, None)
            if not self.threaded:
                self._job(*job)
            return True
        except Exception:                           # noqa: BLE001 — never the loop's
            return False

    def latest(self, now=None, max_age=SNAP_BAND_AGE_S):
        """{'offerId', 'jpg', 'json', 'savedAt'} of the newest band written in
        the last `max_age` seconds and still on disk, or None."""
        with self._lock:
            got = dict(self._latest) if self._latest else None
        now = time.time() if now is None else now
        if not got or not 0 <= now - got['savedAt'] <= max_age \
                or not os.path.isfile(got['jpg']):
            return None
        return got

    def _say_once(self, key, message):
        if key not in self._said:
            self._said.add(key)
            log(message)

    def _done(self, offer_id, what):
        with self._lock:
            self.outcomes = (self.outcomes + [(offer_id, what)])[-64:]
        return what

    def _job(self, offer_id, frame, geom, meta):
        try:
            band = self.band(frame, geom)
        except Exception:                           # noqa: BLE001
            band = None
        if band is None or band.size == 0:
            return self._done(offer_id, 'no band')
        if float(band.mean()) < MAP_BANDS_DIM:
            return self._done(offer_id, 'dim')
        scale = 1.0
        if band.shape[0] > MAP_BANDS_MAX_ROWS:
            scale = MAP_BANDS_MAX_ROWS / float(band.shape[0])
            band = cv2.resize(band, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        began = self.clock()
        try:
            data = self.encode(band, MAP_BANDS_QUALITY)
        except Exception:                           # noqa: BLE001
            data = None
        took = self.clock() - began
        if not data:
            return self._done(offer_id, 'encode failed')
        if took > self.cap_s:
            self._say_once('slow', 'map band: encoding took %.2fs, over its %.1fs cap; '
                                   'skipped (said once)' % (took, self.cap_s))
            return self._done(offer_id, 'slow')
        h = getattr(geom, 'roi', None)
        top, bottom = MAP_LABEL_BAND
        if h and top + 0.2 < float(h[1]) < bottom:
            bottom = float(h[1])
        meta['band'] = {'warpHeight': MAP_LABEL_HEIGHT, 'top': top, 'bottom': bottom,
                        'width': int(band.shape[1]), 'height': int(band.shape[0]),
                        'scale': round(scale, 4), 'quality': MAP_BANDS_QUALITY,
                        'bytes': len(data), 'encodeMs': int(took * 1000)}
        meta['geom']['frame'] = (list(frame.shape[:2]) if hasattr(frame, 'shape') else None)
        safe = re.sub(r'[^A-Za-z0-9_.-]', '_', str(offer_id))[:60] or 'offer'
        jpg = os.path.join(self.where, safe + '.jpg')
        side = os.path.join(self.where, safe + '.json')
        try:
            os.makedirs(self.where, exist_ok=True)
            with open(jpg + '.part', 'wb') as fh:
                fh.write(data)
            os.replace(jpg + '.part', jpg)
            with open(side + '.part', 'w') as fh:
                json.dump(meta, fh, indent=1)
            os.replace(side + '.part', side)
        except (IOError, OSError, TypeError, ValueError) as e:
            for p in (jpg + '.part', side + '.part'):
                try:
                    os.remove(p)
                except OSError:
                    pass
            self._say_once('disk', 'map band: could not write into %s (%s); bands are '
                                   'skipped while that lasts (said once)' % (self.where, e))
            return self._done(offer_id, 'disk')
        with self._lock:
            self.saved = (self.saved + [offer_id])[-256:]
            self._latest = {'offerId': offer_id, 'jpg': jpg, 'json': side,
                            'savedAt': time.time()}
        self.prune()
        return self._done(offer_id, 'saved')

    def prune(self):
        """Oldest first until both caps hold: MAP_BANDS_KEEP files and
        MAP_BANDS_MB megabytes. A .json goes with its .jpg."""
        try:
            found = []
            for name in os.listdir(self.where):
                if not name.endswith('.jpg'):
                    continue
                p = os.path.join(self.where, name)
                st = os.stat(p)
                side = p[:-len('.jpg')] + '.json'
                size = st.st_size + (os.path.getsize(side) if os.path.isfile(side) else 0)
                found.append((st.st_mtime, name, p, side, size))
        except OSError:
            return 0
        found.sort()
        total = sum(f[4] for f in found)
        count = len(found)
        dropped = 0
        for _, _, p, side, size in found:
            if count <= self.keep and total <= self.max_bytes:
                break
            for q in (p, side):
                try:
                    os.remove(q)
                except OSError:
                    pass
            count -= 1
            total -= size
            dropped += 1
        if dropped:
            self._say_once('cap', 'map band: %s is at its cap (%d files, %dMB); the '
                                  'oldest now go as new ones arrive'
                           % (self.where, self.keep, self.max_bytes // (1024 * 1024)))
        return dropped

    def _serve(self):
        while True:
            job = self._work.get()
            if job is None:
                return
            try:
                self._job(*job)
            except Exception:                       # noqa: BLE001
                pass

    def close(self):
        if self._thread is None:
            return
        try:
            self._work.put_nowait(None)
        except queue.Full:
            pass


def emit_offer(offer_id, parsed, rate, where=None, whole=None, map_label=None):
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
        # Everything server.js builds the order in the car out of when the driver
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
        # `minutes`, because that is the name rate() returns the billed time
        # under. There is no `billedMinutes` key in what rate() gives back — in
        # either port — so this line read a name nothing produces and took the
        # fallback every single time, publishing the CARD's minutes as the
        # billed ones. Twenty-eight lines below, emit() gets it right
        # (`round(rate['minutes'], 1)`), and so does journal.py; only this path
        # — the one that feeds the pair arithmetic — was reading the wrong key.
        #
        # server.js stores it as `holding.minutes`, which is `totalA` in
        # Advice.stack: the number a held job's pay is prorated over. A Shop &
        # Deliver card, $22.00 / 45 min / 6.0 mi / 30 items at a 5-minute pad
        # and 90 seconds an item, bills at 95 minutes and $12.76/hr. Published
        # as 45, and measured twenty minutes in against a $10 / 20 min offer:
        #
        #   published (45)   worst $27.50/hr  best $49.49  alone $26.93  GO
        #   true billed (95) worst $16.01/hr  best $20.28  alone $12.76  PASS
        #
        # Green against a $25 target where the honest answer is decline. And
        # past minute 45 `left` reaches zero, so the pair line disappears for
        # the fifty minutes of shopping still to run, while holding() forgets
        # the order at 77.5 minutes instead of 152.5.
        #
        # `alone` is the tell: it is meant to be the same standalone rate the
        # panel already showed for that job, and with the true denominator it
        # comes out at exactly rate['perHour']. With 45 it was $26.93 — a rate
        # belonging to no job that exists.
        #
        # Dormant on this driver's record so far: `pad` and `secondsPerItem`
        # are zero on all 3,065 rows, so billed and card minutes are equal
        # throughout. 131 of those rows carry an item count, which is the shape
        # it fires on the moment a shopping allowance is set.
        'billedMinutes': rate.get('minutes', parsed.get('minutes')),
        'miles': rate.get('miles', parsed.get('miles')),
        'cost': (round(rate['cost'], 2)
                 if rate.get('ready') and rate.get('cost') is not None else None),
        'dropoff': parsed.get('dropoff'),
        'pickup': parsed.get('pickup'),
        # ...and the store's door DoorDash's stops card printed under that
        # name (OP's `pickupLine`), which is what Map view searches for the
        # pickup's pin when there is one (live.html mapWants): the panel's
        # card is this object, server.js keeps it as `scanner.offer`, and a
        # field the reading carries and this line does not never reaches the
        # map. `pickup` stays the name, for showing.
        'pickupLine': parsed.get('pickupLine'),
        # ...and the customer's street DoorDash's map labelled above a card
        # that printed only "Customer dropoff" (read_map_label; the owner, 27
        # Oct): "<n> <street>", or the street alone when the label ran into
        # the screen's edge, or None. Told on a second offer line once its
        # read is done, after this card's own. server.js keeps it as the
        # offer's `dropoffGuess` — a guess Map view may DRAW to, never the
        # offer's `dropoff`, never a figure, never a pin, never a hold's end.
        'mapLabel': map_label,
        # ...and DoorDash's printed stop count ("2 stops"), which
        # MapView.bandTarget reads to know a DoorDash card's miles are the
        # whole job: server.js's CARD_FIELDS has asked for it, and the
        # reading carried it, but this line never did.
        'stops': parsed.get('stops'),
        # Whether the card REFUSED a destination or the reader merely found
        # none. Both arrive as `dropoff: null` and only the first is a state
        # the driver can do something about — Uber prints "Customer dropoff"
        # and the address is one tap away on the phone. See the bottom bar's
        # ⌖ Dropoff, which asks to be pressed on this and on nothing else.
        'endRefused': bool(parsed.get('endRefused')),
        # The two fields that decide whether a verdict may be stated at all,
        # and the reason they have to travel on THIS line and not only on the
        # reading beside it.
        #
        # server.js writes the pairing row from this object and builds the
        # order in the car out of it, and Advice.stack is then asked to judge
        # both. Without these it judged them blind: a card whose pay read as
        # $1184 got a green "+ $1791-$3580/hr with the one you have" beneath a
        # headline already blanked to "--", and that verdict went into the
        # journal as what the panel advised. An offer with no distance on it
        # got a green pair verdict built from a gross figure against a net
        # target.
        #
        # `doubt` is a string naming which figure is impossible, or None;
        # `uncosted` says the money is a ceiling. Both are what rate() already
        # decided - nothing here re-derives them.
        'doubt': rate.get('doubt'),
        'uncosted': bool(rate.get('uncosted')),
        # ...and the verdict THIS card got, for the same reason and one more.
        #
        # ⌖ Dropoff asks to be pressed on a card that refused a destination,
        # and it asked on every one: 457 cards on the real week, 400 of them
        # (87.5%) cards the same panel was painting PASS. It now asks only when
        # the card's own verdict is not a PASS — 57 a week, and all 4 of the
        # driver's ticks in that population were go or warn.
        #
        # It has to ride HERE and not be read off the reading beside it. The
        # page's `last` is whatever reading came most recently, and once the
        # card leaves the phone that is an `empty` one; seeded from
        # /api/status it can be a different card altogether. Gated on that, a
        # PASS card's button starts asking the moment the card goes. Inside
        # the offer, beside the other two, it can only mean this card.
        #
        # Not a verdict to be mistaken for one: the message still carries no
        # `ready`, so it can neither replace a verdict nor stand in for one.
        'state': rate.get('state'),
        # What the card says about its own size, for whatever measures a pin
        # against the card's distance: a straight line from where the car was
        # cannot be longer than the road, but only on a figure that counts the
        # drive from the car and that the reader trusts. Read off the reading
        # the row was written from, not worked out again: `whole` is
        # OP.is_whole's answer the loop already holds, `hasTotal`, `legs` and
        # `toPickupMiles` are the window's merge, and the two `miles*` flags
        # are the parser's own word for a distance it repaired or doubted.
        # Read by map-view.js MapView.cardYardstick, which decides whether
        # Map view may hold this card against a pin, and copied onto the
        # order in the car by server.js cardOf. `toPickupMiles` is carried and
        # deliberately NOT read there: the approach leg alone leaves only the
        # half mile of slack for the car moving between the platform's
        # measurement and this fix, and that motion has not been measured.
        'whole': bool(whole),
        'hasTotal': bool(parsed.get('hasTotal')),
        'legs': parsed.get('legs'),
        'toPickupMiles': parsed.get('toPickupMiles'),
        'milesUncertain': bool(parsed.get('milesUncertain')),
        'milesCorrected': bool(parsed.get('milesCorrected')),
        'earlyLook': says_early_look(parsed),
        'multiOrder': says_multi_order(parsed),
        'manyDropoffs': says_many_dropoffs(parsed),
        # ...and which app's card it is, and which screen (OP.screen_type, off
        # the reading's own text): server.js keeps both on the order in the
        # car, the app as attribution's first hard rule with two orders held,
        # the screen to know Uber's add-on card (`uber.addon`, "+25 min (+ 9.6
        # mi) total"), which is held as part of the trip it joins. And the
        # card's "Deliver by", minutes since midnight, for the deadline cue.
        'app': OP.screen_type(parsed.get('text') or '')['app'],
        'screen': OP.screen_type(parsed.get('text') or '')['screen'],
        # ...and the parser's own word that this is Uber's add-on (OP.is_addon:
        # "+ $9.50" over "+8 min (+1.3 mi)"), the window's union of it. Wider
        # than the screen type, which asks the leg's plus signs alone: a card
        # that kept the pay's plus and lost the leg's is still one. A Took on
        # it keeps the order in the car and holds this beside it (server.js
        # placeTook) — on 16 Oct two of them replaced it.
        'addon': bool(parsed.get('addon')),
        'deliverBy': parsed.get('deliverBy'),
        # ...and where the car was when it came up, in the journal's own seven
        # fields — `lat`, `lon`, `gpsAge`, `gpsErr`, `gpsMode`, and the gate's
        # `gpsOk`/`gpsWhy` — built by the same function the row is, from the
        # SAME fix the row was handed (see where the loop calls this). Two
        # calls to phone.fix() a few lines apart can straddle the reader
        # thread storing a newer fix — gpsd sends one a second — and the row
        # and the line would then put one card in two places, with two ages
        # and possibly two answers from the gate.
        #
        # Not dropped under keepPlaces: like `pickup` and `dropoff` above, this
        # line is what the panel is showing now, not a record. The journal is
        # where that setting applies, and fix_fields applies it there.
        **JR.fix_fields(where),
    }, 'at': int(time.time() * 1000)}), flush=True)


def emit(rate, parsed, ms, locked, tracker=None, scanner=None, whole=None,
         clipped=False, crop_from='drawn'):
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
        # How much of the journey the reading could not time, when that is why
        # the verdict is being withheld. The panel says it out loud: "CHECK THE
        # TIME" alone reads as one odd number, where what happened is that the
        # rig is holding a fraction of the job and knows which fraction.
        #
        # Sent for the same reason `uncosted` is, and with its lesson in mind —
        # a page branch keyed on a field nobody puts on the wire is a notice
        # that has never once appeared in the car.
        'untimedMiles': rate.get('untimedMiles'),
        # Whether the rate below is the offer or only a ceiling on it.
        #
        # live.html has had `if (r.uncosted)` since the uncosted cap was
        # written, printing "No distance on the card - rate is a ceiling." It
        # has never once fired in the car: this key was not in the payload, so
        # the branch tested a field that was never sent. The verdict itself was
        # right - `state` comes from rate(), which caps it - so the panel showed
        # an amber CLOSE CALL on an offer whose printed rate clears the target,
        # with nothing on screen saying why.
        #
        # 788 of this driver's 3,065 recorded offers, 26%, were rated with no
        # running cost taken off, and 188 of those clear the $25 target on the
        # gross figure. Every one of the 188 was an unexplained amber.
        #
        # It is also what Advice.stack needs to apply the same cap to a pair.
        'uncosted': bool(rate.get('uncosted')),
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
        # Whether the card REFUSED a destination or the reader merely found
        # none. Both arrive as `dropoff: null` and only the first is a state
        # the driver can do something about — Uber prints "Customer dropoff"
        # and the address is one tap away on the phone. See the bottom bar's
        # ⌖ Dropoff, which asks to be pressed on this and on nothing else.
        'endRefused': bool(parsed.get('endRefused')),
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
        # DoorDash's printed stop count. See OP.parse's `stops`.
        'stops': parsed.get('stops'),
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
        # Whether this read found a payout flush against the top of the box
        # and threw the whole parse away for it (pipeline.money_is_clipped).
        # The one case where the rig KNOWS the box cut a card, and the reading
        # it sends is `parse('')` — no pay, no time, no places, no text — the
        # same shape as a read of an empty screen. Without this the panel
        # could not tell them apart and said "scanner running, no offer on
        # screen" over the card, while this process's own log said "the payout
        # sat against the top edge of the crop". rpi/README.md's tight-box
        # measurement is the size of it: a box that clips the payout lost it
        # on 13 of 42 cards. Only ever on a reading with no verdict — the
        # empty parse cannot be rated — so it can never sit beside a number.
        'clipped': bool(clipped),
        # Whether the reader knows this screen for the app's own furniture —
        # Uber's online map, DoorDash's "Finding offers", the route planner
        # (OP.NOT_AN_OFFER). rate() withholds a verdict for it once it has a
        # rate to withhold, but a reading with no rate reached the panel with
        # nothing to say what it was, and a payout or a leg read off the map
        # was "a card" there: READING THE CARD on the next read, over the
        # app saying in words that it has no offers. See noVerdictSaid in
        # live.html.
        'notAnOffer': bool(parsed.get('notAnOffer')),
        # Which crop the PAYOUT on this line was read through: 'found' when
        # the drawn card box read a journey and no payout and the payout came
        # off a taller card found above it (pipeline.Scanner._look,
        # cardfind.py) — on this read, or on an earlier read of the same card
        # that the merge carried it from (payout_from); 'drawn' for
        # every other line — the card box, a ⌖ read of the whole screen box,
        # the centred crop a detected screen is read through, and a line with
        # no payout. A payout the rig went looking for is a different claim
        # from one the driver's own box held, and the panel marks it.
        'cropFrom': crop_from,
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
    ap.add_argument('--gps', default=None, metavar='HOST[:PORT]',
                    help='where gpsd or a GPS server app is listening: '
                         '127.0.0.1 for gpsd and the USB receiver on the Pi, '
                         'or a phone\'s Tailscale address, e.g. '
                         '100.x.y.z:2947, rather than its hotspot one, so '
                         'it keeps working wherever the rig is. Each offer is '
                         'then stamped with where the '
                         'car was, which is what lets the map page resolve a '
                         'place near you rather than near anywhere. Off unless '
                         'given, and a phone that is not answering costs '
                         'nothing but the absence of the stamp — which the '
                         'driving panel and the journal now say, once it has '
                         'lasted a minute.')
    ap.add_argument('--no-track', action='store_true',
                    help='never re-find the phone; use the calibrated corners exactly')
    ap.add_argument('--screen-fps', type=float, default=1.0 / SNAPSHOT_SCREEN,
                    help='frames a second for the phone view (default %d); it '
                         'buys a full sensor frame each time, so raise it until '
                         'reads slow down' % round(1.0 / SNAPSHOT_SCREEN))
    ap.add_argument('--no-card-find', action='store_true',
                    help='never look above the drawn card box for a taller card; '
                         'every read is the box as drawn, as config.json '
                         '"cardFinder": false also asks')
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
        # ...or, when a card box was drawn inside it, the card box's share.
        card_share=(CX.card_share(None if cfg.get('cropBox') == CX.PIN_WHOLE
                                  else cfg.get('cropBox'))
                    if manual else None),
        # Whether a read through the card box that found a journey and no
        # payout may look above the box for a taller card. See
        # card_finder_off and pipeline.Scanner._look.
        card_finder=card_finder_off(cfg, args) is None,
        # No `settings=` here any more. The Scanner priced every frame from a
        # copy of this block taken at startup, and digest() replaced that rate
        # with its own before anything read it — so the copy decided nothing,
        # and was a second settings object in the process waiting for the day
        # a change reached one and not the other. digest() prices off `cfg`,
        # per card, and is the only thing that does.
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

    # Where the car is, when gpsd or a phone is willing to say. Off unless --gps was
    # given, and a bad address is a line on stderr rather than a refusal to
    # start: the rig's job is to read offers, and it does that whether or not
    # anything knows where it is doing it. See rpi/gps.py, which is most
    # concerned with not answering.
    phone = None
    # ...and why not, when it was asked for and cannot be. Kept rather than
    # only printed: stderr is server.js's `stderr` tail, which the next line
    # anything prints there replaces (and its `error` only when it is the last
    # thing said before an exit, which this is not), and a rig that was asked
    # for a position and will never get one has to keep saying so — see gps_now.
    gps_refused = None
    if args.gps:
        try:
            phone = GPS.Phone(args.gps).start()
            log('asking %s:%d for a position' % (phone.host, phone.port))
        except (ValueError, OSError) as e:
            gps_refused = 'could not use --gps %r (%s)' % (args.gps, e)
            print('%s — carrying on without a position on each offer'
                  % gps_refused, file=sys.stderr)
            phone = None
    # The rig's own account of itself, and the Pi's. See UpDown and PiHealth.
    pi = PiHealth()

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
    log('setup: %s' % card_finder_says(scanner, card_finder_off(cfg, args), args.config))
    spill = PL.touches_edge(quad, frame_shape)
    if spill:
        log('setup: the screen runs off the %s of the frame. That is expected on a '
            'close mount and is not a problem — the crop is placed from the '
            'card\'s measured share of what is in frame (or is the box drawn by '
            'hand), not as a fraction of a whole screen.' % ' and '.join(spill))
    accumulator = OfferAccumulator()
    last_sample = 0.0
    previous_card = None
    failures = 0
    spoke_for = None
    # The offer the driving screen has already been told about. Once per card,
    # not once per read: a card sits on screen for tens of seconds and is
    # re-read throughout, and the page needs the id rather than a heartbeat.
    told_offer = None
    doubt_kept_for = None
    # ...and the card whose unparsed picture has been kept. See UNPARSED_DIR.
    unparsed_kept_for = None
    # ...and what that card read as when it was told. A later, fuller reading
    # of the same card — the second leg, the address a single frame lost —
    # is told again, because the first was what the panel, the order in the
    # car and the pair row were built from. See below.
    told_as = None
    # ...and the place popup last said for that card, as (offer, role, line):
    # said once per card and address, like the dropoff line's repeat rule, and
    # again for the next card. See emit_popup.
    popup_said = None
    # ...and when each app's completion screen was last read: said once while
    # it stays up. See DeliveredSaid.
    delivered_said = DeliveredSaid()
    # Whether the loop has already said why it went quiet. See where it goes.
    quiet_said = False
    # The last few preview frames, and whether the newest was the same picture
    # as one of them. See STALL_SAY.
    repeats = Repeats()
    frozen = False
    # Whether a beat has carried the stall yet. The loop goes quiet over a
    # stall only once the panel has been told, so the silence that follows is
    # one the driver has a reason for.
    stall_told = False
    # Whether the log has said this stall is being sat out rather than
    # restarted, because the last restart for one was too recent; and whether
    # this stall has gone quiet for one, after which the note it left is for
    # the run after it and not for this stall to sit out. See STALL_AGAIN.
    stall_held_said = False
    stall_asked = False
    # A read handed over since the camera's word was last asked. A flag and not
    # `reader.busy`, which with --no-thread is never true when the word is
    # asked — the read is done and collected inside the pass that hands it
    # over — so a card arriving in a dark box landed its verdict under TOO DARK
    # TO BE SURE until the gain's next look, up to six seconds on. On the
    # threaded path the busy reader says nothing the flag has not already said.
    looked = False
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
    last_dropoff_read = 0.0
    # A press that has not been answered yet.
    #
    # Separate from `dropoff_until`, which says whether the window is still
    # OPEN. This says whether the driver is still owed a reply, and it is the
    # difference between the only control on the bar that cannot report its own
    # failure and one that can: every other one names it — "Took … · not
    # saved", "Drop · failed", "⟳ failed", "could not set the box: …" — while
    # this one repainted itself identically whether the scan worked or not.
    # A control that cannot say it failed is a control that gets abandoned,
    # and abandoning this one costs the geography half of the stacking advice.
    dropoff_asked = False
    # The last address sent, so a navigation screen sitting there for twenty
    # minutes is reported once rather than on every read that happens to catch
    # it. A DIFFERENT address is a different job and is always sent.
    dropoff_said = None
    # ...and the order in the car when it was last looked at (held_signature),
    # which is what forgets it.
    held_seen = None
    # The whole-screen read the rig makes WITHOUT a press, while an order is in
    # the car: of a planner, a navigation screen, a Dropoff label
    # (auto_read_for). `screen_auto` is a whole-screen read wanted on the next
    # pass; `screen_auto_at` is when the last one was asked for, whichever
    # kind asked, which is the rate limit. See where digest() sets it.
    screen_auto = False
    screen_auto_at = None
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
    # What 📷 Snap asks this process for — see reader_record. The read digest()
    # took last, crop and all, and the last beat with when it went. Kept, not
    # made again on request: the crop is the one tesseract's input was made
    # from, and the beat is what the panel was told.
    last_read = None
    last_beat = None
    # ...and, for the richer snap (EXPERIMENTAL), the last reads and the newest
    # full-resolution frame: a reference to the sensor array a read or the
    # phone view already made, never a copy. See ReadLog and answer_snap.
    read_log = ReadLog()
    full_frame = {'frame': None, 'at': None, 'source': None}
    # The accumulator episode whose payout a card found above the drawn card
    # box gave, and that card, or None; and the card the live view outlines
    # now. See payout_from.
    found_kept = None
    found_box = None
    # The card currently being watched, and what has become of it. See
    # Health.saw — an episode that ends having shown a payout but written
    # nothing is a card the rig saw and failed to keep.
    seen_episode = None
    seen_pay = False
    seen_kept = False
    reader = Reader(scanner, threaded=not args.no_thread)
    # ...and DoorDash's map label, read on a thread of its own once a card's
    # offer line is out (MapLabels, read_map_label). `labels` holds what each
    # offer's label read as, and the arguments its offer line was last told
    # with, so the line can be told again carrying the label.
    map_labels = MapLabels(threaded=not args.no_thread)
    labels = {'for': {}, 'told': None}
    # ...and every offer's map band, kept once on a thread of its own after
    # its offer line. Collection only; see MAP_BANDS_DIR.
    bands_on, bands_keep, bands_bytes, bands_off = map_bands_setting(cfg)
    map_bands = None
    if bands_on and not args.no_journal:
        map_bands = MapBands(map_bands_dir(args.journal), keep=bands_keep,
                             max_bytes=bands_bytes, threaded=not args.no_thread)
    elif bands_off:
        log('map bands off (%s)' % bands_off)

    def tell_label():
        got = map_labels.take()
        if got is None:
            return
        offer_id, answer = got
        line = answer.get('line') if answer else None
        if not line:
            return
        labels['for'][offer_id] = line
        read_log.add(time.time(), 'map label', text=answer.get('raw') or line,
                     parsed={}, ms=answer.get('ms'))
        if len(labels['for']) > 32:
            labels['for'].pop(next(iter(labels['for'])))
        told = labels['told']
        if args.json and told and told[0] == offer_id == told_offer:
            emit_offer(offer_id, told[1], told[2], where=told[3], whole=told[4],
                       map_label=line)

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
        # 68MB on a full live file — about twelve weeks at journal.WEEK_BYTES'
        # 5.7MB a week — at every startup, on a Pi, beside a resume() that was
        # doing the same thing again.
        kept = offer_log.journal.count()
        resumed = offer_log.resume()
        log('journal: %s (%d journal row%s so far)%s'
            % (args.journal, kept, '' if kept == 1 else 's',
               ', still on the last one' if resumed else ''))
    # Into the same file as the offers, through the same Journal, so a card
    # gone read-only stops these exactly when it stops them and `notSaving`
    # says so for both. --no-journal writes none of them, which is what it asks.
    updown = UpDown(offer_log.journal if offer_log is not None else None,
                    asked_gps=bool(args.gps))
    def digest(out, frame, read_at=None, whole=False, began=None, geom=None):
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
        nonlocal dropoff_until, dropoff_said, dropoff_asked, held_seen
        nonlocal screen_auto, screen_auto_at
        nonlocal seen_episode, seen_pay, seen_kept
        nonlocal verify_every, verify_signature, last_verify, previous_card
        nonlocal last_sample, spoke_for, told_offer, told_as, doubt_kept_for
        nonlocal unparsed_kept_for
        nonlocal last_read, found_box, found_kept, popup_said
        # Not merged when it was a whole-screen read — see collect().
        parsed = out['parsed'] if whole else accumulator.add(out['parsed'])
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

        # The destination, with or without the button, when this reading has
        # one.
        #
        # Read off `out['parsed']` — which is the MERGED reading by the time
        # this runs, since it was reassigned two statements above. An earlier
        # version of this comment claimed the opposite ("the frame's OWN parse,
        # not the merged reading") and was describing an intention rather than
        # the code. What makes the intention true anyway is accumulate.add()
        # itself: it returns the frame's parse unchanged whenever pay is None
        # or zero (accumulate.py:350), so on exactly the screens this branch
        # cares about there is nothing merged into it. That is worth stating
        # as the reason it holds, because it is also the reason the payout test
        # is a test of one frame — see the guard below, which needs a second
        # arm because of it.
        #
        # Ahead of everything below, because none of that applies either. A
        # screen with an address and no payout is `complete: False`, which is
        # the branch that decides the reading is not worth a verdict — correct
        # for an offer, and it would throw this away.
        # Judged by when the picture was TAKEN, not by when the reading of
        # it came back. A read is over a second on a Pi, so a window closing
        # while one is in flight threw the answer away: the read went out with
        # the window open, found the address, and landed a second past the
        # deadline to be told it was too late. That is the worst second to lose
        # it in - the driver who took a moment to get the destination up is
        # exactly the driver whose address arrives at the end of the window.
        started = read_at if read_at is not None else time.time()
        # ...and the same moment on the monotonic clock (Reader.submit), which
        # is what every interval below is timed on: the ⌖ window, the rate
        # limit on unpressed whole-screen reads, the resample burst. `started`
        # stays the wall clock, because it is a stamp — on the popup line, on
        # 📷 Snap's reader.json, against server.js's note of the order held —
        # and a stamp is never corrected here (AUDITS, Settled: the clock).
        began = began if began is not None else time.monotonic()
        # Where the payout this reading shows came from, which is not always
        # where this read came from — see payout_from. One answer, for the
        # panel's line, a Snap's reader.json and the live view's outline.
        pay_from, found_box, found_kept = payout_from(found_kept, out, parsed)
        # ...and kept for 📷 Snap, ⌖ reads included: the last card the reader
        # cut out — `fitted`, before preprocess() made tesseract's input from
        # it — is what "what was the reader looking at?" asks about. A
        # reference, not a copy — the reader makes a new crop every read.
        last_read = {'at': started, 'fitted': out.get('fitted'),
                     'wholeScreen': bool(whole), 'crop': out.get('crop'),
                     'cropFrom': out.get('cropFrom', 'drawn'), 'payFrom': pay_from,
                     'text': out.get('text'), 'parsed': parsed, 'rate': rate}
        # WITH OR WITHOUT THE BUTTON.
        #
        # This branch used to run only inside the window a press opens, and the
        # window is not what made it safe. What makes it safe is the payout
        # test below — a screen with a payout on it is an offer, not a
        # destination — and that test knows nothing about windows.
        #
        # What the window buys is READS, not safety. The driver presses the
        # button after accepting, when the phone has settled into a navigation
        # screen that is not going to move, and a still picture moves the motion
        # gate not at all: without forced reads nothing would be looked at. That
        # is still true and the window still does it, further down.
        #
        # But the case the driver actually asked about is different. Screening,
        # they TAP the dropoff pin to reveal the address — and a tap changes the
        # screen, which is exactly what the motion gate is for. A read happens
        # at that moment anyway. The rig was looking straight at the address and
        # throwing it away for want of a button press.
        #
        # So the address is taken from any read that finds one, and the window
        # goes on forcing reads when the screen will not move on its own. Two
        # actions become one, and the one that remains is the one the driver was
        # already doing on their phone.
        #
        # The window still closes on the first answer inside it — see below —
        # because that is about stopping two dozen forced reads, not about
        # stopping a second address.
        asked = began < dropoff_until
        shot = out['parsed'] or {}
        # A SCREEN WITH A PAYOUT ON IT IS AN OFFER, NOT A DESTINATION.
        #
        # The window opens the instant the button is pressed, and the driver
        # then has to get the destination up — so the first reads of almost
        # every window are of the offer card still sitting there. An offer
        # card is supposed to yield no address, and the parser says so in a
        # comment: "None on every one of the 604 offer cards on file". That
        # is no longer true. Over the 900 card texts on file now, five DO
        # yield one, because the merchant's branch address carries the same
        # `, ST ZIP` anchor a real address does:
        #
        #     800 Forrest St NW, Atlanta, GA 30318   <- off a Delivery card
        #     100 Rosemont Ct, Hiram, GA 30141
        #     2603 E, GA 30106                       <- and two fragments
        #
        # Any one of them ends the window with the WRONG answer and stops it
        # looking: the order in the car is then recorded as ending where it
        # started, the stack line compares the next offer against a
        # restaurant, and the pairing written to the journal says `scanned:
        # true` — a full address, confidently wrong. That is the expensive
        # direction.
        #
        # The payout is the grammar that separates them, and it costs
        # nothing: a navigation screen has no payout to lose. All five of
        # those cards carry one.
        #
        # BUT THE PAYOUT IS NOT ENOUGH ON ITS OWN, and saying it was is how
        # this branch got dangerous the moment the window came off it.
        #
        # `shot` is the reading for this frame, and accumulate.add() returns
        # the frame's own parse unchanged whenever its pay is None or zero
        # (accumulate.py:350) — the merge has nothing to vote with. So the
        # payout test is a test of ONE FRAME. A frame of an offer card that
        # loses its payout to glare, or to the crop edge the health line
        # already counts as `clipped`, reads `pay: None` with the merchant's
        # branch address still on it — and with no window to be inside any
        # more, that address went out unprompted as the destination and was
        # stapled to the card being screened. A restaurant recorded as where
        # the customer lives, from one bad frame, with nothing saying so.
        #
        # So: a MERCHANT NAME is the other half of the grammar, and it is the
        # half that survives a lost payout. A navigation screen names no
        # merchant — it says "Dropoff <address> 12 min Start" and `places`
        # comes back empty. An offer card names one whether or not its payout
        # survived the frame: the `800 Forrest St NW` case reads
        # `places: ['Wingstop 800 Forrest St NW, Atlanta, GA 30318', ...]`
        # with the payout stripped out of the text entirely.
        #
        # Measured on this driver's own 272 cards: not one carries a `, ST ZIP`
        # anchor at all, with or without its payout, so none of them can reach
        # this branch either way. The guard is for the corpus the parser
        # documents, not for the export.
        #
        # ...EXCEPT Uber's navigation bar, which is not a merchant: see
        # screen_address, which also reads the opened navigation sheet.
        an_offer, frame_address, sheet = screen_address(shot, out.get('text'))
        found = None if an_offer else frame_address
        # UBER'S TRIP PLANNER, which lists every stop of the trip in order and
        # prints no ZIP, so find_address returns None on it — measured on the
        # rig's own view of one. OP.find_planner reads it by its own grammar.
        #
        # OFF THE WHOLE SCREEN, AND ONLY UNDER A PRESS FOR ITS DESTINATION. The
        # owner first asked for "only while ⌖ is pressed"; after a shift, for
        # the stops to be read on their own while an order is held, which
        # `auto` below does — the stops, and never a destination off them. The
        # rest of this is why the destination stays under the press: it is
        # the existing policy for destinations, followed rather than widened. An unprompted
        # sighting is taken only under find_address's strict `, ST ZIP` grammar
        # — the reason it may be taken at all — and the planner's address is
        # the one place that grammar is loosened. A loosened rule belongs under
        # the press, the way the forced reads do; unprompted, a planner left up
        # from the trip before would be filed against whatever card is on the
        # slot (see the screening branch in server.js), which is the confidently
        # wrong direction AUDITS' "Plan 3.1" entry describes.
        #
        # Not on an offer either: `an_offer` is the same two-armed test the
        # address answers to. Measured, it costs a planner nothing — parse()
        # finds no payout and no places on one, pickups and all.
        #
        # A planner's addresses are NEVER this read's to send, asked or not. A
        # screen listing stops can carry more than one address, and
        # find_address would take the last one printed — on a planner with two
        # dropoffs that is one of two customers, chosen by layout. Whether the
        # planner gives the order in the car its end is the assembler's
        # (assemble.js, plannerDestination and plannerLoneDropoff, which were
        # planner_destination and planner_lone_dropoff here), decided off the
        # sighting this read sends below: one page as this file decided it,
        # or several pages stitched, which is what this file could not see. So
        # on a planner `found` is None, and rpi/test_loop.py holds both halves:
        # a planner nobody pressed for, with a ZIP on it, sends no address,
        # and one pressed for sends its stops and its sighting.
        #
        # `seen_stops` is everything find_planner kept, the stops a page edge
        # cut included; `planner`, the planner line's stops, is the headed
        # stops alone, as it always was (planner_stops). The sighting is given
        # all of it.
        seen_stops = None if an_offer else OP.find_planner(out.get('text'))
        planner = planner_stops(seen_stops)
        answers = planner is not None and whole and asked
        # ...AND, NOW, WITHOUT A PRESS, while an order is in the car.
        #
        # The owner, after a shift: the driver wants the planner read
        # automatically. A whole-screen read that nobody asked for is the one
        # `screen_auto` below requested — a press's reads are all `asked`,
        # because the window is open from before they are handed over — and it
        # sends the planner line only off a screen whose TITLE reads "Trip
        # Planner": the stop grammar that started it was read in the card box,
        # and the title is what says the whole screen is the planner and not a
        # map round a card. It goes out as the press's does, `asked: false`,
        # and only with a stop on it (find_planner is None without one), so a
        # read that found no stop never replaces one that had them. The
        # sighting says `titled` too, and the assembler asks it of an
        # unpressed page before it files off one.
        #
        # ...OR WHOSE LAYOUT PROVES IT, title or not (the owner, 16 Oct, after
        # the single trip's planner was read with its title as "ny. mS" and
        # its one dropoff never filed): a Pickup and a Dropoff header each with
        # its "Expected by", "View details" and the "Stop New Requests" bar —
        # OP.planner_laid_out. The sighting says it as `laidOut`.
        #
        # Not an accept detector and not a press: it runs only when the driver
        # has already marked the order taken (order_held), and the rig still
        # touches nothing on the phone.
        auto = (planner is not None and whole and not asked
                and (OP.planner_titled(out.get('text'))
                     or OP.planner_laid_out(out.get('text'))))
        if planner is not None:
            found = None
        # A whole-screen read nobody pressed for sends NO dropoff line at all:
        # not the address find_address would take off the whole screen, which
        # is the map's or a card's as often as the destination's.
        #
        # An address the screen prints under a "Deliver to" or "Dropoff" label,
        # in its own stop block, is still a destination the driver asked to
        # have filed with no ⌖ ("while an order is held, set its destination
        # whenever the screen shows an address directly under a Dropoff
        # label"), and so is the opened navigation sheet's address over
        # "Dropoff type" with the customer's name above (the owner, 14 Oct:
        # OP.sheet_dropoff). It goes out on the SIGHTING this read sends below,
        # typed a dropoff by sighting_stops, and the assembler files it as a
        # navigation destination, rank `nav` (assemble.js, navCandidate) —
        # never over a press or an earlier
        # screen-read end, never read before the Took, never off a pickup
        # screen or as one of the orders' own pickups, and with two orders in
        # the car only on a cue. This read used to send it as a labelled
        # dropoff line instead; one road for it, so the sighting and the line
        # cannot both file one screen.
        #
        # A whole-screen read nobody pressed for happens only as
        # `screen_auto`, which runs only while the driver's own ✓ Took is in
        # force (order_held), so this is not an accept detector, and the rig
        # still touches nothing on the phone.
        labelled = False
        if whole and not asked:
            found = None
        # ...and asked FOR, off a card-box read that shows what auto_read_for
        # names while an order is held: the planner's grammar, Uber's
        # navigation, or an address under a Dropoff label. The card box on this
        # rig is the bottom half of the screen — the shift's reads of a planner
        # caught stop headers, "Address" and "Expected by" in it and never the
        # title, which is at the top — so what the box sees is what can start
        # it, and the whole-screen read is where the title or the label is
        # checked. At most once per SCREEN_AUTO_EVERY, whichever kind asks —
        # SCREEN_AUTO_HOT while the heat guard is on (HeatGuard), and this is
        # the one place the guard reaches — and not while a press is open: that
        # window is already reading the whole screen and answers as ⌖.
        if not whole and not an_offer and not asked and not screen_auto \
                and (screen_auto_at is None
                     or began - screen_auto_at >= screen_auto_every(pi.guard.on)) \
                and auto_read_for(out.get('text'), planner) is not None \
                and order_held(started):
            screen_auto = True
            screen_auto_at = began
        # AN ADDRESS THE SCREEN DID NOT LABEL A DROPOFF IS NOT A DESTINATION.
        #
        # On shift: "✓ Took $28.08" pressed with the Trip Planner up — two
        # pickups, each with a restaurant address and a ZIP, above a closed
        # "Dropoff • 1 order". Nobody pressed ⌖. The card box caught the list
        # mid-scroll with its top edge between the first pickup's street and
        # town lines, no stop header in that read matched PLANNER_STOP, so
        # `planner` above was None and `found` was find_address's answer:
        # "Kennesaw, GA 30144", the restaurant's town. It went out unprompted,
        # server.js filled the held order's empty destination with it, and
        # /api/status said `dropoff: 'Kennesaw, GA 30144', dropoffScanned:
        # true` for an order going somewhere else — the stack line and the map
        # then measured every offer against a restaurant.
        #
        # So the label in front of the address decides (OP.address_stop):
        #   * printed under a PICKUP label — refused, asked or not. A press says
        #     "this screen is the destination"; it does not make a restaurant
        #     one when the screen itself says it is not.
        #   * under no label at all — refused when nobody asked, because an
        #     unprompted sighting is the rig filling a blank on its own say-so
        #     and has nothing else to stand on; and refused under a press too
        #     when the screen carries the planner's furniture, because that is
        #     a planner whose headers did not read and its unlabelled addresses
        #     are as likely pickups as not. A press over a plain navigation
        #     screen with no label keeps the answer it always had.
        # Refusing costs a blank the driver can fill with ⌖; taking it costs a
        # wrong destination nothing on the panel flags. Not on a planner that
        # read (`planner`), whose own grammar has already decided `found`.
        if found and planner is None:
            stop = OP.address_stop(out.get('text'))
            if stop == 'pickup' or (stop != 'dropoff' and (
                    not asked or OP.planner_furniture(out.get('text')))):
                found = None
                # Counted, like the payout guard's refusals, so a destination
                # this throws away is a number on the health line and the `seen`
                # row rather than a silence. No address in the log: it is a
                # restaurant's or a customer's door, and the count is the
                # question.
                health.address_not_dropoff += 1
        # ...and UNDER A PRESS, Uber's opened sheet: its address over "Dropoff
        # type" (or "Business / Building name") with the customer's name above
        # it, which the owner decided (14 Oct) is the dropoff, labelled by the
        # sheet's own words read upwards (OP.sheet_dropoff). Unprompted it goes
        # out on the sighting alone and the assembler files it at rank `nav`;
        # a press's answer is the dropoff line, and the assembler leaves a
        # pressed sighting off a navigation screen to it (navCandidate). So
        # without this a press over the sheet was answered "nothing on that
        # screen read as an address" — find_address wants a ZIP and the sheet
        # prints none — and on 17 Oct, with the customer sheet up, the press
        # was answered by a "planner" of one dropoff read off the sheet's
        # "Drop off 1 order" instead (OP._customer_sheet now refuses that).
        # Only where nothing else answered: `found` is the press's own address
        # when the screen printed one, and a planner answers for itself.
        # `sheet` is None wherever digest() took the frame for an offer.
        if asked and found is None and sheet and planner is None:
            found = sheet
        # ...and a card-box read nobody pressed for whose address is under a
        # Dropoff label in its own block is label-proven as the whole-screen
        # one above is: a navigation screen's "Dropoff <address>" read while an
        # order is held. The label is said, not acted on: whether it files is
        # server.js's to decide, against the hold it has and the scanner does
        # not.
        if found and not asked and not labelled and planner is None \
                and OP.address_under_dropoff(out.get('text')):
            labelled = True
        # ...and KEPT, which is new, and is the one thing standing between this
        # rig and knowing which offers the driver took.
        #
        # 31 of 1,166 offers on the owner's week carry a tick, and every
        # earnings figure on every screen rests on those 31. The rig cannot see
        # the Accept press and must never make it, so the only evidence is the
        # screen the phone goes to afterwards — a navigation screen with
        # "Deliver to <name>" on it, a turn instruction and a speed limit, and
        # no payout and no Accept button anywhere. `an_offer` is already the
        # test that separates that screen from a card, and until now every one
        # of those frames was read, counted twice below, and thrown away.
        #
        # The cheaper idea was measured first and refused: a quiet stretch in
        # the record does NOT mean the driver was out on a job. Against the 31
        # ticks already on file, a thirty-minute silence catches 2 of them and
        # fires on 8 offers that were not ticked, because offers keep arriving
        # through the whole delivery — median 5.4 minutes to the next card
        # after an accepted job of a stated 29. See AUDITS, "A silence does not
        # mean the driver accepted".
        #
        # THE PAYOUT ALONE, and deliberately not `an_offer`. The two questions
        # look identical and are not, and using one test for both would have
        # thrown away the very screens this is collecting.
        #
        # `an_offer`'s second arm is there so that an address is never taken off
        # a card whose payout was lost but whose MERCHANT survived, and the
        # comment above states the measurement it rests on: "a navigation screen
        # names no merchant — it says 'Dropoff <address> 12 min Start' and
        # `places` comes back empty". That was measured on DoorDash. Uber's
        # post-accept screen names its destination the same way a card names a
        # shop — `BCG Atlanta / 1075 Peachtree St NE Ste 3800, Atlanta, GA` off
        # the screenshot this was built from — so the merchant arm would refuse
        # exactly the frames worth having, silently, and the corpus would come
        # back holding only the screens that happened to read badly.
        #
        # What the frame named is written ONTO the row instead, so the one thing
        # that could make it a degraded card rather than a screen is evidence
        # rather than a guess, and the detector gets to partition on it.
        #
        # WHETHER A CARD WAS UP is recorded, not acted on, and that is the
        # second half of the same problem. An offer card that loses its payout
        # to glare for ONE frame reads `pay: None` over a card — the positive
        # class in the negative slot, which is the single confusion a recogniser
        # built on these rows could not survive. Refusing such a frame outright
        # was the first answer and it was worse: reads are driven by a motion
        # gate, so the frame right after an accept is sometimes the only one,
        # and refusing it loses the screen rather than mislabelling it.
        # `card_on_screen` still holds the PREVIOUS read's answer at this point
        # in digest(), which is exactly the question — was there a card here a
        # moment ago — so it is passed down and written onto the row, and the
        # first frame that arrives with no card behind it supersedes.
        #
        # NOT a clipped read either. `clipped` means a payout WAS found and was
        # sitting flush against the top of the crop, and pipeline.py answers
        # that by handing back `parse('')` — an empty parse over a screen that
        # was a card, which no test of the parse can see through.
        #
        # Recording only. `note_screen` writes nothing to `accepted` and
        # nothing reads these rows; see its docstring for why that stays true
        # until they have been measured against ticks the driver made by hand.
        #
        # No `now`. Every other row the rig writes is stamped when digest runs,
        # and `started` is when the FRAME WAS CAPTURED — a read is 1.8s median
        # on this Pi, so passing it would put this row on a different clock from
        # the offer row it names and make `afterMs` short by a whole read.
        if offer_log is not None and not out.get('clipped'):
            if shot.get('pay') is None:
                # ...unless the reader can already say what the screen is. The
                # app's zone prompt has no payout once its per-order bonus is
                # refused (see OP.PAY_IS_PER_ORDER), so it arrives here. It is
                # not the screen after the card before it, and it is the end of
                # that card's window: what the phone shows after the app's own
                # prompt is not evidence about a card read before it, any more
                # than the screen after a second card is (saw_card, below). So
                # note_promo drops the slate, on every read of a prompt, and
                # writes the prompt as what it is. Before the bonus was refused
                # it was a $1 payout and saw_card dropped the slate on it; this
                # keeps that. Without it, a run through main() — the card, the
                # prompt, then a navigation screen — wrote that screen `after:`
                # the card. See rpi/test_loop.py.
                if shot.get('promo'):
                    offer_log.note_promo(out.get('text'))
                elif offer_log.note_screen(out.get('text'),
                                           places=shot.get('places'),
                                           card_was_up=card_on_screen):
                    health.screens_kept += 1
            else:
                # ...and a card in front of the camera that is NOT the one the
                # slate is armed for drops it. The slate is armed by a card
                # REACHING THE FILE, and `saw` minus `kept` on the health line
                # above is the measured count of cards that never do — so
                # without this the screen after an accept is filed against the
                # previous card, which is a pairing naming an offer the driver
                # did not take. Reproduced through main() before it existed;
                # see `saw_card`, and the check in rpi/test_loop.py.
                offer_log.saw_card(shot.get('pay'))
        # ...and COUNTED, both ways, because all three outcomes look identical
        # from the driver's seat: "the rig didn't get it".
        #
        # The driver's own words are that on a DoorDash order they tap the
        # customer dropoff to reveal the address while screening — and on a
        # screening tap the offer card is still on the screen. If the crop
        # catches the payout and the revealed label in the same frame, the
        # guard above throws the address away and nothing anywhere records
        # that it happened. That is the guard doing its job and it is also
        # the screening case failing, and the two are indistinguishable
        # without a number.
        #
        # So: how often the guard actually fired, and how often a screen went
        # past with something street-shaped on it that find_address refused.
        # The second is the one expected to move, and it is the one that says
        # whether the strict `street, ST ZIP` rule is what stands between this
        # driver and an automatic destination — find_address returns None on
        # all 272 of their exported cards, so nothing on file can answer it.
        #
        # Counted, NOT acted on. A number saying how often a guard fired is
        # not an argument that it was wrong to fire; loosening find_address on
        # the strength of it would put "89 Shanty Drive" — a background map
        # label — on the panel as a destination.
        # Counted off `an_offer`, not off the payout alone. The guard has two
        # arms now, and a counter that watched only one of them would make the
        # other a silent refusal — which is the thing this counter exists to
        # stop being possible.
        if an_offer and frame_address:
            health.address_refused_as_offer += 1
        elif not an_offer and not frame_address \
                and OP.STREET_ENDS.search(out.get('text') or ''):
            health.street_seen_no_address += 1
        # ...and said ONCE, not on every read that catches the same screen.
        #
        # A navigation screen can sit in front of the camera for the whole of a
        # delivery. Every read that happens for some other reason catches it,
        # and each one would be a line on the wire and a note appended to the
        # journal — the same address, twenty times, on the card it already
        # names. A DIFFERENT address is a different job and is always sent.
        #
        # Compared on the line, which is the thing stored and shown. Two reads
        # of one screen can differ in the parts around it without disagreeing
        # about where the job goes.
        #
        # NOT when the driver asked. `dropoff_said` is never cleared — there is
        # no moment in this loop that means "a new job began" — so without
        # `not asked` it is a suppression that never lifts: the second delivery
        # of a shift to an address already seen is silently dropped, and
        # pressing ⌖ does not rescue it, because this sits ABOVE the branch
        # that answers. Worse than saying nothing: `dropoff_until = 0.0` is
        # inside that branch too, so a suppressed press closes no window and
        # burns all twelve seconds of forced reads with the rig unresponsive
        # and not one line said about why.
        #
        # A press is a question, and a question asked twice gets answered
        # twice. The unprompted path keeps the suppression whole, which is
        # where it earns its keep: a navigation screen sits in front of the
        # camera for a whole delivery and nobody asked about any of it.
        #
        # The card is deliberately NOT the boundary here. Clearing this when a
        # new card is read sounds narrower and is much wider — `carrying` is
        # null unless the driver pressed "took it", so an unprompted sighting
        # falls through to the screening branch in server.js and staples the
        # address onto whatever card is on screen now, `dropoffScanned: true`.
        # Once per address is a stale answer; once per screened card is a
        # confidently wrong one.
        #
        # THE ORDER IN THE CAR IS the boundary, and it is the server's to say
        # (held_signature: the note server.js leaves names the order). This was
        # never cleared at all, so an address refused once — read before the
        # driver pressed ✓ Took, and so not about the order then held — was
        # never volunteered again for the delivery it was about, and only ⌖
        # could rescue it (AUDITS: "Why that loss is permanent"). Forgotten
        # when the order changes, and only then: one order's own navigation
        # screen is still said once.
        # DOORDASH'S PLACE POPUP is not a destination either, whatever its
        # label: it is about the card being screened, and goes to the server
        # on its own line (emit_popup, below), where it is filed onto that
        # card and NEVER onto the order in the car. A customer's popup reads
        # as an address under a Dropoff label, so without this it would also
        # go out as a labelled dropoff line, which the assembler files onto a
        # held order — the order this popup is not about. A store's is
        # already refused above as an address under a Pickup label. Not under
        # a press: a press says "this screen is the destination" and keeps
        # the answer it always had.
        popup = OP.place_popup(out.get('text'))
        if popup is not None and not asked:
            found = None
        held_now = held_signature(started)
        if held_now != held_seen:
            held_seen = held_now
            dropoff_said = None
        if found and not asked and (found.get('line') or None) == dropoff_said:
            found = None
        # The planner, when it answered a press, goes out on its own line and
        # closes the window — whether or not it gave the order in the car a
        # destination. A planner with two dropoffs IS the answer to "what is on
        # that screen", and the panel shows its stops; a "nothing on that screen
        # read as an address" arriving after it, from the branch that closes an
        # unanswered window, would contradict the stops on the glass. So it is
        # answered here, by the same two assignments `if found:` makes. Its
        # one dropoff, when it gives one, is the assembler's to file off the
        # sighting, and reaches the panel from server.js as a dropoff line.
        #
        # What the read SAW, first: every whole-screen read and every read
        # with a planner on it, typed by its screen. See emit_sighting. Off the
        # frame's own address — `found` above is the dropoff line's answer,
        # already narrowed by press, label and repeat — and that address is
        # None wherever `an_offer` refused it. FIRST, and with the planner
        # line's own stamp (`seen_at`), because a planner's one dropoff and the
        # reason it gives none are the assembler's, off this line: server.js
        # has decided them by the time the planner line below arrives, and
        # puts the reason on it for the panel.
        seen_at = int(time.time() * 1000)
        if args.json and (whole or seen_stops is not None):
            emit_sighting(out.get('text'), seen_stops,
                          None if an_offer else frame_address,
                          asked, whole,
                          keep=offer_log is not None and offer_log.keep_places,
                          at=seen_at, sheet=sheet)
        # ...and the popup, once per card and address, stamped with when its
        # frame was TAKEN: the server files it only onto a card on the slot
        # from before that moment. The role, not the address, in the log.
        if popup is not None:
            said_key = (told_offer, popup['role'], popup['line'])
            if said_key != popup_said:
                popup_said = said_key
                if args.json:
                    emit_popup(popup, at=int(started * 1000))
                log('place popup read: the %s\'s address' % (
                    'store' if popup['role'] == 'pickup' else 'customer'))
        # ...and the delivery app's own screen from AFTER a delivery, card box
        # or whole screen, offer-shaped or not (its "This offer $8.95" reads as
        # a payout): once while it stays up, stamped with when its frame was
        # TAKEN. Whether it puts an order down is the server's (deliveredArrived).
        # The app in the log, never the customer.
        delivered = OP.delivered_screen(out.get('text'))
        if delivered is not None and delivered_said.fresh(delivered['app'], started):
            if args.json:
                emit_delivered(delivered, at=int(started * 1000))
            log('completion screen read: %s' % delivered['app'])
        if answers:
            dropoff_until = 0.0
            dropoff_asked = False
            if args.json:
                # Kept in the journal only where offers' places are: the
                # stops name people and their doors.
                emit_planner(planner,
                             keep=offer_log is not None and offer_log.keep_places,
                             ms=out.get('ms'), at=seen_at)
            # The kinds, not the names: the log is the rig's, and the stops
            # name people and their doors. Whether one was filed is the
            # server's to say now.
            log('trip planner read: %s; the server files from its sighting'
                % ', '.join(s['kind'] for s in planner))
        elif auto:
            # No window to close and no press to answer: the stops, to the
            # panel and onto the order in the car, said as unasked.
            if args.json:
                emit_planner(planner,
                             keep=offer_log is not None and offer_log.keep_places,
                             ms=out.get('ms'), asked=False, at=seen_at)
            log('trip planner read, unpressed, an order being held: %s'
                % ', '.join(s['kind'] for s in planner))
        if found:
            dropoff_said = found.get('line')
            # Closed the moment it is answered, and what that closes is the
            # READ BEAT below - not this branch.
            #
            # This used to say `dropoff_seen` stopped a second answer on its
            # own, and used that to argue an older comment was naming a job
            # nothing did. `dropoff_seen` was assigned in three places and
            # read in none — so the argument for deleting a line rested on a
            # variable that did no work at all, which is the more expensive
            # half of a comment that lies. What stops a second answer is
            # `dropoff_said`, above, and only for a sighting nobody asked
            # for: a press is a question and always gets answered.
            #
            # What it saves is up to two dozen more forced reads over the
            # rest of the window, and on a Pi a read is several seconds of
            # the whole computer's attention. Left open, the driver presses
            # the button, gets their address, and then finds the rig
            # unresponsive until the twelve seconds run out.
            dropoff_until = 0.0
            # Answered. By ANY address, not only by one off a read the driver
            # asked for — which is what this said first, and it was wrong on
            # the glass.
            #
            # `asked` is `began < dropoff_until`, so a read that begins after
            # the deadline is an unprompted sighting however close behind the
            # press it is. On this rig a read is 1.8s and the window is twelve,
            # so one can straddle the deadline: the press goes unanswered, the
            # very next read finds the address and sends it, and the panel puts
            # it up in green — while the press is still outstanding and the
            # branch below then reports "nothing on that screen read as an
            # address" over the address already showing. Two claims about one
            # press, the second contradicting the first, on the screen the
            # driver is reading in a moving car.
            #
            # What the driver asked was "what is on that screen", and something
            # was. Which read found it is a distinction this button does not
            # have to make; `asked` still travels ON the message, so the server
            # goes on telling a press from a sighting where that matters.
            #
            # Found by a check, not by reading: the empty answer and the found
            # one were both being sent for one press.
            dropoff_asked = False
            if args.json:
                emit_dropoff(found, ms=out.get('ms'), asked=asked,
                             labelled=labelled, text=out.get('text'))
            log('destination read%s: %s'
                % ('' if asked else ' (unprompted, under a Dropoff label)'
                   if labelled else ' (unprompted)', found.get('line')))
        # A whole-screen read has answered the only question it was taken for.
        # Everything below is about an offer — the failure count, the verdict,
        # the health tally, the journal row — and this reading is of the card
        # plus whatever surrounds it, so none of it may be judged from here.
        if whole:
            return False
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
        #
        # ...and not off a screen the parser itself says is no offer
        # (NOT_AN_OFFER): DoorDash's idle screen prints the dash's earnings,
        # "$12.55 This dash … Finding offers", and Uber's "$45.67 You're
        # online", so a payout was there and the beat kept looking at a phone
        # nobody had offered anything on. Measured through main(), 30 s of a
        # still idle screen: 15 reads with the earnings in the box, 2 without
        # (rpi/test_loop.py, "an idle screen showing the dash's earnings").
        card_on_screen = parsed.get('pay') is not None and not parsed.get('notAnOffer')
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
        # ...and not for a screen that is no offer, for the reason the beat is
        # not: the idle screen's earnings armed this burst too, 8 more reads in
        # its first 4 s, of a screen with no leg on it to miss.
        elif parsed.get('pay') and not parsed.get('notAnOffer') \
                and parsed.get('episode') != resample_for:
            resample_for = parsed.get('episode')
            resample_until = time.monotonic() + RESAMPLE_WINDOW
        settled_on = signature
        health.add(out, parsed, out.get('card'), previous_card)
        previous_card = out.get('card')

        # When a read comes back wrong, the one thing worth having is what
        # the reader actually saw. Rate limited, because a screen with no
        # offer on it fails constantly and correctly. On the monotonic clock,
        # with the health window below: both are intervals.
        now = time.monotonic()
        why = read_why(out, parsed)
        if why is not None and (now - last_sample) > SAMPLE_EVERY:
            last_sample = now
            # ...and, on a read the card finder was asked about, what it said:
            # a taller card's payout that is never rescued looks, in the text
            # alone, exactly like a box that read "Pit." with no finder at all.
            log('read %d found nothing usable (%s, %d in a row). Reader saw: %r%s'
                % (frames, why, failures,
                   (out.get('text') or '').strip()[:220],
                   '. Card finder: %s' % out['finder'] if out.get('finder') else ''))
        # ...and a card that showed its payout and no journey keeps its picture
        # and its text, once per card — per accumulator episode — whatever the
        # log's rate limit did. See UNPARSED_DIR. Not off a ⌖ read, and with
        # no clause for it: a whole-screen read has returned above, before
        # anything about an offer is judged.
        if why == NO_JOURNEY and offer_log is not None \
                and parsed.get('episode') is not None \
                and parsed.get('episode') != unparsed_kept_for:
            if save_scan(out.get('fitted'), 'ep%d' % parsed['episode'],
                         os.path.join(scans_where, UNPARSED_DIR),
                         text=out.get('text') or ''):
                unparsed_kept_for = parsed['episode']
        tally = health.report(now, tracker, scanner)
        note_tally(tally)

        if args.json:
            emit(rate, parsed, out['ms'], out['locked'], tracker, scanner, whole=whole,
                 clipped=bool(out.get('clipped')),
                 crop_from=pay_from)
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
        #
        # `is not None` because a read that found no payout is not a card
        # boundary, and treating it as one is the very thing the paragraph
        # forty lines up forbids: "nothing here is cleared by a read that came
        # back empty ... one glare frame during the resample burst would re-arm
        # the gate". It re-armed the gate. accumulate.add() returns the frame
        # untouched and with no episode on it when there is no payout to key on
        # (see its first guard), and `None != seen_episode` is true, so the
        # glare frame opened a new card.
        #
        # The `same_card` guard below hid it for most of a card's life, which is
        # why it lasted: once a reading has LANDED, a later re-read carries the
        # same payout and is recognised. The window it does not cover is the one
        # before the card lands — a card is read, read again to agree, and only
        # then written — and a glare frame inside that window is an ordinary
        # event on a rig whose reads take 1.8s and whose verify beat is 2.5s.
        #
        # Measured against the real loop, one card, glare on reads 2, 4 and 6:
        #
        #   before   1 card on disk, saw 4, kept 1
        #   after    1 card on disk, saw 1, kept 1
        #
        # `saw - kept` is what the offers page turns into "3 times the scanner
        # picked a payout off the screen and never managed to record it - 75% of
        # the 4 it saw. So at least that many offers are missing from everything
        # above." About one card that is sitting in the journal. A figure whose
        # whole job is to say how much the file is missing, reporting misses
        # against a file that is complete.
        episode = parsed.get('episode')
        if episode is not None and episode != seen_episode:
            seen_episode = episode
            seen_pay = False
            seen_kept = False
        if parsed.get('pay') is not None and not seen_pay:
            seen_pay = True
            # Not when it is the card already on disk. The accumulator opens
            # a new episode whenever the payout it reads changes, and one
            # frame reading $16.06 or $1605 for a $16.05 card is a new
            # episode that never locks — so the health line said "3 cards
            # seen, 2 recorded" and the offers page called it a card the
            # scanner failed to record, for one card under one id. The
            # journal's identity, not the accumulator's: the same payout as
            # the card that landed, or a payout that cannot be true, is that
            # card again.
            impossible = OP.doubt(parsed.get('pay'), parsed.get('minutes'),
                                  parsed.get('miles')) is not None
            same_card = (offer_log is not None and offer_log.id is not None
                         and offer_log.landed_id == offer_log.id
                         and (impossible or parsed.get('pay') == offer_log.pay))
            if same_card:
                seen_kept = True
            else:
                health.saw += 1

        if offer_log is not None and rate['ready'] and out['locked']:
            # Asked at the moment the row is written rather than kept on the
            # loop, because that is the moment the position belongs to. `fix()`
            # takes a lock, reads a dict and returns — it never touches the
            # network — so this cannot make a read slow, and it answers None
            # whenever there is no phone, no answer, or an answer too old to
            # stand for where the car is now.
            #
            # ONCE, and the one answer goes to both the row and the offer line
            # below, judged by the gate on the way out of gps.py. It was asked
            # inline in this call, and the line had no position at all.
            where = phone.fix() if phone else None
            written = offer_log.consider(parsed, rate, ms=out['ms']['total'],
                                         locked=out['locked'], whole=whole,
                                         settled=stable, where=where)
            landed = written is not None
            # Nothing written because there was nothing new to say means an
            # earlier reading of this same card already landed, which is still
            # a card that reached the file.
            #
            # `landed_id`, not `id`. `id` is assigned the moment consider()
            # decides a reading is a new card, before the append is even
            # attempted, so it is a fact about this process's memory and not
            # about the disk. With the journal on a path that cannot be written
            # — an SD card remounted read-only mid-shift is the classic Pi
            # failure, and `--journal` pointing at a directory nobody made is
            # the classic setup one — every append raises, `Journal._complain`
            # prints one line and then suppresses itself forever because the
            # message never changes, and this counter said the cards were
            # recorded. Reproduced: eight cards in, zero rows on disk, status
            # line "8 cards seen, 8 recorded". The counter built to say how
            # much the journal missed reported no misses at the moment it was
            # missing all of it — and the `kind: 'seen'` row that carries the
            # tally goes to the same dead file, so nothing downstream can tell
            # either.
            #
            # The id is tested for existence as well, because two Nones are
            # equal and "no card yet" must not count as "this card is on disk".
            if (landed or (offer_log.id is not None
                           and offer_log.landed_id == offer_log.id)) \
                    and not seen_kept:
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
            # ...and, flag or no flag, the read the reader was unsure of. Once
            # per offer: the first doubtful landing is the evidence, and a card
            # read twenty times would otherwise be twenty pictures of one guess.
            if landed and offer_log.id and offer_log.id != doubt_kept_for \
                    and doubted(written):
                if save_scan(out.get('fitted'), offer_log.id,
                             os.path.join(scans_where, DOUBT_DIR)):
                    doubt_kept_for = offer_log.id
            # ...and say which offer that is, once per card rather than once
            # per read. The driving screen holds it so the driver can mark it
            # as taken without going and finding the row afterwards.
            #
            # And again when a LATER reading of the same card lands with more
            # on it. The first locked reading can be a fragment — one leg, 20
            # min / 7.3 mi, no address — and it was frozen as the offer: the
            # panel's stack line, the Drop timer and the pair row were built
            # from it while the offers page showed the corrected 23 min /
            # 8.4 mi with the address. A reading that lands a row and reads
            # differently is told; server.js replaces the offer on record
            # and keeps its mark.
            #
            # The verdict is in the tuple as well, because the offer now carries
            # it (see emit_offer) and ⌖ Dropoff asks on it. Without it a later
            # reading of the same card whose verdict moved for a reason that is
            # not minutes, miles or dropoff — an item count read late, which
            # changes the billed minutes through secondsPerItem and not the
            # card's own; a payout the reader first doubted — was never told,
            # and the panel's headline and the offer beside it disagreed about
            # one card. A PASS that became go lost its ask with nothing saying
            # so. Measured frame by frame over the week's stored scans, frames
            # of one row agreeing on minutes, miles and dropoff and not on the
            # verdict: 1 row of 1,166, so this costs about one line a week.
            if args.json and offer_log.id is not None:
                # ...and the store's door (`pickupLine`): a frame that reads
                # the line under the store's name after the row landed is a
                # pin the map can now place, and untold it never gets there.
                reading = (offer_log.id, parsed.get('minutes'), parsed.get('miles'),
                           parsed.get('dropoff'), rate.get('state'),
                           parsed.get('pickupLine'))
                if offer_log.id != told_offer or (landed and reading != told_as):
                    told_offer = offer_log.id
                    told_as = reading
                    emit_offer(offer_log.id, parsed, rate, where=where,
                               whole=whole, map_label=labels['for'].get(offer_log.id))
                    labels['told'] = (offer_log.id, parsed, rate, where, whole)
                # ...and DoorDash's map label for a card that printed only
                # "Customer dropoff", once per card, AFTER its own line: the
                # read is on MapLabels' thread, and its answer is told on a
                # second offer line (tell_label). Not on a whole-screen read,
                # which is a ⌖ press's question — asked of the GEOMETRY, as
                # MapBands asks it: `whole` by here is OP.is_whole, a card with
                # its whole journey on it, and a DoorDash card read well is
                # exactly that, so "not whole" sent only half-read cards and
                # the reader never saw a good one (the owner's shifts of 26-29
                # Oct: 31 DoorDash offers, not one label read).
                if geom is not None and not getattr(geom, 'whole', False) \
                        and wants_map_label(parsed):
                    map_labels.submit(offer_log.id, frame, geom,
                                      store=[parsed.get('pickup'), parsed.get('pickupLine')])
            # ...and the map band above the card, kept once per offer for the
            # map-geometry study (MAP_BANDS_DIR): every offer card, Uber's and
            # DoorDash's, AFTER its offer line, on MapBands' thread. Collection
            # only — nothing the panel shows comes from it. Not `whole`, which
            # by here is OP.is_whole (a card with its whole journey on it), not
            # a ⌖ read: map_band refuses a whole-screen geometry itself.
            if map_bands is not None and offer_log.id is not None \
                    and geom is not None and not getattr(geom, 'whole', False):
                map_bands.submit(offer_log.id, frame, geom, map_band_meta(
                    offer_log.id, parsed, geom, where=where,
                    keep_places=offer_log.keep_places))

        if args.display:
            cv2.imshow('uber-scan', render_panel(rate, parsed, whole=whole,
                                                 pay_from=pay_from))
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
        if offer_log is None or not worth_recording(tally):
            return
        at = JR.now_ms()
        offer_log.journal.append({
            'v': JR.SCHEMA, 'kind': 'seen', 'at': at,
            # An id and a seq because the sync keys on that pair; without them
            # every one of these would look like the same row to the far end.
            'id': 'seen-%d' % at, 'seq': 1,
            'over': tally.get('over'), 'saw': tally.get('saw'),
            'kept': tally.get('kept'),
            # ...and the destination scan's two blind spots, so they leave the
            # Pi at all. Printing them in the health line puts them in a log on
            # a machine in a car, which is not somewhere the driver can read
            # and not somewhere they can send from; the journal syncs to the
            # NUC on its own. Without this the numbers were dead on arrival —
            # widened into the tally and dropped by the only thing that reads
            # it, which is the fault this project deletes code for.
            #
            # Run totals rather than window totals, so the newest `seen` row
            # carries the whole shift and reading two of them does not mean
            # adding them up.
            'streetNoAddress': tally.get('streetNoAddress'),
            'addressAsOffer': tally.get('addressAsOffer'),
            'addressNotDropoff': tally.get('addressNotDropoff'),
            # ...and how the reading went in the window, which was the rest of
            # the health line and went no further than the log. See
            # Health._window. `reads` and `failed` were in the tally all along
            # and were the two fields of it this row dropped.
            'reads': tally.get('reads'), 'failed': tally.get('failed'),
            'complete': tally.get('complete'), 'noPay': tally.get('noPay'),
            'clipped': tally.get('clipped'), 'rescued': tally.get('rescued'),
            # ...and how many reads were left unread for a black crop (see
            # DARK_SAY_EVERY): on 29 Oct each of those was 16-25s of tesseract.
            'darkSkipped': tally.get('darkSkipped'),
            'medianMs': tally.get('medianMs'),
            'tooDim': tally.get('tooDim'), 'tooBright': tally.get('tooBright'),
            'corners': tally.get('corners'), 'relocks': tally.get('relocks'),
            # ...and how many preview frames since start were the same picture
            # as one just before, which is the measurement the stall watch
            # rests on (see STALL_SAY): nought on a working camera by the
            # suites' sensor model, and no frame off the IMX519 itself has ever
            # been measured. In the tally and dropped here, it reached a log in
            # the car and nothing else; on this row it reaches the copy
            # machine from every shift that read.
            'repeats': tally.get('repeats'),
            # ...and how hot the Pi was and whether it was throttling while
            # these cards went past: a throttled Pi reads slower, and the
            # median above is where that would show.
            **pi.sample(time.monotonic()),
        })

    def collect():
        """Take a finished read, if there is one, and act on it."""
        tell_label()
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
            note_tally(health.report(time.monotonic(), tracker, scanner))
            return False
        batch = done['outs']
        # WHICH frame to publish: the last one that actually read the money.
        #
        # A read hands back two frames 33ms apart, and this published the later
        # one whatever it said. accumulate.add short-circuits on a payout-free
        # frame — it returns the parse untouched with mergedFrom 0 — which the
        # destination branch below deliberately relies on. So when the partner
        # frame was the one that lost its payout to glare or to the crop edge,
        # which the loop counts by name, the whole merge was bypassed for that
        # read.
        #
        # Measured: frame one merges to a complete reading, 23.0 min and 8.4 mi
        # on a $16.05 card; frame two is the same card with the payout gone and
        # publishes complete=False, mergedFrom=0, and a rate that is not ready.
        # The panel paints grey WAITING over a verdict the rig had already
        # worked out, 33 milliseconds earlier.
        #
        # Picking the frame that read the money is the same reasoning the
        # accumulator already applies to legs. When NO frame in the batch has a
        # payout the last one is published exactly as before, which is what the
        # destination branch needs: a genuinely payout-free screen still
        # digests as itself.
        chosen = read_the_money(batch)
        # Kept for a snap's reads.json: what kind of read, as the loop asked
        # for it — see ReadLog.
        geom_done = done.get('geom')
        if not getattr(geom_done, 'whole', False):
            read_kind = 'card box'
        elif getattr(geom_done, 'skip_dark', True) is False:
            read_kind = 'press'
        else:
            read_kind = 'auto whole-screen'
        read_log.add(done.get('at') or time.time(), read_kind, batch[chosen],
                     skipped_dark=batch[chosen].get('skipped') == 'dark')
        # A read PL left unread for a black crop, counted and said here rather
        # than in digest(), which a whole-screen read leaves before the tally.
        # Otherwise it goes on as the empty read it is. See DARK_SAY_EVERY.
        if batch[chosen].get('skipped') == 'dark':
            said = health.not_read_dark(time.monotonic(), batch[chosen].get('peak'))
            if said:
                log(said)
            # ...and a whole-screen one gives the health line its chance here,
            # since digest() returns before asking for it on such a read.
            if getattr(done.get('geom'), 'whole', False):
                note_tally(health.report(time.monotonic(), tracker, scanner))
        # The other frames are evidence: the accumulator merges partial reads,
        # and a leg lost to glare in one frame is often present in the other.
        # Every frame but the chosen one, because digest() adds that one itself
        # and adding it twice would merge a card with a copy of itself.
        #
        # NONE of them from a whole-screen read. That is a question about a
        # destination and nothing else: its text is the card AND the map round
        # it, or a trip planner, and none of that is evidence about an offer's
        # money. digest() answers the press from it and stops.
        whole = bool(getattr(done.get('geom'), 'whole', False))
        if not whole:
            for i, other in enumerate(batch):
                if i != chosen:
                    accumulator.add(other['parsed'])
        return digest(batch[chosen], done['frames'][0], done.get('at'), whole=whole,
                      began=done.get('began'), geom=done.get('geom'))

    # What the server answers GET /api/settings with, from the moment the loop
    # runs. See emit_settings.
    if args.json:
        emit_settings(cfg.get('settings'))

    # Whether the loop ended the way a person ends it. Only then is a stop row
    # written: a crash, and the SIGKILL server.js gives a wedged camera, leave
    # the start with nothing after it, which is the whole of how a reader of
    # the journal tells the two apart. See UpDown.
    clean = False
    try:
        # Here, inside the try, rather than when the journal opens: from this
        # line on, every way out of the loop either writes the stop or is a
        # stop that was not clean, so start and stop bracket exactly the
        # stretch the rig was scanning.
        updown.start(bool(args.gps), uptime())
        while True:
            # A read that finished while the camera kept running. Taken here,
            # at the top, because everything below can `continue` past it.
            if collect():
                break

            # The phone, the GPS and what the camera can see, every pass, on the
            # monotonic clock: the wall clock jumps by decades when NTP arrives,
            # and a hold timed across that would write a minute's absence about
            # a phone that was never gone. Every read here is a lock, a dict or
            # a flag the frame below already set.
            #
            # The box's light is AutoGain's answer, and only where nothing
            # tracks the corners — see the note under STALL_SAY.
            sight = updown.watch(
                time.monotonic(),
                tracker.status()['lost'] if tracker is not None else None,
                gps_now(phone, gps_refused),
                sight_now(frozen,
                          auto_gain.lit if (tracker is None and auto_gain is not None)
                          else None,
                          looked),
                auto_gain.bright if auto_gain is not None else None)
            looked = False
            if sight == 'stalled':
                # Both are this stall's. A camera that came back by itself and
                # stalls again in the same run is asked about afresh: kept from
                # the last one, a stall this run had gone quiet over asked for
                # a second restart seconds after the first, its own note unread.
                stall_held_said = stall_asked = False
                log('camera stalled: it has handed over the same picture, byte '
                    'for byte, for %ds. Nothing new can be read off it; the '
                    'panel says so, and once it has, this '
                    'goes quiet so the supervisor restarts the camera — unless '
                    'it did that less than %ds ago'
                    % (int(time.monotonic() - updown.camera_since), STALL_AGAIN))
            elif sight == 'dark':
                log('too dark to be sure of seeing a card arrive: the box has '
                    'held nothing the gain counts as a lit screen for %ds '
                    '(screen brightness %s/%d), where a light-mode card '
                    'arriving does not move the motion gate far enough to send '
                    'a read — is the phone in the mount, its screen on and '
                    'turned up?'
                    % (int(time.monotonic() - updown.camera_since),
                       '?' if auto_gain.bright is None else '%d' % round(auto_gain.bright),
                       round(EX.TARGET_BRIGHT)))
            elif sight == 'seeing':
                log('the camera can see again')

            # ...and a word to say the loop is turning, on a beat the driving
            # page's staleness test comfortably clears. See ALIVE_EVERY: a
            # verdict is not proof of life, because a still picture produces no
            # reads and a card sitting unchanged produces one every twelve
            # seconds. Emitted before the capture below, so a camera that has
            # stopped delivering frames stops this too — which is exactly the
            # fault worth showing.
            if args.json:
                # Two clocks, for two questions. `now_alive` is a stamp: the
                # stall note's age is a file's mtime against it, and 📷 Snap's
                # reader.json gives the last beat's age off it. `beat_now` times
                # the intervals — the beat and a read in flight — which the wall
                # clock cannot: NTP stepping it back an hour stopped the beat
                # for that hour, and forward an hour wrote a restart row for a
                # reader that was working (rpi/test_loop.py, "a wall clock
                # stepped an hour").
                now_alive = time.time()
                beat_now = time.monotonic()
                quiet = None
                # Whether it is a stall going quiet, which leaves a note.
                over_stall = False
                if reader.busy and reader.since is not None \
                        and beat_now - reader.since > READ_STUCK_S:
                    quiet = ('a read has been in flight for %ds — the reader is '
                             'stuck' % int(beat_now - reader.since))
                elif updown.blind() == 'stalled' and stall_told:
                    # The same way out, for the same reason. A camera that hands
                    # over one picture for ever is not cured by waiting — the
                    # owner's ran 9.4 days that way and a restart cured it at
                    # once — and the supervisor's restart is the cure this rig
                    # already has, counted where a wedge is counted (`wedged`
                    # on /api/status). Only once a beat has carried the stall,
                    # so the panel is holding the reason when the beats stop.
                    #
                    # ...and not again within STALL_AGAIN of the last time, so
                    # a stall a restart does not cure is not restarted all
                    # night. Until then this stays up and goes on beating it.
                    again = None if stall_asked else HO.age(HO.STALLED, now_alive)
                    if again is not None and 0 <= again < STALL_AGAIN:
                        if not stall_held_said:
                            stall_held_said = True
                            log('the camera has stalled again %ds after a run '
                                'here went quiet to be restarted over one; a '
                                'restart has not kept it working, so this stays '
                                'up and says so, and asks again once that is '
                                '%ds old — if it keeps on, reseat the camera\'s '
                                'cable' % (int(again), STALL_AGAIN))
                    else:
                        over_stall = stall_asked = True
                        quiet = ('the camera has handed over the same picture '
                                 'for %ds — it has stalled'
                                 % int(time.monotonic() - updown.camera_since))
                if quiet:
                    # No heartbeat for a rig whose reader or camera has gone:
                    # the silence is the message, and the supervisor restarts
                    # on it. Said once, in the log and in the journal — where
                    # it is the only account the run gets, since the SIGKILL
                    # that answers it leaves no stop row.
                    if not quiet_said:
                        quiet_said = True
                        log('%s; going quiet so the supervisor restarts this'
                            % quiet)
                        updown.restart(quiet)
                        # ...and, over a stall, the note that holds the next
                        # one back — see STALL_AGAIN. One that cannot be
                        # written leaves the next stall restarted as before,
                        # which is said here rather than found out then.
                        if over_stall:
                            try:
                                with open(HO.path(HO.STALLED), 'w'):
                                    pass
                            except (IOError, OSError) as e:
                                log('could not leave the note that holds back '
                                    'the next restart over a stall (%s)' % e)
                elif beat_now - last_alive > ALIVE_EVERY or sight:
                    # ...and at once, not on the beat, when what the camera can
                    # see has changed. The panel puts a blind rig's word where
                    # the verdict goes, and a card arriving as the phone goes
                    # back in the mount must not wait four seconds behind the
                    # word that it cannot see.
                    quiet_said = False
                    last_alive = beat_now
                    flags = {'too_bright': health.too_bright,
                             'too_dim': health.too_dim,
                             'not_saving': not_saving_notice(offer_log),
                             'blind': updown.blind()}
                    # ...and what the rig says about itself: whether the GPS
                    # fix is fresh, the Pi's temperature and throttling. Kept
                    # with the flags so 📷 Snap's reader.json says everything
                    # the panel was told, not five of its seven things. The
                    # newest position rides inside `gps`, on the beat that
                    # already travels to the panel and /api/status.
                    #
                    # ...and the heat guard, after the sample, which is the
                    # one that may have just moved it: the beat says the state
                    # its own `cpuC` and `throttled` put the guard in.
                    pi_now = pi.sample(time.monotonic())
                    extra = {'gps': updown.beat(beat_fix(phone)),
                             'pi': pi_now, 'heat_guard': pi.guard.on}
                    emit_alive(**dict(flags, **extra))
                    last_beat = (now_alive, flags, extra)
                    stall_told = flags['blind'] == 'stalled'

            # 📷 Snap, asking for what only this process has. Here, after the
            # read that finished and before the capture, so the answer is the
            # newest read there is and costs the camera nothing. See
            # snap_requested; the server waits four seconds for it.
            snap_to = snap_requested()
            if snap_to is not None:
                now_snap = time.time()
                answer_snap(snap_to, last_read, reader_record(
                    last_read, now_snap, offer_log=offer_log,
                    # The health window is timed on the monotonic clock
                    # (Health.report's callers), and so is how long it has run.
                    counters=health.counters(time.monotonic()), beat=last_beat,
                    phone=phone),
                    # ...and the newest offer's map band, when one was kept
                    # in the last two minutes (MAP_BANDS_DIR).
                    band=map_bands.latest(now_snap) if map_bands is not None else None,
                    # ...and the richer snap's two (EXPERIMENTAL): the last
                    # reads, and the newest full-resolution frame, encoded on a
                    # thread of its own when reads have one.
                    reads=read_log.snapshot(),
                    frame=full_frame,
                    threaded=not args.no_thread)
            request = cam.capture_request()
            try:
                # The Y plane leads the YUV420 buffer, and luma is all the gate
                # needs. Taken from the flat buffer rather than a reshaped array
                # so the chroma planes cannot be mistaken for image rows.
                buf = request.make_buffer('lores')
                luma = np.frombuffer(buf, dtype=np.uint8,
                                     count=LORES[0] * LORES[1]).reshape((LORES[1], LORES[0]))
                # The same picture as one of the last few, byte for byte, which
                # a live sensor never hands over — see STALL_SAY and Repeats.
                # Counted for the whole run, so the health line can say whether
                # this camera ever does.
                frozen = repeats.seen(luma)
                health.repeats += frozen
                # The frame's clock for every INTERVAL below — the camera's
                # tick, the ⌖ window, the resample and verify beats, the
                # tracker's recheck and dispute, the gain's beat, the live
                # view's period — and so the monotonic one. On the wall clock a
                # backward NTP step held every one of them shut until the clock
                # caught up again: measured through main() with the clock put
                # back an hour, a second ⌖ press got 1 whole-screen read in its
                # 3 s window against 7, the one its own pass makes. Nothing
                # here is written anywhere; the read's own stamp is taken off
                # the wall clock where it is handed over, below.
                now = time.monotonic()
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
                # The window runs from the PRESS, not from this pass: what
                # dropoff_requested hands back is what is left of it.
                dropoff_left = dropoff_requested()
                if dropoff_left is not None:
                    dropoff_until = now + dropoff_left
                    dropoff_asked = True
                    # `do_read` here looks redundant against the beat further
                    # down, and on the FIRST press it is: last_dropoff_read
                    # starts at 0.0, so the beat fires on this same pass. It is
                    # not redundant on a second press within half a second of
                    # the last read of the first window, which is the only case
                    # that separates them - worth half a second, not worth a
                    # timing-sensitive test, and written down so it does not get
                    # deleted as dead on the strength of the first press alone.
                    moved = do_read = True
                    log('reading the destination for the next %.1f seconds: '
                        'put the address on the phone' % dropoff_left)

                # A cost per mile typed on the keypad. Taken in the loop, never
                # by a restart: a restart costs an aim-and-calibrate cycle, which
                # is a minute of no readings mid-shift for a change of one
                # number. Written into the same dict digest() reads per card —
                # in place, so there is only ever the one — and saved, so the
                # next start begins from it.
                #
                # And read again now, for the reason the drawn box below is: a
                # card sitting still on the phone produces no motion, and the
                # panel would go on saying "after $0.30/mi costs" under it until
                # the next verify beat. That string is how the driver sees the
                # change take effect, so it should take effect on the card in
                # front of them. The journal does not grow for it: consider()
                # decides novelty on the reading's content, which the cost is
                # not part of.
                cost = settings_requested()
                if cost is not None:
                    live = cfg.setdefault('settings', {})
                    was = OP.setting(live.get('costPerMile'),
                                     OP.DEFAULT_SETTINGS['costPerMile'])
                    live['costPerMile'] = cost
                    save_config(args.config, cfg)
                    if args.json:
                        emit_settings(live)
                    moved = do_read = True
                    log('cost per mile set to $%.2f from a screen (was $%.2f): '
                        'the next reading is costed at it' % (cost, was))

                # A box drawn on the live view. It arrives as fractions of the
                # frame, which is the only form that survives the trip: what the
                # driver drew on was a 480px JPEG of a 2328px sensor frame.
                taken = CX.take_request()
                if taken is not None:
                    drawn, card = taken
                    manual = True
                    use_manual_box(scanner, CX.in_pixels(drawn, capture_size), card)
                    CX.apply_to_config(cfg, drawn, capture_size, card)
                    save_config(args.config, cfg)
                    tracker = None
                    # Read it now. The whole crop just changed, and the motion
                    # gate cannot tell — it watches the frame, and the frame is
                    # a card sitting still, which is exactly what it looks like
                    # while somebody draws a box round it. Without this, pressing
                    # "read this box" does nothing visible until the picture next
                    # moves, which reads as the button not having worked.
                    moved = do_read = True
                    log('crop box set by hand to [%s] of the frame: %s, with corner '
                        'tracking off — ▣ Set box again to change it'
                        % (CX.describe(drawn),
                           'offers read in the card box [%.2f %.2f %.2f %.2f] of it and '
                           '⌖ reading all of it' % tuple(card) if card
                           else 'reading exactly that'))
                    log(card_finder_says(scanner, card_finder_off(cfg, args), args.config))

                # Follow the phone on this same small frame. A mount is not a
                # clamp, and corners a centimetre out slide the crop off the
                # payout — which looks exactly like no offer being on screen.
                #
                # Done here, on the stream the motion gate already has, it costs
                # about a millisecond and needs no full-resolution capture at
                # all; finding the corners on a sensor frame costs seven times
                # as much, almost entirely in shrinking the frame down to this
                # size. Blurred frames are skipped: a smeared edge is a worse
                # guess than the corners already held.
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
                            'moved onto it and the SIZE the tracker judges against '
                            'taken as out of date. The calibration itself is kept. '
                            'Reading carries on — but draw the boxes with ▣ Set '
                            'box, or re-run calibration, when you can, or the '
                            'next start will be stuck again.' % TR.RECOVER_AFTER)
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
                        log(('outline stuck: the corners have been off the screen '
                             'the camera can see for %ds. If the box is drawn '
                             'round part of the offer card rather than the whole '
                             'phone, the screen is probably washed out — shade it '
                             'or dim it. Otherwise draw the boxes with ▣ Set box '
                             'on the live page, or re-run calibration.'
                             % TR.STALL_VISIBLE)
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
                    ctrls = auto_gain.update(lit, now, has_screen=have_screen)
                    # The photometric picture, before any preprocessing — the
                    # same window and the same measure the controller steers
                    # by, so the health line's number is the controller's
                    # number.
                    #
                    # Taken FROM the controller now rather than measured again
                    # beside it. `brightness` is a percentile: a full
                    # order-statistic pass in float32 over the card window,
                    # which update() performs anyway on the very same array —
                    # so this line was a second identical pass on every frame
                    # the camera produced, all shift, for a figure the log
                    # prints once every two minutes.
                    #
                    # It also makes the sentence above true rather than merely
                    # likely. Two derivations of one measurement agree until
                    # one of them changes, and this is the pair the comment was
                    # already claiming were the same.
                    #
                    # Left alone when the beat did not run: update() returns
                    # early between beats without measuring, and `bright` is
                    # then about an older frame. The health line keeps the last
                    # figure it had, which is what it did before.
                    if auto_gain.bright is not None:
                        health.bright = auto_gain.bright
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

                # ...and the whole-screen read digest() asked for, whether the
                # picture moved or not: a planner or a navigation screen sits
                # still on the phone.
                if not do_read and screen_auto:
                    do_read = True

                # ...and a window that closes with nothing on it SAYS SO.
                #
                # The rig emitted only from inside `if found:`, so a press that
                # found no address produced no line at all, and the panel's own
                # timer put the button back exactly as it was. The driver tapped
                # the address open on their phone, pressed, waited, and got the
                # same grey button whether it had worked or not. Every other
                # control on that bar names its failure.
                #
                # Not curable on the page, which is where it was tried first. A
                # read that STARTED inside the window still counts — that is
                # what `asked` means — and a read is 1.8s median and has been
                # measured at 5.9s, so an answer can land a good six seconds
                # after the window shut, well past any timer the page could
                # set. A page saying "not read" and then being corrected by a
                # green address a moment later is this project's first fault
                # class, on the panel, to cure its second.
                #
                # So the wait here is the same predicate `asked` is: a read
                # that began before the deadline can still answer, and nothing
                # that began after it ever will. Once no such read is left in
                # flight, the question has an answer and the answer is no.
                if dropoff_asked and now >= dropoff_until \
                        and not (reader.busy and reader.since is not None
                                 and reader.since < dropoff_until):
                    dropoff_asked = False
                    if args.json:
                        emit_dropoff(None, asked=True)
                    log('nothing on that screen read as an address')

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
                #
                # Deferred, not dropped — the same rule the branch below states
                # and for the same reason, which this one was breaking four
                # lines above it. should_read() fires exactly once per card, on
                # the frame the picture settles, and the tracker only updates on
                # settled frames: so a new card's trigger and the dispute it
                # causes are born on the SAME frame. The card changes the bright
                # geometry, the detector's answer moves further than MAX_JUMP,
                # and that frame's read is cancelled with nothing left to
                # re-arm it.
                #
                # Driven with the real tracker against a detector alternating
                # between two positions 30 lores pixels apart: disputing() stays
                # true for the whole 2.0s of DISPUTE_PATIENCE with no jump and
                # no move, so nothing sets `moved` and nothing revives the read.
                # On an idle screen before the card, `card_on_screen` is false
                # and `resample_until` is zero, so the offer simply sits unread
                # until the picture moves again. With a previous card still up,
                # the verify beat recovers it — after up to VERIFY_MAX seconds
                # of showing the previous card's verdict.
                if do_read and not moved and tracker is not None \
                        and tracker.disputing(now):
                    read_wanted, do_read = True, False

                # ...and nothing at all off a camera that has stalled. Its
                # picture is the past: frozen on an offer card, the verify beat
                # went on re-reading that card and every verdict came back
                # looking fresh. It is also the silence the restart needs:
                # server.js counts a reading, and the `reading` notice every
                # read sends, as the loop speaking, so a frozen card read every
                # few seconds would keep its watchdog from ever firing. Dropped,
                # not deferred: there is nothing new to read until the camera
                # is.
                if updown.blind() == 'stalled':
                    read_wanted, do_read = False, False

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
                # sensor frame, and pays for it by composing fifteen times a
                # second instead of the scene view's thirty — SNAPSHOT_SCREEN,
                # or what --screen-fps asks, against SNAPSHOT_FAST. Only
                # while somebody is actually looking at it; the moment they stop
                # asking, `watching()` says so and this goes back to the
                # preview.
                want_sensor = due and seen_by and want_view == VIEW_SCREEN
                if do_read or want_sensor:
                    # picamera2's "RGB888" hands back B, G, R ordered arrays,
                    # which is exactly what OpenCV expects. The name is the odd
                    # one out.
                    frame, preview_scale = request.make_array('main'), None
                    full_frame = {'frame': frame, 'at': time.time(), 'source': 'sensor'}
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
                               scale=preview_scale, found=found_box,
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
            #
            # While a ⌖ press is open, all of the screen box rather than the
            # card crop: the press asks "what is on this screen", and a trip
            # planner's addresses are outside where the offer cards land. A
            # card box drawn by hand made that a blind spot — see
            # cropbox.parse_card. Only while asked: an unprompted read is
            # hunting offers and keeps the card crop.
            # ...and for the whole-screen read digest() asked for without a
            # press (`screen_auto`), once: the request is spent by this
            # hand-over.
            pressed_read = dropoff_asked and time.monotonic() < dropoff_until
            whole_read = pressed_read or screen_auto
            screen_auto = False
            # ...and a ⌖ press's read is read however dark the crop: the driver
            # asked, so the reader is asked. Every other read — the card box,
            # the verify beat, the whole-screen read nobody pressed for — skips
            # a crop with nothing bright enough in it to be text. See
            # PL.DARK_SKIP_BELOW and DARK_SAY_EVERY.
            reader.submit([frame] if partner is None else [frame, partner],
                          time.time(),
                          scanner.geometry(whole=whole_read,
                                           skip_dark=not pressed_read))
            looked = True
            # Before the read, not after it. The dashboard has nothing else to
            # go on for the second and a half this takes — see emit_reading.
            #
            # Not for a ⌖ read. It is a read of the whole screen for an
            # address, digest() returns before emit() for it, so nothing
            # carrying `ready` ever followed — and the panel said READING THE
            # CARD, "working out the pay, the time and the distance", for its
            # whole 8s READING_MS after every one, through the twelve-second
            # window, over a navigation screen. The ⌖ button says "⌖ reading…"
            # for that read itself.
            if args.json and not whole_read:
                emit_reading()
            if not reader.threaded and collect():
                break
        # Out of the loop by its own `break`: the display window was closed,
        # which is a person ending it.
        clean = True
    except (KeyboardInterrupt, SystemExit):
        # ctrl-c, or the supervisor's SIGTERM turned into SystemExit by
        # _stop_on_sigterm. Anything else that gets here is a crash and is
        # left to say so by having no stop row.
        clean = True
    finally:
        # Written before anything below that can hang on the way out. Once
        # the loop has agreed to stop, a camera that will not close is a
        # different fault from one that never stopped.
        if clean:
            updown.stop()
        reader.close()
        map_labels.close()
        if map_bands is not None:
            map_bands.close()
        if phone is not None:
            phone.stop()
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
                'rate': 'CHECK PAY & TIME',
                # The TIME, because that is what is wrong with it: the reading
                # is over one leg of a journey the card printed two of, so the
                # minutes are the drive to the rider and the rate is the job's
                # several times over. The driving screen has said exactly this
                # since `leg` was added and this table was not given it, so a
                # card whose trip leg failed to read was named on the 800x480
                # panel and "READ AGAIN" on the hat beside it.
                'leg': 'CHECK TIME',
                # Not a figure to check — there is no offer to check it
                # against. Uber's route planner and DoorDash's idle screen both
                # reached this panel with a payout on them, at $68.18/hr in
                # green and $376.50/hr. "CHECK PAY" would send the driver
                # looking for a card that is not there. See NOT_AN_OFFER.
                'screen': 'NOT AN OFFER'}



# The card's own figures, as a line, with a gap where a card said nothing.
#
# `'%s min' % None` prints the literal word "None", and on a delivery card that
# is not an edge case: Uber and DoorDash both state a DEADLINE and no duration,
# so `parsed['minutes']` is None on the whole of that half of a shift. The rig's
# own screen drew `$12.00  None min  2.4 mi` under a green ACCEPT.
#
# A dash, which is what every other screen here draws for a figure that is not
# there, and what the driver already reads as "the card did not say".
def _found_mark(pay_from):
    """After the payout on render_panel's figures line: " ?" when a found
    card gave it (payout_from), nothing otherwise."""
    return ' ?' if pay_from == 'found' else ''


def _fig(value, places=1):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return '--'
    return ('%%.%df' % places) % value


# A figures line, at its size or smaller, so that it ends inside the panel.
#
# cv2.putText draws past the edge without complaint, and what goes over is the
# end of the line: the miles. The doubt panel's line at its own size, for a
# four-figure payout off a found card — "$1999.99 ?  120.0 min  45.3 mi" — ended
# at x=835 on the 800px panel, so the driver read "45.3" with the unit gone, or
# less. A four-figure payout is what that panel is FOR (CHECK PAY). Smaller
# rather than shorter: every figure on the line is one the driver may need to
# hold against the card, and a usual card's line is not touched — the scale
# only comes down when the line would not fit, by as much as it has to.
def _put_line(panel, text, org, scale, thick):
    room = panel.shape[1] - 2 * org[0]          # the left margin, kept on the right
    while scale > 0.5 and cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX,
                                          scale, thick)[0][0] > room:
        scale -= 0.05
    cv2.putText(panel, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), thick)


def render_panel(rate, parsed, size=(800, 480), whole=True, pay_from='drawn'):
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

    `pay_from` is payout_from's answer, and 'found' puts a "?" after the
    payout — the payout was read off a card found above the drawn card box,
    not off the box. live.html labels the same figure PAY ? for the same
    reason; a driver reading both screens is told the same thing on each.
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
        # The card's own numbers here, deliberately — see above. What is not
        # deliberate is printing the word "None" where it said nothing.
        _put_line(panel, '$%.2f%s  %s min  %s mi'
                  % (parsed['pay'], _found_mark(pay_from), _fig(parsed['minutes']),
                     _fig(parsed['miles'])), (40, 300), 1.8, 4)
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
    # The figures the RATE above was worked out over, not the ones the parser
    # first read.
    #
    # This drew `parsed['minutes']`, which is what the card printed as a
    # duration — and a delivery card prints a deadline instead, so on the whole
    # DoorDash half of a shift it was None and this line read `$12.00  None min
    # 2.4 mi` beneath a green ACCEPT at $36/hr. The rate had a perfectly good
    # twenty minutes; it just was not the field being drawn.
    #
    # emit() has always sent the verdict's own figures to the web page, which
    # is why that screen has been right about these cards and this one has not:
    # a driver checking one against the other was reading two different fields
    # with the same label. Same source now.
    _put_line(panel, '$%.2f%s  %s min  %s mi'
              % (parsed['pay'], _found_mark(pay_from),
                 _fig(rate.get('minutes', parsed.get('minutes'))),
                 _fig(rate.get('miles', parsed.get('miles')))), (40, 400), 1.4, 3)
    return panel


if __name__ == '__main__':
    main()
