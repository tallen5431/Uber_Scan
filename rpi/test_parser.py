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
        if key.lower().endswith('perhour') and got is not None:
            got = round(got, 2)
        eq(c['name'] + ' / ' + key, got, want)

# --- the three functions that decide what an offer is judged against -------
# All three had drifted between the two languages, and none of it was reachable
# from a test. Driven from the same list the JavaScript runs.
def _value(v):
    # `.get(v, v)` on a dict cannot be used here: one of the settings cases is a
    # list, and an unhashable key raises rather than missing.
    if v == '@inf':
        return float('inf')
    if v == '@-inf':
        return float('-inf')
    if v == '@nan':
        return float('nan')
    return v


for c in cases.get('coerce', {}).get('toNumber', []):
    eq('toNumber / ' + c['name'], P.to_number(_value(c['in'])), c['expect'])

for c in cases.get('coerce', {}).get('setting', []):
    eq('setting / ' + c['name'],
       P.setting(_value(c['in']), c['fallback']), c['expect'])

for c in cases.get('coerce', {}).get('round2', []):
    eq('round2 / ' + c['name'], P.round2(_value(c['in'])), c['expect'])

for c in cases.get('coerce', {}).get('doubt', []):
    eq('doubt / ' + c['name'],
       P.doubt(_value(c['pay']), _value(c['minutes']), _value(c['miles'])),
       c['expect'])

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

# The screen shows both rates and the cost between them, so those three have to
# be one sum. They are only one sum if both rates were divided by the same
# minutes — and the billed minutes are not the card's as soon as a shopping
# allowance is set. Working the raw rate out from the card's own time gave
# $12.51/hr next to a net $8.39/hr and a $1.08 deduction, three numbers that
# cannot be reconciled by anyone checking them.
shopping = P.rate(offer, {'target': 25, 'costPerMile': 0.30, 'secondsPerItem': 90})
eq('the raw rate is over the billed time, not the card time',
   round(shopping['grossPerHour'], 2), round(offer['pay'] / (43 / 60.0), 2))
eq('...which the card time would have got wrong',
   round(shopping['grossPerHour'], 2) != round(offer['pay'] / (34 / 60.0), 2), True)
for name, r in (('no costs', gross), ('mileage', net), ('shopping', shopping)):
    eq('raw less the cost is the net rate (%s)' % name,
       round(r['grossPerHour'] - r['cost'] / (r['minutes'] / 60.0), 6),
       round(r['perHour'], 6))
eq('with nothing deducted the two rates are the same figure',
   gross['grossPerHour'], gross['perHour'])

# A trip that takes no time pays infinitely well. parse() will not produce a
# zero-minute offer, but `pad` is edited by hand in config.json and a negative
# one cancels the trip out. This raised ZeroDivisionError, which does not stop
# at a bad verdict — it takes the scan loop with it. The JS returned Infinity
# and a confident 'go'.
nil = P.rate(offer, {'target': 25, 'costPerMile': 0, 'pad': -offer['minutes']})
eq('no time left is not a verdict', nil['ready'], False)
eq('...and not a state either', nil['state'], 'empty')
neg = P.rate(offer, {'target': 25, 'costPerMile': 0, 'pad': -offer['minutes'] - 10})
eq('nor is negative time', neg['ready'], False)


# --- a reading that cannot be true --------------------------------------------
# From 234 offers off a real rig: three that had lost a decimal point and two
# whose misread time implied 110 and 120 mph. Every one was shown as ACCEPT, in
# green, and the first was spoken aloud as "accept, three thousand five hundred
# an hour" to somebody watching the road.
S = {'target': 25, 'costPerMile': 0.30}


def card(pay, minutes, miles):
    return {'pay': pay, 'minutes': minutes, 'miles': miles, 'items': None,
            'complete': True, 'milesUncertain': False, 'milesCorrected': False}


lost_point = P.rate(card(1184.0, 20.0, 3.9), S)
eq('$11.84 read as $1184 is not an ACCEPT', lost_point['state'], 'doubt')
eq('...and says which figure to look at', lost_point['doubt'], 'pay')
eq('...while still being a complete row for the journal', lost_point['ready'], True)
eq('...with the numbers it read left on it', round(lost_point['perHour']), 3548)

fast = P.rate(card(56.65, 63.0, 115.6), S)
eq('115 miles in 63 minutes is not an ACCEPT', fast['state'], 'doubt')
eq('...and names the distance', fast['doubt'], 'speed')

# The same trip with the time read correctly is an ordinary long highway run —
# the fastest real average in that shift, 56 mph — and must get a verdict rather
# than a query. That the verdict is PASS is the deduction doing its job: $56.65
# against 115.6 miles is $34.68 of running costs, leaving $10.72/hr. Refusing to
# judge it would be the same mistake as the green ACCEPT, in the other
# direction — the driver learns nothing and decides alone.
real_long = P.rate(card(56.65, 123.0, 115.6), S)
eq('...but 115 miles in 123 minutes is believed', real_long['doubt'], None)
eq('...and judged: at 30c a mile it does not clear the target', real_long['state'], 'no')
eq('...on $10.72 an hour after the car is paid for', round(real_long['perHour'], 2), 10.72)

# Only the direction that produces a wrong ACCEPT is checked. Six miles an hour
# is a real thing that happens in traffic, and the offers it describes are poor
# ones the driver should be told to pass rather than told to check.
eq('crawling through traffic is a PASS, not a doubt',
   P.rate(card(7.09, 34.0, 3.6), S)['state'], 'no')
eq('an ordinary offer is unaffected', P.rate(card(16.05, 23.0, 8.4), S)['state'], 'go')

# `pad` and the shopping allowance are the driver's own additions to the clock.
# A card is not misread for having them applied, and judging the padded time
# would turn a long shopping order into a fault.
padded = P.rate(card(30.0, 20.0, 4.0), {'target': 25, 'costPerMile': 0.3, 'pad': 300})
eq('a huge pad does not make the card a misread', padded['doubt'], None)

# The bound is on the card's own time, so a two-minute card is fine and a
# one-minute one is not: at that length the leading digit has been lost.
eq('a two-minute card is believed', P.rate(card(5.0, 2.0, 0.5), S)['doubt'], None)
eq('a one-minute card is not', P.rate(card(5.0, 1.0, 0.5), S)['doubt'], 'time')

# Short distances are exempt from the speed test: a 0.4-mile leg over a
# one-minute reading is 24 mph, and the arithmetic is too coarse to mean
# anything either way.
eq('a very short hop is not judged on speed',
   P.rate(card(5.0, 3.0, 0.9), S)['doubt'], None)


# --- a sum of one-decimal distances has one decimal ----------------------------
# 3.5 + 6.1 is 9.600000000000001 in binary floating point, and twenty of one
# shift's 234 offers reached the journal and the CSV export looking like that.
two_legs = P.parse('$12.00 8 min (3.5 mi) pickup 20 min (6.1 mi) dropoff')
eq('two legs are summed', two_legs['legs'], 2)
eq('...to a distance a card could have printed', two_legs['miles'], 9.6)


print(('\n%d passed, %d FAILED' % (ok, bad)) if bad else '\nAll %d python parser checks passed' % ok)
sys.exit(1 if bad else 0)
