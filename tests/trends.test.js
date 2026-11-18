/* The offers page's Trends tab: trends.js's sums, and /api/trends.
   Run with: node tests/trends.test.js

   Every journal here is invented: ids, times, pay and places that never
   existed. Held hardest where a trend could flatter or mislead — an offer
   counted once per reading instead of once, a pay the server corrected read
   at its first figure, a suspect or "pay unread" row in a median, a grid cell
   shaded by chance, a rate card that cannot recover a price it was built
   from, a server that caps the window or a lite rig that serves it. */

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
    var j7 = JSON.parse((await get(full.port, '/api/trends?days=7')).body);
    var inSeven = 0;
    for (var j2 = 0; j2 < 6000; j2++) if (now - 20 * 86400000 + j2 * 240000 >= now - 7 * 86400000) inSeven += 1;
    ok('...the range is an honest span: 7 days holds the last 7 days\' offers (' + j7.total + ' of ' + inSeven + ')',
       Math.abs(j7.total - inSeven) <= 2);
    var page = (await get(full.port, '/journal.html')).body;
    ok('the offers page has the Trends tab, and loads trends.js only when it is opened',
       /data-view="trends"/.test(page) && !/<script src="trends\.js">/.test(page) && /s\.src = 'trends\.js'/.test(page));
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
