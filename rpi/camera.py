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
import re

# Tuning lives per ISP pipeline: pisp on Pi 5, vc4 on Pi 4 and earlier, and a
# flat directory on older libcamera. These are NOT interchangeable — a Pi 5
# tuning describes an ISP a Pi 4 does not have — so the running pipeline decides
# the order rather than a fixed preference.
PISP_DIR = '/usr/share/libcamera/ipa/rpi/pisp'
VC4_DIR = '/usr/share/libcamera/ipa/rpi/vc4'
LEGACY_DIR = '/usr/share/libcamera/ipa/raspberrypi'


def pi_model():
    try:
        with open('/proc/device-tree/model') as fh:
            return fh.read().strip('\x00').strip()
    except OSError:
        return ''


def tuning_dirs():
    """Directories to load from: only the pipeline this machine actually runs.

    Not a preference order — a hard restriction. A pisp tuning describes an ISP
    a Pi 4 does not have, and handing one to the vc4 pipeline does not degrade
    gracefully: libcamera fails to load the IPA, registers no cameras, and
    picamera2 dies with an IndexError about an empty list. That happened, and
    the reason it happened is that the search fell through to pisp looking for
    autofocus and found it there. Better no autofocus than no camera.
    """
    if 'Raspberry Pi 5' in pi_model():
        return [PISP_DIR, LEGACY_DIR]
    return [VC4_DIR, LEGACY_DIR]


TUNING_DIRS = tuning_dirs()

# Everything on disk, for reporting. Seeing that an autofocus-capable tuning
# exists but sits in the wrong pipeline's directory is exactly the diagnosis
# someone needs, so doctor.py should show it even though nothing will load it.
ALL_DIRS = [PISP_DIR, VC4_DIR, LEGACY_DIR]

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
    for directory in ALL_DIRS + ['/usr/share/libcamera/ipa/rpi/*']:
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
        # Arducam's packages drop extra tuning beside the stock file rather than
        # replacing it, so the whole directory is worth looking at — but only
        # this pipeline's directory. Reaching into another ISP's tuning to find
        # autofocus takes the camera down entirely.
        seen.extend(sorted(glob.glob(os.path.join(directory, sensor + '*.json'))))

    ordered = []
    for path in seen:
        if path not in ordered:
            ordered.append(path)

    for path in ordered:
        if _has_af(path):
            return path, True
    return (ordered[0] if ordered else None), False


def sensor_from_device_tree():
    """The attached sensor, without starting libcamera.

    Needed because LIBCAMERA_RPI_TUNING_FILE is read when the camera manager
    registers cameras. Asking picamera2 for the sensor name starts that manager,
    so anything decided afterwards arrives too late to matter.
    """
    for pattern in ('/proc/device-tree/soc/*/*/*@*', '/proc/device-tree/soc/*/*@*'):
        for path in sorted(glob.glob(pattern)):
            name = os.path.basename(path).split('@')[0]
            if re.match(r'^(imx|ov)\d+', name):
                return name
    return None


def sensor_name(default='imx519'):
    found = sensor_from_device_tree()
    if found:
        return found
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

    # Anything inherited from a parent process is untrustworthy — most likely a
    # temp file that no longer exists — and it is read before we get a say.
    inherited = os.environ.get('LIBCAMERA_RPI_TUNING_FILE')
    if inherited and not os.path.exists(inherited):
        os.environ.pop('LIBCAMERA_RPI_TUNING_FILE', None)

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

    # Only override when overriding actually buys something. libcamera loads the
    # tuning for the running pipeline by itself, and if that file already has
    # autofocus there is nothing to fix — pointing it elsewhere would risk
    # handing a vc4 pipeline a tuning written for a different ISP.
    default_path = os.path.join(TUNING_DIRS[0], sensor + '.json')
    default_has_af = _has_af(default_path)
    focus['pipelineDefault'] = default_path if os.path.exists(default_path) else None

    if default_has_af:
        focus['tuning'] = default_path
        os.environ.pop('LIBCAMERA_RPI_TUNING_FILE', None)
    elif tuning_path and prefer_autofocus and has_af:
        # Point libcamera at the real file on disk. Handing picamera2 a loaded
        # dict instead makes it write a temp file and set the variable to that
        # path — fine until it is inherited across an exec, because the temp
        # file dies with the process that made it.
        os.environ['LIBCAMERA_RPI_TUNING_FILE'] = tuning_path
    else:
        # Never leave an inherited value behind: a stale one points at a file
        # that no longer exists and takes the camera down with it.
        os.environ.pop('LIBCAMERA_RPI_TUNING_FILE', None)

    # A camera that failed to register surfaces as an empty list and then an
    # IndexError from deep inside picamera2, which says nothing useful.
    if not Picamera2.global_camera_info():
        raise RuntimeError(
            'libcamera registered no cameras. If the log above mentions a tuning '
            'file it could not open, that file is missing or unreadable: '
            'LIBCAMERA_RPI_TUNING_FILE=%s'
            % os.environ.get('LIBCAMERA_RPI_TUNING_FILE', '(unset)'))

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
