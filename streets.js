/* The NucBox's street index: where two named streets meet, and the stretch of
 * one street inside a box. Loaded by server.js when NUCBOX_STREETS_FILE names
 * the file tools/street_index.py wrote; nothing else reads it.
 *
 * WHY THIS EXISTS. Uber prints most dropoffs as a corner, not a door —
 * "Foothill Trl & Northwoods Dr, Marietta": 403 of the week's 1,166 dropoffs,
 * 390 different ones — to keep the customer's address off the card. Nominatim
 * answers ONE representative point for a whole street (Cobb Parkway NW came
 * back as one result on the real install), so the corner of two streets cannot
 * be asked of it, and a numberless street ("Shadowood Pkwy SE, Atlanta") comes
 * back as a point somewhere along it rather than the stretch that is inside
 * the card's disc. Both are questions about the street GRAPH, and the graph is
 * in the Georgia file the NucBox already holds. This answers them from that,
 * and from nothing else: no town, no postcode, no ranking.
 *
 * THE NAME IS THE ONLY KEY, so it is where this can go wrong. Four rules, in
 * order, the first that finds anything wins and later ones are never asked —
 * so a name the index holds exactly is never widened to its neighbours:
 *
 *   exact      case, punctuation and the USPS abbreviations both ways
 *              (Trail/Trl, Parkway/Pkwy, Northwest/NW ...), on BOTH sides,
 *              so "Foxglove Trl" finds OSM's "Foxglove Trail" and "Bramble
 *              Court" finds an OSM name written "Bramble Ct".
 *   dir        a directional on one side only ("Peachtree St" against OSM's
 *              "Peachtree Street Northeast"); two names each with one the
 *              other lacks never match, wherever they stand — in Atlanta "NW"
 *              and "SE" are different streets, and "Main St NW" is not "S
 *              Main St" (see dirsAgree, and its own risk there).
 *   junk       the same two, after the OCR's litter is dropped: tokens of one
 *              or two letters that are not a street word after the street's
 *              last type, printed short ("Ct re ou NW", "Dr Ss R SW") — never
 *              a word before it, which is the name ("Ol Canton Rd" is not
 *              Canton Road), and never a digit (see cleaned).
 *   ocr        one letter, in one word, read wrong — and only the letter the
 *              reader is seen to misread, i for l or l for i ("Tri" for Trl,
 *              "PI" for Pl, "Biue" for Blue; see OCR_LETTERS), so never a
 *              digit (12th and 13th are different streets) and never Pine for
 *              Pike; never one street word for another (St and Ct are
 *              different streets); never in a word of the index shorter than
 *              four letters unless it is a street word ("Oak" and "Oat" are
 *              different streets); and only among the names inside the box
 *              asked, when no rule before it found the name anywhere.
 *
 * Measured over the 390 distinct cross-street dropoffs of the week (722
 * distinct halves) and over every street-like string the week's cards and
 * frames carry — see the commits for the counts. A name this cannot match
 * is refused by name, never guessed at. */
'use strict';

var fs = require('fs');

var FORMAT = 'uberscan-streets/1';

/* USPS Publication 28's suffix abbreviations — the ones Uber prints — and the
 * directionals. Every word on either side is mapped to its short form, so the
 * card's "Trl" and OSM's "Trail" are one word, whichever side spelt it out. */
var TYPES = {
  alley: 'aly', avenue: 'ave', av: 'ave', bend: 'bnd', bluff: 'blf',
  boulevard: 'blvd', branch: 'br', bridge: 'brg', brook: 'brk', bypass: 'byp',
  causeway: 'cswy', center: 'ctr', centre: 'ctr', chase: 'chase', circle: 'cir',
  cliff: 'clf', close: 'close', common: 'cmn', corner: 'cor', court: 'ct',
  cove: 'cv', creek: 'crk', crescent: 'cres', crest: 'crst', crossing: 'xing',
  crossroad: 'xrd', curve: 'curv', drive: 'dr', estate: 'est', estates: 'ests',
  expressway: 'expy', extension: 'ext', falls: 'fls', ferry: 'fry',
  field: 'fld', fields: 'flds', forest: 'frst', fork: 'frk', freeway: 'fwy',
  garden: 'gdn', gardens: 'gdns', gateway: 'gtwy', glen: 'gln', green: 'grn',
  grove: 'grv', harbor: 'hbr', haven: 'hvn', heights: 'hts', highway: 'hwy',
  hill: 'hl', hills: 'hls', hollow: 'holw', island: 'is', junction: 'jct',
  knoll: 'knl', lake: 'lk', landing: 'lndg', lane: 'ln', lodge: 'ldg',
  loop: 'loop', manor: 'mnr', meadow: 'mdw', meadows: 'mdws', mews: 'mews',
  mill: 'ml', mount: 'mt', mountain: 'mtn', orchard: 'orch', overlook: 'ovlk',
  park: 'park', parkway: 'pkwy', pass: 'pass', path: 'path', pike: 'pike',
  pines: 'pnes', place: 'pl', plaza: 'plz', point: 'pt', ridge: 'rdg',
  road: 'rd', route: 'rte', row: 'row', run: 'run', shoals: 'shls',
  spring: 'spg', springs: 'spgs', square: 'sq', station: 'sta', street: 'st',
  saint: 'st', summit: 'smt', terrace: 'ter', trace: 'trce', trail: 'trl',
  turnpike: 'tpke', valley: 'vly', view: 'vw', village: 'vlg', vista: 'vis',
  walk: 'walk', way: 'way'
};
var DIRS = {
  north: 'n', south: 's', east: 'e', west: 'w', northeast: 'ne',
  northwest: 'nw', southeast: 'se', southwest: 'sw'
};
var TYPE_WORDS = {}, DIR_WORDS = {};
Object.keys(TYPES).forEach(function (k) { TYPE_WORDS[TYPES[k]] = true; });
Object.keys(DIRS).forEach(function (k) { DIR_WORDS[DIRS[k]] = true; });
// "Pkwy" and "pky" are both printed; the long form is the one OSM writes.
TYPES.pky = 'pkwy';
TYPES.pkway = 'pkwy';

function isType(t) { return TYPE_WORDS[t] === true; }
function isDir(t) { return DIR_WORDS[t] === true; }
function isWord(t) { return isType(t) || isDir(t); }

/* A name as words, as printed: lowercase. Apostrophes go without a gap
   ("O'Neal" is "oneal", "N'W" is "nw"); every other mark is a gap. */
function printed(name) {
  return String(name == null ? '' : name).toLowerCase()
    .replace(/['‘’`]/g, '')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim().split(' ')
    .filter(Boolean);
}

function short(t) {
  return Object.prototype.hasOwnProperty.call(TYPES, t) ? TYPES[t]
    : Object.prototype.hasOwnProperty.call(DIRS, t) ? DIRS[t] : t;
}

// ...and each in its short form.
function words(name) { return printed(name).map(short); }

/* Leading and trailing directionals apart from the rest. A name that is
   nothing but directionals keeps them as its base. */
function split(ws) {
  var a = 0, b = ws.length;
  while (a < b - 1 && isDir(ws[a])) a++;
  while (b > a + 1 && isDir(ws[b - 1])) b--;
  return { pre: ws.slice(0, a).join(' '), base: ws.slice(a, b),
           post: ws.slice(b).join(' ') };
}

/* Directionals agree when neither name has one the other lacks a match for:
   before the name and after it, each the same or missing on one side, AND
   every one of one name's among the other's. So none against any agrees
   ("Marietta Pkwy" against "N Marietta Pkwy NW"), and one more on one side
   ("Lincoln Trace Ave SE" against "S Lincoln Trace Ave SE"; "North Ave"
   against "North Avenue Northwest", whose first word is a directional too).
   Before and after apart were the whole rule, and so "Main St NW" agreed
   with "S Main St" (one had nothing before, the other nothing after) and
   "Peachtree Rd NW" with "NE Peachtree Rd"; the whole names apart were not
   enough either, "Cobb Pkwy S" being inside "S Cobb Pkwy NW" by that alone.
   On the week's 1,197 distinct street names off the cards, each asked of
   all the others, the old rule matched two that differ ("Peachtree Rd NW"
   and "NE Peachtree Rd") and this does not.
   ITS OWN RISK, kept: a directional on one side only is a street the card
   printed short, or another street. Of this rule's 112 pairs on those
   names, 18 put a leading N, S, E or W against none — West Barrett Pkwy and
   Barrett Pkwy, S Cobb Pkwy and Cobb Pkwy, N Roberts Rd and Roberts Rd, E
   Stone Bridge Run and Stone Bridge Run among them — and in Atlanta that can
   be a different street (West Paces Ferry Rd is not Paces Ferry Rd). What
   stands between them and a pin is the card's disc: a corner is where the
   two names MEET inside it, and a stretch of two streets apart is refused. */
function dirsOf(sp) {
  return (sp.pre ? sp.pre.split(' ') : []).concat(sp.post ? sp.post.split(' ') : []);
}
function within(a, b) {
  return a.every(function (d) { return b.indexOf(d) >= 0; });
}
function dirsAgree(x, y) {
  if (!((x.pre === y.pre || !x.pre || !y.pre) && (x.post === y.post || !x.post || !y.post))) {
    return false;
  }
  var a = dirsOf(x), b = dirsOf(y);
  return within(a, b) || within(b, a);
}

/* The OCR's litter dropped from the words of `name`, or the same words when
 * there is none: tokens of one or two letters that are not a street word,
 * AFTER the name's last street type — and only when the card printed that
 * type in its USPS short form ("Ct", "Ln", "Rd"; or "Way", whose short form
 * is itself). Nothing before that type is ever dropped: it is the name.
 *
 * Measured on the week's cross-street halves (605 distinct, from the
 * dropoffs that carry a comma and so reach the index): of the one- and
 * two-letter tokens that are not street words, 23 come before the type and
 * 21 where there is no type at all — real initials among them ("J R Rd",
 * "Richard D Sailors Pkwy", "Hosea L Williams Dr") beside litter ("Gj
 * Cumberland Creek Way"), not to be told apart by their letters. Dropped
 * anyway, "Ol Canton Rd" (Old Canton Road misread) was asked as Canton Road,
 * a different street whose corner was a mile off; "La Vista Rd" as Vista
 * Rd, "Mc Donough Blvd" as Donough Blvd. The 17 after the type are litter
 * ("Ct re ou NW", "Rd ay tt ra NW", "Dr Ss R SW") but for two: "Orange Grove
 * PI SW" and "Cedar Ridge Or", the TYPE misread after a spelled-out word that
 * is also a street word — so after a type spelled out ("Grove", "Ridge",
 * "Way") nothing is dropped. This drops litter from 9 of the 605 and nothing
 * else. A lone digit is never dropped: after the type it is the route's
 * number (5 of the 6 there, "Georgia State Route 9"), and the old rule, which
 * dropped it and every word after the last type, asked "Old Hwy 41 Kennesaw"
 * as Old Hwy; before the type it is litter ("Twin Branch 4 Rd"), and the name
 * is refused for it. Words after the last type were dropped as a town the
 * reader glued on ("Westover Ln NW Kennesaw"): every one of those in the week
 * is a dropoff with no comma, which map-view.js asks of Nominatim and never
 * of this, while on the dropoffs that do reach this the same rule hit 12
 * halves and 8 of them lost a route's number. */
function cleaned(name) {
  var raw = printed(name), ws = raw.map(short);
  var last = -1;
  ws.forEach(function (t, i) { if (i > 0 && isType(t)) last = i; });
  if (last < 0 || Object.prototype.hasOwnProperty.call(TYPES, raw[last])) return ws;
  return ws.filter(function (t, i) {
    return i <= last || isWord(t) || !/^[a-z]{1,2}$/.test(t);
  });
}

// Whether two words are one edit apart (and not the same).
function oneEdit(a, b) {
  if (a === b || Math.abs(a.length - b.length) > 1) return false;
  var i = 0;
  while (i < a.length && i < b.length && a[i] === b[i]) i++;
  var ca = a.slice(i), cb = b.slice(i);
  if (a.length === b.length) return ca.slice(1) === cb.slice(1) ? [ca[0], cb[0]] : false;
  if (a.length > b.length) return ca.slice(1) === cb ? [ca[0], ''] : false;
  return ca === cb.slice(1) ? ['', cb[0]] : false;
}

/* The one letter the reader is SEEN to misread, both ways: "i" for "l" and
 * "l" for "i". Measured on the week's frames (week.csv `scans`, 5,491 of
 * them): two frames of one card, compared word for word on the lines that
 * read as an address in both, differ by one letter in a word 277 times
 * (lowercased, as this compares; case alone left out). 190 put one letter
 * for another, and 177 of those are i/l ("Tri"/"Trl", "Bivd"/"Blvd",
 * "PI"/"Pl"); the other 13 are h/k 5, a/n 4 and four single ones, none in a
 * street's name. 39 put a digit for a letter (5 for S, 31) and 48 add or drop
 * one ("Smyrn" for Smyrna, 13), which is also how real streets differ (Oak
 * and Oaks, Spring and Springs). Any letter for any letter matched real,
 * different streets the week's cards and frames carry — Beach St (Acworth)
 * and Beech St (Marietta), Olive St SW and Oliver St — and Pine/Pike,
 * Rose/Ross, Bell/Ball, Reed/Reid and Allen/Allan are all one letter apart.
 * A misread the reader makes the same way in every frame cannot be seen this
 * way ("Or" for Dr: "Cedar Ridge Or" and "Ottley Or NE" on the week's cards)
 * and is refused. No two street words are one i/l apart, so St is never read
 * as Ct (tests/streets.test.js holds that). */
var OCR_LETTERS = { il: true, li: true };

/* Whether asked word `q` may be the index's word `w` read one letter wrong. */
function ocrMay(q, w) {
  var e = oneEdit(q, w);
  if (!e) return false;
  if (!OCR_LETTERS[e[0] + e[1]]) return false;        // Pine is not Pike
  return isWord(w) || w.length >= 4;                  // Ell is not Eli
}

/* --- the index ----------------------------------------------------------- */

/* The exporter's JSON, unpacked into typed arrays: coordinates as degrees,
   each way's nodes as indices into them, and each way's bounding box. Names
   are looked up through their words, built once here. */
function build(doc) {
  if (!doc || doc.format !== FORMAT) {
    throw new Error('not a street index (format is not ' + FORMAT + ')');
  }
  var scale = Math.pow(10, doc.e);
  var flat = doc.nodes, n = flat.length / 2;
  if (!(n === Math.floor(n)) || !Array.isArray(doc.ways) || !Array.isArray(doc.names)) {
    throw new Error('the street index is cut short');
  }
  var lon = new Float64Array(n), lat = new Float64Array(n);
  var x = 0, y = 0;
  for (var i = 0; i < n; i++) {
    x += flat[2 * i]; y += flat[2 * i + 1];
    lon[i] = x / scale; lat[i] = y / scale;
  }
  var W = doc.ways.length, refs = 0;
  doc.ways.forEach(function (w) { refs += w[1].length; });
  var start = new Uint32Array(W + 1), nodes = new Uint32Array(refs);
  var box = new Float64Array(4 * W);
  var byKey = new Map();
  var k = 0;
  doc.ways.forEach(function (w, wi) {
    start[wi] = k;
    var at = 0, lo = Infinity, la = Infinity, hi = -Infinity, ha = -Infinity;
    w[1].forEach(function (d, j) {
      at = j === 0 ? d : at + d;
      if (at < 0 || at >= n) throw new Error('the street index names a node it does not have');
      nodes[k++] = at;
      if (lon[at] < lo) lo = lon[at];
      if (lon[at] > hi) hi = lon[at];
      if (lat[at] < la) la = lat[at];
      if (lat[at] > ha) ha = lat[at];
    });
    box[4 * wi] = lo; box[4 * wi + 1] = la; box[4 * wi + 2] = hi; box[4 * wi + 3] = ha;
    w[0].forEach(function (ni) {
      var key = words(doc.names[ni]).join(' ');
      if (!key) return;
      var e = byKey.get(key);
      if (!e) { e = { names: [], ways: [] }; byKey.set(key, e); }
      if (e.names.indexOf(doc.names[ni]) < 0) e.names.push(doc.names[ni]);
      if (e.ways[e.ways.length - 1] !== wi) e.ways.push(wi);
    });
  });
  start[W] = k;
  // The same keys by their words, for the rules after `exact`.
  var keys = [];
  byKey.forEach(function (e, key) {
    var ws = key.split(' ');
    keys.push({ key: key, ws: ws, sp: split(ws) });
  });
  var byBase = new Map();
  keys.forEach(function (o) {
    var b = o.sp.base.join(' ');
    if (!byBase.has(b)) byBase.set(b, []);
    byBase.get(b).push(o);
  });
  return { lon: lon, lat: lat, start: start, nodes: nodes, box: box,
           byKey: byKey, keys: keys, byBase: byBase, bbox: doc.bbox || null,
           counts: { names: byKey.size, ways: W, nodes: n } };
}

function load(file) {
  return build(JSON.parse(fs.readFileSync(file, 'utf8')));
}

/* Which of the index's names a name asked for is, and by which rule:
   { names: [as OSM spells them], how: 'exact'|'dir'|'junk'|'ocr'|null,
     keys: [...] }. The `ocr` rule is asked only inside `box` ([w, s, e, n]),
   of the names with a way reaching into it, and never with no box: a
   misread letter is a guess between names, and the card's own disc is what
   keeps the guess to the streets that could be the one meant. And only when
   no rule before it found the name ANYWHERE, so a name the index holds as
   printed is never read as another inside the box ("Pike St" across town is
   not this box's "Pine St"). */
function match(ix, asked, box) {
  var q = words(asked);
  var tries = [q];
  var c = cleaned(asked);
  if (c.length && c.join(' ') !== q.join(' ')) tries.push(c);
  function found(list, how) {
    var names = [], keys = [];
    list.forEach(function (key) {
      keys.push(key);
      ix.byKey.get(key).names.forEach(function (nm) { if (names.indexOf(nm) < 0) names.push(nm); });
    });
    return { names: names.sort(), how: how, keys: keys.sort() };
  }
  for (var t = 0; t < tries.length; t++) {
    var ws = tries[t];
    var how = t === 0 ? null : 'junk';
    if (ix.byKey.has(ws.join(' '))) return found([ws.join(' ')], how || 'exact');
    var sp = split(ws);
    var near = (ix.byBase.get(sp.base.join(' ')) || []).filter(function (o) {
      return dirsAgree(sp, o.sp);
    }).map(function (o) { return o.key; });
    if (near.length) return found(near, how || 'dir');
  }
  if (!box) return { names: [], how: null, keys: [] };
  for (t = 0; t < tries.length; t++) {
    var sq = split(tries[t]);
    var hits = ix.keys.filter(function (o) {
      if (o.sp.base.length !== sq.base.length || !dirsAgree(sq, o.sp)) return false;
      var diff = -1;
      for (var i = 0; i < sq.base.length; i++) {
        if (sq.base[i] !== o.sp.base[i]) {
          if (diff >= 0) return false;
          diff = i;
        }
      }
      return diff >= 0 && ocrMay(sq.base[diff], o.sp.base[diff])
        && waysIn(ix, [o.key], box).length > 0;
    }).map(function (o) { return o.key; });
    if (hits.length) return found(hits, 'ocr');
  }
  return { names: [], how: null, keys: [] };
}

/* --- geometry ------------------------------------------------------------ */

function metres(aLat, aLon, bLat, bLon) {
  var R = 6371008.8, r = Math.PI / 180;
  var dLat = (bLat - aLat) * r, dLon = (bLon - aLon) * r;
  var h = Math.sin(dLat / 2) * Math.sin(dLat / 2)
        + Math.sin(dLon / 2) * Math.sin(dLon / 2) * Math.cos(aLat * r) * Math.cos(bLat * r);
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

// A box is [west, south, east, north], or null for the whole index.
function boxOf(viewbox) {
  if (!viewbox) return null;
  var v = viewbox.split(',').map(Number);
  return [Math.min(v[0], v[2]), Math.min(v[1], v[3]), Math.max(v[0], v[2]), Math.max(v[1], v[3])];
}

function waysIn(ix, keys, box) {
  var out = [];
  keys.forEach(function (key) {
    ix.byKey.get(key).ways.forEach(function (w) {
      if (out.indexOf(w) >= 0) return;
      if (box && (ix.box[4 * w] > box[2] || ix.box[4 * w + 2] < box[0]
                  || ix.box[4 * w + 1] > box[3] || ix.box[4 * w + 3] < box[1])) return;
      out.push(w);
    });
  });
  return out;
}

function inBox(box, lon, lat) {
  return !box || (lon >= box[0] && lon <= box[2] && lat >= box[1] && lat <= box[3]);
}

/* Where segment p1-p2 meets q1-q2, touching included, as [lon, lat], or null.
   Planar in degrees: across the few hundred metres of one segment the
   difference from the sphere is far below the metre these are kept to. */
function meet(p1x, p1y, p2x, p2y, q1x, q1y, q2x, q2y) {
  var rx = p2x - p1x, ry = p2y - p1y, sx = q2x - q1x, sy = q2y - q1y;
  var d = rx * sy - ry * sx;
  if (d === 0) return null;                  // parallel or on one line
  var t = ((q1x - p1x) * sy - (q1y - p1y) * sx) / d;
  var u = ((q1x - p1x) * ry - (q1y - p1y) * rx) / d;
  if (t < 0 || t > 1 || u < 0 || u > 1) return null;
  return [p1x + t * rx, p1y + t * ry];
}

/* Points within CLUSTER_M of each other, chained, are one meeting. A dual
 * carriageway is two ways of one name a few tens of metres apart, so a road
 * crossing it meets it twice, and two dual carriageways crossing meet four
 * times in a square; each is one corner. 100 m is chosen, not measured: wide
 * enough for a divided arterial's median, and a corner pair it wrongly
 * joins is at most 50 m from the middle it is pinned at — well inside the
 * fifth of a mile map-view.js already calls one place (AGREE_MI), which is
 * what the page then holds every meeting to. */
var CLUSTER_M = 100;

function clusters(points) {
  var group = points.map(function (p, i) { return i; });
  function root(i) { while (group[i] !== i) i = group[i] = group[group[i]]; return i; }
  for (var i = 0; i < points.length; i++) {
    for (var j = i + 1; j < points.length; j++) {
      if (metres(points[i][1], points[i][0], points[j][1], points[j][0]) <= CLUSTER_M) {
        group[root(i)] = root(j);
      }
    }
  }
  var by = new Map();
  points.forEach(function (p, i) {
    var r = root(i);
    if (!by.has(r)) by.set(r, []);
    by.get(r).push(p);
  });
  var out = [];
  by.forEach(function (ps) {
    var lon = 0, lat = 0;
    ps.forEach(function (p) { lon += p[0]; lat += p[1]; });
    lon /= ps.length; lat /= ps.length;
    // How far the farthest two of them are apart: a crossing is a few tens
    // of metres at most; two streets that run together for a mile share
    // every node of that mile and come out as one meeting this long.
    var span = 0;
    for (var a = 0; a < ps.length; a++) {
      for (var b = a + 1; b < ps.length; b++) {
        span = Math.max(span, metres(ps[a][1], ps[a][0], ps[b][1], ps[b][0]));
      }
    }
    out.push({ lat: round6(lat), lon: round6(lon), n: ps.length, spanM: Math.round(span),
               shared: ps.some(function (p) { return p[2] === 'node'; }) });
  });
  return out.sort(function (a, b) { return a.lat - b.lat || a.lon - b.lon; });
}

function round6(v) { return Math.round(v * 1e6) / 1e6; }

/* The most meetings one answer carries. Two names meeting in more places
   than this inside one card's box is not a corner anybody can pin, and a
   list cut here says so (`cutAt`) rather than looking whole. */
var MEETS_MAX = 50;

/* Where streets named `a` and `b` meet inside `box` (null: anywhere). Ways
   that share a node meet there; ways that cross without one (a bridge, or a
   junction mapped without its node) meet where their segments cross. */
function cross(ix, a, b, box) {
  var ma = match(ix, a, box), mb = match(ix, b, box);
  var out = { a: { names: ma.names, how: ma.how, ways: 0 },
              b: { names: mb.names, how: mb.how, ways: 0 }, meets: [], cutAt: null };
  if (!ma.keys.length || !mb.keys.length) return out;
  var wa = waysIn(ix, ma.keys, box), wb = waysIn(ix, mb.keys, box);
  out.a.ways = wa.length;
  out.b.ways = wb.length;
  var points = [];
  var mine = new Set();
  wa.forEach(function (w) {
    for (var k = ix.start[w]; k < ix.start[w + 1]; k++) mine.add(ix.nodes[k]);
  });
  var seen = new Set();
  wb.forEach(function (w) {
    for (var k = ix.start[w]; k < ix.start[w + 1]; k++) {
      var nd = ix.nodes[k];
      if (mine.has(nd) && !seen.has(nd) && inBox(box, ix.lon[nd], ix.lat[nd])) {
        seen.add(nd);
        points.push([ix.lon[nd], ix.lat[nd], 'node']);
      }
    }
  });
  wa.forEach(function (p) {
    wb.forEach(function (q) {
      if (p === q) return;
      if (ix.box[4 * p] > ix.box[4 * q + 2] || ix.box[4 * p + 2] < ix.box[4 * q]
          || ix.box[4 * p + 1] > ix.box[4 * q + 3] || ix.box[4 * p + 3] < ix.box[4 * q + 1]) return;
      for (var i = ix.start[p]; i + 1 < ix.start[p + 1]; i++) {
        var p1 = ix.nodes[i], p2 = ix.nodes[i + 1];
        for (var j = ix.start[q]; j + 1 < ix.start[q + 1]; j++) {
          var q1 = ix.nodes[j], q2 = ix.nodes[j + 1];
          // A shared node is already counted above, as a node.
          if (p1 === q1 || p1 === q2 || p2 === q1 || p2 === q2) continue;
          var m = meet(ix.lon[p1], ix.lat[p1], ix.lon[p2], ix.lat[p2],
                       ix.lon[q1], ix.lat[q1], ix.lon[q2], ix.lat[q2]);
          if (m && inBox(box, m[0], m[1])) points.push([m[0], m[1], 'crossing']);
        }
      }
    });
  });
  var all = clusters(points);
  if (all.length > MEETS_MAX) {
    out.cutAt = MEETS_MAX;
    all = all.slice(0, MEETS_MAX);
  }
  out.meets = all;
  return out;
}

/* Clip segment a-b ([lon, lat]) to `box`, Liang-Barsky: the part inside, or
   null. */
function clipSeg(a, b, box) {
  var t0 = 0, t1 = 1, dx = b[0] - a[0], dy = b[1] - a[1];
  var ps = [-dx, dx, -dy, dy], qs = [a[0] - box[0], box[2] - a[0], a[1] - box[1], box[3] - a[1]];
  for (var i = 0; i < 4; i++) {
    if (ps[i] === 0) { if (qs[i] < 0) return null; continue; }
    var r = qs[i] / ps[i];
    if (ps[i] < 0) { if (r > t1) return null; if (r > t0) t0 = r; }
    else { if (r < t0) return null; if (r < t1) t1 = r; }
  }
  return [[a[0] + t0 * dx, a[1] + t0 * dy], [a[0] + t1 * dx, a[1] + t1 * dy], t0 > 0, t1 < 1];
}

/* The most points one stretch answer carries. 8000 points at about 23
   bytes each is 184 KB, under the 256 KB server.js's relay takes from the
   NucBox (NBX_BODY_MAX). NUCBOX_STREETS_POINTS_MAX moves it (the suites use
   it). */
var POINTS_MAX = 8000;

/* The street named `name`, as the polylines of its ways inside `box` (null:
   all of it), each [[lat, lon], ...], cut at the box's edge. A way that
   leaves the box and comes back is two lines. */
function stretch(ix, name, box, most) {
  var m = match(ix, name, box);
  var out = { names: m.names, how: m.how, lines: [], points: 0, cutAt: null };
  if (!m.keys.length) return out;
  var cap = most || POINTS_MAX;
  var lines = [];
  waysIn(ix, m.keys, box).forEach(function (w) {
    var line = null;
    function put(p) {
      var pt = [round6(p[1]), round6(p[0])];
      var last = line[line.length - 1];
      if (!last || last[0] !== pt[0] || last[1] !== pt[1]) line.push(pt);
    }
    for (var k = ix.start[w]; k + 1 < ix.start[w + 1]; k++) {
      var a = [ix.lon[ix.nodes[k]], ix.lat[ix.nodes[k]]];
      var b = [ix.lon[ix.nodes[k + 1]], ix.lat[ix.nodes[k + 1]]];
      var c = box ? clipSeg(a, b, box) : [a, b, false, false];
      if (!c) { if (line) { lines.push(line); line = null; } continue; }
      if (!line || c[2]) { if (line) lines.push(line); line = []; }
      put(c[0]);
      put(c[1]);
      if (c[3]) { lines.push(line); line = null; }
    }
    if (line) lines.push(line);
  });
  out.lines = lines.filter(function (l) { return l.length >= 2; });
  out.points = out.lines.reduce(function (s, l) { return s + l.length; }, 0);
  if (out.points > cap) {
    out.cutAt = cap;
    out.lines = [];
  }
  return out;
}

module.exports = { FORMAT: FORMAT, words: words, split: split, cleaned: cleaned,
                   oneEdit: oneEdit, ocrMay: ocrMay, build: build, load: load,
                   match: match, cross: cross, stretch: stretch, metres: metres,
                   boxOf: boxOf, CLUSTER_M: CLUSTER_M, MEETS_MAX: MEETS_MAX,
                   POINTS_MAX: POINTS_MAX, TYPES: TYPES, DIRS: DIRS };
