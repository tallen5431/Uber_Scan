"""Getting the offers off the car, and not losing any on the way.

    python3 rpi/test_sync.py

The journal is the only thing this rig produces that cannot be made again, and
the sync is the only thing standing between it and a dead SD card. So what is
checked here is not that it works once — it is that it converges: that sending
the same rows twice changes nothing, that an interrupted run leaves no gap, and
that a car spending most of its life out of range is treated as normal rather
than as a fault.

The far end is the real server.js, started as a subprocess with SCANNER=0, so
this exercises the endpoint the NUC actually runs rather than a stand-in.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import journal as JR                                          # noqa: E402
import sync as SY                                             # noqa: E402

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


def offer(i, at, seq=1, pay=None):
    return {'v': 1, 'id': 'off%d' % i, 'seq': seq, 'at': at, 'firstAt': at,
            'pay': 10.0 + i if pay is None else pay, 'minutes': 20.0, 'miles': 4.0,
            'perHour': 30.0, 'grossPerHour': 36.0, 'perMile': 1.5, 'cost': 1.2,
            'billedMinutes': 20.0, 'state': 'go', 'target': 25, 'band': 15,
            'costPerMile': 0.3, 'legs': 2, 'hasTotal': False, 'whole': True}


def write(path, rows):
    with open(path, 'w') as fh:
        for r in rows:
            fh.write(json.dumps(r) + '\n')


def lines(path):
    if not os.path.exists(path):
        return []
    return [json.loads(l) for l in open(path) if l.strip()]


class FarEnd(object):
    """server.js in the role the NUC plays: a viewer with no camera."""

    def __init__(self, token=None):
        self.dir = tempfile.mkdtemp()
        self.journal = os.path.join(self.dir, 'journal.jsonl')
        self.port = free_port()
        env = dict(os.environ, SCANNER='0', PORT=str(self.port),
                   JOURNAL=self.journal)
        if token:
            env['SYNC_TOKEN'] = token
        else:
            env.pop('SYNC_TOKEN', None)
        self.proc = subprocess.Popen(
            ['node', os.path.join(ROOT, 'server.js')], env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.base = 'http://127.0.0.1:%d' % self.port
        for _ in range(120):
            try:
                urllib.request.urlopen(self.base + '/api/journal/newest', timeout=1).read()
                return
            except Exception:
                time.sleep(0.1)
        raise RuntimeError('the far end never came up')

    def close(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()
        shutil.rmtree(self.dir, ignore_errors=True)


if shutil.which('node') is None:
    print('no node on this machine — skipping the sync checks')
    sys.exit(0)

work = tempfile.mkdtemp()
pi = os.path.join(work, 'journal.jsonl')
now = JR.now_ms()

# --- the ordinary case ------------------------------------------------------
far = FarEnd()
try:
    write(pi, [offer(i, now - i * 300000) for i in range(25)])

    eq('the far end starts empty', SY.newest_at(far.base), 0)
    sent = SY.rows_since(pi, 0)
    result = SY.send(far.base, sent)
    eq('every row is taken the first time', result['added'], 25)
    eq('...and stored', len(lines(far.journal)), 25)

    # The whole point. A timer runs this every few minutes whether or not
    # anything happened, and a car drops the connection constantly, so sending
    # the same rows again has to be free rather than destructive.
    again = SY.send(far.base, sent)
    eq('sending the same rows again adds nothing', again['added'], 0)
    eq('...and does not duplicate them', len(lines(far.journal)), 25)
    third = SY.send(far.base, sent)
    eq('...however many times it happens', third['added'], 0)
    eq('...still', len(lines(far.journal)), 25)

    eq('the far end reports what it has', SY.newest_at(far.base), max(r['at'] for r in sent))

    # A later, better read of an offer already sent. Same id, higher seq: it is
    # a correction rather than a duplicate and has to land.
    corrected = offer(0, now, seq=2, pay=99.0)
    with open(pi, 'a') as fh:
        fh.write(json.dumps(corrected) + '\n')
    eq('a corrected read of the same offer is new', SY.send(far.base, [corrected])['added'], 1)
    eq('...and is kept alongside the first', len(lines(far.journal)), 26)

    # An interrupted upload must not leave a hole. Send the first half, then
    # everything, exactly as a re-run after a dropped connection would.
    half = sent[:12]
    far2 = FarEnd()
    try:
        SY.send(far2.base, half)
        eq('a partial upload stores what arrived', len(lines(far2.journal)), 12)
        SY.send(far2.base, sent)
        eq('...and the next run fills the gap', len(lines(far2.journal)), 25)
        ids = set(r['id'] for r in lines(far2.journal))
        eq('...with nothing missing', len(ids), 25)
    finally:
        far2.close()

    # Rows that cannot be de-duplicated cannot be stored, because there would be
    # no way to avoid writing them again on the next upload.
    bad_rows = SY.send(far.base, [{'pay': 5.0, 'at': now}])
    eq('a row with no id is refused', bad_rows['added'], 0)
    eq('...and counted as malformed', bad_rows['malformed'], 1)

    # The whole file, resent. Costs a few hundred kilobytes and changes nothing.
    eq('--all is safe', SY.send(far.base, SY.rows_since(pi, 0))['added'], 0)

    # --- the calibration rides along ------------------------------------
    # 400 bytes, and every number in it can be measured again — but re-aiming a
    # camera at the roadside is an afternoon nobody wants to spend twice.
    cfg = os.path.join(work, 'config.json')
    calibration = {'quad': [[100, 50], [900, 50], [900, 1700], [100, 1700]],
                   'cardHeight': 900, 'lensPosition': 10.0, 'exposureTime': 16667,
                   'settings': {'target': 32, 'band': 15, 'costPerMile': 0.62}}
    with open(cfg, 'w') as fh:
        json.dump(calibration, fh)
    backup = os.path.join(os.path.dirname(far.journal), 'config-backup.json')

    first = SY.send_config(far.base, cfg)
    ok_('the calibration is taken', first.get('ok'))
    ok_('...and written', first.get('changed'))
    eq('...intact', json.load(open(backup))['settings']['target'], 32)

    # It is sent on every tick and a calibration changes a handful of times in a
    # rig's life, so an unchanged one must not rewrite the file.
    eq('an unchanged calibration is not rewritten',
       SY.send_config(far.base, cfg).get('changed'), False)

    calibration['settings']['target'] = 40
    with open(cfg, 'w') as fh:
        json.dump(calibration, fh)
    eq('...but a changed one is', SY.send_config(far.base, cfg).get('changed'), True)
    eq('...with the new value', json.load(open(backup))['settings']['target'], 40)

    # A backup that cannot be restored is worse than none, because it is
    # believed. Anything that is not a calibration is refused rather than stored.
    junk = os.path.join(work, 'junk.json')
    with open(junk, 'w') as fh:
        fh.write('{"not": "a calibration"}')
    ok_('something that is not a calibration is refused',
        not SY.send_config(far.base, junk).get('ok'))
    with open(junk, 'w') as fh:
        fh.write('not even json')
    ok_('...and so is something that is not JSON',
        not SY.send_config(far.base, junk).get('ok'))
    eq('...neither of which touched the good copy',
       json.load(open(backup))['settings']['target'], 40)

    # A missing config is simply nothing to do, not a failure.
    ok_('a config that is not there is not an error',
        not SY.send_config(far.base, os.path.join(work, 'nope.json')).get('ok'))
finally:
    far.close()

# --- a far end whose journal directory nobody made ---------------------------
# The commonest way this fails in practice, and it failed twice over: JOURNAL is
# usually pointed somewhere outside the checkout, setting the variable is the
# memorable half of that and mkdir is the half that gets forgotten — and the rig
# then got HTTP 500 'could not append' with the actual reason (ENOENT) sitting
# in a log on the other machine.
class FarEndAt(FarEnd):
    def __init__(self, journal):
        self.dir = os.path.dirname(journal)
        self.journal = journal
        self.port = free_port()
        env = dict(os.environ, SCANNER='0', PORT=str(self.port), JOURNAL=journal)
        env.pop('SYNC_TOKEN', None)
        self.proc = subprocess.Popen(
            ['node', os.path.join(ROOT, 'server.js')], env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.base = 'http://127.0.0.1:%d' % self.port
        for _ in range(120):
            try:
                urllib.request.urlopen(self.base + '/api/journal/newest', timeout=1).read()
                return
            except Exception:
                time.sleep(0.1)
        raise RuntimeError('the far end never came up')

    def close(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


missing = os.path.join(work, 'never', 'made', 'this', 'journal.jsonl')
fresh = FarEndAt(missing)
try:
    ok_('a directory nobody made is not an error',
        SY.send(fresh.base, [offer(1, now)])['added'] == 1)
    eq('...the offers are stored anyway', len(lines(missing)), 1)

    cfg2 = os.path.join(work, 'cfg2.json')
    with open(cfg2, 'w') as fh:
        json.dump({'quad': [[1, 1], [2, 1], [2, 2], [1, 2]]}, fh)
    ok_('...and so is the calibration', SY.send_config(fresh.base, cfg2).get('ok'))
finally:
    fresh.close()

# When a write really cannot happen, the reason has to reach the machine that
# can act on it. 'could not append' is not something anyone can do anything
# with, and it is the only message the rig ever sees.
blocked = os.path.join(work, 'blocker')
with open(blocked, 'w') as fh:
    fh.write('a file, not a directory\n')
stuck = FarEndAt(os.path.join(blocked, 'journal.jsonl'))
try:
    try:
        SY.send(stuck.base, [offer(1, now)])
        eq('a write that cannot happen is refused', 'accepted', 'refused')
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', 'replace')
        eq('a write that cannot happen is refused', e.code, 500)
        ok_('...and says which errno, not just that it failed',
            'ENOTDIR' in detail or 'EACCES' in detail or 'ENOENT' in detail)
finally:
    stuck.close()

# --- out of range, which is most of a shift ---------------------------------
dead = 'http://127.0.0.1:%d' % free_port()
eq('an unreachable far end reports nothing rather than raising',
   SY.newest_at(dead), None)

argv = sys.argv
sys.argv = ['sync', '--to', dead, '--journal', pi, '--quiet']
try:
    eq('...and the timer job exits quietly, because a car is offline a lot',
       SY.main(), 0)
finally:
    sys.argv = argv

# --- a token, for the day the far end leaves the VPN ------------------------
guarded = FarEnd(token='letmein')
try:
    rows = SY.rows_since(pi, 0)
    try:
        SY.send(guarded.base, rows)
        eq('an upload with no token is refused', 'accepted', 'refused')
    except urllib.error.HTTPError as e:
        eq('an upload with no token is refused', e.code, 403)
    eq('nothing was written', len(lines(guarded.journal)), 0)

    try:
        SY.send(guarded.base, rows, token='wrong')
        eq('a wrong token is refused', 'accepted', 'refused')
    except urllib.error.HTTPError as e:
        eq('a wrong token is refused', e.code, 403)

    eq('the right token is accepted',
       SY.send(guarded.base, rows, token='letmein')['added'], len(rows))
finally:
    guarded.close()

shutil.rmtree(work, ignore_errors=True)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d sync checks passed' % ok)
sys.exit(1 if bad else 0)
