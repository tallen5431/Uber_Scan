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
import cropbox as CX
import pipeline as PL

DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

# What to write into config.json as the crop.
#
# None means "work it out per read", which is what the scanner does: it places
# a box from geometry it measures each frame (pipeline.centred_roi) rather than
# from anything written down. That is the answer for a mount, because a crop
# recorded once is a guess about how the phone is framed and about which card
# turns up, and both of those were wrong often enough to matter.
#
# A four-element box here overrides that and pins the crop, which --full-screen
# uses and which is the escape hatch if the automatic placement ever misbehaves
# on a mount nobody anticipated.
DEFAULT_ROI = None

# What --full-screen pins it to: everything the camera can see.
WHOLE_VIEW = [0.0, 0.0, 1.0, 1.0]

# Where to judge focus while aiming. The card is the thing that has to be
# sharp, and a dashboard in focus around a soft phone reads as perfectly sharp
# if you measure the whole frame.
SHARP_ROI = [0.0, 0.40, 1.0, 0.60]

# Two numbers, because they mean different things. 350px is where reading
# measurably stops working; below it no setting helps. 450px is where there is
# comfortable margin for a dimmer or busier card. Refusing to calibrate anywhere
# between the two would be enforcing a preference as though it were a limit.
MIN_CARD_PIXELS = 380          # below this, do not bother
GOOD_CARD_PIXELS = 450         # above this, no notes

# Re-exported: the aiming copy reads better next to the two pixel floors above,
# but it belongs with the geometry that uses it.
PHONE_ASPECT = PL.PHONE_ASPECT

# The two IMX519 modes that see the whole sensor. 1280x720 and 1920x1080 are
# cropped windows (2560x1440 and 3840x2160 respectively), so they cut field of
# view rather than resolution and can put the phone partly out of frame.
FULL_FOV_MODES = {'2328x1748': (2328, 1748), '4656x3496': (4656, 3496)}


def write_config(path, config):
    """Write the calibration where a reader may be looking at that instant.

    To a temporary name and renamed, because a plain `open(path, 'w')` truncates
    the live file before writing a byte — and this is a box velcroed into a car
    where the ignition is the power switch. Lose power there, or fill the SD
    card, and what is left is a config.json that exists and does not parse.

    That used to be unrecoverable without ssh: autopilot decided the rig was
    calibrated by asking whether the file *existed*, scan_pi opened it with a
    bare json.load and died, the web server restarted it forever, and
    /api/status went on reporting calibrated:true the whole time. Deleting the
    file self-heals; corrupting it did not.

    scan_pi.save_config has done it this way all along and says why. This is the
    same thing on the two paths that create the file in the first place.
    """
    tmp = path + '.part'
    with open(tmp, 'w') as fh:
        json.dump(config, fh, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def load_existing(path):
    """Whatever is already in the config, or an empty dict.

    Unreadable is treated as absent rather than fatal: a half-written or
    hand-edited file should not stop a driver re-aiming the camera, and
    everything this command needs it is about to write anyway. The cost of
    getting it wrong is the settings block, which is replaced with the defaults
    either way if it cannot be read.
    """
    try:
        with open(path) as fh:
            existing = json.load(fh)
        return existing if isinstance(existing, dict) else {}
    except (IOError, OSError, ValueError):
        return {}


DEFAULT_SETTINGS = {'target': 25, 'band': 15, 'costPerMile': 0.30,
                    'pad': 0, 'secondsPerItem': 0}


def calibrated_config(existing, quad, pin, card_height, capture, lens_position):
    """The stored config with the geometry replaced and nothing else touched.

    Calibrating is about where the phone is, and nothing else. This used to
    build a fresh dict, so re-aiming the camera also put the driver's money back
    to the defaults — and the README tells you to re-run calibration whenever
    the mount moves, then tells you to keep your target and running costs in the
    same file. A driver on $32/hr and $0.62/mi came back to $25/hr and $0.30/mi
    and was not told. On the very offer this command reads back to prove itself,
    their own numbers say $25.0/hr PASS and the reset ones say $35.3/hr ACCEPT,
    which the rig then announces out loud. There is no second copy of those
    settings on the Pi to restore them from.

    Kept separate from main() so the guarantee can be tested without a camera.
    The last version of this regressed once already, and the test that would
    have caught it did not exist because the only way in was a hardware path.
    """
    config = dict(existing or {})
    config.update({
        'quad': [[float(x), float(y)] for x, y in quad],
        # Only written when asked for, and under a key nothing inherits: an
        # older config's `roi` must not act as a pin, or a rig upgrading gets
        # its crop frozen at whatever that version happened to write.
        'cropBox': pin,
        'cardHeight': card_height,
        'capture': {'width': capture[0], 'height': capture[1]},
        'lensPosition': lens_position,
    })
    config.setdefault('settings', dict(DEFAULT_SETTINGS))
    # The tracker's running position is the one thing that must NOT survive: it
    # is where the screen drifted to relative to corners that no longer exist.
    # Exposure measurements do survive, because they describe the phone's
    # backlight rather than where the camera is pointing.
    config.pop('trackedQuad', None)
    return config


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
    ap.add_argument('--box', help='manual override in fractions of the frame: x,y,w,h '
                                  '(0.1,0.3,0.8,0.4 is a wide band across the middle). '
                                  'Reads exactly that box and stops looking for the '
                                  'screen — the same thing ▣ Set box does on /live.html, '
                                  'for when you would rather type it than draw it')
    ap.add_argument('--full-screen', action='store_true',
                    help='pin the crop to the whole visible screen instead of '
                         'letting the scanner place it per read')
    ap.add_argument('--lens', type=float, default=None,
                    help='pin focus in dioptres (4.0 = 25cm) instead of autofocusing')
    args = ap.parse_args()

    width, height = FULL_FOV_MODES[args.mode]
    lens_position = args.lens
    if args.from_image:
        frame = cv2.imread(args.from_image)
        # The corners about to be detected are in this still's pixel space, so
        # the capture size recorded beside them has to be this still's too.
        # Taking it from --mode instead described a sensor the corners were
        # never measured on: an rpicam-still is 4656x3496 by default while
        # --mode defaults to 2328x1748, so the scanner warped a quad twice the
        # size of the frames it was given and read empty text off every one.
        # Nothing recovers from it either — the tracker gates candidates on the
        # calibrated size, so the real screen is refused on every check while
        # the health line goes on reporting "corners held, 0px from
        # calibration". Silent, total and permanent, from a still of the wrong
        # size and no warning anywhere.
        if frame is not None:
            height, width = frame.shape[:2]
    else:
        frame, lens_position = grab_from_camera((width, height), args.lens)
    if frame is None:
        sys.exit('could not read a frame')

    # What the corners are, and what that makes them mean. A box given in
    # fractions is a person saying "read this and nothing else", so it pins the
    # crop and is recorded as their choice; corners in pixels are still a
    # correction to where the *screen* is, and the crop is placed inside them
    # per read as usual.
    drawn = None
    if args.box:
        try:
            drawn = CX.parse_request(
                {'box': [float(n) for n in args.box.replace(' ', '').split(',')]})
        except ValueError as e:
            sys.exit('--box: %s' % e)
        quad = __import__('numpy').array(CX.in_pixels(drawn, (width, height)),
                                         dtype='float32')
    elif args.corners:
        nums = [float(n) for n in args.corners.replace(' ', '').split(',')]
        if len(nums) != 8:
            sys.exit('--corners needs 8 numbers')
        quad = PL.order_quad(__import__('numpy').array(nums, dtype='float32').reshape(4, 2))
    else:
        quad = PL.detect_screen_quad(frame)
        if quad is None:
            sys.exit('no screen found — is the phone lit and in frame? '
                     'else pass --corners, or --box to read a box of your own')

    pin = CX.PIN_WHOLE if drawn else (WHOLE_VIEW if args.full_screen else DEFAULT_ROI)
    share = 1.0 if drawn else None
    config = calibrated_config(load_existing(args.config), quad, pin,
                               args.card_height, (width, height), lens_position)
    if drawn:
        CX.apply_to_config(config, drawn, (width, height))
    else:
        config.pop(CX.MANUAL_KEY, None)
    write_config(args.config, config)

    # Write what the OCR engine will actually be handed, so a bad mount is
    # obvious before it costs a shift's worth of missed offers. Taken from a
    # real read rather than rebuilt, because the crop is placed per read now
    # and a rebuild would show a composition the scanner never uses.
    probe = PL.Scanner(quad=quad, roi=pin, card_height=args.card_height, card_share=share)
    checked = probe.read(frame)
    preview = checked['card']
    preview_path = os.path.splitext(args.config)[0] + '-preview.png'
    cv2.imwrite(preview_path, preview)

    print('wrote %s' % args.config)
    print('corners: %s' % config['quad'])
    if drawn:
        print('reading the box you gave ([%s] of the frame) and nothing else; '
              'corner tracking is off until the scanner is asked to re-find'
              % CX.describe(drawn))
    print('preview: %s  (%dx%d — the exact image tesseract will read)'
          % (preview_path, preview.shape[1], preview.shape[0]))

    # How big the card actually is on the sensor decides whether this works at
    # all. 2328x1748 is 2x2 binned, so the card has half the pixel density the
    # sensor's headline resolution suggests, and no amount of upscaling later
    # recovers detail the mount never captured.
    # Half a screen is the card when a screen was detected; all of it is the
    # card when a person drew the box round one, so halving that would report a
    # hand-drawn box as half the size it is and send the driver closer for no
    # reason.
    card_px = (int(round(PL.screen_height_px(quad, frame.shape))) if drawn
               else card_source_pixels(quad, frame.shape))
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

    parsed = checked['parsed']
    if parsed['complete']:
        print('\nread from this frame: $%.2f, %s min, %s mi — the calibration works'
              % (parsed['pay'], parsed['minutes'], parsed['miles']))
    else:
        print('\nnothing read from this frame. If there was an offer on the screen, '
              'the mount is not good enough yet; if there was not, that is expected.')
    print('Check the preview is a straight-on, sharp, glare-free offer card.')


def card_source_pixels(quad, shape=None):
    """Height, in real sensor pixels, of the offer card itself.

    Of the card, deliberately, and not of the crop around it. This number is
    what MIN_CARD_PIXELS is judged against, so it has to mean the same thing
    however much slack the crop is carrying — measure the crop instead and
    widening it for safety would silently pass mounts that are too far away,
    which is the opposite of safe.

    Pass `shape` (the frame the quad was found in) and a screen running off the
    frame is measured across instead of down. That case is the mount to want,
    not a fault: clipping the map away is what buys the resolution. But once the
    screen is taller than the frame, its visible height is the *frame's* height,
    so measuring down stops measuring the phone — the reading saturates, and
    moving the camera closer cannot make it go up. The one number you aim by
    would go dead at exactly the distances worth using.

    Across the screen nothing is missing, so the height is inferred from the
    width using the shortest aspect ratio phones come in. That errs low, which
    is the right way to err for a floor.

    The measuring itself lives in pipeline.screen_height_px, because the reader
    needs the same answer for a different reason — how tall to warp — and two
    copies of this geometry would be two things to get wrong.
    """
    import pipeline as PL
    return int(round(PL.screen_height_px(quad, shape) * PL.CARD_SHARE))


if __name__ == '__main__':
    main()
