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
PAGES = ['index.html', 'live.html', 'journal.html', 'scan.html']

# The panels this thing actually gets bolted to, plus a phone for comparison.
PANELS = [
    ('800x480', 800, 480),    # the official 7" Pi touchscreen
    ('1024x600', 1024, 600),  # the common 7" HDMI panel
    ('1280x800', 1280, 800),  # a tablet-shaped panel, on its side
    ('1024x768', 1024, 768),  # 4:3 — landscape, but only just
    ('480x320', 480, 320),    # a 3.5" hat
    ('390x844', 390, 844),    # a phone
]

# journal.html is one continuous list — a week of offers is fourteen thousand
# pixels of it — so it scrolls by design and only its width is held to the
# glass. Everything else is a screen glanced at while driving and must fit.
SCROLLS = {'journal.html'}

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
    print('%s — skipping the layout checks' % why)
    sys.exit(0)


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
eq('every file switches to the across-the-screen layout at the same point',
   sorted(c.strip() for c in conditions),
   ['', 'and (max-height: 380px)'])
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

# ---------------------------------------------------------------------------
# Now the browser.
# ---------------------------------------------------------------------------

if shutil.which('node') is None:
    skip('no node on this machine')

NODE_PATHS = [p for p in (os.environ.get('NODE_PATH'),
                          '/opt/node22/lib/node_modules') if p]
env_probe = dict(os.environ, NODE_PATH=os.pathsep.join(NODE_PATHS))
if subprocess.call(['node', '-e', 'require("playwright")'], env=env_probe,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
    skip('no playwright')

DRIVER = r'''
const { chromium } = require('playwright');
const [base, panelsJson, pagesJson, framesJson] = process.argv.slice(2);
const PANELS = JSON.parse(panelsJson), PAGES = JSON.parse(pagesJson);
// Two pictures the shape the rig actually publishes: a landscape cabin for the
// scene view, a portrait phone screen for the other. There is no camera on the
// machine this runs on, so without them every measurement of the live view is a
// measurement of a broken image — which is not a small thing, because a broken
// image collapses to 2px and 2px passes "the phone is taller than the scene
// was" as comfortably as a real picture does.
const FRAMES = JSON.parse(framesJson);

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
          };
        };
        const shown = await page.evaluate(LOOKAT);
        // The bar of controls with everything on it at once.
        //
        // Two of its buttons are conditional — "Took $8.04" appears when there
        // is an offer on the record, "Dropped off" while an order is in the car
        // — and both are hidden on a freshly loaded page, so every measurement
        // above is of a bar two buttons short of its widest. That is the bar a
        // driver never sees at the moment it matters: an offer on screen while
        // a job is already in the car is exactly when both show.
        shown.bar = await page.evaluate(() => {
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
          // empty bar. `plain` is the five fixed controls; `before` adds the
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
          const d = document.documentElement;
          return { plain: plain, before: before, full: full, crowded: crowded,
                   over: d.scrollWidth > d.clientWidth + 1 };
        });
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
        shown.was = scene.h;
        shown.sceneSrc = scene.src;
        shown.scenePressed = scene.pressed;
        shown.sceneLabel = scene.label;
        shown.sceneLoaded = scene.loaded;
        shown.sceneCut = Math.max(scene.cutTop, scene.cutBottom,
                                  scene.cutLeft, scene.cutRight);
        out[panel[0] + ' phoneview'] = shown;
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
      }
      await page.close();
    }
    await ctx.close();
  }
  await browser.close();
  console.log(JSON.stringify(out));
})().catch(e => { console.log(JSON.stringify({ skip: 'browser: ' + e.message })); });
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
         json.dumps(FRAMES)],
        env=env, capture_output=True, text=True, timeout=600)
    line = (proc2.stdout or '').strip().split('\n')[-1] if proc2.stdout else ''
    try:
        got = json.loads(line)
    except Exception:
        skip('the browser produced nothing (%s)'
             % (proc2.stderr or '')[-200:].replace('\n', ' '))
    if got.get('skip'):
        skip(got['skip'])

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
            if name not in SCROLLS:
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
                # With both conditional buttons up, the two links that lead
                # somewhere else stand down — on every panel, because not one of
                # them has room for seven. The five that stay are the ones used
                # while the car is moving.
                eq('the crowded bar sheds the parked-use links at %s (bar %spx)'
                   % (panel, full.get('width')),
                   full.get('count'), 5)
                ok_('...and still fits the glass at %s' % panel,
                    not bar.get('over'))
                ok_('...with every control still 44px tall at %s (%.4gpx)'
                    % (panel, full.get('shortest') or 0),
                    (full.get('shortest') or 0) >= 43.5)
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
                # ...and the five fixed controls are clean wherever the bar is
                # not being squeezed, which is what says the squeeze is the
                # cause rather than the labels being too long everywhere.
                if (plain.get('width') or 0) >= 400:
                    eq('...with the five fixed controls clipping nothing at %s'
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
                ok_('...each still 44px tall at %s (%.4gpx, bar %spx tall)'
                    % (panel, crowded.get('shortest') or 0, crowded.get('height')),
                    (crowded.get('shortest') or 0) >= 43.5)
                if (crowded.get('width') or 0) >= 470:
                    eq('...with every label inside its own button at %s'
                       % panel, crowded.get('spilling'), [])
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
                ok_('...and offers the phone back at %s (%r)'
                    % (panel, phone['sceneLabel']),
                    'Phone' in phone['sceneLabel'])
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

            layers = r.get('layers') or []
            if len(layers) > 1:
                overlaps = [
                    '%s over %s' % (b['sel'], a['sel'])
                    for a, b in zip(layers, layers[1:])
                    if b['top'] < a['bottom'] - 0.5
                ]
                eq('%s at %s draws nothing on top of anything' % (name, panel),
                   overlaps, [])
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
