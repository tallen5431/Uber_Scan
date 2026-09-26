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

# ...and the rule the paragraph above STATES is now the rule this file ENFORCES,
# which it did not. It asserted that both name shapes are gitignored — a fact
# about `.gitignore` — and said in prose that the crop endpoint appends a pid
# and a counter so two writes cannot interleave. Three other sites wrote a fixed
# `<name>.part` and nothing asked.
#
# Measured on the real server before it was fixed: two concurrent POSTs of 600
# places and 1, against a seeded 1,325-place file, ten runs — two left
# `places.json` unparseable with `GET /api/places` answering `stored: 0`, and
# the other eight lost one writer's batch while replying `stored: 1925` over a
# file holding 1,326. None of the ten came out right.
#
# A temporary that is renamed into place must carry something unique to the
# writer. The check is textual because the alternative is running every writer
# concurrently, which is `rpi/test_server.py`'s job and costs a server per case;
# this costs nothing and catches the next one at the point it is typed.
for _f, _mark in (('server.js', 'process.pid'), ('rpi/sync.py', 'getpid')):
    _src = open(os.path.join(ROOT, _f), encoding='utf-8').read().splitlines()
    for _i, _line in enumerate(_src, 1):
        # `//` and `#` catch a trailing comment; a continuation line of a `/* */`
        # block starts with `*` and would otherwise be read as code. Both shapes
        # exist in server.js within ten lines of the helper, and both failed
        # this check as prose the first time it ran — which is the check being
        # wrong, not the file.
        _bare = _line.lstrip()
        if _bare.startswith(('*', '/*')):
            continue
        _code = _line.split('//')[0].split('#')[0]
        if '.part' not in _code:
            continue
        ok_('%s:%d builds its temporary a name of its own' % (_f, _i),
            _mark in _code)

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

# --- the two readers' shared numbers ------------------------------------------
#
# offer-parser.js and rpi/offer_parser.py are one rule with two
# implementations, held to one corpus — and a corpus can only see what it can
# make the two disagree ABOUT. A cap on how many places a card may hold is not
# one of those: reaching it needs a card with five, which no fixture has, so
# both ports could cap at different numbers and every check would pass.
#
# It is not a display cap either. journal.py:content_of folds the places tuple
# into the fingerprint that decides whether a new reading SUPERSEDES an older
# one, so a rig keeping five and a phone keeping four make two fingerprints for
# the same physical card, and it stops being recognised as the same card.
#
# Read out of the two files rather than imported, because the point is that the
# NUMBERS agree, and importing one of them would only prove it agrees with
# itself. MAX_PLACES was a bare `4` at the end of findPlaces on the JS side
# when this was written, which is how it came to be worth checking.
_js = open(os.path.join(ROOT, 'offer-parser.js')).read()
_py = open(os.path.join(ROOT, 'rpi', 'offer_parser.py')).read()
for _name in ('MAX_PLACE', 'MAX_PLACES', 'SANE_RATE', 'SANE_MPH', 'MAX_MPH',
              'UNREADABLE_MPH', 'SANE_RATE_OVER_MINUTES'):
    _j = re.search(r'\bvar\s+%s\s*=\s*([0-9.]+)\s*;' % _name, _js)
    _p = re.search(r'(?m)^%s\s*=\s*([0-9.]+)\s*$' % _name, _py)
    ok_('%s is a named constant in the JavaScript reader' % _name, _j is not None)
    ok_('...and in the Python one', _p is not None)
    if _j and _p:
        eq('...and the two agree about it (js %s, py %s)'
           % (_j.group(1), _p.group(1)),
           float(_j.group(1)), float(_p.group(1)))

# ...and the same for the one number the PHONE has to keep in step with the
# rig: how much of a reading is stored. journal-client.js and rpi/journal.py
# write the same column of the same append-only file, and the phone's copy was
# not a different number but no number at all — so a frame whose crop took in
# the screen behind the card stored 600 characters from the rig and 1,998 from
# the phone. A second copy of a constant is normally what this project refuses;
# these two ends cannot import from each other, so the copy is held here
# instead.
_jc = open(os.path.join(ROOT, 'journal-client.js')).read()
_jt = re.search(r'\bvar\s+TEXT_KEPT\s*=\s*([0-9]+)\s*;', _jc)
_pt = re.search(r'(?m)^TEXT_KEPT\s*=\s*([0-9]+)\s*$', open(
    os.path.join(ROOT, 'rpi', 'journal.py')).read())
ok_('TEXT_KEPT is a named constant in the browser journal client', _jt is not None)
ok_('...and in the rig\'s', _pt is not None)
if _jt and _pt:
    eq('...and the two agree about it (js %s, py %s)' % (_jt.group(1), _pt.group(1)),
       int(_jt.group(1)), int(_pt.group(1)))
# Both ends store the reading the reader gave, not the flattened form. The
# phone stored `parsed.text` — flattening is irreversible, and journal.html
# renders this column in a <pre> whose whole job is the line breaks it threw
# away.
ok_('the browser row keeps the raw reading, not the flattened one',
    'parsed.rawText || parsed.text' in _jc)
ok_('...and caps it', 'slice(0, TEXT_KEPT)' in _jc)

# ...and the same for the one number the DRIVING SCREEN has to keep in step
# with the library. `advice.js` holds DAY_STARTS_AT and `journal.html` and
# `map.html` read it from there; `live.html` writes its own `4` out, and that
# second copy is deliberate — the panel does not load advice.js at all, because
# it has to come up from the service worker with no network and pulling a
# library in for one integer would be paying for that at the worst moment.
#
# What the copy costs is that the two can come apart, and the failure is
# silent and expensive: the day boundary decides which offers belong to
# tonight, so a panel at 4 and a journal at 3 would print two different
# takings for the same shift with neither able to say which was the shift.
# That is the same fault this file's MAX_PLACES and TEXT_KEPT checks exist
# for, arriving through a copy this project has decided to keep. So the copy
# is allowed and the DRIFT is not.
#
# Read out of the two files rather than imported, because the point is that
# the numbers agree and importing one of them would only prove it agrees with
# itself.
_adv = open(os.path.join(ROOT, 'advice.js')).read()
_live = open(os.path.join(ROOT, 'live.html')).read()
_ad = re.search(r'\bvar\s+DAY_STARTS_AT\s*=\s*([0-9]+)\s*;', _adv)
_lv = re.search(r'\bvar\s+DAY_STARTS_AT\s*=\s*([0-9]+)\s*;', _live)
ok_('DAY_STARTS_AT is a named constant in the advice library', _ad is not None)
ok_('...and in the driving screen, which cannot import it', _lv is not None)
if _ad and _lv:
    eq('...and the two agree about when a driver\'s day starts '
       '(advice %s, panel %s)' % (_ad.group(1), _lv.group(1)),
       int(_ad.group(1)), int(_lv.group(1)))
# And the pages that CAN import it still do, rather than quietly growing a
# third copy. `var DAY_STARTS_AT = 4` in either of these would pass the check
# above and be exactly the drift it is written to stop.
for _page in ('journal.html', 'map.html'):
    _src = open(os.path.join(ROOT, _page)).read()
    ok_('%s asks advice.js for the day boundary' % _page,
        'Advice.DAY_STARTS_AT' in _src)
    ok_('...and keeps no copy of its own', not re.search(
        r'\bvar\s+DAY_STARTS_AT\s*=\s*[0-9]', _src))

# --- what a driver STARTS from, in the three places that seed it ------------
#
# Two questions that look like one, and rpi/calibrate.py states the difference
# where the answer lives: `offer_parser.DEFAULT_SETTINGS` has costPerMile 0 and
# means "nobody has told me what this car costs, so do not invent a deduction";
# `SEED_SETTINGS` is "what should a driver start from" and says 0.30. That file
# already records the two being confused once — "written out by hand in three
# places, one of which was a diagnostic that hardcoded 0.30 while the parser it
# was diagnosing used 0" — and the browsers were the fourth and fifth, both
# seeding a driver at the parser's refusal.
#
# What it cost, measured on the owner's week, every row of which the rig scored
# at 0.30: re-scored at 0, 182 of 1,157 offers (15.7%) come out a green ACCEPT
# the rig would not have shown green, median $6.80/hr over, and 202 more soften
# from PASS to CLOSE CALL. A wrong number on a screen the driver acts on, which
# is this project's first fault class, on the two surfaces that have no
# calibrate step to correct them.
#
# Held here because the three cannot import from each other, which is the same
# reason TEXT_KEPT and DAY_STARTS_AT are held here. The parser's own 0 is
# asserted too: it is not a stale copy of the seed, it is the other answer, and
# a well-meaning edit making all four agree would delete the distinction.
_cal = open(os.path.join(ROOT, 'rpi', 'calibrate.py')).read()
_seed = re.search(r"SEED_SETTINGS\s*=\s*\{[^}]*'costPerMile'\s*:\s*([0-9.]+)", _cal, re.S)
_parser_default = re.search(
    r"(?m)^DEFAULT_SETTINGS\s*=\s*\{[^}]*'costPerMile'\s*:\s*([0-9.]+)", _py, re.S)
ok_('the rig has a seed for what a mile costs', _seed is not None)
ok_('...and the parser has its own, separate, refusal', _parser_default is not None)
if _seed and _parser_default:
    eq('the parser still refuses to invent a deduction',
       float(_parser_default.group(1)), 0.0)
    ok_('...and the seed is not that refusal (%s)' % _seed.group(1),
        float(_seed.group(1)) > 0)
    for _file in ('ui.js', 'scan.js'):
        _src = open(os.path.join(ROOT, _file)).read()
        _b = re.search(r'\bvar\s+DEFAULTS\s*=\s*\{.*?\}', _src, re.S)
        ok_('%s has a DEFAULTS block' % _file, _b is not None)
        if not _b:
            continue
        _c = re.search(r'costPerMile\s*:\s*([0-9.]+)', _b.group(0))
        ok_('...naming what a mile costs', _c is not None)
        if _c:
            eq('...and seeding it from the same place the rig does (%s %s)'
               % (_file, _c.group(1)), float(_c.group(1)), float(_seed.group(1)))

# --- the two hand-written approach checks stay in step ---------------------
#
# laid_out_approach's `isTotal` refusal shows only in `legDetail[].isApproach`,
# and the shared corpus cannot carry it: tests/corpus.test.js compares a `parse`
# expectation with `got === want`, which is false for every list, so a case
# naming one passes on the Python side and fails on the JavaScript side. The
# check therefore lives twice, hand-written, once in each port's own suite --
# and two copies of a check drift exactly the way two copies of a constant do.
# What is held here is the CARD, because the card is the whole test: change it
# in one place and the other port is checking a different shape.
_tp = open(os.path.join(ROOT, 'rpi', 'test_parser.py')).read()
_tj = open(os.path.join(ROOT, 'tests', 'parser.test.js')).read()
_card = 'Little Caesars (3372 Canton Rd)'
ok_('the two-delivery-card check exists on the Python side',
    'a total leg is never marked the approach' in _tp)
ok_('...and on the JavaScript side',
    'a total leg is never marked the approach' in _tj)
ok_('...and both use the same card (python)', _card in _tp)
ok_('...and both use the same card (javascript)', _card in _tj)

# --- the shared corpus cannot compare a list in `parse` or `rate` ----------
#
# tests/corpus.test.js's eq() is `got === want` outside the numeric case, so a
# `parse` or `rate` expectation holding a list or an object is true in Python
# and false in JavaScript for every input -- a case that cannot pass on one
# port and cannot fail on the other, which is two of this project's fault
# classes at once. The `places`, `ends` and `toPickup` sections have their own
# runners with sameList, and those are the sections a list belongs in.
# One check, not one per expectation: this is a single invariant about the
# corpus, and 560 green lines saying so would bury the rest of this file.
_cases = json.loads(open(os.path.join(ROOT, 'tests', 'fixtures', 'cases.json')).read())
_listy = ['%s / %s / %s' % (_sec, _c['name'][:40], _k)
          for _sec in ('parse', 'rate')
          for _c in _cases.get(_sec, [])
          for _k, _v in _c['expect'].items()
          if isinstance(_v, (list, dict))]
eq('every `parse` and `rate` expectation is a scalar both runners compare',
   _listy, [])

# --- one rule for which end of a job is which -------------------------------
#
# `places` is the accumulator's union of every name every frame read, in the
# order the FRAMES arrived. Joining it with an arrow draws a journey out of
# arrival order. The two-ends fix gave `pickup` and `dropoff` the real order
# and deliberately left the list alone, so three surfaces went on claiming one
# the list has not got: the driving panel's address row and the offers page's
# log and detail rows — while the SAME page's detail sheet already drew
# `[pickup, dropoff]`. Measured over the owner's week: 12 of 1,166 readings
# drew the arrow backwards and 182 drew a three- or four-stop chain for a job
# with two ends.
#
# MV.ends is the one rule now. This check is not about the arrow character: it
# is that no page works the answer out for itself again, which is how the four
# copies drifted in the first place.
for _page in ('live.html', 'journal.html'):
    _src = open(os.path.join(ROOT, _page), encoding='utf-8').read()
    for _shape in ('places.join', 'places && r.places.length'):
        ok_('%s asks MV.ends rather than reading `places` itself (%s)'
            % (_page, _shape), _shape not in _src)
# ...and the page asks it rather than working the answer out again. The sheet
# on the offers page is the one place that legitimately builds its own pair —
# it draws two points to map, whichever way each end was learned, where "Where"
# is what the CARD printed — so this checks the rule is ASKED, not that the
# pair never appears.
ok_('journal.html asks the shared rule for the two ends',
    'mv.ends(' in open(os.path.join(ROOT, 'journal.html'), encoding='utf-8').read())
ok_('live.html asks it too',
    'MV.ends(' in open(os.path.join(ROOT, 'live.html'), encoding='utf-8').read())

# --- ...and one rule for "this cannot be right" ------------------------------
#
# map.html draws a pair with a stray end as a red dashed line captioned "This
# cannot be right". Three readers decided that separately and two disagreed:
# render() and the sidebar's heading tested `impossible || fromStray ||
# toStray`, while placeAll's `drawn` — the figure in the status line under the
# same map — tested only `impossible`, so the line said a pair was drawn end to
# end while it sat on screen in red accusing itself. MV.accused is the rule.
#
# Checked as "the page asks", the same way as above, because the numbers
# themselves are covered by tests/mapview.test.js and what rots here is a
# reader quietly growing its own copy of the test.
_map_html = open(os.path.join(ROOT, 'map.html'), encoding='utf-8').read()
# Both readers, named separately: one of them quietly reverting to
# `p.impossible` while the other still asks is the shape this whole entry is
# about, and "the file mentions MV.accused somewhere" cannot see it.
ok_('the line map.html draws asks the shared rule',
    'var bad = MV.accused(p);' in _map_html)
ok_('...and so does the count in its sidebar',
    '!MV.accused(p)' in _map_html)
ok_('...and neither keeps a copy of the test beside the one it asks',
    'p.fromStray || p.toStray' not in _map_html)
# `impossible` on its own is a different question and map.html still asks it
# once, for the section that lists the pairs whose stated distance the straight
# line contradicts. Once — a second reader of it is a reader that stopped
# asking MV.accused.
ok_('...and `impossible` is read only by the section that is about it',
    _map_html.count('p.impossible') == 1)

# --- one rule for rounding to two places --------------------------------
#
# rpi/offer_parser.py has round2(), whose docstring is "rounded the way the
# JavaScript rounds" - Python's own round() takes a half to the nearest EVEN
# digit, 2.675 to 2.67, where Math.round gives 2.68 - and the shared corpus
# has nine cases pinning that agreement.
#
# Those nine were checking an expression WRITTEN IN THE TEST FILE. The Python
# runner called P.round2, a real call into the module under test; the
# JavaScript runner evaluated `Math.round(value * 100) / 100` itself, a third
# copy of a rule offer-parser.js had two of. Either of those two could have
# been changed with all nine still passing.
#
# The rule is offer-parser.js's round2 now. This asks that nobody writes it
# out beside the one they could call - the check the mutation could not make,
# since an inlined copy behaves identically until the day it does not.
_op_js = open(os.path.join(ROOT, 'offer-parser.js'), encoding='utf-8').read()
ok_('offer-parser.js rounds to two places in one place',
    len(re.findall(r'Math\.round\([^)]*\* 100\)\s*/\s*100', _op_js)) == 1)
ok_('...and the shared corpus asks that function rather than restating it',
    'P.round2(' in open(os.path.join(ROOT, 'tests/corpus.test.js'),
                        encoding='utf-8').read())

# --- every suite is in the README's list of them -----------------------------
#
# rpi/README.md lists each suite with the number of checks it runs, and
# SCANNING.md lists four of them again. Measured against a real run, 24 of the
# 36 rows were stale and the two documents disagreed with each other:
# corpus.test.js was 720 in one and 681 in the other against 793 actual,
# test_layout.py said 429 against 795, test_lint.py said 59 against its own
# real figure. And rpi/test_gps.py was in neither, so a whole suite had no
# entry at all.
#
# The counts cannot be checked here without running everything, which is what
# tools/test.sh is for. What CAN be checked is that no suite is missing from
# the list, which is the half that goes wrong silently - a new suite is added,
# nobody writes the row, and nothing ever says so.
_readme_rpi = open(os.path.join(ROOT, 'rpi/README.md'), encoding='utf-8').read()
for _suite in sorted(f for f in os.listdir(os.path.join(ROOT, 'rpi'))
                     if f.startswith('test_') and f.endswith('.py')):
    ok_("rpi/README.md lists %s" % _suite, _suite in _readme_rpi)
for _suite in sorted(f for f in os.listdir(os.path.join(ROOT, 'tests'))
                     if f.endswith('.test.js')):
    ok_("rpi/README.md lists tests/%s" % _suite, _suite in _readme_rpi)

# --- every screen names every reason a verdict can be withheld for ---------
#
# rate() can refuse to price a card for six reasons, and SEVEN surfaces turn
# that into words: the Pi's panel and its voice, the driving view's label and
# its voice, the phone scanner, and the keypad's label and its refusal toast.
# Each held its own table, and each was missing a DIFFERENT entry — the panel
# had no `leg`, the voice had no `rate`, `leg` or `screen`, the driving view
# and the phone had no `screen`, the phone had no `leg` either, and the keypad
# had no `rate`. So one card was named on one screen and "READ AGAIN" on the
# next, and scan_pi's own comment records the project fixing exactly this drift
# once already, for `rate`, and leaving four copies behind.
#
# The WORDS are deliberately not shared: a 480x320 hat, an 800x480 panel, a
# phone, a keypad and a voice each need their own. The LIST is, and this is
# where it is enforced.
import offer_parser as _OP_L

_REASONS = set(_OP_L.DOUBT_REASONS)

# First, that the list is what the parser can actually produce. A seventh
# reason added to doubt() or rate() and not to the list would make every check
# below pass while the screens went on falling through to READ AGAIN.
_py_src = open(os.path.join(ROOT, 'rpi/offer_parser.py'), encoding='utf-8').read()
_doubt_body = _py_src[_py_src.index('\ndef doubt('):]
_doubt_body = _doubt_body[:_doubt_body.index('\ndef ', 1)]
_produced = set(re.findall(r"return '([a-z]+)'", _doubt_body))
_produced |= set(re.findall(r"^\s+why = '([a-z]+)'", _py_src, re.M))
eq('DOUBT_REASONS is what doubt() and rate() can return',
   sorted(_produced), sorted(_REASONS))

# ...and that the two ports agree about it, the way they agree about
# everything else the shared corpus holds them to.
_js_src = open(os.path.join(ROOT, 'offer-parser.js'), encoding='utf-8').read()
for _name in ('DOUBT_REASONS', 'TYPED_DOUBT_REASONS'):
    _js_list = re.search(r'var %s = \[(.*?)\];' % _name, _js_src, re.S)
    eq('offer-parser.js %s matches the Python' % _name,
       sorted(re.findall(r"'([a-z]+)'", _js_list.group(1))) if _js_list else None,
       sorted(getattr(_OP_L, _name)))

# The four surfaces that read a real card, each of which can meet all six.
#
# Matched inside the table itself rather than anywhere in the file: `leg` and
# `screen` appear in prose all over scan_pi.py, and a check that greps the
# whole file would pass on a comment.
_TABLES = [
    ('the Pi\'s panel', 'rpi/scan_pi.py', r'DOUBT_LABELS = \{(.*?)\n\n', _REASONS),
    ('the Pi\'s voice', 'rpi/scan_pi.py',
     r"if rate\['state'\] == 'doubt':(.*?)\n\n", _REASONS),
    ('the driving screen', 'live.html',
     r"el\.verdictLabel\.textContent =\s*\{(.*?)\}\[r\.doubt\]", _REASONS),
    ('what the rig says out loud', 'live.html',
     r"var say = r\.state === 'doubt'(.*?)\[r\.doubt\]", _REASONS),
    ('the phone scanner', 'scan.js',
     r"el\.verdictLabel\.textContent = !r\.ready(.*?)\}\[r\.doubt\]", _REASONS),
    # ...and the keypad, which can reach four of the six: it builds rate()'s
    # argument itself, with no legs and no card text. Naming the other two
    # there would be a branch no input can reach.
    ('the keypad', 'ui.js',
     r"el\.verdictLabel\.textContent = r\.state === 'doubt'(.*?)\}\[r\.doubt\]",
     set(_OP_L.TYPED_DOUBT_REASONS)),
    ('the keypad\'s refusal', 'ui.js', r"toast\((.*?)\}\[r\.doubt\]",
     set(_OP_L.TYPED_DOUBT_REASONS)),
]
for _what, _file, _pat, _want in _TABLES:
    _src = open(os.path.join(ROOT, _file), encoding='utf-8').read()
    _m = re.search(_pat, _src, re.S)
    ok_('%s still has a table of doubt reasons (%s)' % (_what, _file), bool(_m))
    if not _m:
        continue
    # Comments stripped first. Every one of these tables carries a paragraph
    # saying why an entry is there, and a key read out of prose would let a
    # table pass on its own explanation.
    _body = re.sub(r'(?m)\s*(?://|#).*$', '', _m.group(1))
    _named = set(re.findall(r"(?:\A|[{,])\s*'?([a-z]+)'?\s*:", _body))
    _named &= _REASONS
    eq('%s names every reason it can be given' % _what,
       sorted(_want - _named), [])
    eq('...and none it cannot: %s' % _what, sorted(_named - _want), [])

# --- the record of what has already been looked at -------------------------
#
# AUDITS.md exists so the same ground is not dug twice: what was fixed, what is
# known and still open, and — the half that actually saves the time — proposals
# that were checked against the code and found to be wrong.
#
# A stale one is worse than none. It would be read as current, and the whole
# point of it is to be believed without re-checking, so it is exactly the shape
# of this project's fifth fault: text making a claim the code does not honour.
# Neither check below can tell whether the PROSE is still true — nothing can —
# but both catch the way it actually rots, which is a file being renamed or
# added underneath it.
_audits = open(os.path.join(ROOT, 'AUDITS.md')).read()
_readme = open(os.path.join(ROOT, 'README.md')).read()

ok_('the record of what has been audited is readable', len(_audits) > 500)
ok_('...and the README points at it', 'AUDITS.md' in _readme)

# Every path it names in backticks is a path that exists. A doc naming a file
# that was renamed a year ago is a doc nobody trusts the rest of.
for _named in sorted(set(re.findall(r'`([A-Za-z0-9_./-]+\.(?:js|py|html|css|md|sh))`',
                                    _audits))):
    ok_('AUDITS.md names a file that exists: %s' % _named,
        os.path.exists(os.path.join(ROOT, _named)))

# ...and the arithmetic it prints is the arithmetic that runs. The README's
# "The math" block is the only place in the project that states the four rates
# as formulas, and it said `$/mile = pay / miles` while offer-parser.js had
# divided `net` since running costs were added — so the one document a driver
# would check the rig against had never matched it, on the figure this project
# has a Settled entry about. Found by reading the block, not by any check;
# this is the check.
#
# Right-hand sides only, and matched as text against the expression in the
# parser rather than evaluated: a checker that worked the rates out itself
# would be a second implementation to keep in step, which is the fault it is
# here to prevent.
_parser_js = open(os.path.join(ROOT, 'offer-parser.js'), encoding='utf-8').read()
_math = re.search(r'## The math\n+```\n(.*?)```', _readme, re.S)
ok_('the README states the arithmetic', bool(_math))
if _math:
    for _rate, _expr in (('$/hour', 'net / (minutes / 60)'),
                         ('$/min', 'net / minutes'),
                         ('$/mile', 'net / miles')):
        _line = re.search(r'^\s*%s\s*=\s*(.+?)\s*$' % re.escape(_rate),
                          _math.group(1), re.M)
        ok_('the README gives a formula for %s' % _rate, bool(_line))
        if _line:
            ok_('...and it is the one offer-parser.js runs: %s = %s'
                % (_rate, _line.group(1)),
                _line.group(1) == _expr and _expr in _parser_js)

# ...and the README's own table covers every file the repo ships at the top
# level, so the next one added has to be written down rather than quietly left
# out. AUDITS.md itself was missing from it until this check was written.
# README.md is not asked to list itself. Everything else is, in whichever form
# the table already uses — some are named in backticks and some are linked.
_shipped = sorted(f for f in os.listdir(ROOT)
                  if os.path.isfile(os.path.join(ROOT, f))
                  and f.rsplit('.', 1)[-1] in ('js', 'html', 'css', 'md', 'webmanifest')
                  and f not in ('package.json', 'package-lock.json', 'README.md'))
for _f in _shipped:
    ok_('the README names %s' % _f,
        ('`%s`' % _f) in _readme or ('(%s)' % _f) in _readme)

# ...and nothing in it is said twice. Both shapes below are real, and both came
# out of the scripts that move an entry from Open into Done once it is fixed:
# the lift left the original behind — four copies of one entry before anything
# noticed — and once stranded an entry's closing sentence in Open as a heading
# with no body under it. Neither check can tell whether the prose is true, and
# nothing can, but this rot has a shape and the shape is checkable. Both failed
# the file as committed, which is the only reason to believe either.

# A bold run of four words or more is a claim, not emphasis. `**not**`,
# `**never**` and `**Done**` repeat freely and are meant to; a sentence is not
# emphasis and has no business appearing twice.
_claims = {}
for _bold in re.findall(r'\*\*(.+?)\*\*', _audits, re.S):
    _bold = re.sub(r'\s+', ' ', _bold).strip()
    if len(_bold.split()) >= 4:
        _claims[_bold] = _claims.get(_bold, 0) + 1
_twice = sorted(_c[:60] for _c, _n in _claims.items() if _n > 1)
ok_('AUDITS.md makes each claim once, not %s' % (_twice[:2] or 'twice'),
    not _twice)

# ...and no two entries open alike. This is the half the rule above cannot see:
# an entry that was moved and then EDITED is not a duplicate string. Open said
# "The two ends of a job ARE taken off the two ends of a list..." while Done
# said "...WERE taken off...", so the ledger called one bug fixed and
# outstanding at the same time, which is worse than either alone. 64 headings
# today and no other pair comes within 20 characters, so the threshold is not
# cut to fit the one case that prompted it.
_heads = []
for _sec in re.split(r'^## ', _audits, flags=re.M)[1:]:
    for _para in re.split(r'\n\s*\n', _sec):
        _lead = re.match(r'\*\*(.+?)\*\*', _para.strip(), re.S)
        if _lead:
            _heads.append(re.sub(r'\s+', ' ', _lead.group(1)).strip())
_alike = sorted(set(_a[:60] for _i, _a in enumerate(_heads)
                    for _b in _heads[_i + 1:]
                    if _a[:20].lower() == _b[:20].lower()))
ok_('AUDITS.md keeps each entry in one section, not %s' % (_alike[:2] or 'two'),
    not _alike)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d static checks passed' % ok)
sys.exit(1 if bad else 0)
