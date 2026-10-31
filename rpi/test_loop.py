"""The scan loop, driven over the fake camera with a stubbed reader.

    python3 rpi/test_loop.py

test_scan_pi.py drives the real loop over the real reader, which is minutes
of tesseract. This drives the same loop — scan_pi.main(), the accumulator,
the journal, the announcements — with the reader replaced by a function that
answers with whatever text the check needs, so a fault in what the loop
DOES with a reading can be reached in seconds and without a card render
that happens to read the way the check wants.

Each check here failed against the loop before its fix:

- The offer told to the driving screen was frozen at the first locked
  reading, which can be a fragment with no address, while a later frame
  landed the whole card in the journal.
- One misread frame of a recorded card counted as a card seen and never
  recorded, on the health line and the offers page.
- A read that never returned left the rig beating and silent, and the
  supervisor's silence watchdog could not see it.
- The startup line counted journal lines and called them offers.
- ⟳ Re-find, pressed with a box drawn, threw the boxes away. It is gone; a
  request an older page left behind must not do it either.

One warning about the stubbed reader, because it cost an afternoon here: it
answers with whatever text the check asked for WHETHER OR NOT THERE IS A CARD
IN FRONT OF IT. So a read, and an offer announced off it, happen on the first
frame of every run, before anything is in the mount — neither is evidence that
the camera can see a card. A check that needs one there must ask the camera
(`cam_out`), not the loop.
"""

import json
import os
import re
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('OMP_THREAD_LIMIT', '1')

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


try:
    import cv2
    import numpy as np
    import testcards as TC
    import pipeline as PL
    import offer_parser as OP
    import handoff as HO
    import scan_pi as SP
except ImportError as e:
    print('%s — skipping the loop checks' % e)
    sys.exit(0)

if not TC.available():
    print('no PIL or no usable font — skipping the loop checks')
    sys.exit(0)

LORES = (640, 480)
CAP = (2328, 1748)


class Request(object):
    def __init__(self, cam):
        self.cam = cam

    def make_buffer(self, name):
        return self.cam.lores.tobytes()

    def make_array(self, name):
        return self.cam.frame.copy()

    def release(self):
        pass


# A sensor's noise, as far as the stall watch can tell: the lowest bit of half
# the pixels flipped, a different half on every capture.
#
# A real camera, on testcards' model of its sensor, never hands over the same
# picture twice — every pixel carries its own noise; whether the IMX519 agrees
# is what scan_pi's repeats count is for — and these are renders, which do:
# replayed at this fake's own pace, a capture every 10ms for 12 seconds, 1,199
# of 1,200 consecutive pairs of frames were identical, the one exception being
# the card arriving. The loop reads a repeated picture as a stalled camera
# (scan_pi.STALL_SAY), so without this every fake here would be a camera that
# stalled the moment its card stopped moving. One level of difference is all it takes and nothing
# else can see it: measured on this suite's card, its empty cabin and a black
# one, two captures 1, 2, 5, 100 or 3,000 apart move the motion gate by 0.505
# at most, against the 2.0 it calls still.
#
# A different half on EVERY capture, as a sensor's is, and not a few patterns
# taken in turn. That was two, which the watch's eight frames back
# (scan_pi.Repeats) see straight through: run that way, the still card below
# was written as stalled 7.3 to 7.6 seconds in, three runs of three, with
# nearly 400 frames counted as repeats on the health line. Each capture's half
# is a window into one long random run, moved along by the capture's number,
# so no two are alike for NOISE_SPAN captures — longer than any run here.
NOISE_SPAN = 1 << 14
NOISE = np.random.RandomState(11).randint(0, 2, LORES[0] * LORES[1] + NOISE_SPAN) \
    .astype(np.uint8)


def dither(n):
    """Capture `n`'s noise: one level, in half the preview's pixels."""
    off = n % NOISE_SPAN
    return NOISE[off:off + LORES[0] * LORES[1]]


class FakeCam(object):
    """A card that appears in the mount shortly after the loop starts.

    `fail_after`: from that capture on, raise this exception instead of
    answering — a RuntimeError is a camera that died, SystemExit is the
    supervisor's SIGTERM as _stop_on_sigterm turns it into one.
    `freeze_at`: from this many seconds in, hand over the very same picture
    on every capture — a stalled camera, which is what the dither above
    exists to tell apart from a still one — or, with `ring`, the last `ring`
    pictures in turn: a camera stuck handing back its buffers, no frame the
    same as the one before it. A list of (from, to) spans instead is a camera
    that stalls and comes back, `to` None for one that stays stalled.
    `noise=False` leaves the dither off, for the pictures that repeat on a
    working camera: ones with nothing in them that could show noise."""

    def __init__(self, offer, empty, appear_at=0.4, fail_after=None, freeze_at=None,
                 noise=True, ring=1):
        self.offer, self.empty = offer, empty
        self.appear_at = appear_at
        self.started = time.time()
        self.fail_after = fail_after
        self.freeze_at = freeze_at
        self.noise = noise
        self.ring = ring
        self.captures = 0
        self.history = []
        self._show()

    def _show(self):
        t = time.time() - self.started
        self.frame = self.offer if t >= self.appear_at else self.empty
        grey = cv2.cvtColor(self.frame, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(grey, LORES, interpolation=cv2.INTER_AREA).ravel()
        if self.noise:
            small = small ^ dither(self.captures)
        self.lores = np.concatenate([small,
                                     np.full(LORES[0] * LORES[1] // 2, 128, np.uint8)])
        self.history = (self.history + [self.lores])[-self.ring:]

    def frozen(self):
        if self.freeze_at is None:
            return False
        t = time.time() - self.started
        spans = (self.freeze_at if isinstance(self.freeze_at, (list, tuple))
                 else [(self.freeze_at, None)])
        return any(a <= t and (b is None or t < b) for a, b in spans)

    def capture_request(self):
        self.captures += 1
        if self.fail_after is not None and self.captures >= self.fail_after[0]:
            raise self.fail_after[1]
        if not self.frozen():
            self._show()
        else:
            self.lores = self.history[self.captures % len(self.history)]
        time.sleep(0.01)
        return Request(self)

    def set_controls(self, c):
        pass

    def stop(self):
        pass

    def close(self):
        pass


def out_for(text, clipped=False, fitted=None):
    # `clipped` is what the real reader answers when a payout WAS found and was
    # sitting flush against the top of the crop — pipeline.py hands back
    # `parse('')` for it, so the parse is empty over a screen that was a card.
    # Reproduced here rather than described, because the branch that has to tell
    # that apart from a payout-free screen cannot be reached any other way.
    p = OP.parse('' if clipped else text)
    return {'parsed': dict(p), 'rate': OP.rate(p, {'target': 25}), 'locked': False,
            'text': text, 'clipped': clipped, 'dropped': 1 if clipped else 0,
            'recovered': 0, 'rescued': 0,
            'crop': [0, 0, 1, 1], 'card': None, 'fitted': fitted,
            'ms': {'warp': 0, 'prep': 0, 'ocr': 0, 'parse': 0, 'total': 1}}


BANDS = []
# ...and each map-label read asked for (scan_pi.MapLabels.submit).
LABELS = []


def run(texts_for_call, extra_argv=(), seconds=12.0, until=None, health_every=None,
        hang_from=None, stuck_after=None, handoff=None, alive_every=None,
        config_extra=None, appear_at=0.4, cam_out=None,
        clipped_for=None, dropoff_window=None, whole_text=None, fitted=None,
        fitted_for=None, hang_on_loop=True,
        fail_after=None, phone_hold=None, gps_hold=None, phone=None,
        planners=None,
        freeze_at=None, stall_say=None, empty=None, noise=True, offer_dim=None,
        ring=1, stall_again=None, offer=None, real_look=None, found_for=None,
        pi=None, dark_for=None):
    """Run main() with the reader answering texts_for_call(n, k) for frame k of
    read call n (1-based). `hang_from`: read calls from this one on never
    return — on the reader's thread only, with `hang_on_loop` False, so a read
    the loop's own thread makes is answered and counted rather than hanging
    the suite. `handoff`: a directory to point the button-press files at, so a
    request written here cannot be eaten by a scanner running on the same
    machine, nor this one eat theirs — and one of its own when none is given,
    because the loop writes there too: going quiet over a stall leaves a note
    (scan_pi.STALL_AGAIN), and a run that left one in the shared directory
    would hold back the real scanner's next restart on this machine for ten
    minutes. Measured before this: with a stuck read made to leave the note
    too, the stuck-read run below wrote /dev/shm/uberscan-stalled and passed
    all four of its checks. `fail_after`: (n, exception) for the
    camera — see FakeCam. `phone`: what gps.Phone hands back, for a --gps run.
    `planners`: a list every Trip Planner the loop answers a press with is
    appended to, as (stops, keywords), handed in so an `until` can watch it.
    `freeze_at`: the camera stalls this many seconds in — see FakeCam, and
    `ring` there — and `stall_say` stands in for scan_pi.STALL_SAY,
    `stall_again` for scan_pi.STALL_AGAIN. `empty`:
    what the mount shows with no card in it, TC.blank() unless a check needs
    it darker.
    `offer_dim`: the card at that share of its brightness — lit, and short of
    the full well that makes the gain look again at once.
    `offer`: the frame the mount shows once the card is up, instead of the
    UberX card. `real_look`: (box_text, found_text) — the REAL Scanner._look
    runs, card finder and all, on the frames the camera gives it, and only the
    OCR engine is stubbed: it answers `box_text` for every crop of a read until
    the card finder has been asked during that read, and `found_text` after.
    `finder` in the result counts the times the finder was asked.
    `found_for(n, k)`: with the stubbed reader, a crop (x, y, w, h) when frame
    k of read call n is to come back as a read off a card found above the box
    — cropFrom "found", that crop, rescued — and None for the box as drawn.
    `pi`: what main() builds in place of scan_pi.PiHealth() — the Pi's
    temperature and throttling from a fake source, since this machine has
    neither, for the heat guard.
    `dark_for(n, k)`: with the stubbed reader, true when frame k of read call
    n is to come back as the real reader answers a black crop it left unread
    (pipeline.DARK_SKIP_BELOW): empty, `skipped: 'dark'`. `skip_darks` in the
    result is each read handed over as (whole screen or not, skip_dark).
    Returns the journal rows, the announcements, the alive beats and what rode
    them, the log lines, how many reads were asked of the reader and how many
    it began, the exception main() raised, if any, and the handoff directory —
    and `stamps`, each read handed over as (when, whole screen or not), on the
    clock the loop stamped it with."""
    if not handoff:
        handoff = tempfile.mkdtemp()
    if offer is None:
        offer = TC.mount(TC.uberx_screen(), 1200)
    quad = PL.detect_screen_quad(offer)
    work = tempfile.mkdtemp()
    config = os.path.join(work, 'config.json')
    journal = os.path.join(work, 'journal.jsonl')
    cfg = {'quad': [[float(x), float(y)] for x, y in quad], 'cardHeight': 900,
           'capture': {'width': CAP[0], 'height': CAP[1]},
           'lensPosition': 10.0, 'exposureTime': 16667,
           'settings': {'target': 25, 'band': 15, 'costPerMile': 0.30}}
    cfg.update(config_extra or {})
    with open(config, 'w') as fh:
        json.dump(cfg, fh)
    if offer_dim is not None:
        offer = (offer.astype(np.float32) * offer_dim).astype(np.uint8)
    cam = FakeCam(offer, TC.blank() if empty is None else empty, appear_at=appear_at,
                  fail_after=fail_after, freeze_at=freeze_at, noise=noise, ring=ring)
    # Handed out so a check can ask what is really in the mount right now. The
    # stubbed reader answers with whatever text the check asked for whether or
    # not there is a card in front of it, so an announced offer is NOT evidence
    # that the camera can see one.
    if cam_out is not None:
        cam_out.append(cam)
    calls = [0]
    # Which reads were of the whole screen box (a ⌖ press) rather than the card
    # crop, in order. `whole_text`, when given, is what those reads see — the
    # map and planner round the card — so a check can tell which crop a
    # reading came from by what it says.
    wholes = []
    # ...and the crop and warp share each read was taken against.
    crops = []

    def look(self, frames, now=None, geom=None):
        calls[0] += 1
        whole = bool(getattr(geom, 'whole', False))
        wholes.append(whole)
        crops.append((list(geom.roi) if geom is not None and geom.roi is not None else None,
                      getattr(geom, 'fixed_card_share', None)))
        if hang_from is not None and calls[0] >= hang_from and (
                hang_on_loop or threading.current_thread() is not threading.main_thread()):
            while True:
                real_sleep(0.05)
        if whole and whole_text is not None:
            return [out_for(whole_text, fitted=fitted_for(calls[0]) if fitted_for else None)
                    for _ in range(len(frames))]
        # `fitted_for(n)`: a crop of its own for each read, so a check can
        # tell which read a kept picture came from.
        outs = [out_for(texts_for_call(calls[0], k),
                        fitted=fitted_for(calls[0]) if fitted_for else fitted,
                        clipped=bool(clipped_for and clipped_for(calls[0], k)))
                for k in range(len(frames))]
        for k, one in enumerate(outs):
            box = found_for(calls[0], k) if found_for else None
            if box:
                one.update(cropFrom='found', crop=list(box), rescued=1)
            if dark_for and dark_for(calls[0], k):
                one.update(out_for(''), skipped='dark', peak=3.0)
        return outs

    announced, verdicts, beats, logs, alive, dropoffs = [], [], [], [], [], []
    # ...and the keywords each offer line was told with: `where` and `whole`
    # travel that way, and a recorder that kept only the positional arguments
    # could not see whether the line and the row were handed one fix or two.
    offer_kw = []
    offer_at = []
    said_settings = []
    real = (SP.start_camera, SP.emit, SP.emit_offer, SP.emit_alive, SP.log,
            PL.Scanner.look_many, time.sleep, SP.HEALTH_EVERY, SP.READ_STUCK_S,
            SP.emit_reading, SP.emit_dropoff, SP.emit_settings, SP.Reader.submit)
    real_sleep = real[6]
    # Every read handed to the reader, begun or not: one asked of a reader
    # stuck on the read before it never starts, so `calls` cannot count it.
    submitted = [0]
    # ...whether each was a ⌖ read of the whole screen, and how many times the
    # panel was told a read had started.
    submitted_whole = []
    stamps = []
    skip_darks = []
    readings = [0]

    def submit(self, frames, now, geom):
        submitted[0] += 1
        skip_darks.append((bool(getattr(geom, 'whole', False)),
                           getattr(geom, 'skip_dark', None)))
        submitted_whole.append(bool(getattr(geom, 'whole', False)))
        stamps.append((now, bool(getattr(geom, 'whole', False))))
        return real[12](self, frames, now, geom)

    SP.Reader.submit = submit
    # What the loop tells the server it is pricing a mile at, as a copy: the
    # loop hands over its live dict, which is exactly the thing that changes.
    SP.emit_settings = lambda settings: said_settings.append(dict(settings or {}))
    SP.emit_reading = lambda *a, **k: readings.__setitem__(0, readings[0] + 1)
    # Captured rather than printed, like the offer line beside it. The empty
    # answer — a press that found no address — is only visible here.
    SP.emit_dropoff = lambda address, **k: dropoffs.append((address, k))
    # ...and the planner line beside it, which nothing else on the wire carries.
    was_planner = SP.emit_planner
    said_planners = planners if planners is not None else []
    SP.emit_planner = lambda stops, **k: said_planners.append((stops, k))
    # ...and the sighting beside them, built by the scanner's own sighting()
    # and kept rather than printed: the line's body as the server is sent it.
    was_sighting = SP.emit_sighting
    sightings = []
    # ...and the place popup's own line, as (popup, at).
    was_popup = SP.emit_popup
    popups = []
    SP.emit_popup = lambda popup, at=None: popups.append((dict(popup), at))
    SP.emit_sighting = lambda *a, **k: sightings.append(SP.sighting(*a, **k))
    SP.start_camera = lambda *a, **k: cam
    # Stamped, so a check can ask how soon after something a verdict came.
    SP.emit = lambda *a, **k: verdicts.append((a, k, time.time()))
    SP.emit_offer = lambda *a, **k: (announced.append(a), offer_kw.append(k),
                                     offer_at.append(time.monotonic()))
    # ...and each map band asked for, when, and of which MapBands, so a check
    # can hold it to after the offer line (scan_pi.MAP_BANDS_DIR).
    del BANDS[:]
    real_band_submit = SP.MapBands.submit

    def band_submit(self, offer_id, frame, geom, meta=None):
        BANDS.append((self, offer_id, time.monotonic()))
        return real_band_submit(self, offer_id, frame, geom, meta)

    SP.MapBands.submit = band_submit
    del LABELS[:]
    real_label_submit = SP.MapLabels.submit

    def label_submit(self, offer_id, frame, geom, store=None):
        LABELS.append((offer_id, time.monotonic()))
        return real_label_submit(self, offer_id, frame, geom, store=store)

    SP.MapLabels.submit = label_submit

    def beat(*a, **k):
        beats.append(time.time())
        alive.append(dict(k))

    SP.emit_alive = beat
    SP.log = lambda m: logs.append(m)
    was_handoff = os.environ.get(HO.ENV_DIR)
    os.environ[HO.ENV_DIR] = handoff
    finder = [0]
    real_reading = (PL.CF.find_card, PL.Scanner._look, PL.ocr_lines)
    if real_look is None:
        PL.Scanner.look_many = look
    else:
        # The real read, card finder and all; only the engine is a stub, and
        # it answers for whichever crop the read is on — see `real_look`.
        box_text, found_text = real_look
        mine = threading.local()

        def find_card(grey, box):
            finder[0] += 1
            mine.asked = True
            return real_reading[0](grey, box)

        def one_look(self, frame, now=None, geom=None):
            calls[0] += 1
            mine.asked = False
            return real_reading[1](self, frame, now, geom)

        def engine(image, config=PL.OCR_CONFIG):
            text = found_text if getattr(mine, 'asked', False) else box_text
            return text, [{'text': t, 'top': 100 + 60 * i, 'bottom': 140 + 60 * i,
                           'left': 10, 'right': 300}
                          for i, t in enumerate(text.split('\n'))]

        PL.CF.find_card, PL.Scanner._look, PL.ocr_lines = find_card, one_look, engine
    if health_every is not None:
        SP.HEALTH_EVERY = health_every
    if stuck_after is not None:
        SP.READ_STUCK_S = stuck_after
    was_alive_every = SP.ALIVE_EVERY
    if alive_every is not None:
        SP.ALIVE_EVERY = alive_every
    was_window = SP.DROPOFF_WINDOW
    if dropoff_window is not None:
        SP.DROPOFF_WINDOW = dropoff_window
    was_holds = (SP.PHONE_HOLD, SP.GPS_HOLD, SP.GPS.Phone, SP.STALL_SAY,
                 SP.STALL_AGAIN)
    if phone_hold is not None:
        SP.PHONE_HOLD = phone_hold
    if gps_hold is not None:
        SP.GPS_HOLD = gps_hold
    if stall_say is not None:
        SP.STALL_SAY = stall_say
    if stall_again is not None:
        SP.STALL_AGAIN = stall_again
    if phone is not None:
        SP.GPS.Phone = lambda address: phone
    was_pi = SP.PiHealth
    if pi is not None:
        SP.PiHealth = pi
    deadline = time.time() + seconds

    def rows():
        out = []
        if os.path.exists(journal):
            for line in open(journal):
                if line.strip():
                    out.append(json.loads(line))
        return out

    def bounded(s):
        if time.time() > deadline or (until is not None and until(rows(), announced, calls[0])):
            raise KeyboardInterrupt
        real_sleep(min(s, 0.01))

    time.sleep = bounded
    sys.argv = ['scan_pi', '--config', config, '--json', '--snapshot', '',
                '--journal', journal] + list(extra_argv)
    raised = None
    try:
        SP.main()
    except KeyboardInterrupt:
        pass
    except RuntimeError as e:
        # A camera that died, from fail_after. main() lets it out, which is
        # what a crash is; the supervisor would restart it.
        raised = e
    finally:
        (SP.start_camera, SP.emit, SP.emit_offer, SP.emit_alive, SP.log,
         PL.Scanner.look_many, time.sleep, SP.HEALTH_EVERY, SP.READ_STUCK_S,
         SP.emit_reading, SP.emit_dropoff, SP.emit_settings, SP.Reader.submit) = real
        PL.CF.find_card, PL.Scanner._look, PL.ocr_lines = real_reading
        SP.MapBands.submit = real_band_submit
        SP.MapLabels.submit = real_label_submit
        SP.emit_planner = was_planner
        SP.emit_sighting = was_sighting
        SP.emit_popup = was_popup
        SP.DROPOFF_WINDOW = was_window
        SP.ALIVE_EVERY = was_alive_every
        SP.PHONE_HOLD, SP.GPS_HOLD, SP.GPS.Phone, SP.STALL_SAY, SP.STALL_AGAIN = was_holds
        SP.PiHealth = was_pi
        if was_handoff is None:
            os.environ.pop(HO.ENV_DIR, None)
        else:
            os.environ[HO.ENV_DIR] = was_handoff
    return dict(rows=rows(), announced=announced, offer_kw=offer_kw, offer_at=offer_at,
                work=work, bands=list(BANDS), labels=list(LABELS),
                beats=beats, calls=calls[0],
                submitted=submitted[0], submitted_whole=submitted_whole, stamps=stamps,
                readings=readings[0], planners=said_planners, sightings=sightings,
                popups=popups,
                logs=logs, alive=alive, dropoffs=dropoffs, verdicts=verdicts,
                settings=said_settings, config=config, wholes=wholes, crops=crops,
                raised=raised, handoff=handoff, finder=finder[0], skip_darks=skip_darks)


def _stall_note_age(handoff):
    """handoff.age of the stall note in `handoff`, as the loop would read it."""
    was = os.environ.get(HO.ENV_DIR)
    os.environ[HO.ENV_DIR] = handoff
    try:
        return HO.age(HO.STALLED)
    finally:
        if was is None:
            os.environ.pop(HO.ENV_DIR, None)
        else:
            os.environ[HO.ENV_DIR] = was


FRAG = '$16.05 20 min (7.3 mi) trip'
# Both ends named, which is what a ride card really prints. It used to name
# only the destination, and the parser then reported that one address as
# BOTH ends of the journey — the fault find_dropoff was corrected for. A
# fixture that depends on a bug keeps the bug alive.
WHOLE = ('$16.05 3 min (1.1 mi) away Cobb Pkwy NW, Kennesaw '
         '20 min (7.3 mi) trip 123 Main St, Acworth, GA 30101')
# The decimal point lost: a payout that cannot be true, on a card that is
# already on disk. (A plausible near miss — $16.06 for $16.05 — is a card
# the journal itself would file as a different offer, and is still counted.)
LOST_DECIMAL = ('$1605 3 min (1.1 mi) away Cobb Pkwy NW, Kennesaw '
                '20 min (7.3 mi) trip 123 Main St, Acworth, GA 30101')

# --- a fuller reading of the same card is told again ------------------------
# The first read returns a fragment on both frames of the pair, so it locks;
# every read after returns the whole card with an address.
r = run(lambda n, k: FRAG if n <= 1 else WHOLE, seconds=25.0,
        until=lambda rows, ann, calls: any(x.get('whole') for x in rows if not x.get('kind'))
        and calls >= 4)
offers = [x for x in r['rows'] if not x.get('kind')]
ids = sorted(set(x['id'] for x in offers))
ok_('the fragment and the whole card landed under one id (%r)' % ids, len(ids) == 1 and offers)
ok_('...and the whole card is in the journal', any(x.get('whole') for x in offers))
told = [(a[0], a[1].get('minutes'), a[1].get('miles'), a[1].get('dropoff')) for a in r['announced']]
ok_('the driving screen was told the card once as a fragment (%r)' % (told[:1],),
    told and told[0][1] == 20 and told[0][3] is None)
ok_('...and told it again as the whole card, same id',
    len(told) >= 2 and told[-1][0] == told[0][0] and told[-1][1] == 23
    and 'Acworth' in (told[-1][3] or ''))
eq('...and not again for a reading that says nothing new',
   len(told), 2)
ok_('the startup line counts rows, not offers (%r)'
    % [l for l in r['logs'] if l.startswith('journal:')][:1],
    any(l.startswith('journal:') and 'journal row' in l and 'offer' not in l for l in r['logs']))

# --- the map band above the card, kept once per offer, after its line ---------
#
# scan_pi.MAP_BANDS_DIR: collection only. Every offer card, Uber's and
# DoorDash's, has its map band written to mapbands/<offer id>.jpg beside the
# journal, on a thread of its own, once — however many reads the card gets.
def _band_saved(rows, ann, calls):
    return calls >= 4 and any(b[0].saved for b in BANDS)


for _app, _text in (('uber', WHOLE),
                    ('doordash', '$12.35 incl. tips\n2 stops (11.2 mi) - 38 min\n'
                                 'Lark Owl Grill\nCustomer dropoff')):
    # The card in the mount from the first frame: the stubbed reader answers
    # its text over an empty mount too, and a band of an empty mount is (rightly)
    # too dark to keep.
    r = run(lambda n, k, t=_text: t, seconds=20.0, until=_band_saved, appear_at=0.0)
    _ids = sorted(set(a[0] for a in r['announced']))
    _dir = os.path.join(r['work'], 'mapbands')
    _files = sorted(os.listdir(_dir)) if os.path.isdir(_dir) else []
    eq('%s: one map band and its sidecar, named for the offer (%r)' % (_app, _ids),
       _files, ['%s.jpg' % i for i in _ids[:1]] + ['%s.json' % i for i in _ids[:1]])
    _side = json.load(open(os.path.join(_dir, _files[1]))) if len(_files) == 2 else {}
    eq('...its sidecar naming the offer and the app', (_side.get('offerId'), _side.get('app')),
       (_ids[0] if _ids else None, _app))
    _mine = [b for b in r['bands'] if b[1] in _ids]
    ok_('...asked for only after the offer line went out (%d asks)' % len(_mine),
        _mine and r['offer_at'] and min(b[2] for b in _mine) >= r['offer_at'][0])
    eq('...and kept once, however many reads (%d)' % r['calls'],
       [o for o in _mine[0][0].outcomes if o[1] == 'saved'] if _mine else None,
       [(_ids[0], 'saved')] if _ids else None)

# ...and DoorDash's map label is READ for a card read well. The submit asked
# `not whole`, and `whole` by there is OP.is_whole: a DoorDash card with its
# "2 stops (11.2 mi)" on it is whole, so the label was asked only of half-read
# cards (the owner's shifts of 26-29 Oct: 31 DoorDash offers, no label).
_dd_whole = '$12.35 incl. tips\n2 stops (11.2 mi) - 38 min\nLark Owl Grill\nCustomer dropoff'
r = run(lambda n, k: _dd_whole, seconds=20.0, appear_at=0.0,
        until=lambda rows, ann, calls: calls >= 4 and bool(LABELS))
_ids = sorted(set(a[0] for a in r['announced']))
ok_('a DoorDash card read whole is asked its map label (%d asks for %r)' % (len(r['labels']), _ids),
    _ids and any(l[0] in _ids for l in r['labels']))
ok_('...after its offer line went out',
    r['labels'] and r['offer_at'] and min(l[1] for l in r['labels']) >= r['offer_at'][0])
r = run(lambda n, k: WHOLE, seconds=6.0, appear_at=0.0, until=lambda rows, ann, calls: calls >= 4)
eq('...and an Uber card is not', r['labels'], [])

r = run(lambda n, k: WHOLE, seconds=4.0, config_extra={'mapBands': False},
        until=lambda rows, ann, calls: calls >= 4)
eq('"mapBands": false keeps none', (os.path.isdir(os.path.join(r['work'], 'mapbands')),
                                    r['bands']), (False, []))
ok_('...and says so at startup', any('map bands off' in l for l in r['logs']))

# --- ...and so is a reading of the same card whose verdict moved -------------
#
# The offer carries its card's verdict, because ⌖ Dropoff asks on it and the
# reading beside it can be a different card. It was only told again when
# minutes, miles or dropoff moved, and an item count read late moves none of
# the three: it adds the shopping allowance to the BILLED minutes. At 90s an
# item and 30c a mile that takes this card from go to PASS, and the headline
# said PASS while the offer on record still said go.
WHOLE_ITEMS = ('$16.05 3 min (1.1 mi) away Cobb Pkwy NW, Kennesaw 20 items '
               '20 min (7.3 mi) trip 123 Main St, Acworth, GA 30101')
r = run(lambda n, k: WHOLE if n <= 1 else WHOLE_ITEMS, seconds=25.0,
        config_extra={'settings': {'target': 25, 'band': 15, 'costPerMile': 0.30,
                                   'secondsPerItem': 90}},
        until=lambda rows, ann, calls: any(x.get('items') for x in rows if not x.get('kind'))
        and calls >= 4)
told = [(a[0], a[1].get('minutes'), a[1].get('miles'), a[1].get('dropoff'),
         a[2].get('state')) for a in r['announced']]
ok_('the card was told first with the verdict it got first (%r)' % (told[:1],),
    told and told[0][4] == 'go')
ok_('...and told again, same id and same journey, when its verdict moved (%r)'
    % (told[-1:],),
    len(told) >= 2 and told[-1][0] == told[0][0]
    and told[-1][1:4] == told[0][1:4] and told[-1][4] == 'no')

# --- ...and so is one whose store's door read late ---------------------------
#
# DoorDash's stops card prints the store's address under its name (OP's
# `pickupLine`), and Map view searches it for the pickup's pin. The first
# frames read the line with the town cut by the card's edge, which is no door;
# the later ones read it whole. Minutes, miles, dropoff and verdict are the
# same throughout, so without the door in the told tuple the offer on record
# never gained it and the map went on searching the store's name. Invented.
_DD = ('$7.70 incl. tips\n2 stops (2.4 mi) - 18 min\n& Lark Owl Grill\n'
       '2530 Kestrel Plains Road, %s\n& Customer dropoff\nAccept')
r = run(lambda n, k: _DD % ('Sm...' if n <= 1 else 'Marietta, 30066 GA'), seconds=25.0,
        until=lambda rows, ann, calls: any((a[1].get('pickupLine') for a in ann))
        and calls >= 4)
told = [(a[0], a[1].get('pickup'), a[1].get('pickupLine'), a[1].get('dropoff'))
        for a in r['announced']]
ok_('a stops card was told first with no door (%r)' % (told[:1],),
    told and told[0][1] == 'Lark Owl Grill' and told[0][2] is None)
ok_('...and told again, same id and same store, when its door read (%r)' % (told[-1:],),
    len(told) >= 2 and told[-1][0] == told[0][0] and told[-1][1] == 'Lark Owl Grill'
    and told[-1][2] == '2530 Kestrel Plains Road, Marietta, GA 30066'
    and told[-1][3] is None)

# --- one misread frame is not a card the rig failed to record ----------------
r = run(lambda n, k: LOST_DECIMAL if n == 3 else WHOLE, extra_argv=['--no-parallel'],
        seconds=16.0, health_every=3.0,
        until=lambda rows, ann, calls: sum(1 for x in rows if x.get('kind') == 'seen') >= 2
        and calls >= 6)
seen = [x for x in r['rows'] if x.get('kind') == 'seen']
offers = [x for x in r['rows'] if not x.get('kind')]
ok_('the health tally was written', bool(seen))
eq('one card on disk', len(set(x['id'] for x in offers)), 1)
eq('...counted as one card seen (%r)' % [(x['saw'], x['kept']) for x in seen],
   sum(x['saw'] for x in seen), 1)
eq('...and as one recorded', sum(x['kept'] for x in seen), 1)
# ...and each tally carries how the reading went in its window, which until now
# was a health line on the Pi and nothing more. Asked of the real row the real
# loop wrote, because the fault this guards is note_tally dropping what the
# tally carried — `reads` and `failed` were in it all along and never reached
# the file.
_first = seen[0] if seen else {}
eq('a seen row carries the window\'s reads and how they went (%r)'
   % dict((k, _first.get(k)) for k in ('reads', 'complete', 'medianMs', 'corners')),
   [k for k in ('reads', 'failed', 'complete', 'noPay', 'clipped', 'medianMs',
                'tooDim', 'tooBright', 'corners', 'relocks')
    if k not in _first], [])
ok_('...with the reads counted, not a placeholder',
    isinstance(_first.get('reads'), int) and _first.get('reads') >= 1)
# ...and the stall watch's own evidence: frames since start that were the same
# picture as one of the eight before. Nought here, a working camera with a
# sensor's noise, over a still card read again and again — and on the row,
# because the premise it measures is the suites' model and only a real shift
# can test it.
eq('...and how many frames since start were a picture handed over again, '
   'which on a working camera is none', _first.get('repeats', 'not on the row'), 0)
eq('...and the corners in the health line\'s own word', _first.get('corners') in
   ('held', 'lost', 'stuck'), True)
# This machine has no thermal zone and no vcgencmd, so both are null — and the
# row has to say why rather than leave a null that reads as never asked.
eq('...and the Pi\'s temperature and throttling, each with its reason when it '
   'cannot be read', [k for k in ('cpuC', 'cpuCWhy', 'throttled', 'throttledWhy')
                      if k not in _first], [])
ok_('...a null always beside a reason (%r)' % ((_first.get('cpuC'), _first.get('cpuCWhy')),),
    (_first.get('cpuC') is not None) != bool(_first.get('cpuCWhy'))
    and (_first.get('throttled') is not None) != bool(_first.get('throttledWhy')))

# --- a glare frame is not a card either --------------------------------------
#
# The case above is a MISREAD payout - "$1605" for "$16.05" - which `same_card`
# recognises by its impossibility. This is the other shape: a read that finds no
# payout at all, which is what glare, a hand across the phone, or a notification
# banner actually produces. It carries no episode, and the seen-gate treated
# that absence as the start of a new card.
#
# Timed to land BEFORE the card is written, which is the whole of the exposure.
# Once a reading has landed, `same_card` matches the payout and hides this; a
# card is read, read again to agree, and only then written, and on a rig whose
# reads take 1.8s and whose verify beat is 2.5s a glare frame inside that
# window is an ordinary event rather than a contrived one.
GLARE = 'Uber  ...  '

r = run(lambda n, k: GLARE if n in (2, 4, 6) else WHOLE, extra_argv=['--no-parallel'],
        seconds=24.0, health_every=3.0,
        until=lambda rows, ann, calls: sum(1 for x in rows if x.get('kind') == 'seen') >= 2
        and calls >= 10)
seen = [x for x in r['rows'] if x.get('kind') == 'seen']
offers = [x for x in r['rows'] if not x.get('kind')]
ok_('the health tally was written for the glare run', bool(seen))
eq('one card on disk through three glare frames',
   len(set(x['id'] for x in offers)), 1)
# Was 4. The offers page turns saw - kept into "3 times the scanner picked a
# payout off the screen and never managed to record it - 75% of the 4 it saw.
# So at least that many offers are missing from everything above" - about one
# card that is in the file.
eq('...counted as one card seen (%r)' % [(x['saw'], x['kept']) for x in seen],
   sum(x['saw'] for x in seen), 1)
eq('...and as one recorded', sum(x['kept'] for x in seen), 1)
eq('...so the page is told nothing went missing',
   sum(x['saw'] for x in seen) - sum(x['kept'] for x in seen), 0)

# The control that keeps the gate honest: a genuinely different card still
# opens a new count. A fix that simply stopped re-arming would pass everything
# above and silently merge every card in a shift into one.
SECOND = ('$9.40 4 min (1.4 mi) away Barrett Pkwy, Kennesaw '
          '15 min (5.2 mi) trip 900 Oak Ln, Marietta, GA 30060')
r2 = run(lambda n, k: WHOLE if n < 4 else SECOND, extra_argv=['--no-parallel'],
         seconds=24.0, health_every=3.0,
         until=lambda rows, ann, calls: sum(1 for x in rows if x.get('kind') == 'seen') >= 2
         and calls >= 10)
seen2 = [x for x in r2['rows'] if x.get('kind') == 'seen']
offers2 = [x for x in r2['rows'] if not x.get('kind')]
eq('two different cards are two cards on disk',
   len(set(x['id'] for x in offers2)), 2)
eq('...and two cards seen', sum(x['saw'] for x in seen2), 2)
eq('...and two recorded', sum(x['kept'] for x in seen2), 2)

# --- a read that never returns stops the heartbeat ---------------------------
# Twelve seconds: a heartbeat every four would leave the last one under four
# seconds old; a rig that went quiet at 1.5s leaves it about twelve.
r = run(lambda n, k: WHOLE, seconds=12.0, hang_from=1, stuck_after=1.5)
beats = r['beats']
ok_('the loop beat while it was waiting (%d beats)' % len(beats), len(beats) >= 1)
last_gap = time.time() - beats[-1] if beats else None
ok_('...and stopped beating once the read was stuck (last beat %.1fs ago)'
    % (last_gap or 0), last_gap is not None and last_gap > 6.0)
ok_('...saying why, once',
    sum(1 for l in r['logs'] if 'stuck' in l) == 1)
# ...and in the journal, where it is the only account the run gets: the SIGKILL
# that answers the silence leaves no stop row, so without this a stuck reader
# reads afterwards exactly as a crash does.
_stuck_rs = [x.get('why') for x in r['rows']
             if x.get('kind') == 'up' and x.get('state') == 'restart']
ok_('...and the journal says the rig asked to be restarted, and why (%r)' % _stuck_rs,
    len(_stuck_rs) == 1 and 'stuck' in (_stuck_rs[0] or ''))
# ...and leaves no note that it went quiet over a stalled camera, because it
# did not. The note holds back the next stall's restart for STALL_AGAIN, so a
# stuck reader's restart that left one would leave a camera stalling in the
# ten minutes after it on the glass, not restarted.
eq('...and leaves no note holding back a stalled camera\'s restart',
   _stall_note_age(r['handoff']), None)

# --- a wall clock stepped an hour ---------------------------------------------
#
# A Pi has no real-time clock and NTP corrects it by STEPPING it, back as often
# as forward (AUDITS.md, Settled: the clock — and a stamp is never corrected
# here; only the intervals moved). Every interval the loop times was taken off
# the wall clock, so a step moved all of them at once. Measured through this
# harness before the fix, the scanner's own modules on a clock stepped mid-run
# and this suite's clock left alone:
#
#   back an hour      no heartbeat for the rest of the run (0 in 15.8 s, 4
#                     without the step); a second ⌖ press got 1 whole-screen
#                     read in its 3 s window, 7 without the step
#   forward an hour   a read 0.6 s in flight at the step was "in flight for
#                     3600s — the reader is stuck", and the journal got a
#                     restart row for a reader that was working
#
# The step is taken from INSIDE a read, so that read is in flight across it,
# and a second ⌖ press comes after it, once the first press's window has run.
class _SteppedWall(type(sys)):
    """The `time` module, with the wall clock moved by `offset`; monotonic not."""

    offset = 0.0

    def __getattr__(self, name):
        return getattr(time, name)

    def time(self):
        return _REAL_TIME() + _SteppedWall.offset


_REAL_TIME, _REAL_SLEEP = time.time, time.sleep
_WALL = _SteppedWall('time')
import accumulate as _AC                                     # noqa: E402
import journal as _JR                                        # noqa: E402
import track as _TR                                          # noqa: E402
_CLOCKED = (SP, HO, _TR, _AC, _JR)


def _stepped_run(step):
    """A card up, ⌖ pressed, the clock stepped by `step` mid-read, ⌖ again."""
    hand = tempfile.mkdtemp()
    seen = {'t0': None, 'p1': False, 'stepped_at': None, 'p2': None}

    def press():
        os.environ[HO.ENV_DIR] = hand
        where = HO.path(HO.DROPOFF)
        open(where, 'w').close()
        stamp = _WALL.time()
        os.utime(where, (stamp, stamp))
        return stamp

    def texts(n, k):
        # The first card read after the first window has run is the one the
        # clock steps inside. Really asleep, not the harness's bounded sleep,
        # so the loop sees it in flight.
        if k == 0 and seen['stepped_at'] is None and seen['t0'] is not None \
                and _REAL_TIME() - seen['t0'] > 5.0:
            _REAL_SLEEP(0.6)
            _SteppedWall.offset = step
            seen['stepped_at'] = _REAL_TIME()
            _REAL_SLEEP(1.4)
        return WHOLE

    def hook(rows, ann, calls):
        now = _REAL_TIME()
        if seen['t0'] is None:
            seen['t0'] = now
        if now - seen['t0'] > 1.5 and not seen['p1']:
            press()
            seen['p1'] = True
        if seen['stepped_at'] is not None and seen['p2'] is None \
                and now - seen['stepped_at'] > 1.6:
            seen['p2'] = press()
        return seen['p2'] is not None and _WALL.time() - seen['p2'] > 3.5

    _SteppedWall.offset = 0.0
    was = [m.time for m in _CLOCKED]
    for m in _CLOCKED:
        m.time = _WALL
    try:
        r = run(texts, seconds=30.0, until=hook, handoff=hand, whole_text=NAV_TEXT,
                dropoff_window=3.0)
    finally:
        for m, t in zip(_CLOCKED, was):
            m.time = t
        _SteppedWall.offset = 0.0
    r['seen'] = seen
    return r


NAV_TEXT = 'Deliver to Pat Q.\n6 min © 1.7 mi\nTurn right onto Ab St'
for _step, _way in ((-3600.0, 'back'), (3600.0, 'forward')):
    _sr = _stepped_run(_step)
    _s = _sr['seen']
    ok_('the premise, %s: the clock stepped inside a read, and ⌖ was pressed after it'
        % _way, _s['stepped_at'] is not None and _s['p2'] is not None)
    _after = [b for b in _sr['beats'] if _s['stepped_at'] and b > _s['stepped_at']]
    ok_('a wall clock stepped an hour %s: beats continue (%d after the step)'
        % (_way, len(_after)), len(_after) >= 1)
    _second = [st for st in _sr['stamps'] if st[1] and _s['p2'] is not None
               and -0.05 <= st[0] - _s['p2'] < 3.0]
    ok_('a wall clock stepped an hour %s: ⌖ gets its forced reads (%d whole-screen '
        'reads in the second press\'s 3 s window)' % (_way, len(_second)),
        len(_second) >= 4)
    _rs = [x.get('why') for x in _sr['rows']
           if x.get('kind') == 'up' and x.get('state') == 'restart']
    eq('a wall clock stepped an hour %s: no restart row is written' % _way, _rs, [])

# --- ▣ Set box always takes, and nothing throws a drawn box away -------------
# ⟳ Re-find was taken off the panel at the owner's request (AUDITS.md,
# Settled). Pressed with a box drawn it threw the boxes away and went back to
# finding the screen by itself — on their mount, the map — and they reported it
# "tends to get stuck and not let me set it". The scanner no longer reads the
# request at all, so a `.recalibrate` an older page left in the handoff
# directory is inert: the drawn box stays, and a new one drawn on the panel
# takes over it.
_ho_rf = tempfile.mkdtemp()
_stale_rf = os.path.join(_ho_rf, 'uberscan-recalibrate')
open(_stale_rf, 'w').close()


def _draw_on_third_read(n, k):
    if n == 3 and k == 0:
        with open(os.path.join(_ho_rf, 'uberscan-cropbox.json'), 'w') as fh:
            json.dump({'quad': [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]],
                       'card': [0.0, 0.3, 1.0, 0.45]}, fh)
    return WHOLE


# The phone is in the mount from the first frame, so a scanner that still read
# the request would find a screen to throw the box away for.
r = run(_draw_on_third_read, seconds=6.0, handoff=_ho_rf, appear_at=0.0,
        config_extra={'manualBox': True, 'cropBox': [0.0, 0.0, 1.0, 1.0]},
        until=lambda rows, ann, calls: calls >= 6)
eq('a drawn box is read as drawn while a stale re-find request lies there',
   r['crops'][0], ([0.0, 0.0, 1.0, 1.0], 1.0))
ok_('...and nothing goes back to finding the screen by itself',
    not any('automatically' in l or 'outline reset' in l for l in r['logs']))
ok_('▣ Set box takes over it, mid-shift (%r)' % r['crops'][-1:],
    any(c == ([0.0, 0.3, 1.0, 0.45], 0.45) for c in r['crops']))
ok_('...and the box is still a person\'s choice in the saved config',
    json.load(open(r['config'])).get('manualBox') is True)

# --- a card box inside the drawn box -------------------------------------------
#
# Offers are read in the card box and the warp is sized to IT, not to the
# screen box round it: sized to the screen, the card would come out at half
# the height the reader wants.
_card = [0.0, 0.4, 1.0, 0.5]
r10 = run(lambda n, k: WHOLE, seconds=3.0,
          config_extra={'manualBox': True, 'cropBox': _card})
eq('a card box saved from before is the crop the rig reads by',
   r10['crops'][0], (_card, 0.5))

# ...and one drawn on the panel mid-shift, arriving through the handoff file.
_ho5 = tempfile.mkdtemp()


def _draw_on_first_read(n, k):
    if n == 1 and k == 0:
        with open(os.path.join(_ho5, 'uberscan-cropbox.json'), 'w') as fh:
            json.dump({'quad': [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]],
                       'card': [0.0, 0.25, 1.0, 0.4]}, fh)
    return WHOLE


r11 = run(_draw_on_first_read, seconds=4.0, handoff=_ho5)
ok_('a card box drawn mid-shift is taken (%r)' % r11['crops'][-1:],
    any(c == ([0.0, 0.25, 1.0, 0.4], 0.4) for c in r11['crops']))
ok_('...and said in the log',
    any('card box' in l for l in r11['logs']))

# --- the reads the rig was unsure of keep their picture ----------------------
#
# 338 of the week's 1,166 offers landed a row the reader doubted, 328 of them
# on recover_decimal's divide-by-ten. Only the picture can say whether the
# guess was right, and those were never kept: --keep-scans is off by default.
DECIMAL_GUESS = WHOLE.replace('(7.3 mi) trip', '(73 mi) trip')
# The reader's crop, which the stub otherwise leaves out: a grey card-sized
# picture is all save_scan needs to have something to write.
_crop = TC.blank()[:400, :300].copy()
# Until a doubtful row has landed, not for a fixed four seconds: under the full
# runner's load four seconds was not always enough for one row, and every
# check below then failed for want of a card rather than for the code.
r12 = run(lambda n, k: DECIMAL_GUESS, seconds=30.0, fitted=_crop,
          until=lambda rows, ann, calls: any(not r.get('kind') and SP.doubted(r)
                                             for r in rows))
_dd = os.path.join(os.path.dirname(r12['config']), 'scans', SP.DOUBT_DIR)
_kept = sorted(os.listdir(_dd)) if os.path.isdir(_dd) else []
_doubted = sorted(set(row['id'] for row in r12['rows']
                      if not row.get('kind') and SP.doubted(row)))
ok_('the card really was read with its miles corrected', _doubted)
ok_('a card the reader corrected the miles on keeps its picture, with no flag asked (%r)'
    % _kept, len(_kept) >= 1)
eq('...one picture per doubtful offer, however many times it was read',
   len(_kept), len(_doubted))
r13 = run(lambda n, k: WHOLE, seconds=30.0, fitted=_crop,
          until=lambda rows, ann, calls: len([r for r in rows if not r.get('kind')]) >= 2)
ok_('the clean card really did land rows', len([r for r in r13['rows'] if not r.get('kind')]) >= 2)
_dd13 = os.path.join(os.path.dirname(r13['config']), 'scans', SP.DOUBT_DIR)
eq('a card read cleanly keeps no picture',
   sorted(os.listdir(_dd13)) if os.path.isdir(_dd13) else [], [])

# ...and the cap is said once, not on every picture after it.
_pd = tempfile.mkdtemp()
for _i in range(3):
    open(os.path.join(_pd, '%013d-x.jpg' % _i), 'w').close()
_said, _was_log = [], SP.log
SP.log = _said.append
try:
    SP.prune_scans(_pd, keep=2)
    open(os.path.join(_pd, '%013d-x.jpg' % 9), 'w').close()
    SP.prune_scans(_pd, keep=2)
finally:
    SP.log = _was_log
eq('pictures pruned at the cap leave the newest', sorted(os.listdir(_pd)),
   ['%013d-x.jpg' % 2, '%013d-x.jpg' % 9])
eq('...and say so once, the first time', len([l for l in _said if 'cap' in l]), 1)

# --- a cost per mile typed on a screen prices the next reading ---------------
#
# POST /api/settings leaves the request in the handoff directory; the loop takes
# it without a restart (a restart is an aim-and-calibrate cycle mid-shift) and
# the very next reading is costed at it. Dropped here once the loop has read a
# couple of times at the config's own 0.30, so the check sees both sides —
# and once the card has sat still long enough for the verify beat to back off,
# so what happens next is the loop's own doing rather than a read that was
# coming anyway. A still card is re-read on that beat, 2.5s backing off to 6s,
# and the panel's "after $0.30/mi costs" would stand under it until then.
#
# The request also names `keepPlaces`, `pad` and `secondsPerItem`, which the
# route refuses — written here by hand, the way a server a `git pull` behind or
# a person at a terminal could. They share the block with the cost, and they
# decide whether addresses reach the append-only journal and how many minutes
# every stored rate is divided by. Only the cost may come through.
_sho = tempfile.mkdtemp()
_sreq = os.path.join(_sho, 'uberscan-settings.json')
_typed_at = [None, None]
_last_read = [0, time.time(), 0.0]     # calls, when, the gap before it


def type_a_cost(rows, ann, calls):
    """Drop the request once the verify beat has backed off — the last gap
    between reads was 3.5s or more, so the next is 6s — and two seconds into
    that wait. Stop two reads after."""
    now = time.time()
    if calls != _last_read[0]:
        _last_read[:] = [calls, now, now - _last_read[1]]
    if (_typed_at[0] is None and calls >= 2 and _last_read[2] >= 3.5
            and now - _last_read[1] > 2.0):
        _typed_at[:] = [calls, time.time()]
        with open(_sreq + '.w', 'w') as fh:
            json.dump({'costPerMile': 0.45, 'keepPlaces': False, 'pad': 9,
                       'secondsPerItem': 60}, fh)
        os.replace(_sreq + '.w', _sreq)
    return _typed_at[0] is not None and calls >= _typed_at[0] + 2


r = run(lambda n, k: WHOLE, extra_argv=['--no-parallel'], seconds=35.0,
        handoff=_sho, until=type_a_cost)
_costs = [(v[0][0].get('costPerMile'), round(v[0][0].get('perHour') or 0, 2))
          for v in r['verdicts'] if v[0] and v[0][0].get('ready')]
_first_new = next((v[2] for v in r['verdicts'] if v[0] and v[0][0].get('ready')
                   and v[0][0].get('costPerMile') == 0.45), None)
_took = (_first_new - _typed_at[1]) if (_first_new and _typed_at[1]) else None
ok_('the card still on the phone is re-read at the new cost at once, not on '
    'the next verify beat (%s)' % ('%.2fs' % _took if _took is not None else 'never'),
    _took is not None and _took < 1.5)
# $16.05 over 23 minutes and 8.4 miles: at $0.30 a mile $35.30/hr, at $0.45
# $32.01/hr. With the refused pad of 9 minutes let through it is $23.01/hr and
# a CLOSE CALL instead of an ACCEPT.
eq('the readings before the request are costed at the config\'s 0.30',
   _costs[:1], [(0.3, 35.3)])
eq('...and the readings after it at the 0.45 typed, in the same process',
   _costs[-1:], [(0.45, 32.01)])
ok_('...with no reading in between at any third figure (%r)' % sorted(set(_costs)),
    set(_costs) <= {(0.3, 35.3), (0.45, 32.01)})
eq('the loop told the server what it priced with, then what it prices with now',
   [x.get('costPerMile') for x in r['settings']], [0.3, 0.45])
_saved = json.load(open(r['config'])).get('settings', {})
eq('the cost is saved, so the next start begins from it',
   _saved.get('costPerMile'), 0.45)
eq('...and nothing else the request named reached the settings block',
   sorted(k for k in ('keepPlaces', 'pad', 'secondsPerItem') if k in _saved), [])
ok_('...and the request was taken, not left for the next start',
    not os.path.exists(_sreq))
ok_('...and the log says what it changed from and to (%r)'
    % [l for l in r['logs'] if 'cost per mile' in l][:1],
    any('$0.45' in l and '$0.30' in l for l in r['logs']))

# --- a journal that will not take writes ------------------------------------
#
# The loop goes on reading, pricing and announcing while nothing is stored, and
# until this existed the only sign was a line in a log on a headless box. The
# sentence and the wire are checked in test_scan_pi.py; what is checked HERE is
# the one link nothing else can reach — that the real main() asks the journal
# and puts the answer on the beat. That link is not theoretical: with the other
# two in place and this one missing, every test still passed and the panel was
# still silent.
_nowhere = os.path.join(tempfile.mkdtemp(), 'gone', 'offers.jsonl')
_dead = run(lambda n, k: WHOLE, extra_argv=('--journal', _nowhere),
            alive_every=0.05, seconds=10.0,
            until=lambda rows, ann, calls: ann and calls >= 4)
_said = [b.get('not_saving') for b in _dead['alive']]
ok_('a journal that will not take writes reaches the beat',
    any(s and 'NOT being saved' in s for s in _said))
ok_('...naming the reason, because on a Pi the errno is the diagnosis',
    any(s and 'No such file or directory' in s for s in _said))
# The whole reason it needs its own channel: nothing else on the wire looks
# wrong. The rig reads the card and announces the offer exactly as it would on
# a healthy card, so a driver watching the panel sees a normal shift.
ok_('...while the rig goes on reading and announcing as if nothing were wrong',
    _dead['announced'])

# An OFFER, not any row: the rig's start row lands before anything is read, so
# "the journal has a row in it" stopped being evidence that an offer was stored.
_fine = run(lambda n, k: WHOLE, alive_every=0.05, seconds=10.0,
            until=lambda rows, ann, calls: any(not x.get('kind') for x in rows)
            and calls >= 4)
eq('a journal that is taking rows says nothing about itself',
   any(b.get('not_saving') for b in _fine['alive']), False)
ok_('...having actually stored something, so that is not a silence of its own',
    [x for x in _fine['rows'] if not x.get('kind')])

# --- the rig says when it starts and when it stops ---------------------------
#
# It never did. A run that crashed, one the watchdog killed and one the driver
# stopped all left the same thing in the journal — nothing — and the counters
# that knew the difference were server.js's, which start again at nought on
# every restart. The rows are written by the real main(), so these drive it;
# what the rows say is UpDown's, and test_scan_pi.py checks that.
def _journal_of(path):
    return ([json.loads(l) for l in open(path) if l.strip()]
            if os.path.exists(path) else [])


def _ups(rows):
    return [(x.get('about'), x.get('state')) for x in rows if x.get('kind') == 'up']


_upj = os.path.join(tempfile.mkdtemp(), 'offers.jsonl')
_clean = run(lambda n, k: WHOLE, extra_argv=('--journal', _upj), seconds=8.0,
             alive_every=0.05, until=lambda rows, ann, calls: calls >= 2)
_crows = _journal_of(_upj)
eq('a run that is stopped writes a start and a stop, and nothing else of its '
   'own (%r)' % _ups(_crows), _ups(_crows), [('rig', 'start'), ('rig', 'stop')])
_cstart = [x for x in _crows if x.get('kind') == 'up'][:1] or [{}]
eq('...the start saying --gps was not given', _cstart[0].get('gps'), False)
ok_('...and how long the machine had been up (%r)' % (_cstart[0].get('uptime'),),
    isinstance(_cstart[0].get('uptime'), int) and _cstart[0]['uptime'] > 0)
ok_('...ahead of every offer the run wrote',
    _crows and _crows[0].get('kind') == 'up')
# The beat, from the same run: the loop has to hand the GPS and the Pi to it.
# Without --gps the word is 'off' — said on the beat, where the page decides to
# say nothing about it, rather than left out.
_cb = [b for b in _clean['alive'] if 'gps' in b]
ok_('the loop puts the GPS on the beat (%d of %d beats)' % (len(_cb), len(_clean['alive'])),
    _cb and len(_cb) == len(_clean['alive']))
eq('...as off, for a rig not asked for a position',
   _cb[-1].get('gps') if _cb else None,
   {'state': 'off', 'ageSeconds': None, 'fix': None})
eq('...and the Pi, with all four of its fields',
   sorted((_clean['alive'][-1].get('pi') or {}).keys()) if _clean['alive'] else [],
   ['cpuC', 'cpuCWhy', 'throttled', 'throttledWhy'])
# ...and the heat guard on every beat, off on a machine that has neither a
# temperature nor a throttle word to give it.
eq('...and the heat guard, on every beat and off here',
   sorted(set(repr(b.get('heat_guard', 'absent')) for b in _clean['alive'])), ['False'])

# A camera that dies mid-run, then the supervisor's restart onto the same
# journal. The first run leaves a start and no stop; that unpaired start IS the
# record of the crash, because the process that crashed cannot write one.
_crashj = os.path.join(tempfile.mkdtemp(), 'offers.jsonl')
_crash = run(lambda n, k: WHOLE, extra_argv=('--journal', _crashj), seconds=8.0,
             fail_after=(40, RuntimeError('the camera stopped answering')))
ok_('the camera really did die mid-run (%r)' % (_crash['raised'],),
    isinstance(_crash['raised'], RuntimeError))
eq('a run that crashed leaves its start and no stop',
   _ups(_journal_of(_crashj)), [('rig', 'start')])
run(lambda n, k: WHOLE, extra_argv=('--journal', _crashj), seconds=8.0,
    until=lambda rows, ann, calls: calls >= 2)
eq('...so after the restart the journal reads start, start, stop: the run '
   'with no stop of its own is the one that crashed',
   _ups(_journal_of(_crashj)), [('rig', 'start'), ('rig', 'start'), ('rig', 'stop')])

# ...and the supervisor's SIGTERM, which _stop_on_sigterm turns into SystemExit,
# is a stop and not a crash. Raised from the camera, where a real signal lands
# most of the time: the loop spends its life waiting on capture_request().
_termj = os.path.join(tempfile.mkdtemp(), 'offers.jsonl')
_term = run(lambda n, k: WHOLE, extra_argv=('--journal', _termj), seconds=8.0,
            fail_after=(40, SystemExit(0)))
eq('a SIGTERM is a clean stop, written as one',
   (_term['raised'], _ups(_journal_of(_termj))), (None, [('rig', 'start'), ('rig', 'stop')]))

# --- the phone out of sight --------------------------------------------------
#
# The mount is empty for the first four seconds, and the tracker calls the
# screen lost. With the hold cut to 0.6s that is a 'gone' row, and the card
# arriving is a 'back' row.
_ph = run(lambda n, k: WHOLE, seconds=20.0, appear_at=4.0, phone_hold=0.6,
          until=lambda rows, ann, calls: ('phone', 'back') in _ups(rows))
_pups = _ups(_ph['rows'])
ok_('a phone the camera cannot find is written as gone, then back when it '
    'is (%r)' % _pups,
    ('phone', 'gone') in _pups and ('phone', 'back') in _pups
    and _pups.index(('phone', 'gone')) < _pups.index(('phone', 'back')))
# ...and with the real hold, the same four seconds are nothing. Without this
# the check above passes on a loop that writes a row on every lost frame — the
# very quiet-window row the gate at worth_recording was written to refuse.
_ph60 = run(lambda n, k: WHOLE, seconds=7.0, appear_at=4.0)
eq('four seconds out of sight is not a row at the real hold',
   [u for u in _ups(_ph60['rows']) if u[0] == 'phone'], [])
ok_('...over a run that did lose the phone for them (%r)'
    % [l for l in _ph60['logs'] if 'screen' in l][:2],
    any('not visible' in l for l in _ph60['logs']))


# --- a camera that hands over one picture for ever ---------------------------
#
# The owner's rig read once in 9.4 days with the heartbeat beating every four
# seconds and the panel saying "scanner reading". Whether the camera's feed had
# stalled or the box was dark is not known, so both are driven here.
#
# The stall first: the camera freezes 1.5s in, on the card, and from then on
# every capture is the same picture byte for byte. The stub reader goes on
# answering the card, which is what the verify beat re-reading a frozen card
# looks like — readings that look fresh, about a card long gone.
#
# Every stall here has a handoff directory of its own: going quiet over one
# leaves a note there (STALL_AGAIN), and a note left in the shared one would
# hold back the next run's restart — this suite's, or another's on the machine.
# run() gives every run one of its own for that reason.
_slho = tempfile.mkdtemp()
_sl = run(lambda n, k: WHOLE, seconds=8.0, freeze_at=1.5, stall_say=1.0,
          alive_every=0.5, handoff=_slho)
_slups = _ups(_sl['rows'])
ok_('a camera handing over the same picture is written as stalled (%r)' % _slups,
    ('camera', 'stalled') in _slups)
ok_('...and the beat carries it, for the panel',
    any(b.get('blind') == 'stalled' for b in _sl['alive']))
_sl_rs = [x.get('why') for x in _sl['rows']
          if x.get('kind') == 'up' and x.get('state') == 'restart']
ok_('...then the journal says the rig asked to be restarted, and why (%r)' % _sl_rs,
    len(_sl_rs) == 1 and 'stalled' in (_sl_rs[0] or ''))
# A stalled camera is not cured by waiting — the owner's ran 9.4 days that way,
# and a restart cured it at once — so it takes the stuck reader's way out: no
# more beats, and the supervisor's silence watchdog restarts it, counting it
# where a wedge is counted. At a half-second beat a loop still beating has its
# last beat under a second old.
_sl_gap = time.time() - _sl['beats'][-1] if _sl['beats'] else None
ok_('...and it goes quiet, the way a stuck read does, so the supervisor restarts '
    'it (last beat %.1fs ago)' % (_sl_gap or 0), _sl_gap is not None and _sl_gap > 3.0)
eq('...the last beat it sent being the one that told the panel why',
   _sl['alive'][-1].get('blind') if _sl['alive'] else None, 'stalled')
eq('...said once in the log', sum(1 for l in _sl['logs']
                                  if 'going quiet' in l and 'stalled' in l), 1)
_sl_note = _stall_note_age(_slho)
ok_('...leaving the run after it a note that it went quiet over a stall '
    '(%r seconds old)' % (_sl_note,),
    _sl_note is not None and 0 <= _sl_note < 8.0)
# ...and nothing more is read off the frozen picture once the stall is said.
# Frozen on a card, the verify beat re-read it every few seconds, each verdict
# as fresh-looking as a real one — and server.js counts a reading as the loop
# speaking, so the silence its watchdog restarts on never came.
_sl_told = [t for t, b in zip(_sl['beats'], _sl['alive']) if b.get('blind') == 'stalled'][:1]
_sl_after = [round(t - _sl_told[0], 1) for a, k, t in _sl['verdicts']
             if _sl_told and t > _sl_told[0] + 0.5]
eq('...and no reading of the frozen card comes after it, to keep the loop '
   'sounding alive', (bool(_sl_told), _sl_after), (True, []))

# ...but not restarted again within STALL_AGAIN of the last time. A camera a
# restart does not cure stalls again in the first seconds of the run after it,
# and nothing but server.js's backoff stopped the watchdog's restart going
# round all night, three rows a time. Here the run before has just gone quiet
# over a stall — its note is fresh — and this one's camera stalls as well.
def _leave_stall_note(handoff, ahead=0.0):
    """The note a run leaves as it goes quiet over a stall, in `handoff`,
    stamped `ahead` seconds past the clock."""
    was = os.environ.get(HO.ENV_DIR)
    os.environ[HO.ENV_DIR] = handoff
    try:
        with open(HO.path(HO.STALLED), 'w'):
            pass
        if ahead:
            stamp = time.time() + ahead
            os.utime(HO.path(HO.STALLED), (stamp, stamp))
    finally:
        if was is None:
            os.environ.pop(HO.ENV_DIR, None)
        else:
            os.environ[HO.ENV_DIR] = was


_agho = tempfile.mkdtemp()
_leave_stall_note(_agho)
_ag = run(lambda n, k: WHOLE, seconds=8.0, freeze_at=1.5, stall_say=1.0,
          alive_every=0.5, handoff=_agho)
_agups = _ups(_ag['rows'])
ok_('a stall soon after a restart over one is still written, and still told '
    'the panel (%r)' % _agups,
    ('camera', 'stalled') in _agups
    and any(b.get('blind') == 'stalled' for b in _ag['alive']))
eq('...but no second restart is asked for inside STALL_AGAIN',
   [x.get('why') for x in _ag['rows']
    if x.get('kind') == 'up' and x.get('state') == 'restart'], [])
_ag_gap = time.time() - _ag['beats'][-1] if _ag['beats'] else None
ok_('...the loop staying up, beating the stall to the panel to the end (last '
    'beat %.1fs ago, saying %r)' % (_ag_gap or 0, _ag['alive'][-1].get('blind')
                                    if _ag['alive'] else None),
    _ag_gap is not None and _ag_gap < 1.5
    and _ag['alive'][-1].get('blind') == 'stalled')
eq('...said once in the log, with the cable named',
   sum(1 for l in _ag['logs'] if 'stays up' in l and 'cable' in l), 1)
_ag_told = [t for t, b in zip(_ag['beats'], _ag['alive']) if b.get('blind') == 'stalled'][:1]
eq('...and still nothing read off the frozen picture while it does',
   (bool(_ag_told), [round(t - _ag_told[0], 1) for a, k, t in _ag['verdicts']
                     if _ag_told and t > _ag_told[0] + 0.5]), (True, []))

# ...and every stall is its own, in a run that sees more than one. A camera
# that comes back by itself after the run has gone quiet over it is beating
# again before the watchdog's thirty seconds are up, so nothing restarts it,
# and the same run meets the next stall. Here: the first goes quiet and leaves
# its note; the camera comes back; the second is inside STALL_AGAIN of that
# note and stays up; it comes back again; the third stays up as well and says
# so in the log again. A run that kept the first stall's answer asked for a
# second restart a few seconds after the first, its own note unread, and said
# nothing in the log about the third.
_3ho = tempfile.mkdtemp()
_3 = run(lambda n, k: WHOLE, seconds=11.5,
         freeze_at=[(1.5, 4.0), (5.0, 7.0), (8.0, None)], stall_say=1.0,
         alive_every=0.5, handoff=_3ho)
eq('a camera that stalls three times in a run, coming back between, is written '
   'as stalled three times',
   [u[1] for u in _ups(_3['rows']) if u[0] == 'camera'],
   ['stalled', 'seeing', 'stalled', 'seeing', 'stalled'])
eq('...the first going quiet for its restart, and only the first: the note it '
   'left holds back the next two',
   len([x for x in _3['rows'] if x.get('kind') == 'up' and x.get('state') == 'restart']), 1)
eq('...each of those said in the log as staying up, with the cable named',
   sum(1 for l in _3['logs'] if 'stays up' in l and 'cable' in l), 2)
_3_gap = time.time() - _3['beats'][-1] if _3['beats'] else None
ok_('...and the run up at the end, beating the last to the panel (last beat '
    '%.1fs ago, saying %r)' % (_3_gap or 0, _3['alive'][-1].get('blind')
                               if _3['alive'] else None),
    _3_gap is not None and _3_gap < 1.5 and _3['alive'][-1].get('blind') == 'stalled')

# ...and once that restart is STALL_AGAIN old, it asks again. The note is left
# as the loop begins, and STALL_AGAIN cut to six seconds: the stall is said
# under it and sat out, then goes quiet when the note ages past it.
_aaho = tempfile.mkdtemp()
_aa_noted = []


def _note_as_it_begins(rows, ann, calls):
    if not _aa_noted:
        _aa_noted.append(time.time())
        _leave_stall_note(_aaho)
    return False


_aa = run(lambda n, k: WHOLE, seconds=12.0, freeze_at=1.5, stall_say=1.0,
          alive_every=0.5, handoff=_aaho, stall_again=6.0, until=_note_as_it_begins)
_aa_st = [t for t, b in zip(_aa['beats'], _aa['alive']) if b.get('blind') == 'stalled']
_aa_rs = [x for x in _aa['rows'] if x.get('kind') == 'up' and x.get('state') == 'restart']
_aa_gap = time.time() - _aa['beats'][-1] if _aa['beats'] else None
ok_('...and asks again once the last restart is STALL_AGAIN old: the stall sat '
    'out first (%.1fs of beats saying it), then a restart row and quiet (last '
    'beat %.1fs ago)' % ((_aa_st[-1] - _aa_st[0]) if _aa_st else 0, _aa_gap or 0),
    _aa_st and _aa_st[-1] - _aa_st[0] >= 0.9 and len(_aa_rs) == 1
    and _aa_gap is not None and _aa_gap > 3.0)
# ...and a note stamped ahead of the clock is not a young one. Its age is its
# mtime against the wall clock, so a clock stepped back since it was left reads
# as a note not yet written — and a stall under it asks for its restart, as it
# did before the note existed, with server.js's backoff still bounding it.
_afho = tempfile.mkdtemp()
_leave_stall_note(_afho, ahead=3600.0)
_af = run(lambda n, k: WHOLE, seconds=8.0, freeze_at=1.5, stall_say=1.0,
          alive_every=0.5, handoff=_afho)
eq('a stall under a note stamped an hour ahead of the clock asks for its '
   'restart rather than sitting it out',
   len([x for x in _af['rows'] if x.get('kind') == 'up' and x.get('state') == 'restart']), 1)
# ...and every repeat is counted on the health line. That a working camera
# never hands one over rests on testcards' sensor model and not on the IMX519,
# whose frames nobody here has — so the rig's own log is where it gets
# measured, and a frozen camera is what a count looks like. The health line
# only speaks after reads, so the card reads as a fragment — which keeps the
# resample window reading every half second for four — and the stall is held
# off past the run, so nothing stops those reads.
_rep = run(lambda n, k: FRAG, seconds=6.0, freeze_at=1.0, stall_say=60.0,
           alive_every=0.5, health_every=0.2)
_rep_lines = [l for l in _rep['logs'] if l.startswith('health') and 'same picture' in l]
ok_('a frozen camera\'s repeated frames are counted on the health line (%r)'
    % (_rep_lines[-1:],),
    _rep_lines and re.search(r'\b\d+ frames since start the same picture',
                             _rep_lines[-1]))

# The stall again, from a camera stuck handing back its ring of buffers: the
# last CAMERA_BUFFERS pictures in turn, so no frame is the same as the one
# before it and a watch that only looked one back saw a working camera. At the
# real STALL_SAY, which is where the verify beat's reads come in: each takes a
# capture the watch never sees, and a watch that kept only CAMERA_BUFFERS
# frames lost the run of repeats on every one and never said it.
_ring = run(lambda n, k: WHOLE, seconds=12.0, freeze_at=1.5, alive_every=0.5,
            ring=SP.CAMERA_BUFFERS, handoff=tempfile.mkdtemp(),
            until=lambda rows, ann, calls: ('camera', 'stalled') in _ups(rows))
ok_('a camera handing back its ring of buffers, no frame the same as the one '
    'before, is written as stalled at the real hold, reads and all (%r)'
    % _ups(_ring['rows']),
    ('camera', 'stalled') in _ups(_ring['rows']) and _ring['submitted'] >= 2)

# ...and a still card is not a stall. A sensor's noise differs from frame to
# frame however still the picture, which is what the fakes' dither stands for,
# and this card sits still for 8.6s at the real STALL_SAY.
_still = run(lambda n, k: WHOLE, seconds=9.0, alive_every=0.5, health_every=1.0)
eq('a card sitting still past the stall\'s hold is not a stall',
   [u for u in _ups(_still['rows']) if u[0] == 'camera'], [])
eq('...and no beat says it cannot see',
   [b.get('blind') for b in _still['alive'] if b.get('blind')], [])
ok_('...on a run long enough to have said so (%d beats)' % len(_still['beats']),
    _still['beats'] and _still['beats'][-1] - _still['beats'][0] > SP.STALL_SAY)
_still_health = [l for l in _still['logs'] if l.startswith('health')]
eq('...and its health lines count no repeated frame, on %d of them'
   % len(_still_health),
   (bool(_still_health), [l for l in _still_health if 'same picture' in l]),
   (True, []))

# ...nor is a picture that is one flat value all over, repeated. Two of those
# match whatever the camera is doing — a box of black, a sensor at full well —
# so a repeat of one is no evidence. Noise off, and nothing but the empty
# cabin, which is uniform.
_flat = run(lambda n, k: '', seconds=5.0, appear_at=1e9, noise=False,
            stall_say=1.0, alive_every=0.5)
eq('a flat picture repeated is not a stall',
   [u for u in _ups(_flat['rows']) if u[0] == 'camera'], [])
# ...nor one that is black clamped against full well and nothing between: the
# two places a sensor's noise is clipped away, so nothing in the picture could
# show any. Split where the preview's pixels split, so no pixel is a blend.
_split = np.zeros((CAP[1], CAP[0], 3), np.uint8)
_split[:, CAP[0] // 2:] = 255
_railcam = []
_rails = run(lambda n, k: '', seconds=5.0, appear_at=1e9, noise=False, empty=_split,
             stall_say=1.0, alive_every=0.5, cam_out=_railcam)
eq('the fixture really is two values and nothing between',
   sorted(set(_railcam[0].lores[:LORES[0] * LORES[1]].tolist())) if _railcam else None,
   [0, 255])
eq('a picture of black against full well, repeated, is not a stall either',
   [u for u in _ups(_rails['rows']) if u[0] == 'camera'], [])

# --- a box too dark to be sure of seeing in -----------------------------------
#
# The other half: the owner's screen read 1-2 of 205 in the reads either side of
# the blind week. The box drawn by hand — --no-track here, the other rig with
# nothing tracking the corners — holds the dark cabin until the card arrives
# four seconds in. Reads answer nothing until there is a card in the mount, so
# the rig is not reading a card it cannot see. A long beat, so the beats that
# come are the ones a change sends.
#
# The gain starts on its ceiling, and the one place too_dim could fire on that
# box at all: from the usual 1.5 the gain never climbs on darkness. Not a
# contrived start: a 📷 Snap off the owner's rig at 15:05 on 8 Oct, in
# daylight, has the box at 218 with the gain at 7.16 of its 8.0.
_dkcam = []
_DARK = np.full((CAP[1], CAP[0], 3), 1, np.uint8)


def _dk_text(n, k):
    return WHOLE if _dkcam and _dkcam[0].frame is _dkcam[0].offer else ''


_dk = run(_dk_text, extra_argv=['--no-track'], seconds=14.0, appear_at=4.0,
          empty=_DARK, phone_hold=1.0, alive_every=30.0, cam_out=_dkcam,
          config_extra={'analogueGain': SP.EX.GAIN_LIMITS[1]},
          until=lambda rows, ann, calls: ('camera', 'seeing') in _ups(rows) and ann)
_dkups = _ups(_dk['rows'])
ok_('a box with nothing lit in it is written as dark, with nothing tracking (%r)'
    % _dkups, ('camera', 'dark') in _dkups)
_dkrow = [x for x in _dk['rows'] if x.get('about') == 'camera'
          and x.get('state') == 'dark'][:1] or [{}]
ok_('...with what the box read, under what a lit screen reads (%r)'
    % (_dkrow[0].get('bright'),),
    isinstance(_dkrow[0].get('bright'), (int, float))
    and _dkrow[0]['bright'] < SP.EX.LIT_ENOUGH)
_dkbeats = [(t, b) for t, b in zip(_dk['beats'], _dk['alive'])]
ok_('...the beat carries it, at once rather than on the next beat',
    any(b.get('blind') == 'dark' for _, b in _dkbeats))
# Asked by the name the loop hands emit_alive, `too_dim`. This asked for the
# wire's `tooDim` off the loop's own arguments, which is never there, so it
# held whatever the gain did — the start at 1.5 was not the only reason it
# could not fail. Measured with too_dim no longer asking `lit`: the log said
# the phone was dimmer than the camera could make up for, the beat that said
# dark carried too_dim True, and this passed. A beat without the key is not
# taken as "not too dim" either.
_dk_dim = [b.get('too_dim', 'not on the beat') for _, b in _dkbeats
           if b.get('blind') == 'dark']
eq('...and never as too dim, with the gain on its ceiling: too dim is a screen '
   'the gain counted as lit, and this one it never did (%r)' % (_dk_dim,),
   (bool(_dk_dim), [d for d in _dk_dim if d is not False]), (True, []))
ok_('...and the card arriving is seeing again (%r)' % _dkups,
    ('camera', 'seeing') in _dkups
    and _dkups.index(('camera', 'dark')) < _dkups.index(('camera', 'seeing')))
# The page puts the blind word where the verdict goes, so a card arriving as
# the phone goes back in has to be cleared for at once — not on the next beat,
# which this run has set thirty seconds away, and not on the gain's next look
# at the box, up to six seconds on.
_dk_card = [t for a, k, t in _dk['verdicts'] if a and a[0].get('ready')]
_dk_dark_at = [t for t, b in _dkbeats if b.get('blind') == 'dark'][:1]
_dk_clear = [t for t, b in _dkbeats
             if _dk_dark_at and t > _dk_dark_at[0] and b.get('blind') is None][:1]
ok_('...cleared on the beat within a second of the card\'s first reading '
    '(%r after it)' % ((round(_dk_clear[0] - _dk_card[0], 2),)
                       if _dk_card and _dk_clear else None,),
    _dk_card and _dk_clear and abs(_dk_clear[0] - _dk_card[0]) < 1.0)


def _cleared_after_card(r):
    """Seconds from the card's first reading to the beat that cleared the
    dark, or None."""
    beats = list(zip(r['beats'], r['alive']))
    card = [t for a, k, t in r['verdicts'] if a and a[0].get('ready')]
    dark = [t for t, b in beats if b.get('blind') == 'dark'][:1]
    clear = [t for t, b in beats if dark and t > dark[0] and b.get('blind') is None][:1]
    return round(clear[0] - card[0], 2) if card and clear else None


# ...and the same with the read on the loop's own thread, where it has been
# done and collected before the camera's word is next asked — so "a read is in
# flight" is never true at the moment it is asked, and only the read having
# been handed over says the box moved. A card at half its brightness: one at
# full well makes the gain look again within a second whatever the reader
# did, and this is about the reader.
_dkcam[:] = []
_dkn = run(_dk_text, extra_argv=['--no-track', '--no-thread'], seconds=14.0,
           appear_at=4.0, empty=_DARK, phone_hold=1.0, alive_every=30.0,
           cam_out=_dkcam, offer_dim=0.5,
           until=lambda rows, ann, calls: ('camera', 'seeing') in _ups(rows) and ann)
_dkn_gap = _cleared_after_card(_dkn)
ok_('...and cleared as quickly with --no-thread (%r after it)' % (_dkn_gap,),
    _dkn_gap is not None and abs(_dkn_gap) < 1.0)

# ...and where the tracker runs, the same dark box is its answer — the phone
# gone — and not a second row about the same absence. Long enough for the
# gain's second look, the first that can see the tracker has lost the phone.
_dkt = run(lambda n, k: '', seconds=9.0, appear_at=1e9, empty=_DARK, phone_hold=1.0)
_dktups = _ups(_dkt['rows'])
ok_('a tracked rig answers a dark box with the phone gone (%r)' % _dktups,
    ('phone', 'gone') in _dktups)
eq('...and writes nothing about the camera for it',
   [u for u in _dktups if u[0] == 'camera'], [])


# --- the GPS, through the real loop ------------------------------------------
#
# A phone whose GPS app answers, hands over positions, and then stops — the
# app's timer running out, which is the ordinary way a shift loses its fix.
# Timed from the first time the loop asks rather than from start(): start()
# runs before the camera opens, and a clock started there would have the phone
# answering before the loop ever looked.
class _StubPhone(object):
    host, port = 'phone', 2947

    def __init__(self):
        self.t0 = None

    def start(self):
        return self

    def stop(self):
        pass

    def fix(self):
        return None

    def latest(self):
        return None

    def state(self):
        if self.t0 is None:
            self.t0 = time.time()
        t = time.time() - self.t0
        # Under the 0.5s hold the run uses, so 'looking' can never last long
        # enough to be written as lost before the first fix arrives.
        if t < 0.4:
            return {'state': 'looking', 'ageSeconds': None,
                    'error': 'ConnectionRefusedError: [Errno 111] Connection refused'}
        if t < 2.0:
            return {'state': 'fixed', 'ageSeconds': 0.4, 'error': None}
        return {'state': 'stale', 'ageSeconds': round(t - 1.6, 1),
                'error': 'OSError: the phone closed the connection'}


def _and_then(seen, extra=0.5):
    """Stop `extra` seconds after `seen(rows)` first holds, not at once: the
    row is written mid-pass and the beat that carries the same word comes on
    a later one, so a run halted at the row never sees the beat."""
    first = []

    def until(rows, ann, calls):
        if not first and seen(rows):
            first.append(time.time())
        return bool(first) and time.time() - first[0] > extra
    return until


_g = run(lambda n, k: WHOLE, extra_argv=('--gps', 'phone'), seconds=15.0,
         alive_every=0.05, gps_hold=0.5, phone=_StubPhone(),
         until=_and_then(lambda rows: ('gps', 'stale') in _ups(rows)))
_gups = [x for x in _g['rows'] if x.get('kind') == 'up']
eq('a rig asked for a position says so on its start row',
   ([x.get('gps') for x in _gups if x.get('state') == 'start'] or [None])[0], True)
eq('the GPS coming up and then going stale are two rows, in that order (%r)'
   % _ups(_g['rows']),
   [u for u in _ups(_g['rows']) if u[0] == 'gps'], [('gps', 'ok'), ('gps', 'stale')])
_gst = [x for x in _gups if x.get('about') == 'gps' and x.get('state') == 'stale'][:1] or [{}]
ok_('...the stale one saying how old the fix was and why (%r)'
    % ((_gst[0].get('ageSeconds'), _gst[0].get('why')),),
    isinstance(_gst[0].get('ageSeconds'), float) and _gst[0]['ageSeconds'] > 0.4
    and 'closed the connection' in (_gst[0].get('why') or ''))
_gwords = [b['gps']['state'] for b in _g['alive'] if b.get('gps')]
_gseq = [w for i, w in enumerate(_gwords) if i == 0 or w != _gwords[i - 1]]
eq('the beat said nothing until the first fix, then ok, then stale (%r)' % (_gseq,),
   _gseq, [None, 'ok', 'stale'])
ok_('...and, stale, how old the fix is, which is what the panel prints',
    any(b['gps']['state'] == 'stale' and (b['gps']['ageSeconds'] or 0) > 0.4
        for b in _g['alive'] if b.get('gps')))

# --gps given and unusable: the rig was asked for a position and will never
# get one. It must not read as a rig nobody asked — that is the panel keeping
# quiet about the very thing the flag was typed for.
_gr = run(lambda n, k: WHOLE, extra_argv=('--gps', 'phone:notaport'), seconds=10.0,
          alive_every=0.05, gps_hold=0.3,
          until=_and_then(lambda rows: ('gps', 'lost') in _ups(rows)))
_grl = [x for x in _gr['rows'] if x.get('kind') == 'up' and x.get('about') == 'gps']
eq('a --gps that cannot be used is written as lost (%r)' % _ups(_gr['rows']),
   [x.get('state') for x in _grl], ['lost'])
ok_('...with the reason it could not be used (%r)' % ((_grl or [{}])[0].get('why'),),
    'could not use --gps' in ((_grl or [{}])[0].get('why') or ''))
ok_('...and the beat says lost, not off',
    any((b.get('gps') or {}).get('state') == 'lost' for b in _gr['alive'])
    and not any((b.get('gps') or {}).get('state') == 'off' for b in _gr['alive']))


# ONE fix per landing, handed to the row and to the offer line. A receiver
# that answers differently on every call — a car moving, a thread storing a
# newer sentence between two asks — is what tells one call from two: with two,
# the row and the line put one card in two places. Each answer is judged the
# way gps.Phone judges, so `ok`/`why` travel as they do on the rig. Marietta
# Square and points north of it, not anywhere the rig has been.
class _MovingPhone(object):
    host, port = 'gpsd', 2947

    def __init__(self):
        self.asked = 0

    def start(self):
        return self

    def stop(self):
        pass

    def fix(self):
        self.asked += 1
        return {'lat': 33.9526 + self.asked * 0.001, 'lon': -84.5499,
                'ageSeconds': 0.4, 'mode': 3, 'err': 12.0, 'ok': True,
                'why': None, 'source': 'gpsd'}

    def latest(self):
        # The beat's fix, kept apart from the rows' so a check can tell which
        # one reached the beat.
        return {'lat': 34.0001, 'lon': -84.5499, 'ageSeconds': 0.4, 'mode': 3,
                'err': 12.0, 'ok': True, 'why': None, 'freshFor': 19.6,
                'source': 'gpsd'}

    def state(self):
        return {'state': 'fixed', 'ageSeconds': 0.4, 'error': None}


_mp = _MovingPhone()
_m = run(lambda n, k: WHOLE, extra_argv=('--gps', 'gpsd'), seconds=15.0,
         alive_every=0.05, phone=_mp,
         until=lambda rows, ann, calls: len(ann) >= 1
         and any(not x.get('kind') for x in rows))
_mrows = [x for x in _m['rows'] if not x.get('kind')]
_mkw = _m['offer_kw'][:1] or [{}]
_mline = SP.JR.fix_fields(_mkw[0].get('where'))
ok_('a --gps run lands a row and tells its offer (%d rows, %d lines)'
    % (len(_mrows), len(_m['offer_kw'])), _mrows and _m['offer_kw'])
eq('the offer line and the row carry the same fix',
   _mline, {k: (_mrows[:1] or [{}])[0].get(k) for k in SP.JR.FIX_FIELDS})
ok_('...a real one, judged usable (%r)' % (_mline.get('lat'),),
    _mline.get('lat') is not None and _mline.get('gpsOk') is True)
eq('...and the line is told whether the card was whole, as the row was',
   _mkw[0].get('whole'), (_mrows[:1] or [{}])[0].get('whole'))
_mbeat = [b['gps'].get('fix') for b in _m['alive'] if (b.get('gps') or {}).get('fix')]
eq('the beat carries the newest fix with its quality and the gate\'s answer',
   (_mbeat[-1] if _mbeat else {}).get('lat'), 34.0001)
eq('...in the journal\'s own fields, the time it has left inside the rule, '
   'its speed, whether the car is being driven and for how long that holds',
   sorted((_mbeat[-1] if _mbeat else {}).keys()),
   sorted(SP.JR.FIX_FIELDS + ('freshFor', 'speed', 'driving', 'drivingFor')))

# --- which frame of one read gets published ----------------------------------
#
# A read hands back two frames 33ms apart, and the loop published the later one
# whatever it said. accumulate.add short-circuits on a payout-free frame — it
# hands the parse straight back with mergedFrom 0, which digest()'s destination
# branch relies on — so when the partner frame was the one that lost its payout
# to glare or to the crop edge, the merge was bypassed for the whole read.
#
# Measured on the real accumulator: '$16.05 3 min (1.1 mi) away 20 min (7.3 mi)
# trip' merges to complete=True, 23.0 min, 8.4 mi; the same text with the payout
# gone publishes complete=False, mergedFrom=0 and a rate that is not ready. The
# panel paints grey WAITING over a verdict the rig had 33 milliseconds earlier.
_paid = {'parsed': {'pay': 16.05}}
_glared = {'parsed': {'pay': None}}
eq('the frame that read the money is the one published',
   SP.read_the_money([_paid, _glared]), 0)
eq('...and it is the LAST such frame, not the first',
   SP.read_the_money([{'parsed': {'pay': 9.0}}, _glared, {'parsed': {'pay': 11.0}}]), 2)
eq('...still the later frame when that is the one with the money',
   SP.read_the_money([_glared, _paid]), 1)
# A screen with no payout on it at all is not a damaged offer card, it is a
# navigation app or a dropoff address, and it still has to digest as itself.
eq('a read with no payout anywhere publishes the last frame, as before',
   SP.read_the_money([_glared, {'parsed': {}}]), 1)
eq('...and a single-frame read is unaffected', SP.read_the_money([_glared]), 0)
# A zero payout is not a payout, and `True` is not 1.0 however much Python
# would like it to be.
eq('a zero payout does not count as having read the money',
   SP.read_the_money([{'parsed': {'pay': 0}}, _glared]), 1)
eq('...nor does a boolean that happens to be truthy',
   SP.read_the_money([{'parsed': {'pay': True}}, _glared]), 1)

# ...and the wiring, asserted on the source and said plainly rather than
# dressed up as a runtime test. collect() is a closure inside the scan loop:
# reaching it means running the loop, which means a camera. What CAN be checked
# without one is that it asks the question above instead of taking the last
# frame regardless, and that it does not hand the chosen frame to the
# accumulator twice — digest() adds that one itself, and a card merged with a
# copy of itself is a different reading.
_loop_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              'scan_pi.py')).read()
ok_('the loop publishes the frame that read the money',
    'chosen = read_the_money(batch)' in _loop_src)
ok_('...and feeds every frame but that one to the accumulator',
    'if i != chosen:' in _loop_src)

# ...and the same for the half of the screen-row wiring a run cannot reach.
#
# Everything else about these rows is driven through main() above. The one
# thing that is not is a screen row carrying `cardWasUp: false`, because that
# needs a SECOND payout-free read, and reads are driven by the motion gate: the
# stubbed camera holds one picture, so once the card stops reading as a card the
# verify beat stops and nothing looks again. A real navigation screen moves for
# a whole delivery and has no such problem.
#
# Two fixtures were built to close that and neither survives the real screen
# detector — a light one blows the exposure out ("the card was blown out with
# the gain already at its floor", four times, no read) and a dark one is not
# seen at all ("screen not visible"). Both were deleted rather than left in
# passing for the wrong reason. `note_screen`'s own suite covers what the row
# says; what is left to check here is that the loop hands it the right answer
# rather than a constant, which is exactly the shape the check above is for.
ok_('the loop tells a screen row whether a card was up a moment ago',
    'card_was_up=card_on_screen' in _loop_src)

# ...and the other half of the dropoff answer that a run cannot reach: it waits
# for any read that STARTED inside the window, because such a read can still
# answer the press. These checks run --no-parallel, where a read is synchronous
# and `reader.busy` is never true at the moment the window is judged; the
# threaded path is the one it is for, and on the rig a read started at 11.9s of
# a twelve-second window lands a second or more after it. The predicate is the
# same one `asked` itself uses, which is the property worth pinning.
ok_('the empty dropoff answer waits for a read that could still answer it',
    'reader.since < dropoff_until' in _loop_src)

# --- a dropoff scan that finds nothing says so -------------------------------
#
# The rig emitted only from inside `if found:`, so a press that found no
# address produced no line at all and the panel's own timer repainted the
# button exactly as it was. The driver tapped the address open on their phone,
# pressed, waited, and got the same grey button whether it had worked or not.
# Every other control on that bar names its failure: "Took …" over "not saved",
# "Drop · failed", "⟳ failed", "could not set the box: …".
#
# Answered from HERE and not from a timer on the page. `asked` is
# `began < dropoff_until`, so a read that began before the deadline still
# counts and still emits when it lands — 1.8s median on this Pi and 5.9s at
# worst measured. A page giving up on its own clock would print "not read" and
# then be corrected by a green address a moment later, which is this project's
# first fault class used to cure its second.
#
# Run to the deadline rather than to a read count: the answer comes when the
# WINDOW closes, and a run that stops at four reads stops before it does.
#
# Pressed from inside the first read, not before run() starts. A press is taken
# only while it is younger than the window (a press nobody was listening for is
# stale, see dropoff_requested), and these runs use a one-second window — so a
# file written before main() imports and calibrates was discarded whenever
# start-up took longer than a second, which it did under the full runner's load
# and not alone. That is the rig being right and the test pressing too early.
def _press_on_first_read(handoff, text):
    def texts(n, k):
        if n == 1 and k == 0:
            open(os.path.join(handoff, 'uberscan-dropoff'), 'w').close()
        return text
    return texts


_ho = tempfile.mkdtemp()
r5 = run(_press_on_first_read(_ho, WHOLE), extra_argv=['--no-parallel'], seconds=6.0,
         handoff=_ho, dropoff_window=1.0)
_said = [d for d in r5['dropoffs'] if d[1].get('asked')]
ok_('a press that found no address is answered, not left silent (%r)'
    % (r5['dropoffs'][:1],), len(_said) == 1)
if _said:
    eq('...with no address, because there was none', _said[0][0], None)
    ok_('...and marked as the answer to a press', _said[0][1].get('asked'))
ok_('...and the log says it too, for whoever reads one',
    any('read as an address' in l for l in r5['logs']))
# ONCE. The window closes, it is answered, and the answer does not repeat on
# every pass of the loop for the rest of the shift.
eq('...said once, over %d reads' % r5['calls'], len(_said), 1)

# ...and a press that IS answered is not also reported as a failure.
#
# This one found a real fault rather than guarding one. `asked` is false for a
# read that began after the deadline, and the press was being closed only by an
# asked read — so a read straddling the deadline sent the address, the panel
# put it up in green, and the press stayed outstanding until the branch below
# announced "nothing on that screen read as an address" over the address
# already showing. Two claims about one press, the second contradicting the
# first, on the screen the driver is reading in a moving car. Any address
# closes the press now.
_ho2 = tempfile.mkdtemp()
NAV_ADDR = 'Dropoff 123 Main St, Acworth, GA 30101 12 min Start'
r7 = run(_press_on_first_read(_ho2, NAV_ADDR), extra_argv=['--no-parallel'], seconds=6.0,
         handoff=_ho2, dropoff_window=1.0)
_found = [d for d in r7['dropoffs'] if d[0] is not None]
_empty = [d for d in r7['dropoffs'] if d[0] is None]
ok_('a press that finds an address is answered with it (%r)'
    % ([(d[0] or {}).get('line') for d in r7['dropoffs']][:2],), len(_found) >= 1)
eq('...and is not ALSO reported as having found nothing', _empty, [])

# --- a ⌖ press reads the whole screen box, and only the destination off it --
#
# A tight card box drawn by hand kept the reader off the map, and blinded ⌖ to
# the trip planner's addresses outside it. So while a press is open the read
# takes all of the screen box. That reading is the card AND what surrounds it,
# which is no evidence about the offer's money, so it answers the press and
# nothing else.
_ho3 = tempfile.mkdtemp()
r8 = run(_press_on_first_read(_ho3, WHOLE), extra_argv=['--no-parallel'], seconds=6.0,
         handoff=_ho3, dropoff_window=1.0, whole_text=NAV_ADDR)
ok_('a ⌖ press reads the whole screen box (%r)' % r8['wholes'][:6], any(r8['wholes']))
eq('...not before it was pressed', r8['wholes'][0], False)
eq('...and goes back to the card box once it is answered', r8['wholes'][-1], False)
ok_('...and the address outside the card box is the answer (%r)'
    % [(d[0] or {}).get('line') for d in r8['dropoffs']][:2],
    any(d[0] and 'Main St' in (d[0].get('line') or '') and d[1].get('asked')
        for d in r8['dropoffs']))
# ...and the panel is not told a card is being priced while it happens. A ⌖
# read answers with an address or nothing, never with `ready`, so the reading
# cue it used to send stood on the panel as READING THE CARD, "working out the
# pay, the time and the distance", for the page's whole READING_MS after each
# one — over a navigation screen, through the whole window.
_card_reads = r8['submitted_whole'].count(False)
ok_('the premise: both kinds of read were handed over (%d whole, %d card)'
    % (r8['submitted_whole'].count(True), _card_reads),
    r8['submitted_whole'].count(True) >= 1 and _card_reads >= 1)
eq('...and the panel is told a read began for the card reads only',
   r8['readings'], _card_reads)

# The whole-screen read sees a DIFFERENT payout here — a card under a map, a
# planner listing two orders' totals. If it reached the offer, the panel would
# show a verdict for money no card on the phone offered.
_ho4 = tempfile.mkdtemp()
r9 = run(_press_on_first_read(_ho4, WHOLE), extra_argv=['--no-parallel'], seconds=6.0,
         handoff=_ho4, dropoff_window=1.0,
         whole_text='$99.00 20 min (5.0 mi) trip Dropoff 9 Elm St, Acworth, GA 30101')
ok_('a press with a payout in the whole screen box was read whole', any(r9['wholes']))
_pays = sorted(set((v[0][1] or {}).get('pay') for v in r9['verdicts']
                   if len(v[0]) > 1 and isinstance(v[0][1], dict)), key=str)
ok_('...and that payout never reached a verdict (%r)' % _pays, 99.0 not in _pays)
ok_('...nor the journal', all(row.get('pay') != 99.0 for row in r9['rows']))

# ...and a rig nobody pressed anything on says nothing. Without this the checks
# above pass on a message that is simply always sent.
r6 = run(lambda n, k: WHOLE, extra_argv=['--no-parallel'], seconds=6.0,
         handoff=tempfile.mkdtemp(), dropoff_window=1.0)
eq('a rig nobody pressed says nothing about a dropoff',
   [d for d in r6['dropoffs'] if d[1].get('asked')], [])
eq('...and reads only the card box', [w for w in r6['wholes'] if w], [])

# --- a ⌖ press over Uber's Trip Planner -------------------------------------
#
# The planner prints no ZIP, so find_address returns None on it and the press
# used to end "not read" twelve seconds later with every stop on the screen.
# Now the planner answers the press, on its own line, the moment a whole-screen
# read finds it; its one dropoff, when it has exactly one, goes on through the
# dropoff line to the consumer every destination has.
#
# The real twelve-second window, not the one-second one above: "answered at
# once" means nothing in a window that shuts by itself a second later. The card
# box sees a blank screen, so every word of the planner came off a ⌖ read.
_PLANNERS = {c['name']: c['text'] for c in json.load(open(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'tests', 'fixtures', 'cases.json'), encoding='utf-8'))['planner']}
_ONE_DROP = _PLANNERS["Uber's Trip Planner as the rig's live view read it"]
# ...the same pixels cropped to the phone's glass, which is what the screen box
# is: "Waybill" read under the stop, so both ends of the list are on it.
_ONE_DROP_WHOLE = _PLANNERS["Uber's Trip Planner as the rig read it off the phone's glass"]
_TWO_DROPS = _PLANNERS['two dropoffs are both listed, in the order the screen gives them']


# --- the assembler, given what the loop sent ------------------------------------
#
# A Trip Planner's one dropoff, and the reason it gives none, are no longer
# decided in this process: the scanner sends the sighting and server.js asks
# assemble.js (Stage 3). So the checks below that used to read the dropoff
# line off a planner hand the sightings the loop ACTUALLY SENT to the real
# assembler, in node, and read its answer: the scanner's half and the
# server's half of one decision, end to end, with nothing restated here.
# `hold` is the order in the car, as server.js would have it, or None.
import subprocess  # noqa: E402

_ASSEMBLE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'assemble.js')
_ASSEMBLE_JS = r"""
var A = require(process.argv[1]);
var input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
var st = A.fresh(), hold = input.hold, out = [];
input.sightings.forEach(function (s) {
  var r = A.sighting(st, hold, s, s.at);
  r.candidates.forEach(function (c) {
    var said = A.dropoff(hold, c, null);
    A.file(hold, c, said, st);
    out.push({ line: c.line, street: c.street, city: c.city, state: c.state, zip: c.zip,
               asked: said.asked, labelled: said.labelled,
               singleCardOnly: c.singleCardOnly === true, kept: said.kept,
               from: said.from });
  });
});
process.stdout.write(JSON.stringify({
  dropoffs: out,
  unfiled: input.sightings.map(function (s) {
    var v = A.verdictFor(st, s.at);
    return v === undefined ? '<no verdict>' : v;
  }),
  byAt: input.sightings.reduce(function (m, s) {
    var v = A.verdictFor(st, s.at);
    m[s.at] = v === undefined ? '<no verdict>' : v;
    return m;
  }, {}),
  hold: hold }));
"""


def assembled(sightings, hold=None):
    """What assemble.js makes of `sightings`, against `hold`."""
    done = subprocess.run(['node', '-e', _ASSEMBLE_JS, _ASSEMBLE],
                          input=json.dumps({'sightings': sightings, 'hold': hold}),
                          capture_output=True, text=True, timeout=60)
    if done.returncode:
        raise RuntimeError(done.stderr)
    return json.loads(done.stdout)


def _held(card=None):
    """An order in the car since long before any of these reads, with the
    card's own corner as its end."""
    return {'id': 'o-held', 'acceptedAt': 0, 'minutes': 30,
            'dropoff': 'Oak Dr & Elm Dr, Acworth', 'dropoffScanned': False,
            'card': card or {'legs': 1, 'multiOrder': True}}

_hp1, _pl1 = tempfile.mkdtemp(), []
rp1 = run(_press_on_first_read(_hp1, ''), extra_argv=['--no-parallel'], seconds=5.0,
          handoff=_hp1, whole_text=_ONE_DROP_WHOLE, planners=_pl1)
eq('⌖ over a Trip Planner is answered with the planner, once (%d reads)' % rp1['calls'],
   len(rp1['planners']), 1)
if rp1['planners']:
    eq('...its stops as the screen listed them',
       [[s['kind'], s['expectedBy'], s['line']] for s in rp1['planners'][0][0]],
       [['dropoff', 978, '4821 Kestrel Dr, Marietta']])
    # The journal may hold them: this run keeps a journal, and keepPlaces is
    # not off. See the two runs further down for the other two answers.
    eq('...saying none was left unfiled, and that the journal may keep them',
       (assembled(rp1['sightings'])['byAt'].get(str(rp1['planners'][0][1].get('at'))),
        rp1['planners'][0][1].get('keep')), (None, True))
    eq('...and the planner line carries the stamp of the sighting it follows',
       [p[1].get('at') for p in rp1['planners']],
       [x['at'] for x in rp1['sightings'] if x['screen'] == 'uber.planner'])
eq('...and its one dropoff, on a list seen whole, is the address the press gets, '
   'off its sighting', [(d['line'], d['asked'])
                        for d in assembled(rp1['sightings'])['dropoffs']],
   [('4821 Kestrel Dr, Marietta', True)])
eq('...and the scanner sends no dropoff line of its own off a planner',
   rp1['dropoffs'], [])
eq('...off the first whole-screen read, then back to the card box (%r)' % rp1['wholes'],
   (sum(rp1['wholes']), rp1['wholes'][-1] if rp1['wholes'] else None), (1, False))
# The `whole` early return in digest() is what keeps this off the offer path,
# and nothing else does: the planner has no payout, so it would never have
# made a verdict — but it WOULD have gone to the panel as a reading, in place
# of whatever the driver was looking at, and through the health tally.
eq('...and the planner reaches no reading the panel is sent',
   [v[0][1].get('rawText') for v in rp1['verdicts']
    if len(v[0]) > 1 and 'Kestrel' in ((v[0][1] or {}).get('rawText') or '')], [])
eq('...nor the journal as an offer', [x for x in rp1['rows'] if not x.get('kind')], [])

# --- a sighting beside the planner line ---------------------------------------
#
# Stage 2 of the multi-order design: the read that answered the press goes out
# as a sighting too, typed by its screen, filing nothing. Its stops are the
# planner line's stops — the one list, said twice, never two readings of it.
# Compared on every field the planner line carries, so a sighting that lost
# the name, re-read the street or dropped a stop is named here.
_PLANNER_FIELDS = ('kind', 'orders', 'name', 'expectedBy', 'street', 'city',
                   'state', 'zip', 'line', 'place')
_said_stops = [[[s.get(k) for k in _PLANNER_FIELDS] for s in p[0]]
               for p in rp1['planners']]
_seen_stops = [[[s.get(k) for k in _PLANNER_FIELDS] for s in x['stops']]
               for x in rp1['sightings']]
ok_('a planner read emits the planner line and a sighting with the same stops '
    '(%r against %r)' % (_seen_stops, _said_stops),
    len(_said_stops) == 1 and _seen_stops == _said_stops)
eq('...the sighting typed as the planner, off the whole screen, under the press',
   [(x['app'], x['screen'], x['whole'], x['asked'], x['page'], x['orderCount'], x['keep'])
    for x in rp1['sightings']],
   [('uber', 'uber.planner', True, True, {'top': True, 'bottom': True}, 1, True)])
eq('...and each stop labelled by its own header, none of them cut',
   [[(s['label'], s['partial']) for s in x['stops']] for x in rp1['sightings']],
   [[('dropoff', None)]])
# ...and nothing else: the card-box reads round the press found no planner and
# were not of the whole screen, so they are not sightings. The panel and the
# journal see nothing new — see "nor the journal as an offer" above.
eq('...and the card-box reads round it are no sighting (%d reads)' % rp1['calls'],
   len(rp1['sightings']), 1)

# A page that begins in the middle of one stop and ends on the header of the
# next: the layout of a read of a stacked trip's planner, scrolled (the corpus
# case, invented street). The sighting keeps both cut stops and says where
# each was cut; the planner line, and the destination, are given only the
# headed stop and no mark, which is what they were given before there was a
# sighting.
_CUT_PAGE = _PLANNERS['a page that starts mid-stop keeps the address above the first '
                      'header, of no kind, partial at the top']
_hpc = tempfile.mkdtemp()
rpc = run(_press_on_first_read(_hpc, ''), extra_argv=['--no-parallel'], seconds=4.0,
          handoff=_hpc, whole_text=_CUT_PAGE)
_cut = [s for x in rpc['sightings'] for s in x['stops']]
ok_('a header at the foot of a page is kept, partial (%r)'
    % [(s['kind'], s['partial']) for s in _cut],
    len(_cut) == 2 and (_cut[-1]['kind'], _cut[-1]['label'], _cut[-1]['partial'],
                        _cut[-1]['line']) == ('dropoff', 'dropoff', 'bottom', None))
eq('...and the address above the first header is kept, of no kind, partial',
   [(s['kind'], s['label'], s['partial'], s['line']) for s in _cut[:1]],
   [(None, None, 'top', '1650 Fable Ridge Blvd NW, Kennesaw')])
eq('...and the planner line is given the headed stop alone, unmarked, as before',
   [[sorted(s) for s in p[0]] for p in rpc['planners']],
   [[sorted(_PLANNER_FIELDS)]])
eq('...and the address above it is filed as nobody\'s end',
   [d[0] for d in rpc['dropoffs'] if d[0]], [])

# The same planner as the WHOLE live view read it: "Waybill" lost, so the rig
# cannot say the list ends under the one dropoff it can see. Two open stops
# fill the list (OP.planner_bounded), and the one dropoff on the glass of a
# longer trip may be another customer's door.
_hp1b = tempfile.mkdtemp()
rp1b = run(_press_on_first_read(_hp1b, ''), extra_argv=['--no-parallel'], seconds=5.0,
           handoff=_hp1b, whole_text=_ONE_DROP)
ok_('the premise: that read has one dropoff and no end to its list',
    [s['kind'] for s in OP.find_planner(_ONE_DROP)] == ['dropoff']
    and not OP.planner_bounded(_ONE_DROP))
_as1b = assembled(rp1b['sightings'], _held())
eq('one dropoff on a list the rig could not see the end of is answered with the '
   'stop and the reason, once',
   [([s['line'] for s in p[0]], _as1b['byAt'].get(str(p[1].get('at'))))
    for p in rp1b['planners']],
   [(['4821 Kestrel Dr, Marietta'], 'list')])
eq('...and is not filed as the order\'s end, nor told "not read" over the stop',
   (rp1b['dropoffs'], _as1b['dropoffs']), ([], []))

# Two dropoffs, the second with a ZIP — so find_address, left to itself, would
# have answered the press with that customer's door, chosen by layout.
ok_('the premise: find_address alone would answer this planner with its last '
    'dropoff', (OP.find_address(_TWO_DROPS) or {}).get('zip') == '30075')
_hp2 = tempfile.mkdtemp()
rp2 = run(_press_on_first_read(_hp2, ''), extra_argv=['--no-parallel'], seconds=5.0,
          handoff=_hp2, whole_text=_TWO_DROPS)
_as2 = assembled(rp2['sightings'], _held())
eq('a planner with two dropoffs is answered with both, once, and the reason',
   [([s['name'] for s in p[0]], _as2['byAt'].get(str(p[1].get('at'))))
    for p in rp2['planners']],
   [(['Pat Q.', 'Lee M.'], 'dropoffs')])
eq('...and the order in the car is given neither, and is not told "not read" '
   'over the stops either', (rp2['dropoffs'], _as2['dropoffs']), ([], []))
eq('...and the window shuts on the answer, not twelve seconds later (%r)'
   % rp2['wholes'], sum(rp2['wholes']), 1)
# ...and the reads the window was forcing stop with it. The whole-screen reads
# would stop on their own, because the press is no longer outstanding; the
# forced beat would not, and the rig would go on photographing a planner it has
# answered every half second for the rest of the twelve. Measured over this
# run's five seconds: 4 reads with the window shut on the answer, 13 without.
ok_('...and the reads it was forcing stop with it (%d reads in five seconds)'
    % rp2['calls'], rp2['calls'] <= 6)

# Nobody pressed: the card box is looking straight at a planner. Read only
# under a press, which is what the owner asked for and the existing rule for
# a loosened address — so neither the stops nor their dropoff go anywhere.
rp3 = run(lambda n, k: _ONE_DROP, extra_argv=['--no-parallel'], seconds=4.0,
          handoff=tempfile.mkdtemp())
ok_('the premise: the card box read the planner, unpressed (%d reads)' % rp3['calls'],
    rp3['calls'] >= 1 and not any(rp3['wholes']))
eq('a planner nobody pressed for is not answered', rp3['planners'], [])
eq('...and gives the order in the car nothing', rp3['dropoffs'], [])
# ...including the address find_address WOULD take off it. That planner has no
# ZIP, so find_address had nothing to give either way; this one has one, on the
# second customer's door, and an unprompted read of a screen with a ZIP address
# and no payout on it is otherwise sent as a sighting — which the server files
# on the card being screened, or on an order in the car that has no end. On a
# planner the planner's own rule decides, asked or not: see `found` in digest().
rp5 = run(lambda n, k: _TWO_DROPS, extra_argv=['--no-parallel'], seconds=4.0,
          handoff=tempfile.mkdtemp())
ok_('the premise: the card box read the two-dropoff planner, unpressed (%d reads)'
    % rp5['calls'], rp5['calls'] >= 1 and not any(rp5['wholes']))
eq('a planner nobody pressed for gives no address, not even the one find_address '
   'would take off it', [((d[0] or {}).get('line'), d[1].get('asked'))
                         for d in rp5['dropoffs']], [])

# --- DoorDash's place popup, read while its card is screened -----------------
#
# The driver taps a stop on a DoorDash card before deciding, and the phone
# opens a sheet over the bottom of the screen: "Pickup from", the store, its
# street and town, "Directions" (offer_parser.place_popup has the five reads of
# it on file). The card box is the bottom of the screen, so the card-box read
# the loop already makes is the one that sees it. Said on its own line, once
# per card and address, stamped with when its frame was taken — and a
# customer's never as a dropoff line, which would file it onto an order in the
# car. Made-up store, street and door.
_DD_CARD = ('$7.75\n3 stops (7.8 mi) · 30 min\n@ Fable Bagel Co\n'
            '123 Lantern Grove Road Northwest, Sm...\n& Customer dropoff')
_STORE_POPUP = ('<q Pickup from\nFable Bagel Co %\nGy 123 Lantern Grove Rd NW\n'
                'Smyrna, GA 30080, USA\nDirections')
_CUSTOMER_POPUP = ('Customer dropoff\n412 Wrenfield Ct NE\nMarietta, GA 30062, USA\n'
                   'Directions')
_t0 = time.time() * 1000
rpop = run(lambda n, k: _DD_CARD if n <= 2 else _STORE_POPUP,
           extra_argv=['--no-parallel'], seconds=5.0, handoff=tempfile.mkdtemp())
_t1 = time.time() * 1000
ok_('the premise: the card was announced and the popup read more than once (%d reads)'
    % rpop['calls'], rpop['announced'] and rpop['calls'] >= 4)
eq('a store popup read off the card box is said once, on its own line, with its '
   'role, the store and the address',
   [(p['role'], p['name'], p['line']) for p, _ in rpop['popups']],
   [('pickup', 'Fable Bagel Co', '123 Lantern Grove Rd NW, Smyrna, GA 30080')])
ok_("...stamped with its frame's own clock, inside the run (%r)"
    % [a for _, a in rpop['popups']],
    rpop['popups'] and all(isinstance(a, int) and _t0 <= a <= _t1 for _, a in rpop['popups']))
eq('...and the log names the role and not the place',
   [l for l in rpop['logs'] if l.startswith('place popup')], ["place popup read: the store's address"])
rcus = run(lambda n, k: _DD_CARD if n <= 2 else _CUSTOMER_POPUP,
           extra_argv=['--no-parallel'], seconds=5.0, handoff=tempfile.mkdtemp())
ok_('the premise: a customer popup is an address under a Dropoff label, which a '
    'dropoff line would carry', OP.address_under_dropoff(_CUSTOMER_POPUP))
eq("a customer's popup goes out on its own line and never as a dropoff line",
   ([(p['role'], p['line']) for p, _ in rcus['popups']], rcus['dropoffs']),
   ([('dropoff', '412 Wrenfield Ct NE, Marietta, GA 30062')], []))

# --- a pickup's address is never the order's destination ---------------------
#
# Off a shift: "✓ Took $28.08" pressed with the Trip Planner up — two pickups,
# each "Address / <street> NW, / Kennesaw, GA <ZIP>", over a closed "Dropoff •
# 1 order" naming nobody's door. Nobody pressed ⌖, and the order in the car
# came out holding `dropoff: 'Kennesaw, GA 30144', dropoffScanned: true` — the
# first restaurant's town. The card box had caught the list scrolling, its top
# edge between that pickup's street and town lines, and no stop header in the
# read matched PLANNER_STOP, so nothing called it a planner and find_address
# took the town line as the last address on the screen.
#
# The texts below are that screen's shapes with every address made up. The
# read that did it was not kept, so which way its headers failed is not known;
# here they are simply gone — the crop as it cut the list with no header read
# under it, and the pickup block with its header down to the word "Pickup",
# the count lost, which PLANNER_STOP does not take for a stop.
_PICKUP_CUT = ('Kennesaw, GA 30144\nView details\nFable Grill\n'
               'Expected by 5:54 PM\nPat Q.\nExpected by 6:37 PM\n'
               'Waybill\nStop New Requests')
_PICKUP_BLOCK = ('Pickup\nFable Grill\nExpected by 5:46 PM\nAddress\n'
                 '4100 Fable Mill Pkwy NW,\nKennesaw, GA 30144\nView details\n'
                 'Stop New Requests')
for _name, _t in (('the cut list', _PICKUP_CUT), ('the pickup block', _PICKUP_BLOCK)):
    ok_('the premise: %s is no planner to the reader, has no payout, and '
        'find_address takes the pickup\'s ZIP off it' % _name,
        OP.find_planner(_t) is None and OP.parse(_t)['pay'] is None
        and not OP.parse(_t)['places']
        and (OP.find_address(_t) or {}).get('zip') == '30144')
# A card fragment first, so the resample window goes on reading every half
# second over the planner that replaces it — a still screen otherwise gets one
# read and the health line, which speaks only after reads, never comes round.
rpk1 = run(lambda n, k: FRAG if n == 1 else _PICKUP_CUT, extra_argv=['--no-parallel'],
           seconds=6.0, handoff=tempfile.mkdtemp(), health_every=0.2)
ok_('the premise: the card box read the cut planner, unpressed (%d reads)'
    % rpk1['calls'], rpk1['calls'] >= 3 and not any(rpk1['wholes']))
eq('an address under no Dropoff label, unprompted, is not sent as the order\'s '
   'destination', [((d[0] or {}).get('line'), d[1].get('asked'))
                   for d in rpk1['dropoffs']], [])
ok_('...and the refusal is said on the health line, not silent',
    any(l.startswith('health') and 'refused for not being under a Dropoff label' in l
        for l in rpk1['logs']))
ok_('...and carried on the seen row the journal keeps (%r)'
    % [x.get('addressNotDropoff') for x in rpk1['rows'] if x.get('kind') == 'seen'],
    any((x.get('addressNotDropoff') or 0) >= 1
        for x in rpk1['rows'] if x.get('kind') == 'seen'))
rpk2 = run(lambda n, k: _PICKUP_BLOCK, extra_argv=['--no-parallel'], seconds=4.0,
           handoff=tempfile.mkdtemp())
ok_('the premise: the card box read the pickup block, unpressed (%d reads)'
    % rpk2['calls'], rpk2['calls'] >= 1)
eq('an address under a Pickup label, unprompted, is not sent as the order\'s '
   'destination', [((d[0] or {}).get('line'), d[1].get('asked'))
                   for d in rpk2['dropoffs']], [])
# ...and not under a press either. ⌖ says "this screen is the destination"; the
# screen saying "Pickup" over the address is the screen disagreeing, and a
# restaurant filed `asked: true` overrules whatever the card said.
_hpk3 = tempfile.mkdtemp()
rpk3 = run(_press_on_first_read(_hpk3, ''), extra_argv=['--no-parallel'], seconds=4.0,
           handoff=_hpk3, dropoff_window=1.0, whole_text=_PICKUP_BLOCK)
ok_('the premise: the press read the pickup block whole', any(rpk3['wholes']))
eq('an address under a Pickup label answers a press with nothing, not with the '
   'restaurant', [((d[0] or {}).get('line'), d[1].get('asked'))
                  for d in rpk3['dropoffs']], [(None, True)])
# ...and the sighting of that read says what the screen said: an address under
# a Pickup label, typed a pickup and nothing else.
# Every whole read the window forced is a sighting of its own, so each is
# asked, and at least one has to be there.
_pk_seen = [[(s['kind'], s['label'], s['line']) for s in x['stops']]
            for x in rpk3['sightings'] if x['whole']]
ok_('a sighting types an address under a Pickup label as a pickup only (%r)' % _pk_seen,
    bool(_pk_seen) and all(
        v == [('pickup', 'pickup', '4100 Fable Mill Pkwy NW, Kennesaw, GA 30144')]
        for v in _pk_seen))
# ...nor a planner whose headers did not read, pressed: the cut list again.
_hpk4 = tempfile.mkdtemp()
rpk4 = run(_press_on_first_read(_hpk4, ''), extra_argv=['--no-parallel'], seconds=4.0,
           handoff=_hpk4, dropoff_window=1.0, whole_text=_PICKUP_CUT)
eq('an unlabelled address on a screen with the planner\'s furniture answers a '
   'press with nothing', [((d[0] or {}).get('line'), d[1].get('asked'))
                          for d in rpk4['dropoffs']], [(None, True)])
# Each arm of the rule on its own, with the others out of the way: a Pickup
# label with no planner furniture under a press, and an unlabelled address
# with no furniture unprompted (refused) and pressed (answered, as it always
# was — a press over a plain navigation screen needs no label).
_PICKING = 'Picking up\n12 Fable St, Acworth, GA 30101\n4 min Start'
_BARE_CUT = 'Kennesaw, GA 30144\nView details\nFable Grill'
_BARE_NAV = '1234 Made Up Ln, Acworth, GA 30101 12 min Start'
ok_('the premise: none of the three carries the planner\'s furniture, a stop '
    'header or a payout',
    not any(OP.planner_furniture(t) or OP.parse(t)['pay'] is not None
            or OP.parse(t)['places'] or OP.find_planner(t) is not None
            for t in (_PICKING, _BARE_CUT, _BARE_NAV)))
_hpk6 = tempfile.mkdtemp()
rpk6 = run(_press_on_first_read(_hpk6, ''), extra_argv=['--no-parallel'], seconds=4.0,
           handoff=_hpk6, dropoff_window=1.0, whole_text=_PICKING)
eq('a press over an address under a Pickup label, no planner in sight, is '
   'answered with nothing', [((d[0] or {}).get('line'), d[1].get('asked'))
                             for d in rpk6['dropoffs']], [(None, True)])
rpk7 = run(lambda n, k: _BARE_CUT, extra_argv=['--no-parallel'], seconds=4.0,
           handoff=tempfile.mkdtemp())
eq('an unlabelled town line nobody asked for, no planner furniture, is not sent',
   [((d[0] or {}).get('line'), d[1].get('asked')) for d in rpk7['dropoffs']], [])
_hpk8 = tempfile.mkdtemp()
rpk8 = run(_press_on_first_read(_hpk8, ''), extra_argv=['--no-parallel'], seconds=4.0,
           handoff=_hpk8, dropoff_window=1.0, whole_text=_BARE_NAV)
eq('...while a press over an unlabelled navigation screen still gets its address',
   [((d[0] or {}).get('line'), d[1].get('asked')) for d in rpk8['dropoffs']],
   [('1234 Made Up Ln, Acworth, GA 30101', True)])
# The other side: the rule is the LABEL, not "a pickup is anywhere on the
# screen". A screen with a Pickup label above the Dropoff one gives the
# dropoff's address, unprompted — which is what a guard that refused every
# screen mentioning a pickup would lose. No merchant under that Pickup: one
# would make the screen an offer to the payout guard's second arm, which
# refuses it for its own reason before this rule is asked.
_BOTH_ENDS = ('Pickup - 5:46 PM\n'
              'Dropoff\n34 Made Up Rd, Acworth, GA 30102\n12 min Start')
ok_('the premise: that screen names a pickup above the dropoff and is no offer '
    'and no planner',
    OP.parse(_BOTH_ENDS)['places'] == [] and OP.parse(_BOTH_ENDS)['pay'] is None
    and OP.find_planner(_BOTH_ENDS) is None
    and 'Pickup' in _BOTH_ENDS.split('Dropoff')[0])
rpk5 = run(lambda n, k: _BOTH_ENDS, extra_argv=['--no-parallel'], seconds=4.0,
           handoff=tempfile.mkdtemp())
eq('an address under a Dropoff label below a pickup is still the destination, '
   'unprompted', [((d[0] or {}).get('line'), d[1].get('asked'))
                  for d in rpk5['dropoffs']], [('34 Made Up Rd, Acworth, GA 30102', False)])
eq('...and sent as label-proven, so the server may file it over the card\'s own end',
   [d[1].get('labelled') for d in rpk5['dropoffs']], [True])

# --- the Trip Planner, read without a press while an order is held ----------
#
# Asked for after a shift: with "✓ Took" pressed, the rig reads Uber's Trip
# Planner on its own whenever it is on the phone, the same whole-screen read ⌖
# makes, at most once every SCREEN_AUTO_EVERY seconds. The card box on the rig
# is the bottom half of the screen, so it sees the planner's stop grammar and
# never its title; the whole-screen read is where the title is checked.
#
# "An order is held" is server.js's to say. It writes `.holding.json` with the
# moment its holding() stops answering yes, and these runs write that file
# into their own handoff directory the way the server would. Every address
# below is invented.
def _hold(handoff, until_s):
    """Leave the web side's "an order is in the car until <until_s>" note."""
    was = os.environ.get(HO.ENV_DIR)
    os.environ[HO.ENV_DIR] = handoff
    try:
        with open(HO.path(HO.HOLDING), 'w') as fh:
            json.dump({'until': int(until_s * 1000)}, fh)
    finally:
        if was is None:
            os.environ.pop(HO.ENV_DIR, None)
        else:
            os.environ[HO.ENV_DIR] = was


_AUTO_BOX = ('Address\n1625 Heron Blvd NW, Kennesaw, GA\n30152\nView details\n'
             'Dropoff • 1 order\nStop New Requests')
_AUTO_WHOLE = next(c['text'] for c in json.load(open(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'tests', 'fixtures', 'cases.json'), encoding='utf-8'))['planner']
    if c['name'] == 'two pickups over a dropoff whose address is below the screen')
ok_('the premise: the card box shows the planner\'s grammar and not its title, '
    'and the whole screen shows both',
    OP.find_planner(_AUTO_BOX) is not None and not OP.planner_titled(_AUTO_BOX)
    and OP.planner_titled(_AUTO_WHOLE) and len(OP.find_planner(_AUTO_WHOLE)) == 3)

# A card fragment first, so the resample window keeps the card box reading
# every half second for four seconds over the planner that follows — enough
# reads to show the read is asked for once and not on every one of them.
_ha1, _pa1 = tempfile.mkdtemp(), []
_hold(_ha1, time.time() + 3600)
ra1 = run(lambda n, k: FRAG if n == 1 else _AUTO_BOX, extra_argv=['--no-parallel'],
          seconds=6.0, handoff=_ha1, whole_text=_AUTO_WHOLE, planners=_pa1)
ok_('the premise: the card box read the planner several times, unpressed (%d reads)'
    % ra1['calls'], ra1['calls'] >= 4)
eq('with an order held, the planner in the card box gets one whole-screen read, '
   'unpressed (%r)' % ra1['wholes'], sum(ra1['wholes']), 1)
eq('...and its stops go out as the planner, said to be unasked',
   [([s['kind'] for s in p[0]], p[1].get('asked')) for p in _pa1],
   [(['pickup', 'pickup', 'dropoff'], False)])
eq('...with each pickup\'s own address and none for the dropoff',
   [[s['line'] for s in p[0]] for p in _pa1],
   [['1200 Fable Mill Pkwy NW, Kennesaw, GA 30144',
     '1625 Heron Blvd NW, Kennesaw, GA 30152', None]])
eq('...and gives the order in the car no destination off it',
   ra1['dropoffs'], [])

# With nothing held: no whole-screen read, nothing said. This is what makes it
# not an accept detector — the driver has to have marked the order taken.
_ha2, _pa2 = tempfile.mkdtemp(), []
ra2 = run(lambda n, k: FRAG if n == 1 else _AUTO_BOX, extra_argv=['--no-parallel'],
          seconds=4.0, handoff=_ha2, whole_text=_AUTO_WHOLE, planners=_pa2)
eq('with no order held, the planner in the card box is not read whole',
   (sum(ra2['wholes']), _pa2), (0, []))
# ...nor with a hold that has run out: the note says until when, and a server
# that died mid-delivery must not leave the rig reading planners all shift.
_ha3, _pa3 = tempfile.mkdtemp(), []
_hold(_ha3, time.time() - 60)
ra3 = run(lambda n, k: FRAG if n == 1 else _AUTO_BOX, extra_argv=['--no-parallel'],
          seconds=4.0, handoff=_ha3, whole_text=_AUTO_WHOLE, planners=_pa3)
eq('...nor with a hold whose time ran out', (sum(ra3['wholes']), _pa3), (0, []))

# The whole screen without the title is not answered as the planner: the stop
# grammar in a box, under no title, is not evidence the screen is the planner.
_ha4, _pa4 = tempfile.mkdtemp(), []
_hold(_ha4, time.time() + 3600)
_UNTITLED = _AUTO_WHOLE.replace('Trip Planner\n', '', 1)
ok_('the premise: that whole screen is the planner without its title',
    OP.find_planner(_UNTITLED) is not None and not OP.planner_titled(_UNTITLED))
ra4 = run(lambda n, k: FRAG if n == 1 else _AUTO_BOX, extra_argv=['--no-parallel'],
          seconds=4.0, handoff=_ha4, whole_text=_UNTITLED, planners=_pa4)
ok_('the premise: it was read whole (%r)' % ra4['wholes'], sum(ra4['wholes']) == 1)
eq('a whole screen with no "Trip Planner" title is not sent as the planner', _pa4, [])

# ...and a whole-screen read that found no planner gives the address only when
# the screen printed it under a Dropoff label in its own block — the driver's
# ask, "set the destination whenever the screen shows an address directly under
# a Dropoff label". Before that ask this read sent nothing. It now goes on the
# read's SIGHTING, typed a dropoff, and the assembler files it as a navigation
# destination (rank `nav`); the read sends no dropoff line of its own, so one
# screen is never filed down two roads. DoorDash's layout, typed 'unknown'.
_ha5, _pa5 = tempfile.mkdtemp(), []
_hold(_ha5, time.time() + 3600)
_WHOLE_NAV = 'Dropoff\n77 Made Up Ct, Acworth, GA 30101\n12 min Start'
ok_('the premise: that whole screen has a labelled address and no stop header',
    OP.find_planner(_WHOLE_NAV) is None and OP.address_stop(_WHOLE_NAV) == 'dropoff')
ra5 = run(lambda n, k: FRAG if n == 1 else _AUTO_BOX, extra_argv=['--no-parallel'],
          seconds=4.0, handoff=_ha5, whole_text=_WHOLE_NAV, planners=_pa5)
ok_('the premise: it was read whole (%r)' % ra5['wholes'], sum(ra5['wholes']) == 1)
eq('an unpressed whole-screen read files an address under a Dropoff label off its '
   'sighting, as a navigation destination',
   [(d['line'], d['asked'], d['labelled'], d['from'], d['kept'])
    for d in assembled([x for x in ra5['sightings'] if x['whole']], _held())['dropoffs']],
   [('77 Made Up Ct, Acworth, GA 30101', False, True, 'nav', True)])
eq('...and sends no dropoff line for it', ra5['dropoffs'], [])
# ...and nothing off the same whole screen with no label over the address: the
# label is what makes it the destination, not the whole-screen read.
_ha5b = tempfile.mkdtemp()
_hold(_ha5b, time.time() + 3600)
_WHOLE_BARE = '77 Made Up Ct, Acworth, GA 30101\n12 min Start'
ra5b = run(lambda n, k: FRAG if n == 1 else _AUTO_BOX, extra_argv=['--no-parallel'],
           seconds=4.0, handoff=_ha5b, whole_text=_WHOLE_BARE)
ok_('the premise: it was read whole, and its sighting carries the address (%r)'
    % ra5b['wholes'], sum(ra5b['wholes']) == 1
    and [s['line'] for x in ra5b['sightings'] if x['whole'] for s in x['stops']]
    == ['77 Made Up Ct, Acworth, GA 30101'])
eq('an unpressed whole-screen read files no address under no label',
   (ra5b['dropoffs'],
    assembled([x for x in ra5b['sightings'] if x['whole']], _held())['dropoffs']), ([], []))
# ...nor one under a Dropoff label that is not its own: the label's address
# is the first, and the last one on the screen — the one find_address takes —
# sits in a block whose header did not print. That address passes the
# unprompted gate (the nearest label above it says dropoff); only
# OP.address_under_dropoff, asked where sighting_stops types it, refuses it.
# With that test taken out, no check failed: the bare screen above never
# reaches it.
_ha5c = tempfile.mkdtemp()
_hold(_ha5c, time.time() + 3600)
_WHOLE_SECOND = ('Dropoff\n34 Made Up Rd, Acworth, GA 30102\nView details\n'
                 '56 Other Made Up Rd, Acworth, GA 30101\n12 min Start')
ok_('the premise: the last address on that screen is under a Dropoff label, and not '
    'in its block', OP.find_planner(_WHOLE_SECOND) is None
    and OP.address_stop(_WHOLE_SECOND) == 'dropoff'
    and not OP.address_under_dropoff(_WHOLE_SECOND))
ra5c = run(lambda n, k: FRAG if n == 1 else _AUTO_BOX, extra_argv=['--no-parallel'],
           seconds=4.0, handoff=_ha5c, whole_text=_WHOLE_SECOND)
ok_('the premise: it was read whole (%r)' % ra5c['wholes'], sum(ra5c['wholes']) == 1)
eq('an unpressed whole-screen read files no second address under another\'s label',
   (ra5c['dropoffs'],
    assembled([x for x in ra5c['sightings'] if x['whole']], _held())['dropoffs']), ([], []))

# --- the navigation screen, read without a press while an order is held -------
#
# The driver's ask, after the planner: read the navigation and "Deliver to"
# screens on their own too. The card box sees Uber's bottom sheet — on the 12
# Oct shift "Deliver to <name>" under the bar, never an address — so the
# navigation screen in the box asks for the whole-screen read, and the
# assembler decides off its sighting. The whole screen here prints an address
# straight under "Deliver to", which the shift never showed (the corpus case
# says so); the collapsed bar is the shift's own layout, with an invented name.
_NAV_CASES = {c['name']: c['text'] for c in json.load(open(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'tests', 'fixtures', 'cases.json'), encoding='utf-8'))['navStops']}
_NAV_BOX = _NAV_CASES["Uber's collapsed bar: 'Deliver to' a name, and no address"]
_NAV_WHOLE = _NAV_CASES["not seen on 12 Oct: Uber's navigation with an address straight "
                        "under 'Deliver to'"]
ok_('the premise: the card box is Uber\'s navigation with no address, and the whole '
    'screen has one under "Deliver to" and no offer',
    OP.screen_type(_NAV_BOX)['screen'] == 'uber.nav' and OP.find_address(_NAV_BOX) is None
    and OP.address_under_dropoff(_NAV_WHOLE) and OP.parse(_NAV_WHOLE)['places'] == []
    and not OP.planner_furniture(_NAV_BOX))
_hn1 = tempfile.mkdtemp()
_hold(_hn1, time.time() + 3600)
rn1 = run(lambda n, k: FRAG if n == 1 else _NAV_BOX, extra_argv=['--no-parallel'],
          seconds=6.0, handoff=_hn1, whole_text=_NAV_WHOLE)
ok_('the premise: the card box read the navigation screen several times, unpressed '
    '(%d reads)' % rn1['calls'], rn1['calls'] >= 4)
eq('with an order held, a navigation screen in the card box gets one whole-screen read, '
   'unpressed (%r)' % rn1['wholes'], sum(rn1['wholes']), 1)
eq('...and its address under "Deliver to" is the held order\'s destination with no press',
   [(d['line'], d['asked'], d['from'], d['kept'])
    for d in assembled([x for x in rn1['sightings'] if x['whole']], _held())['dropoffs']],
   [('2950 Kestrel Dr, Woodstock, GA 30188', False, 'nav', True)])
eq('...off the sighting alone: no dropoff line for it', rn1['dropoffs'], [])
_hn2 = tempfile.mkdtemp()
rn2 = run(lambda n, k: FRAG if n == 1 else _NAV_BOX, extra_argv=['--no-parallel'],
          seconds=4.0, handoff=_hn2, whole_text=_NAV_WHOLE)
eq('with no order held, a navigation screen in the card box is not read whole',
   sum(rn2['wholes']), 0)

# ONE clock for every kind: a planner in the box, then the navigation screen,
# each of which would ask on its own. The owner's figure is one unpressed read
# every ~10 s, and it is one phone in front of one Pi whichever screen is up.
_hn3 = tempfile.mkdtemp()
_hold(_hn3, time.time() + 3600)
rn3 = run(lambda n, k: FRAG if n == 1 else _AUTO_BOX if n == 2 else _NAV_BOX,
          extra_argv=['--no-parallel'], seconds=6.0, handoff=_hn3, whole_text=_NAV_WHOLE)
_after = [w for i, w in enumerate(rn3['wholes']) if i >= 2]
ok_('the premise: card-box reads of the navigation screen came after the planner\'s '
    'whole-screen read (%r)' % rn3['wholes'],
    rn3['wholes'][:3] == [False, False, True] and _after.count(False) >= 2)
eq('the auto reads keep one every 10 s across kinds (%r)' % rn3['wholes'],
   sum(rn3['wholes']), 1)

# ...and the opened navigation sheet: the customer's name, the street, the town
# and "Dropoff type" under them, which the owner decided (14 Oct) is the
# dropoff while an order is held. The 12 Oct layout, under the bar that parse()
# takes for a card's leg; invented name and street.
_SHEET = next(c['text'] for c in json.load(open(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'tests', 'fixtures', 'cases.json'), encoding='utf-8'))['sheets']
    if c['name'].startswith('...under the bar'))
_hn4 = tempfile.mkdtemp()
_hold(_hn4, time.time() + 3600)
rn4 = run(lambda n, k: FRAG if n == 1 else _SHEET, extra_argv=['--no-parallel'],
          seconds=4.0, handoff=_hn4, whole_text=_SHEET)
ok_('the premise: the sheet was read whole (%r)' % rn4['wholes'], sum(rn4['wholes']) == 1)
eq('an opened navigation sheet\'s address over "Dropoff type" is the held order\'s '
   'destination with no press',
   [(d['line'], d['asked'], d['from'], d['kept'])
    for d in assembled([x for x in rn4['sightings'] if x['whole']], _held())['dropoffs']],
   [('4416 Wrenfield Dr NW, Kennesaw', False, 'nav', True)])
eq('...and no dropoff line is sent for it, off the card box or the whole screen',
   rn4['dropoffs'], [])

# ...and the CUSTOMER SHEET, the same sheet pulled all the way up (17 Oct): the
# place between the name and the street, "Business / Building name" and its
# value over "Dropoff type", and the order list under it, whose "Drop off 1
# order" the planner parser took for a stop. On the shift a ⌖ press over it
# was answered by that "planner" of one dropoff with no address, and the
# address on the glass was never filed. The rig's whole-screen read and card-
# box read of it, with every name, place, street and order code invented.
_CSHEETS = {c['name']: c['text'] for c in json.load(open(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'tests', 'fixtures', 'cases.json'), encoding='utf-8'))['sheets']}
_CSHEET = next(t for n, t in _CSHEETS.items()
               if n.startswith('Measured: the customer sheet pulled all the way up'))
_CSHEET_BOX = _CSHEET[_CSHEET.index('Business / Building name'):]
ok_('the premise: the card box holds the sheet\'s lower half, the label to the order list, '
    'and asks for a whole-screen read; the whole screen reads as the sheet and no planner',
    SP.auto_read_for(_CSHEET_BOX) is not None and OP.sheet_dropoff(_CSHEET_BOX) is None
    and OP.find_planner(_CSHEET) is None and OP.sheet_dropoff(_CSHEET) is not None)
_hc1, _pc1 = tempfile.mkdtemp(), []
rc1 = run(_press_on_first_read(_hc1, ''), extra_argv=['--no-parallel'], seconds=5.0,
          handoff=_hc1, whole_text=_CSHEET, planners=_pc1)
eq('⌖ over Uber\'s customer sheet is answered with its address, asked, once',
   [((d[0] or {}).get('line'), d[1].get('asked')) for d in rc1['dropoffs']],
   [('283 Quillon St NW, Smyrna', True)])
eq('...and not with a planner read off its "Drop off 1 order"', _pc1, [])
eq('...its sighting the sheet\'s one dropoff, its place and "Expected by" with it',
   [[(s['kind'], s['label'], s['line'], s['place'], s['expectedBy']) for s in x['stops']]
    for x in rc1['sightings'] if x['whole']][:1],
   [[('dropoff', 'dropoff type', '283 Quillon St NW, Smyrna', 'Fable Parking Deck', 30)]])
_hc2 = tempfile.mkdtemp()
_hold(_hc2, time.time() + 3600)
rc2 = run(lambda n, k: FRAG if n == 1 else _CSHEET_BOX, extra_argv=['--no-parallel'],
          seconds=4.0, handoff=_hc2, whole_text=_CSHEET)
ok_('the premise: the customer sheet was read whole, unpressed (%r)' % rc2['wholes'],
    sum(rc2['wholes']) == 1)
eq('...and with an order held its address is the held order\'s destination with no press',
   [(d['line'], d['asked'], d['from'], d['kept'])
    for d in assembled([x for x in rc2['sightings'] if x['whole']], _held())['dropoffs']],
   [('283 Quillon St NW, Smyrna', False, 'nav', True)])

# ...and the planner's own one dropoff is sent, label-proven, on the list that
# would give it to a press: both ends in view, one dropoff, its street and town
# read, under its own "Dropoff" header. It used to stay the press's to file for
# fear of a planner still up from the trip before; server.js now answers that
# (filed only when newer than the Took, and never as one of the hold's own
# planner pickups), and the driver asked for it filed.
_ha6, _pa6 = tempfile.mkdtemp(), []
_hold(_ha6, time.time() + 3600)
ok_('the premise: under a press that planner gives its dropoff as the destination',
    [d['line'] for d in assembled(rp1['sightings'])['dropoffs']]
    == ['4821 Kestrel Dr, Marietta'] and OP.planner_titled(_ONE_DROP_WHOLE))
ra6 = run(lambda n, k: FRAG if n == 1 else _ONE_DROP, extra_argv=['--no-parallel'],
          seconds=4.0, handoff=_ha6, whole_text=_ONE_DROP_WHOLE, planners=_pa6)
eq('an unpressed planner read sends the stops, unasked',
   [([s['line'] for s in p[0]], p[1].get('asked')) for p in _pa6],
   [(['4821 Kestrel Dr, Marietta'], False)])
eq('...and its one dropoff as the order\'s destination, label-proven',
   [(d['line'], d['asked'], d['labelled'], d['from'], d['kept'])
    for d in assembled([x for x in ra6['sightings'] if x['whole']], _held())['dropoffs']],
   [('4821 Kestrel Dr, Marietta', False, True, 'planner', True)])
eq('...off the sighting alone: the scanner sends no dropoff line for it',
   ra6['dropoffs'], [])

# ...and so is a dropoff at a hotel: the hotel's name, the town bare, then the
# street and town with no ZIP. On shift the card box read that block with its
# header lost ("rept hk VEU"), the whole-screen read listed the stop with no
# street, town or line, and the order's corner stayed its destination with GPS
# arrival never armed. The shared case's text, with "Waybill" under the list so
# both ends are in view — on the shift's screen it was not (see the case).
_HOTEL = next(c['text'] for c in json.load(open(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'tests', 'fixtures', 'cases.json'), encoding='utf-8'))['planner']
    if c['name'].startswith('a dropoff at a hotel'))
_HOTEL_WHOLE = _HOTEL.replace('View details\noS CC Q', 'View details\nWaybill\noS CC Q')
_HOTEL_BOX = _HOTEL[_HOTEL.index('Dropoff'):].replace('Dropoff • 1 order', 'rept hk VEU')
_ha7, _pa7 = tempfile.mkdtemp(), []
_hold(_ha7, time.time() + 3600)
ok_('the premise: the box read of the hotel dropoff has no stop header but the '
    'planner\'s furniture, and the whole screen is bounded',
    OP.find_planner(_HOTEL_BOX) is None and OP.planner_furniture(_HOTEL_BOX)
    and OP.planner_bounded(_HOTEL_WHOLE) and OP.planner_titled(_HOTEL_WHOLE))
ra7 = run(lambda n, k: FRAG if n == 1 else _HOTEL_BOX, extra_argv=['--no-parallel'],
          seconds=4.0, handoff=_ha7, whole_text=_HOTEL_WHOLE, planners=_pa7)
_as7 = assembled([x for x in ra7['sightings'] if x['whole']], _held())
eq('a planner dropoff at a hotel, no ZIP, is filed as the held order\'s destination: '
   'its street and town, label-proven',
   [(d['street'], d['city'], d['state'], d['zip'], d['asked'], d['labelled'])
    for d in _as7['dropoffs']],
   [('1180 Wrenfield Rd NW', 'Kennesaw', 'GA', None, False, True)])
eq('...said as filed on any held card, the list being seen whole',
   [(d['singleCardOnly'], d['kept']) for d in _as7['dropoffs']], [(False, True)])
# ...and the shift's own screen, "Waybill" under the bar: the lone dropoff still
# goes out, marked for server.js to file only onto a single-trip card.
_ha8 = tempfile.mkdtemp()
_hold(_ha8, time.time() + 3600)
ra8 = run(lambda n, k: FRAG if n == 1 else _HOTEL_BOX, extra_argv=['--no-parallel'],
          seconds=4.0, handoff=_ha8, whole_text=_HOTEL)
_seen8 = [x for x in ra8['sightings'] if x['whole']]
eq('an unbounded planner\'s lone one-order dropoff is sent, unasked, label-proven '
   'and marked single-card-only',
   [(d['line'], d['asked'], d['labelled'], d['singleCardOnly'], d['kept'])
    for d in assembled(_seen8, _held({'legs': 1, 'multiOrder': False}))['dropoffs']],
   [('1180 Wrenfield Rd NW, Kennesaw', False, True, True, True)])
eq('...and not filed onto a held card of two orders',
   [d['kept'] for d in assembled(_seen8, _held())['dropoffs']], [False])

# `dropoff_said` is forgotten when the order in the car changes, and only then.
# It was never cleared, so an address the server refused for the order before
# — a screen read before the Took — was never volunteered again for the order
# it was about. server.js's note now names the order (`holds`); here it names
# one, then another a few reads in, over one labelled navigation screen that
# never moves. Invented address.
_hds = tempfile.mkdtemp()
_NAV_SAME = 'Dropoff\n61 Saddlebrook Ln, Acworth, GA 30101\n12 min Start'


def _note(holds):
    was = os.environ.get(HO.ENV_DIR)
    os.environ[HO.ENV_DIR] = _hds
    try:
        with open(HO.path(HO.HOLDING), 'w') as fh:
            json.dump({'until': int((time.time() + 3600) * 1000), 'holds': holds}, fh)
    finally:
        if was is None:
            os.environ.pop(HO.ENV_DIR, None)
        else:
            os.environ[HO.ENV_DIR] = was


_note('o-first@1')
_switched = []


def _switch_hold(rows, announced, calls):
    if calls >= 4 and not _switched:
        _switched.append(calls)
        _note('o-second@2')
    return False


rds = run(lambda n, k: FRAG if n == 1 else _NAV_SAME, extra_argv=['--no-parallel'],
          seconds=5.0, handoff=_hds, until=_switch_hold)
ok_('the premise: the order changed part-way through (%r, %d reads)'
    % (_switched, rds['calls']), _switched and rds['calls'] > _switched[0] + 1)
eq('an unprompted address is said once per order in the car: again for the next one',
   [((d[0] or {}).get('line'), d[1].get('asked')) for d in rds['dropoffs']],
   [('61 Saddlebrook Ln, Acworth, GA 30101', False)] * 2)


# ...and since server.js keeps the orders in the car as a list (Stage 4), the
# note names them as one: `holds: [ids]`. One signature for the list, so a
# second order taken — or one of two put down — is a change of order like any
# other, and a note from a server before the list (one name) reads as it did.
def _sig_now():
    was = os.environ.get(HO.ENV_DIR)
    os.environ[HO.ENV_DIR] = _hds
    try:
        return SP.held_signature()
    finally:
        if was is None:
            os.environ.pop(HO.ENV_DIR, None)
        else:
            os.environ[HO.ENV_DIR] = was


_note(['o-a@1'])
_sig_one = _sig_now()
_note(['o-a@1', 'o-b@2'])
_sig_two = _sig_now()
_note('o-a@1')
eq('the held orders\' note is one signature, list or name, and a second order changes it',
   (_sig_one, _sig_two, _sig_now()), ('o-a@1', 'o-a@1 o-b@2', 'o-a@1'))

# Whether the journal may keep the stops — names and front doors — is the
# scanner's to say, because the server does not read its settings: not with
# "keepPlaces": false, and not with no journal at all.
_hpk, _plk = tempfile.mkdtemp(), []
run(_press_on_first_read(_hpk, ''), extra_argv=['--no-parallel'], seconds=4.0,
    handoff=_hpk, whole_text=_ONE_DROP_WHOLE, planners=_plk,
    config_extra={'settings': {'target': 25, 'band': 15, 'costPerMile': 0.30,
                               'keepPlaces': False}})
eq('with "keepPlaces": false the planner line says the journal may not keep the '
   'stops', [p[1].get('keep') for p in _plk], [False])
_hpn, _pln = tempfile.mkdtemp(), []
run(_press_on_first_read(_hpn, ''), extra_argv=['--no-parallel', '--no-journal'],
    seconds=4.0, handoff=_hpn, whole_text=_ONE_DROP_WHOLE, planners=_pln)
eq('...and nor with --no-journal', [p[1].get('keep') for p in _pln], [False])

# A payout on the screen is an offer whatever else is printed round it.
_PAID_PLANNER = _ONE_DROP + '\n$12.50\nAccept'
ok_('the premise: that screen has a payout and a planner\'s grammar',
    OP.parse(_PAID_PLANNER)['pay'] == 12.5 and OP.find_planner(_PAID_PLANNER))
_hp4 = tempfile.mkdtemp()
rp4 = run(_press_on_first_read(_hp4, ''), extra_argv=['--no-parallel'], seconds=4.0,
          handoff=_hp4, dropoff_window=1.0, whole_text=_PAID_PLANNER)
eq('a planner with a payout on the screen is not answered as a planner',
   rp4['planners'], [])
eq('...and the press is told it found nothing, as for any offer card',
   [d[0] for d in rp4['dropoffs'] if d[1].get('asked')], [None])

# ...and a sighting off a frame with a payout on it carries no address, even
# one printed under a Dropoff label: the refusal is the frame's, and stays in
# the scanner with the frame.
_PAID_NAV = 'Dropoff\n12 Fable St, Acworth, GA 30101\n$12.50\nAccept'
ok_('the premise: that screen has a payout, and an address under a Dropoff label',
    OP.parse(_PAID_NAV)['pay'] == 12.5
    and (OP.find_address(_PAID_NAV) or {}).get('zip') == '30101'
    and OP.address_under_dropoff(_PAID_NAV))
_hp4b = tempfile.mkdtemp()
rp4b = run(_press_on_first_read(_hp4b, ''), extra_argv=['--no-parallel'], seconds=4.0,
           handoff=_hp4b, dropoff_window=1.0, whole_text=_PAID_NAV)
_paid_seen = [x['stops'] for x in rp4b['sightings'] if x['whole']]
ok_('a sighting off a frame with a payout on it carries no address (%r)' % _paid_seen,
    bool(_paid_seen) and all(v == [] for v in _paid_seen))

# ...and a reading of the whole screen box is not one of the two card reads a
# verdict waits for, in either direction. Scanner.settle ran the agreement
# counter over every read, whole or not, so the reading kept out of the offer
# was still deciding whether the offer was confirmed. One read at a time, where
# every run shows it; paired reads confirm each other and show it only when the
# partner frame loses its payout, and then it is the same thing.
#
# Pressed during the third card read, after the card has locked on the second.
# The first card verdict after the press is the one at the index of the first
# whole read, because reads are one at a time and a whole read emits nothing.
def _press_on_card_read(handoff, press_on, text_for):
    seen = [0]

    def texts(n, k):
        if k == 0:
            seen[0] += 1
            if seen[0] == press_on:
                open(os.path.join(handoff, 'uberscan-dropoff'), 'w').close()
        return text_for(seen[0])
    return texts, seen


def _after_press(r):
    at = r['wholes'].index(True) if True in r['wholes'] else None
    return at, [v[0][3] for v in r['verdicts']]


# A navigation screen read whole, then the same card again. Before, the screen
# reset the counter and the card's next read came back unlocked, which the
# panel draws as a "?" on a verdict it had already settled.
_hw1 = tempfile.mkdtemp()
_texts, _seen = _press_on_card_read(_hw1, 3, lambda c: WHOLE)
rw1 = run(_texts, extra_argv=['--no-parallel'], seconds=40.0, handoff=_hw1,
          dropoff_window=1.0, whole_text=NAV_ADDR,
          until=lambda rows, ann, calls: _seen[0] >= 5)
_at, _locks = _after_press(rw1)
ok_('a ⌖ press after the card locked was read whole (%r, %r)'
    % (rw1['wholes'], _locks), _at is not None and _at < len(_locks) and _locks[_at - 1])
if _at is not None and _at < len(_locks):
    eq('...and the whole-screen read does not unlock the card it was pressed over',
       _locks[_at], True)

# A card that arrives while the press is open, read whole under a map that adds
# nothing the parser keeps — so the whole-screen reading says exactly what the
# card's first read will. Before, that confirmed it: the card landed in the
# journal and settled on the panel off ONE read of the card box.
_hw2 = tempfile.mkdtemp()
_texts, _seen = _press_on_card_read(_hw2, 3, lambda c: SECOND if c <= 3 else WHOLE)
rw2 = run(_texts, extra_argv=['--no-parallel'], seconds=40.0, handoff=_hw2,
          dropoff_window=1.0, whole_text=WHOLE + '\nKennesaw State Univ\nChastain Rd',
          until=lambda rows, ann, calls: _seen[0] >= 6)
_at, _locks = _after_press(rw2)
ok_('a card that arrived during a ⌖ press was read whole first (%r, %r)'
    % (rw2['wholes'], _locks), _at is not None and _at + 1 < len(_locks))
if _at is not None and _at + 1 < len(_locks):
    eq('...and the whole-screen read does not confirm its first card read',
       _locks[_at], False)
    eq('...which its own second read does', _locks[_at + 1], True)

# --- what the phone showed after a card landed ------------------------------
#
# The rig cannot see the Accept press and must never make it, so the only
# evidence a job was taken is the screen the phone goes to afterwards. These
# rows are the corpus for building that and nothing else — nothing reads them
# and nothing writes `accepted` off them.
#
# Driven through main() because the branch is a closure inside digest() and the
# one fault that matters is it never firing at all. `note_screen`'s own suite
# proves what it writes; this proves the loop ever calls it.

# The post-accept screen as the owner's own screenshot reads it, destination
# and all. It NAMES A PLACE, and that is the point: an Uber navigation screen
# names where the job goes the same way a card names the shop, so a guard that
# refused a frame for naming one would throw away exactly the screens worth
# collecting. What it named is written onto the row instead.
NAV = ('3.2 mi\nI-75 S toward 14th St\n65 LIMIT\n8 min 4.8 mi\n'
       'Deliver to Daria I.\nBCG Atlanta (1075 Peachtree St NE)')

# The card is read four times and lands on the second, so reads three and four
# are an offer card with a landed card already on the slate. Anything less and
# the fixture cannot tell "only a payout-free screen is recorded" from "the
# screen happened to be the next thing read": with the card read twice it lands
# on the last of them, the very next read is the navigation screen either way,
# and dropping `an_offer` from the guard entirely changes nothing anybody can
# see. Measured — that mutation survived this check until the fixture grew
# these two reads.
r = run(lambda n, k: WHOLE if n <= 4 else NAV, extra_argv=['--no-parallel'],
        seconds=30.0, health_every=0.2,
        until=lambda rows, ann, calls: any(x.get('kind') == 'screen'
                                           for x in rows))
_screens = [x for x in r['rows'] if x.get('kind') == 'screen']
_offers = [x for x in r['rows'] if not x.get('kind')]
ok_('the screen that followed a card reaches the journal', len(_screens) == 1)
if _screens and _offers:
    eq('...naming the card it followed', _screens[0].get('after'),
       _offers[-1].get('id'))
    ok_('...and carrying what was on it',
        'Deliver to Daria I.' in (_screens[0].get('text') or ''))
    # The reading as it was read, not the flattened one the parser works on.
    # On these screens the LINE is the grammar — "Deliver to Daria I." is a
    # line — and the merged reading in `parsed` has already had that thrown
    # away. The loop has both in hand at the call site and has to pass the
    # right one.
    ok_('...as it was read, line breaks and all',
        '\n' in (_screens[0].get('text') or ''))
# ...and the driver can see it happening from the seat, which is the only place
# they can see anything. A collection that quietly stopped collecting would read
# months later as a rate of zero, and the journal is not somewhere a person
# checks while driving.
ok_('the health line says how many screens have been recorded (%r)'
    % ([m for m in r['logs'] if 'screen' in m][:1],),
    any('recorded as following a card' in m for m in r['logs']))
# ONCE, however long the navigation screen sits in front of the camera. This is
# the check that stands between a delivery and a few hundred identical rows in
# a file that is only ever appended to.
# The BOUND — one screen row per card, whatever else is read — is not checked
# here, and deliberately not. It cannot be: once a read comes back with no
# payout `card_on_screen` goes false, the verify beat stops (see next_verify),
# and the stubbed camera holds one still picture, so the motion gate never
# fires again. Measured, on three fixtures: five reads every time, one of them
# payout-free, whatever the reader is told to answer afterwards.
#
# A check written over that run is a check that cannot fail — and one was,
# reading `len(_screens) <= 2` over a run whose `until` halts at the first
# screen row. Deleting the whole once-per-card mechanism from note_screen left
# this suite green while rpi/test_journal.py caught it with four failures.
# That is where the bound is proven, against the real consider(), including the
# case that made it false: a card lands several rows, not one.

# An Uber navigation screen NAMES its destination, the same way a card names the
# shop. Recorded, not acted on: refusing a frame for naming a place would throw
# away exactly the screens this is collected for, and trusting one would be the
# recogniser it must not invent. The loop has to hand what the frame named down
# to the row rather than dropping it on the floor.
ok_('...carrying what the screen named (%r)' % (_screens[0].get('places'),),
    any('BCG Atlanta' in p for p in (_screens[0].get('places') or [])))
# ...and it is a SCREEN, not the card. The two classes a recogniser has to
# separate are "an offer card" and "the screen after one", so a corpus holding a
# card's own text under `kind: screen` is a corpus that teaches the opposite of
# what it was collected for. Asked of the payout, because that is the grammar
# `an_offer` itself separates them by, and asked of every row rather than the
# first: one right answer among several wrong ones is still a poisoned corpus.
eq('no screen row carries a payout, which would make it a card',
   [x.get('text') for x in _screens
    if OP.find_pay(OP.normalize(x.get('text') or '')) is not None], [])

# ONE FRAME of glare over a card reads `pay: None` over a card, and the loop has
# to say which it was. `card_on_screen` still holds the PREVIOUS read's answer
# at the call site, so the loop knows there was a card here a moment ago and
# passes that down onto the row. Not refused — reads are driven by a motion gate
# and the frame after an accept is sometimes the only one, so refusing would
# lose the screen rather than label it.
r3 = run(lambda n, k: GLARE if n == 5 else WHOLE, extra_argv=['--no-parallel'],
         seconds=20.0,
         until=lambda rows, ann, calls: any(x.get('kind') == 'screen'
                                            for x in rows))
_glared = [x for x in r3['rows'] if x.get('kind') == 'screen']
ok_('a glared frame of a card is recorded', len(_glared) == 1)
if _glared:
    eq('...and the loop marks it as taken with a card still up',
       _glared[0].get('cardWasUp'), True)

# A CARD THE RIG SAW AND NEVER RECORDED must not have the next screen filed
# against the card before it. This is the fault that would have put a lie in the
# journal, and it is reproduced here end to end because that is how it was found
# — reading the code, the slate looked like "the last card", and it is "the last
# card that LANDED".
#
# A card needs two agreeing reads to lock (Scanner.agree_to_lock) and consider()
# is only called on a reading that is ready AND locked, so a second card
# delivered exactly once is seen, counted in `saw`, and never reaches the
# journal at all. `saw` minus `kept` is the measured count of those, and the
# offers page already renders it as "the scanner picked a payout off the screen
# and never managed to record it".
#
# Before the fix this run wrote {kind: screen, after: <card A>} over a driver
# who had just accepted card B.
SECOND_CARD = ('$9.25 4 min (1.4 mi) away Barrett Pkwy NW, Kennesaw '
               '18 min (5.2 mi) trip 44 Oak St, Acworth, GA 30101')
r4 = run(lambda n, k: WHOLE if n <= 3 else (SECOND_CARD if n == 4 else NAV),
         extra_argv=['--no-parallel'], seconds=20.0,
         until=lambda rows, ann, calls: calls >= 6)
_landed = [x.get('id') for x in r4['rows'] if not x.get('kind')]
_after = [x.get('after') for x in r4['rows'] if x.get('kind') == 'screen']
ok_('one card landed and a second was seen without landing (%r)'
    % (sorted(set(_landed)),), len(set(_landed)) == 1)
eq('the screen after a card that never landed is not filed against the one '
   'before it', _after, [])

# A CLIPPED read is not a payout-free screen. `clipped` means the payout was
# found and was flush against the top of the crop, and the reader answers it
# with an empty parse — so the parse has no payout and no places over a screen
# that was an offer card. Filing that as "what the phone showed after the card"
# would put a card's own text into the corpus as the negative class, which is
# the one confusion a recogniser built on these rows could not survive.
r2 = run(lambda n, k: WHOLE, extra_argv=['--no-parallel'], seconds=14.0,
         clipped_for=lambda n, k: n >= 3,
         until=lambda rows, ann, calls: calls >= 8
         and any(not x.get('kind') for x in rows))
ok_('a card landed before the crop slipped',
    any(not x.get('kind') for x in r2['rows']))
eq('a clipped read is not recorded as the screen after a card',
   [x for x in r2['rows'] if x.get('kind') == 'screen'], [])

# ...and the page is told, which is the other half of the same fact. The
# reading a clipped read sends is parse('') — no pay, no time, no places — and
# without the flag the panel said "scanner running, no offer on screen" over
# the card while this loop's own log said the payout sat against the top edge
# of the crop. Asked of what main() handed emit(), so a flag emit() can write
# but the loop never passes is caught here and not only in test_scan_pi.
# As (what the loop said, whether the reading was empty): repr-sorted, so a
# loop that says nothing (None) is reported rather than crashing the sort.
_said = sorted(set((v[1].get('clipped'), v[0][1].get('pay') is None)
                   for v in r2['verdicts']), key=repr)
ok_('the loop tells the page which readings it dropped for a payout at the '
    'box\'s edge (%r)' % (_said,), any(c is True for c, _ in _said))
eq('...on those readings and no others: every one of them is empty, and every '
   'reading of the card before the crop slipped says it was not',
   _said, [(False, False), (True, True)])

# --- 📷 Snap: the reader says what it last read, into the folder named ---------
#
# status.json is what the panel knew. What the READER was looking at — the card
# it cut out last, what it made of it, its counters, its last beat, the
# phone's GPS — never left this loop, so POST /api/snap leaves a request naming
# its folder and the loop answers into it once. Driven through main() the way
# the dropoff and crop-box requests are, with the request written as server.js
# writes it: JSON naming the folder, renamed into place.
import socket as _socket                                      # noqa: E402
import threading as _threading                                # noqa: E402


def _ask_snap(handoff, folder, age=None):
    """What POST /api/snap leaves for the loop. `age` back-dates it."""
    where = os.path.join(handoff, 'uberscan-snap.json')
    with open(where + '.w', 'w') as fh:
        json.dump({'folder': folder}, fh)
    os.replace(where + '.w', where)
    if age is not None:
        os.utime(where, (time.time() - age, time.time() - age))
    return where


def _json_or_none(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


# A crop of its own for each read, flat grey at 20 times the read's number, so
# the picture kept says which read it came from. Read 4 never comes back: the
# reader's thread is stuck on it, so read 3 is the last one there is. An answer
# that went back for a fresh read shows as a fifth: asked of the reader, it is
# counted as handed over though it never starts, and made on the loop's own
# thread, it is answered (hang_on_loop=False) — with read 5's crop — rather
# than hanging the suite where no check could see it. Every snap run below
# that strands the reader does the same, for the same reason.
def _crop_of(n):
    return np.full((120, 80), 20 * n, np.uint8)


_snho = tempfile.mkdtemp()
_snfold = tempfile.mkdtemp()
_sreq = [None]


def _snap_once_stuck(rows, ann, calls):
    if _sreq[0] is None and calls >= 4 and any(not x.get('kind') for x in rows):
        _sreq[0] = _ask_snap(_snho, _snfold)
    return _sreq[0] is not None and os.path.exists(os.path.join(_snfold, 'reader.json'))


r14 = run(lambda n, k: WHOLE, extra_argv=['--no-track'], seconds=20.0, handoff=_snho,
          alive_every=0.05, stuck_after=60.0, hang_from=4, hang_on_loop=False,
          fitted_for=_crop_of, until=_snap_once_stuck)
_said = _json_or_none(os.path.join(_snfold, 'reader.json')) or {}
_jpg = cv2.imread(os.path.join(_snfold, 'reader.jpg'), cv2.IMREAD_GRAYSCALE)
ok_('a snap request is answered into the folder it names, reader.json and reader.jpg (%r)'
    % sorted(os.listdir(_snfold)), _said and _jpg is not None)
ok_('reader.jpg is the crop the last read handed the reader, kept from it (mean %r, read 3 is 60)'
    % (None if _jpg is None else round(float(_jpg.mean()), 1)),
    _jpg is not None and _jpg.shape == (120, 80) and abs(float(_jpg.mean()) - 60) < 2)
eq('...answered while the reader is stuck on the next one, so no read was asked for it '
   '(reads handed to the reader, reads begun)', (r14['submitted'], r14['calls']), (4, 4))
_read = _said.get('read') or {}
eq('reader.json says what that read saw, as text and as figures',
   (_read.get('text'), (_read.get('parsed') or {}).get('pay'),
    (_read.get('rate') or {}).get('state')), (WHOLE, 16.05, 'go'))
eq('...and that it read the card crop, not the whole screen for ⌖', _read.get('wholeScreen'), False)
ok_('...when it was read, and how long before the answer (%r ms)' % _read.get('ageMs'),
    isinstance(_read.get('ageMs'), int) and 0 <= _read['ageMs'] < 30000
    and abs(_read.get('at', 0) + _read['ageMs'] - (_said.get('answeredAt') or 0)) <= 1)
_snoffers = [x for x in r14['rows'] if not x.get('kind')]
eq('...the offer it has on record, and that it is in the journal',
   _said.get('offer'), {'id': _snoffers[-1].get('id') if _snoffers else '?', 'landed': True})
ok_('...and the card\'s episode (%r)' % _said.get('episode'),
    isinstance(_said.get('episode'), int))
# Three reads were digested and the health window is two minutes, so the
# counters as they stand are those three — not a fresh window a press opened.
eq('...the health counters as they stand', ((_said.get('health') or {}).get('reads'),
                                              (_said.get('health') or {}).get('complete')), (3, 3))
_beat = _said.get('heartbeat')
ok_('...and the flags the last heartbeat carried (%r)'
    % (_beat,), isinstance(_beat, dict) and 'refindRefused' not in _beat
    and (_beat.get('tooBright'), _beat.get('tooDim'), _beat.get('notSaving')) == (False, False, None)
    and isinstance(_beat.get('ageMs'), int))
eq('...the camera\'s word among them, null while it can see',
   (_beat or {}).get('blind', 'absent'), None)
# ...and the heat guard's state, which the panel was told on that beat.
eq('...and whether the heat guard was on, as the panel was told it',
   (_beat or {}).get('heatGuard', 'absent'), False)
eq('...and "gps off", with no --gps given', _said.get('gps'), 'gps off')
ok_('the request is taken, so it is answered once',
    _sreq[0] is not None and not os.path.exists(_sreq[0]))
eq('...and the log says where the answer went, once',
   [l for l in r14['logs'] if l.startswith('snap:')],
   ['snap: said what the reader last read into %s' % _snfold])
# ...and the richer snap's two (EXPERIMENTAL): the loop's last reads, each the
# card box it read, and its newest full-resolution frame, written on a thread
# of its own before reader.json.
_snreads = (_json_or_none(os.path.join(_snfold, 'reads.json')) or {}).get('reads') or []
eq('reads.json holds the reads the loop collected, as card-box reads of what they saw',
   [(r.get('kind'), r.get('pay'), r.get('skippedDark')) for r in _snreads],
   [('card box', 16.05, False)] * 3)
_snframe = _said.get('frame') if isinstance(_said.get('frame'), dict) else {}
ok_('frame.jpg is the newest sensor frame the loop held, said in reader.json (%r)' % (_snframe,),
    os.path.exists(os.path.join(_snfold, 'frame.jpg')) and _snframe.get('source') == 'sensor'
    and _snframe.get('width', 0) <= 2000)

# ...and before any read has come back there is no crop to give, and it says so.
# --no-journal as well, so there is no card on record to name either.
_snho2 = tempfile.mkdtemp()
_snfold2 = tempfile.mkdtemp()
_sreq2 = [None]


def _snap_first_thing(rows, ann, calls):
    if _sreq2[0] is None and calls >= 1:
        _sreq2[0] = _ask_snap(_snho2, _snfold2)
    return _sreq2[0] is not None and os.path.exists(os.path.join(_snfold2, 'reader.json'))


run(lambda n, k: WHOLE, extra_argv=['--no-journal'], seconds=15.0, handoff=_snho2,
    hang_from=1, hang_on_loop=False, stuck_after=60.0, fitted_for=_crop_of,
    until=_snap_first_thing)
_said2 = _json_or_none(os.path.join(_snfold2, 'reader.json')) or {}
eq('a scanner that has not read anything yet answers with no read and says why',
   (_said2.get('read', '?'), _said2.get('noCrop')), (None, 'no read yet'))
eq('...and leaves no reader.jpg', 'reader.jpg' in os.listdir(_snfold2), False)
eq('...its last reads (EXPERIMENTAL) an empty ring, none having come back',
   (_json_or_none(os.path.join(_snfold2, 'reads.json')) or {}).get('reads'), [])
eq('...and says no journal keeps an offer on record, rather than naming none',
   _said2.get('offer'), 'not kept: --no-journal')

# ...and a ⌖ read is a read: the last thing the reader cut out was the whole
# screen box, and reader.json says that is what it was. Pressed in read 1, so
# read 2 is the whole-screen one; read 3 never comes back, so read 2 stays the
# last there is.
_snho3 = tempfile.mkdtemp()
_snfold3 = tempfile.mkdtemp()
_sreq3 = [None]


_SNAP_NAV = 'Dropoff 9 Elm St, Acworth, GA 30101 4 min Start'


def _press_dropoff_in_read_1(n, k):
    if n == 1 and k == 0:
        open(os.path.join(_snho3, 'uberscan-dropoff'), 'w').close()
    return WHOLE


def _snap_after_the_press(rows, ann, calls):
    if _sreq3[0] is None and calls >= 3:
        _sreq3[0] = _ask_snap(_snho3, _snfold3)
    return _sreq3[0] is not None and os.path.exists(os.path.join(_snfold3, 'reader.json'))


_r15 = run(_press_dropoff_in_read_1, seconds=15.0, handoff=_snho3,
           whole_text=_SNAP_NAV, hang_from=3, hang_on_loop=False, stuck_after=60.0,
           fitted_for=_crop_of, until=_snap_after_the_press)
_read3 = (_json_or_none(os.path.join(_snfold3, 'reader.json')) or {}).get('read') or {}
_jpg3 = cv2.imread(os.path.join(_snfold3, 'reader.jpg'), cv2.IMREAD_GRAYSCALE)
eq('the last read being ⌖\'s, reader.json says it read the whole screen, and what it saw (%r)'
   % (_r15['wholes'],), (_read3.get('wholeScreen'), _read3.get('text')), (True, _SNAP_NAV))
ok_('...and reader.jpg is that read\'s crop (mean %r, read 2 is 40)'
    % (None if _jpg3 is None else round(float(_jpg3.mean()), 1)),
    _jpg3 is not None and abs(float(_jpg3.mean()) - 40) < 2)

# --- ...but only a request still worth answering -----------------------------
#
# The request lives in /dev/shm, which a scanner restart does not clear, and
# server.js stops waiting after four seconds. One found older than that — made
# while the scanner was down, or aiming — would land reader files in a folder
# whose snap.json already says there are none.
for _age, _label, _said_as in (
        (10.0, 'a snap request from before the scanner was listening',
         r'ignored a snap request from \d+s ago'),
        (-600.0, 'a snap request stamped ahead of a clock that has since stepped back',
         r'ignored a snap request stamped \d+s ahead of the clock')):
    _ho = tempfile.mkdtemp()
    _fold = tempfile.mkdtemp()
    _req = _ask_snap(_ho, _fold, age=_age)
    _r = run(lambda n, k: WHOLE, seconds=6.0, handoff=_ho, fitted_for=_crop_of,
             until=lambda rows, ann, calls: calls >= 2)
    eq('%s is not answered' % _label, os.listdir(_fold), [])
    eq('...is cleared, so it cannot be answered later either', os.path.exists(_req), False)
    ok_('...and the log says it was ignored (%r)'
        % [l for l in _r['logs'] if 'snap request' in l][:1],
        any(re.match(_said_as, l) for l in _r['logs']))

# ...and a folder that is not there is not made. The server makes the folder;
# one that has gone was removed by a press that kept nothing.
_ho = tempfile.mkdtemp()
_gone = os.path.join(tempfile.mkdtemp(), 'removed-by-the-server')
_req = _ask_snap(_ho, _gone)
_r = run(lambda n, k: WHOLE, seconds=6.0, handoff=_ho, fitted_for=_crop_of,
         until=lambda rows, ann, calls: calls >= 2)
eq('a snap request naming a folder that is not there makes none', os.path.exists(_gone), False)
ok_('...and says so in the log',
    any(l.startswith('ignored a snap request naming no folder') for l in _r['logs']))

# The age rule's edges, asked directly the way test_scan_pi.py asks
# dropoff_requested: a request a moment old and one just inside the window are
# answered; one exactly the window old is not.
_ho = tempfile.mkdtemp()
_fold = tempfile.mkdtemp()
_was_dir, _was_log = os.environ.get(HO.ENV_DIR), SP.log
os.environ[HO.ENV_DIR] = _ho
SP.log = lambda m: None
try:
    _now = time.time()
    for _age in (0.2, SP.SNAP_ANSWER_WINDOW - 0.2):
        _req = _ask_snap(_ho, _fold)
        os.utime(_req, (_now - _age, _now - _age))
        eq('a snap request %.1fs old names its folder' % _age, SP.snap_requested(now=_now), _fold)
        eq('...once', SP.snap_requested(now=_now), None)
    _req = _ask_snap(_ho, _fold)
    os.utime(_req, (_now - SP.SNAP_ANSWER_WINDOW, _now - SP.SNAP_ANSWER_WINDOW))
    eq('a snap request exactly its window old is not answered', SP.snap_requested(now=_now), None)
finally:
    SP.log = _was_log
    if _was_dir is None:
        os.environ.pop(HO.ENV_DIR, None)
    else:
        os.environ[HO.ENV_DIR] = _was_dir

# --- ...with the phone's GPS when it was asked to listen to one --------------
#
# A phone that answers: a socket here sending the RMC sentence test_gps.py reads
# as 34.0117N 84.6105W. reader.json carries Phone.state() and fix() as given.
RMC = '$GPRMC,182049.00,A,3400.7020,N,08436.6300,W,0.0,0.0,120926,,,A*4A'
_gsock = _socket.socket()
_gsock.bind(('127.0.0.1', 0))
_gsock.listen(1)
_gstop = []


def _gps_phone():
    _gsock.settimeout(0.2)
    while not _gstop:
        try:
            conn, _ = _gsock.accept()
        except OSError:
            continue
        try:
            while not _gstop:
                conn.sendall((RMC + '\r\n').encode('ascii'))
                real_sleep_for_gps(0.1)
        except OSError:
            pass
        finally:
            conn.close()


real_sleep_for_gps = time.sleep
_gthread = _threading.Thread(target=_gps_phone, daemon=True)
_gthread.start()
_ho = tempfile.mkdtemp()
_fold = tempfile.mkdtemp()
_greq = [None]
_gt0 = time.time()


def _snap_once_fixed(rows, ann, calls):
    if _greq[0] is None and time.time() - _gt0 > 2.0 and calls >= 1:
        _greq[0] = _ask_snap(_ho, _fold)
    return _greq[0] is not None and os.path.exists(os.path.join(_fold, 'reader.json'))


try:
    run(lambda n, k: WHOLE, extra_argv=['--gps', '127.0.0.1:%d' % _gsock.getsockname()[1]],
        seconds=15.0, handoff=_ho, fitted_for=_crop_of, until=_snap_once_fixed)
finally:
    _gstop.append(True)
    _gsock.close()
_gps = (_json_or_none(os.path.join(_fold, 'reader.json')) or {}).get('gps')
_gps = _gps if isinstance(_gps, dict) else {'said': _gps}
eq('a rig listening to a phone says what the phone said: its state, and its fix (%r)'
   % (_gps.get('said'),),
   ((_gps.get('state') or {}).get('state'),
    round((_gps.get('fix') or {}).get('lat') or 0, 4),
    round((_gps.get('fix') or {}).get('lon') or 0, 4)),
   ('fixed', 34.0117, -84.6105))

# --- the pieces, asked directly ------------------------------------------------
# An age is two readings of one clock, and the Pi's jumps when the network sets
# it. A read before the jump and an answer after it are not "20,000 days ago".
eq('a read and an answer on a set clock are an age in ms',
   SP.age_ms(1790000000.0, 1790000002.5), 2500)
eq('...a read before the clock was set is of unknown age',
   SP.age_ms(1000.0, 1790000002.5), None)
eq('...and so is a read stamped after the answer: the clock stepped back',
   SP.age_ms(1790000002.5, 1790000000.0), None)

# A card the journal has not taken yet — the append failed, or has not run — is
# on record in memory and not on disk, and reader.json says which.
class _OnRecord(object):
    id, landed_id = '1790000000000-1605', None


eq('a card on record that has not reached the journal is said as not landed',
   SP.reader_record(None, 1790000000.0, offer_log=_OnRecord()).get('offer'),
   {'id': '1790000000000-1605', 'landed': False})

# A snap is a picture of what the panel showed, and `"keepPlaces": false` is a
# rule about the journal. rpi/README.md says a snap keeps the fix and the
# card's text whatever that setting says; this holds the code to that, so a
# snap that started honouring keepPlaces would have to change what the README
# tells the driver too. Marietta Square: a public place, an invented fix.
class _KeepsNoPlaces(object):
    id, landed_id, keep_places = '1790000000000-1606', None, False


class _FixAt(object):
    def state(self):
        return 'ok'

    def fix(self):
        return {'lat': 33.9526, 'lon': -84.5499, 'ageSeconds': 0.6,
                'mode': 3, 'err': 27.8, 'ok': True, 'why': None}


_snap_read = {'at': 1790000000.0, 'wholeScreen': False, 'crop': None,
              'text': '$4.21 Jimmy John\'s Marietta Sq', 'parsed': {}, 'rate': None}
_snap_rec = SP.reader_record(_snap_read, 1790000001.0,
                             offer_log=_KeepsNoPlaces(), phone=_FixAt())
eq('a snap keeps where the car was even under keepPlaces:false, as '
   'rpi/README.md says',
   ((_snap_rec.get('gps') or {}).get('fix') or {}).get('lat'), 33.9526)
eq('...and the card\'s own text, places and all',
   (_snap_rec.get('read') or {}).get('text'), '$4.21 Jimmy John\'s Marietta Sq')

# The counters a snap reports are the ones the health line would, as they
# stand, and asking for them does not start a new window.
_h = SP.Health()
_h.since = 1000.0
for _i in range(2):
    _h.add({'ms': {'total': 100.0 + _i}}, {'complete': True, 'pay': 9.0})
_mid = _h.counters(1010.0)
_was_log = SP.log
SP.log = lambda m: None
try:
    _tally = _h.report(1000.0 + SP.HEALTH_EVERY + 1, None, PL.Scanner(quad=None, roi=None))
finally:
    SP.log = _was_log
eq('a snap\'s counters are the window as it stands', (_mid['reads'], _mid['over']), (2, 10))
eq('...and asking for them does not end the window: the health line still has both reads',
   (_tally or {}).get('reads'), 2)
# ...plus the one thing counters() cannot know, the corners' state, which the
# `seen` row carries and report() alone is handed the tracker for. This holds
# the field names only: the tally is counters() and `corners`, and nothing
# else. Whether `_window` re-states a counter under the same name is held by
# the next check, which asks it for its keys.
eq('...the line\'s tally being the same counters, at its own moment, and the corners',
   sorted((_tally or {}).keys()), sorted(list(_mid.keys()) + ['corners']))
eq('...the window adding only the corners, never a second copy of a counter',
   sorted(_h._window(None).keys()), ['corners'])

# A crop that cannot be written is said in reader.json, and reader.json itself
# still goes; a folder that cannot take reader.json is said in the log.
_fold = tempfile.mkdtemp()
_said3 = []
_was_log = SP.log
SP.log = _said3.append
try:
    _last = {'at': time.time(), 'fitted': None, 'wholeScreen': False, 'crop': None,
             'text': '', 'parsed': {}, 'rate': {}}
    SP.answer_snap(_fold, _last, SP.reader_record(_last, time.time()))
    _blocked = os.path.join(tempfile.mkdtemp(), 'a-file')
    open(_blocked, 'w').close()
    eq('a folder that will not take reader.json is answered False',
       SP.answer_snap(_blocked, None, SP.reader_record(None, time.time())), False)
finally:
    SP.log = _was_log
ok_('a crop that cannot be written is said in reader.json (%r)'
    % (_json_or_none(os.path.join(_fold, 'reader.json')) or {}).get('noCrop'),
    ((_json_or_none(os.path.join(_fold, 'reader.json')) or {}).get('noCrop') or '')
    .startswith('could not write reader.jpg: '))
ok_('...and one that cannot take reader.json is said in the log (%r)' % _said3[-1:],
    any(l.startswith('could not answer a snap into %s' % _blocked) for l in _said3))

# --- the app's zone prompt is not an offer -----------------------------------
#
# "Switch to this zone with peak pay! +$1.00/order ... Avg. offer wait 1min"
# reached the panel five times on the owner's week as an offer — $12.00/hr
# PASS, $20.00/hr twice, $10.91/hr, one withheld for its one minute — and the
# journal five times as a row the offers page counted. The parser refuses the
# bonus as a payout now (OP.PAY_IS_PER_ORDER); these are the end of that, driven
# through main(): what the panel was sent, and what reached the file.
#
# Verbatim, row 565's stored frame.
PROMPT = ('GA: Marietta North\nSwitch to this zone\nwith peak pay!\n'
          '+$1.00/order until 8:20 PM\nAvg. offer wait\n1min\nDon\'t switch')
rp1 = run(lambda n, k: PROMPT, extra_argv=['--no-parallel'], seconds=12.0,
          until=lambda rows, ann, calls: calls >= 3
          or any(x.get('kind') == 'promo' for x in rows))
ok_('the prompt was read (%d reads)' % rp1['calls'], rp1['calls'] >= 1)
eq('no offer row is written for the zone prompt',
   [x.get('pay') for x in rp1['rows'] if not x.get('kind')], [])
eq('...nor any verdict sent to the panel for it',
   [v[0][0].get('state') for v in rp1['verdicts']
    if v[0] and isinstance(v[0][0], dict) and v[0][0].get('ready')], [])
eq('...nor an offer announced off it', rp1['announced'], [])
# The rig's own start and stop rows bracket every run now and are not about the
# screen, so they are set aside here; everything else the run wrote is asked.
_rp1 = [x for x in rp1['rows'] if x.get('kind') != 'up']
eq('it is written as a prompt instead',
   [x.get('kind') for x in _rp1], ['promo'])
if _rp1:
    ok_('...the prompt as it was read, line breaks and all',
        _rp1[0].get('text') == PROMPT)

# ...and after a card, it is not the screen that followed the card. It is one
# prompt in one place, a `promo` row with its own stamp, whether or not a card
# happened to land before it. The card is read six times before the prompt, two
# more than the navigation-screen run above needs, because a run on a loaded
# machine that has not landed the card by then tests nothing here.
rp2 = run(lambda n, k: WHOLE if n <= 6 else PROMPT,
          extra_argv=['--no-parallel'], seconds=30.0,
          until=lambda rows, ann, calls: any(
              x.get('kind') in ('promo', 'screen') for x in rows))
ok_('a card landed before the prompt (%d reads)' % rp2['calls'],
    any(not x.get('kind') for x in rp2['rows']))
eq('the prompt after a card is not recorded as the screen after it',
   [x.get('text') for x in rp2['rows'] if x.get('kind') == 'screen'], [])
eq('...it is recorded as a prompt',
   len([x for x in rp2['rows'] if x.get('kind') == 'promo']), 1)
eq('...and no offer row carries its bonus as a payout',
   [x.get('pay') for x in rp2['rows'] if not x.get('kind')
    and x.get('pay') != 16.05], [])

# ...and the prompt ENDS the card's window, so the screen after the prompt is
# not filed against the card before it. While the bonus read as a $1 payout,
# saw_card dropped the slate on it; refused, it left the slate armed, and this
# run wrote the navigation screen `after:` the card — a card the driver did not
# take, with the app's own prompt in between. All five cards read just before
# the week's five prompts went unticked.
#
# The picture in the mount is changed under the prompt's read. Without that
# the still picture is never read again once a frame comes back payout-free
# (see the once-per-card note above), and a run that never reads the screen
# after the prompt cannot fail the check that is about it.
_rp3 = {'cam': [], 'nav_at': None}


def _rp3_texts(n, k):
    if n <= 6:
        return WHOLE
    if n == 7:
        if _rp3['cam'] and k == 0:
            _rp3['cam'][0].offer = _rp3['cam'][0].empty
        return PROMPT
    if _rp3['nav_at'] is None:
        _rp3['nav_at'] = time.time()
    return NAV


# Halted at the screen row if one is written, or three seconds after the
# screen was first read. With the slate left armed, the wrong row landed 21ms
# after that read, so one that has not landed in three seconds is not coming.
rp3 = run(_rp3_texts, extra_argv=['--no-parallel'], seconds=40.0,
          cam_out=_rp3['cam'],
          until=lambda rows, ann, calls: any(
              x.get('kind') == 'screen' for x in rows)
          or (_rp3['nav_at'] is not None
              and time.time() - _rp3['nav_at'] > 3.0))
ok_('a card, the prompt, then a screen: the card landed (%d reads)'
    % rp3['calls'], any(not x.get('kind') for x in rp3['rows']))
ok_('...the prompt was recorded',
    any(x.get('kind') == 'promo' for x in rp3['rows']))
ok_('...and the screen after the prompt was read', _rp3['nav_at'] is not None)
eq('the screen after the zone prompt is not filed against the card before it',
   [x.get('after') for x in rp3['rows'] if x.get('kind') == 'screen'], [])

# --- an idle screen showing the dash's earnings ----------------------------------
#
# DoorDash's idle screen prints the dash's earnings and Uber's prints the day's,
# so each reads with a payout and the parser calls it no offer (NOT_AN_OFFER).
# The loop asked only for the payout, so the resample burst and then the verify
# beat went on reading a still phone nobody had offered anything on — measured
# over 30 s of the DoorDash one: 15 reads, against 2 for the same screen with
# the earnings out of the box. Counted here over 12 s each, against the screen
# without them. Every word but the app's is invented.
IDLE_DD = ("$12.55\nThis dash\nAb Cd Chinese\nFinding offers.\n"
           "You're in a good place to wait for offers")
IDLE_UBER = "$45.67\nYou're online\nFinding trips"
IDLE_NONE = "This dash\nAb Cd Chinese\nFinding offers.\nYou're in a good place to wait for offers"
ok_('the premise: both idle screens read with a payout and as no offer',
    all(OP.parse(t)['pay'] is not None and OP.parse(t).get('notAnOffer')
        for t in (IDLE_DD, IDLE_UBER)) and OP.parse(IDLE_NONE)['pay'] is None)
_idle = {}
for _name, _text in (('none', IDLE_NONE), ('dd', IDLE_DD), ('uber', IDLE_UBER)):
    _idle[_name] = run(lambda n, k, t=_text: t, seconds=12.0)['submitted']
for _name, _what in (('dd', 'the dash\'s earnings'), ('uber', 'the day\'s earnings, online')):
    ok_('an idle screen showing %s is read no more than one without them (%d reads '
        'against %d in 12 s of a still screen)' % (_what, _idle[_name], _idle['none']),
        _idle[_name] <= _idle['none'] + 1)

# --- a card taller than the card box, through main() ---------------------------
#
# The 8 Oct card box, drawn round a short card, over the taller Early-look card
# whose $14.48 sits across its top edge. The read is the real Scanner._look and
# the card finder runs on the camera's own frames; only the engine is a stub,
# answering what the box saw ("Pit." for the payout, the journey whole) until
# the finder has been asked, and the whole card after.
_EARLY_BOX = ('Pit. FO\nIncludes expected tip\nEst. delivery 4:15 PM • 8.6 mi\n'
              "Dave's Hot Chicken (1985 Cobb\nParkway NW, STE 100)\n"
              'Foothill Trl & Northwoods Dr,\nMarietta\nMatching may take longer')
_EARLY_FOUND = ('Early look • Order in progress\nDelivery\n$14.48\n'
                + _EARLY_BOX.split('\n', 1)[1])
_EARLY_FRAME = TC.mount(TC.early_look_screen(), 720)
_EARLY_CFG = {'quad': TC.screen_corners(720), 'manualBox': True,
              'cropBox': list(TC.BOX_8OCT)}


def _amber(path):
    """How many pixels of the live view are the found card's amber outline."""
    pic = cv2.imread(path) if path and os.path.exists(path) else None
    if pic is None:
        return 0
    b, g, r = [pic[..., i].astype(int) for i in range(3)]
    return int(np.count_nonzero((r > 200) & (g > 120) & (g < 220) & (b < 90)))


_cf_ho, _cf_fold = tempfile.mkdtemp(), tempfile.mkdtemp()
_cf_snap = os.path.join(tempfile.mkdtemp(), 'live.jpg')
_cf_req = [None]


def _snap_after_rescue(rows, ann, calls):
    if _cf_req[0] is None and any(r.get('pay') == 14.48 for r in rows
                                  if not r.get('kind')) and calls >= 4:
        _cf_req[0] = _ask_snap(_cf_ho, _cf_fold)
    return (_cf_req[0] is not None and os.path.exists(os.path.join(_cf_fold, 'reader.json'))
            and any(r.get('kind') == 'seen' for r in rows))


r20 = run(lambda n, k: '', real_look=(_EARLY_BOX, _EARLY_FOUND), offer=_EARLY_FRAME,
          config_extra=_EARLY_CFG, handoff=_cf_ho, health_every=1.0, seconds=40.0,
          extra_argv=['--snapshot', _cf_snap], until=_snap_after_rescue)
ok_('with the card finder on, the taller card\'s payout reaches the journal '
    '(finder asked %d times)' % r20['finder'],
    r20['finder'] > 0 and any(x.get('pay') == 14.48 for x in r20['rows'] if not x.get('kind')))
ok_('...and the line the panel is sent says the read came off a card found, '
    'cropFrom "found" (%r)' % sorted(set(v[1].get('crop_from') for v in r20['verdicts'])),
    any(v[1].get('crop_from') == 'found' for v in r20['verdicts']))
_cf_said = (_json_or_none(os.path.join(_cf_fold, 'reader.json')) or {}).get('read') or {}
eq('...a Snap\'s reader.json says so too', _cf_said.get('cropFrom'), 'found')
ok_('...and so does the crop it reports, above the drawn box (%r)' % (_cf_said.get('crop'),),
    (_cf_said.get('crop') or [0, 1])[1] < TC.BOX_8OCT[1])
ok_('...the live view outlines the card found, in amber (%d pixels)' % _amber(_cf_snap),
    _amber(_cf_snap) > 100)
ok_('...the seen row counts it, beside the clipped ones (%r)'
    % [(x.get('rescued'), x.get('clipped')) for x in r20['rows'] if x.get('kind') == 'seen'],
    any((x.get('rescued') or 0) >= 1 for x in r20['rows'] if x.get('kind') == 'seen'))
ok_('...and the setup line says the finder is on',
    any(l.startswith('setup: card finder on') for l in r20['logs']))

# WHERE THE PAYOUT SHOWN CAME FROM, NOT WHERE THE LAST READ DID. The panel
# shows the merged reading, and a card read off a card found above the box and
# then through the box as drawn, at the same payout, is one episode with the
# found read's figures in it. Said per read, the line went back to "drawn" and
# the amber outline came down on the first drawn read, while the panel went on
# showing the payout the found card gave. Reads 1-2 here are off a found card,
# 3-6 the same card through the box, and from 7 there is no payout at all.
_pf_ho, _pf_fold = tempfile.mkdtemp(), tempfile.mkdtemp()
_pf_snap = os.path.join(tempfile.mkdtemp(), 'live.jpg')
_pf_req, _pf_amber = [None], []


def _pf_until(rows, ann, calls):
    if 4 <= calls <= 6:
        _pf_amber.append(_amber(_pf_snap))
    if _pf_req[0] is None and calls >= 4:
        _pf_req[0] = _ask_snap(_pf_ho, _pf_fold)
    # ...until the outline is down: after read 7 the stubbed screen does not
    # change, and no read follows it for as long as this would wait.
    return (calls >= 7 and os.path.exists(os.path.join(_pf_fold, 'reader.json'))
            and _amber(_pf_snap) == 0)


r20b = run(lambda n, k: _EARLY_FOUND if n <= 6 else '',
           found_for=lambda n, k: [0.025, 0.44, 0.95, 0.48] if n <= 2 else None,
           handoff=_pf_ho, seconds=40.0, extra_argv=['--snapshot', _pf_snap],
           until=_pf_until)
_pf_lines = [(v[0][1].get('pay'), v[1].get('crop_from')) for v in r20b['verdicts']]
ok_('a card whose payout a found card gave keeps saying "found" on the panel\'s line '
    'through the reads of it the box gave (%d lines at $14.48, %r)'
    % (sum(1 for p, _ in _pf_lines if p == 14.48),
       sorted(set(f for p, f in _pf_lines if p == 14.48))),
    sum(1 for p, _ in _pf_lines if p == 14.48) > 2
    and all(f == 'found' for p, f in _pf_lines if p == 14.48))
ok_('...and a line with no payout says "drawn" (%r)'
    % sorted(set(f for p, f in _pf_lines if p is None)),
    any(p is None for p, _ in _pf_lines)
    and all(f == 'drawn' for p, f in _pf_lines if p is None))
ok_('...the amber outline stays up over the box\'s reads of that card (%r)' % _pf_amber,
    any(a > 100 for a in _pf_amber))
eq('...and comes down once no payout is shown', _amber(_pf_snap), 0)
_pf_said = (_json_or_none(os.path.join(_pf_fold, 'reader.json')) or {}).get('read') or {}
eq('...a Snap\'s reader.json, taken on a read through the box, says the crop was the '
   'box and the payout a found card\'s',
   ((_pf_said.get('parsed') or {}).get('pay'), _pf_said.get('cropFrom'),
    _pf_said.get('payFrom')), (14.48, 'drawn', 'found'))

# ...and with it off, by config or by flag, the reads are the box as drawn: the
# finder is never asked, nothing is rescued, and the setup line says why.
for _how, _cfg, _argv, _why in (
        ('config', dict(_EARLY_CFG, cardFinder=False), [], 'cardFinder is false in the config'),
        ('flag', _EARLY_CFG, ['--no-card-find'], '--no-card-find')):
    _off = run(lambda n, k: '', real_look=(_EARLY_BOX, _EARLY_FOUND), offer=_EARLY_FRAME,
               config_extra=_cfg, extra_argv=['--snapshot', _cf_snap + '.off'] + _argv,
               seconds=15.0, until=lambda rows, ann, calls: calls >= 6)
    # Every one of those reads found the journey and no payout, which is the
    # read the finder is asked about when it is on. Run to six looks or fifteen
    # seconds, whichever is first. Off, the reads stop at four looks — two
    # rounds of paired reads, the first of the blank mount — because a reading
    # with no payout stops the verify beat (next_verify) and the stubbed
    # picture never moves the gate again. A main() that turned the finder on
    # whatever the config said is given the payout on the card's first round,
    # and so keeps reading: by six looks its line said "found" and $14.48 was
    # in the journal. Stopped at three looks, as this first was, that main()
    # had put nothing on the line or in the journal yet, and only "the finder
    # is never asked" failed for it.
    eq('with the card finder off by %s the finder is never asked, over %d reads'
       % (_how, _off['calls']), (_off['finder'], _off['calls'] >= 3), (0, True))
    eq('...every line says the box as drawn',
       sorted(set(v[1].get('crop_from') for v in _off['verdicts'])), ['drawn'])
    eq('...no payout reaches the journal',
       [x.get('pay') for x in _off['rows'] if not x.get('kind')], [])
    eq('...no amber on the live view', _amber(_cf_snap + '.off'), 0)
    ok_('...and the setup line says it is off, and why (%r)'
        % [l for l in _off['logs'] if 'card finder' in l][:1],
        any(l.startswith('setup: card finder OFF (%s)' % _why) for l in _off['logs']))

# ...and when it was asked and nothing came of it, the log's sample line says
# why beside what the reader saw: a taller card's payout that is never rescued
# otherwise reads, in the log, exactly like a box that read "Pit." with no
# finder at all. Unsure, on the Early-look card on a phone turned 1.5° inside
# its box (testcards.degrade 'roll'); and sure, with the read of the card
# found holding no payout either — what a navigation sheet whose journey line
# falls inside the box gets on every read (rpi/README.md).
for _what, _frame, _found_text, _said in (
        ('unsure of the card', TC.mount(TC.degrade(TC.early_look_screen(), 'roll',
                                                   strength=0.75), 720),
         _EARLY_FOUND, "Card finder: not sure: the card's top edge is not square"),
        ('refusing the read of the card it found', _EARLY_FRAME, _EARLY_BOX,
         'Card finder: read the card found above the box and refused it: no payout '
         'in the found card either')):
    # The card there from the first frame, so the first sample line is its
    # own: a blank mount's read asks the finder too and would spend the rate
    # limit. Run for a fixed time rather than to a read count — with no payout
    # the verify beat stops after that first round, and a count reached as
    # the round begins stops the loop before the round is digested.
    _fl = run(lambda n, k: '', real_look=(_EARLY_BOX, _found_text), offer=_frame,
              config_extra=_EARLY_CFG, seconds=8.0, appear_at=0.0)
    _sample = [l for l in _fl['logs'] if 'found nothing usable' in l]
    ok_('a read the card finder was asked about, %s, says why in the log\'s sample '
        'line (%r)' % (_what, (_sample or [None])[0]),
        _fl['finder'] > 0 and any(_said in l for l in _sample))
    eq('...and puts no payout in the journal',
       [x.get('pay') for x in _fl['rows'] if not x.get('kind')], [])

# --- the heat guard: the reads nobody pressed for, put off while the Pi is hot
#
# The owner reports the Pi 4 at 60-80°C on a shift and its soft limit hit, and
# the reads above add a whole-screen read every SCREEN_AUTO_EVERY while an order
# is held. At 75°C, or with any throttle word NOW, they are SCREEN_AUTO_HOT
# apart until the Pi is below 70 (scan_pi.HeatGuard); an offer, a ⌖ press and
# a 📷 Snap are read as they always were.
#
# The real loop and the real guard, handed the Pi's temperature by a fake
# source — this machine has no thermal zone — sampled every 0.1s on a 0.05s
# beat, so a change reaches the guard within a beat or two. And a tenth of the
# clock: SCREEN_AUTO_EVERY and SCREEN_AUTO_HOT run at 1s and 3s, so a run is
# seconds and not minutes. The card box sees the navigation screen on every
# half-second resample (the window held open for the run), which is a screen
# asking for the read at every chance — so how far apart the reads are asked
# for is the rate limit's doing and nothing else's.
_PiHealth = SP.PiHealth


def _heat_pi(schedule, made):
    """What run() builds in place of PiHealth(): the Pi at `schedule(t)` — (°C,
    the throttle words now) at t seconds after main() asked for it, which is
    put in `made` on the reads' own clock."""
    def build():
        t0 = time.time()
        made.append(t0)
        return _PiHealth(every=0.1,
                         temp=lambda: (schedule(time.time() - t0)[0], None),
                         throttle=lambda: ({'now': list(schedule(time.time() - t0)[1]),
                                            'sinceBoot': []}, None))
    return build


def _auto_reads(schedule, seconds):
    """The whole-screen reads nobody pressed for over a held order's navigation
    screen, at a tenth of the clock: when each was asked for, in seconds after
    the Pi was first asked, and the run.

    When it was ASKED FOR, which is the stamp of the card-box read that asked
    (`screen_auto_at` in main(), the clock the rate limit keeps) — the read
    handed over just before each whole-screen one, since the reader takes one
    at a time. Not when the whole-screen read itself went: that waits for the
    read that asked to be digested, and under load on this machine (six
    processes spinning beside it) two whole-screen reads went 2.23s apart with
    the limit at 3s — the first had waited 0.77s or more behind its asking."""
    ho, made = tempfile.mkdtemp(), []
    _hold(ho, time.time() + 3600)
    was = SP.SCREEN_AUTO_EVERY, SP.SCREEN_AUTO_HOT, SP.RESAMPLE_WINDOW
    SP.SCREEN_AUTO_EVERY, SP.SCREEN_AUTO_HOT, SP.RESAMPLE_WINDOW = 1.0, 3.0, seconds + 5.0
    try:
        got = run(lambda n, k: FRAG if n == 1 else _NAV_BOX, extra_argv=['--no-parallel'],
                  seconds=seconds, handoff=ho, whole_text=_NAV_WHOLE, alive_every=0.05,
                  health_every=2.0, pi=_heat_pi(schedule, made))
    finally:
        SP.SCREEN_AUTO_EVERY, SP.SCREEN_AUTO_HOT, SP.RESAMPLE_WINDOW = was
    t0 = made[0] if made else 0.0
    st = got['stamps']
    return [round(st[i - 1][0] - t0, 2) for i in range(1, len(st))
            if st[i][1] and not st[i - 1][1]], got


def _gaps(at):
    return [round(b - a, 2) for a, b in zip(at, at[1:])]


# 76°C for nine seconds, then 69.
_hot_until = 9.0
_ah, _rah = _auto_reads(lambda t: (76.0 if t < _hot_until else 69.0, []), 13.5)
_hot_gaps = [round(b - a, 2) for a, b in zip(_ah, _ah[1:]) if b < _hot_until]
_cool_gaps = [round(b - a, 2) for a, b in zip(_ah, _ah[1:]) if a > _hot_until + 0.3]
ok_('the premise: the card box asked at every chance, a read every half second '
    '(%d card-box reads in %.1fs)' % (_rah['submitted_whole'].count(False), 13.5),
    _rah['submitted_whole'].count(False) >= 20)
eq('at 76°C the automatic reads are 30 s apart (asked at %r s, a tenth of the clock: '
   'gaps %r)' % (_ah, _hot_gaps),
   (SP.SCREEN_AUTO_HOT, len(_hot_gaps) >= 2 and all(2.9 <= g <= 4.0 for g in _hot_gaps)),
   (30.0, True))
eq('below 70°C they are 10 s apart again (gaps %r)' % (_cool_gaps,),
   (SP.SCREEN_AUTO_EVERY, len(_cool_gaps) >= 2 and all(0.9 <= g < 2.0 for g in _cool_gaps)),
   (10.0, True))
# ...and the beat says which, from the same sample: the guard on the beats
# while the source said 76, off after it said 69.
_hb = [(b.get('pi') or {}).get('cpuC') for b in _rah['alive'] if b.get('heat_guard')]
_cb = [(b.get('pi') or {}).get('cpuC') for b in _rah['alive']
       if b.get('heat_guard') is False]
eq('...and the beat says the guard is on over the 76°C samples and off over the 69°C '
   'ones (%r on, %r off)' % (sorted(set(_hb)), sorted(set(_cb))),
   (sorted(set(_hb)), sorted(set(_cb))), ([76.0], [69.0]))
# ...and the journal is told nothing new. The `seen` row carries the Pi's four
# fields as it did, written here every two seconds with the guard on, and
# nothing of the guard's; no other row the run wrote does either.
_hseen = [x for x in _rah['rows'] if x.get('kind') == 'seen']
eq('...and the journal is told nothing new: a seen row written while the guard was '
   'on carries the Pi\'s four fields and none of the guard\'s (%d seen rows)' % len(_hseen),
   (bool(_hseen) and all(x.get('cpuC') == 76.0 for x in _hseen[:1]),
    [x.get('kind') for x in _rah['rows'] if 'heatGuard' in x or 'heat_guard' in x]),
   (True, []))

# Any throttle word NOW, at a temperature that would never turn it on alone.
_af, _raf = _auto_reads(lambda t: (50.0, ['throttled']), 10.0)
eq('a throttle flag now turns it on at any temperature (50°C, "throttled": gaps %r)'
   % (_gaps(_af),), len(_gaps(_af)) >= 2 and all(2.9 <= g <= 4.0 for g in _gaps(_af)), True)

# Never an offer, a ⌖ press or a 📷 Snap. The same run twice — the Pi at 90°C
# at its soft limit, and at 50°C with nothing to say — over a card that arrives
# a second in and is read as it lands (three reads, the third under 0.2s after
# the first on this machine) and again on the verify beat, at its ceiling,
# once the press's window has shut; a ⌖ press made in that third read, over a
# navigation screen with no address on it, so its window reads the whole
# screen until it shuts; and a snap asked for after the second. Compared run
# against run rather than against figures, so what is held is that the heat
# changes none of it.
#
# Reads before the card is in the mount see a blank screen: the stubbed reader
# would otherwise answer with the card on the very first frame (see the note
# at the top), and the burst and the beat would be timed from a card nobody
# had put there.
#
# The snap is asked from the loop's own thread, between two of its passes, as
# r14 above asks it. Asked from the reader's thread, while the loop was in
# snap_requested(), it was dropped as "stamped 0s ahead of the clock" in 2 of
# 4 runs with six processes spinning beside the suite: handoff.age read the
# clock before it stat'd the file, so a request written between the two read
# as a negative age. It stats first now, and test_handoff.py and
# test_scan_pi.py put a write between the two on demand; this run asks where
# it did so that what it measures is the heat and nothing else.
def _unslowed(schedule):
    ho, fold, made, asked, cams, card_reads = (tempfile.mkdtemp(), tempfile.mkdtemp(),
                                               [], [], [], [0])

    def texts(n, k):
        if not cams or cams[0].frame is not cams[0].offer:
            return ''
        if k == 0:
            card_reads[0] += 1
            if card_reads[0] == 3:
                open(os.path.join(ho, 'uberscan-dropoff'), 'w').close()
        return WHOLE

    def snap_at_the_second_read(rows, ann, calls):
        if not asked and card_reads[0] >= 2:
            asked.append((time.time(), _ask_snap(ho, fold)))
        return False

    got = run(texts, extra_argv=['--no-parallel'], seconds=8.5, handoff=ho, appear_at=1.0,
              cam_out=cams, dropoff_window=3.0, whole_text=_NAV_BOX, alive_every=0.05,
              pi=_heat_pi(schedule, made), until=snap_at_the_second_read)
    calls = [(t, whole) for t, whole in got['stamps']]
    # From the card's first read, which the burst and the beat are timed from.
    up = cams[0].started + cams[0].appear_at if cams else 0.0
    first = next((t for t, whole in calls if not whole and t >= up), 0.0)
    card = [round(t - first, 2) for t, whole in calls if not whole and t >= first]
    pressed = [round(t - first, 2) for t, whole in calls if whole]
    said = os.path.join(fold, 'reader.json')
    snap = (round(os.path.getmtime(said) - asked[0][0], 2)
            if asked and os.path.exists(said) else None)
    got['said'] = _json_or_none(said) or {}
    return card, pressed, snap, got


_uh = _unslowed(lambda t: (90.0, ['temp limit']))
_uc = _unslowed(lambda t: (50.0, []))
ok_('the premise: the guard was on through the hot run and off through the cool one',
    all(b.get('heat_guard') for b in _uh[3]['alive'])
    and not any(b.get('heat_guard') for b in _uc[3]['alive']))
ok_('the premise: the card was read three times before the press, the press read the '
    'whole screen until its window shut, and the verify beat came after it (cool: card '
    '%r, ⌖ %r)' % (_uc[0], _uc[1]),
    len(_uc[0]) >= 4 and len(_uc[1]) >= 4 and _uc[0][2] < _uc[1][0] < _uc[1][-1] < _uc[0][3])
# Every read of the card — the ones its arrival set off and the verify beat's,
# backed off to its ceiling, after the press — as many hot as cool and none
# later; and the press's reads as many, give or take the one a run's end can
# cut, the first no later.
_card_same = (len(_uc[0]) >= 4 and len(_uh[0]) >= len(_uc[0])
              and all(h <= c + 0.5 for h, c in zip(_uh[0], _uc[0])))
_press_same = (bool(_uh[1]) and bool(_uc[1]) and len(_uh[1]) >= len(_uc[1]) - 1
               and _uh[1][0] <= _uc[1][0] + 0.3)
eq('offer reads and ⌖ are never slowed (s after the card\'s first read; hot: card %r, '
   '⌖ %r; cool: card %r, ⌖ %r)' % (_uh[0], _uh[1], _uc[0], _uc[1]),
   (_card_same, _press_same), (True, True))
ok_('...nor a 📷 Snap, answered at once either way (hot %r s, cool %r s)'
    % (_uh[2], _uc[2]), _uh[2] is not None and _uc[2] is not None
    and _uh[2] <= _uc[2] + 0.3 and _uh[2] < 1.0)
# ...and the snap's reader.json says the guard was on, as the beat the panel
# was shown did: everything the panel was told, not all of it but one.
eq('...and its reader.json says the heat guard was on, as the panel was told',
   ((_uh[3]['said'].get('heartbeat') or {}).get('heatGuard', 'absent'),
    (_uc[3]['said'].get('heartbeat') or {}).get('heatGuard', 'absent')), (True, False))


# --- a card that showed its payout and no journey keeps its picture ----------
#
# A layout the parser has not seen yet — a new Uber card, the first DoorDash
# ones — reads as a payout and nothing it can use. The log quotes one such
# text at most every SAMPLE_EVERY seconds; the picture and the text go to
# scans/unparsed/, once per card.
_NEW_LAYOUT = '$7.25\nGuaranteed (incl. tip)\nNew order type: 2 stops'
r21 = run(lambda n, k: _NEW_LAYOUT, fitted=_crop, seconds=20.0,
          until=lambda rows, ann, calls: calls >= 5)
_ud = os.path.join(os.path.dirname(r21['config']), 'scans', SP.UNPARSED_DIR)
_ukept = sorted(os.listdir(_ud)) if os.path.isdir(_ud) else []
eq('a card with a payout and no journey keeps one picture and its text, '
   'however many times it was read (%d reads)' % r21['calls'],
   [n.rsplit('.', 1)[1] for n in _ukept], ['jpg', 'txt'])
ok_('...the text beside the picture, under the same name',
    len(_ukept) == 2 and _ukept[0].rsplit('.', 1)[0] == _ukept[1].rsplit('.', 1)[0])
eq('...and it is what the reader read',
   open(os.path.join(_ud, _ukept[1])).read() if len(_ukept) == 2 else None, _NEW_LAYOUT)

# ...and not off a ⌖ read, whose whole screen box holds a payout and a map.
# Every read here has a picture to keep, the whole-screen ones included.
_hou = tempfile.mkdtemp()
r22 = run(_press_on_first_read(_hou, WHOLE), extra_argv=['--no-parallel'], seconds=6.0,
          handoff=_hou, dropoff_window=1.0, whole_text=_NEW_LAYOUT,
          fitted_for=lambda n: _crop)
_ud22 = os.path.join(os.path.dirname(r22['config']), 'scans', SP.UNPARSED_DIR)
ok_('a ⌖ press was read whole', any(r22['wholes']))
eq('...and a ⌖ read keeps no unparsed picture',
   sorted(os.listdir(_ud22)) if os.path.isdir(_ud22) else [], [])

# --- a black crop left unread: an empty read, counted, said once ------------
#
# pipeline.DARK_SKIP_BELOW: a crop with nothing bright enough in it to be text
# is never handed to tesseract, which on 29 Oct spent 16-25s a read on a screen
# that was off. The loop must take one as the empty read it is — no offer, no
# verdict — count it on the health line as "dark: not read" and on the `seen`
# row as darkSkipped, and say it in the log once a DARK_SAY_EVERY, not per read.
_dk = run(lambda n, k: '', seconds=4.0, health_every=0.3,
          dark_for=lambda n, k: True,
          until=lambda rows, ann, calls: calls >= 3)
eq('reads of a black screen announce nothing', _dk['announced'], [])
_dk_said = [l for l in _dk['logs'] if l.startswith('screen too dark to read')]
eq('...are said once in the log over %d reads, not once a read (%r)'
   % (_dk['calls'], _dk_said[:1]), len(_dk_said), 1)
ok_('...and counted on the health line as "dark: not read" (%r)'
    % [l for l in _dk['logs'] if l.startswith('health over')][:1],
    any(l.startswith('health over') and 'dark: not read' in l for l in _dk['logs']))

# ...and the `seen` row, written for a window that saw a card, carries the
# count beside `reads` (nought here: the screen was lit). The count itself is
# Health's, held in test_scan_pi; a card read and then a black screen does not
# reach a second window here, because a read with no payout stops the verify
# beat and the still fake gives the motion gate nothing to send another.
_dk2 = run(lambda n, k: WHOLE, seconds=8.0, health_every=0.05,
           until=lambda rows, ann, calls: any(x.get('kind') == 'seen' for x in rows))
_dk2_seen = [x for x in _dk2['rows'] if x.get('kind') == 'seen']
eq('the `seen` row carries darkSkipped (%r)'
   % [(x.get('saw'), x.get('reads'), x.get('darkSkipped', 'absent')) for x in _dk2_seen],
   bool(_dk2_seen) and all(x.get('darkSkipped') == 0 for x in _dk2_seen), True)

# A ⌖ press's reads are never skipped: the driver asked. Every other read is
# handed over with the skip on.
_dkho = tempfile.mkdtemp()


def _press_then_card(n, k):
    if n == 1 and k == 0:
        open(os.path.join(_dkho, 'uberscan-dropoff'), 'w').close()
    return WHOLE


_dk3 = run(_press_then_card, seconds=8.0, handoff=_dkho, whole_text=_SNAP_NAV,
           until=lambda rows, ann, calls: calls >= 3)
eq('a ⌖ press\'s whole-screen reads go out with the dark skip off (%r)'
   % (_dk3['skip_darks'],),
   sorted(set(sd for w, sd in _dk3['skip_darks'] if w)), [False])
eq('...and the card-box reads with it on',
   sorted(set(sd for w, sd in _dk3['skip_darks'] if not w)), [True])

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d loop checks passed' % ok)
sys.exit(1 if bad else 0)
