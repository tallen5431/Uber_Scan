"""Tests for the box a driver draws by hand.

    python3 rpi/test_cropbox.py

This is the escape hatch for the case where the automatic screen finder is
wrong, so it has to work when nothing else does — which means no camera, no
OCR engine and no numpy in the way of testing it. Everything here is the
arithmetic and the validation between a drag on a phone and the corners the
scanner reads from.
"""

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cropbox as CX

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


def refuses(name, payload, contains=None):
    global ok, bad
    try:
        CX.parse_request(payload)
    except ValueError as e:
        if contains and contains not in str(e):
            bad += 1
            print('FAIL  %s: refused, but said %r' % (name, str(e)))
        else:
            ok += 1
    else:
        bad += 1
        print('FAIL  %s: accepted' % name)


# --- a dragged rectangle ----------------------------------------------------

quad = CX.parse_request({'box': [0.1, 0.2, 0.5, 0.6]})
eq('a box becomes four corners, clockwise from top-left', quad,
   [[0.1, 0.2], [0.6, 0.2], [0.6, 0.8], [0.1, 0.8]])

# The live view is a 480px JPEG of a 2328px sensor frame. Fractions are the
# only thing that survives that, and getting it wrong is the failure calibration
# already has a long comment about: corners measured against one size, read
# against another, refused on every check forever.
eq('fractions scale into whatever the capture size is',
   CX.in_pixels(quad, (2328, 1748)),
   [[232.8, 349.6], [1396.8, 349.6], [1396.8, 1398.4], [232.8, 1398.4]])
eq('and back again', CX.as_fractions(CX.in_pixels(quad, (2328, 1748)), (2328, 1748)), quad)

# A drag that runs off the picture is an ordinary way to say "out to the edge" —
# on the mount that actually works the phone screen does run off the frame.
eq('a drag past the edge is clamped, not refused',
   CX.parse_request({'box': [0.8, 0.8, 0.5, 0.5]}),
   [[0.8, 0.8], [1.0, 0.8], [1.0, 1.0], [0.8, 1.0]])
eq('a drag that starts off the top-left is clamped too',
   CX.parse_request({'box': [-0.2, -0.1, 0.6, 0.6]}),
   [[0.0, 0.0], [0.6, 0.0], [0.6, 0.6], [0.0, 0.6]])

# --- four corners, for a screen that is not square-on -----------------------

skewed = CX.parse_request({'quad': [[0.62, 0.19], [0.11, 0.22], [0.13, 0.79], [0.60, 0.83]]})
eq('corners are ordered however they arrive', skewed,
   [[0.11, 0.22], [0.62, 0.19], [0.60, 0.83], [0.13, 0.79]])

# --- what must be refused ---------------------------------------------------

refuses('a mis-tap is not a box', {'box': [0.5, 0.5, 0.01, 0.01]}, 'too small')
refuses('...however it is spelled', {'quad': [[0.5, 0.5], [0.51, 0.5],
                                              [0.51, 0.51], [0.5, 0.51]]}, 'too small')
refuses('a box needs four numbers', {'box': [0.1, 0.2, 0.5]})
refuses('a quad needs four corners', {'quad': [[0.1, 0.2], [0.5, 0.6]]})
refuses('corners are pairs', {'quad': [0.1, 0.2, 0.5, 0.6]})
refuses('text is not a coordinate', {'box': [0.1, 0.2, '0.5', 0.6]}, 'numbers')
refuses('nor is a boolean', {'box': [0.1, 0.2, True, 0.6]}, 'numbers')
refuses('nor is a NaN', {'box': [0.1, 0.2, float('nan'), 0.6]}, 'numbers')
refuses('an empty request says what it wanted', {}, 'box or a quad')
refuses('and so does something that is not one', 'a box', 'box or a quad')

# --- what it does to the config --------------------------------------------

# A box drawn by hand means "read exactly this". The automatic path derives a
# crop inside the quad because it knows the quad is a whole phone screen and
# cards differ in height; nothing knows that about a hand-drawn box.
lived_in = {
    'settings': {'target': 32, 'costPerMile': 0.62},
    'quad': [[0, 0], [10, 0], [10, 10], [0, 10]],
    'trackedQuad': [[5, 5], [15, 5], [15, 15], [5, 15]],
    'exposureTime': 33333,
    'analogueGain': 4.1,
}
config = CX.apply_to_config(dict(lived_in), quad, (2328, 1748))
eq('the corners become the drawn box', config['quad'], CX.in_pixels(quad, (2328, 1748)))
eq('the crop is pinned to all of it', config['cropBox'], [0.0, 0.0, 1.0, 1.0])
ok_('and it is marked as a person\'s choice', config[CX.MANUAL_KEY])
ok_('where the screen had drifted to cannot survive', 'trackedQuad' not in config)
eq('the driver\'s money is not calibration and is not touched',
   config['settings'], lived_in['settings'])
eq('nor is the exposure this phone was measured at', config['exposureTime'], 33333)

cleared = CX.clear_in_config(dict(config))
ok_('re-finding drops the flag', CX.MANUAL_KEY not in cleared)
ok_('...and the pin with it, or the derived crop never comes back',
    'cropBox' not in cleared)
eq('...leaving the corners as the place to start looking from',
   cleared['quad'], config['quad'])

# --- the handover file ------------------------------------------------------

work = tempfile.mkdtemp()
try:
    path = os.path.join(work, '.cropbox.json')
    eq('no request is not an error', CX.take_request(path), None)

    CX.write_request(quad, path)
    eq('a written request comes back as it went in', CX.take_request(path), quad)
    ok_('...and is gone once taken', not os.path.exists(path))
    eq('...so it is applied once, not on every frame forever',
       CX.take_request(path), None)

    with open(path, 'w') as fh:
        fh.write('{"box": [0.1, 0.2, 0.5')
    eq('half a file is not a box', CX.take_request(path), None)
    ok_('...and is still cleared away, or it would be retried for the whole shift',
        not os.path.exists(path))

    with open(path, 'w') as fh:
        json.dump({'box': [0.5, 0.5, 0.001, 0.001]}, fh)
    eq('a mis-tap that reached the file is ignored too', CX.take_request(path), None)
finally:
    shutil.rmtree(work, ignore_errors=True)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d crop-box checks passed' % ok)
sys.exit(1 if bad else 0)
