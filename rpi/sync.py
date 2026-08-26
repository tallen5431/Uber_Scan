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


def far_end(base, timeout=TIMEOUT):
    """What the far end holds and what it can do. None when it will not say."""
    try:
        with urllib.request.urlopen(base.rstrip('/') + '/api/journal/newest',
                                    timeout=timeout) as fh:
            body = json.loads(fh.read().decode('utf-8'))
    except (urllib.error.URLError, ValueError, OSError):
        return None
    # Something answered on that port that is not this server — a router's login
    # page, another project's API. Treat it as silence rather than reading
    # fields off it.
    return body if isinstance(body, dict) else None


def newest_at(base, timeout=TIMEOUT):
    """What the far end already holds, in epoch ms. None if it will not say."""
    body = far_end(base, timeout)
    return None if body is None else int(body.get('newest') or 0)


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
    except urllib.error.HTTPError as e:
        # The far end said no and said why in the body. Without this the driver
        # gets 'HTTP Error 500: Internal Server Error' — true, and useless — and
        # has to go and read a log on the other machine to learn that a
        # directory was not writable. The offers already report the reason; the
        # calibration was doing the older, worse thing beside them.
        detail = e.read()[:200].decode('utf-8', 'replace')
        try:
            detail = json.loads(detail).get('error') or detail
        except ValueError:
            pass
        return {'ok': False, 'error': 'HTTP %s %s' % (e.code, detail)}
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {'ok': False, 'error': str(e)}


# How many rows to put in one POST.
#
# The far end refuses a body over 8MB, and a row is a few hundred bytes, so a
# journal of about twenty thousand rows is the point at which a whole-journal
# send stops fitting — a year and a bit of driving. What made that worth
# bounding rather than documenting is how it failed: the far end resets the
# connection, a reset is indistinguishable here from being out of range, and
# being out of range is normal in a car and exits 0. So the only backup of the
# only irreplaceable thing on the rig would stop working, permanently, and say
# it had worked.
#
# Two thousand rows is comfortably inside the cap with a large margin for rows
# that carry addresses, and each POST is still idempotent on its own — the far
# end appends only (id, seq) pairs it has never seen — so an interrupted run
# leaves the copy consistent and the next tick picks up from there.
CHUNK_ROWS = 2000


def send(base, rows, token=None, timeout=TIMEOUT):
    """POST rows as newline-delimited JSON, in chunks. Returns the summary."""
    total = {'added': 0, 'malformed': 0, 'have': None}
    for start in range(0, len(rows), CHUNK_ROWS):
        part = rows[start:start + CHUNK_ROWS]
        body = ('\n'.join(json.dumps(r, sort_keys=True) for r in part)
                + '\n').encode('utf-8')
        request = urllib.request.Request(
            base.rstrip('/') + '/api/journal/ingest', data=body, method='POST',
            headers={'Content-Type': 'application/x-ndjson'})
        if token:
            request.add_header('X-Sync-Token', token)
        with urllib.request.urlopen(request, timeout=timeout) as fh:
            result = json.loads(fh.read().decode('utf-8'))
        total['added'] += result.get('added') or 0
        total['malformed'] += result.get('malformed') or 0
        # The last chunk's count is the one that is true, since each is applied
        # before the next is sent.
        if result.get('have') is not None:
            total['have'] = result.get('have')
    return total


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

    far = far_end(args.to)
    # A far end that answers and says it cannot read its own journal is a
    # different thing from one that does not answer, and only one of them is
    # normal. Sending into it would append rows it cannot de-duplicate against,
    # so every tick would add another copy of everything and report success.
    if far is not None and far.get('readable') is False:
        # stderr and not say(): --quiet is for the routine chatter of a timer
        # that runs every ten minutes, and this is a standing fault at the other
        # end that nobody will otherwise see. It is also the one the install
        # gate has to catch, since a backup that cannot merge is not a backup.
        print('%s is reachable but cannot read its own journal (%s). Sending '
              'nothing: it could not tell a new row from one it already has, so '
              'every upload would append another copy of everything and report '
              'success. Fix that end before trusting this backup.'
              % (args.to, far.get('error') or 'unknown'), file=sys.stderr)
        return 1
    newest = None if far is None else int(far.get('newest') or 0)
    if newest is None:
        # Unreachable, or something there that is not this server. Normal in a
        # car; not worth a non-zero exit that a timer will report as a fault.
        say('%s did not answer — will try again next time' % args.to)
        return 0

    # Every offer this rig holds, and every offer the copy holds. If the copy
    # holds fewer, something was missed — a run that died half way, a clock that
    # went backwards, a card restored from an older backup — and resuming from
    # an hour before its newest row would step straight over the gap and never
    # come back to it. Counting is the cheapest possible reconciliation: two
    # integers, already in a reply the sync makes anyway, and it turns "somebody
    # has to notice and run --all" into something that repairs itself on the
    # next tick.
    #
    # Counted against the same moment, though, or the count is not a
    # reconciliation at all. `newest` was fetched at the top of this run, so it
    # describes the copy as it was *then* — and during a shift this rig appends
    # rows continuously, a median half a minute apart. Comparing every row held
    # now against a count taken a moment ago makes this shift's own rows look
    # like a gap, so every tick declared a shortfall and re-sent the entire
    # journal. On a long enough history that body passes the far end's 8MB
    # limit, the POST is reset, the reset is indistinguishable from being out of
    # range, and the sync reports success and backs up nothing — for good, and
    # silently, which is the worst way for the only backup to fail.
    mine = [r for r in JR.Journal(args.journal).rows()
            if isinstance(r, dict) and not r.get('kind')]
    settled = sum(1 for r in mine if (r.get('at') or 0) <= newest)
    theirs = far.get('offers')
    short = (isinstance(theirs, int) and settled > theirs)

    if args.all or short:
        floor = 0
        if short and not args.all:
            say('%s holds %d offers and this rig holds %d up to that point — '
                'sending everything to close the gap' % (args.to, theirs, settled))
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
        # the cap, somewhere it cannot write. Worth a non-zero exit, because
        # retrying will not fix any of them.
        detail = e.read()[:200].decode('utf-8', 'replace')
        print('%s refused the upload: HTTP %s %s' % (args.to, e.code, detail),
              file=sys.stderr)
        # Say which end is behind, rather than leaving somebody to notice that an
        # error message is missing a detail. An older build cannot create the
        # directory its journal lives in and does not name the errno when it
        # fails, so the two symptoms arrive together and neither explains itself.
        if 'mkdir' not in (far.get('can') or []):
            print('  the machine keeping the copy is running an older build of '
                  'this server: it cannot create the directory JOURNAL points '
                  'at. Pull and restart it there, then run this again.',
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
