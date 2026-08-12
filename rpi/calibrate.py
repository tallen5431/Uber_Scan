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


def grab_from_camera(size):
    from picamera2 import Picamera2
    cam = Picamera2()
    cam.configure(cam.create_still_configuration(main={'size': size, 'format': 'RGB888'}))
    cam.start()
    try:
        import time
        time.sleep(2)          # let auto-exposure settle before the one frame we keep
        return cam.capture_array('main')
    finally:
        cam.stop()
        cam.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--from-image', help='calibrate from a saved frame instead of the camera')
    ap.add_argument('--config', default=DEFAULT_CONFIG)
    ap.add_argument('--width', type=int, default=2328)
    ap.add_argument('--height', type=int, default=1748)
    ap.add_argument('--card-height', type=int, default=900,
                    help='warp height; 900 is the measured speed/accuracy sweet spot')
    ap.add_argument('--corners', help='manual override: x1,y1,x2,y2,x3,y3,x4,y4 clockwise from top-left')
    ap.add_argument('--full-screen', action='store_true', help='read the whole screen, not just the card')
    args = ap.parse_args()

    frame = cv2.imread(args.from_image) if args.from_image \
        else grab_from_camera((args.width, args.height))
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
        'capture': {'width': args.width, 'height': args.height},
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
    print('\nCheck the preview is a straight-on, sharp, glare-free offer card.')


if __name__ == '__main__':
    main()
