"""Contract checks for the Raspberry Pi dependency installer.

These never install anything.  The installer is run with sudo/python/apt/node
shadowed by harmless stubs so CI can verify the argv it would use on a Pi.
"""

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
INSTALL = os.path.join(HERE, 'install-deps.sh')
CORE = os.path.join(HERE, 'apt-packages.txt')
GPS = os.path.join(HERE, 'apt-packages-gps.txt')
SNAP = os.path.join(HERE, 'apt-packages-snap.txt')
PIP = os.path.join(HERE, 'requirements.txt')

ok = bad = 0


def eq(name, got, want):
    global ok, bad
    if got == want:
        ok += 1
    else:
        bad += 1
        print('FAIL  %s: got %r want %r' % (name, got, want))


def yes(name, value):
    eq(name, bool(value), True)


def packages(path):
    out = []
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            line = line.split('#', 1)[0].strip()
            if line:
                out.append(line)
    return out


# The scanner's own dependency check in autopilot.py names these fixes.  Keep
# the machine-readable manifests at least as complete as that executable check.
core = packages(CORE)
eq('core apt packages are unique', len(core), len(set(core)))
for package in ('python3-picamera2', 'python3-opencv', 'python3-numpy',
                'python3-pip', 'tesseract-ocr', 'espeak-ng'):
    yes('core manifest contains ' + package, package in core)

gps = packages(GPS)
eq('GPS package group', gps, ['gpsd', 'gpsd-clients'])
snap = packages(SNAP)
eq('Snap package group', snap, ['grim', 'scrot'])

pip_text = open(PIP, encoding='utf-8').read()
yes('pytesseract is the Pi pip dependency', 'pytesseract' in pip_text)
for forbidden in ('opencv-python', 'numpy', 'picamera2'):
    eq('hardware/system package is not installed by pip: ' + forbidden,
       forbidden in [line.split('#', 1)[0].strip().split('=')[0].split('<')[0].split('>')[0]
                     for line in pip_text.splitlines() if line.split('#', 1)[0].strip()],
       False)

syntax = subprocess.run(['bash', '-n', INSTALL], capture_output=True, text=True)
eq('install-deps.sh parses as Bash', syntax.returncode, 0)

helped = subprocess.run(['bash', INSTALL, '--help'], capture_output=True, text=True)
eq('--help succeeds without touching the machine', helped.returncode, 0)
yes('--help documents the optional groups', '--gps' in helped.stdout and '--snap' in helped.stdout)

unknown = subprocess.run(['bash', INSTALL, '--definitely-not-an-option'],
                         capture_output=True, text=True)
eq('unknown options are refused', unknown.returncode, 2)

# Exercise the install path with all mutating/external commands shadowed.  This
# proves package groups are selected as argv and that the pip manifest is handed
# to Python without actually invoking apt or pip on the CI host.
work = tempfile.mkdtemp()
try:
    bindir = os.path.join(work, 'bin')
    os.makedirs(bindir)
    log = os.path.join(work, 'calls.log')

    stubs = {
        'sudo': '#!/bin/sh\nprintf "sudo" >> "$CALL_LOG"\nprintf " <%s>" "$@" >> "$CALL_LOG"\nprintf "\\n" >> "$CALL_LOG"\nexit 0\n',
        'apt-get': '#!/bin/sh\nexit 99\n',
        'python3': '#!/bin/sh\nprintf "python3" >> "$CALL_LOG"\nprintf " <%s>" "$@" >> "$CALL_LOG"\nprintf "\\n" >> "$CALL_LOG"\nexit 0\n',
        'node': '#!/bin/sh\nif [ "$1" = "-p" ]; then echo 24; else echo v24.0.0; fi\n',
    }
    for name, body in stubs.items():
        p = os.path.join(bindir, name)
        with open(p, 'w', encoding='utf-8') as fh:
            fh.write(body)
        os.chmod(p, 0o755)

    env = dict(os.environ)
    env['PATH'] = bindir + os.pathsep + env.get('PATH', '')
    env['CALL_LOG'] = log

    plain = subprocess.run(['bash', INSTALL], env=env, capture_output=True,
                           text=True, timeout=30)
    eq('core install path succeeds with harmless command stubs', plain.returncode, 0)
    plain_calls = open(log, encoding='utf-8').read()
    for package in core:
        yes('core install argv contains ' + package, '<%s>' % package in plain_calls)
    for package in gps + snap:
        eq('core install does not include optional package ' + package,
           '<%s>' % package in plain_calls, False)
    yes('pip install uses the Pi requirements file',
        'python3 <-m> <pip> <install> <--break-system-packages> <-r> <%s>' % PIP
        in plain_calls)

    open(log, 'w').close()
    all_groups = subprocess.run(['bash', INSTALL, '--all'], env=env,
                                capture_output=True, text=True, timeout=30)
    eq('--all install path succeeds with harmless command stubs', all_groups.returncode, 0)
    all_calls = open(log, encoding='utf-8').read()
    for package in core + gps + snap:
        yes('--all install argv contains ' + package, '<%s>' % package in all_calls)
    yes('--all prints a matching verification command',
        'verify with: bash rpi/install-deps.sh --check --gps --snap' in all_groups.stdout)

finally:
    shutil.rmtree(work, ignore_errors=True)

print('%d passed%s' % (ok, '' if bad == 0 else ', %d FAILED' % bad))
sys.exit(1 if bad else 0)
