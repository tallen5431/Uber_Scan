"""The order in the car, and the offer measured against it.

    python3 rpi/test_stacking.py

Working two apps at once, a second offer arrives while the first order is still
in the car. The arithmetic behind that lives in advice.js and is checked by
tests/advice.test.js; what is checked here is the part that arithmetic cannot
see — whether the server actually knows an order is being carried, whether it
stops knowing at the right moments, and whether the figure reaches the page.

Driven against the real server with a fake scanner on its stdin contract, so
the mark, the hold and the stream are the real ones. Everything that matters
here is state held across requests, which no unit test of a pure function can
reach.
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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
    print('%s — skipping the stacking checks' % why)
    sys.exit(0)


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def get(base, path):
    return json.loads(urllib.request.urlopen(base + path, timeout=5)
                      .read().decode('utf-8'))


def post(base, path, body=None):
    data = json.dumps(body or {}).encode('utf-8')
    req = urllib.request.Request(base + path, data=data, method='POST',
                                 headers={'Content-Type': 'application/json'})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=5)
                          .read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode('utf-8'))


if not (subprocess.call(['node', '--version'], stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL) == 0):
    skip('no node')
if not subprocess.call(['python3', '--version'], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL) == 0:
    skip('no python3')

work = tempfile.mkdtemp()

# A scanner that puts one offer on the record, then keeps sending readings of a
# second card for the rest of the run. The second card is what gets measured
# against the first once the first has been marked as taken.
#
# The readings carry `target` and `costPerMile` because the server works the
# stacked figure out from the reading's own settings rather than from a config
# it might not share with the rig — a rig whose target was changed mid-shift
# would otherwise have its old line applied to its new verdicts.
#
# Which offer is on the record is driven from a file the test writes, so the
# sequence is deterministic rather than a race against a sleep. Several of the
# properties below are about what happens when the offer on screen is no longer
# the one in the car, and that cannot be reached at all with a scanner that only
# ever names one.
QUEUE = os.path.join(work, 'next')
fake = os.path.join(work, 'fakescan.py')
with open(fake, 'w') as fh:
    fh.write(
        'import json, os, sys, time\n'
        'QUEUE = %r\n'
        'READ = {"ready": True, "locked": True, "state": "no", "doubt": None,\n'
        '        "perHour": 21.6, "grossPerHour": 27.0, "pay": 9.0,\n'
        '        "minutes": 20.0, "billedMinutes": 20.0, "cardMinutes": 20.0,\n'
        '        "miles": 6.0, "cost": 1.8, "perMile": 1.5, "items": None,\n'
        '        "costPerMile": 0.3, "target": 25.0, "band": 15.0,\n'
        '        "milesCorrected": False, "milesUncertain": False,\n'
        '        "uncosted": False, "whole": True, "legs": 2, "mergedFrom": 2,\n'
        '        "ms": 900, "text": "", "places": [], "fromDeadline": False,\n'
        '        "deliverBy": None, "track": None}\n'
        'sent = None\n'
        'while True:\n'
        '    try:\n'
        '        want = open(QUEUE).read().strip()\n'
        '    except Exception:\n'
        '        want = ""\n'
        '    if want and want != sent:\n'
        '        sent = want\n'
        '        print(json.dumps({"offer": json.loads(want)}), flush=True)\n'
        '    print(json.dumps(READ), flush=True)\n'
        '    time.sleep(0.2)\n' % QUEUE)


def put_offer(offer):
    """Make this the offer on the record, and wait until the server has it."""
    tmp = QUEUE + '.part'
    with open(tmp, 'w') as fh:
        fh.write(json.dumps(offer))
    os.replace(tmp, QUEUE)
    for _ in range(100):
        on = get(base, '/api/status').get('offer')
        if on and on.get('id') == offer['id']:
            return True
        time.sleep(0.1)
    return False


HELD = {'id': 'held-1', 'pay': 12.0, 'minutes': 30.0, 'billedMinutes': 30.0,
        'miles': 8.0, 'cost': 2.4, 'perHour': 19.2}

port = free_port()
journal = os.path.join(work, 'j.jsonl')
proc = subprocess.Popen(
    ['node', os.path.join(ROOT, 'server.js')],
    env=dict(os.environ, PORT=str(port), HTTPS_PORT='0', JOURNAL=journal,
             SCANNER='1', SCANNER_CMD='python3', SCANNER_ARGS=fake),
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
base = 'http://127.0.0.1:%d' % port


def stream_read(timeout=8.0, live=False):
    """One reading off the live stream, as the driving screen receives it.

    `live` skips the replay a new listener is handed on connect. The two travel
    different paths through the server — the replay is written straight to the
    socket, live readings go through broadcast() — so a test that only ever
    reads the first message checks one of them and believes it has checked both.
    """
    req = urllib.request.Request(base + '/api/events')
    body = urllib.request.urlopen(req, timeout=timeout)
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = body.readline().decode('utf-8', 'replace').strip()
        if not line.startswith('data: '):
            continue
        msg = json.loads(line[6:])
        if msg.get('ready') and not (live and msg.get('replay')):
            body.close()
            return msg
    body.close()
    return None


try:
    for _ in range(120):
        try:
            urllib.request.urlopen(base + '/api/status', timeout=1).read()
            break
        except Exception:
            time.sleep(0.1)
    else:
        raise RuntimeError('the server never came up')

    # The offer has to be on the record before it can be marked.
    ok_('the offer reaches the record', put_offer(HELD))
    status = get(base, '/api/status')
    if not status.get('offer'):
        raise SystemExit(1)

    # --- nothing in the car yet ---------------------------------------------
    eq('nothing is being carried to begin with', status.get('holding'), None)
    first = stream_read()
    ok_('a reading arrives', bool(first))
    eq('...and carries no stacked figure', (first or {}).get('stack'), None)
    eq('...nor an order to stack onto', (first or {}).get('holding'), None)

    # Pressing "dropped off" with nothing in the car is the state the driver
    # wanted, not an error to be told about.
    done = post(base, '/api/delivered')
    eq('putting down nothing still answers ok', done.get('ok'), True)
    eq('...and says there was nothing to put down', done.get('wasHolding'), False)

    # --- take it ------------------------------------------------------------
    marked = post(base, '/api/offers/mark',
                  {'id': 'held-1', 'accepted': True})
    eq('the offer marks as taken', marked.get('ok'), True)

    status = get(base, '/api/status')
    ok_('...and becomes the order in the car', bool(status.get('holding')))
    eq('...with its payout', (status.get('holding') or {}).get('pay'), 12.0)
    eq('...and its time', (status.get('holding') or {}).get('minutes'), 30.0)
    # An age, not a timestamp. Two machines, two clocks — the same rule the rest
    # of this API already follows.
    ok_('...held as an age rather than a timestamp',
        isinstance((status.get('holding') or {}).get('heldMs'), (int, float)))
    ok_('no timestamp leaks out of it',
        'acceptedAt' not in (status.get('holding') or {}))

    # --- and the next offer is measured against it --------------------------
    #
    # A LIVE reading, not the replay a new listener is handed. The two take
    # different paths out of this server and a test reading only the first
    # message checks one of them while believing it has checked both.
    second = stream_read(live=True)
    ok_('a live reading still arrives', bool(second))
    ok_('...and it really is a live one, not the replay',
        second is not None and not second.get('replay'))
    s = (second or {}).get('stack')
    ok_('...now carrying a stacked figure', bool(s))
    if s:
        # 12 - 2.4 = 9.60 for the order in hand, essentially all of it still to
        # come; 9 - 1.8 = 7.20 for the new one.
        ok_('the pair is worth about seventeen dollars', 16.5 < s['pay'] <= 16.8)
        # The bound has to be a bound, in both directions and in the right order.
        ok_('the worst case is the two times added', 49.0 < s['maxMinutes'] <= 50.0)
        ok_('the best case is the longer of the two', 29.0 < s['minMinutes'] <= 30.0)
        ok_('the range runs low to high', s['worst'] <= s['best'])
        # $16.80 over 50 minutes is $20.16; over 30 it is $33.60. The target is
        # $25, so the range straddles it — and a straddle is never green.
        eq('a range straddling the target is amber, not green', s['state'], 'warn')
        # ...and the second reading also says what is being carried, so a panel
        # that missed the mark still knows.
        ok_('the reading names the order being carried', bool(second.get('holding')))

    # --- put it down --------------------------------------------------------
    done = post(base, '/api/delivered')
    eq('the order is put down', done.get('ok'), True)
    eq('...and it says there was one', done.get('wasHolding'), True)
    eq('nothing is carried afterwards', get(base, '/api/status').get('holding'), None)

    third = stream_read()
    eq('...and the next offer is judged on its own again',
       (third or {}).get('stack'), None)

    # --- taking the mark back is not the same as delivering, but it does end
    #     the hold: the driver pressed it twice because they did not take it.
    post(base, '/api/offers/mark', {'id': 'held-1', 'accepted': True})
    ok_('marking again picks it back up', bool(get(base, '/api/status').get('holding')))
    post(base, '/api/offers/mark', {'id': 'held-1', 'accepted': False})
    eq('unmarking puts it down', get(base, '/api/status').get('holding'), None)

    # --- the offer on screen is not the order in the car ---------------------
    #
    # The ordinary case, not an odd one: the driver takes a job, drives off, and
    # the next card appears while the first is still in the car. Un-marking THAT
    # one — the usual reason being that they pressed it by mistake — must not
    # put down the order they are actually carrying. Nothing here can be reached
    # with a scanner that only ever names one offer, which is why this file
    # drives which offer is on the record.
    post(base, '/api/offers/mark', {'id': 'held-1', 'accepted': True})
    ok_('the first order is in the car', bool(get(base, '/api/status').get('holding')))
    ok_('a second offer reaches the record',
        put_offer({'id': 'other-2', 'pay': 5.0, 'minutes': 12.0,
                   'billedMinutes': 12.0, 'miles': 2.0, 'cost': 0.6,
                   'perHour': 22.0}))
    post(base, '/api/offers/mark', {'id': 'other-2', 'accepted': False})
    held = get(base, '/api/status').get('holding')
    ok_('un-marking a different offer does not put the carried one down',
        bool(held))
    eq('...and the one still in the car is the one that was taken',
       (held or {}).get('pay'), 12.0)
    post(base, '/api/delivered')

    # --- an order the card gave no time for ----------------------------------
    #
    # There is nothing to measure against: with no duration there is no
    # remaining time, so a stacked figure would be a second job's minutes
    # divided by nothing. It must not be carried at all rather than carried
    # forever — an order that never expires puts a stale job against every
    # offer for the rest of the shift, and gets more wrong the longer it sits.
    ok_('an offer with no stated time reaches the record',
        put_offer({'id': 'timeless-3', 'pay': 9.0, 'minutes': None,
                   'billedMinutes': None, 'miles': 3.0, 'cost': 0.9,
                   'perHour': None}))
    post(base, '/api/offers/mark', {'id': 'timeless-3', 'accepted': True})
    eq('...and is not carried, because there is nothing to measure',
       get(base, '/api/status').get('holding'), None)
    timeless = stream_read(live=True)
    eq('...so no offer is stacked against it',
       (timeless or {}).get('stack'), None)
    post(base, '/api/delivered')

finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()

print()
print('%d passed, %d FAILED' % (ok, bad) if bad
      else 'All %d stacking checks passed' % ok)
sys.exit(1 if bad else 0)
