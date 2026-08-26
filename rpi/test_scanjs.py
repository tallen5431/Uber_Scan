"""The phone's own scanner, driven through a real browser.

    python3 rpi/test_scanjs.py

scan.js runs the same parser as the rig over tesseract.js, on a phone the driver
is holding, and until now nothing tested it end to end at all. The hook it needs
was already there — `window.__scan`, with the comment "exposed so the test
harness can drive the same pipeline headlessly" — and no harness ever used it.

What that cost, measured: the browser handed the reader a picture sized by width
rather than by pixels, and because the scale was `Math.min(2, 1400 / width)` it
*upscaled* a phone-sized crop by up to double. Past about a megapixel tesseract
stops reading the largest text on the card, so every Uber Eats shop order came
back with its journey, its item count and its merchant read perfectly and no
payout at all. The rest of the card reading fine is what made it invisible.

Skipped where a browser cannot be had, the same way the live-view checks skip
without node: the Pi does not carry Playwright and does not need to.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
    print('%s — skipping the browser-scanner checks' % why)
    sys.exit(0)


if shutil.which('node') is None:
    skip('no node on this machine')

import cv2                                                   # noqa: E402
import numpy as np                                           # noqa: E402
import pipeline as PL                                        # noqa: E402
import testcards as TC                                       # noqa: E402

if not TC.available():
    skip('no PIL or no usable font')

# Playwright drives the browser, and it is the one thing here that is not
# already a dependency of this project. Found however node can find it.
FIND_PW = '''
try { require.resolve('playwright'); process.stdout.write('yes'); }
catch (e) { process.stdout.write('no'); }
'''
env = dict(os.environ)
if 'NODE_PATH' not in env:
    for guess in ('/opt/node22/lib/node_modules', '/usr/lib/node_modules',
                  '/usr/local/lib/node_modules'):
        if os.path.isdir(os.path.join(guess, 'playwright')):
            env['NODE_PATH'] = guess
            break
found = subprocess.run(['node', '-e', FIND_PW], capture_output=True, env=env)
if found.stdout.strip() != b'yes':
    skip('no playwright')


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


# The card as a driver frames it in the reticle: the offer, not the whole phone.
CARDS = [('a ride card', TC.uberx_screen, 16.05),
         ('a shop order', TC.shop_screen, 7.09),
         ('a delivery card', TC.doordash_screen, 41.11)]

DRIVER = r'''
const { chromium } = require('playwright');
const fs = require('fs'), path = require('path');
const [base, dir] = process.argv.slice(2);
const cards = JSON.parse(fs.readFileSync(path.join(dir, 'cards.json'), 'utf8'));

(async () => {
  let browser;
  for (const exe of JSON.parse(process.env.PW_EXES || '[]').concat([null])) {
    try {
      browser = await chromium.launch(exe ? { executablePath: exe } : {});
      break;
    } catch (e) { /* try the next one */ }
  }
  if (!browser) { console.log(JSON.stringify({ skip: 'no chromium' })); return; }
  const page = await (await browser.newContext(
    { viewport: { width: 420, height: 900 } })).newPage();
  await page.goto(base + '/scan.html', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction('window.__scan && window.__scan.ready()',
                             null, { timeout: 180000 });
  const out = { reads: {}, fit: {} };
  for (const c of cards) {
    const data = 'data:image/png;base64,'
      + fs.readFileSync(path.join(dir, c.file)).toString('base64');
    const r = await page.evaluate(async s => {
      const got = await window.__scan.readImage(s);
      return { pay: got.parsed.pay, minutes: got.parsed.minutes,
               miles: got.parsed.miles, ready: got.rate.ready,
               state: got.rate.state, perHour: got.rate.perHour || null,
               shown: document.getElementById('perHour').textContent.trim() };
    }, data);
    out.reads[c.name] = r;
  }
  for (const wh of JSON.parse(process.env.FIT_CASES)) {
    out.fit[wh.join('x')] = await page.evaluate(
      p => window.__scan.fitForOcr(p[0], p[1]), wh);
  }

  // Half a card: what the page says when the reading is not whole.
  const frag = 'data:image/png;base64,'
    + fs.readFileSync(path.join(dir, 'fragment.png')).toString('base64');
  out.fragment = await page.evaluate(async s => {
    const got = await window.__scan.readImage(s);
    return { pay: got.parsed.pay, ready: got.rate.ready, state: got.rate.state,
             perHour: got.rate.perHour || null,
             shown: document.getElementById('perHour').textContent.trim(),
             label: document.getElementById('verdictLabel').textContent.trim(),
             warned: !document.getElementById('warn').hidden,
             warning: document.getElementById('warn').textContent.trim() };
  }, frag);

  // A reader that throws every cycle must not leave the last verdict standing.
  out.afterThrow = await page.evaluate(async () => {
    const before = document.getElementById('perHour').textContent.trim();
    window.__scan.failRead(4);
    return { before: before,
             after: document.getElementById('perHour').textContent.trim(),
             label: document.getElementById('verdictLabel').textContent.trim() };
  });

  // The offline cache: which caches exist, and does the app shell refresh.
  out.sw = await page.evaluate(async () => {
    const reg = await navigator.serviceWorker.register('/sw.js');
    await navigator.serviceWorker.ready;

    /* Wait to be *controlled*, not merely for a worker to exist.
     *
     * `ready` resolves once the scope has an active registration. It says
     * nothing about this page: a page loaded before the worker registered
     * starts life uncontrolled, and a fetch from an uncontrolled page goes
     * straight to the network without the worker ever seeing it. sw.js calls
     * clients.claim() in activate, which fixes that — asynchronously, some
     * milliseconds later.
     *
     * So the vendor fetch below was racing the claim. Win the race and the
     * engine is cached; lose it and the file is fetched, nothing is stored,
     * and no amount of waiting afterwards produces the entry. That is what was
     * happening: green on an idle machine, red inside a full run, twice.
     */
    for (let i = 0; i < 100 && !navigator.serviceWorker.controller; i++) {
      await new Promise(r => setTimeout(r, 100));
    }
    const controlled = !!navigator.serviceWorker.controller;

    /* ...and ask again rather than once. Even controlled, the worker hands the
     * response back before it finishes putting a copy in the cache, so there
     * is a moment when the engine cache exists and is empty. Re-fetching is
     * free — the second one is served from the cache the first one filled. */
    let keys = [], held = {};
    for (let i = 0; i < 100; i++) {
      try { await fetch('vendor/lang/eng.traineddata.gz'); } catch (e) {}
      keys = await caches.keys();
      held = {};
      for (const k of keys) {
        const c = await caches.open(k);
        held[k] = (await c.keys()).map(r => new URL(r.url).pathname);
      }
      const engine = Object.keys(held).some(k =>
        held[k].some(p => p.indexOf('/vendor/') !== -1));
      if (engine) break;
      await new Promise(r => setTimeout(r, 100));
    }
    return { keys: keys, scope: reg.scope, held: held, controlled: controlled };
  });
  await browser.close();
  console.log(JSON.stringify(out));
})().catch(e => { console.log(JSON.stringify({ skip: 'browser: ' + e.message })); });
'''

# Sizes a reticle on a phone actually produces, plus the ends of the range.
FIT_CASES = [[540, 680], [720, 905], [1080, 1358], [1620, 2037],
             [400, 300], [2000, 2500], [100, 90]]

work = tempfile.mkdtemp()
proc = None
try:
    manifest = []
    for name, make, pay in CARDS:
        screen = make()
        card = screen[int(screen.shape[0] * 0.42):, :]
        fname = name.replace(' ', '-') + '.png'
        cv2.imwrite(os.path.join(work, fname), card)
        manifest.append({'name': name, 'file': fname})
    # Half a card: one leg, which always reads better than the offer is.
    frag = TC.uberx_screen()
    frag = frag[int(frag.shape[0] * 0.42):int(frag.shape[0] * 0.72), :]
    cv2.imwrite(os.path.join(work, 'fragment.png'), frag)
    with open(os.path.join(work, 'cards.json'), 'w') as fh:
        json.dump(manifest, fh)
    driver = os.path.join(work, 'drive.js')
    with open(driver, 'w') as fh:
        fh.write(DRIVER)

    port = free_port()
    proc = subprocess.Popen(
        ['node', os.path.join(ROOT, 'server.js')],
        env=dict(env, PORT=str(port), SCANNER='0',
                 JOURNAL=os.path.join(work, 'j.jsonl')),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = 'http://127.0.0.1:%d' % port
    import urllib.request
    for _ in range(120):
        try:
            urllib.request.urlopen(base + '/api/status', timeout=1).read()
            break
        except Exception:
            time.sleep(0.1)
    else:
        raise RuntimeError('the server never came up')

    exes = [p for p in (
        os.environ.get('PLAYWRIGHT_CHROMIUM'),
        '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
    ) if p and os.path.exists(p)]
    run = subprocess.run(
        ['node', driver, base, work],
        env=dict(env, PW_EXES=json.dumps(exes), FIT_CASES=json.dumps(FIT_CASES)),
        capture_output=True, timeout=600)
    tail = (run.stdout or b'').decode('utf-8', 'replace').strip().splitlines()
    if not tail:
        skip('the browser produced nothing (%s)'
             % (run.stderr or b'').decode('utf-8', 'replace').strip()[-160:])
    got = json.loads(tail[-1])
    if got.get('skip'):
        skip(got['skip'])

    # --- every card shape reads, or says nothing ---------------------------
    for name, make, pay in CARDS:
        r = got['reads'][name]
        ok_('%s: right, or says nothing — never something else' % name,
            (not r['ready']) or r['pay'] == pay)

    # --- and the payout is actually read -----------------------------------
    # The property above was true throughout the bug: a shop order with no
    # payout is not `ready`, so "right or silent" held while the phone app was
    # useless on a whole card shape. Silence is only acceptable when the picture
    # is bad, and these are clean renders.
    for name, make, pay in CARDS:
        eq('%s: the payout is read from a clean card' % name,
           got['reads'][name]['pay'], pay)

    shop = got['reads']['a shop order']
    eq('...including a shop order, which is the one that was lost', shop['pay'], 7.09)
    eq('...with its journey', shop['minutes'], 34)
    eq('...and its distance', shop['miles'], 3.6)
    ok_('...and a rate on the screen', shop['shown'].startswith('$'))

    # --- a delivery card is judged against the clock, or not at all --------
    # The container's clock makes the deadline hours away, which is exactly the
    # case the doubt guard is for: a number is refused rather than shown.
    delivery = got['reads']['a delivery card']
    ok_('a deadline the clock cannot make sense of is refused, not shown',
        delivery['state'] != 'doubt' or delivery['shown'] == '--')

    # --- half a card says so, in words -------------------------------------
    # A single leg is the same pay over less time, so it always reads *better*
    # than the offer is — "$16.00 3 min away" is a confident green $320/hr for
    # a card whose truth is $35.30. doubt() cannot see it (3 minutes and $16 are
    # both ordinary) and the distance is not uncertain, so the only thing that
    # can argue with the number is a sentence saying the journey is not all
    # there. live.html has had one for a while; this page had the "?" on the
    # word and nothing on the figure, which is the wrong half to hedge.
    frag = got['fragment']
    if frag['ready']:
        ok_('half a card is called out on the phone too', frag['warned'])
        ok_('...in the same words as the driving screen',
            'may not be all there' in frag['warning'])
        ok_('...while the label hedges as well', frag['label'].endswith('?'))
    else:
        ok_('half a card shows no rate at all', frag['shown'] == '--')

    # --- a reader that throws does not leave the last verdict standing ------
    # On a throw neither consider() nor render() ran, so every number on the
    # screen kept its previous value. An engine that throws every cycle — a
    # phone that has run its worker out of memory — therefore held a green
    # ACCEPT and a dollar figure from an offer that was already gone, admitted
    # to only by the status line.
    thrown = got['afterThrow']
    eq('a run of failed reads clears the rate', thrown['after'], '--')
    ok_('...and the verdict with it',
        thrown['label'] in ('POINT AT THE OFFER', 'READ AGAIN'))

    # --- the offline cache keeps the engine and refreshes the app ----------
    # The version constant used to be the whole mechanism: forget to bump it and
    # an installed phone serves the old code for ever, which is exactly what
    # happened to two fixes in two commits. The app shell revalidates in the
    # background now, so forgetting costs one page load.
    #
    # And the engine lives in a cache of its own. It was never in ASSETS — it
    # only ever arrived opportunistically, under the same key the activate
    # handler deletes — so the obvious fix, bumping the version, would have
    # thrown away 15MB of reader and left an offline phone unable to scan at
    # all, in the name of shipping a scanner fix.
    # First, because everything below it depends on this and nothing below it
    # would say so. An uncontrolled page fetches straight past the worker, so
    # the engine cache stays empty and the failure reads as "the worker did not
    # cache the engine" when the truth is "the worker never saw the request".
    ok_('the page is under the worker before anything is asked of it',
        got['sw'].get('controlled'))
    held = got['sw']['held']
    shells = [k for k in held if k.startswith('uberscan-shell-')]
    blobs = [k for k in held if k.startswith('uberscan-vendor-')]
    eq('the worker installs one app-shell cache', len(shells), 1)
    eq('...and one for the vendored engine', len(blobs), 1)
    ok_('the shell holds the app', any(p.endswith('scan.js') for p in held[shells[0]]))
    ok_('...and not the engine',
        not any('/vendor/' in p for p in held[shells[0]]))
    ok_('the engine cache holds the engine',
        any('/vendor/' in p for p in held[blobs[0]]))

    # The half of this that a single page load cannot exercise: what survives a
    # *version change*. Bumping the shell runs activate again, and activate
    # deletes every cache it is not told to keep — so the check is that it is
    # told to keep the engine. Asserted on the source, and said plainly rather
    # than dressed up as a runtime test, because reaching it for real would mean
    # serving two different workers to one page.
    worker_src = open(os.path.join(ROOT, 'sw.js')).read()
    keep = [l for l in worker_src.splitlines() if 'caches.delete(k)' in l]
    eq('activate has one rule about what to delete', len(keep), 1)
    ok_('...and it spares the app shell', 'SHELL' in keep[0])
    ok_('...and the vendored engine, which install does not put back',
        'BLOB' in keep[0])
    ok_('...which is a different cache from the shell', shells[0] != blobs[0])

    # --- the browser sizes its picture the way the Pi does ------------------
    # This is the rule that broke, and it broke by drifting from the Pi's. Both
    # are now the same two numbers, so the check is that they still agree.
    for w, h in FIT_CASES:
        want = PL.fit_for_ocr(np.zeros((h, w, 3), np.uint8))
        js = got['fit']['%dx%d' % (w, h)]
        eq('the browser sizes %dx%d as the Pi does' % (w, h),
           (js['w'], js['h']), (want.shape[1], want.shape[0]))
        ok_('...inside the pixel budget at %dx%d' % (w, h),
            js['w'] * js['h'] <= PL.MAX_OCR_PIXELS + 2000)
finally:
    if proc is not None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
    shutil.rmtree(work, ignore_errors=True)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d browser-scanner checks passed' % ok)
sys.exit(1 if bad else 0)
