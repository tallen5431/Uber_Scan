"""The reading engine, kept alive instead of spawned per read.

    python3 rpi/test_tesseract.py

Every read used to start a `tesseract` process, and a fresh process re-loads and
unpacks the LSTM model before it looks at a pixel. Measured on this machine that
was 81.8ms of a 129.1ms read — 63% — paid again on each of the four (median) to
fourteen (worst) reads merged into one stored offer. A whole read went from
187.1ms to 88.3ms when the engine stopped being thrown away.

The engine is the same library the binary is a wrapper around, so in principle
it reads identically. "In principle" is not good enough for the one component
between a camera and a number a driver acts on, so the first and largest check
here is the only one that really matters: over a spread of real card shapes, in
both page-segmentation modes, the two paths are compared row for row and have to
agree exactly.

The rest is about what happens when the library is not there, is the wrong
version, or breaks in the middle of a shift. Every one of those has to end with
the rig still reading, via the binary, having said so once.
"""

import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pipeline as PL                                         # noqa: E402
import testcards as TC                                        # noqa: E402

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


def skip(why):
    print('%s — skipping the engine checks' % why)
    sys.exit(0)


if not TC.available():
    skip('no test cards on this machine')


def prepped(frame):
    """The exact picture a read hands to the engine, or None."""
    quad = PL.detect_screen_quad(frame)
    if quad is None:
        return None
    fitted = PL.to_grey(PL.fit_for_ocr(PL.warp(frame, quad, 900), PL.OCR_CARD_HEIGHT))
    return PL.preprocess(fitted, dark=PL.is_dark_mode(fitted))


# Light and dark screens, four mount distances, and the three card layouts the
# parser knows about. The mount distance matters here: it decides how much
# upscaling fit_for_ocr does, which is the thing most likely to make two
# implementations of the same engine disagree.
CARDS = []
for _pal, _name in ((TC.LIGHT, 'light'), (TC.DARK, 'dark')):
    for _w in (380, 460, 520, 620):
        CARDS.append(('uberx %s w%d' % (_name, _w),
                      TC.mount(TC.uberx_screen(pal=_pal), width=_w)))
    CARDS.append(('shop %s' % _name, TC.mount(TC.shop_screen(pal=_pal), width=500)))
    CARDS.append(('doordash %s' % _name,
                  TC.mount(TC.doordash_screen(pal=_pal), width=500)))

if not PL._tess_lib():
    skip('no libtesseract on this machine')

# --- the one that matters: the two paths read the same card the same way ----
import pytesseract                                            # noqa: E402

compared = 0
for name, frame in CARDS:
    image = prepped(frame)
    ok_('%s gives the reader a picture' % name, image is not None)
    if image is None:
        continue
    for label, config in (('psm 6', PL.OCR_CONFIG), ('psm 4', PL.RECOVER_CONFIG)):
        kept = PL._in_process(image, config, tsv=True)
        ok_('%s / %s: the library answered' % (name, label), kept is not None)
        if kept is None:
            continue
        # Blank rows are the two writers' own habits, not a reading.
        mine = [r for r in kept.splitlines() if r.strip()]
        theirs = [r for r in pytesseract.image_to_data(
            PL.stage_for_ocr(image), config=config).splitlines()[1:] if r.strip()]
        eq('%s / %s: same number of words' % (name, label), len(mine), len(theirs))
        eq('%s / %s: the same table, row for row' % (name, label), mine, theirs)
        compared += 1

ok_('every card was compared both ways', compared == len(CARDS) * 2)

# ...and the header line, which is the one shape difference between them. The
# binary writes one and the library does not; tsv_rows() is where that is dealt
# with, and a caller must never see it.
image = prepped(CARDS[0][1])
rows = PL.tsv_rows(image, PL.OCR_CONFIG)
ok_('the rows carry no header', not rows[0].startswith('level\t'))
ok_('...and are the per-word table', rows[0].split('\t')[0] == '1')

# --- the engine is kept, which is the entire point --------------------------
before = len(PL._TESS_OPEN)
for _ in range(4):
    PL._in_process(image, PL.OCR_CONFIG, tsv=True)
eq('four reads build no further engines', len(PL._TESS_OPEN), before)

# The psm-4 retry runs on the same engine as the read it is retrying — it is a
# page-segmentation mode, set per call, not a different engine. Building a
# second one would double both the startup this exists to avoid and the memory.
PL._in_process(image, PL.RECOVER_CONFIG, tsv=True)
eq('the retry shares the engine', len(PL._TESS_OPEN), before)

# A thread of its own gets an engine of its own, because a TessBaseAPI cannot be
# shared and look_many runs two reads at once.
seen = {}


def read_on_a_thread():
    seen['out'] = PL._in_process(image, PL.OCR_CONFIG, tsv=True)
    seen['engines'] = len(PL._TESS_OPEN)


t = threading.Thread(target=read_on_a_thread)
t.start()
t.join()
ok_('a second thread reads', bool(seen.get('out')))
eq('...on an engine of its own', seen.get('engines'), before + 1)
eq('...and reads the same card the same way', seen['out'],
   PL._in_process(image, PL.OCR_CONFIG, tsv=True))

# --- a paired read reuses its threads, and therefore its engines ------------
#
# The defect this is here for: look_many built a ThreadPoolExecutor per call and
# shut it down at the end, which cost nothing when a read spawned a process and
# everything once the engine belongs to the thread. Six paired reads left twelve
# engines behind and took RSS from 151MB to 286MB, climbing for the whole shift.
paired = PL.Scanner(quad=PL.detect_screen_quad(CARDS[0][1]))
PL._close_engines()
PL._TESS_LOCAL.engines = {}
paired.read_many([CARDS[0][1], CARDS[0][1]])
after_one = len(PL._TESS_OPEN)
ok_('a paired read builds an engine per reader', after_one <= 2)
for _ in range(5):
    paired.read_many([CARDS[0][1], CARDS[0][1]])
eq('...and five more build no others', len(PL._TESS_OPEN), after_one)

# And the backstop under it, for any caller that threads differently than this
# one does. The cost of hitting it is a slow read; the cost of not having it is
# a rig that runs out of memory mid-shift.
ok_('there is a ceiling on engines at all', PL.MAX_ENGINES >= 2)
held = PL._TESS_OPEN[:]
try:
    # Stand the count at the ceiling without building anything real.
    PL._TESS_OPEN[:] = held + [None] * (PL.MAX_ENGINES - len(held))
    hit = {}

    def read_past_the_cap():
        PL._TESS_LOCAL.engines = {}
        hit['out'] = PL._in_process(image, PL.OCR_CONFIG, tsv=True)
        hit['rows'] = PL.tsv_rows(image, PL.OCR_CONFIG)

    capped = threading.Thread(target=read_past_the_cap)
    capped.start()
    capped.join()
    eq('a thread past the ceiling builds no engine', hit.get('out'), None)
    ok_('...and reads on the binary instead', len(hit.get('rows') or []) > 5)
finally:
    PL._TESS_OPEN[:] = held

# --- and every way it can go wrong ends with the rig still reading -----------
#
# A command line this does not understand is handed to the binary rather than
# guessed at. Dropping a flag silently would read the card under settings nobody
# asked for, which is exactly the kind of difference that becomes a wrong number.
eq('a plain config is understood', PL._tess_config('--oem 1 --psm 6'), (1, 6, ()))
eq('...variables too', PL._tess_config('--oem 1 --psm 6 -c tessedit_do_invert=0'),
   (1, 6, (('tessedit_do_invert', '0'),)))
eq('the shipped read config is understood', PL._tess_config(PL.OCR_CONFIG)[1], 6)
eq('...and the retry', PL._tess_config(PL.RECOVER_CONFIG)[1], 4)
eq('an unknown flag is refused', PL._tess_config('--oem 1 --psm 6 --nonsense'), None)
eq('...and a word list, which needs a file the library is not given',
   PL._tess_config('--user-words /tmp/words'), None)
eq('...and a flag with nothing after it', PL._tess_config('--psm'), None)
eq('...and a psm that is not a number', PL._tess_config('--psm six'), None)

# A config the shim refuses still reads, on the binary. `--dpi` is a real flag
# the binary takes and this does not pass on, which is the honest version of
# this case — a made-up flag would fail on both paths and prove nothing.
text = PL.ocr(image, PL.OCR_CONFIG)
ok_('an understood config reads the card', 'min' in text and 'trip' in text)
ok_('...through the library', PL._in_process(image, PL.OCR_CONFIG, tsv=False) is not None)
eq('--dpi is not a flag this passes on', PL._tess_config(PL.OCR_CONFIG + ' --dpi 300'), None)
rows_odd = PL.tsv_rows(image, PL.OCR_CONFIG + ' --dpi 300')
ok_('...so the binary reads that one', len(rows_odd) > 5)

# An engine that throws mid-shift is dropped and the library given up on, rather
# than the read being lost. This is the case that must not take the rig down.
real_lib, real_said = PL._TESS_LIB, PL._TESS_SAID


class Exploding:
    """A library that binds fine and fails when actually used."""

    def __getattr__(self, name):
        if name == 'TessBaseAPICreate':
            def boom(*a):
                raise RuntimeError('the engine fell over')
            return boom
        return getattr(real_lib, name)


def hands_back(name, fn):
    """A call that must give the read up, not raise.

    Spelled out rather than written as eq(fn(), None), because the failure this
    is about *is* an exception: an assertion that lets it through reports a
    traceback instead of a failed check, and a traceback is not a result.
    """
    try:
        eq(name, fn(), None)
    except BaseException as e:
        eq(name, 'raised %s: %s' % (e.__class__.__name__, e), None)


try:
    PL._TESS_LIB = Exploding()
    PL._TESS_LOCAL.engines = {}
    PL._TESS_SAID = True                     # the message is not what is tested
    hands_back('an engine that will not start hands the read back',
               lambda: PL._in_process(image, PL.OCR_CONFIG, tsv=True))
    broken = PL.tsv_rows(image, PL.OCR_CONFIG)
    ok_('...and the card is still read, by the binary', len(broken) > 5)
    # The journey rather than the payout: at this mount distance psm 6 loses
    # the money on this card, which is the failure RECOVER_CONFIG exists for
    # and not the one being tested here.
    ok_('...with the card still on it',
        'trip' in ' '.join(r.split('\t')[-1] for r in broken))
finally:
    PL._TESS_LIB, PL._TESS_SAID = real_lib, real_said
    PL._TESS_LOCAL.engines = {}

# The way back without a code change, in the same spirit as --no-thread.
was = os.environ.get('UBERSCAN_TESSERACT')
try:
    os.environ['UBERSCAN_TESSERACT'] = 'binary'
    PL._TESS_LIB = None
    PL._TESS_SAID = True
    eq('UBERSCAN_TESSERACT=binary refuses the library', PL._tess_lib(), False)
    off = PL.tsv_rows(image, PL.OCR_CONFIG)
    ok_('...and the rig reads exactly as it did before', len(off) > 5)
finally:
    if was is None:
        os.environ.pop('UBERSCAN_TESSERACT', None)
    else:
        os.environ['UBERSCAN_TESSERACT'] = was
    PL._TESS_LIB, PL._TESS_SAID = real_lib, real_said

# Closing is not optional: without TessBaseAPIEnd the library prints a wall of
# "LEAK! object still has count 1" as the process exits, which would be the last
# thing in a log somebody pastes back.
PL._close_engines()
eq('closing releases every engine', len(PL._TESS_OPEN), 0)
ok_('...and reading afterwards still works',
    len(PL.tsv_rows(image, PL.OCR_CONFIG)) > 5)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d engine checks passed' % ok)
sys.exit(1 if bad else 0)
