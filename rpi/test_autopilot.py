"""The one command that takes the rig from nothing to scanning.

    python3 rpi/test_autopilot.py

`autopilot.py` is what the systemd unit starts, what the web server spawns, and
what the README tells a driver to run. It had no test. The pieces it is made of
were each covered and the decision they add up to was not, which is the wrong
way round: it is a decision table that only runs on the rig, at boot, with
nobody watching, and one of its branches used to brick the machine.

That branch: a `config.json` that existed and did not parse. The
already-calibrated test was "does the file exist", so an unreadable one was
treated as good, the scanner was started against it, `json.load` threw, the
supervisor restarted it, and the only repair was ssh. Fixed by asking whether
the file reads back as an object — and nothing anywhere held it to that.

The camera is never opened here. `check`, `aim`, `calibrate_from` and `scan` are
each replaced with something that records being called, which leaves exactly the
branching, the ordering and the arguments — and those are the parts that were
never checked. `scan` really does `os.execv` in life, so it is the one that must
be stubbed even to reach the end of `main`.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'rpi'))

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
    import autopilot as AP
except ImportError as e:
    print('autopilot will not import here (%s) — skipping' % e)
    sys.exit(0)


# --- is this rig calibrated? -----------------------------------------------
# The question that decides whether the next thing the driver sees is a live
# preview asking them to move the mount, or a scanner reading offers.
work = tempfile.mkdtemp()


def config_saying(text):
    path = os.path.join(work, 'config.json')
    if text is None:
        if os.path.exists(path):
            os.remove(path)
        return path
    with open(path, 'w') as fh:
        fh.write(text)
    return path


eq('no config at all is not calibrated', AP._usable_config(config_saying(None)), False)
eq('a real config is', AP._usable_config(config_saying('{"quad": [[0,0]]}')), True)
# The brick. Half a file is what a power cut during a write leaves, and it used
# to pass the "does it exist" test that this replaced.
eq('half a config is not', AP._usable_config(config_saying('{"quad": [[0,')), False)
eq('an empty file is not', AP._usable_config(config_saying('')), False)
# Valid JSON that is not a config. `json.load` is happy and every reader after
# it is not.
eq('a list is not a config', AP._usable_config(config_saying('[1, 2, 3]')), False)
eq('nor is a bare string', AP._usable_config(config_saying('"calibrated"')), False)
eq('nor is null', AP._usable_config(config_saying('null')), False)
eq('a directory in its place is not a config',
   AP._usable_config(os.path.join(work, 'nothing-here', 'config.json')), False)


# --- the decision table ----------------------------------------------------
class Run(object):
    """One run of main() with the camera and the scanner replaced."""

    def __init__(self, argv, config=None, checks=True, aims=True,
                 calibrates=True):
        self.did = []
        self.scan_args = None
        self.closed_before_scan = None
        self.emitted = []
        self.checks, self.aims, self.calibrates = checks, aims, calibrates
        self.config = config
        self.argv = argv
        self.closed = False

    def __enter__(self):
        self.real = {name: getattr(AP, name) for name in
                     ('check', 'aim', 'calibrate_from', 'scan', 'emit', 'CONFIG')}
        self.real_argv, self.real_sleep = sys.argv, AP.time.sleep
        self.real_camera = sys.modules.get('camera')
        # `main` imports camera before branching, and importing picamera2 is
        # the one thing this file exists to avoid.
        sys.modules['camera'] = type(sys)('camera')

        run = self

        class Source(object):
            def close(self):
                run.closed = True

        def check(as_json):
            run.did.append('check')
            return run.checks

        def aim(as_json, port, timeout, min_card=None):
            run.did.append('aim')
            return (Source(), None) if run.aims else (None, None)

        def calibrate_from(source, as_json, drawn=None, floor=None):
            run.did.append('calibrate')
            return run.calibrates

        def scan(as_json, speak, extra_args):
            run.did.append('scan')
            run.scan_args = (as_json, speak, list(extra_args))
            # Whether the camera was handed over rather than held: `scan` execs
            # into the scanner, and two processes cannot own one camera.
            run.closed_before_scan = run.closed

        AP.check, AP.aim, AP.calibrate_from, AP.scan = check, aim, calibrate_from, scan
        AP.emit = lambda payload, as_json: run.emitted.append(payload)
        AP.CONFIG = config_saying(self.config)
        AP.time.sleep = lambda s: None
        sys.argv = ['autopilot'] + self.argv
        return self

    def __exit__(self, *exc):
        for name, value in self.real.items():
            setattr(AP, name, value)
        sys.argv, AP.time.sleep = self.real_argv, self.real_sleep
        if self.real_camera is None:
            sys.modules.pop('camera', None)
        else:
            sys.modules['camera'] = self.real_camera
        return False


with Run([], config='{"quad": [[0,0]]}') as run:
    eq('a calibrated rig goes straight to scanning', AP.main(), 0)
eq('...without opening the preview', run.did, ['check', 'scan'])
ok_('...and says which config it is using',
    any(p.get('phase') == 'calibrated' for p in run.emitted))

with Run([], config=None) as run:
    eq('an uncalibrated rig aims first', AP.main(), 0)
eq('...then calibrates, then scans', run.did, ['check', 'aim', 'calibrate', 'scan'])

# The brick again, end to end this time.
with Run([], config='{"quad": [[0,') as run:
    eq('an unreadable config aims rather than starting the scanner on it',
       AP.main(), 0)
eq('...taking the same route as no config at all', run.did,
   ['check', 'aim', 'calibrate', 'scan'])

with Run(['--recalibrate'], config='{"quad": [[0,0]]}') as run:
    eq('--recalibrate aims even with a good config', AP.main(), 0)
eq('...rather than trusting it', run.did, ['check', 'aim', 'calibrate', 'scan'])
# Deleting config.json was the old way to force this, and it took the driver's
# target and running costs with it.
ok_('...and leaves the config in place to keep its settings',
    os.path.exists(os.path.join(work, 'config.json')))


# --- and every way it can stop ---------------------------------------------
with Run([], config=None, checks=False) as run:
    eq('missing dependencies is a failure', AP.main(), 1)
eq('...and nothing touches the camera', run.did, ['check'])

with Run([], config=None, aims=False) as run:
    eq('a mount that never gets good enough is a failure', AP.main(), 1)
eq('...and the scanner is not started on nothing', run.did, ['check', 'aim'])

with Run([], config=None, calibrates=False) as run:
    eq('calibration that will not write is a failure', AP.main(), 1)
eq('...and, again, no scanner', run.did, ['check', 'aim', 'calibrate'])


# --- handing the camera over ------------------------------------------------
# One process may hold the camera. `scan` execs into the scanner *in this
# process*, so the preview it opened has to be closed first — otherwise the
# scanner finds the camera busy with itself, which looks exactly like a second
# copy running.
with Run([], config=None) as run:
    AP.main()
eq('the preview is released before the scanner starts', run.closed_before_scan, True)


# --- what the scanner is started with --------------------------------------
with Run(['--json', '--speak'], config='{}') as run:
    AP.main()
eq('--json and --speak reach the scanner', run.scan_args[:2], (True, True))

with Run([], config='{}') as run:
    AP.main()
eq('...and are not invented when they were not asked for',
   run.scan_args[:2], (False, False))

# Anything argparse does not recognise is the scanner's. That is how
# --no-thread, --journal and the rest reach it through one entry point.
with Run(['--journal', '/tmp/x.jsonl', '--no-thread'], config='{}') as run:
    AP.main()
eq('unknown flags are passed through rather than refused',
   run.scan_args[2], ['--journal', '/tmp/x.jsonl', '--no-thread'])


# --- the phases it reports --------------------------------------------------
# `server.js` keeps the vocabulary in a comment and `live.html` turns it into
# what the driver reads. A phase the page has never heard of falls through to
# "WAITING FOR AN OFFER" — a claim that the scanner is running, made while it
# is not.
source = open(os.path.join(ROOT, 'rpi', 'autopilot.py')).read()
emitted = set(re.findall(r"'phase':\s*'([a-z]+)'", source))
labels = open(os.path.join(ROOT, 'live.html')).read()
block = labels[labels.index('var PHASE_LABEL'):labels.index('};', labels.index('var PHASE_LABEL'))]
known = set(re.findall(r'^\s*([a-z]+):', block, re.M))
eq('every phase the autopilot reports has a label on the live view',
   sorted(emitted - known), [])
# ...and the other way, which is how `check` sat unused: a label for a phase
# nothing sends is a screen state that can never appear.
eq('every label on the live view is a phase something sends',
   sorted(known - emitted), [])
ok_('...and there are some', emitted)

server = open(os.path.join(ROOT, 'server.js')).read()
line = [ln for ln in server.split('\n') if 'phase:' in ln and '//' in ln]
ok_('the server documents the same vocabulary',
    line and all(name in line[0] for name in emitted))

shutil.rmtree(work, ignore_errors=True)


# --- the exposure sweep, driven end to end ----------------------------------
#
# Nothing here touched `_measure_exposure` before, and one line inside it
# decides which picture the whole measurement is taken off: `prepare=`, handed
# to choose_exposure. Drop that one keyword and every check in this file and in
# test_exposure.py still passes, while the rig goes back to measuring how bright
# the card is on a picture CLAHE has already stretched to fill the range — and
# on a dark-mode card, inverted first, so both numbers run backwards.
#
# So: a fake Source over a dark-mode card lit by a real amount of light, with a
# quad that is the whole frame. No camera, no cv2 warp worth the name, and the
# arrangement that used to elect a rung blowing out half the frame.
try:
    import numpy as np
    import exposure as EX
    import pipeline as PL
except Exception as e:                                   # pragma: no cover
    np = None
    print('no imaging stack here (%s) — skipping the exposure sweep' % e)

if np is not None:
    ROWS, COLS, READOUT_US = 400, 300, 30000.0

    def _dark_card():
        img = np.full((ROWS, COLS), 120.0)
        img[ROWS // 3:] = 235.0
        for i in range(6):
            img[ROWS // 3 + 20 + i * 30: ROWS // 3 + 30 + i * 30] = 60.0
        return 255.0 - img

    def _collected(us, hz, phase, duty=0.6):
        period = 1e6 / hz
        starts = phase + np.arange(ROWS) * (READOUT_US / ROWS)
        duty_us = period * duty
        whole = np.floor(us / period)
        rem = us - whole * period
        into = np.mod(starts, period)
        part = np.clip(np.minimum(into + rem, duty_us) - np.minimum(into, duty_us), 0, None)
        part += np.clip(np.minimum(rem - (period - into), duty_us), 0, None)
        return whole * duty_us + part

    CARD = _dark_card()
    HZ = 120

    class FakeCam(object):
        def __init__(self):
            self.us = EX.DEFAULT_EXPOSURE

        def set_controls(self, controls):
            self.us = int(controls.get('ExposureTime', self.us))

    class FakeSource(object):
        """Three frames per candidate, each catching the flicker differently."""

        def __init__(self, anchor):
            self.cam = FakeCam()
            self.n = 0
            # The scene brightness that puts the card's white at 205 at
            # `anchor`, so a scene can be named by the exposure it suits.
            self.per_us = 205.0 / _collected(anchor, HZ, 0.0).mean()

        def frame(self):
            rows = _collected(self.cam.us, HZ, phase=(self.n % 3) * 7777.0)
            rng = np.random.RandomState(self.n % 3)
            self.n += 1
            f = CARD / 255.0 * rows[:, None] * self.per_us + rng.normal(0, 1.2, (ROWS, COLS))
            return np.clip(f, 0, 255).astype(np.uint8)

    # A quad is warped by PL.warp before anything else touches it, so the
    # picture the sweep sees is a resampled version of the frame above rather
    # than the frame itself. That is the real path and the point of driving it
    # from here.
    QUAD = np.array([[0, 0], [COLS - 1, 0], [COLS - 1, ROWS - 1], [0, ROWS - 1]],
                    dtype=np.float32)

    def sweep(anchor):
        _real_sleep = AP.time.sleep
        AP.time.sleep = lambda s: None                   # 8 rungs x 0.45s
        try:
            return AP._measure_exposure(FakeSource(anchor), QUAD, True)
        finally:
            AP.time.sleep = _real_sleep

    def bands(us):
        cycles = us / (1e6 / HZ)
        return abs(cycles - round(cycles)) > 0.02

    # The premise of the whole block: this card really is the dark-mode one,
    # so `preprocess` really does invert it and the two photometric numbers
    # really do run backwards when they are taken off its output. A light card
    # here would make every check below pass for the wrong reason.
    ok_('the fixture is a dark-mode card',
        PL.is_dark_mode(FakeSource(8333).frame()))

    chosen, detail, ladder = sweep(8333)
    ok_('the sweep elects a rung long enough for a dark car (%dus)' % chosen,
        chosen in EX.FLICKER_SAFE)
    # What it must not do. Measured on this card: taking the two photometric
    # numbers off the prepared frames elects 25000us, where the raw picture is
    # 48% blown out; taking them off the light elects 8333us at 0.000.
    eq('...and not the one that is blowing the card out', chosen, 8333)
    ok_('...with a ladder to fall back down (%s)' % (ladder,),
        ladder and chosen in ladder)
    ok_('...and a line of working to argue with', 'banding' in (detail or ''))

    # The other half of the wiring, and it needs its own scene because the
    # election above survives losing it. Banding is measured on the PREPARED
    # frames, and it has to be: it is an absolute level difference, so on a
    # nearly-black picture a real ripple is a small number. Handed the raw
    # frames, 1042us — an eighth of a 120Hz cycle, a certain bander — scores
    # quiet enough to join the fallback ladder, and AutoGain walks that ladder
    # freely at run time. Measured here: with the frames prepared the ladder is
    # (8333, 16667, 25000); without, (1042, 8333, 16667, 25000).
    chosen2, _detail2, ladder2 = sweep(16667)
    ok_('the fallback ladder is measured on the picture the reader sees (%s)'
        % (ladder2,), ladder2)
    eq('...so no rung on it is a fraction of a flicker cycle',
       [c for c in ladder2 if bands(c)], [])
    ok_('...and the elected rung is on it (%dus)' % chosen2, chosen2 in ladder2)


# --- and it still runs as a program ----------------------------------------
# Everything above replaced four functions; this checks the file is a program
# and not only a module, without a camera anywhere near it.
argv_probe = subprocess.run(
    [sys.executable, os.path.join(ROOT, 'rpi', 'autopilot.py'), '--help'],
    capture_output=True, text=True, timeout=60)
eq('--help works without a camera', argv_probe.returncode, 0)
for flag in ('--json', '--speak', '--recalibrate', '--aim-timeout'):
    ok_('%s is documented in --help' % flag, flag in argv_probe.stdout)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d autopilot checks passed' % ok)
sys.exit(1 if bad else 0)
