#!/usr/bin/env python3
"""Live aiming preview, in a browser, from any device on the network.

    python3 rpi/preview.py                    # http://<pi>:8081/
    python3 rpi/preview.py --image frame.png  # same overlay on a still, off-Pi

Aiming a camera you cannot see is the worst part of building this rig, and a
CSI camera is invisible to browsers, so `scan.html` will never show it. This
streams the frame with the detected phone screen drawn on it and, more usefully,
the one number that decides whether any of it will work: how many real sensor
pixels tall the offer card is.

Mount the bracket with this open on your phone, move until the number is
comfortably above the floor, then run calibrate.py.
"""

import argparse
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline as PL
from calibrate import DEFAULT_ROI, MIN_CARD_PIXELS, card_source_pixels

GREEN = (100, 201, 23)
RED = (75, 50, 240)
AMBER = (36, 165, 245)

PAGE = b"""<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>Uber Scan camera</title>
<style>html,body{margin:0;background:#0b0f14;color:#eef4fb;font-family:system-ui,sans-serif}
img{width:100%;height:auto;display:block}p{padding:10px 14px;font-size:14px;line-height:1.5;margin:0}
b{color:#17c964}</style>
<img src="/stream.mjpg"><p>Move the camera until the card height reads
<b>green</b>, then run <code>calibrate.py</code>. Fill the frame with the phone.</p>
"""


class Source:
    """A still or a camera, behind one method."""

    def __init__(self, image=None, size=(2328, 1748)):
        self.cam = None
        self.still = None
        if image:
            self.still = cv2.imread(image)
            if self.still is None:
                sys.exit('could not read %s' % image)
        else:
            from picamera2 import Picamera2
            self.cam = Picamera2()
            # Preview only, so a modest size keeps the quad search cheap. The
            # measurement is scaled back up to the capture size that scan_pi.py
            # will really use, or the number would flatter the mount.
            self.preview_size = (1164, 874)
            self.capture_size = size
            self.cam.configure(self.cam.create_video_configuration(
                main={'size': self.preview_size, 'format': 'RGB888'},
                raw={'size': size}))
            self.cam.start()
            time.sleep(1.0)

    @property
    def scale_to_capture(self):
        if self.cam is None:
            return 1.0
        return float(self.capture_size[1]) / float(self.preview_size[1])

    def frame(self):
        if self.still is not None:
            return self.still.copy()
        return self.cam.capture_array('main')

    def close(self):
        if self.cam is not None:
            self.cam.stop()
            self.cam.close()


def annotate(frame, scale_to_capture):
    """Draw the detected screen and the number that decides everything."""
    quad = PL.detect_screen_quad(frame)
    out = frame.copy()

    if quad is None:
        cv2.putText(out, 'no screen found', (16, 44),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1, RED, 3)
        cv2.putText(out, 'is the phone lit and in frame?', (16, 86),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, RED, 2)
        return out, None

    card_px = int(round(card_source_pixels(quad, DEFAULT_ROI) * scale_to_capture))
    ok = card_px >= MIN_CARD_PIXELS
    colour = GREEN if ok else (AMBER if card_px >= MIN_CARD_PIXELS * 0.75 else RED)

    cv2.polylines(out, [quad.astype(np.int32)], True, colour, 3)
    # The card sits in the lower part of the screen; show what will be read.
    top = quad[0] + (quad[3] - quad[0]) * DEFAULT_ROI[1]
    top_r = quad[1] + (quad[2] - quad[1]) * DEFAULT_ROI[1]
    cv2.line(out, tuple(top.astype(int)), tuple(top_r.astype(int)), colour, 2)

    cv2.rectangle(out, (0, 0), (out.shape[1], 92), (20, 27, 36), -1)
    cv2.putText(out, 'card %d px' % card_px, (14, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 1.2, colour, 3)
    cv2.putText(out, 'need %d+' % MIN_CARD_PIXELS if not ok else 'good (need %d+)' % MIN_CARD_PIXELS,
                (14, 78), cv2.FONT_HERSHEY_SIMPLEX, 0.7, colour, 2)
    return out, card_px


class Handler(BaseHTTPRequestHandler):
    source = None
    lock = threading.Lock()

    def log_message(self, *a):
        pass                      # the stream would fill the terminal

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(PAGE)))
            self.end_headers()
            self.wfile.write(PAGE)
        elif self.path == '/snapshot.jpg':
            with self.lock:
                frame = self.source.frame()
            ok, jpg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
            self.send_response(200)
            self.send_header('Content-Type', 'image/jpeg')
            self.send_header('Content-Length', str(len(jpg)))
            self.end_headers()
            self.wfile.write(jpg.tobytes())
        elif self.path == '/stream.mjpg':
            self.stream()
        else:
            self.send_error(404)

    def stream(self):
        self.send_response(200)
        self.send_header('Age', '0')
        self.send_header('Cache-Control', 'no-cache, private')
        self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
        self.end_headers()
        try:
            while True:
                with self.lock:
                    frame = self.source.frame()
                shown, _ = annotate(frame, self.source.scale_to_capture)
                ok, jpg = cv2.imencode('.jpg', shown, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if not ok:
                    continue
                data = jpg.tobytes()
                self.wfile.write(b'--FRAME\r\n')
                self.send_header('Content-Type', 'image/jpeg')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                self.wfile.write(b'\r\n')
                time.sleep(0.1)          # ~10fps is plenty for aiming
        except (BrokenPipeError, ConnectionResetError):
            pass                          # the phone navigated away


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8081)
    ap.add_argument('--image', help='annotate a still instead of the camera')
    ap.add_argument('--save', metavar='PATH',
                    help='write one annotated frame and exit, no server')
    args = ap.parse_args()

    Handler.source = Source(args.image)

    if args.save:
        shown, card_px = annotate(Handler.source.frame(), Handler.source.scale_to_capture)
        cv2.imwrite(args.save, shown)
        print('wrote %s  (card %s px)' % (args.save, card_px))
        Handler.source.close()
        return

    server = ThreadingHTTPServer(('0.0.0.0', args.port), Handler)
    print('camera preview on http://<this-pi>:%d/' % args.port)
    print('open it on the phone and move the mount until the number goes green')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        Handler.source.close()


if __name__ == '__main__':
    main()
