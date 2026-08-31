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

# One payout, cut in half by the reader.
#
# The headline is the biggest type on the card and the crop's own edge runs
# through it: the space between the dollars and the cents comes back wider than
# it is, and "$18.75" arrives as "$1 8.75". find_pay then reads the largest
# dollar figure it can see, which is $1.
#
# Nine of this driver's 309 cards, four distinct offers, and the worst of them
# is an offer worth $38.52/hr shown as a red DECLINE. It is worse than a wrong
# number: some frames of the same card read the headline whole and some split
# it, so the accumulator — which keys a card by its payout — files one physical
# offer as two, and the panel alternates between two verdicts while the driver
# is looking at it. One card in the export flickers between $28.85/hr and
# $1.54/hr five times in seventeen seconds.
#
# Glued only where the card's own label follows, and that is the whole safety of
# it. A payout says what it is — "Guaranteed", "Includes expected tip" — and
# gluing on the digits alone would read "$8 5.00" on a ride card, where the 5.00
# is the driver's star rating, as an eighty-five dollar offer. That is the one
# direction this project will not go: a fabricated payout that is LARGER reads
# as a green light. With the label required it fires on all nine real cards,
# changes no payout that was already right, and matches none of the 140 texts in
# the shared corpus.
#
# Only a plain space may sit between the halves, because that space IS the
# defect: one number printed with too wide a gap. Anything else between them
# means they are two different things, and this driver's cards are full of
# stray marks that would happily glue an $8 offer into an $85 one — 60 of the
# 420 texts on file change what they match if the gap is allowed to hold junk.
PAY_SPLIT = re.compile(
    r'\$\s*(' + DC + r'{1,3})\s+(' + DC + r'{1,2}[.,]' + DC + r'{2})'
    r'\s*(?=guarant|includ)',
    re.IGNORECASE | ASCII)

# A component of the payout, printed beside it, and never the payout.
#
# Uber puts a chip under the headline — "+$0.50 included", "+$2.39 included for
# priority" — saying what part of the total came from where. find_pay takes the
# LARGEST dollar figure on the card, on the stated reasoning that "the offer
# headline is the largest dollar figure; promo lines are smaller". That premise
# holds until the chip loses its decimal point, which is the first thing a
# decimal does through a lens.
#
# On this driver's own shift, "+$050 included" was read as FIFTY DOLLARS twice,
# on cards whose real payouts were $13.08 and $21.06, and both were rated
# **ACCEPT** — $71/hr and $68/hr. Nothing caught them: the sane-rate ceiling
# only fires above $200/hr and these sat comfortably under it. A third card read
# "+$170 included" over a real $12.05 and was only caught because $170 over nine
# minutes is $1133/hr. Eight cards in 309 took a chip as the payout.
#
# Decided by the card's own grammar, like LEG_TAIL: a PLUS, an amount, and the
# word the card prints to say what the amount is, with nothing in between. That
# last part is what keeps it off the headline, which reads "$11.42 Guaranteed
# (incl. tip)" — "incl" is there too, but "Guaranteed" sits in the way. Verified
# against all 309: three cards recover their true payout and no card loses one.
#
# The other five stop reporting a chip as the payout and report NO payout, which
# is the right answer. Their real headline never made it through the OCR at all,
# so the reading is incomplete, the panel says so, and the accumulator keeps
# looking. A rate of -$7/hr worked out from a $1.85 priority chip is not a
# smaller error than that; it is the same error wearing a number.
#
# `DC` is itself a character class, so it is spliced in as an alternation rather
# than nested inside brackets — Python warns about `[[\d...].,]` and JavaScript
# reads it as a different class altogether, which is exactly the kind of silent
# disagreement between the two ports this corpus exists to catch.
#
# The amount may arrive in two pieces, for the same reason a headline can: see
# PAY_SPLIT. A chip that reads "+$5 0.00 included" over a real $13.08 headline
# is the same fifty-dollar lie as "+$050 included", so the chip has to cover
# the split form too — otherwise the rule that puts split numbers back together
# would hand it back as the payout.
PAY_CHIP = re.compile(
    r'\+\s*[$S5§]?\s*((?:' + DC + r'|[.,])+(?:\s(?:' + DC + r'|[.,])+)?)'
    r'\s*incl(?:uded)?\b',
    re.IGNORECASE | ASCII)

# The minute unit has to be spelled out. It was once allowed to be a bare "m",
# and on a map full of street names that turns any two letters into a journey:
# "ZIM" out of the road texture became a 21-minute leg, which is enough to make
# a screen with no offer on it look like an offer. The "i" may still be a
# lookalike, because that is one guess inside a word already confirmed.
# A leg's two numbers sit side by side, and the card decides which comes first.
#
# This used to read time-then-distance only, because that is what the older card
# printed: "23 min (8.4 mi) trip". The card this driver is mostly shown now
# prints the other way round —
#
#     $7.50 Guaranteed (incl. tips)  8.0 mi + 25 min  @ Pickup Crumbl
#
# — and against that, LEG matched "25 min" alone. The leg came out with a time
# and no distance, the distance arrived separately through LONE_MILES, and the
# whole per-leg machinery went past it: 142 of 604 cards on file.
#
# It is not only the parse that suffers. accumulate.py matches a leg to a slot
# on EITHER its time or its distance agreeing, and a leg with no distance has
# only the one signal — exact equality of minutes. One frame reading "28 min" as
# "26 min" then lines up with nothing, `_is_a_different_card` calls it a
# replacement, and the window resets. Measured on one real card read sixteen
# times over 45 seconds: five separate offers filed, for one card the driver was
# looking at once. Across the driver's journal, 90 cards were filed more than
# once — 104 surplus rows, 7.6% of it.
#
# So the rule is adjacency in EITHER order, and the glue is the card's own
# bullet: at least one non-space non-word glyph, at most three. Measured over
# the 604: every distance-then-time pair on file is joined by punctuation
# ('+', '-', '«', '+-'), never by a bare space and never by more than three
# glyphs. A bare space is two things next to each other rather than one printed
# line, which is what keeps "$16.05 Promo 4.8 mi 25 min away" from claiming the
# promo's distance. Brackets are excluded from the glue because a distance the
# card closed a bracket on belonged to what came before it.
LEG = re.compile(
    r'(?:(' + DC + r'{1,3}(?:[.,]' + DC + r'{1,2})?)\s*m(?:i|ile|iles)\b'
    r'\s*[^\s\w()]{1,3}\s*)?'
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
#
# The charger badge is spelled out on its own because it is the one entry here
# that is a word STEM. Inside the `\b(?:...)\b` group, `fast\s*charg` can never
# match "fast charger": the closing boundary has to fall between "charg" and
# "e", and there is no boundary there. So the one badge that appears on the very
# cards this stopper was written for — `Cumberland Blvd SE, Atlanta 4, 7 mi from
# fast charger` — walked straight past it, and the address a driver reads to
# recognise the job months later has a charger advert stapled to the end of it.
# Three of one shift's 210 cards.
PLACE_TAIL = re.compile(
    r'(?:\|'
    r'|\bfast\s*charg'
    r'|\b(?:avg|wait\s*time|add\s+to\s+route|accept|decline'
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

# The commonest delivery card puts BOTH ends of the job after one total leg:
#
#     27 min (7.3 mi) total  Rick's Hotwings (Kennesaw)  Hamby Place Dr NW &
#     Travistock Pl NW, Acworth
#
# There is no "Pickup" label to anchor on and only one leg, so the leg-tail rule
# picked the whole thing up as a single place — 71 characters of merchant and
# address together, which the 60-character cap then threw away entire. Both ends
# of the job, lost to a length check, on 53 of one shift's 210 cards.
#
# The card's own grammar separates them: Uber prints the merchant with its
# branch in brackets, and where the job goes after that. So the closing bracket
# is the seam.
PLACE_MERCHANT = re.compile(r'^(.{2,44}?\([^)]{2,34}\))\s*(.{4,})$', ASCII)

# ...and an address ends at its town. Nothing on the card marks the end of one,
# which is what left "Lakeview Ter & Windmill Dr, Dallas ill" in the journal —
# the "ill" is the bottom icon row. A comma, a capitalised name or two, and that
# is the whole address; what follows is furniture.
#
# The possessive is allowed because a card does not always end on a town: "1min
# (0.2 mi) Roswell Road, Johnny's Hideaway" ends on the venue, and a rule that
# stopped at the first capitalised word after a comma cut it to "Roswell Road,
# Johnny". Lower case still ends it, which is what keeps the icon row out.
PLACE_ENDS_AT_TOWN = re.compile(
    r"^(.*?,\s*[A-Z][A-Za-z]+(?:'s)?(?:\s+[A-Z][A-Za-z]+(?:'s)?)?)\b", ASCII)
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

# The other way a leg says it is part of the journey: it printed a distance and
# the reader did not get it. Matched against the same tail LEG_TAIL sees, on a
# leg that came out with no distance.
#
# LEG_TAIL is a word list, and this driver's ride cards do not use those words.
# They label a leg with an ADDRESS — "12 min (8.1 mi) Oak Ln, Marietta" — so
# both legs of a two-leg card count as travel only because they carry
# distances. The moment one of them loses its distance it drops out of the set
# legs_short_a_distance counts, the count falls to one, and the rule that exists
# for exactly this damage returns False. Measured: it fires on ONE of the
# driver's 604 cards, and on none of 1080 readings with a leg's distance broken.
#
# A bracket holding a digit is the distance still sitting on the card. It has to
# be the FIRST thing after the minutes, which is the whole difference between
#
#     20 min (7.3 m1) trip                      <- the bracket is this leg's
#     Avg. wait time at pickup: 1 min 9 mins (2.6 mi) Sedgefield Rd
#
# where a bracket appears in the wait line's tail too, but another leg's minutes
# come first. Searching the tail loosely instead fires on 43% of clean cards;
# anchored it fires on 3%, and every one of those is an "Add a delivery" card
# whose distance really is printed and really did not read.
#
# This is what a wait line, a promo chip and an ETA badge do not have, which is
# the objection the `travel` set was built to answer: they are followed by the
# next leg, and a leg begins with a word.
#
# Nothing is asked about what is INSIDE the bracket. Requiring a digit there
# sounds like a second belt and is a hole: the number is exactly what the damage
# removes, so "9 min (~ mi)" — the distance gone altogether — carries no digit to
# find. Measured over 3466 readings damaged four different ways, the digit
# clause halved what the rule caught, 2096 down to 1052, and bought nothing: both
# versions fire on zero of the 604 clean cards.
LEG_LOST_MILES = re.compile(r'^[^\w(]{0,3}\(', ASCII)

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


# Whitespace, as the UNION of what the two languages call it.
#
# Python's `\s` is Unicode and JavaScript's is not, and they disagree about
# exactly six characters: U+001C to U+001F and U+0085 collapse in Python only,
# U+FEFF in JavaScript only. normalize() runs `\s+` in both ports, so a card
# carrying one of those six arrives as two different strings and every rule
# downstream reads a different card.
#
# It reaches a published number, and in both directions. The map screen this
# parser refuses - "$ 22min" among route times - is refused by whichever port
# collapsed the character and taken as a $22 payout by the other: U+0085 makes
# the browser publish it, U+FEFF makes the Pi. Six invisible characters
# deciding whether a road is rated as an offer.
#
# So each port is told about the other's set, and both collapse the union. No
# card on file carries any of the six; this is a hole closed rather than a bug
# repaired, and the corpus now holds all six so it stays closed.
WHITESPACE = re.compile(r'[\s\ufeff]+')


def normalize(text):
    text = str(text or '')
    text = re.sub(r'[‘’“”]', "'", text)
    text = re.sub(r'[–—−]', '-', text)
    text = text.replace(' ', ' ')
    return WHITESPACE.sub(' ', text).strip()


# A number that is a duration or a distance, wearing a dollar sign.
#
# The rig photographs whatever is on the phone, and between jobs that is the map.
# One screen off this driver's own shift:
#
#     The Townes at Chastain ... Windsor Drive ... 3min  11 min  $ 22min
#     3 min (1.0 mi)  Fastest route now due to traffic conditions
#
# Route alternatives, with a map glyph in front of one of them that read as a
# dollar sign. find_pay took $22, the four times added to 39 minutes, and the
# panel showed a green **ACCEPT at $33.38/hr** for a road. It went into the
# journal as an offer and into the medians as a rate.
#
# The grammar is the card's own and needs no list of screens: a payout says what
# it is, or says nothing, but it is never glued to a unit. "$13.05 ... $ 12 min
# (6.3 mi)" is a real card off the same shift, where a stray glyph sits in front
# of the leg — the $12 is refused and the $13.05 headline is untouched, which is
# the whole test of whether this rule is narrow enough.
#
# One card in 604 changes: the map stops being an offer and becomes an
# unfinished reading, which is what it is. No corpus text moves.
#
# Only the abbreviations these screens actually print — "min", "mins", "mi" —
# and not the spelled-out forms LEG tolerates. A merchant is what sits next to a
# payout when the label between them does not read, and "$12 Minute Maid Park"
# would lose its payout to a rule that accepts "minute". Narrowing to the
# printed grammar is the same move LEG_TAIL makes, and it costs nothing: no card
# in 604 is read differently either way. "Mi Casa" is the collision that
# remains, and it is the safe direction — no payout, so no verdict, rather than
# the wrong one.
PAY_IS_A_DURATION = re.compile(
    r'\$\s*(?:' + DC + r'{1,4}(?:[.,]' + DC + r'{1,2})?)\s*'
    r'(?:m[il1|]ns?|mi)\b',
    re.IGNORECASE | ASCII)


def find_pay(text):
    chips = [m.span() for m in PAY_CHIP.finditer(text)]
    units = [m.span() for m in PAY_IS_A_DURATION.finditer(text)]

    def in_chip(m):
        # A figure inside a "+$0.50 included" chip is part of the payout, not a
        # candidate to be it. See PAY_CHIP: without this the largest-figure rule
        # hands a green light to a chip whose decimal point did not read.
        return any(start <= m.start() and m.end() <= end for start, end in chips)

    matches = list(MONEY_STRICT.finditer(text)) or list(MONEY_LOOSE.finditer(text))
    best = None
    for m in matches:
        if in_chip(m):
            continue
        # An amount has to contain a real digit. `DC` lets a letter stand in for
        # a digit inside a number that is otherwise confirmed, which is right —
        # but a token made ENTIRELY of those stand-ins is not a number that lost
        # a character, it is a word.
        #
        # "$ Bound Ct & Shoals" came off a real card. B reads as 8, o reads as
        # 0, and a street name two lines below the headline became an EIGHTY
        # DOLLAR payout on a $9.03 delivery — published at $153.52/hr, the
        # highest ACCEPT of that shift. The dollar sign was real; every digit
        # after it was a guess.
        #
        # This is the rule find_legs already applies to a duration, in the same
        # words: "the number in front of it has to contain a real digit; 'SI
        # min' is two guesses stacked, and stacked guesses are how noise becomes
        # data." Money never got it. Two cards in 604 change, both from a
        # phantom $80 to their true $9.03, and no corpus text moves.
        # ...and a figure that is really a duration or a distance is not a
        # candidate either. See PAY_IS_A_DURATION.
        if any(start <= m.start() and m.end() <= end for start, end in units):
            continue
        if not HAS_DIGIT.search(m.group(1)):
            continue
        v = to_number(m.group(1).strip())
        # The offer headline is the largest dollar figure; promo lines are smaller.
        if v is not None and 0 < v < 2000 and (best is None or v > best):
            best = v

    # A headline the reader cut in half. See PAY_SPLIT: the halves are put back
    # together only where the card's own label follows them, and the joined
    # figure then competes as an ordinary candidate. It always beats the "$1"
    # fragment it was built from — joining digits can only make a number larger
    # — so the largest-figure rule picks it up without any special standing.
    for m in PAY_SPLIT.finditer(text):
        if in_chip(m):
            continue
        # Both halves, because joining two guessed halves is the same two
        # guesses stacked with an extra step in between.
        if not (HAS_DIGIT.search(m.group(1)) and HAS_DIGIT.search(m.group(2))):
            continue
        v = to_number(m.group(1).strip() + m.group(2).strip())
        if v is not None and 0 < v < 2000 and (best is None or v > best):
            best = v
    return best


def find_legs(text):
    legs = []
    for m in LEG.finditer(text):
        mins = to_number(m.group(3))
        if mins is None or not HAS_DIGIT.search(m.group(3)):
            continue
        minutes = (to_number(m.group(2)) or 0) * 60 + mins
        if minutes <= 0 or minutes > 600:
            continue

        # The distance printed BEFORE the time, if the card put it there. It
        # keeps the two rules a lone distance already keeps: a real digit, and
        # not preceded by a digit or a decimal point — without the second,
        # "1.9 mi" damaged to ".9 mi" reads as nine miles.
        lead = m.group(1)
        if lead is not None and (
                not HAS_DIGIT.search(lead)
                or (m.start(1) > 0 and text[m.start(1) - 1] in '0123456789.,')):
            lead = None
        # The bracketed one wins when a card prints both: the bracket is the
        # card saying which time this distance belongs to.
        side = m.group(4) if m.group(4) is not None else lead
        miles = to_number(side)
        # NOT the real-digit rule that money and the lone distance now keep,
        # and the reason is worth writing down so it is not "fixed" later.
        #
        # Refusing "(SO mi)" leaves the leg with a time and no distance, and on
        # a single leg the card labelled `total` that reading calls itself
        # WHOLE: no distance means no mileage charged, so `$12.45 20 min (SO
        # mi) total` goes from $32.85/hr with a distance to $37.35/hr without
        # one, unflagged, and into the medians. Today the same token becomes
        # 50 miles, which check_distance catches as 150 mph and pulls back.
        #
        # A guard that turns a caught error into a silent one is not a guard.
        # The honest fix is for a leg that lost its distance to stop the
        # reading being whole — which legs_short_a_distance already does for
        # two legs and cannot do for one — and that belongs with that work,
        # not here.
        if miles is not None and (miles < 0 or miles > 500):
            miles = None
        # A decimal point is a pixel or two through a lens and is the first
        # thing to be lost, so remember whether this reading actually had one.
        had_decimal = side is not None and bool(re.search(r'[.,]', side))

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
            # The same question asked of the card's punctuation rather than its
            # vocabulary: a bracket sitting where this leg's distance should be,
            # on a leg that has none. See LEG_LOST_MILES. Only meaningful when
            # the distance did not read, so it is not set when one did — a leg
            # that has its miles is already part of the journey.
            # ...or the leg's own distance group matched and the token inside
            # it would not become a number.
            #
            # The tail test can only ever see a bracket the LEG regex FAILED to
            # consume, so it catches damage that lands on the unit - "(8.1 m1)"
            # - and is blind to damage that lands on the digits, which is the
            # class this rule was written for. "(8.L mi)" is a "1" read as an
            # "L", which this file calls the commonest single confusion there
            # is: DC accepts the L, the bracket is swallowed by the match, the
            # tail begins at the address, and the leg dropped silently out of
            # the journey. Measured on a two-leg card: 17 minutes charged
            # against 1.8 of the journey's 9.9 miles, whole and unflagged, a
            # green $72.49/hr where the truth is $63.92.
            #
            # `side` is what the card printed in the distance slot. Non-empty
            # with no number out of it is the same statement the bracket makes,
            # read from the other side.
            'lostMiles': miles is None and (side is not None
                                            or bool(LEG_LOST_MILES.search(tail))),
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
    if legs_short_a_distance(parsed.get('legDetail') or [],
                             parsed.get('miles')):
        return False
    # ...and its mirror: a distance the card printed that no leg claimed. The
    # leg that lost its minutes was dropped whole, so the journey is short a
    # time AND short a distance, which flatters the rate twice. Another frame is
    # the answer, exactly as above.
    if parsed.get('shortATime'):
        return False
    if parsed.get('hasTotal') or any(
            leg.get('isTotal') for leg in (parsed.get('legDetail') or [])):
        return True
    if (parsed.get('legs') or 0) >= 2:
        return True
    # One token, and whether it is half a journey or a whole job is decided by
    # whether the card labelled it — the same question `legs_short_a_distance`
    # asks, for the same reason. Uber labels every leg of a ride (away, trip,
    # total), so a labelled single leg has a sibling that did not read and
    # another frame can still supply it. An unlabelled one is the "2.4 mi ·
    # 20 min" line of a delivery card: a summary of the whole job, not a leg,
    # and there is no second half coming.
    #
    # This was 37 of the driver's own 309 cards, all reading `complete` and
    # never `whole`: shown with a question mark for the life of the offer,
    # never spoken, set aside on the offers page, and resampled until the card
    # went away — for a reading that had the pay, the distance and the time and
    # nothing left to learn.
    legs = parsed.get('legDetail') or []
    if (parsed.get('legs') or 0) == 1 and legs and not legs[0].get('labelled'):
        return (parsed.get('miles') is not None
                and parsed.get('minutes') is not None)
    return (not (parsed.get('legs') or 0)
            and parsed.get('deliverBy') is not None
            and parsed.get('miles') is not None)


# A distance the card printed that no leg claimed.
#
# The mirror of legs_short_a_distance, and the more dangerous half: that one
# catches a leg that lost its miles, this one catches a leg that lost its
# MINUTES — and minutes are the denominator, so losing them makes the rate look
# bigger twice over. The leg goes entirely, taking its distance with it, so the
# journey comes out shorter in both time and miles.
#
# On these cards a bracketed distance belongs to the time printed beside it —
# that is what LEG's own trailing group says. So a bracketed distance sitting
# outside every leg is a leg the reader failed on, and no list of phrases is
# needed to say so.
#
# Five of this driver's 604 cards, from two different causes, and four of the
# five turn a PASS into an ACCEPT:
#
#   $9.05 * 5.00 min (44 mi)    the star rating sits where the duration goes,
#                               "00" reads as zero minutes -> $49.62/hr ACCEPT
#                               against the eight-frame answer of $19.86 PASS
#   $8.07 *% 490 ll min (35 mi) the minutes spelled entirely in stand-ins, which
#                               HAS_DIGIT correctly refuses -> $35.40/hr ACCEPT
#                               against $15.89 PASS
#
# Both refusals are right. What was wrong is that the distance went with them.
#
# The answer is not to guess the missing time. It is to stop calling the reading
# whole: the rig keeps looking, the panel says it has not finished, and the
# accumulator merges a later frame that read the leg properly — which is what
# already rescued three of these five at scan time.
LEG_ORPHAN = re.compile(
    r'\(\s*(' + DC + r'{1,3}(?:[.,]' + DC + r'{1,2})?)\s*m(?:i|ile|iles)\b\s*\)',
    re.IGNORECASE | ASCII)


def distance_without_a_time(text, legs):
    """True when the card printed a bracketed distance that no leg claimed."""
    spans = [(l['start'], l['end']) for l in legs]
    for m in LEG_ORPHAN.finditer(text):
        # The same real-digit rule the minutes beside it keep: a bracket full of
        # stand-ins is not a distance the card stated.
        if not HAS_DIGIT.search(m.group(1)):
            continue
        if any(start <= m.start() and m.end() <= end for start, end in spans):
            continue
        return True
    return False


def legs_short_a_distance(legs, miles=None):
    """True when a journey is missing a distance one of its legs should carry.

    `miles` is the distance the READING ended up with, from any source, and is
    consulted only for the single-leg case below. None means the reading has no
    distance at all - which is also the default, so a caller that forgets to say
    lands on doubt rather than on a number nobody checked.

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
    used to be left alone entirely, because it can be a total — the corpus has
    `$7.09 34 min total`, which states no distance and is a whole journey by
    itself.

    That exemption was never about the COUNT. It was about not being able to
    tell a total from a leg whose distance failed to read, and `lostMiles` is
    what tells them apart: a total prints no bracket where a distance would go,
    and a damaged leg still has one.

    It has to be asked, because once the two-leg hole was closed this became the
    bigger half — 335 of the 337 damaged readings still publishing an optimistic
    rate had ONE leg.

    The `miles is None` guard is the whole risk and the reason this is not
    simply "a single leg with lostMiles". The "Add a delivery" cards have one
    leg whose distance did not read AND a lone distance that the branch in
    parse() recovers a few lines later, so they end up with the RIGHT number.
    Doubting those would throw away a good reading, which this project treats as
    exactly as bad as publishing a wrong one.
    """
    if len(legs) == 1:
        # Not `labelled`: a card that labelled its only leg still says nothing
        # about whether a distance was ever printed beside it, and a total is
        # exactly that shape.
        return bool(legs[0].get('lostMiles')) and miles is None
    if len(legs) < 2:
        return False
    # A leg is part of the journey if it states a distance, if the card labelled
    # it one, or if a distance is printed beside it that did not read. A
    # minutes-only token with none of those is a wait line, a promo chip or an
    # ETA badge — not a leg the reader failed on — and counting it here switched
    # the mileage cost off on a third of every offer read.
    #
    # Their minutes are still counted. The driver really does wait at the
    # pickup, and dropping the time would raise the rate, which is the one
    # direction that turns a pass into an accept.
    #
    # `lostMiles` is the third clause, and without it this rule was unreachable:
    # the label words are ride-card vocabulary this driver's cards do not print,
    # so damage that removed a leg's distance also removed the leg from the set
    # counted here, and the count fell below two. See LEG_LOST_MILES.
    travel = [l for l in legs
              if l.get('miles') is not None or l.get('labelled')
              or l.get('lostMiles')]
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


# A name the card put a bracket after — "Kroger (Shiloh Square)", "GoPuff
# (Drive)", "McDonald's® (Wade Green)". That is how these cards write a shop,
# and it is the one thing that distinguishes the place a job STARTS from the
# place it ENDS.
PLACE_IS_A_SHOP = re.compile(r'\([^)]{2,40}\)\s*$', ASCII)


# The card's own word for where a job starts. A place printed right after it is
# a pickup however it is named — "@ Pickup Crumbl", "Retail pickup GoPuff" — and
# brackets have nothing to do with it.
# Between the label and the shop there is nothing but marks — "@ Pickup |",
# "@ Pickup 3)", the icon row the crop catches. Between the label and a LATER
# leg's address there is always a leg, and a leg is spelled with letters:
# "at pickup: 1 min 10 mins (4.6 mi) N Cobb Pkwy NW". So "no letters in
# between" is the whole discriminator, and it is the card's own layout rather
# than a list of separators.
PICKUP_LABEL = re.compile(r'\bpick\s?up\b[^A-Za-z]*$', re.IGNORECASE | ASCII)


# --- the address the card will not show you until you have taken the job ------
#
# 106 of the driver's 604 offer cards print "Customer dropoff" and no address at
# all: Uber does not say where the job ends until it is accepted. That is 18% of
# every card the rig sees, and it is what drives 39% of the pairs where the
# stacking advice can say nothing. No parser reaches an address that is not on
# the screen, so this reads the screen that comes AFTER the accept.
#
# The anchor is a two-letter state code followed by five digits. It is the one
# part of a US address that is short, positional, and CHECKABLE — "GA 30127" is
# a state and a ZIP or it is not, where a street name misread by one letter is
# still a perfectly plausible street name and nothing downstream can tell.
#
# That checkability is the whole reason this is worth doing at all. The
# alternative on the table was sending the address to a geocoder, and a geocoder
# returns a confident coordinate for "Daffodll Ln" as readily as for the real
# one — a wrong distance wearing decimal precision, which is the failure this
# project refuses above all others. Here a state that is not a state, or a ZIP
# that is not five digits, produces None and the rig says it did not read it.
ZIP = DC + r'{5}'

# The fifty states, DC and the inhabited territories. A list, and deliberately
# one: the rule against phrase-lists is about lists that do not generalise to
# the next card — merchants, towns, the words a promo chip happens to use. This
# alphabet is closed, national, and older than the app. It is also doing the
# opposite job to a phrase-list: it is here to REFUSE, so an OCR misread lands
# on "no address" rather than on a confident wrong one.
STATES = set((
    'AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS '
    'MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV '
    'WI WY DC AS GU MP PR VI'
).split())

# "…, Powder Springs, GA 30127" and the ZIP+4 form. The city is taken back to a
# comma or the start, because that is where a US address puts the break; the
# street is whatever preceded it, and is kept only for showing.
ADDRESS = re.compile(
    r'([A-Za-z][A-Za-z.\'’-]*(?:\s+[A-Za-z][A-Za-z.\'’-]*){0,3})'
    r'\s*,\s*([A-Za-z]{2})\s+(' + ZIP + r')(?:\s*-\s*' + DC + r'{4})?(?!\d)',
    ASCII)

# A house number and a street, taken only to show the driver what was read. It
# never decides anything, so it is the loosest rule here — but WORDS, not
# "anything but a comma". A card printing "28 min (11.2 mi) total 100 Rosemont
# Ct" satisfies the loose version from the "28", and the driver is shown the
# offer's own arithmetic dressed up as a street name.
STREET = re.compile(
    r'(' + DC + r"{1,6}\s+[A-Za-z][A-Za-z.'-]*"
    r"(?:\s+[A-Za-z0-9.'-]+){0,4})\s*$", ASCII)

# A single letter standing alone in front of a town is the icon row, not a word:
# "l Atlanta", "j Powder Springs", "} Marietta". PLACE_TOWN in advice.js already
# tolerates exactly this, and the two have to agree about what a town is called
# or the same place read twice compares unequal to itself.
CITY_JUNK = re.compile(r'^(?:[A-Za-z]\s+)+', ASCII)

# Where a street stops and a town starts, when the address did not say with a
# comma — which is the case to expect, not the exception: a screen puts the
# street and the town on two lines and `normalize` joins them with a space.
#
# The USPS street-suffix abbreviations, and a list for the same reason STATES is
# one: closed, national, older than the app, and here to draw a line rather than
# to recognise a place. Without it "1234 Daffodil Ln Powder Springs, GA 30127"
# has no grammar for where the street ends, and the town comes out as "Daffodil
# Ln Powder Springs" — which two readings of the same street would disagree
# about. The optional trailing quadrant is part of the street, not the town:
# "Chastain Rd NW Kennesaw".
STREET_ENDS = re.compile(
    r'\b(?:st|street|rd|road|dr|drive|ln|lane|ave|avenue|blvd|boulevard|ct'
    r'|court|way|pkwy|parkway|cir|circle|trl|trail|hwy|highway|ter|terrace'
    r'|pl|place|xing|crossing|sq|square|loop|run|walk|path|row|bnd|bend)\b'
    r'\.?(?:\s+(?:NW|NE|SW|SE|N|S|E|W))?\s+', re.IGNORECASE | ASCII)


def find_address(text):
    """A full street address off a post-acceptance screen, or None.

    Returns {'line', 'street', 'city', 'state', 'zip'} — `line` is what to show
    and what to store, `zip` is what the geography is actually decided on. See
    Advice.area: a ZIP is a few square miles, where "same town" in Atlanta is a
    hundred and thirty-five of them and 44% of this driver's dropoffs are in
    Atlanta.

    Refuses far more readily than the rest of this file, and on purpose. Every
    other rule here is reading a card the driver can also see and is deciding a
    number they can sanity-check; this one is filling in a fact they cannot
    check later, against an offer that has not arrived yet. So a state that is
    not a state, or five digits that are not a plausible ZIP, is None.
    """
    if not text:
        return None
    text = normalize(text)
    best = None
    after = 0          # where the previous address ended; see `head` below.
    for m in ADDRESS.finditer(text):
        state = m.group(2).upper()
        # `fix_digits` first: the ZIP is five characters of small type through a
        # lens, and "3O127" is this OCR's commonest confusion, not a different
        # number. The state gets no such help — two letters have no digits in
        # them, and "6A" corrected to "GA" would be inventing the one token that
        # is here to refuse.
        digits = fix_digits(m.group(3))
        if state not in STATES or not digits.isdigit() or len(digits) != 5:
            continue
        # 00501 is the lowest ZIP in use and 99950 the highest. A five-digit
        # number outside that is a phone fragment or an order id, not a place.
        code = int(digits)
        if not (501 <= code <= 99950):
            continue
        city = CITY_JUNK.sub('', re.sub(r'\s+', ' ', m.group(1)).strip(' .,'))
        if len(city) < 3:
            continue
        # ...but only call it a city when the address said where it began. A US
        # address separates the street from the city with a comma; without one,
        # "1234 Daffodil Ln Powder Springs" gives no grammar for where the
        # street stops, and the group takes up to four words back — so the town
        # comes out as "Daffodil Ln Powder Springs" and two readings of the same
        # street disagree about where they are.
        #
        # There is no honest way to split it, so it is not split. The ZIP is
        # what the geography is decided on and it is unaffected; `line` still
        # shows the driver everything that was read, and `city` — the field
        # anything downstream would treat as a town — is None rather than a
        # guess. Per-field refusal, the same as a leg that keeps its minutes
        # and gives up its distance.
        # Where the city begins in the original text — which is not where the
        # group begins when the group swallowed the street.
        city_at = m.start(1)
        before = text[after:city_at].rstrip()
        if before and not before.endswith(','):
            # ...unless the street named its own end. Take the LAST suffix in
            # the group: "Old Mill Rd Powder Springs" has one, and a town that
            # happens to contain one — "Powder Springs Rd Marietta" — puts the
            # real break at the later of the two.
            split = None
            for s in STREET_ENDS.finditer(m.group(1)):
                split = s.end()
            if split is not None and len(m.group(1)) - split >= 3:
                city_at = m.start(1) + split
                # CITY_JUNK here as well as on the comma path above. The icon
                # row lands between the street and the town whichever way the
                # address was punctuated, and this is the path the code itself
                # calls "the case to expect": a screen puts the street and the
                # town on two lines and normalize joins them with a space.
                #
                # Stripped only here and not there, "800 Forrest St NW l
                # Atlanta, GA 30318" gave the town as "l Atlanta" - which
                # PLACE_TOWN in advice.js cannot read at all, because its junk
                # allowance covers a single UPPERCASE letter and not a lowercase
                # one. area() then returns no town and the geography goes SILENT
                # on exactly the orders the scan was added to rescue.
                city = CITY_JUNK.sub(
                    '', re.sub(r'\s+', ' ', text[city_at:m.end(1)]).strip(' .,'))
            else:
                city = None
        # From the end of the previous address, never before it. A screen
        # listing two stops puts a ZIP between them, and a street search over
        # the whole head reaches back across it: "…GA 30339 then 12 Oak Ln"
        # was stored as the street.
        #
        # Up to where the CITY starts, not where the match does, so the half of
        # the group that turned out to be the street is still shown as one.
        head = text[after:city_at].rstrip(' ,')
        street = STREET.search(head)
        street = re.sub(r'\s+', ' ', street.group(1)).strip(' .,') if street else None
        # What to show, as opposed to what to decide on. When the city could not
        # be trusted, the driver still gets everything that was read — they are
        # looking at this to judge whether the scan worked, and "GA 30127" does
        # not tell them that. `city` stays None either way, so nothing
        # downstream treats the unsplit text as a town.
        line = ', '.join([p for p in (street, city) if p]
                         + ['%s %s' % (state, digits)]) if (street or city) \
            else re.sub(r'\s+', ' ', m.group(0)).strip(' .,')
        found = {'line': line, 'street': street, 'city': city,
                 'state': state, 'zip': digits}
        after = m.end()
        # The LAST one on the screen. A navigation screen shows where you are
        # going, and anything above it — a pickup already made, a previous stop
        # — comes first. Same reasoning as find_dropoff, which takes the last
        # place a card names for the same reason.
        best = found
    return best


def find_dropoff(places, text=None):
    """Where the job ENDS, or None when the card did not say.

    The driver's own description of these cards: "the drop off locations will
    always pretty much be someone's home address and not the restaurant". So
    the dropoff is the last place the card named, unless that place is a shop —
    and a shop is a name the card bracketed, which is the card's own grammar
    rather than a list of chains.

    Measured over 562 cards that name any place: the last one is a bracketed
    shop on 9 of them, every one a card where only the merchant read at all, so
    the honest answer there is None rather than the restaurant.

    Two other shapes land here and both come out right. A ride card names the
    pickup street and then the dropoff street, so the last is still the end. And
    an address split across two entries — "Northeast Expy NE & Westcheste" then
    "Ln NE, Atlanta" — leaves the tail last, which is the half carrying the town.
    """
    for place in reversed(places or []):
        if PLACE_IS_A_SHOP.search(place):
            continue
        # ...and a place the card LABELLED as the pickup is a pickup, bracket or
        # no bracket. Without this, the delivery card that prints "@ Pickup
        # Crumbl" and nothing else offers "Crumbl" as a destination: 112 of the
        # 135 dropoffs the rig could not place on a map were exactly this, an
        # unbracketed shop name standing in for somebody's front door. The word
        # has to end right where the place begins, or "Avg. wait time at pickup:
        # 1 min 10 mins (4.6 mi) N Cobb Pkwy NW" would disown a real address.
        if text and _labelled_pickup(text, place):
            continue
        return place
    return None


def _labelled_pickup(text, place):
    at = text.find(place)
    if at <= 0:
        return False
    # Everything before the place, not a window of it. A window was here and it
    # was an arbitrary number doing a job the letter rule already does: on all
    # 604 cards the two agree exactly, so the number was a second thing to get
    # wrong rather than a second guard.
    return bool(PICKUP_LABEL.search(text[:at]))


def find_pickup(places):
    """Where the job STARTS, or None when the card did not say.

    The mirror of find_dropoff and the weaker of the two, which is the right
    weighting: the driver does not take a second order whose pickup is far away
    in the first place, so this is for showing rather than for judging. A shop
    is what the card brackets; when nothing is bracketed the first place is the
    pickup, because that is the order a card prints its journey in.
    """
    for place in places or []:
        if PLACE_IS_A_SHOP.search(place):
            return place
    return (places or [None])[0]


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

    def ends_at_town(value):
        m = PLACE_ENDS_AT_TOWN.match(value)
        return m.group(1) if m else value

    # The tail of each leg, up to whatever comes next.
    #
    # 130 characters rather than 80. On the single-total delivery card the tail
    # holds the merchant AND the address, and 80 cut the town off the end of the
    # one that matters: "Double Branches Ln & Sagamore Ct. Dal". The window can
    # afford it now that the tail is split rather than stored whole.
    for i, leg in enumerate(legs):
        start = leg.get('end')
        if start is None:
            continue
        stop = legs[i + 1].get('start') if i + 1 < len(legs) else len(text)
        tail = text[start:stop][:130]
        # Cut at the first thing that is plainly not part of an address.
        tail = re.split(r'\b(?:accept|decline|verified|exclusive|guaranteed'
                        r'|add\s+to\s+route|\d+\s*mi\b)', tail,
                        maxsplit=1, flags=re.IGNORECASE | ASCII)[0]
        # Trimmed before it is judged, not after. The test asks whether this is
        # an address, and the thing to ask it about is the string that would be
        # stored — `1 min ~ 4 . mins | . = | i oO < * ~~ agama ae ae; i Old
        # Mountain Rd NW, Kennesaw` passes on the address buried at the end of
        # it and then goes into the journal sludge and all.
        # A pipe with an address after it is two places, not one. The card's
        # own dividers and its icon row both come back as pipes, so `trim_place`
        # cuts at the first one — and everything past it went with it.
        #
        # The JavaScript port has always split here and this one never did,
        # which is the two readers disagreeing about the same card: on 21 of one
        # shift's 309 the phone stored a dropoff the rig did not. Neither corpus
        # case reached it, because a pipe is what a camera makes of a line and
        # no hand-written fixture had one.
        pieces = [tail]
        bar = tail.find('|')
        if bar >= 0 and looks_like_a_place(trim_place(tail[bar + 1:])):
            pieces = [tail[:bar], tail[bar + 1:]]
        for piece in pieces:
            piece = trim_place(piece)
            # Two places in one piece, when the card wrote them that way. The
            # merchant is kept without asking looks_like_a_place: "Rick's
            # Hotwings (Kennesaw)" names no street and no town, so that test
            # refuses it, and it is still exactly where the driver goes first.
            # The bracketed branch is the card vouching for it.
            pair = PLACE_MERCHANT.match(piece)
            if pair:
                keep(pair.group(1))
                drop = ends_at_town(trim_place(pair.group(2)))
                if looks_like_a_place(drop):
                    keep(drop)
                continue
            piece = ends_at_town(piece)
            if looks_like_a_place(piece):
                keep(piece)

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

    # A card gives distances to one decimal place, so a sum of them has one
    # decimal place. Binary floating point disagrees: 3.5 + 6.1 is
    # 9.600000000000001, and that went into the journal, into the CSV export and
    # into anything reading either. Rounded here rather than at each display, so
    # the stored number and the shown number are the same number.
    if miles is not None:
        miles = round2(miles)
    corrected = corrected_leg
    uncertain = False

    m = ITEMS.search(text)
    items = to_number(m.group(1)) if m else None
    if items is not None and not (0 <= items <= 200):
        items = None

    pay = find_pay(text)

    # A delivery card states no duration and puts its distance on its own, so
    # neither reaches the sum above.
    #
    # "Consulted only when the legs found nothing" is what this used to say, and
    # `not used` is not that test. The commonest card this driver is shown reads
    #
    #     $7.20 Guaranteed (incl. tips) 2.4 mi + 20 min @ Pickup McDonald's
    #
    # where the distance and the time are two halves of ONE line, not a journey
    # leg. The "20 min" half is picked up as a minutes-only leg, `used` is
    # therefore truthy, and the "2.4 mi" sitting four characters away is thrown
    # out. On the driver's own 309-card export that happened 37 times — 12% of
    # every offer read — and all 37 for this one reason. No distance means no
    # mileage charged, which means the panel showed a ceiling as if it were a
    # rate: the exact failure the uncosted cap exists to contain, arriving
    # through the door the cap cannot see.
    #
    # The right test is the one `legs_short_a_distance` already uses. A leg is
    # part of the journey if it states a distance or the card labelled it one;
    # an unlabelled minutes-only token was never a leg. So a lone distance is
    # consulted when nothing that travels was found, which still leaves a real
    # ride card alone — its legs carry distances — and still refuses to hand a
    # stray number to a LABELLED leg that lost its own, because that is damage
    # and `short_a_leg` is already saying so.
    deadline = find_deadline(text)
    travelled = [l for l in used
                 if l['miles'] is not None or l.get('labelled')]
    if miles is None and not travelled:
        lone = LONE_MILES.search(text)
        # "4, Smi ~ fast charger" is on a real card, and S reads as 5. A lone
        # distance is already the least anchored number the parser takes; one
        # spelled entirely in stand-ins is not anchored at all.
        #
        # ...unless it printed a decimal point, which is structure the badge
        # does not have. The badge shapes are bare — "Smi", "Lmi", "Imi" — while
        # a real distance on this card reads "l.S" or "ll.l", and a "1" lost to
        # an l or an I is this OCR's commonest single confusion. Without this
        # clause the card has NO distance, so no mileage is charged, and the
        # rate goes UP while the verdict is capped: "l.S mi + 25 min" on a
        # $12.50 offer published $30.00/hr CLOSE CALL where the truth is 1.5
        # miles and a $28.92/hr ACCEPT. That is a guard failing in both
        # directions at once — clipping a real green light and inflating the
        # number it clips it to — which is exactly what the same rule refuses
        # to do to a leg's distance a few hundred lines up.
        if lone and (HAS_DIGIT.search(lone.group(1))
                     or LONE_DECIMAL.search(lone.group(1))):
            v = to_number(lone.group(1))
            if v is not None and 0 < v <= 500:
                miles = round2(v)
                # Whether the token carried a decimal point, which is the one
                # thing recover_decimal needs to know and the one thing that is
                # lost the moment the string becomes a float. A card printing
                # "10.0 mi" and one printing "10 mi" arrive here identical.
                had_decimal = bool(LONE_DECIMAL.search(lone.group(1)))

    # The distance is checked HERE, below the lone-distance branch, and not
    # above it where this call used to sit.
    #
    # Above it, the check ran while `miles` was still None on every card whose
    # distance the legs did not carry — the delivery card that prints
    # "8.0 mi + 25 min", where the "25 min" half is a minutes-only leg and the
    # distance arrives from LONE_MILES four lines below. So the distance was set
    # after the last check that could have looked at it, and then stamped
    # `milesChecked: True`, whose own comment claims check_distance has already
    # run against the legs' own minutes. It had not. That flag is also what
    # gates rate()'s recovery re-check, so the false stamp closed the second
    # door as well.
    #
    # 140 of the 604 cards on file take that path. Five of them are damaged, and
    # they were being published at 98, 117, 157, 196 and 2220 mph — three at a
    # NEGATIVE dollars per hour, because the phantom distance ate the fare as
    # mileage cost. "+21 min (+55 mi) total" is a real Applebee's run: 157 mph,
    # -$26.89/hr and refused as doubtful, where the truth is 5.5 miles and
    # $15.54/hr.
    #
    # Nothing else moves. check_distance never returns None, so `miles is None`
    # in the branch above is unchanged by the motion, and every card whose
    # distance came from a leg gets the identical answer — measured on all 604
    # clean, and again with the decimal stripped from all 424 leg-borne texts:
    # zero differences either time.
    miles, checked_corrected, checked_uncertain = check_distance(
        minutes, miles, had_decimal)
    corrected = corrected or checked_corrected
    uncertain = uncertain or checked_uncertain

    # Asked HERE, below the lone-distance branch and below check_distance, not
    # up beside the leg sum where it used to sit. The single-leg clause turns on
    # whether the reading ended up with a distance from anywhere, and up there
    # the answer is only "did the legs carry one" — which on an "Add a delivery"
    # card is No a few lines before the lone branch makes it Yes. Asked early,
    # the rule would doubt every one of those cards for a distance it was about
    # to recover correctly. The multi-leg branch does not look at `miles` at all,
    # so nothing else moves.
    short_a_leg = legs_short_a_distance(used, miles)
    uncertain = uncertain or short_a_leg

    places = find_places(text, legs)
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
        'places': places,
        # The two ends, named. `places` is what the card said and is what the
        # journal and the offers page show; these say which of them is which,
        # so a second offer can be judged against the one already in the car.
        # See find_dropoff, which is the half that decides.
        'pickup': find_pickup(places),
        'dropoff': find_dropoff(places, text),
        # A full street address, which an offer card never shows — Uber does not
        # say where a delivery ends until it has been accepted. This is here so
        # the screen AFTER the accept can be read by the same pipeline, and it
        # is None on every one of the 604 offer cards on file. See find_address.
        'address': find_address(text),
        # The legs behind the sum, so a caller holding readings from several
        # frames can merge the ones a single frame missed.
        # `labelled` travels with them. is_whole re-runs
        # legs_short_a_distance over this projection, and a field the rule needs
        # that does not survive the trip is a rule that quietly stops working:
        # every minutes-only leg looked unlabelled here, so a two-leg card whose
        # second distance came back as "7.3 m1" called itself whole again.
        'legDetail': [{'minutes': l['minutes'], 'miles': l['miles'],
                       'isTotal': l['isTotal'], 'labelled': l['labelled'],
                       'lostMiles': l['lostMiles']}
                      for l in used],
        'items': items,
        'legs': len(used),
        'milesCorrected': corrected,
        'milesUncertain': uncertain,
        # A distance is only as checkable as the time beside it. Where the card
        # states a time, check_distance has run against it — whatever the
        # distance's source, since the call moved below the lone-distance
        # branch; on a card with no minutes at all it returned the number
        # untouched, and this says whether it may still be recovered later. See
        # rate(), which is where the clock is.
        #
        # The wording used to say "on a ride card", and that was the whole
        # defect: the delivery cards this driver is mostly shown DO state a
        # time, so they were stamped checked while their distance had met no
        # check at all — and this flag gates rate()'s second attempt, so the
        # false stamp shut that door too.
        'milesChecked': minutes is not None,
        'milesHadDecimal': had_decimal,
        # Whether the card printed a distance no leg claimed, which means a leg
        # lost its minutes and took its miles with it. See
        # distance_without_a_time: this is not a number, it is the reason the
        # reading is not finished, and is_whole is where it is spent.
        'shortATime': distance_without_a_time(text, legs),
        'complete': is_complete(pay, minutes, deadline),
        # What the card says it is. None when the card did not say — the top
        # chip may simply not have been inside the crop — which is different
        # from "not a shop order" and is kept different.
        'shop': True if SHOP_CARD.search(text) else None,
        'text': text,
        # ...and the same reading before normalize() flattened it.
        #
        # `text` above is what this parser works on: whitespace collapsed to
        # single spaces, so every rule can be written without caring how the
        # engine broke the lines. That flattening throws away WHICH LINE each
        # figure was on, and the card's meaning is partly in its lines: "2.4 mi
        # + 20 min" is one line and therefore one journey, while a distance and
        # a duration on separate lines are two different facts. Both of this
        # week's parser fixes were rediscovering line structure from
        # punctuation because the line structure itself had been discarded
        # before anything could look at it.
        #
        # Kept beside rather than instead: normalize() is deterministic, so the
        # flattened form can always be made again from this one, and nothing
        # downstream has to change to keep working.
        'rawText': raw_text if isinstance(raw_text, str) else str(raw_text or ''),
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
