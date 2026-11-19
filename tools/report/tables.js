/* The places report's tables: the ranking with its test and intervals,
 * coverage, the second pass (takes, waits, strand, busy, apps, $/mi,
 * add-ons, gone quiet, trend), restaurants, the third pass (the top of the
 * distribution) and the Strategy tab's orders. Each section keeps its own
 * rule and floor; tools/places_report.js has the whole report's. */

'use strict';

var A = require('../../advice.js');
var MV = require('../../map-view.js');
var AS = require('../../assemble.js');
var OP = require('../../offer-parser.js');
// What the app paid, for an order this report could not time (uberTimingFor).
var E = require('../../earnings.js');

var ST = require('./stats.js');
var PL = require('./place.js');
var MIN_N = ST.MIN_N, MIN_OUTINGS = ST.MIN_OUTINGS, ALPHA = ST.ALPHA, SHUFFLES = ST.SHUFFLES,
    BOOTS = ST.BOOTS, DROP_MIN_N = ST.DROP_MIN_N, FINISHED = ST.FINISHED, GPS_TIMED = ST.GPS_TIMED,
    round2 = ST.round2, maxOf = ST.maxOf, rng = ST.rng, seedOf = ST.seedOf, bootCI = ST.bootCI,
    counted = ST.counted, seenAt = ST.seenAt, stratum = ST.stratum, outingOf = ST.outingOf, pText = ST.pText,
    shareName = ST.shareName, pct = ST.pct;
var pickupKind = PL.pickupKind, WHY = PL.WHY, POINT_LEVELS = PL.POINT_LEVELS,
    APPROX_LEVELS = PL.APPROX_LEVELS, isPoint = PL.isPoint, storeLabel = PL.storeLabel;

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
      memo[k] = others.length ? A.median(others) : null;
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
    var score = diffs.length ? round2(A.median(diffs)) : null;
    var sci = bootCI(diffs, seedOf('s' + g.name));
    var clear = sci ? (sci[0] > 0 ? 'above' : sci[1] < 0 ? 'below' : null) : null;
    return {
      name: g.name, n: g.n, outings: g.days,
      median: round2(g.median), ci: bootCI(vals, seedOf('m' + g.name)),
      score: score, sci: sci, compared: diffs.length,
      pay: pays.length ? round2(A.median(pays)) : null,
      take: said.length ? round2(said.filter(function (o) { return o.state === 'go'; }).length
                                 / said.length) : null,
      // $/mi off the card, read and never ranked (see payPerMile).
      ppm: ppms.length ? round2(A.median(ppms)) : null, ppmN: ppms.length,
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
             perHour: list.length ? round2(A.median(list.map(function (o) { return o.perHour; }))) : null,
             pay: list.length ? round2(A.median(list.filter(function (o) {
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

// Advice.median, the one median the reports share (map-view.js's, which this
// file read before, is the same rule and stays map-view's own).
function med(xs) { return xs.length ? round2(A.median(xs)) : null; }
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
  var end = maxOf(times), cut = end - QUIET_DAYS * 864e5;
  var before = pool.filter(function (o) { return seenAt(o) < cut; });
  var recent = pool.filter(function (o) { return seenAt(o) >= cut; });
  var outB = A.outingsIn(before), outR = A.outingsIn(recent);
  var by = groupBy(pool, key);
  var out = Object.keys(by).filter(function (k) { return by[k].length >= DESC_MIN_N; }).map(function (k) {
    var list = by[k];
    var b = list.filter(function (o) { return seenAt(o) < cut; }).length, r = list.length - b;
    var last = maxOf(list.map(seenAt));
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
 * share can sit a little over 10%. Every column counting these says "(for
 * its hours)" (the reporting code's second review): elsewhere in the report
 * "top 10%" is of the whole range — When & where's ruler, the Strategy tab,
 * the Overview's spread — and the two read alike in a header. */
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

// The q-th quantile of an unsorted list, linear between order statistics
// (R's type 7): sorted here, then advice.js's quantile, the one copy.
function quantile(xs, q) {
  return A.quantile(xs.slice().sort(function (a, b) { return a - b; }), q);
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
                  C('top25', 'top 25% (for its hours)', '%'), C('top10N', 'top 10% (for its hours) n', 'n'),
                  C('top10', 'top 10% (for its hours)', '%'),
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
                  C('top25PerHour', 'top 25% (for its hours) / hr waiting', 'r2'),
                  C('top10PerHour', 'top 10% (for its hours) / hr waiting', 'r2'),
                  C('trips', 'taken while there', 'n'), C('timed', 'of them timed', 'n'),
                  C('expected', 'expected $/hr working it', '$'),
                  C('ifTop10', 'if every top 10% (for its hours) taken (offered, card min)', '$')], rows: out };
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
                  C('p90', 'P90 $/hr', '$'), C('top10', 'top 10% (for its hours)', '%'),
                  C('ppm', 'median $/mi (read only)', '$')],
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

module.exports = {
  cells: cells, coverage: coverage, DESC_MIN_N: DESC_MIN_N, REAL_MED_N: REAL_MED_N, REAL_BY: REAL_BY,
  QUIET_DAYS: QUIET_DAYS, SPELL_M: SPELL_M, SPELL_MIN_S: SPELL_MIN_S, SPELL_GAP_S: SPELL_GAP_S,
  SPELL_THIN_S: SPELL_THIN_S, SPELL_MIN_N: SPELL_MIN_N, payPerMile: payPerMile, appOf: appOf,
  EARLY_LOOK: EARLY_LOOK, MULTI_ORDER: MULTI_ORDER, MANY_DROPOFFS: MANY_DROPOFFS, flagsOf: flagsOf,
  wilson: wilson, poissonLE: poissonLE, isoWeek: isoWeek, med: med, medCi: medCi, share: share,
  runsOf: runsOf, realOf: realOf, groupBy: groupBy, C: C, takesTable: takesTable, waitOf: waitOf,
  waitsTable: waitsTable, strandTable: strandTable, busyTable: busyTable, appsTable: appsTable,
  ppmTable: ppmTable, stackTable: stackTable, quietTable: quietTable, trendTable: trendTable,
  stillRuns: stillRuns, spellsOf: spellsOf, heldOf: heldOf, nameOf: nameOf, restaurantNames: restaurantNames,
  restaurantsTable: restaurantsTable, TIER_MIN_N: TIER_MIN_N, TAKE_SLACK_MS: TAKE_SLACK_MS,
  DEAD_MAX_MIN: DEAD_MAX_MIN, STOP_M: STOP_M, STOP_MIN_S: STOP_MIN_S, PRESS_AFTER_MIN: PRESS_AFTER_MIN,
  PRESS_BEFORE_MIN: PRESS_BEFORE_MIN, SHORT_MILES: SHORT_MILES, SIZE_BANDS: SIZE_BANDS, quantile: quantile,
  qOf: qOf, Q_BOOT_MAX: Q_BOOT_MAX, tiersOf: tiersOf, topOf: topOf, timePresses: timePresses,
  shareTest: shareTest, goodTable: goodTable, waitTable: waitTable, deadOf: deadOf, deadTable: deadTable,
  sizeTable: sizeTable, bestLines: bestLines, RECORD_MATCH_MS: RECORD_MATCH_MS, recordFor: recordFor,
  milesBetween: milesBetween, strategyOrders: strategyOrders,
};
