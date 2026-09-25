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


class FakeCam(object):
    """A card that appears in the mount shortly after the loop starts."""

    def __init__(self, offer, empty, appear_at=0.4):
        self.offer, self.empty = offer, empty
        self.appear_at = appear_at
        self.started = time.time()
        self._show()

    def _show(self):
        t = time.time() - self.started
        self.frame = self.offer if t >= self.appear_at else self.empty
        grey = cv2.cvtColor(self.frame, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(grey, LORES, interpolation=cv2.INTER_AREA)
        self.lores = np.concatenate([small.ravel(),
                                     np.full(LORES[0] * LORES[1] // 2, 128, np.uint8)])

    def capture_request(self):
        self._show()
        time.sleep(0.01)
        return Request(self)

    def set_controls(self, c):
        pass

    def stop(self):
        pass

    def close(self):
        pass


def out_for(text, clipped=False):
    # `clipped` is what the real reader answers when a payout WAS found and was
    # sitting flush against the top of the crop — pipeline.py hands back
    # `parse('')` for it, so the parse is empty over a screen that was a card.
    # Reproduced here rather than described, because the branch that has to tell
    # that apart from a payout-free screen cannot be reached any other way.
    p = OP.parse('' if clipped else text)
    return {'parsed': dict(p), 'rate': OP.rate(p, {'target': 25}), 'locked': False,
            'text': text, 'clipped': clipped, 'dropped': 1 if clipped else 0,
            'recovered': 0,
            'crop': [0, 0, 1, 1], 'card': None, 'fitted': None,
            'ms': {'warp': 0, 'prep': 0, 'ocr': 0, 'parse': 0, 'total': 1}}


def run(texts_for_call, extra_argv=(), seconds=12.0, until=None, health_every=None,
        hang_from=None, stuck_after=None, handoff=None, alive_every=None,
        refind_notice_s=None, config_extra=None, appear_at=0.4, cam_out=None,
        clipped_for=None, dropoff_window=None):
    """Run main() with the reader answering texts_for_call(n, k) for frame k of
    read call n (1-based). `hang_from`: read calls from this one on never
    return. `handoff`: a directory to point the button-press files at, so a
    request written here cannot be eaten by a scanner running on the same
    machine, nor this one eat theirs. Returns the journal rows, the
    announcements, the alive beats and what rode them, and the log lines."""
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
    cam = FakeCam(offer, TC.blank(), appear_at=appear_at)
    # Handed out so a check can ask what is really in the mount right now. The
    # stubbed reader answers with whatever text the check asked for whether or
    # not there is a card in front of it, so an announced offer is NOT evidence
    # that the camera can see one.
    if cam_out is not None:
        cam_out.append(cam)
    calls = [0]

    def look(self, frames, now=None, geom=None):
        calls[0] += 1
        if hang_from is not None and calls[0] >= hang_from:
            while True:
                real_sleep(0.05)
        return [out_for(texts_for_call(calls[0], k),
                        clipped=bool(clipped_for and clipped_for(calls[0], k)))
                for k in range(len(frames))]

    announced, verdicts, beats, logs, alive, dropoffs = [], [], [], [], [], []
    real = (SP.start_camera, SP.emit, SP.emit_offer, SP.emit_alive, SP.log,
            PL.Scanner.look_many, time.sleep, SP.HEALTH_EVERY, SP.READ_STUCK_S,
            SP.emit_reading, SP.emit_dropoff)
    real_sleep = real[6]
    SP.emit_reading = lambda *a, **k: None
    # Captured rather than printed, like the offer line beside it. The empty
    # answer — a press that found no address — is only visible here.
    SP.emit_dropoff = lambda address, **k: dropoffs.append((address, k))
    SP.start_camera = lambda *a, **k: cam
    SP.emit = lambda *a, **k: verdicts.append((a, k))
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
    try:
        SP.main()
    except KeyboardInterrupt:
        pass
    finally:
        (SP.start_camera, SP.emit, SP.emit_offer, SP.emit_alive, SP.log,
         PL.Scanner.look_many, time.sleep, SP.HEALTH_EVERY, SP.READ_STUCK_S,
         SP.emit_reading, SP.emit_dropoff) = real
        SP.DROPOFF_WINDOW = was_window
        SP.ALIVE_EVERY = was_alive_every
        SP.REFIND_NOTICE_S = was_refind_s
        if handoff:
            if was_handoff is None:
                os.environ.pop(HO.ENV_DIR, None)
            else:
                os.environ[HO.ENV_DIR] = was_handoff
    return dict(rows=rows(), announced=announced, beats=beats, calls=calls[0],
                logs=logs, alive=alive, dropoffs=dropoffs)


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

_fine = run(lambda n, k: WHOLE, alive_every=0.05, seconds=10.0,
            until=lambda rows, ann, calls: rows and calls >= 4)
eq('a journal that is taking rows says nothing about itself',
   any(b.get('not_saving') for b in _fine['alive']), False)
ok_('...having actually stored something, so that is not a silence of its own',
    _fine['rows'])

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
_ho = tempfile.mkdtemp()
open(os.path.join(_ho, 'uberscan-dropoff'), 'w').close()
r5 = run(lambda n, k: WHOLE, extra_argv=['--no-parallel'], seconds=6.0,
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
open(os.path.join(_ho2, 'uberscan-dropoff'), 'w').close()
NAV_ADDR = 'Dropoff 123 Main St, Acworth, GA 30101 12 min Start'
r7 = run(lambda n, k: NAV_ADDR, extra_argv=['--no-parallel'], seconds=6.0,
         handoff=_ho2, dropoff_window=1.0)
_found = [d for d in r7['dropoffs'] if d[0] is not None]
_empty = [d for d in r7['dropoffs'] if d[0] is None]
ok_('a press that finds an address is answered with it (%r)'
    % ([(d[0] or {}).get('line') for d in r7['dropoffs']][:2],), len(_found) >= 1)
eq('...and is not ALSO reported as having found nothing', _empty, [])

# ...and a rig nobody pressed anything on says nothing. Without this the checks
# above pass on a message that is simply always sent.
r6 = run(lambda n, k: WHOLE, extra_argv=['--no-parallel'], seconds=6.0,
         handoff=tempfile.mkdtemp(), dropoff_window=1.0)
eq('a rig nobody pressed says nothing about a dropoff',
   [d for d in r6['dropoffs'] if d[1].get('asked')], [])

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

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d loop checks passed' % ok)
sys.exit(1 if bad else 0)
