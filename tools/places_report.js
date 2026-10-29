/* Where the good offers start, measured on the NucBox after the fact.
 *
 *   node tools/places_report.js http://localhost:8081 --out ~/places-report
 *   node tools/places_report.js http://localhost:8081 --out ~/places-report \
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
function bootCI(values, seed, reps, stat) {
  if (!values || values.length < 2) return null;
  reps = reps || BOOTS;
  stat = stat || MV.median;
  var r = rng(seed), n = values.length, meds = new Array(reps), buf = new Array(n);
  for (var k = 0; k < reps; k++) {
    for (var i = 0; i < n; i++) buf[i] = values[Math.floor(r() * n)];
    meds[k] = stat(buf);
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
function cellOf(at) {
  if (!at || !isFinite(at.lat) || !isFinite(at.lon)) return null;
  var dLat = GRID_MI / 69.0;
  var i = Math.floor(at.lat / dLat);
  var mid = (i + 0.5) * dLat;
  var dLon = GRID_MI / (69.0 * Math.max(0.2, Math.cos(mid * Math.PI / 180)));
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
  noplace: 'not found inside the card\'s reach',
  none: 'not found inside the card\'s reach',
  nodoor: 'not found inside the card\'s reach',
  together: 'not found inside the card\'s reach',
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
    } else res = await nbx.place(text, disc, { streets: !!streets });
  } catch (e) {
    return { at: null, why: 'refused', kind: k.kind };
  }
  if (res && res.at) {
    if (region && !townAt(res, res.at, region)) return { at: null, why: 'regiontown', kind: k.kind };
    return placedAt(res.at, k.kind, k.kind === 'name' ? 'name' : k.kind === 'cross' ? 'corner' : 'door', 0,
                    region ? { region: true } : null);
  }
  var why = res && res.why;
  why = WHY[why] ? why : 'none';
  if (region || k.kind !== 'door') return { at: null, why: why, kind: k.kind };
  // The door refused: the band first (it narrows; an area it found is tighter
  // than the one it was chosen from), else the area beside the refusal.
  if (ctx.road) {
    var spec = MV.bandTarget(card, 'pickup');
    var band = spec ? await nbx.band(text, res, disc, spec, null, ctx.budget || null, !!streets) : null;
    if (band) return placedAt(band, k.kind, 'band', band.miles, { refused: why, cardMi: band.cardMi });
  }
  if (res && res.area) {
    return placedAt(res.area, k.kind, res.area.rough ? 'street' : 'area', res.area.miles, { refused: why });
  }
  return { at: null, why: why, kind: k.kind };
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
      if (r.refused) e.refused[WHY[r.refused] || r.refused] = (e.refused[WHY[r.refused] || r.refused] || 0) + 1;
      if (r.region) e.region += 1;
      return;
    }
    var w = WHY[r.why] || r.why;
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

// P(X <= x) for X ~ Poisson(lam).
function poissonLE(x, lam) {
  var term = Math.exp(-lam), sum = term;
  for (var k = 1; k <= x; k++) { term *= lam / k; sum += term; }
  return Math.min(1, sum);
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
    return { name: label, n: list.length, pay: med(pays), perHour: med(list.map(function (o) { return o.perHour; })),
             wait: w ? w.medianMin : null, waitN: w ? w.n : null, why: why };
  }).filter(function (r) { return r.wait !== null || r.n >= DESC_MIN_N; })
    .sort(function (a, b) { return (b.wait === null ? -1 : b.wait) - (a.wait === null ? -1 : a.wait) || b.n - a.n; });
  return { cols: [C('name', 'place', 't'), C('n', 'offers', 'n'), C('pay', 'median pay', '$'),
                  C('perHour', 'median $/hr', '$'), C('wait', 'median wait', 'min'), C('waitN', 'waits', 'n'),
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
function qOf(q) {
  return function (xs) {
    var h = (xs.length - 1) * q, lo = Math.floor(h), a = selectK(xs, lo);
    if (h === lo) return a;
    var b = Infinity;
    for (var i = lo + 1; i < xs.length; i++) if (xs[i] < b) b = xs[i];
    return a + (h - lo) * (b - a);
  };
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

/* --- the whole analysis, given placements --------------------------------
 *
 * `placed[i]` is offers[i]'s pickup answer { at, why, kind } (or undefined
 * for a row not asked about), `dropAt(t, o)` a taken trip's position or null. */
var VIEWS = ['all', 0, 1, 2, 3, 4, 5, 6, 7];

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
    },
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
  var data = JSON.stringify(r).replace(/</g, '\\u003c');
  var span = r.span ? new Date(r.span[0]).toISOString().slice(0, 10) + ' to '
    + new Date(r.span[1]).toISOString().slice(0, 10) : 'no offers';
  return '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
    + '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    + '<title>Where Offers Start</title>\n'
    + '<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">\n'
    + '<style>\n' + PAGE_CSS + '\n</style>\n</head>\n<body>\n<main>\n'
    + '<h1>Where the good offers start</h1>\n'
    + '<p class="sub">' + esc(span) + ' · ' + r.coverage.offers + ' offers the rig stands behind, '
    + r.outings + ' shift days · made ' + esc(new Date(r.made).toISOString().slice(0, 16).replace('T', ' '))
    + ' UTC on the NucBox · offline report, nothing on the rig reads it</p>\n'
    + '<section class="banner">' + banner(r) + '</section>\n'
    + '<div class="bar"><label>Hours <select id="when"></select></label>'
    + '<span id="whenNote" class="note"></span></div>\n'
    + '<nav class="tabs" id="tabs">' + TABS.map(function (t) {
      return '<button type="button" data-tab="' + t[0] + '">' + esc(t[1]) + '</button>';
    }).join('') + '</nav>\n'
    + BEST_SECTION(r)
    + '<section data-tab="places"><h2>Places — a store at a location</h2><p class="note">A place is a pin at door, '
    + 'corner or name level, or an approximate placement where it is that store\'s: within ' + PLACE_SAME_MI
    + ' mi of a door or name pin of the same store, or its own candidates no more than ' + r.best.placeApproxMi
    + ' mi apart (see Coverage for every level). <b>P75 / P90</b> are the 75th and 90th percentiles of the '
    + 'place\'s $/hr; <b>top 10%</b> is the share of its offers at or over the 90th percentile of every offer in '
    + 'their own three hours. Click a heading to sort.</p><p class="note" id="placeTest"></p>'
    + '<div id="placePlot" class="plot"></div><div id="placeTable"></div><div id="placeThin" class="thin"></div></section>\n'
    + '<section data-tab="restaurants"><h2>Restaurants — by the name on the card, placed or not</h2>'
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
    + '<p class="note" id="restTest"></p><div id="restPlot" class="plot"></div><div id="restTable"></div>'
    + '<div id="restThin"></div></section>\n'
    + '<section data-tab="map"><h2>Map</h2><p class="note">One dot per place, sized by its offers. Coloured only where it '
    + 'beats chance: <span class="k up">●</span> pays more than the same hours elsewhere, '
    + '<span class="k down">●</span> less; <span class="k grey">●</span> not distinguishable from the rest; '
    + 'small hollow dots are too few to rank. Squares are the ' + r.gridMi + '-mile grid, by the same rule.</p>'
    + '<div id="map"></div></section>\n'
    + '<section data-tab="towns"><h2>Towns — the card\'s own town</h2><p class="note">The town the card printed, dropoff first and '
    + 'then pickup, the rule the rig\'s map ranks towns by (map-view.js townFor). No geocoder.</p>'
    + '<p class="note" id="townTest"></p><div id="townPlot" class="plot"></div><div id="townTable"></div>'
    + '<div id="townThin" class="thin"></div></section>\n'
    + '<section data-tab="grid"><h2>' + r.gridMi + '-mile grid — by the pickup\'s pin</h2><p class="note">Every '
    + 'placement level, an approximate one only where its candidates lie within ' + r.best.areaMi + ' mi of each '
    + 'other (the rig\'s general area, half a cell).</p><p class="note" id="gridTest"></p>'
    + '<div id="gridPlot" class="plot"></div><div id="gridTable"></div><div id="gridThin" class="thin"></div></section>\n'
    + '<section data-tab="after"><h2>Where trips leave you</h2><p class="note">For each order you took and put down at the door: '
    + 'how long until the next offer the rig said <b>take</b>, and what it paid. Placed by the GPS log at the drop '
    + '(' + r.trips.gps + ' trips) or the dropoff\'s door inside its card\'s reach (' + r.trips.pin + '); the town '
    + 'off the card for the town table (' + r.trips.town + '). A silence longer than ' + r.nextGapMin
    + ' minutes before one came is you stopping, counted as "ended", not as a long wait. Counted by area only: '
    + 'no dropoff is named, and a grid cell with fewer than ' + r.dropMinN + ' trips is not shown at all. '
    + r.trips.n + ' trips in all.</p>'
    + '<p class="note" id="dropTest"></p><div id="dropTown"></div><div id="dropGrid"></div></section>\n'
    + MORE_SECTIONS(r)
    + '<section data-tab="coverage"><h2>Coverage, shift day by shift day</h2><p class="note">Pickups placed and not, and what each paid. '
    + 'A gap that keeps the same sign day after day is a bias in what the map can show, not a fact about places.</p>'
    + '<h3>Placed, by level</h3><p class="note">door, corner and name are a point; band, area and street are '
    + 'approximate (an area, with its spread). "Stood in for" is the refusal an approximate placement was found '
    + 'beside. Street index: ' + esc(r.best.streets || 'none') + '. Router (for the band): '
    + esc(r.best.road || 'none') + '.</p><div id="levels"></div>'
    + '<div id="coverage"></div></section>\n'
    + '<section data-tab="method" class="method"><h2>How this was measured</h2>' + METHOD(r) + '</section>\n'
    + '</main>\n<div id="tip" hidden></div>\n'
    + '<script type="application/json" id="data">' + data + '</script>\n'
    + '<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>\n'
    + '<script>\n' + PAGE_JS + '\n</script>\n</body>\n</html>\n';
}

// The page's tabs, in order: [id, label].
var TABS = [['best', 'Best offers'], ['places', 'Places'], ['restaurants', 'Restaurants'], ['map', 'Map'], ['towns', 'Towns'], ['grid', 'Grid'],
            ['after', 'After a drop'], ['takes', 'Your takes'], ['apps', 'Uber vs DoorDash'],
            ['ppm', '$/mi'], ['waits', 'Store waits'], ['strand', 'Strand risk'], ['busy', 'Busy'],
            ['stack', 'Add-ons'], ['quiet', 'Gone quiet'], ['trend', 'Trend'], ['coverage', 'Coverage'],
            ['method', 'Method']];

var EXPERIMENTAL = '<p class="exp">Experimental, descriptive: counts, medians and intervals. Nothing in this tab '
  + 'is ranked by a test or coloured, and none of it is a rule.</p>';

function MORE_SECTIONS(r) {
  function sec(id, title, note, divs) {
    return '<section data-tab="' + id + '"><h2>' + title + '</h2>' + EXPERIMENTAL + '<p class="note">' + note + '</p>'
      + divs.map(function (d) { return '<h3>' + esc(d[1]) + '</h3><div id="m-' + d[0] + '"></div>'; }).join('')
      + '</section>\n';
  }
  var tk = r.takes;
  return sec('takes', 'Your takes, and what they really paid',
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
          'The rig\'s measured waits at a store (server.js storeWaitsOut: name, how many, the median minutes; '
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
}

/* The Best offers tab: plain lines first, then where good offers turn up
 * per hour of waiting and what working an area paid, then the share tests,
 * then the descriptive tables. */
function BEST_SECTION(r) {
  function tbl(id, title) { return '<h3>' + esc(title) + '</h3><div id="b-' + id + '"></div>'; }
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
    + '<div id="shareTests"></div>'
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
  'border-radius:6px;padding:6px 8px;font-size:12px;max-width:300px;z-index:1000;box-shadow:0 2px 8px rgba(0,0,0,.2)}',
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
        + '</td><td>' + m(g.nextPerHour) + '</td><td>' + m(g.nextPay) + '</td><td>' + tag(g, true) + '</td></tr>';
    }).join('');
    var thin = what === 'cell'
      ? (c.thinCount ? '<p class="thin">' + c.thinCount + ' more cells (' + c.thinTrips
         + ' trips) have too few to show, and are not named.</p>' : '')
      : (c.thin.length ? '<p class="thin"><b>Too few</b> (under ' + c.floor + ' measured waits): '
         + c.thin.map(function (t) { return esc(t.name) + ' (' + t.n + ')'; }).join(', ') + '.</p>' : '');
    el.innerHTML = '<h3>' + (what === 'cell' ? 'By ' + R.gridMi + '-mile cell' : 'By town') + '</h3>'
      + (c.groups.length ? '<div class="tw"><table><thead><tr><th>' + (what === 'cell' ? 'cell' : 'town')
        + '</th><th>trips</th><th>measured</th><th>ended</th><th>median wait</th><th>95%</th><th>vs same hours</th>'
        + '<th>next take $/hr</th><th>next take pay</th><th></th></tr></thead><tbody>' + rows
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
    var wait = g.wait !== null && g.wait !== undefined ? g.wait.toFixed(1) + ' min (' + g.waitN + ')'
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

  // Tabs: one section at a time, the pick kept in the address.
  var tabs = document.getElementById('tabs');
  var current = null;
  function showTab(id) {
    var known = Array.prototype.some.call(tabs.children, function (b) { return b.getAttribute('data-tab') === id; });
    if (!known) id = 'best';
    current = id;
    Array.prototype.forEach.call(tabs.children, function (b) {
      b.setAttribute('aria-pressed', b.getAttribute('data-tab') === id ? 'true' : 'false');
    });
    Array.prototype.forEach.call(document.querySelectorAll('section[data-tab]'), function (sec) {
      sec.hidden = sec.getAttribute('data-tab') !== id;
    });
    if (id === 'map') {
      drawMap(R.views[sel.value]);
      if (map) map.invalidateSize();
    }
  }
  tabs.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('button[data-tab]');
    if (!b) return;
    showTab(b.getAttribute('data-tab'));
    try { history.replaceState(null, '', '#' + b.getAttribute('data-tab')); } catch (err) { /* a file: page */ }
  });

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
    document.getElementById('restTest').innerHTML = testText(v.rest, 'restaurants');
    dotPlot(document.getElementById('restPlot'), v.rest, 'rest', '$', false);
    restTable(v.rest);
    document.getElementById('dropTest').innerHTML = testText(v.dropTown, 'wait by town');
    dropTable(document.getElementById('dropTown'), v.dropTown, 'town');
    dropTable(document.getElementById('dropGrid'), v.dropGrid, 'cell');
    drawMore(v);
    markSortable();
    if (current === 'map') drawMap(v);
  }
  sel.addEventListener('change', draw);
  coverageTable();
  levelsTable();
  shareTests();
  draw();
  showTab((location.hash || '').slice(1) || 'best');
}).replace(/^function page\(\) \{/, '(function () {').replace(/\}$/, '}());');

/* --- talking to the server, the NucBox and the GPS log -------------------- */

async function getJson(u) {
  var res = await fetch(u, { headers: { Accept: 'application/json' } });
  var body = null;
  try { body = await res.json(); } catch (e) { body = null; }
  return { ok: res.ok, status: res.status, body: body };
}

async function loadJournal(base, sinceMs) {
  var u = base.replace(/\/+$/, '') + '/api/journal?days=3650&limit=20000'
    + (sinceMs ? '&since=' + sinceMs : '');
  var got = await getJson(u);
  if (!got.ok || !got.body) throw new Error(u + ' answered ' + got.status);
  if (got.body.unreadable) throw new Error('the server could not read its journal (' + got.body.unreadable + ')');
  return got.body;
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
  if (!o.server) o.server = 'http://localhost:8081';
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
  'usage: node tools/places_report.js [http://localhost:8081] [--out ~/places-report]',
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
                  + ' offers (its limit). Narrow the window with --since.');
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

  // Every pickup the rig stands behind, asked once per (text, card disc box).
  var placed = new Array(offers.length);
  var memo = new Map();
  var todo = 0, done = 0;
  offers.forEach(function (row) { if (counted(row) && row.pickup) todo += 1; });
  for (var i = 0; i < offers.length; i++) {
    var row = offers[i];
    if (!counted(row) || !row.pickup) continue;
    var disc = MV.discFor(row);
    var spec = settings.route ? MV.bandTarget(row, 'pickup') : null;
    var k = row.pickup + '\u0000' + (disc ? MV.discBox(disc) + '/' + disc.miles.toFixed(2)
                                          + '/' + disc.at.lat.toFixed(3) + ',' + disc.at.lon.toFixed(3) : '-')
      + (spec ? '/' + spec.miles + (spec.upper ? '+' : '') : '');
    if (!memo.has(k)) memo.set(k, await placePickup(nbx, row.pickup, row, !!st.base, ctx));
    placed[i] = memo.get(k);
    done += 1;
    if (done % 200 === 0) console.error('  pickups ' + done + ' of ' + todo + ' (' + cache.fresh + ' asked, '
                                        + cache.hits + ' from the cache)');
  }
  saveCache();

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
    return null;
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

  var report = analyse(offers, taken, placed, dropAt, {
    minN: o.minN, waits: waits, spells: spells, cellTown: cellTown, fixes: fx ? fx.fixes : null,
    presses: presses, region: region, streetsSaid: st.said, roadSaid: roadSaid, waitsFrom: waitsFrom,
    source: { server: o.server, count: body.count, total: body.total,
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
  Object.keys(MORE_CSVS).forEach(function (name) {
    fs.writeFileSync(path.join(outDir, name), tableCsv(report, MORE_CSVS[name][0], MORE_CSVS[name][1]));
  });
  console.log(summary(report));
  console.log('\nWritten: ' + path.join(outDir, 'index.html') + ' (and ' + (10 + Object.keys(MORE_CSVS).length)
              + ' CSVs beside it)');
  console.log('NucBox questions: ' + cache.fresh + ' asked, ' + cache.hits + ' answered from ' + cacheFile);
}

module.exports = {
  MIN_N: MIN_N, DROP_MIN_N: DROP_MIN_N, GRID_MI: GRID_MI, NEXT_GAP_MIN: NEXT_GAP_MIN, VIEWS: VIEWS,
  pickupKind: pickupKind, placePickup: placePickup, placeDropoff: placeDropoff, storeLabel: storeLabel,
  placesOf: placesOf, cellOf: cellOf, bootCI: bootCI, cells: cells, coverage: coverage,
  nextTake: nextTake, timelineOf: timelineOf, tripsOf: tripsOf, dropTable: dropTable,
  analyse: analyse, summary: summary, testLine: testLine, html: html, csvOf: csvOf, dropCsv: dropCsv,
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
  printedTown: printedTown, regionOf: regionOf, isPoint: isPoint, gridOk: gridOk, PLACE_APPROX_MI: PLACE_APPROX_MI,
  REGION_MARGIN_MI: REGION_MARGIN_MI, quantile: quantile, qOf: qOf, tiersOf: tiersOf, topOf: topOf, timePresses: timePresses,
  stillRuns: stillRuns, shareTest: shareTest, goodTable: goodTable, waitTable: waitTable, deadOf: deadOf,
  deadTable: deadTable, sizeTable: sizeTable, bestLines: bestLines, shareCsv: shareCsv, levelsCsv: levelsCsv,
  streetsBase: streetsBase, loadWaits: loadWaits, GPS_TIMED: GPS_TIMED, TIER_MIN_N: TIER_MIN_N,
  STOP_M: STOP_M, STOP_MIN_S: STOP_MIN_S, PRESS_AFTER_MIN: PRESS_AFTER_MIN, PRESS_BEFORE_MIN: PRESS_BEFORE_MIN,
  SHORT_MILES: SHORT_MILES,
  DEAD_MAX_MIN: DEAD_MAX_MIN, SIZE_BANDS: SIZE_BANDS, TAKE_SLACK_MS: TAKE_SLACK_MS,
};

if (require.main === module) main(process.argv.slice(2));
