"""Contract checks for tools/install-sync.sh without touching systemd.

    python3 tools/test_install_sync.py

The real installer is copied into a temporary checkout with only its two /etc
output paths redirected.  sudo, python3 and systemctl are harmless stubs; tee is
the real tee writing only those temporary files.  This exercises the shell
quoting that matters instead of merely looking for source strings.
"""

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, 'install-sync.sh')

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


if shutil.which('bash') is None:
    print('bash is unavailable — skipping install-sync checks')
    sys.exit(0)

syntax = subprocess.run(['bash', '-n', SOURCE], capture_output=True, text=True)
eq('install-sync.sh parses as Bash', syntax.returncode, 0)

work = tempfile.mkdtemp()
try:
    project = os.path.join(work, 'project')
    tools = os.path.join(project, 'tools')
    rpi = os.path.join(project, 'rpi')
    bindir = os.path.join(work, 'bin')
    os.makedirs(tools)
    os.makedirs(rpi)
    os.makedirs(bindir)

    # The installer only requires this file to exist before handing it to the
    # Python command.  The Python command itself is shadowed below.
    with open(os.path.join(rpi, 'sync.py'), 'w', encoding='utf-8') as fh:
        fh.write('# stand-in for installer testing\n')

    unit = os.path.join(work, 'uberscan-sync.service')
    timer = os.path.join(work, 'uberscan-sync.timer')
    source = open(SOURCE, encoding='utf-8').read()
    eq('the installer has one service path to redirect',
       source.count('UNIT=/etc/systemd/system/uberscan-sync.service'), 1)
    eq('the installer has one timer path to redirect',
       source.count('TIMER=/etc/systemd/system/uberscan-sync.timer'), 1)
    source = source.replace('UNIT=/etc/systemd/system/uberscan-sync.service',
                            'UNIT=' + unit)
    source = source.replace('TIMER=/etc/systemd/system/uberscan-sync.timer',
                            'TIMER=' + timer)
    installer = os.path.join(tools, 'install-sync.sh')
    with open(installer, 'w', encoding='utf-8') as fh:
        fh.write(source)

    # python3 answers both installer probes successfully.  Logging argv lets
    # the test prove a token with spaces is still one value when the one-off
    # sync is tried, and that the preflight's URL is argv rather than Python
    # source.
    python_stub = os.path.join(bindir, 'python3')
    with open(python_stub, 'w', encoding='utf-8') as fh:
        fh.write('#!/bin/sh\n'
                 'printf "python3" >> "$CALL_LOG"\n'
                 'for x in "$@"; do printf " <%s>" "$x" >> "$CALL_LOG"; done\n'
                 'printf "\\n" >> "$CALL_LOG"\n'
                 'exit 0\n')
    os.chmod(python_stub, 0o755)

    systemctl_stub = os.path.join(bindir, 'systemctl')
    with open(systemctl_stub, 'w', encoding='utf-8') as fh:
        fh.write('#!/bin/sh\nexit 0\n')
    os.chmod(systemctl_stub, 0o755)

    # Minimal sudo: -u USER drops those two words, while `sudo tee` and
    # `sudo systemctl` simply exec the command found on PATH. Nothing here has
    # elevated privileges.
    sudo_stub = os.path.join(bindir, 'sudo')
    with open(sudo_stub, 'w', encoding='utf-8') as fh:
        fh.write('#!/bin/sh\n'
                 'if [ "${1:-}" = "-u" ]; then shift 2; fi\n'
                 'exec "$@"\n')
    os.chmod(sudo_stub, 0o755)

    call_log = os.path.join(work, 'calls.log')
    base_env = dict(os.environ)
    base_env['PATH'] = bindir + os.pathsep + base_env.get('PATH', '')
    base_env['CALL_LOG'] = call_log

    def run(args, token_marker=None):
        env = dict(base_env)
        if token_marker is None:
            env.pop('SYNC_TOKEN', None)
        else:
            env['SYNC_TOKEN'] = token_marker
        open(call_log, 'w').close()
        return subprocess.run(['bash', installer] + args, env=env,
                              capture_output=True, text=True, timeout=30)

    def unit_text():
        return open(unit, encoding='utf-8').read() if os.path.exists(unit) else ''

    # Environment input is the preferred authenticated form. Use the characters
    # that have broken systemd Environment= assignments before. The apostrophe
    # in the URL is also deliberate: the old reachability probe interpolated
    # this value into single-quoted Python source.
    url = "https://nuc.example.net/sync%20path?label=O'Reilly"
    token = 'two words pc%25 "quoted" slash\\end'
    result = run([url], token)
    eq('environment-token install succeeds', result.returncode, 0)
    u = unit_text()
    escaped_token = token.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')
    escaped_url = url.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')
    yes('the URL is one escaped systemd environment assignment',
        'Environment="SYNC_TO=%s"' % escaped_url in u)
    yes('the token is one escaped systemd environment assignment',
        'Environment="SYNC_TOKEN=%s"' % escaped_token in u)
    no('the real token is never printed by the installer',
       token in result.stdout or token in result.stderr)
    calls = open(call_log, encoding='utf-8').read()
    yes('the reachability probe reads its destination from argv',
        'sync.far_end(sys.argv[2])' in calls)
    no('the reachability probe does not splice the destination into Python source',
       "sync.far_end('%s')" % url in calls)
    yes('the one-off sync receives --token', '<--token>' in calls)
    yes('the complete token remains one argv value', '<%s>' % token in calls)
    yes('the timer unit is generated too', os.path.exists(timer))

    # Compatibility: a positional token still works, and if both forms are
    # supplied it is the explicitly supplied value that wins.
    positional = 'positional value %42 "q" \\x'
    result = run([url, positional], 'environment value that must lose')
    eq('legacy positional-token install succeeds', result.returncode, 0)
    u = unit_text()
    escaped_pos = positional.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')
    yes('positional token takes precedence over environment input',
        'Environment="SYNC_TOKEN=%s"' % escaped_pos in u)
    no('the losing environment token is not stored',
       'environment value that must lose' in u)

    # Backward-compatible unauthenticated install: no empty token variable is
    # written that could be mistaken for protection.
    result = run([url])
    eq('tokenless install remains supported', result.returncode, 0)
    no('tokenless unit omits SYNC_TOKEN', 'Environment="SYNC_TOKEN=' in unit_text())

    # Newlines cannot live safely in one Environment= directive. They are
    # refused before the reachability probe, not after network/Python use.
    if os.path.exists(unit):
        os.remove(unit)
    if os.path.exists(timer):
        os.remove(timer)
    result = run([url], 'first\nsecond')
    yes('multiline token is rejected', result.returncode != 0)
    yes('multiline-token error names the problem',
        'SYNC_TOKEN may not contain a newline' in result.stderr)
    no('rejected multiline token writes no service unit', os.path.exists(unit))
    no('rejected multiline token writes no timer unit', os.path.exists(timer))
    eq('multiline token is rejected before Python/network use',
       open(call_log, encoding='utf-8').read(), '')

    # Same for the URL: putting a newline into the destination must not create
    # an extra unit directive or reach the Python probe.
    result = run(['https://nuc.example.net/first\nsecond'])
    yes('multiline URL is rejected', result.returncode != 0)
    yes('multiline-URL error names the problem',
        'sync URL may not contain a newline' in result.stderr)
    no('rejected multiline URL writes no service unit', os.path.exists(unit))
    eq('multiline URL is rejected before Python/network use',
       open(call_log, encoding='utf-8').read(), '')

    too_many = run([url, 'one', 'two'])
    eq('more than URL + token is refused', too_many.returncode, 2)

finally:
    shutil.rmtree(work, ignore_errors=True)

print('%d passed%s' % (ok, '' if bad == 0 else ', %d FAILED' % bad))
sys.exit(1 if bad else 0)
