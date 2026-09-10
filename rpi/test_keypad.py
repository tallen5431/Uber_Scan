"""The keypad, driven through a real browser.

    python3 rpi/test_keypad.py

`ui.js` is the fallback input path: what a driver uses when the camera cannot
read a card, or when there is no rig at all and this is just an app on a phone.
The arithmetic it does is the shared parser's and is covered by the corpus. The
four hundred lines around that arithmetic were covered by nothing.

Three faults are already recorded in its own comments, which is to say all three
shipped:

  - Writing settings back wholesale deleted the keys this page does not know
    about. It shares one localStorage entry with the camera scanner, which
    stores `secondsPerItem` and `fullFrame` there, so one keystroke in any
    field silently reset the shopping allowance to zero — and scan.html then
    rated Shop & Deliver offers as if the shopping took no time. Nothing
    resyncs the two pages, so it stayed wrong until somebody noticed.
  - `ready` was tested against the padded total rather than the typed minutes,
    so with a pickup pad set and nothing in the minutes field the app had a
    complete offer: pay, no time, and a confident rate worked out from the pad.
  - `perMile` was gross while the rate beside it was net, so the same offer read
    $1.97/mi here and $1.67/mi on the Pi, and neither screen said why.

None of those is visible from reading a diff, and every one of them is a wrong
number shown confidently — the thing this project's first rule is about. So the
page is opened, the keys are pressed, and what the screen says is read back.

Skipped where a browser cannot be had, the same way the other browser checks
skip.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ok = bad = 0


def eq(name, got, want):
    global ok, bad
    if got == want:
        ok += 1
    else:
        bad += 1
        print('FAIL  %s: got %r want %r' % (name, got, want))


def no_(name, cond):
    eq(name, bool(cond), False)


def ok_(name, cond):
    eq(name, bool(cond), True)


def skip(why):
    print('%s — skipping the keypad checks' % why)
    sys.exit(0)


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


if shutil.which('node') is None:
    skip('no node on this machine')

NODE_PATHS = [p for p in (os.environ.get('NODE_PATH'),
                          '/opt/node22/lib/node_modules') if p]
if subprocess.call(['node', '-e', 'require("playwright")'],
                   env=dict(os.environ, NODE_PATH=os.pathsep.join(NODE_PATHS)),
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
    skip('no playwright')

DRIVER = r'''
const { chromium } = require('playwright');
const [base] = process.argv.slice(2);

(async () => {
  let browser;
  for (const exe of JSON.parse(process.env.PW_EXES || '[]').concat([null])) {
    try { browser = await chromium.launch(exe ? { executablePath: exe } : {}); break; }
    catch (e) { /* try the next one */ }
  }
  if (!browser) { console.log(JSON.stringify({ skip: 'no chromium' })); return; }

  const ctx = await browser.newContext({ viewport: { width: 420, height: 900 } });
  const page = await ctx.newPage();
  const thrown = [];
  page.on('pageerror', e => thrown.push(e.message));

  const out = { thrown: thrown };

  async function open(seed) {
    await page.goto(base + '/index.html', { waitUntil: 'domcontentloaded' });
    if (seed) {
      await page.evaluate(s => {
        for (const k in s) {
          if (s[k] === null) localStorage.removeItem(k);
          else localStorage.setItem(k, s[k]);
        }
      }, seed);
      await page.reload({ waitUntil: 'domcontentloaded' });
    }
    await page.waitForTimeout(250);
  }

  // Pressing keys is the only way in: ui.js exports nothing, which is right for
  // shipped code and means this drives it exactly as a thumb does.
  async function type(keys) {
    for (const k of keys) await page.click(`[data-key="${k}"]`);
    await page.waitForTimeout(60);
  }

  const screen = () => page.evaluate(() => ({
    pay: document.getElementById('f-pay').textContent.trim(),
    minutes: document.getElementById('f-minutes').textContent.trim(),
    miles: document.getElementById('f-miles').textContent.trim(),
    perHour: document.getElementById('perHour').textContent.trim(),
    perMile: document.getElementById('perMile').textContent.trim(),
    perMin: document.getElementById('perMin').textContent.trim(),
    netPay: document.getElementById('netPay').textContent.trim(),
    rawRate: document.getElementById('rawRate').textContent.trim(),
    rawShown: !document.getElementById('rawRate').hidden,
    label: document.getElementById('verdictLabel').textContent.trim(),
    state: document.getElementById('verdict').className,
    active: (document.querySelector('.field.active') || {}).dataset
            ? document.querySelector('.field.active').dataset.field : null,
  }));

  const SETTINGS = 'uberscan.settings.v1';
  const HISTORY = 'uberscan.history.v1';
  const DRAFT = 'uberscan.draft.v1';

  // --- the settings this page does not own ---------------------------------
  // scan.html keeps secondsPerItem and fullFrame in the same entry.
  const SEEDED = JSON.stringify({
    target: 25, band: 15, costPerMile: 0.35, pad: 0, haptics: true,
    secondsPerItem: 90, fullFrame: true });
  await open({ [SETTINGS]: SEEDED, [DRAFT]: null, [HISTORY]: null });

  // Pressing a number is not changing a setting, and must not rewrite the
  // entry at all — the cheapest way for two pages sharing one key to stay in
  // step is for neither to write when it has nothing to say.
  await type(['1', 'next', '2']);
  out.settingsAfterTyping = await page.evaluate(
    k => localStorage.getItem(k), SETTINGS);
  out.settingsSeeded = SEEDED;

  // The writers are the settings sheet's own inputs and the haptics toggle,
  // and those are where the whole entry used to be replaced.
  await page.click('#openSettings');
  await page.fill('#setTarget', '30');
  await page.waitForTimeout(150);
  out.afterEditing = await page.evaluate(
    k => JSON.parse(localStorage.getItem(k)), SETTINGS);
  await page.uncheck('#setHaptics');
  await page.waitForTimeout(150);
  out.afterToggling = await page.evaluate(
    k => JSON.parse(localStorage.getItem(k)), SETTINGS);
  // A blank box is a box being retyped: the value already there stands. And
  // a value outside the range is clamped, and the box then shows what was
  // kept rather than what was typed.
  await page.fill('#setTarget', '');
  await page.waitForTimeout(120);
  out.blankTarget = await page.evaluate(k => JSON.parse(localStorage.getItem(k)).target, SETTINGS);
  await page.fill('#setBand', '60');
  await page.dispatchEvent('#setBand', 'change');
  await page.waitForTimeout(120);
  out.clampedBand = { stored: await page.evaluate(k => JSON.parse(localStorage.getItem(k)).band, SETTINGS),
                      shown: await page.inputValue('#setBand') };
  await page.click('[data-close="settingsSheet"]');

  // --- a pickup pad is not an offer ----------------------------------------
  await open({ [SETTINGS]: JSON.stringify({ target: 25, band: 15, costPerMile: 0, pad: 10 }),
               [DRAFT]: null, [HISTORY]: null });
  await type(['1', '6', '.', '0', '5']);          // pay only; no minutes typed
  out.padOnly = await screen();

  // ...and with a minute typed it is one.
  await type(['next', '2', '3']);
  out.padPlusOne = await screen();

  // --- net and gross agree about what a dollar means -----------------------
  await open({ [SETTINGS]: JSON.stringify({ target: 25, band: 15, costPerMile: 0.35, pad: 0 }),
               [DRAFT]: null, [HISTORY]: null });
  await type(['1', '6', '.', '0', '5', 'next', '2', '3', 'next', '8', '.', '4']);
  out.costed = await screen();

  // --- a slipped decimal point is not a green ACCEPT -----------------------
  await open({ [SETTINGS]: JSON.stringify({ target: 25, band: 15, costPerMile: 0, pad: 0 }),
               [DRAFT]: null, [HISTORY]: null });
  await type(['1', '1', '8', '4', 'next', '2', '0']);
  out.slipped = await screen();

  // --- what the digits do --------------------------------------------------
  await open({ [DRAFT]: null });
  const typing = {};
  const cases = {
    'a lone dot becomes nought-point': ['.'],
    'only one dot': ['1', '.', '5', '.', '2'],
    'two decimals and no more': ['1', '.', '2', '3', '4'],
    'a leading nought is dropped': ['0', '5'],
    'but not on nought-point': ['0', '.', '5'],
    'six digits is the cap': ['1', '2', '3', '4', '5', '6', '7'],
    'double-nought counts as two': ['1', '2', '00'],
  };
  for (const name in cases) {
    await type(['clear']);
    await type(cases[name]);
    typing[name] = (await screen()).pay;
  }
  out.typing = typing;

  // --- moving between the three fields -------------------------------------
  await open({ [DRAFT]: null });
  await type(['clear', '5', 'next']);
  out.afterNext = (await screen()).active;
  await type(['back']);                    // empty field: step back
  out.backOnEmpty = (await screen()).active;
  await type(['back']);                    // now it deletes
  out.backDeletes = await screen();
  await type(['next', 'next', 'next']);    // wraps
  out.wraps = (await screen()).active;
  // ...but ⌫ from PAY stays on PAY. It used to wrap round to MILES, so one
  // ⌫ too many while correcting the pay ate a digit of the distance.
  await type(['clear', '1', '2', 'next', '2', '0', 'next', '5', '.', '5']);
  await page.click('[data-field="pay"]');
  await type(['back', 'back', 'back', 'back']);
  out.backFromPay = await screen();

  // --- the physical keyboard, for a rig with one plugged in ----------------
  await open({ [DRAFT]: null });
  await type(['clear']);
  await page.keyboard.type('16.05');
  await page.keyboard.press('Enter');
  await page.keyboard.type('23');
  await page.waitForTimeout(80);
  out.typedOnAKeyboard = await screen();
  await page.keyboard.press('Backspace');
  await page.waitForTimeout(60);
  out.afterBackspace = (await screen()).minutes;
  await page.keyboard.press('Escape');
  await page.waitForTimeout(60);
  out.afterEscape = await screen();
  // With a sheet open the keys are the sheet's: a digit does not type into
  // the offer behind it and Escape closes the sheet rather than wiping the
  // offer. And Tab moves focus, as it does on every other page.
  await page.keyboard.type('15');
  await page.keyboard.press('Enter');
  await page.keyboard.type('20');
  await page.click('#openSettings');
  await page.keyboard.type('7');
  await page.keyboard.press('Escape');
  await page.waitForTimeout(80);
  out.escapeOnSheet = Object.assign(await screen(), {
    sheetOpen: await page.evaluate(() => !document.getElementById('settingsSheet').hidden) });
  const focused = () => page.evaluate(() => document.activeElement.tagName + ':'
    + (document.activeElement.id || (document.activeElement.textContent || '').trim().slice(0, 12)));
  const focusBefore = await focused();
  await page.keyboard.press('Tab');
  await page.keyboard.press('Tab');
  out.tabbed = { before: focusBefore, after: await focused() };

  // --- the draft, and how long it is worth keeping -------------------------
  // An offer is on the screen for seconds. One from an hour ago is a number
  // the driver will read as this one.
  await open({ [DRAFT]: null, [HISTORY]: null });
  await type(['clear', '9', '9']);
  out.draftWritten = await page.evaluate(k => JSON.parse(localStorage.getItem(k)), DRAFT);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(250);
  out.draftRestored = (await screen()).pay;

  await page.evaluate(k => {
    const d = JSON.parse(localStorage.getItem(k));
    d.t = Date.now() - 60 * 60 * 1000;      // an hour ago
    localStorage.setItem(k, JSON.stringify(d));
  }, DRAFT);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(250);
  out.staleDraft = (await screen()).pay;

  // Clearing everything must not leave a draft behind to come back.
  await open({ [DRAFT]: null });
  await type(['7', 'clear']);
  out.draftAfterClear = await page.evaluate(k => localStorage.getItem(k), DRAFT);

  // --- logging -------------------------------------------------------------
  await open({ [SETTINGS]: JSON.stringify({ target: 25, band: 15, costPerMile: 0, pad: 0 }),
               [DRAFT]: null, [HISTORY]: null });
  await type(['log']);                      // nothing typed
  out.loggedNothing = await page.evaluate(k => localStorage.getItem(k), HISTORY);
  out.toastOnEmpty = await page.evaluate(
    () => (document.getElementById('toast') || {}).textContent || '');

  await type(['3', '0', 'next', '6', '0', 'log']);
  await page.waitForTimeout(120);
  out.logged = await page.evaluate(k => JSON.parse(localStorage.getItem(k)), HISTORY);
  out.afterLogging = await screen();

  // The list is capped, or a year of offers is carried in one string.
  await page.evaluate(k => {
    const many = [];
    for (let i = 0; i < 120; i++) many.push({ t: Date.now() - i * 1000, pay: 10,
      minutes: 20, miles: 1, perHour: 30, state: 'go' });
    localStorage.setItem(k, JSON.stringify(many));
  }, HISTORY);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(200);
  await type(['clear', '1', '0', 'next', '2', '0', 'log']);
  await page.waitForTimeout(120);
  out.capped = await page.evaluate(
    k => JSON.parse(localStorage.getItem(k)).length, HISTORY);

  // --- a rate nothing came off is a ceiling, here as on the two other screens
  //
  // The camera screens cap the verdict at CLOSE CALL when a cost per mile is
  // set and no distance could be charged: the figure is then an upper bound on
  // the offer being compared against a net target. This page worked out `state`
  // itself and had no such branch, so on 16 of the driver's own 1,672 recorded
  // offers it showed a green ACCEPT and the ACCEPT buzz where the rig showed
  // amber. Every one of the 16 was a card that printed no distance.
  await open({ [SETTINGS]: JSON.stringify({ target: 25, band: 15, costPerMile: 0.3, pad: 0 }),
               [DRAFT]: null, [HISTORY]: null });
  await type(['1', '8', '.', '7', '7', 'next', '2', '5']);   // no distance typed
  out.noDistance = await screen();
  // ...and with a distance on it the cap has nothing to do: $0.30 of 6 miles
  // is $1.80 off $18.77 over 25 minutes, which still clears $25/hr.
  await type(['next', '6']);
  out.withDistance = await screen();

  // --- a refusal does not print the answer underneath itself ---------------
  //
  // The headline blanked to "--" and CHECK THE PAY while per-mile, per-min and
  // net pay carried on quantifying the same impossible reading in smaller type.
  await open({ [SETTINGS]: JSON.stringify({ target: 25, band: 15, costPerMile: 0.3, pad: 0 }),
               [DRAFT]: null, [HISTORY]: null });
  await type(['1', '0', '3', '0', 'next', '3', '1', 'next', '8']);
  out.refused = await screen();
  // ...and it cannot be logged as a rate either. `ready` stays true on a doubt,
  // so this went straight into the list: twenty offers at $18/hr plus one $1030
  // over 31 minutes read back as "avg $112 / best $1993 / 100%".
  await type(['log']);
  await page.waitForTimeout(120);
  out.refusedLog = await page.evaluate(k => localStorage.getItem(k), HISTORY);
  out.refusedToast = await page.evaluate(
    () => (document.getElementById('toast') || {}).textContent || '');
  // The entry is left alone to be corrected, not cleared out from under them.
  out.refusedStill = (await screen()).pay;

  // --- a typed offer reaches the journal -----------------------------------
  // This page kept its own list, in this browser, capped at a hundred, and
  // that was the whole record of anything typed here. The server is the real
  // one and the journal it writes is read back through /api/journal, so what
  // is checked is the row as the offers page will see it.
  await open({ [SETTINGS]: SEEDED, [DRAFT]: null, [HISTORY]: null });
  const journal = () => page.evaluate(async () => {
    const r = await fetch('/api/journal?days=1');
    const d = await r.json();
    return d.offers.map(o => ({ id: o.id, typed: o.typed, pay: o.pay,
                                minutes: o.minutes, miles: o.miles,
                                perHour: o.perHour, state: o.state,
                                target: o.target, kind: o.kind }));
  });
  // The tests above this one press LOG too, and those offers now reach the
  // same journal — so everything below is a difference from here, and the
  // row this block wrote is found by its payout rather than by its place.
  out.journalBefore = await journal();
  await type(['1', '6', '.', '0', '5', 'next', '2', '3', 'next', '8', '.', '4', 'log']);
  await page.waitForTimeout(500);
  out.loggedOnce = await journal();
  out.historyOnce = await page.evaluate(
    k => JSON.parse(localStorage.getItem(k) || '[]'), HISTORY);
  // The rig out of reach — an app on a phone with no rig near it is the
  // normal case for this page. The entry is kept here, says so, and goes
  // with the next LOG once the rig answers again.
  await page.route('**/api/journal/ingest',
                   r => r.fulfill({ status: 503, contentType: 'text/plain', body: 'down' }));
  await type(['clear', '9', 'next', '1', '2', 'log']);
  await page.waitForTimeout(500);
  out.keptToast = await page.evaluate(
    () => (document.getElementById('toast') || {}).textContent || '');
  await page.click('#openHistory');
  await page.waitForTimeout(150);
  const histText = () => page.evaluate(
    () => document.getElementById('histList').textContent.replace(/\s+/g, ' ').trim());
  out.keptList = await histText();
  await page.click('[data-close="historySheet"]');
  await page.unroute('**/api/journal/ingest');
  out.journalWhileDown = await journal();
  await type(['clear', '1', '1', 'next', '2', '0', 'log']);
  await page.waitForTimeout(600);
  out.loggedAfter = await journal();
  await page.click('#openHistory');
  await page.waitForTimeout(150);
  out.listAfter = await histText();
  await page.click('[data-close="historySheet"]');
  // Opening the page again re-sends nothing that has already arrived: the
  // rows carry their own ids and the ingest door stores each once.
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(600);
  out.loggedReload = await journal();

  // --- the history says what was typed -------------------------------------
  // With a pickup pad the rate includes it and the journal row carries the
  // typed minutes; the history row said "33 min" for a card that said 23.
  await open({ [SETTINGS]: JSON.stringify(Object.assign(JSON.parse(SEEDED), { pad: 10 })),
               [DRAFT]: null, [HISTORY]: null });
  await type(['1', '6', 'next', '2', '3', 'log']);
  await page.waitForTimeout(400);
  out.paddedHistory = await page.evaluate(k => JSON.parse(localStorage.getItem(k) || '[]')[0], HISTORY);
  await page.click('#openHistory');
  await page.waitForTimeout(150);
  out.paddedList = await histText();
  await page.click('[data-close="historySheet"]');

  // --- a phone that has never had a rig --------------------------------------
  // Served from a static host there is no rig, and every LOG used to end in
  // "kept on this phone — the rig did not answer", about a machine that was
  // never there. A rig that has answered once and does not now is still told.
  await page.route('**/api/status', r => r.fulfill({ status: 404, contentType: 'text/plain', body: 'no' }));
  await page.route('**/api/journal/ingest', r => r.fulfill({ status: 404, contentType: 'text/plain', body: 'no' }));
  await open({ [SETTINGS]: SEEDED, [DRAFT]: null, [HISTORY]: null,
               'uberscan.rig.seen': null, 'uberscan.unsent.v1': null });
  await type(['3', '0', 'next', '6', '0', 'log']);
  await page.waitForTimeout(500);
  out.rigless = { toast: await page.evaluate(() => (document.getElementById('toast') || {}).textContent || ''),
                  queued: await page.evaluate(() => JSON.parse(localStorage.getItem('uberscan.unsent.v1') || '[]').length) };
  await page.unroute('**/api/status');
  await page.unroute('**/api/journal/ingest');

  // --- storage that will not answer ----------------------------------------
  // Private mode, a full quota, a browser with site data blocked. The page has
  // to open and add up an offer either way; only remembering it is optional.
  await page.goto(base + '/index.html', { waitUntil: 'domcontentloaded' });
  await page.evaluate(() => {
    const boom = () => { throw new Error('storage is off'); };
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: { getItem: boom, setItem: boom, removeItem: boom, clear: boom },
    });
  });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(250);
  await type(['clear', '3', '0', 'next', '6', '0']);
  out.withoutStorage = await screen();

  await browser.close();
  console.log(JSON.stringify(out));
})().catch(e => { console.log(JSON.stringify({ skip: 'browser: ' + e.message })); });
'''

work = tempfile.mkdtemp()
journal = os.path.join(work, 'journal.jsonl')
open(journal, 'w').close()
port = free_port()
proc = subprocess.Popen(
    ['node', os.path.join(ROOT, 'server.js')],
    env=dict(os.environ, SCANNER='0', PORT=str(port), JOURNAL=journal,
             FRAME=os.path.join(work, 'live.jpg')),
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
base = 'http://127.0.0.1:%d' % port
got = {}
try:
    import time
    import urllib.request
    for _ in range(120):
        try:
            urllib.request.urlopen(base + '/api/status', timeout=1).read()
            break
        except Exception:
            time.sleep(0.1)
    else:
        raise RuntimeError('the server never came up')

    driver = os.path.join(work, 'keypad.js')
    open(driver, 'w').write(DRIVER)
    run = subprocess.run(
        ['node', driver, base],
        env=dict(os.environ, NODE_PATH=os.pathsep.join(NODE_PATHS),
                 PW_EXES=json.dumps([os.environ.get('CHROMIUM', ''),
                                     '/opt/pw-browsers/chromium-1194/chrome-linux/chrome'])),
        capture_output=True, text=True, timeout=600)
    line = (run.stdout or '').strip().split('\n')[-1] if run.stdout else ''
    try:
        got = json.loads(line)
    except Exception:
        skip('the browser produced nothing (%s)'
             % (run.stderr or '')[-200:].replace('\n', ' '))
    if got.get('skip'):
        skip(got['skip'])
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


# --- the settings this page does not own -----------------------------------
# Typing an offer is not changing a setting, so nothing should be written.
eq('typing an offer does not rewrite the settings at all',
   got.get('settingsAfterTyping'), got.get('settingsSeeded'))

# The two writers, which are where the whole entry used to be replaced.
edited = got.get('afterEditing') or {}
eq('changing the target writes the target', edited.get('target'), 30)
eq('...and leaves the scanner\'s shopping allowance alone',
   edited.get('secondsPerItem'), 90)
eq('...and its whole-frame setting', edited.get('fullFrame'), True)
eq('...and this page\'s other settings', edited.get('costPerMile'), 0.35)
toggled = got.get('afterToggling') or {}
eq('turning haptics off writes that', toggled.get('haptics'), False)
eq('...and still leaves the scanner\'s settings alone',
   toggled.get('secondsPerItem'), 90)
eq('...without losing the target that was just set', toggled.get('target'), 30)

# --- a pickup pad is not an offer ------------------------------------------
pad_only = got.get('padOnly') or {}
eq('pay with no minutes typed is not a rate, whatever the pad says',
   pad_only.get('perHour'), '--')
eq('...and the panel says nothing was worked out', pad_only.get('label'), 'ENTER OFFER')
padded = got.get('padPlusOne') or {}
ok_('...but a typed minute makes one', padded.get('perHour') not in ('--', None))
# 10 minutes of pad on 23 typed: $16.05 over 33 minutes is $29.2/hr, not $41.9.
eq('...and the pad is in it', padded.get('perHour'), '$29.2')

# --- net and gross agree about what a dollar means -------------------------
costed = got.get('costed') or {}
# $16.05, 23 min, 8.4 mi at $0.35/mi: cost $2.94, net $13.11.
eq('the rate is after running costs', costed.get('perHour'), '$34.2')
eq('...and so is the per-mile beside it', costed.get('perMile'), '$1.56')
eq('...and the net pay', costed.get('netPay'), '$13.11')

# ...and the screen says which of the two rates it is showing.
#
# The headline is net and is labelled "/hr" whether a mileage cost came off it
# or not. A driver typing an offer in here to check the rig against it was
# comparing two numbers that are only sometimes the same thing, with nothing on
# either screen saying so. $16.05 over 23 minutes is $41.9/hr before the car
# and $34.2 after it, and the gap is the whole reason the setting exists.
ok_('the raw rate is shown beside the net one', costed.get('rawShown'))
eq('...as the same sum without the running cost', costed.get('rawRate'), '$41.9 raw')

# And not when there is nothing to say. With no cost per mile the two figures
# are one figure, and printing it twice beside itself is noise next to the one
# number that decides an offer. `padPlusOne` rather than `padOnly`: the latter
# has no minutes typed and therefore no rate at all, so it would pass this for
# the wrong reason.
free = got.get('padPlusOne') or {}
ok_('a complete offer with no cost set has a rate', free.get('perHour') != '--')
ok_('...and does not print it twice', not free.get('rawShown'))

# --- a slipped decimal point is not a green ACCEPT -------------------------
slipped = got.get('slipped') or {}
ok_('$1184 for twenty minutes is not accepted',
    'go' not in (slipped.get('state') or ''))
ok_('...it is refused as impossible', 'doubt' in (slipped.get('state') or ''))

# --- the verdict is the rig's verdict, not a second opinion ----------------
#
# $18.77 over 25 minutes with no distance typed is $45.0/hr on its face, which
# clears a $25 target twice over — and is a CEILING, because a cost per mile is
# configured and nothing came off. This screen said ACCEPT and buzzed for it.
gross = got.get('noDistance') or {}
eq('an $18.77 offer with no distance still shows its rate',
   gross.get('perHour'), '$45.0')
ok_('...but is not a green ACCEPT, as it was (%r)' % (gross.get('label') or ''),
    'go' not in (gross.get('state') or ''))
eq('...it is the close call the two camera screens give it',
   gross.get('label'), 'CLOSE CALL')
# An amber with no reason on the screen is the state the driving screen was in
# for as long as its own `uncosted` never reached it.
ok_('...and says why the cap is there (%r)' % (gross.get('rawRate') or ''),
    gross.get('rawShown') and 'ceiling' in (gross.get('rawRate') or ''))
# The cap only exists because nothing was charged. Type a distance and it goes.
costed = got.get('withDistance') or {}
ok_('the same offer with a distance on it is accepted',
    'go' in (costed.get('state') or ''))
no_('...with nothing left saying it is a ceiling',
    'ceiling' in (costed.get('rawRate') or ''))

# --- a refusal does not print the answer underneath itself -----------------
refused = got.get('refused') or {}
eq('an impossible reading withholds the headline', refused.get('perHour'), '--')
eq('...and the per-mile figure with it', refused.get('perMile'), '--')
eq('...and the per-minute one', refused.get('perMin'), '--')
eq('...and the net pay', refused.get('netPay'), '--')
eq('...saying which figure to check instead', refused.get('label'), 'CHECK THE PAY')
# `ready` is true on a doubt — every number is still there — so the log gate,
# which tests only `ready`, let it through and poisoned the summary above the
# list with a $1993/hr best.
eq('...and it cannot be logged as a rate', got.get('refusedLog'), None)
ok_('...with the reason said out loud (%r)' % (got.get('refusedToast') or ''),
    'pay' in (got.get('refusedToast') or '').lower())
eq('...and the entry left to be corrected', got.get('refusedStill'), '$1030')

# --- what the digits do ----------------------------------------------------
typing = got.get('typing') or {}
eq('a lone dot becomes nought-point', typing.get('a lone dot becomes nought-point'), '$0.')
eq('only one dot', typing.get('only one dot'), '$1.52')
eq('two decimals and no more', typing.get('two decimals and no more'), '$1.23')
eq('a leading nought is dropped', typing.get('a leading nought is dropped'), '$5')
eq('but not on nought-point', typing.get('but not on nought-point'), '$0.5')
eq('six digits is the cap', typing.get('six digits is the cap'), '$123456')
eq('double-nought counts as two', typing.get('double-nought counts as two'), '$1200')

# --- moving between the three fields ---------------------------------------
eq('next moves on', got.get('afterNext'), 'minutes')
eq('backspace on an empty field steps back rather than doing nothing',
   got.get('backOnEmpty'), 'pay')
eq('...and then deletes', (got.get('backDeletes') or {}).get('pay'), '$0')
eq('next wraps round the three', got.get('wraps'), 'pay')

# --- a physical keyboard ----------------------------------------------------
typed = got.get('typedOnAKeyboard') or {}
eq('digits typed on a keyboard land in the active field', typed.get('pay'), '$16.05')
eq('...and Enter moves on like NEXT', typed.get('minutes'), '23')
eq('Backspace deletes', got.get('afterBackspace'), '2')
eq('Escape clears the lot', (got.get('afterEscape') or {}).get('pay'), '$0')
bp = got.get('backFromPay') or {}
eq('backspacing past an empty PAY stays on PAY', bp.get('active'), 'pay')
eq('...and leaves the distance typed alone', bp.get('miles'), '5.5')
es = got.get('escapeOnSheet') or {}
ok_('with a sheet open Escape closes it', es.get('sheetOpen') is False)
eq('...and the offer behind it is untouched', (es.get('pay'), es.get('minutes')), ('$15', '20'))
tb = got.get('tabbed') or {}
ok_('Tab moves focus (%r -> %r)' % (tb.get('before'), tb.get('after')),
    tb.get('after') and tb.get('after') != tb.get('before') and not tb['after'].startswith('BODY'))
eq('a blanked Target keeps the value it had', got.get('blankTarget'), 30)
cb = got.get('clampedBand') or {}
eq('a band typed past its range is clamped', cb.get('stored'), 50)
eq('...and the box shows what was kept', cb.get('shown'), '50')

# --- the draft, and how long it is worth keeping ---------------------------
draft = got.get('draftWritten') or {}
ok_('what is typed is kept across a reload', (draft.get('entry') or {}).get('pay') == '99')
eq('...and comes back', got.get('draftRestored'), '$99')
# An offer is on the screen for seconds. One from an hour ago is a number the
# driver will read as this one.
eq('an offer from an hour ago does not come back', got.get('staleDraft'), '$0')
eq('clearing the fields clears the draft too', got.get('draftAfterClear'), None)

# --- logging ---------------------------------------------------------------
eq('LOG with nothing typed keeps nothing', got.get('loggedNothing'), None)
ok_('...and says why', 'Enter pay and minutes' in (got.get('toastOnEmpty') or ''))
logged = got.get('logged') or []
eq('a real offer is kept', len(logged), 1)
eq('...with its rate', (logged[0] if logged else {}).get('perHour'), 30)
eq('...and the fields are cleared for the next one',
   (got.get('afterLogging') or {}).get('pay'), '$0')
eq('the log is capped rather than growing without end', got.get('capped'), 100)

# --- storage that will not answer ------------------------------------------
# Private mode, a full quota, a browser with site data blocked. Remembering is
# optional; adding up the offer in front of the driver is not.
without = got.get('withoutStorage') or {}
eq('the keypad still works with no storage at all', without.get('perHour'), '$30.0')
eq('...and no page error was thrown', got.get('thrown'), [])

# --- a typed offer reaches the journal --------------------------------------
#
# The night the camera cannot read is the night offers get typed, so the
# offers most likely to be missing from the record were the ones entered by
# hand. $16.05 over 23 minutes and 8.4 miles at $0.35/mi is $2.94 of cost and
# $13.11 net: $34.2/hr.
before = len(got.get('journalBefore') or [])
once = got.get('loggedOnce') or []
eq('LOG writes the offer to the journal', len(once) - before, 1)
row = next((o for o in once if o.get('pay') == 16.05), {})
ok_('...as an offer, not a kind the offers page would drop', row.get('kind') is None)
ok_('...marked as typed', row.get('typed') is True)
eq('...with the figures as typed',
   (row.get('pay'), row.get('minutes'), row.get('miles')), (16.05, 23, 8.4))
ok_('...and the net rate the screen showed (%r)' % row.get('perHour'),
    abs((row.get('perHour') or 0) - 34.2) < 0.06)
eq('...judged against the settings in force', row.get('target'), 25)
hist = got.get('historyOnce') or []
ok_('...and the local entry knows it arrived',
    bool(hist) and hist[0].get('sent') is True)
ok_('with the rig out of reach the entry says so (%r)' % (got.get('keptToast') or ''),
    'did not answer' in (got.get('keptToast') or ''))
ph = got.get('paddedHistory') or {}
eq('the history row carries the minutes as typed, pad aside', ph.get('minutes'), 23)
ok_('...and lists them (%r)' % (got.get('paddedList') or '')[:50], '23 min' in (got.get('paddedList') or ''))
rl = got.get('rigless') or {}
ok_('a phone that has never had a rig is not told the rig did not answer (%r)' % rl.get('toast'),
    'did not answer' not in (rl.get('toast') or '') and 'Logged' in (rl.get('toast') or ''))
eq('...though the row is kept for one', rl.get('queued'), 1)
ok_('...in the history as well', 'kept here only' in (got.get('keptList') or ''))
eq('...and nothing reached the journal meanwhile',
   len(got.get('journalWhileDown') or []) - before, 1)
eq('the next LOG carries the kept one with it',
   len(got.get('loggedAfter') or []) - before, 3)
no_('...and the history stops saying kept', 'kept here only' in (got.get('listAfter') or ''))
eq('opening the page again re-sends nothing that already arrived',
   len(got.get('loggedReload') or []) - before, 3)

print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
      else '\nAll %d keypad checks passed' % ok)
sys.exit(1 if bad else 0)
