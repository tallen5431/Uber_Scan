"""Choosing an exposure for a screen that is flickering at you.

A phone display is not a lit object, it is a strobe. Backlights and OLED panels
dim by switching on and off — commonly somewhere in the 60/120/240/480 Hz family
— and a rolling shutter reads the sensor one row at a time, so different rows of
one frame catch different parts of that cycle. The result is horizontal bands
that drift up or down the picture from frame to frame. On a phone screen it
looks like the display is rippling, and to the reader it is a band of the card
that is darker than the rest for this frame and lighter for the next.

The cure is not a filter. It is arithmetic: if the exposure lasts a whole number
of flicker cycles, every row integrates the same amount of light and the banding
cancels exactly. 16.667ms is one cycle of 60Hz, two of 120, four of 240 and
eight of 480, which is why it is the first thing to try — and it happens to be
39% brighter than the 12ms this used to run at, which is the other complaint.

What this module does not do is guess. It measures: grab a few frames at each
candidate exposure, and see which one actually stops rippling on the phone in
front of it.
"""

import numpy as np

# Exposures that are a whole number of cycles of a common dimming frequency,
# shortest first. Every one of these divides evenly into the 60Hz family; the
# 20ms and 25ms entries also cover 50Hz and 100Hz panels.
#
# "Safe for a common frequency" is not "safe for the phone in front of you",
# and the difference is not small. Simulating a rolling shutter over a PWM
# backlight and scoring the result with banding_score() below, where 4.0
# already means rippling:
#
#              60Hz   120Hz   240Hz   480Hz
#     8333us  128.8     2.0     2.6     0.7
#    16667us    2.2     1.3     1.4     0.5
#    20000us   40.5    32.0     9.7     7.8
#    25000us   53.0     2.8     1.3     0.7
#    33333us    2.5     0.7     0.7     0.1
#
# So this is a list of exposures worth *trying*, and which of them are quiet is
# a property of the panel that only measurement settles. choose_exposure()
# measures them; the ladder AutoGain falls back down should be the measured
# answer and not this tuple. See config.json's `exposureLadder`.
#
# 40000 and 50000 used to be here and are not, because they were never
# deliverable: picamera2's create_video_configuration defaults the frame
# duration to 33333us and an exposure cannot outlast its frame. Both were
# requested during calibration, both were silently clamped to 33333, and
# whichever won was written down as "measured against this screen" naming a
# number the sensor never used. 33333us is already two whole 60Hz cycles, and
# longer exposures buy motion smear on a card being read from a moving car.
FLICKER_SAFE = (8333, 16667, 20000, 25000, 33333)

# The default when nothing has been measured. One 60Hz cycle: safe for the
# commonest family and bright enough for a dimmed screen at night.
DEFAULT_EXPOSURE = 16667

# Shorter whole-cycle exposures, for daylight only. 4167us is one cycle of
# 240Hz, 2083 of 480, 1042 of 960 — all of them still cancel the panel families
# they name, and all of them are far too dark for a car at night, which is why
# they are not in the list calibration chooses from. They are reachable only by
# AutoGain, and only when the card is blown out with the gain already on its
# floor: at that point the choice is not between a clean read and a rippling one,
# it is between a rippling read and no read at all. Through a windscreen at noon
# even 8333us leaves the card 100% blown.
DAYLIGHT_SAFE = (1042, 2083, 4167)

# What a well-exposed card looks like. Measured on the bright part of the
# picture — the card is white, so its own brightness is the thing to aim.
TARGET_BRIGHT = 205.0
BRIGHT_PERCENTILE = 90
CLIPPED_AT = 250.0
CLIPPED_FRACTION = 0.08     # above this much blown-out white, back off

# Gain moves in steps this size, and stays inside these limits. Small steps
# because this runs between offers and has no deadline; limits because gain is
# noise, and past about 8x an IMX519 frame is mush.
#
# The step is for going *up*, which is the direction that can rail and that
# costs noise. Coming down is sized from the picture instead — see update().
GAIN_STEP = 1.18
GAIN_LIMITS = (1.0, 8.0)
GAIN_TOLERANCE = 0.10       # within 10% of target is close enough to leave alone

# How hard to cut when the picture is at full well, and how often to look while
# it is. Both are about the one situation where the usual error signal is gone:
# past the clipping point `brightness` pins at 255 and stays there whether the
# card is a fifth too bright or eight times, so there is no factor to measure
# and nothing to be proportional to. Halving needs no factor — it is a
# bisection — and three of them cover eightfold.
#
# Measured on the rig's own test cards, driving the real loop: answering a
# doubling of the phone's brightness took 36 seconds the old way and answering
# an eightfold took 48, against an offer that lives 30 to 45 seconds. The
# driver's complaint was that the picture looks too bright; that is what it was.
# The cut starts as the ordinary step and grows for as long as the picture keeps
# coming back at full well: 1.18, 1.27, 1.40, 1.58, 1.85, 2.26 — a factor of
# fifteen inside six beats, and a factor of fifteen is more than any phone's
# brightness slider can do.
#
# Escalating rather than a flat halving, because both ends matter and they pull
# opposite ways. A flat halving answers an eightfold quickly and over-corrects a
# nudge: a phone turned up a quarter gets cut in half, leaving a card at 62% of
# target that then has to climb back — measured, 19 seconds to undo a 25%
# change. Growing from a small step costs one beat for the nudge and six for the
# eightfold, and 1.4 was picked by sweeping the exponent against the whole range
# of excursions rather than by taste:
#
#             1.25x  1.5x   2x    3x    4x    6x    8x
#   blown       1s    2s    3s    4s    5s    5s    6s
#   on target   1s    2s    3s    4s   11s    5s   12s
#
# against 36 to 48 seconds blown, at every one of those, before.
BLOWN_STEP = GAIN_STEP
BLOWN_ESCALATE = 1.4
BLOWN_MAX_STEP = 8.0
BLOWN_EVERY = 1.0

# How much better than break-even a longer exposure has to be before it is worth
# moving onto. See _split: without it, the light level at which a longer rung
# becomes affordable is the same level at which it stops being affordable, so a
# steady scene sitting on that line flaps the exposure back and forth for ever
# at identical brightness. A little more than one gain step is enough to make
# the two crossings different events.
LENGTHEN_MARGIN = 1.15

# The most light one beat may ask for. Going up is the direction that can rail,
# and what rails it is a brightness read off something that is not the card —
# so the cap is on the step, not on the arithmetic. Twice a beat still crosses
# the whole gain range in three, and no single misread window can do more than
# the next beat undoes.
UP_MAX = 2.0

# Below this, the window holds no lit screen — it is the dark inside of a car.
# A phone at its dimmest still reads several times this; an unlit mount reads
# well under it. Used only as a backstop for when nothing is tracking the
# screen, since a caller that knows the phone is missing says so outright.
LIT_ENOUGH = 20.0


def row_profile(gray):
    """Mean brightness of each row."""
    return np.asarray(gray, dtype=np.float32).mean(axis=1)


def banding_score(frames):
    """How much horizontal banding moves between frames. Lower is better.

    Comparing frames rather than looking at one is what makes this work. The
    card's own content — lines of text, the white panel, the map above it — is
    static and identical in every frame, so it subtracts out. A flicker beat is
    not static: the bands sit in a different place each time, and what survives
    the subtraction is almost entirely them.

    Sensor noise survives too, but a row mean averages it over a thousand pixels
    and it lands near zero, while banding is tens of levels.
    """
    frames = [f for f in frames if f is not None]
    if len(frames) < 2:
        return 0.0
    profiles = [row_profile(f) for f in frames]
    n = min(len(p) for p in profiles)
    diffs = [np.abs(profiles[i + 1][:n] - profiles[i][:n]) for i in range(len(profiles) - 1)]
    return float(np.mean(diffs))


def brightness(gray, percentile=BRIGHT_PERCENTILE):
    """How bright the bright part is — the card, rather than the dark surround.

    The percentile is a stand-in for knowing where the card is. Hand this the
    screen when the caller does know (see AutoGain), because the stand-in gets
    worse the more dark room there is around the phone.
    """
    return float(np.percentile(np.asarray(gray, dtype=np.float32), percentile))


def clipped_fraction(gray):
    """Share of the picture blown out. Detail lost here cannot be recovered.

    Unlike brightness this has no percentile to hide behind: it is a share of
    whatever it is given, so giving it the whole frame divides the answer by
    however much of that frame is dark car. A rig ran with its card at 237 and
    a fifth of it blown out — which should have backed the gain straight off —
    and the guard never fired, because over the whole frame that came to 9%
    against a threshold of 8%. Give it the screen.
    """
    a = np.asarray(gray)
    return float(np.count_nonzero(a >= CLIPPED_AT)) / max(a.size, 1)


def score(frames):
    """Everything worth knowing about one exposure setting."""
    return {'banding': banding_score(frames),
            'bright': brightness(frames[0]) if frames else 0.0,
            'clipped': clipped_fraction(frames[0]) if frames else 0.0}


def choose_exposure(grab, candidates=FLICKER_SAFE, target=TARGET_BRIGHT):
    """Pick the exposure that ripples least while still lighting the card.

    `grab(exposure_us)` must set the exposure and return a list of consecutive
    greyscale frames of the screen. Kept as a callback so this is testable
    without a camera, which is the only way it gets tested at all.

    Returns (exposure, report) where report lists what every candidate scored,
    because a number chosen silently is a number nobody can argue with later.
    """
    report = []
    for exposure in candidates:
        frames = grab(exposure)
        if not frames:
            continue
        row = dict(score(frames), exposure=exposure)
        report.append(row)

    usable = [r for r in report if r['clipped'] <= CLIPPED_FRACTION]
    if not usable:
        # Everything is blown out — at whatever gain the preview's auto-exposure
        # happened to freeze while metering a mostly-dark car interior around a
        # bright screen. That is a gain problem and it does not survive
        # calibration: AutoGain re-sets gain to TARGET_BRIGHT the moment
        # scanning starts. Letting it decide the exposure meant a condition
        # that was about to go away vetoing one that is permanent, against the
        # rule this whole module is built on — gain cannot reintroduce banding,
        # and exposure can.
        #
        # Ranking by least-clipped was worse than merely irrelevant: it selects
        # *for* banding. Once every candidate's white has crossed the clipping
        # point, the one that ripples is the one with dark rows, and dark rows
        # do not clip — so on a 60Hz panel the winner was 8333us, the single
        # entry in FLICKER_SAFE that is half a 60Hz cycle rather than a whole
        # one, and the only one that bands. It was then written to config.json
        # and announced as "measured against this screen".
        #
        # So keep every candidate and let banding decide, which is what the
        # rest of this function already does correctly.
        usable = report
    if not usable:
        return DEFAULT_EXPOSURE, report

    # Banding is the thing being solved, so it decides. Among settings that are
    # equally quiet, prefer the one closest to a well-lit card — quantised,
    # because a difference of a level or two in banding is not a difference.
    quietest = min(r['banding'] for r in usable)
    tied = [r for r in usable if r['banding'] <= quietest + 1.0]
    # Only ever elect a candidate long enough for a dark car. The daylight
    # rungs are measured — that is the whole point of measuring them — but a
    # rig calibrated at noon must not start the night on a 2ms exposure.
    settled = [r for r in tied if r['exposure'] in FLICKER_SAFE] or tied
    best = min(settled, key=lambda r: abs(r['bright'] - target))
    return best['exposure'], report


# How much worse than the quietest candidate a rung may measure and still count
# as quiet. The same margin choose_exposure uses for its tie set, for the same
# reason: a difference of a level or two in banding is not a difference.
QUIET_MARGIN = 1.0


def quiet_ladder(report, ceiling=None):
    """The exposures this phone measured quiet, shortest first.

    This is the answer to a question the rig used to ask a constant. Falling
    back down a hardcoded ladder means stepping onto rungs nobody measured, and
    on the commonest panel family the first rung below the calibrated 16667us
    is 8333us — half a 60Hz cycle, which choose_exposure's own comment above
    calls the only entry in FLICKER_SAFE that bands. Simulated against a 60Hz
    panel it scores 128.8 where 4.0 already means rippling, and the ripple is
    not merely a worse picture: the motion gate reads 75 against a settle
    threshold of 2, so the picture never settles, so nothing reads.

    Four seconds of calibration already measured every rung on the driver's own
    phone. Keeping the answer costs one list in config.json.

    `ceiling` drops anything longer than the exposure that was actually chosen,
    since exposing longer than calibration measured is never wanted.
    """
    scored = [r for r in report if r.get('banding') is not None]
    if not scored:
        return ()
    quietest = min(r['banding'] for r in scored)
    return tuple(sorted(
        r['exposure'] for r in scored
        if r['banding'] <= quietest + QUIET_MARGIN
        and (ceiling is None or r['exposure'] <= ceiling)))


class AutoGain:
    """Keep the card at a sensible brightness by moving gain, never exposure.

    Phones dim themselves. A screen set up in daylight is a different subject at
    two in the morning, and a fixed exposure that suited one leaves the other
    dark — which was the complaint that started this. Full auto-exposure is not
    the answer: it hunts on a strobing emissive panel, and it would undo the
    flicker-safe exposure the moment it decided the picture was dim.

    So the exposure stays exactly where it was measured, and gain does the
    adapting. Gain costs noise rather than banding, and it moves in small steps
    with a long interval, so it tracks a phone's auto-brightness over minutes
    without ever moving during an offer.

    ONE RULE, and every branch below is an instance of it:

        Turning the picture DOWN is always allowed, and is answered at once and
        at whatever size the evidence supports. It cannot rail, it cannot
        reintroduce banding, and a blown-out card is a fault whether or not
        anything is tracking the screen.

        Turning it UP needs a screen to aim at, costs noise, and waits for the
        slow beat.

    That rule used to be four separate ordering interlocks, each written down as
    the anecdote that produced it — clipping above the hold, repayment above the
    darkness guard, and so on. The anecdotes are all real and are all still
    checked in test_exposure.py; they are consequences here rather than
    structure, because four interlocks are four things to get wrong and one rule
    is one thing to read.
    """

    def __init__(self, gain=1.5, target=TARGET_BRIGHT, every=6.0,
                 step=GAIN_STEP, limits=GAIN_LIMITS, exposure=None,
                 candidates=None):
        self.gain = float(gain)
        self.target = target
        self.every = every
        self.step = step
        self.limits = limits
        # The exposure measured at calibration, and the ceiling this may never
        # go above: that value was chosen because it stops the screen rippling,
        # and there is never a reason to spend longer than it.
        self.measured = exposure
        self.exposure = exposure
        # The rungs this may move between. Pass the ones calibration measured
        # quiet on this driver's own phone — see quiet_ladder — and the ladder
        # can be walked freely, because trading exposure for gain then cannot
        # make the screen ripple. Pass nothing and it falls back to a guess
        # about panels in general, which is only ever used in the one emergency
        # it was always used for. See _rungs.
        self.ladder_measured = bool(candidates)
        rungs = set(candidates or (DAYLIGHT_SAFE + FLICKER_SAFE))
        if exposure is not None:
            rungs.add(exposure)
            rungs = {c for c in rungs if c <= exposure}
        self.candidates = tuple(sorted(rungs))
        self.last = None
        # How hard to cut the next time the picture comes back at full well.
        # Grows while it keeps coming back, resets the moment it does not.
        self.cut = BLOWN_STEP
        # The picture is over-exposed and there is nothing left to give: gain is
        # on its floor and there is no shorter rung to fall to. The only
        # remaining remedy belongs to the driver, so it has to reach them — see
        # the health line in scan_pi and the notice on the live page.
        self.stuck = False

    def update(self, gray, now, has_screen=True):
        """The camera controls to apply, or {} to leave the camera alone.

        There is only one quantity worth controlling here, and it is not the
        gain: how bright the picture comes out is decided by gain TIMES
        exposure, and nothing else. So this decides what that product should be
        and then asks _split how to pay for it.

        Writing it the other way round — a rule for gain, a separate rule for
        exposure, and interlocks to stop them fighting — is what the module used
        to do, and every one of the interlocks was there because the two had
        fought. Worst of them: moving a rung changed the brightness by a factor
        of two all on its own, so lengthening a card that was merely a little
        dark blew it out, which shortened it straight back, for ever. With the
        product controlled, a rung change is paid for in gain and the picture
        does not move at all, so that cycle cannot be written.

        Returned rather than applied, and returned whole: this used to hand back
        a gain and move the exposure as a side effect, so the caller had to
        snapshot `self.exposure` before the call and diff it afterwards.

        `has_screen` is the caller saying whether there is actually a phone in
        view. Brightening an empty mount is not a smaller mistake than getting
        the brightness wrong — it is a worse one. The window handed here is
        wherever the screen was last seen, so with the phone gone it is dark car
        interior, and raising gain against it wound the rig to its 8.0 ceiling
        in about 78 seconds chasing a card that was not there. The phone then
        came back to a card blown out at 8x and took another minute to climb
        down — a minute that lands exactly when the driver has picked the phone
        up to look at an offer.
        """
        blown = clipped_fraction(gray) > CLIPPED_FRACTION

        # A blown-out card is unreadable, so there is no offer being disturbed
        # by moving now, and nothing to be gained by idling on a beat meant for
        # gentle tracking. The slow beat is for the direction that can rail.
        if self.last is not None and now - self.last < (BLOWN_EVERY if blown
                                                        else self.every):
            return {}
        self.last = now

        bright = brightness(gray)
        if bright <= 0:
            return {}

        light = self.gain * (self.exposure or 1.0)

        if blown:
            # No measurement is possible here and that is the whole difficulty.
            # `brightness` is a percentile and every percentile of a card at
            # full well is 255, so a fifth too bright and eight times too bright
            # read exactly alike — measured on the rig's own test cards, 255.0
            # at 1.25x and still 255.0 at 8x. The old code answered both with
            # the same 18% nibble, which took 36 seconds to undo a doubling of
            # the phone's brightness and 48 to undo an eightfold, against an
            # offer that lives 30 to 45 seconds.
            #
            # So the size of the cut cannot be reasoned to; it has to be
            # searched for. Start at the ordinary step, and square it every beat
            # the picture comes back at full well — which converges on any
            # excursion in a handful of beats without over-correcting a nudge.
            want = light / self.cut
            self.cut = min(self.cut ** BLOWN_ESCALATE, BLOWN_MAX_STEP)
        else:
            self.cut = BLOWN_STEP
            self.stuck = False
            if abs(bright - self.target) / self.target <= GAIN_TOLERANCE:
                # On target. Nothing to correct — but the same picture may still
                # be payable with a longer exposure and less gain, so ask.
                want = light
            elif bright > self.target:
                # Over target and still off the rail, so the error is a real
                # measurement for once. Move once, by what it says.
                want = light * self.target / bright
            elif has_screen and bright >= LIT_ENOUGH:
                # Under target, with a screen to aim at, and off the rail — so
                # this is a measurement too, and it is answered by what it says
                # rather than by a constant.
                #
                # Capped, which is the part the constant was really buying. The
                # danger up here was never the size of a correct step, it was a
                # step computed from a window that is not the card: a quad
                # drifted onto dark upholstery reads as a very dim screen and
                # asks for everything. UP_MAX bounds one beat's damage to a
                # factor the next beat can undo, and `has_screen` above turns
                # the whole branch off when the tracker knows the phone is gone.
                want = light * min(self.target / bright, UP_MAX)
            else:
                # Under target, and this might be an empty mount rather than a
                # dim card. Raising the light is what wound the gain to its
                # ceiling against dark upholstery — but redistributing the light
                # already in hand is not raising it, and lengthening the
                # exposure toward what calibration measured is free besides.
                #
                # It is also the only way out of a hole the rig digs itself. A
                # card underexposed by the rig's own daylight shortening looks
                # exactly like an empty mount, so a rig that waited for this
                # guard to lift would wait for ever: the thing keeping the
                # picture dark is the thing being guarded. That happened, on a
                # 2083us exposure against a night-time card reading 6.
                want = (light if self.exposure is None
                        else self.gain * self.candidates[-1])

        return self._settle(want, blown)

    def _settle(self, want, blown):
        """Pay for `want` units of light, and say what to send the camera."""
        gain, rung, stuck = self._split(want, blown)
        self.stuck = self.stuck or stuck

        moved = rung is not None and rung != self.exposure
        ctrls = {}
        if moved:
            self.exposure = rung
            ctrls['ExposureTime'] = int(rung)
        # The gain goes with it whenever the rung changed, however small the
        # change: the two are a single move, and sending one without the other
        # is what a factor-of-two jump in brightness looks like.
        if moved or abs(gain - self.gain) >= 0.01:
            self.gain = gain
            ctrls['AnalogueGain'] = float(gain)
        return ctrls

    def _rungs(self, blown):
        """Which exposures are on offer this beat.

        A ladder measured on this screen may be walked freely: every rung came
        back quiet, so trading exposure against gain cannot make the picture
        ripple, and the longest affordable rung is always the least noisy way to
        take it.

        A ladder nobody measured is a different thing — a guess about panels in
        general, and on the commonest one the rung below 16667us is precisely
        the rung that bands. So an unmeasured rig only goes shorter in the
        emergency the old code kept it for: a card blown out with the gain
        already on its floor, where the choice is between a picture that might
        ripple and a picture that is certainly white. Never for a tidier split.
        """
        if self.ladder_measured or blown or self.exposure is None:
            return self.candidates
        return tuple(c for c in self.candidates if c >= self.exposure)

    def _split(self, want, blown):
        """The longest exposure that can carry `want`, and the gain to go with it.

        Longest first, because exposure up to what calibration measured is free
        and gain is noise: of every split that gives the same picture, the one
        with the longest exposure is the quietest. Returns (gain, exposure,
        out_of_room).
        """
        lo, hi = self.limits
        if self.exposure is None:               # nothing to manage but the gain
            return max(lo, min(hi, want)), None, want < lo

        shortest = None
        for rung in sorted(self._rungs(blown), reverse=True):
            shortest = rung
            gain = want / float(rung)
            if gain > hi:
                # Longer rungs need less gain and this is the longest there is,
                # so no split on the ladder can make the picture this bright.
                return hi, rung, False
            # A margin before *lengthening*, and none before shortening. Rungs
            # are a factor of two apart and the gain floor is 1.0, so the point
            # at which a longer rung becomes affordable is exactly the point at
            # which it becomes unaffordable again — and without a margin a light
            # level sitting on it flaps the exposure back and forth for ever, at
            # identical brightness, writing a control and a log line each time.
            floor = lo * (LENGTHEN_MARGIN if rung > self.exposure else 1.0)
            if gain >= floor:
                return gain, rung, False
        # Off the short end: the shortest rung at the gain floor is still more
        # light than was asked for. That is the phone being brighter than this
        # camera can take, and the remedy is the driver's.
        return lo, shortest, True
