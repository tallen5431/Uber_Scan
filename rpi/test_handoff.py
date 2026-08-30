"""The files the two sides pass requests through, and the rule that finds them.

    python3 rpi/test_handoff.py

Three requests travel from the browser to the camera as files: somebody is
watching and which view they want, re-find the phone, read this box. One side
that writes them is JavaScript and the other that reads them is Python, and
nothing anywhere detects a mismatch — a request written where the reader is not
looking is not a stale picture or a slow page, it is a button that does nothing
and never says so.

The live frame has the same split and can afford to be sloppy about it:
`framePath` in server.js takes whichever candidate is freshest, which is right
either way because a frame is written by one side and read by the other. That
does not work for a handshake, so these are found by a *rule* — is /dev/shm a
directory this process may write in? — written once in handoff.py and again in
server.js, and this file runs both and compares the answers character for
character.

What is also checked is that a reader honours the old location. Upgrading is a
`git pull` that moves both sides at once, but the scanner is a long-running
process and the web server is restarted far more often, so on one machine the
two can be minutes apart.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'rpi'))

import cropbox as CX                                          # noqa: E402
import handoff as HO                                          # noqa: E402

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


# Every request both sides share. Adding one here is what holds the new file to
# the same rule as the other three — where it is written, that both sides derive
# the same path for it, and that a private directory moves it for both of them.
# A request written where the reader is not looking is not a stale picture, it
# is a button that does nothing.
BASES = [HO.VIEWING, HO.RECALIBRATE, HO.CROPBOX, HO.DROPOFF]

# --- the rule --------------------------------------------------------------
for base in BASES:
    chosen = HO.path(base)
    ok_('%s is written somewhere absolute' % base, os.path.isabs(chosen))
    ok_('...inside the directory the rule picked',
        os.path.dirname(chosen) == HO._dir())
    ok_('...and is looked for in the checkout as well',
        HO.legacy(base) in HO.candidates(base))
    ok_('...best first', HO.candidates(base)[0] == chosen)

# Derived from BASES rather than written out, so adding a fourth request does
# not need this line edited to keep passing — which is the failure mode of a
# hardcoded expectation: it is edited to match, and stops asking the question.
eq('nothing is looked for twice', [len(HO.candidates(b)) for b in BASES],
   [2 if HO._dir() != HO.HERE else 1] * len(BASES))

# A dot in a shared directory hides a file from exactly the person trying to
# find out what is holding memory; a name with no owner in it is worse.
if HO._dir() == HO.RAM:
    for base in BASES:
        name = os.path.basename(HO.path(base))
        ok_('%s says whose it is in /dev/shm (%s)' % (base, name),
            name.startswith('uberscan-'))
        ok_('...and is not hidden there', not name.startswith('.'))
    for base in BASES:
        eq('%s keeps its dot in a checkout' % base,
           os.path.basename(HO.legacy(base)), base)

# The four files must not collide with each other.
names = [HO.path(b) for b in BASES] + [HO.frame()]
eq('every handoff file has its own name', len(set(names)), len(names))

# --- and server.js answers it the same way ---------------------------------
# The two implementations are the point of this file. Run the real one out of
# server.js rather than a copy of it here, or this checks a copy against a copy.
if shutil.which('node') is None:
    print('no node on this machine — skipping the cross-language check')
else:
    server = open(os.path.join(ROOT, 'server.js')).read()
    start = server.index('function handoffDir()')
    end = server.index("var WATCH_PATH = handoffPath('.viewing');")
    probe = ("var path = require('path'), fs = require('fs');\n"
             "var ROOT = %s;\n" % json.dumps(ROOT)
             + server[start:end]
             + "console.log(JSON.stringify(%s.map(handoffPath)));\n"
             % json.dumps(BASES))
    got = subprocess.run(['node', '-e', probe],
                         capture_output=True, text=True, timeout=60)
    eq('the server-side rule runs', got.returncode, 0)
    if got.returncode != 0:
        print(got.stderr[-400:])
    else:
        theirs = json.loads(got.stdout.strip())
        mine = [HO.path(b) for b in BASES]
        eq('both sides put the requests in the same place', theirs, mine)

    # ...and the same for the picture, whose names predate the module and are
    # written out in FRAME_CANDIDATES rather than derived.
    ok_('the server knows the RAM name for the frame', HO.FRAME_RAM in server)
    ok_('...and the checkout one', HO.FRAME_LEGACY in server)

# --- and a rig can be told to keep its requests to itself -------------------
# Two copies of this on one machine share three fixed filenames in a directory
# everything else can see, so they consume each other's requests. The override
# only matters if BOTH sides honour it, and honour it identically: a server
# writing to the private directory while the scanner still watches /dev/shm is
# the button-that-does-nothing failure this whole module exists to prevent.
private = tempfile.mkdtemp()
was = os.environ.get(HO.ENV_DIR)
try:
    os.environ[HO.ENV_DIR] = private
    eq('a writable directory that was asked for is used', HO._dir(), private)
    ok_('...and the names are prefixed there, as anywhere but the checkout',
        all(os.path.basename(HO.path(b)).startswith('uberscan-') for b in BASES))

    if shutil.which('node') is not None:
        got = subprocess.run(['node', '-e', probe],
                             capture_output=True, text=True, timeout=60)
        eq('the server-side rule honours it too', got.returncode, 0)
        if got.returncode == 0:
            eq('...and lands on the very same files',
               json.loads(got.stdout.strip()), [HO.path(b) for b in BASES])

    # A value that is not somewhere this process can write is not an instruction
    # to write there anyway. Falling back is what keeps a stale line in a shell
    # profile from silently splitting the rig in two.
    os.environ[HO.ENV_DIR] = os.path.join(private, 'not-a-directory')
    eq('a directory that is not there is ignored', HO._dir(),
       HO.RAM if os.path.isdir(HO.RAM) and os.access(HO.RAM, os.W_OK) else HO.HERE)
    os.environ[HO.ENV_DIR] = ''
    eq('...and so is an empty one', HO._dir(),
       HO.RAM if os.path.isdir(HO.RAM) and os.access(HO.RAM, os.W_OK) else HO.HERE)
finally:
    if was is None:
        os.environ.pop(HO.ENV_DIR, None)
    else:
        os.environ[HO.ENV_DIR] = was
    shutil.rmtree(private, ignore_errors=True)


# --- a reader still hears an older writer ----------------------------------
# The dangerous direction: the web server is restarted more often than the
# scanner, so for a few minutes after a pull it can be the newer of the two.
work = tempfile.mkdtemp()
real_here = HO.HERE
try:
    # Pretend the checkout is somewhere writable, so the legacy copy can be made.
    HO.HERE = work

    box = CX.parse_request({'box': [0.1, 0.35, 0.8, 0.3]})

    # Written where the current rule says: read, and gone afterwards.
    CX.write_request(box)
    eq('a box left in the new place is read', CX.take_request(), box)
    eq('...and only once', CX.take_request(), None)

    # Written by a server that has not been restarted since the last pull.
    CX.write_request(box, path=HO.legacy(HO.CROPBOX))
    eq('a box left in the old place is read too', CX.take_request(), box)
    eq('...and is gone afterwards as well', CX.take_request(), None)
    ok_('...actually removed rather than merely ignored',
        not os.path.exists(HO.legacy(HO.CROPBOX)))

    # Both at once. Whichever is honoured, neither may be left behind to be
    # adopted hours later when the scanner next restarts.
    CX.write_request(box)
    CX.write_request(box, path=HO.legacy(HO.CROPBOX))
    ok_('a box in both places is still read', CX.take_request() == box)
    eq('...and nothing is left in either',
       [os.path.exists(p) for p in HO.candidates(HO.CROPBOX)], [False, False])

    # `clear` is what the scanner's recalibrate check uses, and it has the same
    # job: leave nothing that could fire later.
    for where in HO.candidates(HO.RECALIBRATE):
        open(where, 'w').close()
    HO.clear(HO.RECALIBRATE)
    eq('a re-find request is cleared from everywhere it might be',
       [os.path.exists(p) for p in HO.candidates(HO.RECALIBRATE)], [False, False])
    # Clearing a request nobody made is not an error: this runs every frame.
    HO.clear(HO.RECALIBRATE)
    ok_('...and clearing nothing is fine', True)

    ok_('no staging files are left behind',
        not any(p.endswith('.part') for p in os.listdir(work)))
finally:
    HO.HERE = real_here
    shutil.rmtree(work, ignore_errors=True)
    # Anything this test wrote into real RAM goes with it.
    for base in BASES:
        try:
            os.remove(HO.path(base))
        except OSError:
            pass

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d handoff checks passed' % ok)
sys.exit(1 if bad else 0)
