"""Where the offer card actually is on the screen, found from its button up.

The driver draws two boxes on the live view: the phone's screen, and the card
inside it (cropbox.py). The card box is drawn ONCE, round whichever card was up
at the time, and every later card is read through it. A card taller than that
one puts its payout above the box. On 8 Oct an Uber "Early look • Order in
progress" card's $14.48 sat across the top edge of a box drawn round a shorter
"Exclusive" card; the reader got "gg Pit." for it, the rest of the card read
perfectly, and the panel said there was no offer.

So this looks for the card the box was meant to hold. Not by reading — the
reader already failed on the crop — but by its shape, which every offer card
the rig reads shares: a button bar (Accept, Match) near the bottom, a flat
background, and an edge where the map starts. The search starts at the button
because the button is where the drawn box is still right: whatever the card's
height, it sits on the same bar at the bottom of the screen.

    1. the bar, within BAR_ABOVE / BAR_BELOW of the drawn box's bottom;
    2. the card's sides, out from the bar's ends along the rows above it;
    3. the card's top, walking up from the bar until the background stops.

`sure` is the only answer a caller may act on, and it is given only when every
test below passes; `why` names the first that refused. Each is reached by a
picture in rpi/test_cardfind.py made to need it:

  - a full-width dark band is the phone's own navigation bar, never a button;
  - a band that is not solid is a picture strip, never a button;
  - the card must be 15–85% of the screen tall. (At least half of it wide is
    not a test of its own: the bar has to span most of the screen to be found
    at all, and the card is at least as wide as its bar.);
  - its body must be mostly background, and carry at least three text rows;
  - it must not run off the top of the screen box — then the top is unknown;
  - its top edge must start abruptly and square to the box: a phone rolled two
    degrees inside the box it was drawn round slants the edge across rows,
    and a box placed from a slanted edge cuts one end of every line.

Glare is the one that shaped the method. Every comparison is against a
reference taken from the card itself NEAR the pixels being judged — a block
of columns, carried up the card as it is walked — never against one level for
the whole screen. Measured over 432 rendered frames under a glare blob or a
band of glare (testcards.degrade 'glare' and 'sheen'), one level for the whole
card, never followed, was sure of 110 and wrong about 6 of those: a band of
glare across a light card lifted the map above it to the card's own white,
and the top was placed 2% of the screen up into the map — square, sure, and
wrong. References per block, followed up the card: sure of 348, wrong about
none.

No deskew. The box is drawn square round the screen and the warp makes it
square, so the card is square in it, or the phone has moved inside the box —
which is a reason to be unsure, not a thing to correct.

Pure and stateless: a grey screen and a box in, an answer out. Nothing is
remembered between calls, so it can be wrong about one frame and right about
the next, and cannot drift.
"""

import cv2
import numpy as np

# The finder works on a small copy. A card's edge and its button are coarse
# features: at 600 rows a text line is still several rows tall and the bar is
# about thirty. Measured on the development box over 36 warped screens, a look
# costs 27.5ms median against 309ms for the read it follows (8.9%), and is
# only paid on a read that found a journey and no payout.
FIND_HEIGHT = 600

# Where the bar is looked for: from this far above the drawn box's bottom to
# this far below it, as fractions of the screen box's height. The bar sits at
# the bottom of the screen whatever the card's height, so the drawn box's
# bottom is the one edge of it that a taller card does not move.
BAR_ABOVE = 0.20
BAR_BELOW = 0.05

# The bar's own height, as a fraction of the screen's: Uber's is about 4.7%.
BAR_MIN = 0.015
BAR_MAX = 0.09
# How far out of level an edge may run across the screen and still be one edge,
# as a fraction of the height: two degrees across a card is about 1.2%.
SLANT = 0.012

# Column blocks across the screen. Each is judged against its own reference.
BLOCKS = 12

# How far, in grey levels, a block has to move across SLANT rows for it to
# count as an edge, and in how many of the blocks at once.
EDGE = 20
EDGE_SHARE = 0.70

# A pixel within this of its block's median is "that colour": what solidity
# and background are measured with.
TOL = 14

# The widest gap in a bar's colour that is still the bar, as a share of the
# screen's width: the word on it, which defocus can spread over most of the
# bar's height ("Match" is 11% of the width).
GAP = 0.15

# The share of a bar's block-rows that must be solid, and how far its colour
# may step from one block to the next — a glare gradient is gentle, a picture
# is not.
SOLID = 0.60
BAR_STEP = 22

# How far from the card's own background a block of a row may be and still be
# card, while walking up. Light card on light map is the closest pair the rig
# sees: 255 against 232, so this has to sit under 23.
WALK = 12
# How much of each new row is folded into a block's reference as the walk
# goes up — enough to follow a glare gradient, not enough to follow an edge.
FOLLOW = 0.5
# ...and how many rows in a row, as a share of the height, must be off the
# card before the top is called. A hairline divider is not the top.
PERSIST = 0.006

# The share of blocks that must have left the card for a row to be off it, and
# the share of a block that must be the card's background for the block to be
# card. Nearly all of them, not most: a map starts across the whole width at
# once, while a line of text — bold, blurred by a soft focus until its gaps
# close up — takes the left half or two thirds and leaves the rest of the row
# as card. At "most" (60%), defocus ended every tall card at its journey line.
OFF_ACROSS = 0.85
SOME_BACKGROUND = 0.25

# The tests on the answer.
MIN_HEIGHT, MAX_HEIGHT = 0.15, 0.85
MIN_BACKGROUND = 0.55
MIN_TEXT_ROWS = 3
INK = 30
SQUARE = 0.006             # the spread of the top across blocks, of the height


def _unsure(why):
    return {'sure': False, 'box': None, 'why': why}


def _blocks(g, left, right, k):
    """Per-row medians and solidity of `k` column blocks spanning [left, right)."""
    width = max(k, right - left)
    bw = max(1, width // k)
    span = g[:, left:left + bw * k].astype(np.int16)
    cells = span.reshape(g.shape[0], k, bw)
    med = np.median(cells, axis=2)
    solid = (np.abs(cells - med[..., None]) <= TOL).mean(axis=2)
    return med, solid, bw


def _widest(mask, gap, least=3):
    """(first, last) of the widest run of True in `mask`, or None.

    Runs shorter than `least` are dropped first — the one anti-aliased column
    at a card's edge that happens to sit near the bar's colour — and then runs
    up to `gap` apart are joined: the word on the button, which defocus can
    spread over most of the bar's height.
    """
    runs, lo = [], None
    for i, on in enumerate(list(mask) + [False]):
        if on and lo is None:
            lo = i
        elif not on and lo is not None:
            if i - lo >= least:
                runs.append([lo, i - 1])
            lo = None
    if not runs:
        return None
    joined = [runs[0]]
    for r in runs[1:]:
        if r[0] - joined[-1][1] - 1 <= gap:
            joined[-1][1] = r[1]
        else:
            joined.append(r)
    best = max(joined, key=lambda r: r[1] - r[0])
    return int(best[0]), int(best[1])


def _bar(g, r0, r1):
    """The button's (top, bottom, colour, left, right), or a reason there is none.

    Candidate top edges are rows where most blocks step together; the bar runs
    from one to the next step back. The highest candidate that passes is the
    button. When none passes, the reason given is the HIGHEST candidate's: it
    is the one nearest where a button would be, and a lower one failing as
    well is only the card under it.

    Three things a band has to be, each because something else was a band:

      - solid: a picture strip has edges top and bottom like a button, and is
        all texture inside;
      - short of the screen's sides: Android's own bar runs edge to edge;
      - set in a card: just above it, the card carries on past both its ends.
        The strip of card UNDER a button is a band between two edges too,
        solid and short of the screen's sides, and when the button above it
        was refused for any reason that strip was taken in its place: the walk
        up from it ended on the button a few rows higher, and the reason given
        was about the top of a card that was never found. Above that strip,
        past its ends, is the map.
    """
    h, w = g.shape
    a, b = int(0.05 * w), int(0.95 * w)
    med, solid, _ = _blocks(g, a, b, BLOCKS)
    lo, hi = int(BAR_MIN * h), int(BAR_MAX * h)
    # The step is taken over SLANT rows rather than one, so that a bar whose
    # edge is not quite level — a phone turned a degree or two inside its box —
    # still steps in most blocks at once. Over a single row, a 2° roll put the
    # edge in different rows in different blocks, no row had most of them, and
    # the roll came back as "no button" rather than as the slanted top that
    # the walk is built to refuse it for.
    slant = max(2, int(round(SLANT * h)))
    step = np.zeros_like(med)
    step[slant:] = med[slant:] - med[:-slant]
    up = (np.abs(step) >= EDGE).mean(axis=1) >= EDGE_SHARE
    tops = [r for r in range(max(slant, r0), min(h, r1)) if up[r] and not up[r - 1]]
    first = None

    def refuse(why):
        return first or why

    for start in tops:
        sign = np.sign(np.median(step[start]))
        # ...and its bottom, the next row where most blocks step back the
        # other way, or the bottom of the screen.
        end = None
        for r in range(start + lo, min(h, start + hi + 1)):
            back = (np.abs(step[r]) >= EDGE) & (np.sign(step[r]) == -sign)
            if back.mean() >= EDGE_SHARE:
                end = r
                break
        if end is None:
            if lo <= h - start <= hi:
                end = h
            else:
                continue
        if not lo <= end - start <= hi:
            continue
        # Its inside: clear of both edges by the slant they may run at, so a
        # bar on a phone turned inside its box is judged on rows that are all
        # bar, and is left for the walk to refuse by its slanted top.
        inner = slice(start + slant, max(start + slant + 1, end - slant))
        colour = np.median(med[inner], axis=0)
        # Solid: most of each block is one colour, in most blocks, on most
        # rows — the text on a button is a small part of it, a picture is all
        # texture — and one colour from block to block, bar the two outermost,
        # where a bar's rounded end falls when the phone has turned a little.
        if (np.median(solid[inner], axis=0) >= SOLID).mean() < EDGE_SHARE \
                or np.abs(np.diff(colour[1:-1])).max() > BAR_STEP:
            first = refuse('the band near the bottom is not solid \u2014 a picture, '
                           'not a button')
            continue
        level = float(np.median(colour))
        # Its ends: the widest run of columns most of which, top to bottom of
        # the band, are the band's colour as its nearest blocks have it — so a
        # glare gradient along the bar is followed — joined across gaps up to
        # GAP wide, so the word on the button is crossed rather than taken for
        # an end (see _widest). Both were tried and failed first: matching one colour put
        # the ends wherever glare had moved the bar seven levels, and walking
        # the band's median row out from the middle stopped at the "M" of
        # "Match", a sixth of the way along.
        centres = a + (np.arange(BLOCKS) + 0.5) * ((b - a) / float(BLOCKS))
        along = np.interp(np.arange(w), centres, colour)
        share = (np.abs(g[start:end].astype(np.float32) - along) <= TOL).mean(axis=0)
        run = _widest(share >= 0.5, max(1, int(GAP * w)))
        if run is None or run[1] - run[0] < EDGE_SHARE * (b - a):
            first = refuse('the band near the bottom is not solid \u2014 a picture, '
                           'not a button')
            continue
        bar_l, bar_r = run
        # Short of the screen's sides.
        if bar_l <= 1 and bar_r >= w - 2:
            first = refuse('only a full-width band there \u2014 the phone\'s own bar, '
                           'not a button')
            continue
        # Set in a card: in the rows just above the band, the same just
        # outside each of its ends as just inside it — the card carries on
        # past the button's ends. Over the card under a button, past its ends
        # is the map. Asked in the same rows on both sides of each end, a few
        # columns apart, so neither a glare gradient across the card nor one
        # down it can answer it: compared with the band's own rows instead,
        # the slope of a band of glare down the card was enough to refuse a
        # button on 106 of 432 glared frames.
        above = slice(max(0, start - slant - lo), max(1, start - slant))
        if bar_l < 6 or bar_r > w - 7 or \
                abs(float(np.median(g[above, bar_l - 5:bar_l - 2]))
                    - float(np.median(g[above, bar_l + 2:bar_l + 5]))) > WALK or \
                abs(float(np.median(g[above, bar_r + 3:bar_r + 6]))
                    - float(np.median(g[above, bar_r - 4:bar_r - 1]))) > WALK:
            first = refuse('the band near the bottom is not set in a card \u2014 the '
                           'card under a button, not the button')
            continue
        return (start, end, level, bar_l, bar_r)
    return refuse('no button bar near the bottom of the card box')


def _side(profile, start, direction):
    """Walk a column profile out from `start` until the card's background stops."""
    n = len(profile)
    ref = float(np.median(profile[max(0, start - 3):min(n, start + 4)]))
    c = start
    last = start
    while 0 <= c + direction < n:
        c += direction
        if abs(profile[c] - ref) <= WALK:
            ref += FOLLOW * (profile[c] - ref)
            last = c
        elif 0 <= c + direction < n and abs(profile[c + direction] - ref) > WALK:
            break
    return last


def _walk(g, left, right, b0, s0, s1):
    """Up from the bar to the card's top.

    Returns (top, starts, background, text_rows): the card's top row (None if
    the walk reached the screen's own top), the row at which each block of
    columns left the card, the share of the body that was the card's own
    background, and how many lines of text were crossed on the way.

    Each block of columns is judged against its own reference, taken from the
    blank strip above the bar and carried up the card a row at a time — only
    ever from the pixels that matched it, so it follows a glare gradient and
    not the text. A block is card while some of it is still that background:
    a line of bold text at this size leaves a third of its block showing
    through, and a map leaves none. Judging by the block's median instead was
    the first thing tried, and a line of 32px bold text pulled half the blocks'
    medians off the background for five rows — every card ended at its own
    second line of text.
    """
    h = g.shape[0]
    k = BLOCKS - 2
    bw = max(1, (right - left) // k)
    span = g[:, left:left + bw * k].astype(np.int16).reshape(h, k, bw)
    ref = np.median(span[s0:s1], axis=(0, 2)).astype(np.float32)
    persist = max(2, int(round(PERSIST * h)))
    off_since = [None] * k
    off_run = 0
    shares, inked = [], []
    r = b0 - 1
    while r >= 0:
        dist = np.abs(span[r] - ref[:, None])
        near_px = dist <= WALK
        share = near_px.mean(axis=1)
        near = share >= SOME_BACKGROUND
        for j in range(k):
            if near[j]:
                off_since[j] = None
            elif off_since[j] is None:
                off_since[j] = r
        if (~near).mean() < OFF_ACROSS:
            got = np.where(near_px, span[r], 0).sum(axis=1) / np.maximum(1, near_px.sum(axis=1))
            ref = np.where(near, ref + FOLLOW * (got - ref), ref).astype(np.float32)
            off_run = 0
            shares.append(float(share.mean()))
            inked.append(bool((dist > INK).mean() >= 0.01))
        else:
            off_run += 1
            if off_run >= persist:
                top = r + off_run
                ink = np.array(inked[:max(0, b0 - top)], bool)
                lines = int(np.sum(ink[1:] & ~ink[:-1]) + (1 if len(ink) and ink[0] else 0))
                return (top, [s for s in off_since if s is not None],
                        float(np.mean(shares)) if shares else 0.0, lines)
        r -= 1
    return None, [], 0.0, 0


def find_card(screen_grey, box):
    """The card the drawn box was meant to hold. {sure, box, why}.

    `screen_grey` is the warped screen box, grey; `box` is the drawn card box
    as fractions of it (x, y, w, h). The answer's `box` is in the same terms:
    the card's sides, its top, and the TOP of its button — the button holds no
    figure, and its edge is the one thing below the text that is always there.
    """
    if screen_grey is None or box is None:
        return _unsure('no screen or no card box')
    g = screen_grey if screen_grey.ndim == 2 else cv2.cvtColor(screen_grey, cv2.COLOR_BGR2GRAY)
    H0, W0 = g.shape[:2]
    if H0 < 50 or W0 < 20:
        return _unsure('no screen or no card box')
    scale = FIND_HEIGHT / float(H0)
    g = cv2.resize(g, (max(BLOCKS * 2, int(round(W0 * scale))), FIND_HEIGHT),
                   interpolation=cv2.INTER_AREA)
    h, w = g.shape
    bottom = float(box[1]) + float(box[3])
    r0, r1 = int((bottom - BAR_ABOVE) * h), int(min(1.0, bottom + BAR_BELOW) * h)
    bar = _bar(g, r0, r1)
    if isinstance(bar, str):
        return _unsure(bar)
    b0, b1, _, bar_l, bar_r = bar

    # The sides, along a strip just above the bar: the bottom of the card's
    # body, which is blank on every card here.
    s0, s1 = max(0, b0 - int(0.03 * h)), max(1, b0 - int(0.005 * h))
    profile = np.median(g[s0:s1].astype(np.float32), axis=0)
    left = _side(profile, bar_l, -1)
    right = _side(profile, bar_r, +1)

    # The top. Blocks across the card, a little in from its sides so the
    # rounded corners are not what is measured; each carries its own reference
    # up the card.
    m = max(1, int(0.03 * w))
    top, starts, background, lines = _walk(g, left + m, right + 1 - m, b0, s0, s1)
    if top is None:
        return _unsure('the card runs off the top of the screen box')

    # Square: every block should have left the card within a row or two of
    # the others. A slanted top is a phone turned inside its box.
    if len(starts) < (BLOCKS - 2) * OFF_ACROSS or \
            (max(starts) - min(starts)) > SQUARE * h:
        return _unsure('the card\'s top edge is not square to the box — the phone '
                       'has turned inside it')

    height = (b1 - top) / float(h)
    if not MIN_HEIGHT <= height <= MAX_HEIGHT:
        return _unsure('the card would be %d%% of the screen tall, outside %d–%d%%'
                       % (round(height * 100), MIN_HEIGHT * 100, MAX_HEIGHT * 100))

    # The body: mostly background, against each block's own reference, and
    # some lines of text on it.
    if background < MIN_BACKGROUND:
        return _unsure('the card is not mostly background')
    if lines < MIN_TEXT_ROWS:
        return _unsure('fewer than %d lines of text on the card' % MIN_TEXT_ROWS)

    return {'sure': True,
            'box': [left / float(w), top / float(h),
                    (right + 1 - left) / float(w), (b0 - top) / float(h)],
            'why': 'a card from its button up'}
