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
const [base, panelsJson, pagesJson] = process.argv.slice(2);
const PANELS = JSON.parse(panelsJson), PAGES = JSON.parse(pagesJson);

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
        // Every control meant to be pressed one-handed, on glass, in a car.
        let shortest = null, shortestIn = null;
        for (const el of document.querySelectorAll(
               '.bottombar button, .bottombar a, .scanbar button, .scanbar label,'
               + ' .scanbar a, .key, .rangebtns button')) {
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
          layers: layers,
        };
      });
      // The other thing this panel is used for: reading the phone through it
      // and working it with a bluetooth mouse. That view is only worth having
      // if the picture is bigger than the one it replaced, which is a claim
      // about pixels and can be measured.
      if (name === 'live.html') {
        const before = await page.evaluate(() => {
          const r = document.getElementById('view').getBoundingClientRect();
          return { w: r.width, h: r.height };
        });
        await page.click('#viewMode');
        await page.waitForTimeout(1200);
        out[panel[0] + ' phoneview'] = await page.evaluate(before => {
          const d = document.documentElement;
          const img = document.getElementById('view');
          const r = img.getBoundingClientRect();
          const btn = document.getElementById('viewMode');
          return {
            src: img.getAttribute('src') || '',
            pressed: btn.getAttribute('aria-pressed'),
            label: btn.textContent.trim(),
            h: r.height,
            was: before.h,
            rowH: document.getElementById('app').getBoundingClientRect().height,
            over: d.scrollWidth > d.clientWidth + 1 || d.scrollHeight > d.clientHeight + 1,
          };
        }, before);
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

# A week of offers, so the log page is measured with a log in it. Rates
# deliberately spread across the verdicts so every row style is drawn.
now = time.time() * 1000
rows = []
for i in range(40):
    pay = 6.0 + (i % 13) * 2.5
    mins = 8 + (i * 7) % 50
    miles = 1.5 + (i % 9) * 2.1
    rows.append({
        'id': 'r%d' % i, 'at': now - i * 900000, 'firstAt': now - i * 900000,
        'pay': round(pay, 2), 'minutes': mins, 'miles': round(miles, 1),
        'perHour': round(pay / (mins / 60.0), 1),
        'grossPerHour': round(pay / (mins / 60.0), 1),
        'cost': round(miles * 0.35, 2), 'costPerMile': 0.35,
        'target': 25, 'band': 15, 'legs': 2, 'whole': True,
        'accepted': i % 7 == 0, 'hidden': i % 11 == 0, 'suspect': i % 17 == 0,
    })
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
        ['node', driver, base, json.dumps(PANELS), json.dumps(PAGES)],
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
            floor = 12 if dashboard else 9
            ok_('%s at %s has nothing smaller than %dpx (%.4gpx in %s)'
                % (name, panel, floor, r['smallest'], r['smallestIn']),
                r['smallest'] >= floor)

            # 44px is the floor both platform guidelines give, and it is not a
            # preference here: these are pressed one-handed, on glass, by
            # somebody who has just parked.
            if r['shortest'] is not None:
                ok_('%s at %s keeps every control at 44px (%.4gpx in %s)'
                    % (name, panel, r['shortest'], r['shortestIn']),
                    r['shortest'] >= 43.5)

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
                if dashboard:
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
