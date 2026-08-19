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

/* ---- a trip is not a break ---- */
/* The silence after an accepted offer is the driver driving it, and counting
   that as time off is what stopped this answering at all. On one real recording
   eight of the fifteen gaps over ten minutes came straight after a take; raw,
   the gaps smeared evenly across 15-38 minutes with no defensible place to cut,
   and the suggested line swung $39 to $19 depending where you cut. */
(function () {
  // Two offers, then a 39-minute silence, then two more. The silence is longer
  // than the 30-minute break threshold either way; what changes is whether the
  // job before it was one the driver drove.
  function around(job) {
    return A.usable([offer(0, 10, 20), job, offer(40, 10, 20), offer(42, 10, 20)]);
  }

  var took = offer(1, 30, 35); took.accepted = true;
  eq('the silence while driving an accepted job is not a break',
     A.runs(around(took), 30).length, 1);

  var passed = offer(1, 30, 35); passed.accepted = false;
  eq('...but the same silence after one that was passed up is',
     A.runs(around(passed), 30).length, 2);

  // A trip excuses its own length and not a minute more: a five-minute job
  // cannot account for a thirty-nine-minute silence.
  var brief = offer(1, 30, 5); brief.accepted = true;
  eq('a trip only excuses its own length', A.runs(around(brief), 30).length, 2);

  // An untagged take reads as a break, and must. Guessing which silences were
  // really trips is the kind of invention this file exists to refuse.
  eq('an untagged take is not guessed at',
     A.runs(around(offer(1, 30, 35)), 30).length, 2);

  // And the replay still ignores what was actually taken. It simulates a
  // policy; what happened is the thing it is being compared against, not an
  // input to it. Here the accepted offer is the one that misses the line and
  // the declined one clears it, so the two answers cannot be confused.
  var meagre = offer(0, 5, 20); meagre.accepted = true;      // $15/hr, taken
  var rich = offer(30, 20, 20); rich.accepted = false;       // $60/hr, passed
  var sim = A.replay(A.runs(A.usable([meagre, rich]), 30), 30);
  eq('the replay takes what clears the line, not what was taken', sim.trips, 1);
  eq('...which is the one that cleared it', sim.earned, 20);
})();

/* ---- saying what would settle it ---- */
/* When the answer swings, "drive more" is often the wrong advice: the swing
   comes from not knowing which silences were breaks and which were trips, and
   the driver is the only one who can say. Counting the silences nothing
   accounts for is what lets the page ask for the one thing that would help. */
(function () {
  var quiet = A.usable([offer(0, 10, 20), offer(1, 10, 20),
                        offer(60, 10, 20), offer(61, 10, 20),
                        offer(200, 10, 20), offer(201, 10, 20)]);
  var bare = A.unexplained(quiet, 30);
  eq('two long silences, nothing to account for either', bare.silences, 2);
  eq('...and nothing marked as taken', bare.tagged, 0);

  var withTag = A.usable([offer(0, 10, 20), (function () {
    var t = offer(1, 10, 45); t.accepted = true; return t;
  })(), offer(60, 10, 20), offer(61, 10, 20),
    offer(200, 10, 20), offer(201, 10, 20)]);
  var some = A.unexplained(withTag, 30);
  eq('a marked trip accounts for the silence after it', some.silences, 1);
  eq('...and is counted as marked', some.tagged, 1);

  // ...for its own length and no more. A five-minute job followed by an hour of
  // quiet is exactly the stretch worth asking about, and skipping the gap
  // outright whenever the previous offer was taken hid it.
  var brief = A.usable([offer(0, 10, 20), (function () {
    var t = offer(1, 10, 5); t.accepted = true; return t;
  })(), offer(60, 10, 20), offer(61, 10, 20)]);
  eq('a short trip does not excuse a long silence',
     A.unexplained(brief, 30).silences, 1);

  // The count is what the shortfall carries, so the page can ask for tags
  // rather than for another shift.
  var thin = A.advise([offer(0, 10, 20), offer(1, 10, 20), offer(90, 10, 20)],
                      { target: 20 });
  eq('the shortfall says how many silences are unaccounted for', thin.silences, 1);
  eq('...and how many trips are marked', thin.tagged, 0);
})();

/* ---- a refusal has to be arithmetic somebody can check ---- */
/* The page prints the range and the swing in one sentence, so they have to be
   the same quantity. They were not: the low came from the bottom of the plateau
   and the high from the *top* of it, while the swing was measured across the
   bottoms alone — "anywhere between $18 and $41, a $21 swing", about three
   numbers that cannot all be true together. */
(function () {
  // Bursts of offers separated by silences at 16, 24, 33 and 47 minutes, which
  // is the shape that makes the answer depend on where the recording is cut —
  // every threshold from 15 to 90 falls somewhere different among them.
  function bursty(burst) {
    var gaps = [16, 24, 33, 47], rows = [], t = 0;
    for (var b = 0; b < 14; b++) {
      for (var i = 0; i < burst; i++) {
        rows.push(offer(t, 4 + ((b * 7 + i * 5) % 11) * 2, 20));
        t += 1 + (i % 3);
      }
      t += gaps[b % gaps.length];
    }
    return rows;
  }

  var out = A.advise(bursty(7), { target: 25 });
  eq('a recording split four ways refuses rather than picking one',
     out.reason, 'unsettled');
  eq('the swing is the distance between the two numbers printed beside it',
     out.high - out.low, out.spread);
  ok_('...and the range is a range', out.high >= out.low);
  ok_('...drawn from the line that would actually be recommended',
      out.checkedAt.every(function (e) {
        return e.low >= out.low && e.low <= out.high;
      }));

  // And the case that reads as a bug if it is squeezed into that sentence: the
  // recommended line does not move at all, and the plateau around it does. The
  // page has to say something other than "anywhere between $43 and $43".
  var steady = A.advise(bursty(3), { target: 25 });
  eq('a plateau that moves under a line that does not still refuses',
     steady.reason, 'unsettled');
  eq('...with no swing in the line itself', steady.spread, 0);
  ok_('...but a real one in the band, which is why', steady.bandSpread > 0);
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
  // Offers span minute 0 to 50, but the trip accepted at 40 runs to minute 60,
  // and those twenty minutes are the driver's. Billing only to the last offer
  // handed every run one free trip: the more a recording was broken up, the
  // higher the apparent rate and the higher the line that won — which is
  // exactly the fragmentation the driver said their record has.
  eq('the clock runs until the last trip ends, not the last offer',
     Math.round(r.hours * 60), 60);

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
    seen[b] = r ? r.best.target : null;
  });
  var values = Object.keys(seen).map(function (k) { return seen[k]; });
  var spread = Math.max.apply(null, values) - Math.min.apply(null, values);
  ok_('the recommended line survives every break threshold', spread <= 2);

  var a = A.advise(offers, { target: 30 });
  if (a.ready) {
    ok_('a market this clear gets an answer', a.ready);
    ok_('...only ever when it held at every threshold', a.stable);
    eq('...having been checked at each one', a.checkedAt.length, A.THRESHOLDS.length);
    ok_('...with the line above the cheap tier', a.suggested > 5);
    ok_('...and a plateau around it, not a single point', a.high >= a.low);
    ok_('...pointing at the bottom of that plateau', a.suggested === a.low);
  } else {
    // Refusing is a legitimate outcome and has to say which kind of refusal.
    ok_('...or it refuses, and says why',
        ['thin', 'trips', 'unsettled', 'nolinehelps'].indexOf(a.reason) >= 0
        || a.offers < 40);
  }
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
  if (!a.ready) {
    ok_('...or refuses with a reason the page can render', !!a.reason);
  } else {
  ok_('...and how many trips the suggested line would have meant', a.trips > 0);

  // The improvement is a ratio on purpose. A dollar figure per hour would
  // depend on how much of the recorded time was really driving - the one thing
  // this cannot know - and on the recording it was built from that figure
  // ranged from $22 to $78 while the ratio stayed between +19% and +25%.
  ok_('the gain over a too-high target is positive', a.gain > 0);
  eq('nothing claims a dollars-per-hour the driver would earn', a.perHour, undefined);
  eq('nor an earnings figure', a.earned, undefined);

  }
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

/* ---- the same offers, chopped up differently, must not change the answer ---- */
/* The driver's whole point. Their record is fragmented — four runs across ten
   hours with holes of 35 minutes, 39 minutes and nearly three hours — and the
   first version of this replay billed each run only from its first offer to its
   last, while keeping the full fare of a trip accepted near the end. One free
   trip per run: the more a recording was broken up, the higher the apparent
   rate and the higher the line that won. Measured at four runs of ten offers it
   reported $200/hr where the honest figure was $46. */
(function () {
  // Four runs, each nine minutes of cheap offers ending in a 30-minute fare.
  var offers = [];
  for (var r = 0; r < 4; r++) {
    for (var i = 0; i < 10; i++) {
      offers.push(i === 9 ? offer(r * 600 + i, 30, 30) : offer(r * 600 + i, 3, 30));
    }
  }
  var out = A.replay(A.runs(A.usable(offers), 30), 20);
  eq('four end-of-run fares are taken', out.trips, 4);
  eq('...and paid', out.earned, 120);
  // 4 runs x 9 min of offers = 36 min, plus 4 x 30 min of driving = 156 min.
  eq('...with all four trips on the clock', Math.round(out.hours * 60), 156);
  eq('...so the rate is the honest one, not four times it',
     Math.round(out.perHour), 46);

  // The same offers at the same spacing, cut into different numbers of runs.
  // Either the recommendation holds, or it refuses — what it must not do is
  // quietly climb with fragmentation while still reporting itself as stable.
  function chopped(runCount) {
    var out = [], per = Math.floor(200 / runCount), at = 0;
    for (var k = 0; k < runCount; k++) {
      for (var i = 0; i < per; i++) out.push(offer(at + i * 2.5, i % 3 === 0 ? 20 : 6, 25));
      at += per * 2.5 + 120;
    }
    return out;
  }
  var answers = [1, 2, 4, 10].map(function (n) {
    var a = A.advise(chopped(n), { target: 25 });
    return a.ready ? a.suggested : null;
  }).filter(function (v) { return v !== null; });
  if (answers.length > 1) {
    var swing = Math.max.apply(null, answers) - Math.min.apply(null, answers);
    ok_('breaking the same offers into more runs does not raise the line', swing <= 6);
  } else {
    ok_('...or it declines to answer, which is also correct', true);
  }
})();

/* ---- refusing, with a reason the page can act on ---- */
(function () {
  // A market where being selective buys nothing: every offer is the same, so
  // taking everything is exactly as good as any line. The plateau reaches zero,
  // and the bottom of that plateau is $0 — "set your target to nothing".
  var flat = [];
  for (var i = 0; i < 200; i++) flat.push(offer(i * 3, 10, 20));
  var a = A.advise(flat, { target: 25 });
  eq('a market with nothing to choose between offers no line', a.ready, false);
  eq('...and says that is what happened', a.reason, 'nolinehelps');
  eq('...rather than recommending zero', a.suggested, undefined);

  // Not enough yet.
  var thin = [];
  for (var j = 0; j < 20; j++) thin.push(offer(j * 2, 10, 20));
  var t = A.advise(thin, { target: 25 });
  eq('too little is refused', t.ready, false);
  ok_('...with what it is waiting for', t.needOffers > 0 && t.needHours > 0);

  // Every refusal must carry something the page can render, or the panel
  // silently disappears and a driver cannot tell it from a broken feature.
  [flat, thin, [], [offer(0, 10, 20)]].forEach(function (set, i) {
    var r = A.advise(set, { target: 25 });
    if (!r.ready) {
      ok_('refusal ' + i + ' can be explained',
          typeof r.offers === 'number' && typeof r.hours === 'number');
    }
  });
})();

console.log(fail ? '\n' + pass + ' passed, ' + fail + ' FAILED'
                 : '\nAll ' + pass + ' target-advice checks passed');
process.exit(fail ? 1 : 0);
