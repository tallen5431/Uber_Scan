#!/usr/bin/env python3
"""The box a person drew, when finding the screen automatically will not do.

Everything else here locates the phone by looking for it: the brightest
quadrilateral in the frame, checked for size and shape and then followed. That
is right almost always and useless in the cases where it is wrong — a dashboard
that reflects, a second lit screen, a phone that fills the frame edge to edge
with nothing darker to split against. The scanner then reads an arbitrary strip
of the car, forever, and the only fix on offer was ssh and eight pixel
coordinates guessed off a photograph.

So the driver can draw the box instead. What arrives here is fractions of the
frame — the same numbers whatever size the picture was when they drew it, which
matters because the live view is a 480px JPEG of a 2328px sensor frame — and
what leaves is corners in capture pixels, which is what the calibration is in.

A box drawn by hand means "read exactly this", so it pins the crop as well as
the corners (see PIN_WHOLE). The automatic path deliberately does the opposite:
it treats the quad as the whole phone screen and places a crop inside it per
read, because it knows the quad is a screen and cards differ in height. Nothing
knows that about a hand-drawn box, and second-guessing the person looking at
the picture is how a manual override stops being one.

Deliberately free of numpy, cv2 and pytesseract: the web server writes these
requests, the scanner and the autopilot read them, and a module three processes
share should not need the OCR stack to be importable.
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

# Where the web side leaves a box for the camera side to pick up. A file, for
# the same reason .recalibrate and .viewing are files: the scanner is sometimes
# a child of the web server and sometimes a systemd unit that has never heard of
# it, and a file works identically either way.
REQUEST_PATH = os.path.join(HERE, '.cropbox.json')

# What to write into config.json's `cropBox` for a hand-drawn box: read all of
# what was drawn, rather than deriving a crop inside it.
PIN_WHOLE = [0.0, 0.0, 1.0, 1.0]

# The flag that says the corners were chosen by a person. It turns corner
# tracking off — a tracker judges candidates against a calibrated *screen* and
# would either refuse everything or, after its stall watchdog fires, quietly
# move the box back onto whatever it thinks the screen is. Undoing the override
# is exactly what an override must not do.
MANUAL_KEY = 'manualBox'

# Smaller than this in either direction and it is a mis-tap, not a box: at 5% of
# a 2328px frame the card would be 116px tall against a 380px floor, so there is
# nothing readable inside it and adopting one would only lose the picture the
# driver needs to draw the right box.
MIN_SIDE = 0.05


def parse_request(payload):
    """A request as fractions of the frame, ordered TL, TR, BR, BL.

    Takes either `box` — [x, y, w, h], which is what dragging a rectangle
    gives — or `quad`, four [x, y] corners, for a box that has to be skewed to
    sit on an off-axis screen. Raises ValueError with something a person could
    act on; the caller decides whether that is a 400 or a log line.
    """
    if not isinstance(payload, dict):
        raise ValueError('expected an object with a box or a quad')

    if payload.get('quad') is not None:
        pts = payload['quad']
        if not isinstance(pts, (list, tuple)) or len(pts) != 4:
            raise ValueError('quad needs four corners')
        quad = [_point(p) for p in pts]
    elif payload.get('box') is not None:
        box = payload['box']
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            raise ValueError('box needs x, y, w, h')
        x, y, w, h = [_fraction(n) for n in box]
        if w < MIN_SIDE or h < MIN_SIDE:
            raise ValueError('box is too small to read anything from '
                             '(needs %d%% of the frame each way)' % round(MIN_SIDE * 100))
        # Clamped rather than refused: a drag that ends past the edge of the
        # picture is an ordinary way to say "out to the edge", and the phone
        # screen often does run off the frame.
        x2, y2 = min(1.0, x + w), min(1.0, y + h)
        quad = [[x, y], [x2, y], [x2, y2], [x, y2]]
    else:
        raise ValueError('expected a box or a quad')

    quad = order_quad(quad)
    width, height = _extent(quad)
    if width < MIN_SIDE or height < MIN_SIDE:
        raise ValueError('box is too small to read anything from '
                         '(needs %d%% of the frame each way)' % round(MIN_SIDE * 100))
    return quad


def _fraction(n):
    if isinstance(n, bool) or not isinstance(n, (int, float)):
        raise ValueError('corners must be numbers')
    n = float(n)
    if n != n or n in (float('inf'), float('-inf')):
        raise ValueError('corners must be numbers')
    return min(1.0, max(0.0, n))


def _point(p):
    if not isinstance(p, (list, tuple)) or len(p) != 2:
        raise ValueError('each corner is an [x, y] pair')
    return [_fraction(p[0]), _fraction(p[1])]


def _extent(quad):
    xs = [p[0] for p in quad]
    ys = [p[1] for p in quad]
    return max(xs) - min(xs), max(ys) - min(ys)


def order_quad(points):
    """Corners as top-left, top-right, bottom-right, bottom-left.

    The same rule pipeline.order_quad uses — smallest x+y is the top-left,
    smallest y-x the top-right — kept in pure Python here so the web-facing
    half of this does not need numpy to validate a request.
    """
    pts = [[float(x), float(y)] for x, y in points]
    return [min(pts, key=lambda p: p[0] + p[1]),
            min(pts, key=lambda p: p[1] - p[0]),
            max(pts, key=lambda p: p[0] + p[1]),
            max(pts, key=lambda p: p[1] - p[0])]


def in_pixels(quad, size):
    """Fractions of the frame to pixels in a frame of `size` (width, height)."""
    width, height = float(size[0]), float(size[1])
    return [[p[0] * width, p[1] * height] for p in quad]


def as_fractions(quad, size):
    """The other direction, for showing a stored calibration as a box."""
    width, height = float(size[0]) or 1.0, float(size[1]) or 1.0
    return [[float(x) / width, float(y) / height] for x, y in quad]


def describe(quad):
    """A hand-drawn quad as x/y/w/h fractions, for a log line."""
    xs = [p[0] for p in quad]
    ys = [p[1] for p in quad]
    return '%.2f %.2f %.2f %.2f' % (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def take_request(path=REQUEST_PATH):
    """The pending box, removed as it is read. None when there is not one.

    Removed first, so a request that cannot be parsed is not retried on every
    frame for the rest of the shift, and never fatal: this runs inside the
    capture loop, where nothing is worth stopping reading offers for.
    """
    try:
        if not os.path.exists(path):
            return None
        with open(path) as fh:
            raw = fh.read()
    except (IOError, OSError):
        return None
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    try:
        return parse_request(json.loads(raw))
    except (ValueError, TypeError):
        return None


def write_request(quad, path=REQUEST_PATH):
    """Leave a box for the camera side to pick up.

    The counterpart of the writer in server.js, for a rig being driven from a
    terminal rather than from the live page — `calibrate.py --box` cannot help
    there, because the scanner is holding the camera and calibrating needs a
    frame, while a request needs nothing but this file:

        python3 -c 'import sys; sys.path.insert(0, "rpi"); import cropbox
        cropbox.write_request(cropbox.parse_request({"box": [0.1, .35, .8, .3]}))'

    Written to a temporary name and renamed, because the reader may be looking
    at exactly this path at exactly this moment and half a JSON object parses
    as nothing at all.
    """
    tmp = path + '.part'
    with open(tmp, 'w') as fh:
        json.dump({'quad': quad}, fh)
    os.replace(tmp, path)


def apply_to_config(config, quad, size):
    """Put a hand-drawn box into a config dict, in place, and return it.

    Three things move together and they have to stay together: the corners, the
    pin that says read all of what was drawn, and the flag that says a person
    chose it. `trackedQuad` goes, because it is where the screen had drifted to
    relative to corners that no longer exist.
    """
    config['quad'] = in_pixels(quad, size)
    config['cropBox'] = list(PIN_WHOLE)
    config[MANUAL_KEY] = True
    config.pop('trackedQuad', None)
    return config


def clear_in_config(config):
    """Undo the above, leaving the corners as the starting point for a re-find."""
    config.pop(MANUAL_KEY, None)
    config.pop('cropBox', None)
    config.pop('trackedQuad', None)
    return config
