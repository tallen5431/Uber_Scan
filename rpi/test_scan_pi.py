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
import re
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# The two windows live.html keys staleness on, read out of the page rather than
# copied into this file. A copy is a second place to remember, and the failure
# guarded against here is exactly two numbers in two files going out of step —
# which is what happened when the reader got twice as fast and the page's
# patience stayed where a slow one had put it.
def page_constant(name):
    page = open(os.path.join(ROOT, 'live.html')).read()
    found = re.search(r'\bvar\s+%s\s*=\s*(\d+)\s*;' % name, page)
    return int(found.group(1)) if found else None


PAGE_READ_STALE = page_constant('READ_STALE_MS')
PAGE_STALE = page_constant('STALE_MS')

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

    def __init__(self, offer, empty, appear_at=0.6, vanish_at=6.0, spoil=None):
        self.offer, self.empty = offer, empty
        self.appear_at, self.vanish_at = appear_at, vanish_at
        self.started = time.time()
        self.taken = self.given_back = self.outstanding = 0
        self.double_released = 0
        self.controls = []
        self.stopped = False
        # Something done to every frame on its way out, for the cases where what
        # is being tested is a bad picture rather than a bad card.
        self.spoil = spoil
        self.frames = 0
        self._show()

    def _show(self):
        t = time.time() - self.started
        self.frame = self.offer if self.appear_at <= t < self.vanish_at else self.empty
        if self.spoil is not None:
            self.frame = self.spoil(self.frame, self.frames)
        self.frames += 1
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
        until=None, look=None, spoil=None, config_extra=None):
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
    settings = {'quad': [[float(x), float(y)] for x, y in quad],
                'cardHeight': 900,
                'capture': {'width': CAP[0], 'height': CAP[1]},
                'lensPosition': 10.0,
                'exposureTime': 16667,
                'settings': {'target': 25, 'band': 15, 'costPerMile': 0.30,
                             'pad': 0, 'secondsPerItem': 0}}
    settings.update(config_extra or {})
    with open(config, 'w') as fh:
        json.dump(settings, fh)

    cam = FakeCam(offer, empty, appear_at=appear_at, vanish_at=vanish_at,
                  spoil=spoil)
    started = []
    real_start, real_emit, real_sleep = SP.start_camera, SP.emit, time.sleep
    real_look = PL.Scanner.look_many
    # ...and how the loop asks the motion gate, which is not the same question
    # as whether the gate works. The gate is confined to the phone by the scale
    # the loop hands it, and a loop that stops handing it over puts the mean
    # back over the whole cabin — where a dark-mode card scores below the
    # threshold and is never read. Mutating that call out left every suite
    # passing until this recorded it.
    gate_calls = []
    real_should = PL.Scanner.should_read

    def watched_should_read(self, frame, scale=None):
        gate_calls.append(scale)
        return real_should(self, frame, scale)

    PL.Scanner.should_read = watched_should_read
    SP.start_camera = lambda *a, **k: (started.append(1), cam)[1]
    # A stand-in for the OCR, when the case under test is one no rendering of a
    # real card can produce — a payout whose journey never reads, for one.
    if look is not None:
        PL.Scanner.look_many = look

    verdicts = []
    # Both halves of the call. `whole` travels as a keyword, so recording only
    # the positional arguments would have quietly asserted nothing about it —
    # which is exactly what the first version of this test did.
    SP.emit = lambda *a, **k: (verdicts.append((a, k)), real_emit(*a, **k))[1]
    # ...and which offer the loop says it has put on the record, which is what
    # the driving screen's "took it" button is named after and marks by.
    announced = []
    real_offer = SP.emit_offer
    SP.emit_offer = lambda *a, **k: (announced.append(a), real_offer(*a, **k))[1]

    argv = sys.argv
    sys.argv = ['scan_pi', '--config', config, '--json', '--snapshot', '',
                '--journal', journal] + list(extra_argv)
    deadline = time.time() + seconds

    def state():
        return dict(verdicts=verdicts,
                    # How many times the loop has reached a verdict, and how
                    # many times it has named the offer on record. A run that
                    # stops the instant a row lands cannot tell "once per card"
                    # from "once per read" — the loop gets one chance either
                    # way — so a test that means to check that has to be able
                    # to stop on the second announcement instead.
                    announced=len(announced),
                    reads=sum(1 for a, _ in verdicts
                              if a and isinstance(a[0], dict) and a[0].get('ready')),
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
        SP.emit_offer = real_offer
        PL.Scanner.look_many = real_look
        PL.Scanner.should_read = real_should

    rows = []
    if os.path.exists(journal):
        for line in open(journal):
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    ready = [a for a, _ in verdicts if a and isinstance(a[0], dict) and a[0].get('ready')]
    ready_kw = [k for a, k in verdicts if a and isinstance(a[0], dict) and a[0].get('ready')]
    return dict(cam=cam, rows=rows, ready=ready, ready_kw=ready_kw,
                announced=announced, gate_calls=gate_calls,
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

    # ...and the loop said which offer that is, so the driving screen can offer
    # to mark it as taken. Asserted against the *loop*, not against emit_offer
    # in isolation: the function returning the right shape proves nothing if
    # nothing calls it, which is exactly what a first version of this missed.
    # ...and the loop asked the gate about the phone, not about the cabin.
    #
    # test_pipeline proves the gate does the right thing when it is given the
    # scale. Only this proves the loop gives it: mutating `should_read(luma,
    # track_scale)` back to `should_read(luma)` left every other suite passing,
    # which is the shape of fault this project keeps finding — a function that
    # is right and a caller that never asks it.
    gate = run_uberx['gate_calls']
    ok_('the loop ran the motion gate', len(gate) > 1)
    ok_('...over the phone rather than the whole frame, every time',
        all(g is not None for g in gate))
    ok_('...naming how the preview maps onto the calibrated corners',
        all(isinstance(g, tuple) and len(g) == 2 and g[0] > 1 and g[1] > 1
            for g in gate))

    announced = run_uberx['announced']
    ok_('the loop announced the offer it recorded', len(announced) >= 1)
    if announced:
        eq('...by the journal\'s own id', announced[0][0], last['id'])
        eq('...with the payout the button will be named after',
           announced[0][1].get('pay'), 16.05)

# --- one card, held on screen, named once -----------------------------------
#
# The run above stops the instant a row lands, so it cannot tell "once per card"
# from "once per read": the loop gets exactly one chance either way. Removing
# the guard from scan_pi left it passing unchanged — a bound that passes rather
# than a bound that holds, which is the same fault this suite has caught in
# itself before.
#
# So hold the card up and stop on the evidence that would break it. Without the
# guard the second announcement ends the run and the count fails; with it, the
# run goes on until the card has been read several times over and the count is
# still one. The `reads` check is what keeps that honest — a card that is never
# re-read would satisfy the count for the wrong reason.
#
# It matters because the driving screen listens to this socket for verdicts. An
# announcement per read is a message a second arriving beside them, for a card
# that has not changed.
held = run(TC.uberx_screen(), seconds=75.0, extra_argv=['--no-parallel'],
           vanish_at=1e9,
           until=lambda st: st['announced'] >= 2 or st['reads'] >= 4)
ok_('a card that stays up is read again and again', len(held['ready']) >= 2)
eq('...and named once per card, not once per read', len(held['announced']), 1)
if held['announced'] and held['rows']:
    eq('...naming the row that was written',
       held['announced'][0][0], held['rows'][-1]['id'])

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
# renders one may fall over when it does. (`SP` is already imported above.)


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
# Still a real saving over the fast beat — 2.4 reads' worth rather than the 4.8
# it was. The ratio moved because the ceiling is derived from what a read costs
# and the fast beat is not: the reader got twice as quick, so the ceiling came
# down to hold the same duty cycle and the beat it backs off *from* stayed put.
ok_('...and the ceiling is a real saving over the fast beat',
    SP.VERIFY_MAX >= SP.VERIFY_EVERY * 2)
# ...and it is the read cost that sets it, not a number somebody liked.
ok_('the ceiling spends about a tenth of the time reading',
    0.08 <= SP.READ_SECONDS / SP.VERIFY_MAX <= 0.16)

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
    real_look, real_watch = PL.Scanner.look_many, SP.WATCH_PATHS
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
    # `watching()` reads the list, because the scanner also honours the old
    # location while a web server one `git pull` behind is still writing there.
    watch_here = os.path.join(work, '.viewing')
    SP.WATCH_PATHS = [watch_here]
    stop = _threading.Event()

    def keep_watching():
        while not stop.is_set():
            open(watch_here, 'w').close()
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
        PL.Scanner.look_many, SP.WATCH_PATHS = real_look, real_watch

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
    SP.emit_alive = lambda **kw: said.append(time.time())
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
        SP2.ALIVE_EVERY * 2 < PAGE_STALE / 1000.0)
    # ...and the two clocks still have to be separate. A heartbeat proves the
    # loop is turning; it proves nothing about the verdict on screen, which is
    # why a rig whose every read was failing went on showing the last ACCEPT.
    # That argument does not depend on which of the two windows is wider.
    ok_('...and a heartbeat is not a verdict',
        SP2.ALIVE_EVERY < SP2.VERIFY_MAX)

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

# --- a heartbeat is not a reading -----------------------------------------
# The loop says "still here" every four seconds so the page can tell a rig that
# is turning from one that has stopped. What it must NOT do is vouch for the
# verdict on screen: when every read is failing — a degenerate quad, a tesseract
# that died, a full disk — the loop keeps turning and keeps beating, and a page
# that measures verdict freshness on "any message" would hold the last ACCEPT at
# full strength over whatever card is actually in the mount. Measured before the
# fix: 50 reads attempted, 2 verdicts, 50 heartbeats, and nothing on screen
# admitting it.


def failing_look(self, frames, now=None, geom=None):
    raise RuntimeError('tesseract failed: degenerate quad')


beat_said, beat_reads = drive([], 9.0, look=failing_look)
ok_('a rig whose reads all fail still says it is alive', len(beat_said) >= 2)
eq('...but reports no verdict at all', len(beat_reads), 0)

# The page keys verdict freshness on READ_STALE_MS and liveness on STALE_MS, so
# the two constants have to leave room for a healthy verdict beat.
ok_('the page states how long a verdict stays fresh', PAGE_READ_STALE is not None)
ok_('...and how long the scanner may be quiet', PAGE_STALE is not None)

# The healthy worst case, from the scanner's own constants: a full backed-off
# beat with a read on the end of it.
healthy = SP2.VERIFY_MAX + SP2.READ_SECONDS
ok_('the verdict window clears a full verify beat and the read on the end of it',
    healthy < PAGE_READ_STALE / 1000.0)
# ...and is not so much larger that a stopped rig looks alive for a shift.
#
# A band, not a ceiling: a window under about 1.5x the healthy gap dims a
# working rig on a loaded Pi, and one over about 2.5x lets a stopped one look
# live for twice as long as it has to. The first version of this check used 3x
# and let the old 20s value through by a quarter of a second, which is a bound
# that passes rather than a bound that holds.
ok_('...with enough slack for a loaded Pi',
    PAGE_READ_STALE / 1000.0 > healthy * 1.5)
ok_('...without being wider than the fault it has to catch',
    PAGE_READ_STALE / 1000.0 < healthy * 2.5)
ok_('the heartbeat window clears a heartbeat, several times over',
    SP2.ALIVE_EVERY * 2 < PAGE_STALE / 1000.0)

# --- counting what went past ------------------------------------------------
# The one thing a journal can never contain is what is not in it. This is the
# nearest honest thing to a miss rate: a read that found a payout proves a card
# was in front of the camera, and an episode that ends with no row written is
# one the rig watched go past. It is a floor — an offer the reader never saw at
# all is invisible to this too — and everything that displays it says so.


def payout_only(self, frames, now=None, geom=None):
    """A payout, and a journey that never reads.

    rate() refuses an incomplete reading, so a card like this can never reach
    the journal however many times it is read. That is the miss this counter
    exists to surface, and it is unreachable through the camera: no rendering
    of a real card produces a payout with no journey for its whole life.
    """
    p = OP2.parse('$16.05')
    return [{'parsed': dict(p), 'rate': OP2.rate(p, {}), 'locked': True,
             'text': '$16.05', 'clipped': False, 'dropped': 0, 'recovered': 0,
             'crop': [0.0, 0.0, 1.0, 1.0], 'card': None,
             'ms': {'warp': 0, 'prep': 0, 'ocr': 0, 'parse': 0, 'total': 0}}
            for _ in frames]


def tally_over(look, seconds=22.0):
    """Run the loop with a blinking card and add up what it says it saw."""
    import scan_pi as SP
    real_every = SP.HEALTH_EVERY
    SP.HEALTH_EVERY = 3.0                  # so a short run reports at all
    try:
        rows = run(TC.uberx_screen(), seconds=seconds, appear_at=0.4,
                   vanish_at=10_000.0, look=look)['rows']
    finally:
        SP.HEALTH_EVERY = real_every
    seen = [r for r in rows if r.get('kind') == 'seen']
    offers = [r for r in rows if not r.get('kind')]
    return (sum(r.get('saw') or 0 for r in seen),
            sum(r.get('kept') or 0 for r in seen), len(offers))

saw, kept, offers = tally_over(None)
ok_('a card that reads is counted as seen', saw >= 1)
eq('...and as kept', kept, saw)
ok_('...and really did reach the journal', offers >= 1)

saw, kept, offers = tally_over(payout_only)
ok_('a payout that never becomes an offer is counted as seen', saw >= 1)
eq('...and not as kept', kept, 0)
eq('...which is the truth: nothing was written', offers, 0)

# A tally must not look like an offer to anything that reads offers. It carries
# a `kind`, which an offer never does — that one distinction is what lets the
# web side and the scanner write one file without either knowing about the
# other's rows, and a new kind has to keep it.
_mixed = run(TC.uberx_screen(), seconds=8.0, appear_at=0.4,
             vanish_at=10_000.0)['rows']
ok_('every row is either an offer or a kind, never both',
    all(bool(r.get('kind')) != ('pay' in r) for r in _mixed))
ok_('...and a tally carries the pair the sync keys on',
    all(r.get('id') and r.get('seq') for r in _mixed if r.get('kind') == 'seen'))

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

# --- a picture that never settles is still exposed for ----------------------
# This is the trap that used to close on a shift, and it closed because the two
# halves of it were written months apart and never read together.
#
# The exposure control was gated on `scanner.settled`. Shortening the exposure
# is what a blown-out card provokes. On a 60Hz phone the rung below the
# calibrated one is half a dimming cycle, so the screen ripples — and a rippling
# screen never settles: measured against the real motion gate, 8333us on a 60Hz
# panel reads 75.2 where the settle threshold is 2.0. So the branch that would
# have given the exposure back never ran again, `should_read` never fired
# either, and one nudge of the phone's brightness slider ended the shift with
# the loop still saying "still here" every four seconds.
#
# Simulated end to end before the fix: at twice the brightness the rig wedged
# after 19 seconds and managed one read in six minutes.
#
# Nothing in the exposure control ever needed a still picture. A percentile and
# a count of full-well pixels do not care whether the frame is moving.
def rippling(frame, n):
    """A screen beating against the shutter: bands that crawl between frames."""
    rows = np.arange(frame.shape[0], dtype=np.float32)
    wave = np.sin(rows / 3.0 + n * 1.7)[:, None, None] * 60.0
    return np.clip(frame.astype(np.float32) + wave, 0, 255).astype(np.uint8)


ripple_run = run(TC.uberx_screen(), seconds=30.0, spoil=rippling,
                 extra_argv=['--no-parallel'],
                 until=lambda st: False)
ripple_cam = ripple_run['cam']
gain_moves = [c for c in ripple_cam.controls if 'AnalogueGain' in c]
ok_('a rippling picture never settles — the fixture is doing its job',
    ripple_cam.frames > 50)
ok_('...and the exposure control still runs against it', len(gain_moves) >= 1)

# The same loop, on a picture that is both rippling and blown out: the state
# the rig used to lock itself into. What must not happen is that it sits there.
def blown_and_rippling(frame, n):
    return rippling(np.clip(frame.astype(np.float32) * 3.0, 0, 255).astype(np.uint8), n)


stuck_run = run(TC.uberx_screen(), seconds=30.0, spoil=blown_and_rippling,
                extra_argv=['--no-parallel'], until=lambda st: False)
moves = [c for c in stuck_run['cam'].controls if 'AnalogueGain' in c or 'ExposureTime' in c]
ok_('a blown, rippling picture is still acted on', len(moves) >= 2)
gains = [c['AnalogueGain'] for c in stuck_run['cam'].controls if 'AnalogueGain' in c]
ok_('...and the gain comes down rather than staying put',
    gains and min(gains) < 1.5)


# --- ...and only onto rungs this screen measured quiet ----------------------
# With a measured ladder that has nothing below the calibrated exposure — which
# is the truthful answer for a 60Hz phone — the rig may not shorten at all. The
# card stays a little bright, the screen does not ripple, and the driver is told
# the one thing that fixes it.
sixty = run(TC.uberx_screen(), seconds=30.0,
            spoil=lambda f, n: np.clip(f.astype(np.float32) * 3.0, 0, 255).astype(np.uint8),
            extra_argv=['--no-parallel'], until=lambda st: False,
            config_extra={'exposureLadder': [16667]})
exposures = [c['ExposureTime'] for c in sixty['cam'].controls if 'ExposureTime' in c]
ok_('a measured ladder with nothing shorter never shortens the exposure',
    all(e >= 16667 for e in exposures))

# --- which picture the live view is asking for -----------------------------
#
# One file carries both facts, because they expire together: a view nobody has
# asked for in ten seconds is not being watched, and there is no mode to honour.
# Getting that wrong in the safe direction costs a stale picture; getting it
# wrong the other way has the scanner buying a sensor frame ten times a second
# for a browser tab that was closed an hour ago.
watch = os.path.join(tempfile.mkdtemp(), '.viewing')
real_watch = SP.WATCH_PATHS
SP.WATCH_PATHS = [watch]
try:
    def asked_for(text, age=0.0):
        """Write the file as the server would, optionally already stale."""
        SP._watch_cache = (None, SP.VIEW_SCENE)     # a fresh process, not a cache hit
        with open(watch, 'w') as fh:
            fh.write(text)
        if age:
            os.utime(watch, (time.time() - age, time.time() - age))
        return SP.watching()

    eq('no file at all is nobody watching', SP.watching(), (False, SP.VIEW_SCENE))
    eq('the scene, asked for', asked_for('scene\n'), (True, SP.VIEW_SCENE))
    eq('the phone, asked for', asked_for('screen\n'), (True, SP.VIEW_SCREEN))
    # An older web side wrote this file empty. It must not read as a request for
    # the expensive picture.
    eq('an empty file is the view that has always been there',
       asked_for(''), (True, SP.VIEW_SCENE))
    eq('...and so is a word this side does not know',
       asked_for('holographic\n'), (True, SP.VIEW_SCENE))
    # A half-written file is reachable: the server truncates and rewrites in
    # place while this side may be reading.
    eq('...and so is half of one', asked_for('scr'), (True, SP.VIEW_SCENE))
    # The window is what makes the mode expire with the person watching.
    eq('a request nobody has renewed stops being one',
       asked_for('screen\n', age=SP.WATCH_WINDOW + 1), (False, SP.VIEW_SCENE))

    # Read once per camera frame, so up to thirty times a second, off the card.
    # The contents are cached against the mtime; a changed mtime must still be
    # picked up or switching views would never take effect.
    asked_for('screen\n')
    opened = []
    real_open = SP.open if hasattr(SP, 'open') else open
    import builtins
    real_builtin_open = builtins.open

    def counting_open(*a, **k):
        if a and a[0] == watch:
            opened.append(a[0])
        return real_builtin_open(*a, **k)

    builtins.open = counting_open
    try:
        for _ in range(20):
            SP.watching()
        eq('twenty looks at an unchanged file read it none', len(opened), 0)
        with open(watch, 'w') as fh:
            fh.write('scene\n')
        os.utime(watch, (time.time() + 0.01, time.time() + 0.01))
        eq('...and a changed one is picked up', SP.watching(), (True, SP.VIEW_SCENE))
    finally:
        builtins.open = real_builtin_open

    # The rate follows the view, because the phone view buys a sensor frame.
    eq('nobody watching is the idle tick',
       SP.snapshot_interval(SP.VIEW_SCENE, False), SP.SNAPSHOT_IDLE)
    eq('...whichever view was last asked for',
       SP.snapshot_interval(SP.VIEW_SCREEN, False), SP.SNAPSHOT_IDLE)
    eq('the scene runs fast', SP.snapshot_interval(SP.VIEW_SCENE, True), SP.SNAPSHOT_FAST)
    eq('the phone view runs slower, and pays for the sensor frame with it',
       SP.snapshot_interval(SP.VIEW_SCREEN, True), SP.SNAPSHOT_SCREEN)
    ok_('...which is slower, or it is not paying for anything',
        SP.SNAPSHOT_SCREEN > SP.SNAPSHOT_FAST)
finally:
    SP.WATCH_PATHS = real_watch


# --- and what gets written -------------------------------------------------
shot_dir = tempfile.mkdtemp()
shot = os.path.join(shot_dir, 'live.jpg')
big = np.full((1748, 2328, 3), 30, np.uint8)
big[300:1500, 700:1400] = 210
phone = np.float32([[700, 300], [1400, 300], [1400, 1500], [700, 1500]])
cfg_min = {'quad': phone.tolist(), 'cardHeight': 900}

SP.write_snapshot(big, cfg_min, shot, quad=phone, roi=None, view=SP.VIEW_SCENE)
scene_img = cv2.imread(shot)
eq('the scene view is the width it has always been', scene_img.shape[1], SP.SNAPSHOT_WIDTH)

SP.write_snapshot(big, cfg_min, shot, quad=phone, roi=None, view=SP.VIEW_SCREEN)
phone_img = cv2.imread(shot)
eq('the phone view is the height asked for', phone_img.shape[0], SP.SCREEN_HEIGHT)
ok_('...and holds a great deal more of the phone than the scene did',
    phone_img.shape[0] * phone_img.shape[1] > 8 * scene_img.shape[0] * scene_img.shape[1]
    * ((1400 - 700) * (1500 - 300)) / float(2328 * 1748))

# No corners is the case this has to survive rather than the case it is for:
# the phone out of frame, the mount knocked, the outline sitting on a
# reflection. Falling back to the scene shows the driver which of those it is.
SP.write_snapshot(big, cfg_min, shot, quad=phone - np.float32([9000, 0]), roi=None,
                  view=SP.VIEW_SCREEN)
eq('corners that have wandered off the frame fall back to the scene',
   cv2.imread(shot).shape[1], SP.SNAPSHOT_WIDTH)
# ...including when they came from the stored calibration rather than the
# tracker, which is the shape this takes when a rig is started with the phone
# not yet in the mount.
SP.write_snapshot(big, {'quad': (phone + np.float32([0, 9000])).tolist(),
                        'cardHeight': 900},
                  shot, quad=None, roi=None, view=SP.VIEW_SCREEN)
eq('...and so does a stored one that no longer points at anything',
   cv2.imread(shot).shape[1], SP.SNAPSHOT_WIDTH)
# It is a picture to read, so it is not written at the quality of a thumbnail.
ok_('the phone view is encoded for reading, not for glancing',
    SP.SCREEN_QUALITY > SP.SNAPSHOT_QUALITY)

# --- the rate the live view is actually published at ------------------------
#
# The snapshot is due-checked once per camera frame and nowhere else, so the
# only rates it can produce are the camera's divided by whole numbers: 30, 15,
# 10, 7.5 on the binned sensor. That is fine. What was not fine is which of
# them a request landed on.
#
# The check was a strict `elapsed > period`, and the frame that arrives exactly
# on the deadline is a hair early, so it was skipped and the next one — a whole
# camera frame late — was taken instead. Every rate therefore rounded *down* to
# the next achievable one: 15 asked for delivered 10.6, and 18, 20, 24 and 25
# all delivered 15.1, which made the flag close to meaningless above 15 and the
# default a third short of its own label.
#
# Simulated rather than driven through the loop, because what is being checked
# is the arithmetic of the due test and a real camera would only add jitter to
# it. The loop's own version of this is the frame-gap measurement above.
# --- the loop says a card is under the reader, before the verdict -----------
#
# A read is about 1.4 seconds on a Pi 4 and the dashboard spent every one of
# them saying WAITING FOR AN OFFER, which is what it says when the phone is
# blank. This is the one message that fills that gap, and everything about it
# has to stay incapable of standing in for a verdict.
def said(fn):
    out = io.StringIO()
    real, sys.stdout = sys.stdout, out
    try:
        fn()
    finally:
        sys.stdout = real
    return json.loads(out.getvalue())


heard = said(SP.emit_reading)
eq('the loop says when a read starts', heard.get('reading'), True)
ok_('...and stamps it', isinstance(heard.get('at'), int) and heard['at'] > 0)
# The whole safety property, and the same one the heartbeat has: the page keys
# every verdict off `ready`, so a message without it is dropped before it can
# replace one. A "reading" that carried `ready` would blank the last verdict on
# every card the driver is still looking at.
ok_('...carrying no verdict', 'ready' not in heard)
ok_('...and no numbers to mistake for one',
    not [k for k in heard if k in ('perHour', 'grossPerHour', 'pay', 'state')])

# --- and which offer it just put on the record ------------------------------
#
# The one fact the rig cannot observe is the driver pressing Accept, and it must
# never press it — so "I took this" is information only the driver has, and
# until now recording it meant opening the offers page afterwards and finding
# the row. This is the message that lets the driving screen offer the button:
# the journal's own id for the card just written.
told = said(lambda: SP.emit_offer('1700000000-1245',
                                  {'pay': 12.45, 'minutes': 28.0},
                                  {'ready': True, 'perHour': 20.51,
                                   'cardMinutes': 28.0}))
eq('the loop names the offer it recorded', told['offer']['id'], '1700000000-1245')
eq('...with the payout, so the button can say which', told['offer']['pay'], 12.45)
eq('...and the minutes it was judged over', told['offer']['minutes'], 28.0)
# The same safety property the heartbeat has, for the same reason: the page
# keys every verdict off `ready`, so a message without it is dropped before it
# can replace one. An id arriving after a card has gone must not resurrect a
# verdict for it.
ok_('...carrying no verdict', 'ready' not in told)
ok_('...and no state to be mistaken for one',
    not [k for k in told if k in ('state', 'doubt', 'grossPerHour')])

# The card's own minutes, not the billed ones. The button is named after what
# the driver saw on the phone; a figure with their pickup pad added would not
# match the card they are trying to remember.
padded = said(lambda: SP.emit_offer('x', {'pay': 12.45, 'minutes': 28.0},
                                    {'ready': True, 'perHour': 18.0,
                                     'cardMinutes': 28.0, 'minutes': 38.0}))
eq('the minutes are the card\'s, not the billed ones',
   padded['offer']['minutes'], 28.0)

CAMERA_TICK = 1.0 / 30.0


def publishes_at(fps, decide=None, seconds=10.0):
    """Frames a second actually produced, asking for `fps` on a 30fps sensor.

    Driven through the shipped decision rather than a copy of it, or this
    checks arithmetic nobody runs.
    """
    decide = decide or SP.snapshot_due
    period, last, n, t = 1.0 / fps, -1e9, 0, 0.0
    while t < seconds:
        if decide(t, last, period, CAMERA_TICK):
            last, n = t, n + 1
        t += CAMERA_TICK
    return n / seconds


def strictly_after(now, last, period, tick):
    """What the check used to be, for the comparison below."""
    return (now - last) > period


eq('asking for the sensor\'s own rate gets it', round(publishes_at(30)), 30)
eq('...and half of it', round(publishes_at(15)), 15)
eq('...and a third', round(publishes_at(10)), 10)
# The default the flag ships with has to be one the rig can actually hit, or
# the number in --help is a number nobody gets.
eq('the phone view\'s default is delivered, not approached',
   round(publishes_at(1.0 / SP.SNAPSHOT_SCREEN)), round(1.0 / SP.SNAPSHOT_SCREEN))
eq('...and so is the scene view\'s',
   round(publishes_at(1.0 / SP.SNAPSHOT_FAST)), 30)

# The fault itself, as it was: no slack means every rate rounds down.
ok_('without the slack, the asked-for rate is never reached (%.1f for 15)'
    % publishes_at(15, strictly_after), publishes_at(15, strictly_after) < 12)
ok_('...and four different requests collapse onto one rate',
    len({round(publishes_at(f, strictly_after)) for f in (18, 20, 24, 25)}) == 1)

# A rate the sensor cannot divide into is rounded to the nearest it can, rather
# than always downward — that is the whole of the change.
ok_('an unachievable rate lands on the nearest achievable one',
    publishes_at(24) > publishes_at(24, strictly_after))

# --- running out of light, in both directions -------------------------------
#
# The controller decides these (test_exposure.py) and the live page shows them
# (live.html); this is the wiring between, which is the part that silently does
# not exist. `too_dim` did not: the controller had no such idea, the health
# line had no such branch, and the heartbeat carried no such field, so a rig
# that had run out of light showed a dark picture and said nothing.
import contextlib                                             # noqa: E402
# `io` is already imported further up this file.


def health_line(**flags):
    """The line the log gets, with these flags set on it."""
    h = SP.Health()
    h.reset(0.0)
    h.reads = 1
    h.ms.append(200)          # report() takes a median of these
    for name, value in flags.items():
        setattr(h, name, value)
    grab = io.StringIO()
    with contextlib.redirect_stdout(grab):
        h.report(121.0, None, PL.Scanner(quad=None, roi=None))
    return grab.getvalue()


quiet = health_line()
ok_('an ordinary health line complains about neither end',
    'TOO DARK' not in quiet and 'OVER-EXPOSED' not in quiet)

dim = health_line(too_dim=True)
ok_('a rig out of light says so on the health line', 'TOO DARK' in dim)
ok_('...and says what to do about it', 'brightness up' in dim)

bright = health_line(too_bright=True)
ok_('a rig with too much light still says so', 'OVER-EXPOSED' in bright)
ok_('...and says the opposite thing to do', 'brightness down' in bright)

# The heartbeat is what the live page reads, and it is a separate path from the
# health line: a rig can be perfectly healthy in every other respect and still
# need the driver to touch their phone.
def beat(**flags):
    grab = io.StringIO()
    with contextlib.redirect_stdout(grab):
        SP.emit_alive(**flags)
    return json.loads(grab.getvalue().strip())


eq('the heartbeat carries both flags, false by default',
   (beat().get('tooBright'), beat().get('tooDim')), (False, False))
eq('...and true when they are', (beat(too_dim=True).get('tooDim'),
                                 beat(too_bright=True).get('tooBright')),
   (True, True))
# The page reads these by name off the heartbeat; a rename here is a notice
# that silently stops appearing.
page = open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'live.html')).read()
for field in ('tooBright', 'tooDim'):
    ok_('live.html reads %s off the heartbeat' % field,
        'msg.%s' % field in page)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d main-loop checks passed' % ok)
sys.exit(1 if bad else 0)
