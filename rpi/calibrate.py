#!/usr/bin/env python3
"""One-time calibration. The mount is fixed, so the corners of the phone screen
only need finding once — after that every frame reuses the same homography.

    python3 rpi/calibrate.py                      # grab a frame from the camera
    python3 rpi/calibrate.py --from-image f.png   # or calibrate from a still

Put a live offer (or any bright screen) on the phone first, then run it. The
screen is found automatically as the largest bright quadrilateral; check the
written preview and fall back to --corners if the mount sees something brighter.
"""

import argparse
import json
import os
import sys

import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline as PL

DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

# Uber draws the offer card against the bottom of the screen. Cropping to it
# roughly halves the pixels tesseract walks, for no loss of accuracy.
DEFAULT_ROI = [0.02, 0.48, 0.96, 0.50]

# Two numbers, because they mean different things. 350px is where reading
# measurably stops working; below it no setting helps. 450px is where there is
# comfortable margin for a dimmer or busier card. Refusing to calibrate anywhere
# between the two would be enforcing a preference as though it were a limit.
MIN_CARD_PIXELS = 380          # below this, do not bother
GOOD_CARD_PIXELS = 450         # above this, no notes

# The two IMX519 modes that see the whole sensor. 1280x720 and 1920x1080 are
# cropped windows (2560x1440 and 3840x2160 respectively), so they cut field of
# view rather than resolution and can put the phone partly out of frame.
FULL_FOV_MODES = {'2328x1748': (2328, 1748), '4656x3496': (4656, 3496)}


def grab_from_camera(size, lens=None):
    """One sharp frame, plus the lens position that made it sharp.

    The scanner pins focus rather than tracking it, so the focus has to be
    decided once — here — and recorded. Otherwise every run starts at whatever
    the lens happens to be resting at, which is the blurry default.
    """
    import time
    from picamera2 import Picamera2

    cam = Picamera2()
    cam.configure(cam.create_still_configuration(main={'size': size, 'format': 'RGB888'}))
    cam.start()
    try:
        time.sleep(2)          # let auto-exposure settle before the one frame we keep
        lens_position = None

        if 'AfMode' in cam.camera_controls:
            from libcamera import controls
            if lens is not None:
                cam.set_controls({'AfMode': controls.AfModeEnum.Manual, 'LensPosition': lens})
                time.sleep(1.5)
                lens_position = lens
            else:
                print('running autofocus...')
                cam.set_controls({'AfMode': controls.AfModeEnum.Auto})
                try:
                    cam.autofocus_cycle()
                except Exception as e:
                    print('  autofocus cycle failed (%s); using whatever it settled on' % e)
                time.sleep(0.5)
        else:
            print('no autofocus on this module; focus is set by the mount distance')

        request = cam.capture_request()
        try:
            frame = request.make_array('main')
            if lens_position is None:
                lens_position = request.get_metadata().get('LensPosition')
        finally:
            request.release()

        if lens_position:
            print('focus locked at %.2f dioptres (about %.0f cm)'
                  % (lens_position, 100.0 / lens_position))
        return frame, lens_position
    finally:
        cam.stop()
        cam.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--from-image', help='calibrate from a saved frame instead of the camera')
    ap.add_argument('--config', default=DEFAULT_CONFIG)
    ap.add_argument('--mode', choices=sorted(FULL_FOV_MODES), default='2328x1748',
                    help='sensor mode; both see the full frame. 2328x1748 is 2x2 '
                         'binned at 30fps, 4656x3496 is full resolution at 9fps')
    ap.add_argument('--card-height', type=int, default=900,
                    help='warp height; 900 is the measured speed/accuracy sweet spot')
    ap.add_argument('--corners', help='manual override: x1,y1,x2,y2,x3,y3,x4,y4 clockwise from top-left')
    ap.add_argument('--full-screen', action='store_true', help='read the whole screen, not just the card')
    ap.add_argument('--lens', type=float, default=None,
                    help='pin focus in dioptres (4.0 = 25cm) instead of autofocusing')
    args = ap.parse_args()

    width, height = FULL_FOV_MODES[args.mode]
    lens_position = args.lens
    if args.from_image:
        frame = cv2.imread(args.from_image)
    else:
        frame, lens_position = grab_from_camera((width, height), args.lens)
    if frame is None:
        sys.exit('could not read a frame')

    if args.corners:
        nums = [float(n) for n in args.corners.replace(' ', '').split(',')]
        if len(nums) != 8:
            sys.exit('--corners needs 8 numbers')
        quad = PL.order_quad(__import__('numpy').array(nums, dtype='float32').reshape(4, 2))
    else:
        quad = PL.detect_screen_quad(frame)
        if quad is None:
            sys.exit('no screen found — is the phone lit and in frame? else pass --corners')

    roi = None if args.full_screen else DEFAULT_ROI
    config = {
        'quad': [[float(x), float(y)] for x, y in quad],
        'roi': roi,
        'cardHeight': args.card_height,
        'capture': {'width': width, 'height': height},
        'lensPosition': lens_position,
        'settings': {'target': 25, 'band': 15, 'costPerMile': 0.30,
                     'pad': 0, 'secondsPerItem': 0},
    }
    with open(args.config, 'w') as fh:
        json.dump(config, fh, indent=2)

    # Write what the OCR engine will actually be handed, so a bad mount is
    # obvious before it costs a shift's worth of missed offers.
    preview = PL.preprocess(PL.crop(PL.warp(frame, quad, args.card_height), roi))
    preview_path = os.path.splitext(args.config)[0] + '-preview.png'
    cv2.imwrite(preview_path, preview)

    print('wrote %s' % args.config)
    print('corners: %s' % config['quad'])
    print('preview: %s  (%dx%d — the exact image tesseract will read)'
          % (preview_path, preview.shape[1], preview.shape[0]))

    # How big the card actually is on the sensor decides whether this works at
    # all. 2328x1748 is 2x2 binned, so the card has half the pixel density the
    # sensor's headline resolution suggests, and no amount of upscaling later
    # recovers detail the mount never captured.
    card_px = card_source_pixels(quad, roi)
    print('\ncard height on the sensor: %d px' % card_px)
    if card_px < MIN_CARD_PIXELS:
        print('  TOO SMALL — reading stops working below about %d px.' % MIN_CARD_PIXELS)
        print('  Move the camera closer so the phone fills more of the frame,')
        print('  or re-run with --mode 4656x3496 for double the detail at 9fps.')
    elif card_px < GOOD_CARD_PIXELS:
        print('  workable, but thin on margin (%d px against a comfortable %d)'
              % (card_px, GOOD_CARD_PIXELS))
    else:
        print('  comfortable (floor is about %d px)' % MIN_CARD_PIXELS)

    print('\nCheck the preview is a straight-on, sharp, glare-free offer card.')


def card_source_pixels(quad, roi):
    """Height, in real sensor pixels, of the region that gets OCR'd."""
    import numpy as np
    left = np.linalg.norm(quad[3] - quad[0])
    right = np.linalg.norm(quad[2] - quad[1])
    screen_px = (left + right) / 2.0
    return int(round(screen_px * (roi[3] if roi else 1.0)))


if __name__ == '__main__':
    main()
