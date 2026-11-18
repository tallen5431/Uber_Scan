"""Uber's Earnings Activity screen drawn the way the phone draws it, for tests.

Not shipped code and not imported by anything on the rig, like testcards.py
beside it: the earnings parser (earnings.js) and the upload endpoint
(server.js, /api/earnings) are tested on a PICTURE of the screen run through
the real `tesseract`, because the faults that matter live between the two —
a time printed at the right edge landing on another line, a map's street
labels read as words, a tip line in a smaller grey face.

THE LAYOUT is the owner's screenshot of 7 Nov 2026 (Uber driver app ->
Earnings -> Earnings Activity, one day, portrait, about 756x2000): a header
"Earnings Activity", a date chip "11/7", a day heading "Sat, Nov 7", then one
block per trip —

    $25.05                                         4:50 PM
    Delivery · 40 min 48 sec · 9.38 mi
    $19.54 Tip                     (or "Tip processing")
    [the trip's map]
    <Restaurant> (<Street> NW & <Street> Ct)
    <Street> NE, <Town>, GA, USA

— and, under the last, "End of activities during Nov 7, 2026". The owner's
screenshot itself is NOT in the repository and nothing here was copied from
it but the shape: every restaurant, street and town below is invented, and the
figures are made up. (AUDITS.md: invented fixtures only.)

The time sits at the right of the amount's line here; the owner described it
as "time at right" without saying which line, so `time_row` moves it onto the
Delivery line for the parser's other case.

PIL is a test-time dependency only; `available()` says whether a screen can be
drawn here, so a caller can skip rather than fail.
"""

import os

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:                                    # pragma: no cover
    Image = ImageDraw = ImageFont = None

# The fonts testcards.py prefers, for the reason it gives: Liberation is the
# closest to what a phone renders, DejaVu what a bare Debian has.
FONTS = [('/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
          '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf'),
         ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
          '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
         ('/usr/share/fonts/truetype/freefont/FreeSans.ttf',
          '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf')]

# The owner's phone, in its own pixels: a screenshot about 756 wide and 2000
# tall. Not a camera frame — an upload is the phone's own screenshot, sharp and
# square-on, which is why the parser can be stricter here than on the rig.
W, H = 756, 2000

INK = (20, 20, 20)
GREY = (110, 110, 110)
TIP_GREEN = (14, 128, 64)
MAP_BG = (226, 232, 226)
MAP_ROAD = (250, 250, 250)
MAP_ROUTE = (40, 40, 40)
CHIP = (238, 238, 238)


def available():
    return Image is not None and _pair() is not None


def _pair():
    for regular, bold in FONTS:
        if os.path.exists(regular) and os.path.exists(bold):
            return regular, bold
    return None


def font(size, bold=False):
    return ImageFont.truetype(_pair()[1 if bold else 0], size)


# Invented trips for the tests: (amount, kind, minutes, seconds, miles, time,
# tip, pickup, dropoff). `tip` is a string as the screen prints it, or None for
# a trip with no tip line at all. A chain's pickup carries its street corner in
# the bracket; a one-off restaurant its town.
TRIPS = [
    ('$2.00', 'Delivery', 39, 33, '12.30', '5:40 PM', 'Tip processing',
     'Pretend Pizza (Faketown)', 'Placeholder Ct, Faketown, GA, USA'),
    ('$25.05', 'Delivery', 40, 48, '9.38', '4:50 PM', '$19.54 Tip',
     'Make-Believe Burgers (Sample St NW & Fictional Ct)', 'Example Ave NE, Notaville, GA, USA'),
    ('$7.25', 'Delivery', 22, 5, '4.10', '3:58 PM', None,
     'Nowhere Noodles (Inventon)', 'Imaginary Way, Inventon, GA, USA'),
]

# The owner's 12 Nov screenshots showed two things the first layout lacked: a
# tip and a surge on one line ("$6.00 Tip $1.25 Surge"), and a trip the
# driver canceled ("$0.00", "Delivery · You canceled", its map and places).
# Invented as everything here.
TRIPS_12 = [
    ('$9.50', 'Delivery', 24, 10, '6.40', '4:18 PM', '$6.00 Tip $1.25 Surge',
     'Fabled Falafel (Faketown)', 'Storybook Ln, Faketown, GA, USA'),
    ('$0.00', 'Delivery · You canceled', None, None, None, '5:30 PM', None,
     'Sample Sushi (Notaville)', 'Fictional Ct SW, Notaville, GA, USA'),
    ('$12.64', 'Delivery', 22, 0, '6.30', '6:23 PM', None,
     'Nowhere Noodles (Inventon)', 'Imaginary Way, Inventon, GA, USA'),
]


def _map(d, x0, y0, w, h, seed):
    """A trip's map: blocks, roads and a route line, with a couple of short
    street labels of the kind a real map prints. They are there to be read as
    noise: the parser has to step over whatever tesseract makes of a map."""
    d.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=18, fill=MAP_BG)
    for i in range(6):
        y = y0 + 20 + ((seed * 37 + i * 53) % (h - 40))
        d.line([(x0 + 6, y), (x0 + w - 6, y + ((i * 17) % 30) - 15)], fill=MAP_ROAD, width=9)
    for i in range(5):
        x = x0 + 30 + ((seed * 61 + i * 131) % (w - 60))
        d.line([(x, y0 + 6), (x + ((i * 23) % 40) - 20, y0 + h - 6)], fill=MAP_ROAD, width=7)
    pts = [(x0 + 60 + ((seed + k) * 97) % (w - 120), y0 + 30 + k * (h - 60) // 4) for k in range(5)]
    d.line(pts, fill=MAP_ROUTE, width=5)
    d.ellipse([pts[0][0] - 9, pts[0][1] - 9, pts[0][0] + 9, pts[0][1] + 9], fill=MAP_ROUTE)
    d.rectangle([pts[-1][0] - 8, pts[-1][1] - 8, pts[-1][0] + 8, pts[-1][1] + 8], fill=MAP_ROUTE)
    d.text((x0 + 24, y0 + h - 40), 'Mock Rd', font=font(15), fill=(150, 150, 150))


def screen(trips=None, day='Sat, Nov 7', chip='11/7', end='End of activities during Nov 7, 2026',
           time_row='amount', header=True, top_skip=0):
    """One screenshot of the day's Earnings Activity, as a PIL image.

    `trips` as TRIPS; `end` None for a screenshot scrolled short of the
    bottom; `header` False for one scrolled past the top (no header, no chip,
    no day heading — the case where the day must come from another
    screenshot, or from the caller's context); `top_skip` cuts that many
    pixels of blocks off the top, as a scroll does, so a block can arrive
    half-shown."""
    trips = TRIPS if trips is None else trips
    # Drawn on a tall canvas and cut to the phone's height, or to the content
    # where three trips and the end line run past it: a real screenshot is
    # one screen, and the tests that want the scroll make two (`top_skip`).
    im = Image.new('RGB', (W, H * 2), (255, 255, 255))
    d = ImageDraw.Draw(im)
    y = 30 - top_skip
    d.text((24, 8), '6:12', font=font(22, True), fill=INK)          # the status bar
    if header:
        y = 70
        d.text((24, y), '<', font=font(40), fill=INK)
        d.text((150, y), 'Earnings Activity', font=font(38, True), fill=INK)
        y += 90
        d.rounded_rectangle([24, y, 130, y + 50], radius=25, fill=CHIP)
        d.text((46, y + 10), chip, font=font(26, True), fill=INK)
        y += 90
        d.text((24, y), day, font=font(34, True), fill=INK)
        y += 70
    for i, t in enumerate(trips):
        amount, kind, mins, secs, miles, clock, tip, pickup, dropoff = t
        # A canceled trip prints its kind and who canceled in place of its
        # minutes and miles ("Delivery · You canceled"): `mins` None, the
        # kind given whole.
        detail = kind if mins is None else '%s · %d min %d sec · %s mi' % (kind, mins, secs, miles)
        d.text((24, y), amount, font=font(40, True), fill=INK)
        if time_row == 'amount':
            d.text((W - 24 - d.textlength(clock, font=font(26)), y + 8), clock, font=font(26), fill=GREY)
        y += 58
        d.text((24, y), detail, font=font(24), fill=GREY)
        if time_row == 'detail':
            d.text((W - 24 - d.textlength(clock, font=font(26)), y), clock, font=font(26), fill=GREY)
        y += 40
        if tip:
            d.text((24, y), tip, font=font(24, True), fill=TIP_GREEN if '$' in tip else GREY)
            y += 42
        y += 8
        _map(d, 24, y, W - 48, 300, i + 1)
        y += 320
        d.text((24, y), pickup, font=font(26, True), fill=INK)
        y += 40
        d.text((24, y), dropoff, font=font(24), fill=GREY)
        y += 40
        d.line([(24, y + 14), (W - 24, y + 14)], fill=(230, 230, 230), width=2)
        y += 40
    if end:
        d.text((24, y + 10), end, font=font(22), fill=GREY)
        y += 60
    return im.crop((0, 0, W, max(H, y + 20)))


# The owner's 17 Nov screenshot showed rides beside deliveries, and what the
# first layouts lacked: a round icon left of every amount (a person for a
# ride, a bag for a delivery), a pin and a circle before the two place lines,
# a ride's pickup printed as the rider's street, a ride over an hour ("1 hr 1
# min"), a green "Increased" chip on an amount's row, a "Boost+" chip with no
# amount beside a tip, and a canceled $0.00 entry between two trips whose
# dropoff is "Unknown". Invented as everything here: (icon, amount, kind,
# duration or None, miles, time, tip, chip, pickup, dropoff). `time` None
# draws the canceled entry's time too faint to read — the shape of the
# screenshot's "B5I PHI", which no rule should guess at.
TRIPS_17 = [
    ('ride', '$22.10', 'Comfort', '17 min 40 sec', '9.40', '10:31 PM', '$3.00 Tip', None,
     'Sample St, Faketown, GA, USA', 'Mock Rd SE, Notaville, GA, USA'),
    ('bag', '$11.00', 'Delivery', '12 min 30 sec', '3.10', '9:37 PM', '$6.00 Tip', None,
     'Pretend Pizza (100 Example Ave SE)', 'Imaginary Way, Inventon, GA, USA'),
    ('canceled', '$0.00', 'Delivery · You canceled', None, None, None, None, None,
     'Fictional Ct NW, Faketown, GA, USA', 'Unknown'),
    ('ride', '$21.30', 'Comfort', '26 min 10 sec', '12.20', '8:12 PM', None, 'Increased',
     'Placeholder Pkwy, Notaville, GA, USA', '12th St NE, Faketown, GA, USA'),
    ('bag', '$19.75', 'Delivery', '30 min 5 sec', '11.00', '7:05 PM', '$2.50 Tip', 'Boost+',
     'Nowhere Noodles West Inventon', 'Storybook Ln, Faketown, GA, USA'),
    ('ride', '$30.10', 'UberX', '1 hr 4 min', '20.50', '5:48 PM', None, None,
     'Hidden Sample Ct, Notaville, GA, USA', 'Sample St, Faketown, GA, USA'),
]


def _icon(d, x, y, kind):
    """The round icon left of an amount: a person (ride), a bag (delivery) or
    a slashed circle (canceled), grey on a pale disc, as the screen draws it."""
    d.ellipse([x, y, x + 44, y + 44], fill=(242, 242, 242))
    if kind == 'ride':
        d.ellipse([x + 16, y + 9, x + 28, y + 21], outline=INK, width=3)
        d.arc([x + 11, y + 22, x + 33, y + 42], 180, 360, fill=INK, width=3)
    elif kind == 'bag':
        d.rounded_rectangle([x + 13, y + 15, x + 31, y + 33], radius=3, outline=TIP_GREEN, width=3)
        d.arc([x + 17, y + 9, x + 27, y + 20], 180, 360, fill=TIP_GREEN, width=2)
    else:
        d.ellipse([x + 12, y + 12, x + 32, y + 32], outline=GREY, width=2)
        d.line([(x + 15, y + 29), (x + 29, y + 15)], fill=GREY, width=2)


def _pin(d, x, y, first):
    """The small grey icon before a place line: a pin, then a ringed dot."""
    if first:
        d.ellipse([x, y, x + 12, y + 12], fill=GREY)
        d.polygon([(x + 2, y + 9), (x + 10, y + 9), (x + 6, y + 18)], fill=GREY)
    else:
        d.ellipse([x, y + 2, x + 13, y + 15], outline=GREY, width=3)


def screen17(trips=None, day='Tue, Nov 17', chip='11/17', end='End of activities during Nov 17, 2026'):
    """The rides-and-deliveries layout of the owner's 17 Nov screenshot, at
    the phone's width, its maps short as that screen draws them."""
    trips = TRIPS_17 if trips is None else trips
    im = Image.new('RGB', (W, H * 2), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.text((24, 8), '11:52', font=font(22, True), fill=INK)
    y = 60
    d.text((24, y), '<', font=font(34), fill=INK)
    d.text((90, y), 'Earnings Activity', font=font(32, True), fill=INK)
    y += 70
    d.rounded_rectangle([24, y, 130, y + 44], radius=22, fill=CHIP)
    d.text((40, y + 8), chip, font=font(24, True), fill=INK)
    y += 70
    d.text((24, y), day, font=font(22), fill=GREY)
    y += 50
    for i, t in enumerate(trips):
        icon, amount, kind, dur, miles, clock, tip, chip_, pickup, dropoff = t
        _icon(d, 24, y, icon)
        d.text((86, y), amount, font=font(28, True), fill=INK)
        if chip_ == 'Increased':
            x0 = 86 + d.textlength(amount, font=font(28, True)) + 14
            d.rounded_rectangle([x0, y + 2, x0 + 160, y + 36], radius=6, fill=(228, 245, 233))
            d.text((x0 + 10, y + 6), '↑ Increased', font=font(22), fill=TIP_GREEN)
        if clock:
            d.text((W - 24 - d.textlength(clock, font=font(22)), y + 22), clock, font=font(22), fill=INK)
        else:
            d.text((W - 24 - d.textlength('8:51 PM', font=font(22)), y + 22), '8:51 PM', font=font(9),
                   fill=(236, 236, 236))
        y += 38
        detail = kind if dur is None else '%s · %s · %s mi' % (kind, dur, miles)
        d.text((86, y), detail, font=font(22), fill=INK)
        y += 36
        if tip:
            d.text((24, y), tip, font=font(22), fill=INK)
            if chip_ == 'Boost+':
                d.text((24 + d.textlength(tip, font=font(22)) + 40, y), 'Boost+', font=font(22), fill=INK)
            y += 34
        y += 6
        _map(d, 12, y, W - 24, 120, i + 1)
        y += 134
        _pin(d, 16, y + 4, True)
        d.text((40, y), pickup, font=font(22), fill=INK)
        y += 32
        _pin(d, 16, y + 4, False)
        d.text((40, y), dropoff, font=font(22), fill=INK)
        y += 32
        d.rectangle([0, y + 10, W, y + 22], fill=(242, 242, 242))
        y += 36
    if end:
        d.text((W // 2 - d.textlength(end, font=font(24)) // 2, y + 10), end, font=font(24), fill=INK)
        y += 60
    return im.crop((0, 0, W, max(H, y + 20)))


def acceptance_screen(rate=23, last10=4, requests=100, accepted=23, declined=77, scale=1.0):
    """Uber's Acceptance rate screen (Uber Pro -> Acceptance rate), as the
    owner's screenshot of 15 Nov 2026 laid it out, every figure invented: a
    big "23%" over "Acceptance rate", a "4/10" for the last ten exclusive
    requests, Uber's explanation in small grey type, and a box "Based on your
    last 100 exclusive requests" with three rows. Black on white, as that
    screen is. `scale` draws it at another phone's size."""
    def f(size, bold=False):
        return font(int(round(size * scale)), bold)

    def at(v):
        return int(round(v * scale))
    w, h = at(W), at(1500)
    im = Image.new('RGB', (w, h), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.text((at(24), at(8)), '7:41', font=f(22, True), fill=INK)
    d.text((at(24), at(70)), '<', font=f(40), fill=INK)
    d.text((at(24), at(170)), '%d%%' % rate, font=f(96, True), fill=INK)
    d.text((at(24), at(300)), 'Acceptance rate', font=f(30), fill=GREY)
    d.text((at(24), at(390)), '%d/10' % last10, font=f(40, True), fill=TIP_GREEN)
    d.text((at(160), at(398)), 'last 10 exclusive requests', font=f(26), fill=GREY)
    y = at(490)
    for line in ('Your acceptance rate is the percentage of exclusive trip',
                 'requests that you accepted over the last 100 requests.',
                 'Exclusive trip requests are requests sent directly to you.',
                 'Your acceptance rate excludes Trip Radar requests.'):
        d.text((at(24), y), line, font=f(22), fill=GREY)
        y += at(36)
    y += at(40)
    d.rounded_rectangle([at(24), y, w - at(24), y + at(330)], radius=at(18), outline=(220, 220, 220), width=2)
    d.text((at(48), y + at(30)), 'Based on your last 100 exclusive requests', font=f(26, True), fill=INK)
    y += at(110)
    for label, v in (('Exclusive trip requests', requests), ('Accepted', accepted), ('Declined', declined)):
        d.text((at(48), y), label, font=f(28), fill=INK)
        s = str(v)
        d.text((w - at(48) - d.textlength(s, font=f(28, True)), y), s, font=f(28, True), fill=INK)
        y += at(70)
    return im


def save(im, path, kind='PNG'):
    im.save(path, kind)
    return path
