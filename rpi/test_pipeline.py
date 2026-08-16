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
