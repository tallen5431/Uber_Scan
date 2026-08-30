"""The files the web side and the camera side pass requests through.

Three of them, and they are all the same shape: the browser asks for something,
the scanner notices within a frame or two and acts.

    .viewing        somebody is watching, and which of the two views they want
    .recalibrate    forget where you think the phone is and find it again
    .cropbox.json   read this box, drawn by hand on the live picture

Files rather than a socket or a signal, because the scanner is sometimes a child
of the web server and sometimes a systemd unit that has never heard of it, and a
file works identically either way.

WHY THEY MOVED
They lived in `rpi/`, on the card. Every one of them exists for seconds — the
.gitignore has said so all along — and none of them should survive a reboot, so
the card was the wrong place on principle. It became the wrong place in practice
when `.viewing` started carrying which view the driver wants: the web side
rewrites it about once a second for as long as a browser is fetching frames.
The live frame moved to /dev/shm for exactly this reason and these were left
behind.

WHY THE RULE, AND NOT A LIST
The live frame is written by one side and read by the other, so `framePath` in
server.js can simply take whichever candidate is freshest and be right either
way. These are handshakes: a request written where the reader is not looking is
not a stale picture, it is a button that does nothing. So both sides answer the
same question the same way — is /dev/shm a directory this process can write to?
— and get the same answer, because they run as the same user. server.js has the
identical rule beside its own paths, and test_handoff.py holds the two to it.

The readers still look in the old place as well. Upgrading is a `git pull` that
moves both sides at once, but the scanner is a long-running process and the web
server is restarted more often, so the two really can be minutes apart on the
same machine — and during those minutes a button that silently does nothing is
the worst of the available outcomes.
"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))

# Kept out of /tmp deliberately: on a Pi that is the card as well, and systemd's
# PrivateTmp would give the scanner a different one from the server's.
RAM = '/dev/shm'


# One machine, more than one rig.
#
# The three filenames are fixed and the directory is shared with everything else
# on the box, so two copies of this project running at once — a second rig, a
# development checkout beside the live one, a test suite while the scanner is up
# — write to and consume each other's requests. A crop drawn on one screen moves
# the other one's camera. A test that reads a request a neighbouring process has
# already taken fails for a reason that has nothing to do with the code under
# test, which is worse than a bug: it teaches you to ignore a red suite.
#
# Set this and both sides use it. Honoured only when it names a directory this
# process can write to, so a stale value left in a profile cannot quietly
# disconnect the two halves of the rig — it falls back to the shared rule, which
# is the behaviour that was there before.
ENV_DIR = 'UBERSCAN_HANDOFF_DIR'


def _dir():
    """Where the requests go: asked for, else RAM, else the checkout.

    Answered per call rather than once at import, because the scanner is
    started before the desktop on a Pi and this file is imported early enough
    that a mount not yet up would be remembered as absent for the whole shift.
    Three syscalls that the kernel answers from cache; this is not the loop's
    expensive part.
    """
    asked = os.environ.get(ENV_DIR)
    if asked and os.path.isdir(asked) and os.access(asked, os.W_OK):
        return asked
    if os.path.isdir(RAM) and os.access(RAM, os.W_OK):
        return RAM
    return HERE


def _name(base):
    """The filename to use in whichever directory, keeping them apart.

    A dotfile is invisible in a checkout, which is right there and useless in a
    directory shared with every other program on the machine — /dev/shm is
    where you go to find out what is holding memory. Prefixed for the same
    reason `uberscan-live.jpg` is: so it is obvious whose it is and safe to
    delete.
    """
    return base if _dir() == HERE else 'uberscan-' + base.lstrip('.')


def path(base):
    """Where to write, and the first place to look."""
    return os.path.join(_dir(), _name(base))


def legacy(base):
    """The checkout copy, which readers still honour. May be the same file."""
    return os.path.join(HERE, base)


def candidates(base):
    """Everywhere a reader should look, best first, without duplicates."""
    found = []
    for candidate in (path(base), legacy(base)):
        if candidate not in found:
            found.append(candidate)
    return found


def clear(base):
    """Drop the request everywhere it might be.

    Both places, always. A reader that removes only the copy it read leaves the
    other to be picked up later — and a `.recalibrate` acted on an hour after it
    was asked for is the scanner throwing away a good calibration mid-shift for
    no reason the driver can see.
    """
    for candidate in candidates(base):
        try:
            os.remove(candidate)
        except OSError:
            pass


VIEWING = '.viewing'
RECALIBRATE = '.recalibrate'
CROPBOX = '.cropbox.json'
# "The screen in front of you is the destination — read it as an address."
#
# The fourth request, and the only one that is about what a read MEANS rather
# than about where to point. An offer card does not say where a delivery ends;
# Uber prints "Customer dropoff" and the address arrives on the screen after the
# accept. So the driver presses a button, this appears, and the scanner takes a
# reading whether the picture moved or not — because a phone sitting in a mount
# showing a navigation screen is exactly what the motion gate calls "nothing
# happening".
DROPOFF = '.dropoff'


# The live picture is the fourth file the two sides share, and it moved here
# first — twenty-five frames a second at ~50kB while somebody is watching, all
# of it stale two frames later, none of it worth the one part of a Pi that
# wears out. Its names predate this module and are kept exactly: server.js
# lists both in FRAME_CANDIDATES and picks whichever is freshest.
FRAME_RAM = 'uberscan-live.jpg'
FRAME_LEGACY = 'live-frame.jpg'


def frame():
    """Where to leave the live view.

    Here rather than in scan_pi so the autopilot can answer the same question
    without importing the OCR stack — it checks that the dependencies are
    installed before touching any of them, which is the whole point of its
    first phase, and `import scan_pi` at the top of that file would import cv2
    to find out whether cv2 is importable.

    It was two answers before that: the scanner picked RAM, the autopilot's
    aiming phase wrote to the card regardless, and the web side had to choose
    between them by mtime — which worked, and meant the picture a driver aims
    the mount by and the picture they watch offers on were different files.
    """
    return os.path.join(RAM if _dir() == RAM else HERE,
                        FRAME_RAM if _dir() == RAM else FRAME_LEGACY)
