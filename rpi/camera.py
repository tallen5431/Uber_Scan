"""Opening the camera, and the surprising business of whether it can focus.

The IMX519 has a motorised lens, and libcamera advertises AfMode for it, but
whether autofocus actually *works* depends on the tuning file in use. Raspberry
Pi's stock imx519.json carries no autofocus algorithm, so setting AfMode logs

    WARN IPARPI ipa_base.cpp:797 Could not set AF_MODE - no AF algorithm

and the lens stays wherever it was — which is usually out of focus. LensPosition
is applied by that same algorithm, so manual focus is dead too. Advertised
controls are therefore not evidence; the tuning file is.

This finds a tuning file that does contain the algorithm and loads it, and when
there is none it says so plainly instead of silently doing nothing.
"""

import glob
import json
import os

# Where tuning files live, newest layouts first. pisp is Pi 5, vc4 is Pi 4 and
# earlier, and the flat directory is older libcamera.
TUNING_DIRS = [
    '/usr/share/libcamera/ipa/rpi/pisp',
    '/usr/share/libcamera/ipa/rpi/vc4',
    '/usr/share/libcamera/ipa/raspberrypi',
]

AF_KEY = 'rpi.af'

LOCK_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.camera.lock')
_lock_handle = None


class CameraBusy(RuntimeError):
    """Something else already holds the camera."""


def acquire_lock():
    """Take the camera lock, or return False if another process has it.

    libcamera allows exactly one holder, and losing that race produces a
    traceback about acquiring a device that says nothing about which of your own
    programs is already running. The lock is advisory between our own scripts,
    which is precisely where the confusion was.
    """
    global _lock_handle
    import fcntl

    fh = open(LOCK_PATH, 'a+')
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.seek(0)
        holder = fh.read().strip()
        fh.close()
        raise CameraBusy(
            'the camera is already in use by this project (pid %s). It is most '
            'likely the scanner started by the web server — check /api/status, '
            'or stop it with SCANNER=0, before running a camera script by hand.'
            % (holder or 'unknown'))
    fh.seek(0)
    fh.truncate()
    fh.write(str(os.getpid()))
    fh.flush()
    _lock_handle = fh          # held open for the life of the process
    return True


def _has_af(path):
    try:
        with open(path) as fh:
            data = json.load(fh)
    except Exception:
        return False
    # The file is either {"algorithms": [ {...}, ... ]} or an older flat map.
    algorithms = data.get('algorithms', data)
    if isinstance(algorithms, list):
        return any(AF_KEY in entry for entry in algorithms if isinstance(entry, dict))
    return AF_KEY in algorithms


def tuning_report(sensor=None):
    """Every tuning file for this sensor and whether it can actually focus.

    Worth printing rather than summarising: rpicam-apps advertises
    --autofocus-mode for every camera because the flag is compiled in, not
    because the sensor can use it. The tuning file is the only thing that
    settles it.
    """
    sensor = sensor or sensor_name()
    found = []
    for directory in TUNING_DIRS + ['/usr/share/libcamera/ipa/rpi/*']:
        for path in sorted(glob.glob(os.path.join(directory, sensor + '*.json'))):
            if path not in [f[0] for f in found]:
                found.append((path, _has_af(path)))
    return sensor, found


def find_tuning(sensor):
    """Return (path, has_af) for the best tuning file available for this sensor.

    Prefers one with autofocus. Falls back to whatever exists so the caller can
    report precisely what is wrong rather than guessing.
    """
    seen = []
    for directory in TUNING_DIRS:
        seen.extend(sorted(glob.glob(os.path.join(directory, sensor + '*.json'))))
    # Arducam's packages drop tuning beside their drivers rather than in the
    # standard directories.
    seen.extend(sorted(glob.glob('/usr/share/libcamera/ipa/rpi/*/' + sensor + '*.json')))

    ordered = []
    for path in seen:
        if path not in ordered:
            ordered.append(path)

    for path in ordered:
        if _has_af(path):
            return path, True
    return (ordered[0] if ordered else None), False


def sensor_name(default='imx519'):
    try:
        from picamera2 import Picamera2
        info = Picamera2.global_camera_info()
        if info:
            return info[0].get('Model', default)
    except Exception:
        pass
    return default


def open_camera(prefer_autofocus=True):
    """Open the camera, loading an autofocus-capable tuning file when one exists.

    Returns (cam, focus) where focus describes what is actually possible:
      supported  — the lens can be driven at all
      tuning     — the file in use
      reason     — why not, when it cannot
    """
    from picamera2 import Picamera2

    acquire_lock()
    sensor = sensor_name()

    # An explicit override wins: if Arducam's tuning is installed somewhere
    # non-standard, pointing at it is the whole fix.
    override = os.environ.get('UBERSCAN_TUNING')
    if override and os.path.exists(override):
        tuning_path, has_af = override, _has_af(override)
    else:
        tuning_path, has_af = find_tuning(sensor)

    focus = {'sensor': sensor, 'tuning': tuning_path, 'supported': has_af, 'reason': None}

    if not has_af:
        focus['reason'] = (
            'the tuning file for %s has no autofocus algorithm, so libcamera cannot '
            'move the lens (it logs "Could not set AF_MODE - no AF algorithm"). '
            'Install Arducam\'s tuning for this module, or focus the lens by hand.'
            % sensor)

    if tuning_path and prefer_autofocus and has_af:
        cam = Picamera2(tuning=Picamera2.load_tuning_file(os.path.basename(tuning_path),
                                                          dir=os.path.dirname(tuning_path)))
    else:
        cam = Picamera2()

    return cam, focus


def apply_focus(cam, focus, lens=None):
    """Pin or autofocus, and report what actually happened.

    Never claims success from the presence of a control: a fixed-focus module
    and a broken tuning both advertise AfMode.
    """
    if not focus.get('supported') or 'AfMode' not in cam.camera_controls:
        return None

    from libcamera import controls

    if lens is not None:
        cam.set_controls({'AfMode': controls.AfModeEnum.Manual, 'LensPosition': lens})
        return lens

    cam.set_controls({'AfMode': controls.AfModeEnum.Auto})
    try:
        cam.autofocus_cycle()
    except Exception:
        pass
    try:
        return cam.capture_metadata().get('LensPosition')
    except Exception:
        return None
