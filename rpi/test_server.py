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

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d server checks passed' % ok)
sys.exit(1 if bad else 0)
