/* A stand-in for the NucBox's two map services, for the suites.
 *
 *   node tests/fake-nucbox.js            # prints {"port": N} and serves
 *   require('./fake-nucbox.js').start()  # the same, in-process
 *
 * ONE fake, shared: tests/mapview.test.js runs it in-process and
 * rpi/test_server.py and rpi/test_dashboard.py spawn it, so the three suites
 * cannot come to disagree about what the NucBox says.
 *
 * The SHAPES are the real install's — Nominatim 4.5's jsonv2 list and OSRM's
 * route object — and so is what it answers for the questions that were asked
 * of the real one on the driver's NucBox:
 *
 *   q=McDonald's in a box round Marietta, bounded     several branches, each
 *                                                     with a house number
 *   street=Shadowood Pkwy SE in a box, no town        two pieces of the street,
 *                                                     in Cumberland
 *   q=Shadowood Pkwy SE, Atlanta, GA                  nothing (any q with a
 *                                                     town after a comma)
 *   street=1985 Cobb Parkway                          three answers at "1985,
 *                                                     Cobb Parkway, Kennesaw"
 *   q=Dave's Hot Chicken                              nothing: not in OSM
 *   route Marietta Square -> Five Points               31307.4 m, 1659.8 s
 *                                                     (its shape is the
 *                                                     fake's, geometryOf)
 *
 * The POINTS are invented round public places (Marietta Square, Cumberland,
 * Kennesaw), never the owner's or a customer's. The duration is kept in the
 * route answer on purpose: server.js must drop it, and a suite can only see
 * that if it was there.
 *
 * And the NucBox's own server.js's two street questions (/api/streets/cross
 * and /stretch), answered in its shape with one fixed corner and stretch.
 *
 * Also: "Church St" is two streets of that name in two towns (two that fit
 * and disagree, whatever the card's town), "Slow Place" answers after two and
 * a half seconds (for the timeout), "4821 Kestrel Dr" answers its street and
 * not the door, "Starbucks" is twelve branches cut at the limit, "Waffle
 * House" is a pickup the road by is shorter than the road direct, "Farm
 * Stand" is 450 m from a road, "250 Example Road" is a restaurant's door (a
 * held order's pickup) and "1975 Cobb Parkway" one 87 m from 1985's door, a
 * point at 34.1, -84.6 is refused by the
 * router with a code that is not NoRoute, a route touching 33.9, -84.7
 * comes back with a shape that is not one, and GET /__asked lists every
 * question this fake was asked, so a suite can read exactly what left the
 * rig. */
'use strict';

var http = require('http');
var url = require('url');

var LICENCE = 'Data © OpenStreetMap contributors, ODbL 1.0. http://osm.org/copyright';

function place(id, lat, lon, cls, type, name, display) {
  return { place_id: id, licence: LICENCE, osm_type: 'node', osm_id: 9000000 + id,
           lat: lat.toFixed(7), lon: lon.toFixed(7), category: cls, type: type,
           place_rank: 30, importance: 0.00001, addresstype: cls, name: name,
           display_name: display,
           boundingbox: [(lat - 0.0001).toFixed(7), (lat + 0.0001).toFixed(7),
                         (lon - 0.0001).toFixed(7), (lon + 0.0001).toFixed(7)] };
}

var MCD = [
  // 2.1 mi north of Marietta Square.
  place(1, 33.9830, -84.5499, 'amenity', 'fast_food', "McDonald's",
        "McDonald's, 1155, Roswell Street Northeast, Marietta, Cobb County, "
        + 'Georgia, 30060, United States'),
  // Cumberland, about 5.5 mi south-east of the Square.
  place(2, 33.9010, -84.4770, 'amenity', 'fast_food', "McDonald's",
        "McDonald's, 2700, Windy Hill Road Southeast, Cumberland, Marietta, "
        + 'Cobb County, Georgia, 30067, United States'),
  // Kennesaw, about 10.6 mi north-west: inside a 9.9 mi box's corner and
  // outside the 9.9 mi disc.
  place(3, 34.0700, -84.6700, 'amenity', 'fast_food', "McDonald's",
        "McDonald's, 3900, Cobb Parkway Northwest, Kennesaw, Cobb County, "
        + 'Georgia, 30144, United States'),
  // Acworth, about 21.8 mi north of the Square.
  place(4, 34.2683, -84.5499, 'amenity', 'fast_food', "McDonald's",
        "McDonald's, 4400, Highway 92, Acworth, Cherokee County, Georgia, "
        + '30102, United States')
];

var SHADOWOOD = [
  place(11, 33.8768, -84.4620, 'highway', 'residential', 'Shadowood Parkway Southeast',
        'Shadowood Parkway Southeast, Cumberland, Cobb County, Georgia, 30339, '
        + 'United States'),
  place(12, 33.8790, -84.4580, 'highway', 'residential', 'Shadowood Parkway Southeast',
        'Shadowood Parkway Southeast, Cumberland, Cobb County, Georgia, 30339, '
        + 'United States')
];

var COBB_1985 = [
  place(21, 34.0010, -84.5560, 'building', 'yes', '',
        '1985, Cobb Parkway, Kennesaw, Cobb County, Georgia, 30152, United States'),
  place(22, 34.0011, -84.5561, 'shop', 'car', '',
        '1985, Cobb Parkway, Kennesaw, Cobb County, Georgia, 30152, United States'),
  place(23, 34.0009, -84.5559, 'place', 'house', '',
        '1985, Cobb Parkway, Kennesaw, Cobb County, Georgia, 30152, United States')
];

/* A door Nominatim does not hold: asked for "4821 Kestrel Dr" it answers the
   street, with no number in the name — what the real one does for a house
   number it lacks, at the same confidence. Invented. */
var KESTREL = [
  place(41, 33.9700, -84.5300, 'highway', 'residential', 'Kestrel Drive',
        'Kestrel Drive, Marietta, Cobb County, Georgia, 30060, United States')
];

/* Twelve branches of one chain: one a mile north of the Square, and eleven
   in the corners of a 3.5 mi disc's box, 4.4 mi out — inside the box and
   outside the disc. The list is cut at the limit asked (ten), so "only one
   fits" is unproven of it. */
var STARBUCKS = [place(51, 33.9671, -84.5499, 'amenity', 'cafe', 'Starbucks',
                       'Starbucks, 100, North Park Square, Marietta, Cobb County, '
                       + 'Georgia, 30060, United States')];
[[1, 1], [1, -1], [-1, 1], [-1, -1]].forEach(function (c, k) {
  for (var i = 0; i < 3 && STARBUCKS.length < 12; i++) {
    var lat = 33.9526 + c[0] * (0.045 - i * 0.001), lon = -84.5499 + c[1] * (0.055 - i * 0.001);
    STARBUCKS.push(place(52 + k * 3 + i, lat, lon, 'amenity', 'cafe', 'Starbucks',
                         'Starbucks, ' + (200 + k * 3 + i) + ', Corner Road, Marietta, '
                         + 'Cobb County, Georgia, 30060, United States'));
  }
});

/* Two pickups the ROUTER treats specially (route() below): through Waffle
   House the road via it comes out 400 m SHORTER than the road direct — OSRM
   routing the fastest road direct and a shorter, slower one by the pickup —
   and Farm Stand sits 450 m from the nearest road, so OSRM moves it that
   far before routing. Each one branch, invented, inside a 3.0 mi card. */
var WAFFLE = [place(71, 33.9300, -84.5100, 'amenity', 'restaurant', 'Waffle House',
                    'Waffle House, 300, Example Road, Marietta, Cobb County, Georgia, '
                    + '30060, United States')];
var FARM = [place(72, 33.9650, -84.5350, 'shop', 'farm', 'Farm Stand',
                  'Farm Stand, Marietta, Cobb County, Georgia, 30060, United States')];

/* A restaurant's door the router routes like any other point: the held
   order's Trip Planner pickup in the suites (street=250 Example Road), 1.7 mi
   north-east of the Square, inside a 9.4 mi card's disc. Invented. */
var GRILL = [place(81, 33.9700, -84.5300, 'amenity', 'restaurant', 'Example Grill',
                   'Example Grill, 250, Example Road, Marietta, Cobb County, Georgia, '
                   + '30060, United States')];

/* ...and one 87 m from the door at 1985 Cobb Parkway (street=1975 Cobb
   Parkway): a restaurant next to a customer's door, which the GPS drop's
   restaurant guard exists for. Invented. */
var DINER = [place(82, 34.0004, -84.5554, 'amenity', 'restaurant', 'Example Diner',
                   'Example Diner, 1975, Cobb Parkway, Kennesaw, Cobb County, Georgia, '
                   + '30152, United States')];

var CHURCH = [
  place(31, 33.9580, -84.5520, 'highway', 'tertiary', 'Church Street',
        'Church Street, Marietta, Cobb County, Georgia, 30060, United States'),
  place(32, 33.8830, -84.5140, 'highway', 'residential', 'Church Street',
        'Church Street, Smyrna, Cobb County, Georgia, 30080, United States')
];

function inBox(p, box) {
  if (!box) return true;
  var v = box.split(',').map(Number);
  var lonLo = Math.min(v[0], v[2]), lonHi = Math.max(v[0], v[2]);
  var latLo = Math.min(v[1], v[3]), latHi = Math.max(v[1], v[3]);
  var lat = Number(p.lat), lon = Number(p.lon);
  return lat >= latLo && lat <= latHi && lon >= lonLo && lon <= lonHi;
}

function search(q) {
  var term = (q.q || q.street || '').toLowerCase().trim();
  var all = [];
  if (q.q !== undefined) {
    // A town after a comma is the shape that found nothing on the real
    // install, whatever the street: OSM's town is not Uber's.
    if (term.indexOf(',') >= 0) all = [];
    else if (term === "mcdonald's") all = MCD;
    else if (term === 'starbucks') all = STARBUCKS;
    else if (term === 'waffle house') all = WAFFLE;
    else if (term === 'farm stand') all = FARM;
  } else if (q.street !== undefined) {
    if (/^shadowood (pkwy|parkway)/.test(term)) all = SHADOWOOD;
    else if (/^1985 cobb (pkwy|parkway)/.test(term)) all = COBB_1985;
    else if (/^4821 kestrel (dr|drive)/.test(term)) all = KESTREL;
    else if (/^church st/.test(term)) all = CHURCH;
    else if (/^250 example (rd|road)/.test(term)) all = GRILL;
    else if (/^1975 cobb (pkwy|parkway)/.test(term)) all = DINER;
  }
  if (q.bounded === '1') all = all.filter(function (p) { return inBox(p, q.viewbox); });
  return all.slice(0, Number(q.limit) || 10);
}

function miles(a, b) {
  var R = 3958.8, r = Math.PI / 180;
  var dLat = (b[1] - a[1]) * r, dLon = (b[0] - a[0]) * r;
  var h = Math.sin(dLat / 2) * Math.sin(dLat / 2)
        + Math.sin(dLon / 2) * Math.sin(dLon / 2) * Math.cos(a[1] * r) * Math.cos(b[1] * r);
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

/* A road a quarter longer than the straight line, leg by leg — except the
   one route measured on the real install, which answers what it answered,
   and any route touching 1985 Cobb Parkway, which answers OSRM's own
   "no road" (HTTP 400, code NoRoute) so a suite can see that said. */
function route(coords) {
  var pts = coords.split(';').map(function (c) { return c.split(',').map(Number); });
  var near = function (p, lon, lat) {
    return Math.abs(p[0] - lon) < 1e-6 && Math.abs(p[1] - lat) < 1e-6;
  };
  if (pts.some(function (p) { return Math.abs(p[0] + 84.5560) < 5e-4 && Math.abs(p[1] - 34.0010) < 5e-4; })) {
    return null;
  }
  // Any point at 34.1, -84.6 is a question OSRM refuses with a code that is
  // NOT NoRoute: the router failing, never "no road".
  if (pts.some(function (p) { return near(p, -84.6, 34.1); })) return 'InvalidQuery';
  if (pts.length === 2 && near(pts[0], -84.5499, 33.9526) && near(pts[1], -84.3880, 33.7490)) {
    return routeBody(pts, [31307.4], [1659.8]);
  }
  // Any point at 33.9, -84.7 is a route whose shape is not one: a point of
  // it with no latitude (for the relay's all-or-nothing check on the line).
  var badShape = pts.some(function (p) { return near(p, -84.7, 33.9); });
  var legs = [], secs = [];
  for (var i = 1; i < pts.length; i++) {
    var m = Math.round(miles(pts[i - 1], pts[i]) * 1.25 * 1609.344 * 10) / 10;
    legs.push(m);
    secs.push(Math.round(m / 13.4 * 10) / 10);
  }
  // By Waffle House: 400 m shorter than the road direct, the whole of it
  // taken off the last leg.
  if (pts.length === 3 && near(pts[1], Number(WAFFLE[0].lon), Number(WAFFLE[0].lat))) {
    var direct = Math.round(miles(pts[0], pts[2]) * 1.25 * 1609.344 * 10) / 10;
    legs[1] = Math.round((direct - 400 - legs[0]) * 10) / 10;
  }
  var body = routeBody(pts, legs, secs);
  if (badShape) body.routes[0].geometry.coordinates[1] = [-84.7];
  return body;
}

// How far OSRM moved each point to reach a road: 3.1 m, except Farm Stand.
function snapOf(p) {
  return Math.abs(p[0] - Number(FARM[0].lon)) < 1e-6 && Math.abs(p[1] - Number(FARM[0].lat)) < 1e-6
    ? 450.0 : 3.1;
}

/* The road's shape, as OSRM's GeoJSON LineString ([lon, lat] pairs): each
   leg drawn east-west first and then north-south, an L, so a suite can tell
   a line drawn along this "road" from the straight line between the same
   points by the corner it turns at. */
function geometryOf(pts) {
  var c = [pts[0]];
  for (var i = 1; i < pts.length; i++) {
    c.push([pts[i][0], pts[i - 1][1]], pts[i]);
  }
  return { type: 'LineString', coordinates: c };
}

function routeBody(pts, legs, secs) {
  var sum = function (xs) { return Math.round(xs.reduce(function (a, b) { return a + b; }, 0) * 10) / 10; };
  return {
    code: 'Ok',
    routes: [{
      geometry: geometryOf(pts),
      legs: legs.map(function (d, i) {
        return { steps: [], summary: '', weight: secs[i], duration: secs[i], distance: d };
      }),
      weight_name: 'routability', weight: sum(secs), duration: sum(secs), distance: sum(legs)
    }],
    waypoints: pts.map(function (p) {
      return { hint: 'fake', distance: snapOf(p), name: '', location: p };
    })
  };
}

function start(done) {
  var asked = [];
  var server = http.createServer(function (req, res) {
    var u = url.parse(req.url, true);
    function json(code, body) {
      res.writeHead(code, { 'Content-Type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify(body));
    }
    if (u.pathname === '/__asked') return json(200, asked);
    asked.push(req.url);
    // The NucBox's own server.js answering from its street index
    // (server.js streetsRoute), in its shapes: one corner for any two names,
    // one short stretch for any name. "Slow Street" answers after two and a
    // half seconds (for the timeout) and "Bad Street" with a meeting that is
    // not a point (for the relay's all-or-nothing check). What a real index
    // answers is tests/streets.test.js's.
    if (u.pathname === '/api/streets/cross' || u.pathname === '/api/streets/stretch') {
      var said = u.query.a || u.query.name || '';
      var cross = u.pathname === '/api/streets/cross';
      var body = cross
        ? { ok: true, a: { names: [String(u.query.a)], how: 'exact', ways: 1 },
            b: { names: [String(u.query.b)], how: 'exact', ways: 1 }, cutAt: null,
            meets: [{ lat: 33.96, lon: -84.55, n: 1, spanM: 0, shared: true }] }
        : { ok: true, names: [String(u.query.name)], how: 'exact', points: 2, cutAt: null,
            lines: [[[33.948, -84.56], [33.948, -84.552]]] };
      if (said === 'Bad Street') {
        if (cross) body.meets.push({ lat: 'north', lon: -84.55, n: 1, spanM: 0 });
        else body.lines[0].push([33.948]);
      }
      if (said === 'Slow Street') return setTimeout(function () { json(200, body); }, 2500);
      return json(200, body);
    }
    if (u.pathname === '/search') {
      if ((u.query.q || '') === 'Slow Place') {
        return setTimeout(function () { json(200, []); }, 2500);
      }
      return json(200, search(u.query));
    }
    var m = /^\/route\/v1\/driving\/([-0-9.,;]+)$/.exec(u.pathname);
    if (m) {
      var r = route(m[1]);
      if (typeof r === 'string') return json(400, { code: r, message: 'Query string malformed' });
      return r ? json(200, r)
        : json(400, { code: 'NoRoute', message: 'Impossible route between points' });
    }
    json(400, { code: 'InvalidUrl', message: 'URL string malformed close to position 1' });
  });
  server.listen(0, '127.0.0.1', function () {
    done({ port: server.address().port, server: server, asked: asked });
  });
}

module.exports = { start: start, MCD: MCD, SHADOWOOD: SHADOWOOD,
                   COBB_1985: COBB_1985, CHURCH: CHURCH, KESTREL: KESTREL,
                   STARBUCKS: STARBUCKS, WAFFLE: WAFFLE, FARM: FARM, GRILL: GRILL,
                   DINER: DINER };

if (require.main === module) {
  start(function (f) { console.log(JSON.stringify({ port: f.port })); });
}
