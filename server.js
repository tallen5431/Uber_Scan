#!/usr/bin/env node
/* Static file server for Uber Scan.
 *
 * This project is a website, not a Node program — the JavaScript in it runs in
 * a browser. Hosts that look for a Node entry point should land here, which is
 * why package.json points "main" and "start" at this file.
 *
 *   node server.js              # http://localhost:8080
 *   PORT=3000 node server.js
 *
 * No dependencies, so there is nothing to install first.
 */

'use strict';

var http = require('http');
var https = require('https');
var fs = require('fs');
var path = require('path');
var url = require('url');

var os = require('os');
var spawn = require('child_process').spawn;

var ROOT = __dirname;
var PORT = parseInt(process.env.PORT, 10) || 8080;
var HTTPS_PORT = parseInt(process.env.HTTPS_PORT, 10) || 8443;
var HOST = process.env.HOST || '0.0.0.0';
var SSL_DIR = path.join(ROOT, 'ssl');

var TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.webmanifest': 'application/manifest+json; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.wasm': 'application/wasm',
  '.txt': 'text/plain; charset=utf-8',
  // Served as an opaque blob on purpose. This is the OCR language model, which
  // the reader inflates itself — labelling it Content-Encoding: gzip would have
  // the browser silently decompress it first and hand the reader garbage.
  '.gz': 'application/octet-stream'
};

/* Things that must never leave the machine, however they are asked for.
 *
 * This server sits on a LAN, on plain http, with no authentication — every
 * file under ROOT is one GET away from anyone on the same wifi. That is fine
 * for a page of HTML and catastrophic for `ssl/ca-key.pem`, which is the
 * private key of the certificate authority `tools/make-cert.sh` asks you to
 * install on your phone as a trust anchor. Anyone who fetches it can mint a
 * certificate your phone will believe, for any site.
 *
 * `rpi/` is denied because nothing there is meant for a browser: the live
 * frame has its own route, and config.json is the rig's calibration.
 */
var PRIVATE = /(^|\/)(ssl|rpi|node_modules|\.git)(\/|$)|(^|\/)\./i;
var SECRET_EXT = /\.(pem|key|crt|cer|p12|pfx|jks)$/i;

function isPrivate(pathname) {
  return PRIVATE.test(pathname) || SECRET_EXT.test(pathname);
}

/* ---------- the Pi scanner, as a child of this process ----------
 *
 * Started automatically when rpi/config.json exists, because that file only
 * exists once the camera has been aimed and calibrated — which is exactly the
 * point at which running the scanner starts making sense. There is no
 * environment variable to set, since a process manager runs `npm start` with no
 * shell to set one in. SCANNER=0 turns it off.
 */
var scanner = {
  proc: null,
  last: null,          // most recent read
  phase: null,         // check / aim / calibrated / scanning / error
  status: null,        // most recent non-read message, e.g. aiming progress
  started: null,
  restarts: 0,
  error: null
};

var listeners = [];    // open server-sent-event responses

// The autopilot calibrates itself, so it runs whenever the Pi scanner code is
// present — waiting for a config file would mean waiting for a manual step that
// no longer exists.
function scannerEnabled() {
  if (process.env.SCANNER === '0') return false;
  try {
    fs.statSync(path.join(ROOT, 'rpi', 'autopilot.py'));
    return true;
  } catch (e) {
    return false;
  }
}

function calibrated() {
  try {
    fs.statSync(path.join(ROOT, 'rpi', 'config.json'));
    return true;
  } catch (e) {
    return false;
  }
}

function startScanner() {
  var cmd = process.env.SCANNER_CMD;
  var args = cmd ? [] : [path.join(ROOT, 'rpi', 'autopilot.py'), '--json'];
  var bin = cmd || 'python3';
  if (cmd) args = process.env.SCANNER_ARGS ? process.env.SCANNER_ARGS.split(' ') : [];
  if (process.env.SCANNER_SPEAK !== '0' && !cmd) args.push('--speak');

  scanner.proc = spawn(bin, args, { cwd: ROOT });
  scanner.started = Date.now();
  scanner.error = null;
  console.log('scanner: started ' + bin + ' ' + args.join(' '));

  // Without this, a missing python3 or a bad SCANNER_CMD emits an 'error' with
  // nothing listening, which in Node is an uncaught exception — so the failure
  // to start the scanner takes down the web server that was reporting on it.
  // The site is meant to keep working when the camera side does not.
  scanner.proc.on('error', function (err) {
    scanner.error = 'could not start ' + bin + ': ' + err.message;
    console.error('scanner: ' + scanner.error);
  });

  var buffered = '';
  scanner.proc.stdout.on('data', function (chunk) {
    buffered += chunk.toString();
    var lines = buffered.split('\n');
    buffered = lines.pop();          // keep the partial line for next time
    lines.forEach(function (line) {
      line = line.trim();
      if (!line) return;
      try {
        var read = JSON.parse(line);
        read.at = Date.now();
        if (read.phase) {
          scanner.phase = read.phase;
          scanner.status = read;
          if (read.message) console.log('scanner[' + read.phase + ']: ' + read.message);
        }
        // Setup messages carry no rate, so they must not overwrite the last read.
        if (read.ready !== undefined) scanner.last = read;
        broadcast(read);
      } catch (e) {
        console.log('scanner: ' + line);   // not JSON, so it is a log line
      }
    });
  });

  scanner.proc.stderr.on('data', function (c) {
    var text = c.toString().trim();
    if (text) console.error('scanner: ' + text);
    scanner.error = text.split('\n').slice(-3).join(' ');
  });

  scanner.proc.on('exit', function (code, signal) {
    console.error('scanner: exited (' + (signal || code) + ')');
    scanner.proc = null;
    if (shuttingDown) return;
    // Back off so a camera that is missing or busy does not spin the CPU.
    var delay = Math.min(60000, 3000 * Math.pow(2, Math.min(scanner.restarts, 4)));
    scanner.restarts++;
    console.error('scanner: retrying in ' + Math.round(delay / 1000) + 's');
    setTimeout(startScanner, delay);
  });
}

var WATCH_PATH = path.join(ROOT, 'rpi', '.viewing');
var lastTouch = 0;

function touchWatchFile() {
  var now = Date.now();
  if (now - lastTouch < 1000) return;      // the mtime only needs to be recent
  lastTouch = now;
  fs.writeFile(WATCH_PATH, '', function () {});
}

function broadcast(read) {
  var payload = 'data: ' + JSON.stringify(read) + '\n\n';
  listeners = listeners.filter(function (res) {
    try {
      res.write(payload);
      return true;
    } catch (e) {
      return false;
    }
  });
}

var shuttingDown = false;
['SIGTERM', 'SIGINT'].forEach(function (sig) {
  process.on(sig, function () {
    shuttingDown = true;
    if (scanner.proc) scanner.proc.kill('SIGTERM');
    process.exit(0);
  });
});

function send(res, status, body, headers) {
  res.writeHead(status, Object.assign({ 'Cache-Control': 'no-cache' }, headers || {}));
  res.end(body);
}

function handler(req, res) {
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    return send(res, 405, 'method not allowed', { 'Content-Type': 'text/plain' });
  }

  var pathname;
  try {
    pathname = decodeURIComponent(url.parse(req.url).pathname);
  } catch (e) {
    return send(res, 400, 'bad request', { 'Content-Type': 'text/plain' });
  }

  if (pathname === '/api/status') {
    return send(res, 200, JSON.stringify({
      scanner: {
        enabled: scannerEnabled(),
        calibrated: calibrated(),
        phase: scanner.phase,
        running: !!scanner.proc,
        restarts: scanner.restarts,
        startedAt: scanner.started,
        error: scanner.error
      },
      last: scanner.last,
      status: scanner.status
    }), { 'Content-Type': 'application/json; charset=utf-8' });
  }

  // The scanner writes this every couple of seconds while it runs. Serving it
  // from here means the live view needs no second server and no camera of its
  // own — the one process holding the camera is the one producing the picture.
  if (pathname === '/api/frame.jpg') {
    // Tell the scanner someone is looking, so it refreshes the view quickly
    // instead of on its idle tick. Throttled: this fires twice a second.
    touchWatchFile();
    var framePath = path.join(ROOT, 'rpi', 'live-frame.jpg');
    return fs.readFile(framePath, function (err, data) {
      if (err) {
        return send(res, 404, 'no frame yet', { 'Content-Type': 'text/plain' });
      }
      send(res, 200, data, {
        'Content-Type': 'image/jpeg',
        'Content-Length': data.length,
        'Cache-Control': 'no-store'
      });
    });
  }

  if (pathname === '/api/events') {
    res.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive'
    });
    res.write('retry: 2000\n\n');
    if (scanner.last) res.write('data: ' + JSON.stringify(scanner.last) + '\n\n');
    listeners.push(res);
    req.on('close', function () {
      listeners = listeners.filter(function (r) { return r !== res; });
    });
    return;
  }

  if (pathname.endsWith('/')) pathname += 'index.html';

  // Resolve first, then confirm the result is still inside ROOT, so "..", an
  // encoded traversal and an absolute path all fail the same way.
  var file = path.resolve(ROOT, '.' + pathname);
  if ((file !== ROOT && !file.startsWith(ROOT + path.sep)) || isPrivate(pathname)) {
    return send(res, 403, 'forbidden', { 'Content-Type': 'text/plain' });
  }

  // ...and again after following links. Resolving the *path* proves nothing
  // about where a symlink inside ROOT actually points, and a lexical check
  // alone would happily serve whatever it aims at.
  fs.realpath(file, function (linkErr, real) {
    if (linkErr) return send(res, 404, 'not found', { 'Content-Type': 'text/plain' });
    if (real !== ROOT && !real.startsWith(ROOT + path.sep)) {
      return send(res, 403, 'forbidden', { 'Content-Type': 'text/plain' });
    }
    serveFile(req, res, real);
  });
}

function serveFile(req, res, file) {
  fs.stat(file, function (err, stat) {
    if (err || !stat.isFile()) {
      return send(res, 404, 'not found', { 'Content-Type': 'text/plain' });
    }
    var headers = {
      'Content-Type': TYPES[path.extname(file).toLowerCase()] || 'application/octet-stream',
      'Content-Length': stat.size,
      'Cache-Control': 'no-cache'
    };
    if (req.method === 'HEAD') return send(res, 200, '', headers);

    res.writeHead(200, headers);
    var stream = fs.createReadStream(file);
    stream.on('error', function () { res.destroy(); });
    stream.pipe(res);
  });
}

// Browsers gate the camera, home-screen install and service workers behind a
// secure context, so over plain http on a LAN address the scanner cannot open a
// camera at all.
//
// Certificates are found on disk rather than configured, because the usual way
// this runs is a process manager invoking `npm start` — there is no shell in
// which to set an environment variable. Drop a pair in ./ssl (npm run cert) and
// https starts appearing on the next restart, alongside http rather than
// instead of it, so nothing that already points at the http port breaks.
function findCert() {
  var cert = process.env.SSL_CERT || path.join(SSL_DIR, 'cert.pem');
  var key = process.env.SSL_KEY || path.join(SSL_DIR, 'key.pem');
  try {
    return { cert: fs.readFileSync(cert), key: fs.readFileSync(key), certPath: cert };
  } catch (e) {
    return null;
  }
}

function lanAddresses() {
  var out = [];
  var ifaces = os.networkInterfaces();
  Object.keys(ifaces).forEach(function (name) {
    (ifaces[name] || []).forEach(function (nic) {
      if (nic.family === 'IPv4' && !nic.internal) out.push(nic.address);
    });
  });
  return out;
}

// A listener that cannot bind must not take the other one down with it. The
// https port failing is an inconvenience; the process dying under a supervisor
// that restarts it is a loop.
function listen(server, port, label, fatal, onReady) {
  server.on('error', function (err) {
    var why = err.code === 'EADDRINUSE' ? 'port ' + port + ' is already in use' : err.message;
    console.error('\ncould not start ' + label + ': ' + why);
    if (fatal) process.exit(1);
    console.error(label + ' is off; the rest of the server is still running.');
  });
  server.listen(port, HOST, onReady);
}

var tls = findCert();

listen(http.createServer(handler), PORT, 'http', true, function () {
  console.log('Uber Scan serving ' + ROOT);
  console.log('  http://localhost:' + PORT + '/');
  lanAddresses().forEach(function (ip) {
    console.log('  http://' + ip + ':' + PORT + '/   (keypad only — see below)');
  });
});

if (tls) {
  listen(https.createServer({ cert: tls.cert, key: tls.key }, handler),
         HTTPS_PORT, 'https', false, function () {
    console.log('\nhttps using ' + tls.certPath);
    lanAddresses().forEach(function (ip) {
      console.log('  https://' + ip + ':' + HTTPS_PORT + '/   <- open this on the phone');
    });
    console.log('A self-signed certificate warns once; accepting it makes the');
    console.log('origin secure, which is what the camera and install need.');
  });
} else {
  console.log('\nNo certificate in ./ssl, so http only. The browser camera page and');
  console.log('home-screen install need a secure context: they work on localhost,');
  console.log('but not over a LAN address. Run `npm run cert` and restart to fix.');
  console.log('(The Pi scanner below does not care — it never touches a browser.)');
}

if (scannerEnabled()) {
  console.log('\nPi scanner running here too' +
    (calibrated() ? '.' : ' — not calibrated yet, so it starts by aiming.'));
  if (!calibrated()) {
    // Deliberately not "localhost": the phone you are holding while you move
    // the mount is not this machine, and localhost there is the phone.
    console.log('  aim the camera: open /live.html — the camera view is live while aiming');
    console.log('  (or http://<this-pi>:8081/ for a full-size stream)');
  }
  console.log('  live verdict: /live.html      state: /api/status');
  startScanner();
} else if (process.env.SCANNER === '0') {
  console.log('\nPi scanner disabled (SCANNER=0).');
}
