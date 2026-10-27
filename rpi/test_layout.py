"""Every page, at every screen this thing gets bolted to.

    python3 rpi/test_layout.py

Three faults kept recurring in this project's CSS and none of them could be
seen by reading the file that caused them.

A grid whose column count is written out by hand goes out of step with the
markup in another file. `.scanbar` declared five tracks for six buttons; the
sixth flowed onto a second row and that row was drawn on top of the one line
that says why nothing is being read. `.bottombar` used `1fr`, whose floor is
the longest word in the button, and five buttons floored a 390px phone at
408px — so the page scrolled sideways and the controls were off the edge.

A rule can also stop applying, silently. One misplaced `*/` in a comment took
out a whole block of dashboard layout, and the page it broke still rendered:
it just rendered the phone design on a car dashboard. Nothing errors, nothing
logs, and the next screenshot is the only evidence.

And type sized for a phone at 30cm is half the angle on a panel at arm's
length. The offer log was rendering figures at 9.5px on a screen read while
parked, because those sizes live in the page's own <style> block and the
dashboard breakpoint was in the shared stylesheet.

So: the four pages are loaded at the four panel sizes this rig ships on, and
what is checked is what a screenshot would show. Nothing here is about how the
pages look; it is about whether they fit and whether they can be read.

Skipped where a browser cannot be had, the same way the other browser checks
skip.
"""

import base64
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# map.html is here too. It was the only page this server serves that no layout
# check had ever seen, on any panel — including the 3.5" hat, where its bar
# carries six controls and two text boxes and its sidebar is a second column.
# A map needs the network for tiles and lookups and says so when it has none;
# whether the page FITS is a different question, and the answer to it was
# unmeasured.
PAGES = ['index.html', 'live.html', 'journal.html', 'scan.html', 'map.html',
         # ...and the list of 📷 Snaps, measured with two in it — one whole,
         # with the longest note the rig keeps, and one with the longest
         # reason a part can be missing — so its widest line is on the page
         # when it is asked whether the page fits.
         'snaps.html']

# The panels this thing actually gets bolted to, plus a phone for comparison.
PANELS = [
    ('800x480', 800, 480),    # the official 7" Pi touchscreen
    ('1024x600', 1024, 600),  # the common 7" HDMI panel
    ('1280x800', 1280, 800),  # a tablet-shaped panel, on its side
    ('1024x768', 1024, 768),  # 4:3 — landscape, but only just
    ('480x320', 480, 320),    # a 3.5" hat
    ('390x844', 390, 844),    # a phone
]

# ...and screens measured for one question only — whether 📷 Snap is drawn
# exactly where the status row has room for it — on either side of where that
# room runs out, so the rule is held where it is decided and not only where
# every answer is the same. Not added to PANELS: the rest of this suite is
# about the screens the rig is bolted to, and these are not those.
SNAP_PANELS = [
    ('844x390', 844, 390),    # a phone held on its side
    ('760x390', 760, 390),
    ('740x360', 740, 360),    # a smaller phone on its side, in the hat's layout
    ('700x400', 700, 400),    # landscape, but a row too narrow for it
    ('768x1024', 768, 1024),  # a tablet held upright
    # ...and the pixel either side of where the room runs out, with the row
    # as it is since the rest of it went behind "…": 765 wide cuts the
    # median by 0.67px with the camera, 766 leaves it 0.27, at 480 tall; 420
    # cuts it by 0.3 and 421 leaves 0.64 held upright. Upright at 920 tall,
    # not 844: at 844 the phone picture of a screen that wide runs the page
    # past the glass whatever the row says, which is not this question.
    ('765x480', 765, 480),
    ('766x480', 766, 480),
    ('420x920', 420, 920),
    ('421x920', 421, 920),
]

# journal.html is one continuous list — a week of offers is fourteen thousand
# pixels of it — so it scrolls by design and only its width is held to the
# glass. Everything else is a screen glanced at while driving and must fit.
SCROLLS = {'journal.html',
           # A list of pictures, two to a snap, read parked on a phone.
           'snaps.html'}

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


def no_(name, cond):
    eq(name, bool(cond), False)


def skip(why):
    print('%s — skipping the layout checks' % why)
    sys.exit(0)


def crashed(stderr):
    """A driver that RAN and produced nothing is a FAILED suite.

    This used to be a skip, which exits 0, so `tools/test.sh` counted the suite
    as passed with none of its checks run. It is the same conflation `hung()`
    was written for and it was only half fixed: a driver that stops answering
    is caught, a driver that THROWS still slipped through as "the browser
    produced nothing".

    A machine that cannot run these at all — no chromium — is the one case
    where exiting 0 is right, and every driver here now says so explicitly by
    printing {skip: 'no chromium'} and returning. That is a signal; this is the
    absence of one. Reading the difference out of stderr was considered and
    rejected: it makes the suite guess from a message it does not control.
    """
    tail = (stderr or '').strip()[-400:]
    print('FAIL  the driver produced nothing — none of the %s checks ran'
          % 'layout')
    if tail:
        print('      ' + tail.replace('\n', '\n      '))
    print('\n%d passed, %d FAILED' % (ok, bad + 1))
    sys.exit(1)


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ---------------------------------------------------------------------------
# Read the files, before any browser is involved. These are the checks that
# hold whether or not this machine can run one.
# ---------------------------------------------------------------------------

def style_blocks(name):
    """The CSS in a file: the whole file, or every <style> in a page."""
    text = open(os.path.join(ROOT, name)).read()
    if name.endswith('.css'):
        return [text]
    return re.findall(r'<style[^>]*>(.*?)</style>', text, re.S)


SHEETS = ['styles.css', 'scan.css'] + PAGES

for name in SHEETS:
    for i, css in enumerate(style_blocks(name)):
        where = '%s%s' % (name, '' if len(style_blocks(name)) == 1 else ' #%d' % i)
        # An unmatched `*/` does not fail loudly; it silently ends a block of
        # rules early and the page renders the wrong design.
        eq('%s: comments open and close in step' % where,
           css.count('/*'), css.count('*/'))
        # ...and a stray brace does the same thing to everything after it.
        eq('%s: braces balance' % where, css.count('{'), css.count('}'))
        # ...but those two counts can balance while the comments are still
        # wrong: paste a paragraph after a `*/` and its own closing `*/` opens
        # a comment that swallows the rules below it, and the totals still
        # match. A `*/` reached with no comment open is the fault itself, and
        # a line of prose starting `*` outside one is what it looks like.
        depth, stray = 0, []
        for line in css.split('\n'):
            body = line.strip()
            if depth == 0 and body.startswith('*/'):
                stray.append('closed a comment that was not open: ' + body[:40])
            elif depth == 0 and body.startswith('*') and '{' not in line:
                stray.append('prose outside a comment: ' + body[:40])
            depth = max(0, depth + line.count('/*') - line.count('*/'))
        eq('%s: no comment tail outside a comment' % where, stray, [])

# A bar of controls must not be able to force the page wider than the screen.
# `1fr` is `minmax(auto, 1fr)`, and that `auto` is the button's longest word.
for sheet, sel in (('styles.css', '.bottombar'), ('scan.css', '.scanbar')):
    css = open(os.path.join(ROOT, sheet)).read()
    rule = re.search(re.escape(sel) + r'\s*\{([^}]*)\}', css)
    ok_('%s in %s has a rule' % (sel, sheet), rule is not None)
    body = rule.group(1) if rule else ''
    ok_('%s flows into as many columns as it has children' % sel,
        'grid-auto-flow: column' in body)
    ok_('%s tracks can shrink below their own labels' % sel,
        'minmax(0, 1fr)' in body)
    ok_('%s does not count its columns by hand' % sel,
        'grid-template-columns' not in body)

# `warn` is a verdict *state* on these pages — `.verdict.warn` is the CLOSE
# CALL panel — so a bare `.warn` rule meant for a message box restyles the
# panel instead. styles.css says so in a comment and scan.css did it anyway.
for sheet in ('styles.css', 'scan.css'):
    css = open(os.path.join(ROOT, sheet)).read()
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    bare = re.findall(r'(?:^|[,{}])\s*(\.warn(?:\[[^\]]*\])?)\s*(?=[,{])', css, re.M)
    eq('%s: no bare .warn rule to collide with the verdict state' % sheet, bare, [])

# The verdict colours, written out twice on purpose and kept in step by hand.
#
# scan.css cannot use the shared custom properties for the four verdict panels:
# they overlay a live camera picture, so they have to be opaque enough to read
# against it, which means rgba() with an alpha rather than a hex. Its own
# comment says "kept in step with styles.css by hand. If those change, change
# these" — and records that they were not: the copy was left on the old flat
# luminance palette when the shared one changed, and had no case for `doubt` at
# all, so a reading the scanner refused to judge came out the same colour as
# "searching for a card". The one state whose whole purpose is to look like
# nothing else looked like nothing.
#
# A rule that has to be remembered on every commit is a rule that gets
# forgotten on some commit, which is the same reasoning that took the hand-bump
# out of sw.js. Nothing here makes scan.css derive its colours — it cannot —
# but the two are held to the same numbers.
def hex_rgb(value):
    value = value.strip().lstrip('#')
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


shared = dict(re.findall(r'(--[a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;',
                         open(os.path.join(ROOT, 'styles.css')).read()))
overlay = open(os.path.join(ROOT, 'scan.css')).read()
# Which shared colour each overlaid panel is the opaque version of. `fault` is
# not a verdict — it is the scanner saying it is broken — and takes the plain
# panel colour rather than one off the verdict ladder.
OVERLAID = [('go', '--go-dim'), ('warn', '--warn-dim'), ('no', '--no-dim'),
            ('doubt', '--doubt-dim'), ('fault', '--panel-2')]
ok_('styles.css still defines the shared palette',
    all(var in shared for _, var in OVERLAID))
for state, var in OVERLAID:
    found = re.search(r'#stage > \.verdict\.%s\s*\{[^}]*?rgba\(\s*(\d+),\s*(\d+),\s*(\d+)'
                      % state, overlay, re.S)
    ok_('the scanner paints a %s panel' % state, found is not None)
    if not found or var not in shared:
        continue
    eq('...in the same colour styles.css calls %s' % var,
       tuple(int(n) for n in found.groups()), hex_rgb(shared[var]))

# Every state the shared file gives a panel colour must have one here too. The
# gap that actually happened was an absence, not a mismatch: `doubt` was added
# to styles.css and never to scan.css, and an absence is invisible to any check
# that only compares the pairs it finds.
painted = set(re.findall(r'#stage > \.verdict\.([a-z]+)\s*\{', overlay))
eq('the scanner has a panel for every verdict the shared file paints',
   sorted(state for state, _ in OVERLAID if state not in painted), [])

# --- every element the page reaches for actually exists --------------------
#
# A page collects its controls once, by id, into an `el` object — and a
# renamed id does not fail there. `getElementById` returns null, `el.thing`
# is null, and what happens next is either a TypeError deep inside a render
# that runs twice a second, or, worse, a button that quietly does nothing for
# the rest of the shift. Neither says which id went missing.
COLLECTORS = [
    ('live.html', 'live.html'),
    ('journal.html', 'journal.html'),
    ('scan.html', 'scan.js'),
    ('index.html', 'ui.js'),
    ('snaps.html', 'snaps.html'),
]
for page, where in COLLECTORS:
    markup = open(os.path.join(ROOT, page)).read()
    script = markup if where == page else open(os.path.join(ROOT, where)).read()
    have = set(re.findall(r'\bid="([^"]+)"', markup))

    # Both shapes: the one-at-a-time calls, and the list handed to the
    # collector loop that most of these pages build their `el` object with.
    wanted = set(re.findall(r"""getElementById\(\s*['"]([^'"]+)['"]\s*\)""", script))
    anchor = script.find('var el = {}')
    if anchor != -1:
        stop = script.index('.forEach', anchor)
        start = script.rindex('[', 0, stop)
        wanted |= set(re.findall(r"'([^']+)'", script[start:stop]))

    ok_('%s reaches for some elements' % page, len(wanted) > 3)
    eq('%s: every element it reaches for is in the markup' % page,
       sorted(w for w in wanted if w not in have), [])

# --- can it be read at all -------------------------------------------------
#
# The palette is dark on purpose — this is looked at through a windscreen at
# night, and a light panel in a dark car is a lamp pointed at the driver. What
# was wrong was not the darkness but the steps between the darks: the panel
# every card and key is filled with measured 1.11:1 against the background and
# the border round it 1.31:1, which is to say the boxes were not boxes. Turned
# up in daylight they washed into one flat rectangle.
#
# WCAG's ratio is the only non-subjective thing to hold this to, so it is what
# is held to. Text at 4.5:1, large text and the boundary of a control at 3:1.
def relative_luminance(colour):
    colour = colour.strip().lstrip('#')
    channels = []
    for i in (0, 2, 4):
        c = int(colour[i:i + 2], 16) / 255.0
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast(a, b):
    la, lb = relative_luminance(a), relative_luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


# (what is drawn, what it is drawn on, the ratio it has to reach, why)
READABILITY = [
    ('--text', '--bg', 4.5, 'body text'),
    ('--muted', '--bg', 4.5, 'the labels under every figure'),
    ('--muted', '--panel', 4.5, 'the same labels inside a card'),
    ('--muted', '--panel-2', 4.5, 'and inside a key'),
    ('--text', '--go-dim', 4.5, 'the rate on an ACCEPT panel'),
    ('--text', '--warn-dim', 4.5, 'the rate on a CLOSE CALL panel'),
    ('--text', '--no-dim', 4.5, 'the rate on a PASS panel'),
    ('--text', '--doubt-dim', 4.5, 'the rate on a panel that refused to judge'),
    # The verdict words. Never drawn below 18px bold — see .verdict-label —
    # which is where the standard asks 3:1 rather than 4.5:1. Green saturates
    # before it reaches 4.5 against the green it sits on: there is no lighter
    # green that is still green, and darkening the panel would break the
    # brightest-to-darkest ladder that carries the verdict without colour.
    ('--go', '--go-dim', 3.0, 'the word ACCEPT'),
    ('--warn', '--warn-dim', 4.5, 'the words CLOSE CALL'),
    ('--no', '--no-dim', 4.5, 'the word PASS'),
    ('--doubt', '--doubt-dim', 4.5, 'the word on a refused reading'),
    # A rig that cannot see: the word where the verdict goes and the line under
    # it, both red on the page's own black — live.html's `.verdict.blind`. The
    # line is ordinary-sized text, so it is held to 4.5 and not to the 3:1 the
    # big word would be allowed.
    ('--no', '--bg', 4.5, 'the words on a rig that cannot see, and the line under them'),
]

palette = dict(re.findall(r'(--[a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;',
                          open(os.path.join(ROOT, 'styles.css')).read()))
for fg, bg, floor, what in READABILITY:
    if fg not in palette or bg not in palette:
        ok_('styles.css defines %s and %s' % (fg, bg), False)
        continue
    got = contrast(palette[fg], palette[bg])
    ok_('%s reads against what it sits on (%.2f:1, needs %.1f)' % (what, got, floor),
        got >= floor)

# A box has to look like a box. This is the one that was actually failing, and
# it is not about text: a key, a card and the bar of controls are all filled
# with `--panel` or `--panel-2` and identified by nothing else.
for fill, floor, what in (('--panel', 1.45, 'a card against the page'),
                          ('--panel-2', 1.45, 'a key against the page')):
    got = contrast(palette[fill], palette['--bg'])
    ok_('%s is visible as a shape (%.2f:1)' % (what, got), got >= floor)
# ...and the border, which is what carries the edge where two panels meet.
for on in ('--panel', '--panel-2'):
    got = contrast(palette['--line'], palette[on])
    ok_('a border reads against %s (%.2f:1)' % (on, got), got >= 1.9)

# The ladder the whole verdict design rests on: with no colour vision at all,
# take-it is the brightest panel and leave-it is the darkest. Any change to
# these four that reverses the order silently removes the fallback.
ladder = [relative_luminance(palette[v]) for v in
          ('--go-dim', '--warn-dim', '--doubt-dim', '--no-dim')]
eq('the verdict panels still run brightest to darkest',
   ladder, sorted(ladder, reverse=True))

# ...and the same again at night. After civil dusk live.html swaps the greys
# and the verdict fills for darker ones (`html.night`, showNight); the panel
# it paints then is held to exactly the day's floors, read out of that rule
# over the day's palette, so a night token that drops a label below 4.5:1 or
# turns the ladder over fails here by name.
_night_rule = re.search(r'html\.night\s*\{([^}]*)\}',
                        open(os.path.join(ROOT, 'live.html'), encoding='utf-8').read())
_night = dict(re.findall(r'(--[a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;',
                         _night_rule.group(1))) if _night_rule else {}
ok_('live.html has a night palette, and it darkens the page, the words and the labels',
    all(k in _night for k in ('--bg', '--text', '--muted', '--panel'))
    and all(relative_luminance(_night[k]) < relative_luminance(palette[k])
            for k in ('--bg', '--text', '--muted', '--panel')))
night = dict(palette, **_night)
for fg, bg, floor, what in READABILITY:
    got = contrast(night[fg], night[bg])
    ok_('at night, %s reads against what it sits on (%.2f:1, needs %.1f)'
        % (what, got, floor), got >= floor)
for fill, floor, what in (('--panel', 1.45, 'a card against the page'),
                          ('--panel-2', 1.45, 'a key against the page')):
    got = contrast(night[fill], night['--bg'])
    ok_('at night, %s is visible as a shape (%.2f:1)' % (what, got), got >= floor)
for on in ('--panel', '--panel-2'):
    got = contrast(night['--line'], night[on])
    ok_('at night, a border reads against %s (%.2f:1)' % (on, got), got >= 1.9)
ladder = [relative_luminance(night[v]) for v in
          ('--go-dim', '--warn-dim', '--doubt-dim', '--no-dim')]
eq('at night, the verdict panels still run brightest to darkest',
   ladder, sorted(ladder, reverse=True))

# Every file has to agree about when the page lays itself out across the screen
# rather than down it, or a page spends a range of sizes half in one design and
# half in the other.
#
# That used to be `(orientation: landscape) and (max-height: 620px)`, and the
# height term was the mistake. It was written when the only landscape targets
# were an 800x480 touchscreen and a 1024x600 HDMI panel, and it silently
# excluded every larger one: a 1280x800 panel — a tablet on its side, which is
# what the rig ended up bolted to — is landscape and 800px tall, so it missed
# by 180 pixels and got the phone design. Measured there: a 460px column down
# the middle of a 1280px screen, the readout stacked above the picture instead
# of beside it, and the verdict pushed 221px off the top of the glass.
#
# Landscape alone now. It says exactly what it means — this screen is wider
# than it is tall, so use the width — and there is no size of landscape screen
# for which the answer is different.
conditions = set()
for name in SHEETS:
    for css in style_blocks(name):
        conditions |= set(re.findall(r'@media \(orientation: landscape\)([^{]*)\{', css))
# The third is live.html's type step for the rig's own 1024x600 and larger,
# which changes sizes and nothing about where anything goes: a squeeze the
# other way, inside the wide layout as the 380px one is.
eq('every file switches to the across-the-screen layout at the same point',
   sorted(c.strip() for c in conditions),
   ['', 'and (max-height: 380px)', 'and (min-width: 1000px) and (min-height: 560px)'])
# ...and the narrow-panel rules are an extra squeeze inside the wide layout,
# not a third design. A file that only had the 380px block would be applying
# them without the layout they adjust.
for name in SHEETS:
    css = '\n'.join(style_blocks(name))
    narrow = 'and (max-height: 380px)' in css
    wide = re.search(r'@media \(orientation: landscape\)\s*\{', css) is not None
    ok_('%s: the 3.5-inch rules come with the layout they adjust' % name,
        wide or not narrow)

# Every page is somebody's home screen icon and somebody's browser tab. Only
# the keypad ever named one; the rest fell through to a /favicon.ico this
# server does not have.
for name in PAGES:
    head = open(os.path.join(ROOT, name)).read().split('</head>')[0]
    ok_('%s names an icon' % name, 'rel="icon"' in head)
    ok_('%s names a home-screen icon' % name, 'rel="apple-touch-icon"' in head)
    eq('%s paints the same browser chrome as the others' % name,
       re.findall(r'name="theme-color" content="([^"]+)"', head), ['#0b0f14'])

# --- the caption under the map, and the budget it has to keep ---------------
#
# live.html's map mode produces one figure and puts it in one row of the panel.
# That row used to have its budget written in a comment beside a single call —
# "short on purpose, this line is a row of the panel" — and nothing anywhere
# enforced it, so twelve of the twenty-one forms the caption can take ran past
# a row — off ten of its branches — and the longest ran to six, which left the
# map 104px on the 3.5" hat: under the 120px the check further down already
# calls a map rather than a texture. That longest one was the only sentence
# with no length of its own, and no check had ever been given it.
#
# The budget is now in live.html's own <style>, as a clamp in ROWS, and it is
# two rows on a dashboard panel and three on the hat. Both numbers are measured
# off the detour line — the only thing this mode produces — with both of its
# hedges: that line is two rows in the 388px column of an 800x480 panel and
# three in the 228px column of a 480x320 one. One row was never a budget that
# could be kept, and this file is where that is proved rather than asserted.
#
# Every sentence below is filled at its worst: the longest form of each
# optional clause, and, for the one line that carries a place read off a card,
# a name of the widest characters the font has. Widths, not lengths, decide
# this — 32 characters of the owner's own real place names come out two rows
# and 32 W's come out three.
#
# The one interpolation that is not a number is the place name on the
# misread-pin line, and its width is not this file's to choose: live.html cuts
# it to PLACE_SHOWN, so PLACE_SHOWN is read out of live.html and the worst case
# is built from it. Written out here instead, the whole measurement would go on
# passing with the cut removed — the check would be measuring its own fixture
# rather than the page, which is this project's sixth fault class.
live_src = open(os.path.join(ROOT, 'live.html')).read()
_bound = re.search(r'var PLACE_SHOWN = (\d+);', live_src)
ok_('live.html bounds the place name it puts in the map caption',
    _bound is not None)
# ...and the line itself has to be the thing that is bounded. `esc()` belonged
# to the popup markup and was escaping a string on its way to textContent, so
# 39% of this driver's own places printed `&amp;` in this row; both faults are
# refused by the same line.
ok_('...and the misread-name line is the line that uses it',
    re.search(r'if \(badEnd\) return shortPlace\(badEnd\)', live_src)
    is not None)
WIDEST_PLACE = 'W' * (int(_bound.group(1)) if _bound else 60) + '…'
# ...and the shorter cut the lines naming a pin a card contradicts use: they
# carry two figures and the rig's repair besides the name, and at
# PLACE_SHOWN's twenty widest letters both of those lines ran past two rows
# at 800x480.
_disc = re.search(r'var DISC_PLACE_SHOWN = (\d+);', live_src)
ok_('live.html bounds the place name in the lines a card contradicts',
    _disc is not None)
WIDEST_DISC = 'W' * (int(_disc.group(1)) if _disc else 60) + '…'
CAPTION_LINES = [
    ('no map-view.js',
     'map-view.js did not load, so there is no map here.'),
    ('a card naming nowhere',
     'this card names nowhere yet — ⌖ Scan reads it off your phone'),
    ('no card at all',
     'no card read yet — nothing to put on a map'),
    # ...and a card that has gone: its reading stale (cardOnMap), its pins and
    # figure dropped, with nothing in the car, or with an order whose run is
    # what the map then shows.
    ('no card up',
     'no card up — nothing to put on a map'),
    ('no card up, an order in the car',
     'no card up — only the order in your car'),
    ('loading',
     'loading the map…'),
    ('no signal',
     'no signal — the map needs it for both its code and its tiles. '
     '⛶ Phone puts the picture back.'),
    ('still asking',
     'placing 2 of 3 — still asking'),
    # The figure, in all the shapes it comes in. The longest is the wordier of
    # the two verdicts and a place with no pin. `missed` cannot exceed 1 here —
    # a detour needs the pickup and the held job both placed, so the dropoff
    # is the only name left to be missing. There is no age of the fix on it
    # any more: the fix is the card's own, taken when the card landed.
    ('the figure',
     '+3.2 mi out of your way — straight lines, not roads'),
    ('the figure, on your way',
     'this pickup is on your way — straight lines, not roads'),
    ('the figure at its longest',
     'this pickup is on your way — straight lines, not roads · 1 not asked',
     'this pickup is on your way — straight lines, not roads'),
    # Both words, because they are not interchangeable anywhere else in this
    # project: "not found" is a geocoder that answered nothing and "not asked"
    # is a lookup that could not be made. Same length, and measured anyway —
    # the rule here is that nothing reaches this row unmeasured.
    ('the figure at its longest, nothing found',
     'this pickup is on your way — straight lines, not roads · 1 not found',
     'this pickup is on your way — straight lines, not roads'),
    ('a pin in the wrong state',
     WIDEST_PLACE + ' is 3619 mi away — almost certainly a misread name, '
     'so no distance',
     WIDEST_PLACE + ' is 3619 mi away — almost certainly a misread name'),
    # Why this card, or the one the order in the car came from, gives nothing
    # to measure from — MV.fixLine's words, every one. The error figure at
    # four digits: the gate refuses anything over FIX_ERR_MAX, so "rough" can
    # carry any figure above it.
    ('this card, no fix',
     'this card came up without a GPS fix'),
    ('this card, a rough fix',
     'GPS fix on this card too rough to measure from (±9999 m)'),
    ('this card, no accuracy',
     'GPS on this card gave no accuracy to measure from'),
    ('this card, no mode',
     'GPS on this card had no 2D/3D fix to measure from'),
    ('this card, a frozen fix',
     'GPS on this card was stuck on one spot, so nothing to measure from'),
    ('this card, not judged',
     'GPS fix on this card was never judged, so nothing to measure from'),
    ('the held card, no fix',
     'the order in your car came up without a GPS fix, so its end cannot be '
     'checked'),
    ('the held order, no card kept',
     'the rig kept no card for the order in your car, so its end cannot be '
     'checked'),
    ('the held card, a rough fix',
     'GPS fix on the order in your car too rough to check its end (±9999 m)'),
    ('the held card, no accuracy',
     'GPS on the order in your car gave no accuracy to check its end'),
    ('the held card, no mode',
     'GPS on the order in your car had no 2D/3D fix to check its end'),
    ('the held card, a frozen fix',
     'GPS on the order in your car was stuck on one spot, so its end cannot '
     'be checked'),
    ('the held card, not judged',
     'GPS fix on the order in your car was never judged, so its end cannot '
     'be checked'),
    # ...why a card is no yardstick — MV.againstCard's words...
    ('this card, no distance',
     'this card states no distance to check the pickup pin against'),
    ('this card, untrusted',
     'the rig does not trust this card\'s distance, so the pickup pin cannot '
     'be checked'),
    ('this card, Early look',
     'an Early look card may not measure from your car — no yardstick yet'),
    ('this card, one leg',
     'this kind of card may not count the drive to the pickup — no yardstick '
     'yet'),
    ('the held card, no distance',
     'the order in your car stated no distance to check its end against'),
    ('the held card, untrusted',
     'the rig did not trust the distance on the order in your car, so its end '
     'cannot be checked'),
    ('the held card, Early look',
     'the order in your car was an Early look card — no yardstick yet for its '
     'end'),
    ('the held card, one leg',
     'the order in your car is a kind of card with no yardstick yet for its '
     'end'),
    # ...and a pin a card contradicts, at its widest: the place cut to
    # DISC_PLACE_SHOWN in its widest letter, a straight line under farFrom's
    # 75 miles (past that the misread-name line above is said instead), a
    # three-figure distance, and the rig's own repair named. These declared
    # ", so past the card's 9.4 mi" as what the hat's clamp may eat, and what
    # that left readable was "the map's McDonald's is 21.8 mi from you" — a
    # distance with nothing saying the pin is refused, read at a glance as a
    # pickup that far away. The refusal now LEADS: whatever the clamp keeps
    # starts "wrong pin for", so the figure it keeps is the size of the map's
    # mistake and cannot be read as the job's. The `, past` clause carries the
    # card's figure with its hedge, so those two still go together.
    ('a pickup this card contradicts',
     "wrong pin for " + WIDEST_DISC + " — 74.9 mi from you, past the card's "
     "99.9 mi (rig-corrected)",
     "wrong pin for " + WIDEST_DISC + " — 74.9 mi from you"),
    ('a held end its card contradicts',
     "wrong pin for " + WIDEST_DISC + " — 74.9 mi from your order's card, "
     "past its 99.9 mi (rig-corrected)",
     "wrong pin for " + WIDEST_DISC + " — 74.9 mi from your order's card"),
    ('the held job has no address',
     'the order in your car has no address on record — ⌖ Scan reads it '
     'off your phone'),
    ('nothing in the car',
     'nothing in the car to compare this against'),
    ('the card says no pickup',
     'this card does not say where to collect it'),
    ('the geocoder was unreachable, pickup',
     'could not reach the geocoder for the pickup — no network, or busy. '
     'Coming back asks again.'),
    ('the geocoder had nothing, pickup',
     'the geocoder found nothing for the pickup — usually a misread name'),
    ('the geocoder was unreachable, held',
     'could not reach the geocoder for where your order is going'),
    ('the geocoder had nothing, held',
     'the geocoder found nothing for where your order is going'),
    # The NucBox's lines (README "The NucBox at home"). Measuring the road is
    # progress, said while the router is asked. The road figure is labelled
    # "road mi" and carries no hedge of its own; the straight line keeps its
    # label and says in its tail which of the NucBox's services did not
    # answer — the search first, because then every pin is the public map's.
    # Each at its longest: a place with no pin and the NucBox note together.
    ('measuring by road',
     'measuring the detour by road…'),
    ('the road figure',
     '+13.2 road mi out of your way'),
    ('the road figure at its longest',
     'this pickup is on your way by road · 1 not found · NucBox down, public map used',
     'this pickup is on your way by road'),
    ('the figure, the NucBox down',
     'this pickup is on your way — straight lines, not roads · 1 not asked '
     '· NucBox down, public map used',
     'this pickup is on your way — straight lines, not roads'),
    # ...and the NucBox down after it answered a place — a corner, a street's
    # stretch — whose pin is its own, so the public map had only the rest.
    ('the road figure, the NucBox down after a place',
     'this pickup is on your way by road · 1 not found · NucBox down, public '
     'map for the rest',
     'this pickup is on your way by road'),
    ('the figure, its router down',
     'this pickup is on your way — straight lines, not roads · 1 not found '
     '· NucBox router down',
     'this pickup is on your way — straight lines, not roads'),
    # ...and a figure to a numberless street: the straight line's at every
    # point of its stretch in the card (MV.stretchSpan), a range when its
    # least and most print differently. The range is in what the clamp
    # keeps, so the figure is never a single number for a point the card
    # never named; the router is not asked, and the tail says why — or, the
    # NucBox down after it answered the street, that instead.
    ('the figure, anywhere on a street',
     '+13.2–13.6 mi out of your way — straight lines, not roads · 1 not found '
     '· whole street, no road figure',
     '+13.2–13.6 mi out of your way — straight lines, not roads'),
    ('the figure, anywhere on a street, the NucBox down after it',
     '+13.2–13.6 mi out of your way — straight lines, not roads · 1 not asked '
     '· NucBox down, public map for the rest',
     '+13.2–13.6 mi out of your way — straight lines, not roads'),
    ('the figure, no road found',
     'this pickup is on your way — straight lines, not roads · 1 not found '
     '· no road found',
     'this pickup is on your way — straight lines, not roads'),
    # ...and a road figure the router DID give and the page will not state:
    # a point moved more than MV.SNAP_MI to reach a road, a figure below zero
    # past the panel's rounding, the relay refusing the road question (a bug).
    # Never with the search's own note: with " · NucBox down, public map used"
    # before it, every one of these ran past two rows at 800x480.
    ('the figure, a pin off the roads',
     'this pickup is on your way — straight lines, not roads · 1 not found '
     '· a pin over 0.2 mi off road',
     'this pickup is on your way — straight lines, not roads'),
    ('the figure, the router took other roads',
     'this pickup is on your way — straight lines, not roads · 1 not found '
     '· router took different roads',
     'this pickup is on your way — straight lines, not roads'),
    ('the figure, the road question refused',
     'this pickup is on your way — straight lines, not roads · 1 not found '
     '· road question refused, a bug',
     'this pickup is on your way — straight lines, not roads'),
    # ...and the run through a batched trip's dropoffs leaving out two it
    # could not place (MV.routeLadder's `skip`; the owner's snap of 24 Oct),
    # said after the figure's own tail, the most dropoffs a planner page has
    # room to list before its end.
    ('the figure, the run skipping a batched trip\'s dropoffs',
     'this pickup is on your way — straight lines, not roads · 1 not found '
     '· route skips 2 dropoffs, not found',
     'this pickup is on your way — straight lines, not roads'),
    # ...and why the NucBox gave no pin — MV.nbxRefusal's words, every one, at
    # the widest name, three-figure distances and the rig's repair named. The
    # refusal LEADS, as the disc's own lines do, so what a clamp keeps opens
    # with "no pin for" and says why in a few words; the disc's figures, with
    # the repair beside them, are the declared tail. Written first with the
    # figures inside the sentence, six of these ran past three rows on the hat.
    ('no pin, none in this card',
     "no pin for " + WIDEST_DISC + " — none fit the card · within 99.9 mi "
     "(rig-corrected) of you, nearest 74.9 mi",
     "no pin for " + WIDEST_DISC + " — none fit the card"),
    ('no pin, none in the held card',
     "no pin for " + WIDEST_DISC + " — none fit its card · within 99.9 mi "
     "(rig-corrected), nearest 74.9 mi",
     "no pin for " + WIDEST_DISC + " — none fit its card"),
    ('no pin, none in sixty miles of the held card',
     "no pin for " + WIDEST_DISC + " — none found · within 60 mi of your "
     "order's card, nearest 74.9 mi",
     "no pin for " + WIDEST_DISC + " — none found"),
    ('no pin, nothing at all',
     "no pin for " + WIDEST_DISC + " — the NucBox found nothing for it"),
    ('no pin, several in this card',
     "no pin for " + WIDEST_DISC + " — 10 fit the card and disagree · within "
     "99.9 mi (rig-corrected) of you",
     "no pin for " + WIDEST_DISC + " — 10 fit the card and disagree"),
    ('no pin, several in the held card',
     "no pin for " + WIDEST_DISC + " — 10 fit its card and disagree · within "
     "99.9 mi (rig-corrected)",
     "no pin for " + WIDEST_DISC + " — 10 fit its card and disagree"),
    ('no pin, several in sixty miles of the held card',
     "no pin for " + WIDEST_DISC + " — 10 found and they disagree · within 60 mi "
     "of your order's card",
     "no pin for " + WIDEST_DISC + " — 10 found and they disagree"),
    # ...and an end the run was routed to the general area of (the owner,
    # 24 Oct: MV.routeLadder's 'area' rung), its refusal carrying the area's
    # words in place of the disc's figures (MV.routeSaid): ten answers, the
    # NucBox's limit, a mile apart, AREA_MI — the widest it can say; and a
    # street found and not the door, one answer. Written first with the
    # rung's words after the disc's tail, the sentence ran past two rows at
    # 800x480 and its chip past three on the hat.
    ('no pin, several in the held card, routed to their area',
     "no pin for " + WIDEST_DISC + " — 10 fit its card and disagree · ≈ routed, "
     "10 within 1.0 mi",
     "no pin for " + WIDEST_DISC + " — 10 fit its card and disagree"),
    ('no pin, a door the map does not hold, routed to its street\'s area',
     "no pin for " + WIDEST_DISC + " — street found, not that door · ≈ routed to area",
     "no pin for " + WIDEST_DISC + " — street found, not that door"),
    # ...and the owner's DoorDash snap of 24 Oct, 19:23-19:25 ("better to
    # route something than nothing at all"): a list cut at the NucBox's
    # limit that is one area, "10+" at AREA_MI; a door nothing answered,
    # routed to its street's rough area (MV.streetArea), in both of the
    # refusal's "none" forms. (A pickup's area said after ANOTHER end's
    # refusal and its disc's tail was measured here three ways — "≈ route
    # to pickup area, 10+ within 1.0 mi", "≈ route to pickup street area",
    # "≈ pickup area" — and each ran past two rows at 800x480 and its chip
    # past three on the hat, so a pickup's area is said only inside its own
    # refusal, MV.routeSaid, and the row is not kept.)
    ('no pin, a cut list routed to its area',
     "no pin for " + WIDEST_DISC + " — too many to be sure · ≈ routed, 10+ within 1.0 mi",
     "no pin for " + WIDEST_DISC + " — too many to be sure"),
    ('no pin, none in this card, routed to its street\'s area',
     "no pin for " + WIDEST_DISC + " — none fit the card · ≈ routed to street area",
     "no pin for " + WIDEST_DISC + " — none fit the card"),
    ('no pin, none in sixty miles, routed to its street\'s area',
     "no pin for " + WIDEST_DISC + " — none found · ≈ routed to street area",
     "no pin for " + WIDEST_DISC + " — none found"),
    # ...and the distance band (the owner, 25 Oct): several, a cut list, or
    # a long street's points, narrowed by the card's own miles by road
    # (MV.bandPick), said by the card's figure — "88.8", the widest figure a
    # card prints in a tenth.
    ('no pin, several narrowed by the card\'s miles',
     "no pin for " + WIDEST_DISC + " — 10 fit its card and disagree · ≈ routed, "
     "by card's 88.8 mi",
     "no pin for " + WIDEST_DISC + " — 10 fit its card and disagree"),
    ('no pin, a cut list narrowed by the card\'s miles',
     "no pin for " + WIDEST_DISC + " — too many to be sure · ≈ routed, by card's 88.8 mi",
     "no pin for " + WIDEST_DISC + " — too many to be sure"),
    ('no pin, a long street narrowed by the card\'s miles',
     "no pin for " + WIDEST_DISC + " — none found · ≈ routed, by card's 88.8 mi",
     "no pin for " + WIDEST_DISC + " — none found"),
    # ...and a DoorDash card printing only "Customer dropoff", its trip drawn
    # to the street DoorDash's map labelled (the owner, 27 Oct: MV.guessDisc,
    # the ladder's 'guess' rung), said after the caption's own tail.
    ('the figure, the trip drawn to DoorDash\'s map label',
     'this pickup is on your way by road · 1 not found · trip: ≈ from DoorDash\'s map',
     'this pickup is on your way by road'),
    # (After a refusal already carrying an area's words — "no pin for <W…> —
    # too many to be sure · ≈ routed, 10+ within 1.0 mi" — it ran past two
    # rows at 800x480, so there it is not said (MV.routeSaid) and the row is
    # not kept; beside "1 not found · NucBox router down" it did too.) ...and
    # after the straight-line figure:
    ('the straight-line figure, the trip to DoorDash\'s map label',
     'this pickup is on your way — straight lines, not roads · 1 not found '
     '· trip: ≈ from DoorDash\'s map',
     'this pickup is on your way — straight lines, not roads'),
    ('no pin, several with no fix',
     "no pin for " + WIDEST_DISC + " — 10 found · no GPS fix to choose between "
     "them",
     "no pin for " + WIDEST_DISC + " — 10 found"),
    ('no pin, several with no fix on the held card',
     "no pin for " + WIDEST_DISC + " — 10 found · no GPS fix on your order's "
     "card to choose between them",
     "no pin for " + WIDEST_DISC + " — 10 found"),
    ('no pin, a cross street with no street index',
     "no pin for " + WIDEST_DISC + " — no street index to ask"),
    # ...and a corner asked of the street index (README "The NucBox at
    # home"): its streets meeting in several places, in none, running
    # together, one of them not in the index, or not two names at all; and a
    # numberless street's stretch too long to send. Fifty meetings is the
    # index's own limit, so the widest count it can say. Written first as
    # "its streets meet in 50 places in the card" and "...do not meet in the
    # card", four of these ran past two rows at 800x480 (and "no corner fits
    # the card" and "no corner in the card" one each, so a corner with none
    # inside the card is said in "none fit the card"'s own words), and
    # "cross streets need the NucBox street index", "...need the street
    # index" and "its streets run together, no one corner" past three on the
    # hat.
    ('no pin, a corner in several places in this card',
     "no pin for " + WIDEST_DISC + " — 50 corners fit the card · "
     "within 99.9 mi (rig-corrected) of you",
     "no pin for " + WIDEST_DISC + " — 50 corners fit the card"),
    ('no pin, a corner in several places in the held card',
     "no pin for " + WIDEST_DISC + " — 50 corners fit its card · "
     "within 99.9 mi (rig-corrected)",
     "no pin for " + WIDEST_DISC + " — 50 corners fit its card"),
    ('no pin, a corner in several places in sixty miles of the held card',
     "no pin for " + WIDEST_DISC + " — 50 corners found · within 60 mi "
     "of your order's card",
     "no pin for " + WIDEST_DISC + " — 50 corners found"),
    ('no pin, a corner in several places with no fix on the held card',
     "no pin for " + WIDEST_DISC + " — 50 corners found · no GPS fix on "
     "your order's card to choose between them",
     "no pin for " + WIDEST_DISC + " — 50 corners found"),
    ('no pin, a corner not in sixty miles of the held card',
     "no pin for " + WIDEST_DISC + " — its streets do not meet · within 60 mi of "
     "your order's card, nearest 74.9 mi",
     "no pin for " + WIDEST_DISC + " — its streets do not meet"),
    ('no pin, a corner that never meets',
     "no pin for " + WIDEST_DISC + " — its streets do not meet"),
    ('no pin, a corner whose streets run together',
     "no pin for " + WIDEST_DISC + " — its streets run together"),
    ('no pin, a street not on the NucBox',
     "no pin for " + WIDEST_DISC + " — a street name not on the NucBox"),
    ('no pin, not two street names',
     "no pin for " + WIDEST_DISC + " — not two street names"),
    ('no pin, a stretch too long to send',
     "no pin for " + WIDEST_DISC + " — street too long to be sure · the NucBox sends "
     "8000 points at most",
     "no pin for " + WIDEST_DISC + " — street too long to be sure"),
    ('no pin, a door the map does not hold',
     "no pin for " + WIDEST_DISC + " — street found, not that door"),
    # ...and the held end's place asked after it, with nothing of that name
    # (map-view.js pickPlace, the owner's rule of 17 Oct).
    ('no pin, neither the door nor the place on the map',
     "no pin for " + WIDEST_DISC + " — street found, not the door or place"),
    ('no pin, a list cut at the limit',
     "no pin for " + WIDEST_DISC + " — too many to be sure · the NucBox lists 10 "
     "at most",
     "no pin for " + WIDEST_DISC + " — too many to be sure"),
    ('no pin, the rig refused the question',
     "no pin for " + WIDEST_DISC + " — a bug: the rig refused the question"),
    # ...and a numberless street pinned, whose figure is not one answer along
    # its stretch in the card (MV.spanRefusal): refused, with how long it runs.
    ('no figure, a street that runs through this card',
     "no figure for " + WIDEST_DISC + " — the street runs 99.9 mi in the card"),
    ('no figure, a street that runs through the held card',
     "no figure for " + WIDEST_DISC + " — the street runs 99.9 mi in its card"),
    # ...and the held order's restaurant, still ahead on its Trip Planner,
    # measured INTO the figure (MV.detourThrough): the line says so before
    # any tail, so whatever a clamp eats the figure is never read as one
    # measured to the end alone. "incl. restaurant" takes the place of "out
    # of your way" and "this pickup is": beside them, ", restaurant stop
    # included" cut the longest of these short at 800x480. At its longest: a
    # range, more than one stop, a place not asked, the NucBox down after it
    # answered one.
    ('the road figure, the restaurant in it',
     '+13.2 road mi incl. restaurant'),
    ('the road figure, the restaurants in it, at its longest',
     'on your way by road incl. restaurants · 1 not found · NucBox down, public '
     'map for the rest',
     'on your way by road incl. restaurants'),
    ('the figure, the restaurants in it, at its longest',
     '+13.2–13.6 mi incl. restaurants — straight lines, not roads · 1 not asked '
     '· NucBox down, public map for the rest',
     '+13.2–13.6 mi incl. restaurants — straight lines, not roads'),
    ('the figure on your way, the restaurants in it, at its longest',
     'on your way incl. restaurants — straight lines, not roads · 1 not asked '
     '· NucBox down, public map for the rest',
     'on your way incl. restaurants — straight lines, not roads'),
    # ...and why there is no figure with the restaurant in it: no pin for
    # it (the NucBox's refusals and a pin a card contradicts are the lines
    # above, in the held card's words), or a numberless street.
    ('the geocoder was unreachable, held pickup',
     'could not reach the geocoder for where your order is collected'),
    ('the geocoder had nothing, held pickup',
     'the geocoder found nothing for where your order is collected'),
    ('no figure, a held pickup on a street',
     "no figure for " + WIDEST_DISC + " — your order's pickup is a street"),
    # ...and with TWO orders in the car (Stage 6): the figure through both,
    # said "incl. both orders" in "incl. restaurant"'s place and for its
    # reason, at its longest — a range (the two orderings agreeing), a place
    # not asked or not found, the NucBox down after it answered one; and
    # why there is none: the orderings giving two answers, the second order
    # with no end, a street anywhere in the run.
    ('the road figure, both orders in it, at its longest',
     '+13.2–13.6 road mi incl. both orders · 1 not found · NucBox down, public '
     'map for the rest',
     '+13.2–13.6 road mi incl. both orders'),
    ('the road figure on your way, both orders in it, at its longest',
     'on your way by road incl. both orders · 1 not found · NucBox down, public '
     'map for the rest',
     'on your way by road incl. both orders'),
    ('the figure, both orders in it, at its longest',
     '+13.2–13.6 mi incl. both orders — straight lines, not roads · 1 not asked '
     '· NucBox down, public map for the rest',
     '+13.2–13.6 mi incl. both orders — straight lines, not roads'),
    ('the order of two orders\' stops unknown', 'order of stops unknown — no figure'),
    ('the second order with no end on record',
     '② has no address on record — ⌖ Scan reads it off your phone'),
    ('no figure, a street with two orders',
     "no figure for " + WIDEST_DISC + " — a street, with two orders"),
    # ...and the pickup's door off DoorDash's place popup rather than off the
    # card (live.html mapWants): said first in the tail, " · addr from tap", at
    # every length the figure comes in — straight and by road, to a door and
    # to a held street's range, with the restaurant in it — each at its
    # longest with a place not asked. Never beside a NucBox note: with " ·
    # NucBox down, public map for the rest" after it, three of the straight
    # forms ran past two rows at 800x480, so the page drops the tap note
    # there and the pickup pin says it instead.
    ('the figure from a tapped door',
     '+3.2 mi out of your way — straight lines, not roads · addr from tap',
     '+3.2 mi out of your way — straight lines, not roads'),
    ('the figure from a tapped door, at its longest',
     'this pickup is on your way — straight lines, not roads · addr from tap · 1 not '
     'asked',
     'this pickup is on your way — straight lines, not roads'),
    ('the road figure from a tapped door, at its longest',
     'this pickup is on your way by road · addr from tap · 1 not found',
     'this pickup is on your way by road'),
    ('the figure from a tapped door to a held street, at its longest',
     '+13.2–13.6 mi out of your way — straight lines, not roads · addr from tap · 1 not '
     'asked',
     '+13.2–13.6 mi out of your way — straight lines, not roads'),
    ('the figure from a tapped door, the restaurants in it, at its longest',
     '+13.2–13.6 mi incl. restaurants — straight lines, not roads · addr from tap · 1 not '
     'asked',
     '+13.2–13.6 mi incl. restaurants — straight lines, not roads'),
    ('the road figure from a tapped door, the restaurants in it, at its longest',
     'on your way by road incl. restaurants · addr from tap · 1 not found',
     'on your way by road incl. restaurants'),
    # ...and the tapped door with both orders in the car: the same tail, at
    # the longest each two-order figure comes in with a place not asked or not
    # found, and never beside a NucBox note.
    ('the road figure from a tapped door, both orders in it, at its longest',
     '+13.2–13.6 road mi incl. both orders · addr from tap · 1 not found',
     '+13.2–13.6 road mi incl. both orders'),
    ('the road figure on your way from a tapped door, both orders in it, at its longest',
     'on your way by road incl. both orders · addr from tap · 1 not found',
     'on your way by road incl. both orders'),
    ('the figure from a tapped door, both orders in it, at its longest',
     '+13.2–13.6 mi incl. both orders — straight lines, not roads · addr from tap · 1 not '
     'asked',
     '+13.2–13.6 mi incl. both orders — straight lines, not roads'),
]

# ...and the third field, where there is one, is the part that must stay
# READABLE on every panel — the rest being a trailing clause the 3.5" hat may
# ellipsise. FORTY-SEVEN entries have one, and they are four judgements: the
# count of places with no pin, whose tail is ` · 1 not asked` or ` · 1 not
# found` depending on which it was — behind ` · addr from tap` when the
# pickup's door came off DoorDash's place popup and no note follows — with one
# note after it: the NucBox's
# search down (` · NucBox down, public map used`, or `...public map for the
# rest` when it answered a place first), else why the road was not stated
# (` · NucBox router down`, ` · no road found`, ` · a pin over 0.2 mi off
# road`, ` · router took different roads`, ` · road question refused, a
# bug`, ` · whole street, no road figure`) — never a hedge on the figure,
# which a figure to a street carries as its range, in what is kept; the
# consequence of a pin that is plainly
# wrong, whose tail is `, so no distance`; the card's own figure beside a
# pin it contradicts, whose tail is `, past the card's 9.4 mi` with the
# rig's repair named inside it, so the figure and its hedge go together —
# behind "wrong pin for", which the clamp never reaches, so the part kept
# readable is a refusal and never a bare distance; and the disc the NucBox
# searched in, ` · within 99.9 mi (rig-corrected) of you, nearest 74.9 mi`
# (or the limit a cut list or a stretch stopped at), behind "no pin for" and
# the few words saying why — a corner's "50 corners fit the card" among
# them — the same way round; or, where the run was routed to the general
# area of the answers, ` · ≈ routed, 10 within 1.0 mi` in the disc's place
# (`10+` for a cut list, ` · ≈ routed to street area` for a street's, and
# ` · ≈ routed, by card's 1.2 mi` for the distance band's).
# Each is the end of its sentence
# precisely so that it is what a clamp eats; everything before it is a figure
# or a hedge on one.
#
# This comment said "only two entries" while three had a third field, and the
# ledger repeated it. The third is `the figure at its longest, nothing found`,
# added deliberately because "not found" and "not asked" are not
# interchangeable, and then left out of the record of what the clamp eats. The
# two assertions under the table are there so the next entry cannot be added
# without this paragraph being read again.
# Which rows actually DECLARED what may be cut. The normalisation below fills
# the rest in with the whole sentence, and linting those is two assertions that
# cannot fail: `_text.startswith(_text)` and `_drop == ''` are true of every
# string. Only the declared ones are worth checking, and they are the only ones
# the clamp can shorten.
_DECLARED = {row[0] for row in CAPTION_LINES if len(row) > 2}
# Counted here because the prose around this table states both numbers, and
# both had drifted: the paragraph above said two declared tails where there
# are three, and the comment at the foot of the file said the row can say
# twenty things where it can say twenty-one. A number in a comment that
# nothing counts is a number that rots; these fail rather than rot.
eq('the caption table is the size its comments say', len(CAPTION_LINES), 114)
eq('...and fifty-six of its entries declare a tail the clamp may eat',
   len(_DECLARED), 56)
CAPTION_LINES = [(row[0], row[1], row[2] if len(row) > 2 else row[1])
                 for row in CAPTION_LINES]
for _name, _text, _keep in CAPTION_LINES:
    if _name not in _DECLARED:
        continue
    ok_("the caption table's %r keeps a prefix of what it says" % _name,
        _text.startswith(_keep))
    _drop = _text[len(_keep):]
    ok_('...and drops only a whole clause off %r (%r)' % (_name, _drop),
        _drop == '' or _drop.startswith(' · ') or _drop.startswith(', so ')
        or _drop.startswith(', past '))
    # ...and a line that names a pin a card contradicts says so BEFORE any
    # figure, in what the clamp keeps. Its kept part used to be "the map's
    # McDonald's is 21.8 mi from you": a distance, refusal clipped off.
    if 'contradicts' in _name:
        ok_('...and what the clamp keeps of %r opens with the refusal' % _name,
            _keep.startswith('wrong pin for '))
    # ...and the NucBox's refusals the same way: "no pin for" first.
    if _name.startswith('no pin'):
        ok_('...and what the clamp keeps of %r opens with the refusal' % _name,
            _keep.startswith('no pin for '))

# ...and the chip each one is drawn as (MV.captionChip, map-view.js), or none.
# A refusal under the map is a chip the way a notice is — the state in
# capitals and the reason after the dot, the sentence a tap away — and the
# figure, and a line saying one is coming, are not refusals and are drawn as
# written. Every row of the table above is held to exactly this: a row not
# named here must draw no chip, and a row named here that the page draws as
# its sentence, or as another chip, fails by name. So a refusal written
# without a chip, or a chip that drops the reason, is caught where it is
# measured. The place is the page's own cut, as above.
CAPTION_CHIPS = {
    "a card naming nowhere":
        "NO PLACES · ⌖ Scan reads them",
    "no card at all":
        "NO CARD YET · nothing to map",
    "no card up":
        "NO CARD UP · nothing to map",
    "no card up, an order in the car":
        "NO CARD UP · your order only",
    "no signal":
        "NO SIGNAL · ⛶ Phone for the picture",
    "a pin in the wrong state":
        "MISREAD PIN · " + WIDEST_PLACE + ", far off",
    "this card, no fix":
        "NO FIX · on this card",
    "this card, a rough fix":
        "ROUGH FIX · on this card ±9999 m",
    "this card, no accuracy":
        "NO FIX · no accuracy on this card",
    "this card, no mode":
        "NO FIX · no 2D/3D on this card",
    "this card, a frozen fix":
        "STUCK FIX · on this card",
    "this card, not judged":
        "NO FIX · never judged on this card",
    "the held card, no fix":
        "NO FIX · on your order's card",
    "the held order, no card kept":
        "NO CARD KEPT · for your order, end unchecked",
    "the held card, a rough fix":
        "ROUGH FIX · on your order's card ±9999 m",
    "the held card, no accuracy":
        "NO FIX · no accuracy on your order's card",
    "the held card, no mode":
        "NO FIX · no 2D/3D on your order's card",
    "the held card, a frozen fix":
        "STUCK FIX · on your order's card",
    "the held card, not judged":
        "NO FIX · never judged on your order's card",
    "this card, no distance":
        "UNCHECKED · card states no distance",
    "this card, untrusted":
        "UNCHECKED · card's distance untrusted",
    "this card, Early look":
        "UNCHECKED · Early look card",
    "this card, one leg":
        "UNCHECKED · card may not count the drive",
    "the held card, no distance":
        "UNCHECKED · your order's card states no distance",
    "the held card, untrusted":
        "UNCHECKED · your order's distance untrusted",
    "the held card, Early look":
        "UNCHECKED · your order's Early look card",
    "the held card, one leg":
        "UNCHECKED · your order's kind of card",
    "a pickup this card contradicts":
        "WRONG PIN · " + WIDEST_DISC + ", past the card's distance",
    "a held end its card contradicts":
        "WRONG PIN · " + WIDEST_DISC + ", past its card's distance",
    "the held job has no address":
        "NO FIGURE · your order's end unknown, ⌖ Scan",
    "nothing in the car":
        "NO FIGURE · nothing in the car",
    "the card says no pickup":
        "NO FIGURE · card names no pickup",
    "the geocoder was unreachable, pickup":
        "NOT ASKED · pickup, no network or busy",
    "the geocoder had nothing, pickup":
        "NOT FOUND · pickup, likely misread",
    "the geocoder was unreachable, held":
        "NOT ASKED · your order's end",
    "the geocoder had nothing, held":
        "NOT FOUND · your order's end",
    "no pin, none in this card":
        "NO PIN · " + WIDEST_DISC + ", none fit the card",
    "no pin, none in the held card":
        "NO PIN · " + WIDEST_DISC + ", none fit its card",
    "no pin, none in sixty miles of the held card":
        "NO PIN · " + WIDEST_DISC + ", none found",
    "no pin, nothing at all":
        "NO PIN · " + WIDEST_DISC + ", nothing found",
    "no pin, several in this card":
        "NO PIN · " + WIDEST_DISC + ", 10 fit the card and disagree",
    "no pin, several in the held card":
        "NO PIN · " + WIDEST_DISC + ", 10 fit its card and disagree",
    "no pin, several in sixty miles of the held card":
        "NO PIN · " + WIDEST_DISC + ", 10 found and they disagree",
    "no pin, several in the held card, routed to their area":
        "NO PIN · " + WIDEST_DISC + ", ≈ routed, 10 within 1.0 mi",
    "no pin, a door the map does not hold, routed to its street's area":
        "NO PIN · " + WIDEST_DISC + ", ≈ routed to area",
    "no pin, a cut list routed to its area":
        "NO PIN · " + WIDEST_DISC + ", ≈ routed, 10+ within 1.0 mi",
    "no pin, none in this card, routed to its street's area":
        "NO PIN · " + WIDEST_DISC + ", ≈ routed to street area",
    "no pin, none in sixty miles, routed to its street's area":
        "NO PIN · " + WIDEST_DISC + ", ≈ routed to street area",
    "no pin, several narrowed by the card's miles":
        "NO PIN · " + WIDEST_DISC + ", ≈ routed, by card's 88.8 mi",
    "no pin, a cut list narrowed by the card's miles":
        "NO PIN · " + WIDEST_DISC + ", ≈ routed, by card's 88.8 mi",
    "no pin, a long street narrowed by the card's miles":
        "NO PIN · " + WIDEST_DISC + ", ≈ routed, by card's 88.8 mi",
    "no pin, several with no fix":
        "NO PIN · " + WIDEST_DISC + ", no fix to choose",
    "no pin, several with no fix on the held card":
        "NO PIN · " + WIDEST_DISC + ", no fix on its card",
    "no pin, a cross street with no street index":
        "NO PIN · " + WIDEST_DISC + ", no street index",
    "no pin, a corner in several places in this card":
        "NO PIN · " + WIDEST_DISC + ", 50 corners fit the card",
    "no pin, a corner in several places in the held card":
        "NO PIN · " + WIDEST_DISC + ", 50 corners fit its card",
    "no pin, a corner in several places in sixty miles of the held card":
        "NO PIN · " + WIDEST_DISC + ", 50 corners found",
    "no pin, a corner in several places with no fix on the held card":
        "NO PIN · " + WIDEST_DISC + ", no fix on its card",
    "no pin, a corner not in sixty miles of the held card":
        "NO PIN · " + WIDEST_DISC + ", its streets do not meet",
    "no pin, a corner that never meets":
        "NO PIN · " + WIDEST_DISC + ", its streets do not meet",
    "no pin, a corner whose streets run together":
        "NO PIN · " + WIDEST_DISC + ", its streets run together",
    "no pin, a street not on the NucBox":
        "NO PIN · " + WIDEST_DISC + ", street not on the NucBox",
    "no pin, not two street names":
        "NO PIN · " + WIDEST_DISC + ", not two street names",
    "no pin, a stretch too long to send":
        "NO PIN · " + WIDEST_DISC + ", street too long to be sure",
    "no pin, a door the map does not hold":
        "NO PIN · " + WIDEST_DISC + ", street found, not that door",
    "no pin, neither the door nor the place on the map":
        "NO PIN · " + WIDEST_DISC + ", no door or place",
    "no pin, a list cut at the limit":
        "NO PIN · " + WIDEST_DISC + ", too many to be sure",
    "no pin, the rig refused the question":
        "NO PIN · " + WIDEST_DISC + ", a bug: question refused",
    "no figure, a street that runs through this card":
        "NO FIGURE · " + WIDEST_DISC + ", street runs 99.9 mi",
    "no figure, a street that runs through the held card":
        "NO FIGURE · " + WIDEST_DISC + ", street runs 99.9 mi",
    "the geocoder was unreachable, held pickup":
        "NOT ASKED · your order's pickup",
    "the geocoder had nothing, held pickup":
        "NOT FOUND · your order's pickup",
    "no figure, a held pickup on a street":
        "NO FIGURE · " + WIDEST_DISC + ", a street pickup",
    "the order of two orders' stops unknown":
        "NO FIGURE · order of stops unknown",
    "the second order with no end on record":
        "NO FIGURE · ②'s end unknown, ⌖ Scan",
    "no figure, a street with two orders":
        "NO FIGURE · " + WIDEST_DISC + ", a street, 2 orders",
}
_CHIP_SHAPE = re.compile(r'^[A-Z][A-Z0-9 ]+ · \S')
for _name, _chip in CAPTION_CHIPS.items():
    ok_('the caption chip for %r is a state in capitals and its reason (%r)'
        % (_name, _chip), _CHIP_SHAPE.match(_chip))
    _sent = [row[1] for row in CAPTION_LINES if row[0] == _name]
    ok_('...and is a caption form this file measures, said in fewer characters (%r)'
        % _name, _sent and len(_chip) <= len(_sent[0]))

# ...and the list above has to stay the whole list, or a tenth sentence is
# written and measured by nothing. So the page is read for every string the
# caption can be handed, and each one has to appear in something above.
#
# Two sources, because the caption has two writers. `mapLine` returns the words
# under a drawn map and every literal in it is caption text; everywhere else
# the words reach the row through `mapSay` or `mapDrew`, so the arguments to
# those are taken and nothing else — the same region holds tile URLs, popup
# markup and four hex colours, and none of those is ever in this row.
def _literal_runs(js):
    """The string literals in a piece of JS, with `'a' + x + 'b'` kept apart.

    A run is one literal; adjacent literals joined by nothing but `+` are one
    run, because that is how these sentences are written across source lines.
    """
    js = re.sub(r'/\*.*?\*/', '', js, flags=re.S)
    js = re.sub(r'(?m)^\s*//.*$', '', js)
    runs, held, at = [], None, 0
    for m in re.finditer(r"'((?:[^'\\]|\\.)*)'", js):
        lit = m.group(1).replace("\\'", "'").replace('\\\\', '\\')
        if held is not None and re.fullmatch(r"\s*\+\s*", js[at:m.start()]):
            held += lit
        else:
            if held is not None:
                runs.append(held)
            held = lit
        at = m.end()
    if held is not None:
        runs.append(held)
    return runs


def caption_strings(page_src):
    tail = page_src.index('\n  applyViewMode();')
    body = page_src[page_src.index('  function mapLine('):tail]
    out = list(_literal_runs(body))
    head = page_src[page_src.index('  function mapSay(text)'):tail]
    head = re.sub(r'/\*.*?\*/', '', head, flags=re.S)
    for m in re.finditer(r'\bmap(?:Say|Drew)\(', head):
        depth, i = 0, m.end() - 1
        while i < len(head):
            if head[i] == '(':
                depth += 1
            elif head[i] == ')':
                depth -= 1
                if depth == 0:
                    break
            i += 1
        out += _literal_runs(head[m.end():i])
    # Separators and units are not sentences; anything with words in it is.
    return [r for r in out if len(r.strip()) > 4]


# --- 📷 Snap, and the row it shares --------------------------------------------
#
# What the status row is given to carry while 📷 Snap's place on it is
# measured. The shift line is the widest real one — the shape
# rpi/test_dashboard.py stages for the hat, as live.html writes it on the row
# since the rest went behind "…" (fillMore): the ticks, what they came to and
# the median, with the separator the stylesheet puts in front — and the
# connection line is the longest that row says in ordinary use: five minutes
# of silence from the scanner. Longer is possible ("for 3000s", or "scanner not
# running:" with an error after it) and cuts the median with or without this
# control; that is the row's own documented trade, not this control's.
SNAP_FIXTURE = {
    'shift': '✓10 $141 · -$17/hr an offer',
    'figure': '-$17/hr',
    'conn': 'nothing from the scanner for 300s',
    # The longest line a press answers with: the tool failing with what it
    # said (the message rpi/test_server.py stages for grim on a compositor
    # without screencopy), a scanner that is down, and a clock nobody has set.
    # 202 characters, which runs off the glass uncut at 800x480, 1024x600 and
    # 1024x768 (it fits 1280x800), so what is measured there is whether it is
    # cut short rather than whether it happens to fit. The NucBox's own line,
    # 101, fits every row that draws the control with no cutting at all, which
    # is how a check on it alone passed with the cutting taken out.
    'said': '📷 saved — no screenshot: grim failed (exit 1): compositor doesn\'t '
            'support wlr-screencopy-unstable-v1; no camera picture: the scanner is '
            'not running; the rig\'s clock is not set, so it is filed under 1970',
}
# The line under the verdict when a reading carries no verdict: what the reader
# got and what may have cut the rest off, where it used to say "scanner
# running, no offer on screen" over a card whose pay the box had cut in half.
# One reading for each sentence, the old line first, so the others are compared
# against the panel as it was. Shapes only — rpi/test_dashboard.py holds what
# each one says, off the rig's own readings; this file holds where the words
# land.
#
# ...and each of them three times over, because trackNote() appends to this
# line: nothing, " · tracking 30px" (drift past 25px), and " · screen not
# visible". The first version measured `track: None` alone, and its sentences
# wrapped beside the drift note at 800x480 and on the 3.5" hat — lifting the
# verdict label 12px and 5px where the old sentence, with the same note, had
# stayed on one line. The lost note wraps the old sentence too in those two
# scene pictures, so "moves nothing" is asked against the old line WITH the
# same note, not against the line alone.
NOVERDICT_SAID = {
    'nothing': {},
    'nopay': {'miles': 8.6},
    'notime': {'pay': 4.21},
    'clipped': {'clipped': True},
}
NOVERDICT_TRACK = {'alone': None, 'drift': {'drift': 30}, 'lost': {'lost': True}}
NOVERDICT = {}
for _said, _fields in NOVERDICT_SAID.items():
    for _track, _t in NOVERDICT_TRACK.items():
        NOVERDICT['%s/%s' % (_said, _track)] = dict(
            {'ready': False, 'state': 'empty', 'track': _t, 'places': [], 'text': ''},
            **_fields)
# ...and a read starting over a screen whose last reading found no offer:
# READING THE SCREEN and "no offer on screen · reading again", where it said
# READING THE CARD and "working out the pay, the time and the distance" over a
# navigation map. Two messages, pushed in order. No track note: the line while
# a read is out never carries one.
NOVERDICT['again/alone'] = [NOVERDICT['nothing/alone'], {'reading': True, 'at': 1}]
# The rig's own display, and the two the panel is proven at.
NOVERDICT_PANELS = [p for p in PANELS if p[0] in ('1024x600', '800x480', '480x320')]

# A payout read off a card found above the drawn card box: the label under it
# reads PAY ? where it reads PAY (live.html, `cropFrom`). Measured against the
# same card read through the box, on the panels the no-verdict line is proven
# on, in both pictures, over the longest minutes label, "min left": at $99.99,
# the widest two-figure payout, and at $999.99 — a verdict stops at $300
# (offer_parser.SANE_PAY), but a doubted reading keeps its figures on the
# panel, so three figures are on the glass with the label beside them.
_FOUNDPAY_CARD = {'ready': True, 'locked': True, 'whole': True, 'state': 'go',
                  'doubt': None, 'perHour': 999.9, 'grossPerHour': 999.9,
                  'pay': 999.99, 'minutes': 60.0, 'cardMinutes': 60.0, 'miles': 99.9,
                  'cost': 0, 'costPerMile': 0, 'fromDeadline': True,
                  'deliverBy': 1155, 'track': None, 'places': [], 'text': ''}
# The most notices one card writes in ordinary use, as chips (live.html
# showNotes): the journal refusing writes, a washed-out phone, a rate with no
# mileage off it, a card still being read and an end the driver read off the
# phone with ⌖ — five chips, each with its sentence one tap away. Measured on
# the same page as PAY ?, after it. The fifth is the card's on record, sent
# on its own line as server.js sends a card given an end over an order in the
# car (pressBetween), before its reading.
CHIPS_BEAT = {'alive': True, 'at': 1, 'tooBright': True,
              'notSaving': 'Offers are NOT being saved: [Errno 30] Read-only file system'}
CHIPS_OFFER = {'offer': {'id': 'chips-1', 'pay': 8.0, 'minutes': 22.0, 'perHour': 21.8,
                         'state': 'warn', 'dropoff': 'Canton Rd, Marietta',
                         'dropoffScanned': True, 'dropoffFrom': 'press'}}
CHIPS_CARD = dict(_FOUNDPAY_CARD, state='warn', perHour=21.8, grossPerHour=21.8,
                  pay=8.0, minutes=22.0, cardMinutes=22.0, miles=6.9,
                  fromDeadline=False, deliverBy=None, whole=False,
                  milesUncertain=True, uncosted=True, costPerMile=0.3,
                  places=['Cobb Pkwy NW, Acworth', 'Canton Rd, Marietta'])
# The heat guard's chip on the status row (live.html heatNote), as the beat
# brings it: `off`, the guard off at 76°C, which is the row with no note and
# what the others' layout is held to; `alone`, on at 76°C with nothing else
# to say, the chip with what it means after the dot; `slowed`, the widest
# lone chip, a throttled clock with no cause beside it; and the three widest
# notes with a GPS gone stale for longer than a day of driving beside them.
# HEAT_WAS is the widest note the row held before the chip, set on the same
# row as plain words, so "no wider than before" is a measurement and not a
# number copied in here.
_HEAT_STALE = {'state': 'stale', 'ageSeconds': 60000}
_HEAT_OK = {'state': 'ok', 'ageSeconds': 0.4}
HEAT_BEATS = {
    'off': {'heatGuard': False, 'cpuC': 76.2, 'gps': _HEAT_OK,
            'throttled': {'now': [], 'sinceBoot': []}},
    'alone': {'heatGuard': True, 'cpuC': 76.2, 'gps': _HEAT_OK,
              'throttled': {'now': [], 'sinceBoot': []}},
    'slowed': {'heatGuard': True, 'cpuC': 82.4, 'gps': _HEAT_OK,
               'throttled': {'now': ['throttled'], 'sinceBoot': ['throttled']}},
    'hot gps': {'heatGuard': True, 'cpuC': 84.6, 'gps': _HEAT_STALE,
                'throttled': {'now': ['temp limit', 'throttled', 'capped'],
                              'sinceBoot': ['temp limit']}},
    'slowed gps': {'heatGuard': True, 'cpuC': 82.4, 'gps': _HEAT_STALE,
                   'throttled': {'now': ['throttled'], 'sinceBoot': ['throttled']}},
    'low power gps': {'heatGuard': True, 'cpuC': 61.0,
                      'gps': {'state': 'stale', 'ageSeconds': 7380},
                      'throttled': {'now': ['under-voltage', 'throttled'],
                                    'sinceBoot': ['under-voltage', 'throttled']}},
}
HEAT_WAS = 'Pi temp limit 85°C · GPS: no fix for 1000 min'
HEAT_SAYS = {'off': '', 'alone': 'HOT 76°C · fewer auto reads',
             'slowed': 'SLOWED 82°C · fewer auto reads',
             'hot gps': 'HOT 85°C · GPS: no fix for 1000 min',
             'slowed gps': 'SLOWED 82°C · GPS: no fix for 1000 min',
             'low power gps': 'LOW POWER · GPS: no fix for 123 min'}
# The small type on a card, in px, as each panel renders it: the address
# line, a figure's label and the figure, the line under the card, the notice
# and the status row. The rig's own 1024x600 takes a fifth more than the
# 800x480 the sizes were set on (live.html, the min-width: 1000px block):
# the address 15 to 18, the labels 16 to 19 over figures 20 to 24, the line
# under the card 16 to 19, and the status row 15 to 18 since the rest of it
# went behind "…" (fillMore). Not the notice, whose chips would be taller than
# the sentences at 19 (that rule says how much). The 800x480 and the 3.5" hat
# are where they were.
SMALL_SIZES = {'1024x600': [18, 19, 24, 19, 16, 18],
               '800x480': [15, 16, 20, 16, 16, 15],
               '480x320': [14.4, 12, 15, 10, 16, 15]}
CHIPS_WANT = ['OFFERS NOT SAVED · Read-only file system',
              'PHONE TOO BRIGHT · turn it down a notch',
              'CEILING · miles unreadable',
              'STILL READING · may look better than it is',
              'END · from ⌖']
FOUNDPAY = {'drawn': dict(_FOUNDPAY_CARD, cropFrom='drawn', pay=99.99),
            'found': dict(_FOUNDPAY_CARD, cropFrom='found', pay=99.99),
            'drawn3': dict(_FOUNDPAY_CARD, cropFrom='drawn'),
            'found3': dict(_FOUNDPAY_CARD, cropFrom='found')}

# The Trip Planner's stops, as the driving screen lists them after a ⌖ press:
# at the most the block is asked to hold. Four stops and the line saying why
# the order's end was not taken from them — five lines — with an ×2 pickup, a
# closed block, and the longest address line the corpus reads, so the ellipsis
# has an address to take. Three pickups and one dropoff: four open stops do
# not fit the phone's list, so the scanner says 'list', whose line is the
# longest of the three reasons; each of the three is measured as well, below.
# Measured between offers, which is the only time the block is drawn, on the
# same three panels and in both pictures. Invented throughout.
def _pstop(kind, orders, name, by, line):
    return {'kind': kind, 'orders': orders, 'name': name, 'expectedBy': by,
            'street': None, 'city': None, 'state': None, 'zip': None, 'line': line}


PLANNER_STOPS = [
    _pstop('pickup', 1, 'Burger Barn', 712, '310 Mill St, Roswell'),
    _pstop('pickup', 2, 'Taco Hut Express', 725, None),
    _pstop('pickup', 1, 'Pho Real Kitchen', 751, '77 Birch Ln NW, Roswell, GA 30075'),
    _pstop('dropoff', 1, 'Pat Q.', 978, '4821 Kestrel Dr S, Powder Springs'),
]
PLANNER_UNFILED = 'list'
# ...and the stops each of the scanner's reasons comes with, so every line the
# panel can put under them is measured on the panel it has to fit.
PLANNER_NOTES = {
    'list': PLANNER_STOPS,
    'dropoffs': PLANNER_STOPS[:2] + [
        _pstop('dropoff', 1, 'Lee M.', 751, '77 Birch Ln NW, Roswell, GA 30075'),
        PLANNER_STOPS[3]],
    'address': PLANNER_STOPS[:3] + [
        _pstop('dropoff', 1, 'Pat Q.', 978, 'Powder Springs')],
}
PLANNER_PANELS = NOVERDICT_PANELS
# The notice the stops have to share the card with between offers: the two a
# rig with a dead journal under a bright phone writes at once, the first of
# them the longest notSaving the scanner has been seen to send.
PLANNER_NOTICE = {'notSaving': 'Offers are NOT being saved: [Errno 30] Read-only '
                               'file system', 'tooBright': True}
# ...and the camera's word, which takes the same between-offers branch the stops
# are drawn in: a rig that cannot see puts its word where the verdict goes and
# its line where the notice goes, with whatever stops a press read before it
# still on the card. The two came from two lines of work and met only in the
# merge, so nothing had measured them together. Both words, since each has a
# line of its own.
PLANNER_BLIND = ['dark', 'stalled']

# The order in the car, on the card (showHeld in live.html), at the most each
# of its lines is asked to hold. Between offers: where it goes next — the
# planner's first pickup, given the longest name a real card has printed for a
# restaurant (Dave's Hot Chicken with its street in brackets, the 8 Oct snap
# in rpi/test_dashboard.py) — by when, and one line with a three-figure pay
# and the longest of the GPS drop's words ('too many answers', END_WHY_SHORT;
# '● armed by place', an end pinned by its place, is narrower: 179 px to 184
# at 20 px in the headless browser's sans-serif, measured 17 Oct);
# under them the four stops above. With an offer up: the same order in one
# line under the card, beside a pair whose range has a minus sign and three
# figures, every clause the pair line can carry, the geography's widest chip
# and the route link — the most the pair row is ever asked to hold, above the
# figures. Invented but for the name. ...and its pickup the store of the
# order in the car (server.js sameStoreOf), "same store as in car", the
# widest the note is with one order — and with two, on the forms below that
# say so, "same store as ②".
HELD = {
    'hold': {'pay': 112.45, 'minutes': 55, 'holdId': 'h-layout@1',
             'dropoff': '4821 Kestrel Dr S, Powder Springs, GA 30127', 'card': None,
             'endPinned': False, 'arrived': False, 'endWhy': 'too many answers'},
    'stops': [_pstop('pickup', 1, "Dave's Hot Chicken (1985 Cobb Parkway NW, STE 100)",
                     712, '1985 Cobb Pkwy NW, Kennesaw')] + PLANNER_STOPS[1:],
    'offer': {'ready': True, 'locked': True, 'whole': True, 'state': 'no',
              'doubt': None, 'perHour': 14.71, 'grossPerHour': 20.97,
              'billedMinutes': 22.0, 'perMile': 0.7, 'pay': 18.04, 'minutes': 22.0,
              'cardMinutes': 22.0, 'miles': 6.9, 'cost': 2.4, 'costPerMile': 0.3,
              'milesUncertain': False, 'milesCorrected': False, 'uncosted': False,
              'fromDeadline': False, 'deliverBy': None, 'track': None, 'legs': 2,
              'mergedFrom': 5, 'items': None, 'text': '',
              'places': ['Cochran Ridge Rd & Jewel Cole Rd, Hiram',
                         'Old Alabama Rd & Holcomb Bridge Rd, Roswell'],
              'stack': {'pay': 130.49, 'minMinutes': 55, 'maxMinutes': 105,
                        'worst': -16.4, 'best': 133.4, 'state': 'warn', 'sure': True,
                        'uncosted': True, 'ends': 'elsewhere',
                        'route': 'https://www.google.com/maps/dir/?api=1&origin=A'
                                 '&destination=B&travelmode=driving',
                        'sameStore': 'h-layout@1', 'sameStoreN': 1,
                        # ...and the on-time hint at its widest (server.js
                        # onTimeHint): the order in the car late by two
                        # figures of minutes.
                        'onTime': 'late1', 'lateMin': 12}},
    # The Took button's widest label once its card has gone: the widest pay a
    # card prints and an age of two figures. See tookAge.
    'took': {'id': 'o-layout-took', 'pay': 112.45, 'minutes': 55, 'perHour': 99.9},
}
# The card side while gps.py says the car is being driven, every form it
# takes, each measured against the same card parked. With an offer up
# (`offer`: live.html `.live.moving`) the whole card, the owner's decision of
# 17 Oct 2026: every part the parked card draws, at its size, but the read
# diagnostics and the route link (and what the check under DRIVE_FORMS's
# loop names for the smaller panels), and the two ends a line each.
# Between offers the driving form (`.live.driving`), larger. The most each is
# asked to hold: the four notices CHIPS_CARD writes; the pair at its widest
# with the order in the car (HELD); the pair against two orders, "with ① +
# ②"; a card the reader refused, its rate withheld; the owner's snap, a long
# pickup (LONG_ENDS) under the notices, alone and with the pair line; between
# offers with one order in the car and its stops read, and with two; and
# nothing at all. `larger` names the parts that must come out strictly
# larger moving than parked; every part both forms draw must come out no
# smaller.
_DA = {'n': 1, 'pay': 112.45, 'minutes': 55, 'holdId': 'l-a@1',
       'dropoff': '4821 Kestrel Dr S, Powder Springs, GA 30127', 'card': None,
       'endPinned': False, 'arrived': False, 'endWhy': 'too many answers', 'app': 'uber'}
_DB = dict(_DA, n=2, pay=128.08, minutes=60, holdId='l-b@2',
           dropoff='1985 Cobb Pkwy NW, Kennesaw, GA 30152')
_EMPTY = {'ready': False, 'state': 'empty', 'track': None, 'places': [], 'text': ''}
# The owner's 17 Oct snap, an Uber card from a KFC to a corner in Marietta,
# its pickup at the length a store with its street in brackets runs to.
# Invented but for the shape.
# Long enough to be cut on every panel, so the ellipsis is measured too.
LONG_ENDS = ['KFC (2575 Delk Rd SE, Suite 100, Powers Ferry Village Shopping Center, '
             'Marietta, GA 30067)',
             'Powers Ferry Rd & Terrell Mill Rd, Marietta']
_NOTICES = {'tooBright': True, 'notSaving': CHIPS_BEAT['notSaving']}
DRIVE_FORMS = {
    'offer': {'beat': _NOTICES, 'msgs': [CHIPS_CARD], 'offer': True, 'larger': []},
    'pair': {'msgs': [{'holding': HELD['hold']},
                      dict(HELD['offer'], holding=HELD['hold'])],
             'offer': True, 'larger': []},
    'two': {'msgs': [dict(HELD['offer'], holding=_DA, orders=[_DA, _DB], unowned=0,
                          stack=dict(HELD['offer']['stack'], heldCount=2,
                                     leftEach=[55, 60], maxMinutes=137, route=None,
                                     sameStore='l-b@2', sameStoreN=2))],
            'offer': True, 'larger': []},
    'refused': {'msgs': [dict(HELD['offer'], state='doubt', doubt='rate', pay=136.0,
                              minutes=10.0, cardMinutes=10.0, billedMinutes=10.0,
                              perHour=816.0, grossPerHour=816.0, stack=None,
                              holding=None)],
                'offer': True, 'larger': []},
    'long pickup': {'beat': _NOTICES, 'msgs': [dict(CHIPS_CARD, places=LONG_ENDS)],
                    'offer': True, 'larger': []},
    'long pickup pair': {'beat': _NOTICES,
                         'msgs': [{'holding': HELD['hold']},
                                  dict(HELD['offer'], holding=HELD['hold'],
                                       places=LONG_ENDS, milesUncertain=True)],
                         'offer': True, 'larger': []},
    'between': {'msgs': [{'holding': HELD['hold']},
                         {'planner': {'stops': HELD['stops'], 'unfiled': 'list',
                                      'asked': True, 'ms': None, 'at': 1}}, _EMPTY],
                'larger': ['line']},
    'between two': {'msgs': [{'holding': _DA, 'orders': [_DA, _DB], 'unowned': 2}, _EMPTY],
                    'larger': ['line', 'line2']},
    'waiting': {'msgs': [_EMPTY], 'larger': ['label']},
}
# ...and a batched Uber trip (server.js batchDrops, the owner's decision of 19
# Oct): one order with two doors, "2 drops" beside the pay — under an offer at
# the pair's widest, and between offers with its stops read.
_HB = dict(HELD['hold'], drops=2)
DRIVE_FORMS['pair batch'] = {'msgs': [{'holding': _HB}, dict(HELD['offer'], holding=_HB)],
                             'offer': True, 'larger': []}
DRIVE_FORMS['between batch'] = {
    'msgs': [{'holding': _HB},
             {'planner': {'stops': HELD['stops'], 'unfiled': None,
                          'asked': False, 'ms': None, 'at': 1}}, _EMPTY],
    'larger': ['line']}
# ...and an Uber add-on's trip of three, one original and two add-ons
# (server.js placeTook, the owner's 16 Oct trip details): ② onwards share the
# second line ("②–③ +$256.16 → 1/2 ends", live.html restLine) at their widest
# pay, and under an offer the trip is one line. No third line, no control.
_DBA = dict(_DB, addOn=True, of='l-a@1')
_DCA = dict(_DBA, n=3, holdId='l-c@3', dropoff=None)
DRIVE_FORMS['three'] = {
    'msgs': [dict(HELD['offer'], holding=_DA, orders=[_DA, _DBA, _DCA], unowned=0,
                  stack=dict(HELD['offer']['stack'], heldCount=3,
                             leftEach=[55, 60, 60], maxMinutes=197, route=None))],
    'offer': True, 'larger': []}
DRIVE_FORMS['between three'] = {
    'msgs': [{'holding': _DA, 'orders': [_DA, _DBA, _DCA], 'unowned': 2}, _EMPTY],
    'larger': ['line', 'line2']}
# ...and over the two pair forms, the answer on the card (live.html showWay,
# MV.wayLine) in every form it takes, drawn by the page's own MV.sayWay over
# the pair at its widest: ON THE WAY and OUT OF THE WAY at the widest figure
# each can carry (a range from two orders, two figures before the point) and
# the widest ends; the line still checking; and CAN'T TELL with every chip
# the caption can refuse with, at its widest place (CAPTION_CHIPS), and the
# one only the card makes (the NucBox down), read off live.html.
DRIVE_FORMS['pair']['way'] = DRIVE_FORMS['two']['way'] = True
_card_only = re.findall(r"chip: '([A-Z ]+ · [^']+)'",
                        live_src[live_src.index('  function wayNucBoxDown('):
                                 live_src.index('  function wayAnswered(')])
eq("live.html words the card's own refusal as a chip", len(_card_only), 1)
_said = {row[0]: row[1] for row in CAPTION_LINES}
WAY_FORMS = [
    ('on the way, a range', {'said': 'on your way by road incl. both orders',
                             'fig': {'lo': 0.1, 'hi': 0.4, 'road': True, 'onWay': True}},
     'same-side'),
    ('out of the way, a range', {'said': '+18.8–19.2 road mi incl. both orders',
                                 'fig': {'lo': 18.8, 'hi': 19.2, 'road': True,
                                         'onWay': False}}, 'same-side'),
    ('out of the way, straight lines', {'said': '+18.8–19.2 mi incl. both orders — straight '
                                                'lines, not roads',
                                        'fig': {'lo': 18.8, 'hi': 19.2, 'road': False,
                                                'onWay': False}}, 'elsewhere'),
    ('checking', {'pending': True}, 'same-side'),
] + [('cant: ' + name, {'said': _said[name], 'chip': chip}, 'same-side')
     for name, chip in sorted(CAPTION_CHIPS.items())] \
  + [('cant: the card\'s own, ' + chip, {'said': 'the sentence', 'chip': chip}, 'same-side')
     for chip in _card_only]

# ...and the two strings that fixture copies have to still be the page's, or it
# measures a line the page no longer writes.
ok_('live.html still writes the median as "/hr an offer"', "'/hr an offer'" in live_src)
ok_('...and still says "nothing from the scanner for"',
    "'nothing from the scanner for '" in live_src)

spoken = caption_strings(live_src)
ok_('live.html still reads as a page with a map caption in it', len(spoken) > 15)
# ...and the third writer: the lines that say why a card's fix or distance
# gives nothing to measure with, and the line for a pin a card contradicts,
# are worded in map-view.js (MV.fixLine and MV.againstCard), where
# tests/mapview.test.js reaches every one, and mapLine returns them as they
# come. Read from the words' tables to the end of againstCard.
mv_src = open(os.path.join(ROOT, 'map-view.js')).read()
_mv_words = [r for r in _literal_runs(
    mv_src[mv_src.index('  var FIX_WORDS = {'):
           mv_src.index('  /* Every place the loaded offers name')])
    if len(r.strip()) > 4]
ok_("map-view.js still words the card's own refusals", len(_mv_words) > 15)
spoken += _mv_words
said = ' ## '.join(row[1] for row in CAPTION_LINES)
eq('every sentence the map caption can say is one this file measures',
   sorted(set(r for r in spoken if r not in said)), [])

# ---------------------------------------------------------------------------
# Now the browser.
# ---------------------------------------------------------------------------

if shutil.which('node') is None:
    skip('no node on this machine')

NODE_PATHS = [p for p in (os.environ.get('NODE_PATH'),
                          '/opt/node22/lib/node_modules') if p]

# --- the "you are here" label --------------------------------------------------
#
# Every form the label in the map's corner can take, made by the page's own
# MV.hereDot rather than copied here: one line for each word rpi/gps.py's gate
# can refuse with (read out of usable() itself, so a fifth word is a fifth
# line), the line for a fix nobody judged, and the dot's label at its widest —
# an error figure of two digits, and an age in minutes, in hours, or unknown.
# The refusal is measured at a four-digit error, which no working receiver
# reports and a lost one can.
_gps_src = open(os.path.join(ROOT, 'rpi', 'gps.py'), encoding='utf-8').read()
_usable = _gps_src[_gps_src.index('\ndef usable('):]
_usable = _usable[:_usable.index('\ndef ', 1)]
GATE_WORDS = re.findall(r"return False, '([a-z]+)'", _usable)
ok_('rpi/gps.py\'s gate refuses with words this file can measure (%r)' % GATE_WORDS,
    len(GATE_WORDS) >= 3 and 'stale' in GATE_WORDS)
_here_js = '''
var MV = require(process.argv[1]), words = JSON.parse(process.argv[2]), out = [];
var AT = { lat: 33.9526, lon: -84.5499 };
function at(o) { return Object.assign({}, AT, o); }
words.forEach(function (w) {
  if (w === 'stale') return;        // stale is a grey dot, measured as a label
  out.push(['refused: ' + w,
            (MV.hereDot(at({ gpsErr: 9999, gpsOk: false, gpsWhy: w }), 0) || {}).line]);
});
out.push(['refused: unjudged', (MV.hereDot(at({ gpsOk: false }), 0) || {}).line]);
out.push(['label, minutes', (MV.hereDot(at({ gpsAge: 3599, gpsErr: 49.9,
          gpsOk: true, freshFor: 0 }), 0) || {}).label]);
out.push(['label, hours', (MV.hereDot(at({ gpsAge: 86399, gpsErr: 49.9,
          gpsOk: true, freshFor: 0 }), 0) || {}).label]);
out.push(['label, age unknown', (MV.hereDot(at({ gpsAge: null, gpsErr: 49.9,
          gpsOk: true, freshFor: 0 }), 0) || {}).label]);
console.log(JSON.stringify(out));
'''
HERE_LINES = json.loads(subprocess.run(
    ['node', '-e', _here_js, os.path.join(ROOT, 'map-view.js'), json.dumps(GATE_WORDS)],
    capture_output=True, text=True, timeout=60).stdout or '[]')
eq('every "you are here" form is a sentence the page can say',
   [name for name, text in HERE_LINES if not text], [])
# ...and on the panel only, each form with a dot once the driver has taken the
# map and it has stopped following: the label, then live.html's own word for
# that, read out of the page rather than copied here. map.html does not follow
# and never says it.
_live_src = open(os.path.join(ROOT, 'live.html'), encoding='utf-8').read()
_paused = re.search(r"var FOLLOW_PAUSED = '([^']+)';", _live_src)
ok_('live.html says in words when its map has stopped following the dot',
    _paused is not None)
LIVE_HERE_LINES = HERE_LINES + [
    [name + ', not following', text + _paused.group(1)]
    for name, text in HERE_LINES if name.startswith('label') and _paused]
env_probe = dict(os.environ, NODE_PATH=os.pathsep.join(NODE_PATHS))
if subprocess.call(['node', '-e', 'require("playwright")'], env=env_probe,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
    skip('no playwright')

DRIVER = r'''
const { chromium } = require('playwright');
const [base, panelsJson, pagesJson, framesJson, captionJson, snapJson,
       snapPanelsJson, noVerdictJson, noVerdictPanelsJson, plannerJson,
       plannerPanelsJson, hereJson, foundPayJson, liveHereJson, heldJson,
       chipsJson, heatJson, driveJson] = process.argv.slice(2);
// The heat guard's beats, and the widest note the row held before its chip;
// see HEAT_BEATS on the Python side.
const HEAT_BEATS = JSON.parse(heatJson).beats;
const HEAT_WAS = JSON.parse(heatJson).was;
// The order in the car and the offer beside it; see HELD on the Python side.
const HELD = JSON.parse(heldJson);
// A card's payout read off a card found above the box, and the same read
// through the box; see FOUNDPAY on the Python side.
const FOUNDPAY = JSON.parse(foundPayJson);
// The notices as chips; see CHIPS_BEAT on the Python side.
const CHIPS = JSON.parse(chipsJson);
// The card side's driving forms; see DRIVE_FORMS on the Python side.
const DRIVE = JSON.parse(driveJson);
// The "you are here" label's forms, made by MV.hereDot; see HERE_LINES.
const HERE_LINES = JSON.parse(hereJson);
// ...and the panel's, which adds each dot's label once it has stopped
// following; see LIVE_HERE_LINES.
const LIVE_HERE_LINES = JSON.parse(liveHereJson);
const PANELS = JSON.parse(panelsJson), PAGES = JSON.parse(pagesJson);
// The Trip Planner's stops and where they are measured; see PLANNER_STOPS.
const PLANNER = JSON.parse(plannerJson);
const PLANNER_STOPS = PLANNER.stops;
const PLANNER_PANELS = JSON.parse(plannerPanelsJson);
// The readings with no verdict in them, and where their line is measured; see
// NOVERDICT on the Python side.
const NOVERDICT = JSON.parse(noVerdictJson);
const NOVERDICT_PANELS = JSON.parse(noVerdictPanelsJson);
// What 📷 Snap's measurement puts on the status row; see SNAP_FIXTURE.
const SNAP_FIXTURE = JSON.parse(snapJson);
const SNAP_PANELS = JSON.parse(snapPanelsJson);
// The caption sentences, passed in rather than written here: the Python side
// reads them back out of live.html to check that none has been added without
// being measured, and two copies of that list is the fault this file is for.
const CAPTION_LINES = JSON.parse(captionJson);
// Two pictures the shape the rig actually publishes: a landscape cabin for the
// scene view, a portrait phone screen for the other. There is no camera on the
// machine this runs on, so without them every measurement of the live view is a
// measurement of a broken image — which is not a small thing, because a broken
// image collapses to 2px and 2px passes "the phone is taller than the scene
// was" as comfortably as a real picture does.
const FRAMES = JSON.parse(framesJson);

// 📷 Snap's measurement, run in the page: see where it is called, below.
const SNAP_MEASURE = (fixture) => {
  const snap = document.getElementById('snap');
  const bar = document.querySelector('.bottombar');
  const row = document.querySelector('.connbar');
  const d = document.documentElement;
  const box = (el) => {
    const r = el.getBoundingClientRect();
    return [r.left, r.top, r.width, r.height].map((n) => Math.round(n * 10) / 10);
  };
  const layout = () => JSON.stringify({ row: box(row),
                                       bar: [].slice.call(bar.children).map(box) });
  const over = () => d.scrollWidth > d.clientWidth + 1
                     || d.scrollHeight > d.clientHeight + 1;
  // Every glyph of the label inside the control's own box.
  const spilt = () => {
    const r = snap.getBoundingClientRect();
    const n = snap.firstChild;
    if (!n) return '';
    const rg = document.createRange();
    let out = '';
    for (let i = 0; i < n.length; i++) {
      rg.setStart(n, i);
      rg.setEnd(n, i + 1);
      const c = rg.getBoundingClientRect();
      if (c.width === 0 && c.height === 0) continue;
      if (c.left < r.left - 0.5 || c.right > r.right + 0.5
          || c.top < r.top - 0.5 || c.bottom > r.bottom + 0.5) out += n.data[i];
    }
    return out;
  };
  const r = snap.getBoundingClientRect();
  const out = {
    drawn: getComputedStyle(snap).display !== 'none' && r.width > 0 && r.height > 0,
    inRow: !!snap.closest('.connbar'), inBar: !!snap.closest('.bottombar'),
    onGlass: r.left >= -0.5 && r.top >= -0.5 && r.right <= d.clientWidth + 0.5
             && r.bottom <= d.clientHeight + 0.5,
    label: (snap.textContent || '').trim(), spilt: spilt(),
    height: Math.round(r.height), over: over(),
  };
  const withIt = layout();
  snap.style.display = 'none';
  out.same = withIt === layout();
  snap.style.display = '';
  // The longest line it says: the screenshot missing and why. Put back
  // as markup, not as text — the label's word is a span of its own, and
  // flattening it into the text node would paint it.
  const was = snap.innerHTML;
  snap.textContent = fixture.said;
  snap.classList.add('said');
  out.sameSaid = withIt === layout();
  out.overSaid = over();
  // ...and the answer itself on the glass, beside the connection line
  // rather than over it. Overflow alone cannot see this: #app clips, so
  // a line that runs off the right edge leaves nothing to scroll.
  const rs = snap.getBoundingClientRect();
  const rc = document.getElementById('conn').getBoundingClientRect();
  out.saidOnGlass = rs.left >= rc.right - 0.5 && rs.right <= d.clientWidth + 0.5;
  snap.innerHTML = was;
  snap.classList.remove('said');
  // The median, beside the longest connection line the page writes.
  const shift = document.getElementById('shift');
  const conn = document.getElementById('conn');
  const keep = [shift.textContent, shift.hidden, conn.textContent];
  shift.textContent = fixture.shift;
  shift.hidden = false;
  conn.textContent = fixture.conn;
  const node = shift.firstChild;
  const at = node.nodeValue.indexOf(fixture.figure);
  const rg = document.createRange();
  rg.setStart(node, at);
  rg.setEnd(node, at + fixture.figure.length);
  out.figureSpare = Math.round(shift.getBoundingClientRect().right
                               - rg.getBoundingClientRect().right);
  // ...and the same with the control put on the row whatever the stylesheet
  // says: the room it WOULD leave, which is what decides whether it may be
  // drawn here at all. Measured on every screen, drawn or not, so one that
  // does not draw it is held to the reason it does not.
  // To a hundredth, not a pixel: the row's width is fractional on a landscape
  // panel, and at 777x480 the digits end 0.05px past the glass, which rounds
  // to "0px to spare" and is no room at all.
  snap.style.display = 'inline-block';
  out.roomWith = Math.round((shift.getBoundingClientRect().right
                             - rg.getBoundingClientRect().right) * 100) / 100;
  snap.style.display = '';
  shift.textContent = keep[0];
  shift.hidden = keep[1];
  conn.textContent = keep[2];
  return out;
};

(async () => {
  let browser;
  for (const exe of JSON.parse(process.env.PW_EXES || '[]').concat([null])) {
    try {
      browser = await chromium.launch(Object.assign(
        // scan.html sends a device with no camera to live.html on purpose, so
        // without a fake one this measures live.html twice and never sees the
        // scanner at all.
        { args: ['--use-fake-device-for-media-stream',
                 '--use-fake-ui-for-media-stream'] },
        exe ? { executablePath: exe } : {}));
      break;
    } catch (e) { /* try the next one */ }
  }
  if (!browser) { console.log(JSON.stringify({ skip: 'no chromium' })); return; }

  const out = {};
  for (const panel of PANELS) {
    const ctx = await browser.newContext({
      viewport: { width: panel[1], height: panel[2] },
      deviceScaleFactor: 1,
      permissions: ['camera'],
    });
    for (const name of PAGES) {
      const page = await ctx.newPage();
      // Before the navigation, or the first frame is requested before the
      // handler exists. The mjpeg stream is answered with a single JPEG: an
      // <img> renders the first frame of a stream and this only ever needs
      // one, and a route that never ends would hold the page open.
      await page.route('**/api/frame.*', (route) => {
        const view = /view=screen/.test(route.request().url()) ? 'screen' : 'scene';
        route.fulfill({ status: 200, contentType: 'image/jpeg',
                        body: Buffer.from(FRAMES[view], 'base64') });
      });
      await page.goto(base + '/' + name, { waitUntil: 'domcontentloaded' })
                .catch(() => {});
      await page.waitForTimeout(1800);
      out[panel[0] + ' ' + name] = await page.evaluate(() => {
        const d = document.documentElement;
        // The smallest thing anybody is actually being asked to read. Text
        // nodes only, and only ones that are on the screen and have a box.
        const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        let smallest = null, what = null, n;
        while ((n = walk.nextNode())) {
          if (!(n.nodeValue || '').trim()) continue;
          const el = n.parentElement;
          if (!el) continue;
          const r = el.getBoundingClientRect();
          if (!r.width || !r.height) continue;
          const cs = getComputedStyle(el);
          if (cs.visibility === 'hidden' || cs.display === 'none') continue;
          if (parseFloat(cs.opacity) === 0) continue;
          const px = parseFloat(cs.fontSize);
          if (smallest === null || px < smallest) {
            smallest = px;
            what = (el.id || el.className || el.tagName).toString().slice(0, 30);
          }
        }
        // The longest line of running text on the page. A line the eye has to
        // travel a long way along loses its place coming back to the start of
        // the next one, which is why prose has a measure at all.
        let measure = 0, measureIn = '';
        for (const e of document.querySelectorAll('p, li, .hint, .note, #headline, dd')) {
          const b = e.getBoundingClientRect();
          if (!b.width || !b.height) continue;
          if ((e.textContent || '').trim().length < 60) continue;
          if (b.width > measure) {
            measure = b.width;
            measureIn = (e.id || e.className || e.tagName).toString().slice(0, 24);
          }
        }

        // Every row of a chart the same height as its neighbours.
        //
        // This is aimed at one thing: a label too long for the column it is
        // given. `.block .label` is `flex: none` at 62px, 88px on a dashboard
        // panel, and what happens then was worth measuring rather than
        // reasoning about, because two guesses at it were both wrong. The text
        // does not overhang the bar and it does not shorten the bar — the box
        // and the bar keep their widths exactly. It WRAPS inside the column,
        // and the row grows: measured on the chart of what was taken,
        // "unrecorded-verdict-here" in place of "no verdict" took that row from
        // 33px to 48px on a 1024x600 panel and from 30px to 52px on a phone,
        // while the three rows above it stayed where they were.
        //
        // Which is a chart with one row emphasised for no reason, on a page
        // whose whole idiom is that a row means the same thing as the row
        // above it. Nothing errors and nothing else moves, so the only sign is
        // a screenshot somebody has to notice.
        let rowSkew = null, rowSkewIn = '';
        for (const chart of document.querySelectorAll('#blocks, #kinds, #took, #week, #runs')) {
          const heights = [].slice.call(chart.querySelectorAll('.block'))
            .map((b) => b.getBoundingClientRect().height)
            .filter((h) => h > 0);
          if (heights.length < 2) continue;
          const skew = Math.max.apply(null, heights) - Math.min.apply(null, heights);
          if (rowSkew === null || skew > rowSkew) {
            rowSkew = skew;
            rowSkewIn = chart.id + ' (' + heights.length + ' rows)';
          }
        }

        // Every control meant to be pressed one-handed, on glass, in a car.
        let shortest = null, shortestIn = null;
        for (const el of document.querySelectorAll(
               '.bottombar button, .bottombar a, .scanbar button, .scanbar label,'
               + ' .scanbar a, .key, .rangebtns button, .chips button, #runsAll')) {
          const r = el.getBoundingClientRect();
          if (!r.width || !r.height) continue;
          if (shortest === null || r.height < shortest) {
            shortest = r.height;
            shortestIn = (el.id || el.className || el.tagName).toString().slice(0, 30);
          }
        }

        // The scanner draws four layers over one camera picture, each pinned
        // to an edge with no layout between them: the verdict, the box, the
        // line that says what is happening, and the controls. Nothing stops
        // one growing into the next, and when the control bar did exactly
        // that it was drawn on top of the status line.
        const layers = ['#stage > .verdict', '#reticle', '#statusline', '.scanbar']
          .map(s => {
            const el = document.querySelector(s);
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return (r.width && r.height) ? { sel: s, top: r.top, bottom: r.bottom } : null;
          }).filter(Boolean);

        return {
          landed: location.pathname.replace(/^\//, ''),
          scrollW: d.scrollWidth, scrollH: d.scrollHeight,
          clientW: d.clientWidth, clientH: d.clientHeight,
          smallest: smallest, smallestIn: what,
          shortest: shortest, shortestIn: shortestIn,
          measure: measure, measureIn: measureIn,
          rowSkew: rowSkew, rowSkewIn: rowSkewIn,
          layers: layers,
          // What share of the glass the thing the page is FOR actually gets.
          // A page can fit, scroll neither way, keep every font above the floor
          // and still be useless, because its furniture ate the subject: the
          // map page declared three grid rows for four children and the map —
          // the whole point of it — came out 82px tall at 800x480 under a
          // 222px block of warning text. Every other check on this page passed
          // while that was true.
          subject: (function () {
            var el = document.getElementById('map');
            return el ? el.getBoundingClientRect().height : null;
          })(),
        };
      });
      // The day-of-week chart, on the range it exists for. The page lands on
      // "7 days" and the chart hides itself under fourteen, so on the landing
      // page it is never drawn and the row-height check above never sees it —
      // the first version of this suite passed with "Wednesday afternoon" as
      // a label because there was no chart to measure. Pressed to 30 days,
      // the fixture's fifteen days are all on the page and it draws.
      if (name === 'journal.html') {
        await page.click('.rangebtns button[data-days="30"]').catch(() => {});
        await page.waitForTimeout(1500);
        out[panel[0] + ' ' + name + ' week'] = await page.evaluate(() => {
          const head = document.getElementById('weekHead');
          const heights = [].slice.call(document.querySelectorAll('#week .block'))
            .map((b) => b.getBoundingClientRect().height).filter((h) => h > 0);
          // Where the run-by-run chart sits against the chart of hours, on
          // the range where it is longest. Distances, not DOM order: a
          // heading hidden by a stylesheet keeps its place in the DOM.
          const top = (id) => {
            const e = document.getElementById(id);
            return e && !e.hidden ? e.getBoundingClientRect().top + window.scrollY : null;
          };
          return {
            shown: !!head && !head.hidden,
            rows: heights.length,
            skew: heights.length > 1
              ? Math.max.apply(null, heights) - Math.min.apply(null, heights) : 0,
            fits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
            hoursAt: top('blocksHead'),
            runsAt: top('runsHead'),
            runRows: document.querySelectorAll('#runs .block').length,
          };
        });
      }
      // map.html's "you are here" label, by the page's own rule, in the map's
      // own box. Leaflet comes from a CDN this harness cannot reach, and the
      // page's offline path writes its notice over the map's box and takes the
      // label with it — so the label is put back, as the page's markup has
      // it, to be measured where it would sit.
      if (name === 'map.html') {
        out[panel[0] + ' map here'] = await page.evaluate((lines) => {
          const box = document.getElementById('map');
          let note = document.getElementById('hereNote');
          if (!note) {
            note = document.createElement('div');
            note.id = 'hereNote';
            box.appendChild(note);
          }
          const map = box.getBoundingClientRect();
          const out = {};
          for (const pair of lines) {
            note.hidden = false;
            note.textContent = pair[1];
            const r = note.getBoundingClientRect();
            const tops = {};
            const n = note.firstChild;
            if (n) {
              const rg = document.createRange();
              for (let i = 0; i < n.length; i++) {
                rg.setStart(n, i);
                rg.setEnd(n, i + 1);
                const c = rg.getBoundingClientRect();
                if (c.width || c.height) tops[Math.round(c.top)] = 1;
              }
            }
            out[pair[0]] = {
              across: r.left >= map.left + 44 && r.right <= map.right + 0.5,
              inside: r.top >= map.top - 0.5 && r.bottom <= map.bottom + 0.5,
              rows: Object.keys(tops).length,
              spills: note.scrollWidth > note.clientWidth + 1,
              mapH: Math.round(map.height) };
          }
          note.hidden = true;
          return out;
        }, HERE_LINES);
        // ...and its one-line key to the pins, every item of it shown (the
        // widest it gets), put back from the page's own markup — fetched from
        // this server, so it is the key the page ships — when the offline
        // path has written over the map's box.
        out[panel[0] + ' map key'] = await page.evaluate(async () => {
          const box = document.getElementById('map');
          let key = document.getElementById('mapKey');
          if (!key) {
            const src = await (await fetch('/map.html')).text();
            const doc = new DOMParser().parseFromString(src, 'text/html');
            box.appendChild(document.importNode(doc.getElementById('mapKey'), true));
            key = document.getElementById('mapKey');
          }
          key.hidden = false;
          key.querySelectorAll('[hidden]').forEach((e) => { e.hidden = false; });
          const first = key.querySelector('.k-item .k-sep');
          if (first && first.closest('.k-item') === key.querySelector('.k-item')) first.hidden = true;
          const map = box.getBoundingClientRect();
          const r = key.getBoundingClientRect();
          const tops = {};
          let text = '';
          const walk = document.createTreeWalker(key, NodeFilter.SHOW_TEXT);
          let n;
          while ((n = walk.nextNode())) {
            const rg = document.createRange();
            for (let i = 0; i < n.length; i++) {
              rg.setStart(n, i);
              rg.setEnd(n, i + 1);
              const c = rg.getBoundingClientRect();
              if (c.width || c.height) { tops[Math.round(c.top)] = 1; text += n.data[i]; }
            }
          }
          const out = {
            inside: r.left >= map.left - 0.5 && r.right <= map.right + 0.5
              && r.top >= map.top - 0.5 && r.bottom <= map.bottom + 0.5,
            rows: Object.keys(tops).length,
            spills: key.scrollWidth > key.clientWidth + 1,
            text: text.replace(/\s+/g, ' ').trim(),
            w: Math.round(r.width), mapW: Math.round(map.width) };
          key.hidden = true;
          return out;
        });
      }
      // The thing this panel is mostly used for: reading the phone through it
      // and working it with a bluetooth mouse. That view is only worth having
      // if the picture is bigger than the scene view it replaced, which is a
      // claim about pixels and can be measured.
      //
      // Measured where the page lands, then clicked the other way — which is
      // the reverse of how this read when it was written. Aiming the mount is
      // a thing you do once and reading the phone is a thing you do all shift,
      // so the phone is what the page opens on and the scene is what the
      // driver has to ask for. Left as it was, this measured the scene view
      // twice and called the second one the phone.
      if (name === 'live.html') {
        // `cut` is the whole picture minus the part of it on the glass. The
        // page clips at #app — `overflow: hidden`, which is what stops a bar
        // of controls scrolling out of a driver's reach — so a picture drawn
        // taller than its row does not overflow the page and does not fail any
        // check that asks whether the page fits. It is silently trimmed at
        // both ends, and the end that matters is the top, where the payout is.
        const SIDE_SRC = `(() => {
          const v = document.getElementById('viewWrap').getBoundingClientRect();
          const l = document.querySelector('.live').getBoundingClientRect();
          const n = (x) => Math.round(x * 10) / 10;
          return { picL: n(v.left), picR: n(v.right), picT: n(v.top), picW: n(v.width),
                   cardL: n(l.left), cardR: n(l.right), cardB: n(l.bottom), cardW: n(l.width) };
        })()`;
        const LOOKAT = () => {
          const d = document.documentElement;
          const img = document.getElementById('view');
          const r = img.getBoundingClientRect();
          const btn = document.getElementById('viewMode');
          return {
            src: img.getAttribute('src') || '',
            pressed: btn.getAttribute('aria-pressed'),
            label: btn.textContent.trim(),
            h: r.height, w: r.width,
            loaded: img.naturalWidth > 2 && img.naturalHeight > 2,
            cutTop: Math.max(0, -r.top),
            cutBottom: Math.max(0, r.bottom - d.clientHeight),
            cutLeft: Math.max(0, -r.left),
            cutRight: Math.max(0, r.right - d.clientWidth),
            rowH: document.getElementById('app').getBoundingClientRect().height,
            over: d.scrollWidth > d.clientWidth + 1 || d.scrollHeight > d.clientHeight + 1,
            // The third thing this pane can be. Measured here rather than in a
            // block of its own, because the question about the map on a
            // dashboard panel is the same question as about the picture: does
            // it take the row without pushing the bar off the glass.
            // What is actually PAINTED, not what the property says. `img.hidden`
            // answered true while the picture was still filling the pane: the
            // page styles it `display: block`, which is an author rule and beats
            // the browser's own `[hidden] { display: none }`. A check on the
            // property passed and the map underneath it was two pixels tall.
            mapShown: getComputedStyle(document.getElementById('liveMap')).display !== 'none',
            mapH: document.getElementById('liveMap').getBoundingClientRect().height,
            imgShown: getComputedStyle(img).display !== 'none' && r.height > 2,
            note: (document.getElementById('viewNote').textContent || '').trim(),
            noteH: document.getElementById('viewNote').getBoundingClientRect().height,
          };
        };
        const shown = await page.evaluate(LOOKAT);
        // Which side of the card the pane is on, in each thing it can show.
        // The owner's, 21 Oct: the feed on the LEFT — the near side of a panel
        // on the driver's right, and the picture is what gets tapped up to
        // read the phone in its mount. A string, so it is evaluated as written
        // in the page rather than closed over here.
        shown.side = await page.evaluate(SIDE_SRC);
        // The bar of controls with everything on it at once.
        //
        // Two of its buttons are conditional — "Took $8.04" appears when there
        // is an offer on the record, "Dropped off" while an order is in the car
        // — and both are hidden on a freshly loaded page, so every measurement
        // above is of a bar two buttons short of its widest. That is the bar a
        // driver never sees at the moment it matters: an offer on screen while
        // a job is already in the car is exactly when both show.
        // The ⌖ button's answers, which are its face for a while after a
        // press: the fullest bar is measured with each in turn below. The
        // refused-press face is read off the page, so a longer one is measured
        // as written (DEST_STORE_FACE, live.html).
        const destSrc = await (await fetch(base + '/live.html')).text();
        const destFaces = ['⌖ reading…', '⌖ not read',
          (/DEST_STORE_FACE = '([^']*)'/.exec(destSrc) || [])[1] || '(no DEST_STORE_FACE)'];
        shown.bar = await page.evaluate((faces) => {
          const took = document.getElementById('took');
          const drop = document.getElementById('drop');
          const bar = document.querySelector('.bottombar');
          const box = (el) => el.getBoundingClientRect();
          const dest = document.getElementById('dest');
          // What a driver can actually read off the button, glyph by glyph.
          //
          // `scrollWidth > clientWidth` was the whole test and it answers a
          // narrower question than it looks. These buttons are `overflow:
          // visible`, so a label too long for its button is not clipped by the
          // button — it is centred and painted out past both edges — and a
          // label allowed to wrap can spill downwards instead, which no width
          // comparison sees at all. Asking where each character landed catches
          // both, and is what a screenshot would show.
          const outside = (el) => {
            const r = box(el);
            const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
            const out = [];
            let node;
            while ((node = walk.nextNode())) {
              const range = document.createRange();
              for (let i = 0; i < node.length; i++) {
                range.setStart(node, i);
                range.setEnd(node, i + 1);
                const c = range.getBoundingClientRect();
                if (c.width === 0 && c.height === 0) continue;
                if (c.left < r.left - 0.5 || c.right > r.right + 0.5 ||
                    c.top < r.top - 0.5 || c.bottom > r.bottom + 0.5)
                  out.push(node.data[i]);
              }
            }
            return out.join('');
          };
          const measure = () => {
            const kids = [].slice.call(bar.children).filter((el) => {
              const r = box(el);
              return r.width > 0 && r.height > 0;
            });
            return {
              count: kids.length,
              // WHICH controls survived, not only how many. A count alone
              // cannot say whether the bar shed the link to the offer log or
              // the keypad, and that difference is the whole of why this bar
              // was changed: the log stood down for the entire length of a
              // shift and nobody could see it had.
              labels: kids.map((el) => (el.textContent || '').trim()),
              width: Math.round(box(bar).width),
              height: Math.round(box(bar).height),
              shortest: kids.length ? Math.min(...kids.map((el) => box(el).height)) : 0,
              // A label wider than the button holding it. On a control pressed
              // without looking that is worse than a small one: the driver
              // cannot tell which button they are on.
              clipped: kids.filter((el) => el.scrollWidth > Math.ceil(box(el).width) + 1)
                           .map((el) => (el.textContent || '').trim()),
              // ...and the same question asked of the pixels.
              spilling: kids.map((el) => [(el.textContent || '').trim(), outside(el)])
                            .filter((pair) => pair[1] !== '')
            };
          };
          // Four states, because the interesting comparison is not against an
          // empty bar. `plain` is the four fixed controls; `before` adds the
          // "Took ..." button, which is the bar as it stood before an order in
          // the car was a thing this panel knew about; `full` adds "Drop" on
          // top. What has to hold is that `full` clips nothing `before` did not
          // — anything else is this feature making the bar worse.
          //
          // `crowded` adds the destination button, and is the widest this bar
          // ever gets: a card on screen, a job in the car, and an address read
          // off it. It was missing here for as long as that button has
          // existed, so the six-control bar — the only one the 7" panel gets
          // wrong — was measured by nothing.
          took.hidden = true;
          drop.hidden = true;
          dest.hidden = true;
          const plain = measure();
          took.hidden = false;
          took.textContent = 'Took $12.45?';
          const before = measure();
          drop.hidden = false;
          const full = measure();
          dest.hidden = false;
          const crowded = measure();
          // ...and the same bar with each of ⌖'s answers on its face.
          const was = dest.textContent;
          const answers = faces.map((f) => {
            dest.textContent = f;
            return [f, measure().spilling];
          });
          dest.textContent = was;
          const d = document.documentElement;
          return { plain: plain, before: before, full: full, crowded: crowded,
                   answers: answers, over: d.scrollWidth > d.clientWidth + 1 };
        }, destFaces);
        // The line ▣ Set box leaves up for six seconds once a box is read,
        // in the page's own words, over the bar as it stands: each control's
        // width with the line up against its width without. The line widened
        // the phone's column by its own length and took the bar's controls
        // down to 16px at 800x480 while it showed.
        const pageSrc = await (await fetch(base + '/live.html')).text();
        const boxesSent = (/'(boxes sent — [^']*)'/.exec(pageSrc) || [])[1] || '';
        shown.sentHint = await page.evaluate((said) => {
          const bar = document.querySelector('.bottombar');
          const hint = document.getElementById('drawHint');
          const widths = () => [].slice.call(bar.children)
            .filter((el) => el.getBoundingClientRect().width > 0)
            .map((el) => [el.id || (el.textContent || '').trim(),
                          Math.round(el.getBoundingClientRect().width * 10) / 10]);
          const was = widths();
          const keep = [hint.hidden, hint.textContent];
          hint.hidden = false;
          hint.textContent = said;
          const now = widths();
          const phone = document.body.classList.contains('phoneview');
          hint.hidden = keep[0];
          hint.textContent = keep[1];
          return { said: said, phone: phone, was: was, now: now };
        }, boxesSent);
        // 📷 Snap, on the status row and off the bar — measured with the bar at
        // its fullest, which is where the block above leaves it.
        //
        // Three questions, and the third is the one that decided where it may
        // be drawn. Does it fit, with its label inside its own box? Does the
        // bar or the row it sits in move by so much as a tenth of a pixel for
        // its being there — with its label, and with the longest answer it
        // gives? And does the shift line beside it, which is the item on that
        // row that gives way, still get the median's digits onto the glass
        // when the connection line is at its longest? That last is measured
        // on every panel twice, as drawn and with the control forced onto the
        // row, so the panels that do not draw it are held to the reason they
        // do not — it used to be measured only as drawn, which on a panel that
        // hides it is the row without it, and proved nothing about the rule.
        shown.snap = await page.evaluate(SNAP_MEASURE, SNAP_FIXTURE);
        // Bounded, and the result kept rather than thrown.
        //
        // A layout fault that puts the picture over the controls does not make
        // this click fail — it makes it *wait*, because Playwright holds on for
        // the button to become reachable. Left unbounded that is the whole
        // driver's budget spent on one click, and the run ends in a stack trace
        // ten minutes later with every other check unreported. Measured: a
        // wrapper that stops filling its row draws the phone at its natural
        // 1000px inside a 468px panel and buries the bar. A control a driver
        // cannot reach is a result, so it is recorded as one.
        shown.reachable = await page.click('#viewMode', { timeout: 5000 })
          .then(() => true, () => false);
        await page.waitForTimeout(1200);
        const scene = await page.evaluate(LOOKAT);
        shown.sceneSide = await page.evaluate(SIDE_SRC);
        shown.was = scene.h;
        shown.sceneSrc = scene.src;
        shown.scenePressed = scene.pressed;
        shown.sceneLabel = scene.label;
        shown.sceneLoaded = scene.loaded;
        shown.sceneCut = Math.max(scene.cutTop, scene.cutBottom,
                                  scene.cutLeft, scene.cutRight);
        // ...and once more, into the map. Leaflet comes from a CDN this box
        // cannot reach, which is the interesting case rather than a limitation
        // of the harness: a rig on a phone hotspot in a car is offline several
        // times a shift, and what has to hold is that the pane says so, keeps
        // the bar reachable, and still offers the picture back.
        shown.mapReachable = await page.click('#viewMode', { timeout: 5000 })
          .then(() => true, () => false);
        await page.waitForTimeout(600);
        const onMap = await page.evaluate(LOOKAT);
        shown.mapLabel = onMap.label;
        shown.mapShown = onMap.mapShown;
        shown.mapImgShown = onMap.imgShown;
        shown.mapH = onMap.mapH;
        shown.mapRowH = onMap.rowH;
        shown.mapOver = onMap.over;
        shown.mapNote = onMap.note;
        shown.mapNoteH = onMap.noteH;
        // This harness has no offer on screen, so Map view lands between
        // offers: the map across the whole width (live.html setBetween).
        // Measured as it lands, then the class is taken off, so everything
        // below measures the map beside a verdict — the narrow one, which is
        // where every rule about its key, tip and caption is hardest.
        //
        // ...and taken off again at the top of each measurement below, inside
        // the same evaluate. The page's own one-second repaint (render(),
        // setBetween) puts the class back while nothing is on screen, and the
        // measurements below take longer than a second: on whichever ran
        // after a tick the map was across the whole width again. That is what
        // failed "the key with the held pickup in it ... in two rows ... at
        // 480x320" in 2 of 3 runs at b337a44 — one row, measured on a 464px
        // map instead of the hat's narrow one. A 1.1 s wait put before the key
        // failed it the same way; with the class taken off here, the same
        // wait passes. The fit was never wrong; the map it was measured on
        // was the wide one.
        shown.between = await page.evaluate(() => {
          const r = (sel) => document.querySelector(sel).getBoundingClientRect();
          const out = { on: document.body.classList.contains('between'),
                        live: getComputedStyle(document.querySelector('.live')).display !== 'none',
                        mapW: Math.round(r('#liveMap').width),
                        barW: Math.round(r('.bottombar').width),
                        over: document.documentElement.scrollWidth
                              > document.documentElement.clientWidth + 1
                              || document.documentElement.scrollHeight
                              > document.documentElement.clientHeight + 1 };
          document.body.classList.remove('between');
          out.offerMapW = Math.round(r('#liveMap').width);
          return out;
        });
        // ...and the map beside a card, measured while the class is off.
        shown.mapSide = await page.evaluate(
          "document.body.classList.remove('between'), " + SIDE_SRC);
        // Every sentence the caption under the map can say, measured in the
        // row it is said in.
        //
        // The pane is on the map here, which is the only state that row is
        // drawn in on a dashboard panel, and what is asked of each sentence is
        // what a screenshot would show: how many rows of the panel it took,
        // whether the clamp cut it, what survived the cut, and what the map
        // was left with. Character counts cannot answer any of those — two
        // strings of the same length come out one row and two depending on
        // where the spaces fall, and a place name of wide glyphs takes half
        // again the width of an ordinary one.
        // Each sentence is drawn by the page's own MV.sayCaption, the one
        // thing live.html's mapSay draws with: opened, which is the sentence,
        // and closed, which is its chip where it is a refusal (`chip`, then
        // measured the same way as `chipShot`) and the sentence again where
        // it is not.
        shown.caption = await page.evaluate((lines) => {
          document.body.classList.remove('between');
          const note = document.getElementById('viewNote');
          const liveMap = document.getElementById('liveMap');
          // What the page drew, put back whole afterwards: its words, its
          // chip and the state on the element that says which it is.
          const was = { html: note.innerHTML, cls: note.className, title: note.title,
                        role: note.getAttribute('role'),
                        exp: note.getAttribute('aria-expanded') };
          const out = {};
          const shot = () => {
            const box = note.getBoundingClientRect();
            // Row count and readable text taken off the characters themselves.
            // `scrollHeight` says a clamp cut something; only the per-character
            // rects say WHAT, and the rule this is here to hold is about which
            // half of a sentence survives.
            let visible = '';
            const tops = {};
            const walk = document.createTreeWalker(note, NodeFilter.SHOW_TEXT);
            const rg = document.createRange();
            let n;
            while ((n = walk.nextNode())) {
              for (let i = 0; i < n.length; i++) {
                rg.setStart(n, i);
                rg.setEnd(n, i + 1);
                const c = rg.getBoundingClientRect();
                if (c.width === 0 && c.height === 0) { visible += n.data[i]; continue; }
                if (c.bottom <= box.bottom + 1) {
                  visible += n.data[i];
                  tops[Math.round(c.top)] = 1;
                }
              }
            }
            // ...and a chip's own outline inside the row: what is drawn of it
            // past the caption's box, or past the glass, is a chip cut.
            const ch = note.querySelector('.chip');
            let chipOut = false;
            if (ch) {
              for (const r of ch.getClientRects()) {
                if (r.left < box.left - 0.5 || r.right > box.right + 0.5
                    || r.right > window.innerWidth + 0.5 || r.bottom > box.bottom + 1) {
                  chipOut = true;
                }
              }
            }
            return {
              h: Math.round(box.height), rows: Object.keys(tops).length, visible: visible,
              clipped: note.scrollHeight > note.clientHeight + 1, chipOut: chipOut,
              mapH: Math.round(liveMap.getBoundingClientRect().height),
            };
          };
          for (const pair of lines) {
            window.MapView.sayCaption(note, pair[1], true);
            const one = shot();
            one.chip = window.MapView.sayCaption(note, pair[1], false);
            if (one.chip) {
              one.chipShot = shot();
              one.chipTitle = note.title;
            }
            out[pair[0]] = one;
          }
          note.innerHTML = was.html;
          note.className = was.cls;
          note.title = was.title;
          ['role', 'exp'].forEach((k) => {
            const attr = k === 'exp' ? 'aria-expanded' : k;
            if (was[k] === null) note.removeAttribute(attr);
            else note.setAttribute(attr, was[k]);
          });
          return out;
        }, CAPTION_LINES);
        // The clamp itself, not just its effect. Measuring rows proves the
        // sentences fit TODAY; this proves the page is the thing holding them,
        // so a stylesheet edit that drops the rule fails here rather than
        // waiting for a sentence long enough to notice.
        // Leaflet's zoom buttons, as the page's own rule sizes them: a
        // stand-in with Leaflet's classes in the map, measured and removed.
        // Leaflet's stylesheet comes from the CDN this box cannot reach, so
        // the size is the page's rule alone (#liveMap .leaflet-control-zoom
        // a), which is the point: that rule is what makes them 48px. Leaflet
        // puts the bar 10px in with a 2px border, so the column of two ends
        // 10 + 2 + w + 2 across and 10 + 2 + 2h + 2 down.
        shown.zoom = await page.evaluate(() => {
          document.body.classList.remove('between');
          const z = document.createElement('div');
          z.className = 'leaflet-control-zoom leaflet-bar leaflet-control';
          z.innerHTML = '<a class="leaflet-control-zoom-in" href="#">+</a>'
            + '<a class="leaflet-control-zoom-out" href="#">\u2212</a>';
          document.getElementById('liveMap').appendChild(z);
          const a = z.querySelector('a').getBoundingClientRect();
          z.remove();
          return { w: Math.round(a.width), h: Math.round(a.height),
                   right: 10 + 2 + a.width + 2, bottom: 10 + 2 + 2 * a.height + 2 };
        });
        // ...and the "you are here" label in the map's corner, in every form
        // it can take: inside the map, clear of Leaflet's zoom buttons (as
        // measured above), in no more than two rows, and nothing spilling out
        // of its own box.
        shown.here = await page.evaluate(([lines, zoomRight]) => {
          document.body.classList.remove('between');
          const note = document.getElementById('hereNote');
          const map = document.getElementById('liveMap').getBoundingClientRect();
          const out = {};
          for (const pair of lines) {
            note.hidden = false;
            note.textContent = pair[1];
            const r = note.getBoundingClientRect();
            const tops = {};
            const n = note.firstChild;
            if (n) {
              const rg = document.createRange();
              for (let i = 0; i < n.length; i++) {
                rg.setStart(n, i);
                rg.setEnd(n, i + 1);
                const c = rg.getBoundingClientRect();
                if (c.width || c.height) tops[Math.round(c.top)] = 1;
              }
            }
            out[pair[0]] = {
              inside: r.left >= map.left - 0.5 && r.right <= map.right + 0.5
                && r.top >= map.top - 0.5 && r.bottom <= map.bottom + 0.5,
              clearOfZoom: r.left >= map.left + zoomRight,
              rows: Object.keys(tops).length,
              spills: note.scrollWidth > note.clientWidth + 1
                || note.scrollHeight > note.clientHeight + 1,
              w: Math.round(r.width), mapW: Math.round(map.width) };
          }
          note.hidden = true;
          note.textContent = '';
          return out;
        }, [LIVE_HERE_LINES, shown.zoom.right]);
        // ...and the key to how each place was found (drawHow), across the
        // map's foot: shown as the page's own rule draws it on this panel,
        // and asked the same of — inside the map, below the zoom buttons
        // (as measured above), ONE row,
        // nothing cut — plus which of its two forms this panel gets.
        // Both of its forms: what it says of the marks, and what it says
        // when drawing them failed (showKey(null)) — and the marks' form
        // with the held order's pickup ring in it too, which drops the long
        // words everywhere and takes two rows on the hat (see #mapKey's rule).
        // ...and, `lines`, with the order in the car's own marks in it too:
        // its run, the extra and the numbered stops (drawMap, showKey).
        const KEY_MEASURE = ([failed, hpick, zoomBottom, lines]) => {
          document.body.classList.remove('between');
          const key = document.getElementById('mapKey');
          const map = document.getElementById('liveMap').getBoundingClientRect();
          key.hidden = false;
          key.querySelector('.k-all').hidden = failed;
          key.querySelector('.k-fail').hidden = !failed;
          key.querySelector('.k-item[data-k="hpick"]').hidden = !hpick;
          ['run', 'job', 'extra', 'order'].forEach((k) => {
            key.querySelector('.k-item[data-k="' + k + '"]').hidden = !lines;
          });
          const r = key.getBoundingClientRect();
          const tops = {};
          const walk = document.createTreeWalker(key, NodeFilter.SHOW_TEXT);
          let text = '', n;
          while ((n = walk.nextNode())) {
            const rg = document.createRange();
            for (let i = 0; i < n.length; i++) {
              rg.setStart(n, i);
              rg.setEnd(n, i + 1);
              const c = rg.getBoundingClientRect();
              if (c.width || c.height) { tops[Math.round(c.top)] = 1; text += n.data[i]; }
            }
          }
          const out = {
            inside: r.left >= map.left - 0.5 && r.right <= map.right + 0.5
              && r.top >= map.top - 0.5 && r.bottom <= map.bottom + 0.5,
            belowZoom: r.top >= map.top + zoomBottom,
            rows: Object.keys(tops).length,
            spills: key.scrollWidth > key.clientWidth + 1
              || key.scrollHeight > key.clientHeight + 1,
            text: text.replace(/\s+/g, ' ').trim(),
            w: Math.round(r.width), mapW: Math.round(map.width) };
          key.hidden = true;
          key.querySelector('.k-all').hidden = false;
          key.querySelector('.k-fail').hidden = true;
          key.querySelector('.k-item[data-k="hpick"]').hidden = false;
          ['run', 'job', 'extra', 'order'].forEach((k) => {
            key.querySelector('.k-item[data-k="' + k + '"]').hidden = true;
          });
          return out;
        };
        shown.key = await page.evaluate(KEY_MEASURE, [false, false, shown.zoom.bottom]);
        shown.keyHeld = await page.evaluate(KEY_MEASURE, [false, true, shown.zoom.bottom]);
        shown.keyFailed = await page.evaluate(KEY_MEASURE, [true, false, shown.zoom.bottom]);
        shown.keyRun = await page.evaluate(KEY_MEASURE, [false, true, shown.zoom.bottom, true]);
        // ...and what a mark of drawHow's says when pointed at (#mapTip):
        // the longest the suite's marks say — a refused McDonald's with the
        // branch outside its 9.9 mi disc, 142 characters — in the one box
        // across the map's foot. The map places it, not the mark, so where
        // the mark is does not move it; what is asked is what a screenshot
        // shows: inside the map, every word in it (nothing cut), and its rows.
        // It replaced a Leaflet tooltip beside the mark, which the map clipped
        // by up to 92px on the hat (see #mapTip's rule).
        shown.tip = await page.evaluate((text) => {
          document.body.classList.remove('between');
          const tip = document.getElementById('mapTip');
          const map = document.getElementById('liveMap').getBoundingClientRect();
          tip.textContent = text;
          tip.hidden = false;
          const r = tip.getBoundingClientRect();
          const tops = {};
          let seen = '';
          const n = tip.firstChild;
          const rg = document.createRange();
          for (let i = 0; i < n.length; i++) {
            rg.setStart(n, i);
            rg.setEnd(n, i + 1);
            const c = rg.getBoundingClientRect();
            if (!c.width && !c.height) { seen += n.data[i]; continue; }
            if (c.left >= map.left - 0.5 && c.right <= map.right + 0.5
                && c.top >= map.top - 0.5 && c.bottom <= map.bottom + 0.5
                && c.right <= r.right + 0.5 && c.bottom <= r.bottom + 0.5) {
              seen += n.data[i];
              tops[Math.round(c.top)] = 1;
            }
          }
          const out = {
            inside: r.left >= map.left - 0.5 && r.right <= map.right + 0.5
              && r.top >= map.top - 0.5 && r.bottom <= map.bottom + 0.5,
            whole: seen === text,
            spills: tip.scrollWidth > tip.clientWidth + 1
              || tip.scrollHeight > tip.clientHeight + 1,
            rows: Object.keys(tops).length,
            h: Math.round(r.height), mapH: Math.round(map.height),
            w: Math.round(r.width), mapW: Math.round(map.width) };
          tip.hidden = true;
          tip.textContent = '';
          return out;
        }, "no pin for McDonald's… — 2 fit the card and disagree · within 9.4 mi of you"
           + " · this one 10.6 mi from the card's fix, outside the 9.9 mi searched");
        shown.captionStyle = await page.evaluate(() => {
          document.body.classList.remove('between');
          const cs = getComputedStyle(document.getElementById('viewNote'));
          return { overflow: cs.overflow,
                   clamp: cs.getPropertyValue('-webkit-line-clamp') };
        });
        // ...and back to the picture, which is where the driver spends the
        // shift. A cycle that cannot be completed is a driver stuck on a map.
        shown.backReachable = await page.click('#viewMode', { timeout: 5000 })
          .then(() => true, () => false);
        await page.waitForTimeout(600);
        const back = await page.evaluate(LOOKAT);
        shown.backLabel = back.label;
        shown.backMapShown = back.mapShown;
        shown.backImgShown = back.imgShown;
        out[panel[0] + ' phoneview'] = shown;
      }
      // 📷 Snaps with its snaps ticked: the one state in which its bar has a
      // third link, the ticked ones as one file. Drawn only once something is
      // ticked, so the page as it lands, measured above, never has it.
      if (name === 'snaps.html') {
        for (const tick of await page.$$('#shelf .snap .pick input')) {
          await tick.check({ timeout: 2000 }).catch(() => {});
        }
        out[panel[0] + ' snaps chosen'] = await page.evaluate(() => {
          const d = document.documentElement;
          const links = [].slice.call(document.querySelectorAll('.bottombar a'))
            .filter((a) => a.getBoundingClientRect().width > 0);
          // Where each glyph of a label landed, as the bar on live.html is
          // asked: a width comparison misses a label that wraps, because a
          // bar link is allowed to wrap rather than clip, and grows a line
          // taller instead of overflowing. So: every glyph inside its link,
          // and all of them on one line — their tops within half the font's
          // size of each other.
          const unread = (el) => {
            const r = el.getBoundingClientRect();
            const px = parseFloat(getComputedStyle(el).fontSize);
            const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
            const tops = [];
            let outside = '';
            let node;
            while ((node = walk.nextNode())) {
              const rg = document.createRange();
              for (let i = 0; i < node.length; i++) {
                if (/\s/.test(node.data[i])) continue;
                rg.setStart(node, i);
                rg.setEnd(node, i + 1);
                const c = rg.getBoundingClientRect();
                if (!c.width && !c.height) continue;
                tops.push(c.top);
                if (c.left < r.left - 0.5 || c.right > r.right + 0.5 ||
                    c.top < r.top - 0.5 || c.bottom > r.bottom + 0.5) outside += node.data[i];
              }
            }
            const spread = tops.length ? Math.max.apply(null, tops) - Math.min.apply(null, tops) : 0;
            return outside || (spread > px / 2 ? 'on ' + Math.round(spread / px + 1) + ' lines' : '');
          };
          return {
            labels: links.map((a) => a.textContent),
            unread: links.map((a) => [a.textContent, unread(a)]).filter((p) => p[1]),
            shortest: Math.min.apply(null, links.map((a) => a.getBoundingClientRect().height)),
            sideways: d.scrollWidth > d.clientWidth + 1,
          };
        });
        // ...and the one file a snap is saved as, opened at this size: the
        // snap that carries the longest note the rig keeps, with no space in
        // it to wrap at — a heading that pushes the page past the glass.
        const noted = await page.evaluate(() => {
          const n = document.querySelector('#shelf .snap h2 .noted:not(:empty)');
          return n ? n.closest('.snap').getAttribute('data-name') : null;
        });
        const file = noted ? await page.evaluate((n) => fetch(
          '/api/snaps/bundle?snap=' + encodeURIComponent(n)).then((r) => r.text()), noted) : '';
        const opened = await ctx.newPage();
        await opened.setContent(file, { waitUntil: 'load' }).catch(() => {});
        out[panel[0] + ' snap file'] = await opened.evaluate(() => {
          const d = document.documentElement;
          return {
            note: (document.querySelector('h2 .note') || {}).textContent || '',
            pictures: document.images.length,
            sideways: d.scrollWidth > d.clientWidth + 1,
          };
        }).catch((e) => ({ error: String(e).slice(0, 200) }));
        await opened.close();
      }
      // The one section on this page about two offers at once.
      //
      // Its rows carry more in a summary than an offer row does — a range, two
      // payouts, a place and an outcome — so it is the row most likely to run
      // out of width, and it is read parked on whichever screen is to hand.
      if (name === 'journal.html') {
        out[panel[0] + ' pairs'] = await page.evaluate(() => {
          const head = document.getElementById('pairsHead');
          const list = document.getElementById('pairs');
          const rows = [].slice.call(list.querySelectorAll('details.pair'));
          const d = document.documentElement;
          const wide = (el) => {
            const r = el.getBoundingClientRect();
            return r.right > d.clientWidth + 1 || r.left < -1;
          };
          // Opened, because the arithmetic a driver checks the advice against
          // is inside — and a `<dl>` that only fits while folded away fits
          // nothing.
          rows.forEach((r) => { r.open = true; });
          const dds = [].slice.call(list.querySelectorAll('dd'));
          return {
            headShown: !head.hidden,
            headText: (head.textContent || '').trim(),
            lead: (document.getElementById('pairsLead').textContent || '').trim(),
            count: rows.length,
            // What each row says without being opened, which is what makes the
            // list worth scrolling.
            summaries: rows.map((r) => (r.querySelector('summary').textContent || '')
                                       .replace(/\s+/g, ' ').trim()),
            states: rows.map((r) => {
              const dot = r.querySelector('.dot');
              return dot ? dot.className.replace('dot', '').trim() : '';
            }),
            outside: rows.filter(wide).length + dds.filter(wide).length,
            pageWide: d.scrollWidth > d.clientWidth + 1,
          };
        });

        /* The map sheet, on every panel this gets bolted to.
         *
         * Opened by hand rather than by pressing a control: the fixture's
         * offers name no places, and nothing here is about the geocoder. What
         * is being measured is the CSS — that the sheet fits the glass, and
         * that the room it takes is given back to the log underneath, so the
         * last offer in the list can still be scrolled to.
         *
         * That second one had already gone wrong once. The sheet is taller on
         * the 3.5" hat, where half a screen is a map too small to read, and
         * the rule handing the room back stayed at the height the sheet used
         * to be — which puts the end of the log permanently under the panel on
         * the one screen where the log is shortest. */
        out[panel[0] + ' sheet'] = await page.evaluate(async () => {
          const d = document.documentElement;
          const sheet = document.getElementById('sheet');
          document.getElementById('sheetWhere').textContent =
            'Chastain Rd NW, Kennesaw  →  Peachtree St NE, Atlanta';
          document.getElementById('sheetNote').textContent =
            '24.6 mi straight line, card said 3 mi in total — which cannot be '
            + 'right, so one of these pins is wrong.';
          document.getElementById('sheetOut').hidden = false;
          sheet.hidden = false;
          document.body.classList.add('sheeted');
          await new Promise((r) => requestAnimationFrame(() => r()));
          const box = sheet.getBoundingClientRect();
          const app = document.getElementById('app');
          // Scrolled to the very bottom, which is where a sheet that takes
          // room without giving it back hides the oldest rows.
          window.scrollTo(0, d.scrollHeight);
          await new Promise((r) => requestAnimationFrame(() => r()));
          const rows = [].slice.call(document.querySelectorAll('#log details.offer'));
          const last = rows[rows.length - 1];
          const lastBox = last ? last.getBoundingClientRect() : null;
          const shut = document.getElementById('sheetShut').getBoundingClientRect();
          window.scrollTo(0, 0);
          return {
            // On the glass, top and bottom, and no wider than it.
            onScreen: box.top >= -1 && box.bottom <= d.clientHeight + 1
                      && box.left >= -1 && box.right <= d.clientWidth + 1,
            height: Math.round(box.height),
            // Enough map to tell one side of a metro from the other. Below
            // about 120px the tiles are a texture rather than a place.
            mapTall: Math.round(
              document.getElementById('sheetMap').getBoundingClientRect().height),
            // The close button, which is the only way out on a screen with no
            // keyboard, has to be reachable and hittable.
            shutOn: shut.top >= -1 && shut.bottom <= d.clientHeight + 1,
            shutTall: Math.round(shut.height),
            // The last row of the log, with the page scrolled as far as it
            // goes: its top must clear the top of the sheet.
            lastClear: lastBox ? lastBox.top < box.top - 1 : null,
            padded: Math.round(parseFloat(getComputedStyle(app).paddingBottom)),
            pageWide: d.scrollWidth > d.clientWidth + 1,
          };
        });

        /* Close the shift, opened. Folded it is one line and the checks above
         * already see that line; what they cannot see is inside, where every
         * row carries two answers at 52px beside the payout, the distance and
         * a place — the most the page asks of one row's width — and nothing
         * inside a closed <details> has a box to measure. */
        out[panel[0] + ' review'] = await page.evaluate(async () => {
          const d = document.documentElement;
          const box = document.getElementById('review');
          if (!box || box.hidden) return { shown: false };
          box.open = true;
          await new Promise((r) => requestAnimationFrame(() => r()));
          const rows = [].slice.call(box.querySelectorAll('.ask'));
          const buttons = [].slice.call(box.querySelectorAll('.ask button'));
          // The day either side: the one that can be pressed (the newest day
          // has nothing after it, and that end is kept in place unseen).
          const steps = [].slice.call(box.querySelectorAll('.days button'))
            .filter((b) => !b.disabled && b.getBoundingClientRect().width);
          const wide = (el) => {
            const r = el.getBoundingClientRect();
            return r.right > d.clientWidth + 1 || r.left < -1;
          };
          // Every figure on a row — the pay, the minutes, the miles — inside
          // the box it is drawn in. A box edge check cannot see this: the
          // figures used to run under an ellipsis INSIDE a box that fitted,
          // and at 390px the miles of the owner's 4:43am card read "49.".
          const cut = rows.map((a) => {
            const what = a.querySelector('.what'), figs = a.querySelector('.figs');
            if (!figs) return 'no figures on ' + a.getAttribute('data-id');
            const edge = what.getBoundingClientRect();
            const range = document.createRange();
            range.selectNodeContents(figs);
            return [].slice.call(range.getClientRects())
              .some((q) => q.right > edge.right + 1 || q.left < edge.left - 1)
              ? figs.textContent : null;
          }).filter(Boolean);
          let smallest = null, smallestIn = '';
          const walk = document.createTreeWalker(box, NodeFilter.SHOW_TEXT);
          let n;
          while ((n = walk.nextNode())) {
            if (!(n.nodeValue || '').trim()) continue;
            const el = n.parentElement;
            const r = el.getBoundingClientRect();
            if (!r.width || !r.height) continue;
            const px = parseFloat(getComputedStyle(el).fontSize);
            if (smallest === null || px < smallest) {
              smallest = px;
              smallestIn = (el.id || el.className || el.tagName).toString().slice(0, 30);
            }
          }
          const result = {
            shown: true, rows: rows.length,
            says: (document.getElementById('reviewSays').textContent || '')
              .replace(/\s+/g, ' ').trim(),
            lineH: box.querySelector('summary').getBoundingClientRect().height,
            shortest: buttons.length
              ? Math.min.apply(null, buttons.map((b) => b.getBoundingClientRect().height)) : 0,
            steps: steps.map((b) => ({ text: b.textContent,
                                       h: b.getBoundingClientRect().height })),
            outside: rows.filter(wide).length + buttons.filter(wide).length
                     + steps.filter(wide).length,
            clipped: buttons.concat(steps)
                            .filter((b) => b.scrollWidth > Math.ceil(b.getBoundingClientRect().width) + 1)
                            .map((b) => b.textContent),
            cut: cut,
            smallest: smallest, smallestIn: smallestIn,
            leadW: document.getElementById('reviewLead').getBoundingClientRect().width,
            pageWide: d.scrollWidth > d.clientWidth + 1,
          };
          box.open = false;
          return result;
        });
      }
      await page.close();
    }
    await ctx.close();
  }
  // 📷 Snap alone, on the screens either side of where its room runs out:
  // live.html as it lands, with the same pictures, and the same measurement.
  for (const panel of SNAP_PANELS) {
    const ctx = await browser.newContext({
      viewport: { width: panel[1], height: panel[2] }, deviceScaleFactor: 1,
    });
    const page = await ctx.newPage();
    await page.route('**/api/frame.*', (route) => {
      const view = /view=screen/.test(route.request().url()) ? 'screen' : 'scene';
      route.fulfill({ status: 200, contentType: 'image/jpeg',
                      body: Buffer.from(FRAMES[view], 'base64') });
    });
    await page.goto(base + '/live.html', { waitUntil: 'domcontentloaded' }).catch(() => {});
    await page.waitForTimeout(1800);
    out[panel[0] + ' snap'] = await page.evaluate(SNAP_MEASURE, SNAP_FIXTURE);
    await page.close();
    await ctx.close();
  }
  // The line under the verdict when a reading has none, on the rig's own
  // panel and the two it is proven at, in both pictures. The scene picture is
  // the narrower verdict, and it is the width the rig's own panel had on 8 Oct
  // with the phone up: 500px of 1024. Each sentence is measured against the
  // one it replaced, on one page, so "moves nothing" is a comparison with the
  // panel as it was and not a guess at what fits.
  for (const panel of NOVERDICT_PANELS) {
    for (const view of ['screen', 'scene']) {
      const ctx = await browser.newContext({
        viewport: { width: panel[1], height: panel[2] }, deviceScaleFactor: 1,
      });
      const page = await ctx.newPage();
      await page.addInitScript((v) => {
        try { localStorage.setItem('uberscan.liveView', v); } catch (e) {}
        class FakeEventSource {
          constructor(url) { this.url = url; window.__es = this; }
          close() {}
          push(obj) { if (this.onmessage) this.onmessage({ data: JSON.stringify(obj) }); }
        }
        window.EventSource = FakeEventSource;
      }, view);
      await page.route('**/api/frame.*', (route) => {
        const v = /view=screen/.test(route.request().url()) ? 'screen' : 'scene';
        route.fulfill({ status: 200, contentType: 'image/jpeg',
                        body: Buffer.from(FRAMES[v], 'base64') });
      });
      await page.route('**/api/status*', (route) => route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ scanner: { enabled: true, running: true, error: null },
                               status: { phase: 'scanning', message: '' },
                               last: null, lastAgeMs: null, heardAgeMs: 400,
                               offer: null, holding: null }) }));
      // The widest real shift (the shape SNAP_FIXTURE carries), for the row.
      await page.route('**/api/today*', (route) => route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ offers: 435, counted: 428, setAside: 7, took: 10,
                               median: -17, earned: 140.5, earnedCost: 31.0,
                               beforeClock: 0, unreadable: null, rolled: false,
                               clockSet: true }) }));
      await page.goto(base + '/live.html', { waitUntil: 'domcontentloaded' }).catch(() => {});
      await page.waitForFunction(() => document.getElementById('view').naturalWidth > 2,
                                 null, { timeout: 10000 }).catch(() => {});
      await page.waitForTimeout(600);
      const slot = {};
      for (const [key, reading] of Object.entries(NOVERDICT)) {
        await page.evaluate((r) => {
          window.__es.push({ alive: true, at: 1 });
          (Array.isArray(r) ? r : [r]).forEach((m) => window.__es.push(m));
        }, reading);
        await page.waitForTimeout(150);
        slot[key] = await page.evaluate(() => {
          const d = document.getElementById('detail');
          const r = d.getBoundingClientRect();
          const cs = getComputedStyle(d);
          const line = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.2;
          // Every letter inside the line's own width and on the glass: what a
          // screenshot would show, which a width comparison does not. Up and
          // down against the glass alone — on the 3.5" hat this line is set
          // at `line-height: 1`, so every glyph's own box is taller than the
          // line's, the old sentence's included, and nothing clips it.
          const off = [];
          const walk = document.createTreeWalker(d, NodeFilter.SHOW_TEXT);
          const rg = document.createRange();
          let n;
          while ((n = walk.nextNode())) {
            for (let i = 0; i < n.length; i++) {
              rg.setStart(n, i);
              rg.setEnd(n, i + 1);
              const c = rg.getBoundingClientRect();
              if (!c.width && !c.height) continue;
              if (c.left < Math.max(0, r.left) - 0.5
                  || c.right > Math.min(window.innerWidth, r.right) + 0.5
                  || c.top < -0.5 || c.bottom > window.innerHeight + 0.5) off.push(n.data[i]);
            }
          }
          const box = (sel) => {
            const b = document.querySelector(sel).getBoundingClientRect();
            return [b.left, b.top, b.width, b.height].map((v) => Math.round(v * 10) / 10);
          };
          // The words' own width, in the page's font: of the sentence alone
          // when there is no note, which is the one compared.
          const all = document.createRange();
          all.selectNodeContents(d);
          // No "the page still fits" here. It was asked, and it could not
          // fail: #app clips rather than scrolls, so the sentence twelve
          // times over and a `white-space: nowrap` that ran it off the glass
          // both left the page's scroll size alone. The letters are what a
          // driver would miss, and `off` above is what asks after them.
          // ...and the verdict's own label, whose words change for one of
          // these: every letter inside the verdict card and on the glass.
          const lab = document.getElementById('verdictLabel');
          const card = document.getElementById('verdict').getBoundingClientRect();
          const labOff = [];
          const lw = document.createTreeWalker(lab, NodeFilter.SHOW_TEXT);
          while ((n = lw.nextNode())) {
            for (let i = 0; i < n.length; i++) {
              rg.setStart(n, i);
              rg.setEnd(n, i + 1);
              const c = rg.getBoundingClientRect();
              if (!c.width && !c.height) continue;
              if (c.left < Math.max(0, card.left) - 0.5
                  || c.right > Math.min(window.innerWidth, card.right) + 0.5
                  || c.top < Math.max(0, card.top) - 0.5
                  || c.bottom > Math.min(window.innerHeight, card.bottom) + 0.5) labOff.push(n.data[i]);
            }
          }
          const labRange = document.createRange();
          labRange.selectNodeContents(lab);
          return {
            text: d.textContent.trim(),
            label: lab.textContent.trim(),
            labelOff: labOff.join(''),
            labelLines: Math.round(labRange.getClientRects().length),
            width: Math.round(all.getBoundingClientRect().width * 10) / 10,
            lines: Math.round(r.height / line),
            off: off.join(''),
            // Everything else on the panel a driver reads or presses.
            layout: { label: box('#verdictLabel'), verdict: box('#verdict'),
                      bar: box('.bottombar'), row: box('.connbar'), view: box('#viewWrap') },
            phone: document.body.classList.contains('phoneview'),
          };
        });
      }
      out[panel[0] + ' ' + view + ' noverdict'] = slot;
      // ...and on the same page, a card with a verdict whose payout is labelled
      // PAY ?, against the same card labelled PAY.
      const fp = {};
      for (const [key, reading] of Object.entries(FOUNDPAY)) {
        await page.evaluate((r) => {
          window.__es.push({ alive: true, at: 1 });
          window.__es.push(r);
        }, reading);
        await page.waitForTimeout(150);
        fp[key] = await page.evaluate(() => {
          const lab = document.getElementById('lPay');
          const cell = lab.parentElement.getBoundingClientRect();
          const off = [];
          const walk = document.createTreeWalker(lab, NodeFilter.SHOW_TEXT);
          const rg = document.createRange();
          let n;
          while ((n = walk.nextNode())) {
            for (let i = 0; i < n.length; i++) {
              rg.setStart(n, i);
              rg.setEnd(n, i + 1);
              const c = rg.getBoundingClientRect();
              if (!c.width && !c.height) continue;
              if (c.left < Math.max(0, cell.left) - 0.5
                  || c.right > Math.min(window.innerWidth, cell.right) + 0.5
                  || c.top < -0.5 || c.bottom > window.innerHeight + 0.5) off.push(n.data[i]);
            }
          }
          const box = (sel) => {
            const b = document.querySelector(sel).getBoundingClientRect();
            return [b.left, b.top, b.width, b.height].map((v) => Math.round(v * 10) / 10);
          };
          const cs = getComputedStyle(lab);
          const v = document.getElementById('vPay').getBoundingClientRect();
          return {
            text: lab.textContent.trim(),
            // The figure inside its own cell: the label beside it is what
            // changes, and the cell centres the two together.
            payIn: v.left >= cell.left - 0.5 && v.right <= cell.right + 0.5,
            shown: cell.width > 0 && cs.display !== 'none' && cs.visibility !== 'hidden',
            off: off.join(''),
            layout: { label: box('#verdictLabel'), verdict: box('#verdict'),
                      pay: box('#vPay'), min: box('#vMin'), mile: box('#vMile'),
                      perMile: box('#vPerMile'), minLabel: box('#lMin'),
                      bar: box('.bottombar'), row: box('.connbar'), view: box('#viewWrap') },
          };
        });
      }
      out[panel[0] + ' ' + view + ' foundpay'] = fp;
      // ...and the notices as chips, then tapped open to their sentences.
      const CHIPS_MEASURE = () => {
        const w = document.getElementById('warn');
        const vr = document.getElementById('verdict').getBoundingClientRect();
        const card = { left: vr.left + 2, right: vr.right - 2, top: vr.top + 2, bottom: vr.bottom - 2 };
        const off = [];
        const walk = document.createTreeWalker(w, NodeFilter.SHOW_TEXT);
        const rg = document.createRange();
        let n;
        while ((n = walk.nextNode())) {
          for (let i = 0; i < n.length; i++) {
            rg.setStart(n, i);
            rg.setEnd(n, i + 1);
            const c = rg.getBoundingClientRect();
            if (!c.width && !c.height) continue;
            const wr = w.getBoundingClientRect();
            // On the glass, inside the card, and inside the notice's own box
            // (what scrolls out of that box is reachable, not lost: asked below).
            if (c.left < Math.max(0, card.left) - 0.5
                || c.right > Math.min(window.innerWidth, card.right) + 0.5
                || (c.top >= wr.top - 0.5 && c.bottom <= wr.bottom + 0.5
                    && (c.top < Math.max(0, card.top) - 0.5
                        || c.bottom > Math.min(window.innerHeight, card.bottom) + 0.5))) {
              if (/\S/.test(n.data[i])) off.push(n.data[i]);
            }
          }
        }
        const inCard = (sel) => {
          const b = document.querySelector(sel).getBoundingClientRect();
          return b.height > 0 && b.top >= card.top - 0.5 && b.bottom <= card.bottom + 0.5;
        };
        const box = (sel) => {
          const b = document.querySelector(sel).getBoundingClientRect();
          return [b.left, b.top, b.width, b.height].map((v) => Math.round(v * 10) / 10);
        };
        let reach = w.scrollHeight <= w.clientHeight + 1;
        if (!reach) { w.scrollTop = 9999; reach = w.scrollTop > 0; w.scrollTop = 0; }
        const d = document.documentElement;
        return {
          chips: [].slice.call(w.querySelectorAll('.chip')).map((c) => c.textContent),
          text: w.textContent.replace(/\s+/g, ' ').trim(),
          off: off.join(''), need: w.scrollHeight, reach: reach,
          labelIn: inCard('#verdictLabel'), rateIn: inCard('.rate.big'),
          // The small type on this card, as rendered (see SMALL_SIZES).
          sizes: ['#places', '#lPay', '#vPay', '#detail', '#warn', '.connbar'].map(
            (sel) => parseFloat(getComputedStyle(document.querySelector(sel)).fontSize)),
          placesIn: inCard('#places'), subIn: inCard('.submetrics'),
          layout: { bar: box('.bottombar'), row: box('.connbar'), view: box('#viewWrap') },
          over: d.scrollWidth > d.clientWidth + 1 || d.scrollHeight > d.clientHeight + 1,
        };
      };
      // The fifth chip is about the card on record, and a card on record puts
      // ✓ Took on the bar, which moves it: so what the chips are held to is
      // that card on record with no notice at all — its end the card's own,
      // not one read with ⌖ — and the bar, the row and the picture where it
      // left them.
      await page.evaluate((a) => {
        window.__es.push({ alive: true, at: 1, notSaving: null, tooBright: false });
        window.__es.push({ offer: Object.assign({}, a[0].offer, { dropoffScanned: false,
                                                                  dropoffFrom: null }) });
        window.__es.push(a[1]);
      }, [CHIPS.offer, FOUNDPAY.drawn3]);
      await page.waitForTimeout(200);
      const chipsBase = await page.evaluate(CHIPS_MEASURE);
      await page.evaluate((a) => {
        window.__es.push(a[0]);
        window.__es.push(a[2]);
        window.__es.push(a[1]);
      }, [CHIPS.beat, CHIPS.card, CHIPS.offer]);
      await page.waitForTimeout(200);
      const chipsAt = { chips: await page.evaluate(CHIPS_MEASURE),
                        base: { chips: chipsBase.chips, layout: chipsBase.layout } };
      await page.click('#warn', { timeout: 5000 }).catch(() => {});
      await page.waitForTimeout(200);
      chipsAt.open = await page.evaluate(CHIPS_MEASURE);
      out[panel[0] + ' ' + view + ' chips'] = chipsAt;
      // ...and the status row in the steady state, short, with "…" opened.
      await page.click('#warn', { timeout: 5000 }).catch(() => {});
      await page.evaluate(() => {
        if (window.__es.onopen) window.__es.onopen();
        window.__es.push({ alive: true, at: 1, notSaving: null, tooBright: false });
      });
      await page.waitForTimeout(200);
      const ROW_MEASURE = () => {
        const d = document.documentElement;
        const row = document.querySelector('.connbar');
        const more = document.getElementById('more');
        const shift = document.getElementById('shift');
        const sheet = document.getElementById('moreSheet');
        const box = (el) => {
          const b = el.getBoundingClientRect();
          return [b.left, b.top, b.width, b.height].map((v) => Math.round(v * 10) / 10);
        };
        const glyphsOut = (el, r) => {
          let out = '';
          const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
          const rg = document.createRange();
          let n;
          while ((n = walk.nextNode())) {
            for (let i = 0; i < n.length; i++) {
              rg.setStart(n, i);
              rg.setEnd(n, i + 1);
              const c = rg.getBoundingClientRect();
              if (!c.width && !c.height) continue;
              if (c.left < Math.max(0, r.left) - 0.5 || c.right > Math.min(window.innerWidth, r.right) + 0.5
                  || c.top < Math.max(0, r.top) - 0.5
                  || c.bottom > Math.min(window.innerHeight, r.bottom) + 0.5) out += n.data[i];
            }
          }
          return out;
        };
        const sr = shift.getBoundingClientRect();
        // The median's digits, found by shape (as test_dashboard's hat check).
        const m = /(-?\$\d+\/hr)/.exec(shift.textContent);
        let figureIn = false;
        if (m && shift.firstChild) {
          const at = shift.firstChild.nodeValue.indexOf(m[1]);
          const rg = document.createRange();
          rg.setStart(shift.firstChild, at);
          rg.setEnd(shift.firstChild, at + m[1].length);
          const fr = rg.getBoundingClientRect();
          figureIn = fr.right <= sr.right + 0.5 && fr.right <= window.innerWidth + 0.5;
        }
        const layout = () => JSON.stringify({ row: box(row), bar: [].slice.call(
          document.querySelector('.bottombar').children).map(box) });
        const withIt = layout();
        more.style.display = 'none';
        const without = layout();
        more.style.display = '';
        const mr = more.getBoundingClientRect();
        const live = document.querySelector('.live').getBoundingClientRect();
        const shR = sheet.getBoundingClientRect();
        return {
          conn: getComputedStyle(document.getElementById('conn')).display !== 'none',
          shift: shift.textContent, shiftWhole: shift.scrollWidth <= shift.clientWidth + 1,
          figureIn: figureIn,
          more: mr.width > 0 && mr.left >= -0.5 && mr.right <= window.innerWidth + 0.5
                && mr.bottom <= window.innerHeight + 0.5 && !!more.closest('.connbar'),
          moreOut: glyphsOut(more, mr), moreW: Math.round(mr.width),
          moreCostsNothing: withIt === without,
          sheet: !sheet.hidden && shR.height > 0,
          sheetOut: sheet.hidden ? '' : glyphsOut(sheet, shR),
          sheetInPane: sheet.hidden || (shR.left >= live.left - 1 && shR.right <= live.right + 1
                                        && shR.top >= -0.5
                                        && shR.bottom <= row.getBoundingClientRect().top + 0.5),
          layout: layout(),
          over: d.scrollWidth > d.clientWidth + 1 || d.scrollHeight > d.clientHeight + 1,
        };
      };
      const rowAt = { closed: await page.evaluate(ROW_MEASURE) };
      await page.click('#more', { timeout: 5000 }).catch(() => {});
      await page.waitForTimeout(150);
      rowAt.open = await page.evaluate(ROW_MEASURE);
      await page.click('#more', { timeout: 5000 }).catch(() => {});
      out[panel[0] + ' ' + view + ' row'] = rowAt;
      // ...and the heat guard's chip on the same row (live.html heatNote),
      // beat by beat, beside the widest real shift line staged above. See
      // HEAT_BEATS on the Python side.
      const heatAt = {};
      for (const [key, beat] of Object.entries(HEAT_BEATS)) {
        await page.evaluate((b) => window.__es.push(Object.assign(
          { alive: true, at: 1, notSaving: null, tooBright: false, tooDim: false,
            cpuCWhy: null, throttledWhy: null }, b)), beat);
        await page.waitForTimeout(150);
        heatAt[key] = await page.evaluate((fixture) => {
          const d = document.documentElement;
          const h = document.getElementById('health');
          const shift = document.getElementById('shift');
          const chip = h.querySelector('.chip');
          const box = (el) => {
            const b = el.getBoundingClientRect();
            return [b.left, b.top, b.width, b.height].map((v) => Math.round(v * 10) / 10);
          };
          const hr = h.getBoundingClientRect();
          const cr = chip ? chip.getBoundingClientRect() : null;
          // The median's digits, found by shape, as ROW_MEASURE finds them.
          const m = /(-?\$\d+\/hr)/.exec(shift.textContent);
          let figureIn = false;
          if (m && shift.firstChild) {
            const at = shift.firstChild.nodeValue.indexOf(m[1]);
            const rg = document.createRange();
            rg.setStart(shift.firstChild, at);
            rg.setEnd(shift.firstChild, at + m[1].length);
            const fr = rg.getBoundingClientRect();
            figureIn = fr.right <= shift.getBoundingClientRect().right + 0.5
                       && fr.right <= window.innerWidth + 0.5;
          }
          const out = {
            text: h.hidden ? '' : h.textContent,
            chip: chip ? chip.textContent : null,
            title: chip ? chip.title : null,
            shown: !h.hidden && hr.width > 0 && hr.left >= -0.5
                   && hr.right <= window.innerWidth + 0.5,
            whole: h.scrollWidth <= h.clientWidth + 1,
            chipIn: !!cr && cr.left >= hr.left - 0.5 && cr.right <= hr.right + 0.5,
            w: Math.round(hr.width * 10) / 10,
            figureIn: figureIn,
            layout: JSON.stringify({ row: box(document.querySelector('.connbar')),
                                     bar: [].slice.call(document.querySelector('.bottombar')
                                       .children).map(box) }),
            over: d.scrollWidth > d.clientWidth + 1 || d.scrollHeight > d.clientHeight + 1,
          };
          // ...and the widest note the row held before the chip, as plain
          // words on this same row: what "no wider than before" is held to.
          if (!h.hidden) {
            const keep = [].slice.call(h.childNodes);
            h.textContent = fixture;
            out.wasW = Math.round(h.getBoundingClientRect().width * 10) / 10;
            h.textContent = '';
            keep.forEach((n) => h.appendChild(n));
          }
          return out;
        }, HEAT_WAS);
        if (key === 'alone') {
          // The sentence, one press away on "…", and on the glass.
          await page.click('#more', { timeout: 5000 }).catch(() => {});
          await page.waitForTimeout(150);
          heatAt.sheet = await page.evaluate(() => {
            const s = document.getElementById('moreSheet');
            const r = s.getBoundingClientRect();
            return { lines: [].slice.call(s.querySelectorAll('.m-health')).map((n) => n.textContent),
                     onGlass: !s.hidden && r.left >= -0.5 && r.top >= -0.5
                              && r.right <= window.innerWidth + 0.5
                              && r.bottom <= window.innerHeight + 0.5 };
          });
          await page.click('#more', { timeout: 5000 }).catch(() => {});
          await page.waitForTimeout(100);
        }
      }
      out[panel[0] + ' ' + view + ' heat'] = heatAt;
      await page.evaluate(() => window.__es.push({ alive: true, at: 1, heatGuard: false,
                                                   gps: null, throttled: null, cpuC: null }));
      await page.waitForTimeout(100);
      // ...and the night palette (html.night) on the same card: colours only.
      out[panel[0] + ' ' + view + ' night'] = await page.evaluate(() => {
        const boxes = () => JSON.stringify(['#verdict', '#verdictLabel', '.rate.big',
          '.submetrics', '#places', '#warn', '#detail', '.connbar', '.bottombar',
          '#viewWrap'].map((sel) => {
            const b = document.querySelector(sel).getBoundingClientRect();
            return [b.left, b.top, b.width, b.height].map((v) => Math.round(v * 10) / 10);
          }));
        const day = boxes();
        const dayBg = getComputedStyle(document.body).backgroundColor;
        document.documentElement.classList.add('night');
        const out = { same: boxes() === day, dayBg: dayBg,
                      nightBg: getComputedStyle(document.body).backgroundColor };
        document.documentElement.classList.remove('night');
        return out;
      });
      await page.close();
      await ctx.close();
    }
  }
  // The Trip Planner's stops between offers, where they are drawn. Measured
  // against the same panel a moment before they arrived, so "the bar, the
  // status row and the picture did not move" is a comparison and not a guess.
  const plannerPage = async (panel, view) => {
    const ctx = await browser.newContext({
      viewport: { width: panel[1], height: panel[2] }, deviceScaleFactor: 1,
    });
    const page = await ctx.newPage();
    await page.addInitScript((v) => {
      try { localStorage.setItem('uberscan.liveView', v); } catch (e) {}
      class FakeEventSource {
        constructor(url) { this.url = url; window.__es = this; }
        close() {}
        push(obj) { if (this.onmessage) this.onmessage({ data: JSON.stringify(obj) }); }
      }
      window.EventSource = FakeEventSource;
    }, view);
    await page.route('**/api/frame.*', (route) => {
      const v = /view=screen/.test(route.request().url()) ? 'screen' : 'scene';
      route.fulfill({ status: 200, contentType: 'image/jpeg',
                      body: Buffer.from(FRAMES[v], 'base64') });
    });
    await page.route('**/api/status*', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ scanner: { enabled: true, running: true, error: null },
                             status: { phase: 'scanning', message: '' },
                             last: null, lastAgeMs: null, heardAgeMs: 400,
                             offer: null, holding: null }) }));
    await page.goto(base + '/live.html', { waitUntil: 'domcontentloaded' }).catch(() => {});
    await page.waitForFunction(() => document.getElementById('view').naturalWidth > 2,
                               null, { timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(600);
    return { ctx: ctx, page: page };
  };
  const measurePlanner = (page, stops) => page.evaluate((stops) => {
    const box = (sel) => {
      const b = document.querySelector(sel).getBoundingClientRect();
      return [b.left, b.top, b.width, b.height].map((v) => Math.round(v * 10) / 10);
    };
    const v = document.getElementById('verdict').getBoundingClientRect();
    const s = document.getElementById('stops');
    const inCard = (r) => r.top >= v.top - 0.5 && r.bottom <= v.bottom + 0.5
      && r.left >= v.left - 0.5 && r.right <= v.right + 0.5;
    const clock = (m) => ((Math.floor(m / 60) % 12) || 12) + ':'
      + String(m % 60).padStart(2, '0');
    const lines = [].slice.call(s.children).map((d, i) => {
      const r = d.getBoundingClientRect();
      const cs = getComputedStyle(d);
      const lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.35;
      // The parts of a stop that may not be cut, wherever on the line the page
      // puts them: its kind, its time, and the first letter of its name, so
      // the name at least begins on the glass. The rest of the name and the
      // address are what the ellipsis takes. Asked of the STOP, not of the
      // line's punctuation: measured up to the first " · ", a line with the
      // name moved ahead of the time passed with "by 12:05" in the ellipsis.
      // Any other line — the note, "+ N more stops", the count — is held whole.
      const text = d.textContent;
      const st = /^▸ (Pickup|Dropoff)\b/.test(text) ? stops[i] : null;
      const need = [];
      const want = (part, len) => {
        const at = text.indexOf(part);
        if (at === -1) need.push([-1, part]);
        else need.push([at, at + (len === undefined ? part.length : len)]);
      };
      if (st) {
        want(st.kind === 'pickup' ? 'Pickup' : 'Dropoff');
        if (typeof st.expectedBy === 'number') want('by ' + clock(st.expectedBy));
        if (st.name) want(st.name, 1);
      } else {
        need.push([0, text.length]);
      }
      let cut = need.filter((n) => n[0] === -1).map((n) => 'missing ' + n[1]).join('');
      const n = d.firstChild;
      if (n) {
        const rg = document.createRange();
        need.filter((p) => p[0] !== -1).forEach((p) => {
          for (let k = p[0]; k < p[1]; k++) {
            rg.setStart(n, k);
            rg.setEnd(n, k + 1);
            const c = rg.getBoundingClientRect();
            if (!c.width && !c.height) continue;
            if (c.left < r.left - 0.5 || c.right > r.right + 0.5) cut += n.data[k];
          }
        });
      }
      return { text: text, rows: Math.round(r.height / lh), cut: cut,
               inCard: inCard(r),
               onGlass: r.top >= -0.5 && r.bottom <= window.innerHeight + 0.5 };
    });
    const d = document.documentElement;
    const w = document.getElementById('warn');
    const sr = s.getBoundingClientRect();
    return { shown: !s.hidden && sr.height > 0,
             lines: lines, fontPx: parseFloat(getComputedStyle(s).fontSize),
             // What the block costs the column: its height and the margin over it.
             cost: s.hidden ? 0 : sr.height + parseFloat(getComputedStyle(s).marginTop),
             // The notice: how much of it is on the glass, and how much it says.
             warn: { shown: !w.hidden && w.getBoundingClientRect().height > 0,
                     client: w.clientHeight, need: w.scrollHeight },
             labelIn: inCard(document.getElementById('verdictLabel').getBoundingClientRect()),
             layout: { verdict: box('#verdict'), bar: box('.bottombar'),
                       row: box('.connbar'), view: box('#viewWrap') },
             over: d.scrollWidth > d.clientWidth + 1 || d.scrollHeight > d.clientHeight + 1,
             phone: document.body.classList.contains('phoneview') };
  }, stops);
  const pushPlanner = async (page, stops, unfiled) => {
    await page.evaluate((a) => window.__es.push(
      { planner: { stops: a[0], unfiled: a[1], asked: true, ms: null, at: 1 } }),
      [stops, unfiled]);
    await page.waitForTimeout(150);
  };
  for (const panel of PLANNER_PANELS) {
    for (const view of ['screen', 'scene']) {
      const { ctx, page } = await plannerPage(panel, view);
      await page.evaluate(() => {
        window.__es.push({ alive: true, at: 1 });
        window.__es.push({ ready: false, state: 'empty', track: null, places: [], text: '' });
      });
      await page.waitForTimeout(150);
      const before = await measurePlanner(page, PLANNER_STOPS);
      await pushPlanner(page, PLANNER_STOPS, PLANNER.unfiled);
      const after = await measurePlanner(page, PLANNER_STOPS);
      // ...and the line under them in each of the scanner's words.
      const notes = {};
      for (const why of Object.keys(PLANNER.notes)) {
        await pushPlanner(page, PLANNER.notes[why], why);
        const m = await measurePlanner(page, PLANNER.notes[why]);
        notes[why] = m.lines[m.lines.length - 1] || null;
      }
      out[panel[0] + ' ' + view + ' planner'] = { before: before, after: after, notes: notes };
      await page.close();
      await ctx.close();
    }
  }
  // ...and with the notice up, which is the other thing the card holds between
  // offers and the item that gives way. The stops may not take its room.
  for (const panel of PLANNER_PANELS) {
    for (const view of ['screen', 'scene']) {
      const { ctx, page } = await plannerPage(panel, view);
      await page.evaluate((notice) => {
        window.__es.push(Object.assign({ alive: true, at: 1, tooDim: false },
                                       notice));
        window.__es.push({ ready: false, state: 'empty', track: null, places: [], text: '' });
      }, PLANNER.notice);
      await page.waitForTimeout(150);
      const before = await measurePlanner(page, PLANNER_STOPS);
      await pushPlanner(page, PLANNER_STOPS, PLANNER.unfiled);
      out[panel[0] + ' ' + view + ' planner notice'] = {
        before: before, after: await measurePlanner(page, PLANNER_STOPS) };
      await page.close();
      await ctx.close();
    }
  }
  // ...and under the camera's word, whose line is the notice while it holds.
  for (const panel of PLANNER_PANELS) {
    for (const view of ['screen', 'scene']) {
      for (const word of PLANNER.blind) {
        const { ctx, page } = await plannerPage(panel, view);
        await page.evaluate((w) => {
          window.__es.push({ alive: true, at: 1, tooBright: false, tooDim: false,
                             notSaving: null, blind: w });
          window.__es.push({ ready: false, state: 'empty', track: null, places: [], text: '' });
        }, word);
        await page.waitForTimeout(150);
        const before = await measurePlanner(page, PLANNER_STOPS);
        await pushPlanner(page, PLANNER_STOPS, PLANNER.unfiled);
        out[panel[0] + ' ' + view + ' planner blind ' + word] = {
          before: before, after: await measurePlanner(page, PLANNER_STOPS),
          label: await page.evaluate(() =>
            document.getElementById('verdictLabel').textContent.trim()) };
        await page.close();
        await ctx.close();
      }
    }
  }
  // The order in the car, on the card: between offers, then with an offer and
  // a pair up, then the Took button once that offer's card has gone, on the
  // page's own clock moved on 59 minutes. See HELD.
  const measureHeld = (page) => page.evaluate(() => {
    const vr = document.getElementById('verdict').getBoundingClientRect();
    // Inside the card's 2px border.
    const card = { left: vr.left + 2, right: vr.right - 2, top: vr.top + 2,
                   bottom: vr.bottom - 2 };
    const glass = { left: 0, top: 0, right: window.innerWidth, bottom: window.innerHeight };
    const shown = (el) => {
      if (!el || el.hidden) return false;
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && getComputedStyle(el).display !== 'none';
    };
    const text = (el) => (el ? (el.textContent || '').replace(/\s+/g, ' ').trim() : '');
    // The glyphs of `el` that land outside every one of `boxes`.
    const outside = (el, boxes) => {
      if (!el) return '';
      const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      const rg = document.createRange();
      let n, cut = '';
      while ((n = walk.nextNode())) {
        for (let i = 0; i < n.length; i++) {
          rg.setStart(n, i); rg.setEnd(n, i + 1);
          const c = rg.getBoundingClientRect();
          if (!c.width && !c.height) continue;
          if (boxes.some((b) => c.left < b.left - 0.5 || c.right > b.right + 0.5
                                || c.top < b.top - 0.5 || c.bottom > b.bottom + 0.5)) {
            cut += n.data[i];
          }
        }
      }
      return cut;
    };
    const rows = (el) => {
      const cs = getComputedStyle(el);
      const lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.2;
      return Math.round(el.getBoundingClientRect().height / lh);
    };
    const px = (el) => (el ? parseFloat(getComputedStyle(el).fontSize) : null);
    const next = document.getElementById('heldNext');
    const line = document.getElementById('heldLine');
    const detail = document.getElementById('detail');
    const det = detail.querySelector('.held');
    const stack = document.getElementById('stack');
    const range = stack.querySelector('.range');
    const sub = document.querySelector('.submetrics');
    const part = (box, c) => box && box.querySelector('.' + c);
    const d = document.documentElement;
    // Every drawn child of the card inside it: what the card centres and
    // cannot hold goes out of both ends, the word above the verdict first.
    const spill = [].slice.call(document.getElementById('verdict').children)
      .filter(shown).filter((e) => {
        const r = e.getBoundingClientRect();
        return r.top < card.top - 0.5 || r.bottom > card.bottom + 0.5;
      }).map((e) => e.id || e.className);
    return {
      phone: document.body.classList.contains('phoneview'),
      label: shown(document.getElementById('verdictLabel'))
        ? text(document.getElementById('verdictLabel')) : null,
      next: shown(next) ? {
        when: text(next.firstChild), whenCut: outside(next.firstChild, [card, glass]),
        whenRows: rows(next.firstChild), whenPx: px(next.firstChild),
        where: text(next.lastChild), whereRows: rows(next.lastChild),
        wherePx: px(next.lastChild),
        // The name's first word, which may not be cut.
        whereFirst: (() => {
          const n = next.lastChild.firstChild;
          if (!n) return null;
          const end = n.data.indexOf(' ') === -1 ? n.length : n.data.indexOf(' ');
          const rg = document.createRange();
          rg.setStart(n, 0); rg.setEnd(n, end);
          const r = rg.getBoundingClientRect();
          return r.left >= card.left - 0.5 && r.right <= card.right + 0.5
            && r.top >= card.top - 0.5 && r.bottom <= card.bottom + 0.5;
        })(),
      } : null,
      line: shown(line) ? {
        text: [].slice.call(line.children).filter(shown).map(text).join(' '),
        rows: rows(line), px: px(line),
        // Each part on one row: the pay and the state may go onto a row each
        // between offers, where the card has the height and not the width.
        partRows: [].slice.call(line.children).filter(shown).map(rows),
        cut: outside(part(line, 'pay'), [line.getBoundingClientRect(), card, glass])
           + outside(part(line, 'gps'), [line.getBoundingClientRect(), card, glass]),
      } : null,
      det: shown(det) ? {
        text: [].slice.call(det.children).filter(shown).map(text).join(' '),
        rows: rows(detail), px: px(det),
        // Across the line's own box only: on the 3.5" hat it is 10px with a
        // line-height of 1, and every glyph's box is taller than that.
        cut: [part(det, 'pay'), part(det, 'gps'), detail.querySelector('.age')]
          .map((e) => outside(e, [{ left: detail.getBoundingClientRect().left,
                                    right: detail.getBoundingClientRect().right,
                                    top: -Infinity, bottom: Infinity }, glass])).join(''),
      } : null,
      // The same-store note (live.html sameNote) where it is drawn: at the
      // head of the address line, or on the 3.5" hat on the pair line's
      // first row — never both (`both`). Its words, which line it is on,
      // and what of it is outside that line, the card or the glass.
      same: (() => {
        const els = [document.querySelector('#places .same'), stack.querySelector('.same')];
        const on = els.filter(shown);
        if (!on.length) return null;
        const line = on[0] === els[0] ? document.getElementById('places') : stack;
        return { text: text(on[0]), on: line.id, both: on.length > 1,
                 cut: outside(on[0], [line.getBoundingClientRect(), card, glass]) };
      })(),
      range: shown(stack) && range ? {
        text: text(range), px: px(range),
        cut: outside(range, [stack.getBoundingClientRect(), card, glass]),
        above: shown(sub) && range.getBoundingClientRect().bottom
                              <= sub.getBoundingClientRect().top + 0.5,
        rowIn: (() => {
          const r = stack.getBoundingClientRect();
          return r.top >= card.top - 0.5 && r.bottom <= card.bottom + 0.5;
        })(),
      } : null,
      stopsCut: [].slice.call(document.getElementById('stops').children).filter((e) => {
        const r = e.getBoundingClientRect();
        return r.top < card.top - 0.5 || r.bottom > card.bottom + 0.5;
      }).map(text),
      spill: spill,
      over: d.scrollWidth > d.clientWidth + 1 || d.scrollHeight > d.clientHeight + 1,
    };
  });
  const measureTook = (page) => page.evaluate(() => {
    const t = document.getElementById('took');
    const bar = document.querySelector('.bottombar');
    const r = t.getBoundingClientRect();
    const walk = document.createTreeWalker(t, NodeFilter.SHOW_TEXT);
    const rg = document.createRange();
    let n, cut = '';
    while ((n = walk.nextNode())) {
      for (let i = 0; i < n.length; i++) {
        rg.setStart(n, i); rg.setEnd(n, i + 1);
        const c = rg.getBoundingClientRect();
        if (!c.width && !c.height) continue;
        if (c.left < r.left - 0.5 || c.right > r.right + 0.5
            || c.top < r.top - 0.5 || c.bottom > r.bottom + 0.5) cut += n.data[i];
      }
    }
    const kids = [].slice.call(bar.children).filter((el) => {
      const b = el.getBoundingClientRect();
      return b.width > 0 && b.height > 0;
    });
    const d = document.documentElement;
    const ago = t.querySelector('.ago');
    // ...and of the age alone, every glyph of it inside the button's border
    // rather than its outer edge: three lines spilling a few pixels into the
    // padding at each end end with the top of "Took" and the foot of the age
    // drawn over the border line itself, which the outer edge lets past.
    let agoCut = null;
    const cs = getComputedStyle(t);
    const inner = { left: r.left + parseFloat(cs.borderLeftWidth),
                    right: r.right - parseFloat(cs.borderRightWidth),
                    top: r.top + parseFloat(cs.borderTopWidth),
                    bottom: r.bottom - parseFloat(cs.borderBottomWidth) };
    // ...and every line of the button, label and all, between its top and
    // bottom borders: the lines the age shares the bar's height with are
    // the ones it pushes out. (Across, the label is the bar's own question —
    // "$112.45?" is wider than the hat's button — and 'cut' above asks it.)
    let rowsOut = '';
    const tw = document.createTreeWalker(t, NodeFilter.SHOW_TEXT);
    while ((n = tw.nextNode())) {
      for (let i = 0; i < n.length; i++) {
        rg.setStart(n, i); rg.setEnd(n, i + 1);
        const c = rg.getBoundingClientRect();
        if (!c.width && !c.height) continue;
        if (c.top < inner.top - 0.5 || c.bottom > inner.bottom + 0.5) rowsOut += n.data[i];
      }
    }
    if (ago) {
      agoCut = '';
      const aw = document.createTreeWalker(ago, NodeFilter.SHOW_TEXT);
      while ((n = aw.nextNode())) {
        for (let i = 0; i < n.length; i++) {
          rg.setStart(n, i); rg.setEnd(n, i + 1);
          const c = rg.getBoundingClientRect();
          if (!c.width && !c.height) continue;
          if (c.left < inner.left - 0.5 || c.right > inner.right + 0.5
              || c.top < inner.top - 0.5 || c.bottom > inner.bottom + 0.5) agoCut += n.data[i];
        }
      }
    }
    return { text: (t.hidden ? '' : (t.textContent || '')).replace(/\s+/g, ' ').trim(),
             cut: cut, agoCut: agoCut, rowsOut: rowsOut,
             agoPx: ago ? parseFloat(getComputedStyle(ago).fontSize) : null,
             // To a tenth: the bar is 55.4px, and a row grown by a fraction
             // of a pixel still moves every control under the finger.
             barH: Math.round(bar.getBoundingClientRect().height * 10) / 10,
             count: kids.length, width: Math.round(bar.getBoundingClientRect().width),
             over: d.scrollWidth > d.clientWidth + 1 || d.scrollHeight > d.clientHeight + 1 };
  });
  for (const panel of PLANNER_PANELS) {
    for (const view of ['screen', 'scene']) {
      const ctx = await browser.newContext({
        viewport: { width: panel[1], height: panel[2] }, deviceScaleFactor: 1,
      });
      const page = await ctx.newPage();
      await page.clock.install({ time: Date.now() });
      await page.addInitScript((v) => {
        try { localStorage.setItem('uberscan.liveView', v); } catch (e) {}
        class FakeEventSource {
          constructor(url) { this.url = url; window.__es = this; }
          close() {}
          push(obj) { if (this.onmessage) this.onmessage({ data: JSON.stringify(obj) }); }
        }
        window.EventSource = FakeEventSource;
      }, view);
      await page.route('**/api/frame.*', (route) => {
        const v = /view=screen/.test(route.request().url()) ? 'screen' : 'scene';
        route.fulfill({ status: 200, contentType: 'image/jpeg',
                        body: Buffer.from(FRAMES[v], 'base64') });
      });
      await page.route('**/api/status*', (route) => route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ scanner: { enabled: true, running: true, error: null },
                               status: { phase: 'scanning', message: '' },
                               last: null, lastAgeMs: null, heardAgeMs: 400,
                               offer: null, holding: null }) }));
      await page.goto(base + '/live.html', { waitUntil: 'domcontentloaded' }).catch(() => {});
      await page.waitForFunction(() => document.getElementById('view').naturalWidth > 2,
                                 null, { timeout: 10000 }).catch(() => {});
      await page.clock.runFor(600);
      const push = (m) => page.evaluate((x) => window.__es.push(x), m);
      await push({ alive: true, at: 1 });
      // The bar before any offer is on record: no Took on it at all.
      await push({ ready: false, state: 'empty', track: null, places: [], text: '' });
      await page.clock.runFor(1100);
      const noTook = await measureTook(page);
      await push({ offer: HELD.took, at: 1 });
      await push({ holding: HELD.hold });
      await push({ planner: { stops: HELD.stops, unfiled: 'list', asked: true, ms: null, at: 1 } });
      await push({ ready: false, state: 'empty', track: null, places: [], text: '' });
      // Past the page's one-second tick, which renders again: the stops fold
      // to the card as it is laid out at that render, and a picture that
      // arrives after it moves the card under them.
      await page.clock.runFor(1100);
      const between = await measureHeld(page);
      await page.clock.fastForward(59 * 60000);
      await page.clock.runFor(1100);
      const took = await measureTook(page);
      await push(Object.assign({}, HELD.offer, { holding: HELD.hold }));
      await page.clock.runFor(1100);
      const offer = await measureHeld(page);
      // ...the Took button with its card up, which says no age,
      const tookUp = await measureTook(page);
      // ...after a press the journal refused, which says "not saved" — the
      // reply comes back over the routed fetch on the real clock, so it is
      // waited for in this script's time,
      await page.route('**/api/offers/mark', (route) => route.fulfill({
        status: 500, contentType: 'application/json', body: '{"ok":false}' }));
      await page.evaluate(() => document.getElementById('took').click());
      for (let i = 0; i < 40; i++) {
        if (await page.evaluate(() => /not saved/.test(document.getElementById('took').textContent))) break;
        await new Promise((r) => setTimeout(r, 50));
      }
      await page.clock.runFor(300);
      const notSaved = await measureTook(page);
      // ...and for the order already in the car, back on the phone: "in car".
      await push({ offer: Object.assign({}, HELD.took, { heldCard: true }), at: 1 });
      await page.clock.runFor(1100);
      const inCar = await measureTook(page);
      out[panel[0] + ' ' + view + ' held'] = { between: between, offer: offer, took: took,
                                               noTook: noTook, tookUp: tookUp,
                                               notSaved: notSaved, inCar: inCar };
      await page.close();
      await ctx.close();
    }
  }
  // Two orders in the car (carrying two on): the chooser over the verdict
  // pane, with two rows and with the screened card's as a third, and the two
  // compact order lines between offers; and the pair line's "vs ① only". On
  // the three panels and in both pictures. See CARRY on the Python side.
  const measureCarry = (page) => page.evaluate(() => {
    const shown = (el) => {
      if (!el || el.hidden) return false;
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && getComputedStyle(el).display !== 'none';
    };
    const text = (el) => (el ? (el.textContent || '').replace(/\s+/g, ' ').trim() : '');
    const box = (el) => {
      const r = el.getBoundingClientRect();
      return { left: r.left, right: r.right, top: r.top, bottom: r.bottom };
    };
    // Glyphs of `el` outside every one of `boxes`.
    const outside = (el, boxes) => {
      if (!el) return '';
      const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      const rg = document.createRange();
      let n, cut = '';
      while ((n = walk.nextNode())) {
        for (let i = 0; i < n.length; i++) {
          rg.setStart(n, i); rg.setEnd(n, i + 1);
          const c = rg.getBoundingClientRect();
          if (!c.width && !c.height) continue;
          if (boxes.some((b) => c.left < b.left - 0.5 || c.right > b.right + 0.5
                                || c.top < b.top - 0.5 || c.bottom > b.bottom + 0.5)) {
            cut += n.data[i];
          }
        }
      }
      return cut;
    };
    const glass = { left: 0, top: 0, right: window.innerWidth, bottom: window.innerHeight };
    const ch = document.getElementById('chooser');
    const bar = document.querySelector('.bottombar');
    const barKids = [].slice.call(bar.children).filter(shown);
    const vr = document.getElementById('verdict').getBoundingClientRect();
    const card = { left: vr.left + 2, right: vr.right - 2, top: vr.top + 2, bottom: vr.bottom - 2 };
    // The verdict pane: the card's own column, from the top of the glass to
    // the status row above the bar.
    const live = document.querySelector('.live');
    const conn = document.querySelector('.connbar').getBoundingClientRect();
    const lines = ['heldLine', 'heldLine2', 'whose'].map((id) => document.getElementById(id));
    const vs = document.querySelector('#stack .vs');
    const d = document.documentElement;
    return {
      chooser: shown(ch) ? {
        rows: [].slice.call(ch.querySelectorAll('button')).map((b) => ({
          text: [].slice.call(b.children).map(text).join(' '),
          h: Math.round(b.getBoundingClientRect().height),
          // What the row stands for whole inside it — "① $9.48", "This card
          // $12.50", "Neither" — where the street beside it may give way.
          cut: outside(b.querySelector('.who'), [box(b), glass]) !== '',
        })),
        ask: text(ch.querySelector('.ask')),
        // Over the verdict's column, above the status row and the bar.
        inPane: (() => {
          const r = ch.getBoundingClientRect();
          const col = live && shown(live) ? live.getBoundingClientRect() : vr;
          return r.left >= col.left - 1 && r.right <= col.right + 1 && r.top >= -0.5
            && r.bottom <= Math.min(conn.top, bar.getBoundingClientRect().top) + 0.5;
        })(),
      } : null,
      bar: { count: barKids.length, box: box(bar),
             drop: text(document.getElementById('drop')) },
      lines: lines.map((el) => shown(el) ? {
        text: [].slice.call(el.children).length
          ? [].slice.call(el.children).filter(shown).map(text).join(' ') : text(el),
        cut: outside(el, [box(el), card, glass]),
        rows: Math.round(el.getBoundingClientRect().height
                         / (parseFloat(getComputedStyle(el).lineHeight)
                            || parseFloat(getComputedStyle(el).fontSize) * 1.2)),
      } : null),
      vs: shown(vs) ? { text: text(vs), cut: outside(vs, [box(document.getElementById('stack')),
                                                           card, glass]) } : null,
      // The pair line with two in the car, against both: its range and
      // "with ① + ②" (`.both`), each with what of it is cut — outside its
      // own box, the line's, the card or the glass.
      pair: (() => {
        const st = document.getElementById('stack');
        if (!shown(st)) return null;
        const rg = st.querySelector('.range'), bo = st.querySelector('.both');
        const ot = st.querySelector('.ontime');
        const sm = [document.querySelector('#places .same'), st.querySelector('.same')]
          .filter(shown)[0] || null;
        const wt = document.querySelector('#places .wait');
        const cutOf = (el) => outside(el, [box(el), box(el === sm || el === wt
                                                        ? el.closest('#places, #stack') : st),
                                           card, glass]);
        return { range: text(rg), rangeCut: cutOf(rg),
                 both: shown(bo) ? text(bo) : null, bothCut: shown(bo) ? cutOf(bo) : null,
                 // ...and "same store as ②" at the head of the address line
                 // (live.html sameNote), the same.
                 same: shown(sm) ? text(sm) : null, sameCut: shown(sm) ? cutOf(sm) : null,
                 // ...and the store's measured wait after it (waitNote), the
                 // same, with whether the address line is up to carry it.
                 wait: shown(wt) ? text(wt) : null, waitCut: shown(wt) ? cutOf(wt) : null,
                 placesUp: shown(document.getElementById('places')),
                 // ...and the on-time hint (live.html onTimeSaid), the same.
                 ontime: shown(ot) ? text(ot) : null, ontimeCut: shown(ot) ? cutOf(ot) : null };
      })(),
      over: d.scrollWidth > d.clientWidth + 1 || d.scrollHeight > d.clientHeight + 1,
    };
  });
  // The panel the two-order measurements are made on: live.html over a fake
  // event stream, a fake status and the two pictures. Shared by the carry
  // block and the foot block below it.
  const carryPage = async (panel, view) => {
    const ctx = await browser.newContext({
      viewport: { width: panel[1], height: panel[2] }, deviceScaleFactor: 1,
    });
    const page = await ctx.newPage();
    await page.clock.install({ time: Date.now() });
    await page.addInitScript((v) => {
      try { localStorage.setItem('uberscan.liveView', v); } catch (e) {}
      class FakeEventSource {
        constructor(url) { this.url = url; window.__es = this; }
        close() {}
        push(obj) { if (this.onmessage) this.onmessage({ data: JSON.stringify(obj) }); }
      }
      window.EventSource = FakeEventSource;
    }, view);
    await page.route('**/api/frame.*', (route) => {
      const v = /view=screen/.test(route.request().url()) ? 'screen' : 'scene';
      route.fulfill({ status: 200, contentType: 'image/jpeg',
                      body: Buffer.from(FRAMES[v], 'base64') });
    });
    await page.route('**/api/status*', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ scanner: { enabled: true, running: true, error: null },
                             status: { phase: 'scanning', message: '' },
                             last: null, lastAgeMs: null, heardAgeMs: 400,
                             offer: null, holding: null }) }));
    // A NucBox set, as on the owner's rig, so a pair's card carries the
    // answer on the card (live.html showWay) and is measured with it; its
    // questions are not answered, since nothing here asks one but a card
    // with an offer line.
    await page.route('**/api/nbx', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ search: true, route: true, streets: false }) }));
    await page.goto(base + '/live.html', { waitUntil: 'domcontentloaded' }).catch(() => {});
    await page.waitForFunction(() => document.getElementById('view').naturalWidth > 2,
                               null, { timeout: 10000 }).catch(() => {});
    await page.clock.runFor(600);
    const push = (m) => page.evaluate((x) => window.__es.push(x), m);
    return { ctx: ctx, page: page, push: push };
  };
  // The widest each line is asked to hold: three-figure pays, the longest
  // street a real card printed, and the longest of the GPS drop's words.
  const CARRY_A = { n: 1, pay: 112.45, minutes: 55, holdId: 'l-a@1',
                    dropoff: '4821 Kestrel Dr S, Powder Springs, GA 30127', card: null,
                    endPinned: false, arrived: false, endWhy: 'too many answers', app: 'uber' };
  const CARRY_B = { n: 2, pay: 128.08, minutes: 60, holdId: 'l-b@2',
                    dropoff: '1985 Cobb Pkwy NW, Kennesaw, GA 30152', card: null,
                    endPinned: false, arrived: false, endWhy: 'too many answers', app: 'uber' };
  for (const panel of PLANNER_PANELS) {
    for (const view of ['screen', 'scene']) {
      const { ctx, page, push } = await carryPage(panel, view);
      const A = CARRY_A, B = CARRY_B;
      await push({ alive: true, at: 1 });
      await push({ holding: A, orders: [A, B], unowned: 2 });
      await push({ ready: false, state: 'empty', track: null, places: [], text: '' });
      await page.clock.runFor(1100);
      const before = await measureCarry(page);
      const rows = [{ pick: 'l-a@1', n: 1, pay: 112.45, end: A.dropoff },
                    { pick: 'l-b@2', n: 2, pay: 128.08, end: null }];
      await push({ chooser: { id: 'c1', kind: 'scan', line: A.dropoff, rows: rows, card: null,
                              closesInMs: 10000 } });
      await page.clock.runFor(300);
      const two = await measureCarry(page);
      await push({ chooser: { id: 'c2', kind: 'scan', line: A.dropoff, rows: rows,
                              card: { pick: 'card', pay: 118.04 }, closesInMs: 10000 } });
      await page.clock.runFor(300);
      const three = await measureCarry(page);
      // ...and with ONE order in the car and another card being screened
      // (server.js pressBetween, carrying two off as well as on): ①, the
      // card, and Neither.
      await push({ holding: A, orders: [A], unowned: 0 });
      await push({ chooser: { id: 'c3', kind: 'scan', line: A.dropoff, rows: rows.slice(0, 1),
                              card: { pick: 'card', pay: 118.04 }, closesInMs: 10000 } });
      await page.clock.runFor(300);
      const one = await measureCarry(page);
      await page.clock.runFor(10500);
      // ...and the pair line with both in the car, under an offer: against
      // both (Advice.stackMany: `heldCount`, and no route link, which end is
      // last being Map view's question), at the most the row holds.
      // ...and the store's measured waits at their widest beside the note
      // (server.js storeWaitFor): two figures of minutes, ten visits.
      await push(Object.assign({}, HELD.offer, { holding: A, orders: [A, B], unowned: 0,
        storeWait: { n: 10, avgMin: 12 },
        stack: Object.assign({}, HELD.offer.stack, { heldCount: 2, leftEach: [55, 60],
                                                     maxMinutes: 137, route: null,
                                                     sameStore: 'l-b@2', sameStoreN: 2 }) }));
      await page.clock.runFor(1100);
      const offer = await measureCarry(page);
      // ...and with carrying two off and two read back at boot: ① alone, and
      // "vs ① only" beside the chip.
      await push(Object.assign({}, HELD.offer, { holding: A, orders: [A, B], unowned: 0,
        stack: Object.assign({}, HELD.offer.stack, { vsFirst: true }) }));
      await page.clock.runFor(1100);
      const offerFirst = await measureCarry(page);
      out[panel[0] + ' ' + view + ' carry'] = { before: before, two: two, three: three,
                                               one: one, offer: offer,
                                               offerFirst: offerFirst };
      await page.close();
      await ctx.close();
    }
  }
  // The foot of the verdict pane with two things over it at once: the Undo a
  // Took that ADDED an order offers for five seconds, and the "…" sheet the
  // status row opens for ten. They were drawn one on top of the other. Driven
  // the way the driver gets there: a card up with ① in the car, ✓ Took
  // pressed and the server's reply naming the order it added (offerUndo),
  // then "…" pressed inside the five seconds. Each is measured whole (no
  // glyph outside its own box, the verdict pane above the status row, or the
  // glass), the two boxes apart, and each the element its own centre — and
  // the centre of each of the sheet's lines — hits. On the three panels in
  // both pictures, and on the phone, where both are fixed to the glass.
  const FOOT_MEASURE = () => {
    const shown = (el) => !!el && !el.hidden && getComputedStyle(el).display !== 'none'
      && el.getBoundingClientRect().height > 0;
    const rect = (el) => {
      const r = el.getBoundingClientRect();
      return { left: r.left, right: r.right, top: r.top, bottom: r.bottom };
    };
    const conn = document.querySelector('.connbar').getBoundingClientRect();
    const bar = document.querySelector('.bottombar').getBoundingClientRect();
    const live = document.querySelector('.live').getBoundingClientRect();
    // The pane: the verdict's column, from the top of the glass down to the
    // status row (or the bar, if that is higher).
    const pane = { left: Math.max(0, live.left), right: Math.min(window.innerWidth, live.right),
                   top: 0, bottom: Math.min(conn.top, bar.top) };
    const cut = (el) => {
      const own = rect(el);
      const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      const rg = document.createRange();
      let n, out = '';
      while ((n = walk.nextNode())) {
        for (let i = 0; i < n.length; i++) {
          rg.setStart(n, i); rg.setEnd(n, i + 1);
          const c = rg.getBoundingClientRect();
          if (!c.width && !c.height) continue;
          if ([own, pane].some((b) => c.left < b.left - 0.5 || c.right > b.right + 0.5
                                    || c.top < b.top - 0.5 || c.bottom > b.bottom + 0.5)) {
            out += n.data[i];
          }
        }
      }
      return out;
    };
    const hits = (el, r) => {
      const h = document.elementFromPoint((r.left + r.right) / 2, (r.top + r.bottom) / 2);
      return !!h && (h === el || el.contains(h));
    };
    const one = (el) => shown(el) ? {
      text: el.textContent.replace(/\s+/g, ' ').trim(), cut: cut(el), box: rect(el),
      hit: hits(el, rect(el)),
    } : null;
    const u = document.getElementById('undo'), s = document.getElementById('moreSheet');
    const undo = one(u), sheet = one(s);
    if (sheet) sheet.lines = [].slice.call(s.children).map((c) => hits(s, rect(c)));
    const apart = !!(undo && sheet) && (undo.box.bottom <= sheet.box.top + 0.5
                                         || sheet.box.bottom <= undo.box.top + 0.5);
    const d = document.documentElement;
    return { undo: undo, sheet: sheet, apart: apart,
             over: d.scrollWidth > d.clientWidth + 1 || d.scrollHeight > d.clientHeight + 1 };
  };
  for (const panel of PLANNER_PANELS.concat([['390x844', 390, 844]])) {
    for (const view of (panel[1] > panel[2] ? ['screen', 'scene'] : ['screen'])) {
      const { ctx, page, push } = await carryPage(panel, view);
      // A status row with something for the sheet to say beside the
      // connection: the scanner's note that it is not saving.
      await push({ alive: true, at: 1, notSaving: 'Offers are NOT being saved: disk full',
                   tooBright: false });
      await push(Object.assign({}, HELD.offer, {
        offer: { id: 'o-layout-foot', pay: 18.04, minutes: 22.0 },
        holding: CARRY_A, orders: [CARRY_A], unowned: 0 }));
      await page.clock.runFor(1100);
      await page.route('**/api/offers/mark', (route) => route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ ok: true, holding: true, held: CARRY_A,
                               orders: [CARRY_A, CARRY_B],
                               added: { id: 'o-layout-foot', pay: 128.08,
                                        undoForMs: 5000 } }) }));
      await page.evaluate(() => document.getElementById('took').click());
      // The reply comes back over the routed fetch on the real clock, not the
      // page's installed one, so it is waited for — in this script's time —
      // until the Undo it brings is up (two seconds at most).
      for (let i = 0; i < 40; i++) {
        if (await page.evaluate(() => !document.getElementById('undo').hidden)) break;
        await new Promise((r) => setTimeout(r, 50));
      }
      await page.clock.runFor(300);
      const alone = await page.evaluate(FOOT_MEASURE);
      await page.click('#more', { timeout: 5000 }).catch(() => {});
      await page.clock.runFor(200);
      const both = await page.evaluate(FOOT_MEASURE);
      out[panel[0] + ' ' + view + ' foot'] = { alone: alone, both: both };
      await page.close();
      await ctx.close();
    }
  }
  // The driving form (live.html, .live.driving): every form the card side
  // takes while gps.py says the car is being driven, against the same form
  // parked. Measured part by part — the verdict word, the rate, the pay,
  // the pair line's range, the order in the car on whichever line carries
  // it, and the first notice — for its type size and for every glyph of it
  // inside the card and on the glass; the line under the card inside its
  // own row; the card's children inside the card; and the bar, the status
  // row and the picture's column where the parked form left them. See
  // DRIVE_FORMS on the Python side.
  const DRIVE_MEASURE = () => {
    const shown = (el) => {
      if (!el || el.hidden) return false;
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && getComputedStyle(el).display !== 'none';
    };
    const vr = document.getElementById('verdict').getBoundingClientRect();
    const card = { left: vr.left + 2, right: vr.right - 2, top: vr.top + 2, bottom: vr.bottom - 2 };
    const glass = { left: 0, top: 0, right: window.innerWidth, bottom: window.innerHeight };
    const detail = document.getElementById('detail');
    const dr = detail.getBoundingClientRect();
    const row = { left: dr.left, right: dr.right, top: dr.top - 1, bottom: dr.bottom + 1 };
    const outside = (el, boxes) => {
      const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      const rg = document.createRange();
      let n, cut = '';
      while ((n = walk.nextNode())) {
        if (!shown(n.parentElement)) continue;
        for (let i = 0; i < n.length; i++) {
          rg.setStart(n, i); rg.setEnd(n, i + 1);
          const c = rg.getBoundingClientRect();
          if (!c.width && !c.height) continue;
          if (boxes.some((b) => c.left < b.left - 0.5 || c.right > b.right + 0.5
                                || c.top < b.top - 0.5 || c.bottom > b.bottom + 0.5)) {
            cut += n.data[i];
          }
        }
      }
      return cut;
    };
    // Each part: drawn or not, its type size, and what of it is cut. The
    // line under the card is held to its own row, the rest to the card.
    const part = (sel, inDetail) => {
      const el = document.querySelector(sel);
      if (!shown(el)) return null;
      // The size of the words: a line of parts is measured at its first
      // drawn part, which is the pay on the in-car line.
      const first = el.children.length ? [].slice.call(el.children).filter(shown)[0] || el : el;
      return { px: parseFloat(getComputedStyle(first).fontSize),
               text: (el.textContent || '').replace(/\s+/g, ' ').trim(),
               cut: outside(el, inDetail ? [row, glass] : [card, glass]) };
    };
    const box = (sel) => {
      const r = document.querySelector(sel).getBoundingClientRect();
      return [r.left, r.top, r.width, r.height].map((v) => Math.round(v * 10) / 10);
    };
    const d = document.documentElement;
    const lh = parseFloat(getComputedStyle(detail).lineHeight)
      || parseFloat(getComputedStyle(detail).fontSize) * 1.2;
    // The two ends: each one's words, whether it is whole on its line
    // (nothing ellipsised: an inline end has no box of its own to overflow,
    // so parked it is the line that is asked), its box inside the card, and
    // the rows they take.
    const pl = document.getElementById('places');
    const ends = [].slice.call(document.querySelectorAll('#places .end')).filter(shown);
    const inside = (r) => r.left >= card.left - 0.5 && r.right <= card.right + 0.5
      && r.top >= card.top - 0.5 && r.bottom <= card.bottom + 0.5
      && r.right <= glass.right + 0.5 && r.bottom <= glass.bottom + 0.5;
    const places = shown(pl) ? {
      text: pl.textContent,
      rows: new Set(ends.map((e) => Math.round(e.getBoundingClientRect().top))).size,
      ends: ends.map((e) => {
        const box = getComputedStyle(e).display === 'inline' ? pl : e;
        const cs = getComputedStyle(box);
        return { text: e.textContent, whole: box.scrollWidth <= box.clientWidth + 1,
                 // ...and, cut, cut with an ellipsis inside its own box.
                 ellipsis: cs.textOverflow === 'ellipsis' && cs.overflowX === 'hidden',
                 inCard: inside(e.getBoundingClientRect()),
                 px: parseFloat(getComputedStyle(e).fontSize) };
      }),
    } : null;
    // The notice's box on the glass, against one row of its chips: on the
    // hat it scrolls, and its first row is what has to be in sight.
    const warn = document.getElementById('warn');
    const chip0 = warn.querySelector('.chip');
    const warnRow = shown(warn) && chip0 ? {
      h: Math.round(warn.getBoundingClientRect().height * 10) / 10,
      line: Math.round((parseFloat(getComputedStyle(chip0).lineHeight)
                        || parseFloat(getComputedStyle(chip0).fontSize) * 1.2) * 10) / 10,
    } : null;
    return {
      driving: document.querySelector('.live').classList.contains('driving'),
      moving: document.querySelector('.live').classList.contains('moving'),
      places: places, warnRow: warnRow,
      parts: {
        label: part('#verdictLabel'), rate: part('#perHour'), pay: part('#vPay'),
        min: part('#vMin'), mile: part('#vMile'), perMile: part('#vPerMile'),
        working: part('#working'), stops: part('#stops'),
        range: part('#stack .range'), both: part('#stack .both'), ends: part('#stack .ends'),
        same: part('#places .same') || part('#stack .same'),
        way: part('#way .call'),
        next: part('#heldNext .where'), nextWhen: part('#heldNext .when'),
        line: part('#heldLine'), line2: part('#heldLine2'), whose: part('#whose'),
        held: part('#detail .held', true), age: part('#detail .age', true),
        chip: part('#warn .chip'),
      },
      // What the driving form puts out of sight, by name, drawn or not.
      detail: ['#vMin', '#vMile', '#vPerMile', '#working', '#places', '#stops',
               '#detail .diag', '#stack .maplink'].filter((s) => shown(document.querySelector(s))),
      chips: [].slice.call(document.querySelectorAll('#warn .chip')).filter(shown)
        .map((c) => c.textContent),
      detailRows: Math.round(dr.height / lh),
      spill: [].slice.call(document.getElementById('verdict').children).filter(shown)
        .filter((e) => {
          const r = e.getBoundingClientRect();
          return r.top < card.top - 0.5 || r.bottom > card.bottom + 0.5;
        }).map((e) => e.id || e.className),
      layout: { bar: box('.bottombar'), row: box('.connbar'), view: box('#viewWrap') },
      over: d.scrollWidth > d.clientWidth + 1 || d.scrollHeight > d.clientHeight + 1,
    };
  };
  // The answer on the card, every form of it (WAY_FORMS), drawn into the
  // card by the page's own MV.sayWay and measured where it is: the call and
  // the part that may not be cut (the figure, or the refusal's state) whole
  // and inside the card, the line one row, its type size, what of the part
  // that may be cut is on the glass, and every child of the card inside the
  // card. The page draws its real line again on its next tick.
  const WAY_MEASURE = (forms) => {
    const MV = window.MapView;
    const w = document.getElementById('way');
    const shown = (el) => {
      if (!el || el.hidden) return false;
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && getComputedStyle(el).display !== 'none';
    };
    // How far the card's children run past its border, in px: 0 when none
    // does. Asked of each form, and of the same card with the line put away,
    // which is the card as it was before there was a line.
    const overBy = () => {
      const vr = document.getElementById('verdict').getBoundingClientRect();
      let o = 0;
      [].slice.call(document.getElementById('verdict').children).filter(shown).forEach((e) => {
        const r = e.getBoundingClientRect();
        o = Math.max(o, vr.top + 2 - r.top, r.bottom - (vr.bottom - 2));
      });
      return Math.round(o * 2) / 2;
    };
    w.hidden = true;
    const without = overBy();
    w.hidden = false;
    const out = { __without: without };
    for (const f of forms) {
      MV.sayWay(w, MV.wayLine(f[1], f[2]), false);
      const vr = document.getElementById('verdict').getBoundingClientRect();
      const card = { left: vr.left + 2, right: vr.right - 2, top: vr.top + 2,
                     bottom: vr.bottom - 2 };
      const inCard = (r) => r.left >= card.left - 0.5 && r.right <= card.right + 0.5
        && r.top >= card.top - 0.5 && r.bottom <= card.bottom + 0.5
        && r.right <= window.innerWidth + 0.5;
      const wr = w.getBoundingClientRect();
      const lh = parseFloat(getComputedStyle(w).lineHeight)
        || parseFloat(getComputedStyle(w).fontSize) * 1.2;
      // Every part that may not be cut: its words, whole (nothing ellipsised
      // or clipped inside it) and inside the card.
      const kept = [].slice.call(w.querySelectorAll('.call, .fig, .why')).map((e) => {
        const r = e.getBoundingClientRect();
        return { text: e.textContent, whole: e.scrollWidth <= e.clientWidth + 1 && inCard(r) };
      });
      // ...and what is on the glass of the part that may: the characters
      // inside its own box, which is where its ellipsis cuts.
      const more = [].slice.call(w.querySelectorAll('.more')).map((e) => {
        const box = e.getBoundingClientRect();
        let seen = '';
        const walk = document.createTreeWalker(e, NodeFilter.SHOW_TEXT);
        const rg = document.createRange();
        let n;
        while ((n = walk.nextNode())) {
          for (let i = 0; i < n.length; i++) {
            rg.setStart(n, i); rg.setEnd(n, i + 1);
            const c = rg.getBoundingClientRect();
            if (c.right <= box.right + 0.5) seen += n.data[i];
          }
        }
        return { text: e.textContent, seen: seen, inCard: inCard(box) };
      });
      out[f[0]] = {
        text: w.textContent, kept: kept, more: more,
        rows: Math.round(wr.height / lh), inCard: inCard(wr),
        px: parseFloat(getComputedStyle(w.querySelector('.call') || w).fontSize),
        over: overBy(),
      };
    }
    return out;
  };
  // Moving, gps.py's hold has 9.6 s left on a beat 0.4 s after a usable fix.
  const DRIVE_FIX = { lat: 33.9526, lon: -84.5499, gpsAge: 0.4, gpsErr: 12.0, gpsMode: 3,
                      gpsOk: true, gpsWhy: null, freshFor: 19.6, speed: 0.0, driving: false,
                      drivingFor: 0.0 };
  for (const panel of PLANNER_PANELS) {
    for (const view of ['screen', 'scene']) {
      for (const form of Object.keys(DRIVE.forms)) {
        const f = DRIVE.forms[form];
        const { ctx, page, push } = await carryPage(panel, view);
        const beat = (driving) => push(Object.assign({ alive: true, at: 1 }, f.beat || {}, {
          gps: { state: 'ok', ageSeconds: 0.4, fix: Object.assign({}, DRIVE_FIX,
            driving ? { speed: 13.4, driving: true, drivingFor: 9.6 } : {}) } }));
        await beat(false);
        for (const m of f.msgs) await push(m);
        // Past the page's tick, which renders again and folds the stops.
        await page.clock.runFor(1100);
        const parked = await page.evaluate(DRIVE_MEASURE);
        const wayParked = f.way ? await page.evaluate(WAY_MEASURE, DRIVE.way) : null;
        await beat(true);
        await page.clock.runFor(1100);
        const driving = await page.evaluate(DRIVE_MEASURE);
        const wayDriving = f.way ? await page.evaluate(WAY_MEASURE, DRIVE.way) : null;
        out[panel[0] + ' ' + view + ' drive ' + form] = { parked: parked, driving: driving,
                                                          wayParked: wayParked,
                                                          wayDriving: wayDriving };
        await page.close();
        await ctx.close();
      }
    }
  }
  // The map caption's chip, tapped: the sentence, and the chip back on a
  // second tap, after 20 s (WARN_OPEN_MS, the notices' own), and when the
  // line changes. Off the page's own mapSay, in Map view over no card (a
  // refusal: "no card read yet"), on a clock this harness turns.
  {
    const { ctx, page, push } = await carryPage(['1024x600', 1024, 600], 'scene');
    await page.click('#viewMode', { timeout: 5000 }).catch(() => {});
    await page.clock.runFor(300);
    const look = () => page.evaluate(() => {
      const note = document.getElementById('viewNote');
      return { chip: (note.querySelector('.chip') || {}).textContent || null,
               text: note.textContent, title: note.title,
               expanded: note.getAttribute('aria-expanded') };
    });
    const tap = async () => {
      await page.click('#viewNote', { timeout: 5000 }).catch(() => {});
      await page.clock.runFor(100);
    };
    const tapped = { before: await look() };
    await tap();
    tapped.opened = await look();
    await page.clock.runFor(20100);
    tapped.after20s = await look();
    await tap();
    await tap();
    tapped.secondTap = await look();
    await tap();
    tapped.reopened = await look();
    // A card that names nowhere: a different refusal, so a new line.
    await push({ ready: true, state: 'go', perHour: 30, pay: 9.0, minutes: 18,
                 miles: 3.1, places: [], text: '', track: null,
                 offer: { id: 'o-layout-caption', pay: 9.0, minutes: 18 } });
    await page.clock.runFor(1100);
    tapped.newLine = await look();
    out['caption tap'] = tapped;
    await page.close();
    await ctx.close();
  }
  await browser.close();
  console.log(JSON.stringify(out));
})().catch((e) => { console.log(JSON.stringify(
  // A throw anywhere in this driver is a FAULT, not a machine that
  // could not run the checks. Reported as `skip` it exited 0 and the
  // whole suite counted as passed with nothing run. The one real skip
  // — no chromium — is printed above, before anything can throw.
  { __crashed: String((e && e.stack) || e) })); });
'''

work = tempfile.mkdtemp()
journal = os.path.join(work, 'journal.jsonl')

# A fortnight of offers, so the log page is measured with a log in it and with
# every chart drawn. Nine hours apart, so forty offers span fifteen days: the
# landing page shows the week of them its default range holds, and the driver
# presses "30 days" to put the fortnight on the page for the day-of-week
# chart, which hides itself under fourteen days — and a chart that is not
# drawn is not measured. Rates deliberately spread across the verdicts so every
# row style is drawn.
now = time.time() * 1000
rows = []
for i in range(40):
    pay = 6.0 + (i % 13) * 2.5
    mins = 8 + (i * 7) % 50
    miles = 1.5 + (i % 9) * 2.1
    rows.append({
        'id': 'r%d' % i, 'at': now - i * 9 * 3600000, 'firstAt': now - i * 9 * 3600000,
        'pay': round(pay, 2), 'minutes': mins, 'miles': round(miles, 1),
        'perHour': round(pay / (mins / 60.0), 1),
        'grossPerHour': round(pay / (mins / 60.0), 1),
        'cost': round(miles * 0.35, 2), 'costPerMile': 0.35,
        'target': 25, 'band': 15, 'legs': 2, 'whole': True,
        'accepted': i % 7 == 0, 'hidden': i % 11 == 0, 'suspect': i % 17 == 0,
    })
# ...and a second card five minutes after each of the first twenty, so that
# there are runs of scanning to draw. Nine hours apart, every offer above is a
# stretch of one card, and a stretch of one card is not a run: the chart of
# runs was never drawn in this suite, and every check on it measured nothing.
for i in range(20):
    first = rows[i]
    second = dict(first, id='r%db' % i, at=first['at'] + 300000,
                  firstAt=first['at'] + 300000, pay=round(first['pay'] + 1.5, 2),
                  accepted=False, hidden=False, suspect=False)
    second['perHour'] = round(second['pay'] / (second['minutes'] / 60.0), 1)
    second['grossPerHour'] = second['perHour']
    rows.append(second)
# ...and three cards a minute ago that nobody has answered for, so Close the
# shift has rows to lay out. A minute back and a second apart, so all three are
# the newest counted cards and fall on one driver's day whatever the hour this
# runs at; the last carries a long place, because the place is the part of the
# row that has to give way to the two answers. The first carries the owner's
# own 4:43am figures, $41.02 for 63 minutes and 49.3 miles — the top card of
# the newest day of the real week, whose distance was cut to "49." at 390px
# when the figures ran under an ellipsis.
for k, (state, place, pay, mins, miles) in enumerate([
        ('go', 'Chick-fil-A, 2500 Cobb Pkwy SE, Kennesaw', 41.02, 63, 49.3),
        ('warn', 'Zaxbys', 15.5, 22, 7.3),
        ('go', 'The Varsity, 61 North Avenue NW at Spring Street, Atlanta', 16.5, 22, 7.3)]):
    at = now - 60000 - k * 1000
    rows.append({
        'id': 'rv%d' % k, 'at': at, 'firstAt': at, 'pay': pay, 'minutes': mins,
        'miles': miles, 'perHour': round(pay / (mins / 60.0), 1),
        'grossPerHour': round(pay / (mins / 60.0), 1), 'cost': round(miles * 0.35, 2),
        'costPerMile': 0.35, 'target': 25, 'band': 15, 'legs': 2, 'whole': True,
        'state': state, 'pickup': place,
    })
# ...and the pairings, so the "Second jobs" section is measured with something
# in it. One of each answer the panel can give, including the one where it
# declines to answer, because that row is drawn differently and its own width
# is the widest thing in the section.
for i, (state, ends, took) in enumerate([
        ('go', 'same-town', True), ('warn', None, False),
        ('no', 'elsewhere', None), (None, None, True)]):
    rows.append({
        'v': 1, 'kind': 'pair', 'at': now - i * 1800000, 'id': 'r%d' % (i * 3),
        'held': {'pay': 12.0 + i, 'minutes': 30, 'scanned': i % 2 == 0,
                 'dropoff': '1234 Daffodil Ln, Powder Springs, GA 30127',
                 'heldMs': 1080000},
        'offer': {'pay': 8.04 + i, 'minutes': 23,
                  'pickup': 'Chick-fil-A, 2500 Cobb Pkwy SE',
                  'dropoff': 'Chastain Rd NW, Kennesaw'},
        'stack': None if state is None else {
            'pay': 17.2, 'worst': 19.4, 'best': 34.1, 'leftMinutes': 12,
            'minMinutes': 23, 'maxMinutes': 35, 'state': state,
            'sure': state != 'no', 'ends': ends},
        # The row saying its verdict really is what the panel showed. Rows
        # written before recordPairing took the driver's target from the
        # reading have this absent, and the page reports those as "not
        # recorded" rather than as a word the panel used — which is right, and
        # is not what this file is measuring. These are modern rows.
        'judged': True,
    })
    if took is not None:
        rows.append({'kind': 'mark', 'id': 'r%d' % (i * 3), 'accepted': took,
                     'at': now - i * 1800000})
with open(journal, 'w') as fh:
    for r in rows:
        fh.write(json.dumps(r) + '\n')

# A frame on disk, or live.html hides the picture and there is no layout to
# measure. Portrait and the shape of a phone, because that is what the view
# being checked here publishes and the whole question is whether a tall picture
# gets the height of a wide panel.
frame = os.path.join(work, 'live.jpg')
try:
    from PIL import Image
    Image.new('RGB', (573, 1000), (238, 240, 244)).save(frame, quality=70)
except Exception:
    skip('no PIL, so there is no frame to lay out')

# ...and the same two pictures again, for the browser to answer the live view's
# own requests with.
#
# The file above reaches the page through `/api/frame.jpg`, and the page does
# not ask for that: it asks for `/api/frame.mjpeg`, a stream this server has
# nothing to put in without a scanner. So the picture every measurement of the
# live view was taken against was a broken image, 2px tall, and "the phone is
# taller than the scene was" was 2px against 2px dressed up as a result.
#
# Two shapes, not one, because the claim being measured is that a portrait
# picture in a landscape cell gets the height a landscape one cannot use.
def _jpeg(size, colour):
    buf = io.BytesIO()
    Image.new('RGB', size, colour).save(buf, format='JPEG', quality=70)
    return base64.b64encode(buf.getvalue()).decode('ascii')


FRAMES = {'scene': _jpeg((640, 480), (44, 48, 56)),
          'screen': _jpeg((573, 1000), (238, 240, 244))}

# Two 📷 Snaps for snaps.html to lay out, in the folder the server keeps them
# in — beside the journal. One whole, at the panel's own size; one with no
# screenshot and the longest reason the server gives for that, so the widest
# line the page can draw is on it. The whole one carries the longest note the
# rig keeps (SNAP_NOTE_MAX, read out of server.js) in its widest letter with no
# space in it: the heading that has nowhere to wrap, on the list and in the
# one file the snap is saved as.
_NOTE_MAX = int(re.search(r'var SNAP_NOTE_MAX = (\d+);',
                          open(os.path.join(ROOT, 'server.js'), encoding='utf-8').read()).group(1))
_shelf = os.path.join(work, 'snaps')
for _name, _whole in (('2026-10-07_21-14-03', True), ('2026-10-07_21-15-40', False)):
    os.makedirs(os.path.join(_shelf, _name))
    if _whole:
        Image.new('RGB', (800, 480), (11, 15, 20)).save(os.path.join(_shelf, _name, 'panel.png'))
        # ...and the third picture a whole one has: the reader's crop, at the
        # size the test ride card's comes off the warp.
        Image.new('L', (881, 1134), 200).save(
            os.path.join(_shelf, _name, 'reader.jpg'), quality=72)
    Image.new('RGB', (480, 1040), (238, 240, 244)).save(
        os.path.join(_shelf, _name, 'camera.jpg'), quality=60)
    with open(os.path.join(_shelf, _name, 'status.json'), 'w') as _fh:
        _fh.write('{}\n')
    _missing = [] if _whole else [{
        'what': 'panel', 'file': 'panel.png', 'saved': False,
        'why': 'no display session found',
        'detail': 'no wayland-* socket in /run/user/1000, no X display'}]
    _record = {'v': 1, 'name': _name, 'at': now,
               'contents': _missing, 'notes': [],
               'said': 'saved' if _whole else
                       'saved — no screenshot: no display session found'}
    if _whole:
        _record['note'] = 'W' * _NOTE_MAX
    with open(os.path.join(_shelf, _name, 'snap.json'), 'w') as _fh:
        json.dump(_record, _fh)

port = free_port()
proc = subprocess.Popen(
    ['node', os.path.join(ROOT, 'server.js')],
    env=dict(os.environ, SCANNER='0', PORT=str(port), JOURNAL=journal,
             FRAME=frame),
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
base = 'http://127.0.0.1:%d' % port
try:
    for _ in range(120):
        try:
            urllib.request.urlopen(base + '/api/status', timeout=1).read()
            break
        except Exception:
            time.sleep(0.1)
    else:
        raise RuntimeError('the server never came up')

    driver = os.path.join(work, 'layout.js')
    open(driver, 'w').write(DRIVER)
    env = dict(os.environ,
               NODE_PATH=os.pathsep.join(NODE_PATHS),
               PW_EXES=json.dumps([
                   os.environ.get('CHROMIUM', ''),
                   '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
               ]))
    proc2 = subprocess.run(
        ['node', driver, base, json.dumps(PANELS), json.dumps(PAGES),
         json.dumps(FRAMES), json.dumps(CAPTION_LINES), json.dumps(SNAP_FIXTURE),
         json.dumps(SNAP_PANELS), json.dumps(NOVERDICT),
         json.dumps(NOVERDICT_PANELS),
         json.dumps({'stops': PLANNER_STOPS, 'unfiled': PLANNER_UNFILED,
                     'notes': PLANNER_NOTES, 'notice': PLANNER_NOTICE,
                     'blind': PLANNER_BLIND}),
         json.dumps(PLANNER_PANELS), json.dumps(HERE_LINES), json.dumps(FOUNDPAY),
         json.dumps(LIVE_HERE_LINES), json.dumps(HELD),
         json.dumps({'beat': CHIPS_BEAT, 'card': CHIPS_CARD, 'offer': CHIPS_OFFER}),
         json.dumps({'beats': HEAT_BEATS, 'was': HEAT_WAS}),
         json.dumps({'forms': DRIVE_FORMS, 'way': WAY_FORMS})],
        env=env, capture_output=True, text=True, timeout=600)
    line = (proc2.stdout or '').strip().split('\n')[-1] if proc2.stdout else ''
    try:
        got = json.loads(line)
    except Exception:
        crashed(proc.stderr)
    # A throw in the driver, which the catch at its foot now reports as
    # its own thing rather than as a skip — see crashed().
    if got.get('__crashed'):
        crashed(got['__crashed'])
    if got.get('skip'):
        skip(got['skip'])

    # 📷 Snap, on one screen.
    #
    # Off the bar, which holds six — AUDITS.md's Settled — and on the status
    # row, where it costs nothing: not a tenth of a pixel of the bar or the
    # row, with its label or with the longest answer it gives. Drawn exactly
    # where the row has room for it, and that is measured, not stood in for:
    # `roomWith` is the median's spare with the control forced onto the row,
    # on every screen, so one that does not draw it is held to the reason. A
    # rule written as the screen's size ("landscape, 400px tall") was the
    # stand-in, and a phone held on its side broke it both ways round.
    def snap_checks(panel, sn):
        ok_('📷 Snap was measured at %s' % panel, 'drawn' in sn)
        room = (sn.get('roomWith') if sn.get('roomWith') is not None else -1) >= 0
        eq('📷 Snap is drawn at %s exactly where the row has room for it (%gpx with it)'
           % (panel, sn.get('roomWith') if sn.get('roomWith') is not None else float('nan')),
           bool(sn.get('drawn')), room)
        ok_('...on the status row, never on the bar, at %s' % panel,
            sn.get('inRow') and not sn.get('inBar'))
        if room:
            ok_('...on the glass at %s' % panel, sn.get('onGlass'))
            eq('...saying what it is at %s' % panel, sn.get('label'), '📷 Snap')
            eq('...with its label inside its own box at %s' % panel,
               sn.get('spilt'), '')
            ok_('...and its longest answer on the glass, clear of the '
                'connection line, at %s' % panel, sn.get('saidOnGlass'))
        ok_('...moving nothing on the bar or the row at %s' % panel, sn.get('same'))
        ok_('...nor with its longest answer on it at %s' % panel, sn.get('sameSaid'))
        ok_('...and the page still fits, label or answer, at %s' % panel,
            not sn.get('over') and not sn.get('overSaid'))
        ok_('...while the shift line\'s median reaches the glass beside the '
            'longest connection line at %s (%spx to spare)'
            % (panel, sn.get('figureSpare')),
            (sn.get('figureSpare') if sn.get('figureSpare') is not None else -1) >= 0)

    for panel, w, h in SNAP_PANELS:
        snap_checks(panel, got.get('%s snap' % panel) or {})

    # The line under the verdict when a reading has none. No wider than the
    # line it replaced, every letter on the glass, and costing the panel
    # nothing the old line did not cost it: the label, the verdict, the camera
    # view, the status row and the bar exactly where the old sentence left
    # them, with the same tracking note beside it. One line is the whole budget
    # when there is no note — the verdict is this row's other occupant and
    # every pixel the line takes comes out of it.
    NOTE = {'alone': 'alone', 'drift': 'beside "tracking 30px"',
            'lost': 'beside "screen not visible"'}
    for panel, w, h in NOVERDICT_PANELS:
        for view in ('screen', 'scene'):
            where = '%s, %s view' % (panel, view)
            nv = got.get('%s %s noverdict' % (panel, view)) or {}
            eq('the no-verdict line was measured at %s' % where, sorted(nv),
               sorted(NOVERDICT))
            if sorted(nv) != sorted(NOVERDICT):
                continue
            was = nv['nothing/alone']
            # Two pictures are two layouts, or this measured one of them twice.
            eq('...in the layout that picture is drawn in at %s' % where,
               was['phone'], view == 'screen')
            ok_('...against the line it replaced at %s (%r)' % (where, was['text']),
                was['text'] == 'scanner running, no offer on screen')
            # A read over a screen that just read as no offer: the label and
            # the line say what it last found, and fit where the line and the
            # label it stands in for did.
            ag = nv['again/alone']
            eq('a read over a no-offer screen is READING THE SCREEN at %s' % where,
               (ag['label'], ag['text']),
               ('READING THE SCREEN', 'no offer on screen · reading again'))
            eq('...every letter of the label in the verdict card at %s' % where,
               ag['labelOff'], '')
            eq('...on one line, as WAITING FOR AN OFFER is, at %s (%d, %d)'
               % (where, ag['labelLines'], was['labelLines']),
               ag['labelLines'], was['labelLines'])
            eq('...and every letter of the line on the glass at %s' % where,
               ag['off'], '')
            ok_('...on no more lines than the line it replaced at %s (%d, %d)'
                % (where, ag['lines'], was['lines']),
                1 <= ag['lines'] <= was['lines'])
            # Everything but the label's own box, whose width is its words'.
            _nolabel = lambda l: dict(l, label=l['label'][1:2] + l['label'][3:])
            eq('...moving nothing else on the panel at %s' % where,
               _nolabel(ag['layout']), _nolabel(was['layout']))
            for key, opens in (('nopay', 'no pay read'),
                               ('notime', 'pay, no time'),
                               ('clipped', 'pay at the box edge')):
                s = nv[key + '/alone']
                ok_('"%s" is the line measured at %s (%r)' % (opens, where, s['text']),
                    s['text'].startswith(opens))
                # The rule the rest follows from: whatever trackNote() can put
                # beside the old sentence and still fit, it can put beside
                # this one.
                ok_('..."%s" no wider than the line it replaced at %s (%spx of %spx)'
                    % (opens, where, s['width'], was['width']),
                    0 < s['width'] <= was['width'])
                for track, note in NOTE.items():
                    s, old = nv['%s/%s' % (key, track)], nv['nothing/%s' % track]
                    ok_('..."%s" %s, on no more lines than the old line %s at %s '
                        '(%d, %d)' % (opens, note, note, where, s['lines'], old['lines']),
                        1 <= s['lines'] <= old['lines'])
                    eq('..."%s" %s, every letter of it on the glass at %s'
                       % (opens, note, where), s['off'], '')
                    # Against the old line with the same note when they take
                    # the same lines; a shorter sentence that stays on one
                    # line where the old one wrapped leaves the panel as the
                    # old sentence alone left it.
                    ref = old if s['lines'] == old['lines'] else was
                    eq('..."%s" %s, moving nothing the old line did not move at %s'
                       % (opens, note, where), s['layout'], ref['layout'])

    # PAY ? under a payout read off a card found above the box: every
    # letter of it inside its own cell and on the glass, and nothing else on
    # the panel moved from where PAY left it — the four figures, the labels
    # beside them, the verdict, the picture, the status row and the bar.
    for panel, w, h in NOVERDICT_PANELS:
        for view in ('screen', 'scene'):
            where = '%s, %s view' % (panel, view)
            fp = got.get('%s %s foundpay' % (panel, view)) or {}
            ok_('a payout off a found card was measured at %s' % where,
                'found' in fp and 'drawn' in fp)
            if not ('found' in fp and 'drawn' in fp):
                continue
            eq('...labelled PAY ? at %s' % where,
               (fp['found']['text'].lower(), fp['drawn']['text'].lower()),
               ('pay ?', 'pay'))
            ok_('...shown at %s' % where, fp['found']['shown'])
            eq('...every letter of it in its cell and on the glass at %s' % where,
               fp['found']['off'], '')
            # Nothing moves but the figure, sideways inside its own cell: the
            # cell centres the figure and its label together, so a longer label
            # takes the figure a few pixels left on the panels that lay them
            # side by side (480x320). Up and down, and everything else on the
            # panel, exactly where PAY left it.
            _still = lambda l: dict(l, pay=l['pay'][1:])
            eq('...moving nothing PAY did not move, the figure itself bar a few '
               'pixels sideways inside its cell, at %s' % where,
               _still(fp['found']['layout']), _still(fp['drawn']['layout']))
            ok_('...the figure still inside its cell at %s' % where, fp['found']['payIn'])
            # Three figures leave no room beside them, on the 3.5" hat's phone
            # picture, even for PAY. So asked against PAY: no letter off its
            # cell that PAY did not put off too.
            ok_('...and at $999.99, no more of it off its cell than PAY at %s (%r, %r)'
                % (where, fp['found3']['off'], fp['drawn3']['off']),
                len(fp['found3']['off'].strip()) <= len(fp['drawn3']['off'].strip()))

    # The notices as chips: five, the most one card writes in ordinary use.
    # Every letter of every chip inside the card and on the glass, the verdict
    # and its rate still inside the card, nothing past the glass, and the
    # bar, the status row and the picture where the card without them left
    # them. Tapped open, the sentences: every word of them reachable, and the
    # verdict still in the card. The chips take less of the card than the
    # sentences do, which is what they are for.
    for panel, w, h in NOVERDICT_PANELS:
        for view in ('screen', 'scene'):
            where = '%s, %s view' % (panel, view)
            cm = got.get('%s %s chips' % (panel, view)) or {}
            _c, _o = cm.get('chips') or {}, cm.get('open') or {}
            eq('the small type is %s at %s (address, label, figure, line under, '
               'notice, status row)' % (SMALL_SIZES[panel], where),
               _c.get('sizes'), SMALL_SIZES[panel])
            # Not on the 3.5" hat, where a notice hides the figures on
            # purpose (the rule under #verdict:has(#warn) in live.html).
            if h > 380:
                ok_('...with the address and the figures inside the card at %s' % where,
                    _c.get('placesIn') and _c.get('subIn'))
            eq('the notices are five chips, the end read with ⌖ last, at %s' % where,
               _c.get('chips'), CHIPS_WANT)
            eq('...every letter of them inside the card and on the glass at %s' % where,
               _c.get('off'), '')
            ok_('...with the verdict label and the rate inside the card at %s' % where,
                _c.get('labelIn') and _c.get('rateIn'))
            no_('...nothing past the glass at %s' % where, _c.get('over'))
            # ...against the same card on record with no notice: the fifth
            # chip's card puts ✓ Took on the bar.
            _cb = cm.get('base') or {}
            eq('...the bar, the status row and the picture where they were at %s' % where,
               (_c.get('layout'), _cb.get('chips')), (_cb.get('layout'), []))
            eq('tapped, the notice is the sentences at %s' % where,
               (_o.get('chips'), 'Offers are NOT being saved' in (_o.get('text') or '')),
               ([], True))
            ok_('...every word of them reachable, whole or scrolled to, at %s' % where,
                _o.get('reach'))
            ok_('...with the verdict label still inside the card at %s' % where,
                _o.get('labelIn'))
            no_('...nothing past the glass at %s' % where, _o.get('over'))
            ok_('...and the chips need less of the card than the sentences at %s '
                '(%spx, %spx)' % (where, _c.get('need'), _o.get('need')),
                (_c.get('need') or 1e9) < (_o.get('need') or 0))

    # The status row, steady: the dot, the ticks, what they came to and the
    # median, 📷 and "…", with "scanner reading" left to the green dot. The
    # widest real figures whole on the rig's panel and the 800x480, and the
    # median's digits on the glass on the 3.5" hat; "…" on the glass, its
    # glyph in its box, costing the row and the bar nothing. Opened, the
    # sheet sits over the verdict's column above the row, every letter in
    # it, and the row and the bar where they were.
    for panel, w, h in NOVERDICT_PANELS:
        for view in ('screen', 'scene'):
            where = '%s, %s view' % (panel, view)
            rm = got.get('%s %s row' % (panel, view)) or {}
            _r, _o = rm.get('closed') or {}, rm.get('open') or {}
            eq('the status row is short at %s, with no words for the steady connection'
               % where, (_r.get('shift'), _r.get('conn')),
               ('\u271310 $141 \u00b7 -$17/hr an offer', False))
            if h > 380:
                ok_('...whole at %s' % where, _r.get('shiftWhole'))
            ok_('...the median\'s digits on the glass at %s' % where, _r.get('figureIn'))
            ok_('..."…" on the row and the glass at %s (%spx)' % (where, _r.get('moreW')),
                _r.get('more'))
            eq('...its glyph inside its box at %s' % where, _r.get('moreOut'), '')
            ok_('...costing the row and the bar nothing at %s' % where,
                _r.get('moreCostsNothing'))
            no_('...nothing past the glass at %s' % where, _r.get('over'))
            ok_('"…" opens the whole row at %s' % where, _o.get('sheet'))
            ok_('...over the verdict\'s column, above the row, at %s' % where,
                _o.get('sheetInPane'))
            eq('...every letter of it inside it at %s' % where, _o.get('sheetOut'), '')
            eq('...and the row and the bar where they were at %s' % where,
               _o.get('layout'), _r.get('layout'))
            no_('...nothing past the glass at %s' % where, _o.get('over'))

    # The heat guard's chip on the status row (live.html heatNote): said, in
    # the notices' kind of chip, at the front of the note; whole and on the
    # glass at the rig's 1024x600, the 800x480 and the 3.5" hat, in both
    # pictures, beside the widest real shift line. Alone, what it means after
    # the dot, the median's digits still on the glass and the sentence on "…".
    # Beside a GPS a day stale, no wider than the widest note the row held
    # before it — "Pi temp limit 85°C · GPS: no fix for 1000 min" — measured on
    # the same row. And the row and the bar where a row with no note left them.
    for panel, w, h in NOVERDICT_PANELS:
        for view in ('screen', 'scene'):
            where = '%s, %s view' % (panel, view)
            hm = got.get('%s %s heat' % (panel, view)) or {}
            _ha, _hoff = hm.get('alone') or {}, hm.get('off') or {}
            eq('the panel says it at %s: the heat guard\'s chip on the status row (%r)'
               % (where, _ha.get('chip')), (_ha.get('chip'), _ha.get('shown'), _ha.get('whole'),
                                             _ha.get('chipIn')),
               (HEAT_SAYS['alone'], True, True, True))
            ok_('...the sentence on its title at %s (%r)' % (where, _ha.get('title')),
                'less often' in (_ha.get('title') or '')
                and 'Offers, ⌖ and 📷 Snap are read as fast as ever' in (_ha.get('title') or ''))
            eq('...and on "…", on the glass, at %s' % where,
               (((hm.get('sheet') or {}).get('lines') or [None])[0], (hm.get('sheet') or {}).get('onGlass')),
               (_ha.get('title'), True))
            eq('...and nothing with the guard off at 76°C, at %s' % where,
               (_hoff.get('text'), _hoff.get('chip')), ('', None))
            ok_('...the median\'s digits on the glass beside it at %s' % where,
                _ha.get('figureIn') and (hm.get('slowed') or {}).get('figureIn'))
            for key in ('slowed', 'hot gps', 'slowed gps', 'low power gps'):
                _hk = hm.get(key) or {}
                eq('...%s says %r at %s, whole and on the glass' % (key, HEAT_SAYS[key], where),
                   (_hk.get('text'), _hk.get('shown'), _hk.get('whole')),
                   (HEAT_SAYS[key], True, True))
            for key in ('hot gps', 'slowed gps', 'low power gps'):
                _hk = hm.get(key) or {}
                ok_('...%s no wider than the widest note before the chip at %s (%spx, was %spx)'
                    % (key, where, _hk.get('w'), _hk.get('wasW')),
                    _hk.get('w') is not None and _hk.get('wasW') is not None
                    and _hk['w'] <= _hk['wasW'])
            eq('...the row and the bar where a row with no note left them at %s' % where,
               sorted(set((hm.get(k) or {}).get('layout') for k in HEAT_SAYS)),
               [_hoff.get('layout')])
            no_('...nothing past the glass at %s' % where,
                any((hm.get(k) or {}).get('over') for k in HEAT_SAYS))

    # The night palette moves nothing: the card, its words, the row, the bar
    # and the picture where the day's palette left them, the page black.
    for panel, w, h in NOVERDICT_PANELS:
        for view in ('screen', 'scene'):
            where = '%s, %s view' % (panel, view)
            nm = got.get('%s %s night' % (panel, view)) or {}
            ok_('the night palette moves nothing on the panel at %s' % where, nm.get('same'))
            eq('...and paints the page black at %s' % where,
               (nm.get('dayBg'), nm.get('nightBg')), ('rgb(11, 15, 20)', 'rgb(0, 0, 0)'))

    # The Trip Planner's stops between offers, at the most the block holds:
    # four stops and the line under them. Every one on a line of its own, its
    # kind and time on the glass and its name begun, with only the rest of the
    # name and the address given to the ellipsis; inside the card with the
    # verdict label; and the card, the picture, the status row and the bar
    # exactly where they were before the stops arrived. The name came before
    # the time once, and in the 3.5" hat's scene picture "Taco Hut Express"
    # pushed "by 12:05" into the ellipsis.
    for panel, w, h in PLANNER_PANELS:
        for view in ('screen', 'scene'):
            where = '%s, %s view' % (panel, view)
            pm = got.get('%s %s planner' % (panel, view)) or {}
            was, now = pm.get('before') or {}, pm.get('after') or {}
            ok_('the Trip Planner\'s stops were measured at %s' % where,
                was and now and now.get('shown'))
            if not (was and now and now.get('shown')):
                continue
            eq('...in the layout that picture is drawn in at %s' % where,
               now.get('phone'), view == 'screen')
            _lines = now.get('lines') or []
            eq('...four stops and the line under them at %s' % where, len(_lines), 5)
            eq('...each on one line at %s' % where,
               [l['text'] for l in _lines if l.get('rows') != 1], [])
            eq('...every stop\'s kind and time on the glass and its name begun, only '
               'the rest given to the ellipsis, at %s' % where,
               [(l['text'][:24], l['cut']) for l in _lines if l.get('cut')], [])
            eq('...all of it inside the card at %s' % where,
               [l['text'][:24] for l in _lines
                if not (l.get('inCard') and l.get('onGlass'))], [])
            ok_('...with the verdict label still inside it at %s' % where,
                now.get('labelIn'))
            ok_('...in type no smaller than the address line\'s floor at %s (%spx)'
                % (where, now.get('fontPx')), (now.get('fontPx') or 0) >= 12)
            # ...and the address line's size, which they take (SMALL_SIZES).
            eq('...the stops at the address line\'s size at %s' % where,
               now.get('fontPx'), SMALL_SIZES[panel][0])
            eq('...and the card, the picture, the status row and the bar where they '
               'were at %s' % where, now.get('layout'), was.get('layout'))
            no_('...and nothing scrolls at %s' % where, now.get('over'))
            # The line under the stops in each of the scanner's three reasons,
            # whole and on one line: it is the only place on the glass that
            # says why the button stayed amber.
            _notes = pm.get('notes') or {}
            eq('...and the line saying why no end was taken, in each of its three '
               'wordings, whole on one line at %s' % where,
               sorted((why, (n or {}).get('text'), (n or {}).get('rows'), (n or {}).get('cut'))
                      for why, n in _notes.items()),
               [('address', 'dropoff address unread', 1, ''),
                ('dropoffs', '2 dropoffs: end not guessed', 1, ''),
                ('list', 'list cut off: end not guessed', 1, '')])

    # The same-store note's words (live.html sameNote): whole on the
    # address line, short on the pair line on the 3.5" hat.
    def _same1(h):
        return 'same store' if h <= 380 else 'same store as in car'

    def _same2(h):
        return 'same store ②' if h <= 380 else 'same store as ②'

    # Two orders in the car (carrying two on), on the three panels and in both
    # pictures: the two compact order lines between offers, whole — pay and
    # GPS word inside the card — with "2 dropoffs read · whose?" under them;
    # the chooser over the verdict pane, its rows 96px where the pane has the
    # height and never under the bar's 52px where it does not, every row's
    # words whole, the bar and its six controls where they were; and on the
    # pair line "with ① + ②" whole beside its whole range (the card against
    # both, Stage 6), or "vs ① only" with carrying two off and two read back.
    for panel, w, h in PLANNER_PANELS:
        for view in ('screen', 'scene'):
            where = '%s, %s view' % (panel, view)
            cm = got.get('%s %s carry' % (panel, view)) or {}
            _bf, _tw, _th, _of = (cm.get('before') or {}, cm.get('two') or {},
                                  cm.get('three') or {}, cm.get('offer') or {})
            ok_('two orders in the car were measured at %s' % where, _bf and _tw and _th and _of)
            if not (_bf and _tw and _th and _of):
                continue
            _ln = _bf.get('lines') or [None, None, None]
            eq('the two-order lines are whole inside the card at %s' % where,
               [((x or {}).get('text'), (x or {}).get('cut')) for x in _ln],
               [('① $112.45 → 4821 Kestrel Dr S · too many answers', ''),
                ('② $128.08 → 1985 Cobb Pkwy NW · too many answers', ''),
                ('2 dropoffs read · whose?', '')])
            eq('...with Drop ▾ on a bar of six at most, and nothing scrolling at %s' % where,
               (_bf['bar']['drop'], _bf['bar']['count'] <= 6, _bf.get('over')),
               ('Drop ▾', True, False))
            _c2 = _tw.get('chooser') or {}
            _rows2 = _c2.get('rows') or []
            eq('the chooser\'s rows read whole at %s' % where,
               [(r.get('text'), r.get('cut')) for r in _rows2],
               [('① $112.45 · 4821 Kestrel Dr S', False), ('② $128.08 · ?', False),
                ('Neither', False)])
            eq('...over the verdict pane, the bar where it was and still its six at %s' % where,
               (_c2.get('inPane'), _tw['bar']['box'] == _bf['bar']['box'],
                _tw['bar']['count'] == _bf['bar']['count'], _tw.get('over')),
               (True, True, True, False))
            _hs = [r.get('h') for r in _rows2[:2]]
            if h >= 480:
                eq('...its two order rows 96px tall at %s' % where, _hs, [96, 96])
            else:
                ok_('...its order rows no shorter than the bar\'s 52px at %s (%r)' % (where, _hs),
                    _hs and all(x >= 52 for x in _hs))
            _c3 = _th.get('chooser') or {}
            _rows3 = _c3.get('rows') or []
            eq('...and with the screened card as a third row, still whole and in the pane at %s'
               % where,
               ([(r.get('text'), r.get('cut')) for r in _rows3], _c3.get('inPane'),
                _th['bar']['box'] == _bf['bar']['box']),
               ([('① $112.45 · 4821 Kestrel Dr S', False), ('② $128.08 · ?', False),
                 ('This card $118.04', False), ('Neither', False)], True, True))
            ok_('...every row no shorter than 52px at %s (%r)'
                % (where, [r.get('h') for r in _rows3]),
                _rows3 and all((r.get('h') or 0) >= 52 for r in _rows3))
            # ...and with one order in the car and a card being screened:
            # ①, the card and Neither, each whole, in the pane, the bar where
            # it was; the two answers 96px where the pane has the height, and
            # never under the bar's 52px where it does not.
            _one = cm.get('one') or {}
            _c1 = _one.get('chooser') or {}
            _rows1 = _c1.get('rows') or []
            eq('the chooser with one order in the car and a card screened: ①, the card and '
               'Neither, whole and in the pane at %s' % where,
               ([(r.get('text'), r.get('cut')) for r in _rows1], _c1.get('inPane'),
                (_one.get('bar') or {}).get('box') == _bf['bar']['box'], _one.get('over')),
               ([('① $112.45 · 4821 Kestrel Dr S', False), ('This card $118.04', False),
                 ('Neither', False)], True, True, False))
            _hs1 = [r.get('h') for r in _rows1[:2]]
            if h >= 480:
                eq('...① and the card 96px tall at %s' % where, _hs1, [96, 96])
            else:
                ok_('...every row no shorter than the bar\'s 52px at %s (%r)'
                    % (where, [r.get('h') for r in _rows1]),
                    _rows1 and all((r.get('h') or 0) >= 52 for r in _rows1))
            # The pair line against both orders, at the most it holds: the
            # range whole, and "with ① + ②" whole in the slot "vs ① only"
            # had. In the words that give way it was cut to "with ①" at
            # 800x480 beside the scene picture and "with ① +" on the hat,
            # which reads as a range against one order.
            _pr = _of.get('pair') or {}
            eq('the two-order pair line keeps its range whole, and says "with ① + ②" whole, '
               'at %s' % where,
               (_pr.get('range'), _pr.get('rangeCut'), _pr.get('both'), _pr.get('bothCut'),
                _of.get('vs')),
               ('-$16 to $133/hr', '', 'with ① + ②', '', None))
            # ...and "same store as ②" under them, whole, at the head of the
            # address line (live.html sameNote): the store of the second
            # order (server.js sameStoreOf), never in the words that give way.
            # On the 3.5" hat, whose address line the answer on the card puts
            # away, "same store ②" on the pair line's first row.
            eq('...and "%s" whole at %s' % (_same2(h), where),
               (_pr.get('same'), _pr.get('sameCut')), (_same2(h), ''))
            # ...and the store's measured waits at their widest, "waited ~12
            # min avg (10)", whole on the address line after the note
            # (live.html waitNote): the pickup's text is what gives way. On
            # the 3.5" hat the answer on the card puts the address line away
            # (as for "same store" above), and the note goes with it:
            # AUDITS.md's Open note.
            eq('...and "waited ~12 min avg (10)" whole on the address line at %s' % where,
               (_pr.get('placesUp'), _pr.get('wait'), _pr.get('waitCut')),
               (False, None, None) if h <= 380 else (True, 'waited ~12 min avg (10) ·', ''))
            # ...and the on-time hint at its widest, first in the words that
            # give way: whole on every panel but the 3.5" hat beside the
            # scene picture, where the ellipsis takes "n ·" and leaves
            # "① late ~12 mi" — the call and its minutes, never the range.
            _otc = _pr.get('ontimeCut') or ''
            ok_('...and the on-time hint "\u2460 late ~12 min" at %s, cut by at most its last '
                'letter and dot (%r)' % (where, (_pr.get('ontime'), _otc)),
                _pr.get('ontime') == '\u2460 late ~12 min \u00b7'
                and (_otc == '' or (h <= 380 and view == 'scene' and _otc == 'n \u00b7')))
            # ...and with carrying two off and two read back, "vs ① only"
            # beside the chip, whole, as before.
            _vs = (cm.get('offerFirst') or {}).get('vs') or {}
            eq('the pair line says "vs ① only", whole, with carrying two off and two '
               'read back at %s' % where,
               (_vs.get('text'), _vs.get('cut')), ('vs ① only', ''))

    # The foot of the verdict pane with the Undo a Took that added an order
    # offers and the status row's "…" sheet both up: they were drawn one on
    # top of the other. Stacked, the Undo where it was and the sheet above it,
    # each whole and each the element its own centre (and each of the sheet's
    # lines' centres) hits. On the three panels in both pictures, and the
    # phone, where both are fixed to the glass rather than to the grid.
    for panel, w, h in list(PLANNER_PANELS) + [('390x844', 390, 844)]:
        for view in (('screen', 'scene') if w > h else ('screen',)):
            where = '%s, %s view' % (panel, view)
            fm = got.get('%s %s foot' % (panel, view)) or {}
            _al, _bo = fm.get('alone') or {}, fm.get('both') or {}
            _ua, _ub, _sb = _al.get('undo') or {}, _bo.get('undo') or {}, _bo.get('sheet') or {}
            ok_('the Undo and the "…" sheet were both up together at %s' % where,
                _ua and _ub and _sb)
            if not (_ua and _ub and _sb):
                continue
            eq('the Undo says what it undoes, whole and tappable, at %s' % where,
               (_ua.get('text'), _ua.get('cut'), _ua.get('hit')),
               ('Added ② $128.08 · Undo', '', True))
            ok_('...and the "…" sheet opened inside its five seconds does not overlap it at %s'
                % where, _bo.get('apart'))
            eq('...both whole: no glyph outside its own box, the verdict pane or the glass, '
               'at %s' % where, (_ub.get('cut'), _sb.get('cut')), ('', ''))
            eq('...and both tappable: the Undo\'s centre and every line of the sheet hit '
               'their own at %s' % where,
               (_ub.get('hit'), _sb.get('hit'), bool(_sb.get('lines'))
                and all(_sb.get('lines'))), (True, True, True))
            # Scrolling as it did before "…" (the phone may scroll down; the
            # dashboard panels do not, here or anywhere): the sheet adds none.
            eq('...the Undo where it was before "…" was pressed, and the sheet adds no '
               'scrolling, at %s' % where,
               (_ub.get('box') == _ua.get('box'), bool(_bo.get('over')) and not _al.get('over'),
                bool(_bo.get('over')) and w > h), (True, False, False))

    # The map caption's chip under the driver's tap, off the page's own mapSay
    # in Map view over no card (a refusal): the sentence on a tap, the chip
    # back after 20 s (the notices' WARN_OPEN_MS), on a second tap, and when
    # the line changes to another.
    _ct = got.get('caption tap') or {}
    _no_card = 'no card read yet — nothing to put on a map'
    _nowhere = 'this card names nowhere yet — ⌖ Scan reads it off your phone'
    eq('the map caption\'s refusal is a chip, its sentence on its title',
       [(_ct.get('before') or {}).get(k) for k in ('chip', 'title', 'expanded')],
       [CAPTION_CHIPS['no card at all'], _no_card, 'false'])
    eq('...a tap swaps the chip for the sentence',
       [(_ct.get('opened') or {}).get(k) for k in ('chip', 'text', 'expanded')],
       [None, _no_card, 'true'])
    eq('...which goes back to the chip on its own after 20 s',
       (_ct.get('after20s') or {}).get('chip'), CAPTION_CHIPS['no card at all'])
    eq('...and on a second tap', (_ct.get('secondTap') or {}).get('chip'),
       CAPTION_CHIPS['no card at all'])
    eq('...and when the line changes, the new refusal comes up as its chip',
       [(_ct.get(k) or {}).get('chip') for k in ('reopened', 'newLine')]
       + [(_ct.get('newLine') or {}).get('title')],
       [None, CAPTION_CHIPS['a card naming nowhere'], _nowhere])

    # The order in the car, on the card, at the most each line is asked to
    # hold (HELD), on the three panels and in both pictures.
    #
    # Between offers, in WAITING FOR AN OFFER's place: where it goes next and
    # by when, whole, and the name begun; one line with the pay and the GPS
    # drop's state whole; the four stops under them, inside the card.
    #
    # With an offer up, the pair line above the figures, its range whole —
    # under the figures, at the foot of the card, it ran past the border on
    # the 1024x600 panel in a browser window (the driver's snap of 12 Oct,
    # 17:19) — and the order in the car in one line under the card, its pay
    # and GPS state whole.
    #
    # The whole card is held inside its border wherever it fits, which is
    # everywhere but one: the 3.5" hat beside the scene picture, whose card
    # is 228px wide, where the pair's figures wrap to two rows and the pair
    # line to two, and the card was already over its box with a pair before
    # this — the word PASS 5px above the border and the pair row 4px below
    # it, measured on experimental. It is the aiming view; reading an offer
    # on the hat is the phone picture, which is held whole.
    for panel, w, h in PLANNER_PANELS:
        for view in ('screen', 'scene'):
            where = '%s, %s view' % (panel, view)
            hm = got.get('%s %s held' % (panel, view)) or {}
            _b, _o, _t = hm.get('between') or {}, hm.get('offer') or {}, hm.get('took') or {}
            ok_('the order in the car was measured at %s' % where, _b and _o and _t)
            if not (_b and _o and _t):
                continue
            eq('...in the layout that picture is drawn in at %s' % where,
               _b.get('phone'), view == 'screen')
            _n = _b.get('next') or {}
            eq('the order in the car is named between offers at %s' % where,
               (_n.get('when'), _n.get('whenCut'), _n.get('whenRows'), _n.get('whereFirst'),
                _b.get('label')),
               ('Pickup by 11:52', '', 1, True, None))
            ok_('...its name in no more than two rows at %s (%r)' % (where, _n.get('whereRows')),
                1 <= (_n.get('whereRows') or 0) <= 2)
            ok_('...larger than anything else on the card at %s (%spx, the time %spx)'
                % (where, _n.get('wherePx'), _n.get('whenPx')),
                (_n.get('wherePx') or 0) > (_n.get('whenPx') or 0) >= 16)
            _l = _b.get('line') or {}
            eq('...with its pay and the GPS drop\'s state whole at %s' % where,
               (_l.get('text'), _l.get('partRows'), _l.get('cut')),
               ('$112.45 in car · too many answers', [1, 1], ''))
            eq('...and the stops under it inside the card at %s' % where,
               (_b.get('stopsCut'), _b.get('spill')), ([], []))
            no_('...and nothing scrolls at %s' % where, _b.get('over'))
            _r = _o.get('range') or {}
            eq('the pair range sits above the figures, unclipped at %s' % where,
               (_r.get('text'), _r.get('cut'), _r.get('above')),
               ('-$16 to $133/hr', '', True))
            ok_('...larger than the row\'s words at %s (%spx)' % (where, _r.get('px')),
                (_r.get('px') or 0) >= 16)
            _sm = _o.get('same') or {}
            eq('...and "%s" whole, on %s, once, at %s'
               % (_same1(h), 'the pair line' if h <= 380 else 'the address line under it', where),
               (_sm.get('text'), _sm.get('on'), _sm.get('both'), _sm.get('cut')),
               (_same1(h), 'stack' if h <= 380 else 'places', False, ''))
            if not (panel == '480x320' and view == 'scene'):
                eq('...with the pair row, the verdict and the figures inside the card at %s'
                   % where, (_r.get('rowIn'), _o.get('spill')), (True, []))
            _d = _o.get('det') or {}
            eq('...and in one line while an offer is up at %s' % where,
               (_d.get('text'), _d.get('rows'), _d.get('cut'), (_o.get('next') or None)),
               ('· In car $112.45 · ▸ Dave\'s Hot Chicken (1985 Cobb Parkway NW, STE 100) '
                '· too many answers', 1, '', None))
            no_('...and nothing scrolls with the offer up at %s' % where, _o.get('over'))
            # The Took button once its card has gone, with the widest age it
            # says, "59m ago": the bar keeps its six, and every letter of
            # the label and the age is inside the button wherever the bar has
            # the width for six labels (see 'the fullest bar carries six
            # controls': 470px).
            eq('a Took that says its age keeps the bar at six controls at %s (%r)'
               % (where, _t.get('text')), (_t.get('count'), _t.get('over')), (6, False))
            ok_('...saying the age (%r) at %s' % (_t.get('text'), where),
                (_t.get('text') or '').endswith('59m ago'))
            ok_('...in type no smaller than the panel\'s floor at %s (%spx; bar %spx tall)'
                % (where, _t.get('agoPx'), _t.get('barH')),
                (_t.get('agoPx') or 0) >= (15 if h >= 400 else 12) - 0.05)
            if (_t.get('width') or 0) >= 470:
                eq('...every letter of it inside the button at %s (bar %spx)'
                   % (where, _t.get('width')), _t.get('cut'), '')
            # The age on a line of its own, and the bar one height whatever
            # the button says. On the end of the label it took the bar from
            # 55px to 74 or 93 between offers and back when a card came up,
            # every control on it moving under the driver's finger.
            # Inside its border, and pushing no line of the label above it
            # past the border either: glyphs outside it, the age's and then
            # any line's, top or bottom.
            eq('the Took age is whole inside its button at %s (%r)' % (where, _t.get('text')),
               (_t.get('agoCut'), _t.get('rowsOut')), ('', ''))
            _hs = [(hm.get(k) or {}).get('barH') for k in ('noTook', 'tookUp', 'took')]
            ok_('the bar is the same height with and without the Took age, at %s '
                '(none, card up, 59m: %r)' % (where, _hs),
                _hs[0] is not None and len(set(_hs)) == 1)
            _hs2 = [(hm.get(k) or {}).get('barH') for k in ('notSaved', 'inCar')]
            eq('...and when the Took says "not saved" or "in car", at %s (%r, %r)'
               % (where, (hm.get('notSaved') or {}).get('text'),
                  (hm.get('inCar') or {}).get('text')),
               (_hs2, (hm.get('notSaved') or {}).get('text'), (hm.get('inCar') or {}).get('text'),
                (hm.get('notSaved') or {}).get('cut'), (hm.get('inCar') or {}).get('cut'),
                (hm.get('notSaved') or {}).get('rowsOut'), (hm.get('inCar') or {}).get('rowsOut')),
               ([_hs[0]] * 2, 'Took $112.45 not saved', '✓ Took $112.45 in car',
                '', '', '', ''))

    # The card side moving, every form of it (DRIVE_FORMS), on the three
    # panels in both pictures: whole — every glyph of every part it draws
    # inside the card and on the glass, the line under the card inside its
    # row, no child of the card over its edge, nothing scrolling — and the
    # bar, the status row and the picture's column (the map, in Map view)
    # exactly where the parked card left them. With an offer up, the whole
    # card (the owner's decision of 17 Oct 2026): every part the parked card
    # draws, at its size, every notice, and nothing put away but the read
    # diagnostics and the route link (and below 1024x600 the working; on the
    # hat $/mi, the rate smaller under a notice, and the notice a
    # scroll); the ends a line each, the dropoff whole on its own, however
    # long the pickup — on the hat, one line. Between offers, the driving form:
    # larger, the detail out of sight, the first notice kept with a chip
    # counting the rest.
    _NOT_DECIDING = ('#detail .diag', '#stack .maplink')
    # DRIVE_MEASURE's `detail`, in its order.
    _DRIVE_DETAIL = ['#vMin', '#vMile', '#vPerMile', '#working', '#places', '#stops',
                     '#detail .diag', '#stack .maplink']
    for panel, w, h in PLANNER_PANELS:
        for view in ('screen', 'scene'):
            where = '%s, %s view' % (panel, view)
            hat = h <= 380
            for form, spec in DRIVE_FORMS.items():
                dm = got.get('%s %s drive %s' % (panel, view, form)) or {}
                _pk, _dr = dm.get('parked') or {}, dm.get('driving') or {}
                _offer = bool(spec.get('offer'))
                ok_('the card moving, "%s", was measured at %s (%s)'
                    % (form, where, 'the whole card' if _offer else 'the driving form'),
                    _pk and _dr and not _pk.get('moving') and not _pk.get('driving')
                    and _dr.get('moving') is _offer and _dr.get('driving') is not _offer)
                if not (_pk and _dr):
                    continue
                _pp, _dp = _pk.get('parts') or {}, _dr.get('parts') or {}
                _cut = {k: v['cut'] for k, v in _dp.items() if v and v.get('cut')}
                # On the 3.5" hat, with an offer up, the notice is what gives
                # way, as it is parked there ("a line and a bit plus a
                # scroll", live.html): every other part whole, and of the
                # notice its first row of chips in sight — or, where the
                # parked card had less than a row for it (the pair under the
                # notices beside the scene picture: 9px), no less than that.
                _wr, _pwr = _dr.get('warnRow'), _pk.get('warnRow') or {}
                _scrolls = hat and _offer and _wr is not None
                if _scrolls:
                    _cut.pop('chip', None)
                    _need = min(_wr.get('line') or 99, _pwr.get('h') or 99)
                    ok_('...on the 3.5" hat the notice shows a row of its chips, or what the '
                        'parked card gave it, the rest a scroll away (%spx for a %spx row, '
                        '%spx parked), "%s" at %s'
                        % (_wr.get('h'), _wr.get('line'), _pwr.get('h'), form, where),
                        (_wr.get('h') or 0) >= _need - 0.5)
                eq('the card moving, "%s", is whole, nothing clipped%s, at %s'
                   % (form, ' but the notice' if _scrolls else '', where),
                   (_cut, _dr.get('spill'), (_dr.get('detailRows') or 0) <= 1, _dr.get('over')),
                   ({}, [], True, False))
                _px = lambda m, k: (m.get(k) or {}).get('px')
                _smaller = sorted(k for k in _dp if _dp[k] and _pp.get(k)
                                  and _px(_dp, k) < _px(_pp, k) - 0.05)
                eq('...and the bar, the status row and the picture where they were at %s'
                   % where, _dr.get('layout'), _pk.get('layout'))
                _chips = _pk.get('chips') or []
                if _offer:
                    # Below the rig's own 1024x600 the working goes too (the
                    # sum from the figures to the headline; live.html says
                    # why), and on the hat the figures a notice puts away
                    # parked are back.
                    # On the hat $/mi as well, the pay over the miles beside
                    # it, and the rate at the parked pair's size under a
                    # notice.
                    _small = not (w >= 1000 and h >= 560)
                    _away = (_NOT_DECIDING + (('#working',) if _small else ())
                             + (('#vPerMile',) if hat else ()))
                    _larger = sorted(k for k in _dp if _dp[k] and _pp.get(k)
                                     and _px(_dp, k) > _px(_pp, k) + 0.05)
                    _gone = sorted(k for k in _pp if _pp[k] and not _dp.get(k)
                                   and not (_small and k == 'working')
                                   and not (hat and k == 'perMile'))
                    _hatSmall = hat and bool(_pk.get('chips'))
                    if _hatSmall:
                        _smaller = [k for k in _smaller if k != 'rate']
                    eq('...with the offer up, the whole card at the parked sizes: nothing the '
                       'parked card draws is gone, smaller or larger, at %s' % where,
                       (_gone, _smaller, _larger), ([], [], []))
                    # ...and the same-store note (server.js sameStoreOf) drawn
                    # moving wherever the form's pair carries one, whole (the
                    # cut check above): a fact the driver reads at a glance.
                    _sameWant = {'pair': _same1(h), 'long pickup pair': _same1(h),
                                 'two': _same2(h),
                                 'three': 'same store ①' if h <= 380 else 'same store as ①'}
                    if form in _sameWant:
                        eq('...the same-store note drawn moving as parked, "%s", at %s'
                           % (form, where),
                           ((_dp.get('same') or {}).get('text'), (_pp.get('same') or {}).get('text')),
                           (_sameWant[form], _sameWant[form]))
                    _pkd = _pk.get('detail') or []
                    eq('...every notice, and nothing out of sight but the read diagnostics and '
                       'the route link%s, at %s' % (' and the working' if _small else '', where),
                       (_dr.get('detail'), _dr.get('chips')),
                       ([s for s in _DRIVE_DETAIL if s not in _away
                         and (s in _pkd or s in ('#vMin', '#vMile', '#vPerMile'))], _chips))
                    # The pay, the minutes and the miles, wherever the card has
                    # them: on the hat a notice puts them away parked, and
                    # moving they are back.
                    eq('...the pay, the minutes, the miles%s drawn, at %s'
                       % ('' if hat else ' and $/mi', where),
                       [k for k in ('pay', 'min', 'mile') + (() if hat else ('perMile',))
                        if not _dp.get(k)], [])
                    # ...and the rate, at 6.5vw under a notice on the hat
                    # (31.2px at 480 wide; under a pair alone it keeps the
                    # parked 8vw), never under that, and still the largest
                    # type on the card.
                    if _hatSmall:
                        _big = max(_px(_dp, k) or 0 for k in _dp if k != 'rate' and _dp[k])
                        ok_('...the rate at no less than 6.5vw on the hat under a notice, '
                            'and the largest type on the card (%s→%spx, next %spx), at %s'
                            % (_px(_pp, 'rate'), _px(_dp, 'rate'), _big, where),
                            (_px(_dp, 'rate') or 0) >= min(0.065 * w, _px(_pp, 'rate') or 0) - 0.05
                            and (_px(_dp, 'rate') or 0) > _big)
                    _pl, _pkl = _dr.get('places'), _pk.get('places')
                    ok_('...the ends drawn wherever the parked card draws them, saying the '
                        'same, at %s' % where,
                        (_pl or {}).get('text') == (_pkl or {}).get('text'))
                    if _pl and not hat:
                        _e = _pl.get('ends') or []
                        eq('...a line each, inside the card, the dropoff whole on its own '
                           'line (%s), at %s'
                           % (' | '.join('%s %spx%s' % (x.get('text'), x.get('px'),
                                                        '' if x.get('whole') else ' cut')
                                         for x in _e), where),
                           (_pl.get('rows'), len(_e), [x.get('inCard') for x in _e],
                            _e[-1].get('whole') if _e else None,
                            [x.get('px') for x in _e] == [(_pkl.get('ends') or [{}])[0].get('px')] * 2),
                           (2, 2, [True, True], True, True))
                        # A cut end says so, with an ellipsis in its own box;
                        # and the owner's long pickup is cut, so that is asked.
                        eq('...each end cut only with an ellipsis, the long pickup cut, at %s'
                           % where,
                           ([x.get('text') for x in _e if not x.get('whole')
                             and not x.get('ellipsis')],
                            bool(_e) and _e[0].get('text') == LONG_ENDS[0]
                            and _e[0].get('whole')),
                           ([], False))
                    elif _pl:
                        eq('...on the 3.5" hat, the one line it has parked, at %s' % where,
                           _pl.get('rows'), _pkl.get('rows'))
                else:
                    # A part the parked card does not draw counts as larger where
                    # the driving one does.
                    _not = sorted(k for k in spec['larger']
                                  if not (_dp.get(k) and (not _pp.get(k)
                                                          or _px(_dp, k) > _px(_pp, k) + 0.05)))
                    eq('...larger than the normal form at %s (%s)'
                       % (where, ', '.join('%s %s→%s' % (k, _px(_pp, k), _px(_dp, k))
                                           for k in spec['larger'])),
                       (_not, _smaller), ([], []))
                    eq('...the detail out of sight, the first notice and a count of the rest '
                       'kept, at %s' % where,
                       (_dr.get('detail'), _dr.get('chips')),
                       ([], _chips[:1] + (['+%d more' % (len(_chips) - 1)] if len(_chips) > 1 else [])))

                if not spec.get('way'):
                    continue
                # The answer on the card over this pair, every form of it
                # (WAY_FORMS), parked and driving: the call and the part that
                # may not be cut whole and in the card, one row — and the card
                # run no further past its border than the same card with the
                # line put away. That is "nothing past it" wherever the card
                # fitted without the line, which is every form but the pair
                # beside the scene picture on the 3.5" hat, parked: that card
                # was over by 17px before there was a line (the open entry on
                # the pair line in AUDITS.md, "about 9 px past the card"), and
                # the line may not make it worse.
                _wp, _wd = dm.get('wayParked') or {}, dm.get('wayDriving') or {}
                for _state, _ws in (('parked', _wp), ('driving', _wd)):
                    _was = _ws.pop('__without', None)
                    eq('every form of the card line was measured over "%s", %s, at %s'
                       % (form, _state, where), sorted(_ws),
                       sorted(n for n, _a, _e in WAY_FORMS))
                    _bad = sorted(
                        n for n, m in _ws.items()
                        if not m.get('kept') or m['kept'][0]['text'] not in (
                            'ON THE WAY', 'OUT OF THE WAY', "CAN'T TELL", 'CHECKING THE ROUTE')
                        or not all(k['whole'] for k in m['kept']) or not m.get('inCard')
                        or m.get('rows') != 1
                        or not all(x.get('inCard') for x in m.get('more') or []))
                    eq('the card line is whole where it must be — the call, and the figure or '
                       'the refusal\'s state — and one row, in every form over "%s", %s, at %s'
                       % (form, _state, where), _bad, [])
                    _past = sorted((n, m.get('over')) for n, m in _ws.items()
                                   if _was is None or (m.get('over') or 0) > _was + 0.5)
                    eq('...and the card runs no further past its border with it than without '
                       'it (%spx), every form, over "%s", %s, at %s'
                       % (_was, form, _state, where), _past, [])
                # Moving with the pair up the card is the parked card, so the
                # line is the parked line's size (it was larger in the driving
                # form, when the rows round it were put away).
                _small = sorted(n for n in _wp if n in _wd
                                and abs((_wd[n].get('px') or 0) - (_wp[n].get('px') or 0)) > 0.05)
                eq('...and every form at its parked size moving, over "%s" at %s (%s→%s)'
                   % (form, where, (_wp.get('checking') or {}).get('px'),
                      (_wd.get('checking') or {}).get('px')), _small, [])

    # ...and with the notice up as well: the journal dead and the phone too
    # bright, which between offers is the card's other occupant and the item
    # that gives way. The stops are `flex: none`, so on the 3.5" hat they took
    # its room — measured here with the panel's fold switched off: the notice
    # needs 139px in the scene picture and had 121 of them on the glass, and
    # 17 with the four stops under it; in the screen picture 93 of 93, then 38.
    # Now the stops fold first, a line at a time into
    # "+ N more stops", down to one line counting them, and the notice keeps
    # what it had but that one line — which on a notice too long for the card
    # even alone is a line it was not showing in full anyway.
    _FLOOR = re.compile(r'^▸ (\d+) stops?: no room to list$')
    _MORE = re.compile(r'^\+ (\d+) more stops?$')
    for panel, w, h in PLANNER_PANELS:
        for view in ('screen', 'scene'):
            where = '%s, %s view' % (panel, view)
            pm = got.get('%s %s planner notice' % (panel, view)) or {}
            was, now = pm.get('before') or {}, pm.get('after') or {}
            ok_('the Trip Planner\'s stops were measured beside the notice at %s' % where,
                (was.get('warn') or {}).get('shown') and now.get('shown'))
            if not ((was.get('warn') or {}).get('shown') and now.get('shown')):
                continue
            _texts = [l['text'] for l in now.get('lines') or []]
            _listed = sum(1 for t in _texts if re.match(r'^▸ (Pickup|Dropoff)\b', t))
            _counted = sum(int(m.group(1)) for m in (_MORE.match(t) or _FLOOR.match(t)
                                                     for t in _texts) if m)
            eq('...every stop listed or counted with the notice up at %s (%r)'
               % (where, _texts), _listed + _counted, len(PLANNER_STOPS))
            _ww, _wn = was.get('warn') or {}, now.get('warn') or {}
            _whole = _wn.get('need', 0) <= _wn.get('client', 0) + 1
            _floor = len(_texts) == 1 and bool(_FLOOR.match(_texts[0]))
            ok_('...and the notice shows all it says, or the stops are down to the one '
                'line that counts them, at %s (notice %s of %spx; %d lines)'
                % (where, _wn.get('client'), _wn.get('need'), len(_texts)),
                _whole or _floor)
            ok_('...and the notice keeps what it showed without them, less that one '
                'line at most, at %s (%spx before, %spx after, the line %.1fpx)'
                % (where, _ww.get('client'), _wn.get('client'), now.get('cost') or 0),
                _wn.get('client', 0) >= min(_ww.get('client', 0), _wn.get('need', 0))
                - (now.get('cost') or 0) - 1 if _floor
                else _wn.get('client', 0) >= min(_ww.get('client', 0), _wn.get('need', 0)) - 1)
            eq('...each stop line still whole where it may not be cut at %s' % where,
               [(l['text'][:24], l['cut']) for l in now.get('lines') or [] if l.get('cut')],
               [])
            # Where the card has room for both, nothing is given up: the fold
            # answers the notice being cut, not the notice being there.
            if panel != '480x320':
                eq('...and where the card has room for both, all four stops and the '
                   'line under them at %s' % where, len(_texts), 5)

    # ...and under the camera's word. Its line is red and says what to do —
    # reseat the cable, turn the phone up — and a rig that cannot see has no
    # verdict to show, so the line is the card's whole message; the stops give
    # way to it on the rule they give way to any notice by. Held to the same
    # floor: the line whole, or the stops down to the one line counting them,
    # and the line keeping what it had without them less that one line.
    # Measured: whole beside all four stops and the note at 800x480 and
    # 1024x600 in both pictures, and on the 3.5" hat's screen picture with the
    # stops down to their one line (93 of 93px). With the fold switched off the
    # hat's line kept 47 of 93px in the screen picture and 26 in the scene one.
    # The scene picture on the hat is short of room for this line with no
    # stops at all — 130px of the 139 the dark line needs, of the 162 the
    # stalled one does — which is the line's own, not the stops'. The line was
    # measured whole only in the phone layout (rpi/test_dashboard.py, a rig
    # that cannot see), which is the screen picture's.
    _BLIND_WORD = {'dark': 'TOO DARK TO BE SURE', 'stalled': 'CAMERA STALLED'}
    for panel, w, h in PLANNER_PANELS:
        for view in ('screen', 'scene'):
            for word in PLANNER_BLIND:
                where = '%s, %s view, %s' % (panel, view, word)
                pm = got.get('%s %s planner blind %s' % (panel, view, word)) or {}
                was, now = pm.get('before') or {}, pm.get('after') or {}
                ok_('the Trip Planner\'s stops were measured under the camera\'s word '
                    'at %s' % where, (was.get('warn') or {}).get('shown') and now.get('shown'))
                if not ((was.get('warn') or {}).get('shown') and now.get('shown')):
                    continue
                _texts = [l['text'] for l in now.get('lines') or []]
                _listed = sum(1 for t in _texts if re.match(r'^▸ (Pickup|Dropoff)\b', t))
                _counted = sum(int(m.group(1)) for m in (_MORE.match(t) or _FLOOR.match(t)
                                                         for t in _texts) if m)
                eq('...every stop listed or counted under it at %s (%r)' % (where, _texts),
                   _listed + _counted, len(PLANNER_STOPS))
                _ww, _wn = was.get('warn') or {}, now.get('warn') or {}
                _floor = len(_texts) == 1 and bool(_FLOOR.match(_texts[0]))
                ok_('...and its line shows all it says, or the stops are down to the '
                    'one line that counts them, at %s (line %s of %spx; %d lines)'
                    % (where, _wn.get('client'), _wn.get('need'), len(_texts)),
                    _wn.get('need', 0) <= _wn.get('client', 0) + 1 or _floor)
                ok_('...and its line keeps what it showed without them, less that one '
                    'line at most, at %s (%spx before, %spx after, the line %.1fpx)'
                    % (where, _ww.get('client'), _wn.get('client'), now.get('cost') or 0),
                    _wn.get('client', 0) >= min(_ww.get('client', 0), _wn.get('need', 0))
                    - ((now.get('cost') or 0) if _floor else 0) - 1)
                eq('...and the word itself, in the card, at %s' % where,
                   (pm.get('label'), now.get('labelIn')), (_BLIND_WORD[word], True))

    for panel, w, h in PANELS:
        dashboard = w > h and h <= 620
        for name in PAGES:
            r = got.get('%s %s' % (panel, name))
            ok_('%s at %s was measured' % (name, panel), r is not None)
            if not r:
                continue

            # scan.js sends a device with no camera to live.html deliberately.
            # If that fires here the numbers below are live.html's twice over,
            # and the scanner has not been measured at all.
            eq('%s at %s is the page that was asked for' % (name, panel),
               r['landed'], name)

            # A page that scrolls down is a small nuisance. A page that scrolls
            # sideways is one where the driver cannot find the controls.
            eq('%s at %s does not scroll sideways' % (name, panel),
               r['scrollW'] <= r['clientW'] + 1, True)
            # map.html fits every panel with the room for it, and scrolls on
            # the 3.5" hat alone. 320px of glass has to carry a header, NINE
            # controls — the `when` box is the ninth — and a consent notice
            # that may
            # not be hidden — it is what makes sending somebody's address a
            # decision rather than a surprise. Re-measured on the real page
            # rather than decremented: at 480x320 the bar is 151px and the
            # document scrolls to 362 against a 320px screen, both before and
            # after the ninth control. What is left for the map is about forty
            # pixels, and a forty-pixel map is not a map. Scrolling
            # is the honest answer there, the same one the offer log gives
            # everywhere; the panels a driver actually bolts this to are still
            # held to the glass.
            may_scroll = name in SCROLLS or (name == 'map.html' and h < 400)
            if not may_scroll:
                eq('%s at %s fits the glass' % (name, panel),
                   r['scrollH'] <= r['clientH'] + 1, True)

            # The floor is what somebody can read from the driving seat. The
            # panel is roughly twice as far away as a phone, so it is higher
            # there; the phone keeps the size it was designed at.
            # 15px on a panel with the room, because the driving seat is
            # roughly twice as far from the glass as a hand is from a phone.
            # The 3.5" hat is 320px tall and cannot afford it: raised there,
            # the keypad's own labels pushed the page past the bottom of its
            # glass, and a control out of reach is worse than a label leaned
            # in for. One number does not fit both, so this does not pretend it
            # does. The phone keeps the size it was designed at.
            floor = (15 if h >= 400 else 12) if dashboard else 9
            ok_('%s at %s has nothing smaller than %dpx (%.4gpx in %s)'
                % (name, panel, floor, r['smallest'], r['smallestIn']),
                r['smallest'] >= floor)

            # 44px is the floor both platform guidelines give, and it is not a
            # preference here: these are pressed one-handed, on glass, by
            # somebody who has just parked.
            if r['shortest'] is not None:
                ok_('%s at %s keeps every control at %dpx (%.4gpx in %s)'
                    % (name, panel, 52 if h >= 400 else 44,
                       r['shortest'], r['shortestIn']),
                    r['shortest'] >= (51.5 if h >= 400 else 43.5))

            # The scanner's four fixed layers, in order, with nothing drawn on
            # top of anything. A grid whose column count went out of step with
            # its markup put the controls over the status line at every size
            # this rig ships on, and the page still rendered.
            phone = got.get('%s phoneview' % panel)
            if name == 'live.html' and phone:
                # The mode has to reach the rig, and it travels on the request
                # for a frame — there is no other call. A src that does not
                # carry it is a button that changes the layout and nothing else.
                ok_('the phone view asks the rig for the phone at %s (%s)'
                    % (panel, phone['src'][:48]), 'view=screen' in phone['src'])
                eq('...and says it is a mode, not a link, at %s' % panel,
                   phone['pressed'], 'true')
                # The label names what pressing it gets you, or the driver
                # presses it to leave a view they are already in.
                ok_('...and offers the way back at %s (%r)' % (panel, phone['label']),
                    'Scene' in phone['label'])
                ok_('the phone view does not overflow the glass at %s' % panel,
                    not phone['over'])
                # ...and with every control on the bar at once, which is the
                # state a driver is in exactly when it matters: a card on screen
                # while a job is already in the car.
                bar = phone.get('bar') or {}
                plain, full = bar.get('plain') or {}, bar.get('full') or {}
                # With two conditional buttons up the bar holds six, which fits,
                # so nothing stands down. It used to be seven here — ⟳ Re-find
                # was a third always-on control — and the keypad link went for
                # every pair. Re-find is gone at the owner's request, and a rule
                # still shedding at six would cost the driver a control for
                # nothing.
                eq('a bar with two conditionals keeps all six at %s (bar %spx)'
                   % (panel, full.get('width')),
                   full.get('count'), 6)
                ok_('...the keypad link among them, at %s (%r)'
                    % (panel, full.get('labels')),
                    any('Type' in l for l in (full.get('labels') or [])))
                ok_('...and still fits the glass at %s' % panel,
                    not bar.get('over'))
                ok_('...with every control still 44px tall at %s (%.4gpx)'
                    % (panel, full.get('shortest') or 0),
                    (full.get('shortest') or 0) >= 43.5)
                # The "boxes sent" line, up over the phone view: every control
                # on the bar keeps the width it has without it — that width is
                # its floor here, whatever the panel gives it.
                _sh = phone.get('sentHint') or {}
                _was = dict(_sh.get('was') or [])
                _narrowed = [(k, _was.get(k), w) for k, w in (_sh.get('now') or [])
                             if k in _was and w < _was[k] - 0.5]
                ok_('the "boxes sent" hint never narrows a bar control below its floor, '
                    'at %s (%r)' % (panel, _narrowed or _sh.get('now')),
                    _sh.get('said', '').startswith('boxes sent') and _sh.get('phone')
                    and len(_sh.get('now') or []) == len(_was) and not _narrowed)
                # Against the bar as it stood before, not against an empty one.
                #
                # Some labels already overrun their buttons on the narrowest
                # panels — "Set box" wants 78px and a 280px bar gives it 48 —
                # and that predates any of this. What must not happen is the new
                # control making it worse. Measured in the same browser at the
                # same size a moment apart, so the comparison is like for like.
                before = bar.get('before') or {}
                fresh = [c for c in (full.get('clipped') or [])
                         if c not in (before.get('clipped') or [])]
                eq('...clipping no label the bar did not already clip at %s '
                   '(%d before, %d now)'
                   % (panel, len(before.get('clipped') or []),
                      len(full.get('clipped') or [])),
                   fresh, [])
                # ...and the four fixed controls are clean wherever the bar is
                # not being squeezed, which is what says the squeeze is the
                # cause rather than the labels being too long everywhere.
                if (plain.get('width') or 0) >= 400:
                    eq('...with the four fixed controls clipping nothing at %s'
                       % panel, plain.get('clipped'), [])
                # The widest this bar ever gets, and an absolute claim rather
                # than a comparative one.
                #
                # Every check above is "no worse than before", which is the
                # right shape for a feature landing on a crowded bar and the
                # wrong shape for the bar itself: it passed all of them while
                # the 7" panel this rig is bolted to painted "ok $12.4" over
                # the gap beside the button. Six controls, the longest label
                # the Took button can hold, and nothing outside its own box —
                # on every panel with the room for it.
                #
                # 470px is not a threshold with an opinion. Below it the bar is
                # the 3.5" hat's or a phone's, where no type size fits six
                # labels and the trade is a documented one; above it are the
                # four landscape panels, whose bars measure 507, 567, 663 and
                # 804px beside the picture.
                crowded = bar.get('crowded') or {}
                eq('the fullest bar carries six controls at %s (bar %spx)'
                   % (panel, crowded.get('width')), crowded.get('count'), 6)

                # THE WAY TO THE OFFER LOG SURVIVES EVERY STATE OF THIS BAR.
                #
                # It did not. ▤ Offers was grouped with the keypad as a
                # "read parked" link and shed by the rule above — which fires
                # when an order is in the car or a card is being screened, so
                # the only route to the log left the screen for the whole of a
                # shift and came back when the car was empty. The driver could
                # not get to their offers page and the bar looked fine, because
                # what was checked was how many controls survived and never
                # which.
                #
                # All four states, not just the fullest: the fault was that one
                # particular state hid it, and a check that only looks at the
                # widest bar would have missed exactly this one.
                for _state in ('plain', 'before', 'full', 'crowded'):
                    _labels = (bar.get(_state) or {}).get('labels') or []
                    ok_('the way to the offers page is on the bar in "%s" at '
                        '%s (%r)' % (_state, panel, _labels),
                        any('Offers' in l for l in _labels))
                # ...and what gives way in the one state that needs something
                # to: the keypad link, and nothing else.
                _crowded_labels = crowded.get('labels') or []
                no_('...and ⌨ Type is what stands down for it at %s (%r)'
                    % (panel, _crowded_labels),
                    any('Type' in l for l in _crowded_labels))
                # ▣ SET BOX IS ON THE GLASS IN EVERY STATE OF THIS BAR.
                #
                # It was not. With ⟳ Re-find on the bar the fullest state was
                # seven, and ▣ Set box was the control that stood down for it —
                # so with a card on screen, an order in the car and ⌖ Dropoff
                # up, the one control that fixes the boxes was not there to
                # press. The owner's report was that the box "tends to get stuck
                # and not let me set it". Re-find was taken off the bar at their
                # request; Set box stays in all four states, and no state may
                # bring Re-find back.
                for _state in ('plain', 'before', 'full', 'crowded'):
                    _labels = (bar.get(_state) or {}).get('labels') or []
                    ok_('▣ Set box is on the bar in "%s" at %s (%r)'
                        % (_state, panel, _labels),
                        any('Set box' in l for l in _labels))
                    no_('...and there is no ⟳ Re-find on it in "%s" at %s'
                        % (_state, panel),
                        any('Re-find' in l for l in _labels))
                ok_('...each still 44px tall at %s (%.4gpx, bar %spx tall)'
                    % (panel, crowded.get('shortest') or 0, crowded.get('height')),
                    (crowded.get('shortest') or 0) >= 43.5)
                if (crowded.get('width') or 0) >= 470:
                    eq('...with every label inside its own button at %s'
                       % panel, crowded.get('spilling'), [])
                    # ...and ⌖ answering a press: "reading…", "not read", and
                    # the refused press at the restaurant ('⌖ a pickup').
                    eq('...and with each of ⌖\'s answers on its face at %s' % panel,
                       [(f, s) for f, s in bar.get('answers') or [] if s],
                       [])
                    eq('...the refused press\'s face among them, read off the page at %s'
                       % panel, [f for f, _s in bar.get('answers') or []][2:],
                       ['⌖ a pickup'])

                # --- 📷 Snap ------------------------------------------------
                snap_checks(panel, phone.get('snap') or {})
                # ...which is a weaker claim than it looks, and was the one
                # being made. #app clips, so a picture drawn taller than its
                # row is trimmed rather than overflowed and every fits-check
                # goes on passing. `max-height: 100%` was resolving against a
                # wrapper sized to its own contents, so it resolved to nothing
                # and 109px came off the top of the phone at 800x480 — the top
                # being where the payout is.
                #
                # Asserted rather than guarded on. A broken image has no shape
                # to clip and would pass a cut-check by having nothing to cut,
                # which is how the picture came to be measured at 2px in the
                # first place — so "there was a picture here" is the first
                # thing to establish and not a precondition to skip on.
                ok_('there is a picture to measure at %s' % panel,
                    phone['loaded'] and phone['sceneLoaded'])
                ok_('...and nothing is cut off the phone at %s '
                    '(%.0f top, %.0f bottom, %.0f left, %.0f right)'
                    % (panel, phone['cutTop'], phone['cutBottom'],
                       phone['cutLeft'], phone['cutRight']),
                    max(phone['cutTop'], phone['cutBottom'],
                        phone['cutLeft'], phone['cutRight']) <= 1)
                ok_('...nor off the scene at %s (%.0fpx)'
                    % (panel, phone['sceneCut']), phone['sceneCut'] <= 1)
                # The picture on the LEFT of the card, every landscape panel,
                # in all three things the pane shows — the owner's, 21 Oct:
                # "Could you swap the camera/phone feed to the left side of the
                # screen? I use the touch screen as a magnifying glass to read
                # my phone while it is in the mount." The panel is on the
                # driver's right, so its left is the near side. Upright, the
                # pane stays under the card, where it always was.
                for _what, _s in (('the phone', phone.get('side')),
                                  ('the scene', phone.get('sceneSide')),
                                  ('the map beside a card', phone.get('mapSide'))):
                    _s = _s or {}
                    if w > h:
                        ok_('%s is left of the card at %s (%r)' % (_what, panel, _s),
                            _s.get('picW', 0) > 50 and _s.get('cardW', 0) > 50
                            and _s.get('picR', 9999) <= _s.get('cardL', 0) + 1)
                    else:
                        ok_('%s is under the card, upright, at %s (%r)' % (_what, panel, _s),
                            _s.get('picW', 0) > 50
                            and _s.get('picT', 0) >= _s.get('cardB', 9999) - 1)
                # ...and the other direction, which is now the one that takes a
                # press. The mount still has to be aimed sometimes, and a
                # toggle that only travels one way is a driver stuck in the
                # view they did not want — starting with being able to press it
                # at all, which a picture drawn over the bar takes away.
                ok_('the view toggle can be pressed at %s' % panel,
                    phone['reachable'])
                ok_('the scene view is a press away at %s (%s)'
                    % (panel, phone['sceneSrc'][:48]),
                    'view=scene' in phone['sceneSrc'])
                eq('...and the button lets go at %s' % panel,
                   phone['scenePressed'], 'false')
                # The cycle is screen → scene → map → screen, so what the scene
                # offers next is the map. A third mode on this control rather
                # than another button in the bar: the bar holds six, and the
                # fullest state already has six in it.
                ok_('...and offers the map next at %s (%r)'
                    % (panel, phone['sceneLabel']),
                    'Map' in phone['sceneLabel'])

                # --- the map mode ---------------------------------------
                #
                # Leaflet is fetched from a CDN this box cannot reach, which is
                # the ordinary case for a rig on a hotspot rather than an
                # artefact of the harness. What has to hold offline is that the
                # pane says so and the driver is not stranded there.
                ok_('the view toggle is still reachable on the map at %s' % panel,
                    phone['mapReachable'])
                ok_('the map takes the pane at %s' % panel, phone['mapShown'])
                # Both at once is the failure a swap exists to avoid: two dense
                # images over each other in a 269px-wide pane make neither
                # readable, and the picture's whole job is letting the numbers
                # be checked against what the card said.
                ok_('...instead of the picture, not over it at %s' % panel,
                    not phone['mapImgShown'])
                ok_('...and says what happened rather than showing a grey box '
                    'at %s (%r)' % (panel, phone['mapNote'][:60]),
                    len(phone['mapNote']) > 10)
                # Said where it can be READ. The caption is hidden outright on a
                # dashboard panel — "camera view · inset is what the reader
                # sees" is a label on a picture that says what it is — and the
                # map's line is not that: it is the answer the driver switched
                # modes to get. Hidden with the rest, the mode ships with its
                # conclusion invisible on the one screen it is for.
                ok_('...on the glass rather than hidden with the caption at %s '
                    '(%.0fpx)' % (panel, phone['mapNoteH']),
                    phone['mapNoteH'] > 8)
                # The assertion the whole dashboard layout exists to make. A
                # map that overflows its row pushes the bar of controls off the
                # glass, and a driver is not going to scroll.
                ok_('...without pushing anything off the glass at %s' % panel,
                    not phone['mapOver'])
                if dashboard:
                    _bw = phone.get('between') or {}
                    ok_('between offers the map takes the whole width, the empty card '
                        'gone, nothing pushed off the glass, at %s (%r)' % (panel, _bw),
                        _bw.get('on') and not _bw.get('live') and not _bw.get('over')
                        and _bw.get('mapW', 0) >= _bw.get('barW', 1) - 2
                        and _bw.get('offerMapW', 9999) < _bw.get('mapW', 0))
                    ok_('...taking the row rather than a fixed 240px at %s '
                        '(%.0fpx of %.0f)'
                        % (panel, phone['mapH'], phone['mapRowH']),
                        phone['mapH'] > 120)

                # --- the caption's budget -------------------------------
                #
                # Everything above measures the ONE sentence this offline
                # harness happens to land on. The row is the map's other
                # occupant and it can say a hundred and three things, so all
                # of them are put in it and measured. Three rules, and they are not the same
                # rule asked three ways:
                #
                #   the cap    — no sentence may take more rows than the clamp
                #                allows, which is what keeps the map's floor;
                #   the words  — on the panels the rig ships on, the cap must
                #                never actually bite, because a sentence cut
                #                short is a sentence rewritten by the layout;
                #   the order  — where it does bite, on the 3.5" hat, only a
                #                trailing `·` clause may go. The figure, the
                #                straight-line warning and the age of the fix
                #                are what a driver acts on, and a hedge clipped
                #                off a number is this project's first fault.
                shots = phone.get('caption') or {}
                eq('every caption sentence was measured at %s' % panel,
                   sorted(row[0] for row in CAPTION_LINES
                          if row[0] not in shots), [])
                # Two rows, three on the hat — see CAPTION_LINES for where both
                # numbers come from. Held in pixels off the row the panel
                # actually drew rather than off a font size in the stylesheet.
                cap = 3 if h <= 380 else 2
                # ...and the page applies that same number. Without this, `cap`
                # is the same question answered in two places with nothing
                # tying them together: the suite could say 2 while the
                # stylesheet said 4 and every check here would still pass.
                # Landscape only, because the rule lives in a landscape query.
                if w > h:
                    _st = phone.get('captionStyle') or {}
                    eq('the caption row is clipped rather than spilling at %s'
                       % panel, _st.get('overflow'), 'hidden')
                    eq('...and the clamp the page applies is that same cap at %s'
                       % panel, (_st.get('clamp') or '').strip(), str(cap))
                tall = [(row[0], shots[row[0]]['rows']) for row in CAPTION_LINES
                        if row[0] in shots and shots[row[0]]['rows'] > cap]
                eq('no caption sentence takes more than %d rows at %s'
                   % (cap, panel), tall, [])
                worst = max([shots[row[0]]['h'] for row in CAPTION_LINES
                             if row[0] in shots] or [0])
                floor = min([shots[row[0]]['mapH'] for row in CAPTION_LINES
                             if row[0] in shots] or [0])
                ok_('...so the map keeps its floor whatever is said at %s '
                    '(caption %dpx worst, map %dpx)' % (panel, worst, floor),
                    floor > 120)
                cut = [row[0] for row in CAPTION_LINES
                       if row[0] in shots and shots[row[0]]['clipped']]
                if h > 380:
                    ok_('...and nothing is cut short at %s (%s)'
                        % (panel, ', '.join(cut) or 'none'), not cut)
                for name, _text, keep in CAPTION_LINES:
                    if name not in shots:
                        continue
                    # The figure and every hedge on it, readable, on every
                    # panel. What a clamp is allowed to eat is declared in the
                    # table above and linted there to be a whole trailing
                    # clause; this is where it is held to.
                    ok_('...and %r is readable as far as its last hedge at %s '
                        '(%r)' % (name, panel, shots[name]['visible'][-28:]),
                        shots[name]['visible'].startswith(keep))
                # ...and each refusal as the chip the page draws it as
                # (CAPTION_CHIPS): that chip and no other, every other form
                # none; the chip whole — every word on the glass, nothing
                # clamped, its outline inside the row — inside the same cap,
                # the map keeping its floor under it, and the sentence on its
                # title.
                eq('every caption form draws the chip it is expected to, or none, at %s'
                   % panel,
                   sorted((row[0], shots[row[0]].get('chip')) for row in CAPTION_LINES
                          if row[0] in shots
                          and shots[row[0]].get('chip') != CAPTION_CHIPS.get(row[0])), [])
                for name, text, _keep in CAPTION_LINES:
                    if name not in CAPTION_CHIPS or name not in shots:
                        continue
                    _cs = shots[name].get('chipShot') or {}
                    eq('...the chip for %r whole, in %d rows at most, the map over 120px, '
                       'the sentence on its title, at %s' % (name, cap, panel),
                       (_cs.get('visible'), _cs.get('clipped'), _cs.get('chipOut'),
                        (_cs.get('rows') or 99) <= cap, (_cs.get('mapH') or 0) > 120,
                        shots[name].get('chipTitle')),
                       (CAPTION_CHIPS[name], False, False, True, True, text))
                # --- the "you are here" label ---------------------------
                #
                # Over the map's top-right corner, so it costs the caption
                # none of its rows and the map none of its floor. What has to
                # hold is that every form of it is on the map, clear of the
                # zoom buttons, whole, and short enough to read at a glance.
                # Leaflet's zoom buttons, pressed at a red light: 48px on
                # every panel, the hat's map included (see the rule in
                # live.html), with the label and the key held clear below.
                _zm = phone.get('zoom') or {}
                eq('Leaflet\'s zoom buttons are 48px at %s' % panel,
                   (_zm.get('w'), _zm.get('h')), (48, 48))
                here = phone.get('here') or {}
                eq('every "you are here" form was measured at %s' % panel,
                   sorted(name for name, _t in LIVE_HERE_LINES if name not in here), [])
                for name, _t in LIVE_HERE_LINES:
                    m = here.get(name) or {}
                    ok_('the "you are here" %r sits inside the map at %s (%r)'
                        % (name, panel, m), m.get('inside'))
                    ok_('...clear of the zoom buttons at %s' % panel,
                        m.get('clearOfZoom'))
                    ok_('...in two rows at most, nothing spilling, at %s (%r)'
                        % (panel, (m.get('rows'), m.get('spills'))),
                        (m.get('rows') or 9) <= 2 and not m.get('spills'))
                # --- the key to how each place was found ----------------
                #
                # One line across the map's foot, in a glance: grey, colour,
                # hollow and the circle. On the 3.5" hat the map is 228px
                # wide and the whole key 270px, so there it drops two words;
                # what has to hold on every panel is that the form it gets
                # is one row, whole, on the map, below the zoom buttons.
                key = phone.get('key') or {}
                ok_('the map\'s key sits inside the map, below the zoom buttons, at %s (%r)'
                    % (panel, key), key.get('inside') and key.get('belowZoom'))
                ok_('...in one row, nothing cut, at %s (%r)'
                    % (panel, (key.get('rows'), key.get('spills'), key.get('w'), key.get('mapW'))),
                    key.get('rows') == 1 and not key.get('spills'))
                eq('...saying the circle, the pin, the grey and the hollow at %s' % panel,
                   key.get('text'),
                   "◯ reach · PD · ● found · ○ outside" if h <= 380
                   else "◯ card's reach · PD pin · ● also found · ○ outside")
                # ...and with the held order's pickup in it: one row and the
                # short words on every panel but the hat, which has 206px of
                # room for 293px of words and takes two rows, and only there.
                key = phone.get('keyHeld') or {}
                ok_('the key with the held pickup in it sits inside the map, below the '
                    'zoom buttons, in %s, nothing cut, at %s (%r)'
                    % ('two rows' if h <= 380 else 'one row', panel,
                       (key.get('rows'), key.get('spills'), key.get('w'), key.get('mapW'))),
                    key.get('inside') and key.get('belowZoom')
                    and key.get('rows') == (2 if h <= 380 else 1) and not key.get('spills'))
                eq('...saying the held pickup with the rest at %s' % panel, key.get('text'),
                   "◯ reach · PD%s · ● found · ○ outside · P held pickup"
                   % ('' if h <= 380 else ' pin'))
                # ...and with the order in the car's own marks in it as well —
                # its run, the extra, the numbered stops (drawMap) — beside the
                # held pickup: every item it can name at once. Two rows at
                # most, on every panel: the hat's measured two with the held
                # pickup are not exceeded.
                key = phone.get('keyRun') or {}
                ok_('the key with the run, the extra and the numbered stops in it sits '
                    'inside the map, below the zoom buttons, in two rows at most, nothing '
                    'cut, at %s (%r)'
                    % (panel, (key.get('rows'), key.get('spills'), key.get('w'), key.get('mapW'))),
                    key.get('inside') and key.get('belowZoom')
                    and 1 <= (key.get('rows') or 9) <= 2 and not key.get('spills'))
                eq('...saying them after the rest at %s' % panel, key.get('text'),
                   "◯ reach · PD%s · ● found · ○ outside · P held pickup · ━ run · ━%s · ┅ extra "
                   "· 12%s" % (('', '', '') if h <= 380 else (' pin', ' offer', ' order')))
                key = phone.get('keyFailed') or {}
                ok_('the key saying how each place was found was not drawn sits inside '
                    'the map, below the zoom buttons, in one row, nothing cut, at %s (%r)'
                    % (panel, key),
                    key.get('inside') and key.get('belowZoom') and key.get('rows') == 1
                    and not key.get('spills')
                    and key.get('text') == 'how each was found: not drawn')
                # --- what a mark says, pointed at -------------------------
                tip = phone.get('tip') or {}
                ok_('a mark\'s longest reason sits inside the map, every word of it '
                    'readable, nothing spilling, at %s (%r)' % (panel, tip),
                    tip.get('inside') and tip.get('whole') and not tip.get('spills'))

                # ...and the way out. A cycle that cannot be completed is worse
                # than a toggle: the driver pressed once for a look and cannot
                # get the picture back.
                ok_('the cycle comes back to the phone at %s' % panel,
                    phone['backReachable'])
                ok_('...offering the scene again at %s (%r)'
                    % (panel, phone['backLabel']), 'Scene' in phone['backLabel'])
                ok_('...with the picture back at %s' % panel, phone['backImgShown'])
                ok_('...and the map put away at %s' % panel, not phone['backMapShown'])
                if dashboard and h >= 400:
                    # The whole point. A portrait phone in a landscape cell is
                    # bounded by height, so this only pays if it gets the
                    # height — and the picture it replaces was drawn at a third
                    # of the panel.
                    ok_('the phone fills the panel at %s (%.0fpx of %.0f)'
                        % (panel, phone['h'], phone['rowH']),
                        phone['h'] > phone['rowH'] * 0.85)
                    ok_('...taller than the row the scene view was boxed into '
                        'at %s (%.0fpx, was %.0f)' % (panel, phone['h'], phone['was']),
                        phone['h'] > phone['was'] + 40)
                elif dashboard:
                    # The 3.5" hat cannot afford that trade. Given every row,
                    # the picture left the verdict a 279px column in which the
                    # bar wrapped to 74px and a pair's stack line was painted
                    # under the connection line. There the bar takes the width
                    # back and the phone gets the verdict's row: 211px of 320,
                    # which is still the whole phone and still not less than
                    # the scene view's box.
                    ok_('the phone takes the verdict\'s row at %s (%.0fpx of %.0f)'
                        % (panel, phone['h'], phone['rowH']),
                        phone['h'] > phone['rowH'] * 0.6)
                    ok_('...and is no shorter than the scene view was boxed '
                        'at %s (%.0fpx, was %.0f)' % (panel, phone['h'], phone['was']),
                        phone['h'] >= phone['was'])

            # ...and the subject of the page gets a usable share of it. A page
            # that fits, scrolls neither way and keeps its type above the floor
            # can still be useless if its furniture ate the thing it is for.
            # A quarter is deliberately generous — it is a floor against
            # collapse, not a layout opinion. Measured after the grid was fixed:
            # 32% at 800x480 and 60% at 1280x800; before it, 17% and 8%.
            if name == 'map.html' and r.get('subject') is not None and h >= 400:
                share = r['subject'] / float(r['clientH'])
                ok_('map.html at %s gives the map itself a usable share of the '
                    'glass (%.0f%%, %.0fpx)' % (panel, share * 100, r['subject']),
                    share >= 0.25)

            # ...and its "you are here" label, every form of it, across the
            # map clear of the zoom buttons and whole on every panel. Inside
            # the map top to bottom only where the page gives the map room:
            # on the 3.5" hat this page scrolls and leaves the map about forty
            # pixels (see may_scroll above), and a two-row label cannot be
            # inside a forty-pixel map whatever it says.
            if name == 'map.html':
                mh = got.get('%s map here' % panel) or {}
                eq('map.html\'s "you are here" label was measured in every form '
                   'at %s' % panel,
                   sorted(k for k, _t in HERE_LINES if k not in mh), [])
                for k, _t in HERE_LINES:
                    m = mh.get(k) or {}
                    ok_('map.html\'s "you are here" %r lies across the map, clear '
                        'of the zoom buttons, at %s (%r)' % (k, panel, m),
                        m.get('across') and not m.get('spills'))
                    if h >= 400:
                        ok_('...inside it top to bottom, in two rows at most, at '
                            '%s (%r)' % (panel, (m.get('rows'), m.get('mapH'))),
                            m.get('inside') and (m.get('rows') or 9) <= 2)
                # ...and its key to the pins, all four items shown: one row,
                # nothing cut, across the map; inside it top to bottom where
                # the page gives the map room (as for the label above).
                mk = got.get('%s map key' % panel) or {}
                ok_('map.html\'s key to its pins is one row, nothing cut, within the '
                    'map\'s width, at %s (%r)' % (panel, mk),
                    mk.get('rows') == 1 and not mk.get('spills')
                    and (mk.get('w') or 999) <= (mk.get('mapW') or 0)
                    and (h < 400 or mk.get('inside'))
                    and mk.get('text') == '● pickup · ● dropoff · ● stray · ◉ outside its box')

            # A line of prose has a width past which it stops being readable.
            # Widening the across-the-screen breakpoint to all of landscape put
            # the log page on a desktop-sized window for the first time, and it
            # ran body text 1892px wide — around 200 characters a line, because
            # that layout deliberately lifts the shared 480px cap so the charts
            # and the rows can use the panel. The bars keep the width; the
            # sentences do not.
            if r.get('measure'):
                ok_('%s at %s keeps a line of text readable (%.0fpx in %s)'
                    % (name, panel, r['measure'], r['measureIn']),
                    r['measure'] <= 900)

            # Measured at 0px of skew on every panel and in every chart
            # today. The runs chart deliberately runs a second line under
            # every one of its labels, which is why this is asked per chart
            # rather than across the page.
            if r.get('rowSkew') is not None:
                ok_('%s at %s keeps a chart\'s rows the same height '
                    '(%.1fpx apart in %s)'
                    % (name, panel, r['rowSkew'], r['rowSkewIn']),
                    r['rowSkew'] <= 0.5)

            # The day-of-week chart, measured after the driver pressed "30
            # days" — the range it exists for. See the driver for why the
            # landing page cannot hold it.
            wk = got.get('%s %s week' % (panel, name))
            if name == 'journal.html':
                ok_('%s at %s draws the day-of-week chart over a fortnight'
                    % (name, panel), wk and wk.get('shown'))
                if wk and wk.get('shown'):
                    eq('...with a bar for every day of the week at %s' % panel,
                       wk.get('rows'), 7)
                    ok_('...all the same height (%.1fpx apart) at %s'
                        % (wk.get('skew') or 0, panel), wk.get('skew', 99) <= 0.5)
                    ok_('...without widening the page at %s' % panel, wk.get('fits'))
                # The run-by-run chart is a log, one row per stretch of
                # scanning, and on a month it is the longest thing above the
                # offers. It goes after the chart of hours, and shows eight.
                if wk and wk.get('runsAt') is not None:
                    ok_('the chart of hours comes before the run-by-run log at %s '
                        '(%dpx before)' % (panel, (wk['runsAt'] or 0) - (wk['hoursAt'] or 0)),
                        wk.get('hoursAt') is not None and wk['hoursAt'] < wk['runsAt'])
                    ok_('...which shows at most eight runs at %s (%d)' % (panel, wk['runRows']),
                        wk['runRows'] <= 8)

            # The section about two offers at once.
            #
            # It reads back rows that were written to the journal from the day
            # the feature existed and shown to nobody, so the check that
            # matters is the plain one: they are on the page, they say which
            # way the panel went, and they fit the screen the driver has.
            pairs = got.get('%s pairs' % panel)
            if name == 'journal.html' and pairs:
                ok_('the second-jobs section is on the page at %s (%r)'
                    % (panel, pairs['headText'][:60]), pairs['headShown'])
                eq('...with a row for every pairing in the window at %s' % panel,
                   pairs['count'], 4)
                # One of each answer, including the row where the panel
                # declined to answer — which is not a fourth verdict and must
                # not be drawn as one.
                eq('...each carrying the verdict it was given at %s' % panel,
                   sorted(pairs['states']), ['', 'go', 'no', 'warn'])
                # The summary is the whole reason to scroll the list: the range,
                # the two payouts and where the pair ends, without opening
                # anything.
                # `and pairs['summaries']` because `all([])` is True: with the
                # section unrendered this passed while asserting on nothing,
                # which is the shape of check this file exists to refuse.
                ok_('...saying what was offered onto what at %s (%r)'
                    % (panel, (pairs['summaries'] or [''])[0][:70]),
                    pairs['summaries'] and all('onto' in s
                                               for s in pairs['summaries']))
                ok_('...and the lead says which way the panel went at %s (%r)'
                    % (panel, pairs['lead'][:70]),
                    'take it' in pairs['lead'] and 'no answer' in pairs['lead'])
                # Opened, which is when a `<dl>` of arithmetic is widest.
                eq('...with nothing pushed off the glass at %s' % panel,
                   pairs['outside'], 0)
                eq('...and the page still not scrolling sideways at %s' % panel,
                   pairs['pageWide'], False)

            # Close the shift, opened, on every panel: two answers a row at the
            # 52px every control on this page keeps, beside a payout, a
            # distance and a place, and nothing pushed off the glass for it.
            rvw = got.get('%s review' % panel)
            if name == 'journal.html':
                ok_('Close the shift is on the page at %s (%r)'
                    % (panel, ((rvw or {}).get('says') or '')[:70]),
                    rvw and rvw.get('shown'))
            if name == 'journal.html' and rvw and rvw.get('shown'):
                eq('...asking about the three cards nobody answered for at %s'
                   % panel, rvw['rows'], 3)
                ok_('...its one line a target to press at %s (%.0fpx)'
                    % (panel, rvw['lineH']), rvw['lineH'] >= 51.5)
                ok_('...and each answer too at %s (%.0fpx)' % (panel, rvw['shortest']),
                    rvw['shortest'] >= 51.5)
                eq('...with nothing pushed off the glass at %s' % panel,
                   rvw['outside'], 0)
                eq('...no answer\'s label wider than its button at %s' % panel,
                   rvw['clipped'], [])
                # The pay, the minutes and the miles of every row, whole:
                # wrapped between figures if they must, never cut at the edge.
                eq('...every figure on every card shown whole at %s' % panel,
                   rvw['cut'], [])
                # The fixture spans a fortnight, so there is a day before the
                # newest to step to, and the step is a control like the rest.
                ok_('...the day before a 52px press at %s (%r)'
                    % (panel, [(s['text'], round(s['h'])) for s in rvw['steps']]),
                    len(rvw['steps']) == 1 and rvw['steps'][0]['h'] >= 51.5)
                _floor = (15 if h >= 400 else 12) if dashboard else 9
                ok_('...nothing in it smaller than %dpx at %s (%.4gpx in %s)'
                    % (_floor, panel, rvw['smallest'] or 0, rvw['smallestIn']),
                    (rvw['smallest'] or 0) >= _floor)
                ok_('...its sentence a readable width at %s (%.0fpx)'
                    % (panel, rvw['leadW']), rvw['leadW'] <= 900)
                eq('...and no sideways scroll at %s' % panel, rvw['pageWide'], False)

            # The map sheet. See the driver for why it is opened by hand.
            sheet = got.get('%s sheet' % panel)
            if name == 'journal.html' and sheet:
                ok_('the map sheet fits the glass at %s (%dpx tall)'
                    % (panel, sheet['height']), sheet['onScreen'])
                # Below about this, the tiles are a texture rather than a
                # place, and the sheet is answering the question by not
                # answering it.
                ok_('...with enough map to read at %s (%dpx)'
                    % (panel, sheet['mapTall']), sheet['mapTall'] >= 110)
                # The only way out on a screen with no keyboard.
                ok_('...and the way to close it on screen at %s' % panel,
                    sheet['shutOn'])
                ok_('...big enough to press at %s (%dpx)' % (panel, sheet['shutTall']),
                    sheet['shutTall'] >= 30)
                # The room the sheet takes, handed back to the list under it.
                # Without this the end of the log is unreachable for as long as
                # the sheet is open — and it is open exactly when a driver is
                # working through the list.
                ok_('...and the last offer can still be scrolled clear of it at %s'
                    ' (padded %dpx under a %dpx sheet)'
                    % (panel, sheet['padded'], sheet['height']),
                    sheet['lastClear'] is not False)
                ok_('...with the room given back at least as tall as the sheet '
                    'at %s' % panel, sheet['padded'] >= sheet['height'])
                eq('...and no sideways scroll at %s' % panel,
                   sheet['pageWide'], False)

            layers = r.get('layers') or []
            if len(layers) > 1:
                overlaps = [
                    '%s over %s' % (b['sel'], a['sel'])
                    for a, b in zip(layers, layers[1:])
                    if b['top'] < a['bottom'] - 0.5
                ]
                eq('%s at %s draws nothing on top of anything' % (name, panel),
                   overlaps, [])

    # 📷 Snaps with both its snaps ticked: the bar's third link, to the ticked
    # ones as one file, beside the two it always has — whole, as tall as every
    # control on a bar, and without pushing the page sideways.
    for panel, w, h in PANELS:
        sc = got.get('%s snaps chosen' % panel)
        ok_('📷 Snaps was measured with its snaps ticked at %s' % panel, sc is not None)
        if not sc:
            continue
        eq('...its bar offering the ticked ones as one file at %s' % panel,
           sc['labels'], ['◂ Live', '▤ Offers', '⤓ 2 chosen'])
        eq('...every label on the bar on one line, inside its link, at %s' % panel,
           sc['unread'], [])
        ok_('...every link on it %dpx tall at %s (%.4gpx)'
            % (52 if h >= 400 else 44, panel, sc['shortest']),
            sc['shortest'] >= (51.5 if h >= 400 else 43.5))
        no_('...and the page not scrolling sideways at %s' % panel, sc['sideways'])

    # ...and the one file a snap is saved as, opened at each size: the snap
    # with the longest note the rig keeps, which has no space to wrap at.
    for panel, w, h in PANELS:
        sf = got.get('%s snap file' % panel) or {}
        eq('a snap saved as one file, opened at %s, carries its note and its pictures' % panel,
           (sf.get('error'), sf.get('note'), sf.get('pictures')),
           (None, '— ' + 'W' * _NOTE_MAX, 3))
        no_('...and the longest note there is does not push it sideways at %s' % panel,
            sf.get('sideways', True))
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    for spare in ('backup', 'logs'):
        try:
            os.rmdir(os.path.join(ROOT, spare))
        except OSError:
            pass
    shutil.rmtree(work, ignore_errors=True)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d layout checks passed' % ok)
sys.exit(1 if bad else 0)
