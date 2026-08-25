"""Offer cards drawn the way a phone draws them, for tests that need a picture.

Not shipped code and not imported by anything on the rig — it exists so that
the end-to-end tests read a rendered card rather than a hand-typed string,
which is the only way to catch the faults that live between the sensor and the
parser: a crop landing on the wrong part of the screen, a payout too small to
read, a card whose text is white on black.

Three renderers were drifting apart before this — one in test_money.py, one in
a scratch file, one written again for the dark-mode work — so they are here
once, with the theme as an argument rather than a copy.

PIL is required and is a test-time dependency only. `available()` says whether
it is there, so a caller can skip rather than fail on a machine without it.
"""

import numpy as np

try:
    import cv2
except ImportError:      # pragma: no cover - cv2 is a hard dependency elsewhere
    cv2 = None

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = ImageDraw = ImageFont = None


# (regular, bold) pairs, in preference order. Liberation is metrically the
# closest to what a phone actually renders; DejaVu and FreeSans are the ones a
# bare Debian or a Pi image is most likely to already have.
FONTS = [('/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
          '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf'),
         ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
          '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
         ('/usr/share/fonts/truetype/freefont/FreeSans.ttf',
          '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf')]

W, H = 1080, 2340                 # a 19.5:9 phone, in its own pixels
SENSOR = (1748, 2328)             # what the camera hands the scanner

# The themes. `bg`/`fg` are the card; `above` is the map behind it, which is
# part of the problem rather than decoration — a dark-mode screen is dark card
# *and* dark map, and the detector has to hold both.
LIGHT = dict(bg=(255, 255, 255), fg=(0, 0, 0), sub=(110, 110, 110),
             chip=(233, 233, 233), chip_fg=(40, 40, 40),
             above=(232, 234, 231), rule=(205, 210, 205))
DARK = dict(bg=(20, 20, 22), fg=(252, 252, 252), sub=(178, 178, 182),
            chip=(56, 56, 60), chip_fg=(200, 200, 205),
            above=(46, 44, 42), rule=(96, 94, 92))


def available():
    """True when a card can actually be drawn on this machine."""
    return Image is not None and cv2 is not None and _font_pair() is not None


def _font_pair():
    import os
    for regular, bold in FONTS:
        if os.path.exists(regular) and os.path.exists(bold):
            return regular, bold
    return None


def font(size, bold=True):
    pair = _font_pair()
    if pair is None:
        raise RuntimeError('no usable font on this machine')
    return ImageFont.truetype(pair[1 if bold else 0], size)


def _canvas(pal):
    im = Image.new('RGB', (W, H), pal['above'])
    d = ImageDraw.Draw(im)
    for i in range(14):                       # map clutter above the card
        d.line([(60, 120 + i * 60), (1020, 95 + i * 60)], fill=pal['rule'], width=6)
    return im, d


def _bgr(im):
    return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)


def uberx_screen(pal=LIGHT, pay='$16.05', pickup=('3', '1.1'), trip=('20', '7.3')):
    """A ride offer: two legs, no total line, no item count.

    The numbers are arguments so a caller can render a *second* offer in the
    same layout. That is not decoration: two cards that differ only in their
    figures are what the motion gate cannot see, and a test that swaps one card
    type for another proves nothing about it, because a different layout is a
    change the gate spots easily.

    The chips and the rating line are not decoration: they are what sits between
    the top of the card and the payout on a real offer, and leaving them out
    moves the payout up into the part of the crop where a close mount has least
    margin. A card drawn thinner than the real one is a test that fails for a
    reason the road never produces.
    """
    im, d = _canvas(pal)
    top = 1270
    d.rounded_rectangle([0, top, W, H], radius=44, fill=pal['bg'])
    d.rounded_rectangle([46, top + 54, 210, top + 104], radius=25, fill=pal['chip'])
    d.text((72, top + 62), 'UberX', font=font(30), fill=pal['chip_fg'])
    d.rounded_rectangle([224, top + 54, 388, top + 104], radius=25, fill=pal['chip'])
    d.text((250, top + 62), 'Exclusive', font=font(30), fill=pal['chip_fg'])
    d.text((46, top + 130), pay, font=font(86), fill=pal['fg'])
    d.text((46, top + 246), '4.95', font=font(30), fill=pal['sub'])
    d.text((190, top + 246), 'Verified', font=font(30), fill=pal['sub'])
    d.text((66, top + 330), '%s min (%s mi) away' % pickup, font=font(40), fill=pal['fg'])
    d.text((66, top + 386), 'E 61 St & S Rhodes Ave, IL', font=font(32, False), fill=pal['sub'])
    d.text((66, top + 452), '%s min (%s mi) trip' % trip, font=font(40), fill=pal['fg'])
    d.text((66, top + 508), 'S Cottage Grove Ave, IL', font=font(32, False), fill=pal['sub'])
    d.rounded_rectangle([46, top + 590, W - 46, top + 700], radius=26, fill=(23, 74, 232))
    d.text((440, top + 620), 'Accept', font=font(42), fill=(255, 255, 255))
    return _bgr(im)


def shop_screen(pal=LIGHT):
    """A shop order: one total line, and an item count that buys shopping time."""
    im, d = _canvas(pal)
    top = 1180
    d.rounded_rectangle([0, top, W, H], radius=44, fill=pal['bg'])
    d.text((46, top + 126), '$7.09', font=font(86), fill=pal['fg'])
    d.text((46, top + 240), 'Guaranteed (incl. tip)', font=font(32, False), fill=pal['sub'])
    d.text((66, top + 320), '6 items (6 units)', font=font(40), fill=pal['fg'])
    d.text((66, top + 390), '34 min (3.6 mi) total', font=font(40), fill=pal['fg'])
    d.text((66, top + 466), 'Dollar General (925 Shiloh Rd Nw)', font=font(32, False), fill=pal['sub'])
    d.rounded_rectangle([46, top + 600, W - 46, top + 710], radius=26, fill=(20, 120, 60))
    d.text((440, top + 630), 'Accept', font=font(42), fill=(255, 255, 255))
    return _bgr(im)


def doordash_screen(pal=LIGHT, pay='$41.11', miles='9.8', by='7:15 PM',
                    merchant="Papa John's Store 3317"):
    """A delivery offer: a deadline instead of a duration, and a lone distance.

    The third shape this rig has to read, and until now the only one that was
    never drawn. Its three fixtures in the shared corpus are *text* — they go
    straight into the parser and never through a lens, a warp, a crop or the OCR
    engine — so every claim about reading a delivery card rested on text somebody
    had typed out by hand.

    That is the wrong half to test. This card is laid out unlike the other two in
    exactly the ways the pipeline is sensitive to: the payout sits lower down
    under a banner, the distance stands alone with no time beside it, the
    duration is a clock time rather than a number of minutes, and the whole thing
    is shorter, so it occupies a different share of the screen and the crop lands
    somewhere else.

    The wording is taken from the corpus's own real captures rather than
    invented — "Guaranteed (incl. tips)", "Deliver by", "Pickup", the decline
    header and the order count are all as a real card prints them.
    """
    im, d = _canvas(pal)
    top = 1240
    d.rounded_rectangle([0, top, W, H], radius=44, fill=pal['bg'])
    # The banner a real card puts above the money, which is what pushes the
    # payout down the card and is therefore part of the problem.
    d.text((46, top + 44), 'Decline', font=font(30, False), fill=pal['sub'])
    d.text((46, top + 100), 'High paying offer!', font=font(34), fill=pal['fg'])
    d.text((46, top + 150), 'Your Platinum status gave you priority',
           font=font(28, False), fill=pal['sub'])
    d.text((46, top + 222), pay, font=font(86), fill=pal['fg'])
    d.text((46, top + 336), 'Guaranteed (incl. tips)', font=font(32, False), fill=pal['sub'])
    # A distance with no leg around it, and a deadline where a duration would be.
    d.text((66, top + 410), '%s mi' % miles, font=font(40), fill=pal['fg'])
    d.text((66, top + 476), 'Deliver by %s' % by, font=font(40), fill=pal['fg'])
    d.text((66, top + 550), 'Pickup %s' % merchant, font=font(30, False), fill=pal['sub'])
    d.text((66, top + 596), 'Customer dropoff', font=font(30, False), fill=pal['sub'])
    d.rounded_rectangle([46, top + 680, W - 46, top + 790], radius=26, fill=(220, 30, 40))
    d.text((430, top + 710), 'Accept', font=font(42), fill=(255, 255, 255))
    return _bgr(im)


def mount(screen, width, seed=1, cabin=24, sensor=SENSOR):
    """Put the phone in the frame at a given closeness, with sensor noise.

    Clipped rather than refused when the phone does not fit: a close mount that
    runs off the top of the frame is the mount this rig is documented to
    support, and a renderer that cannot draw it hides the cases that matter.
    """
    scale = width / float(screen.shape[1])
    small = cv2.resize(screen, (width, int(round(screen.shape[0] * scale))),
                       interpolation=cv2.INTER_AREA)
    frame = np.full((sensor[0], sensor[1], 3), cabin, np.uint8)
    bottom = sensor[0] - 30
    top = bottom - small.shape[0]
    x = (sensor[1] - width) // 2
    lo, hi = max(0, top), min(sensor[0], bottom)
    frame[lo:hi, x:x + width] = small[lo - top:hi - top]
    rng = np.random.RandomState(seed)
    return np.clip(frame.astype(np.float32) + rng.normal(0, 3.0, frame.shape),
                   0, 255).astype(np.uint8)


def blank(cabin=24, sensor=SENSOR):
    """A frame with no phone in it — the mount between offers."""
    return np.full((sensor[0], sensor[1], 3), cabin, np.uint8)
