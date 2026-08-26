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

# Both halves of the layout have to switch at the same height, or a page spends
# a range of sizes half in one design and half in the other.
heights = set()
for name in SHEETS:
    for css in style_blocks(name):
        heights |= set(re.findall(
            r'orientation: landscape\) and \(max-height: (\d+)px', css))
eq('every file agrees where a dashboard panel starts',
   sorted(int(h) for h in heights), [380, 620])

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

port = free_port()
proc = subprocess.Popen(
    ['node', os.path.join(ROOT, 'server.js')],
    env=dict(os.environ, SCANNER='0', PORT=str(port), JOURNAL=journal,
             FRAME=os.path.join(work, 'live.jpg')),
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
