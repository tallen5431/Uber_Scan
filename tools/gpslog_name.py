#!/usr/bin/env python3
"""The name a new GPS log should have, by the GPS's own clock.

    gpspipe -w -uu -o ~/gpslog/$(python3 tools/gpslog_name.py).jsonl

Prints `<date>_<HHMM>` (the rig's local time, the shape tools/shift_report.py
reads a log's start off: _LOG_NAME), and nothing else on stdout.

WHY NOT `date`. The Pi has no real-time clock. After a reboot it runs from the
time saved at the last shutdown (fake-hwclock) and steps forward when NTP
answers, and a log named off `date` at boot is named for that saved minute.
The owner's 26 Oct shift, every log of it: `2026-10-26_1415` began at 14:30
(its first 136 fixes stamped 923 s early, until the step), `2026-10-26_1526`
at 17:38, 7,925 s later than its name, and the reboot after the shift's
`2026-10-27_0004` at 00:59. A report picks a day's logs by their names
(shift_report._logs_for), and a person reading the directory does too.

So the minute is the receiver's: gpsd's first TPV with a fix (mode 2 or 3)
and a `time` — UTC off the satellites, which no reboot touches. Waits for
one up to --wait seconds (a cold receiver can take a minute or two, and the
log is not started until this answers: gpspipe waits on the name). With no
fix by then, the clock's minute IF `timedatectl` says NTP has set it, and
otherwise the clock's minute with `-unsynced` after it: a name _LOG_NAME does
not read, which shift_report treats as "no date said" and reads for every day
(_logs_for), rather than a confident wrong minute. It never fails: a log with
an honest name is better than none.

The stamps on the lines are still the Pi's clock (-uu); a step of it inside
a log is shift_report's to correct (CLOCK_STEP_S), by the same TPV `time`.
"""

import argparse
import calendar
import json
import os
import socket
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'rpi'))
import gps as G                                               # noqa: E402

WAIT_S = 120.0
UNSYNCED = '-unsynced'


def gps_seconds(tpv):
    """A TPV's UTC `time` as epoch seconds when it carries a fix, else None."""
    if not isinstance(tpv, dict) or tpv.get('class') != 'TPV':
        return None
    if not isinstance(tpv.get('mode'), int) or tpv['mode'] < 2:
        return None
    when = tpv.get('time')
    if not isinstance(when, str) or len(when) < 19:
        return None
    try:
        return float(calendar.timegm(time.strptime(when[:19], '%Y-%m-%dT%H:%M:%S')))
    except ValueError:
        return None


def name_for(seconds, synced=True):
    """The log's name for a start at `seconds` (epoch), local time."""
    out = time.strftime('%Y-%m-%d_%H%M', time.localtime(seconds))
    return out if synced else out + UNSYNCED


def ntp_synced():
    """Whether systemd says NTP has set the clock; False when it cannot say."""
    try:
        got = subprocess.run(['timedatectl', 'show', '-p', 'NTPSynchronized', '--value'],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return got.stdout.strip() == 'yes'


def first_fix_time(host, wait, clock=time.monotonic):
    """The first fix's GPS time off gpsd at `host`, or None by `wait` s."""
    end = clock() + wait
    try:
        addr, port = G.parse_host(host)
        with socket.create_connection((addr, port), timeout=min(10.0, max(wait, 0.1))) as s:
            s.sendall(b'?WATCH={"enable":true,"json":true}\n')
            buf = b''
            while clock() < end:
                s.settimeout(max(0.1, end - clock()))
                try:
                    got = s.recv(4096)
                except socket.timeout:
                    break
                if not got:
                    break
                buf += got
                while b'\n' in buf:
                    line, buf = buf.split(b'\n', 1)
                    try:
                        t = gps_seconds(json.loads(line.decode('utf-8', 'replace')))
                    except ValueError:
                        continue
                    if t is not None:
                        return t
    except (OSError, ValueError):
        return None
    return None


def main(argv=None, now=None, synced=None, fix_time=None):
    ap = argparse.ArgumentParser(description='Print a new GPS log\'s name by the GPS\'s clock.')
    ap.add_argument('--host', default='127.0.0.1:%d' % G.DEFAULT_PORT,
                    help='gpsd, as host or host:port (default 127.0.0.1:%d)' % G.DEFAULT_PORT)
    ap.add_argument('--wait', type=float, default=WAIT_S,
                    help='seconds to wait for a fix (default %g)' % WAIT_S)
    args = ap.parse_args(argv)
    t = (fix_time or first_fix_time)(args.host, args.wait)
    if t is not None:
        print(name_for(t))
        return 0
    now = time.time() if now is None else now
    ok = ntp_synced() if synced is None else synced
    print(name_for(now, synced=ok))
    sys.stderr.write('gpslog_name: no fix in %g s; named by the Pi\'s clock%s\n'
                     % (args.wait, '' if ok else ', which NTP has not set'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
