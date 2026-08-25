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

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d live-view checks passed' % ok)
sys.exit(1 if bad else 0)
