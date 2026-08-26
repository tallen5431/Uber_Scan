"""The faults that only show up when a cold branch finally runs.

    python3 rpi/test_lint.py

Every other suite here runs code and checks what it did. That leaves one class
of fault entirely uncovered: a name that does not exist, on a line nothing has
executed yet. A typo inside an `except` handler, a variable renamed in one
branch and not the other, a helper deleted while one caller was missed — none
of it is a syntax error, none of it fails an import, and all of it waits.

This project is exactly where that hurts. The paths that never run in a test
are the error paths, and the error paths run in a car, at night, on a machine
with no console, in the branch that was supposed to explain what went wrong.

pyflakes answers that statically, so it is asked. Only the checks that are
about correctness rather than taste: undefined names, unused imports, names
redefined before use, broken format strings. Line lengths and where the blank
lines go are not what this is for — this file has opinions about nothing.

Skipped where flake8 is not installed, like every other optional dependency
here. It is not a runtime dependency of the rig and must never become one.
"""

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ok = bad = 0

# The pyflakes codes, and what each one is actually about. Named rather than
# passed as a bare "--select=F" so that adding one is a decision someone made.
CODES = {
    'F401': 'imported and never used',
    'F402': 'an import shadowed by a loop variable',
    'F403': 'a star import, which hides what is defined',
    'F405': 'a name that may be coming from a star import',
    'F501': 'a broken percent format',
    'F502': 'a percent format given a dict where it wanted a tuple',
    'F506': 'a percent format mixing positional and named',
    'F507': 'a percent format whose placeholders and arguments disagree',
    'F521': 'a broken .format() call',
    'F522': 'a .format() given a name it has no placeholder for',
    'F524': 'a .format() missing an argument',
    'F601': 'a membership test that is always true',
    'F631': 'an assertion on a tuple, which is always true',
    'F632': 'is-comparison against a literal, which is not equality',
    'F633': 'an invalid print usage',
    'F701': 'a break outside a loop',
    'F702': 'a continue outside a loop',
    'F706': 'a return outside a function',
    'F707': 'a bare except before a specific one, which swallows it',
    'F811': 'redefined before the first one was used',
    'F821': 'a name that does not exist',
    'F822': 'an __all__ naming something undefined',
    'F823': 'a local used before it is assigned',
    'F841': 'a local assigned and never read',
}


def eq(name, got, want):
    global ok, bad
    if got == want:
        ok += 1
    else:
        bad += 1
        print('FAIL  %s: got %r want %r' % (name, got, want))


def ok_(name, cond):
    eq(name, bool(cond), True)


if shutil.which('flake8') is None:
    print('no flake8 on this machine — skipping the static checks')
    sys.exit(0)

files = sorted(f for f in os.listdir(os.path.join(ROOT, 'rpi')) if f.endswith('.py'))
ok_('there are python files to check', len(files) > 5)

proc = subprocess.run(
    ['flake8', '--select=' + ','.join(sorted(CODES)),
     '--format=%(path)s:%(row)d:%(code)s:%(text)s']
    + [os.path.join('rpi', f) for f in files],
    cwd=ROOT, capture_output=True, text=True, timeout=300)

# flake8 exits 1 when it has findings and something else when it could not run
# at all — a missing plugin, an unreadable file. Those are not a clean pass.
ok_('flake8 ran (exit %d)' % proc.returncode, proc.returncode in (0, 1))
if proc.returncode not in (0, 1):
    print(proc.stderr[-600:])

findings = [line for line in proc.stdout.strip().split('\n') if line]
by_code = {}
for line in findings:
    parts = line.split(':', 3)
    if len(parts) == 4:
        by_code.setdefault(parts[2], []).append('%s:%s %s' % (parts[0], parts[1], parts[3]))

for code in sorted(CODES):
    hits = by_code.get(code, [])
    eq('nothing %s (%s)' % (CODES[code], code), hits, [])

eq('nothing else pyflakes objects to',
   sorted(set(by_code) - set(CODES)), [])

# The gate is only worth having if it would actually catch something, and a
# selection list that has gone stale — a code renamed upstream, a typo in one
# of the entries above — fails open and silently. So it is aimed at a file that
# is definitely wrong.
broken = os.path.join(ROOT, 'rpi', '.lint-probe.py')
try:
    with open(broken, 'w') as fh:
        fh.write('import os\n\n\ndef f():\n    return nothing_defined_here + os.sep\n')
    probe = subprocess.run(
        ['flake8', '--select=' + ','.join(sorted(CODES)), broken],
        cwd=ROOT, capture_output=True, text=True, timeout=120)
    ok_('the gate catches a name that does not exist', 'F821' in probe.stdout)
finally:
    try:
        os.remove(broken)
    except OSError:
        pass

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d static checks passed' % ok)
sys.exit(1 if bad else 0)
