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
  * legs are identified by their distance, so re-reading the same leg does not
    add it twice. Only a genuinely different leg extends the total.
"""

import time

# How long readings of one offer stay mergeable. Long enough to cover the extra
# samples taken when a card appears, short enough that a card replaced by
# another with an identical payout cannot quietly inherit its legs.
WINDOW = 12.0

# Distances this close are the same leg read twice, not two legs.
SAME_LEG_MILES = 0.15


class OfferAccumulator:
    """Merges parsed readings of one offer. Feed it every read; use what it returns."""

    def __init__(self, window=WINDOW):
        self.window = window
        self.reset()

    def reset(self):
        self.key = None
        self.started = 0.0
        self.legs = {}          # leg key -> {'minutes': [...], 'miles': [...], 'isTotal': bool}
        self.items = None
        self.samples = 0

    def _leg_key(self, leg):
        """What makes two readings the same leg.

        Distance when there is one, since it is the more distinctive of the two
        and rounding it absorbs the small disagreements OCR produces. Time alone
        when there is not.
        """
        if leg.get('miles') is not None:
            return ('mi', round(leg['miles'] / SAME_LEG_MILES))
        return ('min', leg.get('minutes'))

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

        key = round(pay, 2)
        if key != self.key or (now - self.started) > self.window:
            self.reset()
            self.key = key
            self.started = now

        self.samples += 1

        for leg in parsed.get('legDetail') or []:
            if leg.get('minutes') is None:
                continue
            slot = self.legs.setdefault(self._leg_key(leg),
                                        {'minutes': [], 'miles': [], 'isTotal': False})
            slot['minutes'].append(leg['minutes'])
            if leg.get('miles') is not None:
                slot['miles'].append(leg['miles'])
            # One frame calling it a total is enough; the word is rarely
            # hallucinated and missing it is the common failure.
            slot['isTotal'] = slot['isTotal'] or bool(leg.get('isTotal'))

        if parsed.get('items') is not None:
            self.items = parsed['items']

        return self._merged(parsed)

    def _merged(self, parsed):
        legs = list(self.legs.values())
        totals = [l for l in legs if l['isTotal']]
        used = totals or legs

        minutes = None
        miles = None
        for slot in used:
            minutes = (minutes or 0) + _consensus(slot['minutes'])
            if slot['miles']:
                miles = (miles or 0) + _consensus(slot['miles'])

        merged = dict(parsed)
        merged['minutes'] = minutes if minutes else parsed.get('minutes')
        merged['miles'] = miles if miles is not None else parsed.get('miles')
        merged['items'] = self.items if self.items is not None else parsed.get('items')
        merged['legs'] = len(used)
        # A total is the whole journey in one line, so one of them is a complete
        # picture where one ordinary leg is only ever half of one.
        merged['hasTotal'] = bool(totals)
        merged['complete'] = (merged['pay'] is not None and merged['pay'] > 0
                              and merged['minutes'] is not None and merged['minutes'] > 0)
        merged['mergedFrom'] = self.samples
        # True when the window supplied a leg this frame did not see, which is
        # the whole reason for keeping one.
        merged['grew'] = len(used) > len(parsed.get('legDetail') or [])
        return merged


def _consensus(values):
    """The value seen most often, and the smaller one when opinion is split.

    OCR disagreements here are usually a digit dropped rather than added, so
    when two readings are equally popular the shorter time is the safer of the
    two to believe: it makes the offer look worse, not better.
    """
    if not values:
        return 0
    counts = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    best = max(counts.values())
    return min(v for v, c in counts.items() if c == best)
