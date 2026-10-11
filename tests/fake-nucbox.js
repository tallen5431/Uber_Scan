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
 *
 * The POINTS are invented round public places (Marietta Square, Cumberland,
 * Kennesaw), never the owner's or a customer's. The duration is kept in the
 * route answer on purpose: server.js must drop it, and a suite can only see
 * that if it was there.
 *
 * Also: "Church St" is two streets of that name in two towns (for the town
 * tie-break), "Slow Place" answers after two and a half seconds (for the timeout), and
 * GET /__asked lists every question this fake was asked, so a suite can read
 * exactly what left the rig. */
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
  } else if (q.street !== undefined) {
    if (/^shadowood (pkwy|parkway)/.test(term)) all = SHADOWOOD;
    else if (/^1985 cobb (pkwy|parkway)/.test(term)) all = COBB_1985;
    else if (/^church st/.test(term)) all = CHURCH;
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
  if (pts.length === 2 && near(pts[0], -84.5499, 33.9526) && near(pts[1], -84.3880, 33.7490)) {
    return routeBody(pts, [31307.4], [1659.8]);
  }
  var legs = [], secs = [];
  for (var i = 1; i < pts.length; i++) {
    var m = Math.round(miles(pts[i - 1], pts[i]) * 1.25 * 1609.344 * 10) / 10;
    legs.push(m);
    secs.push(Math.round(m / 13.4 * 10) / 10);
  }
  return routeBody(pts, legs, secs);
}

function routeBody(pts, legs, secs) {
  var sum = function (xs) { return Math.round(xs.reduce(function (a, b) { return a + b; }, 0) * 10) / 10; };
  return {
    code: 'Ok',
    routes: [{
      legs: legs.map(function (d, i) {
        return { steps: [], summary: '', weight: secs[i], duration: secs[i], distance: d };
      }),
      weight_name: 'routability', weight: sum(secs), duration: sum(secs), distance: sum(legs)
    }],
    waypoints: pts.map(function (p) {
      return { hint: 'fake', distance: 3.1, name: '', location: p };
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
    if (u.pathname === '/search') {
      if ((u.query.q || '') === 'Slow Place') {
        return setTimeout(function () { json(200, []); }, 2500);
      }
      return json(200, search(u.query));
    }
    var m = /^\/route\/v1\/driving\/([-0-9.,;]+)$/.exec(u.pathname);
    if (m) {
      var r = route(m[1]);
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
                   COBB_1985: COBB_1985, CHURCH: CHURCH };

if (require.main === module) {
  start(function (f) { console.log(JSON.stringify({ port: f.port })); });
}
