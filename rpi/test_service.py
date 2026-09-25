"""The systemd unit, as the installer actually writes it.

    python3 rpi/test_service.py

`install-service.sh` is the only file here that produces something the rest of
the project never reads back: a unit in /etc that systemd parses on a machine
nobody is watching. Two faults lived in it for as long as it existed, and
neither could have been noticed by running anything.

It started `scan_pi.py`, which is the scanner and nothing else — it reads
rpi/config.json and begins. On a rig that has never been calibrated there is no
config, so it exits at once, and the unit restarts on failure: a service
respawning every five seconds forever behind a blank live view. Everything else
in the project — the web server, the README, the whole design — goes through
`autopilot.py`, which aims and calibrates first and then becomes the scanner.

And `StartLimitIntervalSec` sat in `[Service]`. systemd moved it to `[Unit]` in
v230 and does not error on the old placement: it logs "Unknown key name" and
carries on with the default. The line meant to stop the unit giving up was
being silently dropped.

So the script is run against a temporary root and what it wrote is read back.
Nothing here touches the real /etc, and nothing needs systemd to be installed.
"""

import getpass
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, 'rpi', 'install-service.sh')
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


if shutil.which('bash') is None:
    print('no bash on this machine — skipping the service checks')
    sys.exit(0)

# The script refuses to run as anyone but root and then writes to /etc and calls
# systemctl, none of which belongs in a test. Only the part that composes the
# unit is wanted, so it is run with `id` and `systemctl` shadowed and the output
# path redirected — the heredoc itself is the shipped code either way.
work = tempfile.mkdtemp()
stub = os.path.join(work, 'bin')
os.makedirs(stub)
for name, body in (
    # Pretend to be root without being it.
    ('id', '#!/bin/sh\necho 0\n'),
    # Record what would have been done to the system, and do none of it.
    ('systemctl', '#!/bin/sh\necho "$@" >> "%s/systemctl.log"\n' % work),
    ('logname', '#!/bin/sh\necho driver\n'),
):
    path = os.path.join(stub, name)
    with open(path, 'w') as fh:
        fh.write(body)
    os.chmod(path, 0o755)

unit_dir = os.path.join(work, 'etc', 'systemd', 'system')
os.makedirs(unit_dir)
script = open(SCRIPT).read()
# The one absolute path in the file, pointed somewhere harmless.
patched = script.replace('/etc/systemd/system/uberscan.service',
                         os.path.join(unit_dir, 'uberscan.service'))
eq('the installer writes exactly one unit file',
   script.count('/etc/systemd/system/uberscan.service'), 1)
# Placed as rpi/install-service.sh under a stand-in project directory, because
# the script derives every path from its own location — "a clone in a home
# directory works without editing anything" is a promise it makes, and this is
# where it gets checked.
project = os.path.join(work, 'project')
os.makedirs(os.path.join(project, 'rpi'))
run_me = os.path.join(project, 'rpi', 'install-service.sh')
with open(run_me, 'w') as fh:
    fh.write(patched)

proc = subprocess.run(
    ['bash', run_me],
    env=dict(os.environ, PATH=stub + os.pathsep + os.environ.get('PATH', ''),
             SUDO_USER='driver', SPEAK='1'),
    capture_output=True, text=True, timeout=60)
eq('the installer runs cleanly', proc.returncode, 0)
if proc.returncode != 0:
    print(proc.stdout[-800:])
    print(proc.stderr[-800:])

unit_path = os.path.join(unit_dir, 'uberscan.service')
ok_('...and leaves a unit behind', os.path.exists(unit_path))
unit = open(unit_path).read() if os.path.exists(unit_path) else ''


def section_of(key):
    """Which [Section] a key was written under."""
    here = None
    for line in unit.split('\n'):
        line = line.strip()
        if line.startswith('[') and line.endswith(']'):
            here = line
        elif line.startswith(key + '='):
            return here
    return None


# --- what it starts --------------------------------------------------------
start = re.search(r'^ExecStart=(.*)$', unit, re.M)
ok_('the unit has an ExecStart', start is not None)
command = start.group(1) if start else ''
# The unit runs the web server, which spawns the autopilot. It used to run
# the autopilot alone, and a rig booted that way had a driving screen that
# could never show a verdict: readings reach the panel only through the
# server that spawned the scanner.
ok_('it starts the web server, which is where the panel gets its verdicts',
    'server.js' in command)
ok_('...and not the scanner directly', 'scan_pi.py' not in command
    and 'autopilot.py' not in command)
ok_('...with node found on this machine (%s)' % command.split()[0],
    os.path.exists(command.split()[0]) if command else False)
named = [word for word in command.split() if word.endswith('.js')]
eq('...naming exactly one script', len(named), 1)
ok_('...that exists in this checkout (%s)' % (os.path.basename(named[0]) if named else ''),
    bool(named) and os.path.exists(os.path.join(ROOT, os.path.basename(named[0]))))
ok_('...told to speak', re.search(r'^Environment=SCANNER_SPEAK=1$', unit, re.M) is not None)

# The web server spawns the autopilot, which can calibrate an uncalibrated
# rig, and reads SCANNER_SPEAK to decide whether it speaks.
server = open(os.path.join(ROOT, 'server.js')).read()
ok_('the web server spawns the autopilot',
    "'autopilot.py'" in server and 'SCANNER_SPEAK' in server)

# --- and how it survives a Pi that is not ready ---------------------------
eq('the restart limit is in the section systemd reads it from',
   section_of('StartLimitIntervalSec'), '[Unit]')
eq('...and the restart policy is in the one it reads that from',
   section_of('Restart'), '[Service]')
ok_('it retries rather than giving up', 'Restart=on-failure' in unit)

# --- and the shape of the thing -------------------------------------------
for key, want in (('User', '[Service]'), ('WorkingDirectory', '[Service]'),
                  ('WantedBy', '[Install]'), ('Description', '[Unit]')):
    eq('%s is under %s' % (key, want), section_of(key), want)
ok_('nothing was left unsubstituted', '$' not in unit)
ok_('it runs as the invoking user rather than root',
    re.search(r'^User=driver$', unit, re.M) is not None)
ok_('...from wherever the script was run, not a path baked in at authoring time',
    re.search(r'^WorkingDirectory=' + re.escape(project) + '$', unit, re.M) is not None)
ok_('...and starts the copy that lives there',
    re.search(r'^ExecStart=\S+ ' + re.escape(project) + r'/server\.js$', unit, re.M)
    is not None)

# --- SPEAK=0 is the other supported way to run it -------------------------
os.remove(unit_path)
quiet = subprocess.run(
    ['bash', run_me],
    env=dict(os.environ, PATH=stub + os.pathsep + os.environ.get('PATH', ''),
             SUDO_USER='driver', SPEAK='0'),
    capture_output=True, text=True, timeout=60)
eq('SPEAK=0 installs too', quiet.returncode, 0)
quiet_unit = open(unit_path).read() if os.path.exists(unit_path) else ''
ok_('...and leaves the speech off', re.search(r'^Environment=SCANNER_SPEAK=0$', quiet_unit, re.M) is not None)
ok_('...while still starting the server', 'server.js' in quiet_unit)

# Flags for the scanner reach it through the server.
os.remove(unit_path)
flagged = subprocess.run(
    ['bash', run_me],
    env=dict(os.environ, PATH=stub + os.pathsep + os.environ.get('PATH', ''),
             SUDO_USER='driver', SPEAK='1', ARGS='--keep-scans --no-track'),
    capture_output=True, text=True, timeout=60)
eq('ARGS installs too', flagged.returncode, 0)
flagged_unit = open(unit_path).read() if os.path.exists(unit_path) else ''
# Quoted, and this is the whole of it. systemd reads Environment= as a
# space-separated list of assignments, so an unquoted value is cut at its first
# space: `ARGS="--keep-scans --screen-fps 6"` installed SCANNER_ARGS=--keep-scans
# and dropped the rest with a warning in a log nobody reads. A flag that takes a
# value then reaches the scanner without it, the scanner exits, and the unit
# restarts for ever — from a line that looked like it had worked.
ok_('...and carries the flags to the scanner, whole',
    re.search(r'^Environment="SCANNER_ARGS=--keep-scans --no-track"$',
              flagged_unit, re.M) is not None)
ok_('...which the server hands to the autopilot',
    'args.concat(extra)' in server)

# ...including one that takes a value, which is the shape that bricks a rig.
os.remove(unit_path)
valued = subprocess.run(
    ['bash', run_me],
    env=dict(os.environ, PATH=stub + os.pathsep + os.environ.get('PATH', ''),
             SUDO_USER='driver', SPEAK='0', ARGS='--screen-fps 6'),
    capture_output=True, text=True, timeout=60)
eq('a flag with a value installs', valued.returncode, 0)
valued_unit = open(unit_path).read() if os.path.exists(unit_path) else ''
ok_('...with its value still attached to it',
    re.search(r'^Environment="SCANNER_ARGS=--screen-fps 6"$', valued_unit, re.M)
    is not None)
# The value must not be sitting on a line of its own, which is what an
# unquoted assignment leaves behind and what systemd would read as a second
# variable name.
ok_('...and not left stranded as an assignment of its own',
    '\nEnvironment=SCANNER_ARGS=--screen-fps 6\n' not in valued_unit)

# Every flag the README tells the driver to put here has to be one the scanner
# will actually accept. An unknown flag is not a warning: argparse exits, and
# the unit restarts on failure, so a documented flag that the scanner has never
# heard of installs a rig that loops for ever instead of reading offers.
scanner_src = open(os.path.join(ROOT, 'rpi', 'scan_pi.py')).read()
autopilot_src = open(os.path.join(ROOT, 'rpi', 'autopilot.py')).read()
ok_('the autopilot passes flags it does not know on to the scanner',
    'parse_known_args' in autopilot_src and 'extra' in autopilot_src)
for flag in ('--keep-scans', '--no-track', '--screen-fps'):
    ok_('...and the scanner accepts %s, which the README offers' % flag,
        "'%s'" % flag in scanner_src)

# --- and it actually asked systemd to do something ------------------------
log = os.path.join(work, 'systemctl.log')
did = open(log).read() if os.path.exists(log) else ''
for wanted in ('daemon-reload', 'enable uberscan.service', 'restart uberscan.service'):
    ok_('the installer runs: systemctl %s' % wanted, wanted in did)

shutil.rmtree(work, ignore_errors=True)

# --- the OTHER installer, which had no check at all -------------------------
#
# tools/install-sync.sh writes the unit that copies the offers out of the car.
# install-service.sh next door carries nine lines about quoting Environment=,
# and this one wrote the token unquoted - so systemd read it as a
# space-separated list of assignments and threw the tail away. A passphrase
# with a space in it, which the installer had just proved works by using it to
# reach the copy, was dropped into a log nobody reads; the far end then
# answered 403 to every run and the backup stopped, with an installed timer and
# a success message.
#
# Asked of systemd itself rather than of a regex, because the rule being
# checked is systemd's.
SYNC_SCRIPT = os.path.join(ROOT, 'tools', 'install-sync.sh')
sync_work = tempfile.mkdtemp()
sync_stub = os.path.join(sync_work, 'bin')
os.makedirs(sync_stub)
for _name, _body in (
    ('id', '#!/bin/sh\necho 0\n'),
    # Drops the `-u <user>` the installer passes and runs the rest as-is.
    ('sudo', '#!/bin/sh\nwhile [ "$1" = "-u" ]; do shift 2; done\nexec "$@"\n'),
    ('systemctl', '#!/bin/sh\necho "$@" >> "%s/systemctl.log"\n' % sync_work),
    # The installer refuses to write a unit until the copy answers. Nothing is
    # being tested about that here, so it is made to answer.
    ('curl', '#!/bin/sh\nexit 0\n'),
):
    _p = os.path.join(sync_stub, _name)
    open(_p, 'w').write(_body)
    os.chmod(_p, 0o755)

sync_units = os.path.join(sync_work, 'units')
os.makedirs(sync_units)
sync_src = open(SYNC_SCRIPT).read()
eq('the sync installer writes exactly one service unit',
   sync_src.count('/etc/systemd/system/uberscan-sync.service'), 1)
patched_sync = (sync_src
                .replace('/etc/systemd/system/uberscan-sync.service',
                         os.path.join(sync_units, 'uberscan-sync.service'))
                .replace('/etc/systemd/system/uberscan-sync.timer',
                         os.path.join(sync_units, 'uberscan-sync.timer'))
                # The reachability gate runs real python against a real URL.
                .replace("sys.exit(0 if isinstance(sync.far_end('$SYNC_TO'), dict) else 1)",
                         'sys.exit(0)'))
sync_project = os.path.join(sync_work, 'project')
os.makedirs(os.path.join(sync_project, 'tools'))
# The installer derives every path from its own location and refuses to write a
# unit for a checkout with no sync in it — which is the right refusal and means
# the stand-in needs one.
os.makedirs(os.path.join(sync_project, 'rpi'))
open(os.path.join(sync_project, 'rpi', 'sync.py'), 'w').write('# stand-in\n')
sync_run = os.path.join(sync_project, 'tools', 'install-sync.sh')
open(sync_run, 'w').write(patched_sync)

# A token with a space in it, which is what a passphrase looks like.
TOKEN = 'two words'
sync_proc = subprocess.run(
    ['bash', sync_run, 'https://nuc.example.net', TOKEN],
    env=dict(os.environ, PATH=sync_stub + os.pathsep + os.environ.get('PATH', '')),
    capture_output=True, text=True, timeout=120)
sync_unit_path = os.path.join(sync_units, 'uberscan-sync.service')
ok_('the sync installer runs and leaves a unit (%r)' % sync_proc.stderr[-90:],
    os.path.exists(sync_unit_path))
sync_unit = open(sync_unit_path).read() if os.path.exists(sync_unit_path) else ''

if sync_unit:
    ok_('...with the token in it', TOKEN in sync_unit)
    # The property, not the spelling: systemd must end up with the whole token.
    ok_('...as ONE assignment, not two words',
        'Environment="SYNC_TOKEN=%s"' % TOKEN in sync_unit)
    ok_('...and the address quoted the same way',
        'Environment="SYNC_TO=https://nuc.example.net"' in sync_unit)
    if shutil.which('systemd-analyze'):
        verdict = subprocess.run(['systemd-analyze', 'verify', sync_unit_path],
                                 capture_output=True, text=True, timeout=60)
        said = verdict.stdout + verdict.stderr
        # systemd's own words for the defect: "Invalid environment assignment,
        # ignoring: words".
        ok_('...and systemd itself keeps the assignment whole (%r)'
            % said.strip()[:80],
            'Invalid environment assignment' not in said)
    else:
        # Said out loud rather than passed quietly: a check that did not run is
        # not a check that passed.
        print('  (no systemd-analyze here, so systemd was not asked directly)')

    # A percent sign is a systemd specifier even inside quotes, so it has to be
    # doubled on the way in. Checked separately because quoting alone does not
    # fix it.
    pct_units = os.path.join(sync_work, 'pct')
    os.makedirs(pct_units)
    pct_run = os.path.join(sync_project, 'tools', 'pct.sh')
    open(pct_run, 'w').write(patched_sync.replace(sync_units, pct_units))
    subprocess.run(['bash', pct_run, 'https://nuc.example.net', 'pc%25'],
                   env=dict(os.environ,
                            PATH=sync_stub + os.pathsep + os.environ.get('PATH', '')),
                   capture_output=True, text=True, timeout=120)
    pct_path = os.path.join(pct_units, 'uberscan-sync.service')
    if os.path.exists(pct_path):
        ok_('a percent in the token is doubled, since systemd expands it',
            'SYNC_TOKEN=pc%%25' in open(pct_path).read())

shutil.rmtree(sync_work, ignore_errors=True)

# --- and the same installer on the machine that keeps the copy --------------
#
# That machine holds the only off-car copy of the one artefact this project
# calls irreplaceable, and it was documented as a command typed into a
# terminal — "that is the whole install" — so the backup ended whenever the
# machine rebooted. Nothing says so: far_end() returns None on a refused
# connection and sync.py exits 0, deliberately, because a car is offline most
# of the time. A backup that has stopped looks exactly like being out of range.
#
# One script and one unit template for both ends, because two would drift.
# Three lines differ, and each is checked here in BOTH directions — the copy
# needs SCANNER=0 or it restart-loops on the missing picamera2, and the rig
# must not get it or the rig stops scanning.
copy_work = tempfile.mkdtemp()
try:
    copy_units = os.path.join(copy_work, 'units')
    copy_stub = os.path.join(copy_work, 'bin')
    os.makedirs(copy_units)
    os.makedirs(copy_stub)
    # The same shadowing the rig's run above uses: pretend to be root, record
    # what would have been done to the system and do none of it. The heredoc
    # that composes the unit is the shipped code either way.
    for _name, _body in (
        ('id', '#!/bin/sh\necho 0\n'),
        ('systemctl', '#!/bin/sh\nexit 0\n'),
        ('logname', '#!/bin/sh\necho %s\n' % getpass.getuser()),
    ):
        _p = os.path.join(copy_stub, _name)
        with open(_p, 'w') as fh:
            fh.write(_body)
        os.chmod(_p, 0o755)
    copy_project = os.path.join(copy_work, 'project')
    os.makedirs(os.path.join(copy_project, 'rpi'))
    copy_script = os.path.join(copy_project, 'rpi', 'install-service.sh')
    with open(copy_script, 'w') as fh:
        fh.write(open(SCRIPT).read().replace(
            '/etc/systemd/system/uberscan.service',
            os.path.join(copy_units, 'uberscan.service')))
    copy_journal = os.path.join(copy_work, 'var', 'uberscan', 'journal.jsonl')
    cp = subprocess.run(
        ['bash', copy_script],
        env=dict(os.environ,
                 PATH=copy_stub + os.pathsep + os.environ.get('PATH', ''),
                 SUDO_USER=getpass.getuser(), COPY=copy_journal),
        capture_output=True, text=True, timeout=60)
    eq('the installer runs cleanly on the copy machine', cp.returncode, 0)
    if cp.returncode != 0:
        print(cp.stdout[-600:])
        print(cp.stderr[-600:])
    copy_unit_path = os.path.join(copy_units, 'uberscan.service')
    ok_('...and leaves a unit behind', os.path.exists(copy_unit_path))
    copy_unit = open(copy_unit_path).read() if os.path.exists(copy_unit_path) else ''

    # Without this the server starts the scanner, fails on the missing
    # picamera2, and the unit restarts it every few seconds for ever. It is
    # the single reason the rig's own installer could not just be reused.
    ok_('the copy is told there is no camera here',
        re.search(r'^Environment=SCANNER=0$', copy_unit, re.M) is not None)
    ok_('...and the rig is NOT, or it stops scanning',
        re.search(r'^Environment=SCANNER=0$', unit, re.M) is None)
    # Left at the default the copy lands in rpi/journal.jsonl inside the
    # clone, which works and stands the only backup next to a `git clean`.
    ok_('...and where to keep the copy, outside the checkout',
        re.search(r'^Environment=JOURNAL=' + re.escape(copy_journal) + r'$',
                  copy_unit, re.M) is not None)
    ok_('...which the rig does not set, keeping its own default',
        re.search(r'^Environment=JOURNAL=', unit, re.M) is None)
    # Speech needs the driver's audio devices. The copy machine says nothing
    # and has no camera, so the grants are dropped rather than handed to
    # something that cannot use them.
    ok_('the copy machine is granted no audio or video devices',
        'SupplementaryGroups' not in copy_unit)
    ok_('...while the rig still is, because speech needs them',
        'SupplementaryGroups=audio video' in unit)
    # The same server, which is the whole reason there is one script.
    ok_('both ends run the same server',
        '/server.js' in copy_unit and '/server.js' in unit)
    # The server can only make the directory where it is allowed to, and this
    # script is already root — the one moment in the install where it is free.
    ok_('the directory for the copy is made and handed over',
        os.path.isdir(os.path.dirname(copy_journal)))
    # A relative path would put it wherever systemd happened to start, which
    # is not a place anybody chose.
    rel = subprocess.run(
        ['bash', copy_script],
        env=dict(os.environ,
                 PATH=copy_stub + os.pathsep + os.environ.get('PATH', ''),
                 SUDO_USER=getpass.getuser(), COPY='journal.jsonl'),
        capture_output=True, text=True, timeout=60)
    ok_('a relative path for the copy is refused rather than guessed at',
        rel.returncode != 0 and 'absolute path' in (rel.stderr or ''))
finally:
    shutil.rmtree(copy_work, ignore_errors=True)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d service checks passed' % ok)
sys.exit(1 if bad else 0)
