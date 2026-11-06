#!/usr/bin/env python3
"""Time the reads the rig makes, on the rig, off screens rendered here.

    python3 tools/pi_bench.py              # 5 of each, under ~3 min on a Pi 4
    python3 tools/pi_bench.py --n 3        # fewer
    python3 tools/pi_bench.py --json       # the same, as one JSON object

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
import json
import math
import os
import re
import statistics
import subprocess
import sys
import time

# One thread per tesseract, as scan_pi sets it for the real rig: two engines
# fight over a Pi's four cores without it (tools/test.sh says how badly).
# Before the engine is loaded, which importing pipeline does not do yet.
os.environ.setdefault('OMP_THREAD_LIMIT', '1')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'rpi'))

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


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--n', type=int, default=5, help='reads of each kind (default 5)')
    ap.add_argument('--budget', type=float, default=150.0,
                    help='seconds for the timed reads, shared by every cell (default 150)')
    ap.add_argument('--json', action='store_true', help='print one JSON object')
    args = ap.parse_args(argv)
    if args.n < 1:
        ap.error('--n must be at least 1')
    if not TC.available():
        sys.exit('pi_bench: no PIL or no usable font here, so no screen can be drawn '
                 '(rpi/testcards.py)')
    # Below the camera loop, as the spare threads are: never raised back, so
    # an already gentler caller (nice -n 19) stays gentler.
    if os.nice(0) < NICE:
        os.nice(NICE - os.nice(0))
    res = run(args.n, args.budget)
    print(json.dumps(res) if args.json else table(res))
    return 0


if __name__ == '__main__':
    sys.exit(main())
