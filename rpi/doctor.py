#!/usr/bin/env python3
"""Check everything the Pi scanner needs, and say exactly how to fix what is missing.

    python3 rpi/doctor.py

Worth running first on a fresh Pi. Each failure prints the command that fixes
it, so a headless setup does not turn into a guessing game.
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

results = []


def check(name, ok, detail='', fix=''):
    results.append((name, ok, detail, fix))
    print('%s  %-34s %s' % ('ok  ' if ok else 'FAIL', name, detail))
    if not ok and fix:
        print('      fix: %s' % fix)
    return ok


def check_import(module, package, apt=True):
    try:
        m = __import__(module)
        version = getattr(m, '__version__', '')
        return check(module, True, version)
    except ImportError as e:
        fix = ('sudo apt install -y %s' % package) if apt else ('pip3 install %s --break-system-packages' % package)
        return check(module, False, str(e), fix)


def main():
    print('Uber Scan — Pi scanner preflight\n')

    check_import('numpy', 'python3-numpy')
    has_cv2 = check_import('cv2', 'python3-opencv')
    has_pytesseract = check_import('pytesseract', 'pytesseract', apt=False)

    binary = shutil.which('tesseract')
    check('tesseract binary', bool(binary), binary or 'not on PATH',
          'sudo apt install -y tesseract-ocr')

    if binary:
        try:
            out = subprocess.run([binary, '--version'], capture_output=True, text=True, timeout=10)
            check('tesseract runs', out.returncode == 0, out.stdout.splitlines()[0] if out.stdout else '')
        except Exception as e:
            check('tesseract runs', False, str(e))

    # Which of the two reading paths this machine will actually use.
    #
    # Both work and both read identically; one is about twice as quick, because
    # it does not re-load the LSTM model before every card. The fallback is
    # silent by design — a rig that reads slowly is working — which is exactly
    # why a preflight should say so. Without this the only symptom is a `ms`
    # column in the journal that is twice what it should be, months later.
    if has_cv2 and has_pytesseract:
        try:
            import pipeline as PL
            kept = bool(PL._tess_lib())
            check('reading engine', kept,
                  'kept in this process (about twice as fast)' if kept
                  else 'spawning a tesseract per read — roughly half speed',
                  'sudo apt install -y tesseract-ocr   # brings libtesseract, '
                  'which is what this uses')
        except Exception as e:
            check('reading engine', False, str(e))

    # RAM for the things that are stale two frames later.
    #
    # The live view is written up to thirty times a second and the OCR staging
    # image once per read. On /dev/shm that is free; on the SD card it is about
    # 5GB an hour onto the one component in the rig that wears out, and nothing
    # anywhere would say so — the fallback is deliberate and silent, because a
    # rig with no RAM disk should still scan.
    try:
        import handoff as HO
        on_ram = HO._dir() != HO.HERE
        check('scratch space', on_ram,
              HO._dir() + '  (frames and OCR images stay out of the SD card)'
              if on_ram else
              'no writable /dev/shm — frames go to the SD card, ~5GB an hour',
              'check /dev/shm is mounted and writable')
    except Exception as e:
        check('scratch space', False, str(e))

    espeak = shutil.which('espeak-ng')
    check('espeak-ng (only for --speak)', bool(espeak), espeak or 'not installed',
          'sudo apt install -y espeak-ng')

    # The camera is the one thing that cannot be worked around.
    try:
        from picamera2 import Picamera2
        cameras = Picamera2.global_camera_info()
        if cameras:
            names = ', '.join(c.get('Model', '?') for c in cameras)
            check('camera detected', True, names)
            full_fov = [m for m in ('2328x1748', '4656x3496')]
            check('full-frame modes available', True, ' / '.join(full_fov) +
                  '  (run scan_pi.py --list-modes to confirm)')
        else:
            check('camera detected', False, 'libcamera reports no cameras',
                  'check the ribbon cable, then add dtoverlay=imx519 to '
                  '/boot/firmware/config.txt and reboot')
    except ImportError as e:
        check('picamera2', False, str(e), 'sudo apt install -y python3-picamera2')
    except Exception as e:
        check('camera detected', False, str(e),
              'rpicam-hello --list-cameras   # see what libcamera thinks')

    # Focus deserves its own section, because the usual evidence is misleading:
    # rpicam-still lists --autofocus-mode whatever the camera is.
    try:
        import camera as CAM
        sensor, tunings = CAM.tuning_report()
        if not tunings:
            check('focus tuning', False, 'no tuning file found for %s' % sensor)
        else:
            usable = [t for t in tunings if t[1]]
            check('autofocus available', bool(usable),
                  ('%s' % usable[0][0]) if usable else
                  'none of %d tuning file(s) for %s contain an AF algorithm'
                  % (len(tunings), sensor),
                  'install Arducam\'s tuning for this module, then re-run. Point at '
                  'it directly with UBERSCAN_TUNING=/path/to/tuning.json if it lands '
                  'outside /usr/share/libcamera. Without it the lens cannot be moved '
                  'at all — focus it by hand using the sharpness number in preview.py')
            for path, has_af in tunings:
                print('      %s  %s' % ('AF  ' if has_af else 'no AF', path))
    except Exception as e:
        check('focus tuning', False, str(e))

    # Calibration is per-mount, so a missing config is expected on a fresh setup.
    config = os.path.join(HERE, 'config.json')
    check('calibration', os.path.exists(config),
          config if os.path.exists(config) else 'not calibrated yet',
          'python3 rpi/preview.py   # aim first, then: python3 rpi/calibrate.py')

    # The parser is pure python and must pass regardless of any hardware.
    if has_cv2 and has_pytesseract:
        try:
            import calibrate as CAL
            import offer_parser as OP
            p = OP.parse('$7.09 6 items (6 units) 34 min (3.6 mi) total')
            # The seed a fresh config.json gets, rather than a rate typed in
            # here. This was a third hand-written copy of the same figure, in
            # the one file whose job is to tell you the rig is set up right.
            r = OP.rate(p, CAL.SEED_SETTINGS)
            good = p['pay'] == 7.09 and p['minutes'] == 34 and round(r['perHour'], 2) == 10.61
            check('parser self-test', good, '$7.09 / 34 min -> $%.2f/hr' % r['perHour'])
        except Exception as e:
            check('parser self-test', False, str(e))

    failed = [r for r in results if not r[1]]
    # Focus by hand still works, so a missing AF algorithm is not blocking.
    # Slower is not broken. A rig spawning a tesseract per read still reads
    # every card correctly, and one with no RAM disk still scans — both are
    # worth knowing and neither is a reason to refuse to start.
    blocking = [r for r in failed
                if 'espeak' not in r[0] and 'calibration' not in r[0] and 'focus' not in r[0]
                and 'autofocus' not in r[0] and 'reading engine' not in r[0]
                and 'scratch space' not in r[0]]

    print()
    if not failed:
        print('All good. Next: python3 rpi/scan_pi.py --speak')
    elif not blocking:
        print('Nothing blocking. Finish setup with the fixes above, then:')
        print('  python3 rpi/preview.py     # aim the camera')
        print('  python3 rpi/calibrate.py   # lock in the corners')
        print('  python3 rpi/scan_pi.py --speak')
    else:
        print('%d blocking problem(s) — fix those first.' % len(blocking))
    return 1 if blocking else 0


if __name__ == '__main__':
    sys.exit(main())
