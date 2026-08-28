"""The live camera view, over the wire.

    python3 rpi/test_liveview.py

This is the picture a driver watches to decide whether to press Accept, and it
is now a connection the server holds open rather than a file it hands over. That
is a better picture — measured end to end through the real page, 13.7 distinct
frames a second before and 28.4 after — and it is also the first thing in this
project that keeps a socket alive indefinitely.

So what is checked here is mostly the failure side of that: that a viewer who
walks away releases their slot, that twenty of them walking away does not
gradually strangle the rig, and that a browser which will not render a stream
still gets a picture. The frame rate is a nice-to-have; a live view that stops
working after a day of tabs being opened and closed is a rig that cannot be
aimed.

The server is the real server.js, started as a subprocess.
"""

import html.parser
import os
import re
import shutil
import socket
import json
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
    print('no node on this machine — skipping the live-view checks')
    sys.exit(0)

work = tempfile.mkdtemp()
# Files planted inside the repo to prove they are not served. Removed in the
# `finally` below whatever happens — leaving a stray journal in a checkout is
# precisely the mistake this block is about.
leaked = []
frame = os.path.join(work, 'live.jpg')
journal = os.path.join(work, 'journal.jsonl')
open(journal, 'w').close()

# A one-pixel JPEG is a real JPEG, and this test is about the plumbing rather
# than the picture.
JPEG = bytes(bytearray([
    0xFF, 0xD8, 0xFF, 0xDB, 0x00, 0x43, 0x00] + [0x08] * 64 + [
    0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01, 0x00, 0x01, 0x01, 0x01, 0x11, 0x00,
    0xFF, 0xC4, 0x00, 0x14, 0x00, 0x01] + [0x00] * 15 + [0x00,
    0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01, 0x00, 0x00, 0x3F, 0x00, 0xD2, 0xCF, 0x20,
    0xFF, 0xD9]))


def write_frame(n=0):
    """A different frame each time, so a new part is genuinely new."""
    with open(frame + '.part', 'wb') as fh:
        fh.write(JPEG + bytes(bytearray([n & 0xFF])))
    os.replace(frame + '.part', frame)


write_frame(1)
port = free_port()
env = dict(os.environ, SCANNER='0', PORT=str(port), JOURNAL=journal, FRAME=frame)
proc = subprocess.Popen(['node', os.path.join(ROOT, 'server.js')], env=env,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
base = 'http://127.0.0.1:%d' % port
for _ in range(120):
    try:
        urllib.request.urlopen(base + '/api/status', timeout=1).read()
        break
    except Exception:
        time.sleep(0.1)
else:
    raise RuntimeError('the server never came up')


def open_stream():
    s = socket.create_connection(('127.0.0.1', port), timeout=5)
    s.sendall(b'GET /api/frame.mjpeg HTTP/1.1\r\nHost: x\r\n\r\n')
    return s


def first_line(sock, wait=0.5):
    time.sleep(wait)
    try:
        return sock.recv(65536).split(b'\r\n')[0].decode('latin1')
    except Exception:
        return ''


try:
    # --- it is a stream, and it says so -----------------------------------
    s = open_stream()
    time.sleep(0.5)
    blob = s.recv(65536)
    head = blob.split(b'\r\n\r\n')[0].decode('latin1')
    eq('the stream opens', head.split('\r\n')[0], 'HTTP/1.1 200 OK')
    ok_('...as a replacing multipart', 'multipart/x-mixed-replace' in head)
    ok_('...with a boundary the parts use', 'boundary=' in head)
    ok_('...and sends a part straight away', b'--uberscanframe' in blob)
    ok_('...carrying a jpeg', b'Content-Type: image/jpeg' in blob)
    s.close()

    # --- new frames, not the same one repeated ----------------------------
    # The whole point of streaming is that an unchanged picture costs nothing.
    s = open_stream()
    time.sleep(0.3)
    s.recv(65536)
    for i in range(2, 8):
        write_frame(i)
        time.sleep(0.08)
    time.sleep(0.2)
    more = s.recv(200000)
    ok_('a new frame on disk becomes a new part', more.count(b'--uberscanframe') >= 3)
    s.close()

    # --- a viewer who walks away gives their slot back --------------------
    # Three rounds, because a leak shows up as the cap never re-arming: the
    # first round would pass and the second would find every slot still taken.
    for round_number in range(3):
        held = [open_stream() for _ in range(6)]
        time.sleep(0.4)
        spare = open_stream()
        eq('round %d: past the cap is refused, not starved' % (round_number + 1),
           first_line(spare, 0.3), 'HTTP/1.1 503 Service Unavailable')
        spare.close()
        for h in held:
            h.close()                      # every one dropped mid-stream
        time.sleep(0.6)

    after = open_stream()
    eq('...and after eighteen dropped streams a new one still opens',
       first_line(after, 0.4), 'HTTP/1.1 200 OK')
    after.close()
    time.sleep(0.4)

    # --- the server is still a server -------------------------------------
    eq('nothing else was harmed',
       urllib.request.urlopen(base + '/api/status', timeout=3).status, 200)
    eq('...including the page itself',
       urllib.request.urlopen(base + '/live.html', timeout=3).status, 200)

    # --- only the site is served ------------------------------------------
    # The path rule used to be a denylist, and a denylist has to be remembered
    # every time something new appears beside server.js. It was not: `rpi/` and
    # `ssl/` were refused by name, so the journal in `rpi/` was safe and a copy
    # of that same journal anywhere else was not. A `journal-backup.jsonl` in
    # the root and a `backup/journal.jsonl` were both served in full — pickup
    # addresses included — to anyone on the car's wifi. Those are exactly the
    # files a person makes when being careful with their data.
    for spot in ('journal-backup.jsonl', os.path.join('backup', 'journal.jsonl'),
                 os.path.join('logs', 'uberscan.log')):
        full = os.path.join(ROOT, spot)
        if os.path.dirname(spot):
            os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, 'w') as fh:
            fh.write('{"pay": 16.05, "places": ["Mae Dell Rd, Chattanooga"]}\n')
        leaked.append(full)

    for spot in ('/journal-backup.jsonl', '/backup/journal.jsonl',
                 '/logs/uberscan.log', '/tools/test.sh'):
        try:
            urllib.request.urlopen(base + spot, timeout=3)
            eq('a journal outside rpi/ is not served: %s' % spot, 'served', 'refused')
        except urllib.error.HTTPError as e:
            ok_('a journal outside rpi/ is not served: %s' % spot, e.code in (403, 404))

    # ...and the site itself is untouched. An allowlist that also refuses the
    # pages is not a fix, and every one of these is a file the app cannot start
    # without.
    for spot in ('/', '/index.html', '/live.html', '/journal.html', '/styles.css',
                 '/offer-parser.js', '/advice.js', '/sw.js',
                 '/manifest.webmanifest', '/icons/icon-192.png',
                 '/vendor/tesseract.min.js', '/vendor/lang/eng.traineddata.gz'):
        try:
            eq('the site still serves %s' % spot,
               urllib.request.urlopen(base + spot, timeout=3).status, 200)
        except urllib.error.HTTPError as e:
            eq('the site still serves %s' % spot, e.code, 200)

    # --- the dashboard layout is wired to the elements it names ------------
    # The rig's own panel is wide and short, so live.html turns #app into a
    # two-column grid — the verdict beside the camera view — and hands each
    # child a `grid-column`. #viewWrap was not a child. It sat one level deeper
    # inside .live, which is a flex column, so its `grid-column: 2` applied to
    # nothing: the camera view stacked underneath the verdict in the left-hand
    # column, the right-hand column stayed empty, and the page grew past the
    # glass. Measured on an 800x480 panel: columns of 431px and 345px, the
    # verdict rendered at 431px instead of 784px, 43% of the screen black, and
    # the page 768px tall so the bar of controls fell off the bottom.
    #
    # It survived because it is invisible without a camera: with no frame the
    # `:has(.gone)` rule collapses the grid to one column and the page looks
    # right, which is exactly the state a development machine is in.
    #
    # Checked structurally rather than by rendering, because that is the actual
    # rule — a grid places its own children and nobody else's — and because it
    # holds for whatever gets added next.
    class Nesting(html.parser.HTMLParser):
        """The id of each element's DIRECT parent, or None when it has none.

        Direct, deliberately. A grid places its own children and nobody else's,
        so "somewhere inside #app" is exactly the wrong question — the element
        that broke this was inside #app the whole time, one level too deep.
        """

        VOID = ('img', 'br', 'hr', 'input', 'meta', 'link', 'source', 'area',
                'base', 'col', 'embed', 'param', 'track', 'wbr')

        def __init__(self):
            html.parser.HTMLParser.__init__(self)
            self.stack = []          # one entry per open element: its id or None
            self.parent = {}

        def handle_starttag(self, tag, attrs):
            got = dict(attrs).get('id')
            if got:
                self.parent[got] = self.stack[-1] if self.stack else None
            if tag not in self.VOID:
                self.stack.append(got)

        def handle_startendtag(self, tag, attrs):
            self.handle_starttag(tag, attrs)

        def handle_endtag(self, tag):
            if tag not in self.VOID and self.stack:
                self.stack.pop()

    page = open(os.path.join(ROOT, 'live.html')).read()
    tree = Nesting()
    tree.feed(page)

    # Every id the across-the-screen layout gives a grid-column to, and where
    # that id actually lives in the markup. A grid places its own children and
    # nobody else's, so a `grid-column` on something nested one level deeper
    # applies to nothing at all — which is how this layout came to have never
    # once worked, invisibly, on a page that looked right without a camera.
    #
    # The condition used to carry `and (max-height: 620px)`; it is bare
    # landscape now, because the height term was excluding every panel larger
    # than the two it was written for. rpi/test_layout.py holds every file to
    # the same condition, so this only has to find the block.
    block = re.search(r'@media \(orientation: landscape\)\s*\{(.*?)\n  \}',
                      page, re.S)
    ok_('the across-the-screen block is still there', block is not None)
    placed = set(re.findall(r'#([A-Za-z][\w-]*)[^{}]*\{[^{}]*grid-column',
                            block.group(1) if block else ''))
    ok_('...and it places things by id', placed)
    for name in sorted(placed):
        eq('%s is a child of the grid that places it' % name,
           tree.parent.get(name), 'app')

    # --- which picture the browser is asking for --------------------------
    #
    # Two views now: the wide shot with the corners drawn on, for aiming the
    # camera, and the phone's own screen flattened, for reading the phone
    # through the rig's display. The scanner learns which from the same file
    # that tells it somebody is watching, so the two expire together — a mode
    # set by a call of its own would outlive the tab that set it, and the
    # scanner would go on buying a sensor frame ten times a second for nobody.
    #
    # This is the seam between two processes that are sometimes parent and
    # child and sometimes strangers, so it is checked as bytes on disk.
    # Asked of the shipped rule rather than written out again here: the three
    # handoff files moved to /dev/shm, and a test carrying its own copy of a
    # path goes on passing against a server writing somewhere else — which is
    # the one failure it exists to catch. rpi/test_handoff.py holds the Python
    # and JavaScript versions of that rule to the same answer.
    sys.path.insert(0, os.path.join(ROOT, 'rpi'))
    import handoff as HO
    watch = HO.path(HO.VIEWING)

    def settled(want=None):
        """What the file says once the write behind the request has landed.

        `want` because these run back to back and the file already holds the
        previous answer: without it a read can win the race and report the
        request before this one. Waiting for a value that never comes still
        returns whatever is there, so a genuine failure reads as one.
        """
        got = ''
        for _ in range(60):
            try:
                with open(watch) as fh:
                    got = fh.read().strip()
            except OSError:
                got = ''
            if got and (want is None or got == want):
                return got
            time.sleep(0.05)
        return got or '<never written>'

    def asked_for(query):
        # A change of view has to go through at once rather than waiting out
        # the once-a-second throttle, so each of these is a real switch.
        urllib.request.urlopen(base + '/api/frame.jpg' + query, timeout=3).read()
        return settled(query.split('view=')[-1].split('&')[0] if 'view=' in query else None)

    eq('asking for the phone view says so', asked_for('?view=screen'), 'screen')
    eq('...and asking for the scene says that', asked_for('?view=scene'), 'scene')
    eq('a browser that says nothing gets the view that has always been there',
       asked_for('?t=123'), 'scene')
    eq('...and so does one that asks for something invented',
       asked_for('?view=holographic'), 'scene')
    # Node hands back an array for a repeated key, and an array is not a word.
    eq('...or asks twice', asked_for('?view=screen&view=scene'), 'scene')

    # The page uses the stream and keeps the still as a fallback, so the view
    # has to travel on both. It is the stream that matters most: one request
    # that never ends, so the only chance to say which picture is when it opens.
    stream = socket.create_connection(('127.0.0.1', port), timeout=5)
    stream.sendall(b'GET /api/frame.mjpeg?view=screen HTTP/1.1\r\nHost: x\r\n\r\n')
    eq('the stream carries it too', settled('screen'), 'screen')
    stream.close()

    # Never a torn read.
    #
    # This file is written by one process and read by another on its own clock,
    # up to thirty times a second, and an empty read means "the scene" — so a
    # truncate-then-write hands the driver the wrong picture for as long as the
    # reader's cache holds it. Sampling for the gap is not a test: the window
    # is microseconds and a loop that misses it passes, which is how a check
    # that proves nothing ends up in a suite. Checked at the mechanism instead.
    # A rename gives the path the staging file's inode, so consecutive writes
    # land on different ones; writing in place keeps the inode it had.
    inodes = []
    for i in range(6):
        urllib.request.urlopen(
            base + '/api/frame.jpg?view=' + ('screen' if i % 2 else 'scene'),
            timeout=3).read()
        settled('screen' if i % 2 else 'scene')
        inodes.append(os.stat(watch).st_ino)
    ok_('the view is swapped in by rename rather than written in place',
        len(set(inodes)) > 1)
    # ...and the staging file is not left lying in the repository.
    ok_('no half-written file is left behind', not os.path.exists(watch + '.part'))
    eq('...and the last word asked for is the one standing', settled(), 'screen')

    # --- the fallback still works -----------------------------------------
    # A browser that will not render a multipart image falls back to fetching
    # stills, so that path may not rot.
    r = urllib.request.urlopen(base + '/api/frame.jpg', timeout=3)
    eq('a single frame is still fetchable', r.status, 200)
    eq('...as a jpeg', r.headers.get('Content-Type'), 'image/jpeg')
    ok_('...with something in it', len(r.read()) > 0)

    # --- no frame yet -----------------------------------------------------
    # Before the scanner has written anything the still 404s, which is what
    # tells the page to say so rather than showing a broken image.
    os.remove(frame)
    try:
        urllib.request.urlopen(base + '/api/frame.jpg', timeout=3)
        eq('a missing frame is a 404', 'served', '404')
    except urllib.error.HTTPError as e:
        eq('a missing frame is a 404', e.code, 404)
    # ...and the stream waits for one rather than failing or spinning.
    s = open_stream()
    eq('...while the stream simply waits', first_line(s, 0.5), 'HTTP/1.1 200 OK')
    write_frame(9)
    time.sleep(0.4)
    got = b''
    try:
        got = s.recv(65536)
    except Exception:
        pass
    ok_('...and delivers the first frame when it appears', b'--uberscanframe' in got)
    s.close()

    # --- what the shift adds up to, for the driving screen's status row ------
    #
    # The offers page works this out from rows it already holds. The driving
    # screen holds none, so the arithmetic happens on the server — and the whole
    # point of putting it there is that there is then exactly one rule for which
    # offers count. These checks are about that rule surviving the trip.
    now = int(time.time() * 1000)
    rows = []
    # One card read three times is ONE offer. Counting journal rows would make a
    # single card look like a busy afternoon — a real recording has a median of
    # four readings per card and a maximum of fourteen.
    for i in range(3):
        rows.append({'v': 1, 'id': 'o1', 'at': now - 3600000 + i, 'seq': i + 1,
                     'pay': 16.05, 'minutes': 23.0, 'perHour': 30.0, 'whole': True})
    rows.append({'v': 1, 'id': 'o2', 'at': now - 1800000, 'seq': 4, 'pay': 8.0,
                 'minutes': 22.0, 'perHour': 20.0, 'whole': True})
    # Two that must be set aside rather than dropped: a partial read always
    # flatters the offer, and a suspect one is not evidence about anything.
    rows.append({'v': 1, 'id': 'o3', 'at': now - 900000, 'seq': 5, 'pay': 12.0,
                 'minutes': 30.0, 'perHour': 10.0, 'whole': False})
    rows.append({'v': 1, 'id': 'o4', 'at': now - 600000, 'seq': 6, 'pay': 9.0,
                 'minutes': 20.0, 'perHour': 40.0, 'whole': True, 'suspect': True})
    # Recorded before the Pi's clock was set. Stamped 1970 on disk forever, so
    # it cannot fall inside any day window.
    rows.append({'v': 1, 'id': 'o5', 'at': 1000, 'seq': 7, 'pay': 5.0,
                 'minutes': 10.0, 'perHour': 25.0, 'whole': True})
    rows.append({'kind': 'mark', 'id': 'o2', 'at': now - 1700000, 'accepted': True})
    # Marked as taken, but its reading was partial. The offers page counts the
    # accepted flag only on rows that already count, so this one must not
    # appear in the taken figure either.
    rows.append({'kind': 'mark', 'id': 'o3', 'at': now - 800000, 'accepted': True})
    with open(journal, 'w') as fh:
        fh.write('\n'.join(json.dumps(r) for r in rows) + '\n')

    since = now - 6 * 3600000

    def today(qs):
        return json.loads(urllib.request.urlopen(base + '/api/today?' + qs,
                                                 timeout=3).read().decode())

    day = today('since=%d' % since)
    eq('one card read many times is one offer', day.get('offers'), 4)
    eq('...of which the ones with a rate worth drawing are counted',
       day.get('counted'), 2)
    eq('...and the rest are named rather than dropped', day.get('setAside'), 2)
    # 20 and 30 straddle the middle of a two-sample set, so the median is 25 by
    # the same interpolation journal.html uses. A different rounding here would
    # put two different medians for one day on two screens.
    eq('...with the median of the counted rates', day.get('median'), 25)
    # The one that matters most: o3 was marked taken and is set aside, so it is
    # not in this number. Counting `accepted` over the raw window instead of
    # over the counted rows would say 2 here and the offers page would say 1.
    eq('taken is counted first and accepted second', day.get('took'), 1)
    eq('...and an offer stamped before the clock was set is said to be missing,'
       ' not quietly lost', day.get('beforeClock'), 1)
    ok_('...on a journal that could be read', day.get('unreadable') is None)
    ok_('...by a machine that knows what day it is', day.get('clockSet'))

    # A window this endpoint cannot believe is an error rather than a silent
    # all-time figure. /api/journal can afford a zero fallback because `days`
    # defaults to 30; alone, zero means the whole journal — which the caller
    # would then put on a panel under the word "today".
    # `refused`, not `bad` — the module-level failure counter is called that,
    # and a loop variable at module scope rebinds it to a string. The tally at
    # the bottom then dies on a %d, which is how this was caught.
    for refused, what in (('', 'no window at all'),
                          ('since=0', 'a window starting at the epoch'),
                          ('since=abc', 'a window that is not a number'),
                          ('since=99999999999999', 'a window past the year 2100')):
        try:
            urllib.request.urlopen(base + '/api/today?' + refused, timeout=3)
            eq('%s is refused' % what, 'answered', '400')
        except urllib.error.HTTPError as e:
            eq('%s is refused' % what, e.code, 400)

    # The same answer twice is not a second read of the journal — but it must
    # still be the right answer, and it must change the moment the journal does.
    again = today('since=%d' % since)
    eq('asking twice gives the same answer', again, day)
    with open(journal, 'a') as fh:
        fh.write(json.dumps({'v': 1, 'id': 'o6', 'at': now - 300000, 'seq': 8,
                             'pay': 20.0, 'minutes': 40.0, 'perHour': 30.0,
                             'whole': True}) + '\n')
    after = today('since=%d' % since)
    eq('...and a new offer is seen, not served from the last answer',
       after.get('offers'), 5)
    eq('...and moves the median with it', after.get('median'), 30)

    # A window that starts after everything in the file is a real, empty day —
    # and an empty day is not the same claim as a journal that could not be read.
    empty = today('since=%d' % (now + 60000))
    eq('a day with nothing in it yet counts nothing', empty.get('offers'), 0)
    eq('...and has no median to report', empty.get('median'), None)
    ok_('...and does not call that a broken journal',
        empty.get('unreadable') is None)
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    for stray in leaked:
        try:
            os.remove(stray)
        except OSError:
            pass
    for spare in ('backup', 'logs'):
        try:
            os.rmdir(os.path.join(ROOT, spare))
        except OSError:
            pass
    shutil.rmtree(work, ignore_errors=True)

# --- how old the last verdict is, said in a number of milliseconds ---------
#
# The page seeds itself from /api/status and is sent the last reading again on
# every socket that connects. It used to start its staleness clocks at zero for
# both, so a rig that stopped an hour ago had its ACCEPT painted at full
# confidence on every page load and re-freshened on every reconnect.
#
# Ages rather than timestamps, because a Pi has no real-time clock: it boots in
# 1970 and jumps when the network arrives, so handing a browser one machine's
# absolute time to subtract from another's is the arithmetic that turned "12
# seconds old" into "fifty-six years old". A duration has no origin to disagree
# about. This checks the server's half of that.
if shutil.which('python3'):
    work2 = tempfile.mkdtemp()
    # A scanner that says one thing and then goes quiet, which is exactly the
    # rig this is about.
    fake = os.path.join(work2, 'onceonly.py')
    with open(fake, 'w') as fh:
        fh.write('import json, sys, time\n'
                 'print(json.dumps({"ready": True, "state": "go", "perHour": 25.0,\n'
                 '                  "grossPerHour": 25.0, "pay": 10.0,\n'
                 '                  "minutes": 24.0, "miles": None}), flush=True)\n'
                 'print(json.dumps({"offer": {"id": "o-1", "pay": 12.45,\n'
                 '                  "minutes": 28.0, "perHour": 20.51}}), flush=True)\n'
                 'time.sleep(600)\n')
    port2 = free_port()
    quiet = subprocess.Popen(
        ['node', os.path.join(ROOT, 'server.js')],
        env=dict(os.environ, PORT=str(port2), HTTPS_PORT='0',
                 JOURNAL=os.path.join(work2, 'j.jsonl'),
                 SCANNER='1', SCANNER_CMD='python3', SCANNER_ARGS=fake),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base2 = 'http://127.0.0.1:%d' % port2
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen(base2 + '/api/status', timeout=1).read()
                break
            except Exception:
                time.sleep(0.1)
        # The reading has to have landed before its age means anything.
        for _ in range(60):
            body = json.loads(urllib.request.urlopen(
                base2 + '/api/status', timeout=3).read().decode('utf-8'))
            if body.get('last'):
                break
            time.sleep(0.1)

        ok_('the server keeps the last reading', bool(body.get('last')))
        ok_('...and says how old it is', isinstance(body.get('lastAgeMs'), int))
        ok_('...and how long since the scanner said anything',
            isinstance(body.get('heardAgeMs'), int))
        first = body.get('lastAgeMs')
        time.sleep(1.2)
        later = json.loads(urllib.request.urlopen(
            base2 + '/api/status', timeout=3).read().decode('utf-8'))
        ok_('the age grows as the reading gets older',
            later.get('lastAgeMs', 0) >= (first or 0) + 900)
        ok_('...and is a duration, not a timestamp',
            later.get('lastAgeMs', 0) < 60 * 60 * 1000)

        # ...and the same reading, replayed to a socket that has just connected.
        stream = urllib.request.urlopen(base2 + '/api/events', timeout=5)
        line = b''
        for _ in range(40):
            line = stream.readline()
            if line.startswith(b'data: '):
                break
        replayed = json.loads(line[len(b'data: '):].decode('utf-8'))
        stream.close()
        eq('a replayed reading says it is a replay', replayed.get('replay'), True)
        ok_('...and carries its own age', isinstance(replayed.get('ageMs'), int))
        ok_('...which is not zero, an hour after the fact',
            replayed.get('ageMs', -1) >= 1000)
        eq('...and is otherwise the reading itself', replayed.get('perHour'), 25.0)

        # --- and which offer is on the record, for the mark button ---------
        #
        # The driving screen offers to mark the last offer as taken, and the
        # normal case is a tab looked at *after* the card has gone: the driver
        # accepts on the phone, the card is replaced, the scanner reads no card.
        # So the offer has to survive here rather than only on the wire.
        eq('the server keeps the offer on record',
           (later.get('offer') or {}).get('id'), 'o-1')
        eq('...with the payout the button is named after',
           (later.get('offer') or {}).get('pay'), 12.45)
        ok_('...and how old it is', isinstance(later.get('offerAgeMs'), int))
    finally:
        quiet.terminate()
        try:
            quiet.wait(timeout=5)
        except Exception:
            quiet.kill()
        shutil.rmtree(work2, ignore_errors=True)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d live-view checks passed' % ok)
sys.exit(1 if bad else 0)
