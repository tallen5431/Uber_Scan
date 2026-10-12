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


# The stops a rendered Trip Planner lists unless told otherwise: the one-stop
# planner the rig photographed, with the name and the house invented. `where` is
# (street, town line), or None for a block the driver has not opened.
PLANNER_STOPS = [('Dropoff • 1 order', 'Pat Q.', 'Expected by 4:18 PM',
                  ('4821 Kestrel Dr', 'Marietta, GA'))]


def planner_screen(pal=LIGHT, stops=PLANNER_STOPS):
    """Uber's Trip Planner: the screen ⌖ Dropoff is pressed over after an accept.

    Not an offer and not a map. Laid out as the rig's own photograph of one
    shows it, in the phone's own pixels — the title at the top, each stop a
    block of a header ("Dropoff • 1 order"), a name, an "Expected by" time and,
    when the block is open, "Address" with the street and the town under it —
    because what a read of it has to survive is THIS layout through a lens: a
    whole-screen crop, a tall white page, small grey type under the black.

    `stops` is a list of (header, name, expected, where), `where` being
    (street, town line) or None for a closed block. Every name and street a
    caller passes should be invented; this draws whatever it is given.
    """
    im = Image.new('RGB', (W, H), pal['bg'])
    d = ImageDraw.Draw(im)
    d.text((70, 40), '3:57', font=font(34, False), fill=pal['fg'])
    d.text((W // 2 - 150, 210), 'Trip Planner', font=font(50, False), fill=pal['fg'])
    d.line([(60, 330), (W - 60, 330)], fill=pal['rule'], width=3)
    y = 400
    for head, name, expected, where in stops:
        d.ellipse([60, y + 50, 116, y + 106], fill=(200, 40, 50))
        d.text((150, y), head, font=font(34, False), fill=pal['sub'])
        d.text((150, y + 52), name, font=font(42), fill=pal['fg'])
        d.text((150, y + 120), expected, font=font(34, False), fill=pal['sub'])
        y += 200
        if where is not None:
            d.text((150, y), 'Address', font=font(34, False), fill=pal['sub'])
            d.text((150, y + 64), where[0], font=font(34, False), fill=pal['sub'])
            d.text((150, y + 128), where[1], font=font(34, False), fill=pal['sub'])
            d.rounded_rectangle([150, y + 210, 470, y + 280], radius=30, fill=pal['chip'])
            d.text((180, y + 224), 'View details', font=font(30, False), fill=pal['chip_fg'])
            y += 320
        d.line([(60, y), (W - 60, y)], fill=pal['rule'], width=3)
        y += 60
    d.text((W // 2 - 90, y + 80), 'Waybill', font=font(36, False), fill=(40, 110, 200))
    d.line([(0, H - 300), (W, H - 300)], fill=pal['rule'], width=3)
    d.ellipse([W // 2 - 110, H - 250, W // 2 + 110, H - 30], fill=(200, 40, 50))
    return _bgr(im)


# --- cards of different heights under one hand-drawn card box ----------------
#
# The card box is drawn once, round the card on the phone at the time, and kept.
# A TALLER card than that one puts its payout above the box: on 8 Oct an Uber
# "Early look • Order in progress" card's $14.48 sat across the top edge of the
# box the driver had drawn round a shorter "Exclusive" card, the reader got
# "gg Pit." for it, and the panel said there was no offer. The real pictures are
# gone, so these draw the two cards — and the shapes that must NOT be taken for a
# taller card — the way that phone drew them: a dark card on a light map, a few
# pixels in from either side, its button a bar near the bottom of the screen.
#
# In the phone's own pixels, like everything above. The two tops are placed so
# that the 8 Oct box, drawn on the short card, runs through the middle of the
# tall card's payout, as it did.

# The box from 8 Oct, as fractions of the screen box: x, y, w, h.
BOX_8OCT = [0.021, 0.544, 0.941, 0.456]

# Dark card on a light map: the 8 Oct phone. The bars are the two buttons — a
# dark Accept and a grey Match with light text.
NIGHT_CARD = dict(DARK, above=LIGHT['above'], rule=LIGHT['rule'],
                  accept=(56, 56, 60), accept_fg=(255, 255, 255),
                  match=(92, 92, 96), match_fg=(235, 235, 235))
DAY_CARD = dict(LIGHT, accept=(0, 0, 0), accept_fg=(255, 255, 255),
                match=(150, 150, 150), match_fg=(255, 255, 255))
# ...and a dark card on a dark map, the one nobody can see the edge of.
NIGHT_ALL = dict(DARK, accept=NIGHT_CARD['accept'], accept_fg=(255, 255, 255),
                 match=NIGHT_CARD['match'], match_fg=NIGHT_CARD['match_fg'])

CARD_MARGIN = 24          # how far in from the screen's sides the card sits
BAR_H = 110               # the button
BAR_FROM_BOTTOM = 170     # its top, above the bottom of the card
NAV_H = 126               # Android's own bar, full width, when it is drawn
SHORT_TOP = 1290          # the "Exclusive" card the 8 Oct box was drawn on
EARLY_TOP = 1038          # ...and the "Early look" card that box cut
TWO_TOP = 840             # a card carrying two orders, taller again
STACK_TOP = 560           # a card stacked above another, with no button


def _sheet(pal, top, bottom, d):
    # Square at the bottom, as a sheet is: the rounding is run off past the
    # bottom and Android's own bar, when there is one, drawn over it.
    d.rounded_rectangle([CARD_MARGIN, top, W - CARD_MARGIN, bottom + 60],
                        radius=40, fill=pal['bg'])
    if bottom < H:
        d.rectangle([0, bottom, W, H], fill=(8, 8, 8))


def _bar(pal, bottom, d, word, kind):
    y = bottom - BAR_FROM_BOTTOM
    d.rounded_rectangle([CARD_MARGIN + 30, y, W - CARD_MARGIN - 30, y + BAR_H],
                        radius=26, fill=pal[kind])
    d.text((W // 2 - 60, y + 30), word, font=font(42), fill=pal[kind + '_fg'])


def _lines(pal, top, rows, d):
    """Draw (offset, text, size, bold, sub) rows down a card from `top`."""
    for off, text, size, bold, sub in rows:
        d.text((CARD_MARGIN + 42, top + off), text, font=font(size, bold),
               fill=pal['sub'] if sub else pal['fg'])


def _chip(pal, x, y, text, d):
    width = int(font(30).getlength(text)) + 52
    d.rounded_rectangle([x, y, x + width, y + 50], radius=25, fill=pal['chip'])
    d.text((x + 26, y + 8), text, font=font(30), fill=pal['chip_fg'])
    return x + width + 14


def _screen(pal, nav):
    im, d = _canvas(pal)
    return im, d, H - (NAV_H if nav else 0)


EXCLUSIVE_ROWS = [(120, '$4.21', 86, True, False),
                  (235, 'Guaranteed (incl. tip)', 32, False, True),
                  (305, '23 min (5.2 mi) total', 40, True, False),
                  (380, "McDonald's (2500 Cobb Pkwy)", 32, False, True),
                  (430, 'Oak Rd, Marietta', 32, False, True)]


def exclusive_screen(pal=NIGHT_CARD, nav=False, pay='$4.21'):
    """The short Uber Eats card the 8 Oct box was drawn on: Exclusive, $4.21."""
    im, d, bottom = _screen(pal, nav)
    _sheet(pal, SHORT_TOP, bottom, d)
    x = _chip(pal, CARD_MARGIN + 42, SHORT_TOP + 40, 'Uber Eats', d)
    _chip(pal, x, SHORT_TOP + 40, 'Exclusive', d)
    rows = [(EXCLUSIVE_ROWS[0][0], pay) + EXCLUSIVE_ROWS[0][2:]] + EXCLUSIVE_ROWS[1:]
    _lines(pal, SHORT_TOP, rows, d)
    _bar(pal, bottom, d, 'Accept', 'accept')
    return _bgr(im)


def early_rows(pay='$14.48', by='4:15 PM', miles='8.6'):
    return [(40, 'Early look • Order in progress', 34, False, True),
            (190, pay, 86, True, False),
            (305, 'Includes expected tip', 32, False, True),
            (375, 'Est. delivery %s • %s mi' % (by, miles), 40, True, False),
            (450, "Dave's Hot Chicken (1985 Cobb", 32, False, True),
            (495, 'Parkway NW, STE 100)', 32, False, True),
            (560, 'Foothill Trl & Northwoods Dr,', 32, False, True),
            (605, 'Marietta', 32, False, True),
            (680, 'Matching may take longer', 32, False, True)]


def early_look_screen(pal=NIGHT_CARD, nav=False, pay='$14.48', by='4:15 PM',
                      miles='8.6', top=EARLY_TOP):
    """The 8 Oct card: taller than the box, so the box's top cuts its payout.

    Laid out as the driver described it — header "Early look • Order in
    progress", a "Delivery" badge, the payout, "Includes expected tip", "Est.
    delivery 4:15 PM • 8.6 mi", the restaurant and the cross streets over two
    lines each, "Matching may take longer", and a Match button: light text on a
    grey bar at the bottom.
    """
    im, d, bottom = _screen(pal, nav)
    _sheet(pal, top, bottom, d)
    _chip(pal, CARD_MARGIN + 42, top + 100, 'Delivery', d)
    _lines(pal, top, early_rows(pay, by, miles), d)
    _bar(pal, bottom, d, 'Match', 'match')
    return _bgr(im)


def two_order_screen(pal=NIGHT_CARD, nav=False):
    """Two orders on one card: taller again, so its payout sits higher still."""
    im, d, bottom = _screen(pal, nav)
    top = TWO_TOP
    _sheet(pal, top, bottom, d)
    _chip(pal, CARD_MARGIN + 42, top + 100, 'Delivery (2)', d)
    # The two pickups sit between the payout and the journey line, which is
    # what puts the payout so far above a box drawn on a one-order card while
    # the journey is still inside it.
    _lines(pal, top, [
        (40, 'Early look • 2 orders', 34, False, True),
        (190, '$18.52', 86, True, False),
        (305, 'Includes expected tip', 32, False, True),
        (375, 'Chipotle (3625 Dallas Hwy)', 32, False, True),
        (425, 'Panda Express (3605 Dallas Hwy)', 32, False, True),
        (520, 'Est. delivery 4:40 PM • 11.2 mi', 40, True, False),
        (595, 'Burnt Hickory Rd &', 32, False, True),
        (640, 'Old Mountain Rd, Marietta', 32, False, True),
        (710, 'Sandtown Rd & Sandy Plains,', 32, False, True),
        (755, 'Marietta', 32, False, True),
        (830, 'Matching may take longer', 32, False, True)], d)
    _bar(pal, bottom, d, 'Match', 'match')
    return _bgr(im)


def stacked_screen(pal=NIGHT_CARD, nav=False):
    """A card stacked above the Early-look card, with no button of its own.

    One sheet, a hairline between the two, so nothing about the edges says
    where the lower card starts: walking up from the Match bar goes straight
    through to the top of the upper card. Its figures — 12 min, 3.1 mi — are
    not the offer the bar belongs to.
    """
    im, d, bottom = _screen(pal, nav)
    _sheet(pal, STACK_TOP, bottom, d)
    _chip(pal, CARD_MARGIN + 42, STACK_TOP + 40, 'Exclusive', d)
    _lines(pal, STACK_TOP, [
        (120, '$6.50', 86, True, False),
        (235, 'Guaranteed (incl. tip)', 32, False, True),
        (305, '12 min (3.1 mi) total', 40, True, False),
        (380, "Wendy's (55 Roswell St)", 32, False, True)], d)
    d.line([(CARD_MARGIN + 30, EARLY_TOP - 20), (W - CARD_MARGIN - 30, EARLY_TOP - 20)],
           fill=pal['rule'], width=3)
    _chip(pal, CARD_MARGIN + 42, EARLY_TOP + 100, 'Delivery', d)
    _lines(pal, EARLY_TOP, early_rows(), d)
    _bar(pal, bottom, d, 'Match', 'match')
    return _bgr(im)


# A DoorDash-shaped card: red Accept, the distance on a line of its own above a
# "Deliver by" deadline, and a "Guaranteed" label under the payout. Drawn with a
# card stacked above it on one sheet, no button of its own and a bigger payout,
# and a card box drawn between the distance and the deadline: the box reads the
# deadline alone, and the walk up from the red bar runs through both cards.
DASH_CARD = dict(NIGHT_CARD, red=(220, 30, 40), red_fg=(255, 255, 255))
DASH_DAY = dict(DAY_CARD, red=(220, 30, 40), red_fg=(255, 255, 255))
DASH_TOP = 900
# The box: its top between "9.8 mi" (DASH_TOP+380..+420) and "Deliver by"
# (DASH_TOP+450), so it holds the deadline and not the distance.
BOX_DASH = [0.021, (DASH_TOP + 435) / float(H), 0.941, 1.0 - (DASH_TOP + 435) / float(H)]
DASH_UPPER = [(40, 'Order in progress', 34, False, True),
              (120, '$22.75', 86, True, False),
              (235, 'Guaranteed (incl. tips)', 32, False, True),
              (300, '3.1 mi', 40, True, False)]


def dash_stacked_screen(pal=DASH_CARD, upper=DASH_UPPER, top=DASH_TOP):
    """A $9.40 DoorDash-shaped offer under a $22.75 card with no button of its own.

    The truth for the offer the red bar belongs to: $9.40, 9.8 mi, deliver by
    7:15 PM. The $22.75 and 3.1 mi above it are another card's.
    """
    im, d, bottom = _screen(pal, False)
    _sheet(pal, STACK_TOP if upper else top, bottom, d)
    if upper:
        _lines(pal, STACK_TOP, upper, d)
        d.line([(CARD_MARGIN + 30, top - 20), (W - CARD_MARGIN - 30, top - 20)],
               fill=pal['rule'], width=3)
    _lines(pal, top, [
        (40, 'Decline', 30, False, True),
        (100, 'High paying offer!', 34, True, False),
        (190, '$9.40', 86, True, False),
        (305, 'Guaranteed (incl. tips)', 32, False, True),
        (380, '9.8 mi', 40, True, False),
        (450, 'Deliver by 7:15 PM', 40, True, False),
        (525, 'Pickup Papa Johns Store 3317', 30, False, True),
        (575, 'Customer dropoff', 30, False, True),
        (640, 'Order total hidden', 30, False, True),
        (700, 'More text', 30, False, True)], d)
    _bar(pal, bottom, d, 'Accept', 'red')
    return _bgr(im)


def degrade(screen, kind, seed=0, strength=1.0):
    """What a windscreen and a car do to a screen, applied in the phone's pixels.

    glare — a bright blob over part of the card; sheen — a band of glare level
    across the screen; blur — defocus; banding — the
    rolling stripes of a PWM-dimmed panel; dark — a dimmed phone; shadow — the
    left-hand side in the shade of the pillar; roll — the phone turned a couple
    of degrees inside the box that was drawn square round it.
    """
    rng = np.random.RandomState(seed)
    img = screen.astype(np.float32)
    h, w = img.shape[:2]
    if kind == 'glare':
        cx = rng.uniform(0.2, 0.8) * w
        cy = rng.uniform(0.5, 0.85) * h
        sigma = rng.uniform(250, 450)
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        blob = np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * sigma ** 2))
        img += (110 * strength * blob)[..., None]
    elif kind == 'sheen':
        # A band of glare straight across the screen — a windscreen's edge
        # reflected — brightest over the lower card and fading up it. Level
        # across, so whatever it does to a row it does to the whole row.
        yy = np.arange(h, dtype=np.float32)
        band = np.exp(-((yy - 0.80 * h) ** 2) / (2 * (0.12 * h) ** 2))
        img += (90 * strength * band)[:, None, None]
    elif kind == 'blur':
        img = cv2.GaussianBlur(img, (0, 0), 2.5 * strength)
    elif kind == 'banding':
        yy = np.arange(h, dtype=np.float32)
        img *= (1 + 0.12 * strength * np.sin(2 * np.pi * yy / 44.0 + seed))[:, None, None]
    elif kind == 'dark':
        img *= 0.38 / strength
    elif kind == 'shadow':
        ramp = np.clip(0.25 + 0.75 * np.arange(w, dtype=np.float32) / (0.45 * w), 0.25, 1.0)
        img *= ramp[None, :, None]
    elif kind == 'roll':
        m = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), 2.0 * strength, 1.0)
        img = cv2.warpAffine(img, m, (w, h), borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
    else:
        raise ValueError('no such degradation: %r' % kind)
    return np.clip(img, 0, 255).astype(np.uint8)


def screen_corners(width, sensor=SENSOR):
    """Where mount() puts the screen's corners, TL TR BR BL, in sensor pixels.

    What a driver drawing ▣ Set box round the screen would give, exactly. Only
    for a width at which the whole screen is in frame.
    """
    height = int(round(H * width / float(W)))
    bottom = sensor[0] - 30
    top = bottom - height
    if top < 0:
        raise ValueError('the screen runs off the frame at %dpx' % width)
    x = (sensor[1] - width) // 2
    return [[x, top], [x + width - 1, top], [x + width - 1, bottom - 1], [x, bottom - 1]]


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
