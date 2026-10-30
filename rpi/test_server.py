"""The server's own arithmetic, against the real server.

    python3 rpi/test_server.py

server.js is tested through the pages that use it — the offers page, the
driving screen, the sync — which is where its faults are seen. It leaves a
class of fault nothing was pointed at: the ones between two callers of the
same endpoint, or between two endpoints answering the same question. Two
journal reads in flight after one append; a body split across two TCP
segments; a count the offers page and the driving screen make differently for
one file; a status answer that disagrees with the event stream about the same
reading. Each of these was found by reading the code and then reproduced here,
and each check below failed before its fix.

Two servers: one with no scanner, for the journal and the body reader; one on
a fake scanner that reads a card, reads it again, then reads another, for the
order in the car.
"""

import json
import math
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The NucBox health probe (server.js nbxProbe) off in every server this
# suite starts, so no fake counts a probe among its questions; the
# checks of the probe itself turn it back on.
os.environ['NUCBOX_PROBE_MS'] = '0'
# Every server this suite starts would otherwise tidy the GPS logs of whoever
# runs it (server.js's tidyGpsLogs, ~/gpslog by default). Off for all of them;
# the section that checks the tidy names its own directory.
os.environ['GPSLOG_DIR'] = ''
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


def no_(name, cond):
    eq(name, bool(cond), False)


if shutil.which('node') is None:
    print('no node on this machine — skipping the server checks')
    sys.exit(0)


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def start(env, journal):
    port = free_port()
    proc = subprocess.Popen(
        ['node', os.path.join(ROOT, 'server.js')],
        env=dict(os.environ, PORT=str(port), HTTPS_PORT='0', JOURNAL=journal, **env),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = 'http://127.0.0.1:%d' % port
    for _ in range(120):
        try:
            urllib.request.urlopen(base + '/api/status', timeout=1).read()
            return proc, base
        except Exception:
            time.sleep(0.1)
    proc.kill()
    raise RuntimeError('the server never came up')


def stop(proc):
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()


def get(base, path):
    return json.loads(urllib.request.urlopen(base + path, timeout=5).read().decode('utf-8'))


def listen(base, seconds):
    """Collect what /api/events broadcasts, in the background, for a while.

    The panel is a reader of this stream and nothing else — live.html sets the
    ⌖ button's state straight off `msg.dropoff.line`. So "what does the driver
    end up believing" is a question about what leaves here, and polling
    /api/status cannot answer it: the status reflects what was STORED, and the
    whole class of fault here is the stream saying something the store refused.

    Its own thread, started before the scanner has anything to say, because the
    stream carries what happens next rather than what already has.
    """
    import threading
    seen = []

    def pump():
        try:
            fh = urllib.request.urlopen(base + '/api/events', timeout=seconds + 5)
            end = time.time() + seconds
            while time.time() < end:
                line = fh.readline()
                if not line:
                    break
                line = line.decode('utf-8', 'replace').strip()
                if line.startswith('data:'):
                    try:
                        seen.append(json.loads(line[5:].strip()))
                    except ValueError:
                        pass
        except Exception:
            pass

    t = threading.Thread(target=pump, daemon=True)
    t.start()
    return seen


def raw(base, path):
    """Status, body and headers — for the endpoints that are not JSON.

    The CSV is one of those, and the things worth checking about it are the
    status code and two headers: a spreadsheet cannot carry "this download is
    short" in a row without making its own totals wrong.
    """
    try:
        with urllib.request.urlopen(base + path, timeout=5) as r:
            return (r.status, r.read().decode('utf-8'),
                    {k.lower(): v for k, v in r.headers.items()})
    except urllib.error.HTTPError as e:
        return (e.code, e.read().decode('utf-8'),
                {k.lower(): v for k, v in e.headers.items()})


def post(base, path, body):
    req = urllib.request.Request(
        base + path, data=json.dumps(body).encode('utf-8'),
        headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode('utf-8') or '{}')


def delete(base, path):
    req = urllib.request.Request(base + path, method='DELETE')
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode('utf-8') or '{}')


def offer(i, at, **extra):
    row = {'v': 1, 'id': 'off%d' % i, 'seq': 1, 'at': at, 'firstAt': at,
           'pay': 10.0 + i, 'minutes': 20.0, 'miles': 4.0, 'perHour': 30.0,
           'grossPerHour': 36.0, 'cost': 1.2, 'billedMinutes': 20.0,
           'state': 'go', 'target': 25, 'band': 15, 'costPerMile': 0.3,
           'legs': 2, 'whole': True}
    row.update(extra)
    return row


def write(path, rows, mode='w'):
    with open(path, mode) as fh:
        for r in rows:
            fh.write(json.dumps(r) + '\n')


def lines(path):
    return [json.loads(l) for l in open(path) if l.strip()]


NOW = int(time.time() * 1000)
work = tempfile.mkdtemp()
journal = os.path.join(work, 'journal.jsonl')
write(journal, [offer(i, NOW - i * 60000) for i in range(3)])
proc, base = start({'SCANNER': '0'}, journal)
try:
    # --- two reads in flight after one append ------------------------------
    # The journal is parsed once and then only the part that grew, and the
    # rows are cached. Two callers that both look before either finishes both
    # start from the same cache — the driving screen's poll, the offers page
    # and the sync's /api/journal/newest all land just after the scanner
    # appends — and each pushed the new rows onto the cached array. Every new
    # row was then in the cache twice for the rest of the process: measured,
    # `have` 9 for a file of 5 lines. The number sync.py reconciles against.
    eq('the cache is warm', get(base, '/api/journal/newest').get('have'), 3)
    write(journal, [offer(3, NOW - 180000), offer(4, NOW - 240000)], mode='a')
    # Genuinely in flight together: three connections, three requests sent
    # back to back before any answer is read, so all three stat the file
    # before any of them has read it. Three threads each doing a whole
    # round trip did not reproduce this — a read takes under a millisecond
    # and the next request arrived after it.
    import http.client
    port = int(base.rsplit(':', 1)[1])
    conns = [http.client.HTTPConnection('127.0.0.1', port, timeout=5) for _ in range(3)]
    for c in conns:
        c.request('GET', '/api/journal/newest')
    answers = []
    for c in conns:
        answers.append(json.loads(c.getresponse().read().decode('utf-8')).get('have'))
        c.close()
    eq('three reads in flight after an append each count the file (%r)' % answers,
       answers, [5, 5, 5])
    eq('...and the read after them still does', get(base, '/api/journal/newest').get('have'), 5)
    eq('...as the offers page sees it', get(base, '/api/journal?days=0').get('count'), 5)

    # --- and the same three on a COLD journal -------------------------------
    #
    # The case above is the warm tail read: the cache is already built and only
    # the appended bytes are parsed. The expensive one is the cold read, which
    # is what happens when systemd restarts the server mid-shift — and every
    # reader used to do the whole job for itself: its own whole-file buffer,
    # its own whole-file string, its own split array, its own rows.
    #
    # Measured on a year-sized journal: one cold read peaks at 380 MB of
    # resident memory, three at once at 820 MB. On a Pi sharing its RAM with
    # OpenCV and Tesseract that is the difference between working and swapping.
    # They queue now — one reader does the work and the others get its answer.
    #
    # What is asserted here is the part that must not break: every caller is
    # still answered, and answered correctly. A queue that drops a waiter, or
    # hands one a half-built array, would be a far worse fault than the memory.
    stop(proc)
    proc, base = start({'SCANNER': '0'}, journal)
    conns = [http.client.HTTPConnection('127.0.0.1', int(base.rsplit(':', 1)[1]),
                                        timeout=10) for _ in range(3)]
    for c in conns:
        c.request('GET', '/api/journal?days=0')
    cold = []
    for c in conns:
        cold.append(json.loads(c.getresponse().read().decode('utf-8')).get('count'))
        c.close()
    eq('three readers arriving together on a cold journal are all answered '
       '(%r)' % cold, cold, [5, 5, 5])
    eq('...and the next one still is', get(base, '/api/journal?days=0').get('count'), 5)

    # --- the file rewritten under the cache ---------------------------------
    #
    # `cp backup journal` keeps the inode and can leave the file larger, which
    # looks exactly like an append until the remembered last line is checked and
    # is not there. The read then starts again from the beginning — and it has
    # to do that WITHOUT going back through the queue it is already holding, or
    # it would be parked behind itself and never answer. A hang here, not a
    # wrong number, is what that mistake looks like, which is why this asserts
    # against a timeout.
    # DIFFERENT rows, not the same ones with more added. A rewrite whose first
    # lines are byte-identical to what was there IS an append as far as this
    # check can tell, and rightly so — the remembered last line is still where
    # it was, so the tail read is correct and the retry never fires. Writing
    # the same offers back was the first version of this fixture and it proved
    # nothing: the retry path stayed unexecuted and a mutation that broke it
    # passed.
    write(journal, [offer(i + 100, NOW - i * 60000) for i in range(7)])
    eq('a journal rewritten in place is read again from the start',
       get(base, '/api/journal?days=0').get('count'), 7)
    eq('...and the cache is right afterwards',
       get(base, '/api/journal/newest').get('have'), 7)

    # --- a window may not change what an offer IS ---------------------------
    #
    # The fold is now given only the rows a window can reach, because folding a
    # year to answer "today" cost 182 ms on every page load during a shift —
    # the scanner appends every few seconds and the cache is keyed on the rows
    # array, so every new offer made the next load re-fold everything.
    #
    # The saving is only allowed if the ANSWER is identical, and this is where
    # that is proved rather than asserted. Every hazard the rule was written
    # around is in this journal at once: a card whose readings straddle the
    # floor, a rule older than the floor that hides a card inside it, a mark
    # older than the floor, a mark NEWER than the offer it names, a pairing
    # older than the floor, and a row from before the rig had a clock.
    stop(proc)
    hz = os.path.join(work, 'hazards.jsonl')
    DAY = 86400000
    old_at = NOW - 40 * DAY
    write(hz, [
        # An offer long outside any recent window. It must not appear in the
        # windowed answer, and its presence must not change the ones that do.
        offer(1, old_at, pay=9.0),
        # A rule written 40 days ago that hides a card scanned TODAY. Dropping
        # rule rows outside the window would un-hide it — and the driver would
        # see the test card they hid, in the figures, with nothing said.
        {'v': 1, 'kind': 'rule', 'at': old_at,
         'match': {'pay': 11.0, 'minutes': 20.0, 'miles': 4.0}, 'hidden': True},
        # A mark written 40 days ago about a card scanned today.
        {'v': 1, 'kind': 'mark', 'at': old_at, 'id': 'off3', 'accepted': True},
        # A card read twice, seconds apart, with the floor between the two — the
        # only shape this hazard really takes, because every reading of one card
        # happens within seconds of the others.
        #
        # The EARLIER reading saw the address and the later one lost it, which
        # is an ordinary outcome: the card scrolls, the crop moves, the second
        # read is better on the figures and blank on the places. bestReading
        # takes the later reading and BORROWS the address from the one it
        # outvoted. Drop the earlier reading because it falls outside the window
        # and the address is simply gone, from a card that is in the window.
        #
        # Two earlier fixtures proved nothing here. Readings that AGREE survive
        # any split, and readings eight days apart make the winner itself fall
        # outside the window, so the offer never appears either way.
        offer(2, NOW - 2 * DAY - 60000, pay=14.0,
              pickup='Chipotle (Barrett)', dropoff='Oak St',
              places=['Chipotle (Barrett)', 'Oak St']),
        offer(2, NOW - 2 * DAY + 60000, pay=14.0, seq=2),
        # ...and the one the rule above hides, scanned today.
        offer(3, NOW - 120000, pay=11.0),
        # A row from before the rig heard from NTP. In no window by
        # construction, and counted separately so it is never silently gone.
        offer(4, 1000, pay=7.0),
        # An ordinary card scanned today.
        offer(5, NOW - 300000, pay=13.0),
    ])
    proc, base = start({'SCANNER': '0'}, hz)
    since = NOW - 2 * DAY
    wide = get(base, '/api/journal?days=0&limit=0')
    narrow = get(base, '/api/journal?days=2&since=%d' % since)
    by_id = lambda body: dict((o['id'], o) for o in (body.get('offers') or []))
    W, N = by_id(wide), by_id(narrow)
    # The window holds what it should and nothing older.
    # off3 is inside the window and absent on purpose: the forty-day-old rule
    # hides it, and a hidden card is in neither the list nor the figures unless
    # asked for by name. Its absence IS the rule surviving the window.
    eq('a windowed read returns the offers inside the window (%r)'
       % sorted(N), sorted(N), ['off2', 'off5'])
    ok_('...and not the one forty days back', 'off1' not in N)
    # THE check. Every offer the window holds must be the SAME offer the
    # unwindowed read reports — same figures, same flags, same everything.
    for oid in sorted(N):
        eq('...and %s is identical to the unwindowed read of it' % oid,
           json.dumps(N[oid], sort_keys=True), json.dumps(W.get(oid), sort_keys=True))
    # Said again on the three hazards by name, so a failure says which rule broke.
    ok_('a rule older than the window still hides a card inside it',
        'off3' not in N and 'off3' not in W)
    eq('...and the window counts it hidden exactly as the whole file does',
       narrow.get('hidden'), wide.get('hidden'))
    ok_('...and that count is not zero, or the rule proved nothing',
        (narrow.get('hidden') or 0) >= 1)
    # The same card, asked for by name. A mark written forty days before the
    # window still has to reach it.
    shown = get(base, '/api/journal?days=2&since=%d&hidden=1' % since)
    marked = dict((o['id'], o) for o in (shown.get('offers') or []))
    ok_('a mark older than the window still reaches its offer',
        (marked.get('off3') or {}).get('accepted') is True)
    eq('a row from before the clock is still counted, not dropped in silence',
       narrow.get('beforeClock'), 1)
    eq('...the same count the unwindowed read gives', wide.get('beforeClock'), 1)
    # A card read either side of the floor keeps both readings, so the vote —
    # and therefore every figure on the card — is the window's business no more
    # than the weather is.
    eq('a card whose readings straddle the floor reads the same either way',
       json.dumps(N.get('off2'), sort_keys=True),
       json.dumps(W.get('off2'), sort_keys=True))
    # ...carrying the address only the reading OUTSIDE the window ever saw.
    # This is the whole of what the straddle check is for: without it the
    # equivalence above passes on a card that lost the same thing both ways.
    eq('...carrying the address the reading outside the window saw',
       (N.get('off2') or {}).get('pickup'), 'Chipotle (Barrett)')

    # The fold is cached per window now, and the windows have to stay apart.
    # Asked narrow FIRST and then wide, a cache that ignored the floor would
    # answer the wide question with the narrow fold — every offer older than
    # the window simply gone, from the range whose whole point is that nothing
    # is. The order is the test: above, wide was asked first and the fault
    # would have hidden behind the handler's own filter.
    stop(proc)
    proc, base = start({'SCANNER': '0'}, hz)
    get(base, '/api/journal?days=2&since=%d' % since)
    after = get(base, '/api/journal?days=0&limit=0')
    ok_('a narrow read first does not shrink the wide one after it (%r)'
        % sorted(dict((o['id'], 1) for o in (after.get('offers') or []))),
        'off1' in dict((o['id'], 1) for o in (after.get('offers') or [])))
    eq('...and it holds every offer the file does', after.get('count'),
       wide.get('count'))
    stop(proc)
    proc, base = start({'SCANNER': '0'}, journal)

    # --- a body split inside a character ------------------------------------
    # Stringifying each TCP segment on its own turns an 'é' whose two bytes
    # arrive in different segments into two replacement characters, and the
    # row is stored that way for good: its identity is its id, so the
    # browser's next re-send of the right bytes is refused as a duplicate.
    row = offer(7, NOW - 300000, places=['Café Résumé, 12 rue de l’Opéra'])
    body = (json.dumps(row, ensure_ascii=False) + '\n').encode('utf-8')
    cut = body.index('é'.encode('utf-8')) + 1          # between the two bytes of é
    head = ('POST /api/journal/ingest HTTP/1.1\r\nHost: x\r\n'
            'Content-Type: application/x-ndjson\r\n'
            'Content-Length: %d\r\nConnection: close\r\n\r\n' % len(body)).encode('ascii')
    sock = socket.create_connection(('127.0.0.1', int(base.rsplit(':', 1)[1])), timeout=5)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sock.sendall(head + body[:cut])
    time.sleep(0.15)
    sock.sendall(body[cut:])
    reply = b''
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        reply += chunk
    sock.close()
    ok_('the split body was taken (%r)' % reply.split(b'\r\n')[0], b'200' in reply.split(b'\r\n')[0])
    stored = [r for r in get(base, '/api/journal?days=0').get('offers', []) if r.get('id') == 'off7']
    eq('a place name split across two segments is stored whole',
       stored[0].get('places') if stored else None, ['Café Résumé, 12 rue de l’Opéra'])

    # --- two uploads in flight together -------------------------------------
    #
    # The handler is a read-modify-write: readJournal, build the `seen` set
    # from what came back, append what is not in it. readWaiters serialises the
    # READ only — and for two overlapping ingests it makes matters worse, since
    # they share one read and are guaranteed to see the same pre-append
    # journal. Each then finds every key in its batch absent and appends the
    # lot, both reply ok, and the append-only file holds every row twice.
    #
    # Measured before the lock on a 400-row journal and two simultaneous POSTs
    # of the same 60 rows: both answered `added: 60, have: 460`, the file held
    # 520 lines, 460 distinct keys, 60 stored twice.
    #
    # It is not a contrived collision. sync.py's own stderr tells the operator
    # to run it by hand with --all while the installed ten-minute timer keeps
    # ticking, and a retry after a dropped connection can overlap the request
    # it is retrying.
    stop(proc)
    write(journal, [offer(100 + i, NOW - 400000 + i) for i in range(20)])
    proc, base = start({'SCANNER': '0'}, journal)
    _batch = ('\n'.join(json.dumps(offer(200 + i, NOW - 200000 + i))
                        for i in range(30)) + '\n').encode('utf-8')

    def _push(out, at):
        req = urllib.request.Request(base + '/api/journal/ingest', data=_batch,
                                     headers={'Content-Type': 'application/x-ndjson'})
        try:
            out[at] = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
        except Exception as e:                     # noqa: BLE001 - reported below
            out[at] = {'error': repr(e)}

    _replies = {}
    _threads = [threading.Thread(target=_push, args=(_replies, _n)) for _n in (0, 1)]
    for _t in _threads:
        _t.start()
    for _t in _threads:
        _t.join()
    _lines = [l for l in open(journal, encoding='utf-8') if l.strip()]
    _keys = {}
    for _l in _lines:
        _r = json.loads(_l)
        _k = (_r.get('id'), _r.get('seq'))
        _keys[_k] = _keys.get(_k, 0) + 1
    eq('two uploads of one batch store each row once', len(_lines), 50)
    eq('...and nothing is in the append-only journal twice',
       sorted(k for k, n in _keys.items() if n > 1), [])
    # One of them has to say it added nothing, or the pair added 60 between
    # them and the count above is a coincidence of the de-duplication rather
    # than of the lock.
    eq('...and the second upload is told it added nothing',
       sorted(r.get('added') for r in _replies.values()), [0, 30])
    eq('...and both are told the same, correct, total',
       sorted(set(r.get('have') for r in _replies.values())), [50])

    # The lock must not be able to strand every later upload behind a request
    # that ended early. Each of these leaves the handler by a different door.
    for _body, _why in ((b'', 'an empty body'),
                        (b'not json at all\n', 'a malformed line'),
                        (_batch, 'a batch already stored')):
        _req = urllib.request.Request(base + '/api/journal/ingest', data=_body,
                                      headers={'Content-Type': 'application/x-ndjson'})
        urllib.request.urlopen(_req, timeout=10).read()
    _after = json.loads(urllib.request.urlopen(urllib.request.Request(
        base + '/api/journal/ingest',
        data=(json.dumps(offer(299, NOW - 100000)) + '\n').encode('utf-8'),
        headers={'Content-Type': 'application/x-ndjson'}), timeout=10).read().decode())
    eq('an upload still goes through after every early exit', _after.get('added'), 1)

    # --- rows from before the clock, counted once, the same way twice --------
    # A Pi boots in 1970 and jumps when NTP arrives. Rows read before that are
    # set aside by both pages, and both say how many. They said different
    # numbers over one hidden test card: the offers page counted hidden rows,
    # the driving screen did not. And on All the sightings tallied in that
    # stretch were still summed into "the rig watched N cards" while every
    # offer from it was set aside.
    write(journal, [offer(20, 1000), offer(21, 2000),
                    {'v': 1, 'kind': 'mark', 'id': 'off21', 'at': NOW - 1000, 'hidden': True},
                    {'v': 1, 'kind': 'seen', 'at': 3000, 'saw': 7, 'kept': 2}], mode='a')
    page = get(base, '/api/journal?days=0')
    screen = get(base, '/api/today?since=%d' % (NOW - 3600000))
    eq('the offers page counts the rows from before the clock', page.get('beforeClock'), 1)
    eq('...and the driving screen counts the same rows', screen.get('beforeClock'), page.get('beforeClock'))
    eq('a tally from before the clock is not what the rig watched',
       (page.get('watched') or {}).get('saw'), 0)

    # --- a screen row is evidence, not an offer ------------------------------
    #
    # `kind: "screen"` carries the raw reading of a payout-free screen that
    # followed a card, so that an accept-detector can one day be built on
    # something other than a screenshot. It is written by the rig, it has to
    # reach the copy at home, and it must be invisible to every figure on the
    # offers page — a row with no pay and no minutes counted as an offer would
    # move every median on that page toward zero.
    #
    # The two halves are separate code and are checked separately: the fold in
    # readJournal skips a `kind` it does not know, and syncKey identifies such a
    # row by its id and seq so ingest can carry it. Neither is written for this
    # kind in particular, which is exactly why a kind this build DOES know
    # should be pinned against them.
    _before = get(base, '/api/journal?days=0')
    _screen = {'v': 1, 'kind': 'screen', 'at': NOW - 2000,
               'id': 'screen-%d' % (NOW - 2000), 'seq': 1,
               'after': 'off20', 'afterMs': 4000,
               'text': '3.2 mi\nI-75 S toward 14th St\nDeliver to Daria I.'}
    write(journal, [_screen], mode='a')
    _after_page = get(base, '/api/journal?days=0')
    eq('a screen row is not counted as an offer',
       len(_after_page.get('offers') or []), len(_before.get('offers') or []))
    eq('...nor as a card the rig watched go past',
       (_after_page.get('watched') or {}).get('saw'),
       (_before.get('watched') or {}).get('saw'))
    # ...and it goes across the sync, which is the whole point of writing it
    # into the journal rather than a file beside it: the corpus is useless on a
    # machine in a car and the journal already syncs on its own.
    _sent = json.dumps(_screen).encode('utf-8') + b'\n'
    _ing = json.loads(urllib.request.urlopen(urllib.request.Request(
        base + '/api/journal/ingest', data=_sent,
        headers={'Content-Type': 'application/x-ndjson'}), timeout=10).read().decode())
    eq('a screen row already stored is recognised by the sync, not doubled',
       _ing.get('added'), 0)
    _fresh = dict(_screen, at=NOW - 1500, id='screen-%d' % (NOW - 1500))
    _ing2 = json.loads(urllib.request.urlopen(urllib.request.Request(
        base + '/api/journal/ingest',
        data=json.dumps(_fresh).encode('utf-8') + b'\n',
        headers={'Content-Type': 'application/x-ndjson'}), timeout=10).read().decode())
    eq('...and one the far end has not seen is stored', _ing2.get('added'), 1)

    # --- a sighting nobody asked for, against a card that named its own end ---
    #
    # The live path already refuses this: an unprompted address may fill a
    # blank and may not overwrite. The JOURNAL did not, and the two guards look
    # at different things — the live one tests the card in memory at that
    # moment, this one is the fold that merges every row for an offer,
    # newest-wins, where `bestReading` has been borrowing ends from whichever
    # reading had them. So a card whose later readings lost the address still
    # carries one here while `scanner.offer.dropoff` is empty, the live guard
    # lets the mark through, and the fold used to apply it unconditionally.
    #
    # A wrong destination, written into an append-only file, synced to the NUC.
    # Both rows are staged directly because that divergence is the whole point
    # and a live run cannot be made to produce it on demand.
    write(journal, [
        offer(40, NOW - 5000, dropoff='Oak Ln, Marietta'),
        {'v': 1, 'kind': 'mark', 'id': 'off40', 'at': NOW - 1000,
         'dropoff': '222 Wrong Way Dr, Kennesaw, GA 30144', 'asked': False},
        # ...and one that named nowhere, which is the case the sighting is FOR.
        offer(41, NOW - 5000),
        {'v': 1, 'kind': 'mark', 'id': 'off41', 'at': NOW - 1000,
         'dropoff': '111 Filled In Rd, Kennesaw, GA 30144', 'asked': False},
        # ...and a press, which still overrules the card. Absent `asked` means
        # asked, so rows written before that field existed keep their meaning —
        # written without it here deliberately, because that is what is already
        # in this driver's journal.
        offer(42, NOW - 5000, dropoff='Oak Ln, Marietta'),
        {'v': 1, 'kind': 'mark', 'id': 'off42', 'at': NOW - 1000,
         'dropoff': '333 Asked For Ave, Kennesaw, GA 30144'},
    ], mode='a')
    folded = {r.get('id'): r for r in get(base, '/api/journal?days=0').get('offers', [])}
    eq('an unasked sighting does not overwrite a card that named its own end',
       (folded.get('off40') or {}).get('dropoff'), 'Oak Ln, Marietta')
    no_('...and the row is not claimed as scanned either',
        (folded.get('off40') or {}).get('dropoffScanned'))
    eq('...while the same sighting fills a card that named nowhere',
       (folded.get('off41') or {}).get('dropoff'),
       '111 Filled In Rd, Kennesaw, GA 30144')
    ok_('...and that one IS marked as scanned',
        (folded.get('off41') or {}).get('dropoffScanned') is True)
    eq('...and a press still overrules the card, as it always did',
       (folded.get('off42') or {}).get('dropoff'),
       '333 Asked For Ave, Kennesaw, GA 30144')

    # ...and a sighting does not displace a press, however late it arrives.
    #
    # Newest-wins is right between two of a kind and wrong across them. A
    # navigation screen caught at 11:05 is not better evidence than the driver
    # deliberately answering at 11:00, and folding on `at` alone let the later
    # one erase the address AND the fact that a press had happened at all.
    #
    # The live path can no longer produce that pair — see the card-re-read
    # check below — but this fold also merges the copy synced from the NUC,
    # where rows arrive in whatever order the two journals reconcile in. So the
    # sighting is staged LATER than the press here deliberately: the ordering
    # that would win on `at`.
    write(journal, [
        offer(43, NOW - 5000),
        {'v': 1, 'kind': 'mark', 'id': 'off43', 'at': NOW - 4000,
         'dropoff': '444 Asked First Rd, Kennesaw, GA 30144', 'asked': True},
        {'v': 1, 'kind': 'mark', 'id': 'off43', 'at': NOW - 1000,
         'dropoff': '555 Seen Later Dr, Kennesaw, GA 30144', 'asked': False},
        # ...while two of a KIND still fold newest-first, or the rule would
        # have stopped being about presses and started being about order.
        offer(44, NOW - 5000),
        {'v': 1, 'kind': 'mark', 'id': 'off44', 'at': NOW - 4000,
         'dropoff': '666 Pressed Early Rd, Kennesaw, GA 30144', 'asked': True},
        {'v': 1, 'kind': 'mark', 'id': 'off44', 'at': NOW - 1000,
         'dropoff': '777 Pressed Again Dr, Kennesaw, GA 30144', 'asked': True},
    ], mode='a')
    folded = {r.get('id'): r for r in get(base, '/api/journal?days=0').get('offers', [])}
    eq('a later sighting does not displace an earlier press',
       (folded.get('off43') or {}).get('dropoff'),
       '444 Asked First Rd, Kennesaw, GA 30144')
    eq('...while a later press does displace an earlier one',
       (folded.get('off44') or {}).get('dropoff'),
       '777 Pressed Again Dr, Kennesaw, GA 30144')

    # --- a mark that carries its offer, after a restart -----------------------
    # The offer on record is process memory. The panel keeps "Took?" across a
    # server restart, the driver presses it, the mark is written — and no
    # order goes in the car. The panel says which offer it is marking, and
    # that stands in when nothing is on record.
    code, reply = post(base, '/api/offers/mark', {
        'id': 'off99', 'accepted': True,
        'offer': {'id': 'off99', 'pay': 12.45, 'minutes': 28.0, 'billedMinutes': 28.0,
                  'miles': 5.0, 'cost': 1.75, 'dropoff': 'Oak Ln, Marietta'}})
    eq('a mark with its offer is taken', code, 200)
    ok_('...and puts the order in the car', reply.get('holding') is True)
    held = get(base, '/api/status').get('holding')
    eq('...where the status says it ends', (held or {}).get('dropoff'), 'Oak Ln, Marietta')
    code, reply = post(base, '/api/offers/mark', {'id': 'off98', 'accepted': True,
                                                  'offer': {'id': 'off97', 'pay': 1.0, 'minutes': 5.0}})
    status = get(base, '/api/status')
    eq('...but only the offer it names: the order in the car is still the first',
       (status.get('holding') or {}).get('dropoff'), 'Oak Ln, Marietta')
    eq('...and so is the offer on record', (status.get('offer') or {}).get('id'), 'off99')
finally:
    stop(proc)
    shutil.rmtree(work, ignore_errors=True)

# --- where a mark was pressed, a pass, and an answer taken back -------------
#
# The end-of-shift review on the offers page asks Took or Passed about every
# card the panel cleared that day, and a pass is now a fact the advice reads:
# Advice.ifCleared stops counting a passed card as one that might have been
# taken. So three things have to hold at this door, and each is asked of the
# file and of the fold separately, because the fold is what every page reads
# and the file is what cannot be corrected.
#
#   * `via` says which of the three surfaces made the press, and only those
#     three. This endpoint has no field for free text; a `via` taken as given
#     would be one.
#   * `false` folds to `false`, and a card nobody marked to NO FIELD. Those are
#     different answers and the page counts them apart.
#   * `null` takes an answer back, newest-wins like the other two, and folds to
#     no field: a ✓ mis-tapped and undone must not become a pass nobody made.
#   * `false` with NO `via` is that same take-back. Every page before Passed
#     existed wrote it for the ✓ pressed again, and a page loaded before an
#     upgrade still does (live.html never reloads; sw.js serves the cached
#     copy first). Read as a pass, it took the card out of the review's list
#     and out of Advice.ifCleared's mix with nobody having passed on it.
work = tempfile.mkdtemp()
journal = os.path.join(work, 'journal.jsonl')
write(journal, [offer(i, NOW - (12 - i) * 60000) for i in range(1, 11)] + [
    # A pairing for off7, so the outcome the offers page's Second jobs section
    # reads off the same marks is asked too.
    {'v': 1, 'kind': 'pair', 'id': 'off7', 'at': NOW - 3 * 60000,
     'held': {'pay': 12.0, 'minutes': 30}, 'offer': {'pay': 17.0, 'minutes': 20},
     'stack': None},
    # ...and a tick taken back the way every journal before this branch holds
    # one: `true`, then `false` a minute later, neither naming a surface.
    {'v': 1, 'kind': 'mark', 'id': 'off10', 'at': NOW - 90000, 'accepted': True},
    {'v': 1, 'kind': 'mark', 'id': 'off10', 'at': NOW - 30000, 'accepted': False}])
proc, base = start({'SCANNER': '0'}, journal)


def _folded(i):
    return {o['id']: o for o in get(base, '/api/journal?days=0')
            .get('offers', [])}.get('off%d' % i, {})


try:
    _before = len(lines(journal))
    _said = {}
    for _i, _via in ((1, 'panel'), (2, 'offers'), (3, 'review')):
        _said[_via] = post(base, '/api/offers/mark',
                           {'id': 'off%d' % _i, 'accepted': True, 'via': _via})[0]
    eq('a mark says where it was pressed, for each of the three places one can '
       'be (%r)' % _said, _said, {'panel': 200, 'offers': 200, 'review': 200})
    eq('...and the journal row carries it, as sent',
       [(r.get('id'), r.get('via')) for r in lines(journal)[_before:]
        if r.get('kind') == 'mark'],
       [('off1', 'panel'), ('off2', 'offers'), ('off3', 'review')])
    # Anything else is refused, and refused BEFORE the append. Dropped quietly,
    # a page that misspelt its own name would go on writing marks with no
    # provenance and look as though it worked.
    _bad = [post(base, '/api/offers/mark',
                 {'id': 'off4', 'accepted': True, 'via': _v})[0]
            for _v in ('phone', 'Review', '', None, 7)]
    eq('a mark naming anywhere else is refused (%r)' % _bad, _bad, [400] * 5)
    eq('...and nothing of it is written', len(lines(journal)), _before + 3)
    no_('...so the offer it named is still unmarked', 'accepted' in _folded(4))
    # Absent is legal: every mark already in a journal was written without it.
    eq('a mark that names no surface is still taken',
       post(base, '/api/offers/mark', {'id': 'off4', 'accepted': True})[0], 200)
    no_('...and stored with no `via` rather than a guessed one',
        'via' in lines(journal)[-1])

    # A pass, then the driver changing their mind twice. Newest wins, and
    # `false` is an answer, not a blank.
    post(base, '/api/offers/mark', {'id': 'off5', 'accepted': False, 'via': 'review'})
    _o5 = _folded(5)
    ok_('a Passed press folds to accepted:false, not to unmarked (%r)'
        % _o5.get('accepted', 'absent'), 'accepted' in _o5 and _o5['accepted'] is False)
    post(base, '/api/offers/mark', {'id': 'off5', 'accepted': True, 'via': 'review'})
    eq('...a Took pressed after it wins', _folded(5).get('accepted'), True)
    post(base, '/api/offers/mark', {'id': 'off5', 'accepted': False, 'via': 'offers'})
    _o5 = _folded(5)
    ok_('...and a pass after that wins back, whichever surface made it (%r)'
        % _o5.get('accepted', 'absent'), 'accepted' in _o5 and _o5['accepted'] is False)
    no_('an offer nobody marked carries no accepted field at all',
        'accepted' in _folded(8))

    # Taking an answer back. A tick, then the same ✓ pressed again: the row
    # must come out as it went in — no field — and not as a pass.
    post(base, '/api/offers/mark', {'id': 'off6', 'accepted': True, 'via': 'offers'})
    _code = post(base, '/api/offers/mark',
                 {'id': 'off6', 'accepted': None, 'via': 'offers'})[0]
    eq('a withdrawal is taken', _code, 200)
    eq('...and written as one', lines(journal)[-1].get('accepted', 'absent'), None)
    _o6 = _folded(6)
    no_('...and a tick taken back folds to no field at all, not to a pass (%r)'
        % _o6.get('accepted', 'absent'), 'accepted' in _o6)
    # ...and from a pass, which is the other thing it can be taking back.
    post(base, '/api/offers/mark', {'id': 'off5', 'accepted': None, 'via': 'review'})
    no_('...and so does a pass taken back', 'accepted' in _folded(5))

    # The same take-back from a page older than Passed: `false`, no `via`.
    # Sent through the door, as a panel or offers page still running the old
    # code sends it after the server is upgraded...
    post(base, '/api/offers/mark', {'id': 'off9', 'accepted': True})
    post(base, '/api/offers/mark', {'id': 'off9', 'accepted': False})
    _o9 = _folded(9)
    no_('a ✓ taken back by a page older than Passed (false, no via) folds to no '
        'field, not to a pass (%r)' % _o9.get('accepted', 'absent'), 'accepted' in _o9)
    # ...and as it already sits in every journal written before this branch.
    _o10 = _folded(10)
    no_('...and one already in the journal file reads the same (%r)'
        % _o10.get('accepted', 'absent'), 'accepted' in _o10)
    # The withdrawal is the newest word on the pairing too, or Second jobs
    # counts it among the ones "marked either way".
    post(base, '/api/offers/mark', {'id': 'off7', 'accepted': False, 'via': 'review'})
    _p7 = [p for p in get(base, '/api/journal?days=0').get('pairs', [])
           if p.get('id') == 'off7']
    eq('a pass reaches the pairing it was about', [p.get('accepted') for p in _p7], [False])
    post(base, '/api/offers/mark', {'id': 'off7', 'accepted': None, 'via': 'review'})
    _p7 = [p for p in get(base, '/api/journal?days=0').get('pairs', [])
           if p.get('id') == 'off7']
    eq('...and taken back, leaves it unmarked', [('accepted' in p) for p in _p7], [False])

    # ...and on the order in the car, a withdrawal puts it down as a pass
    # does: the driver pressed Took again because they did not take it.
    _, _reply = post(base, '/api/offers/mark', {
        'id': 'off8', 'accepted': True, 'via': 'panel',
        'offer': {'id': 'off8', 'pay': 18.0, 'minutes': 20.0, 'billedMinutes': 20.0,
                  'miles': 4.0, 'cost': 1.2}})
    ok_('a Took press puts the order in the car', _reply.get('holding') is True)
    _, _reply = post(base, '/api/offers/mark',
                     {'id': 'off8', 'accepted': None, 'via': 'panel'})
    no_('...and pressing it again puts it down', _reply.get('holding'))
finally:
    stop(proc)
    shutil.rmtree(work, ignore_errors=True)

# --- the order in the car, on a scanner that reads cards again ---------------
#
# The scanner reads a card several times while it sits on the phone, and again
# after a restart. Each reading carried the offer, and each arrival wrote the
# pairing down: with a job in the car, one card produced a pair row per
# reading. And the stored reading was stacked in place, so /api/status served
# a pair line computed before the order was put down.
if shutil.which('python3'):
    work = tempfile.mkdtemp()
    journal = os.path.join(work, 'journal.jsonl')
    fake = os.path.join(work, 'rereads.py')
    with open(fake, 'w') as fh:
        fh.write(
            'import json, sys, time\n'
            'def say(i, minutes, pay, state="go"):\n'
            '    print(json.dumps({"ready": True, "state": "go", "perHour": 30.0,\n'
            '        "grossPerHour": 36.0, "pay": pay, "minutes": minutes, "miles": 5.0,\n'
            '        "cost": 1.75, "billedMinutes": minutes, "target": 25, "band": 15,\n'
            '        "costPerMile": 0.35, "at": int(time.time() * 1000),\n'
            '        "offer": {"id": i, "pay": pay, "minutes": minutes, "billedMinutes": minutes,\n'
            '                  "miles": 5.0, "cost": 1.75, "perHour": 30.0, "target": 25,\n'
            '                  "band": 15, "costPerMile": 0.35, "state": state}}),\n'
            '          flush=True)\n'
            'say("o-1", 0.01, 9.0)\n'
            'time.sleep(2.5)\n'
            'say("o-3", 30.0, 12.45)\n'
            'time.sleep(1.5)\n'
            'say("o-3", 30.0, 12.45)\n'
            'time.sleep(1.5)\n'
            'say("o-4", 20.0, 11.0, "no")\n'
            'time.sleep(600)\n')
    open(journal, 'w').close()
    proc, base = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable,
                        'SCANNER_ARGS': fake, 'HOLD_GRACE_MS': '0'}, journal)
    try:
        def offer_is(i, patience=6.0):
            for _ in range(int(patience * 20)):
                s = get(base, '/api/status')
                if (s.get('offer') or {}).get('id') == i:
                    return s
                time.sleep(0.05)
            return None

        # A card whose own window is 0.9s, marked 1.2s after it was read.
        # Dated from the press, the hold outlived the card; dated from the
        # card, holding() has already let it go.
        ok_('the first card is on record', offer_is('o-1') is not None)
        time.sleep(1.2)
        code, reply = post(base, '/api/offers/mark', {'id': 'o-1', 'accepted': True})
        eq('a late mark is still written', code, 200)
        ok_('...but an order older than its own window does not go in the car',
            reply.get('holding') is False)
        ok_('the next card is on record', offer_is('o-3') is not None)
        code, reply = post(base, '/api/offers/mark', {'id': 'o-3', 'accepted': True})
        ok_('a prompt mark puts the order in the car', reply.get('holding') is True)
        ok_('the card after it is on record', offer_is('o-4', 8.0) is not None)
        time.sleep(0.5)
        pairs = [r for r in lines(journal) if r.get('kind') == 'pair']
        eq('a card read again while it is the order in the car is not paired with itself',
           [r['id'] for r in pairs if r['id'] == 'o-3'], [])
        eq('...and the next card is paired with it once',
           [r['id'] for r in pairs if r['id'] == 'o-4'], ['o-4'])
        # The verdict the panel drew for that card, off its own offer line —
        # its reading beside it says "go" here, so a row that took it from
        # the reading would record the wrong one. The pair line's colour is no
        # longer drawn, so its `stack.state` is not what the driver was shown,
        # and the row says so in a field the rows before it do not have.
        _o4 = [r for r in pairs if r['id'] == 'o-4'][:1] or [{}]
        eq('...recording the verdict the panel showed for that card',
           _o4[0].get('said'), 'no')
        eq('...and that the pair line\'s own verdict was not on the panel',
           _o4[0].get('stackShown'), False)
        before = get(base, '/api/status')
        ok_('the status carries the pair line while the order is held',
            (before.get('last') or {}).get('stack') is not None)
        code, reply = post(base, '/api/delivered', {})
        ok_('putting it down says there was one', reply.get('wasHolding') is True)
        after = get(base, '/api/status')
        ok_('...and the status no longer carries the pair line',
            (after.get('last') or {}).get('stack') is None)
        ok_('...nor the order', after.get('holding') is None)
        ok_('...and still carries the reading', (after.get('last') or {}).get('ready') is True)
    finally:
        stop(proc)
        shutil.rmtree(work, ignore_errors=True)

# --- a mark from a panel that has fallen behind -------------------------------
#
# The socket drops, /api/events replays the last reading and never the offer,
# and the driver ticks the card they took while the server is already on the
# next one. The mark carries its offer, and that copy used to stand in for
# whatever was on record whenever the ids differed — so the older card took
# the slot, /api/status named it with the newer card on the phone, and the
# newer card's next re-read looked like a new card and wrote its pair row a
# second time. Measured against this server before the fix: pair rows
# ['o-a', 'o-b', 'o-b'].
if shutil.which('python3'):
    work = tempfile.mkdtemp()
    journal = os.path.join(work, 'journal.jsonl')
    fake = os.path.join(work, 'behind.py')
    with open(fake, 'w') as fh:
        fh.write(
            'import json, time\n'
            'def say(i, pay):\n'
            '    print(json.dumps({"ready": True, "state": "go", "perHour": 30.0,\n'
            '        "grossPerHour": 36.0, "pay": pay, "minutes": 30.0, "miles": 5.0,\n'
            '        "cost": 1.75, "billedMinutes": 30.0, "target": 25, "band": 15,\n'
            '        "costPerMile": 0.35, "at": int(time.time() * 1000),\n'
            '        "offer": {"id": i, "pay": pay, "minutes": 30.0, "billedMinutes": 30.0,\n'
            '                  "miles": 5.0, "cost": 1.75, "perHour": 30.0, "target": 25,\n'
            '                  "band": 15, "costPerMile": 0.35, "state": "go"}}),\n'
            '          flush=True)\n'
            'say("o-h", 10.0)\n'
            'time.sleep(2.0)\n'
            'say("o-a", 12.0)\n'
            'time.sleep(1.5)\n'
            'say("o-b", 14.0)\n'
            'time.sleep(3.0)\n'
            'say("o-b", 14.0)\n'
            'time.sleep(600)\n')
    open(journal, 'w').close()
    proc, base = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable,
                        'SCANNER_ARGS': fake, 'HOLD_GRACE_MS': '0'}, journal)
    try:
        def offer_is(i, patience=6.0):
            for _ in range(int(patience * 20)):
                s = get(base, '/api/status')
                if (s.get('offer') or {}).get('id') == i:
                    return s
                time.sleep(0.05)
            return None

        ok_('the first card is on record', offer_is('o-h') is not None)
        post(base, '/api/offers/mark', {'id': 'o-h', 'accepted': True})
        ok_('...and the newer card is on record behind it', offer_is('o-b') is not None)
        _a = {'id': 'o-a', 'pay': 12.0, 'minutes': 30.0, 'billedMinutes': 30.0,
              'miles': 5.0, 'cost': 1.75, 'state': 'go'}
        code, reply = post(base, '/api/offers/mark',
                           {'id': 'o-a', 'accepted': True, 'offer': _a})
        eq('a mark for the card before the one on record is taken', code, 200)
        _st = get(base, '/api/status')
        eq('...and the card on record is still the one on the phone',
           (_st.get('offer') or {}).get('id'), 'o-b')
        # By its pay: the status shows the order in the car without its id.
        eq('...while the card the driver took is the order in the car',
           (_st.get('holding') or {}).get('pay'), 12.0)
        time.sleep(3.5)
        eq('...and the newer card read again is still one pair row, not two',
           [r['id'] for r in lines(journal) if r.get('kind') == 'pair'],
           ['o-a', 'o-b'])
    finally:
        stop(proc)
        shutil.rmtree(work, ignore_errors=True)

# --- the held order's own card, back under a new id; a Took that replaces -----
#
# After ✓ Took the same card came back onto the phone and the scanner logged it
# under a new id, and the server judged it against the held order as a second
# job: a pair row and a stack line for one order measured against itself (one
# such row on the 12 Oct shift, stack `warn`). And a second ✓ Took while an
# order was held replaced it with no drop row. Made-up cards throughout.
_HELD_FAKE = (
    'import json, time\n'
    'def say(i, pay, pickup="Test Kitchen", dropoff="Elm St & Oak Ave, Testville",\n'
    '        miles=5.0, minutes=30.0):\n'
    '    print(json.dumps({"ready": True, "state": "go", "perHour": 30.0,\n'
    '        "grossPerHour": 36.0, "pay": pay, "minutes": minutes, "cardMinutes": minutes,\n'
    '        "miles": miles, "cost": 1.75, "billedMinutes": 34.0, "target": 25, "band": 15,\n'
    '        "costPerMile": 0.35, "pickup": pickup, "dropoff": dropoff,\n'
    '        "at": int(time.time() * 1000),\n'
    '        "offer": {"id": i, "pay": pay, "minutes": minutes, "billedMinutes": 34.0,\n'
    '                  "miles": miles, "cost": 1.75, "perHour": 30.0, "state": "go",\n'
    '                  "pickup": pickup, "dropoff": dropoff}}), flush=True)\n'
    'say("h-1", 10.00)\n'
    'time.sleep(2.5)\n'
    'say("h-2", 10.00, pickup="test kitchen,")\n'
    'time.sleep(1.5)\n'
    'say("h-2", 10.00, pickup="test kitchen,")\n'
    'time.sleep(1.5)\n'
    'say("n-1", 10.03)\n'
    'time.sleep(1.5)\n'
    'say("n-2", 10.00, dropoff="Pine Rd & Birch Ln, Testville")\n'
    'time.sleep(1.5)\n'
    'say("n-3", 10.00, miles=6.0)\n'
    'time.sleep(1.5)\n'
    'say("n-4", 10.00, minutes=31.0)\n'
    'time.sleep(1.5)\n'
    'say("h-3", 10.00, pickup=None, dropoff=None)\n'
    'time.sleep(600)\n')
if shutil.which('python3'):
    work = tempfile.mkdtemp()
    journal = os.path.join(work, 'journal.jsonl')
    fake = os.path.join(work, 'heldagain.py')
    with open(fake, 'w') as fh:
        fh.write(_HELD_FAKE)
    open(journal, 'w').close()
    proc, base = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable,
                        'SCANNER_ARGS': fake, 'HOLD_GRACE_MS': '600000'}, journal)
    try:
        def offer_is(i, patience=8.0):
            for _ in range(int(patience * 20)):
                s = get(base, '/api/status')
                if (s.get('offer') or {}).get('id') == i:
                    return s
                time.sleep(0.05)
            return None

        def drops():
            return [(r.get('id'), r.get('by')) for r in lines(journal) if r.get('kind') == 'drop']

        ok_('[held again] the card is on record', offer_is('h-1') is not None)
        code, reply = post(base, '/api/offers/mark', {'id': 'h-1', 'accepted': True})
        ok_('[held again] Took puts it in the car', reply.get('holding') is True)
        code, reply = post(base, '/api/offers/mark', {'id': 'h-1', 'accepted': True})
        eq('[held again] Took pressed again on the same card puts nothing down',
           (drops(), reply.get('replaced')), ([], None))
        _s = offer_is('h-2')
        ok_('[held again] its own card under a new id is on record', _s is not None)
        _s = _s or {}
        ok_('[held again] the offer on record is named as the order in the car',
            ((_s.get('offer') or {}).get('heldCard') or '').startswith('h-1@'))
        eq('[held again] ...and its reading carries no stack line',
           ((_s.get('last') or {}).get('stack'), bool((_s.get('last') or {}).get('heldCard'))),
           (None, True))
        ok_('[held again] the cards after it are on record', offer_is('h-3', 10.0) is not None)
        time.sleep(0.5)
        eq('[held again] no pairing row for the held card come back; '
           'a few-cents re-offer, a different dropoff, a different distance and a '
           'different card time are paired',
           [r['id'] for r in lines(journal) if r.get('kind') == 'pair'],
           ['n-1', 'n-2', 'n-3', 'n-4'])
        _s = get(base, '/api/status')
        ok_('[held again] a reading with no addresses matches on the figures',
            ((_s.get('offer') or {}).get('heldCard') or '').startswith('h-1@'))
        code, reply = post(base, '/api/offers/mark', {'id': 'h-3', 'accepted': True})
        eq('[held again] Took on the held card come back keeps the order and drops nothing',
           (drops(), ((get(base, '/api/status').get('holding') or {}).get('holdId') or '')[:4]),
           ([], 'h-1@'))
        _n2 = {'id': 'n-2', 'pay': 10.00, 'minutes': 30.0, 'billedMinutes': 34.0,
               'miles': 5.0, 'cost': 1.75, 'state': 'go'}
        _ev = listen(base, 3)
        time.sleep(0.3)
        code, reply = post(base, '/api/offers/mark',
                           {'id': 'n-2', 'accepted': True, 'offer': _n2})
        time.sleep(0.5)
        eq('[replaced] a Took while holding another writes its drop row by replaced',
           drops(), [('h-1', 'replaced')])
        ok_('[replaced] ...and the reply says the previous order was put down',
            (reply.get('replaced') or {}).get('saidForMs'))
        ok_('[replaced] ...and so does the stream, for every panel',
            any(m.get('heldReplaced') for m in _ev))
        ok_('[replaced] ...and the new card is the order in the car',
            ((get(base, '/api/status').get('holding') or {}).get('holdId') or '').startswith('n-2@'))
        _row = [r for r in lines(journal) if r.get('kind') == 'drop'][:1] or [{}]
        eq('[replaced] ...in the same shape as a pressed drop',
           sorted(_row[0].keys()),
           ['acceptedAt', 'at', 'by', 'end', 'id', 'kind', 'pickups', 'seq', 'v'])
    finally:
        stop(proc)
        shutil.rmtree(work, ignore_errors=True)

    # The window: the same card arriving after HELD_CARD_MS is a new offer.
    work = tempfile.mkdtemp()
    journal = os.path.join(work, 'journal.jsonl')
    fake = os.path.join(work, 'heldlate.py')
    with open(fake, 'w') as fh:
        fh.write(_HELD_FAKE)
    open(journal, 'w').close()
    proc, base = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable,
                        'SCANNER_ARGS': fake, 'HOLD_GRACE_MS': '600000',
                        'HELD_CARD_MS': '500'}, journal)
    try:
        for _ in range(160):
            if (get(base, '/api/status').get('offer') or {}).get('id') == 'h-1':
                break
            time.sleep(0.05)
        post(base, '/api/offers/mark', {'id': 'h-1', 'accepted': True})
        time.sleep(3.0)
        eq('[held again] past the window the same figures are a new offer, and paired',
           [r['id'] for r in lines(journal) if r.get('kind') == 'pair'][:1], ['h-2'])
    finally:
        stop(proc)
        shutil.rmtree(work, ignore_errors=True)

    # ...but a card recognised on its ARRIVAL stays the held card however long
    # it sits on the phone: its own card a second after the Took, then read
    # again three seconds later, past a two-second window. The reading is
    # still the order in the car, with no stack line.
    work = tempfile.mkdtemp()
    journal = os.path.join(work, 'journal.jsonl')
    fake = os.path.join(work, 'heldstays.py')
    with open(fake, 'w') as fh:
        fh.write(_HELD_FAKE.split('say("h-1", 10.00)\n')[0]
                 + 'say("h-1", 10.00)\n'
                 'time.sleep(1.0)\n'
                 'say("h-2", 10.00)\n'
                 'time.sleep(3.0)\n'
                 'say("h-2", 10.00)\n'
                 'time.sleep(600)\n')
    open(journal, 'w').close()
    proc, base = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable,
                        'SCANNER_ARGS': fake, 'HOLD_GRACE_MS': '600000',
                        'HELD_CARD_MS': '2000'}, journal)
    try:
        for _ in range(160):
            if (get(base, '/api/status').get('offer') or {}).get('id') == 'h-1':
                break
            time.sleep(0.05)
        post(base, '/api/offers/mark', {'id': 'h-1', 'accepted': True})
        time.sleep(5.0)
        _s = get(base, '/api/status')
        eq('[held again] a reading of the held card recognised on arrival, still on the '
           'phone past the window, is still the order in the car: no stack line',
           ((_s.get('last') or {}).get('stack'), bool((_s.get('last') or {}).get('heldCard')),
            [r['id'] for r in lines(journal) if r.get('kind') == 'pair']),
           (None, True, []))
    finally:
        stop(proc)
        shutil.rmtree(work, ignore_errors=True)

    # ...and back under its OWN id. The scanner now gives a card paged away
    # from and back to the id it had (rpi/journal.py, RECENT_CARDS), so the held
    # card arrives after another one as the held order's id, not as the same
    # slot. That is the order in the car by the journal's own word, past the
    # window or not; the offer line tested `!==` and paired it with itself.
    work = tempfile.mkdtemp()
    journal = os.path.join(work, 'journal.jsonl')
    fake = os.path.join(work, 'heldownid.py')
    with open(fake, 'w') as fh:
        fh.write(_HELD_FAKE.split('say("h-1", 10.00)\n')[0]
                 + 'say("h-1", 10.00)\n'
                 'time.sleep(2.5)\n'
                 'say("n-9", 12.00, dropoff="Pine Rd & Birch Ln, Testville")\n'
                 'time.sleep(1.5)\n'
                 'say("h-1", 10.00)\n'
                 'time.sleep(600)\n')
    open(journal, 'w').close()
    proc, base = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable,
                        'SCANNER_ARGS': fake, 'HOLD_GRACE_MS': '600000',
                        'HELD_CARD_MS': '500'}, journal)
    try:
        for _ in range(160):
            if (get(base, '/api/status').get('offer') or {}).get('id') == 'h-1':
                break
            time.sleep(0.05)
        post(base, '/api/offers/mark', {'id': 'h-1', 'accepted': True})
        # Until the card in between has been paired and the held one is back.
        for _ in range(160):
            if any(r.get('kind') == 'pair' for r in lines(journal)) \
                    and (get(base, '/api/status').get('offer') or {}).get('id') == 'h-1':
                break
            time.sleep(0.05)
        time.sleep(0.5)
        _s = get(base, '/api/status')
        ok_('[held again] its own card back under its own id after another card is '
            'the order in the car, past the window too',
            ((_s.get('offer') or {}).get('heldCard') or '').startswith('h-1@'))
        eq('[held again] ...and is not paired with itself',
           [r['id'] for r in lines(journal) if r.get('kind') == 'pair'], ['n-9'])
    finally:
        stop(proc)
        shutil.rmtree(work, ignore_errors=True)

# --- a card read twice, where only one reading saw the map --------------------
#
# The winner of the pay/minutes/miles vote is taken whole, and an address is not
# one of the fields the vote is about — so a reading that scored best and lost
# the map to glare took its empty `places` with it. That was already borrowed
# from an agreeing reading. `pickup` and `dropoff` were not, and they are the
# two fields everything downstream actually asks for: the offers page hides a
# row's map controls without them and map.html's whole working set is
# `o.pickup || o.dropoff`. So the row came back with an address printed on it
# and no way to put it on a map.
work = tempfile.mkdtemp()
journal = os.path.join(work, 'journal.jsonl')
write(journal, [
    # Two readings of one card. Identical figures, so they agree; one saw the
    # map and the other did not.
    offer(1, NOW - 2000, id='twice', places=[], pickup=None, dropoff=None),
    offer(1, NOW - 1000, id='twice', seq=2,
          places=['Chick-fil-A (Dallas Hwy)', 'Old Mountain Rd NW, Kennesaw'],
          pickup='Chick-fil-A (Dallas Hwy)',
          dropoff='Old Mountain Rd NW, Kennesaw'),
])
proc, base = start({'SCANNER': '0'}, journal)
try:
    got = [o for o in (get(base, '/api/journal?days=0').get('offers') or [])
           if o.get('id') == 'twice']
    eq('the two readings fold into one row', len(got), 1)
    row = got[0] if got else {}
    ok_('...carrying the address the other reading saw',
        (row.get('places') or []) and 'Chick-fil-A' in row['places'][0])
    # The half that was missing. Without these the page prints the address and
    # offers no map control for it, which reads as the page contradicting
    # itself about one row.
    eq('...and which end is the pickup',
       row.get('pickup'), 'Chick-fil-A (Dallas Hwy)')
    eq('...and which is the dropoff',
       row.get('dropoff'), 'Old Mountain Rd NW, Kennesaw')
finally:
    stop(proc)
    shutil.rmtree(work, ignore_errors=True)

# ...and the ends are taken from the SAME reading the places came from. Two
# readings of one card can disagree about where it goes, and a pickup off one
# with a dropoff off another is a journey neither of them read.
work = tempfile.mkdtemp()
journal = os.path.join(work, 'journal.jsonl')
write(journal, [
    offer(1, NOW - 3000, id='three', places=[], pickup=None, dropoff=None),
    # Disagrees about the figures, so it is not the preferred lender...
    offer(2, NOW - 2000, id='three', seq=2, pay=99.0,
          places=['Wrong Shop', 'Wrong St, Nowhere'],
          pickup='Wrong Shop', dropoff='Wrong St, Nowhere'),
    # ...and this one agrees, so it is.
    offer(1, NOW - 1000, id='three', seq=3,
          places=['Right Shop', 'Right St, Dallas'],
          pickup='Right Shop', dropoff='Right St, Dallas'),
])
proc, base = start({'SCANNER': '0'}, journal)
try:
    got = [o for o in (get(base, '/api/journal?days=0').get('offers') or [])
           if o.get('id') == 'three']
    row = got[0] if got else {}
    eq('the ends are borrowed from the reading that agrees about the card',
       (row.get('pickup'), row.get('dropoff')),
       ('Right Shop', 'Right St, Dallas'))
    ok_('...and the places with them, from the same one',
        (row.get('places') or [''])[0] == 'Right Shop')
finally:
    stop(proc)
    shutil.rmtree(work, ignore_errors=True)

# --- a CSV that cannot say it is short ----------------------------------------
#
# /api/journal and /api/journal.csv share one handler, and the CSV branch
# returned before the three signals the JSON branch carries: `unreadable`,
# `torn` and `truncated`. toCsv([]) is a header line and nothing else, so a
# journal that could not be OPENED downloaded as 200 OK, Content-Disposition,
# uber-scan-offers.csv, zero rows — the same file a quiet week produces, on the
# one artefact a driver keeps and a backup script collects.
#
# readJournal's own comment is about exactly this: "[] is not 'I do not know',
# it is 'there is nothing'". The JSON branch was made to honour that. This one
# was not.
work = tempfile.mkdtemp()
# A journal that exists, has a size, and cannot be read: a directory where the
# file should be. stat succeeds, open succeeds, read gives EISDIR — which is
# the shape of the real fault (a server that can append and not read) without
# needing a second user to reproduce it.
os.mkdir(os.path.join(work, 'journal.jsonl'))
proc, base = start({'SCANNER': '0'}, os.path.join(work, 'journal.jsonl'))
try:
    code, body, head = raw(base, '/api/journal.csv?days=7')
    eq('an unreadable journal refuses the CSV rather than downloading an empty one',
       code, 503)
    ok_('...saying why (%r)' % body[:60], 'could not be read' in body)
    # ...and the JSON branch still degrades rather than refusing, because a
    # driver looking at the offers page is better served by the page.
    page = get(base, '/api/journal?days=7')
    ok_('...while the page is still served, with the reason on it',
        (page.get('unreadable') or '') != '')
finally:
    stop(proc)
    shutil.rmtree(work, ignore_errors=True)

# ...and a CSV cut short by the cap says so in its headers rather than in a row.
# A spreadsheet with an extra row in it is a spreadsheet with a wrong total, so
# the disclosure cannot be in the body.
work = tempfile.mkdtemp()
journal = os.path.join(work, 'journal.jsonl')
write(journal, [offer(i, NOW - i * 1000) for i in range(6)])
proc, base = start({'SCANNER': '0'}, journal)
try:
    code, body, head = raw(base, '/api/journal.csv?days=0&limit=2')
    eq('a capped CSV is still served', code, 200)
    eq('...with the rows the cap left', len(body.strip().split('\n')), 3)
    eq('...and a header saying what it is short of',
       head.get('x-uber-scan-truncated'), '2 of 6')
    code, body, head = raw(base, '/api/journal.csv?days=0&limit=0')
    eq('...and limit=0 is genuinely uncapped',
       len(body.strip().split('\n')), 7)
    no_('...so it says nothing about being short',
        head.get('x-uber-scan-truncated'))
finally:
    stop(proc)
    shutil.rmtree(work, ignore_errors=True)

# --- an address read while SCREENING, with no order in the car ---------------
#
# The driver's own words: "for doordash orders I need to tap the customer drop
# off location to show the address when screening so it would be possible to
# search on the map". They reveal the address before deciding. Until now the
# rig threw that reading away: the ⌖ Dropoff button attached an address to the
# order in the car, and during screening there is no order in the car.
#
# What must not come back with it is the thing the old rule was protecting
# against — an address read with nothing on the screen, landing on whatever
# card happens to be in the slot. So the guard moved rather than lifted: it is
# the card being SCREENED, which is an id and a clock, not merely "not held".
if shutil.which('python3'):
    work = tempfile.mkdtemp()
    journal = os.path.join(work, 'journal.jsonl')
    fake = os.path.join(work, 'screening.py')
    with open(fake, 'w') as fh:
        fh.write(
            'import json, sys, time\n'
            'def card(i):\n'
            '    print(json.dumps({"ready": True, "state": "go", "perHour": 30.0,\n'
            '        "grossPerHour": 36.0, "pay": 12.0, "minutes": 24.0, "miles": 5.0,\n'
            '        "cost": 1.75, "billedMinutes": 24.0, "target": 25, "band": 15,\n'
            '        "costPerMile": 0.35, "dropoff": None, "endRefused": True,\n'
            '        "at": int(time.time() * 1000),\n'
            '        "offer": {"id": i, "pay": 12.0, "minutes": 24.0, "billedMinutes": 24.0,\n'
            '                  "miles": 5.0, "cost": 1.75, "perHour": 30.0, "target": 25,\n'
            '                  "band": 15, "costPerMile": 0.35, "dropoff": None,\n'
            '                  "endRefused": True, "state": "go"}}), flush=True)\n'
            'def addr(line):\n'
            '    print(json.dumps({"dropoff": {"line": line, "street": "3100 Esquire Dr NW",\n'
            '        "city": "Kennesaw", "state": "GA", "zip": "30144",\n'
            '        "at": int(time.time() * 1000)}}), flush=True)\n'
            'addr("nobody home, 0 Nowhere St, X, GA 30000")\n'
            'time.sleep(0.6)\n'
            'card("o-screen")\n'
            'time.sleep(0.6)\n'
            'addr("3100 Esquire Dr NW, Kennesaw, GA 30144")\n'
            'time.sleep(600)\n')
    # The row the rig itself would have written for this card. server.js does
    # not write offer rows — the scanner does, straight to the file — so a
    # fake scanner that only speaks on stdout leaves the journal with a note
    # about a card that is not in it, and the check below would be measuring
    # the fixture rather than the merge.
    write(journal, [dict(offer(1, NOW - 1000), id='o-screen', dropoff=None)])
    proc, base = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable,
                        'SCANNER_ARGS': fake}, journal)
    try:
        def wait_for(fn, patience=8.0):
            for _ in range(int(patience * 20)):
                s = get(base, '/api/status')
                if fn(s):
                    return s
                time.sleep(0.05)
            return None

        got = wait_for(lambda s: ((s.get('offer') or {}).get('dropoff')))
        ok_('an address read while screening reaches the card on the panel',
            got is not None)
        eq('...as the address itself',
           (got.get('offer') or {}).get('dropoff'),
           '3100 Esquire Dr NW, Kennesaw, GA 30144')
        # Said to be a SCAN rather than something the card printed. The two are
        # different degrees of evidence and the row has to be able to say which
        # it is holding: a cross street off a card is what the reader made of a
        # line of OCR, this is what the phone said when it was asked.
        ok_('...and marked as scanned rather than read off the card',
            (got.get('offer') or {}).get('dropoffScanned') is True)
        # ...and nothing went in the car. Reading an address is not accepting a
        # job, and a hold started here would measure every later offer against
        # a job the driver never took.
        ok_('...without putting an order in the car', got.get('holding') is None)
        # ...and the card's own verdict comes back with it. A panel opened or
        # reloaded mid-card seeds ⌖ Dropoff's ask from this echo, and the ask
        # is gated on the card not being a PASS; without the state here a
        # reloaded panel would go back to asking on every PASS card.
        eq('...and the offer echoed on /api/status keeps the card\'s own '
           'verdict', (got.get('offer') or {}).get('state'), 'go')

        # On the record, not only in memory. The panel is process memory and a
        # restart loses it; the whole point of reading the address before
        # deciding is to still have it afterwards, on the offers page and on
        # the map.
        # Polled, not read once. `/api/status` answers as soon as the address
        # is in memory, and the append that puts it on disk is a separate
        # asynchronous write — so reading the file on the next line is a race
        # that passes on an idle box and fails on a loaded one.
        marks = []
        for _ in range(100):
            rows = [json.loads(l) for l in open(journal) if l.strip()]
            marks = [r for r in rows if r.get('kind') == 'mark' and r.get('dropoff')]
            if marks:
                break
            time.sleep(0.05)
        eq('the address is appended as a note naming the offer', len(marks), 1)
        eq('...naming it', marks[0].get('id'), 'o-screen')
        eq('...and carrying the address', marks[0].get('dropoff'),
           '3100 Esquire Dr NW, Kennesaw, GA 30144')
        # The first address arrived before any card did. The old rule refused
        # it for being unheld; the new one refuses it for having nothing to
        # belong to, which is the reason that was always doing the work.
        no_('an address read with no card on the panel is not written down',
            any('Nowhere' in (r.get('dropoff') or '') for r in rows))
        # ...and it comes back off the file the same way, which is the half a
        # driver actually sees.
        page = get(base, '/api/journal?days=7')
        mine = [o for o in (page.get('offers') or []) if o.get('id') == 'o-screen']
        eq('the offers page shows the row it landed on', len(mine), 1)
        eq('...with the address on it', mine[0].get('dropoff'),
           '3100 Esquire Dr NW, Kennesaw, GA 30144')
        ok_('...still saying it was scanned', mine[0].get('dropoffScanned') is True)
    finally:
        stop(proc)
        shutil.rmtree(work, ignore_errors=True)

# --- an address nobody asked for fills a blank and overwrites nothing ---------
#
# The scanner now reports an address off any screen that has one and no payout,
# not only inside the window a button press opens: the driver taps the dropoff
# pin on their phone, which is a screen change the motion gate already reads.
#
# The two are not the same claim. A press is the driver saying "this screen is
# the destination", and it overrules what the card said. An unprompted sighting
# is the rig filling in a blank — because a navigation screen left up between
# offers would otherwise quietly rewrite the destination of a card that named
# its own, which is a confidently wrong answer arrived at without anybody asking
# a question.
if shutil.which('python3'):
    work = tempfile.mkdtemp()
    journal = os.path.join(work, 'journal.jsonl')
    fake = os.path.join(work, 'unasked.py')
    with open(fake, 'w') as fh:
        fh.write(
            'import json, sys, time\n'
            'def card(i, dropoff):\n'
            '    print(json.dumps({"ready": True, "state": "go", "perHour": 30.0,\n'
            '        "grossPerHour": 36.0, "pay": 12.0, "minutes": 24.0, "miles": 5.0,\n'
            '        "cost": 1.75, "billedMinutes": 24.0, "target": 25, "band": 15,\n'
            '        "costPerMile": 0.35, "at": int(time.time() * 1000),\n'
            '        "offer": {"id": i, "pay": 12.0, "minutes": 24.0,\n'
            '                  "billedMinutes": 24.0, "miles": 5.0, "cost": 1.75,\n'
            '                  "perHour": 30.0, "target": 25, "band": 15,\n'
            '                  "costPerMile": 0.35, "dropoff": dropoff}}), flush=True)\n'
            'def addr(line, asked):\n'
            '    print(json.dumps({"dropoff": {"line": line, "street": "1 X St",\n'
            '        "city": "Kennesaw", "state": "GA", "zip": "30144",\n'
            '        "asked": asked, "at": int(time.time() * 1000)}}), flush=True)\n'
            # Before any card at all, so there is nothing to attach it to and
            # nothing is stored — the one case where the driver DID ask and the
            # answer is kept nowhere. Showing it anyway is deliberate: they
            # pressed the button, and what the rig read is what they need.
            #
            # The pause is not padding. Everything below is checked against
            # what left over the stream, and the fixture starts talking the
            # moment the scanner is spawned — without it the first line can be
            # gone before the listener has connected, and the check would pass
            # or fail on how busy the box was.
            'time.sleep(1.0)\n'
            'addr("444 No Card Yet Rd, Kennesaw, GA 30144", True)\n'
            'time.sleep(0.7)\n'
            '# A card that named nowhere: an unasked sighting fills it.\n'
            'card("o-blank", None)\n'
            'time.sleep(0.7)\n'
            'addr("111 Filled In Rd, Kennesaw, GA 30144", False)\n'
            'time.sleep(0.7)\n'
            '# A card that named its own end: an unasked sighting must not move it.\n'
            'card("o-named", "Oak Ln, Marietta")\n'
            'time.sleep(0.7)\n'
            'addr("222 Wrong Way Dr, Kennesaw, GA 30144", False)\n'
            'time.sleep(0.7)\n'
            '# ...and the driver ASKING does move it.\n'
            'addr("333 Asked For Ave, Kennesaw, GA 30144", True)\n'
            'time.sleep(600)\n')
    open(journal, 'w').close()
    proc, base = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable,
                        'SCANNER_ARGS': fake}, journal)
    try:
        # Started before the fixture's first card, because the stream carries
        # what happens next. See listen().
        told = listen(base, 8.0)

        def wait_offer(i, patience=8.0):
            for _ in range(int(patience * 20)):
                s = get(base, '/api/status')
                if (s.get('offer') or {}).get('id') == i:
                    return s
                time.sleep(0.05)
            return {}

        wait_offer('o-blank')
        time.sleep(1.0)
        blank = (get(base, '/api/status').get('offer') or {})
        eq('an address nobody asked for fills a card that named nowhere',
           blank.get('dropoff'), '111 Filled In Rd, Kennesaw, GA 30144')
        ok_('...and is still marked as read off the screen',
            blank.get('dropoffScanned') is True)

        wait_offer('o-named')
        time.sleep(1.0)
        named = (get(base, '/api/status').get('offer') or {})
        eq('...but does not overwrite a card that named its own end',
           named.get('dropoff'), 'Oak Ln, Marietta')
        # ...and nothing was written about it either, because nothing changed.
        rows = [json.loads(l) for l in open(journal) if l.strip()]
        no_('...nor writes one down',
            any('Wrong Way' in (r.get('dropoff') or '') for r in rows))

        # The mark that WAS written says which kind it is.
        #
        # Checked where it is written rather than only where it is read. The
        # fold refuses an unasked address over a card that named its own end,
        # and the checks for that stage their rows directly — so they prove the
        # fold and say nothing about whether this path ever sets the field. Cut
        # it to a constant here and every one of them still passes, which is a
        # guard resting on a value nothing produces.
        #
        # It matters because the live guard tests the card in MEMORY and the
        # fold tests the row on disk, and the two can disagree: a card whose
        # later readings lost its address is blank here and still has one
        # there. That is the case this bit is carried for.
        filled = [r for r in rows if 'Filled In' in (r.get('dropoff') or '')]
        eq('the sighting that filled a blank was written down', len(filled), 1)
        if filled:
            eq('...and says nobody asked for it', filled[0].get('asked'), False)

        # The press still overrules, which is the whole difference.
        for _ in range(120):
            now = (get(base, '/api/status').get('offer') or {})
            if (now.get('dropoff') or '').startswith('333'):
                break
            time.sleep(0.05)
        eq('an address the driver asked for overrules the card',
           (get(base, '/api/status').get('offer') or {}).get('dropoff'),
           '333 Asked For Ave, Kennesaw, GA 30144')

        # --- and what the PANEL was told, which is a different question ------
        #
        # Refusing to store it is only half the job. live.html sets the ⌖
        # button's caption and its green "done" state straight off
        # `msg.dropoff.line`, and the broadcast used to sit outside all three
        # branches above — so the sighting this server had just declined went
        # out to the panel anyway. The comment beside the refusal said
        # "nothing to say either, because the driver did not ask a question to
        # be answered", and then it said it.
        #
        # What the driver got: holding an order whose destination came off the
        # card, a navigation screen for somewhere else catches one read, and
        # the button turns green reading "Dropoff read as 222 Wrong Way Dr" —
        # not the held job's destination, not on the record, and /api/status
        # cannot take it back, because the poll only rewrites the caption when
        # the held order is `dropoffScanned` or when there is no held order,
        # and this is neither.
        time.sleep(0.6)
        lines = [(m.get('dropoff') or {}).get('line') for m in told
                 if isinstance(m, dict) and m.get('dropoff')]
        # The premise: this stream was alive and did carry the ones that count.
        ok_('the panel was told about the sighting that filled a blank',
            any((l or '').startswith('111') for l in lines))
        ok_('...and about the one the driver asked for',
            any((l or '').startswith('333') for l in lines))
        # ...and NOT about the one that changed nothing.
        no_('an unasked sighting the server refused is not announced to the '
            'panel either (%r)' % (lines,),
            any((l or '').startswith('222') for l in lines))
        # ...while a PRESS with nothing to attach it to is still shown, which
        # is the other direction and the one that keeps this a bound rather
        # than a mute button. The driver asked; what the rig read is what they
        # need, whether or not there was a card to hang it on. Silencing both
        # passes every check above — the asked address up there happens to be
        # one the server kept — so without this the fix could be "say nothing
        # unless it was stored" and nothing would notice.
        ok_('a press with nothing to attach it to is still shown to the driver '
            '(%r)' % (lines,),
            any((l or '').startswith('444') for l in lines))
        # ...and it really was kept nowhere, or the line above is checking the
        # easy case rather than the one it names.
        no_('...though nothing was written down for it',
            any('No Card Yet' in (r.get('dropoff') or '')
                for r in [json.loads(l) for l in open(journal) if l.strip()]))
    finally:
        stop(proc)
        shutil.rmtree(work, ignore_errors=True)

# --- the card is read again, and the press survives it -----------------------
#
# `scanner.offer = read.offer` replaces the slot wholesale, and it used to
# carry only `accepted` across. So the destination a driver had just pressed
# for was thrown away by the NEXT reading of the card it belonged to — which
# arrives within seconds, because every card here is read repeatedly as the
# reading improves and a fuller one is re-announced.
#
# Losing it would be bad enough. What made it a WRONG address is the guard
# beside it: `wasAsked || !scanner.offer.dropoff` re-opens the moment the field
# is wiped, so the next unprompted sighting — a navigation screen left up, the
# previous job's, another app — was accepted over the press and appended as a
# second mark. Reproduced before the fix: pressed for "123 Oak St", the card
# read again, and both the panel and the journal ended up saying "999 Wrong Way
# Dr", with the press still on disk underneath and never shown again.
if shutil.which('python3'):
    work = tempfile.mkdtemp()
    journal = os.path.join(work, 'journal.jsonl')
    fake = os.path.join(work, 'reread.py')
    with open(fake, 'w') as fh:
        fh.write(
            'import json, time\n'
            'def card(i, miles):\n'
            '    print(json.dumps({"ready": True, "state": "go", "perHour": 30.0,\n'
            '        "grossPerHour": 36.0, "pay": 12.0, "minutes": 24.0,\n'
            '        "miles": miles, "cost": 1.75, "billedMinutes": 24.0,\n'
            '        "target": 25, "band": 15, "costPerMile": 0.35,\n'
            '        "at": int(time.time() * 1000),\n'
            '        "offer": {"id": i, "pay": 12.0, "minutes": 24.0,\n'
            '                  "billedMinutes": 24.0, "miles": miles,\n'
            '                  "cost": 1.75, "perHour": 30.0, "target": 25,\n'
            '                  "band": 15, "costPerMile": 0.35,\n'
            '                  "dropoff": None}}), flush=True)\n'
            'def addr(line, asked):\n'
            '    print(json.dumps({"dropoff": {"line": line, "street": "1 X St",\n'
            '        "city": "Kennesaw", "state": "GA", "zip": "30144",\n'
            '        "asked": asked, "at": int(time.time() * 1000)}}), flush=True)\n'
            '# A card that names nowhere, which is 129 of this driver\'s 272.\n'
            'card("o-reread", 5.0)\n'
            'time.sleep(0.7)\n'
            'addr("123 Oak St, Kennesaw, GA 30144", True)\n'
            'time.sleep(0.7)\n'
            '# The SAME card, read fuller — a corrected mileage.\n'
            'card("o-reread", 8.4)\n'
            'time.sleep(0.7)\n'
            'addr("999 Wrong Way Dr, Dallas, GA 30132", False)\n'
            'time.sleep(600)\n')
    open(journal, 'w').close()
    proc, base = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable,
                        'SCANNER_ARGS': fake}, journal)
    try:
        def slot(patience=8.0):
            for _ in range(int(patience * 20)):
                s = (get(base, '/api/status').get('offer') or {})
                if s.get('id') == 'o-reread':
                    return s
                time.sleep(0.05)
            return {}

        slot()
        # Wait past the re-reading AND the sighting that follows it, so what is
        # asserted is the end state rather than a moment before the damage.
        time.sleep(2.6)
        now = (get(base, '/api/status').get('offer') or {})
        # The premise: the card really was read a second time, or this passes
        # by never reaching the case it is named after.
        eq('the card really was read again', now.get('miles'), 8.4)
        eq('...and the address the driver pressed for survived it',
           now.get('dropoff'), '123 Oak St, Kennesaw, GA 30144')
        ok_('...still marked as read off the screen',
            now.get('dropoffScanned') is True)
        rows = [json.loads(l) for l in open(journal) if l.strip()]
        no_('...and no sighting was written over it',
            any('Wrong Way' in (r.get('dropoff') or '') for r in rows))
        page = get(base, '/api/journal?days=0')
        mine = [o for o in (page.get('offers') or []) if o.get('id') == 'o-reread']
        if mine:
            eq('...so the offers page shows what was pressed for',
               mine[0].get('dropoff'), '123 Oak St, Kennesaw, GA 30144')
    finally:
        stop(proc)
        shutil.rmtree(work, ignore_errors=True)

# --- the press this button exists for, with an order in the car --------------
#
# An offer card does not say where a delivery ends: Uber prints "Customer
# dropoff" and the address appears only on the screen after the accept. So
# capturing it once the order is IN THE CAR is the whole reason ⌖ Dropoff
# exists — and that path updated process memory and nothing else.
#
# It reached disk only if another card happened to arrive before the order
# ended, because the pairing row carries the held job's dropoff. Finish a
# delivery with no offer in between, or end the shift, or restart the server,
# and the address the driver deliberately captured was gone: off the offers
# page, off the map, out of the stack line's reasoning, with nothing saying it
# had ever been there.
if shutil.which('python3'):
    work = tempfile.mkdtemp()
    journal = os.path.join(work, 'journal.jsonl')
    fake = os.path.join(work, 'held.py')
    with open(fake, 'w') as fh:
        fh.write(
            'import json, sys, time\n'
            '# Long enough for the mark below to put the order in the car\n'
            '# first — the press being tested is one made while HOLDING.\n'
            'time.sleep(2.0)\n'
            'print(json.dumps({"dropoff": {"line": "77 Held Job Way, Kennesaw, GA 30144",\n'
            '    "street": "77 Held Job Way", "city": "Kennesaw", "state": "GA",\n'
            '    "zip": "30144", "asked": True,\n'
            '    "at": int(time.time() * 1000)}}), flush=True)\n'
            'time.sleep(600)\n')
    open(journal, 'w').close()
    proc, base = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable,
                        'SCANNER_ARGS': fake}, journal)
    try:
        code, reply = post(base, '/api/offers/mark', {
            'id': 'o-held', 'accepted': True,
            'offer': {'id': 'o-held', 'pay': 14.0, 'minutes': 30.0,
                      'billedMinutes': 30.0, 'miles': 6.0, 'cost': 2.1,
                      'dropoff': None}})
        eq('the order goes in the car', code, 200)
        ok_('...and the server says it is holding', reply.get('holding') is True)
        # ...and says it as the stream does (heldForPanel), so Map view has
        # the held order from the press and not from the next reading — and
        # the panel's in-car line its GPS drop's state (heldEndState).
        eq('held end: the mark reply carries the order in the car as the stream describes it',
           sorted((reply.get('held') or {}).keys()),
           # (`endArea`: the general area a refusal kept, the owner's 24 Oct.)
           ['arrived', 'card', 'dropoff', 'drops', 'endArea', 'endAt', 'endBy', 'endPinned',
            'endWhy', 'holdId', 'minutes', 'pay', 'pickAt', 'place', 'visited'])
        eq('held end: ...its `drops` null for an order of one door (a batch\'s count, '
           'server.js batchDrops)', (reply.get('held') or {}).get('drops', 'missing'), None)
        # Started after the mark, before the scanner's 2s sleep ends.
        heard = listen(base, 4)

        # The address, once the scanner reports it. Polled rather than slept
        # on: the append is asynchronous and reading the file on the next line
        # is a race that passes on an idle box and fails on a loaded one.
        marks = []
        for _ in range(200):
            rows = [json.loads(l) for l in open(journal) if l.strip()]
            marks = [r for r in rows
                     if r.get('kind') == 'mark' and r.get('dropoff')]
            if marks:
                break
            time.sleep(0.05)
        eq('a press while holding is written down', len(marks), 1)
        if marks:
            eq('...naming the order in the car', marks[0].get('id'), 'o-held')
            eq('...and carrying the address',
               marks[0].get('dropoff'), '77 Held Job Way, Kennesaw, GA 30144')
            eq('...and saying the driver asked for it', marks[0].get('asked'), True)
        # The premise, so this cannot pass by the order having quietly expired
        # and the address landing on some other path.
        held = get(base, '/api/status').get('holding') or {}
        eq('...while the order really was still in the car',
           held.get('dropoff'), '77 Held Job Way, Kennesaw, GA 30144')
        # The stream: the ⌖ read filed onto the hold goes out carrying that
        # hold, with no `ready`, which is how Map view pins it between
        # readings. Without it the panel learned the end only from the next
        # reading, and the card on the map stood in for it until then.
        for _ in range(60):
            if [m for m in heard if m.get('dropoff')]:
                break
            time.sleep(0.05)
        _said = [m for m in heard if m.get('dropoff')]
        eq('held end: the ⌖ read filed onto the order in the car goes out carrying it',
           [((m.get('holding') or {}).get('dropoff'), 'ready' in m) for m in _said],
           [('77 Held Job Way, Kennesaw, GA 30144', False)])
        ok_('...and marked as read off the screen',
            held.get('dropoffScanned') is True)
        # ...and it survives a restart, which is the whole point of writing it.
        page = get(base, '/api/journal?days=0')
        mine = [o for o in (page.get('offers') or []) if o.get('id') == 'o-held']
        if mine:
            eq('...so the offers page has it off the file',
               mine[0].get('dropoff'), '77 Held Job Way, Kennesaw, GA 30144')
    finally:
        stop(proc)
        shutil.rmtree(work, ignore_errors=True)

# --- an address under a Dropoff label, filed onto the hold with no press -------
#
# The driver's ask: while ✓ Took is in force, set the held order's destination
# whenever the screen shows an address directly under a "Dropoff" label, with
# no ⌖. The scanner says so on the line (`labelled: 'dropoff'`, see digest() in
# rpi/scan_pi.py); this is the server's half. A label-proven sighting fills a
# blank and replaces an end the CARD gave (a corner, a town), and never one
# that came off the screen — a press above all. Refused when it is older than
# the Took, or is one of the hold's own planner pickups. One server, one fake
# scanner that prints whatever line the test appends to its command file, so
# each hold is driven in turn. Every address below is invented.
if shutil.which('python3'):
    work = tempfile.mkdtemp()
    journal = os.path.join(work, 'journal.jsonl')
    cmds = os.path.join(work, 'cmds.jsonl')
    open(cmds, 'w').close()
    fake = os.path.join(work, 'relay.py')
    with open(fake, 'w') as fh:
        fh.write(
            'import sys, time\n'
            'done = 0\n'
            'while True:\n'
            '    lines = open(%r).read().splitlines()\n'
            '    for l in lines[done:]:\n'
            '        print(l, flush=True)\n'
            '    done = len(lines)\n'
            '    time.sleep(0.05)\n' % cmds)
    # The rows the rig would have written for the card-cornered order, so the
    # offers page can show what the fold makes of the mark.
    write(journal, [dict(offer(1, NOW - 1000), id='o-lab-corner',
                         dropoff='Oak Dr & Elm Dr, Acworth')])
    proc, base = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable,
                        'SCANNER_ARGS': fake}, journal)

    def took(i, dropoff, **card):
        code, reply = post(base, '/api/offers/mark', {
            'id': i, 'accepted': True,
            'offer': dict({'id': i, 'pay': 14.0, 'minutes': 30.0, 'billedMinutes': 30.0,
                           'miles': 6.0, 'cost': 2.1, 'dropoff': dropoff}, **card)})
        return code == 200 and reply.get('holding') is True

    def put_down(i):
        post(base, '/api/offers/mark', {'id': i, 'accepted': None})

    def say(msg):
        with open(cmds, 'a') as fh:
            fh.write(json.dumps(msg) + '\n')

    def seen(line, street, asked=False, labelled='dropoff', at=None, screen=None):
        say({'dropoff': {'found': True, 'line': line, 'street': street,
                         'city': 'Acworth', 'state': 'GA', 'zip': '30101',
                         'asked': asked, 'labelled': labelled, 'ms': None,
                         'screen': screen,
                         'at': at if at is not None else int(time.time() * 1000)}})

    def held_end(want=None, patience=4.0):
        """The hold's dropoff once it reads `want`, or after `patience` the
        one it has — a refusal can only be shown by waiting it out."""
        h = {}
        for _ in range(int(patience * 20)):
            h = get(base, '/api/status').get('holding') or {}
            if want is not None and h.get('dropoff') == want:
                return h.get('dropoff')
            time.sleep(0.05)
        return h.get('dropoff')

    def marks_for(i):
        return [r for r in (json.loads(l) for l in open(journal) if l.strip())
                if r.get('kind') == 'mark' and r.get('id') == i and r.get('dropoff')]

    try:
        heard = listen(base, 30)
        # A hold with no end: filed.
        ok_('the premise: the first order is in the car with no end',
            took('o-lab-blank', None))
        seen('12 Made Up Way, Acworth, GA 30101', '12 Made Up Way')
        eq('auto-dropoff: an address under a Dropoff label is filed onto a hold with '
           'no dropoff', held_end('12 Made Up Way, Acworth, GA 30101'),
           '12 Made Up Way, Acworth, GA 30101')
        for _ in range(60):
            if marks_for('o-lab-blank'):
                break
            time.sleep(0.05)
        eq('...written down as a held-dropoff mark, unasked and label-proven',
           [(m.get('asked'), m.get('labelled')) for m in marks_for('o-lab-blank')],
           [(False, True)])
        _said = [m for m in heard if (m.get('dropoff') or {}).get('labelled')]
        eq('...and goes to the panel as a ⌖ read does, carrying the order in the car',
           [((m.get('holding') or {}).get('dropoff'), m['dropoff'].get('line'))
            for m in _said][:1],
           [('12 Made Up Way, Acworth, GA 30101', '12 Made Up Way, Acworth, GA 30101')])
        put_down('o-lab-blank')

        # A hold whose end the card gave as a corner.
        ok_('the premise: an order is in the car with the card\'s corner as its end',
            took('o-lab-corner', 'Oak Dr & Elm Dr, Acworth'))
        seen('99 Unlabelled Rd, Acworth, GA 30101', '99 Unlabelled Rd', labelled=None)
        eq('auto-dropoff: an address under no label is not filed over the card\'s end',
           held_end('99 Unlabelled Rd, Acworth, GA 30101', 1.5),
           'Oak Dr & Elm Dr, Acworth')
        seen('34 Made Up Rd, Acworth, GA 30101', '34 Made Up Rd')
        eq('auto-dropoff: an address under a Dropoff label is filed over a card corner',
           held_end('34 Made Up Rd, Acworth, GA 30101'), '34 Made Up Rd, Acworth, GA 30101')
        seen('56 Second Label Ln, Acworth, GA 30101', '56 Second Label Ln')
        eq('auto-dropoff: ...and a second label-proven one does not overwrite it',
           held_end('56 Second Label Ln, Acworth, GA 30101', 1.5),
           '34 Made Up Rd, Acworth, GA 30101')
        page = get(base, '/api/journal?days=7')
        eq('auto-dropoff: the offers page has the labelled end over the card\'s own',
           [o.get('dropoff') for o in (page.get('offers') or [])
            if o.get('id') == 'o-lab-corner'], ['34 Made Up Rd, Acworth, GA 30101'])
        put_down('o-lab-corner')

        # A hold the driver pressed ⌖ for — over its own navigation, because
        # the first order's card is still on the slot here (each Took above
        # came with the panel's copy of its card), and with another card being
        # screened a press is the order's only on a cue the screen gives
        # (Assemble.pressBetween).
        ok_('the premise: a third order is in the car',
            took('o-lab-press', 'Oak Dr & Elm Dr, Acworth'))
        seen('77 Pressed Pl, Acworth, GA 30101', '77 Pressed Pl', asked=True, labelled=None,
             screen='uber.nav')
        ok_('the premise: the press is filed',
            held_end('77 Pressed Pl, Acworth, GA 30101') == '77 Pressed Pl, Acworth, GA 30101')
        seen('88 Late Label Ln, Acworth, GA 30101', '88 Late Label Ln')
        eq('auto-dropoff: an address under a Dropoff label is not filed over a ⌖ press',
           held_end('88 Late Label Ln, Acworth, GA 30101', 1.5),
           '77 Pressed Pl, Acworth, GA 30101')
        put_down('o-lab-press')

        # A hold whose planner lists a pickup at the address read.
        ok_('the premise: a fourth order is in the car with no end',
            took('o-lab-pickup', None))
        say({'planner': {'stops': [
            {'kind': 'pickup', 'orders': 1, 'name': 'Fable Grill', 'expectedBy': 978,
             'street': '4100 Fable Mill Pkwy NW', 'city': 'Kennesaw', 'state': 'GA',
             'zip': None, 'line': '4100 Fable Mill Pkwy NW, Kennesaw'},
            {'kind': 'dropoff', 'orders': 1, 'name': 'Pat Q.', 'expectedBy': 1001,
             'street': None, 'city': None, 'state': None, 'zip': None, 'line': None}],
            'unfiled': 'address', 'keep': False, 'asked': False, 'ms': None,
            'at': int(time.time() * 1000)}})
        for _ in range(60):
            if (get(base, '/api/status').get('holding') or {}).get('planner'):
                break
            time.sleep(0.05)
        seen('4100 Fable Mill Pkwy NW, Kennesaw, GA 30144', '4100 Fable Mill Pkwy NW')
        eq('auto-dropoff: an address that is one of the hold\'s planner pickups is not '
           'filed', held_end('4100 Fable Mill Pkwy NW, Kennesaw, GA 30144', 1.5), None)
        put_down('o-lab-pickup')

        # A read older than the Took.
        ok_('the premise: a fifth order is in the car with the card\'s corner',
            took('o-lab-stale', 'Oak Dr & Elm Dr, Acworth'))
        seen('21 Old Screen Ct, Acworth, GA 30101', '21 Old Screen Ct',
             at=int(time.time() * 1000) - 60000)
        eq('auto-dropoff: a labelled read from before the Took is not filed over the '
           'card\'s end', held_end('21 Old Screen Ct, Acworth, GA 30101', 1.5),
           'Oak Dr & Elm Dr, Acworth')
        put_down('o-lab-stale')

        # A Trip Planner's lone dropoff off a list whose end was below the
        # screen ("Waybill" under the bar): the scanner marks it
        # `singleCardOnly`, and it is filed only onto a held card that was one
        # order on one leg. The owner's decision, after a hotel dropoff on a
        # two-stop trip was left unfiled as 'list'.
        def lone(line, street):
            say({'dropoff': {'found': True, 'line': line, 'street': street,
                             'city': 'Kennesaw', 'state': 'GA', 'zip': None,
                             'asked': False, 'labelled': 'dropoff',
                             'singleCardOnly': True, 'ms': None,
                             'at': int(time.time() * 1000)}})
        ok_('the premise: a single-trip order is in the car with the card\'s corner',
            took('o-lone-one', 'Oak Dr & Elm Dr, Acworth', legs=1, multiOrder=False))
        # The planner it comes off, as the scanner sends it first: its one
        # dropoff left unfiled as 'list', the end of the list off the screen.
        say({'planner': {'stops': [
            {'kind': 'dropoff', 'orders': 1, 'name': 'Dana R.', 'expectedBy': 1325,
             'street': '1180 Wrenfield Rd NW', 'city': 'Kennesaw', 'state': 'GA',
             'zip': None, 'line': '1180 Wrenfield Rd NW, Kennesaw'}],
            'unfiled': 'list', 'keep': False, 'asked': False, 'ms': None,
            'at': int(time.time() * 1000)}})
        for _ in range(60):
            if (get(base, '/api/status').get('holding') or {}).get('planner'):
                break
            time.sleep(0.05)
        lone('1180 Wrenfield Rd NW, Kennesaw', '1180 Wrenfield Rd NW')
        eq('auto-dropoff: an unbounded planner\'s lone dropoff is filed onto a '
           'single-trip held card', held_end('1180 Wrenfield Rd NW, Kennesaw'),
           '1180 Wrenfield Rd NW, Kennesaw')
        eq('auto-dropoff: ...and the planner it came off stops saying its dropoff was '
           'not filed', (((get(base, '/api/status').get('holding') or {}).get('planner')
                          or {}).get('unfiled', 'absent')), None)
        put_down('o-lone-one')
        ok_('the premise: a two-leg card is in the car with the card\'s corner',
            took('o-lone-legs', 'Oak Dr & Elm Dr, Acworth', legs=2, multiOrder=False))
        lone('1180 Wrenfield Rd NW, Kennesaw', '1180 Wrenfield Rd NW')
        eq('auto-dropoff: an unbounded planner\'s lone dropoff is not filed onto a held '
           'card of two legs', held_end('1180 Wrenfield Rd NW, Kennesaw', 1.5),
           'Oak Dr & Elm Dr, Acworth')
        put_down('o-lone-legs')
        ok_('the premise: a two-order card is in the car with the card\'s corner',
            took('o-lone-two', 'Oak Dr & Elm Dr, Acworth', legs=1, multiOrder=True))
        lone('1180 Wrenfield Rd NW, Kennesaw', '1180 Wrenfield Rd NW')
        eq('auto-dropoff: an unbounded planner\'s lone dropoff is not filed onto a '
           'multi-order held card', held_end('1180 Wrenfield Rd NW, Kennesaw', 1.5),
           'Oak Dr & Elm Dr, Acworth')
        put_down('o-lone-two')
    finally:
        stop(proc)
        shutil.rmtree(work, ignore_errors=True)


# --- Stage 3: the assembler, with one hold ------------------------------------
#
# The decisions moved into assemble.js; the server keeps the writing and the
# saying. With ONE order held every decision must be the one the old dropoff
# branch made, and the one gain is a Trip Planner filed from more than one
# page. Through the real server and a relay scanner, as above. Every name and
# street invented.
if shutil.which('python3'):
    work = tempfile.mkdtemp()
    journal = os.path.join(work, 'journal.jsonl')
    cmds = os.path.join(work, 'cmds.jsonl')
    open(cmds, 'w').close()
    fake = os.path.join(work, 'relay.py')
    with open(fake, 'w') as fh:
        fh.write(
            'import sys, time\n'
            'done = 0\n'
            'while True:\n'
            '    lines = open(%r).read().splitlines()\n'
            '    for l in lines[done:]:\n'
            '        print(l, flush=True)\n'
            '    done = len(lines)\n'
            '    time.sleep(0.05)\n' % cmds)
    write(journal, [])
    proc, base = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable,
                        'SCANNER_ARGS': fake}, journal)

    def say(msg):
        with open(cmds, 'a') as fh:
            fh.write(json.dumps(msg) + '\n')

    def took(i, dropoff, **card):
        code, reply = post(base, '/api/offers/mark', {
            'id': i, 'accepted': True,
            'offer': dict({'id': i, 'pay': 14.0, 'minutes': 30.0, 'billedMinutes': 30.0,
                           'miles': 6.0, 'cost': 2.1, 'dropoff': dropoff}, **card)})
        return code == 200 and reply.get('holding') is True

    def put_down(i):
        post(base, '/api/offers/mark', {'id': i, 'accepted': None})

    def held(want=None, key='dropoff', patience=4.0):
        h = {}
        for _ in range(int(patience * 20)):
            h = get(base, '/api/status').get('holding') or {}
            if want is not None and h.get(key) == want:
                return h
            time.sleep(0.05)
        return h

    def marks_for(i):
        return [(r.get('dropoff'), r.get('asked'), r.get('labelled'))
                for r in (json.loads(l) for l in open(journal) if l.strip())
                if r.get('kind') == 'mark' and r.get('id') == i and r.get('dropoff')]

    _OSTRANDER = {'kind': 'dropoff', 'orders': 1, 'name': 'Mara T.', 'place': None,
                  'expectedBy': 1202, 'street': '415 Ostrander Way NW', 'city': 'Kennesaw',
                  'state': 'GA', 'zip': None, 'line': '415 Ostrander Way NW, Kennesaw',
                  'partial': None, 'label': 'dropoff'}
    _QUARRY = {'kind': 'pickup', 'orders': 1, 'name': 'Juniper Taqueria', 'place': None,
               'expectedBy': 1180, 'street': '2210 Quarry Bend Rd NW', 'city': 'Kennesaw',
               'state': 'GA', 'zip': '30144',
               'line': '2210 Quarry Bend Rd NW, Kennesaw, GA 30144',
               'partial': None, 'label': 'pickup'}

    def page(stops, top, bottom, titled, at=None):
        """A whole-screen planner read, unpressed: its sighting, then its
        planner line under the same stamp, the order the scanner sends them."""
        at = at if at is not None else int(time.time() * 1000)
        say({'sighting': {'at': at, 'asked': False, 'whole': True, 'titled': titled,
                          'app': 'uber', 'screen': 'uber.planner',
                          'page': {'top': top, 'bottom': bottom}, 'stops': stops,
                          'orderCount': 1, 'keep': False}})
        say({'planner': {'stops': [{k: v for k, v in s.items()
                                    if k not in ('partial', 'label')} for s in stops],
                         'keep': False, 'asked': False, 'ms': None, 'at': at}})
        return at

    try:
        heard = listen(base, 40)
        # The old road: the scanner decided the planner's one dropoff and sent
        # it as a label-proven dropoff line.
        ok_('the premise: an order with the card\'s corner is in the car (old road)',
            took('o-asm-old', 'Larch Way & Teal Ct, Kennesaw', legs=1, multiOrder=True))
        say({'dropoff': {'found': True, 'line': '415 Ostrander Way NW, Kennesaw',
                         'street': '415 Ostrander Way NW', 'city': 'Kennesaw',
                         'state': 'GA', 'zip': None, 'asked': False,
                         'labelled': 'dropoff', 'ms': None,
                         'at': int(time.time() * 1000)}})
        _old = held('415 Ostrander Way NW, Kennesaw')
        for _ in range(60):
            if marks_for('o-asm-old'):
                break
            time.sleep(0.05)
        _old_marks = [m[1:] for m in marks_for('o-asm-old')]
        put_down('o-asm-old')
        # The new road: the planner's sighting, and the assembler decides.
        ok_('the premise: the same order is in the car (new road)',
            took('o-asm-new', 'Larch Way & Teal Ct, Kennesaw', legs=1, multiOrder=True))
        page([_QUARRY, _OSTRANDER], True, True, True)
        _new = held('415 Ostrander Way NW, Kennesaw')
        for _ in range(60):
            if marks_for('o-asm-new'):
                break
            time.sleep(0.05)
        eq('one hold: the assembler files what the old branch filed',
           [(h.get('dropoff'), h.get('dropoffScanned')) for h in (_new,)]
           + [m[1:] for m in marks_for('o-asm-new')],
           [(_old.get('dropoff'), _old.get('dropoffScanned'))] + _old_marks)
        ok_('the premise: the old road filed it, label-proven and unasked (%r)' % _old_marks,
            _old.get('dropoff') == '415 Ostrander Way NW, Kennesaw'
            and _old_marks == [(False, True)])
        eq('...and the hold says where it came from',
           ((_new.get('fields') or {}).get('dropoff') or {}).get('from'), 'planner')
        eq('...and the planner line that followed says none was left unfiled',
           (held(key='planner', patience=0.5).get('planner') or {}).get('unfiled', '<none>'),
           None)
        _told = [m for m in heard if (m.get('dropoff') or {}).get('line')
                 == '415 Ostrander Way NW, Kennesaw' and m.get('holding')]
        ok_('...and the panel is told it as a dropoff, carrying the order in the car',
            any((m.get('holding') or {}).get('dropoff') == '415 Ostrander Way NW, Kennesaw'
                for m in _told))
        put_down('o-asm-new')

        # A rival card on the slot: a different offer read after the Took, still
        # what the driver is looking at. A label-proven address is filed onto the
        # one hold all the same — the refused guard (AUDITS) is not written.
        ok_('the premise: an order with the card\'s corner is in the car',
            took('o-asm-rival', 'Larch Way & Teal Ct, Kennesaw'))
        say({'offer': {'id': 'o-rival-card', 'pay': 9.5, 'minutes': 20, 'perHour': 18,
                       'dropoff': None}})
        for _ in range(60):
            if (get(base, '/api/status').get('offer') or {}).get('id') == 'o-rival-card':
                break
            time.sleep(0.05)
        ok_('the premise: the rival card is on the slot',
            (get(base, '/api/status').get('offer') or {}).get('id') == 'o-rival-card')
        say({'dropoff': {'found': True, 'line': '61 Saddlebrook Ln, Acworth, GA 30101',
                         'street': '61 Saddlebrook Ln', 'city': 'Acworth', 'state': 'GA',
                         'zip': '30101', 'asked': False, 'labelled': 'dropoff', 'ms': None,
                         'at': int(time.time() * 1000)}})
        eq('a labelled dropoff with a rival card on the slot is still filed onto the one hold',
           (held('61 Saddlebrook Ln, Acworth, GA 30101').get('dropoff'),
            (get(base, '/api/status').get('offer') or {}).get('dropoff')),
           ('61 Saddlebrook Ln, Acworth, GA 30101', None))
        put_down('o-asm-rival')

        # The gain: a list whose "Waybill" is on the page below, on a card of
        # two orders, so the first page alone files nothing.
        ok_('the premise: a two-order card is in the car with the card\'s corner',
            took('o-asm-pages', 'Larch Way & Teal Ct, Kennesaw', legs=1, multiOrder=True))
        _p1 = page([_QUARRY, _OSTRANDER], True, False, True)
        _h1 = held(patience=1.0)
        eq('a planner page whose list runs off the screen files nothing alone, and says why',
           (_h1.get('dropoff'), (_h1.get('planner') or {}).get('unfiled')),
           ('Larch Way & Teal Ct, Kennesaw', 'list'))
        page([_OSTRANDER], False, True, False, at=_p1 + 6000)
        _h2 = held('415 Ostrander Way NW, Kennesaw')
        eq('...and the page below it, with "Waybill", files the list\'s one dropoff',
           (_h2.get('dropoff'), ((_h2.get('fields') or {}).get('dropoff') or {}).get('from'),
            ((_h2.get('fields') or {}).get('customer') or {}).get('value')),
           ('415 Ostrander Way NW, Kennesaw', 'planner', 'Mara T.'))
        put_down('o-asm-pages')
    finally:
        stop(proc)
        shutil.rmtree(work, ignore_errors=True)

# --- a sighting is counted and goes nowhere ----------------------------------
#
# Stage 2 of the multi-order design: the scanner sends a `sighting` line for
# every whole-screen and planner read (emit_sighting in rpi/scan_pi.py). The
# server counts it by screen type on /api/status's scanner block, writes no
# journal row for it and puts nothing of it on the event stream. Since Stage 3
# a planner sighting is the assembler's to file from — see the next block —
# and these are pages it files nothing off: the one planner page here carries
# no `titled`, and an unpressed page is filed only under the "Trip Planner"
# title, as the scanner's own unpressed read always required; and the
# navigation screen's address is under no label, and a navigation screen
# files only one under a "Deliver to" or "Dropoff" label (the navigation
# block further down). One fake
# scanner relaying whatever the test appends, as above; the order is held so a
# sighting that filed would have somewhere to file. The address is invented.
if shutil.which('python3'):
    work = tempfile.mkdtemp()
    journal = os.path.join(work, 'journal.jsonl')
    cmds = os.path.join(work, 'cmds.jsonl')
    open(cmds, 'w').close()
    fake = os.path.join(work, 'relay.py')
    with open(fake, 'w') as fh:
        fh.write(
            'import sys, time\n'
            'done = 0\n'
            'while True:\n'
            '    lines = open(%r).read().splitlines()\n'
            '    for l in lines[done:]:\n'
            '        print(l, flush=True)\n'
            '    done = len(lines)\n'
            '    time.sleep(0.05)\n' % cmds)
    write(journal, [])
    proc, base = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable,
                        'SCANNER_ARGS': fake}, journal)
    try:
        code, reply = post(base, '/api/offers/mark', {
            'id': 'o-sight', 'accepted': True,
            'offer': {'id': 'o-sight', 'pay': 14.0, 'minutes': 30.0,
                      'billedMinutes': 30.0, 'miles': 6.0, 'cost': 2.1, 'dropoff': None}})
        ok_('the premise: an order with no end is held when the sightings arrive',
            code == 200 and reply.get('holding') is True)
        _stream = listen(base, 3.0)
        time.sleep(0.3)
        # Read here, not with lines(): that name is a list by this point.
        _rows_before = open(journal).read()
        _stop = {'kind': 'dropoff', 'orders': 1, 'name': 'Pat Q.', 'place': None,
                 'expectedBy': 978, 'street': '4821 Kestrel Dr', 'city': 'Marietta',
                 'state': 'GA', 'zip': None, 'line': '4821 Kestrel Dr, Marietta',
                 'partial': None, 'label': 'dropoff'}
        _bare = dict(_stop, kind=None, orders=None, name=None, expectedBy=None, label=None)
        with open(cmds, 'a') as fh:
            for _screen, _stops in (('uber.planner', [_stop]), ('uber.nav', [_bare]),
                                    ('uber.planner', [_stop]), (None, [])):
                fh.write(json.dumps({'sighting': {
                    'at': int(time.time() * 1000), 'asked': False, 'whole': True,
                    'app': 'uber', 'screen': _screen,
                    'page': {'top': True, 'bottom': True}, 'stops': _stops,
                    'orderCount': 1, 'keep': True}}) + '\n')
            # ...and a heartbeat after them, so the stream is shown carrying
            # the scanner's lines and the sightings are seen to be the ones
            # left out, not the stream to be silent.
            fh.write(json.dumps({'alive': True}) + '\n')
        _screens = {}
        for _ in range(80):
            _screens = (get(base, '/api/status').get('scanner') or {}).get('screens') or {}
            if sum(_screens.values()) >= 4:
                break
            time.sleep(0.05)
        eq('a sighting is counted by its screen type on the scanner\'s status, '
           'one without a type as unknown', _screens,
           {'uber.planner': 2, 'uber.nav': 1, 'unknown': 1})
        time.sleep(3.0)
        ok_('the premise: the stream carried the scanner\'s heartbeat after them',
            any(m.get('alive') for m in _stream))
        eq('...and is not broadcast', [m for m in _stream if 'sighting' in m], [])
        eq('...and writes no journal row', open(journal).read(), _rows_before)
        eq('...and files nothing onto the order in the car',
           ((get(base, '/api/status').get('holding') or {}).get('dropoff'),
            (get(base, '/api/status').get('holding') or {}).get('planner')), (None, None))
    finally:
        stop(proc)
        shutil.rmtree(work, ignore_errors=True)

# --- a ⌖ press that read Uber's Trip Planner ---------------------------------
#
# The scanner sends the planner's stops on a line of their own (emit_planner).
# Here they go to the panel on the stream, onto the order in the car for a
# panel reloaded mid-delivery, and into the journal as a collection row the
# copy at home can carry — once for one planner, however many presses read it.
#
# Two stops, both dropoffs: the planner a destination is NOT taken from, so
# the order in the car must come out of this with the end it went in with.
# The scanner sends no dropoff line for it, and nothing here may make one up
# out of the stops. Names, streets and houses invented.
if shutil.which('python3'):
    work = tempfile.mkdtemp()
    journal = os.path.join(work, 'journal.jsonl')
    fake = os.path.join(work, 'planner.py')
    _STOPS_A = [{'kind': 'dropoff', 'orders': 1, 'name': 'Pat Q.', 'expectedBy': 978,
                 'street': '4821 Kestrel Dr', 'city': 'Marietta', 'state': 'GA',
                 'zip': None, 'line': '4821 Kestrel Dr, Marietta'},
                {'kind': 'dropoff', 'orders': 1, 'name': 'Lee M.', 'expectedBy': 1001,
                 'street': None, 'city': None, 'state': None, 'zip': None,
                 'line': None}]
    # ...and the same trip with the first stop done.
    _STOPS_B = _STOPS_A[1:]
    # ...and a planner the scanner says the journal may not keep: "keepPlaces"
    # off, or no journal. Shown, held, and not written.
    _STOPS_C = [dict(_STOPS_A[0], name='Sam R.')]
    with open(fake, 'w') as fh:
        fh.write(
            'import json, sys, time\n'
            'A = %s\nB = %s\nC = %s\n'
            'def planner(stops, keep=True):\n'
            '    print(json.dumps({"planner": {"stops": stops, "unfiled": "dropoffs",\n'
            '        "keep": keep, "asked": True,\n'
            '        "ms": None, "at": int(time.time() * 1000)}}), flush=True)\n'
            '# Long enough for the mark below to put the order in the car.\n'
            'time.sleep(2.0)\n'
            'planner(A)\n'
            '# The driver checking the answer: the same screen, pressed again.\n'
            'time.sleep(0.4)\n'
            'planner(A)\n'
            'time.sleep(0.4)\n'
            'planner(B)\n'
            '# ...and B again once PLANNER_SAME_MS (1.5s here) has passed.\n'
            'time.sleep(2.0)\n'
            'planner(B)\n'
            'time.sleep(0.4)\n'
            'planner(C, keep=False)\n'
            'time.sleep(600)\n' % (json.dumps(_STOPS_A).replace('null', 'None'),
                                   json.dumps(_STOPS_B).replace('null', 'None'),
                                   json.dumps(_STOPS_C).replace('null', 'None')))
    open(journal, 'w').close()
    proc, base = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable,
                        'SCANNER_ARGS': fake, 'PLANNER_SAME_MS': '1500'}, journal)
    try:
        told = listen(base, 8.0)
        code, reply = post(base, '/api/offers/mark', {
            'id': 'o-planned', 'accepted': True,
            'offer': {'id': 'o-planned', 'pay': 14.0, 'minutes': 30.0,
                      'billedMinutes': 30.0, 'miles': 6.0, 'cost': 2.1,
                      'dropoff': None}})
        ok_('the premise: an order is in the car before the planner is read',
            code == 200 and reply.get('holding') is True)
        planned = []
        for _ in range(160):
            rows = [json.loads(l) for l in open(journal) if l.strip()]
            planned = [r for r in rows if r.get('kind') == 'planner']
            if len(planned) >= 3:
                break
            time.sleep(0.05)
        eq('one planner read twice inside PLANNER_SAME_MS is one journal row',
           [r.get('stops') == _STOPS_A for r in planned].count(True), 1)
        eq('...a planner that reads differently is a row of its own, and the same '
           'one again past the window is written again',
           [r.get('stops') == _STOPS_B for r in planned].count(True), 2)
        if planned:
            row = planned[0]
            # The shape syncKey carries a kind row across on: without `id` and
            # `seq` the copy at home would hold none of these.
            eq('...each a collection row the sync can carry',
               (row.get('v'), row.get('id'), row.get('seq'), row.get('asked')),
               (1, 'planner-%s' % row.get('at'), 1, True))
        # ...and C, which the scanner said the journal may not keep, is on the
        # stream and on the order and nowhere on disk.
        for _ in range(60):
            if len([m for m in told if isinstance(m, dict) and m.get('planner')]) >= 5:
                break
            time.sleep(0.05)
        time.sleep(0.2)
        rows = [json.loads(l) for l in open(journal) if l.strip()]
        eq('a planner the scanner says may not be kept — "keepPlaces": false, or no '
           'journal — is not written: no row names its stops',
           [r.get('id') for r in rows if r.get('kind') == 'planner'
            and r.get('stops') == _STOPS_C], [])
        status = get(base, '/api/status')
        held = status.get('holding') or {}
        # With the scanner's reason for filing none of them, so a reloaded
        # panel says what the live one said about the button.
        #
        # Changed 24 Oct, at the owner's ask ("Would there be a way to have
        # the scan button also merge?"): this pinned the LAST pressed read
        # alone, because each press replaced the one before. Pressed reads
        # merge now (Assemble.mergePlanner's `pressed`): B, read with no page
        # known, keeps Pat Q.; C's Sam R. at the same door and minute under
        # another name is a stop of its own (two names, two stops), first by
        # its time. The reason is the last read's.
        eq('the order in the car carries the stops the presses read, merged, and why '
           'none was filed, for a panel reloaded mid-delivery', held.get('planner'),
           {'stops': _STOPS_C + _STOPS_A, 'unfiled': 'dropoffs'})
        # One rule for where an order ends. The scanner sends a dropoff line
        # when a planner gives one; this one did not, so the end stays as it
        # was — a server that read an address out of the stops itself would be
        # a second answer to the question emit_dropoff already answers.
        eq('...and no destination of its own: the order keeps the end it had',
           (held.get('dropoff'), held.get('dropoffScanned')), (None, False))
        no_('...nor a mark written from the stops',
            any(r.get('kind') == 'mark' and r.get('dropoff') for r in rows))
        eq('the panel is told each planner on the stream, kept or not',
           len([m for m in told if isinstance(m, dict) and m.get('planner')]), 5)
        # Collection only: the fold skips a kind it has no use for, so the
        # offers page and every total on it are what they were.
        page = get(base, '/api/journal?days=0')
        eq('the offers page does not count a planner row as an offer',
           [o.get('id') for o in (page.get('offers') or [])
            if str(o.get('id') or '').startswith('planner')], [])
        # ...and the row the server wrote is one the sync recognises when it
        # comes back: ingest builds its de-duplication over syncKey, so a row it
        # could not key would be refused as malformed, and one keyed wrongly
        # would be stored twice.
        if planned:
            _req = urllib.request.Request(
                base + '/api/journal/ingest',
                data=(json.dumps(planned[0]) + '\n').encode('utf-8'),
                headers={'Content-Type': 'application/x-ndjson'})
            _back = json.loads(urllib.request.urlopen(_req, timeout=10).read().decode())
            eq('...and a planner row synced back is recognised as already here',
               (_back.get('added'), _back.get('malformed')), (0, 0))
        # Put down, the stops go with the order.
        code, _ = post(base, '/api/delivered', {})
        eq('...and they go when the order is put down',
           (code, get(base, '/api/status').get('holding')), (200, None))
    finally:
        stop(proc)
        shutil.rmtree(work, ignore_errors=True)

# ...and off the order in the car at the other moment the panel forgets them —
# a different offer on the record — so a reload shows what the live panel
# shows. (A press was the other moment until 24 Oct: it merges now, below.) They were kept until another planner replaced them, and
# a reload after a two-dropoff planner and then a ⌖ press that READ the order's
# end brought back "2 dropoffs: end not guessed" beside a green button. The
# order's read end itself stays: the stack line goes on using it.
if shutil.which('python3'):
    work = tempfile.mkdtemp()
    journal = os.path.join(work, 'journal.jsonl')
    handoff = os.path.join(work, 'handoff')
    os.makedirs(handoff)
    fake = os.path.join(work, 'planner2.py')
    _TWO = [{'kind': 'dropoff', 'orders': 1, 'name': n, 'expectedBy': 978,
             'street': None, 'city': None, 'state': None, 'zip': None, 'line': None}
            for n in ('Pat Q.', 'Lee M.')]
    with open(fake, 'w') as fh:
        fh.write(
            'import json, sys, time\n'
            'T = %s\n'
            'def say(x):\n'
            '    print(json.dumps(x), flush=True)\n'
            'def planner():\n'
            '    say({"planner": {"stops": T, "unfiled": "dropoffs", "keep": True,\n'
            '         "asked": True, "ms": None, "at": int(time.time() * 1000)}})\n'
            'time.sleep(2.0)\n'
            'planner()\n'
            '# The press the test makes in this gap reads the navigation screen.\n'
            'time.sleep(2.5)\n'
            'say({"dropoff": {"line": "12 Oak St, Marietta, GA 30060", "street":\n'
            '     "12 Oak St", "city": "Marietta", "state": "GA", "zip": "30060",\n'
            '     "found": True, "asked": True, "at": int(time.time() * 1000)}})\n'
            'time.sleep(1.0)\n'
            'planner()\n'
            '# ...and a different card goes on the record.\n'
            'time.sleep(2.5)\n'
            'say({"offer": {"id": "o-next-card", "pay": 9.5, "minutes": 20,\n'
            '     "perHour": 18, "dropoff": None}})\n'
            'time.sleep(600)\n' % json.dumps(_TWO).replace('null', 'None'))
    open(journal, 'w').close()
    proc, base = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable,
                        'SCANNER_ARGS': fake, 'UBERSCAN_HANDOFF_DIR': handoff},
                       journal)

    def _held_planner(want_some, seconds=6.0):
        """holding.planner once it is (or is not) there, polled."""
        h = None
        for _ in range(int(seconds / 0.05)):
            h = (get(base, '/api/status').get('holding') or {})
            if bool(h.get('planner')) == want_some:
                break
            time.sleep(0.05)
        return h

    try:
        # ⟳ Re-find is gone from the panel at the owner's request (AUDITS.md,
        # Settled), and with nothing left to call it the door it knocked on
        # went too. A press from a page one version behind is refused, and
        # nothing is left in the handoff directory for the scanner to act on.
        _rq = urllib.request.Request(base + '/api/recalibrate', data=b'',
                                     method='POST')
        try:
            with urllib.request.urlopen(_rq, timeout=5) as _r:
                _code = _r.status
        except urllib.error.HTTPError as _e:
            _code = _e.code
        eq('there is no re-find endpoint any more', _code, 405)
        eq('...and asking for one leaves no request for the scanner',
           sorted(n for n in os.listdir(handoff) if 'recalibrate' in n), [])
        code, reply = post(base, '/api/offers/mark', {
            'id': 'o-carried', 'accepted': True,
            'offer': {'id': 'o-carried', 'pay': 14.0, 'minutes': 30.0,
                      'billedMinutes': 30.0, 'miles': 6.0, 'cost': 2.1,
                      'dropoff': None}})
        ok_('the premise: an order is in the car before the planners are read',
            code == 200 and reply.get('holding') is True)
        ok_('the premise: the order in the car holds a two-dropoff planner',
            (_held_planner(True).get('planner') or {}).get('unfiled') == 'dropoffs')
        # Changed 24 Oct, at the owner's ask ("Would there be a way to have
        # the scan button also merge?"): these pinned that a press took the
        # planner off the order. It keeps it now, for the press's own planner
        # read to merge into (Assemble.mergePlanner's `pressed`), and the panel
        # keeps the held stops through the press too, so a reload still shows
        # what the live panel shows. The "not guessed" line the old fault put
        # beside the green button stays off it: unfiledNow says nothing once
        # the order has an end (test_dashboard's 'reloadedEnd').
        code, _ = post(base, '/api/dropoff', {})
        eq('a ⌖ press keeps the planner on the order in the car, as the panel keeps '
           'its stops', (code, [s.get('name') for s in
                                ((get(base, '/api/status').get('holding') or {})
                                 .get('planner') or {}).get('stops') or []]),
           (200, ['Pat Q.', 'Lee M.']))
        held = {}
        for _ in range(80):
            held = get(base, '/api/status').get('holding') or {}
            if held.get('dropoff'):
                break
            time.sleep(0.05)
        eq('...so a reload after that press read the order\'s end shows the end '
           'and the stops beside it',
           (held.get('dropoff'), held.get('dropoffScanned'),
            len((held.get('planner') or {}).get('stops') or [])),
           ('12 Oak St, Marietta, GA 30060', True, 2))
        ok_('the premise: a planner is held again before the next card',
            bool(_held_planner(True).get('planner')))
        held = _held_planner(False)
        eq('...and a different offer on the record takes it off too, and leaves '
           'the order its end', (held.get('planner'), held.get('dropoff')),
           (None, '12 Oak St, Marietta, GA 30060'))
    finally:
        stop(proc)
        shutil.rmtree(work, ignore_errors=True)

# --- a card too old to attach an address to ----------------------------------
#
# The ceiling, which is the whole of what keeps the old rule's protection. An
# address read long after the card left the screen belongs to nothing, and
# putting it on the last card the rig happened to read is exactly the
# confidently-wrong answer this project refuses. Two minutes in the car; a
# tenth of a second here, because a check that waits out the real window is a
# check nobody runs.
if shutil.which('python3'):
    work = tempfile.mkdtemp()
    journal = os.path.join(work, 'journal.jsonl')
    fake = os.path.join(work, 'stale.py')
    with open(fake, 'w') as fh:
        fh.write(
            'import json, sys, time\n'
            'print(json.dumps({"ready": True, "state": "go", "perHour": 30.0,\n'
            '    "grossPerHour": 36.0, "pay": 12.0, "minutes": 24.0, "miles": 5.0,\n'
            '    "cost": 1.75, "billedMinutes": 24.0, "target": 25, "band": 15,\n'
            '    "costPerMile": 0.35, "at": int(time.time() * 1000),\n'
            '    "offer": {"id": "o-old", "pay": 12.0, "minutes": 24.0,\n'
            '              "billedMinutes": 24.0, "miles": 5.0, "cost": 1.75,\n'
            '              "perHour": 30.0, "target": 25, "band": 15,\n'
            '              "costPerMile": 0.35, "dropoff": None}}), flush=True)\n'
            'time.sleep(1.5)\n'
            'print(json.dumps({"dropoff": {"line": "3100 Esquire Dr NW, Kennesaw, GA 30144",\n'
            '    "street": "3100 Esquire Dr NW", "city": "Kennesaw", "state": "GA",\n'
            '    "zip": "30144", "at": int(time.time() * 1000)}}), flush=True)\n'
            'time.sleep(600)\n')
    open(journal, 'w').close()
    proc, base = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable,
                        'SCANNER_ARGS': fake, 'SCREENING_MS': '300'}, journal)
    try:
        # The address is announced on the stream, not on /api/status — see
        # live.html's `msg.dropoff.line` listener, which is where the button
        # gets what it shows. So this waits out the fake's own schedule rather
        # than polling for a field, and then asks the two questions that are
        # about storage.
        time.sleep(2.6)
        s = get(base, '/api/status')
        no_('an address read after the card went stale does not land on it',
            (s.get('offer') or {}).get('dropoff'))
        rows = [json.loads(l) for l in open(journal) if l.strip()]
        no_('...and is not written down either',
            any(r.get('kind') == 'mark' and r.get('dropoff') for r in rows))
        # The card itself is untouched, rather than quietly acquiring an
        # address from a reading that came too late to be about it.
        eq('...and the card on the slot is the one it always was',
           (s.get('offer') or {}).get('id'), 'o-old')
    finally:
        stop(proc)
        shutil.rmtree(work, ignore_errors=True)

# --- a journal that cannot be written is said at startup ----------------------
# On a fresh copy machine, JOURNAL under /var/lib as a normal user started
# cleanly and answered the rig's install gate; only the first upload failed.
work = tempfile.mkdtemp()
errlog = open(os.path.join(work, 'err.txt'), 'w')
# A directory that cannot be made: a file stands where it would go.
open(os.path.join(work, 'blocker'), 'w').close()
nowhere = os.path.join(work, 'blocker', 'journal.jsonl')
port = free_port()
proc = subprocess.Popen(
    ['node', os.path.join(ROOT, 'server.js')],
    env=dict(os.environ, PORT=str(port), HTTPS_PORT='0', SCANNER='0', JOURNAL=nowhere),
    stdout=subprocess.DEVNULL, stderr=errlog)
try:
    base = 'http://127.0.0.1:%d' % port
    for _ in range(120):
        try:
            urllib.request.urlopen(base + '/api/status', timeout=1).read()
            break
        except Exception:
            time.sleep(0.1)
    time.sleep(0.3)
    errlog.flush()
    said = open(os.path.join(work, 'err.txt')).read()
    ok_('a JOURNAL its user cannot create is said at startup (%r)' % said[:60],
        'cannot create' in said and os.path.dirname(nowhere) in said)
    ok_('...with the command that fixes it', 'mkdir -p' in said and 'chown' in said)
finally:
    stop(proc)
    errlog.close()
    shutil.rmtree(work, ignore_errors=True)

# --- the export, which had no check at all ----------------------------------
#
# The one artefact of this project that leaves the machine and gets opened by
# something else. Every page here is tested through a browser; the CSV was
# tested by being looked at.
#
# One offer has to be one line. Keeping the reader's own line breaks in `text`
# is deliberate — they are the part a later question is most likely to need —
# and putting them in a cell raw and quoted is legal CSV that every proper
# reader handles. It is also what turned this driver's 104 offers into 2076
# physical lines, 103 of the 104 spanning more than one: `wc -l` said 2075
# offers, and so did every quick script, importer and `head` that splits on
# newlines. None of them said it was guessing.
import csv as _csv
import io as _io

# Inside the window, and past the date the server stops believing a clock: a
# Pi with no RTC boots in 1970, so rows stamped before then are filtered out
# and an export fixture dated 2023 is an export of nothing.
_NOW = int(time.time() * 1000)

_work = tempfile.mkdtemp()
_journal = os.path.join(_work, 'offers.jsonl')
_ROWS = [
    # A card read over two lines, which is what the reader really produces.
    {'v': 3, 'id': 'a1', 'seq': 1, 'at': _NOW - 600_000, 'pay': 16.05,
     'minutes': 23.0, 'miles': 8.4, 'perHour': 30.0, 'state': 'go',
     'suspect': False, 'doubt': None, 'untimedMiles': None, 'whole': True,
     'places': ['Cobb Pkwy NW, Kennesaw', 'Canton Rd, Marietta'],
     'pickup': 'Cobb Pkwy NW, Kennesaw', 'dropoff': 'Canton Rd, Marietta',
     'text': '$16.05 3 min (1.1 mi) away\n20 min (7.3 mi) trip',
     'scans': ['$16.05 3 min\n(1.1 mi) away', '$16.05 3 min (1.1 mi) away']},
    # A row refused for a leg, carrying the field that says how much went
    # missing — and a place with a comma and a quote in it, which is what a
    # cross street looks like when the reader has had a bad night.
    {'v': 3, 'id': 'a2', 'seq': 1, 'at': _NOW - 300_000, 'pay': 18.40,
     'minutes': 5.0, 'miles': 2.1, 'perHour': 213.24, 'state': 'doubt',
     'suspect': True, 'doubt': 'leg', 'untimedMiles': 7.8, 'whole': False,
     'places': ['Duval Ct & Manchester Ln, Villa Rica'],
     'pickup': 'Duval Ct & Manchester Ln, Villa Rica', 'dropoff': None,
     'text': 'UberX $18.40 5 min (2.1 mi) away\nl hr 24 min (7.8 "mi") trip'},
]
with open(_journal, 'w') as _fh:
    for _r in _ROWS:
        _fh.write(json.dumps(_r) + '\n')

_proc, _base = start({'SCANNER': '0'}, _journal)
try:
    _body = urllib.request.urlopen(_base + '/api/journal.csv?days=3650',
                                   timeout=10).read().decode('utf-8')
    _records = list(_csv.reader(_io.StringIO(_body)))
    _head, _rows = _records[0], _records[1:]
    eq('the export has a row per offer', len(_rows), 2)
    # The structural property, and the one a spreadsheet fails silently on.
    eq('...every one of them with the header\'s cells',
       sorted(set(len(r) for r in _rows)), [len(_head)])
    # ...and the property that makes the file safe to count, grep and pipe.
    _lines = _body.rstrip('\n').split('\n')
    eq('one offer is one physical line (%d lines, %d offers)'
       % (len(_lines), len(_rows)), len(_lines), len(_rows) + 1)
    # The line breaks are kept, not thrown away: encoding them is what makes a
    # record one line, and what comes back out has to be exactly what the rig
    # recorded or the column stops being able to answer a question about the
    # parser — which is the only reason it is in the file.
    _first = dict(zip(_head, _rows[0]))
    eq('...with the reader\'s own text coming back exactly as it was stored',
       json.loads(_first['text']), _ROWS[0]['text'])
    ok_('...line breaks and all', '\n' in json.loads(_first['text']))

    _by = dict(zip(_head, _rows[1]))
    eq('a row refused for a leg exports the refusal', _by.get('doubt'), 'leg')
    eq('...and how much of the journey never got timed',
       _by.get('untimedMiles'), '7.8')
    # A comma inside a cell is the whole reason this file needs quoting, and
    # 72% of this driver's distinct dropoffs are cross streets.
    ok_('an address with a comma in it survives as one cell (%r)'
        % _by.get('pickup'), _by.get('pickup') == 'Duval Ct & Manchester Ln, Villa Rica')
    # A quote in the middle of a cell is how a CSV gets cut in half. This one
    # is the reader's — a bracket read as a quote mark — and the cell-count
    # check above is what proves it did not end the field; this proves the
    # character itself survived rather than being stripped to make it safe.
    ok_('...and a quote the reader invented survives without ending the field',
        '"mi"' in json.loads(_by.get('text') or '""'))
    eq('booleans come out as something a spreadsheet can sum',
       _by.get('suspect'), '1')
    eq('...both ways', dict(zip(_head, _rows[0])).get('suspect'), '0')
    eq('a field the card never gave is empty, not the word None',
       _by.get('dropoff'), '')
finally:
    stop(_proc)
    shutil.rmtree(_work, ignore_errors=True)

# --- a hole in the one file that cannot be regenerated -----------------------
#
# The server skipped unparseable lines with a comment saying why and no count.
# Right to skip — the file is append-only and one bad line must not cost the
# other fifty thousand — and wrong to say nothing, because the offers are gone
# and no backup gets them back: the copy machine faithfully receives the hole.
#
# Checked through the incremental reader as well as the first read, because
# that is where a count is easiest to lose: the journal is parsed once and
# after that only the part that grew.
_hole_dir = tempfile.mkdtemp()
_hole = os.path.join(_hole_dir, 'offers.jsonl')
_NOW2 = int(time.time() * 1000)


def _row(i):
    return {'v': 3, 'id': 'h%d' % i, 'seq': 1, 'at': _NOW2 - i * 60_000,
            'pay': 10.0, 'minutes': 20.0, 'miles': 4.0, 'perHour': 25.0,
            'state': 'go', 'whole': True}


with open(_hole, 'w') as _fh:
    _fh.write(json.dumps(_row(0)) + '\n')
    _fh.write(json.dumps(_row(1))[:30] + '\n')     # the engine stopped here
    _fh.write(json.dumps(_row(2)) + '\n')

_hproc, _hbase = start({'SCANNER': '0'}, _hole)
try:
    _first = get(_hbase, '/api/journal?days=30')
    eq('the readable rows are still served', _first['count'], 2)
    eq('...and the line that was lost is counted', _first['torn'], 1)
    # Different question from `unreadable`, which is the whole file being
    # unavailable — a transient. These rows are gone for good.
    eq('...without claiming the journal itself could not be read',
       _first['unreadable'], None)

    # Now the incremental path: the file grows, and only the new bytes are
    # parsed. A count kept per-read rather than accumulated would reset here
    # and report a whole journal on the very next page load.
    with open(_hole, 'a') as _fh:
        _fh.write(json.dumps(_row(3)) + '\n')
    time.sleep(0.05)
    _second = get(_hbase, '/api/journal?days=30')
    eq('an appended row is picked up', _second['count'], 3)
    ok_('...and the earlier casualty is not forgotten (%r)' % _second['torn'],
        _second['torn'] == 1)

    # ...and a second torn line adds to it rather than replacing it.
    with open(_hole, 'a') as _fh:
        _fh.write(json.dumps(_row(4))[:25] + '\n')
    time.sleep(0.05)
    _third = get(_hbase, '/api/journal?days=30')
    eq('a second casualty is added to the first', _third['torn'], 2)

    # The row being written RIGHT NOW is not a casualty. The scanner appends
    # while this reads, so the last line of a live journal routinely has no
    # newline on it yet — counting it would report a fault on every shift.
    with open(_hole, 'a') as _fh:
        _fh.write(json.dumps(_row(5))[:25])
    time.sleep(0.05)
    _live = get(_hbase, '/api/journal?days=30')
    eq('a row still being written is not counted as lost', _live['torn'], 2)
finally:
    stop(_hproc)
    shutil.rmtree(_hole_dir, ignore_errors=True)

# --- a row from the future must not stop the backup ---------------------------
#
# sync.py resumes from `newest - 1h`. One row stamped ahead of real time makes
# that floor a moment no real offer ever reaches, so from that tick on every
# offer is silently skipped — for ever, because nothing looks further back. It
# is silent at every step: the shortfall check anchors its own window to the
# same poisoned `newest` so both sides agree, the run exits 0, and the .synced
# stamp is refreshed, so doctor reports a backup made minutes ago.
#
# A ceiling was added for this and set at 1 Jan 2100, which catches a corrupted
# row and does NOT catch the common case: journal-client.js stamps `at` from the
# phone's own Date.now(), so a phone a month fast lands a row a month ahead and
# sails under a ceiling seventy years out.
_fdir = tempfile.mkdtemp()
_fjournal = os.path.join(_fdir, 'j.jsonl')
_fnow = int(time.time() * 1000)
with open(_fjournal, 'w') as _fh:
    for _i in range(40):
        _fh.write(json.dumps({'v': 1, 'id': 'f%d' % _i, 'seq': 1,
                              'at': _fnow - (40 - _i) * 600000,
                              'pay': 10.0, 'minutes': 20.0}) + '\n')
    _fh.write(json.dumps({'v': 1, 'id': 'fpoison', 'seq': 1,
                          'at': _fnow + 45 * 86400000,
                          'pay': 9.0, 'minutes': 20.0}) + '\n')

_fproc, _fbase = start({'SCANNER': '0'}, _fjournal)
try:
    _n = get(_fbase, '/api/journal/newest')
    ok_('a row stamped a month ahead is not taken as the newest offer '
        '(%.1f days out)' % ((_n['newest'] - _fnow) / 86400000.0),
        _n['newest'] <= _fnow + 86400000)
    ok_('...the real last offer is', abs(_n['newest'] - (_fnow - 600000)) < 120000)
    # Not DROPPED, only not believed. The row is on disk and the sender still
    # has to be told the far end holds it, or it would be sent again for ever.
    eq('...and the row itself is still counted as held', _n['have'], 41)
    # Counted as an OFFER too, which is the figure the sender compares against
    # its own to notice a gap and repair it. Under-counting here is the safe
    # direction — the sender re-sends — but it is still a number two machines
    # reconcile on, and a number nothing pins is a number free to drift the
    # other way.
    eq('...and counted among the offers the copy holds', _n['offers'], 41)
finally:
    stop(_fproc)

# ...and the guard that makes that safe on a machine whose own clock is not set.
#
# The ceiling is taken off Date.now(), and this same file runs on the Pi, which
# has no RTC and boots in 1970 until NTP arrives. A ceiling off an unset clock
# would put EVERY row above it and answer `newest: 0` — which loses far more
# than the fault being fixed, and in the default configuration with no poison
# row present at all. The clock boundary is overridable so this branch can be
# reached; moving it past today is what "this machine cannot vouch for its own
# clock" looks like.
_uproc, _ubase = start({'SCANNER': '0',
                        'CLOCK_BELIEVABLE_AFTER': '4102444800000'}, _fjournal)
try:
    _u = get(_ubase, '/api/journal/newest')
    no_('a machine that cannot vouch for its clock does not answer newest 0',
        _u['newest'] == 0)
    # It falls back to the fixed ceiling, so the poison row wins again — which
    # is exactly today's behaviour and is the point: no better, and no worse.
    ok_('...it falls back to the fixed ceiling rather than to nothing',
        _u['newest'] > _fnow)
    eq('...and still holds every row', _u['have'], 41)
finally:
    stop(_uproc)
    shutil.rmtree(_fdir, ignore_errors=True)

# --- places the browser looked up, kept where they outlive the browser --------
#
# The map page's geocode cache was localStorage and nothing else, so it belonged
# to whichever browser did the placing: check the map on the laptop and again on
# the phone and that is two full runs, and clearing site data loses the lot.
# Measured on the owner's own week, 1,325 distinct places at one a second is
# about 24 minutes to rebuild.
#
# The rig still never geocodes. This stores an answer the BROWSER already has.
_pdir = tempfile.mkdtemp()
_pjournal = os.path.join(_pdir, 'j.jsonl')
open(_pjournal, 'w').close()
_pproc, _pbase = start({'SCANNER': '0'}, _pjournal)
try:
    # A box that has never been told anything is an empty cache, not a fault.
    _empty = get(_pbase, '/api/places')
    eq('a server with no places file answers an empty set', _empty['places'], {})
    eq('...and says so rather than erroring', _empty['ok'], True)

    _code, _said = post(_pbase, '/api/places', {
        'Chipotle, Marietta': {'lat': 34.02, 'lon': -84.58},
        # null is "asked, nothing there", and it is worth keeping: it is what
        # stops the next run paying a second to ask again.
        'Nowhere St': None})
    eq('places sent by the browser are accepted', _code, 200)
    eq('...and counted', _said['added'], 2)
    _back = get(_pbase, '/api/places')['places']
    eq('...and come back on the next load', _back['Chipotle, Marietta'],
       {'lat': 34.02, 'lon': -84.58})
    ok_('...including the empty answer', 'Nowhere St' in _back and _back['Nowhere St'] is None)
    ok_('...and they are on disk beside the journal',
        os.path.exists(os.path.join(_pdir, 'places.json')))

    # MERGED, never written over. Two browsers place different days of the same
    # journal; a POST that replaced the file would have whichever finished last
    # throw the other's work away.
    _code2, _said2 = post(_pbase, '/api/places', {'Zaxbys, Kennesaw': {'lat': 34.03, 'lon': -84.61}})
    eq('a second browser adds without replacing', _said2['added'], 1)
    _both = get(_pbase, '/api/places')['places']
    eq('...and both are held', sorted(_both.keys()),
       ['Chipotle, Marietta', 'Nowhere St', 'Zaxbys, Kennesaw'])

    # "Could not ask" is not an answer and must not be stored: one dead spot on
    # I-75 would otherwise become a permanent "this street does not exist".
    _code3, _said3 = post(_pbase, '/api/places', {'Asked But Nobody Home': 'nope'})
    eq('a value that is not a coordinate is refused', _said3['added'], 0)
    no_('...and does not reach the file',
        'Asked But Nobody Home' in get(_pbase, '/api/places')['places'])
    _code4, _said4 = post(_pbase, '/api/places', [1, 2, 3])
    eq('a body that is not a set of places is refused', _code4, 400)

    # A cache file that will not parse is a silent re-run of all 24 minutes.
    with open(os.path.join(_pdir, 'places.json'), 'w') as _fh:
        _fh.write('{ not json')
    _torn = get(_pbase, '/api/places')
    eq('an unreadable places file reads as empty', _torn['places'], {})
    ok_('...and says why, rather than looking like a fresh box',
        'did not parse' in (_torn.get('unreadable') or ''))
    # ...and one that is there and cannot be READ is the same loss. It answered
    # `stored: null` with no `unreadable`, which the page has nothing to say
    # about. A directory in its place is the read error a test can make as root,
    # where a chmod would not stop anything.
    os.remove(os.path.join(_pdir, 'places.json'))
    os.mkdir(os.path.join(_pdir, 'places.json'))
    _shut = get(_pbase, '/api/places')
    eq('a places file that cannot be read reads as empty', _shut['places'], {})
    ok_('...and says so too, rather than looking like a fresh box (%r)'
        % _shut.get('unreadable'),
        'could not be read' in (_shut.get('unreadable') or ''))
    os.rmdir(os.path.join(_pdir, 'places.json'))

    # --- and thrown away, which is what makes the page's button true --------
    #
    # map.html's "Forget lookups" cleared the browser's copy and said
    # "remembered lookups thrown away". Every answer the page ever produced is
    # POSTed here, loadPlaces() GETs the whole set back, and load() runs on the
    # next press of Load AND when the page opens — so the button undid itself
    # on the first thing anyone pressed after it, and the one control that can
    # remove a bad geocode removed nothing.
    post(_pbase, '/api/places', {'Bad Lookup, Nowhere': {'lat': 41.9, 'lon': -87.6},
                                 'Good One, Kennesaw': {'lat': 34.03, 'lon': -84.61}})
    eq('the two lookups are on the server to begin with',
       len(get(_pbase, '/api/places')['places']), 2)
    _dcode, _dsaid = delete(_pbase, '/api/places')
    eq('the server lets them be thrown away', _dcode, 200)
    eq('...and says how many it had', _dsaid.get('removed'), 2)
    eq('...and the next page to ask gets none of them back',
       get(_pbase, '/api/places')['places'], {})
    # Pressing it twice is not an error: already gone is the state it asks for.
    _dcode2, _dsaid2 = delete(_pbase, '/api/places')
    eq('throwing away an empty cache is not a failure', _dcode2, 200)
    eq('...and reports nothing removed', _dsaid2.get('removed'), 0)

    # --- two browsers placing at once, which the handler promised to survive --
    #
    # The handler's own comment says what it was for: "MERGED, never written
    # over. Two browsers place different days of the same journal, and a POST
    # that replaced the file would have whichever finished last throw the
    # other's work away." It did exactly that, because the merge was a read, a
    # decision and a write with nothing holding the three together, and the
    # write went through one fixed `places.json.part`.
    #
    # Measured before the fix, ten runs of the two POSTs below against a seeded
    # 1,325-place file: TWO left places.json unparseable with GET answering
    # `stored: 0`, and the other EIGHT lost one writer's batch entirely while
    # replying `stored: 1925` over a file holding 1,326. None of the ten came
    # out right. Two things were wrong and each needed its own cure — unique
    # `.part` names so the bytes cannot interleave, and a queue so the second
    # read cannot happen before the first write lands.
    #
    # Sized to keep the window open: one body big enough that its write does not
    # finish inside a tick, one small enough to overtake it.
    # 1,325, which is the owner's own distinct-place count and what the Settled
    # entry prices at 24 minutes to rebuild. The SIZE is load-bearing: written
    # first at 400 places the whole merge finished inside one tick, the two
    # requests never overlapped, and all three reverts of this fix passed the
    # check. A race the test cannot open is a check that cannot fail.
    _seed = dict(('Seed St %d, Marietta' % i, {'lat': 34.0 + i * 1e-5, 'lon': -84.6})
                 for i in range(1325))
    _batchA = dict(('A Rd %d, Acworth' % i, {'lat': 34.1, 'lon': -84.7})
                   for i in range(600))
    _batchB = {'B Rd 1, Kennesaw': {'lat': 34.2, 'lon': -84.5}}
    post(_pbase, '/api/places', _seed)
    _said = {}

    def _fire(which, payload):
        try:
            _said[which] = post(_pbase, '/api/places', payload)
        except Exception as exc:                      # noqa: BLE001
            _said[which] = ('threw', str(exc))

    _ta = threading.Thread(target=_fire, args=('A', _batchA))
    _tb = threading.Thread(target=_fire, args=('B', _batchB))
    _ta.start()
    _tb.start()
    _ta.join()
    _tb.join()
    _after = get(_pbase, '/api/places')
    # The file still parses. This is the half that costs the whole 24 minutes.
    ok_('two batches at once leave the cache readable',
        not (_after.get('unreadable') or ''))
    # ...and neither writer's work was thrown away, which is what the comment
    # above the handler promises and what the queue is for. 400 + 600 + 1.
    eq('...and both batches are in it', _after.get('stored'), 1926)
    eq('...with the big batch\'s places really there',
       sum(1 for k in (_after.get('places') or {}) if k.startswith('A Rd ')), 600)
    ok_('...and the small one too', 'B Rd 1, Kennesaw' in (_after.get('places') or {}))
    # Both replies were true AT THE MOMENT THEY WERE SENT, which is a weaker
    # claim than "both match the file" and the only one that is right: the queue
    # runs them in some order, so the first writer honestly reports a partial
    # total and the second reports the lot. Written as "both equal the file"
    # first, and B failed with 401 against 1001 — the test being wrong, not the
    # server. What distinguishes an honest partial from the failure this pins is
    # that no reply may claim MORE than the file ends up holding: the POST that
    # hid this answered `stored: 1925` over a file holding 1,326.
    _counts = []
    for _who in ('A', 'B'):
        _code, _body = _said.get(_who, (0, {}))
        eq('...and the %s reply was a success' % _who, _code, 200)
        _counts.append(_body.get('stored'))
        ok_('...claiming no more than the file ends up holding (%s: %s)'
            % (_who, _body.get('stored')),
            isinstance(_body.get('stored'), int)
            and _body['stored'] <= _after.get('stored'))
    # ...and whichever ran second saw everything, so between them the replies
    # account for the whole file rather than both describing a partial one.
    eq('...and the one that ran second reports the whole cache',
       max(_counts), _after.get('stored'))
    # ...and the queue drained. A lock that is taken and not given back answers
    # the request that took it and then strands every later one behind a holder
    # that has gone — which is silence, not an error, and is exactly what the
    # ingest lock's own comment says a forgotten release would do. Nothing after
    # the pair above would have noticed, so this asks.
    # Caught, because a held lock makes this HANG rather than answer, and an
    # unhandled timeout here ends the suite in a traceback with no named check
    # against it — which the mutation sweep cannot tell from a pass.
    try:
        _ncode, _nsaid = post(_pbase, '/api/places',
                              {'C Rd 1, Woodstock': {'lat': 34.1, 'lon': -84.5}})
    except Exception as _exc:                          # noqa: BLE001
        _ncode, _nsaid = 'no answer: %s' % type(_exc).__name__, {}
    eq('a batch arriving after two at once is still answered', _ncode, 200)
    eq('...and lands on top of both of them', _nsaid.get('stored'), 1927)

    # --- and the calibration backup, which queues for the same reason --------
    #
    # The overlap here needs no imagining: sync.py's own stderr tells the
    # operator to run `--all` by hand, and the installed ten-minute timer keeps
    # ticking. Two of those at once left `config-backup.json` unparseable at
    # 60,168 bytes — and what is lost is the copy of the calibration on the one
    # machine that is NOT in the car, so it is believed until somebody tries to
    # restore it. Bodies sized the same way as the places pair: one big enough
    # that its write spans ticks, one small enough to overtake it.
    _cfgA = {'quad': [[1, 2], [3, 4], [5, 6], [7, 8]],
             'pad': dict(('k%d' % i, 'v' * 40) for i in range(700))}
    _cfgB = {'quad': [[9, 9], [9, 9], [9, 9], [9, 9]]}
    _csaid = {}

    def _fireCfg(which, payload):
        try:
            _csaid[which] = post(_pbase, '/api/config/backup', payload)
        except Exception as exc:                       # noqa: BLE001
            _csaid[which] = ('threw', str(exc))

    _ca = threading.Thread(target=_fireCfg, args=('A', _cfgA))
    _cb = threading.Thread(target=_fireCfg, args=('B', _cfgB))
    _ca.start()
    _cb.start()
    _ca.join()
    _cb.join()
    _cfgPath = os.path.join(_pdir, 'config-backup.json')
    _cfgRaw = ''
    if os.path.exists(_cfgPath):
        with open(_cfgPath, encoding='utf-8') as _fh:
            _cfgRaw = _fh.read()
    _cfgParsed = None
    try:
        _cfgParsed = json.loads(_cfgRaw)
    except Exception:                                  # noqa: BLE001
        _cfgParsed = None
    ok_('two calibration backups at once leave a file that parses (%d bytes)'
        % len(_cfgRaw), _cfgParsed is not None)
    # Whichever landed last, it is ONE of the two whole configs and not a
    # mixture of both — the failure was a 60KB body with a 40-byte one spliced
    # into it, which still contains `quad` and would restore garbage.
    ok_('...and holds exactly one of the two, whole',
        _cfgParsed in (_cfgA, _cfgB))
    for _who in ('A', 'B'):
        eq('...and the %s backup was answered' % _who,
           (_csaid.get(_who) or (0,))[0], 200)
finally:
    stop(_pproc)
    shutil.rmtree(_pdir, ignore_errors=True)

# --- the order in the car survives the ignition ------------------------------
#
# `scanner.holding` was process memory, on "a box velcroed into a car where the
# ignition is the power switch" — rpi/calibrate.py's own words. Press Took,
# drive to the restaurant, switch the engine off, walk in, come back: no order
# in the car, the stack line quiet, Drop and the dropoff scan gone, every card
# for the rest of that delivery judged standalone with nothing saying why. On
# the owner's week 58% of accepted jobs have a `go`-rated offer arrive while
# they are still running.
#
# The comment at /api/delivered argued the opposite and is answered rather than
# ignored: it is right that forgetting is the safer error, and wrong that
# keeping it forces the other one. holding() expires an order on its own stated
# time plus HOLD_OVERRUN plus HOLD_GRACE_MS, and a restored order is read
# through exactly that.
_hdir = tempfile.mkdtemp()
_hjournal = os.path.join(_hdir, 'offers.jsonl')
_hold = os.path.join(_hdir, 'holding.json')
# ...and the scanner's copy of "an order is in the car until <ms>", which is
# what lets it read Uber's Trip Planner without a press (order_held in
# rpi/scan_pi.py). A handoff directory of its own, so its one file can be
# named and looked at.
_hhand = os.path.join(_hdir, 'handoff')
os.mkdir(_hhand)
_hheld = os.path.join(_hhand, 'uberscan-holding.json')


def _held_until():
    try:
        with open(_hheld) as fh:
            return json.load(fh).get('until')
    except (OSError, ValueError):
        return None
# A scanner of its own, because the hold is set from the SLOT — marking a row
# in the journal does not put an order in the car, and with no scanner there is
# no slot. This is the write half; everything after it is the read half.
_hfake = os.path.join(_hdir, 'fake.py')
with open(_hfake, 'w') as _fh:
    _fh.write(
        'import json, sys, time\n'
        'print(json.dumps({"ready": True, "state": "go", "perHour": 30.0,\n'
        '    "grossPerHour": 36.0, "pay": 21.0, "minutes": 30.0, "miles": 5.0,\n'
        '    "cost": 1.75, "billedMinutes": 30.0, "target": 25, "band": 15,\n'
        '    "costPerMile": 0.35, "at": int(time.time() * 1000),\n'
        '    "offer": {"id": "h-1", "pay": 21.0, "minutes": 30.0,\n'
        '              "billedMinutes": 30.0, "miles": 5.0, "cost": 1.75,\n'
        '              "perHour": 30.0, "target": 25, "band": 15,\n'
        '              "costPerMile": 0.35, "dropoff": "Oak Ln, Marietta"}}),\n'
        '    flush=True)\n'
        'time.sleep(600)\n')
open(_hjournal, 'w').close()
_hproc, _hbase = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable,
                        'SCANNER_ARGS': _hfake, 'UBERSCAN_HANDOFF_DIR': _hhand},
                       _hjournal)
try:
    _on = None
    for _ in range(120):
        _s = get(_hbase, '/api/status')
        if (_s.get('offer') or {}).get('id') == 'h-1':
            _on = _s
            break
        time.sleep(0.05)
    ok_('a card reaches the slot', _on is not None)
    _hcode, _hsaid = post(_hbase, '/api/offers/mark',
                          {'id': 'h-1', 'accepted': True})
    eq('an offer on the slot can be marked taken', _hcode, 200)
    ok_('...and the server says an order is being carried',
        (get(_hbase, '/api/status') or {}).get('holding'))
    ok_('...and it is written down, not only remembered',
        os.path.exists(_hold))
    # Stated 30 minutes, half again, and the default ten-minute grace: the
    # moment holding() stops answering yes, which is what the scanner is told.
    # (The file is a list of orders since Stage 4: `{v: 2, orders: [...]}`.)
    _accepted = json.load(open(_hold))['orders'][0].get('acceptedAt')
    eq('...and the scanner is told until when, the moment holding() lets go',
       _held_until(), _accepted + 30 * 1.5 * 60000 + 10 * 60000)
    # ...and WHICH order, so the scanner forgets the address it last
    # volunteered when the order changes (held_signature in rpi/scan_pi.py).
    eq('...and which order it is, by the name the panel knows it by',
       json.load(open(_hheld)).get('holds'), ['h-1@%d' % _accepted])
finally:
    stop(_hproc)
# Taken away here, so the restart below has to write it again for the order it
# restores — a hold brought back at boot is a hold the scanner must hear of.
if os.path.exists(_hheld):
    os.remove(_hheld)

# The engine goes off and comes back on. Same journal, same file, new process.
#
# Started with its output kept, because the restored order is state the driver
# pressed nothing for on THIS run and the boot line is the only place anything
# says so — and because that line must not announce an order /api/status will
# then deny.
def _start_loud(env, journal):
    port = free_port()
    proc = subprocess.Popen(
        ['node', os.path.join(ROOT, 'server.js')],
        env=dict(os.environ, PORT=str(port), HTTPS_PORT='0', JOURNAL=journal,
                 **env),
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    base = 'http://127.0.0.1:%d' % port
    for _ in range(120):
        try:
            urllib.request.urlopen(base + '/api/status', timeout=1).read()
            return proc, base
        except Exception:
            time.sleep(0.1)
    proc.kill()
    raise RuntimeError('the server never came up')


_hproc2, _hbase2 = _start_loud({'SCANNER': '0', 'UBERSCAN_HANDOFF_DIR': _hhand},
                               _hjournal)
try:
    _back = (get(_hbase2, '/api/status') or {}).get('holding')
    ok_('a restarted server still has the order in the car (%r)'
        % ((_back or {}).get('pay'),), bool(_back))
    eq('...and the scanner is told of it again, until the same moment',
       _held_until(), _accepted + 30 * 1.5 * 60000 + 10 * 60000)
    if _back:
        eq('...the same one', _back.get('pay'), 21.0)
        eq('...with where it ends, which is what the stack line needs',
           _back.get('dropoff'), 'Oak Ln, Marietta')
    # ...and putting it down removes the file, so the NEXT restart does not
    # bring back a job that has been delivered.
    post(_hbase2, '/api/delivered', {})
    no_('an order put down is gone from the panel',
        (get(_hbase2, '/api/status') or {}).get('holding'))
    no_('...and gone from the disk too', os.path.exists(_hold))
    no_('...and the scanner is no longer told an order is held',
        os.path.exists(_hheld))
finally:
    _hproc2.terminate()
    try:
        _hproc2.wait(timeout=5)
    except Exception:
        _hproc2.kill()

# ...and the boot line SAYS the order is there, because it is state nobody
# pressed anything for on this run. Read after the drop above, which is when
# the process has printed everything it is going to.
_hout = ''
try:
    _hout = _hproc2.stdout.read() or ''
except Exception:
    _hout = ''
ok_('the restart says out loud that it is carrying an order (%r)'
    % (_hout[-90:].replace('\n', ' '),),
    'carrying an order from before the restart' in _hout)

# A HOLD STAMPED IN THE FUTURE IS REFUSED, both directions on the clock, for
# the same reason journal.py's resume() does it: a Pi has no real-time clock,
# boots in 1970 and jumps when the network arrives. `over` in holding() is
# `now - acceptedAt - ...`, so a stamp ahead of the clock now reading it never
# goes positive — the order would never expire and the panel would offer a pair
# line against it for the rest of the shift.
with open(_hold, 'w') as _fh:
    json.dump({'id': 'h-1', 'pay': 21.0, 'minutes': 30,
               'acceptedAt': NOW + 3600000}, _fh)
_hproc3, _hbase3 = start({'SCANNER': '0'}, _hjournal)
try:
    no_('a held order stamped after the clock reading it is refused',
        (get(_hbase3, '/api/status') or {}).get('holding'))
finally:
    stop(_hproc3)

# ...and one that has outlived its own clock is put down at boot rather than
# waiting to be noticed, which is holding()'s rule and not a second one.
with open(_hold, 'w') as _fh:
    json.dump({'id': 'h-1', 'pay': 21.0, 'minutes': 30,
               'acceptedAt': NOW - 86400000}, _fh)
_hproc4, _hbase4 = _start_loud({'SCANNER': '0'}, _hjournal)
try:
    no_('a held order past its own stated time is not brought back',
        (get(_hbase4, '/api/status') or {}).get('holding'))
finally:
    _hproc4.terminate()
    try:
        _hproc4.wait(timeout=5)
    except Exception:
        _hproc4.kill()
# ...and the boot line does not announce it either. loadHolding answers through
# holding(), so the sentence and /api/status cannot disagree — without that,
# the rig greets the driver with an order the very next request denies.
_hout4 = ''
try:
    _hout4 = _hproc4.stdout.read() or ''
except Exception:
    _hout4 = ''
no_('...and the boot line does not announce one either',
    'carrying an order from before the restart' in _hout4)

# ...and neither is one with no stamp on it at all, which is the shape that
# would never go away: `over` in holding() is `now - acceptedAt - ...`, and with
# acceptedAt missing that is NaN, `over > 0` is false, and the order is carried
# for the rest of the shift with a pair line against it.
with open(_hold, 'w') as _fh:
    json.dump({'id': 'h-1', 'pay': 21.0, 'minutes': 30}, _fh)
_hproc6, _hbase6 = start({'SCANNER': '0'}, _hjournal)
try:
    no_('a held order with no stamp is refused rather than carried for ever',
        (get(_hbase6, '/api/status') or {}).get('holding'))
finally:
    stop(_hproc6)

# ...nor one whose stamp is a STRING. `isFinite("30")` is true, so the type
# test is the only thing between a hand-edited file and arithmetic on a value
# that is not a time — and this file sits beside the journal where a person
# looking for the journal will find it.
with open(_hold, 'w') as _fh:
    json.dump({'id': 'h-1', 'pay': 21.0, 'minutes': 30,
               'acceptedAt': str(NOW - 60000)}, _fh)
_hproc7, _hbase7 = start({'SCANNER': '0'}, _hjournal)
try:
    no_('a held order whose stamp is not a number is refused',
        (get(_hbase7, '/api/status') or {}).get('holding'))
finally:
    stop(_hproc7)

# A file that will not parse is not a held order, and must not stop the server
# coming up — the panel is worth more than the hold.
with open(_hold, 'w') as _fh:
    _fh.write('{not json at all')
_hport5 = free_port()
_hproc5 = subprocess.Popen(
    ['node', os.path.join(ROOT, 'server.js')],
    env=dict(os.environ, PORT=str(_hport5), HTTPS_PORT='0', JOURNAL=_hjournal,
             SCANNER='0'),
    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
_hbase5 = 'http://127.0.0.1:%d' % _hport5
for _ in range(120):
    try:
        urllib.request.urlopen(_hbase5 + '/api/status', timeout=1).read()
        break
    except Exception:
        time.sleep(0.1)
try:
    # Still ALIVE a moment later, not merely answering once. loadHolding runs
    # in the listen callback, so an exception there lands after the port is
    # open: the first request can succeed and the process be gone by the
    # second. Without the pause this check passed with the guard deleted.
    time.sleep(0.5)
    ok_('a hold file that will not parse still lets the server start',
        (get(_hbase5, '/api/status') or {}).get('scanner') is not None)
    eq('...and the process is still running, not dead behind an open port',
       _hproc5.poll(), None)
    no_('...and is not read as an order', (get(_hbase5, '/api/status') or {}).get('holding'))
finally:
    _hproc5.terminate()
    try:
        _hproc5.wait(timeout=5)
    except Exception:
        _hproc5.kill()
# ...and does it QUIETLY. The process survives either way, because this server
# logs an uncaught exception and carries on rather than dying — so without the
# guard the only signs are a stack trace at boot and the rest of the startup
# never running. A file the driver has never heard of must not greet them with
# one.
_herr5 = ''
try:
    _herr5 = _hproc5.stderr.read() or ''
except Exception:
    _herr5 = ''
no_('...without a stack trace at boot (%r)' % (_herr5[:70].replace('\n', ' '),),
    'uncaught' in _herr5)

# --- an order that outlives its own clock leaves a drop row ------------------
#
# holding() put such an order down and wrote nothing, so tools/shift_report.py
# could not tell an expiry from a hold the server lost: both were "no end". It
# now writes `kind: 'drop'`, `by: 'expiry'`, dated at holdEnds — the moment
# the server stopped counting the order — and not at whichever call noticed,
# which after a restart is the boot. Once per order. Invented ids; no place.
_xdir = tempfile.mkdtemp()
_xjournal = os.path.join(_xdir, 'offers.jsonl')
_xhold = os.path.join(_xdir, 'holding.json')
open(_xjournal, 'w').close()


def _xdrops():
    rows = [json.loads(l) for l in open(_xjournal) if l.strip()]
    return [(r.get('id'), r.get('by'), r.get('at'), r.get('seq'), r.get('acceptedAt'))
            for r in rows if r.get('kind') == 'drop']


# Two orders the server was down for, past their clocks by a day, each with
# its own minutes so the two rows cannot share a date by accident.
_xa = NOW - 86400000
with open(_xhold, 'w') as _fh:
    json.dump({'v': 2, 'orders': [
        {'id': 'x-1', 'pay': 11.0, 'minutes': 30, 'acceptedAt': _xa},
        {'id': 'x-2', 'pay': 7.0, 'minutes': 12, 'acceptedAt': _xa + 60000}]}, _fh)
_xend1 = _xa + 30 * 1.5 * 60000 + 10 * 60000
_xend2 = _xa + 60000 + 12 * 1.5 * 60000 + 10 * 60000
_xproc, _xbase = start({'SCANNER': '0'}, _xjournal)
try:
    no_('(the premise: an order past its clock at boot is not carried)',
        (get(_xbase, '/api/status') or {}).get('holding'))
    for _ in range(3):
        get(_xbase, '/api/status')
    time.sleep(0.3)
    eq('an order past its own clock at boot leaves one drop row by expiry, each',
       sorted((r[0], r[1]) for r in _xdrops()), [('x-1', 'expiry'), ('x-2', 'expiry')])
    eq('...dated at the moment its clock ran out, not at the boot that noticed',
       sorted((r[0], r[2], r[3]) for r in _xdrops()),
       [('x-1', _xend1, _xend1), ('x-2', _xend2, _xend2)])
    eq('...carrying when its card was on the screen, as every drop row does',
       sorted((r[0], r[4]) for r in _xdrops()), [('x-1', _xa), ('x-2', _xa + 60000)])
finally:
    stop(_xproc)
# ...and a second restart finds nothing to write: the file it boots from no
# longer names them.
_xproc, _xbase = start({'SCANNER': '0'}, _xjournal)
try:
    get(_xbase, '/api/status')
    time.sleep(0.3)
    eq('...exactly once: a second restart writes no second row',
       sorted(r[0] for r in _xdrops()), ['x-1', 'x-2'])
finally:
    stop(_xproc)

# And on a server that is up when the clock runs out: an order carried at boot,
# with a grace of nothing and minutes of a few seconds (0.0625 min, so the
# half again is 5,625 ms exactly in both languages), asked about after its end
# and then asked about again — the beat asks on every fix.
_xb = int(time.time() * 1000) - 1000
with open(_xhold, 'w') as _fh:
    json.dump({'v': 2, 'orders': [
        {'id': 'x-3', 'pay': 9.0, 'minutes': 0.0625, 'acceptedAt': _xb}]}, _fh)
_xend3 = _xb + 5625
_xproc, _xbase = start({'SCANNER': '0', 'HOLD_GRACE_MS': '0'}, _xjournal)
try:
    ok_('(the premise: the order is carried before its clock runs out)',
        int(time.time() * 1000) < _xend3
        and (get(_xbase, '/api/status') or {}).get('holding'))
    time.sleep(max(0, (_xend3 - time.time() * 1000) / 1000.0) + 0.5)
    for _ in range(4):
        get(_xbase, '/api/status')
    time.sleep(0.3)
    eq('an order that runs out while the server is up leaves one row by expiry',
       [(r[0], r[1]) for r in _xdrops() if r[0] == 'x-3'], [('x-3', 'expiry')])
    eq('...dated at its end, not at the request that noticed',
       [r[2] for r in _xdrops() if r[0] == 'x-3'], [_xend3])
    eq('[pin log] ...and says how its end was pinned, as every drop row does',
       [(r.get('end'), r.get('pickups')) for r in
        (json.loads(l) for l in open(_xjournal) if l.strip())
        if r.get('kind') == 'drop' and r.get('id') == 'x-3'],
       [({'by': None, 'why': 'no dropoff', 'asked': None}, {'pinned': 0, 'why': None})])
finally:
    stop(_xproc)
shutil.rmtree(_xdir, ignore_errors=True)

# --- Stage 4: the order in the car is a list ---------------------------------
#
# holding.json is `{v: 2, orders: [Hold]}` now, capped at one order (MAX_HELD
# in server.js), and every build before it wrote the one-slot object. Both
# directions have to be safe: a v1 file left by the build before is ONE order,
# its clock untouched — a different acceptedAt is a different expiry and a
# different name for the pin to be posted under — and a v2 file read by the
# build before holds nothing rather than something half-read. Invented order
# and street.
_v1at = int(time.time() * 1000) - 5 * 60000
with open(_hold, 'w') as _fh:
    json.dump({'id': 'h-v1', 'pay': 9.48, 'minutes': 40, 'acceptedAt': _v1at,
               'dropoff': '12 Kestrel Dr, Marietta'}, _fh)
if os.path.exists(_hheld):
    os.remove(_hheld)
_v4proc, _v4base = start({'SCANNER': '0', 'UBERSCAN_HANDOFF_DIR': _hhand}, _hjournal)
try:
    _v4held = (get(_v4base, '/api/status') or {}).get('holding') or {}
    _v4note = json.load(open(_hheld)) if os.path.exists(_hheld) else {}
    # A pin on it rewrites the file, which is then the list's shape.
    post(_v4base, '/api/held-pickup', {'holdId': 'h-v1@%d' % _v1at,
                                       'lat': 33.95, 'lon': -84.55})
    _v4file = json.load(open(_hold))
    eq('a v1 holding.json restores as one order, clock unchanged',
       (_v4held.get('holdId'), _v4held.get('pay'), _v4note.get('until'),
        _v4note.get('holds'), _v4file.get('v'), len(_v4file.get('orders') or []),
        ((_v4file.get('orders') or [{}])[0]).get('acceptedAt')),
       ('h-v1@%d' % _v1at, 9.48, _v1at + 40 * 1.5 * 60000 + 10 * 60000,
        ['h-v1@%d' % _v1at], 2, 1, _v1at))
finally:
    stop(_v4proc)

# ...and the build before the list, given the file this one now writes. Run as
# that build, out of git, not as a copy of its rule written here: the rule is
# `typeof h.acceptedAt === 'number'` on the file's top level, and the v2 file
# has none, which only the real loader can be trusted to show. The premise
# first — the same old build DOES restore a v1 file — so a refusal below is
# about the shape and not a server that restores nothing.
_OLD = '000c052'
_oldtree = tempfile.mkdtemp()
_oldok = subprocess.run('git -C "%s" archive %s | tar -x -C "%s"' % (ROOT, _OLD, _oldtree),
                        shell=True, capture_output=True).returncode == 0
ok_('(the build before the list is in this checkout\'s history: %s)' % _OLD, _oldok)


def _old_restores(content):
    jdir = tempfile.mkdtemp()
    jpath = os.path.join(jdir, 'offers.jsonl')
    open(jpath, 'w').close()
    with open(os.path.join(jdir, 'holding.json'), 'w') as fh:
        json.dump(content, fh)
    hand = os.path.join(jdir, 'handoff')
    os.mkdir(hand)
    port = free_port()
    proc = subprocess.Popen(
        ['node', os.path.join(_oldtree, 'server.js')],
        env=dict(os.environ, PORT=str(port), HTTPS_PORT='0', JOURNAL=jpath,
                 SCANNER='0', UBERSCAN_HANDOFF_DIR=hand),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = 'http://127.0.0.1:%d' % port
    try:
        for _ in range(120):
            try:
                return (get(base, '/api/status') or {}).get('holding')
            except Exception:
                time.sleep(0.1)
        return 'never came up'
    finally:
        stop(proc)
        shutil.rmtree(jdir, ignore_errors=True)


if _oldok:
    _v1again = {'id': 'h-v1', 'pay': 9.48, 'minutes': 40,
                'acceptedAt': int(time.time() * 1000) - 60000}
    ok_('(the build before the list restores a v1 file)',
        (_old_restores(_v1again) or {}).get('pay') == 9.48)
    eq('...a v2 file read by the old loader holds nothing',
       _old_restores(_v4file), None)
shutil.rmtree(_oldtree, ignore_errors=True)
shutil.rmtree(_hdir, ignore_errors=True)

# --- Drop leaves a row saying when ------------------------------------------
#
# The one quantity the ledger says the rig lacks is how long a taken job really
# took, and the driver already presses Drop when it is done. `/api/delivered`
# put the order down and wrote nothing, so every press was thrown away. It now
# appends a `kind: 'drop'` row — collection only; nothing reads it.
#
# No scanner: the mark carries the offer, which is the restarted-server path in
# the mark handler, so the hold is the real one and nothing here is staged.
# `lines` is rebound to a list by the ⌖ block above, so this reads its own.
def _drows(path):
    return [json.loads(l) for l in open(path) if l.strip()]


_ddir = tempfile.mkdtemp()
_djournal = os.path.join(_ddir, 'offers.jsonl')
open(_djournal, 'w').close()
_dproc, _dbase = start({'SCANNER': '0'}, _djournal)
try:
    _doffer = {'id': 'drop-1', 'pay': 14.0, 'minutes': 25.0,
               'billedMinutes': 25.0, 'miles': 6.0, 'cost': 1.8}
    _dcode, _dsaid = post(_dbase, '/api/offers/mark',
                          {'id': 'drop-1', 'accepted': True, 'offer': _doffer})
    ok_('a marked offer goes in the car', _dsaid.get('holding') is True)
    with open(os.path.join(_ddir, 'holding.json')) as _fh:
        _dheld = json.load(_fh)['orders'][0]
    _dbefore = int(time.time() * 1000)
    _dcode, _dsaid = post(_dbase, '/api/delivered', {})
    _dafter = int(time.time() * 1000)
    eq('Drop answers as it always did', (_dcode, _dsaid.get('wasHolding')),
       (200, True))
    _drops = [r for r in _drows(_djournal) if r.get('kind') == 'drop']
    eq('Drop writes a drop row naming the order it put down',
       [r.get('id') for r in _drops], ['drop-1'])
    if _drops:
        _d = _drops[0]
        ok_('...stamped with the moment of the press',
            _dbefore <= _d.get('at', 0) <= _dafter)
        # The press time as seq, so a second drop of the same offer is a second
        # key to the sync; test_sync.py sends two through the real ingest.
        eq('...whose seq is the press time, not a constant', _d.get('seq'),
           _d.get('at'))
        eq('...carrying when the card was on the screen, off the hold itself',
           _d.get('acceptedAt'), _dheld.get('acceptedAt'))
    # The mark is a fact about the offer and Drop does not make it untrue.
    eq('...and the tick it was taken on is untouched',
       [r.get('accepted') for r in _drows(_djournal) if r.get('kind') == 'mark'],
       [True])
    _dcount = len(_drows(_djournal))
    _dcode, _dsaid = post(_dbase, '/api/delivered', {})
    eq('Drop with nothing in the car still answers',
       (_dcode, _dsaid.get('wasHolding')), (200, False))
    eq('...and writes nothing, having no offer to name',
       len(_drows(_djournal)), _dcount)
finally:
    stop(_dproc)
    shutil.rmtree(_ddir, ignore_errors=True)

# --- /api/settings: one key, and it says which machine it wrote -------------
#
# The cost per mile is the one setting the driver can now change from a screen.
# The block it lives in also holds `keepPlaces` (whether addresses reach the
# append-only journal at all) and `pad`/`secondsPerItem` (the minutes every
# stored rate is divided by), and the copy at home runs this same server with
# no scanner. Each of those is a way for a POST to answer ok and be wrong.
_sdir = tempfile.mkdtemp()
_sho = os.path.join(_sdir, 'handoff')
os.mkdir(_sho)
_sfake = os.path.join(_sdir, 'fake.py')
with open(_sfake, 'w') as _fh:
    _fh.write('import json, time\n'
              'print(json.dumps({"settings": {"costPerMile": 0.3}}), flush=True)\n'
              'time.sleep(600)\n')
_sjournal = os.path.join(_sdir, 'offers.jsonl')
open(_sjournal, 'w').close()
_sreq = os.path.join(_sho, 'uberscan-settings.json')


def _sleft():
    return sorted(os.listdir(_sho))


_sproc, _sbase = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable,
                        'SCANNER_ARGS': _sfake, 'UBERSCAN_HANDOFF_DIR': _sho},
                       _sjournal)
try:
    _said = None
    for _ in range(100):
        _said = get(_sbase, '/api/settings')
        if _said.get('costPerMile') is not None:
            break
        time.sleep(0.05)
    eq('a rig answers with the cost its scanner says it is pricing with',
       (_said.get('scanner'), _said.get('costPerMile'), _said.get('pending')),
       (True, 0.3, None))
    for _bad in ('0.45', -0.1, True, None, 10.01, 1e308):
        _code, _body = post(_sbase, '/api/settings', {'costPerMile': _bad})
        eq('a cost of %r is refused' % (_bad,), _code, 400)
    _code, _body = post(_sbase, '/api/settings', {})
    eq('...and so is no cost at all', _code, 400)
    _code, _body = post(_sbase, '/api/settings', [0.45])
    eq('...and a body that is not an object', _code, 400)
    eq('...and none of those left anything for the scanner to take', _sleft(), [])
    for _key, _val in (('quad', [[0, 0], [1, 0], [1, 1], [0, 1]]),
                       ('cropBox', [0, 0, 1, 1]),
                       ('trackedQuad', [[0, 0], [1, 0], [1, 1], [0, 1]]),
                       ('keepPlaces', False), ('pad', 9), ('secondsPerItem', 60)):
        _code, _body = post(_sbase, '/api/settings',
                            {'costPerMile': 0.45, _key: _val})
        ok_('a body that also names %s is refused whole, naming it (%r)'
            % (_key, _body.get('error')),
            _code == 400 and _key in (_body.get('error') or ''))
    eq('...and not one of them wrote anything', _sleft(), [])
    _code, _body = post(_sbase, '/api/settings', {'costPerMile': 0.45})
    eq('a cost on its own is taken', (_code, _body.get('ok'), _body.get('scanner')),
       (200, True, True))
    eq('...answering with what is in use and what is on its way',
       (_body.get('costPerMile'), _body.get('pending')), (0.3, 0.45))
    eq('...leaving the scanner that key and no other, and no temporary behind',
       (_sleft(), json.load(open(_sreq)) if os.path.exists(_sreq) else None),
       (['uberscan-settings.json'], {'costPerMile': 0.45}))
    eq('...and a panel opened now is told it is on its way',
       get(_sbase, '/api/settings').get('pending'), 0.45)
finally:
    stop(_sproc)

# The copy at home: SCANNER=0, the same server. A POST there used to be a file
# no scanner would ever read, answered ok.
_hho = os.path.join(_sdir, 'home-handoff')
os.mkdir(_hho)
_sproc, _sbase = start({'SCANNER': '0', 'UBERSCAN_HANDOFF_DIR': _hho}, _sjournal)
try:
    eq('a machine with no scanner says so, and quotes no figure',
       (lambda s: (s.get('scanner'), s.get('costPerMile')))(get(_sbase, '/api/settings')),
       (False, None))
    _code, _body = post(_sbase, '/api/settings', {'costPerMile': 0.45})
    eq('...and refuses the write rather than answering ok',
       (_code, _body.get('ok'), _body.get('scanner')), (409, False, False))
    eq('...leaving nothing behind', os.listdir(_hho), [])
finally:
    stop(_sproc)
    shutil.rmtree(_sdir, ignore_errors=True)

# --- 📷 Snap: what the rig keeps, and what it says it could not ---------------
#
# One press keeps a screenshot of the Pi's display, the camera's last picture
# and what /api/status said, in a folder beside the journal. Every way a part
# can be missing has to come back as a reason, because a folder with no
# panel.png and nothing saying why is the second fault class in the shape of a
# directory — and the NucBox, with no desktop and no camera, has to answer that
# honestly too rather than pretend.
#
# The desktop is faked the way the server finds a real one: a Wayland socket in
# an XDG_RUNTIME_DIR, and a `grim` on PATH. Each fake tool is a script that
# writes a real PNG to the path it is handed, or fails in one particular way.
# The server is started with nothing of this machine's own desktop in its
# environment, and PATH holding only the fakes — `node` is run by its full
# path — so a grim installed here cannot stand in for a missing one.
import http.client                                            # noqa: E402
import re                                                     # noqa: E402
import socket as _socket                                      # noqa: E402
import struct                                                 # noqa: E402
import zlib                                                   # noqa: E402

_pdir = tempfile.mkdtemp()
_node = shutil.which('node')


def _png(w, h):
    """A real PNG, made here so no imaging library is needed to make one."""
    def chunk(kind, data):
        body = kind + data
        return struct.pack('>I', len(data)) + body + struct.pack('>I', zlib.crc32(body) & 0xffffffff)
    rows = b''.join(b'\x00' + bytes([40, 60, 80]) * w for _ in range(h))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


_PNG = _png(8, 4)
_pngfile = os.path.join(_pdir, 'shot.png')
with open(_pngfile, 'wb') as _fh:
    _fh.write(_PNG)


def _tool(where, name, body):
    """A fake screenshot tool: `body` runs with `out` the path it was handed."""
    os.makedirs(where, exist_ok=True)
    path = os.path.join(where, name)
    with open(path, 'w') as fh:
        fh.write('#!%s\nimport json, os, shutil, sys, time\nout = sys.argv[-1]\n' % sys.executable
                 + 'open(%r, "w").write(json.dumps({"argv": sys.argv[1:], "pid": os.getpid(), '
                   '"env": {k: os.environ.get(k) for k in ("WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", '
                   '"DISPLAY", "XAUTHORITY")}}))\n' % (path + '.ran')
                 + body + '\n')
    os.chmod(path, 0o755)
    return path


def _ran(tool):
    try:
        return json.load(open(tool + '.ran'))
    except (OSError, ValueError):
        return None


def _size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return None


_WRITES = 'shutil.copy(%r, out)' % _pngfile
_bins = {
    'grim': os.path.join(_pdir, 'bin-grim'),
    'none': os.path.join(_pdir, 'bin-none'),
    'both': os.path.join(_pdir, 'bin-both'),
    'scrot': os.path.join(_pdir, 'bin-scrot'),
    'import': os.path.join(_pdir, 'bin-import'),
    'fails': os.path.join(_pdir, 'bin-fails'),
    'junk': os.path.join(_pdir, 'bin-junk'),
    'hangs': os.path.join(_pdir, 'bin-hangs'),
    'stall': os.path.join(_pdir, 'bin-stall'),
    'liars': os.path.join(_pdir, 'bin-liars'),
    'slow': os.path.join(_pdir, 'bin-slow'),
    'x0': os.path.join(_pdir, 'bin-x0'),
    'nuc': os.path.join(_pdir, 'bin-nuc'),
}
_grim = _tool(_bins['grim'], 'grim', _WRITES)
_nucgrim = _tool(_bins['nuc'], 'grim', _WRITES)
os.makedirs(_bins['none'])
_tool(_bins['both'], 'grim', _WRITES)
_tool(_bins['both'], 'scrot', _WRITES)
_scrot = _tool(_bins['scrot'], 'scrot', _WRITES)
_import = _tool(_bins['import'], 'import', _WRITES)
_x0scrot = _tool(_bins['x0'], 'scrot', _WRITES)
_tool(_bins['fails'], 'grim',
      'sys.stderr.write("compositor doesn\'t support wlr-screencopy-unstable-v1\\n"); sys.exit(1)')
_tool(_bins['junk'], 'grim', 'open(out, "w").write("not a picture")')
_hangs = _tool(_bins['hangs'], 'grim', 'open(out, "wb").write(b"\\x89PNG"); time.sleep(600)')
# The same hang, for the one case that waits it out on the server's own
# deadline — a tool of its own, so its record of having run is its own too.
_tool(_bins['stall'], 'grim', 'open(out, "wb").write(b"\\x89PNG"); time.sleep(600)')
# A whole picture that takes a second, so two presses can be in flight at once.
_tool(_bins['slow'], 'grim', 'time.sleep(1.0); ' + _WRITES)

# A desktop: a real socket where a compositor puts one. A path under 108 bytes,
# which is all a unix socket's address can hold.
_wl = tempfile.mkdtemp(prefix='wl')
_wsock = _socket.socket(_socket.AF_UNIX)
_wsock.bind(os.path.join(_wl, 'wayland-1'))
# ...and the lock file every compositor leaves beside it, which is not a socket.
open(os.path.join(_wl, 'wayland-1.lock'), 'w').close()
_nodesk = tempfile.mkdtemp(prefix='nd')
_x0 = os.path.exists('/tmp/.X11-unix/X0')

# The live picture, as the scanner leaves it.
_frame = os.path.join(_pdir, 'live.jpg')
with open(_frame, 'wb') as _fh:
    _fh.write(b'\xff\xd8\xff\xe0' + os.urandom(2000) + b'\xff\xd9')
_frame_bytes = open(_frame, 'rb').read()


def _snapper(case, env, cwd=None):
    """A server for one case: its own journal, so its own snaps folder."""
    home = os.path.join(_pdir, case)
    os.makedirs(home, exist_ok=True)
    jpath = os.path.join(home, 'journal.jsonl')
    if not os.path.exists(jpath):
        open(jpath, 'w').close()
    log = os.path.join(home, 'server.log')
    # Nothing of this machine's own desktop, and none of the snap settings, so
    # a default is what is measured wherever a case does not set one. HOME is
    # the case's own folder, which holds no X cookie unless the case puts one.
    full = {k: v for k, v in os.environ.items()
            if k not in ('DISPLAY', 'WAYLAND_DISPLAY', 'XDG_RUNTIME_DIR', 'XAUTHORITY',
                         'PATH', 'HOME', 'SNAPS_KEEP', 'SNAP_TOOL_MS')}
    port = free_port()
    full.update(PORT=str(port), HTTPS_PORT='0', JOURNAL=jpath, SCANNER='0',
                PATH=_bins['none'], XDG_RUNTIME_DIR=_nodesk, FRAME=_frame, HOME=home)
    full.update(env)
    # The scanner's picture as of now, so a case that does not ask for an old
    # one is not handed one by however long the cases before it took.
    os.utime(_frame, None)
    # None takes a name out altogether, the way systemd starts the service.
    full = {k: v for k, v in full.items() if v is not None}
    proc = subprocess.Popen([_node, os.path.join(ROOT, 'server.js')], env=full, cwd=cwd,
                            stdout=open(log, 'w'), stderr=subprocess.STDOUT)
    url = 'http://127.0.0.1:%d' % port
    for _ in range(120):
        try:
            urllib.request.urlopen(url + '/api/status', timeout=1).read()
            break
        except Exception:
            time.sleep(0.1)
    return proc, url, os.path.join(home, 'snaps'), log


def _snap(url, timeout=20):
    req = urllib.request.Request(url + '/api/snap', data=b'', method='POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode('utf-8') or '{}')
    except Exception as e:
        # No answer at all — a hung tool with nothing bounding it. A result,
        # so the check that names it fails, rather than the suite.
        return None, {'error': repr(e)}


def _piece(reply, what):
    return ([p for p in (reply.get('contents') or []) if p.get('what') == what] or [{}])[0]


def _fetch(url, path):
    """Status and body, with the path sent exactly as written — urllib would
    tidy a `..` away before the server ever saw it."""
    u = urllib.parse.urlparse(url)
    c = http.client.HTTPConnection(u.hostname, u.port, timeout=5)
    c.request('GET', path)
    r = c.getresponse()
    body = r.read()
    c.close()
    return r.status, body, r.getheader('Content-Type')


import urllib.parse                                           # noqa: E402


def _listed(url, name):
    """One snap as GET /api/snaps describes it, or {}."""
    return ([s for s in get(url, '/api/snaps')['snaps'] if s.get('name') == name] or [{}])[0]


def _jrows(path):
    """A journal's rows, read here; `lines` above is rebound by the time this runs."""
    with open(path) as fh:
        return [json.loads(l) for l in fh if l.strip()]


def _snaprow(snaps):
    """The last snap row in the journal beside a snaps folder, or {}."""
    return ([r for r in _jrows(os.path.join(os.path.dirname(snaps), 'journal.jsonl'))
             if r.get('kind') == 'snap'] or [{}])[-1]


def _shelve(snaps, name, record=None, torn=False):
    """A snap folder put on the shelf by hand: a status, and a record if any."""
    os.makedirs(os.path.join(snaps, name), exist_ok=True)
    with open(os.path.join(snaps, name, 'status.json'), 'w') as fh:
        fh.write('{}\n')
    if record is not None:
        text = json.dumps(record)
        with open(os.path.join(snaps, name, 'snap.json'), 'w') as fh:
            fh.write(text[:len(text) // 2] if torn else text)


# --- a tool that hangs, against the deadline nobody set -----------------------
#
# Every other hang below shortens the server's deadline so it need not be
# waited out. This one does not, because the default is the figure that has to
# sit inside the deadline the pages themselves put on a press — live.html's
# POST_TIMEOUT_MS and snaps.html's ASK_MS, read out of the pages here — or the
# control says "no answer from the rig" over a snap the rig went on to keep.
# Pressed now and collected at the end, so the wait costs the suite nothing.
_live_src = open(os.path.join(ROOT, 'live.html'), encoding='utf-8').read()
_snaps_src = open(os.path.join(ROOT, 'snaps.html'), encoding='utf-8').read()
_page_ms = min(int(re.search(r'var POST_TIMEOUT_MS = (\d+);', _live_src).group(1)),
               int(re.search(r'var ASK_MS = (\d+);', _snaps_src).group(1)))
_dp, _du, _dsnaps, _dlog = _snapper('deadline', {'XDG_RUNTIME_DIR': _wl, 'PATH': _bins['stall']})
_deadline = {}


def _press_on_the_default():
    t0 = time.time()
    _deadline['reply'] = _snap(_du, timeout=_page_ms / 1000.0)
    _deadline['took'] = time.time() - t0


_dthread = threading.Thread(target=_press_on_the_default)
_dthread.start()

# --- the whole thing, on a desktop with grim ---------------------------------
#
# In a folder with a space in its name, which is what makes "an argument of its
# own, not a shell line" a claim with teeth: a command line pasted together and
# handed to a shell splits there, and the tool is given two arguments, neither
# of them the path.
_p, _u, _snaps, _log = _snapper('whole rig', {'XDG_RUNTIME_DIR': _wl, 'PATH': _bins['grim']})
try:
    _before = time.time()
    _code, _rep = _snap(_u)
    _after = time.time()
    eq('a snap is answered ok', (_code, _rep.get('ok')), (200, True))
    _name = _rep.get('name') or ''
    # The folder is the local time of the press, which this suite reads in the
    # driver's zone (TZ=America/New_York) like every other suite that reads a
    # clock.
    _stamps = {time.strftime('%Y-%m-%d_%H-%M-%S', time.localtime(t))
               for t in (int(_before), int(_before) + 1, int(_after))}
    ok_('the folder is named for the local time of the press (%r)' % _name,
        _name in _stamps)
    _dir = os.path.join(_snaps, _name)
    ok_('...and is made beside the journal, in snaps/', os.path.isdir(_dir))
    _panel = _piece(_rep, 'panel')
    eq('the screenshot is taken by grim, found on PATH, under a Wayland desktop',
       (_panel.get('saved'), _panel.get('tool'), _panel.get('session')),
       (True, 'grim', 'wayland'))
    _got = open(os.path.join(_dir, 'panel.png'), 'rb').read() if os.path.exists(
        os.path.join(_dir, 'panel.png')) else b''
    eq('...and panel.png is the PNG the tool wrote, byte for byte', _got, _PNG)
    eq('...with its size in the reply', _panel.get('bytes'), len(_PNG))
    # Found the way a systemd service has to find it: nothing in this server's
    # own environment named the session, only the runtime directory did.
    _r = _ran(_grim) or {}
    eq('...run with the desktop session the server found, not its own',
       ((_r.get('env') or {}).get('WAYLAND_DISPLAY'),
        (_r.get('env') or {}).get('XDG_RUNTIME_DIR')),
       ('wayland-1', _wl))
    eq('...handed the output path as an argument of its own, not a shell line',
       _r.get('argv'), [os.path.join(_dir, 'panel.png')])
    _cam = _piece(_rep, 'camera')
    _cgot = open(os.path.join(_dir, 'camera.jpg'), 'rb').read() if os.path.exists(
        os.path.join(_dir, 'camera.jpg')) else b''
    eq('the camera\'s last picture is kept, byte for byte', _cgot, _frame_bytes)
    ok_('...with its age, and called current (%r ms)' % _cam.get('ageMs'),
        isinstance(_cam.get('ageMs'), (int, float)) and _cam.get('ageMs') < 12000
        and _cam.get('stale') is False)
    def _json_in(folder, name):
        try:
            return json.load(open(os.path.join(folder, name)))
        except (OSError, ValueError):
            return None
    _status = _json_in(_dir, 'status.json')
    eq('status.json is what /api/status answers', _status, get(_u, '/api/status'))
    eq('the reply says all three were kept and nothing is missing',
       ([p.get('what') for p in _rep.get('contents') or [] if p.get('saved')], _rep.get('said')),
       (['panel', 'camera', 'status'], 'saved'))
    _record = _json_in(_dir, 'snap.json') or {}
    eq('...and snap.json in the folder says the same',
       (_record.get('said'), _record.get('contents')), (_rep.get('said'), _rep.get('contents')))
    # No scanner runs on this server — the copy at home's shape — so there is
    # nothing to ask what it read. Recorded as not applying, with the reason,
    # and not as two parts that failed: the line above is plain "saved".
    eq('on a machine with no scanner the reader\'s two files do not apply, and say why',
       [(_piece(_rep, w).get('file'), _piece(_rep, w).get('saved'),
         _piece(_rep, w).get('applies'), _piece(_rep, w).get('why')) for w in ('crop', 'reader')],
       [('reader.jpg', False, False, 'no scanner runs on this machine'),
        ('reader.json', False, False, 'no scanner runs on this machine')])
    # ...and the press is in the journal, so it can be found from the shift.
    _snaprows = [r for r in _jrows(os.path.join(os.path.dirname(_snaps), 'journal.jsonl'))
                 if r.get('kind') == 'snap']
    eq('a press leaves one snap row in the journal, naming its folder and what it kept',
       [(r.get('v'), r.get('id'), r.get('seq'), r.get('folder'), r.get('parts'))
        for r in _snaprows],
       [(1, 'snap-%s' % (_snaprows[0].get('at') if _snaprows else '?'), 1, _name,
         ['panel.png', 'camera.jpg', 'status.json', 'snap.json'])])
    # Stamped as it is written: after the press, and before the reply that
    # waited for it.
    ok_('...stamped when it was written, between the press and the reply (%r, pressed %r)'
        % ([r.get('at') for r in _snaprows], _rep.get('at')),
        len(_snaprows) == 1 and isinstance(_snaprows[0].get('at'), int)
        and _rep.get('at', 0) <= _snaprows[0]['at'] <= _after * 1000)
    eq('...with nothing missing, and the reader\'s files as not applying here, with why',
       [(r.get('missing'), r.get('notApplicable')) for r in _snaprows],
       [({}, {'reader.jpg': 'no scanner runs on this machine',
              'reader.json': 'no scanner runs on this machine'})])
    # Listed and served.
    _list = get(_u, '/api/snaps')
    eq('the list names it, with the files it holds and their sizes',
       [(s['name'], sorted((f['file'], f['bytes']) for f in s['files'])) for s in _list['snaps']],
       [(_name, sorted([('panel.png', len(_PNG)), ('camera.jpg', len(_frame_bytes)),
                        ('status.json', _size(os.path.join(_dir, 'status.json'))),
                        ('snap.json', _size(os.path.join(_dir, 'snap.json')))]))])
    eq('...and says where they are on the rig', _list.get('where'), _snaps)
    # The default, with nothing set: what snaps.html tells the driver it keeps.
    eq('...and keeps the newest 100 unless told otherwise', _list.get('keep'), 100)
    _age = (_list['snaps'] or [{}])[0].get('ageMs')
    _since = (time.time() - _before) * 1000
    ok_('...and how long ago it was taken, by the rig\'s clock (%r ms, %d since the press)'
        % (_age, _since), isinstance(_age, (int, float)) and 0 <= _age <= _since)
    # Two folders a press did not finish: a record torn part way, and none.
    _shelve(_snaps, '2026-01-03_00-00-00', {'v': 1, 'at': time.time() * 1000, 'said': 'saved',
                                            'contents': [], 'notes': []}, torn=True)
    _shelve(_snaps, '2026-01-04_00-00-00')
    eq('a snap whose snap.json is torn says it cannot be read, not that there is none',
       _listed(_u, '2026-01-03_00-00-00').get('said'),
       'snap.json in this folder cannot be read, so nothing says what is missing')
    eq('...and one with no snap.json says there is none',
       _listed(_u, '2026-01-04_00-00-00').get('said'),
       'no snap.json in this folder, so nothing says what is missing')
    # A snap the rig made in the minute after a boot, before the network set
    # its clock, listed now the clock is set: its stamp is 1970.
    _shelve(_snaps, '1970-01-03_00-00-00', {'v': 1, 'at': 2 * 86400000, 'said': 'saved',
                                            'contents': [], 'notes': []})
    eq('a snap made on a clock nobody had set lists its age as unknown once the clock is set',
       'ageMs=%r' % _listed(_u, '1970-01-03_00-00-00').get('ageMs', '?'), 'ageMs=None')
    _st, _body, _type = _fetch(_u, '/api/snaps/%s/panel.png' % _name)
    eq('panel.png is served from the list, as a PNG', (_st, _body, _type), (200, _PNG, 'image/png'))
    _st, _body, _type = _fetch(_u, '/api/snaps/%s/camera.jpg' % _name)
    eq('...and so is camera.jpg', (_st, _body == _frame_bytes), (200, True))

    # --- nothing outside the snaps folder comes out through it ---------------
    #
    # The journal sits one directory above snaps/, and this server's own source
    # one above that: the two things a traversal would be after.
    _journal_text = b'{"v": 1, "id": "secret-offer"}\n'
    with open(os.path.join(os.path.dirname(_snaps), 'journal.jsonl'), 'wb') as _fh:
        _fh.write(_journal_text)
    with open(os.path.join(_dir, 'notes.txt'), 'w') as _fh:
        _fh.write('not one of the four')
    _tries = [
        '/api/snaps/../journal.jsonl',
        '/api/snaps/%s/../../journal.jsonl' % _name,
        '/api/snaps/%s/..%%2F..%%2Fjournal.jsonl' % _name,
        '/api/snaps/%2e%2e/journal.jsonl',
        '/api/snaps/%s/%%2e%%2e%%2fstatus.json' % _name,
        '/api/snaps//etc/passwd',
        '/api/snaps/%2Fetc%2Fpasswd/panel.png',
        '/api/snaps/%s/%%2Fetc%%2Fpasswd' % _name,
        '/api/snaps/%s/notes.txt' % _name,
        '/api/snaps/%s/' % _name,
        '/api/snaps/not-a-snap/panel.png',
    ]
    for _path in _tries:
        _st, _body, _type = _fetch(_u, _path)
        ok_('%s is refused (%d)' % (_path, _st),
            _st in (403, 404) and b'secret-offer' not in _body and b'root:' not in _body)
    # A real folder inside snaps/ that this server did not make — copied there
    # by hand, or left by something else — holding a real picture. Inside the
    # folder, so no path check refuses it; only the rule that a folder is one
    # of the names a press makes does.
    os.mkdir(os.path.join(_snaps, 'by-hand'))
    shutil.copy(_pngfile, os.path.join(_snaps, 'by-hand', 'panel.png'))
    _st, _body, _type = _fetch(_u, '/api/snaps/by-hand/panel.png')
    eq('a folder in snaps/ not named the way a press names one is not served from',
       _st, 404)
    # A name that is right and a link that is not: panel.png in a snap folder
    # replaced by a link to the journal. Not a snap file, so not served.
    _evil = os.path.join(_snaps, '2026-01-01_00-00-00')
    os.mkdir(_evil)
    os.symlink(os.path.join(os.path.dirname(_snaps), 'journal.jsonl'),
               os.path.join(_evil, 'panel.png'))
    _st, _body, _type = _fetch(_u, '/api/snaps/2026-01-01_00-00-00/panel.png')
    eq('a panel.png that is a link out of the snaps folder is refused',
       (_st, b'secret-offer' in _body), (404, False))
    # ...and a whole folder that is a link out of it is neither listed nor served.
    _out = os.path.join(_pdir, 'outside')
    os.makedirs(_out)
    with open(os.path.join(_out, 'status.json'), 'w') as _fh:
        _fh.write('{"secret-offer": true}')
    os.symlink(_out, os.path.join(_snaps, '2026-01-02_00-00-00'))
    _st, _body, _type = _fetch(_u, '/api/snaps/2026-01-02_00-00-00/status.json')
    eq('a snap folder that is a link out of the snaps folder is refused',
       (_st, b'secret-offer' in _body), (404, False))
    no_('...and is not listed as a snap',
        '2026-01-02_00-00-00' in [s['name'] for s in get(_u, '/api/snaps')['snaps']])
    # Links that stay INSIDE snaps/, which a realpath check lets through and
    # the list never shows: one named like a snap, pointing at the folder made
    # by hand, and a panel.png in a real snap pointing at that folder's
    # picture. What is served and what is listed are one answer.
    os.symlink(os.path.join(_snaps, 'by-hand'), os.path.join(_snaps, '2026-01-05_00-00-00'))
    _st, _body, _type = _fetch(_u, '/api/snaps/2026-01-05_00-00-00/panel.png')
    eq('a link named like a snap, to a folder in snaps/ that is not one, is not served from',
       _st, 404)
    no_('...as it is not listed',
        '2026-01-05_00-00-00' in [s['name'] for s in get(_u, '/api/snaps')['snaps']])
    os.symlink(os.path.join(_snaps, 'by-hand', 'panel.png'),
               os.path.join(_snaps, '2026-01-04_00-00-00', 'panel.png'))
    _st, _body, _type = _fetch(_u, '/api/snaps/2026-01-04_00-00-00/panel.png')
    eq('a panel.png that is a link to a picture elsewhere in snaps/ is not served',
       _st, 404)
    eq('...as it is not listed among that snap\'s files',
       [f['file'] for f in _listed(_u, '2026-01-04_00-00-00').get('files') or []],
       ['status.json'])
finally:
    stop(_p)

# --- no screenshot tool, and the reason --------------------------------------
_p, _u, _snaps, _log = _snapper('notool', {'XDG_RUNTIME_DIR': _wl, 'PATH': _bins['none']})
try:
    _code, _rep = _snap(_u)
    _panel = _piece(_rep, 'panel')
    eq('a desktop with no grim on PATH still keeps a snap', (_code, _rep.get('ok')), (200, True))
    eq('...saying the screenshot is missing because grim is not installed',
       (_panel.get('saved'), _panel.get('why'), _panel.get('fix')),
       (False, 'grim is not installed', 'sudo apt install grim'))
    eq('...in the one line the panel shows',
       _rep.get('said'), 'saved — no screenshot: grim is not installed')
    no_('...with no panel.png in the folder',
        os.path.exists(os.path.join(_snaps, _rep.get('name') or '?', 'panel.png')))
    _first = get(_u, '/api/snaps')['snaps'][0]
    eq('...and the list carries the reason with it',
       [(p.get('what'), p.get('why')) for p in _first.get('problems') or []],
       [('panel', 'grim is not installed')])
finally:
    stop(_p)

# --- no scanner on this machine: the camera does not apply, like the reader ---
#
# One reason, "no scanner runs on this machine", for the camera picture and the
# reader's two files alike, and it was filed two ways: the camera as missing,
# in the journal row, the panel's line and the problems snaps.html lists, and
# the reader's two as not applying. A desktop and grim here, so the screenshot
# is kept and nothing else has a reason to be said — and not gated on an X
# server like the case below, because none of this is about the display.
_p, _u, _snaps, _log = _snapper('home', {'XDG_RUNTIME_DIR': _wl, 'PATH': _bins['grim'],
                                         'FRAME': os.path.join(_pdir, 'no-frame.jpg')})
try:
    _code, _rep = _snap(_u)
    eq('on a machine with no scanner the camera picture does not apply, for the reader\'s reason',
       [(_piece(_rep, w).get('saved'), _piece(_rep, w).get('applies'), _piece(_rep, w).get('why'))
        for w in ('camera', 'crop', 'reader')],
       [(False, False, 'no scanner runs on this machine')] * 3)
    eq('...so the line the panel shows is plain "saved"', _rep.get('said'), 'saved')
    eq('...and the journal row files all three as not applying, none as missing',
       (_snaprow(_snaps).get('parts'), _snaprow(_snaps).get('missing'),
        _snaprow(_snaps).get('notApplicable')),
       (['panel.png', 'status.json', 'snap.json'], {},
        dict.fromkeys(['camera.jpg', 'reader.jpg', 'reader.json'],
                      'no scanner runs on this machine')))
    eq('...and snaps.html lists no problem with it',
       _listed(_u, _rep.get('name')).get('problems'), [])
finally:
    stop(_p)

# --- no desktop at all: the NucBox, which has no scanner either ---------------
if _x0:
    print('  (this machine has an X server at /tmp/.X11-unix/X0, so "no display '
          'session" cannot be staged here — skipping those checks)')
else:
    _p, _u, _snaps, _log = _snapper('nucbox', {'PATH': _bins['nuc'],
                                               'FRAME': os.path.join(_pdir, 'no-frame.jpg')})
    try:
        _code, _rep = _snap(_u)
        eq('a machine with no desktop and no scanner still answers ok, keeping the status',
           (_code, _rep.get('ok'), [p.get('what') for p in _rep.get('contents') or []
                                    if p.get('saved')]),
           (200, True, ['status']))
        _panel = _piece(_rep, 'panel')
        eq('...saying there is no display session rather than blaming a tool',
           (_panel.get('why'), _panel.get('tool')), ('no display session found', None))
        ok_('...and where it looked (%r)' % _panel.get('detail'),
            _nodesk in (_panel.get('detail') or ''))
        eq('...and that the camera picture does not apply, no scanner running here to take one',
           (_piece(_rep, 'camera').get('applies'), _piece(_rep, 'camera').get('why')),
           (False, 'no scanner runs on this machine'))
        eq('...the screenshot\'s reason alone in the line the panel shows', _rep.get('said'),
           'saved — no screenshot: no display session found')
        eq('...and grim, though installed, was never run, there being nothing to photograph',
           _ran(_nucgrim), None)
    finally:
        stop(_p)

    # ...and started the way systemd starts the service, with no runtime
    # directory named at all: the server has to look where this uid's desktop
    # session would be. Here there is none, so what is checked is where it
    # looked — the place a Pi's desktop puts its socket.
    _run = '/run/user/%d' % os.getuid()
    _occupied = os.path.isdir(_run) and any(
        n.startswith('wayland-') for n in os.listdir(_run))
    if _occupied:
        print('  (%s has a Wayland session on this machine, so the service\'s own '
              'search cannot be staged as finding nothing — skipping that check)' % _run)
    else:
        _p, _u, _snaps, _log = _snapper('service', {'PATH': _bins['nuc'],
                                                    'XDG_RUNTIME_DIR': None})
        try:
            _code, _rep = _snap(_u)
            ok_('a server with no XDG_RUNTIME_DIR looks for the desktop in %s (%r)'
                % (_run, _piece(_rep, 'panel').get('detail')),
                'no wayland-* socket in ' + _run in (_piece(_rep, 'panel').get('detail') or ''))
        finally:
            stop(_p)

# --- X11, and Wayland chosen over it ------------------------------------------
#
# An X server refuses a client that cannot show it the cookie, and the service
# is handed no XAUTHORITY by systemd. The desktop account's is in its home,
# which for these servers is the case's own folder: one with a cookie in it,
# and one with none.
def _cookie(case):
    home = os.path.join(_pdir, case)
    os.makedirs(home, exist_ok=True)
    with open(os.path.join(home, '.Xauthority'), 'wb') as fh:
        fh.write(b'\x01\x00cookie')
    return os.path.join(home, '.Xauthority')


_xauth = _cookie('x11')
_p, _u, _snaps, _log = _snapper('x11', {'DISPLAY': ':99', 'PATH': _bins['scrot']})
try:
    _code, _rep = _snap(_u)
    _panel = _piece(_rep, 'panel')
    eq('an X desktop is photographed with scrot',
       (_panel.get('saved'), _panel.get('tool'), _panel.get('session')), (True, 'scrot', 'x11'))
    eq('...on the display it was given', ((_ran(_scrot) or {}).get('env') or {}).get('DISPLAY'),
       ':99')
    eq('...with the desktop account\'s X cookie, which the service is given none of',
       ((_ran(_scrot) or {}).get('env') or {}).get('XAUTHORITY'), _xauth)
finally:
    stop(_p)
_cookie('import')
_p, _u, _snaps, _log = _snapper('import', {'DISPLAY': ':99', 'PATH': _bins['import'],
                                           'XAUTHORITY': '/elsewhere/.Xauthority'})
try:
    _code, _rep = _snap(_u)
    eq('...or with ImageMagick\'s import when that is what there is, whole screen',
       (_piece(_rep, 'panel').get('tool'), ((_ran(_import) or {}).get('argv') or [])[:2]),
       ('import', ['-window', 'root']))
    eq('...and a cookie the server was started with is the one it hands on',
       ((_ran(_import) or {}).get('env') or {}).get('XAUTHORITY'), '/elsewhere/.Xauthority')
finally:
    stop(_p)
# No DISPLAY at all, which is how the service starts, and an X server at
# :0 — whose socket is /tmp/.X11-unix/X0. That path is this machine's own and
# cannot be made here without lying to every other X client on it, so this
# server alone is told it is there, by answering its fs.statSync for that one
# path before server.js loads; the search and what it does with the answer are
# the real code's.
_x0shim = os.path.join(_pdir, 'x0.js')
with open(_x0shim, 'w') as _fh:
    _fh.write("var fs = require('fs');\nvar real = fs.statSync;\n"
              "fs.statSync = function (p) {\n"
              "  if (String(p) === '/tmp/.X11-unix/X0') {\n"
              "    return { isSocket: function () { return true; } };\n"
              "  }\n"
              "  return real.apply(fs, arguments);\n"
              "};\n")
_p, _u, _snaps, _log = _snapper('x0', {'PATH': _bins['x0'],
                                       'NODE_OPTIONS': '--require ' + _x0shim})
try:
    _code, _rep = _snap(_u)
    _panel = _piece(_rep, 'panel')
    eq('a service with no DISPLAY finds the X server\'s socket and photographs :0',
       (_panel.get('tool'), _panel.get('session'),
        ((_ran(_x0scrot) or {}).get('env') or {}).get('DISPLAY')),
       ('scrot', 'x11', ':0'))
    eq('...with no cookie made up where the desktop account has none',
       ((_ran(_x0scrot) or {}).get('env') or {}).get('XAUTHORITY'), None)
finally:
    stop(_p)
_p, _u, _snaps, _log = _snapper('prefer', {'DISPLAY': ':0', 'XDG_RUNTIME_DIR': _wl,
                                           'PATH': _bins['both']})
try:
    _code, _rep = _snap(_u)
    eq('a Wayland desktop that also offers an X display is taken with grim',
       _piece(_rep, 'panel').get('tool'), 'grim')
finally:
    stop(_p)

# --- a tool that fails, lies, or hangs ----------------------------------------
_p, _u, _snaps, _log = _snapper('fails', {'XDG_RUNTIME_DIR': _wl, 'PATH': _bins['fails']})
try:
    _code, _rep = _snap(_u)
    eq('a screenshot tool that fails is named, with what it said',
       _piece(_rep, 'panel').get('why'),
       'grim failed (exit 1): compositor doesn\'t support wlr-screencopy-unstable-v1')
finally:
    stop(_p)
_p, _u, _snaps, _log = _snapper('junk', {'XDG_RUNTIME_DIR': _wl, 'PATH': _bins['junk']})
try:
    _code, _rep = _snap(_u)
    eq('a tool that exits 0 over something that is not a PNG is not believed',
       _piece(_rep, 'panel').get('why'), 'grim wrote something that is not a PNG')
    no_('...and what it wrote is not left behind as panel.png',
        os.path.exists(os.path.join(_snaps, _rep.get('name') or '?', 'panel.png')))
finally:
    stop(_p)
# ...and three that exit 0 over less than a picture: nothing at all, the
# eight-byte signature and no more, and a real PNG cut off part way through.
# One server, its grim rewritten between presses; it is looked up per press.
_p, _u, _snaps, _log = _snapper('liars', {'XDG_RUNTIME_DIR': _wl, 'PATH': _bins['liars']})
try:
    for _body, _name, _want in (
            ('pass', 'a tool that exits 0 and writes nothing is not believed',
             'grim finished without writing a picture'),
            ('open(out, "wb").write(%r)' % _PNG[:8],
             'a tool that exits 0 having written only the PNG signature is not believed',
             'grim wrote something that is not a PNG'),
            ('open(out, "wb").write(%r)' % _PNG[:40],
             'a PNG cut off before its end is not believed',
             'grim wrote a PNG that stops before its end')):
        _tool(_bins['liars'], 'grim', _body)
        _code, _rep = _snap(_u)
        _panel = _piece(_rep, 'panel')
        eq(_name, (_panel.get('saved'), _panel.get('why'),
                   os.path.exists(os.path.join(_snaps, _rep.get('name') or '?', 'panel.png'))),
           (False, _want, False))
finally:
    stop(_p)
_p, _u, _snaps, _log = _snapper('hangs', {'XDG_RUNTIME_DIR': _wl, 'PATH': _bins['hangs'],
                                          'SNAP_TOOL_MS': '600'})
try:
    _t0 = time.time()
    _code, _rep = _snap(_u, timeout=10)
    _took = time.time() - _t0
    eq('a tool that never finishes is given up on, and the snap kept without it',
       (_code, _rep.get('ok'), _piece(_rep, 'panel').get('why')),
       (200, True, 'grim did not finish in 1s'))
    ok_('...on its deadline rather than the panel\'s (%.1fs)' % _took, _took < 5)
    _pid = (_ran(_hangs) or {}).get('pid')
    _alive = True
    for _ in range(40):
        try:
            os.kill(_pid, 0)
        except (OSError, TypeError):
            _alive = False
            break
        time.sleep(0.05)
    no_('...and it is killed, not left running', _alive)
    no_('...taking its half-written file with it',
        os.path.exists(os.path.join(_snaps, _rep.get('name') or '?', 'panel.png')))
finally:
    stop(_p)

# --- a camera picture too old to be the one at the press ----------------------
#
# A running loop rewrites the picture every SNAPSHOT_IDLE with nobody watching,
# so where "old" begins is a statement about that cadence. Read out of the
# scanner rather than copied here: a picture two idle rewrites old is current,
# one six rewrites old is not.
_idle = float(re.search(r'^SNAPSHOT_IDLE = ([\d.]+)', open(
    os.path.join(ROOT, 'rpi', 'scan_pi.py'), encoding='utf-8').read(), re.M).group(1))
_old = os.path.join(_pdir, 'old.jpg')
shutil.copy(_frame, _old)
_p, _u, _snaps, _log = _snapper('stale', {'XDG_RUNTIME_DIR': _wl, 'PATH': _bins['grim'],
                                          'FRAME': _old})
try:
    os.utime(_old, (time.time() - 2 * _idle, time.time() - 2 * _idle))
    _cam = _piece(_snap(_u)[1], 'camera')
    eq('a camera picture two idle rewrites old (%gs) is called current' % (2 * _idle),
       (_cam.get('saved'), _cam.get('stale'), _cam.get('why')), (True, False, None))
    os.utime(_old, (time.time() - 6 * _idle, time.time() - 6 * _idle))
    _cam = _piece(_snap(_u)[1], 'camera')
    eq('...and one six idle rewrites old (%gs) is called old' % (6 * _idle),
       (_cam.get('saved'), _cam.get('stale'), _cam.get('why')),
       (True, True, 'camera picture %ds old, no scanner runs on this machine' % (6 * _idle)))
    # Written before the network set the clock, and pressed after: its mtime
    # is 1970 and the press is not, and the difference is not an age.
    os.utime(_old, (2 * 86400, 2 * 86400))
    _cam = _piece(_snap(_u)[1], 'camera')
    eq('a camera picture written before the rig\'s clock was set is kept with its age unknown',
       (_cam.get('saved'), _cam.get('ageMs'), _cam.get('stale'), _cam.get('why')),
       (True, None, None, 'camera picture of unknown age: '
                          'it was written before the rig\'s clock was set'))
    os.utime(_old, (time.time() - 600, time.time() - 600))
    _code, _rep = _snap(_u)
    _cam = _piece(_rep, 'camera')
    eq('a ten-minute-old camera picture is kept, but called stale, with why',
       (_cam.get('saved'), _cam.get('stale'), _cam.get('why')),
       (True, True, 'camera picture 10 min old, no scanner runs on this machine'))
    eq('...and said so in the line the panel shows, never as plain "saved"',
       _rep.get('said'), 'saved — camera picture 10 min old, no scanner runs on this machine')
finally:
    stop(_p)

# --- what was on the panel: the reading, its text, the offer, the order -------
_reading_text = 'UberX\n$16.05\n3 min (1.1 mi) away\n20 min (7.3 mi) trip'
_sfake2 = os.path.join(_pdir, 'reads.py')
with open(_sfake2, 'w') as _fh:
    _fh.write('import json, time\nprint(json.dumps({"ready": True, "state": "go", '
              '"perHour": 31.6, "grossPerHour": 41.9, "pay": 16.05, "minutes": 23.0, '
              '"miles": 8.4, "cost": 2.94, "billedMinutes": 23.0, "target": 25, "band": 15, '
              '"costPerMile": 0.35, "text": %r, "offer": {"id": "o-snap", "pay": 16.05, '
              '"minutes": 23.0, "billedMinutes": 23.0, "miles": 8.4, "cost": 2.94, '
              '"state": "go"}}), flush=True)\ntime.sleep(600)\n' % _reading_text)
_p, _u, _snaps, _log = _snapper('reading', {
    'SCANNER': '1', 'SCANNER_CMD': sys.executable, 'SCANNER_ARGS': _sfake2,
    'UBERSCAN_HANDOFF_DIR': _pdir, 'FRAME': os.path.join(_pdir, 'no-frame.jpg')})
try:
    for _ in range(100):
        if (get(_u, '/api/status').get('offer') or {}).get('id') == 'o-snap':
            break
        time.sleep(0.05)
    post(_u, '/api/offers/mark', {'id': 'o-snap', 'accepted': True})
    _t0 = time.time()
    _code, _rep = _snap(_u)
    _took = time.time() - _t0
    _status = _json_in(os.path.join(_snaps, _rep.get('name') or '?'), 'status.json') or {}
    eq('status.json carries the reading on the panel, and the reader\'s text',
       ((_status.get('last') or {}).get('perHour'), (_status.get('last') or {}).get('text')),
       (31.6, _reading_text))
    eq('...the offer on record', (_status.get('offer') or {}).get('id'), 'o-snap')
    eq('...and the order in the car', (_status.get('holding') or {}).get('pay'), 16.05)
    eq('a running scanner that has written no picture says so',
       _piece(_rep, 'camera').get('why'), 'no camera picture yet')
    # This scanner never looks for a snap request, so the press asks, waits its
    # four seconds, and then says so.
    eq('a scanner that does not answer is given up on, and both reader files say so',
       [(_piece(_rep, w).get('saved'), _piece(_rep, w).get('why')) for w in ('crop', 'reader')],
       [(False, 'the scanner did not answer in 4s')] * 2)
    ok_('...after the four seconds and not much more (%.1fs)' % _took, 4.0 <= _took < 6.0)
    # The screenshot's bit aside, which is this machine's desktop and not the
    # scanner's business.
    eq('...said once for the two, in the line the panel shows',
       [b for b in (_rep.get('said') or '').split(' — ', 1)[-1].split('; ')
        if 'screenshot' not in b],
       ['no camera picture: no camera picture yet',
        'no reader crop or reader record: the scanner did not answer in 4s'])
    # The request, as the scanner would have found it: in the handoff directory
    # under the shared name, naming the folder, and no temporary left beside it.
    eq('the request names the folder, under the name the scanner looks for',
       (_json_in(_pdir, 'uberscan-snap.json') or {}).get('folder'),
       os.path.join(_snaps, _rep.get('name') or '?'))
    eq('...renamed into place, with no temporary left behind',
       [n for n in os.listdir(_pdir) if n.startswith('uberscan-snap')], ['uberscan-snap.json'])
    # ...and the server was free while it waited. A press four seconds long
    # that held the event loop would have frozen the panel's every request.
    _waited = {}

    def _press_and_time():
        _waited['reply'] = _snap(_u)

    _pt = threading.Thread(target=_press_and_time)
    _pt.start()
    time.sleep(1.0)
    _s0 = time.time()
    get(_u, '/api/status')
    _waited['status'] = time.time() - _s0
    _pt.join()
    ok_('...and the server goes on answering while it waits (status in %.2fs)'
        % _waited['status'], _waited['status'] < 0.5)
finally:
    stop(_p)

# ...and one that has stopped. It is restarted after three seconds, so the
# press is made the moment the status says it is down.
_sfake3 = os.path.join(_pdir, 'dies.py')
with open(_sfake3, 'w') as _fh:
    _fh.write('import sys\nsys.exit(1)\n')
_p, _u, _snaps, _log = _snapper('dead', {
    'SCANNER': '1', 'SCANNER_CMD': sys.executable, 'SCANNER_ARGS': _sfake3,
    'UBERSCAN_HANDOFF_DIR': _pdir, 'FRAME': os.path.join(_pdir, 'no-frame.jpg')})
try:
    for _ in range(100):
        if not get(_u, '/api/status')['scanner']['running']:
            break
        time.sleep(0.02)
    _code, _rep = _snap(_u)
    eq('a scanner that is not running is named as the reason there is no picture',
       _piece(_rep, 'camera').get('why'), 'the scanner is not running')
    eq('...and as the reason there is nothing from the reader',
       [(_piece(_rep, w).get('saved'), _piece(_rep, w).get('why')) for w in ('crop', 'reader')],
       [(False, 'the scanner is not running')] * 2)
    eq('...said once for all three, in the line the panel shows',
       [b for b in (_rep.get('said') or '').split(' — ', 1)[-1].split('; ')
        if 'screenshot' not in b],
       ['no camera picture, reader crop or reader record: the scanner is not running'])
finally:
    stop(_p)

# ...and a request that cannot be written — /dev/shm full — is said as that,
# at once, and leaves no temporary behind. Staged by tearing this server's own
# fs.writeFile for the request's temporary, the way the torn case below does
# for the snap's files.
_aho = os.path.join(_pdir, 'ask-handoff')
os.makedirs(_aho)
_askfull = os.path.join(_pdir, 'ask-full.js')
with open(_askfull, 'w') as _fh:
    _fh.write("var fs = require('fs');\nvar real = fs.writeFile;\n"
              "fs.writeFile = function (p, data, cb) {\n"
              "  if (!/snap\\.json\\.\\d+\\.\\d+\\.part$/.test(String(p))) return real.apply(fs, arguments);\n"
              "  return real.call(fs, p, String(data).slice(0, 4), function () {\n"
              "    var e = new Error('no space left on device'); e.code = 'ENOSPC';\n"
              "    cb(e);\n"
              "  });\n"
              "};\n")
_p, _u, _snaps, _log = _snapper('unasked', {
    'SCANNER': '1', 'SCANNER_CMD': sys.executable, 'SCANNER_ARGS': _sfake2,
    'UBERSCAN_HANDOFF_DIR': _aho, 'FRAME': os.path.join(_pdir, 'no-frame.jpg'),
    'NODE_OPTIONS': '--require ' + _askfull})
try:
    for _ in range(100):
        if get(_u, '/api/status')['scanner']['running']:
            break
        time.sleep(0.05)
    _t0 = time.time()
    _code, _rep = _snap(_u)
    eq('a request the handoff directory will not take is said as that',
       [(_piece(_rep, w).get('saved'), _piece(_rep, w).get('why')) for w in ('crop', 'reader')],
       [(False, 'could not ask the scanner: ENOSPC')] * 2)
    ok_('...at once, not after waiting for an answer to it (%.1fs)' % (time.time() - _t0),
        time.time() - _t0 < 3.0)
    eq('...leaving nothing in the handoff directory', os.listdir(_aho), [])
finally:
    stop(_p)

# --- a scanner that answers: what the reader last read, into the folder -------
#
# The scanner here is a stand-in that takes the request and answers it with the
# real scan_pi.py — snap_requested, reader_record, answer_snap — so what the
# server reads is what the rig writes. rpi/test_loop.py drives the same three
# through the real scan loop. Each answer is one line of the plan: agreeing
# with the panel about the card, disagreeing, before any read, a reader.json
# that is not one, and no card on record at all. It takes a request every
# 0.6s, slowly enough that two presses together are both written before it
# looks. SNAP_TEST_UNTOLD starts it without telling the server of its card,
# the way a server started under a scanner that resumed one is.
try:
    import numpy                                              # noqa: F401
    import cv2                                                # noqa: F401
    _have_reader = True
except ImportError:
    _have_reader = False
    print('  (no numpy or OpenCV here, so the scanner\'s own answer cannot be '
          'written — skipping the answering-scanner checks)')
if _have_reader:
    _rho = os.path.join(_pdir, 'reader-handoff')
    os.makedirs(_rho)
    _rplan = os.path.join(_pdir, 'reader-plan.txt')
    with open(_rplan, 'w') as _fh:
        _fh.write('agree disagree noread garbage none agree agree band')
    _rfake = os.path.join(_pdir, 'answers.py')
    with open(_rfake, 'w') as _fh:
        _fh.write('import json, os, sys, time\n'
                  'sys.path.insert(0, %r)\n'
                  'import numpy as np\n'
                  'import scan_pi as SP\n'
                  'class OnRecord(object):\n'
                  '    def __init__(self, i):\n'
                  '        self.id = self.landed_id = i\n'
                  'told = {"ready": True, "state": "go", "perHour": 31.6, "pay": 16.05, '
                  '"minutes": 23.0, "miles": 8.4, "offer": {"id": "o-snap", "pay": 16.05, '
                  '"minutes": 23.0, "billedMinutes": 23.0, "miles": 8.4, "cost": 2.94, '
                  '"state": "go"}}\n'
                  'if os.environ.get("SNAP_TEST_UNTOLD"):\n'
                  '    del told["offer"]\n'
                  'print(json.dumps(told), flush=True)\n'
                  'last = {"at": time.time(), "fitted": np.full((60, 40), 90, np.uint8), '
                  '"wholeScreen": False, "crop": [0.0, 0.3, 1.0, 0.5], "text": "UberX $16.05", '
                  '"parsed": {"pay": 16.05, "episode": 2}, "rate": {"ready": True, "state": "go"}}\n'
                  'done = 0\n'
                  'while True:\n'
                  '    folder = SP.snap_requested()\n'
                  '    if folder:\n'
                  '        plan = open(%r).read().split()\n'
                  '        how = plan[done] if done < len(plan) else "agree"\n'
                  '        done += 1\n'
                  '        now = time.time()\n'
                  '        if how == "garbage":\n'
                  '            open(os.path.join(folder, "reader.json"), "w").write("not json")\n'
                  '        elif how == "band":\n'
                  '            import tempfile\n'
                  '            src = tempfile.mkdtemp()\n'
                  '            jpg = os.path.join(src, "o-snap.jpg")\n'
                  '            SP.PL.write_jpeg(jpg, np.full((80, 60, 3), 200, np.uint8))\n'
                  '            open(jpg[:-4] + ".json", "w").write(json.dumps({"offerId": "o-snap"}))\n'
                  '            SP.answer_snap(folder, last, SP.reader_record(last, now, '
                  'offer_log=OnRecord("o-snap"), counters=SP.Health().counters(now)), '
                  'band={"offerId": "o-snap", "jpg": jpg, "json": jpg[:-4] + ".json", '
                  '"savedAt": now - 5})\n'
                  '        else:\n'
                  '            read = None if how == "noread" else last\n'
                  '            card = {"disagree": "o-other", "none": None}.get(how, "o-snap")\n'
                  '            SP.answer_snap(folder, read, SP.reader_record(read, now, '
                  'offer_log=OnRecord(card), counters=SP.Health().counters(now)))\n'
                  '    time.sleep(0.6)\n' % (os.path.join(ROOT, 'rpi'), _rplan))
    _p, _u, _snaps, _log = _snapper('reader', {
        'XDG_RUNTIME_DIR': _wl, 'PATH': _bins['grim'],
        'SCANNER': '1', 'SCANNER_CMD': sys.executable, 'SCANNER_ARGS': _rfake,
        'UBERSCAN_HANDOFF_DIR': _rho, 'FRAME': os.path.join(_pdir, 'no-frame.jpg')})
    try:
        for _ in range(400):
            if (get(_u, '/api/status').get('offer') or {}).get('id') == 'o-snap':
                break
            time.sleep(0.05)
        _code, _rep = _snap(_u)
        _dir = os.path.join(_snaps, _rep.get('name') or '?')
        _crop, _reader = _piece(_rep, 'crop'), _piece(_rep, 'reader')
        eq('a scanner that answers leaves its crop and its account in the folder',
           ((_crop.get('saved'), _crop.get('bytes')), (_reader.get('saved'), _reader.get('bytes'))),
           ((True, _size(os.path.join(_dir, 'reader.jpg'))),
            (True, _size(os.path.join(_dir, 'reader.json')))))
        _said = _json_in(_dir, 'reader.json') or {}
        eq('...reader.json being the scanner\'s, naming the card it has on record',
           ((_said.get('read') or {}).get('text'), _said.get('offer'), _said.get('episode')),
           ('UberX $16.05', {'id': 'o-snap', 'landed': True}, 2))
        eq('...which is the panel\'s card too, so nothing is said about it',
           (_reader.get('offer'), _reader.get('panelOffer'), _reader.get('warn'), _rep.get('said')),
           ('o-snap', 'o-snap', None, 'saved — no camera picture: no camera picture yet'))
        eq('...and the two are listed and served with the rest',
           sorted(f['file'] for f in _listed(_u, _rep.get('name')).get('files') or []),
           ['panel.png', 'reader.jpg', 'reader.json', 'snap.json', 'status.json'])
        _st, _body, _type = _fetch(_u, '/api/snaps/%s/reader.jpg' % _rep.get('name'))
        eq('...reader.jpg as the JPEG the scanner wrote',
           (_st, _type, _body == open(os.path.join(_dir, 'reader.jpg'), 'rb').read()),
           (200, 'image/jpeg', True))
        _row = ([r for r in _jrows(os.path.join(os.path.dirname(_snaps), 'journal.jsonl'))
                 if r.get('kind') == 'snap'] or [{}])[-1]
        eq('...and the journal row lists them among the parts kept',
           (_row.get('parts'), _row.get('missing'), _row.get('notApplicable')),
           (['panel.png', 'reader.jpg', 'status.json', 'reader.json', 'snap.json'],
            {'camera.jpg': 'no camera picture yet'}, {}))

        # The reader on another card from the panel: said FIRST, because the
        # line is cut from the end and it says the snap's own reader files
        # and status.json are of two cards.
        _code, _rep = _snap(_u)
        _reader = _piece(_rep, 'reader')
        eq('a reader on another card from the panel is said first, briefly, on the panel\'s line',
           _rep.get('said'), 'saved — reader and panel on different cards: reader o-other, '
                             'panel o-snap; no camera picture: no camera picture yet')
        eq('...and recorded in snap.json with both cards',
           [(p.get('offer'), p.get('panelOffer')) for p in
            (_json_in(os.path.join(_snaps, _rep.get('name') or '?'), 'snap.json') or {})
            .get('contents') or [] if p.get('what') == 'reader'],
           [('o-other', 'o-snap')])

        _code, _rep = _snap(_u)
        eq('a scanner with no read yet answers, and the crop it has not got is said as that',
           [(_piece(_rep, w).get('saved'), _piece(_rep, w).get('why')) for w in ('crop', 'reader')],
           [(False, 'no read yet'), (True, None)])
        eq('...on the panel\'s line', _rep.get('said'),
           'saved — no camera picture: no camera picture yet; no reader crop: no read yet')

        _code, _rep = _snap(_u)
        eq('a reader.json that is not one is kept, called unreadable, and the crop\'s absence '
           'said as unexplained',
           [(_piece(_rep, w).get('saved'), _piece(_rep, w).get('why')) for w in ('crop', 'reader')],
           [(False, 'the scanner kept no reader.jpg and did not say why'),
            (True, 'reader.json cannot be read')])

        # A reader with no card on record beside a panel with one: a scanner
        # restarted after its last card was too old to resume, while this
        # server kept the one it was told about. Not a second card.
        _code, _rep = _snap(_u)
        _reader = _piece(_rep, 'reader')
        eq('a reader with no card on record, beside a panel with one, is not called another card',
           (_reader.get('offer'), _reader.get('panelOffer'), _reader.get('warn'), _rep.get('said')),
           (None, 'o-snap', None, 'saved — no camera picture: no camera picture yet'))

        # Two presses together. One request file: written for both at once,
        # the second would replace the first before the scanner looked, and
        # the first would wait out four seconds for an answer that went to the
        # other. Asked in turn, both are answered.
        _two = [None, None]

        def _press2(i):
            _t = time.time()
            _two[i] = (_snap(_u), time.time() - _t)

        _ts = [threading.Thread(target=_press2, args=(i,)) for i in (0, 1)]
        for _t in _ts:
            _t.start()
        for _t in _ts:
            _t.join()
        eq('two presses together are both answered by the scanner, in turn',
           [[_piece(x[0][1], w).get('saved') for w in ('crop', 'reader')] for x in _two],
           [[True, True], [True, True]])
        ok_('...neither waiting out the deadline for it (%s)'
            % ', '.join('%.1fs' % x[1] for x in _two), all(x[1] < 3.5 for x in _two))

        # The newest offer's map band (scan_pi.MAP_BANDS_DIR), copied in by
        # the scanner beside reader.json: kept as map.jpg and map.json, listed,
        # served and bundled with the rest, and never on the panel's line.
        _code, _rep = _snap(_u)
        _name = _rep.get('name') or '?'
        _dir = os.path.join(_snaps, _name)
        _band = _piece(_rep, 'map')
        eq('a scanner that answers with a map band leaves it in the snap as map.jpg',
           (_band.get('saved'), _band.get('bytes'), _band.get('offer')),
           (True, _size(os.path.join(_dir, 'map.jpg')), 'o-snap'))
        eq('...and nothing about it on the panel\'s line', _rep.get('said'),
           'saved — no camera picture: no camera picture yet')
        eq('...listed with its sidecar among the snap\'s files',
           sorted(f['file'] for f in _listed(_u, _name).get('files') or []),
           ['map.jpg', 'map.json', 'panel.png', 'reader.jpg', 'reader.json', 'snap.json',
            'status.json'])
        _st, _body, _type = _fetch(_u, '/api/snaps/%s/map.jpg' % _name)
        eq('...served as the JPEG the scanner copied',
           (_st, _type, _body == open(os.path.join(_dir, 'map.jpg'), 'rb').read()),
           (200, 'image/jpeg', True))
        _st, _body, _type = _fetch(_u, '/api/snaps/bundle?snap=%s' % _name)
        _body = _body.decode('utf-8', 'replace') if isinstance(_body, bytes) else _body
        ok_('...and carried in the snap\'s bundle, picture and sidecar',
            _st == 200 and 'map.jpg — ' in _body and 'map.json — ' in _body)
    finally:
        stop(_p)

    # The scanner is started in the checkout, and this server need not be: a
    # JOURNAL given relative to where the server was started puts the snaps
    # folder there too, and the folder named to the scanner has to be the same
    # folder from where IT stands.
    _rel = os.path.join(_pdir, 'started-elsewhere')
    os.makedirs(_rel)
    _p, _u, _snaps, _log = _snapper('relative', {
        'XDG_RUNTIME_DIR': _wl, 'PATH': _bins['grim'], 'JOURNAL': 'journal.jsonl',
        'SCANNER': '1', 'SCANNER_CMD': sys.executable, 'SCANNER_ARGS': _rfake,
        'UBERSCAN_HANDOFF_DIR': _rho, 'FRAME': os.path.join(_pdir, 'no-frame.jpg')}, cwd=_rel)
    try:
        open(os.path.join(_rel, 'journal.jsonl'), 'a').close()
        for _ in range(400):
            if (get(_u, '/api/status').get('offer') or {}).get('id') == 'o-snap':
                break
            time.sleep(0.05)
        _code, _rep = _snap(_u)
        eq('a server started elsewhere with a relative JOURNAL names the scanner a folder it '
           'can find, and is answered in it',
           ([_piece(_rep, w).get('saved') for w in ('crop', 'reader')],
            os.path.isfile(os.path.join(_rel, 'snaps', _rep.get('name') or '?', 'reader.json'))),
           ([True, True], True))
    finally:
        stop(_p)

    # ...and the other way about: a server started under a scanner that had
    # resumed a card, and so never told of it. The panel has no card on record
    # and the reader has one, which is not two cards either.
    _p, _u, _snaps, _log = _snapper('untold', {
        'XDG_RUNTIME_DIR': _wl, 'PATH': _bins['grim'], 'SNAP_TEST_UNTOLD': '1',
        'SCANNER': '1', 'SCANNER_CMD': sys.executable, 'SCANNER_ARGS': _rfake,
        'UBERSCAN_HANDOFF_DIR': _rho, 'FRAME': os.path.join(_pdir, 'no-frame.jpg')})
    try:
        for _ in range(400):
            if (get(_u, '/api/status').get('last') or {}).get('perHour') == 31.6:
                break
            time.sleep(0.05)
        _code, _rep = _snap(_u)
        _reader = _piece(_rep, 'reader')
        eq('a panel with no card on record, beside a reader with one, is not called another card',
           (_reader.get('offer'), _reader.get('panelOffer'), _reader.get('warn'), _rep.get('said')),
           ('o-snap', None, None, 'saved — no camera picture: no camera picture yet'))
    finally:
        stop(_p)

# The scanner refuses a request older than its window; the server stops waiting
# after its own. The first must close before the second, or an answer can land
# in a folder whose snap.json has already said there is none. Read out of both
# files, so neither can move alone.
_window = float(re.search(r'^SNAP_ANSWER_WINDOW = ([\d.]+)', open(
    os.path.join(ROOT, 'rpi', 'scan_pi.py'), encoding='utf-8').read(), re.M).group(1))
_wait = int(re.search(r'^var SNAP_READER_MS = (\d+);', open(
    os.path.join(ROOT, 'server.js'), encoding='utf-8').read(), re.M).group(1))
ok_('the scanner stops answering a snap request (%gs) a good half second before the '
    'server stops waiting for one (%gs)' % (_window, _wait / 1000.0),
    _window * 1000 <= _wait - 500)

# --- the snap row is collection only: everything that reads offers passes it --
#
# A `kind` row, like a mark, a pair or a drop. Pressed on a journal with two
# offers in it, and every reader asked the same question before and after:
# the offers page's fold, the CSV, /api/journal/newest's count, the notes the
# sync copies, and journal.py's last(), which the scanner resumes from.
sys.path.insert(0, os.path.join(ROOT, 'rpi'))
import journal as _JR                                         # noqa: E402
_p, _u, _snaps, _log = _snapper('kinds', {'XDG_RUNTIME_DIR': _wl, 'PATH': _bins['grim']})
_kj = os.path.join(os.path.dirname(_snaps), 'journal.jsonl')
_know = int(time.time() * 1000)
write(_kj, [offer(71, _know - 120000), offer(72, _know - 60000)])
try:
    def _readers():
        # `have` in /api/journal/newest is every row the copy holds, and is
        # meant to count this one; the newest offer and the count of offers
        # are the figures the sync resumes from.
        _newest = get(_u, '/api/journal/newest')
        return (get(_u, '/api/journal?days=0').get('offers'),
                raw(_u, '/api/journal.csv?days=0')[1],
                (_newest.get('newest'), _newest.get('offers')),
                get(_u, '/api/journal/notes'),
                _JR.Journal(_kj).last())
    _before = _readers()
    _code, _rep = _snap(_u)
    _krows = [r for r in _jrows(_kj) if r.get('kind') == 'snap']
    eq('a snap on a journal with offers in it writes its row', len(_krows), 1)
    _after = _readers()
    for _i, _what in enumerate(('the offers page\'s fold', 'the CSV',
                                '/api/journal/newest\'s count of offers',
                                'the notes the sync copies',
                                'journal.py\'s last offer, which the scanner resumes from')):
        eq('%s passes over the snap row' % _what, _after[_i], _before[_i])
finally:
    stop(_p)
# ...and the sync carries it to the copy at home, which is why it has an id and
# a seq: syncKey drops a kind row that has neither.
_hj = os.path.join(_pdir, 'home-journal.jsonl')
open(_hj, 'w').close()
_hp, _hb = start({'SCANNER': '0'}, _hj)
try:
    def _send(rows):
        return json.loads(urllib.request.urlopen(urllib.request.Request(
            _hb + '/api/journal/ingest',
            data=(''.join(json.dumps(r) + '\n' for r in rows)).encode('utf-8'),
            headers={'Content-Type': 'application/x-ndjson'}), timeout=10).read().decode())
    eq('the copy at home stores a snap row sent to it', _send(_krows).get('added'), 1)
    eq('...once, however often it is sent', _send(_krows).get('added'), 0)
    eq('...as it was written', _jrows(_hj), _krows)
finally:
    stop(_hp)

# ...and stamped when it is written, not at the press. It is written once the
# slowest part is in, and the scan loop goes on appending offers meanwhile: a
# row stamped at the press lands behind them, which rpi/doctor.py reads as NTP
# stepping the clock back mid-shift. A screenshot that takes a second, and an
# offer landing half way through it.
_p, _u, _snaps, _log = _snapper('forwards', {'XDG_RUNTIME_DIR': _wl, 'PATH': _bins['slow']})
_fj = os.path.join(os.path.dirname(_snaps), 'journal.jsonl')
try:
    def _lands():
        time.sleep(0.5)
        write(_fj, [offer(81, int(time.time() * 1000))], mode='a')

    _lt = threading.Thread(target=_lands)
    _lt.start()
    _code, _rep = _snap(_u)
    _lt.join()
    _frows = _jrows(_fj)
    eq('a snap whose screenshot took a second is written after the offer that landed during it',
       [r.get('kind') for r in _frows], [None, 'snap'])
    ok_('...and stamped after it, so the journal\'s stamps still run forwards (%r, pressed %r)'
        % ([r.get('at') for r in _frows], _rep.get('at')),
        len(_frows) == 2 and _frows[0]['at'] <= _frows[1]['at'])
finally:
    stop(_p)

# --- newest first, and the oldest go, out loud --------------------------------
_p, _u, _snaps, _log = _snapper('prune', {'XDG_RUNTIME_DIR': _wl, 'PATH': _bins['grim'],
                                          'SNAPS_KEEP': '3'})
try:
    # A second apart, so this is about pruning and not about two presses in
    # one second, which has its own case below.
    _made = []
    for _ in range(3):
        _made.append(_snap(_u)[1].get('name') or '')
        time.sleep(1.05)
    eq('three presses are three snaps', len(set(_made)), 3)
    eq('the list is newest first', [s['name'] for s in get(_u, '/api/snaps')['snaps']],
       sorted(_made, reverse=True))
    _code, _rep = _snap(_u)
    eq('a fourth with three kept removes the oldest, and the reply names it',
       _rep.get('pruned'), [sorted(_made)[0]])
    eq('...which is gone from disk',
       sorted(os.listdir(_snaps)), sorted(sorted(_made)[1:] + [_rep.get('name')]))
    # Said where the driver is looking, not only in the reply's fields: the
    # control shows this line and nothing else.
    eq('...and the line the panel shows says which went',
       _rep.get('said'), 'saved — removed the oldest to keep 3: %s' % sorted(_made)[0])
    _logged = open(_log).read()
    ok_('...and the server log says so (%r)'
        % [l for l in _logged.splitlines() if 'removed' in l][:1],
        'snap: %s saved — removed the oldest to keep 3: %s' % (_rep.get('name'), sorted(_made)[0])
        in _logged)
    # A snap named for a time BEFORE every one already there — a Pi that booted
    # in 1970 and has not heard from the network yet — is the oldest folder
    # there is, and the press that made it must not be the press that deletes
    # it. Staged with three from 2099, so the new one is the oldest by name.
    for _n in os.listdir(_snaps):
        shutil.rmtree(os.path.join(_snaps, _n))
    for _future in ('2099-01-01_00-00-00', '2099-01-01_00-00-01', '2099-01-01_00-00-02'):
        os.mkdir(os.path.join(_snaps, _future))
    _code, _rep = _snap(_u)
    eq('a new snap that sorts oldest is never the one removed to make room',
       (os.path.isdir(os.path.join(_snaps, _rep.get('name') or '?')), _rep.get('pruned')),
       (True, ['2099-01-01_00-00-00']))
finally:
    stop(_p)

# --- two presses in one second -------------------------------------------------
#
# Forced rather than hoped for: the folders for this second and the next few
# are already there, so the press has to land on a name that is taken.
_p, _u, _snaps, _log = _snapper('collide', {'XDG_RUNTIME_DIR': _wl, 'PATH': _bins['grim']})
try:
    os.makedirs(_snaps, exist_ok=True)
    _now = time.time()
    _taken = [time.strftime('%Y-%m-%d_%H-%M-%S', time.localtime(_now + i)) for i in range(6)]
    for _n in _taken:
        os.mkdir(os.path.join(_snaps, _n))
    _code, _rep = _snap(_u)
    _n = _rep.get('name') or ''
    ok_('a second snap in a second already taken is numbered -02 (%r)' % _n,
        _n.endswith('-02') and _n[:-3] in _taken)
    _order = [s['name'] for s in get(_u, '/api/snaps')['snaps']]
    ok_('...and lists as newer than the first one of that second, older than the next',
        _n in _order and _n[:-3] in _order
        and _order.index(_n) + 1 == _order.index(_n[:-3]))
finally:
    stop(_p)

# --- a rig whose clock the network has not set yet ----------------------------
#
# A Pi has no real-time clock. Until the network answers it believes it is
# 1970, so a snap taken then is named for 1970 — which is the oldest name there
# is. Staged by winding this server's Date.now back to two days after the epoch
# before server.js loads — two, so the local date is 1970 in any zone — and the
# name, the note and the pruning are the real code's, on the clock a cold Pi
# actually has.
_clock = os.path.join(_pdir, 'cold-boot.js')
with open(_clock, 'w') as _fh:
    _fh.write('var real = Date.now;\nvar back = real() - 2 * 86400000;\n'
              'Date.now = function () { return real() - back; };\n')
_p, _u, _snaps, _log = _snapper('clock', {'XDG_RUNTIME_DIR': _wl, 'PATH': _bins['grim'],
                                          'SNAPS_KEEP': '1',
                                          'NODE_OPTIONS': '--require ' + _clock})
try:
    os.makedirs(_snaps, exist_ok=True)
    os.mkdir(os.path.join(_snaps, '2026-10-01_12-00-00'))
    _code, _rep = _snap(_u)
    ok_('a snap on a clock nobody has set is named for the year that clock says (%r)'
        % _rep.get('name'), (_rep.get('name') or '').startswith('1970-01-0'))
    ok_('...and says so, rather than filing it in 1970 in silence (%r)' % _rep.get('said'),
        'the rig\'s clock is not set, so it is filed under 1970' in (_rep.get('said') or ''))
    eq('...and, sorting oldest, it is the one kept when only one may be',
       (sorted(os.listdir(_snaps)), _rep.get('pruned')),
       ([_rep.get('name')], ['2026-10-01_12-00-00']))
    # The scanner's picture is stamped by the filesystem on the real clock,
    # and the press is on this one: no age can come of the two.
    eq('...and its camera picture\'s age is unknown, the clock reading it not being set',
       (_piece(_rep, 'camera').get('ageMs'), _piece(_rep, 'camera').get('why')),
       (None, 'camera picture of unknown age: the rig\'s clock is not set'))
    # The other way round from the 1970 snap listed on a set clock above: a
    # snap from yesterday, on a set clock, listed by a rig that has just
    # rebooted and not heard from the network.
    _shelve(_snaps, '2026-10-02_12-00-00', {'v': 1, 'at': time.time() * 1000 - 86400000,
                                            'said': 'saved', 'contents': [], 'notes': []})
    eq('a snap made on a set clock lists its age as unknown on a rig whose clock is not set yet',
       'ageMs=%r' % _listed(_u, '2026-10-02_12-00-00').get('ageMs', '?'), 'ageMs=None')
finally:
    stop(_p)

# --- two presses at once, on that clock, with the shelf full ------------------
#
# Both are named for 1970, so both are the oldest folders there are, and each
# prunes when it finishes. Two presses three tenths of a second apart, each
# with a screenshot that takes a second: the first finishes while the second is
# still being filled.
_p, _u, _snaps, _log = _snapper('together', {'XDG_RUNTIME_DIR': _wl, 'PATH': _bins['slow'],
                                             'SNAPS_KEEP': '3',
                                             'NODE_OPTIONS': '--require ' + _clock})
try:
    _shelf3 = ['2026-10-01_12-00-00', '2026-10-01_12-00-01', '2026-10-01_12-00-02']
    for _n in _shelf3:
        _shelve(_snaps, _n)
    _both = [None, None]

    def _press(i):
        _both[i] = _snap(_u)

    _threads = [threading.Thread(target=_press, args=(i,)) for i in (0, 1)]
    _threads[0].start()
    time.sleep(0.3)
    _threads[1].start()
    for _t in _threads:
        _t.join()
    _a, _b = (_both[0] or (None, {}))[1], (_both[1] or (None, {}))[1]
    eq('two presses at once on an unset clock and a full shelf both keep their folders',
       sorted(os.listdir(_snaps)), sorted([_a.get('name'), _b.get('name'), _shelf3[2]]))
    eq('...the first making room with the two oldest that were there, never the other press',
       (_a.get('pruned'), _b.get('pruned')), (_shelf3[:2], []))
    eq('...and both are answered with their snap.json written',
       ['could not write snap.json' in (r.get('said') or '') for r in (_a, _b)], [False, False])
finally:
    stop(_p)

# --- a card that fills while the press is being written -----------------------
#
# A full card makes the file and then fails part way through writing it, so
# what is left is torn, under a name that promises a picture or a record.
# Staged the way the cold clock is, by tearing this server's own fs.writeFile
# for the files named in TEST_TORN before server.js loads.
_torn = os.path.join(_pdir, 'torn.js')
with open(_torn, 'w') as _fh:
    _fh.write("var fs = require('fs');\nvar real = fs.writeFile;\n"
              "var torn = new RegExp(process.env.TEST_TORN);\n"
              "fs.writeFile = function (p, data, cb) {\n"
              "  if (!torn.test(String(p))) return real.apply(fs, arguments);\n"
              "  var buf = Buffer.from(data);\n"
              "  return real.call(fs, p, buf.subarray(0, buf.length >> 1), function () {\n"
              "    var e = new Error('no space left on device'); e.code = 'ENOSPC';\n"
              "    cb(e);\n"
              "  });\n"
              "};\n")
_p, _u, _snaps, _log = _snapper('torn', {'XDG_RUNTIME_DIR': _wl, 'PATH': _bins['grim'],
                                         'TEST_TORN': r'(camera\.jpg|status\.json|snap\.json)$',
                                         'NODE_OPTIONS': '--require ' + _torn})
try:
    _code, _rep = _snap(_u)
    _dir = os.path.join(_snaps, _rep.get('name') or '?')
    eq('a camera picture that cannot be written is not called kept, and says why',
       (_piece(_rep, 'camera').get('saved'), _piece(_rep, 'camera').get('why')),
       (False, 'could not keep the camera picture: ENOSPC'))
    no_('...and leaves no torn camera.jpg behind', os.path.exists(os.path.join(_dir, 'camera.jpg')))
    eq('a status that cannot be written says why',
       (_piece(_rep, 'status').get('saved'), _piece(_rep, 'status').get('why')),
       (False, 'could not write it: ENOSPC'))
    no_('...and leaves no torn status.json behind',
        os.path.exists(os.path.join(_dir, 'status.json')))
    eq('a snap.json that cannot be written is said in the line the panel shows',
       _rep.get('said'), 'saved — no camera picture: could not keep the camera picture: ENOSPC; '
                         'no status: could not write it: ENOSPC; could not write snap.json: ENOSPC')
    no_('...and leaves no torn snap.json behind', os.path.exists(os.path.join(_dir, 'snap.json')))
    _first = _listed(_u, _rep.get('name'))
    eq('...so the list shows only the picture that was kept, and that nothing records the rest',
       ([(f['file'], f['bytes']) for f in _first.get('files') or []], _first.get('said')),
       ([('panel.png', len(_PNG))], 'no snap.json in this folder, so nothing says what is missing'))
    # ...but the journal does: its row is written either way, and says which
    # files went missing, snap.json among them.
    _trow = _snaprow(_snaps)
    eq('...and the journal row records what is missing, snap.json among them',
       (_trow.get('folder'), _trow.get('parts'), _trow.get('missing')),
       (_rep.get('name'), ['panel.png'],
        {'camera.jpg': 'could not keep the camera picture: ENOSPC',
         'status.json': 'could not write it: ENOSPC', 'snap.json': 'could not write it: ENOSPC'}))
finally:
    stop(_p)

# --- nowhere to put it --------------------------------------------------------
_p, _u, _snaps, _log = _snapper('blocked', {'XDG_RUNTIME_DIR': _wl, 'PATH': _bins['grim']})
try:
    with open(_snaps, 'w') as _fh:
        _fh.write('a file where the folder goes')
    _code, _rep = _snap(_u)
    ok_('a snaps folder that cannot be made is a failure that says where (%r)'
        % _rep.get('error'),
        _code == 500 and _rep.get('ok') is False
        and 'could not make a folder for it in ' + _snaps in (_rep.get('error') or ''))
finally:
    stop(_p)

# ...and a folder made with nothing to go in it: no screenshot tool, no camera
# picture, and a card that refuses the status as it is written. Staged the way
# the cold clock is, by failing this server's own fs.writeFile for status.json
# before server.js loads — this suite runs as root, which no permission bit
# stops — so the folder, the three reasons and the clean-up are the real code's.
_full = os.path.join(_pdir, 'card-full.js')
with open(_full, 'w') as _fh:
    _fh.write("var fs = require('fs');\nvar real = fs.writeFile;\n"
              "fs.writeFile = function (p, data, cb) {\n"
              "  if (/status\\.json$/.test(String(p))) {\n"
              "    var e = new Error('no space left on device'); e.code = 'ENOSPC';\n"
              "    return setImmediate(cb, e);\n"
              "  }\n"
              "  return real.apply(fs, arguments);\n"
              "};\n")
_p, _u, _snaps, _log = _snapper('nothing', {'XDG_RUNTIME_DIR': _wl, 'PATH': _bins['none'],
                                            'FRAME': os.path.join(_pdir, 'no-frame.jpg'),
                                            'NODE_OPTIONS': '--require ' + _full})
try:
    _code, _rep = _snap(_u)
    # Every reason of a part that applies here: no scanner runs on this
    # machine, so the camera's and the reader's are not among them.
    eq('a press that keeps nothing at all is a failure that gives every reason',
       (_code, _rep.get('ok'), _rep.get('error')),
       (500, False, 'nothing could be kept: grim is not installed; could not write it: ENOSPC'))
    eq('...and leaves no empty folder behind to list as a snap',
       (os.listdir(_snaps) if os.path.isdir(_snaps) else [], get(_u, '/api/snaps')['snaps']),
       ([], []))
    eq('...and no snap row in the journal, there being no folder for one to name',
       _snaprow(_snaps), {})
finally:
    stop(_p)

# --- 📷 a snap as one file, several as one, and a note on each ----------------
#
# A snap is six files, and the driver hands a series of them to their
# assistant. GET /api/snaps/bundle?snap=<folder>&snap=… makes them one .html,
# built when asked: each picture inline as a data: URI, each record as its text
# and again as the file itself behind a link that saves it. Read here as text,
# which is how an assistant reads it; rpi/test_dashboard.py opens one in a
# browser with the network off.
#
# The reader's two files are put in the first snap by hand — no scanner runs
# here — and its reader.json is the hardest text a record can hold for this:
# a line break before anything else, which an HTML parser drops after <pre>,
# and markup — `</script>`, `<!--`, a tag, an ampersand and quotes — which is
# what tesseract makes of whatever the camera saw.
import base64                                                 # noqa: E402
import html as _html                                          # noqa: E402


def _bundle(url, *names, **kw):
    """Status, headers and text of a bundle, the query sent exactly as given."""
    q = kw.get('raw')
    if q is None:
        q = '&'.join('snap=' + urllib.parse.quote(n, safe='') for n in names)
    u = urllib.parse.urlparse(url)
    c = http.client.HTTPConnection(u.hostname, u.port, timeout=10)
    try:
        c.request('GET', '/api/snaps/bundle' + ('?' + q if q else ''))
        r = c.getresponse()
        body = r.read()
    except Exception as e:
        # A server that dropped the connection part way — a result, so the
        # check that names it fails, rather than the suite (see _snap).
        return None, {}, repr(e)
    finally:
        c.close()
    return r.status, dict(r.getheaders()), body.decode('utf-8', 'replace')


def _pictures(text):
    """(file, bytes) for each picture in a bundle, in order."""
    return [(m.group(2).split(' — ')[0], base64.b64decode(m.group(1))) for m in re.finditer(
        r'<img src="data:image/[a-z]+;base64,([A-Za-z0-9+/=]*)" alt="[^"]*">'
        r'<figcaption>([^<]*)</figcaption>', text)]


def _records(text):
    """(file, text shown, bytes saved, name saved under) for each record, in order."""
    return [(m.group(1).split(' — ')[0], _html.unescape(m.group(2)), base64.b64decode(m.group(4)),
             m.group(3)) for m in re.finditer(
        r'<details><summary>([^<]*)</summary>\n<pre>\n(.*?)</pre>\n<a download="([^"]+)" '
        r'href="data:application/json;base64,([A-Za-z0-9+/=]*)">', text, re.S)]


def _raw(path):
    """A file's bytes, or None where there is no file — a result, so the check
    that reads it fails by name rather than the suite (see _snap)."""
    try:
        with open(path, 'rb') as fh:
            return fh.read()
    except OSError:
        return None


def _note(url, body, raw=None):
    """POST /api/snap/note, with `raw` bytes in place of the JSON when given."""
    req = urllib.request.Request(url + '/api/snap/note',
                                 data=raw if raw is not None else json.dumps(body).encode('utf-8'),
                                 headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode('utf-8') or '{}')


_p, _u, _snaps, _log = _snapper('bundle', {'XDG_RUNTIME_DIR': _wl, 'PATH': _bins['grim']})
try:
    _a, _b, _c = sorted((_snap(_u)[1].get('name') or '?') for _ in range(3))
    _adir = os.path.join(_snaps, _a)
    _reader_text = ('\n' + json.dumps({'v': 1, 'read': {
        'text': '</script><!-- Jimmy John\'s & "Accept" <b>Pverel'}}, indent=2) + '\n')
    with open(os.path.join(_adir, 'reader.json'), 'w', newline='') as _fh:
        _fh.write(_reader_text)
    shutil.copy(_frame, os.path.join(_adir, 'reader.jpg'))

    def _tree(top):
        """Every file under `top`, by its path, with its bytes for all but the log."""
        return sorted((os.path.relpath(os.path.join(d, n), top),
                       None if n == 'server.log' else _raw(os.path.join(d, n)))
                      for d, _x, ns in os.walk(top) for n in ns)

    _home_before = _tree(os.path.dirname(_snaps))
    _st, _hd, _text = _bundle(_u, _a)
    eq('a snap as one file is a download named for the snap, made fresh each time',
       (_st, _hd.get('Content-Type'), _hd.get('Content-Disposition'), _hd.get('Cache-Control')),
       (200, 'text/html; charset=utf-8', 'attachment; filename="%s.html"' % _a, 'no-store'))
    eq('...and kept nowhere on the rig: not a file beside the journal or in a snap changed by it',
       _tree(os.path.dirname(_snaps)) == _home_before, True)
    eq('...holding its pictures inline, byte for byte, the rig\'s screen first',
       [(f, b == _raw(os.path.join(_adir, f))) for f, b in _pictures(_text)],
       [('panel.png', True), ('camera.jpg', True), ('reader.jpg', True)])
    eq('...all three pictures before any record',
       re.findall(r'<(?:figcaption|summary)>([a-z]+\.[a-z]+) — ', _text),
       ['panel.png', 'camera.jpg', 'reader.jpg', 'status.json', 'snap.json', 'reader.json'])
    _recs = _records(_text)
    eq('...and each record shown as its text, exactly, a leading line break and markup '
       'in it included',
       [(f, shown.encode('utf-8') == _raw(os.path.join(_adir, f))) for f, shown, _s, _n in _recs],
       [('status.json', True), ('snap.json', True), ('reader.json', True)])
    eq('...and carried again as the file itself, byte for byte, saved under the snap\'s name',
       [(f, saved == _raw(os.path.join(_adir, f)), name) for f, _t, saved, name in _recs],
       [(f, True, '%s-%s' % (_a, f)) for f in ('status.json', 'snap.json', 'reader.json')])
    # Markup in a record is text in the bundle. Written as it is, `<!--` would
    # open a comment that swallows the rest of the file, and the <pre> above
    # would read back the same here while a browser showed nothing after it.
    eq('...the markup in a record written as text, so nothing in it opens an element',
       ('<b>Pverel' in _text, '&lt;b&gt;Pverel' in _text, '<!-- Jimmy' in _text),
       (False, True, False))
    _refs = re.findall(r'\b(?:src|href)="([^"]*)"', _text)
    eq('...reaching for nothing outside itself: no address, no script, no stylesheet',
       ([r[:40] for r in _refs if not r.startswith(('data:', '#'))],
        re.findall(r'<script|<link|<iframe|url\(|@import', _text, re.I)),
       ([], []))
    eq('...under the line the panel said for it', re.findall(r'<p class="said">([^<]*)</p>', _text),
       ['saved'])

    _st, _hd, _text = _bundle(_u, _c, _a, _b, _a)
    eq('several snaps are one file, oldest first whatever order they were asked in, each once',
       (_st, re.findall(r'<section id="([^"]+)">', _text)), (200, [_a, _b, _c]))
    eq('...named for the first and the last',
       _hd.get('Content-Disposition'), 'attachment; filename="%s_to_%s.html"' % (_a, _c))
    eq('...with a list at the top that leads to each',
       re.findall(r'<li><a href="#([^"]+)">', _text), [_a, _b, _c])

    # --- what a bundle refuses ----------------------------------------------
    _st, _hd, _text = _bundle(_u, raw='')
    eq('a bundle that names no snap is refused, saying how to name one',
       (_st, _text), (400, 'name a snap to bundle: ?snap=<folder>\n'))
    _st, _hd, _text = _bundle(_u, _a, 'not-a-snap')
    eq('a bundle naming one snap the rig does not have is refused whole, saying which',
       (_st, _text), (404, 'no snap named "not-a-snap"\n'))
    # The journal one directory up holds an offer, a folder in snaps/ made by
    # hand holds a picture, and a folder named like a snap is a link out of
    # snaps/ to one that holds a status: what a name in the query would be
    # after. Each is refused before anything is read.
    with open(os.path.join(os.path.dirname(_snaps), 'journal.jsonl'), 'ab') as _fh:
        _fh.write(b'{"v": 1, "id": "secret-offer"}\n')
    os.mkdir(os.path.join(_snaps, 'by-hand'))
    shutil.copy(_pngfile, os.path.join(_snaps, 'by-hand', 'panel.png'))
    _outb = os.path.join(_pdir, 'outside-bundle')
    os.makedirs(_outb)
    with open(os.path.join(_outb, 'status.json'), 'w') as _fh:
        _fh.write('{"secret-offer": true}')
    os.symlink(_outb, os.path.join(_snaps, '2026-01-02_00-00-00'))
    for _q in ('snap=..%2Fjournal.jsonl', 'snap=..', 'snap=.', 'snap=', 'snap=%2Fetc%2Fpasswd',
               'snap=%s%%2F..%%2F..%%2Fjournal.jsonl' % _a, 'snap=%s%%2Fpanel.png' % _a,
               'snap=%2e%2e%2fjournal.jsonl', 'snap=by-hand', 'snap=2026-01-02_00-00-00',
               'snap[]=' + _a):
        _st, _hd, _text = _bundle(_u, raw=_q)
        _inside = b''.join(b for _f, b in _pictures(_text))
        ok_('a bundle of %s is refused (%r)' % (_q, _st),
            _st in (400, 404) and 'secret-offer' not in _text and b'secret-offer' not in _inside
            and 'root:' not in _text)
    # A name that is right and a file in it that is a link: panel.png in a
    # real snap replaced by a link to the journal. Not a snap's file, by the
    # list's rule, so not in the bundle.
    os.remove(os.path.join(_snaps, _b, 'panel.png'))
    os.symlink(os.path.join(os.path.dirname(_snaps), 'journal.jsonl'),
               os.path.join(_snaps, _b, 'panel.png'))
    _st, _hd, _text = _bundle(_u, _b)
    eq('a panel.png that is a link out of the snaps folder is not put in a bundle',
       (_st, [f for f, _x in _pictures(_text)],
        any(b'secret-offer' in x for _f, _t, x, _n in _records(_text))),
       (200, ['camera.jpg'], False))

    # --- a note ---------------------------------------------------------------
    # The limit as the list states it to snaps.html, whose note box is held to
    # it: one figure, read from where the page reads it.
    _max = get(_u, '/api/snaps').get('noteMax') or 0
    ok_('the list says how long a note may be, room for a few words (%r)' % _max, _max >= 20)
    _rec0 = _json_in(_adir, 'snap.json')
    _st, _rep = _note(_u, {'snap': _a, 'note': '  trip planner  '})
    eq('a note is kept, trimmed, and said back', (_st, _rep),
       (200, {'ok': True, 'snap': _a, 'note': 'trip planner'}))
    _rec1 = _json_in(_adir, 'snap.json') or {}
    eq('...in the snap\'s own snap.json, with the rest of it as it was',
       (_rec1.get('note'), dict((k, v) for k, v in _rec1.items() if k != 'note')),
       ('trip planner', _rec0))
    eq('...leaving no temporary beside it', [n for n in os.listdir(_adir) if '.part' in n], [])
    eq('...listed with its snap', _listed(_u, _a).get('note'), 'trip planner')
    _st, _hd, _text = _bundle(_u, _a)
    eq('...and in a bundle of it, in the title and beside the snap\'s name',
       ('<title>📷 Snap %s — trip planner</title>' % _a in _text,
        '<h2>%s <span class="note">— trip planner</span></h2>' % _a in _text), (True, True))
    _note(_u, {'snap': _b, 'note': '<b>after</b> accept & go'})
    _st, _hd, _text = _bundle(_u, _a, _b)
    eq('...a note with markup in it shown as text: beside its snap, in the list at the top, '
       'and in its snap.json',
       (_text.count('&lt;b&gt;after&lt;/b&gt; accept &amp; go'), '<b>after' in _text), (3, False))
    eq('the longest note there is room for is kept',
       _note(_u, {'snap': _a, 'note': 'x' * _max})[0], 200)
    _held = _raw(os.path.join(_adir, 'snap.json'))
    _st, _rep = _note(_u, {'snap': _a, 'note': 'x' * (_max + 1)})
    eq('...and one character more is refused, saying the limit, with the record left as it was',
       (_st, _rep.get('error'), _raw(os.path.join(_adir, 'snap.json')) == _held),
       (400, 'a note is at most %d characters, and this one is %d' % (_max, _max + 1), True))
    for _bad, _what in ((5, 'a number'), (None, 'null'), ('after\naccept', 'two lines'),
                        ('tab\there', 'a tab in it')):
        _st, _rep = _note(_u, {'snap': _a, 'note': _bad})
        eq('a note that is %s is refused, with the record left as it was' % _what,
           (_st, _raw(os.path.join(_adir, 'snap.json')) == _held), (400, True))
    eq('...and so is a press with no note in it at all',
       _note(_u, {'snap': _a})[0], 400)
    eq('...and a body that is not JSON', _note(_u, None, raw=b'trip planner'), (400, {
       'ok': False, 'error': 'bad body'}))
    _st, _rep = _note(_u, {'snap': _a, 'note': '   '})
    eq('a blank note takes the note off',
       (_st, _rep.get('note'), 'note' in (_json_in(_adir, 'snap.json') or {})), (200, None, False))
    # Names that are not snaps: nothing is written anywhere for any of them.
    _shelf_before = sorted(os.listdir(_snaps))
    for _name in ('nope', '../journal.jsonl', '..', 'by-hand', '2026-01-02_00-00-00',
                  _a + '/..', '', None, 5, [_a]):
        _st, _rep = _note(_u, {'snap': _name, 'note': 'x'})
        eq('a note on %r is refused as no snap' % (_name,), (_st, _rep.get('error')),
           (404, 'no snap by that name'))
    eq('...and nothing is written for any of them, in snaps/ or out of it',
       (sorted(os.listdir(_snaps)), os.listdir(os.path.join(_snaps, 'by-hand')),
        os.listdir(_outb)),
       (_shelf_before, ['panel.png'], ['status.json']))
    # Folders the list shows but that have no record it can read: none, a
    # torn one, and one that is a link to a record somewhere else.
    _shelve(_snaps, '2026-01-06_00-00-00')
    _st, _rep = _note(_u, {'snap': '2026-01-06_00-00-00', 'note': 'x'})
    eq('a note on a snap with no snap.json is refused, and none is made for it',
       (_st, _rep.get('error'), os.path.exists(os.path.join(_snaps, '2026-01-06_00-00-00',
                                                            'snap.json'))),
       (409, 'this snap has no snap.json to keep a note in', False))
    _shelve(_snaps, '2026-01-07_00-00-00', {'v': 1, 'at': 1, 'said': 'saved', 'contents': [],
                                            'notes': []}, torn=True)
    _torn_text = _raw(os.path.join(_snaps, '2026-01-07_00-00-00', 'snap.json'))
    _st, _rep = _note(_u, {'snap': '2026-01-07_00-00-00', 'note': 'x'})
    eq('a note on a snap whose snap.json is torn is refused, and the file left as it was',
       (_st, _rep.get('error'), _raw(os.path.join(_snaps, '2026-01-07_00-00-00', 'snap.json'))),
       (409, 'this snap\'s snap.json cannot be read, so there is nowhere to keep a note',
        _torn_text))
    # The link's target says something of its own in every field the list and
    # a bundle take from a record — its line, a note and a part's why — so
    # anything read through the link shows up as itself.
    _shelve(_snaps, '2026-01-08_00-00-00')
    _elsewhere = os.path.join(_pdir, 'a-record-elsewhere.json')
    _elsewhere_text = json.dumps({
        'v': 1, 'at': 1, 'said': 'SAID-FROM-OUTSIDE', 'note': 'NOTE-FROM-OUTSIDE', 'notes': [],
        'contents': [{'what': 'camera', 'file': 'camera.jpg', 'saved': False,
                      'why': 'WHY-FROM-OUTSIDE'}]}).encode('utf-8') + b'\n'
    with open(_elsewhere, 'wb') as _fh:
        _fh.write(_elsewhere_text)
    os.symlink(_elsewhere, os.path.join(_snaps, '2026-01-08_00-00-00', 'snap.json'))
    _st, _rep = _note(_u, {'snap': '2026-01-08_00-00-00', 'note': 'x'})
    eq('a note on a snap whose snap.json is a link is refused, and nothing read or written '
       'through it',
       (_st, _rep.get('error'),
        os.path.islink(os.path.join(_snaps, '2026-01-08_00-00-00', 'snap.json')),
        _raw(_elsewhere) == _elsewhere_text),
       (409, 'this snap has no snap.json to keep a note in', True, True))
    # ...and the list and a bundle of it give the same answer as the note:
    # there is no snap.json here. Read through the link, both carried the
    # target's line, note and why, and the bundle took them off the rig.
    _linked = _listed(_u, '2026-01-08_00-00-00')
    eq('...and the list says it has no snap.json, with nothing from the file the link points at',
       (_linked.get('said'), _linked.get('note'), _linked.get('problems'),
        [f['file'] for f in _linked.get('files') or []]),
       ('no snap.json in this folder, so nothing says what is missing', None, [],
        ['status.json']))
    _st, _hd, _text = _bundle(_u, '2026-01-08_00-00-00')
    eq('...and so does a bundle of it, carrying nothing from that file',
       (_st, re.findall(r'<p class="said">([^<]*)</p>', _text),
        re.findall(r'[A-Z]+-FROM-OUTSIDE', _text)),
       (200, ['no snap.json in this folder, so nothing says what is missing'], []))
finally:
    stop(_p)

# ...and a file that cannot be read by the time its turn comes — a snap pruned
# while the bundle was being built, or a card going bad — is said in its place.
# The reply has already gone out as 200 by then, so the file has to say it.
# Staged the way the torn card is, by failing this server's own fs.readFile
# for camera.jpg before server.js loads — and its fs.rename onto a snap.json,
# which is the last step of keeping a note, for a note that cannot be kept.
_unread = os.path.join(_pdir, 'unreadable.js')
with open(_unread, 'w') as _fh:
    _fh.write("var fs = require('fs');\nvar real = fs.readFile;\n"
              "fs.readFile = function (p) {\n"
              "  if (typeof p === 'string' && /camera\\.jpg$/.test(p)) {\n"
              "    var cb = arguments[arguments.length - 1];\n"
              "    var e = new Error('input/output error'); e.code = 'EIO';\n"
              "    return setImmediate(cb, e);\n"
              "  }\n"
              "  return real.apply(fs, arguments);\n"
              "};\n"
              "var move = fs.rename;\n"
              "fs.rename = function (from, to, cb) {\n"
              "  if (!/snap\\.json$/.test(String(to))) return move.apply(fs, arguments);\n"
              "  var e = new Error('input/output error'); e.code = 'EIO';\n"
              "  return setImmediate(cb, e);\n"
              "};\n"
              # ...and a card that fills while a note's temporary is written,
              # for the one note that says so: half of it written, then ENOSPC.
              "var write = fs.writeFile;\n"
              "fs.writeFile = function (p, data, cb) {\n"
              "  if (!/snap\\.json\\.\\d+\\.\\d+\\.part$/.test(String(p))\n"
              "      || String(data).indexOf('card full') === -1) return write.apply(fs, arguments);\n"
              "  var buf = Buffer.from(data);\n"
              "  return write.call(fs, p, buf.subarray(0, buf.length >> 1), function () {\n"
              "    var e = new Error('no space left on device'); e.code = 'ENOSPC';\n"
              "    cb(e);\n"
              "  });\n"
              "};\n")
_p, _u, _snaps, _log = _snapper('unbundled', {'XDG_RUNTIME_DIR': _wl, 'PATH': _bins['grim'],
                                              'NODE_OPTIONS': '--require ' + _unread})
try:
    _n = _snap(_u)[1].get('name') or '?'
    _st, _hd, _text = _bundle(_u, _n)
    eq('a file that cannot be read when a bundle is made is said in its place, the rest kept',
       (_st, re.findall(r'<p class="lost">([^<]*)</p>', _text),
        [f for f, _x in _pictures(_text)], [f for f, _t, _s, _x in _records(_text)]),
       (200, ['camera.jpg — the camera\'s last picture: could not be read when this file '
              'was made (EIO)'], ['panel.png'], ['status.json', 'snap.json']))
    _ndir = os.path.join(_snaps, _n)
    _held = _raw(os.path.join(_ndir, 'snap.json'))
    _st, _rep = _note(_u, {'snap': _n, 'note': 'after accept'})
    eq('a note that cannot be put in place is said as that, leaving snap.json as it was and '
       'no temporary beside it',
       (_st, _rep.get('error'), _raw(os.path.join(_ndir, 'snap.json')) == _held,
        [x for x in os.listdir(_ndir) if '.part' in x]),
       (500, 'could not keep the note: EIO', True, []))
    _st, _rep = _note(_u, {'snap': _n, 'note': 'card full'})
    eq('...and one whose temporary cannot be written, the same way, leaving no torn temporary',
       (_st, _rep.get('error'), _raw(os.path.join(_ndir, 'snap.json')) == _held,
        [x for x in os.listdir(_ndir) if '.part' in x]),
       (500, 'could not keep the note: ENOSPC', True, []))
finally:
    stop(_p)

# ...and a snap still being kept: it has no snap.json yet and will in a
# moment, which is not the same as a folder that has none, and its screenshot
# can be part way written. A screenshot that takes a second holds the press
# open while the list is read, the note is sent and the snap is bundled — one
# answer from all three, as stillKeeping gives it. The bundle used to be built
# anyway and hand on whatever of the picture was on the card, under "no
# snap.json in this folder".
_p, _u, _snaps, _log = _snapper('notefill', {'XDG_RUNTIME_DIR': _wl, 'PATH': _bins['slow']})
try:
    _pressing = {}
    _pt = threading.Thread(target=lambda: _pressing.update(reply=_snap(_u)))
    _pt.start()
    _filling = None
    for _ in range(200):
        _filling = ([s['name'] for s in get(_u, '/api/snaps')['snaps']] or [None])[0]
        if _filling:
            break
        time.sleep(0.01)
    _st, _rep = _note(_u, {'snap': _filling, 'note': 'offer card'})
    _bst, _bhd, _btext = _bundle(_u, _filling or '?')
    _fsaid = _listed(_u, _filling).get('said')
    # All three asked inside the press, or the checks below are about a snap
    # that had already been kept.
    _out = _pt.is_alive()
    _pt.join()
    eq('a note on a snap still being kept is refused, saying so',
       (_st, _rep.get('error')), (409, 'this snap is still being kept; try again in a moment'))
    eq('...and so is a bundle of it, saying which, whatever of it is on the card by then',
       (_bst, _btext, _out),
       (409, 'snap "%s" is still being kept; try again in a moment\n' % _filling, True))
    eq('...and the list says it is still being kept, not that it has no snap.json',
       _fsaid, 'still being kept, so nothing says yet what is missing')
    _st, _rep = _note(_u, {'snap': _filling, 'note': 'offer card'})
    eq('...and kept once it has been',
       (_st, (_json_in(os.path.join(_snaps, _filling or '?'), 'snap.json') or {}).get('note')),
       (200, 'offer card'))
    _bst, _bhd, _btext = _bundle(_u, _filling or '?')
    eq('...and bundled whole once it has been, under the line the panel said for it',
       (_bst, [(f, b == _raw(os.path.join(_snaps, _filling or '?', f)))
               for f, b in _pictures(_btext)],
        re.findall(r'<p class="said">([^<]*)</p>', _btext)),
       (200, [('panel.png', True), ('camera.jpg', True)],
        [(_pressing.get('reply') or (None, {}))[1].get('said')]))
finally:
    stop(_p)

# ...and a bundle a phone takes slowly, which over the VPN on a phone signal is
# every bundle: the next snap is read once the one before it has gone out, and
# not before. Seen from outside as what a snap removed in the meantime comes
# out as. With the server's "full" ignored, the second snap had been read in
# behind the first, into the Pi's memory, inside the second the phone sat on
# 64kB of it — and came out whole although it was removed after that second.
# The first snap's picture is 16MB, more than the buffers between a server and
# a client that has stopped reading can take (21MB once it is base64).
_p, _u, _snaps, _log = _snapper('slowphone', {'XDG_RUNTIME_DIR': _wl, 'PATH': _bins['grim']})
try:
    _first, _second = sorted((_snap(_u)[1].get('name') or '?') for _ in range(2))
    with open(os.path.join(_snaps, _first, 'panel.png'), 'wb') as _fh:
        _fh.write(os.urandom(16 * 1000 * 1000))
    _held = [f['file'] for f in _listed(_u, _second).get('files') or []]
    _c = http.client.HTTPConnection('127.0.0.1', urllib.parse.urlparse(_u).port, timeout=30)
    try:
        _c.request('GET', '/api/snaps/bundle?snap=%s&snap=%s' % (_first, _second))
        _r = _c.getresponse()
        _got = _r.read(65536)
        time.sleep(1.0)
        shutil.rmtree(os.path.join(_snaps, _second))
        _got += _r.read()
    except Exception as e:
        _got = repr(e).encode('utf-8')
    finally:
        _c.close()
    _text = _got.decode('utf-8', 'replace')
    eq('a bundle taken slowly reads the next snap only once the one before it has gone out, '
       'so one removed meanwhile is said in its place, file by file',
       (re.findall(r'<section id="([^"]+)">', _text),
        re.findall(r'<p class="lost">([a-z]+\.[a-z]+) — [^<]*\((\w+)\)</p>', _text)),
       ([_first, _second], [(f, 'ENOENT') for f in ('panel.png', 'camera.jpg', 'reader.jpg',
                                                     'status.json', 'snap.json', 'reader.json')
                            if f in _held]))
    ok_('...a snap with something in it to lose (%r)' % (_held,), len(_held) >= 3)
finally:
    stop(_p)

# --- ...and the hang pressed at the top, on the deadline nobody set -----------
try:
    _dthread.join(_page_ms / 1000.0 + 5)
    _dcode, _drep = _deadline.get('reply') or (None, {})
    eq('with no deadline set, a tool that hangs is given up on, and says how long it was given',
       (_dcode, _drep.get('ok'), _piece(_drep, 'panel').get('why')),
       (200, True, 'grim did not finish in 8s'))
    ok_('...inside the %gs the panel and 📷 Snaps wait for an answer (%.1fs)'
        % (_page_ms / 1000.0, _deadline.get('took') or -1),
        _dcode == 200 and (_deadline.get('took') or _page_ms) < _page_ms / 1000.0)
finally:
    stop(_dp)

_wsock.close()
shutil.rmtree(_pdir, ignore_errors=True)
shutil.rmtree(_wl, ignore_errors=True)
shutil.rmtree(_nodesk, ignore_errors=True)

# --- the heartbeat's GPS and Pi, relayed -------------------------------------
#
# The scanner puts the GPS's state and the Pi's temperature and throttling on
# its heartbeat. The stream carries a heartbeat whole, which is how tooBright
# and notSaving have always reached the panel; /api/status carried none of it,
# so the status link beside the connection dot — the one place a person
# diagnosing a rig is sent — could not say whether the GPS had a fix. The
# heartbeat is a fact about the process that sent it, so a restarted scanner
# that has not beaten yet has none to report.
_bdir = tempfile.mkdtemp()
_bjournal = os.path.join(_bdir, 'journal.jsonl')
open(_bjournal, 'w').close()
_bfake = os.path.join(_bdir, 'beats.py')
_bonce = os.path.join(_bdir, 'ran-once')
# ...and the newest fix, which the beat now carries inside `gps`: the journal's
# own fields, gps.py's judgement on it, and how long it had left inside the
# staleness rule. Stale here, as it would be on a beat whose word is stale.
# Marietta Square, a public place.
_BFIX = {'lat': 33.9526, 'lon': -84.5499, 'gpsAge': 312.0, 'gpsErr': 12.0,
         'gpsMode': 3, 'gpsOk': False, 'gpsWhy': 'stale', 'freshFor': 0.0}
with open(_bfake, 'w') as fh:
    fh.write(
        'import json, os, sys, time\n'
        'if os.path.exists(%r):\n'
        '    time.sleep(600)\n'
        'open(%r, "w").close()\n'
        'time.sleep(1.5)\n'
        'print(json.dumps({"alive": True, "at": 5, "tooBright": False,\n'
        '    "tooDim": False, "notSaving": None,\n'
        '    "gps": {"state": "stale", "ageSeconds": 312.0, "fix": %s},\n'
        '    "cpuC": 71.4, "cpuCWhy": None,\n'
        '    "throttled": {"now": ["under-voltage"], "sinceBoot": ["under-voltage"]},\n'
        '    "throttledWhy": None, "heatGuard": True}), flush=True)\n'
        'time.sleep(4.0)\n'
        'sys.exit(1)\n' % (_bonce, _bonce, repr(_BFIX)))
_bproc, _bbase = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable,
                        'SCANNER_ARGS': _bfake}, _bjournal)
try:
    _bheard = listen(_bbase, 5.0)
    _bs = None
    for _ in range(100):
        _bs = get(_bbase, '/api/status')
        if _bs.get('beat'):
            break
        time.sleep(0.05)
    _bb = (_bs or {}).get('beat') or {}
    eq('the status carries the heartbeat\'s GPS word and fix age',
       {k: (_bb.get('gps') or {}).get(k) for k in ('state', 'ageSeconds')},
       {'state': 'stale', 'ageSeconds': 312.0})
    # The newest position, with its quality and the gate's answer, on the path
    # the beat already travels: kept whole, not rebuilt from a list of the
    # fields the server knew about when it was written.
    eq('the status carries the beat\'s newest fix with its quality and the '
       'gate\'s answer', (_bb.get('gps') or {}).get('fix'), _BFIX)
    eq('...and the Pi\'s temperature and throttling',
       (_bb.get('cpuC'), _bb.get('throttled')),
       (71.4, {'now': ['under-voltage'], 'sinceBoot': ['under-voltage']}))
    eq('...and the notices that already rode it', _bb.get('notSaving', 'absent'), None)
    # ...and the heat guard's state (scan_pi.HeatGuard), so the status link
    # says whether the reads nobody pressed for are being put off.
    eq('/api/status says whether the heat guard is on', _bb.get('heatGuard', 'absent'), True)
    # An age, never a timestamp — the rule for everything on this endpoint,
    # because whatever reads it does not share this server's clock.
    ok_('...with its own age instead of a timestamp (%r)'
        % ((_bb.get('ageMs'), _bb.get('at')),),
        isinstance(_bb.get('ageMs'), int) and 0 <= _bb['ageMs'] < 10000
        and 'at' not in _bb and 'alive' not in _bb)
    time.sleep(0.5)
    _bstream = [m for m in _bheard if m.get('alive')]
    ok_('the stream carries the same heartbeat to the panel (%d)' % len(_bstream),
        _bstream and (_bstream[0].get('gps') or {}).get('state') == 'stale'
        and _bstream[0].get('cpuC') == 71.4
        and (_bstream[0].get('throttled') or {}).get('now') == ['under-voltage']
        and _bstream[0].get('heatGuard') is True)
    eq('...and the same fix, whole', (_bstream[0].get('gps') or {}).get('fix')
       if _bstream else None, _BFIX)
    # The fake exits four seconds after its beat and is started again; the
    # second run says nothing. What the first one said is not the second's.
    _bgone = None
    for _ in range(300):
        _s = get(_bbase, '/api/status')
        if (_s.get('scanner') or {}).get('fell', 0) >= 1 \
                and (_s.get('scanner') or {}).get('running'):
            _bgone = _s
            break
        time.sleep(0.05)
    ok_('the scanner was restarted', _bgone is not None)
    eq('...and a restarted scanner that has not beaten has no heartbeat to report',
       (_bgone or {}).get('beat', 'absent'), None)
finally:
    stop(_bproc)
    shutil.rmtree(_bdir, ignore_errors=True)

# --- the rig's up rows are carried, and counted as nothing -------------------
#
# Collection only: a start, a stop, a phone gone and a GPS gone stale say when
# the rig was watching, and nothing may read them as offers or fold them into a
# figure. And they have to reach the copy at home, which is what the sync is
# for — a kind this build knows nothing about crosses on its id and seq.
_udir = tempfile.mkdtemp()
_ujournal = os.path.join(_udir, 'journal.jsonl')
_ups = [{'v': 1, 'kind': 'up', 'id': 'up-0f3a9c21b7d4-%d' % (i + 1), 'seq': 1,
         'at': NOW - 5000 + i, 'about': about, 'state': state}
        for i, (about, state) in enumerate([('rig', 'start'), ('gps', 'stale'),
                                            ('phone', 'gone'), ('rig', 'stop')])]
write(_ujournal, [offer(i, NOW - 60000 * (i + 1)) for i in range(3)] + _ups)
_uproc, _ubase = start({'SCANNER': '0'}, _ujournal)
try:
    _uj = get(_ubase, '/api/journal?days=0')
    eq('up rows in the journal are not offers', _uj.get('count'), 3)
    _ut = get(_ubase, '/api/today?since=%d' % (NOW - 3600000))
    eq('...nor counted in the shift line', _ut.get('offers'), 3)
    _uing = json.loads(urllib.request.urlopen(urllib.request.Request(
        _ubase + '/api/journal/ingest',
        data=''.join(json.dumps(dict(r, id=r['id'] + 'x')) + '\n' for r in _ups).encode(),
        headers={'Content-Type': 'application/x-ndjson'}), timeout=10).read().decode())
    eq('the sync carries up rows it has not seen', _uing.get('added'), 4)
    _uing2 = json.loads(urllib.request.urlopen(urllib.request.Request(
        _ubase + '/api/journal/ingest',
        data=''.join(json.dumps(r) + '\n' for r in _ups).encode(),
        headers={'Content-Type': 'application/x-ndjson'}), timeout=10).read().decode())
    eq('...and recognises the ones it has', _uing2.get('added'), 0)
finally:
    stop(_uproc)
    shutil.rmtree(_udir, ignore_errors=True)

# --- what the scanner printed, and why it stopped -----------------------------
#
# Every chunk of the scanner's stderr used to be stored as `scanner.error`. The
# 📷 Snap of 15:45 on 8 Oct has `running: true` beside an error of "Error in
# boxClipToRectangle: box outside rectangle Error in pixScanForForeground:
# invalid box" — leptonica, inside tesseract, narrating a crop while the
# scanner went on reading. The panel shows `error` as the reason a scanner is
# not running, so a crash that said nothing would have been blamed on whatever
# a library last muttered.
#
# Four runs of one stand-in, each the shape of a real one: a library warning
# the loop reads on past and then a silent exit; a crash, whose traceback is
# the last thing it says; a fresh start; and a wedge the watchdog kills. The
# silence window is short so the wedge takes a second and a half, and every
# run beats well inside it.
_edir = tempfile.mkdtemp()
_ejournal = os.path.join(_edir, 'journal.jsonl')
open(_ejournal, 'w').close()
_efake = os.path.join(_edir, 'talks.py')
_eruns = os.path.join(_edir, 'runs')
_LEPTONICA = ('Error in boxClipToRectangle: box outside rectangle\n'
              'Error in pixScanForForeground: invalid box\n')
with open(_efake, 'w') as fh:
    fh.write(
        'import json, os, sys, time\n'
        'n = int(open(%r).read() or 0) + 1 if os.path.exists(%r) else 1\n'
        'open(%r, "w").write(str(n))\n'
        'def beat():\n'
        '    print(json.dumps({"alive": True, "at": 1}), flush=True)\n'
        'if n == 1:\n'
        '    sys.stderr.write(%r)\n'
        '    sys.stderr.flush()\n'
        '    for _ in range(6):\n'
        '        time.sleep(0.3)\n'
        '        beat()\n'
        '    time.sleep(0.3)\n'
        '    os._exit(3)\n'
        'elif n == 2:\n'
        '    beat()\n'
        '    time.sleep(0.3)\n'
        '    raise RuntimeError("camera gone")\n'
        'elif n == 3:\n'
        '    time.sleep(1.0)\n'
        '    beat()\n'
        '    time.sleep(0.3)\n'
        '    beat()\n'
        'time.sleep(600)\n' % (_eruns, _eruns, _eruns, _LEPTONICA))
_eproc, _ebase = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable,
                        'SCANNER_ARGS': _efake, 'SCANNER_SILENT_MS': '1500'},
                       _ejournal)


def _escanner(until, limit=20.0):
    end = time.time() + limit
    while time.time() < end:
        _s = get(_ebase, '/api/status').get('scanner') or {}
        if until(_s):
            return _s
        time.sleep(0.05)
    return {}


try:
    _talk = _escanner(lambda s: s.get('running') and s.get('stderr'))
    eq('a running scanner\'s stderr is kept, as what it printed',
       _talk.get('stderr'), _LEPTONICA.strip().replace('\n', ' '))
    eq('...and is not its error while it goes on reading', _talk.get('error', 'absent'),
       None)
    _quiet = _escanner(lambda s: s.get('fell', 0) >= 1 and not s.get('running'))
    eq('a scanner that read on past a warning and then exited says it exited',
       _quiet.get('error'), 'exited (3)')
    no_('...and the warning is not given as the reason (%r)' % _quiet.get('error'),
        'boxClipToRectangle' in (_quiet.get('error') or ''))
    ok_('...though it is still kept as what it printed',
        'boxClipToRectangle' in (_quiet.get('stderr') or ''))
    _crash = _escanner(lambda s: s.get('fell', 0) >= 2 and not s.get('running'))
    ok_('a crash\'s traceback, the last thing it said, is its error (%r)'
        % _crash.get('error'),
        (_crash.get('error') or '').startswith('exited (1): ')
        and 'RuntimeError: camera gone' in (_crash.get('error') or ''))
    _fresh = _escanner(lambda s: s.get('fell', 0) >= 2 and s.get('running'))
    eq('a restarted scanner has no error and nothing printed yet',
       (_fresh.get('error', 'absent'), _fresh.get('stderr', 'absent')), (None, None))
    _wedge = _escanner(lambda s: s.get('wedged', 0) >= 1 and not s.get('running'))
    ok_('a scanner the watchdog killed keeps the watchdog\'s account of it (%r)'
        % _wedge.get('error'),
        'stopped reporting' in (_wedge.get('error') or ''))
finally:
    stop(_eproc)
    shutil.rmtree(_edir, ignore_errors=True)

# --- the NucBox's search and router, relayed ---------------------------------
#
# server.js relays two questions to the NucBox at home and nothing else. The
# NucBox here is tests/fake-nucbox.js — the one fake the three suites share —
# answering in the real install's shapes (Nominatim 4.5 jsonv2, OSRM route),
# and it lists what it was asked at /__asked, so these checks read exactly what
# left the rig rather than what the server says it sent.
_fake = subprocess.Popen(['node', os.path.join(ROOT, 'tests', 'fake-nucbox.js')],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
_fake_base = 'http://127.0.0.1:%d' % json.loads(_fake.stdout.readline())['port']


def _asked():
    return json.loads(urllib.request.urlopen(_fake_base + '/__asked', timeout=5).read())


def _nbx(base, path):
    s, body, _h = raw(base, path)
    try:
        return s, json.loads(body)
    except ValueError:
        return s, body


_ndir = tempfile.mkdtemp()
_nj = os.path.join(_ndir, 'journal.jsonl')
open(_nj, 'w').close()
try:
    # Nothing set: the ordinary install, and today. The page asks /api/nbx
    # first and does what it always did on this answer.
    _p0, _b0 = start({'SCANNER': '0'}, _nj)
    try:
        _before = len(_asked())
        eq('with no NucBox set, /api/nbx says none is set',
           get(_b0, '/api/nbx'), {'ok': True, 'search': False, 'route': False,
                                  'streets': False})
        _s, _r = _nbx(_b0, "/api/nbx/search?q=McDonald%27s")
        eq('...and a search is refused as not set here, not as unreachable',
           (_s, _r.get('configured'), _r.get('unreachable')), (404, False, None))
        _s, _r = _nbx(_b0, '/api/nbx/route?points=-84.5499,33.9526;-84.3880,33.7490')
        eq('...and so is a route', (_s, _r.get('configured')), (404, False))
        _s, _r = _nbx(_b0, '/api/nbx/cross?a=Foxglove%20Trl&b=Northgate%20Dr')
        eq('...and so is where two streets meet, naming the setting',
           (_s, _r.get('configured'), _r.get('error')),
           (404, False, 'no NucBox street index is set on this machine (NUCBOX_STREETS)'))
        eq('...and nothing at all reached a NucBox', len(_asked()), _before)
    finally:
        stop(_p0)
    # A setting that is not an http(s) URL is said and ignored, never tried.
    _p0, _b0 = start({'SCANNER': '0', 'NUCBOX_SEARCH': 'ftp://127.0.0.1:8088'}, _nj)
    try:
        eq('a NUCBOX_SEARCH that is not an http(s) URL is treated as unset',
           get(_b0, '/api/nbx')['search'], False)
    finally:
        stop(_p0)

    _p1, _b1 = start({'SCANNER': '0', 'NUCBOX_SEARCH': _fake_base,
                      'NUCBOX_ROUTER': _fake_base + '/', 'NUCBOX_STREETS': _fake_base,
                      'NUCBOX_TIMEOUT_MS': '800'}, _nj)
    try:
        eq('with all three set, /api/nbx says all three are',
           get(_b1, '/api/nbx'), {'ok': True, 'search': True, 'route': True,
                                  'streets': True})
        # The real install's own question: McDonald's in a box round Marietta.
        _s, _r = _nbx(_b1, "/api/nbx/search?q=McDonald%27s&viewbox=-84.65,34.04,-84.45,33.87")
        _hits = _r.get('hits') or []
        eq('a chain search answers the branches inside the box, bounded',
           (_s, len(_hits)), (200, 2))
        eq('...each as where it is, what it is called, what kind of thing it is and its own '
           'name (the held end\'s place, map-view.js pickPlace), and nothing else',
           sorted(set(k for h in _hits for k in h)), ['called', 'kind', 'lat', 'lon', 'name'])
        eq('...and a list shorter than the limit is said to be whole',
           sorted(_r.keys()) + [_r.get('cutAt')], ['cutAt', 'hits', 'ok', None])
        ok_('...with its house number and street, as the real install answered',
            "McDonald's, 2700, Windy Hill Road Southeast, Cumberland" in
            ' '.join(h['name'] for h in _hits))
        _last = _asked()[-1]
        eq('...asked of the NucBox with ten candidates, jsonv2, bounded — set '
           'here, not by the page',
           _last, '/search?format=jsonv2&limit=10&q=McDonald%27s'
                  '&viewbox=-84.65%2C34.04%2C-84.45%2C33.87&bounded=1')
        # A street, with no town — the page never sends one, and nothing
        # here adds one.
        _s, _r = _nbx(_b1, '/api/nbx/search?street=Shadowood%20Pkwy%20SE'
                           '&viewbox=-84.65,34.04,-84.45,33.87')
        eq('a street search finds the two pieces of Shadowood Parkway, in '
           'Cumberland', [h['name'].split(', ')[1] for h in _r.get('hits') or []],
           ['Cumberland', 'Cumberland'])
        eq('...asked as street= alone, no city, no town', _asked()[-1],
           '/search?format=jsonv2&limit=10&street=Shadowood%20Pkwy%20SE'
           '&viewbox=-84.65%2C34.04%2C-84.45%2C33.87&bounded=1')
        # Twelve branches, ten asked for: the list stopped at the limit, and
        # says so, so the page cannot read "only one fits" off a cut list.
        _s, _r = _nbx(_b1, '/api/nbx/search?q=Starbucks&viewbox=-84.62,34.01,-84.48,33.90')
        eq('a search that stops at the limit says where it was cut (cutAt 10)',
           (_s, len(_r.get('hits') or []), _r.get('cutAt')), (200, 10, 10))
        # The same question twice is asked of the NucBox once.
        _n = len(_asked())
        _nbx(_b1, "/api/nbx/search?q=McDonald%27s&viewbox=-84.65,34.04,-84.45,33.87")
        eq('the same search a second time is answered from the cache', len(_asked()), _n)

        # The route the driver measured on the real install.
        _s, _r = _nbx(_b1, '/api/nbx/route?points=-84.5499,33.9526;-84.3880,33.7490')
        eq('a route answers the road metres OSRM gave (31307.4 m on the real '
           'install), how far it moved each point to reach a road, and the '
           'road\'s shape to draw as [lat, lon]',
           (_s, _r), (200, {'ok': True, 'metres': 31307.4, 'snaps': [3.1, 3.1],
                            'line': [[33.9526, -84.5499], [33.9526, -84.388],
                                     [33.749, -84.388]], 'duration': 1659.8}))
        no_('...and the router\'s own duration in seconds, the owner\'s decision of 20 Oct '
            '2026, and nothing else of time: no weight, no minutes',
            re.search(r'second|minute|weight', json.dumps(_r)))
        eq('...asked for the simplified shape as GeoJSON, fixed here, the points '
           'as the page wrote them',
           _asked()[-1], '/route/v1/driving/-84.5499,33.9526;-84.3880,33.7490'
                         '?overview=simplified&geometries=geojson')
        _s, _r = _nbx(_b1, '/api/nbx/route?points=-84.5499,33.9526;-84.5400,33.9600;'
                           '-84.5300,33.9700;-84.5200,33.9800;-84.5100,33.9900')
        eq('a route of five points (the car and two orders\' four stops) is relayed, with '
           'its duration', (_s, _r.get('ok'), len(_r.get('snaps') or []),
                            isinstance(_r.get('duration'), (int, float))), (200, True, 5, True))
        _s, _r = _nbx(_b1, '/api/nbx/route?points=-84.5499,33.9526;-84.3880,33.7490'
                           '&overview=full')
        eq('...and the page cannot choose the shape: any other parameter is refused',
           (_s, _r.get('error')), (400, 'refused: overview'))
        _s, _r = _nbx(_b1, '/api/nbx/route?points=-84.5499,33.9526;-84.7,33.9')
        ok_('a route whose shape is not one keeps its metres and sends no line: the '
            'page draws it straight (%r)' % (_r,),
            _s == 200 and isinstance(_r.get('metres'), (int, float)) and _r.get('line') is None)
        _s, _r = _nbx(_b1, '/api/nbx/route?points=-84.5499,33.9526;-84.5499,33.9830;'
                           '-84.3880,33.7490')
        ok_('...and three points is a route too (%r)' % (_r,),
            _s == 200 and isinstance(_r.get('metres'), (int, float)))
        # OSRM's own "no road between these" is HTTP 400 with code NoRoute: an
        # answer about the points, not a NucBox that failed.
        _s, _r = _nbx(_b1, '/api/nbx/route?points=-84.5499,33.9526;-84.5560,34.0010')
        eq('the router saying there is no road is an answer, not unreachable',
           (_s, _r.get('ok'), _r.get('noRoute'), _r.get('unreachable')),
           (200, False, True, None))
        # ...and ONLY NoRoute. OSRM sends its other refusals the same way, as
        # HTTP 400 with a string code; those are the router not answering —
        # said as unreachable and never kept, so the next press asks again.
        _n = len(_asked())
        _s, _r = _nbx(_b1, '/api/nbx/route?points=-84.5499,33.9526;-84.6,34.1')
        eq('a router refusing the question with a code that is not NoRoute is '
           'down, not "no road"', (_s, _r.get('unreachable'), _r.get('noRoute'), _r.get('error')),
           (502, True, None, 'the NucBox router answered InvalidQuery, not a route'))
        _nbx(_b1, '/api/nbx/route?points=-84.5499,33.9526;-84.6,34.1')
        eq('...and is not cached: asked twice, the router was asked twice',
           len(_asked()), _n + 2)

        # The street index, on the NucBox's own server.js: where two streets
        # meet, and the stretch of one, each inside a box.
        _s, _r = _nbx(_b1, '/api/nbx/cross?a=Foxglove%20Trl&b=Northgate%20Dr'
                           '&box=-84.6,34.0,-84.5,33.9')
        eq('where two streets meet is relayed, as the corners and the names it '
           'matched and nothing else',
           (_s, sorted(_r.keys()), _r.get('meets')),
           (200, ['a', 'b', 'cutAt', 'meets', 'ok'],
            [{'lat': 33.96, 'lon': -84.55, 'n': 1, 'spanM': 0, 'shared': True}]))
        eq('...asked of the NucBox at its own path with the same three parameters',
           _asked()[-1], '/api/streets/cross?a=Foxglove%20Trl&b=Northgate%20Dr'
                         '&box=-84.6%2C34.0%2C-84.5%2C33.9')
        _s, _r = _nbx(_b1, '/api/nbx/stretch?name=Larkspur%20Pkwy%20SE')
        eq('the stretch of a street is relayed, its lines and nothing else, with no '
           'box when none is asked', (_s, sorted(_r.keys()), _asked()[-1]),
           (200, ['cutAt', 'how', 'lines', 'names', 'ok'],
            '/api/streets/stretch?name=Larkspur%20Pkwy%20SE'))
        # All or nothing: one meeting that is not a point refuses the answer,
        # because "only one fits" cannot be said of a list with one dropped.
        _n = len(_asked())
        for _which, _q in (('cross', 'a=Bad%20Street&b=X'), ('stretch', 'name=Bad%20Street')):
            _s, _r = _nbx(_b1, '/api/nbx/%s?%s' % (_which, _q))
            ok_('an answer with one %s point that is not a point is the NucBox not '
                'answering, not a shorter list (%r)' % (_which, _r),
                _s == 502 and _r.get('unreachable') is True
                and 'street index answered something that is not' in _r.get('error', ''))
        _nbx(_b1, '/api/nbx/cross?a=Bad%20Street&b=X')
        eq('...and is not cached', len(_asked()), _n + 3)
        _t0 = time.time()
        _s, _r = _nbx(_b1, '/api/nbx/cross?a=Slow%20Street&b=X')
        eq('a street index slower than NUCBOX_TIMEOUT_MS is reported unreachable',
           (_s, _r.get('unreachable'), _r.get('error')),
           (502, True, 'the NucBox did not answer within 0.8 s'))
        ok_('...after the timeout, not after the NucBox (%.1fs)' % (time.time() - _t0),
            time.time() - _t0 < 2.0)

        # Not an open proxy: every other parameter, path and shape is refused,
        # by name, and none of them reaches the NucBox.
        _n = len(_asked())
        for _path, _want in (
                ("/api/nbx/search?q=McDonald%27s&limit=50", 'refused: limit'),
                ("/api/nbx/search?q=McDonald%27s&format=xml", 'refused: format'),
                ("/api/nbx/search?q=McDonald%27s&bounded=0", 'refused: bounded'),
                ('/api/nbx/search?q=a&street=b', 'one of q or street'),
                ('/api/nbx/search?q=a&q=b', 'given more than once: q'),
                ('/api/nbx/search', 'one of q or street'),
                ('/api/nbx/search?q=' + 'x' * 121, 'q must be 1 to 120'),
                ('/api/nbx/search?q=a&viewbox=1,2,3', 'viewbox is'),
                ('/api/nbx/search?q=a&viewbox=-84.6,34,-84.4,9999', 'viewbox is'),
                ('/api/nbx/route?points=-84.5,33.9', 'points is two to five'),
                ('/api/nbx/route?points=-84.5,33.9;-84.4,33.8;-84.3,33.7;-84.2,33.6;'
                 '-84.1,33.5;-84.0,33.4', 'points is two to five'),
                ('/api/nbx/route?points=-84.5,33.9;../../etc', 'points is two to five'),
                ('/api/nbx/route?points=-84.5,33.9;-84.4,33.8&alternatives=true',
                 'refused: alternatives'),
                ('/api/nbx/table?points=-84.5,33.9;-84.4,33.8', 'no such NucBox endpoint'),
                ('/api/nbx/cross?a=x&b=y&limit=5', 'refused: limit'),
                ('/api/nbx/cross?a=x&a=y&b=z', 'given more than once: a'),
                ('/api/nbx/cross?a=x', 'a and b must each be'),
                ('/api/nbx/cross?a=x&b=' + 'y' * 121, 'a and b must each be'),
                ('/api/nbx/cross?a=x&b=y&box=-84.6,34,-84.4', 'box is left,top,right,bottom'),
                ('/api/nbx/cross?a=x&b=y&viewbox=-84.6,34,-84.4,33.9', 'refused: viewbox'),
                ('/api/nbx/stretch?name=x&a=y', 'refused: a'),
                ('/api/nbx/stretch?street=x', 'refused: street'),
                ('/api/nbx/streets?name=x', 'no such NucBox endpoint'),
                ('/api/nbx/../search?q=a', None)):
            _s, _r = _nbx(_b1, _path)
            ok_('the relay refuses %s (%r)' % (_path[:60], _r),
                _s in (400, 404) and (_want is None or _want in str(_r.get('error', ''))))
        eq('...and not one of those reached the NucBox', len(_asked()), _n)
        try:
            urllib.request.urlopen(urllib.request.Request(
                _b1 + '/api/nbx/search?q=a', data=b'{}', method='POST'), timeout=5)
            _s = 200
        except urllib.error.HTTPError as e:
            _s = e.code
        eq('...and it answers GET only', _s, 405)

        # A NucBox that does not answer in time is said, with the time.
        _t0 = time.time()
        _s, _r = _nbx(_b1, '/api/nbx/search?q=Slow%20Place')
        eq('a NucBox slower than NUCBOX_TIMEOUT_MS is reported unreachable',
           (_s, _r.get('unreachable'), _r.get('error')),
           (502, True, 'the NucBox did not answer within 0.8 s'))
        ok_('...after the timeout, not after the NucBox (%.1fs)' % (time.time() - _t0),
            time.time() - _t0 < 2.0)
        _n = len(_asked())
        _nbx(_b1, '/api/nbx/search?q=Slow%20Place')
        eq('...and that is not cached: the next press asks again', len(_asked()), _n + 1)
    finally:
        stop(_p1)

    # One that is not there at all.
    _dead = free_port()
    _p2, _b2 = start({'SCANNER': '0', 'NUCBOX_SEARCH': 'http://127.0.0.1:%d' % _dead,
                      'NUCBOX_ROUTER': 'http://127.0.0.1:%d' % _dead}, _nj)
    try:
        _s, _r = _nbx(_b2, "/api/nbx/search?q=McDonald%27s")
        eq('a NucBox that is not there is said plainly, with the reason',
           (_s, _r.get('unreachable'), _r.get('error')),
           (502, True, 'the NucBox did not answer (ECONNREFUSED)'))
        _s, _r = _nbx(_b2, '/api/nbx/route?points=-84.5499,33.9526;-84.3880,33.7490')
        eq('...and so is its router', (_s, _r.get('unreachable')), (502, True))
    finally:
        stop(_p2)

    # The real thing at both ends: the exporter's index of the synthetic
    # streets (tests/fixtures/streets.opl), loaded by a NucBox's server.js,
    # relayed by a rig's.
    _idx = os.path.join(_ndir, 'streets.json')
    subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'street_index.py'),
                    os.path.join(ROOT, 'tests', 'fixtures', 'streets.osm'), _idx,
                    '--opl', os.path.join(ROOT, 'tests', 'fixtures', 'streets.opl')],
                   check=True, capture_output=True)
    _pn, _bn = start({'SCANNER': '0', 'NUCBOX_STREETS_FILE': _idx}, _nj)
    _pr, _br = start({'SCANNER': '0', 'NUCBOX_STREETS': _bn}, _nj)
    try:
        _s, _r = _nbx(_br, '/api/nbx/cross?a=Foxglove%20Tri&b=Northgate%20Dr'
                           '&box=-84.6,34.0,-84.5,33.9')
        eq("a rig relaying to a NucBox's own index answers where the two streets "
           'meet, the misread "Tri" matched as Trail',
           (_s, _r.get('a'), _r.get('meets')),
           (200, {'names': ['Foxglove Trail'], 'how': 'ocr'},
            [{'lat': 33.96, 'lon': -84.55, 'n': 1, 'spanM': 0, 'shared': True}]))
        _s, _r = _nbx(_br, '/api/nbx/stretch?name=Larkspur%20Pkwy%20SE'
                           '&box=-84.56,33.95,-84.54,33.94')
        eq('...and the stretch of a street inside the box, cut at its edge',
           (_s, [_l[0] for _l in _r.get('lines') or []]), (200, [[33.948, -84.56]]))
    finally:
        stop(_pr)
        stop(_pn)

    # One that never ACCEPTS: a listener whose backlog is full, so the
    # connect itself never completes — the shape of a NucBox whose Tailscale
    # address routes nowhere. The fake above accepts and then stalls, which
    # a socket's idle timer catches; this is the case it did not. Measured
    # before the fix, with NUCBOX_TIMEOUT_MS 500: Node 22 answered at
    # 5009 ms (its global agent's own socket timeout), and an Agent of Node
    # 18's kind was still waiting at 15021 ms. Asked here with its own long
    # client timeout, so a server that hangs fails the checks by name
    # rather than throwing out of the suite.
    _hole = socket.socket()
    _hole.bind(('127.0.0.1', 0))
    _hole.listen(0)
    _fill = []
    for _ in range(4):
        _c = socket.socket()
        _c.setblocking(False)
        try:
            _c.connect(_hole.getsockname())
        except (BlockingIOError, OSError):
            pass
        _fill.append(_c)
    _hole_url = 'http://127.0.0.1:%d' % _hole.getsockname()[1]
    _p3, _b3 = start({'SCANNER': '0', 'NUCBOX_SEARCH': _hole_url, 'NUCBOX_ROUTER': _hole_url,
                      'NUCBOX_TIMEOUT_MS': '800'}, _nj)
    try:
        def _slow_ask(path):
            t0 = time.time()
            try:
                with urllib.request.urlopen(_b3 + path, timeout=30) as r:
                    out = (r.status, json.loads(r.read().decode('utf-8')))
            except urllib.error.HTTPError as e:
                out = (e.code, json.loads(e.read().decode('utf-8')))
            except Exception as e:  # a hang past 30 s, said as the check's failure
                out = (None, {'error': repr(e)})
            return out, time.time() - t0
        (_s, _r), _took = _slow_ask("/api/nbx/search?q=McDonald%27s")
        eq('a NucBox that never accepts the connection is reported unreachable '
           'within NUCBOX_TIMEOUT_MS',
           (_s, _r.get('unreachable'), _r.get('error')),
           (502, True, 'the NucBox did not answer within 0.8 s'))
        ok_('...after the timeout, connecting included (%.2fs)' % _took, _took < 2.0)
        (_s, _r), _took = _slow_ask('/api/nbx/route?points=-84.5499,33.9526;-84.3880,33.7490')
        ok_('...and so is its router (%r, %.2fs)' % (_s, _took),
            _s == 502 and _r.get('unreachable') is True and _took < 2.0)
    finally:
        stop(_p3)
        for _c in _fill:
            _c.close()
        _hole.close()
finally:
    _fake.kill()
    shutil.rmtree(_ndir, ignore_errors=True)

# --- the GPS drop: at the held order's door, then gone from it --------------
#
# The driver: "It can be safe to assume I have completed the order if I am at
# the customer's address." server.js puts the order down — the same putDown()
# Drop runs, its row marked `by: 'gps'` — once a door-level pin of the held end
# is on the hold (POST /api/held-end, from Map view), the car has been inside
# ARRIVE_M of it for the dwell (GPS_DWELL_MS, one second here), and then two
# good fixes put it past LEAVE_M (300 m). Every case below is one way that must
# NOT drop, or the one way that must, once.
#
# A scanner of its own that sends heartbeats on cue: the suite writes
# `beats-N.json` (a list of fixes, one beat each, a quarter second apart) and
# waits for `done-N`; an entry {"_line": {...}} is sent as that line instead,
# for a ⌖ read in the middle of a hold. Coordinates invented, in open country.
_gdir = tempfile.mkdtemp()
_gjournal = os.path.join(_gdir, 'offers.jsonl')
open(_gjournal, 'w').close()
_gfake = os.path.join(_gdir, 'beats.py')
# (kept as text too: the finishing checks at the end give it a directory of its own)
_FSCAN_SRC = (
        'import json, os, sys, time\n'
        'd = os.path.dirname(os.path.abspath(__file__))\n'
        'q = os.path.join(d, "next")\n'
        'n = int(open(q).read()) if os.path.exists(q) else 0\n'
        'end = time.time() + 600\n'
        'while time.time() < end:\n'
        '    p = os.path.join(d, "beats-%d.json" % n)\n'
        '    if not os.path.exists(p):\n'
        '        time.sleep(0.05)\n'
        '        continue\n'
        '    for fix in json.load(open(p)):\n'
        '        if "_line" in fix:\n'
        '            print(json.dumps(fix["_line"]), flush=True)\n'
        '        else:\n'
        '            print(json.dumps({"alive": True, "at": int(time.time() * 1000),\n'
        '                "gps": {"state": "ok", "ageSeconds": 0.1, "fix": fix}}), flush=True)\n'
        '        time.sleep(0.25)\n'
        '    open(os.path.join(d, "done-%d" % n), "w").close()\n'
        '    n += 1\n'
        '    open(q, "w").write(str(n))\n')
with open(_gfake, 'w') as _fh:
    _fh.write(_FSCAN_SRC)
_PIN = (33.9000, -84.5000)
_DOOR = '4821 Kestrel Dr, Marietta'
_seq = [0]


def _fix(dlat, ok=True, fresh=10.0, err=25.0, age=0.1):
    return {'lat': _PIN[0] + dlat, 'lon': _PIN[1], 'gpsAge': age, 'gpsErr': err,
            'gpsMode': 3, 'gpsOk': ok, 'gpsWhy': None if ok else 'rough',
            'freshFor': fresh}


_IN = 0.0003      # ~33 m north of the door
_MID = 0.0018     # ~200 m: out of the door's circle, not yet 300 m away
_FAR = 0.005      # ~556 m


def _beats(fixes):
    """Send these as heartbeats and wait until the last one has been read."""
    n = _seq[0]
    _seq[0] += 1
    path = os.path.join(_gdir, 'beats-%d.json' % n)
    with open(path + '.tmp', 'w') as fh:
        json.dump(fixes, fh)
    os.rename(path + '.tmp', path)
    for _ in range(400):
        if os.path.exists(os.path.join(_gdir, 'done-%d' % n)):
            break
        time.sleep(0.05)
    time.sleep(0.2)


def _took(base, oid, dropoff=_DOOR, multi=False):
    # One customer, as every offer line from a current scanner says it
    # (`multiOrder`): only such a card arms the GPS drop (notOneCustomer).
    post(base, '/api/offers/mark', {
        'id': oid, 'accepted': True,
        'offer': {'id': oid, 'pay': 12.0, 'minutes': 40.0, 'billedMinutes': 40.0,
                  'miles': 5.0, 'cost': 1.75, 'dropoff': dropoff, 'multiOrder': multi}})
    return (get(base, '/api/status').get('holding') or {})


def _pin(base, held, dropoff=_DOOR, name='4821, Kestrel Drive, Marietta, Cobb County'):
    return post(base, '/api/held-end', {
        'holdId': held.get('holdId'), 'dropoff': dropoff, 'lat': _PIN[0],
        'lon': _PIN[1], 'name': name, 'doorLevel': True})


def _drops(oid):
    rows = [json.loads(l) for l in open(_gjournal) if l.strip()]
    return [r for r in rows if r.get('kind') == 'drop' and r.get('id') == oid]


def _holding(base):
    return get(base, '/api/status').get('holding')


_GENV = {'SCANNER': '1', 'SCANNER_CMD': sys.executable,
         'SCANNER_ARGS': _gfake, 'GPS_DWELL_MS': '1000'}
_DWELL = [_fix(_IN)] * 7          # 1.5 s inside
_LEAVE = [_fix(_FAR)] * 3
_gp, _gb = start(_GENV, _gjournal)
try:
    # A fix the gate refused never counts, however long it sits at the door.
    _h = _took(_gb, 'g-gate')
    eq('[gps drop] a door-level pin for the order in the car is kept',
       _pin(_gb, _h)[0], 200)
    _beats([_fix(_IN, ok=False)] * 7 + [_fix(_FAR, ok=False)] * 3)
    ok_('[gps drop] fixes the gate refused never arrive nor leave', _holding(_gb))
    # ...nor does one past gps.py's staleness rule (freshFor 0).
    _beats([_fix(_IN, fresh=0.0)] * 7 + [_fix(_FAR, fresh=0.0)] * 3)
    ok_('[gps drop] a stale fix never counts', _holding(_gb))
    # Driving past: inside for half a second, then gone.
    _beats([_fix(_IN)] * 2 + _LEAVE)
    ok_('[gps drop] passing by the door without dwelling does not drop', _holding(_gb))
    # Stopped at the door, and still there — or a little way along the street.
    _ev = listen(_gb, 4)
    time.sleep(0.3)
    _beats(_DWELL)
    ok_('[gps drop] dwelling at the door is an arrival', (_holding(_gb) or {}).get('arrived'))
    # ...said on the beat itself, which is the panel's only word of it
    # ("at dropoff"): /api/status above is not what live.html listens to.
    ok_('[gps drop] ...and the beat that arrives tells the panel the car is at the dropoff',
        any(m.get('atDropoff') is True for m in _ev if m.get('alive')))
    _beats([_fix(_MID)] * 4)
    ok_('[gps drop] dwelling then staying near does not drop', _holding(_gb))
    # One good fix out past 300 m, then near again: not a departure. It takes
    # LEAVE_FIXES (two) in a row, so one stray fix cannot end the order.
    _beats([_fix(_FAR)] + [_fix(_MID)] * 2)
    ok_('[gps drop] one fix past 300 m between near ones does not drop: it takes two '
        'in a row', _holding(_gb))
    # Gone: two fixes past 300 m.
    _beats(_LEAVE)
    no_('[gps drop] dwelling then leaving puts the order down', _holding(_gb))
    _beats(_LEAVE)
    eq('[gps drop] ...exactly once, as a drop row marked by the GPS',
       [(r.get('by'), r.get('seq') == r.get('at'), 'acceptedAt' in r)
        for r in _drops('g-gate')], [('gps', True, True)])

    # A pin that is not a door is refused, and with none the GPS never drops.
    _h = _took(_gb, 'g-street', dropoff='Kestrel Dr, Marietta')
    eq('[gps drop] a street-level end is refused',
       _pin(_gb, _h, dropoff='Kestrel Dr, Marietta', name='Kestrel Drive, Marietta'),
       (409, {'ok': False, 'error': 'not door level'}))
    _h = _took(_gb, 'g-street2')
    eq('[gps drop] ...and so is a door the answer does not carry',
       _pin(_gb, _h, name='Kestrel Drive, Marietta')[1].get('error'), 'not door level')
    _beats(_DWELL + _LEAVE)
    ok_('[gps drop] an end that is not door-level never drops', _holding(_gb))
    post(_gb, '/api/delivered', {})

    # A card for two customers ("Drop off 2 orders", a batched trip) is one
    # order with two doors: the car stops at the first and leaves for the
    # second with the order still half in the car. Only a card that says one
    # customer arms (notOneCustomer) — and one too old to say does not either.
    _h = _took(_gb, 'g-two', multi=True)
    _pin(_gb, _h)
    _beats(_DWELL + _LEAVE)
    eq('a two-customer card\'s first door does not put it down',
       (bool(_holding(_gb)), _drops('g-two')), (True, []))
    eq('...and the panel is told why the GPS drop is not armed',
       {k: (_holding(_gb) or {}).get(k) for k in ('endPinned', 'endWhy')},
       {'endPinned': True, 'endWhy': 'two customers'})
    post(_gb, '/api/delivered', {})
    _h = _took(_gb, 'g-unsaid', multi=None)
    _pin(_gb, _h)
    _beats(_DWELL + _LEAVE)
    eq('...nor does a card that never said how many customers',
       (bool(_holding(_gb)), _drops('g-unsaid'), (_holding(_gb) or {}).get('endWhy')),
       (True, [], 'customer count unread'))
    post(_gb, '/api/delivered', {})

    # A pin made for the previous order is refused.
    _old = _took(_gb, 'g-old')
    post(_gb, '/api/delivered', {})
    _took(_gb, 'g-new')
    eq('[gps drop] a pin posted for a previous hold is refused',
       _pin(_gb, _old), (409, {'ok': False, 'error': 'not the order in the car'}))

    # Drop by hand clears the arrival: arrived, Drop, and nothing of that order
    # is left — asked straight after the press. It was asked after the same
    # card had been taken and pinned again, and a Took builds its hold afresh,
    # so the check passed with Drop doing nothing at all; and the "leaving
    # afterwards drops nothing" that followed it could not fail by any change
    # to Drop either, for the same reason, and is gone.
    _h = _took(_gb, 'g-hand')
    _pin(_gb, _h)
    _beats(_DWELL)
    ok_('[gps drop] (the premise: it had arrived)', (_holding(_gb) or {}).get('arrived'))
    post(_gb, '/api/delivered', {})
    eq('[gps drop] Drop pressed by hand clears the arrival: the order, its pin and '
       'its arrival are gone', _holding(_gb), None)
    _h = _took(_gb, 'g-hand')
    _pin(_gb, _h)

    # A new Took is a new end: the old pin does not come with it.
    ok_('[gps drop] (the premise: the old order was pinned)',
        (_holding(_gb) or {}).get('endPinned'))
    _took(_gb, 'g-next')
    no_('[gps drop] a new Took clears the old end', (_holding(_gb) or {}).get('endPinned'))

    # A ⌖ read that moves the order's end: the pin was made for the old text,
    # and the car stopping at that door and leaving it is not this order's.
    _h = _took(_gb, 'g-moved')
    _pin(_gb, _h)
    ok_('[gps drop] (the premise: the order was pinned)',
        (_holding(_gb) or {}).get('endPinned'))
    _beats([{'_line': {'dropoff': {'found': True, 'line': '77 Elsewhere Ct, Marietta',
                                   'street': '77 Elsewhere Ct', 'city': 'Marietta',
                                   'state': 'GA', 'zip': None, 'asked': True,
                                   'ms': None}}}])
    eq('[gps drop] a ⌖ read that moves the order\'s end disarms the pin made for the '
       'old one', ((_holding(_gb) or {}).get('dropoff'),
                   (_holding(_gb) or {}).get('endPinned')),
       ('77 Elsewhere Ct, Marietta', False))
    _beats(_DWELL + _LEAVE)
    ok_('[gps drop] ...so stopping at the old door and leaving drops nothing',
        _holding(_gb))
    post(_gb, '/api/delivered', {})

    # Pinned and arrived, then the server restarts in the driveway.
    _h = _took(_gb, 'g-boot')
    _pin(_gb, _h)
    # The pin is on disk as soon as it is kept, not only once an arrival
    # happens to write the hold: a restart between the two must keep it.
    # holding.json is {v: 2, orders: [hold]} since two orders can be carried.
    _hj = json.load(open(os.path.join(_gdir, 'holding.json')))
    _hj = ([o for o in _hj.get('orders') or [] if o.get('id') == 'g-boot'] or [{}])[0]
    eq('[gps drop] the pin is written to holding.json the moment it is kept',
       ((_hj.get('endPin') or {}).get('lat'), (_hj.get('endPin') or {}).get('doorLevel')),
       (_PIN[0], True))
    _beats(_DWELL)
finally:
    stop(_gp)
_gp, _gb = start(_GENV, _gjournal)
try:
    _back = _holding(_gb) or {}
    eq('[gps drop] the pin and the arrival survive a restart via holding.json',
       (_back.get('endPinned'), _back.get('arrived')), (True, True))
    _beats(_LEAVE)
    eq('[gps drop] ...and leaving after it drops the order once',
       ([r.get('by') for r in _drops('g-boot')], _holding(_gb)), (['gps'], None))

    # The restaurant guard: a pickup Map view pinned within 150 m of the door
    # disarms it, and /api/status says why.
    _h = _took(_gb, 'g-rest')
    _pin(_gb, _h)
    eq('[gps drop] a held pickup pin for another order is refused, and changes nothing',
       (post(_gb, '/api/held-pickup', {'holdId': 'g-other@1', 'lat': _PIN[0] + 0.0009,
                                       'lon': _PIN[1]}),
        (_holding(_gb) or {}).get('endWhy')),
       ((409, {'ok': False, 'error': 'not the order in the car'}), None))
    eq('[gps drop] a held pickup pin is kept',
       post(_gb, '/api/held-pickup', {'holdId': _h.get('holdId'),
                                      'lat': _PIN[0] + 0.0009, 'lon': _PIN[1]})[0], 200)
    eq('[gps drop] a door within 150 m of a held pickup is not armed, and says why',
       (_holding(_gb) or {}).get('endWhy'), 'door next to the pickup')
    _beats(_DWELL + _LEAVE)
    ok_('[gps drop] ...so waiting at the restaurant and leaving drops nothing', _holding(_gb))
    # ...and the panel is told the same, on the stream: the beat carries the
    # GPS drop's state (the panel's in-car line says it between offers, when
    # no reading comes), and so does the order as heldForPanel describes it,
    # here in the reply to a Took. /api/status was the only place it was said,
    # and the panel fetches that once, at load.
    _state = lambda h: {k: (h or {}).get(k) for k in ('endPinned', 'arrived', 'endWhy')}
    eq('[gps drop] the beat carries the GPS drop\'s state for the panel',
       (get(_gb, '/api/status').get('beat') or {}).get('heldEnd'),
       {'endPinned': True, 'arrived': False, 'endBy': None,
        'endAt': {'lat': 33.9, 'lon': -84.5},
        # ...and its pickup's pin, the map's last rung (MV.routeLadder).
        'pickAt': {'lat': 33.9009, 'lon': -84.5},
        'endWhy': 'door next to the pickup', 'visited': [],
        # ...and no general area beside a pin (refuseHeldEnd's endArea; the
        # owner, 24 Oct): a door pinned is never routed to roughly.
        'endArea': None})
    eq('[gps drop] ...the same as /api/status says', _state(_holding(_gb)),
       {'endPinned': True, 'arrived': False, 'endWhy': 'door next to the pickup'})
    _r = post(_gb, '/api/offers/mark', {
        'id': 'g-stream', 'accepted': True,
        'offer': {'id': 'g-stream', 'pay': 12.0, 'minutes': 40.0, 'billedMinutes': 40.0,
                  'miles': 5.0, 'cost': 1.75, 'dropoff': 'Kestrel Dr, Marietta',
                  'multiOrder': False}})[1]
    eq('[gps drop] ...and the order the stream describes carries it too',
       _state(_r.get('held')), {'endPinned': False, 'arrived': False, 'endWhy': None})
    post(_gb, '/api/delivered', {})
    _beats([_fix(_FAR)])
    eq('[gps drop] ...and with nothing held the beat says so',
       (get(_gb, '/api/status').get('beat') or {}).get('heldEnd', 'missing'), None)
finally:
    stop(_gp)

# A BATCHED Uber trip (the owner's facts of 17 and 19 Oct 2026, the decision of
# 19 Oct; Assemble.batchPlan): ONE card, one Took, and a Trip Planner seen
# whole that lists two dropoffs. The end is the LAST door, the GPS drop arms on
# it alone, and arriving at the first door and leaving puts nothing down.
# Every store, person and street invented.
def _bstop(kind, name, by, street, city):
    return {'kind': kind, 'orders': 1, 'name': name, 'place': None, 'expectedBy': by,
            'street': street, 'city': city, 'state': 'GA' if city else None, 'zip': None,
            'line': (street + ', ' + city) if street and city else None,
            'partial': None, 'label': kind}


_BFIRST = '88 Hollin Ct, Marietta'
_BLAST = '517 Tarrow Ridge Dr NW, Marietta'
_BSTOPS = [_bstop('pickup', 'Tamsin Bakehouse', 1040, '40 Quarrel St', 'Smyrna'),
           _bstop('pickup', 'Orrin Noodle Co', 1046, '12 Pellow Ave', 'Smyrna'),
           _bstop('dropoff', 'Vesna R.', 1062, '88 Hollin Ct', 'Marietta'),
           _bstop('dropoff', 'Corvin D.', 1080, '517 Tarrow Ridge Dr NW', 'Marietta')]
_BCARD = 'Tarrow Ridge Dr & Brisk Ln, Marietta'


def _bplanner(stops=_BSTOPS, top=True, bottom=True):
    """An unpressed whole-screen planner read: its sighting, then its line."""
    at = int(time.time() * 1000)
    _beats([{'_line': {'sighting': {'at': at, 'asked': False, 'whole': True, 'titled': True,
                                    'app': 'uber', 'screen': 'uber.planner',
                                    'page': {'top': top, 'bottom': bottom}, 'stops': stops,
                                    'orderCount': 1, 'keep': False}}},
            {'_line': {'planner': {'stops': [{k: v for k, v in x.items()
                                              if k not in ('partial', 'label')}
                                             for x in stops],
                                   'keep': False, 'asked': False, 'ms': None, 'at': at}}}])


def _marks(oid):
    rows = [json.loads(l) for l in open(_gjournal) if l.strip()]
    return [r for r in rows if r.get('kind') == 'mark' and r.get('id') == oid]


_BFAR = 0.01      # the first door, ~1.1 km north of the last one (_PIN)
_gp, _gb = start(_GENV, _gjournal)
try:
    _took(_gb, 'b-trip', dropoff=_BCARD)
    _bplanner()
    _bh = _holding(_gb) or {}
    eq('[batch] two dropoffs on a list seen whole with one order held: the end is the '
       'LAST door, from the planner',
       (_bh.get('dropoff'), ((_bh.get('fields') or {}).get('dropoff') or {}).get('from')),
       (_BLAST, 'planner'))
    eq('[batch] ...the order is a batch, every door on it, and no batchWhy',
       (_bh.get('batch'), [d.get('line') for d in _bh.get('drops') or []],
        _bh.get('batchWhy')), (True, [_BFIRST, _BLAST], None))
    eq('[batch] ...the planner line says no reason for the end',
       ((_bh.get('planner') or {}).get('unfiled')), None)
    _bm = [r for r in _marks('b-trip') if r.get('batch')]
    eq('[batch] ...the journal\'s mark row says batch and the count, no door list',
       [(r.get('batch'), r.get('drops'), r.get('dropoff'), 'stops' in r) for r in _bm],
       [(True, 2, _BLAST, False)])
    eq('[batch] the last door\'s pin is kept',
       _pin(_gb, _bh, dropoff=_BLAST,
            name='517, Tarrow Ridge Drive Northwest, Marietta, Cobb County')[0], 200)
    eq('[batch] ...and a pin for the first door is not the order\'s end',
       post(_gb, '/api/held-end', {'holdId': _bh.get('holdId'), 'dropoff': _BFIRST,
                                   'lat': _PIN[0] + _BFAR, 'lon': _PIN[1],
                                   'name': '88, Hollin Court, Marietta',
                                   'doorLevel': True})[0], 409)
    _beats([_fix(_BFAR)] * 7 + [_fix(_BFAR + _FAR)] * 3)
    eq('[batch] arriving at the FIRST door and leaving does not put the order down',
       (bool(_holding(_gb)), _drops('b-trip')), (True, []))
    _beats(_DWELL + _LEAVE)
    eq('[batch] ...arriving at the LAST door and leaving does, once, by the GPS',
       ([r.get('by') for r in _drops('b-trip')], _holding(_gb)), (['gps'], None))

    # The guard: the card's corner is on none of the planner's dropoffs.
    _took(_gb, 'b-else', dropoff='Wexley Pkwy & Brisk Ln, Kennesaw')
    _bplanner()
    _bh = _holding(_gb) or {}
    eq('[batch] a card whose end is on none of the planner\'s dropoffs is no batch, and '
       '/api/status says why', (_bh.get('dropoff'), _bh.get('batch'), _bh.get('batchWhy')),
       ('Wexley Pkwy & Brisk Ln, Kennesaw', False, 'card end elsewhere'))
    post(_gb, '/api/delivered', {})
    # A list whose foot is off the screen. Its customers named afresh: this
    # harness sends no offer line, so every Took here is dated from the same
    # card (cardArrivedAt), and the last order's pages would stitch to these.
    _BOFF = [dict(x, name=(x['name'] + ' 2')) for x in _BSTOPS]
    _took(_gb, 'b-off', dropoff=_BCARD)
    _bplanner(_BOFF, bottom=False)
    _bh = _holding(_gb) or {}
    eq('[batch] a list running off the screen is no batch',
       (_bh.get('dropoff'), _bh.get('batch'), _bh.get('drops')), (_BCARD, False, None))
    # A batch goes with its order: a later card taken replaces it, batch and all.
    _bplanner(_BOFF)
    ok_('[batch] (the premise: the list seen whole makes it a batch)',
        (_holding(_gb) or {}).get('batch'))
    _took(_gb, 'b-next', dropoff='Kestrel Dr, Marietta')
    _bh = _holding(_gb) or {}
    eq('[batch] ...and a later Took replaces it, the batch with it',
       (_bh.get('dropoff'), _bh.get('batch'), _bh.get('drops'),
        [r.get('by') for r in _drops('b-off')]),
       ('Kestrel Dr, Marietta', False, None, ['replaced']))
    post(_gb, '/api/delivered', {})
    # An add-on trip is untouched: two orders held, the planner's doors are
    # theirs by cues, and neither is a batch.
    post(_gb, '/api/offers/mark', {
        'id': 'b-root', 'accepted': True,
        'offer': {'id': 'b-root', 'pay': 12.0, 'minutes': 40.0, 'billedMinutes': 40.0,
                  'miles': 5.0, 'cost': 1.75, 'dropoff': _BCARD, 'multiOrder': False,
                  'app': 'uber'}})
    post(_gb, '/api/offers/mark', {
        'id': 'b-add', 'accepted': True,
        'offer': {'id': 'b-add', 'pay': 9.5, 'minutes': 8.0, 'billedMinutes': 8.0,
                  'miles': 1.3, 'cost': 0.5, 'dropoff': None, 'multiOrder': False,
                  'addon': True, 'app': 'uber'}})
    _bplanner()
    _bo = get(_gb, '/api/status').get('orders') or []
    _bh = _holding(_gb) or {}
    eq('[batch] an add-on trip\'s planner makes no batch of either order',
       (len(_bo), _bh.get('batch'), _bh.get('drops'),
        [r for r in _marks('b-root') + _marks('b-add') if r.get('batch')]),
       (2, False, None, []))
    # The add-on's card says it is one (cardOf `addon`), and the root's does
    # not: what MV.cardYardstick reads to take its miles as an increment and
    # heldDisc to search its door in the trip's disc grown by them (the
    # owner's 26 Oct shift, order #5). Absent, not false, on the root's.
    eq('[add-on disc] the add-on\'s held card is marked an add-on\'s; the root\'s is not',
       [('addon' in (o.get('card') or {}), (o.get('card') or {}).get('addon')) for o in _bo],
       [(False, None), (True, True)])
    post(_gb, '/api/delivered', {})
    post(_gb, '/api/delivered', {})
finally:
    stop(_gp)


# The 12 Oct replay's numbers, at their real defaults (no GPS_DWELL_MS): the
# dwell is 60 s and the arrive radius 75 m + min(err, 25). Real seconds are
# made from each fix's age (gpsAge), 10 s apart, a new hold for each case.
def _aged(dlat, ages, **kw):
    return [_fix(dlat, age=a, **kw) for a in ages]


_gp, _gb = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable,
                  'SCANNER_ARGS': _gfake}, _gjournal)
try:
    _h = _took(_gb, 'g-70s')
    _pin(_gb, _h)
    _beats(_aged(_IN, [70, 60, 50, 40, 30, 20, 10, 0.1]))
    ok_('[gps tune] (the premise: a 70 s stop at the door arrives)',
        (_holding(_gb) or {}).get('arrived'))
    post(_gb, '/api/delivered', {})

    _h = _took(_gb, 'g-50s')
    _pin(_gb, _h)
    _beats(_aged(_IN, [50, 40, 30, 20, 10, 0.1]))
    no_('[gps tune] a 50 s stop no longer arrives (DWELL 60 s)',
        (_holding(_gb) or {}).get('arrived'))
    post(_gb, '/api/delivered', {})

    # 110 m off with err 50: inside 75 + 50 = 125, outside 75 + 25 = 100.
    _h = _took(_gb, 'g-cap')
    _pin(_gb, _h)
    _beats(_aged(0.00099, [70, 60, 50, 40, 30, 20, 10, 0.1], err=50.0))
    no_('[gps tune] the arrive radius stops at 100 m however rough the fix',
        (_holding(_gb) or {}).get('arrived'))
    post(_gb, '/api/delivered', {})

    # 40 s good inside, 40 s of gate-refused fixes, 30 s good inside: 70 s
    # counted, the refused run kept but not counted.
    _h = _took(_gb, 'g-rough')
    _pin(_gb, _h)
    _beats(_aged(_IN, [110, 100, 90, 80, 70])
           + _aged(_IN, [65, 55, 45, 35], ok=False, err=60.0)
           + _aged(_IN, [30, 20, 10, 0.1]))
    ok_('[gps tune] a 40 s run of gate-refused fixes inside the radius keeps the dwell',
        (_holding(_gb) or {}).get('arrived'))
    post(_gb, '/api/delivered', {})

    # The same with nothing at all in the 40 s: silence still resets.
    _h = _took(_gb, 'g-silent')
    _pin(_gb, _h)
    _beats(_aged(_IN, [110, 100, 90, 80, 70]) + _aged(_IN, [30, 20, 10, 0.1]))
    no_('[gps tune] ...but 40 s with no fixes at all resets it',
        (_holding(_gb) or {}).get('arrived'))
    post(_gb, '/api/delivered', {})

    # The refused run's own time is not counted: 20 s good inside, 40 s of
    # refused fixes, 10 s good inside — 30 s counted, short of 60. Counted, it
    # would be 70 and arrive.
    _h = _took(_gb, 'g-skip')
    _pin(_gb, _h)
    _beats(_aged(_IN, [70, 60, 50])
           + _aged(_IN, [45, 35, 25, 15], ok=False, err=60.0)
           + _aged(_IN, [10, 0.1]))
    no_('[gps tune] ...and the time inside a refused run does not count toward the dwell',
        (_holding(_gb) or {}).get('arrived'))
    post(_gb, '/api/delivered', {})

    # Silence inside a refused run resets as silence does: 40 s good, one
    # refused fix, then 35 s of nothing before the next good one.
    _h = _took(_gb, 'g-hush')
    _pin(_gb, _h)
    _beats(_aged(_IN, [110, 100, 90, 80, 70])
           + _aged(_IN, [65], ok=False, err=60.0)
           + _aged(_IN, [30, 20, 10, 0.1]))
    no_('[gps tune] ...and 35 s of nothing after a refused fix resets it',
        (_holding(_gb) or {}).get('arrived'))
    post(_gb, '/api/delivered', {})

    # A refused run longer than REJECTED_GAP_S (60 s) resets: 40 s good, 90 s
    # from the last good fix to the next, refused fixes every 10 s, 40 s good.
    _h = _took(_gb, 'g-long')
    _pin(_gb, _h)
    _beats(_aged(_IN, [170, 160, 150, 140, 130])
           + _aged(_IN, [120, 110, 100, 90, 80, 70, 60, 50], ok=False, err=60.0)
           + _aged(_IN, [40, 30, 20, 10, 0.1]))
    no_('[gps tune] ...and a refused run of more than 60 s resets it',
        (_holding(_gb) or {}).get('arrived'))
    post(_gb, '/api/delivered', {})

    # The radius is 75 m plus the fix's OWN error, capped at 25: a fix sure to
    # 5 m is held to 80 m, so 90 m off for 70 s does not arrive.
    _h = _took(_gb, 'g-tight')
    _pin(_gb, _h)
    _beats(_aged(0.00081, [70, 60, 50, 40, 30, 20, 10, 0.1], err=5.0))
    no_('[gps tune] ...and a fix sure to 5 m is held to 80 m: 90 m off does not arrive',
        (_holding(_gb) or {}).get('arrived'))
    post(_gb, '/api/delivered', {})
finally:
    stop(_gp)
    shutil.rmtree(_gdir, ignore_errors=True)


# --- the held end, searched for by the server --------------------------------
#
# The driver: GPS arrival should arm without opening Map view. When the hold
# names a dropoff and NUCBOX_SEARCH is set, server.js asks the NucBox itself
# (searchHeldEnd), by Map view's own rules — inside the HELD card's disc, door
# level only — and says on /api/status why when it did not pin. Two NucBoxes:
# tests/fake-nucbox.js for the answers, and a stand-in below that is down
# (503) or slow on cue and counts every search it was sent. Card fixes at
# Marietta Square, as the fake's own; addresses invented.
_SQ = {'lat': 33.9526, 'lon': -84.5499, 'gpsOk': True, 'gpsErr': 10.0, 'gpsMode': 3,
       'gpsAge': 0.5, 'hasTotal': True, 'whole': True, 'multiOrder': False}
_COBB = '1985 Cobb Parkway, Kennesaw'      # three door answers, 3.4 mi from the Square
_KES = '4821 Kestrel Dr, Marietta'         # its street only, no number


class _Stub(object):
    mode = 'down'
    searches = []


def _stub_app():
    import http.server

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            _Stub.searches.append(self.path)
            if _Stub.mode == 'down':
                self.send_response(503)
                self.end_headers()
                return
            time.sleep(1.0)
            body = json.dumps([{'lat': '34.0010000', 'lon': '-84.5560000',
                                'display_name': '1985, Cobb Parkway, Kennesaw, Cobb County'}])
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(body.encode('utf-8'))
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _atook(base, oid, dropoff, miles=5.0):
    o = dict(_SQ, id=oid, pay=12.0, minutes=40.0, billedMinutes=40.0, miles=miles,
             cost=1.75)
    if dropoff:
        o['dropoff'] = dropoff
    post(base, '/api/offers/mark', {'id': oid, 'accepted': True, 'offer': o})


def _settled(base, want=lambda h: h.get('endPinned') or h.get('endWhy'), seconds=6.0):
    h = {}
    for _ in range(int(seconds / 0.05)):
        h = get(base, '/api/status').get('holding') or {}
        if want(h):
            break
        time.sleep(0.05)
    return h


_afake = subprocess.Popen(['node', os.path.join(ROOT, 'tests', 'fake-nucbox.js')],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
_afake_base = 'http://127.0.0.1:%d' % json.loads(_afake.stdout.readline())['port']
_stub = _stub_app()
_stub_base = 'http://127.0.0.1:%d' % _stub.server_address[1]


def _aasked(word):
    return [a for a in json.loads(urllib.request.urlopen(
        _afake_base + '/__asked', timeout=5).read()) if word in a]


_adir = tempfile.mkdtemp()
# A scanner that says what the suite writes to say-N.json, one line each.
_asay = os.path.join(_adir, 'say.py')
with open(_asay, 'w') as _fh:
    _fh.write(
        'import json, os, time\n'
        'd = os.path.dirname(os.path.abspath(__file__))\n'
        'n = 0\n'
        'end = time.time() + 600\n'
        'while time.time() < end:\n'
        '    p = os.path.join(d, "say-%d.json" % n)\n'
        '    if not os.path.exists(p):\n'
        '        time.sleep(0.05)\n'
        '        continue\n'
        '    for x in json.load(open(p)):\n'
        '        x["dropoff"]["at"] = int(time.time() * 1000)\n'
        '        print(json.dumps(x), flush=True)\n'
        '    n += 1\n')
try:
    _aj = os.path.join(_adir, 'a', 'offers.jsonl')
    os.makedirs(os.path.dirname(_aj))
    open(_aj, 'w').close()
    _ap, _ab = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable, 'SCANNER_ARGS': _asay,
                      'NUCBOX_SEARCH': _afake_base, 'NUCBOX_TIMEOUT_MS': '800'}, _aj)
    try:
        _atook(_ab, 'a-door', _COBB)
        _h = _settled(_ab)
        eq('[auto arm] a door-level answer inside the held card\'s disc arms the GPS drop',
           (_h.get('endPinned'), _h.get('endBy'), _h.get('endWhy')), (True, 'server', None))
        _s, _r = post(_ab, '/api/held-end', {
            'holdId': _h.get('holdId'), 'dropoff': _COBB, 'lat': 34.0, 'lon': -84.55,
            'name': '1985, Cobb Parkway, Kennesaw', 'doorLevel': True})
        eq('[auto arm] a later page pin for the same dropoff is a no-op: the first wins',
           (_s, (_holding(_ab) or {}).get('endBy')), (200, 'server'))

        _atook(_ab, 'a-street', _KES)
        _h = _settled(_ab)
        eq('[auto arm] a street-only answer does not arm, and says why',
           (_h.get('endPinned'), _h.get('endWhy')), (False, 'street found, not that door'))
        eq('[auto arm] ...asked once for that dropoff', len(_aasked('4821')), 1)

        _atook(_ab, 'a-far', _COBB, miles=2.0)
        _h = _settled(_ab)
        eq('[auto arm] an answer outside the held card\'s disc does not arm',
           (_h.get('endPinned'), _h.get('endWhy')), (False, 'not inside the card\'s reach'))

        # The 17 Oct evening snap, invented: the planner's door printed with
        # the app's "Cts", which the NucBox answers with nothing; asked once
        # more with the type word left out (MV.streetRetry), the door on the
        # same street pinned, never the same number on another type of street.
        _n = len(_aasked('Tansy'))
        _atook(_ab, 'a-retry', '1830 Tansy Creek Cts SW, Marietta')
        _h = _settled(_ab)
        eq('[street retry] a door printed "Cts" and answered with nothing is asked once more '
           'with its type left out, pinned at the same street\'s door, and says how',
           (_h.get('endPinned'), _h.get('endBy'), _h.get('endAsked'), _h.get('endWhy'),
            [urllib.parse.unquote(u.split('street=')[1].split('&')[0])
             for u in _aasked('Tansy')[_n:]]),
           (True, 'server', '1830 Tansy Creek SW', None,
            ['1830 Tansy Creek Cts SW', '1830 Tansy Creek SW']))
        _n = len(_aasked('Tansy'))
        _atook(_ab, 'a-retry2', '1830 Tansy Creek Cts SW, Marietta')
        _h = _settled(_ab)
        eq('[street retry] ...the next order to that door is answered from the cache, both '
           'questions', (_h.get('endPinned'), _h.get('endAsked'), len(_aasked('Tansy')) - _n),
           (True, '1830 Tansy Creek SW', 0))
        _atook(_ab, 'a-retry-drive', '2040 Tansy Creek Cts SW, Marietta')
        _h = _settled(_ab)
        eq('[street retry] the same number on another type of street is not the door: the '
           'first question\'s refusal stands',
           (_h.get('endPinned'), _h.get('endAsked'), _h.get('endWhy')),
           (False, None, 'not inside the card\'s reach'))
        _atook(_ab, 'a-retry-far', '1830 Tansy Creek Cts SW, Marietta', miles=1.0)
        _h = _settled(_ab)
        eq('[street retry] ...and the door found outside the held card\'s disc is refused',
           (_h.get('endPinned'), _h.get('endWhy')), (False, 'not inside the card\'s reach'))
        _atook(_ab, 'a-door2', _COBB)
        _h = _settled(_ab)
        eq('[street retry] a door found as printed says no other street',
           (_h.get('endPinned'), _h.get('endAsked')), (True, None))

        # The owner's 20 Oct fault, invented: the road's middle initial spelled
        # out ("<A> West <B> Parkway"), the road found inside the disc and not
        # the door; asked once more with "W" (MV.dirRetry), the door on the
        # same street pinned, never a house of that number on another street.
        _n = len(_aasked('Ardley'))
        _atook(_ab, 'a-dir', '810 Ardley West Corwin Parkway, Kennesaw, GA 30144')
        _h = _settled(_ab)
        eq('[directional retry] a door whose road is found and not the door is asked once more '
           'with the directional as its letter, pinned at the same street\'s door, and says how',
           (_h.get('endPinned'), _h.get('endBy'), _h.get('endAsked'), _h.get('endWhy'),
            [urllib.parse.unquote(u.split('street=')[1].split('&')[0])
             for u in _aasked('Ardley')[_n:]]),
           (True, 'server', '810 Ardley W Corwin Parkway', None,
            ['810 Ardley West Corwin Parkway', '810 Ardley W Corwin Parkway']))
        _atook(_ab, 'a-dir-circle', '812 Ardley West Corwin Parkway, Kennesaw, GA 30144')
        _h = _settled(_ab)
        eq('[directional retry] a house of that number on another street is not the door: the '
           'road\'s refusal stands', (_h.get('endPinned'), _h.get('endAsked'), _h.get('endWhy')),
           (False, None, 'street found, not that door'))
        _atook(_ab, 'a-dir-far', '810 Ardley West Corwin Parkway, Kennesaw, GA 30144', miles=1.0)
        _h = _settled(_ab)
        eq('[directional retry] ...nor the door outside the held card\'s disc',
           (_h.get('endPinned'), _h.get('endWhy')), (False, 'street found, not that door'))

        # The same order, its dropoff changed by a ⌖ Scan: asked again.
        _atook(_ab, 'a-change', _KES, miles=6.0)
        _settled(_ab)
        _n = len(_aasked('1985'))
        with open(os.path.join(_adir, 'say-0.json.tmp'), 'w') as _fh:
            json.dump([{'dropoff': {'line': '1985 Cobb Parkway, Kennesaw, GA 30152',
                                    'street': '1985 Cobb Parkway', 'city': 'Kennesaw',
                                    'state': 'GA', 'zip': '30152', 'found': True,
                                    'asked': True}}], _fh)
        os.rename(os.path.join(_adir, 'say-0.json.tmp'), os.path.join(_adir, 'say-0.json'))
        _h = _settled(_ab, lambda h: h.get('endPinned'))
        eq('[auto arm] a changed dropoff is searched again, and arms',
           (len(_aasked('1985')) - _n, _h.get('endPinned'), _h.get('endWhy')), (1, True, None))
    finally:
        stop(_ap)

    # The 19 Oct night fault, invented: the planner's "1106 <Name> Ln" read off
    # a dark frame as "L106 <Nam..>r" and filed "1106 Tamaror", which the
    # NucBox's search answers with nothing, and with no type word to leave
    # out. With NUCBOX_STREETS set the street index (the fake's, by the real
    # streets.js) is asked which one street that read is, and the door asked
    # by its name (searchHeldNamed, MV.nameRetry).
    _nmj = os.path.join(_adir, 'nm', 'offers.jsonl')
    os.makedirs(os.path.dirname(_nmj))
    open(_nmj, 'w').close()
    _nmp, _nmb = start({'SCANNER': '0', 'NUCBOX_SEARCH': _afake_base,
                        'NUCBOX_STREETS': _afake_base, 'NUCBOX_TIMEOUT_MS': '800'}, _nmj)
    try:
        _n = len(_aasked('Tamar'))
        _atook(_nmb, 'n-door', '1106 Tamaror, Marietta')
        _h = _settled(_nmb)
        eq('[name rescue] a door filed under a name read short is pinned by the one street the '
           'street index says it is, and says which',
           (_h.get('endPinned'), _h.get('endBy'), _h.get('endAsked'), _h.get('endWhy'),
            [urllib.parse.unquote(re.search(r'[?&](?:street|name)=([^&]*)', u).group(1))
             for u in _aasked('Tamar')[_n:]]),
           (True, 'server', '1106 Tamarons Lane', None,
            ['1106 Tamaror', 'Tamaror', '1106 Tamarons Lane']))
        eq('[name rescue] ...the index asked at /api/streets/named inside the disc\'s box',
           [u.split('?')[0] for u in _aasked('Tamar')[_n:]],
           ['/search', '/api/streets/named', '/search'])
        _n = len(_aasked('Tamar'))
        _atook(_nmb, 'n-door2', '1106 Tamaror, Marietta')
        _h = _settled(_nmb)
        time.sleep(0.3)
        _nrow = [json.loads(x) for x in open(_nmj) if x.strip()]
        eq('[pin log] the replaced order\'s row says its end was pinned by the street-index '
           'rescue, under another spelling of its street',
           [((r.get('end') or {}).get('by'), (r.get('end') or {}).get('asked'))
            for r in _nrow if r.get('kind') == 'drop' and r.get('id') == 'n-door'],
           [('rescue', 'street')])
        eq('[name rescue] ...the next order to that door is answered from the cache, all three',
           (_h.get('endPinned'), _h.get('endAsked'), len(_aasked('Tamar')) - _n),
           (True, '1106 Tamarons Lane', 0))
        _atook(_nmb, 'n-two', '1106 Brindler, Marietta')
        _h = _settled(_nmb)
        eq('[name rescue] a read two near streets can be is neither: the first refusal stands '
           'and no door is asked by either name',
           (_h.get('endPinned'), _h.get('endAsked'), _h.get('endWhy'),
            len(_aasked('Brindlewood')) + len(_aasked('Brindleton'))),
           (False, None, 'not inside the card\'s reach', 0))
        _atook(_nmb, 'n-far', '1106 Tamaror, Marietta', miles=1.0)
        _h = _settled(_nmb)
        eq('[name rescue] ...and the door found outside a 1.0 mi card is refused',
           (_h.get('endPinned'), _h.get('endWhy')), (False, 'not inside the card\'s reach'))
        # A door the NucBox holds only the street of, pinned by Map view's
        # post: its row says the page pinned it and asks nothing of how.
        _atook(_nmb, 'n-page', _KES)
        _h = _settled(_nmb)
        post(_nmb, '/api/held-end', {'holdId': _h.get('holdId'), 'dropoff': _KES,
                                     'lat': 33.9600, 'lon': -84.5400, 'doorLevel': True,
                                     'name': '4821, Kestrel Drive, Marietta, Cobb County'})
        _atook(_nmb, 'n-cobb', _COBB)
        _h = _settled(_nmb)
        time.sleep(0.3)
        _nrow = [json.loads(x) for x in open(_nmj) if x.strip()]
        eq('[pin log] an end Map view pinned says \'page\', and no question of the server\'s',
           [((r.get('end') or {}).get('by'), (r.get('end') or {}).get('asked'))
            for r in _nrow if r.get('kind') == 'drop' and r.get('id') == 'n-page'],
           [('page', None)])
        eq('[name rescue] a door found as printed never asks the index',
           (_h.get('endPinned'), _h.get('endAsked'), len(_aasked('named?name=1985')),
            len(_aasked('named?name=Cobb'))), (True, None, 0, 0))
        _s, _r, _ = raw(_nmb, '/api/nbx/named?name=Tamaror')
        eq('[name rescue] the relay passes the question on only with a box',
           (_s, json.loads(_r).get('error')), (400, 'named needs a box'))
        _r = get(_nmb, '/api/nbx/named?name=Tamaror&box=-84.65,34.04,-84.45,33.87')
        eq('[name rescue] ...and relays the index\'s answer, from the cache',
           (_r.get('names'), _r.get('how'), _r.get('among')), (['Tamarons Lane'], 'cut', 1))
        # Mutation catch-up (21 Oct): a door whose street kept its type word,
        # "1106 Tamarons Ln", asked as printed and without "Ln", neither of
        # which the fake answers: the index is asked after the type-word retry
        # too, and the door found by the street's own name (its search from
        # the cache: "1106 Tamarons Lane" was asked for n-door above).
        _n = len(_aasked('Tamarons'))
        _atook(_nmb, 'n-typed', '1106 Tamarons Ln, Marietta')
        _h = _settled(_nmb)
        eq('[name rescue] after the type-word retry found nothing, the index is asked and the '
           'door pinned by the street\'s own name',
           (_h.get('endPinned'), _h.get('endAsked'),
            [u.split('?')[0] for u in _aasked('Tamarons')[_n:]]),
           (True, '1106 Tamarons Lane', ['/search', '/search', '/api/streets/named']))
    finally:
        stop(_nmp)
    # Without NUCBOX_STREETS: the server above (_ab) refused "2040 Tansy Creek
    # Cts SW" as not inside the card's reach, the case the index would be
    # asked in, and asked it nothing.
    eq('[name rescue] with NUCBOX_STREETS unset the index is never asked',
       len(_aasked('named?name=Tansy')), 0)

    # Mutation catch-up (21 Oct): "1106 Tamaror" with no type word to leave
    # out, on a server with NUCBOX_STREETS unset, keeps the door search's own
    # refusal, not a question to an index that is not there ('NucBox down');
    # and on one whose index answers names beside two streets (not "the one
    # street"), that answer is no answer — the relay says the index is not
    # answering — and, since 26 Oct (endAsk's `unanswered`), the held end keeps
    # the door search's own refusal there too: the search answered, and only
    # the rescue had nothing.
    class _BadIx(object):
        asked = []

    def _badix_app():
        import http.server

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                _BadIx.asked.append(self.path)
                body = json.dumps({'ok': True, 'names': ['Tamarons Lane'], 'how': 'cut',
                                   'among': 2})
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(body.encode('utf-8'))
        srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv
    _badix = _badix_app()
    _badix_base = 'http://127.0.0.1:%d' % _badix.server_address[1]
    for _ixname, _ixenv, _ixwant in (
            ('unset', {}, 'not inside the card\'s reach'),
            ('bad', {'NUCBOX_STREETS': _badix_base}, 'not inside the card\'s reach')):
        _ixj = os.path.join(_adir, 'ix-' + _ixname, 'offers.jsonl')
        os.makedirs(os.path.dirname(_ixj))
        open(_ixj, 'w').close()
        _ixp, _ixb = start(dict({'SCANNER': '0', 'NUCBOX_SEARCH': _afake_base,
                                 'NUCBOX_TIMEOUT_MS': '800', 'NUCBOX_RETRY_MS': '60000'},
                                **_ixenv), _ixj)
        try:
            _atook(_ixb, 'ix-' + _ixname, '1106 Tamaror, Marietta')
            _h = _settled(_ixb)
            eq('[name rescue] the index %s: "1106 Tamaror" refused as %r' % (
                'unset' if _ixname == 'unset' else 'answering names beside two streets',
                _ixwant), (_h.get('endPinned'), _h.get('endWhy')), (False, _ixwant))
            if _ixname == 'bad':
                _s, _r, _ = raw(_ixb, '/api/nbx/named?name=Tamaror&box=-84.65,34.04,-84.45,33.87')
                eq('[name rescue] ...and the relay refuses that answer as the index not answering',
                   (_s, json.loads(_r).get('unreachable')), (502, True))
        finally:
            stop(_ixp)
    _badix.shutdown()

    # The 26 Oct shift: the street index on 8081 refused every connection all
    # evening (ECONNREFUSED; the panel said "NucBox: streets down") while
    # search answered, and three held doors were refused 'NucBox down' — each
    # after its search had answered, by the index asked only to rescue it
    # (doorChain's byName), to arm a short street (searchHeldStreet), or for a
    # rough area (searchHeldStreetArea). Each now keeps the search's own
    # refusal, its drop row says that, and the whole search is still asked
    # once more, once. A port nothing listens on, as that evening's index.
    import socket as _sk
    _dead = _sk.socket()
    _dead.bind(('127.0.0.1', 0))
    _dead_base = 'http://127.0.0.1:%d' % _dead.getsockname()[1]
    _dead.close()
    _sdj = os.path.join(_adir, 'streets-down', 'offers.jsonl')
    os.makedirs(os.path.dirname(_sdj))
    open(_sdj, 'w').close()
    _sdp, _sdb = start({'SCANNER': '0', 'NUCBOX_SEARCH': _afake_base,
                        'NUCBOX_STREETS': _dead_base, 'NUCBOX_TIMEOUT_MS': '800',
                        'NUCBOX_RETRY_MS': '60000'}, _sdj)
    try:
        _sdgot = []
        for _sdid, _sddoor in (('sd-name', '1106 Tamaror, Marietta'),
                               ('sd-court', '306 Larkmoor Ct, Marietta'),
                               ('sd-area', '10495 Pellmore Street, Marietta')):
            _atook(_sdb, _sdid, _sddoor)
            _h = _settled(_sdb)
            _sdgot.append((_h.get('endPinned'), _h.get('endWhy'), bool(_h.get('endArea'))))
        # (The court keeps the general area its door search found, which is
        # the search's and no index's: refuseHeldEnd's endArea, never a pin.
        # The other two have none: the index was to give theirs.)
        eq('[streets down] a door whose search answered keeps the search\'s refusal when the '
           'street index refuses the connection: the name rescue, the short court, the area',
           _sdgot, [(False, 'not inside the card\'s reach', False), (False, 'street found, not that door', True),
                    (False, 'not inside the card\'s reach', False)])
        _atook(_sdb, 'sd-next', _COBB)
        _settled(_sdb, lambda h: h.get('endPinned'))
        time.sleep(0.3)
        _sdrows = [json.loads(x) for x in open(_sdj) if x.strip()]
        eq('[streets down] ...and their drop rows say so, never "NucBox down"',
           [(r['id'], (r.get('end') or {}).get('why')) for r in _sdrows
            if r.get('kind') == 'drop' and r.get('id', '').startswith('sd-')
            and r.get('id') != 'sd-next'],
           [('sd-name', 'not inside the card\'s reach'), ('sd-court', 'street found, not that door'),
            ('sd-area', 'not inside the card\'s reach')])
        eq('[streets down] ...while the panel\'s word for the index is down',
           (get(_sdb, '/api/status').get('nucbox') or {}).get('streets', {}).get('up'), False)
    finally:
        stop(_sdp)

    # ...and the whole search asked once more after NUCBOX_RETRY_MS, ONCE,
    # however many of its index questions went unanswered: "1106 Tamaror"
    # asks the index twice in one chain (named, then whole for the area), both
    # answered 503 by a stub that counts them.
    class _DownIx(object):
        asked = []

    def _downix_app():
        import http.server

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                _DownIx.asked.append(self.path.split('?')[0])
                self.send_response(503)
                self.end_headers()
        srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv
    _downix = _downix_app()
    _sdj2 = os.path.join(_adir, 'streets-503', 'offers.jsonl')
    os.makedirs(os.path.dirname(_sdj2))
    open(_sdj2, 'w').close()
    _sdp, _sdb = start({'SCANNER': '0', 'NUCBOX_SEARCH': _afake_base, 'NUCBOX_PROBE_MS': '0',
                        'NUCBOX_STREETS': 'http://127.0.0.1:%d' % _downix.server_address[1],
                        'NUCBOX_TIMEOUT_MS': '800', 'NUCBOX_RETRY_MS': '400'}, _sdj2)
    try:
        _atook(_sdb, 'sd-retry', '1106 Tamaror, Marietta')
        _h = _settled(_sdb)
        time.sleep(1.5)
        _h = _settled(_sdb)
        eq('[streets down] the search asked once more, once: each index question twice in all, '
           'and the search\'s refusal still',
           (sorted(_DownIx.asked), _h.get('endWhy')),
           (['/api/streets/named'] * 2 + ['/api/streets/whole'] * 2,
            'not inside the card\'s reach'))
    finally:
        stop(_sdp)
        _downix.shutdown()

    # The owner's planner of 21 Oct, 13:57, end to end, every name and street
    # invented: one Uber order held, carrying two on, its card read badly
    # (legs 0, hasTotal false, multiOrder false) with the corner "Corbins Dr,
    # Marietta" as its end. The Trip Planner read whole with its title scrolled
    # off — the shared case, made into the sighting rpi/scan_pi.py sends by
    # offer_parser itself — files its lone dropoff "2282 Corbin, Marietta" as
    # the planner's (assemble.js framedTrip), and the street-index rescue finds
    # the door by "2282 Corbins Drive": the last letter and the type lost.
    import offer_parser as _OP                                # noqa: E402
    _ftext = [c['text'] for c in json.load(open(os.path.join(
        ROOT, 'tests', 'fixtures', 'cases.json')))['planner']
        if c['name'].startswith("Measured: the single trip's planner of 21 Oct")][0]

    def _fread(text, framed=None):
        """One unpressed whole-screen read of `text` as the scanner sends it:
        the sighting (scan_pi.sighting's fields, by offer_parser), then the
        planner line under the same stamp. `framed` overrides the reader's."""
        at = int(time.time() * 1000)
        stops = _OP.find_planner(text) or []
        top, bottom = _OP.planner_ends(text)
        return [{'sighting': {
            'at': at, 'asked': False, 'whole': True, 'titled': _OP.planner_titled(text),
            'laidOut': _OP.planner_laid_out(text),
            'framed': _OP.planner_framed(text) if framed is None else framed,
            'app': 'uber', 'screen': _OP.screen_type(text)['screen'],
            'page': {'top': top, 'bottom': bottom},
            'stops': [dict({k: s.get(k) for k in ('kind', 'orders', 'name', 'place',
                                                  'expectedBy', 'street', 'city', 'state',
                                                  'zip', 'line', 'partial')},
                           label=s.get('kind')) for s in stops],
            'orderCount': 1, 'keep': False}},
            {'planner': {'stops': [{k: v for k, v in s.items() if k != 'partial'}
                                   for s in stops if s.get('kind')],
                         'keep': False, 'asked': False, 'ms': None, 'at': at}}]

    _fdir = os.path.join(_adir, 'framed')
    os.makedirs(_fdir)
    _fj = os.path.join(_fdir, 'offers.jsonl')
    open(_fj, 'w').close()
    _fcmds = os.path.join(_fdir, 'cmds.jsonl')
    open(_fcmds, 'w').close()
    _frelay = os.path.join(_fdir, 'relay.py')
    with open(_frelay, 'w') as _fh:
        _fh.write('import time\n'
                  'done = 0\n'
                  'end = time.time() + 300\n'
                  'while time.time() < end:\n'
                  '    lines = open(%r).read().splitlines()\n'
                  '    for l in lines[done:]:\n'
                  '        print(l, flush=True)\n'
                  '    done = len(lines)\n'
                  '    time.sleep(0.05)\n' % _fcmds)

    def _fsay(msgs):
        with open(_fcmds, 'a') as fh:
            for m in msgs:
                fh.write(json.dumps(m) + '\n')

    _fp, _fb = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable, 'SCANNER_ARGS': _frelay,
                      'CARRY_TWO': '1', 'NUCBOX_SEARCH': _afake_base,
                      'NUCBOX_STREETS': _afake_base, 'NUCBOX_TIMEOUT_MS': '800'}, _fj)
    try:
        post(_fb, '/api/offers/mark', {'id': 'f-one', 'accepted': True, 'offer': dict(
            _SQ, id='f-one', pay=9.75, minutes=21.0, billedMinutes=21.0, miles=5.0, cost=1.75,
            legs=0, hasTotal=False, multiOrder=False, dropoff='Corbins Dr, Marietta')})
        _h = _settled(_fb, lambda h: h.get('endWhy'))
        eq('[framed] (the premise: the card\'s corner is held, no house number, carrying two on)',
           (_h.get('dropoff'), _h.get('endWhy'), get(_fb, '/api/status').get('carryTwo')),
           ('Corbins Dr, Marietta', 'no house number', True))
        # As the reader saw it before: the page not framed, the old refusal.
        # (Its door is searched already, warmEarly: the rescue's answer is in
        # the cache by the time the framed read files the door.)
        _n = len(_aasked('Corbin'))
        _fsay(_fread(_ftext, framed=False))
        time.sleep(1.0)
        _h = _holding(_fb) or {}
        eq('[framed] an unframed read of the page files nothing: the panel says the list was cut '
           'off', (_h.get('dropoff'), (_h.get('planner') or {}).get('unfiled')),
           ('Corbins Dr, Marietta', 'list'))
        _fsay(_fread(_ftext))
        _h = _settled(_fb, lambda h: h.get('endPinned'))
        eq('[framed] the 21 Oct page, title scrolled off, files its lone dropoff onto a card whose '
           'legs read 0, and the planner line says nothing unfiled',
           (_h.get('dropoff'), _h.get('dropoffScanned'),
            (_h.get('planner') or {}).get('unfiled')),
           ('2282 Corbin, Marietta', True, None))
        eq('[framed] ...and the street-index rescue pins the door as "2282 Corbins Drive"',
           (_h.get('endPinned'), _h.get('endBy'), _h.get('endAsked'), _h.get('endWhy')),
           (True, 'server', '2282 Corbins Drive', None))
        eq('[framed] ...asked as printed, of the index inside the disc\'s box, then by the '
           'street\'s own name, once each',
           [u.split('?')[0] for u in _aasked('Corbin')[_n:]],
           ['/search', '/api/streets/named', '/search'])
        eq('[framed] ...and the store\'s street kept without its suite',
           [p.get('street') for p in (_h.get('planner') or {}).get('stops') or []
            if p.get('kind') == 'pickup'], ['1985 Wrenfield Parkway NW'])
    finally:
        stop(_fp)

    # The owner's card-box read of 21 Oct, 15:00, end to end, every street
    # invented: one Uber order held, its end the card's corner "<A> Flat Ct &
    # <B> Rd, Marietta" (no house number). The planner read in the card box,
    # its Dropoff header above the crop: "Address / 3259 <Name> Oaks Dr /
    # Marietta, GA / View details / Waybill / ... / Stop New Requests" — the
    # shared case, made into the sighting rpi/scan_pi.py sends by offer_parser
    # itself. The trip ends on a dropoff, so that block is the order's end,
    # filed at rank `label` over the corner (assemble.js footDropoff).
    _wtext = [c['text'] for c in json.load(open(os.path.join(
        ROOT, 'tests', 'fixtures', 'cases.json')))['planner']
        if c['name'].startswith("Measured: the card-box read of 21 Oct, 15:00")][0]

    def _wread(text, footed=None, asked=False):
        """One card-box read of `text` as the scanner sends it: the sighting
        alone (no planner line: no header read). `footed` overrides the
        reader's."""
        stops = _OP.find_planner(text) or []
        top, bottom = _OP.planner_ends(text)
        return [{'sighting': {
            'at': int(time.time() * 1000), 'asked': asked, 'whole': False,
            'titled': _OP.planner_titled(text), 'laidOut': _OP.planner_laid_out(text),
            'framed': _OP.planner_framed(text),
            'footed': _OP.planner_foot(text) if footed is None else footed,
            'app': 'uber', 'screen': _OP.screen_type(text)['screen'],
            'page': {'top': top, 'bottom': bottom},
            'stops': [dict({k: s.get(k) for k in ('kind', 'orders', 'name', 'place',
                                                  'expectedBy', 'street', 'city', 'state',
                                                  'zip', 'line', 'partial')},
                           label=s.get('kind')) for s in stops],
            'orderCount': None, 'keep': False}}]

    _wdir = os.path.join(_adir, 'footed')
    os.makedirs(_wdir)
    _wj = os.path.join(_wdir, 'offers.jsonl')
    open(_wj, 'w').close()
    _wcmds = os.path.join(_wdir, 'cmds.jsonl')
    open(_wcmds, 'w').close()
    _wrelay = os.path.join(_wdir, 'relay.py')
    with open(_wrelay, 'w') as _fh:
        _fh.write('import time\n'
                  'done = 0\n'
                  'end = time.time() + 300\n'
                  'while time.time() < end:\n'
                  '    lines = open(%r).read().splitlines()\n'
                  '    for l in lines[done:]:\n'
                  '        print(l, flush=True)\n'
                  '    done = len(lines)\n'
                  '    time.sleep(0.05)\n' % _wcmds)

    def _wsay(msgs):
        with open(_wcmds, 'a') as fh:
            for m in msgs:
                fh.write(json.dumps(m) + '\n')

    _wp, _wb = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable, 'SCANNER_ARGS': _wrelay},
                     _wj)
    try:
        post(_wb, '/api/offers/mark', {'id': 'w-one', 'accepted': True, 'offer': dict(
            _SQ, id='w-one', pay=17.62, minutes=30.0, billedMinutes=30.0, miles=8.0, cost=2.8,
            legs=1, hasTotal=True, multiOrder=False,
            pickup='Fable Grill (3400 Fable International Blvd NW)',
            dropoff='Wren Flat Ct & Oriel Rd, Marietta')})
        time.sleep(0.5)
        # As the reader saw it before: no shape, nothing filed.
        _wsay(_wread(_wtext, footed=False))
        time.sleep(1.0)
        _h = _holding(_wb) or {}
        eq('[waybill last] (the premise: a card-box read without the shape files nothing; the '
           'corner is held)', (_h.get('dropoff'), _h.get('dropoffScanned')),
           ('Wren Flat Ct & Oriel Rd, Marietta', False))
        # ...and a press on it is the press's rule: the cropped block is no answer.
        _wsay(_wread(_wtext, asked=True))
        time.sleep(1.0)
        eq('[waybill last] ...nor a pressed one', (_holding(_wb) or {}).get('dropoff'),
           'Wren Flat Ct & Oriel Rd, Marietta')
        _wsay(_wread(_wtext))
        _h = _settled(_wb, lambda h: h.get('dropoffScanned'))
        eq('[waybill last] the 21 Oct 15:00 card-box read files the trip\'s last stop over the '
           'card\'s corner', (_h.get('dropoff'), _h.get('dropoffScanned')),
           ('3259 Wrenfield Oaks Dr, Marietta', True))
    finally:
        stop(_wp)

    _bj = os.path.join(_adir, 'b', 'offers.jsonl')
    os.makedirs(os.path.dirname(_bj))
    open(_bj, 'w').close()
    _bp, _bb = start({'SCANNER': '0', 'NUCBOX_SEARCH': _stub_base,
                      'NUCBOX_TIMEOUT_MS': '3000', 'NUCBOX_RETRY_MS': '1500'}, _bj)
    try:
        _Stub.mode = 'down'
        _Stub.searches[:] = []
        _atook(_bb, 'b-down', _COBB)
        time.sleep(4.0)
        _h = _holding(_bb) or {}
        eq('[auto arm] NucBox down: no arm, said, and asked exactly once more',
           (_h.get('endPinned'), _h.get('endWhy'), len(_Stub.searches)),
           (False, 'NucBox down', 2))
        post(_bb, '/api/delivered', {})

        # The answer for an order already put down lands on nothing.
        _Stub.mode = 'slow'
        _atook(_bb, 'b-old', _COBB)
        time.sleep(0.3)
        post(_bb, '/api/delivered', {})
        _atook(_bb, 'b-new', None)
        time.sleep(2.0)
        _h = _holding(_bb) or {}
        eq('[auto arm] a pin searched for an old hold never applies to the next',
           (_h.get('holdId', '').startswith('b-new'), _h.get('endPinned'), _h.get('endWhy')),
           (True, False, None))
    finally:
        stop(_bp)

    _cj = os.path.join(_adir, 'c', 'offers.jsonl')
    os.makedirs(os.path.dirname(_cj))
    open(_cj, 'w').close()
    _cp, _cb = start({'SCANNER': '0'}, _cj)
    try:
        _n = len(_aasked('')), len(_Stub.searches)
        _atook(_cb, 'c-unset', _COBB)
        time.sleep(1.0)
        _h = _holding(_cb) or {}
        eq('[auto arm] with NUCBOX_SEARCH unset nothing is sent and nothing is said',
           ((len(_aasked('')), len(_Stub.searches)), _h.get('endPinned'), _h.get('endWhy')),
           (_n, False, None))
        eq('[auto arm] ...nor of its pickups, though none has a house number',
           (_h.get('pickupsPinned'), _h.get('pickupsWhy')), (0, None))
    finally:
        stop(_cp)
    # ...and that same hold, restored at boot by a server that now has the
    # NucBox set: searched for at once (armHeldEnd in loadHolding), with no
    # Took, ⌖ or dropoff line to set it off.
    _cp, _cb = start({'SCANNER': '0', 'NUCBOX_SEARCH': _afake_base,
                      'NUCBOX_TIMEOUT_MS': '800'}, _cj)
    try:
        _h = _settled(_cb)
        eq('[auto arm] a hold restored at boot is searched for, and arms',
           (_h.get('holdId', '').startswith('c-unset'), _h.get('endPinned'), _h.get('endBy')),
           (True, True, 'server'))
    finally:
        stop(_cp)

    # A reason is said only of the dropoff it was given for (endWhyFor). The
    # order's first dropoff refused, then the server restarted with no NucBox
    # and a ⌖ read moving the end: nothing searched the new text, so nothing
    # may be said about it — the old "no house number" was about the old one.
    _dj = os.path.join(_adir, 'd', 'offers.jsonl')
    os.makedirs(os.path.dirname(_dj))
    open(_dj, 'w').close()
    _dp, _db = start({'SCANNER': '0', 'NUCBOX_SEARCH': _afake_base,
                      'NUCBOX_TIMEOUT_MS': '800'}, _dj)
    try:
        _atook(_db, 'd-why', _KES)
        _h = _settled(_db)
        eq('[auto arm] (the premise: the order\'s first dropoff was refused)',
           _h.get('endWhy'), 'street found, not that door')
    finally:
        stop(_dp)
    _dfake = os.path.join(_adir, 'd', 'scan.py')
    with open(_dfake, 'w') as _fh:
        _fh.write('import json, time\n'
                  'time.sleep(0.5)\n'
                  'print(json.dumps({"dropoff": {"line": "1985 Cobb Parkway, Kennesaw, GA 30152",\n'
                  '    "street": "1985 Cobb Parkway", "city": "Kennesaw", "state": "GA",\n'
                  '    "zip": "30152", "found": True, "asked": True,\n'
                  '    "at": int(time.time() * 1000)}}), flush=True)\n'
                  'time.sleep(600)\n')
    _dp, _db = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable,
                      'SCANNER_ARGS': _dfake}, _dj)
    try:
        _h = _settled(_db, lambda h: (h.get('dropoff') or '').startswith('1985'))
        eq('[auto arm] a reason given for an earlier dropoff is not said of a new one',
           (_h.get('dropoff'), _h.get('endPinned'), _h.get('endWhy')),
           ('1985 Cobb Parkway, Kennesaw, GA 30152', False, None))
    finally:
        stop(_dp)
finally:
    _afake.kill()
    _stub.shutdown()
    shutil.rmtree(_adir, ignore_errors=True)


# --- the held order's pickups, searched for by the server --------------------
#
# The restaurant guard (pickupNearEnd) without Map view: when a Trip Planner
# read lands on the hold and NUCBOX_SEARCH is set, server.js asks the NucBox
# for each pickup that has a street (searchHeldPickup), inside the HELD card's
# disc, and keeps the position as /api/held-pickup does (keepPickupPin). The
# fake's "1975 Cobb Parkway" is a restaurant 87 m from the door at 1985 Cobb
# Parkway, inside the guard's 150 m; "250 Example Road" one 1.66 mi from the
# Square. Addresses and points invented.
_hkfake = subprocess.Popen(['node', os.path.join(ROOT, 'tests', 'fake-nucbox.js')],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
_hkfake_base = 'http://127.0.0.1:%d' % json.loads(_hkfake.stdout.readline())['port']


def _hkasked(word):
    return [a for a in json.loads(urllib.request.urlopen(
        _hkfake_base + '/__asked', timeout=5).read()) if word in a]


_hkdir = tempfile.mkdtemp()


def _hksayer(name):
    """A scanner of its own in _hkdir/name, saying each line of say-N.json in
    turn a quarter of a second apart (a heartbeat's `at` made now): planner
    reads and GPS beats alike. Returns its script and the function that has
    it say a list of lines and waits until it has."""
    d = os.path.join(_hkdir, name)
    os.makedirs(d)
    script = os.path.join(d, 'say.py')
    with open(script, 'w') as fh:
        fh.write(
            'import json, os, time\n'
            'd = os.path.dirname(os.path.abspath(__file__))\n'
            'n = 0\n'
            'end = time.time() + 600\n'
            'while time.time() < end:\n'
            '    p = os.path.join(d, "say-%d.json" % n)\n'
            '    if not os.path.exists(p):\n'
            '        time.sleep(0.05)\n'
            '        continue\n'
            '    for x in json.load(open(p)):\n'
            '        if x.get("alive"):\n'
            '            x["at"] = int(time.time() * 1000)\n'
            '        print(json.dumps(x), flush=True)\n'
            '        time.sleep(0.25)\n'
            '    open(os.path.join(d, "done-%d" % n), "w").close()\n'
            '    n += 1\n')
    seq = [0]

    def says(lines):
        n = seq[0]
        seq[0] += 1
        path = os.path.join(d, 'say-%d.json' % n)
        with open(path + '.tmp', 'w') as fh:
            json.dump(lines, fh)
        os.rename(path + '.tmp', path)
        for _ in range(400):
            if os.path.exists(os.path.join(d, 'done-%d' % n)):
                break
            time.sleep(0.05)
        time.sleep(0.3)
    open(os.path.join(d, 'offers.jsonl'), 'w').close()
    return script, says, os.path.join(d, 'offers.jsonl')


def _hkplanner(*picks):
    """A Trip Planner read: each pickup (name, street or None), then a dropoff."""
    stops = [{'kind': 'pickup', 'orders': 1, 'name': n, 'expectedBy': 1189, 'street': s,
              'city': None, 'state': None, 'zip': None, 'line': s} for n, s in picks]
    stops.append({'kind': 'dropoff', 'orders': 1, 'name': 'Pat Q.', 'street': None,
                  'city': None, 'state': None, 'zip': None, 'line': None})
    return {'planner': {'stops': stops, 'unfiled': 'dropoffs', 'asked': False}}


_HK_DOOR = (34.0010, -84.5560)    # the fake's three answers' middle


def _hkbeat(dlat):
    return {'alive': True, 'gps': {'state': 'ok', 'ageSeconds': 0.1, 'fix': {
        'lat': _HK_DOOR[0] + dlat, 'lon': _HK_DOOR[1], 'gpsAge': 0.1, 'gpsErr': 25.0,
        'gpsMode': 3, 'gpsOk': True, 'gpsWhy': None, 'freshFor': 10.0}}}


class _HkDown(object):
    """A NucBox that answers every search 503, counting them."""
    searches = []


def _hkdown_app():
    import http.server

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            _HkDown.searches.append(self.path)
            self.send_response(503)
            self.end_headers()
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


_hkdown = _hkdown_app()
try:
    _hks, _hksays, _hkj = _hksayer('a')
    _hkp, _hkb = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable, 'SCANNER_ARGS': _hks,
                        'NUCBOX_SEARCH': _hkfake_base, 'NUCBOX_TIMEOUT_MS': '800',
                        'GPS_DWELL_MS': '1000'}, _hkj)
    try:
        # The end armed by the server, then the planner read: no Map view.
        _atook(_hkb, 'k-guard', _COBB)
        _settled(_hkb, lambda h: h.get('endPinned'))
        _hksays([_hkplanner(('Example Diner', '1975 Cobb Parkway'))])
        _h = _settled(_hkb, lambda h: h.get('pickupsPinned'))
        _q = _hkasked('street=1975')
        ok_('[held pickups] a planner pickup with a street is searched on the NucBox inside '
            'the held card\'s disc and kept for the guard, with no Map view (%r)' % _q[:1],
            _h.get('pickupsPinned') == 1 and len(_q) == 1 and 'viewbox=' in _q[0]
            and 'bounded=1' in _q[0])
        eq('[held pickups] ...so the door the server armed 87 m from it is not armed, and '
           'says why', (_h.get('endPinned'), _h.get('endWhy')), (True, 'door next to the pickup'))
        eq('[held pickups] ...and /api/status says how: by the server, from the planner',
           _h.get('pickupsHow'), [{'by': 'server', 'from': 'planner', 'asked': None}])
        post(_hkb, '/api/delivered', {})

        # A planner pickup with a street and no house number: door level only
        # (pickupDoorPlan, the owner's decision of 18 Oct), so not asked.
        _atook(_hkb, 'k-nonum', _COBB)
        _settled(_hkb, lambda h: h.get('endPinned'))
        _n = len(_hkasked(''))
        _hksays([_hkplanner(('Example Diner', 'Cobb Parkway'))])
        _h = _settled(_hkb, lambda h: (h.get('planner') or {}).get('stops'))
        time.sleep(0.3)
        eq('[held pickups] a planner pickup with no house number is not asked, and /api/status '
           'says why', (_hkasked('')[_n:], _h.get('pickupsPinned'),
                        (_holding(_hkb) or {}).get('pickupsWhy')), ([], 0, 'no house number'))
        post(_hkb, '/api/delivered', {})

        # A door whose town line was lost (19 Oct: "840 <Name> W. <Name>
        # Parkway" alone): a house number and a street type is still a door
        # search inside the disc, for the held end and the pickup alike.
        post(_hkb, '/api/offers/mark', {'id': 'k-notown', 'accepted': True, 'offer': dict(
            _SQ, id='k-notown', pay=12.0, minutes=40.0, billedMinutes=40.0, miles=5.0,
            cost=1.75, dropoff='1985 Cobb Parkway', pickupLine='1975 Cobb Parkway')})
        _h = _settled(_hkb, lambda h: h.get('endWhy') and h.get('pickupsPinned'))
        eq('[held pickups] a door with no town is asked inside the disc, end and pickup both, '
           'and pinned at door level',
           (_h.get('pickupsPinned'), _h.get('endPinned'), _h.get('endWhy'),
            (_h.get('pickupsHow') or [{}])[0].get('from')),
           (1, True, 'door next to the pickup', 'card'))
        post(_hkb, '/api/delivered', {})

        # (23 Oct) No door anywhere on record — the card's pickup is the store's
        # name alone — and the store is asked by its NAME inside the held card's
        # disc, pinned where one place of that name answers...
        post(_hkb, '/api/offers/mark', {'id': 'k-name', 'accepted': True, 'offer': dict(
            _SQ, id='k-name', pay=12.0, minutes=40.0, billedMinutes=40.0, miles=5.0,
            cost=1.75, dropoff=_COBB, pickup='Example Grill')})
        _h = _settled(_hkb, lambda h: h.get('pickupsPinned'))
        _qn = _hkasked('q=Example')
        eq('[held pickups] a card\'s pickup with no door is asked by its store\'s name inside the '
           'disc, and pinned where one place answers',
           (_h.get('pickupsPinned'), _h.get('pickupsHow'), len(_qn),
            'viewbox=' in (_qn[0] if _qn else '')),
           (1, [{'by': 'server', 'from': 'card', 'asked': None}], 1, True))
        post(_hkb, '/api/delivered', {})
        # ...and a chain's several branches inside the disc are no pin.
        post(_hkb, '/api/offers/mark', {'id': 'k-chain', 'accepted': True, 'offer': dict(
            _SQ, id='k-chain', pay=12.0, minutes=40.0, billedMinutes=40.0, miles=5.0,
            cost=1.75, dropoff=_COBB, pickup='Starbucks')})
        _h = _settled(_hkb, lambda h: h.get('pickupsWhy') not in (None,))
        time.sleep(0.5)
        _h = _holding(_hkb) or {}
        # (The fake's twelve Starbucks are more than the ten asked for: capped.)
        eq('[held pickups] ...but a chain\'s branches in the disc pin nothing, and say so',
           (_h.get('pickupsPinned'), _h.get('pickupsWhy')), (0, 'too many answers'))
        post(_hkb, '/api/delivered', {})

        # The end armed AND arrived at — the car waiting at the restaurant —
        # before the planner read says where the restaurant is.
        _atook(_hkb, 'k-late', _COBB)
        _settled(_hkb, lambda h: h.get('endPinned'))
        _hksays([_hkbeat(0.0002)] * 7)
        ok_('[held pickups] (the premise: the car waiting there arrived at the door)',
            (_holding(_hkb) or {}).get('arrived'))
        _hksays([_hkplanner(('Example Diner', '1975 Cobb Parkway'))])
        _h = _settled(_hkb, lambda h: h.get('pickupsPinned'))
        eq('[held pickups] a pickup that lands after the end was armed asks the guard again: '
           'the arrival counted at the restaurant is taken back',
           (_h.get('arrived'), _h.get('endWhy'), _h.get('pickupsPinned')),
           (False, 'door next to the pickup', 1))
        post(_hkb, '/api/delivered', {})

        # A held card of 1.0 mi: its disc is 1.5 mi, and the restaurant at
        # 250 Example Road is 1.66 mi from its fix.
        _atook(_hkb, 'k-far', _COBB, miles=1.0)
        _settled(_hkb)
        _n = len(_hkasked('street=250'))
        _hksays([_hkplanner(('Example Grill', '250 Example Road'))])
        for _ in range(60):
            if len(_hkasked('street=250')) > _n:
                break
            time.sleep(0.05)
        time.sleep(0.3)
        time.sleep(0.3)
        eq('[held pickups] a pickup the NucBox places outside the held card\'s disc is asked, '
           'once more without its street\'s type word (as the end is), and not kept',
           (len(_hkasked('street=250')) - _n, (_holding(_hkb) or {}).get('pickupsPinned'),
            (_holding(_hkb) or {}).get('pickupsWhy')),
           (2, 0, 'not inside the card\'s reach'))
        post(_hkb, '/api/delivered', {})
    finally:
        stop(_hkp)

    # The owner's snap of 24 Oct, invented: the planner's door "<number>
    # <Name> Mill Rd SE", two doors of that number answered inside the held
    # card's disc a few hundred metres apart, refused 'several answers' and
    # nothing routed. The refusal now keeps their general area (MV's
    # withArea) for Map view's run, `endArea` on /api/status — and it is NO
    # PIN: endPinned false, endWhy still the refusal, nothing posted as the
    # door, and a car that waits there and leaves drops nothing.
    _hks, _hksays, _hkj = _hksayer('area')
    _hkp, _hkb = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable, 'SCANNER_ARGS': _hks,
                        'NUCBOX_SEARCH': _hkfake_base, 'NUCBOX_TIMEOUT_MS': '800',
                        'GPS_DWELL_MS': '1000'}, _hkj)

    def _areabeat(lat, lon):
        return {'alive': True, 'gps': {'state': 'ok', 'ageSeconds': 0.1, 'fix': {
            'lat': lat, 'lon': lon, 'gpsAge': 0.1, 'gpsErr': 25.0, 'gpsMode': 3,
            'gpsOk': True, 'gpsWhy': None, 'freshFor': 10.0}}}
    try:
        _atook(_hkb, 'k-area', '3150 Thornbury Mill Rd SE, Marietta')
        _h = _settled(_hkb)
        _ea = _h.get('endArea') or {}
        eq('[area] two doors 0.33 mi apart inside the held card\'s disc: no pin, the refusal '
           'still says why, and their general area kept beside it, approximate',
           (_h.get('endPinned'), _h.get('endBy'), _h.get('endAt'), _h.get('endWhy'),
            _ea.get('approx'), _ea.get('n'), round(_ea.get('lat') or 0, 4),
            round(_ea.get('lon') or 0, 4)),
           (False, None, None, 'several answers', True, 2, 33.962, -84.5435))
        _s, _r = post(_hkb, '/api/held-end', {
            'holdId': _h.get('holdId'), 'dropoff': '3150 Thornbury Mill Rd SE, Marietta',
            'lat': _ea.get('lat'), 'lon': _ea.get('lon'), 'name': 'Thornbury Mill Road',
            'doorLevel': False})
        eq('[area] ...the area posted as the held end is refused as not door level',
           (_s, _r.get('error'), (_holding(_hkb) or {}).get('endPinned')),
           (409, 'not door level', False))
        _hksays([_areabeat(_ea.get('lat'), _ea.get('lon'))] * 7
                + [_areabeat(_ea.get('lat') + 0.02, _ea.get('lon'))] * 3)
        _h = _holding(_hkb) or {}
        eq('[area] ...a car that waits at the area and leaves arrives nowhere and drops nothing',
           (_h.get('dropoff'), _h.get('arrived'), _h.get('endPinned'), _h.get('endWhy')),
           ('3150 Thornbury Mill Rd SE, Marietta', False, False, 'several answers'))
        post(_hkb, '/api/delivered', {})
        _atook(_hkb, 'k-area-far', '3152 Thornbury Mill Rd SE, Marietta')
        _h = _settled(_hkb)
        eq('[area] two doors 2.5 mi apart are no area: refused as ever, nothing kept',
           (_h.get('endPinned'), _h.get('endWhy'), _h.get('endArea')),
           (False, 'several answers', None))
        post(_hkb, '/api/delivered', {})
    finally:
        stop(_hkp)

    # The owner's DoorDash snap of 24 Oct, 19:23-19:25, invented: "It is
    # better to route something than nothing at all." A door the NucBox's list
    # was cut on, its answers one area, and a door NOTHING answered, its
    # street short in the index: each keeps an area beside its refusal for
    # Map view's run (`cut`, `rough`), and NEITHER is a pin — endPinned false,
    # the GPS drop not armed by a car waiting there, and a held pickup's
    # area never enters pickupPins (the restaurant guard's).
    _hks, _hksays, _hkj = _hksayer('area-more')
    _hkp, _hkb = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable, 'SCANNER_ARGS': _hks,
                        'NUCBOX_SEARCH': _hkfake_base, 'NUCBOX_STREETS': _hkfake_base,
                        'NUCBOX_TIMEOUT_MS': '800', 'GPS_DWELL_MS': '1000'}, _hkj)
    try:
        _atook(_hkb, 'k-cut', '10800 Vessington Hwy, Marietta')
        _h = _settled(_hkb)
        _ea = _h.get('endArea') or {}
        eq('[area more] a cut list whose ten answers are one area: no pin, "too many answers", '
           'the area kept and marked cut',
           (_h.get('endPinned'), _h.get('endAt'), _h.get('endWhy'), _ea.get('approx'),
            _ea.get('cut'), _ea.get('n'), _ea.get('rough')),
           (False, None, 'too many answers', True, True, 10, None))
        _hksays([_areabeat(_ea.get('lat'), _ea.get('lon'))] * 7
                + [_areabeat(_ea.get('lat') + 0.02, _ea.get('lon'))] * 3)
        _h = _holding(_hkb) or {}
        eq('[area more] ...a car that waits at it and leaves arrives nowhere and drops nothing',
           (_h.get('dropoff'), _h.get('arrived'), _h.get('endPinned')),
           ('10800 Vessington Hwy, Marietta', False, False))
        post(_hkb, '/api/delivered', {})
        _n = len(_hkasked('/api/streets/whole?name=Pellmore'))
        _atook(_hkb, 'k-street', '10495 Pellmore Street, Marietta')
        _h = _settled(_hkb)
        _ea = _h.get('endArea') or {}
        eq('[area more] a door nothing answered: its street asked alone, once, of the index; no '
           'pin, the refusal kept, the street\'s rough area beside it',
           (_h.get('endPinned'), _h.get('endAt'), _h.get('endWhy'), _ea.get('approx'),
            _ea.get('rough'), round(_ea.get('lat') or 0, 4),
            len(_hkasked('/api/streets/whole?name=Pellmore')) - _n),
           (False, None, 'not inside the card\'s reach', True, True, 33.958, 1))
        _hksays([_areabeat(_ea.get('lat'), _ea.get('lon'))] * 7
                + [_areabeat(_ea.get('lat') + 0.02, _ea.get('lon'))] * 3)
        _h = _holding(_hkb) or {}
        eq('[area more] ...and waiting there drops nothing either',
           (_h.get('arrived'), _h.get('endPinned')), (False, False))
        post(_hkb, '/api/delivered', {})
        _atook(_hkb, 'k-long', '10497 Dunmere Parkway, Marietta')
        _h = _settled(_hkb)
        eq('[area more] a door nothing answered on a street too long to be one area: refused, '
           'no area', (_h.get('endPinned'), _h.get('endWhy'), _h.get('endArea')),
           (False, 'not inside the card\'s reach', None))
        post(_hkb, '/api/delivered', {})
        # A held pickup whose door is the cut list's: the area is the page's
        # to draw and nothing of it is kept as a pin.
        _atook(_hkb, 'k-pick', _COBB)
        _settled(_hkb, lambda h: h.get('endPinned'))
        _hksays([_hkplanner(('Example Cafe', '10800 Vessington Hwy'))])
        _h = _settled(_hkb, lambda h: h.get('pickupsWhy'))
        eq('[area more] a held pickup whose answers are one area is no pin: none kept for the '
           'guard, the refusal said, and the armed door stays armed',
           (_h.get('pickupsPinned'), _h.get('pickupsWhy'), _h.get('endPinned'),
            'pickupAreas' in _h),
           (0, 'too many answers', True, False))
        post(_hkb, '/api/delivered', {})
    finally:
        stop(_hkp)

    # The distance band (the owner, 25 Oct: "Go ahead with the distance
    # band"), invented: an Uber order held whose card printed 5.0 mi, 4.3 of
    # them to the pickup, so a 0.7 mi trip; its door "3152 <Name> Mill Rd SE"
    # answered as two doors 2.5 mi apart inside the disc, refused 'several
    # answers' with no area. When its one pickup is pinned, the router is asked
    # the road from it to each door, and the one 0.73 road mi off is kept as
    # the end's AREA (`band`) — NO PIN: endPinned false, the refusal kept, and
    # a car that waits there and leaves drops nothing. With the router down,
    # nothing is kept and the refusal stands as it was.
    def _bandtook(base, oid):
        o = dict(_SQ, id=oid, pay=12.0, minutes=40.0, billedMinutes=40.0, miles=5.0,
                 toPickupMiles=4.3, cost=1.75, dropoff='3152 Thornbury Mill Rd SE, Marietta')
        post(base, '/api/offers/mark', {'id': oid, 'accepted': True, 'offer': o})

    for _bwhich, _broute in (('up', _hkfake_base), ('down', 'http://127.0.0.1:9')):
        _hks, _hksays, _hkj = _hksayer('band-' + _bwhich)
        _hkp, _hkb = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable, 'SCANNER_ARGS': _hks,
                            'NUCBOX_SEARCH': _hkfake_base, 'NUCBOX_ROUTER': _broute,
                            'NUCBOX_TIMEOUT_MS': '800', 'GPS_DWELL_MS': '1000'}, _hkj)
        try:
            _bandtook(_hkb, 'k-band-' + _bwhich)
            _h = _settled(_hkb)
            eq('[band] (%s) the two doors refused, no area of their own before the pickup is '
               'placed' % _bwhich, (_h.get('endPinned'), _h.get('endWhy'), _h.get('endArea')),
               (False, 'several answers', None))
            post(_hkb, '/api/held-pickup', {'holdId': _h.get('holdId'), 'lat': 33.9526,
                                            'lon': -84.5499, 'q': 'Example Cafe'})
            if _bwhich == 'up':
                _h = _settled(_hkb, lambda h: (h.get('endArea') or {}).get('band'))
                _ea = _h.get('endArea') or {}
                eq('[band] the pickup placed: the door whose road from it fits the card\'s 0.7 mi '
                   'trip kept as the end\'s area, the band\'s — still no pin, the refusal kept',
                   (_h.get('endPinned'), _h.get('endBy'), _h.get('endAt'), _h.get('endWhy'),
                    _ea.get('approx'), _ea.get('band'), _ea.get('n'), _ea.get('cardMi'),
                    round(_ea.get('lat') or 0, 4), round(_ea.get('lon') or 0, 4)),
                   (False, None, None, 'several answers', True, True, 1, 0.7, 33.96, -84.545))
                eq('[band] ...asked of the router as two-point routes, no more than the doors',
                   len([a for a in _hkasked('/route/v1/driving/-84.549900,33.952600;')
                        if 'overview=false' in a]) >= 2, True)
                _hksays([_areabeat(_ea.get('lat'), _ea.get('lon'))] * 7
                        + [_areabeat(_ea.get('lat') + 0.02, _ea.get('lon'))] * 3)
                _h = _holding(_hkb) or {}
                eq('[band] ...a car that waits at the band\'s area and leaves arrives nowhere and '
                   'drops nothing', (_h.get('dropoff'), _h.get('arrived'), _h.get('endPinned'),
                                     _h.get('endWhy')),
                   ('3152 Thornbury Mill Rd SE, Marietta', False, False, 'several answers'))
            else:
                time.sleep(1.5)
                _h = _holding(_hkb) or {}
                eq('[band] the router down: no band, the refusal as it was, nothing kept',
                   (_h.get('endPinned'), _h.get('endWhy'), _h.get('endArea')),
                   (False, 'several answers', None))
            post(_hkb, '/api/delivered', {})
        finally:
            stop(_hkp)

    # The owner's snap of 24 Oct, 03:03, invented: one Uber trip, ONE pickup
    # ("Pickup • 2 orders") and two dropoffs. Page 1 of the Trip Planner read
    # the pickup with its door, the first dropoff and the second's header and
    # nothing more; page 2, scrolled, the second dropoff alone — and each read
    # replaced the last on the hold, so the restaurant went before anything
    # pinned it. Now the pages merge on the hold (Assemble.mergePlanner).
    # Read while the NucBox is DOWN, so the pickup's one ask fails; restarted
    # with it up, the hold asks at boot what its planner keeps — the page-1
    # pickup only if it was kept. The end stays the card's door, armed alone:
    # the first dropoff is drawing only, and a car that waits at it and
    # leaves drops nothing.
    _mpdir = os.path.join(_hkdir, 'pages')
    _mps, _mpsays, _ = _hksayer('pages-say')
    os.makedirs(_mpdir)
    _mpj = os.path.join(_mpdir, 'offers.jsonl')
    open(_mpj, 'w').close()
    _MP_NONE = {'city': None, 'state': None, 'zip': None, 'place': None}
    _mp1 = {'planner': {'stops': [
        dict(_MP_NONE, kind='pickup', orders=2, name='Example Grill', expectedBy=None,
             street='250 Example Road', line='250 Example Road'),
        dict(_MP_NONE, kind='dropoff', orders=1, name='Pat Q.', expectedBy=1403,
             street='4821 Kestrel Dr', city='Marietta', line='4821 Kestrel Dr, Marietta'),
        dict(_MP_NONE, kind='dropoff', orders=1, name=None, expectedBy=None, street=None,
             line=None)], 'unfiled': 'dropoffs', 'asked': False}}
    _mp2 = {'planner': {'stops': [
        dict(_MP_NONE, kind='dropoff', orders=1, name='Lee R.', expectedBy=1416,
             street='1985 Cobb Parkway', city='Kennesaw', line='1985 Cobb Parkway, Kennesaw')],
        'unfiled': None, 'asked': False}}

    def _mpstops(h):
        return [(x.get('kind'), x.get('name'), x.get('line'))
                for x in ((h or {}).get('planner') or {}).get('stops') or []]
    # ...and then a ⌖ press over page 2 (the owner, 24 Oct: "Would there be a
    # way to have the scan button also merge?"): its read MERGES too, the
    # press's fields winning — Pat Q.'s door as the press read it, "4823",
    # over the fuller "4821 …, Marietta" kept — and page 1's pickup, which
    # the pressed page does not show, still kept.
    _mp3 = {'planner': {'stops': [
        dict(_MP_NONE, kind='dropoff', orders=1, name='Pat Q.', expectedBy=1403,
             street='4823 Kestrel Dr', line='4823 Kestrel Dr'),
        dict(_MP_NONE, kind='dropoff', orders=1, name='Lee R.', expectedBy=1416,
             street='1985 Cobb Parkway', city='Kennesaw', line='1985 Cobb Parkway, Kennesaw')],
        'unfiled': 'dropoffs', 'asked': True}}
    _mphand = os.path.join(_mpdir, 'handoff')
    os.makedirs(_mphand)
    _mpp, _mpb = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable, 'SCANNER_ARGS': _mps,
                        'NUCBOX_SEARCH': 'http://127.0.0.1:%d' % _hkdown.server_address[1],
                        'NUCBOX_RETRY_MS': '60000', 'UBERSCAN_HANDOFF_DIR': _mphand}, _mpj)
    try:
        _atook(_mpb, 'k-pages', _COBB)
        _mpsays([_mp1, _mp2])
        _h = _holding(_mpb) or {}
        eq('[planner pages] two pages on one hold are merged: page 1\'s pickup kept with its '
           'door, page 2\'s dropoff in place of the header page 1 cut off',
           _mpstops(_h),
           [('pickup', 'Example Grill', '250 Example Road'),
            ('dropoff', 'Pat Q.', '4821 Kestrel Dr, Marietta'),
            ('dropoff', 'Lee R.', '1985 Cobb Parkway, Kennesaw')])
        eq('[planner pages] ...and the end is still the card\'s, not filed off a planner line',
           (_h.get('dropoff'), _h.get('batch')), (_COBB, False))
        _s, _ = post(_mpb, '/api/dropoff', {})
        eq('[press merge] a ⌖ press keeps the pages the hold merged (it forgot them)',
           (_s, len(_mpstops(_holding(_mpb)))), (200, 3))
        _mpsays([_mp3])
        eq('[press merge] the pressed page merges into them: page 1\'s pickup kept, the '
           'pressed read\'s door winning over the fuller one kept',
           _mpstops(_holding(_mpb)),
           [('pickup', 'Example Grill', '250 Example Road'),
            ('dropoff', 'Pat Q.', '4823 Kestrel Dr'),
            ('dropoff', 'Lee R.', '1985 Cobb Parkway, Kennesaw')])
        eq('[press merge] ...its reason the pressed read\'s, and the end still the card\'s',
           (((_holding(_mpb) or {}).get('planner') or {}).get('unfiled'),
            (_holding(_mpb) or {}).get('dropoff')), ('dropoffs', _COBB))
    finally:
        stop(_mpp)
    # (A scanner of its own: the first one's would say its pages again.)
    _mps, _mpsays, _ = _hksayer('pages-say2')
    _mpp, _mpb = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable, 'SCANNER_ARGS': _mps,
                        'NUCBOX_SEARCH': _hkfake_base, 'NUCBOX_TIMEOUT_MS': '800',
                        'GPS_DWELL_MS': '1000'}, _mpj)

    def _mpbeat(lat, lon):
        return {'alive': True, 'gps': {'state': 'ok', 'ageSeconds': 0.1, 'fix': {
            'lat': lat, 'lon': lon, 'gpsAge': 0.1, 'gpsErr': 25.0, 'gpsMode': 3,
            'gpsOk': True, 'gpsWhy': None, 'freshFor': 10.0}}}
    try:
        _h = _settled(_mpb, lambda h: h.get('pickupsPinned') and h.get('endPinned'))
        eq('[planner pages] restarted with the NucBox up, the pickup only page 1 showed is '
           'asked and pinned, from the planner, and the end armed at its own door',
           (_h.get('pickupsPinned'), _h.get('pickupsHow'), _h.get('endPinned'),
            _h.get('dropoff')),
           (1, [{'by': 'server', 'from': 'planner', 'asked': None}], True, _COBB))
        _s, _r = post(_mpb, '/api/held-end', {
            'holdId': _h.get('holdId'), 'dropoff': '4821 Kestrel Dr, Marietta',
            'lat': 33.9700, 'lon': -84.5300, 'name': 'Kestrel Drive', 'doorLevel': True})
        eq('[planner pages] the first dropoff posted as the held end is refused: the GPS drop '
           'arms on the end alone', (_s, (_holding(_mpb) or {}).get('dropoff')), (409, _COBB))
        # Kestrel Drive, the fake's point for the first dropoff's street.
        _mpsays([_mpbeat(33.9700, -84.5300)] * 7 + [_mpbeat(33.9900, -84.5300)] * 3)
        _h = _holding(_mpb) or {}
        eq('[planner pages] ...and a car that waits at the first dropoff and leaves drops '
           'nothing: still held, its end armed at its own door, nothing arrived',
           (bool(_h), _h.get('dropoff'), _h.get('endPinned'), _h.get('arrived')),
           (True, _COBB, True, False))
        post(_mpb, '/api/delivered', {})
        # A NEW trip after that one ends starts with no planner: its first
        # page is all it keeps.
        _atook(_mpb, 'k-pages-next', _COBB)
        _mpsays([_mp2])
        eq('[planner pages] the next order\'s planner merges with nothing of the last',
           _mpstops(_holding(_mpb)), [('dropoff', 'Lee R.', '1985 Cobb Parkway, Kennesaw')])
        post(_mpb, '/api/delivered', {})
    finally:
        stop(_mpp)

    # A held card stamped ROUGH, its end filed by the Trip Planner: the
    # owner's 17 Oct afternoon. The card's fix was mode 3, 0.2 s old, 73 m —
    # usable() said `rough` — and /api/status said endWhy 'no card fix' for
    # the whole delivery, so the end was never searched and GPS arrival never
    # armed. MV.discFor now centres the disc on a fix refused only as rough,
    # widened by its error (ROUGH_DISC_MAX_M), so the planner's door is
    # searched, pinned and arrived at. And one over the cap is still no disc.
    # The Square fixture and the fake's invented door; no real place.
    _hks, _hksays, _hkj = _hksayer('rough')
    _hkp, _hkb = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable, 'SCANNER_ARGS': _hks,
                        'NUCBOX_SEARCH': _hkfake_base, 'NUCBOX_TIMEOUT_MS': '800',
                        'GPS_DWELL_MS': '1000'}, _hkj)

    def _rough_took(oid, err):
        o = dict(_SQ, id=oid, pay=12.0, minutes=40.0, billedMinutes=40.0, miles=10.3,
                 cost=1.75, gpsOk=False, gpsWhy='rough', gpsErr=err, gpsMode=3, gpsAge=0.2)
        post(_hkb, '/api/offers/mark', {'id': oid, 'accepted': True, 'offer': o})

    def _planner_end(street='1985 Cobb Parkway'):
        """A whole Trip Planner page, unpressed, its sighting then its planner
        line under one stamp (as Stage 3 sends them): an invented pickup with
        no NucBox answer, and the fake's door as the order's end."""
        at = int(time.time() * 1000)
        stops = [{'kind': 'pickup', 'orders': 1, 'name': 'Example Wok', 'place': None,
                  'expectedBy': 1180, 'street': '2210 Quarry Bend Rd NW', 'city': 'Kennesaw',
                  'state': 'GA', 'zip': None, 'line': '2210 Quarry Bend Rd NW, Kennesaw',
                  'partial': None, 'label': 'pickup'},
                 {'kind': 'dropoff', 'orders': 1, 'name': 'Pat Q.', 'place': None,
                  'expectedBy': 1202, 'street': street, 'city': 'Kennesaw',
                  'state': 'GA', 'zip': None, 'line': street + ', Kennesaw',
                  'partial': None, 'label': 'dropoff'}]
        _hksays([{'sighting': {'at': at, 'asked': False, 'whole': True, 'titled': True,
                               'app': 'uber', 'screen': 'uber.planner',
                               'page': {'top': True, 'bottom': True}, 'stops': stops,
                               'orderCount': 1, 'keep': False}},
                 {'planner': {'stops': [{k: v for k, v in s.items()
                                         if k not in ('partial', 'label')} for s in stops],
                              'keep': False, 'asked': False, 'ms': None, 'at': at}}])

    try:
        _rough_took('k-rough', 73.0)
        _planner_end()
        _h = _settled(_hkb, lambda h: h.get('endPinned') or h.get('endWhy'))
        eq('[rough disc] a held card stamped rough (73 m, mode 3, 0.2 s), its door filed by '
           'the Trip Planner: searched, pinned by the server, armed — not "no card fix"',
           (_h.get('dropoff'), ((_h.get('fields') or {}).get('dropoff') or {}).get('from'),
            _h.get('endPinned'), _h.get('endBy'), _h.get('endWhy')),
           ('1985 Cobb Parkway, Kennesaw', 'planner', True, 'server', None))
        _hksays([_hkbeat(0.0002)] * 7)
        ok_('[rough disc] ...and the GPS arrival at it counts (arrived)',
            (_holding(_hkb) or {}).get('arrived'))
        post(_hkb, '/api/delivered', {})

        # 19 Oct night: the planner's dropoff read "1106 Commor" on several
        # frames, then "1106 Commons Ln". A later reading of the SAME stop
        # whose street names its type replaces the one that did not, and the
        # end is searched again for the new text.
        _rough_took('k-typed', 25.0)
        _planner_end('1985 Cobb')
        _h = _settled(_hkb, lambda h: h.get('endWhy'))
        _was = (_h.get('dropoff'), _h.get('endPinned'))
        _planner_end()
        _h = _settled(_hkb, lambda h: h.get('endPinned'))
        eq('[typed street] a clean reading of the same planner stop replaces a garbled one '
           'with no street type, and the end is searched and pinned anew',
           (_was, _h.get('dropoff'), _h.get('endPinned'), _h.get('endBy')),
           (('1985 Cobb, Kennesaw', False), '1985 Cobb Parkway, Kennesaw', True, 'server'))
        post(_hkb, '/api/delivered', {})

        # The owner's 19 Oct 21:41 fault, invented: the planner's dropoff read
        # "1385" once and was filed, then "1985" on every read after, the same
        # stop and as complete. The reading seen most of the last few of that
        # stop replaces the filed one, and the end is searched and pinned.
        _rough_took('k-vote', 25.0)
        _planner_end('1385 Cobb Parkway')
        _h = _settled(_hkb, lambda h: h.get('endWhy'))
        _was = (_h.get('dropoff'), _h.get('endPinned'))
        for _ in range(3):
            _planner_end()
        _h = _settled(_hkb, lambda h: h.get('endPinned'))
        eq('[house vote] "1385" read once then "1985" three times on the same planner stop: '
           '"1985" is filed, searched and pinned, and its point is on status',
           (_was, _h.get('dropoff'), _h.get('endPinned'), _h.get('endBy'),
            sorted((_h.get('endAt') or {}).keys())),
           (('1385 Cobb Parkway, Kennesaw', False), '1985 Cobb Parkway, Kennesaw', True,
            'server', ['lat', 'lon']))
        post(_hkb, '/api/delivered', {})

        _rough_took('k-rough-cap', 250.0)
        _planner_end()
        _h = _settled(_hkb, lambda h: h.get('endPinned') or h.get('endWhy'))
        eq('[rough disc] ...but a rough stamp over the cap (250 m) is still no disc',
           (_h.get('dropoff'), _h.get('endPinned'), _h.get('endWhy')),
           ('1985 Cobb Parkway, Kennesaw', False, 'no card fix'))
        eq('[rough disc] ...and its planner pickup, a door, is not asked either, and says why',
           (_h.get('pickupsPinned'), _h.get('pickupsWhy')), (0, 'no card fix'))
        post(_hkb, '/api/delivered', {})
    finally:
        stop(_hkp)

    # The owner's 20 Oct 20:44 fault, invented, carrying two on: the planner's
    # dropoff read whole-screen as "1985 Cobb Pa" and filed from 'planner';
    # the NucBox found nothing. Every read after was a card-box read of the
    # planner — a dropoff line under a Dropoff label, rank `label`, no stop key
    # — saying "1985 Cobb Parkway" cleanly, and the hold kept the garbled one.
    # Now the same house number with its street's type replaces it
    # (Assemble.labelTyped), the end is searched again and pinned; a press
    # filed garbled is never replaced.
    _bxs, _bxsays, _bxj = _hksayer('boxtyped')
    _bxp, _bxb = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable, 'SCANNER_ARGS': _bxs,
                        'NUCBOX_SEARCH': _hkfake_base, 'NUCBOX_TIMEOUT_MS': '800',
                        'CARRY_TWO': '1'}, _bxj)

    def _bx_box(line, asked=False):
        """The scanner's dropoff line off a card-box read of the planner (or a
        ⌖ press over it, `asked`)."""
        _bxsays([{'dropoff': {'found': True, 'line': line, 'street': line.split(',')[0],
                              'city': 'Kennesaw', 'state': 'GA', 'zip': None, 'place': None,
                              'asked': asked, 'labelled': None if asked else 'dropoff',
                              'ms': None, 'app': 'uber', 'screen': 'uber.planner',
                              'expectedBy': 1202, 'at': int(time.time() * 1000)}}])

    def _bx_planner(street):
        at = int(time.time() * 1000)
        stops = [{'kind': 'pickup', 'orders': 1, 'name': 'Example Wok', 'place': None,
                  'expectedBy': 1180, 'street': '2210 Quarry Bend Rd NW', 'city': 'Kennesaw',
                  'state': 'GA', 'zip': None, 'line': '2210 Quarry Bend Rd NW, Kennesaw',
                  'partial': None, 'label': 'pickup'},
                 {'kind': 'dropoff', 'orders': 1, 'name': 'Pat Q.', 'place': None,
                  'expectedBy': 1202, 'street': street, 'city': 'Kennesaw',
                  'state': 'GA', 'zip': None, 'line': street + ', Kennesaw',
                  'partial': None, 'label': 'dropoff'}]
        _bxsays([{'sighting': {'at': at, 'asked': False, 'whole': True, 'titled': True,
                               'app': 'uber', 'screen': 'uber.planner',
                               'page': {'top': True, 'bottom': True}, 'stops': stops,
                               'orderCount': 1, 'keep': False}},
                 {'planner': {'stops': [{k: v for k, v in s.items()
                                         if k not in ('partial', 'label')} for s in stops],
                              'keep': False, 'asked': False, 'ms': None, 'at': at}}])

    def _bx_took(oid):
        o = dict(_SQ, id=oid, pay=12.0, minutes=40.0, billedMinutes=40.0, miles=10.3,
                 cost=1.75, gpsOk=False, gpsWhy='rough', gpsErr=25.0, gpsMode=3, gpsAge=0.2)
        post(_bxb, '/api/offers/mark', {'id': oid, 'accepted': True, 'offer': o})

    try:
        _bx_took('x-boxtyped')
        _bx_planner('1985 Cobb Pa')
        _h = _settled(_bxb, lambda h: h.get('endWhy'))
        _was = (_h.get('dropoff'), ((_h.get('fields') or {}).get('dropoff') or {}).get('from'),
                _h.get('endPinned'))
        _bx_box('1985 Cobb Parkway, Kennesaw')
        _h = _settled(_bxb, lambda h: h.get('endPinned'))
        eq('[box typed] carrying two on: a planner dropoff filed garbled ("1985 Cobb Pa") is '
           'replaced by a card-box read of it typed, searched anew and pinned by the server',
           (_was, _h.get('dropoff'), ((_h.get('fields') or {}).get('dropoff') or {}).get('from'),
            _h.get('endPinned'), _h.get('endBy')),
           (('1985 Cobb Pa, Kennesaw', 'planner', False), '1985 Cobb Parkway, Kennesaw', 'label',
            True, 'server'))
        post(_bxb, '/api/delivered', {})

        _bx_took('x-boxpress')
        _bx_box('1985 Cobb Pa, Kennesaw', asked=True)
        _settled(_bxb, lambda h: h.get('endWhy'))
        _bx_box('1985 Cobb Parkway, Kennesaw')
        time.sleep(1.0)
        _h = _holding(_bxb) or {}
        eq('[box typed] ...but never over a ⌖ press, garbled or not',
           (_h.get('dropoff'), ((_h.get('fields') or {}).get('dropoff') or {}).get('from')),
           ('1985 Cobb Pa, Kennesaw', 'press'))
        post(_bxb, '/api/delivered', {})
    finally:
        stop(_bxp)

    # The owner's 19 Oct fault, invented: the Trip Planner gave "306 <Name>
    # Ct" right, the NucBox's search holds the court and not house 306 ('no
    # house number'), there is no place, and GPS arrival never armed. With
    # NUCBOX_STREETS set the street index is asked for every street of that
    # name reaching into the disc's box, whole (/api/streets/whole), and ONE
    # short one (SHORT_STREET_M, 600 m) arms the GPS drop on the street
    # (searchHeldStreet): arrival anywhere along it. The fake's Larkmoor
    # Court (360 m, two ways), Hollin Road (1.2 km) and two Fennick Courts.
    _sts, _stsays, _stj = _hksayer('street')
    _stp, _stb = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable, 'SCANNER_ARGS': _sts,
                        'NUCBOX_SEARCH': _hkfake_base, 'NUCBOX_STREETS': _hkfake_base,
                        'NUCBOX_TIMEOUT_MS': '800', 'GPS_DWELL_MS': '1000'}, _stj)

    def _stbeat(lat, lon):
        return {'alive': True, 'gps': {'state': 'ok', 'ageSeconds': 0.1, 'fix': {
            'lat': lat, 'lon': lon, 'gpsAge': 0.1, 'gpsErr': 25.0, 'gpsMode': 3,
            'gpsOk': True, 'gpsWhy': None, 'freshFor': 10.0}}}

    def _stdrops(oid):
        rows = [json.loads(l) for l in open(_stj) if l.strip()]
        return [r.get('by') for r in rows if r.get('kind') == 'drop' and r.get('id') == oid]

    try:
        _n = len(_hkasked('/api/streets/whole'))
        _atook(_stb, 's-court', '306 Larkmoor Ct, Marietta')
        _h = _settled(_stb)
        eq('[street arm] a short court the NucBox holds without house 306 arms the GPS drop on '
           'the street, says so, and asked the index once',
           (_h.get('endPinned'), _h.get('endBy'), _h.get('endWhy'),
            len(_hkasked('/api/streets/whole')) - _n),
           (True, 'street', None, 1))
        # The far end of the court, about 270 m from the street's first point
        # (the pin's lat/lon) and 30 m from the street itself.
        _stsays([_stbeat(33.9613, -84.5373)] * 7)
        ok_('[street arm] ...a dwell anywhere along the street is an arrival (its far end)',
            (_holding(_stb) or {}).get('arrived'))
        _stsays([_stbeat(33.9620, -84.5373)] * 3)
        ok_('[street arm] ...staying near the street does not drop', _holding(_stb))
        _stsays([_stbeat(33.9680, -84.5373)] * 3)
        eq('[street arm] ...and leaving it puts the order down, once, by the GPS',
           (_holding(_stb), _stdrops('s-court')), (None, ['gps']))

        _atook(_stb, 's-road', '512 Hollin Rd, Marietta')
        _h = _settled(_stb)
        eq('[street arm] a road of 1.2 km is never armed by its street: the refusal stands',
           (_h.get('endPinned'), _h.get('endBy'), _h.get('endWhy')),
           (False, None, 'street found, not that door'))
        _atook(_stb, 's-two', '77 Fennick Ct, Marietta')
        _h = _settled(_stb)
        eq('[street arm] two short courts of one name inside the disc are neither',
           (_h.get('endPinned'), _h.get('endWhy')), (False, 'street found, not that door'))
        # Mutation catch-up (21 Oct). A 0.7 mi card (a 1.2 mi disc): the box
        # still holds both Fennick Courts, the disc only the one by the Square.
        _atook(_stb, 's-near', '77 Fennick Ct, Marietta', miles=0.7)
        _h = _settled(_stb)
        eq('[street arm] ...but one of them alone touching a smaller card\'s disc, the other only '
           'in its box, arms on that one',
           (_h.get('endPinned'), _h.get('endBy')), (True, 'street'))
        _atook(_stb, 's-ocr', '21 Eliis Ct, Marietta')
        _h = _settled(_stb)
        eq('[street arm] a street the index reads as the name only by its ocr rule is not the same '
           'name: the refusal stands',
           (_h.get('endPinned'), _h.get('endWhy')), (False, 'street found, not that door'))
        _atook(_stb, 's-long', '40 Quarrel Ct, Marietta')
        _h = _settled(_stb)
        eq('[street arm] a short court beside a street of its name too long to send its shape is '
           'one of two (unknown is not none): neither',
           (_h.get('endPinned'), _h.get('endWhy')), (False, 'street found, not that door'))
        _atook(_stb, 's-untyped', '12 Pembury, Marietta')
        _h = _settled(_stb)
        eq('[street arm] a street read with no type word is no street name to ask the index by, '
           'even one the index holds with none (Pembury, 120 m)',
           (_h.get('endPinned'), _h.get('endWhy')), (False, 'street found, not that door'))
        # The court's door pressed with a place printed for its stop: the place
        # is asked first, and found nowhere (or too short to ask), the street.
        for _pn, _pl in (('s-place', 'Nowhere Hall'), ('s-shortplace', 'Inn')):
            _atook(_stb, _pn, None)
            _stsays([{'dropoff': {
                'found': True, 'line': '306 Larkmoor Ct, Marietta, GA 30060',
                'street': '306 Larkmoor Ct', 'city': 'Marietta', 'state': 'GA', 'zip': '30060',
                'asked': True, 'labelled': None, 'ms': 10, 'app': 'uber', 'screen': 'uber.nav',
                'expectedBy': None, 'place': _pl, 'at': int(time.time() * 1000)}}])
            _h = _settled(_stb, lambda h: h.get('endPinned') or h.get('endWhy'))
            eq('[street arm] a place %s, then the short street: armed by it' % (
                'found nowhere' if _pn == 's-place' else 'too short to ask'),
               (_h.get('place'), _h.get('endPinned'), _h.get('endBy')), (_pl, True, 'street'))

        _n = len(_hkasked('/api/streets/whole'))
        _atook(_stb, 's-guard', '306 Larkmoor Ct, Marietta')
        _h = _settled(_stb)
        eq('[street arm] the next order to that court is armed from the cache',
           (_h.get('endPinned'), _h.get('endBy'), len(_hkasked('/api/streets/whole')) - _n),
           (True, 'street', 0))
        # A pickup 55 m from the court's far end, 280 m from its first point.
        post(_stb, '/api/held-pickup', {'holdId': _h.get('holdId'),
                                        'lat': 33.9615, 'lon': -84.5373})
        eq('[street arm] a held pickup within 150 m of ANY point of the street disarms it',
           (_holding(_stb) or {}).get('endWhy'), 'door next to the pickup')
        _stsays([_stbeat(33.9613, -84.5373)] * 7 + [_stbeat(33.9680, -84.5373)] * 3)
        eq('[street arm] ...so waiting there and leaving drops nothing',
           (bool(_holding(_stb)), _stdrops('s-guard')), (True, []))
        post(_stb, '/api/delivered', {})
    finally:
        stop(_stp)
    _sts, _stsays, _stj = _hksayer('street-unset')
    _stp, _stb = start({'SCANNER': '0', 'NUCBOX_SEARCH': _hkfake_base,
                        'NUCBOX_TIMEOUT_MS': '800'}, _stj)
    try:
        _n = len(_hkasked('/api/streets/whole'))
        _atook(_stb, 's-unset', '306 Larkmoor Ct, Marietta', miles=4.0)
        _h = _settled(_stb)
        eq('[street arm] with NUCBOX_STREETS unset the index is never asked, nothing armed',
           (_h.get('endPinned'), _h.get('endWhy'), len(_hkasked('/api/streets/whole')) - _n),
           (False, 'street found, not that door', 0))
    finally:
        stop(_stp)

    # A NucBox that is down, so nothing is cached and every question shows:
    # the same planner read three times asks once (the retry is a minute off),
    # and a pickup with no street is never asked.
    _hks, _hksays, _hkj = _hksayer('b')
    _hkp, _hkb = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable, 'SCANNER_ARGS': _hks,
                        'NUCBOX_SEARCH': 'http://127.0.0.1:%d' % _hkdown.server_address[1],
                        'NUCBOX_RETRY_MS': '60000'}, _hkj)
    try:
        _atook(_hkb, 'k-once', _COBB)
        _settled(_hkb)
        _n = len(_HkDown.searches)
        _hksays([_hkplanner(('Example Diner', '1975 Cobb Parkway'))] * 3
                + [_hkplanner(('Example Wok', None))])
        time.sleep(0.5)
        _new = _HkDown.searches[_n:]
        eq('[held pickups] a pickup is asked once per hold, however often its planner is read, '
           'and one with no street never (%r)' % _new,
           (len(_new), all('street=1975' in u for u in _new),
            (_holding(_hkb) or {}).get('pickupsPinned')), (1, True, 0))
    finally:
        stop(_hkp)

    # A hold restored at boot with its planner on it and no pickup kept (the
    # NucBox was not there when it was read), its end refused for good: the
    # pickups are asked at boot, as the end is.
    _hkr = os.path.join(_hkdir, 'r')
    os.makedirs(_hkr)
    open(os.path.join(_hkr, 'offers.jsonl'), 'w').close()
    with open(os.path.join(_hkr, 'holding.json'), 'w') as _fh:
        json.dump({'id': 'k-boot', 'acceptedAt': int(time.time() * 1000) - 60000,
                   'pay': 12.0, 'minutes': 40.0, 'miles': 5.0,
                   'dropoff': 'Kestrel Dr, Marietta', 'endWhy': 'no house number',
                   'endWhyFor': 'Kestrel Dr, Marietta',
                   'card': dict(_SQ, miles=5.0),
                   'planner': {'stops': _hkplanner(('Example Diner', '1975 Cobb Parkway'))
                               ['planner']['stops'], 'unfiled': 'dropoffs'}}, _fh)
    _hkp, _hkb = start({'SCANNER': '0', 'NUCBOX_SEARCH': _hkfake_base},
                       os.path.join(_hkr, 'offers.jsonl'))
    try:
        _h = _settled(_hkb, lambda h: h.get('pickupsPinned'))
        eq('[held pickups] a hold restored at boot has its planner pickups asked for',
           (_h.get('holdId', '').startswith('k-boot'), _h.get('pickupsPinned')), (True, 1))
    finally:
        stop(_hkp)

    # --- the held order's restaurant, pinned by the server from its card ---
    #
    # The owner's decision of 18 Oct 2026: the server pins the held order's
    # restaurant itself, so the restaurant guard is always on — not only when
    # a Trip Planner was read. Each pickup address on record with a house
    # number (server.js pickupAsks): DoorDash's printed door under the store's
    # name (`pickupLine`, now carried onto the hold at Took), an Uber card's
    # "Store (<n> <street>)", a popup's door filed on the hold. The fake's
    # "1981 Cobb Parkway" is a restaurant 60 m from the door at 1985 Cobb
    # Parkway. Every name and address invented.
    _SP_DOOR = '1981 Cobb Pkwy, Kennesaw, GA 30152'

    def _sptook(base, oid, pickup, line=None, dropoff=_COBB, app='doordash'):
        o = dict(_SQ, id=oid, pay=9.0, minutes=35.0, billedMinutes=35.0, miles=5.0,
                 cost=1.5, pickup=pickup, app=app)
        if dropoff:
            o['dropoff'] = dropoff
        if line:
            o['pickupLine'] = line
        post(base, '/api/offers/mark', {'id': oid, 'accepted': True, 'offer': o})

    def _spsettled(base):
        return _settled(base, lambda h: (h.get('pickupsPinned') or h.get('pickupsWhy'))
                        and (h.get('endPinned') or h.get('endWhy')))

    def _sporders(journal):
        """holding.json's orders, by id: (pickupLine, [(lat, lon, q, by, from)])."""
        f = json.load(open(os.path.join(os.path.dirname(journal), 'holding.json')))
        return {o.get('id'): (o.get('pickupLine'),
                              [(p.get('lat'), p.get('lon'), p.get('q'), p.get('by'),
                                p.get('from')) for p in o.get('pickupPins') or []])
                for o in f.get('orders') or []}

    _SP_AT = (34.001, -84.55535)          # the fake's restaurant at 1981

    _spj = os.path.join(_hkdir, 'sp', 'offers.jsonl')
    os.makedirs(os.path.dirname(_spj))
    open(_spj, 'w').close()
    _spp, _spb = start({'SCANNER': '0', 'NUCBOX_SEARCH': _hkfake_base,
                        'NUCBOX_TIMEOUT_MS': '800'}, _spj)
    try:
        _n = len(_hkasked('street=1981'))
        _sptook(_spb, 's-uber', 'Example Burger (1981 Cobb Pkwy)', app='uber')
        _h = _spsettled(_spb)
        _spq = _hkasked('street=1981')[_n:]
        ok_('[server pickups] the card\'s door is asked once, on the NucBox, inside the held '
            'card\'s disc (%r)' % _spq,
            len(_spq) == 1 and 'viewbox=' in _spq[0] and 'bounded=1' in _spq[0])
        eq('[server pickups] an Uber card\'s "Store (<n> <street>)" is its door: pinned by the '
           'server from the card, and the door 60 m from it is not armed',
           (_h.get('pickupsPinned'), _h.get('pickupsHow'), _h.get('endPinned'),
            _h.get('endWhy')),
           (1, [{'by': 'server', 'from': 'card', 'asked': None}], True,
            'door next to the pickup'))
        post(_spb, '/api/delivered', {})

        _n = len(_hkasked(''))
        _sptook(_spb, 's-none', 'Example Taqueria', 7)
        _h = _spsettled(_spb)
        eq('[server pickups] a pickupLine that is not a string is not kept on the hold',
           _sporders(_spj).get('s-none', ('missing',))[0], None)
        # (23 Oct) ...and with no door on record the store is asked by its NAME,
        # once, inside the disc (pickupAsks' name ask): this fake knows no
        # Example Taqueria by name, so nothing is pinned and the door is armed.
        _spn = [a for a in _hkasked('')[_n:] if 'street=1985' not in a]
        eq('[server pickups] no pickup address with a house number: the store\'s name asked once '
           'inside the disc, nothing pinned, the door armed, and /api/status says why',
           (len(_spn), all('q=Example%20Taqueria' in a and 'bounded=1' in a for a in _spn),
            _h.get('pickupsPinned'), _h.get('pickupsWhy'), _h.get('endPinned'), _h.get('endWhy')),
           (1, True, 0, 'no door, place not found', True, None))
        post(_spb, '/api/delivered', {})

        # The street-type retry, as the end's: "Cts" asked again without it.
        _sptook(_spb, 's-retry', 'Example Wok', '1830 Tansy Creek Cts SW, Marietta, GA 30064',
                dropoff=_KES)
        _h = _settled(_spb, lambda h: h.get('pickupsPinned') or h.get('pickupsWhy'))
        eq('[server pickups] a printed door the NucBox holds under another type word is asked '
           'again without it, as the end is, and says the street asked',
           (_h.get('pickupsPinned'), _h.get('pickupsHow')),
           (1, [{'by': 'server', 'from': 'card', 'asked': '1830 Tansy Creek SW'}]))
        post(_spb, '/api/delivered', {})

        # The owner's 20 Oct fault, invented: an Uber card's store door with
        # the road's middle initial spelled out, its road found and not the
        # door; asked again with "W", as the end is (MV.dirRetry).
        _sptook(_spb, 's-dir', 'Example Steakhouse (810 Ardley West Corwin Parkway)',
                dropoff=_KES, app='uber')
        _h = _settled(_spb, lambda h: h.get('pickupsPinned') or h.get('pickupsWhy'))
        eq('[server pickups] a store door whose road is found and not the door is asked again '
           'with the directional as its letter, and says the street asked',
           (_h.get('pickupsPinned'), _h.get('pickupsHow')),
           (1, [{'by': 'server', 'from': 'card', 'asked': '810 Ardley W Corwin Parkway'}]))
        post(_spb, '/api/delivered', {})
        _sptook(_spb, 's-dir-circle', 'Example Steakhouse (812 Ardley West Corwin Parkway)',
                dropoff=_KES, app='uber')
        _h = _settled(_spb, lambda h: h.get('pickupsPinned') or h.get('pickupsWhy'))
        eq('[server pickups] ...a house of that number on another street is not its door',
           (_h.get('pickupsPinned'), _h.get('pickupsWhy')), (0, 'street found, not that door'))
        post(_spb, '/api/delivered', {})

        # Left held for the restart below.
        _sptook(_spb, 's-dd', 'Example Taqueria', _SP_DOOR)
        _h = _spsettled(_spb)
        eq('[server pickups] a held DoorDash order keeps its card\'s printed door '
           '(pickupLine), and the server pins it there, by the server, from the card',
           (_sporders(_spj).get('s-dd'), _h.get('pickupsHow'), _h.get('pickupsWhy')),
           ((_SP_DOOR, [(_SP_AT[0], _SP_AT[1], _SP_DOOR, 'server', 'card')]),
            [{'by': 'server', 'from': 'card', 'asked': None}], None))
        eq('[server pickups] ...so a door 60 m from it is not armed, and says why',
           (_h.get('endPinned'), _h.get('endWhy')), (True, 'door next to the pickup'))
        _code = post(_spb, '/api/held-pickup', {'holdId': _h.get('holdId'), 'lat': 34.0,
                                                 'lon': -84.55, 'q': _SP_DOOR})[0]
        eq('[server pickups] the first valid pin for a pickup text wins: Map view\'s post for '
           'it after the server pinned it moves nothing',
           (_code, _sporders(_spj).get('s-dd')[1]),
           (200, [(_SP_AT[0], _SP_AT[1], _SP_DOOR, 'server', 'card')]))
        post(_spb, '/api/held-pickup', {'holdId': _h.get('holdId'), 'lat': _SP_AT[0],
                                        'lon': _SP_AT[1]})
        eq('[server pickups] ...and a post with no name at the same position keeps the name '
           'and who pinned it', _sporders(_spj).get('s-dd')[1],
           [(_SP_AT[0], _SP_AT[1], _SP_DOOR, 'server', 'card')])
    finally:
        stop(_spp)
    _n = len(_hkasked('street=1981'))
    _spp, _spb = start({'SCANNER': '0', 'NUCBOX_SEARCH': _hkfake_base,
                        'NUCBOX_TIMEOUT_MS': '800'}, _spj)
    try:
        _h = _spsettled(_spb)
        time.sleep(0.3)
        eq('[server pickups] a restart restores the pin and how it was made, the door still '
           'not armed, and a pinned pickup is not asked again',
           (_h.get('holdId', '').startswith('s-dd'), _h.get('pickupsHow'), _h.get('endWhy'),
            len(_hkasked('street=1981')) - _n),
           (True, [{'by': 'server', 'from': 'card', 'asked': None}], 'door next to the pickup',
            0))
    finally:
        stop(_spp)

    # A hold restored at boot whose store's door a place popup filed
    # (`fields.pickupAddr`, from 'popup'), no pickup pinned: asked at boot —
    # and its card's own "Store (<n> <street>)" as well, which the popup's
    # filing took out of the field.
    _spr = os.path.join(_hkdir, 'spr')
    os.makedirs(_spr)
    open(os.path.join(_spr, 'offers.jsonl'), 'w').close()
    with open(os.path.join(_spr, 'holding.json'), 'w') as _fh:
        _at = int(time.time() * 1000) - 60000
        json.dump({'id': 's-popup', 'acceptedAt': _at, 'pay': 9.0, 'minutes': 35.0,
                   'miles': 5.0, 'pickup': 'Example Grill (250 Example Rd)', 'dropoff': None,
                   'card': dict(_SQ, miles=5.0),
                   'fields': {'dropoff': None, 'customer': None, 'expectedBy': None,
                              'pickupAddr': {'value': '1981 Cobb Pkwy, Kennesaw',
                                             'from': 'popup', 'conf': 2, 'at': _at}}}, _fh)
    _spp, _spb = start({'SCANNER': '0', 'NUCBOX_SEARCH': _hkfake_base},
                       os.path.join(_spr, 'offers.jsonl'))
    try:
        _h = _settled(_spb, lambda h: (h.get('pickupsPinned') or 0) >= 2)
        eq('[server pickups] a store\'s door a popup filed on the hold is pinned, from the popup, '
           'and the card\'s bracketed door beside it, from the card',
           (_h.get('pickupsPinned'), sorted(w.get('from') for w in _h.get('pickupsHow') or [])),
           (2, ['card', 'popup']))
    finally:
        stop(_spp)

    # Two orders in the car (carrying two on), each card printing its own
    # store's door: each is pinned, under its own order.
    _spj2 = os.path.join(_hkdir, 'sp2', 'offers.jsonl')
    os.makedirs(os.path.dirname(_spj2))
    open(_spj2, 'w').close()
    _spp, _spb = start({'SCANNER': '0', 'NUCBOX_SEARCH': _hkfake_base, 'CARRY_TWO': '1',
                        'NUCBOX_TIMEOUT_MS': '800'}, _spj2)
    try:
        _sptook(_spb, 's-two-a', 'Example Taqueria', _SP_DOOR)
        _sptook(_spb, 's-two-b', 'Example Grill', '250 Example Rd, Marietta, GA 30060',
                dropoff=None)
        _two = []
        for _ in range(120):
            _two = get(_spb, '/api/status').get('orders') or []
            if len(_two) == 2 and all(o.get('pickupsPinned') for o in _two):
                break
            time.sleep(0.05)
        _o = _sporders(_spj2)
        eq('[server pickups] two orders: each order\'s own store is pinned by the server, '
           'under that order, and /api/status says so of each',
           ([(o.get('n'), o.get('pickupsPinned'), o.get('pickupsHow')) for o in _two],
            [(p[0], p[1]) for p in _o.get('s-two-a', (None, []))[1]],
            [(p[0], p[1]) for p in _o.get('s-two-b', (None, []))[1]]),
           ([(1, 1, [{'by': 'server', 'from': 'card', 'asked': None}]),
             (2, 1, [{'by': 'server', 'from': 'card', 'asked': None}])],
            [_SP_AT], [(33.97, -84.53)]))
    finally:
        stop(_spp)

    # A NucBox that does not answer: nothing pinned, said, and Map view's own
    # post for the same text still kept.
    _spj3 = os.path.join(_hkdir, 'sp3', 'offers.jsonl')
    os.makedirs(os.path.dirname(_spj3))
    open(_spj3, 'w').close()
    _spp, _spb = start({'SCANNER': '0', 'NUCBOX_RETRY_MS': '1000',
                        'NUCBOX_SEARCH': 'http://127.0.0.1:%d' % _hkdown.server_address[1]},
                       _spj3)
    try:
        _n = len([u for u in _HkDown.searches if 'street=1981' in u])
        _sptook(_spb, 's-down', 'Example Taqueria', _SP_DOOR)
        _h = _settled(_spb, lambda h: h.get('pickupsWhy'))
        time.sleep(3.5)
        eq('[server pickups] a NucBox that does not answer pins nothing, says so, and is asked '
           'exactly once more',
           (_h.get('pickupsPinned'), _h.get('pickupsWhy'),
            len([u for u in _HkDown.searches if 'street=1981' in u]) - _n), (0, 'NucBox down', 2))
        post(_spb, '/api/held-pickup', {'holdId': _h.get('holdId'), 'lat': _SP_AT[0],
                                        'lon': _SP_AT[1], 'q': _SP_DOOR})
        _h = _holding(_spb) or {}
        eq('[server pickups] ...and Map view\'s post still pins it, said as the page\'s',
           (_h.get('pickupsPinned'), _h.get('pickupsHow'), _h.get('pickupsWhy')),
           (1, [{'by': None, 'from': None, 'asked': None}], None))
    finally:
        stop(_spp)

    # --- the held end by its PLACE (the owner, 17 Oct) -----------------------
    #
    # The fault, invented throughout: an order's door "<n> <Road>" that the
    # NucBox holds the road of and not the house (the fake's 4821 Kestrel Dr,
    # answered as the street alone), so the door search said "no house
    # number" and GPS arrival never armed; the phone printed the stop's place,
    # which a ⌖ press's dropoff line now carries (scan_pi emit_dropoff
    # `place`) onto the hold (Assemble.file `dropoffPlace`). The server asks
    # the place, q= alone, in the held card's disc (searchHeldPlace), and pins
    # only a named feature, not a road, of that name, inside the disc.
    _PL_LINE = '4821 Kestrel Dr, Marietta, GA 30060'

    def _plpress(place, line=_PL_LINE, street='4821 Kestrel Dr'):
        return {'dropoff': {'found': True, 'line': line, 'street': street, 'city': 'Marietta',
                            'state': 'GA', 'zip': '30060', 'asked': True, 'labelled': None,
                            'ms': 10, 'app': 'uber', 'screen': 'uber.nav', 'expectedBy': None,
                            'place': place, 'at': int(time.time() * 1000)}}

    def _plend(base, oid, place, line=_PL_LINE, street='4821 Kestrel Dr', says=None):
        _atook(base, oid, None)
        (says or _hksays)([_plpress(place, line, street)])
        h = _settled(base, lambda h: h.get('endPinned') or h.get('endWhy'))
        return (h.get('place'), h.get('endPinned'), h.get('endBy'), h.get('endWhy'))

    _hks, _hksays, _hkj = _hksayer('p')
    _hkp, _hkb = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable, 'SCANNER_ARGS': _hks,
                        'NUCBOX_SEARCH': _hkfake_base, 'NUCBOX_TIMEOUT_MS': '800'}, _hkj)
    try:
        _n = len(_hkasked('q='))
        eq('[place] the door not on the NucBox, its place is: the end is pinned by the place '
           'and says so', _plend(_hkb, 'p-deck', 'Wrenfield Parking Deck'),
           ('Wrenfield Parking Deck', True, 'place', None))
        _q = _hkasked('q=')[_n:]
        eq('[place] ...asked once, the place alone (no town), bounded to the held card\'s disc',
           [(u.split('&q=')[1].split('&')[0], 'viewbox=' in u, 'bounded=1' in u) for u in _q],
           [('Wrenfield%20Parking%20Deck', True, True)])
        _hksays([_hkbeat(0.5)])
        _beat = (get(_hkb, '/api/status').get('beat') or {}).get('heldEnd') or {}
        eq('[place] ...and the panel is told who pinned it, on the beat as on /api/status',
           (_beat.get('endPinned'), _beat.get('endBy')), (True, 'place'))
        # The restaurant guard holds a place pin as it holds a door: a pickup
        # pinned 60 m from the deck.
        post(_hkb, '/api/held-pickup', {'holdId': (_holding(_hkb) or {}).get('holdId'),
                                        'lat': 33.9717, 'lon': -84.5288,
                                        'q': 'Example Grill, 9 Kestrel Dr'})
        _h = _holding(_hkb) or {}
        eq('[place] ...and a place within 150 m of a held pickup is not armed, and says why',
           (_h.get('endPinned'), _h.get('endBy'), _h.get('endWhy')),
           (True, 'place', 'door next to the pickup'))
        post(_hkb, '/api/delivered', {})

        eq('[place] the reader\'s read with its last letter lost still names the deck',
           _plend(_hkb, 'p-ocr', 'Wrenfield Parking Dec'),
           ('Wrenfield Parking Dec', True, 'place', None))
        post(_hkb, '/api/delivered', {})
        eq('[place] a name the NucBox answered that is not the place (a word short) is refused',
           _plend(_hkb, 'p-loose', 'Wrenfield Deck'),
           ('Wrenfield Deck', False, None, 'no door, place not found'))
        post(_hkb, '/api/delivered', {})
        eq('[place] a ROAD of the place\'s name is refused',
           _plend(_hkb, 'p-road', 'Quarry Hall'),
           ('Quarry Hall', False, None, 'no door, place not found'))
        post(_hkb, '/api/delivered', {})
        eq('[place] a feature of that name outside the held card\'s disc is refused',
           _plend(_hkb, 'p-far', 'Lantern Parking Deck'),
           ('Lantern Parking Deck', False, None, 'not inside the card\'s reach'))
        post(_hkb, '/api/delivered', {})
        # The door on the NucBox: the place is never asked.
        _n = len(_hkasked('q='))
        eq('[place] a door the NucBox holds is pinned by the door, and the place never asked',
           (_plend(_hkb, 'p-door', 'Wrenfield Parking Deck', '1985 Cobb Parkway, Kennesaw',
                   '1985 Cobb Parkway'), len(_hkasked('q=')) - _n),
           (('Wrenfield Parking Deck', True, 'server', None), 0))
        post(_hkb, '/api/delivered', {})
        _n = len(_hkasked('q='))
        eq('[place] no place, no place search: the door\'s refusal stands',
           (_plend(_hkb, 'p-none', None), len(_hkasked('q=')) - _n),
           ((None, False, None, 'street found, not that door'), 0))
        # ...and a place learnt for that same end text is searched for: the
        # same line pressed again, this time with its place.
        _hksays([_plpress('Wrenfield Parking Deck')])
        _h = _settled(_hkb, lambda h: h.get('endPinned'))
        eq('[place] a place learnt later for the same dropoff text is asked, and pins',
           (_h.get('endPinned'), _h.get('endBy')), (True, 'place'))
        post(_hkb, '/api/delivered', {})
    finally:
        stop(_hkp)

    # NUCBOX_SEARCH unset: nothing is asked, place or not, and nothing said.
    _hks, _hksays, _hkj = _hksayer('pu')
    _hkp, _hkb = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable, 'SCANNER_ARGS': _hks},
                       _hkj)
    try:
        _n = len(_hkasked(''))
        _atook(_hkb, 'p-unset', None)
        _hksays([_plpress('Wrenfield Parking Deck')])
        time.sleep(0.5)
        _h = _holding(_hkb) or {}
        eq('[place] with NUCBOX_SEARCH unset the place rides on the hold and nothing is asked',
           (_h.get('place'), _h.get('endPinned'), _h.get('endWhy'), len(_hkasked('')) - _n),
           ('Wrenfield Parking Deck', False, None, 0))
    finally:
        stop(_hkp)

    # --- searched early, and the pin outcome journaled (the owner, 21 Oct) ---
    #
    # An offer card's pickup and dropoff are searched on the NucBox the moment
    # the scanner's offer line arrives (server.js searchCardEarly, earlyDoor:
    # doorChain inside the card's disc), so a later ✓ Took finds every answer
    # in nbxCache and asks nothing. While an order is held, every address a
    # screen reports is searched too, EARLY_WARM_PER_MIN (6) new a minute at
    # most. Every drop row says how the order's end was pinned or why not
    # (pinOutcome), in words. Every address invented; "Quillon Way" is a
    # street the fake does not hold.
    def _ewait(word, n, seconds=4.0):
        for _ in range(int(seconds / 0.05)):
            if len(_hkasked(word)) >= n:
                break
            time.sleep(0.05)
        return len(_hkasked(word))

    def _edrop(journal, oid):
        with open(journal) as fh:
            rows = [json.loads(x) for x in fh if x.strip()]
        return [r for r in rows if r.get('kind') == 'drop' and r.get('id') == oid]

    _ECARD = dict(_SQ, id='e-card', pay=9.0, minutes=35.0, billedMinutes=35.0, miles=5.0,
                  cost=1.5, pickup='Example Burger (1981 Cobb Pkwy)', dropoff=_COBB, app='uber')
    _hks, _hksays, _hkj = _hksayer('early')
    # The warming window is EARLY_WARM_MS (60 s on the rig), 3 s here.
    _hkp, _hkb = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable, 'SCANNER_ARGS': _hks,
                        'NUCBOX_SEARCH': _hkfake_base, 'NUCBOX_TIMEOUT_MS': '800',
                        'EARLY_WARM_MS': '3000'}, _hkj)
    try:
        _n85, _n81 = len(_hkasked('street=1985')), len(_hkasked('street=1981'))
        _hksays([{'offer': _ECARD}])
        _ewait('street=1985', _n85 + 1)
        _ewait('street=1981', _n81 + 1)
        _eq = _hkasked('street=1985')[_n85:] + _hkasked('street=1981')[_n81:]
        ok_('[early search] a card read is searched at once, its dropoff and its pickup, '
            'each once, inside the card\'s disc, before any Took (%r)' % _eq,
            len(_eq) == 2 and all('viewbox=' in q and 'bounded=1' in q for q in _eq))
        _hksays([{'offer': dict(_ECARD, pay=9.5)}])
        eq('[early search] ...and a re-read of the same card asks nothing more',
           (len(_hkasked('street=1985')) - _n85, len(_hkasked('street=1981')) - _n81), (1, 1))
        _nall = len(_hkasked(''))
        post(_hkb, '/api/offers/mark', {'id': 'e-card', 'accepted': True, 'offer': _ECARD})
        _h = _settled(_hkb, lambda h: h.get('endPinned') and h.get('pickupsPinned'))
        eq('[early search] ✓ Took pins the end and the restaurant from the early answers, '
           'with no new request to the NucBox',
           (_h.get('endPinned'), _h.get('endBy'), _h.get('pickupsPinned'),
            len(_hkasked('')) - _nall), (True, 'server', 1, 0))
        post(_hkb, '/api/delivered', {})
        time.sleep(0.3)
        _r = (_edrop(_hkj, 'e-card') or [{}])[0]
        eq('[pin log] Drop journals how the end was pinned and why it did not arm, in words',
           (_r.get('end'), _r.get('pickups')),
           ({'by': 'server', 'why': 'door next to the pickup', 'asked': 'door'},
            {'pinned': 1, 'why': None}))
        # (Its times left out: a millisecond clock can hold "1981" by chance.)
        _rt = json.dumps({k: v for k, v in _r.items() if k not in ('at', 'seq', 'acceptedAt')})
        eq('[pin log] ...and carries no address or coordinate it did not already carry',
           [w for w in ('Cobb', '1985', '1981', 'Burger', '34.0', '-84.5', 'lat', 'lon')
            if w in _rt], [])

        # No door on the NucBox: the refusal, said in the row a Took that
        # replaced the order writes.
        _atook(_hkb, 'e-street', _KES)
        _settled(_hkb, lambda h: h.get('endWhy'))
        _atook(_hkb, 'e-two', _COBB)
        _h = _settled(_hkb, lambda h: h.get('endPinned') and (h.get('holdId') or '')
                      .startswith('e-two'))
        time.sleep(0.3)
        _r = (_edrop(_hkj, 'e-street') or [{}])[0]
        eq('[pin log] a replaced order\'s row says its end was not pinned, and why',
           (_r.get('by'), _r.get('end'), _r.get('pickups')),
           ('replaced', {'by': None, 'why': 'street found, not that door', 'asked': 'door'},
            {'pinned': 0, 'why': 'no house number'}))

        # Every other screen, while an order is held: a planner page of nine
        # doors the fake does not hold. Six are searched in the held card's
        # disc (each with its type-word retry), three are not, this minute.
        def _eplanner(base):
            return {'planner': {'stops': [
                {'kind': 'dropoff', 'orders': 1, 'name': 'Pat Q.', 'street': None,
                 'city': None, 'state': None, 'zip': None,
                 'line': '%d Quillon Way, Marietta' % (base + i)} for i in range(9)],
                'unfiled': 'dropoffs', 'asked': False}}

        def _enumbers():
            said = ' '.join(_hkasked('Quillon'))
            return sorted(set(re.findall(r'street=(\d+)%20Quillon', said)))
        _wt0 = time.time()
        _hksays([_eplanner(300)])
        time.sleep(1.0)
        _got = _enumbers()
        eq('[early warm] while an order is held, a screen\'s doors are searched, six new '
           'a minute at most (EARLY_WARM_PER_MIN)', (len(_got), _got[:1]), (6, ['300']))
        ok_('[early warm] ...inside the held card\'s disc',
            all('viewbox=' in q and 'bounded=1' in q for q in _hkasked('Quillon')))
        _nq = len(_hkasked('Quillon'))
        _hksays([_eplanner(300)])
        time.sleep(0.5)
        eq('[early warm] ...the same page again asks nothing: six already searched, '
           'the minute\'s room spent', len(_hkasked('Quillon')) - _nq, 0)
        time.sleep(max(0.1, _wt0 + 3.4 - time.time()))
        _hksays([_eplanner(300)])
        time.sleep(1.0)
        eq('[early warm] ...and once the window has passed, the three left are searched',
           len(_enumbers()), 9)
        post(_hkb, '/api/delivered', {})
        time.sleep(0.3)
        _r = (_edrop(_hkj, 'e-two') or [{}])[0]
        eq('[pin log] the order the early cache pinned says so on its own Drop row',
           (_r.get('end') or {}).get('by'), 'server')
        _nq = len(_hkasked('Quillon'))
        _hksays([_eplanner(400)])
        time.sleep(0.5)
        eq('[early warm] with nothing held, another screen\'s doors are not searched',
           len(_hkasked('Quillon')) - _nq, 0)
        # [pin log] A store's door the NucBox does not hold: the pickups'
        # refusal is worked out before the order's searches are forgotten.
        post(_hkb, '/api/offers/mark', {'id': 'e-pick', 'accepted': True, 'offer': dict(
            _ECARD, id='e-pick', pickup='Nowhere Cafe (12 Quillon Way)')})
        _settled(_hkb, lambda h: h.get('pickupsWhy') and h.get('endPinned'))
        post(_hkb, '/api/delivered', {})
        time.sleep(0.3)
        eq('[pin log] a pickup the NucBox refused says why on the Drop row',
           (_edrop(_hkj, 'e-pick') or [{}])[0].get('pickups'),
           {'pinned': 0, 'why': 'not inside the card\'s reach'})
        # [early search] A card read before its fix is asked on the next reading.
        _n90 = len(_hkasked('street=1990'))
        _nofix = dict(_ECARD, id='e-nofix', dropoff='1990 Cobb Parkway, Kennesaw',
                      pickup='Nowhere Two')
        _hksays([{'offer': dict(_nofix, lat=None, lon=None, gpsOk=False)}])
        time.sleep(0.5)
        _n90b = len(_hkasked('street=1990'))
        _hksays([{'offer': _nofix}])
        _ewait('street=1990', _n90 + 1)
        eq('[early search] a card read before its fix is asked nothing, and is asked on the next '
           'reading with one', (_n90b - _n90, len(_hkasked('street=1990')) > _n90b), (0, True))
    finally:
        stop(_hkp)

    # A NucBox that does not answer: a card is asked once and not again, however
    # often it is re-read; another screen's door is asked again once the
    # refusal is END_RETRY_MS old (NUCBOX_RETRY_MS, 400 ms here).
    _hks, _hksays, _hkj = _hksayer('early-down')
    _hkp, _hkb = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable, 'SCANNER_ARGS': _hks,
                        'NUCBOX_SEARCH': 'http://127.0.0.1:%d' % _hkdown.server_address[1],
                        'NUCBOX_TIMEOUT_MS': '800', 'NUCBOX_RETRY_MS': '400'}, _hkj)
    try:
        def _downs(word):
            return len([p for p in _HkDown.searches if word in p])
        _n = _downs('street=1985')
        _hksays([{'offer': dict(_ECARD, id='e-down')}])
        time.sleep(0.8)
        _hksays([{'offer': dict(_ECARD, id='e-down', pay=9.5)}])
        time.sleep(0.5)
        eq('[early search] a card the NucBox did not answer is asked once, not again on a re-read',
           _downs('street=1985') - _n, 1)
        _atook(_hkb, 'e-dheld', _KES)
        _n = _downs('Quillon')
        _hksays([{'planner': {'stops': [{'kind': 'dropoff', 'orders': 1, 'name': 'Pat Q.',
                                        'street': None, 'city': None, 'state': None,
                                        'zip': None, 'line': '10 Quillon Way, Marietta'}],
                              'unfiled': 'dropoffs', 'asked': False}}])
        time.sleep(0.8)
        _hksays([{'planner': {'stops': [{'kind': 'dropoff', 'orders': 1, 'name': 'Pat Q.',
                                        'street': None, 'city': None, 'state': None,
                                        'zip': None, 'line': '10 Quillon Way, Marietta'}],
                              'unfiled': 'dropoffs', 'asked': False}}])
        time.sleep(0.5)
        eq('[early warm] a door the NucBox did not answer is asked again past END_RETRY_MS',
           _downs('Quillon') - _n, 2)
        post(_hkb, '/api/delivered', {})
    finally:
        stop(_hkp)
finally:
    _hkfake.kill()
    _hkdown.shutdown()
    shutil.rmtree(_hkdir, ignore_errors=True)

# --- Stage 5: carrying two orders ---------------------------------------------
#
# The driver asked to carry two orders, and AUDITS.md's Settled refused it as
# plan 3.1 for one reason: with two in the car, the ⌖ press for the second was
# filed onto the first — an asked:true dropoff on the wrong order's id, in a
# file that cannot be corrected. The owner's decision puts a safeguard in place
# of the refused rival-card guard: with two held, an address is filed onto one
# of them only on a positive cue, or from the chooser the driver answers, and
# otherwise nowhere. Behind the `carryTwo` setting (CARRY_TWO here); with it
# off a second Took replaces, as before.
#
# A scanner of its own that says whatever the suite writes: `lines-N.json`, a
# list of messages, each printed as one line, and `done-N` when they are out.
# Every name, store and street is invented.
_cdir = tempfile.mkdtemp()
_cfake = os.path.join(_cdir, 'say.py')
with open(_cfake, 'w') as _fh:
    _fh.write(
        'import json, os, time\n'
        'd = os.path.dirname(os.path.abspath(__file__))\n'
        'n = 0\n'
        'end = time.time() + 900\n'
        'while time.time() < end:\n'
        '    p = os.path.join(d, "lines-%d.json" % n)\n'
        '    if not os.path.exists(p):\n'
        '        time.sleep(0.03)\n'
        '        continue\n'
        '    for m in json.load(open(p)):\n'
        '        m.setdefault("at", int(time.time() * 1000))\n'
        '        print(json.dumps(m), flush=True)\n'
        '        time.sleep(0.05)\n'
        '    open(os.path.join(d, "done-%d" % n), "w").close()\n'
        '    n += 1\n')
_cseq = [0]


def _say(*msgs):
    """The fake scanner says these, in order; returns once they are read."""
    n = _cseq[0]
    _cseq[0] += 1
    path = os.path.join(_cdir, 'lines-%d.json' % n)
    with open(path + '.tmp', 'w') as fh:
        json.dump(list(msgs), fh)
    os.rename(path + '.tmp', path)
    for _ in range(300):
        if os.path.exists(os.path.join(_cdir, 'done-%d' % n)):
            break
        time.sleep(0.03)
    time.sleep(0.25)


def _card(oid, pay, minutes=30.0, miles=5.0, app='uber', screen='uber.offer',
          pickup=None, dropoff=None, deliver_by=None, **more):
    o = {'id': oid, 'pay': pay, 'minutes': minutes, 'billedMinutes': minutes,
         'miles': miles, 'cost': 1.5, 'perHour': 20.0, 'state': 'go',
         'app': app, 'screen': screen, 'pickup': pickup, 'dropoff': dropoff,
         'deliverBy': deliver_by, 'legs': 1, 'multiOrder': False}
    o.update(more)
    return {'offer': o}


def _took2(base, card):
    """The card on the slot, then ✓ Took on it; the reply — and a moment for
    the rows the press appends after replying (a replaced order's drop row)."""
    _say(card)
    out = post(base, '/api/offers/mark', {'id': card['offer']['id'], 'accepted': True,
                                         'via': 'panel'})[1]
    time.sleep(0.3)
    return out


def _nav(line, street, city, asked=True, app='uber', expected=None, **more):
    d = {'found': True, 'line': line, 'street': street, 'city': city, 'state': 'GA',
         'zip': None, 'asked': asked, 'labelled': None if asked else 'dropoff',
         'ms': 10, 'app': app, 'screen': 'uber.nav', 'expectedBy': expected}
    d.update(more)
    return {'dropoff': d}


def _rows(journal_path, kind=None):
    out = [json.loads(l) for l in open(journal_path) if l.strip()]
    return [r for r in out if kind is None or r.get('kind') == kind]


def _orders(base):
    return get(base, '/api/status').get('orders') or []


def _cserver(name, hold=None, waits=None, **env):
    # A directory each: holding.json is kept beside the journal, and a server
    # started on the last one's would restore its orders. `hold`, when given,
    # is a holding.json to start with: the orders a restart brings back.
    # `waits`, a store-waits.json to start with: the restaurant waits on record.
    home = os.path.join(_cdir, name)
    os.mkdir(home)
    j = os.path.join(home, 'offers.jsonl')
    open(j, 'w').close()
    if hold is not None:
        with open(os.path.join(home, 'holding.json'), 'w') as fh:
            json.dump(hold, fh)
    if waits is not None:
        with open(os.path.join(home, 'store-waits.json'), 'w') as fh:
            json.dump(waits, fh)
    hand = os.path.join(home, 'hand')
    os.mkdir(hand)
    e = {'SCANNER': '1', 'SCANNER_CMD': sys.executable, 'SCANNER_ARGS': _cfake,
         'UBERSCAN_HANDOFF_DIR': hand, 'HOLD_GRACE_MS': '600000'}
    e.update(env)
    # The fake starts at lines-0 each time it is started: a fresh directory
    # of lines per server.
    for f in os.listdir(_cdir):
        if f.startswith('lines-') or f.startswith('done-'):
            os.remove(os.path.join(_cdir, f))
    _cseq[0] = 0
    proc, base = start(e, j)
    return proc, base, j, hand


_SN = time.localtime()
_NOWMIN = _SN.tm_hour * 60 + _SN.tm_min
_A = _card('c-a', 9.48, minutes=40.0, deliver_by=(_NOWMIN + 40) % 1440,
           pickup='Wren Street Noodles')
_B = _card('c-b', 28.08, minutes=55.0, deliver_by=(_NOWMIN + 75) % 1440,
           pickup='Larkspur Tacos')
_BNAV = ('77 Birch Ln, Roswell, GA 30075', '77 Birch Ln', 'Roswell')

_cp, _cb, _cj, _ch = _cserver('two', CARRY_TWO='1', CHOOSER_MS='1500')
try:
    _ra = _took2(_cb, _A)
    _one = _orders(_cb)
    _rb = _took2(_cb, _B)
    _two = _orders(_cb)
    eq('[carry two] a second Took ADDS an order: two in the car, first-taken first',
       [(o.get('n'), o.get('pay')) for o in _two], [(1, 9.48), (2, 28.08)])
    ok_('[carry two] ...and the Took that added one offers to undo it',
        (_rb.get('added') or {}).get('id') == 'c-b' and not _ra.get('added'))
    eq('[carry two] ...the scanner is told of both, until the later end',
       len(json.load(open(os.path.join(_ch, 'uberscan-holding.json'))).get('holds') or []), 2)

    # Plan 3.1's own case: ⌖ over B's navigation screen, which prints B's
    # deadline. The same app, so the app alone cannot decide it.
    _seen = listen(_cb, 2.5)
    _say(_nav(_BNAV[0], _BNAV[1], _BNAV[2], expected=(_NOWMIN + 76) % 1440))
    _two = _orders(_cb)
    _marks = [r for r in _rows(_cj, 'mark') if r.get('dropoff') == _BNAV[0]]
    eq('plan 3.1: Took A, Took B, ⌖ over B\'s navigation lands on B, never A',
       ([o.get('dropoff') for o in _two], [(r.get('id'), r.get('cue')) for r in _marks]),
       ([None, _BNAV[0]], [('c-b', 'deadline')]))
    time.sleep(0.4)
    ok_('[carry two] ...and the panel is told, with ① still the first-taken',
        any((m.get('dropoff') or {}).get('line') == _BNAV[0]
            and (m.get('holding') or {}).get('pay') == 9.48 for m in _seen))

    # The same press with nothing on the screen to say whose: the chooser.
    _KNAV = ('4821 Kestrel Dr, Marietta, GA 30060', '4821 Kestrel Dr', 'Marietta')
    _seen = listen(_cb, 2.0)
    _say(_nav(_KNAV[0], _KNAV[1], _KNAV[2]))
    _ch1 = get(_cb, '/api/status').get('chooser') or {}
    time.sleep(0.3)
    eq('...with no cue nothing is filed and the chooser is offered',
       ([o.get('dropoff') for o in _orders(_cb)],
        [r for r in _rows(_cj, 'mark') if r.get('dropoff') == _KNAV[0]],
        [r.get('n') for r in _ch1.get('rows') or []], _ch1.get('line'),
        # No card row: the card on the slot is B's own, the last Took's.
        _ch1.get('card'),
        bool(_ch1.get('id'))
        and any((m.get('chooser') or {}).get('id') == _ch1.get('id') for m in _seen)),
       ([None, _BNAV[0]], [], [1, 2], _KNAV[0], None, True))
    # ...and left alone: it closes with nothing filed, and an answer after
    # that is refused.
    time.sleep(1.8)
    _late = post(_cb, '/api/choose', {'id': _ch1.get('id'), 'pick': _two[0].get('holdId')})
    eq('the chooser closing untouched files nothing',
       (get(_cb, '/api/status').get('chooser'), _late[0],
        [o.get('dropoff') for o in _orders(_cb)],
        [r for r in _rows(_cj, 'mark') if r.get('dropoff') == _KNAV[0]]),
       (None, 409, [None, _BNAV[0]], []))
    # ...and the premise: a row picked in time files it, on that order, by
    # the chooser.
    _say(_nav(_KNAV[0], _KNAV[1], _KNAV[2]))
    _ch2 = get(_cb, '/api/status').get('chooser') or {}
    _picked = post(_cb, '/api/choose', {'id': _ch2.get('id'), 'pick': _two[0].get('holdId')})
    time.sleep(0.3)     # its mark row is appended after the reply
    eq('[carry two] ...a row picked in time files the address on that order, cue chooser',
       (_picked[0], [o.get('dropoff') for o in _orders(_cb)],
        [(r.get('id'), r.get('cue')) for r in _rows(_cj, 'mark')
         if r.get('dropoff') == _KNAV[0]]),
       (200, [_KNAV[0], _BNAV[0]], [('c-a', 'chooser')]))

    # ...and a card being screened when the press comes is a row of its own,
    # which files the address on that card.
    _say(_card('c-s', 12.5, minutes=25.0, miles=3.0))
    _SNAV = ('9 Elm Ct, Smyrna, GA 30080', '9 Elm Ct', 'Smyrna')
    _say(_nav(_SNAV[0], _SNAV[1], _SNAV[2]))
    _ch3 = get(_cb, '/api/status').get('chooser') or {}
    _pc = post(_cb, '/api/choose', {'id': _ch3.get('id'), 'pick': 'card'})
    time.sleep(0.3)
    eq('[carry two] a card being screened is the chooser\'s third row, and picking it files '
       'the address on that card',
       (_ch3.get('card'), _pc[0],
        [(r.get('id'), r.get('cue')) for r in _rows(_cj, 'mark') if r.get('dropoff') == _SNAV[0]],
        [o.get('dropoff') for o in _orders(_cb)]),
       ({'pick': 'card', 'pay': 12.5}, 200, [('c-s', 'chooser')], [_KNAV[0], _BNAV[0]]))

    # A Trip Planner listing both orders — ②'s end, then ①'s — read now
    # that both ends are filed: each order says where on it its end is
    # (`planAt`, by Assemble.sameStreet against the order's own end), which
    # is how Map view runs the car through both in the planner's order. A
    # planner placing one end, or the same end twice, places neither. With
    # one order in the car there is no planAt at all: its shape is the one
    # it had.
    def _plan(*stops):
        return {'planner': {'stops': [dict({'orders': 1, 'expectedBy': None, 'city': None,
                                            'state': None, 'zip': None}, **s) for s in stops],
                            'unfiled': None, 'asked': True, 'ms': 10}}
    _PU = {'kind': 'pickup', 'name': 'Larkspur Tacos', 'street': '310 Mill St',
           'line': '310 Mill St, Roswell, GA 30075'}
    _DB = {'kind': 'dropoff', 'name': 'Lee M.', 'street': '77 Birch Ln', 'line': '77 Birch Ln, Roswell'}
    _DK = {'kind': 'dropoff', 'name': 'Pat Q.', 'street': '4821 Kestrel Dr',
           'line': '4821 Kestrel Dr, Marietta'}
    #
    # Each planner below on a hold that keeps none: a pressed read MERGES
    # with the stops kept since 24 Oct (the owner's "Would there be a way to
    # have the scan button also merge?"), so a read leaving ①'s end out would
    # no longer take it off. A different card on the record between them
    # forgets the planner (forgetPlanner), the one moment that still does.
    _say(_plan(_PU, _DB, _DK))
    _both = [o.get('planAt') for o in _orders(_cb)]
    _say(_card('c-forget-1', 5.0))
    _say(_plan(_PU, _DB))
    _half = [o.get('planAt') for o in _orders(_cb)]
    _say(_card('c-forget-2', 5.0))
    _say(_plan(_PU, _DB, dict(_DB, name='Lee M. again')))
    _twice = [o.get('planAt') for o in _orders(_cb)]
    eq('[carry two] one planner listing both orders sets the run order: each order says '
       'where its end is on it, and only when it is there once',
       (_both, _half, _twice, 'planAt' in (_one[0] if _one else {'planAt': 0})),
       ([2, 1], [None, 1], [None, None], False))

    # A card offered while both are in the car: its pair row names the first
    # as `held` and the second beside it, and since Stage 6 its range is
    # against BOTH (Advice.stackMany) — every order's minutes left and the
    # card's at the far end — and the row says so in `stack.over`.
    _say(_card('c-p', 14.0, minutes=25.0, miles=4.0))
    _pair = [r for r in _rows(_cj, 'pair') if r.get('id') == 'c-p']
    eq('[carry two] a pair row keeps held as the first-taken order and adds heldAlso and heldCount',
       [((r.get('held') or {}).get('pay'), [h.get('pay') for h in r.get('heldAlso') or []],
         r.get('heldCount')) for r in _pair], [(9.48, [28.08], 2)])
    # A had 40 min and B 55, both taken moments ago: the far end is about
    # 40 + 55 + 25 = 120, where against A alone it was about 65.
    _ps = (_pair[0].get('stack') or {}) if _pair else {}
    ok_('[carry two] the pair row\'s range is against both orders in the car, stack.over 2 (%r)'
        % _ps, _ps.get('over') == 2 and 115 < (_ps.get('maxMinutes') or 0) <= 120
        and 50 < (_ps.get('minMinutes') or 0) <= 55)
    _say({'ready': True, 'state': 'go', 'perHour': 30.0, 'grossPerHour': 33.6,
          'pay': 14.0, 'minutes': 25.0, 'billedMinutes': 25.0, 'cardMinutes': 25.0,
          'miles': 4.0, 'cost': 1.4, 'target': 25, 'band': 15, 'costPerMile': 0.35})
    _st = get(_cb, '/api/status')
    _ls = (_st.get('last') or {}).get('stack') or {}
    eq('[carry two] ...and the stack line on the reading is against both, as the row is, '
       'and says how many',
       # (Within 0.1: each of leftEach is rounded to 0.1 on its own, so the
       # sum can sit a tenth off the unrounded maxMinutes depending on the
       # second the reading lands — it did, steadily, once the planner checks
       # above put two cards on the record, 24 Oct.)
       (_ls.get('heldCount'), 'vsFirst' in _ls, len(_ls.get('leftEach') or []),
        abs(round((_ls.get('maxMinutes') or 0) - sum(_ls.get('leftEach') or []), 1) - 25.0)
        <= 0.11),
       (2, False, 2, True))
    # ...and an Uber add-on card ("+15 min (+ 3 mi) total") offered against
    # the two: its 15 minutes are what the trip grows by, so the shortest
    # time is the longest order's left AND those 15, on the row (the offer
    # line's own screen) and on the panel (the reading of that same card,
    # typed off the card on record — addOnAsCarded).
    _say(_card('c-x', 6.0, minutes=15.0, miles=3.0, screen='uber.addon'))
    _say({'ready': True, 'state': 'no', 'perHour': 18.0, 'grossPerHour': 24.0,
          'pay': 6.0, 'minutes': 15.0, 'billedMinutes': 15.0, 'cardMinutes': 15.0,
          'miles': 3.0, 'cost': 1.05, 'target': 25, 'band': 15, 'costPerMile': 0.35})
    _px = ([r for r in _rows(_cj, 'pair') if r.get('id') == 'c-x'] or [{}])[0].get('stack') or {}
    _lx = (get(_cb, '/api/status').get('last') or {}).get('stack') or {}
    eq('[carry two] an add-on offered with two in the car: its range is its card\'s extension, '
       'on the pair row and on the panel',
       [round((x.get('minMinutes') or 0) - (x.get('leftMinutes') or 0), 1) for x in (_px, _lx)],
       [15.0, 15.0])

    # A third Took: of the two orders already in the car, the one whose clock
    # ends soonest goes, and its pay is said. A (40 min, taken first) ends
    # before B (55 min).
    _r3 = _took2(_cb, _card('c-c', 6.25, minutes=20.0, deliver_by=None))
    # The drop row is appended after the reply is on its way: waited for.
    for _ in range(40):
        _drop3 = [r for r in _rows(_cj, 'drop') if r.get('id') == 'c-a']
        if _drop3:
            break
        time.sleep(0.05)
    eq('a third Took puts down the soonest-ending order',
       ([o.get('pay') for o in _orders(_cb)],
        [(r.get('by'), r.get('carried')) for r in _drop3],
        (_r3.get('replaced') or {}).get('pay')),
       ([28.08, 6.25], [('replaced', 2)], 9.48))
finally:
    stop(_cp)


# --- the navigation screen, read on its own while an order is held -----------
#
# The driver's ask: while an order is held the rig reads the navigation and
# "Deliver to" screens on its own, as it reads the Trip Planner, and the
# destination fills in with no ⌖. The scanner sends the whole-screen read as a
# sighting (rpi/scan_pi.py, sighting); the assembler makes the navigation
# destination (assemble.js, navCandidate) and files it at rank `nav`. Through
# the real server and a scanner that says what the suite writes. Every name,
# store and street invented.
def _navsight(line, street, city, zip_=None, kind='dropoff', screen='uber.nav',
              expected=None, app='uber'):
    return {'sighting': {
        'asked': False, 'whole': True, 'titled': False, 'app': app, 'screen': screen,
        'page': {'top': None, 'bottom': None},
        'stops': [{'kind': kind, 'orders': None, 'name': None, 'place': None,
                   'expectedBy': expected, 'street': street, 'city': city, 'state': 'GA',
                   'zip': zip_, 'line': line, 'partial': None,
                   'label': 'dropoff' if kind == 'dropoff' else kind}],
        'orderCount': None, 'keep': True}}


def _held_end(base):
    h = get(base, '/api/status').get('holding') or {}
    return (h.get('dropoff'), ((h.get('fields') or {}).get('dropoff') or {}).get('from'))


_CORNER = 'Oak Dr & Elm Dr, Acworth'
_np, _nb, _nj, _nh = _cserver('nav', CARRY_TWO='1')
try:
    _took2(_nb, _card('n-a', 12.0, dropoff=_CORNER))
    _L1 = ('2950 Kestrel Dr, Woodstock, GA 30188', '2950 Kestrel Dr', 'Woodstock', '30188')
    _say(_navsight(*_L1))
    eq('a navigation screen under "Deliver to" fills the held order\'s destination with no '
       'press', _held_end(_nb), (_L1[0], 'nav'))
    eq('...written down as a held-dropoff mark, unasked and label-proven',
       [(r.get('asked'), r.get('labelled')) for r in _rows(_nj, 'mark')
        if r.get('id') == 'n-a' and r.get('dropoff') == _L1[0]], [(False, True)])
    # A press, then the screen again: a different address, and the pressed one
    # read fuller. Neither moves it.
    _say(_nav('77 Birch Ln, Woodstock', '77 Birch Ln', 'Woodstock'))
    ok_('the premise: the press is filed', _held_end(_nb) == ('77 Birch Ln, Woodstock', 'press'))
    _say(_navsight('77 Birch Ln, Woodstock, GA 30188', '77 Birch Ln', 'Woodstock', '30188'),
         _navsight('9 Fable Ct, Woodstock, GA 30188', '9 Fable Ct', 'Woodstock', '30188'))
    eq('...never over a ⌖ press', _held_end(_nb), ('77 Birch Ln, Woodstock', 'press'))
    post(_nb, '/api/offers/mark', {'id': 'n-a', 'accepted': None})

    # A store's navigation — even one that names the next stop under
    # "Deliver to" — and an address under no label, each over the card's own
    # corner, which a navigation destination would replace.
    _took2(_nb, _card('n-b', 15.0, dropoff=_CORNER))
    _say(_navsight('2950 Kestrel Dr, Woodstock, GA 30188', '2950 Kestrel Dr', 'Woodstock',
                   '30188', screen='uber.pickupNav'))
    eq('a pickup navigation screen files nothing', _held_end(_nb), (_CORNER, 'card'))
    _say(_navsight('31 Larch Way, Woodstock, GA 30188', '31 Larch Way', 'Woodstock', '30188',
                   kind=None))
    eq('an unlabelled navigation address files nothing', _held_end(_nb), (_CORNER, 'card'))
    _say(_navsight('31 Larch Way, Woodstock, GA 30188', '31 Larch Way', 'Woodstock', '30188'))
    eq('...and the premise: the same address under its label is filed',
       _held_end(_nb), ('31 Larch Way, Woodstock, GA 30188', 'nav'))

    # Two orders in the car: the existing cues, and with none it waits.
    _took2(_nb, _card('n-c', 22.0, minutes=50.0, dropoff=_CORNER,
                      deliver_by=(_NOWMIN + 70) % 1440))
    ok_('the premise: two orders in the car', len(_orders(_nb)) == 2)
    _L4 = ('4 Heron Bend, Smyrna, GA 30080', '4 Heron Bend', 'Smyrna', '30080')
    _say(_navsight(*_L4))
    eq('[carry two] auto-nav: with two orders held, a navigation destination no cue decides '
       'files nothing and waits', ([o.get('dropoff') for o in _orders(_nb)],
                                   get(_nb, '/api/status').get('unowned'),
                                   get(_nb, '/api/status').get('chooser')),
       (['31 Larch Way, Woodstock, GA 30188', _CORNER], 1, None))
    _say(_navsight('8 Wren Pl, Smyrna, GA 30080', '8 Wren Pl', 'Smyrna', '30080',
                   expected=(_NOWMIN + 71) % 1440))
    eq('[carry two] auto-nav: ...and one whose bar\'s "Expected by" is one card\'s "Deliver by" '
       'files on that order, by the deadline cue',
       ([o.get('dropoff') for o in _orders(_nb)],
        [(r.get('id'), r.get('cue')) for r in _rows(_nj, 'mark')
         if r.get('dropoff') == '8 Wren Pl, Smyrna, GA 30080']),
       (['31 Larch Way, Woodstock, GA 30188', '8 Wren Pl, Smyrna, GA 30080'],
        [('n-c', 'deadline')]))
finally:
    stop(_np)

# Drop with two in the car, and the GPS drop at one door.
_PA = (33.9100, -84.5100)
_PB = (33.9400, -84.5400)
_AD = '4821 Kestrel Dr, Marietta'
_BD = '77 Birch Ln, Roswell'


def _pin2(base, hid, dropoff, at, name):
    return post(base, '/api/held-end', {'holdId': hid, 'dropoff': dropoff, 'lat': at[0],
                                        'lon': at[1], 'name': name, 'doorLevel': True})


def _beat(at, ok=True):
    return {'alive': True, 'gps': {'state': 'ok', 'ageSeconds': 0.1,
            'fix': {'lat': at[0], 'lon': at[1], 'gpsAge': 0.1, 'gpsErr': 10.0,
                    'gpsMode': 3, 'gpsOk': ok, 'gpsWhy': None, 'freshFor': 10.0}}}


def _pinned_pair(base):
    _took2(base, _card('d-a', 11.0, minutes=40.0, dropoff=_AD))
    _took2(base, _card('d-b', 17.5, minutes=50.0, dropoff=_BD))
    o = _orders(base)
    _pin2(base, o[0]['holdId'], _AD, _PA, '4821, Kestrel Drive, Marietta')
    _pin2(base, o[1]['holdId'], _BD, _PB, '77, Birch Lane, Roswell')
    return _orders(base)


_dp, _db, _dj, _dh = _cserver('drop', CARRY_TWO='1', GPS_DWELL_MS='600')
try:
    _o = _pinned_pair(_db)
    ok_('[carry two] (both doors pinned)', all(x.get('endPinned') for x in _o))
    # Nowhere near either door: Drop does not guess.
    _say(_beat((33.80, -84.40)))
    _code, _rep = post(_db, '/api/delivered', {})
    eq('[carry two] Drop with two in the car and no door to go by offers ①, ② and puts '
       'nothing down',
       (_code, [r.get('n') for r in (_rep.get('choose') or {}).get('rows') or []],
        len(_orders(_db)), _rows(_dj, 'drop')), (200, [1, 2], 2, []))
    # At ①'s door: one tap, ① only.
    _say(_beat(_PA))
    _code, _rep = post(_db, '/api/delivered', {})
    eq('Drop at one door leaves the other',
       (_code, _rep.get('choose'), [x.get('pay') for x in _orders(_db)],
        [(r.get('id'), r.get('by'), r.get('carried')) for r in _rows(_dj, 'drop')]),
       (200, None, [17.5], [('d-a', None, 2)]))
    # ...and the chooser's answer, 'both': two rows, by the chooser.
    _took2(_db, _card('d-c', 8.0, minutes=30.0))
    _o = _orders(_db)
    _code, _rep = post(_db, '/api/delivered', {'holdIds': [x['holdId'] for x in _o]})
    eq('[carry two] the Drop chooser\'s Both puts both down, by the chooser, carried 2',
       (_code, _orders(_db), sorted((r.get('id'), r.get('by'), r.get('carried'))
                                    for r in _rows(_dj, 'drop') if r.get('id') != 'd-a')),
       (200, [], [('d-b', 'chooser', 2), ('d-c', 'chooser', 2)]))

    # The GPS drop: dwell at ①'s door, then leave it.
    _o = _pinned_pair(_db)
    _say(*([_beat(_PA)] * 16))
    _say(*([_beat((_PA[0] + 0.006, _PA[1]))] * 3))
    eq('a GPS drop at ①\'s door keeps ②',
       ([x.get('pay') for x in _orders(_db)],
        [(r.get('by'), r.get('carried')) for r in _rows(_dj, 'drop')
         if r.get('id') == 'd-a' and r.get('by') == 'gps']),
       ([17.5], [('gps', 2)]))
finally:
    stop(_dp)

# A re-offer, a different card, an add-on, a two-order DoorDash card, and a
# planner that grows with nobody pressing Took.
_rp, _rb2, _rj, _rh = _cserver('reoffer', CARRY_TWO='1')
try:
    _X = dict(minutes=35.0, miles=6.2, pickup='Wren Street Noodles', dropoff='12 Oak St, Marietta')
    _took2(_rb2, _card('r-1', 12.40, **_X))
    _took2(_rb2, _card('r-2', 13.15, **_X))
    _after_re = [x.get('pay') for x in _orders(_rb2)]
    _took2(_rb2, _card('r-3', 7.80, minutes=22.0, miles=3.1, pickup='Larkspur Tacos',
                       dropoff='9 Elm Ct, Smyrna'))
    eq('a re-offer replaces, a different card adds',
       (_after_re, [x.get('pay') for x in _orders(_rb2)],
        [(r.get('id'), r.get('by')) for r in _rows(_rj, 'drop')]),
       ([13.15], [13.15, 7.80], [('r-1', 'replaced')]))
    post(_rb2, '/api/delivered', {'holdIds': [x['holdId'] for x in _orders(_rb2)]})

    # The add-on: Uber's "+N min" card onto the Uber trip in the car.
    _took2(_rb2, _card('r-base', 18.0, minutes=60.0))
    _took2(_rb2, _card('r-add', 4.50, minutes=10.0, screen='uber.addon'))
    _hf = json.load(open(os.path.join(os.path.dirname(_rj), 'holding.json')))['orders']
    _base, _add = _hf[0], _hf[1]
    _base_ends = _base['acceptedAt'] + 60 * 1.5 * 60000 + 600000
    eq('the add-on expires with its base',
       (_add.get('addOn'), _add.get('of'), _add.get('ofEnds'),
        json.load(open(os.path.join(_rh, 'uberscan-holding.json'))).get('until')),
       (True, _base['holdId'], _base_ends, _base_ends + 10 * 1.5 * 60000))
    post(_rb2, '/api/delivered', {'holdIds': [x['holdId'] for x in _orders(_rb2)]})

    # DoorDash's card for two orders is one card and one Took.
    _took2(_rb2, _card('r-dd', 21.0, minutes=45.0, app='doordash', screen='dd.offer',
                       multiOrder=True, legs=2))
    eq('[carry two] one Took on a DoorDash "Drop off 2 orders" card stays one hold',
       [x.get('pay') for x in _orders(_rb2)], [21.0])
    _took2(_rb2, _card('r-ub', 9.10, minutes=30.0))
    # A Trip Planner that grows by a stop, with no Took: no order is added.
    def _plan(drops):
        stops = [{'kind': 'pickup', 'orders': 1, 'name': 'Wren Street Noodles',
                  'expectedBy': 700, 'street': '5 Mill St', 'city': 'Roswell', 'state': 'GA',
                  'zip': None, 'line': '5 Mill St, Roswell', 'partial': None}]
        for i, nm in enumerate(drops):
            stops.append({'kind': 'dropoff', 'orders': 1, 'name': nm, 'expectedBy': 720 + i,
                          'street': '%d Pine Rd' % (10 + i), 'city': 'Roswell',
                          'state': 'GA', 'zip': None,
                          'line': '%d Pine Rd, Roswell' % (10 + i), 'partial': None})
        return {'sighting': {'asked': False, 'whole': True, 'titled': True, 'app': 'uber',
                             'screen': 'uber.planner', 'page': {'top': True, 'bottom': True},
                             'stops': stops, 'orderCount': None, 'keep': False}}
    _say(_plan(['Mara T.']))
    _say(_plan(['Mara T.', 'Jules K.']))
    _say(_plan(['Mara T.', 'Jules K.', 'Ines V.']))
    eq('a planner that grows with no Took adds no order',
       [x.get('pay') for x in _orders(_rb2)], [21.0, 9.10])
finally:
    stop(_rp)

# >>> add-on
# Uber's add-on with carrying two OFF: the owner's decision of 17 Oct 2026.
# On the 16 Oct shift the driver ticked "+ $9.50 / +8 min (+1.3 mi)" with an
# order in the car, and the Took replaced it — a drop row `by: 'replaced'` for
# an order whose planner door was on record, and a hold that knew only the
# add-on, on its own 21-minute clock. Uber paid the two as one trip. Now the
# add-on joins the trip in the car (server.js placeTook, tripOf), the planner
# that shows both orders files each door on a cue or not at all, and the
# trip's details for that night — a second add-on on the same trip, $25.03 +
# $9.50 + $6.89 — are held as three orders of one trip. Every name, store and
# street is invented.
_HOLD_GRACE = 600000


def _tplan(picks, drops, bottom=True):
    """An unprompted Trip Planner read whole: `picks` store names, `drops`
    (customer, street, Expected by) — the list seen to its foot unless
    `bottom` is False."""
    stops = [{'kind': 'pickup', 'orders': 1, 'name': nm, 'expectedBy': 700 + i,
              'street': '%d Mill St' % (5 + i), 'city': 'Smyrna', 'state': 'GA', 'zip': None,
              'line': '%d Mill St, Smyrna' % (5 + i), 'partial': None}
             for i, nm in enumerate(picks)]
    stops += [{'kind': 'dropoff', 'orders': 1, 'name': nm, 'expectedBy': by, 'street': st,
               'city': 'Smyrna', 'state': 'GA', 'zip': None, 'line': st + ', Smyrna',
               'partial': None} for nm, st, by in drops]
    return {'sighting': {'asked': False, 'whole': True, 'titled': True, 'app': 'uber',
                         'screen': 'uber.planner', 'page': {'top': True, 'bottom': bottom},
                         'stops': stops, 'orderCount': None, 'keep': False}}


def _holdfile(base_dir):
    return json.load(open(os.path.join(os.path.dirname(base_dir), 'holding.json')))['orders']


def _until(hand):
    return json.load(open(os.path.join(hand, 'uberscan-holding.json'))).get('until')


_MARA = ('Mara T.', '4821 Kestrel Dr', 1202)
_JULES = ('Jules K.', '77 Birch Ln', 1220)
_ap, _ab, _aj, _ah = _cserver('addon', CARRY_TWO='0')
try:
    _took2(_ab, _card('u-a', 25.03, minutes=31.0, miles=9.4, pickup='Fable Grill'))
    _say(_tplan(['Fable Grill'], [_MARA]))
    eq('[add-on] the premise: the order in the car has its planner door',
       _held_end(_ab), ('4821 Kestrel Dr, Smyrna', 'planner'))
    # The add-on, typed by the parser's `addon` alone (its leg lost its plus
    # signs, so the screen type says uber.offer).
    _rep = _took2(_ab, _card('u-b', 9.50, minutes=8.0, miles=1.3, pickup='Kestrel Noodle Bar',
                             addon=True))
    _st = get(_ab, '/api/status')
    eq('[add-on] ✓ Took on an add-on with an order in the car keeps that order and holds the '
       'add-on beside it, carrying two off: no drop row, the first order\'s door kept',
       ([o.get('pay') for o in _orders(_ab)], _rows(_aj, 'drop'), _st.get('carryTwo'),
        _held_end(_ab)),
       ([25.03, 9.5], [], False, ('4821 Kestrel Dr, Smyrna', 'planner')))
    _hf = _holdfile(_aj)
    _aend = _hf[0]['acceptedAt'] + 31 * 1.5 * 60000 + _HOLD_GRACE
    eq('[add-on] ...joined to it, and held to its end and then its own +8 min, half again — '
       'not its own clock alone',
       (_hf[1].get('addOn'), _hf[1].get('of'), _hf[1].get('ofEnds'), _until(_ah)),
       (True, _hf[0]['holdId'], _aend, _aend + 8 * 1.5 * 60000))
    eq('[add-on] the Took marks say which is the add-on, and to which order, by id',
       [(r.get('id'), r.get('addon'), r.get('addonTo')) for r in _rows(_aj, 'mark')
        if r.get('accepted') is True],
       [('u-a', None, None), ('u-b', True, _hf[0]['holdId'])])
    eq('[add-on] ...and the panel is told both orders, the second an add-on of the first, '
       'with its Undo',
       ([(o.get('n'), o.get('addOn'), o.get('of')) for o in _orders(_ab)],
        [(o.get('n'), o.get('addOn')) for o in _rep.get('orders') or []],
        (_rep.get('added') or {}).get('id')),
       ([(1, False, None), (2, True, _hf[0]['holdId'])], [(1, False), (2, True)], 'u-b'))
    # The list ran off the screen: a lone dropoff is a single-trip rule, and
    # this is no single trip.
    _say(_tplan(['Fable Grill', 'Kestrel Noodle Bar'], [_JULES], bottom=False))
    eq('[add-on] a planner whose foot is off the screen files nothing onto either order',
       ([o.get('dropoff') for o in _orders(_ab)], get(_ab, '/api/status').get('unowned')),
       (['4821 Kestrel Dr, Smyrna', None], 0))
    _say(_tplan(['Fable Grill', 'Kestrel Noodle Bar'], [_MARA, _JULES]))
    _st = get(_ab, '/api/status')
    eq('[add-on] the Trip Planner with both orders\' stops, read with nobody pressing: each '
       'door onto its own order — the add-on\'s by growth — nothing waiting, no chooser',
       ([o.get('dropoff') for o in _orders(_ab)], _st.get('unowned'), _st.get('chooser'),
        [(r.get('id'), r.get('cue')) for r in _rows(_aj, 'mark')
         if r.get('dropoff') == '77 Birch Ln, Smyrna']),
       (['4821 Kestrel Dr, Smyrna', '77 Birch Ln, Smyrna'], 0, None, [('u-b', 'growth')]))
    _pl = _tplan(['Fable Grill', 'Kestrel Noodle Bar'], [_MARA, _JULES])['sighting']['stops']
    _say({'planner': {'stops': _pl, 'unfiled': None, 'asked': False, 'ms': None,
                      'at': int(time.time() * 1000)}})
    eq('[add-on] ...and its two pickups are each marked with its own order, by the store',
       [s.get('of') for s in (_holdfile(_aj)[0].get('planner') or {}).get('stops') or []
        if s.get('kind') == 'pickup'], [_hf[0]['holdId'], _hf[1]['holdId']])
    # A new offer, weighed against the trip in the car as carrying two weighs
    # one against two orders.
    _say(_card('u-p', 14.0, minutes=25.0, miles=4.0))
    _say({'ready': True, 'state': 'go', 'perHour': 30.0, 'grossPerHour': 33.6,
          'pay': 14.0, 'minutes': 25.0, 'billedMinutes': 25.0, 'cardMinutes': 25.0,
          'miles': 4.0, 'cost': 1.4, 'target': 25, 'band': 15, 'costPerMile': 0.35})
    _ls = (get(_ab, '/api/status').get('last') or {}).get('stack') or {}
    _pr = ([r for r in _rows(_aj, 'pair') if r.get('id') == 'u-p'] or [{}])[0]
    eq('[add-on] a new offer is weighed against both orders, on the panel and the pair row',
       (_ls.get('heldCount'), 'vsFirst' in _ls, _pr.get('heldCount'),
        [h.get('pay') for h in _pr.get('heldAlso') or []]),
       (2, False, 2, [9.5]))
    # The second add-on on the same trip (the owner's trip details: $25.03 +
    # $9.50 + $6.89, one trip).
    _took2(_ab, _card('u-c', 6.89, minutes=9.0, miles=2.1, screen='uber.addon'))
    _hf3 = _holdfile(_aj)
    _bend = _aend + 8 * 1.5 * 60000
    eq('[add-on] a second add-on joins the same trip: three orders, nothing put down, held '
       'to the trip\'s end and then its own',
       ([o.get('pay') for o in _orders(_ab)], [o.get('of') for o in _hf3],
        _hf3[2].get('ofEnds'), _rows(_aj, 'drop')),
       ([25.03, 9.5, 6.89], [None, _hf[0]['holdId'], _hf[0]['holdId']], _bend, []))
    # The manual ⌖ Scan stays the backup: with no cue, the chooser, over all
    # three, and nothing filed.
    _say(_nav('3 Ash Way, Smyrna, GA 30080', '3 Ash Way', 'Smyrna'))
    _ch = get(_ab, '/api/status').get('chooser') or {}
    eq('[add-on] ⌖ Scan with the trip in the car and no cue opens the chooser over its '
       'three orders and files nothing',
       ([r.get('n') for r in _ch.get('rows') or []], [o.get('dropoff') for o in _orders(_ab)]),
       ([1, 2, 3], ['4821 Kestrel Dr, Smyrna', '77 Birch Ln, Smyrna', None]))
    post(_ab, '/api/choose', {'id': _ch.get('id'), 'pick': 'neither'})
    # Drop with nothing to say which was delivered: the Drop chooser, as with
    # two carried, and nothing put down.
    _code, _rep = post(_ab, '/api/delivered', {})
    eq('[add-on] Drop with the trip in the car and no door to go by offers its three orders '
       'and puts nothing down',
       ([r.get('n') for r in (_rep.get('choose') or {}).get('rows') or []],
        len(_orders(_ab)), _rows(_aj, 'drop')), ([1, 2, 3], 3, []))
    # The original delivered: its add-ons stay, still one trip.
    _ids = [o['holdId'] for o in _orders(_ab)]
    _code, _rep = post(_ab, '/api/delivered', {'holdIds': [_ids[0]]})
    eq('[add-on] Drop of the original leaves its add-ons held, still one trip, and the reply '
       'says so',
       ([o.get('pay') for o in _orders(_ab)], [o.get('pay') for o in _rep.get('orders') or []],
        [(r.get('id'), r.get('by'), r.get('carried'), r.get('addon')) for r in _rows(_aj, 'drop')]),
       ([9.5, 6.89], [9.5, 6.89], [('u-a', 'chooser', 3, None)]))
    post(_ab, '/api/delivered', {'holdIds': [_ids[1]]})
    _st = get(_ab, '/api/status')
    eq('[add-on] ...and the last one left is held on its own, its drop row saying it was an '
       'add-on and of which order',
       ((_st.get('holding') or {}).get('pay'), 'orders' in _st,
        [(r.get('id'), r.get('addon'), r.get('addonTo')) for r in _rows(_aj, 'drop')
         if r.get('id') == 'u-b']),
       (6.89, False, [('u-b', True, _hf[0]['holdId'])]))
    post(_ab, '/api/delivered', {})

    # Carrying two off and an ordinary card: the trip is the order in the car,
    # and a Took replaces it as it always replaced one — every order of it.
    _took2(_ab, _card('u-d', 18.0, minutes=40.0))
    _took2(_ab, _card('u-e', 5.0, minutes=10.0, addon=True))
    _rep = _took2(_ab, _card('u-f', 12.0, minutes=30.0))
    _st = get(_ab, '/api/status')
    eq('[add-on] carrying two off, a Took on an ordinary card replaces the trip in the car, '
       'every order of it, and the reply says the one now held',
       ((_st.get('holding') or {}).get('pay'), 'orders' in _st,
        [(r.get('id'), r.get('by'), r.get('addon')) for r in _rows(_aj, 'drop')
         if r.get('id') in ('u-d', 'u-e')],
        [o.get('pay') for o in _rep.get('orders') or []]),
       (12.0, False, [('u-d', 'replaced', None), ('u-e', 'replaced', True)], [12.0]))
    post(_ab, '/api/delivered', {})

    # An add-on with nothing in the car: an order of its own, on its own
    # clock — and a second ✓ on it is a Took pressed twice, never onto itself.
    _took2(_ab, _card('u-g', 4.0, minutes=8.0, addon=True))
    _took2(_ab, _card('u-g', 4.0, minutes=8.0, addon=True))
    _hg = _holdfile(_aj)
    eq('[add-on] an add-on with nothing in the car is held as an order of its own, on its '
       'own clock, and pressed twice joins nothing',
       (len(_hg), _hg[0].get('addOn'), _hg[0].get('of'), _until(_ah)),
       (1, True, None, _hg[0]['acceptedAt'] + 8 * 1.5 * 60000 + _HOLD_GRACE))
    post(_ab, '/api/delivered', {})
    # ...and with only another app's order in the car it joins nothing either:
    # carrying two off, it replaces that order, as any card does.
    _took2(_ab, _card('u-h', 11.0, minutes=30.0, app='doordash', screen='dd.offer'))
    _took2(_ab, _card('u-i', 6.0, minutes=10.0, addon=True))
    eq('[add-on] ...and one with only a DoorDash order in the car joins nothing: it replaces it',
       ((get(_ab, '/api/status').get('holding') or {}).get('pay'),
        [(r.get('id'), r.get('by')) for r in _rows(_aj, 'drop') if r.get('id') == 'u-h']),
       (6.0, [('u-h', 'replaced')]))
finally:
    stop(_ap)

# No cue, no filing: the planner showing both orders' doors with nothing on
# record to tell them apart files neither, and they wait. The ⌖ backup then
# gives the original its door, from the chooser, and the cue that gives the
# other its door is that one — the waiting doors asked again (retryPool).
# And every message that says the car to the panel says the trip, as it says
# two orders carried.
_qp, _qb, _qj, _qh = _cserver('addonpool', CARRY_TWO='0')
try:
    _qseen = listen(_qb, 40)
    time.sleep(0.3)
    _took2(_qb, _card('q-a', 22.46, minutes=40.0, pickup='Fable Grill'))
    _took2(_qb, _card('q-b', 9.64, minutes=19.0, addon=True, pickup='Kestrel Noodle Bar'))
    _say(_tplan(['Fable Grill', 'Kestrel Noodle Bar'], [_MARA, _JULES]))
    _st = get(_qb, '/api/status')
    eq('[add-on] the planner with both doors and no cue files neither: they wait, said',
       ([o.get('dropoff') for o in _orders(_qb)], _st.get('unowned'), _st.get('chooser'),
        [r for r in _rows(_qj, 'mark') if r.get('dropoff')]),
       ([None, None], 2, None, []))
    _say(_nav('4821 Kestrel Dr, Smyrna', '4821 Kestrel Dr', 'Smyrna'))
    _ch = get(_qb, '/api/status').get('chooser') or {}
    post(_qb, '/api/choose', {'id': _ch.get('id'), 'pick': (_ch.get('rows') or [{}])[0].get('pick')})
    time.sleep(0.4)
    _st = get(_qb, '/api/status')
    eq('[add-on] ...and the original\'s door given from the ⌖ chooser decides the other: '
       'the add-on\'s by elimination, nothing left waiting',
       ([o.get('dropoff') for o in _orders(_qb)], _st.get('unowned'),
        sorted((r.get('id'), r.get('cue')) for r in _rows(_qj, 'mark') if r.get('dropoff'))),
       (['4821 Kestrel Dr, Smyrna', '77 Birch Ln, Smyrna'], 0,
        [('q-a', 'chooser'), ('q-b', 'elimination')]))
    # An add-on card offered against the trip: its minutes are what the trip
    # grows by (addOnAsCarded), and the reading carries the orders.
    _say(_card('q-x', 6.0, minutes=15.0, miles=3.0, addon=True))
    _say({'ready': True, 'state': 'no', 'perHour': 18.0, 'grossPerHour': 24.0,
          'pay': 6.0, 'minutes': 15.0, 'billedMinutes': 15.0, 'cardMinutes': 15.0,
          'miles': 3.0, 'cost': 1.05, 'target': 25, 'band': 15, 'costPerMile': 0.35})
    _last = get(_qb, '/api/status').get('last') or {}
    _lx = _last.get('stack') or {}
    eq('[add-on] an add-on card offered against the trip: its range is its card\'s extension, '
       'and the reading names both orders',
       (round((_lx.get('minMinutes') or 0) - (_lx.get('leftMinutes') or 0), 1),
        [o.get('pay') for o in _last.get('orders') or []]),
       (15.0, [22.46, 9.64]))
    _say(_beat((33.80, -84.40)))
    time.sleep(0.3)
    eq('[add-on] the beat and the filed door both carry the trip\'s orders to the panel',
       ([len(m.get('orders') or []) for m in _qseen if m.get('alive') and 'orders' in m][-1:],
        [len(m.get('orders') or []) for m in _qseen
         if (m.get('dropoff') or {}).get('line') == '77 Birch Ln, Smyrna' and 'orders' in m][:1]),
       ([2], [2]))
finally:
    stop(_qp)

# The owner's snap of 20 Oct, 19:06–19:08 (names and streets invented): an
# Uber order held off a card ending at a corner, an add-on onto its trip, and
# the Trip Planner seen only in pages scrolled — never the list whole. The
# add-on's door read first waits; the order's own door is on its card's
# corner (cardStreet), and that decides the waiting one (elimination).
def _ppage(top, drops):
    stops = [{'kind': 'dropoff', 'orders': 1, 'name': nm, 'expectedBy': by, 'street': st,
              'city': town, 'state': 'GA', 'zip': None, 'line': st + ', ' + town,
              'partial': None} for nm, st, town, by in drops]
    return {'sighting': {'asked': False, 'whole': True, 'titled': top, 'app': 'uber',
                         'screen': 'uber.planner', 'page': {'top': top, 'bottom': False},
                         'stops': stops, 'orderCount': None, 'keep': False}}


_sp, _sb, _sj, _sh = _cserver('cardstreet', CARRY_TWO='0')
try:
    _took2(_sb, _card('s-a', 8.14, minutes=22.0, pickup='Fable Grill',
                      dropoff='Larkspur Rd NW & Ombre Cir NW, Kennesaw'))
    _took2(_sb, _card('s-b', 16.43, minutes=18.0, addon=True, pickup='Kestrel Noodle Bar'))
    _say(_ppage(True, [('Ines B.', '608 Wickerby St NW', 'Marietta', 1188)]))
    _st = get(_sb, '/api/status')
    eq('[card street] a planner page not seen whole, its door on no card\'s street: '
       'nothing filed, it waits',
       ([o.get('dropoff') for o in _orders(_sb)], _st.get('unowned')),
       (['Larkspur Rd NW & Ombre Cir NW, Kennesaw', None], 1))
    _say(_ppage(False, [('Rhea A.', '1800 Ombre Cir NW', 'Kennesaw', 1170)]))
    time.sleep(0.3)
    _st = get(_sb, '/api/status')
    eq('[card street] the next page\'s door on the card\'s own corner is the order\'s '
       '(cardStreet), and the waiting door is the add-on\'s (elimination); the cue on '
       'status and the mark rows',
       ([(o.get('dropoff'), o.get('cue')) for o in _orders(_sb)], _st.get('unowned'),
        _st.get('chooser'),
        sorted((r.get('id'), r.get('cue')) for r in _rows(_sj, 'mark') if r.get('dropoff'))),
       ([('1800 Ombre Cir NW, Kennesaw', 'cardStreet'),
         ('608 Wickerby St NW, Marietta', 'elimination')], 0, None,
        [('s-a', 'cardStreet'), ('s-b', 'elimination')]))
    eq('[card street] ...both ends filed from the planner, and kept in holding.json',
       [(((o.get('fields') or {}).get('dropoff') or {}).get('from'), o.get('endCue'))
        for o in _holdfile(_sj)],
       [('planner', 'cardStreet'), ('planner', 'elimination')])
finally:
    stop(_sp)

# The owner's snap of 29 Oct, 17:47 (names, streets and towns invented): two
# Uber orders held, the add-on's card a CORNER, and the Trip Planner read in
# the card box only, listing three dropoffs. The door on the corner's street
# is the add-on's (cardStreet, off a box read now); the base order's door is
# its own; the first customer's door, on no card's street, waits — it is not
# the add-on's by elimination, as the add-on's card names other streets.
_xp, _xb, _xj, _xh = _cserver('boxcorner', CARRY_TWO='0')
try:
    _took2(_xb, _card('x-a', 14.07, minutes=30.0, pickup='Fable Grill',
                      dropoff='Tamsin Pkwy SE, Dunmore'))
    _took2(_xb, _card('x-b', 15.30, minutes=18.0, addon=True, pickup='Kestrel Noodle Bar',
                      dropoff='Vesper St & Corrow Dr NE, Dunmore'))
    _xbox = _ppage(False, [('Ines B.', '820 Halden Rd NE', 'Dunmore', 1107),
                           ('Rhea A.', '631 Corrow Dr NE', 'Dunmore', 1113),
                           ('Jules K.', '1100 S Tamsin Pkwy SE', 'Dunmore', 1122)])
    _xbox['sighting']['whole'] = False
    _say(_xbox)
    time.sleep(0.3)
    _st = get(_xb, '/api/status')
    eq('[box corner] a card-box planner with two held: each door on one card\'s street is '
       'that order\'s (cardStreet), the add-on\'s off its corner; the third waits, never '
       'the add-on\'s by elimination',
       ([(o.get('dropoff'), o.get('cue')) for o in _orders(_xb)], _st.get('unowned'),
        _st.get('chooser')),
       ([('1100 S Tamsin Pkwy SE, Dunmore', 'cardStreet'),
         ('631 Corrow Dr NE, Dunmore', 'cardStreet')], 1, None))
finally:
    stop(_xp)

# ...and with carrying two ON the trip is one order to the cap: an add-on
# joins past it, and a Took past two TRIPS puts down the trip that ends
# soonest, every order of it, said by the trip's pay.
_kp, _kb, _kj, _kh = _cserver('addonon', CARRY_TWO='1')
try:
    _took2(_kb, _card('k-a', 10.0, minutes=10.0))
    _took2(_kb, _card('k-b', 4.0, minutes=5.0, addon=True))
    _took2(_kb, _card('k-c', 20.0, minutes=60.0))
    eq('[add-on] carrying two on, an order beside a trip of two is two trips: all three held',
       ([o.get('pay') for o in _orders(_kb)], _rows(_kj, 'drop')), ([10.0, 4.0, 20.0], []))
    _rep = _took2(_kb, _card('k-d', 15.0, minutes=40.0))
    eq('[add-on] ...and a Took past two trips puts down the trip ending soonest, every order of '
       'it, said by the trip\'s pay',
       ([o.get('pay') for o in _orders(_kb)],
        sorted((r.get('id'), r.get('by')) for r in _rows(_kj, 'drop')),
        (_rep.get('replaced') or {}).get('pay')),
       ([20.0, 15.0], [('k-a', 'replaced'), ('k-b', 'replaced')], 14.0))
finally:
    stop(_kp)

# The original put down by the GPS at its door, and by its own clock: the
# add-on stays either way.
_gp, _gb, _gj, _gh = _cserver('addongps', CARRY_TWO='0', GPS_DWELL_MS='600')
try:
    _took2(_gb, _card('g-a', 22.46, minutes=40.0, dropoff=_AD))
    _took2(_gb, _card('g-b', 9.64, minutes=19.0, addon=True))
    _o = _orders(_gb)
    _pin2(_gb, _o[0]['holdId'], _AD, _PA, '4821, Kestrel Drive, Marietta')
    _say(*([_beat(_PA)] * 16))
    _say(*([_beat((_PA[0] + 0.006, _PA[1]))] * 3))
    eq('[add-on] the GPS drop at the original\'s door keeps its add-on',
       ((get(_gb, '/api/status').get('holding') or {}).get('pay'),
        [(r.get('id'), r.get('by')) for r in _rows(_gj, 'drop')]),
       (9.64, [('g-a', 'gps')]))
finally:
    stop(_gp)
_xnow = int(time.time() * 1000)
_xa = {'id': 'x-a', 'acceptedAt': _xnow - 40 * 60000, 'pay': 25.03, 'minutes': 10.0,
       'miles': 5.0, 'cost': 1.5, 'app': 'uber', 'dropoff': None}
_xb = {'id': 'x-b', 'acceptedAt': _xnow - 5 * 60000, 'pay': 9.50, 'minutes': 8.0,
       'miles': 1.3, 'cost': 0.5, 'app': 'uber', 'dropoff': None, 'addOn': True,
       'of': 'x-a@%d' % _xa['acceptedAt'], 'ofEnds': _xnow + 20 * 60000}
_xp, _xb2, _xj, _xh = _cserver('addonexp', hold={'v': 2, 'orders': [_xa, _xb]}, CARRY_TWO='0')
try:
    _st = get(_xb2, '/api/status')
    # (The expiry's row is appended after the boot's list is written.)
    for _ in range(60):
        if _rows(_xj, 'drop'):
            break
        time.sleep(0.05)
    eq('[add-on] the original run out by its own clock leaves its add-on held, to the trip\'s '
       'end and then its own',
       ((_st.get('holding') or {}).get('pay'), 'orders' in _st,
        [(r.get('id'), r.get('by')) for r in _rows(_xj, 'drop')], _until(_xh)),
       (9.5, False, [('x-a', 'expiry')], _xb['ofEnds'] + 8 * 1.5 * 60000))
finally:
    stop(_xp)
# ...and a trip of three restored at boot comes back whole: the file's cap is
# two TRIPS (MAX_HELD_FILE), and these three are one.
_ya = dict(_xa, id='y-a', acceptedAt=_xnow - 60000, minutes=31.0)
_yof = 'y-a@%d' % _ya['acceptedAt']
_yb = dict(_xb, id='y-b', of=_yof)
_yc = dict(_xb, id='y-c', pay=6.89, minutes=9.0, acceptedAt=_xnow - 30000, of=_yof)
_yp, _yb2, _yj, _yh = _cserver('addonboot', hold={'v': 2, 'orders': [_ya, _yb, _yc]},
                               CARRY_TWO='0')
try:
    eq('[add-on] a trip of three restored at boot comes back whole, carrying two off',
       [o.get('pay') for o in _orders(_yb2)], [25.03, 9.5, 6.89])
finally:
    stop(_yp)
# <<< add-on

# With the flag off: Stage 4, exactly — and the `would` it logs.
_op, _ob, _oj, _oh = _cserver('off', CARRY_TWO='0')
try:
    _took2(_ob, _A)
    _took2(_ob, _B)
    _st = get(_ob, '/api/status')
    eq('carryTwo off: a second Took replaces, as before',
       ((_st.get('holding') or {}).get('pay'), 'orders' in _st,
        [(r.get('id'), r.get('by')) for r in _rows(_oj, 'drop')]),
       (28.08, False, [('c-a', 'replaced')]))
    # ⌖ over the navigation of the order the Took put down: filed onto the
    # one in the car, as Stage 4 files it — and the row says attribution
    # would have given it to the other.
    _say(_nav(_BNAV[0], _BNAV[1], _BNAV[2], expected=(_NOWMIN + 40) % 1440))
    _m = [r for r in _rows(_oj, 'mark') if r.get('dropoff') == _BNAV[0]]
    eq('[carry two] carryTwo off: the mark row is Stage 4\'s and says what attribution would have done',
       [(r.get('id'), r.get('cue'), (r.get('would') or {}).get('cue')) for r in _m],
       [('c-b', None, 'deadline')])
    ok_('[carry two] ...naming the order put down, not the one in the car',
        _m and str((_m[0].get('would') or {}).get('held') or '').startswith('c-a@'))
finally:
    stop(_op)

# ...and with the flag off and TWO in the car — a holding.json written while
# it was on, read back at boot (MAX_HELD_FILE) — Stage 6 changes nothing:
# the pair is weighed against the first-taken alone and the line says so
# ("vs ① only", vsFirst), and the pair row is the one-order row, no heldAlso,
# no heldCount, no `over`.
_fnow = int(time.time() * 1000)
_fhold = {'v': 2, 'orders': [
    {'id': 'f-a', 'acceptedAt': _fnow - 60000, 'pay': 9.48, 'minutes': 40.0, 'miles': 5.0,
     'cost': 1.5, 'dropoff': None},
    {'id': 'f-b', 'acceptedAt': _fnow - 30000, 'pay': 28.08, 'minutes': 55.0, 'miles': 9.0,
     'cost': 1.5, 'dropoff': None}]}
_fp, _fb, _fj, _fh = _cserver('offtwo', hold=_fhold, CARRY_TWO='0')
try:
    _say(_card('f-p', 14.0, minutes=25.0, miles=4.0))
    _say({'ready': True, 'state': 'go', 'perHour': 30.0, 'grossPerHour': 33.6,
          'pay': 14.0, 'minutes': 25.0, 'billedMinutes': 25.0, 'cardMinutes': 25.0,
          'miles': 4.0, 'cost': 1.4, 'target': 25, 'band': 15, 'costPerMile': 0.35})
    _fs = (get(_fb, '/api/status').get('last') or {}).get('stack') or {}
    _fr = ([r for r in _rows(_fj, 'pair') if r.get('id') == 'f-p'] or [{}])[0]
    _frs = _fr.get('stack') or {}
    eq('carryTwo off: every output unchanged',
       (_fs.get('vsFirst'), sorted(k for k in ('heldCount', 'leftEach') if k in _fs),
        round((_fs.get('maxMinutes') or 0) - (_fs.get('leftMinutes') or 0), 1),
        (_fr.get('held') or {}).get('pay'),
        sorted(k for k in ('heldAlso', 'heldCount') if k in _fr), 'over' in _frs,
        round((_frs.get('maxMinutes') or 0) - (_frs.get('leftMinutes') or 0), 1)),
       (True, [], 25.0, 9.48, [], False, 25.0))
finally:
    stop(_fp)

# A cue that fits BOTH orders is a tie, and the map may break it — only it:
# the address searched on the NucBox inside each card's disc and found at
# door level inside exactly one. Both cards here print the same "Deliver by"
# and the navigation screen that time: a tie. The first card came up at
# Marietta Square, 5 mi; the second at Cumberland, 1 mi — and the fake
# NucBox's 1985 Cobb Parkway door is 3.4 mi from the Square.
_tfake = subprocess.Popen(['node', os.path.join(ROOT, 'tests', 'fake-nucbox.js')],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
_tfake_base = 'http://127.0.0.1:%d' % json.loads(_tfake.stdout.readline())['port']
_tp, _tb, _tj, _th = _cserver('tie', CARRY_TWO='1', NUCBOX_SEARCH=_tfake_base,
                              NUCBOX_TIMEOUT_MS='800', CHOOSER_MS='8000')
try:
    _SQFIX = {'lat': 33.9526, 'lon': -84.5499, 'gpsOk': True, 'gpsErr': 10.0, 'gpsMode': 3,
              'gpsAge': 0.5, 'hasTotal': True, 'whole': True}
    _CUFIX = dict(_SQFIX, lat=33.9010, lon=-84.4770)
    _due = (_NOWMIN + 50) % 1440
    _took2(_tb, _card('t-a', 15.0, minutes=40.0, miles=5.0, deliver_by=_due, **_SQFIX))
    _took2(_tb, _card('t-b', 11.0, minutes=40.0, miles=1.0, deliver_by=_due, **_CUFIX))
    _say(_nav('1985 Cobb Parkway, Kennesaw, GA 30144', '1985 Cobb Parkway', 'Kennesaw',
              expected=_due))
    _tie = {}
    for _ in range(80):
        _tie = get(_tb, '/api/status')
        if not _tie.get('chooser'):
            break
        time.sleep(0.05)
    eq('[carry two] a tie is broken only by the card whose reach holds the door, under the '
       'cue that tied',
       (_tie.get('chooser'), [o.get('dropoff') for o in _tie.get('orders') or []],
        [(r.get('id'), r.get('cue')) for r in _rows(_tj, 'mark')
         if r.get('dropoff') == '1985 Cobb Parkway, Kennesaw, GA 30144']),
       (None, ['1985 Cobb Parkway, Kennesaw, GA 30144', None], [('t-a', 'deadline')]))
finally:
    stop(_tp)
    _tfake.kill()

# --- one order in the car and a card being screened: whose is a ⌖ press? ----
#
# AUDITS.md's Open entry on the ⌖ button while an order is in the car. Measured
# at b337a44 against this server, one order held with its end on record and a
# different card on the slot, carrying two off and on alike: a press went onto
# the HELD order and replaced its end, whatever the phone showed — and over the
# card's own customer popup, whose line had already filed that address on the
# card, one address became both jobs' end; and the whole-screen read a
# customer's popup asks for made it the held order's end unpressed as well.
# Now a press there is the card's on its own place popup, the order's on its
# navigation or Trip Planner read since its Took, and otherwise nobody's until
# the driver picks from the chooser (Assemble.pressBetween), carrying two off
# as well as on; and a place popup is never an order's end. The same run on a
# server each way, held to one set of answers. Invented stores, streets, doors.
_SN_END = '9 Heron Ct, Smyrna, GA 30080'
_SH_CARD = 'Pine St & Elm St, Roswell'
_SC_END = '412 Wrenfield Ct NE, Marietta, GA 30062'
_SP_END = '15 Alder Ct, Roswell'
_SX, _SY = '61 Saddlebrook Ln, Acworth, GA 30101', '8 Gallant Rise Ct, Acworth, GA 30101'
_SZ = ('310 Mill St, Roswell, GA 30075', '88 Quill Ln NE, Marietta, GA 30062',
       '4821 Kestrel Dr, Marietta, GA 30060')


def _sline(line, screen, app='doordash', at=None):
    """A press's dropoff line, as emit_dropoff sends it (screen_said's type)."""
    return {'dropoff': {'found': True, 'line': line, 'street': line.split(',')[0],
                        'city': line.split(', ')[1], 'state': 'GA', 'zip': None,
                        'asked': True, 'labelled': None, 'ms': 10, 'app': app,
                        'screen': screen, 'expectedBy': None,
                        'at': int(time.time() * 1000) if at is None else at}}


def _sstop(kind, line, name=None, due=None):
    return {'kind': kind, 'orders': 1, 'name': name, 'place': None, 'expectedBy': due,
            'street': line.split(',')[0], 'city': line.split(', ')[1], 'state': 'GA',
            'zip': None, 'line': line, 'partial': None, 'label': kind}


def _ssight(asked, screen, app, stops, ends=(None, None), titled=False):
    """A whole-screen read's sighting, as rpi/scan_pi.py's sighting() sends it."""
    return {'sighting': {'at': int(time.time() * 1000), 'asked': asked, 'whole': True,
                         'titled': titled, 'app': app, 'screen': screen,
                         'page': {'top': ends[0], 'bottom': ends[1]}, 'stops': stops,
                         'orderCount': None, 'keep': False}}


def _spop(line):
    return {'popup': {'role': 'dropoff', 'name': None, 'line': line,
                      'street': line.split(',')[0], 'city': line.split(', ')[1],
                      'state': 'GA', 'zip': line[-5:], 'app': 'doordash',
                      'screen': 'dd.placePopup', 'at': int(time.time() * 1000)}}


def _screened(carry):
    """The run, on a server with carrying two `carry` ('1' or '0'): what each
    step left, by step."""
    sp, sb, sj, _sh = _cserver('screened-' + carry, CARRY_TWO=carry, CHOOSER_MS='1500')
    out = {}

    def marks(line):
        return [(r.get('id'), r.get('asked'), r.get('cue') or r.get('from'))
                for r in _rows(sj, 'mark') if r.get('dropoff') == line]

    def ends():
        st = get(sb, '/api/status')
        o = st.get('offer') or {}
        return ((st.get('holding') or {}).get('dropoff'),
                (o.get('id'), o.get('dropoff'), o.get('dropoffFrom')))

    try:
        # Nothing held: a DoorDash card, ⌖ over its customer's address.
        _say(_card('n-1', 7.75, app='doordash', screen='dd.offer', pickup='Lark Owl Pizza'))
        heard = listen(sb, 2.0)
        _say(_sline(_SN_END, 'unknown'))
        time.sleep(0.3)
        st = get(sb, '/api/status')
        o = st.get('offer') or {}
        out['none'] = (o.get('dropoff'), o.get('dropoffScanned'), o.get('dropoffFrom'),
                       st.get('chooser'), marks(_SN_END),
                       [sorted(m) for m in heard if (m.get('dropoff') or {}).get('line') == _SN_END])
        # One order in the car, its end the one its card printed.
        _took2(sb, _card('h-1', 9.48, minutes=40.0, pickup='Larkspur Tacos', dropoff=_SH_CARD))
        tookAt = int(time.time() * 1000)
        # Another card being screened, and its customer's popup tapped open
        # with no press: the popup's line and the whole-screen read it asks
        # for (auto_read_for 'label'), typed a dropoff.
        _say(_card('s-1', 12.5, minutes=25.0, miles=3.0, app='doordash', screen='dd.offer',
                   pickup='Lark Owl Pizza'))
        _say(_spop(_SC_END),
             _ssight(False, 'dd.placePopup', 'doordash', [_sstop('dropoff', _SC_END)]))
        out['unpressed'] = (ends(), marks(_SC_END))
        # ⌖ over that popup: the press's sighting and its dropoff line.
        _say(_ssight(True, 'dd.placePopup', 'doordash', [_sstop('dropoff', _SC_END)]),
             _sline(_SC_END, 'dd.placePopup'))
        out['popup'] = (ends(), marks(_SC_END), get(sb, '/api/status').get('chooser'))
        # ⌖ over the held order's Trip Planner: its store and its one dropoff,
        # the list seen whole.
        _say(_ssight(True, 'uber.planner', 'uber',
                     [_sstop('pickup', '310 Mill St, Roswell', 'Larkspur Tacos', 1180),
                      _sstop('dropoff', _SP_END, 'Lee M.', 1202)], (True, True), True))
        out['planner'] = (ends(), marks(_SP_END), get(sb, '/api/status').get('chooser'))
        # ⌖ over a screen that says nothing of whose — DoorDash's own delivery
        # screen types 'unknown' — left alone, and answered late.
        _say(_sline(_SX, 'unknown'))
        ch = get(sb, '/api/status').get('chooser') or {}
        time.sleep(1.8)
        late = post(sb, '/api/choose', {'id': ch.get('id'), 'pick': 'card'})
        out['nocue'] = ([(r.get('n'), r.get('pay')) for r in ch.get('rows') or []],
                        ch.get('card'), ch.get('line'), get(sb, '/api/status').get('chooser'),
                        late[0], ends(), marks(_SX))
        # ...and again, "this card" picked in time.
        _say(_sline(_SY, 'unknown'))
        ch = get(sb, '/api/status').get('chooser') or {}
        heard = listen(sb, 1.5)
        time.sleep(0.2)
        picked = post(sb, '/api/choose', {'id': ch.get('id'), 'pick': 'card'})
        time.sleep(0.5)
        out['card'] = (picked[0], ends(), marks(_SY),
                       [((m.get('offer') or {}).get('id'), (m.get('offer') or {}).get('dropoffFrom'))
                        for m in heard if (m.get('dropoff') or {}).get('line') == _SY])
        # Three presses that file nothing: a store's navigation, which since
        # 17 Oct opens no chooser at all — it is nobody's dropoff, the card's
        # no more than the order's (Assemble.dropoff, rule 5) — and two no cue
        # decides, a place popup the card was never given and the order's
        # navigation read before its Took: left alone, Neither.
        seq = []
        for line, screen, app, at, pick in ((_SZ[0], 'uber.pickupNav', 'uber', None, 'neither'),
                                            (_SZ[1], 'dd.placePopup', 'doordash', None, None),
                                            (_SZ[2], 'uber.nav', 'uber', tookAt - 5000,
                                             'neither')):
            _say(_sline(line, screen, app, at))
            ch = get(sb, '/api/status').get('chooser') or {}
            if pick:
                post(sb, '/api/choose', {'id': ch.get('id'), 'pick': pick})
            else:
                time.sleep(1.8)
            time.sleep(0.3)
            seq.append((bool(ch.get('id')), ends()[0], marks(line)))
        # ...and every end the held order was ever given, with how.
        out['never'] = (seq, [(r.get('dropoff'), r.get('asked'), r.get('cue'))
                              for r in _rows(sj, 'mark')
                              if r.get('id') == 'h-1' and r.get('dropoff')])
    finally:
        stop(sp)
    return out


_SCR_WANT = {
    'none': (_SN_END, True, 'press', None, [('n-1', True, None)],
             [['at', 'dropoff']]),
    'unpressed': ((_SH_CARD, ('s-1', _SC_END, 'popup')), [('s-1', False, 'popup')]),
    'popup': ((_SH_CARD, ('s-1', _SC_END, 'press')),
              [('s-1', False, 'popup'), ('s-1', True, 'popup')], None),
    'planner': ((_SP_END, ('s-1', _SC_END, 'press')), [('h-1', True, 'planner')], None),
    'nocue': ([(1, 9.48)], {'pick': 'card', 'pay': 12.5}, _SX, None, 409,
              (_SP_END, ('s-1', _SC_END, 'press')), []),
    'card': (200, (_SP_END, ('s-1', _SY, 'chooser')), [('s-1', True, 'chooser')],
             [('s-1', 'chooser')]),
    'never': ([(False, _SP_END, []), (True, _SP_END, []), (True, _SP_END, [])],
              [(_SP_END, True, 'planner')]),
}
_scr = _screened('1')
eq('one held, a card screened: the card\'s own popup read unpressed files onto the card and '
   'never the held order', _scr.get('unpressed'), _SCR_WANT['unpressed'])
eq('one held, a card screened: ⌖ over the card\'s own popup files onto the card',
   _scr.get('popup'), _SCR_WANT['popup'])
eq('...⌖ over the held order\'s planner files onto the held order',
   _scr.get('planner'), _SCR_WANT['planner'])
eq('...no cue opens the chooser and files nothing untouched',
   _scr.get('nocue'), _SCR_WANT['nocue'])
eq('...picking "this card" gives the card its end and leaves the held order\'s',
   _scr.get('card'), _SCR_WANT['card'])
eq('...a press never replaces the held end without a cue or a pick',
   _scr.get('never'), _SCR_WANT['never'])
eq('nothing held: ⌖ behaves exactly as before', _scr.get('none'), _SCR_WANT['none'])
eq('carryTwo off: the same', _screened('0'), _SCR_WANT)

# ...and with TWO orders in the car (carrying two on), ① an Uber order and ②
# a DoorDash order with its end on record, and a DoorDash card screened.
# Measured at 657bc18: ⌖ over that card's customer popup was filed onto ② by
# `only` — the app ruled ① out and nothing considered the card — replacing
# ②'s end while the popup's own line gave the card the same address. Now the
# card's own popup is the card's, as with one order, and with no cue the hard
# rules choose no order on their own while the card could own the press: the
# chooser asks ①, ②, This card or Neither.
_S2_END = '77 Birch Ln, Roswell, GA 30075'
_tp2, _tb2, _tj2, _th2 = _cserver('two-screened', CARRY_TWO='1', CHOOSER_MS='1500')
try:
    def _t2marks(line):
        return [(r.get('id'), r.get('asked'), r.get('cue') or r.get('from'))
                for r in _rows(_tj2, 'mark') if r.get('dropoff') == line]

    _took2(_tb2, _card('t-u', 9.48, minutes=40.0, pickup='Larkspur Tacos', dropoff=_SH_CARD))
    _took2(_tb2, _card('t-d', 11.0, minutes=35.0, app='doordash', screen='dd.offer',
                       pickup='Wren Street Noodles', dropoff=_S2_END))
    _say(_card('t-s', 12.5, minutes=25.0, miles=3.0, app='doordash', screen='dd.offer',
               pickup='Lark Owl Pizza'))
    _say(_spop(_SC_END))
    _say(_ssight(True, 'dd.placePopup', 'doordash', [_sstop('dropoff', _SC_END)]),
         _sline(_SC_END, 'dd.placePopup'))
    _st2 = get(_tb2, '/api/status')
    eq('two held, a card screened: ⌖ over the card\'s own popup files onto the card, never ②',
       ([o.get('dropoff') for o in _st2.get('orders') or []],
        ((_st2.get('offer') or {}).get('id'), (_st2.get('offer') or {}).get('dropoff'),
         (_st2.get('offer') or {}).get('dropoffFrom')),
        _t2marks(_SC_END), _st2.get('chooser')),
       ([_SH_CARD, _S2_END], ('t-s', _SC_END, 'press'),
        [('t-s', False, 'popup'), ('t-s', True, 'popup')], None))
    # ...and a press no cue decides, of DoorDash's app: ② is the one order the
    # app leaves, which is no reason while the card could be the press's.
    _say(_sline(_SX, 'unknown'))
    _ch2 = get(_tb2, '/api/status').get('chooser') or {}
    post(_tb2, '/api/choose', {'id': _ch2.get('id'), 'pick': 'neither'})
    time.sleep(0.3)
    eq('...and with no cue the chooser asks ①, ②, This card or Neither, and `only` files nothing',
       ([r.get('n') for r in _ch2.get('rows') or []], _ch2.get('card'),
        [o.get('dropoff') for o in _orders(_tb2)], _t2marks(_SX)),
       ([1, 2], {'pick': 'card', 'pay': 12.5}, [_SH_CARD, _S2_END], []))
finally:
    stop(_tp2)

# --- ⌖ at the restaurant: the store's screen is not where the order goes ------
#
# The 17 Oct fault, through the real server, every name and street invented: an
# Uber order held, its Trip Planner read unprompted and its door filed
# (`from: 'planner'`), then ⌖ pressed at the restaurant over Uber's navigation
# to the store (uber.pickupNav), whose read gave the town line alone. The press
# replaced the door, the panel turned ⌖ green, "Dropoff read as <Town>", and
# Map view ran the order to the town's centre. Now the press is refused
# (Assemble.dropoff, rule 5): the hold keeps its door, nothing is written, and
# the stream says why and what was kept in place of what was read.
_PK_DOOR = '283 Quillon St NW, Smyrna'
_PK_TOWN = 'Smyrna, GA 30066'
_PK_STORE = '1150 Larch Pkwy, Smyrna'


def _pkpress(line, screen, street=None):
    return {'dropoff': {'found': True, 'line': line, 'street': street, 'city': 'Smyrna',
                        'state': 'GA', 'zip': '30066', 'asked': True, 'labelled': None,
                        'ms': 10, 'app': 'uber', 'screen': screen, 'expectedBy': None,
                        'at': int(time.time() * 1000)}}


def _pickupnav(carry):
    pp, pb, pj, _ph = _cserver('pickupnav-' + carry, CARRY_TWO=carry, CHOOSER_MS='1500')
    out = {}

    def held():
        h = get(pb, '/api/status').get('holding') or {}
        return (h.get('dropoff'), ((h.get('fields') or {}).get('dropoff') or {}).get('from'))

    def marks(line):
        return [(r.get('id'), r.get('asked')) for r in _rows(pj, 'mark')
                if r.get('dropoff') == line]

    def told(heard, line):
        return ([(m['dropoff'].get('refused'), m['dropoff'].get('kept'), m['dropoff'].get('line'))
                 for m in heard if (m.get('dropoff') or {}).get('refused')],
                [m for m in heard if (m.get('dropoff') or {}).get('line') == line])

    try:
        # Nothing held, a card being screened, and ⌖ over Uber's navigation
        # to a store (an order the rig was never told of): until 17 Oct the
        # store's town was filed as the CARD's end. A store's screen is
        # nobody's dropoff, so it is refused here too, and said so.
        _say(_card('pk-0', 6.0, minutes=20.0, miles=2.0, dropoff='Customer dropoff'))
        heard = listen(pb, 2.0)
        time.sleep(0.2)
        _say(_pkpress(_PK_TOWN, 'uber.pickupNav'))
        time.sleep(0.4)
        st = get(pb, '/api/status')
        out['nothing'] = ((st.get('offer') or {}).get('dropoff'),
                          (st.get('offer') or {}).get('dropoffScanned'), st.get('chooser'),
                          marks(_PK_TOWN), told(heard, _PK_TOWN))
        _took2(pb, _card('pk-1', 11.09, minutes=35.0, pickup='Fable Grill', dropoff=None))
        _say(_ssight(False, 'uber.planner', 'uber',
                     [_sstop('pickup', _PK_STORE, 'Fable Grill', 1180),
                      _sstop('dropoff', _PK_DOOR, 'Lee M.', 1202)], (True, True), True))
        out['planner'] = held()
        heard = listen(pb, 2.0)
        time.sleep(0.2)
        _say(_pkpress(_PK_TOWN, 'uber.pickupNav'))
        time.sleep(0.4)
        out['store'] = (held(), marks(_PK_TOWN), told(heard, _PK_TOWN))
        # ...the same over another screen, reading the store's own door.
        _say(_pkpress(_PK_STORE + ', GA 30080', 'uber.nav', '1150 Larch Pkwy'))
        out['door'] = (held(), marks(_PK_STORE + ', GA 30080'))
        # ...and with a card being screened: the store's navigation pressed
        # opened the chooser until 17 Oct, and its "This card" row filed the
        # store's town onto the CARD. Now no chooser opens; the press is
        # refused at once, for the order and the card alike, and said so.
        _say(_card('pk-s', 7.5, minutes=20.0, miles=3.0))
        heard = listen(pb, 2.0)
        time.sleep(0.2)
        _say(_pkpress(_PK_TOWN, 'uber.pickupNav'))
        time.sleep(0.4)
        st = get(pb, '/api/status')
        out['chooser'] = (st.get('chooser'), (st.get('offer') or {}).get('dropoff'), held(),
                          marks(_PK_TOWN), told(heard, _PK_TOWN)[0])
        # The premise: an ordinary press over the customer's navigation still
        # replaces the planner's door.
        _say(_pkpress('61 Saddlebrook Ln, Smyrna, GA 30080', 'uber.nav', '61 Saddlebrook Ln'))
        out['ordinary'] = (held(), marks('61 Saddlebrook Ln, Smyrna, GA 30080'))
    finally:
        stop(pp)
    return out


_PKW = {
    'nothing': ('Customer dropoff', None, None, [], ([('a pickup screen', None, None)], [])),
    'planner': (_PK_DOOR, 'planner'),
    'store': ((_PK_DOOR, 'planner'), [],
              ([('a pickup screen', _PK_DOOR, None)], [])),
    'door': ((_PK_DOOR, 'planner'), []),
    'chooser': (None, None, (_PK_DOOR, 'planner'), [], [('a pickup screen', _PK_DOOR, None)]),
    'ordinary': (('61 Saddlebrook Ln, Smyrna, GA 30080', 'press'),
                 [('pk-1', True)]),
}
_pkr = _pickupnav('0')
eq('nothing held: ⌖ over Uber\'s navigation to a store is refused for the card being '
   'screened, which keeps its end, and the panel is told why, never the town',
   _pkr.get('nothing'), _PKW['nothing'])
eq('the premise: the planner filed the held order\'s door', _pkr.get('planner'), _PKW['planner'])
eq('⌖ over Uber\'s navigation to the store leaves the held order\'s planner end on '
   '/api/status, writes no mark, and tells the panel why and what was kept, never the town',
   _pkr.get('store'), _PKW['store'])
eq('...a press that reads the held order\'s pickup door is refused the same way',
   _pkr.get('door'), _PKW['door'])
eq('...and with another card on the slot no chooser opens for that press: it is refused at '
   'once for the card as for the order, and the panel told why',
   _pkr.get('chooser'), _PKW['chooser'])
eq('...while an ordinary press still replaces the planner\'s end', _pkr.get('ordinary'),
   _PKW['ordinary'])
eq('[carry two] ⌖ at the restaurant with one order in the car: the same',
   _pickupnav('1'), _PKW)

# --- the same store as an order in the car ------------------------------------
#
# The owner's decision of 18 Oct 2026, on the 17 Oct shape (invented): an Uber
# order held from "<Store> (113 <Street> NW)", and a DoorDash card whose stops
# line prints the same door with the quadrant NE. The pair row names the held
# order by its holdId (`sameStore`, ids only), the reading's stack carries it
# for the panel with its number on the line (`sameStoreN`), and nothing else
# on either moves: the row's arithmetic, its `said`, the reading's verdict.
# A card at another door says nothing; a reading of another card says nothing
# under the card on record; with two in the car the second is named ②.
def _ssread(pay, miles, state='go'):
    return {'ready': True, 'state': state, 'perHour': 30.0, 'grossPerHour': 33.6,
            'pay': pay, 'minutes': 25.0, 'billedMinutes': 25.0, 'cardMinutes': 25.0,
            'miles': miles, 'cost': 1.4, 'target': 25, 'band': 15, 'costPerMile': 0.35}


def _samestore():
    sp, sb, sj, _sh = _cserver('samestore', CARRY_TWO='1')
    out = {}
    try:
        _took2(sb, _card('ss-a', 9.48, minutes=40.0, pickup='Larkspur Tacos (113 Quillon St NW)'))
        ida = (_orders(sb)[0] or {}).get('holdId')
        out['ida'] = bool(ida)
        # A reading first, so each card's pair row is judged against the same
        # target (recordPairing takes it off the reading before the card).
        _say(_ssread(12.05, 8.4))
        _say(_card('ss-d', 12.05, minutes=25.0, miles=8.4, app='doordash', screen='dd.offer',
                   pickup='Larkspur Tacos', pickupLine='113 Quillon St NE, Marietta, 30060 GA'))
        _say(_ssread(12.05, 8.4))
        st = (get(sb, '/api/status').get('last') or {})
        out['same'] = ([r.get('sameStore') == ida for r in _rows(sj, 'pair') if r.get('id') == 'ss-d'],
                       (st.get('stack') or {}).get('sameStore') == ida,
                       (st.get('stack') or {}).get('sameStoreN'), st.get('state'))
        # ...a reading of ANOTHER card, before its offer line: nothing said
        # under the card on record.
        _say(_ssread(6.10, 3.1))
        out['other reading'] = 'sameStore' in ((get(sb, '/api/status').get('last') or {})
                                                .get('stack') or {})
        # ...the same figures at another door: no note, and the row the same
        # but for it.
        _say(_card('ss-x', 12.05, minutes=25.0, miles=8.4, app='doordash', screen='dd.offer',
                   pickup='Larkspur Tacos', pickupLine='940 Wren Ave, Smyrna, 30080 GA'))
        _say(_ssread(12.05, 8.4))
        st = (get(sb, '/api/status').get('last') or {})
        rd = [r for r in _rows(sj, 'pair') if r.get('id') == 'ss-d'][0]
        rx = [r for r in _rows(sj, 'pair') if r.get('id') == 'ss-x'][0]
        out['other door'] = ('sameStore' in rx, 'sameStore' in (st.get('stack') or {}),
                             sorted(set(rd) - set(rx)), rd.get('said'), rx.get('said'),
                             (rd.get('stack') or {}).get('state') == (rx.get('stack') or {}).get('state'),
                             (rd.get('stack') or {}).get('worst') == (rx.get('stack') or {}).get('worst'))
        # ...and with two in the car, the second's store: named ②.
        _took2(sb, _card('ss-b', 28.08, minutes=55.0, app='doordash', screen='dd.offer',
                         pickup='Wren Street Noodles', pickupLine='7 Wren Ave, Smyrna, 30080 GA'))
        idb = (_orders(sb)[1] if len(_orders(sb)) > 1 else {}).get('holdId')
        _say(_card('ss-e', 14.0, minutes=25.0, miles=4.0, pickup='Wren Street Noodles (7 Wren Avenue SW)'))
        _say(_ssread(14.0, 4.0))
        st = (get(sb, '/api/status').get('last') or {})
        out['second'] = ([r.get('sameStore') == idb for r in _rows(sj, 'pair') if r.get('id') == 'ss-e'],
                         (st.get('stack') or {}).get('sameStore') == idb,
                         (st.get('stack') or {}).get('sameStoreN'))
    finally:
        stop(sp)
    return out


_ssr = _samestore()
ok_('same store: the order in the car has a holdId to be named by', _ssr.get('ida'))
eq('same store: a DoorDash card at the held Uber order\'s door, quadrant NE for NW, names that '
   'order on its pair row and on the reading\'s stack, ①, and the verdict is the reading\'s own',
   _ssr.get('same'), ([True], True, 1, 'go'))
eq('...a reading of another card says nothing under the card on record',
   _ssr.get('other reading'), False)
eq('...a card at another door says nothing, and its pair row differs from the same-store one '
   'by that field alone: the same said, the same arithmetic',
   _ssr.get('other door'), (False, False, ['sameStore'], 'go', 'go', True, True))
eq('...and with two in the car the second order\'s store is named, ②',
   _ssr.get('second'), ([True], True, 2))

# --- DoorDash's map label as the offer's guessed end (the owner, 27 Oct) -------
#
# "reading the doordash icons still doesnt seem to work if a best guess can be
# used for the map": the rig reads the customer's street off DoorDash's map
# label (scan_pi.read_map_label) onto the offer line as `mapLabel`, and the
# server keeps it as the offer's `dropoffGuess` {line, from: 'dd map label'}
# for Map view to DRAW to — and for nothing else. The pair row, the reading's
# stack and its verdict are the same with it as without; a Took's hold ends
# where the screens after the accept say, never at the guess. Invented streets.
def _guesses():
    sp, sb, sj, _sh = _cserver('ddguess')
    out = {}
    try:
        _took2(sb, _card('gl-a', 9.48, minutes=40.0, pickup='Larkspur Tacos',
                         dropoff='12 Quillon St, Marietta, GA 30060'))
        _say(_ssread(12.35, 11.2))
        _say(_card('gl-d', 12.35, minutes=38.0, miles=11.2, app='doordash', screen='dd.offer',
                   pickup='Lark Owl Grill', stops=2, endRefused=True,
                   mapLabel='418 Fable Ave NE'))
        _say(_ssread(12.35, 11.2))
        st = get(sb, '/api/status')
        o = st.get('offer') or {}
        out['kept'] = (o.get('dropoffGuess'), o.get('dropoff'), 'mapLabel' in o)
        out['stack d'] = (st.get('last') or {}).get('stack')
        # ...the same card read again with no label: the guess stands.
        _say(_card('gl-d', 12.35, minutes=38.0, miles=11.2, app='doordash', screen='dd.offer',
                   pickup='Lark Owl Grill', stops=2, endRefused=True))
        out['again'] = ((get(sb, '/api/status').get('offer') or {}).get('dropoffGuess') or {}).get('line')
        # ...the same figures with no label at all: the pair row and the stack
        # as they were, but for the id.
        _say(_card('gl-x', 12.35, minutes=38.0, miles=11.2, app='doordash', screen='dd.offer',
                   pickup='Lark Owl Grill', stops=2, endRefused=True))
        _say(_ssread(12.35, 11.2))
        st = get(sb, '/api/status')
        out['none'] = (st.get('offer') or {}).get('dropoffGuess')
        rd = [r for r in _rows(sj, 'pair') if r.get('id') == 'gl-d'][0]
        rx = [r for r in _rows(sj, 'pair') if r.get('id') == 'gl-x'][0]
        # (`held` and `stack` move with the minutes the order in the car has
        # run between the two cards; the verdict and its worst do not.)
        out['pair'] = ((rd.get('stack') or {}).get('state') == (rx.get('stack') or {}).get('state'),
                       (rd.get('stack') or {}).get('worst') == (rx.get('stack') or {}).get('worst'),
                       rd.get('said') == rx.get('said'), bool(rd.get('said')),
                       '418 Fable' in json.dumps(rd))
        out['stack same'] = out['stack d'] == (st.get('last') or {}).get('stack')
        # ...an Uber card, or a DoorDash card that named its own dropoff: none.
        _say(_card('gl-u', 12.35, app='uber', mapLabel='418 Fable Ave NE'))
        out['uber'] = (get(sb, '/api/status').get('offer') or {}).get('dropoffGuess')
        _say(_card('gl-o', 12.35, app='doordash', screen='dd.offer',
                   dropoff='7 Wren Ave, Smyrna, GA 30080', mapLabel='418 Fable Ave NE'))
        out['own end'] = (get(sb, '/api/status').get('offer') or {}).get('dropoffGuess')
        # ...and a Took on a guessed card: the hold has no end from it.
        _took2(sb, _card('gl-t', 12.35, minutes=38.0, miles=11.2, app='doordash',
                         screen='dd.offer', pickup='Lark Owl Grill', stops=2, endRefused=True,
                         mapLabel='418 Fable Ave NE'))
        held = [h for h in json.load(open(os.path.join(os.path.dirname(sj),
                                                       'holding.json')))['orders']
                if h.get('id') == 'gl-t']
        out['took'] = ([h.get('dropoff') for h in held], '418 Fable' in json.dumps(held))
    finally:
        stop(sp)
    return out


_gl = _guesses()
eq('dd map label: the offer keeps it as dropoffGuess, its dropoff still none, no mapLabel kept',
   _gl.get('kept'), ({'line': '418 Fable Ave NE', 'from': 'dd map label'}, None, False))
eq('...carried across a re-read of the same card', _gl.get('again'), '418 Fable Ave NE')
eq('...a card with no label has none', _gl.get('none'), None)
eq('...and with an order in the car the pair row says the same with it as without',
   _gl.get('pair'), (True, True, True, True, False))
ok_('...and so does the reading\'s stack (no figure moves)', _gl.get('stack same'))
eq('...an Uber card\'s label is not kept', _gl.get('uber'), None)
eq('...nor one on a DoorDash card that named its own dropoff', _gl.get('own end'), None)
eq('...and a Took on a guessed card holds no end from it',
   _gl.get('took'), ([None], False))

# --- whether each NucBox service is answering ----------------------------------
#
# The owner, 22 Oct: the map drew nothing for a held order and nothing said
# whether the NucBox was answering. server.js keeps each set service's state
# (nbxHealth): probed every NUCBOX_PROBE_MS on a path that costs the service
# nothing, and told by every real question, two failures in a row being down.
# Said in /api/status (`nucbox`) and on the beat (`nucboxDown`), which the
# panel's health row reads. Through tests/fake-nucbox.js, which answers the
# probes and does not count them, and a port nothing listens on.
def _nbxhealth(name, unloaded=False, **env):
    nf = subprocess.Popen(['node', os.path.join(ROOT, 'tests', 'fake-nucbox.js')],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                          env=dict(os.environ, FAKE_STREETS_UNLOADED='1' if unloaded else '0'))
    nb = 'http://127.0.0.1:%d' % json.loads(nf.stdout.readline())['port']
    dead = 'http://127.0.0.1:%d' % free_port()
    want = {'NUCBOX_SEARCH': nb, 'NUCBOX_ROUTER': nb, 'NUCBOX_STREETS': nb}
    want.update({k: (dead if v == 'dead' else v) for k, v in env.items()})
    sp, sb, _sj, _sh = _cserver(name, **want)
    return nf, nb, sp, sb


_hf, _hnb, _hp, _hb = _nbxhealth('nbx-health-up', NUCBOX_PROBE_MS='300')
try:
    time.sleep(1.8)
    _say({'alive': True})
    _hs = get(_hb, '/api/status')
    eq('[nucbox health] every service set and answering: each up, and the beat says none down',
       ({k: (v or {}).get('up') for k, v in (_hs.get('nucbox') or {}).items()},
        (_hs.get('beat') or {}).get('nucboxDown')),
       ({'search': True, 'route': True, 'streets': True}, []))
    eq('[nucbox health] ...and the probes are no question the fake counts',
       json.loads(urllib.request.urlopen(_hnb + '/__asked', timeout=5).read()), [])
finally:
    stop(_hp)
    _hf.kill()

_hf, _hnb, _hp, _hb = _nbxhealth('nbx-health-streets', NUCBOX_PROBE_MS='300',
                                  NUCBOX_STREETS='dead')
try:
    time.sleep(1.8)
    _say({'alive': True})
    _hs = get(_hb, '/api/status')
    _st = (_hs.get('nucbox') or {}).get('streets') or {}
    ok_('[nucbox health] the street index not answering: down, with why, the others up (got %r)'
        % (_hs.get('nucbox'),),
        _st.get('up') is False and 'did not answer' in (_st.get('why') or '')
        and (_hs['nucbox'].get('search') or {}).get('up') is True)
    eq('[nucbox health] ...and the beat names it for the panel',
       (_hs.get('beat') or {}).get('nucboxDown'), ['streets'])
finally:
    stop(_hp)
    _hf.kill()

# ...and a NucBox server up with no street index loaded is down for this.
_hf, _hnb, _hp, _hb = _nbxhealth('nbx-health-unloaded', unloaded=True, NUCBOX_PROBE_MS='300')
try:
    time.sleep(1.8)
    _st = (get(_hb, '/api/status').get('nucbox') or {}).get('streets') or {}
    ok_('[nucbox health] the street index server up with no index loaded: down, and says so '
        '(got %r)' % (_st,),
        _st.get('up') is False and 'no street index is loaded' in (_st.get('why') or ''))
finally:
    stop(_hp)
    _hf.kill()

# With no probe, the real questions say it: one failure is not down (a slow
# answer is the question's trouble), two in a row are.
_hf, _hnb, _hp, _hb = _nbxhealth('nbx-health-asked', NUCBOX_SEARCH='dead', NUCBOX_ROUTER='')
try:
    _nbx(_hb, '/api/nbx/search?q=Fable%20Grill')
    _one = ((get(_hb, '/api/status').get('nucbox') or {}).get('search') or {}).get('up')
    _nbx(_hb, '/api/nbx/search?q=Wren%20Diner')
    _two = ((get(_hb, '/api/status').get('nucbox') or {}).get('search') or {}).get('up')
    eq('[nucbox health] no probe: one failed search is not down, a second in a row is',
       (_one, _two), (None, False))
    eq('[nucbox health] ...and a service not set is null, not down',
       get(_hb, '/api/status')['nucbox'].get('route'), None)
finally:
    stop(_hp)
    _hf.kill()

# ...and THE CLOCK STEPPING under it (the owner, after 26 Oct: the Pi runs from
# the time saved at shutdown until NTP answers, then steps). Staged by a server
# whose Date.now runs an hour behind until a file appears, then right: the
# probes note each service up on the stale clock, the step comes, and its
# `since` must be on the clock the server now has, not an hour before it
# started. server.js nbxClockStep: the wall clock against the monotonic one.
_stepflag = os.path.join(_cdir, 'clock-stepped')
_stepjs = os.path.join(_cdir, 'clock-step.js')
with open(_stepjs, 'w') as _fh:
    _fh.write('var fs = require("fs"), real = Date.now, flag = %s, stepped = false, seen = 0;\n'
              'Date.now = function () {\n'
              '  var t = real();\n'
              '  if (!stepped && t - seen > 50) { seen = t; stepped = fs.existsSync(flag); }\n'
              '  return stepped ? t : t - 3600000;\n'
              '};\n' % json.dumps(_stepflag))
_hf, _hnb, _hp, _hb = _nbxhealth('nbx-health-step', NUCBOX_PROBE_MS='300',
                                  NODE_OPTIONS='--require ' + _stepjs)
try:
    time.sleep(1.5)
    _before = ((get(_hb, '/api/status').get('nucbox') or {}).get('search') or {}).get('since')
    open(_stepflag, 'w').close()
    time.sleep(1.5)
    _after = ((get(_hb, '/api/status').get('nucbox') or {}).get('search') or {}).get('since')
    _real = time.time() * 1000
    ok_('[nucbox health] the clock stepping an hour forward moves `since` with it, onto the '
        'clock the server now has (stale %r, after %r, now %r)' % (_before, _after, _real),
        isinstance(_before, (int, float)) and _before < _real - 3000000
        and isinstance(_after, (int, float)) and _real - 120000 < _after <= _real)
finally:
    stop(_hp)
    _hf.kill()
    if os.path.exists(_stepflag):
        os.remove(_stepflag)

# --- on time for both ----------------------------------------------------------
#
# The owner's decision of 20 Oct 2026: with one order in the car and every
# point pinned, the NucBox router's drive times (tests/fake-nucbox.js, a road
# a quarter longer than the line at 13.4 m/s) say whether some order of the
# stops reaches both drops by their deadlines — on the reading's stack and on
# the pair row (`onTime`, numbers only), the verdict untouched. No deadline:
# the road miles the new pickup adds, never via the new job's end. A held end
# with no pin: nothing. Invented doors round Marietta Square, the fake's own.
_OTFIX = {'lat': 33.9526, 'lon': -84.5499, 'gpsOk': True, 'gpsMode': 3, 'gpsAge': 1,
          'gpsErr': 5, 'miles': 6.0}
_OTEND = '1106 Brindlewood Way, Marietta, GA 30060'
# ...and an end the NucBox holds the street of and not the door, so the
# server's own search cannot pin it either.
_OTNODOOR = '4821 Kestrel Dr, Marietta, GA 30060'


def _othold(deliver_by, pinned=True, more=None):
    now = int(time.time() * 1000)
    h = {'id': 'ot-a', 'acceptedAt': now - 60000, 'pay': 9.48, 'minutes': 40.0, 'miles': 5.0,
         'cost': 1.5, 'dropoff': _OTEND if pinned else _OTNODOOR, 'deliverBy': deliver_by,
         'app': 'uber',
         'card': dict(_OTFIX)}
    if pinned:
        h['endPin'] = {'dropoff': _OTEND, 'lat': 33.9650, 'lon': -84.5400, 'doorLevel': True,
                       'pinnedAt': now, 'by': 'server'}
    h.update(more or {})
    return {'v': 2, 'orders': [h]}


def _ontime(name, deliver_by, pinned=True, minutes=30.0, more=None, planner=None, two=False,
            waits=None, planner_first=None):
    nf = subprocess.Popen(['node', os.path.join(ROOT, 'tests', 'fake-nucbox.js')],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    nb = 'http://127.0.0.1:%d' % json.loads(nf.stdout.readline())['port']
    hold = _othold(deliver_by, pinned, more)
    env = {}
    if two:
        # A second order in the car, carrying two on: no hint at all.
        hold['orders'].append(dict(hold['orders'][0], id='ot-c',
                                   acceptedAt=hold['orders'][0]['acceptedAt'] + 1000))
        env['CARRY_TWO'] = '1'
    sp, sb, sj, _sh = _cserver(name, hold=hold, waits=waits, NUCBOX_SEARCH=nb, NUCBOX_ROUTER=nb,
                               **env)
    try:
        read = _ssread(12.05, 6.0)
        _say(read)
        if planner_first is not None:
            # A Trip Planner read BEFORE the offer, as the scanner sends one:
            # its sighting (which the assembler files from), then its line.
            # The card that follows forgets the planner; what it filed stays.
            at = int(time.time() * 1000)
            _say({'sighting': {'at': at, 'asked': False, 'whole': True, 'titled': True,
                               'app': 'uber', 'screen': 'uber.planner',
                               'page': {'top': True, 'bottom': True}, 'stops': planner_first,
                               'orderCount': 1, 'keep': False}},
                 {'planner': {'stops': [{k: v for k, v in s.items()
                                         if k not in ('partial', 'label')}
                                        for s in planner_first],
                              'keep': False, 'asked': False, 'ms': None, 'at': at}})
        _say(_card('ot-b', 12.05, minutes=minutes,
                   pickup='Example Grill (250 Example Road)',
                   dropoff='1106 Tamarons Lane, Marietta, GA 30064', **_OTFIX))
        _say(read)
        time.sleep(1.0)
        _say(read)
        if planner is not None:
            # A Trip Planner read with the card still on record (a new card
            # forgets the planner, forgetPlanner), then the card read again.
            _say({'planner': {'stops': planner, 'unfiled': None, 'asked': False}})
            _say(read)
            time.sleep(1.0)
            _say(read)
        last = get(sb, '/api/status').get('last') or {}
        st = last.get('stack') or {}
        rows = [r for r in _rows(sj, 'pair') if r.get('id') == 'ot-b']
        row = rows[0] if rows else {}
        return {'stack': {k: st.get(k) for k in ('onTime', 'lateMin', 'offWayMi')},
                'storeWait': last.get('storeWait'),
                'row': {k: row.get(k) for k in ('onTime', 'lateMin', 'offWayMi')},
                'rows': len(rows), 'state': last.get('state'), 'said': row.get('said'),
                'rowkeys': sorted(k for k in ('onTime', 'lateMin', 'offWayMi') if k in row)}
    finally:
        stop(sp)
        nf.kill()


_otb = _ontime('ontime-both', (_NOWMIN + 40) % 1440)
eq('on time: both deadlines met by some order of the stops, by the router\'s drive times, '
   'on the reading\'s stack and on the one pair row; the verdict the reading\'s own',
   (_otb['stack'], _otb['row'], _otb['rows'], _otb['state'], _otb['rowkeys']),
   ({'onTime': 'both', 'lateMin': None, 'offWayMi': None},
    {'onTime': 'both', 'lateMin': None, 'offWayMi': None}, 1, 'go', ['onTime']))
_otl = _ontime('ontime-late', _NOWMIN)
ok_('on time: the held order due this minute is late in every order of the stops, said as '
    '①\'s whole minutes late on the stack and the row (got %r)' % (_otl,),
    _otl['stack']['onTime'] == 'late1' and _otl['row']['onTime'] == 'late1'
    and isinstance(_otl['row']['lateMin'], int) and 1 <= _otl['row']['lateMin'] <= 6
    and _otl['stack']['lateMin'] == _otl['row']['lateMin'] and _otl['state'] == 'go')
_otd = _ontime('ontime-nodue', None)
ok_('on time: with no deadline on the held order, the road miles the new pickup adds '
    'instead, no call made (got %r)' % (_otd,),
    _otd['stack']['onTime'] is None and _otd['row']['onTime'] is None
    and isinstance(_otd['stack']['offWayMi'], (int, float)) and _otd['stack']['offWayMi'] >= 0
    and _otd['row']['offWayMi'] == _otd['stack']['offWayMi'])
_otp = _ontime('ontime-nopin', (_NOWMIN + 40) % 1440, pinned=False)
eq('on time: the held end not pinned (its door not on the NucBox), nothing at all: no call, no miles, the row\'s onTime null',
   (_otp['stack'], _otp['row'], _otp['rowkeys']),
   ({'onTime': None, 'lateMin': None, 'offWayMi': None},
    {'onTime': None, 'lateMin': None, 'offWayMi': None}, ['onTime']))
# Mutation catch-up (21 Oct): the fake router's own legs (a road a quarter
# longer than the line at 13.4 m/s) with the food in the car: A-drop B-pick
# B-drop reaches ② at 13.65 min, B-pick A-drop B-drop at 14.2, B-pick B-drop
# A-drop at 13.55 — each with PICKUP_ALLOW_S (5 min) at ② 's pickup. An
# 11-minute offer is ② late in every order, least by 2.55 min: "~3".
_ot2 = _ontime('ontime-late2', (_NOWMIN + 40) % 1440, minutes=11.0)
eq('[on time] an offer due before any order of the stops reaches it, the 5 min at its pickup '
   'counted: ② late, the least late order\'s minutes rounded up',
   (_ot2['stack'], _ot2['row']),
   ({'onTime': 'late2', 'lateMin': 3, 'offWayMi': None},
    {'onTime': 'late2', 'lateMin': 3, 'offWayMi': None}))
# ...and the same offer with its store's waits on record (restaurant waits,
# store-waits.json beside the journal, at the fake's pin for 250 Example
# Road): a median of 60 s in place of the 5 min makes the least late order
# 2.55 - 4 min, on time for both; a median of 600 s, 2.55 + 5 = 7.55, "~8";
# one wait alone is no median, and the 5 min stands. The verdict the
# reading's own each time; the card says what is on record.


def _otwaits(*secs):
    return {'v': 1, 'stores': [{'key': 'examplegrill@67940,-169060', 'name': 'Example Grill',
                                'lat': 33.97, 'lon': -84.53,
                                'waits': [{'at': 1000 * i, 's': s} for i, s in enumerate(secs)]}]}


_otw1 = _ontime('ontime-wait-short', (_NOWMIN + 40) % 1440, minutes=11.0,
                waits=_otwaits(50, 60, 70))
eq('[store waits] the on-time hint allows the store\'s median wait at its pickup in place of '
   'PICKUP_ALLOW_S: 60 s, both on time; the verdict unmoved; the card says "3 visits, ~1 min"',
   (_otw1['stack'], _otw1['row'], _otw1['state'], _otw1['storeWait']),
   ({'onTime': 'both', 'lateMin': None, 'offWayMi': None},
    {'onTime': 'both', 'lateMin': None, 'offWayMi': None}, 'go', {'n': 3, 'avgMin': 1}))
_otw2 = _ontime('ontime-wait-long', (_NOWMIN + 40) % 1440, minutes=11.0,
                waits=_otwaits(600, 540, 660, 600))
eq('[store waits] ...a median of 10 min: ② late ~8 min',
   (_otw2['stack'], _otw2['state']), ({'onTime': 'late2', 'lateMin': 8, 'offWayMi': None}, 'go'))
_otw3 = _ontime('ontime-wait-one', (_NOWMIN + 40) % 1440, minutes=11.0, waits=_otwaits(60))
eq('[store waits] ...one wait on record: PICKUP_ALLOW_S, ② late ~3, and no note',
   (_otw3['stack'], _otw3['storeWait']),
   ({'onTime': 'late2', 'lateMin': 3, 'offWayMi': None}, None))
# The held order's Trip Planner "Expected by" for its own dropoff stop is its
# deadline over its card's: due this minute by the planner, ① late.
_otpl = _ontime('ontime-planner', (_NOWMIN + 40) % 1440, planner=[
    {'kind': 'dropoff', 'orders': 1, 'name': 'Pat Q.', 'line': _OTEND, 'expectedBy': _NOWMIN}])
eq('[on time] the planner\'s Expected by for the held order\'s stop is its deadline, over its '
   'card\'s: read with the card on record, the next reading says ① late',
   _otpl['stack']['onTime'], 'late1')
# ...and read before the offer came: the offer's card forgets the planner, the
# Expected by it filed on the hold with the end (fields.expectedBy) stands.
_otpf = _ontime('ontime-planner-first', (_NOWMIN + 40) % 1440, planner_first=[
    {'kind': 'dropoff', 'orders': 1, 'name': 'Pat Q.', 'place': None, 'expectedBy': _NOWMIN,
     'street': '1106 Brindlewood Way', 'city': 'Marietta', 'state': 'GA', 'zip': '30060',
     'line': _OTEND, 'partial': None, 'label': 'dropoff'}])
eq('[on time] the planner read before the offer, forgotten at its card: the Expected by it '
   'filed on the hold is still the deadline, ① late',
   _otpf['stack']['onTime'], 'late1')
# A pickup of the held order still ahead with no pin: no run to time, nothing.
_otnp = _ontime('ontime-pickup-unpinned', (_NOWMIN + 40) % 1440, more={
    'pickups': [{'q': '250 Example Road, Marietta', 'visited': False}]})
eq('[on time] a held pickup still ahead with no pin: nothing at all',
   _otnp['stack'], {'onTime': None, 'lateMin': None, 'offWayMi': None})
# ...and pinned, with no deadline: the miles the new pickup adds, the shorter
# of it before or after the held pickup (1.7 mi; the longer is 2.7).
_otpp = _ontime('ontime-pickup-pinned', None, more={
    'pickups': [{'q': '250 Example Road, Marietta', 'visited': False}],
    'pickupPins': [{'q': '250 Example Road, Marietta', 'lat': 33.9600, 'lon': -84.5450,
                    'by': 'server'}]})
eq('[on time] a held pickup ahead and pinned, no deadline: the new pickup either side of it, '
   'the shorter', _otpp['stack'], {'onTime': None, 'lateMin': None, 'offWayMi': 1.7})

_ot2o = _ontime('ontime-two', (_NOWMIN + 40) % 1440, two=True)
eq('[on time] two orders in the car: nothing at all',
   _ot2o['stack'], {'onTime': None, 'lateMin': None, 'offWayMi': None})
_otnt = _ontime('ontime-untimed', (_NOWMIN + 40) % 1440, minutes=None)
eq('[on time] an offer with no deadline and no minutes: no call, the miles instead',
   _otnt['stack'], {'onTime': None, 'lateMin': None, 'offWayMi': 1.6})

# --- put down by the delivery app's own screen --------------------------------
#
# The owner, 22 Oct: make it more hands-free. The app's screen from AFTER a
# delivery (offer_parser.delivered_screen, said once by the scanner) puts the
# order of that app down, `by: 'screen'`, behind `screenDrop` (SCREEN_DROP
# here): the only order of that app, or with two the one whose customer the
# screen names; with no cue the Drop chooser, and nothing with no order of that
# app in the car. Every name, store and street is invented.


def _done(app='doordash', name=None, pay=9.4, at=None):
    return {'delivered': {'app': app, 'screen': 'dd.delivered' if app == 'doordash'
                          else 'uber.delivered', 'pay': pay, 'name': name,
                          'at': int(time.time() * 1000) if at is None else at}}


def _sdrops(j):
    return [(r.get('id'), r.get('by')) for r in _rows(j, 'drop')]


def _sdone(j):
    return [(r.get('app'), r.get('would'), r.get('cue'), r.get('acted'))
            for r in _rows(j, 'delivered')]


def _heard(seen, pred, seconds=3.0):
    """What the stream has carried that `pred` takes, waiting for it a while:
    a message is sent the moment a line is handled, and read a moment later."""
    end = time.time() + seconds
    while time.time() < end and not any(pred(m) for m in list(seen)):
        time.sleep(0.05)
    return [m for m in list(seen) if pred(m)]


_DQ = 3.1   # past SCREEN_DROP_QUIET_MS below, so the next screen is a new one
_scp, _scb, _scj, _sch = _cserver('screen-one', SCREEN_DROP='1', CARRY_TWO='1',
                                  SCREEN_DROP_QUIET_MS='3000')
try:
    _say(_done())
    eq('[screen drop] a completion screen with no order in the car puts nothing down, and '
       'its row says so', (_sdrops(_scj), _sdone(_scj)),
       ([], [('doordash', 'nothing held', None, False)]))
    time.sleep(_DQ)
    _took2(_scb, _card('s-1', 9.40, app='doordash', screen='dd.offer'))
    _seen = listen(_scb, 4.0)
    _say(_done())
    _told = _heard(_seen, lambda m: 'screenDrop' in m)
    eq('[screen drop] DoorDash\'s screen with one DoorDash order in the car puts it down, '
       'by the screen', (_sdrops(_scj), _orders(_scb), _sdone(_scj)[-1]),
       ([('s-1', 'screen')], [], ('doordash', 'put down', 'only', True)))
    ok_('[screen drop] ...and the panel is told the car is empty',
        bool(_told) and all(m.get('holding') is None for m in _told))
    # The same screen, still up: the order taken since is not put down by it.
    _took2(_scb, _card('s-2', 7.25, app='doordash', screen='dd.offer'))
    _say(_done())
    eq('[screen drop] the same screen read again inside the quiet window puts down '
       'nothing, not even the order taken since, and writes no second row',
       ([o.get('pay') for o in _orders(_scb)], _sdrops(_scj), len(_sdone(_scj))),
       ([7.25], [('s-1', 'screen')], 2))
    time.sleep(_DQ)
    _say(_done(app='uber', pay=7.45))
    eq('[screen drop] Uber\'s screen with only a DoorDash order held puts nothing down',
       ([o.get('pay') for o in _orders(_scb)], _sdrops(_scj), _sdone(_scj)[-1]),
       ([7.25], [('s-1', 'screen')], ('uber', 'nothing held', None, False)))
    _s2took = _orders(_scb)[0]
    _say(_done(at=int(time.time() * 1000) - 600000))
    eq('[screen drop] a screen whose frame was taken before the order\'s Took is not '
       'that order\'s', ([o.get('pay') for o in _orders(_scb)], _sdone(_scj)[-1]),
       ([7.25], ('doordash', 'before the Took', None, False)))
    time.sleep(_DQ)
    _say(_done())
    eq('[screen drop] ...and the next one, after the quiet window, puts it down',
       (_orders(_scb), _sdrops(_scj)), ([], [('s-1', 'screen'), ('s-2', 'screen')]))
finally:
    stop(_scp)

# Two Uber orders: ①'s end filed with its customer's name (the hold's fields,
# as Assemble.file keeps it), ②'s customer only on the Trip Planner on record.
_SPAT = '4821 Kestrel Dr, Marietta, GA 30060'
_SLEE = '77 Birch Ln, Roswell, GA 30075'
_SSTOPS = [{'kind': 'pickup', 'orders': 1, 'name': 'Wren Street Noodles',
            'line': None, 'expectedBy': None},
           {'kind': 'dropoff', 'orders': 1, 'name': 'Lee R.', 'line': _SLEE,
            'street': '77 Birch Ln', 'city': 'Roswell', 'expectedBy': None}]
_snow = int(time.time() * 1000)
_sta = {'id': 't-a', 'acceptedAt': _snow - 10 * 60000, 'pay': 9.48, 'minutes': 40.0,
        'miles': 5.0, 'cost': 1.5, 'app': 'uber', 'dropoff': _SPAT,
        'fields': {'customer': {'value': 'Pat Q.', 'from': 'planner', 'conf': 1,
                                'at': _snow - 9 * 60000, 'screen': 'uber.planner'}}}
_stbh = {'id': 't-b', 'acceptedAt': _snow - 8 * 60000, 'pay': 28.08, 'minutes': 55.0,
         'miles': 9.0, 'cost': 2.5, 'app': 'uber', 'dropoff': _SLEE}
_stp, _stb, _stj, _sth = _cserver('screen-two', hold={'v': 2, 'orders': [_sta, _stbh]},
                                  SCREEN_DROP='1', CARRY_TWO='1',
                                  SCREEN_DROP_QUIET_MS='3000', CHOOSER_MS='1500')
try:
    _say({'planner': {'stops': _SSTOPS, 'unfiled': None, 'asked': False}})
    _say(_done(app='uber', name='Lee R.', pay=28.08))
    eq('[screen drop] two Uber orders in the car: the screen naming one\'s customer puts '
       'that one down and keeps the other',
       ([o.get('pay') for o in _orders(_stb)], _sdrops(_stj), _sdone(_stj)),
       ([9.48], [('t-b', 'screen')], [('uber', 'put down', 'name', True)]))
    time.sleep(_DQ)
    _took2(_stb, _card('t-c', 6.10))
    _seen = listen(_stb, 4.0)
    _say(_done(app='uber', pay=6.10))
    _chs = [m['chooser'] for m in _heard(_seen, lambda m: isinstance(m.get('chooser'), dict))]
    eq('[screen drop] two in the car and nothing on the screen to say whose: the Drop '
       'chooser over both, and nothing put down',
       ([c.get('kind') for c in _chs], [[r.get('n') for r in c.get('rows') or []] for c in _chs],
        [o.get('pay') for o in _orders(_stb)], _sdrops(_stj), _sdone(_stj)[-1]),
       (['drop'], [[1, 2]], [9.48, 6.10], [('t-b', 'screen')],
        ('uber', 'chooser', None, True)))
    # The driver's answer is Drop's own: ② by the chooser.
    _code, _ = post(_stb, '/api/delivered', {'holdIds': [_chs[0]['rows'][1]['pick']]}
                    if _chs else {'holdIds': []})
    eq('[screen drop] ...answered, it is Drop\'s chooser: that order down, by the chooser',
       ([o.get('pay') for o in _orders(_stb)], _sdrops(_stj)),
       ([9.48], [('t-b', 'screen'), ('t-c', 'chooser')]))
    time.sleep(_DQ)
    _say(_done(app='uber', name='Lee R.', pay=28.08))
    eq('[screen drop] one Uber order left, its customer known, and a screen naming '
       'another: nothing put down', ([o.get('pay') for o in _orders(_stb)],
                                     _sdone(_stj)[-1]),
       ([9.48], ('uber', 'another customer', None, False)))
    time.sleep(_DQ)
    _say(_done(app='uber', name='Pat Q.', pay=9.48))
    eq('[screen drop] ...and the screen naming its own customer puts it down',
       (_orders(_stb), _sdrops(_stj)[-1], _sdone(_stj)[-1]),
       ([], ('t-a', 'screen'), ('uber', 'put down', 'name', True)))
finally:
    stop(_stp)

# Off unless the setting says exactly true: the row, and nothing else.
_sop, _sob, _soj, _soh = _cserver('screen-off')
try:
    _took2(_sob, _card('o-1', 9.40, app='doordash', screen='dd.offer'))
    _say(_done())
    eq('[screen drop] off by default: the order stays in the car, and the row says what '
       'it would have done', ([o.get('pay') for o in _orders(_sob)]
                              or [(get(_sob, '/api/status').get('holding') or {}).get('pay')],
                              _sdrops(_soj), _sdone(_soj)),
       ([9.40], [], [('doordash', 'put down', 'only', False)]))
finally:
    stop(_sop)

shutil.rmtree(_cdir, ignore_errors=True)

# --- the held order's pickups, visited ----------------------------------------
#
# The driver: stopping at the held order's restaurant should mark that pickup
# done, so the panel's next stop, Map view's run and the "on your way" figure
# move on to the dropoff by themselves. server.js runs the door's own rule
# (stepAt) at each held pickup pin that names its planner line — inside the
# arrive radius for the dwell, then past 300 m on two good fixes — and marks
# the pickup visited on LEAVING (visitPickups); a planner read that has moved
# past a pickup marks it too, by the planner (plannerVisits). Real defaults
# here (a 60 s dwell), with real seconds made from each fix's age, 10 s
# apart. Places and points invented, in open country.
_vdir = tempfile.mkdtemp()


def _vsayer(name):
    """A scanner of its own in _vdir/name that says each line of say-N.json a
    quarter of a second apart, a heartbeat's `at` made now, and carries on
    from where it was after a restart; returns its script, the function that
    has it say lines and waits, and its journal."""
    d = os.path.join(_vdir, name)
    os.makedirs(d)
    script = os.path.join(d, 'say.py')
    with open(script, 'w') as fh:
        fh.write(
            'import json, os, time\n'
            'd = os.path.dirname(os.path.abspath(__file__))\n'
            'q = os.path.join(d, "next")\n'
            'n = int(open(q).read()) if os.path.exists(q) else 0\n'
            'end = time.time() + 600\n'
            'while time.time() < end:\n'
            '    p = os.path.join(d, "say-%d.json" % n)\n'
            '    if not os.path.exists(p):\n'
            '        time.sleep(0.05)\n'
            '        continue\n'
            '    for x in json.load(open(p)):\n'
            '        if x.get("alive"):\n'
            '            x["at"] = int(time.time() * 1000)\n'
            '        print(json.dumps(x), flush=True)\n'
            '        time.sleep(0.25)\n'
            '    open(os.path.join(d, "done-%d" % n), "w").close()\n'
            '    n += 1\n'
            '    open(q, "w").write(str(n))\n')
    seq = [0]

    def says(lines):
        n = seq[0]
        seq[0] += 1
        path = os.path.join(d, 'say-%d.json' % n)
        with open(path + '.tmp', 'w') as fh:
            json.dump(lines, fh)
        os.rename(path + '.tmp', path)
        for _ in range(600):
            if os.path.exists(os.path.join(d, 'done-%d' % n)):
                break
            time.sleep(0.05)
        time.sleep(0.3)
    open(os.path.join(d, 'offers.jsonl'), 'w').close()
    return script, says, os.path.join(d, 'offers.jsonl')


_R1 = (33.9000, -84.5000)               # the held order's restaurant
_R2 = (33.9300, -84.5000)               # another, 3.3 km north
_R3 = (33.9011, -84.5000)               # a second store 122 m from _R1
_Q1 = '310 Mill St, Roswell, GA 30075'
_Q2 = '88 Example Way, Roswell, GA 30075'
_Q3 = '312 Mill St, Roswell, GA 30075'


def _vstop(q, street, name='oe Example'):
    return {'kind': 'pickup', 'orders': 1, 'name': name, 'expectedBy': 1189,
            'street': street, 'city': 'Roswell', 'state': 'GA', 'zip': '30075', 'line': q}


_VDROP = {'kind': 'dropoff', 'orders': 1, 'name': 'Pat Q.', 'expectedBy': 1230,
          'street': '4821 Kestrel Dr', 'city': 'Marietta', 'state': None, 'zip': None,
          'line': '4821 Kestrel Dr, Marietta'}


def _vplanner(*stops):
    return {'planner': {'stops': list(stops), 'unfiled': 'dropoffs', 'asked': False}}


def _vread(*stops, **kw):
    """One unpressed planner read as the scanner sends it: the sighting, its
    page's ends (`top`: planner_ends' title over the first stop) and then the
    planner line, the two carrying the read's `at`."""
    at = int(time.time() * 1000)
    seen = [dict(st, label=st['kind'], place=None, partial=None) for st in stops]
    return [{'sighting': {'at': at, 'asked': False, 'whole': True, 'titled': False,
                          'app': 'uber', 'screen': 'uber.planner',
                          'page': {'top': kw.get('top', True), 'bottom': False},
                          'stops': seen, 'orderCount': None, 'keep': False}},
            {'planner': {'stops': list(stops), 'asked': False, 'at': at}}]


def _vbeat(at, dlat=0.0, age=0.1):
    return {'alive': True, 'gps': {'state': 'ok', 'ageSeconds': 0.1, 'fix': {
        'lat': at[0] + dlat, 'lon': at[1], 'gpsAge': age, 'gpsErr': 25.0, 'gpsMode': 3,
        'gpsOk': True, 'gpsWhy': None, 'freshFor': 10.0}}}


def _vwait(at, seconds, dlat=-0.0003):
    """Parked ~33 m south of `at` for `seconds`, one fix every 10 s."""
    return [_vbeat(at, dlat, age=a) for a in range(int(seconds), 0, -10)] + [_vbeat(at, dlat)]


def _vleave(at):
    return [_vbeat(at, 0.005)] * 2       # ~556 m: past LEAVE_M on two fixes


def _vpin(base, h, at, q):
    return post(base, '/api/held-pickup', {'holdId': h.get('holdId'), 'lat': at[0],
                                           'lon': at[1], 'q': q})


def _vvisited(base):
    return (_holding(base) or {}).get('visited')


def _vbeatsaid(base):
    return ((get(base, '/api/status').get('beat') or {}).get('heldEnd') or {}).get('visited')


def _vrows(journal):
    rows = [json.loads(l) for l in open(journal) if l.strip()]
    return [r for r in rows if r.get('kind') == 'visit']


try:
    _vs, _vsay, _vj = _vsayer('one')
    _venv = {'SCANNER': '1', 'SCANNER_CMD': sys.executable, 'SCANNER_ARGS': _vs}
    _vp, _vb = start(_venv, _vj)
    try:
        # Driving past: inside the circle for 20 s, then gone.
        _h = _took(_vb, 'v-past')
        _vsay([_vplanner(_vstop(_Q1, '310 Mill St'), _VDROP)])
        _vpin(_vb, _h, _R1, _Q1)
        _vsay(_vwait(_R1, 20) + _vleave(_R1))
        eq('[pickup visit] driving past the restaurant does not',
           (_vvisited(_vb), _vrows(_vj)), ([], []))
        post(_vb, '/api/delivered', {})

        # Stopped at the restaurant for three minutes and still there: the
        # restaurant is still where the car goes next, on the beat the panel
        # reads it from and on /api/status.
        _h = _took(_vb, 'v-stop')
        _vsay([_vplanner(_vstop(_Q1, '310 Mill St'), _VDROP)])
        eq('[pickup visit] (the premise: the pin is kept, named by its planner line)',
           _vpin(_vb, _h, _R1, _Q1)[0], 200)
        _vsay(_vwait(_R1, 180))
        eq('[pickup visit] a waiting car keeps the restaurant as its next stop',
           (_vvisited(_vb), _vbeatsaid(_vb)), ([], []))
        # ...then it leaves.
        _vcount = get(_vb, '/api/journal?days=0').get('count')
        _vsay(_vleave(_R1))
        _vr = _vrows(_vj)
        eq('[pickup visit] a 3-minute stop at the held pickup, then leaving, marks it visited',
           (_vvisited(_vb), _vbeatsaid(_vb),
            [(r.get('holdId'), r.get('pickup'), r.get('by')) for r in _vr]),
           ([_Q1], [_Q1], [(_h.get('holdId'), 0, 'gps')]))
        eq('[pickup visit] ...and its journal row says which and when, and nothing of where',
           [sorted(r) for r in _vr],
           [['at', 'by', 'holdId', 'id', 'kind', 'pickup', 'seq', 'v']])
        # The offers page reads the journal through the fold, which skips a
        # kind it has no use for.
        eq('[pickup visit] ...and the offers page counts what it did: a visit row is no offer',
           (get(_vb, '/api/journal?days=0').get('count'), _vcount is not None), (_vcount, True))
        # The app still lists the pickup until the driver swipes it.
        _vsay([_vplanner(_vstop(_Q1, '310 Mill St'), _VDROP)])
        eq('[pickup visit] a planner re-read does not un-visit',
           (_vvisited(_vb), len(_vrows(_vj))), ([_Q1], 1))
        _hj = json.load(open(os.path.join(os.path.dirname(_vj), 'holding.json')))
        eq('[pickup visit] ...and the visit is in holding.json',
           [[(e.get('q'), e.get('visited'), e.get('by')) for e in o.get('pickups') or []]
            for o in _hj.get('orders') or []], [[(_Q1, True, 'gps')]])
    finally:
        stop(_vp)
    _vp, _vb = start(_venv, _vj)
    try:
        eq('[pickup visit] survives a restart',
           ((_holding(_vb) or {}).get('holdId'), _vvisited(_vb)), (_h.get('holdId'), [_Q1]))
        post(_vb, '/api/delivered', {})

        # The planner's own word: a read that has moved past a pickup. Every
        # read here shows the top of the list unless it says otherwise.
        _h = _took(_vb, 'v-plan')
        _vsay(_vread(_vstop(_Q1, '310 Mill St'), _vstop(_Q2, '88 Example Way'), _VDROP))
        # ...but first one cut off below the first pickup, which says nothing
        # about the second.
        _vsay(_vread(_vstop(_Q1, '310 Mill St')))
        eq('[pickup visit] a planner read cut off above a pickup does not visit it',
           (_vvisited(_vb), _vrows(_vj)[1:]), ([], []))
        # ...and one scrolled down: the stops after the first pickup without
        # it, which is what "moved past" looks like, off a page that does not
        # show the top of the list.
        _vsay(_vread(_vstop(_Q2, '88 Example Way'), _VDROP, top=False))
        eq('[pickup visit] a planner read that starts below the top of the list marks nothing',
           (_vvisited(_vb), _vrows(_vj)[1:]), ([], []))
        _vsay(_vread(_vstop(_Q2, '88 Example Way'), _VDROP))
        eq('[pickup visit] a planner re-read that drops a pickup marks it visited, by the planner',
           (_vvisited(_vb), [(r.get('holdId'), r.get('pickup'), r.get('by'))
                             for r in _vrows(_vj)[1:]]),
           ([_Q1], [(_h.get('holdId'), 0, 'planner')]))
        post(_vb, '/api/delivered', {})

        # Two stores 122 m apart: parked at one, the car is 156 m from the
        # other, outside its circle for the whole wait.
        _h = _took(_vb, 'v-plaza')
        _vsay([_vplanner(_vstop(_Q1, '310 Mill St'), _vstop(_Q3, '312 Mill St'), _VDROP)])
        _vpin(_vb, _h, _R1, _Q1)
        _vpin(_vb, _h, _R3, _Q3)
        _vsay(_vwait(_R1, 180) + _vleave(_R1))
        eq('[pickup visit] two held pickups within 150 m of each other are visited together',
           sorted(_vvisited(_vb) or []), sorted([_Q1, _Q3]))
        _vr = [r for r in _vrows(_vj) if r.get('holdId') == _h.get('holdId')]
        eq('[pickup visit] ...as two rows the sync keeps apart: one beat, one seq, an id each',
           (len(_vr), len({(r.get('id'), r.get('seq')) for r in _vr}),
            sorted(r.get('pickup') for r in _vr)), (2, 2, [0, 1]))
        post(_vb, '/api/delivered', {})
    finally:
        stop(_vp)

    # Two orders in the car (carrying two on), each card naming its store.
    # The planner, read for the first, lists both restaurants and a third
    # store neither card names; Map view pins all three for the first order,
    # as it does (want.heldId). The car calls at the SECOND order's
    # restaurant and leaves, then at the store nobody's card names.
    _vs2, _vsay2, _vj2 = _vsayer('two')
    _vp, _vb = start(dict(_venv, SCANNER_ARGS=_vs2, CARRY_TWO='1'), _vj2)
    try:
        def _vcard(oid, pay, store, miles, end):
            post(_vb, '/api/offers/mark', {
                'id': oid, 'accepted': True,
                'offer': {'id': oid, 'pay': pay, 'minutes': 40.0, 'billedMinutes': 40.0,
                          'miles': miles, 'cost': 1.75, 'pickup': store, 'dropoff': end,
                          'multiOrder': False}})
        _vcard('v-a', 12.0, 'Example Diner', 5.0, '4821 Kestrel Dr, Marietta')
        _vcard('v-b', 9.0, 'Example Grill', 3.0, '77 Birch Ln, Roswell')
        _two = get(_vb, '/api/status').get('orders') or []
        ok_('[pickup visit] (the premise: two orders in the car)', len(_two) == 2)
        _ha, _hb = (_two + [{}, {}])[:2]
        _Q4 = '9 Other Pl, Roswell, GA 30075'
        _R4 = (33.9600, -84.5000)            # 6.7 km north of _R1
        _vsay2(_vread(_vstop(_Q1, '310 Mill St', 'oe Example Diner'),
                      _vstop(_Q2, '88 Example Way', 'oe Example Grill'),
                      _vstop(_Q4, '9 Other Pl', 'oe Other Place'), _VDROP))
        for _at, _q in ((_R1, _Q1), (_R2, _Q2), (_R4, _Q4)):
            _vpin(_vb, _ha, _at, _q)
        _vsay2(_vwait(_R2, 180) + _vleave(_R2))
        _orders = {o.get('holdId'): o.get('visited')
                   for o in get(_vb, '/api/status').get('orders') or []}
        eq('[pickup visit] two orders: visiting one order\'s restaurant leaves the other\'s',
           _orders.get(_ha.get('holdId')), [])
        _hj = json.load(open(os.path.join(os.path.dirname(_vj2), 'holding.json')))
        _pins = {o.get('holdId'): sorted(p.get('q') for p in o.get('pickupPins') or [])
                 for o in _hj.get('orders') or []}
        eq('[pickup visit] two orders: the pin and the visit are filed under the order whose '
           'card names that store',
           (_orders.get(_hb.get('holdId')), _Q2 in _pins.get(_hb.get('holdId'), []),
            [(r.get('holdId'), r.get('pickup'), r.get('by')) for r in _vrows(_vj2)]),
           ([_Q2], True, [(_hb.get('holdId'), 0, 'gps')]))
    finally:
        stop(_vp)
    # Restarted between the two stops: every named pin is stepped on every
    # beat, so the store's pin has already counted the fixes above, and this
    # suite's fixes are made by age — a wait replayed after them would read as
    # older than the last fix it counted. A car's real fixes only move on. The
    # orders come back from holding.json; the dwell's live part is memory.
    _vp, _vb = start(dict(_venv, SCANNER_ARGS=_vs2, CARRY_TWO='1'), _vj2)
    try:
        _vsay2(_vwait(_R4, 180) + _vleave(_R4))
        eq('[pickup visit] two orders and no cue for a pickup: nothing is marked, not even '
           'under the first order',
           ([o.get('visited') for o in get(_vb, '/api/status').get('orders') or []],
            len(_vrows(_vj2))), ([[], [_Q2]], 1))
    finally:
        stop(_vp)
finally:
    shutil.rmtree(_vdir, ignore_errors=True)

# --- restaurant waits ---------------------------------------------------------
#
# The owner's request of 22 Oct 2026: how long the car stood at a store,
# measured by the GPS at each held pickup it visited (visitPickups), kept per
# store in store-waits.json beside the journal — keyed by the pin rounded to
# STORE_GRID_DEG and the store's name — and said on a card naming the store
# with two visits or more (`storeWait`, server.js storeWaitFor). The fixes are
# _vwait's, real seconds made from each fix's age, so a 3-minute wait reads
# 180 s plus the second or so the lines take to say. Invented stores.
_vdir = tempfile.mkdtemp()
_SW = (33.90012, -84.50017)             # a store's pin, off the 0.0005° grid
_SWQ = '310 Mill St, Roswell, GA 30075'


def _swtook(base, oid, pickup):
    post(base, '/api/offers/mark', {
        'id': oid, 'accepted': True,
        'offer': {'id': oid, 'pay': 12.0, 'minutes': 40.0, 'billedMinutes': 40.0,
                  'miles': 5.0, 'cost': 1.75, 'pickup': pickup,
                  'dropoff': '4821 Kestrel Dr, Marietta', 'multiOrder': False}})
    return get(base, '/api/status').get('holding') or {}


def _swvisit(base, say, oid, pickup, seconds):
    """Took, the pickup pinned, a wait of `seconds` there and away, Drop."""
    h = _swtook(base, oid, pickup)
    _vpin(base, h, _SW, _SWQ)
    say(_vwait(_SW, seconds) + _vleave(_SW))
    post(base, '/api/delivered', {})


def _swfile(journal):
    try:
        return json.load(open(os.path.join(os.path.dirname(journal), 'store-waits.json')))
    except (OSError, ValueError):
        return None


def _swread(pickup):
    return {'ready': True, 'state': 'go', 'perHour': 30.0, 'grossPerHour': 33.6, 'pay': 7.25,
            'minutes': 25.0, 'billedMinutes': 25.0, 'cardMinutes': 25.0, 'miles': 4.0,
            'cost': 1.4, 'target': 25, 'band': 15, 'costPerMile': 0.35, 'pickup': pickup,
            'places': [pickup, '77 Birch Ln, Roswell']}


try:
    _ws, _wsay, _wj = _vsayer('waits')
    _wenv = {'SCANNER': '1', 'SCANNER_CMD': sys.executable, 'SCANNER_ARGS': _ws}
    _wp, _wb = start(_wenv, _wj)
    try:
        _swvisit(_wb, _wsay, 'w-1', 'Larkspur Tacos (310 Mill St)', 180)
        _wf = _swfile(_wj) or {}
        _wst = (_wf.get('stores') or [{}])[0]
        ok_('[store waits] a 3-minute stop at a held pickup the GPS visited is one wait of its '
            'store, 180 s and the seconds the lines took (got %r)' % (_wf,),
            len(_wf.get('stores') or []) == 1 and _wst.get('name') == 'Larkspur Tacos'
            and [180 <= w.get('s', 0) <= 190 for w in _wst.get('waits') or []] == [True])
        eq('[store waits] ...kept at its pin rounded to the grid, and the store\'s name less '
           'Uber\'s bracketed street', (_wst.get('lat'), _wst.get('lon'), _wst.get('key')),
           (33.9, -84.5, 'larkspurtacos@67800,-169000'))
        # One visit is not enough to say anything.
        _wsay([_swread('Larkspur Tacos (310 Mill St)')])
        no_('[store waits] one visit on record: the card says nothing',
            'storeWait' in (get(_wb, '/api/status').get('last') or {}))
        _swvisit(_wb, _wsay, 'w-2', 'Larkspur Tacos', 120)
        # A card whose pickup is a door, not a name: no store to keep it by.
        _swvisit(_wb, _wsay, 'w-3', '1981 Cobb Pkwy NW, Kennesaw', 120)
        _wf = _swfile(_wj) or {}
        eq('[store waits] a second visit joins the first under one store; a pickup that is a '
           'door is kept under no name', [(s.get('name'), len(s.get('waits') or []))
                                          for s in _wf.get('stores') or []],
           [('Larkspur Tacos', 2)])
        _wsay([_swread('Larkspur Tacos')])
        eq('[store waits] two visits: the card naming the store, with no pin, a distinctive name '
           'at one place, carries how many and the mean in whole minutes; the verdict its own',
           ((get(_wb, '/api/status').get('last') or {}).get('storeWait'),
            (get(_wb, '/api/status').get('last') or {}).get('state')),
           ({'n': 2, 'avgMin': 3}, 'go'))
        _wsay([_swread('Wren Street Noodles')])
        no_('[store waits] ...a card naming another store carries none',
            'storeWait' in (get(_wb, '/api/status').get('last') or {}))
        _wrow = [sorted(r) for r in _vrows(_wj)]
        eq('[store waits] ...and the journal\'s visit rows are as they were: no wait, no place',
           _wrow, [['at', 'by', 'holdId', 'id', 'kind', 'pickup', 'seq', 'v']] * 3)
    finally:
        stop(_wp)
    # A history beside the journal survives a restart, and nothing is
    # backfilled into it: the journal has no position and no dwell start.
    _wp, _wb = start(_wenv, _wj)
    try:
        _wsay([_swread('Larkspur Tacos (310 Mill St)')])
        eq('[store waits] after a restart the card still says it',
           (get(_wb, '/api/status').get('last') or {}).get('storeWait'), {'n': 2, 'avgMin': 3})
    finally:
        stop(_wp)
finally:
    shutil.rmtree(_vdir, ignore_errors=True)

# --- DoorDash's place popup, read while a card is screened -------------------
#
# The driver taps a stop on a DoorDash card before deciding and the phone shows
# its address; the scanner sends it on its own `popup` line (emit_popup) and
# the server files it onto the card being screened, or nowhere — never onto the
# order in the car (Assemble.popup decides; popupArrived files). A fake scanner
# steps through it, each step waiting on a file this suite writes, so every
# answer below is read at a known point. Made-up stores, streets and doors.
_PFAKE = (
    'import json, os, time\n'
    'D = os.path.dirname(os.path.abspath(__file__))\n'
    'def wait(n):\n'
    '    while not os.path.exists(os.path.join(D, n)):\n'
    '        time.sleep(0.05)\n'
    'def now():\n'
    '    return int(time.time() * 1000)\n'
    'def card(i, pickup, pay=7.75):\n'
    '    print(json.dumps({"ready": True, "state": "go", "perHour": 30.0,\n'
    '        "grossPerHour": 36.0, "pay": pay, "minutes": 30.0, "cardMinutes": 30.0,\n'
    '        "miles": 7.8, "cost": 2.34, "billedMinutes": 34.0, "target": 25, "band": 15,\n'
    '        "costPerMile": 0.3, "pickup": pickup, "dropoff": None, "at": now(),\n'
    '        "offer": {"id": i, "pay": pay, "minutes": 30.0, "billedMinutes": 34.0,\n'
    '                  "miles": 7.8, "cost": 2.34, "perHour": 30.0, "state": "go",\n'
    '                  "pickup": pickup, "dropoff": None, "app": "doordash",\n'
    '                  "screen": "dd.offer", "manyDropoffs": False}}), flush=True)\n'
    'def popup(role, line, name=None):\n'
    '    print(json.dumps({"popup": {"role": role, "name": name, "line": line,\n'
    '        "street": line.split(",")[0], "city": line.split(", ")[1], "state": "GA",\n'
    '        "zip": line[-5:], "app": "doordash", "screen": "dd.placePopup",\n'
    '        "at": now()}}), flush=True)\n'
    'STORE = "1200 Fable W Lantern Pkwy NW, Kennesaw, GA 30144"\n'
    'card("dd-1", "S &, Lark Owl Pizza ; 1200 Fable Parkway Nort")\n'
    'wait("f1")\n'
    'popup(None, "88 Quill Ln NE, Marietta, GA 30062")\n'
    'popup("pickup", "500 Wren St NW, Atlanta, GA 30318", name="Wren Street Noodles")\n'
    'wait("f2")\n'
    'popup("pickup", STORE, name="Lark Owl Pizza")\n'
    'wait("f3")\n'
    'card("dd-1", "S &, Lark Owl Pizza ; 1200 Fable Parkway Nort")\n'
    'wait("f4")\n'
    'popup("dropoff", "412 Wrenfield Ct NE, Marietta, GA 30062")\n'
    'wait("f5")\n'
    'popup("dropoff", "77 Quill Ln NE, Marietta, GA 30062")\n'
    'popup("pickup", STORE, name="Lark Owl Pizza")\n'
    'wait("f6")\n'
    'card("dd-2", "Fable Bagel Co", pay=6.5)\n'
    # A popup's frame is taken after its card is on the slot: a real tap
    # follows the card by seconds (2.1 s at the least on file). Printed with no
    # gap, its stamp can precede the server's receipt of the card line, which
    # is "read before the card" and refused, rightly.
    'time.sleep(0.5)\n'
    'popup("dropoff", "9 Heron Ct, Smyrna, GA 30080")\n'
    'time.sleep(600)\n')
_pdir = tempfile.mkdtemp()
try:
    _pj = os.path.join(_pdir, 'journal.jsonl')
    _pf = os.path.join(_pdir, 'popupfake.py')
    with open(_pf, 'w') as fh:
        fh.write(_PFAKE)
    open(_pj, 'w').close()
    _pp, _pb = start({'SCANNER': '1', 'SCANNER_CMD': sys.executable, 'SCANNER_ARGS': _pf,
                      'HOLD_GRACE_MS': '600000', 'CARRY_TWO': '0'}, _pj)

    def _step(n, settle=0.8):
        open(os.path.join(_pdir, n), 'w').close()
        time.sleep(settle)
        return get(_pb, '/api/status')

    def _pmarks():
        # Read here: `lines` is rebound to a list by a check above this one.
        _rows = [json.loads(l) for l in open(_pj) if l.strip()]
        return [(r.get('id'), r.get('dropoff'), r.get('from')) for r in _rows
                if r.get('kind') == 'mark' and r.get('dropoff')]

    try:
        for _ in range(160):
            if (get(_pb, '/api/status').get('offer') or {}).get('id') == 'dd-1':
                break
            time.sleep(0.05)
        _pev = listen(_pb, 6.0)
        time.sleep(0.3)
        _s1 = (_step('f1').get('offer') or {})
        eq('[popup] a popup with no role cue files nothing',
           (_s1.get('dropoff'), _s1.get('dropoffScanned'), _pmarks()), (None, None, []))
        eq('[popup] a popup for a different store files nothing', _s1.get('pickupAddr'), None)
        _s2 = (_step('f2').get('offer') or {})
        eq('[popup] a store popup read while a card is screened gives the card its pickup '
           'address', [(_s2.get('pickupAddr') or {}).get(k) for k in ('value', 'from', 'name')],
           ['1200 Fable W Lantern Pkwy NW, Kennesaw, GA 30144', 'popup', 'Lark Owl Pizza'])
        _s3 = (_step('f3').get('offer') or {})
        eq('[popup] ...and the next reading of the card keeps it',
           (_s3.get('pickupAddr') or {}).get('value'),
           '1200 Fable W Lantern Pkwy NW, Kennesaw, GA 30144')
        _s4 = (_step('f4').get('offer') or {})
        eq('[popup] a customer popup gives the dropoff',
           (_s4.get('dropoff'), _s4.get('dropoffScanned'), _s4.get('dropoffFrom'), _pmarks()),
           ('412 Wrenfield Ct NE, Marietta, GA 30062', True, 'popup',
            [('dd-1', '412 Wrenfield Ct NE, Marietta, GA 30062', 'popup')]))
        _code, _reply = post(_pb, '/api/offers/mark', {'id': 'dd-1', 'accepted': True})
        time.sleep(0.3)
        _hj = json.load(open(os.path.join(_pdir, 'holding.json')))
        _f = ((_hj.get('orders') or [{}])[0].get('fields') or {})
        eq('[popup] carried into the hold at Took',
           [(_f.get('pickupAddr') or {}).get('value'), (_f.get('pickupAddr') or {}).get('from'),
            (_f.get('dropoff') or {}).get('value'), (_f.get('dropoff') or {}).get('from'),
            ((_hj.get('orders') or [{}])[0]).get('dropoff')],
           ['1200 Fable W Lantern Pkwy NW, Kennesaw, GA 30144', 'popup',
            '412 Wrenfield Ct NE, Marietta, GA 30062', 'popup',
            '412 Wrenfield Ct NE, Marietta, GA 30062'])
        _s5 = _step('f5')
        _hj5 = json.load(open(os.path.join(_pdir, 'holding.json')))
        eq('[popup] never onto the held order',
           ((_s5.get('offer') or {}).get('dropoff'), (_s5.get('holding') or {}).get('dropoff'),
            ((_hj5.get('orders') or [{}])[0]).get('dropoff'), len(_pmarks())),
           ('412 Wrenfield Ct NE, Marietta, GA 30062', '412 Wrenfield Ct NE, Marietta, GA 30062',
            '412 Wrenfield Ct NE, Marietta, GA 30062', 1))
        _s6 = _step('f6')
        eq('[popup] ...and the next card being screened takes its own, the order in the car '
           'keeping its end',
           ((_s6.get('offer') or {}).get('id'), (_s6.get('offer') or {}).get('dropoff'),
            (_s6.get('holding') or {}).get('dropoff')),
           ('dd-2', '9 Heron Ct, Smyrna, GA 30080', '412 Wrenfield Ct NE, Marietta, GA 30062'))
        time.sleep(1.0)
        ok_('[popup] ...and every panel is sent the card with what it now holds at once, not '
            'at its next reading', any((m.get('popup') or {}).get('field') == 'pickupAddr'
                                       and ((m.get('offer') or {}).get('pickupAddr') or {})
                                       .get('from') == 'popup' for m in _pev))
    finally:
        stop(_pp)
finally:
    shutil.rmtree(_pdir, ignore_errors=True)

# --- a scanner that says what the suite tells it, when it tells it ------------
#
# The sections below each start a server on a fake scanner that prints every
# line the suite appends to its queue, as it arrives — a card, a beat, a
# sighting, a dropoff — so a check puts each one exactly where its fault needs
# it. The server's own output is kept in a file beside the journal, for the
# checks about what it says. Every store, street and customer invented.
_QFAKE = (
    'import sys, time\n'
    'q = sys.argv[1]\n'
    'pos = 0\n'
    'buf = ""\n'
    'while True:\n'
    '    try:\n'
    '        with open(q) as fh:\n'
    '            fh.seek(pos)\n'
    '            data = fh.read()\n'
    '            pos = fh.tell()\n'
    '    except OSError:\n'
    '        data = ""\n'
    '    if data:\n'
    '        buf += data\n'
    '        got = buf.split("\\n")\n'
    '        buf = got.pop()\n'
    '        for line in got:\n'
    '            if line:\n'
    '                print(line, flush=True)\n'
    '    else:\n'
    '        time.sleep(0.01)\n')


class _Q(object):
    """One server on the queue fake. `dir` holds its journal, holding.json and
    log; `emit` sends a line; `card` puts an offer on the slot and waits for it."""

    def __init__(self, carry=False, env=None, holding=None, root=None):
        self.dir = tempfile.mkdtemp()
        self.journal = os.path.join(self.dir, 'journal.jsonl')
        open(self.journal, 'w').close()
        self.queue = os.path.join(self.dir, 'queue')
        open(self.queue, 'w').close()
        self.hold = os.path.join(self.dir, 'holding.json')
        if holding is not None:
            with open(self.hold, 'w') as fh:
                fh.write(holding)
        fake = os.path.join(self.dir, 'qfake.py')
        with open(fake, 'w') as fh:
            fh.write(_QFAKE)
        e = {'SCANNER': '1', 'SCANNER_CMD': sys.executable,
             'SCANNER_ARGS': fake + ' ' + self.queue, 'SCANNER_SILENT_MS': '600000',
             'UBERSCAN_HANDOFF_DIR': self.dir}
        # None: no override, so the flag is read off <root>/rpi/config.json.
        e['CARRY_TWO'] = '' if carry is None else '1' if carry else '0'
        e.update(env or {})
        self.logpath = os.path.join(self.dir, 'server.log')
        self._log = open(self.logpath, 'w')
        port = free_port()
        self.proc = subprocess.Popen(
            ['node', os.path.join(root or ROOT, 'server.js')],
            env=dict(os.environ, PORT=str(port), HTTPS_PORT='0', JOURNAL=self.journal, **e),
            stdout=self._log, stderr=self._log)
        self.base = 'http://127.0.0.1:%d' % port
        for _ in range(120):
            try:
                urllib.request.urlopen(self.base + '/api/status', timeout=1).read()
                return
            except Exception:
                time.sleep(0.1)
        self.stop()
        raise RuntimeError('the server never came up')

    def emit(self, obj):
        with open(self.queue, 'a') as fh:
            fh.write(json.dumps(obj) + '\n')

    def status(self):
        return get(self.base, '/api/status')

    def card(self, oid, pay, minutes, app, **extra):
        o = {'id': oid, 'pay': pay, 'minutes': minutes, 'billedMinutes': minutes,
             'miles': 6.0, 'cost': 1.8, 'perHour': 20.0, 'state': 'warn', 'app': app,
             'screen': app + '.offer', 'pickup': 'Store ' + oid, 'dropoff': None,
             'whole': True, 'legs': 2, 'multiOrder': False}
        o.update(extra)
        self.emit({'offer': o})
        for _ in range(200):
            if (self.status().get('offer') or {}).get('id') == oid:
                return o
            time.sleep(0.02)
        raise RuntimeError('the card never landed: ' + oid)

    def took(self, oid, via='panel', **extra):
        body = {'id': oid, 'accepted': True}
        if via is not None:
            body['via'] = via
        body.update(extra)
        return post(self.base, '/api/offers/mark', body)[1]

    def rows(self, kind=None):
        out = [json.loads(l) for l in open(self.journal) if l.strip()]
        return [r for r in out if kind is None or r.get('kind') == kind]

    def log(self):
        self._log.flush()
        return open(self.logpath).read()

    def stop(self):
        stop(self.proc)
        self._log.close()

    def gone(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def _settle(seconds=0.6):
    time.sleep(seconds)


# --- two orders in the car: a list with more dropoffs than orders left --------
#
# Carrying two on. An Uber card for two customers is taken, and a DoorDash
# order beside it; the Trip Planner is read whole, unpressed, with the two
# customers' doors on it. The hard rules leave one order (the app rules the
# DoorDash order out) and the list has two dropoffs, so `only` would be a guess
# between that order's two customers — or a customer of no order of ours.
# assemble.js attribute(): `only` is not allowed there. The same list read just
# before a second Uber Took lands, so that order is ruled out by the read's own
# time, is the same shape.
_PLAN2 = [
    {'kind': 'pickup', 'orders': 2, 'name': 'Wren Street Noodles', 'expectedBy': 1100,
     'line': '1 Mill St, Roswell', 'street': '1 Mill St', 'city': 'Roswell',
     'state': None, 'zip': None},
    {'kind': 'dropoff', 'orders': 1, 'name': 'Mara T.', 'expectedBy': 1130,
     'line': '20 Larch Way, Kennesaw', 'street': '20 Larch Way', 'city': 'Kennesaw',
     'state': None, 'zip': None},
    {'kind': 'dropoff', 'orders': 1, 'name': 'Jules K.', 'expectedBy': 1150,
     'line': '30 Teal Ct, Smyrna', 'street': '30 Teal Ct', 'city': 'Smyrna',
     'state': None, 'zip': None}]


def _planner2(q, at):
    q.emit({'sighting': {'at': at, 'asked': False, 'whole': True, 'titled': True,
                         'app': 'uber', 'screen': 'uber.planner',
                         'page': {'top': True, 'bottom': True}, 'stops': _PLAN2,
                         'orderCount': 2, 'keep': True}})
    q.emit({'planner': {'at': at, 'stops': _PLAN2, 'asked': False, 'keep': True}})


def _endmarks(q):
    return [(r.get('id'), r.get('dropoff'), r.get('cue')) for r in q.rows('mark')
            if r.get('dropoff')]


_q1 = _Q(carry=True)
try:
    _q1.card('U1', 14.0, 300, 'uber', multiOrder=True)
    _q1.took('U1')
    _q1.card('D1', 9.0, 300, 'doordash')
    _q1.took('D1')
    _settle(0.1)
    _planner2(_q1, int(time.time() * 1000))
    _settle()
    _st1 = _q1.status()
    eq('Uber planner with two dropoffs and a DoorDash order held: nothing filed',
       (_endmarks(_q1), [o.get('dropoff') for o in _st1.get('orders') or []]),
       ([], [None, None]))
finally:
    _q1.stop()
    _q1.gone()

_q2 = _Q(carry=True)
try:
    _q2.card('U1', 14.0, 300, 'uber', multiOrder=True)
    _q2.took('U1')
    _q2.card('U2', 8.0, 300, 'uber')
    _read = int(time.time() * 1000)
    _settle(0.05)
    _q2.took('U2')
    _settle(0.05)
    _planner2(_q2, _read)
    _settle()
    _st2 = _q2.status()
    eq('...nor when the second Took lands during the planner read',
       (_endmarks(_q2), [o.get('dropoff') for o in _st2.get('orders') or []]),
       ([], [None, None]))
finally:
    _q2.stop()
    _q2.gone()

# --- an address no order in the car can own ----------------------------------
#
# Two DoorDash orders held; an Uber navigation screen read unprompted. The hard
# rules (the app) leave it no order, and no later cue can change that, so it is
# not kept — parked, it said "1 dropoff read · whose?" for as long as both were
# carried.
_q3 = _Q(carry=True)
try:
    _q3.card('D1', 9.0, 120, 'doordash')
    _q3.took('D1')
    _q3.card('D2', 8.0, 120, 'doordash')
    _q3.took('D2')
    _settle(0.1)
    _q3.emit({'sighting': {'at': int(time.time() * 1000), 'asked': False, 'whole': True,
                           'app': 'uber', 'screen': 'uber.nav',
                           'stops': [{'kind': 'dropoff', 'line': '5 Heron Ct, Smyrna',
                                      'street': '5 Heron Ct', 'city': 'Smyrna'}]}})
    _settle()
    eq('an address no order can own is not waiting',
       (_q3.status().get('unowned'), _endmarks(_q3)), (0, []))
    ok_('...and the log says it was not kept',
        "nobody's: not kept" in _q3.log())
finally:
    _q3.stop()
    _q3.gone()

# --- holding.json: what is filed onto the order reaches it, whole -------------
#
# A ⌖ end filed onto the order in the car reached holding.json only through the
# NucBox search's save, so with NUCBOX_SEARCH unset (these servers) a restart
# brought the order back with its card's end. And the file was written in
# place, so a power cut mid-write left it cut short — read at boot as nothing
# held, with nothing said. And a planner read wrote it whether or not the read
# changed anything.
_PRESSED = {'found': True, 'line': '61 Wrenfield Ln, Kennesaw, GA 30144',
            'street': '61 Wrenfield Ln', 'city': 'Kennesaw', 'state': 'GA', 'zip': '30144',
            'asked': True}
_q4 = _Q(carry=False)
try:
    _q4.card('A', 12.0, 60, 'uber', dropoff='Birch Ln & Alder Ct, Kennesaw')
    _q4.took('A')
    _settle(0.1)
    _q4.emit({'dropoff': dict(_PRESSED, at=int(time.time() * 1000))})
    _settle()
    _live = _q4.status().get('holding') or {}
    eq('a ⌖ end is on the order in the car', (_live.get('dropoff'),
       ((_live.get('fields') or {}).get('dropoff') or {}).get('from')),
       (_PRESSED['line'], 'press'))
    _held4 = open(_q4.hold).read()
finally:
    _q4.stop()
    _q4.gone()
_q5 = _Q(carry=False, holding=_held4)
try:
    _back5 = _q5.status().get('holding') or {}
    eq('a ⌖ end survives a restart with no NucBox',
       (_back5.get('dropoff'), ((_back5.get('fields') or {}).get('dropoff') or {}).get('from')),
       (_PRESSED['line'], 'press'))
finally:
    _q5.stop()
    _q5.gone()

_whole6 = json.dumps({'v': 2, 'orders': [
    {'id': 'T', 'pay': 10.0, 'minutes': 120, 'acceptedAt': int(time.time() * 1000) - 60000}]})
_torn6 = _whole6[:-9]
_q6 = _Q(carry=False, holding=_torn6)
try:
    _st6 = _q6.status()
    _settle(0.2)
    eq('a torn holding.json is said at boot and kept aside',
       (_st6.get('holding'), 'could not be read' in _q6.log(),
        open(_q6.hold + '.bad').read() if os.path.exists(_q6.hold + '.bad') else None,
        os.path.exists(_q6.hold)),
       (None, True, _torn6, False))
    # ...and the next Took writes a whole file, through a temporary that does
    # not stay behind.
    _q6.card('B', 9.0, 30, 'uber')
    _q6.took('B')
    _settle(0.1)
    eq('...and the next Took writes a whole one, and leaves no temporary',
       ([o.get('id') for o in json.load(open(_q6.hold)).get('orders')],
        sorted(n for n in os.listdir(_q6.dir) if n.startswith('holding.json'))),
       (['B'], ['holding.json', 'holding.json.bad']))
finally:
    _q6.stop()
    _q6.gone()


def _plan1(q, name):
    stops = [{'kind': 'pickup', 'orders': 1, 'name': 'Larkspur Tacos', 'expectedBy': 1100,
              'line': '5 Mill St, Roswell', 'street': '5 Mill St', 'city': 'Roswell',
              'state': None, 'zip': None},
             {'kind': 'dropoff', 'orders': 1, 'name': name, 'expectedBy': 1130,
              'line': None, 'street': None, 'city': None, 'state': None, 'zip': None}]
    q.emit({'planner': {'at': int(time.time() * 1000), 'stops': stops, 'asked': False,
                        'keep': False}})
    _settle()


def _written(path):
    s = os.stat(path)
    return (s.st_ino, s.st_mtime_ns)


_q7 = _Q(carry=False)
try:
    _q7.card('A', 12.0, 60, 'uber')
    _q7.took('A')
    _settle(0.1)
    _plan1(_q7, 'Mara T.')
    _w1 = _written(_q7.hold)
    _plan1(_q7, 'Mara T.')
    eq('a planner read that changes nothing writes nothing', _written(_q7.hold), _w1)
    _plan1(_q7, 'Jules K.')
    eq('...and one that changes the stops writes them',
       (_written(_q7.hold) != _w1,
        [s.get('name') for s in (json.load(open(_q7.hold))['orders'][0].get('planner')
                                 or {}).get('stops', [])]),
       # (Two names due the same minute are two customers since the review
       # of 27 Oct, Assemble slotJoins: Mara's stop is kept beside Jules'.)
       (True, ['Larkspur Tacos', 'Mara T.', 'Jules K.']))
finally:
    _q7.stop()
    _q7.gone()

# --- a tick for the record is not a Took --------------------------------------
#
# The offers page's ✓ and Close the shift's Took and Passed answer for a card
# after the fact (via 'offers', 'review'); only the driving panel's Took (via
# 'panel', or no via from a page older than the field) puts an order in the car
# or takes one out. A review tick of the card still on the slot used to do
# both.
for _carry in (False, True):
    _q8 = _Q(carry=_carry)
    try:
        _q8.card('A', 12.0, 30, 'uber')
        _q8.took('A')
        post(_q8.base, '/api/delivered', {})
        _q8.card('B', 9.0, 25, 'doordash')
        _r8 = _q8.took('B', via='review')
        _settle(0.2)
        eq('a review tick of the card on the slot puts nothing in the car%s'
           % (' (carrying two)' if _carry else ''),
           (_r8.get('holding'), _q8.status().get('holding'),
            [(r.get('id'), r.get('via')) for r in _q8.rows('mark')]),
           (False, None, [('A', 'panel'), ('B', 'review')]))
    finally:
        _q8.stop()
        _q8.gone()

    _q9 = _Q(carry=_carry)
    try:
        _q9.card('A', 12.0, 60, 'uber', dropoff='Birch Ln & Alder Ct, Kennesaw')
        _q9.took('A')
        _settle(0.1)
        _q9.emit({'dropoff': dict(_PRESSED, at=int(time.time() * 1000))})
        _settle()
        _q9.took('A', via='offers')
        _h9 = _q9.status().get('holding') or {}
        eq('...nor rebuilds the order in the car%s' % (' (carrying two)' if _carry else ''),
           (_h9.get('dropoff'), ((_h9.get('fields') or {}).get('dropoff') or {}).get('from'),
            [r.get('by') for r in _q9.rows('drop')]),
           (_PRESSED['line'], 'press', []))
        # Since the owner's decision of 19 Oct 2026 the ✓ taken back on the
        # offers page is Drop for an order in the car, whoever took it.
        post(_q9.base, '/api/offers/mark', {'id': 'A', 'accepted': None, 'via': 'offers'})
        _settle(0.1)
        eq('[offers tick] ...and the ✓ taken back there puts the order down, by \'offers\'%s'
           % (' (carrying two)' if _carry else ''),
           (_q9.status().get('holding'),
            [(r.get('id'), r.get('by')) for r in _q9.rows('drop')]),
           (None, [('A', 'offers')]))
    finally:
        _q9.stop()
        _q9.gone()

# --- [offers tick] the offers page's ✓ on a RECENT card is a ✓ Took on it ------
#
# The owner's decision of 19 Oct 2026: cards move fast, and the panel's Took
# names only the last one. The offers page's ✓ on a card whose own hold would
# still be in force had it been taken when it arrived, with no Took of another
# card since it arrived, puts that card's order in the car from its reading as
# the slot had it (server.js offersTickHolds). Anything else records only and
# says why. Cards, doors and stores invented; the fix is the fake NucBox's
# Marietta Square, as '[auto arm]' uses.
_ofake = subprocess.Popen(['node', os.path.join(ROOT, 'tests', 'fake-nucbox.js')],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
_ofake_base = 'http://127.0.0.1:%d' % json.loads(_ofake.stdout.readline())['port']
_o1 = _Q(carry=False, env={'NUCBOX_SEARCH': _ofake_base, 'NUCBOX_TIMEOUT_MS': '800'})
try:
    _ev1 = listen(_o1.base, 6)
    _settle(0.3)
    _o1.card('R', 12.0, 40, 'doordash', **dict(
        _SQ, miles=5.0, dropoff=_COBB, pickup='Larkspur Tacos',
        pickupLine='12 Mill St, Roswell, GA'))
    _rat = int(time.time() * 1000)
    time.sleep(1.2)
    _o1.card('S', 8.0, 20, 'uber')
    _r1 = _o1.took('R', via='offers')
    _h1 = _settled(_o1.base)
    _f1 = ((json.load(open(_o1.hold)) if os.path.exists(_o1.hold) else {})
           .get('orders') or [{}])[0]
    _id1, _at1 = (str(_h1.get('holdId') or 'none@0').split('@') + ['0'])[:2]
    ok_('[offers tick] a recent card ticked there is the order in the car, dated from its '
        'own arrival (%r)' % _h1.get('holdId'),
        _id1 == 'R' and abs(int(_at1) - _rat) < 400 and (_h1.get('heldMs') or 0) >= 1100)
    eq('[offers tick] ...from that card\'s reading: pay, minutes, miles, ends, store door, fix',
       (_f1.get('pay'), _f1.get('minutes'), _f1.get('miles'), _f1.get('pickup'),
        _f1.get('dropoff'), _f1.get('pickupLine'), _f1.get('app'),
        (_f1.get('card') or {}).get('lat'), (_f1.get('card') or {}).get('multiOrder')),
       (12.0, 40, 5.0, 'Larkspur Tacos', _COBB, '12 Mill St, Roswell, GA', 'doordash',
        _SQ['lat'], False))
    eq('[offers tick] ...and the GPS drop armed from it, as a Took arms it',
       (_h1.get('endPinned'), _h1.get('endBy')), (True, 'server'))
    eq('[offers tick] ...the order says the offers page took it, the slot is left alone',
       (_f1.get('tookOn'), _h1.get('tookOn'), (_o1.status().get('offer') or {}).get('id')),
       ('offers', 'offers', 'S'))
    eq('[offers tick] ...the mark row keeps via \'offers\' and says it held',
       [(r.get('id'), r.get('accepted'), r.get('via'), r.get('inCar')) for r in _o1.rows('mark')],
       [('R', True, 'offers', True)])
    eq('[offers tick] ...the page is told', (_r1.get('car') or {}).get('held'), True)
    _settle(0.3)
    ok_('[offers tick] ...and every panel, on the stream',
        any(m.get('heldBy') == 'offers'
            and str((m.get('holding') or {}).get('holdId') or '').startswith('R@')
            for m in _ev1))
    _s1, _u1 = post(_o1.base, '/api/offers/mark', {'id': 'R', 'accepted': None, 'via': 'offers'})
    _settle(0.2)
    eq('[offers tick] the ✓ taken back puts it down like Drop, by \'offers\'',
       (_o1.status().get('holding'), (_u1.get('car') or {}).get('putDown'),
        [(r.get('id'), r.get('by')) for r in _o1.rows('drop')]),
       (None, True, [('R', 'offers')]))
    _r1b = _o1.took('never-on-the-slot', via='offers')
    eq('[offers tick] a card this server never held records only, and says why',
       (_r1b.get('car'), _o1.status().get('holding')),
       ({'held': False, 'why': 'unseen'}, None))
finally:
    _o1.stop()
    _o1.gone()
    _ofake.kill()

# Old: the card's own clock has run out (HOLD_GRACE_MS 0, a 0.02-minute card,
# so its hold would have ended 1.8 s after it arrived).
_o2 = _Q(carry=False, env={'HOLD_GRACE_MS': '0'})
try:
    _o2.card('O', 9.0, 0.02, 'uber')
    time.sleep(2.2)
    _r2 = _o2.took('O', via='offers')
    eq('[offers tick] a card whose hold would have run out records only (shift review)',
       (_r2.get('car'), _o2.status().get('holding'), _o2.rows('drop'),
        [(r.get('id'), r.get('via'), r.get('inCar')) for r in _o2.rows('mark')]),
       ({'held': False, 'why': 'old'}, None, [], [('O', 'offers', None)]))
finally:
    _o2.stop()
    _o2.gone()

# A later Took: card A, card B, ✓ Took on B; the offers page's ✓ on A records
# only and leaves B where it is. A card C that came up after B's Took is
# recent, and with carrying two off replaces B as a Took on C would.
_o3 = _Q(carry=False)
try:
    _o3.card('A', 12.0, 60, 'uber')
    _o3.card('B', 9.0, 60, 'uber')
    _o3.took('B')
    _r3 = _o3.took('A', via='offers')
    eq('[offers tick] a card ticked after a later Took records only, and the car is as it was',
       (_r3.get('car'), str((_o3.status().get('holding') or {}).get('holdId')).split('@')[0],
        _o3.rows('drop')),
       ({'held': False, 'why': 'later'}, 'B', []))
    time.sleep(0.05)
    _o3.card('C', 11.0, 30, 'uber')
    _o3.card('D', 7.0, 20, 'uber')
    _r3c = _o3.took('C', via='offers')
    _settle(0.2)
    eq('[offers tick] ...one that came up after it replaces the order as a Took would',
       ((_r3c.get('car') or {}).get('held'),
        str((_o3.status().get('holding') or {}).get('holdId')).split('@')[0],
        [(r.get('id'), r.get('by')) for r in _o3.rows('drop')]),
       (True, 'C', [('B', 'replaced')]))
finally:
    _o3.stop()
    _o3.gone()

# An Uber add-on ticked there joins the trip in the car, as its Took would.
_o4 = _Q(carry=False)
try:
    _o4.card('A', 25.03, 60, 'uber')
    _o4.took('A')
    _hA = (_o4.status().get('holding') or {}).get('holdId')
    _o4.card('U', 9.5, 8, 'uber', addon=True, screen='uber.addon')
    _o4.card('X', 6.0, 15, 'doordash')
    _r4 = _o4.took('U', via='offers')
    _settle(0.2)
    _ord4 = _o4.status().get('orders') or []
    eq('[offers tick] an add-on ticked there joins the trip in the car',
       ((_r4.get('car') or {}).get('held'),
        [(str(o.get('holdId')).split('@')[0], o.get('addOn'), o.get('of')) for o in _ord4],
        _o4.rows('drop')),
       (True, [('A', False, None), ('U', True, _hA)], []))
    eq('[offers tick] ...and its mark row says so',
       [(r.get('id'), r.get('addon'), r.get('addonTo'), r.get('inCar'))
        for r in _o4.rows('mark') if r.get('id') == 'U'],
       [('U', True, _hA, True)])
finally:
    _o4.stop()
    _o4.gone()

# Mutation catch-up (21 Oct): the rest of offersTickHolds' rules, each by name.
# A card with no minutes is 'untimed', not 'old'; and a card's own clock is
# its BILLED minutes, as a Took's hold is (HOLD_GRACE_MS 0: a card printing 30
# minutes billed 0.02 is over 1.8 s after it arrived).
_o5 = _Q(carry=False, env={'HOLD_GRACE_MS': '0'})
try:
    _o5.card('N', 9.0, None, 'uber')
    _r5 = _o5.took('N', via='offers')
    eq('[offers tick] a card with no minutes records only, \'untimed\'',
       (_r5.get('car'), _o5.status().get('holding')), ({'held': False, 'why': 'untimed'}, None))
    _o5.card('M', 9.0, 30, 'uber', billedMinutes=0.02)
    time.sleep(2.2)
    _r5 = _o5.took('M', via='offers')
    eq('[offers tick] ...and a card is timed by its billed minutes, as its hold would be',
       (_r5.get('car'), _o5.status().get('holding')), ({'held': False, 'why': 'old'}, None))
    # A card nine cards back, past the slot's own memory of arrivals
    # (OFFER_ATS_MAX, 8): dated from when it came up all the same.
    _o5.card('P', 12.0, 40, 'uber')
    _pat = int(time.time() * 1000)
    time.sleep(1.2)
    for _i in range(9):
        _o5.card('q%d' % _i, 5.0, 20, 'uber')
    _o5.took('P', via='offers')
    _id5, _at5 = (str((_o5.status().get('holding') or {}).get('holdId') or 'none@0')
                  .split('@') + ['0'])[:2]
    ok_('[offers tick] a card nine cards back is dated from its own arrival (%s@%s)'
        % (_id5, _at5), _id5 == 'P' and abs(int(_at5) - _pat) < 400)
finally:
    _o5.stop()
    _o5.gone()

# A pass (accepted false) on the order in the car puts it down as the untick
# does, every panel told on the stream; ticked again it is in the car again
# (its own earlier Took is no later Took). Then a later Took of another card,
# put down since, still makes an earlier card 'later'.
_o6 = _Q(carry=False)
try:
    _ev6 = listen(_o6.base, 8)
    _settle(0.3)
    _o6.card('R', 12.0, 40, 'uber', dropoff='12 Mill St, Roswell, GA')
    _o6.took('R', via='offers')
    _s6, _u6 = post(_o6.base, '/api/offers/mark', {'id': 'R', 'accepted': False, 'via': 'offers'})
    _settle(0.3)
    eq('[offers tick] a pass there on the order in the car puts it down like Drop, by \'offers\'',
       (_o6.status().get('holding'), (_u6.get('car') or {}).get('putDown'),
        [(r.get('id'), r.get('by')) for r in _o6.rows('drop')]),
       (None, True, [('R', 'offers')]))
    ok_('[offers tick] ...and every panel is told on the stream that nothing is held',
        any(m.get('heldBy') == 'offers' and 'holding' in m and m.get('holding') is None
            for m in _ev6))
    eq('[pin log] with NUCBOX_SEARCH unset the row says so, nothing asked',
       (_o6.rows('drop') or [{}])[0].get('end'),
       {'by': None, 'why': 'no NucBox search', 'asked': None})
    _r6 = _o6.took('R', via='offers')
    eq('[offers tick] ...ticked again, it is back in the car: its own Took is not a later one',
       ((_r6.get('car') or {}).get('held'),
        str((_o6.status().get('holding') or {}).get('holdId')).split('@')[0]), (True, 'R'))
    post(_o6.base, '/api/offers/mark', {'id': 'R', 'accepted': None, 'via': 'offers'})
    _o6.card('A', 12.0, 60, 'uber')
    _o6.card('B', 9.0, 60, 'uber')
    _o6.took('B')
    post(_o6.base, '/api/delivered', {})
    _settle(0.2)
    _r6 = _o6.took('A', via='offers')
    eq('[offers tick] a card ticked after a later Took records only, that order put down since',
       (_r6.get('car'), _o6.status().get('holding')), ({'held': False, 'why': 'later'}, None))
finally:
    _o6.stop()
    _o6.gone()

# [pin log] An order restored with a refusal kept for an EARLIER dropoff text,
# its own text still being asked (a NucBox that takes the connection and never
# answers): put down now, its row says 'still asking', not the old refusal.
_hang = socket.socket()
_hang.bind(('127.0.0.1', 0))
_hang.listen(8)
_hnow = int(time.time() * 1000)
_o7 = _Q(carry=False, env={'NUCBOX_SEARCH': 'http://127.0.0.1:%d' % _hang.getsockname()[1],
                           'NUCBOX_TIMEOUT_MS': '20000'},
         holding=json.dumps({'v': 2, 'orders': [dict(
             id='W', acceptedAt=_hnow - 60000, pay=9.0, minutes=40, billedMinutes=40,
             miles=5.0, cost=1.5, dropoff='12 Mill St, Roswell, GA', card=dict(_SQ),
             endWhy='no house number', endWhyFor='99 Old St, Roswell, GA')]}))
try:
    _settle(0.5)
    post(_o7.base, '/api/delivered', {})
    _settle(0.3)
    eq('[pin log] a refusal kept for an earlier dropoff text is not this one\'s: still asking',
       ((_o7.rows('drop') or [{}])[0].get('end') or {}).get('why'), 'still asking')
finally:
    _o7.stop()
    _o7.gone()
    _hang.close()

# --- a Took from a panel behind the slot --------------------------------------
#
# The panel still shows card X when the slot has moved on to Y (its socket
# dropped and came back; /api/events replays readings, never the offer), and
# the driver ticks X: the order goes in the car from the panel's copy of X, and
# its clock starts when X came up, not when Y did.
_q10 = _Q(carry=False)
try:
    _x10 = _q10.card('X', 12.0, 30, 'uber')
    _xat = int(time.time() * 1000)
    time.sleep(1.5)
    _q10.card('Y', 8.0, 20, 'uber')
    _q10.took('X', offer=_x10)
    _h10 = _q10.status().get('holding') or {}
    _id10, _at10 = (str(_h10.get('holdId') or 'none@0').split('@') + ['0'])[:2]
    ok_('Took for the previous card dates the order from that card (%r ms before the Took)'
        % _h10.get('heldMs'),
        _id10 == 'X' and abs(int(_at10) - _xat) < 400 and (_h10.get('heldMs') or 0) >= 1400)
    eq('...and the card on the slot is still the newer one',
       (_q10.status().get('offer') or {}).get('id'), 'Y')
finally:
    _q10.stop()
    _q10.gone()

# --- carrying two, turned off with two in the car -----------------------------
#
# The flag is read off <root>/rpi/config.json (no CARRY_TWO here), so this
# server runs from a copy of the five files it is made of, beside a config of
# its own. Two orders are taken with it on; the owner turns it off. Neither
# order leaves the car for that — each stays until its own end, or Drop — and a
# Took with it off replaces the first-taken, as one order's Took always did,
# with a row, and leaves the other where it is.
_croot = tempfile.mkdtemp()
_q11 = None
try:
    for _f in ('server.js', 'advice.js', 'streets.js', 'map-view.js', 'assemble.js'):
        shutil.copy(os.path.join(ROOT, _f), _croot)
    os.mkdir(os.path.join(_croot, 'rpi'))
    # scannerEnabled() asks only that the autopilot is there; SCANNER_CMD runs
    # the fake in its place.
    open(os.path.join(_croot, 'rpi', 'autopilot.py'), 'w').close()
    _cfg11 = os.path.join(_croot, 'rpi', 'config.json')

    def _carry11(on):
        # Replaced through a rename, as the scanner writes it (save_config).
        with open(_cfg11 + '.part', 'w') as fh:
            json.dump({'settings': {'target': 25, 'carryTwo': on}}, fh)
        os.replace(_cfg11 + '.part', _cfg11)

    _carry11(True)
    _q11 = _Q(carry=None, root=_croot)
    _q11.card('A', 12.0, 120, 'uber')
    _q11.took('A')
    _q11.card('B', 9.0, 120, 'doordash')
    _q11.took('B')
    _two11 = [o.get('holdId', '').split('@')[0] for o in _q11.status().get('orders') or []]
    _carry11(False)
    _q11.emit({'alive': True, 'at': int(time.time() * 1000)})
    _settle(0.3)
    _st11 = _q11.status()
    eq('(carrying two turned off: both orders still held, and nothing put down)',
       (_two11, _st11.get('carryTwo'),
        [o.get('id') for o in json.load(open(_q11.hold)).get('orders')], _q11.rows('drop')),
       (['A', 'B'], False, ['A', 'B'], []))
    # ...and a Took with it off, which is where an order left: it replaces
    # the first-taken, as one order's Took always did, with its row, and the
    # other order stays.
    _q11.card('C', 8.0, 60, 'uber')
    _q11.took('C')
    _settle(0.3)
    eq('turning carryTwo off with two held keeps both until their own ends, and a Took '
       'then replaces only the first-taken',
       ([o.get('id') for o in json.load(open(_q11.hold)).get('orders')],
        [(r.get('id'), r.get('by'), r.get('carried')) for r in _q11.rows('drop')]),
       (['B', 'C'], [('A', 'replaced', 2)]))
finally:
    if _q11:
        _q11.stop()
        _q11.gone()
    shutil.rmtree(_croot, ignore_errors=True)

# ...and the flag itself, read off the file once while the file is unchanged.
# It is asked on every beat, reading and planner line, and was read and parsed
# each time. carryTwo() taken out of server.js's source text, with a file
# system that counts what it reads.
_CTJS = r'''
var fs = require('fs'), vm = require('vm'), path = require('path');
var src = fs.readFileSync(path.join(process.argv[2], 'server.js'), 'utf8');
var root = process.argv[3];
function grab(name) {
  var i = src.indexOf('\nfunction ' + name + '(');
  if (i === -1) throw new Error('server.js has no function ' + name);
  return src.slice(i, src.indexOf('\n}\n', i) + 3);
}
var reads = 0;
var cfs = Object.assign({}, fs, { readFileSync: function () {
  reads += 1; return fs.readFileSync.apply(fs, arguments); } });
var ctx = { fs: cfs, path: path, ROOT: root, JSON: JSON, process: { env: {} } };
vm.createContext(ctx);
var m = /\nvar carryTwoSeen = [^\n]*\n/.exec(src);
if (m) vm.runInContext(m[0], ctx);
vm.runInContext(grab('carryTwo'), ctx);
var file = path.join(root, 'rpi', 'config.json');
function put(on) {
  fs.writeFileSync(file + '.part', JSON.stringify({ settings: { carryTwo: on } }));
  fs.renameSync(file + '.part', file);
}
put(true);
var out = { on: [], reads: [] };
for (var i = 0; i < 50; i++) out.on.push(ctx.carryTwo());
out.reads.push(reads);
put(false);
for (i = 0; i < 50; i++) out.on.push(ctx.carryTwo());
out.reads.push(reads);
out.on = [out.on[0], out.on[49], out.on[50], out.on[99]];
console.log(JSON.stringify(out));
'''
_ctdir = tempfile.mkdtemp()
try:
    os.mkdir(os.path.join(_ctdir, 'rpi'))
    with open(os.path.join(_ctdir, 'ct.js'), 'w') as fh:
        fh.write(_CTJS)
    _ctr = subprocess.run(['node', os.path.join(_ctdir, 'ct.js'), ROOT, _ctdir],
                          capture_output=True, text=True, timeout=60)
    try:
        _cto = json.loads(_ctr.stdout)
    except ValueError:
        _cto = {'error': (_ctr.stderr or _ctr.stdout)[-400:]}
    eq('the carryTwo flag is read off the file once while it is unchanged, and again '
       'when it changes', (_cto.get('on'), _cto.get('reads')),
       ([True, True, False, False], [1, 2]))
finally:
    shutil.rmtree(_ctdir, ignore_errors=True)

# --- two orders restored from holding.json, and a Took -------------------------
#
# The car of the carrying-two section above, after a restart, with the flag
# off: a Took put down the first with a row, and the second with none. With it
# on, the one ending soonest goes, with its row, as before.
_now12 = int(time.time() * 1000)
_held12 = json.dumps({'v': 2, 'orders': [
    {'id': 'P', 'pay': 10.0, 'minutes': 120, 'acceptedAt': _now12 - 60000},
    {'id': 'Q', 'pay': 11.0, 'minutes': 120, 'acceptedAt': _now12 - 30000}]})
for _carry in (False, True):
    _q12 = _Q(carry=_carry, holding=_held12)
    try:
        _was12 = [o.get('id') for o in json.load(open(_q12.hold)).get('orders')]
        _q12.card('R', 9.0, 25, 'uber')
        _q12.took('R')
        _settle(0.3)
        _now_held = [o.get('id') for o in json.load(open(_q12.hold)).get('orders')]
        eq('every order a Took puts down gets a row%s' % (' (carrying two)' if _carry else ''),
           (sorted(set(_was12) - set(_now_held)),
            sorted(r.get('id') for r in _q12.rows('drop'))),
           (['P'], ['P']))
    finally:
        _q12.stop()
        _q12.gone()

# --- a card paged away from and back to ---------------------------------------
#
# The scanner keeps a card's id when the driver pages away and back
# (rpi/journal.py, RECENT_CARDS); with an order in the car its return wrote a
# second pair row for one decision.
_q14 = _Q(carry=False)
try:
    _q14.card('HELD', 12.0, 120, 'uber')
    _q14.took('HELD')
    _q14.card('A', 9.0, 20, 'doordash')
    _q14.card('B', 7.0, 18, 'uber')
    _q14.card('A', 9.0, 20, 'doordash')
    _settle(0.3)
    eq('a card paged back to is one pair row', [r.get('id') for r in _q14.rows('pair')],
       ['A', 'B'])
    eq('...and one pairing on the offers page',
       [p.get('id') for p in get(_q14.base, '/api/journal?days=1').get('pairs') or []],
       ['B', 'A'])
    post(_q14.base, '/api/delivered', {})
    _q14.card('HELD2', 11.0, 120, 'uber')
    _q14.took('HELD2')
    _q14.card('A', 9.0, 20, 'doordash')
    _settle(0.3)
    eq('...while the same card against a different order in the car is a pairing of its own',
       [r.get('id') for r in _q14.rows('pair')], ['A', 'B', 'A'])
finally:
    _q14.stop()
    _q14.gone()

# --- a scanner line the server fails on ---------------------------------------
#
# One try round the parse and the handling both: a throw anywhere in the
# handling was logged as `scanner: <the line>`, as if the scanner had printed
# it. A line whose `phase` cannot be made a string (the log line built from
# it throws) stands in for any fault of this process's own.
_q15 = _Q(carry=False)
try:
    with open(_q15.queue, 'a') as fh:
        fh.write('a line of the scanner\'s own\n')
    _q15.emit({'phase': {'toString': 0, 'valueOf': 0}, 'message': 'x'})
    _q15.card('A', 12.0, 30, 'uber')
    _log15 = _q15.log()
    ok_('a scanner line the server fails on is said as the server\'s fault, with its stack',
        'a scanner line could not be handled: TypeError' in _log15
        and 'server.js:' in _log15 and 'scanner: {"phase"' not in _log15)
    ok_('...and a line that is not JSON is still the scanner\'s own words',
        'scanner: a line of the scanner\'s own' in _log15)
finally:
    _q15.stop()
    _q15.gone()

# --- an order run out on its own clock, said on the beat ----------------------
#
# Nobody pressed anything and no reading comes between offers, so the beat
# is the panel's only word that the car is empty: it carries `holding` on the
# first beat after what is held changed, and not otherwise. A card of 0.05
# minutes, no grace: its clock ends 4.5 s after it came up.
_q13 = _Q(carry=False, env={'HOLD_GRACE_MS': '0'})
try:
    _q13.card('A', 12.0, 0.05, 'uber')
    _q13.took('A')
    _ev13 = listen(_q13.base, 9)
    time.sleep(0.3)

    def _beat13():
        _q13.emit({'alive': True, 'at': int(time.time() * 1000)})
        time.sleep(0.3)

    _beat13()
    time.sleep(5.0)
    _beat13()
    _beat13()
    time.sleep(0.3)
    _b13 = [m for m in _ev13 if m.get('alive')]
    eq('an order expiring on its own clock is said on the next beat, as nothing held, and '
       'the beat after says nothing of it',
       [('holding' in b, b.get('holding') is None) for b in _b13],
       [(True, False), (True, True), (False, True)])
    eq('...and its drop row is the expiry\'s', [r.get('by') for r in _q13.rows('drop')],
       ['expiry'])
finally:
    _q13.stop()
    _q13.gone()

# --- the window a fold reads, carried across appends --------------------------
#
# rowsFor kept every kind row in the file and walked the whole file again
# after every append, so /api/today's cost grew with the journal; and
# latestPerOffer kept one fold per floor, and /api/journal?days= asks from a
# floor that moves every millisecond. The functions themselves, taken out of
# server.js's source text into a context of their own (the file starts a
# server when it is run), against the rule they replace, written out here:
# every kind row kept, every reading of a card with one in the window.
_FOLDJS = r'''
var fs = require('fs'), vm = require('vm'), path = require('path');
var ROOT = process.argv[2];
var src = fs.readFileSync(path.join(ROOT, 'server.js'), 'utf8');
function grab(name) {
  var i = src.indexOf('\nfunction ' + name + '(');
  if (i === -1) throw new Error('server.js has no function ' + name);
  return src.slice(i, src.indexOf('\n}\n', i) + 3);
}
function grabVar(name) {
  var m = new RegExp('\\nvar ' + name + ' = [^\\n]*\\n').exec(src);
  if (!m) throw new Error('server.js has no var ' + name);
  return m[0];
}
var ctx = { Advice: require(path.join(ROOT, 'advice.js')), Set: Set, Date: Date, JSON: JSON,
            Object: Object, console: console };
vm.createContext(ctx);
['CLOCK_BELIEVABLE_AFTER', 'WINDOWS_MAX', 'windows', 'latestCache'].forEach(function (n) {
  vm.runInContext(grabVar(n), ctx);
});
['inWindow', 'foldReads', 'windowTakes', 'windowOver', 'rowsFor', 'dayFloor', 'latestPerOffer',
 'bestReading', 'latestPerOfferUncached'].forEach(function (n) { vm.runInContext(grab(n), ctx); });
function whole(rows, floor) {
  var inR = function (r) {
    var at = (typeof r.at === 'number' && isFinite(r.at)) ? r.at : 0;
    return at >= floor || at < ctx.CLOCK_BELIEVABLE_AFTER;
  };
  var wanted = {};
  rows.forEach(function (r) { if (!r.kind && r.id && inR(r)) wanted[r.id] = true; });
  return rows.filter(function (r) {
    return r.kind ? true : r.id ? !!wanted[r.id] : inR(r);
  });
}
var NOW = Date.now(), H = 3600000, floor = NOW - 2 * H;
function card(id, at, pay) {
  return { v: 1, id: id, seq: 1, at: at, firstAt: at, pay: pay, minutes: 20, miles: 4,
           perHour: 30, grossPerHour: 36, cost: 1.2, billedMinutes: 20, state: 'go',
           target: 25, band: 15, costPerMile: 0.3, legs: 2, whole: true };
}
var rows = [
  card('old', NOW - 50 * H, 9), card('cross', floor - 60000, 11),
  { v: 1, kind: 'mark', at: NOW - 49 * H, id: 'cross', accepted: true },
  { v: 1, kind: 'rule', at: NOW - 48 * H, match: { pay: 13, minutes: 20, miles: 4 }, hidden: true },
  { v: 1, kind: 'seen', at: NOW - 47 * H, id: 'seen-1', saw: 3, kept: 2 },
  { v: 1, kind: 'pair', at: NOW - 46 * H, id: 'old', held: {}, offer: {} },
  { v: 1, kind: 'screen', at: NOW - 45 * H, id: 'screen-1', text: 'x' },
  { v: 1, kind: 'drop', at: NOW - 44 * H, id: 'old', seq: 1 },
  card('cross', floor + 60000, 11.5), card('new', NOW - H, 13),
  { v: 1, kind: 'seen', at: NOW - H, id: 'seen-2', saw: 4, kept: 3 },
  { v: 1, kind: 'pair', at: NOW - H, id: 'new', held: {}, offer: {} },
  { v: 1, kind: 'sighting', at: NOW - H, id: 'sighting-1' },
  { v: 1, kind: 'visit', at: NOW - H, id: 'x#0' }, { v: 1, kind: 'planner', at: NOW - H, id: 'p' },
  { v: 1, kind: 'snap', at: NOW - H, id: 's' }, { v: 1, kind: 'newer', at: NOW - H, id: 'n' },
  { v: 1, kind: 'mark', at: NOW - H, id: 'new', accepted: false, via: 'review' }];
var out = {};
out.kinds = ctx.rowsFor(rows, floor).filter(function (r) { return r.kind; })
  .map(function (r) { return r.kind + (r.at >= floor ? '+' : '-'); });
function seenAs(f) {
  return JSON.stringify({ offers: f.filter(function (o) { return (o.at || 0) >= floor; }),
                          pairs: f.pairs.filter(function (p) { return (p.at || 0) >= floor; }),
                          seen: f.seen.filter(function (s) { return (s.at || 0) >= floor; }) });
}
// ...and across appends, as readJournal hands them over: a new array, the
// same row objects, and the new ones after. The second append is a reading
// of a card whose only reading so far was before the floor — half a card,
// which loses the vote to the whole reading only if that reading is there.
var steps = [[card('new2', NOW - 30000, 8), { v: 1, kind: 'pair', at: NOW, id: 'new2' }],
             [Object.assign(card('old', NOW - 20000, 9.25), { whole: false }),
              card('cross', floor - 30000, 11)],
             [{ v: 1, kind: 'mark', at: NOW, id: 'old', accepted: true }]];
var cur = rows;
var built = 0, over = ctx.windowOver;
ctx.windowOver = function (r, f) { built += 1; return over(r, f); };
vm.runInContext('windows = [];', ctx);
out.same = [seenAs(ctx.latestPerOfferUncached(ctx.rowsFor(cur, floor)))
            === seenAs(ctx.latestPerOfferUncached(whole(cur, floor)))];
out.built = [built];
steps.forEach(function (add) {
  cur = cur.concat(add);
  out.same.push(seenAs(ctx.latestPerOfferUncached(ctx.rowsFor(cur, floor)))
                === seenAs(ctx.latestPerOfferUncached(whole(cur, floor))));
  out.built.push(built);
});
ctx.windowOver = over;
// Two days=30 loads, a few milliseconds apart, with no append between.
var real = ctx.latestPerOfferUncached, folds = 0;
ctx.latestPerOfferUncached = function (r) { folds += 1; return real(r); };
ctx.latestPerOffer(cur, NOW - 30 * 24 * H);
ctx.latestPerOffer(cur, NOW - 30 * 24 * H + 5);
out.folds = folds;
for (var k = 1; k <= 10; k++) ctx.latestPerOffer(cur, NOW - k * 24 * H);
out.kept = vm.runInContext('latestCache.byFloor.length', ctx);
console.log(JSON.stringify(out));
'''
_fdir = tempfile.mkdtemp()
try:
    with open(os.path.join(_fdir, 'fold.js'), 'w') as fh:
        fh.write(_FOLDJS)
    _fr = subprocess.run(['node', os.path.join(_fdir, 'fold.js'), ROOT], capture_output=True,
                         text=True, timeout=60)
    try:
        _fo = json.loads(_fr.stdout)
    except ValueError:
        _fo = {'error': (_fr.stderr or _fr.stdout)[-400:]}
    eq('rowsFor keeps no kind row the fold does not read',
       _fo.get('kinds'), ['mark-', 'rule-', 'seen+', 'pair+', 'mark+'])
    eq('...and the fold over it answers as over every kind row, before and after each '
       'of three appends', _fo.get('same'), [True, True, True, True])
    eq('rowsFor carries its window across an append, and works it out afresh only when a '
       'card it left out comes back', _fo.get('built'), [1, 1, 2, 2])
    eq('two days=30 loads fold once', _fo.get('folds'), 1)
    eq('...and the folds kept are the last three', _fo.get('kept'), 3)
finally:
    shutil.rmtree(_fdir, ignore_errors=True)

# ...and through the server: /api/journal's window against All, filtered by
# hand to the same floor, before and after rows are appended under it.
_wdir = tempfile.mkdtemp()
try:
    _wj = os.path.join(_wdir, 'journal.jsonl')
    _WN = int(time.time() * 1000)
    _wfloor = _WN - 2 * 3600000
    write(_wj, [offer(1, _WN - 50 * 3600000), offer(2, _wfloor - 60000),
                {'v': 1, 'kind': 'screen', 'at': _WN - 40 * 3600000, 'id': 'screen-1'},
                {'v': 1, 'kind': 'seen', 'at': _WN - 30 * 3600000, 'id': 'seen-1', 'saw': 5,
                 'kept': 4},
                offer(3, _WN - 3600000), offer(2, _wfloor + 60000, pay=12.5),
                {'v': 1, 'kind': 'seen', 'at': _WN - 3600000, 'id': 'seen-2', 'saw': 2,
                 'kept': 1}])
    _wp, _wb = start({'SCANNER': '0'}, _wj)
    try:
        def _wsame():
            w = get(_wb, '/api/journal?since=%d&limit=0' % _wfloor)
            a = get(_wb, '/api/journal?days=0&limit=0')
            mine = [o for o in a.get('offers') or [] if (o.get('at') or 0) >= _wfloor]
            return (w.get('offers') == mine and len(mine) > 0,
                    w.get('watched'))
        _w1 = _wsame()
        write(_wj, [offer(4, _WN - 1000), offer(1, _WN - 500, pay=11.75, whole=False),
                    {'v': 1, 'kind': 'mark', 'at': _WN, 'id': 'off1', 'accepted': True}], 'a')
        _w2 = _wsame()
        eq('the windowed journal answers as All does over the same floor, before and after '
           'appends that bring an old card into it', (_w1, _w2),
           ((True, {'saw': 2, 'kept': 1}), (True, {'saw': 2, 'kept': 1})))
    finally:
        stop(_wp)
finally:
    shutil.rmtree(_wdir, ignore_errors=True)

# --- the NucBox's answers, kept by their size --------------------------------
#
# The cache held 500 answers whatever their size, and a route with the road's
# shape is up to 5,000 points. It is bounded in bytes now (NBX_CACHE_BYTES),
# oldest out first; here a bound a little over two of the fake's routes, so a
# third puts the first out and the first is asked of the NucBox again.
import urllib.parse                                            # noqa: E402
_nf = subprocess.Popen(['node', os.path.join(ROOT, 'tests', 'fake-nucbox.js')],
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
_nfb ='http://127.0.0.1:%d' % json.loads(_nf.stdout.readline())['port']
_nroutes = ['-84.5499,33.9526;-84.3880,33.7490', '-84.5499,33.9526;-84.5499,33.9830',
            '-84.5499,33.9526;-84.4500,33.8800']


def _nasks(pts):
    _all = json.loads(urllib.request.urlopen(_nfb + '/__asked', timeout=5).read())
    return len([a for a in _all if pts in urllib.parse.unquote(a)])


try:
    for _cap, _want in (('', (1, 1)), ('300', (2, 1))):
        _q16 = _Q(carry=False, env={'NUCBOX_ROUTER': _nfb, 'NUCBOX_CACHE_BYTES': _cap})
        try:
            _n0 = [_nasks(p) for p in _nroutes]
            _sizes = []
            for _p16 in _nroutes + _nroutes[:1] + _nroutes[2:]:
                _s16, _b16, _h16 = raw(_q16.base, '/api/nbx/route?points=' + _p16)
                _sizes.append(len(_b16.encode('utf-8')))
            _got16 = (_nasks(_nroutes[0]) - _n0[0], _nasks(_nroutes[2]) - _n0[2])
            if _cap:
                eq('the NucBox cache lets its oldest answer go past its size in bytes, as past '
                   'its count (answers of %s bytes)' % _sizes[:3], _got16, _want)
            else:
                eq('...and at its own size, 8 MB, keeps them all', _got16, _want)
        finally:
            _q16.stop()
            _q16.gone()
finally:
    _nf.kill()

# --- ↶ Undo of a Drop, and the shift on the phone (22 Oct 2026) ----------------
#
# The owner: "fewer hands, less friction". For UNDO_DROP_MS (10 s) after a Drop
# puts an order down, the same button reads "↶ Undo", and /api/drop-undo puts
# back exactly what the Drop took, from the snapshot taken at the press, writing
# an `undo` row of ids so the shift report reads the drop as never pressed.
# Invented orders and places throughout; the coordinates are nowhere near the
# driver.
_un = int(time.time() * 1000)
_UA = {'id': 'ud-a', 'acceptedAt': _un - 20 * 60000, 'pay': 12.5, 'minutes': 40.0,
       'miles': 5.0, 'cost': 1.5, 'app': 'uber', 'pickup': 'Larkspur Tacos',
       'dropoff': '4821 Kestrel Dr, Marietta', 'card': {'multiOrder': False},
       'endPin': {'dropoff': '4821 Kestrel Dr, Marietta', 'lat': 12.3456, 'lon': 45.6789,
                  'doorLevel': True, 'pinnedAt': _un - 60000},
       'pickupPins': [{'q': 'Larkspur Tacos', 'lat': 12.3399, 'lon': 45.6701}],
       'planner': {'stops': [{'kind': 'pickup', 'name': 'Larkspur Tacos'},
                             {'kind': 'dropoff', 'line': '4821 Kestrel Dr, Marietta'}],
                   'at': _un - 5 * 60000},
       'batch': True, 'drops': [{'line': '4821 Kestrel Dr'}, {'line': '17 Wren Way'}]}
_UB = {'id': 'ud-b', 'acceptedAt': _un - 5 * 60000, 'pay': 6.25, 'minutes': 9.0,
       'miles': 1.2, 'cost': 0.4, 'app': 'uber', 'dropoff': None, 'addOn': True,
       'of': 'ud-a@%d' % _UA['acceptedAt'], 'ofEnds': _un + 30 * 60000}


def _ujournal(path):
    # The cards and their Tooks, so the shift report has the orders to time.
    write(path, [offer(0, _UA['acceptedAt'], id='ud-a', pay=12.5, minutes=40.0, miles=5.0,
                       pickup='Larkspur Tacos', dropoff='4821 Kestrel Dr, Marietta',
                       lat=12.3456, lon=45.6789,
                       text='$12.50\n40 min (5.0 mi) total\nLarkspur Tacos\n'
                            '4821 Kestrel Dr, Marietta\nAccept'),
                 {'v': 1, 'kind': 'mark', 'id': 'ud-a', 'at': _UA['acceptedAt'] + 1000,
                  'accepted': True, 'via': 'panel'}])


def _uhold(path):
    return json.load(open(os.path.join(os.path.dirname(path), 'holding.json')))['orders']


_ud = tempfile.mkdtemp()
_uj = os.path.join(_ud, 'offers.jsonl')
_ujournal(_uj)
with open(os.path.join(_ud, 'holding.json'), 'w') as _fh:
    json.dump({'v': 2, 'orders': [_UA, _UB]}, _fh)
# A minute of GPS log, a straight drive east, so the shift's totals have fixes.
_ugps = os.path.join(_ud, 'gpslog')
os.mkdir(_ugps)
_ut0 = int(time.time()) - 15 * 60
with open(os.path.join(_ugps, time.strftime('%Y-%m-%d_%H%M', time.localtime(_ut0))
                       + '.jsonl'), 'w') as _fh:
    for _i in range(240):
        _t = _ut0 + _i
        _fh.write('%s %.6f: %s\n' % (
            time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(_t)), _t,
            json.dumps({'class': 'TPV', 'device': '/dev/ttyACM0', 'mode': 3,
                        'time': time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime(_t)),
                        'lat': 12.3456, 'lon': 45.6789 + _i * 0.0001, 'eph': 8.0,
                        'speed': 10.0})))
_up, _ub = start({'SCANNER': '0', 'GPSLOG_DIR': _ugps}, _uj)
try:
    _before = _uhold(_uj)
    eq('[drop undo] set up: a trip of two in the car, the original pinned and planned',
       [o.get('holdId') for o in (get(_ub, '/api/status').get('orders') or [])],
       ['ud-a@%d' % _UA['acceptedAt'], 'ud-b@%d' % _UB['acceptedAt']])
    _c, _d = post(_ub, '/api/delivered', {'holdIds': ['ud-a@%d' % _UA['acceptedAt']]})
    _uid = (_d.get('undo') or {}).get('id')
    eq('[drop undo] Drop answers with an Undo for ten seconds',
       (_c, bool(_uid), (_d.get('undo') or {}).get('forMs')), (200, True, 10000))
    eq('[drop undo] ...the order is down, its add-on left',
       [o.get('id') for o in _uhold(_uj)], ['ud-b'])
    _c2, _d2 = post(_ub, '/api/drop-undo', {'id': _uid})
    eq('[drop undo] Undo puts it back, and says what is in the car',
       (_c2, _d2.get('ok'), _d2.get('restored'), (_d2.get('held') or {}).get('pay'),
        [o.get('pay') for o in _d2.get('orders') or []]),
       (200, True, ['ud-a@%d' % _UA['acceptedAt']], 12.5, [12.5, 6.25]))
    eq('[drop undo] ...exactly as it was: every field of every order, its pins, planner, '
       'batch and add-on links and clock, in its place on the list',
       [{k: o.get(k) for k in f} for o, f in zip(_uhold(_uj), (_UA, _UB))], [_UA, _UB])
    _st = get(_ub, '/api/status')
    eq('[drop undo] ...and the GPS drop armed on its door again',
       ((_st.get('holding') or {}).get('holdId'), (_st.get('holding') or {}).get('endPinned')),
       ('ud-a@%d' % _UA['acceptedAt'], True))
    time.sleep(0.3)
    _urows = _rows(_uj, 'undo')
    _udrop = [r for r in _rows(_uj, 'drop') if r.get('id') == 'ud-a']
    eq('[drop undo] the Undo writes one undo row, naming the drop row it takes back',
       [(r.get('id'), r.get('undoes'), r.get('dropAt'), r.get('holdId')) for r in _urows],
       [('ud-a', 'drop', _udrop[0].get('at') if _udrop else None,
         'ud-a@%d' % _UA['acceptedAt'])])
    eq('[drop undo] ...ids and times only', sorted(_urows[0]) if _urows else None,
       ['at', 'dropAt', 'holdId', 'id', 'kind', 'seq', 'undoes', 'v'])
    # ...and again from the server's own written list (the fields it fills in
    # on an order restored at boot included): a second Drop and Undo.
    _before = _uhold(_uj)
    _cr, _dr = post(_ub, '/api/delivered', {'holdIds': ['ud-a@%d' % _UA['acceptedAt']]})
    post(_ub, '/api/drop-undo', {'id': (_dr.get('undo') or {}).get('id')})
    eq('[drop undo] ...the list the server wrote before the Drop, as it was after the Undo',
       _uhold(_uj), _before)
    time.sleep(0.2)
    eq('[drop undo] the same Undo twice is refused, and changes nothing',
       (post(_ub, '/api/drop-undo', {'id': _uid}), len(_rows(_uj, 'undo')),
        [o.get('id') for o in _uhold(_uj)]),
       ((409, {'ok': False, 'error': 'nothing to undo'}), 2, ['ud-a', 'ud-b']))
    eq('[drop undo] ...as is one with no id it gave',
       post(_ub, '/api/drop-undo', {'id': 'drop-1-1'}), (409, {'ok': False, 'error': 'nothing to undo'}))
    # The car changed under it: the add-on put down by a second Drop, and the
    # first Drop's Undo is no longer about the car there is.
    _c3, _d3 = post(_ub, '/api/delivered', {'holdIds': ['ud-a@%d' % _UA['acceptedAt']]})
    _c4, _d4 = post(_ub, '/api/delivered', {'holdIds': ['ud-b@%d' % _UB['acceptedAt']]})
    eq('[drop undo] an Undo after a later Drop is the later one\'s: the earlier is refused',
       post(_ub, '/api/drop-undo', {'id': (_d3.get('undo') or {}).get('id')})[0], 409)
    eq('[drop undo] ...and the later one puts back what IT took',
       (post(_ub, '/api/drop-undo', {'id': (_d4.get('undo') or {}).get('id')})[0],
        [o.get('id') for o in _uhold(_uj)]), (200, ['ud-b']))
    # Ten seconds, and no more: the trip's add-on dropped again and left.
    _c5, _d5 = post(_ub, '/api/delivered', {'holdIds': ['ud-b@%d' % _UB['acceptedAt']]})
    time.sleep(10.3)
    eq('[drop undo] an Undo after its ten seconds is refused, and nothing comes back',
       (post(_ub, '/api/drop-undo', {'id': (_d5.get('undo') or {}).get('id')}),
        os.path.exists(os.path.join(_ud, 'holding.json')), len(_rows(_uj, 'undo'))),
       ((409, {'ok': False, 'error': 'too late'}), False, 3))
    eq('[drop undo] a Drop with nothing in the car offers no Undo',
       'undo' in post(_ub, '/api/delivered', {})[1], False)

    # The shift, on the phone: today's report through the server.
    _sc, _sh, _ = raw(_ub, '/api/shift')
    _sj = json.loads(_sh) if _sc == 200 else {}
    _srep = _sj.get('report') or {}
    _sa = [o for o in _srep.get('orders') or []]
    eq('[shift] /api/shift answers today\'s shift as the report computes it',
       (_sc, _sj.get('ok'), _sj.get('day'), sorted(_srep)),
       (200, True, time.strftime('%Y-%m-%d', time.localtime(time.time() - 4 * 3600)),
        ['day', 'end', 'gps', 'orders', 'pinning', 'start', 'summary', 'totals',
         'unreadable']))
    _sdrops = [r for r in _rows(_uj, 'drop') if r.get('id') == 'ud-a']
    eq('[shift] ...an undone Drop is no end: the order ends at the Drop that stood',
       [(o.get('how'), o.get('end'), o.get('pay'), o.get('cardMinutes')) for o in _sa],
       [('chooser', _sdrops[-1].get('at') if _sdrops else None, 12.5, 40.0)])
    eq('[shift] ...(the premise: three drop rows for it, the first two taken back)',
       [r.get('at') for r in _sdrops][:2],
       [r.get('dropAt') for r in _rows(_uj, 'undo') if r.get('id') == 'ud-a'])
    eq('[shift] ...and the totals off the GPS log: rig on at its first fix, the miles driven',
       ((_srep.get('totals') or {}).get('on'),
        round((_srep.get('totals') or {}).get('miles') or 0, 1)),
       (_ut0 * 1000.0, round(239 * 0.0001 * 111320 * math.cos(math.radians(12.3456))
                             / 1609.344, 1)))
    eq('[shift] ...and its Pinning line, in the report\'s words',
       [o.get('pin') for o in _sa][:1], ['end pinned by page; pickups 1 pinned'])
    eq('[shift] no address, no place and no coordinate leaves the server',
       [w for w in ('Kestrel', 'Larkspur', 'Wren', 'Marietta', '12.34', '45.67') if w in _sh],
       [])
    eq('[shift] a second ask inside the cache is the same answer, not a second run',
       json.loads(raw(_ub, '/api/shift')[1]).get('at'), _sj.get('at'))
    eq('[shift] a day that is not YYYY-MM-DD is refused',
       raw(_ub, '/api/shift?day=yesterday')[0], 400)
    _sx = json.loads(raw(_ub, '/api/shift?day=2001-01-01')[1])
    eq('[shift] ...and another day is that day\'s, with nothing in it',
       (_sx.get('day'), (_sx.get('report') or {}).get('orders')), ('2001-01-01', []))
finally:
    stop(_up)
shutil.rmtree(_ud, ignore_errors=True)
# ...and a car changed since the Drop by something that offers no Undo of its
# own: the offers page's untick of the other order. The Undo is refused, and
# the order the Drop took stays down.
_ud2 = tempfile.mkdtemp()
_uj2 = os.path.join(_ud2, 'offers.jsonl')
open(_uj2, 'w').close()
with open(os.path.join(_ud2, 'holding.json'), 'w') as _fh:
    json.dump({'v': 2, 'orders': [dict(_UA, id='uc-a'),
                                  dict(_UB, id='uc-b', of='uc-a@%d' % _UA['acceptedAt'])]}, _fh)
_up2, _ub2 = start({'SCANNER': '0'}, _uj2)
try:
    _d6 = post(_ub2, '/api/delivered', {'holdIds': ['uc-a@%d' % _UA['acceptedAt']]})[1]
    post(_ub2, '/api/offers/mark', {'id': 'uc-b', 'accepted': None, 'via': 'offers'})
    time.sleep(0.2)
    eq('[drop undo] an Undo once the car has changed some other way is refused, and the '
       'order stays down',
       (post(_ub2, '/api/drop-undo', {'id': (_d6.get('undo') or {}).get('id')}),
        get(_ub2, '/api/status').get('holding'), len(_rows(_uj2, 'undo'))),
       ((409, {'ok': False, 'error': 'the car changed'}), None, 0))
finally:
    stop(_up2)
shutil.rmtree(_ud2, ignore_errors=True)

# --- what $/mi to accept, read off the record (24 Oct 2026) -----------------
# The owner: "help me decide what $/mi I should accept ... $/mi is always
# correct", then all four tables. /api/journal gains perMileSeen, cardVsReal,
# realByPerMile and refigured (server.js perMileSeen and its neighbours):
# descriptions of the window, counts and dollars, no id and no place. Every
# offer below is invented, at one evening's hour so the time-of-day block is
# one block. Uber: ten 2-mile cards paying $2..$20 ($1..$10/mi) and three
# 10-mile cards ($1, $1.50, $2/mi); five of the 2-mile cards taken and put
# down by the GPS at 22..30 min against a 20-min card (the first with another
# order in the car), one by a Drop press, one replaced, and one an add-on put
# down by the GPS an hour after its Took. DoorDash: five 5-mile cards, all taken and put down by the
# app's screen at 24..33 min against a 30-min card.
import datetime as _pmdt
_pmday = _pmdt.datetime.now().replace(hour=19, minute=5, second=0, microsecond=0) \
    - _pmdt.timedelta(days=1)
_PM0 = int(_pmday.timestamp() * 1000)


def _pm_offer(oid, app, pay, miles, minutes, per_hour, k):
    return offer(0, _PM0 + k * 60000, id=oid, app=app, pay=pay, miles=miles,
                 minutes=minutes, billedMinutes=minutes, perHour=per_hour)


def _pm_drop(oid, by, real_min, k):
    took = _PM0 + k * 60000 + 30000
    return {'v': 1, 'kind': 'drop', 'id': oid, 'seq': 1, 'by': by,
            'acceptedAt': took, 'at': took + int(real_min * 60000)}


_pm_uber_ph = [26, 28, 29, 31, 40, 10, 12, 20, 24, 25, 50, 15, 27]
_pm_rows = []
for _i in range(10):
    _pm_rows.append(_pm_offer('pmu%d' % _i, 'uber', 2.0 * (_i + 1), 2.0, 20.0,
                              _pm_uber_ph[_i], _i))
for _j, _pay in enumerate([10.0, 15.0, 20.0]):
    _pm_rows.append(_pm_offer('pmu%d' % (10 + _j), 'uber', _pay, 10.0, 20.0,
                              _pm_uber_ph[10 + _j], 10 + _j))
for _i, _ph in enumerate([23, 24, 20, 30, 10]):
    _pm_rows.append(_pm_offer('pmd%d' % _i, 'doordash', 10.0, 5.0, 30.0, _ph, 20 + _i))
for _i, _real in enumerate([22, 24, 24, 26, 30]):
    _pm_rows.append(_pm_drop('pmu%d' % _i, 'gps', _real, _i))
_pm_rows[-5]['carried'] = 2
_pm_rows.append(_pm_drop('pmu5', 'drop', 12, 5))
_pm_rows.append(_pm_drop('pmu6', 'replaced', 3, 6))
_pm_rows.append(dict(_pm_drop('pmu7', 'gps', 60, 7), addon=True))
for _i, _real in enumerate([24, 24, 27, 30, 33]):
    _pm_rows.append(_pm_drop('pmd%d' % _i, 'screen', _real, 20 + _i))
_pmd = tempfile.mkdtemp()
write(os.path.join(_pmd, 'j.jsonl'), _pm_rows)
_pmproc, _pmbase = start({'SCANNER': '0'}, os.path.join(_pmd, 'j.jsonl'))
try:
    _pm = get(_pmbase, '/api/journal?days=0')
finally:
    stop(_pmproc)
_seen = _pm.get('perMileSeen') or {}
_apps = {a.get('app'): a for a in _seen.get('apps') or []}
eq('[per mile] where an offer\'s $/mi sits: every counted offer, by app, and the minimum said',
   (_seen.get('n'), _seen.get('min'), sorted(_apps)), (18, 8, ['doordash', 'uber']))
_u = _apps.get('uber') or {}
eq('[per mile] ...Uber\'s 13 offers, p25/p50/p75/p90 of pay over the card\'s miles',
   _u.get('all'), {'n': 13, 'p25': 2.0, 'p50': 4.0, 'p75': 7.0, 'p90': 8.8})
_ul = {c.get('band'): c for c in _u.get('lengths') or []}
eq('[per mile] ...the four trip lengths, each with its count',
   [(c.get('band'), c.get('n')) for c in _u.get('lengths') or []],
   [('under 4 mi', 10), ('4-8 mi', 0), ('8-12 mi', 3), ('12+ mi', 0)])
eq('[per mile] ...a length with 8 or more has its spread',
   _ul.get('under 4 mi'), {'band': 'under 4 mi', 'n': 10, 'p25': 3.25, 'p50': 5.5,
                           'p75': 7.75, 'p90': 9.1})
eq('[per mile] ...and one under 8 its count and no figures',
   _ul.get('8-12 mi'), {'band': '8-12 mi', 'n': 3, 'p25': None, 'p50': None,
                        'p75': None, 'p90': None})
eq('[per mile] ...by time of day, only the blocks the app was seen in',
   [(b.get('block'), b.get('n'), b.get('p50')) for b in _u.get('blocks') or []],
   [('6–9pm', 13, 4.0)])
eq('[per mile] ...DoorDash\'s 5 are too few for any figure',
   (_apps.get('doordash') or {}).get('all'),
   {'n': 5, 'p25': None, 'p50': None, 'p75': None, 'p90': None})
_cvr = _pm.get('cardVsReal') or {}
eq('[card vs real] orders put down at the door only: the Drop press counted out, '
   'the replaced one not at all; no driven miles on this route',
   (_cvr.get('n'), _cvr.get('notAtDoor'), _cvr.get('miles')), (10, 1, None))
eq('[card vs real] ...an add-on left out and counted (its card\'s minutes are an '
   'increment), one carried with another kept and counted',
   (_cvr.get('addons'), _cvr.get('together')), (1, 1))
eq('[card vs real] ...and the orders taken say how many were in the car at the drop',
   sorted((t.get('id'), t.get('carried'), t.get('addon')) for t in _pm.get('taken') or []
          if t.get('id') in ('pmu0', 'pmu1', 'pmu7')),
   [('pmu0', 2, False), ('pmu1', 1, False), ('pmu7', 1, True)])
eq('[card vs real] ...per app: the median real/card, its middle half, the minutes over',
   [(a.get('app'), a.get('n'), a.get('ratio'), a.get('ratioP25'), a.get('ratioP75'),
     a.get('overMin')) for a in _cvr.get('apps') or []],
   [('doordash', 5, 0.9, 0.8, 1.0, -3.0), ('uber', 5, 1.2, 1.2, 1.3, 4.0)])
_rpm = _pm.get('realByPerMile') or {}
eq('[real by $/mi] pay over the real hours, by the card\'s $/mi band, with n and the median',
   [(b.get('band'), b.get('n'), b.get('median')) for b in _rpm.get('bands') or []],
   [('under $1/mi', 0, None), ('$1-1.50/mi', 1, 5.45), ('$1.50-2/mi', 0, None),
    ('$2+/mi', 9, 20.0)])
_rf = _pm.get('refigured') or {}
eq('[refigured] each offer\'s $/hr with its app\'s measured ratio: how many cross the '
   'line each way',
   [(a.get('app'), a.get('runs'), a.get('ratio'), a.get('n'), a.get('toPass'),
     a.get('toAccept')) for a in _rf.get('apps') or []],
   [('doordash', 5, 0.9, 5, 0, 2), ('uber', 5, 1.2, 13, 5, 0)])
eq('[refigured] ...the minimum said and the one line every row was judged on',
   (_rf.get('minRuns'), _rf.get('target')), (5, 25))
eq('[refigured] ...and nothing moved: every offer\'s own verdict and rate as written',
   sorted((o.get('id'), o.get('perHour'), o.get('state')) for o in _pm.get('offers') or []),
   sorted((r['id'], r['perHour'], r['state']) for r in _pm_rows if 'kind' not in r))
_pm_out = json.dumps({k: _pm.get(k) for k in ('perMileSeen', 'cardVsReal', 'realByPerMile',
                                             'refigured')})
no_('[per mile] ...and no id, place or coordinate in the four fields',
    any(w in _pm_out for w in ('pmu', 'pmd', 'lat', 'lon', 'places', 'pickup', 'dropoff')))

# --- what to aim for, the offers page's Targets box (30 Oct 2026) -----------
# The owner: "the best areas to work in and realistic $/hr and $/mile to
# target based on the data". /api/journal gains `targets` (server.js
# targetsOut, Advice.targets; tests/advice.test.js checks the arithmetic in
# depth). Over the same invented evening: 18 counted offers, under the 30 a
# block needs for percentiles; 10 timed takes (5 Uber by the GPS, 5 DoorDash
# by the screen; the Drop press, the replaced one and the add-on left out),
# their $/hr net of each card's $1.20 cost; 9 offers at or over the $25 line,
# their pay over the card's miles $1, $1, $2, $2, $2, $3, $4, $5, $10.
_tg = _pm.get('targets') or {}
_tg_blocks = {b.get('name'): b for b in _tg.get('blocks') or []}
_tg_eve = _tg_blocks.get('6–9pm') or {}
_tg_real = sorted([(pay - 1.2) / (m / 60.0) for pay, m in
                   zip([2, 4, 6, 8, 10], [22, 24, 24, 26, 30])]
                  + [(10 - 1.2) / (m / 60.0) for m in [24, 24, 27, 30, 33]])
eq('[targets] one block, the line the page judges by, and the floors said',
   (sorted(_tg_blocks), _tg.get('target'), _tg.get('floors')),
   (['6–9pm'], 25, {'offers': 30, 'timed': 5, 'cleared': 8, 'town': 8, 'townDays': 2}))
eq('[targets] ...18 offers, under 30: no percentiles',
   (_tg_eve.get('offers'), _tg_eve.get('p50'), _tg_eve.get('p90')), (18, None, None))
eq('[targets] ...the timed takes (at the door; a press, a replaced one and an add-on out), '
   'their median $/hr net of the card\'s cost',
   (_tg_eve.get('timed'), _tg_eve.get('real')),
   (10, round((_tg_real[4] + _tg_real[5]) / 2, 2)))
eq('[targets] ...the $/mi of the offers that cleared the $25 line: n, median, P75',
   (_tg_eve.get('cleared'), _tg_eve.get('ppm50'), _tg_eve.get('ppm75')), (9, 2.0, 4.0))
eq('[targets] ...the replay is the advice\'s, and 18 offers is not enough for it',
   ((_tg.get('replay') or {}).get('ready'), (_tg.get('replay') or {}).get('reason')), (False, 'thin'))
_tg_lines = _tg.get('lines') or {}
ok_('[targets] ...said in plain lines: the block, its takes, its $/mi, the replay (%r)'
    % (_tg_lines.get('rate') or [None])[-1:],
    any(l.startswith('6–9pm: not enough offers yet for percentiles (18 of 30); your timed takes '
                     'earned a median $') and 'offers that cleared your $25 line had a median $2.00/mi, '
                     'top quarter $4.00/mi (n=9)' in l for l in _tg_lines.get('rate') or [])
    and any(l.startswith('The replay\'s best $/hr line: not enough yet') for l in _tg_lines.get('rate') or []))
ok_('[targets] ...towns off the card only: none printed, so not enough yet (%r)' % _tg_lines.get('areas'),
    (_tg_lines.get('areas') or [''])[0].startswith('All hours (hours held): not enough yet'))
ok_('[targets] ...and the notes: one line for all hours, $/mi earned less',
    'not one per block' in ' '.join(_tg_lines.get('notes') or [])
    and '24% less' in ' '.join(_tg_lines.get('notes') or []))
no_('[targets] ...no id, coordinate or address in it',
    any(w in json.dumps(_tg) for w in ('pmu', 'pmd', 'lat', 'lon', 'pickup', 'dropoff')))

# An app with too few orders measured is not re-figured, and says how many it
# has; an empty journal says nothing at all.
_pm_few = [r for r in _pm_rows if r.get('id') != 'pmu4']
write(os.path.join(_pmd, 'few.jsonl'), _pm_few)
write(os.path.join(_pmd, 'none.jsonl'), [])
_pmproc, _pmbase = start({'SCANNER': '0'}, os.path.join(_pmd, 'few.jsonl'))
try:
    _few = get(_pmbase, '/api/journal?days=0')
finally:
    stop(_pmproc)
eq('[refigured] under 5 orders at the door an app is not re-figured, its count kept',
   [(a.get('app'), a.get('runs'), a.get('ratio'), a.get('n'))
    for a in (_few.get('refigured') or {}).get('apps') or []],
   [('doordash', 5, 0.9, 5), ('uber', 4, None, 0)])
_pmproc, _pmbase = start({'SCANNER': '0'}, os.path.join(_pmd, 'none.jsonl'))
try:
    _none = get(_pmbase, '/api/journal?days=0')
finally:
    stop(_pmproc)
eq('[targets] an empty journal: no blocks, nothing timed, the replay not ready',
   ((_none.get('targets') or {}).get('blocks'), ((_none.get('targets') or {}).get('overall') or {}).get('timed'),
    ((_none.get('targets') or {}).get('replay') or {}).get('ready')),
   ([], 0, False))
eq('[per mile] an empty journal: four empty tables',
   ((_none.get('perMileSeen') or {}).get('apps'), (_none.get('cardVsReal') or {}).get('apps'),
    [b.get('n') for b in (_none.get('realByPerMile') or {}).get('bands') or []],
    (_none.get('refigured') or {}).get('apps')),
   ([], [], [0, 0, 0, 0], []))
shutil.rmtree(_pmd, ignore_errors=True)


# --- the GPS logs are tidied when the server starts ---------------------------
#
# tools/gpslog_tidy.py had to be added to an untracked Start.sh by hand, so a
# pull never brought it. server.js now runs it once at start on GPSLOG_DIR.
def _glog(d, name, age_s, body='{"class":"TPV"}\n'):
    p = os.path.join(d, name)
    with open(p, 'w') as fh:
        fh.write(body * 50)
    t = time.time() - age_s
    os.utime(p, (t, t))
    return p


def _gtidied(d, want, seconds=15):
    for _ in range(int(seconds * 10)):
        if want(sorted(os.listdir(d))):
            return sorted(os.listdir(d))
        time.sleep(0.1)
    return sorted(os.listdir(d))


_gd = tempfile.mkdtemp()
_glog(_gd, '2026-10-12_1510.jsonl', 3 * 3600)
_glog(_gd, '2026-10-12_2114.jsonl', 2 * 3600)
_gproc, _gbase = _start_loud({'SCANNER': '0', 'GPSLOG_DIR': _gd}, os.path.join(_gd, 'j.jsonl'))
try:
    _gafter = _gtidied(_gd, lambda names: '2026-10-12_1510.jsonl.gz' in names
                       and '2026-10-12_1510.jsonl' not in names)
    eq('the server tidies the GPS logs when it starts: the finished log is compressed, '
       'the newest left for gpspipe', [n for n in _gafter if n.startswith('2026')],
       ['2026-10-12_1510.jsonl.gz', '2026-10-12_2114.jsonl'])
    # The line is said when the tidy exits, a moment after its last rename.
    time.sleep(1.5)
finally:
    stop(_gproc)
_gsaid = _gproc.stdout.read() if _gproc.stdout else ''
ok_('...and says what it did on its own line', 'gps logs: ' in _gsaid)

_gd2 = tempfile.mkdtemp()
_glog(_gd2, '2026-10-12_1510.jsonl', 3 * 3600)
_glog(_gd2, '2026-10-12_2114.jsonl', 2 * 3600)
_gproc2, _gbase2 = start({'SCANNER': '0', 'GPSLOG_DIR': ''}, os.path.join(_gd2, 'j.jsonl'))
try:
    time.sleep(2)
    eq('GPSLOG_DIR set empty turns the tidy off',
       sorted(n for n in os.listdir(_gd2) if n.startswith('2026')),
       ['2026-10-12_1510.jsonl', '2026-10-12_2114.jsonl'])
finally:
    stop(_gproc2)

_gproc3, _gbase3 = start({'SCANNER': '0', 'GPSLOG_DIR': os.path.join(_gd2, 'nowhere')},
                         os.path.join(_gd2, 'j3.jsonl'))
try:
    ok_('...and a GPSLOG_DIR that is not there leaves the server up',
        get(_gbase3, '/api/status') is not None)
finally:
    stop(_gproc3)
shutil.rmtree(_gd, ignore_errors=True)
shutil.rmtree(_gd2, ignore_errors=True)

# The places report (tools/places_report.js), served from its own folder
# outside the repo at /places/ (the owner, 25 Oct): its page and its tables,
# confined to that folder, and nothing where no report was written.
_pd = tempfile.mkdtemp()
_prep = os.path.join(_pd, 'report')
os.makedirs(_prep)
with open(os.path.join(_prep, 'index.html'), 'w') as fh:
    fh.write('<h1>Where the good offers start</h1>')
with open(os.path.join(_prep, 'places.csv'), 'w') as fh:
    fh.write('place,n\nPho Corner,31\n')
with open(os.path.join(_prep, 'notes.js'), 'w') as fh:
    fh.write('x')
with open(os.path.join(_pd, 'secret.html'), 'w') as fh:
    fh.write('outside')
os.symlink(os.path.join(_pd, 'secret.html'), os.path.join(_prep, 'away.html'))
_pproc, _pbase = start({'SCANNER': '0', 'PLACES_REPORT_DIR': _prep},
                       os.path.join(_pd, 'j.jsonl'))
try:
    _pi = raw(_pbase, '/places/')
    eq('[places] /places/ serves the report\'s page',
       (_pi[0], 'good offers' in _pi[1], _pi[2].get('content-type', '').split(';')[0]),
       (200, True, 'text/html'))
    _pc = raw(_pbase, '/places/places.csv')
    eq('[places] ...and its tables, as CSV',
       (_pc[0], _pc[2].get('content-type', '').split(';')[0], 'Pho Corner' in _pc[1]),
       (200, 'text/csv', True))
    eq('[places] ...and no other kind of file in its folder',
       raw(_pbase, '/places/notes.js')[0], 404)
    eq('[places] ...nor anything outside it, by an encoded step up or a link',
       (raw(_pbase, '/places/%2e%2e/secret.html')[0], raw(_pbase, '/places/away.html')[0]),
       (403, 403))
    try:
        _pr = urllib.request.build_opener(type('NoRedirect', (urllib.request.HTTPRedirectHandler,),
                                               {'redirect_request': lambda *a, **k: None}))
        _pr.open(_pbase + '/places', timeout=5)
        _pwhere = None
    except urllib.error.HTTPError as e:
        _pwhere = (e.code, e.headers.get('Location'))
    eq('[places] /places goes to /places/, so the page\'s own links resolve',
       _pwhere, (302, '/places/'))
finally:
    stop(_pproc)
_pproc2, _pbase2 = start({'SCANNER': '0', 'PLACES_REPORT_DIR': os.path.join(_pd, 'none')},
                         os.path.join(_pd, 'j2.jsonl'))
try:
    eq('[places] a server with no report written answers not found',
       raw(_pbase2, '/places/')[0], 404)
    _pj = raw(_pbase2, '/journal.html')[1]
    ok_('[places] the offers page links the report, hidden until it answers',
        'id="toPlaces" hidden' in _pj and "fetch('places/index.html'" in _pj)
finally:
    stop(_pproc2)
shutil.rmtree(_pd, ignore_errors=True)

# --- a dropped order finished in the background (29 Oct 2026) -------------------
#
# The owner: "I do drop deliveries early to avoid it computing the value for
# incoming deliveries that won't be stacked onto the order I am running, could
# it let me drop it so the computing is treated normally but track the GPS
# points?" A press of Drop (or the chooser's) puts the order down exactly as
# before; server.js then keeps a watch (finishing.json beside the journal) and
# writes one `finished` row when the GPS sees the car get there: at the pinned
# door by the GPS drop's own arrival rule ('door'), the first stop near an
# approximate end ('area'), or with no end the first stop once the car has
# moved 0.2 mi from the press ('stop'). Nothing else: no panel word, no drop of
# any order in the car. A fake scanner of its own, as the GPS drop's above;
# every coordinate invented, in open country.
_fdir = tempfile.mkdtemp()
_fscan = os.path.join(_fdir, 'beats.py')
with open(_fscan, 'w') as _fh:
    _fh.write(_FSCAN_SRC)
_fseq = [0]


def _fbeats(fixes):
    n = _fseq[0]
    _fseq[0] += 1
    p = os.path.join(_fdir, 'beats-%d.json' % n)
    with open(p + '.tmp', 'w') as fh:
        json.dump(fixes, fh)
    os.rename(p + '.tmp', p)
    for _ in range(400):
        if os.path.exists(os.path.join(_fdir, 'done-%d' % n)):
            break
        time.sleep(0.05)
    time.sleep(0.2)


def _ff(dlat, dlon=0.0):
    return {'lat': _PIN[0] + dlat, 'lon': _PIN[1] + dlon, 'gpsAge': 0.1, 'gpsErr': 25.0,
            'gpsMode': 3, 'gpsOk': True, 'gpsWhy': None, 'freshFor': 10.0}


def _fstay(dlat, dlon=0.0, n=7):
    return [_ff(dlat, dlon)] * n       # 1.5 s at one spot: past the 1 s dwell


def _ftook(base, oid, minutes=40.0, dropoff=_DOOR):
    post(base, '/api/offers/mark', {
        'id': oid, 'accepted': True,
        'offer': {'id': oid, 'pay': 12.0, 'minutes': minutes, 'billedMinutes': minutes,
                  'miles': 5.0, 'cost': 1.75, 'dropoff': dropoff, 'multiOrder': False}})
    return (get(base, '/api/status').get('holding') or {})


def _frows(path, kind, oid=None):
    rows = [json.loads(l) for l in open(path) if l.strip()]
    return [r for r in rows if r.get('kind') == kind and (oid is None or r.get('id') == oid)]


def _fwatch(path):
    try:
        return json.load(open(os.path.join(os.path.dirname(path), 'finishing.json')))['watches']
    except (OSError, ValueError):
        return []


_FENV = {'SCANNER': '1', 'SCANNER_CMD': sys.executable, 'SCANNER_ARGS': _fscan,
         'GPS_DWELL_MS': '1000'}
_fj = os.path.join(_fdir, 'offers.jsonl')
open(_fj, 'w').close()
_fp, _fb = start(_FENV, _fj)
try:
    # A door pinned, Drop pressed on the way: the order is down for everything
    # that computes, and its watch is kept.
    _h = _ftook(_fb, 'fin-door')
    _pin(_fb, _h)
    _fbeats([_ff(0.02)] * 2)
    _c, _d = post(_fb, '/api/delivered', {})
    _fdrop = _frows(_fj, 'drop', 'fin-door')
    eq('[finish] Drop puts the order down exactly as before: no order in the car, one drop row '
       'with no `by`, an Undo offered',
       (_c, _holding(_fb), [r.get('by') for r in _fdrop], bool(_d.get('undo'))),
       (200, None, [None], True))
    eq('[finish] ...and a watch is kept for it, at its door, until its own clock runs out',
       [(w.get('holdId'), (w.get('to') or {}).get('kind'), w.get('dropAt'), w.get('by'))
        for w in _fwatch(_fj)], [(_h.get('holdId'), 'door', _fdrop[0]['at'], 'drop')])
    # A new order taken while the old one is being finished is held alone: the
    # watch is not in the car, and its door puts the new one down for nothing.
    _h2 = _ftook(_fb, 'fin-next', dropoff='17 Wren Way, Marietta')
    _st = get(_fb, '/api/status')
    eq('[finish] a watch is not an order in the car: a new Took is held alone',
       ((_st.get('holding') or {}).get('holdId'), len(_st.get('orders') or [None])),
       (_h2.get('holdId'), 1))
    _ev = listen(_fb, 3)
    time.sleep(0.3)
    _fbeats(_fstay(_IN))
    _fin = _frows(_fj, 'finished', 'fin-door')
    eq('[finish] the car stops at the dropped order\'s door: one finished row, by the door',
       [(r.get('how'), r.get('holdId'), r.get('dropAt')) for r in _fin],
       [('door', _h.get('holdId'), _fdrop[0]['at'])])
    eq('[finish] ...ids and times only: {v, kind, at, id, seq, holdId, how, dropAt}, seq its at, '
       'at after the press',
       [(sorted(r), r['seq'] == r['at'], r['at'] >= r['dropAt']) for r in _fin],
       [(['at', 'dropAt', 'holdId', 'how', 'id', 'kind', 'seq', 'v'], True, True)])
    eq('[finish] ...and nothing else: the new order still held, no drop row for it, the watch gone',
       ((_holding(_fb) or {}).get('holdId'), _frows(_fj, 'drop', 'fin-next'), _fwatch(_fj)),
       (_h2.get('holdId'), [], []))
    no_('[finish] ...and the panel is told nothing of it (no finished word on the stream)',
        any('finished' in json.dumps(m) or 'finish' in m for m in _ev))
    # No end at all: the first stop once the car is 0.2 mi from the press.
    # The press is made here, at the old door (the last good fix).
    _c, _d = post(_fb, '/api/delivered', {})
    eq('[finish] an order with no end pinned is watched with no end',
       [(w.get('holdId'), (w.get('to') or {}).get('kind')) for w in _fwatch(_fj)],
       [(_h2.get('holdId'), 'none')])
    _fbeats(_fstay(_IN, n=9))
    eq('[finish] ...a stop where the press was made does not finish it',
       _frows(_fj, 'finished', 'fin-next'), [])
    _fbeats(_fstay(_IN + 0.0025, n=9))      # ~245 m on: not yet 0.2 mi
    eq('[finish] ...nor one before the car has gone 0.2 mi', _frows(_fj, 'finished', 'fin-next'), [])
    _fbeats(_fstay(_IN + 0.0045))           # ~500 m (0.31 mi) on, and stopped
    eq('[finish] ...the first stop after moving 0.2 mi does, `how: stop` (the weakest)',
       [r.get('how') for r in _frows(_fj, 'finished', 'fin-next')], ['stop'])
    eq('[finish] ...and no finish ever wrote a drop row', len(_frows(_fj, 'drop')), 2)
finally:
    stop(_fp)

# An approximate end (refuseHeldEnd's endArea), Undo, the window, a restart.
# The orders are put in the car the way a restart restores them, holding.json.
_fn = int(time.time() * 1000)
_fdir2 = tempfile.mkdtemp()
_fj2 = os.path.join(_fdir2, 'offers.jsonl')
open(_fj2, 'w').close()
_FAREA = {'id': 'fin-area', 'acceptedAt': _fn - 60000, 'pay': 9.0, 'minutes': 40.0,
          'miles': 4.0, 'cost': 1.0, 'app': 'uber', 'dropoff': 'Larch Ct, Marietta',
          'card': {'multiOrder': False}, 'endWhy': 'no door number',
          'endWhyFor': 'Larch Ct, Marietta',
          'endArea': {'lat': _PIN[0] + 0.03, 'lon': _PIN[1], 'approx': True, 'n': 3,
                      'miles': 0.1}}
with open(os.path.join(_fdir2, 'holding.json'), 'w') as _fh:
    json.dump({'v': 2, 'orders': [_FAREA]}, _fh)
# The scanner of the first server counts on from where it stopped.
for _f in os.listdir(_fdir):
    if _f.startswith(('beats-', 'done-', 'next')):
        os.remove(os.path.join(_fdir, _f))
_fseq[0] = 0
_FENV2 = dict(_FENV, HOLD_GRACE_MS='0')
_fp, _fb = start(_FENV2, _fj2)
try:
    _fbeats([_ff(0.0)] * 2)
    post(_fb, '/api/delivered', {})
    eq('[finish] an end refused with an approximate area is watched as that area, 150 m round',
       [((w.get('to') or {}).get('kind'), (w.get('to') or {}).get('m')) for w in _fwatch(_fj2)],
       [('area', 150)])
    _fbeats(_fstay(0.03 + 0.0027))          # stopped ~300 m from the area
    eq('[finish] ...a stop 300 m from the area does not finish it', _frows(_fj2, 'finished'), [])
    _fbeats(_fstay(0.03 + 0.0007))          # stopped ~80 m from it
    eq('[finish] ...one 80 m from it does, `how: area`',
       [(r.get('id'), r.get('how')) for r in _frows(_fj2, 'finished')], [('fin-area', 'area')])

    # ↶ Undo cancels the watch its Drop opened: the order is back in the car,
    # and its door is the GPS drop's again, not a finish.
    _h = _ftook(_fb, 'fin-undo')
    _pin(_fb, _h)
    _c, _d = post(_fb, '/api/delivered', {})
    eq('[finish] Drop opens a watch...', [w.get('holdId') for w in _fwatch(_fj2)], [_h.get('holdId')])
    _c, _u = post(_fb, '/api/drop-undo', {'id': (_d.get('undo') or {}).get('id')})
    eq('[finish] ...↶ Undo puts the order back and the watch is gone',
       (_c, (_holding(_fb) or {}).get('holdId'), _fwatch(_fj2)), (200, _h.get('holdId'), []))
    _fbeats(_fstay(_IN))
    eq('[finish] ...so the car at its door is an arrival, not a finished row',
       (bool((_holding(_fb) or {}).get('arrived')), _frows(_fj2, 'finished', 'fin-undo')),
       (True, []))
    post(_fb, '/api/delivered', {})
    eq('[finish] ...and a Drop pressed AT the door (arrived) opens no watch: the press is the end',
       _fwatch(_fj2), [])

    # The window: the order's own clock (here 0.05 min x 1.5, no grace). A
    # stop after it finishes nothing, and the watch is forgotten.
    _h = _ftook(_fb, 'fin-late', minutes=0.05)
    _pin(_fb, _h)
    _fbeats([_ff(0.02)] * 2)
    post(_fb, '/api/delivered', {})
    _fw = [w.get('holdId') for w in _fwatch(_fj2)]
    time.sleep(4.8)
    _fbeats(_fstay(_IN))
    eq('[finish] a watch past its window writes no row and is forgotten',
       (_fw, _frows(_fj2, 'finished', 'fin-late'), _fwatch(_fj2)), ([_h.get('holdId')], [], []))

    # A restart keeps the watch (finishing.json), and finishes it after.
    _h = _ftook(_fb, 'fin-boot')
    _pin(_fb, _h)
    _fbeats([_ff(0.02)] * 2)
    post(_fb, '/api/delivered', {})
finally:
    stop(_fp)
eq('[finish] the watch is on file across a restart',
   [w.get('holdId') for w in _fwatch(_fj2)], [_h.get('holdId')])
_fp, _fb = start(_FENV2, _fj2)
try:
    eq('[finish] ...the restarted server holds nothing in the car for it',
       _holding(_fb), None)
    _fbeats(_fstay(_IN))
    eq('[finish] ...and finishes it at its door after the restart',
       [r.get('how') for r in _frows(_fj2, 'finished', 'fin-boot')], ['door'])
finally:
    stop(_fp)

# The offers page and the places report read the press's real end off takenRuns:
# a Drop or chooser row a finished row names ends at the finish.
_frun = [_pm_offer('frn1', 'uber', 10.0, 4.0, 20.0, 30, 0),
         _pm_offer('frn2', 'uber', 10.0, 4.0, 20.0, 30, 1),
         _pm_offer('frn3', 'uber', 10.0, 4.0, 20.0, 30, 2),
         _pm_offer('frn4', 'uber', 10.0, 4.0, 20.0, 30, 3)]
_fd1 = _pm_drop('frn1', None, 5, 0)
del _fd1['by']
_fd2 = _pm_drop('frn2', 'chooser', 4, 1)
_fd3 = _pm_drop('frn3', None, 6, 2)
del _fd3['by']
_fd4 = _pm_drop('frn4', 'gps', 22, 3)
_frun += [_fd1, _fd2, _fd3, _fd4]
for _dr, _how, _end in ((_fd1, 'door', 23), (_fd2, 'stop', 21), (_fd4, 'door', 30)):
    _t = _dr['acceptedAt'] + _end * 60000
    _frun.append({'v': 1, 'kind': 'finished', 'at': _t, 'id': _dr['id'], 'seq': _t,
                  'holdId': '%s@%d' % (_dr['id'], _dr['acceptedAt']), 'how': _how,
                  'dropAt': _dr['at']})
_t = _fd3['acceptedAt'] + 20 * 60000
_frun.append({'v': 1, 'kind': 'finished', 'at': _t, 'id': 'frn3', 'seq': _t, 'holdId': 'x',
              'how': 'area', 'dropAt': _fd3['at'] - 1})
write(os.path.join(_fdir2, 'runs.jsonl'), _frun)
_fp, _fb = start({'SCANNER': '0'}, os.path.join(_fdir2, 'runs.jsonl'))
try:
    _fjn = get(_fb, '/api/journal?days=0')
finally:
    stop(_fp)
eq('[finish] takenRuns ends a finished press at the finish, by \'finished-<how>\', the press kept',
   sorted((t.get('id'), t.get('by'), round((t['endedAt'] - t['tookAt']) / 60000.0),
           t.get('pressedBy'), t.get('pressedAt') is not None)
          for t in _fjn.get('taken') or [] if t.get('id', '').startswith('frn')),
   [('frn1', 'finished-door', 23, 'drop', True), ('frn2', 'finished-stop', 21, 'chooser', True),
    ('frn3', 'drop', 6, None, False), ('frn4', 'gps', 22, None, False)])
eq('[finish] ...and card against real counts a finished press as measured at the door',
   ((_fjn.get('cardVsReal') or {}).get('n'), (_fjn.get('cardVsReal') or {}).get('notAtDoor')),
   (3, 1))
_ftp = open(os.path.join(ROOT, 'journal.html'), encoding='utf-8').read()
ok_('[finish] ...and the offers page counts the finished ones as timed at the door',
    "t.by === 'finished-door'" in _ftp and "t.by === 'finished-stop'" in _ftp)
shutil.rmtree(_fdir, ignore_errors=True)
shutil.rmtree(_fdir2, ignore_errors=True)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d server checks passed' % ok)
sys.exit(1 if bad else 0)
