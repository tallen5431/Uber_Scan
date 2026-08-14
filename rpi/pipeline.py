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
"""

import atexit
import os
import tempfile
import threading
import time
from concurrent import futures

import cv2
import numpy as np
import pytesseract

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


def _detect_quad(frame, min_area_frac, max_area_frac):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    gray = cv2.GaussianBlur(gray, (7, 7), 0)
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # The closing kernel is a fraction of the frame so it means the same thing
    # whether this ran on the sensor image or a thumbnail of it.
    k = max(3, (int(frame.shape[1] * 0.011) | 1))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    h, w = frame.shape[:2]
    # The biggest bright thing that the middle of the frame is inside — and
    # only failing that, the biggest bright thing.
    #
    # "Biggest" alone is a guess about the scene, and it is wrong whenever
    # something in the car is brighter and larger than the phone: a lit
    # dashboard panel, a window at dusk, a passenger's own screen. Aiming the
    # card at the middle is a thing the driver can actually do and does, so it
    # is better evidence than size, and preferring it means the outline stops
    # wandering off onto scenery.
    centre = (w / 2.0, h / 2.0)
    inside = [c for c in contours if cv2.pointPolygonTest(c, centre, False) >= 0]
    best = max(inside or contours, key=cv2.contourArea)
    area = cv2.contourArea(best)
    if area < h * w * min_area_frac or area > h * w * max_area_frac:
        return None

    # A phone stood in portrait can fill the frame's height, but it cannot also
    # fill its width — the frame is 4:3 and the phone is about 1:2. Something
    # spanning both dimensions is the picture itself, not a screen in it, which
    # is what Otsu returns when the scene has no darker surround to split off.
    bx, by, bw, bh = cv2.boundingRect(best)
    if bw > w * 0.95 and bh > h * 0.95:
        return None

    peri = cv2.arcLength(best, True)
    for eps in (0.02, 0.03, 0.05, 0.08):
        approx = cv2.approxPolyDP(best, eps * peri, True)
        if len(approx) == 4:
            return order_quad(approx.reshape(4, 2).astype(np.float32))
    # Not a clean quadrilateral: fall back to the rotated bounding box.
    return order_quad(cv2.boxPoints(cv2.minAreaRect(best)).astype(np.float32))


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


def preprocess(card):
    """Grey, even out the glare gradient, and stretch contrast.

    CLAHE rather than a global stretch because a windshield puts a bright band
    across part of the screen and leaves the rest dim.
    """
    gray = cv2.cvtColor(card, cv2.COLOR_BGR2GRAY) if card.ndim == 3 else card
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


def snapshot(frame, quad, roi, card_height=CARD_HEIGHT, width=640, card=None):
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


def ocr(image, config=OCR_CONFIG):
    return pytesseract.image_to_string(stage_for_ocr(image), config=config)


def ocr_lines(image, config=OCR_CONFIG):
    """OCR that also says where each line was. Returns (text, lines).

    Same engine and the same one pass as ocr(), just asked for its layout as
    well, so this costs nothing extra. The boxes are what let a crop that has
    slid off the card find its way back on.
    """
    tsv = pytesseract.image_to_data(stage_for_ocr(image), config=config)
    rows = [r.split('\t') for r in tsv.splitlines()[1:]]
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


class Scanner:
    """Holds the motion gate and the agreement counter across frames."""

    def __init__(self, quad=None, settings=None, agree_to_lock=2,
                 card_height=CARD_HEIGHT, config=OCR_CONFIG, roi=None,
                 ocr_height=OCR_CARD_HEIGHT):
        self.quad = None if quad is None else np.asarray(quad, dtype=np.float32)
        # A fixed override for the crop, as fractional (x, y, w, h) of the
        # warped screen. Left None — which is the normal case — the crop is
        # derived per read from the measured geometry, which is what stops it
        # wandering. See centred_roi.
        self.roi = roi
        self.settings = settings or {}
        self.agree_to_lock = agree_to_lock
        self.card_height = card_height
        self.ocr_height = ocr_height
        self.config = config

        # The card's share of the quad, which is CARD_SHARE only while the
        # whole screen is in frame. Measured from the first frame that arrives,
        # because it takes the frame's shape to know whether the quad is the
        # whole screen or just the part of it that fitted.
        self.card_share = CARD_SHARE

        self._prev = None
        self._dirty = True      # first frame always reads
        self.last_diff = 0.0    # how much the picture moved, for callers that care
        self._sig = None
        self._agree = 0
        self.dropped = 0
        self.locked = False
        self.last = None

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
        out = self._look(frame, now)
        self._consider(out['parsed'])
        # After, not during: _look runs before the agreement counter is
        # updated, so the copy it took is the state as of the *previous* read.
        # Reporting that would have said "not locked yet" on the very read that
        # locked, which is the read the spoken verdict waits for.
        out['locked'] = self.locked
        return out

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
        frames = list(frames)
        if len(frames) == 1:
            return [self.read(frames[0], now)]

        with futures.ThreadPoolExecutor(max_workers=len(frames)) as pool:
            outs = list(pool.map(lambda f: self._look(f, now), frames))
        for out in outs:
            self._consider(out['parsed'])
            out['locked'] = self.locked
        return outs

    def _look(self, frame, now=None):
        """Everything a read does except change what the Scanner believes.

        Split out so several can run at once. Nothing here touches state that
        another reader could be touching: card_share is recomputed from the
        quad and the frame, and both readers arrive at the same answer.
        """
        now = time.time() if now is None else now
        t0 = time.perf_counter()
        if self.quad is not None:
            # Before anything is sized, work out what this quad actually is. A
            # tracked quad moves and a re-locked one can change shape, so this
            # is re-measured per read rather than settled once at startup.
            self.card_share = card_share_of_quad(self.quad, frame.shape)
        screen = warp(frame, self.quad, self.read_height) if self.quad is not None else frame
        t1 = time.perf_counter()
        prepped = preprocess(fit_for_ocr(crop(screen, self.crop_box), self.ocr_height))
        t2 = time.perf_counter()
        # Asked for its layout as well as its text, at no extra cost, because
        # where the payout landed is the only way to tell a crop that read
        # nothing from a crop that read half of something.
        text, lines = ocr_lines(prepped, self.config)
        t3 = time.perf_counter()
        parsed = OP.parse(text)

        # A payout hard against the cut edge is half a number, and half a
        # number still reads as a number: a "4.95" rating with its top shaved
        # became a $45.00 offer in testing. Nothing is re-fitted over it any
        # more — the crop is derived and has nowhere better to go — so the
        # answer is simply to report nothing. A missed offer costs one fare; a
        # phantom $45 one costs an hour driving it.
        clipped = money_is_clipped(lines, prepped.shape[0])
        if clipped:
            parsed = OP.parse('')
            self.dropped += 1

        rate = OP.rate(parsed, self.settings)
        t4 = time.perf_counter()

        return {
            'parsed': parsed,
            'rate': rate,
            'locked': self.locked,
            'text': text,
            # Why a read was unsatisfying, for whoever has to explain it later.
            'clipped': clipped,
            'crop': list(self.crop_box),
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
