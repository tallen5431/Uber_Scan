/* What $/hr to expect, and what holding out for it was worth, off the
 * owner's own record.
 *
 * The owner, 7 Nov 2026: "Any improvements that could be made for offer data
 * analysis? It would be nice to have an improved report, being able to know
 * what is a good $/hr and $/mi metrics to expect would help decide which
 * offers to take and which to decline."
 *
 * Four questions, one module, two reports. tools/places_report.js shows the
 * answers as its Strategy tab on the NucBox over the whole synced record; the
 * end-of-shift report in tools/ prints the same numbers, worded the same way,
 * for a day or a range of days with --strategy. One computation, so the two
 * cannot drift; each report hands it the orders as its OWN rules judged them
 * (the places report's realOf, the shift report's `reliable`), because
 * whether an order was delivered is that report's call and is tested there.
 * This file never decides it.
 *
 *   1. WHAT OFFERS LOOK LIKE. Quartiles and the 90th percentile of the
 *      card's $/hr (the figure the panel showed: the row's `perHour`, net of
 *      the running cost the rig took off) and $/mi (pay over the card's
 *      miles, nothing taken off: journal.html's payPerMile) of every offer
 *      SEEN, by app, three-hour block, weekday or weekend, and area; and how
 *      many offers came in per hour of time with no order in the car.
 *   2. HOW CARDS TURN INTO ACTUALS. For the orders a report timed, the
 *      minutes really taken against the card's, the GPS miles against the
 *      card's, and the actual $/hr against the card's, by app, card length,
 *      card $/hr, block and area — so a card's $/hr can be read as what such
 *      cards have actually paid.
 *   3. THE ACCEPT-THRESHOLD CURVE. For each line T, what holding out for
 *      cards at T or more would have paid per hour of SHIFT, in a renewal
 *      model: free, offers at T+ arrive at λ(T) an hour; each pays pay(T) and
 *      takes time(T), its card minutes scaled by the measured actual/card
 *      ratio; effective $/hr(T) = pay(T) / (1/λ(T) + time(T)).
 *   4. A PLAIN-WORDS SUMMARY of the three.
 *
 * DESCRIPTIVE, AND NOTHING ELSE. Nothing on the rig requires this file: no
 * verdict, state, target, band or panel line reads it. AUDITS.md's Settled
 * list binds every part of it, and each is answered rather than walked past:
 *
 *   - no $/mile rule and no payout floor. The $/mi curve is printed as
 *     information only, labelled so, because a $/mile rule replayed 24%
 *     below $/hr ("Do not judge offers on $/mile, or on a payout floor").
 *   - no re-timing at a pace. Time is a clock less a clock. The one scaling
 *     here multiplies the CARD'S OWN MINUTES by a measured ratio of minutes
 *     to minutes — never minutes from miles, never a speed — which is the
 *     offers page's `refigured` (server.js), not the pace refused in
 *     "Do not re-time an offer at a pace".
 *   - no line tuned to the hour. A curve per block is printed because the
 *     owner asked what each hour pays, and beside it the held-out check that
 *     entry was settled on is run again on the record in hand: fitted on the
 *     other shift days and scored on the one left out, a line per block
 *     against one line for all hours. The overall curve is the one the
 *     summary leads with.
 *   - no weekday term. Weekday against weekend is a row in a table, with its
 *     shift days counted, and a term in nothing.
 *
 * Approximate points never feed a figure. Nothing here reads a position at
 * all: an area is the caller's (the places report's card town, map-view.js
 * townFor), and the miles are the odometer or the GPS log a report measured,
 * never a pin, an `approx` area or DoorDash's map label.
 *
 * Plain node, no dependencies beyond advice.js, so the shift report can run
 * it as a child (`node tools/strategy.js` reads a JSON request on stdin and
 * writes the answer on stdout) and both reports get one answer. */

'use strict';

var A = require('../advice.js');

/* --- the numbers it works to ---------------------------------------------- */

// The lines the curve is drawn at, on the panel's $/hr: $10 to $40 in $2
// steps, as asked. Below $10 every offer the owner is ever shown is in and
// the curve is flat; above $40 the offers are a handful an evening.
var GRID = [];
for (var g = 10; g <= 40; g += 2) GRID.push(g);
// ...and on the card's $/mi, information only (the header's first bullet).
var MILE_GRID = [];
for (var gm = 0.5; gm <= 3.0001; gm += 0.25) MILE_GRID.push(Math.round(gm * 100) / 100);

// A silence longer than this, with no offer seen and no order in the car, is
// the driver stopping, and is no part of a shift: advice.js's SHOWN_AT, the
// break its runs() cut on, so "an hour on shift" here is an hour of the same
// runs the replay walks.
var BREAK_MIN = A.SHOWN_AT;

// The fewest values a quartile or a percentile is printed over; below it a
// row gives its n only. The places report's DESC_MIN_N, the floor under its
// descriptive medians: at nine a 90th percentile is the top value.
var DIST_MIN_N = 10;

// The fewest offers at a line, seen while free, before that point of a
// curve counts: advice.js's TARGET_OFFERS, the places report's MIN_N. A
// point under it is drawn hollow and can be neither the best nor in the
// flat region, because the maximum of a curve is where a thin tail's noise
// goes to look like a finding.
var CURVE_MIN_OFFERS = A.TARGET_OFFERS;

// The fewest timed orders an actual/card ratio is taken over: advice.js's
// TARGET_TIMED (server.js REFIGURED_MIN_RUNS), the floor under the other
// per-take figures on the offers page.
var RATIO_MIN_N = A.TARGET_TIMED;

// Shift days before a curve is drawn at all (advice.js AREA_DAYS: one
// evening is one evening), and before its interval is resampled (with two,
// a resample is one of three shapes and its "interval" is two numbers).
var CURVE_MIN_OUTINGS = A.AREA_DAYS;
var BOOT_MIN_OUTINGS = 3;
var BOOTS = 400;

// The flat region: every line within this of the best. advice.js's PLATEAU,
// the same 5% its own replay calls "the plateau is the finding".
var PLATEAU = A.PLATEAU;

// An order whose clock says it was in the car longer than this is a clock
// that stepped, not a delivery: four hours, chosen, not measured, past the
// longest stacked evening order on record and short of a Pi that slept.
var HOLD_MAX_MIN = 240;
// An order "delivered" in under this share of its card's minutes was put
// down at the pickup or on the way, not at the door: the shift report's
// TOO_SOON (0.3), held to every end here because the places report's
// at-the-door rule does not ask it. The lowest real delivery measured on
// four shifts ran 0.53 of its card.
var TOO_SOON = 0.3;

// Card length bands for the actuals, in card minutes: the shift report's
// BANDS, so the two reports' "20-30 min" rows are one row.
var BANDS = [[0, 20], [20, 30], [30, 45], [45, Infinity]];
// Card $/hr bands for "a card at $X has turned into": the panel's figure.
var RATE_BANDS = [[0, 15], [15, 20], [20, 25], [25, 30], [30, 40], [40, Infinity]];

/* --- small pieces --------------------------------------------------------- */

function num(v) { return typeof v === 'number' && isFinite(v) ? v : null; }
function r2(v) { return typeof v === 'number' && isFinite(v) ? Math.round(v * 100) / 100 : null; }
function sum(xs) { var s = 0; for (var i = 0; i < xs.length; i++) s += xs[i]; return s; }
function sorted(xs) { return xs.slice().sort(function (a, b) { return a - b; }); }

// R's type 7, which is what advice.js, server.js percentileOf and the
// places report's quantile all are: the same offers give the same P90.
function quantile(s, q) {
  if (!s.length) return null;
  var h = (s.length - 1) * q, lo = Math.floor(h), hi = Math.min(s.length - 1, lo + 1);
  return s[lo] + (h - lo) * (s[hi] - s[lo]);
}
function median(xs) { return xs.length ? quantile(sorted(xs), 0.5) : null; }

// advice.js's LCG (and the places report's), so a resample comes out the
// same on every run over the same record.
function rng(seed) {
  var s = seed >>> 0;
  return function () { s = (1664525 * s + 1013904223) >>> 0; return s / 4294967296; };
}

// The driver's shift day, 'YYYY-MM-DD', advice.js's 4am boundary.
function outingOf(at) {
  var d = new Date(at);
  if (!isFinite(d.getTime())) return null;
  d.setHours(d.getHours() - A.DAY_STARTS_AT);
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-'
    + String(d.getDate()).padStart(2, '0');
}

// Weekend is a shift day that is a Saturday or a Sunday (4am to 4am, so a
// Friday night past midnight is still Friday's). A row in a table, not a
// term in anything (the header).
function weekOf(at) {
  var d = new Date(at);
  if (!isFinite(d.getTime())) return null;
  d.setHours(d.getHours() - A.DAY_STARTS_AT);
  var w = d.getDay();
  return w === 0 || w === 6 ? 'weekend' : 'weekday';
}

function bandOf(v, bands) {
  if (v === null) return null;
  for (var i = 0; i < bands.length; i++) if (v >= bands[i][0] && v < bands[i][1]) return i;
  return null;
}
function bandName(b, unit) {
  if (b[1] === Infinity) return (unit === '$' ? '$' + b[0] + '+/hr' : b[0] + '+ min');
  return unit === '$' ? '$' + b[0] + '–' + b[1] + '/hr' : b[0] + '–' + b[1] + ' min';
}

/* --- the offers ----------------------------------------------------------- *
 *
 * One row per offer id. The places report's rows are the server's fold
 * already (bestReading's vote, /api/journal), so there this changes nothing;
 * the shift report reads the raw journal, where one card read four times is
 * four rows. There the newest reading advice.js's `trustworthy` stands
 * behind speaks for the card (else the newest at all), and the card was
 * SEEN when its first reading was written (`firstAt`, else the earliest
 * `at`) — the replay's own rule in advice.js `usable`: when it appeared, not
 * when the last correction was written. The vote between two clean readings
 * that disagree about the pay is not repeated here; on the record that is
 * rare, and the server's is the one the NucBox report reads. */
function dedupe(rows) {
  var byId = Object.create(null), loose = [], dup = 0;
  (rows || []).forEach(function (r) {
    if (!r || typeof r !== 'object') return;
    if (r.kind !== undefined && r.kind !== null) return;   // marks, drops, records: not offers
    if (typeof r.id !== 'string' || !r.id) { loose.push(r); return; }
    if (byId[r.id]) dup += 1;
    (byId[r.id] = byId[r.id] || []).push(r);
  });
  var out = [];
  Object.keys(byId).forEach(function (id) {
    var list = byId[id].slice().sort(function (a, b) { return (num(a.at) || 0) - (num(b.at) || 0); });
    var good = list.filter(A.trustworthy);
    var pick = (good.length ? good : list)[(good.length ? good : list).length - 1];
    var seen = null;
    list.forEach(function (r) {
      var t = num(r.firstAt) !== null ? r.firstAt : num(r.at);
      if (t !== null && (seen === null || t < seen)) seen = t;
    });
    out.push({ row: pick, seen: seen });
  });
  loose.forEach(function (r) { out.push({ row: r, seen: num(r.firstAt) !== null ? r.firstAt : num(r.at) }); });
  return { list: out, duplicates: dup };
}

// The card's minutes as the panel judged them: billed (the pad and the
// shopping allowance in) where the row has them, as advice.js usable does.
function cardMinutesOf(o) {
  var m = num(o.billedMinutes) !== null ? o.billedMinutes : num(o.minutes);
  return m !== null && m > 0 ? m : null;
}

// The panel's $/hr: the row's `perHour` (net of the running cost the rig
// took off), else worked out the way the rig works it, (pay - cost) over the
// billed minutes, for a row written without one.
function panelRate(o, mins) {
  if (num(o.perHour) !== null) return o.perHour;
  if (num(o.pay) === null || mins === null) return null;
  return (o.pay - (num(o.cost) || 0)) / (mins / 60);
}

// payPerMile, journal.html's and the places report's: pay over the card's
// miles, nothing off, none under a tenth of a mile (a misread's ratio).
function perMileOf(o) {
  return num(o.pay) !== null && num(o.miles) !== null && o.miles >= 0.1 ? o.pay / o.miles : null;
}

function appOf(o, appOfFn) {
  if (o.app === 'uber' || o.app === 'doordash') return o.app;
  var a = appOfFn ? appOfFn(o) : null;
  return a === 'uber' || a === 'doordash' ? a : 'unknown';
}

// An Uber add-on's card prints what it ADDS to the trip in progress. Not an
// offer a free driver is choosing among, and its minutes are an increment.
function addOnCard(o) {
  return o.addon === true || o.screen === 'uber.addon';
}

/* --- the shift: when the rig was on, and when the car was free -------------
 *
 * The rig was on shift while it was being shown offers, joined across any
 * silence under BREAK_MIN, and while an order was in the car however long
 * the phone stayed quiet (a forty-minute order with no card on the screen is
 * work, not a break: advice.js occupancy's lesson, measured on the owner's
 * week). So the shift is every offer's moment and every order's hold, merged
 * wherever the next begins within BREAK_MIN of the last one's end; a run of
 * one offer has no length and is no part of it. FREE is the shift less every
 * hold. A clock that steps forward leaves a silence and splits a run, never
 * adds idle hours; one that steps back only reorders rows, which are sorted.
 *
 * A hold is Took to the order's end, however it ended — a Drop pressed
 * early, a GPS drop, a replacing Took, an expiry — because the question is
 * when the car was not free, and every one of those is when the server let
 * it go. An order with a Took and no end is held for its card's minutes, the
 * floor advice.js's freeAgain calls a floor; one held over HOLD_MAX_MIN by
 * its own clock is held the same way and is not timed. */
function holdOf(o) {
  var took = num(o.tookAt);
  if (took === null) return null;
  var end = num(o.endedAt);
  if (end !== null && end >= took && (end - took) / 60000 <= HOLD_MAX_MIN) return [took, end];
  var card = num(o.cardMinutes);
  return card !== null && card > 0 ? [took, took + card * 60000] : null;
}

function mergeRuns(items, gapMs) {
  var s = items.slice().sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; });
  var out = [];
  s.forEach(function (it) {
    var last = out[out.length - 1];
    if (last && it[0] - last[1] <= gapMs) last[1] = Math.max(last[1], it[1]);
    else out.push([it[0], it[1]]);
  });
  return out;
}

// `runs` less `held` (both merged, sorted): the free stretches.
function subtract(runs, held) {
  var out = [];
  runs.forEach(function (r) {
    var pieces = [[r[0], r[1]]];
    held.forEach(function (h) {
      var next = [];
      pieces.forEach(function (p) {
        if (h[1] <= p[0] || h[0] >= p[1]) { next.push(p); return; }
        if (h[0] > p[0]) next.push([p[0], h[0]]);
        if (h[1] < p[1]) next.push([h[1], p[1]]);
      });
      pieces = next;
    });
    pieces.forEach(function (p) { if (p[1] > p[0]) out.push(p); });
  });
  return out;
}

// Free time cut at every local hour, so each piece lies inside one block and
// one shift day: [{from, to, block, outing, week}]. An hour is the finest
// edge either needs (blocks are three hours, the day turns at 4am), and
// Date's own local arithmetic carries a clock change.
function hourPieces(spans) {
  var out = [];
  spans.forEach(function (s) {
    var t = s[0];
    while (t < s[1]) {
      var d = new Date(t);
      var next = new Date(d.getFullYear(), d.getMonth(), d.getDate(), d.getHours() + 1).getTime();
      if (!(next > t)) next = t + 3600000;
      var to = Math.min(next, s[1]);
      out.push({ from: t, to: to, block: A.blockOf(t), outing: outingOf(t), week: weekOf(t) });
      t = to;
    }
  });
  return out;
}

function within(spans, t) {
  // Spans are sorted and disjoint: a binary search.
  var lo = 0, hi = spans.length - 1;
  while (lo <= hi) {
    var m = (lo + hi) >> 1;
    if (t < spans[m][0]) hi = m - 1;
    else if (t >= spans[m][1]) lo = m + 1;
    else return true;
  }
  return false;
}

/* --- the orders ------------------------------------------------------------
 *
 * Each caller's order: { id (the offer's), tookAt, endedAt, app, pay,
 * cardMinutes, cardMiles, addon, carried, actualMinutes, actualMiles,
 * clockStepped }. `actualMinutes` is set ONLY where the caller's own rule
 * measured a delivery (null otherwise); `actualMiles` only where a GPS log or
 * the order record's odometer counted them. Joined to its offer by id for the
 * panel's $/hr, its block and its area. */
function timedOf(o, offer, area, stats) {
  var act = num(o.actualMinutes);
  if (act === null || !(act > 0)) { stats.unmeasured += 1; return null; }
  if (o.addon === true) { stats.addons += 1; return null; }
  var card = num(o.cardMinutes);
  if (card === null || !(card > 0)) { stats.noCard += 1; return null; }
  if (o.clockStepped === true || act > HOLD_MAX_MIN) { stats.clock += 1; return null; }
  if (act < TOO_SOON * card) { stats.tooSoon += 1; return null; }
  var pay = num(o.pay) !== null ? o.pay : (offer ? num(offer.pay) : null);
  if (pay === null) { stats.noCard += 1; return null; }
  var billed = offer ? cardMinutesOf(offer) : null;
  var cost = offer && num(offer.cost) !== null ? offer.cost : 0;
  var cardPH = offer ? panelRate(offer, billed || card) : null;
  if (cardPH === null) { cardPH = (pay - cost) / (card / 60); stats.rateFromPay += 1; }
  var miles = num(o.cardMiles) !== null ? o.cardMiles : (offer ? num(offer.miles) : null);
  var actMi = num(o.actualMiles);
  var app = o.app === 'uber' || o.app === 'doordash' ? o.app
    : offer && (offer.app === 'uber' || offer.app === 'doordash') ? offer.app : null;
  return { id: o.id, app: app, cardMin: card, actMin: act, pay: pay, cost: cost,
           cardPH: cardPH, actualPH: (pay - cost) / (act / 60),
           cardPM: miles !== null && miles >= 0.1 ? pay / miles : null,
           cardMi: miles, actMi: actMi !== null && miles !== null && miles > 0 ? actMi : null,
           together: num(o.carried) !== null && o.carried >= 2,
           at: num(o.tookAt), block: A.blockOf(o.tookAt), outing: outingOf(o.tookAt),
           week: weekOf(o.tookAt), area: area };
}

/* What a set of timed orders says, card against actual. The ratio is the
 * sum of actual minutes over the sum of card minutes — the ratio a stretch
 * of driving runs at, which is what turns a card's $/hr into a shift's —
 * with the median of the per-order ratios beside it for the typical order. */
function actualsOf(name, list) {
  var withMi = list.filter(function (t) { return t.actMi !== null; });
  var enough = list.length >= RATIO_MIN_N;
  var ratio = enough ? sum(list.map(function (t) { return t.actMin; })) / sum(list.map(function (t) { return t.cardMin; })) : null;
  return {
    name: name, timed: list.length,
    together: list.filter(function (t) { return t.together; }).length,
    ratio: r2(ratio),
    ratioMedian: enough ? r2(median(list.map(function (t) { return t.actMin / t.cardMin; }))) : null,
    cardPH: enough ? r2(median(list.map(function (t) { return t.cardPH; }))) : null,
    actualPH: enough ? r2(median(list.map(function (t) { return t.actualPH; }))) : null,
    milesN: withMi.length,
    mileRatio: withMi.length >= RATIO_MIN_N
      ? r2(sum(withMi.map(function (t) { return t.actMi; })) / sum(withMi.map(function (t) { return t.cardMi; }))) : null
  };
}

/* --- the curve --------------------------------------------------------------
 *
 * Per line T, over the offers SEEN WHILE FREE (an offer seen with an order in
 * the car is a stacking question, and stacking is not modelled: the curve is
 * a driver who takes nothing while carrying, so it reads low by what stacking
 * earns): N(T) of them at T or more in H free hours, paying P(T) in all and
 * printing C(T) card minutes in all. With λ = N/H, pay(T) = P/N and time(T) =
 * r(T) x C/N, the renewal model's
 *
 *     effective $/hr(T) = pay(T) / (1/λ(T) + time(T)) = P / (H + r(T) x C / 60)
 *
 * — every free hour waiting, plus every order's measured time, over what they
 * paid. The second form is what is summed, resampled and tested.
 *
 * r(T) is the actual/card minutes ratio (sum over sum) of the timed orders
 * whose card was at T or more, because the cards that look best are the
 * ones whose minutes run most optimistic (AUDITS.md, Settled, on re-timing:
 * picking high $/hr picks high implied speed): one ratio for every line
 * would flatter the high ones. Where fewer than RATIO_MIN_N orders cleared a
 * line, the ratio of the highest line below it that had enough is carried,
 * and the point says so; with fewer than RATIO_MIN_N timed orders in all, r
 * is 1 and the curve takes the cards at their word, and says that too.
 *
 * Gross is the pay. Net is the pay less the running cost on the miles the
 * order drove: the card's miles x the measured GPS/card miles ratio (1 where
 * fewer than RATIO_MIN_N orders have both) x the cost per mile the rows
 * carry (advice.js costPerMileIn: the rig's own setting, as it deducted it).
 * The miles driven between orders are not counted on either side. */
function sumsAt(offers, grid, key) {
  var out = grid.map(function () { return { n: 0, pay: 0, card: 0, miles: 0, noMiles: 0 }; });
  offers.forEach(function (o) {
    var v = o[key];
    if (v === null) return;
    for (var k = 0; k < grid.length && v >= grid[k]; k++) {
      var s = out[k];
      s.n += 1; s.pay += o.pay; s.card += o.cardMin;
      if (o.miles !== null) s.miles += o.miles; else s.noMiles += 1;
    }
  });
  return out;
}
function ratioSumsAt(timed, grid, key) {
  var out = grid.map(function () { return { n: 0, act: 0, card: 0 }; });
  timed.forEach(function (t) {
    var v = t[key];
    if (v === null) return;
    for (var k = 0; k < grid.length && v >= grid[k]; k++) {
      out[k].n += 1; out[k].act += t.actMin; out[k].card += t.cardMin;
    }
  });
  return out;
}
function addSums(a, b) {
  return a.map(function (x, k) {
    var y = b[k], o = {};
    Object.keys(x).forEach(function (f) { o[f] = x[f] + y[f]; });
    return o;
  });
}

// r(T) per line, with where each came from: 'measured', 'carried' (from the
// highest lower line with enough), or 'card' (too few timed orders in all).
function ladder(rs, grid, all) {
  var out = [], last = null;
  for (var k = 0; k < grid.length; k++) {
    var s = rs[k];
    if (s.n >= RATIO_MIN_N && s.card > 0) {
      last = { r: s.act / s.card, from: 'measured', at: grid[k] };
      out.push({ r: last.r, from: 'measured', at: grid[k], n: s.n });
    } else if (last) {
      // Too few cleared this line: the last line below it that had enough.
      out.push({ r: last.r, from: last.from === 'pooled' ? 'pooled' : 'carried', at: last.at, n: s.n });
    } else if (all && all.n >= RATIO_MIN_N && all.card > 0) {
      // Too few even at the lowest line, but enough in all: the pooled
      // ratio, which at the lowest line is nearly the same set of orders.
      last = { r: all.act / all.card, from: 'pooled', at: null };
      out.push({ r: last.r, from: 'pooled', at: null, n: s.n });
    } else {
      out.push({ r: 1, from: 'card', at: null, n: s.n });
    }
  }
  return out;
}

function effective(S, H, r, cpm, mr) {
  var den = H + r * S.card / 60;
  if (!(den > 0) || !S.n) return { gross: null, net: null };
  return { gross: S.pay / den,
           net: cpm !== null ? (S.pay - cpm * mr * S.miles) / den : null };
}

// The best non-thin point and the flat region round it: the contiguous run
// of non-thin points, either side of the best, within PLATEAU of it.
function bestOf(points, field) {
  var best = null;
  points.forEach(function (p, i) {
    if (p.thin || p[field] === null) return;
    if (!best || p[field] > best.v) best = { i: i, v: p[field] };
  });
  if (!best) return null;
  var lo = best.i, hi = best.i;
  while (lo - 1 >= 0 && !points[lo - 1].thin && points[lo - 1][field] !== null
         && points[lo - 1][field] >= PLATEAU * best.v) lo -= 1;
  while (hi + 1 < points.length && !points[hi + 1].thin && points[hi + 1][field] !== null
         && points[hi + 1][field] >= PLATEAU * best.v) hi += 1;
  return { T: points[best.i].T, value: r2(best.v), n: points[best.i].n, from: points[lo].T, to: points[hi].T,
           index: best.i };
}

/* A curve over per-outing sums: { points, best, bestNet, all }. `days` is
 * the list of outings it covers (a resample repeats some). */
function curveFrom(per, days, grid, opts) {
  var S = grid.map(function () { return { n: 0, pay: 0, card: 0, miles: 0, noMiles: 0 }; });
  var R = grid.map(function () { return { n: 0, act: 0, card: 0 }; });
  var allR = { n: 0, act: 0, card: 0 }, H = 0, every = { n: 0, pay: 0, card: 0, miles: 0, noMiles: 0 };
  days.forEach(function (d) {
    var p = per[d];
    if (!p) return;
    S = addSums(S, p.S); R = addSums(R, p.R); H += p.H;
    allR.n += p.allR.n; allR.act += p.allR.act; allR.card += p.allR.card;
    Object.keys(every).forEach(function (f) { every[f] += p.every[f]; });
  });
  var rl = ladder(R, grid, allR);
  var mr = opts.mileRatio || 1;
  var points = grid.map(function (T, k) {
    var e = effective(S[k], H, rl[k].r, opts.cpm, mr);
    return { T: T, n: S[k].n, perFreeHour: H > 0 ? S[k].n / H : null,
             pay: S[k].n ? S[k].pay / S[k].n : null, cardMin: S[k].n ? S[k].card / S[k].n : null,
             ratio: rl[k].r, ratioFrom: rl[k].from, ratioAt: rl[k].at, ratioN: rl[k].n,
             gross: e.gross, net: e.net, thin: S[k].n < CURVE_MIN_OFFERS, noMiles: S[k].noMiles };
  });
  // Taking everything seen while free, at the pooled ratio: the baseline.
  var rAll = allR.n >= RATIO_MIN_N && allR.card > 0 ? allR.act / allR.card : 1;
  var eAll = effective(every, H, rAll, opts.cpm, mr);
  return { points: points, H: H, best: bestOf(points, 'gross'), bestNet: opts.cpm !== null ? bestOf(points, 'net') : null,
           all: { n: every.n, gross: eAll.gross, net: eAll.net } };
}

/* Per-outing sums for one slice of the record: `free` the free offers,
 * `pieces` the free-time pieces, `timed` the timed orders, each already
 * filtered to the slice. */
function perOuting(free, pieces, timed, grid, key, ratioKey) {
  var per = Object.create(null);
  function slot(d) {
    return per[d] || (per[d] = { off: [], H: 0, tm: [] });
  }
  free.forEach(function (o) { slot(o.outing).off.push(o); });
  pieces.forEach(function (p) { slot(p.outing).H += (p.to - p.from) / 3600000; });
  timed.forEach(function (t) { if (t.outing) slot(t.outing).tm.push(t); });
  Object.keys(per).forEach(function (d) {
    var p = per[d];
    p.S = sumsAt(p.off, grid, key);
    p.R = ratioSumsAt(p.tm, grid, ratioKey);
    p.allR = { n: p.tm.length, act: sum(p.tm.map(function (t) { return t.actMin; })),
               card: sum(p.tm.map(function (t) { return t.cardMin; })) };
    p.every = { n: p.off.length, pay: sum(p.off.map(function (o) { return o.pay; })),
                card: sum(p.off.map(function (o) { return o.cardMin; })),
                miles: sum(p.off.map(function (o) { return o.miles || 0; })),
                noMiles: p.off.filter(function (o) { return o.miles === null; }).length };
    delete p.off; delete p.tm;
  });
  return per;
}

/* The interval: shift days resampled with replacement, BOOTS times, seeded,
 * each resample's curve recomputed whole (its free hours, its offers, its
 * timed orders and so its ratios). By shift day and not by offer, because
 * offers on one evening move together and the night-to-night swing is what
 * a line has to survive (AUDITS.md: $13.92 to $27.06 on one week). Returns
 * each line's 95% interval and the middle 90% of where the best line fell. */
function bootstrap(per, days, grid, opts, seed) {
  if (days.length < BOOT_MIN_OUTINGS) return null;
  var r = rng(seed), vals = grid.map(function () { return []; }), bests = [];
  for (var b = 0; b < (opts.boots || BOOTS); b++) {
    var pick = [];
    for (var i = 0; i < days.length; i++) pick.push(days[Math.floor(r() * days.length)]);
    var c = curveFrom(per, pick, grid, opts);
    c.points.forEach(function (p, k) { if (p.gross !== null) vals[k].push(p.gross); });
    if (c.best) bests.push(c.best.T);
  }
  return {
    reps: opts.boots || BOOTS,
    ci: vals.map(function (v) {
      var s = sorted(v);
      return s.length >= 20 ? [r2(quantile(s, 0.025)), r2(quantile(s, 0.975))] : null;
    }),
    bestRange: bests.length ? [quantile(sorted(bests), 0.05), quantile(sorted(bests), 0.95)] : null
  };
}

/* The held-out check, AUDITS.md's "Do not tune the acceptance line to the
 * hour" measured again on the record in hand. One shift day out at a time:
 * on the others, the best single line for all hours, and the best line for
 * each block (a block whose best is thin there keeps the single line); on
 * the day left out, what each policy would have paid, by the curve's own
 * arithmetic (its free hours, its offers, the ratios the OTHER days
 * measured). Summed over every day held out: pay over hours, per policy, and
 * taking everything beside them. Needs BOOT_MIN_OUTINGS shift days. */
function heldOut(perAll, perBlock, days, grid, opts) {
  if (days.length < BOOT_MIN_OUTINGS) return null;
  var tot = { flat: [0, 0], block: [0, 0], all: [0, 0] }, used = 0;
  days.forEach(function (out) {
    var rest = days.filter(function (d) { return d !== out; });
    var flat = curveFrom(perAll, rest, grid, opts);
    var keep = perAll[out];
    if (!flat.best || !keep || !(keep.H > 0)) return;
    used += 1;
    var kFlat = flat.best.index;
    // The ratio each line carries is the other days' (no peeking at the day
    // being scored), as is every line chosen.
    function score(per, k, ratio) {
      var S = per.S[k];
      return [S.pay, per.H + ratio * S.card / 60];
    }
    var f = score(keep, kFlat, flat.points[kFlat].ratio);
    tot.flat[0] += f[0]; tot.flat[1] += f[1];
    var n = 0, act = 0, card = 0;
    rest.forEach(function (d) { var p = perAll[d]; if (p) { n += p.allR.n; act += p.allR.act; card += p.allR.card; } });
    var rEvery = n >= RATIO_MIN_N && card > 0 ? act / card : 1;
    tot.all[0] += keep.every.pay; tot.all[1] += keep.H + rEvery * keep.every.card / 60;
    // Per block: each block's own line where its curve on the other days has
    // a non-thin best, else the single line; scored on that block's slice of
    // the day held out. The blocks' slices add up to the whole day's free
    // hours and offers, so the two policies are scored on the same day.
    Object.keys(perBlock).forEach(function (b) {
      var pb = perBlock[b], here = pb[out];
      if (!here) return;
      var cb = curveFrom(pb, rest, grid, opts);
      var k = cb.best ? cb.best.index : kFlat;
      var s = score(here, k, cb.best ? cb.points[k].ratio : flat.points[kFlat].ratio);
      tot.block[0] += s[0]; tot.block[1] += s[1];
    });
  });
  if (!used) return null;
  function rate(x) { return x[1] > 0 ? r2(x[0] / x[1]) : null; }
  return { days: used, flat: rate(tot.flat), perBlock: rate(tot.block), everything: rate(tot.all) };
}

/* --- the whole thing --------------------------------------------------------
 *
 * input: { offers: journal rows (raw or folded), orders: the caller's orders,
 *          areaOf(row) -> name|null (optional), appOf(row) (optional),
 *          target: the driver's line (optional), costPerMile (optional:
 *          else advice.js costPerMileIn over the rows), boots, seed }. */
function analyse(input) {
  var inp = input || {};
  var dd = dedupe(inp.offers);
  var counts = { rows: (inp.offers || []).filter(function (r) { return r && (r.kind === undefined || r.kind === null); }).length,
                 duplicates: dd.duplicates, offers: 0, untrusted: 0, unrated: 0, addOnCards: 0 };
  var offers = [];
  var points = [];
  var areaById = Object.create(null);
  dd.list.forEach(function (x) {
    var o = x.row;
    if (x.seen === null) return;
    // Every card seen, trusted or not, says the rig was on and scanning.
    points.push(x.seen);
    if (!A.trustworthy(o)) { counts.untrusted += 1; return; }
    var mins = cardMinutesOf(o);
    var ph = panelRate(o, mins);
    if (num(o.pay) === null || mins === null || ph === null) { counts.unrated += 1; return; }
    var area = inp.areaOf ? inp.areaOf(o) || null : null;
    var rec = { id: o.id, at: x.seen, outing: outingOf(x.seen), block: A.blockOf(x.seen), week: weekOf(x.seen),
                app: appOf(o, inp.appOf), area: area, ph: ph, pm: perMileOf(o), pay: o.pay,
                cardMin: num(o.minutes) !== null && o.minutes > 0 ? o.minutes : mins,
                miles: num(o.miles) !== null && o.miles > 0 ? o.miles : null,
                cost: num(o.cost) || 0, addon: addOnCard(o) };
    if (rec.block === null || rec.outing === null) { counts.unrated += 1; return; }
    if (rec.addon) counts.addOnCards += 1;
    offers.push(rec);
  });
  counts.offers = offers.length;
  var byId = Object.create(null);
  dd.list.forEach(function (x) { if (x.row && typeof x.row.id === 'string') byId[x.row.id] = x.row; });
  offers.forEach(function (o) { if (typeof o.id === 'string') areaById[o.id] = o.area; });

  // The orders: holds for the shift, timed ones for the ratios.
  var stats = { orders: 0, unmeasured: 0, addons: 0, noCard: 0, clock: 0, tooSoon: 0, rateFromPay: 0,
                noEnd: 0 };
  var holds = [], timed = [];
  (inp.orders || []).forEach(function (o) {
    if (!o || num(o.tookAt) === null) return;
    stats.orders += 1;
    var h = holdOf(o);
    if (h) holds.push(h);
    if (num(o.endedAt) === null) stats.noEnd += 1;
    var t = timedOf(o, byId[o.id] || null, areaById[o.id] || null, stats);
    if (t) timed.push(t);
  });

  var heldU = mergeRuns(holds, 0);
  var runs = mergeRuns(points.map(function (p) { return [p, p]; }).concat(holds), BREAK_MIN * 60000)
    .filter(function (r) { return r[1] > r[0]; });
  var freeSpans = subtract(runs, heldU);
  var pieces = hourPieces(freeSpans);
  var shiftH = sum(runs.map(function (r) { return (r[1] - r[0]) / 3600000; }));
  var freeH = sum(freeSpans.map(function (s) { return (s[1] - s[0]) / 3600000; }));
  // The offers a free driver was choosing among: seen inside a run (its last
  // moment included), with no order in the car, and not an add-on (which
  // needs a trip in progress).
  var runSpans = runs.map(function (r) { return [r[0], r[1] + 1]; });
  var free = offers.filter(function (o) {
    return !o.addon && within(runSpans, o.at) && !within(heldU, o.at);
  });
  counts.free = free.length;
  counts.alone = offers.filter(function (o) { return !within(runSpans, o.at); }).length;
  counts.held = offers.filter(function (o) { return within(heldU, o.at); }).length;
  counts.outings = Object.keys(groupBy(offers, function (o) { return o.outing; })).length;
  counts.shiftHours = r2(shiftH);
  counts.freeHours = r2(freeH);
  counts.heldHours = r2(sum(heldU.map(function (h) { return (h[1] - h[0]) / 3600000; })));
  Object.keys(stats).forEach(function (k) { counts[k] = stats[k]; });
  counts.timed = timed.length;
  counts.together = timed.filter(function (t) { return t.together; }).length;

  var cpm = num(inp.costPerMile) !== null ? inp.costPerMile : A.costPerMileIn(inp.offers || []);
  if (cpm !== null && !(cpm > 0)) cpm = null;
  var miTimed = timed.filter(function (t) { return t.actMi !== null; });
  var mileRatio = miTimed.length >= RATIO_MIN_N
    ? sum(miTimed.map(function (t) { return t.actMi; })) / sum(miTimed.map(function (t) { return t.cardMi; })) : null;

  /* 1. what offers look like */
  function spread(xs) {
    var s = sorted(xs.filter(function (v) { return v !== null; }));
    var ok = s.length >= DIST_MIN_N;
    return { n: s.length, p25: ok ? r2(quantile(s, 0.25)) : null, p50: ok ? r2(quantile(s, 0.5)) : null,
             p75: ok ? r2(quantile(s, 0.75)) : null, p90: ok ? r2(quantile(s, 0.9)) : null };
  }
  function seenRow(name, list, freeList, hours) {
    return { name: name, n: list.length, outings: Object.keys(groupBy(list, function (o) { return o.outing; })).length,
             ph: spread(list.map(function (o) { return o.ph; })), pm: spread(list.map(function (o) { return o.pm; })),
             free: freeList ? freeList.length : null, freeHours: hours === null ? null : r2(hours),
             perFreeHour: freeList && hours > 0 ? r2(freeList.length / hours) : null };
  }
  function hoursWhere(f) { return sum(pieces.filter(f).map(function (p) { return (p.to - p.from) / 3600000; })); }
  var seen = {
    all: seenRow('every offer', offers, free, freeH),
    byApp: ['uber', 'doordash', 'unknown'].map(function (a) {
      var l = offers.filter(function (o) { return o.app === a; });
      // The two apps share the free time: an hour free is an hour for both.
      return l.length ? seenRow(a === 'unknown' ? 'app not read' : a === 'uber' ? 'Uber' : 'DoorDash', l,
                                free.filter(function (o) { return o.app === a; }), freeH) : null;
    }).filter(Boolean),
    byBlock: A.BLOCK_NAMES.map(function (n, b) {
      var l = offers.filter(function (o) { return o.block === b; });
      return l.length ? seenRow(n, l, free.filter(function (o) { return o.block === b; }),
                                hoursWhere(function (p) { return p.block === b; })) : null;
    }).filter(Boolean),
    byWeek: ['weekday', 'weekend'].map(function (w) {
      var l = offers.filter(function (o) { return o.week === w; });
      return l.length ? seenRow(w, l, free.filter(function (o) { return o.week === w; }),
                                hoursWhere(function (p) { return p.week === w; })) : null;
    }).filter(Boolean),
    // By area: offers only. Free time has no area here — nothing reads where
    // the car stood (the places report's Busy tab does, off the GPS spells).
    byArea: (function () {
      if (!inp.areaOf) return null;
      var by = groupBy(offers.filter(function (o) { return o.area; }), function (o) { return o.area; });
      return Object.keys(by).filter(function (k) { return by[k].length >= DIST_MIN_N; })
        .sort(function (a, b) { return by[b].length - by[a].length || (a < b ? -1 : 1); })
        .map(function (k) { return seenRow(k, by[k], null, null); });
    }()),
    areaThin: inp.areaOf ? (function () {
      var by = groupBy(offers.filter(function (o) { return o.area; }), function (o) { return o.area; });
      var thin = Object.keys(by).filter(function (k) { return by[k].length < DIST_MIN_N; });
      return { areas: thin.length, offers: sum(thin.map(function (k) { return by[k].length; })),
               noArea: offers.filter(function (o) { return !o.area; }).length };
    }()) : null
  };

  /* 2. how cards turn into actuals */
  function groupRows(f, names) {
    return names.map(function (n, i) {
      var l = timed.filter(function (t) { return f(t) === i; });
      return l.length ? actualsOf(n, l) : null;
    }).filter(Boolean);
  }
  var actual = {
    all: actualsOf('every timed order', timed),
    byApp: ['uber', 'doordash', 'unknown'].map(function (a) {
      var l = timed.filter(function (t) { return (t.app || 'unknown') === a; });
      return l.length ? actualsOf(a === 'unknown' ? 'app not read' : a === 'uber' ? 'Uber' : 'DoorDash', l) : null;
    }).filter(Boolean),
    byLength: groupRows(function (t) { return bandOf(t.cardMin, BANDS); }, BANDS.map(function (b) { return bandName(b, 'min'); })),
    byRate: groupRows(function (t) { return bandOf(t.cardPH, RATE_BANDS); }, RATE_BANDS.map(function (b) { return bandName(b, '$'); })),
    byBlock: groupRows(function (t) { return t.block; }, A.BLOCK_NAMES),
    byArea: inp.areaOf ? (function () {
      var by = groupBy(timed.filter(function (t) { return t.area; }), function (t) { return t.area; });
      return Object.keys(by).sort(function (a, b) { return by[b].length - by[a].length || (a < b ? -1 : 1); })
        .map(function (k) { return actualsOf(k, by[k]); });
    }()) : null
  };
  // "A card at $X has turned into about $Y": the band's own card median
  // over the band's own ratio, beside the median actual it measured.
  actual.byRate.forEach(function (g) {
    g.expected = g.ratio ? r2(g.cardPH / g.ratio) : null;
  });

  /* 3. the curve, overall */
  var seed = typeof inp.seed === 'number' ? inp.seed : 20261107;
  var opts = { cpm: cpm, mileRatio: mileRatio || 1, boots: inp.boots };
  var perAll = perOuting(free, pieces, timed, GRID, 'ph', 'cardPH');
  var days = Object.keys(perAll).filter(function (d) { return perAll[d].H > 0; }).sort();
  var overall = curveFrom(perAll, days, GRID, opts);
  var boot = bootstrap(perAll, days, GRID, opts, seed);
  if (boot) overall.points.forEach(function (p, k) { p.ci = boot.ci[k]; });
  var target = num(inp.target);
  var curve = {
    grid: GRID, points: overall.points.map(roundPoint), freeHours: r2(overall.H), days: days.length,
    best: overall.best, bestNet: overall.bestNet, everything: roundAll(overall.all),
    bestCi: boot && overall.best ? boot.ci[overall.best.index] : null,
    bestRange: boot ? boot.bestRange : null, boots: boot ? boot.reps : 0,
    drawn: days.length >= CURVE_MIN_OUTINGS && overall.H > 0,
    cost: { perMile: cpm === null ? null : r2(cpm), mileRatio: mileRatio === null ? null : r2(mileRatio),
            milesN: miTimed.length },
    ratioFrom: timed.length >= RATIO_MIN_N ? 'measured' : 'card',
    target: target === null ? null : {
      T: target,
      side: overall.best ? (target < overall.best.from ? 'below' : target > overall.best.to ? 'above' : 'inside') : null
    }
  };

  // ...on the card's $/mi, information only: thresholds on pay over card
  // miles, the ratio ladder over the timed orders' own card $/mi.
  var perMile = perOuting(free, pieces, timed, MILE_GRID, 'pm', 'cardPM');
  var mileCurve = curveFrom(perMile, days, MILE_GRID, opts);
  var curveMile = { grid: MILE_GRID, points: mileCurve.points.map(roundPoint), best: mileCurve.best,
                    everything: roundAll(mileCurve.all) };

  /* ...per block, app and weekday/weekend, where samples allow: point
   * estimates, each slice's own free hours and offers, its own timed orders
   * for the ratio where it has RATIO_MIN_N of them, else every timed order's
   * (said on the row). */
  function sliceCurve(name, offF, pieceF, timedF) {
    var tm = timed.filter(timedF);
    var own = tm.length >= RATIO_MIN_N;
    var per = perOuting(free.filter(offF), pieces.filter(pieceF), own ? tm : timed, GRID, 'ph', 'cardPH');
    var ds = Object.keys(per).filter(function (d) { return per[d].H > 0; }).sort();
    var c = curveFrom(per, ds, GRID, opts);
    var b = c.best;
    // The actual median for this slice's cards at its best line: "cards at
    // $22+ turned into about $26/hr actual".
    var atBest = b ? tm.filter(function (t) { return t.cardPH >= b.T; }) : [];
    return { name: name, days: ds.length, freeHours: r2(c.H), offers: free.filter(offF).length,
             timed: tm.length, ratioOwn: own, best: b, everything: roundAll(c.all),
             actualAtBest: atBest.length >= RATIO_MIN_N ? r2(median(atBest.map(function (t) { return t.actualPH; }))) : null,
             actualAtBestN: atBest.length,
             points: c.points.map(roundPoint), drawn: ds.length >= CURVE_MIN_OUTINGS && c.H > 0 };
  }
  var slices = {
    block: A.BLOCK_NAMES.map(function (n, b) {
      if (!free.some(function (o) { return o.block === b; })) return null;
      return sliceCurve(n, function (o) { return o.block === b; }, function (p) { return p.block === b; },
                        function (t) { return t.block === b; });
    }).filter(Boolean),
    app: ['uber', 'doordash'].map(function (a) {
      if (!free.some(function (o) { return o.app === a; })) return null;
      // An app's curve is "took only this app's cards at T+", in the same
      // free hours: the two apps are on the one phone at once.
      return sliceCurve(a === 'uber' ? 'Uber' : 'DoorDash', function (o) { return o.app === a; },
                        function () { return true; }, function (t) { return t.app === a; });
    }).filter(Boolean),
    week: ['weekday', 'weekend'].map(function (w) {
      if (!free.some(function (o) { return o.week === w; })) return null;
      return sliceCurve(w, function (o) { return o.week === w; }, function (p) { return p.week === w; },
                        function (t) { return t.week === w; });
    }).filter(Boolean)
  };

  // The held-out check, per block.
  var perBlock = Object.create(null);
  A.BLOCK_NAMES.forEach(function (n, b) {
    var tm = timed.filter(function (t) { return t.block === b; });
    var p = perOuting(free.filter(function (o) { return o.block === b; }),
                      pieces.filter(function (x) { return x.block === b; }),
                      tm.length >= RATIO_MIN_N ? tm : timed, GRID, 'ph', 'cardPH');
    if (Object.keys(p).length) perBlock[b] = p;
  });
  var held = heldOut(perAll, perBlock, days, GRID, opts);

  var res = {
    floors: { dist: DIST_MIN_N, curveOffers: CURVE_MIN_OFFERS, ratio: RATIO_MIN_N, outings: CURVE_MIN_OUTINGS,
              bootOutings: BOOT_MIN_OUTINGS, breakMin: BREAK_MIN, plateau: PLATEAU, holdMaxMin: HOLD_MAX_MIN,
              tooSoon: TOO_SOON },
    counts: counts, seen: seen, actual: actual, curve: curve, curveMile: curveMile, slices: slices, heldOut: held
  };
  res.lines = lines(res);
  return res;
}

function roundPoint(p) {
  return { T: p.T, n: p.n, perFreeHour: r2(p.perFreeHour), pay: r2(p.pay), cardMin: r2(p.cardMin),
           ratio: r2(p.ratio), ratioFrom: p.ratioFrom, ratioAt: p.ratioAt, gross: r2(p.gross), net: r2(p.net),
           thin: p.thin, ci: p.ci || null };
}
function roundAll(a) { return { n: a.n, gross: r2(a.gross), net: r2(a.net) }; }

function groupBy(rows, key) {
  var by = Object.create(null);
  rows.forEach(function (o) { var k = key(o); if (k !== null && k !== undefined) (by[k] = by[k] || []).push(o); });
  return by;
}

/* --- the words -------------------------------------------------------------
 *
 * Worded once, for both reports. What the record shows, with its n beside
 * every figure; no line tells the driver or the rig to do anything. */
function d0(v) { return '$' + Math.round(v); }
function d2(v) { return '$' + v.toFixed(2); }
function hrs(v) { return (Math.round(v * 10) / 10) + ' h'; }
function plural(n, one, many) { return n + ' ' + (n === 1 ? one : (many || one + 's')); }

function lines(r) {
  var out = [], c = r.counts, s = r.seen.all, a = r.actual.all, cv = r.curve;
  if (!c.offers) {
    out.push('No offers the rig stands behind in this window, so nothing to describe yet.');
    return out;
  }
  // 1. what offers look like
  if (s.ph.p50 !== null) {
    out.push('What offers looked like: ' + plural(c.offers, 'offer') + ' on ' + plural(c.outings, 'shift day')
             + '; the typical card showed ' + d2(s.ph.p50) + '/hr on the panel (half of them between '
             + d2(s.ph.p25) + ' and ' + d2(s.ph.p75) + ', the top 10% from ' + d2(s.ph.p90) + ')'
             + (s.pm.p50 !== null ? ' and ' + d2(s.pm.p50) + '/mi (top 10% from ' + d2(s.pm.p90) + '/mi)' : '')
             + (s.perFreeHour !== null ? '. With no order in the car, ' + s.perFreeHour.toFixed(1)
                + ' offers an hour came in (' + hrs(s.freeHours) + ' free)' : '') + '.');
  } else {
    out.push('What offers looked like: only ' + plural(c.offers, 'offer') + ', fewer than the ' + r.floors.dist
             + ' a quartile is given over.');
  }
  // 2. card against actual
  if (a.ratio !== null) {
    var at25 = 25 / a.ratio;
    out.push('Cards against what they took: over ' + plural(a.timed, 'timed order') + ', the minutes really taken ran '
             + a.ratio.toFixed(2) + 'x the card\'s (the typical order ' + a.ratioMedian.toFixed(2) + 'x)'
             + (a.mileRatio !== null ? ' and the miles driven ' + a.mileRatio.toFixed(2) + 'x the card\'s (' + a.milesN + ' with miles)' : '')
             + ', so a card\'s $/hr has turned into about card ÷ ' + a.ratio.toFixed(2) + ': a $25/hr card about '
             + d2(at25) + '/hr actual. The median timed order showed ' + d2(a.cardPH) + '/hr and made '
             + d2(a.actualPH) + '/hr.');
  } else {
    out.push('Cards against what they took: ' + plural(a.timed, 'timed order') + ', fewer than the ' + r.floors.ratio
             + ' a ratio is taken over' + (c.orders ? ' (' + c.orders + ' taken, ' + c.unmeasured + ' not measured at the door)' : '')
             + ', so the curve below takes the cards at their word.');
  }
  // 3. the curve
  if (!cv.drawn || !cv.best) {
    out.push('Holding out for a line: not enough yet — ' + hrs(cv.freeHours || 0) + ' free on '
             + plural(cv.days, 'shift day') + ', and a point needs ' + r.floors.curveOffers + ' offers at its line seen '
             + 'free (and ' + r.floors.outings + ' shift days for a curve at all).');
  } else {
    var b = cv.best;
    out.push('Holding out for cards at ' + d0(b.T) + '+/hr gave the best shift rate in your record: about '
             + d2(b.value) + '/hr gross for every hour on shift'
             + (cv.bestCi ? ' (95% interval ' + d2(cv.bestCi[0]) + '–' + d2(cv.bestCi[1]) + ', shift days resampled)' : '')
             + ', against ' + (cv.everything.gross !== null ? d2(cv.everything.gross) : '—') + '/hr taking everything. '
             + (b.from === b.to ? 'No other line came within ' + Math.round((1 - r.floors.plateau) * 100) + '% of it'
                : 'Anything from ' + d0(b.from) + ' to ' + d0(b.to) + ' gives about the same (within '
                  + Math.round((1 - r.floors.plateau) * 100) + '% of the best)')
             + '. n=' + b.n + ' offers at ' + d0(b.T) + '+ seen in ' + hrs(cv.freeHours) + ' free on '
             + plural(cv.days, 'shift day') + (cv.bestRange && cv.bestRange[0] !== cv.bestRange[1]
               ? '; resampled, the best line fell between ' + d0(cv.bestRange[0]) + ' and ' + d0(cv.bestRange[1]) + ' nine times in ten' : '')
             + '.');
    if (cv.bestNet && cv.cost.perMile !== null) {
      out.push('Net of running cost (' + d2(cv.cost.perMile) + '/mi, the rate the rows carry, on the card\'s miles x '
               + (cv.cost.mileRatio !== null ? cv.cost.mileRatio.toFixed(2) + ', your GPS ÷ card miles' : '1, too few orders with GPS miles')
               + '): best at ' + d0(cv.bestNet.T) + '+, about ' + d2(cv.bestNet.value) + '/hr.');
    }
    if (cv.target && cv.target.side) {
      out.push('Your line, ' + d0(cv.target.T) + ', is ' + (cv.target.side === 'inside' ? 'inside that range'
               : cv.target.side + ' that range') + '.');
    }
  }
  // per block, where a slice has a best of its own
  (r.slices.block || []).forEach(function (sl) {
    if (!sl.drawn || !sl.best) return;
    var turned = sl.actualAtBest !== null
      ? 'cards at ' + d0(sl.best.T) + '+/hr turned into about ' + d2(sl.actualAtBest) + '/hr actual ('
        + sl.actualAtBestN + ' timed); holding out for them'
      : 'holding out for cards at ' + d0(sl.best.T) + '+/hr';
    out.push(sl.name + ': ' + turned + ' gave about ' + d2(sl.best.value) + '/hr on shift (n=' + sl.best.n
             + ' offers, ' + hrs(sl.freeHours) + ' free on ' + plural(sl.days, 'shift day')
             + (sl.ratioOwn ? '' : '; the ratio is every timed order\'s') + ').');
  });
  if (r.heldOut) {
    var h = r.heldOut;
    out.push('Fitted on the other shift days and scored on the one left out (' + plural(h.days, 'day') + ' in turn): a line '
             + 'per block made ' + d2(h.perBlock) + '/hr, one line for all hours ' + d2(h.flat) + '/hr, taking everything '
             + d2(h.everything) + '/hr. ' + (h.perBlock > h.flat ? 'Here a line per block did better out of sample.'
               : 'A line per block did not beat one line out of sample, as AUDITS.md\'s Settled entry found.'));
  }
  // How far to trust it. The ±$2 is arithmetic, not a measurement here: the
  // owner's one measured week swung $13.92 to $27.06 night to night
  // (AUDITS.md), a spread of about $5 a night, and 1.96 x 5 / sqrt(n) is
  // under $2 from n = 24 shift days. Twenty timed orders put a ratio of sums
  // within about 10% on the spread the four measured shifts showed.
  var thin = [];
  if (cv.days < 10) thin.push('only ' + plural(cv.days, 'shift day'));
  if (a.timed < 12) thin.push(plural(a.timed, 'timed order'));
  if ((cv.freeHours || 0) < 20) thin.push(hrs(cv.freeHours || 0) + ' free');
  if (thin.length) {
    out.push('How far to trust it: thin — ' + thin.join(', ') + '. The interval and the resampled range say how far the '
             + 'best line could move; about 25 shift days and 20 timed orders before a ±$2 answer is likely.');
  }
  out.push('Descriptive: what the record shows. Nothing on the rig reads it; the verdict, the target and the panel do not change.');
  return out;
}

/* --- run as a child --------------------------------------------------------
 *
 * `node tools/strategy.js` reads one JSON request on stdin — { offers,
 * orders, target, costPerMile, boots, seed } — and writes the answer as JSON
 * on stdout. How the end-of-shift report asks it: one computation, not a
 * Python copy of this file to keep in step with it. */
if (require.main === module) {
  var chunks = [];
  process.stdin.on('data', function (c) { chunks.push(c); });
  process.stdin.on('end', function () {
    var req;
    try { req = JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}'); } catch (e) {
      process.stderr.write('strategy: the request is not JSON: ' + e.message + '\n');
      process.exitCode = 2;
      return;
    }
    process.stdout.write(JSON.stringify(analyse(req)) + '\n');
  });
}

module.exports = {
  analyse: analyse, lines: lines, dedupe: dedupe, mergeRuns: mergeRuns, subtract: subtract, hourPieces: hourPieces,
  holdOf: holdOf, quantile: quantile, outingOf: outingOf, weekOf: weekOf, ladder: ladder, bestOf: bestOf,
  GRID: GRID, MILE_GRID: MILE_GRID, BREAK_MIN: BREAK_MIN, DIST_MIN_N: DIST_MIN_N, CURVE_MIN_OFFERS: CURVE_MIN_OFFERS,
  RATIO_MIN_N: RATIO_MIN_N, CURVE_MIN_OUTINGS: CURVE_MIN_OUTINGS, BOOT_MIN_OUTINGS: BOOT_MIN_OUTINGS, BOOTS: BOOTS,
  PLATEAU: PLATEAU, HOLD_MAX_MIN: HOLD_MAX_MIN, TOO_SOON: TOO_SOON, BANDS: BANDS, RATE_BANDS: RATE_BANDS
};
