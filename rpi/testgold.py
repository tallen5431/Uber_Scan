"""An invented record for the offers page's Gold card, for tests.

Not shipped code and not imported by anything on the rig, like testcards.py
and testearnings.py beside it. Four evenings of Uber cards ending the night
before `now`, written the way the journal holds them, so server.js
/api/gold, the offers page and its screenshots all read one record:

  - 45 Uber cards an evening, 18:00 to 20:00, 25 minutes each, on ten panel
    rates in turn — $12, $12, $13, $14, $15, $16, $17, $18, $30, $38/hr —
    every one tagged Exclusive but the four `UNTAGGED` (the tag not read:
    counted all the same);
  - the two highest rates of each ten Took'd (a `mark` row, accepted, with
    no drop row: no order holds the car, so every hour is free): 32 of the
    180, and one more card accepted on the phone with no Took, known
    only from an earnings row matched to it (`PHONE`);
  - left out of the count: two Trip Radar cards, one Early look card and
    five DoorDash offers.

Every place, figure and card is made up. (AUDITS.md: invented fixtures only.)
"""

import datetime

RATES = [12, 12, 13, 14, 15, 16, 17, 18, 30, 38]
PER_EVENING = 45
UNTAGGED = ('gold3-5', 'gold3-15', 'gold3-25', 'gold3-35')
PHONE = 'gold3-6'


def _evening(now_ms, back):
    d = datetime.datetime.fromtimestamp(now_ms / 1000.0) - datetime.timedelta(days=back)
    return int(datetime.datetime(d.year, d.month, d.day, 18, 0).timestamp() * 1000)


def card(oid, at, rate, minutes=25.0, app='uber', **extra):
    pay = round(rate * minutes / 60.0, 2)
    row = {'v': 1, 'id': oid, 'seq': 1, 'at': at, 'firstAt': at, 'app': app,
           'pay': pay, 'minutes': minutes, 'miles': round(minutes / 5.0, 1), 'perHour': float(rate),
           'grossPerHour': float(rate), 'cost': 0, 'billedMinutes': minutes,
           'state': 'go' if rate >= 25 else 'warn' if rate >= 15 else 'no',
           'target': 25, 'band': 15, 'costPerMile': 0, 'legs': 2, 'whole': True,
           'pickup': 'Pretend Pizza (Sample St)', 'dropoff': 'Example Ct, Make Town'}
    row.update(extra)
    return row


def rows(now_ms):
    out = []
    for e, back in enumerate((4, 3, 2, 1)):
        t0 = _evening(now_ms, back)
        for i in range(PER_EVENING):
            at = t0 + int(i * (120.0 / PER_EVENING) * 60000)
            rate = RATES[i % 10]
            oid = 'gold%d-%d' % (e, i)
            extra = {} if oid in UNTAGGED else {'exclusive': True}
            out.append(card(oid, at, rate, **extra))
            if i % 10 >= 8:
                out.append({'v': 1, 'kind': 'mark', 'id': oid, 'at': at + 20000, 'accepted': True})
        # ...what the count leaves out, on each evening's edges.
        if e == 0:
            out.append(card('radar0', t0 + 30000, 12, text='Trip Radar\n$5.00\n25 min (5.0 mi) total'))
            out.append(card('radar1', t0 + 90000, 12, text='Trip Radar\n$5.00\n25 min (5.0 mi) total'))
            out.append(card('early0', t0 + 150000, 30, exclusive='early',
                            text='Early look - Order in progress\n$12.50'))
        for k in range(2 if e < 2 else 1 if e == 2 else 0):
            out.append(card('dd%d-%d' % (e, k), t0 + 600000 + k * 60000, 20, app='doordash'))
    # The card accepted on the phone, no Took: an earnings row matched to it.
    ph = [r for r in out if r.get('id') == PHONE][0]
    day = datetime.datetime.fromtimestamp(ph['at'] / 1000.0)
    out.append({'v': 1, 'kind': 'earning', 'id': 'earn:goldphone', 'seq': now_ms - 3600000,
                'at': now_ms - 3600000, 'key': 'goldphone', 'app': 'uber', 'date': day.strftime('%Y-%m-%d'),
                'startedAt': day.strftime('%H:%M'), 'amount': 9.0, 'tip': None, 'status': 'completed',
                'type': 'Delivery', 'minutes': 24, 'seconds': 0, 'miles': 5.1,
                'match': {'status': 'matched', 'by': 'auto', 'offer': PHONE, 'source': 'offer',
                          'said': 'accepted on the phone, no Took', 'cardPay': ph['pay'],
                          'offeredAt': ph['at'], 'tookAt': None}})
    return sorted(out, key=lambda r: r['at'])
