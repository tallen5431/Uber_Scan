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

    # The backup: when the copy machine last answered. Without this a copy
    # that rebooted, or dropped off the VPN, looked exactly like a car out of
    # range — every tick "did not answer" under --quiet, exit 0, a healthy
    # looking timer — and nothing anywhere said how old the last backup was.
    # sync.py stamps `<journal>.synced` on every run that reaches the copy.
    try:
        import journal as JR
        import sync as SY
        journal_path = os.environ.get('JOURNAL') or JR.DEFAULT_PATH
        last = SY.last_synced(journal_path)
        # Overridable for the same reason UBERSCAN_HANDOFF_DIR is: this branch
        # is the one that misreported a working backup, and a check that can
        # only be exercised on a machine with the timer actually installed is a
        # check nothing runs until it is wrong again.
        timer = os.path.exists(os.environ.get('UBERSCAN_SYNC_TIMER')
                               or '/etc/systemd/system/uberscan-sync.timer')
        if last is None:
            # "No stamp" is not "never reached", and saying so cost a rig an
            # afternoon: the stamp file is newer than the sync itself, so on a
            # rig that had been backing up happily for months the first doctor
            # run after an update announced that the copy had never been
            # reached. It had. Nothing had written the stamp yet.
            #
            # The rig cannot tell the two apart from here — there is no record
            # older than the record itself — so it says what it actually knows
            # and what makes it true, rather than picking the alarming reading.
            # FALSE either way, and the two details stay exactly as they were.
            # The verdict used to be `not timer`, which is inverted with respect
            # to the danger it is about: a rig with NO sync at all passed, and a
            # rig half-way through setting one up failed. So a Pi with a camera,
            # a calibration and espeak but no copy of its journal anywhere
            # printed "All good." — about the machine whose only record of every
            # offer it has ever read is one SD card, in a vehicle.
            #
            # What the rig genuinely cannot tell apart is WHY there is no stamp,
            # and that distinction is kept: the detail and the fix still say
            # which of the two it is looking at. What is no longer claimed is
            # that either of them is fine.
            check('offers backed up off the car', False,
                  'no sync set up — see tools/install-sync.sh' if not timer
                  else 'the timer is installed, but no sync has been recorded yet',
                  '' if not timer else
                  'normal for the first ten minutes after an update — this is a '
                  'newer record than the sync itself. To fill it in now: '
                  'sudo systemctl start uberscan-sync.service, then run this '
                  'again. If it still says this, run python3 rpi/sync.py --to '
                  '<the copy machine> and read what it says.')
        else:
            hours = max(0.0, (JR.now_ms() - last['at']) / 3600000.0)
            check('offers backed up off the car', hours < 24,
                  '%s ago, to %s' % (
                      ('%d min' % round(hours * 60)) if hours < 1 else '%.1f hours' % hours,
                      last.get('to') or '?'),
                  'the copy machine has not been reached for %.0f hours — is its '
                  'server running, and is it on the VPN?' % hours)
    except Exception as e:                                    # noqa: BLE001
        check('offers backed up off the car', False, str(e))

    # ...and whether the file the backup is copying is still whole.
    #
    # A line that will not parse is an offer that is gone. The journal is
    # append-only, nothing keeps a second copy of a line, and no amount of
    # syncing gets it back — the copy machine faithfully receives the hole.
    #
    # One is what a power cut costs, and the card loses power when the engine
    # does, so this does not fail for one. It fails for more, because a number
    # that is climbing is a card beginning to go, and the whole value of
    # noticing is noticing while there is still something to copy off it.
    try:
        import journal as JR
        journal_path = os.environ.get('JOURNAL') or JR.DEFAULT_PATH
        log = JR.Journal(journal_path)
        kept = len(log.rows())
        if log.unreadable:
            # Nothing may be concluded from a count of zero here. This branch
            # exists because the count IS zero and the two previous readers of
            # it — this check and sync.py — both read that as "a quiet week".
            check('the journal file is whole', False,
                  'could not be read at all (%s)' % log.unreadable,
                  'this is not an empty journal, it is a journal nothing can '
                  'read — and until it can be, nothing is being backed up '
                  'either. Check %s: ls -l %s' % (journal_path, journal_path))
        else:
            check('the journal file is whole', log.torn <= 1,
                  ('%d row%s readable, none torn' % (kept, '' if kept == 1 else 's'))
                  if not log.torn else
                  '%d row%s readable, %d line%s unreadable'
                  % (kept, '' if kept == 1 else 's',
                     log.torn, '' if log.torn == 1 else 's'),
                  'those offers are gone and cannot be recovered — the file is '
                  'append-only and nothing keeps a second copy of a line. One is '
                  'what a power cut costs; this many is a card starting to fail. '
                  'Copy %s somewhere else now, then check the card.' % journal_path)
        # ...and whether a row can still be ADDED to it, which is a different
        # question and the one the rig actually depends on.
        #
        # Every line above asks whether the journal can be READ. On an SD card
        # remounted read-only — which scan_pi.py names outright as the classic
        # Pi failure — reading is perfect: every row comes back, nothing is
        # torn, and this printed "N rows readable, none torn" on a rig that
        # could not record another offer for the rest of the shift. sync.py
        # then read the same still-readable file, found nothing new, and
        # stamped the backup fresh, so the line above it reported a healthy
        # copy as well. Two greens and a silent, total loss of the only
        # permanent record.
        #
        # Opened for append and closed again: it creates nothing that was not
        # there, writes no byte, and asks the filesystem the exact question the
        # scanner will ask it in a few seconds' time.
        try:
            with open(journal_path, 'a'):
                pass
            writable, why = True, 'a row can be added'
        except Exception as e:                                # noqa: BLE001
            writable, why = False, 'cannot be written (%s)' % e
        check('the journal can be written', writable, why,
              'the rig can read every offer it has already stored and cannot '
              'record another one. An SD card that has gone read-only is the '
              'usual cause, and it reads perfectly until you try to write: '
              'mount | grep " on / " will say ro. Nothing is being kept until '
              'this is fixed, and the backup will keep reporting success '
              'because the file it copies is unchanged.')
    except Exception as e:                                    # noqa: BLE001
        check('the journal file is whole', False, str(e))

    # The camera is the one thing that cannot be worked around.
    try:
        from picamera2 import Picamera2
        cameras = Picamera2.global_camera_info()
        if cameras:
            names = ', '.join(c.get('Model', '?') for c in cameras)
            check('camera detected', True, names)
            # The sensor's own modes, asked of the sensor. This line used to
            # print the IMX519's two sizes over a literal True whatever the
            # camera was, so on a Camera Module 3 the one line the doctor
            # printed about modes was the one line that could not be trusted.
            # The camera has to be opened to ask, and the service may be
            # holding it: then it is not checked, and says so.
            try:
                cam = Picamera2()
                try:
                    sizes = ['%dx%d' % tuple(m['size']) for m in cam.sensor_modes
                             if m.get('size')]
                finally:
                    cam.close()
                biggest = max((m[0] * m[1] for m in
                               (tuple(int(x) for x in sz.split('x')) for sz in sizes)),
                              default=0)
                check('full-frame modes available', biggest >= 2328 * 1748,
                      ' / '.join(sizes) or 'none reported',
                      'this sensor is smaller than the scanner is tuned for')
            except Exception as e:                            # noqa: BLE001
                check('full-frame modes available', True,
                      'not checked — the camera is in use (%s); stop the service '
                      'and run this again to see them' % str(e)[:60])
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
          'python3 rpi/autopilot.py   # aims and calibrates on its own')

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
                and 'scratch space' not in r[0] and 'backed up' not in r[0]]

    print()
    # The next step is the autopilot, which aims, calibrates and scans on its
    # own — not the three scripts it replaced. And if the service is
    # installed it holds the camera, so it is stopped first.
    step = []
    if os.path.exists('/etc/systemd/system/uberscan.service'):
        step.append('  sudo systemctl stop uberscan   # it holds the camera while it runs')
    step.append('  python3 rpi/autopilot.py --speak   # aims, calibrates, then scans')
    if not failed:
        print('All good. Next:')
        print('\n'.join(step))
    elif not blocking:
        print('Nothing blocking. Finish setup with the fixes above, then:')
        print('\n'.join(step))
    else:
        print('%d blocking problem(s) — fix those first.' % len(blocking))
    return 1 if blocking else 0


if __name__ == '__main__':
    sys.exit(main())
