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
    # Card-ish content, so it is not a flat block. Placed as a fraction of the
    # phone rather than at fixed offsets, or a smaller phone gets its text
    # painted on the dark ground underneath it and stops being detectable at
    # all — which would make a shrunken-candidate test pass for the wrong
    # reason.
    for i in range(6):
        top = y + int(h * (0.52 + i * 0.072))
        cv2.rectangle(frame, (x + w // 15, top),
                      (x + w - w // 15, top + max(3, h // 40)), (90, 90, 90), -1)
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

# --- a real move is not believed until it is repeated -----------------------
start = quad_at(400, 140)
SPAN = T.span(start)
MOVED = (460, 180)          # far enough to be a move rather than a nudge
ok_('the test move is a move, not a nudge',
    T.NUDGE * SPAN < T.distance(start, quad_at(*MOVED)) < T.MAX_JUMP * SPAN)

tr = T.QuadTracker(start)
drifted = frame_with_phone(*MOVED)
for i in range(T.AGREE - 1):
    eq('check %d does not move it' % (i + 1), tr.update(drifted, now=1.0 + 2.0 * i), False)
eq('the last one does', tr.update(drifted, now=1.0 + 2.0 * (T.AGREE - 1)), True)
ok_('and it moved toward the phone, not onto it',
    0 < T.distance(tr.quad, start) < T.distance(start, quad_at(*MOVED)))

# --- and it converges if the phone stays there ------------------------------
settle(tr, drifted, 8, t0=40.0)
ok_('converges on the new position', T.distance(tr.quad, quad_at(*MOVED)) < 4.0)
ok_('counted the moves', tr.moves >= 4)
eq('drift is not a re-lock', tr.jumps, 0)

# --- but a nudge is followed at once ----------------------------------------
# A candidate a hair from the corners and the same size as them is the screen;
# there is nothing else it could be, since anything else is excluded by one of
# those two tests. Waiting for five checks to agree before following it is four
# checks of the outline visibly lagging the phone for no gain.
nudged_at = (409, 147)
ok_('the test nudge is a nudge', T.distance(start, quad_at(*nudged_at)) < T.NUDGE * SPAN)
tr = T.QuadTracker(start)
eq('a nudge moves on the first check', tr.update(frame_with_phone(*nudged_at), now=1.0), True)
ok_('...toward it', 0 < T.distance(tr.quad, start))

# --- the recheck interval is honoured ---------------------------------------
# Frames arrive far faster than the corners are re-found, and adopting a move
# takes AGREE checks however many frames went past in the meantime.
tr = T.QuadTracker(start)
window = T.RECHECK_EVERY * (T.AGREE - 1) * 0.9      # just short of enough
for i in range(200):
    tr.update(drifted, now=10.0 + i * (window / 200.0))
eq('rapid frames cannot rush a move', tr.moves, 0)

# --- a nearby candidate of the wrong size is refused ------------------------
# The failure this stops is quiet and cumulative. Easing has no floor, so a
# candidate a fifth too small sits inside MAX_JUMP and could be followed a
# third of the way at a time, walking the outline down onto the white card or
# the lit half of a dimmed screen. Every step looks reasonable and the end
# state is a green box too small, with a crop measured against it.
tr = T.QuadTracker(start)
shrunk = (300 - 90, 620 - 190)         # same centre-ish, a third smaller
ok_('the shrunken candidate is nearby by the distance test',
    T.near(quad_at(445, 235, shrunk), start, T.MAX_JUMP))
ok_('...but not the same size', not T.same_size(quad_at(445, 235, shrunk), start))
settle(tr, frame_with_phone(445, 235, shrunk), 12)
eq('so the corners are left alone', tr.moves, 0)
ok_('and stay where they were', T.distance(tr.quad, start) < 0.01)
# And refused however long it insists, which is the part that matters.
eq('...and it is not adopted as a re-lock either', tr.jumps, 0)
# Its evidence does not survive the refusal either. `agreeing` counts checks
# that saw the same thing; leaving it standing let a run of refused candidates
# walk the counter to the bar, so the first one that squeaked through moved the
# corners on sight with the authority of ten sightings of something else.
eq('and it banks no evidence on the way', tr.agreeing, 0)
settle(tr, frame_with_phone(*MOVED), 1, t0=500.0)
eq('so the next real candidate starts from scratch', tr.moves, 0)

# --- one bad frame cannot steal the corners ---------------------------------
tr = T.QuadTracker(start)
settle(tr, frame_with_phone(402, 142), T.AGREE + 1)
before = tr.quad.copy()
# A hand, a windscreen reflection: something bright and elsewhere, once.
tr.update(frame_with_phone(60, 400, size=(280, 300)), now=100.0)
eq('a single intruder moves nothing', T.distance(tr.quad, before), 0.0)
settle(tr, frame_with_phone(402, 142), T.AGREE + 1, t0=100.0)
ok_('and the real phone is still held', T.distance(tr.quad, quad_at(402, 142)) < 12.0)

# --- a screen that is simply gone leaves the calibration alone --------------
tr = T.QuadTracker(start)
dark = np.full((H, W, 3), 20, np.uint8)
settle(tr, dark, 5)
eq('a dark frame never moves the corners', T.distance(tr.quad, start), 0.0)
ok_('but it is reported as lost', tr.status()['lost'])
settle(tr, frame_with_phone(400, 140), T.AGREE + 1, t0=200.0)
eq('and recovers when the screen comes back', tr.status()['misses'], 0)

# --- a real knock is adopted outright, not eased ----------------------------
# The phone taken out and put back is the same event as the mount being
# knocked, and it is the one the driver actually notices. It used to need
# twice the agreement of any other move, which measured out at 93% of a 4.2s
# recovery - and nearer 10s on a Pi, where a read in flight stops the loop
# honouring the recheck interval at all. The shape gate makes that caution
# redundant, so it is the same bar as everything else.
tr = T.QuadTracker(start)
knocked = frame_with_phone(700, 220)
moved = settle(tr, knocked, T.AGREE + 2)
ok_('a sustained move is taken', moved >= 1)
ok_('and taken whole', T.distance(tr.quad, quad_at(700, 220)) < 5.0)
eq('recorded as a re-lock', tr.jumps, 1)
tr2 = T.QuadTracker(start)
settle(tr2, knocked, T.AGREE - 1)
eq('but not before it has insisted', T.distance(tr2.quad, start), 0.0)

# --- shape, which a diagonal cannot see -------------------------------------
# span() is the mean of the diagonals, and a diagonal is one number about a
# rectangle that needs two. This is the exact geometry a rig was photographed
# wearing: its outline on the Accept button and the dark strip beneath it,
# with a readable offer sitting above, untouched.
phone_q = np.float32([[100, 100], [795, 100], [795, 1612], [100, 1612]])   # 695x1512
strip_q = np.float32([[100, 100], [1440, 100], [1440, 330], [100, 330]])   # 1340x230
ok_('a flat strip passes for the right size', T.same_size(strip_q, phone_q))
ok_('...which is why size alone was never the guard', not T.same_shape(strip_q, phone_q))
dimmer = np.float32([[100, 100], [795, 100], [795, 1400], [100, 1400]])    # 695x1300
ok_('a dimmed screen is still the same shape', T.same_shape(dimmer, phone_q))
angled = np.float32([[100, 100], [760, 100], [760, 1550], [100, 1550]])    # 660x1450
ok_('and so is one seen from a slight angle', T.same_shape(angled, phone_q))

# --- the gate is anchored, so it cannot be walked downhill ------------------
# A relative test has no floor: every step is "the same size as the last", and
# the corners walk off the phone one reasonable step at a time. Worse, once
# they have, the real phone is *bigger* than the band allows the other way, so
# the thing being looked for is the one thing that can no longer be accepted.
tr = T.QuadTracker(start)
here = quad_at(400, 140)
ok_('the calibration is kept', T.distance(tr.calibrated, here) < 0.01)
w, h = PHONE
step = 0.0
for _ in range(6):
    w, h = int(w * 0.82), int(h * 0.82)
    settle(tr, frame_with_phone(400 + (PHONE[0] - w) // 2, 140 + (PHONE[1] - h) // 2,
                                (w, h)), 8, t0=step)
    step += 40.0
ok_('six shrinking candidates do not compound',
    T.span(tr.quad) / T.span(here) > T.SIZE_BAND[0] - 0.01)
# ...and the phone is still acceptable afterwards, which is the whole point.
ok_('the real screen is still recognised', tr.looks_like_the_screen(here))
settle(tr, frame_with_phone(400, 140), 12, t0=step + 40.0)
ok_('so it comes back', T.distance(tr.quad, here) < 20.0)

# --- the band has to answer the same question both ways round --------------
# A band is asked "is this candidate right for that screen" and later "is that
# screen right for this candidate". 1/0.78 is 1.2821, so a rounded 1.28 made
# those two disagree in a sliver — and a rig held in the sliver watched the
# phone sit plainly in frame for 1500 checks without moving.
lo, hi = T.SIZE_BAND
ok_('the band is self-inverse', abs(hi - 1.0 / lo) < 1e-9)
# Just inside the bound rather than exactly on it: float32 corners land a few
# parts in ten million either side of an exact ratio, so testing the knife
# edge tests the rounding rather than the rule.
centre = start.mean(axis=0)
edge = (centre + (start - centre) * (lo * 1.001)).astype(np.float32)
ok_('a quad at the bottom of the band is accepted', T.same_size(edge, start))
ok_('...and can still accept the screen back', T.same_size(start, edge))
# Stated directly: whatever ratio the band accepts, it must accept the inverse,
# or there is a sliver where A can adopt B and B can never adopt A back.
ok_('every accepted ratio has an accepted inverse',
    all(lo <= 1.0 / r <= hi for r in (lo, 1.0, hi, 0.9, 1.1)))
ok_('...which a rounded 1.28 would fail', not (lo <= 1.0 / lo <= 1.28))

# --- the calibration outlives the process ----------------------------------
# The tracked position is written back so the next run resumes where this one
# ended. If that same value were also the reference, every run would re-anchor
# to wherever the last one finished and the per-run bound would compound just
# as the per-check one used to: measured, two runs beside a phone-shaped decoy
# went 100% -> 79% -> 63%.
here = quad_at(400, 140)
tracked = here.copy()
for _ in range(3):
    tr = T.QuadTracker(tracked, calibrated=here)
    w, h = int(PHONE[0] * 0.8), int(PHONE[1] * 0.8)
    settle(tr, frame_with_phone(400 + (PHONE[0] - w) // 2, 140 + (PHONE[1] - h) // 2, (w, h)), 10)
    tracked = tr.quad.copy()
ok_('the bound holds across restarts, not just within a run',
    T.span(tracked) / T.span(here) > T.SIZE_BAND[0] - 0.01)
ok_('and the reference is the calibration, not the resume point',
    T.distance(T.QuadTracker(tracked, calibrated=here).calibrated, here) < 0.01)
eq('...defaulting to the starting quad when none is given',
   round(T.distance(T.QuadTracker(here).calibrated, here), 3), 0.0)

# --- and a stuck tracker is visible in the status --------------------------
# drift is measured against the last *save*, which mark_saved re-baselines, so
# corners far from the phone can report a contented zero. A rig did exactly
# that: "corners held, drift 0px from saved", every health line, while sitting
# 826px off.
tr = T.QuadTracker(start)
settle(tr, frame_with_phone(*MOVED), T.AGREE + 6)
tr.mark_saved(now=999.0)
eq('drift resets when the file catches up', round(tr.status()['drift']), 0)
ok_('wander does not', tr.status()['wander'] > 20)

# ...and never onto something that is not the same size of thing. A lit panel
# elsewhere in the car can be every bit as steady as the phone.
tr3 = T.QuadTracker(start)
settle(tr3, frame_with_phone(120, 120, size=(620, 700)), T.AGREE * 4)
eq('a differently sized bright thing never takes the lock', tr3.jumps, 0)
eq('...and leaves the corners alone', T.distance(tr3.quad, start), 0.0)
ok_('same_size accepts a phone seen slightly nearer',
    T.same_size(quad_at(400, 140, size=(330, 680)), start))
ok_('...and rejects something half the size',
    not T.same_size(quad_at(400, 140, size=(150, 310)), start))

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

# --- following on a small stream, reporting in capture coordinates ----------
# This is how the scanner really runs it: corners are found on the 640-wide
# preview the motion gate already has, and have to land on the sensor frame.
SCALE = (3.6375, 3.6417)          # 2328x1748 capture against a 640x480 stream


def small(x, y, size=(150, 330)):
    """The same scene as frame_with_phone, at preview scale."""
    f = np.full((480, 640, 3), 22, np.uint8)
    w, h = size
    cv2.rectangle(f, (x, y), (x + w, y + h), (238, 240, 238), -1)
    for i in range(6):
        cv2.rectangle(f, (x + 8, y + 170 + i * 24), (x + w - 8, y + 179 + i * 24), (90, 90, 90), -1)
    return f


def big_quad(x, y, size=(150, 330)):
    w, h = size
    return np.float32([[x, y], [x + w, y], [x + w, y + h], [x, y + h]]) * np.float32(SCALE)


start_small = big_quad(240, 70)
tr = T.QuadTracker(start_small, scale=SCALE)
eq('a preview-scale tracker starts where told', T.distance(tr.quad, start_small), 0.0)
settle(tr, small(240, 70), T.AGREE + 1)
ok_('and holds a still phone', T.distance(tr.quad, start_small) < 12.0)

# A 6px slide in the preview is a 22px slide on the sensor — which is the whole
# reason for tracking, and it must be reported at sensor scale.
tr = T.QuadTracker(start_small, scale=SCALE)
settle(tr, small(246, 74), 14)
moved = T.distance(tr.quad, start_small)
ok_('a small-stream nudge is scaled up', moved > 15.0)
ok_('...and lands on the phone, not past it', T.distance(tr.quad, big_quad(246, 74)) < 14.0)

# A single number must behave exactly like a matching pair.
tr_one = T.QuadTracker(big_quad(240, 70), scale=3.6375)
eq('a scalar scale is accepted', [round(v, 4) for v in tr_one.scale.tolist()], [3.6375, 3.6375])

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
