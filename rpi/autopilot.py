#!/usr/bin/env python3
"""One command that takes the rig from nothing to scanning.

    python3 rpi/autopilot.py            # the whole thing
    python3 rpi/autopilot.py --json     # same, machine-readable (server.js uses this)

There were four steps to run in order, each of which had to be stopped before
the next could have the camera. That is a sequence to memorise and a camera to
fight over, so it is done here instead:

  check   — dependencies, camera, focus
  aim     — serves the live preview and waits for the mount to be good
  calibrate — the moment the frame holds steady and sharp, locks in the corners
  scan    — reads offers, for as long as it runs

Already calibrated, it goes straight to scanning. Delete rpi/config.json (or
pass --recalibrate) to set the mount up again.
"""

import argparse
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Same reason as the copy in camera.py, set here too because check() imports
# picamera2 before anything imports camera, and this has to be in the
# environment before libcamera starts talking.
os.environ.setdefault('LIBCAMERA_LOG_LEVELS', '*:WARN')

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, 'config.json')
SNAPSHOT = os.path.join(HERE, 'live-frame.jpg')

# The frame has to be this good, this consistently, before calibrating itself.
# One lucky frame while the bracket is still in your hand is not a mount.
STABLE_READINGS = 6
STABLE_INTERVAL = 0.5


def emit(payload, as_json):
    """Every message goes to one place, so the terminal and the web UI agree."""
    if as_json:
        sys.stdout.write(json.dumps(payload) + '\n')
    else:
        phase = payload.get('phase', '')
        message = payload.get('message', '')
        if payload.get('ready'):
            message = '$%.2f/hr %s  (pay $%.2f, %s min, %s mi)' % (
                payload['perHour'], payload['state'].upper(), payload['pay'],
                payload['minutes'], payload['miles'])
        sys.stdout.write('[%s] %s\n' % (phase, message))
    sys.stdout.flush()


def check(as_json):
    """Fail early and specifically, rather than deep inside a capture loop."""
    missing = []
    for module, fix in (('cv2', 'sudo apt install -y python3-opencv'),
                        ('numpy', 'sudo apt install -y python3-numpy'),
                        ('pytesseract', 'pip3 install pytesseract --break-system-packages'),
                        ('picamera2', 'sudo apt install -y python3-picamera2')):
        try:
            __import__(module)
        except ImportError:
            missing.append('%s (%s)' % (module, fix))

    import shutil
    if not shutil.which('tesseract'):
        missing.append('tesseract (sudo apt install -y tesseract-ocr)')

    if missing:
        emit({'phase': 'error', 'message': 'missing: ' + '; '.join(missing)}, as_json)
        return False
    return True


def aim(as_json, port, timeout, min_card=None):
    """Serve the preview and wait for the mount to be good enough, then stop.

    Returns True once the frame has been big enough and sharp enough for several
    readings in a row.
    """
    import cv2
    import camera as CAM
    import pipeline as PL
    import preview as PV
    from calibrate import MIN_CARD_PIXELS, SHARP_ROI

    try:
        source = PV.Source()
    except CAM.CameraBusy as e:
        emit({'phase': 'error', 'message': str(e)}, as_json)
        return None
    focus = getattr(source, 'focus', None)
    if focus and not focus.get('supported'):
        emit({'phase': 'aim', 'message': 'no working autofocus: ' + focus['reason']}, as_json)

    PV.Handler.source = source
    from http.server import ThreadingHTTPServer
    server = ThreadingHTTPServer(('0.0.0.0', port), PV.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    emit({'phase': 'aim', 'message': 'not calibrated — open /live.html and move the mount '
          'until this says good. The camera view there is live during aiming; port %d '
          'serves the same thing as a plain MJPEG stream if you want it full size.'
          % port, 'previewPort': port}, as_json)

    floor = min_card or MIN_CARD_PIXELS
    good = 0
    started = time.time()
    last_report = 0
    try:
        while time.time() - started < timeout:
            frame = source.frame()
            shown, card_px = PV.annotate(frame, source.scale_to_capture, source.lens_position)

            # Put the annotated frame where the live page looks for it. Aiming a
            # camera you cannot see is the worst part of building this rig, and
            # until now the only picture during this phase was on a second port
            # that the printed URL gave as "localhost" — which, from the phone
            # you are holding, is the phone. The page that is already telling
            # you to move the mount can show you the mount.
            PL.write_jpeg(SNAPSHOT, PL.resize_height(shown, 480))

            sharp = None
            spill = []
            if card_px:
                quad = PL.detect_screen_quad(frame)
                if quad is not None:
                    spill = PL.touches_edge(quad, frame.shape)
                    sharp = PV.sharpness(PL.crop(PL.warp(frame, quad, 600), SHARP_ROI))

            # Spill is reported, not refused. Backing off far enough to fit a
            # whole phone in a 4:3 frame drops the card to around 400px, and
            # the resolution is the thing that makes any of this work — so
            # clipping the map away is the right mount, not a broken one. What
            # used to depend on seeing the whole screen was the crop being a
            # fraction of it, and the crop finds the card by content now.
            ok = bool(card_px and card_px >= floor and sharp and sharp >= PV.SHARP_FLOOR)
            good = good + 1 if ok else 0

            now = time.time()
            if now - last_report > 2:
                last_report = now
                emit({'phase': 'aim', 'cardPixels': card_px, 'sharpness': round(sharp) if sharp else None,
                      'stable': good, 'need': STABLE_READINGS, 'spill': spill,
                      'message': _aim_hint(card_px, sharp, floor, PV.SHARP_FLOOR, spill)}, as_json)

            if good >= STABLE_READINGS:
                emit({'phase': 'aim', 'message': 'mount looks good — calibrating'}, as_json)
                return source
            time.sleep(STABLE_INTERVAL)
    finally:
        server.shutdown()

    emit({'phase': 'error', 'message': 'gave up waiting for a good frame after %ds' % timeout}, as_json)
    source.close()
    return None


def _aim_hint(card_px, sharp, min_px, min_sharp, spill=()):
    if not card_px:
        return ('no phone screen found — it must be lit, in frame, and with some '
                'darker surround; a frame filled edge to edge cannot be told '
                'apart from the room')
    if card_px < min_px:
        return 'card is %d px, needs %d — move the camera closer' % (card_px, min_px)
    if not sharp or sharp < min_sharp:
        return 'card is big enough but blurry (%s) — adjust focus' % (round(sharp) if sharp else '?')
    if spill:
        return ('good: %d px, sharp %d — the %s of the screen is out of frame, which '
                'is fine as long as the whole offer card is visible'
                % (card_px, round(sharp), ' and '.join(spill)))
    return 'good: %d px, sharp %d' % (card_px, round(sharp))


def _measure_exposure(source, quad, as_json):
    """Find the exposure this particular phone does not ripple at.

    Every panel dims at its own frequency, so the right exposure is a property
    of the phone rather than of the camera, and the only way to know it is to
    try a few and watch. Measured on the warped screen so the banding being
    scored is the screen's, not the dashboard's.

    Falls back to the default — one 60Hz cycle, which is also two of 120 and
    four of 240 — if the camera will not take exposure settings at all.
    """
    import exposure as EX
    import pipeline as PL

    def grab(exposure_us):
        try:
            source.cam.set_controls({'AeEnable': False, 'ExposureTime': int(exposure_us)})
        except Exception:
            return []
        time.sleep(0.45)          # let the setting take effect before believing it
        frames = []
        for _ in range(3):
            frame = source.frame()
            warped = PL.warp(frame, quad, 400)
            frames.append(PL.preprocess(warped))
        return frames

    if source.cam is None:
        return EX.DEFAULT_EXPOSURE, 'no camera to measure with'

    chosen, report = EX.choose_exposure(grab)
    if not report:
        return EX.DEFAULT_EXPOSURE, 'exposure not settable on this camera'

    best = [r for r in report if r['exposure'] == chosen]
    detail = '; '.join('%dus banding %.1f bright %.0f' % (r['exposure'], r['banding'], r['bright'])
                       for r in report)
    emit({'phase': 'calibrated',
          'message': 'exposure %dus (banding %.1f) — measured against this screen; tried %s'
                     % (chosen, best[0]['banding'] if best else -1, detail)}, as_json)
    return int(chosen), detail


def calibrate_from(source, as_json):
    """Write config.json from the frame the preview is already looking at."""
    import cv2
    import pipeline as PL
    from calibrate import DEFAULT_ROI, card_source_pixels, load_existing

    frame = source.frame()
    quad = PL.detect_screen_quad(frame)
    if quad is None:
        emit({'phase': 'error', 'message': 'lost the screen while calibrating'}, as_json)
        return False


    # The preview runs smaller than the scanner captures, so the corners have to
    # be scaled into capture coordinates or every read would be cropped wrong.
    scale = source.scale_to_capture
    quad_full = [[float(x * scale), float(y * scale)] for x, y in quad]

    exposure_us, why = _measure_exposure(source, quad, as_json)

    # Keep whatever the driver put in the file. Calibrating decides where the
    # phone is; it has no business deciding what an hour of their time is worth,
    # and there is no second copy of that on the Pi to put back afterwards.
    config = load_existing(CONFIG)
    config.update({
        'quad': quad_full,
        'cropBox': DEFAULT_ROI,
        'cardHeight': 900,
        'capture': {'width': source.capture_size[0], 'height': source.capture_size[1]},
        'lensPosition': source.lens_position,
        'exposureTime': exposure_us,
        'exposureWhy': why,
    })
    config.setdefault('settings', {'target': 25, 'band': 15, 'costPerMile': 0.30,
                                   'pad': 0, 'secondsPerItem': 0})
    # Where the screen had drifted to is measured against corners that no
    # longer exist, so it cannot survive a re-aim.
    config.pop('trackedQuad', None)
    with open(CONFIG, 'w') as fh:
        json.dump(config, fh, indent=2)

    # The preview has to be the reader's own picture, not a re-creation of it.
    # Composed the way the scanner composes it, using this frame and the
    # corners found in it — the aiming stream is half the capture's width, so
    # this is softer than a real read, but it is framed identically. Warping
    # the whole screen and calling it "what tesseract will be handed" stopped
    # being true when the crop started being placed per read, and this file is
    # the one thing a driver is told to look at before trusting the mount.
    preview_path = os.path.join(HERE, 'config-preview.png')
    probe = PL.Scanner(quad=quad, roi=DEFAULT_ROI, card_height=900)
    checked = probe.read(frame)
    cv2.imwrite(preview_path, checked['card'])
    read = checked['parsed']

    # Say whether the calibration can actually read, while the driver is still
    # standing at the car. "wrote config.json" is not the same claim.
    got = ('read $%.2f, %s min, %s mi from this frame'
           % (read['pay'], read['minutes'], read['miles']) if read['complete']
           else 'no offer on the screen to test against — check the preview by eye')
    emit({'phase': 'calibrated',
          'cardPixels': int(round(card_source_pixels(quad, frame.shape) * scale)),
          'read': read['complete'],
          'message': 'wrote config.json (preview at rpi/config-preview.png); %s' % got}, as_json)
    return True


def scan(as_json, speak, extra_args):
    """Hand over to the scanner, replacing this process so there is one to stop."""
    args = [sys.executable, os.path.join(HERE, 'scan_pi.py')]
    if as_json:
        args.append('--json')
    if speak:
        args.append('--speak')
    args.extend(extra_args)
    emit({'phase': 'scanning', 'message': 'starting scanner'}, as_json)
    sys.stdout.flush()
    # execv keeps the process, so the camera lock this process holds has to go
    # first or the scanner would find the camera busy with itself.
    try:
        import camera as CAM
        if CAM._lock_handle:
            CAM._lock_handle.close()
            CAM._lock_handle = None
    except Exception:
        pass
    # execv passes this environment on. Anything pointing into /tmp came from
    # picamera2 writing a tuning file for this process, and will be gone before
    # the scanner reads it.
    tuning = os.environ.get('LIBCAMERA_RPI_TUNING_FILE', '')
    if tuning.startswith('/tmp/'):
        os.environ.pop('LIBCAMERA_RPI_TUNING_FILE', None)
    os.execv(sys.executable, args)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', action='store_true', help='machine-readable output')
    ap.add_argument('--speak', action='store_true', help='say verdicts aloud')
    ap.add_argument('--recalibrate', action='store_true', help='ignore any existing calibration')
    ap.add_argument('--preview-port', type=int, default=8081)
    ap.add_argument('--min-card', type=int, default=None,
                    help='override the card-height floor in sensor pixels')
    ap.add_argument('--aim-timeout', type=int, default=900,
                    help='seconds to wait for a good mount before giving up')
    args, extra = ap.parse_known_args()

    if not check(args.json):
        return 1

    import camera as CAM

    # Deleting the file was the old way to force a re-aim, and it took the
    # driver's target and running costs with it — calibrate_from can only
    # preserve settings that are still there to read. Forcing the branch
    # directly leaves the file, and its settings, in place.
    if args.recalibrate or not os.path.exists(CONFIG):
        source = aim(args.json, args.preview_port, args.aim_timeout, args.min_card)
        if source is None:
            return 1
        ok = calibrate_from(source, args.json)
        # The scanner needs the camera, and only one process may hold it.
        source.close()
        time.sleep(1.0)
        if not ok:
            return 1
    else:
        emit({'phase': 'calibrated', 'message': 'using existing rpi/config.json'}, args.json)

    scan(args.json, args.speak, extra)
    return 0


if __name__ == '__main__':
    sys.exit(main())
