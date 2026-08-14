"""Keep what the scanner read, so a shift can be argued with afterwards.

The verdict on screen answers one question — take this or not — and then it is
gone. The questions that need a season of offers behind them cannot be answered
that way: what a typical offer round here actually pays, whether an hour of
Saturday evening is worth more than an hour of Tuesday lunchtime, whether shop
orders earn their shopping time, and whether the target in the config is the
right line to be drawing at all.

So every offer the scanner is confident about gets a line in a file. One JSON
object per line, appended, never rewritten.

A reading can improve after the scanner is first confident about it — a leg
arriving late, an item count two frames behind — and that is worth keeping
rather than hiding. So a better reading of the same card is appended as a
further row carrying the same `id`. **Anything reading this file takes the last
row of each id.** Nothing is ever edited in place, which is what makes the file
safe to append to from a process that can be killed at any moment.

Three things this deliberately does not do:

  * it does not record what the driver decided. The scanner cannot see the
    Accept button being pressed and must never touch it, so an accept column
    here would be a guess presented as a record.
  * it does not record the OCR text. The useful part is already parsed into
    numbers; what is left is pickup addresses — where the driver was and when —
    which earns nothing towards a $/hour and would sit in a file served over the
    LAN. The reader's text stays in the log, where it is transient.
  * it does not fail. A full card, a read-only filesystem or a missing directory
    costs the journal and nothing else: the scanner exists to read offers, and
    it keeps reading them.
"""

import json
import os
import time

# A backstop, not a retention policy. A working shift produces on the order of a
# hundred offers, so a year of driving is a few megabytes and there is nothing
# to be gained by throwing any of it away. This exists so that a bug writing on
# every frame instead of every offer cannot quietly fill the card: past the cap
# the file is rolled once and a fresh one started.
MAX_BYTES = 64 * 1024 * 1024

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'journal.jsonl')

# How recent the last row has to be for it to still be describing the card in
# front of the camera. The scanner is restarted with a backoff when it dies, and
# a card sits on screen far longer than that — without this, coming back mid
# offer records it a second time under a new id.
RESUME_WINDOW_MS = 90 * 1000

# Bounds for a row that looks like a real ride rather than a fare summary or a
# receipt left on the screen. Deliberately tighter than parse()'s own limits,
# which are set to keep noise out of a spoken verdict, not to keep junk out of a
# year of data. Nothing is dropped for failing these — a missing offer makes a
# driver wonder what else is missing — it is flagged so it can be filtered.
SANE_PAY = (1.0, 300.0)
SANE_MINUTES = (2.0, 240.0)

SCHEMA = 1


def now_ms(now=None):
    """Epoch milliseconds, matching what the web side already timestamps with."""
    return int((time.time() if now is None else now) * 1000)


class Journal:
    """Append-only storage. Never raises into the scan loop."""

    def __init__(self, path=DEFAULT_PATH, cap=MAX_BYTES):
        self.path = path
        self.cap = cap
        self.written = 0
        self._error = None

    def append(self, row):
        """Add one row. Returns True if it reached the disk.

        Opened and closed per row rather than held open: this runs once or twice
        per offer, so a kept handle would sit idle for minutes, and a file that
        is closed is one that survives the process being killed mid-shift with
        nothing buffered. 'a' is O_APPEND, so two scanners briefly overlapping
        during a restart interleave whole lines instead of corrupting each
        other — a row is a few hundred bytes, well inside the size at which a
        single append is atomic.
        """
        line = json.dumps(row, sort_keys=True) + '\n'
        try:
            self._roll_if_huge()
            with open(self.path, 'a') as fh:
                fh.write(line)
            self.written += 1
            self._error = None
            return True
        except Exception as e:
            self._complain(e)
            return False

    def rows(self, limit=0):
        """Stored rows, oldest first. Unreadable lines are skipped, not fatal.

        Reads the whole file. At a few megabytes a year that is cheap, it
        happens at startup and on request rather than in the scan loop, and it
        is the only version of this that stays correct when a line is not the
        length it was assumed to be — a power cut mid-append leaves exactly
        that.
        """
        try:
            if not os.path.exists(self.path):
                return []
            out = []
            with open(self.path) as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue        # a torn line; skip it and carry on
                    if isinstance(row, dict):
                        out.append(row)
            return out[-limit:] if limit else out
        except Exception as e:
            self._complain(e)
            return []

    def last(self):
        """The final row, or None."""
        rows = self.rows()
        return rows[-1] if rows else None

    def _roll_if_huge(self):
        if self.cap and os.path.exists(self.path) \
                and os.path.getsize(self.path) > self.cap:
            os.replace(self.path, self.path + '.1')

    def _complain(self, e):
        """Say it once. A broken path breaks on every offer, and a log that
        repeats itself a thousand times is a log nobody reads."""
        message = str(e)
        if message != self._error:
            self._error = message
            print('could not use the offer journal (further identical errors '
                  'suppressed): %s' % message)


class OfferLog:
    """Decides which readings are worth keeping, and keeps them once.

    Split out from the scan loop because every interesting part of it is an edge
    case — a card read twice, a card that improves, a card still on screen when
    the scanner restarts — and none of those can be tested through a camera.
    """

    def __init__(self, journal):
        self.journal = journal
        self.episode = None          # the accumulator's episode being recorded
        self.id = None
        self.seq = 0
        self.content = None
        self.first_at = None
        self.last_at = None
        self.written = 0

    def resume(self, now=None):
        """Adopt the last row if it is recent enough to be the card on screen.

        The scanner is restarted on any crash, and its dedupe state is in
        memory, so without this it comes back to an offer it already recorded
        and records it again under a fresh id — turning one offer into two in
        every analysis that counts them.

        Returns the row adopted, or None.
        """
        row = self.journal.last()
        if not row:
            return None
        at = row.get('at')
        if not isinstance(at, (int, float)):
            return None
        if now_ms(now) - at > RESUME_WINDOW_MS:
            return None
        self.id = row.get('id')
        self.seq = row.get('seq') or 0
        self.first_at = row.get('firstAt') or at
        self.last_at = at
        self.content = tuple(row.get('content') or ()) or None
        # The episode is left as None so the next reading of this same card is
        # matched on content, not on a counter that restarted at zero with the
        # process.
        self.episode = None
        return row

    def consider(self, parsed, rate, now=None, ms=None, locked=None,
                 settled=False):
        """Offer one confident reading. Returns the row written, or None.

        The caller decides confidence; this decides novelty.
        """
        at = now_ms(now)
        episode = parsed.get('episode')
        content = content_of(parsed)

        # A different payout is a different offer, whatever the episode counter
        # says. The counter lives in one accumulator in one process, so it is
        # only ever as trustworthy as the thing feeding it — and treating a new
        # payout as a correction to the last one would file two offers as one,
        # keeping only the second. Cheap to rule out, and it makes this correct
        # against any caller rather than only the one in the scan loop.
        if self.content is not None and parsed.get('pay') != self.content[0]:
            self.episode = None

        if episode != self.episode:
            # A different card — or the same one after the accumulator's window
            # rolled over, or after a restart. Those two look identical from
            # here and must not become two offers, so an unchanged reading
            # arriving soon enough keeps the id it already had.
            seen_at = self.last_at if self.last_at is not None else self.first_at
            same_card_again = (self.content is not None
                               and content == self.content
                               and seen_at is not None
                               and at - seen_at <= RESUME_WINDOW_MS)
            self.episode = episode
            if not same_card_again:
                self.id = '%d-%s' % (at, _cents(parsed.get('pay')))
                self.seq = 0
                self.first_at = at
                self.content = None

        self.last_at = at
        if content == self.content:
            return None                     # nothing new to say about this card

        self.content = content
        self.seq += 1
        row = row_for(parsed, rate, at, first_at=self.first_at,
                      offer_id=self.id, seq=self.seq, ms=ms, locked=locked,
                      settled=settled)
        if self.journal.append(row):
            self.written += 1
            return row
        return None


def content_of(parsed):
    """What makes this reading different from the last one of the same card.

    Not the payout: the accumulator already keys on that, and the whole point of
    a superseding row is that the payout held still while the journey got
    clearer. Distance and item count are in here because both move money —
    distance through running cost, items through the shopping allowance — with
    the minutes untouched.
    """
    return (parsed.get('pay'), parsed.get('minutes'), parsed.get('miles'),
            parsed.get('items'), bool(parsed.get('hasTotal')),
            bool(parsed.get('milesUncertain')))


def row_for(parsed, rate, at, first_at=None, offer_id=None, seq=1, ms=None,
            locked=None, settled=False):
    """One offer, as it will be stored.

    Numbers only, and each one either read off the card or derived from the
    settings in force at the time. The settings are stored alongside rather than
    assumed, because they change: a row saying only "$10.61/hr, PASS" is
    unreadable a month after the target moved, with no way to tell a verdict
    that was right then from one that would be wrong now.
    """
    pay, minutes = parsed.get('pay'), parsed.get('minutes')
    return {
        # Rows outlive the code that wrote them. One integer buys a reader that
        # can tell a schema change from corruption.
        'v': SCHEMA,
        'id': offer_id,
        'seq': seq,
        'at': at,
        'firstAt': first_at if first_at is not None else at,
        # --- as read off the card -------------------------------------------
        'pay': pay,
        'minutes': minutes,
        'miles': parsed.get('miles'),
        'items': parsed.get('items'),
        # --- what the scanner made of it ------------------------------------
        'perHour': _round(rate.get('perHour'), 2),
        'grossPerHour': _round(rate.get('grossPerHour'), 2),
        'perMile': _round(rate.get('perMile'), 2),
        'cost': _round(rate.get('cost'), 2),
        # What the arithmetic actually divided by, which stops matching the
        # card's own minutes the moment a pad or a shopping allowance is set.
        # Without it nothing can reconstruct the rate from the row.
        'billedMinutes': _round(rate.get('minutes'), 1),
        'state': rate.get('state'),
        # --- the settings that produced that verdict -------------------------
        'target': rate.get('target'),
        'band': rate.get('band'),
        'costPerMile': rate.get('costPerMile'),
        # --- how much to trust the row ---------------------------------------
        'legs': parsed.get('legs'),
        'mergedFrom': parsed.get('mergedFrom'),
        'hasTotal': bool(parsed.get('hasTotal')),
        'milesCorrected': bool(parsed.get('milesCorrected')),
        'milesUncertain': bool(parsed.get('milesUncertain')),
        'locked': bool(locked),
        # Whether the merged reading had stopped moving. Recorded rather than
        # required: a card whose OCR never settles is exactly the marginal
        # reading worth studying later, and refusing to write it would leave
        # the hardest offers missing from the data with nothing to say so.
        'settled': bool(settled),
        # A ride, or a receipt someone left on the screen? parse() has no
        # offer-card token to check, so a fare summary can satisfy it. Flagged,
        # never dropped: a hole in the record is worse than a row with a
        # question against it.
        'suspect': not (_within(pay, SANE_PAY) and _within(minutes, SANE_MINUTES)),
        'ms': _round(ms, 0),
        'content': list(content_of(parsed)),
    }


def _within(value, bounds):
    return isinstance(value, (int, float)) and bounds[0] <= value <= bounds[1]


def _cents(pay):
    return 'x' if pay is None else str(int(round(pay * 100)))


def _round(value, places):
    if not isinstance(value, (int, float)):
        return None
    return round(value, places) if places else int(round(value))
