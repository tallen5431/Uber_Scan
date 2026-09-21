"""What the offers page SAYS, as opposed to how it is laid out.

    python3 rpi/test_offerspage.py

rpi/test_layout.py loads this page at six panel sizes and measures whether it
fits and whether it can be read. Nothing checked what it claimed. That gap is
where three faults lived, all of them the same shape — a sentence about the
data that the data does not support:

  * A journal that exists and could not be opened rendered byte-identically to
    a quiet week, both of them ending "If you have been driving and it is still
    empty, the rig is reading nothing — the live view will say why." The server
    had already worked out which it was and sent `unreadable`; the page read
    that field only on a path the empty case returns before reaching.

  * The headline said "You marked 6 as taken, worth $59.93 after running costs"
    and the day header, for the same six offers, said "took 6 for $73.70" —
    23% apart, and structurally always on screen together.

  * A window whose only rows were hidden said nothing about the hiding and
    blamed the camera instead.

So the page is driven in a real browser with `fetch` replaced before its script
runs, and fed the exact JSON /api/journal emits. Nothing here is about pixels;
it is about whether a driver reading the page is told the truth.

Skipped where a browser cannot be had, the same way the other browser checks
skip.
"""

import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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


def no_(name, cond):
    eq(name, bool(cond), False)


def skip(why):
    print('%s — skipping the offers-page checks' % why)
    sys.exit(0)


def hung(stage):
    """A driver that stopped is a FAILED suite, not a skipped one.

    `skip` is for a machine that cannot run these at all — no chromium — where
    exiting 0 is right, because nothing was learned and nothing was broken. A
    driver that hung is the opposite: it reached some particular control and
    waited for it until the watchdog gave up, which is a fact about the page,
    and it used to report that by exiting 0. tools/test.sh then counted the
    suite as passed with none of its checks run.

    Not hypothetical — it happened to the dashboard suite the day this was
    written, hiding a real regression behind "all 37 suites passed".
    """
    print('FAIL  the driver hung in "%s" — none of the %s checks ran'
          % (stage, 'offers-page'))
    print('\n%d passed, %d FAILED' % (ok, bad + 1))
    sys.exit(1)


NOW = 1700000000000

# Six offers taken out of twelve, with a running cost on each — the shape that
# made the headline and the day line disagree. The numbers are chosen so the
# gap is unmissable: $2.00 of cost against $10.00 of pay, six times over, is
# $48.00 net against $60.00 gross — and across all twelve, $96.00 against
# $120.00.
def offer(i, accepted=False, cost=2.0, pay=10.0, minutes=20.0, state=None,
          places=None, hidden=False, suspect=False, text=None, per_mile=0.33,
          pickup=None, dropoff=None, scanned=False, shop=False, items=None,
          legs=None):
    row = {
        'id': 'r%d' % i, 'at': NOW - i * 600000, 'firstAt': NOW - i * 600000,
        'pay': pay, 'minutes': minutes, 'miles': 6.0,
        'perHour': round((pay - cost) / (minutes / 60.0), 2),
        'grossPerHour': round(pay / (minutes / 60.0), 2),
        'cost': cost, 'costPerMile': per_mile, 'target': 25, 'band': 15,
        'legs': 2, 'whole': True, 'accepted': accepted,
    }
    # What the panel printed in the car at the time, which is what "What you
    # took" groups by. Left off entirely by default, because rows written
    # before the field existed are exactly the case the fourth bar is for —
    # and TOOK_SIX below is what proves those rows are not silently dropped.
    if state is not None:
        row['state'] = state
    if places is not None:
        row['places'] = places
    if hidden:
        row['hidden'] = True
    if suspect:
        row['suspect'] = True
    if text is not None:
        row['text'] = text
    # The two ends as the card named them, and the position the rig's GPS had
    # when it read the card. Both are what the map sheet is built out of: the
    # names are what gets searched, and the fix is what the search is boxed
    # around.
    if pickup is not None:
        row['pickup'] = pickup
    if dropoff is not None:
        row['dropoff'] = dropoff
    if scanned:
        row['dropoffScanned'] = True
    # What the card called itself, and what the OCR happened to read off it.
    # Two different facts, written the way the two writers write them: the shop
    # chip is True or absent (rpi/journal.py writes `True if ... else None`,
    # journal-client.js writes `parsed.shop ? true : null`, and the parser
    # emits only True or None), and the item count is a number or absent.
    if shop:
        row['shop'] = True
    if legs is not None:
        row['legs'] = legs
    if items is not None:
        row['items'] = items
    return row


TOOK_SIX = [offer(i, accepted=(i < 6)) for i in range(12)]

# What the panel said about the jobs that were actually worked. Every group has
# its own median so a bar built from the wrong pile cannot land on the right
# number by accident: ACCEPT $30 and $36 -> $33, CLOSE $24 twice -> $24, PASS
# one at $18. One ticked row is hidden, so six were ticked and five can be
# counted, and the heading has to say so rather than print five under a
# headline that says six.
VERDICTS = [
    offer(0, accepted=True, pay=12.0, state='go'),      # $30/hr
    offer(1, accepted=True, pay=10.0, state='warn'),    # $24/hr
    offer(2, accepted=True, pay=10.0, state='warn'),    # $24/hr
    offer(3, accepted=True, pay=8.0, state='no'),       # $18/hr
    offer(4, accepted=True, pay=14.0, state='go'),      # $36/hr
    offer(5, pay=10.0, state='go'),                     # cleared, never ticked
    offer(6, accepted=True, pay=10.0, state='go', hidden=True),
    offer(7, pay=10.0, state='no'),
    # ...and one typed on the keypad. No verdict recorded, not ticked, so it
    # lands under no chip but All — and its row has to say what it is.
    dict(offer(8, pay=10.0), typed=True),
]

# Five offers through Chattanooga, of which four can be counted and three were
# worked; one job on its own in Soddy Daisy; two in Dalton that were set aside
# and so have no rate to give at all.
#
# The fifth Chattanooga row is the point of the set: it was ticked — the driver
# took that job — and the scanner misread it, so it is set aside. Every figure
# in the sentence has to be over the four that could be counted and not over
# the five that matched, and it is only a mixed set that can tell the two
# apart. Sorted, the four are [$24, $24, $30, $30] and interpolate to $27; put
# the misread $84 back in and the median moves to $30, three clear $25 instead
# of two, and the money taken goes from $18.00 to $46.00.
SEARCHABLE = [
    offer(0, accepted=True, pay=12.0, state='go',
          places=['Chattanooga TN', 'Ringgold GA']),
    offer(1, accepted=True, pay=10.0, state='warn',
          places=['Chattanooga TN', 'Fort Oglethorpe GA']),
    offer(2, pay=12.0, state='go', places=['Chattanooga TN', 'Hixson TN']),
    offer(3, pay=10.0, state='warn', places=['East Ridge TN', 'Chattanooga TN']),
    offer(4, pay=14.0, state='go', places=['Soddy Daisy TN']),
    offer(5, pay=10.0, state='no', places=['Dalton GA'], suspect=True),
    offer(6, pay=10.0, state='no', places=['Dalton GA'], suspect=True),
    offer(7, pay=10.0, state='no'),
    # ...and the misread one carries what the reader actually read, with a
    # '<' in it, because OCR off a photograph of a phone can contain anything
    # and this is the first card text to reach innerHTML on this page.
    offer(8, accepted=True, pay=30.0, places=['Chattanooga TN'], suspect=True,
          text='Deliver by 7:42 PM\n$30.00 <total>\n20 min\nChattanooga TN'),
]

# Four ordinary offers and one the rig stamped past the end of time. The four
# are three hours apart so they fall in four different blocks of the
# by-time-of-day chart, which is what makes "the chart still drew" a claim
# about the chart rather than about one bar.
NO_CLOCK = [offer(200 + i, pay=12.0 + i, state='go') for i in range(4)] + [
    offer(209, pay=20.0, state='go'),
]
for _i in range(4):
    NO_CLOCK[_i]['at'] = NO_CLOCK[_i]['firstAt'] = NOW - _i * 3 * 3600000
NO_CLOCK[4]['at'] = NO_CLOCK[4]['firstAt'] = 1e20

# Typed into the box on the page, in this order, against SEARCHABLE.
QUERIES = ['chattanooga', 'soddy', 'dalton', 'nowhere at all']

# Three weeks, one offer a day at noon UTC — noon so that neither the 4am
# shift boundary nor a browser in another zone can move a row to the next
# date — with the pay set by the weekday, so every bar of the day-of-week
# chart has three identical rates under it and its median is exactly that
# number: $18 + $6 per weekday, Sunday first, so Sunday $18, Monday $24 ... a
# Saturday $54. Three rows per weekday because the check is on the median,
# and a median of three equal numbers cannot be interpolated into a
# coincidence.
import datetime as _dt
NOON = NOW - 10 * 3600000           # NOW is 22:13 UTC; this is 12:13 UTC
def _js_weekday(at_ms):
    """getDay(): Sunday is 0. Python's weekday() puts Monday at 0."""
    return (_dt.datetime.utcfromtimestamp(at_ms / 1000).weekday() + 1) % 7
WEEKS = [
    offer(100 + d, pay=8.0 + 2 * _js_weekday(NOON - d * 86400000), state='go')
    for d in range(21)
]
for _i, _r in enumerate(WEEKS):
    _r['at'] = _r['firstAt'] = NOON - _i * 86400000
# ...plus two rows that only the right grouping gets right.
#
# One at 1am on the first Sunday of the window. The calendar calls that
# Sunday; the driver's day, bounded at 4am, calls it Saturday night, which is
# what it was — so it belongs under Sat, at Saturday's pay, and Sat carries
# four rows to Sunday's three. Grouped on the calendar it would land the other
# way round.
_first_sun = next(r for r in WEEKS if _js_weekday(r['at']) == 0)
_late = offer(140, pay=8.0 + 2 * 6, state='go')
_late['at'] = _late['firstAt'] = _first_sun['at'] - 11 * 3600000   # 01:13 UTC Sun
WEEKS.append(_late)
# Three set-aside Wednesdays at an impossible rate. The chart is drawn over
# the COUNTED offers, like every other chart on the page; over the raw window
# these would drag Wednesday from $36 to $168.
for _k in range(3):
    _bad = offer(150 + _k, pay=102.0, state='go', suspect=True)
    _wed = next(r for r in WEEKS if _js_weekday(r['at']) == 3)
    _bad['at'] = _bad['firstAt'] = _wed['at'] + (_k + 1) * 600000
    WEEKS.append(_bad)

# The same three weeks with one row stamped past the end of time.
#
# NO_CLOCK above holds such a row too, and cannot reach this: its four
# readable rows are three hours apart, so the window is one day, `enoughDays`
# is false and the day-of-week pass never runs. The two conditions — a
# fortnight of days AND a stamp no clock can read — were never in one feed,
# and the pass that needs both walked `offers` and indexed `week` with
# `dayOf(at).getDay()`, which is NaN. `week[NaN]` is undefined, the push threw
# inside a .then(), and load()'s .catch() painted "Cannot reach the scanner"
# over a journal the server had read perfectly: headline, both charts, the
# week chart, "What you took", the whole log and every caveat line gone, with
# nothing in the console.
#
# WEEKS itself is left clean on purpose — it is the control for "a window with
# no such row says nothing about one", and every bar of it is asserted below.
# This feed must produce the same seven bars, which is what makes it a check
# on the row being SKIPPED rather than on the page merely surviving.
WEEKS_NO_CLOCK = [dict(r) for r in WEEKS]
_wk_poison = offer(160, pay=20.0, state='go')
_wk_poison['at'] = _wk_poison['firstAt'] = 1e20
WEEKS_NO_CLOCK.append(_wk_poison)

# ...and a ticked job with offers inside its stated minutes, one of which was
# itself ticked. `offer(i)` is spaced ten minutes apart and counts BACKWARDS
# from NOW, so a 30-minute job at index 5 covers indices 4, 3 and 2.
BUSY_JOB = dict(offer(5, accepted=True), minutes=30.0, pay=16.05,
                perHour=26.0, id='thejob')
INSIDE = [dict(offer(4), id='in-a'),
          dict(offer(3, accepted=True), id='in-b'),   # a stack: ticked as well
          dict(offer(2), id='in-c')]
OUTSIDE = [dict(offer(0), id='after'), dict(offer(11), id='before')]
BUSY_ROWS = [BUSY_JOB] + INSIDE + OUTSIDE

# One pairing, so the section that reads the stacking record is exercised by
# something other than the layout file.
PAIR = {
    'v': 1, 'kind': 'pair', 'at': NOW - 300000, 'id': 'r0',
    'held': {'pay': 12.0, 'minutes': 30, 'dropoff': 'Oak Ln, Marietta',
             'scanned': True, 'heldMs': 600000},
    'offer': {'pay': 9.0, 'minutes': 20, 'dropoff': 'Chastain Rd NW, Kennesaw',
              'pickup': None},
    'stack': {'pay': 17.4, 'worst': 26.1, 'best': 34.8, 'leftMinutes': 20,
              'minMinutes': 20, 'maxMinutes': 40, 'state': 'go', 'sure': True,
              'ends': 'elsewhere', 'uncosted': False},
    # The row saying its verdict really is the one the panel showed. Every pair
    # row written before recordPairing got the driver's target off the reading
    # has this absent, and `state` on those is a constant 'go' — see UNJUDGED
    # below and saidWords() in journal.html.
    'judged': True,
}

# ...and one of those older rows, which are all still on disk. The page may not
# report its `state` as a word the panel used, because the panel did not use
# it: the verdict was computed against a target of zero, which everything
# clears. What the row CAN still be asked is the pair's own figures.
UNJUDGED = dict(PAIR, id='r1', at=NOW - 600000)
UNJUDGED.pop('judged')

# The pair whose unhedged claim the panel declined to make.
#
# `sure` has three values and the page had two branches: `sure ? 'yes, even
# sharing no road at all' : 'no — the worst end is below finishing alone'`.
# Null is WITHHELD — the offer card printed no chargeable distance, so the
# pair's rate is a ceiling and `alone` is a net rate, and the two are
# different kinds of money — and it was printed as the no, which is not a
# hedge but the opposite of what was withheld. Of the (held, gross-offer)
# pairs drawable from the owner's own week, 77.4% have worst >= alone.
#
# `uncosted` is true here and on nothing else in this feed, which is what
# makes it the ceiling case rather than a second copy of PAIR.
WITHHELD = dict(PAIR, id='r2', at=NOW - 900000,
                stack=dict(PAIR['stack'], sure=None, uncosted=True))
# ...and the one that really is a no, which is how the branch above is told
# apart from a page that simply stopped answering. Costed on both sides, so
# nothing about it is a ceiling.
SAID_NO = dict(PAIR, id='r3', at=NOW - 1200000,
               stack=dict(PAIR['stack'], sure=False, worst=9.0, state='no'))

# Dots and rankings. The newest row was judged at a lower target than the
# rest, so re-judging a row against "today's" target would colour it
# differently from the verdict it records; and the misread every real journal
# carries — $1,184 for twenty minutes — led every ranking until rankings
# learned to leave set-aside rows at the bottom.
DOTS = [offer(101, pay=12.0, state='go'),              # $30/hr at 25
        offer(102, pay=8.0, state='no'),               # $18/hr: PASS at 25, ACCEPT at 18
        offer(103, pay=9.0, state='warn'),             # $21/hr
        offer(104, pay=1184.0, state='go', suspect=True),
        offer(100, pay=12.0, state='go')]              # newest, target 18
# Last in the feed and a minute old: the page takes its target from the
# most recent row that is not in the future, in feed order.
DOTS[-1]['at'] = DOTS[-1]['firstAt'] = NOW - 60000
DOTS[-1]['target'] = 18

# Runs of scanning: twelve stretches three hours apart, three cards five
# minutes apart in each, and three such stretches for the small case. The
# chart shows the latest eight and offers the rest, and the way it says so
# has to be read back rather than assumed.
def _runs(count):
    rows = []
    for k in range(count):
        for j in range(3):
            r = offer(200 + k * 3 + j, pay=9.0 + k, state='go')
            r['at'] = r['firstAt'] = NOW - (k * 3 * 3600000 + (2 - j) * 300000)
            rows.append(r)
    return rows


RUNS = _runs(12)
FEW_RUNS = _runs(3)

# Two writers, one file. The rig seeds a new config at $0.30/mi and subtracts
# it; the keypad and the phone's own scanner default to zero and subtract
# nothing. Both post through /api/journal/ingest into the same journal, so a
# window can hold four net rates and three gross ones — and the page used to
# describe all seven with whichever kind happened to be newest.
#
# The rows here are built so the two piles cannot be told apart by their pay:
# every one is $10.00 over twenty minutes. Only the subtraction differs, which
# is what makes a median over the seven a median over two different quantities.
MIXED_COST = ([offer(i, cost=1.80, per_mile=0.30, state='go') for i in range(4)]
              + [offer(4 + i, cost=0.0, per_mile=0.0, state='go')
                 for i in range(3)])

# ...and the shape that made the sentence count the rows it had just excluded.
#
# Four counted rows, every one of them net at $0.30/mi, and two SET ASIDE rows
# off the keypad at nothing. The note directly above this one says those two
# are "left out of the figures above" — and this one was handed the whole
# window rather than the counted part, so it described four net rates as "4 of
# these 6 ... so the figures above mix what offers paid before the car with
# what they paid after it". The figures above mix nothing: they are four net
# rates. The denominator was wrong by the set-aside count on every window that
# had one (26 of 1,166 on the owner's own week), and here the conclusion is
# wrong too, which is what makes this the fixture rather than MIXED_COST.
ASIDE_COST = ([offer(i, cost=1.80, per_mile=0.30, state='go') for i in range(4)]
              + [offer(4 + i, cost=0.0, per_mile=0.0, state='go', suspect=True)
                 for i in range(2)])

# Rides, shop orders, and the cards that said neither.
#
# The three bars are meant to split on what the CARD called itself. The rule
# shipped was `r.shop ? Shop : r.legs >= 2 ? Rides
#                    : (typeof r.shop === 'boolean' || r.items) ? Shop
#                    : Not stated`, and its `typeof` clause is unreachable —
# it needs r.shop falsy AND a boolean, i.e. exactly `false`, which no writer
# can produce (measured over the owner's week: 1,133 rows with no shop field,
# 33 with a truthy one, none with a false one). So what actually decided it
# was `r.items`: a fact about the OCR, and the one thing the comment above the
# chart says it is not splitting on. rate()'s own comment records DoorDash
# printing "4 items" on a restaurant pickup nobody shops for.
#
# Measured on the replayed week: the shipped rule gave Shop 49 rows at a
# median of $12.42, 26 of them — 53% of the bar — single-leg cards never
# called shop orders. On the chip alone it is 23 rows at $11.05.
#
# Here: two real shop cards at $24/hr, two two-leg rides at $36/hr, and two
# single-leg cards carrying an item count and no chip, at $60/hr. The rates
# are far enough apart that a bar holding the wrong pile cannot land on the
# right median.
KINDS = [
    offer(0, pay=10.0, state='go', shop=True, items=12, legs=1),
    offer(1, pay=10.0, state='go', shop=True, items=8, legs=1),
    offer(2, pay=14.0, state='go', legs=2),
    offer(3, pay=14.0, state='go', legs=2),
    offer(4, pay=22.0, state='go', items=4, legs=1),
    offer(5, pay=22.0, state='go', items=4, legs=1),
]

# Cards that named where they went, which is what the map sheet is for.
#
# Three shapes, and the page has to tell them apart. A job with both ends. A
# job the card only named one end of — Uber prints "Customer dropoff" and no
# address until you accept, which is most of this driver's traffic. And a job
# whose dropoff the geocoder cannot place at all, which is what a badly
# misread street looks like from here.
#
# The first two carry a GPS fix, so their lookups get boxed around where the
# car actually was; the third deliberately does not, so the case of a place
# with no anchor is on the page too.
MAPPED = [
    dict(offer(0, state='go', pickup='Chastain Rd NW, Kennesaw',
               dropoff='Oak Ln, Marietta'), lat=34.02, lon=-84.61),
    dict(offer(1, state='warn', pickup='Chastain Rd NW, Kennesaw'),
         lat=34.02, lon=-84.61),
    offer(2, state='no', pickup='Chastain Rd NW, Kennesaw',
          dropoff='Zzqx Nowhere Blvd'),
    # A card that printed "Customer dropoff" and no address, whose destination
    # the driver revealed on their phone and had the rig read. The only reason
    # this row has an end at all.
    dict(offer(3, state='go', pickup='Chastain Rd NW, Kennesaw',
               dropoff='Oak Ln, Marietta', scanned=True),
         lat=34.02, lon=-84.61),
    # The same two ends, three miles apart on the card and four and a half on
    # the map — which the sheet used to answer with "one of these pins is
    # wrong". This reading is `suspect`: the rig is not standing behind its own
    # figures, so three miles is not a distance a straight line can be measured
    # against, and losing that comparison says nothing about either pin.
    dict(offer(4, state='no', pickup='Chastain Rd NW, Kennesaw',
               dropoff='Oak Ln, Marietta', suspect=True),
         miles=3.0),
]

# The four answers /api/journal can give. Every field here is one the server
# actually sends — see the send() call in the /api/journal branch.
# A market the advice answers, whose line moves as the recording is cut a
# different way.
#
# `stable` is not "the line did not move" — it allows the recommended figure to
# wander by UNSTABLE_SPREAD across the six thresholds, which is $6. This one
# uses the whole allowance: $24 at the two shortest cuts and $30 at the other
# four. The page printed "The same line comes out however the recording is
# split into runs, which is why it is worth acting on" over exactly that, in
# the sentence that tells the driver why to trust the number.
#
# Built from a fixed LCG rather than by hand because the case needs a hundred
# offers with enough variety to move the plateau, and a hundred rows written
# out would be a wall nobody could check. What matters is that the numbers do
# not change between runs and that the market really does land in this state —
# which the checks below assert rather than assume.
def wobbly(seed=73, n=120, step=8.0):
    rows, s = [], seed
    for i in range(n):
        s = (s * 1103515245 + 12345) % 2147483648
        r = s / 2147483648.0
        mins = 10 + int(r * 30)
        pay = 4 + int(r * r * 4000) / 100.0
        at = NOW + int((i * step + r * step * 2) * 60000)
        rows.append({'id': 'w%d' % i, 'at': at, 'firstAt': at,
                     'pay': pay, 'minutes': float(mins), 'miles': 6.0,
                     'perHour': round(pay / (mins / 60.0), 2),
                     'grossPerHour': round(pay / (mins / 60.0), 2),
                     'cost': 0.0, 'costPerMile': 0.0, 'target': 25, 'band': 15,
                     'legs': 2, 'whole': True, 'accepted': False})
    return rows


WOBBLY = wobbly()

FEEDS = {
    'a line that moves': {
        'count': len(WOBBLY), 'total': len(WOBBLY), 'truncated': False,
        'days': 30, 'hidden': 0,
        'watched': {'saw': len(WOBBLY), 'kept': len(WOBBLY)},
        'unreadable': None, 'pairs': [], 'offers': WOBBLY},
    'busy': {'count': len(BUSY_ROWS), 'total': len(BUSY_ROWS), 'truncated': False,
             'days': 7, 'hidden': 0, 'watched': {'saw': 6, 'kept': 6},
             'unreadable': None, 'pairs': [], 'offers': BUSY_ROWS},
    'took six': {'count': 12, 'total': 12, 'truncated': False, 'days': 7,
                 'hidden': 0, 'watched': {'saw': 14, 'kept': 12},
                 'unreadable': None, 'pairs': [PAIR, UNJUDGED], 'offers': TOOK_SIX},
    # The three answers `sure` has, in one window. Its own feed rather than
    # more rows on 'took six', whose tally of what the panel said is asserted
    # row by row and would be measuring two things at once.
    'stack claim': {'count': 12, 'total': 12, 'truncated': False, 'days': 7,
                    'hidden': 0, 'watched': {'saw': 12, 'kept': 12},
                    'unreadable': None,
                    'pairs': [PAIR, WITHHELD, SAID_NO], 'offers': TOOK_SIX},
    'verdicts': {'count': len(VERDICTS), 'total': len(VERDICTS),
                 'truncated': False, 'days': 7, 'hidden': 1,
                 'watched': {'saw': 8, 'kept': 8},
                 'unreadable': None, 'pairs': [], 'offers': VERDICTS},
    # A window with rows and nothing countable in it: three misreads. The
    # page takes its "nothing usable" path here, which used to build its own
    # list and ignore the chips, the order and the search box.
    'all aside': {'count': 3, 'total': 3, 'truncated': False, 'days': 7,
                  'hidden': 0, 'watched': {'saw': 3, 'kept': 3},
                  'unreadable': None, 'pairs': [],
                  'offers': [offer(0, pay=1030.0, state='no', suspect=True),
                             offer(1, accepted=True, pay=1184.0, suspect=True),
                             offer(2, pay=1251.0, state='no', suspect=True)]},
    # A row the panel refused because the card showed a leg it could not time.
    # Every figure in it is one the card printed, so nothing about its SIZE is
    # wrong — which is exactly why it may not borrow the sentences written for
    # rows whose figures are out of range, nor the one about a crop that
    # clipped the card. Beside it, an ordinary row, so a page that explained
    # everything this way would be caught too.
    'leg': {'count': 2, 'total': 2, 'truncated': False, 'days': 7, 'hidden': 0,
            'watched': {'saw': 2, 'kept': 2},
            'unreadable': None, 'pairs': [],
            'offers': [dict(offer(0, pay=18.40, minutes=5.0, state='doubt',
                                  suspect=True), doubt='leg', untimedMiles=7.8,
                            whole=False, miles=2.1, perHour=213.24,
                            grossPerHour=220.8),
                       offer(1, pay=10.0, minutes=20.0, state='no')]},
    'dots': {'count': len(DOTS), 'total': len(DOTS), 'truncated': False,
             'days': 7, 'hidden': 0, 'watched': {'saw': 5, 'kept': 5},
             'unreadable': None, 'pairs': [], 'offers': DOTS},
    'runs': {'count': len(RUNS), 'total': len(RUNS), 'truncated': False,
             'days': 7, 'hidden': 0, 'watched': {'saw': 36, 'kept': 36},
             'unreadable': None, 'pairs': [], 'offers': RUNS},
    'few runs': {'count': len(FEW_RUNS), 'total': len(FEW_RUNS), 'truncated': False,
                 'days': 7, 'hidden': 0, 'watched': {'saw': 9, 'kept': 9},
                 'unreadable': None, 'pairs': [], 'offers': FEW_RUNS},
    'mapped': {'count': len(MAPPED), 'total': len(MAPPED), 'truncated': False,
               'days': 7, 'hidden': 0, 'watched': {'saw': 4, 'kept': 4},
               'unreadable': None, 'pairs': [], 'offers': MAPPED},
    'mixed cost': {'count': len(MIXED_COST), 'total': len(MIXED_COST),
                   'truncated': False, 'days': 7, 'hidden': 0,
                   'watched': {'saw': 7, 'kept': 7},
                   'unreadable': None, 'pairs': [], 'offers': MIXED_COST},
    'kinds': {'count': len(KINDS), 'total': len(KINDS), 'truncated': False,
              'days': 7, 'hidden': 0, 'watched': {'saw': 6, 'kept': 6},
              'unreadable': None, 'pairs': [], 'offers': KINDS},
    'aside cost': {'count': len(ASIDE_COST), 'total': len(ASIDE_COST),
                   'truncated': False, 'days': 7, 'hidden': 0,
                   'watched': {'saw': 6, 'kept': 6},
                   'unreadable': None, 'pairs': [], 'offers': ASIDE_COST},
    # A window whose last row is stamped past the end of time.
    #
    # `new Date(1e20).getHours()` is NaN, `Math.floor(NaN / 3)` is NaN, and
    # indexing an eight-element array with NaN gives undefined — so the push
    # threw INSIDE the by-time-of-day pass and the three charts drawn after it
    # never ran either, on a page that had already painted its figures and so
    # looked as though it had worked. This is not a shape invented for a test:
    # CLOCK_BELIEVABLE_UNTIL exists in server.js because a row arrived stamped
    # 1e20, and the server filters the LOW end of the believable range (a Pi
    # with no RTC boots in 1970) and lets the high end through to the page.
    'no clock': {'count': len(NO_CLOCK), 'total': len(NO_CLOCK),
                 'truncated': False, 'days': 7, 'hidden': 0,
                 'watched': {'saw': len(NO_CLOCK), 'kept': len(NO_CLOCK)},
                 'unreadable': None, 'pairs': [], 'offers': NO_CLOCK},
    'weeks': {'count': len(WEEKS), 'total': len(WEEKS), 'truncated': False,
              'days': 30, 'hidden': 0, 'watched': {'saw': 21, 'kept': 21},
              'unreadable': None, 'pairs': [], 'offers': WEEKS},
    'weeks no clock': {'count': len(WEEKS_NO_CLOCK), 'total': len(WEEKS_NO_CLOCK),
                       'truncated': False, 'days': 30, 'hidden': 0,
                       'watched': {'saw': 22, 'kept': 22},
                       'unreadable': None, 'pairs': [],
                       'offers': WEEKS_NO_CLOCK},
    'searchable': {'count': len(SEARCHABLE), 'total': len(SEARCHABLE),
                   'truncated': False, 'days': 7, 'hidden': 0,
                   'watched': {'saw': 8, 'kept': 8},
                   # Two rows the rig read before its clock was set. They are
                   # in no window and the page has to say so.
                   'beforeClock': 2,
                   # ...and three lines that will not parse at all, which is a
                   # different and worse thing: those offers are not somewhere
                   # else in the file, they are gone, and no backup gets them
                   # back. The page has to tell the two apart.
                   'torn': 3,
                   'unreadable': None, 'pairs': [], 'offers': SEARCHABLE},
    'unreadable': {'count': 0, 'total': 0, 'truncated': False, 'days': 7,
                   'hidden': 0, 'watched': {'saw': 0, 'kept': 0},
                   'unreadable': 'EACCES', 'pairs': [], 'offers': []},
    'all hidden': {'count': 0, 'total': 0, 'truncated': False, 'days': 7,
                   'hidden': 4, 'watched': {'saw': 4, 'kept': 4},
                   'unreadable': None, 'pairs': [], 'offers': []},
    'genuinely empty': {'count': 0, 'total': 0, 'truncated': False, 'days': 7,
                        'hidden': 0, 'watched': {'saw': 0, 'kept': 0},
                        'unreadable': None, 'pairs': [], 'offers': []},
}

DRIVER = r'''
const { chromium } = require('playwright');
const [base, feedsJson, queriesJson] = process.argv.slice(2);
const FEEDS = JSON.parse(feedsJson);
// Typed into the page's own search box, one after another, against the feed
// built for them. The box re-renders on a 120ms timer, so each one is given
// time to land before the sentence beside it is read back.
const QUERIES = JSON.parse(queriesJson);

// The page's own fetch, replaced before its script runs. Everything above it —
// render(), the wording, the arithmetic — is the real thing off disk.
//
// Only /api/journal is answered from the fixture; anything else the page asks
// for goes to the real server, so a request this stub forgot shows up as a
// failure rather than as a page that silently rendered half.
const STUB = (feed) => `
  window.__asked = [];
  // How many times the expensive parts ran. advice.js assigns window.Advice
  // once, after this script, so an accessor here sees it land and wraps the
  // two entry points a keystroke must never reach: the replay behind the
  // advice and the busy join over the whole window.
  window.__calls = { advise: 0, busy: 0 };
  (function () {
    var held;
    Object.defineProperty(window, 'Advice', {
      configurable: true,
      get: function () { return held; },
      set: function (v) {
        held = v;
        if (v && typeof v.advise === 'function' && typeof v.busy === 'function') {
          var a = v.advise, b = v.busy;
          v.advise = function () { window.__calls.advise++; return a.apply(this, arguments); };
          v.busy = function () { window.__calls.busy++; return b.apply(this, arguments); };
        }
      }
    });
  })();
  // The public geocoder, answered here so no check ever sends a customer's
  // street to a real service, and so "was anything asked at all" can be read
  // back. Only two places have answers; everything else comes back empty,
  // which is what a misread street really gets.
  window.__geo = [];
  const PLACES = {
    'chastain': [34.010, -84.580],
    'oak ln': [33.952, -84.549],
  };
  // Leaflet, faked before the page can fetch it from a CDN. Two jobs: prove
  // the page never blocks on a network library, and record what got drawn.
  window.__pins = []; window.__views = [];
  window.L = {
    map: function () { return {
      setView: function (c) { window.__views.push(c); return this; },
      fitBounds: function (b) { window.__views.push(b); return this; },
      invalidateSize: function () { return this; },
      removeLayer: function () { return this; } }; },
    tileLayer: function () { return { addTo: function () { return this; } }; },
    layerGroup: function () { return { addTo: function () { return this; } }; },
    circleMarker: function (ll, o) {
      var m = { ll: ll, opts: o, bindPopup: function (h) { this.popup = h; return this; },
                addTo: function () { window.__pins.push(this); return this; } };
      return m; }
  };
  // A load that fails, once, on demand. The page has two ways of showing
  // nothing — an empty window and an unreachable server — and only the first
  // of them is reachable by handing it a feed. Set this and press a range
  // button and the next /api/journal goes the way a Tailscale link does when
  // the car drives out of range.
  window.__failNext = false;
  const REAL = window.fetch;
  window.fetch = function (url, opts) {
    window.__asked.push(String(url));
    if (String(url).indexOf('/api/journal') === 0) {
      if (window.__failNext) {
        window.__failNext = false;
        return Promise.reject(new TypeError('Failed to fetch'));
      }
      return Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve(${JSON.stringify(feed)}),
        text: () => Promise.resolve(${JSON.stringify(JSON.stringify(feed))}),
      });
    }
    if (String(url).indexOf('nominatim') !== -1) {
      const u = new URL(String(url));
      const q = decodeURIComponent(u.searchParams.get('q') || '');
      window.__geo.push({ q: q, box: u.searchParams.get('viewbox') || null,
                          at: Date.now() });
      const key = Object.keys(PLACES).find((k) => q.toLowerCase().indexOf(k) !== -1);
      const hit = key ? [{ lat: String(PLACES[key][0]), lon: String(PLACES[key][1]),
                           display_name: key + ', GA, USA', type: 'road' }] : [];
      return Promise.resolve({ ok: true, status: 200,
                               json: () => Promise.resolve(hit) });
    }
    return REAL.call(window, url, opts);
  };
`;

const TEXT = (sel) => {
  const el = document.querySelector(sel);
  if (!el) return null;
  return (el.textContent || '').replace(/\s+/g, ' ').trim();
};

(async () => {
  let browser;
  for (const exe of JSON.parse(process.env.PW_EXES || '[]').concat([null])) {
    try { browser = await chromium.launch(exe ? { executablePath: exe } : {}); break; }
    catch (e) {}
  }
  // Said, not thrown. The other three drivers here print this and return,
  // and the Python side needs ONE signal it can tell apart from a crash:
  // a machine with no browser learned nothing and broke nothing, while a
  // driver that threw is a fact about the page. Thrown, the two arrive
  // identically — as no parseable output — and the suite had to guess.
  if (!browser) { console.log(JSON.stringify({ skip: 'no chromium' })); return; }
  const out = {};
  // A step that never settles is reported as a skip naming the feed it hung
  // on, rather than as a suite that sat until the runner's timeout killed
  // it in silence.
  let stage = 'start';
  setTimeout(() => {
    console.log(JSON.stringify({ __hung: stage }));
    process.exit(2);
  }, 400000).unref();
  for (const [name, feed] of Object.entries(FEEDS)) {
    stage = name;
    const ctx = await browser.newContext({ viewport: { width: 900, height: 900 } });
    const page = await ctx.newPage();
    await page.addInitScript(STUB(feed));
    await page.goto(base + '/journal.html', { waitUntil: 'domcontentloaded' })
              .catch(() => {});
    await page.waitForTimeout(1500);
    out[name] = await page.evaluate((sel) => {
      const text = new Function('s', 'return (' + sel + ')(s)');
      const list = (s) => [].slice.call(document.querySelectorAll(s))
        .map((e) => (e.textContent || '').replace(/\s+/g, ' ').trim());
      return {
        headline: text('#headline'),
        // The advice block. Shown for a refusal as well as an answer — a
        // refusal says what the window is short of, which is not nothing — so
        // the two are told apart by `working`, which only an answer fills in.
        advice: document.getElementById('advice').hidden ? null : {
          lead: text('#adviceLead'), working: text('#adviceWorking'),
        },
        nothing: document.getElementById('nothing').hidden
          ? null : text('#nothing'),
        caveats: list('#caveats li'),
        // Where the export points. The sentence beside the row count tells
        // the driver to "use the CSV for the rest", so this link is the only
        // thing standing behind that promise.
        csv: document.getElementById('csv').getAttribute('href'),
        days: list('.day'),
        pairsHead: document.getElementById('pairsHead').hidden
          ? null : text('#pairsHead'),
        pairsLead: document.getElementById('pairsLead').hidden
          ? null : text('#pairsLead'),
        // Each pairing's own detail, opened, so what the row SAYS the panel
        // called it can be read rather than only the tally above it.
        // Opened to read, then put back exactly as it was: leaving them open
        // moves everything below down the page, and the checks further on
        // measure whether things are on screen.
        pairSaid: [].slice.call(document.querySelectorAll('#pairs details'))
          .map(function (d) {
            var was = d.open;
            d.open = true;
            var said = (d.textContent || '').replace(/\s+/g, ' ').trim();
            d.open = was;
            return said;
          }),
        // What the page opens on, before anybody presses anything. The driver's
        // own words: "I mostly need to see orders I have scanned today to see
        // how the market is." It used to open on a week, which is both the
        // wrong question by default and the expensive one — a week's answer is
        // 279 KiB against 39 for a day, and every pass the page makes is over
        // the offers in the window.
        openedOn: [].slice.call(document.querySelectorAll('#ranges button'))
          .filter((b) => b.getAttribute('aria-pressed') === 'true')
          .map((b) => b.getAttribute('data-days')),
        // The first thing it ASKS for, which is the half the button cannot
        // prove: a page that shows Today pressed while fetching a week is the
        // same slow page with a tidier label.
        firstAsked: ((window.__asked || []).filter(
          (u) => String(u).indexOf('/api/journal?') === 0)[0]) || '',
        rows: document.querySelectorAll('#log details.offer').length,
        asked: window.__asked.length,
        // What the panel had said about the jobs that were worked.
        tookHead: document.getElementById('tookHead').hidden
          ? null : text('#tookHead'),
        weekHead: document.getElementById('weekHead').hidden
          ? null : text('#weekHead'),
        blocksHead: document.getElementById('blocksHead').hidden
          ? null : text('#blocksHead'),
        blocks: [].slice.call(document.querySelectorAll('#blocks .block'))
          .map(function (b) {
            return { label: b.querySelector('.label').textContent.trim(),
                     n: b.querySelector('.n').textContent.trim() };
          }),
        // Drawn AFTER the time-of-day pass in the same render, which is why
        // it is read: a throw in that pass took this with it, silently.
        kinds: document.querySelectorAll('#kinds .block').length,
        // ...and what each of those bars actually holds, because "three bars
        // were drawn" says nothing about which cards went into which. The
        // Shop bar used to take any single-leg card carrying an item count,
        // which is a fact about the OCR and not about the card.
        kindBars: [].slice.call(document.querySelectorAll('#kinds .block'))
          .map(function (b) {
            return { label: b.querySelector('.label').textContent.trim(),
                     amount: b.querySelector('.amount').textContent.trim(),
                     n: b.querySelector('.n').textContent.trim() };
          }),
        // The three largest figures on the page, above the fold.
        figures: ['p25', 'p50', 'p75'].map(function (id) {
          return document.getElementById(id).textContent.trim();
        }),
        week: [].slice.call(document.querySelectorAll('#week .block'))
          .map(function (b) {
            return { label: b.querySelector('.label').textContent.trim(),
                     amount: b.querySelector('.amount').textContent.trim(),
                     n: b.querySelector('.n').textContent.trim() };
          }),
        took: [].slice.call(document.querySelectorAll('#took .block'))
          .map(function (b) {
            return { label: b.querySelector('.label').textContent.trim(),
                     amount: b.querySelector('.amount').textContent.trim(),
                     n: b.querySelector('.n').textContent.trim() };
          }),
        // What each row says about arriving during a ticked job, opened.
        arrivals: [].slice.call(document.querySelectorAll('#log details.offer'))
          .map(function (d) {
            d.open = true;
            var dt = [].slice.call(d.querySelectorAll('dt'))
              .filter(function (e) { return e.textContent.trim() === 'Arrived'; })[0];
            var tags = [].slice.call(d.querySelectorAll('summary .tag'))
              .map(function (e) { return e.textContent.trim(); });
            // What the reader read, when the row carries it. Read back as
            // textContent so a '<' the OCR produced comes back as a '<' and
            // not as the start of an element.
            var pre = d.querySelector('.cardtext pre');
            var worth = [].slice.call(d.querySelectorAll('dt'))
              .filter(function (e) { return e.textContent.trim() === 'Worth knowing'; })[0];
            return { tags: tags,
                     id: d.getAttribute('data-id'),
                     worth: worth ? worth.nextElementSibling.textContent.trim() : null,
                     // The element, not its text: an empty box and no box
                     // read identically through textContent, and the first
                     // version of the check below could not tell them apart.
                     hasCardtext: !!d.querySelector('.cardtext'),
                     cardtext: pre ? pre.textContent : null,
                     cardtextTags: pre ? pre.querySelectorAll('*').length : 0,
                     arrived: dt ? dt.nextElementSibling.textContent
                                     .replace(/\s+/g, ' ').trim() : null };
          }),
      };
    }, TEXT.toString());
    // The chips and the order, on the feed with a verdict spread. Each press
    // is read back as the rows it left, the sentence describing them, and
    // whether the day headers survived — a ranking has no days.
    if (name === 'verdicts') {
      out[name].picks = {};
      out[name].callsAtLoad = await page.evaluate(() => Object.assign({}, window.__calls));
      const peek = () => page.evaluate(() => {
        const n = document.getElementById('findNote');
        return { rows: [].slice.call(document.querySelectorAll('#log details.offer'))
                          .map((d) => d.getAttribute('data-id')),
                 note: n.hidden ? null : (n.textContent || '').replace(/\s+/g, ' ').trim(),
                 days: document.querySelectorAll('#log .day').length,
                 more: (document.getElementById('more').textContent || '').trim() };
      });
      for (const pick of ['took', 'go', 'warn', 'no', 'aside', 'busy', 'all']) {
        await page.click('#chips button[data-pick="' + pick + '"]');
        await page.waitForTimeout(250);
        out[name].picks[pick] = await peek();
      }
      for (const sort of ['perHour', 'pay', 'minutes', 'newest']) {
        await page.click('#sorts button[data-sort="' + sort + '"]');
        await page.waitForTimeout(250);
        out[name].picks['sort:' + sort] = await peek();
      }
      // A chip and a ranking together, then a mark made inside the selection:
      // the list must stay selected and ranked through the redraw.
      await page.click('#chips button[data-pick="took"]');
      await page.click('#sorts button[data-sort="perHour"]');
      await page.waitForTimeout(250);
      out[name].picks['took+perHour'] = await peek();
      // ...and five keystrokes in the box, each past the 120ms debounce.
      for (const ch of ['1', '0', '.', '0', '0']) {
        await page.type('#find', ch);
        await page.waitForTimeout(250);
      }
      out[name].callsAfterAll = await page.evaluate(() => Object.assign({}, window.__calls));
    }
    // The colour of each row's dot against the verdict it records, and where
    // the set-aside row lands in a ranking.
    if (name === 'dots') {
      const dots = () => page.evaluate(() =>
        [].slice.call(document.querySelectorAll('#log details.offer')).map((d) => ({
          id: d.getAttribute('data-id'),
          aside: d.classList.contains('aside'),
          dot: (d.querySelector('.dot') || { className: '' }).className.replace('dot', '').trim() })));
      out[name].dots = {};
      for (const pick of ['no', 'go', 'all']) {
        await page.click('#chips button[data-pick="' + pick + '"]');
        await page.waitForTimeout(250);
        out[name].dots[pick] = await dots();
      }
      out[name].ranked = {};
      for (const sort of ['perHour', 'pay']) {
        await page.click('#sorts button[data-sort="' + sort + '"]');
        await page.waitForTimeout(250);
        out[name].ranked[sort] = (await dots()).map((d) => d.id);
      }
      out[name].findKeyboard = await page.evaluate(() =>
        document.getElementById('find').getAttribute('inputmode'));
      /* ...and what is left on screen when a range press cannot be answered.
       *
       * The commonest failure this page has: it is read over Tailscale, from a
       * machine in a car, and any range button can land while the link is
       * down. The handler clears the log, the charts, the pairings and the
       * caveats and paints "Cannot reach the scanner" — and left the three
       * $/hr figures standing above it, in the largest type on the page, with
       * nothing marking them as the previous window's answer.
       */
      stage = name + ' — a range press that fails';
      await page.evaluate(() => { window.__failNext = true; });
      await page.click('#ranges button[data-days="7"]');
      await page.waitForTimeout(600);
      out[name].afterFailedLoad = await page.evaluate(() => ({
        nothing: document.getElementById('nothing').hidden ? null
          : (document.getElementById('nothing').textContent || '')
              .replace(/\s+/g, ' ').trim(),
        headline: (document.getElementById('headline').textContent || '').trim(),
        figures: ['p25', 'p50', 'p75'].map(
          (id) => document.getElementById(id).textContent.trim()),
        rows: document.querySelectorAll('#log details.offer').length,
      }));
    }
    if (name === 'leg') {
      out[name].detail = await page.evaluate(() => {
        const all = [].slice.call(document.querySelectorAll('#log details.offer'));
        const d = all.filter((x) => x.getAttribute('data-id') === 'r0')[0];
        if (!d) return { ids: all.map((x) => x.getAttribute('data-id')) };
        d.open = true;
        const flat = (el) => el ? (el.textContent || '').replace(/\s+/g, ' ').trim() : '';
        return { aside: d.classList.contains('aside'),
                 why: flat(d.querySelector('.why, .aside-why, p')),
                 all: flat(d) };
      });
    }
    // The chips and the order on the nothing-usable path.
    if (name === 'all aside') {
      const rows = () => page.evaluate(() => ({
        rows: [].slice.call(document.querySelectorAll('#log details.offer'))
                 .map((d) => d.getAttribute('data-id')),
        days: document.querySelectorAll('#log .day').length,
        note: document.getElementById('findNote').hidden ? null
          : (document.getElementById('findNote').textContent || '').replace(/\s+/g, ' ').trim() }));
      out[name].asIs = await rows();
      await page.click('#chips button[data-pick="took"]');
      await page.waitForTimeout(250);
      out[name].tookChip = await rows();
      await page.click('#chips button[data-pick="all"]');
      await page.click('#sorts button[data-sort="pay"]');
      await page.waitForTimeout(250);
      out[name].byPay = await rows();
    }
    // The runs chart: what it shows, what its button says, and what a press
    // does. Every row is read back as its label and amount so the folded
    // eight can be held against the tail of the twelve.
    if (name === 'runs' || name === 'few runs') {
      const runsNow = () => page.evaluate(() => {
        const b = document.getElementById('runsAll');
        return { head: document.getElementById('runsHead').hidden
                   ? null : (document.getElementById('runsHead').textContent || '').replace(/\s+/g, ' ').trim(),
                 rows: [].slice.call(document.querySelectorAll('#runs .block')).map((e) =>
                   (e.querySelector('.label').textContent + ' ' + e.querySelector('.amount').textContent)
                     .replace(/\s+/g, ' ').trim()),
                 button: b.hidden ? null : (b.textContent || '').trim(),
                 pressed: b.getAttribute('aria-pressed'),
                 height: b.hidden ? 0 : b.getBoundingClientRect().height };
      });
      out[name].runs = { folded: await runsNow() };
      if (out[name].runs.folded.button) {
        await page.click('#runsAll');
        await page.waitForTimeout(250);
        out[name].runs.opened = await runsNow();
        await page.click('#runsAll');
        await page.waitForTimeout(250);
        out[name].runs.refolded = await runsNow();
      }
    }
    /* --- the map sheet ---------------------------------------------------
     *
     * The driver's complaint was that every map control opened a tab and left
     * the log behind. These now open a sheet over the bottom of this page, so
     * what is checked is: nothing is looked up until one is pressed, pressing
     * one draws the right pins, and the page is still the page underneath.
     *
     * Leaflet is faked in the stub above rather than fetched, which also
     * proves the page does not sit waiting on a CDN before it will show
     * anything. */
    if (name === 'mapped') {
      const sheet = () => ({
        open: !document.getElementById('sheet').hidden,
        where: (document.getElementById('sheetWhere').textContent || '').trim(),
        note: (document.getElementById('sheetNote').textContent || '').trim(),
        out: document.getElementById('sheetOut').hidden
          ? null : document.getElementById('sheetOut').getAttribute('href'),
        pins: window.__pins.length,
        asked: window.__geo.map((g) => g.q),
        boxes: window.__geo.map((g) => !!g.box),
      });
      // Open every row, so the controls inside them can be pressed.
      await page.evaluate(() => {
        document.querySelectorAll('#log details.offer').forEach((d) => { d.open = true; });
      });
      await page.waitForTimeout(200);
      out[name].beforeAny = await page.evaluate(sheet);
      out[name].said = await page.evaluate(() =>
        [].slice.call(document.querySelectorAll('#log details.offer'))
          .map((d) => d.getAttribute('data-id') + ': '
                    + (d.textContent || '').replace(/\s+/g, ' ').trim()));
      out[name].controls = await page.evaluate(() =>
        [].slice.call(document.querySelectorAll('#log button[data-map]'))
          .map((b) => b.getAttribute('data-map') + '/' + b.getAttribute('data-end')
                    + ':' + (b.textContent || '').trim()));
      // Picked by the row it belongs to rather than by its place in the list,
      // so a change to the sort order cannot quietly point these checks at a
      // different job than the one they describe.
      const tap = (id, end) => page.evaluate((a) => {
        const b = document.querySelector('#log button[data-map="' + a[0]
                                         + '"][data-end="' + a[1] + '"]');
        if (b) b.click();
        return !!b;
      }, [id, end]);
      // r0 is the job that named both ends.
      stage = name + ' — map sheet';
      out[name].tapped = await tap('r0', 'both');
      // Two lookups at one a second, plus the walk's own overhead.
      await page.waitForTimeout(3600);
      out[name].route = await page.evaluate(sheet);
      // The log is still the log: a sheet that navigated away, or that ate
      // the rows underneath it, would be exactly the thing being replaced.
      out[name].stillThere = await page.evaluate(() => ({
        rows: document.querySelectorAll('#log details.offer').length,
        padded: document.body.classList.contains('sheeted'),
        url: location.pathname,
      }));
      // Pressing the same control again puts it away.
      await tap('r0', 'both');
      await page.waitForTimeout(250);
      out[name].shut = await page.evaluate(sheet);
      // ...and a dropoff nothing can place says so rather than showing an
      // empty map with no explanation. r2's dropoff has no answer anywhere.
      await tap('r2', 'dropoff');
      await page.waitForTimeout(2600);
      out[name].lost = await page.evaluate(sheet);
      // ...and the shape in between, which is the commonest of the three: one
      // end on the map and one that could not be placed. r2's pickup is real
      // and its dropoff is a street nothing has heard of. The sheet used to
      // name BOTH colours here — "Green is the pickup, amber the dropoff" —
      // over a map with one pin on it, and never said which end was missing or
      // why, while the branch for "nothing placed" splits that three ways.
      await tap('r2', 'dropoff');
      await page.waitForTimeout(250);
      // The stub's pin list accumulates across taps, so it is cleared here:
      // what this case is about is how many pins THIS draw put down.
      await page.evaluate(() => { window.__pins = []; });
      await tap('r2', 'both');
      await page.waitForTimeout(3600);
      out[name].halfPlaced = await page.evaluate(sheet);
      // ...and the pair the sheet must NOT settle. r4 names the same two ends
      // as r0, so both are already in the cache and nothing is asked again —
      // what changes is that its reading is suspect, so the card's three miles
      // is not a yardstick and the four and a half on the map is not evidence
      // against either pin.
      await tap('r2', 'both');
      await page.waitForTimeout(250);
      await tap('r4', 'both');
      await page.waitForTimeout(1200);
      out[name].unjudged = await page.evaluate(sheet);
    }
    if (name === 'took six') {
      // A mark, made on an opened row a long way down the list: the row
      // must still be open and on screen afterwards. The mark goes to the
      // real server (only /api/journal is stubbed), which answers, and the
      // list is redrawn from the same feed.
      out[name].mark = await page.evaluate(async () => {
        const rows = document.querySelectorAll('#log details.offer');
        const d = rows[rows.length - 1];
        d.open = true;
        d.scrollIntoView({ block: 'center' });
        const before = { y: window.scrollY, top: d.getBoundingClientRect().top };
        d.querySelector('button[data-act="took"]').click();
        await new Promise((r) => setTimeout(r, 900));
        const again = document.querySelector('#log details.offer[data-id="' + d.getAttribute('data-id') + '"]');
        return { id: d.getAttribute('data-id'), before: before,
                 open: !!(again && again.open),
                 top: again ? again.getBoundingClientRect().top : null,
                 y: window.scrollY, inner: window.innerHeight,
                 undo: (document.getElementById('undoWhat').textContent || '').trim() };
      });
      // Two loads in flight: the slower earlier one must not paint over the
      // window pressed later. 7 days is answered after 1.5s with the feed;
      // Today is answered at once with nothing.
      out[name].race = await page.evaluate(async (empty) => {
        const feedFetch = window.fetch;
        window.fetch = function (url, opts) {
          const u = String(url);
          if (u.indexOf('/api/journal?') === 0 && u.indexOf('days=7') !== -1) {
            return new Promise((r) => setTimeout(() => r(feedFetch(url, opts)), 1500));
          }
          if (u.indexOf('/api/journal?') === 0) {
            return Promise.resolve({ ok: true, status: 200,
              json: () => Promise.resolve(empty), text: () => Promise.resolve(JSON.stringify(empty)) });
          }
          return feedFetch(url, opts);
        };
        document.querySelector('#ranges button[data-days="7"]').click();
        await new Promise((r) => setTimeout(r, 50));
        document.querySelector('#ranges button[data-days="1"]').click();
        await new Promise((r) => setTimeout(r, 2200));
        const pressed = [].slice.call(document.querySelectorAll('#ranges button'))
          .filter((b) => b.getAttribute('aria-pressed') === 'true').map((b) => b.getAttribute('data-days'));
        window.fetch = feedFetch;
        return { pressed: pressed,
                 rows: document.querySelectorAll('#log details.offer').length,
                 days: document.querySelectorAll('#log .day').length,
                 nothing: document.getElementById('nothing').hidden ? null
                   : (document.getElementById('nothing').textContent || '').slice(0, 40),
                 headline: (document.getElementById('headline').textContent || '').trim(),
                 scale: (document.getElementById('blockScale').textContent || '').trim() };
      }, FEEDS['genuinely empty']);
      // The feed again, then a search and a window that fails: nothing of
      // the previous window may stand under the apology, and a chip must
      // not bring it back.
      out[name].failed = await page.evaluate(async () => {
        const feedFetch = window.fetch;
        document.querySelector('#ranges button[data-days="7"]').click();
        await new Promise((r) => setTimeout(r, 400));
        const box = document.getElementById('find');
        box.value = 'marietta';
        box.dispatchEvent(new Event('input', { bubbles: true }));
        await new Promise((r) => setTimeout(r, 400));
        const withRows = { pairs: !document.getElementById('pairsHead').hidden,
                           note: !document.getElementById('findNote').hidden,
                           scale: (document.getElementById('blockScale').textContent || '').trim() };
        window.fetch = function (url, opts) {
          if (String(url).indexOf('/api/journal?') === 0) return Promise.reject(new Error('down'));
          return feedFetch(url, opts);
        };
        document.querySelector('#ranges button[data-days="30"]').click();
        await new Promise((r) => setTimeout(r, 400));
        const down = { pairs: !document.getElementById('pairsHead').hidden,
                       note: !document.getElementById('findNote').hidden,
                       scale: (document.getElementById('blockScale').textContent || '').trim(),
                       nothing: (document.getElementById('nothing').textContent || '').slice(0, 25) };
        document.querySelector('#chips button[data-pick="go"]').click();
        await new Promise((r) => setTimeout(r, 300));
        const chipped = document.querySelectorAll('#log details.offer').length;
        window.fetch = feedFetch;
        box.value = '';
        box.dispatchEvent(new Event('input', { bubbles: true }));
        document.querySelector('#chips button[data-pick="all"]').click();
        await new Promise((r) => setTimeout(r, 300));
        return { withRows: withRows, down: down, chipped: chipped };
      });
      await page.click('#ranges button[data-days="7"]').catch(() => {});
      await page.waitForTimeout(400);
    }
    // A chip that picks nothing, on the feed with no verdicts on its rows.
    if (name === 'took six') {
      await page.click('#chips button[data-pick="no"]');
      await page.waitForTimeout(250);
      out[name].emptyPick = await page.evaluate(() => {
        const n = document.getElementById('findNote');
        return { rows: document.querySelectorAll('#log details.offer').length,
                 note: n.hidden ? null : (n.textContent || '').replace(/\s+/g, ' ').trim() };
      });
      await page.click('#chips button[data-pick="all"]');
      await page.waitForTimeout(250);
    }
    // ...and then the search box, on the one feed built to be searched. Typed
    // rather than assigned, because the note is redrawn by the box's own
    // `input` handler and setting `.value` fires nothing.
    if (name === 'searchable') {
      out[name].searches = {};
      for (const q of QUERIES) {
        await page.fill('#find', q);
        await page.waitForTimeout(400);
        out[name].searches[q] = await page.evaluate(() => {
          const n = document.getElementById('findNote');
          return { note: n.hidden ? null
                     : (n.textContent || '').replace(/\s+/g, ' ').trim(),
                   rows: document.querySelectorAll('#log details.offer').length };
        });
      }
      // ...and cleared again, because an empty box must take the note away
      // rather than leave the last answer standing over the whole list.
      await page.fill('#find', '');
      await page.waitForTimeout(400);
      out[name].searches[''] = await page.evaluate(() => {
        const n = document.getElementById('findNote');
        return { note: n.hidden ? null : (n.textContent || '').trim(),
                 rows: document.querySelectorAll('#log details.offer').length };
      });
    }
    await page.close();
    await ctx.close();
  }
  await browser.close();
  console.log(JSON.stringify(out));
})().catch((e) => { console.log(JSON.stringify(
  // A throw anywhere in this driver is a FAULT, not a machine that
  // could not run the checks. Reported as `skip` it exited 0 and the
  // whole suite counted as passed with nothing run. The one real skip
  // — no chromium — is printed above, before anything can throw.
  { __crashed: String((e && e.stack) || e) })); });
'''


def crashed(stderr):
    """A driver that RAN and produced nothing is a FAILED suite.

    This used to be a skip, which exits 0, so `tools/test.sh` counted the suite
    as passed with none of its checks run. It is the same conflation `hung()`
    was written for and it was only half fixed: a driver that stops answering
    is caught, a driver that THROWS still slipped through as "the browser
    produced nothing".

    A machine that cannot run these at all — no chromium — is the one case
    where exiting 0 is right, and every driver here now says so explicitly by
    printing {skip: 'no chromium'} and returning. That is a signal; this is the
    absence of one. Reading the difference out of stderr was considered and
    rejected: it makes the suite guess from a message it does not control.
    """
    tail = (stderr or '').strip()[-400:]
    print('FAIL  the driver produced nothing — none of the %s checks ran'
          % 'offers-page')
    if tail:
        print('      ' + tail.replace('\n', '\n      '))
    print('\n%d passed, %d FAILED' % (ok, bad + 1))
    sys.exit(1)


def free_port():
    import socket
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


NODE_PATHS = [p for p in (os.environ.get('NODE_PATH'),
                          '/opt/node22/lib/node_modules') if p]
env_probe = dict(os.environ, NODE_PATH=os.pathsep.join(NODE_PATHS))
if subprocess.call(['node', '-e', 'require("playwright")'], env=env_probe,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
    skip('no playwright')

work = tempfile.mkdtemp()
journal = os.path.join(work, 'journal.jsonl')
open(journal, 'w').close()
port = free_port()
proc = subprocess.Popen(
    ['node', os.path.join(ROOT, 'server.js')],
    env=dict(os.environ, SCANNER='0', PORT=str(port), JOURNAL=journal),
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
base = 'http://127.0.0.1:%d' % port

try:
    import time
    import urllib.request
    for _ in range(120):
        try:
            urllib.request.urlopen(base + '/api/status', timeout=1).read()
            break
        except Exception:
            time.sleep(0.1)
    else:
        raise RuntimeError('the server never came up')

    driver = os.path.join(work, 'offerspage.js')
    open(driver, 'w').write(DRIVER)
    run = subprocess.run(
        ['node', driver, base, json.dumps(FEEDS), json.dumps(QUERIES)],
        env=dict(os.environ, NODE_PATH=os.pathsep.join(NODE_PATHS),
                 PW_EXES=json.dumps([
                     os.environ.get('CHROMIUM', ''),
                     '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
                 ])),
        capture_output=True, text=True, timeout=600)
    line = (run.stdout or '').strip().split('\n')[-1] if run.stdout else ''
    try:
        got = json.loads(line)
    except Exception:
        crashed(proc.stderr)
    # A hang first, and separately, because the two mean opposite
    # things — see hung().
    if got.get('__hung'):
        hung(got['__hung'])
    # A throw in the driver, which the catch at its foot now reports as
    # its own thing rather than as a skip — see crashed().
    if got.get('__crashed'):
        crashed(got['__crashed'])
    if got.get('skip'):
        skip(got['skip'])

    # --- the page reached its own data ---------------------------------------
    for name in FEEDS:
        ok_('%s was rendered' % name, got.get(name) is not None)
    if any(got.get(n) is None for n in FEEDS):
        raise SystemExit(1)

    # --- what the page opens on ---------------------------------------------
    #
    # The driver's own words: "I mostly need to see orders I have scanned today
    # to see how the market is." It opened on a week, which is both the wrong
    # question by default — a median over seven days is a fact about the month,
    # and the one being asked at the wheel is whether THIS evening is worth
    # staying out for — and the expensive one: measured against a year-sized
    # journal, a week is 279 KiB where a day is 39, and every pass this page
    # makes is over the offers in the window.
    #
    # Both halves, because the button proves only the label. A page showing
    # Today pressed while fetching a week is the same slow page with a tidier
    # sticker on it.
    for name in FEEDS:
        r = got.get(name) or {}
        eq('%s: the page opens on Today' % name, r.get('openedOn'), ['1'])
        asked = r.get('firstAsked') or ''
        # Today is not days=1: a trailing 24 hours folds last night's shift into
        # this morning's figures, and only the browser knows when the driver's
        # day began. baseWindow sends days=2 with an explicit 4am `since`.
        ok_('%s: ...and asks for it, not for a week (%r)' % (name, asked[:60]),
            'since=' in asked and 'days=7' not in asked)
        csv = r.get('csv') or ''
        ok_('%s: ...and the export points at the same window (%r)'
            % (name, csv[:60]), 'since=' in csv and 'days=7' not in csv)

    # --- a line that moves may not be called a line that did not -------------
    #
    # `stable` lets the recommended figure wander by UNSTABLE_SPREAD across the
    # six ways the recording is cut into runs, which is $6 — a fifth to a third
    # of the line itself on the targets this driver sets. The page printed "The
    # same line comes out however the recording is split into runs ... which is
    # why it is worth acting on" over all of it, in the one sentence whose job
    # is to say why the number can be trusted. This market uses the whole
    # allowance: $24 at the two shortest cuts, $30 at the other four.
    #
    # The remedy is the wording, not the threshold. A line steady to within a
    # few dollars over six different cuts is a real finding and refusing it
    # would throw away the answer; claiming it never moved is the part that was
    # not true.
    wob = (got.get('a line that moves') or {}).get('advice') or {}
    work = wob.get('working') or ''
    ok_('the wobbly market gets an answer at all', bool(work))
    ok_('...and the answer names the line (%r)' % work[-90:], '$30' in work)
    ok_('...and does not claim it came out the same however the recording '
        'is split', 'same line comes out' not in work)
    ok_('...but says where it actually went', '$24' in work and '$30' in work)
    ok_('...and by how much', '$6 spread' in work)
    ok_('...and that the figure shown is one of the six, not their average',
        'not an average' in work)
    # The strong wording is not deleted, only earned. Every other feed here is
    # too small to reach the answered state, so the case that keeps it is
    # checked against the module in tests/advice.test.js rather than through a
    # second hundred-row fixture.

    # --- net and gross may not disagree about the same offers ----------------
    #
    # --- the runs chart shows the latest few and offers the rest ------------
    # Measured on a fortnight of offers at 800x480 before this: seventeen runs
    # on a week put "By time of day" 1,911px down the page, three panel
    # screens of bars between the headline and the chart that says which hours
    # pay. It sits after those charts now, and shows eight.
    rn = got['runs']['runs']
    fold = rn['folded']
    ok_('twelve runs are counted in the heading (%r)' % (fold['head'] or '')[:40],
        fold['head'] is not None and '12 of them' in fold['head'])
    eq('...and eight are drawn', len(fold['rows']), 8)
    ok_('...with a button naming the rest (%r)' % fold['button'],
        fold['button'] is not None and '12' in fold['button'])
    ok_('...tall enough to press in a car (%.0fpx)' % fold['height'], fold['height'] >= 44)
    opened = rn.get('opened') or {}
    eq('pressing it draws all twelve', len(opened.get('rows') or []), 12)
    eq('...the eight it showed being the latest eight',
       fold['rows'], (opened.get('rows') or [])[-8:])
    eq('...and the button says so', opened.get('pressed'), 'true')
    eq('pressing it again folds them back', len((rn.get('refolded') or {}).get('rows') or []), 8)
    few = got['few runs']['runs']['folded']
    eq('three runs are all drawn', len(few['rows']), 3)
    ok_('...with nothing to press', few['button'] is None)

    # --- a mark leaves the row where it was -------------------------------
    mk = got['took six'].get('mark') or {}
    ok_('the row acted on was opened and scrolled to before the mark',
        mk.get('before') and mk['before'].get('y', 0) > 0)
    ok_('the mark was made (%r)' % mk.get('undo'), 'taken' in (mk.get('undo') or ''))
    ok_('...and the row is still open afterwards', mk.get('open'))
    ok_('...and still on screen (top %r of %r)' % (mk.get('top'), mk.get('inner')),
        mk.get('top') is not None and 0 <= mk['top'] < (mk.get('inner') or 0))

    # --- the later window wins ------------------------------------------
    rc = got['took six'].get('race') or {}
    eq('after 7 days then Today, Today is the window pressed', rc.get('pressed'), ['1'])
    eq('...and the rows on the page are today\'s (none)', rc.get('rows'), 0)
    eq('...with no day headers from the week', rc.get('days'), 0)
    ok_('...and the empty state, not the week\'s headline (%r)' % (rc.get('headline') or '')[:40],
        rc.get('nothing') is not None and 'cleared the line' not in (rc.get('headline') or ''))
    eq('...and no chart scale left over', rc.get('scale'), '')

    # --- a window that cannot be fetched leaves nothing of the last one -----
    fl = got['took six'].get('failed') or {}
    wr = fl.get('withRows') or {}
    ok_('with rows on the page there is a pairing, a search sentence and a scale',
        wr.get('pairs') and wr.get('note') and wr.get('scale'))
    dn = fl.get('down') or {}
    ok_('the apology is up (%r)' % dn.get('nothing'), 'Cannot reach' in (dn.get('nothing') or ''))
    ok_('...with no pairing under it', not dn.get('pairs'))
    ok_('...no search sentence', not dn.get('note'))
    eq('...no chart scale', dn.get('scale'), '')
    eq('...and a chip brings nothing back', fl.get('chipped'), 0)

    # --- the dot is the verdict the row records ---------------------------
    dz = got['dots']
    passing = [d for d in (dz['dots'].get('no') or []) if not d['aside']]
    ok_('the PASS chip lists rows', bool(passing))
    eq('...and every one of them wears a PASS dot', sorted(set(d['dot'] for d in passing)), ['no'])
    accepting = [d for d in (dz['dots'].get('go') or []) if not d['aside']]
    eq('...as every row under ACCEPT wears an ACCEPT dot',
       sorted(set(d['dot'] for d in accepting)), ['go'])
    ranked = dz['ranked'].get('perHour') or []
    ok_('Best $/hr does not lead with the set-aside misread (%r)' % ranked[:2],
        ranked and ranked[0] != 'r104')
    eq('...which is last', ranked[-1] if ranked else None, 'r104')
    eq('...and last under Highest pay too', (dz['ranked'].get('pay') or [None])[-1], 'r104')
    ok_('the find box does not ask the phone for a keypad with no letters (%r)'
        % dz.get('findKeyboard'), dz.get('findKeyboard') not in ('decimal', 'numeric'))

    # Six taken offers, $10.00 each with $2.00 of running cost: $48.00 net,
    # $60.00 gross. The headline was already net; the day header was not, and
    # any rendered "took N for $X" guarantees the headline is above it, so the
    # two were never apart.
    took = got['took six']
    ok_('the headline names what was taken (%r)' % (took['headline'] or '')[:70],
        'marked' in (took['headline'] or ''))
    ok_('...net, and saying so',
        '$48.00' in took['headline'] and 'after running costs' in took['headline'])
    no_('...and not the gross total', '$60.00' in took['headline'])
    ok_('there is a day header to compare it with', bool(took['days']))
    day = ' '.join(took['days'])
    ok_('the day header agrees with the headline about the same six (%r)'
        % day[-60:], 'took 6 for $48.00' in day)
    no_('...rather than quoting the gross figure beside a net rate',
        '$60.00' in day)
    # The whole line, not only the half that was wrong: the median beside these
    # totals is net, and a line carrying a net rate and gross money is the
    # fault its own comment names.
    no_('nothing else on the day line is gross either', '$120.00' in day)
    ok_('...the offered total is net too ($96 of $120)', '$96.00' in day)

    # --- an unreadable journal is not a quiet week ---------------------------
    blind = got['unreadable']
    ok_('an unreadable journal says so in the headline (%r)'
        % (blind['headline'] or '')[:70],
        'could not be read' in (blind['headline'] or ''))
    ok_('...and in the panel', 'could not be read' in (blind['nothing'] or ''))
    # The claim that was being made instead. It sends a driver to debug a
    # camera that is working, over a file that is sitting on disk intact.
    no_('...and never claims the rig is reading nothing',
        'reading nothing' in ((blind['headline'] or '') + (blind['nothing'] or '')))
    ok_('...with the server\'s own reason kept',
        any('EACCES' in c for c in blind['caveats']))
    # The notes were blanked on this path, which is the one path where the note
    # IS the explanation for the emptiness above it.
    ok_('...and the notes are not thrown away', len(blind['caveats']) > 1)
    # No row to read a cost per mile off, so nothing is said about one.
    no_('...and nothing is invented about running costs',
        any('running cost' in c for c in blind['caveats']))

    # --- a window that is entirely hidden is not an empty one ----------------
    hid = got['all hidden']
    ok_('a hidden-only window says what is hiding the rows (%r)'
        % (hid['nothing'] or '')[:70], 'hidden' in (hid['nothing'] or ''))
    no_('...and does not blame the camera',
        'reading nothing' in (hid['nothing'] or ''))
    ok_('...and the count reaches the notes',
        any('4 offers are hidden' in c for c in hid['caveats']))

    # --- and a genuinely empty one still reads as it did ---------------------
    #
    # The point of the two branches above is that this one keeps its wording.
    # A page that hedged every empty state would have lost the message that is
    # right when the rig really has read nothing.
    empty = got['genuinely empty']
    ok_('an empty journal still says the scanner has recorded nothing (%r)'
        % (empty['nothing'] or '')[:70],
        'No offers recorded yet' in (empty['nothing'] or ''))
    ok_('...and still sends the driver to the live view',
        'reading nothing' in (empty['nothing'] or ''))
    eq('...with no rows listed', empty['rows'], 0)

    # --- offers that arrived while a ticked job was running ------------------
    #
    # Only the positive case is ever stated. This can see ticked jobs and
    # nothing else, and 49 ticks across eight days of the driver's own record is
    # plainly not every job worked — so an unmarked row means "no ticked job was
    # running", never "you were free". Measured over the seven exports, the
    # share that looks busy tracks how hard the driver was ticking rather than
    # how busy they were: 3.5% of offers on the three days carrying one to three
    # ticks, 27.7% on the four days carrying ten or eleven.
    busy = got['busy']
    arr = busy['arrivals']
    eq('every seeded row is listed', len(arr), 6)
    inside = [a for a in arr if a['arrived']]
    eq('the three offers inside the ticked job are marked', len(inside), 3)
    ok_('...saying how far into it they arrived (%r)'
        % (inside[0]['arrived'] or '')[:60],
        all('min into a job you ticked at' in (a['arrived'] or '') for a in inside))
    # The strongest thing to get wrong: the driver demonstrably took this one.
    stacks = [a for a in arr if 'stacked on' in a['tags']]
    eq('the one inside the window that was itself ticked is a stack', len(stacks), 1)
    ok_('...and says so rather than calling it unavailable',
        'you ticked this one too' in (stacks[0]['arrived'] or ''))
    during = [a for a in arr if 'during a job' in a['tags']]
    eq('...and the other two are marked plainly', len(during), 2)
    # No chip and no row is the whole of what is said about the rest. A page
    # that wrote "you were free" here would be wrong on about 130 rows of the
    # driver's own record, concentrated on the days somebody forgot to tick.
    silent = [a for a in arr if not a['arrived']]
    eq('the rest say nothing at all', len(silent), 3)
    no_('...and never claim the driver was free',
        any('free' in ' '.join(a['tags']).lower() for a in arr))
    # ...and the note that stops the silence being read as its opposite.
    ok_('the note says what the marking is worked out from',
        any('no ticked job was running, not that you were free' in c
            for c in busy['caveats']))
    # With nothing ticked the feature has said nothing, and a note about it
    # would be noise on every window that has no ticks in it.
    no_('...and it stays away when nothing is ticked',
        any('during a job' in c for c in got['unreadable']['caveats']))

    # --- the stacking record reaches the page --------------------------------
    ok_('the second-jobs section appears when there are pairings (%r)'
        % (took['pairsHead'] or '')[:60],
        'Second jobs' in (took['pairsHead'] or ''))
    ok_('...saying which way the panel went (%r)' % (took['pairsLead'] or '')[:70],
        'take it' in (took['pairsLead'] or ''))
    # ...and counting a row whose verdict was never the panel's separately.
    #
    # recordPairing computed every pair's state against a target of zero for as
    # long as it read the driver's settings off the offer line, which has never
    # carried them — so those rows all say 'go' whatever the panel said, and
    # they are all still on disk. Reporting them as "take it" is this page
    # putting words in the panel's mouth; dropping them would hide how much of
    # the record cannot be graded. Named instead.
    ok_('...and naming the pairings whose verdict was not kept',
        'not recorded' in (took['pairsLead'] or ''))
    ok_('...without counting them as a verdict the panel gave (%r)'
        % (took['pairsLead'] or '')[:70],
        'take it <b>1</b>' in (took['pairsLead'] or '')
        or 'take it 1' in (took['pairsLead'] or ''))
    # ...and the row itself, not only the tally above it. This is the line a
    # driver reads when grading one decision, and it is where the wrong word
    # does the damage: "Called it: take it" about a pairing whose verdict was
    # computed against a target of zero.
    _said = took.get('pairSaid') or []
    eq('both pairings are listed', len(_said), 2)
    _judged = [t for t in _said if 'take it' in t]
    _unjudged = [t for t in _said if 'not recorded' in t]
    eq('...the one whose verdict was kept says what the panel called it',
       len(_judged), 1)
    eq('...and the one whose verdict was not says so instead', len(_unjudged), 1)
    ok_('...explaining why, rather than leaving two words on their own',
        _unjudged and 'was not kept' in _unjudged[0])
    # The pair's own figures are unaffected and must still be there: what was
    # lost is the verdict, not the money.
    ok_('...while the pair\'s own figures are still shown',
        _unjudged and '17.4' in _unjudged[0])
    for name in ('unreadable', 'all hidden', 'genuinely empty'):
        eq('...and staying away when there are none: %s' % name,
           got[name]['pairsHead'], None)

    # --- the one claim on a pairing that is made without a hedge -------------
    #
    # "Beats finishing what you have" is the half of the stacking answer that
    # does not depend on geography, so it is the only clause stated flat — and
    # it has three values, not two. `sure` false is the claim made and
    # answered no; `sure` null is the claim WITHHELD, because the offer card
    # printed no chargeable distance and so the pair's rate is a ceiling while
    # the rate it would be held against is net. The page had two branches and
    # printed the withheld case as "no — the worst end is below finishing
    # alone", which is the opposite of what was withheld: on the (held,
    # gross-offer) pairs drawable from the owner's own week, 77.4% have
    # worst >= alone.
    #
    # Read off the rows rather than a tally, because the wrong sentence is on
    # the row. All three must be distinguishable or the fix is not a fix: a
    # page that printed nothing for the withheld case would pass a check that
    # only looked for the absence of the no.
    _claims = got['stack claim']['pairSaid'] or []
    eq('the three pairings are listed', len(_claims), 3)
    _yes = [t for t in _claims if 'yes, even sharing no road at all' in t]
    _no = [t for t in _claims if 'the worst end is below finishing alone' in t]
    _held = [t for t in _claims if 'not said' in t]
    eq('a costed pair that clears says so flat', len(_yes), 1)
    eq('...a costed pair that does not is told it does not', len(_no), 1)
    eq('...and the pair whose offer printed no distance gets neither',
       len(_held), 1)
    _held_said = _held[0][_held[0].find('not said'):][:120] if _held else ''
    ok_('...but is told why, rather than left silent (%r)' % _held_said,
        'ceiling' in _held_said)
    # The three are three different rows. Without this, one row carrying all
    # three phrases would satisfy every count above.
    eq('...and they are three different pairings',
       len(set([_yes[0] if _yes else 'a', _no[0] if _no else 'b',
                _held[0] if _held else 'c'])), 3)

    # --- what was taken, against what the panel had said about it ------------
    #
    # Read in one direction only. Every row behind these bars is ticked, so the
    # denominator is a set of jobs somebody said they worked; the other
    # direction — "of what it cleared, how much did you take" — would divide by
    # a pile that is mostly rows nobody pressed a button on.
    v = got['verdicts']
    bars = {b['label']: b for b in v['took']}
    ok_('the taken chart appears once something is ticked (%r)'
        % (v['tookHead'] or '')[:70], v['tookHead'] is not None)
    eq('...with one bar per verdict the panel can give', len(v['took']), 3)
    eq('...ACCEPT is the two cleared jobs', bars.get('ACCEPT', {}).get('n'), '2')
    # $30 and $36 interpolate to $33. A bar built from the wrong pile would not
    # land here: CLOSE is $24 and PASS is $18.
    eq('...at their own median, not the page\'s',
       bars.get('ACCEPT', {}).get('amount'), '$33')
    eq('...CLOSE is the two it hedged', bars.get('CLOSE', {}).get('n'), '2')
    eq('...at $24', bars.get('CLOSE', {}).get('amount'), '$24')
    # The one that matters most. Taking a job the panel said to pass is the
    # decision the target exists to inform, and what it paid is the answer.
    eq('...PASS is the one taken against the advice',
       bars.get('PASS', {}).get('n'), '1')
    eq('...and says what that one paid', bars.get('PASS', {}).get('amount'), '$18')
    # Six ticked, five countable: a heading printing five under a page that
    # counts six ticks is two numbers on one screen that do not add up.
    ok_('...and the heading reconciles the ticks it could not count (%r)'
        % (v['tookHead'] or '')[-60:],
        '5 of 6 you ticked that could be counted (1 set aside)'
        in (v['tookHead'] or ''))
    # A verdict nobody recorded is not a fourth kind of advice, so the bar for
    # it stays away unless something is actually in it.
    no_('...with no empty fourth bar', 'no verdict' in ' '.join(
        b['label'] for b in v['took']))
    # ...and rows written before the verdict was recorded are not dropped: the
    # older fixture carries no `state` at all and its six ticks must still be
    # somewhere, or the chart and the headline disagree about the same offers.
    tookbars = {b['label']: b for b in took['took']}
    eq('rows with no recorded verdict get their own bar',
       tookbars.get('no verdict', {}).get('n'), '6')
    eq('...and the three real verdicts still show, empty',
       [tookbars.get(k, {}).get('n') for k in ('ACCEPT', 'CLOSE', 'PASS')],
       ['0', '0', '0'])
    # Nothing ticked is not "you took nothing". It is a driver who has never
    # pressed the button, and three empty bars would be a claim about their
    # shift made out of the absence of one.
    for name in ('unreadable', 'all hidden', 'genuinely empty'):
        eq('...and the section stays away with nothing ticked: %s' % name,
           got[name]['tookHead'], None)

    # --- what the search found, and what it was worth ------------------------
    #
    # The figures at the top of the page are the whole window's and do not move
    # when the box is typed into. "Do the Chattanooga runs pay?" is the question
    # somebody types a place in to ask, and the answer used to be a filtered
    # list and nothing else.
    s = got['searchable']['searches']
    chatt = s['chattanooga']['note'] or ''
    eq('a search narrows the list', s['chattanooga']['rows'], 5)
    ok_('...and says how many of how many (%r)' % chatt[:60],
        '5 of 9 offers match "chattanooga"' in chatt)
    # Over the four that could be counted, never the five that matched: with
    # the misread $84 back in, [$24, $24, $30, $30, $84] has a median of $30.
    ok_('...with the median of what it found, not the page\'s (%r)' % chatt[-90:],
        'Typical $27/hr across the 4 that could be counted' in chatt)
    # ...and the same set again. Counting the misread one would make it three.
    ok_('...and how many of those cleared the line',
        '2 of them clearing $25/hr' in chatt)
    # Net, like every figure on this page: $12.00 and $10.00 of pay, $2.00 of
    # running cost off each. The driver ticked a third — they took that job —
    # but the scanner misread the card, so its $28.00 is not money this page
    # will claim they earned.
    ok_('...and what was worked out of them, net (%r)' % chatt[-60:],
        'You marked 2 of them as taken, worth $18.00' in chatt)
    # A median of one offer is that offer. Calling it typical invites it to be
    # read as a pattern, which one job is not.
    one = s['soddy']['note'] or ''
    eq('a search matching one offer finds one', s['soddy']['rows'], 1)
    ok_('...and names it as a single job rather than a typical one (%r)'
        % one[-70:],
        'The one of them that could be counted paid $36/hr' in one)
    no_('...and does not call one offer typical', 'Typical' in one)
    # Rows that were set aside are still listed — that is the whole reason the
    # log keeps them — but there is no rate to give for them, and "median --"
    # would be a figure where there is none.
    none = s['dalton']['note'] or ''
    eq('offers that were all set aside are still listed', s['dalton']['rows'], 2)
    ok_('...and the note says there is no rate to give (%r)' % none[-70:],
        'not one of them could be counted' in none)
    no_('...rather than printing a dash as a rate', '--' in none)
    miss = s['nowhere at all']['note'] or ''
    ok_('a search matching nothing says so (%r)' % miss[:60],
        'Nothing in this stretch matches' in miss)
    eq('...and clearing the box takes the note away', s['']['note'], None)
    eq('...and puts every row back', s['']['rows'], len(SEARCHABLE))

    # --- by day of the week ------------------------------------------------
    #
    # Shown once the window holds a fortnight, on the driver's 4am-bounded
    # day, Monday first. Each fixture bar rests on three identical rates, so
    # a median landing on the right number is a median over the right rows.
    wk = got['weeks']
    ok_('the day-of-week chart appears over three weeks (%r)'
        % (wk['weekHead'] or '')[:60], wk['weekHead'] is not None)
    ok_('...saying how many days are behind it',
        'across 21 days' in (wk['weekHead'] or ''))
    eq('...Monday first, Sunday last',
       [b['label'] for b in wk['week']],
       ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'])
    # Three under every bar but Saturday, which has the 1am row as well —
    # grouped on the driver's day, not the calendar's. Grouped on the calendar
    # it is Sunday that would read 4.
    eq('...three offers under every bar, four under Saturday',
       [b['n'] for b in wk['week']], ['3', '3', '3', '3', '3', '4', '3'])
    wkbars = {b['label']: b['amount'] for b in wk['week']}
    eq('...Sunday at its own median', wkbars.get('Sun'), '$18')
    eq('...Monday at its', wkbars.get('Mon'), '$24')
    eq('...and Saturday at its', wkbars.get('Sat'), '$54')
    # The three set-aside Wednesdays at $300/hr are not in this. Over the raw
    # window they would make it $168.
    eq('...and Wednesday over the counted rows only', wkbars.get('Wed'), '$36')
    # A week of offers is one day per bar, and one day's median is already on
    # its day header — the chart would be the list again, drawn as a pattern.
    for name in ('verdicts', 'took six', 'searchable'):
        eq('...and it stays away over a single day: %s' % name,
           got[name]['weekHead'], None)
    eq('...with no bars drawn behind the hidden heading',
       got['verdicts']['week'], [])

    # --- a row no clock can read does not take the charts with it ----------
    #
    # The by-time-of-day pass indexed its eight-element block array with
    # `Math.floor(new Date(at).getHours() / 3)`, which is NaN for a stamp past
    # 8.64e15 — so the push threw, and everything drawn after it in the same
    # render never ran. That includes the two charts below it and the day
    # headers, on a page whose figures had already painted, so the failure
    # looked like a page with fewer charts rather than like a page that broke.
    # CLOCK_BELIEVABLE_UNTIL in server.js exists because such a row really
    # arrived; the server drops the LOW end of that range and not the high.
    nc = got['no clock']
    ok_('a row stamped past the end of time still draws the time-of-day chart '
        '(%r)' % (nc['blocksHead'] or '')[:70], nc['blocksHead'] is not None)
    # All eight bars, which is the half that says the chart DREW rather than
    # that the heading was merely unhidden.
    eq('...with all eight blocks on it', len(nc['blocks']), 8)
    # Four ordinary rows, three hours apart, so four different bars carry one
    # each and the unreadable row carries none. Counting them is what makes
    # this a check on the pass rather than on the exception handler: put the
    # old `blocks[Math.floor(hour / 3)]` back and these are 0.
    eq('...and the four readable rows are on four separate bars',
       sorted(b['n'] for b in nc['blocks']), ['0', '0', '0', '0', '1', '1', '1', '1'])
    # And the one that could not be placed is SAID, not dropped quietly. A row
    # vanishing from a figure with nothing naming it is this project's second
    # fault class, and "it threw" and "it was skipped" look the same from here
    # without this.
    ok_('...and the row that has no time is named rather than dropped quietly '
        '(%r)' % (nc['blocksHead'] or ''),
        '1 with an unreadable time left out' in (nc['blocksHead'] or ''))
    # ...and the charts that are drawn AFTER it in the same pass, which are
    # what the throw really cost.
    ok_('...and the charts below it were drawn too', nc['kinds'])
    # The ordinary window says nothing about unreadable times, or the clause
    # above is a sentence the page always prints.
    no_('a window with no such row says nothing about one (%r)'
        % (got['weeks']['blocksHead'] or ''),
        'unreadable time' in (got['weeks']['blocksHead'] or ''))

    # --- ...and the chart below that one, which never got the same guard ----
    #
    # The day-of-week pass walked `offers` itself and indexed its array with
    # `dayOf(r.at).getDay()`. That is NaN on a stamp past the end of time,
    # `week[NaN]` is undefined, and the push threw — inside a .then(), so the
    # TypeError went to load()'s .catch() and the page painted "Cannot reach
    # the scanner" over a journal the server had read perfectly and answered
    # 200 with. Nothing reached the console. It needs a fortnight of days AND
    # a corrupt stamp, and no feed here held both: 'no clock' is one day, so
    # `enoughDays` is false and the pass never ran.
    wknc = got['weeks no clock']
    eq('a fortnight of days and a stamp no clock can read still renders',
       wknc['nothing'], None)
    ok_('...with the headline still on it (%r)' % (wknc['headline'] or '')[:60],
        wknc['headline'])
    ok_('...and the day-of-week chart drawn', wknc['weekHead'] is not None)
    # The same seven bars as the clean window, with the same medians and the
    # same counts. This is the half that says the row was SKIPPED rather than
    # that the page merely survived: fold it into a bucket and Sunday reads 4,
    # or its rate lands on whichever weekday `week[NaN]` happened to become.
    eq('...over exactly the bars the clean window has',
       wknc['week'], wk['week'])
    # ...and the offers below, which the .catch() also blanked.
    eq('...and the log is still there',
       len(wknc['days']) > 0 and wknc['rows'] > 0, True)
    # Said, not dropped quietly — the same sentence the chart above it carries,
    # because a reader of this chart should not have to have read that heading.
    ok_('...and the row it left out is named on this chart too (%r)'
        % (wknc['weekHead'] or ''),
        '1 with an unreadable time left out' in (wknc['weekHead'] or ''))
    no_('...while the clean window says nothing about one (%r)'
        % (wk['weekHead'] or ''),
        'unreadable time' in (wk['weekHead'] or ''))

    # --- rides against shop orders, split on what the card said -------------
    #
    # The bar labelled Shop took any single-leg card carrying an item count,
    # which is a fact about the OCR rather than about the card — and the
    # paragraph over the chart says in as many words that it does not do that.
    # On the owner's week that made 26 of the Shop bar's 49 rows cards nobody
    # ever shopped for, and moved its median $1.37.
    kb = {b['label']: b for b in (got['kinds']['kindBars'] or [])}
    eq('the three kinds are drawn', sorted(kb), ['Not stated', 'Rides', 'Shop'])
    eq('...Shop holds the cards that said so, and only those',
       kb.get('Shop', {}).get('n'), '2')
    eq('...at their own median, not one dragged by cards from another pile',
       kb.get('Shop', {}).get('amount'), '$24')
    eq('...Rides holds the two-leg cards', kb.get('Rides', {}).get('n'), '2')
    eq('...at theirs', kb.get('Rides', {}).get('amount'), '$36')
    # An item count on a single-leg card is not a shop chip. These two are
    # what the old rule put under Shop, and where they belong is the bar for
    # cards that did not say — the one the paragraph above the chart was
    # written to defend.
    eq('...and a single-leg card with an item count and no chip is unstated',
       kb.get('Not stated', {}).get('n'), '2')
    eq('...at its own median too', kb.get('Not stated', {}).get('amount'), '$60')

    # --- which offers to list, and in what order ---------------------------
    #
    # Both act on the list alone. The figures above are the whole window's and
    # must stay so — a selection fed into the advice block recommends halving
    # the target off two taps. VERDICTS is r0..r7: taken r0-r4 and r6 (r6
    # hidden), ACCEPT r0 r4 r5 r6, CLOSE r1 r2, PASS r3 r7, and r6 is the one
    # set-aside row. Ranked by $/hr the top is r4 at $36; by pay it is r4 at
    # $14.00; by length every row is 20 minutes so the tie falls to newest.
    p = v['picks']
    eq('the Took chip lists the ticked rows and nothing else',
       sorted(p['took']['rows']), ['r0', 'r1', 'r2', 'r3', 'r4', 'r6'])
    ok_('...and the sentence says what was picked (%r)' % (p['took']['note'] or '')[:60],
        '6 of 9 offers you marked as taken' in (p['took']['note'] or ''))
    eq('PASS lists what the panel said PASS to', sorted(p['no']['rows']), ['r3', 'r7'])
    eq('CLOSE lists what it hedged', sorted(p['warn']['rows']), ['r1', 'r2'])
    eq('ACCEPT lists what it cleared, by the verdict on the row',
       sorted(p['go']['rows']), ['r0', 'r4', 'r5', 'r6'])
    # The chip and the chart above it must count the same rows: the chart's
    # PASS bar says 1 taken, and the one taken row under this chip is r3.
    eq('...so a bar up there has the same rows as its chip down here',
       [r for r in p['no']['rows'] if r in ('r0', 'r1', 'r2', 'r3', 'r4', 'r6')], ['r3'])
    eq('Set aside lists the row that could not be counted', p['aside']['rows'], ['r6'])
    # offer(i) is ten minutes apart, counting backwards from NOW, and every row
    # is twenty minutes long — so a ticked row's window holds exactly the one
    # row after it in time. r4, r3, r2 and r1 are ticked and each covers the
    # next: r3, r2, r1, r0. r6 is ticked too but hidden, and Advice.busy is
    # built over usable() rows only, so its window does not exist and r5 is
    # not inside it. The chip must agree with the "during a job" tag on the
    # rows, which is the same join.
    eq('During a job lists exactly the rows inside a ticked window',
       sorted(p['busy']['rows']), ['r0', 'r1', 'r2', 'r3'])
    ok_('...and the sentence says so (%r)' % (p['busy']['note'] or '')[:70],
        '4 of 9 offers that arrived during a ticked job' in (p['busy']['note'] or ''))
    eq('All puts every row back', len(p['all']['rows']), 9)
    # The typed one says so, and nothing else does.
    typed = {a['id']: a['worth'] for a in v['arrivals']}
    ok_('a row typed on the keypad says so (%r)' % (typed.get('r8') or '')[:50],
        'typed on the keypad' in (typed.get('r8') or ''))
    no_('...and a row the camera read does not',
        any('typed' in (w or '') for i, w in typed.items() if i != 'r8'))
    eq('...and takes the sentence away', p['all']['note'], None)
    ok_('newest keeps the day headers', p['all']['days'] >= 1)
    eq('Best $/hr ranks the list', p['sort:perHour']['rows'][0], 'r4')
    eq('...and a ranking has no days', p['sort:perHour']['days'], 0)
    eq('Highest pay ranks by the card', p['sort:pay']['rows'][0], 'r4')
    ok_('Longest ranks by minutes, ties to newest (%s)' % p['sort:minutes']['rows'][:2],
        p['sort:minutes']['rows'][0] == 'r0')
    ok_('Newest restores the day headers', p['sort:newest']['days'] >= 1)
    # Twelve chip and sort presses and five keystrokes, and the expensive
    # parts of the page ran for none of them. They used to run for every one:
    # the whole render, measured at 150-224ms a keystroke over 3,000 offers on
    # a desktop browser, and the Pi's own browser is several times slower.
    at_load, after = v.get('callsAtLoad') or {}, v.get('callsAfterAll') or {}
    ok_('the advice replay ran when the page loaded (%s)' % at_load.get('advise'),
        (at_load.get('advise') or 0) >= 1)
    ok_('...and the busy join too', (at_load.get('busy') or 0) >= 1)
    eq('a chip, a sort or a keystroke re-runs neither',
       (after.get('advise'), after.get('busy')),
       (at_load.get('advise'), at_load.get('busy')))
    eq('a chip and a ranking compose', p['took+perHour']['rows'][0], 'r4')
    eq('...over the picked rows only', len(p['took+perHour']['rows']), 6)
    # A chip that picks nothing says so in a sentence of its own. The clause
    # that follows a count does not survive "Nothing": the first version of
    # this printed "Nothing in this stretch match".
    empty = took.get('emptyPick') or {}
    eq('a chip picking nothing lists nothing', empty.get('rows'), 0)
    ok_('...and says so, grammatically (%r)' % (empty.get('note') or '')[:60],
        'The panel said PASS to nothing in this stretch' in (empty.get('note') or ''))

    # --- the list on the nothing-usable path ------------------------------
    #
    # A window whose every row was set aside takes an early exit in render()
    # that used to build its own list, so the chips, the order and the search
    # box did nothing there. It goes through the same list code now.
    aside_feed = got['all aside']
    eq('every set-aside row is listed', len(aside_feed['asIs']['rows']), 3)
    eq('the Took chip works on the nothing-usable path',
       aside_feed['tookChip']['rows'], ['r1'])
    ok_('...with the sentence (%r)' % (aside_feed['tookChip']['note'] or '')[:60],
        '1 of 3 offers you marked as taken' in (aside_feed['tookChip']['note'] or ''))
    eq('...and so does the order', aside_feed['byPay']['rows'], ['r2', 'r1', 'r0'])
    eq('...without day headers', aside_feed['byPay']['days'], 0)

    # --- a row refused for a leg, and the two sentences it must not borrow -
    #
    # The row used to arrive here saying `state: 'doubt'` and `doubt: null`,
    # because journal.py worked the verdict out a second time with a function
    # that can only see three numbers. The page then explained it with the first
    # branch that matched — a crop that clipped the card — which is a specific
    # claim about a card that was fully in the crop, and its verdict line fell
    # through to "the reading is outside anything a real offer does", which is
    # false of every figure in it.
    leg = (got.get('leg') or {}).get('detail') or {}
    ok_('the refused row was found', bool(leg))
    if leg:
        ok_('...and is set aside', leg.get('aside'))
        whole = leg.get('all') or ''
        ok_('...explained by the leg that never read (%r)'
            % whole[max(0, whole.find('leg')) - 30:][:90],
            'could not time' in whole)
        ok_('...with how much of the journey that was', '7.8 mi' in whole)
        # The two it must NOT borrow. Both were what the page really said.
        ok_('...not as a crop that clipped the card',
            'was in the crop' not in whole)
        ok_('...and not as a figure outside anything a real offer does',
            'outside anything a real offer does' not in whole)
        ok_('...nor flagged as a figure out of range',
            'outside the range a real offer falls in' not in whole)
        # Said plainly where the verdict would be, because "no verdict" with a
        # dash beside it reads as "this was never recorded".
        ok_('...and the verdict line says a leg never read',
            'a leg of the journey never read' in whole)

    # --- what the reader actually read -----------------------------------
    #
    # On the wire for every row and thrown away by this page, so the one
    # screen somebody opens to ask "why does this row say $30?" was the one
    # that could not answer. Only the misread row carries text in the fixture,
    # so a page printing it on every row would fail the second check.
    by_id = {a['id']: a for a in got['searchable']['arrivals']}
    read = by_id.get('r8', {})
    ok_('a row carries what the reader read (%r)' % (read.get('cardtext') or '')[:40],
        read.get('cardtext') and 'Deliver by 7:42 PM' in read['cardtext'])
    # OCR output is text, never markup: the '<total>' the reader produced has
    # to come back as five characters, not as an element.
    ok_('...as text, with the angle bracket the reader produced still in it',
        '<total>' in (read.get('cardtext') or ''))
    eq('...and not as markup', read.get('cardtextTags'), 0)
    eq('...and rows with no text carry no box at all, empty or otherwise',
       [a['id'] for a in got['searchable']['arrivals'] if a['hasCardtext']], ['r8'])

    # --- rows read before the rig had a clock ------------------------------
    #
    # In no window whichever range is pressed, and until now said nowhere on
    # this page: dropped without a word on Today/7/30 and back as a phantom
    # 1970 day on All. The server now counts them; the page has to say so.
    ok_('offers read before the clock was set are named (%r)'
        % ' | '.join(c[:60] for c in got['searchable']['caveats']),
        any('2 offers were read before the rig’s clock had been set' in c
            for c in got['searchable']['caveats']))
    no_('...and not when there are none',
        any('clock had been set' in c for c in got['took six']['caveats']))

    # A different and worse thing, and it may not be folded into the sentence
    # above. A row with no usable date is still in the file and can be read; a
    # torn line is an offer that is gone, cannot be recovered, and is copied to
    # the machine at home as a hole. Both were silent; only one of them is
    # about a clock.
    _cav = got['searchable']['caveats']
    ok_('lines that could not be read at all are named (%r)'
        % ' | '.join(c[:70] for c in _cav if 'could not be read' in c)[:120],
        any('3 lines in the journal file could not be read' in c for c in _cav))
    ok_('...saying those offers cannot be got back',
        any('cannot be recovered' in c for c in _cav))
    ok_('...and what a growing number of them means',
        any('card starting to fail' in c for c in _cav))
    # Told apart from the clock note, which sits beside it in the same list.
    ok_('...without being confused with a row that merely has no date',
        not any('could not be read' in c and 'clock had been set' in c
                for c in _cav))
    no_('...and nothing is said when the file is whole',
        any('could not be read at all' in c for c in got['took six']['caveats']))

    # --- gross rates and net ones in one median ----------------------------
    #
    # The note about running costs read the NEWEST row's cost per mile and
    # stated it as a fact about every rate on the page. The rig subtracts
    # $0.30/mi by default; the keypad and the phone's scanner subtract nothing
    # and have no way to ask the rig what it uses. Both write into the same
    # file, so the sentence was true of one pile and the exact opposite of the
    # truth for the other.
    _mix = got['mixed cost']['caveats']
    _said = ' | '.join(c for c in _mix if 'running cost' in c)[:160]
    ok_('a window holding both gross and net rates says so (%r)' % _said,
        any('4' in c and '7' in c and 'did not' in c for c in _mix
            if 'running cost' in c))
    ok_('...naming the rate that was actually taken off',
        any('$0.30/mi' in c for c in _mix))
    ok_('...and warning the figures above mix the two',
        any('mix what offers paid before the car' in c for c in _mix))
    # One claim about running costs, not two. A page that pushed the plain
    # sentence AND the mixed one would pass every check above while telling
    # the reader both that all seven rates are net and that three of them are
    # not — which is the original bug back, wearing the new wording.
    eq('...and makes exactly one claim about them',
       len([c for c in _mix if 'running cost' in c]), 1)
    # ...and it describes the rows the figures are made of, not the window.
    #
    # This was handed `kept` — every row, including the ones the note directly
    # above it has just said were "left out of the figures above". So the
    # denominator counted the excluded rows (26 of 1,166 on the owner's own
    # week), and where a set-aside row came off the keypad at no running cost
    # the sentence announced a mixing the figures do not have: four net rates
    # described as "4 of these 6 ... so the figures above mix what offers paid
    # before the car with what they paid after it".
    _as = got['aside cost']['caveats']
    _asr = [c for c in _as if 'running cost' in c]
    ok_('the set-aside rows are named as left out (%r)'
        % ' | '.join(c[:50] for c in _as)[:120],
        any('2 readings left out of the figures above' in c for c in _as))
    eq('...and exactly one sentence describes the running costs', len(_asr), 1)
    eq('...describing the four rows the figures are made of, and only those',
       _asr and _asr[0], 'Rates are after $0.30/mi of running costs.')
    no_('...rather than counting the excluded rows into its own denominator',
        any('6' in c for c in _asr))
    no_('...or calling four net rates a mixture',
        any('mix what offers paid before the car' in c for c in _asr))
    # ...and the same sentence may not appear over a window where every row
    # was written by the same thing, or the check above passes on a page that
    # cries mixture at everything.
    # --- the escape hatch the page points at --------------------------------
    #
    # The list stops at LOG_MAX and the window stops at the server's JSON cap,
    # and the sentence under both says "use the CSV for the rest". That link
    # used to carry the server's own ceiling — 20000 — on the reasoning that a
    # ceiling is not a default. A ceiling is still a cap: past it the download
    # kept the newest rows and dropped the oldest, silently, which is the half
    # a driver exports a year to look at.
    #
    # `limit=0` is uncapped: the handler's test is `if (limit && ...)`.
    _csv = (got.get('took six') or {}).get('csv') or ''
    ok_('the CSV link is uncapped (%r)' % _csv, 'limit=0' in _csv)
    no_('...and does not carry the JSON cap', 'limit=5000' in _csv)
    no_('...nor the server ceiling', 'limit=20000' in _csv)

    # --- one job on a map, without leaving the log -------------------------
    #
    # "It would be convenient if it could do it in the existing program page.
    # As each route click opens a new tab currently." Three taps down the log
    # was three tabs, and on a phone each one meant finding your place again
    # in a list of ninety.
    _m = got['mapped']
    # The page must not send a single place anywhere on load. Some of these are
    # where customers live, and the whole arrangement is that the driver
    # decides, one job at a time.
    eq('the offers page geocodes nothing until asked',
       _m['beforeAny']['asked'], [])
    no_('...and shows no map', _m['beforeAny']['open'])
    # Three controls on each job that named both ends, and ONE on the job the
    # card only named a pickup for — a route control there would open a map of
    # a journey to nowhere, which costs a tap and a moment's belief.
    ok_('the route control reached the job it names', _m['tapped'])
    eq('a job with both ends gets all three controls (%r)' % _m['controls'],
       sorted(c.split(':')[0] for c in _m['controls'] if c.startswith('r0/')),
       ['r0/both', 'r0/dropoff', 'r0/pickup'])
    eq('...and a job that named only a pickup gets just the one',
       [c.split(':')[0] for c in _m['controls'] if c.startswith('r1/')],
       ['r1/pickup'])
    eq('...with one control per named end and no more',
       len(_m['controls']), 13)

    # An address the driver revealed on their phone, on the row it belongs to.
    #
    # It reaches the row as a note, the way a tick does, and until now the page
    # had nowhere to put it: "Where" is built from `places`, which is what the
    # CARD printed, and a card printing "Customer dropoff" prints no address at
    # all. So the one offer whose destination is known only because the driver
    # asked for it showed no destination.
    _r3 = [c for c in (_m['said'] or []) if c.startswith('r3:')]
    ok_('an address read off the phone is shown on its row (%r)'
        % (_r3 or [''])[0][-90:],
        _r3 and 'read off your phone' in _r3[0] and 'Oak Ln, Marietta' in _r3[0])
    # ...and said to have been read rather than printed. The two are different
    # degrees of evidence, and the difference is why this one is worth having.
    _r0 = [c for c in (_m['said'] or []) if c.startswith('r0:')]
    no_('...and a destination the card itself printed is not claimed as one',
        _r0 and 'read off your phone' in _r0[0])

    _r = _m['route']
    ok_('pressing route opens the sheet in this page', _r['open'])
    ok_('...naming both ends (%r)' % _r['where'],
        'Chastain' in _r['where'] and 'Oak Ln' in _r['where'])
    eq('...and looking up exactly those two', len(_r['asked']), 2)
    # Boxed around where the car was, which is the whole of the improvement:
    # "usually the pickup/restaurant is the closest one to me".
    ok_('...near where the car actually was', all(_r['boxes']))
    eq('...drawing a pin for each', _r['pins'], 2)
    # The one question a pin cannot answer. Driving time with real traffic is
    # why the route link existed at all, so it survives — moved from the row,
    # where it cost a tab every time, into the sheet.
    ok_('...and the way to real driving directions is still there (%r)' % _r['out'],
        _r['out'] and 'google.com/maps/dir' in _r['out'])
    # What the sheet is FOR: a straight line cannot beat the road.
    ok_('...with the straight line measured against the card (%r)' % _r['note'],
        'straight line' in _r['note'] and 'card said' in _r['note'])

    eq('the log is still underneath it', _m['stillThere']['rows'], 5)
    ok_('...given room so its last row can still be reached',
        _m['stillThere']['padded'])
    eq('...and nothing navigated anywhere', _m['stillThere']['url'], '/journal.html')
    no_('pressing the same control again puts the sheet away', _m['shut']['open'])

    # A place the geocoder cannot find is the commonest real failure — a badly
    # misread street — and an empty map with no caption looks exactly like a
    # map that is still loading.
    ok_('an unplaceable address says so rather than showing nothing (%r)'
        % _m['lost']['note'], 'found nothing' in _m['lost']['note'])

    # One end on the map and one that could not be placed — the commonest of
    # the three shapes, and the one the sheet described worst. It named BOTH
    # colours over a map with one pin on it, so a driver looking for the amber
    # one went on looking, and it never said which end was missing or why.
    _half = _m['halfPlaced']
    eq('one end placed draws one pin', _half['pins'], 1)
    ok_('...and the caption names the pin that is actually there (%r)'
        % _half['note'], 'Chastain' in _half['note'])
    ok_('...by the colour it was actually drawn in', 'green pin' in _half['note'])
    no_('...and does not name a colour that is not on the map',
        'amber' in _half['note'])
    # Which end is missing, and which of the three kinds of missing it is —
    # only one of them is about the rig's reading, and the other two are about
    # the network. The page splits this three ways when NOTHING places; it said
    # nothing at all when one end did.
    ok_('...naming the end that is missing', 'Zzqx' in _half['note'])
    ok_('...and why, in the words that blame the reading rather than the link',
        'misread' in _half['note'])

    # Two pins, a figure, and no way to hold one against the other. The sheet's
    # one job is to say a straight line cannot beat the road — but r4's reading
    # is suspect, so its three miles was never the road, and "one of these pins
    # is wrong" would be an accusation resting on a number the rig had already
    # refused. Both pins here are exactly where they belong.
    _unj = _m['unjudged']
    ok_('a pair the rig will not vouch for is drawn (%r)' % _unj['note'], _unj['open'])
    no_('...and not accused of anything', 'pins is wrong' in (_unj['note'] or ''))
    no_('...in the words that would have accused it',
        'cannot be right' in (_unj['note'] or ''))
    # Withheld, not silently dropped: a sheet that just stopped saying anything
    # reads exactly like a pair that was checked and passed.
    ok_('...and says why it cannot be settled', 'suspect' in (_unj['note'] or ''))
    ok_('...naming the figure it is declining to use',
        '3 mi' in (_unj['note'] or ''))
    ok_('...while still giving the straight line it measured',
        'straight line' in (_unj['note'] or ''))

    # --- a range press that cannot be answered ------------------------------
    #
    # The commonest failure this page has: it is read over Tailscale from a
    # machine in a car, and any range button can land while the link is down.
    # The handler clears the log, the charts, the pairings, the headline and
    # the caveats and paints "Cannot reach the scanner" — and left the three
    # $/hr figures standing above all of it, in the largest type on the page,
    # last window's answer to a question the driver has since asked
    # differently, with nothing marking it stale. The empty-window path has
    # always set all three to '--'; this one was written separately and did
    # not.
    _fail = got['dots']['afterFailedLoad']
    ok_('a failed range press says the scanner cannot be reached (%r)'
        % (_fail['nothing'] or '')[:60],
        'Cannot reach the scanner' in (_fail['nothing'] or ''))
    eq('...and the three big figures are cleared with everything else',
       _fail['figures'], ['--', '--', '--'])
    eq('...as the headline already was', _fail['headline'], '')
    eq('...and the log with it', _fail['rows'], 0)
    # The control: the same three figures were real before the press, so the
    # check above is about the failure and not about a page that never fills
    # them in.
    no_('...having been real figures a moment earlier (%r)'
        % ' '.join(got['dots']['figures']),
        any(f == '--' for f in got['dots']['figures']))

    _one = [c for c in got['took six']['caveats'] if 'running cost' in c]
    ok_('a window written by one device gets the plain sentence (%r)'
        % ' | '.join(_one)[:100],
        any('Rates are after $0.33/mi of running costs.' == c for c in _one))
    no_('...and is not described as a mixture',
        any('did not' in c for c in _one))
    eq('...also exactly once', len(_one), 1)

finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d offers-page checks passed' % ok)
sys.exit(1 if bad else 0)
