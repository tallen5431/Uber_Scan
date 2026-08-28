"""Offer card parsing — a direct port of offer-parser.js.

Both implementations run tests/fixtures/cases.json, so if this drifts from the
JavaScript the shared corpus fails. Keep the two in step when editing either.
"""

import math
import difflib
import re

# Characters OCR routinely swaps for digits, only ever applied inside a token
# already believed to be a number.
DIGIT_FIX = {
    'O': '0', 'o': '0', 'Q': '0', 'D': '0',
    'l': '1', 'I': '1', 'i': '1', '|': '1', '!': '1',
    'S': '5', 's': '5',
    'B': '8', 'b': '6',
    'Z': '2', 'z': '2',
    'g': '9', 'G': '6', 'T': '7',
}

# Every pattern below is compiled with re.ASCII, and that flag is load-bearing
# rather than tidy.
#
# Python's \d and \b are Unicode-aware by default and JavaScript's are not, so
# the two ports of this parser — which are held to one shared corpus precisely
# so they cannot disagree — disagreed the moment a character outside ASCII
# reached them. On "$16.05 3 min (1.1 mi) away ٢٠ min (7.3 mi) trip" the Pi read
# both legs, 23 minutes, $41.87/hr; the browser matched only the first and read
# 3 minutes, $321/hr. Tesseract with -l eng emits such characters rarely, but
# "rarely" is not "never", and two screens giving one card two different
# verdicts is the failure this project spends a whole shared corpus avoiding.
#
# Not on normalize()'s whitespace pattern, which is the one place the Unicode
# reading is the correct one: JavaScript's \s matches non-breaking spaces and
# the rest, so Python's must too.
ASCII = re.ASCII

# Digits as OCR may render them. Narrow on purpose: letters like G and T are
# corrected inside a confirmed number but are too risky to match on.
DC = r'[\dOoQlIiSsBbZz]'

MONEY_STRICT = re.compile(r'\$\s*(' + DC + r'{1,4}(?:[.,]' + DC + r'{1,2})?)', ASCII)

# The fallback for a dollar sign that OCR read as an S or a 5, used only when no
# real "$" was found anywhere. It insists on cents, which every Uber payout has,
# because without that it will invent one: "E 61 St & S Rhodes Ave" came back
# from a real card as "S 4S Rhodes", and the loose pattern happily read that as
# a $45.00 offer — a confident ACCEPT on a $7 job. Guessing the currency symbol
# is already one guess; allowing a digits-only amount on top of it is two, and
# addresses are full of tokens that survive two guesses.
MONEY_LOOSE = re.compile(r'(?:^|[\s(])[$S5§]\s?(' + DC + r'{1,4}[.,]' + DC + r'{2})', ASCII)

# The minute unit has to be spelled out. It was once allowed to be a bare "m",
# and on a map full of street names that turns any two letters into a journey:
# "ZIM" out of the road texture became a 21-minute leg, which is enough to make
# a screen with no offer on it look like an offer. The "i" may still be a
# lookalike, because that is one guess inside a word already confirmed.
LEG = re.compile(
    r'(?:(\d{1,2})\s*h(?:r|rs|our|ours)?\s*)?'
    r'(' + DC + r'{1,3})\s*m[il1|]n(?:s|ute|utes)?\b'
    r'(?:[^(\d]{0,6}\(?\s*(' + DC + r'{1,3}(?:[.,]' + DC + r'{1,2})?)\s*m(?:i|ile|iles)\b\s*\)?)?',
    re.IGNORECASE | ASCII)

# ...and the number in front of it has to contain a real digit. "SI min" is two
# guesses stacked, and stacked guesses are how noise becomes data.
HAS_DIGIT = re.compile(r'\d', ASCII)

ITEMS = re.compile(r'(' + DC + r'{1,3})\s*items?\b', re.IGNORECASE | ASCII)

# --- the shape a delivery card uses instead of a duration ---------------------
#
# Uber states a journey as legs: "19 min (8.5 mi)". DoorDash does not state a
# duration at all. It gives a deadline — "Deliver by 7:15 PM" — a distance on
# its own, and the merchant. Three real cards off a driver's phone parsed to
# nothing at all: no minutes, so no legs; no legs, so no miles; and with no
# minutes the offer is incomplete, gets no verdict, and never reaches the
# journal. Every DoorDash offer that driver was shown was invisible to the rig.
#
# The deadline is the honest denominator for one of these. It is not the drive
# time — it is how long the job occupies the driver, waiting at the counter
# included, which is the thing an hourly rate is supposed to divide by.
DELIVER_BY = re.compile(
    r'deliver(?:ed|y)?\s*by\s*(\d{1,2})\s*[:.]\s*(\d{2})\s*([ap])\.?\s*m\.?', re.IGNORECASE | ASCII)

# A decimal point inside a distance token, either way OCR renders it. Kept
# because the fact is lost the moment the string becomes a float: "10.0 mi" and
# "10 mi" arrive at check_distance identical, and only one of them may have its
# decimal "recovered".
LONE_DECIMAL = re.compile(r'[.,]', ASCII)

# A distance with no leg around it. Only ever consulted when no leg was found,
# so it cannot double-count an Uber card — and never the "4 mi from fast
# charger" badge, which is a fact about the map rather than about the job.
LONE_MILES = re.compile(
    r'(?<![\d.])(' + DC + r'{1,3}(?:[.,]' + DC + r'{1,2})?)\s*mi(?:les?)?\b(?!\s*from)',
    re.IGNORECASE | ASCII)

# Where the job goes. Two shapes, both anchored to something the card prints
# rather than guessed from free text: what follows "Pickup" on a delivery card,
# and what follows a leg's distance on a ride card.
PICKUP = re.compile(
    r'\bpick\s?up\b[\s:.-]*(.{2,60}?)'
    r'(?=\s*\(\s*\d+\s*orders?\s*\)|\s+customer\b|\s+dropoff\b'
    r'|\s+accept\b|\s+add\s+to\b|\s+decline\b|$)', re.IGNORECASE | ASCII)

# ...except where the word is not a label at all. A ride card prints "Avg. wait
# time at pickup" under the pickup address, and that "pickup" was read as the
# delivery card's own anchor: what followed it — the rest of the card — went
# into the journal as where the job went. One real shift stored the phrase
# itself as a place twice, and stored `1 min 23 min (8.4 mi) trip Celebration
# Blvd, Acworth` as another.
#
# Checked against the text before the match rather than with a lookbehind,
# which Safari did not have until 16.4 and this parser also runs in a phone
# browser.
PICKUP_NOT_A_LABEL = re.compile(r'\b(?:at|time)\s*$', re.IGNORECASE | ASCII)

# An address as these cards write one: a junction, or a street with a town after
# it. Deliberately narrow — a line that is not clearly a place is not stored,
# because a journal full of half-read map furniture is worse than one with a
# few offers that cannot be searched by where they went.
#
# "A comma with a letter after it" was too narrow a definition of narrow. Over a
# real shift of 121 offers it admitted `a we, a oo 1 we, a in i ie. a ; . a ae
# eS My on - J ee ae` — pure sludge off the map behind the card, stored and then
# shown on the offers page as where the job went. A comma is not evidence. A
# street word is, a junction between two named things is, and so is a town: a
# capitalised word of three letters or more sitting after the comma.
#
# Three separate patterns rather than one alternation, because the town test is
# the only one that cares about case and a single regex would have to be
# case-insensitive for the street words — which is how the capital that makes
# ", Kennesaw" evidence and ", a oo" not would have been thrown away.
STREET_WORD = (r'st|street|rd|road|ave|avenue|blvd|bivd|pkwy|parkway|dr|drive|'
               r'ln|lane|way|ct|court|hwy|highway|pl|place|ter|terrace|cir|'
               r'circle|trce|trail|trl|spgs|springs|county')
PLACE_STREET = re.compile(r'\b(?:%s)\b' % STREET_WORD, re.IGNORECASE | ASCII)
PLACE_JUNCTION = re.compile(r'[A-Za-z]{3}.*\s&\s.*[A-Za-z]{3}', ASCII)
PLACE_TOWN = re.compile(r',\s*[A-Z][A-Za-z]{2,}', ASCII)
PLACE_WORD = re.compile(r'[A-Za-z]{3}', ASCII)


def looks_like_a_place(value):
    """Is this an address, or is it the map it was printed on?"""
    if not PLACE_WORD.search(value or ''):
        return False
    return bool(PLACE_STREET.search(value) or PLACE_JUNCTION.search(value)
                or PLACE_TOWN.search(value))

# Words a card puts near a place that are not part of its name.
#
# `total` joins them because a shop card prints "34 min (3.6 mi) total" and the
# merchant's name straight after it, so the leg tail begins with the word: 5 of
# one shift's addresses were stored as "total Five Guys (3450 Cobb Pkwy. NW)".
#
# `away` and `trip` are here for the same reason: an Uber ride card writes
# "5 min (1.2 mi) away" and "20 min (7.3 mi) trip", so the word sits between the
# leg the address hangs off and the address itself.
PLACE_JUNK = re.compile(
    r'^(?:pickup|dropoff|customer|accept|decline|add\s+to\s+route|'
    r'deliver(?:ed|y)?\s*by.*|verified|exclusive|guaranteed|tota?l|away|trip)'
    r'\b[\s:.-]*', re.IGNORECASE | ASCII)

# ...and where a place *ends*. PLACE_JUNK only ever trimmed a prefix, so every
# word the card prints after an address rode along with it into the journal. The
# commonest by far is Uber's own "Avg. wait time at pickup", which sits directly
# under the pickup address: it was on 25 of one shift's 60 stored places, and
# what the offers page showed was `Cobb Pkwy NW, Acworth Avg. wait time at
# pickup; Canton Rd, Marietta` — an address a driver reads as not-an-address.
#
# A pipe ends one too. It is never in a street name and it is what the card's
# own dividers and its bottom icon row come back as.
PLACE_TAIL = re.compile(
    r'(?:\||\b(?:avg|wait\s*time|fast\s*charg|add\s+to\s+route|accept|decline'
    r'|verified|exclusive|guaranteed|included|customer|dropoff|orders?)\b)',
    re.IGNORECASE | ASCII)

# The card's bottom bar — a row of icons — comes back as one and two character
# scraps: `Kennesaw 4`, `Marietta %`, `Acworth ¥`, `Kennesaw 2c 4`. Stripped a
# token at a time from each end, because they arrive in runs.
#
# Two lists, not one. `S Main St NW` starts with a real single letter and
# `Chick-fil-A (2555 Dallas Highway) s` ends with a false one, so a compass
# point is worth keeping at the front and not at the back. Length is the test
# rather than shape: "Papa John's Store 3317" ends in a number that belongs to
# it, and four characters is not a scrap.
PLACE_TRAIL_KEEP = frozenset(('nw', 'ne', 'sw', 'se', 'st', 'rd', 'dr', 'ct',
                              'ln', 'pl', 'ga'))
PLACE_LEAD_KEEP = PLACE_TRAIL_KEEP | frozenset(('n', 's', 'e', 'w'))
PLACE_EDGE = re.compile(r'^[^0-9A-Za-z]+|[^0-9A-Za-z]+$', ASCII)

# How many places one card can name. A pickup and a dropoff on a ride card, a
# merchant and a customer on a delivery one, and a little room for a stacked
# order. Defined here because the accumulator and the journal both cap their own
# collections at the same number and three copies of it is three chances to
# disagree about what a card can hold.
MAX_PLACES = 4
TOTAL_TAIL = re.compile(r'\btota?l\b', ASCII)

# What a card calls a leg of the journey. Uber labels every one — "away",
# "trip", "total" — and prints its distance beside its time.
#
# So a minutes-only token that also carries one of these words is a leg whose
# distance did not read, which is the damage legs_short_a_distance exists for.
# One WITHOUT a label is not a leg at all, and the card is full of them:
# "Avg. wait time at pickup 4 min" under the address, a promo chip's "15 min
# left", an ETA badge's "arrives in 9 min". Each became a third leg on a two-leg
# card and tripped the guard, which marked the whole distance untrusted and made
# rate() charge no mileage. On one real shift that was 67 of the 70 three-leg
# cards and a third of every offer read, with the distance complete throughout.
#
# Deciding it on the card's own grammar rather than on a list of phrases that
# are not legs is what makes it hold for the next one: nothing here has to know
# what a promo chip says.
#
# It also fails safe. A real leg that loses BOTH its label and its distance is
# read as not-a-leg, so the other legs' distance is charged instead of none at
# all — a cost that is too low rather than absent, which is the less optimistic
# of the two errors and the only direction that matters here.
LEG_TAIL = re.compile(r'\b(?:away|tr[il1|]p|tota?l|dropoff|drop\s*off)\b',
                      re.IGNORECASE | ASCII)

# What kind of job the card is offering, taken from the words the card prints
# rather than inferred from its numbers.
#
# The offers page used to split "Rides" from "Shop" on whether an item count had
# been read, which is a fact about the OCR and not about the job: 22 offers in
# one real recording ran at shopping speeds with no item count on them, and all
# 22 were filed as rides, so both medians were wrong and neither said so. An
# item count is also not the same question — it buys shopping time, and a shop
# order whose count was missed still shops.
SHOP_CARD = re.compile(r'\bshop\b[\s&+]*(?:and\s*)?\bdeliver', re.IGNORECASE | ASCII)

# No offer averages highway speed door to door once pickup, lights and parking
# are in it. Above this the distance was misread — but see UNREADABLE_MPH: that
# is the line above which a reading is *treated* as unreadable, and it is a good
# deal higher, because the two questions are not the same one.
MAX_MPH = 55.0

# Above this a distance is not merely fast, it is not a distance.
#
# These were one constant, and conflating them cost real money. Losing a decimal
# multiplies apparent speed by exactly ten, so a 6 mph shopping errand comes back
# at 63 mph — which is why MAX_MPH sits at 55, well below it, and why three
# cases in the shared corpus depend on recovery firing at 63.5. But a reading
# that keeps its decimal cannot have lost one, and for those the same 55 was
# being read as "this distance is unusable", which makes rate() drop the mileage
# cost altogether and show gross as net.
#
# The owner's own longest real offer is 115 miles in about two hours: 56 mph,
# genuine, and one mile per hour the wrong side of the line. It was being shown
# at $24.96/hr against a truth of $8.40 — a PASS dressed as a near-miss, on the
# largest commitment on the board. Between 55 and here a distance is at most a
# third out; ten times out is what zeroing the cost was written for.
UNREADABLE_MPH = 75.0


def fix_digits(token):
    return ''.join(DIGIT_FIX.get(c, c) for c in token)


# Digits, one decimal point, an optional sign. Nothing else.
#
# `float()` is far more accommodating than that: it takes '1e3' as 1000, '1_0'
# as 10, 'nan' as a float that compares false against every bound it is later
# checked against, and 'Infinity' as one that clears them all. None of those can
# come off an offer card, and the JavaScript reader has never accepted them —
# `parseFloat` behind this same guard — so a token like `1_0` was a silent
# disagreement between the rig in the car and the phone in the hand.
NUMERIC = re.compile(r'^[+-]?(\d+(\.\d*)?|\.\d+)$', ASCII)


def round2(value):
    """Two decimal places, rounded the way the JavaScript rounds.

    `round()` in Python rounds a half to the nearest *even* digit — 2.675
    becomes 2.67 — while `Math.round` rounds it away from zero, giving 2.68.
    Both are defensible and they are not the same, so the rig in the car and
    the phone in the hand could store a distance that differed in the second
    decimal, and every figure worked out from it would differ too. Nothing a
    card can print reaches that case today, which is exactly the kind of
    agreement that is worth pinning down before something changes and it does.
    """
    return math.floor(value * 100 + 0.5) / 100.0


def to_number(token):
    if token is None:
        return None
    s = fix_digits(str(token)).replace(',', '.').strip()
    if not NUMERIC.match(s):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def normalize(text):
    text = str(text or '')
    text = re.sub(r'[‘’“”]', "'", text)
    text = re.sub(r'[–—−]', '-', text)
    text = text.replace(' ', ' ')
    return re.sub(r'\s+', ' ', text).strip()


def find_pay(text):
    matches = MONEY_STRICT.findall(text) or MONEY_LOOSE.findall(text)
    best = None
    for raw in matches:
        v = to_number(raw.strip())
        # The offer headline is the largest dollar figure; promo lines are smaller.
        if v is not None and 0 < v < 2000 and (best is None or v > best):
            best = v
    return best


def find_legs(text):
    legs = []
    for m in LEG.finditer(text):
        mins = to_number(m.group(2))
        if mins is None or not HAS_DIGIT.search(m.group(2)):
            continue
        minutes = (to_number(m.group(1)) or 0) * 60 + mins
        if minutes <= 0 or minutes > 600:
            continue

        miles = to_number(m.group(3))
        if miles is not None and (miles < 0 or miles > 500):
            miles = None
        # A decimal point is a pixel or two through a lens and is the first
        # thing to be lost, so remember whether this reading actually had one.
        had_decimal = m.group(3) is not None and bool(re.search(r'[.,]', m.group(3)))

        # Recover a decimal lost from this leg alone, before it reaches the sum.
        # "20 min (7.3 mi)" read as "(73 mi)" is a 219 mph leg, and left alone it
        # does more than inflate the distance: a merger keying legs by distance
        # files it as a *third* leg beside the real one, so a 23-minute card
        # reports 43 minutes. Checking each leg against its own time catches it
        # while it is still identifiable as the leg it came from.
        miles, leg_corrected = recover_decimal(minutes, miles, had_decimal)

        tail = text[m.end():m.end() + 14].lower()
        legs.append({
            'minutes': minutes, 'miles': miles, 'hadDecimal': had_decimal or leg_corrected,
            'isTotal': bool(TOTAL_TAIL.search(tail)), 'corrected': leg_corrected,
            # Whether the card labelled this as part of the journey. Only
            # consulted for a leg with no distance, where it is the difference
            # between a leg that lost its miles and a line that never had any.
            'labelled': bool(LEG_TAIL.search(tail)),
            # Where this leg sat in the text, so the address printed after it
            # can be found without searching the whole card again.
            'start': m.start(), 'end': m.end(),
        })
    return legs


def recover_decimal(minutes, miles, had_decimal):
    """Put back a decimal point this leg clearly lost. Returns (miles, corrected).

    Deliberately narrower than check_distance: it only ever divides by ten, only
    when the reading had no decimal at all, and only when doing so lands the leg
    back in a believable range. Anything else is left for the total to judge,
    because leg times are whole minutes and a two-minute leg is too coarse to
    argue with — a rounded 2 min over 2.0 mi is already "60 mph" and perfectly
    real.
    """
    if miles is None or not minutes or had_decimal:
        return miles, False
    if miles / (minutes / 60.0) <= MAX_MPH:
        return miles, False
    recovered = miles / 10.0
    if 0.5 <= recovered / (minutes / 60.0) <= MAX_MPH:
        return recovered, True
    return miles, False


def is_complete(pay, minutes, deliver_by=None):
    """Whether a reading is enough to judge an offer on.

    A delivery card is complete without a duration, because its deadline is
    one — but only once something has told it what time it is. rate() fills
    that in; parse() must stay a pure function of its text.

    One function rather than the rule written out wherever it is needed. It had
    been written out twice, and the second copy — in the accumulator, which
    recomputes it after merging frames — was missing the deadline clause. So
    every DoorDash card that gives a deadline instead of a duration parsed as
    complete, went through the accumulator, and came back incomplete: no
    verdict, no journal row, nothing on screen, for a whole shape of offer.
    """
    if pay is None or not (pay > 0):
        return False
    if minutes is not None and minutes > 0:
        return True
    return deliver_by is not None


def is_whole(parsed):
    """Whether a reading has nothing further to gain from another frame.

    Not the same question as is_complete, and the difference is what to do next:
    complete means judgeable, whole means finished. A card missing a leg is the
    same pay over less time, so it always reads *better* than the offer is —
    which is why the loop keeps resampling until this is true, why the voice
    waits for it, and why the offers page sets a partial reading aside.

    Written out by hand in two places before this, and both said `hasTotal or
    legs >= 2`. A delivery card has neither: it states a deadline instead of a
    duration and no legs at all, so every DoorDash offer was permanently a
    fragment — never spoken, always shown with a question mark, flagged with a
    warning that said the opposite of the truth, and left out of every figure on
    the offers page. It was invisible until the accumulator stopped losing those
    cards entirely, and then it was merely wrong about them.

    The deadline branch asks for the distance, which the legs branch gets for
    free. A deadline card with no miles is judgeable — rate() charges no mileage
    for a distance it does not have — and that is gross wearing net's clothes,
    $53.62 against a true $49.79 on the corpus's own fixture. There is no second
    leg to wait for on such a card, so the distance is the one thing another
    frame can still add, and waiting for it is exactly what `whole` is for.
    """
    if not parsed.get('complete'):
        return False
    # Two shapes reach this. A raw parse() carries the legs themselves and no
    # summary; a reading merged across frames carries `hasTotal` and has already
    # trimmed the legs. Both are asked, because the browser scanner judges the
    # first and the rig judges the second, and they must agree about one card.
    # A journey whose legs disagree about having a distance is not finished,
    # however many legs were found. `legs >= 2` below counts legs; it does not
    # ask whether they read. A two-leg card whose second distance came back as
    # "7.3 m1" therefore called itself whole — the loop stopped resampling, the
    # voice spoke it, and the offers page counted it — on a journey credited
    # with 23 minutes and 1.1 of its 8.4 miles. Another frame is exactly what
    # fixes that: the accumulator merges legs across frames for this reason.
    if legs_short_a_distance(parsed.get('legDetail') or []):
        return False
    if parsed.get('hasTotal') or any(
            leg.get('isTotal') for leg in (parsed.get('legDetail') or [])):
        return True
    if (parsed.get('legs') or 0) >= 2:
        return True
    return (not (parsed.get('legs') or 0)
            and parsed.get('deliverBy') is not None
            and parsed.get('miles') is not None)


def legs_short_a_distance(legs):
    """True when a multi-leg journey is missing a distance from any of its legs.

    The sum is then a whole journey's *time* against part of its distance, and
    nothing downstream can tell. Every existing guard looks for a distance that
    is too big — `check_distance` catches a lost decimal turning a 6mph errand
    into a 63mph one — and this failure produces one that is too small, which
    reads as an ordinary slow trip and passes every check there is.

    Measured on a rendered card at three times the brightness it was exposed
    for: `20 min (7.3 mi) trip` came back as `20 min (7.3 m1) trip`, so the
    second leg contributed its twenty minutes and no distance at all. The
    reading was 23 minutes over 1.1 miles instead of 8.4, `complete`, `whole`,
    unflagged, and rated — $41.01/hr for an offer worth $35.30/hr, because the
    missing miles are missing *cost*. It errs optimistic, which is the one
    direction that turns a pass into an accept.

    The corpus had an instance of this all along, under a name that says the
    opposite of what it asserted.

    Two legs or more, deliberately, and it does not ask whether any *other* leg
    kept its distance. A first version did, so one leg losing its miles was
    caught and both legs losing them was not — and the second is the worse case,
    since it leaves `miles` as None, which reads as "this card states no
    distance" rather than as damage. Nothing marks it, rate() charges no mileage
    for a distance it does not have, and the row is whole and unsuspicious, so
    its gross rate goes into every median on the offers page beside net ones.
    Measured on `$16.05 25 min (11.q5 mi) away 17 min (3.q mi) trip`, both
    distances mangled: $22.93/hr, whole, unflagged.

    A card printing an ordinary leg always prints its distance beside the time,
    so a leg without one is OCR damage rather than a card shape. A *single* leg
    is left alone, because it can be a total — the corpus has `$7.09 34 min
    total`, which states no distance and is a whole journey by itself — and one
    plain leg is already not whole for having no second half.
    """
    if len(legs) < 2:
        return False
    # A leg is part of the journey if it states a distance, or if the card
    # labelled it one. A minutes-only token with no label is a wait line, a
    # promo chip or an ETA badge — not a leg the reader failed on — and counting
    # it here switched the mileage cost off on a third of every offer read.
    #
    # Their minutes are still counted. The driver really does wait at the
    # pickup, and dropping the time would raise the rate, which is the one
    # direction that turns a pass into an accept.
    travel = [l for l in legs
              if l.get('miles') is not None or l.get('labelled')]
    if len(travel) < 2:
        return False
    return any(l.get('miles') is None for l in travel)


def check_distance(minutes, miles, had_decimal):
    """Guards the one OCR failure that inverts the answer: losing the decimal in
    "3.6 mi" turns a 6 mph errand into a 63 mph one, and the phantom 32 miles
    can swallow the whole fare as mileage cost."""
    if miles is None or not minutes:
        return miles, False, False

    mph = miles / (minutes / 60.0)
    if mph <= MAX_MPH:
        return miles, False, False

    # A missing decimal is the likeliest cause, and only when the reading did
    # not have one. Recovering it must be visible, never silent.
    if not had_decimal and 0.5 <= mph / 10.0 <= MAX_MPH:
        return miles / 10.0, True, False
    # Nothing to recover, so the only question left is whether this is a fast
    # trip or a broken number — and those get different answers. See
    # UNREADABLE_MPH: calling a genuine 56 mph highway run unreadable makes
    # rate() charge no mileage at all, which is the one direction that turns a
    # PASS into an ACCEPT.
    if mph <= UNREADABLE_MPH:
        return miles, False, False
    return miles, False, True


def find_deadline(text):
    """"Deliver by 7:15 PM" as minutes since midnight, or None."""
    m = DELIVER_BY.search(text)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2))
    if not (1 <= hour <= 12) or minute > 59:
        return None
    half = m.group(3).lower()
    hour = hour % 12
    if half == 'p':
        hour += 12
    return hour * 60 + minute


def minutes_until(deadline, now_minutes):
    """How long is left, wrapping across midnight. None if either is missing.

    A deadline that has already passed is not a short job, it is a stale card —
    a screenshot, or a shift left running. Wrapping treats "deliver by 00:15"
    read at 23:50 as twenty-five minutes, which is right, and leaves anything
    beyond a normal delivery window for the sanity bounds to refuse.
    """
    if deadline is None or now_minutes is None:
        return None
    left = deadline - now_minutes
    if left < 0:
        left += 24 * 60
    return float(left)


# When two readings are one address.
#
# Merging the addresses seen across a window of frames is what stops a frame
# that lost the map to glare from erasing one that had it — and, done on exact
# strings, it invents journeys. Two frames one comma apart give "Cobb Pkwy NW,
# Acworth" and "Cobb Pkwy NW Acworth", both survive an exact-match dedupe, and
# the offers page joins places with an arrow: one address rendered as a two-stop
# route that never happened. That is worse than the missing address the merge
# was added to fix, and the behaviour it replaced could not produce it.
#
# Calibrated on one real shift's 61 distinct addresses. One address a single OCR
# slip apart scores 0.889 and up; the two genuinely different ends of a card, over
# all 21 two-place cards in that shift, score 0.595 and down. Same street with a
# different town — the nearest thing to a hard case — sits between at 0.606 to
# 0.875. There is a lot of room in that gap, so the line is drawn at 0.90 and the
# cost of being wrong is one row showing an address twice rather than a route
# nobody drove.
PLACE_SAME = 0.90

# A truncated read is the front of the whole one. Ratio alone is poor at this —
# "Cobb Pkwy NW" against "Cobb Pkwy NW, Acworth" scores 0.74 — so containment
# gets its own rule, with a floor so a fragment cannot swallow a real address.
PLACE_PREFIX_SHARE = 0.7

PLACE_KEY = re.compile(r'[^0-9a-z]+', ASCII)


def place_key(value):
    """An address with everything OCR argues about taken out of it."""
    return PLACE_KEY.sub('', (value or '').lower())


def same_place(a, b):
    """Two readings of one address, rather than two addresses.

    Deliberately not used by find_places: within a single frame the exact match
    is what the JavaScript port also does, and the two are held to the same
    answers by the shared corpus. This is about the *union across frames*, which
    only the Pi does.
    """
    key_a, key_b = place_key(a), place_key(b)
    if not key_a or not key_b:
        return key_a == key_b
    if key_a == key_b:
        return True
    short, long = sorted((key_a, key_b), key=len)
    if (long.startswith(short)
            and len(short) >= len(long) * PLACE_PREFIX_SHARE):
        return True
    return difflib.SequenceMatcher(None, key_a, key_b).ratio() >= PLACE_SAME


def merge_place(places, value):
    """Add one address to a list, unless it is one of them read again.

    Keeps the longer of the two where they are the same place: a truncated read
    is the common failure, so more characters is more of the address.
    """
    for i, seen in enumerate(places):
        if same_place(seen, value):
            if len(value) > len(seen):
                places[i] = value
            return places
    places.append(value)
    return places


def trim_place(value):
    """One address, with the card's furniture taken off both ends.

    An anchor says where a place *starts*; nothing on the card says where it
    stops, so what got stored was the address plus whatever the layout printed
    next to it. Cut at the furniture, drop the prefix, then take the icon-row
    scraps off each end a token at a time. See PLACE_TAIL.

    Parentheses survive on purpose: a branch address is printed inside them —
    "Dollar General (925 Shiloh Rd Nw)" — and taking the closing one off leaves
    a dangling bracket and a name that reads as truncated.
    """
    def scrap(token, keep):
        core = PLACE_EDGE.sub('', token)
        return not core or (len(core) <= 2 and core.lower() not in keep)

    # The front first, and the tail after. Order matters: a pipe ends a place,
    # but `oN | Cobb Pkwy NW, Kennesaw 'a` is a pipe with the sludge on the
    # *near* side of it, and cutting there first threw the address away and
    # kept the "oN".
    parts = (value or '').split()
    while True:
        while parts and scrap(parts[0], PLACE_LEAD_KEEP):
            parts.pop(0)
        # Two prefixes happen — "total Pickup Papa John's" — and the second is
        # only at the front once the first has gone.
        shorter = PLACE_JUNK.sub('', ' '.join(parts).strip()).strip(' .,-;:|').split()
        if shorter == parts:
            break
        parts = shorter

    parts = PLACE_TAIL.split(' '.join(parts))[0].split()
    while parts and scrap(parts[-1], PLACE_TRAIL_KEEP):
        parts.pop()
    return ' '.join(parts).strip(' .,-;:|')


def find_places(text, legs):
    """Where the job goes, as the card writes it. Never invented.

    Two anchors only. What follows "Pickup" on a delivery card is the merchant;
    what follows a leg's distance on a ride card is the address for that leg.
    Anything that does not sit against one of those anchors is left alone —
    a journal full of half-read map furniture would be worse than one that
    cannot be searched by where an offer went.
    """
    out = []

    def keep(value):
        value = trim_place(value)
        if len(value) < 3 or len(value) > 60:
            return
        if not re.search(r'[A-Za-z]{2}', value):
            return
        if value.lower() not in [v.lower() for v in out]:
            out.append(value)

    for m in PICKUP.finditer(text):
        if PICKUP_NOT_A_LABEL.search(text[max(0, m.start() - 14):m.start()]):
            continue
        keep(m.group(1))
        break

    # A delivery card without a "Pickup" label puts the merchant straight after
    # the deadline: "Deliver by 6:39 PM / Cherry Cricket / 4 items 0.6 mi". The
    # deadline is the anchor; the name ends where the figures begin.
    d = DELIVER_BY.search(text)
    if d:
        after = text[d.end():d.end() + 60]
        after = re.split(r'\d|\b(?:accept|decline|pickup|customer|dropoff)\b',
                         after, maxsplit=1, flags=re.IGNORECASE | ASCII)[0]
        keep(after)

    # The tail of each leg, up to whatever comes next.
    for i, leg in enumerate(legs):
        start = leg.get('end')
        if start is None:
            continue
        stop = legs[i + 1].get('start') if i + 1 < len(legs) else len(text)
        tail = text[start:stop][:80]
        # Cut at the first thing that is plainly not part of an address.
        tail = re.split(r'\b(?:accept|decline|verified|exclusive|guaranteed'
                        r'|add\s+to\s+route|\d+\s*mi\b)', tail,
                        maxsplit=1, flags=re.IGNORECASE | ASCII)[0]
        # Trimmed before it is judged, not after. The test asks whether this is
        # an address, and the thing to ask it about is the string that would be
        # stored — `1 min ~ 4 . mins | . = | i oO < * ~~ agama ae ae; i Old
        # Mountain Rd NW, Kennesaw` passes on the address buried at the end of
        # it and then goes into the journal sludge and all.
        tail = trim_place(tail)
        if looks_like_a_place(tail):
            keep(tail)

    return out[:MAX_PLACES]


def parse(raw_text):
    text = normalize(raw_text)
    legs = find_legs(text)

    totals = [l for l in legs if l['isTotal']]
    used = totals or legs

    minutes = None
    miles = None
    had_decimal = False
    corrected_leg = False
    for leg in used:
        minutes = (minutes or 0) + leg['minutes']
        if leg['miles'] is not None:
            miles = (miles or 0) + leg['miles']
            if leg['hadDecimal']:
                had_decimal = True
            if leg.get('corrected'):
                corrected_leg = True
    short_a_leg = legs_short_a_distance(used)

    # A card gives distances to one decimal place, so a sum of them has one
    # decimal place. Binary floating point disagrees: 3.5 + 6.1 is
    # 9.600000000000001, and that went into the journal, into the CSV export and
    # into anything reading either. Rounded here rather than at each display, so
    # the stored number and the shown number are the same number.
    if miles is not None:
        miles = round2(miles)
    miles, corrected, uncertain = check_distance(minutes, miles, had_decimal)
    corrected = corrected or corrected_leg
    uncertain = uncertain or short_a_leg

    m = ITEMS.search(text)
    items = to_number(m.group(1)) if m else None
    if items is not None and not (0 <= items <= 200):
        items = None

    pay = find_pay(text)

    # A delivery card states no duration and puts its distance on its own, so
    # neither reaches the sum above. Consulted only when the legs found nothing,
    # which is what keeps it from double-counting a ride card.
    deadline = find_deadline(text)
    if miles is None and not used:
        lone = LONE_MILES.search(text)
        if lone:
            v = to_number(lone.group(1))
            if v is not None and 0 < v <= 500:
                miles = round2(v)
                # Whether the token carried a decimal point, which is the one
                # thing recover_decimal needs to know and the one thing that is
                # lost the moment the string becomes a float. A card printing
                # "10.0 mi" and one printing "10 mi" arrive here identical.
                had_decimal = bool(LONE_DECIMAL.search(lone.group(1)))

    return {
        'pay': pay,
        'minutes': minutes,
        'miles': miles,
        # Minutes since midnight, not a duration: converting one to the other
        # needs to know the time, and a parser that reads the clock cannot be
        # checked against a fixed corpus. rate() does the subtraction.
        'deliverBy': deadline,
        # Where it goes, for finding this offer again months later. Empty
        # unless the card actually printed something anchored enough to trust.
        'places': find_places(text, legs),
        # The legs behind the sum, so a caller holding readings from several
        # frames can merge the ones a single frame missed.
        # `labelled` travels with them. is_whole re-runs
        # legs_short_a_distance over this projection, and a field the rule needs
        # that does not survive the trip is a rule that quietly stops working:
        # every minutes-only leg looked unlabelled here, so a two-leg card whose
        # second distance came back as "7.3 m1" called itself whole again.
        'legDetail': [{'minutes': l['minutes'], 'miles': l['miles'],
                       'isTotal': l['isTotal'], 'labelled': l['labelled']}
                      for l in used],
        'items': items,
        'legs': len(used),
        'milesCorrected': corrected,
        'milesUncertain': uncertain,
        # A distance is only as checkable as the time beside it. On a ride card
        # check_distance has already run against the legs' own minutes; on a
        # delivery card there are no minutes at all, so it returned the number
        # untouched and this says whether it may still be recovered later. See
        # rate(), which is where the clock is.
        'milesChecked': minutes is not None,
        'milesHadDecimal': had_decimal,
        'complete': is_complete(pay, minutes, deadline),
        # What the card says it is. None when the card did not say — the top
        # chip may simply not have been inside the crop — which is different
        # from "not a shop order" and is kept different.
        'shop': True if SHOP_CARD.search(text) else None,
        'text': text,
    }


# The defaults, and the only values these ever take if what is in config.json
# cannot be read as a number.
DEFAULT_SETTINGS = {'target': 25, 'band': 15, 'costPerMile': 0, 'pad': 0,
                    'secondsPerItem': 0}


def setting(value, fallback):
    """A number a person typed into config.json, or the default if it is not one.

    The driver is told to hand-edit this block, so `"target": "30"` with the
    quotes left on, or a value deleted to `null`, is a keystroke away — and both
    languages got it wrong in opposite directions. Python multiplied a string by
    a float and raised, inside the read guard, which reports a permanent
    misconfiguration as one bad frame and suppresses the repeat: the whole shift
    then produced one log line, no verdicts and no journal rows while the page
    kept a green dot and WAITING FOR AN OFFER. JavaScript coerced silently, and
    for a deleted target that put the accept floor at zero, which makes every
    offer an ACCEPT.

    So a number is taken from anything that reads as one — "30" is what the
    driver meant — and anything else falls back to the documented default rather
    than to a crash or to nonsense. Written the same way in both languages so
    the two cannot answer differently.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return fallback
    # The same guard to_number uses, for the same reason and now on the same
    # patterns. `float()` and `Number()` are each generous and generous in
    # *different* ways: Python read "1_0" as ten and refused "0x10", JavaScript
    # refused "1_0" and read "0x10" as sixteen. This block is hand-edited on the
    # driver's instruction, so a stray character is a keystroke away, and one
    # config file grading the same card against two different targets — with
    # nothing on either screen saying which — is the failure this whole function
    # already exists to prevent. Anything that is not plainly a number falls
    # back to the documented default, in both languages, identically.
    if isinstance(value, str) and not NUMERIC.match(value.strip()):
        return fallback
    try:
        n = float(value)
    except (TypeError, ValueError):
        return fallback
    if n != n or n in (float('inf'), float('-inf')):
        return fallback
    return n


# What a real offer looks like from the outside, used to catch a reading that
# cannot be true rather than a ride that is merely unusual.
#
# These come from 234 offers off a real rig. Three of them had lost a decimal
# point — $11.84 read as $1184, $12.51 as $1251 — and two more had a misread
# time that put the trip at 110 and 120 mph. All five were shown as ACCEPT, in
# green, with a spoken "accept, three thousand five hundred an hour". The
# journal flagged the first three afterwards and said nothing about the other
# two, which is the wrong end of the problem: by then the driver has already
# looked at the screen and decided.
#
# The bounds sit well clear of anything genuine in that data — the best real
# offer was $45/hr, the fastest real trip averaged 56 mph over a 115-mile
# highway run — so a card has to be misread, not just unusual, to trip them.
SANE_PAY = (1.0, 300.0)
SANE_MINUTES = (2.0, 240.0)
SANE_MPH = 75.0
# A rate no offer on these apps pays. Not a judgement about a good job — that is
# what `target` is for — but the line above which the arithmetic itself cannot
# be true, so the reading behind it is a misread rather than a windfall.
#
# Measured against the owner's own shift of 202 offers: the highest rate among
# readings whose distance was trusted was $37.29/hr. Everything above $100/hr
# that shift was a lost decimal point — $1.06 read as $106 over the same 29
# minutes and 11.8 miles, shown as ACCEPT at $219/hr; $7.06 as $158, shown at
# $351/hr; $136 over ten minutes, shown at $816/hr. This sits at five times the
# highest real one because the cost of being wrong runs both ways: a ceiling
# that clips a genuine surge hides an offer the driver should have seen.
SANE_RATE = 200.0
# ...and only once the trip is long enough for a rate to describe it.
#
# A rate ceiling on its own is wrong, because $/hr is unbounded as the duration
# shrinks: $10 for a two-minute half-mile hop is $300/hr and is an ordinary
# offer. The corpus has held that case since before this check existed, and the
# first version of this check broke it — a ceiling clipping a real offer is the
# same failure as a ceiling letting a misread through, pointed the other way.
#
# Below ten minutes a few dollars of tip dominates the rate and $/hr is a poor
# description of the card. Above it, the rate is a rate. At the boundary this
# doubts a payout over $33 for ten minutes, $100 for thirty, $200 for an hour —
# none of which these apps pay.
SANE_RATE_OVER_MINUTES = 10.0


def doubt(pay, minutes, miles=None):
    """Why this reading cannot be true, or None if it might be.

    Only the direction that produces a wrong ACCEPT is checked. A reading that
    understates what an offer pays makes it look worse than it is, and the
    driver declines something they might have taken — a real cost, but a
    recoverable one, and the next offer is thirty seconds away. A reading that
    overstates it puts them in a car for forty minutes for six dollars.
    """
    if not isinstance(pay, (int, float)) or isinstance(pay, bool):
        return None
    if not (SANE_PAY[0] <= pay <= SANE_PAY[1]):
        return 'pay'
    if not isinstance(minutes, (int, float)) or isinstance(minutes, bool):
        return None
    if not (SANE_MINUTES[0] <= minutes <= SANE_MINUTES[1]):
        return 'time'
    # Each of the two can be sane on its own and impossible together. $136 is
    # inside SANE_PAY and ten minutes is inside SANE_MINUTES, and $816/hr is
    # neither — it is a decimal point that did not survive the read. Nothing
    # tested the pair, so five readings of one shift reached the panel as
    # ACCEPT at between $103 and $816 an hour.
    #
    # `max`, so the ceiling never loosens as the trip gets shorter. Written as
    # two branches first, and that made a STEP: below ten minutes nothing but
    # SANE_PAY's own $300 applied, so $136 over ten minutes was doubted at
    # $810/hr while the same $136 over NINE minutes was a green ACCEPT at
    # $899/hr. A guard that a shorter trip walks under is not a guard.
    #
    # Below the boundary this is a flat cap on the PAY — $33.33, the payout that
    # reaches SANE_RATE at ten minutes — because $/hr is unbounded as the
    # duration shrinks and that is the whole reason the boundary exists. It
    # refuses none of the 568 real offers on record (the largest under ten
    # minutes is $5.00) and no corpus card that is not already wrong.
    #
    # It is derived from the two constants above rather than being a third, so
    # raising SANE_RATE raises this with it. That coupling is intended: it is
    # the same ceiling.
    if pay / (max(minutes, SANE_RATE_OVER_MINUTES) / 60.0) > SANE_RATE:
        return 'rate'
    if (isinstance(miles, (int, float)) and not isinstance(miles, bool)
            and miles >= 1.0 and minutes > 0
            and miles / (minutes / 60.0) > SANE_MPH):
        return 'speed'
    return None


def rate(parsed, settings=None):
    s = settings or {}
    target = setting(s.get('target'), DEFAULT_SETTINGS['target'])
    band = setting(s.get('band'), DEFAULT_SETTINGS['band'])
    cost_per_mile = setting(s.get('costPerMile'), DEFAULT_SETTINGS['costPerMile'])
    pad = setting(s.get('pad'), DEFAULT_SETTINGS['pad'])
    seconds_per_item = setting(s.get('secondsPerItem'), DEFAULT_SETTINGS['secondsPerItem'])

    if not parsed['complete']:
        return {'ready': False, 'state': 'empty'}

    # A delivery card gives a deadline where a ride card gives a duration. The
    # subtraction happens here rather than in parse(), because it needs to know
    # the time and a parser that reads the clock cannot be held to a fixed
    # corpus. `nowMinutes` is minutes since midnight; without it a card that
    # only has a deadline stays unjudged rather than being guessed at.
    card_minutes = parsed['minutes']
    from_deadline = False
    if card_minutes is None and parsed.get('deliverBy') is not None:
        card_minutes = minutes_until(parsed['deliverBy'],
                                     setting(s.get('nowMinutes'), None))
        from_deadline = card_minutes is not None
    if card_minutes is None or card_minutes <= 0:
        return {'ready': False, 'state': 'empty'}

    shop_minutes = (parsed['items'] or 0) * seconds_per_item / 60.0
    minutes = card_minutes + pad + shop_minutes
    # A trip that takes no time pays infinitely well, which is the kind of
    # arithmetic that ends in an ACCEPT on nonsense. parse() will not produce a
    # zero-minute offer, but `pad` is a number a driver edits by hand in
    # config.json and a negative one can cancel the trip out. Python raised
    # ZeroDivisionError here — killing the scan loop — while the JS returned
    # Infinity and a confident "go". Neither is a verdict.
    if minutes <= 0:
        return {'ready': False, 'state': 'empty'}
    # A distance we do not trust must not become a cost. Falling back to gross
    # overstates the rate slightly; a bad distance can understate it enormously.
    # A distance is only as checkable as the time beside it, and a delivery card
    # states none — so check_distance returned the number untouched and a lost
    # decimal went straight into the cost. "2.4 mi" read as "24 mi" is charged
    # $7.20 of mileage instead of $0.72: $18.1/hr becomes $2.5/hr, unflagged,
    # with nothing on any screen saying the distance was doubted. A ride card
    # never had this hole, because its legs carry their own minutes.
    #
    # The machinery was always there and unreachable. check_distance(25, 24.0,
    # had_decimal=False) already returns (2.4, corrected, ...) — it just needs a
    # denominator, and the denominator for a delivery card is the time left
    # until its deadline, which is worked out here because it needs the clock.
    #
    # `milesHadDecimal` is what stops the cure being worse: a card that really
    # says "10.0 mi" must not have its decimal "recovered" down to 1.0.
    miles = parsed['miles']
    miles_uncertain = parsed['milesUncertain']
    miles_corrected = parsed['milesCorrected']
    # `is False` and not a truthiness test. A caller that builds this dict by
    # hand — the keypad, a test, an older row being re-rated — has no such key,
    # and treating its absence as "not checked" let rate() recover a decimal
    # from a distance that had already been checked, or typed. A hand-entered
    # 115 miles over 63 minutes came back as 11.5. Absent means do not touch it.
    if parsed.get('milesChecked') is False and miles is not None:
        miles, recovered, doubted = check_distance(
            card_minutes, miles, bool(parsed.get('milesHadDecimal')))
        miles_corrected = miles_corrected or recovered
        miles_uncertain = miles_uncertain or doubted

    cost = 0 if miles_uncertain else (miles or 0) * cost_per_mile
    net = parsed['pay'] - cost
    # ...and whether that leaves a rate the target can be compared against.
    #
    # `target` is a NET line — the driver set it against rates with their
    # running costs already taken off. When no cost could be taken off and a
    # cost per mile is configured, `per_hour` is a gross figure, so it is an
    # UPPER BOUND on the offer rather than the offer. It may clear the target;
    # it may be nowhere near it. The rig does not know.
    #
    # Measured on the owner's own shift of 202 offers: 108 of them, 53%, were
    # rated with no running cost at all, and the overstatement on the ones that
    # did state a distance ran to a median of 30%, a p90 of 173% and a maximum
    # of 334% — where the line above this used to say "slightly". 33 of the 35
    # ACCEPTs that shift came out of that pool, and 20 of them fall below the
    # target once the distance printed on the card is charged. Against a $25
    # target the offers whose cost WAS charged had a median of $12.03/hr.
    #
    # So the verdict is capped rather than the number withheld. CLOSE CALL is
    # the honest answer to "this might clear your line and I cannot tell": the
    # driver still sees the rate, the addresses and the arithmetic, and decides.
    # What they do not get is a green light the arithmetic cannot support.
    uncosted = cost_per_mile > 0 and cost == 0

    per_hour = net / (minutes / 60.0)
    floor = target * (1 - band / 100.0)
    # Judged on what the card said, not on what the arithmetic made of it: `pad`
    # and the shopping allowance are the driver's own additions and a card is
    # not misread for having them applied.
    why = doubt(parsed['pay'], card_minutes, miles)

    return {
        'ready': True,
        'minutes': minutes,
        'shopMinutes': shop_minutes,
        'net': net,
        'cost': cost,
        # Echoed back so a display can say what it deducted and why, rather
        # than showing a number nobody can reconstruct. The target and band go
        # with it because a verdict outlives the settings that produced it: a
        # stored "PASS" means nothing a month later without the line it was
        # being held to at the time.
        'costPerMile': cost_per_mile,
        'target': target,
        'band': band,
        'perHour': per_hour,
        # The same rate before running costs come off, over the same minutes.
        # A display that works this out for itself from the card's own time
        # divides by a different number as soon as `pad` or `secondsPerItem`
        # is set, and then the two rates it shows cannot be reconciled by
        # subtracting the cost it also shows.
        'grossPerHour': parsed['pay'] / (minutes / 60.0),
        'perMin': net / minutes,
        # Net, like perHour, so the two agree about what a dollar means. A
        # display showing one gross and the other net invites exactly the
        # arithmetic that does not add up.
        'perMile': (net / miles if miles and not miles_uncertain else None),
        # The distance this verdict was actually reached with, which is not
        # always the one the card appeared to state. Returned so the row that
        # gets written and the rate that gets shown cannot disagree about it —
        # a ride card's correction happens inside parse() and is already in
        # `parsed`, and a delivery card's happens here.
        'miles': miles,
        'milesUncertain': miles_uncertain,
        'milesCorrected': miles_corrected,
        # The minutes the arithmetic used from the card, and whether they were
        # a stated duration or the time left until a delivery deadline. Those
        # are different claims and a record that cannot tell them apart cannot
        # be argued with later.
        'cardMinutes': card_minutes,
        'fromDeadline': from_deadline,
        # `ready` stays true and every number is still here, because the row has
        # to reach the journal: a reading this project got wrong is the most
        # useful row in the file, and one that is quietly dropped cannot be
        # studied or counted. What is withheld is only the verdict.
        'doubt': why,
        # Whether the rate above is the offer or only a ceiling on it, so a
        # display can say which it is showing rather than leaving two different
        # kinds of number looking identical.
        'uncosted': uncosted,
        'state': ('doubt' if why else
                  # An upper bound may not clear a net target. Capped, not
                  # demoted further: below the floor it is still 'no'.
                  'warn' if uncosted and per_hour >= target else
                  'go' if per_hour >= target else
                  'warn' if per_hour >= floor else 'no'),
    }
