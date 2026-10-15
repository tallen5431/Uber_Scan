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

import json
import math
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

# --- what a fix says about itself ---------------------------------------------
#
# Kept, and judged in one place. Marietta Square, a public place, rather than
# anywhere the rig has actually been. The figures are real ones: 27.8 m is the
# owner's VK-162 on mode 3 indoors (epx 17.8, epy 12.8), and 129.2 m is what
# real gpsd 3.25 made of a four-satellite stream at HDOP 6.8 — still mode 3.

def tpv(**fields):
    msg = {'class': 'TPV', 'lat': 33.9526, 'lon': -84.5499}
    msg.update(fields)
    return json.dumps(msg)


got = G.parse_line(tpv(mode=3, eph=129.2, epx=80.1, epy=95.3))
eq('a 3D fix keeps its error estimate', got and got.get('err'), 129.2)
eq('...and its mode', got and got.get('mode'), 3)
eq('...and its two halves when gpsd sends them',
   got and (got.get('epx'), got.get('epy')), (80.1, 95.3))
eq('a 2D fix says it is 2D', (G.parse_line(tpv(mode=2, eph=12.0)) or {}).get('mode'), 2)
got = G.parse_line(tpv(mode=3))
eq('a TPV gpsd sent without eph has no error estimate, not a zero',
   got and got.get('err', 'absent'), None)
ok_('...and is still a fix: gps.py refuses nothing new', got is not None)
eq('...and has no halves it was not sent', got and ('epx' in got or 'epy' in got), False)
eq('a TPV with no mode stated keeps None for it, not a guess',
   (G.parse_line(tpv(eph=12.0)) or {}).get('mode', 'absent'), None)
got = G.parse_line(RMC)
eq('an RMC says nothing about its quality, and None says so',
   (got.get('mode', 'absent'), got.get('err', 'absent')), (None, None))
got = G.parse_line(GGA)
eq('a GGA keeps its fix quality and HDOP',
   (got.get('quality'), got.get('hdop')), (1, 0.9))
eq('...and turns neither into metres', got.get('err', 'absent'), None)

# The gate. One function, one answer, and a word for why not.
eq('the owner\'s indoor fix is usable',
   G.usable({'mode': 3, 'err': 27.8, 'ageSeconds': 1.0}), (True, None))
eq('a mode-3 fix at 129.2 m is refused as rough — mode bounds nothing',
   G.usable({'mode': 3, 'err': 129.2, 'ageSeconds': 1.0}), (False, 'rough'))
eq('a fix exactly at FIX_ERR_MAX is usable',
   G.usable({'mode': 3, 'err': G.FIX_ERR_MAX, 'ageSeconds': 1.0}), (True, None))
eq('...and one a tenth over it is not',
   G.usable({'mode': 3, 'err': G.FIX_ERR_MAX + 0.1, 'ageSeconds': 1.0}),
   (False, 'rough'))
eq('a 2D fix inside the limit is usable',
   G.usable({'mode': 2, 'err': 20.0, 'ageSeconds': 1.0}), (True, None))
eq('a fix with no error estimate is refused as unrated',
   G.usable({'mode': 3, 'err': None, 'ageSeconds': 1.0}), (False, 'unrated'))
eq('...which is every NMEA fix, which states none',
   G.usable(dict(G.parse_line(GGA), ageSeconds=1.0)), (False, 'unrated'))
eq('a fix with an error but no mode is refused as nomode',
   G.usable({'mode': None, 'err': 20.0, 'ageSeconds': 1.0}), (False, 'nomode'))
eq('...and so is mode 1, which is no fix at all',
   G.usable({'mode': 1, 'err': 20.0, 'ageSeconds': 1.0}), (False, 'nomode'))
eq('a fix past the age rule is refused as stale',
   G.usable({'mode': 3, 'err': 20.0, 'ageSeconds': G.STALE_AFTER + 0.5}),
   (False, 'stale'))
eq('...and one exactly at it is not',
   G.usable({'mode': 3, 'err': 20.0, 'ageSeconds': G.STALE_AFTER}), (True, None))
eq('a fix nobody can date is stale',
   G.usable({'mode': 3, 'err': 20.0, 'ageSeconds': None}), (False, 'stale'))
eq('the caller\'s unrounded age is the one judged',
   G.usable({'mode': 3, 'err': 20.0, 'ageSeconds': 20.0}, age=20.004),
   (False, 'stale'))
# A stale fix is drawn grey where it was; a rough one is not drawn at all. So a
# rough fix that has also gone stale must still say rough, or the panel would
# grey in a position that was never good enough to show.
eq('quality is judged before age: a rough fix that went stale is rough',
   G.usable({'mode': 3, 'err': 129.2, 'ageSeconds': 600.0}), (False, 'rough'))
eq('a boolean is not an error estimate',
   G.usable({'mode': 3, 'err': True, 'ageSeconds': 1.0}), (False, 'unrated'))

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
                # An Event in the script is a gate: nothing after it is sent
                # until the test sets it, rather than after a sleep it hopes
                # is long enough.
                if isinstance(chunk, threading.Event):
                    while not chunk.wait(0.05):
                        if self._stop.is_set():
                            return
                    continue
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
    # ...and how stale. The scan loop reads this for the panel's "no fix for
    # 12 min" and the journal's gps rows; the word alone said only that the
    # fix had gone, not since when.
    eq('...and how old the newest fix is, on the same clock',
       it.state().get('ageSeconds', 'absent'), 21.0)
    it.stop()
finally:
    phone.close()

# The word and the position must not disagree about a fix right at the limit.
# state() reports the age rounded to a tenth; judged on that rounded figure,
# 20.04s became 20.0, "fixed", while fix() — on the true figure — had already
# handed back None. The panel and the row would then say a GPS was fine that
# the offer rows were already going without.
clock = Clock()
phone = FakePhone(script=[RMC + '\r\n'])
try:
    it = G.Phone(phone.address, stale_after=20.0, clock=clock).start()
    ok_('a fix arrives for the boundary', waited(lambda: it.fix() is not None))
    clock.now += 20.04
    eq('at 20.04s the position is gone', it.fix(), None)
    eq('...and the word says so too, judged on the same unrounded age',
       it.state()['state'], 'stale')
    eq('...while the age it reports is rounded for reading',
       it.state().get('ageSeconds', 'absent'), 20.0)
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
    # ...and has no age to give. "No fix for -60 min" is the nonsense this
    # rule exists to keep off the panel, and None is the honest answer. Only a
    # clock handed in can do this: the default is monotonic (see the end of
    # this file), so the panel has no branch for a stale fix without an age.
    eq('...and has no age, rather than a negative one',
       it.state().get('ageSeconds', 'absent'), None)
    it.stop()
finally:
    phone.close()

# The gate's answer leaves with the fix, end to end over a real socket: the
# scan loop hands Phone.fix() to the journal and the offer line, and the
# heartbeat hands Phone.latest() to the panel, so this is where `ok` and `why`
# either arrive or do not.
clock = Clock()
phone = FakePhone(greet='{"class":"VERSION","release":"3.22"}',
                  script=[tpv(mode=3, eph=129.2) + '\r\n'])
try:
    it = G.Phone(phone.address, stale_after=20.0, clock=clock).start()
    ok_('a rough fix arrives', waited(lambda: it.fix() is not None))
    got = it.fix() or {}
    eq('...and is handed out, not refused — gps.py only reports',
       (got.get('lat'), got.get('err')), (33.9526, 129.2))
    eq('...with the gate\'s answer on it',
       (got.get('ok', 'absent'), got.get('why', 'absent')), (False, 'rough'))
    it.stop()
finally:
    phone.close()

clock = Clock()
phone = FakePhone(greet='{"class":"VERSION","release":"3.22"}',
                  script=[tpv(mode=3, eph=27.8, epx=17.8, epy=12.8) + '\r\n'])
try:
    it = G.Phone(phone.address, stale_after=20.0, clock=clock).start()
    ok_('a good fix arrives', waited(lambda: it.fix() is not None))
    got = it.fix() or {}
    eq('...and is usable', (got.get('ok', 'absent'), got.get('why', 'absent')),
       (True, None))
    got = it.latest() or {}
    eq('...and latest() says the same of it while it is fresh',
       (got.get('ok', 'absent'), got.get('ageSeconds')), (True, 0.0))
    clock.now += 6.5
    # The panel greys a beat's dot when this runs out, on its own clock: the
    # rule's limit, less the age, from the one place the rule lives.
    eq('a fix says how long it has left inside the staleness rule',
       (it.latest() or {}).get('freshFor', 'absent'), 13.5)
    clock.now += 14.5                           # 21 seconds since it arrived
    eq('past the limit fix() is still None, as it always was', it.fix(), None)
    got = it.latest()
    # The heartbeat's dot: drawn grey where the car was, rather than gone with
    # nothing saying why.
    eq('...while latest() keeps the position, judged stale',
       got and (got['lat'], got['ok'], got['why'], got['ageSeconds']),
       (33.9526, False, 'stale', 21.0))
    eq('...with no time left on it', (got or {}).get('freshFor', 'absent'), 0.0)
    clock.now -= 3600.0
    got = it.latest()
    eq('a clock run backwards past it gives no age, and stale',
       got and (got['ageSeconds'], got['why']), (None, 'stale'))
    it.stop()
finally:
    phone.close()

# The phone's own limit is the gate's limit. Phone(stale_after=5) refusing at
# five seconds while the gate waited for twenty would be two staleness rules.
clock = Clock()
phone = FakePhone(greet='{"class":"VERSION","release":"3.22"}',
                  script=[tpv(mode=3, eph=27.8) + '\r\n'])
try:
    it = G.Phone(phone.address, stale_after=5.0, clock=clock).start()
    ok_('a fix arrives for a five-second limit', waited(lambda: it.fix() is not None))
    clock.now += 6.0
    eq('the gate goes stale on the phone\'s own limit, not the module\'s',
       (it.latest() or {}).get('why'), 'stale')
    it.stop()
finally:
    phone.close()

eq('latest() with nothing received is None, not an empty fix',
   G.Phone('127.0.0.1:9').latest(), None)

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
    eq('...with no fix to give an age for',
       it.state().get('ageSeconds', 'absent'), None)
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

# Two fixes: the later one wins, and the dict the caller was handed for the
# earlier one stays as it was handed. fix() writes the age into what it
# returns, on every call; were that the stored dict rather than a copy, the
# next frame's call would rewrite the age of a fix this caller still holds.
#
# Compared whole against itself as handed, not its latitude against 34.0117.
# The thread stores each fix as a new dict, so the latitude never moves. Over
# 1,000 repeats of this block that comparison failed 8 with the stored dict
# handed out and 10 with the copy, every one a `held` that was already the
# later fix (got 34.02836666666667): the second sentence, sent 20ms after the
# first, parsed before `held` was taken. This form fails 1,000 of 1,000 with
# the stored dict and 0 with the copy.
#
# The gate holds the second sentence until the next frame has asked. Without
# it, a slow moment after `held` lets the later fix be the stored one by then
# and take that age instead: 0.2s there, and the stored dict passed 3 runs in 3.
gate = threading.Event()
clock = Clock()
phone = FakePhone(script=[RMC + '\r\n', gate,
                          '$GPRMC,182100.00,A,3401.7020,N,08436.6300,W,0.0,0.0,120926,,,A*47\r\n'])
try:
    it = G.Phone(phone.address, clock=clock).start()
    ok_('the first fix arrives', waited(lambda: it.fix() is not None))
    held = it.fix()
    was = dict(held)
    clock.now += 1.0
    it.fix()                                    # the next frame, a second on
    gate.set()
    ok_('...and then a later one',
        waited(lambda: (it.fix() or {}).get('lat', 0) > 34.02, seconds=5.0))
    eq('the dict handed out earlier is not rewritten underneath the caller',
       held, was)
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

# --- a position that does not move -----------------------------------------
#
# The owner's VK-162 under gpsd's binary u-blox mode: TPV lat/lon bit-identical
# second after second, for an hour and a half of driving, while the same lines'
# ECEF moved — and every one of them passed the gate. See FROZEN_AFTER in
# gps.py. Built here at Marietta Square, a public place, never at the owner's
# coordinates; the SHAPE is the owner's: mode 3, eph 27.8, epx 11.4, nine
# decimals, five lines a second apart, the ECEF moving +0.11 m in x and
# -2.65 m in y over the five (interpolated evenly between — only the first
# and last were read off the rig), and lying 3,048.7 m due west of the frozen
# lat/lon, as the owner's did.

def ecef_of(lat, lon, h):
    """Geodetic -> ECEF, the closed form, written out here so ecef_to_lla is
    checked against an independent statement of the ellipsoid, not its own."""
    a, e2 = 6378137.0, (1 / 298.257223563) * (2 - 1 / 298.257223563)
    la, lo = math.radians(lat), math.radians(lon)
    n = a / math.sqrt(1 - e2 * math.sin(la) ** 2)
    return ((n + h) * math.cos(la) * math.cos(lo),
            (n + h) * math.cos(la) * math.sin(lo),
            (n * (1 - e2) + h) * math.sin(la))


def west(lat, lon, metres):
    """The point `metres` due west, on the sphere metres_apart uses."""
    return lat, lon - math.degrees(metres / (6378137.0 * math.cos(math.radians(lat))))


def north(lat, lon, metres):
    return lat + math.degrees(metres / 6378137.0), lon


SQ = (33.9526, -84.5499)


def frozen_tpv(xyz, lat=SQ[0], lon=SQ[1], **more):
    msg = {'class': 'TPV', 'device': '/dev/ttyACM0', 'mode': 3,
           'time': '2026-10-12T19:51:0%dZ' % more.pop('sec', 0),
           'lat': lat, 'lon': lon, 'altHAE': 300.0, 'eph': 27.8, 'epx': 11.4,
           'ecefx': round(xyz[0], 2), 'ecefy': round(xyz[1], 2),
           'ecefz': round(xyz[2], 2), 'ecefpAcc': 15.7}
    msg.update(more)
    return json.dumps(msg)


def feed(lines, step=1.0):
    """Each line to a real Phone over a real socket, `step` seconds of its
    clock apart, and what latest() said after each — the heartbeat's view."""
    clock = Clock()
    gates = [threading.Event() for _ in lines]
    script = []
    for gate, line in zip(gates, lines):
        script += [gate, line + '\r\n']
    phone = FakePhone(greet='{"class":"VERSION","release":"3.22"}', script=script)
    it = G.Phone(phone.address, stale_after=20.0, clock=clock).start()
    seen = []
    try:
        waited(lambda: it.state()['lines'] >= 1)
        for i, gate in enumerate(gates):
            if i:
                clock.now += step
            gate.set()
            waited(lambda: it.state()['lines'] >= i + 2)
            seen.append(it.latest() or {})
    finally:
        it.stop()
        phone.close()
    return seen


def lla(*xyz):
    """ecef_to_lla, with a crash an answer of its own, so a division by
    nothing fails the check that names it rather than the whole file."""
    try:
        return G.ecef_to_lla(*xyz)
    except Exception as e:                       # noqa: BLE001
        return 'raised %s' % type(e).__name__


# ECEF -> lat/lon, against points built the other way, to half a metre.
_worst = 0.0
for _lat, _lon, _h in ((33.9526, -84.5499, 300.0), (0.0, 0.0, 0.0),
                       (-33.8568, 151.2153, 5.0), (27.9881, 86.9250, 8848.0),
                       (31.5590, 35.4732, -430.0), (89.99, -45.0, 0.0),
                       (-89.99, 120.0, 2800.0), (64.8378, -147.7164, 136.0)):
    _back = lla(*ecef_of(_lat, _lon, _h))
    _worst = (max(_worst, G.metres_apart(_lat, _lon, _back[0], _back[1]),
                  abs(_back[2] - _h)) if isinstance(_back, tuple) else float('inf'))
ok_('ECEF -> lat/lon/height comes back within half a metre at eight points, '
    'poles to sea floor (worst %.2g m)' % _worst, _worst < 0.5)
_eq = lla(6378137.0, 0.0, 0.0)
ok_('...and the equator at the prime meridian is (0, 0, 0)',
    isinstance(_eq, tuple) and abs(_eq[0]) < 1e-9 and abs(_eq[1]) < 1e-9 and abs(_eq[2]) < 1e-3)
_np = lla(0.0, 0.0, 6378137.0 * (1 - 1 / 298.257223563))
ok_('...and the north pole is latitude 90 at height 0, not a division by '
    'nothing (%r)' % (_np,), isinstance(_np, tuple) and abs(_np[0] - 90) < 1e-9 and abs(_np[2]) < 1e-3)
eq('...and a receiver with no solution, all zeros, is no position',
   G.ecef_to_lla(0.0, 0.0, 0.0), None)
eq('...nor is NaN', G.ecef_to_lla(float('nan'), 1.0, 1.0), None)

# The owner's five lines, reshaped. Frozen lat/lon; the ECEF where the car is.
_car = west(SQ[0], SQ[1], 3048.7)
_base = ecef_of(_car[0], _car[1], 300.0)
OWNER5 = [frozen_tpv((_base[0] + 0.11 * k / 4, _base[1] - 2.65 * k / 4, _base[2]),
                     lat=33.952600000, lon=-84.549900000, sec=k) for k in range(5)]
got = G.parse_line(OWNER5[0])
eq('a TPV whose lat/lon are 3 km from its own ECEF uses the ECEF position',
   got and got.get('source'), 'ecef')
ok_('...and it is where the ECEF says, within half a metre (%.2f m)'
    % G.metres_apart(got['lat'], got['lon'], *_car),
    G.metres_apart(got['lat'], got['lon'], *_car) < 0.5)
ok_('...says by how much they disagreed (%r)' % got.get('ecefGap'),
    abs(got.get('ecefGap', 0) - 3048.7) < 1.0)
eq('...keeps gpsd\'s pair beside it', (got.get('gpsdLat'), got.get('gpsdLon')),
   (33.9526, -84.5499))
ok_('...and says what was done on the fix (%r)' % got.get('note'),
    'ECEF' in (got.get('note') or '') and '3049 m' in got.get('note'))
eq('...keeping gpsd\'s error estimate for the gate to ask', got.get('err'), 27.8)
seen = feed(OWNER5)
eq('through Phone, every one of the five is the ECEF\'s position, judged usable',
   [(s.get('source'), s.get('ok')) for s in seen], [('ecef', True)] * 5)
ok_('...and the last is within the 2.65 m its own ECEF moved of where the '
    'car started (%.2f m)' % G.metres_apart(seen[-1]['lat'], seen[-1]['lon'], *_car),
    G.metres_apart(seen[-1]['lat'], seen[-1]['lon'], *_car) < 2.7)

# Agreeing positions are left alone: a car driving north at 15 m/s whose
# ECEF is its lat/lon's.
_path = [north(SQ[0], SQ[1], 15.0 * k) for k in range(8)]
AGREE = [frozen_tpv(ecef_of(la, lo, 300.0), lat=round(la, 9), lon=round(lo, 9),
                    speed=15.0, sec=k) for k, (la, lo) in enumerate(_path)]
seen = feed(AGREE)
eq('a TPV whose lat/lon agree with its ECEF keeps gpsd\'s, to the bit',
   [(s.get('source'), s.get('lat'), s.get('lon')) for s in seen],
   [('gpsd', round(la, 9), round(lo, 9)) for la, lo in _path])
ok_('...agreeing to centimetres (worst %.3f m)'
    % max(s.get('ecefGap', 99) for s in seen),
    max(s.get('ecefGap', 99) for s in seen) < 0.05)
eq('...and every one usable', [s.get('ok') for s in seen], [True] * 8)
eq('...with no note', [s.get('note') for s in seen], [None] * 8)

# Frozen lat/lon, the car driving north at 15 m/s, the ECEF moving with it.
# gpsd's pair is believed while it is inside ECEF_AGREE of the ECEF, and the
# ECEF's from the fix after.
_path = [north(SQ[0], SQ[1], 15.0 * k) for k in range(10)]
DRIVE = [frozen_tpv(ecef_of(la, lo, 300.0), sec=k % 10)
         for k, (la, lo) in enumerate(_path)]
seen = feed(DRIVE)
eq('frozen lat/lon with moving ECEF: gpsd\'s pair inside 50 m, the ECEF '
   'position from 60 m on',
   [s.get('source') for s in seen], ['gpsd'] * 4 + ['ecef'] * 6)
ok_('...and the last fix is where the car is, not where it froze (%.2f m off)'
    % G.metres_apart(seen[-1]['lat'], seen[-1]['lon'], *_path[-1]),
    G.metres_apart(seen[-1]['lat'], seen[-1]['lon'], *_path[-1]) < 0.5)
eq('...and every one usable — the frozen pair only while it was within the '
   'gate\'s own error', [s.get('ok') for s in seen], [True] * 10)

# ...and at a crawl, 6 m/s with no speed on the line: the stretch where the
# ECEF has moved past ECEF_MOVED but not yet past ECEF_AGREE is refused as
# frozen, then the ECEF takes over.
_path = [north(SQ[0], SQ[1], 6.0 * k) for k in range(11)]
CRAWL = [frozen_tpv(ecef_of(la, lo, 300.0), sec=k % 10)
         for k, (la, lo) in enumerate(_path)]
seen = feed(CRAWL)
eq('a frozen lat/lon whose ECEF has crept 25-50 m is refused as frozen',
   [(s.get('source'), s.get('why')) for s in seen],
   [('gpsd', None)] * 6 + [('gpsd', 'frozen')] * 3 + [('ecef', None)] * 2)

# Frozen with a speed and no ECEF at all — gpsd's NMEA path, or a phone.
STUCK = [json.dumps({'class': 'TPV', 'mode': 3, 'lat': 33.952600000,
                     'lon': -84.549900000, 'eph': 27.8, 'speed': 13.4})] * 9
seen = feed(STUCK)
eq('frozen lat/lon while the TPV says 13.4 m/s is refused as frozen past '
   'five seconds', [s.get('why') for s in seen], [None] * 6 + ['frozen'] * 3)
eq('...and says how long it has stood', seen[-1].get('heldFor'), 8.0)
_aside = feed([STUCK[0], json.dumps(dict(json.loads(STUCK[0]),
                                         lat=33.952600001))] + STUCK[:7])
eq('a lat/lon that moves by one bit starts the count again',
   [s.get('heldFor') for s in _aside], [0.0, 0.0, 0.0] + [float(k) for k in range(1, 7)])

# Parked in a real static hold: lat/lon still, the ECEF inside its jitter (the
# owner's 2.65 m, scattered), the speed noise. Right, so not refused.
_wobble = [(0.0, 0.0), (1.1, -0.8), (-0.6, 2.4), (2.0, 1.3), (-1.7, -2.2)]
PARKED = [frozen_tpv((_base[0] + dx, _base[1] + dy, _base[2]), lat=_car[0],
                     lon=_car[1], speed=0.12, sec=k % 10)
          for k, (dx, dy) in enumerate(_wobble * 6)]
seen = feed(PARKED)
eq('a parked receiver holding still for 29 s is not refused',
   [s.get('why') for s in seen], [None] * 30)
ok_('...though it has stood that long (%r)' % seen[-1].get('heldFor'),
    seen[-1].get('heldFor') == 29.0)

# The gate's own arithmetic, one arm at a time.
_held = {'mode': 3, 'err': 27.8, 'ageSeconds': 1.0, 'heldFor': 6.0}
eq('held past five seconds at 3 m/s is frozen',
   G.usable(dict(_held, speed=3.0)), (False, 'frozen'))
eq('...and so by its ECEF velocity alone',
   G.usable(dict(_held, ecefSpeed=3.0)), (False, 'frozen'))
eq('...and so by its ECEF having moved 30 m alone',
   G.usable(dict(_held, heldMoved=30.0)), (False, 'frozen'))
eq('held exactly five seconds at speed is not yet',
   G.usable(dict(_held, heldFor=5.0, speed=30.0)), (True, None))
eq('held a minute at walking-noise speed inside the ECEF jitter is fine',
   G.usable(dict(_held, heldFor=60.0, speed=1.9, ecefSpeed=1.9, heldMoved=24.0)),
   (True, None))
_v = G.parse_line(frozen_tpv(_base, lat=_car[0], lon=_car[1], ecefvx=3.0,
                             ecefvy=-4.0, ecefvz=12.0))
eq('ECEF velocity is read as a speed', _v and _v.get('ecefSpeed'), 13.0)

# --- whether the car is being driven ------------------------------------------
#
# The panel's driving form asks this of the fix the beat carries, and gps.py
# answers it on every fix as it arrives (DRIVING_SPEED). Driven here through
# Phone.take(), the one way a fix gets in, on a clock this file turns: each
# speed one TPV a second apart, the car moving north at it so its lat/lon
# never stand still long enough to be `frozen`, and what latest() — the beat's
# view — says after each.


def drive(fixes, step=1.0):
    """`fixes` are speeds in m/s, or dicts of TPV fields; latest()'s
    `driving` after each, and the Phone, for a later look."""
    clock = Clock()
    it = G.Phone('127.0.0.1:9', stale_after=20.0, clock=clock)
    out, north_m = [], 0.0
    for i, f in enumerate(fixes):
        if i:
            clock.now += step
        f = f if isinstance(f, dict) else {'speed': f}
        north_m += step * (f.get('speed') or 0.0) + 1.0
        la, lo = north(SQ[0], SQ[1], north_m)
        line = dict({'mode': 3, 'eph': 12.0, 'lat': round(la, 9), 'lon': round(lo, 9)}, **f)
        it.take(G.parse_line(tpv(**line)))
        out.append((it.latest() or {}).get('driving', 'absent'))
    return out, it, clock


ROUGH = {'speed': 15.0, 'eph': 129.2}
eq('two usable fixes at 3 m/s are driving', drive([3.0, 3.0])[0], [False, True])
eq('one fast fix is not driving: alone, between slow fixes, or between refused '
   'ones', [drive([0.0, 15.0, 0.0])[0], drive([ROUGH, 15.0, ROUGH])[0],
            drive([2.9, 3.0, 2.9])[0]],
   [[False] * 3] * 3)
eq('...nor two that are not in a row', drive([15.0, 0.5, 15.0, 2.0, 15.0])[0], [False] * 5)
eq('driving ends after 5 s under 1 m/s, and not before',
   drive([15.0, 15.0] + [0.5] * 6)[0], [False] + [True] * 6 + [False])
eq('...and a fix between 1 and 3 m/s holds it, and starts the 5 s again',
   drive([15.0, 15.0, 0.5, 0.5, 0.5, 0.5, 2.0, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5])[0],
   [False] + [True] * 11 + [False])
eq('...and does not start it', drive([2.9] * 6)[0], [False] * 6)
_r, _it, _clock = drive([15.0, 15.0, ROUGH, 15.0, 15.0])
_frozen = [{'speed': 15.0, 'lat': SQ[0], 'lon': SQ[1]}] * 8
eq('a stale or refused fix is never driving: a rough one ends it at once, and '
   'two usable fixes start it again', _r, [False, True, False, False, True])
_clock.now += 20.5
eq('...a stale one, past the staleness rule, ends it',
   ((_it.latest() or {}).get('driving'), (_it.latest() or {}).get('why')), (False, 'stale'))
eq('...a lat/lon stuck while the car says 15 m/s is refused as frozen, and is '
   'not driving', drive(_frozen)[0], [False] + [True] * 5 + [False] * 2)
eq('...nor is a fix that says no speed', drive([15.0, 15.0, {'speed': None}])[0],
   [False, True, False])
eq('...nor any NMEA fix, which the gate refuses as unrated',
   [(_x.take(G.parse_line(RMC)), (_x.latest() or {}).get('driving'))[1]
    for _x in [G.Phone('127.0.0.1:9')] for _ in range(3)], [False] * 3)
eq('fix() hands out the same answer as latest() while the fix is fresh',
   (drive([15.0, 15.0])[1].fix() or {}).get('driving'), True)

# The wall clock leaping, as NTP makes it do at the start of every shift on a
# Pi that booted in 1970. Every other check here hands Phone a clock; this one
# leaves it the default, because the default is what the rig runs on and the
# fault was in the default. With the wall clock, a fix taken before the leap
# was put 1,791,454,807 seconds old once the app stopped — and the panel would
# have said "GPS: no fix for 29857580 min".
#
# The module is loaded again with time.time already leaping, so a default
# bound to the wall clock would be bound to this one; restored either way.
import importlib                                              # noqa: E402

_real_time = time.time
_leap = [0.0]
time.time = lambda: _real_time() + _leap[0]
try:
    G2 = importlib.reload(G)
    phone = FakePhone(script=[RMC + '\r\n'])
    try:
        it = G2.Phone(phone.address).start()
        ok_('a fix arrives on the default clock', waited(lambda: it.fix() is not None))
        _leap[0] = 56 * 365.25 * 86400
        _aged = it.state().get('ageSeconds', 'absent')
        ok_('...and the wall clock leaping 56 years does not age it (%r)' % (_aged,),
            isinstance(_aged, (int, float)) and _aged < 5)
        eq('...nor turn a fresh fix stale', it.state()['state'], 'fixed')
        it.stop()
    finally:
        phone.close()
finally:
    time.time = _real_time
    importlib.reload(G)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d gps checks passed' % ok)
sys.exit(1 if bad else 0)
