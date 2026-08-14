"""Tests for the parts of the pipeline that decide *where* and *how big* to read.

    python3 rpi/test_pipeline.py

The OCR engine itself is not exercised here — these are the geometric decisions
around it, which are the ones that fail silently. A crop in the wrong place
reports "no offer" on a screen with an offer on it, and reports it confidently.
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2

import pipeline as PL

ok = bad = 0


def eq(name, got, want):
    global ok, bad
    good = got == want or (isinstance(want, float) and isinstance(got, (int, float))
                           and got is not None and abs(got - want) < 0.005)
    if good:
        ok += 1
    else:
        bad += 1
        print('FAIL  %s: got %r want %r' % (name, got, want))


def ok_(name, cond):
    eq(name, bool(cond), True)


def line(text, top, height=30, left=20, right=400):
    return {'text': text, 'top': top, 'bottom': top + height, 'left': left, 'right': right}


# --- fit_for_ocr: the single biggest accuracy lever ------------------------
small = np.zeros((450, 300, 3), np.uint8)
eq('a short card is scaled up', PL.fit_for_ocr(small, 900).shape[0], 900)
eq('...keeping its aspect', PL.fit_for_ocr(small, 900).shape[1], 600)
eq('a tall one is left alone', PL.fit_for_ocr(np.zeros((1200, 300, 3), np.uint8), 900).shape[0], 1200)
eq('and it can be switched off', PL.fit_for_ocr(small, 0).shape[0], 450)
eq('an exactly-sized card is untouched',
   PL.fit_for_ocr(np.zeros((900, 300, 3), np.uint8), 900).shape[0], 900)

# --- fit_roi: find the card from where its text landed ---------------------
# A screen 1000px tall: map labels up top, then the card from 520 down.
screen = [line('W 63rd St', 120), line('S Rhodes Ave', 300),
          line('Shop & Deliver', 520), line('$7.09', 570, 70),
          line('6 items (6 units)', 680), line('34 min (3.6 mi) total', 730),
          line('Dollar General', 790), line('Accept', 860)]

fitted = PL.fit_roi(screen, 1000, current=[0.0, 0.40, 1.0, 0.60])
ok_('a card is found', fitted is not None)
ok_('the crop starts above the payout', fitted[1] < 570 / 1000.0)
ok_('...but below the map labels', fitted[1] > 300 / 1000.0)
ok_('and it reaches past the bottom line', fitted[1] + fitted[3] > 890 / 1000.0)
eq('the horizontal extent is inherited', (fitted[0], fitted[2]), (0.0, 1.0))

# The payout anchors the top, one padding above it — street names further up
# must not drag the crop back over the map.
eq('anchored a padding above the payout',
   round(fitted[1], 3), round(570 / 1000.0 - PL.FIT_PAD_ABOVE, 3))

# And that padding has to be real headroom, or the very next read calls its own
# crop clipped and the pair of them oscillate.
crop_h = fitted[3] * 1000
ok_('the payout lands clear of the top edge',
    (570 - fitted[1] * 1000) > PL.TOP_EDGE * crop_h * 2)

# --- fit_roi refuses rather than guessing ----------------------------------
eq('no text, no fit', PL.fit_roi([], 1000), None)
eq('no money, no fit', PL.fit_roi([line('W 63rd St', 120), line('Accept', 800)], 1000), None)
eq('a sliver is not a card', PL.fit_roi([line('$7.09', 950)], 1000), None)
eq('no height, no fit', PL.fit_roi(screen, 0), None)

# A payout at the very bottom with nothing under it is not a card either.
ok_('payout alone near the foot is rejected',
    PL.fit_roi([line('W 63rd St', 120), line('$7.09', 900)], 1000) is None)

# --- tighten_roi: the same job from the other side -------------------------
# fit_roi answers "reads are failing, where is the card?". This answers "reads
# are working, how much of this crop is actually card?" — which is what lets
# the shipped crop start as the whole visible screen and walk itself in, so no
# guess has to be made about how the phone is framed.
whole = [0.0, 0.0, 1.0, 1.0]
# A crop of the whole screen, with the card in the lower half of it.
inside_crop = [line('W 63rd St', 120), line('Shop & Deliver', 520), line('$7.09', 570, 70),
               line('6 items (6 units)', 680), line('34 min (3.6 mi) total', 730),
               line('Dollar General', 790)]
tighter = PL.tighten_roi(inside_crop, 1000, whole)
ok_('a roomy crop is worth tightening', tighter is not None)
ok_('...and gets smaller, not bigger', tighter[3] < whole[3])
ok_('the payout is still inside it', tighter[1] < 570 / 1000.0)
ok_('so is the last line of the card', tighter[1] + tighter[3] > 820 / 1000.0)
eq('the horizontal extent is left alone', (tighter[0], tighter[2]), (0.0, 1.0))

# It must converge: tightening the result of a tighten has to stop, or the crop
# walks itself down to nothing one read at a time.
ok_('a crop already on the card stays put',
    PL.tighten_roi([line('$7.09', 60, 70), line('34 min (3.6 mi) total', 300),
                    line('Accept', 700)], 1000, [0.0, 0.30, 1.0, 0.40]) is None)

# Same refusals as fit_roi, for the same reason: no evidence, no move.
eq('no lines, no tighten', PL.tighten_roi([], 1000, whole), None)
eq('no money, no tighten',
   PL.tighten_roi([line('W 63rd St', 120), line('Accept', 800)], 1000, whole), None)
eq('no crop to tighten', PL.tighten_roi(inside_crop, 1000, None), None)
eq('no height, no tighten', PL.tighten_roi(inside_crop, 0, whole), None)

# The lines are positioned in the crop, but the box comes back in screen
# fractions — get that conversion wrong and the crop leaps somewhere arbitrary.
part = [0.0, 0.20, 1.0, 0.80]
mapped = PL.tighten_roi(inside_crop, 1000, part)
ok_('a fit inside a partial crop stays inside it', mapped is not None
    and mapped[1] >= part[1] and mapped[1] + mapped[3] <= part[1] + part[3] + 0.001)
# Padding is a fraction of the screen, so it has to survive that conversion at
# the same size — otherwise a small crop gets a huge margin and grows.
ok_('...with the same headroom above the payout, in screen terms',
    abs((0.570 * part[3] + part[1]) - mapped[1] - PL.FIT_PAD_ABOVE) < 0.005)

# --- money_is_clipped: the guard that stops a phantom payout ---------------
eq('a payout with room above it is fine', PL.money_is_clipped(screen, 1000), False)
ok_('one flush against the top edge is not',
    PL.money_is_clipped([line('$45.00', 2), line('34 min (3.6 mi)', 90)], 1000))
eq('no money means nothing to clip',
   PL.money_is_clipped([line('34 min (3.6 mi) total', 4)], 1000), False)
eq('no lines at all is not a clip', PL.money_is_clipped([], 1000), False)

# --- crop and _same_roi ----------------------------------------------------
img = np.zeros((1000, 400, 3), np.uint8)
eq('crop takes the requested slice', PL.crop(img, [0.0, 0.5, 1.0, 0.5]).shape[0], 500)
eq('crop clamps past the edge', PL.crop(img, [0.0, 0.8, 1.0, 0.9]).shape[0], 200)
eq('no roi is the whole image', PL.crop(img, None).shape[0], 1000)

ok_('identical boxes are the same', PL._same_roi([0.02, 0.48, 0.96, 0.5], [0.02, 0.48, 0.96, 0.5]))
ok_('a jitter apart is the same', PL._same_roi([0.02, 0.48, 0.96, 0.5], [0.02, 0.49, 0.96, 0.5]))
ok_('a real move is not', not PL._same_roi([0.02, 0.48, 0.96, 0.5], [0.02, 0.33, 0.96, 0.39]))
ok_('nothing is not something', not PL._same_roi(None, [0.02, 0.48, 0.96, 0.5]))

# --- detection: the frame-filling guard, at both scales --------------------
def phone_frame(w, h, x, y, W=1200, H=900):
    f = np.full((H, W, 3), 22, np.uint8)
    f[y:y + h, x:x + w] = 240
    return f


ok_('a phone in a dark frame is found',
    PL.detect_screen_quad(phone_frame(300, 620, 400, 140)) is not None)
ok_('...on a thumbnail too',
    PL.detect_screen_quad(phone_frame(300, 620, 400, 140), work_width=PL.DETECT_WIDTH) is not None)
eq('a frame that is all screen is refused',
   PL.detect_screen_quad(np.full((900, 1200, 3), 240, np.uint8)), None)
eq('...on a thumbnail too',
   PL.detect_screen_quad(np.full((900, 1200, 3), 240, np.uint8), work_width=PL.DETECT_WIDTH), None)
eq('a speck is not a screen', PL.detect_screen_quad(phone_frame(30, 60, 400, 140)), None)

# --- read height: warp once, at the size the reader wants ------------------
sc = PL.Scanner(quad=None, roi=[0.02, 0.48, 0.96, 0.50], card_height=900, ocr_height=900)
eq('a half-screen crop warps to double', sc.read_height, 1800)
eq('so the crop needs no scaling at all',
   PL.fit_for_ocr(np.zeros((900, 400, 3), np.uint8), 900).shape[0], 900)

sc = PL.Scanner(quad=None, roi=None, card_height=900, ocr_height=900)
eq('no crop, no adjustment', sc.read_height, 900)
sc = PL.Scanner(quad=None, roi=[0.02, 0.48, 0.96, 0.50], card_height=900, ocr_height=0)
eq('no upscaling, no adjustment', sc.read_height, 900)
sc = PL.Scanner(quad=None, roi=[0.0, 0.0, 1.0, 1.0], card_height=1400, ocr_height=900)
eq('a full-screen crop still reads the card at scale', sc.read_height, 1800)

# Text size must not depend on how much slack the crop carries. Widening the
# crop to stop it clipping the payout would otherwise shrink the warp, and the
# card would come out smaller than before — keeping more of it and reading less.
tight = PL.Scanner(quad=None, roi=[0.02, 0.48, 0.96, 0.50], card_height=900, ocr_height=900)
roomy = PL.Scanner(quad=None, roi=[0.0, 0.40, 1.0, 0.60], card_height=900, ocr_height=900)
eq('a roomier crop reads at the same scale', roomy.read_height, tight.read_height)
ok_('...and that scale is bigger than the screen', roomy.read_height > 900)
roomy.roi = [0.0, 0.20, 1.0, 0.80]
eq('however roomy it gets', roomy.read_height, tight.read_height)

# A thin crop must not ask for a warp nothing can afford either.
sc = PL.Scanner(quad=None, roi=[0.02, 0.40, 0.96, 0.18], card_height=900, ocr_height=4800)
eq('the warp cannot run away', sc.read_height, PL.MAX_READ_HEIGHT)
eq('and the search pass is bounded too', sc._search_height(np.zeros((5000, 900), np.uint8)),
   PL.RESCUE_MAX_HEIGHT)

# --- knowing the screen runs off the frame ---------------------------------
# Reported, not refused. Backing off far enough to fit a whole phone into a 4:3
# frame puts the card at the floor, and the resolution is the thing that makes
# any of this work — so this says which edges, and the callers decide.
SHAPE = (1748, 2328)
spilling = [[548, 0], [1844, 0], [1792, 1746], [592, 1746]]
eq('a screen off two edges is spotted', PL.touches_edge(spilling, SHAPE), ['top', 'bottom'])

inside = [[548, 200], [1844, 200], [1792, 1500], [592, 1500]]
eq('a screen with room around it is fine', PL.touches_edge(inside, SHAPE), [])
eq('off the left', PL.touches_edge([[2, 200], [900, 200], [900, 1500], [2, 1500]], SHAPE),
   ['left'])
eq('off the right',
   PL.touches_edge([[1400, 200], [2326, 200], [2326, 1500], [1400, 1500]], SHAPE), ['right'])
eq('cornered', PL.touches_edge([[0, 0], [2327, 0], [2327, 1747], [0, 1747]], SHAPE),
   ['top', 'bottom', 'left', 'right'])
# Just inside the margin still counts — a screen a pixel from the edge is
# almost certainly continuing past it.
ok_('a hair off the edge counts',
    'top' in PL.touches_edge([[548, 8], [1844, 8], [1792, 1500], [592, 1500]], SHAPE))

# --- and measuring a card on a screen that does ----------------------------
# The number the whole mount is aimed by. Measured down the screen it saturates
# the moment the screen is taller than the frame — past that, moving the camera
# closer cannot make it go up, so it would sit under the "good" mark forever on
# exactly the mount worth having.
import calibrate as CAL                                        # noqa: E402


def screen_quad(width, height, x=600, y=200):
    return np.array([[x, y], [x + width, y], [x + width, y + height], [x, y + height]],
                    dtype=np.float32)


REAL_ASPECT = 2.15                        # what an actual phone is, 19.5:9


def phone_at(width, shape=SHAPE, aspect=REAL_ASPECT):
    """The quad a phone of this width leaves, clipped by the frame if it must.

    Built rather than declared, because a clipped screen cannot be any shape
    you like: the visible part can never be more elongated than the whole
    phone, so the obvious fixture (a fixed height, a shrinking width) is a
    phone that does not exist.
    """
    frame_h, frame_w = shape[:2]
    height = width * aspect
    top = max(0.0, (frame_h - height) / 2.0)
    bottom = min(float(frame_h), top + height)
    x = (frame_w - width) / 2.0
    return np.array([[x, top], [x + width, top], [x + width, bottom], [x, bottom]],
                    dtype=np.float32), height


whole_screen, _ = phone_at(700)
eq('an unclipped screen is measured down it',
   CAL.card_source_pixels(whole_screen, SHAPE), int(round(700 * REAL_ASPECT * PL.CARD_SHARE)))
eq('...and with no frame to check, always',
   CAL.card_source_pixels(whole_screen), int(round(700 * REAL_ASPECT * PL.CARD_SHARE)))
eq('an unclipped screen is not guessed at', PL.touches_edge(whole_screen, SHAPE), [])

# The same phone, moved closer until it runs off the top and bottom. Its
# visible height is the frame's now and says nothing about the phone, but its
# width still does.
mounts = [(w, phone_at(w)) for w in (900, 1050, 1200, 1400)]
ok_('these are the mounts being tested', all(PL.touches_edge(q, SHAPE) == ['top', 'bottom']
                                             for _, (q, _) in mounts))
read = [CAL.card_source_pixels(q, SHAPE) for _, (q, _) in mounts]
ok_('a clipped screen keeps growing as it gets closer',
    all(a < b for a, b in zip(read, read[1:])))
eq('...measured across it', read[0], int(round(900 * CAL.PHONE_ASPECT * PL.CARD_SHARE)))

# Erring low is the point: a floor that flatters the mount is not a floor.
ok_('and never over-reports the real card',
    all(px <= int(round(h * PL.CARD_SHARE)) + 1 for px, (_, (_, h)) in zip(read, mounts)))

# --- how much of the quad the card is, which is not CARD_SHARE --------------
# The same measurement, asked the other way, and the one that decides how tall
# to warp. Get it wrong and nothing looks wrong: the picture is just bigger
# than the reader can use, gets shrunk back to fit the pixel ceiling, and the
# text ends up smaller than it started.
eq('an unclipped quad is a whole screen',
   round(PL.card_share_of_quad(whole_screen, SHAPE), 3), PL.CARD_SHARE)
eq('...and with no frame to check, always',
   round(PL.card_share_of_quad(whole_screen), 3), PL.CARD_SHARE)

clipped_quad, clipped_h = phone_at(1400)
ok_('a clipped quad is mostly card', PL.card_share_of_quad(clipped_quad, SHAPE) > 0.7)
# It is the card over the *quad*, so it has to match what is really there. The
# quad of a clipped phone is the frame's full height.
truth = clipped_h * PL.CARD_SHARE / float(SHAPE[0])
ok_('...to within the aspect it had to assume',
    abs(PL.card_share_of_quad(clipped_quad, SHAPE) - truth) < 0.12)
ok_('never below the whole-screen assumption, which is the safe answer',
    all(PL.card_share_of_quad(q, SHAPE) >= PL.CARD_SHARE
        for q, _ in (phone_at(w) for w in (300, 700, 900, 1200, 1600))))
ok_('and never above all of it',
    all(PL.card_share_of_quad(q, SHAPE) <= 1.0
        for q, _ in (phone_at(w) for w in (300, 700, 900, 1200, 1600))))

# The point of the number: the reader gets a picture sized for the card.
their_quad = np.array([[393, 0], [1750, 0], [1740, 1695], [383, 1687]], dtype=np.float32)
sc = PL.Scanner(quad=their_quad, roi=[0.0, 0.10, 1.0, 0.86], card_height=900)
eq('untold, a quad is assumed to be a whole screen', sc.read_height, 1800)
sc.card_share = PL.card_share_of_quad(their_quad, SHAPE)
ok_('told otherwise, the warp comes down to suit', 1000 < sc.read_height < 1300)
ok_('...which is where the pixels went', sc.read_height < 1800 * 0.7)

# --- and the crop cannot be smaller than the card is known to be ------------
# A fit that catches only the middle of the card leaves a crop far wider than
# it is tall. The pixel ceiling then shrinks it to fit, taking the payout below
# a readable size — so the crop meant to be the fast one is the one that cannot
# read, and it fails in exactly the way that asks for another re-fit.
# The floor has to sit between two crops that look similar and are not: a fit
# that caught only the middle of the card (the rig logged 0.46 of the quad) and
# a correct tight one, which is the payout-to-last-line span plus its padding —
# about 73% of the card, so 0.80 * 0.73 here.
ok_('a mostly-card quad demands a tall crop', sc.min_crop_height > 0.46)
ok_('...but not so tall that a correct tightening is refused',
    sc.min_crop_height < sc.card_share * 0.73)
sliver = [line('$7.09', 100, 60), line('34 min (3.6 mi) total', 200),
          line('Dollar General', 260)]
eq('so a sliver of a fit is refused',
   PL.fit_roi(sliver, 1000, [0.0, 0.0, 1.0, 1.0], sc.min_crop_height), None)
ok_('...where the bare floor would have taken it',
    PL.fit_roi(sliver, 1000, [0.0, 0.0, 1.0, 1.0]) is not None)
# Even an unclipped mount gets a floor above the bare constant, because the
# constant was a guess made before the card's size was known.
plain = PL.Scanner(quad=None, roi=[0.0, 0.0, 1.0, 1.0], card_height=900)
eq('an unclipped mount floors at most of a card',
   plain.min_crop_height, PL.CARD_SHARE * PL.CROP_HOLDS)
ok_('...which is stricter than the old bare floor',
    plain.min_crop_height > PL.FIT_MIN_HEIGHT)

# --- the reader's picture is bounded ---------------------------------------
# Height alone does not bound pixels: a wide quad warped to 1800 came out
# 1336px across on a real rig, nearly twice a normal card, and reads went from
# 0.6s to 1.4s.
wide = PL.fit_for_ocr(np.zeros((1080, 1336, 3), np.uint8), 900)
ok_('an outsized card is trimmed', wide.shape[0] * wide.shape[1] <= PL.MAX_OCR_PIXELS)
ok_('...keeping its aspect', abs(wide.shape[1] / float(wide.shape[0]) - 1336 / 1080.0) < 0.02)
normal = PL.fit_for_ocr(np.zeros((450, 397, 3), np.uint8), 900)
eq('a normal card is untouched by the cap', normal.shape[0], 900)
ok_('...and is well inside it', normal.shape[0] * normal.shape[1] < PL.MAX_OCR_PIXELS)

# --- resize_height goes both ways ------------------------------------------
eq('resize up', PL.resize_height(np.zeros((450, 300, 3), np.uint8), 900).shape[:2], (900, 600))
eq('resize down', PL.resize_height(np.zeros((1800, 600, 3), np.uint8), 900).shape[:2], (900, 300))
eq('resize to the same is a no-op',
   PL.resize_height(np.zeros((900, 300, 3), np.uint8), 900).shape[:2], (900, 300))
eq('resize to nothing is refused',
   PL.resize_height(np.zeros((900, 300, 3), np.uint8), 0).shape[:2], (900, 300))

# --- the crop only moves on real evidence ----------------------------------
# A driving screen shows the day's earnings: money, no journey. Fitting the crop
# to that is how a working scanner talks itself onto the wrong half of the
# screen, and it logged seventy re-fits in twenty minutes doing exactly that.
offer = [line('Shop & Deliver', 520), line('$7.09', 570, 70),
         line('34 min (3.6 mi) total', 730), line('Accept', 860)]
furniture = [line('Today', 120), line('$142.60', 180, 70), line('12 trips', 300)]

ok_('an offer card can be located', PL.fit_roi(offer, 1000) is not None)
ok_('...and so can a screen of earnings, geometrically',
    PL.fit_roi(furniture, 1000) is not None)
# Which is why the gate is not geometric: it is whether the text is an offer.
import offer_parser as OP2                                    # noqa: E402
ok_('but only the offer parses as one', OP2.parse(' '.join(l['text'] for l in offer))['complete'])
ok_('...and the earnings screen does not',
    not OP2.parse(' '.join(l['text'] for l in furniture))['complete'])

# --- staging the image for tesseract ---------------------------------------
staged = PL.stage_for_ocr(np.zeros((900, 400), np.uint8))
ok_('an image is staged to a path', isinstance(staged, str) and staged.endswith('.pgm'))
ok_('...that exists', os.path.exists(staged))
ok_('colour is accepted too', isinstance(PL.stage_for_ocr(np.zeros((90, 40, 3), np.uint8)), str))
eq('and it is reused, not multiplied',
   PL.stage_for_ocr(np.zeros((90, 40), np.uint8)), staged)
back = cv2.imread(staged, cv2.IMREAD_GRAYSCALE)
eq('the staged image survives the round trip', back.shape, (90, 40))

# --- the live picture, written where a server may be reading it ------------
import tempfile                                               # noqa: E402

shot = os.path.join(tempfile.gettempdir(), 'uberscan-test-frame.jpg')
eq('a frame is written', PL.write_jpeg(shot, np.full((60, 80, 3), 128, np.uint8)), None)
ok_('...and is a readable jpeg', cv2.imread(shot) is not None)
eq('...at the size given', cv2.imread(shot).shape[:2], (60, 80))
ok_('no half-written file is left behind', not os.path.exists(shot + '.part'))
# A failure is reported, not raised: this runs on a timer and the scanner has
# better things to do than die because it could not draw a picture.
eq('an unwritable path reports rather than raises',
   type(PL.write_jpeg('/nonexistent-dir/x.jpg', np.zeros((4, 4, 3), np.uint8))), str)
os.remove(shot)

# --- the log has to be worth pasting ---------------------------------------
import scan_pi as SP                                          # noqa: E402

eq('a crop reads as a box', SP._fmt_roi([0.0, 0.4, 1.0, 0.6]), '[0.00 0.40 1.00 0.60]')
eq('and no crop says so', SP._fmt_roi(None), 'whole screen')

h = SP.Health()
eq('nothing to report before anything happens', h.report(1000.0, None, tight), None)
for i in range(5):
    h.add({'ms': {'total': 200.0 + i}, 'clipped': i == 4},
          {'complete': i < 3, 'pay': 7.09 if i < 4 else None})
eq('counted the reads', h.reads, 5)
eq('counted the complete ones', h.complete, 3)
eq('counted the ones with no payout', h.no_pay, 1)
eq('counted the clipped ones', h.clipped, 1)
# The window starts at the first report, not at import, so the clock it is
# judged against is always the caller's.
eq('too soon to summarise', h.report(1000.0, None, tight), None)
eq('still counting', h.reads, 5)
h.report(1000.0 + SP.HEALTH_EVERY + 1, None, tight)
eq('summarising clears the window', h.reads, 0)
ok_('but not the running totals', h.refits == 0 and h.relocks == 0)

# --- the motion gate still gates ------------------------------------------
sc = PL.Scanner(quad=None, roi=None)
still = np.full((480, 640), 100, np.uint8)
sc.should_read(still)
sc.should_read(still)
ok_('a still picture is settled', sc.settled)
moved = np.full((480, 640), 200, np.uint8)
sc.should_read(moved)
ok_('a changed one is not', not sc.settled)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d pipeline checks passed' % ok)
sys.exit(1 if bad else 0)
