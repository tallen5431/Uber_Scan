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
        detail = '%s · %d min %d sec · %s mi' % (kind, mins, secs, miles)
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


def save(im, path, kind='PNG'):
    im.save(path, kind)
    return path
