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
   calendar's week rows, and a looked-at cell that carries figures only. */

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
  eq('good per hour online: the day\'s good offers over its runs\' hours, a run across 4am credited to the day it began',
     [gp[0].key, gp[0].good, gp[0].hours, gp[0].rate, T.hoursBy(runs, 'day')['2026-03-02']], ['2026-03-02', 2, 4, 0.5, 4]);

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

  /* --- /api/trends, through a real server --- */
  var dir = fs.mkdtempSync(path.join(os.tmpdir(), 'trends-'));
  var journal = path.join(dir, 'journal.jsonl');
  var now = Date.now();
  var lines = [];
  for (var j = 0; j < 6000; j++) {
    var tj = now - 20 * 86400000 + j * 240000;
    lines.push(JSON.stringify({ v: 1, id: 'srv' + j, seq: 1, at: tj, pay: 9, minutes: 28, billedMinutes: 28,
                                miles: 8, perHour: 19, target: 25, band: 15, state: 'no', whole: true, app: 'uber',
                                lat: 12.3, lon: 45.6, gpsOk: true }));
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
    var takenAt = [];
    j1.rows.cols.flags.forEach(function (f, i) { if (f & T.F_TAKEN) takenAt.push(i); });
    var srvT = T.unpack(j1.rows).filter(function (r) { return r.taken; });
    eq('...a take reaches the tab as a bit, only for the driver\'s standing tick (not a pass, not a tick taken back)',
       [takenAt.length, srvT.length === 1 && srvT[0].t === Math.round((now - 20 * 86400000 + 10 * 240000) / 1000) * 1000],
       [1, true]);
    var withTop = JSON.parse((await get(full.port, '/api/trends?days=30&top=10')).body);
    eq('...and the server takes no ruler: the same answer whatever the page\'s choice, no cut in it',
       [Object.keys(withTop).sort(), withTop.total, JSON.stringify(withTop.rows) === JSON.stringify(j1.rows)],
       [['days', 'floor', 'ok', 'rows', 'runs', 'target', 'total'], 5999, true]);
    var j7 = JSON.parse((await get(full.port, '/api/trends?days=7')).body);
    var inSeven = 0;
    for (var j2 = 0; j2 < 6000; j2++) if (now - 20 * 86400000 + j2 * 240000 >= now - 7 * 86400000) inSeven += 1;
    ok('...the range is an honest span: 7 days holds the last 7 days\' offers (' + j7.total + ' of ' + inSeven + ')',
       Math.abs(j7.total - inSeven) <= 2);
    var page = (await get(full.port, '/journal.html')).body;
    ok('the offers page has the Trends tab, and loads trends.js only when it is opened',
       /data-view="trends"/.test(page) && !/<script src="trends\.js">/.test(page) && /s\.src = 'trends\.js'/.test(page));
    var order = ['trWhenHead', 'trTop', 'trStat', 'trGrid', 'trCell', 'trHourly', 'trCal', 'trGood', 'trChangeHead',
                 'trDaily', 'trSpread', 'trCompare', 'trShare', 'trShape', 'trMixMin', 'trScatter', 'trRate', 'trQuality',
                 'trCsvDays'].map(function (id) { return page.indexOf('id="' + id + '"'); });
    ok('the tab in three sections: when to drive (ruler, switch, grid, its cell, hours, calendar, good per hour), '
       + 'how it\'s changing, and the shape of offers folded away, CSVs last',
       order.every(function (x, i) { return x > 0 && (i === 0 || x > order[i - 1]); })
       && /<details class="trshape" id="trShape">/.test(page));
    ok('...the ruler offers 10, 20, 30 and 50, opens on 20, and says it is for reading only',
       /data-top="10"[\s\S]*data-top="20" aria-pressed="true"[\s\S]*data-top="30"[\s\S]*data-top="50"/.test(page)
       && /never\s+reaches the verdict/.test(page));
  } finally { full.proc.kill(); }
  var lite = await serve(true);
  try {
    var la = await get(lite.port, '/api/trends?days=30');
    eq('a lite rig refuses /api/trends in lite\'s own words', [la.status, JSON.parse(la.body).lite], [404, true]);
  } finally { lite.proc.kill(); }
  fs.rmSync(dir, { recursive: true, force: true });

  console.log(fail ? '\n' + pass + ' passed, ' + fail + ' FAILED' : '\nAll ' + pass + ' trends checks passed');
  process.exitCode = fail ? 1 : 0;
}()).catch(function (e) {
  console.log('FAIL  the suite threw: ' + (e && e.stack || e));
  process.exitCode = 1;
});
