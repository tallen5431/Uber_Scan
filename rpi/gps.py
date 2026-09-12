"""Where the rig is, when the phone is willing to say.

    python3 rpi/gps.py --from 100.75.197.117:2947

The Pi has no GPS and no clock. The phone in the mount has both, and a GPS
server app on it will hand them out over TCP on port 2947 — gpsd's port — to
anything that asks. This is the thing that asks.

WHY IT IS WORTH HAVING. The geocoder is the weak link in everything this rig
says about *where*. Handed "Chipotle" it answers with a Chipotle, and handed a
misread street it answers with a real street, both with the same confidence and
neither necessarily in the state the driver is in. A coordinate at the moment
the card was read turns every one of those questions from a guess into a
lookup bounded to where the car actually was.

WHAT IT MUST NOT DO, WHICH IS MOST OF THE DESIGN. This runs on a rig somebody
drives with. So:

  * It is OFF unless asked for, and a rig with no `--from` behaves exactly as
    it did before this file existed.
  * It never blocks the scan loop. All of it happens on one background thread
    behind a lock, and the loop's only contact with it is `fix()`, which reads
    a dict and returns.
  * It never blocks on the network holding a lock, so a phone that accepts the
    connection and then says nothing cannot wedge the reader.
  * A fix that has gone stale is NO FIX. This is the whole safety property and
    it is not optional: the app on the phone runs on a timer — the one this was
    written against showed "Runtime Left 4:48" — so it WILL stop mid-shift, and
    a position forty minutes old presented as a position is exactly the
    confidently-wrong number this project exists to avoid. Returning None is
    always available and always honest.
  * It reconnects quietly and for ever. A car loses its hotspot constantly and
    a line of log for each attempt would bury everything else.

THE CLOCK, WHICH IS A TRAP HERE. The Pi boots in 1970 and jumps when the
network arrives, so its wall clock cannot be compared against the GPS's own
timestamps to decide whether a fix is fresh — the two clocks disagree by
decades at boot. Staleness is therefore measured entirely against the local
clock: when WE received the line, against what the local clock says now. Both
readings come from the same wrong clock, so the error cancels and the answer is
right even while the rig thinks it is 1970. The GPS's own time is kept
alongside, because it is the true one and is worth having, but nothing here
decides anything with it.

TWO PROTOCOLS, BECAUSE PORT 2947 IS NOT A PROMISE. Real gpsd greets a client
with a JSON VERSION banner and then says nothing until it is asked to WATCH.
Several phone apps take the same port and simply push raw NMEA sentences at
whoever connects. Both are handled, and which one is in use is decided by
looking at what arrives rather than by a flag: the first line that parses as
either settles it. Sending gpsd's WATCH command at an NMEA server that did not
ask for it is the one thing that could upset a working setup, so it is sent
only after a gpsd banner has actually been seen.
"""

import argparse
import json
import re
import socket
import sys
import threading
import time

# Port 2947 is gpsd's, and every phone app that has borrowed the idea has
# borrowed the port with it.
DEFAULT_PORT = 2947

# How old a fix may be and still be a fix.
#
# The app pushes about once a second, so anything much over a couple of seconds
# already means something is wrong. Twenty is generous enough to ride out a
# hotspot stumbling without ever being generous enough to matter: a car at
# 60mph covers a third of a mile in that time, and every question this answers
# — which branch of a chain, which end of a metro — is asked at a scale where a
# third of a mile is nothing.
STALE_AFTER = 20.0

# Long enough that a phone which accepted the connection and then stopped
# talking is noticed, short enough that stop() is honoured promptly.
READ_TIMEOUT = 5.0

# A car is out of range most of the time and the phone's server app stops on
# its own timer, so failing to connect is the NORMAL state, not an error. The
# backoff climbs to half a minute and stays there: often enough to pick the
# phone up within a block of it coming back, rare enough to cost nothing.
BACKOFF = (1.0, 2.0, 4.0, 8.0, 15.0, 30.0)

# Null Island. Sitting at exactly zero in both is not a place anybody delivers
# to — it is what a receiver with no fix emits when it emits anything, and it
# is the one coordinate worth refusing outright.
NULL_ISLAND = 0.0001

_NMEA = re.compile(r'^\$(G[A-Z]RMC|G[A-Z]GGA),')


def parse_host(text, default_port=DEFAULT_PORT):
    """'host', 'host:2947' or '[::1]:2947' -> (host, port).

    Bracketed form handled because a Tailscale address is as likely to be IPv6
    as IPv4 here, and `fd7a:115c:a1e0::4601:c5d0` split on the last colon gives
    a host of `fd7a:115c:a1e0::4601` and a port of `c5d0`.
    """
    text = (text or '').strip()
    if not text:
        raise ValueError('no address')
    if text.startswith('['):
        end = text.find(']')
        if end < 0:
            raise ValueError('unclosed [ in %r' % text)
        host = text[1:end]
        rest = text[end + 1:]
        if rest.startswith(':'):
            return host, int(rest[1:])
        return host, default_port
    # An unbracketed address with more than one colon is a bare IPv6 literal,
    # not a host and a port.
    if text.count(':') > 1:
        return text, default_port
    if ':' in text:
        host, port = text.rsplit(':', 1)
        return host, int(port)
    return text, default_port


def _checksum_ok(line):
    """NMEA's own integrity check, and it is worth running.

    A sentence arrives over a phone hotspot in a moving car, and a line that
    lost a character mid-flight parses perfectly well into a position several
    degrees from the real one. That is a wrong number nothing downstream could
    ever catch, which makes this five lines the cheapest correctness in the
    file. A sentence with no `*XX` at all is accepted — some senders omit it —
    but one that carries a checksum has to pass it.
    """
    star = line.rfind('*')
    if star < 0:
        return True
    want = line[star + 1:star + 3]
    if len(want) < 2:
        return False
    got = 0
    for ch in line[1:star]:
        got ^= ord(ch)
    try:
        return got == int(want, 16)
    except ValueError:
        return False


def _degrees(value, hemi):
    """NMEA's ddmm.mmmm, which is not degrees and is not minutes."""
    try:
        raw = float(value)
    except (TypeError, ValueError):
        return None
    deg = int(raw / 100)
    out = deg + (raw - deg * 100) / 60.0
    if hemi in ('S', 'W'):
        out = -out
    if out != out or abs(out) == float('inf'):
        return None
    return out


def _sane(lat, lon):
    if lat is None or lon is None:
        return False
    if lat != lat or lon != lon:                    # NaN
        return False
    if abs(lat) > 90 or abs(lon) > 180:
        return False
    if abs(lat) < NULL_ISLAND and abs(lon) < NULL_ISLAND:
        return False
    return True


def parse_line(line):
    """One line from the phone -> a fix, or None.

    Returns a dict with at least lat and lon, or None for anything that is not
    a position: a gpsd banner, a sentence with no fix in it, a corrupt one, a
    blank. None is not an error here — most lines are not positions.
    """
    line = (line or '').strip()
    if not line:
        return None

    if line.startswith('{'):
        try:
            msg = json.loads(line)
        except ValueError:
            return None
        if not isinstance(msg, dict) or msg.get('class') != 'TPV':
            return None
        # mode: 0 unknown, 1 no fix, 2 two-dimensional, 3 three. Below 2 there
        # is no position, whatever else the record carries.
        mode = msg.get('mode')
        if isinstance(mode, (int, float)) and mode < 2:
            return None
        lat, lon = msg.get('lat'), msg.get('lon')
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            return None
        if isinstance(lat, bool) or isinstance(lon, bool):
            return None
        if not _sane(lat, lon):
            return None
        out = {'lat': float(lat), 'lon': float(lon), 'source': 'gpsd'}
        for here, there in (('speed', 'speed'), ('heading', 'track'),
                            ('altitude', 'alt')):
            v = msg.get(there)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out[here] = float(v)
        when = msg.get('time')
        if isinstance(when, str) and when:
            out['gpsTime'] = when
        return out

    if not _NMEA.match(line):
        return None
    if not _checksum_ok(line):
        return None
    body = line.split('*')[0]
    f = body.split(',')
    kind = f[0][3:]
    if kind == 'RMC':
        # $xxRMC,time,status,lat,NS,lon,EW,knots,track,date,...
        if len(f) < 10 or f[2] != 'A':
            return None
        lat, lon = _degrees(f[3], f[4]), _degrees(f[5], f[6])
        if not _sane(lat, lon):
            return None
        out = {'lat': lat, 'lon': lon, 'source': 'nmea'}
        try:
            # Knots on the wire; metres per second everywhere in this file, to
            # match what gpsd reports, so that a caller never has to ask which
            # protocol a number came from.
            out['speed'] = float(f[7]) * 0.514444
        except (TypeError, ValueError):
            pass
        try:
            out['heading'] = float(f[8])
        except (TypeError, ValueError):
            pass
        return out
    # $xxGGA,time,lat,NS,lon,EW,quality,sats,hdop,alt,...
    if len(f) < 7:
        return None
    if f[6] in ('', '0'):                            # quality 0 is "no fix"
        return None
    lat, lon = _degrees(f[2], f[3]), _degrees(f[4], f[5])
    if not _sane(lat, lon):
        return None
    out = {'lat': lat, 'lon': lon, 'source': 'nmea'}
    if len(f) > 9:
        try:
            out['altitude'] = float(f[9])
        except (TypeError, ValueError):
            pass
    return out


class Phone(object):
    """The phone's GPS, read on a thread, never in the way.

    `fix()` is the whole interface the rig uses and it is always safe to call:
    it takes a lock, reads two numbers and a timestamp, and returns. It never
    touches the network, so the scan loop cannot be made slow by a phone that
    is slow.
    """

    def __init__(self, address, stale_after=STALE_AFTER,
                 connect=None, clock=time.time):
        self.host, self.port = parse_host(address)
        self.stale_after = stale_after
        # Injected so the suite can drive this against a socket it controls
        # without opening one, and so the staleness rules can be tested without
        # spending twenty real seconds on each case.
        self._connect = connect or (
            lambda h, p: socket.create_connection((h, p), timeout=READ_TIMEOUT))
        self._clock = clock
        self._lock = threading.Lock()
        self._fix = None
        self._at = 0.0
        self._state = 'off'
        self._error = None
        self._lines = 0
        self._stop = threading.Event()
        self._thread = None

    # --- what the rig asks -------------------------------------------------

    def fix(self):
        """Where the rig is, or None. None whenever that is the honest answer.

        A copy, not the stored dict: a caller that kept the reference and read
        it later would be reading whatever the thread had written since, which
        is a fix with no timestamp attached to it.
        """
        with self._lock:
            if self._fix is None:
                return None
            age = self._clock() - self._at
            if age > self.stale_after or age < 0:
                return None
            out = dict(self._fix)
        out['ageSeconds'] = round(age, 2)
        return out

    def state(self):
        """A word for the dashboard, and why, when there is a why.

        'off'        never started
        'looking'    started, nothing received yet, or trying to reconnect
        'fixed'      a position arrived within stale_after
        'stale'      a position arrived, and it is too old to use
        """
        with self._lock:
            word, why, fix, at, lines = (self._state, self._error, self._fix,
                                         self._at, self._lines)
        # 'off' outranks the fix. A position stays usable for `stale_after`
        # after the reader is stopped — `fix()` will rightly still hand it over
        # — but the word here answers "is anything reading the phone", and
        # after stop() the answer is no. Letting the leftover fix paint it
        # 'fixed' would put a green light on a subsystem that is not running,
        # which is this project's own worst failure shape in miniature.
        if fix is not None and word != 'off':
            age = self._clock() - at
            word = 'fixed' if 0 <= age <= self.stale_after else 'stale'
        return {'state': word, 'error': why, 'lines': lines,
                'address': '%s:%d' % (self.host, self.port)}

    # --- the thread --------------------------------------------------------

    def start(self):
        if self._thread is not None:
            return self
        self._stop.clear()
        with self._lock:
            self._state = 'looking'
        # A daemon, so that a rig shutting down is never held open by a phone
        # that stopped answering.
        self._thread = threading.Thread(target=self._run, name='gps',
                                        daemon=True)
        self._thread.start()
        return self

    def stop(self, timeout=2.0):
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=timeout)
        with self._lock:
            self._state = 'off'

    def _run(self):
        attempt = 0
        while not self._stop.is_set():
            try:
                self._session()
                attempt = 0            # it worked; the next loss starts over
            except Exception as e:     # noqa: BLE001 - a car; everything fails
                with self._lock:
                    self._error = '%s: %s' % (type(e).__name__, e)
                    self._state = 'looking'
                attempt += 1
            if self._stop.is_set():
                break
            # Event.wait, not sleep: a stop during the backoff is honoured at
            # once rather than up to thirty seconds later.
            self._stop.wait(BACKOFF[min(attempt, len(BACKOFF) - 1)])

    def _session(self):
        sock = self._connect(self.host, self.port)
        try:
            sock.settimeout(READ_TIMEOUT)
            rest = b''
            asked = False
            while not self._stop.is_set():
                try:
                    chunk = sock.recv(4096)
                except socket.timeout:
                    # Nothing for a few seconds is ordinary between sentences;
                    # what it must not do is hide a stop().
                    continue
                if not chunk:
                    raise IOError('the phone closed the connection')
                rest += chunk
                # Split on the wire's own line ending, and keep the tail: a
                # sentence arrives in two packets often enough that parsing
                # whatever a single recv() happened to contain would drop one
                # fix in several and, worse, feed half a line to the parser.
                *lines, rest = rest.replace(b'\r\n', b'\n').split(b'\n')
                if len(rest) > 65536:
                    raise IOError('a line with no end to it')
                for raw in lines:
                    line = raw.decode('utf-8', 'replace').strip()
                    if not line:
                        continue
                    with self._lock:
                        self._lines += 1
                    # Real gpsd says nothing until it is watched, and announces
                    # itself first. Asked only here, and only once, so that an
                    # app which merely borrowed the port is never sent a command
                    # it did not advertise.
                    if not asked and line.startswith('{') \
                            and '"VERSION"' in line:
                        asked = True
                        sock.sendall(
                            b'?WATCH={"enable":true,"json":true};\n')
                        continue
                    got = parse_line(line)
                    if got is None:
                        continue
                    with self._lock:
                        self._fix = got
                        self._at = self._clock()
                        self._state = 'fixed'
                        self._error = None
        finally:
            try:
                sock.close()
            except Exception:          # noqa: BLE001
                pass


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--from', dest='address', required=True,
                    metavar='HOST[:PORT]',
                    help='the phone running the GPS server app, e.g. '
                         '100.75.197.117:2947 — its Tailscale address rather '
                         'than its hotspot one, so it keeps working when the '
                         'rig is on wifi at home')
    ap.add_argument('--seconds', type=float, default=30.0,
                    help='how long to watch for (0 = until interrupted)')
    ap.add_argument('--stale', type=float, default=STALE_AFTER)
    args = ap.parse_args(argv)

    phone = Phone(args.address, stale_after=args.stale).start()
    print('asking %s:%d — press ctrl-c to stop' % (phone.host, phone.port))
    started = time.time()
    said = None
    try:
        while args.seconds <= 0 or time.time() - started < args.seconds:
            got = phone.fix()
            if got:
                line = '%.5f, %.5f  (%s, %.1fs old)' % (
                    got['lat'], got['lon'], got['source'], got['ageSeconds'])
            else:
                s = phone.state()
                line = '%s%s' % (s['state'],
                                 ' — %s' % s['error'] if s['error'] else '')
            if line != said:
                print(line)
                said = line
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        phone.stop()
    got = phone.fix()
    if got:
        return 0
    s = phone.state()
    print('no fix. %s%s' % (s['state'], ' — %s' % s['error'] if s['error'] else ''),
          file=sys.stderr)
    print('Check the app is running and showing a GPS lock, that the address '
          'is right, and that the rig can reach it: nc -z %s %d'
          % (phone.host, phone.port), file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
