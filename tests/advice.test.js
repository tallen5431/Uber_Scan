/* What line to draw. Run with: node tests/advice.test.js
 *
 * This is the one piece of the project that tells a driver what to do rather
 * than what something says, so the bar is different. A wrong verdict costs one
 * offer; a wrong target costs every offer for as long as it stands. The checks
 * below are therefore mostly about refusing to answer — on thin data, on a
 * market where nothing clears any line, on offers the reader itself does not
 * trust — because that is the failure that would do real damage.
 */

var A = require('../advice.js');

var pass = 0, fail = 0;

function eq(name, got, want) {
  var ok = got === want
    || (typeof got === 'number' && typeof want === 'number' && Math.abs(got - want) < 1e-6);
  if (ok) pass++;
  else { fail++; console.log('FAIL  ' + name + ': got ' + got + ' want ' + want); }
}

function ok_(name, cond) { eq(name, !!cond, true); }

var HOUR = 3600000;

/* An offer as the journal stores one. `cost` is what the car took, so
   pay - cost is what the driver keeps. */
function offer(at, pay, minutes, cost) {
  return { at: at, pay: pay, minutes: minutes, billedMinutes: minutes,
           cost: cost || 0, suspect: 0, whole: 1, hidden: 0 };
}

/* A market: `n` offers spread evenly over `hours`, paying `payFor(i)`. */
function market(n, hours, payFor, minutesFor) {
  var out = [], step = hours * HOUR / n;
  for (var i = 0; i < n; i++) {
    var mins = minutesFor ? minutesFor(i) : 30;
    out.push(offer(1000000 + i * step, payFor(i), mins, 0));
  }
  return out;
}

/* ---- hours watched, not hours elapsed ---- */
/* A shift that ran 6-9pm and again at 2am is five hours of driving inside an
   eight-hour span. Counting the span says the market is half as busy as it is,
   which makes waiting look cheap and pushes the recommended line up. */
(function () {
  var evening = [], night = [];
  for (var i = 0; i < 30; i++) evening.push(1000000 + i * (HOUR / 10));
  for (var j = 0; j < 20; j++) night.push(1000000 + 8 * HOUR + j * (HOUR / 10));
  eq('a continuous run is its own length',
     Math.round(A.watchedHours(evening) * 100) / 100, 2.9);
  var both = evening.concat(night);
  eq('a break in the middle is not counted as waiting',
     Math.round(A.watchedHours(both) * 100) / 100, 4.8);
  ok_('...which is far less than the span', A.watchedHours(both) < 8);
  eq('one offer is no time at all', A.watchedHours([5]), 0);
  eq('no offers is no time at all', A.watchedHours([]), 0);
  eq('order does not matter', A.watchedHours([300, 100, 200]),
     A.watchedHours([100, 200, 300]));
})();

/* ---- what a line earns ---- */
(function () {
  // Twelve offers an hour, every one paying $10 for 30 minutes. Taking all of
  // them: 5 minutes waiting, 30 driving, $10 a cycle -> $17.14/hr.
  var flat = market(24, 2, function () { return 10; });
  var rows = A.usable(flat);
  var all = A.earnedAt(rows, 0, 12);
  eq('taking everything takes everything', all.takes, 1);
  eq('...and earns pay over wait plus trip', Math.round(all.earned * 100) / 100, 17.14);
  eq('...waiting five minutes each time', Math.round(all.waitMinutes), 5);

  // Nothing clears a line above what anything pays. That is not $0/hr, it is
  // not a strategy, and saying zero would make it look like the worst option
  // rather than an impossible one.
  eq('a line nothing clears is not an answer', A.earnedAt(rows, 100, 12), null);
})();

/* ---- the shape of the trade ---- */
/* Half the offers pay $8 for 30 minutes, half pay $30 for 30 minutes, and they
   arrive 12 an hour. Holding out for the good half doubles the wait and nearly
   quadruples the pay, so the line belongs between the two. A recommendation
   above $30 or below $8 would mean the arithmetic is not trading at all. */
(function () {
  var mixed = market(120, 10, function (i) { return i % 2 ? 30 : 8; });
  var r = A.advise(mixed, { target: 25 });
  ok_('a clear two-tier market gets an answer', r.ready);
  ok_('...drawn between the two tiers', r.suggested > 8 && r.suggested <= 60);
  ok_('...and it beats taking everything',
      r.suggestedEarns.earned > A.earnedAt(A.usable(mixed), 0, r.offersPerHour / 2).earned);

  // The headline number to be sceptical of: the line is not the wage. Waiting
  // for $60/hr offers is how a driver earns $30.
  ok_('the line is below the rate it produces', r.suggested < r.suggestedEarns.earned * 3);
})();

/* ---- it must refuse, far more often than it answers ---- */
(function () {
  eq('one afternoon is not a season', A.advise(market(20, 1, function () { return 10; })).ready, false);
  eq('nothing at all is not an answer', A.advise([]).ready, false);
  eq('undefined is not an answer', A.advise(undefined).ready, false);

  var thin = A.advise(market(20, 1, function () { return 10; }));
  ok_('...and says what it is short of', thin.needOffers > 0 && thin.needHours > 0);
  eq('...and how far along it is', thin.offers, 20);

  // Plenty of offers, but all inside twenty minutes: a rig left running against
  // a screenshot, not a shift. The arrival rate from that is enormous and would
  // make waiting look free.
  var burst = market(100, 0.3, function () { return 10; });
  eq('a hundred offers in twenty minutes is not two hours of driving',
     A.advise(burst).ready, false);
})();

/* ---- the rows a decision must not be built on ---- */
(function () {
  var good = market(100, 5, function () { return 10; });

  // A card read as $1184 for a twenty-minute ride would, left in, drag the
  // recommended line above anything real and empty the shift.
  var withJunk = good.concat([
    { at: 1000000, pay: 1184, minutes: 20, billedMinutes: 20, cost: 0,
      suspect: 1, whole: 1, hidden: 0 }
  ]);
  eq('a misread offer is not evidence about the market',
     A.usable(withJunk).length, A.usable(good).length);

  // A card missing its pickup leg is the same pay over less time, so it always
  // reads better than it is.
  var withHalf = good.concat([
    { at: 1000000, pay: 40, minutes: 10, billedMinutes: 10, cost: 0,
      suspect: 0, whole: false, hidden: 0 }
  ]);
  eq('a half-read card is not evidence either',
     A.usable(withHalf).length, A.usable(good).length);

  // The test card a driver keeps presenting to check the rig still works.
  var withHidden = good.concat([
    { at: 1000000, pay: 99, minutes: 5, billedMinutes: 5, cost: 0,
      suspect: 0, whole: 1, hidden: 1 }
  ]);
  eq('a hidden offer stays out', A.usable(withHidden).length, A.usable(good).length);

  eq('and so does a row with no pay',
     A.usable([{ at: 1, pay: null, minutes: 20, cost: 0 }]).length, 0);
  eq('or no time', A.usable([{ at: 1, pay: 10, minutes: 0, cost: 0 }]).length, 0);
  eq('or no clock', A.usable([{ pay: 10, minutes: 20, cost: 0 }]).length, 0);
})();

/* ---- net, not gross ---- */
/* The target is a figure after running costs, so the comparison has to be too.
   Mixing them is how a recommendation stops meaning anything: at 30c a mile a
   long trip can look like the best offer of the day and be the worst. */
(function () {
  var rows = A.usable([offer(1, 20, 60, 12)]);
  eq('what the car took comes off first', rows[0].net, 8);
  eq('...before the rate is worked out', rows[0].perHour, 8);
})();

/* ---- the honest range ---- */
/* Some of the offers counted arrived while the driver was already carrying
   somebody. That cannot be measured here, and it runs one way: it makes the
   market look busier, waiting look cheaper, and the line look higher than it
   should be. So the recommendation is the cautious end, never the optimistic. */
(function () {
  var mixed = market(200, 10, function (i) { return i % 3 ? 8 : 26; });
  var r = A.advise(mixed, { target: 25 });
  ok_('both ends are reported', r.cautious && r.optimistic);
  ok_('the cautious end is never above the optimistic one',
      r.cautious.target <= r.optimistic.target);
  eq('and the suggestion is the cautious one', r.suggested,
     Math.min(r.cautious.target, r.optimistic.target));
  ok_('the range brackets the suggestion',
      r.range[0] <= r.suggested && r.suggested <= r.range[1]);

  // Judged on the same assumption, so the comparison the page shows is not one
  // number using a friendlier arrival rate than the other.
  var mine = A.advise(mixed, { target: 60 });
  ok_('an unreachable target earns less than the suggestion',
      !mine.current || mine.current.earned <= mine.suggestedEarns.earned);
})();

console.log(fail ? '\n' + pass + ' passed, ' + fail + ' FAILED'
                 : '\nAll ' + pass + ' target-advice checks passed');
process.exit(fail ? 1 : 0);
