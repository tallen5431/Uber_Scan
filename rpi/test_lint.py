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

import fnmatch
import glob
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'rpi'))
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

# --- nothing the rig writes may become a commit ----------------------------
#
# A different class of fault that also only shows up on the machine: a file the
# code creates at runtime, inside its own checkout, that nobody told git to
# ignore. `git add -A` on the Pi then commits it. `rpi/.camera.lock` was one,
# and it holds a pid — a working directory's worth of state pushed to a public
# remote because one line was missed in a file nothing checks.
#
# So the list is derived from the code rather than kept by hand: every literal
# joined onto this directory that is not a source file the repo ships.
WRITES = re.compile(
    r"os\.path\.join\(\s*(?:HERE|os\.path\.dirname\(os\.path\.abspath\(__file__\)\))"
    r"\s*,\s*'([^']+)'")

ignored = []
gitignore = os.path.join(ROOT, '.gitignore')
if os.path.exists(gitignore):
    ignored = [l.strip() for l in open(gitignore) if l.strip()
               and not l.strip().startswith('#')]


def is_ignored(name):
    """Would git leave `rpi/<name>` alone?"""
    return any(fnmatch.fnmatch('rpi/' + name, pattern.rstrip('/'))
               or fnmatch.fnmatch(name, pattern.rstrip('/'))
               for pattern in ignored)


ok_('the repo has a .gitignore at all', bool(ignored))
written = set()
for path in sorted(glob.glob(os.path.join(ROOT, 'rpi', '*.py'))):
    if os.path.basename(path).startswith('test_'):
        continue
    for name in WRITES.findall(open(path).read()):
        # Source the repo ships is not something the rig wrote.
        if os.path.exists(os.path.join(ROOT, 'rpi', name)) and name.endswith('.py'):
            continue
        written.add(name)

ok_('the scan found the files the rig writes', len(written) >= 3)
for name in sorted(written):
    ok_('rpi/%s is ignored, so it cannot be committed' % name, is_ignored(name))

# ...and the fallback names handoff.py uses where there is no RAM disk, which
# are built rather than written out as literals.
import handoff as HO                                          # noqa: E402
for base in (HO.VIEWING, HO.RECALIBRATE, HO.CROPBOX, HO.FRAME_LEGACY):
    ok_('the fallback %s is ignored' % base, is_ignored(base))

# Every one of them is written through a temporary and renamed into place, and
# the temporary names are not all `<name>.part`: the crop endpoint appends a pid
# and a counter so two drags arriving together cannot interleave into one file.
# Naming them exactly is what left three of these committable.
for base in (HO.VIEWING, HO.RECALIBRATE, HO.CROPBOX, HO.FRAME_LEGACY):
    for suffix in ('.part', '.4321.7.part', '.tmp'):
        ok_('...and %s%s with it' % (base, suffix), is_ignored(base + suffix))

# --- nothing big rides along that the rig cannot use ------------------------
#
# Four Python wheels sat at the root of this repository for a while: 48MB,
# built for x86_64, downloaded to stand up a test harness on some other
# machine and swept into a commit by `git add -A`. The Pi fetched them on every
# pull and could not have installed one. Nothing referred to them, so nothing
# noticed. The pattern is ignored now, and this holds the size, because the
# next accident will have a different extension.
#
# The cap is measured, not chosen: the largest thing the repo legitimately
# carries outside vendor/ is rpi/README.md at 310kB; the smallest wheel that
# was not pure metadata was 625kB. One megabyte sits between them. vendor/ is
# the OCR engine, four files of 3-4MB each, and is exempt by name rather than
# by a cap high enough to let a wheel back in.
ok_('*.whl is ignored, so a harness download cannot be committed',
    is_ignored('anything-1.0-py3-none-any.whl'))
BIG = 1000000
git = shutil.which('git')
tracked = None
if git:
    listing = subprocess.run([git, '-C', ROOT, 'ls-files', '-z'],
                             capture_output=True)
    if listing.returncode == 0:
        tracked = [p for p in listing.stdout.decode('utf-8').split('\0') if p]
if tracked is None:
    print('  (no git here, so what is tracked cannot be sized — skipping)')
else:
    ok_('git listed the files the repo carries', len(tracked) > 20)
    big = [p for p in tracked
           if not p.startswith('vendor/')
           and os.path.exists(os.path.join(ROOT, p))
           and os.path.getsize(os.path.join(ROOT, p)) > BIG]
    ok_('no tracked file outside vendor/ is over %dkB%s' % (
        BIG // 1000, ' (' + ', '.join(big) + ')' if big else ''), not big)

# --- the quick JavaScript pass runs every JavaScript suite -------------------
#
# `npm run test:js` named three of the four suites, so the stacking advice
# was tested only by the ten-minute `npm test`. Either every tests/*.test.js
# is named, or the script globs them.
import json                                                   # noqa: E402
scripts = json.load(open(os.path.join(ROOT, 'package.json'))).get('scripts', {})
quick = scripts.get('test:js', '')
suites = sorted(os.path.basename(p) for p in glob.glob(os.path.join(ROOT, 'tests', '*.test.js')))
ok_('there are JavaScript suites to run', len(suites) >= 3)
ok_('npm run test:js runs every one of them (%r)' % quick[:60],
    'tests/*.test.js' in quick or all(name in quick for name in suites))

# --- two figures may not wear the same words -------------------------------
#
# The offers page said "16 of them, 22.1 hours in total, not one shift" and,
# one element below it, "across 16 separate runs of scanning, 26.8 hours in
# total". The same runs and the same offers, 21% apart, because the second one
# carries each run on to the end of the last trip taken in it and the first
# stops at the last card seen. Both are right; neither said which question it
# was answering, and they are never on screen apart.
#
# A static check because reproducing the clash needs a fixture large enough to
# reach a recommendation, and the fault is not in the arithmetic — it is in two
# strings. The rule is narrow and literal: a phrase this ambiguous may appear
# once per page, or not at all. Measured across the four real exports that
# reach a recommendation, the gap ran +12%, +15%, +21%, +22%, always the same
# way round.
AMBIGUOUS = ['hours in total']
for page in ('journal.html', 'live.html', 'index.html', 'scan.html'):
    text = open(os.path.join(ROOT, page)).read()
    # Comments explain the trap and have to be allowed to quote it, or the
    # check would forbid writing down why it exists.
    code = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    code = re.sub(r'(?m)^\s*//.*$', '', code)
    for phrase in AMBIGUOUS:
        seen = code.count(phrase)
        ok_('%s says %r at most once, so two spans cannot share one wording '
            '(%d)' % (page, phrase, seen), seen <= 1)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d static checks passed' % ok)
sys.exit(1 if bad else 0)
