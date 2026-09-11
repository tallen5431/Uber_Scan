"""The preflight, which is the one thing a driver runs when nothing works.

    python3 rpi/test_doctor.py

A diagnostic that crashes is worse than no diagnostic: it is a second fault on
top of the one being chased, on a headless machine, by somebody who is already
stuck. So the first thing checked here is simply that it runs to the end and
says something about everything, whatever this machine happens to be missing —
and this machine is missing plenty, which is the point. It has no camera.

The second thing is the distinction the report exists to draw. Some of what it
finds stops the rig dead and some of it only makes the rig worse, and mixing
those two is how a preflight becomes noise. A missing camera is blocking. A
reading engine that spawns a process per card is half the speed and reads every
card correctly, so it is worth a line and must not be a refusal to start.

That second kind is the hard one to test, because it is invisible from outside:
the fallback is deliberate and silent. UBERSCAN_TESSERACT=binary forces it, so
the same machine can be asked both ways and the two answers compared.
"""

import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

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


def run(**env):
    """The real doctor, as a driver runs it."""
    out = subprocess.run([sys.executable, os.path.join(HERE, 'doctor.py')],
                         capture_output=True, text=True, timeout=300,
                         env=dict(os.environ, **env))
    return out


LINE = re.compile(r'^(ok  |FAIL) {2}(\S.*?) {2,}(.*)$')


def findings(text):
    """{name: passed} for every line the report actually printed."""
    found = {}
    for line in text.splitlines():
        m = LINE.match(line)
        if m:
            found[m.group(2).strip()] = m.group(1) == 'ok  '
    return found


def blocking_count(text):
    m = re.search(r'(\d+) blocking problem', text)
    return int(m.group(1)) if m else 0


# --- it runs to the end, on a machine with most of it missing ---------------
report = run()
ok_('the preflight runs at all', report.returncode in (0, 1))
ok_('...without a traceback', 'Traceback' not in report.stderr)
ok_('...and says what it is', 'preflight' in report.stdout)
seen = findings(report.stdout)
ok_('...checking a good few things', len(seen) >= 8)

# Every line has to be one or the other. A check that prints neither is a check
# nobody can act on, and this report is read by somebody already stuck.
for line in report.stdout.splitlines():
    body = line.strip()
    if not body or body.startswith(('fix:', 'Uber Scan', 'All good', 'Nothing',
                                    'python3', ' ')) or 'blocking' in body:
        continue
    ok_('every finding is marked ok or FAIL: %r' % body[:44], LINE.match(line))

# The things the rig cannot run without, and the things it merely needs told
# about, both have to be in there.
for name in ('numpy', 'cv2', 'pytesseract', 'tesseract binary',
             'reading engine', 'scratch space'):
    ok_('the report covers %s' % name, name in seen)

# --- the report's own claims are true of this machine ----------------------
#
# A preflight that says "ok" without looking is the failure mode here, so the
# two added checks are compared against the thing they claim to describe.
sys.path.insert(0, HERE)
import handoff as HO                                          # noqa: E402
import pipeline as PL                                         # noqa: E402

eq('the engine it reports is the engine that would be used',
   seen.get('reading engine'), bool(PL._tess_lib()))
eq('the scratch space it reports is where files would go',
   seen.get('scratch space'), HO._dir() != HO.HERE)

# --- the camera's modes are the camera's, and the backup's age is real -------
#
# The modes line printed the IMX519's two sizes over a literal True whatever
# the camera was. A fake picamera2 on the path answers with whatever modes the
# check wants, and the doctor has to print those.
import json                                                   # noqa: E402
import tempfile                                               # noqa: E402
import time                                                   # noqa: E402

fakes = tempfile.mkdtemp()


def fake_camera(sizes):
    with open(os.path.join(fakes, 'picamera2.py'), 'w') as fh:
        fh.write('class Picamera2(object):\n'
                 '    @staticmethod\n'
                 '    def global_camera_info():\n'
                 '        return [{"Model": "fakecam"}]\n'
                 '    sensor_modes = %r\n'
                 '    def close(self):\n'
                 '        pass\n' % [{'size': tuple(sz)} for sz in sizes])
    return dict(PYTHONPATH=fakes + os.pathsep + os.environ.get('PYTHONPATH', ''))


small = run(**fake_camera([(1920, 1080)]))
eq('a sensor with only a small mode fails the modes check',
   findings(small.stdout).get('full-frame modes available'), False)
ok_('...printing the size the sensor reported', '1920x1080' in small.stdout)
ok_('...and not the size the doctor used to assume', '2328x1748' not in
    [l for l in small.stdout.splitlines() if 'full-frame' in l][0])
big = run(**fake_camera([(2328, 1748), (4656, 3496)]))
eq('a sensor with the full frame passes it',
   findings(big.stdout).get('full-frame modes available'), True)
ok_('...printing both modes', '4656x3496' in big.stdout)

# The backup. A stamp sync.py wrote a day and a half ago is a copy machine
# that has not answered for a day and a half, and the report says so.
journal_dir = tempfile.mkdtemp()
journal = os.path.join(journal_dir, 'journal.jsonl')
open(journal, 'w').close()
with open(journal + '.synced', 'w') as fh:
    json.dump({'at': int(time.time() * 1000) - 36 * 3600000, 'to': 'http://nuc:8080',
               'have': 12}, fh)
stale = run(JOURNAL=journal)
eq('a backup a day and a half old fails the backup check',
   findings(stale.stdout).get('offers backed up off the car'), False)
ok_('...saying how old it is (%r)' % [l for l in stale.stdout.splitlines() if 'backed up' in l][:1],
    any('36.0 hours' in l for l in stale.stdout.splitlines() if 'backed up' in l))
ok_('...and where it went', 'nuc:8080' in stale.stdout)
ok_('...without blocking the rig', 'backed up' not in ' '.join(
    l for l in stale.stdout.splitlines() if l.startswith('FAIL') and 'blocking' in l))
with open(journal + '.synced', 'w') as fh:
    json.dump({'at': int(time.time() * 1000) - 20 * 60000, 'to': 'http://nuc:8080',
               'have': 12}, fh)
fresh = run(JOURNAL=journal)
eq('a backup twenty minutes old passes it',
   findings(fresh.stdout).get('offers backed up off the car'), True)
ok_('...saying so in minutes', any('20 min ago' in l for l in fresh.stdout.splitlines()))

# ...and a rig with the timer installed but no stamp yet, which is every rig
# for the first ten minutes after the update that introduced the stamp.
#
# The stamp is a NEWER record than the sync it describes, so its absence says
# nothing about whether the copy has ever been reached. Announcing that it had
# never been reached was a confident claim about the one thing on this rig that
# cannot be regenerated, made to a driver who had been backing up for months.
nostamp_dir = tempfile.mkdtemp()
nostamp = os.path.join(nostamp_dir, 'journal.jsonl')
open(nostamp, 'w').close()
timer_file = os.path.join(nostamp_dir, 'uberscan-sync.timer')
open(timer_file, 'w').close()
virgin = run(JOURNAL=nostamp, UBERSCAN_SYNC_TIMER=timer_file)
backup_line = [l for l in virgin.stdout.splitlines() if 'backed up' in l]
ok_('a timer with no stamp yet does not claim the copy has never been reached (%r)'
    % backup_line[:1],
    not any('never been reached' in l for l in backup_line))
ok_('...it says only that nothing has been recorded yet',
    any('no sync has been recorded yet' in l for l in backup_line))
ok_('...and says that is normal just after an update',
    'newer record than the sync itself' in virgin.stdout)
ok_('...naming the one command that settles it',
    'systemctl start uberscan-sync.service' in virgin.stdout)
ok_('...without blocking the rig', 'backed up' not in ' '.join(
    l for l in virgin.stdout.splitlines() if l.startswith('FAIL') and 'blocking' in l))
# ...while a rig with no sync set up at all still gets the other sentence.
unset = run(JOURNAL=nostamp)
ok_('a rig with no sync set up is still told how to set one up',
    any('install-sync.sh' in l for l in unset.stdout.splitlines() if 'backed up' in l))

# The next step named is the autopilot, which aims, calibrates and scans on
# its own — not the three scripts it replaced.
ok_('the next step is the autopilot', 'autopilot.py' in big.stdout)
ok_('...and not the bare scan loop',
    not any('scan_pi.py' in l for l in big.stdout.splitlines()
            if l.strip().startswith('python3')))
ok_('...nor the three scripts it replaced',
    not any('calibrate.py' in l or 'preview.py' in l for l in big.stdout.splitlines()))

# --- slower is not broken --------------------------------------------------
#
# The distinction the whole report rests on. Forcing the slow path must change
# what is said and not what is refused: a rig spawning a tesseract per card
# reads every one of them correctly.
slow = run(UBERSCAN_TESSERACT='binary')
slow_seen = findings(slow.stdout)
ok_('forcing the binary is reported', slow_seen.get('reading engine') is False)
ok_('...and says which way round it is',
    'per read' in slow.stdout or 'half speed' in slow.stdout)
eq('...and blocks nothing that was not already blocked',
   blocking_count(slow.stdout), blocking_count(report.stdout))
eq('...so the exit code does not move', slow.returncode, report.returncode)

# ...and it is a real difference, not a report that says the same thing twice.
ok_('the two runs genuinely disagree about the engine',
    seen.get('reading engine') != slow_seen.get('reading engine'))

# Everything else it found is unchanged, so the fallback is not being blamed
# for anything else on the machine.
eq('nothing else changed with it',
   {k: v for k, v in slow_seen.items() if k != 'reading engine'},
   {k: v for k, v in seen.items() if k != 'reading engine'})

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d preflight checks passed' % ok)
sys.exit(1 if bad else 0)
