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

# ...and within how far it is a nudge rather than a move: close enough that,
# given it is also the same size, there is nothing else it could be. Followed
# without waiting for agreement.
NUDGE = 0.05

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
                 save_drift=SAVE_DRIFT, save_every=SAVE_EVERY, calibrated=None):
        self.quad = np.asarray(quad, dtype=np.float32).reshape(4, 2)
        self.saved = self.quad.copy()
        # The screen as *calibrated*, which is not always where tracking starts.
        # Never updated within a run, because it is the one fixed thing a
        # candidate can be judged against, and judging against anything that
        # moves is what let the corners walk off the phone.
        #
        # Passed in separately for a reason that only shows up across restarts.
        # The tracked position is written back to config.json so the next run
        # resumes where this one ended — sensible — but if that file's `quad`
        # were also the reference, every run would re-anchor to wherever the
        # last one finished and the per-run bound would compound exactly as the
        # per-check one used to. Measured: two runs beside a phone-shaped decoy
        # went 100% -> 79% -> 63%. So the calibration is kept apart from the
        # position and only calibration writes it.
        self.calibrated = (self.quad.copy() if calibrated is None
                           else np.asarray(calibrated, dtype=np.float32).reshape(4, 2).copy())
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

        # One gate, and it is measured against the calibration rather than
        # against wherever the corners have got to. See looks_like_the_screen.
        if not self.looks_like_the_screen(candidate):
            return False

        if near(candidate, self.quad, MAX_JUMP):
            # A correction this small, of a thing this shape, cannot be
            # anything but the screen. So a nudge is followed on the first
            # check that sees it, and only bigger moves argue their case.
            if self.agreeing >= self.agree or near(candidate, self.quad, NUDGE):
                self.quad = ease_toward(self.quad, candidate, self.ease)
                self.moves += 1
                return True
            return False

        # Well away from where the corners are, and it has been saying so
        # steadily: the phone was moved, or taken away and put back. Take it
        # whole, since easing across the gap spends seconds reading neither
        # place.
        #
        # This used to demand twice the agreement, which measured out at 93% of
        # a 4.2s recovery — and more like 10s on a Pi, because a read in flight
        # stops the loop from honouring the 0.4s recheck at all. That caution
        # was buying protection the shape gate now provides outright, so it is
        # the same bar as any other move.
        if self.agreeing >= self.agree:
            self.quad = np.asarray(candidate, dtype=np.float32)
            self.agreeing = 0
            self.moves += 1
            self.jumps += 1
            return True
        return False

    def looks_like_the_screen(self, candidate):
        """Is this the phone, judged against the screen that was calibrated?

        Two things, and both matter for a reason found the hard way.

        **Against the calibration, not against the current corners.** A
        relative test has no floor. Every step is "the same size as the last
        one", every step looks reasonable, and the corners walk downhill: six
        candidates each 80% of the one before left a rig at 63% of its
        calibrated screen. Then the trap closes — the real phone is now 1.57x
        the shrunken box, outside the band the other way, so the one thing the
        tracker exists to find is the one thing it can no longer accept. A rig
        sat there permanently, with the detector handing it corners that were
        exactly right and both gates refusing them. The phone does not change
        size and the mount is fixed, so there is an absolute answer available
        and no reason to use a relative one.

        **Shape, not just scale.** `span` is the mean of the diagonals, and a
        diagonal says nothing about proportions: a 1340x230 strip along the
        bottom of the frame — the Accept button and the dark below it — scores
        0.82 against a 695x1512 phone and sails through a test called
        `same_size`. That is not a hypothetical; it is the outline a rig was
        photographed wearing while a readable offer sat above it.
        """
        return (same_size(candidate, self.calibrated)
                and same_shape(candidate, self.calibrated))
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
        """What the corners are doing, in terms a log line can use.

        `drift` is against the last *saved* calibration, which mark_saved
        re-baselines — so a tracker that has walked a long way and then written
        itself to disk reports a contented zero. That is exactly what a rig did
        while its corners sat 826px off the phone: "corners held, drift 0px
        from saved", every health line, indefinitely. `wander` is against the
        calibration this run started from and is never re-baselined, so it is
        the number that can still see a problem after the file has caught up
        with it.
        """
        return {'moves': self.moves, 'jumps': self.jumps, 'misses': self.misses,
                'drift': round(self.drift, 1),
                'wander': round(distance(self.quad, self.calibrated), 1),
                'lost': self.misses >= 3}


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
#
# This guards both paths, and for a while it only guarded the dramatic one. The
# reasoning was that a re-lock takes the candidate whole, so it had better be
# the right thing — while drift only eases 35% of the way and looked harmless.
# It is not harmless: easing has no floor. A candidate a fifth smaller than the
# screen sits inside MAX_JUMP, so the outline could be walked down onto the
# white card, or onto the lit half of a dimmed screen, one third at a time,
# with every individual step looking reasonable. That is a green box that ends
# up too small for no visible reason, and a crop measured against it that is
# wrong in a way nothing downstream can detect.
SIZE_BAND = (0.78, 1.0 / 0.78)


def same_size(a, b):
    ratio = span(a) / max(span(b), 1.0)
    return SIZE_BAND[0] <= ratio <= SIZE_BAND[1]


# How far the proportions may differ and still be the same screen. Generous,
# because perspective genuinely skews a quad and a dimmed map can shorten the
# lit part of a screen; nowhere near generous enough to admit a strip.
ASPECT_BAND = (0.70, 1.43)


def sides(quad):
    """Mean width and mean height of the quad, in its own units."""
    q = np.asarray(quad, dtype=np.float32).reshape(4, 2)
    across = (np.linalg.norm(q[1] - q[0]) + np.linalg.norm(q[2] - q[3])) / 2.0
    down = (np.linalg.norm(q[3] - q[0]) + np.linalg.norm(q[2] - q[1])) / 2.0
    return float(across), float(down)


def aspect(quad):
    across, down = sides(quad)
    return down / max(across, 1.0)


def same_shape(a, b):
    """Same proportions, which `same_size` cannot see.

    span() is the mean of the diagonals, and a diagonal is one number about a
    rectangle that needs two. A 1340x230 strip and a 695x1512 phone have
    diagonals within 18% of each other, so a test on span alone calls a flat
    bar the same thing as a tall screen. A rig was photographed with its
    outline on exactly that bar — the Accept button and the dark beneath it —
    while the offer it was supposed to be reading sat above it, untouched.
    """
    ratio = aspect(a) / max(aspect(b), 0.01)
    return ASPECT_BAND[0] <= ratio <= ASPECT_BAND[1]


def near(a, b, tolerance):
    """Within `tolerance` of b's own size — so the test means the same thing at
    any distance from the phone."""
    return distance(a, b) <= tolerance * max(span(b), 1.0)


def ease_toward(quad, target, fraction):
    a = np.asarray(quad, dtype=np.float32).reshape(4, 2)
    b = np.asarray(target, dtype=np.float32).reshape(4, 2)
    return (a + (b - a) * float(fraction)).astype(np.float32)
