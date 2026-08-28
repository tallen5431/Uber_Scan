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

import testcards as TC
from testcards import mount, shop_screen, uberx_screen

if not TC.available():
    print('no PIL or no usable font — skipping the end-to-end money checks')
    sys.exit(0)

ok = bad = 0

W, H = TC.W, TC.H                 # a 19.5:9 phone, in its own pixels
SENSOR = TC.SENSOR                # what the camera hands the scanner


def eq(name, got, want):
    global ok, bad
    if got == want:
        ok += 1
    else:
        bad += 1
        print('FAIL  %s: got %r want %r' % (name, got, want))


def ok_(name, cond):
    eq(name, bool(cond), True)

def close(name, got, want, tol=0.01):
    global ok, bad
    if got is not None and abs(got - want) <= tol:
        ok += 1
    else:
        bad += 1
        print('FAIL  %s: got %r want %.4f' % (name, got, want))


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


# --- the third card shape, read from a picture ------------------------------
# A delivery card gives a deadline where the other two give a duration, and a
# distance standing on its own with no time beside it. Its fixtures in the
# shared corpus are *text*, so until this block every claim about reading one
# rested on a string somebody typed by hand — the parser was tested and the
# camera, the warp, the crop and the OCR engine were not. That is the wrong half
# to leave untested: this card is laid out unlike the others in exactly the ways
# the pipeline is sensitive to, with the payout pushed down under a banner and
# the whole card shorter, so the crop lands somewhere else.
#
# The clock is supplied, because a deadline is only a duration once something
# says what time it is. 18:29 against a 19:15 deadline is 46 minutes.
DELIVERY_SETTINGS = {'target': 25, 'band': 15, 'costPerMile': 0.30,
                     'pad': 0, 'secondsPerItem': 0, 'nowMinutes': 18 * 60 + 29}

for theme, pal in (('light', TC.LIGHT), ('dark', TC.DARK)):
    screen = TC.doordash_screen(pal)
    for width in (900, 1200, 1450):
        frame = mount(screen, width, seed=1)
        quad = PL.detect_screen_quad(frame)
        where = 'a delivery card in %s at %dpx' % (theme, width)
        eq(where + ' / the screen is found', quad is not None, True)
        if quad is None:
            continue
        scanner = PL.Scanner(quad=quad, card_height=900,
                             settings=DELIVERY_SETTINGS)
        acc = OfferAccumulator()
        out = scanner.read(frame, now=100.0)
        parsed = acc.add(out['parsed'], now=100.0)

        eq(where + ' / payout', parsed['pay'], 41.11)
        eq(where + ' / the lone distance', parsed['miles'], 9.8)
        eq(where + ' / the deadline, in minutes since midnight',
           parsed['deliverBy'], 19 * 60 + 15)
        eq(where + ' / no duration is invented', parsed['minutes'], None)
        # It survives the merge complete — the rule that lost every one of these
        # cards for a while lived in the accumulator, not the parser.
        eq(where + ' / complete after merging', parsed['complete'], True)
        eq(where + ' / and finished, so it can be spoken',
           OP.is_whole(parsed), True)

        rate = OP.rate(parsed, DELIVERY_SETTINGS)
        eq(where + ' / a verdict is reached', rate['ready'], True)
        if not rate['ready']:
            continue
        eq(where + ' / the duration comes from the deadline',
           rate['cardMinutes'], 46.0)
        eq(where + ' / ...and says so', rate['fromDeadline'], True)
        # $41.11 less 9.8 miles at 30c, over 46 minutes.
        close(where + ' / $ per hour', rate['perHour'], (41.11 - 2.94) / (46 / 60.0))
        close(where + ' / what was deducted', rate['cost'], 2.94)
        eq(where + ' / the verdict', rate['state'], 'go')

# --- and what happens when the picture is bad -------------------------------
# The rule this project is built on is that a confidently wrong number is far
# worse than no number, and this is the only place it can be checked as a
# property rather than asserted as an intention: put every card shape through
# every way a real frame goes wrong, and require that each reading is either
# right or refused. Never a third thing.
#
# Measured while writing this: glare, softness and a dim cabin cost nothing on
# any of the three shapes, and a screen rippling against the shutter takes them
# all down — Uber at amplitude 18, the delivery card not until 30, because it
# has fewer small lines to lose. Every one of those failures came back as no
# payout at all. That is the direction that must hold.


def _glare(f, strength=110):
    """A band of windscreen reflection across the middle of the card."""
    out = f.astype(np.float32)
    h, w = f.shape[:2]
    yy = np.mgrid[0:h, 0:w][0]
    band = np.exp(-((yy - h * 0.52) ** 2) / (2 * (h * 0.06) ** 2))
    return np.clip(out + (band * strength)[:, :, None], 0, 255).astype(np.uint8)


def _soft(f):
    """The mount shaken by a pothole, or a focus that has drifted."""
    return cv2.GaussianBlur(f, (5, 5), 0)


def _dim(f):
    """A phone that has dimmed itself, or a night shift."""
    return np.clip(f.astype(np.float32) * 0.45, 0, 255).astype(np.uint8)


def _ripple(f, amp=30):
    """The screen's refresh beating against the camera's exposure.

    The fault the flicker-safe exposure exists to avoid, at an amplitude past
    what a correctly exposed rig produces — so this is the failure case, and
    what is asserted is only that it fails the right way.
    """
    out = f.astype(np.float32)
    wave = (np.sin(np.arange(f.shape[0]) / 3.0) * amp)[:, None, None]
    return np.clip(out + wave, 0, 255).astype(np.uint8)


def _too_bright(f, times=3.0):
    """The driver turned their phone's brightness up.

    The complaint this file's whole matrix exists to answer, and the one
    condition that was not in it. Modelled the way a sensor actually fails
    rather than as a multiply: charge that will not fit in a well spills into
    the neighbours and the lens veils the frame with a share of its own light,
    which is what eats the thin strokes of a payout. A bare multiply leaves
    black text perfectly black however blown out the white is, and would have
    made this look like a condition the reader shrugs off.
    """
    lit = f.astype(np.float32) * times
    over = np.maximum(lit - 255.0, 0.0)
    lit = lit + cv2.GaussianBlur(over, (0, 0), 9) * 0.55
    return np.clip(lit, 0, 255).astype(np.uint8)


ROUGH = [('glare', _glare), ('soft', _soft), ('a dim cabin', _dim),
         ('a phone turned right up', _too_bright),
         ('a rippling screen', _ripple)]
# Every figure each card was drawn from, not only its payout. The property
# below used to check the pay alone, and the comment above it called that "the
# payout the card was drawn from" — but the number on the screen is pay divided
# by time, less distance times cost, so checking one third of the inputs checks
# none of the answer. It let through a real one: a card three times too bright
# read `20 min (7.3 m1) trip`, contributed that leg's twenty minutes and none of
# its distance, and reached a confident $41.01/hr on 1.1 of its 8.4 miles —
# missing miles being missing cost, so the error ran optimistic.
SHAPES = [('a ride card', uberx_screen(), 16.05, 23.0, 8.4, PROFILES[0][1]),
          ('a shop order', shop_screen(), 7.09, 34.0, 3.6, PROFILES[0][1]),
          ('a delivery card', TC.doordash_screen(), 41.11, None, 9.8,
           DELIVERY_SETTINGS)]

for label, screen, true_pay, true_min, true_miles, settings in SHAPES:
    for cond, damage in ROUGH:
        frame = damage(mount(screen, 1200, seed=1))
        quad = PL.detect_screen_quad(frame)
        where = '%s under %s' % (label, cond)
        if quad is None:
            ok += 1                     # refusing to find the screen is a refusal
            continue
        scanner = PL.Scanner(quad=quad, card_height=900, settings=settings)
        out = scanner.read(frame, now=100.0)
        parsed = out['parsed']
        rate = OP.rate(parsed, settings)
        # The whole property, in one line: a verdict may only be reached on the
        # figures the card was drawn from — all of them, since all of them are
        # in the answer. Anything else has to be a refusal.
        #
        # A distance the reading itself calls uncertain is not "something else":
        # rate() charges no mileage for it, the page says so, and the reading is
        # not whole, so the loop keeps looking. What is forbidden is a wrong
        # number presented as a right one.
        agrees = (parsed['pay'] == true_pay
                  and (true_min is None or parsed['minutes'] == true_min)
                  and (true_miles is None or parsed['miles'] == true_miles
                       or parsed['milesUncertain']))
        ok_(where + ' / is right, or says nothing — never something else',
            (not rate['ready']) or agrees)

# --- a rate with no running cost off it is a ceiling, not the offer ---------
#
# `target` is a NET line, set against rates with running costs already taken
# off. When no cost could be taken off, `perHour` is gross and is therefore an
# upper bound — it may clear the target, it may be nowhere near it, and the rig
# cannot tell which. On the owner's own shift of 202 offers, 108 were rated
# that way and 33 of the 35 ACCEPTs came out of that pool; 20 of them fall
# below the target once the distance printed on the card is charged.
#
# The property that matters is that the cap only ever moves a verdict DOWN. A
# guard that could raise one would be a new way to manufacture the ACCEPT it
# exists to prevent.
RANK = {'no': 0, 'warn': 1, 'go': 2}
SETTINGS = {'target': 25, 'band': 15, 'costPerMile': 0.30}
FREE = {'target': 25, 'band': 15, 'costPerMile': 0}


def priced(pay, minutes, miles, uncertain):
    return {'pay': pay, 'minutes': minutes, 'miles': miles,
            'milesUncertain': uncertain, 'milesCorrected': False, 'items': None,
            'legs': 2, 'deliverBy': None, 'shop': None, 'complete': True}


# The guarantee is narrower than "never more confident", and the first version
# of this block asserted the wider one and failed — correctly. An uncosted rate
# is a HIGHER number, so it lands in a higher band: $16.05 over 34 minutes and
# 33.7 miles is $10.48/hr costed and $28.32/hr uncosted, a clear PASS reading as
# a CLOSE CALL. No cap can fix that while still showing the number, because the
# number really is all the rig knows.
#
# What it CAN guarantee is that an upper bound never earns the one verdict that
# tells a driver to take the job. That is the property here. The residual — a
# pass reading as a close call — is counted rather than hidden, and the way to
# shrink it is to charge the partial distance rather than none, which is a
# change to the cost model and not to this guard.
promoted_to_go = 0
lowered = raised = capped = 0
for pay in (2.0, 5.0, 8.04, 12.0, 16.05, 24.08, 41.06):
    for minutes in (11.0, 20.0, 34.0, 60.0, 90.0):
        for miles in (None, 1.0, 5.2, 12.4, 33.7):
            with_cost = OP.rate(priced(pay, minutes, miles, False), SETTINGS)
            without = OP.rate(priced(pay, minutes, miles, True), SETTINGS)
            if not (with_cost.get('ready') and without.get('ready')):
                continue
            # Same card, same settings; the only difference is whether the
            # distance could be used. The uncosted one may never be the more
            # confident of the two.
            a = RANK.get(with_cost['state'])
            b = RANK.get(without['state'])
            if a is None or b is None:
                continue
            if b > a:
                raised += 1
                if without['state'] == 'go':
                    promoted_to_go += 1
            elif b < a:
                lowered += 1
            if without['state'] == 'warn' and without['perHour'] >= 25:
                capped += 1

eq('an upper bound never earns the verdict that says take it',
   promoted_to_go, 0)
ok_('...and the guard is doing something, not nothing', lowered > 0)
# Named, not hidden: a rate the rig cannot cost still reads a band too high.
ok_('...though %d of these still read a band high, which charging the partial'
    ' distance rather than none would shrink' % raised, raised > 0)
ok_('...capping rates that would have cleared the target (%d of them)' % capped,
    capped > 0)

# The driver who sets no cost per mile has opted out of costing, so gross IS
# net and there is nothing to cap. Capping there would punish a setting.
free_go = OP.rate(priced(9.08, 20.0, 5.2, True), FREE)
eq('with no cost per mile set there is nothing missing, so no cap',
   free_go['state'], 'go')
ok_('...and nothing claims a cost was skipped', not free_go['uncosted'])

# ...and the same card with the cost configured is the capped one.
capped_go = OP.rate(priced(9.08, 20.0, 5.2, True), SETTINGS)
eq('the same card with a cost per mile set is a close call',
   capped_go['state'], 'warn')
ok_('...and says the rate is a ceiling', capped_go['uncosted'])
eq('...while the number itself is unchanged',
   round(capped_go['perHour'], 2), round(free_go['perHour'], 2))

# Below the floor it stays a pass. The cap lowers a green light to a close
# call; it must not raise a pass into one.
poor = OP.rate(priced(4.05, 40.0, 12.0, True), SETTINGS)
eq('an uncosted rate below the floor is still a pass', poor['state'], 'no')
ok_('...though it still says no cost came off', poor['uncosted'])

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d end-to-end money checks passed' % ok)
sys.exit(1 if bad else 0)
