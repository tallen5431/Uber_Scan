#!/usr/bin/env python3
"""Live scanner for a Pi camera pointed at the driving phone.

    python3 rpi/scan_pi.py --speak

Two streams come off the sensor at once: a tiny one that answers "did anything
change?" for almost nothing, and a full one that is only ever touched when the
answer is yes. Idle cost is a few milliseconds per frame; the expensive read
happens once per offer, not sixty times a second.

Every camera control that could hunt — exposure, white balance, focus — is
pinned. A fixed mount means there is nothing to track, and an autofocus pass
mid-offer costs more time than the OCR does.
"""

import argparse
import json
import os
import subprocess
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline as PL

DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
DEFAULT_SNAPSHOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'live-frame.jpg')

# The motion gate means whole minutes can pass with no read, so the snapshot is
# refreshed on a timer as well. Cheap: a warp and a resize, no OCR.
SNAPSHOT_INTERVAL = 2.0


def load_config(path):
    if not os.path.exists(path):
        sys.exit('no %s — run calibrate.py first' % path)
    with open(path) as fh:
        return json.load(fh)


LORES = (640, 480)

# IMX519 modes, from `rpicam-hello --list-cameras`. The two smallest are
# *cropped* out of the sensor, not scaled down: 1280x720 sees only a
# 2560x1440 window and 1920x1080 only 3840x2160, so both throw away field of
# view. Only these two see the whole sensor, which is what a phone in a mount
# needs.
FULL_FOV_MODES = {
    '2328x1748': (2328, 1748),   # 2x2 binned, 30fps — the default
    '4656x3496': (4656, 3496),   # full resolution, 9fps
}


def start_camera(cfg, exposure_us, gain, lens):
    import camera as CAM

    cam, focus = CAM.open_camera()
    cap = cfg.get('capture', {})
    main_size = (cap.get('width', 2328), cap.get('height', 1748))

    # Pin the sensor mode explicitly. Left to itself picamera2 picks a mode from
    # the requested size, and on this sensor a smaller pick silently crops the
    # field of view — which moves the phone out of the calibrated quad.
    cam.configure(cam.create_video_configuration(
        main={'size': main_size, 'format': 'RGB888'},
        lores={'size': LORES, 'format': 'YUV420'},
        raw={'size': main_size},
        buffer_count=4,
    ))

    cam.start()
    time.sleep(1.0)

    # A phone screen is an emissive, PWM-dimmed panel: auto-exposure hunts on it
    # and short exposures alias into the dimming as dark bands. Pin everything.
    ctrls = {
        'AeEnable': False,
        'AwbEnable': False,
        'ExposureTime': exposure_us,
        'AnalogueGain': gain,
    }

    # Advertised controls prove nothing: a tuning file with no autofocus
    # algorithm still exposes AfMode and then ignores every lens position.
    if focus.get('supported') and 'AfMode' in cam.camera_controls:
        from libcamera import controls
        ctrls['AfMode'] = controls.AfModeEnum.Manual
        ctrls['LensPosition'] = lens
    else:
        print('focus not settable (%s) — it is whatever the mount distance gives'
              % focus.get('reason', 'no autofocus'))

    cam.set_controls(ctrls)
    time.sleep(0.5)
    return cam


def write_snapshot(frame, cfg, path):
    """Write what the camera sees, atomically.

    Renamed into place rather than written in place, because the web server may
    read it at any moment and half a JPEG is worse than a slightly old one.
    """
    try:
        view = PL.snapshot(frame, np.array(cfg['quad'], dtype=np.float32),
                           cfg.get('roi'), cfg.get('cardHeight', 900))
        tmp = path + '.tmp'
        cv2.imwrite(tmp, view, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        os.replace(tmp, path)
    except Exception as e:
        print('snapshot failed: %s' % e)


def say(text):
    try:
        subprocess.Popen(['espeak-ng', '-s', '165', text],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        pass


def spoken(rate):
    dollars = int(round(rate['perHour']))
    word = {'go': 'accept', 'warn': 'close', 'no': 'pass'}[rate['state']]
    return '%s. %d an hour.' % (word, dollars)


def show(frame_text, rate, parsed, ms, locked):
    if not rate['ready']:
        print('%s  no offer' % frame_text)
        return
    flags = []
    if parsed['milesCorrected']:
        flags.append('decimal recovered')
    if parsed['milesUncertain']:
        flags.append('distance unreadable, cost ignored')
    print('%s  $%.2f/hr  %-4s  pay $%.2f  %s min  %s mi%s  [%.0fms]%s'
          % (frame_text, rate['perHour'], rate['state'].upper(), parsed['pay'],
             parsed['minutes'], parsed['miles'],
             '  (%s)' % '; '.join(flags) if flags else '',
             ms['total'], '  LOCKED' if locked else ''))


def emit(rate, parsed, ms, locked):
    """One JSON object per line, flushed, so a parent process sees reads live."""
    payload = {
        'ready': rate['ready'],
        'locked': locked,
        'state': rate['state'],
        'perHour': round(rate['perHour'], 2) if rate['ready'] else None,
        'perMile': round(rate['perMile'], 2) if rate.get('perMile') else None,
        'pay': parsed['pay'],
        'minutes': parsed['minutes'],
        'miles': parsed['miles'],
        'items': parsed['items'],
        'milesCorrected': parsed['milesCorrected'],
        'milesUncertain': parsed['milesUncertain'],
        'ms': round(ms['total']),
        'text': (parsed.get('text') or '')[:200],
    }
    sys.stdout.write(json.dumps(payload) + '\n')
    sys.stdout.flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default=DEFAULT_CONFIG)
    ap.add_argument('--speak', action='store_true', help='say the verdict aloud via espeak-ng')
    ap.add_argument('--display', action='store_true', help='fullscreen verdict on an attached screen')
    ap.add_argument('--exposure', type=int, default=12000,
                    help='microseconds; keep above ~10000 so OLED dimming does not band')
    ap.add_argument('--gain', type=float, default=1.5)
    ap.add_argument('--lens', type=float, default=None,
                    help='dioptres (1/metres): 4.0 focuses at 25cm. Defaults to the '
                         'value autofocus found during calibration')
    ap.add_argument('--json', action='store_true',
                    help='emit one JSON object per read on stdout, for another process to consume')
    ap.add_argument('--list-modes', action='store_true',
                    help='print the sensor modes this camera reports, then exit')
    ap.add_argument('--save-misses', metavar='DIR',
                    help='write frames that failed to parse, for tuning')
    ap.add_argument('--snapshot', default=DEFAULT_SNAPSHOT,
                    help='where to write the live view the web UI shows ("" to disable)')
    args = ap.parse_args()

    if args.list_modes:
        from picamera2 import Picamera2
        cam = Picamera2()
        for m in cam.sensor_modes:
            print(m)
        cam.close()
        return

    cfg = load_config(args.config)
    scanner = PL.Scanner(
        quad=np.array(cfg['quad'], dtype=np.float32),
        roi=cfg.get('roi'),
        card_height=cfg.get('cardHeight', 900),
        settings=cfg.get('settings', {}),
    )

    # Calibration already found focus with autofocus; reuse it rather than
    # making the driver rediscover a number that cannot change on a fixed mount.
    lens = args.lens if args.lens is not None else cfg.get('lensPosition') or 4.0
    cam = start_camera(cfg, args.exposure, args.gain, lens)
    if args.save_misses:
        os.makedirs(args.save_misses, exist_ok=True)
    if args.display:
        cv2.namedWindow('uber-scan', cv2.WND_PROP_FULLSCREEN)
        cv2.setWindowProperty('uber-scan', cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    print('scanning — ctrl-c to stop')
    spoke_for = None
    frames = 0
    last_snapshot = 0.0
    try:
        while True:
            request = cam.capture_request()
            try:
                # The Y plane leads the YUV420 buffer, and luma is all the gate
                # needs. Taken from the flat buffer rather than a reshaped array
                # so the chroma planes cannot be mistaken for image rows.
                buf = request.make_buffer('lores')
                luma = np.frombuffer(buf, dtype=np.uint8,
                                     count=LORES[0] * LORES[1]).reshape((LORES[1], LORES[0]))
                do_read = scanner.should_read(luma)
                # Grab the full frame for a read, or when the live view is due —
                # otherwise nothing is ever seen between offers.
                due = args.snapshot and (time.time() - last_snapshot) > SNAPSHOT_INTERVAL
                if not do_read and not due:
                    continue
                # picamera2's "RGB888" hands back B, G, R ordered arrays, which
                # is exactly what OpenCV expects. The name is the odd one out.
                frame = request.make_array('main')
            finally:
                request.release()

            if args.snapshot and (due or do_read):
                write_snapshot(frame, cfg, args.snapshot)
                last_snapshot = time.time()

            if not do_read:
                continue

            frames += 1
            out = scanner.read(frame)
            rate, parsed = out['rate'], out['parsed']
            if args.json:
                emit(rate, parsed, out['ms'], out['locked'])
            else:
                show('#%d' % frames, rate, parsed, out['ms'], out['locked'])

            if args.save_misses and not parsed['complete']:
                cv2.imwrite(os.path.join(args.save_misses, 'miss-%d.png' % int(time.time())), frame)

            # Speak once per offer, at the point two reads agree, never per frame.
            if args.speak and out['locked'] and rate['ready']:
                sig = (parsed['pay'], parsed['minutes'])
                if sig != spoke_for:
                    spoke_for = sig
                    say(spoken(rate))
            if not rate['ready']:
                spoke_for = None

            if args.display:
                cv2.imshow('uber-scan', render_panel(rate, parsed))
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
    except KeyboardInterrupt:
        pass
    finally:
        cam.stop()
        cam.close()
        if args.display:
            cv2.destroyAllWindows()


COLOURS = {'go': (100, 201, 23), 'warn': (36, 165, 245), 'no': (75, 50, 240), 'empty': (36, 27, 20)}


def render_panel(rate, parsed, size=(800, 480)):
    """Big, flat, readable at a glance and at arm's length."""
    panel = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    panel[:] = COLOURS[rate['state'] if rate['ready'] else 'empty']
    if not rate['ready']:
        cv2.putText(panel, 'waiting', (40, 260), cv2.FONT_HERSHEY_SIMPLEX, 2.2, (200, 200, 200), 4)
        return panel

    label = {'go': 'ACCEPT', 'warn': 'CLOSE', 'no': 'PASS'}[rate['state']]
    cv2.putText(panel, label, (40, 90), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (255, 255, 255), 5)
    cv2.putText(panel, '$%.0f/hr' % rate['perHour'], (36, 300),
                cv2.FONT_HERSHEY_SIMPLEX, 6.0, (255, 255, 255), 12)
    cv2.putText(panel, '$%.2f  %s min  %s mi' % (parsed['pay'], parsed['minutes'], parsed['miles']),
                (40, 400), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 3)
    return panel


if __name__ == '__main__':
    main()
