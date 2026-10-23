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
 * And the NucBox's own server.js's street questions: /api/streets/cross and
 * /stretch answered in its shape with one fixed corner and stretch, and
 * /named by the real streets.js over a small invented index (NAMED_INDEX).
 *
 * Also: "Church St" is two streets of that name in two towns (two that fit
 * and disagree, whatever the card's town), "Slow Place" answers after two and
 * a half seconds (for the timeout), "4821 Kestrel Dr" answers its street and
 * not the door, "Starbucks" is twelve branches cut at the limit, "Waffle
 * House" is a pickup the road by is shorter than the road direct, "Farm
 * Stand" is 450 m from a road, "250 Example Road" is a restaurant's door (a
 * held order's pickup) and "1975 Cobb Parkway" one 87 m from 1985's door
 * ("1981 Cobb Parkway" one 60 m),
 * "Wrenfield Parking Deck" a place by Kestrel Drive (with "Quarry Hall" a road
 * and "Lantern Parking Deck" a deck far off, below), a
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

/* ...and one 60 m east of that same door (street=1981 Cobb Parkway): the
   restaurant the SERVER pins for the guard from the held card's own words
   (server.js pickupAsks, the owner's decision of 18 Oct) — DoorDash's printed
   door under the store's name, or an Uber "Store (1981 Cobb Pkwy)". Invented. */
var TAQUERIA = [place(83, 34.0010, -84.55535, 'amenity', 'restaurant', 'Example Taqueria',
                      'Example Taqueria, 1981, Cobb Parkway, Kennesaw, Cobb County, Georgia, '
                      + '30152, United States')];

/* The held end by its PLACE (map-view.js pickPlace; the owner, 17 Oct): a
   parking deck beside Kestrel Drive, whose house 4821 this fake does not hold,
   asked as q=Wrenfield Parking Deck and answered as Nominatim answers a named
   feature, its category amenity and its own name — and the same for the
   reader's read of it with the last letter lost ("Wrenfield Parking Dec") and
   for a shorter name that is not it ("Wrenfield Deck"), as a free-text
   search answers either. "Quarry Hall" is a ROAD of that name, never a
   building, and "Lantern Parking Deck" a deck 6.9 mi north-east of the
   Square: inside the box round a 5.0 mi card's 5.5 mi disc, and outside the
   disc.
   Invented, every one. */
var DECK = [place(91, 33.9712, -84.5288, 'amenity', 'parking', 'Wrenfield Parking Deck',
                  'Wrenfield Parking Deck, Kestrel Drive, Marietta, Cobb County, Georgia, '
                  + '30060, United States')];
var QUARRY = [place(92, 33.9690, -84.5310, 'highway', 'residential', 'Quarry Hall',
                    'Quarry Hall, Marietta, Cobb County, Georgia, 30060, United States')];
var LANTERN = [place(93, 34.0226, -84.4649, 'amenity', 'parking', 'Lantern Parking Deck',
                     'Lantern Parking Deck, Marietta, Cobb County, Georgia, 30062, '
                     + 'United States')];

/* A door the NucBox holds under its street's other type word (map-view.js
   streetRetry; the owner's 17 Oct evening snap): the app prints "1830 Tansy
   Creek Cts SW" and this fake, as the real install did for the owner's, answers
   that with nothing. Asked again with the type left out, "1830 Tansy Creek
   SW", it answers as a free match on the name does: the door on Tansy Creek
   Court Southwest, 2.2 mi north-west of the Square, and a house of the same
   number on Tansy Creek Drive Southwest, 2.0 mi west-south-west — a different
   street, which must never be the door. "2040 Tansy Creek Cts SW" is the same
   and holds only the Drive's 2040. Invented, every one. */
var TANSY_1830 = [
  place(101, 33.9800, -84.5700, 'place', 'house', '',
        '1830, Tansy Creek Court Southwest, Marietta, Cobb County, Georgia, 30064, '
        + 'United States'),
  place(102, 33.9400, -84.5820, 'place', 'house', '',
        '1830, Tansy Creek Drive Southwest, Marietta, Cobb County, Georgia, 30064, '
        + 'United States')
];
var TANSY_2040 = [
  place(103, 33.9410, -84.5830, 'place', 'house', '',
        '2040, Tansy Creek Drive Southwest, Marietta, Cobb County, Georgia, 30064, '
        + 'United States')
];

/* A door the NucBox holds under its street's directional the other way
   (map-view.js dirRetry; the owner's fault of 20 Oct, 21:08): Uber prints the
   road's middle initial spelled out, "810 Ardley West Corwin Parkway", and
   this fake, as the real install did for the owner's, answers that with the
   road alone, half a mile north-west of the Square. Asked "810 Ardley W
   Corwin Parkway" it answers the door, 3.1 mi north-west, under the name as
   OSM writes it, quadrant and all. "812 Ardley West Corwin Parkway" is the
   same road, and its W-spelt question holds only a house 812 on Ardley W
   Corwin Circle — a different street, which must never be the door.
   Invented, every one. */
var ARDLEY_ROAD = [place(131, 33.9600, -84.5550, 'highway', 'primary',
                         'Ardley W Corwin Parkway Northwest',
                         'Ardley W Corwin Parkway Northwest, Marietta, Cobb County, Georgia, '
                         + '30064, United States')];
var ARDLEY_810 = [place(132, 33.9900, -84.5800, 'place', 'house', '',
                        '810, Ardley W Corwin Parkway Northwest, Kennesaw, Cobb County, '
                        + 'Georgia, 30144, United States')];
var ARDLEY_812 = [place(133, 33.9880, -84.5790, 'place', 'house', '',
                        '812, Ardley W Corwin Circle Northwest, Kennesaw, Cobb County, '
                        + 'Georgia, 30144, United States')];

/* A door filed under a name read short (map-view.js nameRetry; the owner's 19
   Oct night fault): "1106 Tamaror" is "1106 Tamarons Ln" read off a dark
   frame with its type lost and its last word cut, and this fake's search, as
   the real install did for the owner's, answers it with nothing. Its street
   index (NAMED_INDEX below) knows Tamarons Lane 1.7 mi north-west of the
   Square, and asked by that name the search answers the door. "Brindler" is
   a read two near streets can be — Brindlewood Way and Brindleton Court,
   both by the Square — whose doors the search holds too, so a suite can see
   neither is ever asked. Invented, every one. */
var TAMARONS_1106 = [
  place(111, 33.9752, -84.5601, 'place', 'house', '',
        '1106, Tamarons Lane, Marietta, Cobb County, Georgia, 30064, United States')];
var BRINDLE_1106 = [
  place(112, 33.9650, -84.5400, 'place', 'house', '',
        '1106, Brindlewood Way, Marietta, Cobb County, Georgia, 30060, United States')];

/* The owner's planner of 21 Oct, 13:57, invented: the dropoff "2282 <Name>s
   Dr" read "2282 <Name>" — its last letter and its type lost — and filed off
   a planner whose title had scrolled away. "2282 Corbin" answers nothing
   here; the index knows Corbins Drive 1.3 mi north-east of the Square, and
   asked by that name the search answers the door. */
var CORBINS_2282 = [
  place(113, 33.9701, -84.5340, 'place', 'house', '',
        '2282, Corbins Drive, Marietta, Cobb County, Georgia, 30062, United States')];

/* The NucBox's street index for the questions above, answered by the real
   streets.js (named), so what the server is told is what the NucBox would
   say: each street one short way. Coordinates are deltas, node to node, in
   millionths of a degree. */
var Streets = require('../streets.js');
var NAMED_INDEX = Streets.build({
  format: Streets.FORMAT, e: 6,
  names: ['Tamarons Lane', 'Brindlewood Way', 'Brindleton Court',
          'Larkmoor Court', 'Hollin Road', 'Fennick Court', 'Ellis Court', 'Quarrel Court',
          'Pembury', 'Corbins Drive'],
  nodes: [-84561000, 33975000, 2000, 400,            // Tamarons Lane
          21000, -10400, 2000, 0,                    // Brindlewood Way
          -6000, 3000, 0, 2000,                      // Brindleton Court
          2000, -10000, 2700, 0, 0, 1000,            // Larkmoor Court, two ways, 360 m
          -22700, -16000, 13000, 0,                  // Hollin Road, 1.2 km
          -13000, 20000, 2000, 0,                    // Fennick Court, by the Square...
          28000, -25000, 2000, 0,                    // ...and another, 2.3 mi south-east
          -17000, 10000, 1500, 0,                    // Ellis Court, 139 m
          -8500, 7000, 2000, 0,                      // Quarrel Court, 185 m by the Square...
          -10000, -57000, 27000, 0,                  // ...and a Quarrel Court of 2.5 km
          -20000, 56000, 1300, 0,                    // Pembury, no type word, 120 m
          16700, 14000, 2000, 0],                    // Corbins Drive, 1.3 mi north-east
  ways: [[[0], [0, 1]], [[1], [2, 1]], [[2], [4, 1]],
         [[3], [6, 1]], [[3], [7, 1]], [[4], [9, 1]], [[5], [11, 1]], [[5], [13, 1]],
         [[6], [15, 1]], [[7], [17, 1]], [[7], [19, 1]], [[8], [21, 1]],
         [[9], [23, 1]]] });

/* Streets the NucBox's search holds without their house numbers, for the
   held end by its street (server.js searchHeldStreet; the owner's fault of 19
   Oct): "306 Larkmoor Ct" (or with no type word) answers the court and not
   the house, and the index
   above holds the court whole (360 m, two ways); "512 Hollin Rd" a road of
   1.2 km; "77 Fennick Ct" two courts of that name, both inside a 5.0 mi
   card's disc round the Square. And (the mutation catch-up of 21 Oct) "21
   Eliis Ct" answers Ellis Court's street, which the index reads as Ellis
   Court only by its ocr rule, and "40 Quarrel Ct" a short court whose name a
   road of 2.5 km also carries, inside the same card's box (said by its length
   alone, past WHOLE_LINE_M), and "12 Pembury" a street the index holds with
   no type word. Invented, every one. */
var LARKMOOR = [place(121, 33.9600, -84.5387, 'highway', 'residential', 'Larkmoor Court',
                      'Larkmoor Court, Marietta, Cobb County, Georgia, 30060, United States')];
var HOLLIN = [place(122, 33.9450, -84.5535, 'highway', 'residential', 'Hollin Road',
                    'Hollin Road, Marietta, Cobb County, Georgia, 30060, United States')];
var ELLIS = [place(125, 33.9500, -84.5442, 'highway', 'residential', 'Ellis Court',
                   'Ellis Court, Marietta, Cobb County, Georgia, 30060, United States')];
var QUARREL = [place(126, 33.9570, -84.5510, 'highway', 'residential', 'Quarrel Court',
                     'Quarrel Court, Marietta, Cobb County, Georgia, 30060, United States')];
var PEMBURY = [place(127, 33.9560, -84.5520, 'highway', 'residential', 'Pembury',
                     'Pembury, Marietta, Cobb County, Georgia, 30060, United States')];
var FENNICK = [
  place(123, 33.9650, -84.5590, 'highway', 'residential', 'Fennick Court',
        'Fennick Court, Marietta, Cobb County, Georgia, 30060, United States'),
  place(124, 33.9400, -84.5290, 'highway', 'residential', 'Fennick Court',
        'Fennick Court, Marietta, Cobb County, Georgia, 30060, United States')];

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
    // ...and the one Example Grill by its name: a held pickup with no door
    // on record is asked by its store's name (server.js pickupAsks, 23 Oct).
    else if (term === 'example grill') all = GRILL;
    else if (term === 'waffle house') all = WAFFLE;
    else if (term === 'farm stand') all = FARM;
    else if (/^wrenfield (parking dec|parking deck|deck)$/.test(term)) all = DECK;
    else if (term === 'quarry hall') all = QUARRY;
    else if (term === 'lantern parking deck') all = LANTERN;
  } else if (q.street !== undefined) {
    if (/^shadowood (pkwy|parkway)/.test(term)) all = SHADOWOOD;
    else if (/^1985 cobb (pkwy|parkway)/.test(term)) all = COBB_1985;
    else if (/^4821 kestrel (dr|drive)/.test(term)) all = KESTREL;
    else if (/^church st/.test(term)) all = CHURCH;
    else if (/^250 example (rd|road)/.test(term)) all = GRILL;
    else if (/^1975 cobb (pkwy|parkway)/.test(term)) all = DINER;
    else if (/^1981 cobb (pkwy|parkway)/.test(term)) all = TAQUERIA;
    else if (term === '1830 tansy creek sw') all = TANSY_1830;
    else if (term === '2040 tansy creek sw') all = TANSY_2040;
    else if (term === '1106 tamarons lane') all = TAMARONS_1106;
    else if (term === '1106 brindlewood way') all = BRINDLE_1106;
    else if (term === '2282 corbins drive') all = CORBINS_2282;
    else if (/^81[02] ardley west corwin (pkwy|parkway)$/.test(term)) all = ARDLEY_ROAD;
    else if (/^810 ardley w corwin (pkwy|parkway)$/.test(term)) all = ARDLEY_810;
    else if (/^812 ardley w corwin (pkwy|parkway)$/.test(term)) all = ARDLEY_812;
    else if (/^\d+ larkmoor( ct| court)?$/.test(term)) all = LARKMOOR;
    else if (/^\d+ hollin (rd|road)$/.test(term)) all = HOLLIN;
    else if (/^\d+ fennick (ct|court)$/.test(term)) all = FENNICK;
    else if (/^\d+ eliis (ct|court)$/.test(term)) all = ELLIS;
    else if (/^\d+ quarrel (ct|court)$/.test(term)) all = QUARREL;
    else if (/^\d+ pembury$/.test(term)) all = PEMBURY;
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
    // The health probes (server.js nbxProbe), answered as the real services
    // answer them and never recorded: they are no question about a place,
    // and the suites read `asked` for the order of those.
    if (u.pathname === '/status') return json(200, { status: 0, message: 'OK' });
    if (u.pathname === '/health') return json(400, { code: 'InvalidUrl', message: 'URL string malformed' });
    if (u.pathname === '/api/streets') {
      // FAKE_STREETS_UNLOADED=1: a NucBox server up with no index loaded.
      if (process.env.FAKE_STREETS_UNLOADED === '1') {
        return json(200, { ok: true, loaded: false, error: 'streets.json is missing' });
      }
      return json(200, { ok: true, loaded: true, counts: { names: 1, ways: 1, nodes: 2 } });
    }
    asked.push(req.url);
    // The NucBox's own server.js answering from its street index
    // (server.js streetsRoute), in its shapes: one corner for any two names,
    // one short stretch for any name. "Slow Street" answers after two and a
    // half seconds (for the timeout) and "Bad Street" with a meeting that is
    // not a point (for the relay's all-or-nothing check). What a real index
    // answers is tests/streets.test.js's.
    // ...and /api/streets/named, by the real streets.js over NAMED_INDEX.
    // ...and /api/streets/whole, the same way.
    if (u.pathname === '/api/streets/whole') {
      var wh = Streets.whole(NAMED_INDEX, String(u.query.name || ''),
                             u.query.box ? Streets.boxOf(String(u.query.box)) : null);
      wh.ok = true;
      return json(200, wh);
    }
    if (u.pathname === '/api/streets/named') {
      var nb = Streets.named(NAMED_INDEX, String(u.query.name || ''),
                             u.query.box ? Streets.boxOf(String(u.query.box)) : null);
      nb.ok = true;
      return json(200, nb);
    }
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
                   DINER: DINER, TAQUERIA: TAQUERIA, DECK: DECK, QUARRY: QUARRY, LANTERN: LANTERN,
                   TANSY_1830: TANSY_1830, TANSY_2040: TANSY_2040,
                   ARDLEY_ROAD: ARDLEY_ROAD, ARDLEY_810: ARDLEY_810, ARDLEY_812: ARDLEY_812,
                   TAMARONS_1106: TAMARONS_1106, BRINDLE_1106: BRINDLE_1106,
                   CORBINS_2282: CORBINS_2282,
                   NAMED_INDEX: NAMED_INDEX };

if (require.main === module) {
  start(function (f) { console.log(JSON.stringify({ port: f.port })); });
}
