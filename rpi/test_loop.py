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


def out_for(text):
    p = OP.parse(text)
    return {'parsed': dict(p), 'rate': OP.rate(p, {'target': 25}), 'locked': False,
            'text': text, 'clipped': False, 'dropped': 0, 'recovered': 0,
            'crop': [0, 0, 1, 1], 'card': None, 'fitted': None,
            'ms': {'warp': 0, 'prep': 0, 'ocr': 0, 'parse': 0, 'total': 1}}


def run(texts_for_call, extra_argv=(), seconds=12.0, until=None, health_every=None,
        hang_from=None, stuck_after=None, handoff=None, alive_every=None,
        refind_notice_s=None, config_extra=None, appear_at=0.4, cam_out=None):
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
        return [out_for(texts_for_call(calls[0], k)) for k in range(len(frames))]

    announced, verdicts, beats, logs, alive = [], [], [], [], []
    real = (SP.start_camera, SP.emit, SP.emit_offer, SP.emit_alive, SP.log,
            PL.Scanner.look_many, time.sleep, SP.HEALTH_EVERY, SP.READ_STUCK_S,
            SP.emit_reading)
    real_sleep = real[6]
    SP.emit_reading = lambda *a, **k: None
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
         SP.emit_reading) = real
        SP.ALIVE_EVERY = was_alive_every
        SP.REFIND_NOTICE_S = was_refind_s
        if handoff:
            if was_handoff is None:
                os.environ.pop(HO.ENV_DIR, None)
            else:
                os.environ[HO.ENV_DIR] = was_handoff
    return dict(rows=rows(), announced=announced, beats=beats, calls=calls[0],
                logs=logs, alive=alive)


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

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d loop checks passed' % ok)
sys.exit(1 if bad else 0)
