"""Small contract checks for which installed machine owns the camera.

The full installer behavior lives in test_service.py.  These checks exist for
one easy-to-miss invariant: the rig and the copy machine must state opposite
scanner roles in the systemd unit instead of relying on server.js to infer a
machine's role from the contents of its checkout.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALLER = os.path.join(ROOT, 'rpi', 'install-service.sh')
SERVER = os.path.join(ROOT, 'server.js')

ok = bad = 0


def check(name, condition):
    global ok, bad
    if condition:
        ok += 1
    else:
        bad += 1
        print('FAIL  ' + name)


installer = open(INSTALLER, encoding='utf-8').read()
server = open(SERVER, encoding='utf-8').read()

copy_contract = 'UNIT_ENV="Environment=SCANNER=0\nEnvironment=JOURNAL=$COPY"'
rig_contract = ('UNIT_ENV="Environment=SCANNER=1\n'
                'Environment=SCANNER_SPEAK=$SPEAK\n'
                'Environment=\\"SCANNER_ARGS=$ARGS\\""')

check('the copy-machine service explicitly disables the scanner',
      copy_contract in installer)
check('the rig service explicitly enables the scanner',
      rig_contract in installer)
check('the two roles are each emitted exactly once',
      installer.count('Environment=SCANNER=0') == 1 and
      installer.count('Environment=SCANNER=1') == 1)

# This makes the service declarations meaningful: SCANNER=0 is the server's
# explicit off switch, while every other value (including the rig's 1) follows
# the existing scanner path.  If server.js later changes this contract, this
# test points at the installer/server boundary rather than letting the rig's
# boot behavior change accidentally.
check('server.js still honors the explicit scanner off switch',
      "process.env.SCANNER === '0'" in server)

print('%d passed%s' % (ok, '' if bad == 0 else ', %d FAILED' % bad))
sys.exit(1 if bad else 0)
