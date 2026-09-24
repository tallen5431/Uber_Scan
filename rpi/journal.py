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

The web side appends here as well — which offers the driver took, and which ones
to hide — and it does it the same way, by adding a line rather than rewriting
one. Those rows carry a `kind`; an offer never does. That is the whole of the
distinction, and it is what lets two processes write one file without either
needing to know when the other is running.

Three things this deliberately does not do:

  * it does not record what the driver decided. The scanner cannot see the
    Accept button being pressed and must never touch it, so an accept column
    here would be a guess presented as a record.
  * it does not record the OCR text. The useful part is parsed into numbers and
    into `places`; what is left is map furniture. The reader's text stays in the
    log, where it is transient.

    `places` is a deliberate exception to what this paragraph used to say, made
    at the driver's request and worth stating plainly. Without somewhere named,
    an offer read months ago is a row of figures that cannot be matched to any
    job a person remembers — which makes the record hard to check, and checking
    it is the entire point. So the merchant behind a "Pickup" label, and the
    address printed after a leg, are kept: only what the card printed, only
    against an anchor the card also printed, never free text off the map.

    It is a real trade. This is a record of where the driver was and when, it
    lives on a card in a vehicle, and it is copied to a machine at home. Setting
    `"keepPlaces": false` alongside the other settings turns it off and changes
    nothing else.
  * it does not fail. A full card, a read-only filesystem or a missing directory
    costs the journal and nothing else: the scanner exists to read offers, and
    it keeps reading them.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import offer_parser as OP                                     # noqa: E402

# A backstop, not a retention policy. A working shift produces on the order of a
# hundred offers, so a year of driving is a few megabytes and there is nothing
# to be gained by throwing any of it away. This exists so that a bug writing on
# every frame instead of every offer cannot quietly fill the card: past the cap
# the live file is moved aside and a fresh one started. Every roll is kept —
# `.1` is the newest, `.2` the one before it — because the alternative, which
# this did for a while, is that the second roll silently deletes the first.
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
# The bounds themselves now live beside the verdict, in offer_parser, because
# the verdict is the place they matter first: a reading that cannot be true
# should never have been shown as an ACCEPT, and flagging it here only helps
# whoever reads the file afterwards. They are imported rather than repeated so
# the two can never drift into disagreeing about what a real offer looks like.
SANE_PAY = OP.SANE_PAY
SANE_MINUTES = OP.SANE_MINUTES

# How long after a card reached the file a payout-free screen can still be said
# to have followed it.
#
# The one thing the rig cannot see is whether the driver pressed Accept, and
# the evidence for it is on the screen the phone goes to afterwards: a
# navigation screen carrying "Deliver to <name>", a turn instruction and a
# speed limit, and no payout and no Accept button anywhere on it. Nothing on
# file says what one of those reads as through this camera at night, so no
# recogniser can be built and none can be invented from a screenshot. These
# rows are the corpus, and this is the bound on how far from a card one may be
# collected.
#
# Three minutes is generous on purpose and is still a bound. An accept happens
# inside the card's own countdown, so the screen that follows it is seconds
# away, not minutes; the window exists for the other case, a driver who stops
# scanning and comes back an hour later to a phone showing something. Without
# it that screen would be filed against a card from an hour ago, which is a
# pairing the data does not support and the shape this collection is for.
SCREEN_WINDOW_MS = 180 * 1000

# How much of the tail to read at a time when walking backwards for the last
# offer. Big enough that the ordinary case — an offer within a few rows of the
# end — is one read, small enough that a file with a very long run of
# annotations on it is not pulled into memory whole, which is the thing the
# backwards walk exists to avoid.
_TAIL_BLOCK = 64 * 1024

SCHEMA = 1


def _ends_mid_line(fh):
    """True when the file already has bytes and the last one is not a newline.

    Asked of the handle that is about to append, so there is no window between
    the check and the write. Costs one seek and one byte read per row, which is
    once or twice per offer.
    """
    try:
        if fh.tell() == 0:                 # opened 'a', so this is the end
            return False
        with open(fh.name, 'rb') as peek:
            peek.seek(-1, os.SEEK_END)
            return peek.read(1) != b'\n'
    except (OSError, ValueError):
        # Cannot tell — and guessing "yes" would put a blank line before every
        # row on any platform where that fails. The reader skips blank lines,
        # but a file that grows a stray newline per offer is worse than the
        # rare torn tail this is guarding.
        return False


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
        self._said_at = None
        # Lines the last rows() read could not parse. Set by rows(); zero
        # before anything has been read, which is different from "none found"
        # only in that nobody has looked yet.
        self.torn = 0
        # ...and why the last read gave up entirely, if it did. None means the
        # rows handed back are the rows there are; a string means they are not,
        # and nothing may be concluded from their number.
        self.unreadable = None

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
                # Start a fresh line if the last one never finished.
                #
                # A power cut mid-write leaves a partial line with no newline on
                # it — one lost row, which the reader skips and which this file
                # is built to tolerate. Appending straight onto that stub fuses
                # it to the next row and loses that one too, silently and for
                # good: the reader sees one unparseable line and skips it, and
                # the offer that was written after the car came back never
                # existed. One torn row is the cost of a power cut; two is a
                # missing byte.
                if _ends_mid_line(fh):
                    fh.write('\n')
                fh.write(line)
            self.written += 1
            self._error = None
            return True
        except Exception as e:
            self._complain(e)
            return False

    def failing(self):
        """Why this journal is not working right now, or None.

        `_complain` puts the reason in the log, which is the right place for it
        and the wrong one for the only person who can act on it. The driver is
        looking at an 800x480 panel in a moving car and has never opened
        `journalctl`. A read-only SD card is the classic Pi failure, it is
        completely silent, and everything above it goes on working: the rig
        reads the card, prices it, speaks the verdict and paints a green ACCEPT
        while the one artefact that cannot be regenerated takes none of it.

        Cleared by the next append that lands, so this is the state now and not
        a scar. A failed READ leaves it set until an append succeeds, which is
        the right way round — an append happens within a card or two of any
        offer, and saying so a little too long beats swallowing it.

        A journal that has never been written is not failing. A missing file is
        the normal state of a fresh rig and append() creates it; rows(), last()
        and count() all return empty for it without complaining, so nothing
        here fires before there is something to report.
        """
        return self._error

    def rows(self, limit=0):
        """Stored rows, oldest first. Unreadable lines are skipped, not fatal.

        Reads the whole file. At a few megabytes a year that is cheap, it
        happens at startup and on request rather than in the scan loop, and it
        is the only version of this that stays correct when a line is not the
        length it was assumed to be — a power cut mid-append leaves exactly
        that.

        How many were skipped is left in `self.torn`, because skipping them is
        right and saying nothing about them was not. This file cannot be
        regenerated and there is no second copy of a line: a row that will not
        parse is an offer that is simply gone. One is what a power cut costs and
        `append` above says so. A number that grows is a card beginning to fail,
        which is worth knowing while a backup can still save what is left.

        Read as BYTES, and decoded one line at a time. That is not a detail.

        Opened as text, the decode happens for the whole file at once, so a
        single bad byte anywhere in it raises UnicodeDecodeError out of the
        iteration and the handler at the bottom throws away every row already
        parsed — measured on a five-row file with one byte flipped: four lines
        still perfect JSON, and rows() handed back NONE of them, with `torn`
        reporting the file as whole. One failing card sector cost the entire
        journal, and said nothing.

        server.js reads the same file the other way — buffers split on the
        newline byte, each piece decoded on its own — and on that same file it
        keeps the four and counts the one. Two readers of one file disagreeing
        about what is in it is the fault this project keeps finding; this is
        the side that was wrong.

        `self.unreadable` is the other half. A file that cannot be opened at all
        is a different thing from a file with nothing in it, and a caller that
        cannot tell them apart will back up an empty journal and call it a
        success — sync.py did exactly that, stamping the copy as fresh.
        """
        self.torn = 0
        self.unreadable = None
        try:
            if not os.path.exists(self.path):
                return []
            out = []
            with open(self.path, 'rb') as fh:
                for raw in fh:
                    # `replace`, so a bad byte becomes a character that will not
                    # parse rather than an exception that ends the read. The
                    # cost of a corrupt byte is then its own line and no other.
                    line = raw.decode('utf-8', 'replace')
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        row = json.loads(stripped)
                    except ValueError:
                        # The row being written RIGHT NOW is not a torn row. It
                        # has no newline on it yet because the scanner is still
                        # appending, and counting it would report a fault on
                        # every busy shift. It becomes a complete line either
                        # way: append() terminates a stub before writing the
                        # next row, so a real casualty is counted the moment the
                        # car comes back.
                        if line.endswith('\n'):
                            self.torn += 1
                        continue
                    if isinstance(row, dict):
                        out.append(row)
                    elif line.endswith('\n'):
                        # Parsed, and not a row. Same silence, same cost.
                        self.torn += 1
            return out[-limit:] if limit else out
        except Exception as e:
            # The file itself: missing permissions, a disappearing mount, an IO
            # error off the card. Not "there are no offers", and a caller that
            # reads it as that will report a backup of nothing as a success.
            self.unreadable = str(e)
            self._complain(e)
            return []

    def last(self):
        """The final *offer*, or None.

        Not simply the last line. The web side appends annotations here too —
        what the driver accepted, what they hid — and those carry a `kind` while
        an offer does not. Handing one of those back would have the scanner
        resume from an annotation on restart and record the card in front of it
        a second time, which is the one thing resume() exists to prevent.

        Read backwards from the end rather than forwards from the start. The
        old version built every row in the file into memory to look at the last
        one: on a year of driving — 40,000 rows, 68MB — that is 287ms and 68MB
        of Python objects, at every startup, on a Pi, to answer one question
        about the tail. The watchdog restarts the scanner mid-shift, and every
        restart paid it.

        The block reading is where this kind of rewrite goes wrong, so it is
        written for the three cases that break it and `test_journal.py` holds it
        against the old implementation on each. A row may STRADDLE the boundary
        between two reads, so the first fragment of each block is carried
        forward rather than parsed — parse it and half a row is either lost or
        read as a row of its own. A file may have NO TRAILING NEWLINE, so the
        final fragment is a whole row and must not be discarded. And the tail
        may be a long run of ANNOTATIONS, which is the ordinary case after a
        shift of marking offers, so the walk keeps going back through blocks
        until it finds something that is not one.
        """
        try:
            if not os.path.exists(self.path):
                return None
            with open(self.path, 'rb') as fh:
                fh.seek(0, os.SEEK_END)
                pos = fh.tell()
                held = b''
                while pos > 0:
                    step = min(_TAIL_BLOCK, pos)
                    pos -= step
                    fh.seek(pos)
                    held = fh.read(step) + held
                    parts = held.split(b'\n')
                    # Everything but the first piece is a whole line. The first
                    # is only whole once the read has reached the start of the
                    # file; until then it is the far half of a straddling row.
                    #
                    # Belt and braces rather than load-bearing, and worth saying
                    # which: reading backwards, that first piece is a PREFIX of
                    # a line, and no prefix of a JSON object parses as one —
                    # checked over every cut of a real row. What a fragment can
                    # do is parse as something that is not a row at all ("123",
                    # "null"), which is what the isinstance below refuses. Skip
                    # both guards and the walk still answers correctly; skip the
                    # isinstance alone and it can hand back an integer.
                    whole = parts if pos == 0 else parts[1:]
                    for chunk in reversed(whole):
                        chunk = chunk.strip()
                        if not chunk:
                            continue
                        try:
                            row = json.loads(chunk.decode('utf-8', 'replace'))
                        except ValueError:
                            continue
                        if isinstance(row, dict) and not row.get('kind'):
                            return row
                    held = b'' if pos == 0 else parts[0]
            return None
        except Exception as e:
            self._complain(e)
            return None

    def count(self):
        """How many rows the file holds, without building one of them.

        The startup line says how many offers are on record, and it used to ask
        `len(rows())` — which is the same 68MB the walk above exists to avoid,
        paid a second time in the same second. Lines rather than parsed rows,
        because the question is how many were written and a line that will not
        parse was still written.
        """
        try:
            if not os.path.exists(self.path):
                return 0
            n = 0
            # Binary, like rows() — and for the same reason, which this had
            # not been given. A bare open() decodes strictly inside the `for`,
            # so ONE byte that is not valid UTF-8 raises out of the loop, the
            # blanket except below catches it, and this answers 0 for a file
            # holding a year of work. rows() already opens 'rb' and decodes per
            # line with `replace` precisely so a bad byte costs its own line
            # and no other; the same question was being answered two ways in
            # one class, and the two drifted by the whole file.
            #
            # Counting needs no decode at all: the question is how many lines
            # were written, and a line that will not parse was still written.
            #
            # What reached the driver is the part that matters. The except
            # below calls _complain, which sets self._error, which failing()
            # reads and the panel prints as "Offers are NOT being saved" — the
            # one notice this project added so a driver would know the
            # irreplaceable file had died. Over a corrupt byte it fired while
            # every write was succeeding, and a later append did not clear it,
            # because the next count() raised again and set it straight back.
            # Measured on the five-row fixture test_journal.py already ships:
            # rows() 3, count() 0, failing() set before AND after a successful
            # append.
            with open(self.path, 'rb') as fh:
                for raw in fh:
                    if raw.strip():
                        n += 1
            return n
        except Exception as e:
            self._complain(e)
            return 0

    def _roll_if_huge(self):
        """Start a fresh file past the cap, keeping every one that came before.

        `os.replace` overwrites, and this used to move the live file straight
        onto `<journal>.1` every time the cap was passed — so the SECOND roll
        deleted the first archive, with no exception, no complaint, and nothing
        left on disk to say it had happened. Measured on the same mechanism at a
        300-byte cap: 39 rows written, 9 still findable anywhere afterwards.

        That is the file this module's own docstring calls append-only and
        irreplaceable, and it is the failure mode of the very thing the cap
        exists for. The comment on MAX_BYTES says the cap is there so a bug
        writing on every frame instead of every offer cannot quietly fill the
        card; in exactly that case this rolled again and again and shredded
        everything behind it.

        The chain is shifted instead: `.1` becomes `.2`, `.2` becomes `.3`, and
        the live file becomes `.1`. Nothing is destroyed, `.1` stays the newest
        archive — which is what server.js stats to notice a roll — and a card
        that really is filling says so by filling, which is recoverable, rather
        than by quietly deleting a year of driving, which is not.
        """
        if not (self.cap and os.path.exists(self.path)
                and os.path.getsize(self.path) > self.cap):
            return
        # From the top down, so nothing is overwritten on the way.
        highest = 0
        while os.path.exists('%s.%d' % (self.path, highest + 1)):
            highest += 1
        for n in range(highest, 0, -1):
            os.replace('%s.%d' % (self.path, n), '%s.%d' % (self.path, n + 1))
        os.replace(self.path, self.path + '.1')
        if highest:
            # Worth saying out loud, and not through _complain: that one says
            # "could not use the offer journal", which is the opposite of what
            # happened here. The journal was used, kept, and moved aside.
            #
            # One roll is the backstop doing its job. A second means a hundred
            # and twenty-eight megabytes of journal, which on a rig that
            # produces a few megabytes a year is a bug writing on every frame
            # rather than a season of driving.
            print('the offer journal has rolled %d times and every roll has '
                  'been kept (%s.1 through .%d). A few megabytes a year is '
                  'normal, so this many is worth looking at.'
                  % (highest + 1, self.path, highest + 1))

    # How long the same complaint stays quiet before it is said again.
    #
    # Not forever, which is what "say it once" turned into. A path that fails
    # identically on every offer — a read-only card, a directory nobody made —
    # produces exactly one line and then nothing for the rest of the shift, so
    # the evidence that the irreplaceable file is not being written scrolls off
    # a headless box's log within minutes of the failure starting. A thousand
    # repeats is a log nobody reads; one every five minutes is a log that still
    # says what is wrong when somebody finally looks at it.
    REPEAT_AFTER_S = 300.0

    def _complain(self, e):
        """Say it once, then again every few minutes for as long as it lasts."""
        message = str(e)
        now = time.time()
        fresh = message != self._error
        due = (self._said_at is None
               or now - self._said_at >= self.REPEAT_AFTER_S)
        if fresh or due:
            self._error = message
            self._said_at = now
            print('could not use the offer journal (repeated every %d minutes '
                  'while it lasts): %s'
                  % (int(self.REPEAT_AFTER_S / 60), message))


class OfferLog:
    """Decides which readings are worth keeping, and keeps them once.

    Split out from the scan loop because every interesting part of it is an edge
    case — a card read twice, a card that improves, a card still on screen when
    the scanner restarts — and none of those can be tested through a camera.
    """

    def __init__(self, journal, keep_places=True):
        self.journal = journal
        # Whether to store where an offer went. On by default because a record
        # nobody can match to a remembered job is hard to check, and checking it
        # is the point; `"keepPlaces": false` in the settings turns it off.
        self.keep_places = keep_places
        self.episode = None          # the accumulator's episode being recorded
        self.id = None
        self.seq = 0
        self.content = None
        # What the card on screen pays, as last read believably. This is what
        # says "the same card again", and it is kept apart from `content` on
        # purpose: content is every field, and it moves every time the
        # accumulator picks up another leg, which is precisely when the id must
        # not change.
        self.pay = None
        # Every address any reading of the card on screen has produced.
        #
        # Kept here as well as in the accumulator because the two have different
        # lifetimes: the accumulator's window is twelve seconds and a card sits
        # on screen for tens of them, so a window that rolls over while the same
        # card is still up starts again with nothing. The row a driver reads is
        # written from here, and a row must be able to gain an address without
        # ever losing one — the settled upgrade in consider() rebuilds the row
        # from the *current* reading, and 93 of one shift's 121 offers go
        # through that path.
        self.places = []
        # Whether this offer's row has already been superseded with a
        # settled flag. See consider(): once per offer, never per look.
        self.settled_written = False
        self.first_at = None
        self.last_at = None
        self.written = 0
        # The id of the last offer a row of which actually reached the file.
        #
        # `self.id` is assigned the moment consider() decides a reading is a new
        # card, BEFORE the append is attempted, so it says only that this
        # process has a name for the card in memory. The health line was reading
        # it as "this card is on disk": with the journal on a path that cannot
        # be written — an SD card remounted read-only mid-shift is the classic
        # Pi failure — eight cards produced eight ids, zero rows, and a status
        # line reading "8 cards seen, 8 recorded". The one counter this project
        # built to say how much the journal is missing reported zero misses at
        # the moment it was missing everything.
        #
        # A separate field rather than checking `written`, because the question
        # is about THIS card: a shift that recorded fifty offers and then lost
        # the disk still has a non-zero `written`.
        self.landed_id = None
        # The card that is still owed a screen row, as `(id, when it landed)`,
        # or None when none is. See note_screen.
        #
        # ONE field rather than three, and it is the difference between a guard
        # that can fail and a guard that cannot. Written first as a landing
        # stamp beside `landed_id` and a separate "already answered" id, it took
        # three states to say one thing, and two of the guards over them were
        # unreachable: on a fresh log the "already answered" test compared None
        # with None, came out true, and returned the right answer for the wrong
        # reason — so deleting the test that was actually about it changed no
        # behaviour at all, and nothing in the suite could tell. This says the
        # whole question in one place: set when a row reaches the file, cleared
        # when a screen has been written against it, and every path that reads
        # it has to look at the same value.
        self.screen_wanted = None

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
        # Both directions. A Pi has no real-time clock: it boots in 1970 and
        # jumps forward when the network arrives, so a row written before NTP
        # carries a timestamp decades in the future relative to the clock now
        # reading it, and a one-sided window welcomes that with open arms —
        # `now - at` is hugely negative, the test passes, and the scanner adopts
        # the identity of an offer from another era. Refusing to resume is
        # always the safe answer: the cost is one offer recorded twice.
        age = now_ms(now) - at
        if age > RESUME_WINDOW_MS or age < -RESUME_WINDOW_MS:
            return None
        self.id = row.get('id')
        self.seq = row.get('seq') or 0
        self.first_at = row.get('firstAt') or at
        self.last_at = at
        # Normalised, because this came back through JSON and JSON has no
        # tuples: the address list inside the fingerprint returns as a list and
        # would never compare equal to the tuple content_of() builds, so every
        # read after a restart looked novel and wrote a row.
        stored = row.get('content') or ()
        self.content = tuple(tuple(x) if isinstance(x, list) else x
                             for x in stored) or None
        # The addresses that fingerprint was built from, so a resumed card can
        # keep them rather than starting again with none.
        self.places = [p for p in (stored[-1] if stored
                                   and isinstance(stored[-1], list) else [])
                       if isinstance(p, str)]
        # A row the reader itself flagged as impossible is not an identity to
        # come back to; leaving the anchor empty lets the first believable
        # reading after the restart adopt this id rather than start a new one.
        self.pay = None if row.get('suspect') else row.get('pay')
        # The episode is left as None so the next reading of this same card is
        # matched on content, not on a counter that restarted at zero with the
        # process.
        self.episode = None
        return row

    def consider(self, parsed, rate, now=None, ms=None, locked=None,
                 settled=False, whole=True, where=None):
        """Offer one confident reading. Returns the row written, or None.

        The caller decides confidence; this decides novelty.

        `where` is a fix from gps.Phone, or None. Passed straight through to the
        row rather than remembered on the log: the position belongs to the
        moment a row was written, and an offer read over ninety seconds while
        the car moves has no single place it happened. A row that was written
        without a fix stays without one.
        """
        at = now_ms(now)
        episode = parsed.get('episode')

        # A different payout is a different offer, whatever the episode counter
        # says. The counter lives in one accumulator in one process, so it is
        # only ever as trustworthy as the thing feeding it — and treating a new
        # payout as a correction to the last one would file two offers as one,
        # keeping only the second. Cheap to rule out, and it makes this correct
        # against any caller rather than only the one in the scan loop.
        #
        # Except that a reading which cannot be true is not evidence of
        # anything, least of all that the card changed. One real recording has
        # $10.30 read as $1030 with the decimal point lost, and that one
        # misreading did the damage twice over: it declared itself a new offer,
        # and then it became the payout the *next* reading was compared
        # against, so the correct $10.30 that followed looked like a third card.
        # Four rows, one card, and a $1,985/hr entry in the middle of them.
        impossible = OP.doubt(parsed.get('pay'), parsed.get('minutes'),
                              parsed.get('miles')) is not None
        if (not impossible and self.pay is not None
                and parsed.get('pay') != self.pay):
            self.episode = None

        if episode != self.episode:
            # A different card — or the same one after the accumulator's window
            # rolled over, or after a restart. Those two look identical from
            # here and must not become two offers, so a reading of the same card
            # arriving soon enough keeps the id it already had.
            #
            # "The same card" used to mean an identical reading, which is a test
            # OCR defeats by its nature: one real card read four times in
            # seventy seconds gave $10.30/31min/15.1mi, then $1030 with a lost
            # decimal point, then a bad merge at 40min/23.6mi, then the right
            # answer again — four rows, four offers, one card, and a $1,985/hr
            # entry among them.
            #
            # The payout is what identifies an offer. It is the figure the app
            # itself leads with, the one this reader gets right most often, and
            # the one a driver would use to say "that is the same offer". Two
            # genuinely different offers paying the same to the cent inside the
            # window is possible and rare; four rows for one card was neither.
            # Nothing is lost either way — every reading is still written, and
            # the reader picks between them by agreement rather than by
            # arrival order.
            #
            # A reading that cannot be true matches whatever is already there,
            # and an anchor that is still empty matches anything: neither one
            # can say the card changed, and both are better attached to the
            # offer in front of them than filed as an offer of their own.
            #
            # Unless the accumulator says otherwise. Matching on the payout is
            # a guess, and it is wrong exactly when a replacement card pays the
            # same to the cent — at which point this files two offers as one and
            # the second is never written at all, which is the failure this
            # whole file exists to prevent, arriving from the other direction.
            # The accumulator is the only thing in the rig that looks at the
            # legs, so it is the only thing that can tell a replacement card
            # from a re-read; it says so in `newCard` and this believes it.
            seen_at = self.last_at if self.last_at is not None else self.first_at
            same_pay = (impossible or self.pay is None
                        or parsed.get('pay') == self.pay)
            same_card_again = (self.content is not None and same_pay
                               and not parsed.get('newCard')
                               and seen_at is not None
                               and at - seen_at <= RESUME_WINDOW_MS)
            self.episode = episode
            if not same_card_again:
                self.id = '%d-%s' % (at, _cents(parsed.get('pay')))
                self.seq = 0
                self.first_at = at
                self.content = None
                self.pay = None
                # A different card is a different place. Reset with the rest of
                # the identity, or the next offer inherits this one's address.
                self.places = []

        self.last_at = at
        # Before anything decides whether to write. A reading that finally saw
        # the map is not a different reading — `content_of` does not look at
        # the address — so this is the only chance to keep it.
        if self.keep_places:
            for place in parsed.get('places') or []:
                if len(self.places) < OP.MAX_PLACES:
                    # Merged rather than appended, so one address read twice
                    # slightly differently is one address. See OP.same_place.
                    OP.merge_place(self.places, place)
        # Computed here rather than at the top, because it now asks about the
        # addresses and those are only settled once the identity above has had
        # its say — a new card clears them, and a reading of the same card adds
        # to them.
        content = content_of(parsed, self.places)
        if not impossible and parsed.get('pay') is not None:
            self.pay = parsed.get('pay')
        if content == self.content:
            # Nothing new about the reading — but possibly something new about
            # how much to believe it.
            #
            # `settled` means "this reading had stopped moving", and a row is
            # only ever written on the read where the reading *changed*, so at
            # that moment it is false by construction. 208 of 245 rows in one
            # real journal said the reading was still changing, including cards
            # read identically four times running, and the offers page printed
            # that warning on 85% of everything in it. A flag that fires on
            # nearly every row is not a flag, it is a description of the
            # mechanism that wrote it.
            #
            # So the moment the same reading comes back a second time, the row
            # is superseded once with the flag it has now earned. Once: the
            # third and fourth identical reads have nothing further to add, and
            # a journal that grows a row per look is a worse problem than the
            # one being fixed.
            if settled and not self.settled_written:
                self.settled_written = True
                self.seq += 1
                upgrade = row_for(parsed, rate, at, first_at=self.first_at,
                                  offer_id=self.id, seq=self.seq, ms=ms,
                                  locked=locked, settled=True, whole=whole,
                                  keep_places=self.keep_places,
                                  places=list(self.places), where=where)
                if self.journal.append(upgrade):
                    self.written += 1
                    self.screen_wanted = self._owe_screen(at)
                    self.landed_id = self.id
                    return upgrade
            return None

        self.content = content
        self.settled_written = False
        self.seq += 1
        row = row_for(parsed, rate, at, first_at=self.first_at,
                      offer_id=self.id, seq=self.seq, ms=ms, locked=locked,
                      settled=settled, whole=whole,
                      keep_places=self.keep_places, places=list(self.places),
                      where=where)
        if self.journal.append(row):
            self.written += 1
            self.screen_wanted = self._owe_screen(at)
            self.landed_id = self.id
            return row
        return None

    def _owe_screen(self, at):
        """What to put on the screen slate now that a row has reached the file.

        Called from both append paths, BEFORE `landed_id` moves, because
        `landed_id` is still the last card that landed and that is the whole
        test: a row of the SAME card is not a new card.

        This is what makes "one screen row per card" true rather than
        approximately true. Both paths used to arm it outright, and a card does
        not write one row — it writes one per reading that improves on the last,
        plus a settled upgrade. So a card that landed four rows re-opened the
        question three times after its screen had already been answered, and
        the bound this feature rests on was really "one per landed ROW". On a
        navigation screen sitting in front of the camera for a whole delivery
        that is the difference between one row and a handful, in a file that is
        only ever appended to.

        A card already part-way through being answered stays where it is:
        returning the current value leaves the third element alone.
        """
        if self.landed_id == self.id:
            return self.screen_wanted
        return (self.id, at, None)

    def saw_card(self, pay):
        """A payout was read off a frame. Drop the screen slate if it is not
        the armed card's. Returns True if it was dropped.

        The slate is armed by a card REACHING THE FILE, and a card that is seen
        and never recorded arms nothing — which is not a rare case but a
        measured one: `saw` minus `kept` is the figure the offers page turns
        into "3 times the scanner picked a payout off the screen and never
        managed to record it". `consider()` is only called on a reading that is
        ready and locked, so a card that never locks never lands, never arms,
        and never clears.

        Without this the slate is "the last card that LANDED" while the driver
        is looking at a different one. Reproduced end to end: card A lands,
        card B is read once and never locks, the driver accepts B, and the
        navigation screen after it is written `after: <A>` — a pairing that
        names an offer the driver did not take, indistinguishable from a real
        one, in the file that cannot be rewritten. `note_screen`'s own docstring
        refuses the analogous `resume()` case on exactly this principle.

        The payout is what says "a different card", for the same reason it is
        what `consider` identifies an offer by: it is the figure the app leads
        with and the one this reader gets right most often. A reading that
        cannot be true says nothing about anything and is ignored here as it is
        there — both ask `OP.doubt`, which is where that rule lives.

        Dropping rather than re-arming, and the asymmetry is the point. A card
        seen and not recorded has no stamp this process wrote, so there is
        nothing honest to pair a screen with; the cost is a missing row and the
        alternative is a wrong one.
        """
        if self.screen_wanted is None or pay is None:
            return False
        if self.pay is not None and pay == self.pay:
            return False
        if OP.doubt(pay, None, None) is not None:
            return False
        self.screen_wanted = None
        return True

    def note_screen(self, text, places=None, card_was_up=False, now=None):
        """What the phone showed after a card landed. Returns the row, or None.

        Records only. Nothing here writes `accepted`, and nothing reads these
        rows yet — a recogniser built on two screenshots would be a guess about
        the one field every earnings figure on every screen is gated on, and a
        wrong tick is a taken job that never happened in the one file that
        cannot be rewritten. So this collects the evidence and stops, and what
        it collects gets measured against ticks the driver made by hand before
        anything is built on it.

        The caller decides the screen had no payout on it; this decides whether
        it followed a card, and writes it once.

        The raw reading, not the flattened one, for the same reason `row_for`
        keeps `rawText`: flattening throws away which LINE each thing sat on,
        and on these screens the line IS the grammar — "Deliver to Daria I." is
        a line, and the same words scattered through a flattened blob are not
        evidence of anything.

        `places` is what the reader made of the frame, and it is RECORDED rather
        than acted on. The caller's payout test is the app's own grammar for
        "this is a card" and it is the only one that holds: a merchant name is
        NOT, because an Uber navigation screen names the destination the same
        way a card names the shop — the screenshot this was built from reads
        `BCG Atlanta / 1075 Peachtree St NE Ste 3800, Atlanta, GA`. Refusing a
        frame for naming a place would throw away exactly the screens worth
        collecting, and trusting one would be the recogniser this must not
        invent. So the frame is written and what it named is written with it,
        and whoever builds the detector can partition on it with the evidence in
        front of them.
        """
        text = text if isinstance(text, str) else ''
        if not text.strip():
            return None
        # Nothing is owed a screen: either no card this process wrote has
        # reached the file, or the one that did has already been answered.
        #
        # Those two are one question and one field on purpose. A navigation
        # screen sits in front of this camera for a whole delivery and is read
        # every time anything else moves, so "once per card, not once per look"
        # is what keeps one job from appending a few hundred rows of the same
        # screen to a file that is only ever appended to — and a card that never
        # landed has nothing for a screen to have followed, which saying
        # otherwise would invent.
        #
        # `resume()` deliberately leaves this alone, so a scanner that came back
        # mid-card writes nothing about the screen after it until the next card
        # lands. That is a real gap and it is the right one: resume adopts an id
        # off the disk without knowing when this process last agreed with it,
        # and a pairing measured against a stamp nothing here wrote is exactly
        # the evidence this collection must not manufacture.
        if self.screen_wanted is None:
            return None
        after, landed_at, wrote = self.screen_wanted
        # `wrote` is what has already been written against this card: None for
        # nothing, or the `card_was_up` of the row that was. A card is answered
        # ONCE, with one exception — a frame taken while a card was still on
        # screen at the previous read may be replaced, once, by one taken when
        # there was not.
        #
        # That exception is the whole reason this is not a boolean. An offer
        # card that loses its payout to glare for a single frame reads
        # `pay: None` over a card, and a corpus whose row for that card is the
        # card's own text has the positive class filed in the negative slot —
        # the one confusion a recogniser built on these rows could not survive.
        # Refusing such a frame outright was the first answer and it was worse:
        # on a rig whose reads are driven by a motion gate, the frame right
        # after an accept is sometimes the ONLY one, and refusing it loses the
        # screen rather than mislabelling it. So it is written, it is labelled,
        # and the first clean frame inside the window supersedes it.
        #
        # Two rows at most, sharing an id and separated by `seq`, which is the
        # same convention every superseded reading in this file already uses.
        if wrote is False:
            return None
        if wrote is True and card_was_up:
            return None
        at = now_ms(now)
        # Both ends of the window, and the negative end is not symmetry for its
        # own sake.
        #
        # The forward jump this rig is famous for is already covered by the far
        # edge: a Pi boots in 1970 and steps to real time when the network
        # arrives, and a card stamped before that step with a screen read after
        # it comes out DECADES apart — a huge positive age, refused for being
        # outside the window. It is the other direction that needs its own arm.
        # NTP corrects a fast clock by stepping it BACKWARDS, and `time.time()`
        # goes with it, so a screen genuinely read after a card can be stamped
        # before it. A negative age is not a fresh screen and it is not an old
        # one; it is a clock that moved, and saying nothing is the honest answer
        # rather than filing a pairing whose `afterMs` would have to be a lie.
        age = at - landed_at
        if age < 0 or age > SCREEN_WINDOW_MS:
            return None
        row = {
            'v': SCHEMA,
            'kind': 'screen',
            'at': at,
            # Stamped from the clock the way the dropoff sighting rows are, and
            # carrying the same caveat: two in one millisecond would be one key
            # to the sync and one of them dropped. One per card makes that
            # unreachable here.
            # Keyed on the CARD, not on the clock, so that the two rows a
            # card may produce are one row superseded rather than two rows
            # about the same moment. `seq` is what tells them apart, exactly as
            # it does for the readings of an offer, and the sync keys on the
            # pair.
            'id': 'screen-%s' % after,
            'seq': 1 if wrote is None else 2,
            # Which card this followed. The whole value of the row: an offer
            # and the screen that came after it is the pair a recogniser has to
            # be measured on, and either half alone says nothing.
            'after': after,
            # How long after, because "the screen five seconds later" and "the
            # screen two minutes later" are different evidence and a reader
            # months from now can only tell them apart if it is written down.
            'afterMs': int(age),
            'text': text[:TEXT_KEPT],
            # What the reader made of the frame, so the one thing that could
            # make this row a degraded CARD rather than a screen is on the row
            # itself instead of being guessed at afterwards. Capped and
            # normalised the way row_for's own places list is; absent rather
            # than empty, so a frame that named nothing looks different from a
            # build that did not record it.
            'places': [p[:OP.MAX_PLACE] for p in (places or [])
                       if isinstance(p, str) and p][:OP.MAX_PLACES] or None,
            # Whether the rig still believed a card was in front of it at the
            # previous read. The one thing that separates a navigation screen
            # from one glared frame of the card before it, written down rather
            # than decided on — see the supersede rule above.
            'cardWasUp': bool(card_was_up),
        }
        if not self.journal.append(row):
            return None
        self.screen_wanted = (after, landed_at, bool(card_was_up))
        return row


# How much of a reading to keep on the row. A ride card reads to about 80
# characters and a delivery card to fewer; the headroom is for the frames where
# the crop takes in a slice of the map behind the card, which are exactly the
# frames worth studying later.
#
# 220 was that estimate and the estimate was low. The first export to carry this
# column came back with 99 of its 309 cards sitting exactly on the cap — a third
# of the corpus cut off mid-card, and cut off at the END, which is where the
# pickup, the dropoff and the second leg of a ride live. Re-parsing a truncated
# card gives a different answer from the one the rig gave, so the very rows most
# worth studying are the ones this column could not answer for.
#
# The headroom was for map spill and there is more of it than expected: the
# frames that overrun are the ones where the crop took in a slice of the screen
# behind the card, which is exactly the case the text is kept for. 600 clears
# every card in that export with room over. The cost is about 380 bytes on the
# offers that use it — under 80KB across a 200-offer shift, on a file that is
# already appended to once per reading.
TEXT_KEPT = 600


def content_of(parsed, places=None):
    """What makes this reading different from the last one of the same card.

    Not the payout: the accumulator already keys on that, and the whole point of
    a superseding row is that the payout held still while the journey got
    clearer. Distance and item count are in here because both move money —
    distance through running cost, items through the shopping allowance — with
    the minutes untouched. So is the deadline, which on a delivery card *is* the
    duration: a card whose deadline is re-read differently is a different
    reading, and without this it superseded nothing and the correction never
    reached the file.
    """
    return (parsed.get('pay'), parsed.get('minutes'), parsed.get('miles'),
            parsed.get('items'), bool(parsed.get('hasTotal')),
            bool(parsed.get('milesUncertain')), parsed.get('deliverBy'),
            tuple(parsed.get('places') or () if places is None else places))


def row_for(parsed, rate, at, first_at=None, offer_id=None, seq=1, ms=None,
            locked=None, settled=False, whole=True, keep_places=True,
            places=None, where=None):
    """One offer, as it will be stored.

    Numbers only, and each one either read off the card or derived from the
    settings in force at the time. The settings are stored alongside rather than
    assumed, because they change: a row saying only "$10.61/hr, PASS" is
    unreadable a month after the target moved, with no way to tell a verdict
    that was right then from one that would be wrong now.
    """
    pay = parsed.get('pay')
    # The distance the verdict was actually made over, for the same reason the
    # minutes below come from rate(): a delivery card states a distance with no
    # time beside it, so parse() had nothing to check it against and rate() —
    # which knows the clock — is where a lost decimal is recovered. Storing the
    # card's apparent 24 miles beside a rate worked out over 2.4 would be a row
    # that cannot be reconciled with itself. Falls back to the parsed value for
    # a row written before rate() returned one.
    miles = rate.get('miles')
    if miles is None:
        miles = parsed.get('miles')
    # The minutes the verdict was actually made over. On a delivery card that
    # is the time left until the deadline, which parse() cannot work out on its
    # own — so it comes back from rate(), and only falls back to the card's own
    # figure for a row written before that existed.
    minutes = rate.get('cardMinutes')
    if minutes is None:
        minutes = parsed.get('minutes')
    # Taken from the verdict rather than worked out again here, for the same
    # reason `miles` and `minutes` above are: two answers to one question drift,
    # and a row that disagrees with the screen the driver saw cannot be argued
    # with later — which is the whole use of keeping it.
    #
    # They had already drifted. OP.doubt() takes three numbers and can only ask
    # whether those three can be true; rate() also weighs the SHAPE of the
    # reading, and refuses a rate worked out over one leg of a journey the card
    # printed two of. So a card the panel refused at $220.80/hr was written down
    # with `state: 'doubt'` and `doubt: None` — a row saying it was not judged
    # and declining to say why, which is the one thing a record of a refusal is
    # for. The offers page then explained it as a crop that clipped the card,
    # which is a specific claim and a false one: the leg was in the crop and its
    # hour read as an "l".
    #
    # The fallback is for a hand-built rate dict — the keypad, a test, an older
    # row being re-rated — that has no verdict in it to take.
    why = rate.get('doubt') if 'doubt' in rate else OP.doubt(pay, minutes, miles)
    # `places` overrides the reading's own, so a caller that has been watching
    # the card for longer than one reading can hand over everything it saw. The
    # settled upgrade rebuilds the row from the current reading, and an address
    # the current reading happened to miss would otherwise be dropped from a row
    # that already had it. See OfferLog.places.
    places = (places if places is not None else parsed.get('places')) \
        if keep_places else []
    # The reading's own record of which END the card printed each of those
    # names against — used only when the list it describes is the list being
    # stored. See OP.place_ends for what it fixes.
    #
    # The condition is the whole point and it is not caution. `places` above
    # can be the CALLER'S list rather than the reading's: OfferLog watches a
    # card across readings, and after a restart it restores names out of
    # `content` while the reading starts again from none. An ends list read
    # against the wrong entries would put the layout's answer on somebody
    # else's name, which is worse than not having it — the fault being fixed,
    # with a fix's confidence behind it.
    #
    # Element for element, not by length. The two lists are built by the same
    # merge over the same readings, so on the owner's week they are identical
    # on 1,164 of 1,166 offers and the two that differ differ only in which
    # reading of one entry was kept — so the guard costs almost nothing and
    # cannot misfile anything.
    _ends = parsed.get('placeEnds') if places == parsed.get('places') else None
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
        'miles': miles,
        # How much of those two is the drive to the pickup rather than the job.
        #
        # `minutes` and `miles` above are the whole journey the card stated,
        # which is the right thing to judge an offer on and the wrong thing to
        # measure geography with: the approach moves with wherever the car
        # happened to be when the card arrived, so the same two places produce a
        # different total every time. Subtracting it is the only way a row says
        # anything about the distance between two JOBS — which is the question
        # a second order raises and the one the rig refuses to guess at.
        #
        # Null on most delivery cards, which state one "total" and never split
        # it. Null is the honest answer and not a zero: see OP.to_pickup, which
        # refuses three separate ways rather than estimating.
        #
        # Written from today forward and unrecoverable for the rows already on
        # disk. That is the whole reason it is here before anything is built on
        # it: the journal is append-only, and a shift that went by without this
        # is a shift nothing can go back for.
        'toPickupMinutes': _round(parsed.get('toPickupMinutes'), 1),
        'toPickupMiles': _round(parsed.get('toPickupMiles'), 1),
        'items': parsed.get('items'),
        # What the card called itself. None when it never said, which is not
        # the same as "a ride" and must not be folded into one — see the kinds
        # split on the offers page.
        'shop': True if parsed.get('shop') else None,
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
        # From rate() as well, and for the same reason: on a delivery card the
        # correction happens there. `in rate` rather than a truthiness test,
        # because False is the answer for most rows and is not a missing one.
        'milesCorrected': bool(rate['milesCorrected'] if 'milesCorrected' in rate
                               else parsed.get('milesCorrected')),
        'milesUncertain': bool(rate['milesUncertain'] if 'milesUncertain' in rate
                               else parsed.get('milesUncertain')),
        'locked': bool(locked),
        # What the reader actually read, which is the one thing this file never
        # kept and the one thing every fix to the parser has needed.
        #
        # 568 real offers on record and not a single recoverable card: every
        # figure the reader derived is here and the text it derived them from is
        # not, so every question about the parser has had to be answered against
        # rendered replicas. Those replicas are honest about the shapes and say
        # nothing about what a camera does to a real screen at night — the
        # "Avg. wait time at pickup" line that switched the running cost off on a
        # third of one shift was found from three mangled fragments that happened
        # to survive in `places`, and only because the addresses were kept.
        #
        # Truncated, and truncated at the reading rather than the card: a real
        # ride card is about 80 characters and the cap is there for the frames
        # where the reader picks up half the map as well. It roughly doubles a
        # row, which on a year of driving is single-digit megabytes against a
        # 64MB roll — cheap for the only evidence that can settle whether a
        # parser change helps on this driver's own phone.
        # Raw where the reader gave it raw. `text` is the flattened form every
        # parser rule works on, and the flattening throws away which LINE each
        # figure sat on — which is the part of a card's meaning that the last
        # two parser fixes had to rediscover from punctuation because it had
        # been discarded before anything could look at it.
        'text': ((parsed.get('rawText') or parsed.get('text') or '')[:TEXT_KEPT]
                 or None),
        # ...and what every OTHER frame of the same card read.
        #
        # A card is read four to eight times and the frames disagree — that
        # disagreement is the whole reason the accumulator exists. Only the
        # winner used to be written, with no account of what it beat, so the
        # one record of what this camera does to a real screen at night was
        # the one reading that happened to come out on top. See
        # accumulate.SCANS_PER_OFFER for the bound.
        'scans': [t[:TEXT_KEPT] for t in (parsed.get('scans') or [])] or None,
        # Whether the whole journey was in view: a line tagged as the total, or
        # both legs of a two-leg card. A reading without it is a *fragment*, and
        # a fragment always flatters the offer — the first leg of a two-leg card
        # on its own is a shorter, better-paying job than the card describes. So
        # it must never reach a median. It is written anyway, because an offer
        # that simply disappears is a hole nothing can account for later.
        'whole': bool(whole),
        # --- where the car was when the card came up --------------------------
        #
        # Absent unless a GPS was reachable AND its fix was fresh, which is most
        # of the time: `gps.Phone.fix()` returns None for a position older than
        # twenty seconds, and the rig runs without a phone at all by default. A
        # row with no lat is a row that did not know, and that is a different
        # thing from a row at (0, 0).
        #
        # This is what makes the map exact instead of inferential. Handed
        # "Chipotle" a geocoder answers with a Chipotle, and handed a misread
        # street it answers with a real street somewhere — both with the same
        # confidence, neither necessarily in the state the driver was in. One
        # coordinate at the moment the card was read turns that from a guess
        # into a lookup bounded to where the car actually was.
        #
        # Five decimal places is about a metre, which is far finer than anything
        # here asks and still keeps the row small.
        #
        # `gpsAge` is kept because it is the difference between a position and a
        # claim. A fix a second old is where the car was; one nineteen seconds
        # old is a third of a mile of motorway ago, and a reader months later
        # can only tell those apart if the number is written down.
        # Both or neither. Half a coordinate is not half a position, it is no
        # position with a number attached — and a `lat` on its own is exactly
        # the shape a reader would test for before drawing a pin. gps.py cannot
        # produce one, because parse_line refuses a fix missing either half;
        # this is the same rule stated where the row is built, so that a caller
        # handing over a dict from somewhere else cannot write one in.
        'lat': _pair(where, 'lat'),
        'lon': _pair(where, 'lon'),
        'gpsAge': (_round(where.get('ageSeconds'), 1)
                   if _pair(where, 'lat') is not None else None),
        # Whether the merged reading had stopped moving. Recorded rather than
        # required: a card whose OCR never settles is exactly the marginal
        # reading worth studying later, and refusing to write it would leave
        # the hardest offers missing from the data with nothing to say so.
        'settled': bool(settled),
        # A ride, or a receipt someone left on the screen, or a card the camera
        # simply got wrong? parse() has no offer-card token to check, so a fare
        # summary can satisfy it. Flagged, never dropped: a hole in the record
        # is worse than a row with a question against it.
        'suspect': not (_within(pay, SANE_PAY) and _within(minutes, SANE_MINUTES)
                        and why is None),
        # Which figure was impossible, when one was. `suspect` alone says a row
        # is not to be trusted without saying what to go and look at, and the
        # three kinds are not the same problem: a lost decimal point in the pay
        # is a reader bug, an implied 120mph is a misread time, and a receipt on
        # the screen is not an offer at all.
        'doubt': why,
        # ...and for the one kind of doubt that is about a leg rather than a
        # figure, how much of the journey never got timed. Without it the row
        # says "leg" and a reader months later has no way to tell a missing walk
        # to the door from a missing trip — which is the difference between a
        # reading that was nearly right and one that was out by a factor of
        # eight. None on every other row, including every row already on disk.
        #
        # Taken as it comes rather than re-tested against `why` here. rate()
        # already sets this only for the verdict it belongs to, so a second
        # `if why == 'leg'` cannot change any answer — it would be a guard no
        # input can reach, which is a guard no check can fail on. That is also
        # the fault this whole field was added to fix: two places working out
        # the same thing, and only one of them right.
        'untimedMiles': rate.get('untimedMiles'),
        # --- where it went ----------------------------------------------------
        # The one thing this file used to refuse on purpose, and the driver
        # asked for it: without somewhere named, an offer months later is a row
        # of numbers that cannot be matched to a job anybody remembers.
        #
        # Only what the card printed against an anchor it prints too — a
        # merchant behind "Pickup", an address after a leg — never free text off
        # the map. It stays a fair trade to be aware of: this is a record of
        # where the driver was and when, it lives on a card in a vehicle and is
        # copied to a machine at home, and `"keepPlaces": false` in the settings
        # turns it off without touching anything else.
        'places': list(places or []),
        # Which of those is which. `places` is what the card printed and is what
        # the offers page shows; these two say which end is the shop and which
        # is somebody's front door, which is the whole basis on which a second
        # order gets judged against the one already in the car. Derived here
        # rather than carried from the reading so that a row rebuilt from a
        # trimmed `places` list stays consistent with it. See OP.find_dropoff.
        'pickup': OP.find_pickup(places, _ends),
        # The card's TEXT goes with it. Without it the "a place the card
        # labelled Pickup is a pickup" rule cannot run, and on the commonest
        # delivery card - "@ Pickup Crumbl / Customer dropoff", which names no
        # address at all - the row recorded the restaurant as the destination.
        # parse() has always passed the text and got None; this call did not,
        # so the stored row and the live reading disagreed about the same card,
        # and the stored one is what the offers page shows and what a replayed
        # stacking answer would compare.
        'dropoff': OP.find_dropoff(places, parsed.get('text'), _ends),
        # A delivery deadline, as minutes since midnight, and whether the time
        # this offer was judged over came from that rather than from a stated
        # duration. Different claims about the same field, and a record that
        # cannot tell them apart cannot be argued with later.
        'deliverBy': parsed.get('deliverBy'),
        'fromDeadline': bool(rate.get('fromDeadline')),
        'ms': _round(ms, 0),
        'content': list(content_of(parsed, places)),
    }


def _within(value, bounds):
    return isinstance(value, (int, float)) and bounds[0] <= value <= bounds[1]


def _cents(pay):
    return 'x' if pay is None else str(int(round(pay * 100)))


def _round(value, places):
    if not isinstance(value, (int, float)):
        return None
    return round(value, places) if places else int(round(value))


def _pair(where, which):
    """One half of a coordinate, and only when the other half is there too.

    Five decimal places is about a metre — finer than anything here asks, and
    small enough to keep a row a row. Booleans are excluded explicitly because
    `isinstance(True, int)` is True in Python, and a `lat: true` sailing through
    into a pin is the kind of thing that only shows up on a map.
    """
    if not isinstance(where, dict):
        return None
    lat, lon = where.get('lat'), where.get('lon')
    for v in (lat, lon):
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return None
    return _round(lat if which == 'lat' else lon, 5)
