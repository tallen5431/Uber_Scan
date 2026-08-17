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


def run(screen, seconds=9.0, extra_argv=(), appear_at=0.6, vanish_at=6.0,
        until=None):
    """Drive scan_pi.main() over a fake camera and collect what came out.

    `until(state)` ends the run as soon as the thing being tested has happened,
    with `seconds` only as a backstop. Stopping on evidence rather than on the
    clock is what makes this survive a loaded machine: a read that normally
    takes 250ms took 34 SECONDS while other work had the cores, the fixed
    deadline expired before the confirming read, and the suite failed for a
    reason that had nothing to do with the code.
    """
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
    # Both halves of the call. `whole` travels as a keyword, so recording only
    # the positional arguments would have quietly asserted nothing about it —
    # which is exactly what the first version of this test did.
    SP.emit = lambda *a, **k: (verdicts.append((a, k)), real_emit(*a, **k))[1]

    argv = sys.argv
    sys.argv = ['scan_pi', '--config', config, '--json', '--snapshot', '',
                '--journal', journal] + list(extra_argv)
    deadline = time.time() + seconds

    def state():
        return dict(verdicts=verdicts,
                    rows=(sum(1 for _ in open(journal))
                          if os.path.exists(journal) else 0))

    def bounded_sleep(s):
        # The loop's own sleeps are how it yields; shortening them makes the
        # test quick, and raising is how it is stopped, since the loop is
        # deliberately infinite.
        if time.time() > deadline:
            raise KeyboardInterrupt
        if until is not None and until(state()):
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
    ready = [a for a, _ in verdicts if a and isinstance(a[0], dict) and a[0].get('ready')]
    ready_kw = [k for a, k in verdicts if a and isinstance(a[0], dict) and a[0].get('ready')]
    return dict(cam=cam, rows=rows, ready=ready, ready_kw=ready_kw,
                config=config, journal=journal, started=len(started))


# --- a ride offer, end to end ----------------------------------------------
run_uberx = run(TC.uberx_screen(), seconds=90.0, extra_argv=['--no-parallel'],
                until=lambda st: st['rows'] >= 1)
cam = run_uberx['cam']

# The lifecycle first, because a leaked request stalls the camera a few frames
# later and everything after that is a symptom rather than the fault.
ok_('the camera was opened', run_uberx['started'] == 1)
# A floor rather than a count: the run now stops as soon as the offer is in the
# journal, so how many frames that took is a property of the machine and not of
# the code. What matters is that it looped at all, and then that every request
# it took came back — which is the next three checks.
ok_('the loop actually ran', cam.taken >= 3)
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

# --- the page has to be told when a reading is only half a card -------------
# `locked` means two consecutive frames parsed the same, which a fragment can
# satisfy perfectly: two frames that both lose the pickup leg to the same glare
# agree with each other. `whole` is the different and more useful claim, and it
# always errs the same way when it is missing — the same pay over less time
# reads as a better offer — so the page must get it rather than infer it.
kw = run_uberx['ready_kw']
ok_('every verdict is told whether the reading is whole',
    kw and all('whole' in k for k in kw))
ok_('...and this card, read in full, says so',
    kw and kw[-1].get('whole') is True)

import scan_pi as SP                                          # noqa: E402
import io                                                     # noqa: E402


def emitted(rate, parsed, whole):
    out = io.StringIO()
    real, sys.stdout = sys.stdout, out
    try:
        SP.emit(rate, parsed, {'total': 10}, True, whole=whole)
    finally:
        sys.stdout = real
    return json.loads(out.getvalue())


sample_rate = {'ready': True, 'state': 'go', 'perHour': 32.5, 'grossPerHour': 35.0,
               'minutes': 19.0, 'perMile': 1.2, 'cost': 0.5, 'costPerMile': 0.3}
sample_parsed = {'pay': 10.30, 'minutes': 19.0, 'miles': 8.5, 'items': None,
                 'milesCorrected': False, 'milesUncertain': False,
                 'text': '', 'legs': 1, 'mergedFrom': 1}
eq('a fragment is reported as not whole',
   emitted(sample_rate, sample_parsed, False)['whole'], False)
eq('...and a finished reading as whole',
   emitted(sample_rate, sample_parsed, True)['whole'], True)
eq('...and a caller that does not say leaves it unstated',
   emitted(sample_rate, sample_parsed, None)['whole'], None)

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
run_shop = run(TC.shop_screen(), seconds=90.0, extra_argv=['--no-parallel'],
               until=lambda st: st['rows'] >= 1)
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
run_paired = run(TC.uberx_screen(), seconds=90.0,
                 until=lambda st: st['rows'] >= 1)
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

# --- one offer replaced by another, with no gap between them ----------------
# The motion gate cannot see this. It compares whole frames as a mean absolute
# difference, and two cards of the same layout with different numbers score
# 0.33 against a threshold of 6.0 — so without a slow re-read the verdict on
# screen stays with the card that is no longer there, which is a confident
# number about a different job.
class SwappingCam(FakeCam):
    def __init__(self, first, second, empty, swap_at=4.0):
        self.second = second
        self.swap_at = swap_at
        FakeCam.__init__(self, first, empty, appear_at=0.6, vanish_at=1e9)

    def _show(self):
        t = time.time() - self.started
        if t < self.appear_at:
            self.frame = self.empty
        else:
            self.frame = self.second if t >= self.swap_at else self.offer
        grey = cv2.cvtColor(self.frame, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(grey, LORES, interpolation=cv2.INTER_AREA)
        self.lores = np.concatenate([small.ravel(),
                                     np.full(LORES[0] * LORES[1] // 2, 128, np.uint8)])


def run_swap(seconds=120.0):
    import scan_pi as SP
    # The same layout with different figures, which is the case the motion
    # gate is blind to. Swapping one card *type* for another proves nothing:
    # a different layout is a change the gate spots easily.
    first = TC.mount(TC.uberx_screen(), 1200)
    second = TC.mount(TC.uberx_screen(pay='$8.20', trip=('12', '3.1')), 1200)
    empty = TC.blank()
    quad = PL.detect_screen_quad(first)
    workdir = tempfile.mkdtemp()
    config = os.path.join(workdir, 'config.json')
    journal = os.path.join(workdir, 'journal.jsonl')
    with open(config, 'w') as fh:
        json.dump({'quad': [[float(x), float(y)] for x, y in quad],
                   'cardHeight': 900,
                   'capture': {'width': CAP[0], 'height': CAP[1]},
                   'lensPosition': 10.0, 'exposureTime': 16667,
                   'settings': {'target': 25, 'band': 15, 'costPerMile': 0.30,
                                'pad': 0, 'secondsPerItem': 0}}, fh)
    cam = SwappingCam(first, second, empty, swap_at=4.5)
    real_start, real_emit, real_sleep = SP.start_camera, SP.emit, time.sleep
    SP.start_camera = lambda *a, **k: cam
    seen = []
    SP.emit = lambda *a, **k: (seen.append(a), real_emit(*a, **k))[1]
    argv = sys.argv
    sys.argv = ['scan_pi', '--config', config, '--json', '--snapshot', '',
                '--no-parallel', '--journal', journal]
    deadline = time.time() + seconds

    def paid():
        return [a[1]['pay'] for a in seen
                if a and isinstance(a[0], dict) and a[0].get('ready')]

    def bounded_sleep(s):
        # Stop once the second card has been seen, not after a fixed stretch of
        # clock — the swap is scheduled in wall time and a loaded machine can
        # spend all of it inside one read.
        if time.time() > deadline:
            raise KeyboardInterrupt
        if 8.20 in paid():
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
    return cam, paid()


swap_cam, swap_pays = run_swap()
eq('the swap run leaks nothing', swap_cam.outstanding, 0)
ok_('the first offer was read', 16.05 in swap_pays)
ok_('...and so was the one that replaced it, with no gap between them',
    8.20 in swap_pays)
ok_('...and the last word is the card actually on screen',
    swap_pays and swap_pays[-1] == 8.20)

# --- a dark-mode card, through the whole loop -------------------------------
run_dark = run(TC.uberx_screen(TC.DARK), seconds=90.0, extra_argv=['--no-parallel'],
               until=lambda st: st['rows'] >= 1)
eq('a dark-mode card leaks nothing', run_dark['cam'].outstanding, 0)
ok_('...and is read', len(run_dark['ready']) > 0)
if run_dark['ready']:
    parsed = run_dark['ready'][-1][1]
    eq('...to the same numbers as the light one',
       (parsed['pay'], parsed['minutes'], parsed['miles']), (16.05, 23.0, 8.4))

# --- what the driver is shown and told --------------------------------------
# These had no checks at all, and adding a fourth verdict to the parser broke
# both of them at once: two dictionary lookups indexed with `[...]` on a state
# they had never been taught. Not a wrong colour — a KeyError, raised inside the
# scan loop, on the first misread card of a shift.
#
# Neither lives in a file the parser's own tests touch, which is the whole point
# of checking them here: the parser is free to grow a state, and nothing that
# renders one may fall over when it does.
import scan_pi as SP                                           # noqa: E402


def _rate(state, per_hour=30.0, why=None):
    return {'ready': True, 'state': state, 'perHour': per_hour, 'doubt': why}


_card = {'pay': 12.51, 'minutes': 20.0, 'miles': 4.2}

for _state in ('go', 'warn', 'no', 'doubt', 'empty', 'something-new'):
    try:
        _panel = SP.render_panel(_rate(_state, why='pay' if _state == 'doubt' else None),
                                 _card)
        eq('the panel draws a %s verdict' % _state, _panel.shape, (480, 800, 3))
    except Exception as e:                                     # noqa: BLE001
        eq('the panel draws a %s verdict' % _state, 'raised %r' % e, 'drawn')

eq('a card with nothing on it is still a panel',
   SP.render_panel({'ready': False, 'state': 'empty'}, _card).shape, (480, 800, 3))

# The doubt panel must not put the rate on the screen. $1184 over twenty minutes
# is $3548/hr, and at that size it is the most convincing thing on the rig.
_doubt = SP.render_panel(_rate('doubt', 3548.49, 'pay'),
                         {'pay': 1184.0, 'minutes': 20.0, 'miles': 3.9})
_go = SP.render_panel(_rate('go', 3548.49), {'pay': 1184.0, 'minutes': 20.0, 'miles': 3.9})
ok_('a doubted card is not drawn like an accepted one',
    not np.array_equal(_doubt, _go))

# And the voice, which is the whole of what a driver gets while watching the
# road. "accept, three thousand five hundred an hour" was what this said.
eq('an ordinary offer is priced', SP.spoken(_rate('go', 31.4)), 'accept. 31 an hour.')
eq('a close one too', SP.spoken(_rate('warn', 22.0)), 'close. 22 an hour.')
eq('a poor one too', SP.spoken(_rate('no', 8.0)), 'pass. 8 an hour.')
eq('a lost decimal point is named, not priced',
   SP.spoken(_rate('doubt', 3548.49, 'pay')), 'check the pay.')
eq('...and so is a misread time', SP.spoken(_rate('doubt', 90.0, 'time')),
   'check the time.')
eq('...and a misread distance', SP.spoken(_rate('doubt', 90.0, 'speed')),
   'check the distance.')
ok_('a doubt this build has no words for still says something',
    SP.spoken(_rate('doubt', 90.0, 'newer-reason')))
ok_('...and never says a number',
    '90' not in SP.spoken(_rate('doubt', 90.0, 'newer-reason')))

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d main-loop checks passed' % ok)
sys.exit(1 if bad else 0)
