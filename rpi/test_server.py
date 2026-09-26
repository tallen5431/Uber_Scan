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
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
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
            'def say(i, minutes, pay):\n'
            '    print(json.dumps({"ready": True, "state": "go", "perHour": 30.0,\n'
            '        "grossPerHour": 36.0, "pay": pay, "minutes": minutes, "miles": 5.0,\n'
            '        "cost": 1.75, "billedMinutes": minutes, "target": 25, "band": 15,\n'
            '        "costPerMile": 0.35, "at": int(time.time() * 1000),\n'
            '        "offer": {"id": i, "pay": pay, "minutes": minutes, "billedMinutes": minutes,\n'
            '                  "miles": 5.0, "cost": 1.75, "perHour": 30.0, "target": 25,\n'
            '                  "band": 15, "costPerMile": 0.35}}), flush=True)\n'
            'say("o-1", 0.01, 9.0)\n'
            'time.sleep(2.5)\n'
            'say("o-3", 30.0, 12.45)\n'
            'time.sleep(1.5)\n'
            'say("o-3", 30.0, 12.45)\n'
            'time.sleep(1.5)\n'
            'say("o-4", 20.0, 11.0)\n'
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
            '                  "endRefused": True}}), flush=True)\n'
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
                        'SCANNER_ARGS': _hfake}, _hjournal)
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
finally:
    stop(_hproc)

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


_hproc2, _hbase2 = _start_loud({'SCANNER': '0'}, _hjournal)
try:
    _back = (get(_hbase2, '/api/status') or {}).get('holding')
    ok_('a restarted server still has the order in the car (%r)'
        % ((_back or {}).get('pay'),), bool(_back))
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
shutil.rmtree(_hdir, ignore_errors=True)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d server checks passed' % ok)
sys.exit(1 if bad else 0)
