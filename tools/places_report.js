/* Where the good offers start, measured on the NucBox after the fact.
 *
 *   node tools/places_report.js http://localhost:8082 --out ~/places-report
 *   node tools/places_report.js http://localhost:8082 --out ~/places-report \
 *        --gps ~/gpslog --since 2026-09-01 --nominatim http://localhost:8088
 *
 * The owner's words (25 Oct 2026): "It would be helpful know where and what
 * places turn up good offers. If you could find a helpful way to visualize and
 * show that information, a table is also very helpful."
 *
 * AN OFFLINE REPORT, NOT A RIG HEAT MAP. AUDITS.md's "A heat map of $/hr by
 * area, asked for, designed, and refuted on the data" is binding on the rig,
 * and nothing here reaches the rig: no verdict, no target, no panel and no
 * page the rig serves reads this file or its output. It answers that entry's
 * three faults rather than walking past them:
 *
 *   - the miscolouring. A cell coloured by a fixed band at n=12 takes the
 *     wrong colour 21-25% of the time with no effect at all. Nothing here is
 *     coloured by a band. Every ranked cell is a median with a bootstrap
 *     interval on a dot plot, and a cell is drawn in colour ONLY where the
 *     grouping's own permutation test beats chance AND the cell's interval of
 *     its hour-held score is clear of zero. Everything else is grey and says
 *     "not distinguishable from the rest".
 *   - the hour. Each offer is measured against what the OTHER cells paid in
 *     its own three-hour block (Advice.areas' `matched`, the baseline the
 *     town table ships with), and the permutation is confined within blocks
 *     (Advice.areas' `strata`), so the test asks the question the score
 *     answers.
 *   - the biased third. Pickups that cannot be placed are counted, and the
 *     pay gap between placed and unplaced is printed with its own test, per
 *     shift day, at the top of the page, not in a footnote.
 *
 * ONE RULE IN ONE PLACE. The rows are /api/journal's, so the server's fold
 * decides which reading of a card to believe (as tools/measure_places.js
 * reads them); `Advice.trustworthy` decides which rows are evidence;
 * `Advice.areas` runs the ranking test; `MV.searchPlan`, `MV.discFor`,
 * `MV.NbxSearch` and `MV.pickPlace` place a pickup exactly as the rig's own
 * server places a held order's pickup (server.js searchHeldPickup /
 * searchHeldPickupName): a printed door by the door inside the disc round the
 * card's GPS fix; a store's name by `pickPlace` inside that disc, pinned only
 * when one place of that name answers; a chain's several branches, a list cut
 * at the limit, or no fix at all is UNPLACED and counted. "Would the driver's
 * rule take it" is the rig's own verdict on the row (`state === 'go'`), never
 * a new rule. The GPS log is read by tools/shift_report.py's load_fixes,
 * which reads it through rpi/gps.py's gate.
 *
 * NOT /api/places. That cache holds map.html's answers, chosen by a
 * different rule (the public geocoder's first answer inside a sixty-mile box
 * round the driver's town), and reusing them would place a "McDonald's" this
 * report's rule refuses. This keeps its own cache of the NucBox's ANSWERS (the
 * hit lists, keyed by the question), never of its decisions, so a re-run is
 * free and still decided by today's rules.
 *
 * PRIVACY. The report holds real places, so it is written outside the
 * repository (refused inside it) and never committed. Pickups are businesses
 * and are named. Dropoffs are customers: they are placed only to be counted
 * by area, a 2-mile cell with fewer than DROP_MIN_N trips is not named at all,
 * and no door, name or coordinate of a dropoff is written anywhere — the
 * answer cache is the one file that holds a dropoff's text, as the question
 * asked, and it lives in ~/.cache, beside nothing that is shared.
 *
 * Read-only against the server and the NucBox. The public geocoder is never
 * asked.
 *
 * THE SECOND PASS (26 Oct 2026), experimental and descriptive, one tab each:
 * your takes and their real $/hr, card against real minutes, restaurant
 * waits, strand risk per store, how busy an area is while parked (off the
 * GPS), Uber against DoorDash, add-on and stacking share, places gone quiet,
 * a weekly trend and $/mi. See "the second pass" below for each one's rule
 * and floor; tools/places_nightly.sh rebuilds the whole report every night.
 *
 * THE THIRD PASS (26 Oct 2026, after the owner's first real run), experimental:
 * pickups placed by the rig's whole search chain with every placement's level
 * (door, corner, name; band, area, street), the street index asked even with
 * --nominatim (--streets), cards with no fix searched in the driver's region
 * by a printed door and town; the rig's store waits (--waits); Drop presses
 * timed by the GPS; and a "Best offers" tab on the top of the distribution —
 * hour-held top-25% / top-10% offers, P75 / P90, good offers per hour of
 * waiting, the expected $/hr of working an area, dead miles after a drop and
 * offer size bands. See "the third pass" below for each rule and floor.
 *
 * THE STRATEGY TAB (7 Nov 2026, the owner: "being able to know what is a good
 * $/hr and $/mi metrics to expect would help decide which offers to take and
 * which to decline"): what offers looked like, what cards turned into, and
 * what holding out for each line of the panel's $/hr paid per hour on shift.
 * Worked out by tools/strategy.js — the end-of-shift report prints the same
 * numbers with --strategy — off this report's offers and its takes as realOf
 * times them; see strategyOrders below for the miles. Descriptive, like the
 * rest: no verdict, target or panel reads it.
 *
 * THE LAYOUT (7 Nov 2026, the owner, on a phone and a laptop: "consider how
 * the page and tabs are laid out, is there a better format for all this
 * information?"). Reorganised, nothing cut: an Overview that opens the page
 * (the few numbers that matter, picked out of the report object, each
 * linking to its tab with its n under it), the twenty tabs grouped by the
 * question each answers (GROUPS), a sticky nav of groups over the chosen
 * group's tabs, long tables folded under their headings on a phone (fold),
 * the curve drawn small for a phone and time of day as bars (blockChart).
 * Every old #hash still opens its tab; #overview is the new default, and a
 * fold's id opens the tab it sits in.
 *
 * WHEN & WHERE (18 Nov 2026). The owner, a selective driver, wants to know
 * which areas pay at a given time, and the answer was spread over a score of
 * tabs that each held one slice. One tab, first in "Where & when": pick the
 * driver's weekday (or Weekdays, Weekends, Any day) and a block, and the
 * areas where the car waited are ranked by good offers per hour waited, good
 * being a fixed top-share cutoff over the whole range. Off the Waited tab's
 * own line; see whenWhere below for the slots, the cutoff, the floor and the
 * marking. Read only, like everything here.
 */

'use strict';

var fs = require('fs');
var os = require('os');
var path = require('path');
var cp = require('child_process');

var A = require('../advice.js');
var MV = require('../map-view.js');
var AS = require('../assemble.js');
var OP = require('../offer-parser.js');
// What $/hr to expect and what holding out paid (the Strategy tab), shared
// with the end-of-shift report so the two print one answer.
var S = require('./strategy.js');
// trends.js's dispersion and rateShade, for When & where's interval (the
// reporting review's S2): the same widening the Trends grid's good per hour
// takes, so the two pages' marks mean the same thing.
var TR = require('../trends.js');
// ...and what the app paid, for an order this report could not time (uberTimingFor).
var E = require('../earnings.js');

var ROOT = path.resolve(__dirname, '..');

/* The floor under a ranked cell, in offers. AUDITS.md's heat-map entry: at
 * fixed colour bands a cell needs 30-60 before its colour can be trusted, and
 * the floor and the scale must be derived together. Here there is no band —
 * colour comes only from a test and an interval — so the floor is the low end
 * of that range: below it a bootstrap interval of a median over a tail this
 * long is not worth drawing. Below it a cell is "too few", listed with its n
 * and never ranked or tested. */
var MIN_N = 30;
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
var DROP_MIN_N = 10;
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
// A Drop press the GPS log timed (timePresses below): its own `by`.
var GPS_TIMED = 'drop (gps-timed)';

/* --- small pieces -------------------------------------------------------- */

function round2(v) { return v === null || v === undefined ? null : Math.round(v * 100) / 100; }

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
    meds[k] = MV.median(buf);
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

// The driver's shift day, advice.js's outingsIn key (DAY_STARTS_AT).
function outingOf(at) {
  var d = new Date(at);
  if (!isFinite(d.getTime())) return null;
  d.setHours(d.getHours() - A.DAY_STARTS_AT);
  var mm = String(d.getMonth() + 1).padStart(2, '0'), dd = String(d.getDate()).padStart(2, '0');
  return d.getFullYear() + '-' + mm + '-' + dd;
}

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

/* --- placing a pickup, by the rig's own rules ----------------------------
 *
 * What the pickup text is, as a question: a door, a store's name, a corner,
 * a street with no number, or nothing searchable. searchPlan decides; the
 * name plan is the server's pickupNamePlan (three letters at least). */
function pickupKind(text) {
  var plan = typeof text === 'string' && text ? MV.searchPlan(text) : null;
  if (!plan) return { kind: 'none', plan: null };
  if (plan.kind === 'street') return { kind: plan.door ? 'door' : 'street', plan: plan };
  if (plan.kind === 'cross') return { kind: 'cross', plan: plan };
  if (plan.kind === 'name' && plan.q && /[A-Za-z]{3}/.test(plan.q)) return { kind: 'name', plan: plan };
  return { kind: 'none', plan: plan };
}

// The words a refusal is counted under. One list, printed as is.
var WHY = {
  nofix: 'no GPS fix on the card',
  nofixdoor: 'no GPS fix on the card, and no town or ZIP printed to search the region by',
  regiontown: 'no fix; the door found in the region is not in the printed town',
  corners: 'a corner whose streets meet in several places',
  nomeet: 'a corner whose streets do not meet inside the card\'s reach',
  nostreet: 'a street the street index does not hold',
  notwo: 'nothing searchable',
  long: 'a street with no door number',
  several: 'several places answer (a chain, or branches)',
  capped: 'several places answer (a chain, or branches)',
  // The search's own refusals, in the rig's words (MV.REFUSAL_WORDS; AUDITS.md,
  // Done, "Four refusals were one label"). All four were "not found inside the
  // card's reach" until 9 Nov 2026, where the rig said that of 'none' alone,
  // and three of them are not about the reach: a street found without its
  // number, a store's name OSM spells otherwise, a corner run together. A
  // placement carries its own words (`said`, `refusedSaid`: wordsOf, which
  // splits 'none' by what the box held); these are for one that does not.
  noplace: MV.REFUSAL_WORDS.noname,
  none: MV.REFUSAL_WORDS.nobox,
  nodoor: MV.REFUSAL_WORDS.nodoor,
  together: MV.REFUSAL_WORDS.together,
  cross: 'a corner, and no street index to ask',
  street: 'a street with no door number',
  notext: 'nothing searchable',
  unreachable: 'the NucBox did not answer',
  refused: 'the NucBox did not answer',
};

/* --- THE THIRD PASS: the rig's whole search chain, and its levels ---------
 *
 * The owner's first real run (25 Oct 2026) placed 8% of pickups: a corner
 * with no street index (the run asked Nominatim directly and so never asked
 * the index), a street with no door number, several answers, and cards with
 * no fix. The owner, 26 Oct: "Go ahead with all three, fast track to
 * experimental."
 *
 * ONE RULE IN ONE PLACE, still. NbxSearch.place IS the chain server.js
 * composes as doorChain for a held order's door — the street as printed
 * (pickInDisc), then the type word left out where the street was not in
 * reach (MV.streetRetry / retryWanted / pickRetry), the directional the other
 * way where the street was found and not the door (MV.dirRetry / dirWanted /
 * afterDir), the street index's one street for the name as read (nameWanted /
 * nameRetry / pickNamed), and for a door nothing answered its street alone
 * (MV.streetArea) — so this asks it, never a copy. A corner is NbxSearch's
 * corner (the street index's /cross, pickInDisc), a numberless street its
 * `whole` (NbxSearch.streetArea), a refused door's candidates the distance
 * band (NbxSearch.band: MV.bandTarget's Uber `toPickupMiles` or DoorDash's
 * upper bound, road miles off the relay's /route, MV.bandPick), and the
 * areas pickInDisc puts beside a refusal (MV.withArea: 'several', 'nodoor',
 * 'capped') are read as they come.
 *
 * LEVELS. Every placement says how it was placed:
 *   'door'    a printed door, found at its number (one place, or agreeing)
 *   'corner'  where the two streets meet, one meeting inside the reach
 *   'name'    a store's name, one place of it answered (pickPlace)
 * ...those three are a POINT. And three that are an AREA, never a pin on the
 * rig and approximate here, each with its spread (the two farthest
 * candidates apart, MV's own `miles`):
 *   'band'    the candidates the card's own miles by road kept (bandPick)
 *   'area'    the door's candidates, one general area (withArea)
 *   'street'  the street alone, its points one area (streetArea)
 *
 * FIX-LESS CARDS. Older cards carry no fix, so no disc. A printed door with
 * its town or ZIP after a comma is searched in the driver's own REGION
 * instead (regionOf: the bounding box of every good card fix in the record,
 * REGION_MARGIN_MI wider each way, as a disc round its middle reaching its
 * corners), through the same chain, and kept only at door or corner level
 * and only where an answer at the pin carries the printed town or ZIP: a
 * house number on a street of that name is not one place across a metro, but
 * in its own town it is. A store NAME with no fix stays unplaced — a chain is
 * everywhere, and which branch is a guess. No band (it measures from the
 * fix) and no area (a region is no card's reach) without a fix. */
var REGION_MARGIN_MI = 5;
// The band asks for its roads with the run's patience, not the panel's: an
// offline run can wait, and a band given up is the refusal as it was.
var BAND_WAIT_OFFLINE_MS = 30000;
// The level a placement is at, and whether it is a point.
var POINT_LEVELS = ['door', 'corner', 'name'];
var APPROX_LEVELS = ['band', 'area', 'street'];

/* The printed town or ZIP of an address text, as the card printed it after a
 * comma (map-view.js townOf, the rule the towns table reads), or null. */
function printedTown(text) {
  var s = String(text || '');
  var zip = /,[^,]*?\b(\d{5})(?:-\d{4})?\b/.exec(s);
  var town = MV.townOf(s, A.area);
  return town || (zip ? zip[1] : null) ? { town: town || null, zip: zip ? zip[1] : null } : null;
}

/* The driver's region off the record's own good card fixes (MV.cardFix):
 * their bounding box, REGION_MARGIN_MI wider on each side, and the disc
 * round its middle that reaches its corners. Null with no fix at all. */
function regionOf(offers) {
  var s = Infinity, n = -Infinity, w = Infinity, e = -Infinity, k = 0;
  (offers || []).forEach(function (o) {
    var f = o && MV.cardFix(o).at;
    if (!f) return;
    k += 1;
    s = Math.min(s, f.lat); n = Math.max(n, f.lat); w = Math.min(w, f.lon); e = Math.max(e, f.lon);
  });
  if (!k) return null;
  var dLat = REGION_MARGIN_MI / 69.0;
  var mid = (s + n) / 2;
  var dLon = REGION_MARGIN_MI / (69.0 * Math.max(0.2, Math.cos(mid * Math.PI / 180)));
  var box = { s: round5(s - dLat), n: round5(n + dLat), w: round5(w - dLon), e: round5(e + dLon) };
  var at = { lat: round5((box.s + box.n) / 2), lon: round5((box.w + box.e) / 2) };
  var miles = MV.crowMiles(at, { lat: box.n, lon: box.e });
  return { box: box, fixes: k, marginMi: REGION_MARGIN_MI,
           disc: { at: at, miles: Math.round(miles * 100) / 100, card: null, corrected: false, region: true } };
}

// An answer's hit list says the printed town (or ZIP) near `at`.
function townAt(res, at, said) {
  var hits = res && res.seen && Array.isArray(res.seen.hits) ? res.seen.hits : [];
  return hits.some(function (h) {
    if (MV.crowMiles(h, at) > PLACE_SAME_MI) return false;
    var nm = String(h.name || '').toLowerCase();
    return (said.town && nm.indexOf(said.town.toLowerCase()) >= 0) || (said.zip && nm.indexOf(said.zip) >= 0);
  });
}

/* The words a refusal is counted under in the Coverage tab and the summary:
 * the rig's for the search's own four (MV.refusalWords with `count`, so a
 * 'none' is "no such door in the reach's box" or "door found past the reach"
 * by what the bounded box held, one label each and no miles; a store asked by
 * its name alone, `byName`), WHY's for the rest — "several places answer (a
 * chain, or branches)" is the report's own, and says more here than the
 * rig's "several answers". `res` is the search's answer, `why` the key kept. */
var RIG_WORDED = ['none', 'noplace', 'nodoor', 'together'];
function wordsOf(res, why, kind) {
  if (RIG_WORDED.indexOf(why) >= 0) {
    var r = res && res.why === why ? res : { why: why };
    var w = MV.refusalWords(r, { count: true, byName: kind === 'name' });
    if (w) return w;
  }
  return WHY[why] || why;
}

function placedAt(at, kind, level, spread, extra) {
  return Object.assign({ at: { lat: at.lat, lon: at.lon }, why: null, kind: kind, level: level,
                         spread: spread ? Math.round(spread * 100) / 100 : 0 }, extra || {});
}

/* One pickup, placed or refused: { at, why, kind, level, spread }. `nbx` is
 * an NbxSearch; `streets` whether the street index answers; `ctx`
 * { region (regionOf), road (the router answers), budget ({left}, road
 * questions) }. Without `ctx` or `streets` it is the first pass's rule. */
async function placePickup(nbx, text, card, streets, ctx) {
  ctx = ctx || {};
  var k = pickupKind(text);
  if (k.kind === 'none') return { at: null, why: 'notext', kind: k.kind };
  if (k.kind === 'street' && !streets) return { at: null, why: 'street', kind: k.kind };
  if (k.kind === 'cross' && !streets) return { at: null, why: 'cross', kind: k.kind };
  var disc = MV.discFor(card || null), region = false;
  if (!disc) {
    var said = k.kind === 'door' ? printedTown(text) : null;
    if (!said || !ctx.region) return { at: null, why: k.kind === 'door' ? 'nofixdoor' : 'nofix', kind: k.kind };
    disc = ctx.region.disc;
    region = said;
  }
  var res;
  try {
    if (k.kind === 'name') res = await nbx.placeSearch(k.plan.q, disc);
    else if (k.kind === 'street') {
      // The street index's `whole` for the street as printed (NbxSearch.
      // streetArea asks it for a door plan's street; a numberless street IS
      // its street), its points one area by MV.streetArea's rule.
      var body = await nbx.get('/whole?name=' + encodeURIComponent(k.plan.street) + '&box='
                               + encodeURIComponent(MV.discBox(disc)));
      var a = body && !body.unreachable && !body.refused ? MV.streetArea(body, disc) : null;
      return a ? placedAt(a, k.kind, 'street', a.miles) : { at: null, why: 'street', kind: k.kind };
    } else {
      // ...a printed door with its store's name beside it (`ctx.store`,
      // placeRow's), for the street printed short: the index's /tail, the
      // door by the one full name, else the store by its name along that
      // street (NbxSearch.place `store`, MV.pickStoreAlong) — the rig's own
      // order (server.js pickupTail), and only after the door refused.
      res = await nbx.place(text, disc, { streets: !!streets,
                                          store: k.kind === 'door' && ctx.store ? ctx.store : null });
    }
  } catch (e) {
    return { at: null, why: 'refused', kind: k.kind };
  }
  if (res && res.at) {
    if (region && !townAt(res, res.at, region)) return { at: null, why: 'regiontown', kind: k.kind };
    // (A store found by its name along its street is a place by its name,
    // not its door: 'name' level, a point all the same.)
    return placedAt(res.at, k.kind, k.kind === 'name' || res.by === 'store' ? 'name'
                    : k.kind === 'cross' ? 'corner' : 'door', 0,
                    region ? { region: true } : null);
  }
  var why = res && res.why;
  why = WHY[why] ? why : 'none';
  var said = wordsOf(res, why, k.kind);
  if (region || k.kind !== 'door') return { at: null, why: why, said: said, kind: k.kind };
  // The door refused: the band first (it narrows; an area it found is tighter
  // than the one it was chosen from), else the area beside the refusal.
  if (ctx.road) {
    var spec = MV.bandTarget(card, 'pickup');
    var band = spec ? await nbx.band(text, res, disc, spec, null, ctx.budget || null, !!streets) : null;
    if (band) {
      return placedAt(band, k.kind, 'band', band.miles, { refused: why, refusedSaid: said, cardMi: band.cardMi });
    }
  }
  if (res && res.area) {
    return placedAt(res.area, k.kind, res.area.rough ? 'street' : 'area', res.area.miles,
                    { refused: why, refusedSaid: said });
  }
  return { at: null, why: why, said: said, kind: k.kind };
}

/* --- a DoorDash pickup by the door its card printed, before its name -------
 *
 * THE FAULT (AUDITS.md, Done, "Four refusals were one label", and the Open
 * entry of 7 Nov it came from, (4)). A DoorDash stops card prints the store's
 * NAME (`pickup`, "Utopian Bowl Kitchen") and under it the store's DOOR
 * (`pickupLine`, "164 Ash Row, Faketown"; with two stores or more every one
 * is listed, `stores` [{name, door}], the parser's `places`/`placeDoors`).
 * The rig searches the printed door — server.js searchCardEarly asks
 * `pickupLine` first for an offer, pickupAsks for a held order, door level in
 * the card's disc, the store's name beside it for pickupTail — and asks a
 * store by its bare name only when no door is on record at all. This report
 * read `row.pickup` alone. So every DoorDash pickup was asked as a NAME, and
 * MV.pickPlace pins a name only where OSM holds a feature with the same words
 * (placeNamed, one slip) and only one inside the disc — and a one-leg DoorDash
 * card ('shape', 528 of the real week's 1,166 offers) sets no radius, so its
 * disc is the sixty-mile default, where a chain's name is every branch. The
 * printed door, which pins at door level wherever the NucBox holds its
 * number, was never asked.
 *
 * So, in the rig's order: the row's printed door (printedDoor) through
 * placePickup — door level inside the card's disc, the retries, and the
 * store's name beside it for MV.pickStoreAlong ONLY after the door refused
 * (`ctx.store`) — and a POINT from it is kept: 'door', or 'name' for the
 * store along its street. No point: the store's name as this report always
 * asked it (pickPlace: one place of that name in the disc, the justified
 * exact place the rig's held pickup by name takes), so nothing placed before
 * is lost; and with neither, the door's approximate area or band, or the
 * DOOR's refusal, which is what is counted (the rig's rule: the door's
 * refusal stands). The band is asked only then, so its road questions are
 * not spent on a pickup the name places. `asked` says which text placed it
 * ('door' or 'name'). A row with no printed door is placed as before. */
function printedDoor(row) {
  if (!row || typeof row.pickup !== 'string' || !row.pickup.trim()) return null;
  var door = typeof row.pickupLine === 'string' && row.pickupLine.trim() ? row.pickupLine.trim() : null;
  if (!door) {
    // ...else the door the card listed beside the store this row names:
    // `stores` (the offer line's, server.js storesOf), or the parser's two
    // lists side by side. The FIRST store's is `pickupLine` itself.
    var list = Array.isArray(row.stores) ? row.stores
      : Array.isArray(row.places) && Array.isArray(row.placeDoors) && row.places.length === row.placeDoors.length
        ? row.places.map(function (n, i) { return { name: n, door: row.placeDoors[i] }; }) : [];
    for (var i = 0; i < list.length; i++) {
      var st = list[i];
      if (st && typeof st.name === 'string' && typeof st.door === 'string' && st.door.trim()
          && AS.sameStore(st.name, row.pickup)) { door = st.door.trim(); break; }
    }
  }
  if (!door || door === row.pickup.trim()) return null;
  return pickupKind(door).kind === 'door' ? door : null;
}

async function placeRow(nbx, row, streets, ctx) {
  ctx = ctx || {};
  var door = printedDoor(row);
  if (!door) return placePickup(nbx, row.pickup, row, streets, ctx);
  var first = await placePickup(nbx, door, row, streets, Object.assign({}, ctx, { road: false, store: row.pickup }));
  if (first.at && isPoint(first)) return Object.assign(first, { asked: 'door' });
  if (pickupKind(row.pickup).kind === 'name') {
    var byName = await placePickup(nbx, row.pickup, row, streets, ctx);
    if (byName.at) return Object.assign(byName, { asked: 'name', doorWhy: first.at ? first.refused : first.why });
  }
  var last = ctx.road ? await placePickup(nbx, door, row, streets, Object.assign({}, ctx, { store: row.pickup }))
    : first;
  return Object.assign(last, { asked: 'door' });
}

/* A taken order's dropoff, placed to be COUNTED by area and nothing else:
 * by the same chain (no band: it measures from the placed pickup), kept at
 * any level whose spread is a 2-mile cell's to tell (AREA_MI). */
async function placeDropoff(nbx, text, card, streets, ctx) {
  var k = pickupKind(text);
  if (k.kind !== 'door' && !(k.kind === 'cross' && streets)) return null;
  var r = await placePickup(nbx, text, card, streets, { region: ctx && ctx.region });
  return r && r.at && !(r.spread > MV.AREA_MI) ? { lat: r.at.lat, lon: r.at.lon } : null;
}

/* --- a card read with an order in the car, searched from that order's end --
 *
 * THE FAULT (AUDITS.md, the Open entry of 7 Nov, (5)): the one real reach
 * miss. An offer shown while another order is held may print miles that
 * start at THAT order's end, not at the car (the owner's 29 Oct shift, #6:
 * 4.3 mi from #5's door). The rig gives a held order taken beside another
 * the `also` circles that cure it (MV.afterParts, round each such end the
 * card's miles and SLACK_MI and the end's own `widen`), and since 9 Nov an
 * offer read while orders are held the same (server.js offerCard). This
 * report's rows carry no `after`, so a stacked offer was searched from the
 * car alone: 10,000 invented stacked offers, 15.1% of their stores outside
 * the disc, most of those "no such door in the reach's box" because the
 * bounded box never reached them.
 *
 * So the report rebuilds `after` the rig's way, from the record: every order
 * TAKEN (the journal's `taken`, takenRuns) whose Took was before the card was
 * first seen and which was not yet put down then, the card's own order
 * aside — its end as one anchor (MV.endAnchor's shape, {lat, lon, widen,
 * from}), at most MV.AFTER_MAX. The anchor is where the order ENDED:
 *
 *   - the GPS at its drop, for an order the GPS or the app's screen put down
 *     at the door (or a press the GPS log timed, a finish the GPS made):
 *     `widen` AFTER_GPS_WIDEN_MI, from 'gps' — the car at the door, give or
 *     take the gate's error and where it stopped (CHOSEN, NOT MEASURED: the
 *     rig's AGREE_MI, its "one place" for two pins); an untimed Drop press is
 *     no position, as timePresses says;
 *   - else its dropoff placed by the same chain as a pickup (placePickup in
 *     its own card's disc): a door or a corner `widen` 0 ('pin'), an area
 *     its spread when that is a general area (MV.AREA_MI or less: 'area'),
 *     exactly the rig's endAnchor over an end pin or an end area.
 *
 * An order with neither gives no circle (MV.endAnchor says why not a disc).
 * A pin still needs door level, or one place of that name, INSIDE the union
 * of circles — the circles widen where a door may be, never what a pin
 * needs. Customers' doors: placed only to anchor, never written anywhere
 * (the answer cache aside, as for every dropoff). */
var AFTER_GPS_WIDEN_MI = MV.AGREE_MI;
var GPS_ANCHOR_BY = ['gps', 'screen', GPS_TIMED].concat(FINISHED);

/* Each taken order's end as an anchor: [{id, tookAt, endedAt, anchor}],
 * anchor null where neither the GPS nor its dropoff gives one. `gpsPos` is
 * main's, keyed id@endedAt. */
async function heldEndsOf(nbx, taken, byId, gpsPos, streets, region) {
  var out = [];
  for (var i = 0; i < (taken || []).length; i++) {
    var t = taken[i];
    if (!t || typeof t.tookAt !== 'number' || typeof t.endedAt !== 'number' || !(t.endedAt > t.tookAt)) continue;
    var anchor = null;
    var g = gpsPos && gpsPos[t.id + '@' + t.endedAt];
    if (g && GPS_ANCHOR_BY.indexOf(t.by || 'drop') >= 0) {
      anchor = { lat: g.lat, lon: g.lon, widen: AFTER_GPS_WIDEN_MI, from: 'gps' };
    } else if (byId[t.id] && typeof byId[t.id].dropoff === 'string') {
      var row = byId[t.id];
      var r = await placePickup(nbx, row.dropoff, row, streets, { region: region });
      if (r && r.at) {
        anchor = MV.endAnchor(isPoint(r) ? { pin: r.at }
          : gridOk(r) ? { area: { lat: r.at.lat, lon: r.at.lon, miles: r.spread } } : null);
      }
    }
    out.push({ id: t.id, tookAt: t.tookAt, endedAt: t.endedAt, anchor: anchor });
  }
  return out;
}

/* The `after` a row's card gets: the anchors of the orders in the car when it
 * was first seen (seenAt), its own order aside, the earliest-taken first,
 * at most MV.AFTER_MAX. [] when none was held, so its disc is as before. */
function afterFor(row, held) {
  var when = row ? seenAt(row) : null;
  if (typeof when !== 'number' || !isFinite(when)) return [];
  return (held || []).filter(function (h) {
    return h.anchor && h.id !== row.id && h.tookAt < when && when < h.endedAt;
  }).sort(function (a, b) { return a.tookAt - b.tookAt; }).slice(0, MV.AFTER_MAX).map(function (h) {
    return Object.assign({ of: h.id }, h.anchor);
  });
}

/* PLACES TAKE A POINT, AND AN AREA ONLY WHERE IT IS ONE STORE'S. A place is
 * a store at a location, and an area is not a location: so an approximate
 * placement joins Places only (a) within PLACE_SAME_MI (AGREE_MI) of a point
 * placement of the same store name — the area agrees with a door or name
 * already found for that store, and is that place — or (b) where its own
 * spread is PLACE_APPROX_MI or less, a few blocks, the size of one shopping
 * centre. 0.3 mi is CHOSEN, NOT MEASURED: AGREE_MI (0.2) is the rig's "one
 * place" for two pins, and a spread is the two FARTHEST candidates, so its
 * middle is within half of it of either — 0.15 mi, inside AGREE_MI. The
 * 2-mile grid takes every level whose spread is AREA_MI or less (a mile:
 * the rig's own general area, half a cell). Towns read the card's text and
 * are unchanged. */
var PLACE_APPROX_MI = 0.3;
function isPoint(r) { return !!(r && r.at && (!r.level || POINT_LEVELS.indexOf(r.level) >= 0)); }
function gridOk(r) { return !!(r && r.at && !(r.spread > MV.AREA_MI)); }

// The store a pickup names, as printed: Uber's bracketed street off the end,
// or for a printed door (a DoorDash stops line) the line before its comma.
function storeLabel(text) {
  var s = AS.storeOf(String(text || '')).replace(/\s+/g, ' ').trim();
  if (/^\d/.test(s)) s = s.split(',')[0].trim();
  return s || String(text || '').trim();
}

/* Pins grouped into places: one store (Assemble.storeKey of its label) at one
 * location (within PLACE_SAME_MI of the place's first pin). Returns
 * { byRow: {rowIndex: placeId}, places: {id: {label, lat, lon, pins}} }. */
function placesOf(placed) {
  var byKey = Object.create(null), places = Object.create(null), byRow = Object.create(null);
  // Points first, so an area can find the door or name it agrees with
  // (PLACE_APPROX_MI above); a pin with no `level` is a point, as before.
  var points = placed.filter(function (p) { return isPoint(p); });
  var areas = placed.filter(function (p) { return !isPoint(p); });
  points.concat(areas).forEach(function (p) {
    var key = AS.storeKey(p.label) || p.label.toLowerCase();
    var list = byKey[key] || (byKey[key] = []);
    var hit = null;
    for (var i = 0; i < list.length; i++) {
      if (MV.crowMiles(list[i].first, p.at) <= PLACE_SAME_MI
          && (isPoint(p) || list[i].point || p.spread <= PLACE_APPROX_MI)) { hit = list[i]; break; }
    }
    if (!hit && !isPoint(p) && !(p.spread <= PLACE_APPROX_MI)) return;
    if (!hit) {
      hit = { id: key + '#' + (list.length + 1), first: p.at, pins: [], labels: {}, point: isPoint(p) };
      list.push(hit);
    }
    hit.pins.push(p.at);
    hit.labels[p.label] = (hit.labels[p.label] || 0) + 1;
    byRow[p.row] = hit.id;
  });
  Object.keys(byKey).forEach(function (k) {
    byKey[k].forEach(function (h) {
      var mid = MV.middleOf(h.pins);
      var label = Object.keys(h.labels).sort(function (a, b) {
        return h.labels[b] - h.labels[a] || (a < b ? -1 : 1);
      })[0];
      places[h.id] = { label: label, lat: round5(mid.lat), lon: round5(mid.lon), pins: h.pins.length };
    });
  });
  return { byRow: byRow, places: places };
}

/* --- the ranking, its test, and its intervals ----------------------------
 *
 * `rows` are offer rows (or anything carrying `perHour` and `at`), `key` the
 * cell an offer belongs to. Advice.areas does the grouping, the floor and the
 * permutation test — `hold` hands it the three-hour block as `strata`, so its
 * shuffle stays inside a block and its `matched` is each cell against the
 * OTHER cells in the same hours. This adds what the page needs and Advice
 * does not keep: the per-offer differences behind `matched` (recomputed by
 * the same rule, and held equal to Advice's figure by the suite), a bootstrap
 * interval on the median and on the score, the share the rig said take, and
 * the cells under the floor by name.
 *
 * The score is computed in every view, a picked block included: there it is
 * each cell against the other cells in that one block, which is the median
 * shifted, and the test is the plain one — nothing is left to hold still,
 * and the page says so. */
function cells(rows, key, opts) {
  opts = opts || {};
  var floor = typeof opts.minN === 'number' ? opts.minN : MIN_N;
  var days = typeof opts.minOutings === 'number' ? opts.minOutings : MIN_OUTINGS;
  var shuffles = opts.shuffles || SHUFFLES;
  var pool = (rows || []).filter(counted);
  var held = A.areas(pool, { key: key, floor: floor, days: days, shuffles: shuffles,
                             strata: opts.hold ? stratum : null });
  var raw = opts.hold ? A.areas(pool, { key: key, floor: floor, days: days, shuffles: shuffles })
                      : held;

  var all = Object.create(null);
  pool.forEach(function (o) {
    var k = key(o);
    if (k) (all[k] = all[k] || []).push(o);
  });
  var keptNames = Object.create(null);
  held.groups.forEach(function (g) { keptNames[g.name] = true; });
  var thin = Object.keys(all).filter(function (k) { return !keptNames[k]; }).map(function (k) {
    return { name: k, n: all[k].length, outings: A.outingsIn(all[k]) };
  }).sort(function (a, b) { return b.n - a.n || (a.name < b.name ? -1 : 1); });

  // What the other ranked cells paid in each block (Advice.areas' baseFor).
  var inBlock = Object.create(null);
  held.groups.forEach(function (g) {
    g.offers.forEach(function (o) {
      var b = String(stratum(o));
      (inBlock[b] = inBlock[b] || []).push({ g: g.name, v: o.perHour });
    });
  });
  var memo = Object.create(null);
  function base(b, name) {
    var k = b + '\u0000' + name;
    if (!(k in memo)) {
      var others = (inBlock[b] || []).filter(function (x) { return x.g !== name; })
                                       .map(function (x) { return x.v; });
      memo[k] = others.length ? MV.median(others) : null;
    }
    return memo[k];
  }

  var significant = typeof held.p === 'number' && held.p < ALPHA;
  var kept = Object.create(null);
  var groups = held.groups.map(function (g) {
    var vals = g.offers.map(function (o) { return o.perHour; });
    var diffs = [];
    g.offers.forEach(function (o) {
      var b = base(String(stratum(o)), g.name);
      if (b !== null) diffs.push(o.perHour - b);
    });
    var pays = g.offers.filter(function (o) { return typeof o.pay === 'number' && isFinite(o.pay); })
                       .map(function (o) { return o.pay; });
    var said = g.offers.filter(function (o) { return typeof o.state === 'string' && o.state; });
    if (opts.keepDiffs) {
      kept[g.name] = [];
      g.offers.forEach(function (o) {
        var b = base(String(stratum(o)), g.name);
        if (b !== null) kept[g.name].push({ at: o.at, d: o.perHour - b });
      });
    }
    var ppms = g.offers.map(payPerMile).filter(function (v) { return v !== null; });
    var top = topOf(g.offers, opts.tierOf);
    var score = diffs.length ? round2(MV.median(diffs)) : null;
    var sci = bootCI(diffs, seedOf('s' + g.name));
    var clear = sci ? (sci[0] > 0 ? 'above' : sci[1] < 0 ? 'below' : null) : null;
    return {
      name: g.name, n: g.n, outings: g.days,
      median: round2(g.median), ci: bootCI(vals, seedOf('m' + g.name)),
      score: score, sci: sci, compared: diffs.length,
      pay: pays.length ? round2(MV.median(pays)) : null,
      take: said.length ? round2(said.filter(function (o) { return o.state === 'go'; }).length
                                 / said.length) : null,
      // $/mi off the card, read and never ranked (see payPerMile).
      ppm: ppms.length ? round2(MV.median(ppms)) : null, ppmN: ppms.length,
      ppmCi: ppms.length >= DESC_MIN_N ? bootCI(ppms, seedOf('d' + g.name)) : null,
      clear: clear,
      beats: !!(significant && clear),
      matched: g.matched === undefined ? null : g.matched,
      p75: top.p75, p90: top.p90, p75Ci: top.p75Ci, p90Ci: top.p90Ci,
      top25: top.top25, top10: top.top10, tiered: top.tiered,
    };
  });
  groups.sort(function (a, b) {
    if (a.score === null) return b.score === null ? b.median - a.median : 1;
    if (b.score === null) return -1;
    return b.score - a.score || b.median - a.median;
  });
  return {
    p: typeof held.p === 'number' ? held.p : null, h: held.h === undefined ? null : held.h,
    rawP: typeof raw.p === 'number' ? raw.p : null,
    held: !!(opts.hold && held.matched),
    significant: significant,
    groups: groups, thin: thin, named: held.named, unnamed: held.unnamed, kept: held.kept,
    floor: floor, outings: days,
    diffs: opts.keepDiffs ? kept : undefined,
  };
}

/* --- what was placed, and what the unplaced paid -------------------------- */

function coverage(rows, placedRow) {
  var pool = rows.filter(counted);
  var withPickup = pool.filter(function (o) { return typeof o.pickup === 'string' && o.pickup.trim(); });
  function side(list) {
    return { n: list.length,
             perHour: list.length ? round2(MV.median(list.map(function (o) { return o.perHour; }))) : null,
             pay: list.length ? round2(MV.median(list.filter(function (o) {
               return typeof o.pay === 'number';
             }).map(function (o) { return o.pay; }))) : null };
  }
  function split(list) {
    var p = list.filter(function (o) { return placedRow(o).at; });
    var u = list.filter(function (o) { return !placedRow(o).at; });
    var out = { placed: side(p), unplaced: side(u), p: null };
    out.gapPerHour = out.placed.n && out.unplaced.n ? round2(out.placed.perHour - out.unplaced.perHour) : null;
    out.gapPay = out.placed.n && out.unplaced.n ? round2(out.placed.pay - out.unplaced.pay) : null;
    if (p.length && u.length) {
      // Two groups through the same test as the ranking: Kruskal-Wallis on
      // ranks, permuted, which with two groups is the rank-sum test.
      var t = A.areas(list, { key: function (o) { return placedRow(o).at ? 'placed' : 'unplaced'; },
                              floor: 1, days: 1, shuffles: SHUFFLES });
      out.p = typeof t.p === 'number' ? t.p : null;
    }
    return out;
  }
  var why = Object.create(null), kinds = Object.create(null), levels = Object.create(null);
  withPickup.forEach(function (o) {
    var r = placedRow(o);
    kinds[r.kind] = kinds[r.kind] || { n: 0, placed: 0 };
    kinds[r.kind].n += 1;
    if (r.at) {
      kinds[r.kind].placed += 1;
      var lv = r.level || (r.kind === 'name' ? 'name' : 'door');
      var e = levels[lv] || (levels[lv] = { level: lv, n: 0, rates: [], refused: Object.create(null), region: 0 });
      e.n += 1;
      e.rates.push(o.perHour);
      if (r.refused) {
        var rw = r.refusedSaid || WHY[r.refused] || r.refused;
        e.refused[rw] = (e.refused[rw] || 0) + 1;
      }
      if (r.region) e.region += 1;
      return;
    }
    var w = r.said || WHY[r.why] || r.why;
    why[w] = (why[w] || 0) + 1;
  });
  var byDay = Object.create(null);
  withPickup.forEach(function (o) {
    var d = outingOf(o.at);
    if (d) (byDay[d] = byDay[d] || []).push(o);
  });
  return {
    offers: pool.length, noPickup: pool.length - withPickup.length,
    all: split(withPickup),
    why: Object.keys(why).map(function (k) { return { why: k, n: why[k] }; })
      .sort(function (a, b) { return b.n - a.n; }),
    kinds: kinds,
    // Placed, by level (POINT_LEVELS then APPROX_LEVELS): how many, their
    // median $/hr, the refusal an approximate one stood in for, and how many
    // were found in the region box (a card with no fix).
    levels: POINT_LEVELS.concat(APPROX_LEVELS).filter(function (l) { return levels[l]; }).map(function (l) {
      var e = levels[l];
      return { level: l, point: POINT_LEVELS.indexOf(l) >= 0, n: e.n, perHour: med(e.rates), region: e.region,
               refused: Object.keys(e.refused).map(function (k) { return k + ' ' + e.refused[k]; }).join(' · ') };
    }),
    points: split(withPickup.filter(function (o) { return !placedRow(o).at || isPoint(placedRow(o)); })),
    days: Object.keys(byDay).sort().map(function (d) {
      var s = split(byDay[d]);
      s.day = d;
      return s;
    }),
  };
}

/* --- where trips leave you -----------------------------------------------
 *
 * For each order taken and put down at the door: the first offer after the
 * drop that the rig said take (`go`, on a row the rig stands behind), how
 * long it took to come and what it paid. The offers are walked from the
 * drop; a silence longer than NEXT_GAP_MIN before one arrives is the driver
 * stopping, and that wait is counted as ended unmeasured, not as a long one. */
function nextTake(timeline, endedAt) {
  var last = endedAt, gap = NEXT_GAP_MIN * 60000;
  for (var i = 0; i < timeline.length; i++) {
    var t = timeline[i];
    if (t.at <= endedAt) continue;
    if (t.at - last > gap) return { censored: true };
    if (t.go) return { censored: false, wait: (t.at - endedAt) / 60000, perHour: t.perHour, pay: t.pay };
    last = t.at;
  }
  return { censored: true };
}

function timelineOf(offers) {
  return offers.filter(function (o) { return typeof seenAt(o) === 'number'; }).map(function (o) {
    return { at: seenAt(o), go: counted(o) && o.state === 'go', counted: counted(o), perHour: o.perHour, pay: o.pay, o: o };
  }).sort(function (a, b) { return a.at - b.at; });
}

/* The trips, each as { at, town, cell, how, next } — no door, no text. */
function tripsOf(offers, taken, dropAt) {
  var byId = Object.create(null);
  offers.forEach(function (o) { if (o && typeof o.id === 'string') byId[o.id] = o; });
  var line = timelineOf(offers);
  var out = [];
  (taken || []).forEach(function (t) {
    if (AT_THE_DOOR.indexOf(t.by || 'drop') < 0 || typeof t.endedAt !== 'number') return;
    var o = byId[t.id];
    if (!o) return;
    var pos = dropAt(t, o);
    var cell = pos ? cellOf(pos.at) : null;
    out.push({ at: t.endedAt, town: MV.townOf(o.dropoff, A.area), cell: cell ? cell.id : null,
               cellBox: cell, how: pos ? pos.how : null, next: nextTake(line, t.endedAt),
               // ...the next offer of any kind (nextOffer), and where the car
               // was, for the empty-driving table; neither is written out.
               nextAny: nextOffer(line, t.endedAt), pos: pos ? pos.at : null,
               // The offer it was taken on, for the per-store tables; never
               // written out (the report keeps the trips' counts only).
               offer: o });
  });
  return out;
}

function dropTable(trips, keyName, hold) {
  // Wait minutes through the same ranking machinery, as a row's `perHour`:
  // a pseudo-row is trustworthy by construction (no flags), and its `at` is
  // the drop, so the block it is held in is the hour the trip ended.
  var rows = trips.filter(function (t) { return t[keyName] && !t.next.censored; }).map(function (t) {
    return { perHour: t.next.wait, at: t.at, area: t[keyName] };
  });
  var res = cells(rows, function (r) { return r.area; },
                  { minN: DROP_MIN_N, minOutings: MIN_OUTINGS, hold: hold });
  var by = Object.create(null);
  trips.forEach(function (t) {
    if (t[keyName]) (by[t[keyName]] = by[t[keyName]] || []).push(t);
  });
  res.groups.forEach(function (g) {
    var list = by[g.name] || [];
    var got = list.filter(function (t) { return !t.next.censored; });
    g.trips = list.length;
    g.ended = list.length - got.length;
    g.nextPerHour = got.length ? round2(MV.median(got.map(function (t) { return t.next.perHour; }))) : null;
    g.nextPay = got.length ? round2(MV.median(got.map(function (t) { return t.next.pay; }))) : null;
    var any = list.filter(function (t) { return t.nextAny && !t.nextAny.censored; });
    g.anyN = any.length;
    g.anyMin = any.length ? round2(MV.median(any.map(function (t) { return t.nextAny.wait; }))) : null;
    g.anyPerHour = any.length ? round2(MV.median(any.map(function (t) { return t.nextAny.perHour; }))) : null;
    g.anyGood = any.length ? share(any.filter(function (t) { return t.nextAny.good; }).length, any.length) : null;
    // Lower is better for a wait: the sign of `clear` says which way.
    if (keyName === 'cell') {
      var c = list[0] && list[0].cellBox;
      if (c) g.box = c;
    }
  });
  // A 2-mile cell under the floor is a handful of customers' homes: not named.
  if (keyName === 'cell') {
    res.thinCount = res.thin.length;
    res.thinTrips = res.thin.reduce(function (s, t) { return s + t.n; }, 0);
    res.thin = [];
  }
  return res;
}

/* --- where you waited: the car's own fix when each card came up -----------
 *
 * Nov 2026, the Trends round. The heat-map entry (AUDITS.md) wrote: "The
 * pickup is where the job STARTS, not where the driver WAS when the card
 * arrived ... with no row carrying a position the second is not knowable at
 * all", and every table above ranks pickups for that reason. Since the USB
 * receiver every offer row carries the car's own fix (journal.py fix_fields,
 * the gate's `gpsOk`), so where the car WAS is now on the record, and this
 * groups the offers by it: by the 2-mile cell the car was in and by that
 * cell's town (the NucBox map's name for the cell's centre, as the Busy tab
 * names its spells). Only a fix the gate passed (MV.fixOf), and only cards
 * that came with no taken order in the car — an offer read on the way to a
 * door says where the job took the car, not where the driver chose to wait.
 *
 * What it can say now: "offers that came while you were here paid this,
 * against the same hours elsewhere", ranked by the same test and colour rule
 * as every ranked table (cells: Advice.areas, shuffles within three-hour
 * blocks, 30 offers on 2 shift days, colour only where the grouping beats
 * chance AND the cell's interval clears zero). What still limits it, and why
 * it is not "where to wait":
 *   - Offers are dispatched NEAR the car, so a place only ever competes with
 *     places the driver already waits in; a cell never waited in has no row.
 *   - A good area may be good because of where its trips go, not where the
 *     wait was; this table cannot tell those apart.
 *   - The hours there are inferred, not measured: each card's time to the
 *     next card (at most CREDIT_MAX_MIN, chosen: a gap longer than that is
 *     the car moving or the phone down, not the wait) credited to where the
 *     car was at the earlier card. The Busy tab's spells, off the GPS log,
 *     are the measured version where --gps is given.
 *   - Takes the driver never pressed Took on leave their drive in as waiting.
 *   - Minutes to the first card at target start at the first CARD seen in
 *     an area, not at arrival (arrival is not on the record without the
 *     log), so a stay whose first card was at target reads 0.
 * "At target" here is the row's own target at the time (perHour >= target),
 * and said so on the page (the reporting review's F8): it is NOT the
 * offers page's Trends ruler nor When & where's "good", which are one
 * dollar cut, the top X% of the whole range — this comment once called it
 * the Trends tab's word, from before Trends moved to its ruler, and the
 * columns said "first good", which on this report means the other thing.
 * "Rig said take" elsewhere is the verdict. */
var CREDIT_MAX_MIN = 10;

function goodOf(o) {
  return counted(o) && typeof o.target === 'number' && isFinite(o.target) && o.perHour >= o.target;
}

function inAny(spans, at) {
  for (var i = 0; i < spans.length; i++) if (at >= spans[i][0] && at <= spans[i][1]) return true;
  return false;
}

/* The cards seen with no taken order in the car, oldest first, each with the
 * car's fix, its 2-mile cell and that cell's town, and its credited minutes
 * (to the next card, at most CREDIT_MAX_MIN; none across a silence longer
 * than NEXT_GAP_MIN, the rig's own break). */
function waitingLine(offers, taken, cellTown, cellBoxes) {
  var held = heldOf(taken);
  var line = timelineOf(offers).filter(function (t) { return t.counted && !inAny(held, t.at); });
  return line.map(function (t, i) {
    var fix = MV.fixOf(t.o);
    var c = fix ? cellOf(fix) : null;
    if (c && cellBoxes) cellBoxes[c.id] = c;
    var next = line[i + 1];
    var gap = next ? (next.at - t.at) / 60000 : null;
    return { at: t.at, o: t.o, fix: fix, cell: c ? c.id : null,
             town: c && cellTown ? cellTown[c.id] || null : null,
             credit: gap !== null && gap <= NEXT_GAP_MIN ? Math.min(gap, CREDIT_MAX_MIN) : 0,
             brk: gap === null || gap > NEXT_GAP_MIN, good: goodOf(t.o) };
  });
}

/* Per area and three-hour block: the cards, the hours credited there, cards
 * per hour, median $/hr, the share that cleared the target, and the stays —
 * consecutive cards in one area with no break — with the minutes from a
 * stay's first card to its first good one. Figures at DESC_MIN_N cards on
 * MIN_OUTINGS shift days; under that the n only. */
function waitedTable(line, keyName, label, what) {
  var stays = [];
  var cur = null;
  line.forEach(function (w) {
    var k = w[keyName];
    if (!cur || cur.key !== k || cur.closed) {
      cur = k ? { key: k, from: w.at, firstGood: null, closed: false } : null;
      if (cur) stays.push(cur);
    }
    if (cur && w.good && cur.firstGood === null) cur.firstGood = (w.at - cur.from) / 60000;
    if (cur && w.brk) cur.closed = true;
  });
  var by = groupBy(line.filter(function (w) { return w[keyName]; }),
                   function (w) { return w[keyName] + '\u0000' + A.blockOf(w.at); });
  var sBy = groupBy(stays, function (s) { return s.key + '\u0000' + A.blockOf(s.from); });
  var out = Object.keys(by).map(function (k) {
    var list = by[k], parts = k.split('\u0000');
    var days = A.outingsIn(list.map(function (w) { return w.o; }));
    var hours = list.reduce(function (a, w) { return a + w.credit / 60; }, 0);
    var ok = list.length >= DESC_MIN_N && days >= MIN_OUTINGS;
    var rates = list.map(function (w) { return w.o.perHour; });
    var ss = sBy[k] || [], got = ss.filter(function (s) { return s.firstGood !== null; })
      .map(function (s) { return s.firstGood; });
    return { name: label(parts[0]), block: A.BLOCK_NAMES[Number(parts[1])], blockN: Number(parts[1]),
             n: list.length, days: days, hours: Math.round(hours * 10) / 10,
             perHour: ok && hours > 0 ? round2(list.length / hours) : null,
             median: ok ? med(rates) : null, medianCi: ok ? medCi(rates, 'w' + k) : null,
             good: ok ? share(list.filter(function (w) { return w.good; }).length, list.length) : null,
             stays: ss.length, staysGood: ok ? share(got.length, ss.length) : null,
             toGood: ok && got.length ? med(got) : null };
  }).sort(function (a, b) { return (a.name < b.name ? -1 : a.name > b.name ? 1 : 0) || a.blockN - b.blockN; });
  out.forEach(function (r) { delete r.blockN; });
  return { cols: [C('name', what, 't'), C('block', 'hours', 't'), C('n', 'offers', 'n'), C('days', 'days', 'n'),
                  C('hours', 'hours there (inferred)', 'h'), C('perHour', 'offers / hr there', 'r'),
                  C('median', 'median $/hr', '$'), C('medianCi', '95%', '$ci'), C('good', 'cleared target', '%'),
                  C('stays', 'stays', 'n'), C('staysGood', 'stays with a card at target', '%'),
                  C('toGood', 'min to first card at target (from first card)', 'min')], rows: out };
}

/* --- when & where: which area, at the weekday and hours picked -----------
 *
 * The owner is a selective driver and wants to know which areas pay at a
 * given time. Twenty-odd tabs each answered one slice of "where" and none
 * answered the question he asks in the car park: on Friday 8-11pm, which
 * area gives me the most good offers per hour I wait there? This does, and
 * builds nothing new to find an area: it reads the Waited tab's own line
 * (waitingLine — the cards that came with no taken order in the car, each at
 * the car's own gated fix, its 2-mile cell and that cell's town, and its
 * credited minutes), so the hours, the area and the "no order in the car"
 * rule are that tab's, word for word. Never a pin, never DoorDash's map
 * label (approximate drawing only, Settled): the car's own fix or nothing.
 *
 * THE SLOT. The driver's weekday, on the report's 4am day (A.DAY_STARTS_AT,
 * outingOf's): 1am on a Saturday is Friday night. Crossed with six blocks,
 * not advice.js's eight three-hour ones, for two reasons. advice.js cuts at
 * midnight and 3am, through the middle of a night shift, while this driver's
 * day runs to 4am, so its last block (11pm-4am) keeps a late night whole and
 * inside the shift day it belongs to. And seven days by eight blocks is 56
 * slots to spread a part-time driver's months over before an area is even
 * asked, where a floor of two shift days per area per slot (below) is what
 * stands between a figure and one evening; six blocks shaped round the
 * day's demand — the breakfast hours (long, because little is driven
 * then), lunch 10-2, the afternoon trough 2-5, dinner 5-8, the late evening
 * 8-11 and the night past it — put each line where demand turns, so one slot
 * is roughly one kind of hour. Chosen, not measured.
 *
 * NOT the Settled weekday term. AUDITS.md refused a weekday term in the
 * RIG MAP's time filter because on one week every weekday x block cell came
 * off one calendar date. Here no area is ranked in a slot it was waited in
 * on fewer than WW_MIN_DAYS separate shift days, which is that entry's fault
 * refused by rule rather than by leaving the question out; Weekdays,
 * Weekends and Any day pool the slot when one weekday is too thin. And it is
 * read only: no target, verdict or panel reads it, and the accept line is
 * not tuned to an hour or a weekday by anything here.
 *
 * GOOD. The card's $/hr in the top WW_TOP% of EVERY counted offer in the
 * report's range (waiting or not): one dollar cutoff per choice, worked out
 * once over the whole range and printed, then held fixed across slots and
 * areas — so "good" on Friday night means the same dollars as on Tuesday
 * morning, and a slot that is poor overall reads poor rather than being
 * graded on its own curve (that is what the Best tab's per-block tiers do,
 * for a different question). 10/20/30/50% to pick from, 20 by default.
 *
 * THE RANKING. Good offers per hour waited there (the credited hours), with
 * the exact (Garwood) 99% Poisson interval on the count over those hours,
 * WIDENED BY PHI (the reporting review's S2): a plain Poisson interval
 * marked 4.5-12.6% of no-effect areas once the nights swing 40%, as the
 * Trends grid's did before it was widened. phi is trends.js `dispersion`
 * over each area's shift days within each weekday x block (Pearson's
 * chi-square of the days' good counts against the area's own rate, pooled
 * over every area, never under 1), one per town or cell and per top; the
 * interval is on k/phi, scaled back (trends.js `rateShade`). The hour
 * strip's lines take one phi over every weekday x hour's days. Simulated
 * in the AUDITS entry: about 1% at every row. An area is marked only where
 * that interval sits wholly above or wholly below the slot's own overall rate — every waiting card in the slot,
 * placed or not; otherwise it is printed without colour, as every
 * descriptive table here is. 99%, not 95%: the driver flicks through up to
 * seventy slots of up to dozens of areas, and at 95% one in twenty would be
 * marked by chance in each (trends.js measured the same for its grid: 4% at
 * 95%, under 1% at 99%). The interval takes the inferred hours as exact and
 * the cards as independent, and neither is quite true (a stay's cards come
 * from one dispatch neighbourhood), which is one more reason for the wider
 * one.
 *
 * THE FLOOR. WW_MIN_HOURS hours waited in the slot on WW_MIN_DAYS shift days.
 * Two days is the report's own rule (MIN_OUTINGS: thirty offers from one
 * evening are one evening). Two hours because a card's credit is capped at
 * CREDIT_MAX_MIN, so two hours is a dozen card gaps at the very least, and
 * below it a rate is one stay's luck; the 99% interval, not the floor, is
 * what keeps a thin rate from being marked. Chosen, not measured. Under the
 * floor an area is listed as "too little time there yet" with its hours.
 *
 * OFFERED, NOT EARNED, as the Waited tab says: offers are dispatched near
 * the car, so only places already waited in compete, and a good offer seen
 * is not one taken. */
var WW_BLOCKS = [[0, 6, '4–10am'], [6, 10, '10am–2pm'], [10, 13, '2–5pm'], [13, 16, '5–8pm'],
                 [16, 19, '8–11pm'], [19, 24, '11pm–4am']];   // hours after the day's 4am start
var WW_DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
// The picker's choices, Monday first; Weekends are the driver's Saturday and
// Sunday, strategy.js's weekOf.
var WW_DAY_OPTS = ['any', 'wkday', 'wkend', '1', '2', '3', '4', '5', '6', '0'];
var WW_BLOCK_OPTS = ['any', '0', '1', '2', '3', '4', '5'];
/* ...and single clock hours, the owner's follow-up (18 Nov 2026): 'h0' is
 * the 4am hour, 'h23' the 3am one, in the driver day's order. The same
 * cutoff, interval, marking and floor as a block. Most areas will sit under
 * the floor in one hour, which is the floor doing its job; the slot's own
 * line (every area together) usually clears it, and it is that line the
 * hour strip draws. A card's credit counts in the hour its card came up in,
 * though up to CREDIT_MAX_MIN of it may run into the next. */
var WW_HOUR_OPTS = [];
for (var wwh = 0; wwh < 24; wwh++) WW_HOUR_OPTS.push('h' + wwh);
var WW_TOPS = [10, 20, 30, 50];
var WW_TOP = 20;
var WW_MIN_HOURS = 2;
var WW_MIN_DAYS = MIN_OUTINGS;
var WW_CONF = 0.99;

// The driver's weekday (0 Sunday), WW_BLOCKS index and hour of the driver
// day (0 the 4am hour, 23 the 3am one) of a stamp, or null.
// The HOUR off the real clock, the day off the driver-day shift (the
// reporting review's F7): shifting the moment back four hours and reading
// the hour off that put 5:30am on the spring-forward Sunday in the 1am hour
// and 6:30 and 7:30 both in the 3am one, while Trends put them at 5, 6 and
// 7. The clock hour, less four, wraps the same way on every other day.
function wwSlotOf(at) {
  var d = new Date(at);
  if (!isFinite(d.getTime())) return null;
  var h = (d.getHours() - A.DAY_STARTS_AT + 24) % 24;
  d.setHours(d.getHours() - A.DAY_STARTS_AT);
  for (var i = 0; i < WW_BLOCKS.length; i++) {
    if (h >= WW_BLOCKS[i][0] && h < WW_BLOCKS[i][1]) return { day: d.getDay(), block: i, hour: h };
  }
  return null;
}

// '4–5am', '11am–12pm', '11pm–12am' for the driver day's hour i (0 = 4am).
function wwHourName(i) {
  var c = (i + A.DAY_STARTS_AT) % 24, n = (c + 1) % 24;
  function hr(x) { return x % 12 || 12; }
  function ap(x) { return x < 12 ? 'am' : 'pm'; }
  return hr(c) + (ap(c) === ap(n) ? '' : ap(c)) + '–' + hr(n) + ap(n);
}

function wwDayIn(opt, day) {
  if (opt === 'any') return true;
  if (opt === 'wkday') return day >= 1 && day <= 5;
  if (opt === 'wkend') return day === 0 || day === 6;
  return Number(opt) === day;
}

/* The exact (Garwood) interval on a Poisson mean from k events: the means at
 * which k or more, and k or fewer, are each (1 - conf) / 2 likely. trends.js
 * `poisCI`, the one copy, by its regularised gamma. This file had its own,
 * a sum over whole terms, and wideCI hands it k / phi, which is rarely whole:
 * the sum ran to floor(k), so 6.67 good drew the interval of 6 (1.54-15.66
 * where the exact one is 1.87-16.65) and the marks leaned towards "below". */
function poissonCI(k, conf) { return TR.poisCI(k, 1 - conf); }

/* The tab's table: every (day choice, block choice) with any waiting in it,
 * keyed 'day|block', each with the slot's overall line and, by town and by
 * 2-mile cell, the areas over the floor (ranked, with the four tops' rates,
 * intervals and marks) and those under it (hours, offers, days only). Areas
 * are keyed as the Waited tab keys them — a town's name, a cell's id (named
 * on the page through R.cells, as every cell is) — so it holds no name and
 * no coordinate the report does not already. Worked out here, once; the page
 * only picks a slot and sorts. */
/* The report's rulers, worked out ONCE (the reporting review's F4): the top
 * 10/20/30/50% of every counted offer's $/hr in the range, as dollar cuts,
 * each with how many offers it is over and how many sit at or over it. When
 * & where reads them and the Strategy tab's section 7 is handed them, so
 * the two never draw two lines over one report: they did — section 7 had
 * T.ruler over its own rated offers (a card with no perHour rated off pay
 * and minutes), and on one invented report put "good" at $36.60 over 90
 * offers while When & where put it at $39.60 over 60. Ties at a cut count
 * as good, as trends.js `ruler` documents. */
function reportRulers(offers) {
  var rates = offers.filter(counted).map(function (o) { return o.perHour; });
  var out = { tops: WW_TOPS, n: rates.length, days: A.outingsIn(offers.filter(counted)), byTop: {} };
  out.cuts = WW_TOPS.map(function (p) {
    var c = rates.length ? round2(quantile(rates, 1 - p / 100)) : null;
    out.byTop[p] = { cut: c, n: rates.length, days: out.days,
                     over: c === null ? 0 : rates.filter(function (v) { return v >= c; }).length };
    return c;
  });
  return out;
}

function whenWhere(offers, waiting, rulers) {
  var ru = rulers || reportRulers(offers);
  var rates = { length: ru.n };
  var cuts = ru.cuts;
  var memo = Object.create(null);
  function ci(k) { return memo[k] || (memo[k] = poissonCI(k, WW_CONF)); }
  var line = (waiting || []).map(function (w) {
    var s = wwSlotOf(w.at);
    if (!s) return null;
    var r = w.o.perHour;
    return { day: s.day, block: s.block, hour: s.hour, outing: outingOf(w.at), mins: w.credit, rate: r,
             good: cuts.map(function (c) { return c !== null && r >= c; }), app: appOf(w.o),
             town: w.town || null, cell: w.cell || null };
  }).filter(Boolean);
  function sum(list) {
    // Minutes summed, then hours: a card's credit is whole minutes more often
    // than not, and twenty-four twelfths of an hour summed in hours come to
    // 1.9999999999999996, which a two-hour floor refuses.
    var days = Object.create(null), mins = 0, u = 0, dd = 0, g = WW_TOPS.map(function () { return 0; });
    list.forEach(function (c) {
      days[c.outing] = true;
      mins += c.mins;
      if (c.app === 'uber') u += 1; else if (c.app === 'doordash') dd += 1;
      c.good.forEach(function (x, i) { if (x) g[i] += 1; });
    });
    var v = list.map(function (c) { return c.rate; });
    return { h: mins / 60, n: list.length, d: Object.keys(days).length, g: g, u: u, dd: dd,
             p50: v.length ? round2(quantile(v, 0.5)) : null, p90: v.length ? round2(quantile(v, 0.9)) : null };
  }
  // phi for each kind of line, per top: `key` puts a card in a group (an
  // area in a weekday x block, or a weekday x hour), each group's members
  // its shift days. Disjoint groups, so no card is counted twice.
  function phiOf(key) {
    var groups = Object.create(null);
    line.forEach(function (c) {
      var g = key(c);
      if (g === null) return;
      var gr = groups[g] || (groups[g] = Object.create(null));
      var m = gr[c.outing] || (gr[c.outing] = { mins: 0, g: WW_TOPS.map(function () { return 0; }) });
      m.mins += c.mins;
      c.good.forEach(function (x, i) { if (x) m.g[i] += 1; });
    });
    return WW_TOPS.map(function (t, i) {
      return TR.dispersion(Object.keys(groups).map(function (g) {
        return Object.keys(groups[g]).map(function (o) { return { k: groups[g][o].g[i], h: groups[g][o].mins / 60 }; });
      }));
    });
  }
  var phi = { town: phiOf(function (c) { return c.town ? c.day + '|' + c.block + '|' + c.town : null; }),
              cell: phiOf(function (c) { return c.cell ? c.day + '|' + c.block + '|' + c.cell : null; }),
              line: phiOf(function (c) { return c.day + '|' + c.hour; }) };
  function rated(s, ph) {
    s.r = s.g.map(function (k) { return s.h > 0 ? round2(k / s.h) : null; });
    var b = s.g.map(function (k, i) { return wideCI(k, s.h, ph[i]); });
    s.lo = b.map(function (x) { return x ? round2(x[0]) : null; });
    s.hi = b.map(function (x) { return x ? round2(x[1]) : null; });
    return s;
  }
  // The Garwood interval on k/phi, scaled back by phi, per hour.
  function wideCI(k, h, f) {
    if (!(h > 0)) return null;
    f = f > 1 ? f : 1;
    var b = f === 1 ? ci(k) : poissonCI(k / f, WW_CONF);
    return [b[0] * f / h, b[1] * f / h];
  }
  // Every slot together: what the hour strip marks each hour's line against.
  var every = sum(line);
  var everyBase = every.g.map(function (k) { return every.h > 0 ? k / every.h : null; });
  function marks(s, against, ph) {
    return s.g.map(function (k, i) {
      if (against[i] === null || !(s.h > 0)) return null;
      var b = wideCI(k, s.h, ph[i]);
      return b[0] > against[i] ? 'above' : b[1] < against[i] ? 'below' : null;
    });
  }
  // The cards bucketed once by weekday and hour of the driver day (the
  // reporting review's R4): 310 slots each filtered the whole line before,
  // 3.3 s of a 3x record's run; each slot now joins its buckets.
  var bucket = [];
  for (var bd = 0; bd < 7; bd++) { bucket.push([]); for (var bh = 0; bh < 24; bh++) bucket[bd].push([]); }
  line.forEach(function (c) { bucket[c.day][c.hour].push(c); });
  function hoursOf(opt) {
    var out = [];
    if (opt === 'any') { for (var x = 0; x < 24; x++) out.push(x); return out; }
    if (opt[0] === 'h') return [Number(opt.slice(1))];
    var b = WW_BLOCKS[Number(opt)];
    for (var y = b[0]; y < b[1]; y++) out.push(y);
    return out;
  }
  var slots = {};
  WW_DAY_OPTS.forEach(function (dOpt) {
    WW_BLOCK_OPTS.concat(WW_HOUR_OPTS).forEach(function (bOpt) {
      var inSlot = [], hrs = hoursOf(bOpt);
      for (var dd = 0; dd < 7; dd++) {
        if (!wwDayIn(dOpt, dd)) continue;
        hrs.forEach(function (hh) { var b = bucket[dd][hh]; for (var j = 0; j < b.length; j++) inSlot.push(b[j]); });
      }
      if (!inSlot.length) return;
      var all = rated(sum(inSlot), phi.line);
      var base = all.g.map(function (k) { return all.h > 0 ? k / all.h : null; });
      // The slot's own line held to the same floor, and marked by the same
      // rule against every slot together (the hour strip's colour).
      all.ok = all.h >= WW_MIN_HOURS && all.d >= WW_MIN_DAYS;
      all.mk = all.ok ? marks(all, everyBase, phi.line) : null;
      var out = { all: all };
      ['town', 'cell'].forEach(function (unit) {
        var by = groupBy(inSlot.filter(function (c) { return c[unit]; }), function (c) { return c[unit]; });
        var ranked = [], thin = [];
        Object.keys(by).forEach(function (a) {
          var s = sum(by[a]);
          s.a = a;
          if (s.h >= WW_MIN_HOURS && s.d >= WW_MIN_DAYS) {
            rated(s, phi[unit]);
            // Marked on the unrounded figures: wholly above or below the slot.
            s.mk = marks(s, base, phi[unit]);
            ranked.push(s);
          } else {
            thin.push({ a: a, h: s.h, n: s.n, d: s.d });
          }
        });
        var ti = WW_TOPS.indexOf(WW_TOP);
        ranked.sort(function (x, y) { return y.r[ti] - x.r[ti] || y.h - x.h || (x.a < y.a ? -1 : 1); });
        thin.sort(function (x, y) { return y.h - x.h || (x.a < y.a ? -1 : 1); });
        out[unit] = { ranked: ranked, thin: thin };
      });
      // Hours to the hundredth on the page's copy: the rates above were
      // worked out on the whole figure.
      [all].concat(out.town.ranked, out.town.thin, out.cell.ranked, out.cell.thin).forEach(function (s) {
        s.h = round2(s.h);
      });
      slots[dOpt + '|' + bOpt] = out;
    });
  });
  /* THE HOURS, TRIMMED. Every hour of every day choice with every area in it
   * took the table from 98 kB to 234 kB on an invented 5,257-offer, 44-day
   * record, more than double. So at hour level an area is kept only if it
   * clears the floor in at least one hour of the same day choice (the
   * strip's day: Fridays for a Friday hour, every day for an Any-day one);
   * the slot's own line is always kept, whole, and the page says how many
   * were left out. The blocks keep every area. Measured on that record: kept
   * if it cleared the floor in any hour of any day choice, 231 kB; of the
   * same day choice, 223 kB, 252 of 827 hour-level "too little time" rows
   * gone. It stays over double because the rows that remain are the ranked
   * ones, each with four tops' rates, intervals and marks, and those are the
   * hour view's answer. */
  ['town', 'cell'].forEach(function (unit) {
    var keep = Object.create(null);
    Object.keys(slots).forEach(function (k) {
      var p = k.split('|');
      if (p[1][0] !== 'h') return;
      slots[k][unit].ranked.forEach(function (s0) { keep[p[0] + '|' + s0.a] = true; });
    });
    Object.keys(slots).forEach(function (k) {
      var p = k.split('|');
      if (p[1][0] !== 'h') return;
      var u = slots[k][unit], before = u.thin.length;
      u.thin = u.thin.filter(function (t) { return keep[p[0] + '|' + t.a]; });
      if (before > u.thin.length) u.left = before - u.thin.length;
    });
  });
  return { blocks: WW_BLOCKS.map(function (b) { return b[2]; }), days: WW_DAYS, dayOpts: WW_DAY_OPTS,
           blockOpts: WW_BLOCK_OPTS, hourOpts: WW_HOUR_OPTS, hours: WW_HOUR_OPTS.map(function (o, i) { return wwHourName(i); }),
           tops: WW_TOPS, top: WW_TOP, cuts: cuts, offers: rates.length,
           phi: { town: phi.town.map(round2), cell: phi.cell.map(round2), line: phi.line.map(round2) },
           cards: line.length, minHours: WW_MIN_HOURS, minDays: WW_MIN_DAYS, conf: WW_CONF, slots: slots };
}

/* --- offers around you: where the car was when each offer came up ---------
 *
 * The owner (Nov 2026): "I am also very curious what the relationship
 * between my GPS location and the offers observed looks like." The Waited
 * and When & where tabs answer it as tables of areas; this draws it: the
 * car's own gated fix on every card that came with no order in the car (the
 * Waited tab's line, waitingLine, word for word), one dot per offer,
 * coloured good or not against the fixed ruler — When & where's cutoffs,
 * the top 10/20/30/50% of every counted offer in the range, worked out once
 * and held across every slot — with that tab's Day and Hours pickers. Never
 * a pin, never DoorDash's map label (approximate drawing only, Settled):
 * the car's own fix or nothing. Read only: no verdict, target, panel or
 * accept line reads it, and it is on the NucBox's report, never the rig.
 *
 * WHY DOTS AND NOT A COLOURED GRID. A grid coloured by its share of good
 * offers is the heat map AUDITS.md refuted: a fixed band edge read off a
 * dozen offers takes the wrong colour a fifth of the time with no effect at
 * all. A dot is one offer and its colour is that offer's own fact (its $/hr
 * against one dollar cutoff), so no estimate is coloured and none can be
 * miscoloured; the eye does the pooling and the rings chart below says
 * what the pooling is worth, with its interval. Dense places are handled by
 * position, not by a bin colour: each dot is drawn at its quarter-mile
 * bin's centre, spread on a sunflower inside the bin, so a busy car park
 * reads as a disc of dots whose mix of colours is the mix of offers.
 *
 * WHY QUARTER-MILE BINS, AND ONLY ON TWO SHIFT DAYS. A raw fix to six
 * places is a door: a card that came just after a drop puts the car at a
 * customer's house, and the report writes no dropoff's position anywhere.
 * So a dot carries only its bin (AROUND_BIN_MI, about 400 m a side, a few
 * dozen houses in a suburb), and a bin is drawn only where the car was seen
 * there on AROUND_BIN_DAYS separate shift days (the report's own two-day
 * rule): a place waited in again, not a door passed once. The cards that
 * fall in a one-day bin are counted on the page, never drawn.
 *
 * GOING ONLINE AT HOME NEVER DRAWS HOME. Two rules, both chosen, not
 * measured (homeOf):
 *   - each driver day's STARTING STAY: every card before the car's fix
 *     first lies more than HOME_MI from that day's first fix. Whatever the
 *     day began at is left out until the car has left it;
 *   - a USUAL START: a day's first fix within HOME_MI of another day's
 *     first fix. Every card within HOME_MI of a usual start is left out, on
 *     any day, so a break at home mid-shift is not drawn either.
 * HOME_MI is 0.3 mi, the report's own PLACE_APPROX_MI (candidates that
 * close are one place): about six times the GPS gate's worst error (50 m),
 * so parking on the other side of the street is still home, and small
 * enough that a restaurant row a street over survives. The cost is real
 * and said on the page: a day begun at a restaurant cluster loses that
 * first stay, and a usual start that is a car park, not a house, is never
 * drawn. The counts left out are on the page. The When & where, Waited and
 * Busy tables do not apply this yet (AUDITS.md, Open).
 *
 * THE CHARTS BESIDE IT need no map: (a) the share of offers that were good
 * by distance from the driver's most-used waiting area — the 2-mile cell
 * with the most credited waiting hours among the dots drawn (so never the
 * home cell), rings of AROUND_RING_MI from its centre, a Wilson interval on
 * each share, figures at DESC_MIN_N offers; (b) good offers per hour waited
 * by area for the slot picked, which is When & where's own slot table
 * (R.whenwhere.slots), drawn and not worked out again; (c) the share good
 * by the card's own drive to the pickup (toPickupMiles: the approach leg
 * offer-parser.js splits off where the card prints it, mostly Uber's "x min
 * (y mi) away"), every counted offer, no GPS needed. All three are
 * descriptive: no test ranks them and no rule is drawn from them — no $/mi
 * or distance rule, no floor.
 *
 * The data are columns, the dots' bin, rate, driver weekday, driver-day
 * hour and ring, so 5,000 dots are about 90 kB; no id, time, text, door or
 * raw coordinate of a card. */
var AROUND_BIN_MI = 0.25;
var AROUND_BIN_DAYS = MIN_OUTINGS;
var HOME_MI = PLACE_APPROX_MI;
var AROUND_RING_MI = 1;
var AROUND_RINGS = 10;   // the last ring holds 10 mi and beyond
var PICKUP_BANDS = [[0, 1, 'under 1 mi'], [1, 2, '1–2 mi'], [2, 3, '2–3 mi'], [3, 5, '3–5 mi'],
                    [5, Infinity, '5 mi or more']];

function round4(v) { return Math.round(v * 1e4) / 1e4; }

/* Which cards' fixes are home, by the two rules above: a Map of the offer
 * row to 'start' or 'usual', and the counts. Every row with a gated fix is
 * read, an order in the car or not: a card on the way to a pickup is the car
 * moving, which is what ends a starting stay. */
function homeOf(offers) {
  var line = timelineOf(offers || []).map(function (t) { return { at: t.at, o: t.o, fix: MV.fixOf(t.o) }; })
    .filter(function (x) { return x.fix; });
  var byDay = groupBy(line, function (x) { return outingOf(x.at); });
  var why = new Map(), starts = [];
  Object.keys(byDay).sort().forEach(function (d) {
    var list = byDay[d], first = list[0].fix;
    starts.push(first);
    for (var i = 0; i < list.length; i++) {
      if (MV.crowMiles(first, list[i].fix) > HOME_MI) break;
      why.set(list[i].o, 'start');
    }
  });
  var usual = starts.filter(function (s, i) {
    return starts.some(function (t, j) { return j !== i && MV.crowMiles(s, t) <= HOME_MI; });
  });
  if (usual.length) {
    line.forEach(function (x) {
      if (why.has(x.o)) return;
      if (usual.some(function (u) { return MV.crowMiles(u, x.fix) <= HOME_MI; })) why.set(x.o, 'usual');
    });
  }
  return { why: why, days: starts.length, usualDays: usual.length };
}

function aroundYou(offers, waiting, ww) {
  var home = homeOf(offers);
  var left = { start: 0, usual: 0, oneDay: 0, noFix: 0 };
  var pts = [];
  (waiting || []).forEach(function (w) {
    if (!w.fix) { left.noFix += 1; return; }
    var hw = home.why.get(w.o);
    if (hw) { left[hw] += 1; return; }
    var s = wwSlotOf(w.at);
    if (!s) return;
    pts.push({ bin: gridCell(w.fix, AROUND_BIN_MI), cell: cellOf(w.fix), mins: w.credit, rate: w.o.perHour,
               d: s.day, h: s.hour, outing: outingOf(w.at) });
  });
  var binDays = Object.create(null);
  pts.forEach(function (p) { (binDays[p.bin.id] = binDays[p.bin.id] || Object.create(null))[p.outing] = true; });
  var kept = pts.filter(function (p) { return Object.keys(binDays[p.bin.id]).length >= AROUND_BIN_DAYS; });
  left.oneDay = pts.length - kept.length;
  // The most-used waiting area: the 2-mile cell with the most credited
  // minutes among the dots drawn; ties to the lower id, so a re-run agrees.
  var mins = Object.create(null), boxes = Object.create(null);
  kept.forEach(function (p) { mins[p.cell.id] = (mins[p.cell.id] || 0) + p.mins; boxes[p.cell.id] = p.cell; });
  var topCell = Object.keys(mins).sort(function (a, b) { return mins[b] - mins[a] || (a < b ? -1 : 1); })[0];
  var centre = topCell ? boxes[topCell] : null;
  var binIdx = Object.create(null), bins = [];
  var dots = { b: [], r: [], d: [], h: [], g: [] };
  kept.forEach(function (p) {
    if (!(p.bin.id in binIdx)) { binIdx[p.bin.id] = bins.length; bins.push([round4(p.bin.lat), round4(p.bin.lon)]); }
    dots.b.push(binIdx[p.bin.id]);
    dots.r.push(round2(p.rate));
    dots.d.push(p.d);
    dots.h.push(p.h);
    // Measured from the bin's centre, the only position the dot keeps.
    var mi = centre ? MV.crowMiles({ lat: p.bin.lat, lon: p.bin.lon }, centre) : null;
    dots.g.push(mi === null ? null : Math.min(AROUND_RINGS, Math.floor(mi / AROUND_RING_MI)));
  });
  // The card's own drive to the pickup, every counted offer, no GPS needed.
  var pick = { b: [], r: [], d: [], h: [] };
  (offers || []).forEach(function (o) {
    if (!counted(o) || typeof o.toPickupMiles !== 'number' || !isFinite(o.toPickupMiles) || o.toPickupMiles < 0) return;
    var s = wwSlotOf(seenAt(o));
    if (!s) return;
    for (var i = 0; i < PICKUP_BANDS.length; i++) {
      if (o.toPickupMiles >= PICKUP_BANDS[i][0] && o.toPickupMiles < PICKUP_BANDS[i][1]) break;
    }
    pick.b.push(i); pick.r.push(round2(o.perHour)); pick.d.push(s.day); pick.h.push(s.hour);
  });
  return { binMi: AROUND_BIN_MI, binDays: AROUND_BIN_DAYS, homeMi: HOME_MI, ringMi: AROUND_RING_MI,
           // When & where's blocks as driver-day hours, for the Hours picker.
           blockHours: WW_BLOCKS.map(function (bk) { return [bk[0], bk[1]]; }),
           rings: AROUND_RINGS, cards: (waiting || []).length, bins: bins, dots: dots, left: left,
           homeDays: home.days, usualDays: home.usualDays,
           centre: centre ? { cell: topCell, lat: centre.lat, lon: centre.lon,
                              hours: Math.round(mins[topCell] / 6) / 10 } : null,
           pickup: { bands: PICKUP_BANDS.map(function (p) { return p[2]; }), b: pick.b, r: pick.r, d: pick.d, h: pick.h } };
}

/* --- the front page's when and where (the reporting work's round B) --------
 *
 * The owner, Nov 2026: "a simplified overview that lets you expand into more
 * specific details ... when (time of day, day of the week, etc) and where
 * (gps, pickup and drop off areas)". The Overview now opens on that, from
 * this report's own data, each part linking to the tab that works it out:
 *
 *   - THE BEST WINDOWS: trends.js findWindows — the offers page's own search,
 *     one definition — over When & where's line (cards with no order in the
 *     car, each credited the minutes to the next card, capped as that tab
 *     caps them), good at When & where's fixed 20% cut. So a window here is
 *     good offers per hour WAITED, When & where's figure, not per hour
 *     online as on the offers page; the floor is When & where's (2 hours on
 *     2 shift days), and "clearly" is the 99% shared over the windows looked
 *     at, phi measured at each window length, as findWindows says.
 *   - THE BEST WAITING AREAS IN THOSE WINDOWS, by the car's own fix: the
 *     same line inside the window's weekday and hours, by town (where the
 *     NucBox named the cell's centre) or 2-mile cell, at When & where's
 *     floor, ranked by good per hour waited. HOME IS LEFT OUT here by
 *     homeOf, the Offers around you rule (each day's starting stay, and
 *     anything within 0.3 mi of a usual start). This is a new view, so the
 *     exclusion changes no existing table: When & where, Waited and Busy
 *     still count home, as AUDITS.md's Open entry says, until the owner
 *     decides.
 *   - PICKUP AND DROP-OFF TOWNS: trends.js towns over every counted offer
 *     (the card's printed town, map-view.js townOf over advice.js area, the
 *     offers page's rule), at the same cut.
 *
 * Descriptive like every tab: when and where offers paid best, never what
 * to take; nothing reaches the rig. No coordinate is added: an area is a
 * town or a cell already named on the report. */
var GLANCE_AREAS = 2;
function glanceOf(offers, waiting, rulers) {
  var ti = WW_TOPS.indexOf(WW_TOP), cut = rulers.cuts[ti];
  var home = homeOf(offers);
  var line = (waiting || []).map(function (w) {
    var sl = wwSlotOf(w.at);
    if (!sl) return null;
    return { w: w, dow: sl.day, hour: (sl.hour + A.DAY_STARTS_AT) % 24, day: outingOf(w.at),
             good: cut !== null && w.o.perHour >= cut };
  }).filter(Boolean);
  var win = TR.findWindows(line.map(function (c) {
    return { day: c.day, dow: c.dow, hour: c.hour, k: c.good ? 1 : 0, h: c.w.credit / 60, offers: 1 };
  }), { floorHours: WW_MIN_HOURS, floorDays: WW_MIN_DAYS });
  var homeLeft = 0;
  function areasIn(w) {
    var by = Object.create(null);
    line.forEach(function (c) {
      if (w.dows.indexOf(c.dow) < 0 || w.hours.indexOf(c.hour) < 0) return;
      if (home.why.has(c.w.o)) { homeLeft += 1; return; }
      var key = c.w.town ? 't:' + c.w.town : c.w.cell ? 'c:' + c.w.cell : null;
      if (!key) return;
      var e = by[key] || (by[key] = { a: key.slice(2), town: key[0] === 't', mins: 0, k: 0, n: 0, days: Object.create(null) });
      e.mins += c.w.credit; e.n += 1; if (c.good) e.k += 1;
      e.days[c.day] = true;
    });
    return Object.keys(by).map(function (k) {
      var e = by[k], h = e.mins / 60, d = Object.keys(e.days).length;
      return { a: e.a, town: e.town, h: round2(h), d: d, n: e.n, good: e.k, r: h > 0 ? round2(e.k / h) : null,
               ok: h >= WW_MIN_HOURS && d >= WW_MIN_DAYS };
    }).filter(function (e) { return e.ok; }).sort(function (x, y) { return y.r - x.r || y.h - x.h; }).slice(0, GLANCE_AREAS);
  }
  var shown = win.best.length ? win.best : win.leading;
  shown.forEach(function (w) { w.areas = areasIn(w); });
  var tw = TR.towns(offers, { cut: cut, townOf: function (v) { return MV.townOf(v, A.area); } });
  // Kept as `pick` and `drop`: the report's embedded data holds no field
  // named after a card's ends (the privacy checks look for one).
  return { cut: cut, top: WW_TOP, windows: win, homeLeft: homeLeft, homeDays: home.days,
           towns: { n: tw.n, share: tw.share, minN: tw.minN, minDays: tw.minDays, pick: tw.pickup, drop: tw.dropoff } };
}

/* --- after a drop, the next offer of any kind ------------------------------
 *
 * "Where trips leave you" timed the next offer the rig said TAKE. The owner's
 * Trends round asked for the next offer at all, and its quality: the first
 * offer the rig stands behind after the put-down, minutes to it, its $/hr
 * and whether it cleared the target, the same silence rule ending the wait. */
function nextOffer(timeline, endedAt) {
  var last = endedAt, gap = NEXT_GAP_MIN * 60000;
  for (var i = 0; i < timeline.length; i++) {
    var t = timeline[i];
    if (t.at <= endedAt || !t.counted) continue;
    if (t.at - last > gap) return { censored: true };
    return { censored: false, wait: (t.at - endedAt) / 60000, perHour: t.perHour, good: goodOf(t.o) };
  }
  return { censored: true };
}

/* Where a put-down left the car when neither the GPS log nor the dropoff's
 * door can say: the car's own fix on the first card that came up within
 * CARD_FIX_AFTER_MIN after it (offers keep arriving through a delivery and
 * after one; the median gap to the next card after a take was 5.4 minutes on
 * the owner's week). Chosen, not measured: three minutes is about a mile of
 * town driving, half a 2-mile cell. */
var CARD_FIX_AFTER_MIN = 3;
function cardFixAfter(offers, endedAt) {
  var best = null;
  (offers || []).forEach(function (o) {
    var t = seenAt(o), fix = MV.fixOf(o);
    if (!fix || typeof t !== 'number' || t < endedAt || t - endedAt > CARD_FIX_AFTER_MIN * 60000) return;
    if (!best || t < best.t) best = { t: t, at: fix };
  });
  return best ? { at: best.at, how: 'card fix' } : null;
}

/* --- empty driving: from a put-down to the next Took ------------------------
 *
 * Measured first, as the round asked: which journal rows carry a position?
 * Offer rows only. `seen` rows (scan_pi.note_tally) and health tallies carry
 * no fix, order rows carry the drive's total miles off the live GPS but no
 * track, `drop` and `finished` rows carry how an order ended, not where. So
 * between jobs the journal's positions are the cards' own, as often as cards
 * come (fixDensity below reports how often that was). That is enough for two
 * ends — where the car was at the drop (the GPS log, the door, or the next
 * card's fix) and where it was when the next order was taken (that card's own
 * fix) — and for a lower bound of the path through the cards between. It is
 * NOT a measure of miles driven: the Best tab's dead miles, off the GPS log
 * (--gps), is that. Moved = the two ends more than MOVED_MI apart (chosen:
 * half a 2-mile cell, beyond a car park and its block). */
var MOVED_MI = 1;
function emptyOf(trips, taken, byId, offers) {
  var tooks = (taken || []).filter(function (t) { return t && typeof t.tookAt === 'number'; })
    .sort(function (a, b) { return a.tookAt - b.tookAt; });
  var fixes = (offers || []).filter(counted).map(function (o) { return { t: seenAt(o), at: MV.fixOf(o) }; })
    .filter(function (f) { return f.at && typeof f.t === 'number'; }).sort(function (a, b) { return a.t - b.t; });
  trips.forEach(function (tr) {
    if (!tr.pos) { tr.empty = null; return; }
    var next = null;
    for (var i = 0; i < tooks.length; i++) if (tooks[i].tookAt > tr.at) { next = tooks[i]; break; }
    var o = next && byId[next.id];
    var end = o ? MV.fixOf(o) : null;
    if (!next || !end || next.tookAt - tr.at > DEAD_MAX_MIN * 60000) { tr.empty = { censored: true }; return; }
    var pts = [tr.pos].concat(fixes.filter(function (f) { return f.t > tr.at && f.t < next.tookAt; })
      .map(function (f) { return f.at; })).concat([end]);
    var path = 0;
    for (var k = 1; k < pts.length; k++) path += MV.crowMiles(pts[k - 1], pts[k]);
    var crow = MV.crowMiles(tr.pos, end);
    tr.empty = { censored: false, minutes: (next.tookAt - tr.at) / 60000, crow: crow, path: path,
                 cards: pts.length - 2, moved: crow > MOVED_MI,
                 perHour: counted(o) ? o.perHour : null };
  });
}

function emptyTable(trips, keyName, label, what) {
  var all = trips.filter(function (t) { return t.empty && !t.empty.censored; });
  function row(name, list) {
    var ok = list.length >= DROP_MIN_N;
    return { name: name, measured: list.length,
             minutes: ok ? med(list.map(function (t) { return t.empty.minutes; })) : null,
             crow: ok ? med(list.map(function (t) { return t.empty.crow; })) : null,
             path: ok ? med(list.map(function (t) { return t.empty.path; })) : null,
             cards: ok ? med(list.map(function (t) { return t.empty.cards; })) : null,
             moved: ok ? share(list.filter(function (t) { return t.empty.moved; }).length, list.length) : null,
             nextPerHour: ok ? med(list.filter(function (t) { return t.empty.perHour !== null; })
               .map(function (t) { return t.empty.perHour; })) : null };
  }
  var out = [row('every trip', all), row('moved over ' + MOVED_MI + ' mi', all.filter(function (t) { return t.empty.moved; })),
             row('stayed within ' + MOVED_MI + ' mi', all.filter(function (t) { return !t.empty.moved; }))];
  var by = groupBy(all.filter(function (t) { return t[keyName]; }), function (t) { return t[keyName]; });
  var thinCount = 0;
  Object.keys(by).sort().forEach(function (k) {
    // A dropoff area under the floor is a handful of customers: not named.
    if (by[k].length < DROP_MIN_N) { thinCount += 1; return; }
    out.push(row(label(k), by[k]));
  });
  return { cols: [C('name', what, 't'), C('measured', 'trips', 'n'), C('minutes', 'min to next Took', 'min'),
                  C('crow', 'straight-line mi', 'mi'), C('path', 'mi through the cards (at least)', 'mi'),
                  C('cards', 'cards between', 'r'), C('moved', 'moved', '%'),
                  C('nextPerHour', 'next take $/hr', '$')], rows: out, thinCount: thinCount };
}

/* How often a good card fix comes, within a run of scanning: the gaps between
 * consecutive fixed cards no more than NEXT_GAP_MIN apart. */
function fixDensity(offers) {
  var pool = (offers || []).filter(counted);
  var ts = pool.filter(function (o) { return MV.fixOf(o); }).map(seenAt).filter(isFinite).sort(function (a, b) { return a - b; });
  var gaps = [];
  for (var i = 1; i < ts.length; i++) {
    var g = (ts[i] - ts[i - 1]) / 60000;
    if (g <= NEXT_GAP_MIN) gaps.push(g);
  }
  gaps.sort(function (a, b) { return a - b; });
  return { offers: pool.length, fixed: ts.length,
           refused: pool.filter(function (o) { return MV.fixRefused(o); }).length,
           gapMedian: gaps.length ? round2(quantile(gaps, 0.5)) : null,
           gapP90: gaps.length ? round2(quantile(gaps, 0.9)) : null,
           over5: gaps.length ? share(gaps.filter(function (g) { return g > 5; }).length, gaps.length) : null };
}

/* --- the second pass: what you took, what it paid, and what the area is like
 *
 * The owner, 26 Oct 2026: "Go ahead with all of them, fast track to
 * experimental, having $/mi data is also a good metric to see." EXPERIMENTAL
 * and DESCRIPTIVE: every table below is a count, a median and (where n
 * allows) a bootstrap or Wilson interval. None is ranked by a test, none is
 * coloured (the colour rule above stays the only one: a grouping that beats
 * chance AND an interval clear of zero), none is a rule. AUDITS.md, Settled:
 * no $/mile rule and no payout floor (the $/mi here is for reading), no
 * minutes re-timed at a pace (real minutes are a clock less a clock), no
 * weekday term (weeks below are a trend line, not a term in anything).
 *
 * The floors. DESC_MIN_N, the dropoff tables' floor, is the fewest values a
 * descriptive median gets an interval on, and the fewest offers an area needs
 * to get a row in these tables at all. REAL_MED_N is the fewest timed trips a
 * median of real time is printed for (below it: the n alone). Chosen, not
 * measured: at three a median is a middle value, not an estimate, and the
 * page prints the n beside it. */
var DESC_MIN_N = DROP_MIN_N;
var REAL_MED_N = 3;
// A trip's real time is Took to put-down, and only a put-down AT THE DOOR
// measures it: the GPS ('gps') or the app's own delivered screen ('screen').
// A Drop press ('drop', 'chooser') can come early and makes a trip look
// faster than it was; 'replaced' and 'expiry' measure nothing. The offers
// page's "Card against what it took" says the same and counts both kinds.
var REAL_BY = ['gps', 'screen', 'drop (gps-timed)'].concat(FINISHED);
// Gone quiet: the last QUIET_DAYS of the record against the rest.
var QUIET_DAYS = 14;
var QUIET_MIN_OUTINGS = 3;
var QUIET_MIN_EXPECTED = 5;
// A wait in one spot: every fix within SPELL_M of the spell's first, for
// SPELL_MIN_S or more, no gap between fixes over SPELL_GAP_S (the rig off),
// and no order in the car. All three chosen, not measured: 150 m is a car
// park and the street outside it, three minutes is longer than a light or a
// drive-through queue, and five minutes without a fix is the rig switched off.
var SPELL_M = 150;
var SPELL_MIN_S = 180;
var SPELL_GAP_S = 300;
// The GPS log thinned to a fix every this many seconds before it reaches
// node: a month at one a second is millions of lines, and a spell is minutes.
var SPELL_THIN_S = 10;
var SPELL_MIN_N = DROP_MIN_N;
var APPS = ['uber', 'doordash'];

/* $/mi exactly as the offers page's payPerMile (journal.html): the card's
 * pay over the card's miles, nothing taken off; null without both, or under
 * a tenth of a mile, whose ratio is a misread's. For reading, never a rule. */
function payPerMile(o) {
  return o && typeof o.pay === 'number' && typeof o.miles === 'number' && o.miles >= 0.1
    ? o.pay / o.miles : null;
}

/* Which app an offer row is: the row's own `app` where a writer put one,
 * else offer-parser.js's screenType off the row's text (the JS port of the
 * rule scan_pi's offer line names the app by), else null. */
function appOf(o) {
  if (o && (o.app === 'uber' || o.app === 'doordash')) return o.app;
  var t = o && typeof o.text === 'string' ? o.text : '';
  return t ? OP.screenType(t).app || null : null;
}

/* What a card said of its own size. The journal row keeps `addon` and the
 * texts; the other three are the OFFER LINE's (scan_pi.says_*), not the
 * row's, so where a row has no such field they are read off the row's text
 * and kept frames by scan_pi's own patterns, copied here and held equal to
 * them by the suite (it reads them out of rpi/scan_pi.py). null: unread. */
var EARLY_LOOK = /\bearly\s*[lt]ook\b|\b[oa]rder\s*in\s*progress\b/i;
var MULTI_ORDER = /\+\s*\d+\s*orders?\b|\b(?:[2-9]|[1-9]\d)\s*orders\b/i;
var MANY_DROPOFFS = /multiple\s*drop\s*-?\s*offs/i;
function flagsOf(o) {
  var texts = (Array.isArray(o.scans) ? o.scans : []).concat([o.text])
    .filter(function (t) { return typeof t === 'string' && t; });
  function said(k, re) {
    if (typeof o[k] === 'boolean') return o[k];
    return texts.length ? texts.some(function (t) { return re.test(t); }) : null;
  }
  var addon = o.addon === true || o.screen === 'uber.addon'
    || texts.some(function (t) { return OP.screenType(t).screen === 'uber.addon'; });
  return { addon: addon || (texts.length || 'addon' in o ? false : null),
           multiOrder: said('multiOrder', MULTI_ORDER), manyDropoffs: said('manyDropoffs', MANY_DROPOFFS),
           earlyLook: said('earlyLook', EARLY_LOOK) };
}

// Wilson's 95% interval on k of n, or null at n = 0.
function wilson(k, n) {
  if (!n) return null;
  var z = 1.96, p = k / n, d = 1 + z * z / n;
  var mid = (p + z * z / (2 * n)) / d, half = z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d;
  return [round2(Math.max(0, mid - half)), round2(Math.min(1, mid + half))];
}

/* P(X <= x) for X ~ Poisson(lam), summed in logs. The plain sum started from
 * exp(-lam), which is 0 for any lam over about 745: every term after it was
 * 0 too, so a busy area expecting 1,142 offers that got 1,138 read p = 0 and
 * "Gone quiet" flagged every busy town on the invented 11,721-offer journal
 * (true p 0.46). Each term's log is the last one's plus log(lam / k), added
 * to the running log-sum without leaving logs. */
function poissonLE(x, lam) {
  if (x < 0) return 0;
  if (lam <= 0) return 1;
  var t = -lam, s = t;
  for (var k = 1; k <= x; k++) {
    t += Math.log(lam / k);
    s = s > t ? s + Math.log1p(Math.exp(t - s)) : t + Math.log1p(Math.exp(s - t));
  }
  return Math.min(1, Math.exp(s));
}

// The ISO week ('2026-W10') of a shift day 'YYYY-MM-DD'.
function isoWeek(day) {
  var p = String(day).split('-').map(Number);
  var d = new Date(Date.UTC(p[0], p[1] - 1, p[2]));
  var dow = d.getUTCDay() || 7;
  d.setUTCDate(d.getUTCDate() + 4 - dow);
  var y = d.getUTCFullYear();
  var wk = Math.ceil(((d - Date.UTC(y, 0, 1)) / 864e5 + 1) / 7);
  return y + '-W' + String(wk).padStart(2, '0');
}

function med(xs) { return xs.length ? round2(MV.median(xs)) : null; }
function medCi(xs, seed) { return xs.length >= DESC_MIN_N ? bootCI(xs, seedOf(seed)) : null; }
function share(k, n) { return n ? round2(k / n) : null; }

/* takenRuns by offer id. Every run, whatever its `by`: a take is a take. */
function runsOf(taken) {
  var by = Object.create(null);
  (taken || []).forEach(function (t) {
    if (t && typeof t.id === 'string') (by[t.id] = by[t.id] || []).push(t);
  });
  return by;
}

// A run's real time, or null: put down at the door, after its Took.
function realOf(t) {
  if (!t || REAL_BY.indexOf(t.by) < 0 || typeof t.tookAt !== 'number' || typeof t.endedAt !== 'number'
      || !(t.endedAt > t.tookAt)) return null;
  var mins = (t.endedAt - t.tookAt) / 60000;
  return { mins: mins, gpsTimed: t.by === GPS_TIMED,
           perHour: typeof t.pay === 'number' ? t.pay / (mins / 60) : null,
           diff: typeof t.minutes === 'number' && t.minutes > 0 ? mins - t.minutes : null,
           ratio: typeof t.minutes === 'number' && t.minutes > 0 ? mins / t.minutes : null };
}

function groupBy(rows, key) {
  var by = Object.create(null);
  rows.forEach(function (o) { var k = key(o); if (k) (by[k] = by[k] || []).push(o); });
  return by;
}

function C(k, h, f) { return { k: k, h: h, f: f }; }

/* 1-3. Your takes, what they really paid, and card against real, by area. */
function takesTable(rows, runs, key, label, what) {
  var by = groupBy(rows.filter(counted), key);
  var out = Object.keys(by).map(function (k) {
    var list = by[k];
    var took = list.filter(function (o) { return runs[o.id]; });
    var real = [];
    took.forEach(function (o) {
      runs[o.id].forEach(function (t) { var r = realOf(t); if (r) real.push(r); });
    });
    var ph = real.map(function (r) { return r.perHour; }).filter(function (v) { return v !== null; });
    var df = real.map(function (r) { return r.diff; }).filter(function (v) { return v !== null; });
    var ra = real.map(function (r) { return r.ratio; }).filter(function (v) { return v !== null; });
    var enough = function (xs) { return xs.length >= REAL_MED_N; };
    return { name: label(k), offered: list.length, taken: took.length, take: share(took.length, list.length),
             takeCi: wilson(took.length, list.length), timed: real.length,
             gpsTimed: real.filter(function (r) { return r.gpsTimed; }).length,
             realPerHour: enough(ph) ? med(ph) : null, realCi: medCi(ph, 'r' + k),
             cardVsReal: enough(df) ? med(df) : null, cardVsRealCi: medCi(df, 'c' + k),
             ratio: enough(ra) ? med(ra) : null };
  }).filter(function (r) { return r.offered >= DESC_MIN_N || r.taken > 0; })
    .sort(function (a, b) { return b.taken - a.taken || b.offered - a.offered; });
  return { cols: [C('name', what, 't'), C('offered', 'offered', 'n'), C('taken', 'taken', 'n'),
                  C('take', 'take rate', '%'), C('takeCi', '95%', '%ci'), C('timed', 'timed at door', 'n'),
                  C('gpsTimed', 'of them, press GPS-timed', 'n'),
                  C('realPerHour', 'real $/hr', '$'), C('realCi', '95%', '$ci'),
                  C('cardVsReal', 'real − card min', 'dmin'), C('cardVsRealCi', '95%', 'dminci'),
                  C('ratio', 'real ÷ card', 'x')], rows: out };
}

/* 4. Restaurant waits beside pay. storeWaitsOut keeps a store's name and no
 * position, so a wait is joined to a place by its name, as Assemble.sameStore
 * compares two (Assemble.storeKey: lower case, letters and digits, one i/l
 * slip) and ONLY where the join cannot be a guess — server.js storeWaitFor's
 * rule for a store with no pin: not a chain's name (Assemble.chainName), one
 * store of that name on record, and one place of that name in this report. */
function waitsOk(waits) {
  return (waits || []).filter(function (w) {
    return w && typeof w.name === 'string' && typeof w.n === 'number' && typeof w.medianMin === 'number';
  });
}

/* The one join rule, for the waits tab and the Restaurants tab alike:
 * `label` the name, `ws` the waits on record (waitsOk), `places` how many
 * places of that name this report holds. { w, why }: the wait, or why not. */
function waitOf(label, ws, places) {
  var hits = ws.filter(function (w) { return AS.sameStore(w.name, label); });
  if (!hits.length) return { w: null, why: 'none on record' };
  if (AS.chainName(label)) return { w: null, why: 'a chain: which branch, a guess' };
  if (hits.length > 1) return { w: null, why: 'several stores of this name on record' };
  if (places > 1) return { w: null, why: 'this name is at more than one place here' };
  return { w: hits[0], why: null };
}

function waitsTable(rows, places, waits, placeKey) {
  var by = groupBy(rows.filter(counted), placeKey);
  var sameName = Object.create(null);
  Object.keys(places).forEach(function (id) {
    var k = AS.storeKey(places[id].label);
    sameName[k] = (sameName[k] || 0) + 1;
  });
  var ws = waitsOk(waits);
  var out = Object.keys(by).map(function (k) {
    var list = by[k], label = places[k] ? places[k].label : k;
    var j = waitOf(label, ws, sameName[AS.storeKey(label)] || 0);
    var why = j.why, w = j.w;
    var pays = list.map(function (o) { return o.pay; }).filter(function (v) { return typeof v === 'number'; });
    // ...and the worst wait and how many of the store's waits the rig found
    // from the stop pattern (server.js storeWaitsOut since the 7 Nov shift:
    // a pickup never pinned is timed off the car's first stop of two
    // minutes after the Took). Null from a rig older than those fields.
    return { name: label, n: list.length, pay: med(pays), perHour: med(list.map(function (o) { return o.perHour; })),
             wait: w ? w.medianMin : null, waitN: w ? w.n : null, why: why,
             waitWorst: w && typeof w.worstMin === 'number' ? w.worstMin : null,
             waitStops: w && typeof w.stops === 'number' ? w.stops : null };
  }).filter(function (r) { return r.wait !== null || r.n >= DESC_MIN_N; })
    .sort(function (a, b) { return (b.wait === null ? -1 : b.wait) - (a.wait === null ? -1 : a.wait) || b.n - a.n; });
  return { cols: [C('name', 'place', 't'), C('n', 'offers', 'n'), C('pay', 'median pay', '$'),
                  C('perHour', 'median $/hr', '$'), C('wait', 'median wait', 'min'), C('waitN', 'waits', 'n'),
                  C('waitWorst', 'worst wait', 'min'), C('waitStops', 'from the stop pattern', 'n'),
                  C('why', 'not joined', 't')], rows: out };
}

/* 5. Strand risk per store: how far its cards run, where its taken trips
 * ended (by town and by named 2-mile cell only), the store's own measured
 * waits for the next take, and the wait its trips' TOWNS predict: the mean,
 * over its trips, of the town table's median wait for the town each ended in
 * (only towns that clear that table's floor; shown when they cover half the
 * store's trips or more). */
function strandTable(rows, trips, placeKey, places, dropTown, namedCells, cellName) {
  var by = groupBy(rows.filter(counted), placeKey);
  var tripsBy = groupBy(trips.filter(function (t) { return t.offer; }), function (t) { return placeKey(t.offer); });
  var townWait = Object.create(null);
  dropTown.groups.forEach(function (g) { townWait[g.name] = g.median; });
  var keys = Object.keys(by).concat(Object.keys(tripsBy).filter(function (k) { return !by[k]; }));
  var out = keys.map(function (k) {
    var list = by[k] || [], ts = tripsBy[k] || [];
    var miles = list.map(function (o) { return o.miles; }).filter(function (v) { return typeof v === 'number' && v > 0; });
    var towns = Object.create(null), cells = Object.create(null), other = 0;
    ts.forEach(function (t) {
      var tw = t.town || 'town unread';
      towns[tw] = (towns[tw] || 0) + 1;
      if (t.cell && namedCells[t.cell]) cells[t.cell] = (cells[t.cell] || 0) + 1;
      else if (t.cell) other += 1;
    });
    function list2(m, name) {
      return Object.keys(m).sort(function (a, b) { return m[b] - m[a] || (a < b ? -1 : 1); })
        .map(function (x) { return name(x) + ' ' + m[x]; }).join(' · ');
    }
    var own = ts.filter(function (t) { return !t.next.censored; }).map(function (t) { return t.next.wait; });
    var covered = ts.filter(function (t) { return t.town && townWait[t.town] !== undefined; });
    var expect = covered.length && covered.length * 2 >= ts.length
      ? round2(covered.reduce(function (s, t) { return s + townWait[t.town]; }, 0) / covered.length) : null;
    return { name: places[k] ? places[k].label : k, n: list.length, miles: med(miles),
             milesCi: medCi(miles, 'm' + k), trips: ts.length, towns: list2(towns, String),
             cells: list2(cells, cellName) + (other ? (Object.keys(cells).length ? ' · ' : '') + 'cells too thin to name '
                                                   + other : ''),
             ownWait: own.length >= REAL_MED_N ? med(own) : null, ownN: own.length,
             expectWait: expect, covered: covered.length };
  }).filter(function (r) { return r.n >= DESC_MIN_N || r.trips > 0; })
    .sort(function (a, b) { return b.trips - a.trips || b.n - a.n; });
  return { cols: [C('name', 'place', 't'), C('n', 'offers', 'n'), C('miles', 'median card mi', 'mi'),
                  C('milesCi', '95%', 'mici'), C('trips', 'taken trips', 'n'), C('towns', 'ended in (towns)', 't'),
                  C('cells', 'ended in (2-mi cells)', 't'), C('ownWait', 'its own wait after', 'min'),
                  C('ownN', 'measured', 'n'), C('expectWait', 'expected wait after (towns)', 'min'),
                  C('covered', 'trips covered', 'n')], rows: out };
}

/* 6. How busy each area is, off the GPS: spells parked with no order in the
 * car (spellsOf), by area and three-hour block. Hours waited, offers the rig
 * counted per hour of it, the share of spells that saw an offer the rig said
 * take while there and the median minutes to the first one. Under
 * SPELL_MIN_N spells or MIN_OUTINGS shift days a row says its n and nothing
 * else. */
function busyTable(spells, keyName, label, what) {
  var by = groupBy(spells.filter(function (s) { return s[keyName]; }),
                   function (s) { return s[keyName] + '\u0000' + A.blockOf(s.from); });
  var out = Object.keys(by).map(function (k) {
    var list = by[k], parts = k.split('\u0000');
    var days = Object.create(null);
    list.forEach(function (s) { days[outingOf(s.from)] = true; });
    var hours = list.reduce(function (sum, s) { return sum + (s.to - s.from) / 3.6e6; }, 0);
    var seen = list.reduce(function (sum, s) { return sum + s.seen; }, 0);
    var got = list.filter(function (s) { return s.go !== null; }).map(function (s) { return s.go; });
    var ok = list.length >= SPELL_MIN_N && Object.keys(days).length >= MIN_OUTINGS;
    return { name: label(parts[0]), block: A.BLOCK_NAMES[Number(parts[1])], blockN: Number(parts[1]),
             n: list.length, days: Object.keys(days).length, hours: Math.round(hours * 10) / 10,
             perHour: ok && hours > 0 ? round2(seen / hours) : null,
             goShare: ok ? share(got.length, list.length) : null,
             goMin: ok && got.length ? med(got) : null, goCi: ok ? medCi(got, 'g' + k) : null };
  }).sort(function (a, b) { return (a.name < b.name ? -1 : a.name > b.name ? 1 : 0) || a.blockN - b.blockN; });
  out.forEach(function (r) { delete r.blockN; });
  return { cols: [C('name', what, 't'), C('block', 'hours', 't'), C('n', 'spells', 'n'), C('days', 'days', 'n'),
                  C('hours', 'hours waited', 'h'), C('perHour', 'offers / hr waiting', 'r'),
                  C('goShare', 'saw a take', '%'), C('goMin', 'min to first take', 'min'),
                  C('goCi', '95%', 'minci')], rows: out };
}

/* 7. Uber against DoorDash, side by side, per area. */
function appsTable(rows, runs, key, label, what) {
  var pool = rows.filter(counted);
  var by = groupBy(pool, key);
  function side(list) {
    var o = {};
    APPS.forEach(function (app) {
      var l = list.filter(function (r) { return appOf(r) === app; });
      var ok = l.length >= DESC_MIN_N;
      o[app + 'N'] = l.length;
      o[app + 'PerHour'] = ok ? med(l.map(function (r) { return r.perHour; })) : null;
      o[app + 'Ppm'] = ok ? med(l.map(payPerMile).filter(function (v) { return v !== null; })) : null;
      o[app + 'Take'] = l.length ? share(l.filter(function (r) { return runs[r.id]; }).length, l.length) : null;
    });
    o.unknownN = list.filter(function (r) { return !appOf(r); }).length;
    return o;
  }
  var out = Object.keys(by).filter(function (k) { return by[k].length >= DESC_MIN_N; }).map(function (k) {
    return Object.assign({ name: label(k), n: by[k].length }, side(by[k]));
  }).sort(function (a, b) { return b.n - a.n; });
  if (pool.length) out.unshift(Object.assign({ name: 'every ' + what, n: pool.length }, side(pool)));
  return { cols: [C('name', what, 't'), C('n', 'offers', 'n'),
                  C('uberN', 'Uber n', 'n'), C('uberPerHour', 'Uber $/hr', '$'), C('uberPpm', 'Uber $/mi', '$'),
                  C('uberTake', 'Uber taken', '%'),
                  C('doordashN', 'DD n', 'n'), C('doordashPerHour', 'DD $/hr', '$'), C('doordashPpm', 'DD $/mi', '$'),
                  C('doordashTake', 'DD taken', '%'), C('unknownN', 'app unread', 'n')], rows: out };
}

/* 11. $/mi per area, and per app. */
function ppmTable(rows, key, label, what) {
  var by = groupBy(rows.filter(function (o) { return counted(o) && payPerMile(o) !== null; }), key);
  var out = Object.keys(by).filter(function (k) { return by[k].length >= DESC_MIN_N; }).map(function (k) {
    var v = by[k].map(payPerMile);
    var r = { name: label(k), n: v.length, ppm: med(v), ppmCi: medCi(v, 'p' + k),
              perHour: med(by[k].map(function (o) { return o.perHour; })) };
    APPS.forEach(function (app) {
      var l = by[k].filter(function (o) { return appOf(o) === app; }).map(payPerMile);
      r[app + 'N'] = l.length;
      r[app] = l.length >= DESC_MIN_N ? med(l) : null;
    });
    return r;
  }).sort(function (a, b) { return b.ppm - a.ppm; });
  return { cols: [C('name', what, 't'), C('n', 'n', 'n'), C('ppm', 'median $/mi', '$'), C('ppmCi', '95%', '$ci'),
                  C('perHour', 'median $/hr', '$'), C('uberN', 'Uber n', 'n'), C('uber', 'Uber $/mi', '$'),
                  C('doordashN', 'DD n', 'n'), C('doordash', 'DD $/mi', '$')], rows: out };
}

/* 8. Add-on and stacking chance per store: the share of its offers whose
 * card said so, each over the cards where that could be read. */
function stackTable(rows, placeKey, label) {
  var by = groupBy(rows.filter(counted), placeKey);
  var out = Object.keys(by).filter(function (k) { return by[k].length >= DESC_MIN_N; }).map(function (k) {
    var fl = by[k].map(flagsOf);
    var r = { name: label(k), n: by[k].length };
    ['addon', 'multiOrder', 'manyDropoffs', 'earlyLook'].forEach(function (f) {
      var read = fl.filter(function (x) { return x[f] !== null; });
      r[f] = share(read.filter(function (x) { return x[f]; }).length, read.length);
      r[f + 'Read'] = read.length;
    });
    var any = fl.filter(function (x) { return x.addon || x.multiOrder || x.manyDropoffs || x.earlyLook; }).length;
    r.any = share(any, fl.length);
    r.anyCi = wilson(any, fl.length);
    return r;
  }).sort(function (a, b) { return b.any - a.any || b.n - a.n; });
  return { cols: [C('name', 'place', 't'), C('n', 'offers', 'n'), C('addon', 'add-on', '%'),
                  C('multiOrder', 'more than one order', '%'), C('manyDropoffs', 'more than one dropoff', '%'),
                  C('earlyLook', 'early look', '%'), C('any', 'any of these', '%'), C('anyCi', '95%', '%ci'),
                  C('addonRead', 'cards read', 'n')], rows: out };
}

/* 9. Gone quiet. The record's own last day (the newest offer, not the
 * clock, so a journal that stopped a week ago does not call everything
 * quiet) less QUIET_DAYS splits each area's offers into before and recent.
 *   fewer offers: before holds MIN_N offers or more, the recent part holds
 *     QUIET_MIN_OUTINGS shift days or more, and at the before rate per shift
 *     day out the recent days should have brought QUIET_MIN_EXPECTED or more;
 *     then flagged where P(this few | Poisson at that rate) < ALPHA.
 *   lower score: DESC_MIN_N hour-held scores or more on each side, recent
 *     median below before, and Advice.areas' test of the two < ALPHA.
 * Per shift day out, not per calendar day: a week off is not a place going
 * quiet. All hours only: the hour filter would leave neither side its n. */
function quietTable(rows, key, label, diffs, what) {
  var pool = rows.filter(counted);
  var times = pool.map(seenAt).filter(isFinite);
  if (!times.length) return { cols: [], rows: [], cut: null };
  var end = Math.max.apply(null, times), cut = end - QUIET_DAYS * 864e5;
  var before = pool.filter(function (o) { return seenAt(o) < cut; });
  var recent = pool.filter(function (o) { return seenAt(o) >= cut; });
  var outB = A.outingsIn(before), outR = A.outingsIn(recent);
  var by = groupBy(pool, key);
  var out = Object.keys(by).filter(function (k) { return by[k].length >= DESC_MIN_N; }).map(function (k) {
    var list = by[k];
    var b = list.filter(function (o) { return seenAt(o) < cut; }).length, r = list.length - b;
    var last = Math.max.apply(null, list.map(seenAt));
    var expected = outB ? round2(b / outB * outR) : null;
    var countP = b >= MIN_N && outR >= QUIET_MIN_OUTINGS && expected >= QUIET_MIN_EXPECTED
      ? Math.round(poissonLE(r, expected) * 1000) / 1000 : null;
    var d = (diffs && diffs[k]) || [];
    var bd = d.filter(function (x) { return x.at < cut; }), rd = d.filter(function (x) { return x.at >= cut; });
    var sB = null, sR = null, scoreP = null;
    if (bd.length >= DESC_MIN_N && rd.length >= DESC_MIN_N) {
      sB = med(bd.map(function (x) { return x.d; }));
      sR = med(rd.map(function (x) { return x.d; }));
      var t = A.areas(bd.map(function (x) { return { perHour: x.d, at: x.at, side: 'b' }; })
                      .concat(rd.map(function (x) { return { perHour: x.d, at: x.at, side: 'r' }; })),
                      { key: function (x) { return x.side; }, floor: 1, days: 1, shuffles: SHUFFLES });
      scoreP = typeof t.p === 'number' ? t.p : null;
    }
    var flags = [];
    if (countP !== null && countP < ALPHA) flags.push('fewer offers');
    if (scoreP !== null && scoreP < ALPHA && sR < sB) flags.push('lower score');
    return { name: label(k), last: outingOf(last), before: b, recent: r, expected: expected, countP: countP,
             scoreBefore: sB, scoreRecent: sR, scoreP: scoreP, flag: flags.join(', ') };
  }).sort(function (a, b) { return (b.flag ? 1 : 0) - (a.flag ? 1 : 0) || (a.last < b.last ? -1 : a.last > b.last ? 1 : 0); });
  return { cols: [C('name', what, 't'), C('last', 'last offer', 't'), C('before', 'before', 'n'),
                  C('recent', 'last ' + QUIET_DAYS + ' days', 'n'), C('expected', 'expected', 'r'),
                  C('countP', 'p (count)', 'p'), C('scoreBefore', 'score before', 's$'),
                  C('scoreRecent', 'score recent', 's$'), C('scoreP', 'p (score)', 'p'), C('flag', 'gone quiet', 't')],
           rows: out, cut: outingOf(cut), outingsBefore: outB, outingsRecent: outR };
}

/* 10. Trend: each ranked area's hour-held score (its offers against the
 * other cells in the same block, the all-hours ranking's own differences),
 * by ISO week of the shift day, only weeks with DESC_MIN_N or more. */
function trendTable(diffs, label, what) {
  var out = Object.keys(diffs || {}).map(function (k) {
    var wk = groupBy(diffs[k], function (x) { return isoWeek(outingOf(x.at)); });
    var weeks = Object.keys(wk).sort().filter(function (w) { return wk[w].length >= DESC_MIN_N; }).map(function (w) {
      var v = wk[w].map(function (x) { return x.d; });
      return { w: w, n: v.length, score: med(v), ci: bootCI(v, seedOf('w' + k + w)) };
    });
    return { name: label(k), weeks: weeks.length, first: weeks.length ? weeks[0].score : null,
             last: weeks.length ? weeks[weeks.length - 1].score : null, spark: weeks };
  }).filter(function (r) { return r.weeks > 0; }).sort(function (a, b) { return b.weeks - a.weeks; });
  return { cols: [C('name', what, 't'), C('spark', 'by week', 'spark'), C('weeks', 'weeks shown', 'n'),
                  C('first', 'first week', 's$'), C('last', 'latest week', 's$')], rows: out };
}

/* Spells parked with no order in the car, off fixes [[tSec, lat, lon]]
 * sorted by time, less `held` ([fromMs, toMs] with an order in the car).
 * A run of fixes each within SPELL_M of the run's first and no further apart
 * in time than SPELL_GAP_S, lasting SPELL_MIN_S; the held time is cut out
 * and each piece left that still lasts SPELL_MIN_S is a spell. Returns
 * [{from, to, lat, lon}] in ms, at the run's first fix. */
/* Runs of fixes each within `m` metres of the run's first, no two fixes
 * further apart than `gapS`, lasting `minS` or more: [{from, to, lat, lon}]
 * in ms, at the run's first fix. The one rule for "the car stood still",
 * a spell's (spellsOf) and a press's stop's (timePresses) alike. */
function stillRuns(fixes, m, minS, gapS) {
  var out = [], n = (fixes || []).length, i = 0;
  function metres(a, b) { return MV.crowMiles({ lat: a[1], lon: a[2] }, { lat: b[1], lon: b[2] }) * 1609.344; }
  while (i < n) {
    var j = i;
    while (j + 1 < n && fixes[j + 1][0] - fixes[j][0] <= gapS && metres(fixes[i], fixes[j + 1]) <= m) j += 1;
    if (fixes[j][0] - fixes[i][0] >= minS) {
      out.push({ from: fixes[i][0] * 1000, to: fixes[j][0] * 1000, lat: fixes[i][1], lon: fixes[i][2] });
    }
    i = j + 1;
  }
  return out;
}

function spellsOf(fixes, held) {
  var out = [];
  var hs = (held || []).slice().sort(function (a, b) { return a[0] - b[0]; });
  stillRuns(fixes, SPELL_M, SPELL_MIN_S, SPELL_GAP_S).forEach(function (run) {
    {
      var pieces = [[run.from, run.to]];
      hs.forEach(function (h) {
        var next = [];
        pieces.forEach(function (p) {
          if (h[1] <= p[0] || h[0] >= p[1]) { next.push(p); return; }
          if (h[0] > p[0]) next.push([p[0], h[0]]);
          if (h[1] < p[1]) next.push([h[1], p[1]]);
        });
        pieces = next;
      });
      pieces.forEach(function (p) {
        if (p[1] - p[0] >= SPELL_MIN_S * 1000) out.push({ from: p[0], to: p[1], lat: run.lat, lon: run.lon });
      });
    }
  });
  return out;
}

// The time an order was in the car: every takenRuns run, Took to put-down.
function heldOf(taken) {
  return (taken || []).filter(function (t) {
    return t && typeof t.tookAt === 'number' && typeof t.endedAt === 'number' && t.endedAt >= t.tookAt;
  }).map(function (t) { return [t.tookAt, t.endedAt]; });
}

/* --- restaurants: every offer of a name, placed or not --------------------
 *
 * The owner, 26 Oct 2026: "Would it be possible to have a comparison of
 * different restaurants and their pay? That could be helpful." The Places
 * table holds only pickups the map could pin, and the unplaced paid less
 * (the banner's own test), so this groups by the NAME the card printed and
 * needs no pin: every "Bramble Burger" is one row, its placed branches listed
 * under it, its unplaced offers counted with them.
 *
 * THE NAME. A pickup's name is storeLabel's (Uber's bracketed street off,
 * the line before a printed door's comma), and only where searchPlan reads
 * it as a name (pickupKind 'name'): a door, a street or a corner is no
 * restaurant's name and is counted as "no name on the card". Names are
 * merged by the rig's own store-name rule, the one this report already joins
 * waits by: Assemble.storeKey (case, marks, the planner's icon letters and a
 * " – Town" tail set aside) and Assemble.sameStore (one i/l slip). server.js
 * keys its store waits by storeKey too (storeWaitHeard), but its name rule
 * (storeNameSaid) is not exported and is not copied here. sameStore is not
 * transitive, so each name joins the first, most-offered, name it is the
 * same store as; a branch's label ("#1155") stays its own name, as the rig
 * reads it. */
function nameOf(pickup) {
  if (typeof pickup !== 'string' || !pickup.trim()) return null;
  var label = storeLabel(pickup);
  return pickupKind(label).kind === 'name' && AS.storeKey(label) ? label : null;
}

/* Every name in `offers`, merged: { of(o) -> key|null, labels: {key: label},
 * keys: {storeKey: key} }. The key is the merged name's own storeKey; the
 * label its most-printed spelling. */
function restaurantNames(offers) {
  var byKey = Object.create(null);
  (offers || []).filter(counted).forEach(function (o) {
    var l = nameOf(o.pickup);
    if (!l) return;
    var k = AS.storeKey(l);
    var e = byKey[k] || (byKey[k] = { n: 0, labels: Object.create(null) });
    e.n += 1;
    e.labels[l] = (e.labels[l] || 0) + 1;
  });
  var order = Object.keys(byKey).sort(function (a, b) { return byKey[b].n - byKey[a].n || (a < b ? -1 : 1); });
  var to = Object.create(null), heads = [], spell = Object.create(null);
  order.forEach(function (k) {
    var head = heads.filter(function (h) { return AS.sameStore(h, k); })[0];
    if (!head) { head = k; heads.push(k); spell[k] = Object.create(null); }
    to[k] = head;
    Object.keys(byKey[k].labels).forEach(function (l) { spell[head][l] = (spell[head][l] || 0) + byKey[k].labels[l]; });
  });
  var labels = Object.create(null);
  heads.forEach(function (h) {
    labels[h] = Object.keys(spell[h]).sort(function (a, b) { return spell[h][b] - spell[h][a] || (a < b ? -1 : 1); })[0];
  });
  var memo = Object.create(null);
  return {
    labels: labels, keys: to,
    of: function (o) {
      var p = o && o.pickup;
      if (typeof p !== 'string') return null;
      if (!(p in memo)) { var l = nameOf(p); memo[p] = l ? to[AS.storeKey(l)] || null : null; }
      return memo[p];
    },
  };
}

/* What a list of offers paid and what became of them, as the second pass
 * measures it: medians, your takes and their real time (realOf: put down at
 * the door), add-on and stacking (flagsOf), the app split (appOf). */
function describe(list, runs, seed, tierOf) {
  var pays = list.map(function (o) { return o.pay; }).filter(function (v) { return typeof v === 'number'; });
  var ppms = list.map(payPerMile).filter(function (v) { return v !== null; });
  var took = list.filter(function (o) { return runs[o.id]; });
  var real = [];
  took.forEach(function (o) { runs[o.id].forEach(function (t) { var r = realOf(t); if (r) real.push(r); }); });
  var ph = real.map(function (r) { return r.perHour; }).filter(function (v) { return v !== null; });
  var df = real.map(function (r) { return r.diff; }).filter(function (v) { return v !== null; });
  var fl = list.map(flagsOf);
  var addonRead = fl.filter(function (x) { return x.addon !== null; });
  var stacked = fl.filter(function (x) { return x.addon || x.multiOrder || x.manyDropoffs || x.earlyLook; }).length;
  var out = { n: list.length, outings: A.outingsIn(list),
              perHour: med(list.map(function (o) { return o.perHour; })), pay: med(pays),
              ppm: med(ppms), ppmN: ppms.length,
              taken: took.length, take: share(took.length, list.length), takeCi: wilson(took.length, list.length),
              timed: real.length, gpsTimed: real.filter(function (r) { return r.gpsTimed; }).length,
              realPerHour: ph.length >= REAL_MED_N ? med(ph) : null, realCi: medCi(ph, 'rr' + seed),
              cardVsReal: df.length >= REAL_MED_N ? med(df) : null,
              addon: share(addonRead.filter(function (x) { return x.addon; }).length, addonRead.length),
              stacked: share(stacked, list.length) };
  var top = topOf(list, tierOf, 'd' + seed);
  out.p75 = top.p75; out.p90 = top.p90; out.p90Ci = top.p90Ci; out.top10 = top.top10; out.top25 = top.top25;
  APPS.forEach(function (app) {
    var l = list.filter(function (o) { return appOf(o) === app; });
    out[app + 'N'] = l.length;
    out[app + 'PerHour'] = l.length >= DESC_MIN_N ? med(l.map(function (o) { return o.perHour; })) : null;
  });
  return out;
}

/* The Restaurants table for one hours view. Ranked exactly as the other
 * groupings are (cells: Advice.areas' Kruskal-Wallis against block-held
 * shuffles across the ranked restaurants, `matched` against the other
 * ranked restaurants in the same block, bootstrap intervals, the same floor
 * and the same colour rule); everything else is describe's.
 *
 * WAITS. A restaurant's own row takes a wait by waitOf with every branch of
 * it counted as a place of that name: not a chain's, one store of it on
 * record, and at most one placed branch. A chain's wait is per branch only,
 * and since the waits on record carry no position (storeWaitsOut), a chain's
 * branch is never joined either: which branch, a guess. A branch row asks
 * waitOf as the waits tab does. */
function restaurantsTable(rows, ctx) {
  var res = cells(rows, ctx.key, { hold: ctx.hold, minN: ctx.minN, tierOf: ctx.tierOf });
  var pool = rows.filter(counted);
  var by = groupBy(pool, ctx.key);
  var ws = waitsOk(ctx.waits);
  var placeOf = Object.create(null);
  (ctx.placeCells ? ctx.placeCells.groups : []).forEach(function (g) { placeOf[g.name] = g; });
  // Places per name, across the whole report, as the waits tab counts them.
  var sameName = Object.create(null), branchesOf = Object.create(null);
  Object.keys(ctx.places).forEach(function (id) {
    var k = AS.storeKey(ctx.places[id].label);
    sameName[k] = (sameName[k] || 0) + 1;
    var head = ctx.names.keys[k];
    if (head) branchesOf[head] = (branchesOf[head] || 0) + 1;
  });
  function rowOf(k, g) {
    var list = by[k] || [];
    var label = ctx.names.labels[k] || k;
    var d = describe(list, ctx.runs, k, ctx.tierOf);
    var j = waitOf(label, ws, branchesOf[k] || 0);
    var subs = groupBy(list, function (o) { return ctx.placeKey(o) || '\u0000'; });
    var branches = Object.keys(subs).filter(function (id) { return id !== '\u0000'; }).map(function (id) {
      var p = ctx.places[id] || {}, pd = describe(subs[id], ctx.runs, id, ctx.tierOf);
      var pj = waitOf(p.label || label, ws, sameName[AS.storeKey(p.label || label)] || 0);
      var pg = placeOf[id];
      return Object.assign(pd, { id: id, name: p.label || label, lat: p.lat, lon: p.lon,
                                 placeScore: pg ? pg.score : null, placeSci: pg ? pg.sci : null,
                                 placeBeats: pg ? pg.beats : false, wait: pj.w ? pj.w.medianMin : null,
                                 waitN: pj.w ? pj.w.n : null, waitWhy: pj.why });
    }).sort(function (a, b) { return b.n - a.n || (a.name < b.name ? -1 : 1); });
    var un = subs['\u0000'] || [];
    if (un.length && branches.length) {
      branches.push(Object.assign(describe(un, ctx.runs, k + '~', ctx.tierOf), { id: null, name: 'not placed', unplaced: true,
                                                                     wait: null, waitN: null, waitWhy: null }));
    }
    var out = Object.assign(d, { name: k, label: label, ranked: !!g, chain: AS.chainName(label),
                                 placedN: list.length - un.length, branchN: branchesOf[k] || 0,
                                 wait: j.w ? j.w.medianMin : null, waitN: j.w ? j.w.n : null, waitWhy: j.why,
                                 waitWorst: j.w && typeof j.w.worstMin === 'number' ? j.w.worstMin : null,
                                 branches: branches });
    if (g) {
      ['score', 'sci', 'median', 'ci', 'clear', 'beats', 'matched', 'compared'].forEach(function (f) { out[f] = g[f]; });
      out.outings = g.outings;
    } else {
      out.score = null; out.sci = null; out.beats = false; out.clear = null;
    }
    return out;
  }
  var ranked = res.groups.map(function (g) { return rowOf(g.name, g); });
  var thin = res.thin.map(function (t) { return rowOf(t.name, null); });
  var noName = pool.filter(function (o) { return typeof o.pickup === 'string' && o.pickup.trim() && !ctx.key(o); }).length;
  var named = pool.filter(function (o) { return ctx.key(o); });
  return { p: res.p, h: res.h, rawP: res.rawP, held: res.held, significant: res.significant, kept: res.kept,
           floor: res.floor, outings: res.outings, groups: ranked, thin: thin,
           named: named.length, noName: noName, noPickup: pool.filter(function (o) {
             return !(typeof o.pickup === 'string' && o.pickup.trim());
           }).length,
           placed: named.filter(function (o) { return ctx.placeKey(o); }).length,
           names: ranked.length + thin.length };
}

/* --- the third pass: the top of the distribution --------------------------
 *
 * The owner, 26 Oct 2026: "please implement the new statistics you mentioned
 * as I am trying to get the best offers which are higher than the median by a
 * good bit." EXPERIMENTAL, and descriptive except where a test is named. No
 * $/mile rule and no payout floor (a threshold here is a percentile of the
 * record's own offers in their own hours, a thing to read, never an accept
 * rule), no minutes re-timed at a pace (real time is a clock less a clock;
 * the band is distance only), no weekday term, and colour only where a
 * grouping beats chance AND the interval is clear of zero — as before.
 *
 * TOP TIER, HOUR-HELD. An offer is top 25% (top 10%) when its $/hr is at or
 * over the 75th (90th) percentile of EVERY offer the rig stands behind in the
 * same three-hour block (advice.js blockOf), so a late-night offer is held to
 * late-night offers. A block with fewer than TIER_MIN_N offers gets no
 * threshold and its offers no tier. Ties at the threshold count as top, so a
 * share can sit a little over 10%. */
var TIER_MIN_N = MIN_N;
// Values before a P75 or P90 gets a bootstrap interval: the ranking's floor.
var Q_CI_MIN_N = MIN_N;
// A take "while waiting there": its Took within the spell or this soon after
// it ends (a spell is cut at the Took; the car may roll off a little first).
var TAKE_SLACK_MS = 2 * 60000;
// Dead miles: the next Took within this many minutes of the put-down, else
// the driver stopped, and the miles are not counted (censored).
var DEAD_MAX_MIN = 90;
// A press's stop: the car within STOP_M of the stop's first fix for STOP_MIN_S.
var STOP_M = 100;
var STOP_MIN_S = 60;
var PRESS_AFTER_MIN = 10;
var PRESS_BEFORE_MIN = 5;
// A press's stop reached with the car's GPS miles since the Took under this
// share of the card's miles is not the door (timePresses, notDriven). The
// value tools/shift_report.py's SHORT_MILES holds an order to, for the same
// fault, and chosen, not measured, as it is there.
var SHORT_MILES = 0.35;
// Offer size by card miles: [from, below, label].
var SIZE_BANDS = [[0, 4, 'short, under 4 mi'], [4, 8, 'medium, 4–8 mi'], [8, 12, 'long, 8–12 mi'],
                  [12, Infinity, '12 mi and over']];

// The q-th quantile, linear between order statistics (R's type 7).
function quantile(xs, q) {
  var v = xs.slice().sort(function (a, b) { return a - b; });
  if (!v.length) return null;
  var h = (v.length - 1) * q, lo = Math.floor(h);
  return v[lo] + (h - lo) * ((v[lo + 1] === undefined ? v[lo] : v[lo + 1]) - v[lo]);
}
// The same quantile, of a resample that may be reordered in place (the
// bootstrap's own buffer): two selections, not a sort.
function selectK(a, k) {
  var lo = 0, hi = a.length - 1;
  while (lo < hi) {
    var pv = a[(lo + hi) >> 1], i = lo, j = hi;
    while (i <= j) {
      while (a[i] < pv) i++;
      while (a[j] > pv) j--;
      if (i <= j) { var t = a[i]; a[i] = a[j]; a[j] = t; i++; j--; }
    }
    if (k <= j) hi = j; else if (k >= i) lo = i; else return a[k];
  }
  return a[k];
}
// It says its q, so bootCI walks the resample's counts to the two ranks
// instead of calling it on every resample (bootCI's header); called on a
// list it is the same quantile, which the check holds against the walk.
function qOf(q) {
  var f = function (xs) {
    var h = (xs.length - 1) * q, lo = Math.floor(h), a = selectK(xs, lo);
    if (h === lo) return a;
    var b = Infinity;
    for (var i = lo + 1; i < xs.length; i++) if (xs[i] < b) b = xs[i];
    return a + (h - lo) * (b - a);
  };
  f.q = q;
  return f;
}

/* A 95% interval for the q-th quantile: the percentile bootstrap (BOOTS
 * resamples, seeded) under Q_BOOT_MAX values; at or over it, where a
 * thousand sorts of thousands of values are slow and the bootstrap and the
 * distribution-free interval agree, the order statistics at ranks
 * n*q -/+ 1.96 * sqrt(n*q*(1-q)) (the binomial interval for a quantile). */
var Q_BOOT_MAX = 1000;
function qCI(vals, q, seed) {
  if (vals.length < Q_CI_MIN_N) return null;
  if (vals.length < Q_BOOT_MAX) return bootCI(vals, seedOf(seed), BOOTS, qOf(q));
  var v = vals.slice().sort(function (a, b) { return a - b; }), n = v.length;
  var half = 1.96 * Math.sqrt(n * q * (1 - q));
  return [round2(v[Math.max(0, Math.floor(n * q - half) - 1)]), round2(v[Math.min(n - 1, Math.ceil(n * q + half) - 1)])];
}
function mean(xs) { return xs.length ? xs.reduce(function (s, x) { return s + x; }, 0) / xs.length : null; }

/* Thresholds per block off every counted offer: { th: {block: {n, p75, p90}},
 * of(o) -> {top25, top10} | null }. */
function tiersOf(offers) {
  var pool = (offers || []).filter(counted);
  var by = groupBy(pool, function (o) { return String(stratum(o)); });
  var th = Object.create(null);
  Object.keys(by).forEach(function (b) {
    var v = by[b].map(function (o) { return o.perHour; });
    if (v.length >= TIER_MIN_N) th[b] = { n: v.length, p75: round2(quantile(v, 0.75)), p90: round2(quantile(v, 0.9)) };
  });
  var memo = new Map();
  pool.forEach(function (o) {
    var t = th[String(stratum(o))];
    memo.set(o, t ? { top25: o.perHour >= t.p75, top10: o.perHour >= t.p90 } : null);
  });
  return { th: th, of: function (o) { return memo.get(o) || null; } };
}

/* P75 and P90 $/hr of a list, with intervals at Q_CI_MIN_N, and its shares
 * of top-25% and top-10% offers over the offers that have a tier. */
function topOf(list, tierOf, seed, noCi) {
  var vals = list.filter(function (o) { return typeof o.perHour === 'number' && isFinite(o.perHour); })
    .map(function (o) { return o.perHour; });
  var t = tierOf ? list.map(tierOf).filter(Boolean) : [];
  return { p75: vals.length ? round2(quantile(vals, 0.75)) : null, p90: vals.length ? round2(quantile(vals, 0.9)) : null,
           // Only the P90's interval is drawn; the P75's is not worked out.
           p75Ci: null, p90Ci: noCi ? null : qCI(vals, 0.9, 'q90' + seed),
           tiered: t.length,
           top25: share(t.filter(function (x) { return x.top25; }).length, t.length),
           top10: share(t.filter(function (x) { return x.top10; }).length, t.length),
           top10N: t.filter(function (x) { return x.top10; }).length };
}

/* TIMING A PRESSED DROP FROM THE GPS. A Drop press ('drop', 'chooser') can
 * come before the door or after it, so the first two passes left it out of
 * real time. The GPS log says where the car stood still: a stop is
 * stillRuns' (every fix within STOP_M of the stop's first, STOP_MIN_S or
 * more, no fix gap over SPELL_GAP_S), and it must begin after the order's
 * Took (a stop that began before it is the restaurant's or the car park's).
 * The press belongs to the stop that CONTAINS it; else the first that starts
 * within PRESS_AFTER_MIN after it (pressed on the way); else the last that
 * ends within PRESS_BEFORE_MIN before it (pressed late). The real end is
 * that stop's END — the car leaving the door. No such stop: still left out.
 * All four figures CHOSEN, NOT MEASURED: 100 m is a kerb and a front door
 * past a ±25 m fix, a minute is longer than a light, ten minutes is a long
 * last mile, five a slow press after. The run is labelled
 * `by: 'drop (gps-timed)'`, its press kept as `pressedAt` / `pressedBy`.
 *
 * ...BUT NOT A STOP THE CAR REACHED WITHOUT DRIVING THE ORDER (the 28 Oct
 * shift). Four Drops were pressed at or just past the pickup — one 18 s after
 * the GPS saw the car leave the restaurant, one in the middle of a 12.8 min
 * stop at the store — and the stop such a press falls in, or the next, is the
 * pickup's or the car park's: "timed" there, the order's real time is its
 * wait for the food. So a stop is the door only if the car drove SHORT_MILES
 * of the card's miles or more from the Took to the stop's end; under that,
 * by a log that covers the whole of it (notDriven), the press is left out as
 * one with no stop is, and counted `short`. An add-on is not held to it: its
 * card's miles are only what it added. */
function notDriven(t, hit, fixes) {
  if (!(typeof t.miles === 'number' && t.miles > 0) || t.addon === true) return false;
  var took = typeof t.tookAt === 'number' ? t.tookAt : null;
  if (took === null) return false;
  var inside = (fixes || []).filter(function (f) { return f[0] * 1000 >= took && f[0] * 1000 <= hit.to; });
  // The whole of it logged: a fix within STOP_MIN_S of the Took and of the
  // stop's end, and no two further apart (miles across a gap are a straight
  // line, the least the car drove, and prove nothing short).
  if (!inside.length || inside[0][0] * 1000 - took > STOP_MIN_S * 1000
      || hit.to - inside[inside.length - 1][0] * 1000 > STOP_MIN_S * 1000) return false;
  var mi = 0, anchor = inside[0];
  for (var i = 1; i < inside.length; i++) {
    if (inside[i][0] - inside[i - 1][0] > STOP_MIN_S) return false;
    // A step counts once the car is STOP_M from where it was last counted: a
    // parked receiver's wander is no driving (shift_report.py's JITTER_M, for
    // the same reason, at this file's stop radius).
    var d = MV.crowMiles({ lat: anchor[1], lon: anchor[2] }, { lat: inside[i][1], lon: inside[i][2] });
    if (d * 1609.344 >= STOP_M) { mi += d; anchor = inside[i]; }
  }
  return mi < SHORT_MILES * t.miles;
}

function timePresses(taken, fixes) {
  var stops = stillRuns(fixes || [], STOP_M, STOP_MIN_S, SPELL_GAP_S);
  var stats = { pressed: 0, timed: 0, inside: 0, early: 0, late: 0, none: 0, short: 0 };
  var out = (taken || []).map(function (t) {
    if (!t || (t.by !== 'drop' && t.by !== 'chooser') || typeof t.endedAt !== 'number') return t;
    stats.pressed += 1;
    var p = t.endedAt, took = typeof t.tookAt === 'number' ? t.tookAt : -Infinity;
    var ok = stops.filter(function (s) { return s.from > took; });
    var hit = null, how = null, i;
    for (i = 0; i < ok.length && !hit; i++) if (ok[i].from <= p && p <= ok[i].to) { hit = ok[i]; how = 'inside'; }
    for (i = 0; i < ok.length && !hit; i++) {
      if (ok[i].from > p && ok[i].from <= p + PRESS_AFTER_MIN * 60000) { hit = ok[i]; how = 'early'; }
    }
    for (i = ok.length - 1; i >= 0 && !hit; i--) {
      if (ok[i].to < p && ok[i].to >= p - PRESS_BEFORE_MIN * 60000) { hit = ok[i]; how = 'late'; }
    }
    if (!hit) { stats.none += 1; return t; }
    if (notDriven(t, hit, fixes)) { stats.short += 1; return t; }
    stats.timed += 1;
    stats[how] += 1;
    return Object.assign({}, t, { by: GPS_TIMED, pressedBy: t.by, pressedAt: p, endedAt: hit.to, timedHow: how });
  });
  return { taken: out, stats: stats };
}

/* DOES TOP-TIER SHARE DIFFER BY AREA, BEYOND CHANCE? Groups over the
 * ranking's floor (MIN_N offers with a tier, MIN_OUTINGS shift days). The
 * statistic is sum over groups of (O - E)^2 / n: O a group's top-10% offers,
 * E what the pooled share of its own blocks predicts for its offers. The
 * shuffle permutes the top-10% marks WITHIN each block (SHUFFLES times,
 * seeded), so every group keeps its hours and E stays put — the hour held,
 * as Advice.areas' strata hold it. Each group's score is the mean, over its
 * offers, of (top 10% ? 1 : 0) less the top-10% share of the OTHER ranked
 * groups in that offer's block (Advice's `matched`, for a share), with a 95%
 * bootstrap interval; colour only where the test beats chance AND the
 * interval is clear of zero. All hours only. */
function shareTest(rows, key, tierOf, opts) {
  opts = opts || {};
  var floor = typeof opts.minN === 'number' ? opts.minN : MIN_N;
  var shuffles = opts.shuffles || SHUFFLES;
  var pool = (rows || []).filter(function (o) { return counted(o) && key(o) && tierOf(o); });
  var by = groupBy(pool, key);
  var names = Object.keys(by).filter(function (k) {
    return by[k].length >= floor && A.outingsIn(by[k]) >= MIN_OUTINGS;
  }).sort();
  var thin = Object.keys(by).filter(function (k) { return names.indexOf(k) < 0; }).map(function (k) {
    return { name: k, n: by[k].length, outings: A.outingsIn(by[k]) };
  }).sort(function (a, b) { return b.n - a.n; });
  var items = [];
  names.forEach(function (k, gi) {
    by[k].forEach(function (o) { items.push({ g: gi, b: String(stratum(o)), y: tierOf(o).top10 ? 1 : 0 }); });
  });
  var G = names.length, ys = items.map(function (it) { return it.y; });
  var blocks = groupBy(items.map(function (it, i) { return { i: i, b: it.b }; }), function (x) { return x.b; });
  var rate = Object.create(null);
  Object.keys(blocks).forEach(function (b) {
    rate[b] = mean(blocks[b].map(function (x) { return ys[x.i]; }));
  });
  var E = new Array(G).fill(0), nG = new Array(G).fill(0);
  items.forEach(function (it) { E[it.g] += rate[it.b]; nG[it.g] += 1; });
  function stat(y) {
    var O = new Array(G).fill(0);
    for (var i = 0; i < items.length; i++) O[items[i].g] += y[i];
    var s2 = 0;
    for (var g = 0; g < G; g++) s2 += (O[g] - E[g]) * (O[g] - E[g]) / Math.max(1, nG[g]);
    return s2;
  }
  var p = null;
  var total = ys.reduce(function (a, b) { return a + b; }, 0);
  if (G >= 2 && total > 0 && total < ys.length) {
    var obs = stat(ys), r = rng(seedOf('share' + names.join('|'))), y = ys.slice(), hits = 0;
    var idx = Object.keys(blocks).map(function (b) { return blocks[b].map(function (x) { return x.i; }); });
    for (var s = 0; s < shuffles; s++) {
      idx.forEach(function (list) {
        for (var i = list.length - 1; i > 0; i--) {
          var j = Math.floor(r() * (i + 1)), a = list[i], c = list[j], tmp = y[a];
          y[a] = y[c]; y[c] = tmp;
        }
      });
      if (stat(y) >= obs - 1e-12) hits += 1;
    }
    p = Math.round(hits / shuffles * 10000) / 10000;
  }
  var significant = p !== null && p < ALPHA;
  // Each offer against the OTHER groups' share in its block.
  var inB = Object.create(null);
  items.forEach(function (it) {
    var c = inB[it.b] || (inB[it.b] = { k: new Array(G).fill(0), n: new Array(G).fill(0), K: 0, N: 0 });
    c.k[it.g] += it.y; c.n[it.g] += 1; c.K += it.y; c.N += 1;
  });
  var groups = names.map(function (k, gi) {
    var d = [];
    items.forEach(function (it) {
      if (it.g !== gi) return;
      var c = inB[it.b], N = c.N - c.n[gi];
      if (N > 0) d.push(it.y - (c.K - c.k[gi]) / N);
    });
    var top = topOf(by[k], tierOf, k, true);
    var sci = bootCI(d, seedOf('sh' + k), BOOTS, mean);
    var score = d.length ? round2(mean(d)) : null;
    var clear = sci ? (sci[0] > 0 ? 'above' : sci[1] < 0 ? 'below' : null) : null;
    return { name: k, n: by[k].length, outings: A.outingsIn(by[k]), top10: top.top10, top10N: top.top10N,
             top25: top.top25, expect: score === null ? null : round2(top.top10 - score), score: score, sci: sci,
             clear: clear, beats: !!(significant && clear) };
  }).sort(function (a, b) { return (b.score || 0) - (a.score || 0); });
  return { p: p, significant: significant, groups: groups, thin: thin, floor: floor, outings: MIN_OUTINGS,
           kept: items.length };
}

/* (a) Good offers by area: the rig's take (`go`) and the two top tiers,
 * counts and shares, beside the median, P75 and P90 $/hr. Areas with
 * DESC_MIN_N offers; the first row is every area together. */
function goodTable(rows, key, label, what, tierOf) {
  var pool = rows.filter(counted);
  var by = groupBy(pool, key);
  function row(name, list, seed) {
    var top = topOf(list, tierOf, seed);
    var go = list.filter(function (o) { return o.state === 'go'; }).length;
    var said = list.filter(function (o) { return typeof o.state === 'string' && o.state; }).length;
    return { name: name, n: list.length, go: go, goShare: share(go, said), tiered: top.tiered,
             top25: top.top25, top10N: top.top10N, top10: top.top10,
             top10Ci: wilson(top.top10N, top.tiered),
             median: med(list.map(function (o) { return o.perHour; })), p75: top.p75, p90: top.p90, p90Ci: top.p90Ci };
  }
  var out = Object.keys(by).filter(function (k) { return by[k].length >= DESC_MIN_N; })
    .map(function (k) { return row(label(k), by[k], 'g' + k); })
    .sort(function (a, b) { return (b.top10 || 0) - (a.top10 || 0) || b.n - a.n; });
  if (pool.length) out.unshift(row('every ' + what, pool, 'g*' + what));
  return { cols: [C('name', what, 't'), C('n', 'offers', 'n'), C('go', 'rig said take', 'n'), C('goShare', 'take share', '%'),
                  C('top25', 'top 25%', '%'), C('top10N', 'top 10% n', 'n'), C('top10', 'top 10%', '%'),
                  C('top10Ci', '95%', '%ci'), C('median', 'median $/hr', '$'), C('p75', 'P75 $/hr', '$'),
                  C('p90', 'P90 $/hr', '$'), C('p90Ci', '95%', '$ci')], rows: out };
}

/* (a) per hour of waiting and (b) the expected $/hr of working an area, off
 * the GPS spells (spellsOf), by area and three-hour block. Each spell carries
 * the offers counted while it lasted (their tiers), and the takes made while
 * waiting there (a Took inside it or TAKE_SLACK_MS after). Expected $/hr =
 * the pay of those takes ÷ (hours waited there + those takes' real hours),
 * over the takes with a real time only (realOf); a take with none is counted
 * and left out of both sides, so the figure reads low where they are many.
 * The counterfactual — every top-10% offer seen while waiting there, taken,
 * at its card's minutes — is OFFERED, NOT EARNED: it ignores that taking one
 * ends the wait, and the card's minutes are the app's. Floors: SPELL_MIN_N
 * spells on MIN_OUTINGS shift days, else the row gives its n only. */
function waitTable(spells, keyName, label, what) {
  var by = groupBy(spells.filter(function (s) { return s[keyName]; }),
                   function (s) { return s[keyName] + '\u0000' + A.blockOf(s.from); });
  var out = Object.keys(by).map(function (k) {
    var list = by[k], parts = k.split('\u0000');
    var days = Object.create(null);
    list.forEach(function (s) { days[outingOf(s.from)] = true; });
    var hours = list.reduce(function (sum, s) { return sum + (s.to - s.from) / 3.6e6; }, 0);
    function sum(f) { return list.reduce(function (a, s) { return a + f(s); }, 0); }
    var ok = list.length >= SPELL_MIN_N && Object.keys(days).length >= MIN_OUTINGS && hours > 0;
    var trips = [].concat.apply([], list.map(function (s) { return s.takes || []; }));
    var timed = trips.filter(function (t) { return t.mins !== null && typeof t.pay === 'number'; });
    var tripH = timed.reduce(function (a, t) { return a + t.mins / 60; }, 0);
    var pay = timed.reduce(function (a, t) { return a + t.pay; }, 0);
    var tPay = sum(function (s) { return s.top10Pay || 0; }), tMin = sum(function (s) { return s.top10Min || 0; });
    return { name: label(parts[0]), block: A.BLOCK_NAMES[Number(parts[1])], blockN: Number(parts[1]),
             n: list.length, days: Object.keys(days).length, hours: Math.round(hours * 10) / 10,
             goPerHour: ok ? round2(sum(function (s) { return s.goN || 0; }) / hours) : null,
             top25PerHour: ok ? round2(sum(function (s) { return s.top25N || 0; }) / hours) : null,
             top10PerHour: ok ? round2(sum(function (s) { return s.top10N || 0; }) / hours) : null,
             trips: trips.length, timed: timed.length,
             expected: ok ? round2(pay / (hours + tripH)) : null,
             ifTop10: ok && sum(function (s) { return s.top10N || 0; }) ? round2(tPay / (hours + tMin / 60)) : null };
  }).sort(function (a, b) { return (a.name < b.name ? -1 : a.name > b.name ? 1 : 0) || a.blockN - b.blockN; });
  out.forEach(function (r) { delete r.blockN; });
  return { cols: [C('name', what, 't'), C('block', 'hours', 't'), C('n', 'spells', 'n'), C('days', 'days', 'n'),
                  C('hours', 'hours waited', 'h'), C('goPerHour', 'takes said / hr waiting', 'r2'),
                  C('top25PerHour', 'top 25% / hr waiting', 'r2'), C('top10PerHour', 'top 10% / hr waiting', 'r2'),
                  C('trips', 'taken while there', 'n'), C('timed', 'of them timed', 'n'),
                  C('expected', 'expected $/hr working it', '$'),
                  C('ifTop10', 'if every top 10% taken (offered, card min)', '$')], rows: out };
}

/* (c) Dead miles after a drop: from each put-down at the door to the next
 * Took (any order), the GPS log's miles — the straight lines between its
 * fixes, one each SPELL_THIN_S, so a little under the road — plus that next
 * card's own printed drive to the pickup (Uber's `toPickupMiles`) where it
 * printed one. Censored (not counted): no next Took within DEAD_MAX_MIN, or
 * the log with a gap over SPELL_GAP_S in between (the rig off). The unpaid
 * share is the area's dead miles ÷ (dead + the delivered trips' card miles),
 * sums over its measured trips. By the dropoff's town and 2-mile cell,
 * counts only; DROP_MIN_N trips for a row, and a thinner cell is not named. */
function deadOf(trips, taken, byId, fixes) {
  var tooks = (taken || []).filter(function (t) { return t && typeof t.tookAt === 'number'; })
    .sort(function (a, b) { return a.tookAt - b.tookAt; });
  var ts = (fixes || []).map(function (f) { return f[0] * 1000; });
  function firstAt(ms) { var lo = 0, hi = ts.length; while (lo < hi) { var m = (lo + hi) >> 1; if (ts[m] < ms) lo = m + 1; else hi = m; } return lo; }
  trips.forEach(function (tr) {
    var next = tooks.filter(function (t) { return t.tookAt > tr.at; })[0];
    if (!next || next.tookAt - tr.at > DEAD_MAX_MIN * 60000) { tr.dead = { censored: true }; return; }
    var i = firstAt(tr.at), j = firstAt(next.tookAt + 1) - 1;
    if (j - i < 1 || ts[i] - tr.at > SPELL_GAP_S * 1000 || next.tookAt - ts[j] > SPELL_GAP_S * 1000) {
      tr.dead = { censored: true }; return;
    }
    var mi = 0;
    for (var k = i + 1; k <= j; k++) {
      if (ts[k] - ts[k - 1] > SPELL_GAP_S * 1000) { tr.dead = { censored: true }; return; }
      mi += MV.crowMiles({ lat: fixes[k - 1][1], lon: fixes[k - 1][2] }, { lat: fixes[k][1], lon: fixes[k][2] });
    }
    var nx = byId[next.id];
    var tp = nx && typeof nx.toPickupMiles === 'number' && isFinite(nx.toPickupMiles) ? nx.toPickupMiles : null;
    tr.dead = { censored: false, gpsMi: mi, toPickupMi: tp, deadMi: mi + (tp || 0),
                paidMi: tr.offer && typeof tr.offer.miles === 'number' ? tr.offer.miles : null };
  });
}

function deadTable(trips, keyName, label, what) {
  var by = groupBy(trips.filter(function (t) { return t[keyName] && t.dead; }), function (t) { return t[keyName]; });
  var thinCount = 0, thinTrips = 0;
  var out = Object.keys(by).map(function (k) {
    var list = by[k], got = list.filter(function (t) { return !t.dead.censored; });
    if (got.length < DROP_MIN_N) {
      if (keyName === 'cell') { thinCount += 1; thinTrips += list.length; return null; }
      return { name: label(k), trips: list.length, measured: got.length, gpsMi: null, toPickup: null, toPickupN: null,
               deadMi: null, unpaid: null };
    }
    var tp = got.filter(function (t) { return t.dead.toPickupMi !== null; }).map(function (t) { return t.dead.toPickupMi; });
    var paid = got.filter(function (t) { return t.dead.paidMi !== null; });
    var dSum = paid.reduce(function (a, t) { return a + t.dead.deadMi; }, 0);
    var pSum = paid.reduce(function (a, t) { return a + t.dead.paidMi; }, 0);
    var gm = got.map(function (t) { return t.dead.gpsMi; });
    return { name: label(k), trips: list.length, measured: got.length, gpsMi: med(gm), gpsCi: medCi(gm, 'dd' + k),
             toPickup: tp.length ? med(tp) : null, toPickupN: tp.length,
             deadMi: med(got.map(function (t) { return t.dead.deadMi; })),
             unpaid: dSum + pSum > 0 ? round2(dSum / (dSum + pSum)) : null };
  }).filter(Boolean).sort(function (a, b) { return b.trips - a.trips; });
  return { cols: [C('name', what, 't'), C('trips', 'trips', 'n'), C('measured', 'measured', 'n'),
                  C('gpsMi', 'GPS mi to next Took', 'mi'), C('gpsCi', '95%', 'mici'),
                  C('toPickup', 'next card\'s to-pickup mi', 'mi'), C('toPickupN', 'printed', 'n'),
                  C('deadMi', 'dead mi', 'mi'), C('unpaid', 'unpaid share', '%')], rows: out,
           thinCount: thinCount, thinTrips: thinTrips };
}

/* (d) Offer size, by card miles (SIZE_BANDS), per area: n, median and P90
 * $/hr, top-10% share, median $/mi (read only). A median needs DESC_MIN_N. */
function sizeTable(rows, key, label, what, tierOf) {
  var pool = rows.filter(function (o) { return counted(o) && typeof o.miles === 'number' && o.miles > 0; });
  var by = groupBy(pool, key);
  var out = [];
  function add(name, list, seed) {
    SIZE_BANDS.forEach(function (b) {
      var l = list.filter(function (o) { return o.miles >= b[0] && o.miles < b[1]; });
      if (!l.length) return;
      var ok = l.length >= DESC_MIN_N, top = topOf(l, tierOf, seed + b[2], true);
      out.push({ name: name, band: b[2], n: l.length, median: ok ? med(l.map(function (o) { return o.perHour; })) : null,
                 p90: ok ? top.p90 : null, top10: ok ? top.top10 : null,
                 ppm: ok ? med(l.map(payPerMile).filter(function (v) { return v !== null; })) : null });
    });
  }
  if (pool.length) add('every ' + what, pool, 'z*');
  Object.keys(by).filter(function (k) { return by[k].length >= DESC_MIN_N; })
    .sort(function (a, b) { return by[b].length - by[a].length; })
    .forEach(function (k) { add(label(k), by[k], 'z' + k); });
  return { cols: [C('name', what, 't'), C('band', 'size', 't'), C('n', 'offers', 'n'), C('median', 'median $/hr', '$'),
                  C('p90', 'P90 $/hr', '$'), C('top10', 'top 10%', '%'), C('ppm', 'median $/mi (read only)', '$')],
           rows: out };
}

/* The Best offers tab's plain-language lines, off the report. */
function bestLines(r) {
  var out = [], b = r.best || {};
  var th = Object.keys(b.thresholds || {}).sort(function (x, y) { return x - y; }).map(function (k) {
    var t = b.thresholds[k];
    return A.BLOCK_NAMES[Number(k)] + ': top 25% at $' + t.p75.toFixed(2) + '/hr, top 10% at $' + t.p90.toFixed(2)
      + '/hr (' + t.n + ' offers)';
  });
  out.push(th.length ? 'What "top" means, from every offer in its own three hours — ' + th.join('; ') + '.'
           : 'No three-hour block has the ' + TIER_MIN_N + ' offers a threshold needs.');
  var all = r.views.all;
  var every = all.best.goodTown.rows[0];
  if (every) {
    out.push('The rig said take to ' + every.go + ' of ' + every.n + ' offers (' + pct(every.go, every.n) + '); '
             + every.top10N + ' were top 10% for their hours.');
  }
  var waits = all.best.waitTown.rows.filter(function (x) { return x.top10PerHour !== null; })
    .sort(function (x, y) { return y.top10PerHour - x.top10PerHour; });
  if (!r.spells.gps) {
    out.push('No GPS spells, so nothing is "per hour of waiting" yet: no GPS log reached this report (--gps).');
  } else if (!waits.length) {
    out.push('No town has the ' + SPELL_MIN_N + ' spells on ' + MIN_OUTINGS + ' shift days a "per hour of waiting" '
             + 'figure needs yet (' + r.spells.n + ' spells in all).');
  } else {
    waits.slice(0, 3).forEach(function (w) {
      out.push('Waiting in ' + w.name + ' (' + w.block + '): ' + w.top10PerHour.toFixed(2) + ' top-10% offers and '
               + w.goPerHour.toFixed(2) + ' the rig said take, an hour (' + w.n + ' spells, ' + w.hours
               + ' h); working it paid ' + (w.expected === null ? '—' : '$' + w.expected.toFixed(2) + '/hr')
               + ' over ' + w.timed + ' timed takes.');
    });
  }
  [['town', 'Towns'], ['rest', 'Restaurants'], ['place', 'Places'], ['grid', r.gridMi + '-mile cells']].forEach(function (k) {
    var t = b.share && b.share[k[0]];
    if (!t) return;
    if (t.p === null) { out.push(k[1] + ': top-10% share not tested (' + t.groups.length + ' over the floor).'); return; }
    var beat = t.groups.filter(function (g) { return g.beats; });
    out.push(k[1] + ': top-10% share ' + (t.significant ? 'differs beyond chance' : 'is not distinguishable from chance')
             + ' (' + pText(t.p) + ', hours held).' + (beat.length ? ' ' + beat.map(function (g) {
               return shareName(r, k[0], g.name) + ' ' + (g.clear === 'above' ? 'more' : 'fewer') + ' ('
                 + Math.round(g.top10 * 100) + '% against ' + Math.round(g.expect * 100) + '% for the others in the same hours)';
             }).join('; ') + '.' : ''));
  });
  return out;
}

/* --- the Strategy tab's orders (7 Nov 2026) --------------------------------
 *
 * tools/strategy.js works out what $/hr to expect and what holding out paid
 * (the owner, 7 Nov: "being able to know what is a good $/hr and $/mi
 * metrics to expect would help decide which offers to take"); it never
 * decides whether an order was delivered. This report does, by its own rule,
 * and hands it the answer: each takenRuns run, its real minutes by realOf
 * (at the door by the GPS, the screen, a Drop the GPS finished, or a press
 * this report timed off the log) and nothing for any other end — the same
 * minutes the Your takes tab prints, so the two tabs cannot disagree about
 * an order.
 *
 * MILES. Where the order left a record (server.js orderRow, since 7 Nov) its
 * odometer (`drive.miles`: the server's own count, the end-of-shift report's
 * JITTER_M step) is the order's miles; for a day before the record, the GPS
 * log's fixes from the Took to the end (milesBetween). Only for an order
 * with real minutes, whose end is the door. Never a pin, never an `approx`
 * area, never DoorDash's map label: the record carries those, and none is
 * read here.
 *
 * A record is an order's when its offer is the run's and its Took is within
 * RECORD_MATCH_MS of the run's (the end-of-shift report's RECORD_MATCH_S:
 * both stamped by one handler milliseconds apart). A record that says the
 * clock stepped while the order was carried is no timing. */
var RECORD_MATCH_MS = 60000;

function recordFor(records, id, tookAt) {
  var best = null;
  (records || []).forEach(function (r) {
    if (!r || r.offer !== id || !r.times || typeof r.times.took !== 'number' || typeof tookAt !== 'number') return;
    var d = Math.abs(r.times.took - tookAt);
    if (d <= RECORD_MATCH_MS && (!best || d < best.d)) best = { d: d, r: r };
  });
  return best ? best.r : null;
}

/* The GPS log's miles from `from` to `to` (ms), off the thinned fixes
 * [[tSec, lat, lon]]: a step counts once the car is STOP_M from where it was
 * last counted (notDriven's rule, so a parked receiver's wander is no
 * driving), and null unless the log covers the whole of it — a fix within
 * SPELL_GAP_S of both ends and no two further apart. Straight lines between
 * fixes ten seconds apart: a little under the road. */
function milesBetween(fixes, from, to) {
  if (!fixes || !fixes.length || !(to > from)) return null;
  var inside = fixes.filter(function (f) { return f[0] * 1000 >= from && f[0] * 1000 <= to; });
  if (!inside.length || inside[0][0] * 1000 - from > SPELL_GAP_S * 1000
      || to - inside[inside.length - 1][0] * 1000 > SPELL_GAP_S * 1000) return null;
  var mi = 0, anchor = inside[0];
  for (var i = 1; i < inside.length; i++) {
    if (inside[i][0] - inside[i - 1][0] > SPELL_GAP_S) return null;
    var d = MV.crowMiles({ lat: anchor[1], lon: anchor[2] }, { lat: inside[i][1], lon: inside[i][2] });
    if (d * 1609.344 >= STOP_M) { mi += d; anchor = inside[i]; }
  }
  return mi;
}

function strategyOrders(taken, records, fixes, earnings) {
  return (taken || []).filter(function (t) { return t && typeof t.tookAt === 'number'; }).map(function (t) {
    var real = realOf(t);
    // An order this report could not time, timed by Uber's own minutes and
    // miles where its trip was matched (earnings.js uberTimingFor): labelled
    // so for the Strategy tab, never in place of the rig's own timing.
    var ub = real ? null : E.uberTimingFor(earnings, t.id, t.tookAt);
    // `by`, the drop row's: section 7 leaves a Took taken back out of what
    // was taken (strategy.js TAKEN_BACK), as earnings.js does.
    var by = typeof t.by === 'string' ? t.by : null;
    if (ub) {
      return { id: t.id, tookAt: t.tookAt, endedAt: typeof t.endedAt === 'number' ? t.endedAt : null, by: by,
               app: t.app || null, pay: t.pay, cardMinutes: t.minutes, cardMiles: t.miles,
               addon: t.addon === true, carried: t.carried, actualMinutes: ub.minutes,
               actualMiles: ub.miles, milesFrom: ub.miles !== null ? 'uber' : null, timedBy: 'uber',
               clockStepped: false };
    }
    var rec = recordFor(records, t.id, t.tookAt);
    var stepped = !!(rec && Array.isArray(rec.flags) && rec.flags.some(function (f) {
      return typeof f === 'string' && f.indexOf('the clock stepped') === 0;
    }));
    var miles = null, from = null;
    if (real) {
      var odo = rec && rec.drive && typeof rec.drive.miles === 'number' && isFinite(rec.drive.miles) ? rec.drive.miles : null;
      if (odo !== null) { miles = odo; from = 'odometer'; }
      else {
        var g = milesBetween(fixes, t.tookAt, t.endedAt);
        if (g !== null) { miles = g; from = 'log'; }
      }
    }
    return { id: t.id, tookAt: t.tookAt, endedAt: typeof t.endedAt === 'number' ? t.endedAt : null, by: by,
             app: t.app || null, pay: t.pay, cardMinutes: t.minutes, cardMiles: t.miles,
             addon: t.addon === true, carried: t.carried, actualMinutes: real ? real.mins : null,
             actualMiles: miles, milesFrom: from, clockStepped: stepped };
  });
}

/* --- the whole analysis, given placements --------------------------------
 *
 * `placed[i]` is offers[i]'s pickup answer { at, why, kind } (or undefined
 * for a row not asked about), `dropAt(t, o)` a taken trip's position or null. */
var VIEWS = ['all', 0, 1, 2, 3, 4, 5, 6, 7];

/* The line the driver judges against: the newest counted row's own target
 * not stamped after `now`, else 25 (journal.html render's and server.js
 * targetsOut's rule). */
function targetLine(counts, now) {
  var at = typeof now === 'number' && now > 0 ? now : Date.now();
  var sorted = counts.slice().sort(function (a, b) { return (a.at || 0) - (b.at || 0); });
  for (var i = sorted.length - 1; i >= 0; i--) {
    if ((sorted[i].at || 0) <= at) return typeof sorted[i].target === 'number' ? sorted[i].target : 25;
  }
  return 25;
}

/* The Targets tab's richer area lines, per hours view, off what the report
 * already worked out: the places, restaurants and 2-mile cells that beat
 * chance with their interval clear of zero (cells' `beats`), and, where the
 * GPS gave waiting spells, the town to wait in by top-10% offers an hour and
 * what working it paid (waitTable). Nothing new is tested here. */
function targetAreaLines(r) {
  var out = [];
  var views = ['all'].concat((r.targets.blocks || []).map(function (b) { return b.block; }));
  views.forEach(function (v) {
    var view = r.views[v];
    if (!view) return;
    var bits = [];
    [['place', 'places', view.place], ['rest', 'restaurants', view.rest], ['grid', r.gridMi + '-mile cells', view.grid]]
      .forEach(function (k) {
        var c = k[2];
        if (!c) return;
        var up = (c.groups || []).filter(function (g) { return g.beats && g.clear === 'above'; });
        if (c.p === null) bits.push(k[1] + ': not enough yet');
        else if (!c.significant) bits.push(k[1] + ': none beats chance (' + pText(c.p) + ')');
        else if (!up.length) bits.push(k[1] + ': differ beyond chance (' + pText(c.p) + '), none clearly better');
        else {
          bits.push(k[1] + ': ' + up.slice(0, 3).map(function (g) {
            return shareName(r, k[0], g.name) + ' (+$' + g.score.toFixed(2) + '/hr'
              + (g.top10 !== null && g.top10 !== undefined ? ', ' + Math.round(g.top10 * 100) + '% top-10%' : '') + ')';
          }).join('; '));
        }
      });
    var waits = (view.best && view.best.waitTown ? view.best.waitTown.rows : []).filter(function (w) {
      return w.top10PerHour !== null && (v === 'all' || w.block === A.BLOCK_NAMES[v]);
    }).sort(function (a, b) { return b.top10PerHour - a.top10PerHour; });
    if (!r.spells.gps) bits.push('waiting: no GPS log reached this report');
    else if (!waits.length) bits.push('waiting: no town has ' + SPELL_MIN_N + ' spells on ' + MIN_OUTINGS + ' shift days');
    else {
      bits.push('waiting: ' + waits.slice(0, 2).map(function (w) {
        return w.name + (v === 'all' ? ' (' + w.block + ')' : '') + ' ' + w.top10PerHour.toFixed(2)
          + ' top-10% offers an hour waiting, working it paid '
          + (w.expected === null ? '—' : '$' + w.expected.toFixed(2) + '/hr') + ' (' + w.n + ' spells)';
      }).join('; '));
    }
    out.push((v === 'all' ? 'All hours' : A.BLOCK_NAMES[v]) + ' — ' + bits.join('; ') + '.');
  });
  return out;
}

function analyse(offers, taken, placed, dropAt, opts) {
  opts = opts || {};
  // Filtered as pairs, so `placed` stays beside the row it answers.
  var pairs = (offers || []).map(function (o, i) { return [o, (placed || [])[i]]; })
    .filter(function (p) { return p[0] && typeof p[0] === 'object'; });
  offers = pairs.map(function (p) { return p[0]; });
  placed = pairs.map(function (p) { return p[1]; });
  var idx = new Map();
  offers.forEach(function (o, i) { idx.set(o, i); });
  function answer(o) {
    var r = placed[idx.get(o)];
    return r || { at: null, why: 'notext', kind: 'none' };
  }
  var pins = [];
  offers.forEach(function (o, i) {
    var r = placed[i];
    if (r && r.at) pins.push({ row: i, at: r.at, label: storeLabel(o.pickup), level: r.level, spread: r.spread || 0 });
  });
  var grouped = placesOf(pins);
  var cellBoxes = Object.create(null);
  function placeKey(o) { return grouped.byRow[idx.get(o)] || null; }
  function cellKey(o) {
    var r = answer(o);
    var c = gridOk(r) ? cellOf(r.at) : null;
    if (c) cellBoxes[c.id] = c;
    return c ? c.id : null;
  }
  function townKey(o) { return MV.townFor(o, A.area); }
  var names = restaurantNames(offers);
  function restKey(o) { return names.of(o); }
  function appKey(o) { return appOf(o); }
  var tiers = tiersOf(offers);
  var tierOf = tiers.of;

  var trips = tripsOf(offers, taken, dropAt);
  var runs = runsOf(taken);
  var byIdAll = Object.create(null);
  offers.forEach(function (o) { if (o && typeof o.id === 'string') byIdAll[o.id] = o; });
  if (opts.fixes) deadOf(trips, taken, byIdAll, opts.fixes);
  emptyOf(trips, taken, byIdAll, offers);
  // Where you waited (waitingLine): the cards that came with no order in the
  // car, by the car's own fix. Their cells join cellBoxes so the page names
  // them as it names every cell, by the cell's centre.
  var waiting = waitingLine(offers, taken, opts.cellTown, cellBoxes);
  var waitBy = new Map();
  waiting.forEach(function (w) { waitBy.set(w.o, w); });
  function waitCellKey(o) { var w = waitBy.get(o); return w ? w.cell : null; }
  function waitTownKey(o) { var w = waitBy.get(o); return w ? w.town : null; }
  // When & where: the same line, by the driver's weekday and block.
  var rulers = reportRulers(offers);
  var whenwhere = whenWhere(offers, waiting, rulers);
  // Offers around you: the same line drawn as dots, home left out (aroundYou).
  var around = aroundYou(offers, waiting, whenwhere);
  // The front page's when and where (round B; glanceOf).
  var glance = glanceOf(offers, waiting, rulers);
  var tookRuns = (taken || []).filter(function (t) { return t && typeof t.tookAt === 'number'; });
  // Spells parked with no order in the car (main reads them off the GPS
  // log): each to its 2-mile cell and, where the NucBox named one, the town
  // of that cell's centre; with the offers counted while there and the
  // minutes to the first the rig said take.
  var line = timelineOf(offers).filter(function (t) { return t.counted; });
  var spells = (opts.spells || []).map(function (sp) {
    var c = cellOf(sp);
    if (c) cellBoxes[c.id] = c;
    var during = line.filter(function (t) { return t.at >= sp.from && t.at <= sp.to; });
    var go = during.filter(function (t) { return t.go; })[0];
    var tops = during.map(function (t) { return { t: tierOf(t.o), o: t.o }; }).filter(function (x) { return x.t; });
    var t10 = tops.filter(function (x) { return x.t.top10; });
    var takes = tookRuns.filter(function (t) { return t.tookAt >= sp.from && t.tookAt <= sp.to + TAKE_SLACK_MS; })
      .map(function (t) { var rr = realOf(t); return { pay: t.pay, mins: rr ? rr.mins : null }; });
    return { from: sp.from, to: sp.to, cell: c ? c.id : null,
             town: c && opts.cellTown ? opts.cellTown[c.id] || null : null,
             seen: during.length, go: go ? (go.at - sp.from) / 60000 : null,
             goN: during.filter(function (t) { return t.go; }).length,
             top25N: tops.filter(function (x) { return x.t.top25; }).length, top10N: t10.length,
             top10Pay: t10.reduce(function (a, x) { return a + (typeof x.o.pay === 'number' ? x.o.pay : 0); }, 0),
             top10Min: t10.reduce(function (a, x) { return a + (typeof x.o.minutes === 'number' ? x.o.minutes : 0); }, 0),
             takes: takes };
  });
  function placeLabel(k) { return (grouped.places[k] && grouped.places[k].label) || k; }
  function cellLabel(k) {
    var c = cellBoxes[k];
    return c ? 'cell near ' + c.lat.toFixed(3) + ', ' + c.lon.toFixed(3) : k;
  }
  function same(k) { return k; }
  var views = {};
  var diffs = null;
  VIEWS.forEach(function (v) {
    var rows = v === 'all' ? offers : offers.filter(function (o) { return A.blockOf(o.at) === v; });
    var tv = v === 'all' ? trips : trips.filter(function (t) { return A.blockOf(t.at) === v; });
    var hold = v === 'all';
    views[v] = {
      name: v === 'all' ? 'all hours' : A.BLOCK_NAMES[v],
      offers: rows.filter(counted).length,
      place: cells(rows, placeKey, { hold: hold, minN: opts.minN, keepDiffs: hold, tierOf: tierOf }),
      town: cells(rows, townKey, { hold: hold, minN: opts.minN, keepDiffs: hold, tierOf: tierOf }),
      grid: cells(rows, cellKey, { hold: hold, minN: opts.minN, tierOf: tierOf }),
      dropTown: dropTable(tv, 'town', hold),
      dropGrid: dropTable(tv, 'cell', hold),
      waitedTown: cells(rows, waitTownKey, { hold: hold, minN: opts.minN, tierOf: tierOf }),
      waitedGrid: cells(rows, waitCellKey, { hold: hold, minN: opts.minN, tierOf: tierOf }),
    };
    views[v].rest = restaurantsTable(rows, { key: restKey, placeKey: placeKey, places: grouped.places,
                                             names: names, runs: runs, waits: opts.waits, hold: hold,
                                             minN: opts.minN, placeCells: views[v].place, tierOf: tierOf });
    if (hold) {
      diffs = { place: views[v].place.diffs, town: views[v].town.diffs };
      delete views[v].place.diffs;
      delete views[v].town.diffs;
    }
  });
  // A dropoff cell is named only where the all-hours table names it.
  var namedCells = Object.create(null);
  views.all.dropGrid.groups.forEach(function (g) { namedCells[g.name] = g.box || cellBoxes[g.name] || null; });
  var dropBoxes = Object.create(null);
  trips.forEach(function (t) { if (t.cell && t.cellBox) dropBoxes[t.cell] = t.cellBox; });
  // A dropoff cell is named in the dead-miles table only over its floor
  // (deadTable drops the thinner ones), by its 2-mile cell's centre.
  function deadCellName(k) {
    var c = dropBoxes[k];
    return c ? 'cell near ' + c.lat.toFixed(3) + ', ' + c.lon.toFixed(3) : 'a cell';
  }
  function dropCellName(k) {
    var c = namedCells[k];
    return c ? 'cell near ' + c.lat.toFixed(3) + ', ' + c.lon.toFixed(3) : 'a cell';
  }
  VIEWS.forEach(function (v) {
    var rows = v === 'all' ? offers : offers.filter(function (o) { return A.blockOf(o.at) === v; });
    var tv = v === 'all' ? trips : trips.filter(function (t) { return A.blockOf(t.at) === v; });
    var sv = v === 'all' ? spells : spells.filter(function (sp) { return A.blockOf(sp.from) === v; });
    var wv = v === 'all' ? waiting : waiting.filter(function (w) { return A.blockOf(w.at) === v; });
    views[v].more = {
      takesPlace: takesTable(rows, runs, placeKey, placeLabel, 'place'),
      takesTown: takesTable(rows, runs, townKey, same, 'town'),
      takesGrid: takesTable(rows, runs, cellKey, cellLabel, 'cell'),
      waits: waitsTable(rows, grouped.places, opts.waits, placeKey),
      strand: strandTable(rows, tv, placeKey, grouped.places, views[v].dropTown, namedCells, dropCellName),
      busyTown: busyTable(sv, 'town', same, 'town'),
      busyGrid: busyTable(sv, 'cell', cellLabel, 'cell'),
      appsPlace: appsTable(rows, runs, placeKey, placeLabel, 'place'),
      appsTown: appsTable(rows, runs, townKey, same, 'town'),
      appsGrid: appsTable(rows, runs, cellKey, cellLabel, 'cell'),
      ppmPlace: ppmTable(rows, placeKey, placeLabel, 'place'),
      ppmTown: ppmTable(rows, townKey, same, 'town'),
      ppmGrid: ppmTable(rows, cellKey, cellLabel, 'cell'),
      stack: stackTable(rows, placeKey, placeLabel),
      waitedAreaTown: waitedTable(wv, 'town', same, 'town where the car was'),
      waitedAreaGrid: waitedTable(wv, 'cell', cellLabel, 'cell where the car was'),
      emptyTown: emptyTable(tv, 'town', same, 'dropoff town'),
    };
    function restLabel(k) { return names.labels[k] || k; }
    views[v].best = {
      goodTown: goodTable(rows, townKey, same, 'town', tierOf),
      goodGrid: goodTable(rows, cellKey, cellLabel, 'cell', tierOf),
      goodRest: goodTable(rows, restKey, restLabel, 'restaurant', tierOf),
      goodApp: goodTable(rows, appKey, same, 'app', tierOf),
      waitTown: waitTable(sv, 'town', same, 'town'),
      waitGrid: waitTable(sv, 'cell', cellLabel, 'cell'),
      deadTown: deadTable(tv, 'town', same, 'dropoff town'),
      deadGrid: deadTable(tv, 'cell', deadCellName, 'dropoff cell'),
      sizeTown: sizeTable(rows, townKey, same, 'town', tierOf),
      sizeApp: sizeTable(rows, appKey, same, 'app', tierOf),
      sizeRest: sizeTable(rows, restKey, restLabel, 'restaurant', tierOf),
    };
  });
  // Top-tier share, all hours, hours held (shareTest).
  var shareTests = { town: shareTest(offers, townKey, tierOf, { minN: opts.minN }),
                     rest: shareTest(offers, restKey, tierOf, { minN: opts.minN }),
                     place: shareTest(offers, placeKey, tierOf, { minN: opts.minN }),
                     grid: shareTest(offers, cellKey, tierOf, { minN: opts.minN }) };
  var quiet = { place: quietTable(offers, placeKey, placeLabel, diffs.place, 'place'),
                town: quietTable(offers, townKey, same, diffs.town, 'town') };
  var trend = { place: trendTable(diffs.place, placeLabel, 'place'),
                town: trendTable(diffs.town, same, 'town') };
  var cov = coverage(offers, answer);
  var counts = offers.filter(counted);
  // The Targets tab's headline: advice.js's own computation, the one the
  // offers page shows (server.js targetsOut), over this report's offers and
  // takes, with the card's town as the rig's (townKey) and the report's real
  // time (realOf, which also counts a Drop it timed off the GPS).
  var targets = A.targets(offers, taken, {
    target: targetLine(counts, opts.now), key: townKey, shuffles: SHUFFLES,
    townFloor: typeof opts.minN === 'number' ? opts.minN : MIN_N,
    isTimed: function (t) { return realOf(t) !== null; },
    timedSaid: 'put down at the door by the GPS or the app\'s screen, a Drop the GPS finished, or a Drop this '
      + 'report timed off the GPS log'
  });
  // The Strategy tab: tools/strategy.js over every row (an untrusted card
  // still says the rig was on), this report's takes as its own realOf timed
  // them, the card's town as the area (townKey, as every town table here),
  // and the driver's line beside the curve.
  var strategyIn = strategyOrders(taken, opts.records, opts.fixes, opts.earnings);
  // ...and, where the server has them, the trips read off the app's own
  // earnings screenshots and matched to orders (/api/earnings): the card
  // against what was paid, under the curve.
  var strategy = S.analyse({ offers: offers, orders: strategyIn, areaOf: townKey, appOf: appOf,
                             // One ruler for section 7 and When & where.
                             rulers: rulers.byTop,
                             target: targetLine(counts, opts.now), boots: opts.boots,
                             earnings: Array.isArray(opts.earnings) ? opts.earnings : undefined,
                             // The Gold card's goal and Uber's own figures,
                             // as the offers page saved them (/api/gold).
                             gold: opts.gold || undefined });
  strategy.miles = { odometer: strategyIn.filter(function (o) { return o.milesFrom === 'odometer'; }).length,
                     uber: strategyIn.filter(function (o) { return o.timedBy === 'uber'; }).length,
                     log: strategyIn.filter(function (o) { return o.milesFrom === 'log'; }).length,
                     records: (opts.records || []).length, gps: !!opts.fixes };
  var times = counts.map(function (o) { return o.at; }).filter(isFinite);
  return {
    made: opts.now || Date.now(),
    span: times.length ? [Math.min.apply(null, times), Math.max.apply(null, times)] : null,
    outings: A.outingsIn(counts),
    minN: typeof opts.minN === 'number' ? opts.minN : MIN_N,
    dropMinN: DROP_MIN_N, minOutings: MIN_OUTINGS, alpha: ALPHA, shuffles: SHUFFLES,
    boots: BOOTS, gridMi: GRID_MI, nextGapMin: NEXT_GAP_MIN,
    taken: (taken || []).length,
    trips: {
      n: trips.length,
      gps: trips.filter(function (t) { return t.how === 'gps'; }).length,
      pin: trips.filter(function (t) { return t.how === 'pin'; }).length,
      town: trips.filter(function (t) { return t.town; }).length,
      ended: trips.filter(function (t) { return t.next.censored; }).length,
      cardFix: trips.filter(function (t) { return t.how === 'card fix'; }).length,
      empty: trips.filter(function (t) { return t.empty && !t.empty.censored; }).length,
    },
    waited: { cards: waiting.length, fixed: waiting.filter(function (w) { return w.fix; }).length,
              towns: waiting.filter(function (w) { return w.town; }).length,
              creditMaxMin: CREDIT_MAX_MIN, movedMi: MOVED_MI, cardFixAfterMin: CARD_FIX_AFTER_MIN,
              density: fixDensity(offers) },
    coverage: cov,
    quiet: quiet, trend: trend,
    takes: { taken: (taken || []).length, onCounted: offers.filter(function (o) { return counted(o) && runs[o.id]; }).length,
             timed: (taken || []).filter(function (t) { return realOf(t); }).length,
             gpsTimed: (taken || []).filter(function (t) { return t && t.by === GPS_TIMED; }).length,
             pressed: (taken || []).filter(function (t) {
               return t && (t.by === 'drop' || t.by === 'chooser' || t.by === GPS_TIMED);
             }).length },
    spells: { n: spells.length, hours: Math.round(spells.reduce(function (s2, sp) { return s2 + (sp.to - sp.from); }, 0) / 3.6e5) / 10,
              towns: spells.filter(function (sp) { return sp.town; }).length, gps: !!opts.spells },
    waitsOnRecord: (opts.waits || []).length, waitsFrom: opts.waitsFrom || null,
    descMinN: DESC_MIN_N, realMedN: REAL_MED_N, quietDays: QUIET_DAYS, spellM: SPELL_M,
    spellMinS: SPELL_MIN_S, spellGapS: SPELL_GAP_S, spellMinN: SPELL_MIN_N,
    best: { thresholds: tiers.th, share: shareTests, tierMinN: TIER_MIN_N, spellMinN: SPELL_MIN_N,
            takeSlackMin: TAKE_SLACK_MS / 60000, deadMaxMin: DEAD_MAX_MIN,
            dead: { gps: !!opts.fixes, n: trips.filter(function (t) { return t.dead && !t.dead.censored; }).length },
            presses: opts.presses || null, stopM: STOP_M, stopMinS: STOP_MIN_S, pressAfterMin: PRESS_AFTER_MIN,
            shortMiles: SHORT_MILES,
            pressBeforeMin: PRESS_BEFORE_MIN, placeApproxMi: PLACE_APPROX_MI, areaMi: MV.AREA_MI,
            region: opts.region ? { box: opts.region.box, fixes: opts.region.fixes, marginMi: opts.region.marginMi,
                                    miles: opts.region.disc.miles } : null,
            streets: opts.streetsSaid || null, road: opts.roadSaid || null },
    targets: targets,
    whenwhere: whenwhere,
    around: around,
    glance: glance,
    strategy: strategy,
    places: grouped.places,
    restNames: names.labels,
    cells: cellBoxes,
    views: views,
    source: opts.source || null,
  };
}

/* --- the one-line verdicts ------------------------------------------------ */

function pText(p) {
  if (p === null || p === undefined) return 'not tested (fewer than two cells clear the floor)';
  return p === 0 ? 'p < ' + (1 / SHUFFLES).toFixed(4) : 'p = ' + p.toFixed(3);
}

function testLine(what, c) {
  if (c.p === null) {
    return what + ': not tested — ' + c.groups.length + ' cell(s) clear the floor of ' + c.floor
      + ' offers on ' + c.outings + ' outings; ' + c.thin.length + ' under it.';
  }
  return what + ': ' + c.groups.length + ' cells, ' + c.kept + ' offers, '
    + (c.held ? 'hours held still, ' : '') + pText(c.p)
    + (c.held && c.rawP !== null ? ' (' + pText(c.rawP) + ' with the hour left in)' : '')
    + ' — ' + (c.significant ? 'beats chance' : 'NOT distinguishable from chance') + '.';
}

function summary(r) {
  var out = [];
  var cv = r.coverage, all = r.views.all;
  out.push('Offers counted: ' + cv.offers + ' over ' + r.outings + ' shift days'
           + (r.source && r.source.truncated ? '  (THE SERVER CUT THE WINDOW: ' + r.source.count
              + ' of ' + r.source.total + ' — use --since)' : ''));
  out.push('Pickups placed: ' + cv.all.placed.n + ' of ' + (cv.all.placed.n + cv.all.unplaced.n)
           + ' (' + pct(cv.all.placed.n, cv.all.placed.n + cv.all.unplaced.n) + ')');
  (cv.levels || []).forEach(function (l) {
    out.push('  placed at ' + l.level + ' level' + (l.point ? '' : ' (approximate)') + ': ' + l.n
             + (l.region ? ' (' + l.region + ' in the region box, no fix)' : '')
             + (l.refused ? '  [stood in for: ' + l.refused + ']' : ''));
  });
  cv.why.forEach(function (w) { out.push('  unplaced, ' + w.why + ': ' + w.n); });
  if (cv.all.gapPerHour !== null) {
    out.push('Placed pay $' + cv.all.placed.perHour.toFixed(2) + '/hr, unplaced $'
             + cv.all.unplaced.perHour.toFixed(2) + '/hr: the map leaves out offers paying '
             + (cv.all.gapPerHour >= 0 ? '$' + cv.all.gapPerHour.toFixed(2) + '/hr less'
                : '$' + (-cv.all.gapPerHour).toFixed(2) + '/hr more')
             + ' (' + pText(cv.all.p) + ')');
  }
  if (cv.points && cv.points.gapPerHour !== null && cv.levels && cv.levels.some(function (l) { return !l.point; })) {
    out.push('  points only (door, corner, name) against the unplaced: $' + cv.points.placed.perHour.toFixed(2) + '/hr vs $'
             + cv.points.unplaced.perHour.toFixed(2) + '/hr (' + pText(cv.points.p) + ')');
  }
  if (r.best) {
    var thr = Object.keys(r.best.thresholds).sort(function (a, b) { return a - b; });
    out.push('Top-tier thresholds (every offer in its own 3-hour block; ' + TIER_MIN_N + ' offers for one):');
    thr.forEach(function (k) {
      var t = r.best.thresholds[k];
      out.push('  ' + A.BLOCK_NAMES[Number(k)] + ': top 25% >= $' + t.p75.toFixed(2) + '/hr, top 10% >= $'
               + t.p90.toFixed(2) + '/hr  (n=' + t.n + ')');
    });
    if (!thr.length) out.push('  none: no block has ' + TIER_MIN_N + ' offers');
    [['town', 'Towns'], ['rest', 'Restaurants'], ['place', 'Places'], ['grid', r.gridMi + '-mile grid']].forEach(function (k) {
      var t = r.best.share[k[0]];
      out.push('Top-10% share, ' + k[1] + ': ' + (t.p === null ? 'not tested (' + t.groups.length + ' over the floor)'
               : t.groups.length + ' groups, hours held, ' + pText(t.p) + ' — '
                 + (t.significant ? 'beats chance' : 'NOT distinguishable from chance')));
      t.groups.filter(function (g) { return g.beats; }).forEach(function (g) {
        out.push('  ' + shareName(r, k[0], g.name) + '  ' + Math.round(g.top10 * 100) + '% top 10% vs '
                 + Math.round(g.expect * 100) + '% for the others, same hours [' + (g.sci[0] * 100).toFixed(1) + ', '
                 + (g.sci[1] * 100).toFixed(1) + ' points], n=' + g.n);
      });
    });
  }
  if (r.strategy) {
    out.push('Strategy (descriptive; the Strategy tab):');
    r.strategy.lines.forEach(function (l) { out.push('  ' + l); });
  }
  out.push(testLine('Places', all.place));
  if (all.rest) {
    out.push('Restaurants, by the name on the card, placed or not: ' + all.rest.groups.length + ' ranked of '
             + all.rest.names + ' names (' + all.rest.thin.length + ' too few), ' + all.rest.named + ' offers named, '
             + all.rest.placed + ' of them placed; ' + all.rest.noName + ' pickups printed no name (a door or a street)');
    out.push(testLine('Restaurants', all.rest));
  }
  out.push(testLine('Towns', all.town));
  out.push(testLine(r.gridMi + '-mile grid', all.grid));
  out.push(testLine('Wait after a drop, by town', all.dropTown));
  if (r.takes) {
    out.push('Taken: ' + r.takes.taken + ' orders, ' + r.takes.timed + ' timed at the door (GPS, screen, or a press '
             + 'the GPS log timed), ' + r.takes.pressed + ' put down by a press: ' + r.takes.gpsTimed
             + ' of them GPS-timed, ' + (r.takes.pressed - r.takes.gpsTimed) + ' not timed');
  }
  if (r.spells && r.spells.gps) out.push('Spells parked with no order in the car: ' + r.spells.n + ', ' + r.spells.hours + ' h');
  ['place', 'town'].forEach(function (k) {
    var q = r.quiet && r.quiet[k];
    (q && q.rows || []).filter(function (x) { return x.flag; }).forEach(function (x) {
      out.push('Gone quiet (' + k + '): ' + x.name + ' — ' + x.flag + ', last offer ' + x.last);
    });
  });
  ['place', 'rest', 'town', 'grid'].forEach(function (k) {
    var beat = all[k] ? all[k].groups.filter(function (g) { return g.beats; }) : [];
    if (!beat.length) return;
    out.push('Clear of the rest (' + (k === 'rest' ? 'restaurant' : k) + '):');
    beat.forEach(function (g) {
      out.push('  ' + labelOf(r, k, g.name) + '  ' + (g.score >= 0 ? '+' : '') + g.score.toFixed(2)
               + ' $/hr vs same hours elsewhere [' + g.sci[0].toFixed(2) + ', ' + g.sci[1].toFixed(2)
               + '], n=' + g.n);
    });
  });
  return out.join('\n');
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

/* --- CSV ----------------------------------------------------------------- */

function csvCell(v) {
  if (v === null || v === undefined) return '';
  var s = String(v);
  return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}

function csvOf(r, kind) {
  var head = ['hours', kind === 'grid' ? 'cell' : kind, 'lat', 'lon', 'n', 'outings',
              'median_per_hour', 'median_lo', 'median_hi', 'score_vs_same_hours', 'score_lo',
              'score_hi', 'median_pay', 'share_rig_said_take', 'clear', 'beats_chance',
              'grouping_p', 'ranked', 'p75_per_hour', 'p90_per_hour', 'p90_lo', 'p90_hi', 'top25_share',
              'top10_share'];
  var lines = [head.join(',')];
  VIEWS.forEach(function (v) {
    var c = r.views[v][kind];
    c.groups.forEach(function (g) {
      var at = kind === 'place' ? r.places[g.name] : kind === 'grid' ? r.cells[g.name] : null;
      lines.push([r.views[v].name, labelOf(r, kind, g.name), at && at.lat, at && at.lon, g.n,
                  g.outings, g.median, g.ci && g.ci[0], g.ci && g.ci[1], g.score,
                  g.sci && g.sci[0], g.sci && g.sci[1], g.pay, g.take, g.clear,
                  g.beats ? 'yes' : 'no', c.p, 'yes', g.p75, g.p90, g.p90Ci && g.p90Ci[0], g.p90Ci && g.p90Ci[1],
                  g.top25, g.top10].map(csvCell).join(','));
    });
    c.thin.forEach(function (t) {
      var at = kind === 'place' ? r.places[t.name] : kind === 'grid' ? r.cells[t.name] : null;
      lines.push([r.views[v].name, labelOf(r, kind, t.name), at && at.lat, at && at.lon, t.n,
                  t.outings, '', '', '', '', '', '', '', '', '', 'too few', c.p, 'no', '', '', '', '', '', '']
                 .map(csvCell).join(','));
    });
  });
  return lines.join('\n') + '\n';
}

function dropCsv(r, kind) {
  var head = ['hours', kind === 'dropGrid' ? 'cell' : 'town', 'trips', 'measured', 'ended_unmeasured',
              'median_wait_min', 'wait_lo', 'wait_hi', 'wait_vs_same_hours', 'vs_lo', 'vs_hi',
              'next_take_per_hour', 'next_take_pay', 'grouping_p'];
  var lines = [head.join(',')];
  VIEWS.forEach(function (v) {
    var c = r.views[v][kind];
    c.groups.forEach(function (g) {
      var name = kind === 'dropGrid' && g.box
        ? 'cell near ' + g.box.lat.toFixed(3) + ', ' + g.box.lon.toFixed(3) : g.name;
      lines.push([r.views[v].name, name, g.trips, g.n, g.ended, g.median, g.ci && g.ci[0],
                  g.ci && g.ci[1], g.score, g.sci && g.sci[0], g.sci && g.sci[1], g.nextPerHour,
                  g.nextPay, c.p].map(csvCell).join(','));
    });
    c.thin.forEach(function (t) {
      lines.push([r.views[v].name, t.name, '', t.n, '', 'too few', '', '', '', '', '', '', '', c.p]
                 .map(csvCell).join(','));
    });
  });
  return lines.join('\n') + '\n';
}

/* One of the second pass's tables as CSV: its raw values, an interval as
 * two columns, a trend's weeks as one line each; per hours view when `pick`
 * takes a view, else once. */
function tableCsv(r, pick, perView) {
  var lines = [], head = null;
  function emit(t, hours) {
    if (!t || !t.cols || !t.cols.length) return;
    var spark = t.cols.filter(function (c) { return c.f === 'spark'; })[0];
    var flat = t.cols.filter(function (c) { return c.f !== 'spark'; });
    if (!head) {
      head = (perView ? ['hours'] : []).concat([].concat.apply([], flat.map(function (c) {
        return /ci$/.test(c.f) ? [c.k + '_lo', c.k + '_hi'] : [c.k];
      }))).concat(spark ? ['week', 'week_n', 'week_score', 'week_lo', 'week_hi'] : []);
      lines.push(head.join(','));
    }
    t.rows.forEach(function (row) {
      var cellsOut = (perView ? [hours] : []).concat([].concat.apply([], flat.map(function (c) {
        var v = row[c.k];
        return /ci$/.test(c.f) ? [v ? v[0] : null, v ? v[1] : null] : [v];
      })));
      if (!spark) { lines.push(cellsOut.map(csvCell).join(',')); return; }
      (row[spark.k] || []).forEach(function (w) {
        lines.push(cellsOut.concat([w.w, w.n, w.score, w.ci && w.ci[0], w.ci && w.ci[1]]).map(csvCell).join(','));
      });
    });
  }
  if (perView) VIEWS.forEach(function (v) { emit(pick(r.views[v]), r.views[v].name); });
  else emit(pick(r), null);
  return (lines.length ? lines.join('\n') : '') + '\n';
}

// The second pass's CSVs: file name -> [pick, per hours view].
var MORE_CSVS = {
  'takes_places.csv': [function (v) { return v.more.takesPlace; }, true],
  'takes_towns.csv': [function (v) { return v.more.takesTown; }, true],
  'takes_grid.csv': [function (v) { return v.more.takesGrid; }, true],
  'waits.csv': [function (v) { return v.more.waits; }, true],
  'strand.csv': [function (v) { return v.more.strand; }, true],
  'busy_towns.csv': [function (v) { return v.more.busyTown; }, true],
  'busy_grid.csv': [function (v) { return v.more.busyGrid; }, true],
  'apps_places.csv': [function (v) { return v.more.appsPlace; }, true],
  'apps_towns.csv': [function (v) { return v.more.appsTown; }, true],
  'apps_grid.csv': [function (v) { return v.more.appsGrid; }, true],
  'per_mile_places.csv': [function (v) { return v.more.ppmPlace; }, true],
  'per_mile_towns.csv': [function (v) { return v.more.ppmTown; }, true],
  'per_mile_grid.csv': [function (v) { return v.more.ppmGrid; }, true],
  'stacking.csv': [function (v) { return v.more.stack; }, true],
  'quiet_places.csv': [function (r) { return r.quiet.place; }, false],
  'quiet_towns.csv': [function (r) { return r.quiet.town; }, false],
  'trend_places.csv': [function (r) { return r.trend.place; }, false],
  'trend_towns.csv': [function (r) { return r.trend.town; }, false],
  'good_towns.csv': [function (v) { return v.best.goodTown; }, true],
  'good_grid.csv': [function (v) { return v.best.goodGrid; }, true],
  'good_restaurants.csv': [function (v) { return v.best.goodRest; }, true],
  'good_apps.csv': [function (v) { return v.best.goodApp; }, true],
  'waiting_towns.csv': [function (v) { return v.best.waitTown; }, true],
  'waiting_grid.csv': [function (v) { return v.best.waitGrid; }, true],
  'dead_miles_towns.csv': [function (v) { return v.best.deadTown; }, true],
  'dead_miles_grid.csv': [function (v) { return v.best.deadGrid; }, true],
  'size_towns.csv': [function (v) { return v.best.sizeTown; }, true],
  'size_apps.csv': [function (v) { return v.best.sizeApp; }, true],
  'size_restaurants.csv': [function (v) { return v.best.sizeRest; }, true],
  'waited_towns.csv': [function (v) { return v.more.waitedAreaTown; }, true],
  'waited_grid.csv': [function (v) { return v.more.waitedAreaGrid; }, true],
  'empty_driving.csv': [function (v) { return v.more.emptyTown; }, true],
};

/* The top-10% share tests (all hours, hours held), one CSV, a line a group. */
function shareCsv(r) {
  var lines = ['grouping,name,ranked,n,outings,top10_share,top25_share,others_same_hours,score,score_lo,score_hi,clear,beats_chance,grouping_p'];
  ['town', 'rest', 'place', 'grid'].forEach(function (k) {
    var t = r.best.share[k];
    t.groups.forEach(function (g) {
      lines.push([k, shareName(r, k, g.name), 'yes', g.n, g.outings, g.top10, g.top25, g.expect, g.score,
                  g.sci && g.sci[0], g.sci && g.sci[1], g.clear, g.beats ? 'yes' : 'no', t.p].map(csvCell).join(','));
    });
    t.thin.forEach(function (g) {
      lines.push([k, shareName(r, k, g.name), 'too few', g.n, g.outings, '', '', '', '', '', '', '', '', t.p]
        .map(csvCell).join(','));
    });
  });
  return lines.join('\n') + '\n';
}

function levelsCsv(r) {
  var lines = ['level,point,placed,median_per_hour,in_region_box,stood_in_for'];
  (r.coverage.levels || []).forEach(function (l) {
    lines.push([l.level, l.point ? 'yes' : 'no', l.n, l.perHour, l.region, l.refused].map(csvCell).join(','));
  });
  return lines.join('\n') + '\n';
}

/* The Restaurants tab as two CSVs: a line per restaurant per hours view, and
 * a line per placed branch (and the not-placed rest) per hours view. */
var REST_COLS = ['n', 'outings', 'score', 'score_lo', 'score_hi', 'median_per_hour', 'median_lo', 'median_hi',
                 'median_pay', 'median_per_mile', 'taken', 'take_rate', 'take_lo', 'take_hi', 'timed_at_door',
                 'real_per_hour', 'real_lo', 'real_hi', 'real_minus_card_min', 'wait_min', 'waits', 'wait_not_joined',
                 'addon_share', 'stacked_share', 'uber_n', 'uber_per_hour', 'doordash_n', 'doordash_per_hour',
                 'gps_timed', 'p75_per_hour', 'p90_per_hour', 'top10_share'];
function restVals(g) {
  function lo(c) { return c ? c[0] : null; }
  function hi(c) { return c ? c[1] : null; }
  return [g.n, g.outings, g.score, lo(g.sci), hi(g.sci), g.median !== undefined ? g.median : g.perHour,
          lo(g.ci), hi(g.ci), g.pay, g.ppm, g.taken, g.take, lo(g.takeCi), hi(g.takeCi), g.timed,
          g.realPerHour, lo(g.realCi), hi(g.realCi), g.cardVsReal, g.wait, g.waitN, g.waitWhy,
          g.addon, g.stacked, g.uberN, g.uberPerHour, g.doordashN, g.doordashPerHour, g.gpsTimed,
          g.p75, g.p90, g.top10];
}
function restCsv(r) {
  var lines = [['hours', 'restaurant', 'ranked', 'chain', 'placed_offers', 'placed_branches'].concat(REST_COLS)
    .concat(['clear', 'beats_chance', 'grouping_p']).join(',')];
  VIEWS.forEach(function (v) {
    var c = r.views[v].rest;
    c.groups.concat(c.thin).forEach(function (g) {
      lines.push([r.views[v].name, g.label, g.ranked ? 'yes' : 'too few', g.chain ? 'yes' : 'no', g.placedN, g.branchN]
        .concat(g.ranked ? restVals(g) : restVals(Object.assign({}, g, { median: g.perHour })))
        .concat([g.clear, g.beats ? 'yes' : 'no', c.p]).map(csvCell).join(','));
    });
  });
  return lines.join('\n') + '\n';
}
function restBranchCsv(r) {
  var lines = [['hours', 'restaurant', 'branch', 'lat', 'lon', 'place_score', 'place_score_lo', 'place_score_hi',
                'place_beats_chance'].concat(REST_COLS.filter(function (k) { return !/^score/.test(k); }))
    .join(',')];
  VIEWS.forEach(function (v) {
    var c = r.views[v].rest;
    c.groups.concat(c.thin).forEach(function (g) {
      g.branches.forEach(function (b) {
        var vals = restVals(Object.assign({}, b, { median: b.perHour, ci: null, score: null, sci: null }));
        vals.splice(2, 3);
        lines.push([r.views[v].name, g.label, b.name, b.lat, b.lon, b.placeScore, b.placeSci && b.placeSci[0],
                    b.placeSci && b.placeSci[1], b.unplaced ? '' : b.placeBeats ? 'yes' : 'no'].concat(vals)
          .map(csvCell).join(','));
      });
    });
  });
  return lines.join('\n') + '\n';
}

/* The Strategy tab's curves as one CSV: a line per threshold, $/hr then
 * $/mi (the second for reading only, as the tab says). */
function strategyCsv(r) {
  var s = r.strategy;
  var head = ['on', 'line', 'offers_seen_free', 'per_free_hour', 'mean_pay', 'mean_card_minutes', 'actual_over_card',
              'ratio_from', 'gross_per_hour_on_shift', 'ci_lo', 'ci_hi', 'net_per_hour_on_shift', 'thin'];
  var lines = [head.join(',')];
  [['per_hour', s.curve.points], ['per_mile_reading_only', s.curveMile.points]].forEach(function (k) {
    k[1].forEach(function (p) {
      lines.push([k[0], p.T, p.n, p.perFreeHour, p.pay, p.cardMin, p.ratio,
                  p.ratioFrom === 'carried' ? 'carried from ' + p.ratioAt : p.ratioFrom, p.gross,
                  p.ci ? p.ci[0] : null, p.ci ? p.ci[1] : null, p.net, p.thin ? 'thin' : ''].map(csvCell).join(','));
    });
  });
  return lines.join('\n') + '\n';
}

function coverageCsv(r) {
  var lines = ['day,placed,unplaced,placed_per_hour,unplaced_per_hour,gap_per_hour,placed_pay,unplaced_pay,gap_pay,p'];
  r.coverage.days.concat([Object.assign({ day: 'all' }, r.coverage.all)]).forEach(function (d) {
    lines.push([d.day, d.placed.n, d.unplaced.n, d.placed.perHour, d.unplaced.perHour, d.gapPerHour,
                d.placed.pay, d.unplaced.pay, d.gapPay, d.p].map(csvCell).join(','));
  });
  return lines.join('\n') + '\n';
}

/* --- the page ------------------------------------------------------------ */

function esc(s) {
  return String(s === null || s === undefined ? '' : s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}

function money(v) { return v === null || v === undefined ? '—' : '$' + v.toFixed(2); }

function banner(r) {
  var cv = r.coverage.all, all = r.views.all;
  var total = cv.placed.n + cv.unplaced.n;
  var lines = [];
  lines.push('<b>Offered, not earned.</b> Every figure is what the cards offered; most offers were passed. '
             + 'It is where good offers <i>start</i>, not where to sit and wait.');
  lines.push('<b>It ranks only places near where you already wait.</b> The apps send offers from near the car, '
             + 'so a place you never wait near cannot show up here, good or bad.');
  lines.push('<b>' + pct(cv.unplaced.n, total) + ' of pickups could not be placed</b> ('
             + cv.unplaced.n + ' of ' + total + ': chains with several branches inside the card\'s reach, '
             + 'cards with no GPS fix, names the map does not hold). '
             + (cv.gapPerHour === null ? ''
                : 'They paid a median ' + money(cv.unplaced.perHour) + '/hr against ' + money(cv.placed.perHour)
                  + '/hr for the placed ones (' + pText(cv.p) + '), so the place and grid tables describe a '
                  + (cv.gapPerHour > 0 ? 'better' : cv.gapPerHour < 0 ? 'worse' : 'similar')
                  + '-paying slice than your whole record. The town and restaurant tables do not need a pin and are '
                  + 'not cut this way.'));
  lines.push('<b>Significance:</b> ' + esc(testLine('places', all.place)) + ' '
             + esc(testLine('restaurants', all.rest)) + ' '
             + esc(testLine('towns', all.town)) + ' ' + esc(testLine(r.gridMi + '-mile grid', all.grid)));
  return lines.map(function (l) { return '<p>' + l + '</p>'; }).join('\n');
}

function html(r) {
  // The page's data is the report, plus which tabs the Hours picker reaches
  // (GROUPS' fourth field), so the script does not keep a second list.
  var hourly = [];
  GROUPS.forEach(function (g) { g[2].forEach(function (t) { if (t[3]) hourly.push(t[0]); }); });
  // The page reads no single wait (the reporting review's R3): section 7's
  // lists of every wait, kept on the analysis for a check that wants them,
  // are left out of the page's data, where nothing read them.
  var data = JSON.stringify(Object.assign({}, r, { hourly: hourly }), function (k, v) {
    return k === 'minutes' && v && Array.isArray(v.good) && Array.isArray(v.take) ? undefined : v;
  }).replace(/</g, '\\u003c');
  var span = r.span ? new Date(r.span[0]).toISOString().slice(0, 10) + ' to '
    + new Date(r.span[1]).toISOString().slice(0, 10) : 'no offers';
  var cvAll = r.coverage.all, placedTotal = cvAll.placed.n + cvAll.unplaced.n;
  // Every section, keyed by its tab, so they can be written in the nav's
  // order whatever order they were built in: a reader paging through the
  // source, or a screen reader, meets them as the tabs list them.
  var SEC = Object.create(null);
  SEC.overview = OVERVIEW_SECTION(r, span);
  SEC.targets = TARGETS_SECTION(r);
  SEC.strategy = STRATEGY_SECTION(r);
  SEC.best = BEST_SECTION(r);
  SEC.whenwhere = WHENWHERE_SECTION(r);
  SEC.around = AROUND_SECTION(r);
  SEC.places = '<section data-tab="places"><h2>Places — a store at a location</h2><p class="note">A place is a pin at door, '
    + 'corner or name level, or an approximate placement where it is that store\'s: within ' + PLACE_SAME_MI
    + ' mi of a door or name pin of the same store, or its own candidates no more than ' + r.best.placeApproxMi
    + ' mi apart (see Coverage for every level). <b>P75 / P90</b> are the 75th and 90th percentiles of the '
    + 'place\'s $/hr; <b>top 10%</b> is the share of its offers at or over the 90th percentile of every offer in '
    + 'their own three hours. Click a heading to sort.</p><p class="note" id="placeTest"></p>'
    + '<div id="placePlot" class="plot"></div>'
    + fold('placesTable', 'The table, every place over the floor', '<div id="placeTable"></div>')
    + fold('placesThin', 'Too few to rank', '<div id="placeThin" class="thin"></div>') + '</section>\n';
  SEC.restaurants = '<section data-tab="restaurants"><h2>Restaurants — by the name on the card, placed or not</h2>'
    + '<p class="note">One row per name, every branch together: the pickup\'s name as the card printed it (Uber\'s '
    + 'bracketed street off), merged by the rig\'s own store-name rule (Assemble.storeKey: case, marks and a '
    + '“ – Town” tail aside; Assemble.sameStore: one i/l slip). <b>No map pin is needed</b>, so this holds the bare '
    + 'names the Places tab cannot place (chains with several branches in reach, cards with no fix): '
    + '<span id="restCover"></span> A branch\'s own label (“#1155”) is its own name, as the rig reads it. '
    + 'Ranked as the other tables are: ' + r.minN + ' offers on ' + r.minOutings + ' shift days, the score '
    + 'against the other ranked restaurants in the same three-hour block, colour only where the test beats chance '
    + 'and the interval is clear of zero. <b>Your take</b> is the share you took; <b>real $/hr</b> only on orders '
    + 'put down at the door by the GPS or the screen (a median needs ' + r.realMedN + '); the <b>wait</b> only where '
    + 'the name cannot be a guess — for a chain the wait is per branch, and the waits on record carry no place, so '
    + 'a chain\'s branches go without. <b>$/mi is for reading, not an accept rule.</b> Click ▸ for the placed '
    + 'branches; click a heading to sort.</p>'
    + '<p class="note" id="restTest"></p><div id="restPlot" class="plot"></div>'
    + fold('restTableFold', 'The table, every restaurant over the floor', '<div id="restTable"></div>')
    + '<div id="restThin"></div></section>\n';
  SEC.map = '<section data-tab="map"><h2>Map</h2><p class="note">One dot per place, sized by its offers. Coloured only where it '
    + 'beats chance: <span class="k up">●</span> pays more than the same hours elsewhere, '
    + '<span class="k down">●</span> less; <span class="k grey">●</span> not distinguishable from the rest; '
    + 'small hollow dots are too few to rank. Squares are the ' + r.gridMi + '-mile grid, by the same rule.</p>'
    + '<div id="map"></div></section>\n';
  SEC.towns = '<section data-tab="towns"><h2>Towns — the card\'s own town</h2><p class="note">The town the card printed, dropoff first and '
    + 'then pickup, the rule the rig\'s map ranks towns by (map-view.js townFor). No geocoder.</p>'
    + '<p class="note" id="townTest"></p><div id="townPlot" class="plot"></div>'
    + fold('townsTable', 'The table, every town over the floor', '<div id="townTable"></div>')
    + fold('townsThin', 'Too few to rank', '<div id="townThin" class="thin"></div>') + '</section>\n';
  SEC.grid = '<section data-tab="grid"><h2>' + r.gridMi + '-mile grid — by the pickup\'s pin</h2><p class="note">Every '
    + 'placement level, an approximate one only where its candidates lie within ' + r.best.areaMi + ' mi of each '
    + 'other (the rig\'s general area, half a cell).</p><p class="note" id="gridTest"></p>'
    + '<div id="gridPlot" class="plot"></div>'
    + fold('gridTableFold', 'The table, every cell over the floor', '<div id="gridTable"></div>')
    + fold('gridThinFold', 'Too few to rank', '<div id="gridThin" class="thin"></div>') + '</section>\n';
  SEC.after = '<section data-tab="after"><h2>Where trips leave you</h2><p class="note">For each order you took and put down at the door: '
    + 'how long until the next offer the rig said <b>take</b>, and what it paid. Placed by the GPS log at the drop '
    + '(' + r.trips.gps + ' trips) or the dropoff\'s door inside its card\'s reach (' + r.trips.pin + '); the town '
    + 'off the card for the town table (' + r.trips.town + '). A silence longer than ' + r.nextGapMin
    + ' minutes before one came is you stopping, counted as "ended", not as a long wait. Counted by area only: '
    + 'no dropoff is named, and a grid cell with fewer than ' + r.dropMinN + ' trips is not shown at all. '
    + r.trips.n + ' trips in all.</p>'
    + '<p class="note" id="dropTest"></p>'
    + fold('afterTown', 'By town', '<div id="dropTown"></div>')
    + fold('afterGrid', 'By ' + r.gridMi + '-mile cell', '<div id="dropGrid"></div>') + '</section>\n';
  var wd = r.waited, dn = wd.density;
  SEC.waited = '<section data-tab="waited"><h2>Where you waited — by the car\'s own fix when each card came up</h2>'
    + '<p class="exp">Offered, not earned. Offers are dispatched near the car, so this compares only places you already '
    + 'wait in; it cannot say a place you never tried would pay, nor whether an area is good for its wait or for where '
    + 'its trips go.</p>'
    + '<p class="note">The cards that came with no taken order in the car (' + wd.cards + '), placed by the GPS fix the '
    + 'gate passed on each card (' + wd.fixed + ' of them; ' + dn.refused + ' fixes refused by the gate, the rest had '
    + 'none). By the ' + r.gridMi + '-mile cell the car was in, and by that cell\'s town (the NucBox map\'s name for '
    + 'its centre: ' + wd.towns + ' cards named). <b>Ranked</b> as every ranked table is: each offer against the other '
    + 'cells in its own three-hour block, ' + r.minN + ' offers on ' + r.minOutings + ' shift days, colour only where '
    + 'the grouping beats chance and the cell\'s interval is clear of zero.</p>'
    + '<p class="note" id="waitedTownTest"></p><div id="waitedTownPlot" class="plot"></div>'
    + fold('waitedTownFold', 'Towns where the car was, ranked', '<div id="waitedTownTable"></div><div id="waitedTownThin" class="thin"></div>')
    + '<p class="note" id="waitedGridTest"></p><div id="waitedGridPlot" class="plot"></div>'
    + fold('waitedGridFold', r.gridMi + '-mile cells where the car was, ranked',
           '<div id="waitedGridTable"></div><div id="waitedGridThin" class="thin"></div>')
    + '<h3>Per area and hours: time there, offers an hour, the share that cleared your target</h3>'
    + '<p class="exp">Experimental, descriptive: counts, medians and intervals, not ranked or coloured.</p>'
    + '<p class="note"><b>Hours there are inferred</b>: each card\'s time to the next card, at most '
    + wd.creditMaxMin + ' minutes and none across a silence over ' + r.nextGapMin + ', credited to where the car was at '
    + 'the earlier card (the Busy tab\'s spells, off the GPS log, are the measured version). <b>Cleared target</b> is '
    + 'the card\'s $/hr at or over the target the panel judged it by. A <b>stay</b> is consecutive cards in one area '
    + 'with no silence; its minutes to the first card at target start at its first CARD, not at arrival, so a stay '
    + 'whose first card was at target reads 0. At target is each card\'s own target at the time, not the top-X% '
    + '"good" of When &amp; where and section 7. Figures at ' + r.descMinN + ' offers on ' + r.minOutings + ' shift days.</p>'
    + fold('f-waitedAreaTown', 'By town', '<div id="m-waitedAreaTown"></div>')
    + fold('f-waitedAreaGrid', 'By ' + r.gridMi + '-mile cell', '<div id="m-waitedAreaGrid"></div>')
    + '<h3>From a drop to the next Took</h3>'
    + '<p class="note">How dense the record\'s positions are between jobs: offer rows are the only journal rows with a '
    + 'fix (seen and health rows carry none; order rows carry a total, not a track). Good card fixes in this window: '
    + dn.fixed + ' of ' + dn.offers + ' counted offers, one every ' + (dn.gapMedian === null ? '—' : dn.gapMedian + ' min')
    + ' at the median within a run (P90 ' + (dn.gapP90 === null ? '—' : dn.gapP90 + ' min') + '; '
    + (dn.over5 === null ? '—' : Math.round(dn.over5 * 100) + '%') + ' of gaps over 5 min). So the two ends are known — '
    + 'where the drop left the car (the GPS log, the dropoff\'s door, or the first card within ' + wd.cardFixAfterMin
    + ' min after: ' + r.trips.cardFix + ' trips) and where the car was when the next order was taken (that card\'s '
    + 'fix) — and the path between them only through the cards: <b>a lower bound, not miles driven</b> (the Best tab\'s '
    + 'dead miles, off the GPS log, are that). <b>Moved</b> = the ends more than ' + wd.movedMi + ' mi apart. '
    + r.trips.empty + ' trips measured; a dropoff town under ' + r.dropMinN + ' is not named.</p>'
    + fold('f-emptyTown', 'Moved against stayed, and by dropoff town', '<div id="m-emptyTown"></div>')
    + '</section>\n';
  var more = MORE_SECTIONS(r);
  Object.keys(more).forEach(function (k) { SEC[k] = more[k]; });
  SEC.coverage = '<section data-tab="coverage"><h2>Coverage, shift day by shift day</h2><p class="note">Pickups placed and not, and what each paid. '
    + 'A gap that keeps the same sign day after day is a bias in what the map can show, not a fact about places.</p>'
    + fold('coverageLevels', 'Placed, by level', '<p class="note">door, corner and name are a point; band, area and street are '
      + 'approximate (an area, with its spread). "Stood in for" is the refusal an approximate placement was found '
      + 'beside. Street index: ' + esc(r.best.streets || 'none') + '. Router (for the band): '
      + esc(r.best.road || 'none') + '.</p><div id="levels"></div>')
    + fold('coverageDays', 'Placed and not, by shift day', '<div id="coverage"></div>') + '</section>\n';
  SEC.method = '<section data-tab="method" class="method"><h2>How this was measured</h2>' + METHOD(r) + '</section>\n';

  /* The top of the page. The title and the window, then the nav — the one
   * part that stays put while a long table scrolls under it — then the Hours
   * picker, which scrolls away with the page and shows only on the tabs it
   * reaches. The banner that opened the page (four paragraphs, taller than a
   * phone's screen, before a single figure) is the Overview's "Read before
   * the numbers" now, whole; every other tab keeps its gist in one line
   * under the nav, with a link back to it, so no tab reads without it. */
  var nav = '<div id="navAt"></div><nav class="nav" id="nav" aria-label="Report sections">'
    + '<div class="groups" id="groups" role="tablist">' + GROUPS.map(function (g) {
      return '<button type="button" role="tab" data-group="' + g[0] + '">' + esc(g[1]) + '</button>';
    }).join('') + '</div>'
    + '<div class="tabs" id="tabs">' + GROUPS.map(function (g) {
      return '<span class="tg" data-group="' + g[0] + '">' + g[2].map(function (t) {
        return '<button type="button" data-tab="' + t[0] + '">' + esc(t[1]) + '</button>';
      }).join('') + '</span>';
    }).join('') + '</div></nav>\n';
  var strip = '<p class="strip" id="strip"><b>Offered, not earned</b>; only places near where you wait; '
    + pct(cvAll.unplaced.n, placedTotal) + ' of pickups unplaced. <a href="#overview">Read before the numbers</a></p>\n'
    // A capped read said on the page, not only on stdout (the reporting
    // review's R2): every figure below is over what was read.
    + (r.source && r.source.truncated ? '<p class="strip warn" id="capped"><b>Not the whole journal:</b> the server sent '
      + r.source.count + ' of ' + r.source.total + ' offers and would not page further, so every figure here is over the '
      + 'newest ' + r.source.count + '. Narrow the window with --since, or update the server.</p>\n' : '');
  return '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
    + '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    + '<title>Strategy &amp; Places Report</title>\n'
    + '<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">\n'
    + '<style>\n' + PAGE_CSS + '\n</style>\n</head>\n<body>\n<main>\n'
    + '<header class="head"><h1>Strategy &amp; places report</h1>\n'
    + '<p class="sub">' + esc(span) + ' · ' + r.coverage.offers + ' offers the rig stands behind, '
    + r.outings + ' shift days · made ' + esc(new Date(r.made).toISOString().slice(0, 16).replace('T', ' '))
    + ' UTC on the NucBox · offline report, nothing on the rig reads it</p></header>\n'
    + nav + strip
    + '<div class="bar" id="hoursBar"><label>Hours <select id="when"></select></label>'
    + '<span id="whenNote" class="note"></span></div>\n'
    + TABS.map(function (t) { return SEC[t[0]] || ''; }).join('')
    + '</main>\n<div id="tip" hidden></div>\n'
    + '<script type="application/json" id="data">' + data + '</script>\n'
    + '<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>\n'
    + '<script>\n' + PAGE_JS + '\n</script>\n</body>\n</html>\n';
}

/* A long table behind its heading: a <details> that is open as written, so
 * a laptop (and a page with its script off) shows everything as before, and
 * that the page's script closes on a phone, where the tables are wider than
 * the screen and a tab of fourteen of them is a scroll of seven screens.
 * Its id is a deep link: #<id> opens the tab it sits in, opens it and
 * scrolls to it. Nothing is dropped; the heading says what is inside. */
function fold(id, title, inner) {
  return '<details class="fold"' + (id ? ' id="' + esc(id) + '"' : '') + ' open><summary><h3>' + esc(title)
    + '</h3></summary>' + inner + '</details>';
}

/* The Overview (7 Nov 2026), where a bare address now opens. The owner
 * asked whether there was "a better format for all this information"; the
 * answer here is a landing page of the few numbers that matter, each one a
 * link to the tab that works it out, with its sample size under it — and no
 * figure of its own. Everything on it is already in the report object
 * (strategy.js's answer, advice.js's Targets lines, the coverage), picked
 * out, never recomputed, so it cannot disagree with the tab it points to:
 *
 *   - the Strategy tab's own sentence on the best line, word for word;
 *   - tiles: the best line and the flat range round it, $/hr on shift gross
 *     and net, offers per free hour, card against actual, the typical offer,
 *     the record and how far to trust it (the Strategy tab's own "thin"
 *     line where it has one), and when this was made;
 *   - the curve, small, and time of day as bars;
 *   - where the good offers start: the Targets tab's town lines, word for
 *     word, and how much of the record could be placed at all;
 *   - the banner that used to head every tab, whole, under "Read before the
 *     numbers";
 *   - and a directory of every tab under its question.
 *
 * Descriptive, like the rest: nothing here is an accept rule or reaches the
 * rig. Formatting is one rule throughout: a rate carries its unit ($/hr,
 * $/mi), a count says n=. */
function fmtPH(v) { return typeof v === 'number' ? '$' + v.toFixed(2) + '/hr' : '—'; }
function fmtPM(v) { return typeof v === 'number' ? '$' + v.toFixed(2) + '/mi' : '—'; }

/* The front page's when and where (round B; glanceOf has the rules). */
function glanceSection(r) {
  var g = r.glance;
  if (!g) return '';
  var w = g.windows, shown = w.best.length ? w.best : w.leading;
  function areaName(e) { return e.town ? e.a : labelOf(r, 'grid', e.a); }
  function days(n, gi) {
    var names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday', 'weekday', 'weekend day'];
    return n + ' ' + names[gi] + (n === 1 ? '' : 's');
  }
  var wins = shown.map(function (x) {
    return '<li><b>' + esc(x.name) + '</b> · ' + x.rate.toFixed(1) + ' good/hr waited'
      + (x.shade === 'above' ? ' <span class="ok">clearly above</span>' : '')
      + ' <small>' + x.online.toFixed(1) + ' h waited on ' + days(x.nights, x.group) + '</small>'
      + (x.areas && x.areas.length ? '<br><small>Waiting areas then (home left out): ' + x.areas.map(function (e) {
        return esc(areaName(e)) + ' ' + (e.r === null ? '—' : e.r.toFixed(1)) + ' good/hr over ' + e.h.toFixed(1) + ' h on '
          + e.d + ' day' + (e.d === 1 ? '' : 's');
      }).join('; ') + '</small>' : '<br><small>No waiting area there yet with ' + WW_MIN_HOURS + ' h on ' + WW_MIN_DAYS
        + ' days, home left out.</small>') + '</li>';
  }).join('');
  var weak = w.worst.map(function (x) {
    return '<li><b>' + esc(x.name) + '</b> · ' + x.rate.toFixed(1) + ' good/hr waited <span class="warn">clearly below</span>'
      + ' <small>' + x.online.toFixed(1) + ' h on ' + days(x.nights, x.group) + '</small></li>';
  }).join('');
  function towns(end, lead) {
    var t = g.towns[end], top = t.ranked.slice(0, 3);
    return '<p class="lead">' + lead + ': ' + (top.length ? top.map(function (e) {
      return '<b>' + esc(e.town) + '</b> ' + Math.round(e.share * 100) + '% good, typical ' + fmtPH(e.typical)
        + ' (n=' + e.n + ')' + (e.shade ? ' — clearly ' + e.shade : '');
    }).join('; ') : 'no town with ' + g.towns.minN + ' offers on ' + g.towns.minDays + ' days yet') + '.</p>';
  }
  return '<h3>When <a class="more" href="#whenwhere">When &amp; where ›</a></h3>'
    + '<p class="note">Good = top ' + g.top + '% of every offer in the range: '
    + (g.cut === null ? 'no offers yet' : '≥ ' + money(g.cut) + '/hr') + '. Good offers per hour WAITED (no order in '
    + 'the car), When &amp; where\'s own figure.</p>'
    + (w.best.length ? '<p class="lead">Good offers came clearly more often than the range\'s ' + w.ref.toFixed(1)
       + ' an hour waited:</p>' : '<p class="lead"><b>No window clearly better yet</b>; highest so far:</p>')
    + (wins ? '<ol class="lines">' + wins + '</ol>' : '<p class="note">No window has ' + WW_MIN_HOURS + ' h waited on '
       + WW_MIN_DAYS + ' days yet.</p>')
    + (weak ? '<p class="lead">Clearly less often:</p><ol class="lines">' + weak + '</ol>' : '')
    + '<p class="note">A window is 1 to ' + w.maxLen + ' whole hours on a weekday, on weekdays or on weekends, at '
    + w.floorHours + ' h waited on ' + w.floorDays + ' days; "clearly" holds at 99% shared over the ' + w.searched
    + ' windows looked at. Waiting areas leave out home (' + g.homeLeft + ' cards; Offers around you\'s rule).</p>'
    + '<h3>Where <a class="more" href="#around">Offers around you ›</a></h3>'
    + towns('pick', 'Pickup towns, by share good')
    + towns('drop', 'Drop-off towns, by share good')
    + '<p class="note">The town printed on the card (<a href="#towns">Towns</a>); where trips leave you is '
    + '<a href="#after">After a drop</a>; where you waited is <a href="#waited">Waited</a>.</p>';
}

function OVERVIEW_SECTION(r, span) {
  var s = r.strategy, cv = s.curve, c = s.counts, all = s.seen.all, act = s.actual.all;
  function line(re) { return s.lines.filter(function (l) { return re.test(l); })[0] || null; }
  function tile(href, label, value, sub, foot, cls) {
    return '<a class="tile' + (cls ? ' ' + cls : '') + '" href="' + href + '"><span class="tl">' + esc(label) + '</span>'
      + '<span class="tv">' + value + '</span>' + (sub ? '<span class="ts">' + sub + '</span>' : '')
      + (foot ? '<span class="tf">' + foot + '</span>' : '') + '</a>';
  }
  var best = cv.drawn ? cv.best : null;
  var lead = line(/^Holding out for/), yours = line(/^Your line/), trust = line(/^How far to trust it/);
  var pct0 = Math.round((1 - s.floors.plateau) * 100);
  var tiles = [];
  tiles.push(tile('#strategy', 'Best line to hold out for',
    best ? '$' + best.T + '+<small>/hr</small>' : '—',
    best ? (best.from === best.to ? 'no other line within ' + pct0 + '%' : 'flat from $' + best.from + ' to $' + best.to
            + ' (within ' + pct0 + '% of the best)') + (cv.target && cv.target.side ? '; your $' + cv.target.T + ' is '
            + (cv.target.side === 'inside' ? 'inside it' : cv.target.side + ' it') : '')
      : 'not enough record for a curve yet',
    best ? 'n=' + best.n + ' offers at $' + best.T + '+ seen free · Strategy' : 'Strategy'));
  tiles.push(tile('#s-curve', '$/hr on shift at that line',
    best ? '$' + best.value.toFixed(2) + (cv.bestNet && cv.cost.perMile !== null
      ? ' <small>gross</small><br>$' + cv.bestNet.value.toFixed(2) + ' <small>net</small>' : '') : '—',
    'every hour on shift, waiting included' + (cv.bestCi ? '; 95% $' + cv.bestCi[0].toFixed(2) + '–$' + cv.bestCi[1].toFixed(2) : '')
      + (typeof cv.everything.gross === 'number' ? '; taking everything ' + fmtPH(cv.everything.gross) : ''),
    cv.days + ' shift days, ' + (cv.freeHours || 0) + ' h free · Strategy'));
  tiles.push(tile('#s-seen', 'Offers per free hour',
    typeof all.perFreeHour === 'number' ? all.perFreeHour.toFixed(1) : '—',
    'seen with no order in the car',
    'n=' + (c.free || 0) + ' offers in ' + c.freeHours + ' h free of ' + c.shiftHours + ' h on shift · Strategy'));
  tiles.push(tile('#s-actual', 'Card against actual',
    typeof act.ratio === 'number' ? act.ratio.toFixed(2) + '×' : '—',
    typeof act.ratio === 'number' ? 'minutes really taken ÷ the card\'s; a $25/hr card ≈ ' + fmtPH(25 / act.ratio) + ' actual'
      : 'fewer than ' + s.floors.ratio + ' timed orders: cards taken at their word',
    'n=' + act.timed + ' timed orders · Strategy'));
  tiles.push(tile('#s-seen', 'The typical offer',
    all.ph.p50 !== null ? fmtPH(all.ph.p50).replace('/hr', '<small>/hr</small>') : '—',
    all.ph.p50 !== null ? 'half between $' + all.ph.p25.toFixed(2) + ' and $' + all.ph.p75.toFixed(2) + '; top 10% from '
      + fmtPH(all.ph.p90) + (all.pm.p50 !== null ? '; ' + fmtPM(all.pm.p50) + ' median (read only)' : '') : '',
    'n=' + all.n + ' offers on ' + all.outings + ' shift days · Strategy'));
  // The record, and how far to trust it: the Strategy tab's own sentence
  // where it calls the record thin, so the warning is worded once.
  tiles.push(tile('#strategy', trust ? 'How far to trust it' : 'The record',
    trust ? 'thin' : c.outings + ' <small>shift days</small>',
    trust ? esc(trust.replace(/^How far to trust it: thin — /, '')) : c.offers + ' offers, ' + act.timed
      + ' timed orders, ' + (cv.freeHours || 0) + ' h free: not flagged thin',
    'made ' + esc(new Date(r.made).toISOString().slice(0, 16).replace('T', ' ')) + ' UTC · ' + esc(span),
    trust ? 'warn' : ''));

  // Time of day in words: the blocks with a curve of their own, highest
  // $/hr on shift first. An ordering of point estimates, said as such.
  var ranked = (s.slices.block || []).filter(function (b) { return b.drawn && b.best; })
    .sort(function (a, b) { return b.best.value - a.best.value; });
  var blocksSaid = ranked.length
    ? 'Highest $/hr on shift, each block at its own best line: ' + ranked.slice(0, 3).map(function (b) {
      return esc(b.name) + ' ' + fmtPH(b.best.value) + ' (n=' + b.offers + ')';
    }).join(', ') + '. Point estimates with no test between them; the held-out check in the Strategy tab says '
      + 'whether a line per block beat one line on this record.'
    : 'No block has a curve of its own yet.';

  var cvAll = r.coverage.all, total = cvAll.placed.n + cvAll.unplaced.n;
  var areas = r.targets && r.targets.lines ? r.targets.lines.areas : [];
  var wwCut = r.whenwhere.cuts[r.whenwhere.tops.indexOf(r.whenwhere.top)];
  return '<section data-tab="overview"><h2>Overview — the few numbers that matter</h2>'
    + '<p class="exp">Descriptive. Every figure is from the tab it links to, with its sample size under it; nothing '
    + 'here is an accept rule or changes a verdict, and nothing on the rig reads it. '
    + '<a href="#caveats">Read before the numbers</a>.</p>'
    // Round B: when and where first, the owner's two questions.
    + glanceSection(r)
    // The figures first, then the Strategy tab's own sentence on them: on a
    // phone the sentence is a screen long, and the tiles are what a glance
    // is for.
    + '<div class="tiles">' + tiles.join('') + '</div>'
    + (lead ? '<p class="lead">' + esc(lead) + (yours ? ' ' + esc(yours) : '') + ' <a href="#strategy">Strategy ›</a></p>' : '')
    + '<div class="pair">'
    + '<div><h3>Holding out for a line <a class="more" href="#s-curve">curve ›</a></h3>'
    + '<div class="plot fluid">' + strategyChart(cv, 'small') + '</div>'
    + '<p class="note">Gross (solid) and net (dashed) $/hr on shift against the line held out for; shaded, within '
    + pct0 + '% of the best; hollow points are thin (under ' + s.floors.curveOffers + ' offers).</p></div>'
    + '<div><h3>Time of day <a class="more" href="#s-blocks">blocks ›</a></h3>'
    + '<div class="plot fluid">' + blockChart(s.slices.block) + '</div>'
    + '<p class="note">' + blocksSaid + '</p></div>'
    + '</div>'
    + '<h3>Where the good offers start <a class="more" href="#targets">Targets ›</a></h3>'
    + '<ul class="lines">' + areas.map(function (l) { return '<li>' + esc(l) + '</li>'; }).join('') + '</ul>'
    // Which area at a given time is its own tab, with its own picker; the
    // Overview names it and its cutoff and works nothing out.
    + '<p class="lead"><a href="#whenwhere">When &amp; where ›</a> which area gave the most good offers per hour '
    + 'waited, on the day and hours you pick (good = top ' + r.whenwhere.top + '%: '
    + (wwCut === null ? 'no offers yet' : '≥ ' + money(wwCut) + '/hr') + ').</p>'
    + '<p class="note">' + pct(cvAll.unplaced.n, total) + ' of pickups could not be placed (' + cvAll.unplaced.n + ' of '
    + total + '), so the Places, Map and Grid tabs describe a slice of the record: <a href="#coverage">Coverage ›</a>. '
    + 'Towns and Restaurants need no pin.</p>'
    + '<details class="caveats" id="caveats" open><summary><h3>Read before the numbers</h3></summary>'
    + '<div class="banner">' + banner(r) + '</div></details>'
    + '<h3>Every tab, by the question it answers</h3><div class="dir">'
    + GROUPS.filter(function (g) { return g[0] !== 'overview'; }).map(function (g) {
      return '<div><h4>' + esc(g[1]) + '</h4><ul>' + g[2].map(function (t) {
        return '<li><a href="#' + t[0] + '">' + esc(t[1]) + '</a> — ' + esc(t[2]) + '</li>';
      }).join('') + '</ul></div>';
    }).join('') + '</div>'
    + '</section>\n';
}

/* The Targets tab: advice.js's lines (the offers page's box, word for word),
 * then the richer area lines only this report can give. */
function TARGETS_SECTION(r) {
  var t = r.targets, L = t.lines;
  function ul(xs) { return '<ul class="lines">' + xs.map(function (l) { return '<li>' + esc(l) + '</li>'; }).join('') + '</ul>'; }
  return '<section data-tab="targets"><h2>Targets — what the record says to aim for</h2>'
    + '<p class="exp">Descriptive. The same lines the offers page shows (advice.js targets): realistic $/hr by '
    + 'three-hour block, the replay\'s one line for all hours, the $/mi good offers tend to have, and the towns '
    + 'that beat chance. Nothing here is an accept rule or changes a verdict.</p>'
    + '<h3>$/hr and $/mi, by time of day</h3>' + ul(L.rate)
    + '<h3>Best areas to work: towns</h3>' + ul(L.areas)
    + '<h3>Best areas to work: places, restaurants, cells and waiting</h3>'
    + '<p class="note">From the tables in the other tabs, by the same tests: named only where the grouping beats '
    + 'chance and the interval of its hour-held score is clear of zero; waiting from the GPS spells (Best offers tab).</p>'
    + ul(targetAreaLines(r))
    + '<p class="note">Floors: ' + t.floors.offers + ' offers in a block for its percentiles, ' + t.floors.timed
    + ' timed takes for a median real $/hr, ' + t.floors.cleared + ' offers over the line for a $/mi, '
    + t.floors.town + ' offers on ' + t.floors.townDays + ' shift days for a town.</p>'
    + ul(L.notes).replace('class="lines"', 'class="note"')
    + '</section>\n';
}

/* The Strategy tab (7 Nov 2026): tools/strategy.js's answer, drawn here and
 * worked out there. The plain lines first (strategy.js words them, for this
 * page and the end-of-shift report alike), then the curve as a chart and a
 * table, the slices, and the two descriptive halves under it. Static HTML:
 * the hours picker above does not reach it, because the curve is over all
 * hours and its blocks are rows of their own. */
/* Two sizes of one drawing. 'wide' is the 640 x 260 the tab always drew,
 * for a laptop; 'small' is 360 x 220 with fewer labels, for a phone and for
 * the Overview: the wide one squeezed to a 343px screen prints its labels at
 * six pixels, and given its old 520px floor it scrolled sideways instead,
 * hiding the right half of the curve — where the best line usually is. */
function strategyChart(cv, size) {
  var small = size === 'small';
  var pts = cv.points, W = small ? 360 : 640, H = small ? 220 : 260, L = small ? 40 : 52, R = small ? 10 : 16, T = 14,
      B = small ? 32 : 34;
  var vals = [];
  pts.forEach(function (p) {
    [p.gross, p.net, p.ci && p.ci[0], p.ci && p.ci[1]].forEach(function (v) { if (typeof v === 'number') vals.push(v); });
  });
  if (cv.everything && typeof cv.everything.gross === 'number') vals.push(cv.everything.gross);
  if (!vals.length) return '<p class="note">Nothing to draw yet.</p>';
  var lo = Math.max(0, Math.floor(Math.min.apply(null, vals) / 5) * 5), hi = Math.ceil(Math.max.apply(null, vals) / 5) * 5;
  if (hi <= lo) hi = lo + 5;
  var x0 = cv.grid[0], x1 = cv.grid[cv.grid.length - 1];
  function X(v) { return L + (v - x0) / (x1 - x0) * (W - L - R); }
  function Y(v) { return T + (hi - v) / (hi - lo) * (H - T - B); }
  var out = ['<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Effective $/hr on shift against the line held out for">'];
  // The flat region first, under everything: "anything in here gives about the same".
  if (cv.best) {
    out.push('<rect x="' + X(cv.best.from).toFixed(1) + '" y="' + T + '" width="' + Math.max(2, X(cv.best.to) - X(cv.best.from)).toFixed(1)
             + '" height="' + (H - T - B) + '" fill="var(--grid)" opacity="0.7"><title>Within '
             + Math.round((1 - S.PLATEAU) * 100) + '% of the best: $' + cv.best.from + ' to $' + cv.best.to + '</title></rect>');
  }
  for (var gy = lo; gy <= hi; gy += (small && hi - lo > 20 ? 10 : 5)) {
    out.push('<line x1="' + L + '" x2="' + (W - R) + '" y1="' + Y(gy).toFixed(1) + '" y2="' + Y(gy).toFixed(1)
             + '" stroke="var(--grid)"/><text x="' + (L - 6) + '" y="' + (Y(gy) + 4).toFixed(1) + '" text-anchor="end">$' + gy + '</text>');
  }
  cv.grid.forEach(function (gx, i) {
    if (i % (small ? 3 : 2)) return;
    out.push('<text x="' + X(gx).toFixed(1) + '" y="' + (H - B + 16) + '" text-anchor="middle">$' + gx + '</text>');
  });
  out.push('<text x="' + ((L + W - R) / 2) + '" y="' + (H - 4) + '" text-anchor="middle">'
           + (small ? 'line held out for ($/hr on the panel)' : 'cards held out for: the panel\'s $/hr or more') + '</text>');
  // The 95% band, where shift days were resampled.
  var band = pts.filter(function (p) { return p.ci; });
  if (band.length >= 2) {
    out.push('<polygon fill="var(--up)" opacity="0.15" points="' + band.map(function (p) { return X(p.T).toFixed(1) + ',' + Y(p.ci[1]).toFixed(1); })
      .concat(band.slice().reverse().map(function (p) { return X(p.T).toFixed(1) + ',' + Y(p.ci[0]).toFixed(1); })).join(' ') + '"/>');
  }
  if (cv.everything && typeof cv.everything.gross === 'number') {
    out.push('<line x1="' + L + '" x2="' + (W - R) + '" y1="' + Y(cv.everything.gross).toFixed(1) + '" y2="' + Y(cv.everything.gross).toFixed(1)
             + '" stroke="var(--ink2)" stroke-dasharray="2 4"><title>Taking everything: $' + cv.everything.gross.toFixed(2) + '/hr</title></line>');
  }
  if (cv.target && typeof cv.target.T === 'number' && cv.target.T >= x0 && cv.target.T <= x1) {
    out.push('<line x1="' + X(cv.target.T).toFixed(1) + '" x2="' + X(cv.target.T).toFixed(1) + '" y1="' + T + '" y2="' + (H - B)
             + '" stroke="var(--ink2)" stroke-dasharray="4 3"/><text x="' + (X(cv.target.T) + 4).toFixed(1) + '" y="' + (T + 10)
             + '">your line</text>');
  }
  [['gross', 'var(--up)', ''], ['net', 'var(--ink2)', ' stroke-dasharray="6 4"']].forEach(function (s) {
    var seg = pts.filter(function (p) { return typeof p[s[0]] === 'number'; });
    if (seg.length < 2) return;
    out.push('<polyline fill="none" stroke="' + s[1] + '" stroke-width="2"' + s[2] + ' points="'
             + seg.map(function (p) { return X(p.T).toFixed(1) + ',' + Y(p[s[0]]).toFixed(1); }).join(' ') + '"/>');
    seg.forEach(function (p) {
      // A thin point is hollow: it can be neither the best nor in the flat region.
      out.push('<circle cx="' + X(p.T).toFixed(1) + '" cy="' + Y(p[s[0]]).toFixed(1) + '" r="' + (small ? 3 : 4) + '" stroke="' + s[1] + '" stroke-width="2" fill="'
               + (p.thin ? 'var(--surface)' : s[1]) + '"><title>$' + p.T + '+: ' + s[0] + ' $' + p[s[0]].toFixed(2) + '/hr on shift, '
               + p.n + ' offers seen free' + (p.thin ? ' (thin)' : '') + '</title></circle>');
    });
    // Labelled at the left end, gross above its line and net below its own:
    // at the right end both curves fall to the same few offers and meet.
    var first = seg[0];
    out.push('<text x="' + (X(first.T) + 6).toFixed(1) + '" y="' + (Y(first[s[0]]) + (s[0] === 'gross' ? -10 : 18)).toFixed(1)
             + '">' + s[0] + '</text>');
  });
  out.push('</svg>');
  return out.join('');
}

/* A table of strategy.js's rows. `thin`, where given, marks a row whose
 * sample is under its floor (a hollow point, a slice with no curve, a row
 * with no quartile): drawn muted and in italics, so a figure over too few
 * offers never reads as loud as one over enough, and its n stays beside it. */
function strategyTable(cols, rows, thin) {
  if (!rows || !rows.length) return '<p class="note">None.</p>';
  function cell(v, f) {
    if (v === null || v === undefined) return '—';
    if (f === '$') return '$' + v.toFixed(2);
    if (f === '$ci') return '[$' + v[0].toFixed(2) + ', $' + v[1].toFixed(2) + ']';
    if (f === 'x') return v.toFixed(2) + '×';
    if (f === 'r') return v.toFixed(2);
    if (f === 'h') return v.toFixed(1);
    return esc(v);
  }
  return '<div class="tw"><table><thead><tr>' + cols.map(function (c) { return '<th>' + esc(c[1]) + '</th>'; }).join('')
    + '</tr></thead><tbody>' + rows.map(function (r) {
      return '<tr' + (thin && thin(r) ? ' class="thinrow"' : '') + '>'
        + cols.map(function (c) { return '<td>' + cell(typeof c[0] === 'function' ? c[0](r) : r[c[0]], c[2]) + '</td>'; }).join('') + '</tr>';
    }).join('') + '</tbody></table></div>';
}

/* Time of day, drawn: one bar per three-hour block, its length the $/hr on
 * shift that holding out for that block's own best line gave (strategy.js's
 * slices), a tick where taking everything in that block would have been, and
 * the line, the offers seen free and the shift days under it. A block with
 * no curve of its own (under its floors) gets no bar, only its counts, in
 * grey. Every bar is one colour: these are point estimates with no test
 * between them, and AUDITS.md's Settled entry found a line tuned to the hour
 * earned less on the nights it was not fitted to — the held-out check under
 * the Strategy tab's lines says how that went on this record. Inline SVG off
 * the page's own colours, so it needs no library, works offline and follows
 * light and dark. */
function blockChart(blocks) {
  blocks = blocks || [];
  if (!blocks.length) return '<p class="note">No three-hour block saw an offer while free.</p>';
  var W = 360, rowH = 32, L = 64, Rr = 8, T = 6, H = T + blocks.length * rowH + 2;
  var top = 0;
  blocks.forEach(function (b) {
    [b.best && b.drawn ? b.best.value : null, b.everything && b.everything.gross].forEach(function (v) {
      if (typeof v === 'number') top = Math.max(top, v);
    });
  });
  top = Math.max(5, Math.ceil(top / 5) * 5);
  function X(v) { return L + v / top * (W - L - Rr); }
  var out = ['<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="$/hr on shift by three-hour block">'];
  blocks.forEach(function (b, i) {
    var y = T + i * rowH, has = b.drawn && b.best;
    out.push('<text x="' + (L - 6) + '" y="' + (y + 12) + '" text-anchor="end">' + esc(b.name) + '</text>');
    if (has) {
      out.push('<rect x="' + L + '" y="' + (y + 2) + '" width="' + Math.max(1, X(b.best.value) - L).toFixed(1)
               + '" height="12" rx="2" fill="var(--up)"><title>' + esc(b.name) + ': $' + b.best.value.toFixed(2)
               + '/hr on shift holding out for $' + b.best.T + '+ (n=' + b.best.n + ' offers)</title></rect>');
      out.push('<text x="' + L + '" y="' + (y + 27) + '" class="sm">$' + b.best.value.toFixed(2) + '/hr at $' + b.best.T
               + '+ · n=' + b.offers + ' seen free · ' + b.days + ' days</text>');
    } else {
      out.push('<rect x="' + L + '" y="' + (y + 2) + '" width="' + (W - L - Rr) + '" height="12" rx="2" fill="none" '
               + 'stroke="var(--axis)" stroke-dasharray="3 3"/><text x="' + L + '" y="' + (y + 27)
               + '" class="sm">too few for a curve · n=' + b.offers + ' seen free · ' + b.days + ' days</text>');
    }
    if (b.everything && typeof b.everything.gross === 'number') {
      var xe = X(b.everything.gross).toFixed(1);
      out.push('<line x1="' + xe + '" x2="' + xe + '" y1="' + y + '" y2="' + (y + 16) + '" stroke="var(--ink)" stroke-width="2">'
               + '<title>' + esc(b.name) + ': taking everything $' + b.everything.gross.toFixed(2) + '/hr</title></line>');
    }
  });
  out.push('</svg>');
  return out.join('') + '<p class="note">Bar: $/hr on shift at the block\'s own best line. Tick: taking everything in '
    + 'that block. Point estimates, no test between blocks.</p>';
}

/* Card against what the app paid (the owner, 7 Nov 2026: "compare what uber
 * actually paid compared to the expected pay of the order"): strategy.js's
 * cardVsPaid over the trips read off the app's earnings screenshots and
 * matched to orders (server.js /api/earnings, earnings.js). By app, by
 * three-hour block of the trip's start and by restaurant, each with its n; a
 * group under its floor is thin (muted, italic, never the headline), and a
 * trip whose tip is still processing is left out of every figure and
 * counted. A server with no earnings, or none uploaded: one sentence. */
function paidSection(p) {
  if (!p) return '';
  var cols = [['name', ''], ['n', 'orders'], ['card', 'cards', '$'], ['paid', 'paid', '$'], ['diff', 'paid − card', '$'],
              ['medianDiff', 'typical order', '$'], ['tips', 'settled tips', '$'], ['over', 'paid more'], ['under', 'paid less']];
  function thin(g) { return g.thin; }
  var c = p.counts;
  return '<h3 id="s-paid">Card vs paid</h3>'
    + '<p class="note">What the app paid, read off its own earnings screenshots uploaded on the offers page, against what '
    + 'the card said, for the trips matched to an order (' + c.matched + ' of ' + c.entries + ' read; ' + c.unmatched
    + ' not matched — no order on file, or waiting for you to pick). <b>' + c.pending + '</b> with a tip still processing '
    + 'are left out of every figure until a later upload settles them' + (c.noCard ? '; ' + c.noCard + ' with no card pay on file' : '')
    + '. A group under ' + p.floor + ' orders is <b>thin</b>. Descriptive: nothing on the rig reads it.</p>'
    + (c.entries ? strategyTable(cols, [p.all], thin)
       + fold('s-paid-app', 'By app', strategyTable(cols, p.byApp, thin))
       + fold('s-paid-block', 'By three-hour block (of the trip\'s start)', strategyTable(cols, p.byBlock, thin))
       + fold('s-paid-rest', 'By restaurant (as the app names it)', strategyTable(cols, p.byRestaurant, thin))
       : '<p class="note">No earnings screenshots have been uploaded yet.</p>');
}

/* Uber's acceptance rate and the line that keeps the goal (strategy.js
 * section 6; the owner, 15 Nov 2026: Gold needs 25%). Its lines are among
 * the tab's own above; here, Uber's curve with the share of exclusive
 * requests each line would have kept. Descriptive, as the rest. */
function GOLD_PART(s) {
  var g = s.gold;
  if (!g || !g.line) return '';
  var goal = Math.round(g.goal * 100) + '%';
  var cols = [['T', 'line ($/hr+)', '$'], ['n', 'Uber offers seen free'], ['gross', 'gross $/hr on shift', '$'],
              [function (p) { return Math.round(p.share * 100) + '%'; }, 'requests at or above it'],
              [function (p) { return Math.round(p.shareKept * 100) + '%'; }, '…with your takes below it'],
              [function (p) { return g.line.best && p.T === g.line.best.T ? 'best' : g.line.kept && p.T === g.line.kept.T
                ? 'best keeping ' + goal : ''; }, ''],
              [function (p) { return p.thin ? 'thin' : ''; }, '']];
  return '<h3 id="s-gold">Uber acceptance — the line that keeps ' + esc(goal) + '</h3>'
    + '<p class="note">Uber\'s cards alone, as the rig saw them: the share of the ' + g.line.requests + ' exclusive requests on '
    + 'record whose card was at each line, beside what holding out for that line paid per hour on shift. The share counts '
    + 'every card at the line as taken, an upper bound. Trip Radar, Early look, reservations and DoorDash are left out; a '
    + 'card with no Exclusive tag read is counted. Not a rule: no verdict, target or panel line reads it. Check Uber Pro\'s '
    + 'own terms for what it counts.</p>'
    + fold('s-gold-points', 'Every line, with its share of requests', strategyTable(cols, g.line.points, function (p) { return p.thin; }));
}

/* The good offers passed on (strategy.js section 7; the reporting work's
 * third round): placed straight under the curve because it is the curve's
 * own question asked of what was done — the curve says what holding out for
 * a line would have paid, this says which good cards were taken and what
 * came after the ones let go. A stacked bar per three-hour block (taken, the
 * phone's own accept, let go, busy: counts, so the bar is as long as the
 * block's good offers), the waits under it, then the table and the four
 * rulers folded. Words in the past tense; no test between blocks, and no
 * block is marked: these are counts, and the blocks are rows of a table. */
function PASSED_PART(s) {
  var p = s.passed;
  if (!p || p.cut === null || !p.all.good) return '';
  var max = 0;
  p.byBlock.forEach(function (g) { max = Math.max(max, g.good); });
  function pctOf(v) { return (max ? v / max * 100 : 0).toFixed(1) + '%'; }
  function wait(w) {
    return !w.n ? 'no wait measured' : w.p50 === null ? 'next good after: n=' + w.n + ', too few for a median'
      : 'next good after a median ' + w.p50 + ' min (P75 ' + w.p75 + '; n=' + w.n + ')';
  }
  var rows = p.byBlock.map(function (g) {
    var seg = [['taken', g.taken], ['phone', g.phone], ['passed', g.passed], ['busy', g.busy]];
    return '<div class="prow"><div class="pname">' + esc(g.name) + '</div><div class="pbar">'
      + seg.map(function (x) {
        return x[1] ? '<i class="p' + x[0] + '" style="width:' + pctOf(x[1]) + '" title="' + esc(x[0]) + ' ' + x[1] + '"></i>' : '';
      }).join('') + '</div><div class="pfig">' + g.good + ' good · took ' + g.taken
      + (g.shareTaken !== null ? ' (' + Math.round(g.shareTaken * 100) + '%)' : '') + ' · no answer ' + g.unanswered
      + ' · let go ' + g.passed + (g.declined ? ' (' + g.declined + ' marked)' : '') + (g.phone ? ' · phone ' + g.phone : '')
      + ' · busy ' + g.busy
      + ' · ' + esc(wait(g.wait)) + '</div></div>';
  }).join('');
  var w = p.waits, wc = w.counts;
  function waitSay(x) {
    var open = x.open ? ', ' + x.open + ' still open' : '';
    return x.p50 === null ? '(too few waits to give a median: n=' + x.n + open + ')'
      : 'after <b>a median ' + x.p50 + ' min</b> (P75 ' + x.p75 + ' min; n=' + x.n + open + ')';
  }
  function waitCell(x) { return x.p50 === null ? (x.n ? 'n=' + x.n + ' (too few)' : '—') : x.p50 + ' / ' + x.p75 + ' min (n=' + x.n + ')'; }
  var blockCols = [['name', ''], ['good', 'good seen'], ['taken', 'taken'],
                   [function (g) { return g.shareTaken === null ? null : Math.round(g.shareTaken * 100) + '%'; }, 'of taken + let go'],
                   ['unanswered', 'no answer'], ['passed', 'let go'], ['declined', '…marked passed'],
                   ['phone', 'on the phone, no Took'], ['busy', 'order already in the car'],
                   [function (g) { return waitCell(g.wait); }, 'to the next good: median / P75']];
  var topCols = [[function (t) { return 'top ' + t.top + '%' + (t.top === p.top ? ' (shown)' : ''); }, 'good ='],
                 ['cut', 'from ($/hr)', '$'], ['good', 'good seen'], ['taken', 'taken'],
                 [function (t) { return t.shareTaken === null ? null : Math.round(t.shareTaken * 100) + '%'; }, 'of taken + let go'],
                 ['passed', 'let go'], ['phone', 'phone'], ['busy', 'busy'],
                 [function (t) { return waitCell(t.waitGood); }, 'to the next good'],
                 [function (t) { return waitCell(t.waitTake); }, 'to the next take']];
  return '<h3 id="s-passed">Good offers not taken on the record</h3>'
    + '<p class="note">Good is the top ' + p.top + '% of ' + (p.report ? 'this report\'s ' + p.n + ' offers over its '
      + (p.days || 0) + ' days' : 'this record\'s own panel $/hr') + ': <b>$' + p.cut.toFixed(2)
    + '/hr or more</b> (' + p.over + ' of ' + p.n + ' offers), one dollar line held fixed across days and blocks — '
    + (p.report ? 'the same line When &amp; where reads, worked out once for the whole report. '
      : 'the offers page\'s Trends ruler, worked out by the same function. ')
    + '<b>No answer</b> is most of what is not taken: a card nobody ticked or Took, counted before <b>let go</b>, '
    + 'which adds the ones you marked passed. <b>Taken</b> is a Took or your ✓ on the card; a card '
    + 'nobody answered for is not taken (silence is never an accept). <b>Busy</b>: it came inside an order\'s hold, Took to '
    + 'its end, or was an Uber add-on — no free driver was choosing it, and an order you never Took leaves its cards '
    + 'reading free. <b>On the phone</b>: Uber\'s earnings screen matched it with no Took, so it is neither taken nor let '
    + 'go here. <b>The wait</b> is minutes online and free from a card let go to the next good card that was not busy, '
    + 'and to your next take: minutes with the rig off are not counted (' + wc.acrossOff + ' of ' + wc.origins
    + ' waits ran across such a stretch), nor the minutes of a trip you took meanwhile (' + (wc.throughHold || 0)
    + ' ran through one)' + (wc.openGood ? '; ' + wc.openGood + ' with no good card after it in the record ' + (wc.openGood === 1
      ? 'is' : 'are') + ' still open, said beside each median and in none' : '') + (wc.lone ? '; ' + wc.lone + ' let go alone, outside any run, start no wait' : '')
    + '. A median needs ' + s.floors.dist + ' waits. History, not advice: no verdict, target or '
    + 'panel line reads it, and the blocks are rows, not a line tuned to the hour.</p>'
    + '<div class="plegend"><span><i class="ptaken"></i>taken</span><span><i class="pphone"></i>on the phone, no Took</span>'
    + '<span><i class="ppassed"></i>let go</span><span><i class="pbusy"></i>order already in the car</span></div>'
    + '<div class="pblocks">' + rows + '</div>'
    + '<p class="note">After one let go, over every block: the next good one came ' + waitSay(w.good)
    + '; your next take came ' + waitSay(w.take) + '.</p>'
    + fold('s-passed-blocks', 'By three-hour block, in full', strategyTable(blockCols, [p.all].concat(p.byBlock)))
    + fold('s-passed-tops', 'At the other rulers (top 10, 20, 30 and 50%)', strategyTable(topCols, p.tops || []));
}

function STRATEGY_SECTION(r) {
  var s = r.strategy, cv = s.curve, f = s.floors, c = s.counts;
  function ul(xs) { return '<ul class="lines">' + xs.map(function (l) { return '<li>' + esc(l) + '</li>'; }).join('') + '</ul>'; }
  function seenRows(list) {
    return strategyTable([['name', ''], ['n', 'offers'], ['outings', 'shift days'],
      [function (x) { return x.ph.p25; }, '$/hr P25', '$'], [function (x) { return x.ph.p50; }, 'median', '$'],
      [function (x) { return x.ph.p75; }, 'P75', '$'], [function (x) { return x.ph.p90; }, 'P90', '$'],
      [function (x) { return x.pm.p25; }, '$/mi P25', '$'], [function (x) { return x.pm.p50; }, 'median', '$'],
      [function (x) { return x.pm.p75; }, 'P75', '$'], [function (x) { return x.pm.p90; }, 'P90', '$'],
      ['freeHours', 'hours free', 'h'], ['perFreeHour', 'offers / hr free', 'r']], list,
      function (x) { return x.ph.p50 === null; });
  }
  function actRows(list, expected) {
    var cols = [['name', ''], ['timed', 'timed'], ['together', 'carried with another'], ['ratio', 'actual ÷ card min', 'x'],
                ['ratioMedian', 'typical order', 'x'], ['cardPH', 'median card $/hr', '$'], ['actualPH', 'median actual $/hr', '$'],
                ['milesN', 'with miles'], ['mileRatio', 'GPS ÷ card mi', 'x']];
    if (expected) cols.push(['expected', 'card ÷ ratio', '$']);
    return strategyTable(cols, list, function (x) { return x.ratio === null; });
  }
  function sliceRows(list) {
    return strategyTable([['name', ''], ['days', 'shift days'], ['freeHours', 'hours free', 'h'], ['offers', 'offers seen free'],
      ['timed', 'timed orders'], [function (x) { return x.best ? x.best.T : null; }, 'best line', '$'],
      [function (x) { return x.best ? x.best.value : null; }, '$/hr on shift', '$'],
      [function (x) { return x.best ? '$' + x.best.from + '–$' + x.best.to : null; }, 'about the same'],
      [function (x) { return x.everything.gross; }, 'taking everything', '$'],
      ['actualAtBest', 'actual $/hr of cards at the best line', '$']], list,
      function (x) { return !x.drawn || !x.best; });
  }
  var pointCols = [['T', 'line ($/hr+)', '$'], ['n', 'offers seen free'], ['perFreeHour', 'per hour free', 'r'],
                   ['pay', 'mean pay', '$'], ['cardMin', 'mean card min', 'r'], ['ratio', 'actual ÷ card', 'x'],
                   [function (p) { return p.ratioFrom === 'carried' ? 'carried from $' + p.ratioAt : p.ratioFrom; }, 'ratio from'],
                   ['gross', 'gross $/hr on shift', '$'], ['ci', '95%', '$ci'], ['net', 'net $/hr on shift', '$'],
                   [function (p) { return p.thin ? 'thin' : ''; }, '']];
  var mileCols = pointCols.filter(function (col) { return col[1] !== '95%'; }).map(function (col) {
    return col[0] === 'T' ? ['T', 'line ($/mi+)', '$'] : col;
  });
  function isThin(p) { return p.thin; }
  var mi = s.miles || {};
  // The order is the tab's own, top to bottom: the lines; the curve drawn,
  // its table folded under it; the slices drawn, their tables folded; the
  // $/mi curve folded whole (for reading only); then the two descriptive
  // halves, each with its all-offers row open and its breakdowns folded.
  // Every heading that opens a part has an id, so the Overview links to it.
  return '<section data-tab="strategy"><h2>Strategy — what $/hr to expect, and what holding out paid</h2>'
    + '<p class="exp">Descriptive. What your own record shows about the offers seen, what cards turned into, and what '
    + 'holding out for a line would have paid per hour on shift. Nothing here is an accept rule or changes a verdict; '
    + 'the $/mi figures are for reading only (AUDITS.md, Settled: a $/mile rule replayed 24% below $/hr).</p>'
    + ul(s.lines)
    + '<h3 id="s-curve">The accept-threshold curve</h3>'
    + '<p class="note">For each line T on the panel\'s $/hr: of the offers seen with no order in the car, those at T or more '
    + 'came at λ(T) an hour; each paid pay(T) and took time(T), its card minutes × the actual ÷ card ratio of the timed '
    + 'orders whose card was at T or more. <b>Effective $/hr on shift = pay(T) ÷ (1/λ(T) + time(T))</b> — every free hour '
    + 'waiting plus every order\'s time, over what they paid. A point with fewer than ' + f.curveOffers + ' offers is '
    + '<b>thin</b> (hollow): it is never the best and never in the flat region (shaded: within '
    + Math.round((1 - f.plateau) * 100) + '% of the best). The band is a 95% interval with shift days resampled ('
    + (cv.boots ? cv.boots + ' times' : 'not drawn: it needs ' + f.bootOutings + ' shift days') + '). '
    + '<b>Net</b> takes off ' + (cv.cost.perMile !== null ? '$' + cv.cost.perMile.toFixed(2) + '/mi (the rate the rows carry)'
      : 'nothing: the rows carry no running cost') + ' on the card\'s miles × '
    + (cv.cost.mileRatio !== null ? cv.cost.mileRatio.toFixed(2) + ' (GPS ÷ card miles over ' + cv.cost.milesN + ' orders)' : '1 (too few orders with miles)')
    + '. Dotted: taking everything. It reads low by whatever stacking earns: a driver who takes nothing while carrying.</p>'
    // The wide drawing on a laptop, the small one on a phone (the CSS picks).
    + '<div class="plot wide">' + strategyChart(cv) + '</div>'
    + '<div class="plot small">' + strategyChart(cv, 'small') + '</div>'
    + fold('s-points', 'Every point of the curve', strategyTable(pointCols, cv.points, isThin))
    + PASSED_PART(s)
    + GOLD_PART(s)
    + '<h3 id="s-slices">The same, by time of day, app and weekday</h3>'
    + '<p class="note">Point estimates, each slice\'s own free hours, offers and (with ' + f.ratio + ' or more) its own timed '
    + 'orders for the ratio. An app\'s curve is that app\'s cards alone in the same free hours. Read as description: a line '
    + 'tuned to the hour earned less on the nights it was not fitted to (AUDITS.md, Settled), and the held-out check in '
    + 'the lines above runs that test again on this record.</p>'
    + '<div class="plot fluid">' + blockChart(s.slices.block) + '</div>'
    + fold('s-blocks', 'By three-hour block', sliceRows(s.slices.block))
    + fold('s-apps', 'By app', sliceRows(s.slices.app))
    + fold('s-week', 'Weekday and weekend', sliceRows(s.slices.week))
    + fold('s-mile', 'The curve on $/mi — for reading only',
           '<p class="note">The same arithmetic with the line on pay ÷ card miles. Not an accept rule: printed because it was asked for.</p>'
           + strategyTable(mileCols, s.curveMile.points, isThin))
    + '<h3 id="s-seen">What offers look like</h3>'
    + '<p class="note">Every offer seen that the rig stands behind (' + c.offers + ', once per offer; ' + c.untrusted
    + ' untrusted and ' + c.unrated + ' with no rate left out). $/hr is the panel\'s; $/mi is pay over the card\'s miles, '
    + 'nothing off. Weekend is a Saturday or Sunday shift day (4am to 4am). A quartile needs ' + f.dist + ' offers. '
    + 'Offers per hour free counts only offers seen with no order in the car, over the hours with none (' + c.freeHours
    + ' h of ' + c.shiftHours + ' h on shift); an area has no free hours of its own here (the Busy tab has them, off the GPS).</p>'
    + seenRows([s.seen.all])
    + fold('s-seen-app', 'By app', seenRows(s.seen.byApp))
    + fold('s-seen-block', 'By three-hour block', seenRows(s.seen.byBlock))
    + fold('s-seen-week', 'Weekday and weekend', seenRows(s.seen.byWeek))
    + fold('s-seen-town', 'By town (the card\'s own)', seenRows(s.seen.byArea || [])
      + (s.seen.areaThin ? '<p class="note">' + s.seen.areaThin.areas + ' towns under ' + f.dist + ' offers (' + s.seen.areaThin.offers
         + ' offers) and ' + s.seen.areaThin.noArea + ' offers with no town are not listed.</p>' : ''))
    + '<h3 id="s-actual">How cards turn into actuals</h3>'
    + '<p class="note">Over the orders this report timed at the door (as the Your takes tab: ' + c.timed + ' of ' + c.orders
    + ' taken; ' + c.unmeasured + ' with no time at the door, ' + c.addons + ' add-ons (their card minutes are an increment), '
    + c.tooSoon + ' put down in under ' + f.tooSoon + ' of the card, ' + c.clock + ' with a clock that stepped or held over '
    + f.holdMaxMin + ' min, left out). <b>Actual ÷ card</b> is the sum of actual minutes over the sum of card minutes, with '
    + 'the typical order\'s ratio beside it; a ratio needs ' + f.ratio + ' orders. Card and actual $/hr are both net of the '
    + 'card\'s running cost, as the panel\'s figure is. <b>Card ÷ ratio</b> is what a card in that band has turned into. '
    + 'Miles: the order record\'s odometer (' + (mi.odometer || 0) + ') or the GPS log (' + (mi.log || 0) + ')'
    + (mi.gps ? '' : '; no GPS log reached this report') + '.</p>'
    + actRows([s.actual.all])
    + fold('s-act-rate', 'By card $/hr', actRows(s.actual.byRate, true))
    + fold('s-act-app', 'By app', actRows(s.actual.byApp))
    + fold('s-act-length', 'By card length', actRows(s.actual.byLength))
    + fold('s-act-block', 'By three-hour block (of the Took)', actRows(s.actual.byBlock))
    + fold('s-act-town', 'By town (the card\'s own)', actRows(s.actual.byArea || []))
    + paidSection(s.paid)
    + '<p class="note">The shift: every offer seen and every order\'s hold, joined across silences under ' + f.breakMin
    + ' minutes; free is that less every hold (Took to its end, however it ended; the card\'s minutes where it has none). '
    + c.duplicates + ' repeat readings folded, ' + c.alone + ' offers alone in a silence, ' + c.held + ' seen with an order '
    + 'in the car, ' + c.addOnCards + ' add-on cards: none of them in λ.</p>'
    + '</section>\n';
}

/* The page's tabs, grouped by the question each answers (7 Nov 2026, the
 * owner: "consider how the page and tabs are laid out, is there a better
 * format for all this information?"). Twenty tabs in one wrapping row of
 * pills was four rows of buttons on a phone, below a banner taller than the
 * screen, before a single figure. Now four groups — the overview, what to
 * take, where and when, and the record — one row of groups and, under it,
 * the chosen group's tabs, which scroll sideways on a narrow screen. Every
 * tab and every hash the page ever had is still here (#targets, #strategy,
 * #best, ... a bookmark keeps working); only #overview is new, and it is
 * where a bare address opens.
 *
 * [group id, group label, [[tab id, tab label, what it answers, hours?], ...]]
 * `hours` marks the tabs the Hours picker reaches (they draw a view of
 * R.views); on the others it is hidden rather than left offering a choice
 * that changes nothing on the page. */
var GROUPS = [
  ['overview', 'Overview', [
    ['overview', 'Overview', 'The few numbers that matter, each linking to its tab.', false]]],
  ['take', 'What to take', [
    ['strategy', 'Strategy', 'What $/hr to expect, what cards turn into, what holding out for a line paid.', false],
    ['targets', 'Targets', 'The offers page\'s Targets lines, word for word, and the richer areas.', false],
    ['apps', 'Uber vs DoorDash', 'Each app\'s offers, $/hr, $/mi and your take, per area.', true],
    ['ppm', '$/mi', 'Pay over the card\'s miles per area — for reading, not a rule.', true]]],
  ['where', 'Where & when', [
    ['whenwhere', 'When & where', 'Which area gave the most good offers per hour waited, on the day and hours you pick.', false],
    ['around', 'Offers around you', 'Where the car was when each offer came up, good or not, home left out (the map needs the internet).', false],
    ['places', 'Places', 'Pinned pickups ranked against the same hours elsewhere.', true],
    ['restaurants', 'Restaurants', 'Pay by the name on the card, placed or not.', true],
    ['map', 'Map', 'The places and the 2-mile grid on a map (needs the internet).', true],
    ['towns', 'Towns', 'The card\'s own town, ranked.', true],
    ['grid', 'Grid', 'A 2-mile grid by the pickup\'s pin, ranked.', true],
    ['busy', 'Busy', 'Offers per hour while parked, by area and hours (GPS).', true],
    ['waited', 'Waited', 'Offers by where the car was when each came up (its own fix), against the same hours.', true],
    ['waits', 'Store waits', 'The rig\'s measured waits beside a place\'s pay.', true],
    ['after', 'After a drop', 'Where trips leave you: minutes to the next take.', true],
    ['strand', 'Strand risk', 'How far a store\'s cards run and where its trips end.', true],
    ['stack', 'Add-ons', 'Add-on and stacking chance per store.', true]]],
  ['record', 'Record', [
    ['best', 'Best offers', 'Where the top 10% turns up, per hour of waiting, dead miles, offer size.', true],
    ['takes', 'Your takes', 'What you took and what it really paid.', true],
    ['quiet', 'Gone quiet', 'Places and towns with fewer offers lately.', false],
    ['trend', 'Trend', 'Each area\'s score by week.', false],
    ['coverage', 'Coverage', 'What could be placed, by day and level, and what that biases.', false],
    ['method', 'Method', 'How every figure was measured.', false]]]
];
// ...and flat, in that order: [id, label], as the page has always listed them.
var TABS = [];
GROUPS.forEach(function (g) { g[2].forEach(function (t) { TABS.push([t[0], t[1]]); }); });

var EXPERIMENTAL = '<p class="exp">Experimental, descriptive: counts, medians and intervals. Nothing in this tab '
  + 'is ranked by a test or coloured, and none of it is a rule.</p>';

// The second pass's tabs, keyed by tab id (html() writes them in the nav's
// order). Each table sits in a fold() under its heading.
function MORE_SECTIONS(r) {
  var out = Object.create(null);
  function sec(id, title, note, divs) {
    out[id] = '<section data-tab="' + id + '"><h2>' + title + '</h2>' + EXPERIMENTAL + '<p class="note">' + note + '</p>'
      + divs.map(function (d) { return fold('f-' + d[0], d[1], '<div id="m-' + d[0] + '"></div>'); }).join('')
      + '</section>\n';
    return '';
  }
  var tk = r.takes;
  sec('takes', 'Your takes, and what they really paid',
             'Taken = the offer\'s id is one of the journal\'s taken orders (server.js takenRuns: a put-down row '
             + 'carrying its Took), ' + tk.taken + ' in the window, ' + tk.onCounted + ' on rows the rig stands behind. '
             + 'Take rate is taken over offered, with a Wilson 95% interval. <b>Real $/hr</b> is the card\'s pay over '
             + 'the real time, Took to put-down, before the car\'s cost (as the offers page\'s "Card against what it '
             + 'took"), and <b>only for orders put down at the door</b> by the GPS, the app\'s own screen, or a Drop '
             + 'press the GPS log timed (' + tk.timed + ' in all, ' + tk.gpsTimed + ' of them a press GPS-timed: the '
             + 'stop the press belongs to, its end the car leaving the door — Method says the rule). A press with no '
             + 'such stop (' + (tk.pressed - tk.gpsTimed) + ' of ' + tk.pressed + ') can come before the door and is left out. '
             + '<b>Real − card</b> is real minutes less the card\'s minutes. A median needs ' + r.realMedN
             + ' timed trips and an interval ' + r.descMinN + '; an area needs ' + r.descMinN
             + ' offers or one take to be listed.',
             [['takesPlace', 'By place'], ['takesTown', 'By town'], ['takesGrid', 'By ' + r.gridMi + '-mile cell']])
    + sec('apps', 'Uber against DoorDash',
          'Per area, each app\'s offers, median $/hr, median $/mi and the share you took. The app is the row\'s own, '
          + 'else offer-parser.js screenType off its text. A median needs ' + r.descMinN + ' offers of that app; an '
          + 'area needs ' + r.descMinN + ' offers. The first row is every area together.',
          [['appsPlace', 'By place'], ['appsTown', 'By town'], ['appsGrid', 'By ' + r.gridMi + '-mile cell']])
    + sec('ppm', '$/mi — pay over the card\'s miles',
          '<b>$/mi is shown for reading, not as an accept rule</b> (AUDITS.md, Settled: a $/mile rule measured worse '
          + 'than $/hr on the replay). The offers page\'s payPerMile: the card\'s pay over its miles, nothing taken '
          + 'off, no card under a tenth of a mile. Median with a 95% bootstrap interval, areas with '
          + r.descMinN + ' or more; per app where that app has ' + r.descMinN + '. Click a column to sort.',
          [['ppmPlace', 'By place'], ['ppmTown', 'By town'], ['ppmGrid', 'By ' + r.gridMi + '-mile cell']])
    + sec('waits', 'Restaurant waits beside pay',
          'The rig\'s measured waits at a store (server.js storeWaitsOut: name, how many, the median and the worst '
          + 'minutes, and how many were found from the stop pattern — the car\'s first stop of two minutes or more '
          + 'after the Took, for a pickup the GPS never visited because it was never pinned; '
          + r.waitsOnRecord + ' stores on record' + (r.waitsFrom ? ', from ' + esc(r.waitsFrom) : '') + ') joined to a place by its name as Assemble.sameStore compares '
          + 'two, and only where the join is not a guess: not a chain\'s name, one store of that name on record, and '
          + 'one place of that name here. The waits are all hours; the pay follows the hours picked.',
          [['waits', 'Places']])
    + sec('strand', 'Strand risk per store',
          'Per pickup place: how far its cards run (median card miles), where its taken trips ended — by town and '
          + 'by 2-mile cell, counts only, a cell named only where "Where trips leave you" names it — its own '
          + 'measured minutes to the next take after those trips, and the wait its trips\' towns predict: the mean '
          + 'of the town table\'s median wait over its trips, shown when the towns that clear that table\'s floor '
          + 'cover half its trips.',
          [['strand', 'Places']])
    + sec('busy', 'How busy each area is, while you wait',
          (r.spells.gps ? r.spells.n + ' spells, ' + r.spells.hours + ' hours. ' : '<b>No GPS log was given (--gps), '
            + 'so there are no spells.</b> ')
          + 'A spell is the car parked: every GPS fix within ' + r.spellM + ' m of the first, for '
          + Math.round(r.spellMinS / 60) + ' minutes or more, no gap over ' + Math.round(r.spellGapS / 60)
          + ' minutes, and <b>no order in the car</b> (every taken order\'s Took to put-down is cut out). '
          + 'Thresholds chosen, not measured. Per area and three-hour block: hours waited, offers the rig counted '
          + 'per hour of it, the share of spells that saw an offer the rig said take, and the minutes to the first. '
          + 'Under ' + r.spellMinN + ' spells or ' + r.minOutings + ' shift days a row gives its n only. The town is '
          + 'the NucBox map\'s name for the 2-mile cell\'s centre (' + r.spells.towns + ' spells named).',
          [['busyTown', 'By town'], ['busyGrid', 'By ' + r.gridMi + '-mile cell']])
    + sec('stack', 'Add-on and stacking chance per store',
          'The share of a store\'s offers whose card was an Uber add-on, more than one order, more than one '
          + 'dropoff, or an early look — each over the cards where it could be read (the row\'s field, else its '
          + 'text by scan_pi\'s own patterns). Places with ' + r.descMinN + ' offers or more.',
          [['stack', 'Places']])
    + sec('quiet', 'Gone quiet',
          'The last ' + r.quietDays + ' days of the record (to its newest offer, not today) against the rest'
          + (r.quiet.place.cut ? ', split at ' + esc(r.quiet.place.cut) + ' (' + r.quiet.place.outingsBefore
             + ' shift days before, ' + r.quiet.place.outingsRecent + ' since)' : '') + '. <b>Fewer offers</b>: '
          + 'with ' + r.minN + '+ offers before and 3+ shift days since, the before rate per shift day out predicts '
          + '5 or more since, and a count this low has Poisson p < ' + r.alpha + '. <b>Lower score</b>: '
          + r.descMinN + '+ hour-held scores each side, recent below before, rank test p < ' + r.alpha
          + '. All hours only.',
          [['quietPlace', 'By place'], ['quietTown', 'By town']])
    + sec('trend', 'Trend by week',
          'Each ranked area\'s score — its offers\' $/hr against the other cells in the same three-hour block — '
          + 'by ISO week of the shift day, weeks with ' + r.descMinN + ' or more offers only (a week under that is '
          + 'left out of the line, not drawn as zero; hover a line for its weeks). The dashed rule is zero; every '
          + 'line is on one scale. All hours only.',
          [['trendPlace', 'By place'], ['trendTown', 'By town']]);
  return out;
}

/* The When & where tab (whenWhere). The pickers and the rule are written
 * here, so a page with its script off still says what was measured and
 * where the cutoff sits; the script fills the slot's line and its areas from
 * R.whenwhere, and does nothing to them but pick and sort. */
function wwDayName(o) {
  return o === 'any' ? 'Any day' : o === 'wkday' ? 'Weekdays (Mon–Fri)' : o === 'wkend' ? 'Weekends (Sat, Sun)'
    : WW_DAYS[Number(o)];
}
function WHENWHERE_SECTION(r) {
  var w = r.whenwhere, ti = w.tops.indexOf(w.top), any = w.slots['any|any'];
  function opt(v, text, on, name) {
    return '<option value="' + esc(v) + '"' + (on ? ' selected' : '') + (name ? ' data-name="' + esc(name) + '"' : '')
      + '>' + esc(text) + '</option>';
  }
  function hoursIn(key) { var sl = w.slots[key]; return (sl ? sl.all.h : 0).toFixed(1) + ' h'; }
  function cutSaid(i) { return w.cuts[i] === null ? 'no offers yet' : 'good = top ' + w.tops[i] + '%: ≥ ' + money(w.cuts[i]) + '/hr'; }
  // By town where the NucBox named the cells the car waited in; else the cells.
  var towns = any ? any.town.ranked.length + any.town.thin.length : 0;
  return '<section data-tab="whenwhere"><h2>When &amp; where — which area, on the day and hours you pick</h2>'
    + '<p class="exp">Experimental, descriptive. <b>Offered, not earned</b>: offers are dispatched near the car, so '
    + 'only areas you already wait in compete, and a good offer seen is not one taken. Nothing here is a rule, and '
    + 'nothing on the rig reads it.</p>'
    + '<p class="note">Every area where the car waited, for the slot you pick, ranked by <b>good per hour waited '
    + '(each gap capped at ' + r.waited.creditMaxMin + ' min, none while carrying)</b>. That is not the offers page\'s '
    + 'Trends "good per hour online", which counts every minute the rig was scanning, carrying included: the two '
    + 'measure different hours, so their figures differ by design. <b>Day</b> is the driver\'s, 4am to 4am: 1am on a Saturday is Friday night; Weekends are the '
    + 'driver\'s Saturday and Sunday. <b>Where</b> is the car\'s own GPS fix on each card that came with no order in '
    + 'the car (the Waited tab\'s line: ' + w.cards + ' cards), by the town of its ' + r.gridMi + '-mile cell or the '
    + 'cell itself; <b>hours waited</b> are inferred as that tab infers them, each card\'s time to the next, at most '
    + r.waited.creditMaxMin + ' minutes and none across a silence over ' + r.nextGapMin + '. <b>Good</b> is the card\'s '
    + '$/hr at or over one fixed cutoff, the top share picked of all ' + w.offers + ' offers in this report\'s range, '
    + 'the same dollars in every slot and the same as the Strategy tab\'s section 7, over this report\'s '
    + r.outings + ' days: <b id="wwCut">' + esc(cutSaid(ti)) + '</b>. The interval is the exact 99% '
    + 'Poisson interval on the good offers over the hours, widened by how much more an area\'s days differ than '
    + 'chance alone would (×' + (w.phi ? w.phi.town[ti].toFixed(2) + ' by town, ×' + w.phi.cell[ti].toFixed(2) + ' by cell'
    : '1') + ' on this record); an area is <b>marked only where it lies wholly above or '
    + 'below the slot\'s own rate</b>, and printed without colour otherwise. About 1 coloured square in 100 can be '
    + 'chance. Ranked at ' + w.minHours + ' h waited on '
    + w.minDays + ' shift days in the slot; under that, listed as too little time there yet.</p>'
    + '<div class="bar" id="wwBar">'
    + '<label>Day <select id="wwDay">' + w.dayOpts.map(function (o) {
      return opt(o, wwDayName(o) + ' · ' + hoursIn(o + '|any'), o === 'any', wwDayName(o));
    }).join('') + '</select></label>'
    + '<label>Hours <select id="wwBlock">' + w.blockOpts.map(function (o) {
      var nm = o === 'any' ? 'Any time' : w.blocks[Number(o)];
      return opt(o, nm + ' · ' + hoursIn('any|' + o), o === 'any', nm);
    }).join('')
    // The single hours after the blocks, in one picker rather than a second
    // control: on a phone one select is one tap, and a toggle beside it was
    // a fifth control on a bar that already wraps to four lines.
    + '<optgroup label="One hour">' + w.hourOpts.map(function (o, i) {
      return opt(o, w.hours[i] + ' · ' + hoursIn('any|' + o), false, w.hours[i]);
    }).join('') + '</optgroup></select></label>'
    + '<label>Good <select id="wwTop">' + w.tops.map(function (t, i) {
      return opt(String(i), 'top ' + t + '%' + (w.cuts[i] === null ? '' : ' (≥ ' + money(w.cuts[i]) + '/hr)'), i === ti);
    }).join('') + '</select></label>'
    + '<label>Area <select id="wwUnit">' + opt('town', 'Town', towns > 0) + opt('cell', r.gridMi + '-mile cell', !towns)
    + '</select></label></div>'
    + '<p class="lead" id="wwSlot"></p>'
    + '<div class="wwstrip" id="wwStrip" role="group" aria-label="Good offers per hour waited, by clock hour"></div>'
    + '<p class="note" id="wwStripNote"></p><div id="wwTable"></div><div id="wwThin" class="thin"></div>'
    + '</section>\n';
}

/* The Offers around you tab (aroundYou). The pickers are When & where's —
 * the same choices, the same driver day and blocks and hours, the same
 * cutoffs — with their own ids, so each tab keeps its own pick. What is
 * left out, and why, is written here, so a page with no script (or no
 * internet for the map) still says it. */
function AROUND_SECTION(r) {
  var a = r.around, w = r.whenwhere, ti = w.tops.indexOf(w.top), L0 = a.left;
  function opt(v, text, on, name) {
    return '<option value="' + esc(v) + '"' + (on ? ' selected' : '') + (name ? ' data-name="' + esc(name) + '"' : '')
      + '>' + esc(text) + '</option>';
  }
  var drawn = a.dots.b.length;
  return '<section data-tab="around"><h2>Offers around you — where the car was when each offer came up</h2>'
    + '<p class="exp">Experimental, descriptive. <b>Offered, not earned</b>: offers are dispatched near the car, so '
    + 'this shows the offers that came where you already wait, not what a place you never tried would send. '
    + 'Nothing here is a rule, and nothing on the rig reads it.</p>'
    + '<p class="note">One dot per offer that came with no order in the car (the Waited tab\'s line: '
    + a.cards + ' cards), at the car\'s own GPS fix the gate passed — never a pin, never DoorDash\'s map label. '
    + '<span class="k up">●</span> good: its $/hr at or over the cutoff picked, the same dollars in every slot '
    + '(<b id="aCut">' + (w.cuts[ti] === null ? 'no offers yet' : 'top ' + w.top + '%: ≥ ' + money(w.cuts[ti]) + '/hr')
    + '</b>); <span class="k grey">●</span> the rest. Each dot sits in its ' + a.binMi + '-mile square, spread inside '
    + 'it, so a busy spot is a disc of dots whose colours are its offers: a dot is one offer, never an area\'s '
    + 'average, so no square is coloured by a share. A square is drawn only where the car was on ' + a.binDays
    + ' shift days or more, so a door passed once (a drop) is never a dot. <b>Home is left out</b>: each day\'s '
    + 'starting stay (every card before the car first moves more than ' + a.homeMi + ' mi from where the day began) '
    + 'and every card within ' + a.homeMi + ' mi of a place two or more days began at — so going online at home '
    + 'never draws home. That also leaves out a day begun at a restaurant until the car leaves it. Left out: '
    + L0.start + ' cards in a starting stay, ' + L0.usual + ' near a usual start (' + a.usualDays + ' of '
    + a.homeDays + ' days began at one), ' + L0.oneDay + ' in a square seen on one day only, ' + L0.noFix
    + ' with no fix the gate passed. ' + drawn + ' dots drawn.</p>'
    + '<div class="bar" id="aBar">'
    + '<label>Day <select id="aDay">' + w.dayOpts.map(function (o) {
      return opt(o, wwDayName(o), o === 'any', wwDayName(o));
    }).join('') + '</select></label>'
    + '<label>Hours <select id="aBlock">' + w.blockOpts.map(function (o) {
      var nm = o === 'any' ? 'Any time' : w.blocks[Number(o)];
      return opt(o, nm, o === 'any', nm);
    }).join('')
    + '<optgroup label="One hour">' + w.hourOpts.map(function (o, i) {
      return opt(o, w.hours[i], false, w.hours[i]);
    }).join('') + '</optgroup></select></label>'
    + '<label>Good <select id="aTop">' + w.tops.map(function (t, i) {
      return opt(String(i), 'top ' + t + '%' + (w.cuts[i] === null ? '' : ' (≥ ' + money(w.cuts[i]) + '/hr)'), i === ti);
    }).join('') + '</select></label></div>'
    + '<p class="lead" id="aSays"></p>'
    + '<div id="aMap" class="amap" role="img" aria-label="Where the car was when each offer came up"></div>'
    + '<p class="note" id="aMapNote"></p>'
    + '<h3>Good offers by distance from your most-used waiting area</h3>'
    + '<p class="note">' + (a.centre ? 'Rings of ' + a.ringMi + ' mile from the centre of the ' + r.gridMi
      + '-mile cell where the car waited longest among the dots drawn (' + a.centre.hours + ' h credited, the home '
      + 'stays already out), measured from each dot\'s square. The share of each ring\'s offers that were good, '
      + 'with its 95% Wilson interval; a ring under ' + r.descMinN + ' offers gives its n only. The last ring is '
      + a.rings + ' mi and beyond.' : 'No dot to measure from yet.') + '</p>'
    + '<div id="aRings" class="hbars"></div>'
    + '<h3>Good offers per hour waited, by area, for the slot picked</h3>'
    + '<p class="note">When &amp; where\'s own table for the same day and hours, drawn: good offers per hour waited '
    + 'there, its 99% interval as the whisker, coloured only where that tab marks it (wholly above or below the '
    + 'slot\'s own rate). Ranked at ' + w.minHours + ' h on ' + w.minDays + ' shift days. That table counts every '
    + 'waiting card, so home is not left out of it yet (AUDITS.md, Open).</p>'
    + '<div id="aAreas" class="hbars"></div>'
    + '<h3>Good offers by the card\'s own drive to the pickup</h3>'
    + '<p class="note">Needs no GPS: the miles to the pickup the card itself printed ("x min (y mi) away", the leg '
    + 'offer-parser.js splits off where the card prints it — mostly Uber\'s), over every counted offer in the slot, '
    + 'an order in the car or not. The share good at the cutoff picked (95% Wilson) and the median $/hr; a band '
    + 'under ' + r.descMinN + ' offers gives its n only. To read, not a distance rule.</p>'
    + '<div id="aPickup" class="hbars"></div>'
    + '</section>\n';
}

/* The Best offers tab: plain lines first, then where good offers turn up
 * per hour of waiting and what working an area paid, then the share tests,
 * then the descriptive tables. */
function BEST_SECTION(r) {
  function tbl(id, title) { return fold('f-b-' + id, title, '<div id="b-' + id + '"></div>'); }
  var b = r.best;
  return '<section data-tab="best"><h2>Best offers — where the top of the pay turns up</h2>'
    + '<p class="exp">Experimental. Offered, not earned; only near where you wait; and see Coverage for what could '
    + 'be placed. Thresholds are percentiles of your own offers, to read — not an accept rule.</p>'
    + '<ul class="lines">' + bestLines(r).map(function (l) { return '<li>' + esc(l) + '</li>'; }).join('') + '</ul>'
    + '<p class="note"><b>Top 25% / top 10%</b>: an offer at or over the 75th / 90th percentile $/hr of EVERY offer '
    + 'in its own three-hour block (' + b.tierMinN + ' offers for a block to have one), so each hour is held to '
    + 'itself. <b>Rig said take</b> is the rig\'s own verdict at the time. <b>Per hour of waiting</b> counts the '
    + 'offers that came while the car was parked in that area with no order in it (the Busy tab\'s spells), over '
    + 'the hours parked; ' + b.spellMinN + ' spells on ' + r.minOutings + ' shift days for a figure. <b>Expected $/hr '
    + 'working it</b> = pay of the orders taken while waiting there (a Took inside the spell or ' + b.takeSlackMin
    + ' min after) ÷ (hours waited + those orders\' real hours); only orders with a real time count, on both '
    + 'sides, so many untimed takes make it read low. <b>If every top 10% taken</b> is the pay of the top-10% '
    + 'offers seen while waiting ÷ (hours waited + their card minutes): <b>offered, not earned</b>, and it ignores '
    + 'that taking one ends the wait.</p>'
    + tbl('waitTown', 'Waiting, by town and hours') + tbl('waitGrid', 'Waiting, by ' + r.gridMi + '-mile cell and hours')
    + '<h3>Does the top-10% share differ by area? (all hours, hours held)</h3><p class="note">A permutation of the '
    + 'top-10% marks within each three-hour block (' + r.shuffles + ' shuffles); the score is a group\'s share less '
    + 'what the other groups showed in the same hours, with a 95% bootstrap interval. Coloured only where the test '
    + 'beats chance and the interval is clear of zero. ' + r.minN + ' offers on ' + r.minOutings + ' shift days.</p>'
    + fold('shareTestsFold', 'The tests, group by group', '<div id="shareTests"></div>')
    + tbl('goodTown', 'Good offers by town') + tbl('goodRest', 'Good offers by restaurant (the name on the card)')
    + tbl('goodGrid', 'Good offers by ' + r.gridMi + '-mile cell') + tbl('goodApp', 'Good offers by app')
    + '<h3>Offer size</h3><p class="note">By card miles: under 4, 4–8, 8–12, 12 and over. Median and P90 $/hr, '
    + 'top-10% share, and $/mi — <b>$/mi for reading, not an accept rule</b>. A median needs ' + r.descMinN + '.</p>'
    + tbl('sizeTown', 'By town') + tbl('sizeApp', 'By app') + tbl('sizeRest', 'By restaurant')
    + '<h3>Dead miles after a drop</h3><p class="note">' + (b.dead.gps ? b.dead.n + ' trips measured. '
      : '<b>No GPS log was given (--gps), so nothing is measured.</b> ')
    + 'From each put-down at the door to the next Took: the GPS log\'s miles (straight lines between fixes ten '
    + 'seconds apart, a little under the road), plus the next card\'s printed drive to the pickup where Uber printed '
    + 'one. Not counted: no Took within ' + b.deadMaxMin + ' minutes, or the log broken between. <b>Unpaid share</b> '
    + '= dead ÷ (dead + the delivered trips\' card miles). By the dropoff\'s town and cell, counts only; a cell under '
    + r.dropMinN + ' measured trips is not named.</p>'
    + tbl('deadTown', 'By dropoff town') + tbl('deadGrid', 'By dropoff cell')
    + '</section>\n';
}

function METHOD(r) {
  var b = r.best;
  return '<ul>'
    + '<li><b>Placing a pickup, third pass</b>: map-view.js\'s NbxSearch chain — the door as printed, the type word '
    + 'left out, the directional the other way, the street index\'s one street for the name as read, the street '
    + 'alone where nothing answered; a corner by the street index; a numberless street by its <code>whole</code> '
    + 'answer; a refused door\'s candidates by the distance band (road miles off the router, held to the card\'s '
    + 'own figure — distance only). Levels: door, corner, name (a point); band, area, street (an area, with its '
    + 'spread). <b>Places</b> take a point, and an area only within ' + PLACE_SAME_MI + ' mi of a point of the same store '
    + 'or with its candidates within ' + b.placeApproxMi + ' mi (chosen); <b>the grid</b> every level within '
    + b.areaMi + ' mi; towns unchanged.</li>'
    + '<li><b>A DoorDash pickup by its printed door</b>, as the rig asks it: the store\'s door the card printed under '
    + 'its name (<code>pickupLine</code>, or its line among the card\'s stores) first, at door level, the store\'s '
    + 'name along that street only after the door refused; then the name alone as before (one place of that name '
    + 'in the disc). With neither, the door\'s refusal is what is counted.</li>'
    + '<li><b>Cards with no fix</b>: a printed door with its town or ZIP is searched in the region '
    + (b.region ? 'from ' + b.region.box.s.toFixed(2) + ',' + b.region.box.w.toFixed(2) + ' to ' + b.region.box.n.toFixed(2)
       + ',' + b.region.box.e.toFixed(2) + ' (the box round ' + b.region.fixes + ' good card fixes, ' + b.region.marginMi
       + ' mi wider each way)' : '(none: the record has no good card fix)')
    + ', kept only at door or corner level with the printed town or ZIP at the pin. A store name with no fix is '
    + 'not placed: a chain is everywhere.</li>'
    + '<li><b>A pressed drop timed by the GPS</b> (chosen, not measured): the stop — every fix within ' + b.stopM
    + ' m for ' + b.stopMinS + ' s or more, beginning after the Took — that contains the press, else the first '
    + 'starting within ' + b.pressAfterMin + ' min after it, else the last ending within ' + b.pressBeforeMin
    + ' min before it; the real end is that stop\'s end, the car leaving the door. No stop: still left out. '
    + 'A stop reached with the car\'s GPS miles since the Took under ' + b.shortMiles + ' of the card\'s (an '
    + 'add-on aside) is the pickup\'s, not the door: left out too. '
    + (b.presses ? b.presses.timed + ' of ' + b.presses.pressed + ' presses timed (' + b.presses.inside + ' inside, '
       + b.presses.early + ' early, ' + b.presses.late + ' late; ' + (b.presses.short || 0)
       + ' at a stop not driven to).' : 'No GPS log, so none timed.') + '</li>'
    + '<li><b>Top tiers, P75 and P90</b>: percentiles of $/hr (linear between order statistics); intervals are '
    + 'bootstraps at ' + r.minN + ' values or more, and the binomial order-statistic interval at ' + Q_BOOT_MAX
    + ' or more.</li>'
    + '<li><b>$/hr</b> is the card\'s rate as the rig worked it out (the row\'s <code>perHour</code>, pay less the car\'s '
    + 'cost over the minutes it was judged over), on rows advice.js\'s <code>trustworthy</code> keeps.</li>'
    + '<li><b>Score</b> is the median, over a cell\'s offers, of each offer\'s $/hr less what the <i>other</i> ranked '
    + 'cells paid in the same three-hour block — advice.js\'s <code>matched</code>, the figure the rig\'s town table ranks by. '
    + 'Zero is "paid what the same hours paid elsewhere".</li>'
    + '<li><b>The test</b> is advice.js\'s <code>areas</code>: Kruskal-Wallis H on ranks against ' + r.shuffles
    + ' seeded shuffles of the same rates, confined within three-hour blocks in the all-hours view. '
    + 'Alpha ' + r.alpha + '.</li>'
    + '<li><b>Intervals</b> are 95% percentile bootstraps of the median (' + r.boots + ' resamples, seeded).</li>'
    + '<li><b>Colour</b> only where the grouping beats chance <i>and</i> the cell\'s score interval is clear of zero. '
    + 'No colour bands: AUDITS.md measured a band map miscolouring 21-25% of cells with no effect at all.</li>'
    + '<li><b>Too few:</b> under ' + r.minN + ' offers or ' + r.minOutings + ' shift days a cell is listed with its n '
    + 'and neither ranked nor tested (' + r.dropMinN + ' trips for the wait after a drop).</li>'
    + '<li><b>Placing a pickup</b> uses map-view.js as the rig\'s server does for an order in the car: a printed door '
    + 'by its door, a store\'s name by <code>pickPlace</code>, both inside the disc round the card\'s GPS fix and the card\'s '
    + 'own distance; pinned only where one place answers. The local NucBox only, never the public geocoder.</li>'
    + '<li><b>Take share</b> is the share of a cell\'s offers the rig itself said <b>take</b> (go) at the time, '
    + 'against the target you had then.</li>'
    + '<li><b>When &amp; where</b>: the Waited tab\'s line (the cards that came with no taken order in the car, at '
    + 'the car\'s own gated GPS fix; never a pin or DoorDash\'s map label), each card in the slot of its driver\'s day '
    + '(4am to 4am) and one of six blocks (' + r.whenwhere.blocks.join(', ') + '; chosen round the meal peaks and so '
    + 'that a night stays whole in its shift day, not measured) or one clock hour of it (4am first, 3am last: 3am '
    + 'on a Saturday is Friday\'s last hour). Hours waited: each card\'s time to the next, at most '
    + r.waited.creditMaxMin + ' min, none across a silence over ' + r.nextGapMin + ' min, credited to the earlier '
    + 'card\'s area. Good: the card\'s $/hr at or over a fixed cutoff, the top 10/20/30/50% of all ' + r.whenwhere.offers
    + ' counted offers in the range (' + r.whenwhere.tops.map(function (t, i) {
      return 'top ' + t + '% ≥ ' + money(r.whenwhere.cuts[i]);
    }).join(', ') + '), worked out once and held fixed across every slot and area, and handed to the Strategy tab\'s '
    + 'section 7 so both read one line. Good/hr with its exact (Garwood) '
    + Math.round(r.whenwhere.conf * 100) + '% Poisson interval, the hours taken as exact, widened by phi: Pearson\'s '
    + 'chi-square of each area\'s shift days against its own rate within each weekday and block, pooled, never under '
    + '1 (trends.js dispersion, as the offers page\'s Trends grid); the hour strip by one phi over every weekday and '
    + 'hour. A plain interval marked 4-13% of no-effect areas once the nights swing 40%; widened, about 1%. An area is ranked at '
    + r.whenwhere.minHours + ' h waited on ' + r.whenwhere.minDays + ' shift days in the slot (chosen: two days is the '
    + 'report\'s own floor, two hours a dozen card gaps at least) and marked only where its interval lies wholly '
    + 'above or below the slot\'s overall rate. A single hour takes the same cutoff, interval, marking and floor, '
    + 'so most areas sit under the floor there; the <b>hour strip</b> draws the slot\'s own line for each of the day\'s '
    + '24 hours (every area together), held to the same floor (grey with its n under it) and marked by the same rule '
    + 'against every slot together. A card\'s credit counts in the hour its card came up in, though up to '
    + r.waited.creditMaxMin + ' min of it may run into the next. <b>Offered, not earned</b>, and descriptive: it never feeds the '
    + 'rig, a verdict, the target or the accept line, and the line is not tuned to an hour or a weekday.</li>'
    + '<li><b>Offers around you</b>: the same line as When &amp; where (no order in the car, the car\'s own gated '
    + 'fix), one dot per offer, coloured by its own $/hr against When &amp; where\'s fixed cutoff for the top share '
    + 'picked, with that tab\'s Day and Hours choices. <b>Dots, not a coloured grid</b>: a dot is one offer\'s own '
    + 'fact, so nothing estimated is coloured (AUDITS.md\'s heat-map entry measured a band-coloured grid '
    + 'miscolouring a fifth of its cells at a dozen offers). Each dot keeps only its ' + r.around.binMi + '-mile '
    + 'square (gridCell, the 2-mile grid\'s rule at a quarter mile) and is drawn on a sunflower inside it; a square '
    + 'is drawn only where the car was on ' + r.around.binDays + ' shift days or more, so a door passed once after a '
    + 'drop is never a dot (chosen, the report\'s own two-day rule). <b>Home</b> (chosen, not measured): each driver '
    + 'day\'s starting stay — every card before the car\'s fix first lies more than ' + r.around.homeMi + ' mi from '
    + 'that day\'s first fix — and every card within ' + r.around.homeMi + ' mi of a first fix two or more days share, '
    + 'on any day, are left out; ' + r.around.homeMi + ' mi is the report\'s distance for one place, about six times the '
    + 'GPS gate\'s worst error. <b>Rings</b>: whole miles from the centre of the ' + r.gridMi + '-mile cell with the '
    + 'most credited waiting hours among the dots drawn, measured from each dot\'s square; the share good with '
    + 'Wilson\'s 95% interval at ' + r.descMinN + ' offers. <b>Areas</b>: When &amp; where\'s own slot table, drawn, '
    + 'home not left out of it (AUDITS.md, Open). <b>Drive to the pickup</b>: the card\'s own toPickupMiles '
    + '(offer-parser.js\'s split of the approach leg, where the card prints one), every counted offer, no GPS: '
    + 'the share good and the median $/hr per band (' + r.around.pickup.bands.join(', ') + '). Descriptive, like '
    + 'everything here: no distance or $/mi rule, no floor, and nothing reaches the rig.</li>'
    + '</ul>';
}

var PAGE_CSS = [
  ':root{--bg:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;',
  '--axis:#c3c2b7;--up:#2a78d6;--down:#e34948;--grey:#a9a79f;--warn:#fff4d6;--warnline:#e8c25a;color-scheme:light}',
  '@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#0d0d0d;--surface:#1a1a19;',
  '--ink:#f0efec;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;--up:#3987e5;--down:#e66767;',
  '--grey:#6b6a64;--warn:#2a2416;--warnline:#8a6d1f;color-scheme:dark}}',
  ':root[data-theme="dark"]{--bg:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#898781;',
  '--grid:#2c2c2a;--axis:#383835;--up:#3987e5;--down:#e66767;--grey:#6b6a64;--warn:#2a2416;--warnline:#8a6d1f;color-scheme:dark}',
  '*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);',
  'font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}',
  'main{max-width:1000px;margin:0 auto;padding:16px}h1{font-size:24px;margin:8px 0 4px}',
  'h2{font-size:18px;margin:28px 0 6px}.sub,.note{color:var(--ink2);font-size:13px}',
  '.banner{background:var(--warn);border-left:4px solid var(--warnline);padding:4px 14px;border-radius:6px}',
  '.banner p{margin:8px 0}.bar{position:sticky;top:0;background:var(--bg);padding:10px 0;z-index:500;',
  'display:flex;gap:12px;flex-wrap:wrap;align-items:center;border-bottom:1px solid var(--grid)}',
  '.bar label{max-width:100%}select{max-width:100%;font:inherit;padding:4px 6px;background:var(--surface);color:var(--ink);border:1px solid var(--axis);border-radius:6px}',
  'table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}',
  '.tw{overflow-x:auto;margin:8px 0}th,td{text-align:right;padding:4px 8px;border-bottom:1px solid var(--grid);white-space:nowrap}',
  'th:first-child,td:first-child{text-align:left;white-space:normal;min-width:140px}th{color:var(--ink2);font-weight:600}',
  '.plot{background:var(--surface);border:1px solid var(--grid);border-radius:8px;padding:8px;overflow-x:auto}',
  '.plot svg{display:block;width:100%;min-width:520px;height:auto}.plot text{fill:var(--ink2);font-size:12px}',
  '.thin{color:var(--ink2);font-size:13px}#map{height:460px;border-radius:8px;border:1px solid var(--grid);background:var(--surface)}',
  '.k{font-size:16px}.k.up{color:var(--up)}.k.down{color:var(--down)}.k.grey{color:var(--grey)}',
  '.tag{display:inline-block;padding:0 6px;border-radius:4px;font-size:12px}.tag.up{color:#fff;background:var(--up)}',
  '.tag.down{color:#fff;background:var(--down)}.tag.grey{color:var(--ink2);border:1px solid var(--grid)}',
  '#tip{position:fixed;pointer-events:none;background:var(--surface);color:var(--ink);border:1px solid var(--axis);',
  'border-radius:6px;padding:6px 8px;font-size:12px;max-width:300px;z-index:1100;box-shadow:0 2px 8px rgba(0,0,0,.2)}',
  '.method li{margin:4px 0;color:var(--ink2);font-size:13px}code{font-size:12px}',
  '.tabs{display:flex;flex-wrap:wrap;gap:6px;margin:12px 0 4px}.tabs button{font:inherit;font-size:13px;',
  'padding:4px 10px;border-radius:14px;border:1px solid var(--axis);background:var(--surface);color:var(--ink);cursor:pointer}',
  '.tabs button[aria-pressed="true"]{background:var(--ink);color:var(--bg);border-color:var(--ink)}',
  'section[hidden]{display:none}h3{font-size:15px;margin:18px 0 4px}',
  '.exp{font-size:12px;color:var(--ink2);border:1px dashed var(--axis);border-radius:6px;padding:4px 8px;display:inline-block}',
  'th.sortable{cursor:pointer;user-select:none}th.sortable:after{content:" \\2195";color:var(--muted)}',
  'th[aria-sort="ascending"]:after{content:" \\2191"}th[aria-sort="descending"]:after{content:" \\2193"}',
  '.spark{display:block;width:140px;height:30px}.spark .z{stroke:var(--axis);stroke-dasharray:3 3}',
  '.spark polyline{fill:none;stroke:var(--ink2);stroke-width:1.5}.spark circle{fill:var(--ink2)}',
  'tr.br td{color:var(--ink2);border-bottom-style:dashed}tr.br td:first-child{padding-left:20px}',
  'table.groups th:first-child,table.groups td:first-child{position:sticky;left:0;z-index:1;background:var(--bg);',
  'min-width:150px;max-width:190px}',
  '.lines{padding-left:20px}.lines li{margin:6px 0}',
  '.xb{font:inherit;font-size:12px;padding:0 6px;margin-right:4px;border-radius:4px;border:1px solid var(--axis);',
  'background:var(--surface);color:var(--ink);cursor:pointer}',
  /* The layout of 7 Nov 2026 (html()'s nav, OVERVIEW_SECTION, fold()), from
   * here down, overriding what is above where the two meet. */
  // Wider on a laptop: the tables are wide and 1000px left half a 1280 screen empty.
  'main{max-width:1120px}.head h1{margin-bottom:2px}',
  // The nav: the one part that stays put. Groups on one row, the chosen
  // group's tabs under it, sideways-scrolling on a phone and wrapping on a
  // laptop. Above Leaflet's panes and controls (400-1000), under the tooltip.
  '.nav{position:sticky;top:0;z-index:1050;background:var(--bg);margin:8px -16px 0;padding:0 16px;',
  'border-bottom:1px solid var(--grid)}',
  '.groups{display:flex;gap:2px;overflow-x:auto;scrollbar-width:none}.groups::-webkit-scrollbar{display:none}',
  '.groups button{flex:none;font:inherit;font-size:14px;font-weight:600;min-height:44px;padding:8px 10px;border:0;',
  'border-bottom:3px solid transparent;background:none;color:var(--ink2);cursor:pointer}',
  '.groups button[aria-selected="true"]{color:var(--ink);border-bottom-color:var(--up)}',
  // On a phone the four share the width equally and a long name wraps onto
  // two lines: measured at 375px, the four in one line need 384px of a 343px
  // column, and a group scrolled off the edge is a group nobody finds.
  '@media (max-width:480px){.groups{display:grid;grid-template-columns:repeat(4,1fr)}',
  '.groups button{font-size:13px;padding:6px 2px;line-height:1.15;white-space:normal}}',
  '.nav .tabs{position:relative;flex-wrap:nowrap;overflow-x:auto;margin:0;padding:6px 0 8px;scrollbar-width:thin}',
  '.nav .tabs[hidden]{display:none}.tg{display:contents}.tg[hidden]{display:none}',
  '.nav .tabs button{flex:none;min-height:36px;padding:4px 12px}',
  '@media (min-width:760px){.nav .tabs{flex-wrap:wrap;overflow:visible}}',
  // The gist of the old banner, under the nav on every tab but the Overview.
  '.strip{font-size:12px;color:var(--ink2);margin:6px 0 0}.strip[hidden]{display:none}.strip.warn{color:var(--ink)}',
  '.bar{position:static;border-bottom:0;padding:8px 0 0}.bar[hidden]{display:none}',
  // A heading a link lands on clears the sticky nav.
  'h3,details.fold{scroll-margin-top:110px}',
  // Folds: the heading is the handle, with a marker that says which way.
  'details.fold{margin:4px 0}details.fold>summary{cursor:pointer;list-style:none;display:flex;align-items:center;gap:6px;min-height:40px}',
  'details.fold>summary::-webkit-details-marker{display:none}',
  'details.fold>summary:before{content:"\\25B8";color:var(--muted);font-size:12px;width:12px}',
  'details.fold[open]>summary:before{content:"\\25BE"}details.fold>summary h3{margin:8px 0}',
  // Tables on a phone: the name column stays while the figures scroll under it.
  '.tw th:first-child,.tw td:first-child{position:sticky;left:0;z-index:1;background:var(--bg)}',
  // A row under its floor: muted, so it never reads as loud as one over it.
  'tr.thinrow td{color:var(--muted);font-style:italic}',
  '.pblocks{margin:8px 0}.prow{margin:0 0 10px}.pname{font-size:13px;font-weight:600}',
  '.pbar{display:flex;height:14px;margin:2px 0;border-radius:3px;overflow:hidden;background:var(--grid)}',
  '.pbar i,.plegend i{display:block;height:100%}.ptaken{background:var(--up)}.pphone{background:var(--up);opacity:.45}',
  '.ppassed{background:var(--grey)}.pbusy{background:repeating-linear-gradient(45deg,var(--axis) 0 3px,transparent 3px 6px)}',
  '.pfig{font-size:12px;color:var(--ink2);font-variant-numeric:tabular-nums}',
  '.plegend{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:12px;color:var(--ink2)}',
  '.plegend i{display:inline-block;width:12px;height:12px;margin-right:4px;vertical-align:-2px;border-radius:2px}',
  // Charts: the wide curve on a laptop, the small one on a phone; a fluid
  // plot scales to its box instead of scrolling inside it.
  '.plot.small{display:none}@media (max-width:640px){.plot.wide{display:none}.plot.small{display:block}}',
  '.plot.small svg,.plot.fluid svg{min-width:0}.plot text.sm{font-size:11px}',
  // The Overview.
  '.lead{font-size:16px;line-height:1.5;margin:12px 0}',
  '.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(158px,1fr));gap:10px;margin:12px 0}',
  '.tile{display:flex;flex-direction:column;gap:2px;background:var(--surface);border:1px solid var(--grid);',
  'border-radius:10px;padding:10px 12px;color:inherit;text-decoration:none;min-width:0}',
  '.tile:hover,.tile:focus{border-color:var(--axis)}.tile .tl{font-size:12px;color:var(--ink2);font-weight:600}',
  '.tile .tv{font-size:24px;font-weight:700;line-height:1.15;font-variant-numeric:tabular-nums}',
  '.tile .tv small{font-size:13px;font-weight:600;color:var(--ink2)}',
  '.tile .ts{font-size:13px;color:var(--ink)}.tile .tf{font-size:11px;color:var(--muted);margin-top:auto;padding-top:4px}',
  '.tile.warn{background:var(--warn);border-color:var(--warnline)}',
  '.pair{display:grid;grid-template-columns:1fr;gap:16px}@media (min-width:760px){.pair{grid-template-columns:1fr 1fr}}',
  '.pair .plot{max-width:460px}a.more{font-size:13px;font-weight:400;margin-left:6px}',
  'details.caveats>summary{cursor:pointer}details.caveats>summary h3{display:inline}',
  '.dir{display:grid;grid-template-columns:1fr;gap:4px 24px}@media (min-width:760px){.dir{grid-template-columns:repeat(3,1fr)}}',
  '.dir h4{margin:10px 0 2px;font-size:14px}.dir ul{margin:0;padding-left:18px;font-size:13px;color:var(--ink2)}',
  '.dir li{margin:3px 0}a{color:var(--up)}',
  // When & where's hour strip: two rows of twelve on a phone (a 28px cell
  // holds "12p" over "5.1"), one row of twenty-four from a laptop up.
  '.wwstrip{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:3px;margin:8px 0 2px}',
  '@media (min-width:760px){.wwstrip{grid-template-columns:repeat(24,minmax(0,1fr))}}',
  '.wwstrip button{font:inherit;font-size:11px;line-height:1.25;min-height:40px;padding:3px 0;min-width:0;display:flex;',
  'flex-direction:column;align-items:center;justify-content:center;border:1px solid var(--grid);border-radius:5px;',
  'background:var(--surface);color:var(--ink);cursor:pointer;font-variant-numeric:tabular-nums}',
  '.wwstrip .hl{font-size:10px;color:var(--ink2)}.wwstrip button.up{background:var(--up);border-color:var(--up);color:#fff}',
  '.wwstrip button.down{background:var(--down);border-color:var(--down);color:#fff}',
  '.wwstrip button.up .hl,.wwstrip button.down .hl{color:#fff}',
  '.wwstrip button.thin{background:transparent;color:var(--muted);font-style:italic}',
  '.wwstrip button.none{background:transparent;color:var(--muted);border-style:dashed;opacity:.45}',
  // R1: on a phone, When & where's P90 and Uber · DD columns become a line
  // under the area's name.
  '#wwTable small.narrow{display:none}@media (max-width:759px){#wwTable .wide{display:none}',
  '#wwTable small.narrow{display:block;font-size:11px;color:var(--ink2);white-space:nowrap}}',
  '.wwstrip button.in{box-shadow:inset 0 -3px 0 var(--ink2)}.wwstrip button.on{outline:2px solid var(--ink);outline-offset:1px}',
  // Offers around you: the map (or the dots on a blank square without the
  // internet), and the three bar charts as rows, a phone's width each.
  '.amap{height:460px;border-radius:8px;border:1px solid var(--grid);background:var(--surface);overflow:hidden}',
  '.amap svg{display:block;width:100%;height:100%}',
  '.hbars{display:grid;gap:4px;margin:6px 0 10px;font-size:13px;font-variant-numeric:tabular-nums}',
  '.hb{display:grid;grid-template-columns:minmax(84px,30%) minmax(0,1fr) auto;gap:8px;align-items:center}',
  '.hb .nm{overflow-wrap:anywhere}.hb .fig{text-align:right;color:var(--ink2);white-space:nowrap;font-size:12px}',
  '.hb .track{position:relative;height:16px;background:var(--grid);border-radius:3px}',
  '.hb .fill{position:absolute;left:0;top:0;bottom:0;background:var(--grey);border-radius:3px}',
  '.hb .fill.up{background:var(--up)}.hb .fill.down{background:var(--down)}',
  '.hb .wh{position:absolute;top:7px;height:2px;background:var(--ink)}',
  '.hb.thinrow .nm,.hb.thinrow .fig{color:var(--muted);font-style:italic}',
  // On a phone the figures go under the bar: beside it they pushed the page sideways.
  '@media (max-width:640px){.hb{grid-template-columns:minmax(70px,32%) minmax(0,1fr)}',
  '.hb .fig{grid-column:2;text-align:left;white-space:normal}}',
].join('\n');

/* The page's script: it switches between views computed above and draws them.
   It computes no statistic of its own. */
var PAGE_JS = String(function page() {
  var R = JSON.parse(document.getElementById('data').textContent);
  var css = getComputedStyle(document.documentElement);
  function col(name) { return css.getPropertyValue(name).trim(); }
  function esc(s) {
    return String(s === null || s === undefined ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function m(v) { return v === null || v === undefined ? '—' : '$' + v.toFixed(2); }
  function sg(v) { return v === null || v === undefined ? '—' : (v >= 0 ? '+' : '−') + '$' + Math.abs(v).toFixed(2); }
  function ci(c, f) { return c ? '[' + f(c[0]) + ', ' + f(c[1]) + ']' : '—'; }
  function pc(v) { return v === null || v === undefined ? '—' : Math.round(v * 100) + '%'; }
  function pTxt(p) {
    return p === null ? 'not tested' : p === 0 ? 'p < ' + (1 / R.shuffles).toFixed(4) : 'p = ' + p.toFixed(3);
  }
  function label(kind, name) {
    if (kind === 'place') return (R.places[name] && R.places[name].label) || name;
    if (kind === 'rest') return (R.restNames && R.restNames[name]) || name;
    if (kind === 'grid') {
      var c = R.cells[name];
      return c ? 'cell near ' + c.lat.toFixed(3) + ', ' + c.lon.toFixed(3) : name;
    }
    return name;
  }
  function tag(g, lowGood) {
    if (!g.beats) return '<span class="tag grey">not distinguishable</span>';
    var good = lowGood ? g.clear === 'below' : g.clear === 'above';
    return '<span class="tag ' + (good ? 'up' : 'down') + '">' + (g.clear === 'above' ? 'above' : 'below')
      + ' the rest</span>';
  }
  var tip = document.getElementById('tip');
  function showTip(e, text) {
    tip.hidden = false; tip.innerHTML = text;
    var x = Math.min(e.clientX + 12, innerWidth - 310);
    tip.style.left = x + 'px'; tip.style.top = (e.clientY + 12) + 'px';
  }
  document.addEventListener('mouseover', function (e) {
    var t = e.target.closest && e.target.closest('[data-tip]');
    if (t) showTip(e, t.getAttribute('data-tip')); else tip.hidden = true;
  });
  document.addEventListener('mousemove', function (e) { if (!tip.hidden) showTip(e, tip.innerHTML); });

  function testText(c, what) {
    if (c.p === null) {
      return what + ': not tested — ' + c.groups.length + ' cell(s) clear the floor of ' + c.floor + ' on '
        + c.outings + ' shift days.';
    }
    return what + ': ' + c.groups.length + ' cells over ' + c.kept + ', ' + (c.held ? 'hours held still, ' : '')
      + pTxt(c.p) + (c.held && c.rawP !== null ? ' (' + pTxt(c.rawP) + ' with the hour left in)' : '') + ' — '
      + (c.significant ? '<b>beats chance</b>; colour only where a cell\'s interval is clear of zero.'
         : '<b>not distinguishable from chance</b>, so nothing is coloured: read the order as noise.');
  }

  /* A ranked dot plot: one row per cell, the score's interval as a bar and
     the score as a dot, zero marked. Colour only on cells that beat chance. */
  function dotPlot(el, c, kind, unit, lowGood) {
    var gs = c.groups.filter(function (g) { return g.score !== null; });
    if (!gs.length) { el.innerHTML = '<p class="note">No cell clears the floor here.</p>'; return; }
    var lo = 0, hi = 0;
    gs.forEach(function (g) {
      var a = g.sci ? g.sci[0] : g.score, b = g.sci ? g.sci[1] : g.score;
      lo = Math.min(lo, a); hi = Math.max(hi, b);
    });
    var pad = (hi - lo) * 0.06 || 1; lo -= pad; hi += pad;
    var W = 720, L = 230, Rr = 20, rowH = 24, top = 26, H = top + gs.length * rowH + 10;
    function x(v) { return L + (v - lo) / (hi - lo) * (W - L - Rr); }
    var step = Math.pow(10, Math.floor(Math.log10((hi - lo) / 4)));
    if ((hi - lo) / step > 8) step *= 2;
    if ((hi - lo) / step > 8) step *= 2.5;
    var s = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="ranked dot plot">';
    for (var t = Math.ceil(lo / step) * step; t <= hi; t += step) {
      s += '<line x1="' + x(t) + '" x2="' + x(t) + '" y1="' + (top - 6) + '" y2="' + (H - 6) + '" stroke="'
        + col('--grid') + '"/><text x="' + x(t) + '" y="' + (top - 10) + '" text-anchor="middle">'
        + (Math.abs(t) < 1e-9 ? '0' : (t > 0 ? '+' : '−') + Math.abs(t).toFixed(step < 1 ? 1 : 0)) + '</text>';
    }
    s += '<line x1="' + x(0) + '" x2="' + x(0) + '" y1="' + (top - 6) + '" y2="' + (H - 6) + '" stroke="'
      + col('--axis') + '" stroke-width="2"/>';
    gs.forEach(function (g, i) {
      var y = top + i * rowH + rowH / 2;
      var good = lowGood ? g.clear === 'below' : g.clear === 'above';
      var colour = g.beats ? col(good ? '--up' : '--down') : col('--grey');
      var name = label(kind, g.name);
      var tipText = esc(name) + '<br>n = ' + g.n + ' on ' + g.outings + ' shift days<br>'
        + (unit === 'min' ? 'wait vs same hours elsewhere: ' : 'vs same hours elsewhere: ') + sg(g.score)
        + ' ' + ci(g.sci, sg) + '<br>median ' + (unit === 'min' ? (g.median + ' min') : m(g.median) + '/hr')
        + (g.beats ? '' : '<br>not distinguishable from the rest');
      s += '<g data-tip="' + esc(tipText) + '"><rect x="0" y="' + (y - rowH / 2) + '" width="' + W + '" height="'
        + rowH + '" fill="transparent"/>';
      s += '<text x="' + (L - 10) + '" y="' + (y + 4) + '" text-anchor="end">'
        + esc(name.length > 30 ? name.slice(0, 29) + '…' : name) + ' (' + g.n + ')</text>';
      if (g.sci) {
        s += '<line x1="' + x(g.sci[0]) + '" x2="' + x(g.sci[1]) + '" y1="' + y + '" y2="' + y
          + '" stroke="' + colour + '" stroke-width="3" stroke-linecap="round"/>';
      }
      s += '<circle cx="' + x(g.score) + '" cy="' + y + '" r="5" fill="' + colour + '" stroke="'
        + col('--surface') + '" stroke-width="2"/></g>';
    });
    s += '</svg><p class="note">' + (unit === 'min'
      ? 'Minutes of wait against the same hours elsewhere, with 95% intervals. Left of zero is a shorter wait.'
      : '$/hr against what the other cells paid in the same three-hour blocks, with 95% intervals.') + '</p>';
    el.innerHTML = s;
  }

  function table(el, c, kind) {
    var rows = c.groups.map(function (g) {
      return '<tr><td>' + esc(label(kind, g.name)) + '</td><td>' + g.n + '</td><td>' + g.outings + '</td><td>'
        + sg(g.score) + '</td><td>' + ci(g.sci, sg) + '</td><td>' + m(g.median) + '</td><td>' + ci(g.ci, m)
        + '</td><td>' + m(g.p75) + '</td><td>' + m(g.p90) + '</td><td>' + ci(g.p90Ci, m)
        + '</td><td data-v="' + (g.top10 === null || g.top10 === undefined ? '' : g.top10) + '">' + pc(g.top10)
        + '</td><td>' + m(g.pay) + '</td><td>' + m(g.ppm) + '</td><td>' + ci(g.ppmCi, m) + '</td><td>' + pc(g.take)
        + '</td><td>' + tag(g, false) + '</td></tr>';
    }).join('');
    el.innerHTML = c.groups.length ? '<div class="tw"><table><thead><tr><th>' + (kind === 'place' ? 'place'
      : kind === 'town' ? 'town' : 'cell') + '</th><th>n</th><th>days</th><th>vs same hours</th><th>95%</th>'
      + '<th>median $/hr</th><th>95%</th><th>P75 $/hr</th><th>P90 $/hr</th><th>95%</th><th>top 10%</th>'
      + '<th>median pay</th><th>$/mi (read only)</th><th>95%</th>'
      + '<th>rig said take</th><th></th></tr></thead><tbody>'
      + rows + '</tbody></table></div>' : '';
  }

  function thinList(el, c, kind, unit) {
    if (!c.thin.length) { el.innerHTML = ''; return; }
    el.innerHTML = '<p><b>Too few to rank</b> (under ' + c.floor + ' ' + unit + ' or ' + c.outings
      + ' shift days): ' + c.thin.slice(0, 60).map(function (t) {
        return esc(label(kind, t.name)) + ' (' + t.n + ')';
      }).join(', ') + (c.thin.length > 60 ? ', and ' + (c.thin.length - 60) + ' more' : '') + '.</p>';
  }

  function dropTable(el, c, what) {
    var rows = c.groups.map(function (g) {
      var name = what === 'cell' && g.box ? 'cell near ' + g.box.lat.toFixed(3) + ', ' + g.box.lon.toFixed(3)
        : g.name;
      return '<tr><td>' + esc(name) + '</td><td>' + g.trips + '</td><td>' + g.n + '</td><td>' + g.ended
        + '</td><td>' + g.median.toFixed(1) + ' min</td><td>' + ci(g.ci, function (v) { return v.toFixed(1); })
        + '</td><td>' + (g.score === null ? '—' : (g.score >= 0 ? '+' : '−') + Math.abs(g.score).toFixed(1) + ' min')
        + '</td><td>' + m(g.nextPerHour) + '</td><td>' + m(g.nextPay)
        + '</td><td>' + (g.anyMin === null || g.anyMin === undefined ? '—' : g.anyMin.toFixed(1) + ' min')
        + '</td><td>' + m(g.anyPerHour) + '</td><td>' + pc(g.anyGood) + '</td><td>' + tag(g, true) + '</td></tr>';
    }).join('');
    var thin = what === 'cell'
      ? (c.thinCount ? '<p class="thin">' + c.thinCount + ' more cells (' + c.thinTrips
         + ' trips) have too few to show, and are not named.</p>' : '')
      : (c.thin.length ? '<p class="thin"><b>Too few</b> (under ' + c.floor + ' measured waits): '
         + c.thin.map(function (t) { return esc(t.name) + ' (' + t.n + ')'; }).join(', ') + '.</p>' : '');
    // Its heading is the fold's round it now (html()), so none is written here.
    el.innerHTML = (c.groups.length ? '<div class="tw"><table><thead><tr><th>' + (what === 'cell' ? 'cell' : 'town')
        + '</th><th>trips</th><th>measured</th><th>ended</th><th>median wait</th><th>95%</th><th>vs same hours</th>'
        + '<th>next take $/hr</th><th>next take pay</th><th>next offer, min</th><th>next offer $/hr</th>'
        + '<th>next offer cleared target</th><th></th></tr></thead><tbody>' + rows
        + '</tbody></table></div>' : '<p class="note">No area clears the floor here.</p>') + thin;
  }

  /* The Restaurants table: a tbody per restaurant, its branches hidden under
     it until ▸ is clicked, so a sort moves a restaurant with its branches. */
  var REST_HEAD = ['restaurant', 'offers', 'days', 'vs same hours', '95%', 'median $/hr', '95%', 'P90 $/hr', 'top 10%',
                   'median pay',
                   '$/mi (read only)', 'you took', 'real $/hr', 'timed', 'real − card', 'wait', 'add-on', 'stacked',
                   'Uber · DD', ''];
  function restCells(g, isBranch) {
    function td(v, text) { return '<td data-v="' + esc(v === null || v === undefined ? '' : String(v)) + '">' + text + '</td>'; }
    // (and the worst, where the rig sends it: storeWaitsOut's worstMin)
    var wait = g.wait !== null && g.wait !== undefined ? g.wait.toFixed(1) + ' min (' + g.waitN + ')'
      + (typeof g.waitWorst === 'number' ? ', worst ' + g.waitWorst.toFixed(1) : '')
      : g.waitWhy && g.waitWhy !== 'none on record' ? '<span title="' + esc(g.waitWhy) + '">— ' + esc(g.waitWhy) + '</span>' : '—';
    var score = isBranch ? (g.placeScore !== null && g.placeScore !== undefined
      ? '<span title="as a place, against the other places">' + sg(g.placeScore) + ' (place)</span>' : '—') : sg(g.score);
    return [td(g.n, String(g.n)), td(g.outings, String(g.outings)), td(isBranch ? g.placeScore : g.score, score),
            td(g.sci ? g.sci[0] : '', isBranch ? '' : ci(g.sci, sg)),
            td(g.ranked ? g.median : g.perHour, m(g.ranked && !isBranch ? g.median : g.perHour)),
            td(g.ci ? g.ci[0] : '', isBranch ? '' : ci(g.ci, m)), td(g.p90, m(g.p90)), td(g.top10, pc(g.top10)),
            td(g.pay, m(g.pay)), td(g.ppm, m(g.ppm)),
            td(g.take, pc(g.take) + (g.taken ? ' (' + g.taken + ')' : '')), td(g.realPerHour, m(g.realPerHour)),
            td(g.timed, String(g.timed)),
            td(g.cardVsReal, g.cardVsReal === null ? '—' : (g.cardVsReal >= 0 ? '+' : '−') + Math.abs(g.cardVsReal).toFixed(1) + ' min'),
            td(g.wait, wait), td(g.addon, pc(g.addon)), td(g.stacked, pc(g.stacked)),
            td(g.uberN, g.uberN + ' · ' + g.doordashN)].join('');
  }
  function restRows(list, ranked) {
    return list.map(function (g, i) {
      var nb = g.branches.filter(function (b) { return !b.unplaced; }).length;
      var btn = g.branches.length ? '<button type="button" class="xb" aria-expanded="false" title="placed branches">▸ '
        + nb + '</button>' : '';
      var head = '<tr><td data-v="' + esc(label('rest', g.name).toLowerCase()) + '">' + btn + esc(label('rest', g.name))
        + (g.chain ? ' <span class="note">chain</span>' : '') + '</td>' + restCells(g, false) + '<td>'
        + (ranked ? tag(g, false) : '<span class="tag grey">too few</span>') + '</td></tr>';
      var subs = g.branches.map(function (b) {
        var nm = b.unplaced ? 'not placed' : b.name + (b.lat !== undefined ? ' <span class="note">near '
          + b.lat.toFixed(3) + ', ' + b.lon.toFixed(3) + '</span>' : '');
        return '<tr class="br" hidden><td>↳ ' + (b.unplaced ? '<i>not placed</i>' : nm) + '</td>' + restCells(b, true)
          + '<td>' + (b.placeBeats ? '<span class="note">clear of the rest in Places</span>' : '') + '</td></tr>';
      }).join('');
      return '<tbody>' + head + subs + '</tbody>';
    }).join('');
  }
  function restTable(c) {
    document.getElementById('restCover').textContent = c.named + ' offers carry a name, ' + c.placed + ' of them '
      + 'placed (' + (c.named ? Math.round(c.placed / c.named * 100) : 0) + '%); ' + c.noName
      + ' printed a door, a street or a corner and no name, and are not here.';
    var head = '<thead><tr>' + REST_HEAD.map(function (h) { return '<th>' + esc(h) + '</th>'; }).join('') + '</tr></thead>';
    document.getElementById('restTable').innerHTML = c.groups.length
      ? '<div class="tw"><table class="groups">' + head + restRows(c.groups, true) + '</table></div>' : '';
    var CAP = 150, thin = c.thin.slice(0, CAP);
    document.getElementById('restThin').innerHTML = c.thin.length
      ? '<h3>Too few to rank</h3><p class="thin">Under ' + c.floor + ' offers or ' + c.outings + ' shift days: listed '
        + 'for reading, neither ranked nor tested nor coloured' + (c.thin.length > CAP ? '; the ' + CAP
        + ' with the most offers shown, all ' + c.thin.length + ' in restaurants.csv' : '') + '.</p>'
        + '<div class="tw"><table class="groups">' + head + restRows(thin, false) + '</table></div>' : '';
  }
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('button.xb');
    if (!b) return;
    e.stopPropagation();
    var open = b.getAttribute('aria-expanded') !== 'true';
    b.setAttribute('aria-expanded', open ? 'true' : 'false');
    b.textContent = (open ? '▾ ' : '▸ ') + b.textContent.slice(2);
    Array.prototype.forEach.call(b.closest('tbody').querySelectorAll('tr.br'), function (r) { r.hidden = !open; });
  });

  function levelsTable() {
    var ls = R.coverage.levels || [];
    document.getElementById('levels').innerHTML = ls.length ? '<div class="tw"><table><thead><tr><th>level</th>'
      + '<th>kind</th><th>placed</th><th>median $/hr</th><th>no fix, region box</th><th>stood in for</th></tr></thead><tbody>'
      + ls.map(function (l) {
        return '<tr><td>' + esc(l.level) + '</td><td>' + (l.point ? 'point' : 'approximate') + '</td><td>' + l.n
          + '</td><td>' + m(l.perHour) + '</td><td>' + l.region + '</td><td>' + esc(l.refused || '—') + '</td></tr>';
      }).join('') + '</tbody></table></div>'
      + (R.coverage.points && R.coverage.points.gapPerHour !== null ? '<p class="note">Points only (door, corner, '
         + 'name) against the unplaced: ' + m(R.coverage.points.placed.perHour) + '/hr against '
         + m(R.coverage.points.unplaced.perHour) + '/hr (' + pTxt(R.coverage.points.p) + '). The table below counts '
         + 'every level as placed.</p>' : '')
      : '<p class="note">Nothing placed.</p>';
  }
  function shareTests() {
    var B = R.best.share, out = '';
    [['town', 'Towns'], ['rest', 'Restaurants'], ['place', 'Places'], ['grid', R.gridMi + '-mile cells']].forEach(function (k) {
      var t = B[k[0]];
      out += '<h3>' + esc(k[1]) + '</h3><p class="note">' + (t.p === null ? 'Not tested: ' + t.groups.length
        + ' over the floor.' : t.groups.length + ' groups over ' + t.kept + ' offers, hours held, ' + pTxt(t.p) + ' — '
        + (t.significant ? '<b>beats chance</b>; colour only where a group\'s interval is clear of zero.'
           : '<b>not distinguishable from chance</b>, so nothing is coloured.')) + '</p>';
      if (!t.groups.length) return;
      out += '<div class="tw"><table><thead><tr><th>' + esc(k[1].toLowerCase()) + '</th><th>offers</th><th>days</th>'
        + '<th>top 10%</th><th>the others, same hours</th><th>vs same hours</th><th>95%</th><th>top 25%</th><th></th></tr></thead><tbody>'
        + t.groups.map(function (g) {
          function pts(v) { return v === null || v === undefined ? '—' : (v >= 0 ? '+' : '−') + Math.abs(v * 100).toFixed(1) + ' pts'; }
          var pl = k[0] === 'place' ? R.places[g.name] : null;
          return '<tr><td>' + esc(label(k[0], g.name)) + (pl ? ' <span class="note">near ' + pl.lat.toFixed(3) + ', '
            + pl.lon.toFixed(3) + '</span>' : '') + '</td><td>' + g.n + '</td><td>' + g.outings + '</td><td data-v="'
            + g.top10 + '">' + pc(g.top10) + '</td><td>' + pc(g.expect) + '</td><td data-v="' + g.score + '">' + pts(g.score)
            + '</td><td>' + ci(g.sci, pts) + '</td><td>' + pc(g.top25) + '</td><td>' + tag(g, false) + '</td></tr>';
        }).join('') + '</tbody></table></div>';
    });
    document.getElementById('shareTests').innerHTML = out;
  }
  function coverageTable() {
    var d = R.coverage.days.concat([Object.assign({ day: 'all days' }, R.coverage.all)]);
    document.getElementById('coverage').innerHTML = '<div class="tw"><table><thead><tr><th>shift day</th>'
      + '<th>placed</th><th>unplaced</th><th>placed $/hr</th><th>unplaced $/hr</th><th>gap</th><th>placed pay</th>'
      + '<th>unplaced pay</th><th>test</th></tr></thead><tbody>' + d.map(function (r) {
        return '<tr><td>' + esc(r.day) + '</td><td>' + r.placed.n + '</td><td>' + r.unplaced.n + '</td><td>'
          + m(r.placed.perHour) + '</td><td>' + m(r.unplaced.perHour) + '</td><td>' + sg(r.gapPerHour) + '</td><td>'
          + m(r.placed.pay) + '</td><td>' + m(r.unplaced.pay) + '</td><td>' + pTxt(r.p) + '</td></tr>';
      }).join('') + '</tbody></table></div><p class="note">Why the unplaced were not placed: '
      + R.coverage.why.map(function (w) { return esc(w.why) + ' ' + w.n; }).join(' · ') + '</p>';
  }

  var map = null, layer = null;
  function drawMap(v) {
    if (typeof L === 'undefined') {
      document.getElementById('map').innerHTML = '<p class="note" style="padding:12px">The map needs the '
        + 'internet for Leaflet and its tiles; the tables above and below do not.</p>';
      return;
    }
    if (!map) {
      map = L.map('map');
      L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19, attribution: '&copy; OpenStreetMap contributors' }).addTo(map);
    }
    if (layer) layer.remove();
    layer = L.layerGroup().addTo(map);
    var pts = [];
    v.grid.groups.forEach(function (g) {
      var c = R.cells[g.name];
      if (!c) return;
      var colour = g.beats ? col(g.clear === 'above' ? '--up' : '--down') : col('--grey');
      L.rectangle([[c.s, c.w], [c.n, c.e]], { color: colour, weight: 1, fillOpacity: g.beats ? 0.18 : 0.06 })
        .bindTooltip('2-mile cell · n ' + g.n + ' · ' + sg(g.score) + ' ' + ci(g.sci, sg)
                     + (g.beats ? '' : ' · not distinguishable from the rest')).addTo(layer);
    });
    var biggest = Math.max.apply(null, [1].concat(v.place.groups.map(function (g) { return g.n; })));
    v.place.groups.forEach(function (g) {
      var p = R.places[g.name];
      if (!p) return;
      var colour = g.beats ? col(g.clear === 'above' ? '--up' : '--down') : col('--grey');
      L.circleMarker([p.lat, p.lon], { radius: 5 + 13 * Math.sqrt(g.n / biggest), color: col('--surface'),
        weight: 2, fillColor: colour, fillOpacity: 0.9 })
        .bindTooltip(esc(p.label) + '<br>n ' + g.n + ' · median ' + m(g.median) + '/hr ' + ci(g.ci, m)
                     + '<br>vs same hours ' + sg(g.score) + ' ' + ci(g.sci, sg)
                     + (g.beats ? '' : '<br>not distinguishable from the rest')).addTo(layer);
      pts.push([p.lat, p.lon]);
    });
    v.place.thin.forEach(function (t) {
      var p = R.places[t.name];
      if (!p) return;
      L.circleMarker([p.lat, p.lon], { radius: 3, color: col('--grey'), weight: 1, fill: false })
        .bindTooltip(esc(p.label) + ' · ' + t.n + ' offers · too few to rank').addTo(layer);
      pts.push([p.lat, p.lon]);
    });
    if (pts.length) map.fitBounds(pts, { padding: [20, 20], maxZoom: 14 });
    else map.setView([0, 0], 2);
  }

  /* The second pass's tables: one renderer for every one, by its columns'
     kinds. Sortable by any column (click a heading); the value sorted by is
     the raw figure, kept on the cell. */
  function fmt(f, v) {
    if (v === null || v === undefined || v === '') return '—';
    if (f === 't') return esc(v);
    if (f === 'n') return String(v);
    if (f === '$') return m(v);
    if (f === 's$') return sg(v);
    if (f === '%') return pc(v);
    if (f === 'min') return v.toFixed(1) + ' min';
    if (f === 'dmin') return (v >= 0 ? '+' : '−') + Math.abs(v).toFixed(1) + ' min';
    if (f === 'mi') return v.toFixed(1) + ' mi';
    if (f === 'h') return v.toFixed(1) + ' h';
    if (f === 'r') return v.toFixed(1);
    if (f === 'r2') return v.toFixed(2);
    if (f === 'x') return v.toFixed(2) + '×';
    if (f === 'p') return v === 0 ? 'p < ' + (1 / R.shuffles).toFixed(4) : v.toFixed(3);
    if (f === '$ci') return ci(v, m);
    if (f === '%ci') return ci(v, pc);
    if (f === 'minci' || f === 'dminci') return ci(v, function (x) { return x.toFixed(1); });
    if (f === 'mici') return ci(v, function (x) { return x.toFixed(1); });
    return esc(v);
  }
  function sparkSvg(weeks, top) {
    if (!weeks || !weeks.length) return '—';
    var W = 140, H = 30, n = weeks.length;
    function x(i) { return n === 1 ? W / 2 : 4 + i * (W - 8) / (n - 1); }
    function y(v) { return H / 2 - (v / top) * (H / 2 - 3); }
    var pts = weeks.map(function (w, i) { return x(i).toFixed(1) + ',' + y(w.score).toFixed(1); });
    var tipText = weeks.map(function (w) { return esc(w.w) + ': ' + sg(w.score) + ' (n ' + w.n + ')'; }).join('<br>');
    return '<svg class="spark" viewBox="0 0 ' + W + ' ' + H + '" data-tip="' + esc(tipText) + '" role="img" '
      + 'aria-label="score by week"><line class="z" x1="0" x2="' + W + '" y1="' + y(0) + '" y2="' + y(0) + '"/>'
      + '<polyline points="' + pts.join(' ') + '"/>' + weeks.map(function (w, i) {
        return '<circle cx="' + x(i).toFixed(1) + '" cy="' + y(w.score).toFixed(1) + '" r="2"/>';
      }).join('') + '</svg>';
  }
  function sortVal(f, v) {
    if (v === null || v === undefined || v === '') return '';
    if (/ci$/.test(f)) return v[0];
    if (f === 'spark') return v.length;
    return v;
  }
  function moreTable(el, t) {
    if (!el) return;
    if (!t || !t.rows || !t.rows.length) { el.innerHTML = '<p class="note">Nothing clears the floor here.</p>'; return; }
    var top = 1;
    t.cols.forEach(function (c) {
      if (c.f !== 'spark') return;
      t.rows.forEach(function (r) { (r[c.k] || []).forEach(function (w) { top = Math.max(top, Math.abs(w.score)); }); });
    });
    el.innerHTML = '<div class="tw"><table><thead><tr>' + t.cols.map(function (c) {
      return '<th>' + esc(c.h) + '</th>';
    }).join('') + '</tr></thead><tbody>' + t.rows.map(function (r) {
      return '<tr>' + t.cols.map(function (c) {
        var sv = sortVal(c.f, r[c.k]);
        return '<td data-v="' + esc(typeof sv === 'number' ? String(sv) : sv) + '">'
          + (c.f === 'spark' ? sparkSvg(r[c.k], top) : fmt(c.f, r[c.k])) + '</td>';
      }).join('') + '</tr>';
    }).join('') + '</tbody></table></div>';
  }
  function drawMore(v) {
    Object.keys(v.more).forEach(function (k) { moreTable(document.getElementById('m-' + k), v.more[k]); });
    Object.keys(v.best).forEach(function (k) { moreTable(document.getElementById('b-' + k), v.best[k]); });
    moreTable(document.getElementById('m-quietPlace'), R.quiet.place);
    moreTable(document.getElementById('m-quietTown'), R.quiet.town);
    moreTable(document.getElementById('m-trendPlace'), R.trend.place);
    moreTable(document.getElementById('m-trendTown'), R.trend.town);
  }

  // Any table: click a heading to sort by it, again to turn it round.
  function cellVal(td) {
    var d = td.getAttribute('data-v');
    var t = d !== null ? d : td.textContent.replace(/[$,%×+]|min|mi|\s/g, '').replace('−', '-');
    if (t === '' || t === '—') return null;
    var n = Number(t);
    return isFinite(n) ? n : (d !== null ? d : td.textContent).toLowerCase();
  }
  document.addEventListener('click', function (e) {
    var th = e.target.closest && e.target.closest('th');
    if (!th) return;
    var table = th.closest('table'), body = table.tBodies[0];
    if (!body) return;
    var i = Array.prototype.indexOf.call(th.parentNode.children, th);
    var dir = th.getAttribute('aria-sort') === 'descending' ? 1 : -1;
    Array.prototype.forEach.call(th.parentNode.children, function (h) { h.removeAttribute('aria-sort'); });
    th.setAttribute('aria-sort', dir === 1 ? 'ascending' : 'descending');
    if (table.classList.contains('groups')) {
      // A restaurant moves with its branches: sort the tbodies by their first row.
      var bodies = Array.prototype.slice.call(table.tBodies);
      bodies.sort(function (a, b) {
        var x = cellVal(a.rows[0].cells[i]), y = cellVal(b.rows[0].cells[i]);
        if (x === null) return y === null ? 0 : 1;
        if (y === null) return -1;
        return (x < y ? -1 : x > y ? 1 : 0) * dir;
      });
      bodies.forEach(function (b) { table.appendChild(b); });
      return;
    }
    var rows = Array.prototype.slice.call(body.rows);
    rows.sort(function (a, b) {
      var x = cellVal(a.cells[i]), y = cellVal(b.cells[i]);
      if (x === null) return y === null ? 0 : 1;
      if (y === null) return -1;
      return (x < y ? -1 : x > y ? 1 : 0) * dir;
    });
    rows.forEach(function (r) { body.appendChild(r); });
  });
  function markSortable() {
    Array.prototype.forEach.call(document.querySelectorAll('th'), function (h) { h.classList.add('sortable'); });
  }

  /* Tabs: one section at a time, the pick kept in the address, in two rows
     (html()'s nav): the groups, and the chosen group's tabs. A tab's group
     is the span it sits in, so the page needs no second list of them. */
  var tabs = document.getElementById('tabs');
  var groups = document.getElementById('groups');
  var current = null;
  var lastIn = {};     // the tab last open in each group, for a press on the group
  function buttons() { return Array.prototype.slice.call(tabs.querySelectorAll('button[data-tab]')); }
  function groupOf(id) {
    var b = tabs.querySelector('button[data-tab="' + id + '"]');
    return b ? b.parentNode.getAttribute('data-group') : null;
  }
  // The tabs the Hours picker reaches (GROUPS' fourth field, carried over in
  // the data as R.hourly); elsewhere it is hidden, not left changing nothing.
  var HOURLY = {};
  (R.hourly || []).forEach(function (t) { HOURLY[t] = true; });
  var navAt = document.getElementById('navAt');
  function showTab(id) {
    if (!groupOf(id)) id = 'overview';
    current = id;
    var g = groupOf(id);
    lastIn[g] = id;
    buttons().forEach(function (b) {
      b.setAttribute('aria-pressed', b.getAttribute('data-tab') === id ? 'true' : 'false');
    });
    Array.prototype.forEach.call(groups.children, function (b) {
      b.setAttribute('aria-selected', b.getAttribute('data-group') === g ? 'true' : 'false');
    });
    // The chosen group's tabs only; the Overview is one tab and needs no row.
    Array.prototype.forEach.call(tabs.children, function (sp) { sp.hidden = sp.getAttribute('data-group') !== g; });
    tabs.hidden = g === 'overview';
    Array.prototype.forEach.call(document.querySelectorAll('section[data-tab]'), function (sec) {
      sec.hidden = sec.getAttribute('data-tab') !== id;
    });
    document.getElementById('hoursBar').hidden = !HOURLY[id];
    document.getElementById('strip').hidden = id === 'overview';
    // The pressed tab into view in its sideways row (a phone's), without
    // moving the page.
    var on = tabs.querySelector('button[aria-pressed="true"]');
    if (on && tabs.scrollWidth > tabs.clientWidth) tabs.scrollLeft = on.offsetLeft - tabs.clientWidth / 2 + on.offsetWidth / 2;
    if (id === 'map') {
      drawMap(R.views[sel.value]);
      if (map) map.invalidateSize();
    }
    // Drawn when first shown (a Leaflet map made in a hidden section has no
    // size), and again on each pick.
    if (id === 'around') {
      drawAround();
      if (aMap) { aMap.invalidateSize(); drawAround(); }
    }
  }
  // A new tab starts at its top: a press from far down a long table would
  // otherwise open the next tab somewhere in its middle.
  function toTop() {
    var y = navAt.getBoundingClientRect().top + window.pageYOffset;
    if (window.pageYOffset > y) window.scrollTo(0, y);
  }
  function remember(id) {
    try { history.replaceState(null, '', '#' + id); } catch (err) { /* a file: page */ }
  }
  tabs.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('button[data-tab]');
    if (!b) return;
    showTab(b.getAttribute('data-tab'));
    remember(b.getAttribute('data-tab'));
    toTop();
  });
  groups.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('button[data-group]');
    if (!b) return;
    var g = b.getAttribute('data-group');
    var first = tabs.querySelector('.tg[data-group="' + g + '"] button[data-tab]');
    var id = lastIn[g] || (first && first.getAttribute('data-tab'));
    showTab(id);
    remember(id);
    toTop();
  });
  /* The address: a tab's id (#strategy, #targets, every one the page ever
     had), or the id of a part inside one (#s-blocks, a fold's id): that tab
     opens, the part's folds open, and it is scrolled to. Anything else is the
     Overview. Read on load and on every change, so the Overview's links (and
     a link from elsewhere, like the offers page's #strategy) work in place. */
  function route() {
    var h = '';
    try { h = decodeURIComponent((location.hash || '').slice(1)); } catch (err) { h = ''; }
    if (groupOf(h)) { showTab(h); toTop(); return; }
    var el = h ? document.getElementById(h) : null;
    var sec = el && el.closest ? el.closest('section[data-tab]') : null;
    if (!sec) { showTab('overview'); return; }
    showTab(sec.getAttribute('data-tab'));
    for (var d = el; d; d = d.parentNode) if (d.tagName === 'DETAILS') d.open = true;
    el.scrollIntoView();
  }
  window.addEventListener('hashchange', route);
  // On a phone the folds start shut: the tables are wider than the screen,
  // and the Strategy tab's fourteen of them were seven screens of scrolling.
  // As written they are open, which is what a laptop (and a page with no
  // script) gets.
  if (window.matchMedia && window.matchMedia('(max-width: 640px)').matches) {
    Array.prototype.forEach.call(document.querySelectorAll('details.fold'), function (d) { d.open = false; });
  }
  // A fold with nothing in it (no "too few" list this time) is not shown,
  // rather than offering a heading that opens on nothing. Asked after every
  // draw, because the hours picked change what each holds.
  function tidyFolds() {
    Array.prototype.forEach.call(document.querySelectorAll('details.fold'), function (d) {
      var body = Array.prototype.slice.call(d.children, 1);
      d.hidden = !body.some(function (n) { return (n.textContent || '').trim() || n.querySelector('table,svg'); });
    });
  }
  var sel = document.getElementById('when');
  ['all'].concat([0, 1, 2, 3, 4, 5, 6, 7]).forEach(function (k) {
    var v = R.views[k];
    var o = document.createElement('option');
    o.value = k;
    o.textContent = (k === 'all' ? 'All hours, held to each 3-hour block' : v.name) + ' (' + v.offers + ')';
    sel.appendChild(o);
  });
  function draw() {
    var v = R.views[sel.value];
    document.getElementById('whenNote').textContent = sel.value === 'all'
      ? 'Hours held still: each offer is compared with the same three hours elsewhere.'
      : 'One block picked: nothing left to hold still, so the score is against the other cells in these hours.';
    [['place', 'places'], ['town', 'towns'], ['grid', 'grid cells']].forEach(function (k) {
      document.getElementById(k[0] + 'Test').innerHTML = testText(v[k[0]], k[1]);
      dotPlot(document.getElementById(k[0] + 'Plot'), v[k[0]], k[0], '$', false);
      table(document.getElementById(k[0] + 'Table'), v[k[0]], k[0]);
      thinList(document.getElementById(k[0] + 'Thin'), v[k[0]], k[0], 'offers');
    });
    [['waitedTown', 'town', 'towns where the car was'], ['waitedGrid', 'grid', 'cells where the car was']].forEach(function (k) {
      if (!v[k[0]] || !document.getElementById(k[0] + 'Test')) return;
      document.getElementById(k[0] + 'Test').innerHTML = testText(v[k[0]], k[2]);
      dotPlot(document.getElementById(k[0] + 'Plot'), v[k[0]], k[1], '$', false);
      table(document.getElementById(k[0] + 'Table'), v[k[0]], k[1]);
      thinList(document.getElementById(k[0] + 'Thin'), v[k[0]], k[1], 'offers');
    });
    document.getElementById('restTest').innerHTML = testText(v.rest, 'restaurants');
    dotPlot(document.getElementById('restPlot'), v.rest, 'rest', '$', false);
    restTable(v.rest);
    document.getElementById('dropTest').innerHTML = testText(v.dropTown, 'wait by town');
    dropTable(document.getElementById('dropTown'), v.dropTown, 'town');
    dropTable(document.getElementById('dropGrid'), v.dropGrid, 'cell');
    drawMore(v);
    markSortable();
    tidyFolds();
    if (current === 'map') drawMap(v);
  }
  sel.addEventListener('change', draw);

  /* When & where: the slot picked out of R.whenwhere and its areas sorted by
     the top share picked. Nothing is worked out here but the sort. */
  function wwName(id) { var s0 = document.getElementById(id); return s0.options[s0.selectedIndex].getAttribute('data-name'); }
  function rt(v) { return v === null || v === undefined ? '—' : v.toFixed(2); }
  /* The hour strip: the day picked, its 24 clock hours in the driver day's
     order, each the slot line's good/hr (every area together). Coloured by
     the slot line's own mark (against every slot together), grey with its n
     under the floor, blank with no waiting; a press picks that hour. */
  function shortHour(i) { var c = (i + 4) % 24; return (c % 12 || 12) + (c < 12 ? 'a' : 'p'); }
  function drawStrip(W, d, b, ti) {
    var el = document.getElementById('wwStrip');
    if (!el) return;
    var blk = W.blocks.length && /^\d$/.test(b) ? Number(b) : null;
    var BL = [[0, 6], [6, 10], [10, 13], [13, 16], [16, 19], [19, 24]];
    var cells = '';
    for (var i = 0; i < 24; i++) {
      var sl = W.slots[d + '|h' + i], a = sl && sl.all, cls = [], val, tipText;
      // An hour with no time waited is greyed (the UX review's R1), as one
      // with no card at all: nothing to read there either way.
      if (!a || !(a.h > 0)) { cls.push('none'); val = '–'; tipText = W.hours[i] + ': no time waited on record'; }
      else if (!a.ok) {
        cls.push('thin'); val = 'n' + a.n;
        tipText = W.hours[i] + ': ' + a.n + ' offers, ' + a.h.toFixed(1) + ' h on ' + a.d + ' shift days — under the floor';
      } else {
        var mk = a.mk && a.mk[ti];
        if (mk) cls.push(mk === 'above' ? 'up' : 'down');
        val = a.r[ti].toFixed(1);
        tipText = W.hours[i] + ': ' + rt(a.r[ti]) + ' good/hr (99% ' + rt(a.lo[ti]) + '–' + rt(a.hi[ti]) + '), '
          + a.h.toFixed(1) + ' h, ' + a.n + ' offers' + (mk ? ', ' + mk + ' every slot together' : '');
      }
      if (b === 'h' + i) cls.push('on');
      if (blk !== null && i >= BL[blk][0] && i < BL[blk][1]) cls.push('in');
      cells += '<button type="button" data-h="' + i + '" class="' + cls.join(' ') + '" title="' + esc(tipText)
        + '" aria-label="' + esc(tipText) + '"><span class="hl">' + shortHour(i) + '</span><span>' + val + '</span></button>';
    }
    el.innerHTML = cells;
    var every = W.slots['any|any'];
    document.getElementById('wwStripNote').innerHTML = esc(wwName('wwDay')) + ', hour by hour, every area together: '
      + 'good per hour waited. Coloured only where its 99% interval (widened by how the days swing) lies wholly above '
      + 'or below every slot together (' + (every ? rt(every.all.r[ti]) : '—') + ' good/hr); grey with its offers (n) '
      + 'under ' + W.minHours + ' h on ' + W.minDays + ' shift days. About 1 coloured square in 100 can be chance. '
      + 'Press an hour to pick it.';
  }
  function drawWW() {
    var W = R.whenwhere, el = document.getElementById('wwTable');
    if (!W || !el) return;
    var d = document.getElementById('wwDay').value, b = document.getElementById('wwBlock').value;
    var ti = Number(document.getElementById('wwTop').value), unit = document.getElementById('wwUnit').value;
    var cut = W.cuts[ti];
    document.getElementById('wwCut').textContent = cut === null ? 'no offers yet'
      : 'good = top ' + W.tops[ti] + '%: ≥ ' + m(cut) + '/hr';
    // Each block's hours on the day picked, so an empty slot shows before it is picked.
    Array.prototype.forEach.call(document.getElementById('wwBlock').options, function (o) {
      var sl = W.slots[d + '|' + o.value];
      o.textContent = o.getAttribute('data-name') + ' · ' + (sl ? sl.all.h : 0).toFixed(1) + ' h';
    });
    drawStrip(W, d, b, ti);
    var slot = W.slots[d + '|' + b], every = W.slots['any|any'];
    var said = '<b>' + esc(wwName('wwDay') + ', ' + wwName('wwBlock').toLowerCase()) + '</b>';
    if (!slot) {
      document.getElementById('wwSlot').innerHTML = said + ': no waiting on record in this slot.';
      el.innerHTML = ''; document.getElementById('wwThin').innerHTML = '';
      return;
    }
    var a0 = slot.all;
    document.getElementById('wwSlot').innerHTML = said + ': ' + a0.h.toFixed(1) + ' h waited on ' + a0.d
      + ' shift days, ' + a0.n + ' offers, ' + a0.g[ti] + ' good — <b>' + rt(a0.r[ti]) + ' good/hr</b> (99% '
      + rt(a0.lo[ti]) + '–' + rt(a0.hi[ti]) + '), P90 ' + m(a0.p90) + '/hr, median ' + m(a0.p50) + '/hr.'
      + (every && every !== slot ? ' Every slot together: ' + rt(every.all.r[ti]) + ' good/hr over '
         + every.all.h.toFixed(1) + ' h.' : '');
    var u = slot[unit];
    function nm(a) { return unit === 'cell' ? label('grid', a) : a; }
    function apps(s) {
      var k = s.u + s.dd;
      return k ? Math.round(s.u / k * 100) + '% · ' + Math.round(s.dd / k * 100) + '%' : '—';
    }
    var rows = u.ranked.slice().sort(function (x, y) { return y.r[ti] - x.r[ti] || y.h - x.h; });
    el.innerHTML = rows.length ? '<div class="tw"><table><thead><tr><th>' + (unit === 'cell' ? 'cell' : 'town')
      + '</th><th>good / hr</th><th>99%</th><th>hours waited</th><th>offers</th><th>good</th><th class="wide">P90 $/hr</th>'
      + '<th>median $/hr</th><th class="wide">Uber · DD</th><th></th></tr></thead><tbody>' + rows.map(function (s) {
        var mk = s.mk[ti];
        // The rate and its interval beside the name: on a phone the table
        // scrolls sideways and the first columns are the ones seen.
        // On a phone P90 and the app split ride under the name (R1), the
        // table's own columns for them hidden, so it scrolls less.
        return '<tr><td>' + esc(nm(s.a)) + '<small class="narrow">P90 ' + m(s.p90) + '/hr · Uber · DD ' + apps(s)
          + '</small></td><td data-v="' + s.r[ti] + '">' + rt(s.r[ti]) + '</td><td data-v="'
          + s.lo[ti] + '">' + rt(s.lo[ti]) + '–' + rt(s.hi[ti]) + '</td><td data-v="' + s.h + '">' + s.h.toFixed(1)
          + ' h</td><td>' + s.n + '</td><td>' + s.g[ti] + '</td><td class="wide">' + m(s.p90) + '</td><td>' + m(s.p50) + '</td><td class="wide" data-v="'
          + (s.u + s.dd ? s.u / (s.u + s.dd) : '') + '">' + apps(s) + '</td><td>'
          + (mk ? '<span class="tag ' + (mk === 'above' ? 'up' : 'down') + '">' + mk + ' the slot</span>' : '')
          + '</td></tr>';
      }).join('') + '</tbody></table></div>'
      : '<p class="note">No ' + (unit === 'cell' ? 'cell' : 'town') + ' has ' + W.minHours + ' h waited on '
        + W.minDays + ' shift days in this slot yet.</p>';
    document.getElementById('wwThin').innerHTML = (u.thin.length ? '<p><b>Too little time there yet</b> (under '
      + W.minHours + ' h or ' + W.minDays + ' shift days in this slot): ' + u.thin.slice(0, 60).map(function (t) {
        return esc(nm(t.a)) + ' ' + t.h.toFixed(1) + ' h (' + t.d + (t.d === 1 ? ' day' : ' days') + ')';
      }).join(', ') + (u.thin.length > 60 ? ', and ' + (u.thin.length - 60) + ' more' : '') + '.</p>' : '')
      + (u.left ? '<p>' + u.left + ' more ' + (unit === 'cell' ? 'cell' : 'town') + (u.left === 1 ? '' : 's')
         + ' where the car waited in this hour ' + (u.left === 1 ? 'clears' : 'clear') + ' the floor in no single hour of this day, so '
         + (u.left === 1 ? 'it is' : 'they are')
         + ' not listed hour by hour; pick a block to see ' + (u.left === 1 ? 'it' : 'them') + '.</p>' : '');
    markSortable();
  }
  var stripEl = document.getElementById('wwStrip');
  if (stripEl) stripEl.addEventListener('click', function (e) {
    var bt = e.target.closest && e.target.closest('button[data-h]');
    if (!bt) return;
    document.getElementById('wwBlock').value = 'h' + bt.getAttribute('data-h');
    drawWW();
  });
  ['wwDay', 'wwBlock', 'wwTop', 'wwUnit'].forEach(function (id) {
    var e0 = document.getElementById(id);
    if (e0) e0.addEventListener('change', drawWW);
  });
  /* Offers around you (aroundYou): the dots of the slot picked, coloured by
     the cutoff picked, on the Map tab's own Leaflet and tiles — or, with no
     internet, on a blank square — and three bar charts. This tab is the
     page's one exception to "computes no statistic of its own": the counts
     by ring and band over the slot picked, a median, and Wilson's interval
     on each share (the report's own wilson()), because the dots are already
     here and every slot of them worked out beforehand would be most of the
     file. The rings, the bands and the cutoffs are the server's. */
  function wilsonP(k, n) {
    if (!n) return null;
    var z = 1.96, p = k / n, dd = 1 + z * z / n;
    var mid = (p + z * z / (2 * n)) / dd, half = z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / dd;
    return [Math.max(0, mid - half), Math.min(1, mid + half)];
  }
  function aPick(d, b, day, h) {
    var A0 = R.around;
    if (d === 'wkday' && !(day >= 1 && day <= 5)) return false;
    if (d === 'wkend' && !(day === 0 || day === 6)) return false;
    if (/^\d$/.test(d) && Number(d) !== day) return false;
    if (b === 'any') return true;
    if (b[0] === 'h') return Number(b.slice(1)) === h;
    var bl = A0.blockHours[Number(b)];
    return h >= bl[0] && h < bl[1];
  }
  function hbRow(name, frac, cls, fig, whisk, thin) {
    return '<div class="hb' + (thin ? ' thinrow' : '') + '"><span class="nm">' + esc(name) + '</span><span class="track">'
      + (frac === null ? '' : '<span class="fill' + (cls ? ' ' + cls : '') + '" style="width:'
         + Math.max(0, Math.min(100, frac * 100)).toFixed(1) + '%"></span>')
      + (whisk ? '<span class="wh" style="left:' + (whisk[0] * 100).toFixed(1) + '%;width:'
         + Math.max(0.5, (whisk[1] - whisk[0]) * 100).toFixed(1) + '%"></span>' : '')
      + '</span><span class="fig">' + fig + '</span></div>';
  }
  var aMap = null, aLayer = null;
  // Each dot of a square at a point of a sunflower inside it, in miles from
  // the square's centre: spread by geography, so it scales with the zoom.
  function spread(list, binMi) {
    var out = [], n = list.length;
    list.forEach(function (x, j) {
      var rr = 0.42 * binMi * Math.sqrt((j + 0.5) / n), th = j * 2.399963;
      out.push({ x: x, dy: rr * Math.cos(th), dx: rr * Math.sin(th) });
    });
    return out;
  }
  function drawAround() {
    var A0 = R.around, W = R.whenwhere, el = document.getElementById('aMap');
    if (!A0 || !el) return;
    var d = document.getElementById('aDay').value, b = document.getElementById('aBlock').value;
    var ti = Number(document.getElementById('aTop').value), cut = W.cuts[ti];
    document.getElementById('aCut').textContent = cut === null ? 'no offers yet'
      : 'top ' + W.tops[ti] + '%: ≥ ' + m(cut) + '/hr';
    var D = A0.dots, byBin = {}, shown = 0, good = 0;
    for (var i = 0; i < D.b.length; i++) {
      if (!aPick(d, b, D.d[i], D.h[i])) continue;
      var g = cut !== null && D.r[i] >= cut;
      (byBin[D.b[i]] = byBin[D.b[i]] || []).push(g);
      shown += 1; if (g) good += 1;
    }
    var said = '<b>' + esc(wwName('aDay') + ', ' + wwName('aBlock').toLowerCase()) + '</b>';
    document.getElementById('aSays').innerHTML = said + ': ' + shown + ' offers drawn, ' + good + ' good'
      + (shown ? ' (' + Math.round(good / shown * 100) + '%)' : '') + (cut === null ? '' : ' at ≥ ' + m(cut) + '/hr') + '.';
    var pts = [];
    Object.keys(byBin).forEach(function (k) {
      var c = A0.bins[Number(k)];
      spread(byBin[k], A0.binMi).forEach(function (p) {
        pts.push({ lat: c[0] + p.dy / 69, lon: c[1] + p.dx / (69 * Math.cos(c[0] * Math.PI / 180)), good: p.x });
      });
    });
    var up = col('--up'), grey = col('--grey');
    var note = document.getElementById('aMapNote');
    if (typeof L !== 'undefined') {
      if (!aMap) {
        aMap = L.map('aMap', { preferCanvas: true });
        L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
          maxZoom: 19, attribution: '&copy; OpenStreetMap contributors' }).addTo(aMap);
      }
      if (aLayer) aLayer.remove();
      aLayer = L.layerGroup().addTo(aMap);
      if (A0.centre) {
        for (var rg = 1; rg <= Math.min(A0.rings, 5); rg++) {
          L.circle([A0.centre.lat, A0.centre.lon], { radius: rg * A0.ringMi * 1609.34, color: col('--axis'), weight: 1,
            dashArray: '4 4', fill: false, interactive: false }).addTo(aLayer);
        }
      }
      pts.forEach(function (p) {
        L.circleMarker([p.lat, p.lon], { radius: 3, stroke: false, fillColor: p.good ? up : grey, fillOpacity: 0.85 })
          .addTo(aLayer);
      });
      if (pts.length) aMap.fitBounds(pts.map(function (p) { return [p.lat, p.lon]; }), { padding: [20, 20], maxZoom: 15 });
      else if (A0.centre) aMap.setView([A0.centre.lat, A0.centre.lon], 12);
      else aMap.setView([0, 0], 2);
      note.textContent = 'Dashed rings: 1 to 5 miles from the most-used waiting area, as in the chart below.';
    } else {
      // No Leaflet (no internet): the same dots on a blank square, north up,
      // a mile to scale, and the rings — no street under them.
      var Wd = el.clientWidth || 600, Hd = el.clientHeight || 460;
      var lats = pts.map(function (p) { return p.lat; }), lons = pts.map(function (p) { return p.lon; });
      if (A0.centre) { lats.push(A0.centre.lat); lons.push(A0.centre.lon); }
      if (!lats.length) { el.innerHTML = '<p class="note" style="padding:12px">No dot in this slot.</p>'; }
      else {
        var la0 = Math.min.apply(null, lats), la1 = Math.max.apply(null, lats);
        var lo0 = Math.min.apply(null, lons), lo1 = Math.max.apply(null, lons);
        var kx = Math.cos((la0 + la1) / 2 * Math.PI / 180);
        var spanX = Math.max((lo1 - lo0) * kx, 0.01), spanY = Math.max(la1 - la0, 0.01);
        var sc = Math.min((Wd - 40) / spanX, (Hd - 40) / spanY);
        var ox = (Wd - spanX * sc) / 2, oy = (Hd - spanY * sc) / 2;
        var X = function (lon) { return ox + (lon - lo0) * kx * sc; };
        var Y = function (lat) { return Hd - oy - (lat - la0) * sc; };
        var mile = sc / 69;
        var svg = '<svg viewBox="0 0 ' + Wd + ' ' + Hd + '" aria-hidden="true">';
        if (A0.centre) {
          for (var rr2 = 1; rr2 <= Math.min(A0.rings, 5); rr2++) {
            svg += '<circle cx="' + X(A0.centre.lon).toFixed(1) + '" cy="' + Y(A0.centre.lat).toFixed(1) + '" r="'
              + (rr2 * A0.ringMi * mile).toFixed(1) + '" fill="none" stroke="' + col('--axis') + '" stroke-dasharray="4 4"/>';
          }
        }
        pts.forEach(function (p) {
          svg += '<circle cx="' + X(p.lon).toFixed(1) + '" cy="' + Y(p.lat).toFixed(1) + '" r="2.6" fill="'
            + (p.good ? up : grey) + '" fill-opacity="0.85"/>';
        });
        svg += '<line x1="16" x2="' + (16 + mile).toFixed(1) + '" y1="' + (Hd - 14) + '" y2="' + (Hd - 14)
          + '" stroke="' + col('--ink2') + '" stroke-width="2"/><text x="16" y="' + (Hd - 20) + '" fill="'
          + col('--ink2') + '" font-size="12">1 mi</text></svg>';
        el.innerHTML = svg;
      }
      note.textContent = 'The map needs the internet for Leaflet and its tiles: the dots are drawn on a blank '
        + 'square, north up, with a mile to scale and dashed rings 1 to 5 miles from the most-used waiting area.';
    }
    // (a) the share good by ring.
    var nR = [], kR = [];
    for (var j = 0; j < D.b.length; j++) {
      if (D.g[j] === null || !aPick(d, b, D.d[j], D.h[j])) continue;
      nR[D.g[j]] = (nR[D.g[j]] || 0) + 1;
      if (cut !== null && D.r[j] >= cut) kR[D.g[j]] = (kR[D.g[j]] || 0) + 1;
    }
    var rings = '';
    for (var q = 0; q <= A0.rings; q++) {
      var n = nR[q] || 0, k = kR[q] || 0;
      if (!n) continue;
      var nm = q === A0.rings ? A0.rings * A0.ringMi + ' mi or more' : q * A0.ringMi + '–' + (q + 1) * A0.ringMi + ' mi';
      if (n < R.descMinN) { rings += hbRow(nm, null, '', n + ' offers — too few', null, true); continue; }
      var w0 = wilsonP(k, n);
      rings += hbRow(nm, k / n, 'up', pc(k / n) + ' good [' + pc(w0[0]) + ', ' + pc(w0[1]) + '] · n ' + n, w0, false);
    }
    document.getElementById('aRings').innerHTML = rings || '<p class="note">No dot in this slot.</p>';
    // (b) When & where's slot table, drawn.
    var slot = W.slots[d + '|' + b], areas = '';
    if (slot) {
      var unit = slot.town.ranked.length ? 'town' : 'cell', u = slot[unit];
      var rows = u.ranked.slice().sort(function (x, y) { return y.r[ti] - x.r[ti] || y.h - x.h; });
      var top = Math.max.apply(null, [0.1].concat(rows.map(function (s0) { return s0.hi[ti]; })));
      rows.forEach(function (s0) {
        var mk = s0.mk[ti];
        areas += hbRow(unit === 'cell' ? label('grid', s0.a) : s0.a, s0.r[ti] / top, mk === 'above' ? 'up' : mk === 'below' ? 'down' : '',
                       rt(s0.r[ti]) + ' good/hr [' + rt(s0.lo[ti]) + '–' + rt(s0.hi[ti]) + '] · ' + s0.h.toFixed(1) + ' h',
                       [s0.lo[ti] / top, s0.hi[ti] / top], false);
      });
      if (!rows.length) areas = '<p class="note">No area has ' + W.minHours + ' h waited on ' + W.minDays
        + ' shift days in this slot yet.</p>';
      if (u.thin.length) areas += '<p class="note">Too little time there yet: ' + u.thin.length + ' '
        + (unit === 'cell' ? 'cell' : 'town') + (u.thin.length === 1 ? '' : 's') + ' (see When &amp; where).</p>';
    } else {
      areas = '<p class="note">No waiting on record in this slot.</p>';
    }
    document.getElementById('aAreas').innerHTML = areas;
    // (c) the card's own drive to the pickup.
    var P0 = A0.pickup, byB = {};
    for (var e = 0; e < P0.b.length; e++) {
      if (!aPick(d, b, P0.d[e], P0.h[e])) continue;
      (byB[P0.b[e]] = byB[P0.b[e]] || []).push(P0.r[e]);
    }
    var bands = '';
    P0.bands.forEach(function (nm2, bi) {
      var v = byB[bi] || [];
      if (!v.length) return;
      if (v.length < R.descMinN) { bands += hbRow(nm2, null, '', v.length + ' offers — too few', null, true); return; }
      var kk = cut === null ? 0 : v.filter(function (x) { return x >= cut; }).length;
      var s1 = v.slice().sort(function (x, y) { return x - y; });
      var med = s1.length % 2 ? s1[(s1.length - 1) / 2] : (s1[s1.length / 2 - 1] + s1[s1.length / 2]) / 2;
      var w1 = wilsonP(kk, v.length);
      bands += hbRow(nm2, kk / v.length, 'up', pc(kk / v.length) + ' good [' + pc(w1[0]) + ', ' + pc(w1[1]) + '] · median '
                     + m(med) + '/hr · n ' + v.length, w1, false);
    });
    document.getElementById('aPickup').innerHTML = bands
      || '<p class="note">No card in this slot printed its drive to the pickup.</p>';
  }
  ['aDay', 'aBlock', 'aTop'].forEach(function (id) {
    var e0 = document.getElementById(id);
    if (e0) e0.addEventListener('change', drawAround);
  });
  coverageTable();
  levelsTable();
  shareTests();
  draw();
  drawWW();
  route();
}).replace(/^function page\(\) \{/, '(function () {').replace(/\}$/, '}());');

/* --- talking to the server, the NucBox and the GPS log -------------------- */

async function getJson(u) {
  var res = await fetch(u, { headers: { Accept: 'application/json' } });
  var body = null;
  try { body = await res.json(); } catch (e) { body = null; }
  return { ok: res.ok, status: res.status, body: body };
}

/* The whole journal, a page of JOURNAL_PAGE at a time (the reporting
 * review's R2). The server lists at most 20,000 offers, the newest, and the
 * report read one answer, so past 20,000 it quietly described the newest
 * 20,000 and said so only on stdout. It now asks again for the offers before
 * the oldest it holds (`until`, the server's), keeping the first answer's
 * takes, records and every figure the server worked over the whole window,
 * until the server says nothing was cut. A server from before `until` sends
 * the same page again: no new offer, so it stops, and the answer keeps
 * `truncated`, which the page now says at its head. `getter` stands in for
 * the network in the checks. */
var JOURNAL_PAGE = 20000;
var JOURNAL_PAGES_MAX = 50;
async function loadJournal(base, sinceMs, getter) {
  var get = getter || getJson;
  var root = base.replace(/\/+$/, '') + '/api/journal?days=3650&limit=' + JOURNAL_PAGE
    + (sinceMs ? '&since=' + sinceMs : '');
  async function one(until) {
    var u = root + (until ? '&until=' + until : '');
    var got = await get(u);
    if (!got.ok || !got.body) throw new Error(u + ' answered ' + got.status);
    if (got.body.unreadable) throw new Error('the server could not read its journal (' + got.body.unreadable + ')');
    return got.body;
  }
  var body = await one(null);
  var offers = Array.isArray(body.offers) ? body.offers.slice() : [];
  var seen = Object.create(null);
  offers.forEach(function (o) { if (o && typeof o.id === 'string') seen[o.id] = true; });
  var page = body, pages = 1;
  while (page.truncated && pages < JOURNAL_PAGES_MAX) {
    var oldest = Infinity;
    (page.offers || []).forEach(function (o) { if (o && typeof o.at === 'number' && o.at < oldest) oldest = o.at; });
    if (!isFinite(oldest)) break;
    // One past the oldest, so a second offer at that same moment, cut off
    // by the cap, comes too; the ids already held are skipped.
    page = await one(oldest + 1);
    pages += 1;
    var fresh = (page.offers || []).filter(function (o) { return !(o && typeof o.id === 'string' && seen[o.id]); });
    if (!fresh.length) break;
    fresh.forEach(function (o) { if (o && typeof o.id === 'string') seen[o.id] = true; });
    offers = fresh.concat(offers);
  }
  body.offers = offers;
  body.pages = pages;
  body.count = offers.length;
  body.truncated = offers.length < (body.total || 0);
  return body;
}

/* A Nominatim jsonv2 list as server.js's relay hands it to a page (nbxHits):
 * where, the display name (where a door shows), the category and the
 * feature's own name, and the limit as `cutAt`. The direct path must hand
 * map-view.js exactly what the relay would, so the same rules decide. */
function hitsOf(list) {
  return { ok: true, cutAt: list.length >= NBX_LIMIT ? NBX_LIMIT : null,
           hits: list.map(function (h) {
             return { lat: Number(h.lat), lon: Number(h.lon), name: String(h.display_name || ''),
                      kind: typeof h.category === 'string' ? h.category : null,
                      called: typeof h.name === 'string' ? h.name : '' };
           }).filter(function (h) { return isFinite(h.lat) && isFinite(h.lon); }) };
}

/* The fetch an NbxSearch is given. Its paths are the relay's (`/api/nbx/search?...`,
 * `/cross?...`, ...): a search goes to `nominatim` directly when one is named,
 * else through the server's own relay; the street index's questions only
 * through the relay. Every answer is kept in `cache` by its question — an
 * answer, never a failure: a NucBox down (502, `unreachable`) or any status
 * but 200 is asked again next time. Each question not from the cache is
 * counted in `cache.asked`, and one the NucBox did not answer (thrown,
 * `unreachable`, a 5xx) in `cache.unreachable`, for main's DEGRADED check. */
function tallyAsk(cache, unreachable) {
  cache.asked = (cache.asked || 0) + 1;
  if (unreachable) cache.unreachable = (cache.unreachable || 0) + 1;
}

/* A run whose fresh questions the NucBox mostly did not answer: offers left
 * unplaced for a Nominatim or relay that was down, not for where they are.
 * Its report is not written (the nightly keeps the old one) unless
 * --allow-degraded. Chosen, not measured: more than DEGRADED_SHARE of the
 * fresh questions AND more than DEGRADED_MIN of them, so a few misses on a
 * warm cache never refuse a night. */
var DEGRADED_SHARE = 0.2;
var DEGRADED_MIN = 50;

function degraded(cache) {
  var asked = cache.asked || 0, bad = cache.unreachable || 0;
  return bad > DEGRADED_MIN && bad > DEGRADED_SHARE * asked
    ? { asked: asked, unreachable: bad } : null;
}

function nbxFetch(opts) {
  var cache = opts.cache;
  var server = opts.server.replace(/\/+$/, '');
  // The street index's questions go to `opts.streets` (streetsBase: a relay's
  // /api/nbx, or a server's own /api/streets), else this server's relay.
  var streetsAt = opts.streets ? opts.streets.replace(/\/+$/, '') : server + '/api/nbx';
  function reply(status, body) {
    return { ok: status === 200, status: status, json: function () { return Promise.resolve(body); } };
  }
  return async function (asked) {
    // NbxSearch puts its base in front ('/api/nbx', its default: an empty
    // base is no base to it), and the question is what follows.
    var pathAsked = String(asked).replace(/^\/api\/nbx(?=\/)/, '');
    if (Object.prototype.hasOwnProperty.call(cache.answers, pathAsked)) {
      cache.hits += 1;
      return reply(200, cache.answers[pathAsked]);
    }
    var body, status;
    try {
      if (opts.nominatim && /^\/search\?/.test(pathAsked)) {
        var q = new URLSearchParams(pathAsked.slice('/search?'.length));
        var term = q.has('q') ? 'q' : 'street';
        var u = opts.nominatim.replace(/\/+$/, '') + '/search?format=jsonv2&limit=' + NBX_LIMIT + '&' + term
          + '=' + encodeURIComponent(q.get(term) || '')
          + (q.get('viewbox') ? '&viewbox=' + encodeURIComponent(q.get('viewbox')) + '&bounded=1' : '');
        var r = await getJson(u);
        if (!r.ok || !Array.isArray(r.body)) {
          tallyAsk(cache, true);
          return reply(502, { ok: false, unreachable: true, error: 'Nominatim answered ' + r.status });
        }
        body = hitsOf(r.body); status = 200;
      } else if (/^\/(cross|stretch|named|whole)\?/.test(pathAsked)) {
        var r3 = await getJson(streetsAt + pathAsked);
        body = r3.body || {}; status = r3.status;
      } else {
        var r2 = await getJson(server + '/api/nbx' + pathAsked);
        body = r2.body || {}; status = r2.status;
      }
    } catch (e) {
      tallyAsk(cache, true);
      return reply(502, { ok: false, unreachable: true, error: String(e && e.message || e) });
    }
    tallyAsk(cache, !!(body && body.unreachable) || !(status < 500));
    if (status === 200 && body && body.ok !== undefined && !body.unreachable) {
      cache.answers[pathAsked] = body;
      cache.fresh += 1;
      if (opts.onFresh) opts.onFresh();
    }
    return reply(status, body);
  };
}

/* Where the street index is asked: `url` as given — a path ending /api/nbx
 * is a relay (server.js nbxRoute: /api/nbx/cross...), a bare server is its
 * own index (/api/streets/cross..., server.js streetsRoute, NUCBOX_STREETS_FILE
 * loaded there) — or, unasked, this server's relay when it has one set, else
 * this server's own index when it has one loaded. Returns { base, said } or
 * { base: null, said } with why not. */
async function streetsBase(server, url) {
  server = server.replace(/\/+$/, '');
  async function probe(base) {
    try {
      if (/\/api\/nbx$/.test(base)) {
        var a = await getJson(base);
        return a.ok && a.body && a.body.streets ? base : null;
      }
      var b = await getJson(base.replace(/\/api\/streets$/, '') + '/api/streets');
      return b.ok && b.body && b.body.loaded ? base.replace(/\/api\/streets$/, '') + '/api/streets' : null;
    } catch (e) { return null; }
  }
  if (url) {
    var u = url.replace(/\/+$/, '');
    var got = await probe(u);
    return got ? { base: got, said: got } : { base: null, said: 'none — ' + u + ' did not answer as a street index' };
  }
  var relay = await probe(server + '/api/nbx');
  if (relay) return { base: relay, said: relay + ' (the server\'s relay)' };
  var own = await probe(server);
  if (own) return { base: own, said: own + ' (the server\'s own index)' };
  return { base: null, said: 'none — ' + server + ' has no relay to one (NUCBOX_STREETS) and no index loaded; give --streets' };
}

/* The rig's store waits, for a source whose /api/journal carries none (the
 * NucBox's copy holds no store-waits file): `url`'s /api/journal `waits`. */
/* The trips read off the app's earnings screenshots (server.js
 * /api/earnings, since 8 Nov 2026), for the Strategy tab's card vs paid. A
 * server from before it answers 404, and the tab says none were uploaded. */
async function loadEarnings(base) {
  try {
    var got = await getJson(base.replace(/\/+$/, '') + '/api/earnings?days=3650');
    return got.ok && got.body && Array.isArray(got.body.entries) ? got.body.entries : [];
  } catch (e) {
    return [];
  }
}

/* The Gold card's setting (server.js /api/gold, since 15 Nov 2026): the
 * goal and Uber's own figures, for the Strategy tab's acceptance lines. A
 * server from before it answers 404, and the defaults stand (25%, no
 * figures). */
async function loadGold(base) {
  try {
    var got = await getJson(base.replace(/\/+$/, '') + '/api/gold');
    var st = got.ok && got.body && got.body.settings;
    return st ? { goal: st.goal, uber: st.uber } : null;
  } catch (e) {
    return null;
  }
}

async function loadWaits(url) {
  var got = await getJson(url.replace(/\/+$/, '') + '/api/journal?days=1&limit=1');
  if (!got.ok || !got.body || !Array.isArray(got.body.waits)) throw new Error(url + ' answered ' + got.status + ' with no waits');
  return got.body.waits;
}

/* The car's position at each moment asked, off the GPS log, read by
 * tools/shift_report.py's load_fixes (rpi/gps.py's gate on every fix) and the
 * nearest usable fix within its NEAR_S. Python, because that is where the
 * gate is; one rule in one place. Returns [[lat, lon] | null] in order. */
var GPS_HELPER = [
  'import bisect, json, sys',
  'sys.path.insert(0, sys.argv[1])',
  'import shift_report as SR',
  'req = json.load(sys.stdin)',
  'ts = req["times"]',
  'out = [None] * len(ts)',
  'info = {}',
  'if ts:',
  '    fixes, info = SR.load_fixes(req["dir"], (min(ts) * 1000.0 - 3600e3, max(ts) * 1000.0 + 3600e3))',
  '    keys = [f[0] for f in fixes or []]',
  '    for n, t in enumerate(ts):',
  '        i = bisect.bisect_left(keys, t)',
  '        best = None',
  '        for j in (i - 1, i):',
  '            if 0 <= j < len(keys) and abs(keys[j] - t) <= SR.NEAR_S:',
  '                if best is None or abs(keys[j] - t) < abs(best[0] - t):',
  '                    best = fixes[j]',
  '        out[n] = [best[1], best[2]] if best else None',
  'print(json.dumps({"at": out, "files": info.get("files", 0), "passed": info.get("passed", 0)}))',
].join('\n');

function gpsAt(dir, timesMs) {
  var got = cp.spawnSync('python3', ['-c', GPS_HELPER, __dirname], {
    input: JSON.stringify({ dir: dir, times: timesMs.map(function (t) { return t / 1000; }) }),
    encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 });
  if (got.status !== 0) throw new Error('reading the GPS log failed: ' + (got.stderr || got.error || '').toString().slice(0, 400));
  return JSON.parse(got.stdout);
}

/* Every usable fix in [fromMs, toMs], thinned to one per `thin` seconds,
 * as [[tSec, lat, lon]] — load_fixes again, so the gate is rpi/gps.py's. */
var FIXES_HELPER = [
  'import json, sys',
  'sys.path.insert(0, sys.argv[1])',
  'import shift_report as SR',
  'req = json.load(sys.stdin)',
  'fixes, info = SR.load_fixes(req["dir"], (req["from"], req["to"]))',
  'out, last = [], None',
  'for f in fixes or []:',
  '    if f[0] * 1000.0 < req["from"] or f[0] * 1000.0 > req["to"]:',
  '        continue',
  '    if last is None or f[0] - last >= req["thin"]:',
  '        out.append([round(f[0], 1), round(f[1], 6), round(f[2], 6)])',
  '        last = f[0]',
  'print(json.dumps({"fixes": out, "files": info.get("files", 0), "passed": info.get("passed", 0)}))',
].join('\n');

function gpsFixes(dir, fromMs, toMs, thin) {
  var got = cp.spawnSync('python3', ['-c', FIXES_HELPER, __dirname], {
    input: JSON.stringify({ dir: dir, from: fromMs, to: toMs, thin: thin || SPELL_THIN_S }),
    encoding: 'utf8', maxBuffer: 512 * 1024 * 1024 });
  if (got.status !== 0) throw new Error('reading the GPS log failed: ' + (got.stderr || got.error || '').toString().slice(0, 400));
  return JSON.parse(got.stdout);
}

/* The town a 2-mile cell's centre is in, by the NucBox's own Nominatim
 * (reverse, zoom 12: the town level), or null. The cell's centre is asked,
 * never a spell's own position, and the answer is kept in the cache. */
async function cellTownOf(fetchFn, nominatim, cache, c) {
  var q = '/reverse?lat=' + c.lat.toFixed(5) + '&lon=' + c.lon.toFixed(5);
  if (Object.prototype.hasOwnProperty.call(cache.answers, q)) { cache.hits += 1; return cache.answers[q].town; }
  var r;
  try {
    r = await fetchFn(nominatim.replace(/\/+$/, '') + '/reverse?format=jsonv2&zoom=12&lat=' + c.lat.toFixed(5)
                      + '&lon=' + c.lon.toFixed(5), { headers: { Accept: 'application/json' } });
  } catch (e) { return null; }
  if (!r || !r.ok) return null;
  var body = null;
  try { body = await r.json(); } catch (e) { return null; }
  var ad = (body && body.address) || {};
  var town = ad.city || ad.town || ad.village || ad.hamlet || ad.suburb || null;
  cache.answers[q] = { ok: true, town: town };
  cache.fresh += 1;
  return town;
}

/* --- the command --------------------------------------------------------- */

function inside(child, parent) {
  var rel = path.relative(parent, child);
  return rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel));
}

function realish(p) {
  // The nearest existing ancestor's real path, so a symlink into the repo is
  // caught before anything is written.
  var abs = path.resolve(p), tail = [];
  while (!fs.existsSync(abs)) { tail.unshift(path.basename(abs)); abs = path.dirname(abs); }
  return path.join.apply(null, [fs.realpathSync(abs)].concat(tail));
}

function home(p) { return p && p[0] === '~' ? path.join(os.homedir(), p.slice(1)) : p; }

function parseArgs(argv) {
  var o = { server: null, out: path.join(os.homedir(), 'places-report'), gps: null, since: null,
            nominatim: null, cache: path.join(os.homedir(), '.cache', 'uber-scan', 'places-report-answers.json'),
            gap: MV.NBX_GAP_MS, minN: MIN_N, streets: null, waits: null, relay: null, roadAsks: 5000,
            allowDegraded: false };
  for (var i = 0; i < argv.length; i++) {
    var a = argv[i];
    var val = function () { if (i + 1 >= argv.length) throw new Error(a + ' wants a value'); return argv[++i]; };
    if (a === '--out') o.out = home(val());
    else if (a === '--gps') o.gps = home(val());
    else if (a === '--since') o.since = val();
    else if (a === '--nominatim') o.nominatim = val();
    else if (a === '--cache') o.cache = home(val());
    else if (a === '--gap') o.gap = Number(val());
    else if (a === '--min-n') o.minN = Number(val());
    else if (a === '--streets') o.streets = val();
    else if (a === '--waits') o.waits = val();
    else if (a === '--relay') o.relay = val();
    else if (a === '--road-asks') o.roadAsks = Number(val());
    else if (a === '--allow-degraded') o.allowDegraded = true;
    else if (a === '-h' || a === '--help') o.help = true;
    else if (/^--/.test(a)) throw new Error('unknown option ' + a);
    else if (!o.server) o.server = a;
    else throw new Error('one server address, not two');
  }
  if (!o.server) o.server = 'http://localhost:8082';
  if (o.since && !/^\d{4}-\d\d-\d\d$/.test(o.since)) throw new Error('--since is YYYY-MM-DD');
  if (!(o.minN >= 2)) throw new Error('--min-n is a number, 2 or more');
  if (!(o.gap >= 0)) throw new Error('--gap is milliseconds');
  if (!(o.roadAsks >= 0)) throw new Error('--road-asks is a number');
  [['--streets', o.streets], ['--waits', o.waits], ['--relay', o.relay]].forEach(function (x) {
    if (x[1] && !/^https?:\/\//.test(x[1])) throw new Error(x[0] + ' is an http(s) URL');
  });
  return o;
}

var USAGE = [
  'usage: node tools/places_report.js [http://localhost:8082] [--out ~/places-report]',
  '         [--gps ~/gpslog] [--since YYYY-MM-DD] [--nominatim http://localhost:8088]',
  '         [--cache ~/.cache/uber-scan/places-report-answers.json] [--gap ms] [--min-n 30]',
  '         [--streets URL] [--waits URL] [--relay URL] [--road-asks 5000] [--allow-degraded]',
  '',
  'Run on the NucBox. Reads the copy at home (its /api/journal), places pickups with the',
  'NucBox\'s own Nominatim (directly with --nominatim, else through that server\'s /api/nbx),',
  'and writes index.html and CSVs to --out, which must be outside the repository.',
  'With --gps, also the spells parked with no order in the car (the Busy tab), Drop presses',
  'timed by the GPS, and dead miles after a drop.',
  '--streets: the street index (a relay\'s .../api/nbx, or a server with one loaded); by default',
  'the server\'s relay, else its own index — asked EVEN WITH --nominatim.',
  '--waits: a server whose /api/journal carries the rig\'s store waits (the rig\'s :8080),',
  'used when the main source carries none.',
  '--relay: a server whose /api/nbx relay (search, router, street index) is asked instead of',
  'the journal\'s server\'s: the copy at home may keep the journal and the site and have no',
  'NucBox settings of its own.',
  '--road-asks: road questions the distance band may ask in all (through the relay\'s',
  '/api/nbx/route; cached).',
  '--allow-degraded: write the report even when more than ' + DEGRADED_SHARE * 100 + '% (and more than '
    + DEGRADED_MIN + ') of the',
  'fresh NucBox questions went unanswered; without it such a run writes nothing and exits 1.',
  'Every night: tools/places_nightly.sh (see the README, "Every night, on the NucBox").',
].join('\n');

async function main(argv) {
  var o;
  try { o = parseArgs(argv); } catch (e) {
    console.error(e.message + '\n\n' + USAGE);
    process.exitCode = 2;
    return;
  }
  if (o.help) { console.log(USAGE); return; }
  var outDir = realish(o.out), cacheFile = realish(o.cache);
  if (inside(outDir, fs.realpathSync(ROOT)) || inside(cacheFile, fs.realpathSync(ROOT))) {
    console.error('refused: the report and its cache hold real places and must not be written inside the '
                  + 'repository (' + ROOT + '). Pick --out and --cache outside it.');
    process.exitCode = 2;
    return;
  }
  var sinceMs = null;
  if (o.since) {
    var ymd = o.since.split('-').map(Number);
    sinceMs = new Date(ymd[0], ymd[1] - 1, ymd[2], A.DAY_STARTS_AT).getTime();
  }

  var body;
  try { body = await loadJournal(o.server, sinceMs); } catch (e) {
    console.error('could not read ' + o.server + ': ' + (e && e.message || e));
    process.exitCode = 1;
    return;
  }
  var offers = Array.isArray(body.offers) ? body.offers : [];
  if (body.truncated) {
    console.error('warning: the server sent ' + body.count + ' of ' + body.total
                  + ' offers (its limit, and it did not page: an older server?). Narrow the window with --since.');
  } else if (body.pages > 1) {
    console.log('journal: ' + body.count + ' offers, read in ' + body.pages + ' pages of ' + JOURNAL_PAGE);
  }

  // The relay asked: --relay, else the journal's own server.
  var relay = (o.relay || o.server).replace(/\/+$/, '');
  var settings = { search: false, streets: false, route: false };
  try {
    var s = await getJson(relay + '/api/nbx');
    if (s.ok && s.body) settings = { search: !!s.body.search, streets: !!s.body.streets, route: !!s.body.route };
  } catch (e) { /* an older server: no relay */ }
  var nominatim = o.nominatim || (settings.search ? null : 'http://localhost:8088');
  // The street index EVEN WITH --nominatim (the first real run's 662 corners
  // went unasked): --streets, else the server's relay, else its own index.
  var st = await streetsBase(relay, o.streets);
  var roadSaid = settings.route ? relay + '/api/nbx/route (the relay), at most '
    + o.roadAsks + ' questions' : 'none — ' + relay + ' has no router set (NUCBOX_ROUTER), so no distance band';
  console.log('search: ' + (nominatim ? nominatim + ' (direct)' : relay + '/api/nbx (relay)'));
  console.log('street index: ' + st.said);
  console.log('router: ' + roadSaid);

  var cache = { answers: {}, hits: 0, fresh: 0, asked: 0, unreachable: 0 };
  try {
    var held = JSON.parse(fs.readFileSync(cacheFile, 'utf8'));
    if (held && held.v === 1 && held.answers && typeof held.answers === 'object') cache.answers = held.answers;
  } catch (e) { /* none yet */ }
  function saveCache() {
    fs.mkdirSync(path.dirname(cacheFile), { recursive: true });
    var tmp = cacheFile + '.part';
    fs.writeFileSync(tmp, JSON.stringify({ v: 1, answers: cache.answers }));
    fs.renameSync(tmp, cacheFile);
  }
  var nbx = new MV.NbxSearch({ base: '/api/nbx', gap: o.gap, bandWait: BAND_WAIT_OFFLINE_MS,
    fetch: nbxFetch({ cache: cache, server: relay, nominatim: nominatim, streets: st.base,
                      onFresh: function () { if (cache.fresh % 100 === 0) saveCache(); } }) });
  var region = regionOf(offers.filter(counted));
  console.log('region for cards with no fix: ' + (region ? region.box.s + ',' + region.box.w + ' to ' + region.box.n
              + ',' + region.box.e + ' (the box round ' + region.fixes + ' good card fixes, ' + REGION_MARGIN_MI
              + ' mi wider each way)' : 'none (no good card fix in the record)'));
  var ctx = { region: region, road: settings.route, budget: { left: o.roadAsks } };

  // The GPS log, once: presses timed, drops placed, spells, dead miles.
  var taken = Array.isArray(body.taken) ? body.taken : [];
  var spanTimes = offers.filter(counted).map(seenAt).filter(isFinite);
  var fx = null, presses = null;
  if (o.gps && spanTimes.length) {
    fx = gpsFixes(o.gps, Math.min.apply(null, spanTimes) - 3600e3, Math.max.apply(null, spanTimes) + 3600e3);
    var tp = timePresses(taken, fx.fixes);
    taken = tp.taken;
    presses = tp.stats;
    console.log('presses timed by the GPS: ' + presses.timed + ' of ' + presses.pressed + ' (' + presses.inside
                + ' inside a stop, ' + presses.early + ' early, ' + presses.late + ' late; ' + presses.none + ' no stop, '
                + presses.short + ' at a stop the car had not driven the order to)');
  }

  // Taken trips: the GPS log at the drop, else the dropoff's door.
  var byId = Object.create(null);
  offers.forEach(function (row2) { if (row2 && typeof row2.id === 'string') byId[row2.id] = row2; });
  var atDoor = taken.filter(function (t) { return AT_THE_DOOR.indexOf(t.by || 'drop') >= 0 && byId[t.id]; });
  var gpsPos = Object.create(null);
  if (o.gps && atDoor.length) {
    var g = gpsAt(o.gps, atDoor.map(function (t) { return t.endedAt; }));
    atDoor.forEach(function (t, j) { if (g.at[j]) gpsPos[t.id + '@' + t.endedAt] = { lat: g.at[j][0], lon: g.at[j][1] }; });
    console.error('GPS log: ' + g.files + ' files, ' + g.passed + ' usable fixes, '
                  + Object.keys(gpsPos).length + ' of ' + atDoor.length + ' drops placed by it');
  }
  var dropPins = Object.create(null);
  for (var t = 0; t < atDoor.length; t++) {
    var trip = atDoor[t], key = trip.id + '@' + trip.endedAt;
    if (gpsPos[key]) continue;
    var at = await placeDropoff(nbx, byId[trip.id].dropoff, byId[trip.id], !!st.base, { region: region });
    if (at) dropPins[key] = at;
  }
  saveCache();
  // Where each taken order ended, for the cards read while it was in the car
  // (heldEndsOf, afterFor): the GPS at its drop, else its dropoff placed.
  var heldEnds = await heldEndsOf(nbx, taken, byId, gpsPos, !!st.base, region);
  saveCache();

  // Every pickup the rig stands behind, asked once per (text, card disc box).
  var placed = new Array(offers.length);
  var memo = new Map();
  var todo = 0, done = 0, inCar = 0;
  offers.forEach(function (row) { if (counted(row) && row.pickup) todo += 1; });
  for (var i = 0; i < offers.length; i++) {
    var row = offers[i];
    if (!counted(row) || !row.pickup) continue;
    // ...searched from the ends of the orders in the car when it came up as
    // well (afterFor: the `also` circles the rig gives such a card).
    var after = afterFor(row, heldEnds);
    if (after.length) inCar += 1;
    var card = after.length ? Object.assign({}, row, { after: after }) : row;
    var disc = MV.discFor(card);
    var spec = settings.route ? MV.bandTarget(row, 'pickup') : null;
    // (Its printed door in the key as well: one store's name with two doors
    // is two questions — placeRow asks the door first.)
    var k = (printedDoor(row) || '') + '\u0001' + row.pickup + '\u0000' + (disc ? MV.discBox(disc) + '/' + disc.miles.toFixed(2)
                                          + '/' + disc.at.lat.toFixed(3) + ',' + disc.at.lon.toFixed(3) : '-')
      + (spec ? '/' + spec.miles + (spec.upper ? '+' : '') : '')
      + (after.length ? '/also ' + MV.discBox(disc) + ' ' + after.map(function (e) {
        return e.lat.toFixed(4) + ',' + e.lon.toFixed(4) + '+' + e.widen;
      }).join(';') : '');
    if (!memo.has(k)) memo.set(k, await placeRow(nbx, card, !!st.base, ctx));
    placed[i] = memo.get(k);
    done += 1;
    if (done % 200 === 0) console.error('  pickups ' + done + ' of ' + todo + ' (' + cache.fresh + ' asked, '
                                        + cache.hits + ' from the cache)');
  }
  saveCache();
  console.log('offers read with an order in the car, searched from its end too: ' + inCar);

  // A NucBox down for the run: nothing written, so the nightly keeps the
  // report it has (review, 27 Oct: it used to write one with the offers
  // unplaced and swap it in).
  var down = degraded(cache);
  if (down) {
    var downSaid = down.unreachable + ' of ' + down.asked + ' fresh NucBox questions went unanswered (the search, '
      + 'Nominatim or the relay down?)';
    if (!o.allowDegraded) {
      console.log('NOT WRITTEN: ' + downSaid + '; the report would leave those offers unplaced. '
                  + 'Run again when it answers, or pass --allow-degraded.');
      process.exitCode = 1;
      return;
    }
    console.log('DEGRADED, written anyway (--allow-degraded): ' + downSaid);
  }

  function dropAt(tr) {
    var kk = tr.id + '@' + tr.endedAt;
    if (gpsPos[kk]) return { at: gpsPos[kk], how: 'gps' };
    if (dropPins[kk]) return { at: dropPins[kk], how: 'pin' };
    return cardFixAfter(offers, tr.endedAt);
  }

  // Spells parked with no order in the car, over the record's own span.
  var spells = null, cellTown = Object.create(null);
  if (fx) {
    spells = spellsOf(fx.fixes, heldOf(taken));
    console.error('spells: ' + spells.length + ' parked with no order in the car, off ' + fx.fixes.length
                  + ' fixes (one per ' + SPELL_THIN_S + ' s)');
    if (nominatim || o.nominatim) {
      var seenCells = Object.create(null);
      for (var si = 0; si < spells.length; si++) {
        var sc = cellOf(spells[si]);
        if (!sc || seenCells[sc.id]) continue;
        seenCells[sc.id] = true;
        cellTown[sc.id] = await cellTownOf(fetch, nominatim || o.nominatim, cache, sc);
      }
      saveCache();
    }
  }

  // ...and the towns of the cells the car's own fixes fall in (the Waited
  // tab), named by the same reverse lookup and cache.
  if (nominatim || o.nominatim) {
    var fixCells = Object.create(null);
    for (var fi = 0; fi < offers.length; fi++) {
      var ff = counted(offers[fi]) ? MV.fixOf(offers[fi]) : null;
      var fc = ff ? cellOf(ff) : null;
      if (!fc || fixCells[fc.id] || fc.id in cellTown) continue;
      fixCells[fc.id] = true;
      cellTown[fc.id] = await cellTownOf(fetch, nominatim || o.nominatim, cache, fc);
    }
    saveCache();
  }

  // Store waits: the source's, else the rig's (--waits) when the source has none.
  var waits = Array.isArray(body.waits) ? body.waits : [];
  var waitsFrom = waits.length ? o.server : null;
  if (!waits.length && o.waits) {
    try {
      waits = await loadWaits(o.waits);
      waitsFrom = o.waits;
    } catch (e) { console.error('store waits: ' + (e && e.message || e) + '; none used'); }
  }
  console.log('store waits: ' + waits.length + (waitsFrom ? ' from ' + waitsFrom : ' (none on record)'));

  var earnings = await loadEarnings(o.server);
  console.log('earnings: ' + earnings.length + ' trips read off uploaded screenshots');

  var gold = await loadGold(o.server);

  var report = analyse(offers, taken, placed, dropAt, {
    minN: o.minN, waits: waits, spells: spells, cellTown: cellTown, fixes: fx ? fx.fixes : null,
    earnings: earnings, gold: gold,
    // The order records (server.js orderRecords, since 7 Nov): the Strategy
    // tab's miles where an order left one. An older server sends none.
    records: Array.isArray(body.records) ? body.records : [],
    presses: presses, region: region, streetsSaid: st.said, roadSaid: roadSaid, waitsFrom: waitsFrom,
    source: { server: o.server, count: body.count, total: body.total, pages: body.pages || 1,
              truncated: !!body.truncated, since: o.since } });
  fs.mkdirSync(outDir, { recursive: true });
  fs.writeFileSync(path.join(outDir, 'index.html'), html(report));
  fs.writeFileSync(path.join(outDir, 'places.csv'), csvOf(report, 'place'));
  fs.writeFileSync(path.join(outDir, 'towns.csv'), csvOf(report, 'town'));
  fs.writeFileSync(path.join(outDir, 'grid.csv'), csvOf(report, 'grid'));
  fs.writeFileSync(path.join(outDir, 'dropoff_towns.csv'), dropCsv(report, 'dropTown'));
  fs.writeFileSync(path.join(outDir, 'dropoff_grid.csv'), dropCsv(report, 'dropGrid'));
  fs.writeFileSync(path.join(outDir, 'coverage.csv'), coverageCsv(report));
  fs.writeFileSync(path.join(outDir, 'restaurants.csv'), restCsv(report));
  fs.writeFileSync(path.join(outDir, 'restaurant_branches.csv'), restBranchCsv(report));
  fs.writeFileSync(path.join(outDir, 'top_share_tests.csv'), shareCsv(report));
  fs.writeFileSync(path.join(outDir, 'coverage_levels.csv'), levelsCsv(report));
  fs.writeFileSync(path.join(outDir, 'strategy_curve.csv'), strategyCsv(report));
  Object.keys(MORE_CSVS).forEach(function (name) {
    fs.writeFileSync(path.join(outDir, name), tableCsv(report, MORE_CSVS[name][0], MORE_CSVS[name][1]));
  });
  console.log(summary(report));
  console.log('\nWritten: ' + path.join(outDir, 'index.html') + ' (and ' + (11 + Object.keys(MORE_CSVS).length)
              + ' CSVs beside it)');
  console.log('NucBox questions: ' + cache.fresh + ' asked, ' + cache.hits + ' answered from ' + cacheFile);
}

module.exports = {
  waitingLine: waitingLine, waitedTable: waitedTable, nextOffer: nextOffer, cardFixAfter: cardFixAfter,
  emptyOf: emptyOf, emptyTable: emptyTable, fixDensity: fixDensity, goodOf: goodOf,
  CREDIT_MAX_MIN: CREDIT_MAX_MIN, MOVED_MI: MOVED_MI, CARD_FIX_AFTER_MIN: CARD_FIX_AFTER_MIN,
  MIN_N: MIN_N, DROP_MIN_N: DROP_MIN_N, GRID_MI: GRID_MI, NEXT_GAP_MIN: NEXT_GAP_MIN, VIEWS: VIEWS,
  pickupKind: pickupKind, placePickup: placePickup, placeDropoff: placeDropoff, storeLabel: storeLabel,
  printedDoor: printedDoor, placeRow: placeRow, heldEndsOf: heldEndsOf, afterFor: afterFor,
  AFTER_GPS_WIDEN_MI: AFTER_GPS_WIDEN_MI,
  placesOf: placesOf, cellOf: cellOf, bootCI: bootCI, cells: cells, coverage: coverage,
  nextTake: nextTake, timelineOf: timelineOf, tripsOf: tripsOf, dropTable: dropTable,
  analyse: analyse, summary: summary, testLine: testLine, html: html, csvOf: csvOf, dropCsv: dropCsv,
  paidSection: paidSection, loadEarnings: loadEarnings,
  coverageCsv: coverageCsv, restCsv: restCsv, restBranchCsv: restBranchCsv, nameOf: nameOf,
  restaurantNames: restaurantNames, restaurantsTable: restaurantsTable, waitOf: waitOf, hitsOf: hitsOf, nbxFetch: nbxFetch,
  degraded: degraded, DEGRADED_SHARE: DEGRADED_SHARE, DEGRADED_MIN: DEGRADED_MIN, gpsAt: gpsAt, parseArgs: parseArgs,
  DESC_MIN_N: DESC_MIN_N, REAL_MED_N: REAL_MED_N, QUIET_DAYS: QUIET_DAYS, SPELL_M: SPELL_M,
  SPELL_MIN_S: SPELL_MIN_S, SPELL_GAP_S: SPELL_GAP_S, SPELL_MIN_N: SPELL_MIN_N, REAL_BY: REAL_BY, FINISHED: FINISHED,
  EARLY_LOOK: EARLY_LOOK, MULTI_ORDER: MULTI_ORDER, MANY_DROPOFFS: MANY_DROPOFFS, MORE_CSVS: MORE_CSVS,
  payPerMile: payPerMile, appOf: appOf, flagsOf: flagsOf, wilson: wilson, poissonLE: poissonLE,
  isoWeek: isoWeek, runsOf: runsOf, realOf: realOf, takesTable: takesTable, waitsTable: waitsTable,
  strandTable: strandTable, busyTable: busyTable, appsTable: appsTable, ppmTable: ppmTable,
  stackTable: stackTable, quietTable: quietTable, trendTable: trendTable, spellsOf: spellsOf,
  heldOf: heldOf, gpsFixes: gpsFixes, cellTownOf: cellTownOf, tableCsv: tableCsv,
  inside: inside, realish: realish, outingOf: outingOf, main: main,
  printedTown: printedTown, regionOf: regionOf, wordsOf: wordsOf, WHY: WHY, isPoint: isPoint, gridOk: gridOk, PLACE_APPROX_MI: PLACE_APPROX_MI,
  REGION_MARGIN_MI: REGION_MARGIN_MI, quantile: quantile, qOf: qOf, tiersOf: tiersOf, topOf: topOf, timePresses: timePresses,
  stillRuns: stillRuns, shareTest: shareTest, goodTable: goodTable, waitTable: waitTable, deadOf: deadOf,
  deadTable: deadTable, sizeTable: sizeTable, bestLines: bestLines, targetLine: targetLine,
  targetAreaLines: targetAreaLines, shareCsv: shareCsv, levelsCsv: levelsCsv,
  strategyOrders: strategyOrders, recordFor: recordFor, milesBetween: milesBetween, strategyCsv: strategyCsv,
  RECORD_MATCH_MS: RECORD_MATCH_MS,
  streetsBase: streetsBase, loadWaits: loadWaits, GPS_TIMED: GPS_TIMED, TIER_MIN_N: TIER_MIN_N,
  STOP_M: STOP_M, STOP_MIN_S: STOP_MIN_S, PRESS_AFTER_MIN: PRESS_AFTER_MIN, PRESS_BEFORE_MIN: PRESS_BEFORE_MIN,
  SHORT_MILES: SHORT_MILES,
  DEAD_MAX_MIN: DEAD_MAX_MIN, SIZE_BANDS: SIZE_BANDS, TAKE_SLACK_MS: TAKE_SLACK_MS,
  GROUPS: GROUPS, TABS: TABS, blockChart: blockChart, fold: fold,
  bootCIPlain: bootCIPlain, loadJournal: loadJournal, JOURNAL_PAGE: JOURNAL_PAGE,
  whenWhere: whenWhere, reportRulers: reportRulers, wwSlotOf: wwSlotOf, poissonCI: poissonCI, WW_BLOCKS: WW_BLOCKS, WW_TOPS: WW_TOPS,
  aroundYou: aroundYou, homeOf: homeOf, glanceOf: glanceOf, glanceSection: glanceSection, gridCell: gridCell, HOME_MI: HOME_MI, AROUND_BIN_MI: AROUND_BIN_MI,
  AROUND_BIN_DAYS: AROUND_BIN_DAYS, AROUND_RINGS: AROUND_RINGS, PICKUP_BANDS: PICKUP_BANDS,
  WW_TOP: WW_TOP, WW_MIN_HOURS: WW_MIN_HOURS, WW_MIN_DAYS: WW_MIN_DAYS, WW_CONF: WW_CONF,
};

if (require.main === module) main(process.argv.slice(2));
