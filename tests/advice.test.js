/* What line to draw. Run with: node tests/advice.test.js
 *
 * This is the one piece of the project that tells a driver what to do rather
 * than what something says, so the bar is different. A wrong verdict costs one
 * offer; a wrong target costs every offer for as long as it stands.
 *
 * The first version of this estimated an arrival rate and did renewal-reward
 * arithmetic on it. It looked entirely reasonable and it was not: estimating a
 * rate means picking a number of minutes that separates "waiting" from "not
 * driving", and on one real recording the answer moved by a factor of three as
 * that constant went from 45 minutes to 5. So a good half of what is checked
 * here is that the answer does not depend on that constant — and that when it
 * does, nothing is claimed.
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

var MIN = 60000;

/* An offer as the journal stores one. `cost` is what the car took, so
   pay - cost is what the driver keeps. */
function offer(atMinutes, pay, minutes, cost) {
  return { at: 1000000000000 + atMinutes * MIN, pay: pay, minutes: minutes,
           billedMinutes: minutes, cost: cost || 0,
           suspect: 0, whole: 1, hidden: 0 };
}

/* ---- runs, not shifts ---- */
/* The driver's own words: "not all the time here is from one continuous shift".
   A recording is stretches of scanning separated by gaps, and a gap can be a
   break, a trip, or a rig left switched on in a driveway. */
(function () {
  var rows = A.usable([
    offer(0, 10, 20), offer(2, 10, 20), offer(4, 10, 20),
    // ...a two-hour hole...
    offer(124, 10, 20), offer(126, 10, 20)
  ]);
  eq('a gap longer than the threshold starts a new run', A.runs(rows, 30).length, 2);
  eq('...and a shorter one does not', A.runs(rows, 180).length, 1);

  // A run of one offer has no span. Counting it as an instant of driving would
  // divide earnings by nearly zero.
  var lonely = A.usable([offer(0, 10, 20), offer(600, 10, 20)]);
  eq('a single offer on its own is not a run', A.runs(lonely, 30).length, 0);
  eq('nothing at all is no runs', A.runs([], 30).length, 0);
})();

/* ---- the replay ---- */
(function () {
  // Six offers, ten minutes apart, each a 20-minute trip paying $10. Taking
  // everything: accept at 0, busy until 20, so the offers at 10 are skipped -
  // exactly what happens to an offer that arrives while you are driving.
  var rows = A.usable([offer(0, 10, 20), offer(10, 10, 20), offer(20, 10, 20),
                       offer(30, 10, 20), offer(40, 10, 20), offer(50, 10, 20)]);
  var r = A.replay(A.runs(rows, 30), 0);
  eq('an offer arriving mid-trip is not taken', r.trips, 3);
  eq('...and the ones that are, are', r.earned, 30);
  eq('the run is as long as it lasted', Math.round(r.hours * 60), 50);

  // A line nothing clears is a shift spent parked.
  eq('a line nothing clears takes nothing', A.replay(A.runs(rows, 30), 99).trips, 0);
  eq('...and earns nothing', A.replay(A.runs(rows, 30), 99).earned, 0);

  // Net, not gross. The target is a figure after running costs and mixing the
  // two is how a comparison stops meaning anything.
  var costly = A.usable([offer(0, 20, 60, 12)]);
  eq('what the car took comes off first', costly[0].net, 8);
  eq('...before the rate is worked out', costly[0].perHour, 8);
})();

/* ---- the whole point: the answer must not depend on the break threshold ---- */
/* A market where cheap offers are constant and good ones are occasional. The
   right line is somewhere above the cheap ones, and which minute-count is used
   to chop the recording into runs must not change that. */
(function () {
  var offers = [];
  for (var m = 0; m < 600; m += 3) {
    // every third offer is a good one; a 25-minute hole every 90 minutes, which
    // is exactly the length that different thresholds disagree about
    if (m % 90 > 64) continue;
    offers.push((m / 3) % 3 === 0 ? offer(m, 18, 30) : offer(m, 5, 30));
  }
  var seen = {};
  [15, 20, 30, 45, 60, 90].forEach(function (b) {
    var r = A.bestAt(A.usable(offers), b);
    seen[b] = r && r.best.target;
  });
  var values = Object.keys(seen).map(function (k) { return seen[k]; });
  var spread = Math.max.apply(null, values) - Math.min.apply(null, values);
  ok_('the recommended line survives every break threshold', spread <= 2);

  var a = A.advise(offers, { target: 30 });
  ok_('a market this clear gets an answer', a.ready);
  ok_('...and is reported as stable', a.stable);
  eq('...having been checked at every threshold', a.checkedAt.length, A.THRESHOLDS.length);
  ok_('...with the line between the two tiers',
      a.suggested > 10 && a.suggested < 36);
  ok_('...and a plateau around it, not a single point', a.high >= a.low);
  ok_('...pointing at the bottom of that plateau', a.suggested === a.low);
})();

/* ---- it must refuse, far more often than it answers ---- */
(function () {
  eq('nothing at all is not an answer', A.advise([]).ready, false);
  eq('undefined is not an answer', A.advise(undefined).ready, false);
  eq('null is not an answer', A.advise(null).ready, false);

  var thin = [];
  for (var i = 0; i < 20; i++) thin.push(offer(i * 2, 10, 20));
  eq('one afternoon is not a season', A.advise(thin).ready, false);
  eq('...and it says how far along it is', A.advise(thin).offers, 20);
  ok_('...and what it is waiting for', A.advise(thin).needOffers > 0);

  // Plenty of offers inside twenty minutes: a rig left running against a
  // screenshot, not a shift.
  var burst = [];
  for (var j = 0; j < 100; j++) burst.push(offer(j * 0.2, 10, 20));
  eq('a hundred offers in twenty minutes is not two hours of driving',
     A.advise(burst).ready, false);

  // Enough offers and enough hours, but the line only ever produces two or
  // three trips. That is a recommendation resting on three coincidences.
  var sparse = [];
  for (var k = 0; k < 60; k++) sparse.push(offer(k * 5, 6, 200));
  var s = A.advise(sparse, { target: 25 });
  ok_('a handful of trips is not a finding', !s.ready);
})();

/* ---- the rows a decision must not be built on ---- */
(function () {
  var good = [];
  for (var i = 0; i < 100; i++) good.push(offer(i * 3, 10, 20));

  // A card read as $1184 for a twenty-minute ride would, left in, drag the
  // recommended line above anything real and empty the shift.
  eq('a misread offer is not evidence about the market',
     A.usable(good.concat([{ at: 1, pay: 1184, minutes: 20, billedMinutes: 20,
                             cost: 0, suspect: 1, whole: 1, hidden: 0 }])).length,
     A.usable(good).length);

  // A card missing its pickup leg is the same pay over less time, so it always
  // reads better than it is.
  eq('a half-read card is not evidence either',
     A.usable(good.concat([{ at: 1, pay: 40, minutes: 10, billedMinutes: 10,
                             cost: 0, suspect: 0, whole: false, hidden: 0 }])).length,
     A.usable(good).length);

  // The test card a driver keeps presenting to check the rig still works.
  eq('a hidden offer stays out',
     A.usable(good.concat([{ at: 1, pay: 99, minutes: 5, billedMinutes: 5,
                             cost: 0, suspect: 0, whole: 1, hidden: 1 }])).length,
     A.usable(good).length);

  eq('and so does a row with no pay',
     A.usable([{ at: 1, pay: null, minutes: 20, cost: 0 }]).length, 0);
  eq('or no time', A.usable([{ at: 1, pay: 10, minutes: 0, cost: 0 }]).length, 0);
  eq('or no clock', A.usable([{ pay: 10, minutes: 20, cost: 0 }]).length, 0);
  eq('or a pay that is not a number',
     A.usable([{ at: 1, pay: Infinity, minutes: 20, cost: 0 }]).length, 0);
  eq('or a clock that is not a number',
     A.usable([{ at: NaN, pay: 10, minutes: 20, cost: 0 }]).length, 0);
  eq('or a cost that is not a number',
     A.usable([{ at: 1, pay: 10, minutes: 20, cost: NaN }])[0].net, 10);
  eq('a row that is not a row at all', A.usable([null, 7, 'x']).length, 0);
})();

/* ---- rows out of order ---- */
/* The journal is append-only and the web side appends to it too, so nothing
   guarantees the file is sorted. A replay walked out of order would take an
   offer, then take one that arrived before it finished. */
(function () {
  var forwards = [], backwards = [];
  for (var i = 0; i < 60; i++) forwards.push(offer(i * 3, 10, 20));
  for (var j = 59; j >= 0; j--) backwards.push(offer(j * 3, 10, 20));
  var a = A.replay(A.runs(A.usable(forwards), 30), 0);
  var b = A.replay(A.runs(A.usable(backwards), 30), 0);
  eq('a shuffled journal replays the same way', b.trips, a.trips);
  eq('...and earns the same', b.earned, a.earned);
})();

/* ---- what it claims, and what it declines to claim ---- */
(function () {
  var offers = [];
  for (var m = 0; m < 900; m += 4) {
    if (m % 120 > 90) continue;
    offers.push(m % 12 === 0 ? offer(m, 20, 30) : offer(m, 6, 30));
  }
  var a = A.advise(offers, { target: 10 });
  ok_('an answer knows how many separate runs it is built from', a.runs >= 1);
  ok_('...and over how long', a.hours > 0);
  ok_('...and how many trips the suggested line would have meant', a.trips > 0);

  // The improvement is a ratio on purpose. A dollar figure per hour would
  // depend on how much of the recorded time was really driving - the one thing
  // this cannot know - and on the recording it was built from that figure
  // ranged from $22 to $78 while the ratio stayed between +19% and +25%.
  ok_('the gain over a too-high target is positive', a.gain > 0);
  eq('nothing claims a dollars-per-hour the driver would earn', a.perHour, undefined);
  eq('nor an earnings figure', a.earned, undefined);

  // No current target given, nothing to compare against, so no claim.
  eq('with no target set there is no comparison',
     A.advise(offers).gain, null);

  // A line nothing clears is a shift spent parked. The ratio is undefined
  // because the denominator is a driver earning nothing, and reporting that as
  // "no comparison available" would bury the one case where the target is
  // doing visible harm.
  var parked = A.advise(offers, { target: 500 });
  eq('a target nothing clears takes nothing', parked.current.trips, 0);
  eq('...which is not a missing comparison', parked.currentTakesNothing, true);
  eq('...and not a ratio either', parked.gain, null);
  eq('a workable target is not flagged that way',
     A.advise(offers, { target: 10 }).currentTakesNothing, false);
})();

/* ---- when the thresholds disagree, say so ---- */
(function () {
  // A recording whose whole character changes with where it is cut: a dense
  // burst of poor offers, then long gaps around a few excellent ones.
  var offers = [];
  for (var i = 0; i < 90; i++) offers.push(offer(i * 1.5, 4, 25));
  for (var j = 0; j < 12; j++) offers.push(offer(200 + j * 37, 40, 25));
  var a = A.advise(offers, { target: 25 });
  if (a.ready) {
    ok_('a disagreement between thresholds is reported, not averaged away',
        typeof a.stable === 'boolean');
    ok_('...with the spread it saw', typeof a.spread === 'number');
    ok_('...and every threshold it asked at', a.checkedAt.length > 1);
  } else {
    ok_('...or nothing is claimed at all', true);
  }
})();

console.log(fail ? '\n' + pass + ' passed, ' + fail + ' FAILED'
                 : '\nAll ' + pass + ' target-advice checks passed');
process.exit(fail ? 1 : 0);
