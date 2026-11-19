/* Where and when, off the car's own position: where trips leave you, where
 * you waited, When & where, Offers around you, the front page's glance,
 * the next offer after a drop and the empty driving to the next Took. Part
 * of the places report (tools/places_report.js has the rules). */

'use strict';

var A = require('../../advice.js');
var MV = require('../../map-view.js');
// trends.js's dispersion and rateShade, for When & where's interval (the
// reporting review's S2): the same widening the Trends grid's good per hour
// takes, so the two pages' marks mean the same thing.
var TR = require('../../trends.js');

var ST = require('./stats.js');
var PL = require('./place.js');
var TB = require('./tables.js');
var MIN_OUTINGS = ST.MIN_OUTINGS, DROP_MIN_N = ST.DROP_MIN_N, NEXT_GAP_MIN = ST.NEXT_GAP_MIN,
    AT_THE_DOOR = ST.AT_THE_DOOR, round2 = ST.round2, counted = ST.counted, seenAt = ST.seenAt,
    outingOf = ST.outingOf, cellOf = ST.cellOf, gridCell = ST.gridCell;
var PLACE_APPROX_MI = PL.PLACE_APPROX_MI;
var cells = TB.cells, DESC_MIN_N = TB.DESC_MIN_N, appOf = TB.appOf, med = TB.med, medCi = TB.medCi,
    share = TB.share, groupBy = TB.groupBy, C = TB.C, heldOf = TB.heldOf, DEAD_MAX_MIN = TB.DEAD_MAX_MIN,
    quantile = TB.quantile;

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
    g.nextPerHour = got.length ? round2(A.median(got.map(function (t) { return t.next.perHour; }))) : null;
    g.nextPay = got.length ? round2(A.median(got.map(function (t) { return t.next.pay; }))) : null;
    var any = list.filter(function (t) { return t.nextAny && !t.nextAny.censored; });
    g.anyN = any.length;
    g.anyMin = any.length ? round2(A.median(any.map(function (t) { return t.nextAny.wait; }))) : null;
    g.anyPerHour = any.length ? round2(A.median(any.map(function (t) { return t.nextAny.perHour; }))) : null;
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
 * all", and the ranked tables rank pickups for that reason. Since the USB
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

module.exports = {
  nextTake: nextTake, timelineOf: timelineOf, tripsOf: tripsOf, dropTable: dropTable,
  CREDIT_MAX_MIN: CREDIT_MAX_MIN, goodOf: goodOf, waitingLine: waitingLine, waitedTable: waitedTable,
  WW_BLOCKS: WW_BLOCKS, WW_DAYS: WW_DAYS, WW_TOPS: WW_TOPS, WW_TOP: WW_TOP, WW_MIN_HOURS: WW_MIN_HOURS,
  WW_MIN_DAYS: WW_MIN_DAYS, WW_CONF: WW_CONF, wwSlotOf: wwSlotOf, poissonCI: poissonCI,
  reportRulers: reportRulers, whenWhere: whenWhere, AROUND_BIN_MI: AROUND_BIN_MI,
  AROUND_BIN_DAYS: AROUND_BIN_DAYS, HOME_MI: HOME_MI, AROUND_RINGS: AROUND_RINGS, PICKUP_BANDS: PICKUP_BANDS,
  homeOf: homeOf, aroundYou: aroundYou, glanceOf: glanceOf, nextOffer: nextOffer,
  CARD_FIX_AFTER_MIN: CARD_FIX_AFTER_MIN, cardFixAfter: cardFixAfter, MOVED_MI: MOVED_MI, emptyOf: emptyOf,
  emptyTable: emptyTable, fixDensity: fixDensity,
};
