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
