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

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d service checks passed' % ok)
sys.exit(1 if bad else 0)
