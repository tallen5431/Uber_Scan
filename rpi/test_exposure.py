"""Tests for choosing an exposure against a flickering screen.

    python3 rpi/test_exposure.py

The camera is simulated: a rolling shutter integrating a square-wave-dimmed
panel is a few lines of arithmetic, and simulating it is the only way any of
this gets tested without a phone and a dark room.
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import exposure as EX

ok = bad = 0

ROWS, COLS = 400, 300
READOUT_US = 30000.0        # time for the shutter to sweep the whole frame


def eq(name, got, want, tol=1e-6):
    global ok, bad
    good = got == want or (isinstance(want, (int, float)) and isinstance(got, (int, float))
                           and abs(got - want) <= tol)
    if good:
        ok += 1
    else:
        bad += 1
        print('FAIL  %s: got %r want %r' % (name, got, want))


def ok_(name, cond):
    eq(name, bool(cond), True)


def card(rows=ROWS, cols=COLS):
    """Static content: a white card with darker lines of text on it."""
    img = np.full((rows, cols), 120.0)
    img[rows // 3:] = 235.0
    for i in range(6):
        img[rows // 3 + 20 + i * 30: rows // 3 + 30 + i * 30] = 60.0
    return img


CARD = card()


def capture(exposure_us, flicker_hz, phase=0.0, duty=0.6, gain=1.0, seed=0):
    """One frame of a PWM-dimmed panel, read out one row at a time.

    Each row integrates the panel over its own exposure window, which starts a
    little later than the row above. When the window is a whole number of
    flicker cycles every row collects the same light and the frame is even; when
    it is not, the leftovers land in different places down the frame.
    """
    period = 1e6 / flicker_hz
    starts = phase + np.arange(ROWS) * (READOUT_US / ROWS)
    duty_us = period * duty
    # Light collected in [t, t + exposure) from a square wave that is on for
    # duty_us of every period, worked out in whole cycles plus a remainder.
    whole = np.floor(exposure_us / period)
    rem = exposure_us - whole * period
    into = np.mod(starts, period)
    part = np.clip(np.minimum(into + rem, duty_us) - np.minimum(into, duty_us), 0, None)
    part += np.clip(np.minimum(rem - (period - into), duty_us), 0, None)
    collected = whole * duty_us + part
    level = collected / (exposure_us * duty)      # 1.0 when evenly exposed
    rng = np.random.RandomState(seed)
    frame = CARD * level[:, None] * gain + rng.normal(0, 1.2, (ROWS, COLS))
    return np.clip(frame, 0, 255).astype(np.uint8)


def frames_at(exposure_us, flicker_hz, n=3, gain=1.0):
    """Consecutive frames, each catching the flicker at a different phase."""
    return [capture(exposure_us, flicker_hz, phase=i * 7777.0, gain=gain, seed=i)
            for i in range(n)]


# --- the simulation has to actually band, or nothing below means anything ---
# 12000us was the old default. It is 0.72 of a 60Hz cycle and 2.88 of a 240Hz
# one, so it bands against both; 16667us is exactly 1, 2 and 4 cycles of 60,
# 120 and 240 and is quiet against all of them. That is the whole fix.
banded = frames_at(12000, 60)
even = frames_at(16667, 60)
ok_('a mismatched exposure bands', EX.banding_score(banded) > 20.0)
ok_('a matched one does not', EX.banding_score(even) < 1.0)
ok_('and the difference is stark', EX.banding_score(banded) > 10 * EX.banding_score(even))

# The shipped default has to be quiet across the whole common family, since it
# is used before anything has been measured.
for hz in (60, 120, 240, 480):
    ok_('the default is quiet at %dHz' % hz,
        EX.banding_score(frames_at(EX.DEFAULT_EXPOSURE, hz)) < 1.0)
ok_('...where the old default was not',
    EX.banding_score(frames_at(12000, 60)) > 20.0)

# Static content must not register as banding, however busy it is.
still = [CARD.astype(np.uint8)] * 3
eq('identical frames score zero', round(EX.banding_score(still), 6), 0.0)
ok_('noise alone barely registers',
    EX.banding_score([np.clip(CARD + np.random.RandomState(i).normal(0, 1.2, CARD.shape),
                              0, 255).astype(np.uint8) for i in range(3)]) < 0.5)
eq('one frame cannot be compared', EX.banding_score([CARD]), 0.0)
eq('no frames either', EX.banding_score([]), 0.0)

# --- choosing: it must land on a whole number of cycles ---------------------
for hz in (60, 120, 240, 480):
    chosen, report = EX.choose_exposure(lambda us, h=hz: frames_at(us, h))
    cycles = chosen / (1e6 / hz)
    ok_('%dHz picks a whole number of cycles (%.2f at %dus)' % (hz, cycles, chosen),
        abs(cycles - round(cycles)) < 0.02)
    ok_('%dHz result is quiet' % hz, EX.banding_score(frames_at(chosen, hz)) < 1.5)

# It reports what it saw, so the choice can be argued with later.
chosen, report = EX.choose_exposure(lambda us: frames_at(us, 240))
eq('every candidate is reported', len(report), len(EX.FLICKER_SAFE))
ok_('with the numbers behind it', all('banding' in r and 'bright' in r for r in report))

# A blown-out setting is not chosen however quiet it is.
def blinding(us):
    return frames_at(us, 240, gain=8.0)


chosen, report = EX.choose_exposure(blinding)
ok_('an over-exposed candidate is rejected', chosen <= EX.FLICKER_SAFE[1])

# ...but when EVERY candidate is over-exposed, clipping must not get to decide.
# The checks above all run at gain 1.0, where nothing clips and the clipping
# path is never taken. The sweep on a real rig runs at whatever gain the
# preview's auto-exposure froze while metering a mostly-dark car around a
# bright screen, so blowing the card out is the ordinary case, not the edge
# one — and there the least-clipped candidate was taken as the winner.
#
# Ranking by clipping there actively selects for banding: once every candidate
# is over the line, the one that ripples has dark rows and dark rows do not
# clip. On a 60Hz panel that hands the prize to 8333us, the one entry in
# FLICKER_SAFE that is half a 60Hz cycle instead of a whole one, and the only
# one that bands — measured, written to config.json, and used for every read
# thereafter.
for hz in (60, 120, 240):
    for gain in (3.0, 6.0):
        chosen, report = EX.choose_exposure(
            lambda us, h=hz, g=gain: frames_at(us, h, gain=g))
        cycles = chosen / (1e6 / hz)
        ok_('%dHz at gain %.0f still picks a whole number of cycles (%.2f at %dus)'
            % (hz, gain, cycles, chosen), abs(cycles - round(cycles)) < 0.02)
        ok_('%dHz at gain %.0f is still quiet' % (hz, gain),
            EX.banding_score(frames_at(chosen, hz)) < 1.5)
        ok_('%dHz at gain %.0f still reports every candidate' % (hz, gain),
            len(report) == len(EX.FLICKER_SAFE))

# Nothing to look at: fall back rather than crash.
eq('no frames at all falls back', EX.choose_exposure(lambda us: [])[0], EX.DEFAULT_EXPOSURE)

# --- brightness and clipping -----------------------------------------------
dim = np.full((100, 100), 40, np.uint8)
bright = np.full((100, 100), 230, np.uint8)
ok_('a dim picture reads dim', EX.brightness(dim) < 60)
ok_('a bright one reads bright', EX.brightness(bright) > 200)
eq('nothing clipped', EX.clipped_fraction(bright), 0.0)
eq('all clipped', EX.clipped_fraction(np.full((10, 10), 255, np.uint8)), 1.0)

# --- gain tracks the phone dimming itself ----------------------------------
g = EX.AutoGain(gain=1.5, every=6.0)
eq('the first look is taken', g.update(np.full((50, 50), 205, np.uint8), 100.0), None)
eq('...and a well-lit card needs nothing', g.gain, 1.5)

# The phone dims at night: gain should climb, and keep climbing while it is dark.
g = EX.AutoGain(gain=1.5, every=6.0)
g.update(np.full((50, 50), 90, np.uint8), 100.0)
first = g.gain
ok_('a dim card raises gain', first > 1.5)
eq('but not again within the interval', g.update(np.full((50, 50), 90, np.uint8), 102.0), None)
for i in range(1, 12):
    g.update(np.full((50, 50), 90, np.uint8), 100.0 + i * 7.0)
ok_('it keeps climbing while dark', g.gain > first)
ok_('...but never past the ceiling', g.gain <= EX.GAIN_LIMITS[1])

# A blown-out card pulls gain back even if the average looks fine.
g = EX.AutoGain(gain=4.0, every=6.0)
g.update(np.full((50, 50), 254, np.uint8), 100.0)
ok_('clipping pulls gain down', g.gain < 4.0)

# And it settles rather than oscillating around the target.
g = EX.AutoGain(gain=1.0, every=1.0)
level = 60.0
for i in range(40):
    frame = np.full((50, 50), int(min(255, level * g.gain)), np.uint8)
    g.update(frame, float(i))
settled = g.gain
for i in range(40, 60):
    frame = np.full((50, 50), int(min(255, level * g.gain)), np.uint8)
    g.update(frame, float(i))
ok_('gain settles', abs(g.gain - settled) / settled < 0.25)
ok_('...near enough the target',
    abs(min(255, level * g.gain) - EX.TARGET_BRIGHT) / EX.TARGET_BRIGHT < 0.2)
ok_('never below the floor', g.gain >= EX.GAIN_LIMITS[0])

# --- an empty mount is not a dim card ---------------------------------------
# The window handed to AutoGain is wherever the screen was last seen, so with
# the phone out of the mount it is dark upholstery. Read as a very dim card, it
# wound the gain to its 8.0 ceiling in about 78 seconds — and the phone then
# came back to a card blown out at 8x, needing a further minute of six-second
# steps to climb down. That minute lands exactly when the driver has picked the
# phone up to look at an offer.
def cabin(gain):
    """What the screen's corner of the frame holds once the phone is gone."""
    return np.clip(np.full((60, 40), 6.0 * gain, np.float32), 0, 255).astype(np.uint8)


def lit_card(gain, dim=1.0):
    return np.clip(np.full((60, 40), 150.0 * gain * dim, np.float32), 0, 255).astype(np.uint8)


g = EX.AutoGain(gain=1.5, every=6.0)
for i in range(1, 31):
    g.update(cabin(g.gain), 100.0 + i * 6.0, has_screen=False)
eq('gain is held while the phone is away', g.gain, 1.5)

# The same, with nothing tracking the screen to say so — --no-track leaves the
# caller no answer to give, so the darkness has to speak for itself.
g = EX.AutoGain(gain=1.5, every=6.0)
for i in range(1, 31):
    g.update(cabin(g.gain), 100.0 + i * 6.0)
eq('...and held on darkness alone when nothing is tracking', g.gain, 1.5)

# None of which may cost it its actual job: a phone that really has dimmed.
g = EX.AutoGain(gain=1.5, every=6.0)
for i in range(1, 31):
    g.update(lit_card(g.gain, dim=0.35), 100.0 + i * 6.0)
ok_('a genuinely dimmed phone is still brightened', g.gain > 3.0)
ok_('...to about the right level',
    abs(EX.brightness(lit_card(g.gain, dim=0.35)) - EX.TARGET_BRIGHT)
    / EX.TARGET_BRIGHT < 0.2)

# ...and a card that comes back blown out is still brought down.
g = EX.AutoGain(gain=8.0, every=6.0)
for i in range(1, 31):
    g.update(lit_card(g.gain), 100.0 + i * 6.0)
ok_('a blown-out card still pulls gain down', g.gain < 2.0)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d exposure checks passed' % ok)
sys.exit(1 if bad else 0)
