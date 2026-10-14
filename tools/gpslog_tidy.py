#!/usr/bin/env python3
"""Keep the GPS logs from filling the Pi's card.

    python3 tools/gpslog_tidy.py ~/gpslog                  what it would do
    python3 tools/gpslog_tidy.py --apply ~/gpslog          do it, and say what it did
    python3 tools/gpslog_tidy.py --apply --days 30 ~/gpslog

`gpspipe -w -uu -o ~/gpslog/<stamp>.jsonl` writes every gpsd report as a line
of JSON, all shift, and nothing ever removed one. Measured on the 12 Oct
shift's 14 logs: 5.4 to 9.0 MB an hour while driving, 58,446,184 bytes for the
day. The lines are the same few keys over and over, and gzip at its default
level keeps 4.6% of them — 2,665,398 bytes for that day, in half a second of
CPU on the build machine (level 9 keeps 4.1% for nearly three times the CPU,
so this does not use it).

So, run before gpspipe starts:

  * every finished `.jsonl` in the directory is gzipped beside itself, and the
    original removed only once the `.gz` has been read back and found to hold
    exactly the same bytes. A log that changed while it was being compressed is
    left as it is. The `.gz` keeps the log's own modification time, so the age
    rule below counts from when the log was last written, not from when it was
    compressed.
  * a log is FINISHED unless it is the newest one, or was written to in the
    last QUIET_S. The newest is the one gpspipe is most likely still writing,
    and a writer can still be attached to the one before it while a second
    gpspipe starts; neither can be told from a closed file by looking at it.
    The newest is compressed on the next run, once a newer one exists.
  * a `.jsonl.gz` older than `--days` (KEEP_DAYS) is deleted.

The age of a file is its modification time against the clock, and the Pi's
clock is the one thing here that cannot be taken on trust: it has no real-time
clock, boots in 1970 and jumps when the network arrives (rpi/sync.py's
CLOCK_BELIEVABLE_AFTER, which this takes rather than copies). So a run whose
own clock is below that floor does nothing and says why, and a `.gz` stamped
below it is kept and named rather than deleted — a log written before the clock
was set would otherwise be compressed on one run and read as 56 years old, and
deleted, on the next.

It never touches anything outside the directory it is given: no subdirectory,
nothing reached through a symbolic link, no file whose name does not end
`.jsonl` or `.jsonl.gz`. A `.gz` somebody else put there is not one of these.

Dry run by default, because a tool that deletes is a tool that should say what
it will delete before anybody lets it. Every log it skips, compresses or
deletes gets a line naming it and what happened, a summary line closes the
run, and a failure is printed and makes the exit status 1, so nothing goes
missing with nothing saying so.
"""

import argparse
import gzip
import os
import stat
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'rpi'))
import sync                                                   # noqa: E402

# Below this a modification time is a Pi that had not heard from NTP yet, in
# seconds. See the docstring.
CLOCK_FLOOR = sync.CLOCK_BELIEVABLE_AFTER / 1000.0

# How long a log must have been left alone to count as finished.
QUIET_S = 10 * 60

# How many days a compressed log is kept. About two months of shifts, and at
# the 12 Oct shift's 2.7MB a day compressed that is about 160MB on the card — an
# estimate, from one shift.
KEEP_DAYS = 60

# gzip's own default, and the level the figures above were measured at.
LEVEL = 6

CHUNK = 1 << 20

LOG = '.jsonl'
PACKED = '.jsonl.gz'


def plan(directory, now, days=KEEP_DAYS):
    """What would be done, as a list of (action, name, why), in name order.

    `action` is 'gzip', 'skip' or 'delete'. Only regular files directly inside
    `directory` are looked at, by lstat, so a symbolic link is never followed
    and never counted.
    """
    files = []
    for name in sorted(os.listdir(directory)):
        st = os.lstat(os.path.join(directory, name))
        if stat.S_ISREG(st.st_mode):
            files.append((name, st))
    logs = [(name, st) for name, st in files if name.endswith(LOG)]
    newest = max(logs, key=lambda f: (f[1].st_mtime, f[0]))[0] if logs else None
    out = []
    for name, st in files:
        age = now - st.st_mtime
        if name.endswith(LOG):
            if name == newest:
                out.append(('skip', name, 'the newest log, which gpspipe may still be writing'))
            elif age < QUIET_S:
                out.append(('skip', name, 'written %d s ago, under the %d min a finished log has been left'
                            % (max(0, age), QUIET_S // 60)))
            else:
                out.append(('gzip', name, '%d bytes' % st.st_size))
        elif name.endswith(PACKED) and st.st_mtime < CLOCK_FLOOR:
            out.append(('skip', name, 'stamped %s, before the rig\'s clock was set; kept'
                        % time.strftime('%Y-%m-%d', time.localtime(st.st_mtime))))
        elif name.endswith(PACKED) and age > days * 86400:
            out.append(('delete', name, '%.0f days old, past %d' % (age / 86400, days)))
    return out


def _open_read(path):
    return os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb')


def _same_bytes(log, packed):
    """Whether the gzip at `packed` decompresses to exactly the file at `log`."""
    with _open_read(log) as a, gzip.open(packed, 'rb') as b:
        while True:
            x, y = a.read(CHUNK), b.read(CHUNK)
            if x != y:
                return False
            if not x:
                return True


def _sync_dir(directory):
    # So the rename is on the card before the original goes: a power cut
    # between the two must leave the log, not neither. If this raises, the
    # log stays beside its .gz and the next run does it again.
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def compress(directory, name):
    """Gzip one log beside itself and remove it. Returns the packed size.

    Raises with a reason on anything short of that, leaving the log where it
    was: a partial `.part` is removed, and the original is only unlinked after
    the `.gz` has been read back whole and renamed into place.
    """
    log = os.path.join(directory, name)
    packed = log + '.gz'
    part = packed + '.part'
    before = os.lstat(log)
    try:
        # Truncated, because a `.part` already there is one a power cut left,
        # and writing over the front of it would leave its tail on the end.
        fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW,
                     0o644)
        with os.fdopen(fd, 'wb') as raw:
            with gzip.GzipFile(filename=name, mode='wb', fileobj=raw,
                               compresslevel=LEVEL, mtime=int(before.st_mtime)) as gz:
                with _open_read(log) as src:
                    while True:
                        chunk = src.read(CHUNK)
                        if not chunk:
                            break
                        gz.write(chunk)
            raw.flush()
            os.fsync(raw.fileno())
        if not _same_bytes(log, part):
            raise RuntimeError('the compressed copy did not read back the same; log kept')
        after = os.lstat(log)
        if (after.st_size, after.st_mtime) != (before.st_size, before.st_mtime):
            raise RuntimeError('written to while it was being compressed; log kept')
        os.utime(part, (before.st_atime, before.st_mtime))
        os.replace(part, packed)
    except BaseException:
        try:
            os.unlink(part)
        except OSError:
            pass
        raise
    _sync_dir(directory)
    os.unlink(log)
    return os.lstat(packed).st_size


def main(argv=None, now=None):
    ap = argparse.ArgumentParser(description='Gzip finished GPS logs and delete old ones. '
                                             'Says what it would do unless given --apply.')
    ap.add_argument('directory')
    ap.add_argument('--apply', action='store_true', help='do it, rather than say what it would do')
    ap.add_argument('--days', type=int, default=KEEP_DAYS,
                    help='delete compressed logs older than this many days (default %d)' % KEEP_DAYS)
    args = ap.parse_args(argv)
    # Zero would delete every log the moment it was compressed. Refused rather
    # than obeyed: nobody who wanted that would ask for it this way.
    if args.days < 1:
        ap.error('--days must be at least 1')
    directory = args.directory
    if not os.path.isdir(directory):
        print('gpslog_tidy: %s is not a directory; nothing done' % directory)
        return 1
    now = time.time() if now is None else now
    # Not a failure: the clock will be right later, and so will this.
    if now < CLOCK_FLOOR:
        print('gpslog_tidy: this clock says %s, so it has not been set yet and '
              'no age can be trusted; nothing done'
              % time.strftime('%Y-%m-%d %H:%M', time.localtime(now)))
        return 0
    failed = 0
    done = {'gzip': 0, 'delete': 0}
    for action, name, why in plan(directory, now, args.days):
        if action == 'skip':
            print('skip    %s  (%s)' % (name, why))
            continue
        if not args.apply:
            print('would %-6s %s  (%s)' % (action, name, why))
            continue
        try:
            if action == 'gzip':
                size = compress(directory, name)
                print('gzipped %s  (%s -> %d bytes)' % (name, why, size))
            else:
                os.unlink(os.path.join(directory, name))
                print('deleted %s  (%s)' % (name, why))
            done[action] += 1
        except Exception as e:
            failed += 1
            print('FAILED  %s %s: %s' % (action, name, e))
    if args.apply:
        print('gpslog_tidy: %d gzipped, %d deleted, %d failed, in %s'
              % (done['gzip'], done['delete'], failed, directory))
    else:
        print('gpslog_tidy: dry run, nothing changed; --apply to do it')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
