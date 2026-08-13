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

var ROOT = __dirname;
var PORT = parseInt(process.env.PORT, 10) || 8080;
var HOST = process.env.HOST || '0.0.0.0';

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
  if (pathname.endsWith('/')) pathname += 'index.html';

  // Resolve first, then confirm the result is still inside ROOT, so that "..",
  // encoded traversal and symlinked paths all fail the same way.
  var file = path.resolve(ROOT, '.' + pathname);
  if (file !== ROOT && !file.startsWith(ROOT + path.sep)) {
    return send(res, 403, 'forbidden', { 'Content-Type': 'text/plain' });
  }

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
// camera at all. Point SSL_CERT and SSL_KEY at a certificate to serve https;
// README.md has a one-liner for a self-signed one.
var certPath = process.env.SSL_CERT;
var keyPath = process.env.SSL_KEY;
var server, scheme;

if (certPath && keyPath) {
  server = https.createServer({
    cert: fs.readFileSync(certPath),
    key: fs.readFileSync(keyPath)
  }, handler);
  scheme = 'https';
} else {
  server = http.createServer(handler);
  scheme = 'http';
}

server.listen(PORT, HOST, function () {
  console.log('Uber Scan serving ' + ROOT);
  console.log('  ' + scheme + '://localhost:' + PORT + '/');
  if (scheme === 'http') {
    console.log('\nPlain http. The camera scanner and home-screen install need a');
    console.log('secure context, so they work on localhost but not over a LAN address.');
    console.log('Set SSL_CERT and SSL_KEY to serve https — see README.md.');
  }
});
