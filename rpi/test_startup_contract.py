"""Focused integration checks for the installed server roles.

    python3 rpi/test_startup_contract.py

The larger service suite checks the installer broadly.  This file protects the
boundary added when the two machines stopped relying on server.js to guess
their roles: the Pi must explicitly enable its scanner, the copy machine must
explicitly disable it, and an optional sync token must survive shell + systemd
escaping without being printed back to the operator.

The real installer is executed after redirecting only its /etc output and
shadowing commands that would mutate the machine.  No real service is touched.
"""

import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, 'rpi', 'install-service.sh')

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


def no(name, value):
    eq(name, bool(value), False)


if shutil.which('bash') is None or shutil.which('node') is None:
    print('bash or node is unavailable — skipping startup-contract checks')
    sys.exit(0)

work = tempfile.mkdtemp()
try:
    stub = os.path.join(work, 'bin')
    os.makedirs(stub)

    # Pretend to be root, but make every machine-changing command a no-op.
    stubs = {
        'id': '#!/bin/sh\necho 0\n',
        'systemctl': '#!/bin/sh\nexit 0\n',
        'logname': '#!/bin/sh\necho driver\n',
        'chown': '#!/bin/sh\nexit 0\n',
    }
    for name, body in stubs.items():
        path = os.path.join(stub, name)
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(body)
        os.chmod(path, 0o755)

    project = os.path.join(work, 'project')
    os.makedirs(os.path.join(project, 'rpi'))
    unit = os.path.join(work, 'uberscan.service')

    source = open(SOURCE, encoding='utf-8').read()
    eq('the installer has one service destination to redirect',
       source.count('/etc/systemd/system/uberscan.service'), 1)
    patched = source.replace('/etc/systemd/system/uberscan.service', unit)
    installer = os.path.join(project, 'rpi', 'install-service.sh')
    with open(installer, 'w', encoding='utf-8') as fh:
        fh.write(patched)

    base_env = dict(os.environ)
    base_env.update({
        'PATH': stub + os.pathsep + os.environ.get('PATH', ''),
        'SUDO_USER': 'driver',
    })

    def run(extra=None):
        env = dict(base_env)
        env.update(extra or {})
        return subprocess.run(
            ['bash', installer], env=env, capture_output=True,
            text=True, timeout=60)

    # The camera rig says what it is instead of relying on the repository
    # containing autopilot.py.  That keeps future server startup changes from
    # silently changing what a rebooted rig does.
    rig = run({'SPEAK': '0'})
    eq('the rig installer succeeds', rig.returncode, 0)
    rig_unit = open(unit, encoding='utf-8').read() if os.path.exists(unit) else ''
    yes('the rig service explicitly enables the scanner',
        '\nEnvironment=SCANNER=1\n' in rig_unit)
    no('the rig service does not carry the copy-machine off switch',
       '\nEnvironment=SCANNER=0\n' in rig_unit)
    yes('the rig still starts the web server rather than the scanner directly',
        'ExecStart=' in rig_unit and 'server.js' in rig_unit and
        'autopilot.py' not in [line for line in rig_unit.splitlines()
                               if line.startswith('ExecStart=')][0])

    # The receiving machine says the opposite and can require the same token
    # tools/install-sync.sh passes from the car.  Use every character that has
    # broken Environment= assignments before: spaces, %, quotes and backslash.
    copy_path = os.path.join(work, 'copy', 'journal.jsonl')
    token = 'two words pc%25 "quoted" slash\\end'
    copy = run({'COPY': copy_path, 'SYNC_TOKEN': token})
    eq('the authenticated copy installer succeeds', copy.returncode, 0)
    copy_unit = open(unit, encoding='utf-8').read() if os.path.exists(unit) else ''
    yes('the copy service explicitly disables the scanner',
        '\nEnvironment=SCANNER=0\n' in copy_unit)
    no('the copy service never enables the camera',
       '\nEnvironment=SCANNER=1\n' in copy_unit)
    yes('the copy service keeps the journal outside the checkout',
        'Environment=JOURNAL=' + copy_path in copy_unit)

    escaped = token.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')
    wanted = 'Environment="SYNC_TOKEN=%s"' % escaped
    yes('the complete sync token is written as one quoted systemd assignment',
        wanted in copy_unit)
    no('the real sync token is never echoed after installation',
       token in copy.stdout or token in copy.stderr)
    yes('the operator is told to reuse the token without printing it',
        "'<same-token>'" in copy.stdout)

    # Authentication is optional for backward compatibility.  A copy service
    # installed without it must not receive an empty token variable whose
    # presence could be mistaken for protection.
    plain = run({'COPY': copy_path, 'SYNC_TOKEN': ''})
    eq('an unauthenticated copy install remains supported', plain.returncode, 0)
    plain_unit = open(unit, encoding='utf-8').read() if os.path.exists(unit) else ''
    no('an omitted token is omitted from the unit', 'Environment="SYNC_TOKEN=' in plain_unit)

    # A newline cannot live in one systemd Environment= assignment.  Refuse it
    # rather than producing a second line that systemd could interpret as a new
    # directive.
    if os.path.exists(unit):
        os.remove(unit)
    multiline = run({'COPY': copy_path, 'SYNC_TOKEN': 'first\nsecond'})
    yes('a multiline sync token is rejected', multiline.returncode != 0)
    no('a rejected token leaves no replacement service behind', os.path.exists(unit))
    yes('the rejection names the token problem',
        'SYNC_TOKEN may not contain a newline' in multiline.stderr)

finally:
    shutil.rmtree(work, ignore_errors=True)

print('%d passed%s' % (ok, '' if bad == 0 else ', %d FAILED' % bad))
sys.exit(1 if bad else 0)
