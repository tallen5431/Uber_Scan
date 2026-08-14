"""Offer card parsing — a direct port of offer-parser.js.

Both implementations run tests/fixtures/cases.json, so if this drifts from the
JavaScript the shared corpus fails. Keep the two in step when editing either.
"""

import re

# Characters OCR routinely swaps for digits, only ever applied inside a token
# already believed to be a number.
DIGIT_FIX = {
    'O': '0', 'o': '0', 'Q': '0', 'D': '0',
    'l': '1', 'I': '1', 'i': '1', '|': '1', '!': '1',
    'S': '5', 's': '5',
    'B': '8', 'b': '6',
    'Z': '2', 'z': '2',
    'g': '9', 'G': '6', 'T': '7',
}

# Digits as OCR may render them. Narrow on purpose: letters like G and T are
# corrected inside a confirmed number but are too risky to match on.
DC = r'[\dOoQlIiSsBbZz]'

MONEY_STRICT = re.compile(r'\$\s*(' + DC + r'{1,4}(?:[.,]' + DC + r'{1,2})?)')
MONEY_LOOSE = re.compile(r'(?:^|[\s(])[$S5§]\s?(' + DC + r'{1,4}(?:[.,]' + DC + r'{1,2})?)')

LEG = re.compile(
    r'(?:(\d{1,2})\s*h(?:r|rs|our|ours)?\s*)?'
    r'(' + DC + r'{1,3})\s*m(?:in|ins|inute|inutes)?\b'
    r'(?:[^(\d]{0,6}\(?\s*(' + DC + r'{1,3}(?:[.,]' + DC + r'{1,2})?)\s*m(?:i|ile|iles)\b\s*\)?)?',
    re.IGNORECASE)

ITEMS = re.compile(r'(' + DC + r'{1,3})\s*items?\b', re.IGNORECASE)
TOTAL_TAIL = re.compile(r'\btota?l\b')

# No offer averages highway speed door to door once pickup, lights and parking
# are in it. Above this the distance was misread.
MAX_MPH = 55.0


def fix_digits(token):
    return ''.join(DIGIT_FIX.get(c, c) for c in token)


def to_number(token):
    if token is None:
        return None
    try:
        return float(fix_digits(str(token)).replace(',', '.'))
    except ValueError:
        return None


def normalize(text):
    text = str(text or '')
    text = re.sub(r'[‘’“”]', "'", text)
    text = re.sub(r'[–—−]', '-', text)
    text = text.replace(' ', ' ')
    return re.sub(r'\s+', ' ', text).strip()


def find_pay(text):
    matches = MONEY_STRICT.findall(text) or MONEY_LOOSE.findall(text)
    best = None
    for raw in matches:
        v = to_number(raw.strip())
        # The offer headline is the largest dollar figure; promo lines are smaller.
        if v is not None and 0 < v < 2000 and (best is None or v > best):
            best = v
    return best


def find_legs(text):
    legs = []
    for m in LEG.finditer(text):
        mins = to_number(m.group(2))
        if mins is None:
            continue
        minutes = (to_number(m.group(1)) or 0) * 60 + mins
        if minutes <= 0 or minutes > 600:
            continue

        miles = to_number(m.group(3))
        if miles is not None and (miles < 0 or miles > 500):
            miles = None
        # A decimal point is a pixel or two through a lens and is the first
        # thing to be lost, so remember whether this reading actually had one.
        had_decimal = m.group(3) is not None and bool(re.search(r'[.,]', m.group(3)))

        tail = text[m.end():m.end() + 14].lower()
        legs.append({
            'minutes': minutes, 'miles': miles, 'hadDecimal': had_decimal,
            'isTotal': bool(TOTAL_TAIL.search(tail)),
        })
    return legs


def check_distance(minutes, miles, had_decimal):
    """Guards the one OCR failure that inverts the answer: losing the decimal in
    "3.6 mi" turns a 6 mph errand into a 63 mph one, and the phantom 32 miles
    can swallow the whole fare as mileage cost."""
    if miles is None or not minutes:
        return miles, False, False

    mph = miles / (minutes / 60.0)
    if mph <= MAX_MPH:
        return miles, False, False

    # A missing decimal is the likeliest cause, and only when the reading did
    # not have one. Recovering it must be visible, never silent.
    if not had_decimal and 0.5 <= mph / 10.0 <= MAX_MPH:
        return miles / 10.0, True, False
    return miles, False, True


def parse(raw_text):
    text = normalize(raw_text)
    legs = find_legs(text)

    totals = [l for l in legs if l['isTotal']]
    used = totals or legs

    minutes = None
    miles = None
    had_decimal = False
    for leg in used:
        minutes = (minutes or 0) + leg['minutes']
        if leg['miles'] is not None:
            miles = (miles or 0) + leg['miles']
            if leg['hadDecimal']:
                had_decimal = True

    miles, corrected, uncertain = check_distance(minutes, miles, had_decimal)

    m = ITEMS.search(text)
    items = to_number(m.group(1)) if m else None
    if items is not None and not (0 <= items <= 200):
        items = None

    pay = find_pay(text)

    return {
        'pay': pay,
        'minutes': minutes,
        'miles': miles,
        # The legs behind the sum, so a caller holding readings from several
        # frames can merge the ones a single frame missed.
        'legDetail': [{'minutes': l['minutes'], 'miles': l['miles'],
                       'isTotal': l['isTotal']} for l in used],
        'items': items,
        'legs': len(used),
        'milesCorrected': corrected,
        'milesUncertain': uncertain,
        'complete': pay is not None and pay > 0 and minutes is not None and minutes > 0,
        'text': text,
    }


def rate(parsed, settings=None):
    s = settings or {}
    target = s.get('target', 25)
    band = s.get('band', 15)
    cost_per_mile = s.get('costPerMile', 0)
    pad = s.get('pad', 0)
    seconds_per_item = s.get('secondsPerItem', 0)

    if not parsed['complete']:
        return {'ready': False, 'state': 'empty'}

    shop_minutes = (parsed['items'] or 0) * seconds_per_item / 60.0
    minutes = parsed['minutes'] + pad + shop_minutes
    # A distance we do not trust must not become a cost. Falling back to gross
    # overstates the rate slightly; a bad distance can understate it enormously.
    cost = 0 if parsed['milesUncertain'] else (parsed['miles'] or 0) * cost_per_mile
    net = parsed['pay'] - cost

    per_hour = net / (minutes / 60.0)
    floor = target * (1 - band / 100.0)

    return {
        'ready': True,
        'minutes': minutes,
        'shopMinutes': shop_minutes,
        'net': net,
        'cost': cost,
        'perHour': per_hour,
        'perMin': net / minutes,
        'perMile': (parsed['pay'] / parsed['miles']
                    if parsed['miles'] and not parsed['milesUncertain'] else None),
        'milesUncertain': parsed['milesUncertain'],
        'milesCorrected': parsed['milesCorrected'],
        'state': 'go' if per_hour >= target else ('warn' if per_hour >= floor else 'no'),
    }
