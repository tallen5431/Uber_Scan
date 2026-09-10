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
        hang_from=None, stuck_after=None):
    """Run main() with the reader answering texts_for_call(n, k) for frame k of
    read call n (1-based). `hang_from`: read calls from this one on never
    return. Returns the journal rows, the announcements, the alive beats and
    the log lines."""
    offer = TC.mount(TC.uberx_screen(), 1200)
    quad = PL.detect_screen_quad(offer)
    work = tempfile.mkdtemp()
    config = os.path.join(work, 'config.json')
    journal = os.path.join(work, 'journal.jsonl')
    with open(config, 'w') as fh:
        json.dump({'quad': [[float(x), float(y)] for x, y in quad], 'cardHeight': 900,
                   'capture': {'width': CAP[0], 'height': CAP[1]},
                   'lensPosition': 10.0, 'exposureTime': 16667,
                   'settings': {'target': 25, 'band': 15, 'costPerMile': 0.30}}, fh)
    cam = FakeCam(offer, TC.blank())
    calls = [0]

    def look(self, frames, now=None, geom=None):
        calls[0] += 1
        if hang_from is not None and calls[0] >= hang_from:
            while True:
                real_sleep(0.05)
        return [out_for(texts_for_call(calls[0], k)) for k in range(len(frames))]

    announced, verdicts, beats, logs = [], [], [], []
    real = (SP.start_camera, SP.emit, SP.emit_offer, SP.emit_alive, SP.log,
            PL.Scanner.look_many, time.sleep, SP.HEALTH_EVERY, SP.READ_STUCK_S,
            SP.emit_reading)
    real_sleep = real[6]
    SP.emit_reading = lambda *a, **k: None
    SP.start_camera = lambda *a, **k: cam
    SP.emit = lambda *a, **k: verdicts.append((a, k))
    SP.emit_offer = lambda *a, **k: announced.append(a)
    SP.emit_alive = lambda *a, **k: beats.append(time.time())
    SP.log = lambda m: logs.append(m)
    PL.Scanner.look_many = look
    if health_every is not None:
        SP.HEALTH_EVERY = health_every
    if stuck_after is not None:
        SP.READ_STUCK_S = stuck_after
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
    return dict(rows=rows(), announced=announced, beats=beats, calls=calls[0], logs=logs)


FRAG = '$16.05 20 min (7.3 mi) trip'
WHOLE = '$16.05 3 min (1.1 mi) away 20 min (7.3 mi) trip 123 Main St, Acworth, GA 30101'
# The decimal point lost: a payout that cannot be true, on a card that is
# already on disk. (A plausible near miss — $16.06 for $16.05 — is a card
# the journal itself would file as a different offer, and is still counted.)
LOST_DECIMAL = '$1605 3 min (1.1 mi) away 20 min (7.3 mi) trip 123 Main St, Acworth, GA 30101'

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

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d loop checks passed' % ok)
sys.exit(1 if bad else 0)
