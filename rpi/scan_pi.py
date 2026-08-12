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


def load_config(path):
    if not os.path.exists(path):
        sys.exit('no %s — run calibrate.py first' % path)
    with open(path) as fh:
        return json.load(fh)


def start_camera(cfg, exposure_us, gain, lens):
    from picamera2 import Picamera2
    from libcamera import controls

    cam = Picamera2()
    cap = cfg.get('capture', {})
    main_size = (cap.get('width', 2328), cap.get('height', 1748))

    cam.configure(cam.create_video_configuration(
        main={'size': main_size, 'format': 'RGB888'},
        lores={'size': (640, 480), 'format': 'YUV420'},
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
    try:
        ctrls['AfMode'] = controls.AfModeEnum.Manual
        ctrls['LensPosition'] = lens
    except AttributeError:
        pass                       # fixed-focus module: nothing to pin
    cam.set_controls(ctrls)
    time.sleep(0.5)
    return cam


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default=DEFAULT_CONFIG)
    ap.add_argument('--speak', action='store_true', help='say the verdict aloud via espeak-ng')
    ap.add_argument('--display', action='store_true', help='fullscreen verdict on an attached screen')
    ap.add_argument('--exposure', type=int, default=12000,
                    help='microseconds; keep above ~10000 so OLED dimming does not band')
    ap.add_argument('--gain', type=float, default=1.5)
    ap.add_argument('--lens', type=float, default=4.0,
                    help='dioptres (1/metres): 4.0 focuses at 25cm')
    ap.add_argument('--save-misses', metavar='DIR',
                    help='write frames that failed to parse, for tuning')
    args = ap.parse_args()

    cfg = load_config(args.config)
    scanner = PL.Scanner(
        quad=np.array(cfg['quad'], dtype=np.float32),
        roi=cfg.get('roi'),
        card_height=cfg.get('cardHeight', 900),
        settings=cfg.get('settings', {}),
    )

    cam = start_camera(cfg, args.exposure, args.gain, args.lens)
    if args.save_misses:
        os.makedirs(args.save_misses, exist_ok=True)
    if args.display:
        cv2.namedWindow('uber-scan', cv2.WND_PROP_FULLSCREEN)
        cv2.setWindowProperty('uber-scan', cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    print('scanning — ctrl-c to stop')
    spoke_for = None
    frames = 0
    try:
        while True:
            request = cam.capture_request()
            try:
                lores = request.make_array('lores')
                # YUV420's first plane is luma, which is all the gate needs.
                luma = lores[:480, :640]
                if not scanner.should_read(luma):
                    continue
                frame = request.make_array('main')
            finally:
                request.release()

            frames += 1
            out = scanner.read(frame)
            rate, parsed = out['rate'], out['parsed']
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
