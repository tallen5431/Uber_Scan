"""Frame in, verdict out. No camera dependency, so it runs and is tested off-Pi.

The speed of this thing comes from what it refuses to do:

  * it does not OCR while nothing is changing (a cheap motion gate),
  * it does not OCR a moving frame (waits for the picture to settle),
  * it does not OCR the whole sensor frame (warps to just the phone screen),
  * it does not OCR at 16MP (downscales to the smallest size that keeps a
    decimal point legible),
  * and it does not spend a third of each read compressing a PNG nobody wants
    (see stage_for_ocr).

Tesseract cost scales with pixels, so the warp is worth far more than any
tuning of the engine itself.
"""

import atexit
import os
import tempfile
import time

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
OCR_CONFIG = '--oem 1 --psm 6'

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
    best = max(contours, key=cv2.contourArea)
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

    So the crop is anchored to the card by content instead (see fit_roi and
    tighten_roi), which does not care how much of the screen is visible, and
    this is reported as a note rather than enforced as a rule.
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
# process, reused, because the loop is sequential and a fresh temp file per read
# is churn for its own sake.
_SCRATCH = None


def _clear_scratch():
    """/dev/shm is RAM. Leaving a megabyte of it behind per run is rude."""
    try:
        os.remove(_SCRATCH)
    except OSError:
        pass


def stage_for_ocr(image):
    """Put an image where tesseract can read it cheaply. Returns a path.

    Falls back to handing over the array — slow but correct — if the scratch
    file cannot be written, since a working slow read beats a broken fast one.
    """
    global _SCRATCH
    if _SCRATCH is None:
        base = '/dev/shm' if os.path.isdir('/dev/shm') and os.access('/dev/shm', os.W_OK) \
            else tempfile.gettempdir()
        _SCRATCH = os.path.join(base, 'uberscan-ocr-%d.pgm' % os.getpid())
        atexit.register(_clear_scratch)
    # PGM is greyscale only, which everything here already is by this point.
    if image.ndim == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    try:
        if cv2.imwrite(_SCRATCH, image):
            return _SCRATCH
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


# Padding around the text found on the card, as a fraction of screen height.
#
# Generous on purpose, and generous above in particular. These were half this
# size and the crops came back shaved: one capture from the road cropped in
# below the "$16.05" it was supposed to be reading, and reported a payout it had
# only remembered from an earlier frame. Clipping the top line is the expensive
# mistake here, and buffer is nearly free — it costs a few percent of a read and
# does not shrink the text, because the size handed to the reader is set by
# CARD_SHARE rather than by how much slack the crop carries.
FIT_PAD_ABOVE = 0.10
FIT_PAD_BELOW = 0.05
# Anything shorter than this did not find a card. Raised alongside the padding:
# with generous margins even a lone payout near the foot of the screen produces
# a box tall enough to look plausible, and a lone payout is furniture.
FIT_MIN_HEIGHT = 0.28

# How much of the card a crop must be able to hold to be worth believing.
#
# Well under 1.0, because a fit is anchored on the payout and the lowest line
# beneath it — not on the card. On a real Uber card that span plus its padding
# is about 73% of the card rectangle; the rest is the badge row above and the
# Accept button below, neither of which is worth a pixel. A floor above that
# would refuse every correct tightening there is. What it has to exclude is a
# fit that caught the middle of a card and lost the payout, which measured
# around 57%. See Scanner.min_crop_height.
CROP_HOLDS = 0.60

# A payout this close to the top edge of the crop, as a fraction of the crop's
# height, is not trusted to be whole.
TOP_EDGE = 0.02


# A crop this much taller than the card it holds is worth tightening. Loose
# enough that ordinary variation between cards does not cause a move.
TIGHTEN_SLACK = 1.30


def tighten_roi(lines, image_height, current, min_height=FIT_MIN_HEIGHT):
    """Shrink a working crop onto the card inside it. Returns a box or None.

    The mirror of fit_roi, and the half that makes a clipped screen workable.
    fit_roi answers "reads are failing, where is the card?" by looking at the
    whole screen; this answers "reads are working, but how much of this crop is
    actually card?" from the lines a successful read already produced — which
    costs nothing, because the reader hands back its layout anyway.

    Together they mean the crop never has to be guessed from the geometry of
    the screen. It can start as the whole of whatever is visible, which cannot
    miss the card however the phone is framed, and walk in to fit.

    `lines` are positioned within the crop; the box returned is in screen
    fractions, like `current`.
    """
    if not lines or not image_height or not current:
        return None

    money = [l for l in lines if OP.find_pay(OP.normalize(l['text'])) is not None]
    if not money:
        return None

    top = min(l['top'] for l in money) / float(image_height)
    bottom = max(l['bottom'] for l in lines if l['top'] >= min(m['top'] for m in money))
    bottom = bottom / float(image_height)

    # Padding is expressed against the screen, so convert it into this crop's
    # own scale before applying it, or a small crop gets a huge margin.
    scale = current[3] or 1.0
    top = max(0.0, top - FIT_PAD_ABOVE / scale)
    bottom = min(1.0, bottom + FIT_PAD_BELOW / scale)
    if bottom - top >= 1.0:
        return None                      # already tight

    fitted = [current[0], current[1] + top * scale, current[2], (bottom - top) * scale]
    if fitted[3] < min_height or current[3] < fitted[3] * TIGHTEN_SLACK:
        return None                      # too short to hold a card, or not worth moving
    return fitted


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


def fit_roi(lines, image_height, current=None, min_height=FIT_MIN_HEIGHT):
    """Where the offer card is, deduced from where its text landed.

    The payout is the top of the card for our purposes — everything above it is
    map — and the lowest text is the bottom. Anchoring to the money rather than
    to all text is what keeps street labels on the map from dragging the crop
    back over the whole screen.

    Returns a fractional (x, y, w, h) box, or None when there is nothing to
    anchor to. The horizontal extent is inherited, because the card always spans
    the screen and a short line would otherwise narrow the crop onto itself.
    """
    if not lines or not image_height:
        return None

    money = [l for l in lines if OP.find_pay(OP.normalize(l['text'])) is not None]
    if not money:
        return None

    top = min(l['top'] for l in money)
    bottom = max(l['bottom'] for l in lines if l['top'] >= top)

    y0 = max(0.0, top / float(image_height) - FIT_PAD_ABOVE)
    y1 = min(1.0, bottom / float(image_height) + FIT_PAD_BELOW)
    if y1 - y0 < min_height:
        return None

    x0, w = (current[0], current[2]) if current else (0.0, 1.0)
    return [float(x0), float(y0), float(w), float(y1 - y0)]


# A crop that has slid off the card is worth work to put back. All of the rest
# of these numbers exist because that work, left ungoverned, is far worse than
# the problem: a scanner logged 70 re-fits in twenty minutes, each one moving
# the crop somewhere new, and spent the time between them reading whichever
# slice of screen the last mistake had chosen.
#
# The governing idea is that a crop which is genuinely in the wrong place fails
# *every* time. One failed read is an empty screen or a blurred frame; several
# in a row, with nothing succeeding between them, is a crop that has stopped
# working.
MISSES_BEFORE_RESCUE = 2
RESCUE_EVERY = 1.2          # ...and no more often than this even then

# How many consecutive failures are worth chasing before accepting that the
# screen simply has no offer on it. Enough to reach the rescue and act on it,
# few enough that an idle scanner goes quiet again.
RECOVER_LOOKS = 4

# Two searches must land in the same place before the crop actually moves, and
# having moved it, it stays put for a while. A single search is one OCR pass on
# a hard image and is quite capable of being wrong.
#
# The intervals are short because the *conditions* are what make this safe, not
# the waiting. A search only counts if it read a complete offer, and two of them
# have to agree; once that holds there is nothing to be gained by sitting on the
# answer, and plenty to lose — every second spent deciding is a second spent
# reading the wrong part of the screen.
REFIT_AGREE = 0.06          # how close two proposals must be to count as agreeing
REFIT_EVERY = 6.0           # seconds between actually moving the crop

# The rescue pass reads the whole screen, and the card is only part of it, so it
# needs proportionally more height to leave the card legible — but not without
# limit, or a tall thin crop would ask for a picture nothing can afford to read.
RESCUE_MAX_HEIGHT = 1500

# Ceiling on the warp used for a read. Without one, a crop that has re-fitted
# itself thin asks for a proportionally taller screen — a 0.18-high crop wants
# 5000px, which is a 40MB warp and an OCR pass to match. That is the difference
# between a scanner that stutters and one that stops.
MAX_READ_HEIGHT = 2200


class Scanner:
    """Holds the motion gate and the agreement counter across frames."""

    def __init__(self, quad=None, settings=None, agree_to_lock=2,
                 card_height=CARD_HEIGHT, config=OCR_CONFIG, roi=None,
                 ocr_height=OCR_CARD_HEIGHT, on_roi=None):
        self.quad = None if quad is None else np.asarray(quad, dtype=np.float32)
        # Fractional (x, y, w, h) of the warped screen holding the offer card.
        # Uber puts it in the same place every time, so cropping to it is free
        # accuracy and halves the pixels tesseract has to walk.
        self.roi = roi
        self.settings = settings or {}
        self.agree_to_lock = agree_to_lock
        self.card_height = card_height
        self.ocr_height = ocr_height
        self.config = config
        # Called with the new box whenever the crop is re-fitted, so the owner
        # can write it down rather than rediscovering it every run.
        self.on_roi = on_roi

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
        self._last_rescue = 0.0
        self._last_refit = 0.0
        self._misses = 0
        self._proposal = None
        # Whether this crop has ever produced a whole reading. A crop that has
        # is defended; one that has not is still a guess. See _adopt.
        self._roi_proven = False
        self.rescues = 0
        self.dropped = 0
        self.locked = False
        self.last = None

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
        if self.roi and self.roi[3] and self.ocr_height:
            return int(min(max(self.card_height, round(self.ocr_height / self.card_share)),
                           MAX_READ_HEIGHT))
        return self.card_height

    def _search_height(self, screen):
        """Height for the whole-screen pass that looks for a lost card."""
        if not self.ocr_height:
            return screen.shape[0]
        share = (self.roi[3] if self.roi else 1.0) or 1.0
        return int(min(max(self.ocr_height / share, self.ocr_height), RESCUE_MAX_HEIGHT))

    @property
    def min_crop_height(self):
        """Shortest crop worth believing, as a fraction of the quad.

        A crop cannot be much shorter than the card and still hold it, and how
        tall the card is on this mount is known (card_share) rather than
        guessed. Without this the failure is self-inflicted and self-sustaining:
        a fit that catches only the middle of the card leaves a crop far wider
        than it is tall, the pixel ceiling then shrinks the text to fit, the
        payout drops below a readable size, and the reads that follow fail in
        exactly the way that asks for another re-fit.

        This is above FIT_MIN_HEIGHT even on an unclipped mount — 0.375 of a
        screen against a bare 0.28 — because the bare number was a guess made
        without knowing how big the card was, and now that is known. The max()
        is only there so a caller that sets card_share by hand cannot go under
        the old floor.
        """
        return max(FIT_MIN_HEIGHT, self.card_share * CROP_HOLDS)

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
    def recovering(self):
        """True while extra looks are still worth taking at a suspect crop.

        The motion gate fires once per card, so left alone a suspect crop learns
        one thing per offer and takes several offers to work out that it is
        broken. A caller that keeps feeding it frames while this is set turns
        that into a couple of seconds.

        Bounded, and that bound is the whole point. "Reads are failing" is the
        normal state of a scanner pointed at a screen with no offer on it, so a
        caller that re-armed on every failure would never stop: the extra looks
        fail, which asks for more extra looks, and a motion-gated scanner that
        should be idle instead warps and OCRs twice a second forever. A few
        looks are enough to tell a broken crop from an empty screen; after that
        the answer is in, and the gate can go back to doing its job.
        """
        return self.roi is not None and 0 < self._misses <= RECOVER_LOOKS

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
        now = time.time() if now is None else now
        t0 = time.perf_counter()
        if self.quad is not None:
            # Before anything is sized, work out what this quad actually is. A
            # tracked quad moves and a re-locked one can change shape, so this
            # is re-measured per read rather than settled once at startup.
            self.card_share = card_share_of_quad(self.quad, frame.shape)
        screen = warp(frame, self.quad, self.read_height) if self.quad is not None else frame
        t1 = time.perf_counter()
        prepped = preprocess(fit_for_ocr(crop(screen, self.roi), self.ocr_height))
        t2 = time.perf_counter()
        # Asked for its layout as well as its text, at no extra cost, because
        # where the payout landed is the only way to tell a crop that read
        # nothing from a crop that read half of something.
        text, lines = ocr_lines(prepped, self.config)
        t3 = time.perf_counter()
        parsed = OP.parse(text)

        # Either of these means the crop, not the screen, is the problem — and
        # from inside the crop neither is distinguishable from an empty screen.
        # Ask the whole screen where the card really is.
        refit = None
        clipped = money_is_clipped(lines, prepped.shape[0])
        suspect = parsed['pay'] is None or clipped
        if not suspect:
            # The crop is working. Whatever it failed to read a moment ago was
            # the screen's fault, not the crop's.
            self._misses = 0
            # ...and a working crop is the one chance to make it a *tight* one,
            # from lines this read already produced. A crop that starts as the
            # whole visible screen cannot miss the card however the phone is
            # framed; this is what stops it staying that expensive.
            if parsed['complete'] and self.roi:
                self._roi_proven = True
                refit = self._adopt(tighten_roi(lines, prepped.shape[0], self.roi,
                                                self.min_crop_height), now)
            else:
                self._proposal = None
        elif self.roi:
            self._misses += 1
        if suspect and self.roi and self._misses >= MISSES_BEFORE_RESCUE \
                and (now - self._last_rescue) > RESCUE_EVERY:
            self._last_rescue = now
            rescued, refit = self._rescue(screen, now)
            if rescued is not None:
                parsed, text = rescued['parsed'], rescued['text']
            elif clipped:
                # The crop found a payout hard against its cut edge and the
                # whole screen found none. One of the two passes is wrong, and
                # it is not the one that could see the entire card. Report
                # nothing: a missed offer costs one fare, a phantom $45 one
                # costs an hour driving it.
                parsed = OP.parse('')
                self.dropped += 1

        rate = OP.rate(parsed, self.settings)
        t4 = time.perf_counter()

        self._consider(parsed)
        return {
            'parsed': parsed,
            'rate': rate,
            'locked': self.locked,
            'text': text,
            'refit': refit,
            # Why a read was unsatisfying, for whoever has to explain it later.
            'clipped': clipped,
            'misses': self._misses,
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

    def _adopt(self, fitted, now):
        """Move the crop to `fitted`, but only on agreement. Returns it or None.

        Shared by both directions — the rescue that widens onto a lost card and
        the tightening that trims a working crop — because the discipline is
        the same either way. A single fit is one OCR pass on a hard image and is
        quite capable of being wrong; two that agree is evidence, and having
        moved, it stays put for a while so the crop cannot oscillate.

        That settling time is owed to a crop that has *earned* it. A crop which
        has produced a whole reading is worth defending against one bad search;
        a crop that has never read anything is a guess, and making a guess sit
        out the same six seconds is how the box ends up somewhere useless and
        stays there. So the wait applies only once the crop has worked at least
        once, which is the difference between recovering inside one offer and
        recovering inside several.
        """
        if not fitted or _same_roi(fitted, self.roi):
            self._proposal = None
            return None
        if not (self._proposal and _same_roi(fitted, self._proposal, REFIT_AGREE)):
            self._proposal = fitted
            return None
        if self._roi_proven and (now - self._last_refit) < REFIT_EVERY:
            return None

        self._proposal = None
        self._last_refit = now
        self._misses = 0
        self._roi_proven = False
        self.roi = fitted
        if self.on_roi:
            self.on_roi(fitted)
        return fitted

    def _rescue(self, screen, now):
        """Find the card on the whole screen and move the crop back onto it.

        Two passes on purpose. The first only has to find the payout and say
        where it is; the second reads the re-cropped card properly, and that is
        the answer returned.

        The search pass is scaled by how much of the screen the card was last
        thought to occupy, because a card at half the screen's height needs the
        screen at twice the card's target to arrive legible. Getting this wrong
        is silent and total: the search finds no money on a screen with money on
        it, and concludes the crop was fine.
        """
        wide = resize_height(screen, self._search_height(screen))
        text, lines = ocr_lines(preprocess(wide), self.config)
        parsed = OP.parse(text)
        if parsed['pay'] is None:
            return None, None       # genuinely nothing on the screen

        found = {'parsed': parsed, 'text': text}

        # Only a whole offer may move the crop. This is the rule that matters:
        # a driving screen shows the day's earnings, a promotion, a fare
        # estimate — money with no journey attached — and fitting the crop to
        # one of those is exactly how a working scanner talks itself onto the
        # wrong part of the screen and stays there. A payout with a leg beneath
        # it is an offer card; a payout on its own is furniture.
        if not parsed['complete']:
            return found, None

        fitted = self._adopt(fit_roi(lines, wide.shape[0], self.roi,
                                     self.min_crop_height), now)
        if not fitted:
            return found, None      # the card is where we thought, or not agreed yet
        self.rescues += 1

        again = ocr(preprocess(fit_for_ocr(crop(screen, fitted), self.ocr_height)), self.config)
        reparsed = OP.parse(again)
        if reparsed['pay'] is None:
            return {'parsed': parsed, 'text': text}, fitted
        return {'parsed': reparsed, 'text': again}, fitted

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


def _same_roi(a, b, tol=0.02):
    """Boxes this close are the same box; moving between them is jitter."""
    if a is None or b is None:
        return a is b
    return all(abs(float(x) - float(y)) <= tol for x, y in zip(a, b))
