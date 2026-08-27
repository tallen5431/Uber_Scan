"""Frame in, verdict out. No camera dependency, so it runs and is tested off-Pi.

The speed of this thing comes from what it refuses to do:

  * it does not OCR while nothing is changing (a cheap motion gate),
  * it does not OCR a moving frame (waits for the picture to settle),
  * it does not OCR the whole sensor frame (warps to just the phone screen),
  * it does not OCR at 16MP (downscales to the smallest size that keeps a
    decimal point legible),
  * and it does not spend a third of each read compressing a PNG nobody wants
    (see stage_for_ocr).

Tesseract's cost is mostly the recogniser walking the text, not the image: four
times the pixels measured 26% more time. So the wins are in not running it, and
in not making it read the same page twice (see OCR_CONFIG) — not in shaving
pixels off a picture it was going to read either way.

...and the largest one was in not *starting* it. That paragraph was written
about a `tesseract` process spawned per read, and a fresh process re-loads and
unpacks the LSTM model before it looks at a pixel: 81.8ms of a 129.1ms read, or
63% of it, and paid again on each of the four (median) to fourteen (worst) reads
merged into one stored offer. The engine is now initialised once and kept — same
library, same model, byte-identical output — and a whole read went from 187.1ms
to 88.3ms. See _Tesseract.
"""

import atexit
import ctypes
import os
import shlex
import tempfile
import threading
import time
from concurrent import futures

import cv2
import numpy as np

# OpenMP pinned to one thread per tesseract instance, always, and set here
# because here is the last moment it can be: tesseract now runs inside this
# process (see _Tesseract) and libgomp reads the environment when it first
# starts a parallel region, not when a subprocess is spawned. Importing this
# module is what loads the library, so this has to be above that import.
#
# Two reads at once need it or they fight over all four cores: unpinned, a pair
# measured 46 seconds against 435ms sequential. It is unconditional because a
# single read is not alone on the machine either — it runs beside the camera
# loop, which is capturing, gating, tracking and writing the live view
# throughout, so an unpinned tesseract spreading over four cores takes them from
# the thing whose whole purpose is to keep going during a read. Pinning costs a
# single read nothing measurable.
#
# setdefault, so an explicit setting still wins.
OMP_THREAD_LIMIT = os.environ.setdefault('OMP_THREAD_LIMIT', '1')

import pytesseract                                            # noqa: E402

try:
    from . import offer_parser as OP
except ImportError:  # running as a plain script
    import offer_parser as OP


# --- tuning ---------------------------------------------------------------

MOTION_SIZE = (160, 120)   # the gate runs on a thumbnail; it is nearly free
CHANGE_T = 6.0             # mean abs difference that counts as "something happened"
STILL_T = 2.0              # ...and below which the picture has settled again
CARD_HEIGHT = 1100         # canonical warp height; the decimal point needs this
# tessedit_do_invert=0 is the one engine switch worth setting. When a page
# scores badly, tesseract runs the whole thing again inverted in case it was
# white-on-black — and preprocess() hands it dark text on a light card every
# single time, so that second pass can never help and is pure cost. It is paid
# exactly where it hurts most, on the reads that fail: a map costs 282ms with
# the retry and 211 without, a dark screen 199 against 154. Half of a driving
# shift's reads are of something that is not an offer.
OCR_CONFIG = '--oem 1 --psm 6 -c tessedit_do_invert=0'

# ...and what to try when that reading came back with a journey but no payout.
#
# psm 6 is told the image is one uniform block of text. An offer card is not:
# the payout is set two or three times the size of every other line, and layout
# analysis sometimes decides an outlier that large is not part of the block and
# drops it. The rest of the card reads perfectly, so the failure is silent — a
# close, clean, well-lit mount returned "Guaranteed (incl. tip) / 6 items /
# 34 min (3.6 mi) total" with no money on it at all. Measured over rendered
# cards at eight mount distances, psm 6 lost the payout on 6 of 32 otherwise
# perfect frames.
#
# psm 4 is "a single column of text of variable sizes", which is exactly what an
# offer card is, and it read all 32. It is not the default only because that is
# a bigger claim than this evidence supports: on frames degraded the way a
# windscreen degrades them — banding, glare, defocus, a dimmed screen — the two
# measure the same, and none of this was checked against real captures. So the
# second mode is used as a *retry*, on the one shape of failure it is known to
# fix, where it cannot regress any read that works today.
RECOVER_CONFIG = '--oem 1 --psm 4 -c tessedit_do_invert=0'

# How tall the card image handed to tesseract should be, whatever the mount
# gives us. This is the single highest-value number in the file.
#
# Tesseract is trained on scanned text and wants roughly a 20px x-height; below
# that its accuracy falls off a cliff. A phone card measuring a healthy 420px on
# the sensor, cropped out of a screen warped to 900, arrives about 450px tall
# with eight lines of text on it — an x-height near 10px, squarely in the bad
# regime. Interpolating it up adds no information, but it puts the strokes back
# on the grid the engine expects, and measured over a synthetic sweep of card
# sizes and noise it took exact reads from 12/36 to 29/36. The cost is roughly
# +60% on the OCR call, which is the cheapest accuracy ever sold.
#
# Sharpening and binarising were tried here too and both made things markedly
# worse: an unsharp mask eats the thin "$" and Otsu closes up the small digits.
OCR_CARD_HEIGHT = 900

# How much of a phone screen the offer card itself occupies. Used to turn the
# card target above into a warp height for the whole screen, so that the size of
# the text handed to the reader is a property of the card and not of however
# much slack the crop happens to be carrying around it.
CARD_SHARE = 0.5

# Corner-finding runs on a thumbnail this wide. A phone's outline is a coarse
# feature, so the answer is the same to within a pixel once scaled back, and it
# costs about a tenth as much — which is what makes re-checking it while
# scanning affordable.
DETECT_WIDTH = 640


def detect_screen_quad(frame, min_area_frac=0.05, max_area_frac=0.90, work_width=None):
    """Find the phone screen: in a dark car it is the bright rectangle.

    A result covering nearly the whole frame is rejected. Otsu splits an image
    into light and dark whatever is in it, so a scene with no dark surround
    "finds" a screen the size of the picture — and calibrating on that makes the
    card region an arbitrary strip of the room. Better to report no screen and
    say why than to lock in a frame-shaped one.

    `work_width` detects on a thumbnail and scales the corners back up, for
    callers that run this repeatedly rather than once.
    """
    src = frame
    scale = 1.0
    if work_width and frame.shape[1] > work_width:
        scale = work_width / float(frame.shape[1])
        src = cv2.resize(frame, (int(work_width), max(1, int(round(frame.shape[0] * scale)))),
                         interpolation=cv2.INTER_AREA)

    quad = _detect_quad(src, min_area_frac, max_area_frac)
    return None if quad is None else quad / scale


# How much taller than wide a candidate has to be. A phone in portrait is about
# 2:1; a windscreen, a bonnet reflection and the strip of sky above the dash are
# all far wider than they are tall. Generous enough for a phone clipped by the
# frame or seen at an angle, which is why it is not near 2.0.
UPRIGHT = 0.90

# Thresholds to try, in order, as percentiles of the frame's own brightness.
#
# Otsu first, because in the case this rig was built for — a lit phone in a dark
# car — it is exactly right and nothing beats it. But Otsu splits whatever it is
# given into light and dark, and through a windscreen at sunset the bright half
# is the sky, the glass, the bonnet AND the phone, all one blob: measured on a
# rendered sunset it chose 120 on a frame averaging 170 and returned a single
# contour covering 80% of the picture, which the frame-shaped guard then threw
# away. The rig reported "screen not visible" with the offer plainly in view.
#
# So when Otsu's answer is not shaped like a phone, the threshold climbs. Each
# step keeps only a brighter slice, and a phone card — which is white — survives
# further up than sky, glass or paintwork.
# The low rungs are not padding. The gap between Otsu and the 70th percentile is
# where a whole phone gets lost: on the rendered sunset Otsu chose 120 and the
# 70th chose 233, and 233 is a hair above the grey of the map panel at the top of
# an offer screen. So the ladder skipped from "the sky, the glass and the phone,
# all one blob" straight to "the white card only" with nothing in between, and
# what it locked onto was the card panel rather than the screen. Every fraction
# downstream is measured against the quad, so a quad that is the card is not a
# smaller error than no quad — it is a crop placed from the wrong rectangle, and
# it read the journey off the card and lost the payout. With 55 and 62 in the
# ladder the same scene finds the whole phone at every mount distance tried.
BRIGHT_LEVELS = (55, 62, 70, 80, 86, 91, 95, 97)


def _looks_like_a_phone(contour, shape, min_area_frac, max_area_frac):
    """Could this contour be a phone screen, on size and proportion alone?"""
    h, w = shape[:2]
    area = cv2.contourArea(contour)
    if area < h * w * min_area_frac or area > h * w * max_area_frac:
        return False
    bx, by, bw, bh = cv2.boundingRect(contour)
    # A phone stood in portrait can fill the frame's height, but it cannot also
    # fill its width — the frame is 4:3 and the phone is about 1:2. Something
    # spanning both dimensions is the picture itself, not a screen in it, which
    # is what Otsu returns when the scene has no darker surround to split off.
    if bw > w * 0.95 and bh > h * 0.95:
        return False
    # ...and it is taller than it is wide, which the sky above a dashboard and
    # the Accept bar below the card both are not.
    return bh >= bw * UPRIGHT


def _quad_of(contour):
    peri = cv2.arcLength(contour, True)
    for eps in (0.02, 0.03, 0.05, 0.08):
        approx = cv2.approxPolyDP(contour, eps * peri, True)
        if len(approx) == 4:
            return order_quad(approx.reshape(4, 2).astype(np.float32))
    # Not a clean quadrilateral: fall back to the rotated bounding box.
    return order_quad(cv2.boxPoints(cv2.minAreaRect(contour)).astype(np.float32))


def _pick(contours, shape, min_area_frac, max_area_frac):
    """The candidate most likely to be the card the driver is holding up.

    Nearest the middle, not biggest. The driver aims the card at the centre of
    the frame — it is the one thing about the scene they control — so distance
    from the centre is better evidence than area, and it is evidence that does
    not go stale the way a stored position does. Preferring size instead is what
    let the outline wander onto a lit dashboard panel, a window at dusk, or a
    passenger's own screen, every one of which can be bigger than the phone.
    """
    h, w = shape[:2]
    centre = np.array([w / 2.0, h / 2.0], dtype=np.float32)
    fits = [c for c in contours
            if _looks_like_a_phone(c, shape, min_area_frac, max_area_frac)]
    if not fits:
        return None

    def score(contour):
        m = cv2.moments(contour)
        if m['m00'] <= 0:
            return 1e9
        middle = np.array([m['m10'] / m['m00'], m['m01'] / m['m00']], dtype=np.float32)
        # As a fraction of the frame, so it means the same on a thumbnail as on
        # a sensor frame. A candidate the centre actually falls inside is
        # preferred outright, since that is a stronger statement than being
        # merely close to it.
        away = float(np.linalg.norm(middle - centre)) / max(w, h)
        holds = cv2.pointPolygonTest(contour, (centre[0], centre[1]), False) >= 0
        return away - (1.0 if holds else 0.0)

    return min(fits, key=score)


# Thresholds for the second pass, as percentiles of how far each pixel is from
# the cabin — see _different_from_cabin.
DIFFERENCE_LEVELS = (60, 70, 78, 85, 90, 94)

# How much of the frame's edge is taken as surround rather than subject.
CABIN_BORDER = 0.10


def _cabin_level(gray, border=CABIN_BORDER):
    """The surround's own brightness, taken from the frame's outer ring.

    The driver aims the card at the middle of the frame, so the edge of it is
    the one part that is nearly always car rather than phone. Median rather than
    mean, because a ring that clips the corner of a bright screen should not
    drag the answer with it.
    """
    h, w = gray.shape[:2]
    bh, bw = max(1, int(h * border)), max(1, int(w * border))
    ring = np.concatenate([gray[:bh].ravel(), gray[-bh:].ravel(),
                           gray[:, :bw].ravel(), gray[:, -bw:].ravel()])
    return float(np.median(ring))


def _search(gray, kernel, shape, min_area_frac, max_area_frac, masks):
    for values, cut in masks:
        mask = (values > cut).astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best = _pick(contours, shape, min_area_frac, max_area_frac)
        if best is not None:
            return best
    return None


def _brighter_than_the_car(gray, kernel, shape, min_area_frac, max_area_frac):
    """The original search: the screen is the bright thing in a dark cabin."""
    masks = []
    otsu, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    masks.append((gray, otsu))
    # All of them in one call, which is one sort rather than eight. Measured at
    # 1.13ms each against 1.3ms for the lot, and this runs every 0.4s on a Pi
    # while it is also trying to read.
    for cut in np.percentile(gray, BRIGHT_LEVELS):
        # Nothing left to separate: every remaining step would only crop the
        # same blob smaller.
        if float(cut) >= 254.0:
            break
        masks.append((gray, float(cut)))
    return _search(gray, kernel, shape, min_area_frac, max_area_frac, masks)


def _different_from_the_car(gray, kernel, shape, min_area_frac, max_area_frac):
    """The screen is whatever does not look like the cabin, either way up.

    A dark-mode offer card breaks the brightness premise outright, and not by
    being dim — by *straddling* the cabin. Measured on a rendered dark card, the
    map above the sheet sits at grey 44 and the sheet itself at 19, so with a
    car interior anywhere between them no single threshold can hold both halves
    of one screen. What the brightness ladder returns in that case is not
    nothing, which would at least be honest: it is the map, at the full width of
    the phone and 47% of its height, on every check, indefinitely. The crop is a
    fraction of the corners, so the reader is then handed a piece of the map and
    the card is never looked at.

    Distance from the cabin holds both halves, because neither of them looks
    like upholstery. It is a weaker assumption than the brightness one and true
    more often — but not always: it needs the frame's edge to actually *be*
    cabin, which stops being true on a very close mount, and it has nothing to
    measure against when the whole frame is blown-out windscreen. So it does not
    replace the brightness search. See _detect_quad for how the two are put
    together.
    """
    # absdiff against a constant image rather than a float subtract, so this
    # stays in uint8 and does it in one pass. Worth having but not worth much:
    # the cost of this search is the percentile (1.3ms) and the threshold and
    # contour rounds, not the subtraction. What the whole second search costs,
    # measured on the 640px thumbnail the loop uses, is 2.6ms against the
    # brightness search's 3.6ms, plus 0.4ms for the ink test when both find
    # something — about 3ms on top of a 9.6ms check, of which 6.3ms is the
    # resize that happens either way.
    diff = cv2.absdiff(gray, np.full_like(gray, int(round(_cabin_level(gray)))))
    masks = []
    seen = set()
    for cut in np.percentile(diff, DIFFERENCE_LEVELS):
        # A cut of zero is kept, not skipped. It looked like the degenerate case
        # — "nothing here differs from the cabin" — and it is the opposite: an
        # evenly-lit interior puts most of this image at exactly nought, so every
        # percentile below the phone's own share lands on zero, and `differs from
        # the cabin at all` is then precisely the right question to ask. Skipping
        # it threw away the only level that worked and left the search finding
        # the map again. If there really is nothing there, the mask comes out
        # empty and the search moves on by itself.
        key = round(float(cut), 3)
        if key in seen:
            continue
        seen.add(key)
        masks.append((diff, float(cut)))
    return _search(gray, kernel, shape, min_area_frac, max_area_frac, masks)


# How much of the smaller answer has to lie inside the bigger one before the two
# searches count as having found the same screen.
#
# Overlap rather than containment, which was the first thing tried and was too
# strict to be useful: on a dark card at a mid-grey cabin the brightness search
# returned a box 826 wide against the difference search's 762, because it bled a
# little into the upholstery either side. Same phone, 90% of one sitting inside
# the other, and neither containing it — so the test said "different things",
# the tie went to seniority, and the answer was the map again.
SAME_SCREEN_OVERLAP = 0.70


def _same_screen(a, b):
    """Do these two answers describe one screen, one of them clipped?"""
    ax, ay, aw, ah = cv2.boundingRect(a)
    bx, by, bw, bh = cv2.boundingRect(b)
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    smaller = min(aw * ah, bw * bh)
    return smaller > 0 and (ix * iy) / float(smaller) >= SAME_SCREEN_OVERLAP


# How much taller the second opinion has to be before it is worth considering.
#
# Not "taller at all", which was the first attempt and cost accuracy on every
# ordinary frame: the difference mask carries a small halo from the blur, so on
# a plainly-lit phone it returns a box about 1% bigger than the brightness
# search's — which is exact — and preferring it moved every detected corner a
# few pixels out.
MATERIALLY_TALLER = 1.15

# ...and how much of the disputed region has to be ink before it is believed.
#
# Height alone is not enough, and this is the case that proves it: a phone sits
# in a black case in a cradle, and the difference search does not find the
# screen at all — it finds the *phone*, body and all. Measured on a lit screen
# at 240x619 inside a case at 306x766, the brightness search returned the screen
# exactly and the difference search returned the case, 25% taller, which sailed
# past a height test and took over. Every crop fraction downstream is measured
# off those corners, so that is not a near miss, it is reading a rectangle a
# quarter of which is plastic.
#
# So the question is not "is the other answer bigger" but "is what it adds more
# screen?" — and a screen, dark mode or not, has writing on it while a phone
# case does not. Measured over the region one answer claims and the other does
# not, eroded away from the seam so the boundary between them is not what gets
# measured: a case scores 0.000 whatever colour it or the upholstery is, and a
# dark offer sheet scores 0.116 to 0.145. There is nothing in between to worry
# about, so this sits low enough to be safe from a card with little text on it
# and high enough that a highlight on glossy plastic cannot reach it.
INK_SHARE = 0.04
INK_ABOVE = 55          # levels above the disputed region's own background
INK_SEAM = 0.02         # how far to pull back from the boundary, as frame width


def _height(contour):
    return cv2.boundingRect(contour)[3]


def _writing_in_the_difference(gray, outer, inner):
    """How much of what `outer` adds to `inner` is ink rather than blank.

    Returns 0.0 when there is not enough of it to judge, which keeps the
    brightness answer — the conservative direction, since that is the one with a
    shift's worth of road behind it.
    """
    claimed = np.zeros(gray.shape[:2], np.uint8)
    cv2.drawContours(claimed, [outer], -1, 255, -1)
    held = np.zeros_like(claimed)
    cv2.drawContours(held, [inner], -1, 255, -1)
    extra = cv2.bitwise_and(claimed, cv2.bitwise_not(held))
    # The seam between two answers of the same thing is all boundary, and a
    # boundary has all the contrast in the picture across it. Without this the
    # case scored 75 levels of range and looked a lot like a card.
    e = max(3, (int(gray.shape[1] * INK_SEAM) | 1))
    extra = cv2.erode(extra, cv2.getStructuringElement(cv2.MORPH_RECT, (e, e)))
    pixels = gray[extra > 0]
    if pixels.size < 400:
        return 0.0
    background = float(np.median(pixels))
    return float(np.count_nonzero(pixels > background + INK_ABOVE)) / pixels.size


def _detect_quad(frame, min_area_frac, max_area_frac):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    gray = cv2.GaussianBlur(gray, (7, 7), 0)
    # The closing kernel is a fraction of the frame so it means the same thing
    # whether this ran on the sensor image or a thumbnail of it.
    k = max(3, (int(frame.shape[1] * 0.011) | 1))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
    shape = frame.shape

    lit = _brighter_than_the_car(gray, kernel, shape, min_area_frac, max_area_frac)
    other = _different_from_the_car(gray, kernel, shape, min_area_frac, max_area_frac)
    if lit is None and other is None:
        return None
    if lit is None or other is None:
        return _quad_of(lit if other is None else other)

    # Two answers about one screen, one of them clipped. The brightness search
    # keeps it unless the other is both materially taller AND what it adds has
    # writing on it — the second half being what tells a dark offer sheet, which
    # is more screen, from a phone case, which is not.
    #
    # When they do not overlap at all they are looking at different things, and
    # the brightness search wins on seniority: it is the one with a shift's worth
    # of road behind it, and the disagreement is rare enough not to guess at.
    if (_same_screen(lit, other)
            and _height(other) >= _height(lit) * MATERIALLY_TALLER
            and _writing_in_the_difference(gray, other, lit) >= INK_SHARE):
        return _quad_of(other)
    return _quad_of(lit)


# A screen this close to the frame edge is probably continuing past it.
EDGE_MARGIN = 0.012


def touches_edge(quad, shape, margin=EDGE_MARGIN):
    """Which frame edges the screen runs into. Empty when it fits.

    Worth knowing, but *not* worth refusing over, and the difference matters.

    A screen running off the frame used to be treated as a fault, on the
    grounds that everything downstream was measured against a screen that was
    not the whole screen — the crop landing somewhere arbitrary, the card
    height inflated, the warp the wrong shape. All true, and all of it was
    really one fault: the crop was a *fraction of the detected quad*, so it
    only meant anything if the quad was the whole screen.

    Backing off far enough to fix that is not free. A phone is about 2.15 times
    taller than it is wide and the frame is 4:3, so fitting all of it makes the
    width the constraint and drops the card to around 400px — the floor, from
    a mount that used to have 870. Clipping the map away is precisely what buys
    the resolution that makes the text readable.

    So the crop is placed from the measured geometry instead — see
    card_share_of_quad and centred_roi — which does not care how much of the
    screen is visible, and this is a note rather than a rule.
    """
    q = np.asarray(quad, dtype=np.float32).reshape(4, 2)
    h, w = shape[:2]
    mx, my = w * margin, h * margin
    hit = []
    if q[:, 1].min() <= my:
        hit.append('top')
    if q[:, 1].max() >= h - 1 - my:
        hit.append('bottom')
    if q[:, 0].min() <= mx:
        hit.append('left')
    if q[:, 0].max() >= w - 1 - mx:
        hit.append('right')
    return hit


# How much taller than wide a phone screen is. Used only to size a screen that
# runs off the frame, where its height cannot be measured directly. Modern
# phones are 18:9 through 20:9, so assume the shortest: guessing low makes a
# clipped mount read smaller than it is, and everything downstream would rather
# under-read the card than over-read it.
PHONE_ASPECT = 2.0


def screen_height_px(quad, shape=None):
    """How tall the whole phone screen is, in the units the quad is drawn in.

    The quad's own height, until the screen runs off the frame — at which point
    the quad stops at the frame edge and its height is the *frame's*, not the
    phone's. Then the only intact measurement left is across the screen, so the
    height comes from the width.
    """
    q = np.asarray(quad, dtype=np.float32).reshape(4, 2)
    down = (np.linalg.norm(q[3] - q[0]) + np.linalg.norm(q[2] - q[1])) / 2.0
    if shape is None or not touches_edge(q, shape):
        return float(down)
    across = (np.linalg.norm(q[1] - q[0]) + np.linalg.norm(q[2] - q[3])) / 2.0
    return float(max(down, across * PHONE_ASPECT))


def card_share_of_quad(quad, shape=None):
    """What fraction of the detected quad the offer card takes up.

    CARD_SHARE is the card's share of a whole *screen*. The quad is the whole
    screen only when the whole screen is in frame, and on the mount that
    actually works it is not — so anywhere the quad's own height is the thing
    being divided up, this is the number, not the constant.

    Getting this wrong does not look wrong, it just costs. A rig logged corners
    spanning 1690 rows of a 1748-row frame with the top of the phone off the
    edge: a quad that is 86% card, treated as 50% card. Every read warped the
    screen 1.7x taller than it needed to be — 2.6 megapixels where 0.9 would
    do — and since tesseract's cost is linear in pixels and there is a ceiling
    on what it will be handed (MAX_OCR_PIXELS), the picture was then shrunk
    back down again. Same text, three times the work, and on a narrow crop the
    shrinking took the payout below the size it can be read at, so the crop
    that was meant to be the fast one was the one that could not read.
    """
    q = np.asarray(quad, dtype=np.float32).reshape(4, 2)
    down = (np.linalg.norm(q[3] - q[0]) + np.linalg.norm(q[2] - q[1])) / 2.0
    if down <= 0:
        return CARD_SHARE
    share = screen_height_px(q, shape) * CARD_SHARE / down
    # Never below the whole-screen assumption: that is the unclipped answer and
    # the conservative one. Never above 1.0: the card cannot exceed the quad.
    return float(min(1.0, max(CARD_SHARE, share)))


def quad_window(image, quad, scale=(1.0, 1.0)):
    """The part of `image` the screen covers — its bounding box, clamped.

    A box rather than a warp because the callers that want this want it often
    and cheaply, and for measuring light a box is as good: the few corner
    pixels it picks up outside a slightly rotated screen are the same few every
    frame. `scale` divides quad coordinates into this image's, for callers
    working on the small preview stream rather than the capture.

    Returns the whole image, rather than nothing, when the box comes out empty.
    """
    q = np.asarray(quad, dtype=np.float32).reshape(4, 2)
    h, w = image.shape[:2]
    x0 = int(max(0, np.floor(q[:, 0].min() / scale[0])))
    x1 = int(min(w, np.ceil(q[:, 0].max() / scale[0])))
    y0 = int(max(0, np.floor(q[:, 1].min() / scale[1])))
    y1 = int(min(h, np.ceil(q[:, 1].max() / scale[1])))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return image
    return image[y0:y1, x0:x1]


def order_quad(pts):
    """Order corners as top-left, top-right, bottom-right, bottom-left."""
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)],
                     pts[np.argmax(s)], pts[np.argmax(d)]], dtype=np.float32)


def warp(frame, quad, height=CARD_HEIGHT):
    """Flatten the off-axis screen into a straight-on image of a fixed height."""
    quad = np.asarray(quad, dtype=np.float32)
    wa = np.linalg.norm(quad[1] - quad[0])
    wb = np.linalg.norm(quad[2] - quad[3])
    ha = np.linalg.norm(quad[3] - quad[0])
    hb = np.linalg.norm(quad[2] - quad[1])
    aspect = max(wa, wb) / max(max(ha, hb), 1.0)

    h = int(height)
    w = max(16, int(round(h * aspect)))
    dst = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=np.float32)
    return cv2.warpPerspective(frame, cv2.getPerspectiveTransform(quad, dst), (w, h))


def crop(image, roi):
    """Crop to a fractional (x, y, w, h) box, clamped to the image."""
    if not roi:
        return image
    h, w = image.shape[:2]
    x0 = max(0, min(w - 1, int(roi[0] * w)))
    y0 = max(0, min(h - 1, int(roi[1] * h)))
    x1 = max(x0 + 1, min(w, int((roi[0] + roi[2]) * w)))
    y1 = max(y0 + 1, min(h, int((roi[1] + roi[3]) * h)))
    return image[y0:y1, x0:x1]


def to_grey(card):
    return cv2.cvtColor(card, cv2.COLOR_BGR2GRAY) if card.ndim == 3 else card


# How far from the halfway point the background has to sit before a *change* of
# mind is allowed, as a share of the card's own range. Below this it is too
# close to call and the previous answer stands.
#
# Only reached by a picture that is genuinely half one thing and half the other,
# which an offer card is not: measured over 60 noisy frames each, all four cards
# in the corpus decided the same way every single time, dark and light. A
# contrived half-and-half image flipped 16 times in 60 — and a flip is not a
# small error, because the frames either side of one are compared. Two frames of
# the same still picture judged opposite ways score 200.7 on banding_score
# against 0.7 for two judged alike, where 4.0 already means "rippling". Exposure
# is chosen by ranking candidates on exactly that number, so one flip inside a
# candidate's three frames makes the right exposure look like the worst on offer
# and writes a different one to config.json for the rest of the shift.
POLARITY_MARGIN = 0.06


def is_dark_mode(gray, was=None):
    """True when this card is light text on a dark ground.

    Decided from the picture rather than from a setting, because the phone's own
    theme can follow the time of day and nobody is going to tell the rig.

    The card is mostly background, so the median IS the background — and the
    question is which end of the card's own range that background sits at. Doing
    it that way rather than against a fixed level is what makes it survive the
    camera: an absolute `median < 128` gets a badly underexposed *light* card
    wrong, and inverting a light card does not degrade the reading, it destroys
    it. Measured over twelve renderings — both themes, windscreen glare, gain
    pushed, exposure starved, half-cards — the relative test got 12 of 12 and
    `median < 128` got 11.

    `was` is the last answer, when there is one. Given it, a picture too close to
    call keeps that answer rather than changing its mind on sensor noise.
    """
    lo, hi = np.percentile(gray, (5, 95))
    middle = (float(lo) + float(hi)) / 2.0
    background = float(np.median(gray))
    if was is not None and abs(background - middle) < POLARITY_MARGIN * max(1.0, float(hi - lo)):
        return was
    return background < middle


def preprocess(card, dark=None):
    """Grey, put the ink dark side up, even out the glare, stretch contrast.

    CLAHE rather than a global stretch because a windshield puts a bright band
    across part of the screen and leaves the rest dim.

    The inversion is what makes a dark-mode card readable at all. Tesseract is
    run with tessedit_do_invert=0 — see OCR_CONFIG — which switches off its own
    white-on-black retry, and that was a sound trade for as long as this handed
    it dark text on a light card every single time. A phone in dark mode breaks
    that premise silently: measured on a rendered card the reader returned
    'Ee y Piece ek te | So | - - ee ee ne ee oo' and the offer was simply never
    seen. Letting tesseract do the flip instead costs a whole second pass over
    every dark page (255ms against 359ms measured); deciding it here costs a
    median and two percentiles, and leaves the light path exactly as it was.

    `dark` settles the question for callers that compare one prepared card with
    another — the health line's banding number, and calibration's choice of
    exposure. Both of those subtract consecutive frames, so both need every
    frame in a batch turned the same way up whatever each one would have decided
    on its own.
    """
    gray = to_grey(card)
    if dark is None:
        dark = is_dark_mode(gray)
    if dark:
        gray = cv2.bitwise_not(gray)
    return cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(gray)


# Ceiling on the image handed to the reader, for pictures that are outsized in
# both directions — a wide quad warped too tall. Height alone does not bound
# pixels, and an image nobody asked for is work nobody wanted.
#
# How much it is worth is smaller than it looks, and worth writing down so the
# next person does not spend the read budget here. "Tesseract's cost is linear
# in pixels" is folklore; measured on a real card it is nothing like linear —
# 1.83MP against 0.76MP is four times the pixels for 26% more time, because the
# cost is the recogniser walking the text rather than the image. Trimming to
# this budget also scales text down, and a card trimmed from 900px to 650px
# still read correctly, so neither side of the trade is large. It stays because
# an image nobody asked for is work nobody wanted, not because it is a lever.
MAX_OCR_PIXELS = 1_000_000


def fit_for_ocr(card, height=OCR_CARD_HEIGHT, max_pixels=MAX_OCR_PIXELS):
    """Scale a card to the size tesseract reads best, within a pixel budget."""
    if height and card.shape[0] < height:
        card = resize_height(card, height)
    pixels = card.shape[0] * card.shape[1]
    if max_pixels and pixels > max_pixels:
        card = resize_height(card, int(card.shape[0] * (max_pixels / float(pixels)) ** 0.5))
    return card


def write_jpeg(path, image, quality=80):
    """Write an image where a web server may be reading it at any moment.

    Encoded to bytes first, then renamed into place. Writing straight to a
    temporary name does not work: OpenCV chooses its encoder from the file
    extension, so a ".tmp" suffix has no writer at all. Encoding by format and
    renaming plain bytes keeps the swap atomic — half a JPEG is worse than a
    slightly old one.

    Returns None on success or the error text, because this runs on a timer and
    a caller that cannot show the picture should say so rather than die.
    """
    try:
        ok, buf = cv2.imencode('.jpg', image, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
        if not ok:
            return 'jpeg encoding failed'
        tmp = path + '.part'
        with open(tmp, 'wb') as fh:
            fh.write(buf.tobytes())
        os.replace(tmp, path)
        return None
    except Exception as e:
        return str(e)


def resize_height(image, height):
    """Resize to an exact height, either direction, keeping the aspect."""
    height = int(height)
    if height <= 0 or image.shape[0] == height:
        return image
    scale = height / float(image.shape[0])
    return cv2.resize(image, (max(1, int(round(image.shape[1] * scale))), height),
                      interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA)


def screen_view(frame, quad, height):
    """The phone's screen, flattened, filling the picture.

    `snapshot` below answers "is it looking at the right thing?" and is built
    for that: the whole scene, shrunk hard, with the corners drawn on. That is
    the right picture for aiming a camera and the wrong one for *reading* the
    phone through it, which is what the rig's own display is used for when the
    driver is working the phone with a bluetooth mouse rather than a thumb.
    Most of a scene view is car interior, and the part that is not is a couple
    of hundred pixels of phone.

    This is the same warp the reader uses — straight on, at a fixed height —
    without the OCR preprocessing, which is contrast-stretched, thresholded and
    sometimes inverted, and is a picture of a page rather than a picture of a
    screen. Colour where the frame has colour, because "which button is blue"
    is a thing a person reads off a phone and a reader never does.

    Not cropped to the reading box either. The box is deliberately the part of
    the screen a *price* lives in; the Accept button is outside it on every card
    shape here, and a view you cannot see the button in is not one you can drive
    the phone from.

    Returns None when there is nothing to flatten, so the caller can fall back
    to the scene rather than publish a stretched picture of the wrong corners.
    """
    if quad is None or height <= 0:
        return None
    quad = np.asarray(quad, dtype=np.float32)
    if quad.shape != (4, 2) or not np.all(np.isfinite(quad)):
        return None
    h, w = frame.shape[:2]
    # Corners that have wandered off the frame warp to a picture of the black
    # outside it. The tracker can produce those between a phone being moved and
    # the recovery noticing, and they are exactly when somebody is looking.
    if quad[:, 0].max() < 0 or quad[:, 1].max() < 0:
        return None
    if quad[:, 0].min() > w or quad[:, 1].min() > h:
        return None
    view = warp(frame, quad, height)
    if view.ndim == 2:
        view = cv2.cvtColor(view, cv2.COLOR_GRAY2BGR)
    return view


def snapshot(frame, quad, roi, card_height=CARD_HEIGHT, width=640, card=None,
             warp_card=True):
    """One image that answers "is it looking at the right thing?".

    The whole frame with the calibrated corners drawn on it, and inset, the
    exact card image handed to the OCR engine. Aim problems show up in the
    first; focus and glare problems show up in the second.

    This runs several times a second on a small computer that is also trying to
    read, so it does the least it can: it shrinks first and draws on the small
    picture, rather than copying and drawing over a 12MB frame to throw 97% of
    it away, and it will take a card image the reader has already made rather
    than warping a second one. Pass `card` whenever a read just produced one —
    the picture is more honest that way as well, since it is then literally
    what the reader saw and not a re-creation of it.
    """
    scale = width / float(frame.shape[1])
    # resize returns a new array, so this is also the copy. Linear rather than
    # area: over a 4-megapixel frame that is the difference between 6ms and
    # 0.4ms, which at several frames a second is most of what the preview
    # costs, and the aliasing it trades away lands on a 640px thumbnail of a
    # car interior. The one part of this picture anybody reads detail from is
    # the inset, which is the reader's own image and is not resampled here.
    view = cv2.resize(frame, (width, max(1, int(frame.shape[0] * scale))),
                      interpolation=cv2.INTER_LINEAR)
    if quad is not None:
        q = (np.asarray(quad, dtype=np.float32) * scale).astype(np.int32)
        cv2.polylines(view, [q], True, (100, 201, 23), 2)

    if quad is not None:
        if card is None:
            # `warp_card` is False when the frame handed here is the preview
            # stream rather than the sensor. Warping that would produce an inset
            # at a fraction of the reader's resolution, and the inset is the one
            # part of this picture a person reads detail from — a soft one looks
            # exactly like a focus problem, so the honest thing is no inset at
            # all until a real read has made one.
            if not warp_card:
                return view
            card = preprocess(crop(warp(frame, quad, card_height), roi))
        if card.ndim == 2:
            card = cv2.cvtColor(card, cv2.COLOR_GRAY2BGR)
        # Inset it at a third of the width, bottom-right, inside a border so it
        # reads as a separate picture rather than part of the scene.
        cw = width // 3
        ch = max(1, int(card.shape[0] * (cw / float(card.shape[1]))))
        ch = min(ch, view.shape[0] - 20)
        cw = max(1, int(card.shape[1] * (ch / float(card.shape[0]))))
        card = cv2.resize(card, (cw, ch), interpolation=cv2.INTER_AREA)
        x0, y0 = view.shape[1] - cw - 8, view.shape[0] - ch - 8
        if x0 > 0 and y0 > 0:
            view[y0:y0 + ch, x0:x0 + cw] = card
            cv2.rectangle(view, (x0 - 2, y0 - 2), (x0 + cw + 1, y0 + ch + 1), (255, 255, 255), 2)
    return view


# A RAM-backed file handed to tesseract instead of the image itself.
#
# pytesseract's array path routes the picture through PIL, whose PNG encoder
# measured 93ms — well over a third of a whole read, spent compressing an image
# that tesseract is about to decompress again. An uncompressed PGM of the same
# picture encodes in 0.1ms and tesseract reads it just as happily: 262ms a read
# becomes 157ms, for no change in what comes back.
#
# /dev/shm when it exists, so this never touches the SD card. One file per
# reading *thread*, reused.
#
# Per thread rather than per process because two reads of the same card can now
# run at once (Scanner.read_many). A single shared path would have had them
# overwriting each other's image between the write and tesseract opening it —
# a race that produces a plausible reading of the wrong frame, which is the
# worst failure this code has.
_SCRATCH = {}
_SCRATCH_LOCK = threading.Lock()


def _clear_scratch():
    """/dev/shm is RAM. Leaving a megabyte of it behind per run is rude."""
    for path in list(_SCRATCH.values()):
        try:
            os.remove(path)
        except OSError:
            pass


def stage_for_ocr(image):
    """Put an image where tesseract can read it cheaply. Returns a path.

    Falls back to handing over the array — slow but correct — if the scratch
    file cannot be written, since a working slow read beats a broken fast one.
    """
    key = threading.get_ident()
    path = _SCRATCH.get(key)
    if path is None:
        base = '/dev/shm' if os.path.isdir('/dev/shm') and os.access('/dev/shm', os.W_OK) \
            else tempfile.gettempdir()
        path = os.path.join(base, 'uberscan-ocr-%d-%d.pgm' % (os.getpid(), key))
        with _SCRATCH_LOCK:
            if not _SCRATCH:
                atexit.register(_clear_scratch)
            _SCRATCH[key] = path
    # PGM is greyscale only, which everything here already is by this point.
    if image.ndim == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    try:
        if cv2.imwrite(path, image):
            return path
    except Exception:
        pass
    return image


# --- the engine, kept alive ------------------------------------------------
#
# Every read used to spawn a `tesseract` process, and a fresh process re-loads
# and unpacks the LSTM model before it looks at a single pixel. Measured here:
# 81.8ms of a 129.1ms read, or **63% of it**, spent starting up — and paid again
# on every one of the four (median) to fourteen (worst) reads that get merged
# into one stored offer. The module note at the top of this file says the wins
# are in not running tesseract rather than in shaving pixels off a picture it
# was going to read anyway. True, and it missed that most of each run was not
# reading anything.
#
# So the engine is initialised once and kept. Same library the binary is a
# wrapper around — libtesseract.so.5 is already on the box as its dependency, so
# nothing new is installed — same traineddata, same OEM, same variables, and the
# TSV it returns is byte-identical to the binary's, header line aside. Measured
# on the same card: **124.8ms to 37.2ms**.
#
# One engine per thread, because look_many runs two reads at once and a
# TessBaseAPI is not shareable. Each holds its own copy of the model, which is
# the cost of this: memory for time.
#
# Everything here is allowed to fail. A missing library, a missing symbol, an
# init that returns non-zero, an exception mid-read — any of them and this hands
# the read back to the binary, permanently, and says so once. A rig that reads
# slowly is working; a rig that does not read is not. `UBERSCAN_TESSERACT=binary`
# is the way back without a code change, in the same spirit as --no-thread.
#
# GetTSVText is reached by its C++ symbol because the C wrapper does not export
# it. That is the one brittle thing in here, so it is looked up at init and its
# absence is simply another reason to use the binary.
_TSV_SYMBOL = '_ZN9tesseract11TessBaseAPI10GetTSVTextEi'

_TESS_LIB = None                 # None: not tried. False: not usable.
_TESS_LOCK = threading.Lock()
_TESS_LOCAL = threading.local()
_TESS_OPEN = []                  # every engine built, so they can be closed
_TESS_SAID = False


def _tess_off(why):
    """Give up on the library, once, out loud."""
    global _TESS_LIB, _TESS_SAID
    _TESS_LIB = False
    if not _TESS_SAID:
        _TESS_SAID = True
        print('reading with the tesseract binary instead of the library: %s' % why)


def _tess_lib():
    """The shared library, bound, or False."""
    global _TESS_LIB
    if _TESS_LIB is not None:
        return _TESS_LIB
    with _TESS_LOCK:
        if _TESS_LIB is not None:
            return _TESS_LIB
        if os.environ.get('UBERSCAN_TESSERACT', '').lower() == 'binary':
            _tess_off('asked for by UBERSCAN_TESSERACT')
            return False
        try:
            lib = ctypes.CDLL('libtesseract.so.5')
            lib.TessBaseAPICreate.restype = ctypes.c_void_p
            lib.TessBaseAPIInit2.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                             ctypes.c_char_p, ctypes.c_int]
            lib.TessBaseAPIInit2.restype = ctypes.c_int
            lib.TessBaseAPISetVariable.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                                   ctypes.c_char_p]
            lib.TessBaseAPISetVariable.restype = ctypes.c_bool
            lib.TessBaseAPISetPageSegMode.argtypes = [ctypes.c_void_p, ctypes.c_int]
            lib.TessBaseAPISetImage.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                                ctypes.c_int, ctypes.c_int,
                                                ctypes.c_int, ctypes.c_int]
            lib.TessBaseAPIGetUTF8Text.argtypes = [ctypes.c_void_p]
            lib.TessBaseAPIGetUTF8Text.restype = ctypes.c_void_p
            lib.TessBaseAPIEnd.argtypes = [ctypes.c_void_p]
            lib.TessBaseAPIDelete.argtypes = [ctypes.c_void_p]
            lib.TessDeleteText.argtypes = [ctypes.c_void_p]
            tsv = getattr(lib, _TSV_SYMBOL)
            tsv.argtypes = [ctypes.c_void_p, ctypes.c_int]
            tsv.restype = ctypes.c_void_p
            lib.uberscan_tsv = tsv
            _TESS_LIB = lib
        except Exception as e:
            _tess_off(str(e))
    return _TESS_LIB


def _tess_config(config):
    """(oem, psm, variables) out of a tesseract command line, or None.

    None means "not a command line this understands", and the caller falls back
    to the binary rather than guessing at it. Every flag has to be recognised:
    silently dropping one would read the card under settings nobody asked for,
    which is the sort of difference that shows up as a wrong number.
    """
    oem, psm, variables = 3, 3, []
    parts = shlex.split(config or '')
    i = 0
    while i < len(parts):
        flag = parts[i]
        nxt = parts[i + 1] if i + 1 < len(parts) else None
        try:
            if flag == '--oem' and nxt is not None:
                oem = int(nxt)
            elif flag == '--psm' and nxt is not None:
                psm = int(nxt)
            elif flag == '-c' and nxt is not None and '=' in nxt:
                key, value = nxt.split('=', 1)
                variables.append((key, value))
            else:
                return None
        except ValueError:
            return None
        i += 2
    return oem, psm, tuple(variables)


class _Tesseract:
    """One initialised engine, on one thread."""

    def __init__(self, lib, oem, variables):
        self.lib = lib
        self.api = ctypes.c_void_p(lib.TessBaseAPICreate())
        if not self.api:
            raise RuntimeError('tesseract would not start')
        if lib.TessBaseAPIInit2(self.api, None, b'eng', int(oem)) != 0:
            lib.TessBaseAPIDelete(self.api)
            self.api = None
            raise RuntimeError('tesseract would not load eng')
        # Tesseract narrates to stderr — "Estimating resolution as 146" on every
        # read, and more when a page confuses it. Run as a subprocess that went
        # to a pipe pytesseract threw away; run in this process it goes to the
        # rig's own log, several lines a second while a card is up, in the file
        # a driver pastes back. Sending it to the same place the binary's copy
        # went is not losing anything. Set before the caller's own variables, so
        # a caller that wants it back can ask.
        lib.TessBaseAPISetVariable(self.api, b'debug_file', b'/dev/null')
        for key, value in variables:
            lib.TessBaseAPISetVariable(self.api, key.encode(), str(value).encode())
        _TESS_OPEN.append(self)

    def read(self, image, psm, tsv):
        # Greyscale and contiguous, which is what SetImage is being told it is.
        # A picture that is neither would be read as noise rather than refused.
        if image.ndim == 3:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        buf = np.ascontiguousarray(image, dtype=np.uint8)
        height, width = buf.shape[:2]
        self.lib.TessBaseAPISetPageSegMode(self.api, int(psm))
        self.lib.TessBaseAPISetImage(self.api, buf.ctypes.data,
                                     width, height, 1, width)
        got = (self.lib.uberscan_tsv(self.api, 0) if tsv
               else self.lib.TessBaseAPIGetUTF8Text(self.api))
        if not got:
            return ''
        try:
            return ctypes.string_at(got).decode('utf-8', 'replace')
        finally:
            self.lib.TessDeleteText(ctypes.c_void_p(got))

    def close(self):
        if self.api:
            # Ended as well as deleted: without it tesseract prints a wall of
            # "LEAK! object still has count 1" at exit, which is the last thing
            # in the log a driver would paste back.
            self.lib.TessBaseAPIEnd(self.api)
            self.lib.TessBaseAPIDelete(self.api)
            self.api = None


# Two, because a paired read is two frames and OMP_THREAD_LIMIT pins each engine
# to one core — two at once on a four-core Pi leaves the camera loop the other
# two. A larger batch is not refused, it queues, which is the right answer
# rather than a wider fan-out onto cores that are already busy.
_READ_WORKERS = 2
_READ_POOL = None
_READ_POOL_LOCK = threading.Lock()


def _read_pool():
    global _READ_POOL
    if _READ_POOL is None:
        with _READ_POOL_LOCK:
            if _READ_POOL is None:
                _READ_POOL = futures.ThreadPoolExecutor(
                    max_workers=_READ_WORKERS, thread_name_prefix='ocr')
    return _READ_POOL


# A ceiling on engines, whatever the threading above does.
#
# Each holds its own copy of the model — 11.7MB for the first, 14.2MB for the
# second — so a caller that reads from a fresh thread every time would eat the
# Pi. The pool above is the fix; this is the backstop, because the failure it
# guards against is a rig running out of memory mid-shift and the cost of being
# wrong about it is one slow read.
MAX_ENGINES = 4


def _close_engines():
    for engine in list(_TESS_OPEN):
        try:
            engine.close()
        except Exception:
            pass
    del _TESS_OPEN[:]


atexit.register(_close_engines)


def _in_process(image, config, tsv):
    """Read with the kept engine. None means "use the binary"."""
    lib = _tess_lib()
    if not lib:
        return None
    parsed = _tess_config(config)
    if parsed is None:
        return None
    oem, psm, variables = parsed
    key = (oem, variables)
    engines = getattr(_TESS_LOCAL, 'engines', None)
    if engines is None:
        engines = _TESS_LOCAL.engines = {}
    engine = engines.get(key)
    try:
        if engine is None:
            if len(_TESS_OPEN) >= MAX_ENGINES:
                return None
            engine = engines[key] = _Tesseract(lib, oem, variables)
        return engine.read(image, psm, tsv)
    except Exception as e:
        # This one is dead; the next read builds a fresh one. Twice in a row and
        # the library is the problem rather than the engine.
        engines.pop(key, None)
        if engine is not None:
            try:
                engine.close()
                _TESS_OPEN.remove(engine)
            except Exception:
                pass
            _tess_off(str(e))
        return None


def ocr(image, config=OCR_CONFIG):
    out = _in_process(image, config, tsv=False)
    if out is not None:
        return out
    return pytesseract.image_to_string(stage_for_ocr(image), config=config)


def tsv_rows(image, config=OCR_CONFIG):
    """Tesseract's per-word table for this image, without the header line.

    The library returns the rows alone and the binary writes a header above
    them; the difference is dealt with here rather than by every caller.
    """
    out = _in_process(image, config, tsv=True)
    if out is not None:
        return out.splitlines()
    return pytesseract.image_to_data(stage_for_ocr(image),
                                     config=config).splitlines()[1:]


def ocr_lines(image, config=OCR_CONFIG):
    """OCR that also says where each line was. Returns (text, lines).

    Same engine and the same one pass as ocr(), just asked for its layout as
    well, so this costs nothing extra. The boxes are what let a crop that has
    slid off the card find its way back on.
    """
    rows = [r.split('\t') for r in tsv_rows(image, config)]
    grouped = {}
    order = []
    for r in rows:
        if len(r) < 12:
            continue
        try:
            key = (int(r[2]), int(r[3]), int(r[4]))       # block, paragraph, line
            left, top, width, height = (int(r[6]), int(r[7]), int(r[8]), int(r[9]))
            conf = float(r[10])
        except ValueError:
            continue
        word = r[11].strip()
        # -1 marks a box with no text in it; an empty word carries no position.
        if not word or conf < 0:
            continue
        if key not in grouped:
            grouped[key] = {'top': top, 'bottom': top + height,
                            'left': left, 'right': left + width, 'words': []}
            order.append(key)
        line = grouped[key]
        line['top'] = min(line['top'], top)
        line['bottom'] = max(line['bottom'], top + height)
        line['left'] = min(line['left'], left)
        line['right'] = max(line['right'], left + width)
        line['words'].append(word)

    lines = []
    for key in order:
        line = grouped[key]
        line['text'] = ' '.join(line['words'])
        del line['words']
        lines.append(line)
    return '\n'.join(l['text'] for l in lines), lines


# The crop, and why it is not learned any more.
#
# It used to find itself: fit the box to wherever the payout and the lines
# under it landed, widen when reads failed, tighten when they worked, with
# agreement counting and settling times to keep it honest. It was careful and
# it still could not converge, because it was chasing something that genuinely
# moves. A rig logged **sixteen crop moves in eighteen minutes** — 0.70, 0.45,
# 0.70, 0.54, 0.74, 0.54, 0.71, 0.82, 0.92, 0.66, 0.46, 0.80 — never settling,
# and spending the gaps reading whichever slice the last move had chosen.
#
# Nothing was wrong with the fitting. An UberX card and a Shop & Deliver card
# are different heights; a two-leg card is taller than a one-leg card. Every
# one of those moves was a correct fit to the card in front of it, and the next
# card wanted a different box. A crop learned from the last offer is always the
# wrong shape for the next one.
#
# So it is derived instead. Two things are known without learning anything:
# how much of the quad is card (card_share_of_quad, measured per read), and
# that the card is aimed at the middle of the frame. That is enough to place a
# box, it costs nothing, it cannot drift, and it is right for the *current*
# card rather than the last one.
#
# Slack on top of the card's own height, to cover the card not being perfectly
# centred and card_share erring low by design (it assumes the shortest phone
# there is). A fifth of the screen is about a centimetre of aim.
CROP_SLACK = 0.20


def centred_roi(card_share, slack=CROP_SLACK):
    """The box to read, given how much of the quad the card takes up.

    Centred, because that is where the card is put. Never taller than the quad
    and never so tall that it is not a crop at all — on a mount close enough
    that the visible screen is nearly all card, the honest answer is to read
    all of it, and this returns that.
    """
    height = min(1.0, float(card_share) + slack)
    return [0.0, (1.0 - height) / 2.0, 1.0, height]


# A payout this close to the top edge of the crop, as a fraction of the crop's
# height, is not trusted to be whole.
TOP_EDGE = 0.02


def money_is_clipped(lines, image_height):
    """True when the payout sits flush against the top of the crop.

    This is the failure that costs money rather than time. A crop that has slid
    down over the card cuts the payout off at the eyes, and half a line of
    digits still reads as digits — a "4.95" rating with its top shaved became a
    $45.00 offer in testing, which is a confident ACCEPT on a $7 job. There is
    no sign of trouble in the text itself, so the only evidence is geometric: a
    card read from the right place has its service badge above the payout, never
    the payout hard against the edge.
    """
    if not lines or not image_height:
        return False
    money = [l for l in lines if OP.find_pay(OP.normalize(l['text'])) is not None]
    if not money:
        return False
    return min(l['top'] for l in money) <= TOP_EDGE * image_height


# Ceiling on the warp used for a read. Without one, a crop that has re-fitted
# itself thin asks for a proportionally taller screen — a 0.18-high crop wants
# 5000px, which is a 40MB warp and an OCR pass to match. That is the difference
# between a scanner that stutters and one that stops.
MAX_READ_HEIGHT = 2200


class Geometry:
    """The corners and the crop one read is taken against, frozen.

    The read runs on a thread of its own now, while the loop that holds the
    camera keeps going — and that loop moves the corners. The tracker eases
    them 35% toward a candidate every 0.4s, a re-lock replaces them outright,
    and a box drawn on the live view replaces the crop as well. Reading
    `scanner.quad` from inside the read would mean warping a frame captured at
    one moment against corners measured at another, which is the one thing a
    homography must never do: the crop lands somewhere the card is not, and
    that reads exactly like no offer being on screen.

    So the geometry is taken once, at the moment the frame is handed over, and
    a read becomes a pure function of (frame, geometry). The two fields a read
    *measures* — the card's share of the quad, and which way up the ink is —
    are written here rather than on the Scanner, and folded back by whoever
    collects the result. One writer, on the thread that owns the loop.
    """

    __slots__ = ('quad', 'roi', 'fixed_card_share', 'card_share',
                 'card_height', 'ocr_height', 'dark_mode')

    def __init__(self, quad=None, roi=None, fixed_card_share=None,
                 card_share=CARD_SHARE, card_height=CARD_HEIGHT,
                 ocr_height=OCR_CARD_HEIGHT, dark_mode=None):
        self.quad = quad
        self.roi = roi
        self.fixed_card_share = fixed_card_share
        self.card_share = card_share
        self.card_height = card_height
        self.ocr_height = ocr_height
        self.dark_mode = dark_mode

    @property
    def crop_box(self):
        return self.roi if self.roi else centred_roi(self.card_share)

    @property
    def read_height(self):
        if not self.ocr_height:
            return self.card_height
        return int(min(max(self.card_height, round(self.ocr_height / self.card_share)),
                       MAX_READ_HEIGHT))


class Scanner:
    """Holds the motion gate and the agreement counter across frames."""

    def __init__(self, quad=None, settings=None, agree_to_lock=2,
                 card_height=CARD_HEIGHT, config=OCR_CONFIG, roi=None,
                 ocr_height=OCR_CARD_HEIGHT, card_share=None):
        self.quad = None if quad is None else np.asarray(quad, dtype=np.float32)
        # A fixed override for the crop, as fractional (x, y, w, h) of the
        # warped screen. Left None — which is the normal case — the crop is
        # derived per read from the measured geometry, which is what stops it
        # wandering. See centred_roi.
        self.roi = roi
        # And an override for what the quad *is*. Measured per read normally,
        # because the quad is a phone screen and the card is half of one — but
        # a box someone drew by hand around the card is all card, and measuring
        # it as half a screen warps it twice as tall as the reader can use,
        # only to shrink it back down again against MAX_OCR_PIXELS. Same text,
        # three times the work, and smaller by the time it is read.
        self.fixed_card_share = card_share
        self.settings = settings or {}
        self.agree_to_lock = agree_to_lock
        self.card_height = card_height
        self.ocr_height = ocr_height
        self.config = config

        # The card's share of the quad, which is CARD_SHARE only while the
        # whole screen is in frame. Measured from the first frame that arrives,
        # because it takes the frame's shape to know whether the quad is the
        # whole screen or just the part of it that fitted.
        self.card_share = CARD_SHARE if card_share is None else float(card_share)

        # Which way up the ink was last time, so the answer is steady across
        # reads. None until the first card has been looked at.
        self.dark_mode = None
        self._prev = None
        self._dirty = True      # first frame always reads
        self.last_diff = 0.0    # how much the picture moved, for callers that care
        self._sig = None
        self._agree = 0
        self.dropped = 0
        # Reads where the payout was only found on the second look. Worth a
        # counter: if this climbs on a rig, the mount is producing the exact
        # shape of frame the default segmentation mishandles.
        self.recovered = 0
        self.locked = False
        self.last = None

    def geometry(self):
        """A frozen copy of everything a read is taken against. See Geometry."""
        return Geometry(quad=self.quad, roi=self.roi,
                        fixed_card_share=self.fixed_card_share,
                        card_share=self.card_share,
                        card_height=self.card_height,
                        ocr_height=self.ocr_height,
                        dark_mode=self.dark_mode)

    @property
    def crop_box(self):
        """The box to read this frame, derived rather than remembered.

        Nothing here carries over from the last read. That is the point: a crop
        learned from the last offer is the wrong shape for the next one, since
        an UberX card and a Shop & Deliver card are different heights and a
        two-leg card is taller than a one-leg card. Deriving it costs nothing
        and is right for the card actually in front of the camera.
        """
        return self.roi if self.roi else centred_roi(self.card_share)

    @property
    def read_height(self):
        """Warp height for a read, as opposed to for a picture of the screen.

        The crop is going to be scaled up to the reader's size anyway, so warp
        the screen tall enough that it arrives there directly: same pixels, one
        resampling instead of shrinking and stretching back.

        Crucially this is derived from how much of a screen a card *is*, not
        from how much of the screen the crop keeps. Those look interchangeable
        and are not. Text size in the finished image depends only on this
        height, so deriving it from the crop ties the two together backwards:
        widening the crop to stop clipping the payout would shrink the warp,
        and the text would come out smaller than before — the crop would keep
        more of the card and read less of it.

        What it *is* derived from is the card's share of this quad, measured
        (self.card_share), not the whole-screen constant. On a mount close
        enough to clip the map away the quad is most of the way to being the
        card already, and warping as though it were half a screen makes a
        picture nearly twice as tall as the reader can use.
        """
        if not self.ocr_height:
            return self.card_height
        return int(min(max(self.card_height, round(self.ocr_height / self.card_share)),
                       MAX_READ_HEIGHT))

    def _motion(self, frame):
        small = cv2.cvtColor(cv2.resize(frame, MOTION_SIZE, interpolation=cv2.INTER_AREA),
                             cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else \
                cv2.resize(frame, MOTION_SIZE, interpolation=cv2.INTER_AREA)
        if self._prev is None:
            self._prev = small
            return CHANGE_T + 1
        diff = float(np.mean(cv2.absdiff(small, self._prev)))
        self._prev = small
        return diff

    @property
    def settled(self):
        """True when the picture is holding still enough to measure anything."""
        return self.last_diff <= STILL_T

    def should_read(self, frame):
        """True when the picture just changed and has since settled."""
        diff = self.last_diff = self._motion(frame)
        if diff > CHANGE_T:
            self._dirty = True
            return False        # still moving; reading now would blur
        if self._dirty and diff <= STILL_T:
            self._dirty = False
            return True
        return False

    def read(self, frame, now=None):
        """Full read of one frame, ignoring the motion gate."""
        geom = self.geometry()
        return self.settle([self._look(frame, now, geom)], geom)[0]

    def read_many(self, frames, now=None):
        """Read several frames of the same card at once. Returns one per frame.

        A verdict needs two reads that agree, and agreement is the only thing
        standing between the driver and a confidently wrong number: over
        rippling, soft, glared and dim frames, one read claiming a whole offer
        was wrong 1 time in 36, and two agreeing were wrong none. So the
        confirmation stays — it just stops being a second helping of wall clock.

        Tesseract releases the interpreter while it runs, and a Pi 4 has four
        cores that the loop was using one of. Two reads at once measured 55% of
        the cost of two in a row, which halves the time to a verdict without
        weakening the evidence by anything at all.

        The catch is that OpenMP must be pinned to one thread per instance, or
        two of them fight over all four cores: unpinned, the same pair took
        **46 seconds** against 435ms sequential. scan_pi sets it; this says so
        rather than assuming, because a hundredfold regression is not something
        to leave to an environment variable nobody mentions.

        Only the reading is concurrent. The agreement counter is applied here,
        in frame order, because "two reads said the same thing" has to mean the
        same thing every run.
        """
        geom = self.geometry()
        return self.settle(self.look_many(frames, now, geom), geom)

    def look_many(self, frames, now=None, geom=None):
        """The reading half, with nothing in it that another thread owns.

        Safe to call off the loop that holds the camera, which is the point:
        an OCR pass is 1.4s of a Pi 4 and the live view is frozen for every
        one of them if the loop waits for it. Pass the geometry captured with
        the frames — see Geometry — and hand the result to settle() on the
        thread that owns the Scanner.
        """
        frames = list(frames)
        geom = self.geometry() if geom is None else geom
        if len(frames) == 1:
            return [self._look(frames[0], now, geom)]
        # The pool outlives the call. It used to be built per read and shut down
        # at the end of it, which was free when a read spawned a process and is
        # not now: the engine belongs to the thread, so a fresh pair of threads
        # per read meant a fresh pair of engines per read — 12 of them after six
        # paired reads, RSS 151MB to 286MB, and climbing for as long as the
        # shift lasted. Reusing the threads is what makes keeping the engine
        # mean anything.
        return list(_read_pool().map(lambda f: self._look(f, now, geom), frames))

    def settle(self, outs, geom=None):
        """Fold a batch of readings back into what the Scanner believes.

        In frame order, on one thread, because "two reads said the same thing"
        has to mean the same thing every run.
        """
        for out in outs:
            self._consider(out['parsed'])
            # After, not during: _look runs before the agreement counter is
            # updated, so the copy it took is the state as of the *previous*
            # read. Reporting that would have said "not locked yet" on the very
            # read that locked, which is the read the spoken verdict waits for.
            out['locked'] = self.locked
            self.dropped += out['dropped']
            self.recovered += out['recovered']
        # The two things a read measures rather than is given, brought back to
        # where the next read will look for them. (The counters above are per
        # read and added up here for the same reason: two frames read at once
        # can lose an increment between them, which `self.dropped += 1` inside
        # the pool quietly could.)
        #
        # The card's share is accepted unless somebody *set* it while the read
        # was running. A read takes over a second, and in that second the driver
        # can draw a box on the live view or press re-find — both of which pin
        # the crop and the share deliberately. Folding a measurement taken
        # against the old crop over the top of that would undo half of what the
        # button did, and leave the crop somewhere neither the driver nor the
        # code asked for.
        #
        # Deliberately not tested against the quad. The tracker allocates fresh
        # corners on every ease, so an identity check there would refuse the
        # measurement on almost every read while tracking is on — and a share
        # measured against corners a few pixels stale is a better estimate than
        # one measured a minute ago. The read itself is unaffected either way:
        # _look measures the share from the frame it was given before it sizes
        # anything, so a reading is always self-consistent.
        if geom is not None:
            if (geom.roi is self.roi
                    and geom.fixed_card_share == self.fixed_card_share):
                self.card_share = geom.card_share
            # Which way up the ink is has nothing to do with the corners: it is
            # a property of the screen, it is re-decided on every read with the
            # last answer only as a hint, and it is worth carrying across a
            # crop that moved.
            self.dark_mode = geom.dark_mode
        return outs

    def _look(self, frame, now=None, geom=None):
        """Everything a read does except change what the Scanner believes.

        Split out so several can run at once, and so the whole of it can run on
        a thread while the camera loop carries on. Nothing here touches state
        another reader could be touching: the geometry is a snapshot, and the
        two fields a read measures are written on that snapshot rather than on
        the Scanner. Both readers of a pair arrive at the same answer for them.
        """
        now = time.time() if now is None else now
        g = self.geometry() if geom is None else geom
        t0 = time.perf_counter()
        if g.quad is not None and g.fixed_card_share is None:
            # Before anything is sized, work out what this quad actually is. A
            # tracked quad moves and a re-locked one can change shape, so this
            # is re-measured per read rather than settled once at startup.
            g.card_share = card_share_of_quad(g.quad, frame.shape)
        screen = warp(frame, g.quad, g.read_height) if g.quad is not None else frame
        t1 = time.perf_counter()
        # Decided here rather than inside preprocess, and remembered, so two
        # consecutive reads of one still card cannot come back turned opposite
        # ways up — which is what the health line's banding number subtracts.
        fitted = to_grey(fit_for_ocr(crop(screen, g.crop_box), g.ocr_height))
        g.dark_mode = is_dark_mode(fitted, was=g.dark_mode)
        prepped = preprocess(fitted, dark=g.dark_mode)
        t2 = time.perf_counter()
        # Asked for its layout as well as its text, at no extra cost, because
        # where the payout landed is the only way to tell a crop that read
        # nothing from a crop that read half of something.
        text, lines = ocr_lines(prepped, self.config)
        parsed = OP.parse(text)

        # A journey but no money is the one failure worth paying to re-read.
        # It means the card was in front of the reader and legible — the times
        # and distances came back — and only the single field the whole rig
        # exists for went missing, which is what psm 6 does to a payout set much
        # larger than the text around it. Reading it again under RECOVER_CONFIG
        # costs about 200ms and only ever on a read that was otherwise going to
        # report nothing, so no working read pays for it.
        #
        # The retry has to win on its own merits: it is taken only if it finds a
        # payout AND still agrees about the journey. A second opinion that also
        # rewrites the minutes is not a recovered payout, it is a different
        # reading, and there is nothing here to say which of the two is right.
        recovered = 0
        if parsed['pay'] is None and parsed['minutes']:
            again, again_lines = ocr_lines(prepped, RECOVER_CONFIG)
            second = OP.parse(again)
            if (second['pay'] is not None
                    and second['minutes'] == parsed['minutes']
                    and second['miles'] == parsed['miles']):
                text, lines, parsed = again, again_lines, second
                recovered = 1
        t3 = time.perf_counter()

        # A payout hard against the cut edge is half a number, and half a
        # number still reads as a number: a "4.95" rating with its top shaved
        # became a $45.00 offer in testing. Nothing is re-fitted over it any
        # more — the crop is derived and has nowhere better to go — so the
        # answer is simply to report nothing. A missed offer costs one fare; a
        # phantom $45 one costs an hour driving it.
        clipped = money_is_clipped(lines, prepped.shape[0])
        if clipped:
            parsed = OP.parse('')

        rate = OP.rate(parsed, self.settings)
        t4 = time.perf_counter()

        return {
            'parsed': parsed,
            'rate': rate,
            'locked': self.locked,
            'text': text,
            # Why a read was unsatisfying, for whoever has to explain it later.
            'clipped': clipped,
            # Carried out rather than counted in place: settle() adds them up on
            # one thread. See there.
            'dropped': 1 if clipped else 0,
            'recovered': recovered,
            'crop': list(g.crop_box),
            # The exact picture the reader was given, so a caller can measure how
            # bright it was and whether it was rippling.
            'card': prepped,
            'ms': {
                'warp': (t1 - t0) * 1000,
                'prep': (t2 - t1) * 1000,
                'ocr': (t3 - t2) * 1000,
                'parse': (t4 - t3) * 1000,
                'total': (t4 - t0) * 1000,
            },
        }

    def _consider(self, parsed):
        if not parsed['complete']:
            self._agree = 0
            self._sig = None
            self.locked = False
            return
        sig = (parsed['pay'], parsed['minutes'], parsed['miles'])
        self._agree = self._agree + 1 if sig == self._sig else 1
        self._sig = sig
        self.locked = self._agree >= self.agree_to_lock
        self.last = parsed

    def feed(self, frame):
        """Motion-gated read. Returns None when the frame was skipped."""
        if not self.should_read(frame):
            return None
        return self.read(frame)
