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
import cropbox as CX
import exposure as EX
import offer_parser as OP
import pipeline as PL
import journal as JR
import track as TR
from accumulate import OfferAccumulator

DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
DEFAULT_SNAPSHOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'live-frame.jpg')

# The motion gate means whole minutes can pass with no read, so the snapshot is
# refreshed on a timer as well. Cheap: a warp and a resize, no OCR.
#
# Two rates, because a live view is only worth CPU while a person is looking at
# it. The server touches a file whenever the browser fetches a frame; within
# that window the view is worth refreshing quickly, and outside it a slow tick
# is enough to prove the camera is alive.
#
# The fast rate is what someone watching the page actually experiences, so it
# is set by what looks alive rather than by what is cheap. Raising it was paid
# for first: a snapshot used to copy a 12MB frame, draw on it at full size,
# shrink it with an area filter and then warp a second copy of a card the
# reader had already made. It now shrinks once, draws on the small picture and
# reuses the reader's card — about a quarter of the work, roughly 20ms of a
# Pi 4's loop thread per frame. At this rate that is an eighth of that one
# thread, which measured against the reads is affordable: the Pi 4 has four
# cores and the reads leave most of them idle.
SNAPSHOT_FAST = 0.07
SNAPSHOT_IDLE = 3.0

# The live view is a *view*, not a read. It exists so the driver can see what
# the camera is pointed at, and it is looked at on a phone over the car's wifi —
# so what limits it is bytes on the link, not pixels on the Pi. Composing and
# encoding one costs a few milliseconds either way; a 640px frame at quality 80
# is about 136kB, which at ten a second is 1.4MB/s of wifi and is why the
# picture lagged.
#
# 480px at quality 60 is about 50kB, near a third of that, and it is still twice
# the resolution anything in this picture is judged at: the aim is read from a
# green outline and the focus from the inset, which is the reader's own image
# and is pasted in rather than resampled here. None of it touches what the
# scanner reads — that is warped from the full sensor frame at OCR_CARD_HEIGHT
# and never goes near this path.
SNAPSHOT_WIDTH = 480
SNAPSHOT_QUALITY = 60

# The motion gate fires once per offer, because a card sitting still is not a
# change. One frame is therefore the only sample there would ever be, and one
# frame is where a leg gets lost to glare or a blink of defocus. After anything
# is read, keep reading for a few seconds so the accumulator has more than one
# view of the same card to work from.
RESAMPLE_WINDOW = 4.0
RESAMPLE_EVERY = 0.5

WATCH_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.viewing')
WATCH_WINDOW = 10.0

# Touched by the web side when the driver asks for the outline to be re-found.
# A file rather than a signal or a socket, for the same reason .viewing is one:
# the scanner is sometimes a child of the web server and sometimes a systemd
# unit that has never heard of it, and a file works identically either way.
#
# It exists because the automatic recovery cannot always be sure. Corners that
# have drifted off to one side are unambiguous — the card is in the middle of
# the frame and they are not — but corners sitting concentric with the screen
# at the wrong size are not: that is equally "the phone was re-seated" and "the
# outline is on part of the screen", and no amount of looking tells them apart.
# The driver can see which it is in one glance at the live view, so the honest
# answer is to let them say.
RESET_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.recalibrate')


def reset_requested():
    """True once per request, and never fatal if the file cannot be removed."""
    try:
        if not os.path.exists(RESET_PATH):
            return False
        os.remove(RESET_PATH)
        return True
    except OSError:
        return False


def use_manual_box(scanner, quad_px):
    """Read exactly the box a person drew, and stop deriving one inside it.

    Three settings, and they only make sense together. The corners are the box.
    The crop is pinned to all of it, because a crop derived from the box would
    trim the top off the very thing the driver framed. And the card's share of
    the quad is 1.0 — the box *is* the card — which keeps the warp at the height
    the reader wants instead of twice it.
    """
    scanner.quad = np.array(quad_px, dtype=np.float32)
    scanner.roi = list(CX.PIN_WHOLE)
    scanner.fixed_card_share = 1.0
    scanner.card_share = 1.0


def snapshot_interval():
    try:
        if time.time() - os.path.getmtime(WATCH_PATH) < WATCH_WINDOW:
            return SNAPSHOT_FAST
    except OSError:
        pass
    return SNAPSHOT_IDLE


def load_config(path):
    if not os.path.exists(path):
        sys.exit('no %s — run calibrate.py first' % path)
    with open(path) as fh:
        return json.load(fh)


_config_error = None


def save_config(path, cfg):
    """Write the calibration back, atomically and never fatally.

    Atomically because the web server reads this file to report what the scanner
    is doing, and must never see a half-written one. Never fatally because this
    is a convenience — it saves the next run rediscovering what this one already
    knows — and a read-only card or a full disk is no reason to stop reading
    offers. The scanner keeps the corrected values in memory either way.
    """
    global _config_error
    try:
        tmp = path + '.part'
        with open(tmp, 'w') as fh:
            json.dump(cfg, fh, indent=2)
        os.replace(tmp, path)
        _config_error = None
    except Exception as e:
        message = str(e)
        if message != _config_error:
            _config_error = message
            print('could not save calibration (further identical errors '
                  'suppressed): %s' % message)


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

    # A phone screen is an emissive, PWM-dimmed panel: auto-exposure hunts on it,
    # and an exposure that is not a whole number of dimming cycles aliases into
    # rolling bands that drift down the picture. Pin both, and pick the exposure
    # by arithmetic rather than by taste — see exposure.py.
    ctrls = {
        'AeEnable': False,
        'AwbEnable': False,
        'ExposureTime': int(exposure_us),
        'AnalogueGain': float(gain),
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


_read_error = None


def _read_failed(exc):
    """Report a read that raised, once per distinct fault.

    Rate-limited by message the same way the snapshot and config writers are:
    whatever makes one frame fail usually makes the next hundred fail too, and
    a log that repeats it at thirty lines a second buries the one line that
    said what happened.
    """
    global _read_error
    message = '%s: %s' % (type(exc).__name__, exc)
    if message != _read_error:
        _read_error = message
        log('read failed (further identical errors suppressed): %s' % message)


_snapshot_error = None


def write_snapshot(frame, cfg, path, quad=None, roi=None, card=None, scale=None):
    """Write what the camera sees, for the live page. Never fatally.

    `quad` overrides the calibrated corners so the outline follows the tracker
    rather than lagging behind it, `roi` is the box being read, and `card` is
    the reader's own last picture, which saves warping another one.

    `scale` says the frame is the preview stream rather than the sensor, and by
    how much — the corners are stored in capture coordinates, so they have to
    come down onto the smaller picture. See the call site for why that is worth
    doing: the sensor frame exists to be read, and copying twelve megabytes of
    it to make a 480px thumbnail is most of what the live view costs.
    """
    global _snapshot_error
    try:
        if quad is None:
            quad = np.array(cfg['quad'], dtype=np.float32)
        if scale is not None:
            quad = np.asarray(quad, dtype=np.float32) / np.asarray(scale, dtype=np.float32)
        if frame.ndim == 2:
            # The outline is drawn in green and the preview stream is luma, so
            # it has to become a colour picture before anything coloured goes on
            # it — otherwise the box comes out grey on grey.
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        view = PL.snapshot(frame, quad, roi,
                           cfg.get('cardHeight', 900),
                           width=SNAPSHOT_WIDTH, card=card,
                           warp_card=scale is None)
    except Exception as e:
        message = str(e)
    else:
        message = PL.write_jpeg(path, view, quality=SNAPSHOT_QUALITY)
    # This runs several times a second; repeating one broken thing that often
    # buries everything else in the log.
    if message and message != _snapshot_error:
        print('snapshot failed (further identical errors suppressed): %s' % message)
    _snapshot_error = message


def log(message):
    """A human-readable line for the log file.

    Deliberately not JSON. In --json mode every read goes to stdout as an
    object for the web server to parse; anything that fails to parse is passed
    through to the log instead, which is exactly where these belong. The point
    of them is that a log someone pastes back should be enough to diagnose the
    problem without also needing the rig.
    """
    sys.stdout.write(message + '\n')
    sys.stdout.flush()


# How often to summarise, and how often at most to quote what the reader saw.
# Both are rate limits rather than schedules: a quiet scanner says nothing.
HEALTH_EVERY = 120.0
SAMPLE_EVERY = 20.0


class Health:
    """Counts what happened, and says so occasionally.

    A per-read line would bury the log and a silent scanner cannot be
    diagnosed. This reports a summary only when something has actually
    happened since the last one.
    """

    def __init__(self):
        self.reset(None)
        self.relocks = 0
        self.rebaselines = 0
        self.gain = None
        self.bright = None
        self.banding = None
        # What the exposure is now, and what calibration measured it at. Only
        # worth a line when they differ — see report().
        self.exposure = None
        self.measured_exposure = None

    def reset(self, now):
        # None rather than time.time(): the window starts when the first read
        # arrives, so the clock this is judged against is always the caller's.
        self.since = now
        self.reads = self.complete = self.no_pay = self.clipped = 0
        self.ms = []

    def add(self, out, parsed, card=None, previous=None):
        self.reads += 1
        self.ms.append(out['ms']['total'])
        if card is not None:
            self.bright = EX.brightness(card)
            # Two consecutive reads of a still card differ by flicker and noise
            # and almost nothing else, which is exactly what banding_score is.
            if previous is not None and previous.shape == card.shape:
                self.banding = EX.banding_score([previous, card])
        if parsed.get('complete'):
            self.complete += 1
        if parsed.get('pay') is None:
            self.no_pay += 1
        if out.get('clipped'):
            self.clipped += 1

    def report(self, now, tracker, scanner):
        if self.since is None:
            self.since = now
        if now - self.since < HEALTH_EVERY or not self.reads:
            return
        median = sorted(self.ms)[len(self.ms) // 2]
        bits = ['%d reads, %d complete' % (self.reads, self.complete),
                'median %.0fms' % median]
        if self.no_pay:
            bits.append('%d found no payout' % self.no_pay)
        if self.clipped:
            bits.append('%d had the payout at the crop edge' % self.clipped)
        # Brightness and banding, because "the picture looks dark" and "the
        # screen looks wavy" are things a person notices and a log should be
        # able to confirm or deny with a number.
        if self.bright is not None:
            bits.append('card brightness %d/%d' % (round(self.bright), round(EX.TARGET_BRIGHT)))
        if self.banding is not None:
            bits.append('banding %.1f%s' % (self.banding,
                                            ' (rippling)' if self.banding > 4.0 else ''))
        if self.gain is not None:
            bits.append('gain %.2f' % self.gain)
        # A shortened exposure is the one thing that can make the screen ripple
        # on a rig that measured a flicker-safe one, so if the banding number
        # above is high, the reason for it belongs on the same line.
        if self.exposure is not None and self.exposure != self.measured_exposure:
            bits.append('exposure %dus, borrowed against %dus for daylight'
                        % (self.exposure, self.measured_exposure))
        bits.append('crop %s' % _fmt_roi(scanner.crop_box))
        if tracker is not None:
            status = tracker.status()
            # Both numbers, because they answer different questions and the
            # reassuring one can be reassuring while the corners are nowhere
            # near the phone: drift is against the last save, which moves.
            # Three states, not two. "Held" used to cover being frozen beside
            # the screen as well as tracking it, because a candidate was found
            # on every check either way and only `misses` was being reported.
            where = ('lost' if status['lost']
                     else 'stuck' if status.get('stalled') else 'held')
            bits.append('corners %s, %.0fpx from calibration (%.0fpx since last save)'
                        % (where, status.get('wander', status['drift']), status['drift']))
            if self.relocks:
                bits.append('re-locked %dx since start' % self.relocks)
            if self.rebaselines:
                bits.append('un-stuck %dx — the stored calibration is out of date'
                            % self.rebaselines)
        log('health over %.0fs: %s' % (now - self.since, '; '.join(bits)))
        self.reset(now)


def _fmt_roi(roi):
    return 'whole screen' if not roi else '[%.2f %.2f %.2f %.2f]' % tuple(roi)


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
    if parsed.get('grew'):
        flags.append('%d legs merged from %d reads'
                     % (parsed.get('legs') or 0, parsed.get('mergedFrom') or 0))
    print('%s  $%.2f/hr  %-4s  pay $%.2f  %s min  %s mi%s  [%.0fms]%s'
          % (frame_text, rate['perHour'], rate['state'].upper(), parsed['pay'],
             parsed['minutes'], parsed['miles'],
             '  (%s)' % '; '.join(flags) if flags else '',
             ms['total'], '  LOCKED' if locked else ''))


def emit(rate, parsed, ms, locked, tracker=None, scanner=None):
    """One JSON object per line, flushed, so a parent process sees reads live."""
    payload = {
        'track': tracker.status() if tracker is not None else None,
        'ready': rate['ready'],
        'locked': locked,
        'state': rate['state'],
        'perHour': round(rate['perHour'], 2) if rate['ready'] else None,
        # Both rates, and the time they were both divided by. The card's own
        # minutes are below as `minutes`, for checking against the phone; these
        # are what the arithmetic actually used, which differ once `pad` or
        # `secondsPerItem` is set. Sending both is what lets the page show a
        # sum that adds up instead of one it has to guess at.
        'grossPerHour': round(rate['grossPerHour'], 2) if rate['ready'] else None,
        'billedMinutes': round(rate['minutes'], 1) if rate['ready'] else None,
        # `is not None`, not truthiness: this is a number that can legitimately
        # be zero, and now that it is net of running costs it can be negative
        # too. Testing it for truth turned "you break exactly even per mile"
        # into "--".
        'perMile': (round(rate['perMile'], 2)
                    if rate.get('perMile') is not None else None),
        'pay': parsed['pay'],
        'minutes': parsed['minutes'],
        'miles': parsed['miles'],
        'items': parsed['items'],
        'milesCorrected': parsed['milesCorrected'],
        'milesUncertain': parsed['milesUncertain'],
        # What was taken off the top, and at what rate. Without these the page
        # cannot explain its own headline: a driver who works out 7.09 over 34
        # minutes gets $12.51/hr and the screen says $10.61, with nothing on it
        # saying that 3.6 miles of running costs came out first.
        'cost': round(rate['cost'], 2) if rate.get('ready') else None,
        'costPerMile': rate.get('costPerMile'),
        'ms': round(ms['total']),
        'text': (parsed.get('text') or '')[:200],
        'legs': parsed.get('legs'),
        'mergedFrom': parsed.get('mergedFrom', 1),
        'grew': bool(parsed.get('grew')),
    }
    sys.stdout.write(json.dumps(payload) + '\n')
    sys.stdout.flush()


def _stop_on_sigterm():
    """Turn the supervisor's stop signal into an ordinary unwind.

    server.js stops the scanner with SIGTERM, and autopilot execv's into this
    process so that is where it lands. Python's default action for it ends the
    process without unwinding, which skips `finally: cam.stop()` and skips the
    atexit handler that deletes the OCR scratch file — a megabyte of /dev/shm,
    which is RAM, left behind on every stop. Raising SystemExit instead runs
    both.
    """
    import signal

    def handler(signum, frame):
        raise SystemExit(0)

    try:
        signal.signal(signal.SIGTERM, handler)
    except (ValueError, OSError):
        pass                    # not the main thread, or no such signal here


def main():
    _stop_on_sigterm()
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default=DEFAULT_CONFIG)
    ap.add_argument('--speak', action='store_true', help='say the verdict aloud via espeak-ng')
    ap.add_argument('--display', action='store_true', help='fullscreen verdict on an attached screen')
    ap.add_argument('--exposure', type=int, default=None,
                    help='microseconds. Defaults to the value measured at calibration, '
                         'or %d — one 60Hz cycle, which is also two of 120 and four of '
                         '240, so it does not band against any of them'
                         % EX.DEFAULT_EXPOSURE)
    ap.add_argument('--gain', type=float, default=None,
                    help='fixed analogue gain. Omit to let it track the phone dimming '
                         'itself, which is what a screen does at night')
    ap.add_argument('--no-auto-gain', action='store_true',
                    help='never adjust gain; use exactly what --gain says')
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
    ap.add_argument('--journal', default=JR.DEFAULT_PATH,
                    help='where to keep every confident offer, for looking at '
                         'a shift afterwards. The web side reads the default '
                         'path, so if you move it, set JOURNAL to match or the '
                         'offers page will keep saying there is nothing there')
    ap.add_argument('--no-journal', action='store_true',
                    help='read offers without keeping any record of them')
    ap.add_argument('--no-parallel', action='store_true',
                    help='read one frame at a time. The default reads the '
                         'confirming frame alongside the first, which is 56%% '
                         'of the wall clock for the same evidence')
    ap.add_argument('--no-track', action='store_true',
                    help='never re-find the phone; use the calibrated corners exactly')
    args = ap.parse_args()

    if args.list_modes:
        from picamera2 import Picamera2
        cam = Picamera2()
        for m in cam.sensor_modes:
            print(m)
        cam.close()
        return

    cfg = load_config(args.config)
    health = Health()

    # Corners a person drew, rather than ones the detector found. They change
    # three things at once — see use_manual_box — and they turn tracking off,
    # because a tracker judges candidates against a calibrated *screen* and
    # would move a hand-drawn box back onto whatever it believes that is. The
    # driver overrode the detector; letting the tracker overrule them would put
    # the rig straight back where it was.
    manual = bool(cfg.get(CX.MANUAL_KEY))

    # Start tracking from where the last run ended, if it wrote that down —
    # a fixed mount usually has not moved between runs, so resuming saves
    # re-converging. `quad` stays the calibration; see QuadTracker.calibrated.
    scanner = PL.Scanner(
        # Resume where the last run ended — but only when tracking is on to
        # pull it back. --no-track promises the calibrated corners exactly, and
        # pinning a position no run can correct is the opposite of that.
        quad=np.array((None if (args.no_track or manual) else cfg.get('trackedQuad'))
                      or cfg['quad'], dtype=np.float32),
        card_height=cfg.get('cardHeight', 900),
        # A pin has to be asked for, under a key only a pin is written to.
        # `roi` cannot serve: every config.json written before the crop became
        # derived has one, and honouring an inherited value silently disables
        # the placement. The boxes in the wild are [0,0,1,1] (harmless but
        # slow), [0,0.40,1,0.60], and [0.02,0.48,0.96,0.50] — the old tight
        # crop, which lost the payout on 13 of 42 test cards.
        roi=cfg.get('cropBox'),
        # A hand-drawn box is all card. Measured as half a screen it would be
        # warped twice as tall as the reader can use, then shrunk back down
        # against the pixel budget — same text, three times the work, smaller
        # by the time it is read.
        card_share=1.0 if manual else None,
        settings=cfg.get('settings', {}),
    )
    # The tracker works in the small stream's coordinates and reports in the
    # capture's, so it needs the ratio between them.
    cap = cfg.get('capture', {})
    track_scale = (cap.get('width', 2328) / float(LORES[0]),
                   cap.get('height', 1748) / float(LORES[1]))
    capture_size = (cap.get('width', 2328), cap.get('height', 1748))
    # Start from where the last run left off, but judge candidates against the
    # calibration itself — see QuadTracker.calibrated.
    tracker = None if (args.no_track or manual) else TR.QuadTracker(
        scanner.quad, scale=track_scale,
        calibrated=np.array(cfg['quad'], dtype=np.float32))

    # Calibration already found focus with autofocus; reuse it rather than
    # making the driver rediscover a number that cannot change on a fixed mount.
    lens = args.lens if args.lens is not None else cfg.get('lensPosition') or 4.0

    # Exposure is chosen for flicker, not for brightness; gain then does the
    # brightening, because gain cannot reintroduce banding and exposure can.
    exposure_us = (args.exposure if args.exposure is not None
                   else cfg.get('exposureTime') or EX.DEFAULT_EXPOSURE)
    gain = args.gain if args.gain is not None else cfg.get('analogueGain') or 1.5
    auto_gain = (None if (args.no_auto_gain or args.gain is not None)
                 else EX.AutoGain(gain, exposure=exposure_us))
    cam = start_camera(cfg, exposure_us, gain, lens)
    if args.save_misses:
        os.makedirs(args.save_misses, exist_ok=True)
    if args.display:
        cv2.namedWindow('uber-scan', cv2.WND_PROP_FULLSCREEN)
        cv2.setWindowProperty('uber-scan', cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    # Two reads at once need OpenMP pinned to one thread per instance, or the
    # two tesseracts fight over all four cores: unpinned, a pair measured 46
    # seconds against 435ms sequential. Pinning costs a single read nothing
    # measurable. setdefault so an explicit setting still wins.
    pair_reads = not args.no_parallel
    if pair_reads:
        os.environ.setdefault('OMP_THREAD_LIMIT', '1')

    # Everything that decides what gets read, in one place, once. A log without
    # this is a log where every question starts with "what was it set to?".
    import calibrate as CAL
    quad = scanner.quad
    # The frame shape matters to the measurement, not just to the spill note
    # below: a screen taller than the frame has to be measured across rather
    # than down, or this reports the frame's height back at you.
    frame_shape = (cap.get('height', 1748), cap.get('width', 2328))
    log('scanning — ctrl-c to stop')
    log('setup: capture %dx%d, card ~%dpx on the sensor (floor %d), crop %s, '
        'warp %dpx, reader gets %dpx, lens %s%s'
        % (cap.get('width', 0), cap.get('height', 0),
           CAL.card_source_pixels(quad, frame_shape), CAL.MIN_CARD_PIXELS,
           _fmt_roi(scanner.crop_box),
           scanner.read_height, scanner.ocr_height,
           ('%.2f dioptres' % lens) if lens else 'fixed',
           '' if tracker is not None else
           (', reading a box set by hand — corner tracking OFF' if manual
            else ', corner tracking OFF')))
    log('setup: reads %s'
        % ('paired — the confirming frame is read alongside the first'
           if pair_reads else 'one at a time (--no-parallel)'))
    log('setup: exposure %dus (%s), gain %.2f (%s)'
        % (exposure_us,
           'a whole number of 60/120/240Hz cycles, so the screen should not band'
           if exposure_us in EX.FLICKER_SAFE else 'not a standard flicker period',
           gain, 'tracking the screen' if auto_gain else 'fixed'))
    log('setup: corners %s' % [[int(x), int(y)] for x, y in quad])
    spill = PL.touches_edge(quad, frame_shape)
    if spill:
        log('setup: the screen runs off the %s of the frame. That is expected on a '
            'close mount and is not a problem — the crop is fitted to the card by '
            'content, not to the screen by fraction.' % ' and '.join(spill))
    accumulator = OfferAccumulator()
    last_sample = 0.0
    previous_card = None
    failures = 0
    spoke_for = None
    frames = 0
    last_snapshot = 0.0
    resample_until = 0.0
    last_resample = 0.0
    settled_on = None

    # Every offer the scanner is sure of, kept so a shift can be looked at
    # afterwards. Seeded from the file rather than from nothing: the scanner is
    # restarted with a backoff when it dies, and a card sits on screen far
    # longer than a restart takes, so starting empty meant coming back to the
    # same offer and recording it twice.
    offer_log = None
    if not args.no_journal:
        offer_log = JR.OfferLog(JR.Journal(args.journal))
        kept = offer_log.journal.rows()
        resumed = offer_log.resume()
        log('journal: %s (%d offer%s so far)%s'
            % (args.journal, len(kept), '' if len(kept) == 1 else 's',
               ', still on the last one' if resumed else ''))
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
                now = time.time()
                do_read = scanner.should_read(luma)
                moved = False           # did the corners shift on this frame?

                # Re-find the phone on this same small frame. A mount is not a
                # clamp, and corners a centimetre out slide the crop off the
                # payout — which looks exactly like no offer being on screen.
                #
                # Done here, on the stream the motion gate already has, it costs
                # about a millisecond and needs no full-resolution capture at
                # all; finding the corners on a sensor frame costs seven times
                # as much, almost entirely in shrinking the frame down to this
                # size. Blurred frames are skipped: a smeared edge is a worse
                # guess than the corners already held.
                if reset_requested():
                    if manual:
                        # Re-find is also the way *out* of a hand-drawn box, and
                        # it has to find something before it throws one away:
                        # dropping the box first would leave the rig reading
                        # corners nobody has checked, which is the state the
                        # driver drew the box to escape.
                        found = PL.detect_screen_quad(luma, work_width=PL.DETECT_WIDTH)
                        if found is None:
                            log('re-find asked for, but there is no screen in view to '
                                'find — the box you drew is still in use. Try again '
                                'with the phone lit and a darker border around it.')
                        else:
                            quad_px = (np.asarray(found, dtype=np.float32)
                                       * np.asarray(track_scale, dtype=np.float32))
                            manual = False
                            scanner.quad = quad_px
                            scanner.roi = None
                            scanner.fixed_card_share = None
                            cfg['quad'] = [[float(x), float(y)] for x, y in quad_px]
                            CX.clear_in_config(cfg)
                            save_config(args.config, cfg)
                            tracker = None if args.no_track else TR.QuadTracker(
                                quad_px, scale=track_scale, calibrated=quad_px)
                            # Same reason as the box below: the corners and the
                            # crop both just changed under a still picture.
                            moved = do_read = True
                            log('back to finding the phone automatically: the screen '
                                'in view now is the calibration, the crop is derived '
                                'from it again, and tracking is %s'
                                % ('off (--no-track)' if tracker is None else 'on'))
                    elif tracker is not None:
                        tracker.start_over()
                        scanner.quad = tracker.quad
                        cfg.pop('trackedQuad', None)
                        save_config(args.config, cfg)
                        log('outline reset: back to the calibrated corners, and '
                            'the next screen in the middle of the frame will be '
                            'taken as the phone')
                    else:
                        log('outline reset asked for, but tracking is off '
                            '(--no-track), so the corners are already fixed')

                # A box drawn on the live view. It arrives as fractions of the
                # frame, which is the only form that survives the trip: what the
                # driver drew on was a 480px JPEG of a 2328px sensor frame.
                drawn = CX.take_request()
                if drawn is not None:
                    manual = True
                    use_manual_box(scanner, CX.in_pixels(drawn, capture_size))
                    CX.apply_to_config(cfg, drawn, capture_size)
                    save_config(args.config, cfg)
                    tracker = None
                    # Read it now. The whole crop just changed, and the motion
                    # gate cannot tell — it watches the frame, and the frame is
                    # a card sitting still, which is exactly what it looks like
                    # while somebody draws a box round it. Without this, pressing
                    # "read this box" does nothing visible until the picture next
                    # moves, which reads as the button not having worked.
                    moved = do_read = True
                    log('crop box set by hand to [%s] of the frame: reading exactly '
                        'that, with corner tracking off until re-find is pressed'
                        % CX.describe(drawn))

                if tracker is not None and scanner.settled:
                    was = tracker.status()
                    jumps_before, lost_before = tracker.jumps, was['lost']
                    stalled_before = was['stalled']
                    rebased_before = tracker.rebaselines
                    if tracker.update(luma, now):
                        scanner.quad = tracker.quad
                        # Where tracking has got to, kept apart from `quad`,
                        # which is the calibration and is written only by
                        # calibrate.py / autopilot.py.
                        cfg['trackedQuad'] = [[float(x), float(y)] for x, y in tracker.quad]
                    # A re-lock is a different rectangle, so it is a different
                    # picture to read as surely as a different picture would be
                    # — and the motion gate cannot see it, because it watches
                    # the frame and the frame did not change. Without this the
                    # read that finally uses the corrected box waits for the
                    # resample tick, or for the driver to move something.
                    #
                    # Only a re-lock. The ordinary path eases 35% of the way to
                    # the candidate on each check and reports every one of those
                    # steps as a move, so treating "moved" as "read again" put
                    # fourteen reads through one stationary card where two had
                    # done. A few pixels of drift does not invalidate the read
                    # that just happened; being on a different phone does.
                    if tracker.jumps > jumps_before or tracker.rebaselines > rebased_before:
                        moved = do_read = True
                    if tracker.rebaselines > rebased_before:
                        health.rebaselines += 1
                        log('corners un-stuck: the screen in front of the camera '
                            'is not the size the stored calibration describes, and '
                            'has been steadily so for %ds, so the corners were '
                            'moved onto it and the calibration taken as out of '
                            'date. Reading carries on — but re-run calibration '
                            'when you can, or the next start will be stuck again.'
                            % TR.RECOVER_AFTER)
                    elif tracker.jumps > jumps_before:
                        health.relocks += 1
                        log('corners re-locked: the phone is somewhere the stored '
                            'calibration did not expect, and has been for several '
                            'checks running. Mount moved?')
                    lost_now = tracker.status()['lost']
                    if lost_now != lost_before:
                        log('screen %s' % ('not visible — is the phone lit and in frame?'
                                           if lost_now else 'visible again'))
                    # Being stuck used to be one word in a health line every two
                    # minutes, which is not where anybody was looking. The
                    # automatic recovery handles a phone that has been re-seated;
                    # what it deliberately will not do is adopt a candidate of
                    # the wrong shape, and the commonest wrong shape is the white
                    # offer card on its own — the crop is a fraction of the
                    # corners, so corners drawn round the card read the journey
                    # and lose the payout. That case cannot be fixed by moving
                    # the box, only by the person who can see the screen.
                    stalled_now = tracker.status()['stalled']
                    if stalled_now != stalled_before:
                        log('outline stuck: the corners have been off the screen '
                            'the camera can see for %ds. If the box is drawn '
                            'round part of the offer card rather than the whole '
                            'phone, the screen is probably washed out — shade it '
                            'or dim it. Otherwise press reset on the live page, '
                            'or re-run calibration.' % TR.STALL_VISIBLE
                            if stalled_now else 'outline unstuck: the corners are '
                            'back on the screen')
                    if tracker.needs_save(now):
                        save_config(args.config, cfg)
                        tracker.mark_saved(now)

                # A phone dims itself. A screen set up in daylight is a much
                # darker subject at two in the morning, and a fixed exposure that
                # suited one leaves the other too dark to read. Exposure stays
                # where it was measured — moving it would undo the flicker
                # arithmetic — and gain does the adapting, slowly, off the same
                # small frame the gate just used.
                #
                # Measured on the screen, not the frame. The dark car around
                # the phone is most of the picture and none of the subject: it
                # drags the brightness reading down and divides the blown-out
                # fraction by however much of the frame it fills, so a card
                # sitting at 237 with a fifth of it clipped still asked for
                # more gain. Rig logs showed the gain hunting between 6.8 and
                # its 8.0 ceiling while the card was over-exposed the whole
                # time, which is also what turns a screen's flicker into the
                # ripple that fails reads.
                #
                # And only while there is a screen there to expose for. The
                # window is wherever the phone was last seen, so once the phone
                # is out of the mount it is dark upholstery, and the gain used
                # to wind up chasing a card that had gone — railing at 8x in
                # about 78 seconds and then needing a further minute of
                # six-second steps to come back down once the phone returned.
                # That minute lands exactly when the driver has picked the phone
                # up to look at an offer.
                if auto_gain is not None and scanner.settled:
                    lit = PL.quad_window(luma, scanner.quad, track_scale) \
                        if scanner.quad is not None else luma
                    have_screen = True if tracker is None \
                        else not tracker.status()['lost']
                    was_exposure = auto_gain.exposure
                    new_gain = auto_gain.update(lit, now, has_screen=have_screen)
                    if new_gain is not None:
                        cam.set_controls({'AnalogueGain': float(new_gain)})
                        cfg['analogueGain'] = round(new_gain, 3)
                        health.gain = new_gain
                    # Daylight through a windscreen can blow the card out with
                    # the gain already on its floor, and then the exposure is
                    # the only thing left. It is given back the moment the light
                    # drops, and never goes above what calibration measured.
                    if auto_gain.exposure != was_exposure:
                        cam.set_controls({'ExposureTime': int(auto_gain.exposure)})
                        log('exposure %s to %dus: the card was blown out with '
                            'the gain already at its floor'
                            % ('shortened' if auto_gain.exposure < was_exposure
                               else 'given back', auto_gain.exposure))
                    # Deliberately not written to cfg: the borrowed value is a
                    # response to the light right now, and persisting it would
                    # start a night shift on a noon exposure with nothing to
                    # tell it that is wrong. cfg keeps what calibration measured.
                    health.exposure = auto_gain.exposure
                    health.measured_exposure = auto_gain.measured

                # Keep sampling for a short while after a card appears, so a leg
                # missed by one frame can still be picked up by the next.
                if not do_read and now < resample_until and (now - last_resample) > RESAMPLE_EVERY:
                    do_read = True
                    last_resample = now

                # ...but not while the outline is visibly on the wrong thing.
                #
                # This is the loop's one real inefficiency, and it is a feedback
                # loop rather than a waste: a read costs several hundred
                # milliseconds during which nothing else in this loop runs —
                # including the tracker, whose 0.4s recheck is what would fix
                # the corners. So reading a crop taken from corners the detector
                # can already see are wrong does not merely throw the read away,
                # it postpones the correction that would have made the next one
                # good. A rig reached its verdict after 5.7 seconds and eight
                # reads, seven of them of the rectangle being replaced.
                #
                # A move above overrides this, because the whole point of
                # waiting is to read the moment the corners arrive.
                if do_read and not moved and tracker is not None \
                        and tracker.disputing(now):
                    do_read = False
                # Grab the full frame for a read, or when the live view is due —
                # otherwise nothing is ever seen between offers.
                due = args.snapshot and (now - last_snapshot) > snapshot_interval()
                if not do_read and not due:
                    continue
                # The sensor frame is copied only when something is going to
                # *read* it. A live view is a 480px thumbnail of a car interior
                # with a box drawn on it, and it was being made by copying
                # twelve megabytes of sensor and throwing 99% of it away — 8ms
                # of pure memory traffic on this machine, and a good deal more
                # on a Pi, at up to fourteen frames a second. The preview stream
                # is already in hand, already the right sort of size, and the
                # only thing lost is colour in a picture nobody reads colour
                # from. The reader still gets the sensor, at full resolution.
                if do_read:
                    # picamera2's "RGB888" hands back B, G, R ordered arrays,
                    # which is exactly what OpenCV expects. The name is the odd
                    # one out.
                    frame, preview_scale = request.make_array('main'), None
                else:
                    # Copied, because `luma` is a view onto the request's own
                    # buffer and the request is released a few lines below —
                    # after which that memory goes back to the camera to be
                    # filled again. 300KB, against the 12MB this branch exists
                    # to avoid.
                    frame, preview_scale = luma.copy(), track_scale
            finally:
                request.release()

            # A verdict needs two reads that agree, so when one is due, take
            # the frame after it as well and read both at once. The sensor is
            # already producing them 33ms apart, and two reads together cost
            # 56% of two in a row — so the confirmation stops costing a second
            # of wall clock while an offer is timing out. It is the same
            # evidence, gathered at the same time instead of one after the
            # other. --no-parallel falls back to one at a time.
            partner = None
            if do_read and pair_reads:
                partner_request = cam.capture_request()
                try:
                    partner = partner_request.make_array('main')
                finally:
                    partner_request.release()

            if args.snapshot and (due or do_read):
                write_snapshot(frame, cfg, args.snapshot, quad=scanner.quad,
                               roi=scanner.crop_box, card=previous_card,
                               scale=preview_scale)
                last_snapshot = time.time()

            if not do_read:
                continue

            frames += 1
            try:
                batch = scanner.read_many(
                    [frame] if partner is None else [frame, partner], now=time.time())
                out = batch[-1]
                # The earlier frame's reading is evidence too: the accumulator
                # merges partial reads, and a leg lost to glare in one frame is
                # often present in the other.
                for earlier in batch[:-1]:
                    accumulator.add(earlier['parsed'])
            except Exception as e:
                # A read is the one part of this loop that touches an external
                # engine, a homography and a JPEG encoder, and any of them can
                # throw on one bad frame: a degenerate quad, a tesseract
                # invocation that fails, a full disk. Killing the process for
                # it means the supervisor's backoff, a camera re-open, and
                # roughly a minute of not scanning — for a frame that would
                # have been replaced 30ms later.
                _read_failed(e)
                continue
            parsed = accumulator.add(out['parsed'])
            rate = OP.rate(parsed, cfg.get('settings', {}))
            out['parsed'], out['rate'] = parsed, rate
            # Anything with a payout is worth a second look; anything without is
            # not an offer and should not hold the loop open.
            #
            # But a second look is all it takes once the reading is whole — a
            # total, or both legs of a two-leg card — and two reads running have
            # said the same thing. Sampling on past that point re-reads a card
            # nothing more can be learned from, which on a Pi is several seconds
            # of a small computer's whole attention. What keeps sampling is the
            # case that needs it: a single leg that is not a total, which is
            # exactly the shape of a card with a leg still missing.
            # Counted here because the Scanner stopped counting when the crop
            # stopped moving, and the log line that says "N in a row" is the
            # one that tells a bad frame from a broken mount. It had been
            # printing 0 every time, on every rig.
            failures = 0 if parsed['complete'] else failures + 1

            signature = (parsed['pay'], parsed['minutes'], parsed['miles'])
            whole = parsed['complete'] and (parsed.get('hasTotal')
                                            or (parsed.get('legs') or 0) >= 2)
            # Two different questions, kept apart.
            #
            # `stable` is the merged reading holding still across two reads, and
            # nothing else — which is what the journal's field of that name says
            # it stores. It has to be taken here because `settled_on` is
            # overwritten a few lines below; asking again after the overwrite
            # compares the signature with itself and is true on every read, so
            # every row was being stored as settled and the flag said nothing.
            #
            # Whether to STOP resampling is a stricter question: a reading that
            # holds still while a leg is still missing has not finished, it has
            # only stopped changing. Conjoining the two into the stored flag
            # made it redundant with `whole` instead of independent of it.
            stable = signature == settled_on
            if whole and stable:
                resample_until = 0.0
            elif parsed.get('pay'):
                resample_until = time.time() + RESAMPLE_WINDOW
            settled_on = signature
            health.add(out, parsed, out.get('card'), previous_card)
            previous_card = out.get('card')

            # When a read comes back wrong, the one thing worth having is what
            # the reader actually saw. Rate limited, because a screen with no
            # offer on it fails constantly and correctly.
            now = time.time()
            if not parsed['complete'] and (now - last_sample) > SAMPLE_EVERY:
                last_sample = now
                why = ('the payout sat against the top edge of the crop'
                       if out.get('clipped') else
                       'no payout in the crop' if parsed['pay'] is None else
                       'a payout but no journey')
                log('read %d found nothing usable (%s, %d in a row). Reader saw: %r'
                    % (frames, why, failures,
                       (out.get('text') or '').strip()[:220]))
            health.report(now, tracker, scanner)

            if args.json:
                emit(rate, parsed, out['ms'], out['locked'], tracker, scanner)
            else:
                show('#%d' % frames, rate, parsed, out['ms'], out['locked'])

            if args.save_misses and not parsed['complete']:
                cv2.imwrite(os.path.join(args.save_misses, 'miss-%d.png' % int(time.time())), frame)

            # Speak once per offer, never per frame — and only once the
            # reading is *whole*.
            #
            # `locked` means two consecutive raw frames parsed the same, which
            # is not the same claim: two frames that both lose the pickup leg
            # to the same glare agree perfectly with each other. The loop
            # already computes `whole` for exactly this distinction and uses it
            # to decide whether to keep resampling; speaking before it is
            # announcing a number the scanner is still in the middle of
            # correcting, and a two-leg card missing a leg reads as a much
            # better offer than it is.
            if args.speak and out['locked'] and whole and rate['ready']:
                sig = (parsed['pay'], parsed['minutes'])
                if sig != spoke_for:
                    spoke_for = sig
                    say(spoken(rate))
            if not rate['ready']:
                spoke_for = None

            # Keep the offer. Same confidence the spoken verdict uses, so the
            # file and the voice can never disagree about what was read.
            #
            # Unlike `spoke_for`, nothing here is cleared by a read that came
            # back empty. Clearing on a bad read is right for speech — the next
            # card should be announced even if it pays the same — but it is
            # wrong for a file: a clipped payout parses as nothing at all, so
            # one glare frame during the resample burst would re-arm the gate
            # and record the same card twice. What separates one offer from the
            # next here is the accumulator's own episode, which is the thing
            # that actually knows.
            #
            # Whether the reading had settled is recorded rather than required.
            # A card whose OCR never holds still is the marginal reading most
            # worth studying afterwards, and refusing to write it would leave
            # the hardest offers missing with nothing to say so.
            #
            # `whole` is recorded rather than required, for the same reason
            # `settled` is. Requiring it dropped two real shapes without a
            # word: a single-leg card whose "total" the reader mangled, and a
            # two-leg card no single frame ever caught both halves of. Those
            # readings are optimistic — a card's first leg alone looks like a
            # much better job than the card is — so they must not reach a
            # median. But dropping them makes the offer *vanish*, and a gap
            # nothing accounts for is the worst thing to find in a file being
            # read back months later. Written and flagged: the page sets them
            # aside and says how many, and if a later frame does see the card
            # whole it supersedes the partial row anyway.
            if offer_log is not None and rate['ready'] and out['locked']:
                offer_log.consider(parsed, rate, ms=out['ms']['total'],
                                   locked=out['locked'], whole=whole,
                                   settled=stable)

            if args.display:
                cv2.imshow('uber-scan', render_panel(rate, parsed))
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
    except (KeyboardInterrupt, SystemExit):
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
