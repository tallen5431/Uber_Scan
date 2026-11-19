/* The offers page's Trends tab: trends.js's sums, and /api/trends.
   Run with: node tests/trends.test.js

   Every journal here is invented: ids, times, pay and places that never
   existed. Held hardest where a trend could flatter or mislead — an offer
   counted once per reading instead of once, a pay the server corrected read
   at its first figure, a suspect or "pay unread" row in a median, a grid cell
   shaded by chance, a rate card that cannot recover a price it was built
   from, a server that caps the window or a lite rig that serves it.
   Round two adds: the quantile interval against hand-worked ranks, runs
   split at the clock hour across midnight and 4am, the ruler held as one
   figure across days, the floors of P90 and of good per hour online, the
   calendar's week rows, and a looked-at cell that carries figures only.
   Round three adds: a take gross and net (and gross when no cost per mile is
   known), the weighted-Poisson interval against the Garwood one, earned per
   hour's floor and a no-take cell left unshaded, the wait for a good offer,
   good offers by app, off against quiet, the timeline across Monday 4am and
   the 1 Nov clock change, B against A (no difference left unshaded across
   224 cells; a real one shaded; both sides under the floor left grey), month
   thirds gated on three months, and one weekday over the weeks.
   The week in review adds: a week's span and its steps across the 1 Nov
   change, a week by hand, slots marked by a tile's rule and "none clear",
   and week against week only where both meet the floor. */

'use strict';

process.env.TZ = process.env.TZ || 'America/New_York';

var fs = require('fs');
var os = require('os');
var path = require('path');
var http = require('http');
var cp = require('child_process');
var T = require('../trends.js');

var pass = 0, fail = 0;
function eq(name, got, want) {
  if (JSON.stringify(got) === JSON.stringify(want)) { pass += 1; return; }
  fail += 1;
  console.log('FAIL  ' + name + ': got ' + JSON.stringify(got) + ' want ' + JSON.stringify(want));
}
function ok(name, cond) { eq(name, !!cond, true); }

function rng(seed) {
  var s = seed >>> 0;
  return function () { s = (1664525 * s + 1013904223) >>> 0; return s / 4294967296; };
}
// Local ms on 2026-03-<day> at <h>:<m>, the driver's clock.
function at(day, h, m) { return new Date(2026, 2, day, h, m || 0).getTime(); }
function offer(x) {
  var o = { id: 'o', at: at(2, 19), pay: 10, perHour: 20, minutes: 30, miles: 6, target: 25, whole: true,
            app: 'uber', state: 'no' };
  Object.keys(x || {}).forEach(function (k) { o[k] = x[k]; });
  return o;
}

(async function () {

  /* --- one offer, once: distinct ids, the newest copy --- */
  var dup = [offer({ id: 'a', at: at(2, 19, 0), pay: 8 }), offer({ id: 'a', at: at(2, 19, 1), pay: 12 }),
             offer({ id: 'b', at: at(2, 19, 5) }), offer({ id: 'a', at: at(2, 18, 59), pay: 99 }),
             offer({ kind: 'mark', id: 'b', at: at(2, 19, 6) }), offer({ id: undefined, at: at(2, 19, 7) })];
  var rows = T.readRows(T.rowsOf(dup));
  eq('an offer read three times is one offer, the newest copy\'s pay; a mark is no offer; a row with no id is its own',
     [rows.length, rows.filter(function (r) { return r.pay === 12; }).length], [3, 1]);

  /* --- the money: corrected pay used, suspect and "pay unread" left out, counted --- */
  var mix = [offer({ id: 'c1', pay: 14, corrected: { from: 1.68, to: 14, why: 'x' }, perHour: 28 }),
             offer({ id: 'c2', suspect: true, pay: 400, perHour: 800 }),
             offer({ id: 'c3', payUnread: true, suspect: true, pay: 1.68, perHour: null,
                     corrected: { from: 1.68, to: null, why: 'y' } }),
             offer({ id: 'c4', payUnread: true, pay: 1.68, perHour: 3 }),
             offer({ id: 'c5', pay: 10, perHour: 20 }),
             offer({ id: 'c6', hidden: true, pay: 50, perHour: 100 })];
  var mr = T.readRows(T.rowsOf(mix));
  var day = T.periods(mr, 'day')[0];
  eq('every offer is counted, the money only over the ones it can be read off',
     [day.n, day.counted, day.metrics.pay.n], [6, 2, 2]);
  eq('...the corrected pay is the pay, and the suspect $400 and the unread $1.68 are in no median',
     [day.metrics.pay.p50, day.metrics.perHour.p50], [12, 24]);
  eq('...a "pay unread" row is refused by name even where it was not marked suspect',
     mr.filter(function (r) { return r.unread && r.ok; }).length, 0);
  eq('the data-quality counts: suspect for another reason, pay re-read, pay unread (not overlapping)',
     day.quality, { suspect: 1, corrected: 1, unread: 2 });
  eq('"good" is the row\'s own target', mr.filter(function (r) { return r.good; }).length, 1);
  eq('the app share counts offers, and an offer whose app is not known says so',
     T.periods(T.readRows(T.rowsOf([offer({ id: 'u' }), offer({ id: 'd', app: 'doordash' }),
                                    offer({ id: 'n', app: null })])), 'day')[0].share,
     { uber: 1, doordash: 1, unknown: 1 });
  var bst = T.periods(T.readRows(T.rowsOf([offer({ id: 'b1', boost: 2.5 }), offer({ id: 'b2', boost: 0 }),
                                           offer({ id: 'b3' })])), 'day')[0].boost;
  eq('boost share only over rows that carry the field; none at all is no share, not zero', [bst,
     T.periods(T.readRows(T.rowsOf([offer({ id: 'x' })])), 'day')[0].boost], [{ known: 2, yes: 1 }, null]);

  /* --- the driver's day, the hours, the weekdays --- */
  var nightRows = T.readRows(T.rowsOf([offer({ id: 'n1', at: at(6, 23, 30) }), offer({ id: 'n2', at: at(7, 1, 30) }),
                                        offer({ id: 'n3', at: at(7, 5, 0) })]));
  eq('1:30am belongs to the night before (the 4am day); 5am is the next day',
     nightRows.map(function (r) { return r.day; }), ['2026-03-06', '2026-03-06', '2026-03-07']);
  eq('...and 1:30am on a Saturday is a Friday night', [nightRows[1].dow, nightRows[1].hour], [5, 1]);
  eq('weeks start on the Monday of the driver\'s day', T.weekKeyOf('2026-03-08'), '2026-03-02');

  // An invented month: 30 offers an hour from 6pm to 9pm on twelve evenings,
  // $/hr 10 + hour, so each hour's median is known.
  var r1 = rng(7), month = [];
  for (var d = 1; d <= 12; d++) {
    for (var h = 18; h <= 20; h++) {
      for (var k = 0; k < 3; k++) {
        month.push(offer({ id: 'm' + d + '-' + h + '-' + k, at: at(d, h, k * 15),
                           perHour: 10 + h - 18 + (k - 1) * 0.5, pay: 10 + r1() }));
      }
    }
  }
  var mrows = T.readRows(T.rowsOf(month));
  var hrs = T.hourly(mrows);
  eq('hours run 4am first, the small hours last', [hrs[0].hour, hrs[23].hour], [4, 3]);
  var six = hrs.filter(function (e) { return e.hour === 18; })[0], nine = hrs.filter(function (e) { return e.hour === 21; })[0];
  eq('each hour\'s median, its quartiles and its n over twelve days', [six.p50, six.n, six.days, six.enough],
     [10, 36, 12, true]);
  eq('...an hour with nothing is n 0 and not enough', [nine.n, nine.p50, nine.enough], [0, null, false]);
  var wkend = T.hourly(mrows, { days: 'weekend' }).filter(function (e) { return e.hour === 18; })[0];
  // March 2026: the 1st, 7th and 8th of the twelve are a Sunday and a weekend.
  eq('weekends alone: three of the twelve evenings', [wkend.n, wkend.days, wkend.enough], [9, 3, false]);
  eq('this month against the one before', T.monthsOf(mrows), { now: '2026-03', before: '2026-02' });
  var dailies = T.periods(mrows, 'day');
  eq('one entry a day, oldest first, nine offers each, the median $/hr of the three hours',
     [dailies.length, dailies[0].key, dailies[0].n, dailies[0].metrics.perHour.p50], [12, '2026-03-01', 9, 11]);
  eq('...and by week, Monday to Sunday', T.periods(mrows, 'week').map(function (e) { return [e.key, e.n]; }),
     [['2026-02-23', 9], ['2026-03-02', 63], ['2026-03-09', 36]]);

  /* --- good offers per hour online, off the runs of scanning --- */
  var runs = [[at(2, 18), at(2, 21)], [at(3, 3, 30), at(3, 4, 30)]];
  var goodRows = T.readRows(T.rowsOf([offer({ id: 'g1', at: at(2, 18, 5), perHour: 30 }),
                                       offer({ id: 'g2', at: at(2, 18, 6), perHour: 26 }),
                                       offer({ id: 'g3', at: at(2, 18, 7), perHour: 20 })]));
  var gp = T.goodPerHour(goodRows, runs, 'day');
  eq('good per hour online: the day\'s good offers over its own slices\' hours, a run across 4am cut there (its '
     + '3:30-4am half the night before\'s), while hoursBy still credits the sitting to the day it began',
     [gp[0].key, gp[0].good, gp[0].hours, gp[0].rate, T.hoursBy(runs, 'day')['2026-03-02'],
      T.onlineHoursBy(runs, 'day')['2026-03-03']], ['2026-03-02', 2, 3.5, 0.57, 4, 0.5]);

  /* --- one hours rule for every rate (the reporting review's F1) --- */
  // A night across Monday 4am: 1am-7am Mon 23 Nov 2026, the 4-7am cards $40
  // (good), the rest $15; Thu, Fri and Tue evenings at $15. Every view's
  // hours for a day, a week and a month are the same slices.
  (function () {
    var L = function (y, m, d, h) { return new Date(y, m - 1, d, h).getTime(); };
    var offs = [], rr = [], id = 0;
    function run(a, b, ph) {
      for (var t = a; t <= b; t += 600000) offs.push({ id: 'h' + (id++), at: t, pay: 10, perHour: ph(t), minutes: 20, miles: 4, app: 'uber' });
      rr.push([a, b]);
    }
    run(L(2026, 11, 19, 18), L(2026, 11, 19, 21), function () { return 15; });
    run(L(2026, 11, 20, 18), L(2026, 11, 20, 21), function () { return 15; });
    run(L(2026, 11, 23, 1), L(2026, 11, 23, 7), function (t) { return new Date(t).getHours() >= 4 ? 40 : 15; });
    run(L(2026, 11, 24, 18), L(2026, 11, 24, 20), function () { return 15; });
    var R = T.readRows(T.rowsOf(offs)), cutF = 40;
    var cal = T.calendar(R, rr, { stat: 'goodRate', cut: cutF });
    var tlw = T.timeline(R, rr, { by: 'week', stat: 'goodRate', cut: cutF });
    var wr = T.weekReview(R, rr, '2026-11-23', { cut: cutF });
    var gpw = T.goodPerHour(R, rr, 'week', cutF);
    var tile = function (d) { return cal.days.filter(function (x) { return x.day === d; })[0]; };
    eq('F1: Sunday night\'s 1-4am is Sunday\'s (3 h, no good), Monday\'s 4-7am Monday\'s (3 h, 19 good)',
       [tile('2026-11-22').hours, tile('2026-11-22').good, tile('2026-11-23').hours, tile('2026-11-23').good,
        tile('2026-11-23').value], [3, 0, 3, 19, 6.33]);
    eq('F1: the calendar\'s week column, the timeline\'s week row, the good-per-hour chart and the week card agree',
       [cal.weeks.map(function (w) { return [w.week, w.hours, w.good]; }),
        tlw.rows.map(function (r) { return [r.key, r.hours]; }).reverse(),
        gpw.map(function (e) { return [e.key, e.hours, e.good]; }), [wr.prev.hours, wr.now.hours, wr.now.good]],
       [[['2026-11-16', 9, 0], ['2026-11-23', 5, 19]], [['2026-11-16', 9], ['2026-11-23', 5]],
        [['2026-11-16', 9, 0], ['2026-11-23', 5, 19]], [9, 5, 19]]);
    var mon = T.sameWeekday(R, rr, 1, { cut: cutF }).days.filter(function (d) { return d.day === '2026-11-23'; })[0];
    eq('F1: one weekday over the weeks takes the same day hours', [mon.hours, mon.good, mon.goodRate, mon.rateThin],
       [3, 19, 6.33, false]);
    // The 1 Nov night: 10pm 31 Oct to 6am 1 Nov is nine real hours (1am twice):
    // 6 to October's driver day 31 Oct, 3 to 1 Nov.
    var offs2 = [], rr2 = [];
    offs = offs2; rr = rr2;
    run(L(2026, 10, 30, 18), L(2026, 10, 30, 21), function () { return 15; });
    run(L(2026, 10, 31, 22), L(2026, 11, 1, 6), function (t) { var d = new Date(t); return d.getDate() === 1 && d.getHours() >= 4 ? 40 : 15; });
    run(L(2026, 11, 2, 18), L(2026, 11, 2, 21), function () { return 15; });
    var R2 = T.readRows(T.rowsOf(offs2));
    var cal2 = T.calendar(R2, rr2, { stat: 'goodRate', cut: 40 });
    var tlm = T.timeline(R2, rr2, { by: 'month', stat: 'goodRate', cut: 40 });
    eq('F1: "Nov so far · Oct" are the timeline\'s month rows across the 1 Nov change (10 h and 5 h of 15 real)',
       [cal2.months.now.hours, cal2.months.before.hours, tlm.rows.map(function (r) { return r.hours; })], [5, 10, [5, 10]]);
  }());

  /* --- the grid: floor and shading together --- */
  var r2 = rng(11), gridRows = [];
  for (var gd = 2; gd <= 29; gd++) {
    var date = new Date(2026, 2, gd);
    if (date.getDay() !== 5) continue;                        // Fridays only: 4 of them
    for (var gk = 0; gk < 12; gk++) {
      // 8pm pays far more than 7pm; 6pm the same as the month; 9pm has 8 offers.
      gridRows.push(offer({ id: 'f' + gd + '-' + gk, at: at(gd, 20, gk * 4), perHour: 34 + r2() * 4 }));
      gridRows.push(offer({ id: 'g' + gd + '-' + gk, at: at(gd, 19, gk * 4), perHour: 8 + r2() * 4 }));
      gridRows.push(offer({ id: 'h' + gd + '-' + gk, at: at(gd, 18, gk * 4), perHour: 12 + r2() * 20 }));
      if (gk < 2) gridRows.push(offer({ id: 'i' + gd + '-' + gk, at: at(gd, 21, gk * 4), perHour: 90 }));
    }
  }
  var g = T.grid(T.readRows(T.rowsOf(gridRows)));
  function cellAt(dow, hour) { return g.cells.filter(function (c) { return c.dow === dow && c.hour === hour; })[0]; }
  var c8 = cellAt(5, 20), c7 = cellAt(5, 19), c6 = cellAt(5, 18), c9 = cellAt(5, 21);
  eq('a cell well above the month, over the floor on four Fridays, is shaded above', [c8.n, c8.days, c8.enough, c8.shade],
     [48, 4, true, 'above']);
  eq('...one well below, below', c7.shade, 'below');
  eq('...one whose interval holds the month\'s median is not shaded, though it prints its median', [c6.shade, c6.median !== null],
     [null, true]);
  eq('...a cell under the floor (8 offers, $90 each) is never shaded, however far out', [c9.n, c9.enough, c9.shade],
     [8, false, null]);
  eq('the grid is Monday first, 4am first, 168 cells', [g.cells.length, g.cells[0].dow, g.cells[0].hour, g.cells[167].dow],
     [168, 1, 4, 0]);
  eq('the 99% order-statistic ranks: none under 8, then the binomial\'s', [T.medianRank(7, 0.01), T.medianRank(8, 0.01),
     T.medianRank(30, 0.01), T.medianRank(100, 0.01)], [0, 1, 8, 37]);
  // With no effect: 400 cells of 30 from one distribution, compared with its median.
  var r3 = rng(99), shaded = 0;
  for (var rep = 0; rep < 400; rep++) {
    var vals = [];
    for (var v = 0; v < 30; v++) vals.push(Math.exp(Math.log(14) + 0.37 * (r3() + r3() + r3() - 1.5) * 2));
    if (T.shadeOf(vals, 2, 14).shade) shaded += 1;
  }
  ok('with no effect, at the floor, about 1 cell in 100 or fewer is shaded (' + shaded + ' of 400)', shaded <= 8);
  eq('...and one day is not enough for a grid cell', T.shadeOf(new Array(40).fill(30), 1, 14).enough, false);

  /* --- the calendar --- */
  var cal = T.calendar(T.readRows(T.rowsOf(gridRows)), [[at(6, 18), at(6, 22)]]);
  var fri = cal.days.filter(function (x) { return x.day === '2026-03-06'; })[0];
  eq('a tile a day: its offers, its median, offers per hour online, shaded by the grid\'s rule (one day is enough)',
     [fri.n, fri.hours, fri.perOnlineHour, fri.enough], [38, 4, 9.5, true]);

  /* --- the rate card: least squares that recovers what it was built from --- */
  var r4 = rng(5), rc = [];
  for (var rd = 2; rd <= 15; rd++) {
    for (var rk = 0; rk < 40; rk++) {
      var mins = 12 + r4() * 40, mi = 1 + r4() * 14;
      // pay = 2.50 + 0.20/min + 0.60/mi, plus a little noise.
      rc.push(offer({ id: 'r' + rd + '-' + rk, at: at(rd, 19, rk), minutes: mins, miles: mi,
                      pay: 2.5 + 0.2 * mins + 0.6 * mi + (r4() - 0.5) * 0.4, app: 'uber' }));
    }
  }
  // DoorDash: one week of only 12 offers, one whose minutes are miles over again.
  for (var dk = 0; dk < 12; dk++) rc.push(offer({ id: 'dd' + dk, at: at(3, 20, dk), app: 'doordash', minutes: 20, miles: 5 + dk }));
  for (var ck = 0; ck < 40; ck++) {
    rc.push(offer({ id: 'cl' + ck, at: at(10, 20, ck), app: 'doordash', minutes: 10 + ck, miles: (10 + ck) / 2 + (ck % 3) * 0.2,
                    pay: 5 + ck * 0.3 }));
  }
  var card = T.rateCard(T.readRows(T.rowsOf(rc)));
  var w1 = card.weeks.filter(function (w) { return w.week === '2026-03-02'; })[0];
  eq('the fit recovers the base and both rates it was built from',
     [Math.round(w1.uber.base * 10) / 10, Math.round(w1.uber.a * 100) / 100, Math.round(w1.uber.b * 100) / 100],
     [2.5, 0.2, 0.6]);
  eq('...and reads off the 20-minute, 5-mile trip ($9.50) inside its bootstrap interval',
     [Math.round(w1.uber.price), w1.uber.lo < 9.5 && w1.uber.hi > 9.5, w1.uber.thin], [10, true, null]);
  eq('a week under ' + T.RATE_MIN_N + ' offers is too thin: no point, the reason said',
     [w1.doordash.n, w1.doordash.price, w1.doordash.thin], [12, null, 'fewer than 30 offers']);
  var w2 = card.weeks.filter(function (w) { return w.week === '2026-03-09'; })[0];
  eq('...and one whose minutes and miles move together cannot be split, and says so',
     [w2.doordash.price, w2.doordash.thin], [null, 'minutes and miles move together; the fit cannot tell them apart']);
  eq('the same week drawn twice is the same interval (a seeded bootstrap)',
     T.rateCard(T.readRows(T.rowsOf(rc))).weeks[1].uber, card.weeks[1].uber);

  /* --- two periods --- */
  var cmp = T.compare(mrows, { from: '2026-03-01', to: '2026-03-06' }, 'weekend');
  eq('two periods side by side with their n: a date range against weekends',
     [cmp.a.offers, cmp.a.days, cmp.a.metrics.perHour.n, cmp.b.offers, cmp.b.days], [54, 6, 54, 27, 3]);

  /* --- the scatter and the CSVs --- */
  var sc = T.scatter(mrows, 50);
  eq('the scatter is thinned evenly past its cap, and says how many it was', [sc.points.length, sc.of, sc.labels],
     [50, 108, ['2026-03']]);
  var csv = T.csvPeriods(dailies, T.goodPerHour(mrows, [], 'day'), 'day').split('\n');
  eq('the daily CSV: a header and a line a day', [csv[0].split(',').slice(0, 4), csv.length - 2],
     [['day', 'offers', 'counted', 'pay_p25'], 12]);
  ok('...the hourly CSV: 24 lines', T.csvHourly(hrs).split('\n').length === 26);
  ok('...and no place or position is in the packed rows', !/lat|lon|pickup|dropoff|text/.test(JSON.stringify(T.pack(T.rowsOf(dup)))));

  /* === Round two: the ruler, the quantiles, good per hour online, the
     calendar's weeks and a cell looked at closely === */

  /* --- the order-statistic interval at any share, against hand-worked cases --- */
  // n=10, p=1/2, 95%: P(X<=1) = 11/1024 = .0107 <= .025 < P(X<=2) = 56/1024 = .0547,
  // so [x(2), x(9)], the textbook interval for a median of ten.
  // n=20, p=.75, 95%: P(X<=10) = .0139 <= .025 < P(X<=11) = .0409, so lo = 11;
  // P(X>=19) = 20(.75^19)(.25) + .75^20 = .0211 + .0032 = .0243 <= .025 < P(X>=18) = .091,
  // so hi = 19.
  // n=10, p=.9, 99%: P(X<=5) = .0016 <= .005 < P(X<=6) = .0128, so lo = 6; but
  // P(X>=10) = .9^10 = .349 > .005, so there is no upper rank at all (hi = 11).
  eq('quantile ranks: hand-worked n=10 median at 95%, n=20 P75 at 95%, n=10 P90 at 99% (no top)',
     [T.quantRanks(10, 0.5, 0.05), T.quantRanks(20, 0.75, 0.05), T.quantRanks(10, 0.9, 0.01)],
     [[2, 9], [11, 19], [6, 11]]);
  eq('...a P90 at 99% has a top only from 51 offers (0.9^51 = .0046, 0.9^50 = .0052)',
     [T.quantRanks(50, 0.9, 0.01)[1], T.quantRanks(51, 0.9, 0.01)], [51, [40, 51]]);
  var mirrored = true, sameMedian = true;
  [12, 30, 57, 100, 333].forEach(function (n) {
    [0.75, 0.9, 0.6].forEach(function (p) {
      var a = T.quantRanks(n, p, 0.01), b = T.quantRanks(n, Math.round((1 - p) * 100) / 100, 0.01);
      if (a[0] !== n + 1 - b[1] || a[1] !== n + 1 - b[0]) mirrored = false;
    });
    var m = T.quantRanks(n, 0.5, 0.01), k = T.medianRank(n, 0.01);
    if (m[0] !== k || m[1] !== n - k + 1) sameMedian = false;
  });
  ok('...the ranks at p mirror the ranks at 1 - p, and at 1/2 they are round one\'s median ranks', mirrored && sameMedian);
  var oneTo20 = []; for (var o20 = 1; o20 <= 20; o20++) oneTo20.push(o20);
  eq('...and the interval is those order statistics', [T.quantCI(oneTo20, 0.75, 0.05), T.quantCI(oneTo20.slice(0, 10), 0.9, 0.01)],
     [[11, 19], null]);

  /* --- the Poisson interval --- */
  var pz = T.poisCI(0, 0.01), pt = T.poisCI(10, 0.01), p1 = T.poisCI(1, 0.05);
  eq('the exact Poisson interval: 0 at 99% is [0, 5.30], 10 is [3.72, 21.40], 1 at 95% is [0.0253, 5.5716]',
     [pz[0], Math.round(pz[1] * 100) / 100, Math.round(pt[0] * 100) / 100, Math.round(pt[1] * 100) / 100,
      Math.round(p1[0] * 10000) / 10000, Math.round(p1[1] * 10000) / 10000], [0, 5.3, 3.72, 21.4, 0.0253, 5.5716]);
  eq('phi: nights alike is 1; nights that swing far past chance is well over 1',
     [T.dispersion([[{ k: 6, h: 1 }, { k: 6, h: 1 }, { k: 6, h: 1 }]]) === 1,
      T.dispersion([[{ k: 1, h: 1 }, { k: 14, h: 1 }, { k: 2, h: 1 }, { k: 16, h: 1 }]]) > 4], [true, true]);
  eq('...and a slice under a quarter hour is not used to measure it (a run starts at its first card)',
     T.dispersion([[{ k: 1, h: 0.05 }, { k: 6, h: 1 }, { k: 6, h: 1 }]]), 1);

  /* --- runs split at every clock hour, on the driver's day --- */
  var pcs = T.onlinePieces([[at(2, 19, 40), at(2, 21, 10)]]);
  eq('a run from 7:40 to 9:10 is 20 minutes of 7pm, an hour of 8pm and 10 minutes of 9pm',
     Object.keys(pcs).sort().map(function (k) { return [k, Math.round(pcs[k].hours * 60)]; }),
     [['2026-03-02|19', 20], ['2026-03-02|20', 60], ['2026-03-02|21', 10]]);
  var mid = T.onlinePieces([[at(6, 23, 30), at(7, 0, 30)]]);
  eq('a run across midnight stays on the Friday night: 11pm and 12am, half an hour each, both Friday',
     Object.keys(mid).sort().map(function (k) { return [k, mid[k].dow, mid[k].hour, mid[k].hours]; }),
     [['2026-03-06|0', 5, 0, 0.5], ['2026-03-06|23', 5, 23, 0.5]]);
  var four = T.onlinePieces([[at(7, 3, 30), at(7, 4, 30)]]);
  eq('a run across 4am: its 3am half on the Friday night, its 4am half on Saturday',
     Object.keys(four).sort().map(function (k) { return [k, four[k].dow, four[k].hour, four[k].hours]; }),
     [['2026-03-06|3', 5, 3, 0.5], ['2026-03-07|4', 6, 4, 0.5]]);
  var byCell = T.hoursByCell([[at(6, 23, 30), at(7, 0, 30)], [at(7, 3, 30), at(7, 4, 30)], [at(13, 23, 0), at(13, 23, 45)]]);
  eq('...and by weekday x hour: Friday 11pm 1.25 h on two nights, Friday 3am and Saturday 4am half an hour each',
     [byCell[5 * 24 + 23], byCell[5 * 24 + 3], byCell[6 * 24 + 4]],
     [{ hours: 1.25, days: 2 }, { hours: 0.5, days: 1 }, { hours: 0.5, days: 1 }]);
  eq('...while hoursBy still credits a sitting across 4am to the day it began (round one\'s rule, unchanged)',
     T.hoursBy([[at(7, 3, 30), at(7, 4, 30)]], 'day'), { '2026-03-06': 1 });

  /* --- the ruler: once over the range, then one fixed dollar figure --- */
  var rl = [];
  for (var rv = 1; rv <= 100; rv++) rl.push(offer({ id: 'rl' + rv, at: at(rv <= 50 ? 2 : 9, 19, rv % 50), perHour: rv }));
  rl.push(offer({ id: 'rlsus', at: at(9, 20), perHour: 900, suspect: true }));
  var rlRows = T.readRows(T.rowsOf(rl));
  var rul = T.ruler(rlRows, 20);
  eq('the ruler: the top 20% of $1..$100 is at or over $80.20, 20 offers, the suspect $900 not in it',
     [rul.top, rul.cut, rul.n, rul.over], [20, 80.2, 100, 20]);
  eq('...10, 30 and 50 the same way, and a share not offered falls back to 20',
     [T.ruler(rlRows, 10).cut, T.ruler(rlRows, 30).cut, T.ruler(rlRows, 50).cut, T.ruler(rlRows, 37).top],
     [90.1, 70.3, 50.5, 20]);
  var gpd = T.goodPerHour(rlRows, [[at(2, 19), at(2, 21)], [at(9, 19), at(9, 21)]], 'day', rul.cut);
  eq('...and every day is counted against that one figure: the low first week has none, the second all 20',
     gpd.map(function (e) { return [e.key, e.good, e.rate]; }), [['2026-03-02', 0, 0], ['2026-03-09', 20, 10]]);
  var calR = T.calendar(rlRows, [], { stat: 'p50', cut: rul.cut });
  eq('...the calendar\'s days by the same line, adding up to the ruler\'s own count',
     calR.days.reduce(function (a, d) { return a + d.good; }, 0), rul.over);
  eq('...and a good share in two periods uses it too', [T.compare(rlRows, { from: '2026-03-02', to: '2026-03-02' },
     { from: '2026-03-09', to: '2026-03-09' }, rul.cut).a.good, T.compare(rlRows, { from: '2026-03-02', to: '2026-03-02' },
     { from: '2026-03-09', to: '2026-03-09' }, rul.cut).b.good], [0, 20]);
  // The ruler is a way of reading the tab, and nothing outside the tab reads it.
  var outside = ['advice.js', 'server.js', 'live.html', 'ui.js', path.join('rpi', 'scan_pi.py')].filter(function (f) {
    var src = fs.readFileSync(path.join(__dirname, '..', f), 'utf8');
    return /uberscan\.trends\.top|\.ruler\(|isGood\(/.test(src);
  });
  eq('the ruler reaches no verdict, target, rig or scan_pi: nothing outside trends.js and the tab names it', outside, []);

  /* --- shading floors: the quantiles and good per hour online --- */
  var flo = [], fruns = [];
  [6, 13, 20, 27].forEach(function (fd, i) {
    for (var fk = 0; fk < 15; fk++) {
      // Friday 8pm: 15 offers a night at $40 (60 on four Fridays); 9pm: 10 a night (40 on four).
      flo.push(offer({ id: 'p8-' + fd + '-' + fk, at: at(fd, 20, fk * 3), perHour: 40 + fk * 0.1 }));
      if (fk < 10) flo.push(offer({ id: 'p9-' + fd + '-' + fk, at: at(fd, 21, fk * 4), perHour: 40 + fk * 0.1 }));
      // Friday 6pm, the bulk of the range: $8-$20, one good a night at most.
      flo.push(offer({ id: 'p6-' + fd + '-' + fk, at: at(fd, 18, fk * 4), perHour: 8 + fk * 0.8 }));
      flo.push(offer({ id: 'p7-' + fd + '-' + fk, at: at(fd, 19, fk * 4), perHour: 8 + fk * 0.8 }));
    }
    fruns.push([at(fd, 18, 0), at(fd, 21, 59)]);
    if (i < 3) fruns.push([at(fd, 22, 0), at(fd, 22, 30)]);           // Friday 10pm: 1.5 h on three nights
  });
  for (var tk = 0; tk < 12; tk++) flo.push(offer({ id: 'p10-' + tk, at: at([6, 13, 20][tk % 3], 22, tk), perHour: 60 }));
  var floRows = T.readRows(T.rowsOf(flo));
  // For the quantiles the two high cells must be a small part of the range
  // (a range P90 sits among them otherwise): eleven hundred ordinary offers
  // on the other weeknights, $8-$20.
  var filler = [];
  for (var fi = 0; fi < 1100; fi++) {
    filler.push(offer({ id: 'fl' + fi, at: at(2 + (fi % 4) + 7 * Math.floor(fi / 275) % 28, 18 + (fi % 3), Math.floor(fi / 4) % 60),
                        perHour: 8 + (fi % 25) * 0.5 }));
  }
  var qRows = T.readRows(T.rowsOf(flo.concat(filler)));
  var g90 = T.grid(qRows, { stat: 'p90' });
  var gc = function (gg, dow, hour) { return gg.cells.filter(function (c) { return c.dow === dow && c.hour === hour; })[0]; };
  eq('P90: a cell of 60 offers well above is shaded; one of 40, as far above, stays grey (no top rank under 51)',
     [gc(g90, 5, 20).n, gc(g90, 5, 20).shade, gc(g90, 5, 21).n, gc(g90, 5, 21).enough, gc(g90, 5, 21).noRanks,
      gc(g90, 5, 21).shade], [60, 'above', 40, false, true, null]);
  eq('...while its median, from the same 40, is shaded (a median\'s interval needs 8)',
     gc(T.grid(qRows, { stat: 'p50' }), 5, 21).shade, 'above');
  // Good per hour online against a fixed $30 line (the ruler's own sums are
  // held above): 8pm and 9pm and the 10pm $60s are good, 6pm and 7pm never.
  var cutF = 30;
  var gg = T.grid(floRows, { stat: 'goodRate', cut: cutF, runs: fruns });
  eq('good per hour online: 8pm\'s 15 an hour is shaded above the range, 6pm\'s none is below',
     [gc(gg, 5, 20).value, gc(gg, 5, 20).hours, gc(gg, 5, 20).shade, gc(gg, 5, 18).good, gc(gg, 5, 18).shade],
     [15, 4, 'above', 0, 'below']);
  eq('...a cell with 1.5 hours online on three nights is under the floor however good (12 good, 8 an hour)',
     [gc(gg, 5, 22).hours, gc(gg, 5, 22).days, gc(gg, 5, 22).good, gc(gg, 5, 22).enough, gc(gg, 5, 22).shade],
     [1.5, 3, 12, false, null]);
  var gg2 = T.grid(floRows, { stat: 'goodRate', cut: cutF, runs: fruns.slice(0, 2) });
  eq('...and one Friday alone (an hour a cell) is under it everywhere', gg2.cells.filter(function (c) { return c.enough; }).length, 0);
  // With no effect, 300 cells on four nights each, every night's rate drawn
  // with a 40% swing: the widened interval shades about 1 in 100 or fewer.
  var r6 = rng(17), noFx = [], noShaded = 0;
  for (var nc = 0; nc < 300; nc++) {
    var nights = [];
    for (var nn = 0; nn < 4; nn++) {
      var lam = 6 * Math.max(0.1, 1 + 0.4 * (r6() + r6() + r6() - 1.5) * 2), kk = 0, L0 = Math.exp(-lam), pp = 1;
      do { kk++; pp *= r6(); } while (pp > L0);
      nights.push({ k: kk - 1, h: 1 });
    }
    noFx.push(nights);
  }
  var phiNo = T.dispersion(noFx);
  noFx.forEach(function (ns) {
    var K = ns.reduce(function (a, x) { return a + x.k; }, 0);
    if (T.rateShade(K, 4, 6, phiNo).shade) noShaded += 1;
  });
  ok('...with no effect and a 40% night-to-night swing, phi ' + phiNo.toFixed(2) + ' keeps chance shading low ('
     + noShaded + ' of 300)', phiNo > 1.3 && noShaded <= 9);

  /* --- unpack's clock, worked once per day and hour (the reporting review's T5) --- */
  (function () {
    var rr = [];
    // Every 7 minutes across both clock changes of 2026-27, and a row out of order.
    [[new Date(2026, 9, 31, 20).getTime(), new Date(2026, 10, 1, 8).getTime()],
     [new Date(2027, 2, 13, 20).getTime(), new Date(2027, 2, 14, 8).getTime()]].forEach(function (sp) {
      for (var t = sp[0]; t <= sp[1]; t += 7 * 60000) rr.push({ t: t, app: 1, pay: 5, perHour: 20, minutes: 15, miles: 3, flags: 1 });
    });
    rr.push({ t: new Date(2026, 10, 1, 1, 30).getTime(), app: 1, pay: 5, perHour: 20, minutes: 15, miles: 3, flags: 1 });
    var got = T.readRows(rr), bad = 0;
    got.forEach(function (r) {
      var day = T.dayKeyOf(r.t), d = new Date(r.t);
      if (r.day !== day || r.hour !== d.getHours() || r.week !== T.weekKeyOf(day) || r.month !== day.slice(0, 7)
          || r.dow !== new Date(Number(day.slice(0, 4)), Number(day.slice(5, 7)) - 1, Number(day.slice(8, 10)), 12).getDay()) bad += 1;
    });
    eq('T5: a day and hour worked once and reused give each row its own clock, across both changes and out of order',
       [got.length, bad], [rr.length, 0]);
  }());

  /* --- a quantile's interval and the nights (the reporting review's S1) --- */
  eq('S1: at phi_q 1 the widened interval is the plain one; at 2 its ranks are n=30\'s scaled onto 60 (8 -> 16, 23 -> 46)',
     [T.quantCIw(Array.from({ length: 60 }, function (_, i) { return i + 1; }), 0.5, 0.01, 1),
      T.quantRanks(30, 0.5, 0.01),
      T.quantCIw(Array.from({ length: 60 }, function (_, i) { return i + 1; }), 0.5, 0.01, 2)],
     [T.quantCI(Array.from({ length: 60 }, function (_, i) { return i + 1; }), 0.5, 0.01), [8, 23], [16, 46]]);
  eq('S1: rho_q by hand: one group, two above in one night and none in the other (S 8, A 2, B 2: 3) is capped at 1; '
     + 'nights alike are 0; and the design effect 1 + (m - 1) rho with m = sum n^2 / sum n',
     [T.qRho([[[20, 20], [5, 5]]], 10), T.qRho([[[5, 20], [5, 20]], [[20, 5], [20, 5]]], 10),
      T.qPhiOf([10, 30], 0.1)], [1, 0, 3.4000000000000004]);
  // 300 no-effect cells on four nights of 12 offers, the owner's spread
  // around $13.95, each night's whole hour shifted by a 20% swing in log
  // $/hr: the plain interval shades by chance far past 1 in 100, the
  // widened one about 1 in 100 or fewer.
  var r7 = rng(29), qCells = [];
  function nz() { var u = 0; while (!u) u = r7(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * r7()); }
  for (var qc = 0; qc < 300; qc++) {
    var qn = [];
    for (var qd = 0; qd < 4; qd++) {
      var sh = 0.2 * nz(), vs = [];
      for (var qo = 0; qo < 12; qo++) vs.push(13.95 * Math.exp(0.398 * nz() + sh));
      qn.push(vs);
    }
    qCells.push(qn);
  }
  var rhoQ = T.qRho(qCells, 13.95), plainQ = 0, wideQ = 0;
  qCells.forEach(function (ns) {
    var all = [].concat.apply([], ns);
    if (T.shadeQ(all, 4, 13.95, 0.5, 2).shade) plainQ += 1;
    if (T.shadeQ(all, 4, 13.95, 0.5, 2, T.qPhiOf(ns.map(function (v) { return v.length; }), rhoQ)).shade) wideQ += 1;
  });
  ok('S1: with no effect and a 20% night swing, rho_q ' + rhoQ.toFixed(3) + ' keeps the medians\' chance shading low ('
     + wideQ + ' of 300; ' + plainQ + ' unwidened)', rhoQ > 0.05 && wideQ <= 6 && plainQ >= 15);

  // Ties at the cut count as good: five offers at $20 among ten, top 20%.
  var tieR = T.ruler(T.readRows(T.rowsOf([1, 2, 3, 4, 5, 20, 20, 20, 20, 20].map(function (v, i) {
    return offer({ id: 'tie' + i, at: at(2, 19, i), perHour: v });
  }))), 20);
  eq('S8: ties at the cut are good, and counted: a $20 cut over ten offers calls 5 of them good, and says so',
     [tieR.cut, tieR.over, tieR.n], [20, 5, 10]);

  /* --- earned net with a take that lost money (the reporting review's S4) --- */
  // 300 evenings, a take an hour; in Saturday's 7pm hour the takes alternate
  // $60 over 20 mi (+$46 net at $0.70/mi) and $5 over 57 mi (-$34.90): the
  // interval weighs the loser as 0 and drew "above" at $6.49 against $11.80.
  (function () {
    var rr = [], sp = [], flip = 0;
    for (var d = 0; d < 300; d++) {
      var day = new Date(2026, 6, 1 + d), a0 = new Date(day.getFullYear(), day.getMonth(), day.getDate(), 18).getTime();
      sp.push([a0, a0 + 4 * 3.6e6]);
      for (var t = a0, i = 0; t <= a0 + 4 * 3.6e6; t += 600000, i++) {
        var take = i % 6 === 3, dt = new Date(t), sat = dt.getDay() === 6 && dt.getHours() === 19, pay = 12, miles = 0;
        if (sat && take) { flip ^= 1; pay = flip ? 60 : 5; miles = flip ? 20 : 57; }
        rr.push({ t: t, app: 2, pay: pay, perHour: 20, minutes: 20, miles: miles, flags: 1 | (take ? 128 : 0) });
      }
    }
    var G = T.grid(T.readRows(rr), { stat: 'earned', runs: sp, cut: 30, net: true, costPerMile: 0.7 });
    var c = G.cells.filter(function (x) { return x.dow === 6 && x.hour === 19; })[0];
    eq('S4: a cell holding a take that paid less than its miles cost is printed and never shaded, and counted',
       [c.value < G.ref, c.clamped, c.enough, c.shade, c.ci, G.clamped >= 1], [true, true, true, null, null, true]);
  }());

  /* --- the calendar as week rows --- */
  var cw = [];
  ['2026-02-26', '2026-02-27', '2026-03-03', '2026-03-10', '2026-03-12'].forEach(function (dk, i) {
    var p = dk.split('-').map(Number);
    for (var ck2 = 0; ck2 < 5; ck2++) {
      cw.push(offer({ id: 'cw' + i + '-' + ck2, at: new Date(p[0], p[1] - 1, p[2], 19, ck2).getTime(), perHour: 10 + i * 5 + ck2 }));
    }
  });
  var calW = T.calendar(T.readRows(T.rowsOf(cw)), [], { stat: 'p75', cut: 20 });
  eq('the calendar\'s rows are weeks, Monday to Sunday, first to last, the month named where one starts',
     calW.weeks.map(function (w) { return [w.week, w.days[0], w.days[6], w.month]; }),
     [['2026-02-23', '2026-02-23', '2026-03-01', '2026-02'], ['2026-03-02', '2026-03-02', '2026-03-08', null],
      ['2026-03-09', '2026-03-09', '2026-03-15', null]]);
  eq('...each week its own figure pooled over its offers, with its n (P75 of $10-$19 is $16.75)',
     calW.weeks.map(function (w) { return [w.n, w.counted, w.value]; }), [[10, 10, 16.75], [5, 5, 23], [10, 10, 31.75]]);
  eq('...a week starting on a 1st is labelled with it', T.calendar(T.readRows(T.rowsOf([offer({ id: 'j1', at: new Date(2026, 5, 1, 19).getTime() })])),
     []).weeks[0].month, '2026-06');
  eq('...and this month so far against the month before, each with its n',
     [calW.months.now.month, calW.months.now.n, calW.months.now.through, calW.months.before.month, calW.months.before.n],
     ['2026-03', 15, '2026-03-12', '2026-02', 10]);

  /* --- a cell looked at closely, and only figures in it --- */
  var dr = [offer({ id: 'd1', at: at(6, 20, 1), perHour: 30, app: 'uber', accepted: true }),
            offer({ id: 'd2', at: at(6, 20, 5), perHour: 12, app: 'doordash', accepted: false }),
            offer({ id: 'd3', at: at(13, 20, 9), perHour: 25, app: 'doordash' }),
            offer({ id: 'd4', at: at(13, 20, 20), perHour: 18, app: 'uber', suspect: true }),
            offer({ id: 'd5', at: at(13, 21, 0), perHour: 50, app: 'uber', accepted: true })];
  dr.push({ v: 1, kind: 'mark', id: 'd3', at: at(13, 20, 30), accepted: true });
  var drRows = T.readRows(T.rowsOf(dr));
  eq('a take is only the driver\'s own tick: true is taken, false and no answer are not, a mark row is no offer',
     drRows.map(function (r) { return r.taken; }), [true, false, false, false, true]);
  var cd = T.cellDetail(drRows, [[at(6, 20, 0), at(6, 21, 0)], [at(13, 20, 0), at(13, 20, 30)]], 5, 20,
                        { stat: 'p50', cut: 20 });
  eq('the cell: its money offers as dots ($/hr, taken, app), the suspect one counted but not drawn',
     [cd.offers, cd.n, cd.dots, cd.taken, cd.good, cd.hours], [4, 3, [[30, 1, 1], [12, 0, 2], [25, 0, 2]], 1, 2, 1.5]);
  eq('...the two apps apart, its quantiles, and the best by $/hr first',
     [cd.apps.uber.n, cd.apps.doordash.n, cd.apps.doordash.value, cd.p50, cd.best.map(function (b) { return b.perHour; })],
     [1, 2, 18.5, 25, [30, 25, 12]]);
  eq('...each best offer says pay, minutes, miles, app and when, and nothing else',
     Object.keys(cd.best[0]).sort(), ['app', 'day', 'miles', 'minutes', 'pay', 'perHour', 't', 'taken']);
  eq('...and its figure week by week', cd.weeks.map(function (w) { return [w.week, w.n, w.value]; }),
     [['2026-03-02', 2, 21], ['2026-03-09', 1, 25]]);
  var cdg = T.cellDetail(drRows, [[at(6, 20, 0), at(6, 21, 0)], [at(13, 20, 0), at(13, 20, 30)]], 5, 20,
                         { stat: 'goodRate', cut: 20 });
  eq('...in good per hour online: 2 good over its 1.5 hours, week by week over each week\'s own hours',
     [cdg.value, cdg.weeks.map(function (w) { return [w.good, w.hours, w.value]; })], [1.33, [[1, 1, 1], [1, 0.5, 2]]]);
  ok('...and nothing in it, or in the packed rows, is text, a place or a position',
     !/lat|lon|pickup|dropoff|text|address|"id"/.test(JSON.stringify(cd) + JSON.stringify(T.pack(T.rowsOf(dr)))));
  eq('the packed rows are still seven columns; a take is a bit in the flags', [Object.keys(T.pack(T.rowsOf(dr)).cols),
     T.pack(T.rowsOf(dr)).cols.flags.map(function (f) { return f & T.F_TAKEN ? 1 : 0; })],
     [['t', 'app', 'pay', 'perHour', 'minutes', 'miles', 'flags'], [1, 0, 0, 0, 1]]);

  /* --- the hour of day in each figure --- */
  var hp = T.hourly(qRows, { stat: 'p90' }), hg = T.hourly(floRows, { stat: 'goodRate', cut: cutF, runs: fruns });
  var hAt = function (list, h) { return list.filter(function (e) { return e.hour === h; })[0]; };
  eq('the hour chart in P90 and in good per hour online, with the same floors as the grid',
     [hAt(hp, 20).value !== null, hAt(hp, 20).enough, hAt(hp, 21).enough, hAt(hg, 20).value, hAt(hg, 20).enough,
      hAt(hg, 22).enough], [true, true, false, 15, true, false]);

  /* === Round three: earned per hour (gross and net), the wait for a good
     offer, the app share, off against quiet, the timeline, B against A,
     month thirds and one weekday over the weeks === */

  /* --- a take, gross and net --- */
  var tk = T.readRows(T.rowsOf([
    offer({ id: 't1', at: at(6, 20, 1), pay: 20, miles: 5, perHour: 40, accepted: true }),
    offer({ id: 't2', at: at(6, 20, 9), pay: 12, miles: 4, perHour: 24 }),
    offer({ id: 't3', at: at(6, 20, 20), pay: 30, miles: 8, perHour: 60, accepted: true, suspect: true }),
    offer({ id: 't4', at: at(6, 20, 40), pay: 18, miles: 6, perHour: 36, accepted: true, milesUncertain: true })]));
  eq('a take: the card\'s pay, net of miles x the one cost per mile; untaken is none; an unread pay is unpaid; no miles is noted',
     tk.map(function (r) { return T.takeOf(r, 0.5); }),
     [{ e: 17.5, noMiles: false }, null, { unpaid: true }, { e: 18, noMiles: true }]);
  eq('...and gross (no cost per mile known) takes nothing off', T.takeOf(tk[0], null), { e: 20, noMiles: false });

  /* --- the weighted-Poisson interval, hand-worked --- */
  var ec = T.earnCI(10, 10, 1, 1, 0.01), ez = T.earnCI(0, 0, 12, 1, 0.01), e2 = T.earnCI(10, 10, 1, 2, 0.01);
  eq('earned interval: every weight 1 is the Garwood interval ([3.72, 21.40] at 10); no take is [0, 5.30 x the mean take]',
     [Math.round(ec[0] * 100) / 100, Math.round(ec[1] * 100) / 100, ez[0], Math.round(ez[1] * 100) / 100],
     [3.72, 21.4, 0, 63.58]);
  eq('...widened by phi 2, its lower end is 2 x the Garwood lower end of 10/2 (2 x 1.08 = 2.16)',
     Math.round(e2[0] * 100) / 100, Math.round(2 * T.poisCI(5, 0.01)[0] * 100) / 100);
  eq('Clopper-Pearson on a share, hand-worked: 5 of 10 at 95% is [0.1871, 0.8129]; 0 of 10 is [0, 0.3085]',
     T.shareCI(5, 10, 0.05).concat(T.shareCI(0, 10, 0.05)).map(function (v) { return Math.round(v * 10000) / 10000; }),
     [0.1871, 0.8129, 0, 0.3085]);

  /* --- earned per hour on the grid: floors, shading, net --- */
  // Friday 8pm on two Fridays, an hour online each: two $20 takes (5 mi) a
  // night and an untaken $12; Tuesday 8pm, two nights, one $10 take a night.
  // Friday 9pm: 1.75 h on two nights. Friday 10pm: 1.25 h on two nights.
  // Seven hours online in all, $160 taken: the range's own $22.86 an hour.
  var er = [], eruns = [];
  [6, 13].forEach(function (fd) {
    er.push(offer({ id: 'ea' + fd, at: at(fd, 20, 5), pay: 20, miles: 5, perHour: 40, accepted: true }));
    er.push(offer({ id: 'eb' + fd, at: at(fd, 20, 25), pay: 20, miles: 5, perHour: 40, accepted: true }));
    er.push(offer({ id: 'ec' + fd, at: at(fd, 20, 45), pay: 12, miles: 4, perHour: 18 }));
    er.push(offer({ id: 'ed' + fd, at: at(fd, 21, 5), pay: 20, miles: 5, perHour: 40, accepted: true }));
    eruns.push([at(fd, 20, 0), fd === 6 ? at(fd, 21, 45) : at(fd, 22, 15)]);
  });
  [3, 10].forEach(function (td) {
    er.push(offer({ id: 'et' + td, at: at(td, 20, 10), pay: 10, miles: 5, perHour: 20, accepted: true }));
    eruns.push([at(td, 20, 0), at(td, 21, 0)]);
  });
  eruns.push([at(20, 22, 0), at(20, 23, 0)]);
  er.push(offer({ id: 'ee', at: at(20, 22, 5), pay: 20, miles: 5, perHour: 40, accepted: true }));
  var erRows = T.readRows(T.rowsOf(er));
  var eg = T.grid(erRows, { stat: 'earned', runs: eruns, cut: 30 });
  var egn = T.grid(erRows, { stat: 'earned', runs: eruns, cut: 30, net: true, costPerMile: 0.5 });
  var egx = T.grid(erRows, { stat: 'earned', runs: eruns, cut: 30, net: true });
  var c8e = gc(eg, 5, 20), c9e = gc(eg, 5, 21), c10e = gc(eg, 5, 22), t8e = gc(eg, 2, 20);
  eq('earned/hr: Friday 8pm is four $20 takes over 2 h online on 2 nights, $40 an hour gross, the untaken offer not in it',
     [c8e.takes, c8e.earned, c8e.hours, c8e.onlineDays, c8e.value, c8e.enough], [4, 80, 2, 2, 40, true]);
  eq('...net of $0.50/mi takes $2.50 off each take ($35 an hour); asked for net with no cost per mile, it stays gross and says so',
     [gc(egn, 5, 20).value, egn.net, gc(egx, 5, 20).value, egx.net], [35, true, 40, false]);
  eq('...under the floor: 1.75 h on two nights, and 1.25 h on two nights',
     [c9e.hours, c9e.onlineDays, c9e.enough, c9e.shade, c10e.hours, c10e.onlineDays, c10e.enough],
     [1.75, 2, false, null, 1.25, 2, false]);
  // Two and a half hours on one day (a slice table built by hand: a clock
  // hour holds an hour a night, so only pooled days can) is under the days
  // half of the floor; 2 h on 2 days is at it.
  function slc(day, h) { return { day: day, hours: h, rows: [], good: 0, takes: 0, earned: 0, y: 0, v: 0, unpaid: 0, noMiles: 0 }; }
  var ectx = { stat: 'earned', ref: 10, wMean: 10 };
  eq('...and 2.5 h on one day is under it, 2 h on two days at it',
     [T.poolCell([slc('2026-03-06', 2.5)], ectx).enough, T.poolCell([slc('2026-03-06', 1), slc('2026-03-13', 1)], ectx).enough],
     [false, true]);
  eq('...Tuesday\'s $10 an hour, at the floor, is printed, against the range\'s own $22.86',
     [t8e.value, t8e.enough, eg.ref], [10, true, 22.86]);
  // A cell with no take at all over 2 h on 2 nights is NOT shaded below: its
  // upper end is 5.30 mean takes ($18.57 here) over 2 h. A bootstrap over its
  // two nights would be [0, 0] and shade it below with certainty.
  var zeroCell = T.earnShade(0, 0, 2, eg.ref, eg.wMean, 1);
  eq('...and a cell with no take in 2 h on 2 nights is not shaded below: its interval reaches $' + Math.round(zeroCell.ci[1]),
     [eg.wMean, zeroCell.shade, zeroCell.ci[0], zeroCell.ci[1] > eg.ref], [17.78, null, 0, true]);
  var unpaidRows = T.readRows(T.rowsOf(er.concat([offer({ id: 'eu', at: at(6, 20, 50), pay: 50, perHour: 99,
                                                           accepted: true, suspect: true })])));
  eq('...a take whose pay was not trusted adds nothing and is counted as unpaid',
     [gc(T.grid(unpaidRows, { stat: 'earned', runs: eruns, cut: 30 }), 5, 20).value,
      T.grid(unpaidRows, { stat: 'earned', runs: eruns, cut: 30 }).unpaid], [40, 1]);
  eq('...the hour chart and the calendar read earned the same way',
     [T.hourly(erRows, { stat: 'earned', runs: eruns, cut: 30 }).filter(function (e) { return e.hour === 20; })[0].value,
      T.calendar(erRows, eruns, { stat: 'earned', cut: 30 }).days.filter(function (d) { return d.day === '2026-03-06'; })[0].earned],
     [25, 60]);

  /* --- the wait for a good offer --- */
  eq('a good offer about every N minutes: 60 x hours / good, at the good floor; under it none said; no good at all said so',
     [c8e.good, c8e.waitMin, c9e.waitMin, c9e.timeOk, gc(eg, 2, 20).waitNone, gc(eg, 2, 20).waitMin],
     [4, 30, null, false, true, null]);
  var calW8 = T.calendar(erRows, eruns, { stat: 'goodRate', cut: 30 }).days;
  eq('...a calendar tile: one day at 2 hours (the 6th, 1.75 h: too little; the 13th, 2.25 h and three good: every 45 min)',
     calW8.filter(function (d) { return d.day === '2026-03-06' || d.day === '2026-03-13'; })
       .map(function (d) { return [d.day, d.hours, d.waitMin, d.waitNone]; }),
     [['2026-03-06', 1.75, null, false], ['2026-03-13', 2.25, 45, false]]);

  /* --- which app brings the good offers --- */
  var ap = [];
  for (var ai = 0; ai < 14; ai++) ap.push(offer({ id: 'ap' + ai, at: at(6, 19, ai * 4), perHour: 40, app: ai < 10 ? 'uber' : 'doordash' }));
  ap.push(offer({ id: 'apn', at: at(6, 19, 58), perHour: 40, app: null }));
  ap.push(offer({ id: 'apl', at: at(6, 18, 1), perHour: 40, app: 'doordash' }));
  ap.push(offer({ id: 'apx', at: at(6, 19, 59), perHour: 10, app: 'doordash' }));
  var apRows = T.readRows(T.rowsOf(ap)), share = T.goodAppShare(apRows, 30);
  var s19 = share.filter(function (e) { return e.hour === 19; })[0], s18 = share.filter(function (e) { return e.hour === 18; })[0];
  eq('good offers by app: 7pm has 10 Uber, 4 DoorDash, 1 app unknown, the $10 one not good: 71% Uber',
     [s19.uber, s19.doordash, s19.unknown, s19.enough, s19.uberShare], [10, 4, 1, true, 0.71]);
  eq('...an hour with one good offer prints no share', [s18.good, s18.enough], [1, false]);
  var apc = T.cellDetail(apRows, [[at(6, 19, 0), at(6, 20, 0)]], 5, 19, { stat: 'goodRate', cut: 30 });
  eq('...and the looked-at cell says the same', apc.goodApps, { uber: 10, doordash: 4, unknown: 1 });

  /* --- off is not quiet --- */
  var oq = T.grid(T.readRows(T.rowsOf([offer({ id: 'oq', at: at(6, 20, 10), perHour: 20 })])),
                  { stat: 'p50', runs: [[at(6, 20, 0), at(6, 20, 30)], [at(7, 22, 0), at(7, 23, 0)]] });
  eq('off against quiet: Friday 8pm had a card; Saturday 10pm was online an hour and saw none (quiet, not off); '
     + 'Sunday 8pm had neither (off)',
     [gc(oq, 5, 20).off, gc(oq, 6, 22).off, gc(oq, 6, 22).hours, gc(oq, 6, 22).n, gc(oq, 0, 20).off],
     [false, false, 1, 0, true]);
  eq('...in every figure', ['goodRate', 'earned', 'p90'].map(function (s) {
    var g3 = T.grid(T.readRows(T.rowsOf([offer({ id: 'oq', at: at(6, 20, 10), perHour: 20 })])),
                    { stat: s, runs: [[at(7, 22, 0), at(7, 23, 0)]] });
    return [gc(g3, 6, 22).off, gc(g3, 0, 20).off];
  }), [[false, true], [false, true], [false, true]]);

  /* --- the timeline: days, weeks across Monday 4am, the 1 Nov clock change --- */
  // A run from Sunday-night 3am to Monday 5am (March 2026: Monday the 9th).
  var wkRuns = [[at(9, 3, 0), at(9, 5, 0)]];
  var tlw = T.timeline([], wkRuns, { stat: 'goodRate', by: 'week' });
  eq('a run across Monday 4am: its 3am hour in the week before (Mar 2), its 4am hour in the new week (Mar 9), newest first',
     tlw.rows.map(function (r) {
       return [r.key, r.cells.filter(function (c) { return c.hours > 0; }).map(function (c) { return [c.hour, c.hours]; })];
     }), [['2026-03-09', [[4, 1]]], ['2026-03-02', [[3, 1]]]]);
  var tld = T.timeline([], wkRuns, { stat: 'p50', by: 'day' });
  eq('...by days: Sunday the 8th holds 3am, Monday the 9th holds 4am, every other square off',
     [tld.rows.map(function (r) { return r.key; }), tld.rows[1].cells.filter(function (c) { return !c.off; }).length,
      tld.rows[0].cells.filter(function (c) { return !c.off; }).length], [['2026-03-09', '2026-03-08'], 1, 1]);
  // 1 Nov 2026: the clocks go back at 2am, so 1am happens twice. A run from
  // 11:30pm Saturday to 3:30am is five hours, and its 1am square holds two.
  var dst = [[new Date(2026, 9, 31, 23, 30).getTime(), new Date(2026, 10, 1, 3, 30).getTime()]];
  var tlx = T.timeline([], dst, { stat: 'goodRate', by: 'day' });
  var oct31 = tlx.rows.filter(function (r) { return r.key === '2026-10-31'; })[0];
  eq('the 1 Nov clock change: five hours, all on Saturday\'s driver day, the doubled 1am square holding two',
     [tlx.rows.length, oct31.hours, oct31.cells.filter(function (c) { return c.hour === 1; })[0].hours,
      oct31.cells.filter(function (c) { return c.hour === 23; })[0].hours], [1, 5, 2, 0.5]);
  eq('...and by weeks it is in the week of Monday 26 Oct, by months in October',
     [T.timeline([], dst, { by: 'week' }).rows[0].key, T.timeline([], dst, { by: 'month' }).rows[0].key,
      T.timeline([], dst, { by: 'month' }).rows[0].to], ['2026-10-26', '2026-10', '2026-10-31']);
  // Pooled squares use the grid's rules, so a single day-hour never meets
  // the 2-day floor, while a month of Friday 8pms can.
  var tlq = T.timeline(qRows, [], { stat: 'p50', by: 'day' });
  ok('...one day-hour is never shaded (30 offers on 2 days cannot fit in one hour of one night)',
     tlq.rows.every(function (r) { return r.cells.every(function (c) { return !c.enough && !c.shade; }); }));
  var tlqw = T.timeline(floRows, [], { stat: 'p50', by: 'month' });
  var mar20 = tlqw.rows[0].cells.filter(function (c) { return c.hour === 20; })[0];
  eq('...while a month pools its four Friday 8pms (60 offers at $40, the only 8pm offers in that record) and is shaded above',
     [mar20.n, mar20.days, mar20.enough, mar20.shade], [60, 4, true, 'above']);
  var cdd = T.cellDetail(drRows, [[at(6, 20, 0), at(6, 21, 0)], [at(13, 20, 0), at(13, 20, 30)]], null, 20,
                         { stat: 'p50', cut: 20, from: '2026-03-13', to: '2026-03-13' });
  eq('a timeline square pressed: the cell panel for that date and hour only (the 13th, 8pm: one offer counted, half an hour)',
     [cdd.offers, cdd.n, cdd.hours, cdd.from, cdd.dow], [2, 1, 0.5, '2026-03-13', null]);

  /* --- B against A --- */
  // No difference: the same draw in both periods, many cells, every
  // weekday's 6-9pm on two four-week periods.
  var r7 = rng(23), na = [], nruns = [];
  for (var nd = 2; nd <= 29; nd++) {
    for (var nh = 16; nh <= 23; nh++) {
      for (var nk = 0; nk < 24; nk++) {
        na.push(offer({ id: 'n' + nd + '-' + nh + '-' + nk, at: at(nd, nh, Math.floor(nk * 2.5)),
                        perHour: Math.exp(Math.log(16) + 0.37 * (r7() + r7() + r7() - 1.5) * 2),
                        accepted: r7() < 0.1 }));
      }
    }
    nruns.push([at(nd, 16, 0), at(nd + 1, 0, 0)]);
  }
  var naRows = T.readRows(T.rowsOf(na)), pA = { from: '2026-03-02', to: '2026-03-15' }, pB = { from: '2026-03-16', to: '2026-03-29' };
  var nullShaded = 0, nullCells = 0;
  ['p50', 'p90', 'goodRate', 'earned'].forEach(function (s) {
    T.gridCompare(naRows, nruns, pA, pB, { stat: s, cut: 22 }).cells.forEach(function (c) {
      if (c.enough) nullCells += 1;
      if (c.shade) nullShaded += 1;
    });
  });
  ok('B vs A with no difference: ' + nullShaded + ' of ' + nullCells + ' compared cells shaded across four figures (under 1%)',
     nullCells >= 200 && nullShaded <= Math.floor(nullCells / 100));
  var dense = [], druns = [];
  for (var dd = 2; dd <= 29; dd++) {
    if (new Date(2026, 2, dd).getDay() !== 5) continue;
    for (var dk2 = 0; dk2 < 40; dk2++) {
      dense.push(offer({ id: 'dn' + dd + '-' + dk2, at: at(dd, 20, dk2), perHour: 15 + (dk2 % 10) + (dd >= 16 ? 10 : 0) }));
    }
    druns.push([at(dd, 20, 0), at(dd, 21, 0)]);
  }
  var thinD = T.readRows(T.rowsOf(dense.filter(function (o, i) { return i % 40 < 12; })));
  var gT = T.gridCompare(thinD, druns, pA, pB, { stat: 'p50', cut: 30 });
  eq('B vs A: B minus A per cell, and with both sides under the floor (24 offers a side) nothing is shaded however far apart',
     [gc(gT, 5, 20).a.n, gc(gT, 5, 20).b.n, gc(gT, 5, 20).diff, gc(gT, 5, 20).enough, gc(gT, 5, 20).shade],
     [24, 24, 10, false, null]);
  var gD = T.gridCompare(T.readRows(T.rowsOf(dense)), druns, pA, pB, { stat: 'p50', cut: 30 });
  eq('...80 offers a side, B $10 higher: compared, shaded above, B - A = $10',
     [gc(gD, 5, 20).a.n, gc(gD, 5, 20).b.n, gc(gD, 5, 20).enough, gc(gD, 5, 20).shade, gc(gD, 5, 20).diff],
     [80, 80, true, 'above', 10]);
  var gG = T.gridCompare(T.readRows(T.rowsOf(dense)), druns, pA, pB, { stat: 'goodRate', cut: 30 });
  eq('...in good per hour: A none good, B 40 good in 2 h: the exact ratio test shades above',
     [gc(gG, 5, 20).a.good, gc(gG, 5, 20).b.good, gc(gG, 5, 20).shade, gc(gG, 5, 20).ciIs], [0, 40, 'above', 'ratio']);

  /* --- month thirds --- */
  function thirdsRows(months) {
    var out = [], rr = [];
    months.forEach(function (mo) {
      [3, 5, 8, 12, 14, 17, 22, 24, 27].forEach(function (dm) {
        for (var k3 = 0; k3 < 20; k3++) {
          out.push(offer({ id: 'th' + mo + '-' + dm + '-' + k3, at: new Date(2026, mo, dm, 19, k3 * 2).getTime(),
                           perHour: dm > 20 ? 40 + k3 * 0.1 : 10 + k3 }));
        }
        rr.push([new Date(2026, mo, dm, 19, 0).getTime(), new Date(2026, mo, dm, 19, 59).getTime()]);
      });
    });
    return { rows: T.readRows(T.rowsOf(out)), runs: rr };
  }
  var th2 = thirdsRows([5, 6]), th3 = thirdsRows([5, 6, 7]);
  var mt2 = T.monthThirds(th2.rows, th2.runs, { stat: 'p50' }), mt3 = T.monthThirds(th3.rows, th3.runs, { stat: 'p50' });
  eq('month thirds over two months: printed with n, days and months, and shaded nowhere (each third needs three months)',
     [mt2.gated, mt2.thirds.map(function (e) { return [e.label, e.n, e.dates, e.months, e.shade]; })],
     [false, [['1–10', 120, 6, 2, null], ['11–20', 120, 6, 2, null], ['21–end', 120, 6, 2, null]]]);
  eq('...over three months the 21st-to-end third, far above, is shaded',
     [mt3.gated, mt3.thirds[2].months, mt3.thirds[2].shade, mt3.thirds[0].shade], [true, 3, 'above', 'below']);
  eq('...and a month\'s last days go to the last third whatever its length (the 31st, the 28th)',
     [T.monthThirds(T.readRows(T.rowsOf([offer({ id: 'x31', at: new Date(2026, 6, 31, 19).getTime() })])), [], {}).thirds[2].offers],
     [1]);

  /* --- one weekday over the weeks --- */
  var swr = T.sameWeekday(erRows, eruns, 5, { cut: 30 });
  eq('one weekday over the weeks: every Friday from the first to the last, off ones said, each with its figures',
     swr.days.map(function (d) { return [d.day, d.off, d.offers, d.hours, d.takes, d.earnedRate, d.goodRate, d.rateThin]; }),
     // The 6th: $60 of takes over 1.75 h; the 13th: $60 over 2.25 h, at the
     // 2-hour mark; the 20th: one $20 take in an hour.
     [['2026-03-06', false, 4, 1.75, 3, 34.29, 1.71, true], ['2026-03-13', false, 4, 2.25, 3, 26.67, 1.33, false],
      ['2026-03-20', false, 1, 1, 1, 20, 1, true]]);
  eq('...a P90 over fewer than ' + T.DAY_MIN + ' offers is thin', swr.days[0].p90Thin, true);
  var swOff = T.sameWeekday(erRows, eruns, 2, { cut: 30 });
  eq('...Tuesdays: the 3rd and 10th on, the 17th off (nothing that day, within the range)',
     swOff.days.map(function (d) { return [d.day, d.off]; }), [['2026-03-03', false], ['2026-03-10', false], ['2026-03-17', true]]);

  /* --- the hour chart, one period at a time (compare mode) --- */
  var hA = T.hourly(naRows, { stat: 'p50', period: pA }).filter(function (e) { return e.hour === 19; })[0];
  eq('the hour chart for one period: only its days', [hA.offers, hA.days], [24 * 14, 14]);

  /* --- the week in review ----------------------------------------------------
   * Weeks are Monday 4am to Monday 4am; every figure is the slice table's. */
  function nov(d, h, m) { return new Date(2026, 10, d, h, m || 0).getTime(); }
  function oct(d, h, m) { return new Date(2026, 9, d, h, m || 0).getTime(); }
  eq('a driver week\'s span: 169 hours the week holding 1 Nov (1am twice), 167 the one holding 8 Mar, 168 otherwise',
     ['2026-10-26', '2026-03-02', '2026-03-16'].map(function (k) {
       var s = T.weekSpanMs(k);
       return (s[1] - s[0]) / 3.6e6;
     }), [169, 167, 168]);
  eq('...from Monday 4am', new Date(T.weekSpanMs('2026-10-26')[0]).getHours(), 4);
  // Runs: Saturday 31 Oct 11:30pm to 3:30am across the change (five hours),
  // Monday 2 Nov 3am to 5am (its 3am hour the week before's), and 16 Nov;
  // the week of 9 Nov off.
  var wkRuns2 = [[oct(31, 23, 30), nov(1, 3, 30)], [nov(2, 3, 0), nov(2, 5, 0)], [nov(16, 18, 0), nov(16, 20, 0)]];
  var wkRows2 = T.readRows(T.rowsOf([offer({ id: 'w1', at: oct(20, 19, 0) }), offer({ id: 'w2', at: nov(16, 19, 0) })]));
  eq('stepping weeks across the 1 Nov change: every Monday from the first to the last, the week off included',
     T.weekKeys(wkRows2, wkRuns2), ['2026-10-19', '2026-10-26', '2026-11-02', '2026-11-09', '2026-11-16']);
  var wOct26 = T.weekReview(wkRows2, wkRuns2, '2026-10-26', { cut: 25 });
  var wNov2 = T.weekReview(wkRows2, wkRuns2, '2026-11-02', { cut: 25 });
  var wNov9 = T.weekReview(wkRows2, wkRuns2, '2026-11-09', { cut: 25 });
  eq('...the five hours of 31 Oct and the 3am hour of Monday 2 Nov are the week of 26 Oct (six); its 4am hour the next',
     [wOct26.now.hours, wNov2.now.hours, wNov2.prev.hours, wOct26.now.onlineDays], [6, 1, 6, 2]);
  eq('...the week off says nothing happened, and the week after it has no week before to stand beside',
     [wNov9.now.any, wNov9.now.hours, wNov9.now.offers, T.weekReview(wkRows2, wkRuns2, '2026-11-16', { cut: 25 }).prev],
     [false, 0, 0, null]);

  // Week A (Mon 16 Mar): Monday 6-8pm, 20 cards at $30 (good at a $25
  // ruler), two of them ticked taken ($10, 6 mi each); Tuesday 6-9pm, ten
  // cards at $20 and none good. Week B (Mon 23 Mar): Monday and Tuesday
  // 6-8pm, one good card each among ten at $20; Wednesday 6-7:30pm online
  // and quiet. Plus, in week B, one suspect, one re-read and one "pay unread".
  var wa = [], wb = [];
  for (var wi = 0; wi < 20; wi++) wa.push(offer({ id: 'am' + wi, at: at(16, 18, wi * 6), perHour: 30, pay: 10, miles: 6,
                                                  accepted: wi < 2 ? true : undefined }));
  for (var wj = 0; wj < 10; wj++) wa.push(offer({ id: 'at' + wj, at: at(17, 18, wj * 12), perHour: 20 }));
  [23, 24].forEach(function (d) {
    wb.push(offer({ id: 'bg' + d, at: at(d, 18, 5), perHour: 30 }));
    for (var k = 0; k < 10; k++) wb.push(offer({ id: 'bn' + d + '-' + k, at: at(d, 18, 10 + k * 10), perHour: 20 }));
  });
  wb.push(offer({ id: 'bs', at: at(23, 19, 2), suspect: true }), offer({ id: 'bc', at: at(23, 19, 3), corrected: { to: 11 } }),
          offer({ id: 'bu', at: at(23, 19, 4), payUnread: true, suspect: true }));
  var wkR = T.readRows(T.rowsOf(wa.concat(wb)));
  var wkRun = [[at(16, 18, 0), at(16, 20, 0)], [at(17, 18, 0), at(17, 21, 0)], [at(23, 18, 0), at(23, 20, 0)],
               [at(24, 18, 0), at(24, 20, 0)], [at(25, 18, 0), at(25, 19, 30)]];
  var wA = T.weekReview(wkR, wkRun, '2026-03-16', { cut: 25, costPerMile: 0.5 });
  eq('a week by hand: 5 h online on 2 days, 30 offers, 20 good (4/h), 2 takes; $20 earned gross ($4.00/h), '
     + '$14 net of $0.50/mi on 12 miles ($2.80/h)',
     [wA.now.hours, wA.now.onlineDays, wA.now.offers, wA.now.good, wA.now.goodRate, wA.now.takes, wA.now.earned,
      wA.now.gross, wA.now.earnedNet, wA.now.net, wA.now.enough], [5, 2, 30, 20, 4, 2, 20, 4, 14, 2.8, true]);
  eq('...the range\'s own good per hour, the reference a slot is marked against: 22 good over 10.5 h', wA.ref, 2.1);
  eq('...a slot is one driver day, marked as a calendar tile: Monday 6-9pm (20 good in 2 h) clear above, '
     + 'Tuesday 6-9pm (none in 3 h: at most 5.30 / 3 = 1.77 an hour) clear below',
     [wA.slots.met, wA.slots.best && [wA.slots.best.name, wA.slots.best.rate, wA.slots.best.shade],
      wA.slots.worst && [wA.slots.worst.name, wA.slots.worst.rate, wA.slots.worst.shade]],
     [2, ['Mon 6–9pm', 10, 'above'], ['Tue 6–9pm', 0, 'below']]);
  var wB = T.weekReview(wkR, wkRun, '2026-03-23', { cut: 25 });
  eq('..."none clear": one good in each 2 h slot (0.5/h) is not clear of 2.10/h at 99% (up to 3.71), and Wednesday\'s 1.5 h is '
     + 'under the floor and no candidate',
     [wB.slots.met, wB.slots.of, wB.slots.best, wB.slots.worst], [2, 3, null, null]);
  eq('...the week\'s data quality: one suspect, one re-read, one pay unread (counted apart, as the strip)',
     wB.now.quality, { suspect: 1, corrected: 1, unread: 1 });
  eq('...no cost per mile, no net', [wB.net, wB.now.net, wB.now.earnedNet], [false, null, null]);

  // Against the week before. Steady nights (no swing, phi 1): week one 12
  // good a night, week two 2 — clearly below; the same weeks with 12 each —
  // nothing marked; week two on one night only — under the floor, no
  // comparison at all.
  function steady(goodA, goodB, nightsB) {
    var rr = [], ru = [];
    [16, 17].forEach(function (d) {
      ru.push([at(d, 18, 0), at(d, 20, 0)]);
      for (var x = 0; x < goodA; x++) rr.push(offer({ id: 'sa' + d + '-' + x, at: at(d, 18, x * 5), perHour: 30 }));
    });
    [23, 24].slice(0, nightsB).forEach(function (d) {
      ru.push([at(d, 18, 0), at(d, 20, 0)]);
      for (var x = 0; x < goodB; x++) rr.push(offer({ id: 'sb' + d + '-' + x, at: at(d, 18, x * 5), perHour: 30 }));
    });
    return T.weekReview(T.readRows(T.rowsOf(rr)), ru, '2026-03-23', { cut: 25 });
  }
  var sLow = steady(12, 2, 2), sSame = steady(12, 12, 2), sOne = steady(12, 2, 1);
  eq('week against week: 4 good in 4 h against 24 in 4 h is clearly lower (compare mode\'s exact test at 99%)',
     [sLow.cmp.good, sLow.phi.good], [{ prev: 6, shade: 'below' }, 1]);
  eq('...the same figure both weeks: printed beside it, nothing marked', sSame.cmp.good, { prev: 6, shade: null });
  eq('...a week on one night only is under the week\'s floor (2 h on 2 days): no comparison drawn at all',
     [sOne.now.enough, sOne.cmp.good, sOne.cmp.gross, sOne.prev.goodRate], [false, null, null, 6]);
  eq('...and the earnings of two weeks with no take at all are not compared into a difference',
     sLow.cmp.gross, { prev: 0, shade: null, clamped: false });
  eq('...a range that starts mid-week says the week is only part of one',
     [T.weekReview(wkR, wkRun, '2026-03-16', { cut: 25, first: '2026-03-17' }).now.partStart,
      T.weekReview(wkR, wkRun, '2026-03-16', { cut: 25, first: '2026-03-16' }).now.partStart], [true, false]);

  // Like with like (the reporting review's F2): a week still running is set
  // beside last week to the same weekday and hour; the whole week before
  // where no moment inside this week is given; a week before the range
  // began says from when.
  var wSo = T.weekReview(wkR, wkRun, '2026-03-23', { cut: 25, now: at(24, 19, 0) });
  eq('F2: Tuesday 7pm of week B against Tuesday 7pm of week A: 3 h (Monday\'s 2, Tuesday\'s first), 25 offers, 2 takes',
     [wSo.counts.soFar, wSo.counts.hours, wSo.counts.offers, wSo.counts.takes, wSo.counts.until === at(17, 19, 0)],
     [true, 3, 25, 2, true]);
  eq('...with no moment inside the week, the whole week before (5 h, 30 offers, 2 takes), said as full by the page',
     [wB.counts.soFar, wB.counts.hours, wB.counts.offers, wB.counts.takes], [false, 5, 30, 2]);
  var wPart = T.weekReview(wkR, wkRun, '2026-03-23', { cut: 25, first: '2026-03-17' });
  eq('...a week before the range began is part of one, and says from when', [wPart.counts.partStart, wPart.counts.from],
     [true, '2026-03-17']);
  eq('S5: the slots share 99% over the two that met the floor (0.5% each), and Monday and Tuesday still clear',
     [wA.slots.alpha, wA.slots.best.name, wA.slots.worst.name], [0.005, 'Mon 6–9pm', 'Tue 6–9pm']);

  /* --- a large journal is quick --- */
  var r5 = rng(3), big = [];
  for (var b = 0; b < 12500; b++) {
    var t0 = at(1, 16) + Math.floor(b / 130) * 86400000 + (b % 130) * 150000;
    big.push(offer({ id: 'big' + b, at: t0, perHour: 5 + r5() * 30, pay: 3 + r5() * 20, minutes: 10 + r5() * 40,
                     miles: 1 + r5() * 15, app: r5() < 0.7 ? 'uber' : 'doordash' }));
  }
  var started = Date.now();
  var packed = JSON.stringify(T.pack(T.rowsOf(big)));
  var back = T.unpack(JSON.parse(packed));
  T.periods(back, 'day'); T.periods(back, 'week'); T.hourly(back); T.grid(back); T.calendar(back, []);
  T.rateCard(back); T.scatter(back, 4000);
  var took = Date.now() - started;
  ok('12,500 offers packed, read back and summed every way in under 3 s (' + took + ' ms), in about half a MB ('
     + Math.round(packed.length / 1024) + ' kB)', took < 3000 && packed.length < 700 * 1024);

  /* === The every-offer CSV and Excel-friendly tables (the owner, Nov 2026:
     "the CSV download does not seem to include the GPS data", and dates
     Excel can chart) === */
  function csvRows(text) {
    // A small reader: quoted cells, doubled quotes, no line breaks inside.
    return text.trim().split('\n').map(function (line) {
      var out = [], cur = '', q = false;
      for (var i = 0; i < line.length; i++) {
        var ch = line[i];
        if (q) { if (ch === '"' && line[i + 1] === '"') { cur += '"'; i++; } else if (ch === '"') q = false; else cur += ch; }
        else if (ch === '"') q = true; else if (ch === ',') { out.push(cur); cur = ''; } else cur += ch;
      }
      out.push(cur);
      return out;
    });
  }
  function xo(id, ms, extra) {
    var o = { id: id, at: ms, firstAt: ms, pay: 10, perHour: 20, minutes: 30, miles: 5, whole: true, state: 'no',
              app: 'uber', target: 25 };
    Object.keys(extra || {}).forEach(function (k) { o[k] = extra[k]; });
    return o;
  }
  // 1 Nov 2026: the clocks go back at 2am EDT. 1:30am comes twice.
  var fbFirst = new Date('2026-11-01T05:30:00Z').getTime();    // 1:30 EDT
  var fbSecond = new Date('2026-11-01T06:30:00Z').getTime();   // 1:30 EST
  var xoffers = [
    xo('x1', new Date(2026, 9, 30, 3, 59).getTime(), { perHour: 31.5, pay: 15.75, lat: 12.3456789, lon: 45.6123456,
                                                       gpsOk: true, gpsErr: 7.25, gpsAge: 1.04, gpsMode: 3,
                                                       pickup: '=HYPERLINK("http://example.invalid")',
                                                       dropoff: '742 Example Ave, Faketown', accepted: true, state: 'go' }),
    xo('x2', new Date(2026, 9, 30, 4, 0).getTime(), { perHour: 12, lat: 12.31, lon: 45.61, gpsOk: false, gpsWhy: 'rough',
                                                      gpsErr: 129.2, pickup: '+ 1 order', accepted: false }),
    xo('x3', fbFirst, { perHour: 25, boost: 2.5, state: 'warn' }),
    xo('x4', fbSecond, { perHour: 18, boost: false, pickup: '-3.50' }),
    xo('x5', new Date(2026, 10, 1, 4, 0).getTime(), { perHour: 40, suspect: true, doubt: 'speed' }),
    xo('x6', new Date(2026, 10, 2, 20, 15, 9).getTime(), { perHour: null, pay: 1.68, payUnread: true, suspect: true,
                                                           corrected: { from: 1.68, to: null } }),
    xo('x7', new Date(2026, 10, 3, 21, 0).getTime(), { perHour: 22, pay: 11, corrected: { from: 1.1, to: 11 }, miles: 0.05 }),
  ];
  // A second copy of x7, older: the newest copy wins, as the fold.
  xoffers.push(xo('x7', new Date(2026, 10, 3, 20, 59).getTime(), { perHour: 99 }));
  var made = T.offersCsv(xoffers, { busy: { x2: true } });
  var xr = csvRows(made.text), xh = xr[0];
  function col(row, name) { return row[xh.indexOf(name)]; }
  function rowOf(id) { return xr.filter(function (r) { return col(r, 'offer_id') === id; })[0]; }
  eq('[offers csv] the columns, in a stable order: the clock, the card, what the page knows, the flags, the GPS, the places',
     xh, ['datetime', 'date', 'time', 'weekday', 'hour', 'driver_day', 'driver_weekday', 'week_start', 'app', 'pay',
          'boost', 'card_minutes', 'card_miles', 'per_hour', 'per_mile', 'panel_said', 'driver_marked', 'during_job',
          'good_top20_of_range', 'counted', 'suspect', 'doubt', 'pay_reread', 'pay_unread', 'lat', 'lon', 'gps_ok',
          'gps_err_m', 'gps_age_s', 'pickup', 'dropoff', 'offer_id', 'special_day', 'reoffered']);
  eq('[offers csv] one row per offer id, oldest first, the newest copy of each', [made.rows, xr.slice(1).map(function (r) {
    return col(r, 'offer_id'); }), col(rowOf('x7'), 'per_hour')], [7, ['x1', 'x2', 'x3', 'x4', 'x5', 'x6', 'x7'], '22']);
  var r1 = rowOf('x1'), r2 = rowOf('x2');
  eq('[offers csv] 3:59am Friday: a date-time Excel reads, the calendar day, and Thursday\'s driver day and week',
     ['datetime', 'date', 'time', 'weekday', 'hour', 'driver_day', 'driver_weekday', 'week_start'].map(function (k) { return col(r1, k); }),
     ['2026-10-30 03:59:00', '2026-10-30', '03:59', 'Fri', '3', '2026-10-29', 'Thu', '2026-10-26']);
  eq('[offers csv] ...4am is Friday\'s own driver day', [col(r2, 'driver_day'), col(r2, 'driver_weekday'), col(r2, 'hour')],
     ['2026-10-30', 'Fri', '4']);
  eq('[offers csv] the clocks go back (1 Nov): both 1:30ams print as the wall read and belong to Saturday\'s driver day; '
     + '4am Sunday starts Sunday, in the week of 26 Oct', [col(rowOf('x3'), 'datetime'), col(rowOf('x4'), 'datetime'),
       col(rowOf('x3'), 'driver_day'), col(rowOf('x4'), 'driver_day'), col(rowOf('x5'), 'driver_day'),
       col(rowOf('x5'), 'week_start'), col(rowOf('x6'), 'week_start')],
     ['2026-11-01 01:30:00', '2026-11-01 01:30:00', '2026-10-31', '2026-10-31', '2026-11-01', '2026-10-26', '2026-11-02']);
  eq('[offers csv] plain numbers, no $ or commas: pay, minutes, miles, $/hr, $/mi', ['pay', 'card_minutes', 'card_miles',
     'per_hour', 'per_mile'].map(function (k) { return col(r1, k); }), ['15.75', '30', '5', '31.5', '3.15']);
  eq('[offers csv] what the page knows: the panel\'s word, the driver\'s own mark only (taken, passed, else empty), '
     + 'and during a job', [[col(r1, 'panel_said'), col(r1, 'driver_marked'), col(r1, 'during_job')],
       [col(r2, 'panel_said'), col(r2, 'driver_marked'), col(r2, 'during_job')],
       [col(rowOf('x3'), 'panel_said'), col(rowOf('x3'), 'driver_marked')]],
     [['ACCEPT', 'taken', ''], ['PASS', 'passed', 'yes'], ['CLOSE CALL', '']]);
  // The ruler, held equal to trends.js's own over the same offers.
  var xRule = T.ruler(T.readRows(T.rowsOf(xoffers)), 20);
  var xGood = T.readRows(T.rowsOf(xoffers)).filter(function (r) { return T.isGood(r, xRule.cut); }).length;
  eq('[offers csv] good_top20_of_range is trends.js\'s ruler over the same range (cut ' + xRule.cut + ', '
     + xGood + ' good), empty where the money does not count', [made.cut, xr.slice(1).filter(function (r) {
       return col(r, 'good_top20_of_range') === 'yes'; }).length, col(rowOf('x5'), 'good_top20_of_range'),
       col(rowOf('x6'), 'good_top20_of_range'), col(r1, 'good_top20_of_range')], [xRule.cut, xGood, '', '', 'yes']);
  eq('[offers csv] the flags: suspect and its doubt, counted, the pay re-read, the pay unread (and then no pay)',
     [['suspect', 'doubt', 'counted'].map(function (k) { return col(rowOf('x5'), k); }),
      ['pay', 'pay_unread', 'counted', 'per_hour'].map(function (k) { return col(rowOf('x6'), k); }),
      ['pay_reread', 'per_mile'].map(function (k) { return col(rowOf('x7'), k); })],
     [['yes', 'speed', 'no'], ['', 'yes', 'no', ''], ['yes', '']]);
  eq('[offers csv] boost as the card said it: an amount, no, or empty when unknown',
     [col(rowOf('x3'), 'boost'), col(rowOf('x4'), 'boost'), col(r1, 'boost')], ['2.5', 'no', '']);
  eq('[offers csv] GPS where the row has a fix: six places, the gate\'s word, metres and seconds; a refused fix says no',
     [['lat', 'lon', 'gps_ok', 'gps_err_m', 'gps_age_s'].map(function (k) { return col(r1, k); }),
      ['lat', 'gps_ok', 'gps_err_m'].map(function (k) { return col(r2, k); }), made.gps],
     [['12.345679', '45.612346', 'yes', '7.3', '1'], ['12.31', 'no', '129.2'], 2]);
  eq('[offers csv] ...and empty, never null or NaN, on a row with no fix',
     ['lat', 'lon', 'gps_ok', 'gps_err_m', 'gps_age_s'].map(function (k) { return col(rowOf('x3'), k); }), ['', '', '', '', '']);
  ok('[offers csv] ...no cell anywhere says null, NaN or undefined', !/(^|,)(null|NaN|undefined)(,|$)/m.test(made.text));
  eq('[offers csv] a formula is defused with an apostrophe: =HYPERLINK, "+ 1 order"; a plain -3.50 keeps its sign',
     [col(r1, 'pickup'), col(r2, 'pickup'), col(rowOf('x4'), 'pickup')],
     ['\'=HYPERLINK("http://example.invalid")', '\'+ 1 order', '-3.50']);
  eq('[offers csv] T.safeCell: = + - @ tab and CR, not a number', ['=1+1', '@Home Kitchen', '-', '\tx', '+15.00', '-2', 'Oak']
     .map(T.safeCell), ['\'=1+1', '\'@Home Kitchen', '\'-', '\'\tx', '+15.00', '-2', 'Oak']);
  var off = T.offersCsv(xoffers, { keepPlaces: false }), offR = csvRows(off.text);
  var offRow = offR.filter(function (r) { return r[offR[0].indexOf('offer_id')] === 'x1'; })[0];
  eq('[offers csv] keepPlaces off: the GPS and place columns stay, and are empty on every row',
     [offR[0].join(','), ['lat', 'lon', 'gps_ok', 'gps_err_m', 'gps_age_s', 'pickup', 'dropoff'].map(function (k) {
       return offRow[offR[0].indexOf(k)]; }), off.gps], [xh.join(','), ['', '', '', '', '', '', ''], 0]);
  eq('[offers csv] the page puts a byte-order mark in front, so Excel reads it as UTF-8', T.BOM.charCodeAt(0), 0xfeff);
  ok('[offers csv] ...and the text itself starts with its header', made.text.indexOf('datetime,') === 0);
  // The Trends tables: week_start and the weekday appended, the hour's label.
  var xp = T.periods(T.readRows(T.rowsOf(xoffers)), 'day');
  var xpd = csvRows(T.csvPeriods(xp, [], 'day', 19)), xpw = csvRows(T.csvPeriods(T.periods(T.readRows(T.rowsOf(xoffers)), 'week'), [], 'week', 19));
  eq('[trends csv] daily: the first column kept, week_start (a Monday) and the weekday appended last',
     [xpd[0][0], xpd[0].slice(-2), xpd[1][0], xpd[1].slice(-2)], ['day', ['week_start', 'weekday'], '2026-10-29', ['2026-10-26', 'Thu']]);
  eq('[trends csv] weekly: week_of is the Monday, week_start the same date, no weekday',
     [xpw[0][0], xpw[1][0], xpw[1].slice(-2)], ['week_of', '2026-10-26', ['2026-10-26', '']]);
  var xhCsv = csvRows(T.csvHourly(T.hourly(T.readRows(T.rowsOf(xoffers)), {}), 'all'));
  eq('[trends csv] hourly: the hour a bare integer, its label appended (4am first, as the day runs)',
     [xhCsv[0].slice(0, 2), xhCsv[0].slice(-1), xhCsv[1][1], xhCsv[1].slice(-1)[0], xhCsv[24][1], xhCsv[24].slice(-1)[0]],
     [['hours', 'hour'], ['hour_label'], '4', '04:00-05:00', '3', '03:00-04:00']);
  ok('[trends csv] ...and no table says null or NaN', !/(^|,)(null|NaN|undefined)(,|$)/m.test(T.csvPeriods(xp, [], 'day', null)
     + T.csvHourly(T.hourly(T.readRows(T.rowsOf(xoffers)), {}), 'all')));

  /* --- /api/trends, through a real server --- */
  /* --- round B: special days, leave out, windows, outliers, costs, reveals --- */

  // Special days by rule, 2026-2028, checked against the calendar by hand.
  var sd = [2026, 2027, 2028].map(function (y) {
    var d = T.specialDays(y), by = {};
    Object.keys(d).forEach(function (k) { d[k].split(' · ').forEach(function (n) { by[n] = k; }); });
    return by;
  });
  eq('[special] Thanksgiving is the 4th Thursday of November: 26 Nov 2026, 25 Nov 2027, 23 Nov 2028',
     sd.map(function (b) { return b.Thanksgiving; }), ['2026-11-26', '2027-11-25', '2028-11-23']);
  eq('[special] Super Bowl Sunday is the 2nd Sunday of February from 2022: 8 Feb 2026, 14 Feb 2027, 13 Feb 2028; '
     + 'the 1st before (7 Feb 2021), and 13 Feb 2022 and 9 Feb 2025 as played',
     sd.map(function (b) { return b['Super Bowl Sunday']; }).concat([T.specialDayOf('2021-02-07'),
       T.specialDayOf('2022-02-13'), T.specialDayOf('2025-02-09')]),
     ['2026-02-08', '2027-02-14', '2028-02-13', 'Super Bowl Sunday', 'Super Bowl Sunday', 'Super Bowl Sunday']);
  eq('[special] 14 Feb 2027 is both, and says both; Mother\'s Day the 2nd Sunday of May (10 May 2026, 9 May 2027, '
     + '14 May 2028); the fixed days',
     [T.specialDayOf('2027-02-14'), sd[0]['Mother\'s Day'], sd[1]['Mother\'s Day'], sd[2]['Mother\'s Day'],
      T.specialDayOf('2026-10-31'), T.specialDayOf('2027-12-24'), T.specialDayOf('2027-12-25'), T.specialDayOf('2028-12-31'),
      T.specialDayOf('2028-01-01'), T.specialDayOf('2026-07-04'), T.specialDayOf('2026-02-14'), T.specialDayOf('2026-11-19')],
     ['Valentine\'s Day · Super Bowl Sunday', '2026-05-10', '2027-05-09', '2028-05-14', 'Halloween', 'Christmas Eve',
      'Christmas Day', 'New Year\'s Eve', 'New Year\'s Day', 'July 4th', 'Valentine\'s Day', null]);
  eq('[special] a day the owner marked, alone and on a built-in day; a bad date is no day',
     [T.specialDayOf('2026-11-07', ['2026-11-07']), T.specialDayOf('2026-10-31', ['2026-10-31']),
      T.specialDayOf('2026-02-30'), T.specialDayOf('nonsense', ['nonsense'])],
     ['marked by you', 'Halloween (marked by you)', null, null]);
  // Leave out: Halloween's driver day runs 4am 31 Oct to 4am 1 Nov, so its
  // 1:30am card is Halloween's, and a run across 4am keeps its later part.
  function hal(day, h, m) { return new Date(2026, 9, day, h, m || 0).getTime(); }
  var halRows = T.readRows(T.rowsOf([
    offer({ id: 'h1', at: hal(30, 20), perHour: 20 }), offer({ id: 'h2', at: hal(31, 20), perHour: 60 }),
    offer({ id: 'h3', at: hal(32, 1, 30), perHour: 70 }), offer({ id: 'h4', at: hal(32, 5), perHour: 22 }),
    offer({ id: 'h5', at: hal(30, 21), perHour: 90, reoffered: true })]));
  var halRuns = [[hal(30, 19), hal(30, 23)], [hal(31, 19), hal(32, 6)]];
  var lo0 = T.leaveOut(halRows, halRuns, {});
  var loS = T.leaveOut(halRows, halRuns, { special: true });
  var loR = T.leaveOut(halRows, halRuns, { reoffered: true });
  var hoursOf = function (runs) { return runs.reduce(function (a, r) { return a + (r[1] - r[0]) / 3.6e6; }, 0); };
  eq('[leave out] off: the same rows and runs by identity; special days: Halloween\'s 8pm and 1:30am cards and its '
     + 'nine hours out, the 4-6am of 1 Nov kept; re-offered: the marked card only',
     [lo0.rows === halRows && lo0.runs === halRuns, loS.removed, loS.days, hoursOf(loS.runs), loR.removed, loR.reoffered,
      loR.runs === halRuns],
     [true, 2, [{ day: '2026-10-31', name: 'Halloween' }], 6, 1, 1, true]);
  // Windows: an invented record with a clear Friday evening, contiguous.
  function winSlices(seed, fri, nights) {
    var r = rng(seed), out = [];
    for (var d = 0; d < (nights || 63); d++) {
      var day = new Date(2026, 8, 7 + d, 12), key = T.dayKeyOf(day.getTime()), dow = day.getDay();
      if (r() > 0.6) continue;
      [17, 18, 19, 20, 21, 22, 23].forEach(function (h) {
        var lam = 4 * (fri && dow === 5 && h >= 18 && h <= 21 ? fri : 1), k = 0, p = 1, L = Math.exp(-lam);
        do { k += 1; p *= r(); } while (p > L);
        out.push({ day: key, dow: dow, hour: h, k: k - 1, h: 1, offers: k - 1 + 3, takes: 0, e: 0 });
      });
    }
    return out;
  }
  var wv = T.findWindows(winSlices(7, 2.5));
  eq('[windows] a Friday evening at 2.5 times the rate is found whole, a contiguous run of its hours, clearly above',
     [wv.clear, wv.best[0].name, wv.best[0].hours, wv.best[0].shade], [true, 'Fridays 6–10pm', [18, 19, 20, 21], 'above']);
  ok('[windows] ...no two chosen windows share a cell, and every window shown meets the floor (2 h online on 2 days)',
     wv.best.concat(wv.worst).every(function (w, i, a) {
       return w.online >= 2 && w.nights >= 2 && a.every(function (x, j) {
         return j === i || !x.cells.some(function (c) { return w.cells.indexOf(c) >= 0; });
       });
     }));
  var nulls = 0;
  for (var sN = 0; sN < 40; sN++) if (T.findWindows(winSlices(100 + sN, 0)).best.length) nulls += 1;
  var wn = T.findWindows(winSlices(101, 0));
  eq('[windows] with no effect: "no window clearly better" in (nearly) every record, and three leading windows '
     + 'listed apart, sharing no cell',
     [nulls <= 1, wn.clear, wn.best.length, wn.leading.length, wn.leading.every(function (w) { return w.shade !== 'below'; })],
     [true, false, 0, 3, true]);
  eq('[windows] untried hours (no minute online, no card) are listed, merged over every day, never ranked as weak',
     [wn.untried[0].name, wn.untried[0].every, wn.worst.every(function (w) { return w.online > 0; })],
     ['every day 4am–5pm', true, true]);
  var one = T.findWindows([{ day: '2026-09-11', dow: 5, hour: 19, k: 30, h: 5, offers: 30 }]);
  eq('[windows] one night, however strong, is under the floor: no window at all', [one.searched, one.leading.length], [0, 0]);
  eq('[windows] the names: a night across midnight and a single hour', [T.spanName(22, 1), T.spanName(4, 4), T.spanName(18, 21)],
     ['10pm–2am', '4–5am', '6–10pm']);
  // The overview on rows and runs: good per hour online, the grid's own.
  var ovRows = T.readRows(T.rowsOf([offer({ id: 'v1', at: at(6, 19, 10), perHour: 40 }),
                                    offer({ id: 'v2', at: at(13, 19, 20), perHour: 40 }),
                                    offer({ id: 'v3', at: at(13, 19, 40), perHour: 10 })]));
  var ov = T.overviewWhen(ovRows, [[at(6, 19), at(6, 20)], [at(13, 19), at(13, 20)]], { cut: 30 });
  eq('[windows] the tab\'s own: 2 good in 2 hours online on two Fridays, the 7pm hour, leading (too little to be clear)',
     [ov.leading[0].name, ov.leading[0].good, ov.leading[0].online, ov.leading[0].nights, ov.leading[0].rate],
     ['Fridays 7–8pm', 2, 2, 2, 1]);
  // Outliers: the axis stops at the bulk; nothing is dropped.
  var bulk = [];
  for (var bi = 0; bi < 200; bi++) bulk.push(15 + (bi % 20));
  var capA = T.axisCap(bulk.concat([400, 250, 180])), capB = T.axisCap(bulk), capC = T.axisCap([10, 500]);
  eq('[outliers] three wild offers over 200 of the bulk: the cap at the far fence or P99, "↑ 3 above"; none wild, '
     + 'no cap; under 20 values, no cap', [capA.above, capA.cap > 34 && capA.cap < 180, capB.cap, capC.cap],
     [3, true, null, null]);
  var outRows = T.readRows(T.rowsOf(bulk.map(function (v, i) { return offer({ id: 'b' + i, perHour: v, at: at(2, 19) + i * 1000 }); })
    .concat([offer({ id: 'w1', perHour: 400, pay: 99, reoffered: true, at: at(2, 22) })])));
  var ol = T.outliers(outRows, T.axisCap(outRows.map(function (r) { return r.perHour; })).cap);
  eq('[outliers] the list: figures and when only, the re-offered mark carried', [ol.length, ol[0].perHour, ol[0].pay,
     ol[0].reoffered, Object.keys(ol[0]).sort()],
     [1, 400, 99, true, ['app', 'day', 'miles', 'minutes', 'pay', 'perHour', 'reoffered', 't', 'taken']]);
  // Costs: where the rows' own cost per mile moved.
  var cn = T.costNote([[at(2, 19) / 1000, 0.3], [at(9, 19) / 1000, 0.45]]);
  eq('[costs] a change in the range: when, from and to; one cost, no change', [cn.now, cn.changes.length, cn.changes[0].day,
     cn.changes[0].from, cn.changes[0].to, T.costNote([[1, 0.3]]).changes.length], [0.45, 1, '2026-03-09', 0.3, 0.45, 0]);
  // Hidden until the record can hold it (D4-D6).
  function spanRows(from, to) {
    var list = [];
    for (var t = from; t <= to; t += 864e5) list.push(offer({ id: 's' + t, at: t }));
    return T.readRows(T.rowsOf(list));
  }
  var rv2 = T.reveals(spanRows(new Date(2026, 8, 20, 19).getTime(), new Date(2026, 10, 10, 19).getTime()), []);
  var rv3 = T.reveals(spanRows(new Date(2026, 7, 20, 19).getTime(), new Date(2026, 10, 10, 19).getTime()), []);
  var rvF = T.reveals(T.readRows(T.rowsOf([offer({ id: 'f1', at: at(6, 19) }), offer({ id: 'f2', at: at(13, 19) }),
                                           offer({ id: 'f3', at: at(20, 19) })])), [[at(27, 19), at(27, 20)]]);
  eq('[reveals] Sep 20 to Nov 10: three months with data, one whole (October); Aug 20 to Nov 10: four, two whole; '
     + 'four Fridays (three cards and an hour online) show Fridays, nothing else',
     [rv2.months, rv2.fullMonths, rv2.tlMonths, rv2.monthVsLast, rv3.fullMonths, rv3.monthVsLast, rvF.sameDow[5],
      rvF.sameDow[4], rvF.thirds],
     [3, 1, true, false, 2, true, true, false, false]);
  // The CSV carries both marks as columns, never as rows taken away.
  var csvB = T.offersCsv([offer({ id: 'c1', at: hal(31, 21) }), offer({ id: 'c2', at: hal(30, 21), reoffered: true }),
                          offer({ id: 'c3', at: hal(25, 21) })], { marked: ['2026-10-25'] }).text.split('\n');
  eq('[offers csv] special_day and reoffered, appended last: Halloween, a re-offered card, a day marked by you',
     [csvB[1].split(',').slice(-2), csvB[2].split(',').slice(-2), csvB[3].split(',').slice(-2), csvB.length - 2],
     [['marked by you', 'no'], ['', 'yes'], ['Halloween', 'no'], 3]);
  // The overview words history, never advice (Settled: the rig never says
  // take or decline off a time or a place): the page's When and Where and the
  // window names hold none of those words.
  var pageSrc = fs.readFileSync(path.join(__dirname, '..', 'journal.html'), 'utf8');
  var ovSrc = pageSrc.slice(pageSrc.indexOf('    function outSaid() {'), pageSrc.indexOf('    function drawOvOutliers('));
  // What it says: its string literals (code may name a figure `takes`).
  ovSrc = (ovSrc.replace(/\n\s*\/\/[^\n]*/g, '').match(/'(?:[^'\\\n]|\\.)*'/g) || []).join(' ');
  ok('[wording] the Overview\'s When, Where and switches say what paid, never take, decline or accept (' + ovSrc.length
     + ' characters read)', ovSrc.length > 1500 && !/\b(take|takes|taking|decline|declin\w*|accept\w*|should)\b/i.test(ovSrc)
     && !/\b(take|decline|accept)\b/i.test(T.GROUP_NAMES.join(' ') + wv.best.map(function (w) { return w.name; }).join(' ')));
  ok('[labels] an offer\'s $/hr is said after its cost per mile on the card\'s miles, and a change in the range is dated',
     /'after ' \+ money2\(c\.now\) \+ '\/mi \(card miles\)'/.test(pageSrc)
     && /'Cost per mile changed ' \+ c\.changes\.map/.test(pageSrc)
     && /offers are netted at the cost set when each was seen/.test(pageSrc)
     && /Gross \(before costs\)/.test(pageSrc) && /'pay \(before costs\)'/.test(pageSrc));

  // The every-offer CSV named its file off Math.min/max.apply over every
  // offer's time, which throws past ~125,000 arguments, and no file came.
  var eoSrc = pageSrc.slice(pageSrc.indexOf('T.offersCsv(data.offers'), pageSrc.indexOf("'every-offer' +"));
  ok('[every offer csv] its first and last times are a loop, not Math.min/max.apply over every offer',
     eoSrc.length > 100 && /for \(var ti = 0; ti < times\.length/.test(eoSrc) && !/Math\.(min|max)\.apply/.test(eoSrc.replace(/\/\/[^\n]*/g, '')));

  var dir = fs.mkdtempSync(path.join(os.tmpdir(), 'trends-'));
  var journal = path.join(dir, 'journal.jsonl');
  var now = Date.now();
  var lines = [];
  for (var j = 0; j < 6000; j++) {
    var tj = now - 20 * 86400000 + j * 240000;
    lines.push(JSON.stringify({ v: 1, id: 'srv' + j, seq: 1, at: tj, pay: 9, minutes: 28, billedMinutes: 28,
                                miles: 8, perHour: 19, target: 25, band: 15, state: 'no', whole: true, app: 'uber',
                                costPerMile: j >= 5990 ? 0.35 : 0.3, lat: 12.3, lon: 45.6, gpsOk: true }));
    if (j % 2) lines.push(JSON.stringify({ v: 1, id: 'srv' + j, seq: 2, at: tj + 2000, pay: 9, minutes: 28,
                                           billedMinutes: 28, miles: 8, perHour: 19, target: 25, band: 15,
                                           state: 'no', whole: true, app: 'uber' }));
  }
  lines.push(JSON.stringify({ v: 1, kind: 'mark', id: 'srv5', at: now, hidden: true }));
  // Takes: a tick; a pass (Passed sends `via`); a tick taken back (a `false`
  // with no `via` is a withdrawal, server.js folds it to no answer).
  lines.push(JSON.stringify({ v: 1, kind: 'mark', id: 'srv10', at: now - 1000, accepted: true }));
  lines.push(JSON.stringify({ v: 1, kind: 'mark', id: 'srv12', at: now - 1000, accepted: false, via: 'review' }));
  lines.push(JSON.stringify({ v: 1, kind: 'mark', id: 'srv14', at: now - 2000, accepted: true }));
  lines.push(JSON.stringify({ v: 1, kind: 'mark', id: 'srv14', at: now - 1000, accepted: false }));
  // Round B: re-offered cards, folded by the server. Forty days back, out of
  // the 30-day window every figure above counts.
  var ro = now - 40 * 86400000;
  function roRow(id, seq, t, pay, extra) {
    return JSON.stringify(Object.assign({ v: 1, id: id, seq: seq, at: t, firstAt: t, pay: pay, minutes: 18, billedMinutes: 18,
      miles: 6, perHour: pay * 3, target: 25, band: 15, state: 'go', whole: true, app: 'doordash',
      pickup: 'Invented Burger 7', dropoff: '12 Nowhere St, Faketown' }, extra || {}));
  }
  lines.push(roRow('ro1', 1, ro, 40));
  lines.push(roRow('ro2', 1, ro + 4 * 60000, 55));                                      // the same trip, raised
  lines.push(roRow('ro3', 1, ro + 6 * 60000, 30, { dropoff: '99 Elsewhere Rd, Mockville' }));   // another door
  lines.push(roRow('ro4', 1, ro + 50 * 60000, 70));                                     // the same trip, 46 min on
  lines.push(roRow('rb1', 1, ro + 90 * 60000, 20, { pickup: 'Other Grill', dropoff: '' }));
  lines.push(roRow('rb1', 2, ro + 95 * 60000, 20, { pickup: 'Other Grill', dropoff: '', firstAt: ro + 90 * 60000 }));  // came back
  lines.push(roRow('rq1', 1, ro + 120 * 60000, 20, { pickup: 'Quiet Deli', dropoff: '' }));
  lines.push(roRow('rq1', 2, ro + 120 * 60000 + 2000, 20, { pickup: 'Quiet Deli', dropoff: '', firstAt: ro + 120 * 60000 }));
  // One card filed under two ids 25 s apart while it was still up (the owner's
  // first breakdown: the median pair 27 s): not an order coming round again.
  lines.push(roRow('rq2', 1, ro + 150 * 60000, 20, { pickup: 'Twin Diner', dropoff: '7 Mock Ave, Faketown' }));
  lines.push(roRow('rq3', 1, ro + 150 * 60000 + 25000, 20, { pickup: 'Twin Diner', dropoff: '7 Mock Ave, Faketown' }));
  fs.writeFileSync(journal, lines.join('\n') + '\n');
  async function serve(lite) {
    var port = 20000 + Math.floor(Math.random() * 20000);
    var proc = cp.spawn('node', [path.join(__dirname, '..', 'server.js')], {
      env: Object.assign({}, process.env, { PORT: String(port), HTTPS_PORT: '0', SCANNER: '0', JOURNAL: journal,
                                            LITE: lite ? '1' : '0' }),
      stdio: 'ignore' });
    for (var tries = 0; tries < 100; tries++) {
      try { await get(port, '/api/lite'); return { proc: proc, port: port }; } catch (e) {
        await new Promise(function (r) { setTimeout(r, 100); });
      }
    }
    proc.kill();
    throw new Error('server did not start');
  }
  function get(port, p) {
    return new Promise(function (resolve, reject) {
      http.get({ host: '127.0.0.1', port: port, path: p }, function (res) {
        var body = '';
        res.on('data', function (c) { body += c; });
        res.on('end', function () { resolve({ status: res.statusCode, body: body }); });
      }).on('error', reject);
    });
  }
  var full = await serve(false);
  try {
    var ans = await get(full.port, '/api/trends?days=30');
    var j1 = JSON.parse(ans.body);
    eq('/api/trends answers every offer in the window, once each, hidden ones out, past /api/journal\'s 5,000',
       [ans.status, j1.ok, j1.total, j1.rows.n], [200, true, 5999, 5999]);
    ok('...with the runs of scanning and the target', Array.isArray(j1.runs) && j1.runs.length >= 1 && j1.target === 25);
    ok('...and no place or position in it', !/lat|lon|pickup|dropoff|"text"/.test(ans.body));
    // The every-offer CSV's GPS comes from /api/journal, which the owner's
    // own browser asks of his own server, never from /api/trends.
    var jj = JSON.parse((await get(full.port, '/api/journal?days=30&limit=5')).body);
    eq('...the fix reaches the offers page by /api/journal alone, with the rig\'s keepPlaces (none heard: no scanner)',
       [jj.offers.some(function (o) { return o.lat === 12.3 && o.gpsOk === true; }), jj.keepPlaces], [true, null]);
    var takenAt = [];
    j1.rows.cols.flags.forEach(function (f, i) { if (f & T.F_TAKEN) takenAt.push(i); });
    var srvT = T.unpack(j1.rows).filter(function (r) { return r.taken; });
    eq('...a take reaches the tab as a bit, only for the driver\'s standing tick (not a pass, not a tick taken back)',
       [takenAt.length, srvT.length === 1 && srvT[0].t === Math.round((now - 20 * 86400000 + 10 * 240000) / 1000) * 1000],
       [1, true]);
    var withTop = JSON.parse((await get(full.port, '/api/trends?days=30&top=10')).body);
    eq('...and the server takes no ruler: the same answer whatever the page\'s choice, no cut in it',
       [Object.keys(withTop).sort(), withTop.total, JSON.stringify(withTop.rows) === JSON.stringify(j1.rows)],
       [['costPerMile', 'costs', 'days', 'floor', 'marked', 'ok', 'rows', 'runs', 'target', 'total'], 5999, true]);
    eq('[round B] costs: where the rows\' own cost per mile changed, [seconds, cost], numbers only; marked: dates only',
       [j1.costs.length, j1.costs[1][1], j1.costs.every(function (c) { return typeof c[0] === 'number' && typeof c[1] === 'number'; }),
        j1.marked], [2, 0.35, true, []]);
    eq('...with one cost per mile, the rig\'s own off its newest offer (for earned per hour net), a number and nothing else',
       [j1.costPerMile, typeof j1.costPerMile], [0.35, 'number']);
    var j7 = JSON.parse((await get(full.port, '/api/trends?days=7')).body);
    var inSeven = 0;
    for (var j2 = 0; j2 < 6000; j2++) if (now - 20 * 86400000 + j2 * 240000 >= now - 7 * 86400000) inSeven += 1;
    ok('...the range is an honest span: 7 days holds the last 7 days\' offers (' + j7.total + ' of ' + inSeven + ')',
       Math.abs(j7.total - inSeven) <= 2);
    // T9: gzipped where the browser asks, the same answer underneath.
    var gz = await new Promise(function (resolve, reject) {
      http.get({ host: '127.0.0.1', port: full.port, path: '/api/trends?days=30', headers: { 'Accept-Encoding': 'gzip, deflate' } },
        function (res) {
          var parts = [];
          res.on('data', function (c) { parts.push(c); });
          res.on('end', function () { resolve({ enc: res.headers['content-encoding'], vary: res.headers.vary, buf: Buffer.concat(parts) }); });
        }).on('error', reject);
    });
    var gzBody = require('zlib').gunzipSync(gz.buf).toString('utf8');
    eq('T9: /api/trends is gzipped for a browser that takes it, a fraction of the size, the same rows underneath',
       [gz.enc, gz.vary, gz.buf.length < ans.body.length / 3, JSON.stringify(JSON.parse(gzBody).rows) === JSON.stringify(j1.rows)],
       ['gzip', 'Accept-Encoding', true, true]);
    // R2 (the reporting review): /api/journal's `until` lists only the older
    // offers, so a reader past `limit` can page back; the window's figures stay.
    var untilAt = now - 10 * 86400000;
    var ju = JSON.parse((await get(full.port, '/api/journal?days=30&limit=100&until=' + untilAt)).body);
    var before10 = 0;
    for (var j3 = 0; j3 < 6000; j3++) if (j3 !== 5 && now - 20 * 86400000 + j3 * 240000 < untilAt) before10 += 1;
    eq('R2: /api/journal\'s until lists the newest `limit` offers before it, its total those before it, said cut',
       [ju.offers.length, ju.offers.every(function (o) { return o.at < untilAt; }), Math.abs(ju.total - before10) <= 1,
        ju.truncated], [100, true, true, true]);
    // Round B: the fold's re-offered mark, one definition for every view.
    var jall = JSON.parse((await get(full.port, '/api/journal?days=0&limit=0')).body);
    var reo = {};
    jall.offers.forEach(function (o) { if (/^r[obq]/.test(o.id)) reo[o.id] = o.reoffered === true; });
    eq('[reoffered] the same trip twice in 30 min (both marked), another door not, the same trip 46 min on not; '
       + 'one id back after 5 min marked, one read twice in 2 s not, one card under two ids 25 s apart not',
       reo, { ro1: true, ro2: true, ro3: false, ro4: false, rb1: true, rq1: false, rq2: false, rq3: false });
    ok('[reoffered] ...set only where true, so every other row is byte for byte what it was',
       jall.offers.filter(function (o) { return 'reoffered' in o; }).every(function (o) { return o.reoffered === true; }));
    var tall = JSON.parse((await get(full.port, '/api/trends?days=0')).body);
    eq('[reoffered] ...and /api/trends carries it as one flag bit, no new column',
       [tall.rows.cols.flags.filter(function (f) { return f & T.F_REOFFER; }).length, Object.keys(tall.rows.cols).length], [3, 7]);
    // The owner's special days: dates only, the /api/settings pattern.
    function post(port, p, body) {
      return new Promise(function (resolve, reject) {
        var data = typeof body === 'string' ? body : JSON.stringify(body);
        var rq = http.request({ host: '127.0.0.1', port: port, path: p, method: 'POST',
                                headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) } },
          function (res) { var b = ''; res.on('data', function (c) { b += c; }); res.on('end', function () { resolve({ status: res.statusCode, body: b }); }); });
        rq.on('error', reject);
        rq.end(data);
      });
    }
    var sp1 = await post(full.port, '/api/specialdays', { add: '2026-11-07' });
    var sp2 = await post(full.port, '/api/specialdays', { add: '2026-02-30' });
    var sp3 = await post(full.port, '/api/specialdays', { add: '2026-11-08', note: 'x' });
    var sp4 = await post(full.port, '/api/specialdays', { add: '2026-11-08', remove: '2026-11-07' });
    var sp5 = await post(full.port, '/api/specialdays', '[1]');
    var sp6 = await post(full.port, '/api/specialdays', { add: '2019-12-31' });
    var sp7 = await post(full.port, '/api/specialdays', { add: '<b>2026-11-09' });
    var spG = JSON.parse((await get(full.port, '/api/specialdays')).body);
    eq('[special days] a real date is kept; Feb 30, an extra key, two at once, an array, 2019 and a dressed-up date refused',
       [sp1.status, JSON.parse(sp1.body).days, sp2.status, sp3.status, sp4.status, sp5.status, sp6.status, sp7.status, spG.days],
       [200, ['2026-11-07'], 400, 400, 400, 400, 400, 400, ['2026-11-07']]);
    var spFile = JSON.parse(fs.readFileSync(path.join(dir, 'special-days.json'), 'utf8'));
    eq('[special days] ...the file beside the journal holds dates and nothing else, and /api/trends reads it',
       [spFile, JSON.parse((await get(full.port, '/api/trends?days=30')).body).marked], [{ v: 1, days: ['2026-11-07'] }, ['2026-11-07']]);
    var spR = await post(full.port, '/api/specialdays', { remove: '2026-11-07' });
    eq('[special days] ...and a day unmarked is gone', [spR.status, JSON.parse(spR.body).days], [200, []]);
    var page = (await get(full.port, '/journal.html')).body;
    ok('the offers page has the Trends tab, and loads trends.js only when it is opened',
       /data-view="trends"/.test(page) && !/<script src="trends\.js">/.test(page) && /s\.src = 'trends\.js'/.test(page));
    // Round B: the Overview first (the ruler line, the switches, When,
    // Where, this week, the outliers), every chart folded beneath it.
    var order = ['trOverview', 'trRuler', 'trTop', 'trOut', 'trOvWhen', 'trOvWhere', 'trWeek', 'trOvOutliers', 'trMore',
                 'trWhenHead', 'trStat', 'trGrid', 'trCell', 'trHourly', 'trCal', 'trSpecial', 'trTimeFold', 'trThirdsBox',
                 'trChangeHead', 'trSame', 'trOverTime', 'trBy', 'trDaily', 'trGood', 'trSpread', 'trShare', 'trCompare',
                 'trShape', 'trMixMin', 'trScatter', 'trRate', 'trQuality', 'trHow', 'trCsvDays']
      .map(function (id) { return page.indexOf('id="' + id + '"'); });
    ok('[round B] the Overview first; every chart of the rounds before folded under "Every chart", each id kept; '
       + 'Each day, good per hour, the pay spread and the app share folded with By day / By week beside them; the '
       + 'timeline folded; one "How this is measured"; CSVs last',
       order.every(function (x, i) { return x > 0 && (i === 0 || x > order[i - 1]); })
       && /<details class="trmore" id="trMore">/.test(page) && /<details class="trshape" id="trShape">/.test(page)
       && /<details class="trfold" id="trTimeFold">/.test(page) && /<details class="trfold" id="trOverTime">/.test(page));
    ok('the week in review is the Overview\'s "This week", stepped by ‹ ›, its sums trends.js weekReview\'s, and the Money '
       + 'tab\'s earnings handed over by event (never fetched again)',
       page.indexOf('id="trOvWeekHead"') < page.indexOf('id="trWeek"') && page.indexOf('id="trWeek"') < page.indexOf('id="trMore"')
       && /id="trWeekPrev"[\s\S]*id="trWeekNext"/.test(page) && /T\.weekReview\(rows, got\.runs, st\.week/.test(page)
       && /E\.rangeSummary\(money\.entries/.test(page) && /CustomEvent\('money:held'/.test(page)
       && /addEventListener\('money:ask', sayMoneyHeld\)/.test(page));
    ok('the week card words a running week like with like, the earned floor, one evening and one "no slot" row',
       /same time last week/.test(page) && /last week \(full\)/.test(page) && /\(only from /.test(page)
       && /a floor: only your ✓ or Took counts as taken/.test(page) && /that evening, clearly/.test(page)
       && /No slot clearly better or worse/.test(page) && /matched to an order in this week/.test(page)
       && /now: Date\.now\(\) \}\)/.test(page));
    ok('S7: every coloured view says about 1 coloured square in 100 can be chance; the grid says its quantile is widened',
       (page.match(/\+ CHANCE|\+ ' ' \+ CHANCE/g) || []).length === 6
       && /About 1 coloured square in 100 can be chance\./.test(page) && /move together \(a slow night/.test(page)
       // Round B: kept under the chart when a note is cut to one sentence.
       && /\$\(id\)\.textContent = first \+ \(chance \? ' ' \+ CHANCE : ''\)/.test(page));
    ok('F3: good per hour online is said apart from When & where\'s good per hour waited',
       /When & where counts good per hour waited \(each \'\s*\+ '\s*gap capped at 10 min, none while carrying\)/.test(page)
       || /good per hour waited \(each/.test(page));
    ok('T1/T2/T7: a press redraws what reads it (ruler, By week, resize), "When to drive" first and the rest after a '
       + 'paint; the folded shape of offers only once open; the CSVs built on their own click',
       /all: \{ first: \['ruler', 'overview', 'week'\], rest: \['more'\] \}/.test(page)
       && /by: \{ first: \[\], rest: \['overtime', 'shape'\] \}/.test(page)
       && /\$\('trMore'\)\.addEventListener\('toggle'/.test(page) && /\$\('trOverTime'\)\.addEventListener\('toggle'/.test(page)
       && /draw\('ruler'\)/.test(page) && /draw\('by'\)/.test(page) && /draw\('resize'\)/.test(page)
       && /requestAnimationFrame\(function \(\) \{ setTimeout\(later, 0\); \}\)/.test(page)
       && /\$\('trShape'\)\.addEventListener\('toggle'/.test(page)
       && /if \(moreOpen\(\) && \$\('trShape'\)\.open\) drawShape\(\); else shapeDirty = true;/.test(page)
       && /\$\('trCsvDays'\)\.addEventListener\('click', csvClick\)/.test(page) && !/\n      csvs\(rows, per\);/.test(page));
    ok('T4/T6/T8: the periods worked out once per answer and by-day or by-week, widths read before any write, scroll '
       + 'reads after them, and no title on a day timeline\'s thin square',
       /function periodsOf\(by\)/.test(page) && /drawDaily\(pb\.keys, pb\.line\);/.test(page)
       && /function readWidths\(\)/.test(page) && /post\(function \(\) \{ openAtFirst/.test(page)
       && /tl\.by === 'day' \? '' : ' title="'/.test(page));
    ok('...the ruler offers 10, 20, 30 and 50, opens on 20, and says it is for reading only',
       /data-top="10"[\s\S]*data-top="20" aria-pressed="true"[\s\S]*data-top="30"[\s\S]*data-top="50"/.test(page)
       && /sets "good" on every chart here/.test(page)
       && /id="trRulerHint">Descriptive only — never moves your line\.</.test(page));
    // Round B, the UX review's cleanup, held on the page itself.
    var visible = page.replace(/<!--[\s\S]*?-->/g, '').replace(/\n\s*\/\/[^\n]*/g, '').replace(/\/\*[\s\S]*?\*\//g, '');
    eq('[round B] the one disclaimer: the tab says "never moves your line" once, and the dozen repeats are gone',
       [(visible.match(/never moves your line/g) || []).length,
        /Descriptive; it feeds nothing|What happened, not advice|accept line is not tuned to the|for reading, not a rule\.'\);/.test(visible)],
       [1, false]);
    ok('[round B] D3: no Weekdays vs weekends button on Compare (the hour chart\'s chips set them side by side)',
       !/id="trCmpWk"/.test(page) && !/trCmpWk/.test(page));
    ok('[round B] D4: the hour × date timeline folded, opening on Weeks; Months hidden until three months',
       /<button type="button" data-tl="week" aria-pressed="true">Weeks<\/button>/.test(page)
       && /data-tl="month" aria-pressed="false" hidden>Months/.test(page) && /tl: 'week'/.test(page)
       && /querySelector\('button\[data-tl="month"\]'\)\.hidden = !rv\.tlMonths/.test(page));
    ok('[round B] D5/D6: days of the month, one weekday and this month vs last hidden until the record can hold them',
       /\$\('trThirdsBox'\)\.hidden = !rv\.thirds/.test(page) && /b\.hidden = !rv\.sameDow\[/.test(page)
       && /\$\('trMonths'\)\.hidden = !rv\.monthVsLast/.test(page) && /id="trMonths" hidden>/.test(page));
    ok('[round B] C2/C3/J1: the chips say what they change, the hour chart\'s line is the panel target (not Good), '
       + 'plain words for the figures', /panel target ' \+ FMT\.perHour\(got\.target\) \+ ' \(not Good\)'/.test(page)
       && /data-stat="p50" aria-pressed="true">Typical \$\/hr</.test(page) && />Top quarter</.test(page)
       && />Top tenth</.test(page) && /Group these charts:/.test(page));
    ok('[round B] D2: each day draws its top tenth beside the typical and the middle half',
       /e\.metrics\[m\]\.p90; \}\), cls: 'p90' \}/.test(page));
    ok('[round B] L1: the bottom line points to the places report\'s When & where, by /api/placeslink',
       /id="trToWw" href="places\/#whenwhere"/.test(page) && /\$\('trToWw'\)\.setAttribute\('href', base \+ '#whenwhere'\)/.test(page));
    ok('[round B] Where reads the offers the list already holds (an event), never a second fetch, and /api/trends '
       + 'stays without places', /CustomEvent\('offers:held'/.test(page) && /addEventListener\('offers:held'/.test(page)
       && /T\.towns\(held\.offers/.test(page));
  } finally { full.proc.kill(); }
  var lite = await serve(true);
  try {
    var la = await get(lite.port, '/api/trends?days=30');
    eq('a lite rig refuses /api/trends in lite\'s own words', [la.status, JSON.parse(la.body).lite], [404, true]);
    var ls = await get(lite.port, '/api/specialdays');
    eq('[special days] a lite rig refuses them in lite\'s own words (GET and POST alike: a path, not a method)',
       [ls.status, JSON.parse(ls.body).lite], [404, true]);
  } finally { lite.proc.kill(); }
  fs.rmSync(dir, { recursive: true, force: true });

  console.log(fail ? '\n' + pass + ' passed, ' + fail + ' FAILED' : '\nAll ' + pass + ' trends checks passed');
  process.exitCode = fail ? 1 : 0;
}()).catch(function (e) {
  console.log('FAIL  the suite threw: ' + (e && e.stack || e));
  process.exitCode = 1;
});
