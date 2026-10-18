'use strict';

/*
 * NucBox relay primitives.
 *
 * This module deliberately knows nothing about the scanner, journal, held
 * orders, or HTTP response objects.  It owns the small bounded client used to
 * ask the NucBox and the validation/normalisation rules that define the
 * questions this project is willing to relay.  server.js can keep route
 * dispatch and response writing while sharing these rules.
 *
 * create() takes an env object rather than reading process.env throughout so
 * tests can exercise deployment settings without mutating the process.
 */

var httpDefault = require('http');
var httpsDefault = require('https');
var url = require('url');

var DEFAULT_TIMEOUT_MS = 3000;
var DEFAULT_CACHE_MAX = 500;
var DEFAULT_CACHE_BYTES = 8 * 1024 * 1024;
var DEFAULT_BODY_MAX = 256 * 1024;
var DEFAULT_LIMIT = 10;
var DEFAULT_TERM_MAX = 120;
var DEFAULT_LINE_MAX = 5000;

function positiveNumber(v, dflt) {
  var n = Number(v);
  return isFinite(n) && n > 0 ? n : dflt;
}

function nonNegativeNumber(v, dflt) {
  if (v === undefined || v === null || v === '') return dflt;
  var n = Number(v);
  return isFinite(n) && n >= 0 ? n : dflt;
}

function base(v, name, report) {
  var said = String(v || '').trim();
  if (!said) return null;
  var u;
  try { u = new URL(said); } catch (e) { u = null; }
  if (!u || (u.protocol !== 'http:' && u.protocol !== 'https:')) {
    if (report) report((name || 'NucBox URL') + ' is not an http(s) URL (' + said + '), so it is ignored');
    return null;
  }
  return said.replace(/\/+$/, '');
}

function services(env, report) {
  env = env || {};
  return {
    search: base(env.NUCBOX_SEARCH, 'NUCBOX_SEARCH', report),
    route: base(env.NUCBOX_ROUTER, 'NUCBOX_ROUTER', report),
    streets: base(env.NUCBOX_STREETS, 'NUCBOX_STREETS', report)
  };
}

function point(s) {
  var m = /^(-?\d{1,3}(?:\.\d{1,7})?),(-?\d{1,2}(?:\.\d{1,7})?)$/.exec(String(s));
  if (!m) return null;
  return (Math.abs(Number(m[1])) <= 180 && Math.abs(Number(m[2])) <= 90)
    ? m[1] + ',' + m[2] : null;
}

function box(s) {
  var corners = String(s).split(',');
  var a = corners.length === 4 && point(corners[0] + ',' + corners[1]);
  var b = corners.length === 4 && point(corners[2] + ',' + corners[3]);
  return a && b ? a + ',' + b : null;
}

function term(v, max) {
  max = max || DEFAULT_TERM_MAX;
  var said = String(v === undefined || v === null ? '' : v).trim();
  return said && said.length <= max && !/[\u0000-\u001f]/.test(said) ? said : null;
}

function query(req, allowed) {
  var q = url.parse(req.url, true).query;
  var others = Object.keys(q).filter(function (k) { return allowed.indexOf(k) < 0; });
  if (others.length) return { error: 'refused: ' + others.join(', ') };
  var twice = Object.keys(q).filter(function (k) { return typeof q[k] !== 'string'; });
  if (twice.length) return { error: 'given more than once: ' + twice.join(', ') };
  return { q: q };
}

function streetQuestion(req, which, termMax) {
  termMax = termMax || DEFAULT_TERM_MAX;
  var names = which === 'cross' ? ['a', 'b'] : ['name'];
  var sq = query(req, names.concat(['box']));
  if (sq.error) return sq;
  var out = {};
  for (var i = 0; i < names.length; i++) {
    out[names[i]] = sq.q[names[i]] === undefined ? null : term(sq.q[names[i]], termMax);
    if (!out[names[i]]) {
      return { error: names.join(' and ') + ' must each be 1 to ' + termMax
                      + ' printable characters' };
    }
  }
  out.box = null;
  if (sq.q.box !== undefined) {
    out.box = box(sq.q.box);
    if (!out.box) return { error: 'box is left,top,right,bottom' };
  }
  return out;
}

function streetAnswer(which, body) {
  var fin = function (v) { return typeof v === 'number' && isFinite(v); };
  var names = function (side) {
    return side && Array.isArray(side.names) && side.names.every(function (n) {
      return typeof n === 'string';
    }) ? { names: side.names, how: typeof side.how === 'string' ? side.how : null } : null;
  };
  var cut = body && fin(body.cutAt) ? body.cutAt : null;
  if (which === 'cross') {
    var a = names(body && body.a), b = names(body && body.b);
    if (!body || body.ok !== true || !a || !b || !Array.isArray(body.meets)
        || !body.meets.every(function (m) {
          return m && fin(m.lat) && fin(m.lon) && fin(m.n) && fin(m.spanM);
        })) {
      return { error: 'the NucBox street index answered something that is not where two streets meet' };
    }
    return { ok: true, a: a, b: b, cutAt: cut, meets: body.meets.map(function (m) {
      return { lat: m.lat, lon: m.lon, n: m.n, spanM: m.spanM, shared: !!m.shared };
    }) };
  }
  var s = names(body);
  if (!body || body.ok !== true || !s || !Array.isArray(body.lines)
      || !body.lines.every(function (l) {
        return Array.isArray(l) && l.every(function (pt) {
          return Array.isArray(pt) && pt.length === 2 && fin(pt[0]) && fin(pt[1]);
        });
      })) {
    return { error: 'the NucBox street index answered something that is not a street' };
  }
  return { ok: true, names: s.names, how: s.how, cutAt: cut, lines: body.lines };
}

function line(g, max) {
  max = max || DEFAULT_LINE_MAX;
  var c = g && g.type === 'LineString' && Array.isArray(g.coordinates) ? g.coordinates : null;
  if (!c || c.length < 2 || c.length > max) return null;
  var out = [];
  for (var i = 0; i < c.length; i++) {
    var p = c[i];
    if (!Array.isArray(p) || p.length < 2 || typeof p[0] !== 'number' || typeof p[1] !== 'number'
        || !isFinite(p[0]) || !isFinite(p[1]) || Math.abs(p[0]) > 180 || Math.abs(p[1]) > 90) {
      return null;
    }
    out.push([p[1], p[0]]);
  }
  return out;
}

function Cache(maxCount, maxBytes) {
  this.maxCount = positiveNumber(maxCount, DEFAULT_CACHE_MAX);
  this.maxBytes = nonNegativeNumber(maxBytes, DEFAULT_CACHE_BYTES);
  this.map = new Map();
  this.sizes = new Map();
  this.bytes = 0;
}

Cache.prototype.has = function (key) { return this.map.has(key); };
Cache.prototype.get = function (key) { return this.map.get(key); };
Cache.prototype.size = function () { return this.map.size; };

Cache.prototype.remember = function (key, value) {
  var size = Buffer.byteLength(JSON.stringify(value));
  if (this.map.has(key)) {
    this.bytes -= this.sizes.get(key) || 0;
    this.map.delete(key);
    this.sizes.delete(key);
  }
  if (size > this.maxBytes) return false;
  this.map.set(key, value);
  this.sizes.set(key, size);
  this.bytes += size;
  while (this.map.size > this.maxCount || this.bytes > this.maxBytes) {
    var oldest = this.map.keys().next().value;
    this.bytes -= this.sizes.get(oldest) || 0;
    this.map.delete(oldest);
    this.sizes.delete(oldest);
  }
  return true;
};

function create(options) {
  options = options || {};
  var env = options.env || process.env;
  var report = options.report || function () {};
  var http = options.http || httpDefault;
  var https = options.https || httpsDefault;
  var svc = services(env, report);
  var timeoutMs = positiveNumber(env.NUCBOX_TIMEOUT_MS, DEFAULT_TIMEOUT_MS);
  var bodyMax = positiveNumber(options.bodyMax, DEFAULT_BODY_MAX);
  var limit = positiveNumber(options.limit, DEFAULT_LIMIT);
  var termMax = positiveNumber(options.termMax, DEFAULT_TERM_MAX);
  var lineMax = positiveNumber(options.lineMax, DEFAULT_LINE_MAX);
  var cache = new Cache(options.cacheMax || DEFAULT_CACHE_MAX,
                        nonNegativeNumber(env.NUCBOX_CACHE_BYTES, DEFAULT_CACHE_BYTES));

  function searchTarget(kind, said, viewbox) {
    return svc.search + '/search?format=jsonv2&limit=' + limit + '&' + kind + '='
         + encodeURIComponent(said)
         + (viewbox ? '&viewbox=' + encodeURIComponent(viewbox) + '&bounded=1' : '');
  }

  function hits(body) {
    return { ok: true, cutAt: body.length >= limit ? limit : null,
             hits: body.map(function (h) {
               return { lat: Number(h.lat), lon: Number(h.lon),
                        name: String(h.display_name || '') };
             }).filter(function (h) { return isFinite(h.lat) && isFinite(h.lon); }) };
  }

  function ask(target, done) {
    var u;
    try { u = new URL(target); } catch (e) { return done('the NucBox address is not a URL'); }
    var lib = u.protocol === 'https:' ? https : http;
    var finished = false;
    var req = null;
    var timer = setTimeout(function () {
      end('the NucBox did not answer within ' + (timeoutMs / 1000) + ' s');
      if (req) req.destroy();
    }, timeoutMs);
    function end(err, body) {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      done(err, body);
    }
    req = lib.get(target, { headers: { 'Accept': 'application/json' } }, function (up) {
      var chunks = [], size = 0;
      up.on('data', function (c) {
        size += c.length;
        if (size > bodyMax) {
          end('the NucBox answered with more than ' + bodyMax + ' bytes');
          req.destroy();
          return;
        }
        chunks.push(c);
      });
      up.on('end', function () {
        var parsed;
        try { parsed = JSON.parse(Buffer.concat(chunks).toString('utf8')); }
        catch (e) { parsed = undefined; }
        if (up.statusCode !== 200
            && !(up.statusCode === 400 && parsed && typeof parsed.code === 'string')) {
          return end('the NucBox answered ' + up.statusCode);
        }
        if (parsed === undefined) return end('the NucBox answered something that is not JSON');
        end(null, parsed);
      });
      up.on('error', function (e) {
        end('the NucBox stopped answering (' + (e.code || e.message) + ')');
      });
    });
    req.on('error', function (e) {
      end('the NucBox did not answer (' + (e.code || e.message) + ')');
    });
  }

  return {
    services: svc,
    timeoutMs: timeoutMs,
    bodyMax: bodyMax,
    limit: limit,
    termMax: termMax,
    lineMax: lineMax,
    cache: cache,
    remember: function (key, value) { return cache.remember(key, value); },
    ask: ask,
    searchTarget: searchTarget,
    hits: hits,
    point: point,
    box: box,
    term: function (v) { return term(v, termMax); },
    query: query,
    streetQuestion: function (req, which) { return streetQuestion(req, which, termMax); },
    streetAnswer: streetAnswer,
    line: function (g) { return line(g, lineMax); }
  };
}

module.exports = {
  DEFAULT_TIMEOUT_MS: DEFAULT_TIMEOUT_MS,
  DEFAULT_CACHE_MAX: DEFAULT_CACHE_MAX,
  DEFAULT_CACHE_BYTES: DEFAULT_CACHE_BYTES,
  DEFAULT_BODY_MAX: DEFAULT_BODY_MAX,
  DEFAULT_LIMIT: DEFAULT_LIMIT,
  DEFAULT_TERM_MAX: DEFAULT_TERM_MAX,
  DEFAULT_LINE_MAX: DEFAULT_LINE_MAX,
  base: base,
  services: services,
  point: point,
  box: box,
  term: term,
  query: query,
  streetQuestion: streetQuestion,
  streetAnswer: streetAnswer,
  line: line,
  Cache: Cache,
  create: create
};
