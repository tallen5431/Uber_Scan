"""Frame in, verdict out. No camera dependency, so it runs and is tested off-Pi.

The speed of this thing comes from what it refuses to do:

  * it does not OCR while nothing is changing (a cheap motion gate),
  * it does not OCR a moving frame (waits for the picture to settle),
  * it does not OCR the whole sensor frame (warps to just the phone screen),
  * it does not OCR at 16MP (downscales to the smallest size that keeps a
    decimal point legible).

Tesseract cost scales with pixels, so the warp is worth far more than any
tuning of the engine itself.
"""

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


def detect_screen_quad(frame, min_area_frac=0.05, max_area_frac=0.90):
    """Find the phone screen: in a dark car it is the bright rectangle.

    Used at calibration time, not per frame — with a fixed mount the corners
    only need finding once.

    A result covering nearly the whole frame is rejected. Otsu splits an image
    into light and dark whatever is in it, so a scene with no dark surround
    "finds" a screen the size of the picture — and calibrating on that makes the
    card region an arbitrary strip of the room. Better to report no screen and
    say why than to lock in a frame-shaped one.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (7, 7), 0)
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25)))

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


def snapshot(frame, quad, roi, card_height=CARD_HEIGHT, width=640):
    """One image that answers "is it looking at the right thing?".

    The whole frame with the calibrated corners drawn on it, and inset, the
    exact card image handed to the OCR engine. Aim problems show up in the
    first; focus and glare problems show up in the second.
    """
    view = frame.copy()
    if quad is not None:
        q = np.asarray(quad, dtype=np.int32)
        cv2.polylines(view, [q], True, (100, 201, 23), 6)

    scale = width / float(view.shape[1])
    view = cv2.resize(view, (width, max(1, int(view.shape[0] * scale))),
                      interpolation=cv2.INTER_AREA)

    if quad is not None:
        card = crop(warp(frame, quad, card_height), roi)
        card = preprocess(card)
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


def ocr(image, config=OCR_CONFIG):
    return pytesseract.image_to_string(image, config=config)


class Scanner:
    """Holds the motion gate and the agreement counter across frames."""

    def __init__(self, quad=None, settings=None, agree_to_lock=2,
                 card_height=CARD_HEIGHT, config=OCR_CONFIG, roi=None):
        self.quad = None if quad is None else np.asarray(quad, dtype=np.float32)
        # Fractional (x, y, w, h) of the warped screen holding the offer card.
        # Uber puts it in the same place every time, so cropping to it is free
        # accuracy and halves the pixels tesseract has to walk.
        self.roi = roi
        self.settings = settings or {}
        self.agree_to_lock = agree_to_lock
        self.card_height = card_height
        self.config = config

        self._prev = None
        self._dirty = True      # first frame always reads
        self._sig = None
        self._agree = 0
        self.locked = False
        self.last = None

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

    def should_read(self, frame):
        """True when the picture just changed and has since settled."""
        diff = self._motion(frame)
        if diff > CHANGE_T:
            self._dirty = True
            return False        # still moving; reading now would blur
        if self._dirty and diff <= STILL_T:
            self._dirty = False
            return True
        return False

    def read(self, frame):
        """Full read of one frame, ignoring the motion gate."""
        t0 = time.perf_counter()
        card = warp(frame, self.quad, self.card_height) if self.quad is not None else frame
        card = crop(card, self.roi)
        t1 = time.perf_counter()
        prepped = preprocess(card)
        t2 = time.perf_counter()
        text = ocr(prepped, self.config)
        t3 = time.perf_counter()

        parsed = OP.parse(text)
        rate = OP.rate(parsed, self.settings)
        t4 = time.perf_counter()

        self._consider(parsed)
        return {
            'parsed': parsed,
            'rate': rate,
            'locked': self.locked,
            'text': text,
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
