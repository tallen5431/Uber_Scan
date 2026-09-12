"""Reading the phone's GPS, including every way it stops.

    python3 rpi/test_gps.py

This module exists to put a coordinate on an offer, and a coordinate is the
kind of number that gets believed. So the checks here are weighted the way the
risk is: a little on parsing a good sentence, and most of it on refusing to
produce a number when the honest answer is none.

The phone's server app runs on a timer — the one this was written against
showed "Runtime Left 4:48" — so it stopping mid-shift is not an edge case, it
is Tuesday. Everything below is driven against a real socket on a real port so
that the threading, the reconnect and the line framing are the real ones; only
the clock is faked, because twenty seconds of staleness per case is twenty
seconds nobody should spend.
"""

import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gps as G                                              # noqa: E402

ok = bad = 0


def eq(name, got, want):
    global ok, bad
    if got == want:
        ok += 1
    else:
        bad += 1
        print('FAIL  %s: got %r want %r' % (name, got, want))


def close_to(name, got, want, tol=1e-4):
    global ok, bad
    if got is not None and abs(got - want) <= tol:
        ok += 1
    else:
        bad += 1
        print('FAIL  %s: got %r want %r (+/- %g)' % (name, got, want, tol))


def ok_(name, cond):
    eq(name, bool(cond), True)


def waited(test, seconds=5.0, step=0.02):
    """Poll until true. The thread is real, so nothing here is instant."""
    end = time.time() + seconds
    while time.time() < end:
        if test():
            return True
        time.sleep(step)
    return False


# --- addresses --------------------------------------------------------------
#
# The phone in question reports four IPv4 addresses and four IPv6, and the ones
# worth using are its Tailscale pair — the hotspot's DHCP address changes and
# the tailnet's does not. So the IPv6 form is not a curiosity here, it is the
# likely one.

eq('a bare host takes the default port', G.parse_host('phone'), ('phone', 2947))
eq('a host and port', G.parse_host('10.96.203.95:2947'), ('10.96.203.95', 2947))
eq('...and a port that is not the default', G.parse_host('phone:5000'),
   ('phone', 5000))
# The trap: rsplit(':') on a bare IPv6 literal yields a host of
# `fd7a:115c:a1e0::4601` and a port of `c5d0`, which is not an error until it
# is a connection to the wrong place.
eq('a bare IPv6 address is a host, not a host and a port',
   G.parse_host('fd7a:115c:a1e0::4601:c5d0'),
   ('fd7a:115c:a1e0::4601:c5d0', 2947))
eq('...and bracketed, with a port', G.parse_host('[fd7a:115c:a1e0::4601:c5d0]:2947'),
   ('fd7a:115c:a1e0::4601:c5d0', 2947))
eq('...and bracketed without one', G.parse_host('[::1]'), ('::1', 2947))
eq('whitespace around it is not part of it', G.parse_host('  phone:1  '),
   ('phone', 1))
for bad_one in ('', '   ', '[::1'):
    try:
        G.parse_host(bad_one)
        eq('%r is refused' % bad_one, 'accepted', 'refused')
    except ValueError:
        ok += 1

# --- one line at a time -----------------------------------------------------

# gpsd's own shape, which is what port 2947 means when it means anything.
TPV = ('{"class":"TPV","device":"/dev/x","mode":3,'
       '"time":"2026-09-12T18:20:49.000Z","lat":34.0117,"lon":-84.6105,'
       '"alt":290.0,"speed":0.0,"track":0.0}')
got = G.parse_line(TPV)
ok_('a gpsd TPV record is a fix', got is not None)
close_to('...at the latitude it states', got['lat'], 34.0117)
close_to('...and the longitude', got['lon'], -84.6105)
eq('...and says where it came from', got['source'], 'gpsd')
eq('...and keeps the GPS\'s own time, which is the true one',
   got['gpsTime'], '2026-09-12T18:20:49.000Z')

# mode 1 is "no fix". A record can carry a lat and lon and still be saying it
# does not know where it is - the last known position, or a zero.
eq('a TPV with no fix is not a fix',
   G.parse_line('{"class":"TPV","mode":1,"lat":34.0,"lon":-84.6}'), None)
eq('...and mode 2 is', G.parse_line(
    '{"class":"TPV","mode":2,"lat":34.0,"lon":-84.6}')['lat'], 34.0)
# A record with no mode at all is taken at its word: several senders omit it,
# and refusing them all would refuse the fix for the sake of a missing field.
ok_('a TPV with no mode stated is still a fix',
    G.parse_line('{"class":"TPV","lat":34.0,"lon":-84.6}') is not None)

eq('the VERSION banner is not a fix',
   G.parse_line('{"class":"VERSION","release":"3.22"}'), None)
eq('nor a SKY record', G.parse_line('{"class":"SKY","satellites":[]}'), None)
eq('nor half a line of JSON', G.parse_line('{"class":"TPV","lat":34'), None)
eq('nor a blank', G.parse_line(''), None)
eq('nor a None', G.parse_line(None), None)

# The other protocol. Several phone apps take gpsd's port and push raw NMEA at
# whoever connects, so the port says nothing about what will arrive.
RMC = '$GPRMC,182049.00,A,3400.7020,N,08436.6300,W,0.0,0.0,120926,,,A*4A'
got = G.parse_line(RMC)
ok_('an NMEA RMC sentence is a fix', got is not None)
# ddmm.mmmm is neither degrees nor minutes: 3400.7020 is 34 degrees and 0.702
# minutes, which is 34.0117 degrees. Read as a decimal it would be off by an
# entire hemisphere's worth of arithmetic.
close_to('...with ddmm.mmmm converted, not read as a decimal',
         got['lat'], 34.0117)
close_to('...and west made negative', got['lon'], -84.6105)
eq('...and says which protocol it came from', got['source'], 'nmea')

# 'V' is the receiver saying the fix is not valid. The position beside it is
# whatever it last thought, and using it would put the car wherever it was when
# it last saw the sky - a tunnel, a car park, this morning.
eq('an RMC marked void is not a fix',
   G.parse_line('$GPRMC,182049.00,V,3400.7020,N,08436.6300,W,0,0,120926,,,N*52'),
   None)

# Knots on the wire. Storing them as if they were metres per second would
# overstate every speed by a factor of two.
fast = G.parse_line(
    '$GPRMC,182049.00,A,3400.7020,N,08436.6300,W,38.9,271.5,120926,,,A*79')
ok_('a moving RMC carries a speed', fast is not None and 'speed' in fast)
close_to('...converted from knots to metres per second', fast['speed'],
         38.9 * 0.514444, tol=0.01)
close_to('...and a heading', fast['heading'], 271.5)

GGA = '$GPGGA,182049.00,3400.7020,N,08436.6300,W,1,08,0.9,290.0,M,,,,*2F'
got = G.parse_line(GGA)
ok_('a GGA sentence is a fix too', got is not None)
close_to('...at the same place', got['lat'], 34.0117)
close_to('...and carries the altitude', got['altitude'], 290.0)
# Quality 0 means the receiver has no fix. Same trap as RMC's 'V'.
eq('a GGA with quality 0 is not a fix',
   G.parse_line('$GPGGA,182049.00,3400.7020,N,08436.6300,W,0,00,,,M,,,,*24'),
   None)

# The checksum. A sentence crosses a phone hotspot in a moving car, and one
# flipped character parses perfectly into a position several degrees away -
# a wrong number with nothing downstream that could ever catch it.
broken = RMC.replace('3400.7020', '3500.7020')          # moved a degree north
ok_('...and the corrupted one no longer matches its own checksum',
    not G._checksum_ok(broken))
eq('a sentence that fails its checksum is refused', G.parse_line(broken), None)
# ...while one with no checksum at all is allowed, because some senders omit it
# and refusing them would refuse a working setup over a missing field.
ok_('a sentence with no checksum is still read',
    G.parse_line('$GPRMC,182049.00,A,3400.7020,N,08436.6300,W,0.0,0.0,120926,,,A')
    is not None)
eq('a checksum that is not hexadecimal is refused',
   G.parse_line(RMC[:-2] + 'ZZ'), None)

# Null Island: what a receiver emits when it has nothing. It is a real point on
# the map, in the Gulf of Guinea, and it would place a shift there.
eq('exactly zero in both is not a place', G.parse_line(
    '{"class":"TPV","mode":3,"lat":0,"lon":0}'), None)
ok_('...but a real coordinate near zero is',
    G.parse_line('{"class":"TPV","mode":3,"lat":0.5,"lon":-0.2}') is not None)
eq('a latitude past the pole is refused', G.parse_line(
    '{"class":"TPV","mode":3,"lat":91.0,"lon":10.0}'), None)
eq('...and a longitude past the line', G.parse_line(
    '{"class":"TPV","mode":3,"lat":10.0,"lon":181.0}'), None)
# JSON has no NaN, but a bool is an int in Python and `lat: true` would sail
# through an isinstance check into arithmetic.
eq('a boolean is not a latitude', G.parse_line(
    '{"class":"TPV","mode":3,"lat":true,"lon":true}'), None)
eq('nor is a string', G.parse_line(
    '{"class":"TPV","mode":3,"lat":"34.0","lon":"-84.6"}'), None)

# Not everything on the wire is a position, and most of it is not.
for noise in ('$GPGSV,3,1,11,01,45,123,35*4D', 'hello', '$GPRMC,182049.00,A',
              '$', '$*', '{}', '[]', 'null'):
    eq('%r is not a fix' % noise[:24], G.parse_line(noise), None)


# --- a phone at the end of a socket ----------------------------------------

class FakePhone(object):
    """The GPS server app, in the roles it actually plays.

    A real socket on a real port, because the framing, the threading and the
    reconnect are the parts most likely to be wrong and a stubbed transport
    would check none of them.
    """

    def __init__(self, script=(), greet=None, drop_after=None):
        self.script = list(script)
        self.greet = greet
        self.drop_after = drop_after
        self.heard = []
        self.connections = 0
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('127.0.0.1', 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    @property
    def address(self):
        return '127.0.0.1:%d' % self.port

    def _serve(self):
        self.sock.settimeout(0.2)
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            self.connections += 1
            threading.Thread(target=self._talk, args=(conn,),
                             daemon=True).start()

    def _talk(self, conn):
        try:
            conn.settimeout(0.2)
            if self.greet:
                conn.sendall(self.greet.encode() + b'\r\n')
                # Whatever the client says back - gpsd's WATCH, or nothing.
                try:
                    self.heard.append(conn.recv(4096).decode('utf-8', 'replace'))
                except socket.timeout:
                    pass
            sent = 0
            for chunk in self.script:
                if self._stop.is_set():
                    return
                conn.sendall(chunk if isinstance(chunk, bytes) else chunk.encode())
                sent += 1
                if self.drop_after is not None and sent >= self.drop_after:
                    return                      # the app's timer ran out
                time.sleep(0.02)
            while not self._stop.is_set():
                time.sleep(0.05)
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def close(self):
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass


class Clock(object):
    """A clock that only moves when told, so staleness costs no wall time."""

    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


# The ordinary case, end to end: raw NMEA at whoever connects.
phone = FakePhone(script=[RMC + '\r\n'])
try:
    it = G.Phone(phone.address).start()
    ok_('a fix arrives over a real socket', waited(lambda: it.fix() is not None))
    got = it.fix()
    close_to('...at the right latitude', got['lat'], 34.0117)
    eq('...and the state says so', it.state()['state'], 'fixed')
    ok_('...and it reports how old the fix is', got['ageSeconds'] >= 0)
    it.stop()
    eq('...and stopping says so', it.state()['state'], 'off')
finally:
    phone.close()

# A sentence split across two packets. This is not hypothetical over a phone
# hotspot, and a reader that parsed whatever one recv() returned would lose
# that fix and feed half a line to the parser.
half, rest = RMC[:20], RMC[20:] + '\r\n'
phone = FakePhone(script=[half, rest])
try:
    it = G.Phone(phone.address).start()
    ok_('a sentence split across two packets is still one fix',
        waited(lambda: it.fix() is not None))
    close_to('...and is not half a position',
             (it.fix() or {}).get('lat'), 34.0117)
    it.stop()
finally:
    phone.close()

# Real gpsd greets, then says nothing until it is asked to WATCH. An app that
# merely borrowed the port must not be sent that command.
phone = FakePhone(greet='{"class":"VERSION","release":"3.22"}',
                  script=[TPV + '\r\n'])
try:
    it = G.Phone(phone.address).start()
    ok_('a greeting gpsd is asked to watch, and answers',
        waited(lambda: it.fix() is not None))
    ok_('...and the command it was sent is gpsd\'s (%r)' % (phone.heard[:1],),
        any('?WATCH' in h for h in phone.heard))
    it.stop()
finally:
    phone.close()

quiet = FakePhone(script=[RMC + '\r\n'])
try:
    it = G.Phone(quiet.address).start()
    ok_('a server that never greets still gets read',
        waited(lambda: it.fix() is not None))
    eq('...and is sent nothing it did not ask for', quiet.heard, [])
    it.stop()
finally:
    quiet.close()


# --- the ways it stops, which is the point of the file ---------------------

# THE safety property. The app on the phone runs on a timer and will stop
# mid-shift; a position from before it stopped, handed over as a position, is
# the confidently-wrong number this whole project is built to refuse.
clock = Clock()
phone = FakePhone(script=[RMC + '\r\n'])
try:
    it = G.Phone(phone.address, stale_after=20.0, clock=clock).start()
    ok_('a fix arrives', waited(lambda: it.fix() is not None))
    clock.now += 19.0
    ok_('...and is still good a moment later', it.fix() is not None)
    eq('...and still reads as fixed', it.state()['state'], 'fixed')
    clock.now += 2.0
    eq('a fix older than the limit is NO fix', it.fix(), None)
    # ...and the state says which of the two silences this is, because "the
    # phone stopped talking" and "there is no phone" want different answers
    # from the driver.
    eq('...and the state says it went stale rather than never arriving',
       it.state()['state'], 'stale')
    it.stop()
finally:
    phone.close()

# A clock that jumps backwards. The Pi has no RTC: it boots in 1970 and leaps
# forward when NTP answers, so a fix taken before the jump is measured against
# a clock decades ahead of the one that timed it. A negative age is nonsense,
# and nonsense must not read as "fresh".
clock = Clock()
phone = FakePhone(script=[RMC + '\r\n'])
try:
    it = G.Phone(phone.address, stale_after=20.0, clock=clock).start()
    ok_('a fix arrives before the clock jumps', waited(lambda: it.fix() is not None))
    clock.now -= 3600.0
    eq('a fix from the future is not a fix', it.fix(), None)
    it.stop()
finally:
    phone.close()

# The app's timer runs out mid-stream: one sentence, then the socket closes.
# What must happen is that the fix ages out and the reader keeps trying.
clock = Clock()
phone = FakePhone(script=[RMC + '\r\n', RMC + '\r\n'], drop_after=1)
try:
    it = G.Phone(phone.address, stale_after=5.0, clock=clock).start()
    ok_('the one sentence before the app stopped is read',
        waited(lambda: it.fix() is not None))
    ok_('...and the reader goes back for more',
        waited(lambda: phone.connections >= 2, seconds=6.0))
    clock.now += 6.0
    eq('...while what it already had goes stale on schedule', it.fix(), None)
    it.stop()
finally:
    phone.close()

# Nothing listening at all, which is the state a parked car is in most of the
# time. It must not raise, must not block, and must not invent a position.
it = G.Phone('127.0.0.1:9', stale_after=20.0).start()
try:
    eq('a phone that is not there yields no fix', it.fix(), None)
    ok_('...and the reader survives it',
        waited(lambda: it.state()['error'] is not None, seconds=5.0))
    eq('...and is still looking', it.state()['state'], 'looking')
    # The scan loop calls this between frames. It has to be free.
    started = time.time()
    for _ in range(2000):
        it.fix()
    ok_('...and asking costs nothing (%.0fms for 2000 calls)'
        % ((time.time() - started) * 1000), time.time() - started < 1.0)
finally:
    it.stop()

# A phone that accepts the connection and then says nothing. This is the shape
# that would wedge a reader written with a blocking read and no timeout, and
# the rig would go quiet with it.
mute = FakePhone(script=[])
try:
    it = G.Phone(mute.address, stale_after=20.0).start()
    time.sleep(0.5)
    eq('a phone that accepts and says nothing yields no fix', it.fix(), None)
    started = time.time()
    it.stop()
    ok_('...and lets go promptly when asked (%.1fs)' % (time.time() - started),
        time.time() - started < 3.0)
finally:
    mute.close()

# Rubbish on the port - a web server, a different app, a wrong address. It must
# be read and discarded rather than believed or crashed on.
junk = FakePhone(script=['HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n'
                         '<html><body>not a gps</body></html>\r\n'])
try:
    it = G.Phone(junk.address, stale_after=20.0).start()
    time.sleep(0.6)
    eq('a wrong address on the right port yields no fix', it.fix(), None)
    ok_('...and the lines are counted, so it is visibly talking to something',
        it.state()['lines'] > 0)
    it.stop()
finally:
    junk.close()

# A sender with no line endings at all. Left unbounded this is a buffer that
# grows until the rig runs out of memory - on the machine that is also driving
# the panel.
flood = FakePhone(script=['x' * 20000] * 8)
try:
    it = G.Phone(flood.address, stale_after=20.0).start()
    ok_('a stream with no line ending is given up on rather than buffered',
        waited(lambda: (it.state()['error'] or '').find('no end') >= 0,
               seconds=8.0))
    it.stop()
finally:
    flood.close()

# Two fixes: the later one wins, and the earlier one is not still hanging about
# inside the dict the caller was handed.
phone = FakePhone(script=[RMC + '\r\n',
                          '$GPRMC,182100.00,A,3401.7020,N,08436.6300,W,0.0,0.0,120926,,,A*47\r\n'])
try:
    it = G.Phone(phone.address).start()
    ok_('the first fix arrives', waited(lambda: it.fix() is not None))
    held = it.fix()
    ok_('...and then a later one',
        waited(lambda: (it.fix() or {}).get('lat', 0) > 34.02, seconds=5.0))
    close_to('the dict handed out earlier is not rewritten underneath the caller',
             held['lat'], 34.0117)
    it.stop()
finally:
    phone.close()

# start() twice is one thread, not two racing to write the same fix.
phone = FakePhone(script=[RMC + '\r\n'])
try:
    it = G.Phone(phone.address)
    it.start()
    it.start()
    ok_('starting twice still yields a fix', waited(lambda: it.fix() is not None))
    it.stop()
    time.sleep(0.4)
    eq('...and stopping once stops it', it.state()['state'], 'off')
    # A second stop on something already stopped is a thing a shutdown path
    # does, and it must not raise.
    it.stop()
    ok += 1
finally:
    phone.close()

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d gps checks passed' % ok)
sys.exit(1 if bad else 0)
