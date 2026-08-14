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
# 20ms and 40ms entries also cover 50Hz and 100Hz panels.
FLICKER_SAFE = (8333, 16667, 20000, 25000, 33333, 40000, 50000)

# The default when nothing has been measured. One 60Hz cycle: safe for the
# commonest family and bright enough for a dimmed screen at night.
DEFAULT_EXPOSURE = 16667

# What a well-exposed card looks like. Measured on the bright part of the
# picture — the card is white, so its own brightness is the thing to aim.
TARGET_BRIGHT = 205.0
BRIGHT_PERCENTILE = 90
CLIPPED_AT = 250.0
CLIPPED_FRACTION = 0.08     # above this much blown-out white, back off

# Gain moves in steps this size, and stays inside these limits. Small steps
# because this runs between offers and has no deadline; limits because gain is
# noise, and past about 8x an IMX519 frame is mush.
GAIN_STEP = 1.18
GAIN_LIMITS = (1.0, 8.0)
GAIN_TOLERANCE = 0.10       # within 10% of target is close enough to leave alone


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
    best = min(tied, key=lambda r: abs(r['bright'] - target))
    return best['exposure'], report


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
    """

    def __init__(self, gain=1.5, target=TARGET_BRIGHT, every=6.0,
                 step=GAIN_STEP, limits=GAIN_LIMITS):
        self.gain = float(gain)
        self.target = target
        self.every = every
        self.step = step
        self.limits = limits
        self.last = None
        self.moves = 0

    def update(self, gray, now):
        """Returns a new gain to apply, or None to leave it alone."""
        if self.last is not None and now - self.last < self.every:
            return None
        self.last = now

        bright = brightness(gray)
        if bright <= 0:
            return None
        # Clipping is worse than dimness: detail that is blown out is gone,
        # while a dim card still has its edges.
        if clipped_fraction(gray) > CLIPPED_FRACTION:
            return self._set(self.gain / self.step)
        if abs(bright - self.target) / self.target <= GAIN_TOLERANCE:
            return None
        return self._set(self.gain * (self.step if bright < self.target else 1 / self.step))

    def _set(self, gain):
        gain = max(self.limits[0], min(self.limits[1], gain))
        if abs(gain - self.gain) < 0.01:
            return None
        self.gain = gain
        self.moves += 1
        return gain
