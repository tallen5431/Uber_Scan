"""The two installers in this lane, run from a checkout whose path has a space.

    python3 tools/test_installers.py

tools/install-sync.sh and lite/install.sh wrote the checkout's path bare into
the lines that start things: the sync unit's ExecStart= and ReadWritePaths=,
and lite's kiosk command, which goes into the labwc autostart (a shell line),
the desktop entry's Exec= (the XDG spec's quoting) and cage's unit's ExecStart=
(systemd's). Each reader splits at spaces, so a checkout under "Uber Scan" ran
python and bash on ".../Uber" and nothing said so: the sync timer failed every
run and the card never opened. rpi/test_service.py runs install-sync.sh for
its token; this runs both for the path. Each script is run as shipped, from a
stand-in checkout, with id, sudo, systemctl and the rest shadowed and /etc
pointed into a temp dir, test_service.py's own way, so nothing here touches
the machine. Asked of systemd itself where systemd-analyze is here.
"""

import os
import shlex
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


def stubs(directory, extra=()):
    os.makedirs(directory)
    for name, body in (('id', '#!/bin/sh\necho 0\n'),
                       ('sudo', '#!/bin/sh\nwhile [ "$1" = "-u" ]; do shift 2; done\nexec "$@"\n'),
                       ('systemctl', '#!/bin/sh\nexit 0\n'),
                       ('curl', '#!/bin/sh\nexit 0\n'),
                       ('chown', '#!/bin/sh\nexit 0\n'),
                       ('usermod', '#!/bin/sh\nexit 0\n'),
                       ('logname', '#!/bin/sh\necho driver\n')) + tuple(extra):
        path = os.path.join(directory, name)
        with open(path, 'w') as fh:
            fh.write(body)
        os.chmod(path, 0o755)


def value(unit, key):
    """The value of the first `key=` line of a unit or desktop entry, or None."""
    for line in unit.splitlines():
        if line.startswith(key + '='):
            return line[len(key) + 1:]
    return None


def verify(path):
    """What systemd-analyze verify says of a unit, or None with none here."""
    if not shutil.which('systemd-analyze'):
        return None
    got = subprocess.run(['systemd-analyze', 'verify', path], capture_output=True, text=True,
                         timeout=60)
    return got.stdout + got.stderr


work = tempfile.mkdtemp()
try:
    # --- tools/install-sync.sh ---------------------------------------------------
    project = os.path.join(work, 'Uber Scan')
    os.makedirs(os.path.join(project, 'tools'))
    os.makedirs(os.path.join(project, 'rpi'))
    with open(os.path.join(project, 'rpi', 'sync.py'), 'w') as fh:
        fh.write('# stand-in\n')
    units = os.path.join(work, 'units')
    os.makedirs(units)
    with open(os.path.join(ROOT, 'tools', 'install-sync.sh')) as fh:
        src = fh.read()
    src = (src.replace('/etc/systemd/system/uberscan-sync.service',
                       os.path.join(units, 'uberscan-sync.service'))
           .replace('/etc/systemd/system/uberscan-sync.timer',
                    os.path.join(units, 'uberscan-sync.timer'))
           .replace("sys.exit(0 if isinstance(sync.far_end('$SYNC_TO'), dict) else 1)",
                    'sys.exit(0)'))
    script = os.path.join(project, 'tools', 'install-sync.sh')
    with open(script, 'w') as fh:
        fh.write(src)
    stubs(os.path.join(work, 'bin'))
    env = dict(os.environ, PATH=os.path.join(work, 'bin') + os.pathsep + os.environ.get('PATH', ''))
    got = subprocess.run(['bash', script, 'https://nuc.example.net', 'invented-token'], env=env,
                         capture_output=True, text=True, timeout=120)
    unit_path = os.path.join(units, 'uberscan-sync.service')
    ok_('[sync] the installer runs from a checkout with a space in its path (%r)'
        % got.stderr[-120:], os.path.exists(unit_path))
    unit = open(unit_path).read() if os.path.exists(unit_path) else ''
    exec_start = shlex.split(value(unit, 'ExecStart') or '')
    eq('[sync] ExecStart= hands python the whole path to sync.py, as one word',
       exec_start[1:], [os.path.join(project, 'rpi', 'sync.py'), '--quiet'])
    eq('[sync] ...and ReadWritePaths= is the whole rpi directory',
       shlex.split(value(unit, 'ReadWritePaths') or ''), [os.path.join(project, 'rpi')])
    said = verify(unit_path) if unit else None
    if said is None:
        print('  (no systemd-analyze here, so systemd was not asked directly)')
    else:
        # systemd's words for the bare path: "ReadWritePaths= path is not
        # absolute, ignoring: Scan/rpi".
        eq('[sync] ...and systemd-analyze verify finds nothing split off the path',
           [ln for ln in said.splitlines() if 'Scan' in ln or 'not absolute' in ln], [])

    # --- lite/install.sh -----------------------------------------------------------
    lite = os.path.join(work, 'Lite Rig')
    os.makedirs(os.path.join(lite, 'lite'))
    os.makedirs(os.path.join(lite, 'rpi'))
    with open(os.path.join(lite, 'rpi', 'install-service.sh'), 'w') as fh:
        fh.write('# stand-in: the service is not what is asked here\n')
    with open(os.path.join(lite, 'lite', 'kiosk.sh'), 'w') as fh:
        fh.write('# stand-in\n')
    home = os.path.join(work, 'home', 'driver')
    os.makedirs(home)
    kunits = os.path.join(work, 'kunits')
    os.makedirs(kunits)
    with open(os.path.join(ROOT, 'lite', 'install.sh')) as fh:
        lsrc = fh.read().replace('/etc/systemd/system/uberscan-kiosk.service',
                                 os.path.join(kunits, 'uberscan-kiosk.service'))
    lscript = os.path.join(lite, 'lite', 'install.sh')
    with open(lscript, 'w') as fh:
        fh.write(lsrc)
    stubs(os.path.join(work, 'lbin'),
          (('getent', '#!/bin/sh\necho "driver:x:1000:1000::%s:/bin/bash"\n' % home),))
    lenv = dict(os.environ, APT='0', SUDO_USER='driver',
                PATH=os.path.join(work, 'lbin') + os.pathsep + os.environ.get('PATH', ''))
    kiosk = os.path.join(lite, 'lite', 'kiosk.sh')
    def install(mode):
        got = subprocess.run(['bash', lscript], env=dict(lenv, KIOSK=mode), capture_output=True,
                             text=True, timeout=120)
        eq('[lite] KIOSK=%s installs from a checkout with a space in its path (%r)'
           % (mode, got.stderr[-120:]), got.returncode, 0)

    # The desktop run first: the cage run after it takes the desktop entry away,
    # as a desktop run takes cage's unit away.
    install('desktop')
    autostart = os.path.join(home, '.config', 'labwc', 'autostart')
    line = open(autostart).read() if os.path.exists(autostart) else ''
    eq('[lite] the labwc autostart runs bash on the whole kiosk path, read as its shell reads it',
       shlex.split(line, comments=True), ['bash', kiosk, '&'])
    entry_path = os.path.join(home, '.config', 'autostart', 'uberscan-lite.desktop')
    entry = open(entry_path).read() if os.path.exists(entry_path) else ''
    eq('[lite] ...the desktop entry\'s Exec= the same, by the XDG spec\'s double quotes',
       shlex.split(value(entry, 'Exec') or ''), ['bash', kiosk])
    install('cage')
    kunit_path = os.path.join(kunits, 'uberscan-kiosk.service')
    kunit = open(kunit_path).read() if os.path.exists(kunit_path) else ''
    eq('[lite] ...and cage\'s unit\'s ExecStart= the same',
       shlex.split(value(kunit, 'ExecStart') or ''), ['/usr/bin/cage', '-s', '--', 'bash', kiosk])
    said = verify(kunit_path) if kunit else None
    if said is not None:
        eq('[lite] ...and systemd-analyze verify finds nothing split off the path',
           [ln for ln in said.splitlines() if 'Rig' in ln], [])
finally:
    shutil.rmtree(work, ignore_errors=True)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d installer checks passed' % ok)
sys.exit(1 if bad else 0)
