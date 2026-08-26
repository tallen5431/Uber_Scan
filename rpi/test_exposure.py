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
eq('the first look is taken', g.update(np.full((50, 50), 205, np.uint8), 100.0), {})
eq('...and a well-lit card needs nothing', g.gain, 1.5)

# The phone dims at night: gain should climb, and keep climbing while it is dark.
g = EX.AutoGain(gain=1.5, every=6.0)
g.update(np.full((50, 50), 90, np.uint8), 100.0)
first = g.gain
ok_('a dim card raises gain', first > 1.5)
eq('but not again within the interval', g.update(np.full((50, 50), 90, np.uint8), 102.0), {})
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

# ...including one dimmed past the point where darkness alone would be taken
# for an empty mount.
#
# LIT_ENOUGH is a backstop for a caller that cannot say whether the phone is
# there, and it says so in its own comment — but the branch read
# `has_screen and bright >= LIT_ENOUGH`, so a tracker locked onto a phone still
# lost the argument to the constant. A screen reading under 20 therefore took
# the empty-mount path: lengthen to the longest rung, then stop. Measured, the
# gain sat at its starting 1.5 for ever with 5.3x of headroom untouched and the
# picture stayed dark, which is the shape of "some conditions make it very
# dim". The claim that a phone at its dimmest still reads several times
# LIT_ENOUGH is contradicted by this file's own record of a night-time card
# reading 6.
VERY_DIM = 0.06                       # about 13 at the starting gain, under 20
g = EX.AutoGain(gain=1.5, every=6.0)
start = EX.brightness(lit_card(1.5, dim=VERY_DIM))
ok_('the fixture really is darker than the empty-mount backstop (%d)' % start,
    start < EX.LIT_ENOUGH)
for i in range(1, 31):
    g.update(lit_card(g.gain, dim=VERY_DIM), 100.0 + i * 6.0, has_screen=True)
ok_('a phone dimmer than the backstop is still brightened when the tracker '
    'can see it (gain %.1f)' % g.gain, g.gain > 6.0)

# The protection it must not cost: the same darkness with the phone actually
# gone. Raising gain against dark upholstery is what wound the rig to its
# ceiling chasing a card that was not there.
g = EX.AutoGain(gain=1.5, every=6.0)
for i in range(1, 31):
    g.update(lit_card(g.gain, dim=VERY_DIM), 100.0 + i * 6.0, has_screen=False)
eq('...and held at exactly the same darkness when the tracker says it is gone',
   g.gain, 1.5)

# ...and with nobody tracking, where the caller has no answer to give, the
# constant is all there is and still holds.
g = EX.AutoGain(gain=1.5, every=6.0)
for i in range(1, 31):
    g.update(lit_card(g.gain, dim=VERY_DIM), 100.0 + i * 6.0)
eq('...and held on darkness alone when nothing is tracking', g.gain, 1.5)

# --- running out of light, and saying so -----------------------------------
#
# `too_bright` has always been reported: gain on its floor, no shorter rung,
# the remedy the driver's. The other end of the same complaint was reported by
# nothing at all — everything spent, the screen still under target, a dark
# picture and no word about why.
g = EX.AutoGain(gain=1.5, every=6.0)
ok_('a fresh controller is complaining about neither end',
    not g.too_dim and not g.too_bright)
for i in range(1, 31):
    g.update(lit_card(g.gain, dim=VERY_DIM), 100.0 + i * 6.0, has_screen=True)
eq('...and it spends everything it has first', g.gain, EX.GAIN_LIMITS[1])
ok_('a phone the camera cannot make up for is reported', g.too_dim)
ok_('...and not as the opposite complaint', not g.too_bright)

# It clears when the light does, or it is a notice the driver learns to ignore.
for i in range(31, 61):
    g.update(lit_card(g.gain, dim=1.0), 100.0 + i * 6.0, has_screen=True)
ok_('the complaint clears when the phone is turned back up', not g.too_dim)
ok_('...and the gain comes back down with it', g.gain < 3.0)

# An empty mount is not a dim phone, and must not be reported as one: the
# driver would turn up a phone that is in their pocket.
g = EX.AutoGain(gain=1.5, every=6.0)
for i in range(1, 31):
    g.update(cabin(g.gain), 100.0 + i * 6.0, has_screen=False)
ok_('a phone that is not there is not a phone that is too dim', not g.too_dim)

# Nor may both ends be true at once, which would put two contradictory
# instructions on the same screen.
g = EX.AutoGain(gain=1.5, every=6.0, exposure=EX.DEFAULT_EXPOSURE)
white = np.full((60, 40), 255, np.uint8)
for i in range(1, 41):
    g.update(white, 100.0 + i * 6.0, has_screen=True)
ok_('a blown-out card is too bright', g.too_bright)
ok_('...and never also too dim', not g.too_dim)

# ...and a card that comes back blown out is still brought down.
g = EX.AutoGain(gain=8.0, every=6.0)
for i in range(1, 31):
    g.update(lit_card(g.gain), 100.0 + i * 6.0)
ok_('a blown-out card still pulls gain down', g.gain < 2.0)

# --- daylight: when the gain runs out, the exposure has to give way ---------
# Through a windscreen the card blows out with the gain already on its floor,
# and then there is nothing left but the exposure. The corners are found
# perfectly the whole time — this is not a detection failure, it is a picture
# with no detail left in it: on a rendered sunset the payout read "$7.09", then
# "7.09", then "wiaVvwyw" as the clipping climbed past 80%.
MEASURED = 16667


def at(gain, exposure, light):
    """A card lit by `light`, seen at this gain and exposure.

    A rig with no exposure to manage still takes a picture; it is simply the
    one calibration measured, which is what `None` means here.
    """
    v = 150.0 * gain * ((MEASURED if exposure is None else exposure) / 16667.0) * light
    return np.clip(np.full((60, 40), v, np.float32), 0, 255).astype(np.uint8)


def a_day(g, light, steps=80, t0=0.0):
    t = t0
    for _ in range(steps):
        t += 6.0
        g.update(at(g.gain, g.exposure, light), t)
    return t


for name, light in(('a dark car', 0.35), ('an overcast day', 2.0),
                    ('sun through the screen', 5.0), ('glare off the bonnet', 12.0)):
    g = EX.AutoGain(gain=1.5, every=6.0, exposure=MEASURED)
    a_day(g, light)
    lit = at(g.gain, g.exposure, light)
    ok_('%s is not blown out' % name, EX.clipped_fraction(lit) <= EX.CLIPPED_FRACTION)
    ok_('%s is bright enough to read' % name, EX.brightness(lit) > 120)
    ok_('%s never exposes longer than calibration measured' % name,
        g.exposure <= MEASURED)

# The exposure is borrowed, not taken: a rig that drives out of daylight has to
# give it back, or it spends the night on a picture eight times too dark and
# cannot tell that from an empty mount — which is exactly what happened when the
# repayment sat below the darkness guard.
g = EX.AutoGain(gain=1.5, every=6.0, exposure=MEASURED)
t = a_day(g, 12.0)
ok_('daylight borrows exposure', g.exposure < MEASURED)
t = a_day(g, 0.35, steps=120, t0=t)
eq('...and nightfall gives all of it back', g.exposure, MEASURED)
ok_('...leaving a readable card', EX.brightness(at(g.gain, g.exposure, 0.35)) > 150)

# Exposure is spent before gain, because exposure up to the measured value is
# free — every rung was measured quiet — and gain is noise.
#
# Asserted as a property of where it comes to rest rather than as the order of
# the first two moves. The order was the right test of a design with a rule for
# gain and a separate rule for exposure; there is one rule now, and it picks the
# longest rung that can carry the light every single beat. So the thing to check
# is that the rig cannot be found sitting on a short exposure with gain to spare
# — which is the actual complaint, and which the ordering test could not see.
g = EX.AutoGain(gain=1.5, every=6.0, exposure=MEASURED)
t = a_day(g, 12.0)
short, noisy = g.exposure, g.gain
a_day(g, 2.0, steps=40, t0=t)
ok_('coming out of glare lengthens the exposure', g.exposure > short)
ok_('...on a card that reads', 120 < EX.brightness(at(g.gain, g.exposure, 2.0)) < 250)
ok_('...without paying for it in noise', g.gain < EX.GAIN_LIMITS[1] / 2)

# Deliberately not "and the gain came down". Less light on the card needs more
# light out of the camera, so the gain can legitimately end up higher than it
# was in the glare — what must not happen is the rig sitting on a short
# exposure with gain it could have spent on a longer one. That is the property,
# and it is checkable directly.
longer = [c for c in g.candidates if c > g.exposure]
ok_('...and it rests on the longest exposure it can afford',
    not longer or g.gain * g.exposure / longer[0] < EX.GAIN_LIMITS[0])

# The lengthening looks before it steps. Doubling a card that is merely a little
# dark blows it out, which shortens it straight back, which is a limit cycle —
# and it ran at six-second intervals through a windscreen.
g = EX.AutoGain(gain=1.5, every=6.0, exposure=MEASURED)
t = a_day(g, 5.0)
seen = set()
for _ in range(30):
    t += 6.0
    g.update(at(g.gain, g.exposure, 5.0), t)
    seen.add(g.exposure)
eq('a settled exposure stays settled', len(seen), 1)

# None of it may let an empty mount wind the gain up, which is what the darkness
# guard is for.
g = EX.AutoGain(gain=1.5, every=6.0, exposure=MEASURED)
t = 0.0
for _ in range(60):
    t += 6.0
    g.update(np.clip(np.full((60, 40), 6.0 * g.gain, np.float32), 0, 255).astype(np.uint8),
             t, has_screen=False)
eq('an empty mount still holds the gain', g.gain, 1.5)
eq('...and the exposure', g.exposure, MEASURED)

# And a rig with no exposure to manage behaves exactly as it did before.
g = EX.AutoGain(gain=1.0, every=6.0)
a_day(g, 5.0, steps=20)
eq('without an exposure to manage, nothing is invented', g.exposure, None)
eq('...and the gain still backs off a blown card', g.gain, EX.GAIN_LIMITS[0])


# --- the driver turns their phone's brightness up ---------------------------
# The complaint this was built from, in one line: "it looks too bright if I turn
# the brightness up on my phone". It was a fair complaint. `brightness` is a
# percentile, every percentile of a card at full well is 255, and so the loop
# could not tell a nudge from an eightfold and answered both with the same 18%
# step on a six-second beat. Measured against the real loop driving a rendered
# card, the card stayed blown out for 36 seconds after a doubling and 48 after
# an eightfold — against an offer that lives 30 to 45.
def chasing(light, gain0=1.5, ladder=None, limit=200):
    """Seconds until the card is off the rail, and until it is back on target."""
    g = EX.AutoGain(gain=gain0, every=6.0, exposure=MEASURED,
                    **({'candidates': ladder} if ladder else {}))
    t, off_rail = 0.0, None
    for _ in range(limit):
        frame = at(g.gain, g.exposure, light)
        blown = EX.clipped_fraction(frame) > EX.CLIPPED_FRACTION
        if not blown and off_rail is None:
            off_rail = t
        if (off_rail is not None and not blown
                and abs(EX.brightness(frame) - EX.TARGET_BRIGHT)
                / EX.TARGET_BRIGHT <= 0.2):
            return off_rail, t, g
        t += EX.BLOWN_EVERY if blown else 6.0
        g.update(frame, t)
    return off_rail, None, g


# Two numbers, because they are two different promises. Coming off the rail is
# when the card stops being a white rectangle and starts being readable at all;
# reaching target is when the picture is properly exposed again. The first is
# the one that costs offers.
for light in (1.25, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0):
    rail, settled, g = chasing(light)
    ok_('a phone turned up %.2fx is off the rail inside 8s' % light,
        rail is not None and rail <= 8.0)
    ok_('...and properly exposed again inside 15s at %.2fx' % light,
        settled is not None and settled <= 15.0)

# It must not be answered by over-correcting into the dark, which is what a flat
# halving does to a small nudge: the card comes off the rail immediately and
# then sits at 62% of target while it climbs back.
rail, settled, g = chasing(1.25)
ok_('a small nudge is answered with a small cut',
    EX.brightness(at(g.gain, g.exposure, 1.25)) > EX.TARGET_BRIGHT * 0.75)
eq('...without touching the exposure at all', g.exposure, MEASURED)


# --- and only onto rungs this screen measured quiet -------------------------
# Falling back down a hardcoded ladder means stepping onto exposures nobody
# measured. On the commonest panel family the first rung below the calibrated
# 16667us is 8333us — half a 60Hz cycle, which choose_exposure's own comment
# calls the only entry in FLICKER_SAFE that bands. Simulated against a 60Hz
# panel it scores 128.8 where 4.0 already means rippling.
#
# On such a phone the honest ladder has nothing below the calibrated value, and
# the honest answer to a phone turned up past what gain can take is to say so
# rather than to make the screen ripple.
SIXTY_HZ = (16667,)                 # what quiet_ladder returns for a 60Hz panel

g = EX.AutoGain(gain=1.5, every=6.0, exposure=MEASURED, candidates=SIXTY_HZ)
t = 0.0
for _ in range(60):
    t += 6.0
    g.update(at(g.gain, g.exposure, 6.0), t)
eq('a measured ladder with nothing shorter holds the exposure', g.exposure, MEASURED)
ok_('...at the gain floor', g.gain < EX.GAIN_LIMITS[0] * 1.02)
ok_('...and says the phone is too bright rather than making it ripple', g.too_bright)

# ...and it stops saying so the moment the phone comes back down.
for _ in range(20):
    t += 6.0
    g.update(at(g.gain, g.exposure, 1.0), t)
ok_('the complaint clears when the light does', not g.too_bright)
ok_('...on a card back at target',
    abs(EX.brightness(at(g.gain, g.exposure, 1.0)) - EX.TARGET_BRIGHT)
    / EX.TARGET_BRIGHT < 0.2)

# A ladder that WAS measured quiet below the calibrated value may be walked.
g = EX.AutoGain(gain=1.5, every=6.0, exposure=MEASURED,
                candidates=(4167, 8333, 16667))     # a 240Hz panel
t = 0.0
for _ in range(60):
    t += 6.0
    g.update(at(g.gain, g.exposure, 6.0), t)
ok_('a measured ladder with room below it is used', g.exposure < MEASURED)
ok_('...and only rungs that were on it', g.exposure in (4167, 8333, 16667))
ok_('...leaving a card that reads',
    EX.clipped_fraction(at(g.gain, g.exposure, 6.0)) <= EX.CLIPPED_FRACTION)
ok_('...with nothing to complain about', not g.too_bright)

# An unmeasured ladder keeps its old emergency, and only its old emergency: it
# may shorten to escape a blown-out card, but never to tidy up a split.
g = EX.AutoGain(gain=3.0, every=6.0, exposure=MEASURED)
ok_('an unmeasured ladder is marked as such', not g.ladder_measured)
t = 0.0
for _ in range(30):
    t += 6.0
    g.update(at(g.gain, g.exposure, 0.5), t)       # dim: never blown
eq('...so a dim card never shortens the exposure on a guess', g.exposure, MEASURED)


# --- the ladder comes off the measurement calibration already took ----------
REPORT = [{'exposure': 1042, 'banding': 170.0, 'bright': 20},
          {'exposure': 2083, 'banding': 169.9, 'bright': 40},
          {'exposure': 4167, 'banding': 164.7, 'bright': 80},
          {'exposure': 8333, 'banding': 128.8, 'bright': 150},
          {'exposure': 16667, 'banding': 2.2, 'bright': 205},
          {'exposure': 25000, 'banding': 53.0, 'bright': 250},
          {'exposure': 33333, 'banding': 2.5, 'bright': 255}]
eq('a 60Hz panel keeps only whole 60Hz cycles',
   EX.quiet_ladder(REPORT), (16667, 33333))
eq('...and nothing longer than the exposure that was chosen',
   EX.quiet_ladder(REPORT, ceiling=16667), (16667,))
eq('an empty report is an empty ladder', EX.quiet_ladder([]), ())

QUIET = [{'exposure': 4167, 'banding': 1.5, 'bright': 90},
         {'exposure': 8333, 'banding': 0.7, 'bright': 150},
         {'exposure': 16667, 'banding': 0.5, 'bright': 205}]
eq('a 480Hz panel keeps the short rungs too',
   EX.quiet_ladder(QUIET, ceiling=16667), (4167, 8333, 16667))

# The rungs a bright phone actually pushes the rig onto are the short ones, and
# they used to be the only exposures it ever used that nobody had measured.
ok_('the daylight rungs are candidates worth measuring',
    set(EX.DAYLIGHT_SAFE) & set(EX.quiet_ladder(QUIET, ceiling=16667)))

# ...but a rig calibrated in daylight must not start the night on a 2ms
# exposure, so a short rung may be measured without ever being elected.
picked, _ = EX.choose_exposure(
    lambda us: [np.full((40, 40), min(255, us / 80.0), np.uint8)] * 3,
    candidates=EX.DAYLIGHT_SAFE + EX.FLICKER_SAFE)
ok_('a daylight rung is never elected as the calibrated exposure',
    picked in EX.FLICKER_SAFE)

# Two exposures nobody could deliver used to sit in the list. picamera2 defaults
# a video configuration's frame duration to 33333us and an exposure cannot
# outlast its frame, so 40000 and 50000 were requested, silently clamped, and
# whichever won was written to config.json as "measured against this screen"
# naming a number the sensor never used.
ok_('every candidate fits inside a 30fps frame', max(EX.FLICKER_SAFE) <= 33333)
ok_('...including the default', EX.DEFAULT_EXPOSURE <= 33333)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d exposure checks passed' % ok)
sys.exit(1 if bad else 0)
