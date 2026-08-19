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

# --- a clock that has not been set ------------------------------------------
# A Pi 4 has no real-time clock: with no network it boots in 1970 and jumps
# forward whenever it first reaches an NTP server, which in a car may be minutes
# into a shift or never. That did not matter until a delivery card's duration
# started coming from "Deliver by 7:15 PM" minus the current time — where an
# hour of skew turns a 45-minute job into a 105-minute one, or into a deadline
# already passed that wraps to twenty-three hours, and the verdict looks exactly
# as confident either way.
eq('a clock still in 1970 is not used', SP.clock_minutes(0), None)
eq('...nor one an hour into 1970', SP.clock_minutes(3600), None)
ok_('...but a real one is', SP.clock_minutes() is not None)
ok_('...and reads as minutes since midnight',
    0 <= (SP.clock_minutes() or -1) < 24 * 60)

# The consequence, end to end: with no believable clock a delivery card has no
# duration, so it gets no verdict — which is the right answer for an offer whose
# length nothing here knows.
import offer_parser as OP2                                     # noqa: E402
_dd = OP2.parse('$41.11 Guaranteed 9.8 mi Deliver by 7:15 PM Pickup Papa Johns')
eq('a delivery card is complete on its own', _dd['complete'], True)
eq('...but unjudged without a clock',
   OP2.rate(_dd, {'target': 25, 'costPerMile': 0.3})['ready'], False)
eq('...and judged with one',
   OP2.rate(_dd, {'target': 25, 'costPerMile': 0.3,
                  'nowMinutes': 18 * 60 + 29})['ready'], True)
# A ride card states its own minutes and is unaffected either way.
_ride = OP2.parse('$16.05 3 min (1.1 mi) away 20 min (7.3 mi) trip')
eq('a ride card needs no clock',
   OP2.rate(_ride, {'target': 25, 'costPerMile': 0.3})['ready'], True)

# --- how often to look again at a card that is not changing -----------------
# The slow beat exists because a replacement offer does not move the motion
# gate, so the only way to notice one is to look. But a read is 1.4 seconds of
# a Pi 4, 91% of it inside tesseract, and one real recording spends seventy of
# those seconds re-reading a card that says the same thing every time.
#
# So the beat backs off while nothing changes. What must not break is the case
# it was written for: a reading that comes back different is looked at again at
# the fast beat, no matter how patient the loop had become.
A, B = ('$10.30', 31, 15.1), ('$8.75', 20, 6.1)

every, sig = SP.next_verify(SP.VERIFY_EVERY, None, A, True)
eq('the first sight of a card sets the fast beat', every, SP.VERIFY_EVERY)
eq('...and remembers what it said', sig, A)

every, sig = SP.next_verify(every, sig, A, True)
ok_('the same answer again earns a longer wait', every > SP.VERIFY_EVERY)
first_backoff = every
for _ in range(20):
    every, sig = SP.next_verify(every, sig, A, True)
eq('...but only up to a ceiling', every, SP.VERIFY_MAX)
ok_('...which is reached in a handful of reads, not one',
    first_backoff < SP.VERIFY_MAX)

# The whole point: patience is not paid for by the offer that replaces this one.
every, sig = SP.next_verify(every, sig, B, True)
eq('a different reading drops straight back to the fast beat',
   every, SP.VERIFY_EVERY)
eq('...and it is the new reading that is remembered', sig, B)

# An empty screen is not a card saying the same thing. Coming back to the fast
# beat here is what makes the next offer's first look prompt.
every, sig = SP.next_verify(SP.VERIFY_MAX, A, None, False)
eq('an empty screen resets the beat', every, SP.VERIFY_EVERY)
eq('...and forgets the card that was there', sig, None)
every, sig = SP.next_verify(every, sig, A, True)
eq('...so a card appearing is read at the fast beat', every, SP.VERIFY_EVERY)

# Worst case, stated as a number: how long a replacement offer can sit unread.
ok_('a stale verdict cannot outlive the ceiling', SP.VERIFY_MAX <= 15.0)
ok_('...and the ceiling is a real saving over the fast beat',
    SP.VERIFY_MAX >= SP.VERIFY_EVERY * 3)

# --- the reader, on its own ------------------------------------------------
# The queue between the loop and the OCR. Checked apart from the loop because
# the interesting cases are the ones a camera cannot produce: a read that
# throws, a reader closed with work still inside it, a thread left behind.
import scan_pi as SPR                                          # noqa: E402
import threading as _threading                                 # noqa: E402


class StubScanner(object):
    """Stands in for the Scanner: records what it was asked, answers slowly."""

    def __init__(self, hold=0.0, blow_up=False):
        self.hold, self.blow_up = hold, blow_up
        self.seen = []
        self.settled = []

    def look_many(self, frames, now=None, geom=None):
        if self.hold:
            time.sleep(self.hold)
        if self.blow_up:
            raise RuntimeError('tesseract fell over')
        self.seen.append((list(frames), geom))
        return [{'parsed': {'pay': f}, 'dropped': 0, 'recovered': 0} for f in frames]

    def settle(self, outs, geom=None):
        self.settled.append(outs)
        return outs


def wait_for(reader, tries=300):
    for _ in range(tries):
        done = reader.take()
        if done is not None:
            return done
        time.sleep(0.02)
    return None


for threaded in (False, True):
    how = 'beside the loop' if threaded else 'on the loop'
    stub = StubScanner()
    r = SPR.Reader(stub, threaded=threaded)
    ok_('%s: idle to begin with' % how, not r.busy)
    eq('%s: nothing to take yet' % how, r.take(), None)

    r.submit(['a', 'b'], 1.0, 'geom')
    ok_('%s: busy once handed work' % how, r.busy)
    done = wait_for(r)
    ok_('%s: the read comes back' % how, done is not None)
    eq('%s: ...with a reading per frame' % how, len(done['outs']), 2)
    eq('%s: ...against the geometry it was given' % how, stub.seen[0][1], 'geom')
    eq('%s: ...and the frames, for whoever wants the picture' % how,
       done['frames'], ['a', 'b'])
    eq('%s: ...folded back on this thread, once' % how, len(stub.settled), 1)
    ok_('%s: free again' % how, not r.busy)
    r.close()

    # A read that throws comes back as a result, not as an exception. The
    # engine is external, and a rig that dies on one bad frame costs the
    # supervisor's backoff and a minute of not scanning.
    boom = SPR.Reader(StubScanner(blow_up=True), threaded=threaded)
    boom.submit(['a'], 1.0, None)
    done = wait_for(boom)
    ok_('%s: a read that throws still comes back' % how, done is not None)
    ok_('%s: ...carrying the failure' % how, isinstance(done['error'], RuntimeError))
    eq('%s: ...and no reading' % how, done['outs'], None)
    ok_('%s: ...leaving the reader free for the next frame' % how, not boom.busy)
    boom.close()


class Stopped(StubScanner):
    """A read interrupted by Ctrl-C, or by the SIGTERM handler's SystemExit."""

    def __init__(self, how):
        StubScanner.__init__(self)
        self.how = how

    def look_many(self, frames, now=None, geom=None):
        raise self.how


# Those two are not failed reads and must not be reported as ones.
#
# Under --no-thread the read runs on the loop's own thread, and a read is over
# a second long, so a stop signal usually lands inside it. Swallowed, the log
# says "read failed: SystemExit" once, the rate limiter silences every one
# after it, and the rig keeps holding the camera until the supervisor gives up
# and SIGKILLs it — skipping the cleanup that handler exists to run. Ctrl-C
# does nothing at all, silently, which is worse.
for how in (KeyboardInterrupt, SystemExit):
    name = how.__name__
    inline = SPR.Reader(Stopped(how()), threaded=False)
    got = 'swallowed'
    try:
        inline.submit(['a'], 1.0, None)
    except how:
        got = 'raised'
    eq('on the loop, %s is a stop and not a read failure' % name, got, 'raised')
    inline.close()

    # On the reader thread there is nothing above it to unwind to, and letting
    # it out would kill the reader — leaving the rig alive and never reading
    # again, which is the worst failure this project has.
    off = SPR.Reader(Stopped(how()), threaded=True)
    off.submit(['a'], 1.0, None)
    done = wait_for(off)
    ok_('...but beside the loop it is reported, not thrown', done is not None)
    ok_('...and the reader lives to read again', not off.busy)
    off.close()

# Closing waits for a read already in flight — that is deliberate, so nothing
# is still writing while the next process starts — but the wait is bounded, and
# the thread must be gone at the end of it. The rig is restarted on every crash,
# and a strand of leftover readers is how a Pi runs out of memory overnight.
before = _threading.active_count()
slow = SPR.Reader(StubScanner(hold=1.5), threaded=True)
slow.submit(['a'], 1.0, None)
time.sleep(0.1)
t0 = time.time()
slow.close()
spent = time.time() - t0
ok_('closing waits for the read in flight', spent > 1.0)
ok_('...but not indefinitely', spent < 3.5)
for _ in range(120):
    if _threading.active_count() <= before:
        break
    time.sleep(0.05)
eq('...and leaves no thread behind', _threading.active_count(), before)

# --- the live view does not stop while a card is being read -----------------
# The whole point of moving the read off the loop, stated as the property
# rather than as a number: how long the picture goes without a new frame must
# not depend on how long a read takes. A read is ~1.4s on a Pi 4, and the
# picture is what the driver is looking at to decide whether to press Accept.


class BlinkCam(FakeCam):
    """The card comes and goes, so the gate keeps firing."""

    def __init__(self, offer, empty, period=1.6):
        self.period = period
        FakeCam.__init__(self, offer, empty)

    def _show(self):
        t = time.time() - self.started
        self.frame = self.offer if (t % self.period) < self.period / 2 else self.empty
        grey = cv2.cvtColor(self.frame, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(grey, LORES, interpolation=cv2.INTER_AREA)
        self.lores = np.concatenate([small.ravel(),
                                     np.full(LORES[0] * LORES[1] // 2, 128, np.uint8)])


def worst_frame_gap(extra_argv, hold, seconds=9.0):
    """Longest gap between live-view frames, with a read forced to take `hold`."""
    import scan_pi as SP

    offer = TC.mount(TC.uberx_screen(), 1200)
    quad = PL.detect_screen_quad(offer)
    work = tempfile.mkdtemp()
    config = os.path.join(work, 'config.json')
    with open(config, 'w') as fh:
        json.dump({'quad': [[float(x), float(y)] for x, y in quad],
                   'cardHeight': 900,
                   'capture': {'width': CAP[0], 'height': CAP[1]},
                   'lensPosition': 10.0, 'exposureTime': 16667,
                   'settings': {'target': 25, 'band': 15, 'costPerMile': 0.30}}, fh)

    # Blinking, not a single appearance: the motion gate fires on the frame a
    # moving picture settles, so one appearance is one read, and one read lands
    # inside the warm-up and is not there to be measured.
    cam = BlinkCam(offer, TC.blank(), period=1.6)
    stamps = []
    real_start, real_snap = SP.start_camera, SP.write_snapshot
    real_sleep = time.sleep
    real_look, real_watch = PL.Scanner.look_many, SP.WATCH_PATH
    empty = OP2.parse('')

    def slow_look(self, frames, now=None, geom=None):
        # A read of a known duration and nothing else. What is being measured
        # is the loop around it, so the OCR is exactly what must not run.
        real_sleep(hold)
        return [{'parsed': dict(empty), 'rate': OP2.rate(empty, {}), 'locked': False,
                 'text': '', 'clipped': False, 'dropped': 0, 'recovered': 0,
                 'crop': [0.0, 0.0, 1.0, 1.0], 'card': None,
                 'ms': {'warp': 0, 'prep': 0, 'ocr': 0, 'parse': 0, 'total': 0}}
                for _ in frames]

    SP.start_camera = lambda *a, **k: cam
    SP.write_snapshot = lambda *a, **k: stamps.append(time.time())
    PL.Scanner.look_many = slow_look
    # "Someone is watching" goes stale after ten seconds, and what would then
    # be measured is the idle interval rather than the read.
    SP.WATCH_PATH = os.path.join(work, '.viewing')
    stop = _threading.Event()

    def keep_watching():
        while not stop.is_set():
            open(SP.WATCH_PATH, 'w').close()
            real_sleep(0.5)

    watcher = _threading.Thread(target=keep_watching, daemon=True)
    watcher.start()

    argv, deadline = sys.argv, time.time() + seconds
    sys.argv = ['scan_pi', '--config', config, '--json', '--no-journal',
                '--snapshot', os.path.join(work, 'live.jpg')] + list(extra_argv)

    def bounded(s):
        if time.time() > deadline:
            raise KeyboardInterrupt
        real_sleep(min(s, 0.01))

    time.sleep = bounded
    try:
        SP.main()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        time.sleep, sys.argv = real_sleep, argv
        SP.start_camera, SP.write_snapshot = real_start, real_snap
        PL.Scanner.look_many, SP.WATCH_PATH = real_look, real_watch

    # The first stretch is camera setup and screen detection, which is not what
    # is being judged.
    if len(stamps) < 6:
        return None
    live = [t for t in stamps if t >= stamps[0] + 1.5]
    gaps = [b - a for a, b in zip(live, live[1:])]
    return max(gaps) if gaps else None


HOLD = 1.2
on_loop = worst_frame_gap(['--no-thread'], HOLD)
beside = worst_frame_gap([], HOLD)
if on_loop is None or beside is None:
    print('the live-view timing run produced too few frames — skipping those checks')
else:
    ok_('a read on the loop stops the live view for as long as it takes',
        on_loop > HOLD * 0.8)
    ok_('...and a read beside it does not stop the picture at all',
        beside < HOLD * 0.35)
    ok_('...by a wide margin, not a whisker', beside * 3 < on_loop)

import scan_pi as SP2                                          # noqa: E402
RESAMPLE_SETTLE = 5.0

# --- the loop says it is alive, whether or not it has anything to report -----
# The driving page decides the scanner has stopped when it has heard nothing for
# STALE_MS. It used to infer that from readings, and neither half of the
# reasoning held: a still picture moves the motion gate not at all, so between
# offers there can be minutes with no read; and a card sitting unchanged has its
# verify beat back off to VERIFY_MAX, so with a read on the end of it the silence
# exceeds twelve seconds. The page would dim the verdict and say the rig had
# stopped at the moment the driver was reading it to decide.


def drive(extra_argv, seconds, look=None, appear_at=0.4):
    """Run the real main() over a fake camera. Returns when every message came.

    `look` stands in for the OCR so a run can be about the loop rather than
    about tesseract. Returns (message times, read times) in seconds.
    """
    import scan_pi as SP

    offer = TC.mount(TC.uberx_screen(), 1200)
    quad = PL.detect_screen_quad(offer)
    work = tempfile.mkdtemp()
    config = os.path.join(work, 'config.json')
    with open(config, 'w') as fh:
        json.dump({'quad': [[float(x), float(y)] for x, y in quad],
                   'cardHeight': 900,
                   'capture': {'width': CAP[0], 'height': CAP[1]},
                   'lensPosition': 10.0, 'exposureTime': 16667,
                   'settings': {'target': 25, 'band': 15, 'costPerMile': 0.30}}, fh)

    cam = FakeCam(offer, TC.blank(), appear_at=appear_at, vanish_at=10_000.0)
    said, reads = [], []
    real_start, real_emit, real_alive = SP.start_camera, SP.emit, SP.emit_alive
    real_sleep = time.sleep
    real_look = PL.Scanner.look_many

    SP.start_camera = lambda *a, **k: cam
    SP.emit = lambda *a, **k: (said.append(time.time()), reads.append(time.time()))
    SP.emit_alive = lambda: said.append(time.time())
    if look is not None:
        PL.Scanner.look_many = look

    argv, deadline = sys.argv, time.time() + seconds
    sys.argv = ['scan_pi', '--config', config, '--json', '--no-journal',
                '--snapshot', ''] + list(extra_argv)

    def bounded(s):
        if time.time() > deadline:
            raise KeyboardInterrupt
        real_sleep(min(s, 0.01))

    time.sleep = bounded
    try:
        SP.main()
    except KeyboardInterrupt:
        pass
    finally:
        time.sleep, sys.argv = real_sleep, argv
        SP.start_camera, SP.emit, SP.emit_alive = real_start, real_emit, real_alive
        PL.Scanner.look_many = real_look
    return said, reads


def one_plain_leg(self, frames, now=None, geom=None):
    """A card with a payout and a single leg that is not a total.

    Never `whole`, so the resample burst's stopping condition is never met —
    which is the shape that used to pin the reader at two reads a second for as
    long as the card was on the screen. Eight of the owner's 245 rows are it.
    """
    parsed = OP2.parse('$16.05 20 min (7.3 mi) trip')
    return [{'parsed': dict(parsed), 'rate': OP2.rate(parsed, {'target': 25}),
             'locked': True, 'text': '', 'clipped': False, 'dropped': 0,
             'recovered': 0, 'crop': [0.0, 0.0, 1.0, 1.0], 'card': None,
             'ms': {'warp': 0, 'prep': 0, 'ocr': 0, 'parse': 0, 'total': 0}}
            for _ in frames]


# Judged on a blank screen, which is where the rig spends most of a shift and
# where the old reasoning fails hardest: a still picture moves the motion gate
# not at all, so there are no reads to infer life from and the silence is
# unbounded. The card never appears in this run.
QUIET_RUN = 9.0
quiet_said, _ = drive([], QUIET_RUN, appear_at=10_000.0)

# Asserted, not guarded. Producing almost nothing over nine seconds of blank
# screen IS the fault, so a run that is too short to measure must fail here
# rather than skip — which is what it did the first time this was written, and
# a check that goes quiet exactly when the thing it watches does is no check.
ok_('a rig with nothing to report still reports',
    len(quiet_said) >= int(QUIET_RUN / SP2.ALIVE_EVERY))
if len(quiet_said) >= 2:
    quiet = max(b - a for a, b in zip(quiet_said, quiet_said[1:]))
    ok_('...and is never silent for as long as the page waits', quiet * 1000 < 12000)
    ok_('...keeping its own beat rather than the reader\'s',
        quiet < SP2.ALIVE_EVERY * 2)

said, reads = drive([], 9.0, look=one_plain_leg)
if len(said) < 3:
    print('the resample run produced too little to judge — skipping those checks')
else:

    # The constants have to be checked against each other, not just observed:
    # the page's patience must clear a full verify beat plus the read on the end
    # of it, or the fix above is one slow read away from coming back.
    ok_('the heartbeat is well inside the page\'s patience',
        SP2.ALIVE_EVERY * 2 < 12.0)
    ok_('...and the verify ceiling alone would not have been',
        SP2.VERIFY_MAX + 1.4 > 12.0)

    # --- and the burst is armed once per card, not once per read ------------
    # Each read inside the resample burst used to push its end four seconds
    # further out, so a card that never reads whole held the reader at one read
    # every half second for as long as it was on screen — the opposite of what
    # the verify beat's backoff is for, and it won, because it is checked first.
    settled = [t for t in reads if t > reads[0] + RESAMPLE_SETTLE]
    span = (reads[-1] - reads[0] - RESAMPLE_SETTLE) if len(reads) > 1 else 0
    if span > 2.0:
        rate = len(settled) / span
        ok_('a card that never reads whole stops being re-read every half second',
            rate < 1.0 / SP2.RESAMPLE_EVERY * 0.6)
        ok_('...though it is still looked at now and then', len(settled) >= 1)

# --- a fault that comes back is said again --------------------------------
# The read-failure log is rate limited by message, and it never cleared that
# message on a good read — so a fault that recurred an hour later matched the
# suppressed one and was silent for the rest of the shift. A disk that filled,
# was emptied and filled again would say so exactly once, in the morning.
SPR._read_error = None
SPR._read_failed(RuntimeError('disk full'))
SPR._read_failed(RuntimeError('disk full'))
eq('the same fault twice running is remembered once',
   SPR._read_error, 'RuntimeError: disk full')
SPR._read_ok()
eq('a good read forgets it', SPR._read_error, None)
SPR._read_failed(RuntimeError('disk full'))
eq('...so its return is reported rather than suppressed',
   SPR._read_error, 'RuntimeError: disk full')

# --- and the health line still speaks when every read is failing -----------
# The guard was `not self.reads`, which is exactly true when the reader is
# broken: the two-minute summary went quiet at the moment it had the most to
# say, and the log's last word was one suppressed failure line.
said = []
real_log = SPR.log
SPR.log = lambda m: said.append(m)
try:
    h = SPR.Health()
    h.reset(0.0)
    h.failed = 12
    h.report(SPR.HEALTH_EVERY + 1, None, None)
finally:
    SPR.log = real_log
ok_('a health line appears even with no successful read', len(said) == 1)
ok_('...and says every read failed', 'ALL FAILED' in (said[0] if said else ''))
ok_('...and how many', '12' in (said[0] if said else ''))

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d main-loop checks passed' % ok)
sys.exit(1 if bad else 0)
