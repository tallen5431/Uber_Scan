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

fitted = PL.fit_roi(screen, 1000, current=[0.02, 0.48, 0.96, 0.50])
ok_('a card is found', fitted is not None)
ok_('the crop starts above the payout', fitted[1] < 570 / 1000.0)
ok_('...but below the map labels', fitted[1] > 300 / 1000.0)
ok_('and it reaches the bottom line', fitted[1] + fitted[3] > 890 / 1000.0)
eq('the horizontal extent is inherited', (fitted[0], fitted[2]), (0.02, 0.96))

# The payout anchors the top, one padding above it — street names further up
# must not drag the crop back over the map.
eq('anchored a padding above the payout',
   round(fitted[1], 3), round(570 / 1000.0 - PL.FIT_PAD_ABOVE, 3))

# --- fit_roi refuses rather than guessing ----------------------------------
eq('no text, no fit', PL.fit_roi([], 1000), None)
eq('no money, no fit', PL.fit_roi([line('W 63rd St', 120), line('Accept', 800)], 1000), None)
eq('a sliver is not a card', PL.fit_roi([line('$7.09', 950)], 1000), None)
eq('no height, no fit', PL.fit_roi(screen, 0), None)

# A payout at the very bottom with nothing under it is not a card either.
ok_('payout alone near the foot is rejected',
    PL.fit_roi([line('W 63rd St', 120), line('$7.09', 900)], 1000) is None)

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
