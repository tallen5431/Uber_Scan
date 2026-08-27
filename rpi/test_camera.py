"""Opening the camera: which tuning file, and who already has it.

    python3 rpi/test_camera.py

Nothing here needs a camera. Everything here decides whether the rig gets one.

Two of these have already gone wrong on real hardware. Searching every tuning
directory for one that mentions autofocus found a Pi 5 file on a Pi 4, and
handing a pisp tuning to the vc4 pipeline does not degrade politely — libcamera
fails to load the IPA, registers no cameras at all, and picamera2 dies with an
IndexError about an empty list. Better no autofocus than no camera, so the
running pipeline is a hard restriction rather than a preference, and this is
where that restriction is held.

The other is the lock. libcamera allows exactly one holder, and losing that race
used to produce a traceback about acquiring a device that named neither of the
two programs involved — while the answer, every time, was that the scanner
started by the web server already had it.

The tuning search is exercised against a directory tree built here rather than
against whatever this machine happens to have installed, because the interesting
cases are the ones a development machine does not have: two tunings for one
sensor where only the second can focus, an autofocus file sitting in the wrong
pipeline's directory, and a file that is not JSON at all.
"""

import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import camera as CAM                                          # noqa: E402

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


work = tempfile.mkdtemp()


def tuning(directory, name, af, broken=False):
    """One tuning file on disk, with or without the autofocus algorithm."""
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, name)
    with open(path, 'w') as fh:
        if broken:
            fh.write('{ this is not json')
        else:
            algorithms = [{'rpi.black_level': {}}]
            if af:
                algorithms.append({CAM.AF_KEY: {'ranges': {}}})
            json.dump({'version': 2.0, 'algorithms': algorithms}, fh)
    return path


# --- which pipeline's tuning, which is the one that bricked a rig -----------
#
# Not a preference order — a restriction. A pisp tuning describes an ISP a Pi 4
# does not have, and the search fell through to it looking for autofocus.
def dirs_for(model):
    real = CAM.pi_model
    try:
        CAM.pi_model = lambda: model
        return CAM.tuning_dirs()
    finally:
        CAM.pi_model = real


four = dirs_for('Raspberry Pi 4 Model B Rev 1.5')
five = dirs_for('Raspberry Pi 5 Model B Rev 1.0')
ok_('a Pi 4 is given the vc4 pipeline', CAM.VC4_DIR in four)
ok_('...and never the pisp one', CAM.PISP_DIR not in four)
ok_('a Pi 5 is given the pisp pipeline', CAM.PISP_DIR in five)
ok_('...and never the vc4 one', CAM.VC4_DIR not in five)
# Older libcamera keeps tuning in one flat directory with no pipeline in the
# path, so it is safe on both and belongs on both.
ok_('both fall back to the flat legacy directory', CAM.LEGACY_DIR in four
    and CAM.LEGACY_DIR in five)
# An unreadable /proc/device-tree/model is a machine we know nothing about, and
# the only safe guess is the pipeline that cannot take a camera down.
ok_('a machine that will not say what it is gets the safe pipeline',
    CAM.PISP_DIR not in dirs_for(''))

# ...and the report, which is deliberately the other way round: it shows every
# file on the machine, including the ones nothing will load, because "there is
# an autofocus tuning here but it is for the wrong ISP" is precisely the
# diagnosis somebody needs.
ok_('the report looks wider than the loader', len(CAM.ALL_DIRS) > len(four) - 1)
ok_('...and covers both pipelines', CAM.PISP_DIR in CAM.ALL_DIRS
    and CAM.VC4_DIR in CAM.ALL_DIRS)

# --- is this file one that can focus ---------------------------------------
plain = tuning(os.path.join(work, 'vc4'), 'imx519.json', af=False)
focus = tuning(os.path.join(work, 'vc4'), 'imx519_af.json', af=True)
broken = tuning(os.path.join(work, 'vc4'), 'imx519_bad.json', af=False, broken=True)

ok_('a tuning with the autofocus algorithm says so', CAM._has_af(focus))
ok_('...and one without it does not', not CAM._has_af(plain))
ok_('a file that is not JSON is not autofocus', not CAM._has_af(broken))
ok_('...nor is a file that is not there',
    not CAM._has_af(os.path.join(work, 'nothing.json')))

# The older layout is a flat map rather than a list under "algorithms", and a
# reader that only understands one of the two shapes reports no autofocus on a
# camera that has it — which reads identically to a camera that does not.
flat = os.path.join(work, 'vc4', 'imx519_flat.json')
with open(flat, 'w') as fh:
    json.dump({CAM.AF_KEY: {'ranges': {}}, 'rpi.black_level': {}}, fh)
ok_('the older flat layout is understood too', CAM._has_af(flat))

# --- picking one -----------------------------------------------------------
def pick(directories, sensor='imx519'):
    real = CAM.TUNING_DIRS
    try:
        CAM.TUNING_DIRS = directories
        return CAM.find_tuning(sensor)
    finally:
        CAM.TUNING_DIRS = real


path, has_af = pick([os.path.join(work, 'vc4')])
eq('the file that can focus is the one chosen', path, focus)
ok_('...and it is reported as focusing', has_af)

# Arducam's packages drop their tuning beside the stock file rather than
# replacing it, so a directory holding both has to yield the better one — which
# is why the whole directory is globbed rather than one expected filename.
only_plain = os.path.join(work, 'plainonly')
stock = tuning(only_plain, 'imx519.json', af=False)
path, has_af = pick([only_plain])
eq('a directory with no autofocus tuning still yields a file', path, stock)
ok_('...reported honestly as not focusing', not has_af)
# The caller needs the path even then: "there is a tuning and it cannot focus"
# and "there is no tuning at all" are different faults with different fixes.
path, has_af = pick([os.path.join(work, 'empty')])
eq('a sensor with no tuning at all yields nothing', path, None)
ok_('...and does not claim to focus', not has_af)

# The restriction again, from the other end: an autofocus tuning sitting in a
# directory this pipeline does not use must not be reached for.
wrong = os.path.join(work, 'pisp')
tuning(wrong, 'imx519.json', af=True)
path, has_af = pick([only_plain])
eq('autofocus in another pipeline\'s directory is not borrowed', path, stock)
ok_('...and is not claimed', not has_af)

# Only this sensor's files. A tuning for the camera that is not attached is not
# a fallback, it is a different camera.
other = os.path.join(work, 'mixed')
tuning(other, 'ov5647.json', af=True)
mine = tuning(other, 'imx708.json', af=False)
path, has_af = pick([other], sensor='imx708')
eq('another sensor\'s tuning is not used', path, mine)

# --- what is attached, without starting libcamera --------------------------
#
# It has to be answered before the camera manager registers anything, because
# LIBCAMERA_RPI_TUNING_FILE is read at that moment and a decision made after it
# arrives too late to matter.
def named(tree):
    """sensor_from_device_tree against a device tree built here."""
    real = CAM.glob.glob
    try:
        CAM.glob.glob = lambda pattern: tree.get(pattern, [])
        return CAM.sensor_from_device_tree()
    finally:
        CAM.glob.glob = real


eq('the sensor is read out of the device tree',
   named({'/proc/device-tree/soc/*/*/*@*':
          ['/proc/device-tree/soc/i2c0mux/i2c@1/imx519@1a']}), 'imx519')
eq('...on the shallower path too',
   named({'/proc/device-tree/soc/*/*@*':
          ['/proc/device-tree/soc/i2c@7e205000/ov5647@36']}), 'ov5647')
# Everything else on that bus is not a camera. Matching loosely here names a
# power controller as the sensor and then looks for its tuning file.
eq('a node that is not a camera sensor is not one',
   named({'/proc/device-tree/soc/*/*/*@*':
          ['/proc/device-tree/soc/i2c0mux/i2c@1/pca9546@70']}), None)
eq('...and nothing at all is nothing', named({}), None)

# The fallback, for a machine whose device tree says nothing and which has no
# picamera2 to ask. A default is better than a crash: it names the sensor this
# rig ships with, and every path below it reports honestly if that is wrong.
real_tree = CAM.sensor_from_device_tree
try:
    CAM.sensor_from_device_tree = lambda: None
    eq('a machine with nothing to go on falls back',
       CAM.sensor_name(default='imx296'), 'imx296')
finally:
    CAM.sensor_from_device_tree = real_tree

# --- and who already holds the camera --------------------------------------
#
# libcamera allows one holder. Losing that race produced a traceback about
# acquiring a device that named neither program, when the answer was always the
# scanner the web server had already started.
HOLDER = '''
import os, sys, time
sys.path.insert(0, %r)
import camera
camera.LOCK_PATH = %r
camera.acquire_lock()
print('held', flush=True)
time.sleep(30)
'''

lock_path = os.path.join(work, '.camera.lock')
holder = subprocess.Popen(
    [sys.executable, '-c', HOLDER % (os.path.dirname(os.path.abspath(__file__)),
                                     lock_path)],
    stdout=subprocess.PIPE, text=True)
try:
    ok_('a first holder takes the lock', holder.stdout.readline().strip() == 'held')

    real_path, real_handle = CAM.LOCK_PATH, CAM._lock_handle
    try:
        CAM.LOCK_PATH = lock_path
        CAM._lock_handle = None
        try:
            CAM.acquire_lock()
            eq('a second holder is refused', 'taken it', 'refused')
        except CAM.CameraBusy as e:
            ok_('a second holder is refused', True)
            # The whole point of the message. A pid the driver can act on beats
            # a stack trace about a device node.
            ok_('...naming the pid that has it', str(holder.pid) in str(e))
            ok_('...and where to look', '/api/status' in str(e))
        except Exception as e:
            eq('a second holder is refused', e.__class__.__name__, 'CameraBusy')
    finally:
        CAM.LOCK_PATH, CAM._lock_handle = real_path, real_handle
finally:
    holder.terminate()
    try:
        holder.wait(timeout=5)
    except Exception:
        holder.kill()

# ...and once it is gone the lock is free again. A lock that outlived its holder
# would need clearing by hand on a rig with no keyboard.
free_path = os.path.join(work, '.free.lock')
real_path, real_handle = CAM.LOCK_PATH, CAM._lock_handle
try:
    CAM.LOCK_PATH = free_path
    CAM._lock_handle = None
    ok_('the lock is free once nobody holds it', CAM.acquire_lock())
    ok_('...and the file names the holder',
        open(free_path).read().strip() == str(os.getpid()))
finally:
    if CAM._lock_handle:
        CAM._lock_handle.close()
    CAM.LOCK_PATH, CAM._lock_handle = real_path, real_handle

# --- the log the rig produces ----------------------------------------------
#
# libcamera narrates seven lines to stderr every time the camera is opened, and
# it is opened twice per run. A supervisor tagging stderr as an error files all
# of it under errors, so the log a person pastes back is mostly that.
eq('libcamera is quietened before picamera2 is imported',
   os.environ.get('LIBCAMERA_LOG_LEVELS'), '*:WARN')

import shutil                                                 # noqa: E402
shutil.rmtree(work, ignore_errors=True)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d camera checks passed' % ok)
sys.exit(1 if bad else 0)
