#!/usr/bin/env python3
"""Push this rig's offers to a machine that is not in the car.

    python3 rpi/sync.py --to http://nuc.lan:8080

The journal is the one irreplaceable thing here — about 19MB a year, and until
this existed there was exactly one copy of it, on an SD card, in a vehicle. The
scanner can be reflashed in an afternoon; a year of what the work actually paid
cannot be got back.

Run from a timer, never from the scan loop. The loop's whole budget is a few
hundred milliseconds and it must not spend any of it waiting on a network: a
cellular stall while an offer is on the screen is exactly the delay this project
has spent its time removing.

Being out of range is not an error. A car is offline most of the time, so a
failure to connect exits 0 and says so once — a timer that reports a fault every
ten minutes for a normal condition is a timer nobody reads.

WHAT MAKES THIS SAFE TO RUN AT ANY TIME
Every row carries an `id` and a `seq`, and the far end appends only the pairs it
has never seen. So this can send the same rows twice, or a hundred times, and
the result is the same. There is no stored offset to drift out of step, nothing
to repair after a connection drops half way, and no state on this side at all
beyond the journal itself. It can be interrupted, restarted, or run from a
restored backup, and it converges.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import journal as JR                                          # noqa: E402

DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              'config.json')

# How far back to start from, relative to what the far end already has.
#
# Overlap rather than an exact watermark, because the two clocks are not the
# same clock and a row can be written while a request is in flight. Re-sending
# an hour of rows costs a few kilobytes and the far end discards them; missing
# one loses an offer permanently.
OVERLAP_MS = 60 * 60 * 1000

# What to send when the far end has nothing, or cannot say what it has.
FIRST_RUN_DAYS = 30

TIMEOUT = 20.0


def newest_at(base, timeout=TIMEOUT):
    """What the far end already holds, in epoch ms. None if it will not say."""
    try:
        with urllib.request.urlopen(base.rstrip('/') + '/api/journal/newest',
                                    timeout=timeout) as fh:
            body = json.loads(fh.read().decode('utf-8'))
        return int(body.get('newest') or 0)
    except (urllib.error.URLError, ValueError, OSError):
        return None


def rows_since(path, floor_ms):
    """Rows at or after `floor_ms`, oldest first."""
    return [r for r in JR.Journal(path).rows()
            if isinstance(r, dict) and (r.get('at') or 0) >= floor_ms]


def send_config(base, path, token=None, timeout=TIMEOUT):
    """Keep a copy of the calibration beside the offers. Never fatal.

    400 bytes: the corners, the lens, the flicker-safe exposure and the driver's
    own target and running costs. Not irreplaceable the way the journal is —
    every number in it can be measured again — but re-aiming a camera at the
    roadside is an afternoon, and it is small enough that there is no reason to
    make anyone spend one.

    Failures here are reported and shrugged off. The journal is the thing worth
    a non-zero exit; this is a convenience riding along with it.
    """
    try:
        with open(path, 'rb') as fh:
            body = fh.read()
        json.loads(body.decode('utf-8'))      # do not upload something unreadable
    except (IOError, OSError, ValueError, UnicodeDecodeError) as e:
        return {'ok': False, 'error': str(e)}
    request = urllib.request.Request(
        base.rstrip('/') + '/api/config/backup', data=body, method='POST',
        headers={'Content-Type': 'application/json'})
    if token:
        request.add_header('X-Sync-Token', token)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as fh:
            return json.loads(fh.read().decode('utf-8'))
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {'ok': False, 'error': str(e)}


def send(base, rows, token=None, timeout=TIMEOUT):
    """POST rows as newline-delimited JSON. Returns the far end's summary."""
    body = ('\n'.join(json.dumps(r, sort_keys=True) for r in rows) + '\n').encode('utf-8')
    request = urllib.request.Request(
        base.rstrip('/') + '/api/journal/ingest', data=body, method='POST',
        headers={'Content-Type': 'application/x-ndjson'})
    if token:
        request.add_header('X-Sync-Token', token)
    with urllib.request.urlopen(request, timeout=timeout) as fh:
        return json.loads(fh.read().decode('utf-8'))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--to', default=os.environ.get('SYNC_TO'),
                    help='base URL of the machine keeping the copy, '
                         'e.g. http://nuc.lan:8080 (or set SYNC_TO)')
    ap.add_argument('--journal', default=JR.DEFAULT_PATH)
    ap.add_argument('--token', default=os.environ.get('SYNC_TOKEN'),
                    help='only needed if the far end sets SYNC_TOKEN')
    ap.add_argument('--days', type=int, default=FIRST_RUN_DAYS,
                    help='how far back to go when the far end has nothing')
    ap.add_argument('--all', action='store_true',
                    help='send the whole journal; safe, just slower')
    ap.add_argument('--config', default=DEFAULT_CONFIG,
                    help='calibration to keep a copy of alongside the offers')
    ap.add_argument('--no-config', action='store_true',
                    help='send only the offers')
    ap.add_argument('--quiet', action='store_true')
    args = ap.parse_args()

    if not args.to:
        sys.exit('nowhere to send to — pass --to or set SYNC_TO')

    def say(message):
        if not args.quiet:
            print(message)

    if not os.path.exists(args.journal):
        say('no journal at %s yet — nothing to send' % args.journal)
        return 0

    newest = newest_at(args.to)
    if newest is None:
        # Unreachable, or something there that is not this server. Normal in a
        # car; not worth a non-zero exit that a timer will report as a fault.
        say('%s did not answer — will try again next time' % args.to)
        return 0

    if args.all:
        floor = 0
    elif newest:
        floor = newest - OVERLAP_MS
    else:
        floor = JR.now_ms() - args.days * 86400000

    if not args.no_config and os.path.exists(args.config):
        backup = send_config(args.to, args.config, token=args.token)
        if backup.get('ok') and backup.get('changed'):
            say('calibration copied across')
        elif not backup.get('ok'):
            say('could not copy the calibration (%s) — the offers still went'
                % backup.get('error'))

    rows = rows_since(args.journal, floor)
    if not rows:
        say('nothing new since %s' % time.strftime('%Y-%m-%d %H:%M',
                                                   time.localtime(floor / 1000.0)))
        return 0

    try:
        result = send(args.to, rows, token=args.token)
    except urllib.error.HTTPError as e:
        # A real answer that says no — a token that does not match, a body over
        # the cap. Worth a non-zero exit, because retrying will not fix it.
        print('%s refused the upload: HTTP %s %s'
              % (args.to, e.code, e.read()[:200].decode('utf-8', 'replace')),
              file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError) as e:
        say('lost the connection to %s (%s) — will try again next time'
            % (args.to, e))
        return 0

    say('sent %d row(s), %d were new, %s now holds %s'
        % (len(rows), result.get('added', 0), args.to, result.get('have', '?')))
    if result.get('malformed'):
        print('%d row(s) were refused as malformed' % result['malformed'],
              file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
