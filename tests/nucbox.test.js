'use strict';

/* Direct tests for nucbox.js.
 *
 * These are intentionally below the HTTP route layer.  The existing server
 * suites continue to own /api/nbx behavior; this file makes the extracted
 * boundary independently executable before server.js is switched over to it.
 */

var EventEmitter = require('events').EventEmitter;
var N = require('../nucbox.js');

var pass = 0, fail = 0;

function eq(name, got, want) {
  var a = typeof got === 'object' ? JSON.stringify(got) : String(got);
  var b = typeof want === 'object' ? JSON.stringify(want) : String(want);
  if (a === b) pass++;
  else { fail++; console.log('FAIL  ' + name + ': got ' + a + ' want ' + b); }
}

function yes(name, got) { eq(name, !!got, true); }
function no(name, got) { eq(name, !!got, false); }

/* ---- deployment settings ------------------------------------------------ */
(function () {
  var said = [];
  var s = N.services({
    NUCBOX_SEARCH: ' http://nuc:8088/// ',
    NUCBOX_ROUTER: 'https://router.example/',
    NUCBOX_STREETS: 'file:///tmp/nope'
  }, function (m) { said.push(m); });
  eq('search base is trimmed and has no trailing slash', s.search, 'http://nuc:8088');
  eq('https router base is accepted', s.route, 'https://router.example');
  eq('non-http street base is ignored', s.streets, null);
  yes('an invalid configured base is reported', said[0].indexOf('NUCBOX_STREETS') >= 0);
})();

/* ---- points, boxes and terms -------------------------------------------- */
(function () {
  eq('a lon,lat pair is preserved exactly', N.point('-84.5499,33.9526'), '-84.5499,33.9526');
  eq('longitude outside the planet is refused', N.point('181,33'), null);
  eq('latitude outside the planet is refused', N.point('-84,91'), null);
  eq('scientific notation is not a relayed coordinate', N.point('1e2,33'), null);
  eq('a four-coordinate box is two checked points',
     N.box('-84.7,34.1,-84.2,33.6'), '-84.7,34.1,-84.2,33.6');
  eq('a malformed box is refused', N.box('-84.7,34.1,-84.2'), null);
  eq('term whitespace is trimmed', N.term('  Cobb Parkway  ', 120), 'Cobb Parkway');
  eq('control characters are refused in terms', N.term('Cobb\nParkway', 120), null);
  eq('overlong terms are refused', N.term(new Array(122).join('x'), 120), null);
})();

/* ---- query allowlists ---------------------------------------------------- */
(function () {
  var q = N.query({ url: '/api/nbx/search?q=coffee&viewbox=-1%2C1%2C1%2C-1' },
                  ['q', 'street', 'viewbox']);
  eq('allowed query keys survive', q.q.q, 'coffee');
  eq('unexpected query keys refuse the whole question',
     N.query({ url: '/api/nbx/search?q=x&host=elsewhere' }, ['q']).error,
     'refused: host');
  eq('the same key twice is refused',
     N.query({ url: '/api/nbx/search?q=a&q=b' }, ['q']).error,
     'given more than once: q');
})();

/* ---- street questions and answers -------------------------------------- */
(function () {
  var cross = N.streetQuestion({ url: '/api/streets/cross?a=Main&b=Oak&box=-85,34,-84,33' },
                               'cross', 120);
  eq('cross keeps both names', [cross.a, cross.b], ['Main', 'Oak']);
  eq('cross keeps a checked box', cross.box, '-85,34,-84,33');
  yes('cross refuses a missing street name',
      N.streetQuestion({ url: '/api/streets/cross?a=Main' }, 'cross', 120).error);

  var good = N.streetAnswer('cross', {
    ok: true,
    a: { names: ['Main Street'], how: 'exact' },
    b: { names: ['Oak Road'], how: 'alias' },
    cutAt: 4,
    meets: [{ lat: 33.1, lon: -84.2, n: 1, spanM: 12, shared: 1 }]
  });
  eq('cross answer keeps only the relay contract fields', good.meets[0],
     { lat: 33.1, lon: -84.2, n: 1, spanM: 12, shared: true });
  eq('cross answer keeps cutAt', good.cutAt, 4);
  yes('one malformed meeting refuses the complete cross answer',
      N.streetAnswer('cross', {
        ok: true, a: { names: ['Main'] }, b: { names: ['Oak'] },
        meets: [{ lat: 33.1, lon: 'bad', n: 1, spanM: 1 }]
      }).error);

  var stretch = N.streetAnswer('stretch', {
    ok: true, names: ['Main'], how: 'exact', cutAt: null,
    lines: [[[33.1, -84.2], [33.2, -84.3]]]
  });
  eq('stretch answer keeps line geometry', stretch.lines[0][1], [33.2, -84.3]);
  yes('a malformed stretch point refuses the complete answer',
      N.streetAnswer('stretch', {
        ok: true, names: ['Main'], lines: [[[33.1, null], [33.2, -84.3]]]
      }).error);
})();

/* ---- route geometry ------------------------------------------------------ */
(function () {
  eq('GeoJSON lon,lat becomes page lat,lon',
     N.line({ type: 'LineString', coordinates: [[-84.2, 33.1], [-84.3, 33.2]] }),
     [[33.1, -84.2], [33.2, -84.3]]);
  eq('a one-point route is no road line',
     N.line({ type: 'LineString', coordinates: [[-84.2, 33.1]] }), null);
  eq('an off-planet route point refuses the whole line',
     N.line({ type: 'LineString', coordinates: [[-84.2, 33.1], [200, 33.2]] }), null);
  eq('the configured point cap is all-or-nothing',
     N.line({ type: 'LineString', coordinates: [[0, 0], [1, 1], [2, 2]] }, 2), null);
})();

/* ---- search result shape ------------------------------------------------ */
(function () {
  var c = N.create({ env: { NUCBOX_SEARCH: 'http://nuc:8088' }, limit: 2 });
  eq('search target fixes format and limit', c.searchTarget('q', 'Mc Donald', null),
     'http://nuc:8088/search?format=jsonv2&limit=2&q=Mc%20Donald');
  eq('bounded search fixes viewbox and bounded=1', c.searchTarget('street', 'Main', '-85,34,-84,33'),
     'http://nuc:8088/search?format=jsonv2&limit=2&street=Main&viewbox=-85%2C34%2C-84%2C33&bounded=1');
  var out = c.hits([
    { lat: '33.1', lon: '-84.2', display_name: 'one' },
    { lat: 'bad', lon: '-84.3', display_name: 'bad' }
  ]);
  eq('invalid search coordinates are dropped', out.hits, [{ lat: 33.1, lon: -84.2, name: 'one' }]);
  eq('cutAt describes the upstream list, not the filtered list', out.cutAt, 2);
})();

/* ---- bounded FIFO cache ------------------------------------------------- */
(function () {
  var c = new N.Cache(2, 1024);
  c.remember('a', { n: 1 });
  c.remember('b', { n: 2 });
  c.remember('c', { n: 3 });
  no('count bound evicts the oldest answer', c.has('a'));
  yes('count bound keeps newer answers', c.has('b') && c.has('c'));

  c.remember('b', { n: 22 });       // replacement becomes newest
  c.remember('d', { n: 4 });
  no('replacing an answer refreshes its FIFO position', c.has('c'));
  eq('replacement value is kept', c.get('b').n, 22);

  var tiny = new N.Cache(50, 10);
  no('an answer larger than the entire byte budget is not cached',
     tiny.remember('huge', { text: '01234567890123456789' }));
  eq('oversize refusal leaves cache empty', tiny.size(), 0);

  var budget = new N.Cache(50, 26);
  budget.remember('a', { x: '1234' });
  budget.remember('b', { x: '5678' });
  budget.remember('c', { x: 'abcd' });
  yes('byte bound leaves at least the newest answer', budget.has('c'));
  yes('byte bound evicts an older answer when necessary', !budget.has('a'));
})();

/* ---- the client: status, body cap and wall-clock timeout ---------------- */
function response(status, body) {
  var up = new EventEmitter();
  up.statusCode = status;
  process.nextTick(function () {
    if (body !== undefined) up.emit('data', Buffer.from(body));
    up.emit('end');
  });
  return up;
}

function fakeHttp(factory) {
  return {
    get: function (target, opts, cb) {
      var req = new EventEmitter();
      req.destroyed = false;
      req.destroy = function () { req.destroyed = true; };
      factory(target, opts, cb, req);
      return req;
    }
  };
}

function ask(client, target) {
  return new Promise(function (resolve) {
    client.ask(target, function (err, body) { resolve({ err: err, body: body }); });
  });
}

(async function () {
  var accepted = N.create({
    env: { NUCBOX_TIMEOUT_MS: '1000' },
    http: fakeHttp(function (target, opts, cb) {
      cb(response(400, JSON.stringify({ code: 'NoRoute', message: 'No route found' })));
    })
  });
  var a = await ask(accepted, 'http://nuc/route');
  eq('OSRM 400 with a code reaches route interpretation', a.err, null);
  eq('OSRM refusal body is parsed', a.body.code, 'NoRoute');

  var status = N.create({
    env: { NUCBOX_TIMEOUT_MS: '1000' },
    http: fakeHttp(function (target, opts, cb) { cb(response(503, '{}')); })
  });
  var s = await ask(status, 'http://nuc/search');
  eq('ordinary non-200 status is a NucBox failure', s.err, 'the NucBox answered 503');

  var broken = N.create({
    env: { NUCBOX_TIMEOUT_MS: '1000' },
    http: fakeHttp(function (target, opts, cb) { cb(response(200, 'not json')); })
  });
  var j = await ask(broken, 'http://nuc/search');
  eq('non-JSON body is refused', j.err, 'the NucBox answered something that is not JSON');

  var capped = N.create({
    env: { NUCBOX_TIMEOUT_MS: '1000' }, bodyMax: 8,
    http: fakeHttp(function (target, opts, cb) { cb(response(200, '{"long":"answer"}')); })
  });
  var b = await ask(capped, 'http://nuc/search');
  eq('body cap is enforced before parsing', b.err, 'the NucBox answered with more than 8 bytes');

  var timedReq = null;
  var silent = N.create({
    env: { NUCBOX_TIMEOUT_MS: '25' },
    http: fakeHttp(function (target, opts, cb, req) { timedReq = req; })
  });
  var t0 = Date.now();
  var t = await ask(silent, 'http://nuc/never');
  var elapsed = Date.now() - t0;
  eq('wall-clock timeout names the configured interval', t.err,
     'the NucBox did not answer within 0.025 s');
  yes('wall-clock timeout destroys an unresponsive request', timedReq && timedReq.destroyed);
  yes('wall-clock timeout fires without waiting for a socket event', elapsed >= 20 && elapsed < 500);

  var invalid = await ask(silent, 'not a url');
  eq('invalid target is rejected before I/O', invalid.err, 'the NucBox address is not a URL');

  console.log('\n' + pass + ' NucBox module checks passed' + (fail ? ', ' + fail + ' FAILED' : ''));
  process.exit(fail ? 1 : 0);
}()).catch(function (e) {
  console.error(e && e.stack ? e.stack : e);
  process.exit(1);
});
