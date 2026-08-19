"""Build one reading out of several frames of the same offer.

A single frame is not always a complete read. Glare across one line, a moment
of defocus, a hand passing the phone — any of these can cost a leg, and a card
listing a pickup and a trip then reports only the half that survived, which
reads as a shorter, better-paying job than it is.

The offer is on screen for tens of seconds, so there is no reason to depend on
one frame. This keeps the legs seen across a short window and sums their union.

Two things keep that safe:

  * the pay is the key. A different payout is a different offer, and the window
    resets rather than merging one card's distance into another's.
  * a leg is matched to one already seen when *either* its duration or its
    distance agrees, so re-reading the same leg does not add it twice and a
    misread field lands in the slot it belongs to, where it gets outvoted
    instead of becoming a leg of its own.
"""

import time

import offer_parser as OP

# How long readings of one offer stay mergeable. Long enough to cover the extra
# samples taken when a card appears, short enough that a card replaced by
# another with an identical payout cannot quietly inherit its legs.
WINDOW = 12.0

# ...except that it could, because 12 seconds is long enough to work through two
# cards. A fresh card is also separated from the last one by a gap: while a card
# is being worked on the loop resamples every RESAMPLE_EVERY (0.5s), so readings
# of one card arrive in a burst, and a quiet stretch means the burst ended. Two
# seconds is four times the resample cadence — long enough that it cannot fire
# inside a burst, short enough to catch the next card.
QUIET = 2.0

# Distances this close are the same leg read twice, not two legs.
SAME_LEG_MILES = 0.15


class OfferAccumulator:
    """Merges parsed readings of one offer. Feed it every read; use what it returns."""

    def __init__(self, window=WINDOW):
        self.window = window
        # Counts the cards this accumulator has been shown, and survives reset()
        # so it never repeats. It is what lets a caller tell "the same offer,
        # read again and better" from "a different offer" without comparing
        # numbers that legitimately move as the reading improves.
        self.episode = 0
        self.reset()

    def reset(self):
        self.episode += 1
        self.key = None
        self.started = 0.0
        self.last_add = 0.0
        self.legs = []          # [{'minutes': [...], 'miles': [...], 'isTotal': bool, 'seen': n}]
        self.items = []
        self.samples = 0
        self.max_legs = 0
        self.corrected = False

    def _find_slot(self, leg, taken):
        """The slot this reading belongs in, or None if it belongs in no slot yet."""
        for i, slot in enumerate(self.legs):
            if i in taken:
                continue
            if leg['minutes'] in slot['minutes']:
                return i
            if leg.get('miles') is not None and any(
                    abs(m - leg['miles']) <= SAME_LEG_MILES for m in slot['miles']):
                return i
        return None

    def _slot_for(self, leg, taken):
        """Find the slot this reading belongs in, or open a new one.

        A leg matches on *either* field agreeing, not on one chosen field. That
        matters because each field fails differently and neither is reliable
        alone:

          * keying on distance alone files a misread distance as a brand new
            leg. One frame reading "23 min (8.4 mi)" as "(3.4 mi)" turned a
            28-minute offer into a 51-minute one and it stayed that way for the
            rest of the window — 3.4 miles in 23 minutes is a perfectly
            believable 9 mph, so no plausibility check can catch it.
          * keying on duration alone loses the case where the duration is what
            was misread and the distance proves the legs are the same.

        Either field agreeing is evidence; both disagreeing is a different leg.

        `taken` holds the slots this frame has already used, so a card genuinely
        listing two legs of equal duration keeps both — within a single frame
        they are certainly distinct, however alike they read.
        """
        found = self._find_slot(leg, taken)
        if found is not None:
            return found
        self.legs.append({'minutes': [], 'miles': [], 'isTotal': False, 'seen': 0})
        return len(self.legs) - 1

    def _is_a_different_card(self, detail, now):
        """Is this reading a new offer that happens to pay the same to the cent?

        The payout alone cannot tell them apart, and getting it wrong is not a
        near miss: a replacement card whose legs match none of the stored slots
        opens new slots, the trim at `_merged` keeps the best-supported ones —
        always the previous card's, which have been seen more often — and the
        new offer is reported *entirely* with the old one's time and distance.
        A 11-minute $63/hr job was shown as a 28-minute $20/hr one, and because
        the contaminated merge reproduces the old card's signature exactly the
        loop stops resampling and never looks again.

        Nothing is a new card while it still lines up with the one on record.
        That test comes first and outranks everything below it: a reading that
        matches a stored leg *is* that card, however long it took to arrive.

        Only once nothing lines up do two further signals get a say, and between
        them they separate a new card from a new *leg* of the card already being
        read, which is the case the merging exists for and must survive:

          * a quiet stretch. Readings of one card arrive in a burst; a gap means
            the burst ended.
          * whether the frame is looking at a whole journey. A frame that
            finally catches a leg glare had been hiding shows a *fragment* — one
            plain leg — and matches nothing only because that leg is new to us.
            A replacement card shows the whole thing: both legs, or a line
            tagged as the total. So a fragment is never allowed to be a new
            card, however little of it lines up.

        Counting legs against the card on record is not enough for that second
        test. Two frames that each catch a different single leg of the same
        two-leg card leave the record believing the card has one leg, so the
        second frame clears any count-based bar and resets away the first —
        losing exactly the merge this class exists to perform.
        """
        if not self.legs:
            return False
        if not detail:
            return False
        for leg in detail:
            if self._find_slot(leg, set()) is not None:
                return False        # something lines up: the same card.

        # Only now does the gap get a say. It used to be tested first and on its
        # own, which threw the card away whenever a re-read arrived late — and
        # the motion gate fires once per card, so a second look is *often* late.
        # A frame that had lost the pickup leg to glare then became the whole
        # answer: 28 minutes and 9.6 miles collapsed to 23 and 8.4, a $20.51/hr
        # PASS was published as $25.90/hr ACCEPT, and the journal filed it as a
        # second offer. A reading that lines up with the card on record is that
        # card, however long it took to arrive.
        quiet = bool(self.last_add) and (now - self.last_add) > QUIET
        return quiet or len(detail) >= 2 or any(l.get('isTotal') for l in detail)

    def add(self, parsed, now=None):
        """Merge one reading in, and return the combined view of the offer.

        Returns a dict shaped like a parse result, so callers can hand it
        straight to rate() without caring how many frames it came from.
        """
        now = time.time() if now is None else now
        pay = parsed.get('pay')

        # Nothing to key on, or nothing to add: pass it through untouched.
        if pay is None or pay <= 0:
            return dict(parsed, mergedFrom=0)

        detail = [l for l in (parsed.get('legDetail') or []) if l.get('minutes') is not None]

        key = round(pay, 2)
        if (key != self.key or (now - self.started) > self.window
                or self._is_a_different_card(detail, now)):
            self.reset()
            self.key = key
            self.started = now

        self.samples += 1
        self.last_add = now

        # No frame of a real card lists more legs than the card has, so the most
        # any single frame reported is a ceiling on the union. Without it a
        # misread *duration* invents a leg the same way a misread distance used
        # to, and nothing outvotes it because it sits in a slot of its own.
        self.max_legs = max(self.max_legs, len(detail))
        self.corrected = self.corrected or bool(parsed.get('milesCorrected'))

        taken = set()
        for leg in detail:
            index = self._slot_for(leg, taken)
            taken.add(index)
            slot = self.legs[index]
            slot['seen'] += 1
            slot['minutes'].append(leg['minutes'])
            if leg.get('miles') is not None:
                slot['miles'].append(leg['miles'])
            # One frame calling it a total is enough; the word is rarely
            # hallucinated and missing it is the common failure.
            slot['isTotal'] = slot['isTotal'] or bool(leg.get('isTotal'))

        if parsed.get('items') is not None:
            self.items.append(parsed['items'])

        return self._merged(parsed)

    def _merged(self, parsed):
        legs = list(self.legs)
        totals = [l for l in legs if l['isTotal']]
        used = totals or legs
        if self.max_legs and len(used) > self.max_legs:
            # More slots than any frame ever saw legs: at least one is a misread.
            # Keep the best-supported, which is the ones most frames agreed on.
            used = sorted(used, key=lambda l: -l['seen'])[:self.max_legs]

        minutes = None
        miles = None
        for slot in used:
            minutes = (minutes or 0) + _consensus(slot['minutes'])
            if slot['miles']:
                miles = (miles or 0) + _consensus(slot['miles'])

        merged = dict(parsed)
        merged['minutes'] = minutes if minutes else parsed.get('minutes')
        # Rounded, because this is where the sum is actually made on the rig and
        # binary floating point does not agree that 3.5 + 6.1 is 9.6. Twenty of
        # one shift's 234 offers reached the journal as 9.600000000000001 or
        # 17.299999999999997, and from there the CSV export and everything
        # reading it. A card gives one decimal place; so does a sum of them.
        merged['miles'] = (OP.round2(miles) if miles is not None
                           else parsed.get('miles'))

        # The sum is a different distance from any frame's, so it needs judging
        # on its own. `dict(parsed)` carried the *last frame's* verdict on its
        # own distance, and the merge then replaced the distance that verdict
        # was about. One frame losing the leading digit of "23 min" reads 8.4
        # miles in 8 minutes, flags the distance unreadable and is correctly
        # outvoted on the numbers — but the flag it raised stayed on the merged
        # 9.6 miles over 28 minutes, a perfectly ordinary 21 mph. rate() reads
        # that flag to decide whether to charge mileage at all, so the cost
        # silently vanished and a $20.51/hr PASS was shown as a $26.68/hr
        # ACCEPT, with "distance unreadable" printed next to a distance that
        # was never in doubt.
        #
        # Recovery is not re-attempted here, only doubt: the legs were already
        # offered a decimal point individually in parse(), and dividing a *sum*
        # by ten is not a correction any single misread can justify.
        _, _, uncertain = OP.check_distance(merged['minutes'], merged['miles'],
                                            had_decimal=True)
        merged['milesUncertain'] = uncertain
        # Correcting is only ever advisory — it colours a note, it does not move
        # money — so it is remembered across the window rather than taken from
        # whichever frame happened to be last. If any frame needed a decimal put
        # back, the distance is worth a glance.
        merged['milesCorrected'] = self.corrected
        # Voted on, like the minutes and the distance. This took whichever
        # frame happened to be last, so a single misread outvoted every good
        # reading before it purely by arriving after them — and the item count
        # is not decoration, it buys shopping time. At 90s an item, "12 items"
        # misread as "2" on the last frame of a $18.40 shop order took a
        # 56-minute job to 41 minutes and $17.75/hr PASS to $24.25/hr, on two
        # frames out of three that said 12.
        merged['items'] = _consensus(self.items) if self.items else parsed.get('items')
        merged['legs'] = len(used)
        # A total is the whole journey in one line, so one of them is a complete
        # picture where one ordinary leg is only ever half of one.
        merged['hasTotal'] = bool(totals)
        # The parser's own rule, called rather than restated. Restated, it went
        # stale: this copy had no deadline clause, so every delivery card that
        # gives "Deliver by 7:15 PM" instead of a duration parsed as complete
        # and came back out of here incomplete — no verdict, no journal row,
        # nothing on screen, for a whole shape of offer.
        merged['complete'] = OP.is_complete(merged['pay'], merged['minutes'],
                                            merged.get('deliverBy'))
        merged['mergedFrom'] = self.samples
        merged['episode'] = self.episode
        # True when the window supplied a leg this frame did not see, which is
        # the whole reason for keeping one.
        merged['grew'] = len(used) > len(parsed.get('legDetail') or [])
        return merged


def _consensus(values):
    """The value seen most often, and the larger one when opinion is split.

    Two arguments, and they agree. OCR disagreements here are usually a digit
    dropped rather than added, so of two equally popular readings the *larger*
    is the one that was not corrupted — "23 min" misread as "3 min", never the
    reverse. And a tie is a coin toss, so it should land on the side that costs
    nothing to be wrong about: more minutes is a lower $/hr, and more miles is
    more running cost and a lower $/mile, so the larger reading is the one that
    understates the offer.

    This used to take the smaller value, on the stated grounds that a shorter
    time "makes the offer look worse, not better". It does the opposite —
    $/hr is pay over time, so the shorter time is the *flattering* one — and it
    also contradicted the dropped-digit premise it was written under. A single
    frame reading "23 min" as "3 min" tied one-all and won: a $20.51/hr PASS
    was reported as $93.38/hr, the strongest ACCEPT of the shift.
    """
    if not values:
        return 0
    counts = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    best = max(counts.values())
    return max(v for v, c in counts.items() if c == best)
