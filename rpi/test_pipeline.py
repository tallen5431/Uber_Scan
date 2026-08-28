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

# --- the crop is derived, not learned --------------------------------------
# It used to fit itself to wherever the payout landed, and it could not
# converge: a rig logged sixteen moves in eighteen minutes because an UberX
# card and a Shop & Deliver card are genuinely different heights, so every fit
# was correct for the card in front of it and wrong for the next one. Now it
# comes from two things that need no history — how much of the quad is card,
# and that the card is aimed at the middle.
half = PL.centred_roi(0.5)
eq('a half-card quad gets the card plus slack', round(half[3], 3), 0.5 + PL.CROP_SLACK)
eq('...centred', round(half[1], 3), round((1.0 - half[3]) / 2.0, 3))
eq('...spanning the full width', (half[0], half[2]), (0.0, 1.0))

ok_('a bigger card gets a bigger box', PL.centred_roi(0.7)[3] > PL.centred_roi(0.5)[3])
eq('and a quad that is nearly all card is read whole', PL.centred_roi(0.85)[3], 1.0)
eq('...starting at the top, since there is nowhere to centre it',
   PL.centred_roi(0.85)[1], 0.0)
ok_('a box never leaves the quad',
    all(0.0 <= PL.centred_roi(s)[1] and PL.centred_roi(s)[1] + PL.centred_roi(s)[3] <= 1.0001
        for s in (0.3, 0.5, 0.62, 0.8, 0.95, 1.0)))

# The same input twice is the same box: nothing accumulates, so there is
# nothing to drift. This is the property the old fitting could not have.
eq('it is a function of the geometry and nothing else',
   PL.centred_roi(0.64), PL.centred_roi(0.64))

# --- money_is_clipped: the guard that stops a phantom payout ---------------
# The only guard left that can throw a reading away, and the one that has to be:
# half a payout still reads as a payout, and a "4.95" rating with its top shaved
# became a $45.00 offer.
card_text = [line('Shop & Deliver', 520), line('$7.09', 570, 70),
             line('6 items (6 units)', 680), line('34 min (3.6 mi) total', 730),
             line('Dollar General', 790), line('Accept', 860)]
eq('a payout with room above it is fine', PL.money_is_clipped(card_text, 1000), False)
ok_('one flush against the top edge is not',
    PL.money_is_clipped([line('$45.00', 2), line('34 min (3.6 mi)', 90)], 1000))
eq('no money means nothing to clip',
   PL.money_is_clipped([line('34 min (3.6 mi) total', 4)], 1000), False)
eq('no lines at all is not a clip', PL.money_is_clipped([], 1000), False)

# --- crop ------------------------------------------------------------------
img = np.zeros((1000, 400, 3), np.uint8)
eq('crop takes the requested slice', PL.crop(img, [0.0, 0.5, 1.0, 0.5]).shape[0], 500)
eq('crop clamps past the edge', PL.crop(img, [0.0, 0.8, 1.0, 0.9]).shape[0], 200)
eq('no roi is the whole image', PL.crop(img, None).shape[0], 1000)


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

# --- and it prefers the middle of the frame to the biggest bright thing -----
# "Biggest" is a guess about the scene, and it is wrong whenever something in
# the car is brighter and larger than the phone: a lit dashboard panel, a
# window at dusk, a passenger's screen. Aiming the card at the middle is a
# thing a driver can actually do, so it is better evidence than size.
# The phone straddles the middle of the frame (1200x900, so 600,450); the
# panel is bigger and brighter and does not.
distracted = phone_frame(300, 620, 450, 140)
distracted[60:840, 30:410] = 250
found = PL.detect_screen_quad(distracted)
ok_('something is found', found is not None)
ok_('and it is the phone, not the bigger panel', found[:, 0].min() > 420)
ok_('...on a thumbnail too',
    PL.detect_screen_quad(distracted, work_width=PL.DETECT_WIDTH)[:, 0].min() > 420)

# Failing that, size is still the fallback — an off-centre phone is better than
# no phone.
off = phone_frame(300, 620, 60, 140)
ok_('a phone nowhere near the middle is still found', PL.detect_screen_quad(off) is not None)

# --- a windscreen at sunset, which is not a dark car ------------------------
# Everything above assumes the phone is the bright thing in a dim cabin. Driving
# into the sun it is the dimmest bright thing in the frame: the sky is blown out,
# the glass is blown out and the bonnet is a mirror. Otsu splits light from dark
# whatever it is given, so it answered with one blob covering four fifths of the
# picture, the frame-shaped guard threw that away, and the rig reported "screen
# not visible" with the offer plainly in view.
#
# The screen here is built the way a real one looks — a grey map panel above a
# white offer card — because that is what makes it hard. A threshold high enough
# to lose the sky is very nearly high enough to lose the map too, and if it does,
# what gets locked on is the card rather than the screen.
SCREEN_TOP, SCREEN_HEIGHT = 270, 600


def windscreen(W=1200, H=900):
    f = np.full((H, W, 3), 26, np.uint8)             # dark dash
    f[0:int(H * 0.26)] = 247                         # sky, blown out
    f[int(H * 0.26):int(H * 0.39)] = 196             # hazy glass
    f[int(H * 0.39):int(H * 0.49)] = 168             # bonnet reflection
    x, w = 470, 260
    y, h = SCREEN_TOP, SCREEN_HEIGHT
    f[y:y + h, x:x + w] = 233                        # the map panel: grey
    f[y + h // 2:y + h, x:x + w] = 255               # the offer card: white
    return f


# The share of blown-out sky is chosen so the 70th percentile of this frame lands
# at 247 — above the map's 233. That is not a contrivance, it is the case the low
# rungs exist for: at that cut the map is gone and the only thing left of the
# phone is the white card, so the detector locks onto the card and every fraction
# measured against the quad is measured against the wrong rectangle.
for name, quad in (('at full size', PL.detect_screen_quad(windscreen())),
                   ('on a thumbnail, which is the path the loop takes',
                    PL.detect_screen_quad(windscreen(), work_width=PL.DETECT_WIDTH))):
    ok_('a phone against a blown-out windscreen is found %s' % name, quad is not None)
    if quad is None:
        continue
    tall = quad[:, 1].max() - quad[:, 1].min()
    wide = quad[:, 0].max() - quad[:, 0].min()
    ok_('...and it is the screen, not the white card on it %s' % name,
        tall > SCREEN_HEIGHT * 0.9)
    ok_('...nor the sky above it %s' % name, quad[:, 1].min() > SCREEN_TOP * 0.8)
    ok_('...and it is phone-shaped %s' % name, tall > wide)

# The bonnet and the strip of sky are both wider than they are tall, and both are
# brighter than the card. Shape is what rules them out, so state it directly.
band = np.full((900, 1200, 3), 20, np.uint8)
band[300:520, 40:1160] = 250
eq('a bright horizontal band is not a phone', PL.detect_screen_quad(band), None)

# --- a phone in dark mode, which is not a bright thing at all ---------------
# The brightness search assumes the screen is the bright object in a dim cabin.
# A dark-mode offer card does not merely break that, it *straddles* it: the map
# above the sheet renders around grey 44 and the sheet itself around 19, so with
# a car interior anywhere between them no single threshold can hold both halves
# of one screen. What came back was not "no screen", which would at least be
# honest — it was the map, at the full width of the phone and 47% of its height,
# on every check. The crop is a fraction of the corners, so the reader was then
# handed a piece of a map and the offer was never looked at.
def phone_in_two_tones(top_tone, card_tone, cabin, W=1200, H=900):
    """A screen whose upper half and lower half sit either side of the cabin."""
    f = np.full((H, W, 3), cabin, np.uint8)
    x, y, w, h = 470, 100, 260, 700
    f[y:y + h, x:x + w] = top_tone                       # the map
    f[y + int(h * 0.48):y + h, x:x + w] = card_tone      # the offer sheet
    # text on the sheet, which is the only bright thing on a dark card
    for i in range(5):
        r = y + int(h * 0.56) + i * 24
        f[r:r + 8, x + 20:x + w - 20] = 245
    return f, (x, y, w, h)


for cabin in (8, 30, 55, 90):
    frame, (px, py, pw, ph) = phone_in_two_tones(44, 19, cabin)
    quad = PL.detect_screen_quad(frame)
    ok_('a dark-mode screen is found at all, cabin %d' % cabin, quad is not None)
    if quad is None:
        continue
    tall = quad[:, 1].max() - quad[:, 1].min()
    ok_('...and it is the whole screen, not the map on top of it, cabin %d' % cabin,
        tall > ph * 0.8)
    ok_('...on a thumbnail too, cabin %d' % cabin,
        PL.detect_screen_quad(frame, work_width=PL.DETECT_WIDTH) is not None)

# The two searches disagreeing must not cost the case that already worked: a
# plain lit phone on a dark ground is still found, and a frame with no darker
# surround is still refused rather than "found" frame-sized.
ok_('an ordinary lit phone is still found',
    PL.detect_screen_quad(phone_frame(300, 620, 400, 140)) is not None)
eq('a frame that is all screen is still refused',
   PL.detect_screen_quad(np.full((900, 1200, 3), 240, np.uint8)), None)

# ...and the second search must not run away with the phone's *body*.
# A phone sits in a case, in a cradle, and the case is as unlike the upholstery
# as the screen is — so the difference search finds the whole handset while the
# brightness search finds the screen exactly. The case is taller, and on height
# alone it won every time: measured on a screen at 240x619 inside a case at
# 306x766, detection went from the screen to the case, 25% too tall and 28% too
# wide, with every crop fraction downstream then measured off plastic. What
# separates the two is not size, it is that a screen has writing on it.
def phone_in_a_case(case_tone=18, seat=95, case=(447, 87, 306, 766)):
    f = np.full((900, 1200, 3), seat, np.uint8)
    cx, cy, cw, ch = case
    f[cy:cy + ch, cx:cx + cw] = case_tone
    x, y, w, h = 480, 151, 240, 619
    f[y:y + h, x:x + w] = 238
    for i in range(6):
        t = y + int(h * (0.52 + i * 0.07))
        f[t:t + 7, x + 16:x + w - 16] = 60
    return f


for name, frame in (('a black case', phone_in_a_case()),
                    ('a thick cradle', phone_in_a_case(case=(430, 60, 340, 820))),
                    ('dark upholstery', phone_in_a_case(seat=35)),
                    ('a bright cabin', phone_in_a_case(seat=180))):
    quad = PL.detect_screen_quad(frame)
    ok_('a phone in %s is found' % name, quad is not None)
    if quad is None:
        continue
    tall = quad[:, 1].max() - quad[:, 1].min()
    ok_('...and it is the screen, not the handset, in %s' % name, tall < 619 * 1.1)
    ok_('...and not a piece of the screen either, in %s' % name, tall > 619 * 0.9)

# The rule that tells them apart, stated on its own: what one answer adds to the
# other has to have ink in it.
gray = cv2.cvtColor(phone_in_a_case(), cv2.COLOR_BGR2GRAY)
gray = cv2.GaussianBlur(gray, (7, 7), 0)
kern = cv2.getStructuringElement(cv2.MORPH_RECT, (13, 13))
screen_c = PL._brighter_than_the_car(gray, kern, gray.shape, 0.05, 0.90)
body_c = PL._different_from_the_car(gray, kern, gray.shape, 0.05, 0.90)
ok_('the two searches really do disagree here', screen_c is not None and body_c is not None)
if screen_c is not None and body_c is not None:
    ok_('...with the body taller enough to have won on height alone',
        PL._height(body_c) >= PL._height(screen_c) * PL.MATERIALLY_TALLER)
    ok_('...but blank, so it does not win',
        PL._writing_in_the_difference(gray, body_c, screen_c) < PL.INK_SHARE)

# --- and the reader has to know which way up the ink is ---------------------
# Tesseract runs with tessedit_do_invert=0, which switches off its own
# white-on-black retry. That is a sound trade only while preprocess() hands it
# dark text on a light card every time, and a phone in dark mode breaks that
# premise silently — the reader returned 'Ee y Piece ek te | So | - - ee ee' and
# the offer was never seen.
light_card = np.full((400, 300), 245, np.uint8)
light_card[100:130, 40:260] = 20
dark_card = cv2.bitwise_not(light_card)
ok_('a light card is not called dark mode', not PL.is_dark_mode(light_card))
ok_('a dark card is', PL.is_dark_mode(dark_card))
# Both come out of preprocess the same way up, which is the whole point.
eq('preprocess leaves a light card alone',
   bool(PL.preprocess(light_card).mean() > 128), True)
eq('...and turns a dark one over to match',
   bool(PL.preprocess(dark_card).mean() > 128), True)

# The decision is relative to the card's own range, not to a fixed level, and
# that is not a detail: inverting a light card does not degrade the reading, it
# destroys it, and a badly underexposed light card is exactly what a fixed level
# gets wrong.
starved = (light_card.astype(np.float32) * 0.32).astype(np.uint8)
ok_('a badly underexposed light card is still light mode', not PL.is_dark_mode(starved))
ok_('...and its median really is below the halfway point',
    float(np.median(starved)) < 128.0)
# ...and the mirror image: a dark card the gain has pushed up is still dark mode.
lifted = np.clip(dark_card.astype(np.float32) * 2.4, 0, 255).astype(np.uint8)
ok_('a gain-pushed dark card is still dark mode', PL.is_dark_mode(lifted))

# ...and it must not change its mind frame to frame, because the frames either
# side of a change get subtracted from one another. Two frames of one still
# picture judged opposite ways score 200.7 on banding_score against 0.7 for two
# judged alike, where 4.0 already means "rippling" — and exposure is chosen by
# ranking candidates on exactly that number, so one flip inside a candidate's
# three frames condemns the right exposure and writes another to config.json.
halves = np.zeros((400, 240), np.uint8)
halves[:200] = 20
halves[200:] = 250
rng = np.random.RandomState(9)
verdicts = []
for _ in range(40):
    noisy = np.clip(halves.astype(np.float32) + rng.normal(0, 3, halves.shape),
                    0, 255).astype(np.uint8)
    verdicts.append(PL.is_dark_mode(noisy))
ok_('a picture that is genuinely half and half is not decidable', len(set(verdicts)) == 2)
held = []
was = None
for _ in range(40):
    noisy = np.clip(halves.astype(np.float32) + rng.normal(0, 3, halves.shape),
                    0, 255).astype(np.uint8)
    was = PL.is_dark_mode(noisy, was=was)
    held.append(was)
eq('...so with a previous answer to hold onto it never changes its mind',
   len(set(held)), 1)
# The hysteresis must not make it stubborn about a card that really is the other
# way round — a phone whose theme changed between offers has to be followed.
eq('a real light card overrides a remembered dark one',
   PL.is_dark_mode(light_card, was=True), False)
eq('...and a real dark card overrides a remembered light one',
   PL.is_dark_mode(dark_card, was=False), True)

# preprocess takes the answer when it is given one, so a batch of frames being
# compared with each other are all turned the same way up.
eq('preprocess obeys an explicit polarity',
   bool(PL.preprocess(light_card, dark=True).mean() < 128), True)
eq('...in both directions',
   bool(PL.preprocess(dark_card, dark=False).mean() < 128), True)

# --- read height: warp once, at the size the reader wants ------------------
sc = PL.Scanner(quad=None, card_height=900, ocr_height=900)
eq('a half-card quad warps to double', sc.read_height, 1800)
eq('so the crop needs no scaling at all',
   PL.fit_for_ocr(np.zeros((900, 400, 3), np.uint8), 900).shape[0], 900)
eq('no upscaling asked for, no adjustment',
   PL.Scanner(quad=None, card_height=900, ocr_height=0).read_height, 900)

# Text size must not depend on how much slack the crop carries — that is the
# whole reason it comes from card_share and not from the box. Widening the crop
# would otherwise shrink the warp, and the card would come out smaller than
# before: keeping more of it and reading less of it.
tight = PL.Scanner(quad=None, roi=[0.02, 0.48, 0.96, 0.50], card_height=900, ocr_height=900)
roomy = PL.Scanner(quad=None, roi=[0.0, 0.40, 1.0, 0.60], card_height=900, ocr_height=900)
eq('a roomier crop reads at the same scale', roomy.read_height, tight.read_height)
ok_('...and that scale is bigger than the screen', roomy.read_height > 900)
roomy.roi = [0.0, 0.20, 1.0, 0.80]
eq('however roomy it gets', roomy.read_height, tight.read_height)

# A quad that is nearly all card asks for the least warping, and one that is a
# sliver of card must not ask for a warp nothing can afford.
mostly = PL.Scanner(quad=None, card_height=900, ocr_height=900)
mostly.card_share = 0.9
ok_('a mostly-card quad warps least', mostly.read_height < tight.read_height)
runaway = PL.Scanner(quad=None, card_height=900, ocr_height=4800)
runaway.card_share = 0.5
eq('and the warp cannot run away', runaway.read_height, PL.MAX_READ_HEIGHT)

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

# --- and the crop follows the same measurement ------------------------------
# The two consumers of card_share have to agree, or the reader is handed a box
# and a scale that describe different cards.
derived = PL.Scanner(quad=their_quad, card_height=900)
derived.card_share = sc.card_share
box = derived.crop_box
ok_('the crop holds the card the warp was sized for',
    box[3] >= min(1.0, sc.card_share))
ok_('...with slack for the aim being imperfect', box[3] >= min(1.0, sc.card_share + 0.1))
eq('a mount this close reads its whole visible screen', box[3], 1.0)

# On a mount far enough back to see the whole phone, it really is a crop.
plain = PL.Scanner(quad=None, card_height=900)
ok_('a whole screen in frame gets a real crop', plain.crop_box[3] < 1.0)
ok_('...still holding the card', plain.crop_box[3] > PL.CARD_SHARE)
ok_('...and centred on it', abs(plain.crop_box[1] - (1 - plain.crop_box[3]) / 2) < 0.001)

# An explicit box wins, for anyone who wants to pin one.
eq('a given crop is used as given',
   PL.Scanner(quad=None, roi=[0.0, 0.3, 1.0, 0.4]).crop_box, [0.0, 0.3, 1.0, 0.4])

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

# --- money still has to come with a journey --------------------------------
# A driving screen shows the day's earnings: money, no journey. The crop no
# longer moves for anything, so this can no longer walk it onto the wrong half
# of the screen — but the reading must still not be reported as an offer.
offer = [line('Shop & Deliver', 520), line('$7.09', 570, 70),
         line('34 min (3.6 mi) total', 730), line('Accept', 860)]
furniture = [line('Today', 120), line('$142.60', 180, 70), line('12 trips', 300)]
import offer_parser as OP2                                    # noqa: E402
ok_('an offer parses as one', OP2.parse(' '.join(l['text'] for l in offer))['complete'])
ok_('...and a screen of earnings does not',
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

# --- the live view, which no longer costs a sensor frame -------------------
# A preview is a 480px thumbnail of a car interior with a box drawn on it, and
# it was being made by copying twelve megabytes of sensor and throwing 99% of it
# away, up to fourteen times a second. The preview stream is already in hand and
# already about the right size — but the corners are stored in capture
# coordinates, so the box only lands in the right place if they come down by the
# same ratio. Getting that wrong would draw a wandering outline on a rig whose
# tracking was perfectly fine, so the two paths are compared directly.
sensor = np.full((1748, 2328, 3), 30, np.uint8)
sensor[300:1500, 700:1400] = 220
small = cv2.cvtColor(cv2.resize(sensor, (640, 480), interpolation=cv2.INTER_AREA),
                     cv2.COLOR_BGR2GRAY)
sensor_quad = np.float32([[700, 300], [1400, 300], [1400, 1500], [700, 1500]])
preview_scale = np.float32([2328 / 640.0, 1748 / 480.0])

from_sensor = PL.snapshot(sensor, sensor_quad, [0, 0.2, 1, 0.6], width=480)
from_preview = PL.snapshot(cv2.cvtColor(small, cv2.COLOR_GRAY2BGR),
                           sensor_quad / preview_scale, [0, 0.2, 1, 0.6],
                           width=480, warp_card=False)
eq('both paths make the same size of picture', from_preview.shape, from_sensor.shape)


def green_box(view):
    """Where the outline was drawn, as (x0, x1, y0, y1)."""
    g = (view[:, :, 1].astype(int)
         - np.maximum(view[:, :, 0], view[:, :, 2]).astype(int)) > 40
    ys, xs = np.nonzero(g)
    return xs.min(), xs.max(), ys.min(), ys.max()


ok_('the preview draws its outline in the same place as the sensor would',
    all(abs(a - b) <= 1 for a, b in zip(green_box(from_preview), green_box(from_sensor))))
# ...and it does not invent an inset. The inset is the one part of this picture
# anybody reads detail from, so a soft one warped out of a 640px preview looks
# exactly like a focus problem that is not there.
ok_('the sensor path insets the card it warped', from_sensor[-20:, -20:].std() > 0)
inset = from_preview[-40:, -40:]
ok_('the preview path leaves the inset off until a real read has made one',
    inset.std() < 1.0)
# But it will show one it is *given*, since that came from the reader.
card = np.full((900, 600), 200, np.uint8)
card[100:200] = 20
with_card = PL.snapshot(cv2.cvtColor(small, cv2.COLOR_GRAY2BGR),
                        sensor_quad / preview_scale, [0, 0.2, 1, 0.6],
                        width=480, card=card, warp_card=False)
ok_("...but does show the reader's own picture when there is one",
    with_card[-40:, -40:].std() > 1.0)

# --- the other live view: the phone's screen, to be read through -----------
# The scene view exists to answer "is it pointed at the right thing?" and is
# built for that: shrunk to 480px with the corners drawn on. It cannot also be
# the picture somebody reads the phone through — the phone is about a fifth of
# the frame, so it lands in roughly 120x200 of those pixels, and no amount of
# enlarging the <img> puts detail back that the file never held.
scene_phone = sensor_quad * (480.0 / 2328)
eq('the phone is barely a hundred pixels wide inside the scene view',
   int(scene_phone[:, 0].max() - scene_phone[:, 0].min()), 144)

flat = PL.screen_view(sensor, sensor_quad, 1000)
eq('the phone view is exactly the height asked for', flat.shape[0], 1000)
eq('...and keeps the screen\'s own shape', flat.shape[1],
   int(round(1000 * (1400 - 700) / float(1500 - 300))))
ok_('...which is five times the phone the scene view holds',
    flat.shape[1] > 4 * (scene_phone[:, 0].max() - scene_phone[:, 0].min()))

# Colour, even off the luma preview, because the caller composites nothing onto
# it and the page displays it as-is — a two-dimensional array is not a picture
# a browser can be handed.
eq('a colour frame stays colour', flat.ndim, 3)
grey = PL.screen_view(small, sensor_quad / preview_scale, 400)
eq('a luma frame comes back as a picture rather than a plane', grey.ndim, 3)

# Not cropped to the reading box. That box is deliberately the part of the
# screen a *price* lives in; the Accept button is outside it on every card shape
# here, and a view with no button in it is not one a phone can be driven from.
whole = PL.warp(sensor, sensor_quad, 1000)
eq('the phone view is the whole screen', flat.shape, whole.shape)
boxed = PL.crop(whole, [0, 0.2, 1, 0.6])
ok_("...and the reader's own picture is a slice of it, which is why this is "
    'not that', boxed.shape[0] < whole.shape[0] * 0.7)

# Nothing to flatten is None rather than a picture of nothing, so the caller can
# fall back to the scene — which is the view that shows *why* there is no phone
# in this one.
# `ok_(... is None)` rather than `eq(..., None)`: comparing an ndarray to None
# is elementwise, and the array of booleans that comes back raises rather than
# being false. A refusal check written the obvious way crashes when the refusal
# stops happening, which reads as a broken test rather than a caught fault.
ok_('no corners, no phone view', PL.screen_view(sensor, None, 1000) is None)
ok_('...nor a zero height', PL.screen_view(sensor, sensor_quad, 0) is None)
ok_('...nor corners that are not four points',
    PL.screen_view(sensor, np.float32([[0, 0], [1, 1]]), 1000) is None)
ok_('...nor corners with a NaN in them',
    PL.screen_view(sensor, np.float32([[np.nan, 0], [1400, 300],
                                       [1400, 1500], [700, 1500]]), 1000) is None)
# Corners that have wandered clean off the frame warp to a picture of the black
# outside it, and the tracker can produce those between a phone being moved and
# the recovery noticing — which is exactly when somebody is looking.
ok_('...nor corners entirely off the left of the frame',
    PL.screen_view(sensor, sensor_quad - np.float32([4000, 0]), 1000) is None)
ok_('...nor corners entirely below it',
    PL.screen_view(sensor, sensor_quad + np.float32([0, 4000]), 1000) is None)

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
ok_('but not the running totals', h.relocks == 0)

# --- a pin has to be asked for, not inherited ------------------------------
# The crop is placed per read. A box in the config pins it instead, which is
# the escape hatch — but the key it is read from must be one nothing inherits.
# Every config.json written before the crop became derived carries an `roi`,
# and honouring those silently disabled the placement: [0,0,1,1] (harmless but
# slow), [0,0.40,1,0.60], and [0.02,0.48,0.96,0.50] — the old tight crop, which
# lost the payout on 13 of 42 test cards.
pinned = PL.Scanner(quad=None, roi=[0.0, 0.30, 1.0, 0.40])
eq('an explicit box is used as given', pinned.crop_box, [0.0, 0.30, 1.0, 0.40])
free = PL.Scanner(quad=None)
ok_('and without one the crop is placed', free.crop_box != [0.0, 0.30, 1.0, 0.40])
eq('...from the measured geometry', free.crop_box, PL.centred_roi(PL.CARD_SHARE))

# The three boxes older versions wrote, each fed in as a config would feed it.
# None of them may reach the Scanner from the `roi` key any more.
import scan_pi as SP2                                          # noqa: E402
for legacy in ([0.0, 0.0, 1.0, 1.0], [0.0, 0.40, 1.0, 0.60], [0.02, 0.48, 0.96, 0.50]):
    cfg = {'roi': legacy}
    eq('a config carrying %s pins nothing' % (legacy,), cfg.get('cropBox'), None)
    eq('...and the scanner built from it places its own crop',
       PL.Scanner(quad=None, roi=cfg.get('cropBox')).crop_box,
       PL.centred_roi(PL.CARD_SHARE))

# --- one bad frame is a log line, not a dead scanner ------------------------
import io                                                      # noqa: E402
import contextlib                                              # noqa: E402
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    for _ in range(50):
        SP2._read_failed(RuntimeError('tesseract died'))
    SP2._read_failed(ValueError('degenerate quad'))
said = [l for l in buf.getvalue().splitlines() if l.strip()]
eq('repeats of one fault are said once', len(said), 2)
ok_('and the fault is named', 'tesseract died' in said[0])

# --- reading two frames at once -------------------------------------------
# A verdict needs two reads that agree, and that confirmation earns its keep:
# over rippling, soft, glared and dim frames a single read claiming a whole
# offer was wrong 1 time in 36, and two agreeing were wrong none. So it is not
# the checking that gets shortened, only the waiting — the two reads happen at
# the same time instead of one after the other.
pair = PL.Scanner(quad=None, roi=[0.0, 0.0, 1.0, 1.0], card_height=200, ocr_height=0)
blank = np.full((200, 300, 3), 255, np.uint8)
outs = pair.read_many([blank, blank], now=1.0)
eq('one reading per frame', len(outs), 2)
eq('a single frame still works', len(pair.read_many([blank], now=2.0)), 1)

# The agreement counter is the whole point of the confirmation, so it must be
# applied per frame and in order — the same evidence, however it was gathered.
seq = PL.Scanner(quad=None, roi=[0.0, 0.0, 1.0, 1.0], card_height=200, ocr_height=0)
seq.agree_to_lock = 2
for parsed in ({'complete': True, 'pay': 7.09, 'minutes': 34.0, 'miles': 3.6},) * 2:
    seq._consider(parsed)
ok_('two agreeing readings lock', seq.locked)
alone = PL.Scanner(quad=None)
alone.agree_to_lock = 2
alone._consider({'complete': True, 'pay': 7.09, 'minutes': 34.0, 'miles': 3.6})
ok_('...and one on its own does not', not alone.locked)
alone._consider({'complete': True, 'pay': 9.99, 'minutes': 34.0, 'miles': 3.6})
ok_('nor do two that disagree', not alone.locked)

# The reported lock has to be the state *after* this reading is counted, or the
# read that locks reports itself as unlocked — and that is the read the spoken
# verdict waits for.
one = PL.Scanner(quad=None, roi=[0.0, 0.0, 1.0, 1.0], card_height=200, ocr_height=0)
one._sig = (7.09, 34.0, 3.6)
one._agree = 1
out = one.read(blank, now=3.0)
eq('the reported lock is current', out['locked'], one.locked)

# --- a read taken beside the loop, against frozen corners -------------------
# The read now runs on a thread while the loop that holds the camera keeps
# going, and that loop moves the corners. So a read is a pure function of the
# frames and a Geometry taken when they were captured, and what it measures is
# folded back afterwards by whoever owns the Scanner.
geo = PL.Scanner(quad=None, roi=[0.0, 0.0, 1.0, 1.0], card_height=200, ocr_height=0)
snap = geo.geometry()
eq('the snapshot carries the crop', list(snap.crop_box), [0.0, 0.0, 1.0, 1.0])
eq('...and the warp height', snap.read_height, geo.read_height)
snap.card_share = 0.9
eq('...and changing it does not reach back into the Scanner', geo.card_share,
   PL.CARD_SHARE)

# Moving the corners mid-read must not change the read in flight: the frame was
# captured against the corners that came with it.
moving = PL.Scanner(quad=None, roi=[0.0, 0.0, 1.0, 1.0], card_height=200, ocr_height=0)
held = moving.geometry()
looked = moving.look_many([blank], now=4.0, geom=held)
moving.roi = [0.1, 0.1, 0.5, 0.5]                 # the loop, while that ran
eq('a reading is one per frame however it was taken', len(looked), 1)
eq('...taken against the crop it was handed', looked[0]['crop'], [0.0, 0.0, 1.0, 1.0])

# What a read measures is only accepted if the geometry it measured against is
# still in use. A driver can draw a box on the live view during the second a
# read takes, and folding a stale measurement over the top of that would undo
# half of what the button did.
drawn = PL.Scanner(quad=None, card_height=200, ocr_height=0)
stale = drawn.geometry()
stale.card_share = 0.42                            # as if measured mid-read
drawn.roi = [0.0, 0.0, 1.0, 1.0]                   # the driver, meanwhile
drawn.fixed_card_share = 1.0
drawn.card_share = 1.0
drawn.settle([{'parsed': {'complete': False}, 'dropped': 0, 'recovered': 0}], stale)
eq('a box drawn during a read survives the read landing', drawn.card_share, 1.0)
eq('...and so does the crop it pinned', drawn.roi, [0.0, 0.0, 1.0, 1.0])

# With nothing moved, the measurement is exactly what the next read should use.
steady = PL.Scanner(quad=None, card_height=200, ocr_height=0)
fresh = steady.geometry()
fresh.card_share = 0.42
fresh.dark_mode = True
steady.settle([{'parsed': {'complete': False}, 'dropped': 0, 'recovered': 0}], fresh)
eq('an undisturbed measurement is kept', steady.card_share, 0.42)
eq('...along with which way up the ink was', steady.dark_mode, True)

# ...and corners that merely drifted are not "somebody moved it". The tracker
# eases 35% toward its candidate every 0.4s and allocates a fresh array each
# time, so refusing the measurement on that would refuse it on nearly every
# read while tracking is on.
eased = PL.Scanner(quad=[[0, 0], [10, 0], [10, 20], [0, 20]], card_height=200,
                   ocr_height=0)
drifted = eased.geometry()
drifted.card_share = 0.37
eased.quad = np.asarray([[1, 0], [11, 0], [11, 20], [1, 20]], dtype=np.float32)
eased.settle([{'parsed': {'complete': False}, 'dropped': 0, 'recovered': 0}], drifted)
eq('corners easing along does not throw the measurement away',
   eased.card_share, 0.37)

# The counters are per read and added up on one thread, so two frames read at
# once cannot lose an increment between them.
counted = PL.Scanner(quad=None, card_height=200, ocr_height=0)
counted.settle([{'parsed': {'complete': False}, 'dropped': 1, 'recovered': 0},
                {'parsed': {'complete': False}, 'dropped': 1, 'recovered': 1}])
eq('both dropped frames are counted', counted.dropped, 2)
eq('...and the recovered payout', counted.recovered, 1)

# --- a box drawn by hand reads what is inside it ---------------------------
#
# The whole point of letting a driver draw the box is the case where nothing
# automatic works, so this is checked against a frame the detector gives up on:
# a card on a dark background with no phone-shaped bright region to find. What
# the driver drew has to be read exactly, which means the crop pinned to all of
# it and the quad counted as all card — treat it as half a screen, the way a
# detected quad is, and the derived crop takes 15% off the top, which is where
# the payout is.
import cropbox as CX

W, H = 2328, 1748
scene = np.full((H, W, 3), 18, np.uint8)
cx0, cy0, cx1, cy1 = 300, 700, 1500, 1300
cv2.rectangle(scene, (cx0, cy0), (cx1, cy1), (245, 245, 245), -1)
cv2.putText(scene, '$7.09', (cx0 + 40, cy0 + 180), cv2.FONT_HERSHEY_SIMPLEX, 4.0, (10, 10, 10), 9)
cv2.putText(scene, '34 min (3.6 mi)', (cx0 + 40, cy0 + 380), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (10, 10, 10), 5)
cv2.putText(scene, 'Deliver to Main St', (cx0 + 40, cy0 + 520), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (60, 60, 60), 3)

eq('the detector finds nothing here, which is why the box exists',
   PL.detect_screen_quad(scene), None)

drawn = CX.parse_request({'box': [cx0 / float(W), cy0 / float(H),
                                  (cx1 - cx0) / float(W), (cy1 - cy0) / float(H)]})
hand = PL.Scanner(quad=np.array(CX.in_pixels(drawn, (W, H)), dtype=np.float32),
                  roi=CX.PIN_WHOLE, card_height=900, card_share=1.0)
read = hand.read(scene)['parsed']
eq('the payout inside a hand-drawn box is read', read['pay'], 7.09)
eq('...with the time', read['minutes'], 34.0)
eq('...and the distance', read['miles'], 3.6)
eq('the crop is all of what was drawn', hand.crop_box, CX.PIN_WHOLE)
eq('and the warp is the height the reader wants, not twice it',
   hand.read_height, 900)

# The same corners taken for a screen rather than a card: this is what the
# hand-drawn path must not do, and it is not a small difference.
as_screen = PL.Scanner(quad=np.array(CX.in_pixels(drawn, (W, H)), dtype=np.float32),
                       roi=None, card_height=900)
eq('treated as half a screen it reads nothing at all',
   as_screen.read(scene)['parsed']['pay'], None)
eq('...because the derived crop cuts the top off', [round(v, 2) for v in as_screen.crop_box],
   [0.0, 0.15, 1.0, 0.7])

# --- the motion gate still gates ------------------------------------------
sc = PL.Scanner(quad=None, roi=None)
still = np.full((480, 640), 100, np.uint8)
sc.should_read(still)
sc.should_read(still)
ok_('a still picture is settled', sc.settled)
moved = np.full((480, 640), 200, np.uint8)
sc.should_read(moved)
ok_('a changed one is not', not sc.settled)

# --- the gate has to watch the phone, not the cabin -------------------------
#
# The gate's statistic is a mean over every pixel it is handed, so whatever is
# not phone divides the signal down. On this rig the phone is about a quarter of
# the frame and the rest is a dark cabin that does not change between frames.
#
# The consequence is not a late read. `card_on_screen` stays false, so neither
# the resample burst nor the verify beat can fire either — the card is never
# read at all — and it bites hardest in dark mode, which is when this rig is
# driven: one real shift ran from half past eight at night until half past two.
import testcards as TC2                                        # noqa: E402

CAP = (2328, 1748)
GATE_SCALE = (CAP[0] / 640.0, CAP[1] / 480.0)


def cabin(card, share=0.33, w=640, h=480):
    """A rendered phone on a mount, in a dark cabin, at a given framing."""
    frame = np.full((h, w, 3), 28, np.uint8)
    cv2.rectangle(frame, (0, int(h * 0.55)), (w, h), (52, 48, 44), -1)
    pw = int(w * share)
    ph = int(pw * 16 / 9)
    if ph > int(h * 0.92):
        ph = int(h * 0.92)
        pw = int(ph * 9 / 16)
    frame[(h - ph) // 2:(h - ph) // 2 + ph, (w - pw) // 2:(w - pw) // 2 + pw] = \
        cv2.resize(card, (pw, ph), interpolation=cv2.INTER_AREA)
    x, y = (w - pw) // 2, (h - ph) // 2
    quad = np.array([[x * GATE_SCALE[0], y * GATE_SCALE[1]],
                     [(x + pw) * GATE_SCALE[0], y * GATE_SCALE[1]],
                     [(x + pw) * GATE_SCALE[0], (y + ph) * GATE_SCALE[1]],
                     [x * GATE_SCALE[0], (y + ph) * GATE_SCALE[1]]], dtype=np.float32)
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), quad


def fires(before, after, quad, scale):
    sc = PL.Scanner(quad=quad)
    sc.should_read(before, scale)
    sc.should_read(after, scale)
    return sc.last_diff


# Every transition where the card genuinely changes. A payout swap on an
# otherwise identical layout is deliberately not here: it moves a few hundred
# pixels and no difference gate can see it, which is what the verify beat is
# for — asserting it would be asking the gate for something it cannot do.
wide_fired = narrow_fired = cases = 0
worst_wide = None
for share in (0.25, 0.33, 0.45):
    for pal in (TC2.LIGHT, TC2.DARK):
        for before_card, after_card in (
                (TC2.blank(), TC2.uberx_screen(pal)),
                (TC2.blank(), TC2.doordash_screen(pal)),
                (TC2.uberx_screen(pal), TC2.shop_screen(pal))):
            before, quad = cabin(before_card, share)
            after, _ = cabin(after_card, share)
            cases += 1
            wide = fires(before, after, quad, None)
            narrow = fires(before, after, quad, GATE_SCALE)
            if wide > PL.CHANGE_T:
                wide_fired += 1
            elif worst_wide is None or wide > worst_wide[0]:
                worst_wide = (wide, narrow)
            if narrow > PL.CHANGE_T:
                narrow_fired += 1

eq('the gate notices every card that arrives (%d of %d)' % (narrow_fired, cases),
   narrow_fired, cases)
# ...and the wide statistic is kept beside it, because a check that only says
# the new way works cannot say whether it was ever needed.
ok_('...where measuring the whole cabin missed %d of them'
    % (cases - wide_fired), wide_fired < cases)
if worst_wide:
    ok_('...the nearest miss scoring %.2f against a threshold of %.1f, where the'
        ' phone window scored %.2f' % (worst_wide[0], PL.CHANGE_T, worst_wide[1]),
        worst_wide[1] > PL.CHANGE_T)

# A card appearing on a dark-mode phone at the framing scan_pi documents. This
# is the case that costs an offer, so it is asserted on its own rather than
# only inside the tally above.
dark_before, dark_quad = cabin(TC2.blank(), 0.33)
dark_after, _ = cabin(TC2.uberx_screen(TC2.DARK), 0.33)
ok_('a dark-mode card arriving is below the threshold over the whole cabin',
    fires(dark_before, dark_after, dark_quad, None) <= PL.CHANGE_T)
ok_('...and above it over the phone', 
    fires(dark_before, dark_after, dark_quad, GATE_SCALE) > PL.CHANGE_T)

# An uncalibrated rig has no phone to crop to, and a caller that names no scale
# is asking for the old statistic. Both must still work rather than throwing.
no_quad = PL.Scanner(quad=None)
no_quad.should_read(dark_before, GATE_SCALE)
no_quad.should_read(dark_after, GATE_SCALE)
ok_('with no quad known the gate still measures something',
    isinstance(no_quad.last_diff, float))
eq('...and it is the whole-frame statistic, unchanged',
   round(no_quad.last_diff, 6), round(fires(dark_before, dark_after, dark_quad, None), 6))

# A quad is known and the caller named no scale. This is not hypothetical:
# Scanner.feed() calls should_read(frame) with one argument, and the quad is in
# SENSOR coordinates — so a crop that treated a missing scale as 1:1 would index
# a 2328-wide box into a 640-wide frame and measure a slice down one edge rather
# than the whole picture. The statistic here has to be the wide one.
#
# The quad here is the rig's own calibrated one, not the synthetic one above:
# a synthetic quad centred in the frame clamps to an empty box at 1:1 and
# quad_window hands back the whole image regardless, so it cannot tell a
# working fallback from a broken one. This one starts at x=564 of 2328, which
# at 1:1 on a 640-wide preview is a 76-pixel strip down the right edge — a
# crop, and the wrong one.
REAL_QUAD = np.array([[564, 0], [1763, 0], [1762, 1717], [564, 1716]],
                     dtype=np.float32)
with_quad = PL.Scanner(quad=REAL_QUAD)
with_quad.should_read(dark_before)
with_quad.should_read(dark_after)
without_quad = PL.Scanner(quad=None)
without_quad.should_read(dark_before)
without_quad.should_read(dark_after)
eq('a caller that names no scale gets the whole frame, quad or no quad',
   round(with_quad.last_diff, 6), round(without_quad.last_diff, 6))

# ...and the gated read path is one of those callers, so it must still work.
fed = PL.Scanner(quad=REAL_QUAD)
fed.feed(dark_before)
ok_('the gated read path still runs with a quad set',
    isinstance(fed.last_diff, float))

# A still picture is still still, whichever window it is measured over — the
# crop must not manufacture a change out of a frame that did not move.
quiet = PL.Scanner(quad=dark_quad)
quiet.should_read(dark_after, GATE_SCALE)
quiet.should_read(dark_after, GATE_SCALE)
ok_('an unchanged picture does not fire the gate through the window',
    quiet.last_diff <= PL.STILL_T)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d pipeline checks passed' % ok)
sys.exit(1 if bad else 0)
