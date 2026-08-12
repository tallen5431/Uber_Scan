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

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad else '\nAll %d python parser checks passed' % ok)
sys.exit(1 if bad else 0)
