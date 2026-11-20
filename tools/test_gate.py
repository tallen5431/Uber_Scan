"""tools/test.sh's verdict, over stub suites in a scratch checkout.

    python3 tools/test_gate.py

The gate printed suites in a fixed order and stopped at the first with no
.done file; the count it ended on covered only what it had printed. A runner
killed with -9 (the OOM killer, a stray kill) writes no .done, so the suites
after it went unsaid and the gate said "all 1 suites passed" and exited 0 over
five. Here the shipped script is run as it is, in a temp directory holding
only invented suites of a few lines, one of which kills its own runner: in
the pool (two at once) and one at a time. Nothing of the real suites runs.
"""

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

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


PASS = 'print("All 1 stub checks passed")\n'
# Kills the subshell tools/test.sh started this suite's runner in: the one
# just below the gate's own shell, among this process's ancestors. A forked
# subshell carries the gate's command line (`bash <dir>/tools/test.sh`), so
# the gate is the topmost of the unbroken run of those above this suite.
# Then finishes as a passing suite would, with nobody left to say so.
KILL_RUNNER = r'''
import os, signal
def up(pid):
    with open('/proc/%d/stat' % pid) as fh:
        return int(fh.read().rsplit(')', 1)[1].split()[1])
def gate(pid):
    with open('/proc/%d/cmdline' % pid, 'rb') as fh:
        args = fh.read().split(b'\0')
    return len(args) > 1 and args[1].endswith(b'/tools/test.sh')
chain, pid = [], up(os.getpid())
while pid > 1 and not gate(pid):
    pid = up(pid)
while pid > 1 and gate(pid):
    chain.append(pid)
    pid = up(pid)
os.kill(chain[-2], signal.SIGKILL)
print("All 1 stub checks passed")
'''


def checkout(work, suites):
    os.makedirs(os.path.join(work, 'tools'))
    os.makedirs(os.path.join(work, 'rpi'))
    os.makedirs(os.path.join(work, 'tests'))
    shutil.copy(os.path.join(ROOT, 'tools', 'test.sh'), os.path.join(work, 'tools', 'test.sh'))
    for rel, body in suites.items():
        with open(os.path.join(work, rel), 'w') as fh:
            fh.write(body)


def gate(work, jobs):
    got = subprocess.run(['bash', os.path.join(work, 'tools', 'test.sh')],
                         env=dict(os.environ, TEST_JOBS=str(jobs)), capture_output=True,
                         text=True, timeout=120)
    return got.returncode, got.stdout


if not os.path.isdir('/proc/self'):
    print('  (no /proc here, so no runner can be found to kill: skipping)')
else:
    work = tempfile.mkdtemp()
    try:
        killed = os.path.join(work, 'killed')
        checkout(killed, {'rpi/test_a.py': PASS, 'rpi/test_b.py': KILL_RUNNER,
                          'rpi/test_c.py': PASS, 'tools/test_t.py': PASS, 'tests/x.test.js':
                          'console.log("All 1 stub checks passed");\n'})
        for jobs in (2, 1):
            code, out = gate(killed, jobs)
            last = out.rstrip().splitlines()[-1] if out.strip() else ''
            eq('[gate %d at once] a runner killed with -9: exit 1, and the last line names the '
               'suite with no result (%r)' % (jobs, out[-300:]),
               (code, last), (1, '1 of 5 suites gave no result: test_b.py'))
            ok_('[gate %d at once] ...and the suites after it are still each said' % jobs,
                'test_c.py' in out and 'test_t.py' in out and 'x.test.js' in out
                and 'NO RESULT' in out.split('test_b.py', 1)[-1].split('\n', 1)[0])
        whole = os.path.join(work, 'whole')
        checkout(whole, {'rpi/test_a.py': PASS, 'rpi/test_c.py': PASS, 'tools/test_t.py': PASS,
                         'tests/x.test.js': 'console.log("All 1 stub checks passed");\n'})
        code, out = gate(whole, 2)
        eq('[gate] every suite with its result: all of them counted, exit 0',
           (code, out.rstrip().splitlines()[-1] if out.strip() else ''),
           (0, 'all 4 suites passed'))
    finally:
        shutil.rmtree(work, ignore_errors=True)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d gate checks passed' % ok)
sys.exit(1 if bad else 0)
