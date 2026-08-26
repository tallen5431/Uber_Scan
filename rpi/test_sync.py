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
                # /api/status, not /api/journal/newest: this is a liveness
                # probe, and `newest` is a data endpoint that is *supposed* to
                # fail when the journal path is unusable — which is exactly the
                # case two of the tests below set up on purpose.
                urllib.request.urlopen(self.base + '/api/status', timeout=1).read()
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

    # --- what the driver typed, rather than what the camera read -------
    # The rows a person makes by hand: 'I took this one', and 'stop showing me
    # my own test card'. They are the only rows in the journal that carry
    # judgement rather than measurement, and they were the ones being dropped —
    # a mark has an id but no seq, a rule has neither, and the sync demanded
    # both. A shift's worth of tags went nowhere, silently, under a malformed
    # count nobody looks at.
    mark = {'v': 1, 'at': now + 1, 'kind': 'mark', 'id': 'off99', 'accepted': True}
    rule = {'v': 1, 'at': now + 2, 'kind': 'rule', 'hidden': True,
            'match': {'pay': 3.0, 'minutes': 30.0, 'miles': 12.0}}
    tags = SY.send(far.base, [mark, rule])
    eq('an offer marked as taken crosses over', tags['added'], 2)
    eq('...with nothing refused', tags['malformed'], 0)
    stored = lines(far.journal)
    ok_('...and the mark is there', any(r.get('kind') == 'mark'
                                        and r.get('accepted') is True
                                        for r in stored))
    ok_('...and so is the rule', any(r.get('kind') == 'rule' for r in stored))

    # Tags are re-sent on every tick alongside the offers, so a second run must
    # not double them — a card marked taken twice is a card counted twice.
    eq('sending the tags again adds nothing', SY.send(far.base, [mark, rule])['added'], 0)
    eq('...and does not duplicate them', len(lines(far.journal)), len(stored))

    # Changing your mind is a new note, not the same one.
    undo = dict(mark, at=now + 3, accepted=False)
    eq('...but changing your mind is new', SY.send(far.base, [undo])['added'], 1)

    # A mark names an offer; a reading of that offer is a different row that
    # happens to share the id. Neither may stand in for the other.
    eq('a mark does not stand in for a reading of the same offer',
       SY.send(far.base, [offer(99, now, seq=1)])['added'], 1)

    # A kind this build has never heard of is carried across rather than
    # dropped, as long as it says which row it is: the copy outlives the build.
    eq('a row from a newer build is kept, not discarded',
       SY.send(far.base, [{'v': 2, 'kind': 'weather', 'id': 'w1', 'seq': 1,
                           'at': now}])['added'], 1)

    # A mark with no offer to name cannot be de-duplicated or applied.
    eq('a mark naming nothing is still refused',
       SY.send(far.base, [{'v': 1, 'at': now, 'kind': 'mark', 'accepted': True}])['malformed'], 1)

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
                # /api/status, not /api/journal/newest: this is a liveness
                # probe, and `newest` is a data endpoint that is *supposed* to
                # fail when the journal path is unusable — which is exactly the
                # case two of the tests below set up on purpose.
                urllib.request.urlopen(self.base + '/api/status', timeout=1).read()
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

    # The calibration rides along with the offers and used to report the same
    # failure as a bare 'HTTP Error 500: Internal Server Error', which sends
    # somebody to read a log on the other machine to learn what the offers had
    # already said in plain words on this one.
    cfg3 = os.path.join(work, 'cfg3.json')
    with open(cfg3, 'w') as fh:
        json.dump({'quad': [[1, 1], [2, 1], [2, 2], [1, 2]]}, fh)
    refused = SY.send_config(stuck.base, cfg3)
    ok_('a calibration that cannot be stored is not reported as stored',
        not refused.get('ok'))
    ok_('...and says why, like the offers do',
        any(e in (refused.get('error') or '')
            for e in ('ENOTDIR', 'EACCES', 'ENOENT')))
finally:
    stuck.close()

# --- a tag made on the copy machine must not skip the rig's offers -----------
# The sender resumes from an hour before the far end's newest row, so "newest"
# has to mean "how far through the offers I am". Every row counted equally, and
# the driver's own tags are rows: ticking "I took this" on the copy machine
# stamped a row with the current time, the rig resumed from an hour before
# *that*, and every unsent offer older than an hour was stepped over —
# permanently, because nothing ever looks further back. One tap could cost a
# day of offers.
tagged = FarEnd()
try:
    old_at = now - 6 * 3600000
    SY.send(tagged.base, [offer(500, old_at)])
    eq('the copy holds one old offer', len(lines(tagged.journal)), 1)

    # The driver ticks it on the copy machine, right now.
    mark_now = {'v': 1, 'at': now, 'kind': 'mark', 'id': 'off500', 'accepted': True}
    SY.send(tagged.base, [mark_now])

    eq('a tag made now does not become the offer watermark',
       SY.newest_at(tagged.base), old_at)
    ok_('...and the copy says how many offers it holds',
        SY.far_end(tagged.base).get('offers') == 1)

    # Offers from four hours ago, never sent. With the watermark at `now` these
    # were skipped for good.
    stranded = os.path.join(work, 'stranded.jsonl')
    write(stranded, [offer(500, old_at)]
                    + [offer(600 + i, now - 4 * 3600000 + i * 1000) for i in range(5)])
    argv = sys.argv
    sys.argv = ['sync', '--to', tagged.base, '--journal', stranded, '--quiet',
                '--no-config']
    try:
        eq('the sync runs', SY.main(), 0)
    finally:
        sys.argv = argv
    kept = [r for r in lines(tagged.journal) if not r.get('kind')]
    eq('...and the offers the tag would have stranded arrive', len(kept), 6)
finally:
    tagged.close()

# --- a copy that is behind repairs itself ------------------------------------
# A run that died half way, a clock that went backwards, a card restored from an
# older backup: the far end ends up holding fewer offers than the rig, and
# resuming from an hour before its newest row steps straight over the gap. Two
# integers already in a reply the sync makes anyway are enough to notice.
behind = FarEnd()
try:
    gappy = os.path.join(work, 'gappy.jsonl')
    rows = [offer(700 + i, now - (20 - i) * 60000) for i in range(20)]
    write(gappy, rows)
    # Only the newest three ever made it across.
    SY.send(behind.base, rows[-3:])
    eq('the copy is behind', SY.far_end(behind.base).get('offers'), 3)

    argv = sys.argv
    sys.argv = ['sync', '--to', behind.base, '--journal', gappy, '--quiet',
                '--no-config']
    try:
        eq('the sync runs', SY.main(), 0)
    finally:
        sys.argv = argv
    eq('...and closes the gap without anyone running --all',
       len([r for r in lines(behind.journal) if not r.get('kind')]), 20)
finally:
    behind.close()

# --- rows that cannot say which row they are ---------------------------------
# `undefined` was the only thing refused, so `id: null` sailed through and every
# id-less row in a batch collapsed onto one key: the first was stored and the
# rest thrown away as duplicates of it.
nulls = FarEnd()
try:
    two = [{'v': 1, 'id': None, 'seq': 1, 'at': now, 'pay': 10.0, 'minutes': 20.0},
           {'v': 1, 'id': None, 'seq': 1, 'at': now + 1, 'pay': 99.0, 'minutes': 20.0}]
    result = SY.send(nulls.base, two)
    eq('a row with a null id is not stored', result['added'], 0)
    eq('...and both are counted, not silently deduplicated', result['malformed'], 2)

    # An id containing the separator the key used to be joined with.
    forged = [{'v': 1, 'id': 'a/1', 'seq': 2, 'at': now, 'pay': 10.0},
              {'v': 1, 'id': 'a', 'seq': '1/2', 'at': now + 1, 'pay': 99.0}]
    eq('an id containing a slash cannot forge another row s key',
       SY.send(nulls.base, forged)['added'], 2)
finally:
    nulls.close()

# --- which end is out of date -----------------------------------------------
# The rig lost two rounds to this. The copy machine was running a build from
# before the directory was created for it, and the only evidence was that the
# error said 'could not append' where the current build says 'could not append
# (ENOENT)'. Nobody should have to diff error strings across two machines, so
# the far end now states what it can do and the sender says which end is behind.
class OldBuild(object):
    """A far end from before any of this: no capabilities, no errno."""

    def __init__(self):
        import http.server
        import threading

        class Handler(http.server.BaseHTTPRequestHandler):
            def _json(self, code, body):
                raw = json.dumps(body).encode('utf-8')
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                self._json(200, {'ok': True, 'newest': 0, 'have': 0})

            def do_POST(self):
                self.rfile.read(int(self.headers.get('Content-Length') or 0))
                self._json(500, {'ok': False, 'error': 'could not append'})

            def log_message(self, *a):
                pass

        self.httpd = http.server.HTTPServer(('127.0.0.1', 0), Handler)
        self.base = 'http://127.0.0.1:%d' % self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever)
        self.thread.daemon = True
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def run_main(base, journal, extra=()):
    """SY.main() as the timer runs it, with whatever it complained about."""
    import io
    argv, err = sys.argv, sys.stderr
    sys.argv = ['sync', '--to', base, '--journal', journal, '--quiet',
                '--no-config'] + list(extra)
    sys.stderr = io.StringIO()
    try:
        return SY.main(), sys.stderr.getvalue()
    finally:
        sys.argv, sys.stderr = argv, err


old = OldBuild()
try:
    eq('an old far end has no capabilities to report',
       SY.far_end(old.base).get('can'), None)
    code, said = run_main(old.base, pi)
    eq('a refused upload is worth a non-zero exit', code, 1)
    ok_('...and the refusal is quoted', 'could not append' in said)
    ok_('...and it says which machine is behind', 'older build' in said)
finally:
    old.close()

# The same failure against a current build must not blame the far end for being
# old, or the message sends somebody to update a machine that is already current.
stuck2 = FarEndAt(os.path.join(blocked, 'journal.jsonl'))
try:
    ok_('a current far end says what it can do',
        'mkdir' in (SY.far_end(stuck2.base).get('can') or []))
    code, said = run_main(stuck2.base, pi)
    eq('...a refusal from it still exits non-zero', code, 1)
    ok_('...and does not send anyone to update it', 'older build' not in said)
finally:
    stuck2.close()

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


# --- a journal that cannot be read is not an empty journal ------------------
#
# The far end de-duplicates by building a set of what it already holds, which is
# what makes ingest idempotent and is called "the whole design" where it is
# written. The rows come from readJournal, and readJournal answered [] to every
# error — including a journal that is there and unreadable. An empty set makes
# every incoming row look new.
#
# Reproduced against the real server before the fix, running as a user that
# could append to the journal but not read it: twenty rows on disk, the same
# twenty POSTed three times, `ok: true, added: 20` each time, and eighty lines
# on disk afterwards. And /api/journal/newest answered 0, which sends the rig
# back to a thirty-day floor — so it re-sends a month of offers every ten
# minutes and the far end appends all of them, both ends reporting success.
#
# Needs a process that cannot read a file it can append to, so: drop privileges
# where we have them to drop, use the mode directly where we are already an
# ordinary user, and skip where neither is possible rather than pretend.
def _unprivileged():
    if os.geteuid() != 0:
        return []                       # the mode alone will do it
    if shutil.which('setpriv') is None:
        return None
    return ['setpriv', '--reuid=65534', '--regid=65534', '--clear-groups']


PREFIX = _unprivileged()
if PREFIX is None:
    print('cannot drop privileges here — skipping the unreadable-journal checks')
else:
    work = tempfile.mkdtemp()
    # The whole chain has to be traversable by whoever ends up running node.
    os.chmod(work, 0o777)
    proc = None
    try:
        path = os.path.join(work, 'journal.jsonl')
        rows = [offer(i, 1_700_000_000_000 + i) for i in range(6)]
        body = ''.join(json.dumps(r) + '\n' for r in rows)
        with open(path, 'w') as fh:
            fh.write(body)
        os.chmod(path, 0o222)           # appendable, not readable
        write(os.path.join(work, 'mine.jsonl'), rows)

        port = free_port()
        proc = subprocess.Popen(
            PREFIX + ['node', os.path.join(ROOT, 'server.js')],
            env=dict(os.environ, SCANNER='0', PORT=str(port), JOURNAL=path),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        base = 'http://127.0.0.1:%d' % port
        up = False
        for _ in range(120):
            try:
                urllib.request.urlopen(base + '/api/status', timeout=1).read()
                up = True
                break
            except Exception:
                time.sleep(0.1)

        if not up:
            print('the far end never came up — skipping the unreadable-journal checks')
        else:
            def post(where, payload):
                req = urllib.request.Request(
                    base + where, data=payload.encode('utf-8'), method='POST')
                try:
                    r = urllib.request.urlopen(req, timeout=10)
                    return r.status, json.loads(r.read().decode('utf-8'))
                except urllib.error.HTTPError as e:
                    return e.code, json.loads(e.read().decode('utf-8') or '{}')

            def get(where):
                try:
                    r = urllib.request.urlopen(base + where, timeout=10)
                    return r.status, json.loads(r.read().decode('utf-8'))
                except urllib.error.HTTPError as e:
                    return e.code, json.loads(e.read().decode('utf-8') or '{}')

            code, out = get('/api/journal/newest')
            eq('an unreadable journal still answers', code, 200)
            eq('...but not with "you have nothing"', out.get('newest'), None)
            eq('...it says it could not read', out.get('readable'), False)
            ok_('...and which way it failed', 'EACCES' in json.dumps(out))
            # Still a current build, and it has to be able to say so: a rig told
            # nothing about a reachable machine goes on to blame it for being
            # out of date, which sends somebody to update the wrong thing.
            ok_('...while still saying what it can do', 'mkdir' in (out.get('can') or []))

            # And the sender declines rather than piling copies into it.
            code2, said = run_main(base, os.path.join(work, 'mine.jsonl'))
            eq('the rig refuses to send into it', code2, 1)
            ok_('...and says why, in terms of the far end', 'cannot read' in said)

            before = len(rows)
            for attempt in (1, 2, 3):
                code, out = post('/api/journal/ingest', body)
                eq('ingest %d is refused rather than duplicating' % attempt, code, 500)
                eq('...and reports failure', out.get('ok'), False)

            os.chmod(path, 0o644)
            on_disk = [l for l in open(path).read().splitlines() if l.strip()]
            eq('nothing was appended by the three refusals', len(on_disk), before)

            # ...and the page a driver looks at says so, rather than showing an
            # empty history that looks like a quiet week.
            os.chmod(path, 0o222)
            code, out = get('/api/journal')
            eq('the offers page still answers', code, 200)
            eq('...with nothing in it', out.get('count'), 0)
            ok_('...and says why it is empty', out.get('unreadable'))
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        try:
            os.chmod(os.path.join(work, 'journal.jsonl'), 0o644)
        except OSError:
            pass
        shutil.rmtree(work, ignore_errors=True)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d sync checks passed' % ok)
sys.exit(1 if bad else 0)
