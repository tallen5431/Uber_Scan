/* tools/report_check.js: the reports checked against a journal, aggregates only.
   Run with: node tests/reportcheck.test.js

   Every journal here is invented: ids, text, places, coordinates and pay that
   never existed, and each of them looked for in what the tool prints — the
   one thing it must never do is hand back a place, a coordinate, a card's
   text, an id or one trip's amount. The figures are worked by hand: offers
   and days, the fixes, the cutoffs read the same both ways, hours online by
   the one rule, the takes by each view's rule with a Took taken back, the
   costs per mile and their dates, and a read the server cut. */

'use strict';

process.env.TZ = process.env.TZ || 'America/New_York';

var T = require('../trends.js');
var RC = require('../tools/report_check.js');

var pass = 0, fail = 0;
function eq(name, got, want) {
  if (JSON.stringify(got) === JSON.stringify(want)) { pass += 1; return; }
  fail += 1;
  console.log('FAIL  ' + name + ': got ' + JSON.stringify(got) + ' want ' + JSON.stringify(want));
}
function ok(name, cond) { eq(name, !!cond, true); }

// Three Tuesday and Thursday evenings in March 2026, 6 to 9pm, a card every
// 10 minutes; every fourth with a gated fix. Pay unique to the cent, so a
// single trip's amount can be looked for in the output.
function at(day, h, m) { return new Date(2026, 2, day, h, m || 0).getTime(); }
var offers = [], runs = [], k = 0;
[3, 5, 10, 12, 17, 19].forEach(function (d) {
  runs.push([at(d, 18), at(d, 20, 50)]);
  for (var i = 0; i < 18; i++, k++) {
    var o = { id: 'secret-card-' + k, at: at(d, 18, i * 10), pay: 6 + k * 0.17 + 0.03, minutes: 20, miles: 4,
              perHour: 10 + (k % 10) * 3, target: 25, app: k % 3 ? 'uber' : 'doordash', whole: true, state: 'no',
              text: 'Pickup Imaginary Grill 123 Mock Street Faketown', pickup: 'Imaginary Grill',
              costPerMile: d < 12 ? 0.3 : 0.35 };
    if (k % 4 === 0) { o.lat = 12.3456 + k / 1e4; o.lon = 45.6789 + k / 1e4; o.gpsOk = true; }
    if (k % 25 === 0) o.corrected = { from: 1.68, to: o.pay };
    if (k % 30 === 7) o.suspect = true;
    if (k === 20 || k === 50 || k === 80) o.accepted = true;     // a standing ✓
    offers.push(o);
  }
});
// Orders: the three ✓ also Took'd; one more Took on the offers page, taken back.
var taken = [20, 50, 80].map(function (x) {
  return { id: 'secret-card-' + x, tookAt: offers[x].at + 30000, endedAt: offers[x].at + 900000, by: 'gps' };
}).concat([{ id: 'secret-card-60', tookAt: offers[60].at + 30000, endedAt: offers[60].at + 60000, by: 'offers' }]);
var records = [20, 50, 80].map(function (x) {
  return { kind: 'order', id: 'order-' + x, offer: 'secret-card-' + x, how: 'gps', times: { took: offers[x].at + 30000 } };
}).concat([{ kind: 'order', id: 'order-60', offer: 'secret-card-60', how: 'offers', times: { took: offers[60].at + 30000 } }]);
var journal = { offers: offers, total: offers.length, count: offers.length, truncated: false, taken: taken, records: records };
var trends = { ok: true, rows: T.pack(T.rowsOf(offers)), costPerMile: 0.35,
               runs: runs.map(function (r) { return [r[0] / 1000, r[1] / 1000]; }) };

var res = RC.check(journal, trends, { now: 0, boots: 20 });
var text = RC.format(res);

eq('what was read: 108 offers on 6 driver days, 3 to 19 March, one page, not cut',
   [res.journal.offers, res.journal.driverDays, res.journal.first, res.journal.last, res.journal.pages, res.journal.truncated],
   [108, 6, '2026-03-03', '2026-03-19', 1, false]);
eq('...the Trends tab\'s rows the same offers (two suspect ones out of the money)',
   [res.trends.rows, res.trends.counted, res.trends.driverDays, res.trends.runs], [108, 104, 6, 6]);
eq('gps: every fourth card carries a gated fix, 27 of 108', [res.gps.fixed, res.gps.share], [27, 25]);
ok('the cutoffs, the Trends tab\'s and the places report\'s, are one figure over the same offers',
   res.cuts.length === 4 && res.cuts.every(function (c) { return c.trends === c.report && c.trendsN === c.reportN; }));
var gr = res.views.filter(function (v) { return v.figure === 'goodRate'; })[0];
ok('every Trends view is tallied for every figure, gross and net (six), cells at the floor never fewer than coloured',
   res.views.length === 6 && res.views.every(function (v) {
     return ['grid', 'calendarDays', 'calendarWeeks', 'timelineDay', 'timelineWeek', 'timelineMonth', 'thirds']
       .every(function (x) { return v[x] && v[x].enough >= v[x].above + v[x].below; });
   }) && gr.calendarDays.cells === 6);
eq('hours online by the slices: 6 evenings of 2 h 50 min, 17 h, the same total as by sittings',
   [res.hours.online, res.hours.sittings, res.hours.daysOnline], [17, 17, 6]);
eq('takes by each view\'s rule: the three ✓ with their Tooks agree, and the Took taken back is in none',
   [res.takes.total, res.takes.moneyRangeSummary, res.takes.disagree], [{ trends: 3, money: 3, section7: 3 }, 3, []]);
eq('costs per mile: $0.30 to the 10th, $0.35 from the 12th, each with its dates and count',
   res.costPerMile.seen.map(function (c) { return [c.value, c.offers, c.first, c.last]; }),
   [[0.3, 54, '2026-03-03', '2026-03-10'], [0.35, 54, '2026-03-12', '2026-03-19']]);
eq('the pay as marked: 5 re-read, 4 suspect, none unread, re-offered and raised not marked on the record',
   [res.pay.corrected, res.pay.suspect, res.pay.payUnread, res.pay.marked], [5, 4, 0, { reoffered: false, raised: false }]);
ok('the main computations are timed', res.times.length > 20 && res.times.every(function (x) { return x.ms >= 0; }));

// Never a place, a coordinate, a card's text, an id or a single trip's amount.
var json = JSON.stringify(res);
var leaks = [];
[text, json].forEach(function (s, which) {
  if (/secret-card|order-\d/.test(s)) leaks.push(which + ': an id');
  if (/Imaginary|Mock Street|Faketown|Pickup/.test(s)) leaks.push(which + ': text or a place');
  if (/12\.3[0-9]{2}|45\.6[0-9]{2}/.test(s)) leaks.push(which + ': a coordinate');
  offers.forEach(function (o) {
    var p = o.pay.toFixed(2);
    if (s.indexOf('$' + p) >= 0 || s.indexOf(':' + p + ',') >= 0) leaks.push(which + ': a pay ' + p);
  });
});
eq('[privacy] nothing printed or in --json is an id, a text, a place, a coordinate or one trip\'s pay', leaks, []);

// Which half of the re-offered rule marked what (the first real run marked
// more than expected). Invented: one order offered again 5 min later, same route, pay up;
// two different orders from one grill to one town 10 min apart, the miles
// far apart; one card that left the screen and came back, alone.
function ro(id, min, pay, miles, minutes, drop, extra) {
  return Object.assign({ id: id, at: at(24, 18, min), pay: pay, miles: miles, minutes: minutes, app: 'uber',
                         pickup: 'Imaginary Grill', dropoff: drop, reoffered: true, perHour: 20 }, extra || {});
}
var roOffers = [
  ro('secret-ro-1', 0, 7.13, 4.1, 18, 'Faketown'), ro('secret-ro-2', 5, 9.47, 4.2, 19, 'Faketown'),
  ro('secret-ro-3', 40, 8.21, 3.0, 15, 'Mocksville'), ro('secret-ro-4', 50, 8.19, 7.4, 27, 'Mocksville'),
  ro('secret-ro-5', 90, 11.37, 5.0, 20, 'Elsewhere Plaza'),
  ro('secret-ro-6', 95, 12.53, 5.0, 20, 'Not Again Lane', { reoffered: undefined })
];
var roRes = RC.check({ offers: roOffers, total: 6, truncated: false, taken: [], records: [] },
                     { ok: true, rows: T.pack(T.rowsOf(roOffers)), costPerMile: 0.3, runs: [] },
                     { now: at(30, 12), boots: 20 });
var how = roRes.pay.reofferedHow;
eq('re-offered by: four in same-trip pairs, one by its id coming back alone',
   [how.marked, how.byPair, how.bySpanOnly], [5, 4, 1]);
eq('...the pairs: two keyed on a printed dropoff, one agreeing on miles and minutes, pay up once and down once, '
   + 'the median gap the shorter, 5 min',
   [how.pairs.total, how.pairs.named, how.pairs.sameBoth, how.pairs.payUp, how.pairs.paySame, how.pairs.payDown,
    how.pairs.gapMedianMin], [2, 2, 1, 1, 0, 1, 5]);
var roText = RC.format(roRes);
ok('...and said in the words, with how old the newest offer is (5 days: a stopped sync looks like no driving)',
   /re-offered by: same trip under two ids 4, one id back on screen only 1/.test(roText)
   && /agreeing on miles \(±0\.2\) and minutes \(±2\) 1 \(50%\)/.test(roText)
   && /newest:  5 days before today/.test(roText));
ok('[privacy] the breakdown names no place, id or pay',
   !/Imaginary|Faketown|Mocksville|Elsewhere|Not Again|secret-ro|7\.13|9\.47|8\.21|8\.19|11\.37/.test(roText + JSON.stringify(how)));
var srv = require('fs').readFileSync(require('path').join(__dirname, '..', 'server.js'), 'utf8');
var sw = /var REOFFER_WINDOW_MS = ([^;]+);/.exec(srv);
var sg = /var REOFFER_GAP_MS = ([^;]+);/.exec(srv);
eq('...and the gap', sg && sg[1].split('*').reduce(function (a, x) { return a * Number(x); }, 1), 60 * 1000);
eq('pairs by gap: both of the invented pairs a minute or more apart', [how.pairs.withinAMinute, how.pairs.apart], [0, 2]);
eq('the pair window is the server\'s own (server.js REOFFER_WINDOW_MS)', sw && sw[1].split('*').reduce(function (a, x) { return a * Number(x); }, 1), 30 * 60 * 1000);

// A read the server cut, through the tool's own fetch (a fake server).
(async function () {
  var fake = async function (u) {
    if (/\/api\/trends/.test(u)) return { ok: true, status: 200, body: trends };
    return { ok: true, status: 200, body: { offers: offers.slice(-50), total: 108, count: 50, truncated: true,
                                            taken: taken, records: records } };
  };
  var got = await RC.fetchAll('http://fake', null, fake);
  var cut = RC.check(got.journal, got.trends, { boots: 20 });
  ok('a server that will not page: the read is said CUT, 50 of 108, in the figures and the words',
     cut.journal.truncated && cut.journal.offers === 50 && cut.journal.total === 108
     && /CUT: the server would not page/.test(RC.format(cut)));
  eq('the arguments: one server (the NucBox\'s copy by default), --since as a date, --json',
     [RC.parseArgs([]).server, RC.parseArgs(['http://x:1', '--since', '2026-03-01', '--json'])],
     ['http://localhost:8082', { server: 'http://x:1', since: '2026-03-01', json: true }]);
  var threw = null;
  try { RC.parseArgs(['--since', 'March']); } catch (e) { threw = e.message; }
  eq('...and refuses a date it cannot read', threw, '--since is YYYY-MM-DD');

  console.log(fail ? '\n' + pass + ' passed, ' + fail + ' FAILED' : '\nAll ' + pass + ' report-check checks passed');
  process.exitCode = fail ? 1 : 0;
}()).catch(function (e) {
  console.log('FAIL  the suite threw: ' + (e && e.stack || e));
  process.exitCode = 1;
});
