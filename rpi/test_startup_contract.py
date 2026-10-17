"""Small contract checks for installed scanner and sync roles.

The full installer behavior lives in test_service.py.  These checks exist for
two easy-to-miss invariants: the rig and the copy machine must state opposite
scanner roles, and optional sync authentication must survive into the copy
machine's systemd environment instead of existing only on the sending side.
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

copy_contract = ('UNIT_ENV="Environment=SCANNER=0\n'
                 'Environment=JOURNAL=$COPY\n'
                 '$TOKEN_ENV"')
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
# the existing scanner path. If server.js later changes this contract, this
# test points at the installer/server boundary rather than letting the rig's
# boot behavior change accidentally.
check('server.js still honors the explicit scanner off switch',
      "process.env.SCANNER === '0'" in server)

# The sender already knows how to pass a token. The receiving installer must
# persist the same server-side variable or a reboot silently removes the
# protection. Percent, quote and backslash handling are all systemd-specific
# failure modes, so keep the escaping itself under the contract too.
check('the copy installer accepts the server-side sync token',
      'SYNC_TOKEN="${SYNC_TOKEN:-}"' in installer)
check('the copy service writes SYNC_TOKEN into systemd when supplied',
      'TOKEN_ENV="Environment=\\"SYNC_TOKEN=$SYSTEMD_TOKEN\\""' in installer)
check('the token is escaped for systemd percent specifiers',
      'SYSTEMD_TOKEN="${SYSTEMD_TOKEN//%/%%}"' in installer)
check('the token is escaped for quoted systemd assignments',
      'SYSTEMD_TOKEN="${SYNC_TOKEN//\\\\/\\\\\\\\}"' in installer and
      'SYSTEMD_TOKEN="${SYSTEMD_TOKEN//\\"/\\\\\\"}"' in installer)

print('%d passed%s' % (ok, '' if bad == 0 else ', %d FAILED' % bad))
sys.exit(1 if bad else 0)
