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

A candidate that fails the *position* test but keeps insisting anyway is treated
as a mount that genuinely moved, and adopted after the same agreement as any
other move. It still has to look like the screen — the right size and the right
shape — which is the check that stopped an Accept bar being adopted as a phone.
That is the difference between drift and a knock, and both need handling.

The size test is judged against the calibration and never against where the
corners have got to, because a relative test has no floor and walks downhill.
The price is that a screen the calibration does not recognise can never be
adopted, however plainly it is there — re-seat the phone a little further back
and the real screen is refused on every check, forever, while `misses` stays at
zero so nothing reports it. So there is one bound on that: corners that sit off
a steady, phone-shaped screen for RECOVER_AFTER are taken as the stuck party,
moved onto it, and the calibration written off as out of date. Only the size
test is given up there; shape still decides, because size is what legitimately
changes when a phone is re-seated and shape is what tells a screen from the
Accept bar beneath it.
"""

import time

import cv2
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

# ...except on the centre path, which does not need five, and where the wait is
# most of what a driver feels as "slow".
#
# That path fires on three independent conditions at once: the candidate holds
# the middle of the frame, the corners do not, and the shape still matches the
# calibration. To fool it you would need a phone-shaped bright thing dead centre,
# holding still, at a moment when the outline is already off the middle — and
# being off the middle is itself the fault being corrected. It is also
# self-limiting: the move puts the corners on the centre, and the path's second
# condition then refuses to fire again, so it cannot oscillate.
#
# Five checks on top of that is evidence bought twice. Measured against a
# simulated loop with a Pi's read costs, dropping to two takes a re-lock from
# 3.6s to 2.0s — and the greater part of that saving is not the 1.2s of waiting,
# it is the reads that no longer happen on the old rectangle while it waits.
CENTRE_AGREE = 2

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

# How long the corners may sit somewhere else while the detector goes on
# offering a steady, phone-shaped screen, before the stored calibration is
# treated as the thing that is out of date.
#
# Judging candidates against the calibration is what stops the corners walking
# downhill, and it has no upper bound by design — but that cuts both ways. A
# phone re-seated a little further back, or a mount knocked closer, is a screen
# the size test refuses *every time*, forever: the corners freeze wherever they
# were, and because a candidate was found on each check `misses` stays at zero,
# so nothing reports it as lost. The green box simply stops moving and the log
# goes on saying "corners held".
#
# Thirty seconds is far longer than any real re-lock takes — those complete in
# about two — so this cannot fire in place of the ordinary path. It is also
# deliberately longer than a candidate of the wrong size is given to insist:
# refusing one of those is a protection worth keeping at the timescale it was
# written for, and this only overrides it once being stuck has become the more
# likely explanation than being lured onto a sub-region of the screen.
RECOVER_AFTER = 30.0

# ...and how long before it is worth *saying* so. The clock starts on the first
# check that finds the corners off the screen, which is also what an ordinary
# move looks like for the two seconds it spends gathering agreement — so
# reporting from the first check called every routine drift "stuck" and made the
# word useless. Comfortably longer than AGREE * RECHECK_EVERY, comfortably
# shorter than the recovery itself.
STALL_VISIBLE = 5.0

# Consecutive checks finding no screen at all before the phone counts as gone.
LOST_AFTER = 3

# How long a disputed outline is worth waiting for before reading anyway.
#
# While the detector can see a screen that is not where the corners are, the
# crop is being taken from a rectangle already known to be wrong, and reading it
# is not merely wasted — a read blocks the loop, and the loop is what runs the
# tracker, so it delays the correction it is waiting on. A rig took eight reads
# to produce one verdict and seven of them were of the old rectangle.
#
# Bounded, because "the detector can see something" is not proof it is the
# phone, and a scanner that will not read until it is happy is worse than one
# that reads a bad crop. Two seconds is about one re-lock; past that, read.
DISPUTE_PATIENCE = 2.0


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
                 save_drift=SAVE_DRIFT, save_every=SAVE_EVERY, calibrated=None,
                 recover_after=RECOVER_AFTER, centre_agree=CENTRE_AGREE,
                 dispute_patience=DISPUTE_PATIENCE):
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
        self.centre_agree = min(centre_agree, agree)
        self.dispute_patience = dispute_patience
        self.ease = ease
        self.save_drift = save_drift
        self.save_every = save_every

        self.recover_after = recover_after

        self.moves = 0          # times the corners were adjusted
        self.jumps = 0          # ...of those, how many were a re-lock, not drift
        self.misses = 0         # consecutive checks that found no screen at all
        self.rebaselines = 0    # ...and how often the calibration itself gave way
        self.centred = 0        # ...of those, how many were the centre rule
        self.resets = 0         # times the driver asked for a fresh start
        self.agreeing = 0
        self._candidate = None
        self._disputed_since = None  # when the corners were last visibly wrong
        self._off_since = None       # ...and how long they have been off the screen
        self._last_check = None     # None, not 0, so the first check is always due
        self._last_save = 0.0
        # The screen the corners are *not* on, and how long that has been true.
        self._stuck_on = None
        self._stuck_since = None

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
            self._disputed_since = None
            self._forget_stall()
            # One check finding nothing is not evidence that the corners are
            # right — it is no evidence at all, and clearing the clock on it let
            # an intermittent detector hide a stuck outline the same way an
            # alternating one did. A screen that is genuinely gone does clear
            # it, because then there is nothing for the corners to be off.
            if self.misses >= LOST_AFTER:
                self._off_since = None
            return False
        candidate = candidate * self.scale

        self.misses = 0
        consistent = (self._candidate is not None
                      and near(candidate, self._candidate, SETTLE))
        self.agreeing = self.agreeing + 1 if consistent else 1
        self._candidate = candidate

        # "There is a screen there, and it is not where the corners are." Noted
        # here rather than derived by the caller, because the caller would have
        # to reach into the candidate to ask — and because this is precisely the
        # window in which reading the crop reads a rectangle already known to be
        # wrong. See disputing().
        if near(candidate, self.quad, MAX_JUMP):
            self._disputed_since = None
        elif self._disputed_since is None:
            self._disputed_since = now

        # ...and a second, blunter clock, for reporting rather than for deciding.
        #
        # It has to be separate from both of the others, because each of those is
        # switched off by the very thing being reported. `_disputed_since` is
        # cleared when the shape gate refuses a candidate, and `_stuck_since`
        # needs a candidate that matches the calibrated shape — so in the case
        # where the detector can only ever find the white card panel, neither
        # clock runs and the outline freezes without a word. This one asks only
        # "are the corners on whatever the camera can see?", which stays a fair
        # question no matter what any gate thinks of the answer.
        if distance(candidate, self.quad) <= SETTLE * max(span(candidate), 1.0):
            self._off_since = None
        elif self._off_since is None:
            self._off_since = now

        # Before the gate, because the gate is one of the things that can be
        # wrong. See _stalled.
        if self._stalled(candidate, now):
            self.quad = np.asarray(candidate, dtype=np.float32)
            # The reference moves too. Leaving it would mean unsticking the
            # corners once and then refusing every correction to them
            # afterwards, which is the same trap one step along.
            self.calibrated = self.quad.copy()
            self.agreeing = 0
            self._forget_stall()
            self.moves += 1
            self.jumps += 1
            self.rebaselines += 1
            return True

        # The card is presented in the middle of the frame. So a screen that
        # holds the centre, while the corners do not, is not a candidate to be
        # weighed against a stored size — it is the phone, and the corners are
        # on something else.
        #
        # This is the one piece of evidence that does not decay. The stored
        # position goes stale the moment the mount is nudged and the stored size
        # goes stale the moment the phone is re-seated, but where the driver
        # aims the card does not change: the detector already prefers the
        # bright shape the centre falls inside, and this is the tracker agreeing
        # with it. Shape still has to match, because that is what separates a
        # screen from the Accept bar under it — but size deliberately does not,
        # since a size the calibration refuses is exactly the state that leaves
        # the corners stuck with no way out.
        if self._holds_the_centre(candidate, frame) and self.agreeing >= self.centre_agree:
            self.quad = np.asarray(candidate, dtype=np.float32)
            self.calibrated = self.quad.copy()
            self.agreeing = 0
            self._forget_stall()
            self.moves += 1
            self.jumps += 1
            self.centred += 1
            return True

        # One gate, and it is measured against the calibration rather than
        # against wherever the corners have got to. See looks_like_the_screen.
        #
        # A rejected candidate takes its evidence with it. `agreeing` counts
        # how many checks running have seen the same thing, and a bare return
        # left the count standing — so a run of steadily-shrinking detections,
        # each refused, still walked the counter up to the bar. The first
        # candidate that then squeaked through the gate moved the corners on
        # sight, carrying the authority of ten sightings that were all of
        # something else.
        if not self.looks_like_the_screen(candidate):
            self.agreeing = 0
            self._candidate = None
            # Nor is there anything to dispute: a candidate the gate refuses is
            # not evidence that the corners are wrong, and holding reads on it
            # would stall the scanner every time a bright thing crossed the
            # frame — which is the whole reason the gate exists.
            self._disputed_since = None
            return False

        if near(candidate, self.quad, MAX_JUMP):
            # A correction this small, of a thing this shape, cannot be
            # anything but the screen. So a nudge is followed on the first
            # check that sees it, and only bigger moves argue their case.
            if self.agreeing >= self.agree or near(candidate, self.quad, NUDGE):
                self.quad = ease_toward(self.quad, candidate, self.ease)
                # Corners that are moving are not stuck, however far they still
                # have to go. Without this a slow ease-in kept the stall clock
                # running across its own successful moves, and a long enough
                # convergence turned ordinary drift into a re-baseline.
                self._forget_stall()
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
            self._forget_stall()
            self.moves += 1
            self.jumps += 1
            return True
        return False

    def _holds_the_centre(self, candidate, frame):
        """Is the candidate on the middle of the frame while the corners are not?

        Both tested in the tracking image's own coordinates, since that is what
        `frame` is; the stored corners are in capture space, so they come back
        down by the same scale that took the candidate up.
        """
        middle = (frame.shape[1] / 2.0, frame.shape[0] / 2.0)
        if not contains(candidate / self.scale, middle):
            return False
        if contains(self.quad / self.scale, middle):
            return False        # already on it; nothing to correct
        return same_shape(candidate, self.calibrated)

    def disputing(self, now=None):
        """True while a re-lock is being argued, and worth waiting out.

        The caller's question is "should I read right now?", and while this is
        true the answer is no: the crop is a fraction of the corners, the
        detector can see that the corners are on the wrong thing, and a read
        takes several hundred milliseconds of a small computer's whole
        attention. Worse than wasted — the loop that would fix the corners is
        the loop the read is blocking, so each wasted read pushes the correction
        further out. A rig produced one verdict from eight reads, seven of them
        of the rectangle it was in the middle of replacing.

        Bounded by dispute_patience, so a detector that never converges costs a
        couple of seconds rather than the whole shift.
        """
        if self._disputed_since is None:
            return False
        now = time.time() if now is None else now
        return now - self._disputed_since < self.dispute_patience

    def start_over(self):
        """Forget where the screen has got to, and go back to the calibration.

        The escape hatch for when the automatic recovery cannot be sure. It puts
        the corners back where calibration left them and drops every piece of
        accumulated evidence, so the next screen argues for itself from nothing
        rather than against a history that has gone wrong.
        """
        self.quad = self.calibrated.copy()
        self.agreeing = 0
        self._candidate = None
        self._disputed_since = None
        self._off_since = None
        self.misses = 0
        self.resets += 1
        self._forget_stall()

    def _forget_stall(self):
        self._stuck_on = None
        self._stuck_since = None
        self._off_since = None

    def _stalled(self, candidate, now):
        """Have the corners been sitting off the screen for far too long?

        This is the escape hatch for the one failure the absolute size gate
        creates. Judging candidates against the calibration is right — a
        relative test has no floor and the corners walk downhill — but it also
        means a screen the calibration does not recognise can never be adopted,
        however plainly it is there. Re-seat the phone a quarter further back
        and every detection of it is refused, on every check, forever, while
        `misses` stays at zero and the health line goes on saying the corners
        are held.

        Two conditions, and between them they separate being stuck from being
        walked downhill, which is the thing that must not be reintroduced:

          * **the candidate has to hold still.** A downhill walk is a sequence
            of *different* boxes, each a little smaller than the last; the
            anchor resets the moment one moves away from the one before it, so
            the clock never runs. A phone that has genuinely been re-seated
            sits exactly still, so its clock runs from the first check.
          * **it still has to be phone-shaped.** Only the size test is given
            up here, never the shape one — because size is what legitimately
            changes when a phone is re-seated or a mount is knocked, and shape
            is what tells a screen from the Accept bar underneath it. A strip
            can sit still all day and will never be adopted.

        And it only counts while the corners are not actually on the candidate.
        "On it" has to mean tracking it, not merely lying within re-lock range
        of it: the commonest way to be stuck is a *size* mismatch, where the
        frozen corners sit concentric with the screen and comfortably inside
        MAX_JUMP of it while being half again too big. Measured that way the
        watchdog never started its clock in the one case it was written for.
        The agreement tolerance is the right scale, and against the candidate's
        own size, so it means the same thing at any distance from the phone.
        """
        # Shape first, and — this is the part that was wrong — a candidate that
        # fails it leaves the clock exactly as it found it, rather than resetting
        # it.
        #
        # A detector does not always give the same answer twice. In bright light
        # the threshold that loses the sky is very nearly the threshold that
        # loses the grey map panel too, so consecutive checks can alternate
        # between the whole screen and just the white offer card on it. Those
        # are not two opinions about where the screen is; the second is not an
        # opinion about the screen at all. Treating it as one reset the anchor on
        # every other check, so the clock never got past a single interval: a
        # simulated rig ran 100 seconds with moves 0, jumps 0 — and `stalled`
        # never even became true, so nothing was reported either. A permanent,
        # silent freeze, which is exactly what "it gets stuck and never adapts"
        # looks like from the driver's seat.
        #
        # Only the size test is given up in here, never the shape one, because
        # size is what legitimately changes when a phone is re-seated and shape
        # is what tells a screen from the card panel on it.
        if not same_shape(candidate, self.calibrated):
            return False
        if distance(candidate, self.quad) <= SETTLE * max(span(candidate), 1.0):
            self._forget_stall()
            return False
        # SETTLE, not MAX_JUMP: the anchor has to mean "the same box", not
        # "a box in roughly that area". At re-lock tolerance an 0.82x step still
        # counts as the same thing, so a downhill walk kept one clock running
        # across every one of its steps and could have compounded straight
        # through this — the exact failure the anchored gate exists to stop.
        if self._stuck_on is None or not near(candidate, self._stuck_on, SETTLE):
            self._stuck_on = candidate
            self._stuck_since = now
            return False
        return now - self._stuck_since >= self.recover_after

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
                'rebaselines': self.rebaselines,
                'centred': self.centred,
                'resets': self.resets,
                'lost': self.misses >= LOST_AFTER,
                # Being stuck is not being lost, and it used to look identical
                # from out here: a candidate was found on every check, so
                # `misses` stayed at zero and nothing distinguished corners
                # tracking a screen from corners frozen beside one.
                #
                # Read off `_off_since` rather than the recovery anchor. The
                # anchor only advances on candidates that match the calibrated
                # shape, which is right for deciding whether to adopt one and
                # useless for saying whether anything is wrong: the worst case
                # is precisely the one where nothing the detector offers matches,
                # and reporting from the anchor there reported nothing at all.
                'stalled': (self._off_since is not None
                            and self._last_check is not None
                            and self._last_check - self._off_since >= STALL_VISIBLE)}


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
#
# Written as 1/lower for the same reason SIZE_BAND is, and it was not: 1/0.70
# is 1.428571 and this said 1.43, which accepts a ratio whose inverse it
# refuses. That is the sliver where A can adopt B and B can never adopt A back
# — the exact defect the commit above this one removed from SIZE_BAND, put
# straight back in the band added alongside it.
ASPECT_BAND = (0.70, 1.0 / 0.70)


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


def contains(quad, point):
    """Is this point inside the quad?"""
    q = np.asarray(quad, dtype=np.float32).reshape(4, 2)
    return cv2.pointPolygonTest(q, (float(point[0]), float(point[1])), False) >= 0


def near(a, b, tolerance):
    """Within `tolerance` of b's own size — so the test means the same thing at
    any distance from the phone."""
    return distance(a, b) <= tolerance * max(span(b), 1.0)


def ease_toward(quad, target, fraction):
    a = np.asarray(quad, dtype=np.float32).reshape(4, 2)
    b = np.asarray(target, dtype=np.float32).reshape(4, 2)
    return (a + (b - a) * float(fraction)).astype(np.float32)
