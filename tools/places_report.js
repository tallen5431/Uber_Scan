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
 */

'use strict';

var fs = require('fs');
var os = require('os');
var path = require('path');
var cp = require('child_process');

var A = require('../advice.js');
var MV = require('../map-view.js');
var AS = require('../assemble.js');

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
var AT_THE_DOOR = ['gps', 'screen', 'drop', 'chooser'];

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

/* A percentile bootstrap interval for the median, 95%, or null under two. */
function bootCI(values, seed, reps) {
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

/* One pickup, placed or refused: { at, why, kind }. `nbx` is an NbxSearch.
 * The door is asked as the server asks a held order's pickup door; the name
 * as it asks the store by its name (searchHeldPickupName: one question, the
 * name as searchPlan writes it, chosen by MV.pickPlace). Only a pin counts:
 * a "general area" beside a refusal is a refusal here. */
async function placePickup(nbx, text, card, streets) {
  var k = pickupKind(text);
  if (k.kind === 'none') return { at: null, why: 'notext', kind: k.kind };
  if (k.kind === 'street') return { at: null, why: 'street', kind: k.kind };
  if (k.kind === 'cross' && !streets) return { at: null, why: 'cross', kind: k.kind };
  var disc = MV.discFor(card || null);
  if (!disc) return { at: null, why: 'nofix', kind: k.kind };
  var res = k.kind === 'name'
    ? await nbx.placeSearch(k.plan.q, disc)
    : await nbx.place(text, disc, { streets: !!streets });
  if (res && res.at) return { at: { lat: res.at.lat, lon: res.at.lon }, why: null, kind: k.kind };
  var why = res && res.why;
  return { at: null, why: WHY[why] ? why : 'none', kind: k.kind };
}

/* A taken order's dropoff, placed to be COUNTED by area and nothing else: a
 * door or (with the street index) a corner, inside its card's disc. */
async function placeDropoff(nbx, text, card, streets) {
  var k = pickupKind(text);
  if (k.kind !== 'door' && !(k.kind === 'cross' && streets)) return null;
  var disc = MV.discFor(card || null);
  if (!disc) return null;
  var res = await nbx.place(text, disc, { streets: !!streets });
  return res && res.at ? { lat: res.at.lat, lon: res.at.lon } : null;
}

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
  placed.forEach(function (p) {
    var key = AS.storeKey(p.label) || p.label.toLowerCase();
    var list = byKey[key] || (byKey[key] = []);
    var hit = null;
    for (var i = 0; i < list.length; i++) {
      if (MV.crowMiles(list[i].first, p.at) <= PLACE_SAME_MI) { hit = list[i]; break; }
    }
    if (!hit) {
      hit = { id: key + '#' + (list.length + 1), first: p.at, pins: [], labels: {} };
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
      clear: clear,
      beats: !!(significant && clear),
      matched: g.matched === undefined ? null : g.matched,
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
  var why = Object.create(null), kinds = Object.create(null);
  withPickup.forEach(function (o) {
    var r = placedRow(o);
    kinds[r.kind] = kinds[r.kind] || { n: 0, placed: 0 };
    kinds[r.kind].n += 1;
    if (r.at) { kinds[r.kind].placed += 1; return; }
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
    return { at: seenAt(o), go: counted(o) && o.state === 'go', perHour: o.perHour, pay: o.pay };
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
               cellBox: cell, how: pos ? pos.how : null, next: nextTake(line, t.endedAt) });
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
    if (r && r.at) pins.push({ row: i, at: r.at, label: storeLabel(o.pickup) });
  });
  var grouped = placesOf(pins);
  var cellBoxes = Object.create(null);
  function placeKey(o) { return grouped.byRow[idx.get(o)] || null; }
  function cellKey(o) {
    var r = answer(o);
    var c = r.at ? cellOf(r.at) : null;
    if (c) cellBoxes[c.id] = c;
    return c ? c.id : null;
  }
  function townKey(o) { return MV.townFor(o, A.area); }

  var trips = tripsOf(offers, taken, dropAt);
  var views = {};
  VIEWS.forEach(function (v) {
    var rows = v === 'all' ? offers : offers.filter(function (o) { return A.blockOf(o.at) === v; });
    var tv = v === 'all' ? trips : trips.filter(function (t) { return A.blockOf(t.at) === v; });
    var hold = v === 'all';
    views[v] = {
      name: v === 'all' ? 'all hours' : A.BLOCK_NAMES[v],
      offers: rows.filter(counted).length,
      place: cells(rows, placeKey, { hold: hold, minN: opts.minN }),
      town: cells(rows, townKey, { hold: hold, minN: opts.minN }),
      grid: cells(rows, cellKey, { hold: hold, minN: opts.minN }),
      dropTown: dropTable(tv, 'town', hold),
      dropGrid: dropTable(tv, 'cell', hold),
    };
  });
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
    places: grouped.places,
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
  cv.why.forEach(function (w) { out.push('  unplaced, ' + w.why + ': ' + w.n); });
  if (cv.all.gapPerHour !== null) {
    out.push('Placed pay $' + cv.all.placed.perHour.toFixed(2) + '/hr, unplaced $'
             + cv.all.unplaced.perHour.toFixed(2) + '/hr: the map leaves out offers paying '
             + (cv.all.gapPerHour >= 0 ? '$' + cv.all.gapPerHour.toFixed(2) + '/hr less'
                : '$' + (-cv.all.gapPerHour).toFixed(2) + '/hr more')
             + ' (' + pText(cv.all.p) + ')');
  }
  out.push(testLine('Places', all.place));
  out.push(testLine('Towns', all.town));
  out.push(testLine(r.gridMi + '-mile grid', all.grid));
  out.push(testLine('Wait after a drop, by town', all.dropTown));
  ['place', 'town', 'grid'].forEach(function (k) {
    var beat = all[k].groups.filter(function (g) { return g.beats; });
    if (!beat.length) return;
    out.push('Clear of the rest (' + k + '):');
    beat.forEach(function (g) {
      out.push('  ' + labelOf(r, k, g.name) + '  ' + (g.score >= 0 ? '+' : '') + g.score.toFixed(2)
               + ' $/hr vs same hours elsewhere [' + g.sci[0].toFixed(2) + ', ' + g.sci[1].toFixed(2)
               + '], n=' + g.n);
    });
  });
  return out.join('\n');
}

function pct(n, of) { return of ? (Math.round(n / of * 1000) / 10).toFixed(1) + '%' : 'n/a'; }

function labelOf(r, kind, name) {
  if (kind === 'place') return (r.places[name] && r.places[name].label) || name;
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
              'grouping_p', 'ranked'];
  var lines = [head.join(',')];
  VIEWS.forEach(function (v) {
    var c = r.views[v][kind];
    c.groups.forEach(function (g) {
      var at = kind === 'place' ? r.places[g.name] : kind === 'grid' ? r.cells[g.name] : null;
      lines.push([r.views[v].name, labelOf(r, kind, g.name), at && at.lat, at && at.lon, g.n,
                  g.outings, g.median, g.ci && g.ci[0], g.ci && g.ci[1], g.score,
                  g.sci && g.sci[0], g.sci && g.sci[1], g.pay, g.take, g.clear,
                  g.beats ? 'yes' : 'no', c.p, 'yes'].map(csvCell).join(','));
    });
    c.thin.forEach(function (t) {
      var at = kind === 'place' ? r.places[t.name] : kind === 'grid' ? r.cells[t.name] : null;
      lines.push([r.views[v].name, labelOf(r, kind, t.name), at && at.lat, at && at.lon, t.n,
                  t.outings, '', '', '', '', '', '', '', '', '', 'too few', c.p, 'no']
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
                  + '-paying slice than your whole record. The town table does not need a pin and is not cut this way.'));
  lines.push('<b>Significance:</b> ' + esc(testLine('places', all.place)) + ' '
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
    + '<section><h2>Places — a store at a location</h2><p class="note" id="placeTest"></p>'
    + '<div id="placePlot" class="plot"></div><div id="placeTable"></div><div id="placeThin" class="thin"></div></section>\n'
    + '<section><h2>Map</h2><p class="note">One dot per place, sized by its offers. Coloured only where it '
    + 'beats chance: <span class="k up">●</span> pays more than the same hours elsewhere, '
    + '<span class="k down">●</span> less; <span class="k grey">●</span> not distinguishable from the rest; '
    + 'small hollow dots are too few to rank. Squares are the ' + r.gridMi + '-mile grid, by the same rule.</p>'
    + '<div id="map"></div></section>\n'
    + '<section><h2>Towns — the card\'s own town</h2><p class="note">The town the card printed, dropoff first and '
    + 'then pickup, the rule the rig\'s map ranks towns by (map-view.js townFor). No geocoder.</p>'
    + '<p class="note" id="townTest"></p><div id="townPlot" class="plot"></div><div id="townTable"></div>'
    + '<div id="townThin" class="thin"></div></section>\n'
    + '<section><h2>' + r.gridMi + '-mile grid — by the pickup\'s pin</h2><p class="note" id="gridTest"></p>'
    + '<div id="gridPlot" class="plot"></div><div id="gridTable"></div><div id="gridThin" class="thin"></div></section>\n'
    + '<section><h2>Where trips leave you</h2><p class="note">For each order you took and put down at the door: '
    + 'how long until the next offer the rig said <b>take</b>, and what it paid. Placed by the GPS log at the drop '
    + '(' + r.trips.gps + ' trips) or the dropoff\'s door inside its card\'s reach (' + r.trips.pin + '); the town '
    + 'off the card for the town table (' + r.trips.town + '). A silence longer than ' + r.nextGapMin
    + ' minutes before one came is you stopping, counted as "ended", not as a long wait. Counted by area only: '
    + 'no dropoff is named, and a grid cell with fewer than ' + r.dropMinN + ' trips is not shown at all. '
    + r.trips.n + ' trips in all.</p>'
    + '<p class="note" id="dropTest"></p><div id="dropTown"></div><div id="dropGrid"></div></section>\n'
    + '<section><h2>Coverage, shift day by shift day</h2><p class="note">Pickups placed and not, and what each paid. '
    + 'A gap that keeps the same sign day after day is a bias in what the map can show, not a fact about places.</p>'
    + '<div id="coverage"></div></section>\n'
    + '<section class="method"><h2>How this was measured</h2>' + METHOD(r) + '</section>\n'
    + '</main>\n<div id="tip" hidden></div>\n'
    + '<script type="application/json" id="data">' + data + '</script>\n'
    + '<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>\n'
    + '<script>\n' + PAGE_JS + '\n</script>\n</body>\n</html>\n';
}

function METHOD(r) {
  return '<ul>'
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
        + '</td><td>' + m(g.pay) + '</td><td>' + pc(g.take) + '</td><td>' + tag(g, false) + '</td></tr>';
    }).join('');
    el.innerHTML = c.groups.length ? '<div class="tw"><table><thead><tr><th>' + (kind === 'place' ? 'place'
      : kind === 'town' ? 'town' : 'cell') + '</th><th>n</th><th>days</th><th>vs same hours</th><th>95%</th>'
      + '<th>median $/hr</th><th>95%</th><th>median pay</th><th>rig said take</th><th></th></tr></thead><tbody>'
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
    document.getElementById('dropTest').innerHTML = testText(v.dropTown, 'wait by town');
    dropTable(document.getElementById('dropTown'), v.dropTown, 'town');
    dropTable(document.getElementById('dropGrid'), v.dropGrid, 'cell');
    drawMap(v);
  }
  sel.addEventListener('change', draw);
  coverageTable();
  draw();
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
 * through the relay. Every answer is kept in `cache` by its question. */
function nbxFetch(opts) {
  var cache = opts.cache;
  var server = opts.server.replace(/\/+$/, '');
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
          return reply(502, { ok: false, unreachable: true, error: 'Nominatim answered ' + r.status });
        }
        body = hitsOf(r.body); status = 200;
      } else {
        var r2 = await getJson(server + '/api/nbx' + pathAsked);
        body = r2.body || {}; status = r2.status;
      }
    } catch (e) {
      return reply(502, { ok: false, unreachable: true, error: String(e && e.message || e) });
    }
    if (status === 200 && body && body.ok !== undefined && !body.unreachable) {
      cache.answers[pathAsked] = body;
      cache.fresh += 1;
      if (opts.onFresh) opts.onFresh();
    }
    return reply(status, body);
  };
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
            gap: MV.NBX_GAP_MS, minN: MIN_N };
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
    else if (a === '-h' || a === '--help') o.help = true;
    else if (/^--/.test(a)) throw new Error('unknown option ' + a);
    else if (!o.server) o.server = a;
    else throw new Error('one server address, not two');
  }
  if (!o.server) o.server = 'http://localhost:8081';
  if (o.since && !/^\d{4}-\d\d-\d\d$/.test(o.since)) throw new Error('--since is YYYY-MM-DD');
  if (!(o.minN >= 2)) throw new Error('--min-n is a number, 2 or more');
  if (!(o.gap >= 0)) throw new Error('--gap is milliseconds');
  return o;
}

var USAGE = [
  'usage: node tools/places_report.js [http://localhost:8081] [--out ~/places-report]',
  '         [--gps ~/gpslog] [--since YYYY-MM-DD] [--nominatim http://localhost:8088]',
  '         [--cache ~/.cache/uber-scan/places-report-answers.json] [--gap ms] [--min-n 30]',
  '',
  'Run on the NucBox. Reads the copy at home (its /api/journal), places pickups with the',
  'NucBox\'s own Nominatim (directly with --nominatim, else through that server\'s /api/nbx),',
  'and writes index.html and CSVs to --out, which must be outside the repository.',
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

  var settings = { search: false, streets: false };
  try {
    var s = await getJson(o.server.replace(/\/+$/, '') + '/api/nbx');
    if (s.ok && s.body) settings = { search: !!s.body.search, streets: !!s.body.streets };
  } catch (e) { /* an older server: no relay */ }
  var nominatim = o.nominatim || (settings.search ? null : 'http://localhost:8088');
  console.error('search: ' + (nominatim ? nominatim + ' (direct)' : o.server + '/api/nbx (relay)')
                + ' · street index: ' + (settings.streets ? 'yes, through the relay' : 'none'));

  var cache = { answers: {}, hits: 0, fresh: 0 };
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
  var nbx = new MV.NbxSearch({ base: '/api/nbx', gap: o.gap,
    fetch: nbxFetch({ cache: cache, server: o.server, nominatim: nominatim,
                      onFresh: function () { if (cache.fresh % 100 === 0) saveCache(); } }) });

  // Every pickup the rig stands behind, asked once per (text, card disc box).
  var placed = new Array(offers.length);
  var memo = new Map();
  var todo = 0, done = 0;
  offers.forEach(function (row) { if (counted(row) && row.pickup) todo += 1; });
  for (var i = 0; i < offers.length; i++) {
    var row = offers[i];
    if (!counted(row) || !row.pickup) continue;
    var disc = MV.discFor(row);
    var k = row.pickup + '\u0000' + (disc ? MV.discBox(disc) + '/' + disc.miles.toFixed(2)
                                          + '/' + disc.at.lat.toFixed(3) + ',' + disc.at.lon.toFixed(3) : '-');
    if (!memo.has(k)) memo.set(k, await placePickup(nbx, row.pickup, row, settings.streets));
    placed[i] = memo.get(k);
    done += 1;
    if (done % 200 === 0) console.error('  pickups ' + done + ' of ' + todo + ' (' + cache.fresh + ' asked, '
                                        + cache.hits + ' from the cache)');
  }

  // Taken trips: the GPS log at the drop, else the dropoff's door.
  var taken = Array.isArray(body.taken) ? body.taken : [];
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
    var at = await placeDropoff(nbx, byId[trip.id].dropoff, byId[trip.id], settings.streets);
    if (at) dropPins[key] = at;
  }
  saveCache();
  function dropAt(tr) {
    var kk = tr.id + '@' + tr.endedAt;
    if (gpsPos[kk]) return { at: gpsPos[kk], how: 'gps' };
    if (dropPins[kk]) return { at: dropPins[kk], how: 'pin' };
    return null;
  }

  var report = analyse(offers, taken, placed, dropAt, {
    minN: o.minN, source: { server: o.server, count: body.count, total: body.total,
                            truncated: !!body.truncated, since: o.since } });
  fs.mkdirSync(outDir, { recursive: true });
  fs.writeFileSync(path.join(outDir, 'index.html'), html(report));
  fs.writeFileSync(path.join(outDir, 'places.csv'), csvOf(report, 'place'));
  fs.writeFileSync(path.join(outDir, 'towns.csv'), csvOf(report, 'town'));
  fs.writeFileSync(path.join(outDir, 'grid.csv'), csvOf(report, 'grid'));
  fs.writeFileSync(path.join(outDir, 'dropoff_towns.csv'), dropCsv(report, 'dropTown'));
  fs.writeFileSync(path.join(outDir, 'dropoff_grid.csv'), dropCsv(report, 'dropGrid'));
  fs.writeFileSync(path.join(outDir, 'coverage.csv'), coverageCsv(report));
  console.log(summary(report));
  console.log('\nWritten: ' + path.join(outDir, 'index.html') + ' (and six CSVs beside it)');
  console.log('NucBox questions: ' + cache.fresh + ' asked, ' + cache.hits + ' answered from ' + cacheFile);
}

module.exports = {
  MIN_N: MIN_N, DROP_MIN_N: DROP_MIN_N, GRID_MI: GRID_MI, NEXT_GAP_MIN: NEXT_GAP_MIN, VIEWS: VIEWS,
  pickupKind: pickupKind, placePickup: placePickup, placeDropoff: placeDropoff, storeLabel: storeLabel,
  placesOf: placesOf, cellOf: cellOf, bootCI: bootCI, cells: cells, coverage: coverage,
  nextTake: nextTake, timelineOf: timelineOf, tripsOf: tripsOf, dropTable: dropTable,
  analyse: analyse, summary: summary, testLine: testLine, html: html, csvOf: csvOf, dropCsv: dropCsv,
  coverageCsv: coverageCsv, hitsOf: hitsOf, nbxFetch: nbxFetch, gpsAt: gpsAt, parseArgs: parseArgs,
  inside: inside, realish: realish, outingOf: outingOf, main: main,
};

if (require.main === module) main(process.argv.slice(2));
