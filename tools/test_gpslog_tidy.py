"""What tools/gpslog_tidy.py compresses, deletes, and leaves alone.

    python3 tools/test_gpslog_tidy.py

The tool deletes files on the rig, unattended, from Start.sh. So the checks
here are mostly about what it must NOT do: act on a dry run, touch the log
gpspipe is writing, trust a copy it has not read back, follow a link out of
the directory, or read a clock that has not been set. Every log is made up.
"""

import contextlib
import gzip
import io
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gpslog_tidy as TD                                      # noqa: E402

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


NOW = time.time()
DAY = 86400
LINE = b'{"class":"TPV","device":"/dev/ttyACM0","mode":3,"lat":40.0,"lon":-75.0}\n'
work = tempfile.mkdtemp()


def put(directory, name, body=LINE * 200, age=0.0):
    path = os.path.join(directory, name)
    with open(path, 'wb') as fh:
        fh.write(body)
    os.utime(path, (NOW - age, NOW - age))
    return path


def put_gz(directory, name, age):
    path = os.path.join(directory, name)
    with gzip.open(path, 'wb') as fh:
        fh.write(LINE)
    os.utime(path, (NOW - age, NOW - age))
    return path


def snapshot(directory):
    out = {}
    for root, dirs, files in os.walk(directory):
        for name in dirs + files:
            path = os.path.join(root, name)
            st = os.lstat(path)
            body = open(path, 'rb').read() if os.path.isfile(path) and not os.path.islink(path) else None
            out[os.path.relpath(path, directory)] = (st.st_mtime, body, os.path.islink(path))
    return out


def run(*argv, now=NOW):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = TD.main(list(argv), now=now)
    return code, buf.getvalue()


def fresh(name):
    d = os.path.join(work, name)
    os.makedirs(d)
    put(d, 'old.jsonl', age=3 * DAY)
    put(d, 'parked-by-hand.jsonl', age=2 * DAY)
    put(d, 'recent.jsonl', age=5 * 60)
    put(d, 'newest.jsonl', age=60 * 60)
    os.utime(os.path.join(d, 'newest.jsonl'), (NOW - 1, NOW - 1))
    put_gz(d, 'ancient.jsonl.gz', 61 * DAY)
    put_gz(d, 'kept.jsonl.gz', 59 * DAY)
    put_gz(d, 'middling.jsonl.gz', 45 * DAY)
    return d


# --- a dry run ----------------------------------------------------------------
d = fresh('dry')
before = snapshot(d)
code, out = run(d)
eq('a dry run changes nothing', snapshot(d), before)
eq('...and exits 0', code, 0)
ok_('...and says what it would gzip', 'would gzip   old.jsonl' in out)
ok_('...and what it would delete', 'would delete ancient.jsonl.gz' in out)
ok_('...and that nothing was changed', 'dry run, nothing changed' in out)

# --- --apply ------------------------------------------------------------------
d = fresh('apply')
old_body = open(os.path.join(d, 'old.jsonl'), 'rb').read()
old_mtime = os.stat(os.path.join(d, 'old.jsonl')).st_mtime
code, out = run('--apply', d)
eq('--apply exits 0 when everything worked', code, 0)
ok_('a finished log is gzipped', os.path.exists(os.path.join(d, 'old.jsonl.gz')))
ok_('...and the log itself removed', not os.path.exists(os.path.join(d, 'old.jsonl')))
with gzip.open(os.path.join(d, 'old.jsonl.gz'), 'rb') as fh:
    eq('...the .gz holding exactly the log', fh.read(), old_body)
eq('...and keeping the log\'s own time, so its age counts from the log',
   os.stat(os.path.join(d, 'old.jsonl.gz')).st_mtime, old_mtime)
ok_('a log by any name is a log', os.path.exists(os.path.join(d, 'parked-by-hand.jsonl.gz')))
ok_('no .part is left behind', not [n for n in os.listdir(d) if n.endswith('.part')])
ok_('a log written to in the last ten minutes is left alone',
    os.path.exists(os.path.join(d, 'recent.jsonl'))
    and not os.path.exists(os.path.join(d, 'recent.jsonl.gz')))
ok_('a .gz past the days is deleted', not os.path.exists(os.path.join(d, 'ancient.jsonl.gz')))
ok_('...one inside them kept', os.path.exists(os.path.join(d, 'kept.jsonl.gz')))
ok_('--apply says what it gzipped', 'gzipped old.jsonl' in out)
ok_('...and what it deleted', 'deleted ancient.jsonl.gz' in out)
ok_('...and what it skipped, with why', 'skip    newest.jsonl  (the newest log' in out)

# The newest log is the one gpspipe may still hold open, however quiet it has
# been. Its own directory, because beside a log written five minutes ago the
# newest is always inside the ten minutes as well, and that rule would hide
# this one.
d = os.path.join(work, 'quiet')
os.makedirs(d)
put(d, 'monday.jsonl', age=3 * DAY)
put(d, 'tuesday.jsonl', age=60 * 60)
run('--apply', d)
ok_('the newest log is left alone, however long ago it was written to',
    os.path.exists(os.path.join(d, 'tuesday.jsonl'))
    and not os.path.exists(os.path.join(d, 'tuesday.jsonl.gz')))
ok_('...while the one before it is gzipped', os.path.exists(os.path.join(d, 'monday.jsonl.gz')))

d = fresh('days')
run('--apply', '--days', '30', d)
ok_('--days moves the line', not os.path.exists(os.path.join(d, 'middling.jsonl.gz')))
code, out = None, ''
try:
    with contextlib.redirect_stderr(io.StringIO()):
        run('--apply', '--days', '0', fresh('days0'))
except SystemExit as e:
    code = e.code
eq('--days 0 is refused rather than deleting every log it just compressed', code, 2)

# --- nothing outside the directory --------------------------------------------
d = fresh('confined')
outside = os.path.join(work, 'outside')
os.makedirs(outside)
target = put(outside, 'elsewhere.jsonl', age=10 * DAY)
target_gz = put_gz(outside, 'elsewhere.jsonl.gz', 100 * DAY)
os.symlink(target, os.path.join(d, 'link.jsonl'))
os.symlink(target_gz, os.path.join(d, 'link.jsonl.gz'))
# The links themselves old, so it is the kind of file that keeps them out and
# not their age: a link is never a log here, whatever it points at.
for _l, _age in (('link.jsonl', 10 * DAY), ('link.jsonl.gz', 100 * DAY)):
    os.utime(os.path.join(d, _l), (NOW - _age, NOW - _age), follow_symlinks=False)
# ...and a .part a power cut might have left, as a link out of the directory:
# writing the next copy "into" it would overwrite whatever it points at.
part_target = put(outside, 'not-a-part.txt', body=b'keep me\n', age=DAY)
os.symlink(part_target, os.path.join(d, 'old.jsonl.gz.part'))
os.makedirs(os.path.join(d, 'sub'))
put(os.path.join(d, 'sub'), 'deep.jsonl', age=10 * DAY)
put_gz(os.path.join(d, 'sub'), 'deep.jsonl.gz', 100 * DAY)
put_gz(d, 'somebody-else.gz', 100 * DAY)
put(d, 'notes.txt', age=100 * DAY)
outside_before = snapshot(outside)
sub_before = snapshot(os.path.join(d, 'sub'))
code, out = run('--apply', d)
eq('nothing outside the directory is touched, through a link or otherwise',
   snapshot(outside), outside_before)
eq('...not even a .part that is a link out of it, which is refused and said',
   (open(part_target, 'rb').read(), 'FAILED  gzip old.jsonl' in out),
   (b'keep me\n', True))
ok_('...the links themselves left where they are',
    os.path.islink(os.path.join(d, 'link.jsonl'))
    and os.path.islink(os.path.join(d, 'link.jsonl.gz')))
# The listing keeps links out; compress() is the second lock, for a log that
# becomes a link between the listing and the read.
try:
    TD.compress(d, 'link.jsonl')
    _through = True
except OSError:
    _through = False
ok_('compress() itself will not read a log through a link',
    not _through and os.path.islink(os.path.join(d, 'link.jsonl')))
eq('a subdirectory is not walked', snapshot(os.path.join(d, 'sub')), sub_before)
ok_('a .gz that is not a log is not this tool\'s to delete',
    os.path.exists(os.path.join(d, 'somebody-else.gz')))
ok_('...nor anything else in there', os.path.exists(os.path.join(d, 'notes.txt')))

code, out = run('--apply', os.path.join(work, 'no-such-dir'))
eq('a directory that is not there is a failure', code, 1)
ok_('...and says so', 'is not a directory' in out)

# --- the clock ----------------------------------------------------------------
d = fresh('unset-clock')
# A log written before the clock was set, on a clock still not set: eleven days
# "old" to that clock, and the one file here the clock could act on.
os.utime(put(d, 'before-ntp.jsonl'), (5_000.0, 5_000.0))
before = snapshot(d)
code, out = run('--apply', d, now=1_000_000.0)
eq('a run on a clock that has not been set does nothing', snapshot(d), before)
ok_('...and says why', 'has not been set yet' in out)
eq('...and is not a failure', code, 0)

d = os.path.join(work, 'before-clock')
os.makedirs(d)
p = put_gz(d, 'from-1970.jsonl.gz', 0)
os.utime(p, (5_000.0, 5_000.0))
code, out = run('--apply', d)
ok_('a .gz stamped before the rig\'s clock was set is kept, not read as 56 years old',
    os.path.exists(p))
ok_('...and named', 'from-1970.jsonl.gz' in out and 'before the rig\'s clock was set' in out)

# --- a copy it cannot trust ---------------------------------------------------
real_same = TD._same_bytes

d = fresh('bad-copy')
body = open(os.path.join(d, 'old.jsonl'), 'rb').read()
TD._same_bytes = lambda log, packed: False
try:
    code, out = run('--apply', d)
finally:
    TD._same_bytes = real_same
_log = os.path.join(d, 'old.jsonl')
eq('a copy that does not read back the same keeps the log',
   open(_log, 'rb').read() if os.path.exists(_log) else None, body)
ok_('...writes no .gz for it', not os.path.exists(os.path.join(d, 'old.jsonl.gz')))
ok_('...leaves no .part', not [n for n in os.listdir(d) if n.endswith('.part')])
eq('...and is a failure', code, 1)
ok_('...said as one', 'FAILED  gzip old.jsonl' in out)


# Written to AFTER the read-back agreed: a write before it is a copy that does
# not read back the same, which is the case above. This is the window the
# read-back itself takes, on a log a second gpspipe is still holding open.
def appended(log, packed):
    same = real_same(log, packed)
    with open(log, 'ab') as fh:
        fh.write(LINE)
    return same


d = fresh('written-during')
TD._same_bytes = appended
try:
    code, out = run('--apply', d)
finally:
    TD._same_bytes = real_same
ok_('a log written to while it was compressed is kept',
    os.path.exists(os.path.join(d, 'old.jsonl')))
ok_('...with no .gz of half of it', not os.path.exists(os.path.join(d, 'old.jsonl.gz')))
ok_('...said as a failure', code == 1 and 'written to while' in out)

# A power cut mid-compress leaves a .part. The next run writes over it, and
# writing over the FRONT of it would leave its tail on the end of the new one.
d = fresh('stale-part')
put(d, 'old.jsonl.gz.part', body=os.urandom(64 * 1024), age=DAY)
code, out = run('--apply', d)
ok_('a .part a power cut left does not stop the next run',
    code == 0 and os.path.exists(os.path.join(d, 'old.jsonl.gz')))

shutil.rmtree(work, ignore_errors=True)
print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d gpslog tidy checks passed' % ok)
sys.exit(1 if bad else 0)
