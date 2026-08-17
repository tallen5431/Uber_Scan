"""The main loop, run against a fake camera.

    python3 rpi/test_scan_pi.py

scan_pi.py is the largest file here and the one with the most consequence — it
holds the camera, the journal and the decision to speak — and it had no test at
all. The parts it is made of were each covered and the thing they add up to was
not, which is the wrong way round: the faults that actually stop a shift are
lifecycle faults, and those only exist in the assembled loop.

Nothing here stubs the pipeline. The frames are synthesised, but the motion
gate, the tracker, the accumulator, the paired reads, the exposure control, the
health line, the journal and the speech gate are all the shipped code. The
camera is the only fake, and it is fake so that the test can hold it to account:
it counts every request handed out and every one given back.
"""

import json
import os
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2                                                    # noqa: E402
import testcards as TC                                        # noqa: E402

if not TC.available():
    print('no PIL or no usable font — skipping the main-loop checks')
    sys.exit(0)

import pipeline as PL                                         # noqa: E402

ok = bad = 0
LORES = (640, 480)
CAP = (2328, 1748)


def eq(name, got, want):
    global ok, bad
    if got == want:
        ok += 1
    else:
        bad += 1
        print('FAIL  %s: got %r want %r' % (name, got, want))


def ok_(name, cond):
    eq(name, bool(cond), True)


class Request(object):
    """One capture, which the loop is obliged to give back."""

    def __init__(self, cam):
        self.cam = cam
        self.released = False
        cam.outstanding += 1
        cam.taken += 1

    def make_buffer(self, name):
        return self.cam.lores.tobytes()

    def make_array(self, name):
        return self.cam.frame.copy()

    def get_metadata(self):
        return {}

    def release(self):
        if self.released:
            self.cam.double_released += 1
            return
        self.released = True
        self.cam.outstanding -= 1
        self.cam.given_back += 1


class FakeCam(object):
    """A cabin, then an offer, then the cabin again."""

    def __init__(self, offer, empty, appear_at=0.6, vanish_at=6.0):
        self.offer, self.empty = offer, empty
        self.appear_at, self.vanish_at = appear_at, vanish_at
        self.started = time.time()
        self.taken = self.given_back = self.outstanding = 0
        self.double_released = 0
        self.controls = []
        self.stopped = False
        self._show()

    def _show(self):
        t = time.time() - self.started
        self.frame = self.offer if self.appear_at <= t < self.vanish_at else self.empty
        grey = cv2.cvtColor(self.frame, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(grey, LORES, interpolation=cv2.INTER_AREA)
        # YUV420 puts the Y plane first, which is all the loop reads.
        self.lores = np.concatenate([small.ravel(),
                                     np.full(LORES[0] * LORES[1] // 2, 128, np.uint8)])

    def capture_request(self):
        self._show()
        time.sleep(0.01)
        return Request(self)

    def set_controls(self, controls):
        self.controls.append(controls)

    def stop(self):
        self.stopped = True

    def close(self):
        pass


def run(screen, seconds=9.0, extra_argv=(), appear_at=0.6, vanish_at=6.0):
    """Drive scan_pi.main() over a fake camera and collect what came out."""
    import scan_pi as SP

    offer = TC.mount(screen, 1200)
    empty = TC.blank()
    quad = PL.detect_screen_quad(offer)
    if quad is None:
        raise RuntimeError('the test card is not detectable; the fault is in the fixture')

    workdir = tempfile.mkdtemp()
    config = os.path.join(workdir, 'config.json')
    journal = os.path.join(workdir, 'journal.jsonl')
    with open(config, 'w') as fh:
        json.dump({'quad': [[float(x), float(y)] for x, y in quad],
                   'cardHeight': 900,
                   'capture': {'width': CAP[0], 'height': CAP[1]},
                   'lensPosition': 10.0,
                   'exposureTime': 16667,
                   'settings': {'target': 25, 'band': 15, 'costPerMile': 0.30,
                                'pad': 0, 'secondsPerItem': 0}}, fh)

    cam = FakeCam(offer, empty, appear_at=appear_at, vanish_at=vanish_at)
    started = []
    real_start, real_emit, real_sleep = SP.start_camera, SP.emit, time.sleep
    SP.start_camera = lambda *a, **k: (started.append(1), cam)[1]

    verdicts = []
    SP.emit = lambda *a, **k: (verdicts.append(a), real_emit(*a, **k))[1]

    argv = sys.argv
    sys.argv = ['scan_pi', '--config', config, '--json', '--snapshot', '',
                '--journal', journal] + list(extra_argv)
    deadline = time.time() + seconds

    def bounded_sleep(s):
        # The loop's own sleeps are how it yields; shortening them makes the
        # test quick, and raising at the deadline is how it is stopped, since
        # the loop is deliberately infinite.
        if time.time() > deadline:
            raise KeyboardInterrupt
        real_sleep(min(s, 0.01))

    time.sleep = bounded_sleep
    try:
        SP.main()
    except KeyboardInterrupt:
        pass
    finally:
        time.sleep = real_sleep
        sys.argv = argv
        SP.start_camera, SP.emit = real_start, real_emit

    rows = []
    if os.path.exists(journal):
        for line in open(journal):
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    ready = [v for v in verdicts if v and isinstance(v[0], dict) and v[0].get('ready')]
    return dict(cam=cam, rows=rows, ready=ready, config=config, journal=journal,
                started=len(started))


# --- a ride offer, end to end ----------------------------------------------
run_uberx = run(TC.uberx_screen(), extra_argv=['--no-parallel'])
cam = run_uberx['cam']

# The lifecycle first, because a leaked request stalls the camera a few frames
# later and everything after that is a symptom rather than the fault.
ok_('the camera was opened', run_uberx['started'] == 1)
ok_('the loop actually ran', cam.taken > 20)
eq('every capture request was given back', cam.outstanding, 0)
eq('...exactly once each', cam.double_released, 0)
eq('...and the totals agree', cam.given_back, cam.taken)
ok_('the camera was stopped on the way out', cam.stopped)

ok_('a verdict came out', len(run_uberx['ready']) > 0)
if run_uberx['ready']:
    rate, parsed = run_uberx['ready'][-1][0], run_uberx['ready'][-1][1]
    eq('...for the right payout', parsed['pay'], 16.05)
    # 3 + 20 minutes and 1.1 + 7.3 miles: a two-leg card with no total line,
    # which has to be summed rather than read off one line.
    eq('...with both legs summed', parsed['minutes'], 23.0)
    eq('...including the miles', parsed['miles'], 8.4)
    # Two rates, and which is which matters: `grossPerHour` is the offer's own
    # arithmetic and `perHour` is what is left after the car has been paid for.
    ok_('...and a gross rate that is just the card divided by the clock',
        abs(rate['grossPerHour'] - 16.05 / (23.0 / 60.0)) < 0.6)
    ok_('...and a net rate below it, because 8.4 miles cost something',
        0 < rate['perHour'] < rate['grossPerHour'])
    ok_('...by about the mileage cost',
        abs((rate['grossPerHour'] - rate['perHour'])
            - (8.4 * 0.30) / (23.0 / 60.0)) < 0.6)

# --- the journal -----------------------------------------------------------
rows = run_uberx['rows']
ok_('the offer was written down', len(rows) >= 1)
if rows:
    eq('one card is one offer, however many times it was read',
       len(set(r['id'] for r in rows)), 1)
    last = rows[-1]
    eq('the row carries the payout', last['pay'], 16.05)
    eq('...and the journey', (last['minutes'], last['miles']), (23.0, 8.4))
    ok_('...and is marked whole, since both legs were read', last.get('whole'))
    ok_('...and rows are numbered', last.get('seq', 0) >= 1)

# --- a shop order, which is a different shape of card ----------------------
run_shop = run(TC.shop_screen(), extra_argv=['--no-parallel'])
eq('the shop order also released every request', run_shop['cam'].outstanding, 0)
ok_('...and produced a verdict', len(run_shop['ready']) > 0)
if run_shop['ready']:
    parsed = run_shop['ready'][-1][1]
    eq('...off the total line', (parsed['pay'], parsed['minutes'], parsed['miles']),
       (7.09, 34.0, 3.6))
    eq('...with the item count', parsed['items'], 6.0)

# --- reading two frames at once, which is the default ----------------------
# The paired path has its own request handling — it takes a second capture
# outside the first one's `with` — so it is the one most likely to leak.
os.environ.setdefault('OMP_THREAD_LIMIT', '1')
run_paired = run(TC.uberx_screen(), seconds=7.0)
eq('the paired path releases every request too', run_paired['cam'].outstanding, 0)
eq('...exactly once each', run_paired['cam'].double_released, 0)
ok_('...and still reads the card', len(run_paired['ready']) > 0)

# --- an empty mount ---------------------------------------------------------
# No phone at all, for the whole run. Nothing should be recorded, nothing
# spoken, and the loop should neither crash nor leak.
run_empty = run(TC.uberx_screen(), seconds=4.0, appear_at=1e9, vanish_at=1e9,
                extra_argv=['--no-parallel'])
eq('an empty mount records no offers', len(run_empty['rows']), 0)
eq('...and leaks nothing', run_empty['cam'].outstanding, 0)
ok_('...and keeps running', run_empty['cam'].taken > 10)

# --- a dark-mode card, through the whole loop -------------------------------
run_dark = run(TC.uberx_screen(TC.DARK), extra_argv=['--no-parallel'])
eq('a dark-mode card leaks nothing', run_dark['cam'].outstanding, 0)
ok_('...and is read', len(run_dark['ready']) > 0)
if run_dark['ready']:
    parsed = run_dark['ready'][-1][1]
    eq('...to the same numbers as the light one',
       (parsed['pay'], parsed['minutes'], parsed['miles']), (16.05, 23.0, 8.4))

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d main-loop checks passed' % ok)
sys.exit(1 if bad else 0)
