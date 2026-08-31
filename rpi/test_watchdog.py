"""A scanner that is running and not working, and what the server does about it.

    python3 rpi/test_watchdog.py

Everything else about supervising the scan loop assumes it dies when it fails.
Mostly it does. The case that is not covered by that assumption is the one that
costs a whole shift: a CSI camera that stops delivering frames leaves
capture_request() blocked inside the driver, so the process stays up, systemd
stays happy, /api/status keeps answering running:true, the live page keeps its
green dot, and the loop never turns again. Nothing crashes, nothing retries, and
every offer between there and the end of the night is missed with a screen that
says it is fine.

The scan loop's four-second "still here" beat is what makes that visible, and
these checks are about the server acting on it. The stand-in scanner here does
exactly what a wedged one does: beats for a while, then stops, and ignores
SIGTERM — so a polite restart is not enough, which is the whole reason the
watchdog uses SIGKILL.

The server is the real server.js, started as a subprocess with a short silence
window so a test that is about a thirty-second timeout does not take thirty
seconds.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


if shutil.which('node') is None:
    print('no node on this machine — skipping the watchdog checks')
    sys.exit(0)

# A stand-in for the scan loop. Beats for `BEATS` seconds, then wedges: no
# output, no exit, and SIGTERM ignored, which is what a process blocked in a
# driver looks like from outside. It records each start so the test can tell a
# restart from a survivor.
FAKE = r'''
import json, os, signal, sys, time

signal.signal(signal.SIGTERM, signal.SIG_IGN)
signal.signal(signal.SIGINT, signal.SIG_IGN)

with open(os.environ['STARTS'], 'a') as fh:
    fh.write('%d\n' % os.getpid())

# An offer on the record, put there by the FIRST start only. Emitted again by
# the replacement, "the order survived the restart" could not be told apart
# from "the replacement said it again".
with open(os.environ['STARTS']) as fh:
    first_start = len([l for l in fh if l.strip()]) == 1
if first_start:
    sys.stdout.write(json.dumps({'offer': {
        'id': 'wedge-1', 'pay': 14.0, 'minutes': 45.0, 'billedMinutes': 45.0,
        'miles': 6.0, 'cost': 1.8, 'perHour': 18.7}}) + '\n')
    sys.stdout.flush()

until = time.time() + float(os.environ['BEATS'])
while time.time() < until:
    sys.stdout.write(json.dumps({'alive': True}) + '\n')
    sys.stdout.flush()
    time.sleep(0.2)

# ...and now the camera stops. Nothing below ever prints, and nothing exits.
while True:
    time.sleep(3600)
'''

work = tempfile.mkdtemp()
fake = os.path.join(work, 'wedged_scanner.py')
starts = os.path.join(work, 'starts')
journal = os.path.join(work, 'journal.jsonl')
open(journal, 'w').close()
open(starts, 'w').close()
with open(fake, 'w') as fh:
    fh.write(FAKE)

SILENT_MS = 1500
port = free_port()
env = dict(os.environ,
           PORT=str(port), JOURNAL=journal,
           FRAME=os.path.join(work, 'live.jpg'),
           SCANNER_CMD=sys.executable, SCANNER_ARGS=fake,
           SCANNER_SILENT_MS=str(SILENT_MS),
           STARTS=starts, BEATS='1.0')
proc = subprocess.Popen(['node', os.path.join(ROOT, 'server.js')], env=env,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
base = 'http://127.0.0.1:%d' % port


def status():
    raw = urllib.request.urlopen(base + '/api/status', timeout=3).read()
    return json.loads(raw.decode('utf-8'))


def started_count():
    with open(starts) as fh:
        return len([l for l in fh if l.strip()])


def wait_for(cond, limit=25.0, step=0.1):
    end = time.time() + limit
    while time.time() < end:
        try:
            if cond():
                return True
        except Exception:
            pass
        time.sleep(step)
    return False


try:
    ok_('the server comes up', wait_for(lambda: status()['scanner']['running']))
    ok_('...and starts the scanner once', wait_for(lambda: started_count() >= 1))
    first = started_count()
    eq('...exactly once', first, 1)

    # --- while it is beating, it is left alone ----------------------------
    # A watchdog that restarts a working scanner is worse than no watchdog: the
    # rig would drop the camera every few seconds forever.
    time.sleep(0.6)
    eq('a beating scanner is not restarted', started_count(), 1)
    eq('...it is still the same process', status()['scanner']['running'], True)
    eq('...and is not counted as wedged', status()['scanner']['wedged'], 0)

    # --- an order in the car, taken before the wedge ----------------------
    #
    # The state that has to survive what follows. A wedge mid-delivery is not a
    # rare shape: the watchdog kills a scanner blocked in the camera driver
    # roughly every minute it stays blocked, and the driver is carrying food
    # for twenty.
    ok_('an offer reaches the record',
        wait_for(lambda: (status().get('offer') or {}).get('id') == 'wedge-1'))
    urllib.request.urlopen(urllib.request.Request(
        base + '/api/offers/mark', method='POST',
        data=json.dumps({'id': 'wedge-1', 'accepted': True}).encode('utf-8'),
        headers={'Content-Type': 'application/json'}), timeout=3).read()
    ok_('...and is marked as the order in the car', bool(status().get('holding')))

    # --- it goes quiet, and is killed and replaced ------------------------
    ok_('a silent scanner is restarted', wait_for(lambda: started_count() >= 2))
    ok_('...having actually been killed, not asked',
        wait_for(lambda: status()['scanner']['running']))
    st = status()
    ok_('...and the wedge is counted', st['scanner']['wedged'] >= 1)
    ok_('...separately from crashes', 'restarts' in st['scanner'])
    ok_('...and when it happened is on the record', st['scanner']['wedgedAt'])

    # --- the record survives the replacement ------------------------------
    # A successful restart clears `error`, correctly: there is no current
    # problem. These two are what is left to say it happened at all, so if they
    # were cleared too the whole thing would be invisible after the fact —
    # which is the same as not counting it.
    st = status()
    ok_('the wedge count is not zeroed by the restart', st['scanner']['wedged'] >= 1)
    ok_('...nor is the time it happened', st['scanner']['wedgedAt'])

    # ...and neither is the order in the car, which is the one that costs money.
    #
    # A camera that crashed says nothing about whether there is food on the back
    # seat. Cleared on restart, a wedge mid-delivery took the order with it: the
    # stack line went silent for the rest of that delivery and Drop and the
    # destination scan vanished off the panel with a job still in the car — the
    # one time the pairing advice is worth anything. The replacement scanner
    # never re-sends this offer (see the fake above), so this can only pass by
    # surviving.
    ok_('the order in the car survives the restart', bool(st.get('holding')))
    eq('...with its payout intact', (st.get('holding') or {}).get('pay'), 14.0)
    ok_('...and the offer is still there to un-mark',
        (st.get('offer') or {}).get('id') == 'wedge-1')

    # --- and it keeps happening -------------------------------------------
    # A camera that is genuinely gone should produce a steady retry rather than
    # one attempt and a shrug — the replacement wedges too, and is caught too.
    ok_('a scanner that wedges again is caught again',
        wait_for(lambda: status()['scanner']['wedged'] >= 2, limit=25.0))

    # --- the site is unharmed by all of it --------------------------------
    eq('the server survives its own watchdog',
       urllib.request.urlopen(base + '/live.html', timeout=3).status, 200)

    # --- the restart that was never scheduled -----------------------------
    #
    # A structural check, and it says so. Everything above drives a real
    # scanner; this one path cannot be driven, because it needs spawn to hand
    # back a child with no pipes — the shape a process out of file descriptors
    # gets — and nothing a test can do to this server produces that. The choice
    # was a check that proves the ordering or no check at all, and this failure
    # is too expensive to leave unwatched: the rig reads nothing for the rest of
    # the shift while /api/status answers running:true and the panel keeps its
    # green dot.
    #
    # The guard for it writes "Retrying." and returns. If it returns before the
    # 'close' handler is attached, nothing retries — the message is a promise
    # the function has already broken by the time it prints. The code carried a
    # comment saying the handler "only ever needed the chance to run" while
    # returning past it.
    src = open(os.path.join(ROOT, 'server.js')).read()
    at_close = src.index("scanner.proc.on('close'")
    at_guard = src.index('!scanner.proc.stdout')
    ok_('the restart handler is attached before the no-pipes guard returns',
        at_close < at_guard)
    ok_('...and that guard really does give up on the spawn',
        'return;' in src[at_guard:at_guard + 400])
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    # The stand-ins ignore SIGTERM by design, so nothing else will collect them.
    try:
        with open(starts) as fh:
            for line in fh:
                if line.strip():
                    try:
                        os.kill(int(line.strip()), 9)
                    except OSError:
                        pass
    except OSError:
        pass
    shutil.rmtree(work, ignore_errors=True)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d watchdog checks passed' % ok)
sys.exit(1 if bad else 0)
