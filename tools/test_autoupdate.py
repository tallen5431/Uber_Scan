"""The nightly update and the nightly diagnostics, each safety rule on a real git.

    python3 tools/test_autoupdate.py

tools/autoupdate.sh pulls and restarts the rig and the NucBox by itself, so
every rule that keeps it from doing harm is held here against the real thing:
a bare "origin" and a clone of it in a temp dir, a stand-in server (a small
HTTP stub that answers idle, busy or broken, and says how long its "process"
has been up), and a stand-in restart command that notes the commit it
restarted at. Nothing here touches this checkout or the machine: the script
is pointed at the clone with REPO, its settings file at nothing, systemctl at
a stand-in. tools/install-autoupdate.sh is run from a copy inside the clone,
its units and settings written into the temp dir and asked of
systemd-analyze verify where it is installed. tools/places_nightly.sh's new
diagnostics step is run with stand-in tools that fail, to hold that they
never fail the night.

Invented data throughout: commits that say "v2", a journal with no rows.
"""

import fcntl
import http.server
import json
import os
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# AUTOUPDATE_UNDER_TEST: a changed copy, to see a check fail with its rule gone.
SCRIPT = os.environ.get('AUTOUPDATE_UNDER_TEST') or os.path.join(HERE, 'autoupdate.sh')
INSTALLER = os.path.join(HERE, 'install-autoupdate.sh')
NIGHTLY = os.path.join(HERE, 'places_nightly.sh')

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


work = tempfile.mkdtemp(prefix='autoupdate-')
# git's own settings for every git here, the script's included: no signing
# (this machine's global config may sign with a key), a name to commit as,
# and nothing from the system's config.
gitcfg = os.path.join(work, 'gitconfig')
with open(gitcfg, 'w') as fh:
    fh.write('[user]\n\tname = Test Driver\n\temail = driver@example.invalid\n'
             '[commit]\n\tgpgsign = false\n[init]\n\tdefaultBranch = main\n'
             '[advice]\n\tdetachedHead = false\n')
GITENV = dict(os.environ, GIT_CONFIG_GLOBAL=gitcfg, GIT_CONFIG_NOSYSTEM='1',
              TZ='America/New_York')
GITENV.pop('GIT_DIR', None)
GITENV.pop('GIT_WORK_TREE', None)


def git(cwd, *args, check=True):
    got = subprocess.run(['git', '-C', cwd] + list(args), capture_output=True, text=True,
                         env=GITENV, timeout=60)
    if check and got.returncode:
        raise RuntimeError('git %s: %s' % (' '.join(args), got.stderr))
    return got.stdout.strip()


origin = os.path.join(work, 'origin.git')
seed = os.path.join(work, 'seed')
clone = os.path.join(work, 'clone')
subprocess.run(['git', 'init', '--quiet', '--bare', origin], env=GITENV, check=True)
subprocess.run(['git', 'init', '--quiet', seed], env=GITENV, check=True)
git(seed, 'remote', 'add', 'origin', origin)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as fh:
        fh.write(text)


def push(msg, files=None, remove=()):
    """A commit on origin's main, as the gate would push one. Its sha."""
    for name, text in (files or {}).items():
        write(os.path.join(seed, name), text)
    for name in remove:
        git(seed, 'rm', '--quiet', name)
    git(seed, 'add', '-A')
    git(seed, 'commit', '--quiet', '-m', msg)
    git(seed, 'push', '--quiet', 'origin', 'HEAD:main')
    return git(seed, 'rev-parse', 'HEAD')


v1 = push('v1', {'.gitignore': 'rpi/update-status.json*\n', 'server.txt': 'v1\n',
                 'rpi/keep.txt': 'kept\n', 'package.json': '{"name": "x"}\n'})
subprocess.run(['git', 'clone', '--quiet', origin, clone], env=GITENV, check=True)


def head():
    return git(clone, 'rev-parse', 'HEAD')


# --- the stand-in server -------------------------------------------------------
# Its state is a dict the cases set. It answers /api/status as statusNow does,
# with the fields autoupdate.sh reads, and /api/journal/newest. A BROKEN file
# in the clone's working tree is code that cannot serve (500); SCANNER_FALLS
# is a scanner that falls over once restarted. Its "process" was started when
# the restart command last wrote MARK; with no mark, an hour ago.
MARK = os.path.join(work, 'restarted-at')
RESTARTS = os.path.join(work, 'restarts.log')
state = {}


def reset_state():
    state.clear()
    state.update(mode='idle', newest=None)


reset_state()


class Stub(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def answer(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        mode = state['mode']
        if mode == 'down' or os.path.exists(os.path.join(clone, 'BROKEN')):
            return self.answer(500, {'error': 'broken'})
        if self.path.startswith('/api/journal/newest'):
            return self.answer(200, {'ok': True, 'newest': state['newest'] or 0})
        if not self.path.startswith('/api/status'):
            return self.answer(404, {})
        try:
            up = (time.time() - float(open(MARK).read())) * 1000
        except (OSError, ValueError):
            up = 6 * 3600 * 1000
        falls = os.path.exists(os.path.join(clone, 'SCANNER_FALLS'))
        st = {'scanner': {'enabled': True, 'running': not falls, 'fell': 2 if falls else 0},
              'holding': None, 'offerAgeMs': None, 'lastAgeMs': None, 'upMs': round(up),
              'beat': {'ageMs': 1000, 'gps': {'fix': {'driving': False}}}}
        if mode == 'holding':
            st['holding'] = {'pay': 7.5, 'minutes': 12}
        elif mode == 'offer':
            st['offerAgeMs'] = 5 * 60000
        elif mode == 'reading':
            st['lastAgeMs'] = 90 * 1000
        elif mode == 'moving':
            st['beat']['gps']['fix']['driving'] = True
        elif mode == 'notjson':
            data = b'<html>a router login page</html>'
            self.send_response(200)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.answer(200, st)


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


srv = Server(('127.0.0.1', 0), Stub)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

# A port nothing listens on.
_s = Server(('127.0.0.1', 0), Stub)
DEAD = _s.server_address[1]
_s.server_close()

# --- the stand-ins for the restart and systemctl --------------------------------
bin_dir = os.path.join(work, 'bin')
os.makedirs(bin_dir)
restart_sh = os.path.join(work, 'restart.sh')
write(restart_sh, '#!/bin/sh\ndate +%%s.%%N > "%s"\ngit -C "%s" rev-parse HEAD >> "%s"\n'
      % (MARK, clone, RESTARTS))
failing_restart = os.path.join(work, 'restart-fails.sh')
write(failing_restart, '#!/bin/sh\nexit 1\n')
# A restart that leaves something running in the background, holding every
# descriptor it was given, as a manager starting a server would.
lingering_restart = os.path.join(work, 'restart-lingers.sh')
write(lingering_restart, '#!/bin/sh\nsh "%s"\nsleep 30 &\n' % restart_sh)
# systemctl: `show -p ActiveState` answers SYNC_STATE; anything else is noted.
SYSTEMCTL_LOG = os.path.join(work, 'systemctl.log')
fake_systemctl = os.path.join(bin_dir, 'systemctl')
write(fake_systemctl, '#!/bin/sh\necho "$*" >> "%s"\n'
      'if [ "$1" = show ]; then echo "${SYNC_STATE:-inactive}"; fi\nexit 0\n' % SYSTEMCTL_LOG)
for f in (restart_sh, failing_restart, lingering_restart, fake_systemctl):
    os.chmod(f, 0o755)

STATUS = os.path.join(clone, 'rpi', 'update-status.json')
LOCK = os.path.join(clone, '.git', 'uberscan-update.lock')


def restarts():
    try:
        return open(RESTARTS).read().split()
    except OSError:
        return []


def run(extra=None, args=(), timeout=120, server_age=6 * 3600):
    """The script, once. The clock's gates are opened (any hour, no daily cap)
    unless a case sets them, and the stand-in server has been up `server_age`
    seconds — hours, as between two real runs, so the "up long enough to
    vouch for the quiet window" gate holds unless a case says otherwise."""
    if server_age is not None:
        write(MARK, str(time.time() - server_age))
    env = dict(GITENV, REPO=clone, AUTOUPDATE_ENV=os.path.join(work, 'no-such.env'),
               ROLE='rig', PORT=str(PORT), RESTART_CMD='sh "%s"' % restart_sh,
               BOOT_QUIET_MIN='0', HEALTH_TIMEOUT='4', HEALTH_SETTLE='0',
               SYSTEMCTL=fake_systemctl, FETCH_TIMEOUT='30', UPDATE_HOURS='0-23', DAILY_CAP='0')
    env.update(extra or {})
    for k in [k for k, v in env.items() if v is None]:
        del env[k]
    got = subprocess.run(['bash', SCRIPT] + list(args), capture_output=True, text=True,
                         env=env, timeout=timeout)
    return got


def status():
    try:
        return json.load(open(STATUS))
    except (OSError, ValueError):
        return {}


def outcome():
    s = status()
    return (s.get('outcome'), s.get('why'))


try:
    # --- updated and healthy -----------------------------------------------------
    v2 = push('v2', {'server.txt': 'v2\n'})
    got = run()
    eq('a new commit on main, the server idle and well: updated, exit 0 (%s)' % got.stdout.strip(),
       got.returncode, 0)
    eq('...the clone is at the new commit', head(), v2)
    eq('...the status says updated, from and to', (status().get('outcome'), status().get('from'),
                                                   status().get('to')), ('updated', v1, v2))
    eq('...the server was restarted once, at the new commit', restarts(), [v2])
    ok_('...and the journal line says so', 'autoupdate: updated' in got.stdout)
    st = status()
    eq('the status file holds what the owner and the server read', sorted(st),
       sorted(['at', 'atMs', 'outcome', 'why', 'from', 'to', 'branch', 'role', 'note', 'words',
               'refused', 'lastUpdate']))
    ok_('...a few words for /api/status (%r)' % st.get('words'),
        st.get('words') == 'updated %s to %s' % (v1[:7], v2[:7]))
    ok_('...a local time and a time in ms', len(st.get('at', '')) == 19
        and abs(st.get('atMs', 0) / 1000.0 - time.time()) < 60)
    eq('...the branch and the role', (st.get('branch'), st.get('role')), ('main', 'rig'))
    eq('...the last real update kept', st.get('lastUpdate', {}).get('to'), v2)
    eq('...no temporary left beside it', sorted(n for n in os.listdir(os.path.dirname(STATUS))
                                               if n.startswith('update-status')), ['update-status.json'])
    eq('...and the file is not a local change: the tree is clean after it',
       git(clone, 'status', '--porcelain'), '')
    eq("this repository's .gitignore covers it and its temporary, so it is never committed",
       [subprocess.run(['git', '-C', ROOT, 'check-ignore', '-q', p], env=GITENV).returncode
        for p in ('rpi/update-status.json', 'rpi/update-status.json.4321.part')], [0, 0])

    # --- already current ---------------------------------------------------------
    got = run()
    eq('nothing new: current, exit 0', (got.returncode, outcome()), (0, ('current', None)))
    eq('...no restart', restarts(), [v2])
    eq('...the last real update remembered across a night of "current"',
       status().get('lastUpdate', {}).get('to'), v2)

    # --- --status ----------------------------------------------------------------
    got = run(args=['--status'])
    ok_('--status prints the last outcome in words (%r)' % got.stdout,
        got.returncode == 0 and 'current' in got.stdout and 'last updated' in got.stdout)

    # --- dirty tree skipped ------------------------------------------------------
    # A file the update does not touch, so git itself would fast-forward over
    # it happily: the rule is this script's, not git's.
    v3 = push('v3', {'server.txt': 'v3\n'})
    keep = os.path.join(clone, 'rpi', 'keep.txt')
    write(keep, 'a change made by hand on the rig\n')
    got = run()
    eq('a tracked file changed by hand: skipped', outcome()[0], 'skipped')
    ok_('...and said why (%r)' % (outcome()[1],), (outcome()[1] or '').startswith('local changes'))
    eq('...nothing moved', head(), v2)
    eq('...the change is still there, untouched', open(keep).read(), 'a change made by hand on the rig\n')
    eq('...no restart', restarts(), [v2])
    git(clone, 'add', 'rpi/keep.txt')
    got = run()
    ok_('a staged change too', outcome()[0] == 'skipped'
        and (outcome()[1] or '').startswith('local changes') and head() == v2)
    git(clone, 'reset', '--quiet', '--hard', 'HEAD')

    # --- diverged branch skipped -------------------------------------------------
    write(os.path.join(clone, 'local.txt'), 'a commit made on the rig\n')
    git(clone, 'add', 'local.txt')
    git(clone, 'commit', '--quiet', '-m', 'local')
    local = head()
    got = run()
    eq('a local commit beside new ones on origin: skipped', outcome()[0], 'skipped')
    ok_('...cannot fast-forward, said (%r)' % (outcome()[1],), 'diverged' in (outcome()[1] or ''))
    eq('...the local commit kept, nothing reset', head(), local)
    git(clone, 'reset', '--quiet', '--hard', v2)

    # --- busy skipped ------------------------------------------------------------
    for mode, said in (('holding', 'an order is held'), ('offer', 'an offer 5 min ago'),
                       ('reading', 'a reading 2 min ago'), ('moving', 'the car is moving')):
        state['mode'] = mode
        got = run()
        eq('a shift (%s): skipped, nothing moved, no restart' % mode,
           (outcome(), head(), restarts()), (('skipped', 'a shift: ' + said), v2, [v2]))
    state['mode'] = 'idle'
    state['newest'] = int((time.time() - 10 * 60) * 1000)
    got = run()
    eq('an offer in the journal 10 min ago, which the server forgot across a restart: skipped',
       outcome(), ('skipped', 'a shift: an offer in the journal 10 min ago'))
    state['newest'] = int((time.time() - 3 * 3600) * 1000)
    state['mode'] = 'notjson'
    got = run()
    ok_('an answer that is not its status is not "no shift": skipped (%r)' % (outcome(),),
        outcome()[0] == 'skipped' and head() == v2)
    state['mode'] = 'idle'
    got = run()
    eq('an offer three hours ago, past QUIET_MIN: updated', (outcome()[0], head()), ('updated', v3))
    state['newest'] = int((time.time() - 10 * 60) * 1000)
    got = run(extra={'QUIET_MIN': '5'})
    eq('...and QUIET_MIN is the window: ten minutes ago is past five', outcome(), ('current', None))
    state['newest'] = None

    # --- the NucBox: asked only whether it answers --------------------------------
    v4 = push('v4', {'server.txt': 'v4\n'})
    state['mode'] = 'holding'
    got = run(extra={'ROLE': 'nucbox'})
    eq('on the NucBox an order held on the rig is not its shift: updated', (outcome()[0], head()),
       ('updated', v4))
    eq('...and its status says nucbox', status().get('role'), 'nucbox')
    state['mode'] = 'idle'

    # --- server unreachable skipped ----------------------------------------------
    v5 = push('v5', {'server.txt': 'v5\n'})
    n = len(restarts())
    got = run(extra={'PORT': str(DEAD)})
    eq('the rig\'s server not answering: skipped, the cautious side', (outcome()[0], head()),
       ('skipped', v4))
    ok_('...said (%r)' % (outcome()[1],), 'did not answer' in (outcome()[1] or ''))
    got = run(extra={'PORT': str(DEAD), 'ROLE': 'nucbox'})
    eq('...and the NucBox\'s the same', (outcome()[0], head(), len(restarts())), ('skipped', v4, n))
    state['mode'] = 'down'
    got = run()
    eq('a server answering 500: skipped', (outcome()[0], head()), ('skipped', v4))
    state['mode'] = 'idle'

    # --- the lock held skipped ---------------------------------------------------
    # Held here, in this process, and let go by closing it: a `flock FILE
    # sleep` killed leaves its sleep holding the lock.
    def held(path):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX)
        return fd

    fd = held(LOCK)
    try:
        got = run()
        eq('the lock held (an update, a sync or the nightly): skipped, nothing moved',
           (outcome()[0], head()), ('skipped', v4))
        ok_('...said (%r)' % (outcome()[1],), 'lock is held' in (outcome()[1] or ''))
    finally:
        os.close(fd)
    # ...the NucBox's lock is places_nightly.sh's own file: held by a nightly
    # run, the update leaves.
    places_lock = os.path.join(work, 'places-report.lock')
    fd = held(places_lock)
    try:
        got = run(extra={'ROLE': 'nucbox', 'LOCK': places_lock})
        eq('...places_nightly.sh holding its lock: the NucBox update leaves',
           (outcome()[0], head()), ('skipped', v4))
    finally:
        os.close(fd)
    # ...and the lock's mtime is never touched (places_nightly.sh reads it to
    # tell a wedged run from a running one).
    old = time.time() - 4000
    os.utime(places_lock, (old, old))
    got = run(extra={'ROLE': 'nucbox', 'LOCK': places_lock,
                     'RESTART_CMD': 'sh "%s"' % lingering_restart})
    eq('an update under the shared lock: done', (outcome()[0], head()), ('updated', v5))
    ok_('...and the lock\'s mtime is as it was', abs(os.stat(places_lock).st_mtime - old) < 2)
    free = subprocess.run(['flock', '-n', places_lock, 'true']).returncode
    eq('...and a server the restart left running in the background does not hold the lock',
       free, 0)

    # --- a sync running, a rig just booted, the wrong branch, turned off ----------
    v6 = push('v6', {'server.txt': 'v6\n'})
    got = run(extra={'SYNC_STATE': 'activating'})
    eq('a sync running on the rig: skipped', outcome(), ('skipped', 'a sync is running'))
    got = run(extra={'BOOT_QUIET_MIN': '99999999'})
    ok_('a rig booted minutes ago: skipped, a shift starting (%r)' % (outcome(),),
        outcome()[0] == 'skipped' and 'booted' in (outcome()[1] or '') and head() == v5)
    git(clone, 'checkout', '--quiet', '-b', 'experimental')
    got = run()
    ok_('the checkout on another branch than BRANCH: skipped, never switched (%r)' % (outcome(),),
        outcome()[0] == 'skipped' and 'not main' in (outcome()[1] or '')
        and git(clone, 'symbolic-ref', '--short', 'HEAD') == 'experimental')
    git(clone, 'checkout', '--quiet', 'main')
    got = run(extra={'ENABLED': '0'})
    eq('ENABLED=0: skipped, turned off', outcome(), ('skipped', 'turned off (ENABLED=0)'))
    eq('...nothing moved', head(), v5)

    # --- --dry-run ----------------------------------------------------------------
    before = open(STATUS).read()
    got = run(args=['--dry-run'])
    ok_('--dry-run says what it would do (%r)' % got.stdout.strip(),
        got.returncode == 0 and 'would update' in got.stdout)
    eq('...and changes nothing: no merge, no restart, no status written',
       (head(), open(STATUS).read() == before, len(restarts())), (v5, True, n + 1))

    # --- failed health rolled back to the exact previous commit -------------------
    # The clone is at v5; origin has v6 and then the broken v7 on top. The
    # rollback goes to v5, where the clone was, not to v7's parent.
    broken = push('v7 broken', {'BROKEN': 'this build cannot serve\n'})
    got = run()
    eq('the new code not answering: rolled back, exit 3', (got.returncode, outcome()[0]),
       (3, 'rolled back'))
    eq('...to the exact commit it was at (v5), not the broken one\'s parent (v6)',
       (head(), git(clone, 'rev-parse', broken + '^')), (v5, v6))
    eq('...the status says from and to', (status().get('from'), status().get('to')), (v5, broken))
    eq('...restarted at the broken commit, then again at the one before',
       restarts()[-2:], [broken, v5])
    ok_('...said why (%r)' % (outcome()[1],), 'after 4s' in (outcome()[1] or ''))
    eq('...the broken commit remembered as refused', status().get('refused'), broken)
    eq('...the tree clean, the broken file gone with its commit',
       (git(clone, 'status', '--porcelain'), os.path.exists(os.path.join(clone, 'BROKEN'))), ('', False))
    rolled_to = head()
    n = len(restarts())
    got = run()
    ok_('the next night, the same commit is not taken again (%r)' % (outcome(),),
        outcome()[0] == 'skipped' and 'rolled back before' in (outcome()[1] or '')
        and head() == rolled_to and len(restarts()) == n)
    fixed = push('v8 fixed', remove=['BROKEN'])
    got = run()
    eq('a newer commit on the branch: taken, the refusal forgotten',
       (outcome()[0], head(), status().get('refused')), ('updated', fixed, None))

    # --- a scanner that falls over after the restart: rolled back -----------------
    falls = push('v9 scanner falls', {'SCANNER_FALLS': 'x\n'})
    got = run(extra={'HEALTH_SETTLE': '1'})
    eq('the server answering but its scanner falling over: rolled back',
       (outcome()[0], head()), ('rolled back', fixed))
    ok_('...said (%r)' % (outcome()[1],), 'scanner fell over' in (outcome()[1] or ''))
    eq('...and that commit refused', status().get('refused'), falls)
    after_fall = push('v10', {'server.txt': 'v10\n'}, remove=['SCANNER_FALLS'])

    # --- a restart command that fails: rolled back --------------------------------
    got = run(extra={'RESTART_CMD': 'sh "%s"' % failing_restart})
    ok_('the restart command failing: rolled back (%r)' % (outcome(),),
        outcome()[0] == 'rolled back' and 'restart command failed' in (outcome()[1] or '')
        and head() == fixed and status().get('to') == after_fall)
    push('v11a', {'server.txt': 'v11a\n'})

    # --- the old process still answering: not taken for the new one ---------------
    got = run(extra={'RESTART_CMD': 'true'})   # the "process" stays six hours old
    ok_('a restart that left the old process answering: rolled back (%r)' % (outcome(),),
        outcome()[0] == 'rolled back' and 'old process' in (outcome()[1] or '') and head() == fixed)
    v11 = push('v11', {'server.txt': 'v11\n'})
    got = run()
    eq('...and a real restart of a newer commit afterwards: updated', (outcome()[0], head()),
       ('updated', v11))

    # --- requirements changed: a person's job ------------------------------------
    req = push('v12 adds a requirement', {'requirements.txt': 'numpy\n'})
    got = run()
    ok_('a requirements file in the update: skipped, needs a manual update (%r)' % (outcome(),),
        outcome() == ('skipped', 'needs a manual update: requirements changed (requirements.txt)')
        and head() == v11 and status().get('to') == req)
    git(seed, 'reset', '--quiet', '--hard', v11)
    git(seed, 'push', '--quiet', '--force', 'origin', 'HEAD:main')
    deps = push('v12b', {'package.json': '{"name": "x", "dependencies": {"left-pad": "1.0.0"}}\n'})
    got = run()
    ok_('...package.json gaining dependencies, the same (%r)' % (outcome(),),
        outcome()[0] == 'skipped' and 'package.json' in (outcome()[1] or '') and head() == v11
        and status().get('to') == deps)
    git(seed, 'reset', '--quiet', '--hard', v11)
    git(seed, 'push', '--quiet', '--force', 'origin', 'HEAD:main')
    lite1 = push('lite installer', {'lite/install.sh': 'pkgs=(python3-picamera2 nodejs)\necho hi\n'})
    got = run()
    eq('a lite/install.sh that is new is its packages new: skipped',
       (outcome()[0], head(), status().get('to')), ('skipped', v11, lite1))
    git(seed, 'reset', '--quiet', '--hard', v11)
    git(seed, 'push', '--quiet', '--force', 'origin', 'HEAD:main')
    write(os.path.join(seed, 'lite', 'install.sh'), 'pkgs=(python3-picamera2 nodejs)\necho hi\n')
    v13 = push('v13 lite installer')
    got = run(extra={'ROLE': 'nucbox'})
    eq('...(on the NucBox, which runs no reader, the lite packages are not its business)',
       (outcome()[0], head()), ('updated', v13))
    ok_('...and the changed installer is noted (%r)' % status().get('note'),
        'lite/install.sh changed' in (status().get('note') or ''))
    v14 = push('v14 comment only', {'lite/install.sh': 'pkgs=(python3-picamera2 nodejs)\necho hello\n'})
    got = run()
    eq('a lite/install.sh change that leaves its packages alone: taken', (outcome()[0], head()),
       ('updated', v14))

    # --- an untracked file the update would overwrite: refused, kept --------------
    write(os.path.join(clone, 'notes.txt'), 'the owner\'s own notes\n')
    v15 = push('v15 adds notes.txt', {'notes.txt': 'a file of the same name\n'})
    got = run()
    ok_('an untracked file in the way: skipped, the fast-forward refused (%r)' % (outcome(),),
        outcome()[0] == 'skipped' and 'refused' in (outcome()[1] or '') and head() == v14)
    eq('...and the file kept as it was', open(os.path.join(clone, 'notes.txt')).read(),
       'the owner\'s own notes\n')
    os.remove(os.path.join(clone, 'notes.txt'))

    # --- VERIFY_SIGNED: an unsigned commit is not taken ----------------------------
    got = run(extra={'VERIFY_SIGNED': '1'})
    ok_('VERIFY_SIGNED=1 and an unsigned commit: skipped (%r)' % (outcome(),),
        outcome()[0] == 'skipped' and 'not signed' in (outcome()[1] or '') and head() == v14)

    # --- a fetch that fails --------------------------------------------------------
    got = run(extra={'REMOTE': 'nowhere'})
    ok_('a remote that cannot be fetched: skipped, said (%r)' % (outcome(),),
        outcome()[0] == 'skipped' and 'could not fetch' in (outcome()[1] or '') and head() == v14)
    got = run(extra={'BRANCH': 'lite'})
    ok_('BRANCH=lite before that branch exists (and the checkout not on it): skipped (%r)'
        % (outcome(),), outcome()[0] == 'skipped' and head() == v14)

    # --- the settings file: KEY=value, quotes, the environment winning --------------
    envfile = os.path.join(work, 'autoupdate.env')
    noted = os.path.join(work, 'from-the-file')
    # As the installer writes it: one level of quotes, the rest verbatim.
    write(envfile, '# a comment\nROLE=nucbox\nPORT=%d\nUNKNOWN=ignored\n'
          'RESTART_CMD="sh "%s" && printf %%s "$HOME" > "%s""\n' % (PORT, restart_sh, noted))
    got = run(extra={'AUTOUPDATE_ENV': envfile, 'ROLE': None, 'PORT': None, 'RESTART_CMD': None})
    eq('settings from the file, RESTART_CMD with quotes and $ run as written: updated',
       (outcome()[0], head(), status().get('role')), ('updated', v15, 'nucbox'))
    ok_('...the command ran whole', os.path.exists(noted))
    got = run(extra={'AUTOUPDATE_ENV': envfile, 'ENABLED': '0'})
    eq('...and the environment wins over the file', outcome(), ('skipped', 'turned off (ENABLED=0)'))

    # --- the rig's hourly cadence: the quiet window, the hours, once a day ---------
    # The rig's timer is hourly (a Pi in a car is off at 04:20 most nights),
    # so the script's own gates are what keep it to one quiet moment a day.
    # Times on the rig's clock, America/New_York; AUTOUPDATE_NOW is "now".
    from zoneinfo import ZoneInfo

    def at(day, hh, mm):
        import datetime
        return str(int(datetime.datetime(2026, 11, day, hh, mm,
                                         tzinfo=ZoneInfo('America/New_York')).timestamp()))

    v16 = push('v16', {'server.txt': 'v16\n'})
    state['newest'] = int((time.time() - 75 * 60) * 1000)
    got = run()
    eq('the rig\'s default quiet window is 90 minutes: an offer 75 minutes ago is a shift',
       outcome(), ('skipped', 'a shift: an offer in the journal 75 min ago'))
    state['newest'] = None
    got = run(server_age=30 * 60)
    eq('a server up 30 minutes cannot vouch for 90 quiet ones: skipped (a rig booted for a shift)',
       (outcome(), head()), (('skipped', 'a shift: the server has been up only 30 min, too short '
                              'to vouch for the quiet window'), v15))
    before = open(STATUS).read()
    got = run(extra={'UPDATE_HOURS': None, 'DAILY_CAP': None, 'AUTOUPDATE_NOW': at(23, 12, 30)})
    ok_('12:30, in the lunch rush the default UPDATE_HOURS leaves out: skipped in the journal (%r)'
        % got.stdout.strip(), got.returncode == 0 and 'outside UPDATE_HOURS (22-10,14-16)' in got.stdout
        and head() == v15)
    eq('...and the status file still says what last happened', open(STATUS).read(), before)
    got = run(extra={'UPDATE_HOURS': None, 'DAILY_CAP': None, 'AUTOUPDATE_NOW': at(23, 18, 40)})
    ok_('...18:40, the dinner rush, the same', 'outside UPDATE_HOURS' in got.stdout and head() == v15)
    got = run(extra={'UPDATE_HOURS': 'lunchtime'})
    ok_('an UPDATE_HOURS nobody can read is a closed gate, said (%r)' % (outcome(),),
        outcome()[0] == 'skipped' and 'UPDATE_HOURS is not understood' in (outcome()[1] or '')
        and head() == v15)
    got = run(extra={'UPDATE_HOURS': None, 'DAILY_CAP': None, 'AUTOUPDATE_NOW': at(23, 2, 30)})
    eq('02:30 on the 23rd, inside 22-10 across midnight, no update yet this driver day: updated',
       (outcome()[0], head()), ('updated', v16))
    ok_('...the status stamped on the rig\'s clock (%r)' % status().get('at'),
        status().get('at') == '2026-11-23 02:30:00' and status()['lastUpdate'].get('atMs')
        == int(at(23, 2, 30)) * 1000)
    v17 = push('v17', {'server.txt': 'v17\n'})
    before = open(STATUS).read()
    got = run(extra={'UPDATE_HOURS': None, 'DAILY_CAP': None, 'AUTOUPDATE_NOW': at(23, 3, 55)})
    ok_('03:55, still the driver day that 02:30 was in: once a day, skipped in the journal (%r)'
        % got.stdout.strip(), 'already updated this driver day (at 02:30)' in got.stdout
        and head() == v16)
    eq('...the status file untouched, still "updated"', (open(STATUS).read() == before,
                                                         status().get('outcome')), (True, 'updated'))
    got = run(extra={'UPDATE_HOURS': None, 'DAILY_CAP': None, 'AUTOUPDATE_NOW': at(23, 4, 5)})
    eq('04:05, just past the 4am turn, a new driver day: updated', (outcome()[0], head()),
       ('updated', v17))
    v18 = push('v18', {'server.txt': 'v18\n'})
    got = run(extra={'UPDATE_HOURS': None, 'DAILY_CAP': None, 'AUTOUPDATE_NOW': at(23, 15, 10)})
    ok_('15:10 the same day, inside the hours: the day\'s one update was at 04:05, skipped',
        'already updated this driver day (at 04:05)' in got.stdout and head() == v17)
    got = run(extra={'UPDATE_HOURS': None, 'DAILY_CAP': None, 'AUTOUPDATE_NOW': at(24, 3, 59)})
    ok_('03:59 the next morning is still that driver day', 'already updated' in got.stdout
        and head() == v17)
    got = run(extra={'UPDATE_HOURS': None, 'DAILY_CAP': None, 'AUTOUPDATE_NOW': at(24, 4, 0)})
    eq('04:00 sharp is the next one: updated', (outcome()[0], head()), ('updated', v18))
    v19 = push('v19', {'server.txt': 'v19\n'})
    got = run(extra={'ROLE': 'nucbox', 'UPDATE_HOURS': None, 'DAILY_CAP': None,
                     'AUTOUPDATE_NOW': at(24, 12, 30)})
    eq('the NucBox has neither gate: 12:30, a second update that driver day, taken',
       (outcome()[0], head()), ('updated', v19))
    latest = v19

    # --- the installer ------------------------------------------------------------
    # A copy of the two scripts inside the clone (as they are in a checkout),
    # its units and settings into the temp dir. Root here, so the account the
    # checkout belongs to is root.
    os.makedirs(os.path.join(clone, 'tools'), exist_ok=True)
    for name in ('autoupdate.sh', 'install-autoupdate.sh'):
        shutil.copy(os.path.join(HERE, name), os.path.join(clone, 'tools', name))
    write(os.path.join(clone, '.git', 'info', 'exclude'), 'tools/\n')
    units = os.path.join(work, 'units')
    etc = os.path.join(work, 'etc-uberscan')
    os.makedirs(units)

    def install(*args, stdin=None):
        env = dict(GITENV, UNIT_DIR=units, ENV_DIR=etc, PATH=bin_dir + ':' + os.environ['PATH'],
                   SYNC_STATE='inactive')
        return subprocess.run(['bash', os.path.join(clone, 'tools', 'install-autoupdate.sh')]
                              + list(args), capture_output=True, text=True, env=env,
                              timeout=120, stdin=subprocess.DEVNULL)

    def value(text, key):
        for line in text.splitlines():
            if line.startswith(key + '='):
                return line[len(key) + 1:]
        return None

    open(SYSTEMCTL_LOG, 'w').close()
    got = install('rig')
    eq('[install] rig: exit 0 (%r)' % got.stderr[-200:], got.returncode, 0)
    envtxt = open(os.path.join(etc, 'autoupdate.env')).read()
    eq('[install] ...the settings: rig, on, main, 8080, the checkout',
       [value(envtxt, k) for k in ('ROLE', 'ENABLED', 'BRANCH', 'PORT', 'REPO')],
       ['rig', '1', 'main', '8080', '"%s"' % clone])
    eq('[install] ...no RESTART_CMD on the rig: the script\'s own systemctl', value(envtxt, 'RESTART_CMD'), None)
    svc = open(os.path.join(units, 'uberscan-update.service')).read()
    tmr = open(os.path.join(units, 'uberscan-update.timer')).read()
    eq('[install] ...the service runs as root on the rig, the script in the checkout',
       (value(svc, 'User'), value(svc, 'ExecStart')),
       ('root', '/bin/bash "%s/tools/autoupdate.sh"' % clone))
    eq('[install] ...the rig\'s timer hourly, up to twenty minutes\' spread, never caught up at boot',
       (value(tmr, 'OnCalendar'), value(tmr, 'RandomizedDelaySec'), value(tmr, 'Persistent')),
       ('hourly', '20min', None))
    eq('[install] ...its quiet window 90 minutes, its hours and its once a day',
       [value(envtxt, k) for k in ('QUIET_MIN', 'UPDATE_HOURS', 'DAILY_CAP')],
       ['90', '"22-10,14-16"', '1'])
    ok_('[install] ...and a run is capped inside the hour, so the next never meets it',
        value(svc, 'TimeoutStartSec') == '20min')
    ok_('[install] ...the timer enabled', 'enable --now uberscan-update.timer' in open(SYSTEMCTL_LOG).read())
    ok_('[install] ...and it tried once, with --dry-run (%r)' % got.stdout[-300:],
        'trying it once' in got.stdout and 'autoupdate:' in got.stdout)
    eq('[install] ...which changed nothing', head(), latest)
    if shutil.which('systemd-analyze'):
        for unit in ('uberscan-update.service', 'uberscan-update.timer'):
            said = subprocess.run(['systemd-analyze', 'verify', os.path.join(units, unit)],
                                  capture_output=True, text=True, timeout=60)
            eq('[install] systemd-analyze verify has nothing to say of %s' % unit,
               [ln for ln in (said.stdout + said.stderr).splitlines()
                if 'uberscan-update' in ln or 'Unknown' in ln or 'Invalid' in ln], [])
    restart_cmd = 'sh "%s" && echo "$HOME %%s" > /dev/null' % restart_sh
    got = install('nucbox', '--restart-cmd', restart_cmd, '--lock', places_lock, '--branch', 'main')
    eq('[install] nucbox: exit 0 (%r)' % got.stderr[-200:], got.returncode, 0)
    envtxt = open(os.path.join(etc, 'autoupdate.env')).read()
    eq('[install] ...nucbox, 8082, the lock given, the restart command verbatim in one pair of quotes',
       [value(envtxt, k) for k in ('ROLE', 'PORT', 'LOCK', 'RESTART_CMD')],
       ['nucbox', '8082', '"%s"' % places_lock, '"%s"' % restart_cmd])
    svc = open(os.path.join(units, 'uberscan-update.service')).read()
    tmr = open(os.path.join(units, 'uberscan-update.timer')).read()
    eq('[install] ...run as the checkout\'s owner on the NucBox', value(svc, 'User'), 'root')
    eq('[install] ...its timer nightly at 04:20, clear of the report at 05:17, no clock gates written',
       (value(tmr, 'OnCalendar'), value(tmr, 'RandomizedDelaySec'), value(envtxt, 'UPDATE_HOURS'),
        value(envtxt, 'DAILY_CAP')), ('*-*-* 04:20:00', '10min', None, None))
    got = install('rig', '--hours', '')
    ok_('[install] --hours \'\' on the rig: any hour', got.returncode == 0 and value(
        open(os.path.join(etc, 'autoupdate.env')).read(), 'UPDATE_HOURS') == '""')
    got = install('rig', '--hours', 'evenings')
    ok_('[install] ...and an unreadable --hours refused', got.returncode != 0)
    got = install('nucbox')
    ok_('[install] nucbox with no restart command and nobody to ask: refused, and says how to find it',
        got.returncode != 0 and 'ps -eo' in got.stdout + got.stderr)
    got = install('rig', '--branch', 'lite')
    ok_('[install] a branch the checkout is not on: refused, never switched (%r)' % got.stderr[-120:],
        got.returncode != 0 and 'git checkout lite' in got.stderr
        and git(clone, 'symbolic-ref', '--short', 'HEAD') == 'main')
    got = install('nucbox', '--restart-cmd', restart_cmd)
    envtxt = open(os.path.join(etc, 'autoupdate.env')).read()
    import pwd
    owner_home = pwd.getpwnam(pwd.getpwuid(os.stat(clone).st_uid).pw_name).pw_dir
    eq('[install] ...with no --lock and no places.env, the NucBox lock is places_nightly.sh\'s default',
       (got.returncode, value(envtxt, 'ROLE'), value(envtxt, 'LOCK')),
       (0, 'nucbox', '"%s/places-report.lock"' % owner_home))
    # The written settings, read back by the script itself: the command runs.
    v20 = push('v20', {'server.txt': 'v20\n'})
    got = run(extra={'AUTOUPDATE_ENV': os.path.join(etc, 'autoupdate.env'), 'ROLE': None,
                     'PORT': str(PORT), 'RESTART_CMD': None, 'LOCK': places_lock, 'REPO': None})
    eq('[install] the settings it wrote, read by the update: updated with its restart command',
       (outcome()[0], head(), restarts()[-1]), ('updated', v20, v20))
    got = install('off')
    envtxt = open(os.path.join(etc, 'autoupdate.env')).read()
    ok_('[install] off: the timer disabled and ENABLED=0',
        'disable --now uberscan-update.timer' in open(SYSTEMCTL_LOG).read()
        and value(envtxt, 'ENABLED') == '0'
        and [ln for ln in envtxt.splitlines() if ln.startswith('ENABLED=')] == ['ENABLED=0'])
finally:
    srv.shutdown()

# --- the real server: /api/status says how long it has been up, and the night --
# server.js with no scanner, its journal and the status file in the temp dir.
sdir = os.path.join(work, 'server')
os.makedirs(sdir)
sfile = os.path.join(sdir, 'update-status.json')
_p = Server(('127.0.0.1', 0), Stub)
SPORT = _p.server_address[1]
_p.server_close()


def real_status():
    import urllib.request
    with urllib.request.urlopen('http://127.0.0.1:%d/api/status' % SPORT, timeout=5) as r:
        return json.load(r)


node = subprocess.Popen(['node', os.path.join(ROOT, 'server.js')], cwd=sdir,
                        env=dict(os.environ, SCANNER='0', PORT=str(SPORT), HTTPS_PORT='0',
                                 JOURNAL=os.path.join(sdir, 'journal.jsonl'), HOME=sdir,
                                 UPDATE_STATUS=sfile, HOST='127.0.0.1'),
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    st = None
    for _ in range(100):
        try:
            st = real_status()
            break
        except OSError:
            time.sleep(0.1)
    ok_('[server] /api/status answers', isinstance(st, dict))
    st = st or {}
    ok_('[server] ...with upMs, this process\'s age (%r)' % st.get('upMs'),
        isinstance(st.get('upMs'), int) and 0 <= st['upMs'] < 60000)
    eq('[server] ...and no update yet: null', st.get('update', 'absent'), None)
    node.terminate()
    node.wait(timeout=10)
    write(sfile, json.dumps({'outcome': 'skipped', 'why': 'a shift: an order is held',
                             'words': 'skipped: a shift: an order is held',
                             'atMs': int(time.time() * 1000) - 5000, 'from': 'a' * 40, 'to': None}))
    node = subprocess.Popen(node.args, cwd=sdir, env=dict(os.environ, SCANNER='0', PORT=str(SPORT),
                            HTTPS_PORT='0', JOURNAL=os.path.join(sdir, 'journal.jsonl'), HOME=sdir,
                            UPDATE_STATUS=sfile, HOST='127.0.0.1'),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    st = None
    for _ in range(100):
        try:
            st = real_status()
            break
        except OSError:
            time.sleep(0.1)
    up = (st or {}).get('update') or {}
    eq('[server] the last night in a few words, and its age rather than its time',
       (up.get('outcome'), up.get('words'), up.get('from'), up.get('to')),
       ('skipped', 'skipped: a shift: an order is held', 'a' * 40, None))
    ok_('[server] ...age %r ms' % up.get('ageMs'), isinstance(up.get('ageMs'), int)
        and 4000 <= up['ageMs'] < 60000 and 'atMs' not in up)
finally:
    node.terminate()
    node.wait(timeout=10)

# --- the nightly's diagnostics never fail the night ---------------------------
home = os.path.join(work, 'home')
nbin = os.path.join(work, 'nbin')
os.makedirs(home)
os.makedirs(nbin)
calls = os.path.join(work, 'nightly-calls.log')
# A node that builds a page for places_report.js, and for report_check.js
# prints a count, a tag to escape and a secret on stderr — or fails.
fake_node = os.path.join(nbin, 'node')
write(fake_node, '#!/bin/sh\necho "node $*" >> "%s"\n'
      'case "$1" in\n'
      '*places_report.js) while [ "$1" != "--out" ]; do shift; done; mkdir -p "$2";'
      ' echo "<html>report</html>" > "$2/index.html"; exit 0 ;;\n'
      '*report_check.js) echo "SECRET-ON-STDERR" >&2;'
      ' [ -n "$CHECK_FAILS" ] && exit 7; echo "offers 12 <b>"; exit 0 ;;\n'
      'esac\nexit 9\n' % calls)
fake_python = os.path.join(nbin, 'python3')
write(fake_python, '#!/bin/sh\necho "python $*" >> "%s"\n'
      '[ -n "$CHECK_FAILS" ] && exit 1; echo "twinPairs: 3"; exit 0\n' % calls)
os.chmod(fake_node, 0o755)
os.chmod(fake_python, 0o755)
out = os.path.join(home, 'places-report')


def nightly(extra=None):
    env = dict(os.environ, HOME=home, PLACES_ENV=os.path.join(home, 'none.env'),
               PLACES_NODE=fake_node, PLACES_PYTHON=fake_python, RIG_HOST='',
               PLACES_SERVER='http://127.0.0.1:%d' % DEAD, PLACES_JOURNAL=os.path.join(home, 'j.jsonl'))
    env.update(extra or {})
    return subprocess.run(['bash', NIGHTLY], capture_output=True, text=True, env=env, timeout=120)


got = nightly({'CHECK_FAILS': '1'})
log = open(os.path.join(home, 'places-report.log')).read()
eq('[nightly] both diagnostics failing: the night still exits 0', got.returncode, 0)
ok_('[nightly] ...the report swapped in', os.path.islink(out)
    and open(os.path.join(out, 'index.html')).read().startswith('<html>report'))
page = open(os.path.join(out, 'checks.html')).read() if os.path.exists(os.path.join(out, 'checks.html')) else ''
eq('[nightly] ...the checks page says each did not finish', page.count('did not finish cleanly'), 2)
ok_('[nightly] ...and the log says so, and that the report was built regardless',
    log.count('did not finish cleanly') == 2 and 'done: ' in log)
ok_('[nightly] ...the report was asked to link the page (--checks checks.html)',
    '--checks checks.html' in open(calls).read())
ok_('[nightly] ...report_check against the same server, twin_ids against PLACES_JOURNAL',
    'report_check.js http://127.0.0.1:%d' % DEAD in open(calls).read()
    and 'twin_ids.py %s' % os.path.join(home, 'j.jsonl') in open(calls).read())
got = nightly()
page = open(os.path.join(out, 'checks.html')).read()
txt = open(os.path.join(out, 'checks.txt')).read()
ok_('[nightly] both working: their counts on the page, escaped', got.returncode == 0
    and 'offers 12 &lt;b&gt;' in page and 'twinPairs: 3' in page and 'href="index.html"' in page)
ok_('[nightly] ...and in checks.txt as printed', 'offers 12 <b>' in txt and 'twinPairs: 3' in txt)
ok_('[nightly] ...a tool\'s stderr goes to the log, never onto the page',
    'SECRET-ON-STDERR' not in page and 'SECRET-ON-STDERR' not in txt
    and 'SECRET-ON-STDERR' in open(os.path.join(home, 'places-report.log')).read())
open(calls, 'w').close()
got = nightly({'PLACES_CHECKS': '0'})
ok_('[nightly] PLACES_CHECKS=0: no diagnostics, no link asked for',
    got.returncode == 0 and 'report_check' not in open(calls).read()
    and '--checks' not in open(calls).read() and not os.path.exists(os.path.join(out, 'checks.html')))
# A diagnostic that hangs is stopped at CHECKS_TIMEOUT and the night goes on.
hang = os.path.join(nbin, 'python-hangs')
write(hang, '#!/bin/sh\nsleep 30\n')
os.chmod(hang, 0o755)
t0 = time.time()
got = nightly({'PLACES_PYTHON': hang, 'CHECKS_TIMEOUT': '1'})
ok_('[nightly] a diagnostic that hangs is stopped at CHECKS_TIMEOUT and the night goes on (%.1fs)'
    % (time.time() - t0), got.returncode == 0 and time.time() - t0 < 20
    and 'did not finish cleanly' in open(os.path.join(out, 'checks.html')).read())

shutil.rmtree(work, ignore_errors=True)
print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d autoupdate checks passed' % ok)
sys.exit(1 if bad else 0)
