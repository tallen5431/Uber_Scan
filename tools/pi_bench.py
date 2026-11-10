#!/usr/bin/env python3
"""Time the reads the rig makes, on the rig, off screens rendered here.

    python3 tools/pi_bench.py              # 5 of each, under ~3 min on a Pi 4
    python3 tools/pi_bench.py --n 3        # fewer
    python3 tools/pi_bench.py --json       # the same, as one JSON object
    python3 tools/pi_bench.py --busy       # paired reads with the rig's other
                                           # work beside them (service STOPPED;
                                           # see "busy" below), ~2.5 min

Every figure this project has printed for what a read costs ON THE PI has
been an estimate or a number off the development box: unsure_payout's "about
1.5-2 s on the Pi (an ESTIMATE, from the read times the rig logs)", the raise's
"+4559ms median" read off the owner's health line, the spare threads' "407ms
median before, 259 after" measured on x86. A Pi 4 is a different machine (four
A72 cores, a firmware that slows them when hot), and nothing measured the
reads themselves there, one kind at a time. This does, on the screens
rpi/testcards.py draws — invented cards, no owner's data, no camera:

  uber card          UberX's card through the centred box, as most reads are;
  dd rescue, evened  DoorDash's stops card in a left-hand shadow through a box
                     drawn round an Uber card: the box's read, the finder, the
                     found sheet's read (no payout in the shade) and its
                     second read with the light evened out (PL.even_light);
  dd rescue, raised  the same card under another on one sheet, through the
                     box that cuts its payout: the box, the finder's sheet
                     refused (two dollar figures), the box raised (RAISE_STEPS);
  dd next read       that card's next read once a rescue taught the crop: one
                     read, through the remembered crop (PL.CARD_BOX_FOR);
  planner, whole     Uber's Trip Planner, read across the whole screen box as
                     a ⌖ press reads it;
  map label          DoorDash's map label off the band above the card
                     (scan_pi.read_map_label, capped as the rig caps it).

each N times with the spare threads on (PL.spare_cores: the rescue's next
link started early on an idle core) and off, and prints the median and p90
in milliseconds, how many reads gave the card's own answer, and the CPU's
temperature and throttle flags before and after. One frame per read (the
loop reads pairs: a pair costs less than two of these, see read_many).

SAFE BESIDE THE SCANNER. It opens no camera, writes no file, posts nothing
and touches no handoff file; it runs at niceness 10 (the spare threads'
own), so with the service running the camera loop keeps its cores and these
figures come out slower — the line under the table says whether
uberscan.service was active. A time budget (--budget, default 150 s for the
timed reads) stops each cell early, after at least one read, so the whole
run stays under three minutes on a Pi 4 whatever N says; `n` in the table is
how many were taken.
"""

import argparse
import itertools
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import tempfile
import sys
import time

# One thread per tesseract, as scan_pi sets it for the real rig: two engines
# fight over a Pi's four cores without it (tools/test.sh says how badly).
# Before the engine is loaded, which importing pipeline does not do yet.
os.environ.setdefault('OMP_THREAD_LIMIT', '1')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'rpi'))

import cv2                             # noqa: E402
import numpy as np                     # noqa: E402

import offer_parser as OP              # noqa: E402
import pipeline as PL                  # noqa: E402
import scan_pi as SP                   # noqa: E402
import testcards as TC                 # noqa: E402

WIDTH = 680                  # the screen's width in the sensor frame, px
NICE = 10                    # the spare threads' niceness (PL._SPARE_NICE)
# A card stacked above DoorDash's on one sheet, no button of its own and a
# larger payout (test_pipeline's): the finder's walk takes both, its read is
# refused for two figures, and the box is raised.
UPPER = (762, [(782, 'Order in progress', 34, False), (872, '$22.75', 86, True)])


def quad(width=WIDTH):
    return np.array(TC.screen_corners(width), np.float32)


def scanner(box=None, finder=True):
    if box is None:
        return PL.Scanner(quad=quad())
    return PL.Scanner(quad=quad(), roi=list(box), card_share=box[3], card_finder=finder)


def frame(screen, seed=1):
    """The screen as the camera hands it over: one sensor frame, read again
    and again, so every read of a kind does the same work and the spread is
    the machine's own (tesseract gives one image one answer)."""
    return TC.mount(screen, WIDTH, seed=seed)


def cases():
    """[(name, once)]: `once()` makes one read and says whether it gave the
    card's own answer. Every frame is rendered, and the remembered crop
    taught, here, before any clock runs."""
    out = []

    uber = frame(TC.uberx_screen())
    s_uber = scanner()
    out.append(('uber card, centred box',
                lambda: abs((s_uber.read(uber)['parsed']['pay'] or 0) - 16.05) < 0.005))

    # A fresh Scanner per read: one that remembered the rescue's crop would
    # read it first and never rescue again (that is the next case but one).
    # Seed 2 at 680px is the frame test_pipeline holds to this chain.
    shade = frame(TC.degrade(TC.dd_stores_screen(), 'shadow'), seed=2)

    def evened():
        o = scanner(TC.BOX_DD_BELOW).read(shade)
        return o['parsed']['pay'] == 14.1 and o['rescuedBy'] == 'finder'
    out.append(('dd rescue: finder, evened read', evened))

    stacked = frame(TC.dd_stores_screen(upper=UPPER))

    def raised():
        o = scanner(TC.BOX_DD_PAY).read(stacked)
        return o['parsed']['pay'] == 14.1 and o['rescuedBy'] == 'raised'
    out.append(('dd rescue: refused, raised', raised))

    # Taught once, untimed, then read through the crop it remembered. Its
    # clock held still so the memory never ages out (CARD_BOX_FOR, 15 s)
    # between reads however slow the machine is.
    dd = frame(TC.dd_stores_screen(), seed=2)
    s_dd = scanner(TC.BOX_DD_BELOW)
    s_dd.clock = lambda: 0.0
    s_dd.read(frame(TC.dd_stores_screen(), seed=3))

    def remembered():
        o = s_dd.read(dd)
        return o['parsed']['pay'] == 14.1 and o.get('cardBox') == 'kept'
    out.append(('dd next read: remembered crop', remembered))

    plan = frame(TC.planner_screen())
    s_plan = scanner()

    def planner():
        g = s_plan.geometry(whole=True, skip_dark=False)
        o = s_plan.settle([s_plan._look(plan, None, g)], g)[0]
        return bool(OP.find_planner(o.get('text') or ''))
    out.append(('planner, whole screen (⌖)', planner))

    label = frame(TC.dd_stores_screen())
    g_label = scanner(TC.BOX_DD_BELOW).geometry()

    def map_label():
        got = SP.read_map_label(label, g_label)
        return bool(got) and '1256' in (got.get('line') or '')
    out.append(('map label', map_label))
    return out


def p90(ms):
    """Nearest rank: with fewer than ten reads, the slowest."""
    s = sorted(ms)
    return s[max(0, int(math.ceil(0.9 * len(s))) - 1)]


def heat():
    """{'cpuC', 'from', 'throttled', 'why'}: the temperature off vcgencmd where
    there is one, else the kernel's thermal zone (scan_pi.cpu_temp), and the
    throttle flags as the rig words them (scan_pi.throttling)."""
    cpu, src = None, None
    try:
        done = subprocess.run(['vcgencmd', 'measure_temp'], capture_output=True,
                              text=True, timeout=1.0)
        m = re.search(r"temp=([0-9.]+)", done.stdout or '')
        if done.returncode == 0 and m:
            cpu, src = float(m.group(1)), 'vcgencmd'
    except (OSError, subprocess.SubprocessError):
        pass
    if cpu is None:
        cpu, why = SP.cpu_temp()
        src = 'thermal zone' if cpu is not None else why
    flags, why = SP.throttling()
    return {'cpuC': cpu, 'from': src, 'throttled': flags, 'why': why}


def heat_line(h):
    t = ('%.1f°C (%s)' % (h['cpuC'], h['from'])) if h['cpuC'] is not None \
        else 'no temperature (%s)' % h['from']
    if h['throttled'] is None:
        return t + ', throttled: unknown (%s)' % h['why']
    return t + ', throttled now: %s, since boot: %s' % (
        ', '.join(h['throttled']['now']) or 'none',
        ', '.join(h['throttled']['sinceBoot']) or 'none')


def service_active():
    try:
        done = subprocess.run(['systemctl', 'is-active', 'uberscan.service'],
                              capture_output=True, text=True, timeout=2.0)
        return (done.stdout or '').strip() == 'active'
    except (OSError, subprocess.SubprocessError):
        return None


def run(n, budget):
    began = time.monotonic()
    before = heat()
    warm = time.monotonic()
    todo = cases()
    # One read of each engine before any clock: the main thread's tesseract
    # (the teaching read in cases() loaded it), and with the spares on,
    # theirs — each thread loads its own model, and the first rescue with
    # them on would otherwise carry two model loads.
    PL.spare_cores(True)
    todo[1][1]()
    warm_s = time.monotonic() - warm
    cell_s = budget / float(len(todo) * 2)
    rows = []
    for name, once in todo:
        row = {'read': name}
        for spare in (True, False):
            PL.spare_cores(spare)
            ms, ok, spent = [], 0, 0.0
            for _ in range(n):
                if ms and spent > cell_s:
                    break
                t = time.perf_counter()
                good = once()
                took = (time.perf_counter() - t) * 1000.0
                ms.append(took)
                spent += took / 1000.0
                ok += bool(good)
            row['on' if spare else 'off'] = {
                'n': len(ms), 'median': round(statistics.median(ms)),
                'p90': round(p90(ms)), 'ok': ok}
        rows.append(row)
    PL.spare_cores(True)
    return {'n': n, 'budgetS': budget, 'nice': os.nice(0), 'service': service_active(),
            'before': before, 'after': heat(), 'warmS': round(warm_s, 1),
            'rows': rows, 'tookS': round(time.monotonic() - began, 1)}


def table(res):
    lines = ['pi_bench: up to %d reads of each, spare threads on and off, nice %d, '
             'ms per read (p90: nearest rank)' % (res['n'], res['nice'])]
    lines.append('before: ' + heat_line(res['before']))
    w = max(len(r['read']) for r in res['rows'])
    lines.append('%-*s  %23s  %23s' % (w, '', 'spare threads on', 'spare threads off'))
    lines.append('%-*s  %3s %7s %6s %4s  %3s %7s %6s %4s'
                 % (w, 'read', 'n', 'median', 'p90', 'ok', 'n', 'median', 'p90', 'ok'))
    for r in res['rows']:
        cells = []
        for k in ('on', 'off'):
            c = r[k]
            cells.append('%3d %7d %6d %4s' % (c['n'], c['median'], c['p90'],
                                              '%d/%d' % (c['ok'], c['n'])))
        lines.append('%-*s  %s  %s' % (w, r['read'], cells[0], cells[1]))
    lines.append('after:  ' + heat_line(res['after']))
    svc = {True: 'running (these reads shared the cores with it)',
           False: 'not running', None: 'unknown (no systemctl)'}[res['service']]
    lines.append('uberscan.service %s; screens drawn and engines warmed in %.1f s; took %.1f s'
                 % (svc, res['warmS'], res['tookS']))
    return '\n'.join(lines)


# --- busy: the reads with the rest of the rig running beside them ------------
#
# THE GAP THE TABLE ABOVE CANNOT SHOW. On the owner's Pi 4 (cooler on, never
# throttled; 931c50c) this bench, the service stopped, read an Uber card in
# 392 ms median; the 9 Nov shift's health lines, on the same build, put the
# read itself (`time: ... read`, the reader's own clock less the warp) at
# 979-1526 ms median, with the process at 120-169% of a core and a load of
# 2.1-5.3 on four. The read is the same function on the same kind of card;
# what differs is everything else the rig runs while it reads: the paired
# frame's own engine, the rescue's links started ahead on the spare cores,
# DoorDash's map label asked every 2 s while its card is up (each ask a warp
# of the sensor frame and up to three OCRs), the map band cut and encoded
# once an offer, and the camera loop itself — 30 frames a second, the motion
# gate, and the live view composed and JPEG-encoded at up to 30 a second.
#
# So `--busy` runs that, with the real classes off scan_pi, on rendered
# frames — no camera, no owner's data — and times the reads as the rig's
# health line does (ReadTimes, the same stages), beside a stand-in for the
# camera loop whose every tick is timed too:
#
#   the loop     every 33 ms: the preview's luma copied and put through the
#                real motion gate (PL.Scanner.should_read), the live view
#                composed and encoded by the real write_snapshot (the scene
#                view at 30/s off the preview, or with --view screen the
#                phone view at 15/s off the sensor frame), the finished read
#                taken and settled, and a new paired read handed over the
#                moment the reader is free — a card up whose reads never let
#                the reader rest, which the shift's `held` (74-529 ms median)
#                says is how the reader spent a card;
#   the cards    an Uber card through the centred box for EPISODE_S[0], then
#                DoorDash's stops card through the box that cuts its payout
#                for EPISODE_S[1] — a new offer each, so its first read is
#                rescued (the finder started ahead on the spare cores) and
#                the rest go through the remembered crop, as on the rig;
#   the label    scan_pi.MapLabels asked after every DoorDash read, as the
#                loop asks it, with the label's own text given as a store's
#                so it is never found: every ask MAP_LABEL_AGAIN_S apart is
#                read, the worst case (the overview map, then a label that
#                will not read) the 20-try cap allows;
#   the band     scan_pi.MapBands once per offer, into a temporary folder
#                removed afterwards.
#
# Each of those can be switched off (--no-label, --no-band, --no-spare,
# --no-pair, --view none) to see what it costs the read. The figures are the
# machine's own: on x86 they say which way a change moves the read, not what
# a Pi will print; tools/pi_bench.py --busy on the Pi is that measurement.
BUSY_S = 40.0
TICK_S = 1 / 30.0               # the camera's frame interval
EPISODE_S = (8.0, 12.0)         # an Uber card, then a DoorDash card
LORES = SP.LORES
LABEL_TEXT = '1256 Maple Run Ln NW'   # testcards' label: given as a store, never found


def busy_frames():
    """{kind: [(sensor frame, preview luma)]}: four sensor frames of each card,
    different noise each (the pair is two frames, not one twice), and the
    preview stream's luma of each, as the camera hands over both."""
    out = {}
    for kind, screen in (('uber', TC.uberx_screen()), ('dd', TC.dd_stores_screen())):
        got = []
        for seed in (2, 3, 4, 5):
            f = frame(screen, seed=seed)
            luma = cv2.cvtColor(cv2.resize(f, LORES, interpolation=cv2.INTER_AREA),
                                cv2.COLOR_BGR2GRAY)
            got.append((f, luma))
        out[kind] = got
    return out


_THREADS = []
_OFFERS = itertools.count(1)


def _threads():
    """(Reader, MapLabels), the same pair for every run of this process."""
    if not _THREADS:
        _THREADS.extend([SP.Reader(PL.Scanner(), threaded=True), SP.MapLabels(threaded=True)])
    return _THREADS[0], _THREADS[1]


def busy_run(frames, seconds, view='scene', label=True, band=True, spare=True,
             pair=True, slots=None, episodes=EPISODE_S, label_below=None,
             clock=time.monotonic):
    """One busy run (see above): {'reads': [...], 'ticks': [...], ...}."""
    want = {'uber': 16.05, 'dd': 14.1}
    q = quad()
    scale = (TC.SENSOR[1] / float(LORES[0]), TC.SENSOR[0] / float(LORES[1]))
    scanners = {'uber': scanner(), 'dd': scanner(TC.BOX_DD_BELOW)}
    gate = scanner()
    cfg = {'quad': q.tolist(), 'cardHeight': 900}
    PL.spare_cores(spare)
    slots_was = PL.ocr_slots(PL.OCR_SLOTS if slots is None else int(slots)) \
        if hasattr(PL, 'ocr_slots') else None
    below_was = PL.ocr_label_below(label_below) if hasattr(PL, 'ocr_label_below') else None
    if slots_was is not None:
        PL.ocr_slot_waits(reset=True)
    tmp = tempfile.mkdtemp(prefix='pi_bench-')
    snap = os.path.join(tmp, 'snapshot.jpg')
    # The reader's thread and the label's are made once and kept (_threads):
    # an engine belongs to its thread, and a thread a run would be an engine
    # a run — past PL.MAX_ENGINES the reads go to the binary, a model load
    # each, and the figures would be the binary's.
    reader, labels = _threads()
    reader.scanner = scanners['uber']
    label_reads0 = labels.reads
    bands = SP.MapBands(os.path.join(tmp, 'mapbands'), threaded=True) if band else None
    reads, ticks, late = [], [], 0
    offers = 0
    kind, offer, episode_end = None, None, 0.0
    i = 0
    cpu0 = time.process_time()
    began = clock()
    end = began + seconds
    next_tick = began
    try:
        while True:
            now = clock()
            if now >= end and not reader.busy:
                break
            if now < next_tick:
                time.sleep(next_tick - now)
                now = clock()
            # A tick is late when it began a whole frame after it was due:
            # the camera's frame it was for had gone.
            if now - next_tick > TICK_S:
                late += 1
            next_tick = max(next_tick + TICK_S, now - TICK_S)
            t0 = clock()
            done = reader.take()
            if done is not None:
                taken = clock()
                outs = done.get('outs') or []
                clock_ = done.get('clock') or {}
                for k, out in enumerate(outs):
                    ms = out.get('ms') or {}
                    reads.append({
                        'kind': clock_['kind'], 'frame': k,
                        'queue': ((clock_['started'] - clock_['submitted'])
                                  + (taken - clock_['ended'])) * 1000.0,
                        'pair': clock_.get('pair'),
                        'age': (clock_['started'] - clock_['frameAt']) * 1000.0,
                        'warp': ms.get('warp'),
                        'read': ms.get('total', 0) - ms.get('warp', 0),
                        'slot': ms.get('slot'), 'find': ms.get('find'),
                        'prep': ms.get('prep'), 'ocr': ms.get('ocr'),
                        'wall': (clock_['ended'] - clock_['started']) * 1000.0,
                        'ok': abs((out['parsed'].get('pay') or 0) - want[clock_['kind']]) < 0.005,
                        'pay': out['parsed'].get('pay'),
                        # A payout off a crop above the box found by this
                        # read's own chain, not the remembered crop.
                        'rescue': (out.get('cropFrom') == 'found'
                                   and out.get('cardBox') != 'kept'),
                        'overlapped': bool(clock_.get('labelling') or labels.reading
                                           or labels.reads != clock_.get('labels'))})
                if outs and clock_['kind'] == 'dd' and label:
                    labels.submit(clock_['offer'], done['frames'][0], done['geom'],
                                  store=[LABEL_TEXT])
                if outs and bands is not None:
                    bands.submit(clock_['offer'], done['frames'][0], done['geom'],
                                 {'v': 1, 'offerId': clock_['offer'], 'geom': {}})
            # The card on screen: a new offer when the last one's time is up
            # and its read is in (the Scanner a read was handed is the one
            # that settles it).
            if now >= episode_end and now < end and not reader.busy:
                kind = 'dd' if kind == 'uber' else 'uber'
                offers += 1
                offer = 'bench-%d' % next(_OFFERS)
                episode_end = now + episodes[kind == 'dd']
                reader.scanner = scanners[kind]
                scanners[kind].forget_card_box('a new offer')
            f, luma = frames[kind][i % len(frames[kind])]
            i += 1
            labels.take()
            gate.should_read(luma.copy(), scale)
            if view == 'scene':
                SP.write_snapshot(luma.copy(), cfg, snap, quad=q, roi=scanners[kind].crop_box,
                                  scale=scale, view=SP.VIEW_SCENE)
            elif view == 'screen' and i % 2 == 0:
                SP.write_snapshot(f.copy(), cfg, snap, quad=q, roi=scanners[kind].crop_box,
                                  view=SP.VIEW_SCREEN)
            if not reader.busy and now < end:
                p0 = clock()
                batch = [f.copy()]
                if pair:
                    batch.append(frames[kind][i % len(frames[kind])][0].copy())
                geom = scanners[kind].geometry()
                # (The card and the offer ride in `meta`, which the reader
                # hands back as the read's `clock`.)
                meta = {'frameAt': t0, 'pair': (clock() - p0) * 1000.0 if pair else None,
                        'labels': labels.reads, 'labelling': labels.reading,
                        'kind': kind, 'offer': offer}
                reader.submit(batch, time.time(), geom, meta=meta)
            ticks.append((clock() - t0) * 1000.0)
    finally:
        # (Not closed: kept for the next run, see _threads. A read still in
        # flight was waited for above.)
        if bands is not None:
            bands.close()
        if slots_was is not None:
            PL.ocr_slots(slots_was)
        if below_was is not None:
            PL.ocr_label_below(below_was)
        PL.spare_cores(True)
        shutil.rmtree(tmp, ignore_errors=True)
    took = clock() - began
    waits = PL.ocr_slot_waits(reset=True) if slots_was is not None else None
    return {'reads': reads, 'ticks': ticks, 'late': late, 'offers': offers, 'slots': waits,
            'labelReads': labels.reads - label_reads0, 'seconds': round(took, 1),
            'cpuPct': int(round((time.process_time() - cpu0) / took * 100)),
            'load1': SP.load_average()}


def _med(values):
    v = sorted(x for x in values if x is not None)
    return int(round(v[len(v) // 2])) if v else None


def busy_summary(r):
    """One busy run's figures: the read per card kind, the health line's
    `time:` stages the harness can see, the loop's tick, the gate."""
    reads = r['reads']
    out = {'seconds': r['seconds'], 'offers': r['offers'], 'labelReads': r['labelReads'],
           'cpuPct': r['cpuPct'], 'load1': r['load1'], 'kinds': {}}
    for kind in ('uber', 'dd'):
        rr = [x for x in reads if x['kind'] == kind]
        ms = [x['read'] for x in rr]
        out['kinds'][kind] = {'n': len(rr), 'median': _med(ms), 'p90': round(p90(ms)) if ms else None,
                              'ok': sum(x['ok'] for x in rr)}
    out['time'] = dict((k, _med([x[k] for x in reads]))
                       for k in ('queue', 'pair', 'age', 'warp', 'read', 'slot'))
    t = r['ticks']
    out['tick'] = {'n': len(t), 'median': round(statistics.median(t), 1) if t else None,
                   'p95': round(sorted(t)[int(0.95 * (len(t) - 1))], 1) if t else None,
                   'max': round(max(t), 1) if t else None, 'late': r['late']}
    g = r.get('slots') or {}
    spent = g.get('spent') or {}
    total = sum(spent.values()) or 1.0
    out['engines'] = dict(('%d' % k, round(100.0 * v / total)) for k, v in sorted(spent.items()))
    out['waited'] = dict((role, {'asks': (g.get(role) or {}).get('asks', 0),
                                 'waited': len((g.get(role) or {}).get('waited') or []),
                                 'median': _med((g.get(role) or {}).get('waited') or [])})
                         for role in getattr(PL, 'SLOT_ROLES', ()))
    out['stopped'] = g.get('stopped', 0)
    return out


def busy(seconds, slots, view='scene', label=True, band=True, spare=True, pair=True):
    """The three runs `--busy` prints: the paired reads alone, then with the
    rig's concurrent work beside them with the engines' gate off (as the rig
    was before it) and on, `slots` engines."""
    began = time.monotonic()
    frames = busy_frames()
    # Every engine loaded before any clock, the spares' and the label's too.
    busy_run(frames, 3.0, view='none', label=label, band=False, spare=spare, pair=pair, slots=0)
    warm_s = time.monotonic() - began
    runs = []
    for name, kw in (('alone', dict(view='none', label=False, band=False, slots=0)),
                     ('busy, ocr slots off', dict(view=view, label=label, band=band, slots=0)),
                     ('busy, ocr slots %d' % slots, dict(view=view, label=label, band=band,
                                                         slots=slots))):
        got = busy_summary(busy_run(frames, seconds, spare=spare, pair=pair, **kw))
        got['run'] = name
        got['slots'] = kw['slots']
        runs.append(got)
    return {'busy': True, 'secondsEach': seconds, 'view': view, 'label': label, 'band': band,
            'spare': spare, 'pair': pair, 'nice': os.nice(0), 'service': service_active(),
            'warmS': round(warm_s, 1), 'runs': runs, 'tookS': round(time.monotonic() - began, 1)}


def busy_table(res):
    lines = ['pi_bench --busy: %d s each, ms; the reads paired and taken back to back, the '
             'live view %s, map label %s, map band %s, spare threads %s'
             % (res['secondsEach'], res['view'], 'on' if res['label'] else 'off',
                'on' if res['band'] else 'off', 'on' if res['spare'] else 'off')]
    w = max(len(r['run']) for r in res['runs'])
    lines.append('%-*s  %-21s %-21s  %s' % (w, '', 'Uber card read', 'DoorDash card read',
                                           'camera loop tick'))
    lines.append('%-*s  %3s %6s %5s %4s  %3s %6s %5s %4s  %6s %5s %5s %4s'
                 % (w, 'run', 'n', 'median', 'p90', 'ok', 'n', 'median', 'p90', 'ok',
                    'median', 'p95', 'max', 'late'))
    for r in res['runs']:
        cells = []
        for kind in ('uber', 'dd'):
            c = r['kinds'][kind]
            cells.append('%3d %6s %5s %4s' % (c['n'], c['median'] if c['median'] is not None else '-',
                                              c['p90'] if c['p90'] is not None else '-',
                                              '%d/%d' % (c['ok'], c['n'])))
        t = r['tick']
        lines.append('%-*s  %s  %s  %6s %5s %5s %4d' % (w, r['run'], cells[0], cells[1],
                                                       t['median'], t['p95'], t['max'], t['late']))
    for r in res['runs']:
        tm = r['time']
        bits = ['time: ' + ' '.join('%s %d' % (k, tm[k]) for k in
                                    ('queue', 'pair', 'age', 'warp', 'read') if tm.get(k))
                + ' ms median']
        if r['engines']:
            bits.append('engines at once (share of the time) ' + ' '.join(
                '%s:%d%%' % (k, v) for k, v in r['engines'].items()))
        if r['slots']:
            wt = r['waited']
            bits.append('ocr slots %d, reads waited %sms median' % (r['slots'], r['time'].get('slot')))
            bits.append(', '.join('%s OCRs %d of %d waited%s' % (
                role, wt[role]['waited'], wt[role]['asks'],
                ' +%dms median' % wt[role]['median'] if wt[role]['waited'] else '')
                for role in ('card', 'spare', 'label') if role in wt and wt[role]['asks'])
                + (', %d stopped as dropped' % r['stopped'] if r['stopped'] else ''))
        bits.append('%d label reads, cpu %d%%, load %s' % (r['labelReads'], r['cpuPct'], r['load1']))
        lines.append('%s: %s' % (r['run'], '; '.join(bits)))
    svc = {True: 'running (these reads shared the cores with it)',
           False: 'not running', None: 'unknown (no systemctl)'}[res['service']]
    lines.append('uberscan.service %s; engines warmed in %.1f s; took %.1f s'
                 % (svc, res['warmS'], res['tookS']))
    return '\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--n', type=int, default=5, help='reads of each kind (default 5)')
    ap.add_argument('--budget', type=float, default=150.0,
                    help='seconds for the timed reads, shared by every cell (default 150)')
    ap.add_argument('--json', action='store_true', help='print one JSON object')
    ap.add_argument('--busy', action='store_true',
                    help='time paired reads with the scanner\'s concurrent work beside them '
                         '(STOP uberscan.service first): alone, then the engines\' gate off '
                         'and on')
    ap.add_argument('--seconds', type=float, default=BUSY_S,
                    help='--busy: seconds of each run (default %d)' % BUSY_S)
    ap.add_argument('--slots', type=int, default=None,
                    help='--busy: the gate\'s slots for its third run (default PL.OCR_SLOTS)')
    ap.add_argument('--view', choices=('scene', 'screen', 'none'), default='scene',
                    help='--busy: the live view composed beside the reads (default scene, '
                         '30/s off the preview; screen is the phone view, 15/s off the sensor)')
    for flag, what in (('label', 'the map label asks'), ('band', 'the map band'),
                       ('spare', 'the spare threads'), ('pair', 'the paired frame')):
        ap.add_argument('--no-' + flag, action='store_true', help='--busy: without ' + what)
    args = ap.parse_args(argv)
    if args.n < 1:
        ap.error('--n must be at least 1')
    if args.seconds <= 0:
        ap.error('--seconds must be above 0')
    if not TC.available():
        sys.exit('pi_bench: no PIL or no usable font here, so no screen can be drawn '
                 '(rpi/testcards.py)')
    if args.busy:
        # NOT niced, unlike the table: the stand-in loop is the camera loop,
        # at the rig's own priority, and the spare threads renice themselves
        # to 10 as on the rig. Which is why the service must be stopped: this
        # would take its cores.
        res = busy(args.seconds, PL.OCR_SLOTS if args.slots is None else args.slots,
                   view=args.view, label=not args.no_label, band=not args.no_band,
                   spare=not args.no_spare, pair=not args.no_pair)
        print(json.dumps(res) if args.json else busy_table(res))
        return 0
    # Below the camera loop, as the spare threads are: never raised back, so
    # an already gentler caller (nice -n 19) stays gentler.
    if os.nice(0) < NICE:
        os.nice(NICE - os.nice(0))
    res = run(args.n, args.budget)
    print(json.dumps(res) if args.json else table(res))
    return 0


if __name__ == '__main__':
    sys.exit(main())
