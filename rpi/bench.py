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
        out = scanner.read(frame)
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
        combos = [(card_height, roi, 'configured')]
    else:
        combos = ([(h, None, 'whole screen') for h in (1400, 1100, 900, 700)] +
                  [(h, CARD_ROI, 'card only') for h in (1400, 1100, 900, 700, 500)])

    print('%-14s %-7s %-8s %-7s %-7s %-8s  %s'
          % ('crop', 'height', 'pixels', 'warp', 'ocr', 'total', 'read'))
    for height, r, label in combos:
        scanner = PL.Scanner(quad=quad, roi=r, card_height=height)
        ms, parsed = timed(scanner, frame, args.repeat)
        shape = PL.crop(PL.warp(frame, quad, height), r).shape
        ok = 'OK' if parsed['complete'] else 'MISS'
        print('%-14s %-7d %-8s %-7.0f %-7.0f %-8.0f  %s pay=%s min=%s mi=%s%s'
              % (label, height, '%dx%d' % (shape[1], shape[0]), ms['warp'], ms['ocr'],
                 ms['total'], ok, parsed['pay'], parsed['minutes'], parsed['miles'],
                 ' (recovered)' if parsed['milesCorrected'] else ''))

    print('\nPick the smallest height that still reads, then leave margin: the '
          'card is smaller in frame when the phone sits further away.')


if __name__ == '__main__':
    main()
