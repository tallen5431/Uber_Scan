"""tools/pi_bench.py, run once of each read on this machine.

    python3 tools/test_pi_bench.py

The bench is for the Pi, and a script nobody runs until the night it is
needed is a script that fails that night: a renamed Scanner field, a testcards
screen that changed shape, an import that moved. So it is run here end to end
with N=1 (`--n 1 --json`, and once more as the owner would read it), and held
to what it is for: every read it names is timed, each gave the card's own
answer — the rescue cases rescued, by the link the case is named for, the
remembered crop kept — and it said the heat both sides and wrote nothing.
The timings themselves are this machine's and asserted only to be there.

Skipped where no card can be drawn (no PIL or no usable font), as the other
rendered suites skip.
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'rpi'))
import testcards as TC                                        # noqa: E402

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


if not TC.available():
    print('no PIL or no usable font — skipping the bench smoke test')
    sys.exit(0)


def tree():
    """Every file under the repository with its size and mtime, but the
    caches Python writes beside what it imports."""
    out = {}
    for d, dirs, files in os.walk(ROOT):
        dirs[:] = [x for x in dirs if x not in ('.git', '__pycache__', 'node_modules')]
        for f in files:
            p = os.path.join(d, f)
            st = os.stat(p)
            out[p] = (st.st_size, st.st_mtime)
    return out


READS = ['uber card, centred box', 'dd rescue: finder, evened read',
         'dd rescue: refused, raised', 'dd next read: remembered crop',
         'planner, whole screen (⌖)', 'map label']

was = tree()
env = dict(os.environ, OMP_THREAD_LIMIT='1')
done = subprocess.run([sys.executable, os.path.join(HERE, 'pi_bench.py'), '--n', '1', '--json'],
                      capture_output=True, text=True, env=env, timeout=600)
eq('pi_bench --n 1 --json exits 0 (%s)' % (done.stderr or '').strip()[-200:],
   done.returncode, 0)
try:
    res = json.loads(done.stdout)
except ValueError:
    res = {}
rows = res.get('rows') or []
eq('it times the six reads it names, in order', [r.get('read') for r in rows], READS)
for r in rows:
    for k in ('on', 'off'):
        c = r.get(k) or {}
        ok_('%s, spare threads %s: one read, timed (%r)' % (r.get('read'), k, c),
            c.get('n') == 1 and isinstance(c.get('median'), int) and c['median'] > 0
            and c.get('p90') == c.get('median'))
        eq('...and it gave the card\'s own answer', c.get('ok'), 1)
ok_('it runs below the camera loop (nice %r)' % res.get('nice'),
    isinstance(res.get('nice'), int) and res['nice'] >= 10)
for side in ('before', 'after'):
    h = res.get(side) or {}
    ok_('it says the heat %s, a figure or why not (%r)' % (side, h),
        set(h) == {'cpuC', 'from', 'throttled', 'why'}
        and (h['cpuC'] is not None or bool(h['from']))
        and (h['throttled'] is not None or bool(h['why'])))
ok_('it says whether the scanner service was running', 'service' in res)
eq('it wrote nothing in the repository',
   sorted(p for p, v in tree().items() if was.get(p) != v), [])

# ...and the table the owner reads, made from that same run (pi_bench.table,
# which the plain run prints): a line a read with both cells, the heat before
# and after.
sys.path.insert(0, HERE)
import pi_bench as B                                          # noqa: E402
lines = B.table(res).splitlines() if rows else []
ok_('the table: a line for each read, with its two cells (%r)' % lines[4:5],
    bool(lines) and all(any(l.startswith(name) and l.count('1/1') == 2 for l in lines)
                        for name in READS))
ok_('...and the heat before and after it',
    any(l.startswith('before: ') for l in lines) and any(l.startswith('after: ') for l in lines))
eq('...and by default the timed reads share 150 s, so a Pi 4 is done inside three minutes',
   res.get('budgetS'), 150.0)

# --- --busy: the reads with the rig's concurrent work beside them --------------
#
# Run end to end, a few seconds a run (the reads, the label asks, the band,
# the live view and the stand-in camera loop all turning over), and held to
# what it is for: three runs — the reads alone, then busy with the engines'
# gate off and on — each timing reads that all gave the card's own answer,
# the loop's tick timed, the label asked only where it is on, the gate's
# figures on the gated run only, and nothing written in the repository (the
# snapshot and the map bands go to a temporary folder, removed after).
was = tree()
done = subprocess.run([sys.executable, os.path.join(HERE, 'pi_bench.py'), '--busy',
                       '--seconds', '22', '--json'],
                      capture_output=True, text=True, env=env, timeout=600)
eq('pi_bench --busy --json exits 0 (%s)' % (done.stderr or '').strip()[-200:],
   done.returncode, 0)
try:
    busy = json.loads(done.stdout)
except ValueError:
    busy = {}
runs = busy.get('runs') or []
eq('--busy: three runs, the reads alone, then busy with the gate off and on',
   [(r.get('run'), r.get('slots')) for r in runs],
   [('alone', 0), ('busy, ocr slots off', 0), ('busy, ocr slots 4', 4)])
for r in runs:
    k = r.get('kinds') or {}
    ok_('%s: both cards read, every read the card\'s own answer (%r)' % (r.get('run'), k),
        all((k.get(c) or {}).get('n', 0) > 0 and k[c]['ok'] == k[c]['n']
            and isinstance(k[c].get('median'), int) for c in ('uber', 'dd')))
    t = r.get('tick') or {}
    ok_('%s: the camera loop\'s tick timed (%r)' % (r.get('run'), t),
        t.get('n', 0) > 0 and all(isinstance(t.get(x), (int, float)) for x in ('median', 'p95', 'max')))
    ok_('%s: the time: stages a health line would print (%r)' % (r.get('run'), r.get('time')),
        all(isinstance((r.get('time') or {}).get(x), int) for x in ('queue', 'warp', 'read')))
eq('--busy: the label asked only beside the busy runs',
   [r.get('labelReads', 0) > 0 for r in runs], [False, True, True])
eq('--busy: only the gated run says the gate held anything back',
   [sum(w.get('waited', 0) for w in (r.get('waited') or {}).values()) > 0 or bool(r.get('stopped'))
    for r in runs][:2], [False, False])
ok_('--busy: ...and the gated run never had more than four engines reading, one a core (%r)'
    % (runs[2].get('engines') if len(runs) > 2 else None),
    len(runs) > 2 and runs[2].get('engines')
    and max(int(e) for e in runs[2]['engines']) <= 4)
ok_('--busy: the busy run with the gate off says its engines at once too (%r)'
    % (runs[1].get('engines') if len(runs) > 1 else None),
    len(runs) > 1 and max(int(e) for e in (runs[1].get('engines') or {'0': 0})) >= 2)
ok_('--busy runs at the rig\'s own priority, not niced (%r)' % busy.get('nice'),
    busy.get('nice') == os.nice(0))
eq('--busy: it wrote nothing in the repository',
   sorted(p for p, v in tree().items() if was.get(p) != v), [])
lines = B.busy_table(busy).splitlines() if runs else []
ok_('--busy: the table, a line for each run with its cards and its tick (%r)' % lines[3:4],
    bool(lines) and all(any(l.startswith(r['run'] + ' ') for l in lines) for r in runs))
ok_('...and each run\'s time: stages', sum(1 for l in lines if ': time: ' in l) == 3)

print('FAILED: %d of %d' % (bad, ok + bad) if bad
      else '\nAll %d pi_bench smoke checks passed' % ok)
sys.exit(1 if bad else 0)
