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

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, 'config.json')

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


def aim(as_json, port, timeout):
    """Serve the preview and wait for the mount to be good enough, then stop.

    Returns True once the frame has been big enough and sharp enough for several
    readings in a row.
    """
    import cv2
    import preview as PV
    import camera as CAM
    from calibrate import DEFAULT_ROI, MIN_CARD_PIXELS

    source = PV.Source()
    focus = getattr(source, 'focus', None)
    if focus and not focus.get('supported'):
        emit({'phase': 'aim', 'message': 'no working autofocus: ' + focus['reason']}, as_json)

    PV.Handler.source = source
    from http.server import ThreadingHTTPServer
    server = ThreadingHTTPServer(('0.0.0.0', port), PV.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    emit({'phase': 'aim', 'message': 'not calibrated — open http://<this-pi>:%d/ and '
          'move the mount until the overlay is green' % port, 'previewPort': port}, as_json)

    good = 0
    started = time.time()
    last_report = 0
    try:
        while time.time() - started < timeout:
            frame = source.frame()
            _, card_px = PV.annotate(frame, source.scale_to_capture, source.lens_position)

            sharp = None
            if card_px:
                import pipeline as PL
                quad = PL.detect_screen_quad(frame)
                if quad is not None:
                    sharp = PV.sharpness(PL.crop(PL.warp(frame, quad, 600), DEFAULT_ROI))

            ok = bool(card_px and card_px >= MIN_CARD_PIXELS and sharp and sharp >= PV.SHARP_FLOOR)
            good = good + 1 if ok else 0

            now = time.time()
            if now - last_report > 2:
                last_report = now
                emit({'phase': 'aim', 'cardPixels': card_px, 'sharpness': round(sharp) if sharp else None,
                      'stable': good, 'need': STABLE_READINGS,
                      'message': _aim_hint(card_px, sharp, MIN_CARD_PIXELS, PV.SHARP_FLOOR)}, as_json)

            if good >= STABLE_READINGS:
                emit({'phase': 'aim', 'message': 'mount looks good — calibrating'}, as_json)
                return source
            time.sleep(STABLE_INTERVAL)
    finally:
        server.shutdown()

    emit({'phase': 'error', 'message': 'gave up waiting for a good frame after %ds' % timeout}, as_json)
    source.close()
    return None


def _aim_hint(card_px, sharp, min_px, min_sharp):
    if not card_px:
        return 'no phone screen in frame — is it lit and pointing at the camera?'
    if card_px < min_px:
        return 'card is %d px, needs %d — move the camera closer' % (card_px, min_px)
    if not sharp or sharp < min_sharp:
        return 'card is big enough but blurry (%s) — adjust focus' % (round(sharp) if sharp else '?')
    return 'good: %d px, sharp %d' % (card_px, round(sharp))


def calibrate_from(source, as_json):
    """Write config.json from the frame the preview is already looking at."""
    import cv2
    import pipeline as PL
    from calibrate import DEFAULT_ROI, card_source_pixels

    frame = source.frame()
    quad = PL.detect_screen_quad(frame)
    if quad is None:
        emit({'phase': 'error', 'message': 'lost the screen while calibrating'}, as_json)
        return False

    # The preview runs smaller than the scanner captures, so the corners have to
    # be scaled into capture coordinates or every read would be cropped wrong.
    scale = source.scale_to_capture
    quad_full = [[float(x * scale), float(y * scale)] for x, y in quad]

    config = {
        'quad': quad_full,
        'roi': DEFAULT_ROI,
        'cardHeight': 900,
        'capture': {'width': source.capture_size[0], 'height': source.capture_size[1]},
        'lensPosition': source.lens_position,
        'settings': {'target': 25, 'band': 15, 'costPerMile': 0.30,
                     'pad': 0, 'secondsPerItem': 0},
    }
    with open(CONFIG, 'w') as fh:
        json.dump(config, fh, indent=2)

    preview_path = os.path.join(HERE, 'config-preview.png')
    cv2.imwrite(preview_path, PL.preprocess(PL.crop(PL.warp(frame, quad, 900), DEFAULT_ROI)))

    emit({'phase': 'calibrated',
          'cardPixels': int(round(card_source_pixels(quad, DEFAULT_ROI) * scale)),
          'message': 'wrote config.json (preview at rpi/config-preview.png)'}, as_json)
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
    os.execv(sys.executable, args)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', action='store_true', help='machine-readable output')
    ap.add_argument('--speak', action='store_true', help='say verdicts aloud')
    ap.add_argument('--recalibrate', action='store_true', help='ignore any existing calibration')
    ap.add_argument('--preview-port', type=int, default=8081)
    ap.add_argument('--aim-timeout', type=int, default=900,
                    help='seconds to wait for a good mount before giving up')
    args, extra = ap.parse_known_args()

    if not check(args.json):
        return 1

    if args.recalibrate:
        try:
            os.remove(CONFIG)
        except OSError:
            pass

    if not os.path.exists(CONFIG):
        source = aim(args.json, args.preview_port, args.aim_timeout)
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
