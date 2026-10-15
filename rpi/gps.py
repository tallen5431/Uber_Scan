"""Where the rig is, when the receiver is willing to say.

    python3 rpi/gps.py --from 127.0.0.1               # gpsd on the Pi
    python3 rpi/gps.py --from 100.x.y.z:2947          # a phone's server app

Anything that speaks on TCP port 2947 — gpsd's port — can hand the rig a
position, and this is the thing that asks. It was written for a phone in the
mount running a GPS server app, because the Pi had no GPS of its own. It has
one now: a VK-162 (u-blox 7) on USB, read by gpsd on the Pi, and on the owner's
rig `--from 127.0.0.1` reads it. Both routes are still served, and everything
below about a source that stops is as true of a USB lead knocked out as of an
app on a timer.

WHAT A FIX SAYS ABOUT ITSELF, WHICH IS NOW KEPT. A position is only as good as
the receiver's own account of it, and that account used to be thrown away here:
gpsd's `mode` and its error estimate `eph` arrived on every TPV and were
dropped, so a fix from four satellites at an HDOP of 6.8 and one from a clear
sky were the same two numbers to everything downstream. Each fix now carries
`mode` and `err` (gpsd's `eph`, metres), and `epx`/`epy` when sent; an NMEA
sentence carries what it gives — GGA its fix `quality` and `hdop` — and None
for what it does not. This file REPORTS them and refuses nothing it did not
refuse before. Whether a fix is good enough to show or compare is `usable()`'s
question, asked in one place, and its answer travels on the fix as `ok` and
`why`.

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
    always available and always honest. `latest()` is the one exception, and
    it says so on what it returns: the heartbeat hands the panel the newest fix
    whatever its age, judged `stale` past the limit, so a dot that stopped
    moving is drawn grey rather than vanishing with nothing saying why.
  * It reconnects quietly and for ever. A car loses its hotspot constantly and
    a line of log for each attempt would bury everything else.

THE CLOCK, WHICH IS A TRAP HERE. The Pi boots in 1970 and jumps when the
network arrives, so its wall clock cannot be compared against the GPS's own
timestamps to decide whether a fix is fresh — the two clocks disagree by
decades at boot. Staleness is therefore measured entirely against the local
clock: when WE received the line, against what the local clock says now. Both
readings come from the same clock, so its error cancels and the answer is right
even while the rig thinks it is 1970. The GPS's own time is kept alongside,
because it is the true one and is worth having, but nothing here decides
anything with it.

...and that local clock is the MONOTONIC one, because "the same clock" was not
enough. Both readings came off the wall clock, so the error cancelled only
until the wall clock moved between them — which is what NTP does once, by
decades, at the start of every shift. Measured through Phone with that clock
injected: a fix taken at boot, the app stopping, NTP arriving, and state() put
the fix 1,791,454,807 seconds old — "GPS: no fix for 29857580 min" on the
driving panel. The monotonic clock does not jump, and an age is all it is used
for here.

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
import math
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

# How rough a fix may be, in metres of gpsd's own error estimate (`eph`), and
# still be used for anything shown or compared. Provisional: the first week of
# logged shifts is what sets it, from how often a moving car stays inside it.
#
# Why an error figure and not the mode: MODE BOUNDS NOTHING. Run through real
# gpsd 3.25 by the design study (gpsuses/verify-3/run.out), a four-satellite
# stream at HDOP 6.8 came out mode 3 with eph 129.2 m, every TPV of it — and a
# stream whose GSA said 2D but whose GGA carried an altitude was promoted to
# mode 3 too. A gate on `mode == 3` alone would have passed all of them.
#
# Why 50: the owner's VK-162 read eph 27.8 m on mode 3 indoors (epx 17.8, epy
# 12.8), so a working receiver sits well inside it. Where gpsd derives eph
# from HDOP (its NMEA path: eph = HDOP x 19 m — measured, HDOP 2.6 gave 49.4
# and 2.7 gave 51.3), 50 m is HDOP 2.6 or better. And at the scale of the one
# figure a position feeds today, it is small: moving the car 50 m in a random
# direction moved live.html's "+N mi out of your way" by 0.017 mi at the
# median, 0.054 at p95 and 0.062 at most (the 2 x 50 m bound), over 20,000
# random metro triples through the real MV.detour, and flipped the half-mile
# call on 11 of them (0.06%). The 129.2 m fix moved it by up to 0.160 mi. So
# 50 m is not where the detour's error lives — the pins are — and the limit is
# there to refuse a fix that says it is lost, not to grade a working one.
#
# eph is a model: gpsd's own documentation calls its certainty unknown, and it
# cannot see multipath. The parked-scatter check in the first week is what says
# whether it is an honest bound on this receiver.
FIX_ERR_MAX = 50.0

# A POSITION THAT DOES NOT MOVE, WHICH IS WHAT THE OWNER'S RECEIVER SENT.
#
# gpsd switched the VK-162 into u-blox binary (its log says `"driver":"u-blox"`,
# PROTVER 14.00) and from then on its TPV `lat`/`lon` stopped changing while
# everything else on the same line went on updating. Five consecutive TPVs,
# a second apart, carried bit-identical lat/lon while `ecefx` moved +0.11 m and
# `ecefy` -2.65 m (the owner's coordinates are not repeated here, ECEF being
# a coordinate too); an hour and a half of
# driving later the heartbeat still carried the same point, 0.6 s old, gpsOk
# true. A u-blox 7 has no NAV-PVT, so gpsd's lat/lon come from NAV-POSLLH, and
# what this receiver plainly WAS sending is NAV-SOL — the receiver's solution
# as an earth-centred x/y/z, which gpsd reports as `ecefx/y/z`. The frozen
# point is not even where that solution put the car: the ECEF on those five
# lines lies 3,048.6-3,048.8 m WEST of the reported lat/lon (the east-west
# part alone, which needs no altitude and no `ecefz` to measure — measured
# here from the two printed lines). Every fix the gate passed that day was a
# number with a fresh age and a good error estimate, three kilometres from the
# car: this project's worst fault in its plainest form.
#
# Two defences, both below. parse_line works lat/lon out of the line's own ECEF
# and uses it when the two disagree (ECEF_AGREE); and Phone notices a lat/lon
# that has not moved by one bit while the car plainly has, which usable()
# refuses as `frozen` (FROZEN_AFTER, MOVING, ECEF_MOVED). The cure at the
# source is gpsd's `-b`; see rpi/README.md, "A USB receiver on the Pi".

# WGS84, which is the datum both gpsd's lat/lon and its ECEF are in.
WGS84_A = 6378137.0
WGS84_F = 1 / 298.257223563
WGS84_E2 = WGS84_F * (2 - WGS84_F)

# How far gpsd's lat/lon may be from its own ECEF, in metres, before the ECEF
# is believed instead.
#
# When both are the receiver's, they are ONE navigation solution printed two
# ways — NAV-POSLLH to 1e-7 degree (about a centimetre) and NAV-SOL to a
# centimetre — so a working receiver's two agree to centimetres, and anything
# larger is one of them not being this epoch's. Why 50 rather than one metre:
# gpsd merges the messages of a cycle into one TPV, and a cycle split across
# two epochs puts the halves one epoch apart, which at 1 Hz is the car's speed
# in metres; 50 m is 112 mph for a second. And 50 is FIX_ERR_MAX: a
# disagreement this file tolerates is never larger than an error the gate
# already passes as usable, so keeping gpsd's figure inside it costs nothing
# the gate had not agreed to. The owner's frozen fix disagreed by over 3 km.
ECEF_AGREE = 50.0

# How long a lat/lon may stay bit-identical while the car is moving, in
# seconds, before usable() calls it `frozen`.
#
# A moving car cannot repeat a lat/lon to the last printed bit: gpsd prints
# nine decimals (0.1 mm), and at MOVING the car covers two metres an epoch.
# Five rather than one because gpsd can send more than one TPV for one epoch,
# and a repeat of the same epoch is not a frozen receiver; five consecutive
# identical TPVs is exactly what the owner's log showed, and five seconds is a
# quarter of STALE_AFTER, so a frozen position is refused well before an old
# one would have been.
FROZEN_AFTER = 5.0

# What counts as moving while the lat/lon stands still: the TPV's own `speed`,
# or the speed of its ECEF velocity (`ecefvx/vy/vz`), over MOVING m/s — or its
# ECEF position more than ECEF_MOVED metres from where it was when the lat/lon
# last changed.
#
# MOVING is 2 m/s (4.5 mph): a parked receiver's speed is noise around zero,
# and the owner's five frozen lines, taken two minutes after the rig booted,
# moved their ECEF 2.65 m in four seconds — 0.66 m/s, a third of this (whether
# the car was parked then is the owner's account, not measured here).
# ECEF_MOVED is 25 m: over this receiver's own stated one-sigma figures,
# measured indoors on the rig (epx 17.8, epy 12.8, ecefpAcc 15.7), so a parked
# receiver wandering inside its own error is not read as a car driving; and
# under ECEF_AGREE, so this is the arm that refuses a frozen lat/lon in the
# stretch before its own ECEF has moved far enough to be used instead.
#
# A receiver PARKED in a real static hold — lat/lon held, ECEF inside that
# jitter, speed near zero — passes, because it is right.
MOVING = 2.0
ECEF_MOVED = 25.0

# WHETHER THE CAR IS BEING DRIVEN, for the panel's driving form: live.html
# shows the verdict, the pay, the rate, the pair line and the order in the car,
# larger, and hides the rest of the card until the car stops. Decided HERE, on
# every fix as it arrives, and nowhere else: the rule sees the receiver's own
# one-a-second fixes where the heartbeat carries one in four, and it rides the
# beat as the fix's `driving` (Phone.latest()) the way the gate's answer rides
# it as `ok`. The page asks nothing again.
#
# Driving once DRIVING_FIXES consecutive usable fixes read DRIVING_SPEED or
# more; not driving once usable fixes have read under STOPPED_SPEED for
# STOPPED_FOR seconds; between the two speeds the state holds. A refused fix
# (or one with no speed) never starts it and breaks a run of fast fixes, and
# while driving it changes nothing: the state is HELD until no usable fix has
# come for DRIVING_HOLD seconds, and then it ends. A stale fix is past that by
# construction, so a car this file cannot place is never said to be moving for
# longer than the hold, and the full card is what a driver sees when nothing
# is known. All of it measured by replaying the 12 Oct shift's gpspipe logs —
# 31,140 fixes over 7.9 hours, 836 of them refused (818 rough, 18 frozen) —
# through Phone.take() itself:
#
#   3 m/s (6.7 mph) to start. Over the minutes the car stood still (60 s
#   windows whose median speed was under 0.2 m/s: 15,846 fixes) the receiver
#   read p50 0.04 m/s, p99 0.42 — noise well under it.
#   Two fixes in a row, so one stray reading cannot start it. This shift
#   sent no such reading: its 11 runs of exactly ONE usable fix at 3 m/s or
#   more were 8 between two refused fixes at 11-28 m/s and 3 on the line
#   (2.9, 3.0, 2.9), none a parked receiver's spike, and with the hold below
#   a one-fix rule differs little here (84 entries against 86). It costs at
#   most a second at the start of a drive.
#   Under 1 m/s for 5 s to stop. 19 of those 15,846 still fixes read 1 m/s or
#   more. Of the 213 stretches under 1 m/s, 58 lasted under 5 s — a slowdown
#   for a turn, a stop sign rolled — and keep the driving form; 97 lasted 5 s
#   to a minute — a light — and give the driver the card back while stopped.
#   The band between holds. Without it (in and out at 3 m/s) the shift had
#   106 entries to driving and 29 stops under 10 s; with it 86 and 12.
#   A 10 s hold through refused fixes. Ending the state at the first refused
#   fix, as this did first, gave 123 entries, 43 of them ended by a refused
#   fix rather than a stop, 43 stops under 10 s, and a full card for one beat
#   mid-drive 14-23 times in the 7.9 hours (by the beat's phase). Held, 86
#   entries, 83 of the 85 ends a stop and 2 the hold running out, 12 stops
#   under 10 s (11 of them real: 5 s still, then away), and 3-5 such beats.
#   Ten seconds, or this Phone's stale_after where that is shorter (_hold()):
#   on the rig the staleness rule is 20 s, so the hold is the 10.
#
# What it costs, measured the same way: 35.8% of the shift in the driving
# form, and the panel changing form about 21 times an hour on a 4 s beat.
DRIVING_SPEED = 3.0
DRIVING_FIXES = 2
STOPPED_SPEED = 1.0
STOPPED_FOR = 5.0
DRIVING_HOLD = 10.0

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


def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def ecef_to_lla(x, y, z):
    """Earth-centred x/y/z in metres -> (lat, lon, height above the
    ellipsoid), WGS84, or None for a point nowhere near the earth's surface.

    Longitude is exact (atan2). Latitude by Bowring's closed form, which
    needs no iteration and is good to well under a millimetre at any height a
    car can be at — rpi/test_gps.py holds it to half a metre against points
    built the other way, from the Dead Sea shore to Everest and both poles.
    Pure arithmetic, so a NaN in is a None out, not a position.
    """
    if not all(_number(v) for v in (x, y, z)):
        return None
    r = math.sqrt(x * x + y * y + z * z)
    # A receiver with no solution sends zeros; one with a corrupt one can send
    # anything. The ellipsoid's radius runs 6,356,752 m (pole) to 6,378,137 m
    # (equator); outside 6,200-6,500 km it is not a car's position.
    if not 6.2e6 < r < 6.5e6:
        return None
    a, e2 = WGS84_A, WGS84_E2
    b = a * (1 - WGS84_F)
    ep2 = (a * a - b * b) / (b * b)
    p = math.hypot(x, y)
    lon = math.atan2(y, x)
    th = math.atan2(z * a, p * b)
    lat = math.atan2(z + ep2 * b * math.sin(th) ** 3,
                     p - e2 * a * math.cos(th) ** 3)
    n = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
    # Height off whichever of cos and sin is the larger, so that neither the
    # equator nor a pole divides by nothing.
    if abs(math.cos(lat)) > abs(math.sin(lat)):
        h = p / math.cos(lat) - n
    else:
        h = z / math.sin(lat) - n * (1 - e2)
    return math.degrees(lat), math.degrees(lon), h


def metres_apart(lat1, lon1, lat2, lon2):
    """Ground distance between two nearby points, in metres.

    Equirectangular on a sphere of the WGS84 semi-major axis: at the distances
    it is asked about here — tens of metres to a few kilometres — its error is
    a small fraction of a percent, far inside any bound it is compared with.
    """
    k = math.pi / 180.0
    dx = (lon2 - lon1) * k * math.cos((lat1 + lat2) / 2.0 * k)
    dy = (lat2 - lat1) * k
    return WGS84_A * math.hypot(dx, dy)


def fresh(age, stale_after=STALE_AFTER):
    """The staleness rule, stated once: an age in seconds, on the local
    monotonic clock, no older than `stale_after` and not negative.

    fix(), state() and usable() all ask this, on the same unrounded age, so the
    position, the word and the gate cannot disagree about the last tenth of a
    second before a fix goes stale. A missing age is not fresh: a fix nobody
    can date cannot be said to be where the car is now.
    """
    return _number(age) and 0 <= age <= stale_after


def usable(fix, age=None, stale_after=STALE_AFTER):
    """(True, None) when a fix may be shown or compared, else (False, why).

    THE gate, and the only one. Nothing on the panel, the maps or the journal
    asks this question again: Phone puts the answer on every fix it hands out
    as `ok` and `why`, journal rows write it as `gpsOk` and `gpsWhy`, and the
    pages read those. A second copy in JavaScript would be a second rule the
    first time either moved.

    `why` is one word, and the pages phrase it — live.html and map.html each
    name every word below, and rpi/test_lint.py holds them to this function:

      unrated  no error estimate in metres: an NMEA sentence, which states
               none, or a TPV gpsd sent without `eph`
      nomode   no 2D or 3D mode stated
      rough    an error estimate over FIX_ERR_MAX
      frozen   a lat/lon that has not changed by one bit for over
               FROZEN_AFTER seconds (`heldFor`, which Phone puts on the fix)
               while the car is moving: its `speed` or `ecefSpeed` over
               MOVING, or its ECEF over ECEF_MOVED metres from where it was
               when the lat/lon last changed (`heldMoved`). What the owner's
               VK-162 did under gpsd's binary mode; see FROZEN_AFTER.
      stale    older than `stale_after` (or of no known age)

    Quality before age, deliberately. A stale fix is drawn grey where it was,
    and only a fix that was good when it arrived has a "where it was" worth
    drawing; a rough one is not drawn at all.

    `age` is the caller's unrounded figure when it has one; otherwise the
    fix's own `ageSeconds`.
    """
    err = fix.get('err')
    if not _number(err):
        return False, 'unrated'
    mode = fix.get('mode')
    if not (_number(mode) and mode >= 2):
        return False, 'nomode'
    if err > FIX_ERR_MAX:
        return False, 'rough'
    # A good error estimate says nothing here: the owner's frozen fix carried
    # eph 27.8 m, well inside FIX_ERR_MAX, three kilometres from the car.
    held = fix.get('heldFor')
    if _number(held) and held > FROZEN_AFTER and any(
            _number(fix.get(k)) and fix[k] > limit
            for k, limit in (('speed', MOVING), ('ecefSpeed', MOVING),
                             ('heldMoved', ECEF_MOVED))):
        return False, 'frozen'
    if not fresh(fix.get('ageSeconds') if age is None else age, stale_after):
        return False, 'stale'
    return True, None


def parse_line(line):
    """One line from the phone -> a fix, or None.

    Returns a dict with at least lat and lon, or None for anything that is not
    a position: a gpsd banner, a sentence with no fix in it, a corrupt one, a
    blank. None is not an error here — most lines are not positions.

    Every fix carries `mode` and `err` (metres), None where the line did not
    say. Kept, not judged: see usable().
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
        out = {'lat': float(lat), 'lon': float(lon), 'source': 'gpsd',
               # What the receiver says about this position: 2 or 3, and its
               # horizontal error estimate in metres. Dropped here until now,
               # so a four-satellite fix gpsd itself put at 129 m and a clear
               # sky's were indistinguishable downstream. None when not sent.
               'mode': int(mode) if _number(mode) else None,
               'err': float(msg['eph']) if _number(msg.get('eph')) else None}
        # ...and its two halves, longitude-wise and latitude-wise, only when
        # sent: reported, never judged on.
        for half in ('epx', 'epy'):
            if _number(msg.get(half)):
                out[half] = float(msg[half])
        for here, there in (('speed', 'speed'), ('heading', 'track'),
                            ('altitude', 'alt')):
            v = msg.get(there)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out[here] = float(v)
        when = msg.get('time')
        if isinstance(when, str) and when:
            out['gpsTime'] = when
        _ecef(msg, out)
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
        # RMC says valid or void and nothing about how good: no mode, no error.
        out = {'lat': lat, 'lon': lon, 'source': 'nmea', 'mode': None,
               'err': None}
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
    # GGA's fix quality (1 GPS, 2 DGPS, ...) and HDOP, which are what it gives.
    # Neither is a mode or a distance: HDOP is a ratio, and turning it into
    # metres takes a constant this file would be inventing — gpsd uses 19 m
    # for it — so `err` stays None and usable() says `unrated`.
    out = {'lat': lat, 'lon': lon, 'source': 'nmea', 'mode': None,
           'err': None, 'quality': int(f[6]) if f[6].isdigit() else None}
    if len(f) > 8:
        try:
            out['hdop'] = float(f[8])
        except (TypeError, ValueError):
            pass
    if len(f) > 9:
        try:
            out['altitude'] = float(f[9])
        except (TypeError, ValueError):
            pass
    return out


def _ecef(msg, out):
    """The TPV's own ECEF, checked against its lat/lon — and believed instead
    of them when the two disagree by more than ECEF_AGREE metres.

    Adds to `out`, in place: `ecef` ([x, y, z], metres) and `ecefGap` (metres
    between gpsd's lat/lon and the ECEF's) whenever the line carries all
    three; `ecefSpeed` (m/s) from `ecefvx/vy/vz`. On disagreement the fix's
    lat/lon BECOME the ECEF's, `source` becomes 'ecef', gpsd's pair is kept as
    `gpsdLat`/`gpsdLon`, and `note` says what was done — a fix that was
    corrected says so on itself. The error estimate is left as gpsd sent it,
    and the gate still asks it: whether that `eph` is the receiver's own
    accuracy on this path or gpsd's HDOP model has not been measured.
    A TPV with no ECEF is left exactly as it came.
    """
    v = [msg.get(k) for k in ('ecefvx', 'ecefvy', 'ecefvz')]
    if all(_number(c) for c in v):
        out['ecefSpeed'] = math.sqrt(sum(c * c for c in v))
    xyz = [msg.get(k) for k in ('ecefx', 'ecefy', 'ecefz')]
    got = ecef_to_lla(*xyz)
    if got is None:
        return
    lat, lon = got[0], got[1]
    out['ecef'] = [float(c) for c in xyz]
    gap = metres_apart(out['lat'], out['lon'], lat, lon)
    out['ecefGap'] = round(gap, 1)
    if gap > ECEF_AGREE:
        out['gpsdLat'], out['gpsdLon'] = out['lat'], out['lon']
        out['lat'], out['lon'] = lat, lon
        out['source'] = 'ecef'
        out['note'] = ("gpsd's lat/lon were %.0f m from its own ECEF; "
                       'the ECEF position is used' % gap)


class Phone(object):
    """The phone's GPS, read on a thread, never in the way.

    `fix()` is the whole interface the rig uses and it is always safe to call:
    it takes a lock, reads two numbers and a timestamp, and returns. It never
    touches the network, so the scan loop cannot be made slow by a phone that
    is slow.
    """

    def __init__(self, address, stale_after=STALE_AFTER,
                 connect=None, clock=time.monotonic):
        self.host, self.port = parse_host(address)
        self.stale_after = stale_after
        # Injected so the suite can drive this against a socket it controls
        # without opening one, and so the staleness rules can be tested without
        # spending twenty real seconds on each case. Monotonic by default — see
        # THE CLOCK at the top of this file for what the wall clock did.
        self._connect = connect or (
            lambda h, p: socket.create_connection((h, p), timeout=READ_TIMEOUT))
        self._clock = clock
        self._lock = threading.Lock()
        self._fix = None
        self._at = 0.0
        self._state = 'off'
        self._error = None
        self._lines = 0
        # When the lat/lon last changed, and where the ECEF put the car then:
        # see _held().
        self._held_at = None
        self._held_from = None
        # Whether the car is being driven, the two counts that decide it, and
        # when the last usable fix came, which the hold runs from: see
        # DRIVING_SPEED, DRIVING_HOLD and _moving().
        self._driving = False
        self._fast = 0
        self._slow_since = None
        self._good_at = None
        self._stop = threading.Event()
        self._thread = None

    # --- what the rig asks -------------------------------------------------

    def fix(self):
        """Where the rig is, or None. None whenever that is the honest answer.

        A copy, not the stored dict: a caller that kept the reference and read
        it later would be reading whatever the thread had written since, which
        is a fix with no timestamp attached to it.

        Judged on the way out: `ok` and `why` are usable()'s answer for this
        fix at this age, so whoever stores or sends it sends the answer with
        it. A fix past `stale_after` is still None here, exactly as before.
        """
        got, age = self._newest()
        if got is None or not fresh(age, self.stale_after):
            return None
        return self._judged(got, age)

    def latest(self):
        """The newest fix whatever its age, judged — or None if none came.

        For the heartbeat and nothing that records: the panel draws where the
        car was, grey once the fix is `stale`, and a fix that went stale would
        otherwise leave the dot to vanish with nothing saying why. A clock
        that ran backwards past it gives no age and `stale`, as state() does.
        """
        got, age = self._newest()
        return None if got is None else self._judged(got, age)

    def take(self, got):
        """Store one fix from parse_line as the newest, at this clock's now.

        The one way a fix gets in: the session calls it for every position
        the phone or gpsd sends, and tools/shift_report.py calls it for every
        position in a `gpspipe -w -uu` log, with a clock that reads each
        line's own stamp. So a logged shift is judged by the same `_held`
        bookkeeping and the same usable() the live rig used — a frozen
        lat/lon is refused in the log exactly as it was on the panel — and
        there is no second copy of either to drift.
        """
        with self._lock:
            self._at = self._clock()
            self._held(got, self._at)
            self._moving(got, self._at)
            self._fix = got
            self._state = 'fixed'
            self._error = None

    def _newest(self):
        with self._lock:
            if self._fix is None:
                return None, None
            got = dict(self._fix)
            now = self._clock()
            got['driving'] = self._still_driving(now)
            return got, now - self._at

    def _judged(self, got, age):
        got['ageSeconds'] = round(age, 2) if age >= 0 else None
        got['ok'], got['why'] = usable(got, age=age, stale_after=self.stale_after)
        # ...and how many more seconds it stays inside the staleness rule, for
        # whoever is handed it and keeps it: the panel ages a beat's fix on its
        # own clock once the beat stops coming, and greys it when this runs
        # out, without a copy of the rule in JavaScript. Zero once stale.
        got['freshFor'] = (round(self.stale_after - age, 1)
                           if fresh(age, self.stale_after) else 0.0)
        return got

    def _held(self, got, now):
        """Put on a fresh fix how long its lat/lon have stood bit-identical
        (`heldFor`, seconds by this clock) and, when it carries ECEF, how far
        the ECEF has moved over the ground meanwhile (`heldMoved`, metres).
        Called holding the lock, with the fix about to be stored.

        Reported, not judged: usable() decides whether a held position is a
        parked car or a frozen receiver, from these and the speed. Bit-identical
        because that is what a receiver repeating itself sends, and nothing
        coarser is safe — a car at a light moves its lat/lon by millimetres.
        Horizontal, because a parked receiver's height wanders further than
        its position and a car does not drive upward.
        """
        prev = self._fix
        here = got.get('ecef')
        here = ecef_to_lla(*here) if here else None
        if prev is None or got['lat'] != prev['lat'] \
                or got['lon'] != prev['lon']:
            self._held_at, self._held_from = now, here
        elif self._held_from is None:
            self._held_from = here
        got['heldFor'] = round(now - self._held_at, 2)
        if here is not None and self._held_from is not None:
            got['heldMoved'] = round(metres_apart(
                self._held_from[0], self._held_from[1], here[0], here[1]), 1)

    def _hold(self):
        """How long a driving state outlives its last usable fix, in seconds:
        DRIVING_HOLD, or this Phone's staleness rule where that is shorter, so
        the state never outlives the fix it stands on."""
        return min(DRIVING_HOLD, self.stale_after)

    def _still_driving(self, now):
        """Whether the car is being driven as of `now`: the state, while the
        last usable fix is no older than the hold. Asked as a fix is handed
        out as well as when one arrives, because a receiver that has gone
        quiet sends nothing that would end it."""
        return (self._driving and self._good_at is not None
                and now - self._good_at <= self._hold())

    def _moving(self, got, now):
        """Move the driving state on by one fix, as it arrives: the rule under
        DRIVING_SPEED. Called holding the lock, after _held(), whose `heldFor`
        the gate's `frozen` needs. The fix is judged at its arrival, age 0.

        A refused fix, or one with no speed — GGA says none — is one this rule
        cannot read. It starts nothing and breaks a run of fast fixes; while
        driving it holds the state, and the stop's five seconds with it, until
        no usable fix has come for the hold (DRIVING_HOLD)."""
        speed = got.get('speed')
        if self._driving and not self._still_driving(now):
            # The hold ran out before this fix: the state ends here, so a
            # fast fix after a long silence is the first of two, not a
            # continuation.
            self._driving, self._fast, self._slow_since = False, 0, None
        if not usable(got, age=0.0, stale_after=self.stale_after)[0] \
                or not _number(speed):
            self._fast = 0
            return
        self._good_at = now
        if speed >= DRIVING_SPEED:
            self._fast += 1
            self._slow_since = None
            if self._fast >= DRIVING_FIXES:
                self._driving = True
        elif speed < STOPPED_SPEED:
            self._fast = 0
            if self._slow_since is None:
                self._slow_since = now
            if now - self._slow_since >= STOPPED_FOR:
                self._driving = False
        else:
            self._fast, self._slow_since = 0, None

    def state(self):
        """A word for the dashboard, and why, when there is a why.

        'off'        never started
        'looking'    started, nothing received yet, or trying to reconnect
        'fixed'      a position arrived within stale_after
        'stale'      a position arrived, and it is too old to use

        `ageSeconds` is how long ago the newest position arrived, by the local
        clock, or None when none has — and None too for a clock that has run
        backwards past it (the monotonic default cannot; one handed in can),
        because a negative age is not a duration anyone can be told. It is
        what lets the panel say "no fix for 12 min" rather than
        only "stale": the scan loop used to have the word and nothing else,
        and this method was read by this file's own command line and nowhere
        on the rig at all.
        """
        with self._lock:
            word, why, fix, at, lines = (self._state, self._error, self._fix,
                                         self._at, self._lines)
        since = None if fix is None else self._clock() - at
        # 'off' outranks the fix. A position stays usable for `stale_after`
        # after the reader is stopped — `fix()` will rightly still hand it over
        # — but the word here answers "is anything reading the phone", and
        # after stop() the answer is no. Letting the leftover fix paint it
        # 'fixed' would put a green light on a subsystem that is not running,
        # which is this project's own worst failure shape in miniature.
        #
        # Judged on the unrounded age by fresh(), the same rule fix() and
        # usable() ask, so the word and the position can never disagree about
        # the last tenth of a second before a fix goes stale.
        if fix is not None and word != 'off':
            word = 'fixed' if fresh(since, self.stale_after) else 'stale'
        return {'state': word, 'error': why, 'lines': lines,
                'ageSeconds': (round(since, 1)
                               if since is not None and since >= 0 else None),
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
                    self.take(got)
        finally:
            try:
                sock.close()
            except Exception:          # noqa: BLE001
                pass


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--from', dest='address', required=True,
                    metavar='HOST[:PORT]',
                    help='where gpsd or a GPS server app is listening: '
                         '127.0.0.1 for gpsd and a USB receiver on the Pi, or '
                         'a phone\'s Tailscale address, e.g. '
                         '100.x.y.z:2947, rather than its hotspot one, so '
                         'it keeps working when the rig is on wifi at home')
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
                # ...and what the receiver says about it, and the gate's
                # answer, because "it prints positions" is not the same as
                # "the rig will use them".
                line = '%.5f, %.5f  (%s, %.1fs old, mode %s, err %s m) %s' % (
                    got['lat'], got['lon'], got['source'], got['ageSeconds'],
                    got.get('mode'), got.get('err'),
                    'usable' if got['ok'] else 'refused: %s' % got['why'])
                # ...and a position worked out from the ECEF says so, every
                # line: it means gpsd's own lat/lon are wrong; see -b in
                # rpi/README.md.
                if got.get('note'):
                    line += ' — ' + got['note']
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
    print('Check gpsd (or the phone\'s app) is running and has a lock — '
          '`gpspipe -w -n 10` on the Pi shows what gpsd hears — that the '
          'address is right, and that the rig can reach it: nc -z %s %d'
          % (phone.host, phone.port), file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
