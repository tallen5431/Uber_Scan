"""Runs the shared corpus against the Python parser.
   python3 rpi/test_parser.py"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import offer_parser as P

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
cases = json.load(open(os.path.join(ROOT, 'tests', 'fixtures', 'cases.json')))

ok = bad = 0
def eq(name, got, want):
    global ok, bad
    if isinstance(want, float) and isinstance(got, (int, float)) and got is not None:
        good = abs(got - want) < 0.001
    else:
        good = got == want
    if good: ok += 1
    else:
        bad += 1
        print('FAIL  %s: got %r want %r' % (name, got, want))

for c in cases['parse']:
    p = P.parse(c['text'])
    for key, want in c['expect'].items():
        eq(c['name'] + ' / ' + key, p[key], want)

for c in cases['rate']:
    r = P.rate(P.parse(c['text']), c['settings'])
    for key, want in c['expect'].items():
        got = r[key]
        if key == 'perHour' and got is not None:
            got = round(got, 2)
        eq(c['name'] + ' / ' + key, got, want)

# --- a rate has to be able to explain itself ------------------------------
# Working $7.09 over 34 minutes by hand gives $12.51/hr. The screen said
# $10.61 and gave no hint that $1.08 of running costs came off first, so the
# reasonable conclusion was that the arithmetic was broken. It was not; the
# display was mute. These are the fields that let it speak.
offer = P.parse('$7.09 6 items (6 units) 34 min (3.6 mi) total')
net = P.rate(offer, {'target': 25, 'costPerMile': 0.30})
gross = P.rate(offer, {'target': 25, 'costPerMile': 0})
eq('gross is what a driver works out by hand', round(gross['perHour'], 2), 12.51)
eq('net is what the screen shows', round(net['perHour'], 2), 10.61)
eq('the deduction is reported', round(net['cost'], 2), 1.08)
eq('...and the rate it came from', net['costPerMile'], 0.30)
eq('deducting nothing reports nothing', gross['cost'], 0)
eq('...at a rate of nothing', gross['costPerMile'], 0)
eq('and the gap is exactly the deduction',
   round(gross['perHour'] - net['perHour'], 2), round(net['cost'] / (34 / 60.0), 2))


print(('\n%d passed, %d FAILED' % (ok, bad)) if bad else '\nAll %d python parser checks passed' % ok)
sys.exit(1 if bad else 0)
