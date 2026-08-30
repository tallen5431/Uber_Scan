/* The box a driver draws on the live view, from the browser to the scanner.
   Run with: node tests/crop.test.js

   This is the path that exists for when everything automatic has failed, so it
   is tested end to end rather than as a function: a real server, a real POST,
   and the file the camera side actually reads. It also hands that file to
   rpi/cropbox.py when python3 is around, because the two halves agreeing about
   the format is the whole point of there being a file at all. */

var http = require('http');
var fs = require('fs');
var path = require('path');
var spawn = require('child_process').spawn;

var ROOT = path.join(__dirname, '..');
/* Where the request lands, asked of the shipped rule rather than written out
   again here. The three handoff files moved to /dev/shm — see rpi/handoff.py —
   and a test carrying its own copy of a path is a test that goes on passing
   against a server writing somewhere else, which is the one failure this file
   exists to catch. */
var CROP_PATH = (function () {
  try {
    fs.accessSync('/dev/shm', fs.constants.W_OK);
    if (fs.statSync('/dev/shm').isDirectory()) return '/dev/shm/uberscan-cropbox.json';
  } catch (e) { /* no shm here */ }
  return path.join(ROOT, 'rpi', '.cropbox.json');
})();
var PORT = 8791;

var ok = 0, bad = 0;
function eq(name, got, want) {
  if (JSON.stringify(got) === JSON.stringify(want)) ok++;
  else { bad++; console.log('FAIL  ' + name + ': got ' + JSON.stringify(got) + ' want ' + JSON.stringify(want)); }
}
function ok_(name, cond) { eq(name, !!cond, true); }

function post(body) {
  return new Promise(function (resolve, reject) {
    var payload = typeof body === 'string' ? body : JSON.stringify(body);
    var req = http.request({
      host: '127.0.0.1', port: PORT, path: '/api/crop', method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(payload) }
    }, function (res) {
      var text = '';
      res.on('data', function (c) { text += c; });
      res.on('end', function () {
        var parsed = null;
        try { parsed = JSON.parse(text); } catch (e) {}
        resolve({ status: res.statusCode, body: parsed });
      });
    });
    req.on('error', reject);
    req.write(payload);
    req.end();
  });
}

function written() {
  try { return JSON.parse(fs.readFileSync(CROP_PATH, 'utf8')); } catch (e) { return null; }
}

function clear() {
  try { fs.unlinkSync(CROP_PATH); } catch (e) {}
}

// SCANNER=0 so the test does not try to start a camera it does not have.
var server = spawn(process.execPath, [path.join(ROOT, 'server.js')], {
  env: Object.assign({}, process.env, { PORT: String(PORT), SCANNER: '0', HTTPS_PORT: '0' }),
  stdio: ['ignore', 'ignore', 'inherit']
});

function waitForServer(tries) {
  return new Promise(function (resolve, reject) {
    http.get({ host: '127.0.0.1', port: PORT, path: '/api/status' }, function (res) {
      res.resume();
      resolve();
    }).on('error', function (e) {
      if (tries <= 0) return reject(e);
      setTimeout(function () { waitForServer(tries - 1).then(resolve, reject); }, 100);
    });
  });
}

(async function () {
  try {
    await waitForServer(50);
    clear();

    // A dragged rectangle, which is what the live page sends.
    var res = await post({ box: [0.1, 0.2, 0.5, 0.6] });
    eq('a dragged box is accepted', res.status, 200);
    eq('...and comes back as ordered corners', res.body.quad,
       [[0.1, 0.2], [0.6, 0.2], [0.6, 0.8], [0.1, 0.8]]);
    eq('...and is what lands in the file for the scanner',
       written(), { quad: [[0.1, 0.2], [0.6, 0.2], [0.6, 0.8], [0.1, 0.8]] });

    // Fractions, never pixels: the picture drawn on is a 480px JPEG of a
    // 2328px sensor frame, and corners measured against one size and read
    // against another are refused on every check, silently, forever.
    ok_('every corner is a fraction of the frame',
        written().quad.every(function (p) {
          return p.every(function (n) { return n >= 0 && n <= 1; });
        }));

    // The same box drawn from the far corner is the same box.
    res = await post({ quad: [[0.6, 0.8], [0.1, 0.8], [0.1, 0.2], [0.6, 0.2]] });
    eq('corners are ordered however they arrive', res.body.quad,
       [[0.1, 0.2], [0.6, 0.2], [0.6, 0.8], [0.1, 0.8]]);

    // A drag off the edge of the picture is an ordinary way to say "out to the
    // edge" — on the mount that works, the phone does run off the frame.
    res = await post({ box: [0.7, 0.7, 0.9, 0.9] });
    eq('a drag past the edge is clamped, not refused', res.body.quad,
       [[0.7, 0.7], [1, 0.7], [1, 1], [0.7, 1]]);

    clear();
    var refusals = [
      ['a mis-tap is not a box', { box: [0.5, 0.5, 0.01, 0.01] }],
      ['a box needs four numbers', { box: [0.1, 0.2, 0.5] }],
      ['a quad needs four corners', { quad: [[0.1, 0.2], [0.5, 0.6]] }],
      ['corners are pairs', { quad: [0.1, 0.2, 0.5, 0.6] }],
      ['text is not a coordinate', { box: [0.1, 0.2, '0.5', 0.6] }],
      ['an empty request is not a box', {}],
      ['nor is nonsense', 'not json at all']
    ];
    for (var i = 0; i < refusals.length; i++) {
      var out = await post(refusals[i][1]);
      eq(refusals[i][0] + ' → 400', out.status, 400);
    }
    eq('...and nothing bad was left for the scanner to pick up', written(), null);

    // The other half of the contract: what this server writes is what the
    // camera side parses. Skipped rather than failed where python3 is absent.
    await post({ box: [0.12, 0.34, 0.5, 0.4] });
    var read = await pythonReadsIt();
    if (!read.ran) {
      console.log('note: python3 did not run (' + read.why
                  + '), skipped the cropbox.py round trip');
    } else {
      eq('the scanner reads back the box this server wrote', read.value,
         [[0.12, 0.34], [0.62, 0.34], [0.62, 0.74], [0.12, 0.74]]);
      eq('...and takes it away with it, so it is applied once', written(), null);
    }
  } catch (e) {
    bad++;
    console.log('FAIL  the test itself threw: ' + e.message);
  } finally {
    clear();
    server.kill('SIGTERM');
  }

  console.log(bad ? '\n' + ok + ' passed, ' + bad + ' FAILED'
                  : '\nAll ' + ok + ' crop-box checks passed');
  process.exit(bad ? 1 : 0);
})();

/* Runs the camera side's reader and says which of three things happened.
 *
 * `null` used to mean both "python3 is not here, skip this" and "python3 ran
 * and there was no pending box" — and the second is a FAILURE dressed as the
 * first. take_request() legitimately returns JSON null when the file is not
 * there, so a round trip that silently wrote nothing reported itself as an
 * absent interpreter and the suite printed "All 16 passed" with 14 of them
 * run. The count moving is the only trace it left.
 *
 * So the outcome is discriminated: `ran` says the interpreter worked, `value`
 * is whatever it said, and only `ran === false` is a reason to skip. */
function pythonReadsIt() {
  return new Promise(function (resolve) {
    var code = 'import json, sys; sys.path.insert(0, "rpi"); import cropbox; ' +
               'print(json.dumps(cropbox.take_request()))';
    var py = spawn('python3', ['-c', code], { cwd: ROOT });
    var out = '', err = '';
    py.stdout.on('data', function (c) { out += c; });
    py.stderr.on('data', function (c) { err += c; });
    py.on('error', function (e) { resolve({ ran: false, why: e.message }); });
    py.on('close', function (status) {
      if (status !== 0) {
        return resolve({ ran: false, why: 'exit ' + status + ': ' + err.trim().slice(-200) });
      }
      try {
        resolve({ ran: true, value: JSON.parse(out.trim()) });
      } catch (e) {
        resolve({ ran: false, why: 'unparsable output: ' + JSON.stringify(out.slice(0, 120)) });
      }
    });
  });
}
