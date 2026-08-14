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
import exposure as EX
import offer_parser as OP
import pipeline as PL
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
SNAPSHOT_FAST = 0.10
SNAPSHOT_IDLE = 3.0

# The motion gate fires once per offer, because a card sitting still is not a
# change. One frame is therefore the only sample there would ever be, and one
# frame is where a leg gets lost to glare or a blink of defocus. After anything
# is read, keep reading for a few seconds so the accumulator has more than one
# view of the same card to work from.
RESAMPLE_WINDOW = 4.0
RESAMPLE_EVERY = 0.5

WATCH_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.viewing')
WATCH_WINDOW = 10.0


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


_snapshot_error = None


def write_snapshot(frame, cfg, path, quad=None, roi=None, card=None):
    """Write what the camera sees, for the live page. Never fatally.

    `quad` overrides the calibrated corners so the outline follows the tracker
    rather than lagging behind it, `roi` is the box being read, and `card` is
    the reader's own last picture, which saves warping another one.
    """
    global _snapshot_error
    try:
        if quad is None:
            quad = np.array(cfg['quad'], dtype=np.float32)
        view = PL.snapshot(frame, quad, roi,
                           cfg.get('cardHeight', 900), card=card)
    except Exception as e:
        message = str(e)
    else:
        message = PL.write_jpeg(path, view)
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
        self.gain = None
        self.bright = None
        self.banding = None

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
        bits.append('crop %s' % _fmt_roi(scanner.crop_box))
        if tracker is not None:
            status = tracker.status()
            # Both numbers, because they answer different questions and the
            # reassuring one can be reassuring while the corners are nowhere
            # near the phone: drift is against the last save, which moves.
            bits.append('corners %s, %.0fpx from calibration (%.0fpx since last save)'
                        % ('lost' if status['lost'] else 'held',
                           status.get('wander', status['drift']), status['drift']))
            if self.relocks:
                bits.append('re-locked %dx since start' % self.relocks)
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


def main():
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

    # Start tracking from where the last run ended, if it wrote that down —
    # a fixed mount usually has not moved between runs, so resuming saves
    # re-converging. `quad` stays the calibration; see QuadTracker.calibrated.
    scanner = PL.Scanner(
        quad=np.array(cfg.get('trackedQuad') or cfg['quad'], dtype=np.float32),
        card_height=cfg.get('cardHeight', 900),
        settings=cfg.get('settings', {}),
    )
    # The tracker works in the small stream's coordinates and reports in the
    # capture's, so it needs the ratio between them.
    cap = cfg.get('capture', {})
    track_scale = (cap.get('width', 2328) / float(LORES[0]),
                   cap.get('height', 1748) / float(LORES[1]))
    # Start from where the last run left off, but judge candidates against the
    # calibration itself — see QuadTracker.calibrated.
    tracker = None if args.no_track else TR.QuadTracker(
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
    auto_gain = None if (args.no_auto_gain or args.gain is not None) else EX.AutoGain(gain)
    cam = start_camera(cfg, exposure_us, gain, lens)
    if args.save_misses:
        os.makedirs(args.save_misses, exist_ok=True)
    if args.display:
        cv2.namedWindow('uber-scan', cv2.WND_PROP_FULLSCREEN)
        cv2.setWindowProperty('uber-scan', cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

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
           '' if tracker is not None else ', corner tracking OFF'))
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
    spoke_for = None
    frames = 0
    last_snapshot = 0.0
    resample_until = 0.0
    last_resample = 0.0
    settled_on = None
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
                if tracker is not None and scanner.settled:
                    jumps_before, lost_before = tracker.jumps, tracker.status()['lost']
                    if tracker.update(luma, now):
                        scanner.quad = tracker.quad
                        # Where tracking has got to, kept apart from `quad`,
                        # which is the calibration and is written only by
                        # calibrate.py / autopilot.py.
                        cfg['trackedQuad'] = [[float(x), float(y)] for x, y in tracker.quad]
                    if tracker.jumps > jumps_before:
                        health.relocks += 1
                        log('corners re-locked: the phone is somewhere the stored '
                            'calibration did not expect, and has been for several '
                            'checks running. Mount moved?')
                    lost_now = tracker.status()['lost']
                    if lost_now != lost_before:
                        log('screen %s' % ('not visible — is the phone lit and in frame?'
                                           if lost_now else 'visible again'))
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
                if auto_gain is not None and scanner.settled:
                    lit = PL.quad_window(luma, scanner.quad, track_scale) \
                        if scanner.quad is not None else luma
                    new_gain = auto_gain.update(lit, now)
                    if new_gain is not None:
                        cam.set_controls({'AnalogueGain': float(new_gain)})
                        cfg['analogueGain'] = round(new_gain, 3)
                        health.gain = new_gain

                # Keep sampling for a short while after a card appears, so a leg
                # missed by one frame can still be picked up by the next.
                if not do_read and now < resample_until and (now - last_resample) > RESAMPLE_EVERY:
                    do_read = True
                    last_resample = now
                # Grab the full frame for a read, or when the live view is due —
                # otherwise nothing is ever seen between offers.
                due = args.snapshot and (now - last_snapshot) > snapshot_interval()
                if not do_read and not due:
                    continue
                # picamera2's "RGB888" hands back B, G, R ordered arrays, which
                # is exactly what OpenCV expects. The name is the odd one out.
                frame = request.make_array('main')
            finally:
                request.release()

            if args.snapshot and (due or do_read):
                write_snapshot(frame, cfg, args.snapshot, quad=scanner.quad,
                               roi=scanner.crop_box, card=previous_card)
                last_snapshot = time.time()

            if not do_read:
                continue

            frames += 1
            out = scanner.read(frame, now=time.time())
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
            signature = (parsed['pay'], parsed['minutes'], parsed['miles'])
            whole = parsed['complete'] and (parsed.get('hasTotal')
                                            or (parsed.get('legs') or 0) >= 2)
            if whole and signature == settled_on:
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
                    % (frames, why, out.get('misses', 0),
                       (out.get('text') or '').strip()[:220]))
            health.report(now, tracker, scanner)

            if args.json:
                emit(rate, parsed, out['ms'], out['locked'], tracker, scanner)
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
