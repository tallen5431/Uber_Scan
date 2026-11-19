/* The places report's floors and small pieces: the constants every tab is
 * cut by, the bootstrap interval, the 2-mile grid and the words a verdict
 * prints a p-value or a name with. Read by the rest of tools/report/ and
 * re-exported by tools/places_report.js, whose header has the rules. */

'use strict';

var A = require('../../advice.js');
var MV = require('../../map-view.js');
// trends.js, whose FLOOR and DAY_MIN are the floors below (MIN_N, DROP_MIN_N).
var TR = require('../../trends.js');

/* The floor under a ranked cell, in offers. AUDITS.md's heat-map entry: at
 * fixed colour bands a cell needs 30-60 before its colour can be trusted, and
 * the floor and the scale must be derived together. Here there is no band —
 * colour comes only from a test and an interval — so the floor is the low end
 * of that range: below it a bootstrap interval of a median over a tail this
 * long is not worth drawing. Below it a cell is "too few", listed with its n
 * and never ranked or tested. The same 30 as trends.js FLOOR, whose own
 * table arrived at it, and read from there so the two cannot come apart. */
var MIN_N = TR.FLOOR;
// ...and on two separate outings at least, Advice.areas' own rule: thirty
// offers from one evening are one evening.
var MIN_OUTINGS = A.AREA_DAYS;
var ALPHA = A.AREA_ALPHA;
// More shuffles than the page's 500, because this runs once, offline, and a
// p near 0.05 deserves its third decimal.
var SHUFFLES = 2000;
var BOOTS = 1000;
// The coarse grid: about two miles a side. AUDITS found nothing below town
// scale on one week; a grid this coarse is the finest worth asking, and the
// test says whether even it is noise.
var GRID_MI = 2;
// "Where trips leave you": taken trips are few, so this floor is lower and
// the table is descriptive; its colour follows the same test-and-interval rule.
// Ten, trends.js DAY_MIN: the one floor under a descriptive median in the
// reports (tables.js's DESC_MIN_N is this; strategy.js's DIST_MIN_N reads it too).
var DROP_MIN_N = TR.DAY_MIN;
// A silence after a drop longer than the rig's own break (advice.js SHOWN_AT)
// ends the wait unmeasured: the driver stopped, not the market.
var NEXT_GAP_MIN = A.SHOWN_AT;
// Two pins of one store this close are one place (map-view.js AGREE_MI: a
// door or a branch is one point, a building and its node a few yards apart).
var PLACE_SAME_MI = MV.AGREE_MI;
// What a search asks for, as server.js asks it (NBX_LIMIT): the direct path
// asks exactly the relay's question, so a cut list is cut at the same place.
var NBX_LIMIT = 10;
// How a taken order was put down, by takenRuns' `by`: at the door. The
// offers page leaves out 'replaced' and 'expiry', which measure nothing.
// A Drop the GPS went on to finish (server.js finishWatch, the owner's 29 Oct
// "let me drop it so the computing is treated normally but track the GPS
// points"): takenRuns' 'finished-door', '-area' or '-stop', ended at the GPS's
// finish, the press kept as `pressedAt`. 'finished-stop' is the weakest (the
// first stop after the car moved off). timePresses never re-times one: it
// reads 'drop' and 'chooser' only.
var FINISHED = ['finished-door', 'finished-area', 'finished-stop'];
var AT_THE_DOOR = ['gps', 'screen', 'drop', 'chooser', 'drop (gps-timed)'].concat(FINISHED);
// A Drop press the GPS log timed (tables.js's timePresses): its own `by`.
var GPS_TIMED = 'drop (gps-timed)';

/* --- small pieces -------------------------------------------------------- */

function round2(v) { return v === null || v === undefined ? null : Math.round(v * 100) / 100; }

/* The least and greatest of a list, by a loop. Math.min.apply and
 * Math.max.apply pass the list as arguments, on the stack, and past about
 * 125,000 values that throws "Maximum call stack size exceeded": the span,
 * Gone quiet and --gps all took one over every offer, so a record that size
 * would have stopped the report. Infinity / -Infinity for none and NaN if
 * any is NaN, as the two Math calls give. */
function minOf(xs) {
  var m = Infinity;
  for (var i = 0; i < xs.length; i++) if (xs[i] < m || xs[i] !== xs[i]) { m = xs[i]; if (m !== m) break; }
  return m;
}
function maxOf(xs) {
  var m = -Infinity;
  for (var i = 0; i < xs.length; i++) if (xs[i] > m || xs[i] !== xs[i]) { m = xs[i]; if (m !== m) break; }
  return m;
}

// advice.js's own LCG (shuffled), for intervals that come out the same twice.
function rng(seed) {
  var s = seed >>> 0;
  return function () {
    s = (1664525 * s + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

function seedOf(text) {
  var h = 2166136261;
  for (var i = 0; i < text.length; i++) { h ^= text.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}

/* A percentile bootstrap interval for the median, 95%, or null under two.
 * `stat` another statistic of the resample in its place (a quantile, a mean). */
/* The median's own path (the reporting review's R1): the resample in a
 * Float64Array sorted in place, numerically by the engine, where MV.median
 * copied every resample into a new array and sorted it through a compare
 * function — the report's largest single cost on a 3x record. The same
 * draws in the same order, the same middle value (or the mean of the two
 * middle ones), so the same interval for the same seed: a check holds it.
 *
 * Then the second review: sorting every resample was still 37% of the whole
 * report on the invented 11,721-offer journal. A resample's middle needs no
 * sort at all: the values are sorted ONCE, each draw adds one to its value's
 * rank, and a walk up the counts reaches the middle rank(s). Each draw is
 * still values[floor(r() * n)], in the same order, and the order statistics
 * are the same numbers the sort put there, so the interval is the same to
 * the bit (bootCIPlain's check; the report built before and after, every CSV
 * and the page's data identical). O(n) a resample where the sort was
 * O(n log n). A quantile's own statistic (qOf, which says its q) takes the
 * same walk to its two straddling ranks and the same arithmetic. */
function bootCI(values, seed, reps, stat) {
  if (!values || values.length < 2) return null;
  reps = reps || BOOTS;
  var r = rng(seed), n = values.length, meds = new Float64Array(reps), k, i;
  var q = !stat ? 0.5 : typeof stat.q === 'number' ? stat.q : null;
  if (q !== null) {
    // Each value's rank in the one sort; `order[rank[j]]` IS values[j].
    var idx = new Array(n);
    for (i = 0; i < n; i++) idx[i] = i;
    idx.sort(function (a, b) { return values[a] - values[b]; });
    var order = new Float64Array(n), rank = new Int32Array(n), cnt = new Int32Array(n);
    for (i = 0; i < n; i++) { order[i] = values[idx[i]]; rank[idx[i]] = i; }
    // The lower rank wanted, and whether the one above it is needed: the
    // median's mid (odd) or mid - 1 and mid (even); type 7's floor(h), h + 1.
    var h = (n - 1) * q, lo, two;
    if (!stat) { lo = n % 2 === 1 ? Math.floor(n / 2) : n / 2 - 1; two = n % 2 === 0; }
    else { lo = Math.floor(h); two = h !== lo; }
    for (k = 0; k < reps; k++) {
      cnt.fill(0);
      for (i = 0; i < n; i++) cnt[rank[Math.floor(r() * n)]]++;
      var c = 0, j = 0;
      while (c + cnt[j] <= lo) { c += cnt[j]; j++; }
      var a = order[j], b = a;
      if (two && c + cnt[j] === lo + 1) { j++; while (cnt[j] === 0) j++; b = order[j]; }
      // The very expressions the sorted paths used, so the same bits.
      meds[k] = !stat ? (two ? (a + b) / 2 : a) : (two ? a + (h - lo) * (b - a) : a);
    }
  } else {
    var buf = new Array(n);
    for (k = 0; k < reps; k++) {
      for (i = 0; i < n; i++) buf[i] = values[Math.floor(r() * n)];
      meds[k] = stat(buf);
    }
  }
  meds.sort();
  return [round2(meds[Math.floor(0.025 * reps)]), round2(meds[Math.ceil(0.975 * reps) - 1])];
}
// The way it was, kept for the check that the fast path gives the same.
function bootCIPlain(values, seed, reps) {
  if (!values || values.length < 2) return null;
  reps = reps || BOOTS;
  var r = rng(seed), n = values.length, meds = new Array(reps), buf = new Array(n);
  for (var k = 0; k < reps; k++) {
    for (var i = 0; i < n; i++) buf[i] = values[Math.floor(r() * n)];
    meds[k] = A.median(buf);
  }
  meds.sort(function (a, b) { return a - b; });
  return [round2(meds[Math.floor(0.025 * reps)]), round2(meds[Math.ceil(0.975 * reps) - 1])];
}

// Evidence about the market, by the rig's one rule, with a rate to rank.
function counted(o) {
  return A.trustworthy(o) && typeof o.perHour === 'number' && isFinite(o.perHour);
}

function seenAt(o) {
  return typeof o.firstAt === 'number' && isFinite(o.firstAt) ? o.firstAt : o.at;
}

// The block an offer is held still in: advice.js's eight, as map.html asks it.
function stratum(o) { return A.blockOf(o.at); }

// The driver's shift day, 'YYYY-MM-DD': advice.js's dayKeyOf, the key its
// outingsIn counts by (DAY_STARTS_AT).
var outingOf = A.dayKeyOf;

/* The 2-mile cell a point is in, as { id, s, w, n, e, lat, lon }. Rows of
 * GRID_MI/69 degrees of latitude; each row's columns as wide as GRID_MI at
 * that row's middle, so a cell is about square wherever it is. */
function cellOf(at) { return gridCell(at, GRID_MI); }
// ...and the same squares at any size (the Offers around you tab's
// quarter-mile bins), so there is one grid rule.
function gridCell(at, mi) {
  if (!at || !isFinite(at.lat) || !isFinite(at.lon)) return null;
  var dLat = mi / 69.0;
  var i = Math.floor(at.lat / dLat);
  var mid = (i + 0.5) * dLat;
  var dLon = mi / (69.0 * Math.max(0.2, Math.cos(mid * Math.PI / 180)));
  var j = Math.floor(at.lon / dLon);
  return { id: i + ':' + j, s: round5(i * dLat), n: round5((i + 1) * dLat),
           w: round5(j * dLon), e: round5((j + 1) * dLon),
           lat: round5(mid), lon: round5((j + 0.5) * dLon) };
}
function round5(v) { return Math.round(v * 1e5) / 1e5; }

/* The hours views every ranked table is worked out for: all hours, then
 * advice.js's eight three-hour blocks by number (analyse, and the CSVs
 * that write a row per view). */
var VIEWS = ['all', 0, 1, 2, 3, 4, 5, 6, 7];

/* --- the words a verdict prints with ------------------------------------
 *
 * A p-value, a share and a group's name as the one-line verdicts, the
 * Targets lines, the Best offers lines and the CSVs all print them. */

function pText(p) {
  if (p === null || p === undefined) return 'not tested (fewer than two cells clear the floor)';
  return p === 0 ? 'p < ' + (1 / SHUFFLES).toFixed(4) : 'p = ' + p.toFixed(3);
}

// A group's name in the share lines: a place with where it is, as there
// may be several branches of one name.
function shareName(r, kind, name) {
  var l = labelOf(r, kind, name), p = kind === 'place' ? r.places[name] : null;
  return p ? l + ' near ' + p.lat.toFixed(3) + ', ' + p.lon.toFixed(3) : l;
}

function pct(n, of) { return of ? (Math.round(n / of * 1000) / 10).toFixed(1) + '%' : 'n/a'; }

function labelOf(r, kind, name) {
  if (kind === 'place') return (r.places[name] && r.places[name].label) || name;
  if (kind === 'rest') return (r.restNames && r.restNames[name]) || name;
  if (kind === 'grid') {
    var c = r.cells[name];
    return c ? 'cell near ' + c.lat.toFixed(3) + ', ' + c.lon.toFixed(3) : name;
  }
  return name;
}

module.exports = {
  MIN_N: MIN_N, MIN_OUTINGS: MIN_OUTINGS, ALPHA: ALPHA, SHUFFLES: SHUFFLES, BOOTS: BOOTS, GRID_MI: GRID_MI,
  DROP_MIN_N: DROP_MIN_N, NEXT_GAP_MIN: NEXT_GAP_MIN, PLACE_SAME_MI: PLACE_SAME_MI, NBX_LIMIT: NBX_LIMIT,
  FINISHED: FINISHED, AT_THE_DOOR: AT_THE_DOOR, GPS_TIMED: GPS_TIMED, round2: round2, minOf: minOf,
  maxOf: maxOf, rng: rng, seedOf: seedOf, bootCI: bootCI, bootCIPlain: bootCIPlain, counted: counted,
  seenAt: seenAt, stratum: stratum, outingOf: outingOf, cellOf: cellOf, gridCell: gridCell, round5: round5,
  VIEWS: VIEWS, pText: pText, shareName: shareName, pct: pct, labelOf: labelOf,
};
