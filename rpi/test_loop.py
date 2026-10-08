"""The scan loop, driven over the fake camera with a stubbed reader.

    python3 rpi/test_loop.py

test_scan_pi.py drives the real loop over the real reader, which is minutes
of tesseract. This drives the same loop — scan_pi.main(), the accumulator,
the journal, the announcements — with the reader replaced by a function that
answers with whatever text the check needs, so a fault in what the loop
DOES with a reading can be reached in seconds and without a card render
that happens to read the way the check wants.

Each check here failed against the loop before its fix:

- The offer told to the driving screen was frozen at the first locked
  reading, which can be a fragment with no address, while a later frame
  landed the whole card in the journal.
- One misread frame of a recorded card counted as a card seen and never
  recorded, on the health line and the offers page.
- A read that never returned left the rig beating and silent, and the
  supervisor's silence watchdog could not see it.
- The startup line counted journal lines and called them offers.
- A Re-find the scanner refused was answered in the log and nowhere else,
  while the button on the driving screen said it was re-finding.

One warning about the stubbed reader, because it cost an afternoon here: it
answers with whatever text the check asked for WHETHER OR NOT THERE IS A CARD
IN FRONT OF IT. So a read, and an offer announced off it, happen on the first
frame of every run, before anything is in the mount — neither is evidence that
the camera can see a card. A check that needs one there must ask the camera
(`cam_out`), not the loop.
"""

import json
import os
import sys
import tempfile
import threading
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
    import cv2
    import numpy as np
    import testcards as TC
    import pipeline as PL
    import offer_parser as OP
    import handoff as HO
    import scan_pi as SP
except ImportError as e:
    print('%s — skipping the loop checks' % e)
    sys.exit(0)

if not TC.available():
    print('no PIL or no usable font — skipping the loop checks')
    sys.exit(0)

LORES = (640, 480)
CAP = (2328, 1748)


class Request(object):
    def __init__(self, cam):
        self.cam = cam

    def make_buffer(self, name):
        return self.cam.lores.tobytes()

    def make_array(self, name):
        return self.cam.frame.copy()

    def release(self):
        pass


# A sensor's noise, as far as the stall watch can tell: the lowest bit of a
# scattering of pixels, flipped by one of two patterns taken in turn.
#
# A real camera never hands over the same picture twice — every pixel carries
# its own noise — and these are renders, which do: replayed at this fake's own
# pace, a capture every 10ms for 12 seconds, 1,199 of 1,200 consecutive pairs
# of frames were identical, the one exception being the card arriving. The loop now reads a repeated picture as a stalled camera
# (scan_pi.STALL_SAY), so without this every fake here would be a camera that
# stalled the moment its card stopped moving. One level of difference is all
# it takes and nothing else can see it: measured on this suite's card, its
# empty cabin and a black one, the two patterns move the motion gate by 0.50 at
# most, against the 2.0 it calls still.
DITHER = [np.random.RandomState(seed).randint(0, 2, LORES[0] * LORES[1]).astype(np.uint8)
          for seed in (11, 12)]


class FakeCam(object):
    """A card that appears in the mount shortly after the loop starts.

    `fail_after`: from that capture on, raise this exception instead of
    answering — a RuntimeError is a camera that died, SystemExit is the
    supervisor's SIGTERM as _stop_on_sigterm turns it into one.
    `freeze_at`: from this many seconds in, hand over the very same picture
    on every capture — a stalled camera, which is what the dither above
    exists to tell apart from a still one. `noise=False` leaves the dither
    off, for the one picture that repeats on a working camera: a flat one."""

    def __init__(self, offer, empty, appear_at=0.4, fail_after=None, freeze_at=None,
                 noise=True):
        self.offer, self.empty = offer, empty
        self.appear_at = appear_at
        self.started = time.time()
        self.fail_after = fail_after
        self.freeze_at = freeze_at
        self.noise = noise
        self.captures = 0
        self._show()

    def _show(self):
        t = time.time() - self.started
        self.frame = self.offer if t >= self.appear_at else self.empty
        grey = cv2.cvtColor(self.frame, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(grey, LORES, interpolation=cv2.INTER_AREA).ravel()
        if self.noise:
            small = small ^ DITHER[self.captures % 2]
        self.lores = np.concatenate([small,
                                     np.full(LORES[0] * LORES[1] // 2, 128, np.uint8)])

    def frozen(self):
        return (self.freeze_at is not None
                and time.time() - self.started >= self.freeze_at)

    def capture_request(self):
        self.captures += 1
        if self.fail_after is not None and self.captures >= self.fail_after[0]:
            raise self.fail_after[1]
        if not self.frozen():
            self._show()
        time.sleep(0.01)
        return Request(self)

    def set_controls(self, c):
        pass

    def stop(self):
        pass

    def close(self):
        pass


def out_for(text, clipped=False, fitted=None):
    # `clipped` is what the real reader answers when a payout WAS found and was
    # sitting flush against the top of the crop — pipeline.py hands back
    # `parse('')` for it, so the parse is empty over a screen that was a card.
    # Reproduced here rather than described, because the branch that has to tell
    # that apart from a payout-free screen cannot be reached any other way.
    p = OP.parse('' if clipped else text)
    return {'parsed': dict(p), 'rate': OP.rate(p, {'target': 25}), 'locked': False,
            'text': text, 'clipped': clipped, 'dropped': 1 if clipped else 0,
            'recovered': 0,
            'crop': [0, 0, 1, 1], 'card': None, 'fitted': fitted,
            'ms': {'warp': 0, 'prep': 0, 'ocr': 0, 'parse': 0, 'total': 1}}


def run(texts_for_call, extra_argv=(), seconds=12.0, until=None, health_every=None,
        hang_from=None, stuck_after=None, handoff=None, alive_every=None,
        refind_notice_s=None, config_extra=None, appear_at=0.4, cam_out=None,
        clipped_for=None, dropoff_window=None, whole_text=None, fitted=None,
        fitted_for=None, hang_on_loop=True,
        fail_after=None, phone_hold=None, gps_hold=None, phone=None,
        freeze_at=None, stall_say=None, empty=None, noise=True, offer_dim=None):
    """Run main() with the reader answering texts_for_call(n, k) for frame k of
    read call n (1-based). `hang_from`: read calls from this one on never
    return — on the reader's thread only, with `hang_on_loop` False, so a read
    the loop's own thread makes is answered and counted rather than hanging
    the suite. `handoff`: a directory to point the button-press files at, so a
    request written here cannot be eaten by a scanner running on the same
    machine, nor this one eat theirs. `fail_after`: (n, exception) for the
    camera — see FakeCam. `phone`: what gps.Phone hands back, for a --gps run.
    `freeze_at`: the camera stalls this many seconds in — see FakeCam — and
    `stall_say` stands in for scan_pi.STALL_SAY. `empty`: what the mount
    shows with no card in it, TC.blank() unless a check needs it darker.
    `offer_dim`: the card at that share of its brightness — lit, and short of
    the full well that makes the gain look again at once.
    Returns the journal rows, the announcements, the alive beats and what rode
    them, the log lines, how many reads were asked of the reader and how many
    it began, and the exception main() raised, if any."""
    offer = TC.mount(TC.uberx_screen(), 1200)
    quad = PL.detect_screen_quad(offer)
    work = tempfile.mkdtemp()
    config = os.path.join(work, 'config.json')
    journal = os.path.join(work, 'journal.jsonl')
    cfg = {'quad': [[float(x), float(y)] for x, y in quad], 'cardHeight': 900,
           'capture': {'width': CAP[0], 'height': CAP[1]},
           'lensPosition': 10.0, 'exposureTime': 16667,
           'settings': {'target': 25, 'band': 15, 'costPerMile': 0.30}}
    cfg.update(config_extra or {})
    with open(config, 'w') as fh:
        json.dump(cfg, fh)
    if offer_dim is not None:
        offer = (offer.astype(np.float32) * offer_dim).astype(np.uint8)
    cam = FakeCam(offer, TC.blank() if empty is None else empty, appear_at=appear_at,
                  fail_after=fail_after, freeze_at=freeze_at, noise=noise)
    # Handed out so a check can ask what is really in the mount right now. The
    # stubbed reader answers with whatever text the check asked for whether or
    # not there is a card in front of it, so an announced offer is NOT evidence
    # that the camera can see one.
    if cam_out is not None:
        cam_out.append(cam)
    calls = [0]
    # Which reads were of the whole screen box (a ⌖ press) rather than the card
    # crop, in order. `whole_text`, when given, is what those reads see — the
    # map and planner round the card — so a check can tell which crop a
    # reading came from by what it says.
    wholes = []
    # ...and the crop and warp share each read was taken against.
    crops = []

    def look(self, frames, now=None, geom=None):
        calls[0] += 1
        whole = bool(getattr(geom, 'whole', False))
        wholes.append(whole)
        crops.append((list(geom.roi) if geom is not None and geom.roi is not None else None,
                      getattr(geom, 'fixed_card_share', None)))
        if hang_from is not None and calls[0] >= hang_from and (
                hang_on_loop or threading.current_thread() is not threading.main_thread()):
            while True:
                real_sleep(0.05)
        if whole and whole_text is not None:
            return [out_for(whole_text, fitted=fitted_for(calls[0]) if fitted_for else None)
                    for _ in range(len(frames))]
        # `fitted_for(n)`: a crop of its own for each read, so a check can
        # tell which read a kept picture came from.
        return [out_for(texts_for_call(calls[0], k),
                        fitted=fitted_for(calls[0]) if fitted_for else fitted,
                        clipped=bool(clipped_for and clipped_for(calls[0], k)))
                for k in range(len(frames))]

    announced, verdicts, beats, logs, alive, dropoffs = [], [], [], [], [], []
    said_settings = []
    real = (SP.start_camera, SP.emit, SP.emit_offer, SP.emit_alive, SP.log,
            PL.Scanner.look_many, time.sleep, SP.HEALTH_EVERY, SP.READ_STUCK_S,
            SP.emit_reading, SP.emit_dropoff, SP.emit_settings, SP.Reader.submit)
    real_sleep = real[6]
    # Every read handed to the reader, begun or not: one asked of a reader
    # stuck on the read before it never starts, so `calls` cannot count it.
    submitted = [0]

    def submit(self, frames, now, geom):
        submitted[0] += 1
        return real[12](self, frames, now, geom)

    SP.Reader.submit = submit
    # What the loop tells the server it is pricing a mile at, as a copy: the
    # loop hands over its live dict, which is exactly the thing that changes.
    SP.emit_settings = lambda settings: said_settings.append(dict(settings or {}))
    SP.emit_reading = lambda *a, **k: None
    # Captured rather than printed, like the offer line beside it. The empty
    # answer — a press that found no address — is only visible here.
    SP.emit_dropoff = lambda address, **k: dropoffs.append((address, k))
    SP.start_camera = lambda *a, **k: cam
    # Stamped, so a check can ask how soon after something a verdict came.
    SP.emit = lambda *a, **k: verdicts.append((a, k, time.time()))
    SP.emit_offer = lambda *a, **k: announced.append(a)

    def beat(*a, **k):
        beats.append(time.time())
        alive.append(dict(k))

    SP.emit_alive = beat
    SP.log = lambda m: logs.append(m)
    was_handoff = os.environ.get(HO.ENV_DIR)
    if handoff:
        os.environ[HO.ENV_DIR] = handoff
    PL.Scanner.look_many = look
    if health_every is not None:
        SP.HEALTH_EVERY = health_every
    if stuck_after is not None:
        SP.READ_STUCK_S = stuck_after
    was_alive_every = SP.ALIVE_EVERY
    if alive_every is not None:
        SP.ALIVE_EVERY = alive_every
    was_window = SP.DROPOFF_WINDOW
    if dropoff_window is not None:
        SP.DROPOFF_WINDOW = dropoff_window
    was_refind_s = SP.REFIND_NOTICE_S
    if refind_notice_s is not None:
        SP.REFIND_NOTICE_S = refind_notice_s
    was_holds = (SP.PHONE_HOLD, SP.GPS_HOLD, SP.GPS.Phone, SP.STALL_SAY)
    if phone_hold is not None:
        SP.PHONE_HOLD = phone_hold
    if gps_hold is not None:
        SP.GPS_HOLD = gps_hold
    if stall_say is not None:
        SP.STALL_SAY = stall_say
    if phone is not None:
        SP.GPS.Phone = lambda address: phone
    deadline = time.time() + seconds

    def rows():
        out = []
        if os.path.exists(journal):
            for line in open(journal):
                if line.strip():
                    out.append(json.loads(line))
        return out

    def bounded(s):
        if time.time() > deadline or (until is not None and until(rows(), announced, calls[0])):
            raise KeyboardInterrupt
        real_sleep(min(s, 0.01))

    time.sleep = bounded
    sys.argv = ['scan_pi', '--config', config, '--json', '--snapshot', '',
                '--journal', journal] + list(extra_argv)
    raised = None
    try:
        SP.main()
    except KeyboardInterrupt:
        pass
    except RuntimeError as e:
        # A camera that died, from fail_after. main() lets it out, which is
        # what a crash is; the supervisor would restart it.
        raised = e
    finally:
        (SP.start_camera, SP.emit, SP.emit_offer, SP.emit_alive, SP.log,
         PL.Scanner.look_many, time.sleep, SP.HEALTH_EVERY, SP.READ_STUCK_S,
         SP.emit_reading, SP.emit_dropoff, SP.emit_settings, SP.Reader.submit) = real
        SP.DROPOFF_WINDOW = was_window
        SP.ALIVE_EVERY = was_alive_every
        SP.REFIND_NOTICE_S = was_refind_s
        SP.PHONE_HOLD, SP.GPS_HOLD, SP.GPS.Phone, SP.STALL_SAY = was_holds
        if handoff:
            if was_handoff is None:
                os.environ.pop(HO.ENV_DIR, None)
            else:
                os.environ[HO.ENV_DIR] = was_handoff
    return dict(rows=rows(), announced=announced, beats=beats, calls=calls[0],
                submitted=submitted[0],
                logs=logs, alive=alive, dropoffs=dropoffs, verdicts=verdicts,
                settings=said_settings, config=config, wholes=wholes, crops=crops,
                raised=raised)


FRAG = '$16.05 20 min (7.3 mi) trip'
# Both ends named, which is what a ride card really prints. It used to name
# only the destination, and the parser then reported that one address as
# BOTH ends of the journey — the fault find_dropoff was corrected for. A
# fixture that depends on a bug keeps the bug alive.
WHOLE = ('$16.05 3 min (1.1 mi) away Cobb Pkwy NW, Kennesaw '
         '20 min (7.3 mi) trip 123 Main St, Acworth, GA 30101')
# The decimal point lost: a payout that cannot be true, on a card that is
# already on disk. (A plausible near miss — $16.06 for $16.05 — is a card
# the journal itself would file as a different offer, and is still counted.)
LOST_DECIMAL = ('$1605 3 min (1.1 mi) away Cobb Pkwy NW, Kennesaw '
                '20 min (7.3 mi) trip 123 Main St, Acworth, GA 30101')

# --- a fuller reading of the same card is told again ------------------------
# The first read returns a fragment on both frames of the pair, so it locks;
# every read after returns the whole card with an address.
r = run(lambda n, k: FRAG if n <= 1 else WHOLE, seconds=25.0,
        until=lambda rows, ann, calls: any(x.get('whole') for x in rows if not x.get('kind'))
        and calls >= 4)
offers = [x for x in r['rows'] if not x.get('kind')]
ids = sorted(set(x['id'] for x in offers))
ok_('the fragment and the whole card landed under one id (%r)' % ids, len(ids) == 1 and offers)
ok_('...and the whole card is in the journal', any(x.get('whole') for x in offers))
told = [(a[0], a[1].get('minutes'), a[1].get('miles'), a[1].get('dropoff')) for a in r['announced']]
ok_('the driving screen was told the card once as a fragment (%r)' % (told[:1],),
    told and told[0][1] == 20 and told[0][3] is None)
ok_('...and told it again as the whole card, same id',
    len(told) >= 2 and told[-1][0] == told[0][0] and told[-1][1] == 23
    and 'Acworth' in (told[-1][3] or ''))
eq('...and not again for a reading that says nothing new',
   len(told), 2)
ok_('the startup line counts rows, not offers (%r)'
    % [l for l in r['logs'] if l.startswith('journal:')][:1],
    any(l.startswith('journal:') and 'journal row' in l and 'offer' not in l for l in r['logs']))

# --- ...and so is a reading of the same card whose verdict moved -------------
#
# The offer carries its card's verdict, because ⌖ Dropoff asks on it and the
# reading beside it can be a different card. It was only told again when
# minutes, miles or dropoff moved, and an item count read late moves none of
# the three: it adds the shopping allowance to the BILLED minutes. At 90s an
# item and 30c a mile that takes this card from go to PASS, and the headline
# said PASS while the offer on record still said go.
WHOLE_ITEMS = ('$16.05 3 min (1.1 mi) away Cobb Pkwy NW, Kennesaw 20 items '
               '20 min (7.3 mi) trip 123 Main St, Acworth, GA 30101')
r = run(lambda n, k: WHOLE if n <= 1 else WHOLE_ITEMS, seconds=25.0,
        config_extra={'settings': {'target': 25, 'band': 15, 'costPerMile': 0.30,
                                   'secondsPerItem': 90}},
        until=lambda rows, ann, calls: any(x.get('items') for x in rows if not x.get('kind'))
        and calls >= 4)
told = [(a[0], a[1].get('minutes'), a[1].get('miles'), a[1].get('dropoff'),
         a[2].get('state')) for a in r['announced']]
ok_('the card was told first with the verdict it got first (%r)' % (told[:1],),
    told and told[0][4] == 'go')
ok_('...and told again, same id and same journey, when its verdict moved (%r)'
    % (told[-1:],),
    len(told) >= 2 and told[-1][0] == told[0][0]
    and told[-1][1:4] == told[0][1:4] and told[-1][4] == 'no')

# --- one misread frame is not a card the rig failed to record ----------------
r = run(lambda n, k: LOST_DECIMAL if n == 3 else WHOLE, extra_argv=['--no-parallel'],
        seconds=16.0, health_every=3.0,
        until=lambda rows, ann, calls: sum(1 for x in rows if x.get('kind') == 'seen') >= 2
        and calls >= 6)
seen = [x for x in r['rows'] if x.get('kind') == 'seen']
offers = [x for x in r['rows'] if not x.get('kind')]
ok_('the health tally was written', bool(seen))
eq('one card on disk', len(set(x['id'] for x in offers)), 1)
eq('...counted as one card seen (%r)' % [(x['saw'], x['kept']) for x in seen],
   sum(x['saw'] for x in seen), 1)
eq('...and as one recorded', sum(x['kept'] for x in seen), 1)
# ...and each tally carries how the reading went in its window, which until now
# was a health line on the Pi and nothing more. Asked of the real row the real
# loop wrote, because the fault this guards is note_tally dropping what the
# tally carried — `reads` and `failed` were in it all along and never reached
# the file.
_first = seen[0] if seen else {}
eq('a seen row carries the window\'s reads and how they went (%r)'
   % dict((k, _first.get(k)) for k in ('reads', 'complete', 'medianMs', 'corners')),
   [k for k in ('reads', 'failed', 'complete', 'noPay', 'clipped', 'medianMs',
                'tooDim', 'tooBright', 'corners', 'relocks')
    if k not in _first], [])
ok_('...with the reads counted, not a placeholder',
    isinstance(_first.get('reads'), int) and _first.get('reads') >= 1)
eq('...and the corners in the health line\'s own word', _first.get('corners') in
   ('held', 'lost', 'stuck'), True)
# This machine has no thermal zone and no vcgencmd, so both are null — and the
# row has to say why rather than leave a null that reads as never asked.
eq('...and the Pi\'s temperature and throttling, each with its reason when it '
   'cannot be read', [k for k in ('cpuC', 'cpuCWhy', 'throttled', 'throttledWhy')
                      if k not in _first], [])
ok_('...a null always beside a reason (%r)' % ((_first.get('cpuC'), _first.get('cpuCWhy')),),
    (_first.get('cpuC') is not None) != bool(_first.get('cpuCWhy'))
    and (_first.get('throttled') is not None) != bool(_first.get('throttledWhy')))

# --- a glare frame is not a card either --------------------------------------
#
# The case above is a MISREAD payout - "$1605" for "$16.05" - which `same_card`
# recognises by its impossibility. This is the other shape: a read that finds no
# payout at all, which is what glare, a hand across the phone, or a notification
# banner actually produces. It carries no episode, and the seen-gate treated
# that absence as the start of a new card.
#
# Timed to land BEFORE the card is written, which is the whole of the exposure.
# Once a reading has landed, `same_card` matches the payout and hides this; a
# card is read, read again to agree, and only then written, and on a rig whose
# reads take 1.8s and whose verify beat is 2.5s a glare frame inside that
# window is an ordinary event rather than a contrived one.
GLARE = 'Uber  ...  '

r = run(lambda n, k: GLARE if n in (2, 4, 6) else WHOLE, extra_argv=['--no-parallel'],
        seconds=24.0, health_every=3.0,
        until=lambda rows, ann, calls: sum(1 for x in rows if x.get('kind') == 'seen') >= 2
        and calls >= 10)
seen = [x for x in r['rows'] if x.get('kind') == 'seen']
offers = [x for x in r['rows'] if not x.get('kind')]
ok_('the health tally was written for the glare run', bool(seen))
eq('one card on disk through three glare frames',
   len(set(x['id'] for x in offers)), 1)
# Was 4. The offers page turns saw - kept into "3 times the scanner picked a
# payout off the screen and never managed to record it - 75% of the 4 it saw.
# So at least that many offers are missing from everything above" - about one
# card that is in the file.
eq('...counted as one card seen (%r)' % [(x['saw'], x['kept']) for x in seen],
   sum(x['saw'] for x in seen), 1)
eq('...and as one recorded', sum(x['kept'] for x in seen), 1)
eq('...so the page is told nothing went missing',
   sum(x['saw'] for x in seen) - sum(x['kept'] for x in seen), 0)

# The control that keeps the gate honest: a genuinely different card still
# opens a new count. A fix that simply stopped re-arming would pass everything
# above and silently merge every card in a shift into one.
SECOND = ('$9.40 4 min (1.4 mi) away Barrett Pkwy, Kennesaw '
          '15 min (5.2 mi) trip 900 Oak Ln, Marietta, GA 30060')
r2 = run(lambda n, k: WHOLE if n < 4 else SECOND, extra_argv=['--no-parallel'],
         seconds=24.0, health_every=3.0,
         until=lambda rows, ann, calls: sum(1 for x in rows if x.get('kind') == 'seen') >= 2
         and calls >= 10)
seen2 = [x for x in r2['rows'] if x.get('kind') == 'seen']
offers2 = [x for x in r2['rows'] if not x.get('kind')]
eq('two different cards are two cards on disk',
   len(set(x['id'] for x in offers2)), 2)
eq('...and two cards seen', sum(x['saw'] for x in seen2), 2)
eq('...and two recorded', sum(x['kept'] for x in seen2), 2)

# --- a read that never returns stops the heartbeat ---------------------------
# Twelve seconds: a heartbeat every four would leave the last one under four
# seconds old; a rig that went quiet at 1.5s leaves it about twelve.
r = run(lambda n, k: WHOLE, seconds=12.0, hang_from=1, stuck_after=1.5)
beats = r['beats']
ok_('the loop beat while it was waiting (%d beats)' % len(beats), len(beats) >= 1)
last_gap = time.time() - beats[-1] if beats else None
ok_('...and stopped beating once the read was stuck (last beat %.1fs ago)'
    % (last_gap or 0), last_gap is not None and last_gap > 6.0)
ok_('...saying why, once',
    sum(1 for l in r['logs'] if 'stuck' in l) == 1)
# ...and in the journal, where it is the only account the run gets: the SIGKILL
# that answers the silence leaves no stop row, so without this a stuck reader
# reads afterwards exactly as a crash does.
_stuck_rs = [x.get('why') for x in r['rows']
             if x.get('kind') == 'up' and x.get('state') == 'restart']
ok_('...and the journal says the rig asked to be restarted, and why (%r)' % _stuck_rs,
    len(_stuck_rs) == 1 and 'stuck' in (_stuck_rs[0] or ''))

# --- a Re-find the rig cannot honour has to say so on the beat ---------------
# Pressing Re-find is the driver saying the outline is wrong, so from that press
# on the rig is reading through corners they have already judged bad. With
# --no-track there is nothing for the press to move, and the refusal went to the
# log — which is not a place a driver looks. The button on the live page went on
# to say "re-finding" either way, because the only thing it waits for is a web
# handler that touches a file and has never spoken to the scanner.
handoff = tempfile.mkdtemp()
open(os.path.join(handoff, 'uberscan-recalibrate'), 'w').close()
r = run(lambda n, k: WHOLE, extra_argv=['--no-track'], seconds=8.0,
        handoff=handoff, alive_every=0.05,
        until=lambda rows, ann, calls: calls >= 3)
said = [b.get('refind_refused') for b in r['alive']]
carried = [s for s in said if s]
ok_('the refusal reaches the heartbeat (%r)' % (carried[:1],), bool(carried))
ok_('...saying which refusal it was', carried and '--no-track' in carried[0])
ok_('...and the log still has it too, for the day somebody reads one',
    any('tracking is off' in l for l in r['logs']))
ok_('...and the request was taken, not left to fire again on the next restart',
    not any(os.path.exists(p) for p in HO.candidates(HO.RECALIBRATE)))

# ...and a rig nobody has pressed anything on says nothing about re-finding.
# Without this the check above passes on a flag that is simply always set.
r = run(lambda n, k: WHOLE, extra_argv=['--no-track'], seconds=8.0,
        handoff=tempfile.mkdtemp(), alive_every=0.05,
        until=lambda rows, ann, calls: calls >= 3)
ok_('an unpressed button is not a refusal',
    r['alive'] and not any(b.get('refind_refused') for b in r['alive']))

# ...and it goes away on its own, which is the part that only matters because
# of --no-track: there the refusal is permanently true, the button can never do
# anything on that rig, and a notice with no expiry would go up on the first
# press and stay up for the whole shift. A notice that cannot be cleared is one
# the driver stops reading, and it takes the ones that can be with it.
handoff = tempfile.mkdtemp()
open(os.path.join(handoff, 'uberscan-recalibrate'), 'w').close()
# Run on the clock rather than on a read count: the thing being measured is a
# notice ageing out, so the run has to outlive it.
r = run(lambda n, k: WHOLE, extra_argv=['--no-track'], seconds=3.0,
        handoff=handoff, alive_every=0.05, refind_notice_s=0.8)
said = [bool(b.get('refind_refused')) for b in r['alive']]
ok_('the refusal is on the beat to begin with (%d of %d beats)'
    % (sum(said), len(said)), any(said))
ok_('...and off it again once the press is old news', said and not said[-1])
ok_('...having been there for several beats, not one', sum(said) > 1)

# ...and a press that works takes the refusal down at once, rather than leaving
# it to age out. Driven through the hand-drawn box, which is the only path where
# both answers are reachable in one process: a rig with no tracker never gets a
# press that works, and a rig with one never refuses.
#
# The card arrives partway through, so the first press — made against an empty
# mount — is refused for want of a screen, and the second, dropped in once that
# refusal has been seen, finds one.
handoff = tempfile.mkdtemp()
REQ = os.path.join(handoff, 'uberscan-recalibrate')
open(REQ, 'w').close()
pressed_again = [False]
mount = []


def press_again_once_refused(rows, ann, calls):
    """Called from inside the loop, on its own sleep. Not a condition to stop
    on — it returns False every time — but the only hook this harness has for
    doing something to the rig mid-run.

    Waits for the card to really be in the mount, asked of the camera rather
    than inferred from the loop. Neither a read nor an announcement is evidence
    here: the reader is stubbed and answers with a whole card on a blank frame,
    so both happen on the first frame, and a press then is the same press
    against the same empty mount the first one was refused for.
    """
    if (not pressed_again[0] and not os.path.exists(REQ)
            and mount and mount[0].frame is mount[0].offer):
        pressed_again[0] = True
        open(REQ, 'w').close()
    return False


r = run(lambda n, k: WHOLE, seconds=10.0, handoff=handoff, alive_every=0.05,
        appear_at=1.0, cam_out=mount,
        config_extra={'manualBox': True, 'cropBox': [0.0, 0.0, 1.0, 1.0]},
        until=press_again_once_refused)
ok_('the first press, against an empty mount, was refused',
    any('no screen in view' in l for l in r['logs']))
ok_('...and said so on the beat',
    any('box you drew' in (b.get('refind_refused') or '') for b in r['alive']))
ok_('the second press, with the card there, was honoured',
    any('finding the phone automatically' in l for l in r['logs']))
said = [bool(b.get('refind_refused')) for b in r['alive']]
ok_('...and took the refusal down with it, without waiting for it to age out',
    pressed_again[0] and said and not said[-1])

# --- a card box inside the drawn box -------------------------------------------
#
# Offers are read in the card box and the warp is sized to IT, not to the
# screen box round it: sized to the screen, the card would come out at half
# the height the reader wants.
_card = [0.0, 0.4, 1.0, 0.5]
r10 = run(lambda n, k: WHOLE, seconds=3.0,
          config_extra={'manualBox': True, 'cropBox': _card})
eq('a card box saved from before is the crop the rig reads by',
   r10['crops'][0], (_card, 0.5))

# ...and one drawn on the panel mid-shift, arriving through the handoff file.
_ho5 = tempfile.mkdtemp()


def _draw_on_first_read(n, k):
    if n == 1 and k == 0:
        with open(os.path.join(_ho5, 'uberscan-cropbox.json'), 'w') as fh:
            json.dump({'quad': [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]],
                       'card': [0.0, 0.25, 1.0, 0.4]}, fh)
    return WHOLE


r11 = run(_draw_on_first_read, seconds=4.0, handoff=_ho5)
ok_('a card box drawn mid-shift is taken (%r)' % r11['crops'][-1:],
    any(c == ([0.0, 0.25, 1.0, 0.4], 0.4) for c in r11['crops']))
ok_('...and said in the log',
    any('card box' in l for l in r11['logs']))

# --- the reads the rig was unsure of keep their picture ----------------------
#
# 338 of the week's 1,166 offers landed a row the reader doubted, 328 of them
# on recover_decimal's divide-by-ten. Only the picture can say whether the
# guess was right, and those were never kept: --keep-scans is off by default.
DECIMAL_GUESS = WHOLE.replace('(7.3 mi) trip', '(73 mi) trip')
# The reader's crop, which the stub otherwise leaves out: a grey card-sized
# picture is all save_scan needs to have something to write.
_crop = TC.blank()[:400, :300].copy()
# Until a doubtful row has landed, not for a fixed four seconds: under the full
# runner's load four seconds was not always enough for one row, and every
# check below then failed for want of a card rather than for the code.
r12 = run(lambda n, k: DECIMAL_GUESS, seconds=30.0, fitted=_crop,
          until=lambda rows, ann, calls: any(not r.get('kind') and SP.doubted(r)
                                             for r in rows))
_dd = os.path.join(os.path.dirname(r12['config']), 'scans', SP.DOUBT_DIR)
_kept = sorted(os.listdir(_dd)) if os.path.isdir(_dd) else []
_doubted = sorted(set(row['id'] for row in r12['rows']
                      if not row.get('kind') and SP.doubted(row)))
ok_('the card really was read with its miles corrected', _doubted)
ok_('a card the reader corrected the miles on keeps its picture, with no flag asked (%r)'
    % _kept, len(_kept) >= 1)
eq('...one picture per doubtful offer, however many times it was read',
   len(_kept), len(_doubted))
r13 = run(lambda n, k: WHOLE, seconds=30.0, fitted=_crop,
          until=lambda rows, ann, calls: len([r for r in rows if not r.get('kind')]) >= 2)
ok_('the clean card really did land rows', len([r for r in r13['rows'] if not r.get('kind')]) >= 2)
_dd13 = os.path.join(os.path.dirname(r13['config']), 'scans', SP.DOUBT_DIR)
eq('a card read cleanly keeps no picture',
   sorted(os.listdir(_dd13)) if os.path.isdir(_dd13) else [], [])

# ...and the cap is said once, not on every picture after it.
_pd = tempfile.mkdtemp()
for _i in range(3):
    open(os.path.join(_pd, '%013d-x.jpg' % _i), 'w').close()
_said, _was_log = [], SP.log
SP.log = _said.append
try:
    SP.prune_scans(_pd, keep=2)
    open(os.path.join(_pd, '%013d-x.jpg' % 9), 'w').close()
    SP.prune_scans(_pd, keep=2)
finally:
    SP.log = _was_log
eq('pictures pruned at the cap leave the newest', sorted(os.listdir(_pd)),
   ['%013d-x.jpg' % 2, '%013d-x.jpg' % 9])
eq('...and say so once, the first time', len([l for l in _said if 'cap' in l]), 1)

# --- a cost per mile typed on a screen prices the next reading ---------------
#
# POST /api/settings leaves the request in the handoff directory; the loop takes
# it without a restart (a restart is an aim-and-calibrate cycle mid-shift) and
# the very next reading is costed at it. Dropped here once the loop has read a
# couple of times at the config's own 0.30, so the check sees both sides —
# and once the card has sat still long enough for the verify beat to back off,
# so what happens next is the loop's own doing rather than a read that was
# coming anyway. A still card is re-read on that beat, 2.5s backing off to 6s,
# and the panel's "after $0.30/mi costs" would stand under it until then.
#
# The request also names `keepPlaces`, `pad` and `secondsPerItem`, which the
# route refuses — written here by hand, the way a server a `git pull` behind or
# a person at a terminal could. They share the block with the cost, and they
# decide whether addresses reach the append-only journal and how many minutes
# every stored rate is divided by. Only the cost may come through.
_sho = tempfile.mkdtemp()
_sreq = os.path.join(_sho, 'uberscan-settings.json')
_typed_at = [None, None]
_last_read = [0, time.time(), 0.0]     # calls, when, the gap before it


def type_a_cost(rows, ann, calls):
    """Drop the request once the verify beat has backed off — the last gap
    between reads was 3.5s or more, so the next is 6s — and two seconds into
    that wait. Stop two reads after."""
    now = time.time()
    if calls != _last_read[0]:
        _last_read[:] = [calls, now, now - _last_read[1]]
    if (_typed_at[0] is None and calls >= 2 and _last_read[2] >= 3.5
            and now - _last_read[1] > 2.0):
        _typed_at[:] = [calls, time.time()]
        with open(_sreq + '.w', 'w') as fh:
            json.dump({'costPerMile': 0.45, 'keepPlaces': False, 'pad': 9,
                       'secondsPerItem': 60}, fh)
        os.replace(_sreq + '.w', _sreq)
    return _typed_at[0] is not None and calls >= _typed_at[0] + 2


r = run(lambda n, k: WHOLE, extra_argv=['--no-parallel'], seconds=35.0,
        handoff=_sho, until=type_a_cost)
_costs = [(v[0][0].get('costPerMile'), round(v[0][0].get('perHour') or 0, 2))
          for v in r['verdicts'] if v[0] and v[0][0].get('ready')]
_first_new = next((v[2] for v in r['verdicts'] if v[0] and v[0][0].get('ready')
                   and v[0][0].get('costPerMile') == 0.45), None)
_took = (_first_new - _typed_at[1]) if (_first_new and _typed_at[1]) else None
ok_('the card still on the phone is re-read at the new cost at once, not on '
    'the next verify beat (%s)' % ('%.2fs' % _took if _took is not None else 'never'),
    _took is not None and _took < 1.5)
# $16.05 over 23 minutes and 8.4 miles: at $0.30 a mile $35.30/hr, at $0.45
# $32.01/hr. With the refused pad of 9 minutes let through it is $23.01/hr and
# a CLOSE CALL instead of an ACCEPT.
eq('the readings before the request are costed at the config\'s 0.30',
   _costs[:1], [(0.3, 35.3)])
eq('...and the readings after it at the 0.45 typed, in the same process',
   _costs[-1:], [(0.45, 32.01)])
ok_('...with no reading in between at any third figure (%r)' % sorted(set(_costs)),
    set(_costs) <= {(0.3, 35.3), (0.45, 32.01)})
eq('the loop told the server what it priced with, then what it prices with now',
   [x.get('costPerMile') for x in r['settings']], [0.3, 0.45])
_saved = json.load(open(r['config'])).get('settings', {})
eq('the cost is saved, so the next start begins from it',
   _saved.get('costPerMile'), 0.45)
eq('...and nothing else the request named reached the settings block',
   sorted(k for k in ('keepPlaces', 'pad', 'secondsPerItem') if k in _saved), [])
ok_('...and the request was taken, not left for the next start',
    not os.path.exists(_sreq))
ok_('...and the log says what it changed from and to (%r)'
    % [l for l in r['logs'] if 'cost per mile' in l][:1],
    any('$0.45' in l and '$0.30' in l for l in r['logs']))

# --- a journal that will not take writes ------------------------------------
#
# The loop goes on reading, pricing and announcing while nothing is stored, and
# until this existed the only sign was a line in a log on a headless box. The
# sentence and the wire are checked in test_scan_pi.py; what is checked HERE is
# the one link nothing else can reach — that the real main() asks the journal
# and puts the answer on the beat. That link is not theoretical: with the other
# two in place and this one missing, every test still passed and the panel was
# still silent.
_nowhere = os.path.join(tempfile.mkdtemp(), 'gone', 'offers.jsonl')
_dead = run(lambda n, k: WHOLE, extra_argv=('--journal', _nowhere),
            alive_every=0.05, seconds=10.0,
            until=lambda rows, ann, calls: ann and calls >= 4)
_said = [b.get('not_saving') for b in _dead['alive']]
ok_('a journal that will not take writes reaches the beat',
    any(s and 'NOT being saved' in s for s in _said))
ok_('...naming the reason, because on a Pi the errno is the diagnosis',
    any(s and 'No such file or directory' in s for s in _said))
# The whole reason it needs its own channel: nothing else on the wire looks
# wrong. The rig reads the card and announces the offer exactly as it would on
# a healthy card, so a driver watching the panel sees a normal shift.
ok_('...while the rig goes on reading and announcing as if nothing were wrong',
    _dead['announced'])

# An OFFER, not any row: the rig's start row lands before anything is read, so
# "the journal has a row in it" stopped being evidence that an offer was stored.
_fine = run(lambda n, k: WHOLE, alive_every=0.05, seconds=10.0,
            until=lambda rows, ann, calls: any(not x.get('kind') for x in rows)
            and calls >= 4)
eq('a journal that is taking rows says nothing about itself',
   any(b.get('not_saving') for b in _fine['alive']), False)
ok_('...having actually stored something, so that is not a silence of its own',
    [x for x in _fine['rows'] if not x.get('kind')])

# --- the rig says when it starts and when it stops ---------------------------
#
# It never did. A run that crashed, one the watchdog killed and one the driver
# stopped all left the same thing in the journal — nothing — and the counters
# that knew the difference were server.js's, which start again at nought on
# every restart. The rows are written by the real main(), so these drive it;
# what the rows say is UpDown's, and test_scan_pi.py checks that.
def _journal_of(path):
    return ([json.loads(l) for l in open(path) if l.strip()]
            if os.path.exists(path) else [])


def _ups(rows):
    return [(x.get('about'), x.get('state')) for x in rows if x.get('kind') == 'up']


_upj = os.path.join(tempfile.mkdtemp(), 'offers.jsonl')
_clean = run(lambda n, k: WHOLE, extra_argv=('--journal', _upj), seconds=8.0,
             alive_every=0.05, until=lambda rows, ann, calls: calls >= 2)
_crows = _journal_of(_upj)
eq('a run that is stopped writes a start and a stop, and nothing else of its '
   'own (%r)' % _ups(_crows), _ups(_crows), [('rig', 'start'), ('rig', 'stop')])
_cstart = [x for x in _crows if x.get('kind') == 'up'][:1] or [{}]
eq('...the start saying --gps was not given', _cstart[0].get('gps'), False)
ok_('...and how long the machine had been up (%r)' % (_cstart[0].get('uptime'),),
    isinstance(_cstart[0].get('uptime'), int) and _cstart[0]['uptime'] > 0)
ok_('...ahead of every offer the run wrote',
    _crows and _crows[0].get('kind') == 'up')
# The beat, from the same run: the loop has to hand the GPS and the Pi to it.
# Without --gps the word is 'off' — said on the beat, where the page decides to
# say nothing about it, rather than left out.
_cb = [b for b in _clean['alive'] if 'gps' in b]
ok_('the loop puts the GPS on the beat (%d of %d beats)' % (len(_cb), len(_clean['alive'])),
    _cb and len(_cb) == len(_clean['alive']))
eq('...as off, for a rig not asked for a position',
   _cb[-1].get('gps') if _cb else None, {'state': 'off', 'ageSeconds': None})
eq('...and the Pi, with all four of its fields',
   sorted((_clean['alive'][-1].get('pi') or {}).keys()) if _clean['alive'] else [],
   ['cpuC', 'cpuCWhy', 'throttled', 'throttledWhy'])

# A camera that dies mid-run, then the supervisor's restart onto the same
# journal. The first run leaves a start and no stop; that unpaired start IS the
# record of the crash, because the process that crashed cannot write one.
_crashj = os.path.join(tempfile.mkdtemp(), 'offers.jsonl')
_crash = run(lambda n, k: WHOLE, extra_argv=('--journal', _crashj), seconds=8.0,
             fail_after=(40, RuntimeError('the camera stopped answering')))
ok_('the camera really did die mid-run (%r)' % (_crash['raised'],),
    isinstance(_crash['raised'], RuntimeError))
eq('a run that crashed leaves its start and no stop',
   _ups(_journal_of(_crashj)), [('rig', 'start')])
run(lambda n, k: WHOLE, extra_argv=('--journal', _crashj), seconds=8.0,
    until=lambda rows, ann, calls: calls >= 2)
eq('...so after the restart the journal reads start, start, stop: the run '
   'with no stop of its own is the one that crashed',
   _ups(_journal_of(_crashj)), [('rig', 'start'), ('rig', 'start'), ('rig', 'stop')])

# ...and the supervisor's SIGTERM, which _stop_on_sigterm turns into SystemExit,
# is a stop and not a crash. Raised from the camera, where a real signal lands
# most of the time: the loop spends its life waiting on capture_request().
_termj = os.path.join(tempfile.mkdtemp(), 'offers.jsonl')
_term = run(lambda n, k: WHOLE, extra_argv=('--journal', _termj), seconds=8.0,
            fail_after=(40, SystemExit(0)))
eq('a SIGTERM is a clean stop, written as one',
   (_term['raised'], _ups(_journal_of(_termj))), (None, [('rig', 'start'), ('rig', 'stop')]))

# --- the phone out of sight --------------------------------------------------
#
# The mount is empty for the first four seconds, and the tracker calls the
# screen lost. With the hold cut to 0.6s that is a 'gone' row, and the card
# arriving is a 'back' row.
_ph = run(lambda n, k: WHOLE, seconds=20.0, appear_at=4.0, phone_hold=0.6,
          until=lambda rows, ann, calls: ('phone', 'back') in _ups(rows))
_pups = _ups(_ph['rows'])
ok_('a phone the camera cannot find is written as gone, then back when it '
    'is (%r)' % _pups,
    ('phone', 'gone') in _pups and ('phone', 'back') in _pups
    and _pups.index(('phone', 'gone')) < _pups.index(('phone', 'back')))
# ...and with the real hold, the same four seconds are nothing. Without this
# the check above passes on a loop that writes a row on every lost frame — the
# very quiet-window row the gate at worth_recording was written to refuse.
_ph60 = run(lambda n, k: WHOLE, seconds=7.0, appear_at=4.0)
eq('four seconds out of sight is not a row at the real hold',
   [u for u in _ups(_ph60['rows']) if u[0] == 'phone'], [])
ok_('...over a run that did lose the phone for them (%r)'
    % [l for l in _ph60['logs'] if 'screen' in l][:2],
    any('not visible' in l for l in _ph60['logs']))


# --- a camera that hands over one picture for ever ---------------------------
#
# The owner's rig read once in 9.4 days with the heartbeat beating every four
# seconds and the panel saying "scanner reading". Whether the camera's feed had
# stalled or the box was dark is not known, so both are driven here.
#
# The stall first: the camera freezes 1.5s in, on the card, and from then on
# every capture is the same picture byte for byte. The stub reader goes on
# answering the card, which is what the verify beat re-reading a frozen card
# looks like — readings that look fresh, about a card long gone.
_sl = run(lambda n, k: WHOLE, seconds=8.0, freeze_at=1.5, stall_say=1.0,
          alive_every=0.5)
_slups = _ups(_sl['rows'])
ok_('a camera handing over the same picture is written as stalled (%r)' % _slups,
    ('camera', 'stalled') in _slups)
ok_('...and the beat carries it, for the panel',
    any(b.get('blind') == 'stalled' for b in _sl['alive']))
_sl_rs = [x.get('why') for x in _sl['rows']
          if x.get('kind') == 'up' and x.get('state') == 'restart']
ok_('...then the journal says the rig asked to be restarted, and why (%r)' % _sl_rs,
    len(_sl_rs) == 1 and 'stalled' in (_sl_rs[0] or ''))
# A stalled camera is not cured by waiting — the owner's ran 9.4 days that way,
# and a restart cured it at once — so it takes the stuck reader's way out: no
# more beats, and the supervisor's silence watchdog restarts it, counting it
# where a wedge is counted. At a half-second beat a loop still beating has its
# last beat under a second old.
_sl_gap = time.time() - _sl['beats'][-1] if _sl['beats'] else None
ok_('...and it goes quiet, the way a stuck read does, so the supervisor restarts '
    'it (last beat %.1fs ago)' % (_sl_gap or 0), _sl_gap is not None and _sl_gap > 3.0)
eq('...the last beat it sent being the one that told the panel why',
   _sl['alive'][-1].get('blind') if _sl['alive'] else None, 'stalled')
eq('...said once in the log', sum(1 for l in _sl['logs']
                                  if 'going quiet' in l and 'stalled' in l), 1)
# ...and nothing more is read off the frozen picture once the stall is said.
# Frozen on a card, the verify beat re-read it every few seconds, each verdict
# as fresh-looking as a real one — and server.js counts a reading as the loop
# speaking, so the silence its watchdog restarts on never came.
_sl_told = [t for t, b in zip(_sl['beats'], _sl['alive']) if b.get('blind') == 'stalled'][:1]
_sl_after = [round(t - _sl_told[0], 1) for a, k, t in _sl['verdicts']
             if _sl_told and t > _sl_told[0] + 0.5]
eq('...and no reading of the frozen card comes after it, to keep the loop '
   'sounding alive', (bool(_sl_told), _sl_after), (True, []))

# ...and a still card is not a stall. A sensor's noise differs from frame to
# frame however still the picture, which is what the fakes' dither stands for,
# and this card sits still for 8.6s at the real STALL_SAY.
_still = run(lambda n, k: WHOLE, seconds=9.0, alive_every=0.5)
eq('a card sitting still past the stall\'s hold is not a stall',
   [u for u in _ups(_still['rows']) if u[0] == 'camera'], [])
eq('...and no beat says it cannot see',
   [b.get('blind') for b in _still['alive'] if b.get('blind')], [])
ok_('...on a run long enough to have said so (%d beats)' % len(_still['beats']),
    _still['beats'] and _still['beats'][-1] - _still['beats'][0] > SP.STALL_SAY)

# ...nor is a picture that is one flat value all over, repeated. Two of those
# match whatever the camera is doing — a box of black, a sensor at full well —
# so a repeat of one is no evidence. Noise off, and nothing but the empty
# cabin, which is uniform.
_flat = run(lambda n, k: '', seconds=5.0, appear_at=1e9, noise=False,
            stall_say=1.0, alive_every=0.5)
eq('a flat picture repeated is not a stall',
   [u for u in _ups(_flat['rows']) if u[0] == 'camera'], [])

# --- a box with nothing lit in it ---------------------------------------------
#
# The other half: the owner's screen read 1-2 of 205 in the reads either side of
# the blind week. The box drawn by hand — --no-track here, the other rig with
# nothing tracking the corners — holds the dark cabin until the card arrives
# four seconds in. Reads answer nothing until there is a card in the mount, so
# the rig is not reading a card it cannot see. A long beat, so the beats that
# come are the ones a change sends.
_dkcam = []
_DARK = np.full((CAP[1], CAP[0], 3), 1, np.uint8)


def _dk_text(n, k):
    return WHOLE if _dkcam and _dkcam[0].frame is _dkcam[0].offer else ''


_dk = run(_dk_text, extra_argv=['--no-track'], seconds=14.0, appear_at=4.0,
          empty=_DARK, phone_hold=1.0, alive_every=30.0, cam_out=_dkcam,
          until=lambda rows, ann, calls: ('camera', 'seeing') in _ups(rows) and ann)
_dkups = _ups(_dk['rows'])
ok_('a box with nothing lit in it is written as dark, with nothing tracking (%r)'
    % _dkups, ('camera', 'dark') in _dkups)
_dkrow = [x for x in _dk['rows'] if x.get('about') == 'camera'
          and x.get('state') == 'dark'][:1] or [{}]
ok_('...with what the box read, under what a lit screen reads (%r)'
    % (_dkrow[0].get('bright'),),
    isinstance(_dkrow[0].get('bright'), (int, float))
    and _dkrow[0]['bright'] < SP.EX.LIT_ENOUGH)
_dkbeats = [(t, b) for t, b in zip(_dk['beats'], _dk['alive'])]
ok_('...the beat carries it, at once rather than on the next beat',
    any(b.get('blind') == 'dark' for _, b in _dkbeats))
eq('...and never as too dim, which is a lit screen out of light',
   [b.get('tooDim') for _, b in _dkbeats if b.get('blind') == 'dark' and b.get('tooDim')],
   [])
ok_('...and the card arriving is seeing again (%r)' % _dkups,
    ('camera', 'seeing') in _dkups
    and _dkups.index(('camera', 'dark')) < _dkups.index(('camera', 'seeing')))
# The page puts the blind word where the verdict goes, so a card arriving as
# the phone goes back in has to be cleared for at once — not on the next beat,
# which this run has set thirty seconds away, and not on the gain's next look
# at the box, up to six seconds on.
_dk_card = [t for a, k, t in _dk['verdicts'] if a and a[0].get('ready')]
_dk_dark_at = [t for t, b in _dkbeats if b.get('blind') == 'dark'][:1]
_dk_clear = [t for t, b in _dkbeats
             if _dk_dark_at and t > _dk_dark_at[0] and b.get('blind') is None][:1]
ok_('...cleared on the beat within a second of the card\'s first reading '
    '(%r after it)' % ((round(_dk_clear[0] - _dk_card[0], 2),)
                       if _dk_card and _dk_clear else None,),
    _dk_card and _dk_clear and abs(_dk_clear[0] - _dk_card[0]) < 1.0)


def _cleared_after_card(r):
    """Seconds from the card's first reading to the beat that cleared the
    dark, or None."""
    beats = list(zip(r['beats'], r['alive']))
    card = [t for a, k, t in r['verdicts'] if a and a[0].get('ready')]
    dark = [t for t, b in beats if b.get('blind') == 'dark'][:1]
    clear = [t for t, b in beats if dark and t > dark[0] and b.get('blind') is None][:1]
    return round(clear[0] - card[0], 2) if card and clear else None


# ...and the same with the read on the loop's own thread, where it has been
# done and collected before the camera's word is next asked — so "a read is in
# flight" is never true at the moment it is asked, and only the read having
# been handed over says the box moved. A card at half its brightness: one at
# full well makes the gain look again within a second whatever the reader
# did, and this is about the reader.
_dkcam[:] = []
_dkn = run(_dk_text, extra_argv=['--no-track', '--no-thread'], seconds=14.0,
           appear_at=4.0, empty=_DARK, phone_hold=1.0, alive_every=30.0,
           cam_out=_dkcam, offer_dim=0.5,
           until=lambda rows, ann, calls: ('camera', 'seeing') in _ups(rows) and ann)
_dkn_gap = _cleared_after_card(_dkn)
ok_('...and cleared as quickly with --no-thread (%r after it)' % (_dkn_gap,),
    _dkn_gap is not None and abs(_dkn_gap) < 1.0)

# ...and where the tracker runs, the same dark box is its answer — the phone
# gone — and not a second row about the same absence. Long enough for the
# gain's second look, the first that can see the tracker has lost the phone.
_dkt = run(lambda n, k: '', seconds=9.0, appear_at=1e9, empty=_DARK, phone_hold=1.0)
_dktups = _ups(_dkt['rows'])
ok_('a tracked rig answers a dark box with the phone gone (%r)' % _dktups,
    ('phone', 'gone') in _dktups)
eq('...and writes nothing about the camera for it',
   [u for u in _dktups if u[0] == 'camera'], [])


# --- the GPS, through the real loop ------------------------------------------
#
# A phone whose GPS app answers, hands over positions, and then stops — the
# app's timer running out, which is the ordinary way a shift loses its fix.
# Timed from the first time the loop asks rather than from start(): start()
# runs before the camera opens, and a clock started there would have the phone
# answering before the loop ever looked.
class _StubPhone(object):
    host, port = 'phone', 2947

    def __init__(self):
        self.t0 = None

    def start(self):
        return self

    def stop(self):
        pass

    def fix(self):
        return None

    def state(self):
        if self.t0 is None:
            self.t0 = time.time()
        t = time.time() - self.t0
        # Under the 0.5s hold the run uses, so 'looking' can never last long
        # enough to be written as lost before the first fix arrives.
        if t < 0.4:
            return {'state': 'looking', 'ageSeconds': None,
                    'error': 'ConnectionRefusedError: [Errno 111] Connection refused'}
        if t < 2.0:
            return {'state': 'fixed', 'ageSeconds': 0.4, 'error': None}
        return {'state': 'stale', 'ageSeconds': round(t - 1.6, 1),
                'error': 'OSError: the phone closed the connection'}


def _and_then(seen, extra=0.5):
    """Stop `extra` seconds after `seen(rows)` first holds, not at once: the
    row is written mid-pass and the beat that carries the same word comes on
    a later one, so a run halted at the row never sees the beat."""
    first = []

    def until(rows, ann, calls):
        if not first and seen(rows):
            first.append(time.time())
        return bool(first) and time.time() - first[0] > extra
    return until


_g = run(lambda n, k: WHOLE, extra_argv=('--gps', 'phone'), seconds=15.0,
         alive_every=0.05, gps_hold=0.5, phone=_StubPhone(),
         until=_and_then(lambda rows: ('gps', 'stale') in _ups(rows)))
_gups = [x for x in _g['rows'] if x.get('kind') == 'up']
eq('a rig asked for a position says so on its start row',
   ([x.get('gps') for x in _gups if x.get('state') == 'start'] or [None])[0], True)
eq('the GPS coming up and then going stale are two rows, in that order (%r)'
   % _ups(_g['rows']),
   [u for u in _ups(_g['rows']) if u[0] == 'gps'], [('gps', 'ok'), ('gps', 'stale')])
_gst = [x for x in _gups if x.get('about') == 'gps' and x.get('state') == 'stale'][:1] or [{}]
ok_('...the stale one saying how old the fix was and why (%r)'
    % ((_gst[0].get('ageSeconds'), _gst[0].get('why')),),
    isinstance(_gst[0].get('ageSeconds'), float) and _gst[0]['ageSeconds'] > 0.4
    and 'closed the connection' in (_gst[0].get('why') or ''))
_gwords = [b['gps']['state'] for b in _g['alive'] if b.get('gps')]
_gseq = [w for i, w in enumerate(_gwords) if i == 0 or w != _gwords[i - 1]]
eq('the beat said nothing until the first fix, then ok, then stale (%r)' % (_gseq,),
   _gseq, [None, 'ok', 'stale'])
ok_('...and, stale, how old the fix is, which is what the panel prints',
    any(b['gps']['state'] == 'stale' and (b['gps']['ageSeconds'] or 0) > 0.4
        for b in _g['alive'] if b.get('gps')))

# --gps given and unusable: the rig was asked for a position and will never
# get one. It must not read as a rig nobody asked — that is the panel keeping
# quiet about the very thing the flag was typed for.
_gr = run(lambda n, k: WHOLE, extra_argv=('--gps', 'phone:notaport'), seconds=10.0,
          alive_every=0.05, gps_hold=0.3,
          until=_and_then(lambda rows: ('gps', 'lost') in _ups(rows)))
_grl = [x for x in _gr['rows'] if x.get('kind') == 'up' and x.get('about') == 'gps']
eq('a --gps that cannot be used is written as lost (%r)' % _ups(_gr['rows']),
   [x.get('state') for x in _grl], ['lost'])
ok_('...with the reason it could not be used (%r)' % ((_grl or [{}])[0].get('why'),),
    'could not use --gps' in ((_grl or [{}])[0].get('why') or ''))
ok_('...and the beat says lost, not off',
    any((b.get('gps') or {}).get('state') == 'lost' for b in _gr['alive'])
    and not any((b.get('gps') or {}).get('state') == 'off' for b in _gr['alive']))

# --- the Health object's own account of a Re-find ---------------------------
# Reachable directly, and worth reaching: the loop above can only ever show one
# of the two answers per run, because a rig with no tracker never gets a press
# that works and a rig with one never refuses.
h = SP.Health()
eq('a rig nobody has pressed anything on has nothing to say', h.refind_notice(1000.0), None)
h.refind_says('no screen to find', 1000.0)
eq('...a refusal is said', h.refind_notice(1000.0), 'no screen to find')
eq('...and goes on being said while the press is recent',
   h.refind_notice(1000.0 + SP.REFIND_NOTICE_S - 1.0), 'no screen to find')
eq('...and stops once it is not', h.refind_notice(1000.0 + SP.REFIND_NOTICE_S + 1.0), None)
h.refind_says('no screen to find', 1000.0)
h.refind_says(None, 1002.0)
eq('a press that worked leaves nothing behind', h.refind_notice(1002.0), None)

# --- which frame of one read gets published ----------------------------------
#
# A read hands back two frames 33ms apart, and the loop published the later one
# whatever it said. accumulate.add short-circuits on a payout-free frame — it
# hands the parse straight back with mergedFrom 0, which digest()'s destination
# branch relies on — so when the partner frame was the one that lost its payout
# to glare or to the crop edge, the merge was bypassed for the whole read.
#
# Measured on the real accumulator: '$16.05 3 min (1.1 mi) away 20 min (7.3 mi)
# trip' merges to complete=True, 23.0 min, 8.4 mi; the same text with the payout
# gone publishes complete=False, mergedFrom=0 and a rate that is not ready. The
# panel paints grey WAITING over a verdict the rig had 33 milliseconds earlier.
_paid = {'parsed': {'pay': 16.05}}
_glared = {'parsed': {'pay': None}}
eq('the frame that read the money is the one published',
   SP.read_the_money([_paid, _glared]), 0)
eq('...and it is the LAST such frame, not the first',
   SP.read_the_money([{'parsed': {'pay': 9.0}}, _glared, {'parsed': {'pay': 11.0}}]), 2)
eq('...still the later frame when that is the one with the money',
   SP.read_the_money([_glared, _paid]), 1)
# A screen with no payout on it at all is not a damaged offer card, it is a
# navigation app or a dropoff address, and it still has to digest as itself.
eq('a read with no payout anywhere publishes the last frame, as before',
   SP.read_the_money([_glared, {'parsed': {}}]), 1)
eq('...and a single-frame read is unaffected', SP.read_the_money([_glared]), 0)
# A zero payout is not a payout, and `True` is not 1.0 however much Python
# would like it to be.
eq('a zero payout does not count as having read the money',
   SP.read_the_money([{'parsed': {'pay': 0}}, _glared]), 1)
eq('...nor does a boolean that happens to be truthy',
   SP.read_the_money([{'parsed': {'pay': True}}, _glared]), 1)

# ...and the wiring, asserted on the source and said plainly rather than
# dressed up as a runtime test. collect() is a closure inside the scan loop:
# reaching it means running the loop, which means a camera. What CAN be checked
# without one is that it asks the question above instead of taking the last
# frame regardless, and that it does not hand the chosen frame to the
# accumulator twice — digest() adds that one itself, and a card merged with a
# copy of itself is a different reading.
_loop_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              'scan_pi.py')).read()
ok_('the loop publishes the frame that read the money',
    'chosen = read_the_money(batch)' in _loop_src)
ok_('...and feeds every frame but that one to the accumulator',
    'if i != chosen:' in _loop_src)

# ...and the same for the half of the screen-row wiring a run cannot reach.
#
# Everything else about these rows is driven through main() above. The one
# thing that is not is a screen row carrying `cardWasUp: false`, because that
# needs a SECOND payout-free read, and reads are driven by the motion gate: the
# stubbed camera holds one picture, so once the card stops reading as a card the
# verify beat stops and nothing looks again. A real navigation screen moves for
# a whole delivery and has no such problem.
#
# Two fixtures were built to close that and neither survives the real screen
# detector — a light one blows the exposure out ("the card was blown out with
# the gain already at its floor", four times, no read) and a dark one is not
# seen at all ("screen not visible"). Both were deleted rather than left in
# passing for the wrong reason. `note_screen`'s own suite covers what the row
# says; what is left to check here is that the loop hands it the right answer
# rather than a constant, which is exactly the shape the check above is for.
ok_('the loop tells a screen row whether a card was up a moment ago',
    'card_was_up=card_on_screen' in _loop_src)

# ...and the other half of the dropoff answer that a run cannot reach: it waits
# for any read that STARTED inside the window, because such a read can still
# answer the press. These checks run --no-parallel, where a read is synchronous
# and `reader.busy` is never true at the moment the window is judged; the
# threaded path is the one it is for, and on the rig a read started at 11.9s of
# a twelve-second window lands a second or more after it. The predicate is the
# same one `asked` itself uses, which is the property worth pinning.
ok_('the empty dropoff answer waits for a read that could still answer it',
    'reader.since < dropoff_until' in _loop_src)

# --- a dropoff scan that finds nothing says so -------------------------------
#
# The rig emitted only from inside `if found:`, so a press that found no
# address produced no line at all and the panel's own timer repainted the
# button exactly as it was. The driver tapped the address open on their phone,
# pressed, waited, and got the same grey button whether it had worked or not.
# Every other control on that bar names its failure: "Took … · not saved",
# "Drop · failed", "⟳ failed", "could not set the box: …".
#
# Answered from HERE and not from a timer on the page. `asked` is
# `started < dropoff_until`, so a read that began before the deadline still
# counts and still emits when it lands — 1.8s median on this Pi and 5.9s at
# worst measured. A page giving up on its own clock would print "not read" and
# then be corrected by a green address a moment later, which is this project's
# first fault class used to cure its second.
#
# Run to the deadline rather than to a read count: the answer comes when the
# WINDOW closes, and a run that stops at four reads stops before it does.
#
# Pressed from inside the first read, not before run() starts. A press is taken
# only while it is younger than the window (a press nobody was listening for is
# stale, see dropoff_requested), and these runs use a one-second window — so a
# file written before main() imports and calibrates was discarded whenever
# start-up took longer than a second, which it did under the full runner's load
# and not alone. That is the rig being right and the test pressing too early.
def _press_on_first_read(handoff, text):
    def texts(n, k):
        if n == 1 and k == 0:
            open(os.path.join(handoff, 'uberscan-dropoff'), 'w').close()
        return text
    return texts


_ho = tempfile.mkdtemp()
r5 = run(_press_on_first_read(_ho, WHOLE), extra_argv=['--no-parallel'], seconds=6.0,
         handoff=_ho, dropoff_window=1.0)
_said = [d for d in r5['dropoffs'] if d[1].get('asked')]
ok_('a press that found no address is answered, not left silent (%r)'
    % (r5['dropoffs'][:1],), len(_said) == 1)
if _said:
    eq('...with no address, because there was none', _said[0][0], None)
    ok_('...and marked as the answer to a press', _said[0][1].get('asked'))
ok_('...and the log says it too, for whoever reads one',
    any('read as an address' in l for l in r5['logs']))
# ONCE. The window closes, it is answered, and the answer does not repeat on
# every pass of the loop for the rest of the shift.
eq('...said once, over %d reads' % r5['calls'], len(_said), 1)

# ...and a press that IS answered is not also reported as a failure.
#
# This one found a real fault rather than guarding one. `asked` is false for a
# read that began after the deadline, and the press was being closed only by an
# asked read — so a read straddling the deadline sent the address, the panel
# put it up in green, and the press stayed outstanding until the branch below
# announced "nothing on that screen read as an address" over the address
# already showing. Two claims about one press, the second contradicting the
# first, on the screen the driver is reading in a moving car. Any address
# closes the press now.
_ho2 = tempfile.mkdtemp()
NAV_ADDR = 'Dropoff 123 Main St, Acworth, GA 30101 12 min Start'
r7 = run(_press_on_first_read(_ho2, NAV_ADDR), extra_argv=['--no-parallel'], seconds=6.0,
         handoff=_ho2, dropoff_window=1.0)
_found = [d for d in r7['dropoffs'] if d[0] is not None]
_empty = [d for d in r7['dropoffs'] if d[0] is None]
ok_('a press that finds an address is answered with it (%r)'
    % ([(d[0] or {}).get('line') for d in r7['dropoffs']][:2],), len(_found) >= 1)
eq('...and is not ALSO reported as having found nothing', _empty, [])

# --- a ⌖ press reads the whole screen box, and only the destination off it --
#
# A tight card box drawn by hand kept the reader off the map, and blinded ⌖ to
# the trip planner's addresses outside it. So while a press is open the read
# takes all of the screen box. That reading is the card AND what surrounds it,
# which is no evidence about the offer's money, so it answers the press and
# nothing else.
_ho3 = tempfile.mkdtemp()
r8 = run(_press_on_first_read(_ho3, WHOLE), extra_argv=['--no-parallel'], seconds=6.0,
         handoff=_ho3, dropoff_window=1.0, whole_text=NAV_ADDR)
ok_('a ⌖ press reads the whole screen box (%r)' % r8['wholes'][:6], any(r8['wholes']))
eq('...not before it was pressed', r8['wholes'][0], False)
eq('...and goes back to the card box once it is answered', r8['wholes'][-1], False)
ok_('...and the address outside the card box is the answer (%r)'
    % [(d[0] or {}).get('line') for d in r8['dropoffs']][:2],
    any(d[0] and 'Main St' in (d[0].get('line') or '') and d[1].get('asked')
        for d in r8['dropoffs']))

# The whole-screen read sees a DIFFERENT payout here — a card under a map, a
# planner listing two orders' totals. If it reached the offer, the panel would
# show a verdict for money no card on the phone offered.
_ho4 = tempfile.mkdtemp()
r9 = run(_press_on_first_read(_ho4, WHOLE), extra_argv=['--no-parallel'], seconds=6.0,
         handoff=_ho4, dropoff_window=1.0,
         whole_text='$99.00 20 min (5.0 mi) trip Dropoff 9 Elm St, Acworth, GA 30101')
ok_('a press with a payout in the whole screen box was read whole', any(r9['wholes']))
_pays = sorted(set((v[0][1] or {}).get('pay') for v in r9['verdicts']
                   if len(v[0]) > 1 and isinstance(v[0][1], dict)), key=str)
ok_('...and that payout never reached a verdict (%r)' % _pays, 99.0 not in _pays)
ok_('...nor the journal', all(row.get('pay') != 99.0 for row in r9['rows']))

# ...and a rig nobody pressed anything on says nothing. Without this the checks
# above pass on a message that is simply always sent.
r6 = run(lambda n, k: WHOLE, extra_argv=['--no-parallel'], seconds=6.0,
         handoff=tempfile.mkdtemp(), dropoff_window=1.0)
eq('a rig nobody pressed says nothing about a dropoff',
   [d for d in r6['dropoffs'] if d[1].get('asked')], [])
eq('...and reads only the card box', [w for w in r6['wholes'] if w], [])

# --- what the phone showed after a card landed ------------------------------
#
# The rig cannot see the Accept press and must never make it, so the only
# evidence a job was taken is the screen the phone goes to afterwards. These
# rows are the corpus for building that and nothing else — nothing reads them
# and nothing writes `accepted` off them.
#
# Driven through main() because the branch is a closure inside digest() and the
# one fault that matters is it never firing at all. `note_screen`'s own suite
# proves what it writes; this proves the loop ever calls it.

# The post-accept screen as the owner's own screenshot reads it, destination
# and all. It NAMES A PLACE, and that is the point: an Uber navigation screen
# names where the job goes the same way a card names the shop, so a guard that
# refused a frame for naming one would throw away exactly the screens worth
# collecting. What it named is written onto the row instead.
NAV = ('3.2 mi\nI-75 S toward 14th St\n65 LIMIT\n8 min 4.8 mi\n'
       'Deliver to Daria I.\nBCG Atlanta (1075 Peachtree St NE)')

# The card is read four times and lands on the second, so reads three and four
# are an offer card with a landed card already on the slate. Anything less and
# the fixture cannot tell "only a payout-free screen is recorded" from "the
# screen happened to be the next thing read": with the card read twice it lands
# on the last of them, the very next read is the navigation screen either way,
# and dropping `an_offer` from the guard entirely changes nothing anybody can
# see. Measured — that mutation survived this check until the fixture grew
# these two reads.
r = run(lambda n, k: WHOLE if n <= 4 else NAV, extra_argv=['--no-parallel'],
        seconds=30.0, health_every=0.2,
        until=lambda rows, ann, calls: any(x.get('kind') == 'screen'
                                           for x in rows))
_screens = [x for x in r['rows'] if x.get('kind') == 'screen']
_offers = [x for x in r['rows'] if not x.get('kind')]
ok_('the screen that followed a card reaches the journal', len(_screens) == 1)
if _screens and _offers:
    eq('...naming the card it followed', _screens[0].get('after'),
       _offers[-1].get('id'))
    ok_('...and carrying what was on it',
        'Deliver to Daria I.' in (_screens[0].get('text') or ''))
    # The reading as it was read, not the flattened one the parser works on.
    # On these screens the LINE is the grammar — "Deliver to Daria I." is a
    # line — and the merged reading in `parsed` has already had that thrown
    # away. The loop has both in hand at the call site and has to pass the
    # right one.
    ok_('...as it was read, line breaks and all',
        '\n' in (_screens[0].get('text') or ''))
# ...and the driver can see it happening from the seat, which is the only place
# they can see anything. A collection that quietly stopped collecting would read
# months later as a rate of zero, and the journal is not somewhere a person
# checks while driving.
ok_('the health line says how many screens have been recorded (%r)'
    % ([m for m in r['logs'] if 'screen' in m][:1],),
    any('recorded as following a card' in m for m in r['logs']))
# ONCE, however long the navigation screen sits in front of the camera. This is
# the check that stands between a delivery and a few hundred identical rows in
# a file that is only ever appended to.
# The BOUND — one screen row per card, whatever else is read — is not checked
# here, and deliberately not. It cannot be: once a read comes back with no
# payout `card_on_screen` goes false, the verify beat stops (see next_verify),
# and the stubbed camera holds one still picture, so the motion gate never
# fires again. Measured, on three fixtures: five reads every time, one of them
# payout-free, whatever the reader is told to answer afterwards.
#
# A check written over that run is a check that cannot fail — and one was,
# reading `len(_screens) <= 2` over a run whose `until` halts at the first
# screen row. Deleting the whole once-per-card mechanism from note_screen left
# this suite green while rpi/test_journal.py caught it with four failures.
# That is where the bound is proven, against the real consider(), including the
# case that made it false: a card lands several rows, not one.

# An Uber navigation screen NAMES its destination, the same way a card names the
# shop. Recorded, not acted on: refusing a frame for naming a place would throw
# away exactly the screens this is collected for, and trusting one would be the
# recogniser it must not invent. The loop has to hand what the frame named down
# to the row rather than dropping it on the floor.
ok_('...carrying what the screen named (%r)' % (_screens[0].get('places'),),
    any('BCG Atlanta' in p for p in (_screens[0].get('places') or [])))
# ...and it is a SCREEN, not the card. The two classes a recogniser has to
# separate are "an offer card" and "the screen after one", so a corpus holding a
# card's own text under `kind: screen` is a corpus that teaches the opposite of
# what it was collected for. Asked of the payout, because that is the grammar
# `an_offer` itself separates them by, and asked of every row rather than the
# first: one right answer among several wrong ones is still a poisoned corpus.
eq('no screen row carries a payout, which would make it a card',
   [x.get('text') for x in _screens
    if OP.find_pay(OP.normalize(x.get('text') or '')) is not None], [])

# ONE FRAME of glare over a card reads `pay: None` over a card, and the loop has
# to say which it was. `card_on_screen` still holds the PREVIOUS read's answer
# at the call site, so the loop knows there was a card here a moment ago and
# passes that down onto the row. Not refused — reads are driven by a motion gate
# and the frame after an accept is sometimes the only one, so refusing would
# lose the screen rather than label it.
r3 = run(lambda n, k: GLARE if n == 5 else WHOLE, extra_argv=['--no-parallel'],
         seconds=20.0,
         until=lambda rows, ann, calls: any(x.get('kind') == 'screen'
                                            for x in rows))
_glared = [x for x in r3['rows'] if x.get('kind') == 'screen']
ok_('a glared frame of a card is recorded', len(_glared) == 1)
if _glared:
    eq('...and the loop marks it as taken with a card still up',
       _glared[0].get('cardWasUp'), True)

# A CARD THE RIG SAW AND NEVER RECORDED must not have the next screen filed
# against the card before it. This is the fault that would have put a lie in the
# journal, and it is reproduced here end to end because that is how it was found
# — reading the code, the slate looked like "the last card", and it is "the last
# card that LANDED".
#
# A card needs two agreeing reads to lock (Scanner.agree_to_lock) and consider()
# is only called on a reading that is ready AND locked, so a second card
# delivered exactly once is seen, counted in `saw`, and never reaches the
# journal at all. `saw` minus `kept` is the measured count of those, and the
# offers page already renders it as "the scanner picked a payout off the screen
# and never managed to record it".
#
# Before the fix this run wrote {kind: screen, after: <card A>} over a driver
# who had just accepted card B.
SECOND_CARD = ('$9.25 4 min (1.4 mi) away Barrett Pkwy NW, Kennesaw '
               '18 min (5.2 mi) trip 44 Oak St, Acworth, GA 30101')
r4 = run(lambda n, k: WHOLE if n <= 3 else (SECOND_CARD if n == 4 else NAV),
         extra_argv=['--no-parallel'], seconds=20.0,
         until=lambda rows, ann, calls: calls >= 6)
_landed = [x.get('id') for x in r4['rows'] if not x.get('kind')]
_after = [x.get('after') for x in r4['rows'] if x.get('kind') == 'screen']
ok_('one card landed and a second was seen without landing (%r)'
    % (sorted(set(_landed)),), len(set(_landed)) == 1)
eq('the screen after a card that never landed is not filed against the one '
   'before it', _after, [])

# A CLIPPED read is not a payout-free screen. `clipped` means the payout was
# found and was flush against the top of the crop, and the reader answers it
# with an empty parse — so the parse has no payout and no places over a screen
# that was an offer card. Filing that as "what the phone showed after the card"
# would put a card's own text into the corpus as the negative class, which is
# the one confusion a recogniser built on these rows could not survive.
r2 = run(lambda n, k: WHOLE, extra_argv=['--no-parallel'], seconds=14.0,
         clipped_for=lambda n, k: n >= 3,
         until=lambda rows, ann, calls: calls >= 8
         and any(not x.get('kind') for x in rows))
ok_('a card landed before the crop slipped',
    any(not x.get('kind') for x in r2['rows']))
eq('a clipped read is not recorded as the screen after a card',
   [x for x in r2['rows'] if x.get('kind') == 'screen'], [])

# --- 📷 Snap: the reader says what it last read, into the folder named ---------
#
# status.json is what the panel knew. What the READER was looking at — the card
# it cut out last, what it made of it, its counters, its last beat, the
# phone's GPS — never left this loop, so POST /api/snap leaves a request naming
# its folder and the loop answers into it once. Driven through main() the way
# the dropoff and crop-box requests are, with the request written as server.js
# writes it: JSON naming the folder, renamed into place.
import re                                                     # noqa: E402
import socket as _socket                                      # noqa: E402
import threading as _threading                                # noqa: E402


def _ask_snap(handoff, folder, age=None):
    """What POST /api/snap leaves for the loop. `age` back-dates it."""
    where = os.path.join(handoff, 'uberscan-snap.json')
    with open(where + '.w', 'w') as fh:
        json.dump({'folder': folder}, fh)
    os.replace(where + '.w', where)
    if age is not None:
        os.utime(where, (time.time() - age, time.time() - age))
    return where


def _json_or_none(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


# A crop of its own for each read, flat grey at 20 times the read's number, so
# the picture kept says which read it came from. Read 4 never comes back: the
# reader's thread is stuck on it, so read 3 is the last one there is. An answer
# that went back for a fresh read shows as a fifth: asked of the reader, it is
# counted as handed over though it never starts, and made on the loop's own
# thread, it is answered (hang_on_loop=False) — with read 5's crop — rather
# than hanging the suite where no check could see it. Every snap run below
# that strands the reader does the same, for the same reason.
def _crop_of(n):
    return np.full((120, 80), 20 * n, np.uint8)


_snho = tempfile.mkdtemp()
_snfold = tempfile.mkdtemp()
_sreq = [None]
# --no-track and a Re-find press, so the beat carries a refusal: the flags
# reader.json reports are then something the beat said, not four Falses.
open(os.path.join(_snho, 'uberscan-recalibrate'), 'w').close()


def _snap_once_stuck(rows, ann, calls):
    if _sreq[0] is None and calls >= 4 and any(not x.get('kind') for x in rows):
        _sreq[0] = _ask_snap(_snho, _snfold)
    return _sreq[0] is not None and os.path.exists(os.path.join(_snfold, 'reader.json'))


r14 = run(lambda n, k: WHOLE, extra_argv=['--no-track'], seconds=20.0, handoff=_snho,
          alive_every=0.05, stuck_after=60.0, hang_from=4, hang_on_loop=False,
          fitted_for=_crop_of, until=_snap_once_stuck)
_said = _json_or_none(os.path.join(_snfold, 'reader.json')) or {}
_jpg = cv2.imread(os.path.join(_snfold, 'reader.jpg'), cv2.IMREAD_GRAYSCALE)
ok_('a snap request is answered into the folder it names, reader.json and reader.jpg (%r)'
    % sorted(os.listdir(_snfold)), _said and _jpg is not None)
ok_('reader.jpg is the crop the last read handed the reader, kept from it (mean %r, read 3 is 60)'
    % (None if _jpg is None else round(float(_jpg.mean()), 1)),
    _jpg is not None and _jpg.shape == (120, 80) and abs(float(_jpg.mean()) - 60) < 2)
eq('...answered while the reader is stuck on the next one, so no read was asked for it '
   '(reads handed to the reader, reads begun)', (r14['submitted'], r14['calls']), (4, 4))
_read = _said.get('read') or {}
eq('reader.json says what that read saw, as text and as figures',
   (_read.get('text'), (_read.get('parsed') or {}).get('pay'),
    (_read.get('rate') or {}).get('state')), (WHOLE, 16.05, 'go'))
eq('...and that it read the card crop, not the whole screen for ⌖', _read.get('wholeScreen'), False)
ok_('...when it was read, and how long before the answer (%r ms)' % _read.get('ageMs'),
    isinstance(_read.get('ageMs'), int) and 0 <= _read['ageMs'] < 30000
    and abs(_read.get('at', 0) + _read['ageMs'] - (_said.get('answeredAt') or 0)) <= 1)
_snoffers = [x for x in r14['rows'] if not x.get('kind')]
eq('...the offer it has on record, and that it is in the journal',
   _said.get('offer'), {'id': _snoffers[-1].get('id') if _snoffers else '?', 'landed': True})
ok_('...and the card\'s episode (%r)' % _said.get('episode'),
    isinstance(_said.get('episode'), int))
# Three reads were digested and the health window is two minutes, so the
# counters as they stand are those three — not a fresh window a press opened.
eq('...the health counters as they stand', ((_said.get('health') or {}).get('reads'),
                                              (_said.get('health') or {}).get('complete')), (3, 3))
_beat = _said.get('heartbeat')
ok_('...and the flags the last heartbeat carried, the refused Re-find among them (%r)'
    % (_beat,), isinstance(_beat, dict) and
    '--no-track' in (_beat.get('refindRefused') or '')
    and (_beat.get('tooBright'), _beat.get('tooDim'), _beat.get('notSaving')) == (False, False, None)
    and isinstance(_beat.get('ageMs'), int))
eq('...the camera\'s word among them, null while it can see',
   (_beat or {}).get('blind', 'absent'), None)
eq('...and "gps off", with no --gps given', _said.get('gps'), 'gps off')
ok_('the request is taken, so it is answered once',
    _sreq[0] is not None and not os.path.exists(_sreq[0]))
eq('...and the log says where the answer went, once',
   [l for l in r14['logs'] if l.startswith('snap:')],
   ['snap: said what the reader last read into %s' % _snfold])

# ...and before any read has come back there is no crop to give, and it says so.
# --no-journal as well, so there is no card on record to name either.
_snho2 = tempfile.mkdtemp()
_snfold2 = tempfile.mkdtemp()
_sreq2 = [None]


def _snap_first_thing(rows, ann, calls):
    if _sreq2[0] is None and calls >= 1:
        _sreq2[0] = _ask_snap(_snho2, _snfold2)
    return _sreq2[0] is not None and os.path.exists(os.path.join(_snfold2, 'reader.json'))


run(lambda n, k: WHOLE, extra_argv=['--no-journal'], seconds=15.0, handoff=_snho2,
    hang_from=1, hang_on_loop=False, stuck_after=60.0, fitted_for=_crop_of,
    until=_snap_first_thing)
_said2 = _json_or_none(os.path.join(_snfold2, 'reader.json')) or {}
eq('a scanner that has not read anything yet answers with no read and says why',
   (_said2.get('read', '?'), _said2.get('noCrop')), (None, 'no read yet'))
eq('...and leaves no reader.jpg', sorted(os.listdir(_snfold2)), ['reader.json'])
eq('...and says no journal keeps an offer on record, rather than naming none',
   _said2.get('offer'), 'not kept: --no-journal')

# ...and a ⌖ read is a read: the last thing the reader cut out was the whole
# screen box, and reader.json says that is what it was. Pressed in read 1, so
# read 2 is the whole-screen one; read 3 never comes back, so read 2 stays the
# last there is.
_snho3 = tempfile.mkdtemp()
_snfold3 = tempfile.mkdtemp()
_sreq3 = [None]


_SNAP_NAV = 'Dropoff 9 Elm St, Acworth, GA 30101 4 min Start'


def _press_dropoff_in_read_1(n, k):
    if n == 1 and k == 0:
        open(os.path.join(_snho3, 'uberscan-dropoff'), 'w').close()
    return WHOLE


def _snap_after_the_press(rows, ann, calls):
    if _sreq3[0] is None and calls >= 3:
        _sreq3[0] = _ask_snap(_snho3, _snfold3)
    return _sreq3[0] is not None and os.path.exists(os.path.join(_snfold3, 'reader.json'))


_r15 = run(_press_dropoff_in_read_1, seconds=15.0, handoff=_snho3,
           whole_text=_SNAP_NAV, hang_from=3, hang_on_loop=False, stuck_after=60.0,
           fitted_for=_crop_of, until=_snap_after_the_press)
_read3 = (_json_or_none(os.path.join(_snfold3, 'reader.json')) or {}).get('read') or {}
_jpg3 = cv2.imread(os.path.join(_snfold3, 'reader.jpg'), cv2.IMREAD_GRAYSCALE)
eq('the last read being ⌖\'s, reader.json says it read the whole screen, and what it saw (%r)'
   % (_r15['wholes'],), (_read3.get('wholeScreen'), _read3.get('text')), (True, _SNAP_NAV))
ok_('...and reader.jpg is that read\'s crop (mean %r, read 2 is 40)'
    % (None if _jpg3 is None else round(float(_jpg3.mean()), 1)),
    _jpg3 is not None and abs(float(_jpg3.mean()) - 40) < 2)

# --- ...but only a request still worth answering -----------------------------
#
# The request lives in /dev/shm, which a scanner restart does not clear, and
# server.js stops waiting after four seconds. One found older than that — made
# while the scanner was down, or aiming — would land reader files in a folder
# whose snap.json already says there are none.
for _age, _label, _said_as in (
        (10.0, 'a snap request from before the scanner was listening',
         r'ignored a snap request from \d+s ago'),
        (-600.0, 'a snap request stamped ahead of a clock that has since stepped back',
         r'ignored a snap request stamped \d+s ahead of the clock')):
    _ho = tempfile.mkdtemp()
    _fold = tempfile.mkdtemp()
    _req = _ask_snap(_ho, _fold, age=_age)
    _r = run(lambda n, k: WHOLE, seconds=6.0, handoff=_ho, fitted_for=_crop_of,
             until=lambda rows, ann, calls: calls >= 2)
    eq('%s is not answered' % _label, os.listdir(_fold), [])
    eq('...is cleared, so it cannot be answered later either', os.path.exists(_req), False)
    ok_('...and the log says it was ignored (%r)'
        % [l for l in _r['logs'] if 'snap request' in l][:1],
        any(re.match(_said_as, l) for l in _r['logs']))

# ...and a folder that is not there is not made. The server makes the folder;
# one that has gone was removed by a press that kept nothing.
_ho = tempfile.mkdtemp()
_gone = os.path.join(tempfile.mkdtemp(), 'removed-by-the-server')
_req = _ask_snap(_ho, _gone)
_r = run(lambda n, k: WHOLE, seconds=6.0, handoff=_ho, fitted_for=_crop_of,
         until=lambda rows, ann, calls: calls >= 2)
eq('a snap request naming a folder that is not there makes none', os.path.exists(_gone), False)
ok_('...and says so in the log',
    any(l.startswith('ignored a snap request naming no folder') for l in _r['logs']))

# The age rule's edges, asked directly the way test_scan_pi.py asks
# dropoff_requested: a request a moment old and one just inside the window are
# answered; one exactly the window old is not.
_ho = tempfile.mkdtemp()
_fold = tempfile.mkdtemp()
_was_dir, _was_log = os.environ.get(HO.ENV_DIR), SP.log
os.environ[HO.ENV_DIR] = _ho
SP.log = lambda m: None
try:
    _now = time.time()
    for _age in (0.2, SP.SNAP_ANSWER_WINDOW - 0.2):
        _req = _ask_snap(_ho, _fold)
        os.utime(_req, (_now - _age, _now - _age))
        eq('a snap request %.1fs old names its folder' % _age, SP.snap_requested(now=_now), _fold)
        eq('...once', SP.snap_requested(now=_now), None)
    _req = _ask_snap(_ho, _fold)
    os.utime(_req, (_now - SP.SNAP_ANSWER_WINDOW, _now - SP.SNAP_ANSWER_WINDOW))
    eq('a snap request exactly its window old is not answered', SP.snap_requested(now=_now), None)
finally:
    SP.log = _was_log
    if _was_dir is None:
        os.environ.pop(HO.ENV_DIR, None)
    else:
        os.environ[HO.ENV_DIR] = _was_dir

# --- ...with the phone's GPS when it was asked to listen to one --------------
#
# A phone that answers: a socket here sending the RMC sentence test_gps.py reads
# as 34.0117N 84.6105W. reader.json carries Phone.state() and fix() as given.
RMC = '$GPRMC,182049.00,A,3400.7020,N,08436.6300,W,0.0,0.0,120926,,,A*4A'
_gsock = _socket.socket()
_gsock.bind(('127.0.0.1', 0))
_gsock.listen(1)
_gstop = []


def _gps_phone():
    _gsock.settimeout(0.2)
    while not _gstop:
        try:
            conn, _ = _gsock.accept()
        except OSError:
            continue
        try:
            while not _gstop:
                conn.sendall((RMC + '\r\n').encode('ascii'))
                real_sleep_for_gps(0.1)
        except OSError:
            pass
        finally:
            conn.close()


real_sleep_for_gps = time.sleep
_gthread = _threading.Thread(target=_gps_phone, daemon=True)
_gthread.start()
_ho = tempfile.mkdtemp()
_fold = tempfile.mkdtemp()
_greq = [None]
_gt0 = time.time()


def _snap_once_fixed(rows, ann, calls):
    if _greq[0] is None and time.time() - _gt0 > 2.0 and calls >= 1:
        _greq[0] = _ask_snap(_ho, _fold)
    return _greq[0] is not None and os.path.exists(os.path.join(_fold, 'reader.json'))


try:
    run(lambda n, k: WHOLE, extra_argv=['--gps', '127.0.0.1:%d' % _gsock.getsockname()[1]],
        seconds=15.0, handoff=_ho, fitted_for=_crop_of, until=_snap_once_fixed)
finally:
    _gstop.append(True)
    _gsock.close()
_gps = (_json_or_none(os.path.join(_fold, 'reader.json')) or {}).get('gps')
_gps = _gps if isinstance(_gps, dict) else {'said': _gps}
eq('a rig listening to a phone says what the phone said: its state, and its fix (%r)'
   % (_gps.get('said'),),
   ((_gps.get('state') or {}).get('state'),
    round((_gps.get('fix') or {}).get('lat') or 0, 4),
    round((_gps.get('fix') or {}).get('lon') or 0, 4)),
   ('fixed', 34.0117, -84.6105))

# --- the pieces, asked directly ------------------------------------------------
# An age is two readings of one clock, and the Pi's jumps when the network sets
# it. A read before the jump and an answer after it are not "20,000 days ago".
eq('a read and an answer on a set clock are an age in ms',
   SP.age_ms(1790000000.0, 1790000002.5), 2500)
eq('...a read before the clock was set is of unknown age',
   SP.age_ms(1000.0, 1790000002.5), None)
eq('...and so is a read stamped after the answer: the clock stepped back',
   SP.age_ms(1790000002.5, 1790000000.0), None)

# A card the journal has not taken yet — the append failed, or has not run — is
# on record in memory and not on disk, and reader.json says which.
class _OnRecord(object):
    id, landed_id = '1790000000000-1605', None


eq('a card on record that has not reached the journal is said as not landed',
   SP.reader_record(None, 1790000000.0, offer_log=_OnRecord()).get('offer'),
   {'id': '1790000000000-1605', 'landed': False})

# The counters a snap reports are the ones the health line would, as they
# stand, and asking for them does not start a new window.
_h = SP.Health()
_h.since = 1000.0
for _i in range(2):
    _h.add({'ms': {'total': 100.0 + _i}}, {'complete': True, 'pay': 9.0})
_mid = _h.counters(1010.0)
_was_log = SP.log
SP.log = lambda m: None
try:
    _tally = _h.report(1000.0 + SP.HEALTH_EVERY + 1, None, PL.Scanner(quad=None, roi=None))
finally:
    SP.log = _was_log
eq('a snap\'s counters are the window as it stands', (_mid['reads'], _mid['over']), (2, 10))
eq('...and asking for them does not end the window: the health line still has both reads',
   (_tally or {}).get('reads'), 2)
# ...plus the one thing counters() cannot know, the corners' state, which the
# `seen` row carries and report() alone is handed the tracker for. This holds
# the field names only: the tally is counters() and `corners`, and nothing
# else. Whether `_window` re-states a counter under the same name is held by
# the next check, which asks it for its keys.
eq('...the line\'s tally being the same counters, at its own moment, and the corners',
   sorted((_tally or {}).keys()), sorted(list(_mid.keys()) + ['corners']))
eq('...the window adding only the corners, never a second copy of a counter',
   sorted(_h._window(None).keys()), ['corners'])

# A crop that cannot be written is said in reader.json, and reader.json itself
# still goes; a folder that cannot take reader.json is said in the log.
_fold = tempfile.mkdtemp()
_said3 = []
_was_log = SP.log
SP.log = _said3.append
try:
    _last = {'at': time.time(), 'fitted': None, 'wholeScreen': False, 'crop': None,
             'text': '', 'parsed': {}, 'rate': {}}
    SP.answer_snap(_fold, _last, SP.reader_record(_last, time.time()))
    _blocked = os.path.join(tempfile.mkdtemp(), 'a-file')
    open(_blocked, 'w').close()
    eq('a folder that will not take reader.json is answered False',
       SP.answer_snap(_blocked, None, SP.reader_record(None, time.time())), False)
finally:
    SP.log = _was_log
ok_('a crop that cannot be written is said in reader.json (%r)'
    % (_json_or_none(os.path.join(_fold, 'reader.json')) or {}).get('noCrop'),
    ((_json_or_none(os.path.join(_fold, 'reader.json')) or {}).get('noCrop') or '')
    .startswith('could not write reader.jpg: '))
ok_('...and one that cannot take reader.json is said in the log (%r)' % _said3[-1:],
    any(l.startswith('could not answer a snap into %s' % _blocked) for l in _said3))

# --- the app's zone prompt is not an offer -----------------------------------
#
# "Switch to this zone with peak pay! +$1.00/order ... Avg. offer wait 1min"
# reached the panel five times on the owner's week as an offer — $12.00/hr
# PASS, $20.00/hr twice, $10.91/hr, one withheld for its one minute — and the
# journal five times as a row the offers page counted. The parser refuses the
# bonus as a payout now (OP.PAY_IS_PER_ORDER); these are the end of that, driven
# through main(): what the panel was sent, and what reached the file.
#
# Verbatim, row 565's stored frame.
PROMPT = ('GA: Marietta North\nSwitch to this zone\nwith peak pay!\n'
          '+$1.00/order until 8:20 PM\nAvg. offer wait\n1min\nDon\'t switch')
rp1 = run(lambda n, k: PROMPT, extra_argv=['--no-parallel'], seconds=12.0,
          until=lambda rows, ann, calls: calls >= 3
          or any(x.get('kind') == 'promo' for x in rows))
ok_('the prompt was read (%d reads)' % rp1['calls'], rp1['calls'] >= 1)
eq('no offer row is written for the zone prompt',
   [x.get('pay') for x in rp1['rows'] if not x.get('kind')], [])
eq('...nor any verdict sent to the panel for it',
   [v[0][0].get('state') for v in rp1['verdicts']
    if v[0] and isinstance(v[0][0], dict) and v[0][0].get('ready')], [])
eq('...nor an offer announced off it', rp1['announced'], [])
# The rig's own start and stop rows bracket every run now and are not about the
# screen, so they are set aside here; everything else the run wrote is asked.
_rp1 = [x for x in rp1['rows'] if x.get('kind') != 'up']
eq('it is written as a prompt instead',
   [x.get('kind') for x in _rp1], ['promo'])
if _rp1:
    ok_('...the prompt as it was read, line breaks and all',
        _rp1[0].get('text') == PROMPT)

# ...and after a card, it is not the screen that followed the card. It is one
# prompt in one place, a `promo` row with its own stamp, whether or not a card
# happened to land before it. The card is read six times before the prompt, two
# more than the navigation-screen run above needs, because a run on a loaded
# machine that has not landed the card by then tests nothing here.
rp2 = run(lambda n, k: WHOLE if n <= 6 else PROMPT,
          extra_argv=['--no-parallel'], seconds=30.0,
          until=lambda rows, ann, calls: any(
              x.get('kind') in ('promo', 'screen') for x in rows))
ok_('a card landed before the prompt (%d reads)' % rp2['calls'],
    any(not x.get('kind') for x in rp2['rows']))
eq('the prompt after a card is not recorded as the screen after it',
   [x.get('text') for x in rp2['rows'] if x.get('kind') == 'screen'], [])
eq('...it is recorded as a prompt',
   len([x for x in rp2['rows'] if x.get('kind') == 'promo']), 1)
eq('...and no offer row carries its bonus as a payout',
   [x.get('pay') for x in rp2['rows'] if not x.get('kind')
    and x.get('pay') != 16.05], [])

# ...and the prompt ENDS the card's window, so the screen after the prompt is
# not filed against the card before it. While the bonus read as a $1 payout,
# saw_card dropped the slate on it; refused, it left the slate armed, and this
# run wrote the navigation screen `after:` the card — a card the driver did not
# take, with the app's own prompt in between. All five cards read just before
# the week's five prompts went unticked.
#
# The picture in the mount is changed under the prompt's read. Without that
# the still picture is never read again once a frame comes back payout-free
# (see the once-per-card note above), and a run that never reads the screen
# after the prompt cannot fail the check that is about it.
_rp3 = {'cam': [], 'nav_at': None}


def _rp3_texts(n, k):
    if n <= 6:
        return WHOLE
    if n == 7:
        if _rp3['cam'] and k == 0:
            _rp3['cam'][0].offer = _rp3['cam'][0].empty
        return PROMPT
    if _rp3['nav_at'] is None:
        _rp3['nav_at'] = time.time()
    return NAV


# Halted at the screen row if one is written, or three seconds after the
# screen was first read. With the slate left armed, the wrong row landed 21ms
# after that read, so one that has not landed in three seconds is not coming.
rp3 = run(_rp3_texts, extra_argv=['--no-parallel'], seconds=40.0,
          cam_out=_rp3['cam'],
          until=lambda rows, ann, calls: any(
              x.get('kind') == 'screen' for x in rows)
          or (_rp3['nav_at'] is not None
              and time.time() - _rp3['nav_at'] > 3.0))
ok_('a card, the prompt, then a screen: the card landed (%d reads)'
    % rp3['calls'], any(not x.get('kind') for x in rp3['rows']))
ok_('...the prompt was recorded',
    any(x.get('kind') == 'promo' for x in rp3['rows']))
ok_('...and the screen after the prompt was read', _rp3['nav_at'] is not None)
eq('the screen after the zone prompt is not filed against the card before it',
   [x.get('after') for x in rp3['rows'] if x.get('kind') == 'screen'], [])

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d loop checks passed' % ok)
sys.exit(1 if bad else 0)
