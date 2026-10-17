#!/usr/bin/env python3
"""Read-only capability probe for the phone-touch experiment.

It does not pair devices or change Bluetooth/input configuration.  Run it on the
Pi to collect the facts needed for the HID implementation.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess


def command(*args: str) -> str:
    try:
        p = subprocess.run(args, text=True, capture_output=True, timeout=5,
                           check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f'ERROR: {exc}'
    text = (p.stdout or '') + (p.stderr or '')
    return text.strip() or f'(exit {p.returncode}, no output)'


def main() -> None:
    print('Phone touch-control capability probe')
    print('====================================')
    print('\nInput event nodes:')
    nodes = sorted(glob.glob('/dev/input/event*'))
    if nodes:
        for path in nodes:
            print(f'  {path}  readable={os.access(path, os.R_OK)}')
    else:
        print('  none found')

    print('\nInput devices:')
    try:
        with open('/proc/bus/input/devices', encoding='utf-8') as fh:
            print(fh.read().strip())
    except OSError as exc:
        print(f'ERROR: {exc}')

    print('\nBluetooth tools:')
    for tool in ('bluetoothctl', 'btmgmt', 'hciconfig'):
        print(f'  {tool}: {shutil.which(tool) or "not installed"}')

    if shutil.which('bluetoothctl'):
        print('\nBluetooth adapter:')
        print(command('bluetoothctl', 'show'))
        print('\nKnown Bluetooth devices:')
        print(command('bluetoothctl', 'devices'))

    print('\nKernel HID support hints:')
    print(command('sh', '-c',
                  "lsmod | grep -E '(^|_)(hid|uhid|bluetooth|btusb)' || true"))
    print(f'\n/dev/uhid present: {os.path.exists("/dev/uhid")}')


if __name__ == '__main__':
    main()
