"""The lite edition: what the one switch turns off, what it keeps, and the card.

    python3 rpi/test_lite.py
    LITE_SHOTS=/some/dir python3 rpi/test_lite.py    # ...and keep the screenshots

Lite (CLAUDE.md, lite/README.md) is the full rig with a few doors shut, not a
second program, so what can go wrong with it is narrow and has two directions:

  - a door left open — a NucBox question leaving a rig that has no NucBox, an
    upload or a report running on a Zero 2 W;
  - a door shut too far — the verdict, the money rules, the settings or the
    offers log lost along with the map, which would make lite a program that
    tells a driver less than the truth about what an offer pays.

So every "off" below is checked against the same server with the switch the
other way, where it must be on — a check that a fake NucBox was asked nothing
proves nothing until the same fake, asked the same way by a full server, is
seen to be asked. And the card is measured on the three panels lite lists, in
both themes, with the widest figures a card prints.

Its own file rather than a section of test_server.py, test_layout.py and
test_service.py: the switch is read at three seams in files other work edits
every day, and a suite of its own keeps those suites' diffs clean.
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
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'rpi'))
import lite as LT                                             # noqa: E402

os.environ['GPSLOG_DIR'] = ''
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


def done():
    print(('\n%d passed, %d FAILED' % (ok, bad)) if bad
          else '\nAll %d lite checks passed' % ok)
    sys.exit(1 if bad else 0)


# --- the switch, read the same by both halves --------------------------------
#
# The server reads it (lite/lite.js) and so does the scanner it spawns
# (rpi/lite.py). Two readers of one bit that disagreed would give a rig whose
# server shut the map while its scanner still read the label for it, or the
# other way round. So both are asked the same cases.
CASES = [
    # (env LITE, settings in config.json or None for no file, want)
    (None, None, False),             # nothing said: the full rig
    (None, {'lite': True}, True),
    (None, {'lite': 'true'}, False),  # exactly true, as carryTwo is read
    (None, {'lite': 1}, False),
    (None, {'lite': False}, False),
    ('1', None, True),
    ('1', {'lite': False}, True),    # the environment wins...
    ('0', {'lite': True}, False),    # ...both ways
    ('yes', {'lite': True}, True),   # not 1 or 0: the file decides
    ('yes', None, False),
]
_tmp = tempfile.mkdtemp()
try:
    for _i, (_env, _settings, _want) in enumerate(CASES):
        _root = os.path.join(_tmp, str(_i))
        os.makedirs(os.path.join(_root, 'rpi'))
        _cfg = os.path.join(_root, 'rpi', 'config.json')
        if _settings is not None:
            with open(_cfg, 'w') as _fh:
                json.dump({'settings': _settings}, _fh)
        _environ = {} if _env is None else {'LITE': _env}
        eq('rpi/lite.py: LITE=%r, settings %r' % (_env, _settings),
           LT.on_file(_cfg, _environ), _want)
        if shutil.which('node'):
            _js = subprocess.run(
                ['node', '-e', 'process.stdout.write(String(require(%r).on(%r, %s)))'
                 % (os.path.join(ROOT, 'lite', 'lite.js'), _root, json.dumps(_environ))],
                capture_output=True, text=True, timeout=30)
            eq('lite/lite.js agrees: LITE=%r, settings %r' % (_env, _settings),
               _js.stdout.strip(), 'true' if _want else 'false')
    # A config that is not JSON is the full rig, not a crash and not lite.
    _bad = os.path.join(_tmp, 'bad.json')
    open(_bad, 'w').write('{"settings": {"lite": tru')
    eq('an unreadable config is the full rig', LT.on_file(_bad, {}), False)
    eq('...and a loaded config with no settings block too', LT.on({'x': 1}, {}), False)
finally:
    shutil.rmtree(_tmp, ignore_errors=True)

# --- the scanner's seams ------------------------------------------------------
#
# The scanner needs a camera to run, so its seams are held as source: the bit
# read once after the config, the label's thread not started under it, both
# label submits and the bands gated on it. A seam that lost its `lite` would
# put a second OCR pass a card back on a Zero 2 W with nobody to read it.
_sp = open(os.path.join(ROOT, 'rpi', 'scan_pi.py'), encoding='utf-8').read()
ok_('scan_pi reads the switch once, after the config', re.search(
    r'cfg = load_config\(args\.config\)\n(?:\s*#.*\n)*\s*lite = LT\.on\(cfg\)', _sp))
ok_('...starts no map-label thread under it',
    'MapLabels(threaded=not args.no_thread and not lite)' in _sp)
eq('...submits no map label under it, from a card or a press',
   len(re.findall(r'if not lite and [^\n]*\n[^\n]*wants_map_label\(', _sp)), 2)
eq('...and those two are every map-label submit there is',
   len(re.findall(r'map_labels\.submit\(', _sp)), 2)
ok_('...and keeps no map bands under it', re.search(
    r'if lite:\n(?:\s*#.*\n)*\s*log\(\'map bands off \(lite\)\'\)\n\s*elif bands_on', _sp))
# What it must NOT gate: the reader, the verdict, speech, the journal. If any
# of those names ever sits beside `lite` the switch has reached the money.
for _keep in ('Reader(', 'emit(', 'speak', 'JR.', 'OP.rate', 'unsure_payout'):
    ok_('scan_pi does not gate %s on lite' % _keep,
        not re.search(r'\blite\b[^\n]*%s|%s[^\n]*\blite\b' % (re.escape(_keep), re.escape(_keep)),
                      _sp))

# --- the journal sync, off under lite ----------------------------------------
_sj = tempfile.mkdtemp()
try:
    _jf = os.path.join(_sj, 'journal.jsonl')
    open(_jf, 'w').write('{"v":1,"at":1,"kind":"offer","id":"o-1"}\n')
    _cfgf = os.path.join(_sj, 'config.json')
    open(_cfgf, 'w').write('{}')
    # Port 9 on loopback: nothing listens there, so the full sync's answer is
    # its "did not answer" and nothing leaves this machine either way.
    _args = [sys.executable, os.path.join(ROOT, 'rpi', 'sync.py'), '--to', 'http://127.0.0.1:9',
             '--journal', _jf, '--config', _cfgf, '--no-pull']
    _lite = subprocess.run(_args, env=dict(os.environ, LITE='1'),
                           capture_output=True, text=True, timeout=60)
    eq('a lite rig\'s sync exits quietly (0)', _lite.returncode, 0)
    ok_('...and says the journal stays on the rig (%r)' % _lite.stdout.strip()[:80],
        'lite edition' in _lite.stdout and 'nothing sent' in _lite.stdout)
    _full = subprocess.run(_args, env=dict(os.environ, LITE='0'),
                           capture_output=True, text=True, timeout=60)
    ok_('...where the full rig\'s goes looking for the copy (%r)' % _full.stdout.strip()[:80],
        'did not answer' in _full.stdout and 'lite' not in _full.stdout)
finally:
    shutil.rmtree(_sj, ignore_errors=True)

# --- the scripts ----------------------------------------------------------------
for _sh in ('lite/install.sh', 'lite/kiosk.sh', 'rpi/install-service.sh'):
    _p = subprocess.run(['bash', '-n', os.path.join(ROOT, _sh)], capture_output=True, text=True)
    eq('%s parses (bash -n)' % _sh, (_p.returncode, _p.stderr.strip()), (0, ''))
    ok_('...and is executable', os.access(os.path.join(ROOT, _sh), os.X_OK))
    if shutil.which('shellcheck'):
        _sc = subprocess.run(['shellcheck', '-S', 'error', os.path.join(ROOT, _sh)],
                             capture_output=True, text=True)
        eq('%s has no shellcheck errors' % _sh, _sc.stdout.strip(), '')
_inst = open(os.path.join(ROOT, 'lite', 'install.sh'), encoding='utf-8').read()
_kiosk = open(os.path.join(ROOT, 'lite', 'kiosk.sh'), encoding='utf-8').read()
ok_('lite/install.sh installs the service through the full rig\'s installer, with LITE=1',
    re.search(r'LITE=1 [^\n]*bash "\$PROJECT/rpi/install-service\.sh"', _inst))
for _pkg in ('python3-picamera2', 'python3-opencv', 'tesseract-ocr', 'nodejs', 'espeak-ng'):
    ok_('lite/install.sh installs %s' % _pkg, _pkg in _inst)
ok_('...without the recommends that pull a desktop onto Lite',
    _inst.count('--no-install-recommends') >= 2)
ok_('...and replaces its own desktop lines by their marker rather than adding more',
    'grep -vF "$MARK"' in _inst)
ok_('the kiosk waits for the server before opening the browser',
    _kiosk.index('/api/lite') < _kiosk.index('exec "$BROWSER"'))
ok_('...holds a lock, so two autostarts open one card', 'flock -n 9' in _kiosk)
ok_('...and opens full screen with no prompt after a power cut',
    '--kiosk' in _kiosk and '--disable-session-crashed-bubble' in _kiosk)

# The unit itself, as install-service.sh writes it with LITE=1 and without:
# id and systemctl shadowed and /etc pointed into a temp dir, test_service.py's
# own way, so nothing here touches the machine.
if shutil.which('bash'):
    def unit_for(extra):
        work = tempfile.mkdtemp()
        try:
            stub = os.path.join(work, 'bin')
            os.makedirs(stub)
            for name, body in (('id', '#!/bin/sh\necho 0\n'),
                               ('systemctl', '#!/bin/sh\nexit 0\n'),
                               ('logname', '#!/bin/sh\necho driver\n')):
                with open(os.path.join(stub, name), 'w') as fh:
                    fh.write(body)
                os.chmod(os.path.join(stub, name), 0o755)
            unit_dir = os.path.join(work, 'etc')
            os.makedirs(unit_dir)
            os.makedirs(os.path.join(work, 'project', 'rpi'))
            script = open(os.path.join(ROOT, 'rpi', 'install-service.sh')).read().replace(
                '/etc/systemd/system/uberscan.service', os.path.join(unit_dir, 'u.service'))
            run_me = os.path.join(work, 'project', 'rpi', 'install-service.sh')
            open(run_me, 'w').write(script)
            env = dict(os.environ, PATH=stub + os.pathsep + os.environ.get('PATH', ''),
                       SUDO_USER='driver', SPEAK='1', NODE=shutil.which('node') or '/usr/bin/node')
            env.pop('LITE', None)
            env.update(extra)
            p = subprocess.run(['bash', run_me], env=env, capture_output=True, text=True, timeout=60)
            path = os.path.join(unit_dir, 'u.service')
            return p.returncode, (open(path).read() if os.path.exists(path) else '')
        finally:
            shutil.rmtree(work, ignore_errors=True)

    _rc, _unit = unit_for({'LITE': '1'})
    eq('install-service.sh runs with LITE=1', _rc, 0)
    ok_('...and the unit carries Environment=LITE=1', '\nEnvironment=LITE=1\n' in _unit)
    ok_('...beside the scanner\'s own lines, still', 'Environment=SCANNER_SPEAK=1' in _unit
        and 'ExecStart=' in _unit and 'server.js' in _unit)
    _rc0, _unit0 = unit_for({})
    eq('...and without it', _rc0, 0)
    ok_('...the full rig\'s unit has no LITE line at all', 'LITE' not in _unit0)
    _rc2, _unit2 = unit_for({'LITE': 'yes'})
    ok_('...nor does one given anything but 1', 'LITE' not in _unit2)

# --- the server, both ways --------------------------------------------------------
if shutil.which('node') is None:
    print('no node on this machine — skipping the server and page checks')
    done()


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def start(env, journal):
    port = free_port()
    proc = subprocess.Popen(
        ['node', os.path.join(ROOT, 'server.js')],
        env=dict(os.environ, PORT=str(port), HTTPS_PORT='0', JOURNAL=journal, **env),
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    base = 'http://127.0.0.1:%d' % port
    for _ in range(150):
        try:
            urllib.request.urlopen(base + '/api/lite', timeout=1).read()
            return proc, base
        except Exception:
            time.sleep(0.1)
    proc.kill()
    raise RuntimeError('the server never came up')


def stop(proc):
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_opener = urllib.request.build_opener(NoRedirect)


def raw(base, path, body=None, method=None):
    req = urllib.request.Request(base + path, data=body, method=method)
    if body is not None:
        req.add_header('Content-Type', 'application/json')
    try:
        r = _opener.open(req, timeout=8)
        return r.status, r.read().decode('utf-8', 'replace'), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace'), dict(e.headers)


def as_json(text):
    try:
        return json.loads(text)
    except ValueError:
        return None


_fake = subprocess.Popen(['node', os.path.join(ROOT, 'tests', 'fake-nucbox.js')],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
_fake_base = 'http://127.0.0.1:%d' % json.loads(_fake.stdout.readline())['port']


def asked():
    return json.loads(urllib.request.urlopen(_fake_base + '/__asked', timeout=5).read())


# A scanner that reads one card, as rpi/scan_pi.py's emit() puts it on the
# wire: the verdict already decided, which is the point — the server and the
# card only carry it.
_work = tempfile.mkdtemp()
_scanner = os.path.join(_work, 'scanner.py')
with open(_scanner, 'w') as _fh:
    _fh.write(
        'import json, time\n'
        'r = {"ready": True, "locked": True, "whole": True, "state": "go", "perHour": 31.4,\n'
        '     "grossPerHour": 36.0, "billedMinutes": 22, "pay": 14.25, "minutes": 22,\n'
        '     "miles": 6.1, "perMile": 1.98, "cost": 2.14, "costPerMile": 0.35,\n'
        '     "target": 25, "band": 15, "app": "uber",\n'
        '     "pickup": "Example Grill", "dropoff": "250 Example Road",\n'
        '     "places": ["Example Grill", "250 Example Road"],\n'
        '     "offer": {"id": "lite-1", "pay": 14.25, "minutes": 22, "billedMinutes": 22,\n'
        '               "miles": 6.1, "cost": 2.14, "perHour": 31.4, "target": 25, "band": 15,\n'
        '               "costPerMile": 0.35, "state": "go", "app": "uber"}}\n'
        'while True:\n'
        '    r["at"] = int(time.time() * 1000)\n'
        '    print(json.dumps(r), flush=True)\n'
        '    time.sleep(0.5)\n')

NBX_ENV = {'NUCBOX_SEARCH': _fake_base, 'NUCBOX_ROUTER': _fake_base,
           'NUCBOX_STREETS': _fake_base, 'NUCBOX_PROBE_MS': '300',
           'NUCBOX_TIMEOUT_MS': '800',
           'SCANNER': '1', 'SCANNER_CMD': sys.executable, 'SCANNER_ARGS': _scanner}

# Every door lite shuts, with a request that would reach the feature behind it.
SHUT = [
    ('GET', '/api/earnings', None),
    ('POST', '/api/earnings/shot', b'{}'),
    ('GET', '/places/', None),
    ('GET', '/api/placeslink', None),
    ('GET', '/api/shift', None),
    ('GET', '/shift.html', None),
    ('POST', '/api/journal/ingest', b'{"rows": []}'),
    ('POST', '/api/held-end', b'{}'),
    ('POST', '/api/held-pickup', b'{}'),
    ('POST', '/api/mapwalk', b'{}'),
    ('GET', '/map.html', None),
]
# ...and what it keeps, which a phone on the same Wi-Fi uses to set it up.
KEPT = ['/live.html', '/index.html', '/lite/lite.html', '/api/status', '/api/journal',
        '/api/settings', '/api/frame.jpg']

try:
    _lj = os.path.join(_work, 'lite.jsonl')
    open(_lj, 'w').close()
    _before = len(asked())
    _lp, _lb = start(dict(NBX_ENV, LITE='1'), _lj)
    try:
        _s, _body, _h = raw(_lb, '/')
        eq('[lite] / goes to the card', (_s, _h.get('Location')), (302, '/lite/lite.html'))
        _s, _body, _h = raw(_lb, '/lite/lite.html')
        ok_('[lite] ...which is served', _s == 200 and 'id="card"' in _body)
        _info = as_json(raw(_lb, '/api/lite')[1]) or {}
        eq('[lite] /api/lite says so', _info.get('lite'), True)
        ok_('[lite] ...and lists the NucBox among what is off',
            any('NucBox' in w for w in _info.get('off') or []))
        for _method, _path, _data in SHUT:
            _s, _body, _h = raw(_lb, _path, _data, _method)
            _j = as_json(_body) or {}
            eq('[lite] %s %s is shut (404, saying lite)' % (_method, _path),
               (_s, _j.get('lite')), (404, True))
        for _path in KEPT:
            _s, _body, _h = raw(_lb, _path)
            # The frame answers 404 with no picture yet (this server has no
            # camera): kept is "not shut by lite", whatever the route says.
            ok_('[lite] %s is kept (%d)' % (_path, _s),
                _s < 500 and (as_json(_body) or {}).get('lite') is not True
                and (_s == 200 or _path == '/api/frame.jpg'))
        eq('[lite] the NucBox reads as not set, whatever the environment names',
           {k: v for k, v in (as_json(raw(_lb, '/api/nbx')[1]) or {}).items() if k != 'ok'},
           {'search': False, 'route': False, 'streets': False})
        _s, _body, _h = raw(_lb, "/api/nbx/search?q=McDonald%27s&viewbox=-84.65,34.04,-84.45,33.87")
        ok_('[lite] a search asked of the relay is answered "not set", not relayed (%d)' % _s,
            _s != 200 or not (as_json(_body) or {}).get('hits'))
        _s = raw(_lb, '/api/nbx/route?points=-84.5499,33.9526;-84.3880,33.7490')[0]
        ok_('[lite] ...and a route (%d)' % _s, _s != 200)
        # The verdict, carried as ever: the scanner decided it, the server keeps
        # it, /api/status serves it to the card.
        _last = None
        for _ in range(60):
            _last = (as_json(raw(_lb, '/api/status')[1]) or {}).get('last')
            if _last and _last.get('ready'):
                break
            time.sleep(0.1)
        _last = _last or {}
        eq('[lite] the verdict still arrives: state, $/hr, pay, minutes, miles, $/mi',
           [_last.get(k) for k in ('state', 'perHour', 'pay', 'minutes', 'miles', 'perMile')],
           ['go', 31.4, 14.25, 22, 6.1, 1.98])
        eq('[lite] ...against the driver\'s own target and cost per mile',
           [_last.get('target'), _last.get('costPerMile')], [25, 0.35])
        # Long enough for the first probe (a second in) and several more at
        # NUCBOX_PROBE_MS, and the card searched.
        time.sleep(2.0)
        eq('[lite] and not one question reached the NucBox', asked()[_before:], [])
        # The fake does not record its health probes, so they are read where
        # the server keeps their outcome: none, under lite, for no service.
        eq('[lite] ...nor one probe of its health',
           (as_json(raw(_lb, '/api/status')[1]) or {}).get('nucbox'),
           {'search': None, 'route': None, 'streets': None})
    finally:
        stop(_lp)
    ok_('[lite] the banner says which program started',
        'lite edition' in (_lp.stdout.read() if _lp.stdout else ''))

    # The same server, the switch the other way: every door open again, and
    # the same fake asked — which is what makes "asked nothing" above mean
    # something.
    _fj = os.path.join(_work, 'full.jsonl')
    open(_fj, 'w').close()
    _before = len(asked())
    _fp, _fb = start(dict(NBX_ENV, LITE='0'), _fj)
    try:
        _s, _body, _h = raw(_fb, '/')
        ok_('[full] / is the keypad, as ever', _s == 200 and 'data-page="keypad"' in _body)
        eq('[full] /api/lite says not lite', as_json(raw(_fb, '/api/lite')[1]), {'lite': False})
        for _method, _path, _data in SHUT:
            _s, _body, _h = raw(_fb, _path, _data, _method)
            ok_('[full] %s %s is not shut by lite (%d)' % (_method, _path, _s),
                (as_json(_body) or {}).get('lite') is not True)
        eq('[full] the NucBox reads as set',
           {k: v for k, v in (as_json(raw(_fb, '/api/nbx')[1]) or {}).items() if k != 'ok'},
           {'search': True, 'route': True, 'streets': True})
        raw(_fb, "/api/nbx/search?q=McDonald%27s&viewbox=-84.65,34.04,-84.45,33.87")
        time.sleep(2.0)
        ok_('[full] ...and is asked, through the relay (%d)' % len(asked()[_before:]),
            len(asked()[_before:]) >= 1)
        ok_('[full] ...and probed: its search is up',
            ((as_json(raw(_fb, '/api/status')[1]) or {}).get('nucbox') or {})
            .get('search', {}).get('up') is True)
    finally:
        stop(_fp)

    # The NucBox out of reach (server.js nbxOff, the panel's red NO NUCBOX on
    # live.html): a lite rig has no NucBox to miss, so the warning must never
    # come up there, even with an environment that names a NucBox nobody
    # answers at. Port 9 on loopback refuses at once; NUCBOX_OFF_MS shortens
    # the minute the warning waits for. The same settings on a full server
    # raise it, which is what makes its absence under lite mean something.
    _dead = 'http://127.0.0.1:9'
    _off_env = {'NUCBOX_SEARCH': _dead, 'NUCBOX_ROUTER': _dead, 'NUCBOX_STREETS': _dead,
                'NUCBOX_PROBE_MS': '150', 'NUCBOX_OFF_MS': '300', 'NUCBOX_TIMEOUT_MS': '500',
                'SCANNER': '0'}
    for _mode in ('1', '0'):
        _oj = os.path.join(_work, 'off-%s.jsonl' % _mode)
        open(_oj, 'w').close()
        _op, _ob = start(dict(_off_env, LITE=_mode), _oj)
        try:
            _seen = None
            for _ in range(40):
                _seen = (as_json(raw(_ob, '/api/status')[1]) or {}).get('nucboxOff')
                if _seen:
                    break
                time.sleep(0.1)
            if _mode == '1':
                eq('[lite] a NucBox nobody answers at never raises NO NUCBOX', _seen, None)
            else:
                ok_('[full] ...where the full rig raises it (%r)' % (_seen,), bool(_seen))
        finally:
            stop(_op)
finally:
    _fake.kill()

_lite_page = open(os.path.join(ROOT, 'lite', 'lite.html'), encoding='utf-8').read()
ok_('the lite card has no NucBox line of its own to show',
    'nucbox' not in _lite_page.lower())

# --- the card, on every panel lite lists ------------------------------------------
#
# What a screenshot would show: the word, the rate and the four figures each
# inside their own box (nothing cut, nothing scrolled), the card above the
# status line, the status line on the glass, and the rate large enough to read
# from the seat — at the three panels lite/README.md lists and a phone, in
# both themes, with the widest figures a card prints.
NODE_PATHS = [p for p in (os.environ.get('NODE_PATH'), '/opt/node22/lib/node_modules') if p]
PANELS = [('800x480', 800, 480), ('1024x600', 1024, 600), ('480x320', 480, 320),
          ('390x844', 390, 844)]
# Each a message as the stream would carry it, the widest of its kind.
STATES = {
    'accept': {'ready': True, 'locked': True, 'whole': True, 'state': 'go', 'perHour': 108.6,
               'pay': 123.45, 'minutes': 104, 'miles': 38.6, 'perMile': -0.12, 'cost': 13.51,
               'costPerMile': 0.35, 'target': 25},
    'close': {'ready': True, 'locked': False, 'whole': True, 'state': 'warn', 'perHour': 23.9,
              'pay': 9.75, 'minutes': 21, 'cardMinutes': 21, 'fromDeadline': True, 'miles': 4.2,
              'perMile': 1.97, 'cost': 1.47, 'costPerMile': 0.35, 'target': 25, 'cropFrom': 'found'},
    'pass': {'ready': True, 'locked': True, 'whole': True, 'state': 'no', 'perHour': -4.5,
             'pay': 3.0, 'minutes': 40, 'miles': 12.0, 'perMile': -0.1, 'cost': 4.2,
             'costPerMile': 0.35, 'target': 25},
    'doubt': {'ready': True, 'locked': True, 'whole': True, 'state': 'doubt', 'doubt': 'rate',
              'perHour': 990, 'pay': 99.0, 'minutes': 6, 'miles': 1.1, 'perMile': 90,
              'target': 25, 'uncosted': True},
    'waiting': {'tooBright': True},
    'lowpower': {'heatGuard': True, 'throttled': {'now': ['under-voltage']}, 'cpuC': 61},
}
WORDS = {'accept': 'ACCEPT', 'close': 'CLOSE CALL ?', 'pass': 'PASS',
         'doubt': 'CHECK PAY AND TIME', 'waiting': 'WAITING FOR AN OFFER',
         'lowpower': 'WAITING FOR AN OFFER'}

if subprocess.call(['node', '-e', 'require("playwright")'],
                   env=dict(os.environ, NODE_PATH=os.pathsep.join(NODE_PATHS)),
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
    print('no playwright — skipping the card\'s fit')
    shutil.rmtree(_work, ignore_errors=True)
    done()

DRIVER = r'''
const { chromium } = require('playwright');
const [base, panelsJson, statesJson, shots] = process.argv.slice(2);
const PANELS = JSON.parse(panelsJson), STATES = JSON.parse(statesJson);
const fs = require('fs');
(async () => {
  let browser;
  for (const exe of JSON.parse(process.env.PW_EXES || '[]').concat([null])) {
    try { browser = await chromium.launch(exe ? { executablePath: exe } : {}); break; }
    catch (e) { /* the next */ }
  }
  if (!browser) { console.log(JSON.stringify({ skip: 'no chromium' })); return; }
  const out = {};
  for (const [name, w, h] of PANELS) {
    for (const scheme of ['dark', 'light']) {
      const ctx = await browser.newContext({ viewport: { width: w, height: h },
                                             colorScheme: scheme });
      const page = await ctx.newPage();
      // A scanner that is running, whatever this test server says (it runs
      // none, and the card would rightly say "scanner is off").
      await page.route('**/api/status', (r) => r.fulfill({ contentType: 'application/json',
        body: JSON.stringify({ scanner: { enabled: true, running: true } }) }));
      for (const [state, msg] of Object.entries(STATES)) {
        // A fresh page per state, so the card before it cannot linger.
        await page.goto(base + '/lite/lite.html');
        await page.waitForFunction(() => window.__lite);
        await page.evaluate((m) => window.__lite.take(m), msg);
        const m = await page.evaluate(() => {
          const box = (s) => { const e = document.querySelector(s); const r = e.getBoundingClientRect();
            return { top: r.top, bottom: r.bottom, left: r.left, right: r.right,
                     sw: e.scrollWidth, cw: e.clientWidth, text: e.textContent,
                     font: parseFloat(getComputedStyle(e).fontSize),
                     bg: getComputedStyle(e).backgroundColor, color: getComputedStyle(e).color }; };
          const figs = Array.from(document.querySelectorAll('.figs b, .figs small')).map((e) => ({
            sw: e.scrollWidth, cw: e.clientWidth, text: e.textContent }));
          return { word: box('#word'), rate: box('#rate'), card: box('#card'),
                   footer: box('footer'), status: box('#status'), target: box('#target'), figs,
                   docW: document.documentElement.scrollWidth, docH: document.documentElement.scrollHeight,
                   bodyBg: getComputedStyle(document.body).backgroundColor,
                   vw: innerWidth, vh: innerHeight };
        });
        out[name + ' ' + scheme + ' ' + state] = m;
        if (shots) await page.screenshot({ path: shots + '/lite-' + name + '-' + scheme + '-' + state + '.png' });
      }
      await ctx.close();
    }
  }
  await browser.close();
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e && e.stack || e); process.exit(1); });
'''

_shots = os.environ.get('LITE_SHOTS', '')
if _shots:
    os.makedirs(_shots, exist_ok=True)
_pj = os.path.join(_work, 'page.jsonl')
open(_pj, 'w').close()
# No scanner and no stream messages of its own: the driver feeds the card.
_pp, _pb = start({'SCANNER': '0', 'LITE': '1'}, _pj)
try:
    _drv = os.path.join(_work, 'lite-fit.js')
    open(_drv, 'w').write(DRIVER)
    _run = subprocess.run(
        ['node', _drv, _pb, json.dumps(PANELS), json.dumps(STATES), _shots],
        env=dict(os.environ, NODE_PATH=os.pathsep.join(NODE_PATHS),
                 PW_EXES=json.dumps([os.environ.get('CHROMIUM', ''),
                                     '/opt/pw-browsers/chromium-1194/chrome-linux/chrome'])),
        capture_output=True, text=True, timeout=300)
finally:
    stop(_pp)
    shutil.rmtree(_work, ignore_errors=True)

_res = None
try:
    _res = json.loads(_run.stdout.strip().split('\n')[-1])
except (ValueError, IndexError):
    _res = None
if _res is None:
    eq('the card\'s fit driver ran', _run.stderr.strip()[-400:], '')
    done()
if _res.get('skip'):
    print('%s — skipping the card\'s fit' % _res['skip'])
    done()

for _key in sorted(_res):
    _m = _res[_key]
    _state = _key.split(' ')[-1]
    eq('%s: the word is %s' % (_key, WORDS[_state]), _m['word']['text'], WORDS[_state])
    ok_('%s: the page does not scroll (%dx%d in %dx%d)'
        % (_key, _m['docW'], _m['docH'], _m['vw'], _m['vh']),
        _m['docW'] <= _m['vw'] and _m['docH'] <= _m['vh'])
    for _part in ('word', 'rate', 'status', 'target'):
        ok_('%s: the %s is not cut (%d of %d px)' % (_key, _part, _m[_part]['sw'], _m[_part]['cw']),
            _m[_part]['sw'] <= _m[_part]['cw'] + 1)
    _cut = [f['text'] for f in _m['figs'] if f['sw'] > f['cw'] + 1]
    eq('%s: no figure or label is cut' % _key, _cut, [])
    ok_('%s: the card ends above the status line' % _key,
        _m['card']['bottom'] <= _m['footer']['top'] + 0.5)
    ok_('%s: the status line is on the glass' % _key, _m['footer']['bottom'] <= _m['vh'] + 0.5)
    # Readable from the seat: the rate at least 60px on the 3.5" panel and
    # more on the bigger ones, the word at least 30px — chosen, against the
    # full rig's own panel, whose rate is 64px at 480x320.
    _short = min(_m['vw'], _m['vh'])
    ok_('%s: the rate is large (%.0fpx)' % (_key, _m['rate']['font']),
        _m['rate']['font'] >= max(60, 0.22 * _short))
    ok_('%s: the word is large (%.0fpx)' % (_key, _m['word']['font']), _m['word']['font'] >= 30)

# The verdict's colour is the card's, and a fault is never one: the waiting card
# has no verdict fill in either theme.
for _panel in ('800x480',):
    for _scheme in ('dark', 'light'):
        _bgs = {s: _res['%s %s %s' % (_panel, _scheme, s)]['card']['bg'] for s in STATES}
        eq('%s %s: ACCEPT, CLOSE CALL, PASS and a doubt are four different cards'
           % (_panel, _scheme), len({_bgs['accept'], _bgs['close'], _bgs['pass'], _bgs['doubt']}), 4)
        ok_('%s %s: and the card with no verdict is none of them' % (_panel, _scheme),
            _bgs['waiting'] not in (_bgs['accept'], _bgs['close'], _bgs['pass']))
    ok_('%s: the light theme is light and the dark one dark' % _panel,
        _res['%s light accept' % _panel]['bodyBg'] != _res['%s dark accept' % _panel]['bodyBg'])
# What the status line says for the two states the owner named.
eq('LOW POWER is said on the status line',
   _res['800x480 dark lowpower']['status']['text'], 'LOW POWER — check the power lead')
eq('...and a payout read off a found card is "pay ?", as on live.html',
   [f['text'] for f in _res['800x480 dark close']['figs']][1], 'pay ?')
eq('...and a delivery\'s deadline minutes are "min left"',
   [f['text'] for f in _res['800x480 dark close']['figs']][3], 'min left')
ok_('...and a doubt shows no rate', _res['800x480 dark doubt']['rate']['text'] == '--')

done()
