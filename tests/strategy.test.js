/* What $/hr to expect, and what holding out for it was worth.
   Run with: node tests/strategy.test.js

   tools/strategy.js changes no verdict and never reaches the rig, so it is
   held where it could flatter: a curve whose best point is a thin tail, a
   free hour that was really an order in the car, a card read four times
   counted four times, a clock that stepped read as a long delivery, and a
   ratio that leaves the best-looking cards' optimism in.

   Every journal here is invented: cards from no real shop, on evenings in
   March 2026 that nobody drove, with no position anywhere. The curve's
   fixtures are built so that its answer is known before it runs; each is
   worked by hand in the comment above it. */

'use strict';

process.env.TZ = process.env.TZ || 'America/New_York';

var S = require('../tools/strategy.js');
var A = require('../advice.js');

var pass = 0, fail = 0;
function eq(name, got, want) {
  if (JSON.stringify(got) === JSON.stringify(want)) { pass += 1; return; }
  fail += 1;
  console.log('FAIL  ' + name + ': got ' + JSON.stringify(got) + ' want ' + JSON.stringify(want));
}
function ok(name, cond) { eq(name, !!cond, true); }
function near(name, got, want, tol) {
  ok(name + ' (got ' + got + ', want ' + want + ')', typeof got === 'number' && Math.abs(got - want) <= (tol || 0.005));
}

// Local ms on 2026-03-<day> at h:m:s, the driver's clock (EST: the clocks
// go forward on the 8th, after every evening here).
function at(day, h, m, s) { return new Date(2026, 2, day, h, m || 0, s || 0).getTime(); }

// A card the rig stands behind. perHour is the panel's: here no running cost,
// so it is pay over the card's minutes.
function card(id, when, pay, minutes, miles, extra) {
  var o = { id: id, at: when, pay: pay, minutes: minutes, miles: miles, perHour: pay / (minutes / 60),
            whole: true, app: 'uber' };
  Object.keys(extra || {}).forEach(function (k) { o[k] = extra[k]; });
  return o;
}

/* One evening, 18:00 to 19:30: fifty cards, evenly spaced, so the run is
 * exactly 1.5 hours and, with no order in the car, all of it free.
 *   30 at $12/hr  ($6.00, 30 min, 3 mi)
 *   15 at $24/hr  ($12.00, 30 min, 6 mi)
 *    5 at $36/hr  ($18.00, 30 min, 6 mi)
 * The kinds interleave so no hour holds one kind only. */
function evening(day, tag, t0h) {
  var out = [], kinds = [];
  for (var i = 0; i < 50; i++) kinds.push(i % 10 === 9 ? 36 : i % 10 >= 6 ? 24 : 12);
  var start = at(day, t0h || 18, 0);
  kinds.forEach(function (k, i) {
    var when = start + Math.round(i * (90 / 49) * 60000);
    if (k === 12) out.push(card(tag + i, when, 6, 30, 3));
    else if (k === 24) out.push(card(tag + i, when, 12, 30, 6));
    else out.push(card(tag + i, when, 18, 30, 6));
  });
  return out;
}

/* --- the curve, cards at their word (no timed orders) --------------------
 *
 * Two evenings: H = 3 free hours, 100 offers.
 *   T <= 12  N=100, P = 2 x (30x6 + 15x12 + 5x18) = 900, C = 3000 min:
 *            900 / (3 + 3000/60)            = 16.98
 *   12 < T <= 24  N=40, P=540, C=1200:  540 / (3 + 20) = 23.48
 *   24 < T <= 36  N=10 (thin, under 30): 180 / (3 + 5) = 22.50
 *   T > 36   none.
 * Best $14 (the first of the equal ones), flat from $14 to $24; $12 is 72%
 * of it, out. Taking everything = the T <= 12 figure. */
var two = evening(2, 'a').concat(evening(3, 'b'));
var r0 = S.analyse({ offers: two, orders: [] });
var P0 = {};
r0.curve.points.forEach(function (p) { P0[p.T] = p; });
eq('every card seen counted once, on two shift days', [r0.counts.offers, r0.counts.outings], [100, 2]);
near('the shift is the two runs, 1.5 h each', r0.counts.shiftHours, 3);
near('...and with no order in the car all of it is free', r0.counts.freeHours, 3);
near('offers per free hour', r0.seen.all.perFreeHour, 33.33);
near('the curve at $10: 900 / (3 + 50)', P0[10].gross, 16.98);
near('...at $12, the same set', P0[12].gross, 16.98);
near('...at $14: 540 / (3 + 20)', P0[14].gross, 23.48);
near('...at $24, still the same 40', P0[24].gross, 23.48);
near('...at $26: 180 / (3 + 5)', P0[26].gross, 22.5);
eq('...and that point is thin (10 offers, under the floor)', [P0[26].n, P0[26].thin], [10, true]);
eq('...past $36 nothing was seen, so no figure', [P0[38].n, P0[38].gross], [0, null]);
eq('the best line is the first of the equal non-thin ones', [r0.curve.best.T, r0.curve.best.value, r0.curve.best.n], [14, 23.48, 40]);
eq('...and the flat region runs from $14 to $24 (not $12, at 72% of it; not the thin $26)',
   [r0.curve.best.from, r0.curve.best.to], [14, 24]);
near('taking everything is the $10 figure', r0.curve.everything.gross, 16.98);
eq('with no timed order the curve takes the cards at their word, and says so',
   [P0[14].ratio, P0[14].ratioFrom, r0.curve.ratioFrom], [1, 'card', 'card']);
eq('two shift days: a curve, but no resampled interval (it needs three)', [r0.curve.drawn, r0.curve.bestCi, r0.curve.boots],
   [true, null, 0]);
eq('...and no held-out check either', r0.heldOut, null);
ok('the summary says how far to trust it', r0.lines.some(function (l) { return /^How far to trust it: thin/.test(l); }));
ok('...and leads with what the offers looked like', /^What offers looked like: 100 offers on 2 shift days/.test(r0.lines[0]));

/* Quartiles: 60 at $12, 30 at $24, 10 at $36, type 7. P25 = P50 = 12;
 * P75 at rank 74.25, inside the $24s; P90 at 89.1: 24 + 0.1 x 12 = 25.2. */
eq('the panel $/hr\'s quartiles and P90 over every card seen', r0.seen.all.ph, { n: 100, p25: 12, p50: 12, p75: 24, p90: 25.2 });
eq('...and $/mi, pay over the card\'s miles: 2.00 for all but the $36s at 3.00 (P90 at rank 89.1: 2.1)',
   [r0.seen.all.pm.p50, r0.seen.all.pm.p90], [2, 2.1]);
eq('by block: every card in 6–9pm', r0.seen.byBlock.map(function (b) { return [b.name, b.n]; }), [['6–9pm', 100]]);
eq('by weekday and weekend: a Monday and a Tuesday', r0.seen.byWeek.map(function (b) { return [b.name, b.n]; }), [['weekday', 100]]);

/* --- the curve with measured time ----------------------------------------
 *
 * The same two evenings, and on each three orders back to back from the
 * last card (19:30, and a millisecond, so that card was seen free):
 * card 20 min, $10 (so $30/hr on the panel), 5 card miles; each really took
 * 30 min and the GPS 6 miles. Holds 19:30-21:00 extend the run and are cut
 * out of it whole, so free stays 3 h; the orders' own
 * cards are not in the offers, so nothing is added to λ.
 *   ratio = 6 x 30 / 6 x 20 = 1.5 for every line up to $30 (six orders at
 *   $30), carried from $30 past it; miles ratio 6/5 = 1.2.
 *   T <= 12        900 / (3 + 1.5 x 50) = 11.54
 *   12 < T <= 24   540 / (3 + 1.5 x 20) = 16.36
 *   24 < T <= 36   180 / (3 + 1.5 x 5)  = 17.14 (thin)
 * Net at $0.30/mi on card miles x 1.2:
 *   T <= 12  M = 420:  (900 - 0.36 x 420) / 78 = 9.60
 *   14..24   M = 240:  (540 - 0.36 x 240) / 33 = 13.75 */
function orders(day, tag) {
  var out = [];
  for (var k = 0; k < 3; k++) {
    var took = at(day, 19, 30) + 1 + k * 30 * 60000;
    out.push({ id: tag + 'o' + k, tookAt: took, endedAt: took + 30 * 60000, app: 'uber', pay: 10,
               cardMinutes: 20, cardMiles: 5, actualMinutes: 30, actualMiles: 6 });
  }
  return out;
}
var ords = orders(2, 'a').concat(orders(3, 'b'));
var r1 = S.analyse({ offers: two, orders: ords, costPerMile: 0.3, target: 25 });
var P1 = {};
r1.curve.points.forEach(function (p) { P1[p.T] = p; });
near('an order held back to back after the run joins it, and is cut out of free time', r1.counts.freeHours, 3);
near('...the shift now runs to the last order\'s end', r1.counts.shiftHours, 6);
eq('six timed orders', [r1.counts.timed, r1.actual.all.ratio, r1.actual.all.mileRatio], [6, 1.5, 1.2]);
near('measured time: $10 = 900 / (3 + 1.5 x 50)', P1[10].gross, 11.54);
near('...$14 = 540 / (3 + 1.5 x 20)', P1[14].gross, 16.36);
near('...$26 = 180 / (3 + 1.5 x 5)', P1[26].gross, 17.14);
eq('the ratio is measured up to the orders\' own $30 and carried past it',
   [P1[30].ratioFrom, P1[32].ratioFrom, P1[32].ratioAt, P1[32].ratio], ['measured', 'carried', 30, 1.5]);
near('net at $10: (900 - 0.30 x 1.2 x 420) / 78', P1[10].net, 9.6);
near('net at $14: (540 - 0.30 x 1.2 x 240) / 33', P1[14].net, 13.75, 0.006);
eq('the net curve\'s best is the same line here', [r1.curve.bestNet.T], [14]);
eq('the driver\'s $25 line is outside the flat region, above it', r1.curve.target, { T: 25, side: 'above' });
eq('a card\'s $/hr reads as card ÷ ratio: $30 cards made $20 actual', [r1.actual.all.cardPH, r1.actual.all.actualPH], [30, 20]);
var band30 = r1.actual.byRate.filter(function (g) { return g.name === '$30–40/hr'; })[0];
eq('...the $30-40 band says so: card ÷ ratio = 30 / 1.5', [band30.timed, band30.expected], [6, 20]);
eq('an order\'s card $/hr with no offer row to join is worked from its pay, and counted', r1.counts.rateFromPay, 6);
ok('the summary names the ratio and what a $25 card turns into',
   r1.lines.some(function (l) { return /ran 1\.50x the card's/.test(l) && /a \$25\/hr card about \$16\.67\/hr actual/.test(l); }));
ok('...the best line, its value and the flat region',
   r1.lines.some(function (l) { return /^Holding out for cards at \$14\+\/hr gave the best shift rate in your record: about \$16\.36\/hr/.test(l)
     && /Anything from \$14 to \$24 gives about the same/.test(l); }));
ok('...the net figure, labelled with the rate and the miles ratio',
   r1.lines.some(function (l) { return /^Net of running cost \(\$0\.30\/mi.*x 1\.20, your GPS ÷ card miles\): best at \$14\+/.test(l); }));
ok('...the driver\'s line', r1.lines.indexOf('Your line, $25, is above that range.') >= 0);
ok('...and that it changes nothing on the rig', /^Descriptive/.test(r1.lines[r1.lines.length - 1]));
ok('no line of it tells anyone what to do', r1.lines.every(function (l) { return !/\byou should\b|\bset your\b|\btake only\b/i.test(l); }));

/* --- what is not counted --------------------------------------------------- */

// A card read four times is one card, seen at its first reading.
var reads = [card('r1', at(4, 18, 0), 9, 30, 3), card('r1', at(4, 18, 0, 20), 10, 30, 3),
             card('r1', at(4, 18, 1), 10, 30, 3, { suspect: true }), card('r1', at(4, 18, 2), 10, 30, 3)];
var dd = S.dedupe(reads);
eq('four readings of one card are one, three folded', [dd.list.length, dd.duplicates], [1, 3]);
eq('...the newest reading the rig stands behind speaks for it, seen at the first',
   [dd.list[0].row.at, dd.list[0].seen], [at(4, 18, 2), at(4, 18, 0)]);
ok('...and a suspect reading never does', !dd.list[0].row.suspect);
eq('marks, drops and records are not offers', S.dedupe([{ kind: 'mark', id: 'x', at: 1 }, { kind: 'order', id: 'x', at: 2 }]).list.length, 0);

// An untrusted card is no evidence about pay, but says the rig was on.
var mixed = evening(5, 'm');
mixed[10] = Object.assign({}, mixed[10], { suspect: true });
mixed[20] = Object.assign({}, mixed[20], { whole: false });
mixed[30] = Object.assign({}, mixed[30], { hidden: true });
var rm = S.analyse({ offers: mixed, orders: [] });
eq('suspect, partial and hidden cards are left out of every figure', [rm.counts.offers, rm.counts.untrusted], [47, 3]);
near('...but the shift still runs from the first card to the last', rm.counts.shiftHours, 1.5);

// Offers seen with an order in the car, and add-on cards, are not a free
// driver's choices.
var busy = evening(6, 'h');
var hold = [{ id: 'held', tookAt: at(6, 18, 30), endedAt: at(6, 19, 0), pay: 8, cardMinutes: 25, cardMiles: 4 }];
busy.push(card('addon1', at(6, 18, 10), 4, 8, 1, { addon: true }));
var rb = S.analyse({ offers: busy, orders: hold });
near('half an hour held is cut out of the free time', rb.counts.freeHours, 1);
eq('...the cards seen during it are not in λ, nor the add-on card',
   [rb.counts.held, rb.counts.addOnCards, rb.counts.free, rb.counts.free + rb.counts.held + 1], [16, 1, 34, 51]);
eq('...and an order with no time measured is counted, not timed', [rb.counts.orders, rb.counts.unmeasured, rb.counts.timed], [1, 1, 0]);

// An order with no end is held for its card's minutes (the floor
// advice.js freeAgain calls a floor); one whose clock ran over four hours is
// held the same way and not timed.
eq('a Took with no end holds the car for the card\'s minutes', S.holdOf({ tookAt: 1000, cardMinutes: 20 }), [1000, 1000 + 20 * 60000]);
eq('...and a hold over HOLD_MAX_MIN is a clock that stepped: the card\'s minutes again',
   S.holdOf({ tookAt: 1000, endedAt: 1000 + 600 * 60000, cardMinutes: 20 }), [1000, 1000 + 20 * 60000]);
var odd = [
  { id: 'c1', tookAt: at(2, 19, 31), endedAt: at(2, 19, 31) + 600 * 60000, pay: 10, cardMinutes: 20, actualMinutes: 600 },
  { id: 'c2', tookAt: at(2, 19, 31), endedAt: at(2, 19, 35), pay: 10, cardMinutes: 20, actualMinutes: 4 },
  { id: 'c3', tookAt: at(2, 19, 31), endedAt: at(2, 20, 0), pay: 10, cardMinutes: 20, actualMinutes: 29, addon: true },
  { id: 'c4', tookAt: at(2, 19, 31), endedAt: at(2, 20, 0), pay: 10, cardMinutes: 20, actualMinutes: 29, clockStepped: true }];
var ro = S.analyse({ offers: two, orders: odd });
eq('a clock that stepped, a put-down at the pickup and an add-on are not timed, and each is counted',
   [ro.counts.timed, ro.counts.clock, ro.counts.tooSoon, ro.counts.addons], [0, 2, 1, 1]);

// A card alone in a silence has no shift around it.
var lonely = evening(7, 'l').concat([card('alone', at(7, 23, 0), 20, 30, 5)]);
var rl = S.analyse({ offers: lonely, orders: [] });
eq('a card alone in an hour\'s silence is no part of a shift and not in λ', [rl.counts.alone, rl.counts.free], [1, 50]);
near('...and adds no hours', rl.counts.shiftHours, 1.5);

// A clock stepping forward leaves a silence: two runs, no idle hours across it.
var stepped = evening(9, 's');
stepped = stepped.slice(0, 25).concat(stepped.slice(25).map(function (o) { return Object.assign({}, o, { at: o.at + 3 * 3600000 }); }));
var rs = S.analyse({ offers: stepped, orders: [] });
ok('a clock that steps forward splits the run: the step is not free time (' + rs.counts.shiftHours + ' h)',
   rs.counts.shiftHours < 1.5);

/* --- free time by the hour -------------------------------------------------- */

var pcs = S.hourPieces([[at(2, 20, 30), at(2, 22, 15)]]);
eq('free time is cut at each local hour, each piece to its block',
   pcs.map(function (p) { return [new Date(p.from).getHours(), (p.to - p.from) / 60000, p.block]; }),
   [[20, 30, 6], [21, 60, 7], [22, 15, 7]]);
var late = S.hourPieces([[at(3, 3, 30), at(3, 4, 30)]]);
eq('...and to its shift day: 3:30am is the day before\'s, 4:00 the new day\'s',
   late.map(function (p) { return p.outing; }), ['2026-03-02', '2026-03-03']);
eq('weekend is a Saturday or Sunday shift day; 1am Saturday is still Friday\'s',
   [S.weekOf(at(6, 23, 0)), S.weekOf(at(7, 1, 0)), S.weekOf(at(7, 18, 0)), S.weekOf(at(9, 2, 0))],
   ['weekday', 'weekday', 'weekend', 'weekend']);
eq('runs join across a silence up to the break, not past it',
   S.mergeRuns([[0, 0], [S.BREAK_MIN * 60000, S.BREAK_MIN * 60000], [3 * S.BREAK_MIN * 60000, 3 * S.BREAK_MIN * 60000]],
               S.BREAK_MIN * 60000).length, 2);
eq('free is the runs less the holds', S.subtract([[0, 100]], [[10, 20], [50, 60]]), [[0, 10], [20, 50], [60, 100]]);

/* --- resampling and the held-out check -------------------------------------
 *
 * Three identical evenings: every resample is the same three, so the
 * interval is the point itself.
 *
 * Then two blocks a night, on three identical nights, the held-out check by
 * hand (fitted on two nights, scored on the third; every night the same):
 *   block A, 18:00-19:30: the evening above. Its own best on two nights is
 *   $14 (23.48); $26 there is thin (10 offers).
 *   block B, 21:00-22:30: 30 at $12 ($6, 30 min) and 30 at $30 ($15, 30 min).
 *   Best $14 (900 / 33 = 27.27 on two nights).
 *   One line for both on two nights: $14 -> 1440 / 56 = 25.71; $26 -> 70
 *   offers, 1080 / 41 = 26.34: best $26.
 *   Scored on the night left out:
 *     one line ($26): A 90 / (1.5 + 2.5) and B 450 / (1.5 + 15): 540 / 20.5 = 26.34
 *     per block ($14, $14): A 270 / 11.5 and B 450 / 16.5: 720 / 28 = 25.71
 *     everything: (450 + 630) / (3 + 55) = 18.62 */
var three = evening(2, 'a').concat(evening(3, 'b'), evening(4, 'c'));
var r3 = S.analyse({ offers: three, orders: [], boots: 50 });
eq('three identical evenings: every resample is the same, so the interval is the point',
   [r3.curve.bestCi, r3.curve.bestRange, r3.curve.boots], [[23.48, 23.48], [14, 14], 50]);
function nightB(day, tag) {
  var out = [], start = at(day, 21, 0);
  for (var i = 0; i < 60; i++) {
    var when = start + Math.round(i * (90 / 59) * 60000);
    out.push(i % 2 ? card(tag + i, when, 15, 30, 5) : card(tag + i, when, 6, 30, 3));
  }
  return out;
}
var nights = [];
[2, 3, 4].forEach(function (d) { nights = nights.concat(evening(d, 'A' + d), nightB(d, 'B' + d)); });
var rh = S.analyse({ offers: nights, orders: [], boots: 20 });
eq('held out a night at a time: one line $26.34, a line per block $25.71, everything $18.62',
   rh.heldOut, { days: 3, flat: 26.34, perBlock: 25.71, everything: 18.62 });
ok('...and the summary says a line per block did not beat one line out of sample',
   rh.lines.some(function (l) { return /a line per block made \$25\.71\/hr, one line for all hours \$26\.34\/hr/.test(l)
     && /did not beat one line out of sample/.test(l); }));
var blk = {};
rh.slices.block.forEach(function (b) { blk[b.name] = b; });
eq('each block\'s own curve: 6–9pm best $14, 9pm–12 best $14',
   [blk['6–9pm'].best.T, blk['6–9pm'].best.value, blk['9pm–12'].best.T, blk['9pm–12'].best.value], [14, 23.48, 14, 27.27]);
ok('...and each has its line in the summary', rh.lines.some(function (l) { return /^9pm–12: holding out for cards at \$14\+\/hr gave about \$27\.27\/hr on shift/.test(l); }));

/* --- by area and app --------------------------------------------------------- */

var towns = two.map(function (o, i) { return Object.assign({}, o, { app: i % 2 ? 'doordash' : 'uber' }); });
var ra = S.analyse({ offers: towns, orders: [], areaOf: function (o) { return /^a/.test(o.id) ? 'Faketown' : 'Nowhereville'; } });
eq('by town: each card\'s area, as the caller gives it, most offers first',
   ra.seen.byArea.map(function (x) { return [x.name, x.n]; }), [['Faketown', 50], ['Nowhereville', 50]]);
eq('...with no free hours of its own (nothing reads where the car stood)', ra.seen.byArea[0].perFreeHour, null);
eq('by app: the two share the free hours', ra.seen.byApp.map(function (x) { return [x.name, x.n, x.freeHours]; }),
   [['Uber', 50, 3], ['DoorDash', 50, 3]]);
eq('without an area function there is no area table', r0.seen.byArea, null);

// An empty window says one thing, not twenty.
eq('no offers: one line', S.analyse({ offers: [], orders: [] }).lines.length, 1);

/* --- the shared numbers -------------------------------------------------------- */

eq('the flat region is advice.js\'s plateau, read, not copied', S.PLATEAU, A.PLATEAU);
eq('a curve point\'s floor is advice.js\'s TARGET_OFFERS', S.CURVE_MIN_OFFERS, A.TARGET_OFFERS);
eq('a ratio\'s floor is advice.js\'s TARGET_TIMED', S.RATIO_MIN_N, A.TARGET_TIMED);
eq('the break that ends a run is advice.js\'s SHOWN_AT', S.BREAK_MIN, A.SHOWN_AT);
eq('the lines run $10 to $40 in $2 steps', [S.GRID[0], S.GRID[S.GRID.length - 1], S.GRID.length], [10, 40, 16]);

/* --- 5. card against what the app paid (8 Nov 2026) ------------------------------
 *
 * The owner: "compare what uber actually paid compared to the expected pay of
 * the order". /api/earnings' entries, in the writer's shape: six Uber trips
 * matched to orders, each card $7.00 and paid $9.00 (a $2.00 tip settled),
 * four from Pretend Pizza at 6:30 PM and two from Make-Believe Burgers at 1 PM;
 * one DoorDash trip matched, card $10.00, paid $8.00; one Uber trip matched
 * with its tip still processing; one waiting for the driver; one with no
 * order on file. Worked by hand: seven counted, cards $52.00, paid $62.00,
 * +$10.00 in all, the typical order +$2.00, $12.00 of settled tips. */
function earned(key, app, h, card, paid, tip, status, name) {
  return { kind: 'earning', key: key, at: 1, app: app, date: '2026-03-16',
           startedAt: (h < 10 ? '0' : '') + h + ':30', amount: paid, tip: tip,
           tipStatus: tip === 'processing' ? 'pending' : typeof tip === 'number' ? 'settled' : 'none',
           pickup: name ? { name: name } : null,
           match: status === 'matched' || status === 'picked'
             ? { status: status, offer: key, tookAt: 1, cardPay: card } : { status: status } };
}
var paidIn = [
  earned('p1', 'uber', 18, 7, 9, 2, 'matched', 'Pretend Pizza'),
  earned('p2', 'uber', 18, 7, 9, 2, 'matched', 'Pretend Pizza'),
  earned('p3', 'uber', 18, 7, 9, 2, 'picked', 'Pretend Pizza'),
  earned('p4', 'uber', 18, 7, 9, 2, 'matched', 'Pretend  pizza'),
  earned('b1', 'uber', 13, 7, 9, 2, 'matched', 'Make-Believe Burgers'),
  earned('b2', 'uber', 13, 7, 9, 2, 'matched', 'Make Believe Burgers'),
  earned('d1', 'doordash', 13, 10, 8, null, 'matched', 'Nowhere Noodles'),
  earned('w1', 'uber', 19, 6, 6, 'processing', 'matched', 'Pretend Pizza'),
  earned('n1', 'uber', 19, null, 5, null, 'needs', 'Imaginary Bistro'),
  earned('z1', 'uber', 20, null, 4, null, 'none', 'Imaginary Bistro')
];
var pv = S.cardVsPaid(paidIn);
var withCanceled = paidIn.concat([Object.assign(earned('c1', 'uber', 18, 9.5, 0, null, 'matched', 'Sample Sushi'),
                                                { status: 'canceled', canceledBy: 'you' })]);
var pvc = S.cardVsPaid(withCanceled);
eq('card vs paid: a trip canceled on the phone, matched to the order taken back, is counted and in no figure',
   [pvc.counts.canceled, pvc.all.n, pvc.all.card, pvc.all.paid], [1, 7, 52, 62]);
eq('card vs paid: the matched and settled are counted, the tip still processing left out and counted, '
   + 'the unmatched counted', [pv.all.n, pv.counts.pending, pv.counts.unmatched, pv.counts.entries], [7, 1, 2, 10]);
eq('...cards, paid, the difference in all and the typical order\'s, the settled tips, more and less',
   [pv.all.card, pv.all.paid, pv.all.diff, pv.all.medianDiff, pv.all.tips, pv.all.over, pv.all.under],
   [52, 62, 10, 2, 12, 6, 1]);
eq('...by app, each with its n, a group under the floor thin',
   pv.byApp.map(function (g) { return [g.name, g.n, g.diff, g.thin]; }),
   [['Uber', 6, 12, false], ['DoorDash', 1, -2, true]]);
eq('...by restaurant, named as first printed, grouped on its words, most orders first',
   pv.byRestaurant.map(function (g) { return [g.name, g.n, g.thin]; }),
   [['Pretend Pizza', 4, true], ['Make-Believe Burgers', 2, true], ['Nowhere Noodles', 1, true]]);
eq('...by three-hour block of the trip\'s end', pv.byBlock.map(function (g) { return [g.name, g.n]; }),
   [[A.BLOCK_NAMES[4], 3], [A.BLOCK_NAMES[6], 4]]);
eq('...the floor for a group', [pv.floor, S.PAID_MIN_N], [5, 5]);
var rp = S.analyse({ offers: two, orders: ords, costPerMile: 0.3, target: 25, earnings: paidIn });
var paidLine = rp.lines.filter(function (l) { return l.indexOf('Card against what the app paid') === 0; });
eq('the lines say it once, with n, the pending left out, each app\'s, and that no verdict reads it',
   paidLine, ['Card against what the app paid: over 7 matched orders (1 more with a tip still processing, left out), '
              + 'the app paid $62.00 against cards of $52.00 (+$10.00 in all, the typical order +$2.00; $12.00 of it '
              + 'settled tips; 6 paid more than the card, 1 less). By app: Uber +$12.00 over 6, DoorDash -$2.00 over 1 '
              + '(thin). Descriptive: no verdict reads it.']);
eq('...and name no restaurant (the end-of-shift report prints these lines, and names no place)',
   rp.lines.filter(function (l) { return /Pizza|Burgers|Noodles|Bistro/.test(l); }), []);
eq('...the rest of the answer as it was without earnings; and with none handed, no paid half and no line',
   [rp.curve.best, rp.lines.filter(function (l) { return paidLine.indexOf(l) === -1; }),
    S.analyse({ offers: two, orders: ords, costPerMile: 0.3, target: 25 }).paid],
   [r1.curve.best, r1.lines, undefined]);
eq('...and with earnings handed but no trip uploaded yet, no line',
   S.paidLines(S.cardVsPaid([])), []);

// Run as a child, it answers one JSON request with the same analysis.
var cp = require('child_process'), path = require('path');
var child = cp.spawnSync(process.execPath, [path.join(__dirname, '..', 'tools', 'strategy.js')],
                         { input: JSON.stringify({ offers: two, orders: ords, costPerMile: 0.3, target: 25 }), encoding: 'utf8' });
var got = null;
try { got = JSON.parse(child.stdout); } catch (e) { got = null; }
eq('run as a child, it gives the same answer as required', got && [got.curve.best, got.lines], [r1.curve.best, r1.lines]);
var bad = cp.spawnSync(process.execPath, [path.join(__dirname, '..', 'tools', 'strategy.js')], { input: 'not json', encoding: 'utf8' });
eq('...and refuses a request that is not JSON', [bad.status, /not JSON/.test(bad.stderr)], [2, true]);

console.log(fail ? '\n' + pass + ' passed, ' + fail + ' FAILED' : '\nAll ' + pass + ' strategy checks passed');
process.exitCode = fail ? 1 : 0;
