#!/usr/bin/env python3
"""Measure the pipeline on your own hardware. Numbers from a laptop mean little;
a Pi 4 is a different machine, so run this before tuning anything.

    python3 rpi/bench.py --image frame.png          # sweep sizes on a saved frame
    python3 rpi/bench.py --image frame.png --quick  # just the configured setup
"""

import argparse
import json
import os
import statistics
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline as PL

DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
CARD_ROI = [0.02, 0.48, 0.96, 0.50]


def timed(scanner, frame, n):
    stages = {'warp': [], 'prep': [], 'ocr': [], 'parse': [], 'total': []}
    parsed = None
    for _ in range(n):
        # A fixed clock keeps the crop-recovery pass out of the timings. It is
        # real work, but it happens once when a crop has gone wrong, and
        # averaging it into the steady-state read cost would misreport both.
        out = scanner.read(frame, now=0.0)
        parsed = out['parsed']
        for k in stages:
            stages[k].append(out['ms'][k])
    return {k: statistics.median(v) for k, v in stages.items()}, parsed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--image', required=True)
    ap.add_argument('--config', default=DEFAULT_CONFIG)
    ap.add_argument('--repeat', type=int, default=5)
    ap.add_argument('--quick', action='store_true')
    args = ap.parse_args()

    frame = cv2.imread(args.image)
    if frame is None:
        sys.exit('could not read %s' % args.image)

    quad = roi = None
    card_height = 900
    if os.path.exists(args.config):
        cfg = json.load(open(args.config))
        quad = np.array(cfg['quad'], dtype=np.float32)
        roi = cfg.get('roi')
        card_height = cfg.get('cardHeight', 900)
    else:
        quad = PL.detect_screen_quad(frame)
        roi = CARD_ROI
        print('no config; using an auto-detected screen quad\n')

    print('frame %dx%d, median of %d reads\n' % (frame.shape[1], frame.shape[0], args.repeat))

    if args.quick:
        combos = [(card_height, roi, PL.OCR_CARD_HEIGHT, 'configured')]
    else:
        combos = ([(h, None, PL.OCR_CARD_HEIGHT, 'whole screen') for h in (1400, 1100, 900, 700)] +
                  [(h, CARD_ROI, PL.OCR_CARD_HEIGHT, 'card only') for h in (1400, 1100, 900, 700, 500)] +
                  # The read size is the axis that matters most and the one
                  # nobody expects: the same crop, handed over larger, reads
                  # things it could not read before. 0 means "as cropped".
                  [(900, CARD_ROI, o, 'read size') for o in (0, 600, 900, 1200, 1500)])

    print('%-14s %-7s %-7s %-9s %-7s %-7s %-8s  %s'
          % ('crop', 'height', 'read', 'pixels', 'warp', 'ocr', 'total', 'result'))
    for height, r, ocr_height, label in combos:
        scanner = PL.Scanner(quad=quad, roi=r, card_height=height, ocr_height=ocr_height)
        ms, parsed = timed(scanner, frame, args.repeat)
        shape = PL.fit_for_ocr(PL.crop(PL.warp(frame, quad, height), r), ocr_height).shape
        ok = 'OK' if parsed['complete'] else 'MISS'
        print('%-14s %-7d %-7s %-9s %-7.0f %-7.0f %-8.0f  %s pay=%s min=%s mi=%s%s'
              % (label, height, ocr_height or 'as-is', '%dx%d' % (shape[1], shape[0]),
                 ms['warp'], ms['ocr'], ms['total'], ok, parsed['pay'], parsed['minutes'],
                 parsed['miles'], ' (recovered)' if parsed['milesCorrected'] else ''))

    print('\nPick the smallest warp height that still reads, then leave margin: the '
          'card is smaller in frame when the phone sits further away.')
    print('Read size buys accuracy, not detail — it cannot recover what the mount '
          'never captured, but tesseract needs about a 20px x-height to work at all.')


if __name__ == '__main__':
    main()
