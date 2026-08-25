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

    # --- and it keeps happening -------------------------------------------
    # A camera that is genuinely gone should produce a steady retry rather than
    # one attempt and a shrug — the replacement wedges too, and is caught too.
    ok_('a scanner that wedges again is caught again',
        wait_for(lambda: status()['scanner']['wedged'] >= 2, limit=25.0))

    # --- the site is unharmed by all of it --------------------------------
    eq('the server survives its own watchdog',
       urllib.request.urlopen(base + '/live.html', timeout=3).status, 200)
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
