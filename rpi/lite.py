"""Whether this rig runs as the lite edition: the camera, the reader and one card.

    import lite as LT
    if LT.on(cfg): ...

The owner, Nov 2026: some people want this program without the experimental
half — "just a means to read their phone screen with the camera, and the card
pay output card", a display and nothing to touch. Decided with him: lite is a
MODE of this repository, not a copy of it, so that every reading and
money-safety fix (CENTS_LOST, unsure_payout, money_is_clipped, the rescue
rules, the card finder, DoorDash's raise and evened read, the remembered crop)
reaches both the day it is made. A copy would have forked exactly the code
that decides what a driver is told an offer pays. See CLAUDE.md and lite/.

So the switch is one bit and it is read in two places, by name: here for the
scanner, and lite/lite.js for the server (which must agree with this file
word for word — rpi/test_lite.py holds the two to the same answers). What the
bit turns off on this side is only what reads more of the screen than the
verdict needs:

  - DoorDash's map label (MapLabels): an extra OCR pass per DoorDash card, on
    its own thread, whose one consumer is the ≈ drawing on Map view. Lite has
    no map.
  - the map bands (MapBands): collection for a geometry study, on another
    thread, written to disk. Nothing the driver sees comes from it.

What it never turns off: the reader, the parser, every money-safety rule, the
verdict, speech and the journal (the small local offers log). Those are not
features; they are the program.

THE ORDER OF ASKING. The environment's LITE wins when it says exactly '1' or
'0' — the service sets it (lite/install.sh), and the suites set both ways.
Otherwise `"lite": true` in rpi/config.json's `settings`, true only when it is
exactly true, the way carryTwo and screenDrop are read in server.js. Anything
else is the full rig: a missing file, a typo, "yes", 1. The full rig is what
this repository has always been, and a bit that fails open into it costs the
lite user a few idle threads, where one failing the other way would quietly
take the map away from the owner mid-shift.

READ ONCE, at the scanner's start. A mode is not a setting to flip between two
reads: what it gates are threads started at boot, and a restart (the service
does one in five seconds) is how a mode changes.
"""

import json
import os


def from_config(cfg):
    """`"lite": true` in a config's settings block, and nothing looser."""
    settings = cfg.get('settings') if isinstance(cfg, dict) else None
    return isinstance(settings, dict) and settings.get('lite') is True


def on(cfg=None, environ=None):
    """Is this the lite edition? LITE in the environment ('1' or '0') first,
    then the config's settings. `environ` is for the suites."""
    env = (os.environ if environ is None else environ).get('LITE')
    if env == '1':
        return True
    if env == '0':
        return False
    return from_config(cfg)


def on_file(path, environ=None):
    """The same, from a config file on disk — for a caller that has not loaded
    one (rpi/sync.py). An unreadable file is the full rig, as above."""
    cfg = None
    try:
        with open(path) as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        cfg = None
    return on(cfg, environ)


# Said once at the scanner's start, so a lite rig's log explains why the map
# label and the bands are never mentioned again.
SAYS = ('lite edition: the card, its verdict and the offers log only - no map '
        'label reads, no map bands (rpi/lite.py)')
