"""Tests for what calibration is allowed to touch.

    python3 rpi/test_calibrate.py

Calibrating decides where the phone is. It had also been deciding what an hour
of the driver's time is worth, because it wrote a fresh dict over config.json —
and there is no second copy of those settings anywhere on the Pi. That regressed
once and went unnoticed, because the only way into the code was a camera, and a
test that needs a camera is a test nobody runs.
"""

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import calibrate as CB
import offer_parser as P

ok = bad = 0


def eq(name, got, want):
    global ok, bad
    if got == want:
        ok += 1
    else:
        bad += 1
        print('FAIL  %s: got %r want %r' % (name, got, want))


def ok_(name, cond):
    eq(name, bool(cond), True)


QUAD = [[100, 20], [900, 22], [905, 1600], [98, 1598]]

# What a driver's file looks like after a season of use: their own money, an
# exposure someone measured, and the tracker's running position.
LIVED_IN = {
    'settings': {'target': 32, 'band': 10, 'costPerMile': 0.62,
                 'pad': 3, 'secondsPerItem': 45},
    'exposureTime': 33333,
    'exposureWhy': 'measured against this screen',
    'analogueGain': 4.1,
    'quad': [[0, 0], [10, 0], [10, 10], [0, 10]],
    'trackedQuad': [[5, 5], [15, 5], [15, 15], [5, 15]],
    'cardHeight': 900,
}

# --- re-aiming the camera must not touch the driver's money -----------------
out = CB.calibrated_config(LIVED_IN, QUAD, None, 900, (2328, 1748), 4.0)
eq('the target survives', out['settings']['target'], 32)
eq('the running cost survives', out['settings']['costPerMile'], 0.62)
eq('the pad survives', out['settings']['pad'], 3)
eq('the shopping allowance survives', out['settings']['secondsPerItem'], 45)
eq('the whole settings block is untouched', out['settings'], LIVED_IN['settings'])

# The verdict those settings produce is the point of keeping them. On the very
# offer calibration reads back to prove itself, the driver's numbers and the
# defaults disagree about whether to take the job.
offer = P.parse('$16.05 23 min (8.4 mi) total')
theirs = P.rate(offer, out['settings'])
defaults = P.rate(offer, CB.DEFAULT_SETTINGS)
eq('their settings call this offer a pass', theirs['state'], 'no')
eq('...and the defaults call it an accept', defaults['state'], 'go')
ok_('so losing them inverts the verdict', theirs['state'] != defaults['state'])

# --- the measured exposure survives too -------------------------------------
# It describes the phone's backlight, not where the camera is pointing, so
# re-aiming does not invalidate it.
eq('the measured exposure survives', out['exposureTime'], 33333)
eq('...and why it was chosen', out['exposureWhy'], 'measured against this screen')
eq('the gain survives', out['analogueGain'], 4.1)

# --- but the geometry is replaced, and the drift discarded ------------------
eq('the corners are the new ones', out['quad'], [[100.0, 20.0], [900.0, 22.0],
                                                 [905.0, 1600.0], [98.0, 1598.0]])
ok_('the tracker position is dropped', 'trackedQuad' not in out)
eq('the capture size is recorded', out['capture'], {'width': 2328, 'height': 1748})
eq('the lens position is recorded', out['lensPosition'], 4.0)
eq('the crop is left to the scanner by default', out['cropBox'], None)
eq('...and pinned only when asked',
   CB.calibrated_config({}, QUAD, CB.WHOLE_VIEW, 900, (2328, 1748), None)['cropBox'],
   CB.WHOLE_VIEW)

# --- a first calibration still gets sensible settings -----------------------
fresh = CB.calibrated_config({}, QUAD, None, 900, (2328, 1748), None)
eq('a new rig gets the defaults', fresh['settings'], CB.DEFAULT_SETTINGS)
ok_('...as its own copy, not a shared one',
    fresh['settings'] is not CB.DEFAULT_SETTINGS)
fresh['settings']['target'] = 99
eq('...so editing one config cannot move the defaults',
   CB.DEFAULT_SETTINGS['target'], 25)

# --- reading the existing file ----------------------------------------------
work = tempfile.mkdtemp()
try:
    path = os.path.join(work, 'config.json')
    eq('a missing file reads as empty', CB.load_existing(path), {})

    with open(path, 'w') as fh:
        json.dump(LIVED_IN, fh)
    eq('an existing file reads back', CB.load_existing(path)['settings']['target'], 32)

    # Half-written or hand-edited should not stop a driver re-aiming the camera.
    with open(path, 'w') as fh:
        fh.write('{"settings": {"target": 32')
    eq('a torn file reads as empty rather than exploding', CB.load_existing(path), {})

    with open(path, 'w') as fh:
        fh.write('[1, 2, 3]')
    eq('so does a file that is not an object', CB.load_existing(path), {})
finally:
    shutil.rmtree(work, ignore_errors=True)

# --- the capture size has to match the frame the corners came from ----------
# --from-image took its size from --mode while detecting corners in the still's
# own pixel space. An rpicam-still is 4656x3496 by default and --mode defaults
# to 2328x1748, so the scanner warped a quad twice the size of the frames it was
# given and read empty text off every one — silently, permanently, because the
# tracker judges candidates against the calibrated size and refuses the real
# screen on every check while the health line reports "corners held".
#
# --from-image needs no camera, so this runs the real command end to end.
import numpy as np
import cv2
import track as TR

work = tempfile.mkdtemp()
try:
    # A lit phone screen on a dark seat, at a size that is not any --mode.
    STILL_W, STILL_H = 1400, 1050
    frame = np.full((STILL_H, STILL_W, 3), 18, np.uint8)
    cv2.rectangle(frame, (380, 90), (1010, 960), (238, 240, 242), -1)
    still = os.path.join(work, 'still.png')
    cv2.imwrite(still, frame)

    cfg_path = os.path.join(work, 'config.json')
    with open(cfg_path, 'w') as fh:
        json.dump(LIVED_IN, fh)

    # Run the real command, with its own reporting muffled so a failure here
    # reads as a test failure rather than as a wall of calibration output.
    argv, out = sys.argv, sys.stdout
    sys.argv = ['calibrate', '--from-image', still, '--config', cfg_path]
    try:
        sys.stdout = open(os.devnull, 'w')
        CB.main()
    finally:
        sys.stdout.close()
        sys.stdout, sys.argv = out, argv

    written = json.load(open(cfg_path))
    eq('the recorded size is the still, not the --mode default',
       written['capture'], {'width': STILL_W, 'height': STILL_H})
    corners = np.array(written['quad'], dtype=np.float32)
    ok_('...so every corner falls inside the frame it was measured on',
        corners[:, 0].max() <= STILL_W and corners[:, 1].max() <= STILL_H)
    eq('and the driver\'s money came through the real command intact',
       written['settings'], LIVED_IN['settings'])
    ok_('...with the drift discarded', 'trackedQuad' not in written)

    # The failure this prevents, as the tracker would have seen it: corners
    # measured on a frame of one size are refused against a screen of another,
    # on every check, forever.
    eq('a quad from a wrongly-sized frame never matches',
       TR.same_size(corners / 2.0, corners), False)
    eq('...while the right one does', TR.same_size(corners, corners), True)
finally:
    shutil.rmtree(work, ignore_errors=True)


# --- the frame that gets written down is a frame that was checked ------------
# aim() spends three seconds proving the mount is big enough and sharp enough,
# several frames running — and then calibration grabbed one more frame and
# calibrated on *that*, unchecked. The gap between them is where a hand comes
# off the bracket, the phone dims a step, or the lens hunts once more. A bad
# read costs one offer; a bad quad is what every read of the shift is cropped
# from, and the only sign the driver gets is "no offer on the screen to test
# against" — which is also what a perfect calibration says when the phone is
# idle. So the frame kept has to clear the same floors aiming did.
import io
import contextlib

import autopilot as AP

AP.STABLE_INTERVAL = 0            # the checks are about which frame, not waiting


def scene(box=(380, 90, 1010, 960), blur=0):
    """A lit phone on a dark seat, with enough detail to have a focus at all."""
    f = np.full((1050, 1400, 3), 18, np.uint8)
    x0, y0, x1, y1 = box
    cv2.rectangle(f, (x0, y0), (x1, y1), (238, 240, 242), -1)
    for i in range(y0 + 10, y1 - 10, 26):        # text-ish bars
        cv2.rectangle(f, (x0 + 20, i), (x1 - 20, i + 10), (20, 20, 24), -1)
    return cv2.GaussianBlur(f, (blur, blur), 0) if blur else f


GOOD = scene()                      # 435 px, sharp 6512
SOFT = scene(blur=31)               # 434 px, sharp 51 — under the floor of 60
FAR = scene(box=(500, 250, 930, 850))   # 300 px, under the floor of 380
DARK = np.full((1050, 1400, 3), 12, np.uint8)


class FakeSource(object):
    """Hands out a fixed run of frames, repeating the last one forever."""

    scale_to_capture = 1.0

    def __init__(self, frames):
        self.frames = list(frames)
        self.taken = 0

    def frame(self):
        f = self.frames[min(self.taken, len(self.frames) - 1)]
        self.taken += 1
        return f


def why_not(said):
    """The complaint, or '' if there wasn't one — so a check that should have
    failed reports as a failure rather than crashing the rest of the file."""
    return said[0]['message'] if said else ''


def keep(frames, drawn=None, floor=None):
    """Returns (frame, quad, sharp, messages)."""
    said = io.StringIO()
    src = FakeSource(frames)
    with contextlib.redirect_stdout(said):
        frame, quad, sharp = AP._frame_to_keep(src, True, drawn, floor)
    lines = [json.loads(l) for l in said.getvalue().splitlines() if l.strip()]
    return frame, quad, sharp, lines


frame, quad, sharp, said = keep([GOOD])
ok_('a good frame is kept', frame is not None)
ok_('...it is the frame that was looked at', frame is GOOD)
ok_('...with the corners found in that same frame', quad is not None)
eq('...and nothing is complained about', said, [])

# The one that matters: aiming passed, then the frame went soft. Every earlier
# version wrote this down and called it calibrated.
frame, quad, sharp, said = keep([SOFT] * AP.CALIBRATE_TRIES)
ok_('a frame too soft to read is refused, not written', frame is None)
eq('...loudly', [m['phase'] for m in said], ['error'])
ok_('...saying which way it went wrong', 'soft' in why_not(said))
ok_('...and that nothing was written', 'Nothing was written' in why_not(said))

frame, quad, sharp, said = keep([FAR] * AP.CALIBRATE_TRIES)
ok_('a screen that drifted out of range is refused too', frame is None)
ok_('...by distance, in the words for distance',
    'further away' in why_not(said))
ok_('...with the measurement in it', '300 px' in why_not(said))

frame, quad, sharp, said = keep([DARK] * AP.CALIBRATE_TRIES)
ok_('a frame with no screen in it is refused', frame is None)
ok_('...as a lost screen', 'lost the screen' in why_not(said))

# Looking at several is the point of looking at several: one bad frame in the
# run must not decide the shift, and a taking-the-first rule would let it.
frame, quad, sharp, said = keep([SOFT, SOFT, GOOD, SOFT])
ok_('one soft frame does not decide the calibration', frame is GOOD)
eq('...and it is not reported as a problem', said, [])

frame, quad, sharp, said = keep([FAR, GOOD])
ok_('nor does one frame at the wrong distance', frame is GOOD)

# ...and of several good ones, the sharpest, because there is no reason to
# keep a worse frame when a better one is in hand.
blurred = scene(blur=9)             # 434 px, sharp 424 — passes, but not best
frame, quad, sharp, said = keep([blurred, GOOD, blurred])
ok_('the sharpest of the good frames is the one kept', frame is GOOD)

# A hand-drawn box exists *because* the detector could not find the phone.
# Refusing it would send the driver back to the phase that already failed them.
DRAWN = [[0.27, 0.09], [0.72, 0.09], [0.72, 0.91], [0.27, 0.91]]
frame, quad, sharp, said = keep([SOFT] * AP.CALIBRATE_TRIES, drawn=DRAWN)
ok_('a box drawn by hand is never refused for being soft', frame is not None)
eq('...and is not complained about', said, [])
frame, quad, sharp, said = keep([DARK] * AP.CALIBRATE_TRIES, drawn=DRAWN)
ok_('...nor for there being no screen the detector can see', frame is not None)
frame, quad, sharp, said = keep([SOFT, GOOD, SOFT], drawn=DRAWN)
ok_('...but it still gets the sharpest frame going', frame is GOOD)
ok_('...pinned to the corners the person drew, not to a detection',
    quad is not None and abs(float(quad[0][0]) - 0.27 * 1400) < 1.5)

# --min-card is the escape hatch for a mount that cannot get closer. It has to
# mean the same thing here as it does while aiming, or the two phases disagree
# and the driver is told to aim at something calibration will refuse.
frame, quad, sharp, said = keep([FAR] * AP.CALIBRATE_TRIES, floor=250)
ok_('a lowered floor is honoured while calibrating too', frame is FAR)
frame, quad, sharp, said = keep([GOOD] * AP.CALIBRATE_TRIES, floor=600)
ok_('...and a raised one is as well', frame is None)

# --- the one frame calibration keeps comes through the shared opener --------
#
# This function had no test because the only way in was a camera, which is the
# reason given at the top of this file for the last thing that regressed here.
# It is also the worst place in the project to go its own way: a calibration is
# permanent, and every later read is warped through the corners decided from
# this one frame.
#
# A fake `camera` module in sys.modules is enough, because the function asks
# for it by name at call time. picamera2 is stubbed to EXPLODE if anything
# constructs it directly, which is exactly what this function used to do.
class _Boom(object):
    def __init__(self, *a, **k):
        raise AssertionError('calibration opened the camera itself, '
                             'bypassing camera.open_camera()')


class _FakeRequest(object):
    def __init__(self, meta):
        self.meta = meta
        self.released = False

    def make_array(self, _name):
        return 'THE-FRAME'

    def get_metadata(self):
        return self.meta

    def release(self):
        self.released = True


class _FakeCam(object):
    def __init__(self, meta=None):
        self.started = self.stopped = self.closed = False
        self.configured = None
        self.request = _FakeRequest(meta or {})

    def create_still_configuration(self, **kw):
        return kw

    def configure(self, cfg):
        self.configured = cfg

    def start(self):
        self.started = True

    def capture_request(self):
        return self.request

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


class _FakeCameraModule(object):
    """Stands in for rpi/camera.py, recording what calibration asked of it."""

    CameraBusy = type('CameraBusy', (RuntimeError,), {})

    def __init__(self, focus, cam=None, busy=False):
        self.focus, self.cam, self.busy = focus, cam or _FakeCam(), busy
        self.opened = False
        self.focus_calls = []

    def open_camera(self, prefer_autofocus=True):
        if self.busy:
            raise self.CameraBusy('the camera is already in use by this project (pid 42)')
        self.opened = True
        return self.cam, self.focus

    def apply_focus(self, cam, focus, lens=None):
        self.focus_calls.append((focus, lens))
        if not focus.get('supported'):
            return None
        return lens if lens is not None else 3.5


def _with_camera(module, fn):
    saved_cam = sys.modules.get('camera')
    saved_pi = sys.modules.get('picamera2')
    sys.modules['camera'] = module
    sys.modules['picamera2'] = type('m', (), {'Picamera2': _Boom})
    try:
        return fn()
    finally:
        for name, was in (('camera', saved_cam), ('picamera2', saved_pi)):
            if was is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = was


AF = {'supported': True, 'tuning': '/x/imx519_af.json', 'reason': None}
NO_AF = {'supported': False, 'tuning': '/x/imx519.json',
         'reason': 'the tuning file for imx519 has no autofocus algorithm'}

fake = _FakeCameraModule(AF)
# Caught rather than left to propagate: a suite that dies on its own stub
# reports a stack trace where it should report a failing check, and the next
# person reads that as the test being broken rather than the code.
try:
    frame, lens_at = _with_camera(fake, lambda: CB.grab_from_camera((2328, 1748)))
    went_around = None
except AssertionError as e:                                   # noqa: BLE001
    frame, lens_at, went_around = None, None, str(e)
ok_('calibration does not open the camera itself (%s)' % (went_around or 'it did not'),
    went_around is None)
ok_('calibration opens the camera through the shared opener', fake.opened)
eq('...and keeps the frame it was given', frame, 'THE-FRAME')
# The lock, the tuning file and the empty-camera-list message all live in
# open_camera. Going around it skipped every one of them.
ok_('...releasing the request whatever happens', fake.cam.request.released)
ok_('...and shutting the camera down after', fake.cam.stopped and fake.cam.closed)
# Focus is decided by the shared rule, not by a second copy of it here. The
# copy that lived here asked only whether the AfMode control existed, which a
# fixed-focus module and a broken tuning both answer yes to.
eq('...asking the shared rule to pin or autofocus', len(fake.focus_calls), 1)
eq('...and recording what it actually settled on', lens_at, 3.5)

pinned = _FakeCameraModule(AF)
_frame, lens_at = _with_camera(pinned, lambda: CB.grab_from_camera((2328, 1748), lens=4.0))
eq('a pinned lens is passed through to the shared rule', pinned.focus_calls[0][1], 4.0)
eq('...and is what gets recorded', lens_at, 4.0)

# A module whose lens cannot be driven must not have a focus invented for it.
# The old code read LensPosition back off the metadata regardless, so a dead
# lens resting at its blurry default was written into the config as the focus
# to pin for every read from then on.
blind = _FakeCameraModule(NO_AF, cam=_FakeCam(meta={}))
_frame, lens_at = _with_camera(blind, lambda: CB.grab_from_camera((2328, 1748)))
eq('a module that cannot focus records no lens position', lens_at, None)

# ...and the camera being busy reaches the driver as this project's own
# sentence naming the pid, not as libcamera's "Device or resource busy".
busy = _FakeCameraModule(AF, busy=True)
try:
    _with_camera(busy, lambda: CB.grab_from_camera((2328, 1748)))
    ok_('a camera already in use stops calibration', False)
except Exception as e:                                        # noqa: BLE001
    ok_('a camera already in use stops calibration', True)
    ok_('...saying who has it (%r)' % str(e)[:48], 'already in use' in str(e))

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d calibration checks passed' % ok)
sys.exit(1 if bad else 0)
