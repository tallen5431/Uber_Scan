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

  /* The legacy shape, and the reason this exclusion exists.
   *
   * Until 19 August the threshold for distrusting a distance (MAX_MPH, 55) and
   * the one for calling a whole reading suspect (SANE_MPH, 75) were different
   * numbers reached by different reasoning in different parts of the parser.
   * A journey computing between the two — a real highway run, or a misread
   * landing in that band — was written distrusted, not suspect, and whole.
   * Nothing above catches any of that, and rate() charges no mileage on a
   * distance it does not trust, so the row's $/hr is a before-costs figure
   * sitting in a list of after-costs ones. They are still in the journal. */
  function legacyUncertain(pay, minutes, costPerMile, atMinutes) {
    return { at: 1000000000000 + (atMinutes || 0) * MIN,
             pay: pay, minutes: minutes, billedMinutes: minutes,
             cost: 0, costPerMile: costPerMile, milesUncertain: true,
             suspect: 0, whole: 1, hidden: 0 };
  }

  eq('a rate with no running cost taken off it is not evidence either',
     A.usable(good.concat([legacyUncertain(40, 20, 0.35)])).length,
     A.usable(good).length);
  ok_('...and the test would pass on the old rule too unless it is this shape',
      !legacyUncertain(40, 20, 0.35).suspect
      && legacyUncertain(40, 20, 0.35).whole === 1);

  // ...but only where a running cost is actually charged. At zero nothing was
  // ever deducted from anything, so this rate is not out of step with its
  // neighbours and dropping it would throw away a good offer for a difference
  // that does not exist.
  eq('a rig that charges no mileage keeps them',
     A.usable(good.concat([legacyUncertain(40, 20, 0)])).length,
     A.usable(good).length + 1);
  eq('...and so does one that never recorded a cost per mile',
     A.usable(good.concat([legacyUncertain(40, 20, undefined)])).length,
     A.usable(good).length + 1);

  /* The whole point, in the figures the page is actually read for.
   *
   * Honest offers: $10 over twenty minutes with $3 of car, so $21/hr net.
   * Legacy rows: $30 over the same twenty minutes with nothing deducted, so
   * $90/hr — the shape a highway run took before 19 August. Excluded, the
   * typical rate is the honest one; left in, the same page reports a market
   * that does not exist. The `before` list is the same rows with the guard
   * defeated, which is what the old code did with them.
   *
   * An even split, and deliberately so. A handful of these among a hundred
   * honest rows moves a median barely at all — that is what a median is for,
   * and it is why this went unnoticed. What is being checked here is that the
   * rows are capable of moving the figures, not a claim about how many of them
   * anybody's journal holds. The quartiles and the recommended line are where
   * even a few of them show up first. */
  var honest = [], legacy = [];
  for (var g = 0; g < 20; g++) honest.push(offer(g * 3, 10, 20, 3));
  // Arriving after the honest ones and at the same spacing, so they form part
  // of the same shift rather than a run the replay would drop for having no
  // length — which is what a shared timestamp would make them.
  for (var t = 0; t < 20; t++) legacy.push(legacyUncertain(30, 20, 0.35, 60 + t * 3));

  function typicalOf(rows) {
    var v = rows.map(function (r) { return r.perHour; })
                .sort(function (x, y) { return x - y; });
    return v.length ? v[Math.floor(v.length / 2)] : null;
  }

  var after = A.usable(honest.concat(legacy));
  // Defeating the guard the only way the module allows: say no cost was ever
  // charged. Same pay, same minutes, same missing deduction.
  var before = A.usable(honest.concat(legacy.map(function (r) {
    var copy = {}; for (var k in r) copy[k] = r[k];
    copy.costPerMile = 0;
    return copy;
  })));

  eq('the honest rows all survive', after.length, honest.length);
  eq('...and the legacy ones are what the difference is', before.length,
     honest.length + legacy.length);
  eq('the typical rate is the after-costs one', Math.round(typicalOf(after)), 21);
  ok_('...where leaving them in reported a market that does not exist ('
      + Math.round(typicalOf(before)) + '/hr)',
      typicalOf(before) > typicalOf(after) + 5);
  // The advice built on the same rows describes a different shift: twice the
  // offers, twice the hours, and a replay earning two and a half times as much
  // per hour from them. The recommended *line* happens not to move on this
  // fixture — the plateau covers the same range either way, which is the point
  // of reporting a plateau rather than a maximum — so the claim made here is
  // the one that is true rather than the one that sounds worst.
  var adviceAfter = A.bestAt(after, 30), adviceBefore = A.bestAt(before, 30);
  eq('the replay walks only the honest rows', adviceAfter.offers, honest.length);
  eq('...where it used to walk all of them', adviceBefore.offers,
     honest.length + legacy.length);
  ok_('...and credited itself two and a half times the hourly rate for it ($'
      + Math.round(adviceBefore.best.perHour) + ' against $'
      + Math.round(adviceAfter.best.perHour) + ')',
      adviceBefore.best.perHour > adviceAfter.best.perHour * 2);

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


/* --- two orders at once ---------------------------------------------------
 *
 * The arithmetic behind stacking, and — as much the point — the cases where it
 * has to refuse. This rig cannot see a map, so every claim it makes here has to
 * be true whatever the two routes turn out to look like.
 */
(function () {
  var SET = { target: 25, band: 15, costPerMile: 0.3 };
  var T0 = 1700000000000;
  function active(o) {
    return { pay: 12, minutes: 30, miles: 8, cost: 2.4, acceptedAt: T0,
             ...o };
  }
  function newOffer(o) { return { pay: 9, minutes: 20, miles: 6, cost: 1.8, ...o }; }

  // Ten minutes into a thirty-minute job: twenty left, two thirds of the fare
  // still to earn.
  var s = A.stack(active(), newOffer(), SET, T0 + 10 * 60000);
  ok_('a stack is worked out', !!s);
  eq('...with the right time left on the old order', s.leftMinutes, 20);
  // 12 - 2.4 = 9.60 net, two thirds of it = 6.40, plus 9 - 1.8 = 7.20.
  eq('...pro-rating the old order rather than counting it whole', s.pay, 13.6);
  eq('...worst case is the two times added', s.maxMinutes, 40);
  eq('...best case is the longer of the two', s.minMinutes, 20);
  eq('...and the worst rate divides by the worst time', s.worst, 20.4);
  eq('...the best rate by the best', s.best, 40.8);

  // The bound has to be a bound: nothing that could happen on any map may fall
  // outside it, and the order must never invert.
  ok_('the range is the right way round', s.best >= s.worst);
  ok_('...and the honest floor is the no-sharing case', s.worst <= s.best);

  // ACCEPT only when the WHOLE range clears the line. A range straddling the
  // target is a maybe, and a maybe drawn in green is a wrong answer.
  eq('a range straddling the target is not a green light', s.state, 'warn');
  eq('...it is green only when even the worst case clears it',
     A.stack(active(), newOffer({ pay: 30 }), SET, T0 + 10 * 60000).state, 'go');
  eq('...and red when even the best case does not',
     A.stack(active(), newOffer({ pay: 1, cost: 0 }), SET, T0 + 10 * 60000).state, 'no');

  // The claim that does not need the geography: better than just finishing,
  // even with nothing shared.
  ok_('a better-paying second job beats finishing alone',
      A.stack(active(), newOffer({ pay: 40, cost: 0 }), SET, T0 + 10 * 60000).sure);
  eq('...and a worse-paying one does not',
     A.stack(active(), newOffer({ pay: 1, cost: 0 }), SET, T0 + 10 * 60000).sure, false);

  // Refusals. Each of these would otherwise put a second job's time against a
  // first job's pay and call it a rate.
  eq('no active order, no stack', A.stack(null, newOffer(), SET, T0), null);
  eq('no offer, no stack', A.stack(active(), null, SET, T0), null);
  eq('an order already over is not stacked onto',
     A.stack(active(), newOffer(), SET, T0 + 31 * 60000), null);
  eq('...nor one that ends exactly now',
     A.stack(active(), newOffer(), SET, T0 + 30 * 60000), null);
  eq('an order with no stated time is not stacked onto',
     A.stack(active({ minutes: null }), newOffer(), SET, T0), null);
  eq('...nor an offer with none', A.stack(active(), newOffer({ minutes: null }), SET, T0), null);
  eq('an offer with no payout is not stacked',
     A.stack(active(), newOffer({ pay: null }), SET, T0), null);
  eq('a zero-length order is refused rather than divided by',
     A.stack(active({ minutes: 0 }), newOffer(), SET, T0), null);
  // ...and so is a zero-length OFFER, which is the same division one field
  // along. `null` was already refused above by the is-it-a-number test, so a
  // guard covering only null looks complete and divides by zero on a real 0.
  eq('a zero-length offer is refused too',
     A.stack(active(), newOffer({ minutes: 0 }), SET, T0), null);
  eq('...and a negative one, which no card states and OCR can still produce',
     A.stack(active(), newOffer({ minutes: -5 }), SET, T0), null);

  // No accept time is not the same as no order. A rig restarted mid-delivery
  // knows the order and not the clock, and the honest reading of that is that
  // none of it has run yet — which is the pessimistic one.
  var noClock = A.stack(active({ acceptedAt: null }), newOffer(), SET, T0 + 99 * 60000);
  ok_('an order with no start time is still stacked, from the top', !!noClock);
  eq('...with all of its minutes still ahead', noClock.leftMinutes, 30);

  // Costs come off both sides, or the stacked figure is gross while every other
  // number on the same screen is net.
  var free = A.stack(active({ cost: 0 }), newOffer({ cost: 0 }), SET, T0 + 10 * 60000);
  ok_('mileage is deducted from the pair', free.pay > s.pay);
})();

/* ---- where the two jobs end ---------------------------------------------
 *
 * Not a distance. The driver's ask was "close enough so that I don't take two
 * orders that end up in completely different places", so the only output that
 * matters is a veto, and it is deliberately asymmetric: a wrong "elsewhere"
 * costs a stack that could have been taken, a wrong "near" costs an hour and a
 * late delivery. All the addresses below are the driver's own, off real cards. */

eq('two dropoffs in the same town are near',
   A.sameArea('Park Pl, Atlanta', 'Cobalt Dr NW & Ember Ln NW, Atlanta'), 'near');
eq('...and in the same town and quadrant, still near',
   A.sameArea('Hamby Place Dr NW & Travistock Pl NW, Acworth',
              'Brookstone Walk NW & Downington Trl NW, Acworth'), 'near');
eq('a different town is somewhere else',
   A.sameArea('Hamby Place Dr NW & Travistock Pl NW, Acworth',
              'Lakeview Ter & Windmill Dr, Dallas'), 'elsewhere');
eq('...the twenty-mile pair the driver actually stacked',
   A.sameArea('Cochran Ridge Rd & Jewel Cole Rd, Hiram',
              'Chastain Meadows Pkwy NW, Marietta'), 'elsewhere');
eq('...and the same town on opposite sides of it is too',
   A.sameArea('Cobalt Dr NW & Ember Ln NW, Atlanta',
              'E Twin Oaks Dr SE & Spruce Dr, Smyrna'), 'elsewhere');

// Atlanta alone covers 250 of the 960 places the parser reads off these cards,
// so the town on its own is far too coarse. The quadrant is what splits it, and
// the split is real: the Atlanta dropoffs on file run NE 50, NW 20, SE 10, SW 5.
eq('the same town on opposite quadrants is somewhere else',
   A.sameArea('Cobalt Dr NW & Ember Ln NW, Atlanta',
              'Ormewood Ave SE & Woodland Ave SE, Atlanta'), 'elsewhere');
// A quadrant has to be a word of its own. 28 of the places on file contain an
// ALL-CAPS word - "HOME DEPOT 0156", "GOODFELLAS PIZZA & WINGS", "MIDTOWN" - and
// KENNESAW has an NE inside it. A town that shouts must not donate a compass
// point it never printed, or two dropoffs in the same town read as opposite
// sides of it.
eq('a capitalised town does not donate a quadrant',
   A.sameArea('HOME DEPOT 0156 I Stonewall Dr, KENNESAW',
              'Cobb Place Ln NW, Kennesaw'), 'near');

// OCR shouts: this driver's cards carry "COBB PKWY & MARS" and "shallowford rd".
// A town that came back in capitals is the same town.
eq('a town in capitals is the same town',
   A.sameArea('Cobb Pkwy NW, ACWORTH', 'Main St NW, Acworth'), 'near');

// Half of real pairs land here, and saying nothing is the answer they get.
eq('a dropoff the card did not name says nothing',
   A.sameArea('Luckie St NW & Spring St NW, Atlanta', null), null);
eq('...nor does a place with neither a town nor a quadrant',
   A.sameArea('Somewhere', 'Elsewhere'), null);
eq('a shared quadrant alone is a whole side of the metro, not a promise',
   A.sameArea('George Busbee Pkwy NW', 'Cobb Place Ln NW, Kennesaw'), null);

// The veto rides on stack(), which is what the driving screen reads.
var heldFar = { pay: 12, minutes: 30, cost: 1, acceptedAt: 0,
                dropoff: 'Cochran Ridge Rd & Jewel Cole Rd, Hiram' };
var offerFar = { pay: 10, minutes: 20, cost: 1,
                 dropoff: 'Chastain Meadows Pkwy NW, Marietta' };
var far = A.stack(heldFar, offerFar, { target: 25 }, 0);
eq('stack() reports where the pair ends', far.ends, 'elsewhere');
eq('...and still reports the money, which the geography only qualifies',
   typeof far.worst === 'number' && typeof far.best === 'number', true);
var near = A.stack(heldFar,
   { pay: 10, minutes: 20, cost: 1, dropoff: 'Jewel Cole Rd, Hiram' },
   { target: 25 }, 0);
eq('...and says so when they end in the same place', near.ends, 'near');
var blind = A.stack(heldFar, { pay: 10, minutes: 20, cost: 1 }, { target: 25 }, 0);
eq('...and says nothing when the second card named nowhere', blind.ends, null);

console.log(fail ? '\n' + pass + ' passed, ' + fail + ' FAILED'
                 : '\nAll ' + pass + ' target-advice checks passed');
process.exit(fail ? 1 : 0);
