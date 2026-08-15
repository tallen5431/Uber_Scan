"""Does a picture of an offer card come out as the right dollar figure?

    python3 rpi/test_money.py

Every other suite here tests a piece. test_parser.py checks the arithmetic on
text, test_pipeline.py checks the geometry around the reader, test_accumulate.py
checks the merging. Nothing checked the one claim the driver actually acts on:
that a photograph of a card, put through the whole chain, produces the $/hour
that card really pays.

So this renders offer cards, mounts them in a sensor-sized frame at several
distances, and runs the *real* detector, Scanner, accumulator and rate() over
them — then checks the money against the numbers the card was drawn from rather
than against a recorded answer, so it cannot drift with the code.

Slower than the others (it runs tesseract), and it needs PIL and a font. It
skips cleanly rather than failing when either is missing, because the point is
to catch a regression on a working machine, not to add a dependency nobody had.
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2

import offer_parser as OP
import pipeline as PL
from accumulate import OfferAccumulator

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print('PIL not installed — skipping the end-to-end money checks')
    sys.exit(0)

# (regular, bold) pairs, in preference order. Liberation is metrically the
# closest to what a phone actually renders; DejaVu and FreeSans are the ones a
# bare Debian or a Pi image is most likely to already have.
FONTS = [('/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
          '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf'),
         ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
          '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
         ('/usr/share/fonts/truetype/freefont/FreeSans.ttf',
          '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf')]

ok = bad = 0

W, H = 1080, 2340                 # a 19.5:9 phone, in its own pixels
SENSOR = (1748, 2328)             # what the camera hands the scanner


def eq(name, got, want):
    global ok, bad
    if got == want:
        ok += 1
    else:
        bad += 1
        print('FAIL  %s: got %r want %r' % (name, got, want))


def close(name, got, want, tol=0.01):
    global ok, bad
    if got is not None and abs(got - want) <= tol:
        ok += 1
    else:
        bad += 1
        print('FAIL  %s: got %r want %.4f' % (name, got, want))


def font(size, bold=True):
    for regular, heavy in FONTS:
        path = heavy if bold else regular
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    raise LookupError('no usable font')


def uberx_screen():
    """A ride offer: two legs, no item count."""
    im = Image.new('RGB', (W, H), (232, 234, 231))
    d = ImageDraw.Draw(im)
    for i in range(14):                       # map clutter above the card
        d.line([(60, 120 + i * 60), (1020, 95 + i * 60)], fill=(205, 210, 205), width=6)
    top = 1270
    d.rounded_rectangle([0, top, W, H], radius=44, fill=(255, 255, 255))
    # The chips and the rating line are not decoration: they are what sits
    # between the top of the card and the payout on a real offer, and leaving
    # them out moves the payout up into the part of the crop where a close mount
    # has least margin. A card drawn thinner than the real one is a test that
    # fails for a reason the road never produces.
    d.rounded_rectangle([46, top + 54, 210, top + 104], radius=25, fill=(28, 28, 28))
    d.text((72, top + 62), 'UberX', font=font(30), fill=(255, 255, 255))
    d.rounded_rectangle([224, top + 54, 388, top + 104], radius=25, fill=(233, 233, 233))
    d.text((250, top + 62), 'Exclusive', font=font(30), fill=(40, 40, 40))
    d.text((46, top + 130), '$16.05', font=font(86), fill=(0, 0, 0))
    d.text((46, top + 246), '4.95', font=font(30), fill=(90, 90, 90))
    d.text((190, top + 246), 'Verified', font=font(30), fill=(90, 90, 90))
    d.text((66, top + 330), '3 min (1.1 mi) away', font=font(40), fill=(0, 0, 0))
    d.text((66, top + 386), 'E 61 St & S Rhodes Ave, IL', font=font(32, False), fill=(110, 110, 110))
    d.text((66, top + 452), '20 min (7.3 mi) trip', font=font(40), fill=(0, 0, 0))
    d.text((66, top + 508), 'S Cottage Grove Ave, IL', font=font(32, False), fill=(110, 110, 110))
    d.rounded_rectangle([46, top + 590, W - 46, top + 700], radius=26, fill=(23, 74, 232))
    d.text((440, top + 620), 'Accept', font=font(42), fill=(255, 255, 255))
    return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)


def shop_screen():
    """A shop order: one total line, and an item count that buys shopping time."""
    im = Image.new('RGB', (W, H), (232, 234, 231))
    d = ImageDraw.Draw(im)
    for i in range(14):
        d.line([(60, 120 + i * 60), (1020, 95 + i * 60)], fill=(205, 210, 205), width=6)
    top = 1180
    d.rounded_rectangle([0, top, W, H], radius=44, fill=(255, 255, 255))
    d.text((46, top + 126), '$7.09', font=font(86), fill=(0, 0, 0))
    d.text((46, top + 240), 'Guaranteed (incl. tip)', font=font(32, False), fill=(110, 110, 110))
    d.text((66, top + 320), '6 items (6 units)', font=font(40), fill=(0, 0, 0))
    d.text((66, top + 390), '34 min (3.6 mi) total', font=font(40), fill=(0, 0, 0))
    d.text((66, top + 466), 'Dollar General (925 Shiloh Rd Nw)', font=font(32, False), fill=(60, 60, 60))
    d.rounded_rectangle([46, top + 600, W - 46, top + 710], radius=26, fill=(20, 120, 60))
    d.text((440, top + 630), 'Accept', font=font(42), fill=(255, 255, 255))
    return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)


def mount(screen, width, seed=1):
    """Put the phone in the frame at a given closeness, with sensor noise."""
    scale = width / float(screen.shape[1])
    small = cv2.resize(screen, (width, int(round(screen.shape[0] * scale))),
                       interpolation=cv2.INTER_AREA)
    frame = np.full((SENSOR[0], SENSOR[1], 3), 24, np.uint8)
    bottom, top = SENSOR[0] - 30, SENSOR[0] - 30 - small.shape[0]
    x = (SENSOR[1] - width) // 2
    lo, hi = max(0, top), min(SENSOR[0], bottom)
    frame[lo:hi, x:x + width] = small[lo - top:hi - top]
    rng = np.random.RandomState(seed)
    return np.clip(frame.astype(np.float32) + rng.normal(0, 3.0, frame.shape),
                   0, 255).astype(np.uint8)


def by_hand(pay, minutes, miles, items, settings):
    """The answer worked out the way a driver would, from the card's own numbers.

    Deliberately not a call into rate(): checking rate() against itself proves
    nothing. This is the arithmetic written out longhand from what the card says,
    which is the thing the whole rig exists to compute.
    """
    shopping = (items or 0) * settings.get('secondsPerItem', 0) / 60.0
    billed = minutes + settings.get('pad', 0) + shopping
    cost = miles * settings.get('costPerMile', 0)
    return {'perHour': (pay - cost) / (billed / 60.0),
            'grossPerHour': pay / (billed / 60.0),
            'cost': cost,
            'perMile': (pay - cost) / miles}


try:
    CARDS = [('a ride offer', uberx_screen(), (16.05, 23.0, 8.4), None),
             ('a shop order', shop_screen(), (7.09, 34.0, 3.6), 6.0)]
except (LookupError, OSError):
    print('no usable font — skipping the end-to-end money checks')
    sys.exit(0)

# Three profiles a real driver might be on, including the one where the pad and
# the shopping allowance both bite, since that is where the billed time stops
# matching the card's own minutes.
PROFILES = [
    ('the defaults', {'target': 25, 'band': 15, 'costPerMile': 0.30,
                      'pad': 0, 'secondsPerItem': 0}),
    ('an EV, with shopping time', {'target': 32, 'band': 10, 'costPerMile': 0.12,
                                   'pad': 3, 'secondsPerItem': 90}),
    ('no running cost', {'target': 25, 'band': 15, 'costPerMile': 0,
                         'pad': 0, 'secondsPerItem': 0}),
]

# Three mount distances. The narrow one is close to the floor below which the
# card stops resolving at all, so if it ever reads it has to read *correctly*.
for label, screen, want, want_items in CARDS:
    pay, minutes, miles = want
    for width in (900, 1200, 1450):
        frame = mount(screen, width, seed=1)
        quad = PL.detect_screen_quad(frame)
        eq('%s at %dpx / the screen is found' % (label, width), quad is not None, True)
        if quad is None:
            continue

        scanner = PL.Scanner(quad=quad, card_height=900,
                             settings=PROFILES[0][1])
        acc = OfferAccumulator()
        out = scanner.read(frame, now=100.0)
        parsed = acc.add(out['parsed'], now=100.0)

        eq('%s at %dpx / payout' % (label, width), parsed['pay'], pay)
        eq('%s at %dpx / minutes' % (label, width), parsed['minutes'], minutes)
        eq('%s at %dpx / miles' % (label, width), parsed['miles'], miles)
        eq('%s at %dpx / items' % (label, width), parsed['items'], want_items)
        eq('%s at %dpx / the distance is not doubted' % (label, width),
           parsed['milesUncertain'], False)

        for pname, settings in PROFILES:
            rate = OP.rate(parsed, settings)
            truth = by_hand(pay, minutes, miles, parsed['items'], settings)
            where = '%s at %dpx on %s' % (label, width, pname)
            eq(where + ' / a verdict is reached', rate['ready'], True)
            if not rate['ready']:
                continue          # the checks below would only echo that failure
            close(where + ' / $ per hour', rate['perHour'], truth['perHour'])
            close(where + ' / $ per hour before costs',
                  rate['grossPerHour'], truth['grossPerHour'])
            close(where + ' / what was deducted', rate['cost'], truth['cost'])
            close(where + ' / $ per mile', rate['perMile'], truth['perMile'])
            # The verdict has to follow from the rate and the driver's own line,
            # not from anything the reader decided along the way.
            floor = settings['target'] * (1 - settings['band'] / 100.0)
            expect = ('go' if truth['perHour'] >= settings['target']
                      else 'warn' if truth['perHour'] >= floor else 'no')
            eq(where + ' / the verdict', rate['state'], expect)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d end-to-end money checks passed' % ok)
sys.exit(1 if bad else 0)
