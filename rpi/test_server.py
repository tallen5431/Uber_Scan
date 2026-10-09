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
        eq('the order in the car carries the stops last read, and why none was '
           'filed, for a panel reloaded mid-delivery', held.get('planner'),
           {'stops': _STOPS_C, 'unfiled': 'dropoffs'})
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

# ...and off the order in the car at the other two moments the panel forgets
# them — a press, and a different offer on the record — so a reload shows what
# the live panel shows. They were kept until another planner replaced them, and
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
        code, reply = post(base, '/api/offers/mark', {
            'id': 'o-carried', 'accepted': True,
            'offer': {'id': 'o-carried', 'pay': 14.0, 'minutes': 30.0,
                      'billedMinutes': 30.0, 'miles': 6.0, 'cost': 2.1,
                      'dropoff': None}})
        ok_('the premise: an order is in the car before the planners are read',
            code == 200 and reply.get('holding') is True)
        ok_('the premise: the order in the car holds a two-dropoff planner',
            (_held_planner(True).get('planner') or {}).get('unfiled') == 'dropoffs')
        code, _ = post(base, '/api/dropoff', {})
        eq('a ⌖ press takes the last planner off the order in the car, as it takes '
           'its stops off the panel', (code, (get(base, '/api/status').get('holding')
                                              or {}).get('planner')), (200, None))
        held = {}
        for _ in range(80):
            held = get(base, '/api/status').get('holding') or {}
            if held.get('dropoff'):
                break
            time.sleep(0.05)
        eq('...so a reload after that press read the order\'s end shows the end '
           'and no stops beside it',
           (held.get('dropoff'), held.get('dropoffScanned'), held.get('planner')),
           ('12 Oak St, Marietta, GA 30060', True, None))
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
        _dheld = json.load(_fh)
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
        _fh.write('agree disagree noread garbage none agree agree')
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
    with open(path, 'rb') as fh:
        return fh.read()


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
       [(f, shown == _raw(os.path.join(_adir, f)).decode('utf-8')) for f, shown, _s, _n in _recs],
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
    _shelve(_snaps, '2026-01-08_00-00-00')
    _elsewhere = os.path.join(_pdir, 'a-record-elsewhere.json')
    with open(_elsewhere, 'w') as _fh:
        _fh.write('{"v": 1, "said": "saved", "contents": [], "notes": []}\n')
    os.symlink(_elsewhere, os.path.join(_snaps, '2026-01-08_00-00-00', 'snap.json'))
    _st, _rep = _note(_u, {'snap': '2026-01-08_00-00-00', 'note': 'x'})
    eq('a note on a snap whose snap.json is a link is refused, and nothing read or written '
       'through it',
       (_st, os.path.islink(os.path.join(_snaps, '2026-01-08_00-00-00', 'snap.json')),
        _raw(_elsewhere)),
       (409, True, b'{"v": 1, "said": "saved", "contents": [], "notes": []}\n'))
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

# ...and a note on a snap still being kept: it has no snap.json yet and will
# in a moment, which is not the same as a folder that has none. A screenshot
# that takes a second holds the press open while the note is sent.
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
    _pt.join()
    eq('a note on a snap still being kept is refused, saying so',
       (_st, _rep.get('error')), (409, 'this snap is still being kept; try again in a moment'))
    _st, _rep = _note(_u, {'snap': _filling, 'note': 'offer card'})
    eq('...and kept once it has been',
       (_st, (_json_in(os.path.join(_snaps, _filling or '?'), 'snap.json') or {}).get('note')),
       (200, 'offer card'))
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
with open(_bfake, 'w') as fh:
    fh.write(
        'import json, os, sys, time\n'
        'if os.path.exists(%r):\n'
        '    time.sleep(600)\n'
        'open(%r, "w").close()\n'
        'time.sleep(1.5)\n'
        'print(json.dumps({"alive": True, "at": 5, "tooBright": False,\n'
        '    "tooDim": False, "refindRefused": None, "notSaving": None,\n'
        '    "gps": {"state": "stale", "ageSeconds": 312.0},\n'
        '    "cpuC": 71.4, "cpuCWhy": None,\n'
        '    "throttled": {"now": ["under-voltage"], "sinceBoot": ["under-voltage"]},\n'
        '    "throttledWhy": None}), flush=True)\n'
        'time.sleep(4.0)\n'
        'sys.exit(1)\n' % (_bonce, _bonce))
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
       _bb.get('gps'), {'state': 'stale', 'ageSeconds': 312.0})
    eq('...and the Pi\'s temperature and throttling',
       (_bb.get('cpuC'), _bb.get('throttled')),
       (71.4, {'now': ['under-voltage'], 'sinceBoot': ['under-voltage']}))
    eq('...and the notices that already rode it', _bb.get('notSaving', 'absent'), None)
    # An age, never a timestamp — the rule for everything on this endpoint,
    # because whatever reads it does not share this server's clock.
    ok_('...with its own age instead of a timestamp (%r)'
        % ((_bb.get('ageMs'), _bb.get('at')),),
        isinstance(_bb.get('ageMs'), int) and 0 <= _bb['ageMs'] < 10000
        and 'at' not in _bb and 'alive' not in _bb)
    time.sleep(0.5)
    _bstream = [m for m in _bheard if m.get('alive')]
    ok_('the stream carries the same heartbeat to the panel (%d)' % len(_bstream),
        _bstream and _bstream[0].get('gps') == {'state': 'stale', 'ageSeconds': 312.0}
        and _bstream[0].get('cpuC') == 71.4
        and (_bstream[0].get('throttled') or {}).get('now') == ['under-voltage'])
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

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d server checks passed' % ok)
sys.exit(1 if bad else 0)
