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
