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
    sent, _unreadable = SY.rows_since(pi, 0)
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

    # ...and the pairing, which is the same shape as a mark — an id and no seq
    # — and is the row a shift driven to test the stacking advice exists to
    # produce. Dropped here, the box at home would hold the offers and none of
    # the advice, which is the whole of the evidence.
    pair = {'v': 1, 'at': now + 3, 'kind': 'pair', 'id': 'off99',
            'held': {'pay': 12.0, 'minutes': 30.0, 'dropoff': 'Oak Ln, Marietta',
                     'scanned': True, 'heldMs': 60000},
            'offer': {'pay': 9.0, 'minutes': 20.0,
                      'dropoff': 'Chastain Rd NW, Kennesaw', 'pickup': None},
            'stack': {'pay': 17.4, 'worst': 20.9, 'best': 34.8, 'minMinutes': 30,
                      'maxMinutes': 50, 'state': 'warn', 'sure': True,
                      'ends': 'elsewhere'}}
    paired = SY.send(far.base, [pair])
    eq('a pairing crosses over', paired['added'], 1)
    eq('...with nothing refused', paired['malformed'], 0)
    stored = lines(far.journal)
    ok_('...and the advice it recorded is there',
        any(r.get('kind') == 'pair'
            and (r.get('stack') or {}).get('ends') == 'elsewhere'
            for r in stored))
    eq('...and sending it again adds nothing',
       SY.send(far.base, [pair])['added'], 0)
    # Two pairings for one offer are a real thing - the same card judged again
    # against a different order - and they must not collapse onto each other.
    pair2 = dict(pair, at=now + 4)
    eq('a second pairing for the same offer is its own row',
       SY.send(far.base, [pair2])['added'], 1)
    stored = lines(far.journal)

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
    eq('--all is safe', SY.send(far.base, SY.rows_since(pi, 0)[0])['added'], 0)

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

# --- one row from a phone with a wrong clock ---------------------------------
#
# `at` on a browser row is the phone's own Date.now() (journal-client.js), so a
# phone whose clock is wrong stamps a moment that never happened into the
# append-only journal, where nothing can go back and edit it.
#
# /api/journal/newest answered with it. The sender then resumes from an hour
# before a date in the year 5138, rows_since keeps nothing but the pre-NTP rows,
# and every real offer from that moment on is skipped — for ever, because
# nothing ever looks further back.
#
# The silence is the worst of it. The shortfall check anchors its own window to
# the same poisoned `newest`, so both sides count the one bad row and agree;
# the run exits 0, says "nothing new" (suppressed by --quiet in the installed
# unit) and refreshes the .synced stamp, so doctor.py reports a backup made
# minutes ago. The only copy of the one file that cannot be regenerated stops
# growing while both ends report success.
future = FarEnd()
try:
    poisoned = os.path.join(work, 'poisoned.jsonl')
    good = [offer(800 + i, now - (10 - i) * 60000) for i in range(10)]
    # 1 Jan 2100 is the ceiling this file already calls "a moment in this
    # century"; one millisecond past it is not a position in the offers.
    # Not named `bad`: this suite keeps its failure count in a global of that
    # name, and a local one here makes the final tally a dict.
    poison = offer(899, 4102444800001)
    write(poisoned, good[:5] + [poison] + good[5:])

    eq('a moment that never happened is not the resume point',
       SY.far_end(future.base).get('newest'), 0)

    argv = sys.argv
    sys.argv = ['sync', '--to', future.base, '--journal', poisoned, '--quiet',
                '--no-config']
    try:
        eq('the sync runs', SY.main(), 0)
    finally:
        sys.argv = argv
    # THE check. Without the ceiling the copy holds the poison row and nothing
    # else, and says ok.
    copied = [r for r in lines(future.journal) if not r.get('kind')]
    eq('...and every real offer still reaches the copy', len(copied), 11)

    # ...and the anchor it leaves behind is a real moment, so the NEXT run
    # resumes from somewhere that exists rather than from the year 5138.
    anchor = SY.far_end(future.base).get('newest')
    eq('the resume point is the newest offer that really happened',
       anchor, max(r['at'] for r in good))
finally:
    future.close()

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
    # An older build has no notes door to pull from, and that is the same as
    # having nothing to say: the run must not append anything on this side
    # or complain about it.
    before_old = len(lines(pi))
    code_pull, said_pull = run_main(old.base, pi, ['--local', 'http://127.0.0.1:1'])
    eq('...and an old copy with no tags door changes nothing here',
       len(lines(pi)), before_old)
    ok_('...quietly', 'tag' not in said_pull)
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
    rows, _unreadable = SY.rows_since(pi, 0)
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

# --- the driver's tags come back from the copy ------------------------------
#
# The sync ran one way. A tick made on the copy at home stayed there, and the
# rig's offers page showed that week untagged. Two real servers: `home` is the
# copy, `rig` is this machine's own server, and the run is the timer's.
T = 1_750_000_000_000
OFFER = {'v': 1, 'id': 'o1', 'seq': 1, 'at': T, 'firstAt': T, 'pay': 16.05,
         'minutes': 23.0, 'miles': 8.4, 'perHour': 34.2, 'whole': True,
         'target': 25, 'band': 15, 'costPerMile': 0.35, 'cost': 2.94}
home, rig = FarEnd(), FarEnd()
try:
    def shown(base):
        body = urllib.request.urlopen(base + '/api/journal?days=0', timeout=5).read()
        rows = json.loads(body.decode('utf-8'))['offers']
        return {r['id']: r.get('accepted') for r in rows}

    write(rig.journal, [OFFER])
    write(home.journal, [OFFER,
                         {'kind': 'mark', 'id': 'o1', 'at': T + 3600000, 'accepted': True}])
    code, said = run_main(home.base, rig.journal, ['--local', rig.base])
    eq('the run still exits 0', code, 0)
    marks = [r for r in lines(rig.journal) if r.get('kind') == 'mark']
    eq('a tick made on the copy comes back to the rig', len(marks), 1)
    eq('...as written', (marks[0].get('id'), marks[0].get('accepted')), ('o1', True))
    eq('...and the rig\'s offers page shows the offer taken', shown(rig.base).get('o1'), True)
    before = len(lines(rig.journal))
    run_main(home.base, rig.journal, ['--local', rig.base])
    eq('a second run adds nothing', len(lines(rig.journal)), before)

    # A tick in the car after an un-tick at home. The un-tick arrives on the
    # rig later — appended last — and must not win by being last: marks fold
    # by when they were made. And the tick goes the other way on the same
    # run, so both copies agree.
    with open(home.journal, 'a') as fh:
        fh.write(json.dumps({'kind': 'mark', 'id': 'o1', 'at': T + 5400000,
                             'accepted': False}) + '\n')
    with open(rig.journal, 'a') as fh:
        fh.write(json.dumps({'kind': 'mark', 'id': 'o1', 'at': T + 7200000,
                             'accepted': True}) + '\n')
    run_main(home.base, rig.journal, ['--local', rig.base])
    on_rig = [r for r in lines(rig.journal) if r.get('kind') == 'mark']
    eq('the older un-tick did come across', len(on_rig), 3)
    eq('...and is the last row on the rig', on_rig[-1].get('accepted'), False)
    eq('...but the newer tick made in the car is what the rig shows',
       shown(rig.base).get('o1'), True)
    eq('...and what the copy shows, having received it', shown(home.base).get('o1'), True)

    # ...and the same for a RULE, which hides every card like this one. Marks
    # fold by when they were made; rules were replayed in file order, last in
    # the file winning, with `at` never looked at — and rules travel over this
    # same two-way sync, so on whichever machine did not make the newer one the
    # older one lands last.
    #
    # The driver's "put this back" made at 11:00 was therefore reverted by
    # their own "hide every card like this" from 10:00, as soon as the sync
    # carried it across. Those offers then drop out of the median, the count
    # and the CSV, and /api/today carries no hidden count at all — so the
    # driving screen just reads short.
    def hidden_of(base, offer_id):
        body = urllib.request.urlopen(base + '/api/journal?days=0&hidden=1',
                                      timeout=5).read()
        rows = json.loads(body.decode('utf-8'))['offers']
        for r in rows:
            if r.get('id') == offer_id:
                return bool(r.get('hidden'))
        return None

    MATCH = {'pay': OFFER['pay'], 'minutes': OFFER['minutes'],
             'miles': OFFER['miles']}
    # Newer, on the copy: put it back.
    with open(home.journal, 'a') as fh:
        fh.write(json.dumps({'kind': 'rule', 'at': T + 11000000,
                             'match': MATCH, 'hidden': False}) + '\n')
    # Older, in the car: hide every card like this.
    with open(rig.journal, 'a') as fh:
        fh.write(json.dumps({'kind': 'rule', 'at': T + 10000000,
                             'match': MATCH, 'hidden': True}) + '\n')
    run_main(home.base, rig.journal, ['--local', rig.base])
    _rules_on_rig = [r for r in lines(rig.journal) if r.get('kind') == 'rule']
    eq('the older hide-rule did come across', len(_rules_on_rig), 2)
    eq('...and is not the last row, the newer one having arrived',
       _rules_on_rig[-1].get('hidden'), False)
    eq('the newer put-this-back is what the rig shows',
       hidden_of(rig.base, OFFER['id']), False)
    eq('...and what the copy shows', hidden_of(home.base, OFFER['id']), False)

    # The other direction, so this is a rule about time and not about False
    # winning: an older un-hide must not beat a newer hide either.
    with open(rig.journal, 'a') as fh:
        fh.write(json.dumps({'kind': 'rule', 'at': T + 12000000,
                             'match': MATCH, 'hidden': True}) + '\n')
    run_main(home.base, rig.journal, ['--local', rig.base])
    eq('a newer hide beats the older put-this-back',
       hidden_of(rig.base, OFFER['id']), True)

    # An offer typed on the copy's keypad, or read by a phone's scanner pointed
    # at the copy, is a row nothing but a browser wrote — and like a mark it
    # existed only where that browser was pointed. It comes back the same way.
    with open(home.journal, 'a') as fh:
        fh.write(json.dumps({'v': 1, 'id': 'kabc123', 'seq': 1, 'at': T + 8000000,
                             'firstAt': T + 8000000, 'pay': 9.0, 'minutes': 12.0,
                             'perHour': 45.0, 'whole': True, 'typed': True}) + '\n')
    run_main(home.base, rig.journal, ['--local', rig.base])
    ok_('an offer typed on the copy comes back as an offer',
        'kabc123' in shown(rig.base))

    # --no-pull is the old behaviour, for anyone who wants it.
    with open(home.journal, 'a') as fh:
        fh.write(json.dumps({'kind': 'mark', 'id': 'o1', 'at': T + 9000000,
                             'hidden': True}) + '\n')
    before = len(lines(rig.journal))
    run_main(home.base, rig.journal, ['--local', rig.base, '--no-pull'])
    eq('--no-pull brings nothing back', len(lines(rig.journal)), before)
    run_main(home.base, rig.journal, ['--local', rig.base])
    eq('...and the next ordinary run does', len(lines(rig.journal)), before + 1)

    # This rig's own server not answering is a standing fault, not the chatter
    # of a timer in a car: the copy has tags to give and they will never
    # arrive until somebody hears. The timer runs --quiet, so it goes to
    # stderr — and the run still exits 0, because the offers still went.
    with open(home.journal, 'a') as fh:
        fh.write(json.dumps({'kind': 'mark', 'id': 'o1', 'at': T + 10800000,
                             'accepted': True}) + '\n')
    before = len(lines(rig.journal))
    code, said = run_main(home.base, rig.journal, ['--local', 'http://127.0.0.1:1'])
    eq('a rig whose own server will not answer still exits 0', code, 0)
    ok_('...but says so past --quiet (%r)' % said[:80], 'not brought back' in said)
    ok_('...naming the setting to check', 'SYNC_LOCAL' in said)
    eq('...and brought nothing back', len(lines(rig.journal)), before)
    # ...and the way back once it does answer. The floor moves with the copy's
    # newest offer, so a tag left behind for more than an hour of driving is
    # below every later run's floor: an ordinary run never reaches it again,
    # and the message has to say which run does.
    ok_('...and names the run that reaches a tag the floor has passed',
        '--all' in said)
    # A day before the copy's newest offer: the floor is an hour before it.
    OLD = T - 86400000
    with open(home.journal, 'a') as fh:
        fh.write(json.dumps({'kind': 'mark', 'id': 'o1', 'at': OLD,
                             'hidden': True}) + '\n')

    def old_tag_on_rig():
        return any(r.get('kind') == 'mark' and r.get('at') == OLD
                   for r in lines(rig.journal))

    run_main(home.base, rig.journal, ['--local', rig.base])
    ok_('a tag older than the floor is out of an ordinary run\'s reach',
        not old_tag_on_rig())
    run_main(home.base, rig.journal, ['--local', rig.base, '--all'])
    ok_('...and --all brings it back', old_tag_on_rig())
finally:
    home.close()
    rig.close()

# --- the journal is parsed once, and then only the part that grew ----------
#
# readJournal keeps what it parsed and reads only the bytes past the last
# complete line. The cases that can go wrong are the ones where the file did
# not simply grow: a line still being written, a roll to a smaller file, and a
# backup restored over the top — a different inode that happens to be larger.
def have(base):
    body = urllib.request.urlopen(base + '/api/journal/newest', timeout=5).read()
    return json.loads(body.decode('utf-8')).get('have')

def ids(base):
    body = urllib.request.urlopen(base + '/api/journal?days=0', timeout=5).read()
    return sorted(r['id'] for r in json.loads(body.decode('utf-8'))['offers'])

def row(i):
    return {'v': 1, 'id': 'g%d' % i, 'seq': 1, 'at': T + i * 60000, 'pay': 9.0,
            'minutes': 20.0, 'perHour': 27.0, 'whole': True}

grow = FarEnd()
try:
    write(grow.journal, [row(1), row(2), row(3)])
    eq('three rows read', have(grow.base), 3)
    with open(grow.journal, 'a') as fh:
        fh.write(json.dumps(row(4)) + '\n')
    eq('a fourth appended is seen without re-reading the first three',
       have(grow.base), 4)
    # A line the scanner is half way through writing. Parsed if it parses —
    # it does not — and read again when it is finished, once.
    half = json.dumps(row(5))
    with open(grow.journal, 'a') as fh:
        fh.write(half[:len(half) // 2])
    eq('a line still being written is not a row yet', have(grow.base), 4)
    with open(grow.journal, 'a') as fh:
        fh.write(half[len(half) // 2:] + '\n')
    eq('...and is one row when it is finished', have(grow.base), 5)
    eq('...exactly once', ids(grow.base).count('g5'), 1)
    # A complete last line with no newline after it is a row, as it always
    # was — and still one row after something follows it.
    with open(grow.journal, 'a') as fh:
        fh.write(json.dumps(row(6)))
    eq('a finished line with no newline yet is a row', have(grow.base), 6)
    with open(grow.journal, 'a') as fh:
        fh.write('\n' + json.dumps(row(7)) + '\n')
    eq('...and is still one row once the file moves on', ids(grow.base).count('g6'), 1)
    eq('...with the next one after it', have(grow.base), 7)
    # The roll: journal.py replaces the file with a smaller one.
    write(grow.journal, [row(8), row(9)])
    eq('a smaller file is read from the start', have(grow.base), 2)
    eq('...and holds only what it holds', ids(grow.base), ['g8', 'g9'])
    # A backup restored over the top: a different inode, and larger, so a
    # tail read would append the middle of some other file to the old rows.
    fresh = grow.journal + '.restore'
    write(fresh, [row(10), row(11), row(12), row(13)])
    os.replace(fresh, grow.journal)
    eq('a file replaced underneath is read from the start', ids(grow.base),
       ['g10', 'g11', 'g12', 'g13'])
    # ...and rewritten IN PLACE — `cp backup journal` — which keeps the inode
    # and here leaves the file larger, exactly the shape of an append. The
    # bytes before the old offset are not the bytes that were parsed, and
    # that is how it is told apart. The first version of the reader took this
    # for an append and served three offers where there were two.
    write(grow.journal, [row(20), row(21), row(22), row(23), row(24), row(25)])
    eq('a file rewritten in place, larger, is read from the start',
       ids(grow.base), ['g20', 'g21', 'g22', 'g23', 'g24', 'g25'])
    write(grow.journal, [row(30), row(31)])
    eq('...and smaller', ids(grow.base), ['g30', 'g31'])
finally:
    grow.close()

# --- the stamp: when the copy was last reached -------------------------------
#
# A copy machine that rebooted looked exactly like a car out of range, and
# nothing on the rig ever said how old the last backup was. A run that reaches
# the copy stamps `<journal>.synced`; one that does not leaves it alone.
stamp_far = FarEnd()
try:
    work3 = tempfile.mkdtemp()
    j3 = os.path.join(work3, 'journal.jsonl')
    write(j3, [offer(1, now - 60000)])
    eq('no stamp before the first run', SY.last_synced(j3), None)
    run_main(stamp_far.base, j3)
    first = SY.last_synced(j3)
    ok_('a run that reaches the copy stamps the journal', first is not None)
    eq('...naming where it went', (first or {}).get('to'), stamp_far.base)
    eq('...and what the copy holds', (first or {}).get('have'), 1)
    time.sleep(0.01)
    run_main(stamp_far.base, j3)
    second = SY.last_synced(j3)
    ok_('...and a run with nothing new stamps it again',
        second is not None and second['at'] >= first['at'])
    run_main('http://127.0.0.1:1', j3)
    eq('a run that cannot reach the copy leaves the stamp alone',
       SY.last_synced(j3), second)
finally:
    stamp_far.close()

# --- --days bounds the second tick as well as the first ------------------------
#
# The first tick sent thirty days as promised; the second saw the rig holding
# more offers than the copy "up to that point" — the older ones, deliberately
# not sent — and sent everything from the start of the file.
days_far = FarEnd()
try:
    work4 = tempfile.mkdtemp()
    j4 = os.path.join(work4, 'journal.jsonl')
    write(j4, [offer(i, now - i * 86400000) for i in range(60)])
    run_main(days_far.base, j4, ['--days', '30'])
    first_tick = len(lines(days_far.journal))
    ok_('the first tick sends the window (%d rows)' % first_tick, 29 <= first_tick <= 31)
    run_main(days_far.base, j4, ['--days', '30'])
    eq('...and the second sends nothing more, rather than everything',
       len(lines(days_far.journal)), first_tick)
finally:
    days_far.close()

# --- a copy that is genuinely missing rows repairs itself -------------------
#
# The only backup of a file that cannot be regenerated, so the reconciliation
# matters more than anything else here. It had no test at all, and it was
# broken: windowing this rig's count to `--days` while still comparing it
# against the copy's ALL-TIME count meant the copy's number was always the
# larger one, so no shortfall could ever be seen. A gap of any size, from any
# cause, stayed open for ever while both ends reported success.
#
# Three shapes, because the fix has to do all three and the middle one is what
# the window was added for in the first place.
gap_far = FarEnd()
try:
    work5 = tempfile.mkdtemp()
    j5 = os.path.join(work5, 'journal.jsonl')
    # 120 offers, twelve hours apart: sixty days, so most of the file is
    # outside a thirty-day window.
    rig_rows = [offer(i, now - (120 - i) * 12 * 3600000) for i in range(120)]
    write(j5, rig_rows)
    # The copy holds all of it but five rows from inside the window.
    write(gap_far.journal, [r for i, r in enumerate(rig_rows)
                            if not (100 <= i < 105)])
    eq('the copy starts five rows short', len(lines(gap_far.journal)), 115)
    run_main(gap_far.base, j5, ['--days', '30'])
    eq('a real gap inside the window is closed on the next tick',
       len(lines(gap_far.journal)), 120)

    # ...and having closed it, the next tick is quiet. A repair that re-fires
    # every ten minutes for ever is the failure this replaced.
    before = len(lines(gap_far.journal))
    run_main(gap_far.base, j5, ['--days', '30'])
    eq('...and does not fire again once there is nothing to close',
       len(lines(gap_far.journal)), before)
finally:
    gap_far.close()

# The case the window exists for: the copy is complete INSIDE the window and
# has no older history, because the window is all it was ever offered. That is
# not a gap, and reading it as one re-sent the whole file every tick.
win_far = FarEnd()
try:
    work6 = tempfile.mkdtemp()
    j6 = os.path.join(work6, 'journal.jsonl')
    rig_rows = [offer(i, now - (120 - i) * 12 * 3600000) for i in range(120)]
    write(j6, rig_rows)
    cutoff = now - 30 * 86400000
    write(win_far.journal, [r for r in rig_rows if r['at'] >= cutoff])
    held = len(lines(win_far.journal))
    ok_('the copy holds only the window (%d rows)' % held, 55 <= held <= 65)
    run_main(win_far.base, j6, ['--days', '30'])
    eq('history older than the window is not a gap', len(lines(win_far.journal)), held)
    run_main(win_far.base, j6, ['--days', '30'])
    eq('...on the second tick either', len(lines(win_far.journal)), held)
finally:
    win_far.close()

# ...and against a copy that has not been updated yet, which cannot count a
# window and simply does not answer with one. Falling back to comparing whole
# files can re-send history the copy was never offered; it never misses a real
# gap. Noisy is recoverable, blind is not.
#
# The real far end throughout — its de-duplication is the half that decides
# whether a re-send costs anything — with only the one key the old build does
# not send stripped from the reply. Simulating the whole far end here would be
# testing a stub's arithmetic instead of the server's.
old_far = FarEnd()
try:
    work7 = tempfile.mkdtemp()
    j7 = os.path.join(work7, 'journal.jsonl')
    rig_rows = [offer(i, now - (120 - i) * 12 * 3600000) for i in range(120)]
    write(j7, rig_rows)
    write(old_far.journal, [r for i, r in enumerate(rig_rows)
                            if not (100 <= i < 105)])
    eq('the un-updated copy starts five rows short',
       len(lines(old_far.journal)), 115)
    real_far_end = SY.far_end

    def without_window(base, timeout=SY.TIMEOUT, since=None):
        body = real_far_end(base, timeout, since)
        if isinstance(body, dict):
            body = dict(body)
            body.pop('offersSince', None)
        return body

    SY.far_end = without_window
    try:
        run_main(old_far.base, j7, ['--days', '30'])
    finally:
        SY.far_end = real_far_end
    eq('a copy too old to count a window still has its gap closed',
       len(lines(old_far.journal)), 120)
finally:
    old_far.close()

# --- a journal nothing can read is not a journal with nothing in it ---------
#
# The worst shape this tool had. JR.Journal.rows() ends in a catch-all that
# returns [], so a file that could not be opened handed back the same answer as
# a quiet week. sync.py read that as "nothing new", exited 0, and stamped the
# copy fresh on the way out — and doctor.py then reported a healthy backup made
# minutes ago. The rig would have said everything was fine while nothing at all
# was being copied off it, which is the one direction this backup must never
# fail in.
_ur_dir = tempfile.mkdtemp()
# A DIRECTORY where the journal should be. Staged this way rather than with a
# chmod because these suites are often run as root, and a fixture root walks
# straight through is a check that cannot fail.
_not_a_file = os.path.join(_ur_dir, 'offers.jsonl')
os.mkdir(_not_a_file)

_ur_far = FarEnd()
try:
    _code, _said = run_main(_ur_far.base, _not_a_file)
    ok_('a journal that cannot be read is a failed run, not a quiet one (%r)' % _code,
        _code != 0)
    ok_('...saying what could not be read (%r)' % _said.strip()[:70],
        'could not be read' in _said)
    ok_('...and naming the file, since that is what has to be looked at',
        _not_a_file in _said)
    # The stamp is the whole point. doctor.py reads it and says how long ago
    # the offers were backed up; writing one here is the rig telling the driver
    # a backup happened when none did.
    eq('...and no backup stamp is left behind', SY.last_synced(_not_a_file), None)
    eq('...and nothing was sent to the copy', len(lines(_ur_far.journal)), 0)

    # ...while a journal that is genuinely empty is still an ordinary quiet
    # run, or the check above would just be refusing to work.
    _empty = os.path.join(_ur_dir, 'empty.jsonl')
    open(_empty, 'w').close()
    _code2, _said2 = run_main(_ur_far.base, _empty)
    eq('an empty journal is a quiet run, not a failure', _code2, 0)
    ok_('...and does get its stamp', SY.last_synced(_empty) is not None)
finally:
    _ur_far.close()
    shutil.rmtree(_ur_dir, ignore_errors=True)

# --- the offers read before the rig knew what time it was -------------------
#
# The Pi has no clock of its own: it boots in 1970 and jumps when the network
# arrives, and a card read in between is on disk stamped with a moment that
# never happened. Those rows were never backed up. Every ordinary tick sends
# from an hour before the copy's newest row — a number in the trillions — and a
# 1970 stamp is below it, so only a hand-run `--all` ever carried one.
#
# Nor could the shortfall check notice: both ends count inside the same window
# and a row with no date is in no window on either side, so the two counts
# agreed and nothing looked missing. Meanwhile the offers page tells the driver
# those rows are "still in the journal file on disk" — true, and on exactly one
# disk, the SD card in the car, which is the thing the backup is for.
_clock_far = FarEnd()
_clock_dir = tempfile.mkdtemp()
try:
    _cp = os.path.join(_clock_dir, 'journal.jsonl')
    _early = [dict(offer(90 + i, at), id='boot%d' % i)
              for i, at in enumerate((42000, 0, 1100))]
    _recent = [offer(i, now - i * 60000) for i in range(4)]
    write(_cp, _early + _recent)

    # The ordinary tick: a floor an hour before the copy's newest row.
    _floor = now - 3600000
    _sent, _ = SY.rows_since(_cp, _floor)
    _ids = [r['id'] for r in _sent]
    for _r in _early:
        ok_('a row read before the clock was set is sent on an ordinary tick '
            '(%s)' % _r['id'], _r['id'] in _ids)
    ok_('...and so are the ones the floor was for',
        all(r['id'] in _ids for r in _recent))
    # ...and nothing else has been let through with them. A floor that stopped
    # working would pass this file too.
    _old = os.path.join(_clock_dir, 'old.jsonl')
    write(_old, [offer(500, now - 86400000 * 30)] + _recent)
    _sent_old, _ = SY.rows_since(_old, _floor)
    eq('a dated row below the floor is still left alone',
       [r['id'] for r in _sent_old], [r['id'] for r in _recent])

    # End to end, against the real far end: they arrive, and they arrive once.
    _res = SY.send(_clock_far.base, _sent)
    eq('they reach the copy', _res['added'], len(_early) + len(_recent))
    _res2 = SY.send(_clock_far.base, _sent)
    eq('...and the next tick, which offers them again, adds nothing',
       _res2['added'], 0)
    eq('...leaving one of each on the copy',
       len(lines(_clock_far.journal)), len(_early) + len(_recent))
    _there = set(r['id'] for r in lines(_clock_far.journal))
    ok_('...including every one of the undated ones',
        all(r['id'] in _there for r in _early))
finally:
    _clock_far.close()
    shutil.rmtree(_clock_dir, ignore_errors=True)

# --- a body too big for the far end -----------------------------------------
#
# The cap this side chunks against and the cap the far end refuses at have to be
# the same limit in the same unit, or nothing holds them together. They were
# not: 2000 ROWS here against 8MB of BYTES there, tied by an estimate of how
# large a row is — an estimate that ages every time a field is added to what is
# worth keeping. And the way it failed is the worst one available: the far end
# reset the connection, a reset here is indistinguishable from being out of
# range, out of range is normal in a car and exits 0, so the only backup of the
# only irreplaceable thing on the rig would have stopped working permanently
# while every tick reported success.

# The chunker, first, on its own terms: it must fit the cap, keep every row, and
# keep them in order.
_rows = [offer(i, now - i * 1000) for i in range(200)]
_one = len((json.dumps(_rows[0], sort_keys=True) + '\n').encode('utf-8'))
_cap = _one * 7 + 3          # room for seven rows, not eight
_parts = list(SY.chunks(_rows, _cap))
eq('nothing is lost in the split', sum(len(p) for p in _parts), len(_rows))
eq('...and the order is the file order',
   [r['id'] for p in _parts for r in p], [r['id'] for r in _rows])
ok_('...and every body fits the cap',
    all(len(('\n'.join(json.dumps(r, sort_keys=True) for r in p) + '\n')
            .encode('utf-8')) <= _cap for p in _parts))
eq('...with the cap actually filled, not one row per body',
   max(len(p) for p in _parts), 7)

# A single row larger than the whole cap cannot be made to fit, and the only two
# things to do with it are drop it or send it. Dropping it loses a row in
# silence, which is the failure this limit exists to prevent. Sending it gets a
# refusal that says so.
_fat = dict(_rows[0], text='x' * (_cap * 2))
_fat_parts = list(SY.chunks([_rows[0], _fat, _rows[1]], _cap))
eq('a row too big for the cap is still sent, on its own',
   [len(p) for p in _fat_parts], [1, 1, 1])
eq('...and it is the row itself, not a stand-in',
   _fat_parts[1][0]['id'], _fat['id'])

# An empty list is not one empty POST.
eq('nothing to send is no bodies at all', list(SY.chunks([], _cap)), [])

# The cap is in the same unit as the far end's, and under it.
ok_('the chunk cap is bytes, and inside the 8MB the far end refuses at',
    0 < SY.MAX_CHUNK_BYTES <= 8 * 1024 * 1024)

_big_far = FarEnd()
_big_dir = tempfile.mkdtemp()
try:
    # The end-to-end half: a journal that does not fit in one POST still arrives
    # whole. The real far end, the real chunker, a cap small enough to force
    # several round trips.
    _big = os.path.join(_big_dir, 'journal.jsonl')
    _many = [offer(i, now - i * 1000) for i in range(300)]
    write(_big, _many)
    _sent, _ = SY.rows_since(_big, 0)
    _was, SY.MAX_CHUNK_BYTES = SY.MAX_CHUNK_BYTES, _one * 7 + 3
    try:
        _res = SY.send(_big_far.base, _sent)
    finally:
        SY.MAX_CHUNK_BYTES = _was
    eq('a journal too big for one POST still arrives whole', _res['added'], 300)
    eq('...and is stored once each', len(lines(_big_far.journal)), 300)
    eq('...and the count reported is the last chunk\'s, which is the true one',
       _res['have'], 300)

    # And the refusal itself, which is what made the row-count cap dangerous
    # rather than merely imprecise. A body over the far end's own limit has to
    # come back as something readable — an HTTP answer — and not as a reset that
    # this side would file under "out of range" and exit 0 on.
    _huge = (json.dumps(_many[0], sort_keys=True) + '\n').encode('utf-8')
    _huge = _huge * (9 * 1024 * 1024 // len(_huge) + 1)
    _req = urllib.request.Request(
        _big_far.base + '/api/journal/ingest', data=_huge, method='POST',
        headers={'Content-Type': 'application/x-ndjson'})
    try:
        urllib.request.urlopen(_req, timeout=30).read()
        _refusal = 'accepted'
    except urllib.error.HTTPError as e:
        _refusal = 'http %d' % e.code
    except (urllib.error.URLError, OSError) as e:
        # This is the old behaviour, and the point: sync.main() treats OSError
        # as "lost the connection — will try again next time" and exits 0.
        _refusal = 'reset (%s)' % type(e).__name__
    eq('a body over the far end\'s cap is refused in words, not by a reset',
       _refusal, 'http 400')

    # ...and that refusal reaches send() as the error main() exits non-zero on,
    # rather than as the OSError it files under "out of range" and exits 0 on.
    # Driven through send() with this side's cap lifted above the far end's,
    # which is the shape a mismatched pair of limits has.
    _over = os.path.join(_big_dir, 'over.jsonl')
    write(_over, _many)
    _was2, SY.MAX_CHUNK_BYTES = SY.MAX_CHUNK_BYTES, 64 * 1024 * 1024
    try:
        _sent2, _ = SY.rows_since(_over, 0)
        _sent2 = [dict(r, text='y' * 30000) for r in _sent2]
        try:
            SY.send(_big_far.base, _sent2)
            _too = 'accepted'
        except urllib.error.HTTPError as e:
            _too = 'http %d' % e.code
        except (urllib.error.URLError, OSError) as e:
            _too = 'reset (%s)' % type(e).__name__
    finally:
        SY.MAX_CHUNK_BYTES = _was2
    eq('...so an oversized chunk raises the error send() cannot mistake for '
       'being out of range', _too, 'http 400')

    # The honest boundary of that, so nobody reads the two checks above as a
    # promise the far end cannot keep. Node stops feeding the request once the
    # response is finished, so a body far past the cap still breaks the pipe on
    # the way out and lands back in the "out of range" arm. It is unfixable from
    # the far end and it is why the cap on THIS side has to be real: a sender
    # that chunks by bytes never gets here in the first place.
    _wild = (json.dumps(_many[0], sort_keys=True) + '\n').encode('utf-8')
    _wild = _wild * (32 * 1024 * 1024 // len(_wild) + 1)
    _req2 = urllib.request.Request(
        _big_far.base + '/api/journal/ingest', data=_wild, method='POST',
        headers={'Content-Type': 'application/x-ndjson'})
    try:
        urllib.request.urlopen(_req2, timeout=30).read()
        _far_past = 'accepted'
    except urllib.error.HTTPError as e:
        _far_past = 'http %d' % e.code
    except (urllib.error.URLError, OSError):
        _far_past = 'broken'
    ok_('a body far past the cap still breaks the pipe, which is why the '
        'sender chunks', _far_past in ('broken', 'http 400'))

    # And the reason none of that is reachable in normal service: the rows a
    # real journal holds, chunked by the real cap, make bodies the far end takes.
    _real = list(SY.chunks(_many))
    eq('a whole ordinary journal is one body', len(_real), 1)
    ok_('...and it is nowhere near the far end\'s limit',
        len(('\n'.join(json.dumps(r, sort_keys=True) for r in _real[0]) + '\n')
            .encode('utf-8')) < SY.MAX_CHUNK_BYTES)
finally:
    _big_far.close()
    shutil.rmtree(_big_dir, ignore_errors=True)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d sync checks passed' % ok)
sys.exit(1 if bad else 0)
