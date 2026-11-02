"""The card finder: where the offer card is, from its button up.

    python3 rpi/test_cardfind.py

cardfind.find_card is asked one question by the reader — is there a card
taller than the drawn card box, and where? — and only its `sure` answers are
acted on. So most of what is held here is the other half: every reason it
gives for NOT being sure is reached by a picture made to need it, and every
picture that once got a sure answer that was wrong is in here being refused.

Pictures are drawn by testcards.py in the phone's own pixels and handed over
at the height a read warps the screen to, with no mount between: the finder
is a pure function of a grey screen and a box, and the mount is the reader's
problem (rpi/test_pipeline.py drives it through one).
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('OMP_THREAD_LIMIT', '1')

ok = bad = 0


def eq(name, got, want):
    global ok, bad
    if got == want:
        ok += 1
    else:
        bad += 1
        print('FAIL  %s: got %r want %r' % (name, got, want))


def ok_(name, cond):
    eq(name, bool(cond), True)


try:
    import numpy as np
    import testcards as TC
    import pipeline as PL
    import cardfind as CF
except ImportError as e:
    print('%s — skipping the card finder checks' % e)
    sys.exit(0)

if not TC.available():
    print('no PIL or no usable font — skipping the card finder checks')
    sys.exit(0)

BOX = TC.BOX_8OCT
# The height the reader warps a screen box to for this card box: 900 for the
# card, over the card box's share of the screen.
READ_H = PL.Geometry(roi=BOX, fixed_card_share=BOX[3], card_share=BOX[3]).read_height


def grey(screen):
    return PL.to_grey(PL.resize_height(screen, READ_H))


def find(screen, box=BOX):
    return CF.find_card(grey(screen), box)


def top_of(phone_px):
    return phone_px / float(TC.H)


def near(a, b, within=0.01):
    return a is not None and abs(a - b) <= within


# --- the card the 8 Oct box was too short for ----------------------------------
#
# The box was drawn round the short card; the tall one's payout sat across its
# top edge. Found from the Match bar up, its top is where the card's is, its
# sides are the card's, and its bottom is the top of the bar.
for _name, _pal in (('dark on a light map', TC.NIGHT_CARD),
                    ('light on a light map', TC.DAY_CARD),
                    ('dark on a dark map', TC.NIGHT_ALL)):
    _r = find(TC.early_look_screen(_pal))
    ok_('the Early-look card, %s, is found and the finder is sure (%r)' % (_name, _r['why']),
        _r['sure'])
    _b = _r['box'] or [None] * 4
    ok_('...its top where the card\'s is, above the drawn box (%r)' % (_b[1],),
        near(_b[1], top_of(TC.EARLY_TOP)) and _b[1] < BOX[1])
    ok_('...its sides the card\'s, a few pixels in from the screen\'s (%r)' % (_b[0],),
        near(_b[0], TC.CARD_MARGIN / float(TC.W), 0.012)
        and near(_b[0] + _b[2], 1 - TC.CARD_MARGIN / float(TC.W), 0.012))
    ok_('...and its bottom the top of the Match bar, not the bottom of the card (%r)'
        % ((_b[1] or 0) + (_b[3] or 0),),
        near((_b[1] or 0) + (_b[3] or 0), top_of(TC.H - TC.BAR_FROM_BOTTOM)))

_r = find(TC.two_order_screen())
ok_('a card carrying two orders is found at its own top (%r)' % (_r['box'],),
    _r['sure'] and near(_r['box'][1], top_of(TC.TWO_TOP)))
_r = find(TC.exclusive_screen())
ok_('the short card the box was drawn on is found where the box already starts (%r)'
    % (_r['box'],), _r['sure'] and near(_r['box'][1], top_of(TC.SHORT_TOP)))
ok_('...so it is no taller than the box, which is the reader\'s test, not this one',
    _r['sure'] and _r['box'][1] > BOX[1] - PL.TALLER)

# --- a card stacked above, with no button of its own --------------------------
#
# One sheet and a hairline: nothing in the picture says where the lower card
# starts, so the walk goes through to the upper card's top. Found that way on
# purpose and refused by the READER, which can see the figures change — see
# rescue_refused in pipeline.py. The finder's answer is what the picture shows.
_r = find(TC.stacked_screen())
ok_('a card stacked above with no button is one sheet with the card below (%r)'
    % (_r['box'],), _r['sure'] and near(_r['box'][1], top_of(TC.STACK_TOP)))

# --- the phone's own bar is never the button ---------------------------------
_r = find(TC.early_look_screen(TC.DAY_CARD, nav=True))
ok_('with Android\'s bar below the button, the button is the bar found (%r)'
    % (_r['box'],),
    _r['sure'] and near(_r['box'][1] + _r['box'][3],
                        top_of(TC.H - TC.NAV_H - TC.BAR_FROM_BOTTOM)))


def without_button(screen, pal, nav=False):
    """The same screen with its button painted out in the card's own colour."""
    out = screen.copy()
    bottom = TC.H - (TC.NAV_H if nav else 0)
    y = bottom - TC.BAR_FROM_BOTTOM
    out[y - 4:y + TC.BAR_H + 4, TC.CARD_MARGIN + 20:TC.W - TC.CARD_MARGIN - 20] = \
        np.array(pal['bg'][::-1], np.uint8)
    return out


_r = find(without_button(TC.early_look_screen(TC.DAY_CARD, nav=True), TC.DAY_CARD, nav=True),
          box=[BOX[0], BOX[1], BOX[2], 1.0 - BOX[1]])
eq('a full-width dark band with no button above it is the phone\'s own bar, refused',
   (_r['sure'], _r['why']),
   (False, 'only a full-width band there — the phone\'s own bar, not a button'))

# --- every other reason it gives, reached ---------------------------------------
eq('no picture is no answer', CF.find_card(None, BOX),
   {'sure': False, 'box': None, 'why': 'no screen or no card box'})
eq('...and no card box is no answer', CF.find_card(grey(TC.exclusive_screen()), None)['why'],
   'no screen or no card box')

_r = find(without_button(TC.early_look_screen(), TC.NIGHT_CARD))
eq('a card with no button near the box\'s bottom is not one',
   (_r['sure'], _r['why']), (False, 'no button bar near the bottom of the card box'))


def picture_for_button(screen):
    """A photograph-like strip where the button would be: edges, no solid colour."""
    out = screen.copy()
    y = TC.H - TC.BAR_FROM_BOTTOM
    rng = np.random.RandomState(4)
    strip = rng.randint(60, 255, (TC.BAR_H // 10 + 1, (TC.W - 2 * TC.CARD_MARGIN - 60) // 10 + 1, 3))
    strip = np.kron(strip, np.ones((10, 10, 1))).astype(np.uint8)
    out[y:y + TC.BAR_H, TC.CARD_MARGIN + 30:TC.W - TC.CARD_MARGIN - 30] = \
        strip[:TC.BAR_H, :TC.W - 2 * TC.CARD_MARGIN - 60]
    return out


_r = find(picture_for_button(TC.early_look_screen()))
eq('a picture strip where the button would be is not a button',
   (_r['sure'], _r['why']),
   (False, 'the band near the bottom is not solid — a picture, not a button'))


def card_from(top, left=TC.CARD_MARGIN, right=TC.W - TC.CARD_MARGIN, rows=None,
              pal=TC.NIGHT_CARD, body=None):
    """A plain card of any shape with a Match bar, for the reasons that need one."""
    im, d = TC._canvas(pal)
    d.rounded_rectangle([left, top, right, TC.H + 60], radius=40, fill=pal['bg'])
    for off, text in (rows if rows is not None else
                      [(40, 'Early look'), (190, '$14.48'), (305, 'Includes expected tip'),
                       (375, 'Est. delivery 4:15 PM')]):
        if top + off < TC.H - 200:
            d.text((left + 42, top + off), text, font=TC.font(40), fill=pal['fg'])
    y = TC.H - TC.BAR_FROM_BOTTOM
    d.rounded_rectangle([left + 30, y, right - 30, y + TC.BAR_H], radius=26, fill=pal['match'])
    if body is not None:
        body(d, top, left, right)
    return TC._bgr(im)


# Narrower than half the screen is not a test of its own: its button is
# narrower still, and a bar has to span most of the screen to be found at all.
_r = find(card_from(TC.EARLY_TOP, left=300, right=780))
eq('a card narrower than half the screen is not an offer card: its button is no bar',
   (_r['sure'], _r['why']), (False, 'no button bar near the bottom of the card box'))

# Its body a tenth of the screen, two lines on it, and its bar: 14.7%.
_r = find(card_from(TC.H - TC.BAR_FROM_BOTTOM - 234, rows=[(40, 'Early look'), (120, '$4.21')]),
          box=[BOX[0], 0.80, BOX[2], 0.20])
ok_('a card shorter than 15%% of the screen is not one (%r)' % _r['why'],
    not _r['sure'] and 'outside 15' in _r['why'])
_r = find(card_from(150, rows=[(40 + 120 * i, 'line %d' % i) for i in range(12)]))
ok_('...nor one taller than 85%% of it (%r)' % _r['why'],
    not _r['sure'] and 'outside 15' in _r['why'] and '% of the screen tall' in _r['why'])

_r = find(card_from(-60))
eq('a card running off the top of the screen box has no top to be sure of',
   (_r['sure'], _r['why']), (False, 'the card runs off the top of the screen box'))

_r = find(card_from(TC.EARLY_TOP, rows=[(190, '$14.48'), (375, 'Est. delivery 4:15 PM')]))
eq('a card with fewer than three lines of text on it is not an offer card',
   (_r['sure'], _r['why']), (False, 'fewer than 3 lines of text on the card'))


def bars(d, top, left, right):
    # A body that is mostly ink, but in upright bars, so that every block of
    # every row still shows some of the card between them and the walk goes
    # on up it: 13 pixels of ink in every 24, down to 85% of the way down the
    # screen, which at the finder's scale leaves under half the body clear.
    for x in range(left + 10, right - 10, 24):
        d.rectangle([x, top + 30, x + 12, int(0.85 * TC.H)], fill=(150, 150, 150))


_r = find(card_from(TC.EARLY_TOP, body=bars))
eq('a body that is mostly not background is not an offer card',
   (_r['sure'], _r['why']), (False, 'the card is not mostly background'))

# --- a phone turned inside its box ---------------------------------------------
#
# No deskew: the box was drawn square round the screen, so a card that is not
# square in it is a phone that has moved, and the honest answer is unsure. The
# abrupt-start test is what says so — the bar is still found, but the card's
# top leaves the card in one block several rows before it does in another.
_ROLL = "the card's top edge is not square to the box \u2014 the phone has turned inside it"
for _name, _pal in (('dark', TC.NIGHT_CARD), ('light', TC.DAY_CARD)):
    _r = find(TC.degrade(TC.early_look_screen(_pal), 'roll', strength=0.75))
    eq('a %s card on a phone turned 1.5\u00b0 inside its box is unsure, for its top'
       % _name, (_r['sure'], _r['why']), (False, _ROLL))
    # At two degrees the button itself is too far out of level to be one: its
    # ends no longer sit in the card beside them. Named, because the module's
    # docstring says which test refuses which roll.
    _r = find(TC.degrade(TC.early_look_screen(_pal), 'roll', strength=1.0))
    eq('...and at 2\u00b0 it is unsure too, for its button', (_r['sure'], _r['why']),
       (False, 'the band near the bottom is not set in a card \u2014 the card under '
               'a button, not the button'))
_r = find(TC.degrade(TC.early_look_screen(), 'roll', strength=0.25))
ok_('...while half a degree is still square enough to be sure of (%r)' % (_r['box'],),
    _r['sure'] and near(_r['box'][1], top_of(TC.EARLY_TOP)))

# --- glare: a reference per block, carried up the card --------------------------
#
# A glare blob lifts part of a card by tens of levels. Measured against one
# level for the whole screen and not followed up the card, a band of glare
# across the lower card ended the light card two per cent of the screen INTO
# the map above it — sure, square, and wrong — on 6 of the 432 glare and sheen
# frames this sweep is drawn from, and was sure of only 110 of them. Per block
# and followed: 348 sure, none wrong. The sheen frames that went wrong are held
# here; the blobs are held to being right whenever sure.
for _seed in range(3):
    _r = find(TC.degrade(TC.exclusive_screen(TC.DAY_CARD), 'sheen', seed=_seed, strength=1.4))
    ok_('a band of glare across a light card never makes a sure box that is wrong '
        '(seed %d: %r)' % (_seed, _r['box']),
        not _r['sure'] or near(_r['box'][1], top_of(TC.SHORT_TOP)))
_glared = _right = 0
for _seed in range(4):
    for _pal in (TC.NIGHT_CARD, TC.DAY_CARD, TC.NIGHT_ALL):
        _r = find(TC.degrade(TC.early_look_screen(_pal), 'glare', seed=_seed))
        if _r['sure']:
            _glared += 1
            _right += near(_r['box'][1], top_of(TC.EARLY_TOP))
ok_('a glare blob over the card leaves most of them sure (%d of 12)' % _glared,
    _glared >= 9)
eq('...and every sure one right', _right, _glared)

# --- the other things a windscreen does --------------------------------------
for _kind in ('blur', 'banding', 'shadow'):
    _r = find(TC.degrade(TC.early_look_screen(), _kind, seed=2))
    ok_('the dark card under %s is found at its own top (%r)' % (_kind, _r['box']),
        _r['sure'] and near(_r['box'][1], top_of(TC.EARLY_TOP)))
# A dimmed light card on a light map is 97 against 88: no edge to find, and
# it says so rather than guessing.
_r = find(TC.degrade(TC.early_look_screen(TC.DAY_CARD), 'dark'))
ok_('a dimmed light card on a light map is not guessed at (%r)' % _r['why'], not _r['sure'])

# --- DoorDash's stops card: a sheet under a map, its red pill at the bottom ------
#
# The owner's snaps of 31 Oct (testcards.dd_stores_screen; every store and
# street invented). Handed in grey, the finder was never sure of it: the pill's
# two reds are 28 grey levels apart, past BAR_STEP. Handed in colour, it is
# found by its red, walked up with DoorDash's own tolerances, and sure of the
# sheet's top — the row its map ends — with its bottom the top of the pill.
DD_PILL_TOP = 1965           # where dd_stores_screen draws the Accept pill


def colour(screen):
    return PL.resize_height(screen, READ_H)


def find_dd(screen, box=TC.BOX_DD_BELOW, grey_only=False):
    return CF.find_card(grey(screen) if grey_only else colour(screen), box)


DD_SCREENS = (('one customer', TC.dd_stores_screen()),
              ('two customers', TC.dd_stores_screen(
                  pay='$21.35', journey='4 stops (15.0 mi) • 53 min',
                  tail=('Multiple dropoffs (2 stops)', None))),
              ('dark mode', TC.dd_stores_screen(TC.DARK)))
for _name, _scr in DD_SCREENS:
    for _bn, _bx in (('just under the payout', TC.BOX_DD_BELOW),
                     ('flush on the payout', TC.BOX_DD_PAY)):
        _r = find_dd(_scr, _bx)
        _b = _r['box'] or [None] * 4
        ok_("DoorDash's stops card (%s), the box %s, is sure as DoorDash's sheet (%r)"
            % (_name, _bn, _r['why']), _r['sure'] and _r['why'] == CF.DD_SHEET)
        ok_('...its top the sheet\'s, where the map ends (%r)' % (_b[1],),
            near(_b[1], top_of(TC.DD_TOP)))
        ok_('...its bottom the top of the pill (%r)' % ((_b[1] or 0) + (_b[3] or 0),),
            near((_b[1] or 0) + (_b[3] or 0), top_of(DD_PILL_TOP)))
        ok_('...and its sides the screen\'s: the sheet runs edge to edge (%r)' % (_b[0],),
            near(_b[0], 0.0, 0.012) and near(_b[0] + _b[2], 1.0, 0.012))
_r = find_dd(DD_SCREENS[0][1], grey_only=True)
eq('...while handed it in grey, the finder says what it always said',
   (_r['sure'], _r['why']),
   (False, 'the band near the bottom is not solid — a picture, not a button'))

# The rig's map is 12 levels off the sheet (215 against 203 on the frames of
# 31 Oct), not dd_stores_screen's 22: inside WALK, so the walk the Uber cards
# get ran up the map to the top of the screen box on every one of them. Drawn
# here with the map 12 levels under the sheet's white.
_close = TC.dd_stores_screen(dict(TC.LIGHT, above=(243, 243, 243)))
_r = find_dd(_close)
ok_('a map only 12 levels off the sheet, as the rig sees it, still ends the walk at the '
    'sheet\'s top (%r)' % (_r['box'],),
    _r['sure'] and _r['why'] == CF.DD_SHEET and near(_r['box'][1], top_of(TC.DD_TOP)))
_b0 = CF.WALK
try:
    CF.WALK = CF.DD_WALK + 100           # any walk tolerance but DoorDash's own
    _r2 = find_dd(_close)
finally:
    CF.WALK = _b0
eq('...which is DD_WALK\'s doing, not WALK\'s: the Uber walk\'s tolerance is not used on it',
   (_r2['sure'], _r2['box']), (_r['sure'], _r['box']))

# What a windscreen does. The 12 frames the raise could not rescue in the
# last build were a light sheet in a left-hand shadow; the sheet is found
# under it now, by a reference per column (see cardfind._walk). (Its crop
# still reads no payout: the figure is in the deepest of the shadow. That is
# the reader's, in rpi/test_pipeline.py.) Under every degradation, sure means
# right.
_dd_sure = _dd_right = 0
for _name, _scr in DD_SCREENS:
    for _kind in ('glare', 'blur', 'shadow', 'sheen', 'banding'):
        for _seed in range(2):
            _r = find_dd(TC.degrade(_scr, _kind, seed=_seed))
            _dd_sure += _r['sure']
            _dd_right += bool(_r['sure'] and near(_r['box'][1], top_of(TC.DD_TOP)))
            if _kind == 'shadow' and _scr is not DD_SCREENS[2][1]:
                ok_('a light DoorDash sheet in a left-hand shadow (%s, seed %d) is found at its '
                    'top (%r)' % (_name, _seed, _r['why']),
                    _r['sure'] and near(_r['box'][1], top_of(TC.DD_TOP)))
# 25 of 30 when written. Not sure of: a light sheet under banding, all four
# (the stripes are 30 levels either way on white, so the walk at DD_WALK
# stops at the first one and the card would be 9% tall), and one glare blob
# on the dark sheet (its top spread past SQUARE).
ok_('DoorDash\'s sheet under glare, blur, shadow, sheen and banding: most sure (%d of 30)'
    % _dd_sure, _dd_sure >= 24)
eq('...and every sure one at the sheet\'s top', _dd_right, _dd_sure)

# A phone turned inside its box: the top slants and is refused, as on Uber's.
_r = find_dd(TC.degrade(DD_SCREENS[0][1], 'roll', strength=0.75))
ok_('a DoorDash sheet on a phone turned 1.5° inside its box is not sure (%r)' % _r['why'],
    not _r['sure'])
# A dimmed light sheet: the edge is under DD_WALK too, and it says so.
_r = find_dd(TC.degrade(DD_SCREENS[0][1], 'dark'))
ok_('a dimmed light DoorDash sheet is not guessed at either (%r)' % _r['why'],
    not _r['sure'] or near(_r['box'][1], top_of(TC.DD_TOP)))

# A card stacked above on the same sheet, no button of its own, a bigger
# payout: walked through, as Uber's stacked card is, to the upper card's top.
# What the picture shows; the reader refuses its two dollar figures
# (rpi/test_pipeline.py holds that the panel never sees $22.75).
_up = (762, [(782, 'Order in progress', 34, False), (872, '$22.75', 86, True)])
_r = find_dd(TC.dd_stores_screen(upper=_up))
ok_('a card stacked above the DoorDash card is one sheet with it, as on Uber\'s (%r)'
    % (_r['box'],), _r['sure'] and near(_r['box'][1], top_of(_up[0])))


def pill_painted(screen, bgr):
    """dd_stores_screen with its Accept pill painted one colour: the black of
    DoorDash's "Declined" state, or red right across the screen."""
    out = screen.copy()
    if bgr is None:                       # red edge to edge
        out[DD_PILL_TOP:DD_PILL_TOP + 176, :] = (36, 28, 232)
    else:
        mask = (np.abs(out[DD_PILL_TOP:DD_PILL_TOP + 176].astype(int)
                       - np.array([255, 255, 255])).sum(axis=2) > 60)
        out[DD_PILL_TOP:DD_PILL_TOP + 176][mask] = bgr
    return out


# Red is the whole of how the pill is known, so what is not a red pill is not
# one. "Declined": the pill turns black when the offer is gone (a 31 Oct
# frame), and the answer is the grey one, never DoorDash's sheet.
_r = find_dd(pill_painted(DD_SCREENS[0][1], (0, 0, 0)))
ok_('DoorDash\'s pill turned black ("Declined") is no red pill: never DoorDash\'s sheet (%r)'
    % _r['why'], _r['why'] != CF.DD_SHEET)
_r = find_dd(pill_painted(DD_SCREENS[0][1], None))
ok_('...nor is a red band from one side of the screen to the other (%r)' % _r['why'],
    _r['why'] != CF.DD_SHEET)

# And none of it touches an Uber screen: handed in colour, every Uber picture
# in this file gives the very answer it gave in grey. They have no red, so
# none of them gets past the pill; DoorDash's older card, red but one red and
# set in a card, is found by its button bar as it was.
_same = []
for _scr, _bx in ([(TC.early_look_screen(_p), BOX) for _p in (TC.NIGHT_CARD, TC.DAY_CARD,
                                                              TC.NIGHT_ALL)]
                  + [(TC.two_order_screen(), BOX), (TC.exclusive_screen(), BOX),
                     (TC.stacked_screen(), BOX), (TC.early_look_screen(TC.DAY_CARD, nav=True), BOX),
                     (TC.dash_stacked_screen(), TC.BOX_DASH),
                     (TC.dash_stacked_screen(TC.DASH_DAY), TC.BOX_DASH),
                     (without_button(TC.early_look_screen(), TC.NIGHT_CARD), BOX),
                     (TC.degrade(TC.early_look_screen(TC.DAY_CARD), 'roll', strength=1.0), BOX),
                     (TC.degrade(TC.early_look_screen(TC.DAY_CARD), 'dark'), BOX)]
                  + [(TC.degrade(TC.early_look_screen(_p), _k, seed=1), BOX)
                     for _p in (TC.NIGHT_CARD, TC.DAY_CARD)
                     for _k in ('glare', 'sheen', 'shadow', 'blur')]):
    _same.append(CF.find_card(colour(_scr), _bx) == CF.find_card(grey(_scr), _bx))
eq('every Uber picture, and DoorDash\'s older card, in colour is the answer it was in grey '
   '(%d pictures)' % len(_same), _same, [True] * len(_same))

# --- pure and cheap ------------------------------------------------------------
_g = grey(TC.early_look_screen())
_before = _g.copy()
_a, _b = CF.find_card(_g, BOX), CF.find_card(_g, BOX)
eq('the same picture twice is the same answer', _a, _b)
ok_('...and the picture handed in is not touched', np.array_equal(_g, _before))
_t = time.perf_counter()
for _ in range(5):
    CF.find_card(_g, BOX)
_ms = (time.perf_counter() - _t) * 200
ok_('a look costs tens of milliseconds, not a read\'s hundreds (%.1fms)' % _ms, _ms < 100)
# ...DoorDash's included: the grey look, then the pill and the walk again.
_c = colour(TC.dd_stores_screen())
_t = time.perf_counter()
for _ in range(5):
    CF.find_card(_c, TC.BOX_DD_BELOW)
_ms = (time.perf_counter() - _t) * 200
ok_('...and a look at DoorDash\'s sheet in colour too (%.1fms)' % _ms, _ms < 100)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d card finder checks passed' % ok)
sys.exit(1 if bad else 0)
