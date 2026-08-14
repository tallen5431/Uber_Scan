"""Keep the calibrated corners on the phone while the phone drifts.

Calibration assumes a fixed mount, and a mount is not a clamp. The phone comes
out for a message and goes back a centimetre over; the bracket sags on a rough
road; the cradle gets nudged reaching for the cup holder. None of that is enough
to notice by eye, and all of it moves the corners.

That matters more than it sounds, because the corners are not used directly —
the card is cropped as a *fraction* of whatever they enclose. Slide the phone up
so its top leaves the frame and the quad shrinks to the part still visible, the
same fraction now lands lower on the real screen, and the crop walks off the
payout. The scanner then reports, perfectly confidently, that there is no offer
on a screen with an offer on it.

So the corners are re-found while scanning. The whole job here is doing that
without ever making things worse than the stored calibration:

  * a candidate has to look like the screen we already know — similar size,
    near the same place — before it is allowed to move anything,
  * it has to say the same thing several checks running, so a hand crossing the
    frame or one bad threshold cannot steal the lock,
  * and it is then eased toward, not jumped to, so the crop never twitches
    mid-offer.

A candidate that fails the first test but keeps insisting anyway is treated as a
mount that genuinely moved, and adopted outright after twice the agreement. That
is the difference between drift and a knock, and both need handling.
"""

import time

import numpy as np

try:
    from . import pipeline as PL
except ImportError:      # running as a plain script
    import pipeline as PL


# Corners are re-found no more often than this. Finding them on the preview
# stream costs about a millisecond, so this is set by how fast the answer should
# arrive rather than by what it costs: at 0.4s the corners follow a nudge within
# about two seconds instead of the six the old 1.5s interval took.
RECHECK_EVERY = 0.4

# Agreeing checks before the corners are allowed to move. Raised alongside the
# faster interval on purpose — five checks at 0.4s is both quicker to react and
# strictly more evidence than three at 1.5s, so a hand crossing the frame has to
# work harder to be believed, not less.
AGREE = 5

# How far a candidate may sit from the current corners and still count as the
# same screen, as a fraction of the screen's own diagonal.
MAX_JUMP = 0.22

# ...and how close two consecutive candidates must be to count as agreeing.
SETTLE = 0.06

# Fraction of the way to the candidate on each accepted check. Converges in a
# handful of checks while staying immune to a single noisy detection.
EASE = 0.35

# Corner movement, in capture pixels, worth writing to disk — and how often at
# most. The file only exists so the next run starts where this one ended.
SAVE_DRIFT = 10.0
SAVE_EVERY = 30.0


class QuadTracker:
    """Follows the phone screen, starting from a calibrated quad.

    `scale` converts a corner found in the tracking image into capture
    coordinates, which is what the stored quad is in. Pass the ratio of capture
    size to tracking size when following on the small preview stream — the
    corners of a phone are a coarse feature and finding them there costs about a
    seventh of finding them on a downscaled sensor frame, because the small
    stream is already the right size and the sensor frame is not.
    """

    def __init__(self, quad, scale=1.0, recheck=RECHECK_EVERY, agree=AGREE, ease=EASE,
                 save_drift=SAVE_DRIFT, save_every=SAVE_EVERY):
        self.quad = np.asarray(quad, dtype=np.float32).reshape(4, 2)
        self.saved = self.quad.copy()
        # One number or an (x, y) pair; the streams are not always the same
        # aspect ratio to the last pixel, and a couple of pixels of skew across
        # a 1700px screen is not worth being sloppy about.
        self.scale = np.asarray(scale, dtype=np.float32).reshape(-1)
        if self.scale.size == 1:
            self.scale = np.array([self.scale[0], self.scale[0]], dtype=np.float32)
        self.recheck = recheck
        self.agree = agree
        self.ease = ease
        self.save_drift = save_drift
        self.save_every = save_every

        self.moves = 0          # times the corners were adjusted
        self.jumps = 0          # ...of those, how many were a re-lock, not drift
        self.misses = 0         # consecutive checks that found no screen at all
        self.agreeing = 0
        self._candidate = None
        self._last_check = None     # None, not 0, so the first check is always due
        self._last_save = 0.0

    # --- the loop calls these -------------------------------------------

    def update(self, frame, now=None):
        """Re-find the screen if it is time to. True when the corners moved."""
        now = time.time() if now is None else now
        if self._last_check is not None and now - self._last_check < self.recheck:
            return False
        self._last_check = now

        candidate = PL.detect_screen_quad(frame, work_width=PL.DETECT_WIDTH)
        if candidate is None:
            self.misses += 1
            self.agreeing = 0
            self._candidate = None
            return False
        candidate = candidate * self.scale

        self.misses = 0
        consistent = (self._candidate is not None
                      and near(candidate, self._candidate, SETTLE))
        self.agreeing = self.agreeing + 1 if consistent else 1
        self._candidate = candidate

        if near(candidate, self.quad, MAX_JUMP):
            if self.agreeing >= self.agree:
                self.quad = ease_toward(self.quad, candidate, self.ease)
                self.moves += 1
                return True
            return False

        # Well away from the stored corners, and it has been saying so steadily:
        # the mount was moved rather than misread. Take the new position whole,
        # since easing toward it would spend seconds cropping the gap between
        # two places the card is not.
        #
        # It must still be the same *size* of thing. Without that check any
        # steady bright rectangle — a lit dashboard panel, a window at dusk —
        # can eventually claim the lock, and re-locking onto one is worse than
        # never moving at all: the corners are then confidently wrong.
        if self.agreeing >= self.agree * 2 and same_size(candidate, self.quad):
            self.quad = np.asarray(candidate, dtype=np.float32)
            self.agreeing = 0
            self.moves += 1
            self.jumps += 1
            return True
        return False

    def needs_save(self, now=None):
        """True when what is on disk is stale enough to be worth rewriting."""
        now = time.time() if now is None else now
        if now - self._last_save < self.save_every:
            return False
        return distance(self.quad, self.saved) > self.save_drift

    def mark_saved(self, now=None):
        self._last_save = time.time() if now is None else now
        self.saved = self.quad.copy()

    @property
    def drift(self):
        """How far the corners have walked from the last saved calibration."""
        return distance(self.quad, self.saved)

    def status(self):
        return {'moves': self.moves, 'jumps': self.jumps, 'misses': self.misses,
                'drift': round(self.drift, 1), 'lost': self.misses >= 3}


# --- geometry ---------------------------------------------------------------

def distance(a, b):
    """Mean distance between corresponding corners."""
    a = np.asarray(a, dtype=np.float32).reshape(4, 2)
    b = np.asarray(b, dtype=np.float32).reshape(4, 2)
    return float(np.mean(np.linalg.norm(a - b, axis=1)))


def span(quad):
    """The screen's own scale: the mean of its two diagonals."""
    q = np.asarray(quad, dtype=np.float32).reshape(4, 2)
    return float((np.linalg.norm(q[2] - q[0]) + np.linalg.norm(q[3] - q[1])) / 2.0)


# How far the diagonal may differ and still be the same phone, seen from a
# slightly different place. A phone that has genuinely moved in the mount stays
# about the same size; something a third bigger or smaller is a different thing.
SIZE_BAND = (0.78, 1.28)


def same_size(a, b):
    ratio = span(a) / max(span(b), 1.0)
    return SIZE_BAND[0] <= ratio <= SIZE_BAND[1]


def near(a, b, tolerance):
    """Within `tolerance` of b's own size — so the test means the same thing at
    any distance from the phone."""
    return distance(a, b) <= tolerance * max(span(b), 1.0)


def ease_toward(quad, target, fraction):
    a = np.asarray(quad, dtype=np.float32).reshape(4, 2)
    b = np.asarray(target, dtype=np.float32).reshape(4, 2)
    return (a + (b - a) * float(fraction)).astype(np.float32)
