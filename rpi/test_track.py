"""Tests for following the phone as it drifts.

    python3 rpi/test_track.py

Frames are synthesised — a bright rectangle on a dark ground, which is what the
detector actually keys on — so this runs anywhere OpenCV does.
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2

import track as T

ok = bad = 0

W, H = 1200, 900
PHONE = (300, 620)          # a portrait phone, comfortably inside the frame


def eq(name, got, want):
    global ok, bad
    good = got == want or (isinstance(want, float) and isinstance(got, (int, float))
                           and abs(got - want) < 0.51)
    if good:
        ok += 1
    else:
        bad += 1
        print('FAIL  %s: got %r want %r' % (name, got, want))


def ok_(name, cond):
    eq(name, bool(cond), True)


def frame_with_phone(x, y, size=PHONE):
    """A lit screen at (x, y), on a dark surround, with some texture on it."""
    frame = np.full((H, W, 3), 22, np.uint8)
    w, h = size
    cv2.rectangle(frame, (x, y), (x + w, y + h), (238, 240, 238), -1)
    for i in range(6):        # card-ish content, so it is not a flat block
        cv2.rectangle(frame, (x + 20, y + 320 + i * 45),
                      (x + w - 20, y + 336 + i * 45), (90, 90, 90), -1)
    return frame


def quad_at(x, y, size=PHONE):
    w, h = size
    return np.float32([[x, y], [x + w, y], [x + w, y + h], [x, y + h]])


def settle(tracker, frame, checks, t0=0.0, step=2.0):
    """Run `checks` updates far enough apart to clear the recheck interval."""
    moved = 0
    for i in range(checks):
        if tracker.update(frame, now=t0 + step * (i + 1)):
            moved += 1
    return moved


# --- the detector has to find the synthetic phone at all --------------------
import pipeline as PL                                       # noqa: E402

found = PL.detect_screen_quad(frame_with_phone(400, 140), work_width=PL.DETECT_WIDTH)
ok_('detects the synthetic phone', found is not None)
# Detecting on a 640px thumbnail of a 1200px frame quantises the corners to
# about two capture pixels; on a 620px phone that is well under a percent.
ok_('detected corners land on it', T.distance(found, quad_at(400, 140)) < 5.0)

# The thumbnail path must agree with the full-resolution one, or every tracked
# quad would be quietly offset from the calibrated one.
full = PL.detect_screen_quad(frame_with_phone(400, 140))
ok_('thumbnail detection agrees with full', T.distance(found, full) < 4.0)

# --- nothing moves until the same thing is seen repeatedly ------------------
start = quad_at(400, 140)
tr = T.QuadTracker(start)
drifted = frame_with_phone(418, 152)
eq('first check does not move it', tr.update(drifted, now=1.0), False)
eq('nor the second', tr.update(drifted, now=3.0), False)
eq('the third does', tr.update(drifted, now=5.0), True)
ok_('and it moved toward the phone, not onto it',
    0 < T.distance(tr.quad, start) < T.distance(start, quad_at(418, 152)))

# --- and it converges if the phone stays there ------------------------------
settle(tr, drifted, 8, t0=5.0)
ok_('converges on the new position', T.distance(tr.quad, quad_at(418, 152)) < 4.0)
ok_('counted the moves', tr.moves >= 4)
eq('drift is not a re-lock', tr.jumps, 0)

# --- the recheck interval is honoured ---------------------------------------
tr = T.QuadTracker(start)
for i in range(30):
    tr.update(drifted, now=10.0 + i * 0.1)      # 3s of frames, 0.1s apart
eq('rapid frames collapse into few checks', tr.moves, 0)

# --- one bad frame cannot steal the corners ---------------------------------
tr = T.QuadTracker(start)
settle(tr, frame_with_phone(402, 142), 4)
before = tr.quad.copy()
# A hand, a windscreen reflection: something bright and elsewhere, once.
tr.update(frame_with_phone(60, 400, size=(280, 300)), now=100.0)
eq('a single intruder moves nothing', T.distance(tr.quad, before), 0.0)
settle(tr, frame_with_phone(402, 142), 3, t0=100.0)
ok_('and the real phone is still held', T.distance(tr.quad, quad_at(402, 142)) < 12.0)

# --- a screen that is simply gone leaves the calibration alone --------------
tr = T.QuadTracker(start)
dark = np.full((H, W, 3), 20, np.uint8)
settle(tr, dark, 5)
eq('a dark frame never moves the corners', T.distance(tr.quad, start), 0.0)
ok_('but it is reported as lost', tr.status()['lost'])
settle(tr, frame_with_phone(400, 140), 4, t0=200.0)
eq('and recovers when the screen comes back', tr.status()['misses'], 0)

# --- a real knock is adopted outright, not eased ----------------------------
tr = T.QuadTracker(start)
knocked = frame_with_phone(700, 220)
moved = settle(tr, knocked, 8)
ok_('a sustained move is taken', moved >= 1)
ok_('and taken whole', T.distance(tr.quad, quad_at(700, 220)) < 5.0)
eq('recorded as a re-lock', tr.jumps, 1)
# Two checks is not sustained: the far position must not be adopted early.
tr2 = T.QuadTracker(start)
settle(tr2, knocked, 5)
eq('but not before it has insisted', T.distance(tr2.quad, start), 0.0)

# --- saving is rate limited and drift limited -------------------------------
tr = T.QuadTracker(start)
eq('nothing to save at rest', tr.needs_save(now=1000.0), False)
tr.quad = quad_at(403, 143)
eq('a nudge is not worth a write', tr.needs_save(now=1000.0), False)
tr.quad = quad_at(430, 170)
eq('a real drift is', tr.needs_save(now=1000.0), True)
tr.mark_saved(now=1000.0)
eq('saving clears it', tr.needs_save(now=1001.0), False)
tr.quad = quad_at(480, 220)
eq('and it will not write again immediately', tr.needs_save(now=1010.0), False)
eq('but will once the interval passes', tr.needs_save(now=1040.0), True)

# --- geometry ---------------------------------------------------------------
eq('distance of a quad to itself', T.distance(start, start), 0.0)
eq('shifting by 10px reads as 10px', round(T.distance(start, quad_at(410, 140))), 10.0)
ok_('near() scales with the screen', T.near(quad_at(400, 160), start, 0.10))
ok_('...and rejects a real jump', not T.near(quad_at(400, 400), start, 0.10))
half = T.ease_toward(start, quad_at(500, 140), 0.5)
eq('easing halfway lands halfway', round(T.distance(half, quad_at(450, 140))), 0.0)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d tracker checks passed' % ok)
sys.exit(1 if bad else 0)
